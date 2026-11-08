"""Lost bindings: noticing them, and putting them back (1.3.0, reworked 1.8.0).

On by default ("Watch for lost bindings"). Bindings can vanish without anyone
noticing: a device is factory reset, re-paired, or loses its table after a
firmware update (IKEA remotes' bindings "seem to have a half-life", HarvsG).
A remote then just stops working. See the PRD "Lost Bindings and
Self-Healing".

- Expected bindings per device start from the card's scans. Every later
  read of the device, by the card (any scan), the nightly check or a check
  after a button press, is compared with them first. A binding missing from
  a successful read is *lost* straight away; it stays expected until it's
  put back or the user says it was removed on purpose. (Before 1.8.0 a card
  scan replaced the expected set, so a scan quietly accepted a loss.)
- Bindings removed through ZHA Bindings Manager are reported by the card
  (watch_removed) and simply leave the expected set.
- A device that doesn't answer never makes anything lost.
- Per device: off / notify (default) / auto. With auto, lost bindings are put
  back straight away, or on the device's next button press if it doesn't
  answer (battery remotes), at most AUTO_LIMIT times a day; a device that
  keeps losing them is paused and reported instead. Auto devices are also
  checked after a button press if not checked in the last 10 minutes.
- Every night at 03:17 each watched device is read; battery devices that
  don't answer are checked on their next button press after 20 hours.
- One Repairs issue for the whole network, linking to the card.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import storage
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_change

from .bindings import BindsGetFailed, describe_binding, identity_key, norm_ieee, relationship_map
from .const import DOMAIN, OPT_SIDEBAR_PANEL, PANEL_URL_PATH, SIGNAL_BINDINGS_UPDATED
from .options import current_options
from .device_bindings import DeviceBindings
from .fallback import Fallback

_LOGGER = logging.getLogger(__name__)

WATCH_STORAGE_KEY = f"{DOMAIN}/watch"
CHECK_HOUR, CHECK_MINUTE = 3, 17
DUE_AFTER = timedelta(hours=20)
PRESS_CHECK_GAP = timedelta(minutes=10)
AUTO_LIMIT = 3
AUTO_WINDOW = timedelta(hours=24)
PAUSE_BETWEEN_DEVICES = 2.0
POLICIES = ("off", "notify", "auto")
DEFAULT_POLICY = "notify"
ISSUE_ID = "lost_bindings"
OLD_ISSUE_PREFIX = "binding_missing_"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _older_than(iso: str | None, delta: timedelta) -> bool:
    if not iso:
        return True
    try:
        return _now() - datetime.fromisoformat(iso) >= delta
    except ValueError:
        return True



def key_matches(key: str, pattern: dict) -> bool:
    """Does an identity_key match a removal pattern (None/missing = any)?"""
    try:
        src, ep, cluster, target = key.split("|", 3)
        if src != norm_ieee(pattern.get("sourceIeee") or ""):
            return False
        if pattern.get("sourceEndpoint") is not None and str(pattern["sourceEndpoint"]) != ep:
            return False
        clusters = pattern.get("clusterIds")
        if clusters is None and pattern.get("clusterId") is not None:
            clusters = [pattern["clusterId"]]
        if clusters is not None and int(cluster) not in {int(c) for c in clusters}:
            return False
        if pattern.get("isGroup"):
            if not target.startswith("g:"):
                return False
            if pattern.get("groupId") is not None and target != f"g:{pattern['groupId']}":
                return False
        elif pattern.get("targetIeee") is not None:
            if not target.startswith("d:"):
                return False
            t_ieee, _sep, t_ep = target[2:].rpartition(":")
            if t_ieee != norm_ieee(pattern["targetIeee"]):
                return False
            if pattern.get("targetEndpoint") is not None and t_ep != str(pattern["targetEndpoint"]):
                return False
        elif pattern.get("isGroup") is False and not target.startswith("d:"):
            return False
        return True
    except (TypeError, ValueError, AttributeError):
        return False

def compare_read(expected: dict[str, dict], lost: dict[str, dict], present: dict[str, dict], how: str, at: str) -> tuple[dict, dict, list[str]]:
    """One successful read of a device's table, compared with what it should have.

    Returns (expected, lost, newly_lost_keys). Expected bindings absent from
    the read become lost (keeping their first "since"); bindings present are
    no longer lost; new bindings on the device join the expected set (bound
    elsewhere, e.g. Find & Bind)."""
    lost = {k: v for k, v in lost.items() if k in expected and k not in present}
    newly = [k for k in expected if k not in present and k not in lost]
    for k in newly:
        lost[k] = {"since": at, "noticed_by": how}
    return {**expected, **present}, lost, newly


class BindingWatch:
    def __init__(self, hass: HomeAssistant, data: DeviceBindings) -> None:
        self.hass = hass
        self.data = data
        self._store = storage.Store(hass, 1, WATCH_STORAGE_KEY)
        self.tracked: dict[str, dict[str, Any]] = {}
        self._busy: set[str] = set()
        self.pause = PAUSE_BETWEEN_DEVICES
        self.fallback = Fallback(hass, self)

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self.tracked = stored if isinstance(stored, dict) else {}
        for w in self.tracked.values():
            # From 1.3.0: a two-miss count. Misses become lost only after the
            # next successful read (no flood of "lost" on upgrade).
            w.pop("misses", None)
            w.setdefault("lost", {})
            w.setdefault("policy", DEFAULT_POLICY)
            w.setdefault("queued", False)
            w.setdefault("auto_history", [])
            w.setdefault("auto_paused", False)
            w.setdefault("fallback", False)
        # Per-device issues from before 1.8.0 are replaced by one issue.
        reg = ir.async_get(self.hass)
        for issue_id in [i for (d, i) in list(reg.issues) if d == DOMAIN and i.startswith(OLD_ISSUE_PREFIX)]:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self.data.extra_exposed = lambda: {i for i, w in self.tracked.items() if w.get("expected")}
        self.sync_from_card()
        await self.data.async_refresh()

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self.tracked, 1)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        unsubs = [
            async_dispatcher_connect(self.hass, SIGNAL_BINDINGS_UPDATED, self.sync_from_card),
            async_track_time_change(self.hass, self._nightly, hour=CHECK_HOUR, minute=CHECK_MINUTE, second=0),
            self.hass.bus.async_listen("zha_event", self._on_zha_event),
        ]

        def stop() -> None:
            for u in unsubs:
                u()

        return stop

    def _entry(self, ieee: str) -> dict[str, Any]:
        return self.tracked.setdefault(
            ieee,
            {"expected": {}, "lost": {}, "policy": DEFAULT_POLICY, "queued": False, "last_check": None, "auto_history": [], "auto_paused": False, "fallback": False},
        )

    # --- reads -------------------------------------------------------------------

    @callback
    def _apply_read(self, ieee: str, present: dict[str, dict], how: str, at: str | None = None) -> list[str]:
        """Compares one successful read with the expected set. Returns newly lost keys."""
        w = self._entry(ieee)
        if not w.get("expected"):
            w["expected"], w["lost"] = dict(present), {}
            return []
        if w.get("policy") == "off":
            w["expected"], w["lost"] = {**w["expected"], **present}, {}
            return []
        w["expected"], w["lost"], newly = compare_read(w["expected"], w.get("lost") or {}, present, how, at or _now().isoformat())
        if not w["lost"]:
            w["queued"] = False
        return newly

    @callback
    def sync_from_card(self) -> None:
        """The card read devices: compare each newer read before adopting it."""
        changed = False
        auto: list[str] = []
        for ieee, (read_at, lst) in self.data.card.items():
            w = self.tracked.get(ieee)
            if w is not None and read_at <= (w.get("card_at") or ""):
                continue
            present = relationship_map(lst, self.data.coordinator)
            if not present and w is None:
                continue
            newly = self._apply_read(ieee, present, "scan", read_at or None)
            self.tracked[ieee]["card_at"] = read_at
            changed = True
            if newly and self.tracked[ieee].get("policy") == "auto":
                auto.append(ieee)
        if changed:
            self._save()
            self._update_issue()
        for ieee in auto:
            self.hass.async_create_task(self._auto_put_back(ieee))

    @callback
    def removed_by_user(self, bindings: list[dict]) -> int:
        """Bindings the card removed on purpose: stop expecting them. Each
        item is a pattern: sourceIeee is required; sourceEndpoint,
        clusterId/clusterIds, isGroup+groupId and targetIeee/targetEndpoint
        narrow it down, and anything left out matches all. (If the unbind
        actually failed, the next read simply expects the binding again.)"""
        n = 0
        dirty = False
        for b in bindings or []:
            if not isinstance(b, dict):
                continue
            w = self.tracked.get(norm_ieee(b.get("sourceIeee") or ""))
            if not w:
                continue
            for bucket in ("expected", "lost"):
                store = w.get(bucket) or {}
                for key in [k for k in store if key_matches(k, b)]:
                    del store[key]
                    dirty = True
                    if bucket == "expected":
                        n += 1
        if dirty:
            self._save()
            self._update_issue()
        return n

    async def async_check_device(self, ieee: str, how: str = "nightly", put_back: bool = True) -> list[dict] | None:
        """Reads one device. Returns its lost bindings, or None if it didn't
        answer (which never makes anything lost)."""
        ieee = norm_ieee(ieee)
        w = self.tracked.get(ieee)
        if not w or not w.get("expected") or w.get("policy") == "off" or ieee in self._busy:
            return None
        self._busy.add(ieee)
        try:
            try:
                await self.data.async_rescan(ieee)
            except BindsGetFailed as err:
                _LOGGER.debug("Binding check: %s didn't answer (%s)", ieee, err)
                return None
            present = relationship_map((self.data.scans.get(ieee) or {}).get("bindings"), self.data.coordinator)
            self._apply_read(ieee, present, how)
            w["last_check"] = _now().isoformat()
            self._save()
            self._update_issue()
        finally:
            self._busy.discard(ieee)
        if put_back and w.get("lost") and w.get("policy") == "auto":
            await self._auto_put_back(ieee)
        return self.lost(ieee)

    async def async_check_all(self) -> dict[str, str]:
        """Reads every watched device. {ieee: "ok" | "lost" | "no_answer"}."""
        result: dict[str, str] = {}
        for ieee in [i for i, w in self.tracked.items() if w.get("expected") and w.get("policy") != "off"]:
            lost = await self.async_check_device(ieee, "check")
            result[ieee] = "no_answer" if lost is None else "lost" if lost else "ok"
            if self.pause:
                await asyncio.sleep(self.pause)
        return result

    async def _nightly(self, _now_dt: datetime) -> None:
        await self.async_check_all()

    @callback
    def _on_zha_event(self, event: Event) -> None:
        """A device just sent something, so it's awake."""
        ieee = norm_ieee(event.data.get("device_ieee"))
        w = self.tracked.get(ieee)
        if not w or not w.get("expected") or w.get("policy") == "off":
            return
        self.fallback.handle(ieee, event.data)
        if ieee in self._busy:
            return
        if w.get("queued"):
            self.hass.async_create_task(self.async_put_back(ieee))
        elif w.get("policy") == "auto" and w.get("lost") and not w.get("auto_paused"):
            self.hass.async_create_task(self._auto_put_back(ieee))
        elif w.get("policy") == "auto" and _older_than(w.get("last_check"), PRESS_CHECK_GAP):
            self.hass.async_create_task(self.async_check_device(ieee, "press"))
        elif _older_than(w.get("last_check"), DUE_AFTER):
            self.hass.async_create_task(self.async_check_device(ieee, "press"))

    # --- putting back --------------------------------------------------------------

    def lost(self, ieee: str) -> list[dict]:
        w = self.tracked.get(norm_ieee(ieee)) or {}
        exp = w.get("expected") or {}
        return [exp[k] for k in sorted(w.get("lost") or {}) if k in exp]

    async def _bind(self, ieee: str, b: dict) -> None:
        try:
            if b.get("isGroup"):
                data = {"ieee": ieee, "command_data": b.get("groupId"), "cluster": b.get("clusterId"), "endpoint": b.get("sourceEndpoint")}
                await self.hass.services.async_call("zha_toolkit", "bind_group", data, blocking=True, return_response=True)
            else:
                data = {
                    "ieee": ieee,
                    "command_data": b.get("targetIeee"),
                    "cluster": b.get("clusterId"),
                    "endpoint": b.get("sourceEndpoint"),
                    "dst_endpoint": b.get("targetEndpoint"),
                }
                await self.hass.services.async_call("zha_toolkit", "bind_ieee", data, blocking=True, return_response=True)
        except Exception as err:  # noqa: BLE001 - checked by the read below
            _LOGGER.debug("Putting back a binding on %s raised: %s", ieee, err)

    async def async_put_back(self, ieee: str) -> dict[str, Any]:
        """Binds the lost bindings again and reads the device back.
        {"status": "put_back" | "still_missing" | "waiting" | "nothing", "count": n, "still": [...]}.
        A device that doesn't answer is queued: its bindings go back on its
        next button press."""
        ieee = norm_ieee(ieee)
        w = self.tracked.get(ieee)
        lost = self.lost(ieee)
        if not w or not lost:
            if w:
                w["queued"] = False
            return {"status": "nothing", "count": 0, "still": []}
        if ieee in self._busy:
            return {"status": "waiting", "count": len(lost), "still": lost}
        self._busy.add(ieee)
        try:
            for b in lost:
                await self._bind(ieee, b)
            try:
                await self.data.async_rescan(ieee)
            except BindsGetFailed:
                w["queued"] = True
                self._save()
                self._update_issue()
                return {"status": "waiting", "count": len(lost), "still": lost}
            present = relationship_map((self.data.scans.get(ieee) or {}).get("bindings"), self.data.coordinator)
            self._apply_read(ieee, present, "put_back")
            w["last_check"] = _now().isoformat()
            still = self.lost(ieee)
            w["queued"] = False
            self._save()
            self._update_issue()
            return {"status": "still_missing" if still else "put_back", "count": len(lost) - len(still), "still": still}
        finally:
            self._busy.discard(ieee)

    async def async_put_back_all(self) -> dict[str, dict[str, Any]]:
        out = {}
        for ieee in [i for i, w in self.tracked.items() if w.get("lost") and w.get("policy") != "off"]:
            out[ieee] = await self.async_put_back(ieee)
            if self.pause:
                await asyncio.sleep(self.pause)
        return out

    async def _auto_put_back(self, ieee: str) -> None:
        w = self.tracked.get(ieee)
        if not w or w.get("policy") != "auto" or w.get("auto_paused") or not w.get("lost"):
            return
        history = [t for t in (w.get("auto_history") or []) if not _older_than(t, AUTO_WINDOW)]
        if len(history) >= AUTO_LIMIT:
            w["auto_history"] = history
            w["auto_paused"] = True
            self._save()
            self._update_issue()
            return
        history.append(_now().isoformat())
        w["auto_history"] = history
        result = await self.async_put_back(ieee)
        if result["status"] in ("put_back", "still_missing") and result["count"]:
            self._log(ieee, result["count"])

    def _log(self, ieee: str, count: int) -> None:
        name = self.data.names().get(ieee) or ieee
        try:
            from homeassistant.components.logbook import async_log_entry

            async_log_entry(self.hass, "ZHA Bindings Manager", f"put back {count} lost binding{'s' if count != 1 else ''} on {name}", DOMAIN)
        except Exception:  # noqa: BLE001 - logbook is optional
            _LOGGER.info("Put back %s lost bindings on %s", count, name)

    # --- user choices ----------------------------------------------------------------

    @callback
    def forget(self, ieee: str, keys: list[str] | None = None) -> None:
        """Lost bindings removed on purpose: stop expecting them."""
        w = self.tracked.get(norm_ieee(ieee))
        if not w:
            return
        for k in list(keys if keys is not None else (w.get("lost") or {})):
            (w.get("lost") or {}).pop(k, None)
            w["expected"].pop(k, None)
        if not w.get("lost"):
            w["queued"] = False
        self._save()
        self._update_issue()

    # --- Replace a device (1.9.0) ---------------------------------------------------

    @callback
    def expect_and_queue(self, ieee: str, bindings: list[dict]) -> None:
        """Bindings copied to a device that didn't answer (asleep): expect
        them, mark them missing and queue them, so they go on at its next
        button press like any lost binding."""
        ieee = norm_ieee(ieee)
        w = self._entry(ieee)
        at = _now().isoformat()
        for b in bindings:
            key = identity_key(b)
            w["expected"][key] = b
            w["lost"][key] = {"since": at, "noticed_by": "replace"}
        if w.get("policy") == "off":
            w["policy"] = DEFAULT_POLICY
        w["queued"] = True
        self._save()
        self._update_issue()

    @callback
    def adopt(self, ieee: str) -> None:
        """After copying bindings to a device and reading it back: what it
        has now is what's expected from here on."""
        ieee = norm_ieee(ieee)
        present = relationship_map((self.data.scans.get(ieee) or {}).get("bindings"), self.data.coordinator)
        self._apply_read(ieee, present, "replace")
        w = self._entry(ieee)
        w["last_check"] = _now().isoformat()
        self._save()
        self._update_issue()

    @callback
    def retire(self, ieee: str) -> None:
        """The old device of a replacement: stop watching it, so its
        bindings aren't reported as lost."""
        if self.tracked.pop(norm_ieee(ieee), None) is not None:
            self._save()
            self._update_issue()

    @callback
    def set_fallback(self, ieee: str, enabled: bool) -> None:
        """Switch the lights from Home Assistant if a press doesn't reach them."""
        w = self._entry(norm_ieee(ieee))
        w["fallback"] = bool(enabled)
        self._save()

    @callback
    def set_policy(self, ieee: str, policy: str) -> None:
        if policy not in POLICIES:
            raise ValueError(policy)
        w = self._entry(norm_ieee(ieee))
        w["policy"] = policy
        if policy == "off":
            w["lost"], w["queued"] = {}, False
        if policy == "auto":
            w["auto_paused"], w["auto_history"] = False, []
        self._save()
        self._update_issue()

    # --- reporting -------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        names = self.data.names()
        group_names, _ = self.data.groups()
        devices = {}
        for ieee, w in self.tracked.items():
            if not w.get("expected") and w.get("policy", DEFAULT_POLICY) == DEFAULT_POLICY and not w.get("fallback"):
                continue
            exp = w.get("expected") or {}
            devices[ieee] = {
                "name": names.get(ieee) or ieee,
                "policy": w.get("policy", DEFAULT_POLICY),
                "expected": len(exp),
                "lost": [
                    {**exp[k], "key": k, "since": v.get("since"), "noticed_by": v.get("noticed_by"), "text": describe_binding(exp[k], names, group_names)}
                    for k, v in sorted((w.get("lost") or {}).items())
                    if k in exp
                ],
                "queued": bool(w.get("queued")),
                "auto_paused": bool(w.get("auto_paused")),
                "fallback": bool(w.get("fallback")),
                "last_check": w.get("last_check"),
            }
        return {"devices": devices}

    @callback
    def _update_issue(self) -> None:
        names = self.data.names()
        lines, total, paused = [], 0, []
        for ieee, w in self.tracked.items():
            if w.get("policy") == "off":
                continue
            n = len(self.lost(ieee))
            if n:
                total += n
                lines.append(f"- {names.get(ieee) or ieee}: {n}")
            if w.get("auto_paused"):
                paused.append(names.get(ieee) or ieee)
        if not total and not paused:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID)
            return
        link = f"/{PANEL_URL_PATH}" if current_options(self.hass)[OPT_SIDEBAR_PANEL] else None
        paused_text = (
            "\n\nStopped putting bindings back automatically on "
            + ", ".join(paused)
            + " after 3 times in 24 hours: it keeps losing them. Check its range, battery or firmware."
            if paused
            else ""
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_ID,
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="lost_bindings",
            learn_more_url=link,
            translation_placeholders={"count": str(total), "devices": "\n".join(lines) or "-", "paused": paused_text},
        )


@callback
def get_watch(hass: HomeAssistant) -> BindingWatch | None:
    return hass.data.get(DOMAIN, {}).get("watch")
