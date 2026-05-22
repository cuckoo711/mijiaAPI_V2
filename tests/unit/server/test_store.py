"""Tests for server-local storage and security behavior."""

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
    assert checks["admin_configured"]["status"] == "warn"
