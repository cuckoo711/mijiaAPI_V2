"""Tests for the FastAPI server application."""

from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import ServerSettings
from server.store import ServerStore


def make_client(tmp_path: Path) -> TestClient:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    return TestClient(create_app(settings))


def make_client_with_store(tmp_path: Path) -> tuple[TestClient, ServerStore]:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    return TestClient(create_app(settings, store=store)), store


def admin_token(client: TestClient) -> str:
    client.post(
        "/api/admin/bootstrap/admin",
        json={"username": "admin", "password": "strong-password"},
    )
    login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "strong-password"},
    )
    return str(login.json()["token"])


def test_healthz_is_public(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_network_access_policy_allows_lan_only_after_switch_enabled(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)

    blocked_client = TestClient(app, client=("192.168.1.20", 50000))
    assert blocked_client.get("/healthz").status_code == 403

    store.set_config("ALLOW_LAN_ACCESS", True)
    allowed_client = TestClient(app, client=("192.168.1.20", 50000))
    assert allowed_client.get("/healthz").status_code == 200


def test_network_access_policy_allows_public_only_after_switch_enabled(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)

    blocked_client = TestClient(app, client=("8.8.8.8", 50000))
    assert blocked_client.get("/healthz").status_code == 403

    store.set_config("ALLOW_PUBLIC_ACCESS", True)
    allowed_client = TestClient(app, client=("8.8.8.8", 50000))
    assert allowed_client.get("/healthz").status_code == 200


def test_network_access_policy_uses_forwarded_for_from_trusted_proxy(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    store.set_config("TRUST_PROXY_HEADERS", True)
    store.set_config("TRUSTED_PROXY_CIDRS", ["127.0.0.1/32", "::1/128"])
    client = TestClient(app, client=("127.0.0.1", 50000))

    blocked_response = client.get("/healthz", headers={"X-Forwarded-For": "8.8.8.8"})
    assert blocked_response.status_code == 403

    store.set_config("ALLOW_PUBLIC_ACCESS", True)
    allowed_response = client.get("/healthz", headers={"X-Forwarded-For": "8.8.8.8"})
    assert allowed_response.status_code == 200


def test_network_access_policy_trusts_loopback_proxy_headers_by_default(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    client = TestClient(app, client=("127.0.0.1", 50000))

    blocked_response = client.get("/healthz", headers={"X-Forwarded-For": "8.8.8.8"})
    assert blocked_response.status_code == 403

    store.set_config("ALLOW_PUBLIC_ACCESS", True)
    allowed_response = client.get("/healthz", headers={"X-Forwarded-For": "8.8.8.8"})
    assert allowed_response.status_code == 200


def test_network_access_policy_allows_admin_bootstrap_from_public_proxy(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = {"X-Forwarded-For": "8.8.8.8"}

    frontend_response = client.get("/", headers=headers)
    assert frontend_response.status_code == 200

    state_response = client.get("/api/admin/bootstrap/state", headers=headers)
    assert state_response.status_code == 200
    assert state_response.json() == {"initialized": False}

    created_admin = client.post(
        "/api/admin/bootstrap/admin",
        headers=headers,
        json={"username": "admin", "password": "strong-password"},
    )
    assert created_admin.status_code == 201

    login = client.post(
        "/api/admin/auth/login",
        headers=headers,
        json={"username": "admin", "password": "strong-password"},
    )
    assert login.status_code == 200
    admin_token = login.json()["token"]

    config_response = client.get(
        "/api/admin/config",
        headers={**headers, "Authorization": f"Bearer {admin_token}"},
    )
    assert config_response.status_code == 200

    external_api_response = client.get("/api/v1/status", headers=headers)
    assert external_api_response.status_code == 403
    assert external_api_response.json()["error"]["code"] == "NETWORK_ACCESS_DENIED"


def test_network_access_policy_uses_real_ip_from_trusted_proxy(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    store.set_config("TRUST_PROXY_HEADERS", True)
    store.set_config("TRUSTED_PROXY_CIDRS", ["127.0.0.1/32", "::1/128"])
    client = TestClient(app, client=("127.0.0.1", 50000))

    blocked_response = client.get("/healthz", headers={"X-Real-IP": "192.168.1.20"})
    assert blocked_response.status_code == 403

    store.set_config("ALLOW_LAN_ACCESS", True)
    allowed_response = client.get("/healthz", headers={"X-Real-IP": "192.168.1.20"})
    assert allowed_response.status_code == 200


def test_network_access_policy_ignores_forwarded_for_from_untrusted_proxy(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    store.set_config("TRUST_PROXY_HEADERS", True)
    store.set_config("TRUSTED_PROXY_CIDRS", ["127.0.0.1/32", "::1/128"])
    store.set_config("ALLOW_LAN_ACCESS", True)
    client = TestClient(app, client=("192.168.1.20", 50000))

    response = client.get("/healthz", headers={"X-Forwarded-For": "8.8.8.8"})

    assert response.status_code == 200


def test_bootstrap_login_create_key_and_status_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    state = client.get("/api/admin/bootstrap/state")
    assert state.json() == {"initialized": False}

    created_admin = client.post(
        "/api/admin/bootstrap/admin",
        json={"username": "admin", "password": "strong-password"},
    )
    assert created_admin.status_code == 201

    login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "strong-password"},
    )
    assert login.status_code == 200
    admin_token = login.json()["token"]

    created_key = client.post(
        "/api/admin/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "status reader", "scopes": ["read:status"]},
    )
    assert created_key.status_code == 201
    api_key = created_key.json()["key"]

    status_response = client.get(
        "/api/v1/status",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["name"] == "mijia-api-server"


def test_admin_config_audit_and_public_device_listing(tmp_path: Path) -> None:
    client, store = make_client_with_store(tmp_path)
    token = admin_token(client)
    store.replace_home_registry([{"id": "home-1", "name": "我的家", "uid": "user-1", "rooms": []}])
    store.upsert_devices(
        [
            {
                "did": "miot-device-1",
                "name": "客厅灯",
                "model": "yeelink.light.test",
                "home_id": "home-1",
                "room_id": None,
                "status": "online",
            }
        ]
    )

    config_response = client.put(
        "/api/admin/config/PUBLIC_BASE_URL",
        headers={"Authorization": f"Bearer {token}"},
        json={"value": "https://mijia.example.test"},
    )
    assert config_response.status_code == 200

    key_response = client.post(
        "/api/admin/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "reader", "scopes": ["read:status", "read:devices"]},
    )
    api_key = key_response.json()["key"]

    devices_response = client.get(
        "/api/v1/devices",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert devices_response.status_code == 200
    assert devices_response.json()["items"][0]["slug"]

    audit_response = client.get(
        "/api/admin/audit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert audit_response.status_code == 200


def test_status_requires_api_key_scope(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/v1/status")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "HTTP_ERROR"
