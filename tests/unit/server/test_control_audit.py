"""Control outcome audits through the public API and persistent store."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import httpx
from fastapi.testclient import TestClient

from mijiaAPI_V2.domain.exceptions import ExecutionUnknownError, ValidationError
from mijiaAPI_V2.api_client import MijiaAPI
from mijiaAPI_V2.domain.models import Credential, Device, DeviceAction, DeviceProperty
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from mijiaAPI_V2.infrastructure.http_client import HttpClient
from mijiaAPI_V2.repositories.device_repository import DeviceRepositoryImpl
from mijiaAPI_V2.repositories.interfaces import DeviceSpec
from mijiaAPI_V2.repositories.scene_repository import SceneRepositoryImpl
from mijiaAPI_V2.services.device_service import DeviceService
from mijiaAPI_V2.services.scene_service import SceneService

from server.app import create_app
from server.config import ServerSettings
from server.routers import api_v1
from server.store import ServerStore

OPERATIONS = {
    "property": {
        "path": "/api/v1/devices/lamp/properties",
        "payload": {"siid": 2, "piid": 1, "value": True},
        "method": "set_device_property",
        "action": "device.property.set",
        "metadata": {"device": "lamp", "siid": 2, "piid": 1},
        "response": {"success": True},
    },
    "action": {
        "path": "/api/v1/devices/lamp/actions",
        "payload": {"siid": 2, "aiid": 1, "params": {"secret": "private-value"}},
        "method": "call_device_action",
        "action": "device.action.call",
        "metadata": {"device": "lamp", "siid": 2, "aiid": 1},
        "response": {"result": {"code": 0}},
    },
    "batch": {
        "path": "/api/v1/batch/devices/properties",
        "payload": {
            "items": [
                {"device": "lamp", "siid": 2, "piid": 1, "value": True},
                {"device_id": "fan", "siid": 2, "piid": 1, "value": False},
            ]
        },
        "method": "batch_set_properties",
        "action": "device.property.batch_set",
        "metadata": {"count": 2},
        "response": {"items": [{"code": 0}, {"code": 0}]},
    },
    "scene": {
        "path": "/api/v1/scenes/scene-1/execute",
        "payload": None,
        "method": "execute_scene",
        "action": "scene.execute",
        "metadata": {"scene": "scene-1"},
        "response": {"success": True},
    },
}


@pytest.fixture
def control_client(tmp_path: Path) -> tuple[TestClient, ServerStore, dict[str, Any]]:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    store.replace_home_registry([{"id": "home-1", "name": "Home", "uid": "user-1"}])
    store.upsert_devices(
        [
            {"did": "did-1", "slug": "lamp", "name": "Lamp", "home_id": "home-1"},
            {"did": "did-2", "slug": "fan", "name": "Fan", "home_id": "home-1"},
        ]
    )
    for slug in ("lamp", "fan"):
        store.update_device(slug, {"access_mode": "write"})
    store.upsert_scenes([{"scene_id": "scene-1", "name": "Scene", "home_id": "home-1"}])
    store.update_scene("scene-1", {"executable": True})
    key = store.create_api_key("controller", ["write:devices", "write:scenes"])
    return TestClient(app, client=("127.0.0.1", 50000)), store, key


def post_control(client: TestClient, key: dict[str, Any], operation: str) -> Any:
    case = OPERATIONS[operation]
    return client.post(
        case["path"],
        json=case["payload"],
        headers={"Authorization": f"Bearer {key['key']}"},
    )


def assert_audit(
    store: ServerStore, key: dict[str, Any], operation: str, expected_result: str
) -> dict[str, Any]:
    case = OPERATIONS[operation]
    events = store.list_audit(action=case["action"])
    assert len(events) == 1
    event = events[0]
    assert event["result"] == expected_result
    assert event["actor_type"] == "api_key"
    assert event["actor_id"] == key["key_prefix"]
    for name, value in case["metadata"].items():
        assert event["metadata"][name] == value
    assert key["key"] not in json.dumps(event)
    assert "private-value" not in json.dumps(event)
    return event


@pytest.mark.parametrize("operation", OPERATIONS)
def test_success_is_audited_without_changing_response(
    control_client: Any, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    client, store, key = control_client
    case = OPERATIONS[operation]
    execute = Mock(return_value=case["response"])
    monkeypatch.setattr(client.app.state.runtime, case["method"], execute)

    response = post_control(client, key, operation)

    assert response.status_code == 200
    assert response.json() == case["response"]
    execute.assert_called_once()
    assert_audit(store, key, operation, "success")


@pytest.mark.parametrize("operation", ["property", "scene"])
def test_false_control_result_is_audited_as_failed(
    control_client: Any, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    client, store, key = control_client
    monkeypatch.setattr(
        client.app.state.runtime,
        OPERATIONS[operation]["method"],
        Mock(return_value={"success": False}),
    )

    response = post_control(client, key, operation)

    assert response.status_code == 200
    assert response.json() == {"success": False}
    assert_audit(store, key, operation, "failed")


@pytest.mark.parametrize(
    "result", [{"code": -704042011}, {"code": False}, {"code": "0"}, {}, None, "unknown"]
)
def test_rejected_or_unknown_action_result_is_not_audited_as_success(
    control_client: Any, monkeypatch: pytest.MonkeyPatch, result: Any
) -> None:
    client, store, key = control_client
    monkeypatch.setattr(
        client.app.state.runtime, "call_device_action", Mock(return_value={"result": result})
    )

    response = post_control(client, key, "action")

    assert response.status_code == 200
    assert response.json() == {"result": result}
    assert_audit(store, key, "action", "failed")


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([{"code": 0}, {"code": -1}], "warning"),
        ([{"code": -1}, {"code": -2}], "failed"),
        ([], "failed"),
        ([{"code": 0}], "warning"),
        ([{"code": 0}, {}], "warning"),
        ([{"code": 0}, {"code": 0}, {"code": 0}], "warning"),
        (None, "failed"),
        ([None, "unknown"], "failed"),
        ([{"code": False}, {"code": "0"}], "failed"),
    ],
    ids=[
        "mixed",
        "all-failed",
        "empty-result",
        "truncated",
        "unknown-item",
        "extra-item",
        "malformed-result",
        "malformed-items",
        "invalid-code-types",
    ],
)
def test_batch_audit_reflects_complete_or_partial_outcomes(
    control_client: Any, monkeypatch: pytest.MonkeyPatch, items: Any, expected: str
) -> None:
    client, store, key = control_client
    execute = Mock(return_value={"items": items})
    monkeypatch.setattr(client.app.state.runtime, "batch_set_properties", execute)

    response = post_control(client, key, "batch")

    assert response.status_code == 200
    assert response.json() == {"items": items}
    assert "device_id" not in execute.call_args.args[0][1]
    assert execute.call_args.args[0][1]["device"] == store.get_device("fan")["id"]
    assert execute.call_args.kwargs["internal_only"] is True
    assert_audit(store, key, "batch", expected)


def test_empty_batch_does_not_report_a_successful_execution(
    control_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, key = control_client
    monkeypatch.setattr(
        client.app.state.runtime, "batch_set_properties", Mock(return_value={"items": []})
    )

    response = client.post(
        OPERATIONS["batch"]["path"],
        json={"items": []},
        headers={"Authorization": f"Bearer {key['key']}"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    events = store.list_audit(action="device.property.batch_set")
    assert events == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_runtime_exception_is_audited_without_changing_http_handling(
    control_client: Any, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    client, store, key = control_client
    monkeypatch.setattr(
        client.app.state.runtime,
        OPERATIONS[operation]["method"],
        Mock(side_effect=RuntimeError("private-value")),
    )

    response = post_control(client, key, operation)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RUNTIME_ERROR"
    assert response.json()["error"]["message"] == "private-value"
    event = assert_audit(store, key, operation, "failed")
    assert event["metadata"]["error_type"] == "RuntimeError"


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("denial", ["scope", "resource", "local-permission"])
def test_authorization_denial_does_not_execute_control(
    control_client: Any, monkeypatch: pytest.MonkeyPatch, operation: str, denial: str
) -> None:
    client, store, key = control_client
    runtime = client.app.state.runtime
    if denial == "local-permission":
        store.update_device("lamp", {"access_mode": "read"})
        store.update_scene("scene-1", {"executable": False})
        execute = Mock()
        monkeypatch.setattr(runtime, "_api", execute)
    else:
        execute = Mock()
        monkeypatch.setattr(runtime, OPERATIONS[operation]["method"], execute)
        key = store.create_api_key(
            "denied-controller",
            ["read:status"] if denial == "scope" else ["write:devices", "write:scenes"],
            resource_policy={"devices": ["other-device"], "scenes": ["other-scene"]},
        )

    response = post_control(client, key, operation)

    assert response.status_code == 403
    execute.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_audit_storage_failure_does_not_mask_completed_control(
    control_client: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
) -> None:
    client, store, key = control_client
    case = OPERATIONS[operation]
    execute = Mock(return_value=case["response"])
    monkeypatch.setattr(client.app.state.runtime, case["method"], execute)
    monkeypatch.setattr(store, "add_audit", Mock(side_effect=sqlite3.OperationalError("disk full")))
    monkeypatch.setattr(api_v1.logger, "propagate", True)

    with caplog.at_level(logging.WARNING, logger=api_v1.logger.name):
        response = post_control(client, key, operation)

    assert response.status_code == 200
    assert response.json() == case["response"]
    execute.assert_called_once()
    assert any("audit" in record.getMessage().lower() for record in caplog.records)


def test_audit_storage_failure_preserves_original_unhandled_exception(
    control_client: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, store, key = control_client
    error = ValueError("original control failure: private-value")
    monkeypatch.setattr(client.app.state.runtime, "set_device_property", Mock(side_effect=error))
    audit = Mock(side_effect=sqlite3.OperationalError("disk full"))
    monkeypatch.setattr(store, "add_audit", audit)
    monkeypatch.setattr(api_v1.logger, "propagate", True)

    with (
        caplog.at_level(logging.WARNING, logger=api_v1.logger.name),
        pytest.raises(ValueError) as raised,
    ):
        post_control(client, key, "property")

    assert raised.value is error
    audit.assert_called_once()
    assert any("audit" in record.getMessage().lower() for record in caplog.records)
    assert "private-value" not in caplog.text


@pytest.mark.parametrize("operation", OPERATIONS)
def test_unknown_execution_is_not_reported_as_failure_or_safe_to_retry(
    control_client, monkeypatch, operation
):
    client, store, key = control_client
    execute = Mock(side_effect=ExecutionUnknownError("private-value"))
    monkeypatch.setattr(client.app.state.runtime, OPERATIONS[operation]["method"], execute)
    response = post_control(client, key, operation)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "EXECUTION_UNKNOWN"
    assert error["details"] == {"outcome": "unknown", "retry_safe": False}
    assert "private-value" not in response.text
    execute.assert_called_once()
    assert_audit(store, key, operation, "unknown")


def test_partial_batch_unknown_preserves_completed_count(control_client, monkeypatch):
    client, store, key = control_client
    monkeypatch.setattr(
        client.app.state.runtime,
        "batch_set_properties",
        Mock(side_effect=ExecutionUnknownError("response lost", context={"completed_count": 1})),
    )
    response = post_control(client, key, "batch")
    assert response.status_code == 409
    assert response.json()["error"]["details"]["completed_count"] == 1
    assert assert_audit(store, key, "batch", "unknown")["metadata"]["completed_count"] == 1


@pytest.mark.parametrize(
    "item",
    [
        {"device": "lamp", "piid": 1, "value": True},
        {"device": "lamp", "siid": 2, "value": True},
        {"device": "lamp", "siid": 2, "piid": 1},
        {"device": "lamp", "siid": True, "piid": 1, "value": True},
        {"device": "lamp", "siid": 2, "piid": -1, "value": True},
        {"device": "lamp", "device_id": "fan", "siid": 2, "piid": 1, "value": True},
        {"device_id": "", "siid": 2, "piid": 1, "value": True},
    ],
)
def test_invalid_batch_is_rejected_before_any_control(control_client, monkeypatch, item):
    client, store, key = control_client
    execute = Mock()
    monkeypatch.setattr(client.app.state.runtime, "batch_set_properties", execute)
    response = client.post(
        OPERATIONS["batch"]["path"],
        json={"items": [item]},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    execute.assert_not_called()
    assert store.list_audit(action="device.property.batch_set") == []


def test_sdk_validation_error_has_actionable_json_response(control_client, monkeypatch):
    client, store, key = control_client
    monkeypatch.setattr(
        client.app.state.runtime,
        "set_device_property",
        Mock(side_effect=ValidationError("属性值超出允许范围")),
    )
    response = post_control(client, key, "property")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONTROL_PARAMETERS"
    assert response.json()["error"]["message"] == "属性值超出允许范围"
    assert_audit(store, key, "property", "failed")


def install_real_sdk(client, store, http):
    credential = Credential(
        user_id="user-1",
        service_token="fixture-token",
        ssecurity="fixture-security",
        c_user_id="fixture-user",
        device_id="fixture-device",
        user_agent="test",
        expires_at=datetime(2099, 1, 1),
    )
    FileCredentialStore(store.settings.credential_path).save(credential)
    cache, specs = Mock(), Mock()
    repository = DeviceRepositoryImpl(http, cache)
    repository.get_by_id = Mock(
        side_effect=lambda did, credential: Device(
            did=did, name="fixture", model="fixture.light", home_id="home-1"
        )
    )
    specs.get_spec.return_value = DeviceSpec(
        model="fixture.light",
        name="fixture",
        properties=[DeviceProperty(siid=2, piid=1, name="power", type="bool", access="read_write")],
        actions=[DeviceAction(siid=2, aiid=1, name="trigger", parameters=[])],
    )
    sdk = MijiaAPI(
        credential,
        DeviceService(repository, specs, cache),
        SceneService(SceneRepositoryImpl(http)),
        cache_manager=cache,
    )
    client.app.state.runtime._api_client = sdk
    client.app.state.runtime._api_client_credential_id = credential.user_id


def test_batch_route_preserves_did_through_runtime_sdk_and_repository(control_client):
    client, store, key = control_client
    http = Mock()
    http.post.return_value = {
        "code": 0,
        "result": [
            {"did": "did-1", "siid": 2, "piid": 1, "code": 0},
            {"did": "did-2", "siid": 2, "piid": 1, "code": 0},
        ],
    }
    install_real_sdk(client, store, http)
    response = post_control(client, key, "batch")
    assert response.status_code == 200
    assert http.post.call_args.kwargs["json"] == {
        "params": [
            {"did": "did-1", "siid": 2, "piid": 1, "value": True},
            {"did": "did-2", "siid": 2, "piid": 1, "value": False},
        ]
    }
    assert_audit(store, key, "batch", "success")


@pytest.mark.parametrize("operation", OPERATIONS)
def test_lost_response_is_unknown_across_complete_server_sdk_chain(control_client, operation):
    client, store, key = control_client
    sent = []

    def upstream(request):
        sent.append(request.url.path)
        raise httpx.ReadTimeout("response lost after dispatch", request=request)

    config, crypto = Mock(), Mock()
    config.get.side_effect = lambda name, default: default
    crypto.encrypt_params.return_value = {"_nonce": "fixture-nonce"}
    http = HttpClient(config, crypto)
    http._client.close()
    with httpx.Client(transport=httpx.MockTransport(upstream)) as connection:
        http._client = connection
        install_real_sdk(client, store, http)
        if operation == "action":
            response = client.post(
                OPERATIONS[operation]["path"],
                json={"siid": 2, "aiid": 1},
                headers={"Authorization": f"Bearer {key['key']}"},
            )
        else:
            response = post_control(client, key, operation)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTION_UNKNOWN"
    assert len(sent) == 1
    assert_audit(store, key, operation, "unknown")


@pytest.mark.parametrize("operation", ["property", "action", "batch", "scene", "state", "spec"])
@pytest.mark.parametrize("alias_collision", [False, True])
def test_authorized_resource_cannot_rebind_to_switched_account(
    control_client, monkeypatch, operation, alias_collision
):
    client, store, _ = control_client
    runtime = client.app.state.runtime
    http = Mock()
    install_real_sdk(client, store, http)
    old_device, old_scene = store.get_device("lamp"), store.get_scene("scene-1")
    key = store.create_api_key(
        "only-old-record",
        ["read:devices", "write:devices", "write:scenes"],
        {"devices": [old_device["id"], store.get_device("fan")["id"]], "scenes": [old_scene["id"]]},
    )
    name = (
        OPERATIONS[operation]["method"]
        if operation in OPERATIONS
        else ("get_device_state" if operation == "state" else "get_device_spec")
    )
    original = getattr(runtime, name)
    sdk_lookup = Mock()
    monkeypatch.setattr(runtime, "_api_with_generation", sdk_lookup)

    def switch_after_route_authorization(*args, **kwargs):
        credential = Credential(
            user_id="new-user",
            service_token="new-token",
            ssecurity="new-security",
            c_user_id="new-cookie",
            device_id="new-device",
            user_agent="test",
            expires_at=datetime(2099, 1, 1),
        )
        runtime.commit_login_credential(credential, runtime.begin_login_attempt())
        store.replace_home_registry([{"id": "new-home", "uid": "new-user", "name": "New home"}])
        store.upsert_devices(
            [
                {
                    "did": "new-did",
                    "slug": old_device["id"] if alias_collision else "lamp",
                    "name": "new-lamp",
                    "model": "new.light",
                    "home_id": "new-home",
                }
            ]
        )
        store.update_device("new-did", {"access_mode": "write"})
        store.upsert_scenes(
            [
                {
                    "scene_id": old_scene["id"] if alias_collision else "scene-1",
                    "name": "new-scene",
                    "home_id": "new-home",
                }
            ]
        )
        store.update_scene(old_scene["id"] if alias_collision else "scene-1", {"executable": True})
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, name, switch_after_route_authorization)
    if operation in OPERATIONS:
        response = post_control(client, key, operation)
    else:
        response = client.get(
            f"/api/v1/devices/lamp/{operation}", headers={"Authorization": f"Bearer {key['key']}"}
        )
    assert response.status_code == 404
    sdk_lookup.assert_not_called()
    http.post.assert_not_called()


@pytest.mark.parametrize("operation", ["property", "action", "batch", "scene", "state", "spec"])
def test_resource_policy_is_rechecked_after_home_changes(control_client, monkeypatch, operation):
    client, store, _ = control_client
    runtime = client.app.state.runtime
    key = store.create_api_key(
        "home-limited",
        ["read:devices", "write:devices", "write:scenes"],
        {"devices": ["home-1"], "scenes": ["home-1"]},
    )
    name = (
        OPERATIONS[operation]["method"]
        if operation in OPERATIONS
        else ("get_device_state" if operation == "state" else "get_device_spec")
    )
    original = getattr(runtime, name)
    sdk_lookup = Mock()
    monkeypatch.setattr(runtime, "_api_with_generation", sdk_lookup)

    def move_after_route_authorization(*args, **kwargs):
        with store._database.connect() as conn:
            conn.execute("UPDATE device_registry SET home_id = 'other-home'")
            conn.execute("UPDATE scene_registry SET home_id = 'other-home'")
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, name, move_after_route_authorization)
    if operation in OPERATIONS:
        response = post_control(client, key, operation)
    else:
        response = client.get(
            f"/api/v1/devices/lamp/{operation}", headers={"Authorization": f"Bearer {key['key']}"}
        )
    assert response.status_code == 403
    sdk_lookup.assert_not_called()
