"""Manual controls enforce authentication, CSRF and the current resource policy."""

from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.exceptions import ExecutionUnknownError
from server.rate_limit import SlidingWindowRateLimiter
from server.routers import admin_auth
from tests.unit.server.test_app import make_client_with_store, admin_cookie_session


@pytest.fixture
def manual_client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        admin_auth,
        "ADMIN_AUTH_RATE_LIMITER",
        SlidingWindowRateLimiter(max_requests=20, window_seconds=300),
    )
    client, store = make_client_with_store(tmp_path)
    _, csrf = admin_cookie_session(client)
    store.replace_home_registry([{"id": "home", "uid": "owner", "name": "Home"}])
    store.upsert_devices([{"did": "lamp", "slug": "lamp", "name": "Lamp", "home_id": "home"}])
    store.update_device("lamp", {"access_mode": "write"})
    store.upsert_scenes([{"scene_id": "scene", "home_id": "home", "name": "Scene"}])
    store.update_scene("scene", {"executable": True})
    device, scene = store.get_device("lamp"), store.get_scene("scene")
    return client, store, {"X-CSRF-Token": csrf}, device["id"], scene["id"]


def case(device_id, scene_id, operation):
    if operation == "scene":
        return f"/api/admin/scenes/{scene_id}/execute", None, "execute_scene", {"success": True}
    if operation == "property":
        return (
            f"/api/admin/devices/{device_id}/properties",
            {"siid": 2, "piid": 1, "value": False},
            "set_device_property",
            {"success": True},
        )
    return (
        f"/api/admin/devices/{device_id}/actions",
        {"siid": 2, "aiid": 1, "params": {}},
        "call_device_action",
        {"result": {"code": 0}},
    )


@pytest.mark.parametrize("operation", ["property", "action", "scene"])
def test_cookie_control_requires_csrf_and_authentication(manual_client, monkeypatch, operation):
    client, store, headers, device, scene = manual_client
    path, payload, method, result = case(device, scene, operation)
    execute = Mock(return_value=result)
    monkeypatch.setattr(client.app.state.runtime, method, execute)
    assert client.post(path, json=payload).status_code == 403
    execute.assert_not_called()
    client.cookies.clear()
    assert client.post(path, json=payload, headers=headers).status_code == 401
    execute.assert_not_called()


@pytest.mark.parametrize("operation", ["property", "action", "scene"])
@pytest.mark.parametrize("denial", ["hidden", "permission"])
def test_manual_control_checks_current_visibility_and_permission(
    manual_client, monkeypatch, operation, denial
):
    client, store, headers, device, scene = manual_client
    if operation == "scene":
        store.update_scene(scene, {"hidden": True} if denial == "hidden" else {"executable": False})
    else:
        store.update_device(
            device, {"hidden": True} if denial == "hidden" else {"access_mode": "read"}
        )
    sdk = Mock()
    monkeypatch.setattr(client.app.state.runtime, "_api_with_generation", sdk)
    path, payload, _, _ = case(device, scene, operation)
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 403
    sdk.assert_not_called()
    assert response.headers["X-Operation-ID"]
    assert store.get_audit_event(response.headers["X-Operation-ID"])["result"] == "failed"


@pytest.mark.parametrize("operation", ["property", "action", "scene"])
def test_manual_result_receipt_keeps_original_response(manual_client, monkeypatch, operation):
    client, store, headers, device, scene = manual_client
    path, payload, method, result = case(device, scene, operation)
    execute = Mock(return_value=result)
    monkeypatch.setattr(client.app.state.runtime, method, execute)
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 200 and response.json() == result
    execute.assert_called_once()
    assert execute.call_args.kwargs["internal_only"] is True
    operation_id = response.headers["X-Operation-ID"]
    receipt = client.get(f"/api/admin/operations/{operation_id}")
    assert receipt.status_code == 200
    assert receipt.json()["result"] == "success" and receipt.json()["actor_type"] == "admin"
    assert response.headers["X-Audit-Delivery"] == "stored"


def test_admin_unknown_result_has_receipt_without_retry(manual_client, monkeypatch):
    client, store, headers, device, scene = manual_client
    execute = Mock(side_effect=ExecutionUnknownError("secret-token"))
    monkeypatch.setattr(client.app.state.runtime, "set_device_property", execute)
    path, payload, _, _ = case(device, scene, "property")
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "EXECUTION_UNKNOWN"
    assert "secret-token" not in response.text
    execute.assert_called_once()
    receipt = client.get(f"/api/admin/operations/{response.headers['X-Operation-ID']}")
    assert receipt.json()["result"] == "unknown"


def test_admin_state_and_spec_are_read_only(manual_client, monkeypatch):
    client, _, _, device, _ = manual_client
    state = Mock(return_value=[{"siid": 2, "piid": 1, "code": 0, "value": False}])
    spec = Mock(return_value={"properties": []})
    monkeypatch.setattr(client.app.state.runtime, "get_device_state", state)
    monkeypatch.setattr(client.app.state.runtime, "get_device_spec", spec)
    assert client.get(f"/api/admin/devices/{device}/state").json()["items"][0]["value"] is False
    assert client.get(f"/api/admin/devices/{device}/spec").json()["spec"] == {"properties": []}
    state.assert_called_once_with(device, internal_only=True)
    spec.assert_called_once_with(device, internal_only=True)
