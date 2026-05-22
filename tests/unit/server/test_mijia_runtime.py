"""Tests for the Mijia runtime bridge."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mijiaAPI_V2.domain.models import Credential, Home
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from server.config import ServerSettings
from server.mijia_runtime import MijiaRuntime, SyncInProgressError
from server.store import ServerStore


def make_settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )


def make_credential(service_token: str, expires_at: datetime) -> Credential:
    return Credential(
        user_id="user-1",
        service_token=service_token,
        ssecurity="security",
        pass_token="pass-token",
        c_user_id="user-1",
        device_id="device-1",
        user_agent="agent",
        expires_at=expires_at,
    )


def test_runtime_refreshes_expiring_credential_before_creating_api(
    tmp_path: Path, monkeypatch: Any
) -> None:
    settings = make_settings(tmp_path)
    store = ServerStore(settings)
    store.initialize()
    FileCredentialStore(settings.credential_path).save(
        make_credential("old-token", datetime.now() + timedelta(minutes=5))
    )
    refreshed = make_credential("new-token", datetime.now() + timedelta(days=30))
    seen_tokens: list[str] = []

    class FakeAuth:
        def refresh_credential(self, credential: Credential) -> Credential:
            seen_tokens.append(credential.service_token)
            return refreshed

        def save_credential(self, credential: Credential) -> None:
            FileCredentialStore(settings.credential_path).save(credential)

    class FakeApi:
        def __init__(self, credential: Credential):
            self.credential = credential

        def refresh_cache(self, home_id: str | None = None) -> None:
            seen_tokens.append(self.credential.service_token)

    monkeypatch.setattr("server.mijia_runtime.create_auth_service", lambda **_: FakeAuth())
    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: FakeApi(credential),
    )

    MijiaRuntime(settings, store).refresh_cache()

    assert seen_tokens == ["old-token", "new-token"]
    assert FileCredentialStore(settings.credential_path).load().service_token == "new-token"


def test_sync_continues_when_one_home_scene_sync_fails(tmp_path: Path, monkeypatch: Any) -> None:
    settings = make_settings(tmp_path)
    store = ServerStore(settings)
    store.initialize()
    FileCredentialStore(settings.credential_path).save(
        make_credential("token", datetime.now() + timedelta(days=30))
    )

    class FakeApi:
        def get_homes(self) -> list[Home]:
            return [
                Home(id="home-ok", name="主家庭", uid="user-1", rooms=[]),
                Home(id="home-bad", name="异常家庭", uid="user-1", rooms=[]),
            ]

        def get_devices(self, home_id: str) -> list[Any]:
            return []

        def get_scenes(self, home_id: str) -> list[Any]:
            if home_id == "home-bad":
                raise RuntimeError("homeId is not home")
            return []

    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: FakeApi(),
    )

    result = MijiaRuntime(settings, store).sync_all()

    assert result["homes"] == 2
    assert result["devices"] == 0
    assert result["scenes"] == 0
    assert result["warnings"] == [
        {
            "kind": "scenes",
            "home_id": "home-bad",
            "home_name": "异常家庭",
            "message": "homeId is not home",
        }
    ]


def test_sync_all_rejects_second_request_while_running(
    tmp_path: Path, monkeypatch: Any
) -> None:
    settings = make_settings(tmp_path)
    store = ServerStore(settings)
    store.initialize()
    FileCredentialStore(settings.credential_path).save(
        make_credential("token", datetime.now() + timedelta(days=30))
    )
    started = threading.Event()
    release = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    class FakeApi:
        def get_homes(self) -> list[Home]:
            nonlocal call_count
            with call_lock:
                call_count += 1
                current_call = call_count
            if current_call == 1:
                started.set()
                release.wait(timeout=5)
            return []

        def get_devices(self, home_id: str) -> list[Any]:
            return []

        def get_scenes(self, home_id: str) -> list[Any]:
            return []

    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: FakeApi(),
    )

    runtime = MijiaRuntime(settings, store)
    errors: list[Exception] = []
    results: list[dict[str, Any]] = []

    def run_first_sync() -> None:
        try:
            results.append(runtime.sync_all())
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_first_sync)
    thread.start()
    assert started.wait(timeout=2)

    try:
        with pytest.raises(SyncInProgressError, match="同步正在进行中"):
            runtime.sync_all()
    finally:
        release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors == []
    assert results[0]["homes"] == 0
    assert call_count == 1
