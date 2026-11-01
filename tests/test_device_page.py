"""Bindings sensor and Rescan button on ZHA device pages (1.2.0), against
real Home Assistant core."""
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.zha_bindings_manager.const import DOMAIN, OPT_DEVICE_PAGE, STORAGE_KEY, TITLE

R = "aa:aa:aa:aa:aa:aa:aa:01"
L = "bb:bb:bb:bb:bb:bb:bb:02"
P = "cc:cc:cc:cc:cc:cc:cc:03"
C = "00:12:4b:00:00:00:00:01"


def _b(src, cid, target, ep=1):
    return {"sourceIeee": src, "sourceEndpoint": 1, "clusterId": cid, "isGroup": False, "targetIeee": target, "targetEndpoint": ep, "groupId": None}


def _card_state(bindings, saved_at="2026-11-01T10:00:00+00:00"):
    return {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {
            "zha-bindings-manager": {
                "updated_at": saved_at,
                "state": {"scanState": {"last_complete": {"savedAt": saved_at, "bindings": bindings}}},
            }
        },
    }


def _zha_devices(hass):
    zha = MockConfigEntry(domain="zha", title="ZHA")
    zha.add_to_hass(hass)
    reg = dr.async_get(hass)
    for ieee, name in ((R, "Rodret"), (L, "Spots"), (P, "Plug"), (C, "Coordinator")):
        reg.async_get_or_create(
            config_entry_id=zha.entry_id,
            identifiers={("zha", ieee)},
            connections={(dr.CONNECTION_ZIGBEE, ieee)},
            name=name,
        )
    return reg


async def _setup(hass, options=None):
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entities_for(hass, ieee):
    dev = dr.async_get(hass).async_get_device(identifiers={("zha", ieee)})
    return sorted(e.entity_id for e in er.async_entries_for_device(er.async_get(hass), dev.id))


async def test_entities_only_on_bound_devices_and_attached_to_the_zha_device(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 0x20, C), _b(R, 6, L), _b(R, 8, L)], L: [_b(L, 6, C)], P: [_b(P, 6, C)]})
    reg = _zha_devices(hass)
    await _setup(hass)
    devices_before = len(reg.devices)
    assert _entities_for(hass, R) == ["button.rodret_rescan_bindings", "sensor.rodret_bindings"]
    assert _entities_for(hass, L) == ["button.spots_rescan_bindings", "sensor.spots_bindings"]
    assert _entities_for(hass, P) == []  # coordinator-only bindings: nothing added
    assert len(reg.devices) == devices_before  # no new devices created
    st = hass.states.get("sensor.rodret_bindings")
    assert st.state == "Controls Spots (On/Off, Level Control)"
    assert st.attributes["controls"] == ["Spots (On/Off, Level Control)"]
    assert hass.states.get("sensor.spots_bindings").state == "Controlled by Rodret (On/Off, Level Control)"


async def test_option_off_adds_nothing(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)
    await _setup(hass, {OPT_DEVICE_PAGE: False})
    assert _entities_for(hass, R) == []


async def test_rescan_button_updates_and_entities_follow_the_data(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)
    replies = {"value": {"success": True, "result": {"0": {"src_ep": 1, "cluster_id": "0x0006", "dst": {"addrmode": 3, "dst_ieee": P, "dst_ep": 1}}}}}

    async def binds_get(call):
        return replies["value"]

    hass.services.async_register("zha_toolkit", "binds_get", binds_get, supports_response=SupportsResponse.ONLY)
    await _setup(hass)
    assert hass.states.get("sensor.rodret_bindings").state == "Controls Spots (On/Off)"

    # Rescan: the Rodret now controls the plug instead of the light.
    await hass.services.async_call("button", "press", {"entity_id": "button.rodret_rescan_bindings"}, blocking=True)
    await hass.async_block_till_done()
    st = hass.states.get("sensor.rodret_bindings")
    assert st.state == "Controls Plug (On/Off)"
    assert st.attributes["last_rescanned"]
    assert hass.states.get("sensor.plug_bindings").state == "Controlled by Rodret (On/Off)"
    # The light is no longer bound to anything: its entities go away.
    assert _entities_for(hass, L) == []
    assert hass.states.get("sensor.spots_bindings") is None

    # A device that doesn't answer gives a clear error, nothing changes.
    replies["value"] = {"success": False, "errors": ["Timeout"]}
    with pytest.raises(HomeAssistantError, match="Battery devices are usually asleep"):
        await hass.services.async_call("button", "press", {"entity_id": "button.rodret_rescan_bindings"}, blocking=True)
    assert hass.states.get("sensor.rodret_bindings").state == "Controls Plug (On/Off)"


async def test_card_save_refreshes_the_device_page(hass: HomeAssistant, hass_storage, hass_ws_client):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/save_state", "card_id": "zha-bindings-manager",
                            "state": {"scanState": {"last_complete": {"savedAt": "2026-11-02T10:00:00+00:00", "bindings": {R: [_b(R, 8, L)]}}}},
                            "base_updated_at": "2026-11-01T10:00:00+00:00"})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.rodret_bindings").state == "Controls Spots (Level Control)"


async def test_unload_removes_platforms(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.rodret_bindings").state == "unavailable"


async def test_card_save_does_not_override_a_newer_device_page_rescan(hass: HomeAssistant, hass_storage, hass_ws_client):
    """The card stamps its whole scan data on every save; what counts per
    device is when the card last read that device (history.lastSuccessAt)."""
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)

    async def binds_get(call):
        return {"success": True, "result": {"0": {"src_ep": 1, "cluster_id": "0x0006", "dst": {"addrmode": 3, "dst_ieee": P, "dst_ep": 1}}}}

    hass.services.async_register("zha_toolkit", "binds_get", binds_get, supports_response=SupportsResponse.ONLY)
    await _setup(hass)
    await hass.services.async_call("button", "press", {"entity_id": "button.rodret_rescan_bindings"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.rodret_bindings").state == "Controls Plug (On/Off)"
    # The card saves later (it scanned some other device); its copy of the
    # Rodret was read before the rescan, so the rescan still wins.
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/save_state", "card_id": "zha-bindings-manager",
                            "state": {"scanState": {"last_complete": {"savedAt": "2099-01-01T00:00:00+00:00", "bindings": {R: [_b(R, 6, L)]}}},
                                      "history": {R: {"lastSuccessAt": "2026-11-01T10:00:00+00:00"}}},
                            "base_updated_at": "2026-11-01T10:00:00+00:00"})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.rodret_bindings").state == "Controls Plug (On/Off)"
