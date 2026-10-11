"""Deterministic account lifecycle and background scheduling regressions."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from mijiaAPI_V2.domain.models import Credential, Home
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from server.config import ServerSettings
from server.mijia_runtime import AccountChangedError, LoginJobManager, MijiaRuntime
from server.store import ServerStore


def credential(user: str = "A", token: str = "old", *, expiring: bool = False) -> Credential:
    return Credential(
        user_id=user,
        service_token=token,
        ssecurity="security",
        pass_token="pass",
        c_user_id=user,
        device_id="device",
        user_agent="agent",
        expires_at=datetime.now() + (timedelta(minutes=5) if expiring else timedelta(days=30)),
    )


@pytest.fixture
def account(tmp_path: Path) -> tuple[ServerSettings, ServerStore, MijiaRuntime]:
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    store.initialize()
    FileCredentialStore(settings.credential_path).save(credential())
    store.replace_home_registry([{"id": "1", "name": "old home", "uid": "A", "rooms": []}])
    store.upsert_devices([{"did": "shared", "name": "lamp", "model": "model", "home_id": "1"}])
    store.update_device("shared", {"access_mode": "write", "alias": "local lamp"})
    store.upsert_scenes([{"scene_id": "scene", "name": "scene", "home_id": "1"}])
    store.update_scene("scene", {"executable": True})
    runtime = MijiaRuntime(settings, store)
    runtime._progress_cleanup_delay_seconds = 3600
    return settings, store, runtime


def run_thread(
    operation: Callable[[], Any],
) -> tuple[threading.Thread, list[BaseException], threading.Event]:
    errors: list[BaseException] = []
    done = threading.Event()

    def run() -> None:
        try:
            operation()
        except BaseException as error:
            errors.append(error)
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors, done


def change_account(runtime: MijiaRuntime, target: str | None) -> None:
    if target is None:
        runtime.delete_credential()
    else:
        runtime.commit_login_credential(credential(target, "login"), runtime.begin_login_attempt())


@pytest.mark.parametrize("target", [None, "B", "A"])
def test_inflight_refresh_cannot_restore_removed_or_relogged_account(
    account: Any,
    monkeypatch: pytest.MonkeyPatch,
    target: str | None,
) -> None:
    settings, store, runtime = account
    entered, release = threading.Event(), threading.Event()

    class Auth:
        def refresh_credential(self, old: Credential) -> Credential:
            entered.set()
            assert release.wait(5)
            return old.model_copy(update={"service_token": "stale-refresh"})

        def save_credential(self, new: Credential) -> None:
            FileCredentialStore(settings.credential_path).save(new)

    monkeypatch.setattr("server.mijia_runtime.create_auth_service", lambda **_: Auth())
    worker, errors, _ = run_thread(runtime.refresh_credential)
    assert entered.wait(2)
    mutation, mutation_errors, mutation_done = run_thread(lambda: change_account(runtime, target))
    try:
        assert mutation_done.wait(2), "account removal/login must not wait for refresh network IO"
        assert not mutation_errors
    finally:
        release.set()
        worker.join(3)
        mutation.join(3)
    assert len(errors) == 1 and isinstance(errors[0], AccountChangedError)
    saved = runtime.load_credential()
    if target is None:
        assert saved is None and store.list_homes() == []
    else:
        assert saved.user_id == target and saved.service_token == "login"


@pytest.mark.parametrize("target", [None, "B"])
def test_inflight_sync_cannot_repopulate_removed_or_switched_account(
    account: Any,
    monkeypatch: pytest.MonkeyPatch,
    target: str | None,
) -> None:
    _, store, runtime = account
    entered, release = threading.Event(), threading.Event()

    class Api:
        def refresh_cache(self) -> None:
            pass

        def clear_all_cache(self) -> None:
            pass

        def get_homes(self) -> list[Home]:
            entered.set()
            assert release.wait(5)
            return [Home(id="1", name="stale A home", uid="A", rooms=[])]

        def get_devices(self, home_id: str) -> list[Any]:
            return []

        def get_scenes(self, home_id: str, owner_uid: str | None = None) -> list[Any]:
            return []

    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: Api())
    runtime.sync_all()
    assert entered.wait(2)
    mutation, errors, done = run_thread(lambda: change_account(runtime, target))
    try:
        assert done.wait(2), "account removal/login must not wait for sync network IO"
        assert not errors
    finally:
        release.set()
        mutation.join(3)
    assert runtime._sync_lock.acquire(timeout=3)
    runtime._sync_lock.release()
    assert runtime.get_sync_progress()["status"] == "failed"
    assert store.list_homes() == []
    assert store.list_devices(include_hidden=True) == []
    assert store.list_scenes(include_hidden=True) == []


def test_switch_resets_permissions_and_same_account_relogin_preserves_them(account: Any) -> None:
    _, store, runtime = account
    change_account(runtime, "A")
    assert store.get_device("shared")["access_mode"] == "write"
    assert store.get_scene("scene")["executable"] is True
    change_account(runtime, "B")
    assert store.list_homes() == []
    assert store.list_devices(include_hidden=True) == []
    assert store.list_scenes(include_hidden=True) == []
    store.upsert_devices([{"did": "shared", "name": "lamp", "model": "model", "home_id": "1"}])
    store.upsert_scenes([{"scene_id": "scene", "name": "scene", "home_id": "1"}])
    assert store.get_device("shared")["access_mode"] == "read"
    assert store.get_scene("scene")["executable"] is False


class LoginProvider:
    def __init__(self, user: str) -> None:
        self.user = user
        self.entered, self.release, self.closed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self._client = SimpleNamespace(
            get=lambda _: SimpleNamespace(cookies={"serviceToken": f"token-{self.user}"}),
            close=self.closed.set,
        )

    def _get_location(self) -> dict[str, Any]:
        return {}

    def _get_qrcode_data(self, data: Any) -> dict[str, str]:
        return {"loginUrl": "https://example.test/qr", "qr": "qr", "lp": "poll"}

    def _long_poll_for_scan(self, url: str) -> dict[str, str]:
        self.entered.set()
        assert self.release.wait(5)
        return {"location": "callback", "userId": self.user, "ssecurity": "security"}

    def _generate_device_id(self) -> str:
        return "device"

    def _generate_user_agent(self) -> str:
        return "agent"

    def _calculate_expires_at(self, data: Any) -> datetime:
        return datetime.now() + timedelta(days=30)


def test_latest_login_wins_when_earlier_qr_completes_later(
    account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, runtime = account
    first, second = LoginProvider("B"), LoginProvider("C")
    providers = iter([first, second])
    monkeypatch.setattr("server.mijia_runtime.CredentialProvider", lambda _: next(providers))
    jobs = LoginJobManager(runtime._settings, runtime)
    first_job = jobs.start()
    assert first.entered.wait(2)
    second_job = jobs.start()
    assert second.entered.wait(2)
    try:
        assert jobs.get(first_job["id"])["status"] == "canceled"
        second.release.set()
        assert second.closed.wait(3)
        assert jobs.get(second_job["id"])["status"] == "success"
    finally:
        first.release.set()
        second.release.set()
    assert first.closed.wait(3)
    assert runtime.load_credential().user_id == "C"
    assert jobs.get(first_job["id"])["status"] == "canceled"


def test_remove_account_cancels_waiting_qr_and_discards_callback(
    account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store, runtime = account
    provider = LoginProvider("B")
    monkeypatch.setattr("server.mijia_runtime.CredentialProvider", lambda _: provider)
    jobs = LoginJobManager(runtime._settings, runtime)
    job = jobs.start()
    assert provider.entered.wait(2)
    try:
        runtime.delete_credential()
        assert jobs.get(job["id"])["status"] == "canceled"
    finally:
        provider.release.set()
    assert provider.closed.wait(3)
    assert runtime.load_credential() is None
    assert store.list_homes() == []


class FakeTimer:
    instances: list[FakeTimer] = []

    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.cancelled = False
        self.started = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def test_timer_rearms_after_every_check_even_without_credentials(
    account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, runtime = account
    runtime.delete_credential()
    FakeTimer.instances = []
    monkeypatch.setattr("server.mijia_runtime.threading.Timer", FakeTimer)
    runtime.start_credential_refresh_timer()
    runtime.start_credential_refresh_timer()
    assert len(FakeTimer.instances) == 1
    FakeTimer.instances[0].callback()
    assert len(FakeTimer.instances) == 2
    FakeTimer.instances[1].callback()
    assert len(FakeTimer.instances) == 3
    runtime.stop_credential_refresh_timer()
    FakeTimer.instances[2].callback()
    assert len(FakeTimer.instances) == 3
    assert FakeTimer.instances[2].cancelled


def test_stop_during_callback_and_restart_do_not_resurrect_old_timer(
    account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _, runtime = account
    FileCredentialStore(settings.credential_path).save(credential(expiring=True))
    entered, release = threading.Event(), threading.Event()

    class Auth:
        def refresh_credential(self, old: Credential) -> Credential:
            entered.set()
            assert release.wait(5)
            return credential(token="refreshed")

        def save_credential(self, new: Credential) -> None:
            FileCredentialStore(settings.credential_path).save(new)

    FakeTimer.instances = []
    monkeypatch.setattr("server.mijia_runtime.threading.Timer", FakeTimer)
    monkeypatch.setattr("server.mijia_runtime.create_auth_service", lambda **_: Auth())
    runtime.start_credential_refresh_timer()
    old = FakeTimer.instances[0]
    worker, errors, _ = run_thread(old.callback)
    assert entered.wait(2)
    try:
        runtime.stop_credential_refresh_timer()
        runtime.start_credential_refresh_timer()
        assert len(FakeTimer.instances) == 2
    finally:
        release.set()
        worker.join(3)
    assert not errors
    assert len(FakeTimer.instances) == 2
    old.callback()
    assert len(FakeTimer.instances) == 2
    runtime.stop_credential_refresh_timer()


def test_manual_sync_invalidates_inventory_cache_before_enumeration(
    account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store, runtime = account
    calls: list[str] = []

    class Api:
        def refresh_cache(self) -> None:
            calls.append("invalidate")

        def get_homes(self) -> list[Home]:
            assert calls == ["invalidate"]
            calls.append("enumerate")
            return []

    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: Api())
    runtime.sync_all()
    assert runtime._sync_lock.acquire(timeout=3)
    runtime._sync_lock.release()
    assert calls == ["invalidate", "enumerate"]
    assert runtime.get_sync_progress()["status"] == "completed"
    assert store.list_homes() == []


def test_failed_credential_write_keeps_previous_complete_file(
    account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _, runtime = account

    def interrupted_dump(payload: Any, handle: Any, **kwargs: Any) -> None:
        handle.write("{")
        raise OSError("simulated disk write failure")

    with monkeypatch.context() as scoped:
        scoped.setattr("mijiaAPI_V2.infrastructure.credential_store.json.dump", interrupted_dump)
        with pytest.raises(OSError, match="simulated"):
            FileCredentialStore(settings.credential_path).save(credential(token="new"))
    assert runtime.load_credential().service_token == "old"
    assert not list(settings.credential_path.parent.glob(".credential.json.*.tmp"))
