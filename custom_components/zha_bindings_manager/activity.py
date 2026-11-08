"""Experimental: how many messages each device sends to Home Assistant (1.7.0).

Prompted by tube0013's WTH thread "Did my ZHA Zigbee light turn on 40
seconds after I toggled it?": one plug flooded his network and advertised
itself as the coordinator's address, and finding it took a sniffer. This
counts what ZHA itself receives, per device, so a chatty device stands out.

- Registers as a zigpy listener on ZHA's application controller. zigpy calls
  handle_message(device, profile, cluster, src_ep, dst_ep, message) for every
  message from a known device (the same hook zha-toolkit uses). The work per
  message is a few dict updates.
- Keeps per-device counts per minute for the last 60 minutes, plus the
  busiest clusters (at most MAX_CLUSTERS per device, MAX_DEVICES devices).
  Memory only: counts restart with Home Assistant.
- Re-attaches every 60 s if ZHA was reloaded (a new controller object), and
  detaches when the entry unloads.
- Coordinator counters come from the radio library (app.state.counters, e.g.
  EZSP); which ones exist depends on the radio. At most MAX_COUNTERS.
- Only with Experimental features on. Only traffic that reaches the
  coordinator is seen: messages between other devices aren't.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .bindings import norm_ieee
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

WINDOW_MINUTES = 60
MAX_DEVICES = 1024
MAX_CLUSTERS = 16
MAX_COUNTERS = 64
REATTACH_EVERY = timedelta(seconds=60)


def _minute(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // 60)


class ActivityCounter:
    """Counts messages per device and minute. `by_device` maps a colon-hex
    IEEE address to {"nwk", "minutes": {minute: count}, "clusters": {id: count}}."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.by_device: dict[str, dict[str, Any]] = {}
        self.started_at = datetime.now(timezone.utc)
        self.dropped_devices = 0
        self._app: Any = None
        self._unsub: CALLBACK_TYPE | None = None

    # --- zigpy listener -----------------------------------------------------------

    def handle_message(self, device: Any, profile: int, cluster: int, src_ep: int, dst_ep: int, message: bytes) -> None:
        try:
            self.count(str(device.ieee), getattr(device, "nwk", None), cluster)
        except Exception:  # never let counting break message handling
            _LOGGER.debug("Couldn't count a message", exc_info=True)

    def count(self, ieee: str, nwk: Any, cluster: int, now: float | None = None) -> None:
        ieee = norm_ieee(ieee)
        entry = self.by_device.get(ieee)
        if entry is None:
            if len(self.by_device) >= MAX_DEVICES:
                self.dropped_devices += 1
                return
            entry = self.by_device[ieee] = {"nwk": None, "minutes": {}, "clusters": {}}
        if nwk is not None:
            try:
                entry["nwk"] = int(nwk)
            except (TypeError, ValueError):
                pass
        minute = _minute(now)
        minutes = entry["minutes"]
        minutes[minute] = minutes.get(minute, 0) + 1
        if len(minutes) > WINDOW_MINUTES + 5:
            oldest = minute - WINDOW_MINUTES + 1
            for m in [m for m in minutes if m < oldest]:
                del minutes[m]
        clusters = entry["clusters"]
        cid = int(cluster)
        if cid in clusters or len(clusters) < MAX_CLUSTERS:
            clusters[cid] = clusters.get(cid, 0) + 1

    # --- reading ----------------------------------------------------------------------

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        current = _minute(now)
        first = current - WINDOW_MINUTES + 1
        by_device = {}
        for ieee, entry in self.by_device.items():
            per_minute = [entry["minutes"].get(m, 0) for m in range(first, current + 1)]
            if not any(per_minute):
                continue
            by_device[ieee] = {
                "nwk": entry["nwk"],
                "per_minute": per_minute,
                "clusters": {f"0x{c:04x}": n for c, n in sorted(entry["clusters"].items(), key=lambda kv: -kv[1])},
            }
        return {
            "since": self.started_at.isoformat(),
            "window_minutes": WINDOW_MINUTES,
            "coordinator_ieee": self._coordinator_ieee(),
            "by_device": by_device,
            "dropped_devices": self.dropped_devices,
            "coordinator_counters": self._counters(),
            "attached": self._app is not None,
        }

    def _coordinator_ieee(self) -> str | None:
        try:
            return norm_ieee(str(self._app.state.node_info.ieee)) if self._app is not None else None
        except Exception:
            return None

    def _counters(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            groups = self._app.state.counters if self._app is not None else None
        except Exception:
            groups = None
        if not groups:
            return out

        def walk(group: Any, prefix: str) -> None:
            for counter in getattr(group, "counters", lambda: [])():
                if len(out) >= MAX_COUNTERS:
                    return
                try:
                    out.append({"name": f"{prefix}{counter.name}", "value": int(counter.value)})
                except Exception:
                    continue
            for sub in getattr(group, "groups", lambda: [])():
                walk(sub, f"{prefix}{sub.name}.")

        for group in list(groups.values()):
            if len(out) >= MAX_COUNTERS:
                break
            walk(group, f"{getattr(group, 'name', '')}.")
        return out

    # --- attaching to ZHA ------------------------------------------------------------

    def _current_app(self) -> Any:
        try:
            from homeassistant.components.zha.helpers import get_zha_gateway  # type: ignore

            return get_zha_gateway(self.hass).application_controller
        except Exception:
            return None

    @callback
    def attach(self, _now: Any = None) -> None:
        app = self._current_app()
        if app is self._app:
            return
        self._detach_app()
        if app is not None:
            app.add_listener(self)
            self._app = app
            _LOGGER.debug("Counting messages to Home Assistant")

    def _detach_app(self) -> None:
        if self._app is not None:
            try:
                self._app.remove_listener(self)
            except Exception:
                pass
            self._app = None

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        self.attach()
        self._unsub = async_track_time_interval(self.hass, self.attach, REATTACH_EVERY)

        @callback
        def stop() -> None:
            if self._unsub:
                self._unsub()
                self._unsub = None
            self._detach_app()

        return stop


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/activity_get"})
@websocket_api.require_admin
@callback
def websocket_activity_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    from .mesh import _enabled

    if not _enabled(hass, connection, msg["id"]):
        return
    counter: ActivityCounter | None = hass.data.get(DOMAIN, {}).get("activity")
    if counter is None:
        connection.send_error(msg["id"], "not_running", "The message counter isn't running. Reload the integration.")
        return
    connection.send_result(msg["id"], counter.snapshot())
