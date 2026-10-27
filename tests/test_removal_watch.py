"""Tests for the removed-device notice, against a real Home Assistant core
(pytest-homeassistant-custom-component). Not shipped with the integration."""
from homeassistant.components import persistent_notification as pn
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import storage
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zha_bindings_manager.const import DOMAIN, STORAGE_KEY, STORAGE_VERSION
from custom_components.zha_bindings_manager.stale import (
    bindings_to_removed_target,
    notification_id,
)

SWITCH = "aa:aa:aa:aa:aa:aa:aa:01"
SWITCH2 = "aa:aa:aa:aa:aa:aa:aa:03"
BULB = "aa:aa:aa:aa:aa:aa:aa:02"
GONE_SOURCE = "00:0d:6f:ff:fe:bc:cc:e0"


def _b(src, tgt, cluster, ep=1, group=False):
    return {"sourceIeee": src, "sourceEndpoint": ep, "clusterId": cluster, "isGroup": group,
            "targetIeee": None if group else tgt, "targetEndpoint": None if group else 1}


def _saved():
    bindings = {
        SWITCH: [_b(SWITCH, BULB, 6), _b(SWITCH, BULB, 8), _b(SWITCH, None, 6, group=True)],
        SWITCH2: [_b(SWITCH2, BULB.upper(), 6)],
        GONE_SOURCE: [_b(GONE_SOURCE, BULB, 6)],
    }
    state = {"items": {}, "scanState": {"last_complete": {"bindings": bindings}}, "history": {}}
    # Two card instances holding the same scan must not double count.
    return {"default": {"updated_at": "t", "state": state}, "second": {"updated_at": "t", "state": state}}


def test_counts_live_sources_once_and_ignores_groups_and_removed_sources():
    assert bindings_to_removed_target(_saved(), BULB, {SWITCH, SWITCH2}) == {SWITCH: 2, SWITCH2: 1}
    # Without a live list, every other saved source counts.
    assert bindings_to_removed_target(_saved(), BULB) == {SWITCH: 2, SWITCH2: 1, GONE_SOURCE: 1}
    assert bindings_to_removed_target(_saved(), "ff:ff") == {}
    assert bindings_to_removed_target({}, BULB) == {}
    assert bindings_to_removed_target({"x": {"state": None}}, BULB) == {}


async def _setup(hass: HomeAssistant):
    zha_entry = MockConfigEntry(domain="zha")
    zha_entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    devices = {}
    for ieee, name in ((SWITCH, "Hall Switch"), (SWITCH2, "Landing Switch"), (BULB, "Hall Bulb")):
        devices[ieee] = reg.async_get_or_create(
            config_entry_id=zha_entry.entry_id, identifiers={("zha", ieee)}, name=name
        )
    await storage.Store(hass, STORAGE_VERSION, STORAGE_KEY).async_save(_saved())
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return reg, zha_entry, devices, entry


def _notices(hass):
    return pn._async_get_or_create_notifications(hass)


async def test_notifies_when_bound_target_removed_and_dismisses_on_repair(hass: HomeAssistant):
    reg, zha_entry, devices, _ = await _setup(hass)
    reg.async_remove_device(devices[BULB].id)
    await hass.async_block_till_done()

    nid = notification_id(DOMAIN, BULB)
    notices = _notices(hass)
    assert nid in notices
    msg = notices[nid]["message"]
    assert "Hall Bulb" in msg and "3 bindings on 2 devices" in msg
    assert "Hall Switch (2)" in msg and "Landing Switch (1)" in msg

    # Paired again with the same address: dismissed.
    reg.async_get_or_create(config_entry_id=zha_entry.entry_id, identifiers={("zha", BULB)}, name="Hall Bulb")
    await hass.async_block_till_done()
    assert nid not in _notices(hass)


async def test_no_notice_when_nothing_points_to_removed_device(hass: HomeAssistant):
    reg, _, devices, _ = await _setup(hass)
    reg.async_remove_device(devices[SWITCH].id)
    await hass.async_block_till_done()
    assert notification_id(DOMAIN, SWITCH) not in _notices(hass)


async def test_stops_watching_after_unload(hass: HomeAssistant):
    reg, _, devices, entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    reg.async_remove_device(devices[BULB].id)
    await hass.async_block_till_done()
    assert notification_id(DOMAIN, BULB) not in _notices(hass)
