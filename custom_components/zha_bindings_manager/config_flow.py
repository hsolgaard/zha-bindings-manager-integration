"""Config and options flow for ZHA Bindings Manager.

Adding the integration asks nothing. Configure (the options flow) has six
switches; see const.DEFAULT_OPTIONS for the defaults. Single instance only:
there's one shared store and one sidebar page per Home Assistant.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    OPT_DEVICE_PAGE,
    LQI_GOOD_DEFAULT,
    LQI_WEAK_DEFAULT,
    OPT_EXPERIMENTAL,
    OPT_LOGBOOK,
    OPT_LQI_GOOD,
    OPT_LQI_WEAK,
    OPT_WATCH,
    OPT_LOAD_EVERYWHERE,
    OPT_REMOVAL_NOTICES,
    OPT_SHARED_STORAGE,
    OPT_SIDEBAR_PANEL,
    TITLE,
)
from .options import options_from


class ZhaBindingsManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ZHA Bindings Manager."""

    VERSION = 1
    # 1.8.0: "Watch for lost bindings" is on for everyone (see async_migrate_entry).
    MINOR_VERSION = 2

    async def async_step_user(self, user_input: dict | None = None):
        """Single confirmation step, no fields."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return ZhaBindingsManagerOptionsFlow()


class ZhaBindingsManagerOptionsFlow(config_entries.OptionsFlow):
    """The on/off switches."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            if data.pop("reset_lqi", False):
                data[OPT_LQI_GOOD], data[OPT_LQI_WEAK] = LQI_GOOD_DEFAULT, LQI_WEAK_DEFAULT
            if data.get(OPT_LQI_WEAK, LQI_WEAK_DEFAULT) >= data.get(OPT_LQI_GOOD, LQI_GOOD_DEFAULT):
                errors["base"] = "lqi_order"
            else:
                return self.async_create_entry(title="", data=data)

        # self.handler is the entry id on every supported HA version, unlike
        # the config_entry property, which only exists in newer ones.
        current = options_from(self.hass.config_entries.async_get_entry(self.handler))
        schema = vol.Schema(
            {
                vol.Required(OPT_SIDEBAR_PANEL, default=current[OPT_SIDEBAR_PANEL]): bool,
                vol.Required(OPT_LOAD_EVERYWHERE, default=current[OPT_LOAD_EVERYWHERE]): bool,
                vol.Required(OPT_SHARED_STORAGE, default=current[OPT_SHARED_STORAGE]): bool,
                vol.Required(OPT_REMOVAL_NOTICES, default=current[OPT_REMOVAL_NOTICES]): bool,
                vol.Required(OPT_DEVICE_PAGE, default=current[OPT_DEVICE_PAGE]): bool,
                vol.Required(OPT_WATCH, default=current[OPT_WATCH]): bool,
                vol.Required(OPT_LOGBOOK, default=current[OPT_LOGBOOK]): bool,
                vol.Required(OPT_EXPERIMENTAL, default=current[OPT_EXPERIMENTAL]): bool,
                vol.Required(OPT_LQI_GOOD, default=current[OPT_LQI_GOOD]): vol.All(vol.Coerce(int), vol.Range(min=2, max=255)),
                vol.Required(OPT_LQI_WEAK, default=current[OPT_LQI_WEAK]): vol.All(vol.Coerce(int), vol.Range(min=1, max=254)),
                vol.Optional("reset_lqi", default=False): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
