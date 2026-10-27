"""ZHA Bindings Manager Backend — optional persistent storage for the
zha-binding-map-card Lovelace card.

Installing this integration doesn't change anything on its own — it just
makes a storage backend available. The card detects it (via
get_capabilities) and, from that point, offers to save its data here
instead of (or in addition to) the browser's local storage, so it
survives across browsers/devices rather than being stuck in just one.
It also watches for ZHA devices being removed and, if other devices still
have bindings to the removed one, raises a notification pointing to the
card's clean-up. Removing this integration doesn't delete anything the card already saved
locally; the card falls back to local storage automatically the next time
it loads and finds the backend gone.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .removal_watch import async_setup_removal_watch
from .websocket_api import async_register_websocket_commands


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ZHA Bindings Manager Backend from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)
    # Notify when a removed ZHA device still has bindings pointing to it
    # (see removal_watch.py). Stops when the entry is unloaded.
    entry.async_on_unload(async_setup_removal_watch(hass))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    The registered websocket commands stay registered for the life of the
    process — hass.components.websocket_api has no async_unregister_command,
    and that's fine here: the frontend only ever calls these after seeing
    this domain via get_capabilities, so a command with no config entry
    behind it is just unreachable in practice, not a real leak.
    """
    return True
