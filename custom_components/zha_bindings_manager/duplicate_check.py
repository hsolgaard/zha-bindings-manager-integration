"""Raises a Repairs issue when the card is also installed from HACS.

With this integration, the separate HACS card (hsolgaard/zha-bindings-
manager) isn't needed. If both are installed, two copies of the card
compete for the page and whichever loads first is the one that runs. The
card copes (the second copy steps aside), but the version you see may not
be the one this integration ships, so ask the user to remove the HACS card.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, HACS_CARD_URL_FRAGMENT, ISSUE_CARD_INSTALLED_TWICE

_LOGGER = logging.getLogger(__name__)


def _resources_collection(hass: HomeAssistant) -> Any:
    data = hass.data.get("lovelace")
    if data is None:
        return None
    # A dataclass since HA 2025.x, a plain dict before that.
    return getattr(data, "resources", None) or (data.get("resources") if isinstance(data, dict) else None)


async def async_hacs_card_resource(hass: HomeAssistant) -> str | None:
    """The Lovelace resource URL of the separately installed card, if any."""
    resources = _resources_collection(hass)
    if resources is None:
        return None
    try:
        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()  # loads storage-mode resources on first use
        items = resources.async_items() or []
    except Exception:  # noqa: BLE001 - a check that can't run just doesn't report
        _LOGGER.debug("Could not read Lovelace resources", exc_info=True)
        return None
    for item in items:
        url = str(item.get("url", ""))
        if HACS_CARD_URL_FRAGMENT in url:
            return url
    return None


async def async_check_card_installed_twice(hass: HomeAssistant) -> None:
    url = await async_hacs_card_resource(hass)
    if url:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_CARD_INSTALLED_TWICE,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_CARD_INSTALLED_TWICE,
            translation_placeholders={"resource": url},
            learn_more_url="https://github.com/hsolgaard/zha-bindings-manager-integration#installed-the-card-from-hacs-too",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_CARD_INSTALLED_TWICE)
