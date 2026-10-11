"""设备仓储单元测试"""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.models import Credential, DeviceStatus
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.infrastructure.http_client import HttpClient
from mijiaAPI_V2.repositories.device_repository import DeviceRepositoryImpl


@pytest.fixture
def mock_http_client():
    """创建Mock HTTP客户端"""
    return Mock(spec=HttpClient)


@pytest.fixture
def mock_cache_manager():
    """创建Mock缓存管理器"""
    return Mock(spec=CacheManager)


@pytest.fixture
def device_repository(mock_http_client, mock_cache_manager):
    """创建设备仓储实例"""
    return DeviceRepositoryImpl(mock_http_client, mock_cache_manager)


@pytest.fixture
def test_credential():
    """创建测试凭据"""
    return Credential(
        user_id="test_user",
        service_token="test_token",
        ssecurity="test_ssecurity",
        c_user_id="test_c_user",
        device_id="test_device",
        user_agent="test_agent",
        expires_at=datetime.now() + timedelta(days=7),
    )


class TestGetAll:
    """测试get_all方法"""

    def test_get_all_from_cache(self, device_repository, mock_cache_manager, test_credential):
        """测试从缓存获取设备列表"""
        # 准备缓存数据
        cached_devices = [
            {
                "did": "device1",
                "name": "设备1",
                "model": "model1",
                "home_id": "home1",
                "room_id": None,
                "status": "online",
                "parent_id": None,
                "parent_model": None,
            }
        ]
        mock_cache_manager.get.return_value = cached_devices

        # 调用方法
        devices = device_repository.get_all("home1", test_credential)

        # 验证结果
        assert len(devices) == 1
        assert devices[0].did == "device1"
        assert devices[0].name == "设备1"
        assert devices[0].status == DeviceStatus.ONLINE

        # 验证缓存被调用
        mock_cache_manager.get.assert_called_once_with(
            "devices:home1", namespace=test_credential.user_id
        )

    def test_get_all_from_api(
        self, device_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试从API获取设备列表"""
        # 缓存未命中
        mock_cache_manager.get.return_value = None

        # 准备家庭列表API响应（用于获取home_owner）
        home_list_response = {
            "code": 0,
            "result": {"homelist": [{"id": 1, "uid": 123456, "name": "我的家"}]},  # id 应该是整数
        }

        # 准备设备列表API响应
        device_list_response = {
            "code": 0,
            "result": {
                "device_info": [
                    {
                        "did": "device1",
                        "name": "设备1",
                        "model": "model1",
                        "isOnline": True,
                    },
                    {
                        "did": "device2",
                        "name": "设备2",
                        "model": "model2",
                        "isOnline": False,
                    },
                ],
                "has_more": False,
            },
        }

        # 配置mock返回不同的响应（第一次调用返回家庭列表，第二次返回设备列表）
        mock_http_client.post.side_effect = [home_list_response, device_list_response]

        # 调用方法（使用字符串 "1" 作为 home_id）
        devices = device_repository.get_all("1", test_credential)

        # 验证结果
        assert len(devices) == 2
        assert devices[0].did == "device1"
        assert devices[0].status == DeviceStatus.ONLINE
        assert devices[1].did == "device2"
        assert devices[1].status == DeviceStatus.OFFLINE

        # 验证HTTP调用（应该调用两次：一次获取家庭列表，一次获取设备列表）
        assert mock_http_client.post.call_count == 2

        # 验证缓存被设置
        mock_cache_manager.set.assert_called_once()


class TestSetProperty:
    """测试set_property方法"""

    def test_set_property_success(
        self, device_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试成功设置设备属性"""
        # 准备API响应（返回结果列表）
        api_response = {"code": 0, "result": [{"code": 0}]}
        mock_http_client.post.return_value = api_response

        # 调用方法
        result = device_repository.set_property("device1", 2, 1, True, test_credential)

        # 验证结果
        assert result is True

        # 验证HTTP调用（使用params包装）
        mock_http_client.post.assert_called_once_with(
            "/miotspec/prop/set",
            json={"params": [{"did": "device1", "siid": 2, "piid": 1, "value": True}]},
            credential=test_credential,
        )

        # 验证缓存失效
        mock_cache_manager.invalidate_pattern.assert_called_once_with(
            f"{test_credential.user_id}:device:device1"
        )

    def test_set_property_failure(
        self, device_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试设置设备属性失败"""
        # 准备API响应（失败）
        api_response = {"code": -1, "message": "设置失败"}
        mock_http_client.post.return_value = api_response

        # 调用方法
        result = device_repository.set_property("device1", 2, 1, True, test_credential)

        # 验证结果
        assert result is False

        # 验证缓存未失效
        mock_cache_manager.invalidate_pattern.assert_not_called()


class TestCallAction:
    """测试call_action方法"""

    def test_call_action_success(
        self, device_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试成功调用设备操作"""
        # 准备API响应
        api_response = {"code": 0, "result": {"code": 0, "status": "ok"}}
        mock_http_client.post.return_value = api_response

        # 调用方法
        result = device_repository.call_action("device1", 2, 1, {"param": "value"}, test_credential)

        # 验证结果
        assert result == {"code": 0, "status": "ok"}

        # 验证HTTP调用
        mock_http_client.post.assert_called_once_with(
            "/miotspec/action",
            json={"params": {"did": "device1", "siid": 2, "aiid": 1, "value": ["value"]}},
            credential=test_credential,
        )

        # 验证缓存失效
        mock_cache_manager.invalidate_pattern.assert_called_once_with(
            f"{test_credential.user_id}:device:device1"
        )


class TestBatchOperations:
    """测试批量操作"""

    def test_batch_set_properties(
        self, device_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试批量设置属性"""
        # 准备请求
        requests = [
            {"did": "device1", "siid": 2, "piid": 1, "value": True},
            {"did": "device2", "siid": 2, "piid": 1, "value": False},
        ]

        # 准备API响应
        api_response = {"code": 0, "result": [{"code": 0}, {"code": 0}]}
        mock_http_client.post.return_value = api_response

        # 调用方法
        results = device_repository.batch_set_properties(requests, test_credential)

        # 验证结果
        assert len(results) == 2

        # 验证HTTP调用（使用 /miotspec/prop/set 而不是 set_batch）
        mock_http_client.post.assert_called_once_with(
            "/miotspec/prop/set", json={"params": requests}, credential=test_credential
        )

        # 验证缓存失效（两个设备）
        assert mock_cache_manager.invalidate_pattern.call_count == 2


class TestParseDeviceStatus:
    """测试设备状态解析"""

    def test_parse_status_bool_true(self, device_repository):
        """测试解析布尔值True"""
        status = device_repository._parse_device_status(True)
        assert status == DeviceStatus.ONLINE

    def test_parse_status_bool_false(self, device_repository):
        """测试解析布尔值False"""
        status = device_repository._parse_device_status(False)
        assert status == DeviceStatus.OFFLINE

    def test_parse_status_int_one(self, device_repository):
        """测试解析整数1"""
        status = device_repository._parse_device_status(1)
        assert status == DeviceStatus.ONLINE

    def test_parse_status_int_zero(self, device_repository):
        """测试解析整数0"""
        status = device_repository._parse_device_status(0)
        assert status == DeviceStatus.OFFLINE

    def test_parse_status_none(self, device_repository):
        """测试解析None"""
        status = device_repository._parse_device_status(None)
        assert status == DeviceStatus.UNKNOWN

    def test_parse_status_unknown_type(self, device_repository):
        """测试解析未知类型"""
        status = device_repository._parse_device_status("unknown")
        assert status == DeviceStatus.UNKNOWN
