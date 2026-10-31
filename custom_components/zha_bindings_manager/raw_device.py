"""Raw device identity and signature, read from the device itself.

ZHA's view of a device goes through quirks. A quirk can change the
manufacturer and model ZHA shows (`friendly_name`), and it can replace the
device's endpoints and clusters with its own. zha_toolkit's scan_device
sends real ZCL discovery requests, but it decides which endpoints and
clusters to ask about, and reports the profile, device type, manufacturer
and model, from zigpy's in-memory device object, which is the quirk's
version when a quirk is loaded. Capability records built from that view can
describe the quirk rather than the device.

This module asks the device directly instead:

  - ZDO Active_EP_req and Simple_Desc_req for the real endpoint list and
    each endpoint's profile, device type and input/output clusters.
  - A raw read of the Basic cluster (manufacturer name, model identifier,
    app/hw version, date code, sw build id) through a plain zigpy Basic
    cluster object, so no quirk class, constant attribute or cached value
    is involved.
  - A raw read of the OTA client's CurrentFileVersion, the most reliable
    firmware identifier on devices that support OTA.

Every step reports its own status ("ok", "unsupported", "no_response",
"error") instead of a bare null, so "the device has no sw_build_id" and
"the device didn't answer" stay distinguishable.

Nothing here identifies the user's network: the IEEE address is only used
to find the device and is not returned.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # seconds per request; sleepy devices may need waking first

BASIC_CLUSTER = 0x0000
OTA_CLUSTER = 0x0019
OTA_CURRENT_FILE_VERSION = 0x0002
MANUFACTURER_SPECIFIC_MIN = 0xFC00

# Basic cluster attribute IDs, in the order they're requested.
BASIC_ATTRIBUTES: dict[str, int] = {
    "manufacturer": 0x0004,
    "model": 0x0005,
    "app_version": 0x0001,
    "hw_version": 0x0003,
    "date_code": 0x0006,
    "sw_build_id": 0x4000,
}

STATUS_OK = "ok"
STATUS_UNSUPPORTED = "unsupported"
STATUS_NO_RESPONSE = "no_response"
STATUS_ERROR = "error"
STATUS_NOT_AVAILABLE = "not_available"  # e.g. no OTA cluster on the device

# ZCL status codes that mean "the device doesn't have this attribute".
_ZCL_UNSUPPORTED = {0x86, 0x8F}  # UNSUPPORTED_ATTRIBUTE, UNREPORTABLE/legacy


class DeviceNotFound(LookupError):
    """The IEEE address isn't a device on this ZHA network."""


def zigpy_application(hass: HomeAssistant) -> Any:
    """The zigpy application controller behind ZHA."""
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway

        return get_zha_gateway(hass).application_controller
    except Exception:  # noqa: BLE001 - fall back to the hass.data layout
        pass
    data = hass.data.get("zha")
    for path in (("gateway_proxy", "gateway", "application_controller"), ("gateway", "application_controller")):
        obj = data
        try:
            for attr in path:
                obj = getattr(obj, attr)
        except AttributeError:
            continue
        if obj is not None:
            return obj
    raise LookupError("ZHA is not loaded")


def find_device(app: Any, ieee: str) -> Any:
    from zigpy.types import EUI64

    try:
        return app.get_device(ieee=EUI64.convert(ieee))
    except (KeyError, ValueError) as exc:
        raise DeviceNotFound(ieee) from exc


def _status_of(exc: BaseException) -> str:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return STATUS_NO_RESPONSE
    name = type(exc).__name__
    if "Timeout" in name or "Delivery" in name:
        return STATUS_NO_RESPONSE
    return STATUS_ERROR


async def _with_timeout(coro: Any) -> Any:
    async with asyncio.timeout(REQUEST_TIMEOUT):
        return await coro


def _hex4(value: int) -> str:
    return f"0x{int(value):04x}"


