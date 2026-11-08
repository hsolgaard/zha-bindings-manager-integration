"""Address changes and missed presses (1.10.0): evidence, not a fix.

HarvsG's TRÅDFRI switches stop controlling a light although the binding is
still in their table, and removing and re-adding it fixes it. One theory: the
light's short (network) address changed, and the battery remote, which never
hears the light's announcement, keeps sending to the old one. This records
what's needed to prove or disprove that on any network. Read-only: it sends
nothing to any device.

- Short addresses: every device's current address is read from ZHA (zigpy's
  device list, in memory, no radio traffic) every 5 minutes, and straight
  away when zigpy reports a device joining or rejoining. Only changes are
  stored: {ieee: [{"nwk": "0x1a2b", "from": iso, "seen": "snapshot"|"joined"}]}.
- Presses: when a remote sends On, Off or Toggle (a zha_event: most remotes
  are also bound to the coordinator) each light it's bound to directly is
  checked after PRESS_WAIT seconds: followed, already as wanted, missed, or
  unknown (no state). Per remote and light: counts, and the last press that
  worked with the light's address at that moment. Each missed press is
  logged with the light's address now and at the last press that worked, and
  whether the binding was still in the remote's last read table.
- Kept in .storage/zha_bindings_manager/evidence: 90 days of address changes
  (always the latest), the last MAX_MISSES missed presses.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import storage
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .bindings import norm_ieee
from .const import DOMAIN
from .fallback import CHANGED_SLACK, COMMANDS, ON_OFF, direct_targets, entity_for, wanted_state

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}/evidence"
SNAPSHOT_EVERY = timedelta(minutes=5)
KEEP = timedelta(days=90)
MAX_PER_DEVICE = 50
MAX_MISSES = 300
PRESS_WAIT = 2.0


def nwk_hex(nwk: Any) -> str | None:
    try:
        return f"0x{int(nwk):04x}"
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_address(history: dict[str, list[dict]], ieee: str, nwk: str | None, seen: str, at: str) -> bool:
    """Adds an entry when the address differs from the last one. True if added."""
    if not ieee or not nwk:
        return False
    lst = history.setdefault(ieee, [])
    if lst and lst[-1].get("nwk") == nwk:
        return False
    lst.append({"nwk": nwk, "from": at, "seen": seen})
    del lst[:-MAX_PER_DEVICE]
    return True


def prune(history: dict[str, list[dict]], now: datetime) -> None:
    """Drops entries older than KEEP, always keeping each device's latest."""
    cutoff = (now - KEEP).isoformat()
    for ieee, lst in history.items():
        keep = [e for e in lst[:-1] if e.get("from", "") >= cutoff]
        history[ieee] = keep + lst[-1:]


def address_at(history: list[dict] | None, at: str | None) -> str | None:
    """The address a device had at a moment (the last entry from before it)."""
    if not history:
        return None
    if not at:
        return history[-1].get("nwk")
    best = None
    for e in history:
        if e.get("from", "") <= at:
            best = e.get("nwk")
    return best or history[0].get("nwk")


def changes_between(history: list[dict] | None, since: str | None, until: str) -> list[dict]:
    return [e for e in (history or []) if since and since < e.get("from", "") <= until]


def outcome(wanted: str, state: Any, pressed_at: datetime) -> str:
    """followed | already | missed | unknown for one light after a press."""
    if state is None or state.state not in ("on", "off"):
        return "unknown"
    if state.last_changed >= pressed_at - CHANGED_SLACK:
        return "followed"
    return "already" if state.state == wanted else "missed"


