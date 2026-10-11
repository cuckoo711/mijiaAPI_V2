"""Scene acknowledgements remain known successes, known failures, or unknown execution."""

from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.exceptions import ExecutionUnknownError
from mijiaAPI_V2.repositories.scene_repository import SceneRepositoryImpl
from tests.unit.server import test_control_audit as control_tests

control_client = control_tests.control_client

INVALID_ACKS = [
    None,
    [],
    "unexpected",
    {},
    {"code": None},
    {"code": False},
    {"code": True},
    {"code": "0"},
    {"code": 0.0},
]


@pytest.mark.parametrize("ack", INVALID_ACKS)
def test_sync_scene_repository_rejects_missing_or_malformed_ack(control_client, ack):
    client, store, _ = control_client
    http = Mock()
    http.post.return_value = ack
    control_tests.install_real_sdk(client, store, http)
    runtime = client.app.state.runtime
    scene = store.get_scene("scene-1")
    with pytest.raises(ExecutionUnknownError) as raised:
        runtime.execute_scene(scene["id"], internal_only=True)
    assert raised.value.context["retry_safe"] is False
    http.post.assert_called_once()


@pytest.mark.parametrize("ack", INVALID_ACKS)
def test_api_scene_unknown_ack_has_owned_unknown_receipt_and_no_retry(control_client, ack):
    client, store, key = control_client
    http = Mock()
    http.post.return_value = ack
    control_tests.install_real_sdk(client, store, http)
    response = control_tests.post_control(client, key, "scene")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTION_UNKNOWN"
    assert response.json()["error"]["details"]["retry_safe"] is False
    operation_id = response.headers["X-Operation-ID"]
    receipt = client.get(
        f"/api/v1/operations/{operation_id}", headers={"Authorization": f"Bearer {key['key']}"}
    )
    assert receipt.status_code == 200
    assert receipt.json()["result"] == "unknown"
    assert receipt.json()["metadata"]["retry_safe"] is False
    assert response.headers["X-Audit-Delivery"] == "stored"
    http.post.assert_called_once()


@pytest.mark.parametrize("code", [0, -1, 1, 404, 500])
def test_scene_repository_explicit_integer_ack_preserves_known_outcome(control_client, code):
    client, store, key = control_client
    http = Mock()
    http.post.return_value = {"code": code}
    control_tests.install_real_sdk(client, store, http)
    response = control_tests.post_control(client, key, "scene")
    assert response.status_code == 200
    assert response.json() == {"success": code == 0}
    event = store.get_audit_event(response.headers["X-Operation-ID"])
    assert event["result"] == ("success" if code == 0 else "failed")
    http.post.assert_called_once()


def test_scene_ack_does_not_require_unverified_result_fields(control_client):
    client, store, _ = control_client
    http = Mock()
    http.post.return_value = {"code": 0}
    control_tests.install_real_sdk(client, store, http)
    credential = client.app.state.runtime.load_credential()
    assert SceneRepositoryImpl(http).execute("scene-1", "home-1", credential) is True
    http.post.assert_called_once()
