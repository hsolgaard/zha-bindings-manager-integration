"""Finds saved bindings that point at a device that has just been removed.

Pure functions over the card's stored state, with no Home Assistant
imports, so verify_removal_notice.py can test them directly.

The card saves one state blob per card instance (see websocket_api.py):
    {card_id: {"updated_at": ..., "state": {"scanState": {"last_complete":
        {"bindings": {source_ieee: [binding, ...]}}}}}}
Each binding has at least sourceIeee, targetIeee and isGroup. This is the
card's most recent scan, so it only knows about bindings that existed when
each source device was last scanned.
"""
from __future__ import annotations

from typing import Any


def norm_ieee(ieee: Any) -> str:
    return str(ieee or "").strip().lower()


def _saved_bindings(entry: Any) -> dict[str, list]:
    state = (entry or {}).get("state") if isinstance(entry, dict) else None
    scan = (state or {}).get("scanState") or {}
    last = scan.get("last_complete") or {}
    bindings = last.get("bindings") or {}
    return bindings if isinstance(bindings, dict) else {}


def bindings_to_removed_target(
    store_data: dict[str, Any], removed_ieee: str, live_ieees: set[str] | None = None
) -> dict[str, int]:
    """Live-source bindings whose target is the removed device.

    live_ieees, when given, is every ZHA device still present: saved data
    from sources removed earlier is skipped, since there's nothing left to
    unbind on them.

    Returns {source_ieee: binding_count}, merged across every card instance
    (two dashboards with the card would otherwise double count, so each
    binding is counted once by its identity). Bindings held by the removed
    device itself are ignored: they went with the device, and the card
    clears its saved copy of them.
    """
    removed = norm_ieee(removed_ieee)
    seen: set[tuple] = set()
    counts: dict[str, int] = {}
    for entry in (store_data or {}).values():
        for source, items in _saved_bindings(entry).items():
            src = norm_ieee(source)
            if src == removed or (live_ieees is not None and src not in live_ieees):
                continue
            for b in items or []:
                if not isinstance(b, dict) or b.get("isGroup"):
                    continue
                if norm_ieee(b.get("targetIeee")) != removed:
                    continue
                key = (src, b.get("sourceEndpoint"), b.get("clusterId"), b.get("targetEndpoint"))
                if key in seen:
                    continue
                seen.add(key)
                counts[src] = counts.get(src, 0) + 1
    return counts


def notification_id(domain: str, ieee: str) -> str:
    return f"{domain}_removed_{norm_ieee(ieee).replace(':', '')}"


def removal_message(device_name: str, ieee: str, sources: dict[str, int], names: dict[str, str]) -> str:
    """Markdown body for the persistent notification."""
    total = sum(sources.values())
    source_list = ", ".join(
        f"{names.get(src) or src} ({n})" for src, n in sorted(sources.items(), key=lambda kv: names.get(kv[0]) or kv[0])
    )
    return (
        f"**{device_name}** (`{norm_ieee(ieee)}`) was removed from ZHA, but "
        f"{total} binding{'s' if total != 1 else ''} on {len(sources)} "
        f"device{'s' if len(sources) != 1 else ''} still point{'s' if total == 1 else ''} to it: {source_list}.\n\n"
        "These bindings use slots in each device's binding table and send commands to nobody.\n\n"
        "- **Pairing it again?** Ignore this. Once it's back with the same address the bindings work again, "
        "and this notice is dismissed automatically.\n"
        "- **Gone for good?** Open ZHA Bindings Manager (the **ZHA Bindings** page in the sidebar), go to the "
        "Bindings tab and click **Unbind all** in the banner above the table.\n\n"
        "_Based on the card's last scan of those devices._"
    )
