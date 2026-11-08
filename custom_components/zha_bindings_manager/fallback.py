"""Switch them from Home Assistant if they don't respond (1.8.0, PRD R22–R24).

Per device, off by default. HarvsG's self-healing blueprint, built in: when a
remote with this switched on sends On, Off or Toggle (seen as a zha_event
through its binding to the coordinator), the lights it's bound to directly
should change. If one hasn't changed within FALLBACK_WAIT seconds, Home
Assistant switches it, logs it, and the remote's binding table is checked
straight away (it's awake), so a lost binding is noticed and, with "Put back
automatically", put back.

Limits, shown in the card as pitfalls:
- On/Off only, and only device-to-device bindings. Not group bindings: a
  light that misses one group broadcast hasn't lost a binding (Repenic).
- Toggle only when every light agreed before the press; otherwise there's no
  telling what "toggled" should look like.
- Needs lights that report their state promptly, and Home Assistant running.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .bindings import norm_ieee

_LOGGER = logging.getLogger(__name__)

FALLBACK_WAIT = 2.2  # just after the press check in evidence.py (2.0 s), so it sees the light first
CHANGED_SLACK = timedelta(seconds=1)
ON_OFF = 0x0006
COMMANDS = ("on", "off", "toggle")
DOMAINS = ("light", "switch")


def direct_targets(expected: dict[str, dict], endpoint: int | None) -> list[tuple[str, int]]:
    """(target ieee, endpoint) of the remote's direct On/Off bindings from
    this endpoint (any endpoint if the event didn't say)."""
    out: list[tuple[str, int]] = []
    for b in (expected or {}).values():
        if b.get("isGroup") or int(b.get("clusterId", -1)) != ON_OFF:
            continue
        if endpoint is not None and b.get("sourceEndpoint") is not None and int(b["sourceEndpoint"]) != int(endpoint):
            continue
        t = (norm_ieee(b.get("targetIeee")), int(b.get("targetEndpoint") or 1))
        if t not in out:
            out.append(t)
    return out


def wanted_state(command: str, before: list[tuple[bool, str]]) -> str | None:
    """What the lights should be after the press, or None to leave them.
    before: per light, (changed at the press, its state). A light that had
    already changed responded, so for Toggle its state now is the target and
    every other light must have started from the opposite."""
    if command in ("on", "off"):
        return command
    if command != "toggle" or not before:
        return None
    changed = {s for c, s in before if c}
    still = [s for c, s in before if not c]
    if any(s not in ("on", "off") for s in still) or len(changed) > 1 or (changed and not changed <= {"on", "off"}):
        return None
    if changed:
        target = next(iter(changed))
        return target if all(s != target for s in still) else None
    if len(set(still)) != 1:
        return None  # the lights didn't agree before the press
    return "off" if still[0] == "on" else "on"


def missed(wanted: str, after: State | None, pressed_at) -> bool:
    """Didn't respond: hasn't changed since the press and isn't as wanted."""
    if after is None or after.state not in ("on", "off"):
        return False  # unavailable or unknown: nothing sensible to do
    if after.last_changed >= pressed_at - CHANGED_SLACK:
        return False  # it changed (or was changing) around the press
    return after.state != wanted


def entity_for(hass: HomeAssistant, device_id: str | None, ieee: str, endpoint: int) -> str | None:
    """The light or switch entity of a ZHA device endpoint. ZHA unique ids
    start with "<ieee>-<endpoint>"."""
    if not device_id:
        return None
    reg = er.async_get(hass)
    best = None
    for ent in er.async_entries_for_device(reg, device_id):
        if ent.domain not in DOMAINS or ent.disabled_by:
            continue
        uid = str(ent.unique_id or "")
        if not uid.lower().startswith(ieee.lower()):
            continue
        rest = uid[len(ieee) :].lstrip("-")
        if rest.split("-")[0] == str(endpoint):
            if ent.domain == "light":
                return ent.entity_id
            best = best or ent.entity_id
    return best


class Fallback:
    """Runs one press check per remote at a time."""

    def __init__(self, hass: HomeAssistant, watch: Any) -> None:
        self.hass = hass
        self.watch = watch
        self.wait = FALLBACK_WAIT
        self._running: set[str] = set()

    def handle(self, ieee: str, data: dict) -> None:
        w = self.watch.tracked.get(ieee) or {}
        if not w.get("fallback") or w.get("policy") == "off" or ieee in self._running:
            return
        command = str(data.get("command") or "").lower()
        try:
            cluster = int(data.get("cluster_id"))
        except (TypeError, ValueError):
            return
        if cluster != ON_OFF or command not in COMMANDS:
            return
        endpoint = data.get("endpoint_id")
        targets = direct_targets(w.get("expected") or {}, int(endpoint) if endpoint is not None else None)
        if not targets:
            return
        self._running.add(ieee)
        self.hass.async_create_task(self._run(ieee, command, targets))

    async def _run(self, ieee: str, command: str, targets: list[tuple[str, int]]) -> None:
        try:
            pressed_at = dt_util.utcnow()
            entities = []
            for t_ieee, ep in targets:
                dev = self.watch.data.zha_device(t_ieee)
                eid = entity_for(self.hass, dev.id if dev else None, t_ieee, ep)
                if eid:
                    entities.append(eid)
            if not entities:
                return
            before = []
            for eid in entities:
                st = self.hass.states.get(eid)
                changed = st is not None and st.last_changed >= pressed_at - CHANGED_SLACK
                before.append((changed, st.state if st else "unknown"))
            wanted = wanted_state(command, before)
            if wanted is None:
                return
            await asyncio.sleep(self.wait)
            late = [eid for eid in entities if missed(wanted, self.hass.states.get(eid), pressed_at)]
            if not late:
                return
            for eid in late:
                domain = eid.split(".", 1)[0]
                await self.hass.services.async_call(domain, f"turn_{wanted}", {"entity_id": eid}, blocking=False)
            self._log(ieee, late, wanted)
            await self.watch.async_check_device(ieee, "press")
        except Exception:  # noqa: BLE001 - never let this break event handling
            _LOGGER.debug("Fallback check failed for %s", ieee, exc_info=True)
        finally:
            self._running.discard(ieee)

    def _log(self, ieee: str, entity_ids: list[str], wanted: str) -> None:
        name = self.watch.data.names().get(ieee) or ieee
        lights = ", ".join(
            (self.hass.states.get(e).name if self.hass.states.get(e) else e) for e in entity_ids
        )
        message = f"switched {lights} {wanted} from Home Assistant: {name}'s press didn't reach {'it' if len(entity_ids) == 1 else 'them'}"
        try:
            from homeassistant.components.logbook import async_log_entry

            async_log_entry(self.hass, "ZHA Bindings Manager", message, "zha_bindings_manager", entity_ids[0])
        except Exception:  # noqa: BLE001 - logbook is optional
            _LOGGER.info("ZHA Bindings Manager %s", message)
