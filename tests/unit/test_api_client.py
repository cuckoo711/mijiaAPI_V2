"""MijiaAPI 顶层客户端的单元测试。

主要覆盖 v3.1.2 引入的：控制设备/调用操作时若传入 ``home_id`` 应跳过 ``get_by_id``
的家庭反查，避免遍历所有家庭。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from mijiaAPI_V2.api_client import MijiaAPI
from mijiaAPI_V2.domain.models import Credential


@pytest.fixture
def credential() -> Credential:
    return Credential(
        user_id="user-1",
        service_token="token",
        ssecurity="security",
        pass_token="pass",
        c_user_id="user-1",
        device_id="device",
        user_agent="ua",
        expires_at=datetime(2099, 1, 1),
    )


@pytest.fixture
def mock_device_service() -> MagicMock:
    service = MagicMock()
    service.set_device_property.return_value = True
    service.call_device_action.return_value = "ok"
    service.batch_control_devices.side_effect = lambda reqs, _cred: [
        {"code": 0} for _ in reqs
    ]
    service.get_device_by_id.return_value = MagicMock(home_id="home-fallback")
    return service


@pytest.fixture
def mock_cache_manager() -> MagicMock:
    return MagicMock()


@pytest.fixture
def api(credential, mock_device_service, mock_cache_manager) -> MijiaAPI:
    return MijiaAPI(
        credential=credential,
        device_service=mock_device_service,
        scene_service=MagicMock(),
        cache_manager=mock_cache_manager,
    )


def test_control_device_with_known_home_id_skips_lookup(
    api: MijiaAPI, mock_device_service: MagicMock, mock_cache_manager: MagicMock
) -> None:
    api.control_device("dev-1", 2, 1, True, home_id="home-123")

    mock_device_service.get_device_by_id.assert_not_called()
    mock_cache_manager.invalidate_pattern.assert_called_once_with(
        "user-1:devices:home-123"
    )


def test_control_device_without_home_id_falls_back_to_lookup(
    api: MijiaAPI, mock_device_service: MagicMock, mock_cache_manager: MagicMock
) -> None:
    api.control_device("dev-1", 2, 1, True)

    mock_device_service.get_device_by_id.assert_called_once()
    mock_cache_manager.invalidate_pattern.assert_called_once_with(
        "user-1:devices:home-fallback"
    )


def test_call_device_action_with_known_home_id_skips_lookup(
    api: MijiaAPI, mock_device_service: MagicMock, mock_cache_manager: MagicMock
) -> None:
    api.call_device_action("dev-1", 2, 1, {}, home_id="home-abc")

    mock_device_service.get_device_by_id.assert_not_called()
    mock_cache_manager.invalidate_pattern.assert_called_once_with(
        "user-1:devices:home-abc"
    )


def test_batch_control_uses_home_ids_from_requests(
    api: MijiaAPI, mock_device_service: MagicMock, mock_cache_manager: MagicMock
) -> None:
    api.batch_control_devices(
        [
            {"device_id": "dev-1", "home_id": "home-A", "siid": 2, "piid": 1, "value": True},
            {"device_id": "dev-2", "home_id": "home-A", "siid": 2, "piid": 1, "value": False},
            {"device_id": "dev-3", "home_id": "home-B", "siid": 2, "piid": 1, "value": True},
        ]
    )

    # 全部 request 都带了 home_id，不应触发 get_by_id
    mock_device_service.get_device_by_id.assert_not_called()

    # 每个不同的 home 只失效一次
    invalidated_patterns = {
        call.args[0] for call in mock_cache_manager.invalidate_pattern.call_args_list
    }
    assert invalidated_patterns == {"user-1:devices:home-A", "user-1:devices:home-B"}

    # 剥离辅助字段后再传给 SDK
    forwarded_calls = mock_device_service.batch_control_devices.call_args_list
    assert len(forwarded_calls) == 1
    forwarded_requests = forwarded_calls[0].args[0]
    for req in forwarded_requests:
        assert "home_id" not in req


def test_batch_control_falls_back_when_home_id_missing(
    api: MijiaAPI, mock_device_service: MagicMock, mock_cache_manager: MagicMock
) -> None:
    api.batch_control_devices(
        [
            {"device_id": "dev-1", "siid": 2, "piid": 1, "value": True},  # 缺 home_id
            {"device_id": "dev-2", "home_id": "home-known", "siid": 2, "piid": 1, "value": False},
        ]
    )

    # 只对缺失 home_id 的 dev-1 做反查
    assert mock_device_service.get_device_by_id.call_count == 1
    assert mock_device_service.get_device_by_id.call_args.args[0] == "dev-1"
