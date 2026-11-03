"""Experimental: reading routing and neighbour tables (local build)."""
from homeassistant.core import HomeAssistant, SupportsResponse
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zha_bindings_manager.const import DOMAIN, OPT_EXPERIMENTAL, TITLE
from custom_components.zha_bindings_manager.mesh import parse_tables

R = "aa:aa:aa:aa:aa:aa:aa:01"
L = "bb:bb:bb:bb:bb:bb:bb:02"

SAMPLE = {
    "result": {
        "routes": [
            {"destination": "0x1a2b", "next_hop": "0x0001", "status": "Active", "many_to_one": False},
            {"destination": "bad", "next_hop": "0x0001", "status": "Active"},
        ],
        "neighbours": [
            {"ieee": R, "nwk": "0x1A2B", "device_type": "Router", "relationship": "Sibling", "lqi": 180},
            {"ieee": L, "nwk": "0x0002", "device_type": "EndDevice", "relationship": "Child", "lqi": 70},
            {"ieee": "<script>", "nwk": "0x0003", "device_type": "Router", "relationship": "Sibling", "lqi": 9},
            {"ieee": L, "nwk": "0x0002", "device_type": "<b>", "relationship": "x", "lqi": 999},
        ],
    }
}


def test_parse_tables_validates_everything():
    t = parse_tables(SAMPLE)
    assert t["routes"] == [{"dst": 0x1A2B, "next": 1, "status": "Active", "many_to_one": False}]
    assert t["neighbours"][0] == {"ieee": R, "nwk": 0x1A2B, "type": "Router", "rel": "Sibling", "lqi": 180}
    assert t["neighbours"][1]["rel"] == "Child" and t["neighbours"][1]["lqi"] == 70
    assert len(t["neighbours"]) == 3
    assert t["neighbours"][2] == {"ieee": L, "nwk": 2, "type": "Unknown", "rel": "NoneOfTheAbove", "lqi": None}
    assert parse_tables(None) == {"routes": [], "neighbours": []}


async def _setup(hass, hass_ws_client, options):
    calls = []

    async def get_rn(call):
        calls.append(call.data["ieee"])
        return SAMPLE

    hass.services.async_register("zha_toolkit", "get_routes_and_neighbours", get_rn, supports_response=SupportsResponse.OPTIONAL)
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await hass_ws_client(hass), calls


async def test_mesh_commands_need_the_experimental_switch(hass: HomeAssistant, hass_ws_client):
    client, calls = await _setup(hass, hass_ws_client, {})
    await client.send_json({"id": 1, "type": f"{DOMAIN}/mesh_read", "ieee": R})
    msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "not_enabled" and calls == []
    await client.send_json({"id": 2, "type": f"{DOMAIN}/get_capabilities"})
    res = (await client.receive_json())["result"]
    assert res["features"]["experimental_features"] is False
    assert res["lqi_thresholds"] == {"good": 150, "weak": 80}


async def test_mesh_read_stores_and_returns_tables(hass: HomeAssistant, hass_ws_client):
    client, calls = await _setup(hass, hass_ws_client, {OPT_EXPERIMENTAL: True})
    await client.send_json({"id": 1, "type": f"{DOMAIN}/mesh_read", "ieee": R.upper()})
    res = (await client.receive_json())["result"]
    assert calls == [R] and res["ieee"] == R and res["ok"] is True and len(res["neighbours"]) == 3
    await client.send_json({"id": 2, "type": f"{DOMAIN}/mesh_get"})
    devices = (await client.receive_json())["result"]["devices"]
    assert list(devices) == [R] and devices[R]["routes"][0]["dst"] == 0x1A2B
    await client.send_json({"id": 3, "type": f"{DOMAIN}/mesh_read", "ieee": "not-an-ieee"})
    assert (await client.receive_json())["error"]["code"] == "invalid_format"


async def test_mesh_read_is_admin_only(hass: HomeAssistant, hass_ws_client, hass_admin_user):
    client, calls = await _setup(hass, hass_ws_client, {OPT_EXPERIMENTAL: True})
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/mesh_read", "ieee": R})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"


async def test_options_reset_lqi_and_order_check(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options={"lqi_good": 200, "lqi_weak": 60})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    base = {"sidebar_panel": True, "load_card_everywhere": False, "shared_storage": True, "removal_notices": True,
            "device_page_bindings": True, "binding_watch": False, "logbook_attribution": False, "experimental_features": True}
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**base, "lqi_good": 90, "lqi_weak": 100})
    assert flow["type"] == "form" and flow["errors"] == {"base": "lqi_order"}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**base, "lqi_good": 90, "lqi_weak": 100, "reset_lqi": True})
    assert flow["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["lqi_good"] == 150 and entry.options["lqi_weak"] == 80 and "reset_lqi" not in entry.options
