"""1.4.0: logbook entries naming the remote that switched a light."""
import asyncio

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zha_bindings_manager import attribution as attr
from custom_components.zha_bindings_manager.attribution import (
    caused_by_home_assistant,
    describe_change,
    entity_matches_endpoint,
    get_attribution,
    press_targets,
)
from custom_components.zha_bindings_manager.const import DOMAIN, OPT_DEVICE_PAGE, OPT_LOGBOOK, STORAGE_KEY, TITLE

from .test_device_page import C, L, P, R, _b, _card_state, _zha_devices


def _g(src, cid, gid):
    return {"sourceIeee": src, "sourceEndpoint": 1, "clusterId": cid, "isGroup": True, "targetIeee": None, "targetEndpoint": None, "groupId": gid}


# --- pure helpers -------------------------------------------------------------------


def test_press_targets_devices_groups_and_coordinator():
    bindings = [_b(R, 6, C), _b(R, 6, L), _b(R, 8, L), _g(R, 6, 5)]
    members = {5: {P, C}}
    assert press_targets(bindings, C, 1, 6, members) == {(L, 1), (P, None)}
    assert press_targets(bindings, C, 1, 8, members) == {(L, 1)}
    assert press_targets(bindings, C, 2, 6, members) == set()  # other endpoint
    assert press_targets(bindings, C, None, 6, members) == {(L, 1), (P, None)}
    assert press_targets([_b(R, 6, C)], C, 1, 6, {}) == set()  # coordinator only


def test_entity_matches_endpoint():
    assert entity_matches_endpoint(f"{L}-1", L, 1)
    assert entity_matches_endpoint(f"{L}-1-6", L, 1)
    assert not entity_matches_endpoint(f"{L}-11", L, 1)
    assert not entity_matches_endpoint(f"{L}-2", L, 1)
    assert entity_matches_endpoint("anything", L, None)


def test_describe_change():
    on = {"state": "on", "attributes": {"brightness": 100}}
    off = {"state": "off", "attributes": {}}
    assert describe_change(off, on) == "turned on"
    assert describe_change(on, off) == "turned off"
    assert describe_change(on, {"state": "on", "attributes": {"brightness": 50}}) == "dimmed"
    assert describe_change(on, {"state": "on", "attributes": {"brightness": 200}}) == "brightened"
    assert describe_change(on, {"state": "on", "attributes": {"brightness": 100, "color_temp_kelvin": 3000}}) == "colour changed"
    assert describe_change(on, on) is None
    assert describe_change({"state": "unavailable", "attributes": {}}, on) is None
    assert describe_change(None, on) is None


def test_caused_by_home_assistant():
    assert not caused_by_home_assistant(Context())
    assert caused_by_home_assistant(Context(user_id="u"))
    assert caused_by_home_assistant(Context(parent_id="p"))


# --- with Home Assistant ---------------------------------------------------------------


async def _setup(hass, hass_storage, options):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, C), _b(R, 6, L), _b(R, 8, L)]})
    _zha_devices(hass)
    dev = dr.async_get(hass)
    ent = er.async_get(hass)
    zha_entry = hass.config_entries.async_entries("zha")[0]
    by_ieee = {
        v: d for d in dr.async_entries_for_config_entry(dev, zha_entry.entry_id) for (dom, v) in d.identifiers if dom == "zha"
    }
    light, plug = by_ieee[L], by_ieee[P]
    ent.async_get_or_create("light", "zha", f"{L}-1", device_id=light.id, config_entry=zha_entry, suggested_object_id="spots")
    ent.async_get_or_create("switch", "zha", f"{P}-1", device_id=plug.id, config_entry=zha_entry, suggested_object_id="plug")
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    logged = []
    hass.bus.async_listen("logbook_entry", lambda e: logged.append(dict(e.data)))
    hass.states.async_set("light.spots", "off", {"friendly_name": "Spots"})
    hass.states.async_set("switch.plug", "off", {"friendly_name": "Plug"})
    await hass.async_block_till_done()
    return logged


