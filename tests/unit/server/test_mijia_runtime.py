"""Tests for the Mijia runtime bridge."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mijiaAPI_V2.domain.models import Credential, Home
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from server.config import ServerSettings
from server.mijia_runtime import MijiaRuntime, SyncInProgressError
from server.store import ServerStore


def _wait_for_sync_completion(runtime: MijiaRuntime, timeout: float = 5.0) -> dict[str, Any]:
    """轮询 sync progress 直到进入终态或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        progress = runtime.get_sync_progress()
        if progress is not None and progress["status"] in {"completed", "failed"}:
            return progress
        time.sleep(0.02)
    raise AssertionError("sync did not finish within timeout")


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

        def get_scenes(self, home_id: str, owner_uid: str | None = None) -> list[Any]:
            if home_id == "home-bad":
                raise RuntimeError("homeId is not home")
            return []

    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: FakeApi(),
    )

    runtime = MijiaRuntime(settings, store)
    started = runtime.sync_all()
    assert started["status"] == "started"

    progress = _wait_for_sync_completion(runtime)
    assert progress["status"] == "completed"
    assert progress["homes_total"] == 2
    assert progress["devices_found"] == 0
    assert progress["scenes_found"] == 0
    assert progress["warnings"] == [
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

        def get_scenes(self, home_id: str, owner_uid: str | None = None) -> list[Any]:
            return []

    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: FakeApi(),
    )

    runtime = MijiaRuntime(settings, store)
    first = runtime.sync_all()
    assert first["status"] == "started"
    assert started.wait(timeout=2)

    try:
        with pytest.raises(SyncInProgressError, match="同步正在进行中"):
            runtime.sync_all()
    finally:
        release.set()

    progress = _wait_for_sync_completion(runtime)
    assert progress["status"] == "completed"
    assert progress["homes_total"] == 0
    assert call_count == 1


def test_sync_progress_cleanup_does_not_clear_new_run(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """旧一次 sync 的延迟清理线程不应把后续新一轮 sync 的 progress 清空。"""
    settings = make_settings(tmp_path)
    store = ServerStore(settings)
    store.initialize()
    FileCredentialStore(settings.credential_path).save(
        make_credential("token", datetime.now() + timedelta(days=30))
    )

    class FakeApi:
        def get_homes(self) -> list[Home]:
            return []

        def get_devices(self, home_id: str) -> list[Any]:
            return []

        def get_scenes(self, home_id: str, owner_uid: str | None = None) -> list[Any]:
            return []

    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: FakeApi(),
    )

    runtime = MijiaRuntime(settings, store)

    # 第一次 sync 完成
    runtime.sync_all()
    first_progress = _wait_for_sync_completion(runtime)
    first_task_id = first_progress["task_id"]

    # 第二次 sync 完成，覆盖了 _sync_progress
    runtime.sync_all()
    second_progress = _wait_for_sync_completion(runtime)
    second_task_id = second_progress["task_id"]
    assert second_task_id != first_task_id

    # 模拟"第一次任务的 cleanup 线程到点"——按新逻辑，task_id 不匹配则不清空
    runtime._clear_progress_if_task(first_task_id)
    remaining = runtime.get_sync_progress()
    assert remaining is not None
    assert remaining["task_id"] == second_task_id

    # 模拟"第二次任务的 cleanup 线程到点"——task_id 匹配，清空
    runtime._clear_progress_if_task(second_task_id)
    assert runtime.get_sync_progress() is None


def test_api_client_is_reused_across_calls(tmp_path: Path, monkeypatch: Any) -> None:
    """同一用户凭据下，多次调用 _api() 应复用同一个 MijiaAPI，避免重建 HttpClient/L1 缓存。"""
    settings = make_settings(tmp_path)
    store = ServerStore(settings)
    store.initialize()
    FileCredentialStore(settings.credential_path).save(
        make_credential("token-a", datetime.now() + timedelta(days=30))
    )

    class FakeApi:
        instances: list["FakeApi"] = []

        def __init__(self) -> None:
            self.updated_with: list[Credential] = []
            FakeApi.instances.append(self)

        def update_credential(self, credential: Credential) -> None:
            self.updated_with.append(credential)

    FakeApi.instances = []
    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: FakeApi(),
    )

    runtime = MijiaRuntime(settings, store)
    api1 = runtime._api()
    api2 = runtime._api()
    assert api1 is api2
    assert len(FakeApi.instances) == 1

    # 凭据 token 刷新（同一 user_id）应通过 update_credential 复用实例
    FileCredentialStore(settings.credential_path).save(
        make_credential("token-b", datetime.now() + timedelta(days=30))
    )
    api3 = runtime._api()
    assert api3 is api1
    assert len(FakeApi.instances) == 1
    assert api1.updated_with[-1].service_token == "token-b"

    # 凭据被删除后再次调用应触发重建
    runtime.delete_credential()
    FileCredentialStore(settings.credential_path).save(
        make_credential("token-c", datetime.now() + timedelta(days=30))
    )
    api4 = runtime._api()
    assert api4 is not api1
    assert len(FakeApi.instances) == 2


def test_delete_credential_clears_synced_data_and_sdk_cache(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """删除米家凭据时应同时清理已同步的家庭/设备/场景以及 SDK 缓存。"""
    settings = make_settings(tmp_path)
    store = ServerStore(settings)
    store.initialize()
    FileCredentialStore(settings.credential_path).save(
        make_credential("token", datetime.now() + timedelta(days=30))
    )

    # 塞一些"已同步"的数据
    store.replace_home_registry(
        [{"id": "home-1", "name": "主家庭", "uid": "u", "rooms": []}]
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
        [{"id": "scene-1", "scene_id": "scene-1", "name": "回家", "home_id": "home-1"}]
    )

    class FakeApi:
        def __init__(self) -> None:
            self.cache_cleared = False

        def update_credential(self, credential: Credential) -> None:
            pass

        def clear_all_cache(self) -> None:
            self.cache_cleared = True

    fake_api = FakeApi()
    monkeypatch.setattr(
        "server.mijia_runtime.create_api_client",
        lambda credential, **_: fake_api,
    )

    runtime = MijiaRuntime(settings, store)
    # 先触发一次 _api() 让 runtime 缓存 fake_api
    runtime._api()

    result = runtime.delete_credential()

    # 返回的清理摘要
    assert result["cleared"] == {"homes": 1, "devices": 1, "scenes": 1}
    # 本地已同步数据全部清空
    assert store.list_homes() == []
    assert store.list_devices(include_hidden=True) == []
    assert store.list_scenes(include_hidden=True) == []
    # SDK 缓存被清
    assert fake_api.cache_cleared is True
    # 凭据文件被删
    assert not settings.credential_path.exists()
