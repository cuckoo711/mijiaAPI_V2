"""The admin contract supports restrictive keys and atomic rotation."""

from datetime import timedelta

import pytest

from server.store import utc_now
from server.rate_limit import SlidingWindowRateLimiter
from server.routers import admin_auth
from tests.unit.server.test_app import admin_token, make_client_with_store


@pytest.fixture(autouse=True)
def isolated_auth_limiter(monkeypatch):
    monkeypatch.setattr(
        admin_auth,
        "ADMIN_AUTH_RATE_LIMITER",
        SlidingWindowRateLimiter(max_requests=20, window_seconds=300),
    )


def test_rotate_key_endpoint_inherits_policy_and_revokes_old_key(tmp_path):
    client, store = make_client_with_store(tmp_path)
    headers = {"Authorization": f"Bearer {admin_token(client)}"}
    old = client.post(
        "/api/admin/api-keys",
        headers=headers,
        json={
            "name": "limited",
            "scopes": ["read:devices"],
            "resource_policy": {"devices": ["lamp"]},
            "expires_at": (utc_now() + timedelta(days=2)).isoformat(),
        },
    ).json()
    store.validate_api_key(old["key"])
    rotated = client.post(f"/api/admin/api-keys/{old['id']}/rotate", headers=headers)
    assert rotated.status_code == 201
    replacement = rotated.json()
    assert replacement["resource_policy"] == old["resource_policy"]
    assert replacement["expires_at"] == old["expires_at"]
    assert (
        client.get("/api/v1/devices", headers={"Authorization": f"Bearer {old['key']}"}).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/devices", headers={"Authorization": f"Bearer {replacement['key']}"}
        ).status_code
        == 200
    )
    listed = client.get("/api/admin/api-keys", headers=headers)
    assert old["key"] not in listed.text and replacement["key"] not in listed.text
    audit = store.list_audit(action="api_key.rotate")
    assert len(audit) == 1
    assert audit[0]["metadata"]["old_key_id"] == old["id"]
    assert replacement["key"] not in str(audit)


@pytest.mark.parametrize(
    "payload",
    [
        {"scopes": []},
        {"scopes": ["write:everything"]},
        {"resource_policy": {"devices": "lamp"}},
        {"resource_policy": {"typo": ["lamp"]}},
        {"resource_policy": {"devices": [" "]}},
        {"expires_at": "2000-01-01T00:00:00Z"},
    ],
)
def test_invalid_key_contract_is_rejected(tmp_path, payload):
    client, store = make_client_with_store(tmp_path)
    headers = {"Authorization": f"Bearer {admin_token(client)}"}
    response = client.post(
        "/api/admin/api-keys", headers=headers, json={"name": "invalid", **payload}
    )
    assert response.status_code == 422
    assert store.list_api_keys() == []


def test_rotation_can_replace_expiry_explicitly(tmp_path):
    client, store = make_client_with_store(tmp_path)
    headers = {"Authorization": f"Bearer {admin_token(client)}"}
    old = store.create_api_key("reader", ["read:status"], expires_at=utc_now() + timedelta(days=1))
    new_expiry = (utc_now() + timedelta(days=5)).isoformat()
    response = client.post(
        f"/api/admin/api-keys/{old['id']}/rotate", headers=headers, json={"expires_at": new_expiry}
    )
    assert response.status_code == 201
    assert response.json()["expires_at"] == new_expiry
