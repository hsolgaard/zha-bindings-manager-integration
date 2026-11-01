"""Pure helpers for bindings on the ZHA device page (1.2.0).

No Home Assistant imports, so tests can call them directly.

Binding dicts use the card's normalized shape (see the card's parser.js):
    {id, sourceIeee, sourceEndpoint, clusterId, isGroup,
     targetIeee, targetEndpoint, groupId}
"""
from __future__ import annotations

from typing import Any, Iterable

CLUSTER_NAMES = {
    0x0000: "Basic",
    0x0001: "Power Configuration",
    0x0003: "Identify",
    0x0004: "Groups",
    0x0005: "Scenes",
    0x0006: "On/Off",
    0x0008: "Level Control",
    0x000A: "Time",
    0x0019: "OTA",
    0x0020: "Poll Control",
    0x0102: "Window Covering",
    0x0201: "Thermostat",
    0x0300: "Colour Control",
    0x0400: "Illuminance",
    0x0402: "Temperature",
    0x0405: "Humidity",
    0x0406: "Occupancy",
    0x0500: "IAS Zone",
    0x0702: "Metering",
    0x0B04: "Electrical Measurement",
}


def norm_ieee(ieee: Any) -> str:
    return str(ieee or "").strip().lower()


def cluster_name(cluster_id: int) -> str:
    return CLUSTER_NAMES.get(int(cluster_id), f"0x{int(cluster_id):04x}")


def _ieee_bytes_to_str(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) == 8:
        return ":".join(f"{int(b):02x}" for b in reversed(value))
    return None


def _le16(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]) + int(value[1]) * 256
    return None


def _to_int(value: Any) -> int:
    if isinstance(value, str):
        return int(value.replace("0x", "").replace("0X", ""), 16)
    return int(value)


def _binding(source: str, src_ep: Any, cluster_id: int, is_group: bool, dst_ieee: str | None, dst_ep: Any, group: Any) -> dict:
    return {
        "id": f"{source}|{src_ep}|{cluster_id}|{'g' + str(group) if is_group else f'{dst_ieee}:{dst_ep}'}",
        "sourceIeee": norm_ieee(source),
        "sourceEndpoint": src_ep,
        "clusterId": cluster_id,
        "isGroup": is_group,
        "targetIeee": None if is_group else norm_ieee(str(dst_ieee or "").replace("0x", "")),
        "targetEndpoint": None if is_group else dst_ep,
        "groupId": int(group) if is_group and group is not None else None,
    }


def identity_key(b: dict) -> str:
    target = f"g:{b.get('groupId')}" if b.get("isGroup") else f"d:{norm_ieee(b.get('targetIeee'))}:{b.get('targetEndpoint')}"
    return f"{norm_ieee(b.get('sourceIeee'))}|{b.get('sourceEndpoint')}|{int(b.get('clusterId'))}|{target}"


class BindsGetFailed(Exception):
    """binds_get returned nothing usable (device asleep, offline, ...)."""


def parse_binds_get(source_ieee: str, response: dict | None) -> tuple[list[dict], bool]:
    """zha_toolkit.binds_get response -> (bindings, partial).

    Merges both shapes zha_toolkit has used: response["result"] (a dict of
    entries) and response["replies"] (raw ZDO Mgmt_Bind_rsp pages). Raises
    BindsGetFailed when the call failed and nothing usable came back.
    """
    response = response or {}
    failed = bool(response.get("errors")) or response.get("success") is False
    out: list[dict] = []

    for raw in (response.get("result") or {}).values():
        try:
            dst = raw.get("dst") or {}
            is_group = int(dst.get("addrmode", 3)) == 1
            group = dst.get("group")
            if is_group and isinstance(group, str):
                group = int(group.replace("0x", ""), 16)
            out.append(
                _binding(
                    source_ieee,
                    raw.get("src_ep"),
                    _to_int(raw.get("cluster_id")),
                    is_group,
                    dst.get("dst_ieee"),
                    dst.get("dst_ep"),
                    group,
                )
            )
        except (TypeError, ValueError, AttributeError):
            continue

    for page in response.get("replies") or []:
        entries = None
        if isinstance(page, list) and page:
            last = page[-1]
            if isinstance(last, list):
                entries = last
            elif all(isinstance(p, dict) for p in page):
                entries = page
        for raw in entries or []:
            try:
                src_ep = raw.get("SrcEndpoint", raw.get("src_ep"))
                cid = raw.get("ClusterId", raw.get("cluster_id"))
                dst = raw.get("DstAddress", raw.get("dst")) or {}
                mode = int(dst.get("addrmode", dst.get("AddrMode", 3)))
                is_group = mode == 1
                dst_ieee = dst.get("ieee", dst.get("IEEE", dst.get("dst_ieee")))
                if isinstance(dst_ieee, (list, tuple)):
                    dst_ieee = _ieee_bytes_to_str(dst_ieee)
                group = dst.get("nwk", dst.get("group", dst.get("group_id")))
                if isinstance(group, (list, tuple)):
                    group = _le16(group)
                if src_ep is None or cid is None or (not is_group and not dst_ieee):
                    continue
                out.append(_binding(source_ieee, src_ep, _to_int(cid), is_group, dst_ieee, dst.get("endpoint", dst.get("dst_ep")), group))
            except (TypeError, ValueError, AttributeError):
                continue

    seen: set[str] = set()
    bindings = []
    for b in out:
        key = identity_key(b)
        if key in seen:
            continue
        seen.add(key)
        bindings.append(b)
    if failed and not bindings:
        raise BindsGetFailed("; ".join(response.get("errors") or []) or response.get("warning") or "binds_get reported failure")
    return bindings, failed


