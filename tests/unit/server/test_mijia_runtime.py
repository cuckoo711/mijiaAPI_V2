"""Tests for the Mijia runtime bridge."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mijiaAPI_V2.domain.models import Credential, Home
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from server.config import ServerSettings
from server.mijia_runtime import MijiaRuntime
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
