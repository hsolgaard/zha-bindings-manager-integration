"""Raises a notification when a ZHA device that other devices are bound to
is removed.

Home Assistant fires a device registry "remove" event when a device is
removed from ZHA. The remove event doesn't reliably carry the device's
identifiers on every Home Assistant version, so a device_id -> (ieee, name)
map of ZHA devices is kept up to date from the registry and its create and
update events.

On removal, the card's saved scan data is checked for live devices that
still have bindings to the removed device. If there are any, a persistent
notification says which, and points to the card's "Unbind all". Nothing is
unbound here: the removal may be part of re-pairing, and the card is what
talks to zha_toolkit. When a device with the same IEEE address is added
again, the notification is dismissed.

This only reads stored data, never writes it, so it can't conflict with
the card's own saves.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .stale import bindings_to_removed_target, norm_ieee, notification_id, removal_message
from .websocket_api import _load

_LOGGER = logging.getLogger(__name__)

ZHA_DOMAIN = "zha"


def _zha_ieee(identifiers: Any) -> str | None:
    for ident in identifiers or ():
        try:
            domain, value = ident[0], ident[1]
        except (TypeError, IndexError, KeyError):
            continue
        if domain == ZHA_DOMAIN and value:
            return norm_ieee(value)
    return None


def _device_name(device: Any) -> str:
    if isinstance(device, dict):
        return device.get("name_by_user") or device.get("name") or ""
    return getattr(device, "name_by_user", None) or getattr(device, "name", None) or ""


@callback
def async_setup_removal_watch(hass: HomeAssistant) -> CALLBACK_TYPE:
    """Start watching. Returns the unsubscribe callback."""
    registry = dr.async_get(hass)
    known: dict[str, tuple[str, str]] = {}

    def remember(device: Any) -> None:
        ieee = _zha_ieee(device.identifiers)
        if ieee:
            known[device.id] = (ieee, _device_name(device))

    for device in registry.devices.values():
        remember(device)

    def names_by_ieee() -> dict[str, str]:
        return {ieee: name for ieee, name in known.values()}

    async def handle_removed(ieee: str, name: str) -> None:
        try:
            data = await _load(hass)
        except Exception:  # noqa: BLE001 - a notice is best effort
            _LOGGER.exception("Could not read saved scan data after %s was removed", ieee)
            return
        live = {known_ieee for known_ieee, _ in known.values()}
        sources = bindings_to_removed_target(data, ieee, live)
        if not sources:
            return
        persistent_notification.async_create(
            hass,
            removal_message(name or ieee, ieee, sources, names_by_ieee()),
            title="ZHA Bindings Manager: bindings to a removed device",
            notification_id=notification_id(DOMAIN, ieee),
        )

    @callback
    def on_registry_event(event: Event) -> None:
        action = event.data.get("action")
        device_id = event.data.get("device_id")
        if action in ("create", "update"):
            device = registry.async_get(device_id)
            if device is None:
                return
            remember(device)
            ieee = _zha_ieee(device.identifiers)
            if action == "create" and ieee:
                # Re-paired with the same address: its bindings work again.
                persistent_notification.async_dismiss(hass, notification_id(DOMAIN, ieee))
            return
        if action != "remove":
            return
        ieee, name = known.pop(device_id, (None, ""))
        if not ieee:
            removed = event.data.get("device") or {}
            ieee = _zha_ieee(removed.get("identifiers"))
            name = _device_name(removed)
        if ieee:
            hass.async_create_task(handle_removed(ieee, name))

    return hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, on_registry_event)
