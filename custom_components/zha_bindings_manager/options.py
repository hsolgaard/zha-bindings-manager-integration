"""Reading the integration's options with their defaults."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DEFAULT_OPTIONS, DOMAIN


def options_from(entry: ConfigEntry | None) -> dict[str, Any]:
    opts = dict(DEFAULT_OPTIONS)
    if entry is not None:
        opts.update({k: v for k, v in (entry.options or {}).items() if k in DEFAULT_OPTIONS})
    return opts


def current_options(hass: HomeAssistant) -> dict[str, Any]:
    """Options of the (single) loaded entry, or the defaults."""
    entries = hass.config_entries.async_entries(DOMAIN)
    return options_from(entries[0] if entries else None)
