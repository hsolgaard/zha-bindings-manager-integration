"""Replace a device (1.9.0, PRD "Replace a Device").

Swapping a Zigbee device breaks its bindings both ways: remotes bound to the
old device keep sending to an address that's gone, and a replaced remote
loses everything it controlled. This plans the swap, checks the new device
can do what the old one did, copies the bindings and confirms each by
reading the table back, and cleans up afterwards.

- plan: what the old device did (from saved scans, so it works for a dead
  device too), each item checked against the new device's clusters in the
  right role (a binding *to* it needs the cluster as an input; a binding
  *from* it as an output; a group member needs the Groups cluster), with an
  endpoint mapping that can be overridden, and a verdict.
- run: binds what's ticked, then reads each device back. A device that
  doesn't answer (a battery remote) gets the binding through the Lost
  Bindings watch: it's added to that device's expected bindings as lost and
  queued, so it goes on at the device's next button press.
- cleanup: removes what still points at the old device and retires its watch
  entry, so the old bindings aren't reported as lost.
- Group membership is changed by the card through ZHA's own websocket
  (zha/group/members/add and remove), as the Groups tab does.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from homeassistant.core import HomeAssistant

from .bindings import BindsGetFailed, cluster_name, identity_key, is_relationship, norm_ieee, relationship_map

_LOGGER = logging.getLogger(__name__)

GROUPS_CLUSTER = 0x0004
MAX_PLANS = 10


# --- pure logic ------------------------------------------------------------------


def endpoints_of(clusters: list[dict] | None) -> dict[int, dict[str, set[int]]]:
    """{endpoint: {"in": {ids}, "out": {ids}}} from ZHA cluster lists
    ({endpoint_id, id, type: "in"|"out"})."""
    out: dict[int, dict[str, set[int]]] = {}
    for c in clusters or []:
        try:
            ep, cid, kind = int(c.get("endpoint_id")), int(c.get("id")), str(c.get("type"))
        except (TypeError, ValueError, AttributeError):
            continue
        if kind not in ("in", "out"):
            continue
        out.setdefault(ep, {"in": set(), "out": set()})[kind].add(cid)
    return out


def map_endpoint(eps: dict[int, dict[str, set[int]]], role: str, clusters: set[int], old_ep: int | None, override: int | None = None) -> int | None:
    """The new device's endpoint for an item: the user's choice if it fits,
    else the same number if it has the clusters in that role, else the first
    endpoint that does. None: no endpoint can do it."""
    fits = lambda ep: ep in eps and clusters <= eps[ep][role]  # noqa: E731
    if override is not None and fits(int(override)):
        return int(override)
    if old_ep is not None and fits(int(old_ep)):
        return int(old_ep)
    for ep in sorted(eps):
        if fits(ep):
            return ep
    return None


def inventory(by_source: dict[str, list[dict]], coordinator: str | None, old: str, group_members: dict[int, list[tuple[str, int]]]) -> dict[str, list]:
    """What the old device did: bindings to it, its own bindings, and the
    ZHA groups its endpoints are in."""
    old = norm_ieee(old)
    coord = norm_ieee(coordinator) if coordinator else None
    controlled_by, controls = [], []
    for source, lst in (by_source or {}).items():
        src = norm_ieee(source)
        for b in lst or []:
            if src == old:
                if is_relationship(b, coord):
                    controls.append(b)
            elif src != coord and not b.get("isGroup") and norm_ieee(b.get("targetIeee")) == old:
                controlled_by.append(b)
    groups = sorted(
        (gid, ep) for gid, members in (group_members or {}).items() for (ieee, ep) in members if norm_ieee(ieee) == old
    )
    return {"controlled_by": controlled_by, "controls": controls, "groups": groups}


def build_plan(inv: dict, old: str, new: str, old_clusters: list[dict] | None, new_clusters: list[dict] | None, endpoint_map: dict | None = None) -> dict[str, Any]:
    """Items with the check for each, and the verdict ("all" | "most" | "none").

    Each item: {id, kind: controlled_by|controls|group, binding?, group_id?,
    clusters, role, old_ep, new_ep, ok, reason}. endpoint_map overrides the
    new endpoint per old endpoint ({"2": 3})."""
    old, new = norm_ieee(old), norm_ieee(new)
    old_eps = endpoints_of(old_clusters)
    new_eps = endpoints_of(new_clusters)
    overrides = {int(k): int(v) for k, v in (endpoint_map or {}).items()}
    items: list[dict] = []

    def add(kind: str, role: str, clusters: set[int], old_ep: int | None, **extra: Any) -> None:
        new_ep = map_endpoint(new_eps, role, clusters, old_ep, overrides.get(old_ep) if old_ep is not None else None)
        if not new_eps:
            ok, reason = None, "The new device's clusters aren't known yet."
        elif new_ep is None:
            what = ", ".join(cluster_name(c) for c in sorted(clusters))
            ok = False
            reason = (
                f"The new device doesn't accept {what} commands."
                if role == "in"
                else f"The new device doesn't send {what} commands."
            )
        else:
            ok, reason = True, ""
        items.append({"id": f"i{len(items)}", "kind": kind, "role": role, "clusters": sorted(clusters), "old_ep": old_ep, "new_ep": new_ep, "ok": ok, "reason": reason, **extra})

    for b in inv["controlled_by"]:
        add("controlled_by", "in", {int(b["clusterId"])}, _int(b.get("targetEndpoint")), binding=b)
    for b in inv["controls"]:
        cid, ep = int(b["clusterId"]), _int(b.get("sourceEndpoint"))
        # Reporting bindings (a light telling a group its state) are on a
        # cluster the device *receives*; everything else it sends.
        role = "in" if ep in old_eps and cid in old_eps[ep]["in"] and cid not in old_eps[ep]["out"] else "out"
        add("controls", role, {cid}, ep, binding=b)
    for gid, ep in inv["groups"]:
        clusters = {GROUPS_CLUSTER} | ({c for c in old_eps.get(ep, {}).get("in", set()) if c in (0x0006, 0x0008, 0x0300, 0x0102)})
        add("group", "in", clusters, ep, group_id=gid)

    known = [i for i in items if i["ok"] is not None]
    if not items:
        verdict = "nothing"
    elif not known:
        verdict = "unknown"
    elif all(i["ok"] for i in known):
        verdict = "all"
    elif any(i["ok"] for i in known):
        verdict = "most"
    else:
        verdict = "none"
    return {"old": old, "new": new, "items": items, "verdict": verdict, "new_endpoints": sorted(new_eps), "old_endpoints": sorted(old_eps)}


def new_binding(item: dict, old: str, new: str) -> tuple[str, dict]:
    """(device to bind on, binding) for a planned item."""
    b = dict(item["binding"])
    if item["kind"] == "controlled_by":
        b["targetIeee"], b["targetEndpoint"] = new, item["new_ep"]
        return norm_ieee(b["sourceIeee"]), b
    b["sourceIeee"], b["sourceEndpoint"] = new, item["new_ep"]
    return new, b


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --- running it --------------------------------------------------------------------


class Replacer:
    def __init__(self, hass: HomeAssistant, data: Any) -> None:
        self.hass = hass
        self.data = data
        self.plans: dict[str, dict] = {}

    def group_members(self) -> dict[int, list[tuple[str, int]]]:
        out: dict[int, list[tuple[str, int]]] = {}
        gw = self.data._gateway()  # noqa: SLF001 - shared helper
        try:
            for gid, group in (getattr(gw, "groups", None) or {}).items():
                out[int(gid)] = [
                    (norm_ieee(str(getattr(getattr(m, "device", None), "ieee", ""))), int(getattr(m, "endpoint_id", 1) or 1))
                    for m in (getattr(group, "members", None) or [])
                ]
        except Exception:  # noqa: BLE001 - internal ZHA API, optional
            pass
        return out

    def zha_clusters(self, ieee: str) -> list[dict] | None:
        """Clusters from ZHA's gateway, for callers that don't pass them
        (Lighting Manager). Internal API: None if it can't be read."""
        gw = self.data._gateway()  # noqa: SLF001
        try:
            for dev in (getattr(gw, "devices", None) or {}).values():
                if norm_ieee(str(dev.ieee)) != norm_ieee(ieee):
                    continue
                out = []
                for ep_id, ep in (getattr(dev, "endpoints", None) or {}).items():
                    zep = getattr(ep, "zigpy_endpoint", ep)
                    for kind, attr in (("in", "in_clusters"), ("out", "out_clusters")):
                        for cid in (getattr(zep, attr, None) or {}):
                            out.append({"endpoint_id": int(ep_id), "id": int(cid), "type": kind})
                return out or None
        except Exception:  # noqa: BLE001
            return None
        return None

    def plan(self, old: str, new: str, old_clusters=None, new_clusters=None, endpoint_map=None) -> dict[str, Any]:
        old, new = norm_ieee(old), norm_ieee(new)
        if old == new:
            return {"error": "same_device"}
        if new == norm_ieee(self.data.coordinator or ""):
            return {"error": "coordinator"}
        inv = inventory(self.data.by_source, self.data.coordinator, old, self.group_members())
        plan = build_plan(
            inv,
            old,
            new,
            old_clusters if old_clusters is not None else self.zha_clusters(old),
            new_clusters if new_clusters is not None else self.zha_clusters(new),
            endpoint_map,
        )
        names = self.data.names()
        group_names, _ = self.data.groups()
        for item in plan["items"]:
            item["text"] = self._describe(item, names, group_names)
        plan["old_in_zha"] = self.data.zha_device(old) is not None
        plan["plan_id"] = uuid.uuid4().hex[:12]
        self.plans[plan["plan_id"]] = plan
        while len(self.plans) > MAX_PLANS:
            self.plans.pop(next(iter(self.plans)))
        return plan

    def _describe(self, item: dict, names: dict[str, str], group_names: dict[int, str]) -> str:
        cl = ", ".join(cluster_name(c) for c in item["clusters"] if c != GROUPS_CLUSTER) or "Groups"
        if item["kind"] == "group":
            return f"Member of {group_names.get(item['group_id'], 'group ' + str(item['group_id']))} (endpoint {item['old_ep']})"
        b = item["binding"]
        if item["kind"] == "controlled_by":
            src = norm_ieee(b["sourceIeee"])
            return f"{names.get(src, src)} (ep {b.get('sourceEndpoint')}) → this device ep {item['old_ep']}: {cl}"
        target = group_names.get(b.get("groupId"), f"group {b.get('groupId')}") if b.get("isGroup") else names.get(norm_ieee(b.get("targetIeee")), b.get("targetIeee"))
        return f"This device ep {item['old_ep']} → {target}: {cl}"

    async def _bind(self, on_ieee: str, b: dict) -> None:
        try:
            if b.get("isGroup"):
                data = {"ieee": on_ieee, "command_data": b.get("groupId"), "cluster": b.get("clusterId"), "endpoint": b.get("sourceEndpoint")}
                await self.hass.services.async_call("zha_toolkit", "bind_group", data, blocking=True, return_response=True)
            else:
                data = {
                    "ieee": on_ieee,
                    "command_data": b.get("targetIeee"),
                    "cluster": b.get("clusterId"),
                    "endpoint": b.get("sourceEndpoint"),
                    "dst_endpoint": b.get("targetEndpoint"),
                }
                await self.hass.services.async_call("zha_toolkit", "bind_ieee", data, blocking=True, return_response=True)
        except Exception as err:  # noqa: BLE001 - the read-back decides
            _LOGGER.debug("Bind on %s raised: %s", on_ieee, err)

    async def run(self, plan_id: str, item_ids: list[str]) -> dict[str, Any]:
        """Binds the chosen binding items (groups are the card's job) and
        reads each device back. {"results": {item id: confirmed|rejected|waiting}}."""
        plan = self.plans.get(plan_id)
        if plan is None:
            return {"error": "unknown_plan"}
        chosen = [i for i in plan["items"] if i["id"] in set(item_ids) and i["kind"] != "group" and i["new_ep"] is not None]
        by_device: dict[str, list[tuple[dict, dict]]] = {}
        for item in chosen:
            on, b = new_binding(item, plan["old"], plan["new"])
            by_device.setdefault(on, []).append((item, b))
        results: dict[str, str] = {}
        from .watch import get_watch

        watch = get_watch(self.hass)
        for on, pairs in by_device.items():
            for _item, b in pairs:
                await self._bind(on, b)
            try:
                await self.data.async_rescan(on)
            except BindsGetFailed:
                for item, b in pairs:
                    results[item["id"]] = "waiting"
                if watch is not None:
                    watch.expect_and_queue(on, [b for _i, b in pairs])
                continue
            present = relationship_map((self.data.scans.get(on) or {}).get("bindings"), self.data.coordinator)
            for item, b in pairs:
                results[item["id"]] = "confirmed" if identity_key(b) in present else "rejected"
            if watch is not None:
                watch.adopt(on)
        plan["results"] = {**plan.get("results", {}), **results}
        return {"results": results}

    async def cleanup(self, plan_id: str, unbind_old: bool = True) -> dict[str, Any]:
        """Removes bindings that still point at the old device (on each
        source), and retires the old device's watch entry."""
        plan = self.plans.get(plan_id)
        if plan is None:
            return {"error": "unknown_plan"}
        old = plan["old"]
        done, failed = [], []
        from .watch import get_watch

        watch = get_watch(self.hass)
        if unbind_old:
            sources = sorted({norm_ieee(i["binding"]["sourceIeee"]) for i in plan["items"] if i["kind"] == "controlled_by"})
            for src in sources:
                try:
                    await self.hass.services.async_call(
                        "zha_toolkit", "binds_remove_all", {"ieee": src, "command_data": old}, blocking=True, return_response=True
                    )
                    done.append(src)
                except Exception as err:  # noqa: BLE001 - reported per device
                    _LOGGER.debug("Unbinding %s from %s failed: %s", src, old, err)
                    failed.append(src)
                if watch is not None:
                    watch.removed_by_user([{"sourceIeee": src, "targetIeee": old}])
        if watch is not None:
            watch.retire(old)
        return {"unbound": done, "failed": failed}
