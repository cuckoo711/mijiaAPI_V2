# 米家 API SDK & Server

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

> **非官方第三方项目。** 与小米 / 米家无隶属或授权关系。仅操作你有权控制的账号与设备，并遵守平台用户协议。详见 [免责声明与使用边界](DISCLAIMER.md)。

第三方米家智能家居 Python SDK，内置 FastAPI + Vue3 管理后台。

**两种使用形态：**

| 形态 | 说明 |
|------|------|
| **SDK** | 在 Python 项目中直接调用米家登录、设备控制、场景执行等能力 |
| **API Server** | 部署为本地/服务器服务，通过网页管理，对外提供 HTTP API |

> 管理台默认监听 `127.0.0.1:8123`，公网使用需开启访问开关并建议搭配 HTTPS 反向代理。

## 快速部署

### 环境要求

- Python 3.9+ / uv
- Node.js 18+ / npm

### 一键启动

```bash
git clone git@github.com:cuckoo711/mijiaAPI_V2.git
cd mijiaAPI_V2

# 安装依赖 & 构建前端
uv sync && cd web && npm ci && npm run build && cd ..

# 初始化 & 启动
uv run python -m server.cli init
uv run python -m server.cli run
```

打开 `http://127.0.0.1:8123` → 创建管理员 → 扫码登录米家 → 同步家庭/设备/场景 → 开始使用。

### 首次使用流程

1. 打开管理台，创建管理员账号
2. 进入「米家登录」，用米家 App 扫码
3. 点击「同步家庭/设备/场景」（支持实时进度显示）
4. 进入「API Key」创建调用密钥
5. 使用 API 接入你的应用

## 核心功能

| 功能 | 说明 |
|------|------|
| 扫码登录 | 米家 App 扫码，凭据自动保存和刷新 |
| 设备管理 | 家庭/设备列表、实时属性状态、按规格手动写入属性与执行动作、隐藏/只读控制 |
| 场景控制 | 场景列表、明确确认后手动执行、权限管理 |
| API Key | 创建/启停/删除，细粒度权限控制 |
| 实时同步进度 | 同步时显示进度条、步骤、设备/场景计数 |
| 安全策略 | 全站网络 ACL、可信代理（默认关）、Cookie+CSRF、操作回执、审计补写队列、凭据加密 |
| 管理改密 | 管理台改密 + CLI `reset-admin` |

## 对外 API

