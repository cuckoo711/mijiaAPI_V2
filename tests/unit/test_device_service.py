"""DeviceService单元测试"""

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.exceptions import (
    DeviceNotFoundError,
    PropertyReadOnlyError,
    ValidationError,
)
from mijiaAPI_V2.domain.models import (
    Credential,
    ActionParameter,
    Device,
    DeviceAction,
    DeviceProperty,
    DeviceStatus,
    PropertyAccess,
    PropertyType,
)
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.repositories.interfaces import (
    DeviceSpec,
    IDeviceRepository,
    IDeviceSpecRepository,
)
from mijiaAPI_V2.services.device_service import DeviceService


@pytest.fixture
def mock_device_repo() -> Mock:
    """创建模拟的IDeviceRepository"""
    return Mock(spec=IDeviceRepository)


@pytest.fixture
def mock_spec_repo() -> Mock:
    """创建模拟的IDeviceSpecRepository"""
    return Mock(spec=IDeviceSpecRepository)


@pytest.fixture
def mock_cache_manager() -> Mock:
    """创建模拟的CacheManager"""
    return Mock(spec=CacheManager)


@pytest.fixture
def sample_credential() -> Credential:
    """创建示例凭据"""
    return Credential(
        user_id="test_user_123",
        service_token="test_token_abc",
        ssecurity="test_ssecurity_xyz",
        c_user_id="test_c_user_id",
        device_id="test_device_456",
        user_agent="iOS-14.4-6.0.103-iPhone12,1",
        expires_at=datetime.now() + timedelta(days=7),
    )


@pytest.fixture
def sample_device() -> Device:
    """创建示例设备"""
    return Device(
        did="device_001",
        name="智能灯泡",
        model="yeelink.light.color1",
        home_id="home_123",
        room_id="room_456",
        status=DeviceStatus.ONLINE,
    )


@pytest.fixture
def sample_property() -> DeviceProperty:
    """创建示例设备属性"""
    return DeviceProperty(
        siid=2,
        piid=1,
        name="power",
        type=PropertyType.BOOL,
        access=PropertyAccess.READ_WRITE,
        value=True,
    )


@pytest.fixture
def sample_readonly_property() -> DeviceProperty:
    """创建只读属性"""
    return DeviceProperty(
        siid=2,
        piid=2,
        name="temperature",
        type=PropertyType.INT,
        access=PropertyAccess.READ_ONLY,
        value=25,
        value_range=[0, 100],
    )


@pytest.fixture
def sample_device_spec(
    sample_property: DeviceProperty, sample_readonly_property: DeviceProperty
) -> DeviceSpec:
    """创建示例设备规格"""
    return DeviceSpec(
        model="yeelink.light.color1",
        name="Yeelight彩光灯泡",
        properties=[sample_property, sample_readonly_property],
        actions=[],
    )


@pytest.fixture
def device_service(
    mock_device_repo: Mock,
    mock_spec_repo: Mock,
    mock_cache_manager: Mock,
    sample_device: Device,
    sample_device_spec: DeviceSpec,
) -> DeviceService:
    """创建DeviceService实例"""
    mock_device_repo.get_by_id.return_value = sample_device
    mock_spec_repo.get_spec.return_value = sample_device_spec
    return DeviceService(
        device_repo=mock_device_repo,
        spec_repo=mock_spec_repo,
        cache_manager=mock_cache_manager,
    )


def test_device_service_initialization(
    mock_device_repo: Mock, mock_spec_repo: Mock, mock_cache_manager: Mock
) -> None:
    """测试DeviceService初始化"""
    service = DeviceService(
        device_repo=mock_device_repo,
        spec_repo=mock_spec_repo,
        cache_manager=mock_cache_manager,
    )
    assert service._device_repo is mock_device_repo
    assert service._spec_repo is mock_spec_repo
    assert service._cache is mock_cache_manager


def test_get_devices_delegates_to_repo(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
    sample_device: Device,
) -> None:
    """测试get_devices委托给device_repo"""
    # 设置mock返回值
    mock_device_repo.get_all.return_value = [sample_device]

    # 调用方法
    result = device_service.get_devices("home_123", sample_credential)

    # 验证
    mock_device_repo.get_all.assert_called_once_with("home_123", sample_credential)
    assert len(result) == 1
    assert result[0] == sample_device


