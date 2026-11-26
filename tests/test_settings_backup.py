"""Device configuration backup (1.12.0) and firmware update servers."""
from types import SimpleNamespace
from unittest import mock

import pytest
import zigpy.types as t
from homeassistant.core import HomeAssistant
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import Identify, LevelControl, OnOff

from custom_components.zha_bindings_manager import ota_api
from custom_components.zha_bindings_manager.const import DOMAIN
from custom_components.zha_bindings_manager.settings_backup import (
    KEEP,
    SettingsBackup,
    get_settings,
    settings_attributes,
    to_json,
)

from .test_websocket import _client

SW = "44:9f:da:ff:fe:a4:a7:6d"
NEW = "44:9f:da:ff:fe:a2:f6:4a"
COORD = "44:9f:da:ff:fe:77:0b:94"


class FakeCluster:
    """Enough of a zigpy cluster: real attribute definitions, values in a dict."""

    def __init__(self, cls, values, refuse=(), sticky=True, answers=True):
        self.cluster_id = cls.cluster_id
        self.ep_attribute = cls.ep_attribute
        self.name = cls.name
        self.attributes = cls.attributes
        self.unsupported_attributes = set()
        self.values = dict(values)
        self.refuse = set(refuse)
        self.sticky = sticky
        self.answers = answers
        self.writes = []

    async def read_attributes(self, names, allow_cache=False, **kw):
        if not self.answers:
            raise TimeoutError
        return ({n: self.values[n] for n in names if n in self.values}, {})

    async def write_attributes(self, attrs, **kw):
        self.writes.append(dict(attrs))
        name, value = next(iter(attrs.items()))
        if name in self.refuse:
            return [[foundation.WriteAttributesStatusRecord(foundation.Status.READ_ONLY, 0)]]
        if self.sticky:
            self.values[name] = value
        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]


def _device(ieee, model, endpoints, mains=True):
    eps = {0: SimpleNamespace(in_clusters={}, out_clusters={})}
    for ep_id, clusters in endpoints.items():
        eps[ep_id] = SimpleNamespace(in_clusters={c.cluster_id: c for c in clusters}, out_clusters={})
    return SimpleNamespace(
        ieee=t.EUI64.convert(ieee),
        nwk=0x1234,
        model=model,
        manufacturer="SONOFF",
        endpoints=eps,
        node_desc=SimpleNamespace(is_mains_powered=mains),
    )


def _app(*devices):
    by = {str(d.ieee): d for d in devices}
    app = mock.Mock()

    def get_device(ieee=None, nwk=None):
        return by[str(ieee)]

    app.get_device.side_effect = get_device
    app.devices = {d.ieee: d for d in devices}
    app.state.node_info.ieee = t.EUI64.convert(COORD)
    return app


def _data():
    return SimpleNamespace(
        coordinator=COORD,
        scans={},
        by_source={},
        card={},
        group_memberships=lambda ieee: [{"group_id": 5, "endpoint_id": 1, "name": "Lounge"}],
    )


def test_only_writable_settings_are_backed_up():
    names = [a.name for a in settings_attributes(FakeCluster(OnOff, {}))]
    assert names == ["start_up_on_off"]  # on_time/off_wait_time are timers, on_off is read-only
    level = [a.name for a in settings_attributes(FakeCluster(LevelControl, {}))]
    assert "on_level" in level and "options" in level and "current_level" not in level
    assert settings_attributes(FakeCluster(Identify, {})) == []  # identify_time is a countdown


def test_values_are_stored_as_plain_json_with_enum_names():
    assert to_json(OnOff.StartUpOnOff.Toggle) == (2, "Toggle")
    assert to_json(t.uint8_t(40)) == (40, None)
    assert to_json(True) == (True, None)
    assert to_json("Hall") == ("Hall", None)


async def test_snapshot_plan_and_apply_on_a_re_paired_switch(hass: HomeAssistant):
    onoff = FakeCluster(OnOff, {"start_up_on_off": OnOff.StartUpOnOff.Off})
    level = FakeCluster(LevelControl, {"on_level": t.uint8_t(40), "on_transition_time": t.uint16_t(5)})
    sw = _device(SW, "ZBM5-3C-80/86", {1: [onoff, level]})
    backup = SettingsBackup(hass, _data())
    backup.app_getter = lambda _h: _app(sw)

    snap = await backup.async_snapshot(SW)
    attrs = snap["endpoints"]["1"]["0x0006"]["attributes"]
    assert attrs["0x4003"] == {"name": "start_up_on_off", "value": 0, "label": "Off"}
    assert snap["endpoints"]["1"]["0x0008"]["attributes"]["0x0011"]["value"] == 40
    assert snap["groups"] == [{"group_id": 5, "endpoint_id": 1, "name": "Lounge"}]
    assert snap["model"] == "ZBM5-3C-80/86"

    # Factory reset: everything back to defaults.
    onoff.values["start_up_on_off"] = OnOff.StartUpOnOff.On
    level.values["on_level"] = t.uint8_t(255)
    plan = await backup.async_plan(backup.find(SW), SW)
    by = {r["name"]: r for r in plan["rows"]}
    assert by["start_up_on_off"]["state"] == "differs" and by["start_up_on_off"]["current_label"] == "On"
    assert by["on_level"]["state"] == "differs"
    assert by["on_transition_time"]["state"] == "same"
    assert plan["same_model"] is True

    items = [{"endpoint": r["endpoint"], "cluster": r["cluster"], "attribute": r["attribute"], "value": r["saved"]} for r in plan["rows"] if r["state"] == "differs"]
    res = await backup.async_apply(SW, items)
    assert res["restored"] == 2 and res["total"] == 2
    assert onoff.values["start_up_on_off"] == OnOff.StartUpOnOff.Off and level.values["on_level"] == 40


