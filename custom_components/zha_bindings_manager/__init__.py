"""ZHA Bindings Manager: the integration.

Includes the ZHA Bindings Manager card and adds, each switchable in
Configure:
  - a "ZHA Bindings" sidebar page (admins only) running the card,
  - loading the card on every page, for use on your own dashboards,
  - shared storage, so the card's data is the same in every browser,
  - a notice when a removed ZHA device still has bindings pointing to it.

Removing this integration doesn't delete anything the card saved in a
browser; the card falls back to browser storage the next time it loads.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant

from .const import DOMAIN, OLD_TITLE, OPT_REMOVAL_NOTICES, TITLE
from .duplicate_check import async_check_card_installed_twice
from .card_frontend import async_setup_frontend, async_unload_frontend
from .options import options_from
from .removal_watch import async_setup_removal_watch
from .websocket_api import async_register_websocket_commands


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ZHA Bindings Manager from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("ws_registered"):
        async_register_websocket_commands(hass)
        domain_data["ws_registered"] = True

    # Entries created before 1.0.0 are titled "ZHA Bindings Manager Backend".
    if entry.title == OLD_TITLE:
        hass.config_entries.async_update_entry(entry, title=TITLE)

    options = options_from(entry)
    await async_setup_frontend(hass, options)

    if options[OPT_REMOVAL_NOTICES]:
        entry.async_on_unload(async_setup_removal_watch(hass))

    # Lovelace resources are only reliable once Home Assistant has started.
    if hass.state is CoreState.running:
        hass.async_create_task(async_check_card_installed_twice(hass))
    else:

        async def _check_after_start(_event: Event) -> None:
            await async_check_card_installed_twice(hass)

        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _check_after_start))

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Websocket commands and the static file path stay registered for the
    life of the process (Home Assistant can't unregister either). That's
    harmless: get_capabilities reports the current options, and nothing
    links to the file once the panel and extra script are removed.
    """
    async_unload_frontend(hass)
    return True
