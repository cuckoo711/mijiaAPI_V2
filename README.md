# 米家API SDK - 重构版本 (V2)

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

米家智能家居 Python SDK 的现代化重构版本，采用清晰的分层架构设计。

## 核心特性

- ✅ **凭据与操作完全分离** - Credential 作为独立对象，灵活管理用户认证
- ✅ **多用户并发支持** - 每个用户拥有独立的客户端实例和缓存命名空间
- ✅ **清晰的分层架构** - 领域层、仓储层、服务层、基础设施层分离
- ✅ **完整的类型注解** - 全面的类型提示，支持 IDE 智能提示和静态类型检查
- ✅ **智能缓存管理** - 三层缓存架构（内存、Redis、文件），支持分布式部署
- ✅ **异步API支持** - 提供同步和异步两种API接口
- ✅ **结构化日志系统** - JSON 格式日志，支持请求追踪和敏感信息脱敏
- ✅ **依赖注入** - 便捷的工厂函数，自动组装所有依赖组件

## 快速开始

### 安装

```bash
# 使用 uv 安装依赖
uv sync

# 或使用 pip
pip install -r requirements.txt
```

### 首次使用：登录认证

```python
from mijiaAPI_V2 import create_auth_service

# 创建认证服务
auth_service = create_auth_service()

# 二维码登录（首次使用）
print("请使用米家APP扫描二维码登录：")
credential = auth_service.login_by_qrcode()

# 保存凭据（默认保存到 .mijia/credential.json）
auth_service.save_credential(credential)
print("登录成功，凭据已保存！")
```

### 基本使用

```python
from mijiaAPI_V2 import create_api_client_from_file

# 从文件加载凭据并创建API客户端
api = create_api_client_from_file()

# 获取家庭列表
homes = api.get_homes()
for home in homes:
    print(f"家庭: {home.name} (ID: {home.id})")

# 获取设备列表
home_id = homes[0].id
devices = api.get_devices(home_id)
for device in devices:
    status = "在线" if device.is_online() else "离线"
    print(f"{device.name} ({device.model}) - {status}")

# 控制设备（需要先查看设备规格确定 siid 和 piid）
api.control_device(
    device_id=devices[0].did,
    siid=2,  # 服务ID
    piid=1,  # 属性ID（通常是开关）
    value=True  # 打开设备
)
```

### 查看设备规格

```python
# 获取设备规格（了解设备支持的属性和操作）
device = devices[0]
spec = api.get_device_spec(device.model)

if spec:
    print(f"设备: {spec.name}")
    print(f"属性数量: {len(spec.properties)}")
    
    # 查看所有属性
    for prop in spec.properties:
        print(f"  - {prop.name} (siid={prop.siid}, piid={prop.piid})")
```

### 批量操作

```python
# 批量获取设备属性
requests = [
    {"did": device.did, "siid": 2, "piid": 1},  # 设备1的开关状态
    {"did": device.did, "siid": 2, "piid": 2},  # 设备1的亮度
]
results = api.get_device_properties(requests)

# 批量设置设备属性
set_requests = [
    {"did": device1.did, "siid": 2, "piid": 1, "value": True},   # 打开设备1
    {"did": device2.did, "siid": 2, "piid": 1, "value": False},  # 关闭设备2
]
results = api.batch_control_devices(set_requests)
```

### 缓存管理

```python
# SDK 自动缓存常用数据，提升性能
devices = api.get_devices(home_id)  # 第一次从API获取
devices = api.get_devices(home_id)  # 第二次从缓存读取（快 1000+ 倍）

# 手动刷新缓存
api.refresh_cache(home_id=home_id)  # 刷新特定家庭的缓存
api.refresh_cache()  # 刷新当前用户的所有缓存
api.clear_all_cache()  # 清空所有缓存
```

## 高级用法

### 处理凭据过期

