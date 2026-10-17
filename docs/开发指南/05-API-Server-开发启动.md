# API Server 开发启动

后端位于 `server/`（FastAPI），管理台位于 `web/`（Vue3），默认数据目录为 `configs/`。

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
| `MIJIA_SERVER_LOG_LEVEL` | `INFO` | 服务日志级别 |
| `MIJIA_SERVER_ACCESS_LOG` | 关闭 | 设为 `1` 时开启 Uvicorn 访问日志（或 `--access-log`） |
| `MIJIA_PUBLIC_BASE_URL` | 空 | 对外 Base URL，用于外部调用示例/回调展示 |
| `MIJIA_AUDIT_RETENTION_DAYS` | `30` | 审计日志保留天数 |
| `MIJIA_ADMIN_SESSION_HOURS` | `12` | 管理台会话有效期（小时） |
| `MIJIA_CREDENTIAL_REFRESH_BEFORE_SECONDS` | `86400` | 凭据到期前多少秒触发自动刷新（1 天） |

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

Docker、systemd、打包与运维见[部署说明](../../deploy/README.md)。

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
- `GET  /api/v1/account`
- `GET  /api/v1/homes`
- `GET  /api/v1/devices`（可选 `include_spec` / `include_raw`）
- `GET  /api/v1/devices/{slug}`
- `GET  /api/v1/devices/{slug}/state`
- `GET  /api/v1/devices/{slug}/spec`
- `POST /api/v1/devices/{slug}/properties`
- `POST /api/v1/devices/{slug}/actions`
- `POST /api/v1/batch/devices/properties`
- `GET  /api/v1/scenes`
- `POST /api/v1/scenes/{id}/execute`
- `GET  /api/v1/operations/{operation_id}`（有效 API Key 仅能查询自己发起的控制操作，无需 `read:logs`）
- `POST /api/v1/cache/refresh`
- `POST /api/v1/cache/clear`
- `GET  /api/v1/logs`

设备列表默认不带 `raw`/`spec`，需要时传 `include_raw=1` / `include_spec=1`。API Key 权限校验使用短 TTL 缓存。

管理台「API 使用」页有完整示例；交互式文档可在「系统安全」开启，仍受网络 ACL 和文档鉴权策略约束。

### 批量属性

`POST /api/v1/batch/devices/properties` 的每项必须包含 `device`（兼容 `device_id`）、正整数 `siid` / `piid` 和 `value`。SDK 批量请求使用 `did`（兼容 `device_id`）。服务会在发送整批命令前检查全部属性规格、写权限、类型、范围和步长。

### 密钥轮换

`POST /api/admin/api-keys/{id}/rotate` 在同一事务中创建新密钥并停用旧密钥，继承原权限与资源范围。默认继承原有效期，可传 `expires_at` 修改有效期，传 `null` 取消有效期。新密钥仅在创建或轮换响应中显示一次。

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

属性写入收到成功回执后，管理台会继续核对可读属性：最多读取 5 次，间隔 1 秒，只有成功读值与本次提交的目标值一致才显示读回确认。核对过程中不会重发写入；读错、超时、不可读或关闭对话框时，保留“请求已被接受，但效果尚未确认”的提示，需人工核查后再发起新的操作。读回确认仍不代替物理设备观察。

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

## 审计恢复与就绪

`/healthz` 检查 HTTP 存活，`/readyz` 检查 SQLite、前端文件和审计状态；两者均受全站网络 ACL 约束。审计队列、健康计数、自动补写和存储故障恢复见[部署运维说明](../../deploy/README.md#依赖就绪与审计恢复)。
