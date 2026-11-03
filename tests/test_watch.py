"""1.3.0: noticing bindings that disappear, Repairs issue, Re-apply/Forget."""
from datetime import timedelta

import pytest
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.zha_bindings_manager.bindings import evaluate_check
from custom_components.zha_bindings_manager.const import DOMAIN, OPT_WATCH, STORAGE_KEY, TITLE
from custom_components.zha_bindings_manager.watch import get_watch, issue_id_for

from .test_device_page import C, L, P, R, _b, _card_state, _zha_devices


def test_evaluate_check_needs_two_misses_and_learns_new_bindings():
    a, b2 = {"sourceIeee": R, "clusterId": 6}, {"sourceIeee": R, "clusterId": 8}
    exp, misses, missing = evaluate_check({"a": a}, {}, {})
    assert misses == {"a": 1} and missing == []
    exp, misses, missing = evaluate_check(exp, misses, {"b": b2})
    assert misses == {"a": 2} and missing == [a] and set(exp) == {"a", "b"}
    exp, misses, missing = evaluate_check(exp, misses, {"a": a, "b": b2})
    assert misses == {} and missing == []


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
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id_for(R))


async def test_off_by_default(hass: HomeAssistant, hass_storage):
    hass_storage[STORAGE_KEY] = _card_state({R: [_b(R, 6, L)]})
    _zha_devices(hass)
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert get_watch(hass) is None


async def test_expected_bindings_come_from_the_card(setup):
    hass, watch, _ = setup
    assert set(watch.tracked) == {R}  # only devices with real relationships
    assert len(watch.tracked[R]["expected"]) == 1


async def test_issue_after_two_misses_and_silence_when_asleep(setup):
    hass, watch, state = setup
    assert await watch.async_check_device(R) == []
    state["table"] = _table((0x20, C))  # the binding to the light is gone
    assert await watch.async_check_device(R) == []
    assert _issue(hass) is None
    state["answer"] = False  # asleep: doesn't count
    assert await watch.async_check_device(R) is None
    assert _issue(hass) is None
    state["answer"] = True
    missing = await watch.async_check_device(R)
    assert len(missing) == 1
    issue = _issue(hass)
    assert issue.is_fixable and issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["device"] == "Rodret"
    assert "On/Off from endpoint 1 → Spots" in issue.translation_placeholders["bindings"]
    assert issue.learn_more_url == f"/zha-bindings-manager?device={R}"


async def _make_issue(watch, state):
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)
    await watch.async_check_device(R)


async def test_reapply_binds_checks_and_clears_the_issue(setup):
    hass, watch, state = setup
    await _make_issue(watch, state)
    manager = repairs_flow_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": issue_id_for(R)})
    assert flow["type"] == "menu" and flow["menu_options"] == ["reapply", "forget"]
    # 1.5.0: the text links to the device in the card when the sidebar page is on.
    from custom_components.zha_bindings_manager.const import OPT_SIDEBAR_PANEL
    from custom_components.zha_bindings_manager.options import current_options

    link = flow["description_placeholders"]["card_link"]
    if current_options(hass)[OPT_SIDEBAR_PANEL]:
        assert f"(/zha-bindings-manager?device={R})" in link
    else:
        assert link == ""
    flow = await manager.async_configure(flow["flow_id"], {"next_step_id": "reapply"})
    assert flow["type"] == "form" and flow["step_id"] == "reapply"
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    assert state["bound"] == [{"ieee": R, "command_data": L, "cluster": 6, "endpoint": 1, "dst_endpoint": 1}]
    assert _issue(hass) is None
    assert await watch.async_check_device(R) == []


async def test_reapply_that_does_not_take_says_so(setup):
    hass, watch, state = setup
    await _make_issue(watch, state)
    state["answer"] = False
    manager = repairs_flow_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": issue_id_for(R)})
    flow = await manager.async_configure(flow["flow_id"], {"next_step_id": "reapply"})
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "form" and flow["errors"] == {"base": "still_missing"}
    assert _issue(hass) is not None


async def test_forget_stops_expecting_them(setup):
    hass, watch, state = setup
    await _make_issue(watch, state)
    manager = repairs_flow_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": issue_id_for(R)})
    flow = await manager.async_configure(flow["flow_id"], {"next_step_id": "forget"})
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    assert _issue(hass) is None
    assert watch.tracked[R]["expected"] == {}
    assert await watch.async_check_device(R) is None  # nothing left to watch on it


async def test_unbinding_in_the_card_is_not_reported(setup, hass_ws_client):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    await watch.async_check_device(R)  # one miss so far
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/save_state", "card_id": "zha-bindings-manager",
                            "state": {"scanState": {"last_complete": {"savedAt": "2099-01-01T00:00:00+00:00", "bindings": {R: [_b(R, 0x20, C)]}}},
                                      "history": {R: {"lastSuccessAt": "2099-01-01T00:00:00+00:00"}}},
                            "base_updated_at": "2026-11-01T10:00:00+00:00"})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert watch.tracked[R]["expected"] == {}
    assert await watch.async_check_device(R) is None  # nothing left to watch
    assert _issue(hass) is None


async def test_battery_device_checked_when_it_wakes(setup):
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    watch.tracked[R]["misses"] = {next(iter(watch.tracked[R]["expected"])): 1}
    hass.bus.async_fire("zha_event", {"device_ieee": R, "command": "on"})
    await hass.async_block_till_done()
    assert _issue(hass) is not None
    # Checked just now, so the next press doesn't trigger another read.
    calls_before = watch.tracked[R]["last_check"]
    hass.bus.async_fire("zha_event", {"device_ieee": R, "command": "on"})
    await hass.async_block_till_done()
    assert watch.tracked[R]["last_check"] == calls_before


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
    """With the watch on, two Rescan presses after a binding disappears raise
    the Repairs issue, so it can be tested without waiting for the night."""
    hass, watch, state = setup
    state["table"] = _table((0x20, C))
    for _ in range(2):
        await hass.services.async_call("button", "press", {"entity_id": "button.rodret_rescan_bindings"}, blocking=True)
        await hass.async_block_till_done()
    assert _issue(hass) is not None
    # It lost its only binding, but its entities stay while it's watched.
    assert hass.states.get("sensor.rodret_bindings").state == "No bindings"
    state["answer"] = False
    with pytest.raises(Exception, match="usually asleep"):
        await hass.services.async_call("button", "press", {"entity_id": "button.rodret_rescan_bindings"}, blocking=True)