```bash
# 基本用法
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://127.0.0.1:8123/api/v1/devices
```

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/status` | 服务状态 |
| `GET` | `/api/v1/homes` | 家庭列表 |
| `GET` | `/api/v1/devices` | 设备列表（可选 `include_spec` / `include_raw`） |
| `GET` | `/api/v1/devices/{slug}/state` | 设备状态 |
| `POST` | `/api/v1/devices/{slug}/properties` | 控制设备 |
| `POST` | `/api/v1/devices/{slug}/actions` | 执行动作 |
| `GET` | `/api/v1/scenes` | 场景列表 |
| `POST` | `/api/v1/scenes/{id}/execute` | 执行场景 |
| `GET` | `/api/v1/logs` | 审计日志 |
| `GET` | `/api/v1/operations/{operation_id}` | 查询当前 API Key 自己发起的控制操作回执 |

管理台「API 使用」页面有完整的请求示例和参数说明。交互式文档（Swagger/ReDoc）可在「系统安全」中开启。

控制请求出现 `409 EXECUTION_UNKNOWN` 时，命令可能已送达，服务不会自动重发；请先查询设备状态或场景效果，再决定后续操作。查询请求与发送前的连接失败仍可重试。

批量属性接口 `/api/v1/batch/devices/properties` 的每项必须包含 `device`（兼容 `device_id`）、正整数 `siid` / `piid` 和 `value`。SDK 批量请求使用 `did`（兼容 `device_id`）。服务会在发送整批命令前检查全部属性规格、写权限、类型、范围和步长。

管理台支持密钥资源范围、有效期、启停、删除与轮换。`POST /api/admin/api-keys/{id}/rotate` 在同一事务中创建新密钥并停用旧密钥；默认继承原权限和有效期，可传 `expires_at` 修改有效期，传 `null` 取消有效期。新密钥仅在创建或轮换响应中显示一次。

在「家庭与设备」打开「状态与控制」，可读取状态与规格，填写属性值或动作参数后明确点击确认；「场景管理」提供手动执行入口。管理员写入要求设备可控或场景可执行，并拒绝隐藏资源。读取状态、打开表单、审计补写均不会自动执行设备操作。接口、参数与 Cookie/CSRF 说明见 [API Server 开发启动](docs/开发指南/05-API-Server-开发启动.md#管理员手动控制与操作回执)。

控制响应进入审计阶段后，`X-Operation-ID` 标识该次操作，`X-Audit-Delivery` 区分 `stored`、`queued`、`unavailable`；审计落盘状态与设备执行结果分开判断。队列在启动时和运行中约每 10 秒补写，也可在管理台显式补写。完全未能保存的事件无法补写，需排查日志与存储。`/healthz` 用于 HTTP 存活检测，`/readyz` 检查 SQLite 可写、前端入口与审计状态，依赖异常返回 503。详细恢复步骤见 [部署运维说明](deploy/README.md#依赖就绪与审计恢复)。

源码测试、模拟浏览器和隔离 Docker 验证只能证明对应的软件路径；真实米家授权、具体设备规格、共享家庭场景权限、设备状态与实际动作效果仍需在目标环境验收。HTTP 200、控制 ACK、操作回执和就绪检查均不代替物理设备验收。

## 免责声明与使用边界

本仓库是**第三方开源项目**，与小米科技有限责任公司 / 米家**无**隶属、授权或合作关系，**不是**官方 SDK 或服务。文档与界面中的「米家」「Xiaomi」等仅用于指明互操作目标，商标归权利人所有。

- 仅在你**有权控制**的账号、家庭与设备上使用
- 自行遵守当地法律与米家/小米平台用户协议
- 勿冒充官方、勿对外商业代控、勿用于撞库或接口滥用
- 软件按现状提供，不附带担保；详见 [DISCLAIMER.md](DISCLAIMER.md)

参与贡献前请阅读 [DISCLAIMER.md](DISCLAIMER.md) 中的贡献者约定。

## SDK 使用

```python
from mijiaAPI_V2 import create_api_client_from_file

# 加载凭据并创建客户端
api = create_api_client_from_file()

# 获取家庭和设备
homes = api.get_homes()
devices = api.get_devices(homes[0].id)

# 控制设备
api.control_device(device_id=devices[0].did, siid=2, piid=1, value=True)
```

更多示例见 `examples/` 目录。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MIJIA_SERVER_HOST` | `127.0.0.1` | 监听地址 |
| `MIJIA_SERVER_PORT` | `8123` | 监听端口 |
| `MIJIA_SERVER_DATA_DIR` | `configs` | 数据目录 |
| `MIJIA_SERVER_DATABASE_PATH` | `configs/server/server.sqlite3` | SQLite 路径 |
| `MIJIA_CREDENTIAL_PATH` | `configs/credential.json` | 凭据文件（AES-GCM 加密） |
| `MIJIA_WEB_DIST_DIR` | `web/dist` | 前端静态资源 |
| `MIJIA_SERVER_LOG_LEVEL` | `INFO` | 日志级别（支持 `DEBUG`） |
| `MIJIA_BOOTSTRAP_ALLOW_PRIVATE` | 空 | `1` 时允许未初始化实例从私网首次建管理员，并原子启用局域网访问策略（Docker）；不启用公网 |
| `MIJIA_CREDENTIAL_SECRET` | 空 | 可选凭据加密密钥；不设则用 `.credential_key` |

