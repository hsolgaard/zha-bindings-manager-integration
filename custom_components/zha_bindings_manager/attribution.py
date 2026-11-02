"""Logbook attribution for direct bindings (1.4.0, off by default).

From HarvsG's WTH thread: Home Assistant's logbook says a light turned on,
but not that a bound remote did it. Commands sent over a binding go
straight from the remote to the light, so Home Assistant only knows when it
hears the press too. It does for most remotes: when ZHA pairs a remote it
binds the remote's On/Off and Level clusters to the coordinator as well
(that's how zha_event works), and a remote sends each command to everything
bound for that cluster.

So when a zha_event arrives from a remote whose binding table (from the
card's last scan or a device-page rescan) has it bound to lights or a group
for that cluster, the lights it controls are watched for a few seconds (and changes from just before the press count too, as
a light's own report can arrive first).
A light that changes state in that window, on its own report rather than
because of Home Assistant (no user and no automation behind the change),
gets a logbook entry: "turned on by Kitchen RODRET (direct binding)".
Remotes Home Assistant can't hear, and changes HA caused itself, get none.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .bindings import is_relationship, norm_ieee
from .const import DOMAIN
from .device_bindings import DeviceBindings

_LOGGER = logging.getLogger(__name__)

# Clusters whose commands change a light, switch or similar.
ATTRIBUTED_CLUSTERS = {0x0006, 0x0008, 0x0300}
# How long after a press a state change still counts as caused by it. Lights
# usually report within a second; anything slower is left unattributed.
WINDOW_SECONDS = 3.0
# A light's own report can reach Home Assistant a moment before the press
# does (1.4.2), so a press also claims changes from just before it.
LOOKBACK_SECONDS = 1.5
# Holding a dimmer sends a stream of commands; log each light once per hold.
REPEAT_SECONDS = 10.0
CONTROLLED_DOMAINS = {"light", "switch", "fan", "cover"}
EVENT_LOGBOOK_ENTRY = "logbook_entry"


# --- pure helpers ---------------------------------------------------------------


def press_targets(
    bindings: Iterable[dict] | None,
    coordinator: str | None,
    endpoint: Any,
    cluster_id: int,
    group_members: dict[int, set[str]],
) -> set[tuple[str, Any]]:
    """(ieee, endpoint) of every device a press on this endpoint and
    cluster reaches over a binding. endpoint None means any endpoint. A
    group target expands to its members, with endpoint None (any of the
    member's entities)."""
    out: set[tuple[str, Any]] = set()
    for b in bindings or []:
        if int(b.get("clusterId", -1)) != int(cluster_id):
            continue
        if endpoint is not None and b.get("sourceEndpoint") is not None and int(b["sourceEndpoint"]) != int(endpoint):
            continue
        if not is_relationship(b, coordinator):
            continue
        if b.get("isGroup"):
            for member in group_members.get(int(b.get("groupId")), set()):
                if member and member != norm_ieee(coordinator):
                    out.add((member, None))
        else:
            out.add((norm_ieee(b.get("targetIeee")), b.get("targetEndpoint")))
    return out


def entity_matches_endpoint(unique_id: str, ieee: str, endpoint: Any) -> bool:
    """ZHA unique ids look like "<ieee>-<endpoint>" or "<ieee>-<endpoint>-<cluster>"."""
    if endpoint is None:
        return True
    prefix = f"{norm_ieee(ieee)}-{int(endpoint)}"
    uid = (unique_id or "").lower()
    return uid == prefix or uid.startswith(prefix + "-")


def describe_change(old: dict | None, new: dict | None) -> str | None:
    """What a state change did, in logbook words, or None if nothing worth
    attributing changed. old/new are {"state": str, "attributes": dict}."""
    if not new:
        return None
    o_state = (old or {}).get("state")
    n_state = new.get("state")
    if n_state in (None, "unavailable", "unknown") or o_state in (None, "unavailable", "unknown"):
        return None
    if o_state != n_state:
        return {"on": "turned on", "off": "turned off", "open": "opened", "closed": "closed"}.get(n_state, f"changed to {n_state}")
    if n_state != "on":
        return None
    oa = (old or {}).get("attributes") or {}
    na = new.get("attributes") or {}
    if oa.get("brightness") != na.get("brightness"):
        return "dimmed" if (na.get("brightness") or 0) < (oa.get("brightness") or 0) else "brightened"
    for key in ("color_temp_kelvin", "color_temp", "hs_color", "xy_color", "rgb_color"):
        if oa.get(key) != na.get(key):
            return "colour changed"
    return None


def caused_by_home_assistant(context: Any) -> bool:
    """A user, a script or an automation behind the change means Home
    Assistant did it, not the binding."""
    return bool(getattr(context, "user_id", None) or getattr(context, "parent_id", None))


# --- the listener ------------------------------------------------------------------


class BindingAttribution:
    """Listens for presses and state changes and writes logbook entries."""

    def __init__(self, hass: HomeAssistant, data: DeviceBindings) -> None:
        self.hass = hass
        self.data = data
        # entity_id -> (source ieee, expires at monotonic time)
        self._pending: dict[str, tuple[str, float]] = {}
        # (entity_id, source ieee, message) -> last logged at
        self._recent: dict[tuple[str, str, str], float] = {}
        # entity_id -> (changed at, message, name, context) for changes no
        # press has claimed yet, kept for LOOKBACK_SECONDS.
        self._unclaimed: dict[str, tuple[float, str, str, Any]] = {}

    def async_start(self) -> CALLBACK_TYPE:
        unsubs = [
            self.hass.bus.async_listen("zha_event", self._on_zha_event),
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_state_changed),
        ]

        @callback
        def stop() -> None:
            for unsub in unsubs:
                unsub()

        return stop

    def _entities_for(self, ieee: str, endpoint: Any) -> list[str]:
        device = self.data.zha_device(ieee)
        if device is None:
            return []
        registry = er.async_get(self.hass)
        entries = [
            e
            for e in er.async_entries_for_device(registry, device.id)
            if e.domain in CONTROLLED_DOMAINS and e.platform == "zha" and not e.disabled_by
        ]
        on_endpoint = [e.entity_id for e in entries if entity_matches_endpoint(e.unique_id, ieee, endpoint)]
        return on_endpoint or [e.entity_id for e in entries]

    @callback
    def _on_zha_event(self, event: Event) -> None:
        data = event.data or {}
        try:
            cluster_id = int(data.get("cluster_id"))
        except (TypeError, ValueError):
            return
        if cluster_id not in ATTRIBUTED_CLUSTERS:
            return
        if str(data.get("command") or "").startswith("attribute_"):
            return  # a device reporting its own state, not a press
        source = norm_ieee(data.get("device_ieee"))
        bindings = self.data.by_source.get(source)
        if not bindings:
            return
        _names, members = self.data.groups()
        targets = press_targets(bindings, self.data.coordinator, data.get("endpoint_id"), cluster_id, members)
        if not targets:
            return
        now = time.monotonic()
        expires = now + WINDOW_SECONDS
        for ieee, endpoint in targets:
            for entity_id in self._entities_for(ieee, endpoint):
                self._pending[entity_id] = (source, expires)
                earlier = self._unclaimed.pop(entity_id, None)
                if earlier and now - earlier[0] <= LOOKBACK_SECONDS:
                    _at, message, name, context = earlier
                    self._log(entity_id, source, message, name, context, now)

    @callback
    def _on_state_changed(self, event: Event) -> None:
        entity_id = event.data.get("entity_id") or ""
        if entity_id.split(".", 1)[0] not in CONTROLLED_DOMAINS:
            return
        if caused_by_home_assistant(event.context):
            return
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        message = describe_change(
            {"state": old.state, "attributes": dict(old.attributes)} if old else None,
            {"state": new.state, "attributes": dict(new.attributes)} if new else None,
        )
        if not message:
            return
        now = time.monotonic()
        name = new.name if new else entity_id
        pending = self._pending.get(entity_id)
        if pending and now <= pending[1]:
            self._log(entity_id, pending[0], message, name, event.context, now)
            return
        if pending:
            self._pending.pop(entity_id, None)
        # Not claimed by a press (yet): the press may still be on its way.
        self._unclaimed[entity_id] = (now, message, name, event.context)
        if len(self._unclaimed) > 200:
            self._unclaimed = {k: v for k, v in self._unclaimed.items() if now - v[0] <= LOOKBACK_SECONDS}

    def _log(self, entity_id: str, source: str, message: str, name: str, context: Any, now: float) -> None:
        key = (entity_id, source, message)
        if now - self._recent.get(key, -1e9) < REPEAT_SECONDS:
            return
        self._recent[key] = now
        if len(self._recent) > 500:
            self._recent = {k: v for k, v in self._recent.items() if now - v < REPEAT_SECONDS}
        source_name = self.data.names().get(source, source)
        self.hass.bus.async_fire(
            EVENT_LOGBOOK_ENTRY,
            {
                "name": name,
                "message": f"{message} by {source_name} (direct binding)",
                "domain": DOMAIN,
                "entity_id": entity_id,
            },
            context=context,
        )


@callback
def get_attribution(hass: HomeAssistant) -> BindingAttribution | None:
    return hass.data.get(DOMAIN, {}).get("attribution")
