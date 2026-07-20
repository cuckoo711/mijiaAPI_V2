# 更新日志

本项目遵循“面向部署和使用者可读”的更新记录。最新变化放在最前面。

## v3.3.0 - 2026-07-20

### 新增

- 管理台支持修改管理员密码：登录后可通过右上角「修改密码」更新密码。
- 新增接口 `POST /api/admin/auth/change-password`：校验当前密码后更新，保留当前会话并吊销其他管理员会话。
- 补齐 CLI `mijia-server reset-admin`：本机忘记密码时可重置管理员密码（支持 `--username` / `--password`）。

## v3.2.2 - 2026-07-05

### 改进

- GitHub Release 页面现在会自动展示 CHANGELOG 中对应版本的详细更新内容。
  之前只有 `generate_release_notes: true` 生成的 issue/PR 列表，用户看不到本次
  版本的实际改动。现在会把 CHANGELOG 里对应段落作为 release body 主要内容，
  自动生成的 commit / PR 列表附在后面。
- 新增 `scripts/extract_release_notes.py`：从 `CHANGELOG.md` 提取指定版本段落，
  供 CI release 步骤使用；命令行也可以直接调用（例如本地校验）。

### 内部改动

- `.github/workflows/build.yml` 的 release 任务补充 checkout + Python 环境，
  新增 "Extract release notes from CHANGELOG" 步骤生成 body 文件。

## v3.2.1 - 2026-07-05

### 修复

- 删除米家凭据时同步清理已同步的家庭 / 设备 / 场景数据，以及 SDK 内部缓存。之前只删凭据文件不清理下游数据，导致管理台仍能看到过期的家庭 / 设备 / 场景（且这些数据在无凭据时无法调 API 使用），造成误导。
- `DELETE /api/admin/mijia/credential` 的审计日志 metadata 现在带上清理摘要（`homes` / `devices` / `scenes` 各删除的行数），便于事后排查。

### 保持不变

- 管理员账号 / API Key / runtime_config / 审计日志本地状态在删凭据时保持不变（这些属于服务本身的运维数据，不因米家账号变化而失效）。

## v3.2.0 - 2026-07-05

### 新增

- 管理台侧栏底部新增"关于"入口，展示应用名称、版本、许可证、贡献者、项目仓库/Issue/发行版链接，以及版权信息。
- 内置检查更新：登录后自动向 GitHub Releases 查询最新版本，发现新版本时侧栏"关于"按钮显示黄点提示，顶栏版本号旁出现"有新版本可用"胶囊按钮。关于弹窗内展示新版本号、发布时间、发行说明和"前往下载"跳转。
- 弹窗提供"立即检查"按钮支持强制刷新（绕过服务端 1 小时缓存）；结果时间戳一并展示，方便排查。
- 新增后端端点：
  - `GET /api/admin/app-info`：应用元信息（版本 / 仓库 / 许可 / 贡献者）。
  - `GET /api/admin/updates/check?force=1`：查询 GitHub Releases 最新版本；带进程内 1 小时缓存与错误静默降级。
- `pyproject.toml` 补齐 `[project.urls]`：Homepage / Repository / Issues / Releases。

### 内部改动

- 新增 `server/updater.py`：`UpdateChecker` 使用 httpx 拉取 `api.github.com/repos/{owner}/{repo}/releases/latest`，支持进程内 TTL 缓存、宽松版本号解析、切换仓库地址（未来做 fork 支持）。
- 新增单元测试覆盖版本比较、缓存命中、网络错误静默降级；集成测试覆盖两个新端点的鉴权与响应结构。

## v3.1.2 - 2026-07-05

### 修复（性能）

