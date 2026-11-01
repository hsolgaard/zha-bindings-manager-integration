"""Fix flow for "bindings disappeared" Repairs issues: Re-apply or Forget."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .watch import get_watch


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict | None) -> RepairsFlow:
    return BindingMissingFlow((data or {}).get("ieee"))


class BindingMissingFlow(RepairsFlow):
    def __init__(self, ieee: str | None) -> None:
        self._ieee = ieee

    def _placeholders(self) -> dict[str, str]:
        watch = get_watch(self.hass)
        if watch is None:
            return {"device": self._ieee or "", "bindings": ""}
        return {
            "device": watch.data.names().get(self._ieee or "", self._ieee or ""),
            "bindings": watch.describe(watch.missing(self._ieee or "")),
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
