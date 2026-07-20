# API客户端参考

## MijiaAPI（同步）

### 类定义

```python
class MijiaAPI:
    """米家API客户端（同步版本）
    
    无状态的API客户端，所有操作都需要使用初始化时传入的Credential。
    支持多用户场景，每个用户创建独立的客户端实例。
    """
```

### 初始化

```python
def __init__(
    self,
    credential: Credential,
    device_service: DeviceService,
    scene_service: SceneService,
    statistics_service: Optional[StatisticsService] = None,
    home_repository: Optional[Any] = None,
)
```

**参数**：
- `credential`: 用户凭据对象
- `device_service`: 设备服务实例
- `scene_service`: 智能服务实例
- `statistics_service`: 统计服务实例（可选）
- `home_repository`: 家庭仓储实例（可选）

**注意**：通常不直接实例化，而是使用工厂函数 `create_api_client()`

### 家庭管理

#### get_homes()

获取用户的所有家庭列表。

```python
def get_homes(self) -> List[Home]
```

**返回**：
- `List[Home]`: 家庭列表

**异常**：
- `TokenExpiredError`: 凭据已过期
- `NetworkError`: 网络错误
- `RuntimeError`: 家庭仓储未初始化

**示例**：
```python
homes = api.get_homes()
for home in homes:
    print(f"{home.name} (ID: {home.id})")
```

### 设备管理

#### get_devices()

获取指定家庭下的所有设备。

```python
def get_devices(self, home_id: str) -> List[Device]
```

**参数**：
- `home_id`: 家庭ID

**返回**：
- `List[Device]`: 设备列表

**异常**：
- `TokenExpiredError`: 凭据已过期
- `NetworkError`: 网络错误

**示例**：
```python
devices = api.get_devices(home_id="123456")
for device in devices:
    print(f"{device.name} - {device.model}")
```

#### get_device()

根据设备ID获取单个设备信息。

```python
def get_device(self, device_id: str) -> Optional[Device]
```

**参数**：
- `device_id`: 设备ID

**返回**：
- `Optional[Device]`: 设备对象，不存在返回None

**异常**：
- `TokenExpiredError`: 凭据已过期
- `NetworkError`: 网络错误

**示例**：
```python
device = api.get_device(device_id="device_123")
if device:
    print(f"找到设备: {device.name}")
else:
    print("设备不存在")
```

#### control_device()

控制设备的指定属性。

```python
def control_device(
    self, 
    device_id: str, 
    siid: int, 
    piid: int, 
    value: Any,
    refresh_cache: bool = True
) -> bool
```

**参数**：
- `device_id`: 设备ID
- `siid`: 服务ID（Service ID）
- `piid`: 属性ID（Property ID）
- `value`: 属性值
- `refresh_cache`: 是否在控制后刷新缓存，默认为True

**返回**：
- `bool`: 是否成功

**异常**：
- `TokenExpiredError`: 凭据已过期
- `DeviceNotFoundError`: 设备不存在
- `PropertyReadOnlyError`: 属性只读
- `ValidationError`: 属性值无效
- `NetworkError`: 网络错误

**缓存刷新**：
控制设备后默认会自动刷新该设备所属家庭的缓存，确保下次获取的是最新状态。如果需要高频控制设备（如连续调节亮度），可以设置 `refresh_cache=False` 以提高性能，然后在操作完成后手动调用 `refresh_cache()` 刷新缓存。

**示例**：
```python
# 打开灯（自动刷新缓存）
success = api.control_device(
    device_id="light_123",
    siid=2,      # 灯光服务
    piid=1,      # 开关属性
    value=True   # 打开
)

# 设置亮度（不刷新缓存，适用于高频操作）
success = api.control_device(
    device_id="light_123",
    siid=2,      # 灯光服务
    piid=2,      # 亮度属性
    value=80,    # 亮度值 0-100
    refresh_cache=False
)
```

#### call_device_action()

