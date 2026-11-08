"""Switch them from Home Assistant if they don't respond (1.8.0, R22–R24)."""
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.zha_bindings_manager.const import DOMAIN
from custom_components.zha_bindings_manager.fallback import direct_targets, wanted_state

from .test_device_page import C, L, R, _b, _zha_device
from .test_watch import setup  # noqa: F401 - fixture

G = {"sourceIeee": R, "sourceEndpoint": 1, "clusterId": 6, "isGroup": True, "groupId": 5}


def test_targets_are_direct_on_off_bindings_from_that_endpoint():
    exp = {"a": _b(R, 6, L), "b": _b(R, 8, L), "g": G, "c": {**_b(R, 6, C), "sourceEndpoint": 2}}
    assert direct_targets(exp, 1) == [(L, 1)]
    assert set(direct_targets(exp, None)) == {(L, 1), (C, 1)}


def test_what_the_lights_should_be():
    assert wanted_state("on", [(False, "off")]) == "on"
    assert wanted_state("toggle", [(False, "off"), (False, "off")]) == "on"
    assert wanted_state("toggle", [(False, "on"), (False, "off")]) is None  # didn't agree
    assert wanted_state("toggle", [(True, "on"), (False, "off")]) == "on"  # one responded
    assert wanted_state("toggle", [(True, "on"), (False, "on")]) is None
    assert wanted_state("move", [(False, "off")]) is None


async def _with_light(hass, state="off"):
    dev = _zha_device(hass, L)
    er.async_get(hass).async_get_or_create("light", "zha", f"{L}-1", device_id=dev.id, suggested_object_id="spots")
    hass.states.async_set("light.spots", state)
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(("on", call.data["entity_id"])))
    hass.services.async_register("light", "turn_off", lambda call: calls.append(("off", call.data["entity_id"])))
    return calls


async def test_switches_a_light_that_missed_the_press_and_checks_the_remote(setup, hass_ws_client):
    hass, watch, state = setup
    calls = await _with_light(hass, "off")
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/watch_fallback", "ieee": R, "enabled": True})
    res = await client.receive_json()
    assert res["success"] and res["result"]["devices"][R]["fallback"] is True
    watch.fallback.wait = 0
    state["table"] = _table_without_light()
    _age(hass, "light.spots")  # the light last changed well before the press
    hass.bus.async_fire("zha_event", {"device_ieee": R, "cluster_id": 6, "endpoint_id": 1, "command": "on"})
    await hass.async_block_till_done()
    assert calls == [("on", "light.spots")]
    assert watch.lost(R)  # the check after the press noticed the binding had gone


async def test_leaves_lights_that_responded_and_devices_without_it(setup):
    hass, watch, state = setup
    calls = await _with_light(hass, "off")
    watch.fallback.wait = 0
    hass.bus.async_fire("zha_event", {"device_ieee": R, "cluster_id": 6, "endpoint_id": 1, "command": "on"})
    await hass.async_block_till_done()
    assert calls == []  # fallback is off by default
    watch.set_fallback(R, True)
    hass.states.async_set("light.spots", "on")  # changed right at the press
    hass.bus.async_fire("zha_event", {"device_ieee": R, "cluster_id": 6, "endpoint_id": 1, "command": "on"})
    await hass.async_block_till_done()
    assert calls == []


def _age(hass, entity_id):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    st = hass.states.get(entity_id)
    object.__setattr__(st, "last_changed", dt_util.utcnow() - timedelta(minutes=5))


def _table_without_light():
    from .test_watch import _table

    return _table((0x20, C))
