"""仓储层

抽象数据访问逻辑，提供接口和实现。

模块：
- interfaces: 仓储抽象接口（IHomeRepository、IDeviceRepository、IAsyncDeviceRepository等）
- device_repository: 设备仓储实现（同步）
- async_device_repository: 设备仓储实现（异步）
- home_repository: 家庭仓储实现
- scene_repository: 场景仓储实现
- device_spec_repository: 设备规格仓储实现
"""

from mijiaAPI_V2.repositories.async_device_repository import AsyncDeviceRepositoryImpl
from mijiaAPI_V2.repositories.device_repository import DeviceRepositoryImpl
from mijiaAPI_V2.repositories.device_spec_repository import DeviceSpecRepositoryImpl
from mijiaAPI_V2.repositories.home_repository import HomeRepositoryImpl
from mijiaAPI_V2.repositories.interfaces import (
    DeviceSpec,
    IAsyncDeviceRepository,
    IDeviceRepository,
    IDeviceSpecRepository,
    IHomeRepository,
    ISceneRepository,
)
from mijiaAPI_V2.repositories.scene_repository import SceneRepositoryImpl

__all__ = [
    # 仓储接口
    "IHomeRepository",
    "IDeviceRepository",
    "IAsyncDeviceRepository",
    "ISceneRepository",
    "IDeviceSpecRepository",
    # 数据模型
    "DeviceSpec",
    # 仓储实现
    "DeviceRepositoryImpl",
    "AsyncDeviceRepositoryImpl",
    "HomeRepositoryImpl",
    "SceneRepositoryImpl",
    "DeviceSpecRepositoryImpl",
]