async def test_refused_and_not_sticking_are_reported(hass: HomeAssistant):
    onoff = FakeCluster(OnOff, {"start_up_on_off": OnOff.StartUpOnOff.On}, refuse={"start_up_on_off"})
    level = FakeCluster(LevelControl, {"on_level": t.uint8_t(255)}, sticky=False)
    sw = _device(SW, "ZBM5-3C-80/86", {1: [onoff, level]})
    backup = SettingsBackup(hass, _data())
    backup.app_getter = lambda _h: _app(sw)
    res = await backup.async_apply(
        SW,
        [
            {"endpoint": 1, "cluster": 6, "attribute": 0x4003, "value": 0},
            {"endpoint": 1, "cluster": 8, "attribute": 0x0011, "value": 40},
            {"endpoint": 2, "cluster": 6, "attribute": 0x4003, "value": 0},
        ],
    )
    got = {(r["endpoint"], r["cluster"]): r for r in res["results"]}
    assert got[(1, 6)]["result"] == "refused" and got[(1, 6)]["status"] == "READ_ONLY"
    assert got[(1, 8)]["result"] == "didnt_stick" and got[(1, 8)]["now"] == 255
    assert got[(2, 6)]["result"] == "not_on_device"
    assert res["restored"] == 0


async def test_apply_to_another_model_offers_only_what_it_has(hass: HomeAssistant):
    old = _device(SW, "ZBM5-3C-80/86", {1: [FakeCluster(OnOff, {"start_up_on_off": OnOff.StartUpOnOff.Off})], 3: [FakeCluster(OnOff, {"start_up_on_off": OnOff.StartUpOnOff.Off})]})
    new = _device(NEW, "ZBM5-1C-80/86", {1: [FakeCluster(OnOff, {"start_up_on_off": OnOff.StartUpOnOff.On})]})
    backup = SettingsBackup(hass, _data())
    backup.app_getter = lambda _h: _app(old, new)
    await backup.async_snapshot(SW)
    plan = await backup.async_plan(backup.find(SW), NEW)
    assert plan["same_model"] is False
    states = sorted((r["endpoint"], r["state"]) for r in plan["rows"])
    assert states == [(1, "differs"), (3, "not_on_device")]
    # The old endpoint 3 can be mapped onto the new switch's endpoint 1.
    plan = await backup.async_plan(backup.find(SW), NEW, {"3": 1})
    assert [r["endpoint"] for r in plan["rows"]] == [1, 1]


async def test_a_sleeping_device_is_reported_not_saved(hass: HomeAssistant):
    sw = _device(SW, "SNZB", {1: [FakeCluster(OnOff, {"start_up_on_off": 0}, answers=False)]}, mains=False)
    backup = SettingsBackup(hass, _data())
    backup.app_getter = lambda _h: _app(sw)
    assert (await backup.async_snapshot(SW)) == {"error": "no_answer"}
    assert backup.get(SW) == {"snapshots": [], "after_reset": None}


async def test_keeps_five_and_the_after_reset_read_separately(hass: HomeAssistant):
    onoff = FakeCluster(OnOff, {"start_up_on_off": OnOff.StartUpOnOff.Off})
    sw = _device(SW, "ZBM5-3C-80/86", {1: [onoff]})
    backup = SettingsBackup(hass, _data())
    backup.app_getter = lambda _h: _app(sw)
    ids = []
    for _ in range(KEEP + 2):
        snap = await backup.async_snapshot(SW)
        ids.append(snap["id"])
    after = await backup.async_snapshot(SW, "after_reset")
    saved = backup.get(SW)
    assert len(saved["snapshots"]) == KEEP and saved["after_reset"]["id"] == after["id"]
    assert backup.find(SW, "after_reset")["reason"] == "after_reset"
    # "before": the newest backup taken before the device was removed.
    assert backup.find(SW, before=saved["snapshots"][1]["taken_at"])["id"] == saved["snapshots"][2]["id"]


async def test_auto_backup_only_for_mains_devices_not_backed_up_lately(hass: HomeAssistant):
    sw = _device(SW, "ZBM5-3C-80/86", {1: [FakeCluster(OnOff, {"start_up_on_off": 0})]})
    remote = _device(NEW, "SNZB-01M", {1: [FakeCluster(OnOff, {"start_up_on_off": 0})]}, mains=False)
    backup = SettingsBackup(hass, _data())
    backup.app_getter = lambda _h: _app(sw, remote)
    assert backup.is_due(SW) is True and backup.is_due(NEW) is False and backup.is_due(COORD) is False
    await backup.async_snapshot(SW, "auto")
    assert backup.is_due(SW) is False


