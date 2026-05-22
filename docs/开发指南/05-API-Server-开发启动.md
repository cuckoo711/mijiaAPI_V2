# API Server 开发启动

本项目在 SDK 外新增 `server/` 和 `web/` 两个上层应用目录。

## 后端

初始化本地 SQLite 数据库：

```bash
uv run python -m server.cli init
```

启动 API Server：

```bash
uv run python -m server.cli run
```

执行自检：

```bash
uv run python -m server.cli check
```

默认监听 `127.0.0.1:8123`，可通过环境变量调整：

- `MIJIA_SERVER_HOST`
- `MIJIA_SERVER_PORT`
- `MIJIA_SERVER_DATA_DIR`
- `MIJIA_SERVER_DATABASE_PATH`
- `MIJIA_CREDENTIAL_PATH`
- `MIJIA_PUBLIC_BASE_URL`

## 访问来源与反向代理

服务默认只监听本机，并且本机请求始终允许。要让局域网或公网客户端访问，需要同时满足两件事：

1. 启动时监听可被外部访问的地址，例如 `MIJIA_SERVER_HOST=0.0.0.0`，或由 Nginx/Caddy/NAS 反向代理转发到本服务。
2. 在管理台的“系统安全”中开启对应的“允许局域网请求”或“允许公网请求”开关，控制对外 API 和健康检查的来源范围。

管理台和 `/api/admin/*` 由管理员登录鉴权保护，不受上述来源开关拦截，避免清库环境无法完成初始化。

反向代理模式默认开启。后端只会信任“可信代理地址”传来的 `X-Forwarded-For` / `X-Real-IP`，再用真实客户端 IP 判断局域网/公网权限。默认可信代理仅包含：

```text
127.0.0.1/32
::1/128
```

Nginx 示例：

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

## 前端

开发期进入 `web/`：

```bash
npm install
npm run dev
```

构建前端：

```bash
npm run build
```

构建产物默认输出到 `web/dist`。当该目录存在时，FastAPI 会托管前端静态文件。

## 当前实现范围

当前 MVP 已包含：

- FastAPI 应用工厂。
- SQLite schema 初始化。
- 管理员初始化和登录。
- API Key 创建、列表、启停、删除和作用域鉴权。
- `/healthz` 和 `/api/v1/status`。
- 管理台构建后由 FastAPI 单服务托管。
- 米家二维码登录任务。
- 凭据状态、刷新和删除。
- 家庭、设备、场景同步到 SQLite 注册表。
- 设备 slug、别名、隐藏和只读/可控权限维护。
- 场景隐藏和可执行权限维护。
- 对外 REST API：账号、家庭、设备、设备状态、设备规格、设备控制、批量控制、场景执行、缓存和日志。
- 运行时配置读写。
- 局域网/公网访问来源开关，以及可信反向代理来源识别。
- 审计日志写入和查询。

## 常用接口

管理后台接口使用管理员会话 token：

- `POST /api/admin/bootstrap/admin`
- `POST /api/admin/auth/login`
- `GET /api/admin/system/check`
- `POST /api/admin/mijia/login/start`
- `POST /api/admin/sync`
- `GET /api/admin/devices`
- `PATCH /api/admin/devices/{device_id}`
- `GET /api/admin/api-keys`
- `POST /api/admin/api-keys`

对外 API 使用 `Authorization: Bearer <api_key>`：

- `GET /api/v1/status`
- `GET /api/v1/account`
- `GET /api/v1/homes`
- `GET /api/v1/devices`
- `GET /api/v1/devices/{device_slug}/state`
- `POST /api/v1/devices/{device_slug}/properties`
- `POST /api/v1/devices/{device_slug}/actions`
- `POST /api/v1/batch/devices/properties`
- `GET /api/v1/scenes`
- `POST /api/v1/scenes/{scene_id}/execute`