```python
from mijiaAPI_V2 import create_auth_service
from mijiaAPI_V2.domain.exceptions import TokenExpiredError

auth_service = create_auth_service()

try:
    api = create_api_client_from_file()
    devices = api.get_devices(home_id)
except TokenExpiredError:
    # 凭据过期，需要重新登录
    print("凭据已过期，请重新登录")
    credential = auth_service.login_by_qrcode()
    auth_service.save_credential(credential)
```

### 多用户场景

```python
from mijiaAPI_V2 import create_api_client
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore

# 加载不同用户的凭据
store = FileCredentialStore()
credential_a = store.load(Path("user_a_credential.json"))
credential_b = store.load(Path("user_b_credential.json"))

# 创建独立的客户端（状态完全隔离）
api_a = create_api_client(credential_a)
api_b = create_api_client(credential_b)

# 用户A的操作
homes_a = api_a.get_homes()
devices_a = api_a.get_devices(homes_a[0].id)

# 用户B的操作（互不影响）
homes_b = api_b.get_homes()
devices_b = api_b.get_devices(homes_b[0].id)
```

### 异步API

```python
import asyncio
from mijiaAPI_V2 import create_async_api_client_from_file

async def main():
    # 创建异步客户端
    api = create_async_api_client_from_file()
    
    # 异步获取数据
    homes = await api.get_homes()
    devices = await api.get_devices(homes[0].id)
    
    # 并发控制多个设备
    await asyncio.gather(
        api.control_device(device1.did, 2, 1, True),
        api.control_device(device2.did, 2, 1, False),
    )

asyncio.run(main())
```

## 配置

### 使用配置文件

创建 `config.toml` 文件：

```toml
[api]
base_url = "https://api.mina.mi.com"

[network]
default_timeout = 30
max_retries = 3

[cache]
device_list_ttl = 300
device_state_ttl = 30

[redis]
enabled = false
host = "localhost"
port = 6379

[logging]
level = "INFO"
format = "json"
```

### 使用环境变量

```bash
export MIJIA_REDIS_ENABLED=true
export MIJIA_REDIS_HOST=redis.example.com
export MIJIA_REDIS_PORT=6379
export MIJIA_LOG_LEVEL=DEBUG
```

## Redis 缓存（可选）

Redis 用于多进程/多服务器场景的分布式缓存。

```python
from mijiaAPI_V2 import create_api_client
from mijiaAPI_V2.infrastructure.redis_client import RedisClient
from mijiaAPI_V2.core.config import ConfigManager

# 配置 Redis
config = ConfigManager()
config.set("REDIS_ENABLED", True)
config.set("REDIS_HOST", "localhost")

# 创建 Redis 客户端
redis_client = RedisClient(config)

# 创建带 Redis 的 API 客户端
api = create_api_client(credential, redis_client=redis_client)
```

## 项目结构

```
mijiaAPI_V2/
├── core/                   # 核心配置和工具
│   ├── config.py          # 配置管理器
│   └── logging.py         # 日志系统
├── domain/                 # 领域层
│   ├── models.py          # 领域模型（Credential、Device等）
│   └── exceptions.py      # 异常定义
├── infrastructure/         # 基础设施层
│   ├── http_client.py     # HTTP客户端
│   ├── cache_manager.py   # 缓存管理器
│   ├── crypto_service.py  # 加密服务
│   ├── credential_provider.py  # 凭据提供者
│   └── credential_store.py     # 凭据存储
├── repositories/           # 仓储层
│   ├── interfaces.py      # 仓储接口
│   ├── device_repository.py    # 设备仓储
│   ├── home_repository.py      # 家庭仓储
│   ├── scene_repository.py     # 场景仓储
│   └── device_spec_repository.py  # 设备规格仓储
├── services/               # 服务层
│   ├── auth_service.py    # 认证服务
│   ├── device_service.py  # 设备服务
│   ├── scene_service.py   # 场景服务
│   └── statistics_service.py  # 统计服务
├── api_client.py          # API客户端（MijiaAPI、AsyncMijiaAPI）
└── factory.py             # 依赖注入工厂
```