- **重大**：`MijiaRuntime._api()` 之前每个 HTTP 请求都会重建 `MijiaAPI` 实例（新连接池 + 空 L1 缓存 + 全部仓储 + 服务）。改为进程内缓存，只在凭据被替换到新 `user_id` 时重建；同一用户的凭据刷新走 `update_credential` 复用连接池。控制设备、查询状态等高频路径下 CPU 与网络开销显著下降。
- 控制设备 / 调用操作时新增可选参数 `home_id`：调用方（如本项目 server 层）已知家庭时直接精确失效缓存，跳过原有"遍历所有家庭 × 全量拉设备列表"的 `get_device_by_id` 反查。批量控制的 `requests` 每项同样支持 `home_id`。
- `ServerStore.get_config_map` 每个 HTTP 请求都被 middleware 调用一次，之前每次都打开 SQLite + JSON 解析。加进程内 5 秒 TTL 缓存；`set_config` 会主动失效。
- `ServerStore.validate_admin_session` 之前每次都走 PBKDF2 260k 轮（约 30ms）。加进程内 30 秒 TTL 的正例缓存；session 续期时同步失效对应条目。
- SQLite 每次 `connect()` 都执行的 `PRAGMA journal_mode = WAL` 是持久化设置，改为只在 `initialize()` 时执行一次。
- `ServerStore.list_devices` 默认不再反序列化 `spec_json`（单个 spec 可能几十 KB × 上百台设备，`/api/admin/devices`、`/api/v1/devices` 每次刷新都产生几 MB JSON 反序列化）。需要时调用方显式传 `include_spec=True`，或改用 `get_device` 单点查询。API 路由暴露 `?include_spec=1` 查询参数。
- `uvicorn` `access_log` 默认关闭：前端同步期间每 500ms 轮询会淹没控制台，Windows 下 stdio 是同步阻塞的。可通过 `--access-log` 或环境变量 `MIJIA_SERVER_ACCESS_LOG=1` 显式启用。

### 内部改动

- `MijiaRuntime` 新增 `_invalidate_api_client()`：凭据被删除时同步丢弃缓存的 API 实例。
- `AsyncMijiaAPI.control_device` / `call_device_action` / `batch_control_devices` 补齐 `home_id` 支持，行为对齐同步版本。
- `MijiaAPI._invalidate_device_cache` / `_invalidate_batch_device_cache` 抽出，同步与异步版本共享失效策略。

## v3.1.1 - 2026-07-05

### 修复

- **性能**：同步家庭设备时 CPU 占用异常偏高（可达 60%+）。根因是 `DeviceSpecRepositoryImpl` 在获取每台设备规格时都会重新拉取 miot-spec.org 的 `instances?status=released` 全量清单（约 1.8MB / 14k+ 条记录），并在 Python 里做线性扫描找匹配的 `type`。修复后：清单在进程内缓存 model→type 映射，同时写入文件层 24 小时缓存；100 台设备的同步从 200 次 HTTP + 100 次全量反序列化降为 1 次 HTTP + 100 次哈希查找。
- 修复 v3.1.0 在存量数据库上启动时报错 `sqlite3.OperationalError: no such column: token_prefix`：`idx_admin_sessions_token_prefix` 索引与 `_ensure_columns` 补列的执行顺序颠倒。索引改为在补列完成后再创建，存量库能够正常迁移。

## v3.1.0 - 2026-07-05

### 变更（Breaking）

- `POST /api/admin/sync` 改为非阻塞：立即返回 `{"status": "started", "message": "..."}`，后台线程执行实际同步；前端继续通过 `/api/admin/sync/progress` 轮询进度。旧调用方若依赖同步返回体中的 `homes` / `devices` / `scenes` / `warnings` 字段，需改为读取进度接口的最终状态。
- 审计事件 `mijia.sync` 拆分为 `mijia.sync.start`（同步任务发起时记录），完成结果保留在进度接口。

### 新增

- `AsyncMijiaAPI.get_scenes` 补齐 `owner_uid` 参数，支持共享家庭场景的异步获取。
- `DeviceService` 暴露公开方法 `get_device_spec` / `batch_get_properties`，避免调用方穿透到仓储私有成员。
- `ServerStore.purge_expired_sessions`：清理已过期的管理员 session；在初始化和每次登录后自动调用。
- `admin_sessions` 表新增 `token_prefix` 列和 `idx_admin_sessions_token_prefix` 索引，用于按前缀快速定位 session，避免逐条 PBKDF2 校验的全表扫描。

### 修复

- 管理员会话校验从"全表扫描 + 逐条 PBKDF2"改为"按 `token_prefix` 索引命中后再 PBKDF2"，session 数量增长时性能不再线性劣化。
- `ServerStore.update_api_key_status` 从"UPDATE 后 SELECT 全部再 Python 过滤"改为"UPDATE 后按 id SELECT"，避免全表查询。
- `ServerStore.system_checks` 内 `list_homes()` / `list_api_keys()` 从各调用两次改为各调用一次。
- `MijiaRuntime._sync_all_unlocked` 的延迟清理线程只清空 `task_id` 匹配的进度，避免在 5 秒窗口期内被新一轮同步覆盖后误清进度。
- `MijiaAPI.get_scenes` 的 `owner_uid` 类型注解修正为 `Optional[str]`。
- `FileCredentialStore.save` 在 Windows 下不再调用无实际效果的 `chmod`；Linux/macOS 行为不变。
- `CacheManager` 文件层缓存写入时记录 `expires_at`，读取时若已过期则删除文件并返回 `None`；兼容旧格式缓存文件。

