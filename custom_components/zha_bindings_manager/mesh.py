"""Experimental: reading the Zigbee mesh (routing and neighbour tables).

Behind the "Experimental features" option (off by default). The card asks
for one router at a time (`mesh_read`), so it can show progress and stop;
each answer is stored, so the snapshot survives a reload and is the same
in every browser (`mesh_get`). Reading goes through zha-toolkit's
get_routes_and_neighbours (ZDO Mgmt_Rtg_req and Mgmt_Lqi_req). Nothing on
the network is ever changed.

Path prediction and the network map are worked out in the card, which
already has the device list, bindings, groups and floor plan.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import storage

from .bindings import is_ieee, norm_ieee
from .const import DOMAIN, OPT_EXPERIMENTAL
from .options import current_options

MESH_STORAGE_KEY = f"{DOMAIN}/mesh"
MAX_ENTRIES = 512
_RELATIONSHIPS = {"Parent", "Child", "Sibling", "NoneOfTheAbove", "None_of_the_above", "PreviousChild", "Previous_Child"}
_DEVICE_TYPES = {"Coordinator", "Router", "EndDevice", "Unknown"}
_ROUTE_STATUS = {"Active", "Discovery_Underway", "Discovery_Failed", "Inactive", "Validation_Underway"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nwk(value: Any) -> int | None:
    try:
        if isinstance(value, str):
            v = value.strip().lower()
            if not v.startswith("0x"):
                return None  # zha-toolkit always writes "0x1a2b"
            n = int(v, 16)
        elif isinstance(value, int) and not isinstance(value, bool):
            n = value
        else:
            return None
    except ValueError:
        return None
    return n if 0 <= n <= 0xFFFF else None


def _word(value: Any, allowed: set[str], fallback: str) -> str:
    s = str(getattr(value, "name", value) or "")
    return s if s in allowed else fallback


def parse_tables(response: Any) -> dict[str, Any]:
    """zha-toolkit get_routes_and_neighbours response -> validated tables.

    Every value is checked and reduced to plain types, so what's stored
    and sent to the card can't carry anything unexpected."""
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        result = response if isinstance(response, dict) else {}
    routes = []
    for r in (result.get("routes") or [])[:MAX_ENTRIES]:
        if not isinstance(r, dict):
            continue
        dst, nxt = _nwk(r.get("destination")), _nwk(r.get("next_hop"))
        if dst is None or nxt is None:
            continue
        routes.append(
            {
                "dst": dst,
                "next": nxt,
                "status": _word(r.get("status"), _ROUTE_STATUS, "Unknown"),
                "many_to_one": bool(r.get("many_to_one")),
            }
        )
    neighbours = []
    for n in (result.get("neighbours") or [])[:MAX_ENTRIES]:
        if not isinstance(n, dict):
            continue
        ieee = norm_ieee(n.get("ieee"))
        if not is_ieee(ieee):
            continue
        lqi = n.get("lqi")
        lqi = lqi if isinstance(lqi, int) and not isinstance(lqi, bool) and 0 <= lqi <= 255 else None
        neighbours.append(
            {
                "ieee": ieee,
                "nwk": _nwk(n.get("nwk")),
                "type": _word(n.get("device_type"), _DEVICE_TYPES, "Unknown"),
                "rel": _word(n.get("relationship"), _RELATIONSHIPS, "NoneOfTheAbove"),
                "lqi": lqi,
            }
        )
    return {"routes": routes, "neighbours": neighbours}


class MeshStore:
    """The latest tables read from each router."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = storage.Store(hass, 1, MESH_STORAGE_KEY)
        self.data: dict[str, dict] | None = None
        self.lock = asyncio.Lock()

    async def async_load(self) -> dict[str, dict]:
        if self.data is None:
            raw = await self._store.async_load()
            self.data = raw if isinstance(raw, dict) else {}
        return self.data

    async def async_read(self, ieee: str) -> dict[str, Any]:
        """Reads one device's tables and stores the result (also a failure)."""
        await self.async_load()
        key = norm_ieee(ieee)
        async with self.lock:
            if not self.hass.services.has_service("zha_toolkit", "get_routes_and_neighbours"):
                entry = {"at": _now_iso(), "ok": False, "error": "zha-toolkit isn't installed or isn't loaded", "routes": [], "neighbours": []}
            else:
                try:
                    response = await self.hass.services.async_call(
                        "zha_toolkit",
                        "get_routes_and_neighbours",
                        {"ieee": key},
                        blocking=True,
                        return_response=True,
                    )
                    tables = parse_tables(response)
                    ok = bool(tables["routes"] or tables["neighbours"])
                    entry = {"at": _now_iso(), "ok": ok, "error": None if ok else "no answer (asleep, offline or not supported)", **tables}
                except Exception as err:  # noqa: BLE001 - reported to the user
                    entry = {"at": _now_iso(), "ok": False, "error": str(err)[:200], "routes": [], "neighbours": []}
            self.data[key] = entry
            self._store.async_delay_save(lambda: self.data, 5)
        return entry


def get_mesh_store(hass: HomeAssistant) -> MeshStore:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "mesh" not in domain_data:
        domain_data["mesh"] = MeshStore(hass)
    return domain_data["mesh"]


def _enabled(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int) -> bool:
    if current_options(hass)[OPT_EXPERIMENTAL]:
        return True
    connection.send_error(msg_id, "not_enabled", "Turn on Experimental features under the integration's Configure.")
    return False


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/mesh_read", vol.Required("ieee"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mesh_read(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not _enabled(hass, connection, msg["id"]):
        return
    if not is_ieee(msg["ieee"]):
        connection.send_error(msg["id"], "invalid_format", "Not an IEEE address.")
        return
    entry = await get_mesh_store(hass).async_read(msg["ieee"])
    connection.send_result(msg["id"], {"ieee": norm_ieee(msg["ieee"]), **entry})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/mesh_get"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mesh_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not _enabled(hass, connection, msg["id"]):
        return
    connection.send_result(msg["id"], {"devices": await get_mesh_store(hass).async_load()})
