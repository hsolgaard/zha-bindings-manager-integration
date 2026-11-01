"""Bindings shown on Home Assistant's own ZHA device pages (1.2.0).

Answers the WTH thread "Is device binding a second-class citizen?": each
ZHA device that controls, or is controlled by, another device or a group
gets two entities on its normal device page:
  - "Bindings" (diagnostic sensor): what it controls and what controls it,
  - "Rescan bindings" (button): reads its binding table again.

Sources of binding data, newest per device wins:
  - the card's saved scan data (shared storage, per card instance),
  - rescans done here (stored under zha_bindings_manager/scans).
Devices with only coordinator bindings get nothing, to keep the entity
count down.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import storage
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .bindings import (
    BindsGetFailed,
    devices_with_bindings,
    guess_coordinator,
    norm_ieee,
    parse_binds_get,
    summarize,
)
from .const import DOMAIN, SIGNAL_BINDINGS_UPDATED

_LOGGER = logging.getLogger(__name__)

SCANS_STORAGE_KEY = f"{DOMAIN}/scans"
ZHA_DOMAIN = "zha"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def card_bindings(store_data: dict[str, Any]) -> dict[str, tuple[str, list[dict]]]:
    """{source_ieee: (read_at, bindings)} from every card instance's saved
    scan data; the most recently read copy wins for each device.

    read_at is when the card last read that device successfully (its
    per-device history, lastSuccessAt), not when it last saved: the card
    saves its whole scan data on every scan, so the save time would make an
    old copy of one device look newer than a device-page rescan."""
    out: dict[str, tuple[str, list[dict]]] = {}
    for entry in (store_data or {}).values():
        if not isinstance(entry, dict):
            continue
        state = entry.get("state") or {}
        last = ((state.get("scanState") or {}).get("last_complete")) or {}
        saved_at = last.get("savedAt") or entry.get("updated_at") or ""
        history = state.get("history") or {}
        for ieee, lst in (last.get("bindings") or {}).items():
            key = norm_ieee(ieee)
            h = history.get(key) or history.get(ieee) or {}
            read_at = h.get("lastSuccessAt") or saved_at
            if key not in out or read_at > out[key][0]:
                out[key] = (read_at, lst if isinstance(lst, list) else [])
    return out


def merge_sources(card: dict[str, tuple[str, list]], scans: dict[str, dict]) -> dict[str, list[dict]]:
    """Newest per device of the card's data and rescans done here."""
    merged = {k: v[1] for k, v in card.items()}
    for ieee, scan in (scans or {}).items():
        key = norm_ieee(ieee)
        if key not in card or (scan.get("at") or "") > card[key][0]:
            merged[key] = scan.get("bindings") or []
    return merged


class DeviceBindings:
    """Loads, merges and serves binding data for the device-page entities."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._scans_store = storage.Store(hass, 1, SCANS_STORAGE_KEY)
        self.scans: dict[str, dict] = {}
        self.by_source: dict[str, list[dict]] = {}
        self.coordinator: str | None = None
        self.exposed: set[str] = set()

    async def async_load(self) -> None:
        data = await self._scans_store.async_load()
        self.scans = data if isinstance(data, dict) else {}
        await self.async_refresh()

    async def async_refresh(self) -> None:
        from .websocket_api import _load  # local import: avoids a cycle

        card = card_bindings(await _load(self.hass))
        self.by_source = merge_sources(card, self.scans)
        self.coordinator = self._gateway_coordinator() or guess_coordinator(self.by_source)
        exposed = devices_with_bindings(self.by_source, self.coordinator)
        # Only devices ZHA actually has, so no orphan devices get created.
        self.exposed = {i for i in exposed if self.zha_device(i) is not None}
        async_dispatcher_send(self.hass, SIGNAL_BINDINGS_UPDATED)

    # --- ZHA lookups -------------------------------------------------------

    def zha_device(self, ieee: str) -> dr.DeviceEntry | None:
        registry = dr.async_get(self.hass)
        return registry.async_get_device(identifiers={(ZHA_DOMAIN, norm_ieee(ieee))}) or registry.async_get_device(
            connections={(dr.CONNECTION_ZIGBEE, norm_ieee(ieee))}
        )

    def names(self) -> dict[str, str]:
        registry = dr.async_get(self.hass)
        out: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries(ZHA_DOMAIN):
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                for domain, value in device.identifiers:
                    if domain == ZHA_DOMAIN:
                        out[norm_ieee(value)] = device.name_by_user or device.name or norm_ieee(value)
        return out

    def _gateway(self) -> Any:
        try:
            from homeassistant.components.zha.helpers import get_zha_gateway  # type: ignore

            return get_zha_gateway(self.hass)
        except Exception:  # noqa: BLE001 - internal ZHA API, optional
            return None

    def _gateway_coordinator(self) -> str | None:
        gw = self._gateway()
        try:
            return norm_ieee(str(gw.state.node_info.ieee)) if gw else None
        except Exception:  # noqa: BLE001
            return None

    def groups(self) -> tuple[dict[int, str], dict[int, set[str]]]:
        """ZHA group names and members, when ZHA's gateway can be asked."""
        names: dict[int, str] = {}
        members: dict[int, set[str]] = {}
        gw = self._gateway()
        try:
            for gid, group in (getattr(gw, "groups", None) or {}).items():
                names[int(gid)] = getattr(group, "name", None) or f"group {gid}"
                members[int(gid)] = {
                    norm_ieee(str(getattr(getattr(m, "device", None), "ieee", "")))
                    for m in (getattr(group, "members", None) or [])
                }
        except Exception:  # noqa: BLE001
            pass
        return names, members

    # --- per device ----------------------------------------------------------

    def summary(self, ieee: str) -> dict[str, Any]:
        group_names, group_members = self.groups()
        s = summarize(ieee, self.by_source, self.coordinator, self.names(), group_names, group_members)
        scan = self.scans.get(norm_ieee(ieee))
        s["last_rescanned"] = scan.get("at") if scan else None
        return s

    async def async_rescan(self, ieee: str) -> int:
        """Reads the device's binding table with zha_toolkit.binds_get.
        Returns the number of bindings read; raises BindsGetFailed."""
        if not self.hass.services.has_service("zha_toolkit", "binds_get"):
            raise BindsGetFailed("zha-toolkit isn't installed or isn't loaded")
        try:
            response = await self.hass.services.async_call(
                "zha_toolkit", "binds_get", {"ieee": norm_ieee(ieee)}, blocking=True, return_response=True
            )
        except Exception as err:  # noqa: BLE001 - reported to the user
            raise BindsGetFailed(str(err)) from err
        bindings, partial = parse_binds_get(ieee, response)
        self.scans[norm_ieee(ieee)] = {"at": _now_iso(), "bindings": bindings, "partial": partial}
        await self._scans_store.async_save(self.scans)
        await self.async_refresh()
        return len(bindings)


@callback
def get_device_bindings(hass: HomeAssistant) -> DeviceBindings | None:
    return hass.data.get(DOMAIN, {}).get("device_bindings")
