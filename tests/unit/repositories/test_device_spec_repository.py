"""设备规格仓储单元测试"""

import pytest
from unittest.mock import Mock, patch

from mijiaAPI_V2.domain.exceptions import MijiaAPIException
from mijiaAPI_V2.domain.models import PropertyAccess, PropertyType
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.infrastructure.http_client import HttpClient
from mijiaAPI_V2.repositories.device_spec_repository import DeviceSpecRepositoryImpl
from mijiaAPI_V2.repositories.interfaces import DeviceSpec


@pytest.fixture
def mock_http_client():
    """创建Mock HTTP客户端"""
    return Mock(spec=HttpClient)


@pytest.fixture
def mock_cache_manager():
    """创建Mock缓存管理器"""
    cache = Mock(spec=CacheManager)
    cache.get.return_value = None  # 默认缓存未命中
    return cache


@pytest.fixture
def device_spec_repo(mock_http_client, mock_cache_manager):
    """创建设备规格仓储实例"""
    return DeviceSpecRepositoryImpl(mock_http_client, mock_cache_manager)


@pytest.fixture
def sample_spec_data():
    """示例设备规格数据"""
    return {
        "description": "米家智能灯",
        "services": [
            {
                "iid": 2,
                "properties": [
                    {
                        "iid": 1,
                        "description": "开关",
                        "format": "bool",
                        "access": ["read", "write"],
                    },
                    {
                        "iid": 2,
                        "description": "亮度",
                        "format": "uint8",
                        "access": ["read", "write"],
                        "value-range": {"min": 1, "max": 100},
                    },
                    {
                        "iid": 3,
                        "description": "色温",
                        "format": "uint16",
                        "access": ["read", "write"],
                        "value-range": {"min": 2700, "max": 6500},
                    },
                ],
                "actions": [
                    {"iid": 1, "description": "切换场景"},
                ],
            }
        ],
    }


