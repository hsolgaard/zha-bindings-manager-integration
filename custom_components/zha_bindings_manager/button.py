"""The "Rescan bindings" button on each bound ZHA device's page."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bindings import BindsGetFailed
from .device_bindings import get_device_bindings
from .watch import get_watch
from .entity_manager import async_manage_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_manage_entities(hass, entry, async_add_entities, "button", "rescan_bindings", RescanBindingsButton)


class RescanBindingsButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "rescan_bindings"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:refresh"

    def __init__(self, ieee: str) -> None:
        self._ieee = ieee
        self._attr_unique_id = f"{ieee}_rescan_bindings"

    async def async_press(self) -> None:
        data = get_device_bindings(self.hass)
        if data is None:
            raise HomeAssistantError("ZHA Bindings Manager isn't ready yet.")
        # With "Check bindings every night" on, a manual rescan also counts as a
        # check, so a disappeared binding can be confirmed (and the Repairs
        # flow tested) without waiting for the nightly run.
        watch = get_watch(self.hass)
        if watch is not None and (watch.tracked.get(self._ieee) or {}).get("expected"):
            if await watch.async_check_device(self._ieee, "scan") is None:
                raise HomeAssistantError(
                    "The device didn't answer. Battery devices are usually asleep: press a button on it, then try again."
                )
            return
        try:
            await data.async_rescan(self._ieee)
        except BindsGetFailed as err:
            raise HomeAssistantError(
                f"The device didn't answer ({err}). Battery devices are usually asleep: press a button on it, then try again."
            ) from err
