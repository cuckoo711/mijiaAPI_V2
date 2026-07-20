# 米家 API SDK & Server

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

米家智能家居 Python SDK，内置 FastAPI + Vue3 管理后台。

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
| 设备管理 | 家庭/设备列表、状态查询、隐藏/只读控制 |
| 场景控制 | 场景列表、一键执行、权限管理 |
| API Key | 创建/启停/删除，细粒度权限控制 |
| 实时同步进度 | 同步时显示进度条、步骤、设备/场景计数 |
| 安全策略 | 局域网/公网开关、可信代理、审计日志 |

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
| `GET` | `/api/v1/devices` | 设备列表 |
| `GET` | `/api/v1/devices/{slug}/state` | 设备状态 |
| `POST` | `/api/v1/devices/{slug}/properties` | 控制设备 |
| `POST` | `/api/v1/devices/{slug}/actions` | 执行动作 |
| `GET` | `/api/v1/scenes` | 场景列表 |
| `POST` | `/api/v1/scenes/{id}/execute` | 执行场景 |
| `GET` | `/api/v1/logs` | 审计日志 |

管理台「API 使用」页面有完整的请求示例和参数说明。交互式文档（Swagger/ReDoc）可在「系统安全」中开启。

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
| `MIJIA_CREDENTIAL_PATH` | `configs/credential.json` | 凭据文件 |
| `MIJIA_LOG_LEVEL` | `INFO` | 日志级别（支持 `DEBUG`） |

## 部署

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
├── mijiaAPI_V2/        # SDK 核心
│   ├── api_client.py   # API 客户端
│   ├── core/           # 配置、日志
│   ├── domain/         # 领域模型
│   ├── repositories/   # 数据仓储
│   ├── services/       # 业务服务
│   └── infrastructure/ # HTTP、缓存、加密
├── server/             # FastAPI 服务端
│   ├── app.py          # 路由和鉴权
│   ├── mijia_runtime.py # SDK 桥接层
│   └── store.py        # SQLite 读写
├── web/                # Vue3 管理后台
├── examples/           # 11 个示例
├── docs/               # 详细文档
├── build.py            # 多平台构建脚本
├── build.sh            # Linux/macOS 构建脚本
├── build.bat           # Windows 构建脚本
└── mijia-server.spec   # PyInstaller 配置
```

## 打包为可执行文件

项目支持打包为独立可执行文件，无需安装 Python 即可运行。

### 本地构建

```bash
# 安装构建工具
uv pip install pyinstaller

# 构建前端
cd web && npm ci && npm run build && cd ..

# 构建可执行文件
uv run pyinstaller --clean --noconfirm mijia-server.spec

# 输出目录: dist/mijia-server/
```

### 多平台构建

项目支持以下平台的自动构建：

| 平台 | 架构 | 输出格式 |
|------|------|----------|
| Windows | x64 | ZIP |
| Linux | x64 | TAR.GZ |
| Linux | ARM64 | TAR.GZ |
| macOS | x64 | TAR.GZ |
| macOS | ARM64 | TAR.GZ |

推送版本标签后会自动触发 GitHub Actions 构建：

```bash
git tag v2.1.0
git push origin v2.1.0
```

### 运行可执行文件

```bash
# 解压后直接运行
./mijia-server init
./mijia-server run
```

默认监听 `127.0.0.1:8123`。

## 常见问题

**同步按钮可以连续点吗？** 前端会禁用按钮，后端返回 `409 SYNC_IN_PROGRESS`。

**API 返回 `NETWORK_ACCESS_DENIED`？** 需在「系统安全」开启局域网/公网请求。

**API Key 创建后还能查看完整密钥吗？** 不能，只在创建时显示一次。

**支持 Docker 吗？** 支持，核心只需 Python、Node 和 SQLite。
