"""Runtime shared-family scene and live property read regression tests."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.api_client import MijiaAPI
from mijiaAPI_V2.domain.exceptions import MijiaAPIException
from mijiaAPI_V2.domain.models import (
    Credential,
    Device,
    DeviceProperty,
    Home,
    PropertyAccess,
    PropertyType,
)
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from mijiaAPI_V2.repositories.interfaces import DeviceSpec
from mijiaAPI_V2.repositories.scene_repository import SceneRepositoryImpl
from mijiaAPI_V2.services.device_service import DeviceService
from mijiaAPI_V2.services.scene_service import SceneService
from server.config import ServerSettings
from server.mijia_runtime import LoginJob, LoginJobManager, MijiaRuntime
from server.store import ServerStore


@pytest.fixture
def setup(tmp_path):
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
    )
    store = ServerStore(settings)
    store.initialize()
    credential = Credential(
        user_id="member",
        service_token="token",
        ssecurity="security",
        c_user_id="member",
        device_id="client",
        user_agent="agent",
        expires_at=datetime(2099, 1, 1),
    )
    FileCredentialStore(settings.credential_path).save(credential)
    home = Home(id="shared-home", name="shared family", uid="home-owner", rooms=[])
    store.replace_home_registry([home.model_dump()])
    runtime = MijiaRuntime(settings, store)
    runtime._progress_cleanup_delay_seconds = 3600
    return store, runtime, credential, home


def test_shared_owner_round_trip_from_home_to_saved_scene_to_execution(setup, monkeypatch):
    store, runtime, credential, home = setup
    http = Mock()
    http.post.side_effect = [
        {"code": 0, "result": {"manual_scene_info_list": [{"scene_id": 42, "name": "welcome"}]}},
        {"code": 0},
    ]
    api = MijiaAPI(credential, Mock(), SceneService(SceneRepositoryImpl(http)))
    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: api)
    scenes = runtime._scene_dicts(api, home)
    assert scenes[0]["owner_uid"] == home.uid
    store.upsert_scenes(scenes)
    scene = store.update_scene(scenes[0]["id"], {"executable": True})
    assert runtime.execute_scene(
        scene["id"],
        internal_only=True,
        authorize=lambda current: current["id"] == scene["id"],
    ) == {"success": True}
    assert [call.kwargs["json"]["owner_uid"] for call in http.post.call_args_list] == [
        home.uid,
        home.uid,
    ]


def test_legacy_scene_uses_synced_home_owner_when_raw_owner_is_missing(setup, monkeypatch):
    store, runtime, credential, home = setup
    store.upsert_scenes([{"scene_id": "legacy", "name": "legacy", "home_id": home.id}])
    store.update_scene("legacy", {"executable": True})
    http = Mock()
    http.post.return_value = {"code": 0}
    api = MijiaAPI(credential, Mock(), SceneService(SceneRepositoryImpl(http)))
    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: api)
    assert runtime.execute_scene("legacy") == {"success": True}
    assert http.post.call_args.kwargs["json"]["owner_uid"] == home.uid


def test_malformed_scene_snapshot_preserves_previous_scene_and_authorization(setup, monkeypatch):
    store, runtime, credential, home = setup
    store.upsert_scenes([{"scene_id": "old", "name": "old", "home_id": home.id}])
    store.update_scene("old", {"executable": True})
    http = Mock()
    http.post.return_value = {"code": 0, "result": {}}
    homes = Mock()
    homes.get_all.return_value = [home]
    devices = Mock()
    devices.get_devices.return_value = []
    api = MijiaAPI(
        credential, devices, SceneService(SceneRepositoryImpl(http)), home_repository=homes
    )
    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: api)
    runtime.sync_all()
    assert runtime._sync_lock.acquire(timeout=3)
    runtime._sync_lock.release()
    progress = runtime.get_sync_progress()
    assert progress["status"] == "completed"
    assert progress["warnings"][0]["kind"] == "scenes"
    assert store.get_scene("old")["executable"] is True


@pytest.mark.parametrize("spec_source", ["stored", "dynamic"])
def test_live_state_reads_all_readable_properties_and_preserves_errors(
    setup, monkeypatch, spec_source
):
    store, runtime, credential, home = setup
    spec = DeviceSpec(
        model="lamp.model",
        name="lamp",
        properties=[
            DeviceProperty(
                siid=2,
                piid=index,
                name=f"property-{index}",
                type=PropertyType.INT,
                access=PropertyAccess.WRITE_ONLY if index <= 31 else PropertyAccess.READ_ONLY,
            )
            for index in range(1, 114)
        ],
    )
    device_data = {"did": "lamp", "name": "lamp", "model": spec.model, "home_id": home.id}
    if spec_source == "stored":
        device_data["spec"] = spec.model_dump(mode="json")
    store.upsert_devices([device_data])
    device = store.get_device("lamp")
    repo, specs = Mock(), Mock()
    specs.get_spec.return_value = spec

    def live_read(requests, credential):
        return [
            (
                {**request, "code": -704042011}
                if request["piid"] == 113
                else {**request, "code": 0, "value": request["piid"]}
            )
            for request in reversed(requests)
        ]

    repo.batch_get_properties.side_effect = live_read
    api = MijiaAPI(credential, DeviceService(repo, specs, Mock()), Mock())
    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: api)
    results = runtime.get_device_state(
        device["id"],
        internal_only=True,
        authorize=lambda current: current["id"] == device["id"],
    )
    assert len(results) == 82
    assert [len(call.args[0]) for call in repo.batch_get_properties.call_args_list] == [50, 32]
    assert [item["piid"] for item in results] == list(range(32, 114))
    assert results[-1]["code"] == -704042011 and "value" not in results[-1]
    assert specs.get_spec.call_count == (1 if spec_source == "dynamic" else 0)


def test_missing_spec_reports_unavailable_state_instead_of_empty_success(setup, monkeypatch):
    store, runtime, credential, home = setup
    store.upsert_devices([{"did": "lamp", "name": "lamp", "model": "unknown", "home_id": home.id}])
    service = Mock()
    service.get_device_spec.return_value = None
    api = MijiaAPI(credential, service, Mock())
    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: api)
    with pytest.raises(RuntimeError, match="规格不可用"):
        runtime.get_device_state("lamp")
    service.batch_get_properties.assert_not_called()


def test_access_values_accept_enums_and_explicit_read_flags(setup):
    _, runtime, _, _ = setup
    requests = runtime._readable_property_requests(
        "lamp",
        {
            "properties": [
                {"siid": 2, "piid": 1, "access": PropertyAccess.READ_WRITE},
                {"siid": 2, "piid": 2, "access": ["read", "notify"]},
                {"siid": 2, "piid": 3, "access": "write"},
                {"siid": 2, "piid": 4, "access": "not-readable"},
            ]
        },
    )
    assert [item["piid"] for item in requests] == [1, 2]


def test_device_enum_status_is_saved_in_the_public_lowercase_contract(setup):
    _, runtime, _, home = setup
    api = Mock()
    api.get_device_spec.return_value = None
    api.get_devices.return_value = [
        Device(
            did="lamp",
            name="lamp",
            model="lamp.model",
            home_id=home.id,
            status="online",
        )
    ]
    assert runtime._device_dicts(api, home)[0]["status"] == "online"


def test_sync_failure_warning_progress_and_audit_do_not_copy_upstream_secrets(setup, monkeypatch):
    store, runtime, _, home = setup
    secret = "upstream-secret-ticket"
    error = MijiaAPIException(
        f"https://account.xiaomi.com/callback?serviceToken={secret}", code=401
    )
    warning = runtime._sync_warning("scenes", home, error)
    assert warning["error_type"] == "MijiaAPIException" and warning["code"] == 401
    assert secret not in repr(warning)
    api = Mock()
    api.get_homes.side_effect = error
    monkeypatch.setattr("server.mijia_runtime.create_api_client", lambda *args, **kwargs: api)
    runtime.sync_all()
    assert runtime._sync_lock.acquire(timeout=3)
    runtime._sync_lock.release()
    assert runtime.get_sync_progress()["status"] == "failed"
    assert secret not in repr(runtime.get_sync_progress())
    assert secret not in repr(store.list_audit(action="mijia.sync.completed"))


def test_login_failure_does_not_expose_callback_or_token_in_job(setup):
    _, runtime, _, _ = setup
    jobs = LoginJobManager(runtime._settings, runtime)
    attempt = runtime.begin_login_attempt()
    job = LoginJob(id="test", qr_url="qr", login_url="login", poll_url="poll", attempt=attempt)
    jobs._jobs[job.id] = job
    provider = Mock()
    provider._long_poll_for_scan.side_effect = RuntimeError(
        "https://account.xiaomi.com/callback?serviceToken=must-not-leak"
    )
    jobs._wait_and_save(provider, job.id)
    result = jobs.get(job.id)
    assert result["status"] == "failed"
    assert "must-not-leak" not in repr(result)
    provider._client.close.assert_called_once()
