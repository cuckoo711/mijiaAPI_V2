# 更新日志

本项目遵循“面向部署和使用者可读”的更新记录。最新变化放在最前面。

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
