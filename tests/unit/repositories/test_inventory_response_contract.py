"""Complete inventory acknowledgements are required before destructive reconciliation."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.api_client import MijiaAPI
from mijiaAPI_V2.domain.exceptions import MijiaAPIException
from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from mijiaAPI_V2.repositories.device_repository import DeviceRepositoryImpl
from mijiaAPI_V2.repositories.home_repository import HomeRepositoryImpl
from mijiaAPI_V2.services.device_service import DeviceService
from mijiaAPI_V2.services.scene_service import SceneService
from server.config import ServerSettings
from server.mijia_runtime import MijiaRuntime
from server.store import ServerStore


@pytest.fixture
def credential():
    return Credential(
        user_id="123",
        service_token="fixture-token",
        ssecurity="fixture-security",
        c_user_id="fixture-user",
        device_id="fixture-device",
        user_agent="test",
        expires_at=datetime(2099, 1, 1),
    )


def homes():
    return {"code": 0, "result": {"homelist": [{"id": 1, "uid": 123, "name": "Home"}]}}


def page(items=None, *, more=False, cursor=None):
    result = {"device_info": [] if items is None else items, "has_more": more}
    if cursor is not None:
        result["max_did"] = cursor
    return {"code": 0, "result": result}


@pytest.fixture
def cache(tmp_path):
    return CacheManager(cache_dir=tmp_path / "cache")


@pytest.mark.parametrize(
    "response",
    [
        {"code": 0},
        {"code": 0, "result": {}},
        {"code": 0, "result": None},
        {"code": 0, "result": []},
        {"code": 0, "result": {"homelist": None}},
        {"code": 0, "result": {"homelist": {}}},
        {"code": 0, "result": {"homelist": [], "has_more": True}},
        {"code": 0, "result": {"homelist": [None]}},
        {"code": 0, "result": {"homelist": [{"uid": 123}]}},
        {"code": 0, "result": {"homelist": [{"id": 1}]}},
        {"code": 0, "result": {"homelist": [{"id": " ", "uid": 123}]}},
        {"code": 0, "result": {"homelist": [{"id": True, "uid": 123}]}},
    ],
)
def test_malformed_home_inventory_is_not_empty_or_cached(cache, credential, response):
    http = Mock()
    http.post.return_value = response
    with pytest.raises(MijiaAPIException):
        HomeRepositoryImpl(http, cache).get_all(credential)
    assert cache.get("homes", namespace=credential.user_id) is None


def test_explicit_empty_home_inventory_and_empty_cache_are_valid(cache, credential):
    http = Mock()
    http.post.return_value = {"code": 0, "result": {"homelist": []}}
    repository = HomeRepositoryImpl(http, cache)
    assert repository.get_all(credential) == []
    assert repository.get_all(credential) == []
    http.post.assert_called_once()


@pytest.mark.parametrize(
    "bad_cache",
    [
        {},
        [None],
        [{"id": "", "uid": "123"}],
        [{"id": "1", "name": "Home", "uid": "123"}, {"id": "1", "name": "Duplicate", "uid": "123"}],
    ],
)
def test_invalid_home_cache_is_replaced_by_validated_upstream(cache, credential, bad_cache):
    cache.set("homes", bad_cache, namespace=credential.user_id)
    http = Mock()
    http.post.return_value = homes()
    assert HomeRepositoryImpl(http, cache).get_all(credential)[0].id == "1"
    http.post.assert_called_once()
    assert cache.get("homes", namespace=credential.user_id)[0]["uid"] == "123"


def prepare_device_repository(http, cache, credential):
    cache.set(
        "homes",
        [{"id": "1", "uid": "123", "name": "Home", "rooms": []}],
        namespace=credential.user_id,
    )
    return DeviceRepositoryImpl(http, cache)


@pytest.mark.parametrize(
    "response",
    [
        {"code": 0},
        {"code": 0, "result": {}},
        {"code": 0, "result": None},
        {"code": 0, "result": {"device_info": None, "has_more": False}},
        {"code": 0, "result": {"device_info": {}, "has_more": False}},
        {"code": 0, "result": {"device_info": []}},
        page(more="false"),
        page(more=True, cursor="next"),
        page([{"did": "a"}], more=True),
        page([{"did": "a"}], more=True, cursor=" "),
        page([{}]),
        page([{"did": None}]),
        page([{"did": ""}]),
        page([{"did": True}]),
        page([{"did": "a", "home_id": "2"}]),
        page([{"did": "a", "home_id": None}]),
        page([{"did": "a"}, {"did": "a"}]),
    ],
)
def test_malformed_or_incomplete_device_inventory_is_not_empty_or_cached(
    cache, credential, response
):
    http = Mock()
    http.post.return_value = response
    repository = prepare_device_repository(http, cache, credential)
    with pytest.raises(MijiaAPIException):
        repository.get_all("1", credential)
    assert cache.get("devices:1", namespace=credential.user_id) is None


def test_complete_empty_device_inventory_and_cache_are_valid(cache, credential):
    http = Mock()
    http.post.return_value = page()
    repository = prepare_device_repository(http, cache, credential)
    assert repository.get_all("1", credential) == []
    assert repository.get_all("1", credential) == []
    http.post.assert_called_once()


def test_complete_two_page_inventory_uses_owner_and_progressing_cursor(cache, credential):
    http = Mock()
    http.post.side_effect = [
        page([{"did": "a", "home_id": 1}], more=True, cursor="a"),
        page([{"did": "b"}]),
    ]
    devices = prepare_device_repository(http, cache, credential).get_all("1", credential)
    assert [device.did for device in devices] == ["a", "b"]
    assert all(device.home_id == "1" for device in devices)
    requests = [call.kwargs["json"] for call in http.post.call_args_list]
    assert [request["start_did"] for request in requests] == ["", "a"]
    assert all(request["home_owner"] == 123 and request["home_id"] == 1 for request in requests)


def test_repeated_pagination_cursor_is_rejected_without_partial_cache(cache, credential):
    http = Mock()
    http.post.side_effect = [
        page([{"did": "a"}], more=True, cursor="a"),
        page([{"did": "b"}], more=True, cursor="a"),
    ]
    with pytest.raises(MijiaAPIException, match="分页"):
        prepare_device_repository(http, cache, credential).get_all("1", credential)
    assert http.post.call_count == 2
    assert cache.get("devices:1", namespace=credential.user_id) is None


def test_page_budget_allows_complete_inventory_on_last_permitted_page(
    cache, credential, monkeypatch
):
    monkeypatch.setattr("mijiaAPI_V2.repositories.device_repository.MAX_DEVICE_PAGES", 3)
    http = Mock()
    http.post.side_effect = [
        page([{"did": "a"}], more=True, cursor="a"),
        page([{"did": "b"}], more=True, cursor="b"),
        page([{"did": "c"}], more=False),
    ]
    devices = prepare_device_repository(http, cache, credential).get_all("1", credential)
    assert [device.did for device in devices] == ["a", "b", "c"]
    assert http.post.call_count == 3
    assert len(cache.get("devices:1", namespace=credential.user_id)) == 3


def test_unique_continuation_cursors_still_stop_at_page_budget(cache, credential, monkeypatch):
    monkeypatch.setattr("mijiaAPI_V2.repositories.device_repository.MAX_DEVICE_PAGES", 3)
    http = Mock()

    def post(path, **kwargs):
        number = http.post.call_count
        return page([{"did": f"device-{number}"}], more=True, cursor=f"cursor-{number}")

    http.post.side_effect = post
    with pytest.raises(MijiaAPIException, match="读取预算"):
        prepare_device_repository(http, cache, credential).get_all("1", credential)
    assert http.post.call_count == 3
    assert cache.get("devices:1", namespace=credential.user_id) is None


def test_wrong_home_device_cache_is_refetched(cache, credential):
    cache.set(
        "devices:1",
        [{"did": "other", "name": "Other", "model": "m", "home_id": "2"}],
        namespace=credential.user_id,
    )
    http = Mock()
    http.post.return_value = page([{"did": "correct", "name": "Correct", "model": "m"}])
    devices = prepare_device_repository(http, cache, credential).get_all("1", credential)
    assert devices[0].did == "correct" and devices[0].home_id == "1"
    http.post.assert_called_once()


def test_wrong_did_single_device_cache_cannot_authorize_another_device(cache, credential):
    cache.set(
        "device:target",
        {"did": "other", "name": "Other", "model": "m", "home_id": "1"},
        namespace=credential.user_id,
    )
    http = Mock()
    http.post.return_value = page([{"did": "target", "name": "Target", "model": "m"}])
    repository = prepare_device_repository(http, cache, credential)
    assert repository.get_by_id("target", credential).did == "target"
    http.post.assert_called_once()


def test_wrong_id_single_home_cache_cannot_authorize_another_home(cache, credential):
    cache.set(
        "home:1",
        {"id": "2", "uid": "123", "name": "Other", "rooms": []},
        namespace=credential.user_id,
    )
    http = Mock()
    http.post.return_value = homes()
    assert HomeRepositoryImpl(http, cache).get_by_id("1", credential).id == "1"
    http.post.assert_called_once()


def runtime_fixture(tmp_path, credential, home_response, device_response):
    settings = ServerSettings(
        data_dir=tmp_path,
        database_path=tmp_path / "server.sqlite3",
        credential_path=tmp_path / "credential.json",
        web_dist_dir=tmp_path / "no-dist",
    )
    store = ServerStore(settings)
    store.initialize()
    store.replace_home_registry([{"id": "1", "name": "Home", "uid": "123"}])
    store.upsert_devices(
        [{"did": "retained", "slug": "retained", "name": "Retained", "model": "m", "home_id": "1"}]
    )
    store.update_device("retained", {"access_mode": "write"})
    FileCredentialStore(settings.credential_path).save(credential)
    cache = CacheManager(cache_dir=tmp_path / "cache")
    http = Mock()

    def post(path, **kwargs):
        return home_response if path == "/v2/homeroom/gethome_merged" else device_response

    http.post.side_effect = post
    scene_repo = Mock()
    scene_repo.get_all.return_value = []
    specs = Mock()
    specs.get_spec.return_value = None
    sdk = MijiaAPI(
        credential,
        DeviceService(DeviceRepositoryImpl(http, cache), specs, cache),
        SceneService(scene_repo),
        home_repository=HomeRepositoryImpl(http, cache),
        cache_manager=cache,
    )
    runtime = MijiaRuntime(settings, store)
    runtime._api_client, runtime._api_client_credential_id = sdk, credential.user_id
    return runtime, store


@pytest.mark.parametrize("response", [{"code": 0}, {"code": 0, "result": {}}])
def test_malformed_home_response_preserves_real_runtime_registry(tmp_path, credential, response):
    runtime, store = runtime_fixture(tmp_path, credential, response, page())
    old = store.get_device("retained")
    with pytest.raises(MijiaAPIException):
        runtime._sync_all_unlocked(runtime._account_generation)
    assert store.get_device("retained")["id"] == old["id"]
    assert store.get_device("retained")["access_mode"] == "write"
    assert store.list_homes()[0]["id"] == "1"


@pytest.mark.parametrize(
    "response",
    [
        {"code": 0},
        {"code": 0, "result": {}},
        page([{"did": "partial"}], more=True),
        page([{"did": "bad", "home_id": "2"}]),
    ],
)
def test_malformed_device_response_warns_and_retains_write_grant(tmp_path, credential, response):
    runtime, store = runtime_fixture(tmp_path, credential, homes(), response)
    old = store.get_device("retained")
    result = runtime._sync_all_unlocked(runtime._account_generation)
    assert result["warnings"][0]["kind"] == "devices"
    assert store.get_device("retained")["id"] == old["id"]
    assert store.get_device("retained")["access_mode"] == "write"
    assert len(store.list_devices(include_hidden=True)) == 1


def test_exhausted_page_budget_retains_real_runtime_sqlite_snapshot(
    tmp_path, credential, monkeypatch
):
    monkeypatch.setattr("mijiaAPI_V2.repositories.device_repository.MAX_DEVICE_PAGES", 3)
    runtime, store = runtime_fixture(tmp_path, credential, homes(), page())
    old = store.get_device("retained")
    http = runtime._api_client._device_service._device_repo._http
    requests = []

    def post(path, **kwargs):
        if path == "/v2/homeroom/gethome_merged":
            return homes()
        number = len(requests) + 1
        requests.append(kwargs["json"])
        return page([{"did": f"partial-{number}"}], more=True, cursor=f"cursor-{number}")

    http.post.side_effect = post
    result = runtime._sync_all_unlocked(runtime._account_generation)
    assert len(requests) == 3
    assert result["warnings"][0]["kind"] == "devices"
    assert "保留上次同步数据" in result["warnings"][0]["message"]
    retained = store.get_device("retained")
    assert retained["id"] == old["id"] and retained["access_mode"] == "write"
    assert [device["did"] for device in store.list_devices(include_hidden=True)] == ["retained"]
    assert runtime._api_client._cache_manager.get("devices:1", namespace=credential.user_id) is None


def test_explicit_complete_empty_device_response_legitimately_prunes_old_registry(
    tmp_path, credential
):
    runtime, store = runtime_fixture(tmp_path, credential, homes(), page())
    assert runtime._sync_all_unlocked(runtime._account_generation)["warnings"] == []
    assert store.list_devices(include_hidden=True) == []
    assert store.list_homes()[0]["id"] == "1"


def test_explicit_empty_home_response_legitimately_prunes_all_old_inventory(tmp_path, credential):
    runtime, store = runtime_fixture(
        tmp_path, credential, {"code": 0, "result": {"homelist": []}}, page()
    )
    assert runtime._sync_all_unlocked(runtime._account_generation)["warnings"] == []
    assert store.list_devices(include_hidden=True) == []
    assert store.list_homes() == []
