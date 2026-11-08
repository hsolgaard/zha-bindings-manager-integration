"""Experimental: messages per device to Home Assistant (1.7.0)."""
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zha_bindings_manager import activity as act
from custom_components.zha_bindings_manager.activity import MAX_CLUSTERS, MAX_DEVICES, ActivityCounter
from custom_components.zha_bindings_manager.const import DOMAIN, OPT_EXPERIMENTAL, TITLE

A = "aa:aa:aa:aa:aa:aa:aa:01"
COORD = "cc:cc:cc:cc:cc:cc:cc:00"
T0 = 1_800_000_000.0  # a fixed point in time, on a minute boundary


class FakeApp:
    def __init__(self):
        self.listeners = []
        counter = SimpleNamespace(name="tx_failed", value=3)
        group = SimpleNamespace(name="ezsp_counters", counters=lambda: [counter], groups=lambda: [])
        self.state = SimpleNamespace(node_info=SimpleNamespace(ieee=COORD.upper()), counters={"ezsp_counters": group})

    def add_listener(self, listener):
        self.listeners.append(listener)

    def remove_listener(self, listener):
        self.listeners.remove(listener)


def test_counts_per_minute_and_cluster(hass: HomeAssistant):
    c = ActivityCounter(hass)
    for i in range(30):
        c.count(A.upper(), 0x1234, 0x0006, now=T0 + i)  # 30 in minute 0
    c.count(A, 0x1234, 0x0702, now=T0 + 60)  # 1 in minute 1
    snap = c.snapshot(now=T0 + 61)
    d = snap["by_device"][A]
    assert d["nwk"] == 0x1234
    assert len(d["per_minute"]) == 60 and d["per_minute"][-2:] == [30, 1] and sum(d["per_minute"]) == 31
    assert list(d["clusters"].items()) == [("0x0006", 30), ("0x0702", 1)]


def test_window_drops_old_minutes_and_quiet_devices(hass: HomeAssistant):
    c = ActivityCounter(hass)
    c.count(A, 1, 6, now=T0)
    assert c.snapshot(now=T0 + 61 * 60)["by_device"] == {}  # older than the hour
    for m in range(80):
        c.count(A, 1, 6, now=T0 + m * 60)
    assert len(c.by_device[A]["minutes"]) <= 65  # pruned as it goes


def test_limits_devices_and_clusters(hass: HomeAssistant):
    c = ActivityCounter(hass)
    for cid in range(MAX_CLUSTERS + 5):
        c.count(A, 1, cid, now=T0)
    assert len(c.by_device[A]["clusters"]) == MAX_CLUSTERS
    with patch.object(act, "MAX_DEVICES", 2):
        c2 = ActivityCounter(hass)
        for i in range(4):
            c2.count(f"aa:aa:aa:aa:aa:aa:aa:0{i}", 1, 6, now=T0)
        assert len(c2.by_device) == 2 and c2.dropped_devices == 2
    assert MAX_DEVICES == 1024


def test_handle_message_never_raises(hass: HomeAssistant):
    c = ActivityCounter(hass)
    c.handle_message(object(), 260, 6, 1, 1, b"")  # no ieee attribute
    c.handle_message(SimpleNamespace(ieee=A, nwk=5), 260, 6, 1, 1, b"\x00")
    assert sum(c.by_device[A]["minutes"].values()) == 1


def test_attaches_reattaches_and_reads_coordinator(hass: HomeAssistant):
    c = ActivityCounter(hass)
    app1, app2 = FakeApp(), FakeApp()
    with patch.object(ActivityCounter, "_current_app", return_value=app1):
        stop = c.async_start()
    assert app1.listeners == [c]
    snap = c.snapshot()
    assert snap["coordinator_ieee"] == COORD and snap["attached"] is True
    assert snap["coordinator_counters"] == [{"name": "ezsp_counters.tx_failed", "value": 3}]
    with patch.object(ActivityCounter, "_current_app", return_value=app2):
        c.attach()  # ZHA reloaded: a new controller object
    assert app1.listeners == [] and app2.listeners == [c]
    stop()
    assert app2.listeners == [] and c.snapshot()["attached"] is False


async def _setup(hass, hass_ws_client, options):
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, await hass_ws_client(hass)


async def test_activity_get_needs_the_experimental_switch(hass: HomeAssistant, hass_ws_client):
    _entry, client = await _setup(hass, hass_ws_client, {})
    assert "activity" not in hass.data[DOMAIN]
    await client.send_json({"id": 1, "type": f"{DOMAIN}/activity_get"})
    msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "not_enabled"


async def test_activity_get_returns_counts(hass: HomeAssistant, hass_ws_client):
    entry, client = await _setup(hass, hass_ws_client, {OPT_EXPERIMENTAL: True})
    counter = hass.data[DOMAIN]["activity"]
    counter.count(A, 0x10, 6)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/activity_get"})
    msg = await client.receive_json()
    assert msg["success"] is True
    assert sum(msg["result"]["by_device"][A]["per_minute"]) == 1
    assert msg["result"]["window_minutes"] == 60
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "activity" not in hass.data[DOMAIN]