def _standard_cluster_name(cluster_id: int) -> str | None:
    """zigpy's own name for a standard ZCL cluster (never a quirk class).
    Manufacturer-specific IDs get None: their meaning depends on the vendor,
    and the capability database resolves those separately."""
    if cluster_id >= MANUFACTURER_SPECIFIC_MIN:
        return None
    try:
        from zigpy.zcl import Cluster

        cls = Cluster._registry.get(cluster_id)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return None
    return cls.__name__ if cls is not None else None


def _plain(value: Any) -> Any:
    """JSON-safe version of a zigpy attribute value."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return str(value)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    return str(value)


def parse_read_response(response: Any) -> dict[int, tuple[str, Any]]:
    """{attribute_id: (status, value)} from a Read_Attributes response, in
    whichever shape this zigpy version returns it."""
    records = getattr(response, "status_records", None)
    if records is None and isinstance(response, (list, tuple)) and response:
        records = response[0]
    out: dict[int, tuple[str, Any]] = {}
    for rec in records or []:
        try:
            attr_id = int(rec.attrid)
            status = int(rec.status)
        except (AttributeError, TypeError, ValueError):
            continue
        if status == 0:
            raw = getattr(rec.value, "value", rec.value)
            out[attr_id] = (STATUS_OK, _plain(raw))
        elif status in _ZCL_UNSUPPORTED:
            out[attr_id] = (STATUS_UNSUPPORTED, None)
        else:
            out[attr_id] = (STATUS_ERROR, None)
    return out


async def _raw_signature(device: Any) -> tuple[str, list[dict[str, Any]]]:
    """Endpoints straight from the device's ZDO descriptors."""
    try:
        rsp = await _with_timeout(device.zdo.Active_EP_req(device.nwk))
    except Exception as exc:  # noqa: BLE001
        return _status_of(exc), []
    try:
        status, active = int(rsp[0]), list(rsp[2])
    except (TypeError, IndexError, ValueError):
        return STATUS_ERROR, []
    if status != 0:
        return STATUS_ERROR, []

    endpoints: list[dict[str, Any]] = []
    overall = STATUS_OK
    for ep_id in sorted(int(e) for e in active):
        try:
            rsp = await _with_timeout(device.zdo.Simple_Desc_req(device.nwk, ep_id))
            status, desc = int(rsp[0]), rsp[2]
        except Exception as exc:  # noqa: BLE001
            overall = _status_of(exc)
            endpoints.append({"id": ep_id, "status": overall})
            continue
        if status != 0 or desc is None:
            overall = STATUS_ERROR
            endpoints.append({"id": ep_id, "status": STATUS_ERROR})
            continue
        in_ids = [int(c) for c in desc.input_clusters]
        out_ids = [int(c) for c in desc.output_clusters]
        endpoints.append(
            {
                "id": ep_id,
                "status": STATUS_OK,
                "profile": _hex4(desc.profile),
                "device_type": _hex4(desc.device_type),
                "in_clusters": [_hex4(c) for c in in_ids],
                "out_clusters": [_hex4(c) for c in out_ids],
            }
        )
    return overall, endpoints


def _first_endpoint_with(device: Any, raw_eps: list[dict[str, Any]], cluster: int, side: str) -> Any:
    """The zigpy endpoint object to send a raw read through: the first
    endpoint the device itself declares the cluster on that zigpy also has
    it on (replies are only routed for clusters zigpy knows about)."""
    want = _hex4(cluster)
    zigpy_side = "in_clusters" if side == "in_clusters" else "out_clusters"
    candidates = [e["id"] for e in raw_eps if want in e.get(side, [])]
    if not candidates:  # descriptors unavailable: fall back to zigpy's view
        candidates = [ep_id for ep_id in device.endpoints if ep_id != 0]
    for ep_id in candidates:
        ep = device.endpoints.get(ep_id)
        if ep is not None and ep_id != 0 and cluster in getattr(ep, zigpy_side, {}):
            return ep
    return None


