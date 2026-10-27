"""Serves the bundled card, registers the sidebar page and, optionally,
loads the card on every page.

The card file is served at CARD_URL with the version as a query string,
so each update is fetched fresh instead of coming from a browser cache.
The sidebar page loads the file only when it's opened. "Load the card on
every page" adds it to every page, which is only needed to use the card
on your own dashboards (it's about 380 KB, so it's off by default).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    CARD_FILENAME,
    CARD_URL,
    DOMAIN,
    OPT_LOAD_EVERYWHERE,
    OPT_SIDEBAR_PANEL,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
)

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"


def _read_bundled_card_version() -> str | None:
    try:
        return json.loads((FRONTEND_DIR / "card_version.json").read_text(encoding="utf-8")).get("card_version")
    except (OSError, ValueError):
        return None


# Read once, while the module is imported (Home Assistant imports custom
# integrations outside the event loop), never from inside the event loop.
_BUNDLED_CARD_VERSION = _read_bundled_card_version()


def bundled_card_version() -> str | None:
    """The card version recorded next to the bundled file."""
    return _BUNDLED_CARD_VERSION


def versioned_card_url() -> str:
    return f"{CARD_URL}?v={bundled_card_version() or 'unknown'}"


async def async_setup_frontend(hass: HomeAssistant, options: dict) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    # A static path can't be removed again, so register it once per run.
    if not domain_data.get("static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(FRONTEND_DIR / CARD_FILENAME), True)]
        )
        domain_data["static_registered"] = True

    url = versioned_card_url()
    if options[OPT_SIDEBAR_PANEL]:
        try:
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=PANEL_URL_PATH,
                webcomponent_name=PANEL_COMPONENT,
                sidebar_title=PANEL_TITLE,
                sidebar_icon=PANEL_ICON,
                module_url=url,
                require_admin=True,
                config={},
            )
            domain_data["panel_registered"] = True
        except ValueError:
            # Something else already uses this sidebar address. Don't fail
            # the whole integration over it; storage and notices still work.
            _LOGGER.warning(
                "Not adding the ZHA Bindings sidebar page: /%s is already used by another dashboard or panel",
                PANEL_URL_PATH,
            )
    if options[OPT_LOAD_EVERYWHERE]:
        frontend.add_extra_js_url(hass, url)
        domain_data["extra_js_url"] = url


def async_unload_frontend(hass: HomeAssistant) -> None:
    domain_data = hass.data.get(DOMAIN, {})
    if domain_data.pop("panel_registered", False):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
    url = domain_data.pop("extra_js_url", None)
    if url:
        frontend.remove_extra_js_url(hass, url)
