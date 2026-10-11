# API Server 开发启动

本项目在 SDK 外提供 `server/`（FastAPI）与 `web/`（Vue3 管理台）。以下接口以当前源码为准（默认数据目录 `configs/`，部署资产在 `deploy/`）。

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
│   ├── admin_controls.py  # 管理员手动控制、操作回执、审计补写
│   ├── admin_resources.py # 设备/场景/API Key/配置/审计…
│   └── api_v1.py          # 对外 REST
├── store.py               # ServerStore 组合入口
├── store_auth.py          # 管理员会话
├── store_api_keys.py      # API Key
├── control_operations.py  # 执行结果、回执 ID 与审计状态
├── audit_journal.py       # 审计文件队列与补写
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
- 管理员按规格手动控制、按操作 ID 查询回执、审计队列补写与依赖就绪检查
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
- `GET  /api/v1/operations/{operation_id}`（有效 API Key 仅能查询自己发起的控制操作，无需 `read:logs`）

管理台「API 使用」页有完整示例；交互式文档可在「系统安全」开启。

## 管理员手动控制与操作回执

以下管理接口使用已登录管理员 Cookie；写入和补写须带 `X-CSRF-Token`。`device_id`、`scene_id` 使用管理列表返回的本地 `id`，不使用设备 Slug 或米家远端 ID。

| 方法 | 路径 | 请求与响应 |
|------|------|------------|
| `GET` | `/api/admin/devices/{device_id}/state` | 返回 `{"items": [...]}`；直接读取当前属性，逐项含 `did/siid/piid/code`，只有 `code=0` 且含 `value` 才是已确认读值 |
| `GET` | `/api/admin/devices/{device_id}/spec` | 返回 `{"spec": ...}`；规格含 `properties`、`actions` 及动作 `parameters` |
| `POST` | `/api/admin/devices/{device_id}/properties` | JSON `{"siid":2,"piid":1,"value":true}`；返回 `{"success":true/false}` |
| `POST` | `/api/admin/devices/{device_id}/actions` | JSON `{"siid":2,"aiid":1,"params":{"2":4,"3":false}}`；返回 `{"result": ...}`，明确整数 `code=0` 表示接受执行 |
| `POST` | `/api/admin/scenes/{scene_id}/execute` | 无必填请求体，管理台发送 `{}`；返回 `{"success":true/false}` |
| `GET` | `/api/admin/operations/{operation_id}` | 查询管理审计中已保存或待补写的操作回执 |
| `GET` | `/api/admin/audit/health` | 返回整数计数 `{"pending":0,"invalid":0,"unavailable":0}` |
| `POST` | `/api/admin/audit/replay` | 返回 `{"delivered":0,"pending":0,"invalid":0,"unavailable":0}`；只补写审计，不执行设备操作 |

表中的属性、动作及参数 ID 仅示例，须按选定设备规格填写。属性须可写，设备本地授权须为 `access_mode=write`；场景须为 `executable=true`。管理员手动写入与执行拒绝隐藏资源，后端在派发前复核当前记录、账号与权限。状态/规格读取仍允许查看隐藏或只读设备。参数不符时返回 422 标准错误对象，字段问题位于 `error.details.issues`；表单保留输入。读取属性失败的项目保留错误码，不补假值；属性读值也不用于推断设备在线状态。

打开设备对话框只读取规格和状态，选择字段或填写参数不会发送控制；只有点击「确认写入属性」「确认执行动作」「确认执行场景」才发出写入。关闭或切换页面保留当前会话中的草稿与未决结果，并按本地记录 ID 隔离迟到响应。

进入控制执行/审计阶段的响应会携带：

| 响应头 | 含义 |
|--------|------|
| `X-Operation-ID` | 本次控制操作的审计事件 UUID；用于查回执，不是去重重试键 |
| `X-Audit-Delivery: stored` | 事件已写入 SQLite |
| `X-Audit-Delivery: queued` | SQLite 写入失败，事件已保存在审计补写文件队列 |
| `X-Audit-Delivery: unavailable` | 事件既未写入 SQLite，也未能保存到队列；不能靠补写恢复 |

设备执行结果与审计保存状态互相独立；不得因为 `queued/unavailable` 而重发控制。参数验证或鉴权在进入控制阶段前失败时，响应可能没有操作 ID。回执返回 `id/occurred_at/action/result/request_id/metadata/delivery`，管理员还会看到 `actor_type`；`result` 区分 `success`、`failed`、`warning`（部分成功/警告）和 `unknown`。回执记录上游结果与审计落点，不代表物理动作已经完成。

对外 `GET /api/v1/operations/{operation_id}` 只允许仍有效的、发起该操作的同一个 API Key 查询；其他 Key 查询返回 404。轮换后的新 Key 不继承旧 Key 的回执所有权，可由管理员查验。只读查询示例：

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://127.0.0.1:8123/api/v1/operations/OPERATION_ID
```

`409 EXECUTION_UNKNOWN` 返回 `error.details.outcome="unknown"` 和 `retry_safe=false`，可能还包含已收到的批量结果数量 `completed_count`。这表示请求可能已经执行、回执缺失或后续批次未确认，不能自动重试。先查询最新设备状态或核对场景实际效果；管理台保留输入并要求明确核查后才允许新的手动操作。若浏览器丢失写入响应，也按结果未知处理；查询操作回执返回 404 本身不证明命令未执行。

## 审计恢复、就绪与验收

审计队列位于 `<data_dir>/audit-pending/`，正常待补写文件为 `.json`，无效记录隔离为 `.invalid`。初始化时尝试补写，服务运行中约每 10 秒再次尝试；每轮默认最多成功补写 100 条。事件 ID 保持不变，重复补写不会产生同 ID 的重复审计行。

`pending` 是待补写文件数量；`invalid` 是异常/隔离记录数量（队列无法检查时也会报告异常）；`unavailable` 是**本进程未能保存的事件历史计数**，不是当前目录可访问性的布尔值。补写可继续处理已有 `pending`，但无法恢复完全未保存的事件，也不会清零 `unavailable`。应核对日志、磁盘空间、权限、SQLite 与队列文件，保留排查证据；故障排查完成后重启进程才会重置这一历史计数，重启本身不会找回缺失记录。

`GET /healthz` 正常返回 `status=ok` 与版本，用于 HTTP 存活检测；`GET /readyz` 检查 SQLite 可写（回滚探测）、前端 `index.html` 存在、审计三个计数均为零，全部通过返回 200，否则 `status=degraded` 和 503。若读取存储配置即失败，会返回标准 503 `STORAGE_UNAVAILABLE` 错误对象。两者仍受全站网络 ACL 约束，不探测真实米家授权或设备动作。`unavailable>0` 会让就绪持续降级，直至完成排查并重启；详细步骤见 [部署运维说明](../../deploy/README.md#依赖就绪与审计恢复)。

单元测试、模拟浏览器与隔离 Docker 验证不使用真实米家设备，只证明所覆盖的软件路径。上线前仍需在目标部署核对真实授权、规格、只读/可控边界、共享家庭 owner、实时属性错误码与实际设备/场景效果；控制 ACK、回执和就绪均不代替物理验收。
