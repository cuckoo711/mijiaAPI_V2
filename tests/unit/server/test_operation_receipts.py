"""API-key receipts belong to the initiating key, including queued events."""

import sqlite3
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.exceptions import ExecutionUnknownError
from tests.unit.server.test_control_audit import (
    control_client as _control_client_fixture,
    post_control,
)

# Reuse the existing real store/client fixture through pytest discovery.
control_client = _control_client_fixture


@pytest.mark.parametrize("outcome", ["success", "unknown", "failure"])
def test_receipt_is_owned_by_initiating_key(control_client, monkeypatch, outcome):
    client, store, key = control_client
    execute = Mock(return_value={"success": outcome == "success"})
    if outcome == "unknown":
        execute.side_effect = ExecutionUnknownError("upstream secret")
    monkeypatch.setattr(client.app.state.runtime, "set_device_property", execute)
    response = post_control(client, key, "property")
    operation_id = response.headers["X-Operation-ID"]
    assert response.headers["X-Audit-Delivery"] == "stored"
    own = client.get(
        f"/api/v1/operations/{operation_id}", headers={"Authorization": f"Bearer {key['key']}"}
    )
    assert own.status_code == 200
    assert (
        own.json()["result"]
        == {"success": "success", "unknown": "unknown", "failure": "failed"}[outcome]
    )
    assert own.json()["request_id"] == response.headers["X-Request-ID"]
    other = store.create_api_key("other", ["read:status", "read:logs"])
    denied = client.get(
        f"/api/v1/operations/{operation_id}", headers={"Authorization": f"Bearer {other['key']}"}
    )
    assert denied.status_code == 404
    assert client.get(f"/api/v1/operations/{operation_id}").status_code == 401


def test_audit_insert_failure_returns_queued_receipt_and_recovers(control_client, monkeypatch):
    client, store, key = control_client
    execute = Mock(return_value={"success": True})
    monkeypatch.setattr(client.app.state.runtime, "set_device_property", execute)
    original = store._persist_audit_event
    monkeypatch.setattr(
        store, "_persist_audit_event", Mock(side_effect=sqlite3.OperationalError("full"))
    )
    response = post_control(client, key, "property")
    assert response.status_code == 200 and response.json() == {"success": True}
    assert response.headers["X-Audit-Delivery"] == "queued"
    operation_id = response.headers["X-Operation-ID"]
    receipt = client.get(
        f"/api/v1/operations/{operation_id}", headers={"Authorization": f"Bearer {key['key']}"}
    )
    assert receipt.status_code == 200 and receipt.json()["delivery"] == "queued"
    monkeypatch.setattr(store, "_persist_audit_event", original)
    assert store.flush_pending_audit()["delivered"] == 1
    assert store.get_audit_event(operation_id)["delivery"] == "stored"
    execute.assert_called_once()


def test_oversized_client_trace_cannot_disable_control_audit(control_client, monkeypatch):
    client, store, key = control_client
    execute = Mock(return_value={"success": True})
    monkeypatch.setattr(client.app.state.runtime, "set_device_property", execute)
    response = client.post(
        "/api/v1/devices/lamp/properties",
        json={"siid": 2, "piid": 1, "value": False},
        headers={"Authorization": f"Bearer {key['key']}", "X-Request-ID": "x" * 3000},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.headers["X-Audit-Delivery"] == "stored"
    event = store.get_audit_event(response.headers["X-Operation-ID"])
    assert event["request_id"] == response.headers["X-Request-ID"]
    assert store.audit_status()["unavailable"] == 0
    execute.assert_called_once()