### 内部改动

- FastAPI 生命周期从已弃用的 `@app.on_event("startup"/"shutdown")` 迁移到 `lifespan` 上下文管理器，启动日志不再出现 `DeprecationWarning`。
- 删除 `DeviceSpecRepositoryImpl` 中未使用的旧格式解析代码 `_parse_spec` / `_parse_property_v2` / `_parse_action_v2`（约 150 行），清理未使用的 `import json` / `import re`。
- `api_client.py` 不再直接访问 `DeviceService` 的私有成员 `_spec_repo` / `_device_repo`。

## 2026-05-23

### 变更

- 场景管理页的场景 ID 复制按钮改为复制完整场景执行 `curl` 命令；当前页面存在一次性 API Key 时会自动带入，否则保留 `YOUR_API_KEY` 占位。

## 2026-05-22

### 新增

- 新增 FastAPI + Vue3 + Element Plus 管理后台，并在 README 中补齐从拉取代码到启动服务的部署路径。
- 管理后台支持管理员初始化、管理员登录、系统自检、米家二维码登录、凭据状态查看、凭据刷新和凭据删除。
- 支持同步米家家庭、设备、场景到本地 SQLite。
- 支持家庭与设备页面的家庭筛选、状态筛选、访问筛选、隐藏筛选、分页和家庭名称展示。
- 支持设备只读/可控、隐藏状态自动保存。
- 支持场景允许执行、隐藏状态自动保存。
- 支持在场景管理页面查看并复制场景 ID，用于调用场景执行 API。
- 支持 API Key 创建、启停、删除、调用次数统计和中文权限说明。
- 新增独立“API 使用”菜单页，展示 Header 用法、curl/fetch 示例、每个接口的请求数据、返回说明、常用接口和访问策略。
- 新增系统安全页面，支持局域网请求、公网请求、反向代理模式和可信代理地址配置。
- 新增审计日志查询。
- 新增管理员会话续期接口 `/api/admin/auth/refresh`，管理台会在会话到期前自动续期。
- 新增 systemd、Nginx 反向代理、环境变量、日常维护、备份和常见问题说明。

### 变更

- 管理台菜单改为分级导航，保留“总览”为顶级入口。
- 家庭与设备默认分页改为每页 20 条。
- API Key 列表不再展示具体权限字段，权限细节集中放到创建表格和 API 使用说明中。
- 系统自检返回和页面展示增加中文检查项、中文说明和中文状态。
- 前端启动状态改为通过 `/api/admin/bootstrap/state` 获取，避免公网来源策略下浏览器请求 `/healthz` 产生 403 噪音。
- Swagger/ReDoc/OpenAPI JSON 从环境变量开关改为 SQLite 运行时配置，可在管理台“系统安全”中即时切换，无需重启服务。

### 修复

- 修复系统自检“公网访问地址”只读取启动环境变量的问题；现在会优先读取 SQLite 运行时配置中的 `PUBLIC_BASE_URL`。
- 修复反向代理公网访问时初始化页面可能被来源策略阻断的问题。
- 修复扫码登录成功后二维码仍停留的问题。
- 修复米家同步中单个家庭场景同步失败会中断整体同步的问题，同步结果会返回警告列表。
- 修复同步按钮可被多次触发的问题；前端会禁用按钮，后端会用 `409 SYNC_IN_PROGRESS` 拒绝并发同步。
- 修复家庭与设备、场景管理中只展示家庭编号不直观的问题，改为展示家庭名称。
- 修复管理员会话过期后前端仍停留在后台页面的问题，现在会清理本地登录态并回到登录页。
- 修复开启文档后 OpenAPI JSON 被公网来源策略误拦截，导致 Swagger 无法加载接口列表的问题。

## v2.0.0 - 2026-03-13

### 新增

- 完全重构 SDK，采用领域层、仓储层、服务层、基础设施层、API 客户端层的分层架构。
- 凭据与操作完全分离，Credential 可以独立保存和加载。
- 支持同步和异步 API。
- 添加完整类型注解。
- 添加结构化日志和敏感信息脱敏。
- 添加缓存管理、凭据存储、设备规格查询、家庭/设备/场景仓储。
- 添加测试、类型检查和代码质量工具配置。

### 变更

- 将原始米家调用封装为更清晰的工厂函数和服务对象。
- 将设备、家庭、场景、规格等模型整理为领域对象。
