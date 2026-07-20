"""Tests for server-local storage and security behavior."""

import sqlite3
from pathlib import Path

import pytest

from server.config import ServerSettings
from server.store import (
    AuthenticationFailedError,
    BootstrapAlreadyCompletedError,
    ServerStore,
)


def make_settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )


def test_create_initial_admin_only_once(tmp_path: Path) -> None:
    store = ServerStore(make_settings(tmp_path))
    store.initialize()

    admin = store.create_initial_admin("admin", "strong-password")

    assert admin["username"] == "admin"
    assert store.has_admin()
    with pytest.raises(BootstrapAlreadyCompletedError):
        store.create_initial_admin("admin2", "strong-password")


def test_admin_login_creates_valid_session(tmp_path: Path) -> None:
    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    store.create_initial_admin("admin", "strong-password")

    session = store.authenticate_admin("admin", "strong-password")
    admin = store.validate_admin_session(session["token"])

    assert admin["username"] == "admin"
    assert session["token"].startswith("ms_")


def test_admin_session_refresh_extends_expiry(tmp_path: Path) -> None:
    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    store.create_initial_admin("admin", "strong-password")
    session = store.authenticate_admin("admin", "strong-password")

    refreshed = store.refresh_admin_session(session["token"])

    assert refreshed["token"] == session["token"]
    assert refreshed["expires_at"] >= session["expires_at"]
    assert refreshed["admin"]["username"] == "admin"


def test_change_admin_password_keeps_current_session(tmp_path: Path) -> None:
    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    store.create_initial_admin("admin", "strong-password")
    old_session = store.authenticate_admin("admin", "strong-password")
    other_session = store.authenticate_admin("admin", "strong-password")

    result = store.change_admin_password(
        old_session["admin"]["id"],
        "strong-password",
        "newer-password",
        keep_session_token=old_session["token"],
    )

    assert result["username"] == "admin"
    assert store.validate_admin_session(old_session["token"])["username"] == "admin"
    with pytest.raises(AuthenticationFailedError):
        store.validate_admin_session(other_session["token"])
    with pytest.raises(AuthenticationFailedError):
        store.authenticate_admin("admin", "strong-password")
    assert store.authenticate_admin("admin", "newer-password")["admin"]["username"] == "admin"


def test_change_admin_password_rejects_wrong_current(tmp_path: Path) -> None:
    from server.store import InvalidCurrentPasswordError

    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    admin = store.create_initial_admin("admin", "strong-password")

    with pytest.raises(InvalidCurrentPasswordError):
        store.change_admin_password(admin["id"], "wrong-password", "newer-password")


def test_reset_admin_password_revokes_sessions(tmp_path: Path) -> None:
    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    store.create_initial_admin("admin", "strong-password")
    session = store.authenticate_admin("admin", "strong-password")

    result = store.reset_admin_password("reset-password")

    assert result["username"] == "admin"
    with pytest.raises(AuthenticationFailedError):
        store.validate_admin_session(session["token"])
    assert store.authenticate_admin("admin", "reset-password")["token"].startswith("ms_")


def test_api_key_scope_is_enforced(tmp_path: Path) -> None:
    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    created = store.create_api_key("status reader", ["read:status"])

    verified = store.validate_api_key(created["key"], required_scope="read:status")

    assert verified["name"] == "status reader"
    with pytest.raises(AuthenticationFailedError):
        store.validate_api_key(created["key"], required_scope="write:devices")


def test_system_checks_include_sqlite_and_admin_state(tmp_path: Path) -> None:
    store = ServerStore(make_settings(tmp_path))
    store.initialize()

    checks = {item["key"]: item for item in store.system_checks()}

    assert checks["sqlite"]["status"] == "pass"
    assert checks["sqlite"]["label"] == "SQLite 数据库"
    assert checks["sqlite"]["description"] == "确认本地 SQLite 数据库可连接并能执行基础查询。"
    assert checks["admin_configured"]["status"] == "warn"
    assert checks["admin_configured"]["label"] == "管理员账号"
    assert checks["admin_configured"]["description"] == "确认管理台初始化管理员已经创建。"
    assert checks["docs_enabled"]["status"] == "info"
    assert checks["docs_enabled"]["message"] == "disabled"
    assert checks["openapi_enabled"]["message"] == "disabled"
    assert checks["public_base_url"]["status"] == "warn"
    assert checks["public_base_url"]["message"] == "PUBLIC_BASE_URL is not configured"

    store.set_config("DOCS_ENABLED", True)
    store.set_config("OPENAPI_ENABLED", True)
    store.set_config("PUBLIC_BASE_URL", "https://miapi.example.com")
    updated_checks = {item["key"]: item for item in store.system_checks()}

    assert updated_checks["docs_enabled"]["message"] == "enabled"
    assert updated_checks["openapi_enabled"]["message"] == "enabled"
    assert updated_checks["public_base_url"]["status"] == "pass"
    assert updated_checks["public_base_url"]["message"] == "https://miapi.example.com"


