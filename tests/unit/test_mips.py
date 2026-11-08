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

    def test_extract_code_from_raw_code(self):
        assert extract_code_from_redirect("abc123") == "abc123"

    def test_extract_code_missing(self):
        with pytest.raises(MipsAuthError):
            extract_code_from_redirect("http://homeassistant.local:8123/?state=xyz")
        with pytest.raises(MipsAuthError):
            extract_code_from_redirect("   ")

    def test_auth_url_contains_required_params(self):
        client = MipsOAuthClient(device_uuid="u1")
        url = client.auth_url()
        assert "account.xiaomi.com/oauth2/authorize" in url
        assert "client_id=2882303761520251711" in url
        assert "response_type=code" in url
        assert "device_id=ha.u1" in url
        assert "homeassistant.local" in url

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
        client = MipsOAuthClient(device_uuid="u1")
        tokens = client.exchange_code("the-code")
        assert tokens.access_token == "at"
        assert tokens.refresh_token == "rt"
        assert not tokens.needs_refresh()
        args, kwargs = mock_get.call_args
        assert args[0].endswith("/app/v2/ha/oauth/get_token")
        data = json.loads(kwargs["params"]["data"])
        assert data["code"] == "the-code"
        assert data["client_id"] == "2882303761520251711"

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
            device_uuid="u1",
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

    def test_subscribe_all_wildcards(self):
        client = self._client()
        mqtt = MagicMock()
        mqtt.subscribe.return_value = (0, 1)
        client._mqtt = mqtt
        client.subscribe_all()
        topics = [call.args[0] for call in mqtt.subscribe.call_args_list]
        assert "device/+/up/properties_changed/#" in topics

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
