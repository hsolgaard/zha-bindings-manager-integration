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