调用设备的指定操作。

```python
def call_device_action(
    self,
    device_id: str,
    siid: int,
    aiid: int,
    params: Optional[Dict[str, Any]] = None,
    refresh_cache: bool = True
) -> Any
```

**参数**：
- `device_id`: 设备ID
- `siid`: 服务ID
- `aiid`: 操作ID（Action ID）
- `params`: 操作参数（可选）
- `refresh_cache`: 是否在操作后刷新缓存，默认为True

**返回**：
- `Any`: 操作结果

**异常**：
- `TokenExpiredError`: 凭据已过期
- `DeviceNotFoundError`: 设备不存在
- `NetworkError`: 网络错误

**缓存刷新**：
调用设备操作后默认会自动刷新该设备所属家庭的缓存，确保下次获取的是最新状态。

**示例**：
```python
# 调用扫地机器人的清扫操作（自动刷新缓存）
result = api.call_device_action(
    device_id="vacuum_123",
    siid=2,      # 清扫服务
    aiid=1,      # 开始清扫操作
    params={"mode": "auto"}
)

# 调用操作但不刷新缓存
result = api.call_device_action(
    device_id="vacuum_123",
    siid=2,
    aiid=1,
    params={"mode": "auto"},
    refresh_cache=False
)
```

#### batch_control_devices()

批量控制多个设备。

```python
def batch_control_devices(
    self,
    requests: List[Dict[str, Any]],
    refresh_cache: bool = True
) -> List[Dict[str, Any]]
```

**参数**：
- `requests`: 批量请求列表，每个请求包含：
  - `device_id`: 设备ID
  - `siid`: 服务ID
  - `piid`: 属性ID
  - `value`: 属性值
- `refresh_cache`: 是否在控制后刷新缓存，默认为True

**返回**：
- `List[Dict[str, Any]]`: 批量操作结果列表

**异常**：
- `TokenExpiredError`: 凭据已过期
- `NetworkError`: 网络错误

**缓存刷新**：
批量控制设备后默认会自动刷新所有涉及家庭的缓存，确保下次获取的是最新状态。如果需要高频批量操作，可以设置 `refresh_cache=False` 以提高性能。

**示例**：
```python
requests = [
    {"device_id": "light_1", "siid": 2, "piid": 1, "value": True},
    {"device_id": "light_2", "siid": 2, "piid": 1, "value": False},
    {"device_id": "light_3", "siid": 2, "piid": 2, "value": 50},
]

# 批量控制并自动刷新缓存（推荐）
results = api.batch_control_devices(requests)

# 批量控制但不刷新缓存（高频操作时使用）
results = api.batch_control_devices(requests, refresh_cache=False)

# 处理结果
for i, result in enumerate(results):
    if result.get("code") == 0:
        print(f"请求{i+1}成功")
    else:
        print(f"请求{i+1}失败")
```

### 智能管理

#### get_scenes()

获取指定家庭下的所有智能。

```python
def get_scenes(self, home_id: str) -> List[Scene]
```

**参数**：
- `home_id`: 家庭ID

**返回**：
- `List[Scene]`: 智能列表

**异常**：
- `TokenExpiredError`: 凭据已过期
- `NetworkError`: 网络错误

**示例**：
```python
scenes = api.get_scenes(home_id="123456")
for scene in scenes:
    print(f"{scene.name} (ID: {scene.scene_id})")
```

#### execute_scene()

执行指定智能。

```python
def execute_scene(self, scene_id: str) -> bool
```

**参数**：
- `scene_id`: 智能ID

**返回**：
- `bool`: 是否成功

**异常**：
- `TokenExpiredError`: 凭据已过期
- `NetworkError`: 网络错误

**示例**：
```python
success = api.execute_scene(scene_id="scene_123")
if success:
    print("智能执行成功")
```

### 统计信息

#### get_device_statistics()

获取设备统计信息。

