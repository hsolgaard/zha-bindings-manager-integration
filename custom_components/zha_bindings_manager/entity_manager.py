"""Adds and removes the device-page entities as binding data changes."""
from __future__ import annotations

from typing import Callable

from homeassistant.helpers import device_registry as dr

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
            entities = []
            for ieee in sorted(new):
                device = data.zha_device(ieee)
                if device is None:
                    continue
                entity = factory(ieee)
                # Attach to ZHA's own device. Describing the device (device_info)
                # makes Home Assistant 2026.10+ create a separate "linked"
                # device owned by this integration instead.
                entity.device_entry = device
                entities.append(entity)
            if entities:
                async_add_entities(entities)
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
    _remove_linked_devices(hass, entry)
    sync()


@callback
def _remove_linked_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """1.2.0 described ZHA's device instead of attaching to it, which on
    Home Assistant 2026.10+ created a separate "ZHA Bindings Manager" device
    linked to each ZHA device. This integration owns no devices of its own,
    so drop it from any device that still lists it (Home Assistant deletes a
    device once no integration lists it)."""
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
