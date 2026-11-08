"""MIPS 推送模块单元测试"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from mijiaAPI_V2.mips.auth import (
    MipsAuthError,
    MipsOAuthClient,
    MipsTokenStore,
    MipsTokens,
    extract_code_from_redirect,
)
from mijiaAPI_V2.mips.cloud import MipsCloudClient
from mijiaAPI_V2.mips.events import (
    parse_device_event,
    parse_device_state,
    parse_property_change,
)
from mijiaAPI_V2.mips.service import MipsService

# 云 MQTT 要求 client_id 为 ha.<32位hex>，测试统一用合规的实例 ID
TEST_UUID = "0123456789abcdef0123456789abcdef"


class TestEventParsing:
    def test_parse_property_change(self):
        payload = json.dumps({"params": {"siid": 2, "piid": 1, "value": True}}).encode()
        event = parse_property_change("did-1", "device/did-1/up/properties_changed/2/1", payload)
        assert event is not None
        assert event.did == "did-1"
        assert (event.siid, event.piid, event.value) == (2, 1, True)
        assert event.key == "2.1"

    def test_parse_property_change_rejects_garbage(self):
        assert parse_property_change("d", "t", b"not-json") is None
        assert parse_property_change("d", "t", b"{}") is None
        assert parse_property_change("d", "t", b'{"params": {"siid": 2}}') is None

    def test_parse_device_event(self):
        payload = json.dumps(
            {"params": {"siid": 2, "eiid": 1014, "arguments": [{"piid": 1, "value": 1}]}}
        ).encode()
        event = parse_device_event("did-1", "device/did-1/up/event_occured/2/1014", payload)
        assert event is not None
        assert (event.siid, event.eiid) == (2, 1014)
        assert event.arguments == [{"piid": 1, "value": 1}]

    def test_parse_device_event_arguments_default_empty(self):
        payload = json.dumps({"params": {"siid": 2, "eiid": 1014}}).encode()
        event = parse_device_event("did-1", "t", payload)
        assert event is not None
        assert event.arguments == []

    def test_parse_device_state(self):
        payload = json.dumps(
            {"device_id": "did-1", "event": "online", "model": "yeelink.light.mbulb3"}
        ).encode()
        event = parse_device_state("did-1", "device/did-1/state/#", payload)
        assert event is not None
        assert event.state == "online"
        assert event.did == "did-1"

    def test_parse_device_state_rejects_bad_payload(self):
        assert parse_device_state("d", "t", b"[]") is None
        assert parse_device_state("d", "t", b'{"device_id": "x"}') is None


class TestAuth:
    def test_extract_code_from_url(self):
        url = "http://homeassistant.local:8123/?code=abc123&state=xyz"
        assert extract_code_from_redirect(url) == "abc123"

    def test_extract_code_preserves_plus_and_padding(self):
        # 浏览器地址栏显示解码后的网址，base64 授权码里的 + / = 必须原样保留
        url = "http://homeassistant.local:8123/?code=ab+c/d==&state=xyz"
        assert extract_code_from_redirect(url) == "ab+c/d=="

    def test_extract_code_decodes_percent_encoding(self):
        url = "http://homeassistant.local:8123/?code=ab%2Bc%2Fd%3D%3D&state=x"
        assert extract_code_from_redirect(url) == "ab+c/d=="

    def test_extract_code_tolerates_surrounding_text(self):
        text = "登录后跳转到了 http://homeassistant.local:8123/?code=zz9/xx= 打不开"
        assert extract_code_from_redirect(text) == "zz9/xx="

    def test_extract_code_from_raw_code(self):
        assert extract_code_from_redirect("abc123") == "abc123"
        assert extract_code_from_redirect("ab+c/d==") == "ab+c/d=="

    def test_extract_code_missing(self):
        with pytest.raises(MipsAuthError):
            extract_code_from_redirect("http://homeassistant.local:8123/?state=xyz")
        with pytest.raises(MipsAuthError):
            extract_code_from_redirect("   ")

    def test_auth_url_contains_required_params(self):
        client = MipsOAuthClient(device_uuid=TEST_UUID)
        url = client.auth_url()
        assert "account.xiaomi.com/oauth2/authorize" in url
        assert "client_id=2882303761520251711" in url
        assert "response_type=code" in url
        assert f"device_id=ha.{TEST_UUID}" in url
        assert "homeassistant.local" in url
        # 与官方集成一致：webhook 路径 redirect_uri、sha1 state、布尔 skip_confirm
        assert "redirect_uri=http%3A%2F%2Fhomeassistant.local%3A8123%2Fapi%2Fwebhook%2F" in url
        assert f"state={client.state}" in url
        assert "skip_confirm=False" in url

    def test_state_matches_official_shape(self):
        import hashlib

        client = MipsOAuthClient(device_uuid=TEST_UUID)
        assert client.state == hashlib.sha1(f"d=ha.{TEST_UUID}".encode()).hexdigest()

    def test_device_uuid_defaults_to_real_uuid(self):
        import re

        client = MipsOAuthClient()
        # 云 MQTT 要求 ha.<32位hex>，不合规会被拒（Not authorized）
        assert re.fullmatch(r"ha\.[0-9a-f]{32}", client.device_id)

    def test_nonconforming_uuid_is_replaced(self):
        client = MipsOAuthClient(device_uuid="b4b1d7d2-cc28-4220-ae61-2034a565dcb3")
        import re

        assert re.fullmatch(r"ha\.[0-9a-f]{32}", client.device_id)

    @patch("mijiaAPI_V2.mips.auth.httpx.get")
    def test_exchange_code_calls_token_api(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "code": 0,
                "result": {
                    "access_token": "at",
                    "refresh_token": "rt",
                    "expires_in": 1000,
                },
            },
        )
        client = MipsOAuthClient(device_uuid=TEST_UUID)
        tokens = client.exchange_code("the-code")
        assert tokens.access_token == "at"
        assert tokens.refresh_token == "rt"
        assert not tokens.needs_refresh()
        args, kwargs = mock_get.call_args
        assert args[0].endswith("/app/v2/ha/oauth/get_token")
        data = json.loads(kwargs["params"]["data"])
        assert data["code"] == "the-code"
        assert data["client_id"] == 2882303761520251711  # 服务端要求数值类型
        assert isinstance(data["client_id"], int)
        assert data["device_id"] == f"ha.{TEST_UUID}"
        # redirect_uri 与授权请求一致：注册前缀 + webhook 路径
        assert data["redirect_uri"].startswith("http://homeassistant.local:8123/api/webhook/")
        assert kwargs["headers"]["User-Agent"] == f"ha_xiaomi_home/v0.5.0 client/ha.{TEST_UUID}"

    @patch("mijiaAPI_V2.mips.auth.httpx.get")
    def test_exchange_code_rejects_error_response(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"code": 1})
        with pytest.raises(MipsAuthError):
            MipsOAuthClient().exchange_code("bad")

    @patch("mijiaAPI_V2.mips.auth.httpx.get")
    def test_refresh_token_flow(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "code": 0,
                "result": {
                    "access_token": "at2",
                    "refresh_token": "rt2",
                    "expires_in": 1000,
                },
            },
        )
        tokens = MipsOAuthClient().refresh("rt1")
        data = json.loads(mock_get.call_args.kwargs["params"]["data"])
        assert data["refresh_token"] == "rt1"
        assert "code" not in data
        assert tokens.access_token == "at2"


class TestTokenStore:
    def test_roundtrip_encrypted(self, tmp_path):
        store = MipsTokenStore(default_path=tmp_path / "mips_tokens.json")
        tokens = MipsTokens(
            access_token="SECRET-ACCESS-VALUE",
            refresh_token="SECRET-REFRESH-VALUE",
            expires_at=123.0,
            device_uuid=TEST_UUID,
        )
        store.save_tokens(tokens)
        raw = (tmp_path / "mips_tokens.json").read_text(encoding="utf-8")
        assert "SECRET-ACCESS-VALUE" not in raw  # 密文落盘
        assert "SECRET-REFRESH-VALUE" not in raw
        loaded = store.load_tokens()
        assert loaded == tokens

    def test_load_missing_returns_none(self, tmp_path):
        store = MipsTokenStore(default_path=tmp_path / "none.json")
        assert store.load_tokens() is None

    def test_needs_refresh(self):
        tokens = MipsTokens("at", "rt", expires_at=100.0, device_uuid="u")
        assert tokens.needs_refresh(now=99.0) is False
        assert tokens.needs_refresh(now=100.0) is True


class TestCloudClient:
    def _client(self) -> MipsCloudClient:
        return MipsCloudClient(
            app_id="app", access_token="tok", client_id="ha.test"
        )

    def test_subscribe_devices_topics(self):
        client = self._client()
        mqtt = MagicMock()
        mqtt.subscribe.return_value = (0, 1)
        client._mqtt = mqtt
        client.subscribe_devices(["did-1"])
        topics = [call.args[0] for call in mqtt.subscribe.call_args_list]
        assert "device/did-1/up/properties_changed/#" in topics
        assert "device/did-1/up/event_occured/#" in topics
        assert "device/did-1/state/#" in topics

    @patch("mijiaAPI_V2.mips.cloud.httpx.post")
    def test_fetch_device_dids(self, mock_post):
        from mijiaAPI_V2.mips.cloud import fetch_device_dids

        mock_post.return_value = MagicMock(
            json=lambda: {
                "code": 0,
                "result": {
                    "list": [{"did": "111"}, {"did": 222}],
                    "has_more": False,
                },
            }
        )
        dids = fetch_device_dids("tok", "inst32hex")
        assert dids == ["111", "222"]
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearertok"

    def test_on_message_dispatches_property_change(self):
        client = self._client()
        received = []
        client.on_property_change(received.append)
        message = MagicMock(
            topic="device/did-1/up/properties_changed/2/1",
            payload=json.dumps({"params": {"siid": 2, "piid": 1, "value": 7}}).encode(),
        )
        client._on_message(None, None, message)
        assert len(received) == 1
        assert received[0].value == 7

    def test_on_message_dispatches_event_and_state(self):
        client = self._client()
        events, states = [], []
        client.on_device_event(events.append)
        client.on_device_state(states.append)

        event_msg = MagicMock(
            topic="device/did-1/up/event_occured/2/1014",
            payload=json.dumps({"params": {"siid": 2, "eiid": 1014, "arguments": []}}).encode(),
        )
        client._on_message(None, None, event_msg)
        state_msg = MagicMock(
            topic="device/did-1/state/online",
            payload=json.dumps({"device_id": "did-1", "event": "offline"}).encode(),
        )
        client._on_message(None, None, state_msg)
        assert len(events) == 1
        assert len(states) == 1
        assert states[0].state == "offline"

    def test_handler_exception_does_not_break_dispatch(self):
        client = self._client()
        second = []
        client.on_property_change(lambda e: (_ for _ in ()).throw(RuntimeError("x")))
        client.on_property_change(second.append)
        message = MagicMock(
            topic="device/did-1/up/properties_changed/2/1",
            payload=json.dumps({"params": {"siid": 2, "piid": 1, "value": 1}}).encode(),
        )
        client._on_message(None, None, message)
        assert len(second) == 1


class TestService:
    def _service(self, webhook_url=None) -> MipsService:
        return MipsService(webhook_url=webhook_url)

    def test_decorator_did_filter(self):
        service = self._service()
        all_events, only_one = [], []
        service.on_property_change()(all_events.append)
        service.on_property_change(did="did-1")(only_one.append)

        service._dispatch_property(
            parse_property_change(
                "did-2", "t", json.dumps({"params": {"siid": 1, "piid": 1, "value": 0}}).encode()
            )
        )
        assert len(all_events) == 1
        assert len(only_one) == 0

        service._dispatch_property(
            parse_property_change(
                "did-1", "t", json.dumps({"params": {"siid": 1, "piid": 1, "value": 1}}).encode()
            )
        )
        assert len(all_events) == 2
        assert len(only_one) == 1

    @patch("mijiaAPI_V2.mips.service.httpx.post")
    def test_webhook_post(self, mock_post):
        service = self._service(webhook_url="http://example.com/hook")
        service._dispatch_state(
            parse_device_state("did-1", "t", json.dumps({"device_id": "did-1", "event": "online"}).encode())
        )
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert payload["type"] == "device_state"
        assert payload["did"] == "did-1"

    @patch("mijiaAPI_V2.mips.service.httpx.post")
    def test_webhook_failure_is_swallowed(self, mock_post):
        mock_post.side_effect = RuntimeError("boom")
        service = self._service(webhook_url="http://example.com/hook")
        service._dispatch_state(
            parse_device_state("did-1", "t", json.dumps({"device_id": "did-1", "event": "online"}).encode())
        )  # 不应抛出

    def test_start_requires_login(self):
        service = self._service()
        with pytest.raises(RuntimeError):
            service.start()

    @patch.object(MipsTokenStore, "save_tokens")
    @patch("mijiaAPI_V2.mips.auth.httpx.get")
    def test_complete_login_saves_tokens(self, mock_get, mock_save):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "code": 0,
                "result": {
                    "access_token": "at",
                    "refresh_token": "rt",
                    "expires_in": 1000,
                },
            },
        )
        service = self._service()
        service.complete_login("http://homeassistant.local:8123/?code=c1")
        assert service.is_logged_in
        mock_save.assert_called_once()

    def test_is_connected_false_before_start(self):
        assert self._service().is_connected is False

    def test_refresh_watchdog_lifecycle(self):
        service = self._service()
        with patch.object(MipsCloudClient, "connect"), patch(
            "mijiaAPI_V2.mips.service.fetch_device_dids", return_value=["did-1"]
        ), patch.object(MipsCloudClient, "subscribe_devices"), patch.object(
            MipsTokenStore, "save_tokens"
        ):
            service._tokens = MipsTokens(
                access_token="at",
                refresh_token="rt",
                expires_at=100.0,
                device_uuid=TEST_UUID,
            )
            service.start()
            assert service._refresh_stop is not None
            service.stop()
            assert service._refresh_stop is None
            assert service._client is None

    def test_old_uuid_normalized_on_use(self, tmp_path):
        import re as _re

        service = MipsService(token_path=str(tmp_path / "t.json"))
        service._tokens = MipsTokens(
            access_token="at",
            refresh_token="rt",
            expires_at=100.0,
            device_uuid="b4b1d7d2-cc28-4220-ae61-2034a565dcb3",
        )
        with patch.object(MipsTokenStore, "save_tokens") as mock_save:
            did = service._ensure_device_uuid()
        assert _re.fullmatch(r"[0-9a-f]{32}", did)
        assert service._tokens.device_uuid == did
        mock_save.assert_called_once()
