"""Adds and removes the device-page entities as binding data changes."""
from __future__ import annotations

from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_BINDINGS_UPDATED
from .device_bindings import get_device_bindings


@callback
def async_manage_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    unique_suffix: str,
    factory: Callable[[str], Entity],
) -> None:
    data = get_device_bindings(hass)
    if data is None:
        return
    current: set[str] = set()

    @callback
    def sync() -> None:
        wanted = set(data.exposed)
        new = wanted - current
        if new:
            async_add_entities([factory(ieee) for ieee in sorted(new)])
            current.update(new)
        gone = current - wanted
        if gone:
            registry = er.async_get(hass)
            for ieee in gone:
                entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{ieee}_{unique_suffix}")
                if entity_id:
                    registry.async_remove(entity_id)
            current.difference_update(gone)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_BINDINGS_UPDATED, sync))
    sync()
