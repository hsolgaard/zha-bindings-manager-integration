"""The "Rescan bindings" button on each bound ZHA device's page."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bindings import BindsGetFailed
from .device_bindings import get_device_bindings
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
        self._attr_device_info = DeviceInfo(connections={(dr.CONNECTION_ZIGBEE, ieee)})

    async def async_press(self) -> None:
        data = get_device_bindings(self.hass)
        if data is None:
            raise HomeAssistantError("ZHA Bindings Manager isn't ready yet.")
        try:
            await data.async_rescan(self._ieee)
        except BindsGetFailed as err:
            raise HomeAssistantError(
                f"The device didn't answer ({err}). Battery devices are usually asleep: press a button on it, then try again."
            ) from err
