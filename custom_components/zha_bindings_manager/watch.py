"""Noticing bindings that disappear, and putting them back (1.3.0).

Opt-in ("Check bindings every night"). Bindings can vanish without anyone
noticing: a device is factory reset, re-paired, or loses its table after a
firmware update. A remote then just stops working.

- Expected bindings per device follow the card: whenever the card has read
  a device more recently than the last time we synced, its bindings become
  the expected set. (Unbinding in the card is therefore never reported.)
- Every night at 03:17 each device with expected bindings is read again.
  Mains devices answer; battery devices usually don't, so they're checked
  instead the next time they send something (a zha_event, e.g. a button
  press) and haven't been checked for 20 hours.
- A binding absent in 2 successful reads in a row raises a Repairs issue.
  A device that doesn't answer never counts as a miss.
- The Repairs issue offers Re-apply (binds them again with zha-toolkit and
  checks) or Forget (they were removed on purpose).
Nothing is ever re-bound automatically.
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

from .bindings import BindsGetFailed, describe_binding, evaluate_check, norm_ieee, relationship_map
from .const import DOMAIN, SIGNAL_BINDINGS_UPDATED
from .device_bindings import DeviceBindings

_LOGGER = logging.getLogger(__name__)

WATCH_STORAGE_KEY = f"{DOMAIN}/watch"
CHECK_HOUR, CHECK_MINUTE = 3, 17
DUE_AFTER = timedelta(hours=20)
PAUSE_BETWEEN_DEVICES = 2.0
ISSUE_PREFIX = "binding_missing_"


def issue_id_for(ieee: str) -> str:
    return ISSUE_PREFIX + norm_ieee(ieee).replace(":", "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BindingWatch:
    def __init__(self, hass: HomeAssistant, data: DeviceBindings) -> None:
        self.hass = hass
        self.data = data
        self._store = storage.Store(hass, 1, WATCH_STORAGE_KEY)
        self.tracked: dict[str, dict[str, Any]] = {}
        self._busy: set[str] = set()
        self.pause = PAUSE_BETWEEN_DEVICES

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self.tracked = stored if isinstance(stored, dict) else {}
        self.sync_from_card()

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

    # --- expected bindings follow the card ------------------------------------

    @callback
    def sync_from_card(self) -> None:
        changed = False
        for ieee, (read_at, lst) in self.data.card.items():
            w = self.tracked.get(ieee)
            if w is not None and read_at <= (w.get("card_at") or ""):
                continue
            expected = relationship_map(lst, self.data.coordinator)
            if not expected and w is None:
                continue
            w = self.tracked.setdefault(ieee, {"misses": {}, "last_check": None})
            w["expected"] = expected
            w["card_at"] = read_at
            w["misses"] = {k: n for k, n in (w.get("misses") or {}).items() if k in expected}
            changed = True
            self._update_issue(ieee, [])
        if changed:
            self._save()

    # --- checks -------------------------------------------------------------------

    async def async_check_device(self, ieee: str) -> list[dict] | None:
        """Reads one device. Returns bindings now reported missing, or None if
        the device didn't answer (which never counts as a miss)."""
        ieee = norm_ieee(ieee)
        w = self.tracked.get(ieee)
        if not w or not w.get("expected") or ieee in self._busy:
            return None
        self._busy.add(ieee)
        try:
            try:
                await self.data.async_rescan(ieee)
            except BindsGetFailed as err:
                _LOGGER.debug("Binding check: %s didn't answer (%s)", ieee, err)
                return None
            present = relationship_map((self.data.scans.get(ieee) or {}).get("bindings"), self.data.coordinator)
            w["expected"], w["misses"], missing = evaluate_check(w["expected"], w.get("misses") or {}, present)
            w["last_check"] = _now().isoformat()
            self._update_issue(ieee, missing)
            self._save()
            return missing
        finally:
            self._busy.discard(ieee)

    async def async_check_all(self) -> None:
        for ieee in [i for i, w in self.tracked.items() if w.get("expected")]:
            await self.async_check_device(ieee)
            if self.pause:
                await asyncio.sleep(self.pause)

    async def _nightly(self, _now_dt: datetime) -> None:
        await self.async_check_all()

    def _due(self, w: dict[str, Any]) -> bool:
        last = w.get("last_check")
        if not last:
            return True
        try:
            return _now() - datetime.fromisoformat(last) >= DUE_AFTER
        except ValueError:
            return True

    @callback
    def _on_zha_event(self, event: Event) -> None:
        """A device just sent something, so it's awake: check it if due."""
        ieee = norm_ieee(event.data.get("device_ieee"))
        w = self.tracked.get(ieee)
        if w and w.get("expected") and self._due(w) and ieee not in self._busy:
            self.hass.async_create_task(self.async_check_device(ieee))

    # --- Repairs -------------------------------------------------------------------

    def missing(self, ieee: str) -> list[dict]:
        w = self.tracked.get(norm_ieee(ieee)) or {}
        from .bindings import MISSES_FOR_ISSUE

        return [w["expected"][k] for k, n in sorted((w.get("misses") or {}).items()) if n >= MISSES_FOR_ISSUE and k in w.get("expected", {})]

    def describe(self, bindings: list[dict]) -> str:
        names = self.data.names()
        group_names, _ = self.data.groups()
        return "\n".join(f"- {describe_binding(b, names, group_names)}" for b in bindings)

    @callback
    def _update_issue(self, ieee: str, missing: list[dict]) -> None:
        missing = missing or self.missing(ieee)
        if not missing:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id_for(ieee))
            return
        name = self.data.names().get(ieee) or ieee
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id_for(ieee),
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="binding_missing",
            translation_placeholders={"device": name, "bindings": self.describe(missing)},
            data={"ieee": ieee},
        )

    async def async_reapply(self, ieee: str) -> list[dict]:
        """Binds the missing bindings again and reads the device. Returns
        what is still missing (everything, if the device didn't answer)."""
        ieee = norm_ieee(ieee)
        missing = self.missing(ieee)
        for b in missing:
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
                _LOGGER.warning("Re-apply of a binding on %s raised: %s", ieee, err)
        try:
            await self.data.async_rescan(ieee)
        except BindsGetFailed:
            return missing
        w = self.tracked[ieee]
        present = relationship_map((self.data.scans.get(ieee) or {}).get("bindings"), self.data.coordinator)
        for k in list(w.get("misses") or {}):
            if k in present:
                w["misses"].pop(k)
        w["last_check"] = _now().isoformat()
        self._save()
        still = self.missing(ieee)
        if still:
            self._update_issue(ieee, still)
        return still

    @callback
    def forget(self, ieee: str) -> None:
        """The missing bindings were removed on purpose: stop expecting them."""
        ieee = norm_ieee(ieee)
        w = self.tracked.get(ieee)
        if not w:
            return
        for b in self.missing(ieee):
            from .bindings import identity_key

            w["expected"].pop(identity_key(b), None)
            w["misses"].pop(identity_key(b), None)
        self._save()


@callback
def get_watch(hass: HomeAssistant) -> BindingWatch | None:
    return hass.data.get(DOMAIN, {}).get("watch")
