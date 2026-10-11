"""First-run private-network setup used by Docker's loopback port publishing."""

import sqlite3
from argparse import Namespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import ServerSettings
from server.cli import init_command
from server.store import BootstrapAlreadyCompletedError, ServerStore


def setup_app(tmp_path: Path):
    dist = tmp_path / "web-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>setup</title>", encoding="utf-8")
    (dist / "assets" / "setup.js").write_text("console.log('setup')", encoding="utf-8")
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=dist,
    )
    store = ServerStore(settings)
    app = create_app(settings, store=store)
    return app, store


def test_opted_in_private_bootstrap_reaches_login_without_opening_public(tmp_path, monkeypatch):
    monkeypatch.setenv("MIJIA_BOOTSTRAP_ALLOW_PRIVATE", "1")
    app, store = setup_app(tmp_path)
    private = TestClient(app, client=("172.17.0.1", 50000))
    public = TestClient(app, client=("8.8.8.8", 50000))
    # Warm the config cache with the default closed policy before bootstrap.
    assert not store.get_config_map().get("ALLOW_LAN_ACCESS", False)
    for route in ("/", "/assets/setup.js", "/api/admin/bootstrap/state"):
        assert private.get(route).status_code == 200
        assert public.get(route).status_code == 403
    for route in ("/healthz", "/api/v1/status", "/api/admin/config"):
        assert private.get(route).status_code == 403
    payload = {"username": "admin", "password": "strong-password"}
    assert public.post("/api/admin/bootstrap/admin", json=payload).status_code == 403
    assert private.post("/api/admin/bootstrap/admin", json=payload).status_code == 201
    assert store.get_config_map()["ALLOW_LAN_ACCESS"] is True
    assert not store.get_config_map().get("ALLOW_PUBLIC_ACCESS", False)
    login = private.post("/api/admin/auth/login", json=payload)
    assert login.status_code == 200
    assert login.cookies.get("mijia_admin_session")
    assert login.cookies.get("mijia_csrf")
    assert private.get("/api/admin/config").status_code == 200
    assert public.get("/").status_code == 403
    assert public.get("/api/admin/bootstrap/state").status_code == 403
    assert public.post("/api/admin/auth/login", json=payload).status_code == 403


@pytest.mark.parametrize("flag", ["0", ""])
def test_private_first_run_is_closed_without_explicit_opt_in(tmp_path, monkeypatch, flag):
    monkeypatch.setenv("MIJIA_BOOTSTRAP_ALLOW_PRIVATE", flag)
    app, store = setup_app(tmp_path)
    client = TestClient(app, client=("172.17.0.1", 50000))
    assert client.get("/").status_code == 403
    assert client.get("/api/admin/bootstrap/state").status_code == 403
    assert (
        client.post(
            "/api/admin/bootstrap/admin", json={"username": "admin", "password": "strong-password"}
        ).status_code
        == 403
    )
    assert not store.has_admin()


def test_bootstrap_opt_in_does_not_bypass_disabled_lan_after_initialization(tmp_path, monkeypatch):
    monkeypatch.setenv("MIJIA_BOOTSTRAP_ALLOW_PRIVATE", "1")
    app, store = setup_app(tmp_path)
    store.create_initial_admin("admin", "strong-password")
    store.set_config("ALLOW_LAN_ACCESS", False)
    client = TestClient(app, client=("172.17.0.1", 50000))
    for path in ("/", "/assets/setup.js", "/api/admin/bootstrap/state", "/api/admin/config"):
        assert client.get(path).status_code == 403
    assert (
        client.post(
            "/api/admin/bootstrap/admin", json={"username": "other", "password": "strong-password"}
        ).status_code
        == 403
    )
    assert store.get_config_map()["ALLOW_LAN_ACCESS"] is False


def test_loopback_bootstrap_retains_closed_lan_default(tmp_path, monkeypatch):
    monkeypatch.setenv("MIJIA_BOOTSTRAP_ALLOW_PRIVATE", "1")
    app, store = setup_app(tmp_path)
    client = TestClient(app, client=("127.0.0.1", 50000))
    assert (
        client.post(
            "/api/admin/bootstrap/admin", json={"username": "admin", "password": "strong-password"}
        ).status_code
        == 201
    )
    assert not store.get_config_map().get("ALLOW_LAN_ACCESS", False)


def test_private_policy_and_admin_creation_are_atomic(tmp_path):
    _, store = setup_app(tmp_path)
    with store._database.connect() as connection:
        connection.execute("""
            CREATE TRIGGER reject_private_policy BEFORE INSERT ON runtime_config
            WHEN NEW.key = 'ALLOW_LAN_ACCESS'
            BEGIN SELECT RAISE(ABORT, 'simulated policy write failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        store.create_initial_admin("admin", "strong-password", allow_private_requests=True)
    assert not store.has_admin()
    assert not store.get_config_map().get("ALLOW_LAN_ACCESS", False)


def test_repeated_bootstrap_does_not_reenable_disabled_lan(tmp_path):
    _, store = setup_app(tmp_path)
    store.create_initial_admin("admin", "strong-password", allow_private_requests=True)
    store.set_config("ALLOW_LAN_ACCESS", False)
    with pytest.raises(BootstrapAlreadyCompletedError):
        store.create_initial_admin("another", "strong-password", allow_private_requests=True)
    assert store.get_config_map()["ALLOW_LAN_ACCESS"] is False


def test_cli_explicit_lan_flag_enables_existing_admin_docker_access(tmp_path, monkeypatch, capsys):
    _, store = setup_app(tmp_path)
    store.create_initial_admin("admin", "strong-password")
    store.set_config("ALLOW_LAN_ACCESS", False)
    monkeypatch.setattr("server.cli._settings", lambda: store.settings)
    init_command(Namespace(admin=None, password=None, allow_lan=True))
    store._invalidate_config_map_cache()
    assert store.get_config_map()["ALLOW_LAN_ACCESS"] is True
    assert not store.get_config_map().get("ALLOW_PUBLIC_ACCESS", False)
    assert store.authenticate_admin("admin", "strong-password")
    assert "initialized" in capsys.readouterr().out


def test_cli_without_lan_flag_preserves_closed_policy(tmp_path, monkeypatch):
    _, store = setup_app(tmp_path)
    monkeypatch.setattr("server.cli._settings", lambda: store.settings)
    init_command(Namespace(admin="admin", password="strong-password"))
    assert store.has_admin()
    store._invalidate_config_map_cache()
    assert not store.get_config_map().get("ALLOW_LAN_ACCESS", False)
