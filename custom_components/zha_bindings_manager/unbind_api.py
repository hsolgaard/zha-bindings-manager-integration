"""Remove one binding by sending the ZDO Unbind_req ourselves (1.10.6).

zha-toolkit's binds_remove_all looks the *target* device up first, so a
binding to a device that's no longer in ZHA can't be removed with it (it
fails with a KeyError and never sends the request), and its unbind_group
only handles clusters the source sends, not a light's own reporting binding
to a group. Sending the request directly needs neither, removes exactly the
binding asked for, and returns what the device answered (SUCCESS, NO_ENTRY,
NOT_SUPPORTED...)."""
from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .bindings import norm_ieee
from .const import DOMAIN

UNBIND_TIMEOUT = 20


def _app(hass: HomeAssistant) -> Any:
    if "zha" not in hass.config.components:
        return None
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway  # type: ignore

        return get_zha_gateway(hass).application_controller
    except Exception:  # noqa: BLE001 - internal ZHA API
        return None


def status_name(status: Any) -> str:
    """'SUCCESS', 'NO_ENTRY'... for a ZDO status (enum or int)."""
    name = getattr(status, "name", None)
    if name:
        return str(name)
    try:
        from zigpy.zdo.types import Status  # type: ignore

        return Status(int(status)).name
    except Exception:  # noqa: BLE001
        return str(status)


async def async_unbind(
    hass: HomeAssistant, source: str, endpoint: int, cluster: int, *, group: int | None = None, target: str | None = None, target_endpoint: int | None = None
) -> dict[str, Any]:
    """Sends one Unbind_req. Returns {"status": "SUCCESS" | "NO_ENTRY" | ...}
    or {"status": "no_answer"} / {"status": "unavailable"}."""
    app = _app(hass)
    if app is None:
        return {"status": "unavailable", "detail": "ZHA isn't loaded"}
    import zigpy.types as t  # type: ignore
    from zigpy.zdo.types import MultiAddress, ZDOCmd  # type: ignore

    src = t.EUI64.convert(norm_ieee(source))
    try:
        device = app.get_device(ieee=src)
    except KeyError:
        return {"status": "unavailable", "detail": "the source device isn't in ZHA"}
    dst = MultiAddress()
    if group is not None:
        dst.addrmode = t.uint8_t(1)
        dst.nwk = t.uint16_t(int(group))
    else:
        dst.addrmode = t.uint8_t(3)
        dst.ieee = t.EUI64.convert(norm_ieee(target))
        dst.endpoint = t.uint8_t(int(target_endpoint))
    try:
        async with asyncio.timeout(UNBIND_TIMEOUT):
            res = await device.zdo.request(ZDOCmd.Unbind_req, src, int(endpoint), int(cluster), dst)
    except (TimeoutError, asyncio.TimeoutError):
        return {"status": "no_answer"}
    except Exception as err:  # noqa: BLE001 - radio/delivery errors
        return {"status": "no_answer", "detail": str(err) or type(err).__name__}
    status = res[0] if isinstance(res, (list, tuple)) and res else res
    return {"status": status_name(status)}


_ieee = vol.All(str, vol.Length(min=16, max=23))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/unbind",
        vol.Required("source_ieee"): _ieee,
        vol.Required("endpoint"): vol.All(int, vol.Range(min=1, max=254)),
        vol.Required("cluster"): vol.All(int, vol.Range(min=0, max=0xFFFF)),
        vol.Exclusive("group_id", "dst"): vol.All(int, vol.Range(min=0, max=0xFFFF)),
        vol.Exclusive("target_ieee", "dst"): _ieee,
        vol.Optional("target_endpoint"): vol.All(int, vol.Range(min=0, max=255)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_unbind(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if msg.get("group_id") is None and (msg.get("target_ieee") is None or msg.get("target_endpoint") is None):
        connection.send_error(msg["id"], "invalid_format", "Give group_id, or target_ieee and target_endpoint")
        return
    result = await async_unbind(
        hass,
        msg["source_ieee"],
        msg["endpoint"],
        msg["cluster"],
        group=msg.get("group_id"),
        target=msg.get("target_ieee"),
        target_endpoint=msg.get("target_endpoint"),
    )
    connection.send_result(msg["id"], result)
