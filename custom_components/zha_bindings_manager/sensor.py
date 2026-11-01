"""The "Bindings" sensor on each bound ZHA device's page."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bindings import summary_text
from .const import SIGNAL_BINDINGS_UPDATED
from .device_bindings import get_device_bindings
from .entity_manager import async_manage_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_manage_entities(hass, entry, async_add_entities, "sensor", "bindings", BindingsSensor)


class BindingsSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "bindings"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:link-variant"
    _attr_should_poll = False

    def __init__(self, ieee: str) -> None:
        self._ieee = ieee
        self._attr_unique_id = f"{ieee}_bindings"
        self._attr_device_info = DeviceInfo(connections={(dr.CONNECTION_ZIGBEE, ieee)})
        self._summary: dict[str, Any] = {"count": 0, "controls": [], "controlled_by": []}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_BINDINGS_UPDATED, self._update))
        self._update()

    @callback
    def _update(self) -> None:
        data = get_device_bindings(self.hass)
        if data is None:
            return
        self._summary = data.summary(self._ieee)
        if self.hass and self.entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return summary_text(self._summary)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "binding_count": self._summary["count"],
            "controls": self._summary["controls"],
            "controlled_by": self._summary["controlled_by"],
            "last_rescanned": self._summary.get("last_rescanned"),
        }