async def _raw_basic(device: Any, raw_eps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from zigpy.zcl.clusters.general import Basic

    result = {name: {"status": STATUS_NOT_AVAILABLE, "value": None} for name in BASIC_ATTRIBUTES}
    endpoint = _first_endpoint_with(device, raw_eps, BASIC_CLUSTER, "in_clusters")
    if endpoint is None:
        return result
    cluster = Basic(endpoint, is_server=True)
    # Two small reads rather than one big one: some devices reject a whole
    # request if it contains one attribute they don't know.
    for group in (["manufacturer", "model"], ["app_version", "hw_version", "date_code", "sw_build_id"]):
        ids = [BASIC_ATTRIBUTES[n] for n in group]
        try:
            parsed = parse_read_response(await _with_timeout(cluster.read_attributes_raw(ids)))
        except Exception as exc:  # noqa: BLE001
            for n in group:
                result[n] = {"status": _status_of(exc), "value": None}
            continue
        for n in group:
            status, value = parsed.get(BASIC_ATTRIBUTES[n], (STATUS_ERROR, None))
            result[n] = {"status": status, "value": value}
    return result


async def _raw_ota_version(device: Any, raw_eps: list[dict[str, Any]]) -> dict[str, Any]:
    from zigpy.zcl.clusters.general import Ota

    endpoint = _first_endpoint_with(device, raw_eps, OTA_CLUSTER, "out_clusters")
    if endpoint is None:
        return {"status": STATUS_NOT_AVAILABLE, "value": None}
    cluster = Ota(endpoint, is_server=False)
    try:
        parsed = parse_read_response(
            await _with_timeout(cluster.read_attributes_raw([OTA_CURRENT_FILE_VERSION]))
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": _status_of(exc), "value": None}
    status, value = parsed.get(OTA_CURRENT_FILE_VERSION, (STATUS_ERROR, None))
    if status == STATUS_OK and isinstance(value, int):
        value = f"0x{value:08x}"
    return {"status": status, "value": value}


def _node_info(device: Any) -> dict[str, Any]:
    """Node descriptor facts zigpy stored from the device's interview."""
    desc = getattr(device, "node_desc", None)
    if desc is None:
        return {}
    out: dict[str, Any] = {}
    logical = getattr(desc, "logical_type", None)
    if logical is not None:
        out["logical_type"] = getattr(logical, "name", str(logical))
    for key, attr in (("mains_powered", "is_mains_powered"), ("rx_on_when_idle", "is_receiver_on_when_idle")):
        value = getattr(desc, attr, None)
        if isinstance(value, bool):
            out[key] = value
    code = getattr(desc, "manufacturer_code", None)
    if code is not None:
        out["manufacturer_code"] = _hex4(code)
    return out


def _quirk_applied(device: Any) -> bool:
    try:
        import zigpy.device

        return type(device) is not zigpy.device.Device
    except Exception:  # noqa: BLE001
        return False


async def async_get_raw_device_info(hass: HomeAssistant, ieee: str) -> dict[str, Any]:
    device = find_device(zigpy_application(hass), ieee)
    signature_status, raw_eps = await _raw_signature(device)
    basic = await _raw_basic(device, raw_eps)
    ota = await _raw_ota_version(device, raw_eps)

    cluster_ids: set[int] = set()
    for ep in raw_eps:
        for key in ("in_clusters", "out_clusters"):
            cluster_ids.update(int(c, 16) for c in ep.get(key, []))
    names = {_hex4(c): n for c in sorted(cluster_ids) if (n := _standard_cluster_name(c))}

    return {
        "manufacturer": basic["manufacturer"],
        "model": basic["model"],
        "identity": {
            "sw_build_id": basic["sw_build_id"],
            "app_version": basic["app_version"],
            "hw_version": basic["hw_version"],
            "date_code": basic["date_code"],
            "ota_file_version": ota,
        },
        "signature": {"status": signature_status, "endpoints": raw_eps},
        "standard_cluster_names": names,
        "node": _node_info(device),
        "quirk_applied": _quirk_applied(device),
    }
