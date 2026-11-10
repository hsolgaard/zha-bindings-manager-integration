"""Lost bindings (1.3.0, reworked 1.8.0): noticed on every read, put back, per-device policy."""
from datetime import timedelta

import pytest
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.zha_bindings_manager.const import DOMAIN, OPT_WATCH, STORAGE_KEY, TITLE
from custom_components.zha_bindings_manager.bindings import identity_key
from custom_components.zha_bindings_manager.watch import AUTO_LIMIT, ISSUE_ID, compare_read, get_watch, key_matches

from .test_device_page import C, L, P, R, _b, _card_state, _zha_devices


def test_compare_read_marks_lost_at_once_and_learns_new_bindings():
    a, b2 = {"sourceIeee": R, "clusterId": 6}, {"sourceIeee": R, "clusterId": 8}
    exp, lost, newly = compare_read({"a": a}, {}, {}, "scan", "t1")
    assert newly == ["a"] and lost == {"a": {"since": "t1", "noticed_by": "scan"}} and exp == {"a": a}
    exp, lost, newly = compare_read(exp, lost, {"b": b2}, "nightly", "t2")
    assert newly == [] and lost["a"]["since"] == "t1" and set(exp) == {"a", "b"}  # still lost, first noticed kept
    exp, lost, newly = compare_read(exp, lost, {"a": a, "b": b2}, "scan", "t3")
    assert lost == {} and newly == []


def _table(*bindings):
    return {"success": True, "result": {str(i): {"src_ep": 1, "cluster_id": f"0x{c:04x}", "dst": {"addrmode": 3, "dst_ieee": t, "dst_ep": 1}} for i, (c, t) in enumerate(bindings)}}


@pytest.fixture
async def setup(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 0x20, C), _b(R, 6, L)], L: [_b(L, 6, C)], P: [_b(P, 6, C)]})
    _zha_devices(hass)
    state = {"table": _table((0x20, C), (6, L)), "answer": True, "bound": []}

    async def binds_get(call):
        if not state["answer"]:
            return {"success": False, "errors": ["Timeout"]}
        return state["table"]

    async def bind_ieee(call):
        state["bound"].append(dict(call.data))
        state["table"] = _table((0x20, C), (call.data["cluster"], call.data["command_data"]))
        return {"success": True}

    hass.services.async_register("zha_toolkit", "binds_get", binds_get, supports_response=SupportsResponse.ONLY)
    hass.services.async_register("zha_toolkit", "bind_ieee", bind_ieee, supports_response=SupportsResponse.OPTIONAL)
    assert await async_setup_component(hass, "repairs", {})
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options={OPT_WATCH: True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    watch = get_watch(hass)
    watch.pause = 0
    return hass, watch, state


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)


