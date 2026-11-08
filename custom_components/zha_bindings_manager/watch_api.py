"""Websocket commands for lost bindings (1.8.0). Admins only."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .bindings import is_ieee, norm_ieee
from .const import DOMAIN
from .watch import POLICIES, get_watch


def _watch(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int):
    watch = get_watch(hass)
    if watch is None:
        connection.send_error(msg_id, "not_enabled", "Turn on \"Watch for lost bindings\" under the integration's Configure.")
    return watch


def _ieee(value: Any) -> str:
    if not is_ieee(value):
        raise vol.Invalid("not an IEEE address")
    return norm_ieee(value)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/watch_get"})
@websocket_api.require_admin
@callback
def websocket_watch_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    watch = get_watch(hass)
    if watch is None:
        connection.send_result(msg["id"], {"enabled": False, "devices": {}})
        return
    connection.send_result(msg["id"], {"enabled": True, **watch.summary()})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/watch_removed", vol.Required("bindings"): [dict]})
@websocket_api.require_admin
@callback
def websocket_watch_removed(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    watch = get_watch(hass)
    connection.send_result(msg["id"], {"removed": watch.removed_by_user(msg["bindings"][:200]) if watch else 0})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/watch_put_back", vol.Optional("ieee"): _ieee})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_watch_put_back(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    watch = _watch(hass, connection, msg["id"])
    if watch is None:
        return
    if msg.get("ieee"):
        results = {msg["ieee"]: await watch.async_put_back(msg["ieee"])}
    else:
        results = await watch.async_put_back_all()
    connection.send_result(msg["id"], {"results": results, **watch.summary()})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/watch_forget", vol.Required("ieee"): _ieee, vol.Optional("keys"): [str]}
)
@websocket_api.require_admin
@callback
def websocket_watch_forget(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    watch = _watch(hass, connection, msg["id"])
    if watch is None:
        return
    watch.forget(msg["ieee"], msg.get("keys"))
    connection.send_result(msg["id"], watch.summary())


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/watch_policy", vol.Required("ieee"): _ieee, vol.Required("policy"): vol.In(POLICIES)}
)
@websocket_api.require_admin
@callback
def websocket_watch_policy(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    watch = _watch(hass, connection, msg["id"])
    if watch is None:
        return
    watch.set_policy(msg["ieee"], msg["policy"])
    connection.send_result(msg["id"], watch.summary())


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/watch_check_all"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_watch_check_all(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    watch = _watch(hass, connection, msg["id"])
    if watch is None:
        return
    results = await watch.async_check_all()
    connection.send_result(msg["id"], {"results": results, **watch.summary()})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/watch_fallback", vol.Required("ieee"): _ieee, vol.Required("enabled"): bool}
)
@websocket_api.require_admin
@callback
def websocket_watch_fallback(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    watch = _watch(hass, connection, msg["id"])
    if watch is None:
        return
    watch.set_fallback(msg["ieee"], msg["enabled"])
    connection.send_result(msg["id"], watch.summary())


COMMANDS = (
    websocket_watch_get,
    websocket_watch_removed,
    websocket_watch_put_back,
    websocket_watch_forget,
    websocket_watch_policy,
    websocket_watch_check_all,
    websocket_watch_fallback,
)