class Evidence:
    def __init__(self, hass: HomeAssistant, data: Any) -> None:
        self.hass = hass
        self.data = data
        self._store = storage.Store(hass, 1, STORAGE_KEY)
        self.addresses: dict[str, list[dict]] = {}
        self.pairs: dict[str, dict] = {}  # "remote|light|ep" -> counts and last press that worked
        self.misses: list[dict] = []
        self.started_at = _now().isoformat()
        self.wait = PRESS_WAIT
        self._app: Any = None
        self._running: set[str] = set()

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.addresses = stored.get("addresses") or {}
        self.pairs = stored.get("pairs") or {}
        self.misses = stored.get("misses") or []
        self.started_at = stored.get("started_at") or self.started_at

    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {"addresses": self.addresses, "pairs": self.pairs, "misses": self.misses, "started_at": self.started_at}, 5
        )

    # --- short addresses -------------------------------------------------------------

    def _current_app(self) -> Any:
        if "zha" not in self.hass.config.components:
            return None
        try:
            from homeassistant.components.zha.helpers import get_zha_gateway  # type: ignore

            return get_zha_gateway(self.hass).application_controller
        except Exception:  # noqa: BLE001 - internal ZHA API
            return None

    def zigpy_devices(self) -> dict[str, Any]:
        app = self._app or self._current_app()
        try:
            return {norm_ieee(str(ieee)): dev for ieee, dev in (getattr(app, "devices", None) or {}).items()}
        except Exception:  # noqa: BLE001
            return {}

    @callback
    def snapshot(self, _now_dt: Any = None) -> None:
        at = _now().isoformat()
        changed = False
        for ieee, dev in self.zigpy_devices().items():
            changed |= record_address(self.addresses, ieee, nwk_hex(getattr(dev, "nwk", None)), "snapshot", at)
        self._attach()
        if changed:
            prune(self.addresses, _now())
            self._save()

    # zigpy listener: a device joined or rejoined (zigpy updates its address first)
    def device_joined(self, device: Any) -> None:
        try:
            ieee = norm_ieee(str(device.ieee))
            if record_address(self.addresses, ieee, nwk_hex(device.nwk), "joined", _now().isoformat()):
                self._save()
        except Exception:  # noqa: BLE001 - never break zigpy's event handling
            _LOGGER.debug("Couldn't record a join", exc_info=True)

    def _attach(self) -> None:
        app = self._current_app()
        if app is self._app:
            return
        if self._app is not None:
            try:
                self._app.remove_listener(self)
            except Exception:  # noqa: BLE001
                pass
        self._app = app
        if app is not None:
            try:
                app.add_listener(self)
            except Exception:  # noqa: BLE001
                self._app = None

    def _current_nwk(self, ieee: str) -> str | None:
        lst = self.addresses.get(ieee)
        if lst:
            return lst[-1].get("nwk")
        return nwk_hex(getattr(self.zigpy_devices().get(ieee), "nwk", None))

    # --- presses --------------------------------------------------------------------

    @callback
    def _on_zha_event(self, event: Event) -> None:
        ieee = norm_ieee(event.data.get("device_ieee") or "")
        command = str(event.data.get("command") or "").lower()
        try:
            cluster = int(event.data.get("cluster_id"))
        except (TypeError, ValueError):
            return
        if not ieee or cluster != ON_OFF or command not in COMMANDS or ieee in self._running:
            return
        bindings = self.data.by_source.get(ieee) or []
        coord = norm_ieee(self.data.coordinator or "")
        ep = event.data.get("endpoint_id")
        targets = [t for t in direct_targets({str(i): b for i, b in enumerate(bindings)}, int(ep) if ep is not None else None) if t[0] != coord]
        if not targets:
            return
        self._running.add(ieee)
        self.hass.async_create_task(self._check_press(ieee, command, targets, ep))

    async def _check_press(self, remote: str, command: str, targets: list[tuple[str, int]], ep: Any) -> None:
        try:
            pressed_at = dt_util.utcnow()
            lights = []
            for t_ieee, t_ep in targets:
                dev = self.data.zha_device(t_ieee)
                eid = entity_for(self.hass, dev.id if dev else None, t_ieee, t_ep)
                if eid:
                    lights.append((t_ieee, t_ep, eid))
            if not lights:
                return
            before = []
            for _i, _e, eid in lights:
                st = self.hass.states.get(eid)
                before.append((st is not None and st.last_changed >= pressed_at - CHANGED_SLACK, st.state if st else "unknown"))
            wanted = wanted_state(command, before)
            await asyncio.sleep(self.wait)
            if wanted is None:
                return  # Toggle with lights that didn't agree: nothing to judge
            at = pressed_at.isoformat()
            names = self.data.names()
            for t_ieee, t_ep, eid in lights:
                result = outcome(wanted, self.hass.states.get(eid), pressed_at)
                key = f"{remote}|{t_ieee}|{t_ep}"
                pair = self.pairs.setdefault(key, {"presses": 0, "followed": 0, "missed": 0, "last_ok_at": None, "last_ok_nwk": None})
                pair["presses"] += 1
                if result == "followed":
                    pair["followed"] += 1
                    pair["last_ok_at"], pair["last_ok_nwk"] = at, self._current_nwk(t_ieee)
                elif result == "missed":
                    pair["missed"] += 1
                    hist = self.addresses.get(t_ieee)
                    nwk_now = self._current_nwk(t_ieee)
                    still_bound = any(
                        not b.get("isGroup") and norm_ieee(b.get("targetIeee")) == t_ieee and int(b.get("clusterId", -1)) == ON_OFF
                        for b in self.data.by_source.get(remote) or []
                    )
                    self.misses.append(
                        {
                            "at": at,
                            "remote": remote,
                            "remote_name": names.get(remote, remote),
                            "endpoint": ep,
                            "command": command,
                            "light": t_ieee,
                            "light_name": names.get(t_ieee, t_ieee),
                            "light_endpoint": t_ep,
                            "nwk_now": nwk_now,
                            "nwk_at_last_ok": pair.get("last_ok_nwk"),
                            "last_ok_at": pair.get("last_ok_at"),
                            "address_changed_since_last_ok": bool(pair.get("last_ok_nwk") and nwk_now and pair["last_ok_nwk"] != nwk_now),
                            "changes_since_last_ok": changes_between(hist, pair.get("last_ok_at"), at),
                            "binding_in_last_read": still_bound,
                        }
                    )
                    del self.misses[:-MAX_MISSES]
            self._save()
        except Exception:  # noqa: BLE001 - never break event handling
            _LOGGER.debug("Couldn't check a press from %s", remote, exc_info=True)
        finally:
            self._running.discard(remote)

    # --- start/stop and reading --------------------------------------------------------

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        self.snapshot()
        unsubs = [
            async_track_time_interval(self.hass, self.snapshot, SNAPSHOT_EVERY),
            self.hass.bus.async_listen("zha_event", self._on_zha_event),
        ]

        @callback
        def stop() -> None:
            for u in unsubs:
                u()
            if self._app is not None:
                try:
                    self._app.remove_listener(self)
                except Exception:  # noqa: BLE001
                    pass
                self._app = None

        return stop

    def result(self) -> dict[str, Any]:
        names = self.data.names()
        changed = {i: h for i, h in self.addresses.items() if len(h) > 1}
        return {
            "since": self.started_at,
            "names": {i: names.get(i, i) for i in set(self.addresses) | {p.split("|")[0] for p in self.pairs} | {p.split("|")[1] for p in self.pairs}},
            "addresses": self.addresses,
            "changed": sorted(changed),
            "pairs": self.pairs,
            "misses": self.misses,
        }


@callback
def get_evidence(hass: HomeAssistant) -> Evidence | None:
    return hass.data.get(DOMAIN, {}).get("evidence")