## 示例代码

查看 `examples/` 目录获取完整示例（共 11 个）：

### 基础示例
1. **认证和凭据管理** (`01_authentication.py`) - 二维码登录、凭据保存和管理
2. **快速开始** (`02_quick_start.py`) - 基本的设备获取和控制
3. **设备控制** (`03_device_control.py`) - 各种设备控制方法
4. **设备规格查询** (`04_device_spec.py`) - 查看设备属性和操作
5. **场景控制** (`05_scene_control.py`) - 获取和执行场景

### 高级示例
6. **批量操作** (`06_batch_operations.py`) - 批量控制设备，性能优化
7. **错误处理** (`07_error_handling.py`) - 完整的错误处理策略
8. **自定义翻译** (`08_custom_translations.py`) - 自定义设备规格翻译
9. **配置管理** (`09_configuration.py`) - 配置文件和环境变量
10. **缓存管理** (`10_cache_management.py`) - 缓存使用和性能优化
11. **完整工作流** (`11_complete_workflow.py`) - 智能家居自动化脚本

详细说明请参考 `examples/README.md`

## 测试

```bash
# 运行所有测试
uv run pytest

# 运行单元测试
uv run pytest tests/unit/

# 生成覆盖率报告
uv run pytest --cov=mijiaAPI_V2 --cov-report=html
```

## 开发

### 代码质量工具

```bash
# 使用 Makefile（推荐）
make format      # 代码格式化
make lint        # 代码质量检查
make type-check  # 类型检查
make test        # 运行测试
make test-cov    # 测试覆盖率
make clean       # 清理缓存文件

# 或直接使用工具
uv run black mijiaAPI_V2/
uv run isort mijiaAPI_V2/
uv run mypy mijiaAPI_V2/
uv run flake8 mijiaAPI_V2/
```

### 清理项目文件

```bash
# 清理缓存和临时文件
make clean

# 清理所有生成文件（包括覆盖率报告）
make clean-all

# 或使用脚本
./scripts/clean.sh
uv run python scripts/clean.py
```

清理内容包括：
- Python 缓存文件（`__pycache__/`, `*.pyc`）
- 测试覆盖率文件（`.coverage`, `htmlcov/`）
- 构建产物（`dist/`, `build/`, `*.egg-info/`）
- 工具缓存（`.mypy_cache/`, `.pytest_cache/`）
- 临时文件（`*.tmp`, `*.log`, `.DS_Store`）

详细说明请参考 `scripts/README.md`

## 架构设计

本项目采用分层架构设计：

1. **领域层** - 核心业务实体和异常
2. **仓储层** - 数据访问抽象和实现
3. **服务层** - 业务逻辑封装
4. **基础设施层** - HTTP、缓存、加密等基础组件
5. **API客户端层** - 对外提供的统一接口

详细文档请参考：
- [项目概览](docs/架构设计/01-项目概览.md)
- [分层架构](docs/架构设计/02-分层架构.md)
- [文档索引](docs/README.md)

## 致谢

本项目受到 [Do1e/mijia-api](https://github.com/Do1e/mijia-api) 的启发。特别感谢原作者 Do1e 的开创性工作，他的算法和实现思路为本项目提供了重要参考，为米家智能家居的 Python 生态做出了卓越贡献。

本项目在借鉴其核心算法的基础上，采用了现代化的分层架构设计和工程实践，旨在提供更好的开发体验、可维护性和扩展性。

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v2.0.0 (2026.03.13)

- 完全重构，采用分层架构
- 凭据与操作完全分离
- 支持多用户并发场景
- 添加完整的类型注解
- 实现三层缓存架构
- 支持 Redis 分布式缓存
- 提供异步API接口
- 结构化日志系统
