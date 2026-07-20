"""Tests for the FastAPI server application."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import mijiaAPI_V2
from server.app import create_app
from server.config import ServerSettings
from server.mijia_runtime import SyncInProgressError
from server.store import ServerStore


def make_client(tmp_path: Path) -> TestClient:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
    )
    return TestClient(create_app(settings), client=("127.0.0.1", 50000))


def make_client_with_store(tmp_path: Path) -> tuple[TestClient, ServerStore]:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
    )
    store = ServerStore(settings)
    return TestClient(create_app(settings, store=store), client=("127.0.0.1", 50000)), store


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


def test_admin_auth_refresh_extends_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    token = admin_token(client)

    response = client.post(
        "/api/admin/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token"] == token
    assert payload["expires_at"]
    assert payload["admin"]["username"] == "admin"


def test_admin_change_password(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    token = admin_token(client)

    bad = client.post(
        "/api/admin/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "wrong-password", "new_password": "newer-password"},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "CURRENT_PASSWORD_INVALID"

    ok = client.post(
        "/api/admin/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "strong-password", "new_password": "newer-password"},
    )
    assert ok.status_code == 200
    assert ok.json()["username"] == "admin"

    still_valid = client.post(
        "/api/admin/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert still_valid.status_code == 200

    old_login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "strong-password"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "newer-password"},
    )
    assert new_login.status_code == 200


def test_healthz_is_public(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_bootstrap_state_includes_status_metadata(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/admin/bootstrap/state")

    assert response.status_code == 200
    assert response.json() == {
        "initialized": False,
        "status": "ok",
        "version": mijiaAPI_V2.__version__,
    }


def test_network_access_policy_allows_lan_only_after_switch_enabled(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
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
        web_dist_dir=tmp_path / "missing-web-dist",
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


def test_network_access_policy_ignores_forwarded_for_by_default(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    client = TestClient(app, client=("127.0.0.1", 50000))

    # TRUST_PROXY_HEADERS 默认关闭：伪造的公网 XFF 不应改变来源判定
    response = client.get("/healthz", headers={"X-Forwarded-For": "8.8.8.8"})
    assert response.status_code == 200


def test_network_access_policy_blocks_admin_api_from_public_source(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    store.set_config("TRUST_PROXY_HEADERS", True)
    store.set_config("TRUSTED_PROXY_CIDRS", ["127.0.0.1/32", "::1/128"])
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = {"X-Forwarded-For": "8.8.8.8"}

    state_response = client.get("/api/admin/bootstrap/state", headers=headers)
    assert state_response.status_code == 403
    assert state_response.json()["error"]["code"] == "NETWORK_ACCESS_DENIED"

    created_admin = client.post(
        "/api/admin/bootstrap/admin",
        headers=headers,
        json={"username": "admin", "password": "strong-password"},
    )
    assert created_admin.status_code == 403

    store.set_config("ALLOW_PUBLIC_ACCESS", True)
    # 即使开启公网访问，bootstrap 仍仅允许回环来源
    created_admin = client.post(
        "/api/admin/bootstrap/admin",
        headers=headers,
        json={"username": "admin", "password": "strong-password"},
    )
    assert created_admin.status_code == 403
    assert created_admin.json()["error"]["code"] == "BOOTSTRAP_LOCAL_ONLY"

    local_create = client.post(
        "/api/admin/bootstrap/admin",
        json={"username": "admin", "password": "strong-password"},
    )
    assert local_create.status_code == 201

    login = client.post(
        "/api/admin/auth/login",
        headers=headers,
        json={"username": "admin", "password": "strong-password"},
    )
    assert login.status_code == 200


def test_docs_routes_follow_runtime_config_without_restart(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    client = TestClient(app, client=("127.0.0.1", 50000))
    token = admin_token(client)
    auth_headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 404

    store.set_config("DOCS_ENABLED", True)

    unauth = client.get("/docs")
    assert unauth.status_code == 401
    assert unauth.json()["error"]["code"] == "DOCS_AUTH_REQUIRED"

    assert client.get("/docs", headers=auth_headers).status_code == 200
    assert client.get("/redoc", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/openapi.json", headers=auth_headers).status_code == 200

    store.set_config("DOCS_ENABLED", False)
    assert client.get("/docs", headers=auth_headers).status_code == 404
    store.set_config("OPENAPI_ENABLED", True)

    assert client.get("/docs", headers=auth_headers).status_code == 404
    assert client.get("/redoc", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 401
    assert client.get("/api/v1/openapi.json", headers=auth_headers).status_code == 200


def test_openapi_json_requires_auth_and_follows_network_policy(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "missing-web-dist",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    store.set_config("DOCS_ENABLED", True)
    store.set_config("TRUST_PROXY_HEADERS", True)
    store.set_config("TRUSTED_PROXY_CIDRS", ["127.0.0.1/32", "::1/128"])
    client = TestClient(app, client=("127.0.0.1", 50000))
    token = admin_token(client)
    auth_headers = {"Authorization": f"Bearer {token}"}
    public_headers = {"X-Forwarded-For": "8.8.8.8", **auth_headers}

    assert client.get("/api/v1/openapi.json").status_code == 401
    assert client.get("/api/v1/openapi.json", headers=auth_headers).status_code == 200

    denied = client.get("/api/v1/openapi.json", headers=public_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "NETWORK_ACCESS_DENIED"

    store.set_config("ALLOW_PUBLIC_ACCESS", True)
    allowed = client.get("/api/v1/openapi.json", headers=public_headers)
    assert allowed.status_code == 200
    assert allowed.json()["info"]["title"] == "Mijia API Server"


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


def test_admin_sync_reports_conflict_when_sync_is_running(tmp_path: Path) -> None:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    client = TestClient(app, client=("127.0.0.1", 50000))
    token = admin_token(client)

    class BusyRuntime:
        def sync_all(self) -> dict[str, Any]:
            raise SyncInProgressError("同步正在进行中，请稍后再试")

    app.state.runtime = BusyRuntime()

    response = client.post(
        "/api/admin/sync",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SYNC_IN_PROGRESS"


def test_bootstrap_login_create_key_and_status_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    state = client.get("/api/admin/bootstrap/state")
    assert state.json() == {
        "initialized": False,
        "status": "ok",
        "version": mijiaAPI_V2.__version__,
    }

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


def test_admin_app_info_returns_repository_metadata(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    token = admin_token(client)

    response = client.get(
        "/api/admin/app-info",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == mijiaAPI_V2.__version__
    assert payload["license"] == "MIT"
    assert payload["repository_url"].startswith("https://github.com/")
    assert payload["issues_url"].endswith("/issues")
    assert payload["releases_url"].endswith("/releases")


def test_admin_app_info_requires_auth(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/admin/app-info")

    assert response.status_code == 401


def test_admin_updates_check_delegates_to_checker(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client = make_client(tmp_path)
    token = admin_token(client)

    from server.updater import UpdateChecker

    # 用 stub 覆盖真实网络请求
    stub = UpdateChecker(current_version="0.0.0")

    def fake_check(force: bool = False) -> dict[str, Any]:
        return {
            "current_version": "0.0.0",
            "latest": {
                "latest_version": "9.9.9",
                "latest_tag": "v9.9.9",
                "published_at": "2026-07-05T07:00:00Z",
                "release_url": "https://example.com/r",
                "release_notes": "notes",
            },
            "update_available": True,
            "error": None,
            "checked_at": 0.0,
            "repository_url": stub.repository_url,
        }

    monkeypatch.setattr(stub, "check", fake_check)
    client.app.state.update_checker = stub

    response = client.get(
        "/api/admin/updates/check",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["update_available"] is True
    assert payload["latest"]["latest_tag"] == "v9.9.9"