def test_validate_admin_session_uses_cache_on_hot_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连续 validate 同一个 token 时应命中缓存，只在首次做 PBKDF2。"""
    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    store.create_initial_admin("admin", "strong-password")
    session = store.authenticate_admin("admin", "strong-password")

    # 用 monkeypatch 计数 verify_secret 调用
    from server import store as store_module

    original_verify = store_module.verify_secret
    call_count = 0

    def counting_verify(secret: str, stored_hash: str) -> bool:
        nonlocal call_count
        call_count += 1
        return original_verify(secret, stored_hash)

    monkeypatch.setattr(store_module, "verify_secret", counting_verify)

    # 首次：走完整 PBKDF2 校验
    admin_1 = store.validate_admin_session(session["token"])
    assert admin_1["username"] == "admin"
    assert call_count == 1

    # 后续多次：应命中缓存，不再触发 verify
    for _ in range(5):
        store.validate_admin_session(session["token"])
    assert call_count == 1


def test_refresh_admin_session_invalidates_session_cache(tmp_path: Path) -> None:
    """session 续期时旧的缓存条目必须失效，避免拿到过期的 admin dict。"""
    store = ServerStore(make_settings(tmp_path))
    store.initialize()
    store.create_initial_admin("admin", "strong-password")
    session = store.authenticate_admin("admin", "strong-password")

    # 触发缓存
    store.validate_admin_session(session["token"])
    assert session["token"] in store._admin_session_cache  # type: ignore[attr-defined]

    # 续期后该 token 的缓存条目应被清掉
    store.refresh_admin_session(session["token"])
    assert session["token"] not in store._admin_session_cache  # type: ignore[attr-defined]


def test_get_config_map_caches_within_ttl_and_invalidates_on_set(tmp_path: Path) -> None:
    """get_config_map 在 TTL 内应复用缓存，set_config 后立即失效。"""
    store = ServerStore(make_settings(tmp_path))
    store.initialize()

    # 首次读取（此时空表）
    first = store.get_config_map()
    assert first == {}

    # 直接改数据库绕过 set_config，模拟"外部写入"
    with store._database.connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "INSERT INTO runtime_config(key, value, source, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("EXTERNAL_KEY", '"v"', "manual", "2026-07-05T00:00:00"),
        )

    # TTL 内应仍拿到旧的缓存
    cached = store.get_config_map()
    assert cached == first

    # 通过 store.set_config 主动写入应触发失效
    store.set_config("NEW_KEY", "value")
    updated = store.get_config_map()
    assert "NEW_KEY" in updated
    assert "EXTERNAL_KEY" in updated  # 失效后也顺便读到了外部写入


def test_initialize_migrates_legacy_admin_sessions_table(tmp_path: Path) -> None:
    """存量数据库缺少 token_prefix 列时，initialize 应先补列再建索引，不应报错。"""
    database_path = tmp_path / "server.sqlite3"

    # 模拟 v3.0.1 及以前的旧表结构：admin_sessions 没有 token_prefix 列。
    conn = sqlite3.connect(database_path)
    try:
        conn.execute(
            """
            CREATE TABLE admin_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                last_login_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE admin_sessions (
                token_hash TEXT PRIMARY KEY,
                admin_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(admin_id) REFERENCES admin_users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=database_path,
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    # 不应抛出 sqlite3.OperationalError: no such column: token_prefix
    store.initialize()

    # 迁移完成后，可以正常创建管理员并登录
    store.create_initial_admin("admin", "strong-password")
    session = store.authenticate_admin("admin", "strong-password")
    admin = store.validate_admin_session(session["token"])
    assert admin["username"] == "admin"


def test_clear_synced_registries_removes_homes_devices_scenes(tmp_path: Path) -> None:
    """清理同步数据后应彻底删除家庭/设备/场景，保留其他本地状态。"""
    store = ServerStore(make_settings(tmp_path))
    store.initialize()

    store.replace_home_registry(
        [
            {"id": "home-1", "name": "主家庭", "uid": "user", "rooms": []},
        ]
    )
    store.upsert_devices(
        [
            {
                "id": "dev-1",
                "did": "did-1",
                "name": "灯",
                "model": "xiaomi.light",
                "home_id": "home-1",
                "status": "online",
            }
        ]
    )
    store.upsert_scenes(
        [
            {
                "id": "scene-1",
                "scene_id": "scene-1",
                "name": "回家",
                "home_id": "home-1",
            }
        ]
    )

    # 顺便建一个 API Key，验证清理不会误删
    store.create_api_key("test", ["read:status"])

    result = store.clear_synced_registries()

    assert result == {"homes": 1, "devices": 1, "scenes": 1}
    assert store.list_homes() == []
    assert store.list_devices(include_hidden=True) == []
    assert store.list_scenes(include_hidden=True) == []
    # 其他本地状态保留
    assert len(store.list_api_keys()) == 1
