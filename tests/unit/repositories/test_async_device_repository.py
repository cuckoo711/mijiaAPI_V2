"""异步设备仓储测试"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from mijiaAPI_V2.domain.models import Credential, Device, DeviceStatus
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.infrastructure.http_client import AsyncHttpClient
from mijiaAPI_V2.repositories.async_device_repository import AsyncDeviceRepositoryImpl


@pytest.fixture
def credential() -> Credential:
    """创建测试凭据"""
    from datetime import datetime, timedelta
    
    return Credential(
        user_id="123456",
        service_token="test_token",
        ssecurity="test_ssecurity",
        c_user_id="c123456",
        device_id="device123",
        user_agent="test_user_agent",
        expires_at=datetime.now() + timedelta(days=30),
    )


@pytest.fixture
def mock_http_client() -> AsyncHttpClient:
    """创建模拟HTTP客户端"""
    client = AsyncMock(spec=AsyncHttpClient)
    return client


@pytest.fixture
def mock_cache_manager() -> CacheManager:
    """创建模拟缓存管理器"""
    cache = MagicMock(spec=CacheManager)
    cache.get.return_value = None
    return cache


@pytest.fixture
def repository(
    mock_http_client: AsyncHttpClient, mock_cache_manager: CacheManager
) -> AsyncDeviceRepositoryImpl:
    """创建仓储实例"""
    return AsyncDeviceRepositoryImpl(mock_http_client, mock_cache_manager)


@pytest.mark.asyncio
async def test_get_all_devices(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    mock_cache_manager: CacheManager,
    credential: Credential,
) -> None:
    """测试获取所有设备"""
    # 模拟API响应
    mock_http_client.post.return_value = {
        "code": 0,
        "result": {
            "device_info": [
                {
                    "did": "device1",
                    "name": "设备1",
                    "model": "model1",
                    "isOnline": True,
                    "roomid": "room1",
                },
                {
                    "did": "device2",
                    "name": "设备2",
                    "model": "model2",
                    "isOnline": False,
                },
            ]
        },
    }

    # 获取设备列表
    devices = await repository.get_all("home123", credential)

    # 验证结果
    assert len(devices) == 2
    assert devices[0].did == "device1"
    assert devices[0].name == "设备1"
    assert devices[0].status == DeviceStatus.ONLINE
    assert devices[1].did == "device2"
    assert devices[1].status == DeviceStatus.OFFLINE

    # 验证缓存调用
    mock_cache_manager.set.assert_called_once()


@pytest.mark.asyncio
async def test_get_all_devices_from_cache(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    mock_cache_manager: CacheManager,
    credential: Credential,
) -> None:
    """测试从缓存获取设备列表"""
    # 模拟缓存命中
    cached_devices = [
        {
            "did": "device1",
            "name": "设备1",
            "model": "model1",
            "home_id": "home123",
            "status": "online",
        }
    ]
    mock_cache_manager.get.return_value = cached_devices

    # 获取设备列表
    devices = await repository.get_all("home123", credential)

    # 验证结果
    assert len(devices) == 1
    assert devices[0].did == "device1"

    # 验证没有调用HTTP客户端
    mock_http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_device_by_id(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    credential: Credential,
) -> None:
    """测试根据ID获取设备"""
    # 模拟API响应
    mock_http_client.post.return_value = {
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
                    "isOnline": True,
                },
            ]
        },
    }

    # 获取特定设备
    device = await repository.get_by_id("device2", "home123", credential)

    # 验证结果
    assert device is not None
    assert device.did == "device2"
    assert device.name == "设备2"


@pytest.mark.asyncio
async def test_get_device_by_id_not_found(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    credential: Credential,
) -> None:
    """测试获取不存在的设备"""
    # 模拟API响应
    mock_http_client.post.return_value = {
        "code": 0,
        "result": {"device_info": []},
    }

    # 获取不存在的设备
    device = await repository.get_by_id("nonexistent", "home123", credential)

    # 验证结果
    assert device is None


@pytest.mark.asyncio
async def test_get_properties(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    credential: Credential,
) -> None:
    """测试获取设备属性"""
    # 模拟API响应
    mock_http_client.post.return_value = {
        "code": 0,
        "result": {"value": 25.5},
    }

    # 获取属性
    value = await repository.get_properties("device1", 2, 1, credential)

    # 验证结果
    assert value == 25.5

    # 验证HTTP调用
    mock_http_client.post.assert_called_once_with(
        "/miotspec/prop/get",
        {"did": "device1", "siid": 2, "piid": 1},
        credential,
    )


@pytest.mark.asyncio
async def test_set_property(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    mock_cache_manager: CacheManager,
    credential: Credential,
) -> None:
    """测试设置设备属性"""
    # 模拟API响应
    mock_http_client.post.return_value = {"code": 0}

    # 设置属性
    result = await repository.set_property("device1", 2, 1, True, credential)

    # 验证结果
    assert result is True

    # 验证HTTP调用
    mock_http_client.post.assert_called_once_with(
        "/miotspec/prop/set",
        {"did": "device1", "siid": 2, "piid": 1, "value": True},
        credential,
    )

    # 验证缓存失效
    mock_cache_manager.invalidate_pattern.assert_called_once_with("devices:")


@pytest.mark.asyncio
async def test_call_action(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    credential: Credential,
) -> None:
    """测试调用设备操作"""
    # 模拟API响应
    mock_http_client.post.return_value = {"code": 0}

    # 调用操作
    result = await repository.call_action("device1", 2, 1, [100], credential)

    # 验证结果
    assert result is True

    # 验证HTTP调用
    mock_http_client.post.assert_called_once_with(
        "/miotspec/action",
        {"did": "device1", "siid": 2, "aiid": 1, "in": [100]},
        credential,
    )


@pytest.mark.asyncio
async def test_batch_get_properties(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    credential: Credential,
) -> None:
    """测试批量获取属性"""
    # 模拟API响应
    mock_http_client.post.return_value = {
        "code": 0,
        "result": [{"value": 25.5}, {"value": 60}],
    }

    # 批量获取
    requests = [
        {"did": "device1", "siid": 2, "piid": 1},
        {"did": "device1", "siid": 2, "piid": 2},
    ]
    results = await repository.batch_get_properties(requests, credential)

    # 验证结果
    assert len(results) == 2
    assert results[0]["value"] == 25.5
    assert results[1]["value"] == 60


@pytest.mark.asyncio
async def test_batch_set_properties(
    repository: AsyncDeviceRepositoryImpl,
    mock_http_client: AsyncHttpClient,
    mock_cache_manager: CacheManager,
    credential: Credential,
) -> None:
    """测试批量设置属性"""
    # 模拟API响应
    mock_http_client.post.return_value = {
        "code": 0,
        "result": [{"code": 0}, {"code": 0}],
    }

    # 批量设置
    requests = [
        {"did": "device1", "siid": 2, "piid": 1, "value": True},
        {"did": "device1", "siid": 2, "piid": 2, "value": 100},
    ]
    results = await repository.batch_set_properties(requests, credential)

    # 验证结果
    assert len(results) == 2
    assert all(results)

    # 验证缓存失效
    mock_cache_manager.invalidate_pattern.assert_called_once_with("devices:")


@pytest.mark.asyncio
async def test_parse_device_with_bool_status(
    repository: AsyncDeviceRepositoryImpl,
) -> None:
    """测试解析设备数据（布尔状态）"""
    data = {
        "did": "device1",
        "name": "测试设备",
        "model": "test.model",
        "isOnline": True,
        "roomid": "room1",
    }

    device = repository._parse_device(data, "home123")

    assert device.did == "device1"
    assert device.name == "测试设备"
    assert device.status == DeviceStatus.ONLINE
    assert device.room_id == "room1"


@pytest.mark.asyncio
async def test_parse_device_with_int_status(
    repository: AsyncDeviceRepositoryImpl,
) -> None:
    """测试解析设备数据（整数状态）"""
    data = {
        "did": "device1",
        "name": "测试设备",
        "model": "test.model",
        "isOnline": 0,
    }

    device = repository._parse_device(data, "home123")

    assert device.status == DeviceStatus.OFFLINE


@pytest.mark.asyncio
async def test_parse_device_with_unknown_status(
    repository: AsyncDeviceRepositoryImpl,
) -> None:
    """测试解析设备数据（未知状态）"""
    data = {
        "did": "device1",
        "name": "测试设备",
        "model": "test.model",
        "isOnline": "unknown",
    }

    device = repository._parse_device(data, "home123")

    assert device.status == DeviceStatus.UNKNOWN