def guess_coordinator(bindings_by_source: dict[str, list[dict]]) -> str | None:
    """The device most other devices bind to. Every ZHA device binds its
    reporting clusters to the coordinator, so with 3+ sources the most
    common target that a majority points at is almost always it. Only a
    fallback for when ZHA's gateway can't be asked directly."""
    counts: dict[str, int] = {}
    for source, lst in bindings_by_source.items():
        for target in {norm_ieee(b.get("targetIeee")) for b in lst or [] if not b.get("isGroup")}:
            if target and target != norm_ieee(source):
                counts[target] = counts.get(target, 0) + 1
    if not counts or len(bindings_by_source) < 3:
        return None
    best = max(counts, key=counts.get)
    return best if counts[best] * 2 > len(bindings_by_source) else None


def is_relationship(b: dict, coordinator: str | None) -> bool:
    """A binding worth showing on a device page: to a group, or to another
    device that isn't the coordinator (those are routine reporting)."""
    if b.get("isGroup"):
        return True
    target = norm_ieee(b.get("targetIeee"))
    return bool(target) and target != norm_ieee(coordinator) and target != norm_ieee(b.get("sourceIeee"))


def devices_with_bindings(bindings_by_source: dict[str, list[dict]], coordinator: str | None) -> set[str]:
    """IEEEs that control, or are controlled by, another device or a group."""
    out: set[str] = set()
    for source, lst in bindings_by_source.items():
        for b in lst or []:
            if not is_relationship(b, coordinator):
                continue
            out.add(norm_ieee(source))
            if not b.get("isGroup"):
                out.add(norm_ieee(b.get("targetIeee")))
    return out


def _group_by(items: Iterable[tuple[str, int]]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for label, cid in items:
        names = grouped.setdefault(label, [])
        name = cluster_name(cid)
        if name not in names:
            names.append(name)
    return [f"{label} ({', '.join(names)})" for label, names in sorted(grouped.items(), key=lambda x: x[0].lower())]


def summarize(
    ieee: str,
    bindings_by_source: dict[str, list[dict]],
    coordinator: str | None,
    names: dict[str, str],
    group_names: dict[int, str],
    group_members: dict[int, set[str]] | None = None,
) -> dict[str, Any]:
    """What one device controls and what controls it.

    Returns {"count", "controls": [...], "controlled_by": [...]}, each entry
    "Name (On/Off, Level Control)". A device in a group that another device
    is bound to counts as controlled by that device ("via group …").
    """
    me = norm_ieee(ieee)
    name = lambda i: names.get(norm_ieee(i)) or norm_ieee(i)  # noqa: E731
    controls: list[tuple[str, int]] = []
    controlled: list[tuple[str, int]] = []
    count = 0
    for source, lst in bindings_by_source.items():
        for b in lst or []:
            if not is_relationship(b, coordinator):
                continue
            src = norm_ieee(source)
            if b.get("isGroup"):
                gid = b.get("groupId")
                gname = group_names.get(gid, f"group {gid}")
                if src == me:
                    controls.append((f"group {gname}", b.get("clusterId")))
                    count += 1
                elif group_members and me in group_members.get(gid, set()):
                    controlled.append((f"{name(src)} via group {gname}", b.get("clusterId")))
                    count += 1
                continue
            if src == me:
                controls.append((name(b.get("targetIeee")), b.get("clusterId")))
                count += 1
            elif norm_ieee(b.get("targetIeee")) == me:
                controlled.append((name(src), b.get("clusterId")))
                count += 1
    return {"count": count, "controls": _group_by(controls), "controlled_by": _group_by(controlled)}


def summary_text(summary: dict[str, Any]) -> str:
    """Short sensor state (max 255 chars)."""
    parts = []
    if summary["controls"]:
        parts.append("Controls " + "; ".join(summary["controls"]))
    if summary["controlled_by"]:
        parts.append("Controlled by " + "; ".join(summary["controlled_by"]))
    text = ". ".join(parts) or "No bindings"
    return text if len(text) <= 255 else text[:252] + "..."


# --- 1.3.0: noticing bindings that disappear --------------------------------

MISSES_FOR_ISSUE = 2


def relationship_map(bindings: list[dict] | None, coordinator: str | None) -> dict[str, dict]:
    """{identity_key: binding} for the bindings worth watching."""
    return {identity_key(b): b for b in bindings or [] if is_relationship(b, coordinator)}


def evaluate_check(expected: dict[str, dict], misses: dict[str, int], present: dict[str, dict]) -> tuple[dict, dict, list[dict]]:
    """One successful read of a device's binding table.

    expected: bindings it should have; misses: consecutive checks each one
    was absent; present: what the device has now. Returns (expected, misses,
    missing) where missing lists bindings absent MISSES_FOR_ISSUE checks in
    a row. A binding that's present resets its count; new bindings join
    expected (the user added them)."""
    new_misses = {k: misses.get(k, 0) + 1 for k in expected if k not in present}
    merged = {**expected, **present}
    missing = [merged[k] for k, n in sorted(new_misses.items()) if n >= MISSES_FOR_ISSUE]
    return merged, new_misses, missing


def describe_binding(b: dict, names: dict[str, str], group_names: dict[int, str]) -> str:
    if b.get("isGroup"):
        target = f"group {group_names.get(b.get('groupId'), b.get('groupId'))}"
    else:
        t = norm_ieee(b.get("targetIeee"))
        target = names.get(t) or t
    return f"{cluster_name(b.get('clusterId'))} from endpoint {b.get('sourceEndpoint')} → {target}"