```python
def get_device_statistics(self, home_id: str) -> Dict[str, Any]
```

**参数**：
- `home_id`: 家庭ID

**返回**：
- `Dict[str, Any]`: 统计信息字典，包含：
  - `total`: 总设备数
  - `online`: 在线设备数
  - `offline`: 离线设备数
  - `by_model`: 按型号统计

**异常**：
- `TokenExpiredError`: 凭据已过期
- `NetworkError`: 网络错误

**示例**：
```python
stats = api.get_device_statistics(home_id="123456")
print(f"总设备数: {stats['total']}")
print(f"在线: {stats['online']}, 离线: {stats['offline']}")
```

### 凭据管理

#### update_credential()

更新客户端使用的凭据。

```python
def update_credential(self, credential: Credential) -> None
```

**参数**：
- `credential`: 新的凭据对象

**使用场景**：
- 凭据刷新后更新客户端
- 切换用户

**示例**：
```python
# 刷新凭据
new_credential = auth_service.refresh_credential(api.credential)

# 更新客户端凭据
api.update_credential(new_credential)
```

#### credential

获取当前使用的凭据（属性）。

```python
@property
def credential(self) -> Credential
```

**返回**：
- `Credential`: 凭据对象

**示例**：
```python
credential = api.credential
print(f"用户ID: {credential.user_id}")
print(f"过期时间: {credential.expires_at}")
```

---

### 缓存管理

#### refresh_cache()

主动刷新缓存，强制从API重新获取数据。

```python
def refresh_cache(self, home_id: Optional[str] = None) -> None
```

**参数**：
- `home_id`: 家庭ID，如果指定则只刷新该家庭的缓存，否则刷新当前用户的所有缓存

**使用场景**：
- 通过米家APP添加了新设备后，需要立即获取
- 设备状态在外部发生变化，需要获取最新状态
- 定时任务开始前，确保数据是最新的

**示例**：
```python
# 刷新特定家庭的缓存
api.refresh_cache(home_id="123456")

# 刷新当前用户的所有缓存
api.refresh_cache()
```

#### clear_all_cache()

清空所有缓存数据。

```python
def clear_all_cache(self) -> None
```

**警告**：此方法会清空所有用户的所有缓存数据，谨慎使用！

**使用场景**：
- 系统维护
- 缓存数据损坏需要重建

**示例**：
```python
api.clear_all_cache()
```

#### 自动刷新缓存

SDK 在设备控制操作后会自动刷新缓存，这是标准做法，确保下次获取的是最新状态：

```python
# 控制设备后自动刷新缓存（默认行为）
api.control_device("device_123", 2, 1, True)

# 下次获取设备状态时会得到最新数据
device = api.get_device("device_123")
```

对于高频操作场景，可以禁用自动刷新以提高性能：

```python
# 连续调节亮度（禁用自动刷新）
for brightness in range(0, 100, 10):
    api.control_device(
        "light_123", 
        2, 
        2, 
        brightness, 
        refresh_cache=False
    )

# 操作完成后手动刷新
api.refresh_cache(home_id="123456")
```

---

## AsyncMijiaAPI（异步）

### 类定义

```python
class AsyncMijiaAPI:
    """米家API客户端（异步版本）
    
    提供与同步版本相同的接口，但所有方法都是异步的。
    适用于异步应用场景，如异步Web框架、并发设备控制等。
    """
```

### 初始化

与 `MijiaAPI` 相同，但通常使用 `create_async_api_client()` 工厂函数。

### 方法

所有方法与 `MijiaAPI` 相同，但都是异步方法（使用 `async def` 定义）。

#### 使用示例

```python
import asyncio

async def main():
    api = create_async_api_client(credential)
    
    # 获取家庭列表
    homes = await api.get_homes()
    
    # 获取设备列表
    devices = await api.get_devices(home_id=homes[0].id)
    
    # 控制设备
    success = await api.control_device(
        device_id=devices[0].did,
        siid=2,
        piid=1,
        value=True
    )
    
    print(f"控制结果: {success}")

asyncio.run(main())
```

