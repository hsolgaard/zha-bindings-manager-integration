"""Replace a device (1.9.0)."""
from homeassistant.core import SupportsResponse

from custom_components.zha_bindings_manager.const import DOMAIN
from custom_components.zha_bindings_manager.replace import build_plan, inventory, map_endpoint, endpoints_of

from .test_device_page import C, L, P, R, _b
from .test_watch import _table, setup  # noqa: F401 - fixture

N = "aa:bb:cc:dd:ee:ff:00:11"  # the new light


def cl(ep, cid, kind):
    return {"endpoint_id": ep, "id": cid, "type": kind}


LIGHT = [cl(1, 0x0004, "in"), cl(1, 0x0006, "in"), cl(1, 0x0008, "in")]
ONOFF_ONLY = [cl(1, 0x0004, "in"), cl(1, 0x0006, "in")]
REMOTE = [cl(1, 0x0006, "out"), cl(1, 0x0008, "out")]


def test_endpoint_mapping_prefers_same_number_then_first_that_fits():
    eps = endpoints_of([cl(1, 6, "in"), cl(2, 6, "in"), cl(2, 8, "in")])
    assert map_endpoint(eps, "in", {6}, 2) == 2
    assert map_endpoint(eps, "in", {8}, 1) == 2
    assert map_endpoint(eps, "in", {6}, 3, override=1) == 1
    assert map_endpoint(eps, "out", {6}, 1) is None


def test_plan_for_a_bulb_swap_checks_each_binding_in_the_right_role():
    by_source = {R: [_b(R, 6, L), _b(R, 8, L), _b(R, 6, C)], L: [_b(L, 6, C)], C: []}
    inv = inventory(by_source, C, L, {5: [(L, 1), (P, 1)]})
    assert len(inv["controlled_by"]) == 2 and inv["controls"] == [] and inv["groups"] == [(5, 1)]
    plan = build_plan(inv, L, N, LIGHT, LIGHT)
    assert plan["verdict"] == "all"
    plan = build_plan(inv, L, N, LIGHT, ONOFF_ONLY)
    assert plan["verdict"] == "most"
    dim = next(i for i in plan["items"] if i["clusters"] == [8])
    assert dim["ok"] is False and "doesn't accept Level" in dim["reason"]
    assert build_plan(inv, L, N, LIGHT, REMOTE)["verdict"] == "none"
    assert build_plan(inv, L, N, LIGHT, None)["verdict"] == "unknown"


def test_plan_for_a_remote_swap_needs_outputs():
    inv = inventory({R: [_b(R, 6, L), _b(R, 6, C)]}, C, R, {})
    assert [b["targetIeee"] for b in inv["controls"]] == [L]  # not the coordinator
    assert build_plan(inv, R, N, REMOTE, REMOTE)["verdict"] == "all"
    assert build_plan(inv, R, N, REMOTE, LIGHT)["verdict"] == "none"


async def test_replace_light_end_to_end(setup, hass_ws_client):
    hass, watch, state = setup
    tables = {R: _table((0x20, C), (6, L)), N: {"success": True, "result": {}}}
    bound = []

    async def binds_get(call):
        return tables.get(call.data["ieee"], {"success": False})

    async def bind_ieee(call):
        bound.append(dict(call.data))
        tables[call.data["ieee"]] = _table((0x20, C), (6, L), (call.data["cluster"], call.data["command_data"]))
        return {"success": True}

    removed = []

    async def binds_remove_all(call):
        removed.append(dict(call.data))
        return {"success": True}

    hass.services.async_register("zha_toolkit", "binds_get", binds_get, supports_response=SupportsResponse.ONLY)
    hass.services.async_register("zha_toolkit", "bind_ieee", bind_ieee, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register("zha_toolkit", "binds_remove_all", binds_remove_all, supports_response=SupportsResponse.OPTIONAL)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/replace_plan", "old_ieee": L, "new_ieee": N, "old_clusters": LIGHT, "new_clusters": LIGHT})
    plan = (await client.receive_json())["result"]
    item = next(i for i in plan["items"] if i["kind"] == "controlled_by")
    assert plan["verdict"] == "all" and "Rodret" in item["text"]
    await client.send_json({"id": 2, "type": f"{DOMAIN}/replace_run", "plan_id": plan["plan_id"], "items": [item["id"]]})
    res = (await client.receive_json())["result"]
    assert res["results"][item["id"]] == "confirmed"
    assert bound[0]["ieee"] == R and bound[0]["command_data"] == N
    assert any(b["targetIeee"] == N for b in watch.tracked[R]["expected"].values())
    await client.send_json({"id": 3, "type": f"{DOMAIN}/replace_cleanup", "plan_id": plan["plan_id"]})
    res = (await client.receive_json())["result"]
    assert res["unbound"] == [R] and removed[0] == {"ieee": R, "command_data": L}
    assert not any(b["targetIeee"] == L for b in watch.tracked[R]["expected"].values())
    assert L not in watch.tracked


async def test_asleep_source_is_queued_through_the_watch(setup, hass_ws_client):
    hass, watch, state = setup
    state["answer"] = False  # the remote is asleep
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/replace_plan", "old_ieee": L, "new_ieee": N, "old_clusters": LIGHT, "new_clusters": LIGHT})
    plan = (await client.receive_json())["result"]
    ids = [i["id"] for i in plan["items"] if i["kind"] == "controlled_by"]
    await client.send_json({"id": 2, "type": f"{DOMAIN}/replace_run", "plan_id": plan["plan_id"], "items": ids})
    res = (await client.receive_json())["result"]
    assert set(res["results"].values()) == {"waiting"}
    assert watch.tracked[R]["queued"] is True
    assert any(b["targetIeee"] == N for b in watch.lost(R))


async def test_same_device_is_refused(setup, hass_ws_client):
    hass, watch, state = setup
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/replace_plan", "old_ieee": L, "new_ieee": L})
    msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "same_device"
