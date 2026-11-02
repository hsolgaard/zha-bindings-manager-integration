"""Shared-storage websocket commands, against real Home Assistant core.
Replaces the old verify_websocket_api.py (fake-module) script."""
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zha_bindings_manager.const import DOMAIN


async def _client(hass: HomeAssistant, hass_ws_client):
    entry = MockConfigEntry(domain=DOMAIN, title="ZHA Bindings Manager")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await hass_ws_client(hass)


async def test_get_save_and_stale_write(hass: HomeAssistant, hass_ws_client):
    client = await _client(hass, hass_ws_client)

    await client.send_json({"id": 1, "type": f"{DOMAIN}/get_state", "card_id": "default"})
    assert (await client.receive_json())["result"] is None

    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/save_state", "card_id": "default", "state": {"a": 1}, "base_updated_at": None}
    )
    first = (await client.receive_json())["result"]["updated_at"]

    await client.send_json({"id": 3, "type": f"{DOMAIN}/get_state", "card_id": "default"})
    got = (await client.receive_json())["result"]
    assert got == {"updated_at": first, "state": {"a": 1}}

    # A save based on an older version is rejected, not silently applied.
    await client.send_json(
        {"id": 4, "type": f"{DOMAIN}/save_state", "card_id": "default", "state": {"a": 2}, "base_updated_at": None}
    )
    msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "stale_write"

    # Based on the current version, it's accepted.
    await client.send_json(
        {"id": 5, "type": f"{DOMAIN}/save_state", "card_id": "default", "state": {"a": 3}, "base_updated_at": first}
    )
    assert (await client.receive_json())["success"] is True

    # Another card_id is independent.
    await client.send_json({"id": 6, "type": f"{DOMAIN}/get_state", "card_id": "other"})
    assert (await client.receive_json())["result"] is None


async def test_save_state_is_admin_only(hass: HomeAssistant, hass_ws_client, hass_admin_user):
    """1.4.1 (HACS review): a non-admin can't write the shared data."""
    entry = MockConfigEntry(domain=DOMAIN, title="ZHA Bindings Manager")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass_admin_user.groups = []  # the default test user, made non-admin
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": f"{DOMAIN}/save_state", "card_id": "default", "state": {"a": 1}, "base_updated_at": None}
    )
    msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "unauthorized"
    # Reading still works (the card needs it to detect shared storage).
    await client.send_json({"id": 2, "type": f"{DOMAIN}/get_state", "card_id": "default"})
    assert (await client.receive_json())["success"] is True


async def test_saved_bindings_are_validated(hass: HomeAssistant, hass_ws_client):
    """1.4.1: only well-formed bindings are stored; markup is dropped."""
    client = await _client(hass, hass_ws_client)
    r, l = "aa:aa:aa:aa:aa:aa:aa:01", "bb:bb:bb:bb:bb:bb:bb:02"
    evil = '"><img src=x onerror=alert(1)>'
    good = {"id": "x", "sourceIeee": r, "sourceEndpoint": 1, "clusterId": 6, "isGroup": False, "targetIeee": l, "targetEndpoint": 1}
    state = {
        "filters": {"keep": True},
        "scanState": {
            "last_complete": {
                "savedAt": "t",
                "bindings": {
                    r: [good, {**good, "id": evil, "sourceEndpoint": evil}, {**good, "clusterId": "6<b>"}, {**good, "isGroup": True, "groupId": evil}],
                    evil: [good],
                },
            },
            "latest": None,
        },
    }
    await client.send_json({"id": 1, "type": f"{DOMAIN}/save_state", "card_id": "default", "state": state, "base_updated_at": None})
    assert (await client.receive_json())["success"] is True
    await client.send_json({"id": 2, "type": f"{DOMAIN}/get_state", "card_id": "default"})
    stored = (await client.receive_json())["result"]["state"]
    assert stored["filters"] == {"keep": True}
    bindings = stored["scanState"]["last_complete"]["bindings"]
    assert list(bindings) == [r]
    assert len(bindings[r]) == 1 and bindings[r][0]["clusterId"] == 6 and bindings[r][0]["targetEndpoint"] == 1
    assert "<img" not in str(stored)
