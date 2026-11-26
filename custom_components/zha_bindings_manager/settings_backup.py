"""Device configuration backup (1.12.0).

Saves a device's settings, the writable attributes ZHA knows on each of its
endpoints' input (server) clusters, so they can be viewed, restored after a
re-pair (removing a device from ZHA factory-resets it), or applied to
another device (a replacement). SONOFF's detach-relay mode, a switch's
power-on behaviour or a dimmer's minimum level are all attributes like
this, defined by zigpy or by the device's quirk.

What's in a backup:
- endpoints -> clusters -> attributes: value, and how to show it,
- the device's ZHA group memberships and its bindings (for the record and
  for export; bindings are put back by the watch, groups by the card),
- model, manufacturer, firmware and when.

What isn't: clusters that aren't settings (Basic, Identify, Time, OTA,
Poll Control, Diagnostics, Groups, Scenes), On/Off's on_time and
off_wait_time (timers), read-only attributes, and attributes ZHA has no
definition for (there's no safe way to write those back).

Talks to zigpy directly, like unbind_api.py. Nothing is ever written
without a plan the user has seen; every write is read back.
"""
from __future__ import annotations

import asyncio
import enum
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import storage
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .bindings import norm_ieee, relationship_map
from .const import DOMAIN, SIGNAL_BINDINGS_UPDATED

_LOGGER = logging.getLogger(__name__)

SETTINGS_STORAGE_KEY = f"{DOMAIN}/settings"
KEEP = 5
AUTO_AFTER = timedelta(days=7)
READ_TIMEOUT = 20
CHUNK = 4  # attributes per read request; keeps each answer small
PAUSE_BETWEEN_DEVICES = 2.0

