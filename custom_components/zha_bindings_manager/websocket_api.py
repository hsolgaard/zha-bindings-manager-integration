"""WebSocket API for the ZHA Bindings Manager integration.

Four commands, deliberately minimal — no patch_state, no
subscribe_updates, no list_instances/delete_instance until something
actually needs them:

  get_capabilities — feature detection. The card calls this once at
    load; a response means "integration installed". It also carries the
    version, the bundled card's version and which options are switched on.
  get_state — returns the whole stored state blob for one card instance,
    plus the updated_at timestamp it was last saved with.
  save_state — writes the whole state blob for one card instance.
    Last-write-wins, guarded by base_updated_at: if what's currently
    stored doesn't match what the client last saw, the write is rejected
    with a "stale_write" error instead of silently clobbering a newer
    save. The frontend is expected to reload and retry rather than merge.
  raw_device_info — the device's own identity, signature and firmware,
    read over the air rather than from ZHA's (possibly quirked) view. Used
    when sharing a scan to the capabilities database. See raw_device.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import storage

from .const import (
    BACKEND_VERSION,
    DOMAIN,
    OPT_LOAD_EVERYWHERE,
    OPT_REMOVAL_NOTICES,
    OPT_SHARED_STORAGE,
    OPT_SIDEBAR_PANEL,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .card_frontend import bundled_card_version
from .options import current_options
from .raw_device import DeviceNotFound, async_get_raw_device_info


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register this integration's websocket commands."""
    websocket_api.async_register_command(hass, websocket_get_capabilities)
    websocket_api.async_register_command(hass, websocket_get_state)
    websocket_api.async_register_command(hass, websocket_save_state)
    websocket_api.async_register_command(hass, websocket_raw_device_info)


def _get_store(hass: HomeAssistant) -> storage.Store:
    """One Store per hass, cached in hass.data — cheap to call repeatedly;
    storage.Store itself already debounces/coalesces writes to disk."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "store" not in domain_data:
        domain_data["store"] = storage.Store(hass, STORAGE_VERSION, STORAGE_KEY)
    return domain_data["store"]


async def _load(hass: HomeAssistant) -> dict[str, Any]:
    store = _get_store(hass)
    data = await store.async_load()
    return data if isinstance(data, dict) else {}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_capabilities",
    }
)
@websocket_api.async_response
async def websocket_get_capabilities(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Feature detection. A response means the integration is installed.

    Since 1.0.0 it also reports the bundled card's version (the card warns
    if the page is running a different copy) and which options are on (the
    card uses shared storage only when shared_storage is true)."""
    opts = current_options(hass)
    connection.send_result(
        msg["id"],
        {
            "available": True,
            "version": BACKEND_VERSION,
            "bundled_card_version": bundled_card_version(),
            "features": {
                "shared_storage": opts[OPT_SHARED_STORAGE],
                "sidebar_panel": opts[OPT_SIDEBAR_PANEL],
                "load_card_everywhere": opts[OPT_LOAD_EVERYWHERE],
                "removal_notices": opts[OPT_REMOVAL_NOTICES],
                # Always on: lets the card read a device's raw identity and
                # signature instead of ZHA's quirked view (raw_device_info).
                "raw_device_info": True,
            },
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_state",
        vol.Required("card_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_state(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Returns {updated_at, state} for this card_id, or null if nothing's
    been saved yet — e.g. first activation, before the frontend's
    import-existing-browser-data-or-start-fresh prompt has run."""
    data = await _load(hass)
    entry = data.get(msg["card_id"])
    connection.send_result(msg["id"], entry if entry else None)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_state",
        vol.Required("card_id"): str,
        vol.Required("state"): dict,
        vol.Optional("base_updated_at"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def websocket_save_state(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Whole-state, last-write-wins save, guarded by base_updated_at.

    base_updated_at is whatever updated_at the frontend last saw for this
    card_id (from a prior get_state or save_state response), or None if
    it's never saved before / never fetched first. If what's currently
    stored doesn't match, something else wrote in between — reject rather
    than silently overwrite, so the frontend can reload and retry instead
    of one client's save quietly discarding another's.
    """
    store = _get_store(hass)
    data = await _load(hass)
    card_id = msg["card_id"]
    current = data.get(card_id)
    current_updated_at = current["updated_at"] if current else None

    if current_updated_at != msg.get("base_updated_at"):
        connection.send_error(
            msg["id"],
            "stale_write",
            "State was updated elsewhere since it was last loaded. Reload and retry.",
        )
        return

    new_updated_at = _now_iso()
    data[card_id] = {"updated_at": new_updated_at, "state": msg["state"]}
    await store.async_save(data)
    connection.send_result(msg["id"], {"updated_at": new_updated_at})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/raw_device_info",
        vol.Required("ieee"): str,
    }
)
@websocket_api.async_response
async def websocket_raw_device_info(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The device's own identity, endpoints/clusters and firmware, asked of
    the device itself (see raw_device.py). Each part carries its own status,
    so a sleepy device that misses one request still returns the rest."""
    try:
        result = await async_get_raw_device_info(hass, msg["ieee"])
    except DeviceNotFound:
        connection.send_error(msg["id"], "device_not_found", f"No ZHA device with IEEE {msg['ieee']}")
        return
    except LookupError as exc:
        connection.send_error(msg["id"], "zha_not_loaded", str(exc))
        return
    connection.send_result(msg["id"], result)
