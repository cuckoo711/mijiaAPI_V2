# 米家 API SDK 与 API Server 管理台

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

米家智能家居 Python SDK 的现代化重构版本，同时内置一个 FastAPI + Vue3 + Element Plus 的 API Server 管理后台。

本仓库可以作为两种形态使用：

- **SDK**：在 Python 项目里直接调用米家登录、家庭、设备、场景、设备规格和控制能力。
- **API Server 管理后台**：部署成一个本地或服务器上的米家 API 服务，通过网页完成扫码登录、同步家庭/设备/场景、创建 API Key，并向脚本、AI Agent、Home Assistant 或其他后端提供 HTTP API。

API Server 按单米家账号设计。管理台和对外 API 默认只监听本机，公网能力需要显式开启访问来源开关，并建议放在 HTTPS 反向代理后面。

## 适用场景

本 SDK 特别适合以下项目场景：

- **企业级智能家居平台** - 需要稳定可靠的设备控制能力，支持多用户并发
- **智能家居自动化系统** - 需要集成米家设备的自动化控制逻辑
- **物联网（IoT）应用** - 需要将米家设备接入更大的物联网生态
- **智能办公/酒店系统** - 需要批量管理和控制多个空间的智能设备
- **家庭助手/机器人** - 需要语音或 AI 控制米家设备
- **数据分析平台** - 需要采集和分析智能设备的状态数据
- **微服务架构** - 需要将设备控制作为独立服务部署
- **FastAPI/Django/Flask 应用** - 需要在 Web 应用中集成设备控制功能

相比原版，本重构版本提供了更好的：
- **可维护性** - 清晰的分层架构，便于理解和修改
- **可扩展性** - 依赖注入设计，易于添加新功能
- **可测试性** - 完整的类型注解和单元测试
- **生产就绪** - 缓存、日志、错误处理等企业级特性

## 核心特性

- ✅ **凭据与操作完全分离** - Credential 作为独立对象，灵活管理用户认证
- ✅ **多用户并发支持** - 每个用户拥有独立的客户端实例和缓存命名空间
- ✅ **清晰的分层架构** - 领域层、仓储层、服务层、基础设施层分离
- ✅ **完整的类型注解** - 全面的类型提示，支持 IDE 智能提示和静态类型检查
- ✅ **智能缓存管理** - 三层缓存架构（内存、Redis、文件），支持分布式部署
- ✅ **异步API支持** - 提供同步和异步两种API接口
- ✅ **结构化日志系统** - JSON 格式日志，支持请求追踪和敏感信息脱敏
- ✅ **依赖注入** - 便捷的工厂函数，自动组装所有依赖组件

## API Server 管理后台

### 功能范围

管理后台已经包含：

- 管理员初始化、登录和会话鉴权。
- 米家二维码登录、凭据状态查看、刷新和删除。
- 同步家庭、设备、场景到本地 SQLite。
- 家庭与设备列表、分类筛选、分页、设备 slug 维护、隐藏和只读/可控开关。
- 场景列表、场景 ID 复制、允许执行和隐藏开关。
- API Key 创建、启停、删除、调用次数统计和中文权限说明。
- 独立 API 使用说明页，包含 Header、curl/fetch 示例、每个接口的请求数据、返回说明和访问策略。
- 系统自检、运行时配置、系统安全、审计日志。
- 局域网/公网来源开关，以及可信反向代理的 `X-Forwarded-For` / `X-Real-IP` 识别。
- 同步互斥保护，避免多次点击同时触发米家同步。

### 最短部署路径

适合本机、家里服务器、NAS 或云服务器。示例默认监听 `127.0.0.1:8123`，先保证本机可用，再按需接反向代理。

#### 1. 准备运行环境

- Python 3.9+
- uv
- Node.js 18+
- npm

```bash
git clone git@github.com:cuckoo711/mijiaAPI_V2.git
cd mijiaAPI_V2

uv sync
cd web
npm ci
npm run build
cd ..
```

#### 2. 初始化本地数据

```bash
uv run python -m server.cli init
```

也可以在命令行直接创建初始管理员：

```bash
uv run python -m server.cli init --admin admin
```

没有用命令行创建管理员也没关系，第一次打开管理台会出现初始化页面。

#### 3. 启动服务

```bash
uv run python -m server.cli run
```

默认访问地址：

```text
http://127.0.0.1:8123
```

#### 4. 首次使用流程

1. 打开 `http://127.0.0.1:8123`。
2. 创建管理员并登录。
3. 进入“米家登录”，点击二维码登录，用米家 App 扫码。
4. 登录成功后点击“同步家庭/设备/场景”。
5. 进入“家庭与设备”，确认设备状态、访问权限和隐藏状态。
6. 进入“场景管理”，复制场景 ID，按需开启允许执行。
7. 进入“API Key”，创建调用方需要的最小权限。
8. 进入“API 使用”，复制调用示例。