也可编辑 `configs/server.toml`（可用 `python -m server.cli write-config` 生成）；环境变量优先。

### 常用 CLI

```bash
uv run python -m server.cli init
uv run python -m server.cli run
uv run python -m server.cli check
uv run python -m server.cli status          # 版本 / 路径 / 磁盘占用
uv run python -m server.cli reset-admin     # 本机重置管理员密码
uv run python -m server.cli purge-audit
uv run python -m server.cli purge-cache     # 可加 --all
uv run python -m server.cli write-config
```

## 部署

### Docker Compose

在仓库根目录执行即可构建并后台启动：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

默认只绑定本机 `127.0.0.1:8123`，启动后访问 `http://127.0.0.1:8123`。数据、SQLite 数据库、米家凭据、加密密钥和缓存持久化在命名卷 `mijia-data` 中。

Docker 会把宿主回环 HTTP 转为容器的私网来源。Compose 默认设置 `MIJIA_BOOTSTRAP_ALLOW_PRIVATE=1`，仅在尚无管理员时放行首页、静态资源和首次创建入口；首次私网创建管理员会同时启用 `ALLOW_LAN_ACCESS`，使随后登录可用，`ALLOW_PUBLIC_ACCESS` 仍关闭。已有管理员的实例不会因该变量自动修改访问策略。