def test_get_device_by_id_delegates_to_repo(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
    sample_device: Device,
) -> None:
    """测试get_device_by_id委托给device_repo"""
    # 设置mock返回值
    mock_device_repo.get_by_id.return_value = sample_device

    # 调用方法
    result = device_service.get_device_by_id("device_001", sample_credential)

    # 验证
    mock_device_repo.get_by_id.assert_called_once_with("device_001", sample_credential)
    assert result == sample_device


def test_get_device_by_id_returns_none_when_not_found(
    device_service: DeviceService, mock_device_repo: Mock, sample_credential: Credential
) -> None:
    """测试get_device_by_id在设备不存在时返回None"""
    # 设置mock返回None
    mock_device_repo.get_by_id.return_value = None

    # 调用方法
    result = device_service.get_device_by_id("nonexistent", sample_credential)

    # 验证
    mock_device_repo.get_by_id.assert_called_once_with("nonexistent", sample_credential)
    assert result is None


def test_get_device_properties_delegates_to_repo(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
    sample_property: DeviceProperty,
) -> None:
    """测试get_device_properties委托给device_repo"""
    # 设置mock返回值
    mock_device_repo.get_properties.return_value = [sample_property]

    # 调用方法
    result = device_service.get_device_properties("device_001", sample_credential)

    # 验证
    mock_device_repo.get_properties.assert_called_once_with("device_001", sample_credential)
    assert len(result) == 1
    assert result[0] == sample_property


def test_set_device_property_success(
    device_service: DeviceService,
    mock_device_repo: Mock,
    mock_spec_repo: Mock,
    sample_credential: Credential,
    sample_device: Device,
    sample_device_spec: DeviceSpec,
) -> None:
    """测试set_device_property成功设置属性"""
    # 设置mock返回值
    mock_device_repo.get_by_id.return_value = sample_device
    mock_spec_repo.get_spec.return_value = sample_device_spec
    mock_device_repo.set_property.return_value = True

    # 调用方法
    result = device_service.set_device_property(
        "device_001", siid=2, piid=1, value=False, credential=sample_credential
    )

    # 验证
    mock_device_repo.get_by_id.assert_called_once_with("device_001", sample_credential)
    mock_spec_repo.get_spec.assert_called_once_with("yeelink.light.color1")
    mock_device_repo.set_property.assert_called_once_with(
        "device_001", 2, 1, False, sample_credential
    )
    assert result is True


def test_set_device_property_raises_device_not_found(
    device_service: DeviceService, mock_device_repo: Mock, sample_credential: Credential
) -> None:
    """测试set_device_property在设备不存在时抛出异常"""
    # 设置mock返回None
    mock_device_repo.get_by_id.return_value = None

    # 验证抛出异常
    with pytest.raises(DeviceNotFoundError) as exc_info:
        device_service.set_device_property(
            "nonexistent", siid=2, piid=1, value=True, credential=sample_credential
        )

    assert "设备不存在: nonexistent" in str(exc_info.value)


def test_set_device_property_raises_readonly_error(
    device_service: DeviceService,
    mock_device_repo: Mock,
    mock_spec_repo: Mock,
    sample_credential: Credential,
    sample_device: Device,
    sample_device_spec: DeviceSpec,
) -> None:
    """测试set_device_property在属性只读时抛出异常"""
    # 设置mock返回值
    mock_device_repo.get_by_id.return_value = sample_device
    mock_spec_repo.get_spec.return_value = sample_device_spec

    # 验证抛出异常（尝试设置只读属性temperature）
    with pytest.raises(PropertyReadOnlyError) as exc_info:
        device_service.set_device_property(
            "device_001", siid=2, piid=2, value=30, credential=sample_credential
        )

    assert "属性只读: temperature" in str(exc_info.value)


def test_set_device_property_raises_validation_error_for_invalid_type(
    device_service: DeviceService,
    mock_device_repo: Mock,
    mock_spec_repo: Mock,
    sample_credential: Credential,
    sample_device: Device,
    sample_device_spec: DeviceSpec,
) -> None:
    """测试set_device_property在属性值类型无效时抛出异常"""
    # 设置mock返回值
    mock_device_repo.get_by_id.return_value = sample_device
    mock_spec_repo.get_spec.return_value = sample_device_spec

    # 验证抛出异常（power属性应该是bool，但传入了字符串）
    with pytest.raises(ValidationError) as exc_info:
        device_service.set_device_property(
            "device_001", siid=2, piid=1, value="invalid", credential=sample_credential
        )

    assert "属性值无效" in str(exc_info.value)


