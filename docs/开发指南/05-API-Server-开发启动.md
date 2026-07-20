# API Server 开发启动

本项目在 SDK 外提供 `server/`（FastAPI）与 `web/`（Vue3 管理台）。当前行为以 **v3.7.x** 为准（默认数据目录 `configs/`，部署资产在 `deploy/`）。

## 后端

初始化本地 SQLite：

```bash
uv run python -m server.cli init
# 可选：一并创建管理员
uv run python -m server.cli init --admin admin --password 'your-password'
```

启动：

```bash
uv run python -m server.cli run
```

常用运维命令：

```bash
uv run python -m server.cli check          # 系统自检
uv run python -m server.cli status         # 版本、路径、库/缓存体积
uv run python -m server.cli diagnose       # 导出诊断信息
uv run python -m server.cli reset-admin    # 本机重置管理员密码
uv run python -m server.cli purge-audit    # 清理过期审计
uv run python -m server.cli purge-cache    # 清理过期磁盘缓存（可加 --all）
uv run python -m server.cli write-config   # 从模板生成 configs/server.toml
```

默认监听 `127.0.0.1:8123`。常用环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `MIJIA_SERVER_HOST` | `127.0.0.1` | 监听地址 |
| `MIJIA_SERVER_PORT` | `8123` | 端口 |
| `MIJIA_SERVER_DATA_DIR` | `configs` | 数据目录 |
| `MIJIA_SERVER_DATABASE_PATH` | `configs/server/server.sqlite3` | SQLite |
| `MIJIA_CREDENTIAL_PATH` | `configs/credential.json` | 米家凭据（落盘加密） |
| `MIJIA_WEB_DIST_DIR` | `web/dist` | 前端构建产物 |
| `MIJIA_BOOTSTRAP_ALLOW_PRIVATE` | 空 | 设为 `1` 时允许私网 IP 完成首次建管理员（Docker 常用） |
| `MIJIA_CREDENTIAL_SECRET` | 空 | 可选；不设则使用同目录 `.credential_key` |

也可通过 `configs/server.toml` 配置（环境变量优先）。可用 `write-config` 从模板生成。

旧版项目根目录 `.mijia/` 会在启动时迁入 `configs/`，完成后**删除** `.mijia` 与 `.mijia_backup*`（不留备份）。SDK 默认凭据/缓存亦为 `configs/`。

## 访问来源与反向代理

服务默认只监听本机。要让局域网或公网客户端访问，需要同时满足：

1. 监听可被外部访问的地址（如 `MIJIA_SERVER_HOST=0.0.0.0`），或由反向代理转发到本服务。
2. 在管理台「系统安全」开启「允许局域网请求」和/或「允许公网请求」。

**网络 ACL 覆盖整站**（管理台、`/api/admin/*`、SPA、`/api/v1/*`、文档页、健康检查），不仅限对外 API。本机回环地址始终放行。

`TRUST_PROXY_HEADERS` **默认关闭**。仅在确认前置代理可信时开启，并正确配置 `TRUSTED_PROXY_CIDRS`；否则伪造 `X-Forwarded-For` 可能绕过来源策略。

Nginx 示例：

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

同仓库部署资产见 [`deploy/`](../../deploy/)（Docker、`systemd`、打包脚本、运维脚本），说明见 [`deploy/README.md`](../../deploy/README.md)。

常用命令：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
uv run python deploy/packaging/build.py
uv run python deploy/scripts/show_device_spec.py
```

## 管理台会话（Cookie + CSRF）

管理台登录后：

- 服务端设置 HttpOnly Cookie：`mijia_admin_session`（SameSite=Lax；HTTPS 时 Secure）。
- 同时下发可读 CSRF Cookie：`mijia_csrf`。Cookie 会话下的 `POST/PUT/PATCH/DELETE` 须带匹配头 `X-CSRF-Token`。
- 仍兼容 `Authorization: Bearer <admin_token>`（Bearer 路径免 CSRF，适合脚本）。
- 登出：`POST /api/admin/auth/logout`（吊销会话并清 Cookie）。
- 补发 CSRF：`GET /api/admin/auth/csrf`（需已登录）。
- 修改密码：管理台 UI，或 CLI `reset-admin`。

管理台与 API 须**同源**部署（或反代保持同一站点 Cookie）。跨域前端请改用 Bearer，不要依赖 Cookie。

## 前端

开发：

```bash
cd web
npm ci
npm run dev
```

生产构建：

```bash
cd web
npm ci
npm run build
```

产物在 `web/dist`。存在时由 FastAPI 托管；`/assets/*` 长缓存，`index.html` 为 `no-cache`。

## 代码结构（服务端）

```
server/
├── app.py                 # 应用工厂、中间件、SPA
├── cli.py                 # 运维入口
├── config.py              # 环境变量 + server.toml + v2→v3 迁移
├── deps.py                # 共享依赖
├── routers/
│   ├── admin_auth.py      # 登录 / CSRF / 改密 / bootstrap
│   ├── admin_mijia.py     # 扫码登录、同步
│   ├── admin_resources.py # 设备/场景/API Key/配置/审计…
│   └── api_v1.py          # 对外 REST
├── store.py               # ServerStore 组合入口
├── store_auth.py          # 管理员会话
├── store_api_keys.py      # API Key
└── store_registry.py      # 家庭/设备/场景注册表
```

## 当前能力摘要

- 管理员初始化、登录、改密、logout、会话刷新
- 米家扫码登录（同源二维码图片）、凭据加密落盘与定时刷新
- 家庭/设备/场景同步（非阻塞 + `task_id` 进度）
- API Key 作用域与资源策略；校验有短 TTL 缓存
- 对外 REST：状态、家庭、设备、属性/动作、场景、缓存、审计
- 设备列表默认不带重型 `raw`/`spec`；需要时传 `include_raw=1` / `include_spec=1`
- 审计保留清理、磁盘缓存清理、系统自检
- OpenAPI/Swagger 可开关；开启后仍受网络 ACL 与文档鉴权策略约束

## 常用接口

管理台（Cookie 或 Bearer）：

- `POST /api/admin/bootstrap/admin`（仅回环；Docker 可放宽）
- `POST /api/admin/auth/login`
- `POST /api/admin/auth/logout`
- `POST /api/admin/auth/refresh`
- `GET  /api/admin/auth/csrf`
- `POST /api/admin/auth/change-password`
- `POST /api/admin/mijia/login/start`
- `POST /api/admin/sync` → 返回 `task_id`；轮询 `GET /api/admin/sync/progress`
- `GET  /api/admin/devices`
- `POST /api/admin/api-keys`

对外 API（`Authorization: Bearer <api_key>`）：

- `GET  /api/v1/status`
- `GET  /api/v1/homes`
- `GET  /api/v1/devices`（可选 `include_spec` / `include_raw`）
- `GET  /api/v1/devices/{slug}/state`
- `POST /api/v1/devices/{slug}/properties`
- `POST /api/v1/devices/{slug}/actions`
- `GET  /api/v1/scenes`
- `POST /api/v1/scenes/{id}/execute`

管理台「API 使用」页有完整示例；交互式文档可在「系统安全」开启。
