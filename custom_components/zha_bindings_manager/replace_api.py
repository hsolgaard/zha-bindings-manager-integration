"""Websocket commands for Replace a device (1.9.0). Admins only.

Also the hook for Lighting Manager's own Replace flow: it can call
replace_plan / replace_run / replace_cleanup when get_capabilities reports
feature "replace" (clusters are then read from ZHA's gateway)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .bindings import is_ieee, norm_ieee
from .const import DOMAIN


def _ieee(value: Any) -> str:
    if not is_ieee(value):
        raise vol.Invalid("not an IEEE address")
    return norm_ieee(value)


_CLUSTER = vol.Schema({vol.Required("endpoint_id"): int, vol.Required("id"): int, vol.Required("type"): vol.In(["in", "out"])}, extra=vol.REMOVE_EXTRA)


def _replacer(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int):
    r = hass.data.get(DOMAIN, {}).get("replacer")
    if r is None:
        connection.send_error(msg_id, "not_enabled", 'Turn on "Watch for lost bindings" or "Bindings on device pages" under the integration\'s Configure.')
    return r


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/replace_plan",
        vol.Required("old_ieee"): _ieee,
        vol.Required("new_ieee"): _ieee,
        vol.Optional("old_clusters"): [_CLUSTER],
        vol.Optional("new_clusters"): [_CLUSTER],
        vol.Optional("endpoint_map"): {vol.Coerce(str): vol.Coerce(int)},
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_replace_plan(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    r = _replacer(hass, connection, msg["id"])
    if r is None:
        return
    plan = r.plan(msg["old_ieee"], msg["new_ieee"], msg.get("old_clusters"), msg.get("new_clusters"), msg.get("endpoint_map"))
    if plan.get("error"):
        text = {"same_device": "That's the same device: re-paired devices keep their address, so use Put all back instead.", "coordinator": "The coordinator can't replace a device."}
        connection.send_error(msg["id"], plan["error"], text.get(plan["error"], plan["error"]))
        return
    connection.send_result(msg["id"], plan)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/replace_run", vol.Required("plan_id"): str, vol.Required("items"): [str]}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_replace_run(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    r = _replacer(hass, connection, msg["id"])
    if r is None:
        return
    res = await r.run(msg["plan_id"], msg["items"][:200])
    if res.get("error"):
        connection.send_error(msg["id"], res["error"], "That plan has expired: start the replacement again.")
        return
    connection.send_result(msg["id"], res)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/replace_cleanup", vol.Required("plan_id"): str, vol.Optional("unbind_old", default=True): bool}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_replace_cleanup(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    r = _replacer(hass, connection, msg["id"])
    if r is None:
        return
    res = await r.cleanup(msg["plan_id"], msg["unbind_old"])
    if res.get("error"):
        connection.send_error(msg["id"], res["error"], "That plan has expired: start the replacement again.")
        return
    connection.send_result(msg["id"], res)


COMMANDS = (websocket_replace_plan, websocket_replace_run, websocket_replace_cleanup)
