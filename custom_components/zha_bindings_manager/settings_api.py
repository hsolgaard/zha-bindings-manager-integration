"""Websocket commands for device configuration backups (1.12.0). Admins only."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .bindings import is_ieee, norm_ieee
from .const import DOMAIN
from .settings_backup import get_settings

ERRORS = {
    "zha_unavailable": "ZHA isn't loaded.",
    "not_in_zha": "That device isn't in ZHA.",
    "busy": "That device is already being read.",
    "no_answer": "The device didn't answer. A battery device has to be awake: press one of its buttons and try again straight away.",
    "not_found": "That backup no longer exists.",
}


def _ieee(value: Any) -> str:
    if not is_ieee(value):
        raise vol.Invalid("not an IEEE address")
    return norm_ieee(value)


def _settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int):
    settings = get_settings(hass)
    if settings is None:
        connection.send_error(msg_id, "not_enabled", "Device configuration backups need the integration's binding features (they're on by default).")
    return settings


def _error(connection: websocket_api.ActiveConnection, msg_id: int, code: str) -> None:
    connection.send_error(msg_id, code, ERRORS.get(code, code))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/settings_get", vol.Required("ieee"): _ieee})
@websocket_api.require_admin
@callback
def websocket_settings_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    settings = _settings(hass, connection, msg["id"])
    if settings is None:
        return
    connection.send_result(msg["id"], settings.get(msg["ieee"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/settings_backup", vol.Required("ieee"): _ieee})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_settings_backup(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    settings = _settings(hass, connection, msg["id"])
    if settings is None:
        return
    snap = await settings.async_snapshot(msg["ieee"], "manual")
    if snap.get("error"):
        _error(connection, msg["id"], snap["error"])
        return
    connection.send_result(msg["id"], snap)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/settings_plan",
        vol.Required("source_ieee"): _ieee,
        vol.Optional("snapshot_id"): str,
        vol.Optional("before"): str,
        vol.Required("target_ieee"): _ieee,
        vol.Optional("endpoint_map"): {vol.Coerce(str): vol.All(int, vol.Range(min=1, max=240))},
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_settings_plan(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    settings = _settings(hass, connection, msg["id"])
    if settings is None:
        return
    snap = settings.find(msg["source_ieee"], msg.get("snapshot_id"), msg.get("before"))
    if snap is None:
        _error(connection, msg["id"], "not_found")
        return
    plan = await settings.async_plan(snap, msg["target_ieee"], msg.get("endpoint_map"))
    if plan.get("error"):
        _error(connection, msg["id"], plan["error"])
        return
    connection.send_result(msg["id"], plan)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/settings_apply",
        vol.Required("target_ieee"): _ieee,
        vol.Required("items"): [
            {
                vol.Required("endpoint"): vol.All(int, vol.Range(min=1, max=240)),
                vol.Required("cluster"): vol.All(int, vol.Range(min=0, max=0xFFFF)),
                vol.Required("attribute"): vol.All(int, vol.Range(min=0, max=0xFFFF)),
                vol.Required("value"): object,
            }
        ],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_settings_apply(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    settings = _settings(hass, connection, msg["id"])
    if settings is None:
        return
    res = await settings.async_apply(msg["target_ieee"], msg["items"][:200])
    if res.get("error"):
        _error(connection, msg["id"], res["error"])
        return
    connection.send_result(msg["id"], res)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/settings_import", vol.Required("ieee"): _ieee, vol.Required("snapshot"): dict}
)
@websocket_api.require_admin
@callback
def websocket_settings_import(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    settings = _settings(hass, connection, msg["id"])
    if settings is None:
        return
    try:
        snap = settings.import_snapshot(msg["ieee"], msg["snapshot"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], snap)


COMMANDS = (
    websocket_settings_get,
    websocket_settings_backup,
    websocket_settings_plan,
    websocket_settings_apply,
    websocket_settings_import,
)