def test_set_device_property_without_spec_is_rejected(
    device_service: DeviceService,
    mock_device_repo: Mock,
    mock_spec_repo: Mock,
    sample_credential: Credential,
    sample_device: Device,
) -> None:
    """规格不可用时拒绝发送属性控制。"""
    # 设置mock返回值（规格不存在）
    mock_device_repo.get_by_id.return_value = sample_device
    mock_spec_repo.get_spec.return_value = None
    mock_device_repo.set_property.return_value = True

    # 调用方法（没有规格验证，直接设置）
    with pytest.raises(ValidationError):
        device_service.set_device_property(
            "device_001", siid=2, piid=1, value=True, credential=sample_credential
        )
    mock_device_repo.set_property.assert_not_called()


def test_call_device_action_delegates_to_repo(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
    sample_device_spec: DeviceSpec,
) -> None:
    """测试call_device_action委托给device_repo"""
    # 设置mock返回值
    mock_device_repo.call_action.return_value = {"code": 0, "message": "success"}
    sample_device_spec.actions = [
        DeviceAction(
            siid=2, aiid=1, name="set_level", parameters=[ActionParameter(name="level", type="int")]
        )
    ]

    # 调用方法
    params: Dict[str, Any] = {"level": 50}
    result = device_service.call_device_action(
        "device_001", siid=2, aiid=1, params=params, credential=sample_credential
    )

    # 验证
    mock_device_repo.call_action.assert_called_once_with(
        "device_001", 2, 1, params, sample_credential
    )
    assert result == {"code": 0, "message": "success"}


def test_batch_control_devices_single_batch(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试batch_control_devices处理单个批次"""
    # 创建10个请求（小于20）
    requests: List[Dict[str, Any]] = [
        {"did": f"device_{i}", "siid": 2, "piid": 1, "value": True} for i in range(10)
    ]
    expected_results = [{"code": 0} for _ in range(10)]
    mock_device_repo.batch_set_properties.return_value = expected_results

    # 调用方法
    result = device_service.batch_control_devices(requests, sample_credential)

    # 验证（只调用一次，因为请求数小于20）
    mock_device_repo.batch_set_properties.assert_called_once_with(requests, sample_credential)
    assert len(result) == 10
    assert result == expected_results


def test_batch_control_devices_multiple_batches(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试batch_control_devices自动分组处理多个批次"""
    # 创建45个请求（需要分成3个批次：20+20+5）
    requests: List[Dict[str, Any]] = [
        {"did": f"device_{i}", "siid": 2, "piid": 1, "value": True} for i in range(45)
    ]

    # 设置mock返回值（每次调用返回对应数量的结果）
    def batch_side_effect(
        batch_requests: List[Dict[str, Any]], cred: Credential
    ) -> List[Dict[str, Any]]:
        return [{"code": 0} for _ in batch_requests]

    mock_device_repo.batch_set_properties.side_effect = batch_side_effect

    # 调用方法
    result = device_service.batch_control_devices(requests, sample_credential)

    # 验证（应该调用3次：20+20+5）
    assert mock_device_repo.batch_set_properties.call_count == 3
    assert len(result) == 45

    # 验证每次调用的批次大小
    calls = mock_device_repo.batch_set_properties.call_args_list
    assert len(calls[0][0][0]) == 20  # 第一批20个
    assert len(calls[1][0][0]) == 20  # 第二批20个
    assert len(calls[2][0][0]) == 5  # 第三批5个


def test_batch_control_devices_empty_requests(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试batch_control_devices处理空请求列表"""
    # 调用方法
    result = device_service.batch_control_devices([], sample_credential)

    # 验证（不应该调用仓储层）
    mock_device_repo.batch_set_properties.assert_not_called()
    assert len(result) == 0


def test_batch_control_devices_exactly_20_requests(
    device_service: DeviceService,
    mock_device_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试batch_control_devices处理恰好20个请求"""
    # 创建20个请求（边界情况）
    requests: List[Dict[str, Any]] = [
        {"did": f"device_{i}", "siid": 2, "piid": 1, "value": True} for i in range(20)
    ]
    expected_results = [{"code": 0} for _ in range(20)]
    mock_device_repo.batch_set_properties.return_value = expected_results

    # 调用方法
    result = device_service.batch_control_devices(requests, sample_credential)

    # 验证（应该只调用一次）
    mock_device_repo.batch_set_properties.assert_called_once()
    assert len(result) == 20
