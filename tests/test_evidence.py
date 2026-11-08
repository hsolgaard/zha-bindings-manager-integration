"""Address changes and missed presses (1.10.0)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.zha_bindings_manager.const import DOMAIN
from custom_components.zha_bindings_manager.evidence import (
    address_at,
    changes_between,
    get_evidence,
    prune,
    record_address,
)

from .test_device_page import L, R, _zha_device
from .test_watch import setup  # noqa: F401 - fixture


def test_history_keeps_changes_only_and_prunes_old_ones():
    h = {}
    assert record_address(h, L, "0x1a2b", "snapshot", "2026-01-01T00:00:00+00:00")
    assert not record_address(h, L, "0x1a2b", "snapshot", "2026-01-02T00:00:00+00:00")
    assert record_address(h, L, "0x5c3d", "joined", "2026-11-08T03:12:00+00:00")
    assert [e["nwk"] for e in h[L]] == ["0x1a2b", "0x5c3d"]
    assert address_at(h[L], "2026-06-01T00:00:00+00:00") == "0x1a2b"
    assert address_at(h[L], None) == "0x5c3d"
    assert [e["nwk"] for e in changes_between(h[L], "2026-06-01T00:00:00+00:00", "2026-11-09T00:00:00+00:00")] == ["0x5c3d"]
    prune(h, datetime(2026, 11, 9, tzinfo=timezone.utc))
    assert [e["nwk"] for e in h[L]] == ["0x5c3d"]  # the old one is past 90 days; the latest always stays


def _fake_zigpy(ev, addresses):
    ev.zigpy_devices = lambda: {i: SimpleNamespace(ieee=i, nwk=n) for i, n in addresses.items()}


async def _light(hass, state):
    dev = _zha_device(hass, L)
    er.async_get(hass).async_get_or_create("light", "zha", f"{L}-1", device_id=dev.id, suggested_object_id="spots")
    hass.states.async_set("light.spots", state)
    st = hass.states.get("light.spots")
    object.__setattr__(st, "last_changed", dt_util.utcnow() - timedelta(minutes=5))


def _press(hass, command="on"):
    hass.bus.async_fire("zha_event", {"device_ieee": R, "cluster_id": 6, "endpoint_id": 1, "command": command})


async def test_records_addresses_and_ties_a_missed_press_to_an_address_change(setup, hass_ws_client):
    hass, watch, state = setup
    ev = get_evidence(hass)
    ev.wait = 0
    _fake_zigpy(ev, {L: 0x1A2B, R: 0x0042})
    ev.snapshot()
    await _light(hass, "off")
    # a press that works: the light changes straight away
    _press(hass)
    hass.states.async_set("light.spots", "on")
    await hass.async_block_till_done()
    pair = ev.pairs[f"{R}|{L}|1"]
    assert pair["followed"] == 1 and pair["last_ok_nwk"] == "0x1a2b"
    # the light gets a new short address (re-pair, conflict…), then a press goes nowhere
    _fake_zigpy(ev, {L: 0x5C3D, R: 0x0042})
    ev.device_joined(SimpleNamespace(ieee=L, nwk=0x5C3D))
    await _light(hass, "on")
    _press(hass, "off")
    await hass.async_block_till_done()
    miss = ev.misses[-1]
    assert miss["light"] == L and miss["nwk_now"] == "0x5c3d" and miss["nwk_at_last_ok"] == "0x1a2b"
    assert miss["address_changed_since_last_ok"] is True and miss["binding_in_last_read"] is True
    assert [c["seen"] for c in miss["changes_since_last_ok"]] == ["joined"]
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/evidence_get"})
    res = (await client.receive_json())["result"]
    assert res["changed"] == [L] and res["misses"][-1]["light_name"] == "Spots"


async def test_a_light_already_as_wanted_is_not_a_miss(setup):
    hass, watch, state = setup
    ev = get_evidence(hass)
    ev.wait = 0
    await _light(hass, "on")
    _press(hass, "on")
    await hass.async_block_till_done()
    assert ev.misses == [] and ev.pairs[f"{R}|{L}|1"]["presses"] == 1


async def test_can_be_turned_off(hass, hass_ws_client, hass_storage):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.zha_bindings_manager.const import OPT_EVIDENCE, TITLE

    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options={OPT_EVIDENCE: False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert get_evidence(hass) is None
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/evidence_get"})
    assert (await client.receive_json())["error"]["code"] == "not_enabled"