def _press(hass, cluster=6, command="on", ieee=R, endpoint=1):
    hass.bus.async_fire("zha_event", {"device_ieee": ieee, "endpoint_id": endpoint, "cluster_id": cluster, "command": command, "args": []})


async def test_off_by_default(hass: HomeAssistant, hass_storage):
    await _setup(hass, hass_storage, {})
    assert get_attribution(hass) is None


async def test_press_then_light_change_is_attributed(hass: HomeAssistant, hass_storage):
    logged = await _setup(hass, hass_storage, {OPT_LOGBOOK: True, OPT_DEVICE_PAGE: False})
    _press(hass)
    await hass.async_block_till_done()
    hass.states.async_set("light.spots", "on", {"friendly_name": "Spots", "brightness": 120})
    hass.states.async_set("switch.plug", "on", {"friendly_name": "Plug"})  # not bound: no entry
    await hass.async_block_till_done()
    assert logged == [
        {"name": "Spots", "message": "turned on by Rodret (direct binding)", "domain": DOMAIN, "entity_id": "light.spots"}
    ]
    # Holding to dim: one entry per light, not one per step.
    _press(hass, cluster=8, command="move")
    await hass.async_block_till_done()
    hass.states.async_set("light.spots", "on", {"friendly_name": "Spots", "brightness": 90})
    hass.states.async_set("light.spots", "on", {"friendly_name": "Spots", "brightness": 60})
    await hass.async_block_till_done()
    assert [e["message"] for e in logged] == ["turned on by Rodret (direct binding)", "dimmed by Rodret (direct binding)"]


async def test_changes_by_home_assistant_or_too_late_are_not_attributed(hass: HomeAssistant, hass_storage, monkeypatch):
    logged = await _setup(hass, hass_storage, {OPT_LOGBOOK: True})
    _press(hass)
    await hass.async_block_till_done()
    hass.states.async_set("light.spots", "on", {"friendly_name": "Spots"}, context=Context(parent_id="automation"))
    await hass.async_block_till_done()
    assert logged == []
    # Too late: past the window.
    monkeypatch.setattr(attr, "WINDOW_SECONDS", 0.0)
    _press(hass, command="off")
    await hass.async_block_till_done()
    await asyncio.sleep(0.01)
    hass.states.async_set("light.spots", "off", {"friendly_name": "Spots"})
    await hass.async_block_till_done()
    assert logged == []


async def test_reports_and_unbound_remotes_are_ignored(hass: HomeAssistant, hass_storage):
    logged = await _setup(hass, hass_storage, {OPT_LOGBOOK: True})
    _press(hass, command="attribute_updated")
    _press(hass, ieee=P)
    _press(hass, cluster=0x0005, command="recall")
    await hass.async_block_till_done()
    hass.states.async_set("light.spots", "on", {"friendly_name": "Spots"})
    await hass.async_block_till_done()
    assert logged == []


async def test_light_reporting_just_before_the_press_is_attributed(hass: HomeAssistant, hass_storage):
    """1.4.2: the light's own report can arrive before the press."""
    logged = await _setup(hass, hass_storage, {OPT_LOGBOOK: True})
    hass.states.async_set("light.spots", "on", {"friendly_name": "Spots"})
    await hass.async_block_till_done()
    assert logged == []
    _press(hass)
    await hass.async_block_till_done()
    assert [e["message"] for e in logged] == ["turned on by Rodret (direct binding)"]
    # Not claimed twice when the same press is followed by nothing else.
    _press(hass)
    await hass.async_block_till_done()
    assert len(logged) == 1


async def test_change_long_before_the_press_is_not_attributed(hass: HomeAssistant, hass_storage, monkeypatch):
    logged = await _setup(hass, hass_storage, {OPT_LOGBOOK: True})
    monkeypatch.setattr(attr, "LOOKBACK_SECONDS", 0.0)
    hass.states.async_set("light.spots", "on", {"friendly_name": "Spots"})
    await hass.async_block_till_done()
    await asyncio.sleep(0.01)
    _press(hass)
    await hass.async_block_till_done()
    assert logged == []