class TestDeviceSpecRepositoryImpl:
    """设备规格仓储实现测试"""

    def test_get_spec_from_cache(self, device_spec_repo, mock_cache_manager):
        """测试从缓存获取设备规格"""
        # 准备缓存数据
        cached_spec = {
            "model": "xiaomi.light.ceiling1",
            "name": "米家智能灯",
            "properties": [],
            "actions": [],
        }
        mock_cache_manager.get.return_value = cached_spec

        # 获取规格
        spec = device_spec_repo.get_spec("xiaomi.light.ceiling1")

        # 验证
        assert spec is not None
        assert spec.model == "xiaomi.light.ceiling1"
        assert spec.name == "米家智能灯"
        mock_cache_manager.get.assert_called_once_with(
            "device_spec:xiaomi.light.ceiling1", namespace="specs"
        )

    @patch("httpx.get")
    def test_get_spec_from_network(
        self, mock_httpx_get, device_spec_repo, mock_cache_manager, sample_spec_data
    ):
        """测试从网络获取设备规格"""
        # Mock两次网络响应：第一次获取instances，第二次获取spec
        instances_response = Mock()
        instances_response.json.return_value = {
            "instances": [
                {"model": "xiaomi.light.ceiling1", "type": "urn:miot-spec-v2:device:light:0000A001:xiaomi-ceiling1:1"}
            ]
        }
        
        spec_response = Mock()
        spec_response.json.return_value = sample_spec_data
        
        mock_httpx_get.side_effect = [instances_response, spec_response]

        # 获取规格
        spec = device_spec_repo.get_spec("xiaomi.light.ceiling1")

        # 验证
        assert spec is not None
        assert spec.model == "xiaomi.light.ceiling1"
        assert spec.name == "米家智能灯"
        assert len(spec.properties) == 3
        assert len(spec.actions) == 1

        # 验证缓存被调用
        mock_cache_manager.set.assert_called_once()

    @patch("httpx.get")
    def test_parse_property_bool(
        self, mock_httpx_get, device_spec_repo, mock_cache_manager, sample_spec_data
    ):
        """测试解析布尔类型属性"""
        # Mock两次网络响应：第一次获取instances，第二次获取spec
        instances_response = Mock()
        instances_response.json.return_value = {
            "instances": [
                {"model": "xiaomi.light.ceiling1", "type": "urn:miot-spec-v2:device:light:0000A001:xiaomi-ceiling1:1"}
            ]
        }
        
        spec_response = Mock()
        spec_response.json.return_value = sample_spec_data
        
        mock_httpx_get.side_effect = [instances_response, spec_response]

        spec = device_spec_repo.get_spec("xiaomi.light.ceiling1")

        # 验证开关属性
        switch_prop = spec.properties[0]
        assert switch_prop.name == "开关"
        assert switch_prop.type == PropertyType.BOOL
        assert switch_prop.access == PropertyAccess.READ_WRITE
        assert switch_prop.siid == 2
        assert switch_prop.piid == 1

    @patch("httpx.get")
    def test_parse_property_with_range(
        self, mock_httpx_get, device_spec_repo, mock_cache_manager, sample_spec_data
    ):
        """测试解析带值范围的属性"""
        # Mock两次网络响应：第一次获取instances，第二次获取spec
        instances_response = Mock()
        instances_response.json.return_value = {
            "instances": [
                {"model": "xiaomi.light.ceiling1", "type": "urn:miot-spec-v2:device:light:0000A001:xiaomi-ceiling1:1"}
            ]
        }
        
        spec_response = Mock()
        spec_response.json.return_value = sample_spec_data
        
        mock_httpx_get.side_effect = [instances_response, spec_response]

        spec = device_spec_repo.get_spec("xiaomi.light.ceiling1")

        # 验证亮度属性
        brightness_prop = spec.properties[1]
        assert brightness_prop.name == "亮度"
        assert brightness_prop.type == PropertyType.UINT
        assert brightness_prop.value_range == [1, 100]

    @patch("httpx.get")
    def test_parse_action(
        self, mock_httpx_get, device_spec_repo, mock_cache_manager, sample_spec_data
    ):
        """测试解析设备操作"""
        # Mock两次网络响应：第一次获取instances，第二次获取spec
        instances_response = Mock()
        instances_response.json.return_value = {
            "instances": [
                {"model": "xiaomi.light.ceiling1", "type": "urn:miot-spec-v2:device:light:0000A001:xiaomi-ceiling1:1"}
            ]
        }
        
        spec_response = Mock()
        spec_response.json.return_value = sample_spec_data
        
        mock_httpx_get.side_effect = [instances_response, spec_response]

        spec = device_spec_repo.get_spec("xiaomi.light.ceiling1")

        # 验证操作
        action = spec.actions[0]
        assert action.name == "切换场景"
        assert action.siid == 2
        assert action.aiid == 1

    @patch("httpx.get")
    def test_network_error(self, mock_httpx_get, device_spec_repo, mock_cache_manager):
        """测试网络错误处理"""
        # Mock网络错误
        import httpx

        mock_httpx_get.side_effect = httpx.HTTPError("网络错误")

        # 验证抛出异常
        with pytest.raises(MijiaAPIException) as exc_info:
            device_spec_repo.get_spec("xiaomi.light.ceiling1")

        assert "获取设备规格失败" in str(exc_info.value)

    def test_cache_spec(self, device_spec_repo, mock_cache_manager):
        """测试缓存设备规格"""
        spec = DeviceSpec(
            model="xiaomi.light.ceiling1",
            name="米家智能灯",
            properties=[],
            actions=[],
        )

        device_spec_repo.cache_spec("xiaomi.light.ceiling1", spec)

        # 验证缓存被调用
        mock_cache_manager.set.assert_called_once()
        call_args = mock_cache_manager.set.call_args
        assert call_args[0][0] == "device_spec:xiaomi.light.ceiling1"
        assert call_args[1]["namespace"] == "specs"
        assert call_args[1]["ttl"] == 365 * 24 * 3600  # 1年

    def test_parse_property_type_variations(self, device_spec_repo):
        """测试各种属性类型的解析"""
        assert device_spec_repo._parse_property_type("bool") == PropertyType.BOOL
        assert device_spec_repo._parse_property_type("int32") == PropertyType.INT
        assert device_spec_repo._parse_property_type("uint8") == PropertyType.UINT
        assert device_spec_repo._parse_property_type("float") == PropertyType.FLOAT
        assert device_spec_repo._parse_property_type("string") == PropertyType.STRING

    def test_parse_property_access_variations(self, device_spec_repo):
        """测试各种访问权限的解析"""
        assert (
            device_spec_repo._parse_property_access(["read", "write"])
            == PropertyAccess.READ_WRITE
        )
        assert device_spec_repo._parse_property_access(["read"]) == PropertyAccess.READ_ONLY
        assert device_spec_repo._parse_property_access(["write"]) == PropertyAccess.WRITE_ONLY
        assert device_spec_repo._parse_property_access([]) == PropertyAccess.READ_ONLY

    @patch("httpx.get")
    def test_parse_property_with_value_list(
        self, mock_httpx_get, device_spec_repo, mock_cache_manager
    ):
        """测试解析带枚举值列表的属性"""
        spec_data = {
            "description": "测试设备",
            "services": [
                {
                    "iid": 1,
                    "properties": [
                        {
                            "iid": 1,
                            "description": "模式",
                            "format": "uint8",
                            "access": ["read", "write"],
                            "value-list": [
                                {"value": 0, "description": "自动"},
                                {"value": 1, "description": "手动"},
                                {"value": 2, "description": "睡眠"},
                            ],
                        }
                    ],
                    "actions": [],
                }
            ],
        }

        # Mock两次网络响应：第一次获取instances，第二次获取spec
        instances_response = Mock()
        instances_response.json.return_value = {
            "instances": [
                {"model": "test.device.v1", "type": "urn:miot-spec-v2:device:test:0000A001:test-v1:1"}
            ]
        }
        
        spec_response = Mock()
        spec_response.json.return_value = spec_data
        
        mock_httpx_get.side_effect = [instances_response, spec_response]

        spec = device_spec_repo.get_spec("test.device.v1")

        # 验证枚举值列表
        mode_prop = spec.properties[0]
        assert mode_prop.name == "模式"
        assert mode_prop.value_list == [0, 1, 2]

    def test_cached_spec_corrupted(self, device_spec_repo, mock_cache_manager):
        """测试缓存数据损坏时的处理"""
        # 返回无效的缓存数据
        mock_cache_manager.get.return_value = {"invalid": "data"}

        # Mock网络请求
        with patch("httpx.get") as mock_httpx_get:
            # Mock两次网络响应：第一次获取instances，第二次获取spec
            instances_response = Mock()
            instances_response.json.return_value = {
                "instances": [
                    {"model": "test.device.v1", "type": "urn:miot-spec-v2:device:test:0000A001:test-v1:1"}
                ]
            }
            
            spec_response = Mock()
            spec_response.json.return_value = {
                "description": "测试设备",
                "services": [],
            }
            
            mock_httpx_get.side_effect = [instances_response, spec_response]

            spec = device_spec_repo.get_spec("test.device.v1")

            # 验证缓存被清除
            mock_cache_manager.invalidate.assert_called_once_with(
                "device_spec:test.device.v1", namespace="specs"
            )

            # 验证从网络获取成功
            assert spec is not None
            assert spec.model == "test.device.v1"

    @patch("httpx.get")
    def test_parse_property_with_list_range(
        self, mock_httpx_get, device_spec_repo, mock_cache_manager
    ):
        """测试解析列表格式的值范围"""
        # Mock两次网络响应：第一次获取instances，第二次获取spec
        instances_response = Mock()
        instances_response.json.return_value = {
            "instances": [
                {"model": "test.device.v1", "type": "urn:miot-spec-v2:device:test:0000A001:test-v1:1"}
            ]
        }
        
        # 使用列表格式的 value-range
        spec_response = Mock()
        spec_response.json.return_value = {
            "description": "测试设备",
            "services": [
                {
                    "iid": 2,
                    "type": "urn:miot-spec-v2:service:test:00000001:test-v1:1",
                    "description": "测试服务",
                    "properties": [
                        {
                            "iid": 1,
                            "type": "urn:miot-spec-v2:property:temperature:00000020:test-v1:1",
                            "description": "温度",
                            "format": "uint8",
                            "access": ["read", "write", "notify"],
                            "unit": "celsius",
                            "value-range": [30, 100, 1]  # 列表格式: [min, max, step]
                        }
                    ],
                    "actions": []
                }
            ]
        }
        
        mock_httpx_get.side_effect = [instances_response, spec_response]

        spec = device_spec_repo.get_spec("test.device.v1")

        # 验证属性解析正确
        assert spec is not None
        assert len(spec.properties) == 1
        
        temp_prop = spec.properties[0]
        assert temp_prop.name == "温度"
        assert temp_prop.type == PropertyType.UINT
        assert temp_prop.value_range == [30, 100, 1]  # 应该保持列表格式