async def test_websocket_backup_plan_apply_and_import(hass: HomeAssistant, hass_ws_client):
    client = await _client(hass, hass_ws_client)
    onoff = FakeCluster(OnOff, {"start_up_on_off": OnOff.StartUpOnOff.Off})
    sw = _device(SW, "ZBM5-3C-80/86", {1: [onoff]})
    settings = get_settings(hass)
    settings.app_getter = lambda _h: _app(sw)
    await client.send_json({"id": 20, "type": f"{DOMAIN}/settings_backup", "ieee": SW})
    snap = (await client.receive_json())["result"]
    assert snap["endpoints"]["1"]["0x0006"]["attributes"]["0x4003"]["label"] == "Off"
    onoff.values["start_up_on_off"] = OnOff.StartUpOnOff.On
    await client.send_json({"id": 21, "type": f"{DOMAIN}/settings_plan", "source_ieee": SW, "target_ieee": SW})
    plan = (await client.receive_json())["result"]
    assert [r["state"] for r in plan["rows"]] == ["differs"]
    await client.send_json({"id": 22, "type": f"{DOMAIN}/settings_apply", "target_ieee": SW, "items": [{"endpoint": 1, "cluster": 6, "attribute": 0x4003, "value": 0}]})
    assert (await client.receive_json())["result"]["restored"] == 1
    await client.send_json({"id": 23, "type": f"{DOMAIN}/settings_import", "ieee": NEW, "snapshot": snap})
    assert (await client.receive_json())["result"]["reason"] == "import"
    await client.send_json({"id": 24, "type": f"{DOMAIN}/settings_get", "ieee": NEW})
    assert len((await client.receive_json())["result"]["snapshots"]) == 1
    await client.send_json({"id": 25, "type": f"{DOMAIN}/settings_plan", "source_ieee": SW, "snapshot_id": "nope", "target_ieee": SW})
    msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "not_found"


# --- firmware update servers -------------------------------------------------------


def _ota_device(ieee, server=None, claims=False):
    ota_client = mock.Mock()
    ota_client.read_attributes = mock.AsyncMock(return_value=({"upgrade_server_id": t.EUI64.convert(server)}, {}) if server else TimeoutError())
    if server is None:
        ota_client.read_attributes.side_effect = TimeoutError
    eps = {
        0: SimpleNamespace(in_clusters={}, out_clusters={}),
        1: SimpleNamespace(in_clusters={6: object()}, out_clusters={0x0019: ota_client}),
    }
    if claims:
        eps[3] = SimpleNamespace(in_clusters={0x0019: object()}, out_clusters={})
    return SimpleNamespace(ieee=t.EUI64.convert(ieee), nwk=0x1111, endpoints=eps)


def test_devices_claiming_to_be_an_update_server():
    coord = SimpleNamespace(ieee=t.EUI64.convert(COORD), nwk=0, endpoints={1: SimpleNamespace(in_clusters={0x0019: object()}, out_clusters={})})
    app = _app(_ota_device(SW, claims=True), _ota_device(NEW))
    app.devices[coord.ieee] = coord
    assert ota_api.claimants(app) == [{"ieee": SW, "endpoints": [3]}]


@pytest.mark.parametrize(
    ("server", "expected"),
    [
        (COORD, {"status": "ok", "server": COORD, "is_coordinator": True, "not_set": False, "coordinator": COORD}),
        (SW, {"status": "ok", "server": SW, "is_coordinator": False, "not_set": False, "coordinator": COORD}),
        ("ff:ff:ff:ff:ff:ff:ff:ff", {"status": "ok", "server": "ff:ff:ff:ff:ff:ff:ff:ff", "is_coordinator": False, "not_set": True, "coordinator": COORD}),
    ],
)
async def test_reads_where_a_device_gets_its_updates(server, expected):
    app = _app(_ota_device(NEW, server))
    assert await ota_api.read_update_server(app, NEW) == expected


async def test_update_server_of_a_sleeping_device():
    app = _app(_ota_device(NEW, None))
    assert (await ota_api.read_update_server(app, NEW))["status"] == "no_answer"


async def test_ota_websocket(hass: HomeAssistant, hass_ws_client):
    client = await _client(hass, hass_ws_client)
    app = _app(_ota_device(SW, claims=True), _ota_device(NEW, SW))
    with mock.patch.object(ota_api, "_app", return_value=app):
        await client.send_json({"id": 30, "type": f"{DOMAIN}/ota_claimants"})
        res = (await client.receive_json())["result"]
        await client.send_json({"id": 31, "type": f"{DOMAIN}/ota_server", "ieee": NEW})
        server = (await client.receive_json())["result"]
    assert res["claimants"] == [{"ieee": SW, "endpoints": [3]}] and res["coordinator"] == COORD
    assert server["server"] == SW and server["is_coordinator"] is False
