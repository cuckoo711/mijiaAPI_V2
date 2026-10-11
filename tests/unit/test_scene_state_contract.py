"""Shared-home ownership and complete live property read contracts."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.api_client import AsyncMijiaAPI, MijiaAPI
from mijiaAPI_V2.domain.exceptions import MijiaAPIException, ValidationError
from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.repositories.scene_repository import SceneRepositoryImpl
from mijiaAPI_V2.services.device_service import DeviceService
from mijiaAPI_V2.services.scene_service import SceneService


@pytest.fixture
def member():
    return Credential(
        user_id="member",
        service_token="token",
        ssecurity="security",
        c_user_id="member",
        device_id="client",
        user_agent="agent",
        expires_at=datetime(2099, 1, 1),
    )


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"code": 0},
        {"code": 0, "result": None},
        {"code": 0, "result": {}},
        {"code": 0, "result": {"manual_scene_info_list": None}},
        {"code": 0, "result": {"manual_scene_info_list": {}}},
        {"code": 0, "result": {"manual_scene_info_list": [None]}},
        {"code": 0, "result": {"manual_scene_info_list": [{"scene_id": ""}]}},
        {"code": 0, "result": {"manual_scene_info_list": [{"scene_id": None}]}},
        {"code": 0, "result": {"manual_scene_info_list": [{"scene_id": True}]}},
        {"code": 0, "result": {"manual_scene_info_list": [{"scene_id": "a"}, {"scene_id": "a"}]}},
        {"code": False, "result": {"manual_scene_info_list": []}},
        {"code": -1, "result": {"manual_scene_info_list": []}},
        {"result": {"manual_scene_info_list": []}},
    ],
)
def test_invalid_scene_snapshot_is_not_an_empty_success(member, response):
    http = Mock()
    http.post.return_value = response
    with pytest.raises(MijiaAPIException):
        SceneRepositoryImpl(http).get_all("home", member, owner_uid="owner")


def test_shared_owner_survives_sdk_enumeration_and_execution(member):
    http = Mock()
    http.post.side_effect = [
        {"code": 0, "result": {"manual_scene_info_list": [{"scene_id": 42, "name": "welcome"}]}},
        {"code": 0},
    ]
    api = MijiaAPI(member, Mock(), SceneService(SceneRepositoryImpl(http)))
    scene = api.get_scenes("home", owner_uid="owner")[0]
    assert scene.owner_uid == "owner"
    assert api.execute_scene(scene.scene_id, scene.home_id, owner_uid=scene.owner_uid)
    assert [call.kwargs["json"]["owner_uid"] for call in http.post.call_args_list] == [
        "owner",
        "owner",
    ]


@pytest.mark.asyncio
async def test_async_sdk_preserves_shared_owner_and_legacy_calls(member):
    service = Mock()
    service.execute_scene.return_value = True
    api = AsyncMijiaAPI(member, Mock(), service)
    assert await api.execute_scene("scene", "home", owner_uid="owner")
    service.execute_scene.assert_called_once_with("scene", "home", member, owner_uid="owner")
    service.reset_mock()
    assert await api.execute_scene("scene", "home")
    service.execute_scene.assert_called_once_with("scene", "home", member)


def test_read_groups_all_properties_and_matches_out_of_order_results(member):
    repo = Mock()
    service = DeviceService(repo, Mock(), Mock())
    requests = [{"did": "lamp", "siid": 2, "piid": index} for index in range(1, 114)]

    def read(batch, credential):
        return [{**request, "code": 0, "value": request["piid"]} for request in reversed(batch)]

    repo.batch_get_properties.side_effect = read
    result = service.batch_get_properties(requests, member)
    assert [len(call.args[0]) for call in repo.batch_get_properties.call_args_list] == [50, 50, 13]
    assert [item["value"] for item in result] == list(range(1, 114))


@pytest.mark.parametrize(
    "response",
    [
        [],
        None,
        {},
        [{"did": "other", "siid": 2, "piid": 1, "code": 0, "value": True}],
        [{"did": "lamp", "siid": 2, "piid": 3, "code": 0, "value": True}],
        [{"siid": 2, "piid": 1, "code": 0, "value": True}],
        [{"did": "lamp", "siid": 2, "piid": 1, "value": True}],
        [{"did": "lamp", "siid": 2, "piid": 1, "code": False, "value": True}],
        [{"did": "lamp", "siid": 2, "piid": 1, "code": 0}],
    ],
)
def test_invalid_read_response_never_becomes_a_successful_state(member, response):
    repo = Mock()
    repo.batch_get_properties.return_value = response
    service = DeviceService(repo, Mock(), Mock())
    with pytest.raises(MijiaAPIException):
        service.batch_get_properties([{"did": "lamp", "siid": 2, "piid": 1}], member)


def test_read_keeps_device_error_and_explicit_null_without_fabricating_values(member):
    repo = Mock()
    repo.batch_get_properties.return_value = [
        {"did": "lamp", "siid": 2, "piid": 1, "code": -704042011},
        {"did": "lamp", "siid": 2, "piid": 2, "code": 0, "value": None},
    ]
    service = DeviceService(repo, Mock(), Mock())
    result = service.batch_get_properties(
        [
            {"did": "lamp", "siid": 2, "piid": 1},
            {"did": "lamp", "siid": 2, "piid": 2},
        ],
        member,
    )
    assert result[0]["code"] == -704042011 and "value" not in result[0]
    assert result[1]["value"] is None


def test_read_validates_all_requests_before_first_dispatch_and_handles_duplicates(member):
    repo = Mock()
    service = DeviceService(repo, Mock(), Mock())
    valid = {"did": "lamp", "siid": 2, "piid": 1}
    with pytest.raises(ValidationError):
        service.batch_get_properties([valid] * 51 + [{**valid, "piid": True}], member)
    repo.batch_get_properties.assert_not_called()
    repo.batch_get_properties.return_value = [{**valid, "code": 0, "value": True}]
    assert len(service.batch_get_properties([valid, valid], member)) == 2
    repo.batch_get_properties.assert_called_once_with([valid], member)
