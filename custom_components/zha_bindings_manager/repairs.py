"""Fix flow for "bindings disappeared" Repairs issues: Re-apply or Forget."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import OPT_SIDEBAR_PANEL, device_link_path
from .options import current_options
from .watch import get_watch


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict | None) -> RepairsFlow:
    return BindingMissingFlow((data or {}).get("ieee"))


class BindingMissingFlow(RepairsFlow):
    def __init__(self, ieee: str | None) -> None:
        self._ieee = ieee

    def _card_link(self) -> str:
        """A line linking to the device in the card (1.5.0). "Learn more"
        isn't shown for fixable issues, so the link goes in the text."""
        if not self._ieee or not current_options(self.hass)[OPT_SIDEBAR_PANEL]:
            return ""
        return f"\n\n[Open this device in ZHA Bindings Manager]({device_link_path(self._ieee)}) to see its bindings."

    def _placeholders(self) -> dict[str, str]:
        watch = get_watch(self.hass)
        if watch is None:
            return {"device": self._ieee or "", "bindings": "", "card_link": self._card_link()}
        return {
            "device": watch.data.names().get(self._ieee or "", self._ieee or ""),
            "bindings": watch.describe(watch.missing(self._ieee or "")),
            "card_link": self._card_link(),
        }

    async def async_step_init(self, user_input=None) -> data_entry_flow.FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["reapply", "forget"], description_placeholders=self._placeholders())

    async def async_step_reapply(self, user_input=None) -> data_entry_flow.FlowResult:
        watch = get_watch(self.hass)
        if watch is None:
            return self.async_abort(reason="not_enabled")
        if user_input is None:
            return self.async_show_form(step_id="reapply", data_schema=vol.Schema({}), description_placeholders=self._placeholders())
        still = await watch.async_reapply(self._ieee or "")
        if not still:
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="reapply", data_schema=vol.Schema({}), errors={"base": "still_missing"}, description_placeholders=self._placeholders()
        )

    async def async_step_forget(self, user_input=None) -> data_entry_flow.FlowResult:
        watch = get_watch(self.hass)
        if watch is None:
            return self.async_abort(reason="not_enabled")
        if user_input is None:
            return self.async_show_form(step_id="forget", data_schema=vol.Schema({}), description_placeholders=self._placeholders())
        watch.forget(self._ieee or "")
        return self.async_create_entry(data={})