async def test_on_by_default(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert get_watch(hass) is not None


async def test_turned_on_for_existing_installs_once(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options={OPT_WATCH: False}, version=1, minor_version=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.options[OPT_WATCH] is True and entry.minor_version == 2


async def test_off_when_switched_off(hass: HomeAssistant, hass_storage):
    _zha_devices(hass)
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options={OPT_WATCH: False}, version=1, minor_version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert get_watch(hass) is None


async def test_expected_bindings_come_from_the_card(setup):
    hass, watch, _ = setup
    assert set(watch.tracked) == {R}  # only devices with real relationships
    assert len(watch.tracked[R]["expected"]) == 1 and watch.tracked[R]["policy"] == "notify"


async def test_lost_on_first_read_and_silence_when_asleep(setup):
    hass, watch, state = setup
    assert await watch.async_check_device(R) == []
    state["answer"] = False  # asleep: doesn't count
    state["table"] = _table((0x20, C))
    assert await watch.async_check_device(R) is None
    assert _issue(hass) is None
    state["answer"] = True
    lost = await watch.async_check_device(R)  # one successful read is enough
    assert len(lost) == 1
    issue = _issue(hass)
    assert issue.is_fixable and issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["count"] == "1"
    assert "Rodret: 1" in issue.translation_placeholders["devices"]
    summary = watch.summary()["devices"][R]
    assert summary["lost"][0]["noticed_by"] == "nightly" and "On/Off from endpoint 1 → Spots" in summary["lost"][0]["text"]


async def _scan_from_card(hass, client, bindings, at, msg_id=1):
    await client.send_json({"id": msg_id, "type": f"{DOMAIN}/get_state", "card_id": "zha-bindings-manager"})
    reply = await client.receive_json()
    assert reply.get("success"), reply
    base = (reply.get("result") or {}).get("updated_at")
    await client.send_json({"id": msg_id + 100, "type": f"{DOMAIN}/save_state", "card_id": "zha-bindings-manager",
                            "state": {"scanState": {"last_complete": {"savedAt": at, "bindings": {R: bindings}}},
                                      "history": {R: {"lastSuccessAt": at}}}, "base_updated_at": base})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()


async def test_a_card_scan_notices_the_loss_instead_of_accepting_it(setup, hass_ws_client):
    """Before 1.8.0 a scan replaced the expected set, hiding the loss."""
    hass, watch, state = setup
    client = await hass_ws_client(hass)
    await _scan_from_card(hass, client, [_b(R, 0x20, C)], "2099-01-01T00:00:00+00:00")
    assert len(watch.lost(R)) == 1 and watch.summary()["devices"][R]["lost"][0]["noticed_by"] == "scan"
    assert len(watch.tracked[R]["expected"]) == 1  # still expected
    assert _issue(hass) is not None
    # A later scan where it's back clears it.
    await _scan_from_card(hass, client, [_b(R, 0x20, C), _b(R, 6, L)], "2099-01-02T00:00:00+00:00", 200)
    assert watch.lost(R) == [] and _issue(hass) is None


async def test_unbinding_in_the_card_is_not_reported(setup, hass_ws_client):
    hass, watch, state = setup
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/watch_removed", "bindings": [_b(R, 6, L)]})
    assert (await client.receive_json())["result"] == {"removed": 1}
    await _scan_from_card(hass, client, [_b(R, 0x20, C)], "2099-01-01T00:00:00+00:00", 200)
    assert watch.lost(R) == [] and _issue(hass) is None
    assert watch.tracked[R]["expected"] == {}


def test_removal_patterns_match_like_the_card_unbinds():
    direct = identity_key(_b(R, 6, L))
    group = identity_key({"sourceIeee": R, "sourceEndpoint": 2, "clusterId": 8, "isGroup": True, "groupId": 4845})
    assert key_matches(direct, {"sourceIeee": R, "targetIeee": L, "clusterIds": [6, 8]})  # unbindIeee
    assert not key_matches(direct, {"sourceIeee": R, "targetIeee": L, "clusterIds": [8]})
    assert not key_matches(direct, {"sourceIeee": R, "targetIeee": C})
    assert key_matches(direct, {"sourceIeee": R, "targetIeee": L, "targetEndpoint": 1})
    assert not key_matches(direct, {"sourceIeee": R, "targetIeee": L, "targetEndpoint": 2})
    assert key_matches(group, {"sourceIeee": R, "isGroup": True, "groupId": 4845})  # unbindGroup
    assert not key_matches(group, {"sourceIeee": R, "isGroup": True, "groupId": 1})
    assert not key_matches(direct, {"sourceIeee": R, "isGroup": True})
    assert key_matches(group, {"sourceIeee": R, "sourceEndpoint": 2, "clusterId": 8})  # removeBindingsOnCluster
    assert not key_matches(group, {"sourceIeee": R, "sourceEndpoint": 1, "clusterId": 8})
    assert not key_matches(direct, {"sourceIeee": L})
    assert not key_matches(direct, {"sourceIeee": R, "clusterIds": ["x"]})


async def test_wildcard_removal_drops_lost_too(setup, hass_ws_client):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    assert len(watch.lost(R)) == 1
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/watch_removed", "bindings": [{"sourceIeee": R, "targetIeee": L}]})
    assert (await client.receive_json())["result"] == {"removed": 1}
    assert watch.lost(R) == [] and _issue(hass) is None


async def test_put_back_binds_checks_and_clears(setup, hass_ws_client):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/watch_put_back"})
    res = (await client.receive_json())["result"]
    assert res["results"][R]["status"] == "put_back" and res["results"][R]["count"] == 1
    assert state["bound"] == [{"ieee": R, "command_data": L, "cluster": 6, "endpoint": 1, "dst_endpoint": 1}]
    assert _issue(hass) is None and watch.lost(R) == []


async def test_put_back_waits_for_a_sleeping_device_then_goes_on_its_next_press(setup):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    state["answer"] = False
    res = await watch.async_put_back(R)
    assert res["status"] == "waiting" and watch.tracked[R]["queued"] is True
    state["answer"] = True
    hass.bus.async_fire("zha_event", {"device_ieee": R, "command": "on"})
    await hass.async_block_till_done()
    assert watch.lost(R) == [] and watch.tracked[R]["queued"] is False


async def test_repairs_puts_them_all_back(setup):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    manager = repairs_flow_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": ISSUE_ID})
    assert flow["type"] == "form" and flow["step_id"] == "confirm" and "Rodret: 1" in flow["description_placeholders"]["devices"]
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    assert _issue(hass) is None


async def test_repairs_says_who_is_still_waiting(setup):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    state["answer"] = False
    manager = repairs_flow_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": ISSUE_ID})
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "form" and flow["errors"] == {"base": "not_all"}
    assert "Waiting for a button press" in flow["description_placeholders"]["result"]


async def test_removed_on_purpose(setup, hass_ws_client):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/watch_forget", "ieee": R})
    res = (await client.receive_json())["result"]
    assert res["devices"].get(R, {"lost": []})["lost"] == [] and watch.tracked[R]["expected"] == {}
    assert _issue(hass) is None


async def test_auto_puts_back_straight_away_and_logs(setup, hass_ws_client):
    hass, watch, state = setup
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/watch_policy", "ieee": R, "policy": "auto"})
    assert (await client.receive_json())["success"]
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    await hass.async_block_till_done()
    assert watch.lost(R) == [] and len(state["bound"]) == 1
    assert _issue(hass) is None


async def test_auto_stops_after_three_a_day(setup):
    hass, watch, state = setup
    watch.set_policy(R, "auto")
    for i in range(AUTO_LIMIT + 1):
        state["table"] = _table((0x20, C))  # loses it again every time
        await watch.async_check_device(R)
        await hass.async_block_till_done()
    assert watch.tracked[R]["auto_paused"] is True and len(state["bound"]) == AUTO_LIMIT
    issue = _issue(hass)
    assert issue is not None and "keeps losing them" in issue.translation_placeholders["paused"]
    # The Repairs fix form shows it too (a fixable issue has no description of its own).
    assert "keeps losing them" in watch.paused_text()


async def test_auto_device_checked_after_a_press(setup):
    hass, watch, state = setup
    watch.set_policy(R, "auto")
    state["table"] = _table((0x20, C))
    hass.bus.async_fire("zha_event", {"device_ieee": R, "command": "on"})
    await hass.async_block_till_done()
    assert watch.tracked[R]["last_check"] is not None and watch.lost(R) == [] and len(state["bound"]) == 1
    # Checked just now: the next press within 10 minutes doesn't read it again.
    before = watch.tracked[R]["last_check"]
    hass.bus.async_fire("zha_event", {"device_ieee": R, "command": "on"})
    await hass.async_block_till_done()
    assert watch.tracked[R]["last_check"] == before


async def test_off_stops_tracking_a_device(setup):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    watch.set_policy(R, "off")
    assert watch.lost(R) == [] and _issue(hass) is None
    assert await watch.async_check_device(R) is None


async def test_nightly_check_at_0317(setup):
    hass, watch, state = setup
    assert watch.tracked[R].get("last_check") is None
    now = dt_util.now()
    target = now.replace(hour=3, minute=17, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    async_fire_time_changed(hass, target)
    await hass.async_block_till_done()
    assert watch.tracked[R]["last_check"] is not None


async def test_rescan_button_counts_as_a_check(setup):
    """With the watch on, one Rescan press after a binding disappears reports it."""
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await hass.services.async_call("button", "press", {"entity_id": "button.rodret_rescan_bindings"}, blocking=True)
    await hass.async_block_till_done()
    assert _issue(hass) is not None
    assert hass.states.get("sensor.rodret_bindings").state == "No bindings"