### 常用环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MIJIA_SERVER_HOST` | `127.0.0.1` | API Server 监听地址。公网或局域网直连才需要改成 `0.0.0.0`。 |
| `MIJIA_SERVER_PORT` | `8123` | API Server 监听端口。 |
| `MIJIA_SERVER_DATA_DIR` | `.mijia/server` | 服务端数据目录。 |
| `MIJIA_SERVER_DATABASE_PATH` | `${MIJIA_SERVER_DATA_DIR}/server.sqlite3` | SQLite 数据库路径。 |
| `MIJIA_CREDENTIAL_PATH` | `.mijia/credential.json` | 米家扫码登录凭据文件路径。 |
| `MIJIA_PUBLIC_BASE_URL` | 空 | 对外展示的服务地址，例如 `https://miapi.example.com`。 |
| `MIJIA_WEB_DIST_DIR` | `web/dist` | 前端构建产物目录。 |
| `MIJIA_OPENAPI_ENABLED` | `false` | 是否开启 `/api/v1/openapi.json`。 |
| `MIJIA_DOCS_ENABLED` | `false` | 是否开启 `/docs` 和 `/redoc`。 |

### systemd 部署示例

假设项目放在 `/opt/mijia_server`，运行用户为 `root` 或你自己的服务用户：

