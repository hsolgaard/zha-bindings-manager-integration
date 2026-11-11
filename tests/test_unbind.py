"""Direct unbind (1.10.6): the integration sends the ZDO Unbind_req itself."""
from unittest import mock

from homeassistant.core import HomeAssistant
from zigpy.zdo.types import Status, ZDOCmd

from custom_components.zha_bindings_manager import unbind_api
from custom_components.zha_bindings_manager.const import DOMAIN

from .test_websocket import _client

SRC = "bb:bb:bb:bb:bb:bb:bb:02"
GONE = "90:fd:9f:ff:fe:d4:b7:4e"  # a target no longer in ZHA


def _fake_app(answer):
    device = mock.Mock()
    device.zdo.request = mock.AsyncMock(return_value=answer)
    app = mock.Mock()

    def get_device(ieee=None, nwk=None):
        if str(ieee) == SRC:
            return device
        raise KeyError(ieee)

    app.get_device.side_effect = get_device
    return app, device


async def test_unbinds_a_binding_to_a_removed_device(hass: HomeAssistant, hass_ws_client):
    client = await _client(hass, hass_ws_client)
    app, device = _fake_app([Status.SUCCESS])
    with mock.patch.object(unbind_api, "_app", return_value=app):
        await client.send_json({"id": 10, "type": f"{DOMAIN}/unbind", "source_ieee": SRC, "endpoint": 1, "cluster": 6, "target_ieee": GONE, "target_endpoint": 1})
        msg = await client.receive_json()
    assert msg["success"] and msg["result"] == {"status": "SUCCESS"}
    args = device.zdo.request.call_args.args
    assert args[0] == ZDOCmd.Unbind_req and str(args[1]) == SRC and args[2] == 1 and args[3] == 6
    assert args[4].addrmode == 3 and str(args[4].ieee) == GONE and args[4].endpoint == 1  # never looked the target up


async def test_group_binding_and_the_device_answer_is_returned(hass: HomeAssistant, hass_ws_client):
    client = await _client(hass, hass_ws_client)
    app, device = _fake_app([Status.NO_ENTRY])
    with mock.patch.object(unbind_api, "_app", return_value=app):
        await client.send_json({"id": 11, "type": f"{DOMAIN}/unbind", "source_ieee": SRC, "endpoint": 1, "cluster": 0, "group_id": 0x4845})
        msg = await client.receive_json()
    assert msg["result"] == {"status": "NO_ENTRY"}
    dst = device.zdo.request.call_args.args[4]
    assert dst.addrmode == 1 and dst.nwk == 0x4845


async def test_no_answer_and_bad_input(hass: HomeAssistant, hass_ws_client):
    client = await _client(hass, hass_ws_client)
    app, device = _fake_app(None)
    device.zdo.request.side_effect = TimeoutError()
    with mock.patch.object(unbind_api, "_app", return_value=app):
        await client.send_json({"id": 12, "type": f"{DOMAIN}/unbind", "source_ieee": SRC, "endpoint": 1, "cluster": 6, "group_id": 5})
        assert (await client.receive_json())["result"]["status"] == "no_answer"
        await client.send_json({"id": 13, "type": f"{DOMAIN}/unbind", "source_ieee": SRC, "endpoint": 1, "cluster": 6, "target_ieee": GONE})
        assert not (await client.receive_json())["success"]
    await client.send_json({"id": 14, "type": f"{DOMAIN}/get_capabilities"})
    assert (await client.receive_json())["result"]["features"]["direct_unbind"] is True
