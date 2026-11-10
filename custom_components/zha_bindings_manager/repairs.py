"""Fix flow for the "lost bindings" Repairs issue (1.8.0): put them all back.

Choosing bindings one by one, or saying one was removed on purpose, is done
in the card (Bindings tab), which the issue links to."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import OPT_SIDEBAR_PANEL, PANEL_URL_PATH
from .options import current_options
from .watch import get_watch


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict | None) -> RepairsFlow:
    return LostBindingsFlow()


class LostBindingsFlow(RepairsFlow):
    def _card_link(self) -> str:
        if not current_options(self.hass)[OPT_SIDEBAR_PANEL]:
            return ""
        return f"\n\n[Open ZHA Bindings Manager](/{PANEL_URL_PATH}) to choose bindings one by one, or to say one was removed on purpose."

    def _placeholders(self, extra: str = "") -> dict[str, str]:
        watch = get_watch(self.hass)
        names = watch.data.names() if watch else {}
        lines = []
        if watch:
            for ieee in watch.tracked:
                lost = watch.lost(ieee)
                if lost and watch.tracked[ieee].get("policy") != "off":
                    lines.append(f"- {names.get(ieee) or ieee}: {len(lost)}")
        paused = watch.paused_text() if watch else ""
        return {"devices": "\n".join(lines) or "-", "paused": paused, "card_link": self._card_link(), "result": extra}

    async def async_step_init(self, user_input=None) -> data_entry_flow.FlowResult:
        # The flow manager passes the issue data as the first input: show the form.
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None) -> data_entry_flow.FlowResult:
        watch = get_watch(self.hass)
        if watch is None:
            return self.async_abort(reason="not_enabled")
        if user_input is None:
            return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}), description_placeholders=self._placeholders())
        results = await watch.async_put_back_all()
        names = watch.data.names()
        waiting = [names.get(i) or i for i, r in results.items() if r["status"] == "waiting"]
        still = [names.get(i) or i for i, r in results.items() if r["status"] == "still_missing"]
        if not waiting and not still:
            return self.async_create_entry(data={})
        parts = []
        if waiting:
            parts.append("Waiting for a button press (they go back then): " + ", ".join(waiting) + ".")
        if still:
            parts.append("Still missing after putting them back: " + ", ".join(still) + ".")
        return self.async_show_form(
            step_id="confirm", data_schema=vol.Schema({}), errors={"base": "not_all"}, description_placeholders=self._placeholders("\n\n" + " ".join(parts))
        )