# Clusters whose writable attributes aren't settings.
SKIP_CLUSTERS = {
    0x0000,  # Basic (location, physical environment: rarely set, never by ZBM)
    0x0003,  # Identify (identify_time is a countdown)
    0x0004,  # Groups (memberships are saved separately)
    0x0005,  # Scenes
    0x000A,  # Time
    0x0019,  # OTA
    0x0020,  # Poll Control (check-in timers)
    0x0B05,  # Diagnostics
}
# Single attributes that are timers or state, not settings.
SKIP_ATTRIBUTES = {
    (0x0006, 0x4001),  # on_time
    (0x0006, 0x4002),  # off_wait_time
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _app(hass: HomeAssistant) -> Any:
    if "zha" not in hass.config.components:
        return None
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway  # type: ignore

        return get_zha_gateway(hass).application_controller
    except Exception:  # noqa: BLE001 - internal ZHA API
        return None


def _device(app: Any, ieee: str) -> Any:
    import zigpy.types as t  # type: ignore

    try:
        return app.get_device(ieee=t.EUI64.convert(norm_ieee(ieee)))
    except KeyError:
        return None


def is_writable(attr_def: Any) -> bool:
    try:
        from zigpy.zcl.foundation import ZCLAttributeAccess  # type: ignore

        return bool(attr_def.access & ZCLAttributeAccess.Write)
    except Exception:  # noqa: BLE001
        return False


def settings_attributes(cluster: Any) -> list[Any]:
    """The attribute definitions of one cluster worth backing up."""
    cid = int(cluster.cluster_id)
    if cid in SKIP_CLUSTERS:
        return []
    unsupported = getattr(cluster, "unsupported_attributes", set()) or set()
    out = []
    for attr_def in (getattr(cluster, "attributes", None) or {}).values():
        if attr_def.id is None or not attr_def.name:
            continue
        if (cid, int(attr_def.id)) in SKIP_ATTRIBUTES or not is_writable(attr_def):
            continue
        if attr_def.id in unsupported or attr_def.name in unsupported:
            continue
        out.append(attr_def)
    return sorted(out, key=lambda a: int(a.id))


def to_json(value: Any) -> tuple[Any, str | None]:
    """(value for storage, label to show). Enums keep their number, with the
    name as the label; everything else is a plain JSON value."""
    if isinstance(value, enum.Enum):
        raw = value.value
        return (int(raw) if isinstance(raw, int) else raw), str(value.name)
    if isinstance(value, bool):
        return value, None
    if isinstance(value, int):
        return int(value), None
    if isinstance(value, float):
        return float(value), None
    if isinstance(value, (str, bytes)):
        return (value.decode(errors="replace") if isinstance(value, bytes) else str(value)), None
    if isinstance(value, (list, tuple)):
        try:
            return [to_json(v)[0] for v in value], None
        except Exception:  # noqa: BLE001
            return str(value), None
    return str(value), None


def same_value(a: Any, b: Any) -> bool:
    return a == b or str(a) == str(b)


def firmware_of(device: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ep_id, ep in (getattr(device, "endpoints", None) or {}).items():
        if ep_id == 0:
            continue
        basic = (getattr(ep, "in_clusters", None) or {}).get(0x0000)
        if basic is not None and "sw_build_id" not in out:
            try:
                val = basic.get("sw_build_id")
                if val is not None:
                    out["sw_build_id"] = str(val)
            except Exception:  # noqa: BLE001
                pass
        ota = (getattr(ep, "out_clusters", None) or {}).get(0x0019)
        if ota is not None and "ota_version" not in out:
            try:
                val = ota.get("current_file_version")
                if val is not None:
                    out["ota_version"] = int(val)
            except Exception:  # noqa: BLE001
                pass
    return out


class SettingsBackup:
    def __init__(self, hass: HomeAssistant, data: Any) -> None:
        self.hass = hass
        self.data = data  # DeviceBindings: names, groups, scans
        self._store = storage.Store(hass, 1, SETTINGS_STORAGE_KEY)
        self.saved: dict[str, dict[str, Any]] = {}
        self._busy: set[str] = set()
        self._auto_queue: list[str] = []
        self._auto_running = False
        self.pause = PAUSE_BETWEEN_DEVICES
        self.app_getter = _app

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self.saved = stored if isinstance(stored, dict) else {}

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self.saved, 1)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        return async_dispatcher_connect(self.hass, SIGNAL_BINDINGS_UPDATED, self._after_scans)

    # --- reading -----------------------------------------------------------------

    async def _read_cluster(self, cluster: Any, defs: list[Any]) -> tuple[dict[str, Any], int]:
        """{attr name: value} for the attributes that answered, and how many didn't."""
        values: dict[str, Any] = {}
        missed = 0
        for i in range(0, len(defs), CHUNK):
            names = [d.name for d in defs[i : i + CHUNK]]
            try:
                async with asyncio.timeout(READ_TIMEOUT):
                    res = await cluster.read_attributes(names, allow_cache=False)
            except Exception as err:  # noqa: BLE001 - didn't answer
                _LOGGER.debug("Reading %s from cluster 0x%04x failed: %s", names, cluster.cluster_id, err)
                missed += len(names)
                continue
            success = res[0] if isinstance(res, (list, tuple)) else res
            for name in names:
                if name in success:
                    values[name] = success[name]
        return values, missed

    async def async_snapshot(self, ieee: str, reason: str = "manual") -> dict[str, Any]:
        """Reads the device's settings and saves them. Returns the backup, or
        {"error": ...} if it couldn't be read at all."""
        ieee = norm_ieee(ieee)
        app = self.app_getter(self.hass)
        if app is None:
            return {"error": "zha_unavailable"}
        device = _device(app, ieee)
        if device is None:
            return {"error": "not_in_zha"}
        if ieee in self._busy:
            return {"error": "busy"}
        self._busy.add(ieee)
        try:
            endpoints: dict[str, Any] = {}
            wanted = missed = 0
            for ep_id, ep in sorted((device.endpoints or {}).items()):
                if ep_id == 0 or ep_id == 242:  # ZDO, Green Power
                    continue
                for cid, cluster in sorted((ep.in_clusters or {}).items()):
                    defs = settings_attributes(cluster)
                    if not defs:
                        continue
                    wanted += len(defs)
                    values, miss = await self._read_cluster(cluster, defs)
                    missed += miss
                    attrs = {}
                    for d in defs:
                        if d.name not in values:
                            continue
                        val, label = to_json(values[d.name])
                        attrs[f"0x{int(d.id):04x}"] = {
                            "name": d.name,
                            "value": val,
                            **({"label": label} if label else {}),
                            **({"manufacturer_specific": True} if d.is_manufacturer_specific or int(cid) >= 0xFC00 else {}),
                        }
                    if attrs:
                        endpoints.setdefault(str(ep_id), {})[f"0x{int(cid):04x}"] = {"name": getattr(cluster, "ep_attribute", None) or cluster.name, "attributes": attrs}
            if wanted and missed == wanted:
                return {"error": "no_answer"}
            snap = {
                "id": _now().isoformat(),
                "taken_at": _now().isoformat(),
                "reason": reason,
                "model": getattr(device, "model", None),
                "manufacturer": getattr(device, "manufacturer", None),
                "firmware": firmware_of(device),
                "endpoints": endpoints,
                "groups": self.data.group_memberships(ieee) or [],
                "bindings": list(relationship_map(self._bindings_of(ieee), self.data.coordinator).values()),
                "unread": missed,
            }
            self._keep(ieee, snap)
            return snap
        finally:
            self._busy.discard(ieee)

    def _bindings_of(self, ieee: str) -> list[dict]:
        scan = (getattr(self.data, "scans", {}) or {}).get(ieee)
        if scan and scan.get("bindings") is not None:
            return scan.get("bindings") or []
        return (getattr(self.data, "by_source", {}) or {}).get(ieee) or []

    def _keep(self, ieee: str, snap: dict[str, Any]) -> None:
        entry = self.saved.setdefault(ieee, {"snapshots": []})
        if snap.get("reason") == "after_reset":
            entry["after_reset"] = snap
        else:
            entry["snapshots"] = [snap, *[s for s in entry.get("snapshots") or [] if s.get("id") != snap.get("id")]][:KEEP]
        self._save()

    # --- automatic backups ---------------------------------------------------------

    @callback
    def _after_scans(self) -> None:
        """After the card saved a scan: back up mains devices that have no
        backup from the last 7 days, one at a time in the background."""
        for ieee in list((getattr(self.data, "card", {}) or {}).keys()):
            if self.is_due(ieee) and ieee not in self._auto_queue:
                self._auto_queue.append(ieee)
        if self._auto_queue and not self._auto_running:
            self.hass.async_create_background_task(self._run_auto(), f"{DOMAIN} settings backup")

    def is_due(self, ieee: str) -> bool:
        ieee = norm_ieee(ieee)
        if ieee == norm_ieee(self.data.coordinator or ""):
            return False
        # A re-paired device has its factory settings until it's restored: an
        # automatic backup now would hide the one from before the removal.
        w = (getattr(self.hass.data.get(DOMAIN, {}).get("watch"), "tracked", {}) or {}).get(ieee) or {}
        if w.get("repaired") or w.get("removed_at"):
            return False
        snaps = (self.saved.get(ieee) or {}).get("snapshots") or []
        if snaps:
            try:
                if _now() - datetime.fromisoformat(snaps[0]["taken_at"]) < AUTO_AFTER:
                    return False
            except (KeyError, ValueError):
                pass
        return self._mains_powered(ieee)

    def _mains_powered(self, ieee: str) -> bool:
        app = self.app_getter(self.hass)
        device = _device(app, ieee) if app is not None else None
        if device is None:
            return False
        node = getattr(device, "node_desc", None)
        try:
            return bool(node and node.is_mains_powered)
        except Exception:  # noqa: BLE001
            return False

    async def _run_auto(self) -> None:
        self._auto_running = True
        try:
            while self._auto_queue:
                ieee = self._auto_queue.pop(0)
                if not self.is_due(ieee):
                    continue
                res = await self.async_snapshot(ieee, "auto")
                if res.get("error"):
                    _LOGGER.debug("Automatic settings backup of %s: %s", ieee, res["error"])
                if self.pause:
                    await asyncio.sleep(self.pause)
        finally:
            self._auto_running = False

    # --- looking at backups --------------------------------------------------------

    def get(self, ieee: str) -> dict[str, Any]:
        entry = self.saved.get(norm_ieee(ieee)) or {}
        return {"snapshots": entry.get("snapshots") or [], "after_reset": entry.get("after_reset")}

    def find(self, ieee: str, snapshot_id: str | None = None, before: str | None = None) -> dict[str, Any] | None:
        """A backup by id, or the newest one (taken before `before`, if given)."""
        entry = self.saved.get(norm_ieee(ieee)) or {}
        if snapshot_id == "after_reset":
            return entry.get("after_reset")
        for snap in entry.get("snapshots") or []:
            if snapshot_id and snap.get("id") != snapshot_id:
                continue
            if before and str(snap.get("taken_at") or "") >= before:
                continue
            return snap
        return None

    def import_snapshot(self, ieee: str, snap: dict[str, Any]) -> dict[str, Any]:
        """A backup from a file: kept like any other, marked imported."""
        if not isinstance(snap.get("endpoints"), dict):
            raise ValueError("not a settings backup")
        clean = {**snap, "reason": "import", "id": _now().isoformat(), "imported_at": _now().isoformat()}
        clean.setdefault("taken_at", clean["id"])
        self._keep(norm_ieee(ieee), clean)
        return clean

    # --- planning and applying -----------------------------------------------------

    async def async_plan(self, snap: dict[str, Any], target_ieee: str, endpoint_map: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compares a backup with what the target device has now. Each row:
        endpoint, cluster, attribute, name, saved, current, state:
        "differs" | "same" | "not_on_device" | "not_read". Rows that differ
        are the ones offered (ticked) for writing."""
        target_ieee = norm_ieee(target_ieee)
        app = self.app_getter(self.hass)
        if app is None:
            return {"error": "zha_unavailable"}
        device = _device(app, target_ieee)
        if device is None:
            return {"error": "not_in_zha"}
        emap = {str(k): int(v) for k, v in (endpoint_map or {}).items()}
        rows: list[dict[str, Any]] = []
        read_any = asked_any = False
        for ep_key, clusters in sorted((snap.get("endpoints") or {}).items(), key=lambda kv: int(kv[0])):
            ep_id = emap.get(str(ep_key), int(ep_key))
            ep = (device.endpoints or {}).get(ep_id)
            for c_key, cdata in sorted((clusters or {}).items()):
                cid = int(c_key, 16)
                cluster = (getattr(ep, "in_clusters", None) or {}).get(cid) if ep is not None else None
                defs_by_id = {int(d.id): d for d in settings_attributes(cluster)} if cluster is not None else {}
                pending: list[tuple[dict, Any]] = []
                for a_key, a in sorted((cdata.get("attributes") or {}).items()):
                    aid = int(a_key, 16)
                    row = {
                        "endpoint": ep_id,
                        "saved_endpoint": int(ep_key),
                        "cluster": cid,
                        "cluster_name": cdata.get("name"),
                        "attribute": aid,
                        "name": a.get("name"),
                        "saved": a.get("value"),
                        "saved_label": a.get("label"),
                        "manufacturer_specific": bool(a.get("manufacturer_specific")),
                    }
                    d = defs_by_id.get(aid)
                    if d is None:
                        rows.append({**row, "state": "not_on_device"})
                        continue
                    pending.append((row, d))
                if pending:
                    asked_any = True
                    values, _missed = await self._read_cluster(cluster, [d for _, d in pending])
                    for row, d in pending:
                        if d.name not in values:
                            rows.append({**row, "state": "not_read"})
                            continue
                        read_any = True
                        cur, label = to_json(values[d.name])
                        state = "same" if same_value(cur, row["saved"]) else "differs"
                        rows.append({**row, "current": cur, "current_label": label, "state": state})
        if asked_any and not read_any:
            return {"error": "no_answer", "rows": rows}
        snap_fw = (snap.get("firmware") or {})
        now_fw = firmware_of(device)
        return {
            "target": target_ieee,
            "snapshot_id": snap.get("id"),
            "taken_at": snap.get("taken_at"),
            "same_model": (snap.get("model") or None) == (getattr(device, "model", None) or None),
            "firmware_differs": bool(snap_fw and now_fw and snap_fw != now_fw),
            "firmware": {"saved": snap_fw, "now": now_fw},
            "rows": rows,
        }

    async def async_apply(self, target_ieee: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Writes the chosen settings and reads each one back.
        items: [{endpoint, cluster, attribute, value}].
        Result per item: "restored" | "refused" (with the device's status) |
        "didnt_stick" (accepted but reads back differently) | "no_answer" |
        "not_on_device"."""
        target_ieee = norm_ieee(target_ieee)
        app = self.app_getter(self.hass)
        if app is None:
            return {"error": "zha_unavailable"}
        device = _device(app, target_ieee)
        if device is None:
            return {"error": "not_in_zha"}
        results: list[dict[str, Any]] = []
        by_cluster: dict[tuple[int, int], list[dict]] = {}
        for it in items:
            by_cluster.setdefault((int(it["endpoint"]), int(it["cluster"])), []).append(it)
        for (ep_id, cid), its in sorted(by_cluster.items()):
            ep = (device.endpoints or {}).get(ep_id)
            cluster = (getattr(ep, "in_clusters", None) or {}).get(cid) if ep is not None else None
            defs_by_id = {int(d.id): d for d in settings_attributes(cluster)} if cluster is not None else {}
            for it in its:
                d = defs_by_id.get(int(it["attribute"]))
                base = {"endpoint": ep_id, "cluster": cid, "attribute": int(it["attribute"])}
                if d is None:
                    results.append({**base, "result": "not_on_device"})
                    continue
                base["name"] = d.name
                try:
                    async with asyncio.timeout(READ_TIMEOUT):
                        res = await cluster.write_attributes({d.name: it["value"]})
                except Exception as err:  # noqa: BLE001
                    results.append({**base, "result": "no_answer", "detail": str(err) or type(err).__name__})
                    continue
                status = _write_status(res)
                if status != "SUCCESS":
                    results.append({**base, "result": "refused", "status": status})
                    continue
                values, _ = await self._read_cluster(cluster, [d])
                if d.name not in values:
                    results.append({**base, "result": "no_answer", "detail": "written, but it didn't answer the read-back"})
                    continue
                now, label = to_json(values[d.name])
                results.append({**base, "result": "restored" if same_value(now, it["value"]) else "didnt_stick", "now": now, "now_label": label})
        done = sum(1 for r in results if r["result"] == "restored")
        return {"target": target_ieee, "results": results, "restored": done, "total": len(results)}


def _write_status(res: Any) -> str:
    """'SUCCESS' or the device's status name from a write_attributes result."""
    try:
        records = res[0] if isinstance(res, (list, tuple)) and res and isinstance(res[0], (list, tuple)) else res
        for rec in records or []:
            st = getattr(rec, "status", rec)
            name = getattr(st, "name", None) or str(st)
            if name != "SUCCESS":
                return name
        return "SUCCESS"
    except Exception:  # noqa: BLE001
        return "SUCCESS"


@callback
def get_settings(hass: HomeAssistant) -> SettingsBackup | None:
    return hass.data.get(DOMAIN, {}).get("settings")
