"""The "Bindings" sensor on each bound ZHA device's page."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.network import NoURLAvailableError, get_url

from .bindings import summary_text
from .const import OPT_SIDEBAR_PANEL, SIGNAL_BINDINGS_UPDATED, TITLE, device_link_path
from .options import current_options
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
    # The lists can be long; keep them out of the history database. The short
    # state ("Controls 2 · Controlled by 1") is what gets recorded.
    _unrecorded_attributes = frozenset(
        {"controls", "controlled_by", "last_rescanned", "shown_by", "open_in_zha_bindings_manager"}
    )

    def __init__(self, ieee: str) -> None:
        self._ieee = ieee
        self._attr_unique_id = f"{ieee}_bindings"
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

    def _card_link(self) -> str | None:
        """Full address of the card's page on this device. Home Assistant only
        shows attribute values as links when they start with http(s)://, so a
        relative path won't do. Left out when the sidebar page is off or Home
        Assistant's address isn't known (Settings → System → Network)."""
        if not current_options(self.hass)[OPT_SIDEBAR_PANEL]:
            return None
        try:
            base = get_url(self.hass)
        except NoURLAvailableError:
            return None
        return f"{base.rstrip('/')}{device_link_path(self._ieee)}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "shown_by": TITLE,
            "controls": self._summary["controls"],
            "controlled_by": self._summary["controlled_by"],
            "binding_count": self._summary["count"],
            "last_rescanned": self._summary.get("last_rescanned"),
        }
        link = self._card_link()
        if link:
            attrs["open_in_zha_bindings_manager"] = link
        return attrs
