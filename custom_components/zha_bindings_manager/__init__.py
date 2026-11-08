"""ZHA Bindings Manager: the integration.

Includes the ZHA Bindings Manager card and adds, each switchable in
Configure:
  - a "ZHA Bindings" sidebar page (admins only) running the card,
  - loading the card on every page, for use on your own dashboards,
  - shared storage, so the card's data is the same in every browser,
  - a notice when a removed ZHA device still has bindings pointing to it,
  - bindings on each bound ZHA device's own page: a "Bindings" sensor and a
    "Rescan bindings" button (1.2.0),
  - watching for lost bindings: every read of a device is compared with what
    it had, with Put back (automatically per device if chosen), in the card
    and in Repairs (1.3.0, reworked and on by default in 1.8.0),
  - logbook entries naming the remote that switched a light over a direct
    binding (1.4.0, off by default),
  - with Experimental features on: the Network tab's routing and neighbour
    tables (1.5.0) and a count of messages each device sends to Home
    Assistant (1.7.0).

Removing this integration doesn't delete anything the card saved in a
browser; the card falls back to browser storage the next time it loads.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant

from .const import DOMAIN, OLD_TITLE, OPT_DEVICE_PAGE, OPT_EXPERIMENTAL, OPT_LOGBOOK, OPT_REMOVAL_NOTICES, OPT_WATCH, PLATFORMS, TITLE
from .device_bindings import DeviceBindings
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

    domain_data.pop("device_bindings", None)
    domain_data.pop("watch", None)
    domain_data.pop("attribution", None)
    domain_data.pop("activity", None)
    domain_data["platforms_loaded"] = False
    if options[OPT_EXPERIMENTAL]:
        from .activity import ActivityCounter

        activity = ActivityCounter(hass)
        domain_data["activity"] = activity
        entry.async_on_unload(activity.async_start())
    if options[OPT_DEVICE_PAGE] or options[OPT_WATCH] or options[OPT_LOGBOOK]:
        device_bindings = DeviceBindings(hass)
        domain_data["device_bindings"] = device_bindings
        await device_bindings.async_load()
        if options[OPT_WATCH]:
            from .watch import BindingWatch

            watch = BindingWatch(hass, device_bindings)
            await watch.async_load()
            domain_data["watch"] = watch
            entry.async_on_unload(watch.async_start())
        if options[OPT_LOGBOOK]:
            from .attribution import BindingAttribution

            attribution = BindingAttribution(hass, device_bindings)
            domain_data["attribution"] = attribution
            entry.async_on_unload(attribution.async_start())
        if options[OPT_DEVICE_PAGE]:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
            domain_data["platforms_loaded"] = True

    # Lovelace resources are only reliable once Home Assistant has started.
    if hass.state is CoreState.running:
        hass.async_create_task(async_check_card_installed_twice(hass))
    else:

        async def _check_after_start(_event: Event) -> None:
            await async_check_card_installed_twice(hass)

        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _check_after_start))

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.8.0: "Check bindings every night" becomes "Watch for lost bindings",
    on by default; turned on once for existing installs too (it can be
    turned off again under Configure)."""
    if entry.version == 1 and entry.minor_version < 2:
        options = {**(entry.options or {}), OPT_WATCH: True}
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
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
    domain_data = hass.data.get(DOMAIN, {})
    domain_data.pop("device_bindings", None)
    domain_data.pop("watch", None)
    domain_data.pop("attribution", None)
    domain_data.pop("activity", None)
    if domain_data.pop("platforms_loaded", False):
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
