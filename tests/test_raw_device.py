"""raw_device_info: identity, signature and firmware read from the device,
not from ZHA's quirked view. zigpy's radio side is faked; the parsing,
endpoint choice, status reporting and websocket wiring are real."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zigpy.zcl.clusters.general import Basic, Ota

from custom_components.zha_bindings_manager import raw_device
from custom_components.zha_bindings_manager.const import DOMAIN

IEEE = "00:11:22:33:44:55:66:77"


def _rec(attrid, status=0, value=None):
    return SimpleNamespace(attrid=attrid, status=status, value=SimpleNamespace(value=value))


def _desc(ep, profile, device_type, ins, outs):
    return SimpleNamespace(endpoint=ep, profile=profile, device_type=device_type, input_clusters=ins, output_clusters=outs)


class QuirkedDevice:
    """Stands in for a quirked zigpy device: zigpy's endpoint 1 claims a
    MultistateInput cluster (0x0012) the real device doesn't have."""

    def __init__(self, active=(1, 242)):
        self.nwk = 0x1234
        ep1 = SimpleNamespace(in_clusters={0x0000: None, 0x0006: None, 0x0012: None}, out_clusters={0x0019: None})
        self.endpoints = {0: object(), 1: ep1, 242: SimpleNamespace(in_clusters={}, out_clusters={0x0021: None})}
        descs = {
            1: _desc(1, 0x0104, 0x0100, [0x0000, 0x0006, 0xE001], [0x0019]),
            242: _desc(242, 0xA1E0, 0x0061, [], [0x0021]),
        }
        self.zdo = SimpleNamespace(
            Active_EP_req=AsyncMock(return_value=(0, self.nwk, list(active))),
            Simple_Desc_req=AsyncMock(side_effect=lambda nwk, ep: (0, nwk, descs[ep])),
        )
        self.node_desc = SimpleNamespace(
            logical_type=SimpleNamespace(name="Router"),
            is_mains_powered=True,
            is_receiver_on_when_idle=True,
            manufacturer_code=0x1141,
        )


def _basic_reply(ids):
    values = {0x0004: "_TZ3000_abcdefgh", 0x0005: "TS0001", 0x0001: 70, 0x0003: 1, 0x0006: ""}
    return [[_rec(i, value=values[i]) if i in values else _rec(i, status=0x86) for i in ids]]


async def _info(device, ota_reply=None):
    ota = AsyncMock(return_value=ota_reply if ota_reply is not None else [[_rec(0x0002, value=0x00000046)]])
    with (
        patch.object(raw_device, "zigpy_application", return_value=SimpleNamespace(get_device=lambda ieee: device)),
        patch.object(Basic, "read_attributes_raw", new=AsyncMock(side_effect=_basic_reply)),
        patch.object(Ota, "read_attributes_raw", new=ota),
    ):
        return await raw_device.async_get_raw_device_info(None, IEEE)


async def test_identity_comes_from_raw_basic_read():
    info = await _info(QuirkedDevice())
    assert info["manufacturer"] == {"status": "ok", "value": "_TZ3000_abcdefgh"}
    assert info["model"] == {"status": "ok", "value": "TS0001"}
    ident = info["identity"]
    assert ident["app_version"] == {"status": "ok", "value": 70}
    # No sw_build_id on this device: reported as unsupported, not as a bare null.
    assert ident["sw_build_id"] == {"status": "unsupported", "value": None}
    assert ident["ota_file_version"] == {"status": "ok", "value": "0x00000046"}


async def test_signature_is_the_devices_not_the_quirks():
    info = await _info(QuirkedDevice())
    assert info["signature"]["status"] == "ok"
    ep1 = info["signature"]["endpoints"][0]
    assert ep1 == {
        "id": 1,
        "status": "ok",
        "profile": "0x0104",
        "device_type": "0x0100",
        "in_clusters": ["0x0000", "0x0006", "0xe001"],
        "out_clusters": ["0x0019"],
    }
    # The quirk's virtual 0x0012 isn't in the device's own descriptor.
    assert "0x0012" not in ep1["in_clusters"]
    assert [e["id"] for e in info["signature"]["endpoints"]] == [1, 242]
    # Standard names come from zigpy's registry; manufacturer-specific IDs get none.
    assert info["standard_cluster_names"]["0x0006"] == "OnOff"
    assert "0xe001" not in info["standard_cluster_names"]
    assert info["node"] == {"logical_type": "Router", "mains_powered": True, "rx_on_when_idle": True, "manufacturer_code": "0x1141"}
    assert info["quirk_applied"] is True  # not a plain zigpy Device


async def test_sleepy_device_reports_no_response_instead_of_nulls():
    device = QuirkedDevice()
    device.zdo.Active_EP_req = AsyncMock(side_effect=TimeoutError)
    with (
        patch.object(raw_device, "zigpy_application", return_value=SimpleNamespace(get_device=lambda ieee: device)),
        patch.object(Basic, "read_attributes_raw", new=AsyncMock(side_effect=TimeoutError)),
        patch.object(Ota, "read_attributes_raw", new=AsyncMock(side_effect=TimeoutError)),
    ):
        info = await raw_device.async_get_raw_device_info(None, IEEE)
    assert info["signature"] == {"status": "no_response", "endpoints": []}
    assert info["manufacturer"]["status"] == "no_response"
    assert info["identity"]["ota_file_version"]["status"] == "no_response"


async def test_websocket_command(hass: HomeAssistant, hass_ws_client):
    entry = MockConfigEntry(domain=DOMAIN, title="ZHA Bindings Manager")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)

    device = QuirkedDevice()
    with (
        patch.object(raw_device, "zigpy_application", return_value=SimpleNamespace(get_device=lambda ieee: device)),
        patch.object(Basic, "read_attributes_raw", new=AsyncMock(side_effect=_basic_reply)),
        patch.object(Ota, "read_attributes_raw", new=AsyncMock(return_value=[[_rec(0x0002, value=0x46)]])),
    ):
        await client.send_json({"id": 1, "type": f"{DOMAIN}/raw_device_info", "ieee": IEEE})
        msg = await client.receive_json()
    assert msg["success"] is True
    assert msg["result"]["model"]["value"] == "TS0001"
    assert IEEE not in str(msg["result"])  # nothing network-identifying comes back

    def _missing(ieee):
        raise KeyError(ieee)

    with patch.object(raw_device, "zigpy_application", return_value=SimpleNamespace(get_device=_missing)):
        await client.send_json({"id": 2, "type": f"{DOMAIN}/raw_device_info", "ieee": IEEE})
        msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "device_not_found"

    with patch.object(raw_device, "zigpy_application", side_effect=LookupError("ZHA is not loaded")):
        await client.send_json({"id": 3, "type": f"{DOMAIN}/raw_device_info", "ieee": IEEE})
        msg = await client.receive_json()
    assert msg["success"] is False and msg["error"]["code"] == "zha_not_loaded"