#### 并发操作

```python
async def control_multiple():
    api = create_async_api_client(credential)
    
    # 并发控制多个设备
    results = await asyncio.gather(
        api.control_device("device_1", 2, 1, True),
        api.control_device("device_2", 2, 1, False),
        api.control_device("device_3", 2, 2, 50),
    )
    
    return results
```

---

## 工厂函数

### create_api_client()

创建同步API客户端。

```python
def create_api_client(
    credential: Credential,
    config_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    redis_client: Optional[Any] = None,
) -> MijiaAPI
```

**参数**：
- `credential`: 用户凭据对象
- `config_path`: 配置文件路径（可选）
- `cache_dir`: 缓存目录（可选）
- `redis_client`: Redis客户端（可选）

**返回**：
- `MijiaAPI`: 配置好的API客户端实例

**示例**：
```python
from mijiaAPI_V2 import create_api_client

api = create_api_client(credential)
```

### create_async_api_client()

创建异步API客户端。

```python
def create_async_api_client(
    credential: Credential,
    config_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    redis_client: Optional[Any] = None,
) -> AsyncMijiaAPI
```

参数和返回值与 `create_api_client()` 相同。

### create_api_client_from_file()

从文件加载凭据并创建API客户端。

```python
def create_api_client_from_file(
    credential_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    redis_client: Optional[Any] = None,
) -> MijiaAPI
```

**参数**：
- `credential_path`: 凭据文件路径（可选，默认 `configs/credential.json`）
- `config_path`: 配置文件路径（可选）
- `redis_client`: Redis客户端（可选）

**返回**：
- `MijiaAPI`: 配置好的API客户端实例

**异常**：
- `FileNotFoundError`: 凭据文件不存在
- `ValueError`: 凭据无效或已过期

**示例**：
```python
from mijiaAPI_V2 import create_api_client_from_file

# 使用默认路径
api = create_api_client_from_file()

# 使用自定义路径
api = create_api_client_from_file(
    credential_path=Path("my_credential.json")
)
```

### create_multi_user_clients()

创建多用户API客户端。

```python
def create_multi_user_clients(
    credentials: dict[str, Credential],
    config_path: Optional[Path] = None,
    redis_client: Optional[Any] = None,
) -> dict[str, MijiaAPI]
```

**参数**：
- `credentials`: 用户凭据字典，key为用户标识，value为Credential对象
- `config_path`: 配置文件路径（可选）
- `redis_client`: Redis客户端（可选）

**返回**：
- `dict[str, MijiaAPI]`: 用户API客户端字典

**示例**：
```python
from mijiaAPI_V2 import create_multi_user_clients

credentials = {
    "user_a": credential_a,
    "user_b": credential_b,
}

clients = create_multi_user_clients(credentials)

# 使用
devices_a = clients["user_a"].get_devices(home_id="123")
devices_b = clients["user_b"].get_devices(home_id="456")
```

---

## 认证服务

### create_auth_service()

创建认证服务。

```python
def create_auth_service(
    config_path: Optional[Path] = None,
    credential_store: Optional[ICredentialStore] = None
) -> AuthService
```

**参数**：
- `config_path`: 配置文件路径（可选）
- `credential_store`: 凭据存储实现（可选）

**返回**：
- `AuthService`: 认证服务实例

**示例**：
```python
from mijiaAPI_V2 import create_auth_service

auth_service = create_auth_service()

# 二维码登录
credential = auth_service.login_by_qrcode()

# 保存凭据
auth_service.save_credential(credential)
```

---

## 下一步

- [领域模型参考](02-领域模型.md) - Credential、Device、Home等模型
- [异常参考](03-异常处理.md) - 所有异常类型和处理方法
- [配置参考](04-配置选项.md) - 完整的配置选项说明
