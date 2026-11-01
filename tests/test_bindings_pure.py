"""Pure helpers behind the device-page entities (bindings.py)."""
import pytest

from custom_components.zha_bindings_manager.bindings import (
    BindsGetFailed,
    devices_with_bindings,
    guess_coordinator,
    parse_binds_get,
    summarize,
    summary_text,
)

R = "aa:aa:aa:aa:aa:aa:aa:01"  # remote
L = "bb:bb:bb:bb:bb:bb:bb:02"  # light
P = "cc:cc:cc:cc:cc:cc:cc:03"  # plug
C = "00:12:4b:00:00:00:00:01"  # coordinator


def b(src, cid, target=None, ep=1, group=None):
    return {
        "sourceIeee": src, "sourceEndpoint": 1, "clusterId": cid, "isGroup": group is not None,
        "targetIeee": None if group is not None else target, "targetEndpoint": None if group is not None else ep,
        "groupId": group,
    }


def test_parse_result_and_replies_shapes_and_dedup():
    response = {
        "success": True,
        "result": {"0": {"src_ep": 1, "cluster_id": "0x0006", "dst": {"addrmode": 3, "dst_ieee": L, "dst_ep": 1}}},
        # same binding again in the ZDO page shape (IEEE as little-endian bytes), plus a group binding
        "replies": [[0, 2, 0, [
            {"SrcEndpoint": 1, "ClusterId": 6, "DstAddress": {"addrmode": 3, "ieee": [2, 0xbb, 0xbb, 0xbb, 0xbb, 0xbb, 0xbb, 0xbb], "endpoint": 1}},
            {"SrcEndpoint": 1, "ClusterId": 8, "DstAddress": {"addrmode": 1, "nwk": [3, 0]}},
        ]]],
    }
    bindings, partial = parse_binds_get(R, response)
    assert partial is False
    assert [(x["clusterId"], x["isGroup"], x["targetIeee"], x["groupId"]) for x in bindings] == [
        (6, False, L, None),
        (8, True, None, 3),
    ]


def test_parse_failure_with_nothing_raises_and_partial_keeps_data():
    with pytest.raises(BindsGetFailed):
        parse_binds_get(R, {"success": False, "errors": ["Timeout"]})
    bindings, partial = parse_binds_get(
        R, {"success": False, "result": {"0": {"src_ep": 1, "cluster_id": "0x0006", "dst": {"addrmode": 3, "dst_ieee": L, "dst_ep": 1}}}}
    )
    assert partial is True and len(bindings) == 1


def test_guess_coordinator_needs_a_clear_majority():
    data = {R: [b(R, 0x20, C), b(R, 6, L)], L: [b(L, 6, C)], P: [b(P, 6, C)]}
    assert guess_coordinator(data) == C
    assert guess_coordinator({R: [b(R, 6, C)]}) is None


def test_only_devices_with_real_relationships_are_exposed():
    data = {R: [b(R, 0x20, C), b(R, 6, L), b(R, 8, group=3)], L: [b(L, 6, C)], P: [b(P, 6, C)]}
    assert devices_with_bindings(data, C) == {R, L}


def test_summary_both_directions_groups_and_coordinator_left_out():
    data = {R: [b(R, 0x20, C), b(R, 6, L), b(R, 8, L), b(R, 6, group=3)]}
    names = {R: "Rodret", L: "Spots", P: "Lamp"}
    s = summarize(R, data, C, names, {3: "Lounge"}, {3: {P}})
    assert s["controls"] == ["group Lounge (On/Off)", "Spots (On/Off, Level Control)"]
    assert s["controlled_by"] == []
    assert s["count"] == 3
    assert summarize(L, data, C, names, {3: "Lounge"}, {3: {P}})["controlled_by"] == ["Rodret (On/Off, Level Control)"]
    lamp = summarize(P, data, C, names, {3: "Lounge"}, {3: {P}})
    assert lamp["controlled_by"] == ["Rodret via group Lounge (On/Off)"]
    assert summary_text(lamp) == "Controlled by Rodret via group Lounge (On/Off)"


def test_summary_text_is_capped_for_the_sensor_state():
    s = {"controls": [f"Light {i} (On/Off, Level Control)" for i in range(30)], "controlled_by": []}
    assert len(summary_text(s)) == 255
