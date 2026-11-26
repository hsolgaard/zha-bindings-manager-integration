"""Firmware update servers (1.12.0). Admins only.

A device finds its firmware update ("OTA") server by asking the network
which device serves the OTA cluster, and keeps whoever answers first. That
should be the coordinator. A device that wrongly lists the OTA cluster as an
input (server) cluster can answer first; the devices that pick it then send
their update requests to it, and their updates time out. The SONOFF
ZBM5-3C-80/86 on firmware 1.0.6 does this (endpoint 3).

- ota_claimants: devices other than the coordinator that list OTA as an
  input cluster, from what ZHA knows about them (no radio traffic).
- ota_server: reads one device's upgrade_server_id (OTA client cluster,
  attribute 0x0000): the address it sends its update requests to. The last
  answer per device is saved, with when, so the card's Devices tab can show
  every device's update server after a reload (1.12.0).
"""
from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import storage
from datetime import datetime, timezone

from .bindings import is_ieee, norm_ieee
from .const import DOMAIN
from .settings_backup import _app, _device

OTA_CLUSTER = 0x0019
READ_TIMEOUT = 15
NOT_SET = "ff:ff:ff:ff:ff:ff:ff:ff"
OTA_STORAGE_KEY = f"{DOMAIN}/ota"
SAVED_STATUSES = ("ok", "no_ota")  # answers worth keeping; "no answer" isn't one


async def _results(hass: HomeAssistant) -> tuple[storage.Store, dict[str, Any]]:
    """The saved update-server answers, loaded once per run."""
    data = hass.data.setdefault(DOMAIN, {})
    if "ota_store" not in data:
        store = storage.Store(hass, 1, OTA_STORAGE_KEY)
        loaded = await store.async_load()
        data["ota_store"] = store
        data["ota_results"] = loaded if isinstance(loaded, dict) else {}
    return data["ota_store"], data["ota_results"]


async def save_result(hass: HomeAssistant, ieee: str, res: dict[str, Any]) -> dict[str, Any]:
    """Keeps an answer (with when it was read) and returns it with "at"."""
    if res.get("status") not in SAVED_STATUSES:
        return res
    store, results = await _results(hass)
    entry = {**res, "at": datetime.now(timezone.utc).isoformat()}
    results[norm_ieee(ieee)] = entry
    store.async_delay_save(lambda: results, 1)
    return entry


def _ieee(value: Any) -> str:
    if not is_ieee(value):
        raise vol.Invalid("not an IEEE address")
    return norm_ieee(value)


def coordinator_ieee(app: Any) -> str | None:
    try:
        return norm_ieee(str(app.state.node_info.ieee))
    except Exception:  # noqa: BLE001
        return None


def claimants(app: Any) -> list[dict[str, Any]]:
    """[{ieee, endpoints: [..]}] for devices other than the coordinator that
    list OTA as an input (server) cluster."""
    coord = coordinator_ieee(app)
    out = []
    for device in list((getattr(app, "devices", None) or {}).values()):
        ieee = norm_ieee(str(device.ieee))
        if ieee == coord or getattr(device, "nwk", None) == 0:
            continue
        eps = sorted(
            int(ep_id)
            for ep_id, ep in (getattr(device, "endpoints", None) or {}).items()
            if ep_id != 0 and OTA_CLUSTER in (getattr(ep, "in_clusters", None) or {})
        )
        if eps:
            out.append({"ieee": ieee, "endpoints": eps})
    return sorted(out, key=lambda d: d["ieee"])


async def read_update_server(app: Any, ieee: str) -> dict[str, Any]:
    """{"status": "ok", "server": ieee, "is_coordinator": bool, "not_set": bool}
    or {"status": "no_ota" | "no_answer" | "not_in_zha"}."""
    device = _device(app, ieee)
    if device is None:
        return {"status": "not_in_zha"}
    cluster = None
    for ep_id, ep in sorted((getattr(device, "endpoints", None) or {}).items()):
        if ep_id == 0:
            continue
        cluster = (getattr(ep, "out_clusters", None) or {}).get(OTA_CLUSTER)
        if cluster is not None:
            break
    if cluster is None:
        return {"status": "no_ota"}
    try:
        async with asyncio.timeout(READ_TIMEOUT):
            res = await cluster.read_attributes(["upgrade_server_id"], allow_cache=False)
    except Exception as err:  # noqa: BLE001
        return {"status": "no_answer", "detail": str(err) or type(err).__name__}
    success = res[0] if isinstance(res, (list, tuple)) else res
    if "upgrade_server_id" not in success:
        return {"status": "no_answer"}
    value = success["upgrade_server_id"]
    server = norm_ieee(str(value)) if not isinstance(value, (list, tuple)) else norm_ieee(":".join(f"{int(b):02x}" for b in reversed(value)))
    coord = coordinator_ieee(app)
    return {"status": "ok", "server": server, "is_coordinator": bool(coord and server == coord), "not_set": server == NOT_SET, "coordinator": coord}


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ota_claimants"})
@websocket_api.require_admin
@callback
def websocket_ota_claimants(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    app = _app(hass)
    data = hass.data.get(DOMAIN, {})
    saved = data.get("ota_results") or {}
    if app is None:
        connection.send_result(msg["id"], {"available": False, "claimants": [], "results": saved})
        return
    connection.send_result(msg["id"], {"available": True, "coordinator": coordinator_ieee(app), "claimants": claimants(app), "results": saved})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ota_server", vol.Required("ieee"): _ieee})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_ota_server(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    app = _app(hass)
    if app is None:
        connection.send_result(msg["id"], {"status": "zha_unavailable"})
        return
    res = await read_update_server(app, msg["ieee"])
    connection.send_result(msg["id"], await save_result(hass, msg["ieee"], res))


COMMANDS = (websocket_ota_claimants, websocket_ota_server)
