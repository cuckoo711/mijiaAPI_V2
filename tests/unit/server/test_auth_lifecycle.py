"""Revocation must win over in-flight validation and shared-store caches."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, current_thread

import pytest

from server.config import ServerSettings
from server.store import (
    AuthenticationFailedError,
    BootstrapAlreadyCompletedError,
    ServerStore,
    utc_now,
)


def make_store(path: Path) -> ServerStore:
    store = ServerStore(
        ServerSettings(
            data_dir=path,
            database_path=path / "server.sqlite3",
            credential_path=path / "credential.json",
        )
    )
    store.initialize()
    return store


@pytest.mark.parametrize("mutation", ["disable", "delete", "rotate"])
def test_revocation_wins_over_inflight_cache_fill(tmp_path, monkeypatch, mutation):
    store = make_store(tmp_path)
    key = store.create_api_key("controller", ["read:status"])
    loaded, release = Event(), Event()
    original = store._load_api_key_record

    def delayed_load(*args):
        result = original(*args)
        loaded.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(store, "_load_api_key_record", delayed_load)
    with ThreadPoolExecutor(max_workers=1) as pool:
        validating = pool.submit(store.validate_api_key, key["key"])
        try:
            assert loaded.wait(5)
            if mutation == "disable":
                store.update_api_key_status(key["id"], False)
            elif mutation == "delete":
                store.delete_api_key(key["id"])
            else:
                store.rotate_api_key(key["id"])
        finally:
            release.set()
        with pytest.raises(AuthenticationFailedError):
            validating.result(timeout=5)
    with pytest.raises(AuthenticationFailedError):
        store.validate_api_key(key["key"])
    assert key["key"] not in store._api_key_cache


@pytest.mark.parametrize("mutation", ["disable", "delete", "rotate"])
def test_another_store_cannot_keep_using_revoked_key(tmp_path, mutation):
    reader, writer = make_store(tmp_path), make_store(tmp_path)
    key = reader.create_api_key("shared", ["read:status"])
    reader.validate_api_key(key["key"])
    if mutation == "disable":
        writer.update_api_key_status(key["id"], False)
    elif mutation == "delete":
        writer.delete_api_key(key["id"])
    else:
        writer.rotate_api_key(key["id"])
    with pytest.raises(AuthenticationFailedError):
        reader.validate_api_key(key["key"])


def test_rotation_preserves_policy_and_revokes_predecessor(tmp_path):
    store = make_store(tmp_path)
    old = store.create_api_key(
        "controller",
        ["read:devices", "write:devices"],
        {"devices": ["lamp"]},
        utc_now() + timedelta(days=1),
    )
    store.validate_api_key(old["key"])
    replacement = store.rotate_api_key(old["id"])
    for field in ("name", "scopes", "resource_policy", "expires_at"):
        assert replacement[field] == old[field]
    assert replacement["key"] != old["key"]
    assert store.validate_api_key(replacement["key"])["resource_policy"] == {"devices": ["lamp"]}
    with pytest.raises(AuthenticationFailedError):
        store.validate_api_key(old["key"])
    with pytest.raises(ValueError, match="停用"):
        store.rotate_api_key(old["id"])


def test_rotation_rolls_back_replacement_if_revocation_fails(tmp_path):
    store = make_store(tmp_path)
    old = store.create_api_key("controller", ["read:status"])
    with store._database.connect() as conn:
        conn.execute(
            """CREATE TRIGGER fail_revoke BEFORE UPDATE OF is_active ON api_keys
                        WHEN NEW.is_active = 0 BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"""
        )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        store.rotate_api_key(old["id"])
    assert len(store.list_api_keys()) == 1
    assert store.validate_api_key(old["key"])["id"] == old["id"]


def test_expired_rotation_requires_new_expiry(tmp_path):
    store = make_store(tmp_path)
    old = store.create_api_key("expired", ["read:status"])
    with store._database.connect() as conn:
        conn.execute(
            "UPDATE api_keys SET expires_at = ? WHERE id = ?",
            ((utc_now() - timedelta(days=1)).isoformat(), old["id"]),
        )
    with pytest.raises(ValueError, match="有效期"):
        store.rotate_api_key(old["id"])
    assert len(store.list_api_keys()) == 1
    replacement = store.rotate_api_key(old["id"], replace_expiry=True, expires_at=None)
    assert replacement["expires_at"] is None
    assert store.validate_api_key(replacement["key"])


def test_login_failures_survive_rollback_and_lock_account(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    store.create_initial_admin("admin", "strong-password")
    for attempt in range(5):
        with pytest.raises(AuthenticationFailedError):
            store.authenticate_admin("admin", "incorrect-password")
        with store._database.connect() as conn:
            row = conn.execute("SELECT failed_attempts, locked_until FROM admin_users").fetchone()
        assert row["failed_attempts"] == (attempt + 1) % 5
    assert row["locked_until"]
    with pytest.raises(AuthenticationFailedError, match="locked"):
        store.authenticate_admin("admin", "strong-password")
    from server import store_auth

    future = utc_now() + timedelta(minutes=16)
    monkeypatch.setattr(store_auth, "utc_now", lambda: future)
    assert store.authenticate_admin("admin", "strong-password")


def test_concurrent_bootstrap_creates_only_one_admin(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    barrier = Barrier(2)
    original = store.has_admin

    def checked_together():
        value = original()
        barrier.wait(timeout=5)
        return value

    monkeypatch.setattr(store, "has_admin", checked_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [
            pool.submit(store.create_initial_admin, name, "strong-password")
            for name in ("first", "second")
        ]
        results = []
        for job in jobs:
            try:
                results.append(job.result(timeout=5))
            except BootstrapAlreadyCompletedError:
                pass
    assert len(results) == 1
    with store._database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0] == 1


def test_logout_invalidates_another_store_session_cache(tmp_path):
    reader, writer = make_store(tmp_path), make_store(tmp_path)
    reader.create_initial_admin("admin", "strong-password")
    session = reader.authenticate_admin("admin", "strong-password")
    reader.validate_admin_session(session["token"])
    assert writer.revoke_admin_session(session["token"])
    with pytest.raises(AuthenticationFailedError):
        reader.validate_admin_session(session["token"])


@pytest.mark.parametrize("separate_store", [False, True])
@pytest.mark.parametrize("mutation", ["logout", "password-reset"])
def test_revocation_during_cold_session_verification_cannot_fill_cache(
    tmp_path,
    monkeypatch,
    separate_store,
    mutation,
):
    reader = make_store(tmp_path)
    writer = make_store(tmp_path) if separate_store else reader
    reader.create_initial_admin("admin", "strong-password")
    session = reader.authenticate_admin("admin", "strong-password")
    token = session["token"]
    verified, release = Event(), Event()
    requesting_thread = current_thread()
    from server import store_auth

    original_verify = store_auth.verify_secret

    def delayed_verify(value, stored_hash):
        valid = original_verify(value, stored_hash)
        if value == token and current_thread() is not requesting_thread:
            verified.set()
            assert release.wait(5)
        return valid

    monkeypatch.setattr(store_auth, "verify_secret", delayed_verify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        validating = pool.submit(reader.validate_admin_session, token)
        try:
            assert verified.wait(5)
            if mutation == "logout":
                assert writer.revoke_admin_session(token)
            else:
                writer.reset_admin_password("new-strong-password")
        finally:
            release.set()
        with pytest.raises(AuthenticationFailedError):
            validating.result(timeout=5)
    assert token not in reader._admin_session_cache
    with pytest.raises(AuthenticationFailedError):
        reader.validate_admin_session(token)


def test_session_generation_blocks_cache_fill_after_final_active_read(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    store.create_initial_admin("admin", "strong-password")
    token = store.authenticate_admin("admin", "strong-password")["token"]
    active_read, release = Event(), Event()
    original = store._require_active_admin_session

    def delayed_active_read(token_hash):
        expires_at = original(token_hash)
        active_read.set()
        assert release.wait(5)
        return expires_at

    monkeypatch.setattr(store, "_require_active_admin_session", delayed_active_read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        validating = pool.submit(store.validate_admin_session, token)
        try:
            assert active_read.wait(5)
            assert store.revoke_admin_session(token)
        finally:
            release.set()
        with pytest.raises(AuthenticationFailedError):
            validating.result(timeout=5)
    assert token not in store._admin_session_cache