> 从 v3.7.3 及更早版本升级的实例，旧卷名是 `deploy_mijia-data`，需要按
> [`deploy/README.md`](deploy/README.md#从旧卷名迁移仅影响-v373-及更早已部署的实例) 搬迁一次，否则会挂到空卷。

首次创建管理员可以直接打开管理台，或执行：

```bash
docker compose -f deploy/docker-compose.yml run --rm mijia-server mijia-server init --admin admin --allow-lan
```

常用维护命令：

```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f mijia-server
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml up -d --build
```

如需从局域网访问，在 `deploy/` 目录（compose 文件旁边）创建未提交的 `.env`，例如：

```dotenv
MIJIA_BIND_ADDRESS=0.0.0.0
MIJIA_HOST_PORT=8123
MIJIA_BOOTSTRAP_ALLOW_PRIVATE=0
MIJIA_SERVER_LOG_LEVEL=INFO
```

改为非本机绑定后，建议关闭私网首次创建入口，使用容器内 `init --admin admin --allow-lan` 创建管理员并明确启用局域网策略。更多说明见 [`deploy/README.md`](deploy/README.md)。

Docker 生命周期验证可复用以下命令。测试仅创建带随机前缀的隔离卷和回环端口，覆盖首次创建、Cookie/CSRF、密钥撤销、重启/重建持久化及整卷备份恢复；不会读取生产卷或调用真实米家设备。

```bash
python tests/docker/smoke.py --image mijia-server:latest --report docker-smoke-report.json
```

### systemd

仓库提供加固示例单元，见 [`deploy/mijia-server.service`](deploy/mijia-server.service) 与
[`deploy/mijia-server.env.example`](deploy/mijia-server.env.example)。

```bash
sudo cp deploy/mijia-server.service /etc/systemd/system/
sudo cp deploy/mijia-server.env.example /etc/mijia-server.env
# 按需修改路径与 User=
sudo systemctl daemon-reload
sudo systemctl enable --now mijia-server
```

默认仅监听 `127.0.0.1`。若经 Nginx 反代并需要按真实客户端 IP 做网络策略，请在管理台开启
`TRUST_PROXY_HEADERS`，并正确配置 `TRUSTED_PROXY_CIDRS`。

### Nginx 反向代理

```nginx
server {
    listen 443 ssl http2;
    server_name miapi.example.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8123;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## 项目结构

```
mijiaAPI_V2/
├── mijiaAPI_V2/           # SDK 核心
├── server/                # FastAPI 服务端
├── web/                   # Vue3 管理台
├── configs/               # 运行时数据与 TOML 模板
├── docs/ · examples/ · tests/
├── deploy/                # Docker / systemd / 打包 / 运维脚本
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── packaging/         # build 脚本与 mijia-server.spec
│   ├── scripts/           # clean / release notes / 设备规格工具
│   └── assets/            # 应用图标
├── pyproject.toml · Makefile · README.md
└── .dockerignore          # 需在仓库根（Docker build context）
```

管理台使用 HttpOnly Cookie 会话 + CSRF；对外 API 仍用 `Authorization: Bearer <api_key>`。
SDK 与 Server 默认数据目录均为 `configs/`（旧 `.mijia/` 启动时迁移后删除）。
详见 [docs/开发指南/05-API-Server-开发启动.md](docs/开发指南/05-API-Server-开发启动.md)。

## 打包为可执行文件

项目支持打包为独立可执行文件，无需安装 Python 即可运行。

### 本地构建

```bash
# 安装构建工具
uv pip install pyinstaller pillow

# 一键构建（前端 + 可执行文件）
uv run python deploy/packaging/build.py

# 或分步：
cd web && npm ci && npm run build && cd ..
uv run pyinstaller --clean --noconfirm deploy/packaging/mijia-server.spec
```

输出目录：`dist/`。

### 多平台构建

项目支持以下平台的自动构建：

| 平台 | 架构 | 产物 |
|------|------|------|
| Windows | x64 | `mijia-server-windows-x64.exe` |
| Linux | x64 | `mijia-server-linux-x64` |
| Linux | ARM64 | `mijia-server-linux-arm64` |
| macOS | ARM64 | `mijia-server-macos-arm64` |

产物是 PyInstaller 单文件可执行程序，直接挂在 Release 上，不额外打包成压缩包。Release 同时提供 `SHA256SUMS`，用于核对下载文件的 SHA-256。

Android 手机独立运行服务的测试 APK 见 [Android 测试版下载](https://github.com/cuckoo711/mijiaAPI_V2/releases/tag/v3.9.1-android-test.1)。Android 7.0 起，优先下载 `universal` 通用包；安装使用、兼容性与验收范围见 [Android 说明](android/README.md)。后续版本会自动构建并附带安卓测试包。

> macOS Intel（x64）不再随版本发布：标准运行器里最后一个 Intel macOS 镜像
> `macos-13` 已于 2025 年 12 月停止支持，而 PyInstaller 无法交叉编译。Intel Mac
> 用户请用 `uv sync` 从源码运行，或自行在本机执行上面的打包命令。

推送版本标签后会自动触发 GitHub Actions 构建：

```bash
git tag v3.9.1
git push origin v3.9.1
```

### 运行可执行文件

```bash
# Linux x64 示例；ARM64/macOS 请替换为上表中的对应文件名
chmod +x mijia-server-linux-x64
./mijia-server-linux-x64 init
./mijia-server-linux-x64 run
```

```powershell
# Windows x64
.\mijia-server-windows-x64.exe init
.\mijia-server-windows-x64.exe run
```

默认监听 `127.0.0.1:8123`。

## 常见问题

**同步按钮可以连续点吗？** 前端会禁用按钮，后端返回 `409 SYNC_IN_PROGRESS`；进度接口按 `task_id` 区分轮次。

**API 返回 `NETWORK_ACCESS_DENIED`？** 需在「系统安全」开启局域网/公网请求。策略覆盖管理台与对外 API。

**API Key 创建后还能查看完整密钥吗？** 不能，只在创建时显示一次。

**忘记管理员密码？** 本机执行 `python -m server.cli reset-admin`。

**管理台登录态存在哪？** HttpOnly Cookie（`mijia_admin_session`）+ CSRF；不要跨域依赖 Cookie。

**支持 Docker 吗？** 支持：`docker compose -f deploy/docker-compose.yml up -d --build`，详见 [`deploy/README.md`](deploy/README.md)。