```ini
[Unit]
Description=Mijia API Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/mijia_server
Environment=MIJIA_SERVER_HOST=127.0.0.1
Environment=MIJIA_SERVER_PORT=8123
Environment=MIJIA_SERVER_DATA_DIR=/opt/mijia_server/.mijia/server
Environment=MIJIA_SERVER_DATABASE_PATH=/opt/mijia_server/.mijia/server/server.sqlite3
Environment=MIJIA_CREDENTIAL_PATH=/opt/mijia_server/.mijia/credential.json
Environment=MIJIA_WEB_DIST_DIR=/opt/mijia_server/web/dist
Environment=MIJIA_PUBLIC_BASE_URL=https://miapi.example.com
ExecStart=/usr/bin/env uv run python -m server.cli run
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

部署和更新：

```bash
cd /opt/mijia_server
git pull --ff-only
uv sync
cd web
npm ci
npm run build
cd ..
uv run python -m server.cli init
systemctl daemon-reload
systemctl enable --now mijia-server
systemctl restart mijia-server
```

### Nginx 反向代理示例

推荐公网只暴露 HTTPS 反向代理，后端继续监听 `127.0.0.1`：

```nginx
server {
    listen 443 ssl http2;
    server_name miapi.example.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8123;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

管理台默认信任来自 `127.0.0.1/32` 和 `::1/128` 的反向代理头。反向代理在其他机器上时，需要在“系统安全”里把代理 IP 加入“可信代理地址”。

### 访问来源策略

本机请求始终允许。局域网和公网请求需要在“系统安全”里显式开启：

- **允许局域网请求**：允许私有网段访问对外 API 和 `/healthz`。
- **允许公网请求**：允许公网来源访问对外 API 和 `/healthz`。
- **反向代理模式**：信任可信代理传来的真实客户端 IP，再按真实来源判断。

管理台页面和 `/api/admin/*` 仍由管理员登录保护，不受局域网/公网来源开关拦截。这样清库或首次部署后，仍然可以通过反向代理完成初始化。

如果公网访问 `/healthz` 返回 `403 NETWORK_ACCESS_DENIED`，通常表示公网来源开关没有打开，这是预期的安全行为。管理台本身不会依赖公网 `/healthz`。

### 对外 API 使用

创建 API Key 后，把密钥放到 HTTP Header：

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://127.0.0.1:8123/api/v1/devices
```

JavaScript 示例：

```js
const response = await fetch("http://127.0.0.1:8123/api/v1/devices", {
  headers: {
    Authorization: "Bearer YOUR_API_KEY",
  },
});
const payload = await response.json();
```

常用接口：

| 方法 | 路径 | 权限 | 请求数据 | 说明 |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/status` | 读取服务状态 | 无 | 服务状态、版本、运行时间。 |
| `GET` | `/api/v1/account` | 读取服务状态 | 无 | 米家凭据状态。 |
| `GET` | `/api/v1/homes` | 读取家庭与设备 | 无 | 家庭列表。 |
| `GET` | `/api/v1/devices` | 读取家庭与设备 | 无 | 设备列表。 |
| `GET` | `/api/v1/devices/{device_slug}` | 读取家庭与设备 | 无 | 单个设备详情。 |
| `GET` | `/api/v1/devices/{device_slug}/state` | 读取家庭与设备 | 无 | 读取设备属性状态。 |
| `GET` | `/api/v1/devices/{device_slug}/spec` | 读取家庭与设备 | 无 | 读取设备规格，确认 `siid`、`piid`、`aiid`。 |
| `POST` | `/api/v1/devices/{device_slug}/properties` | 控制设备 | `{"siid":2,"piid":1,"value":true}` | 设置设备属性。 |
| `POST` | `/api/v1/devices/{device_slug}/actions` | 控制设备 | `{"siid":2,"aiid":1,"params":{}}` | 调用设备动作。 |
| `POST` | `/api/v1/batch/devices/properties` | 控制设备 | `{"items":[...]}` | 批量设置设备属性。 |
| `GET` | `/api/v1/scenes` | 读取家庭与设备 | 无 | 场景列表。 |
| `POST` | `/api/v1/scenes/{scene_id}/execute` | 执行场景 | 无 | 执行已授权场景。 |
| `POST` | `/api/v1/cache/refresh?home_id={home_id}` | 管理缓存 | 无 | 刷新 SDK 缓存，`home_id` 可选。 |
| `POST` | `/api/v1/cache/clear` | 管理缓存 | 无 | 清理 SDK 和本地缓存。 |
| `GET` | `/api/v1/logs?limit=100` | 读取审计日志 | 无 | 查看审计日志。 |

管理台“API 使用”页面会展示每个接口的请求数据、返回说明、注意事项和 curl 示例。若需要自动生成文档，可启动时设置：

```bash
export MIJIA_DOCS_ENABLED=true
export MIJIA_OPENAPI_ENABLED=true
uv run python -m server.cli run
```

然后访问：

- Swagger UI：`/docs`
- ReDoc：`/redoc`
- OpenAPI JSON：`/api/v1/openapi.json`

### 日常维护

```bash
# 查看服务自检
uv run python -m server.cli check

# 导出诊断信息
uv run python -m server.cli diagnose --output diagnose.json

# 更新代码和前端
git pull --ff-only
uv sync
cd web && npm ci && npm run build && cd ..
systemctl restart mijia-server
```

需要备份的关键文件：

- SQLite 数据库：`MIJIA_SERVER_DATABASE_PATH`
- 米家凭据：`MIJIA_CREDENTIAL_PATH`
- 如使用默认路径，还需要整个 `.mijia/` 目录

### 常见问题

**初始化后页面没有变化**

先刷新页面，再检查后端日志。初始化成功后 `/api/admin/bootstrap/state` 应返回 `{"initialized": true, ...}`。

**同步按钮可以连续点吗**

前端会在同步过程中禁用按钮，后端也会拒绝第二个同步请求并返回 `409 SYNC_IN_PROGRESS`。

**API 返回 `NETWORK_ACCESS_DENIED`**

当前请求来源没有被允许。进入“系统安全”开启局域网或公网请求；如果走反向代理，还要确认可信代理地址和转发头。

**API Key 创建后还能再次查看完整密钥吗**

不能。完整 API Key 只在创建时显示一次，之后只保存哈希和前缀。

**可以不用 Docker 吗**

可以。当前服务只要求 Python、Node 和 SQLite，直接运行、systemd、NAS 套件、Docker 或反向代理后部署都可以。仓库的核心要求是保证服务能访问数据目录、数据库、凭据文件和前端构建产物。

## SDK 快速开始

### 安装

```bash
# 使用 uv 安装依赖
uv sync

# 或使用 pip
pip install -e .
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
├── server/                 # FastAPI API Server 与管理端接口
│   ├── app.py             # 应用工厂、路由和鉴权
│   ├── cli.py             # mijia-server 命令行
│   ├── config.py          # 服务端环境变量配置
│   ├── db.py              # SQLite 初始化
│   ├── mijia_runtime.py   # SDK 与服务端运行时桥接
│   └── store.py           # SQLite 数据读写
├── web/                    # Vue3 + Element Plus 管理台
│   ├── src/               # 前端源码
│   └── dist/              # npm run build 后的静态产物
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
│   ├── scene_repository.py     # 智能仓储
│   └── device_spec_repository.py  # 设备规格仓储
├── services/               # 服务层
│   ├── auth_service.py    # 认证服务
│   ├── device_service.py  # 设备服务
│   ├── scene_service.py   # 智能服务
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
5. **智能控制** (`05_scene_control.py`) - 获取和执行智能

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

完整更新记录见 [CHANGELOG.md](CHANGELOG.md)。

### 2026-05-22

- 新增 FastAPI + Vue3 + Element Plus 管理后台部署和使用说明。
- 管理后台支持管理员初始化、二维码登录、家庭/设备/场景同步、API Key、访问来源策略、反向代理模式、系统自检和审计日志。
- 系统自检增加中文解释。
- 同步增加前端 loading 和后端互斥保护，避免重复触发同步。
- API 使用说明从 API Key 页面拆分为独立菜单页。
- 管理台菜单改成分级导航。
- 家庭与设备默认分页调整为每页 20 条。

### v2.0.0 (2026.03.13)

- 完全重构，采用分层架构
- 凭据与操作完全分离
- 支持多用户并发场景
- 添加完整的类型注解
- 实现三层缓存架构
- 支持 Redis 分布式缓存
- 提供异步API接口
- 结构化日志系统
