# mijiaAPI_V2 优化执行规格（修订版）

> 本文档供 AI Agent 直接执行，每个任务包含：问题定位、根因、改法、验收标准。
> 按优先级从高到低排列，P1 必须改，P2 建议改，P3 可选改。
>
> **本次修订说明**（相对上一版）：
> - TASK-01：删除无意义的 `token_hash` 唯一索引建议（该列已是 PRIMARY KEY），改为对新列 `token_prefix` 建普通索引；补充旧数据迁移策略。
> - TASK-03：修正对 FastAPI 阻塞行为的描述——sync 是同步 `def`，被 FastAPI 放到 threadpool 执行，不会阻塞 event loop；改动目标是"避免用户等待长响应"和"释放 threadpool 线程"。
> - TASK-10：已删除。原改法与当前实现等价，且问题描述（"中文字符被丢弃"）与 Python `str.isalnum()` 的实际行为不符，不属实。

---

## P1 — 影响正确性 / 性能的关键问题

---

### TASK-01：`validate_admin_session` / `refresh_admin_session` 全表扫描 + 无过期清理

**文件**：`server/store.py`、`server/db.py`

**问题**
两个方法都执行 `SELECT * FROM admin_sessions WHERE revoked_at IS NULL`，把所有有效 session 全部拉到内存，再逐条调用 `verify_secret`（PBKDF2 260000 轮）做时间恒定比较。session 越积越多时性能线性劣化，且数据库中过期的 session 永远不清理。

不能直接按 `token_hash` 索引查：`hash_secret` 使用随机 salt，同一 token 每次哈希结果不同。因此需要一个稳定的派生 lookup 列（`token_prefix`）。

**当前代码（两处相同模式）**
```python
rows = conn.execute("""
    SELECT s.token_hash, s.expires_at, s.revoked_at, u.id, u.username
    FROM admin_sessions s
    JOIN admin_users u ON u.id = s.admin_id
    WHERE s.revoked_at IS NULL
    """).fetchall()

for row in rows:
    if not verify_secret(token, row["token_hash"]):
        continue
    ...
```

**改法**

1. 在 `admin_sessions` 表上新增 `token_prefix TEXT` 列，并对其建普通索引。
   在 `db.py` 的 `SCHEMA_STATEMENTS` 中追加：
   ```sql
   CREATE INDEX IF NOT EXISTS idx_admin_sessions_token_prefix
   ON admin_sessions(token_prefix)
   ```
   注意：`token_hash` 是 PRIMARY KEY，已有隐式唯一索引，无需再加。

2. `db.py` 的 `_ensure_columns` 中为存量数据库追加 `token_prefix` 列：
   ```python
   "admin_sessions": {
       "token_prefix": "TEXT",
   },
   ```

3. `store.py` 的 `authenticate_admin` 写入 session 时同时写 `token_prefix`：
   ```python
   INSERT INTO admin_sessions(token_hash, token_prefix, admin_id, expires_at, created_at)
   VALUES (?, ?, ?, ?, ?)
   ```
   参数 `(hash_secret(token), secret_prefix(token), row["id"], isoformat(expires_at), isoformat(now))`。

4. `validate_admin_session` / `refresh_admin_session` 改为按 prefix 过滤：
   ```python
   prefix = secret_prefix(token)
   rows = conn.execute("""
       SELECT s.token_hash, s.expires_at, s.revoked_at, u.id, u.username
       FROM admin_sessions s
       JOIN admin_users u ON u.id = s.admin_id
       WHERE s.token_prefix = ? AND s.revoked_at IS NULL
       """, (prefix,)).fetchall()
   ```
   循环内 `verify_secret` 保持不变（同一 prefix 理论上只有 1 条，最坏也只做极少次哈希）。

5. **存量迁移**：旧 session 的 `token_prefix` 为 NULL，无法通过新路径匹配，会被视为过期。这是可接受的（用户重新登录即可），不需要写迁移脚本。

6. 新增 `ServerStore.purge_expired_sessions()`：
   ```python
   def purge_expired_sessions(self) -> int:
       with self._database.connect() as conn:
           cursor = conn.execute(
               "DELETE FROM admin_sessions WHERE expires_at < ?",
               (isoformat(utc_now()),),
           )
           return int(cursor.rowcount)
   ```
   在 `ServerStore.initialize()` 末尾调用一次；在 `authenticate_admin` 成功创建新 session 前也可顺带调用（低成本）。

**验收**
- 登录后调用 `validate_admin_session`，查询语句仅在 `token_prefix = ?` 命中的极少数记录上做 `verify_secret`。
- 数据库中不再存在 `expires_at < now` 的记录（每次初始化、每次登录后清理）。
- 现有测试 `tests/unit/server/test_store.py` 中 `refresh_admin_session` 相关用例仍能通过。

---

### TASK-02：`update_api_key_status` 全表查询 + `system_checks` 重复查询

**文件**：`server/store.py`

**问题 A**：`update_api_key_status` 执行 UPDATE 后调用 `self.list_api_keys()`（全表 SELECT），再在 Python 里 filter，应直接按 id 查：
```python
# 现状
keys = [item for item in self.list_api_keys() if item["id"] == key_id]
```

**问题 B**：`system_checks` 中 `list_homes()` 和 `list_api_keys()` 各被调用两次：
```python
"status": "pass" if self.list_homes() else "warn",
"message": "Homes have been synced" if self.list_homes() else "No synced homes",
```

**改法 A**
```python
def update_api_key_status(self, key_id: str, is_active: bool) -> dict[str, Any]:
    with self._database.connect() as conn:
        conn.execute(
            "UPDATE api_keys SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, key_id),
        )
        row = conn.execute(
            """SELECT id, name, key_prefix, scopes_json, resource_policy_json,
                      is_active, expires_at, created_at, last_used_at,
                      last_used_ip, use_count
               FROM api_keys WHERE id = ?""",
            (key_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"API key not found: {key_id}")
    return {
        "id": row["id"],
        "name": row["name"],
        "key_prefix": row["key_prefix"],
        "scopes": json.loads(row["scopes_json"]),
        "resource_policy": json.loads(row["resource_policy_json"]),
        "is_active": bool(row["is_active"]),
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "last_used_ip": row["last_used_ip"],
        "use_count": row["use_count"],
    }
```

**改法 B**：在 `system_checks` 方法开头先把结果存变量：
```python
homes = self.list_homes()
api_keys = self.list_api_keys()
# 后面所有判断都用这两个变量，不再重复调用方法
```

**验收**
- `update_api_key_status` 只产生一条 UPDATE + 一条 SELECT by id。
- `system_checks` 方法内 `list_homes()` 和 `list_api_keys()` 各只出现一次调用。

---

### TASK-03：`sync_all` 让用户等待长响应（前端体验优化）

**文件**：`server/mijia_runtime.py`、`server/app.py`

**问题**
`POST /api/admin/sync` 是同步实现（`def admin_sync`），FastAPI 会把它放到 threadpool 里执行。因此**它不会阻塞 uvicorn 的 event loop，也不会独占单一 worker**，但会：
- 让前端等几十秒才拿到 HTTP 响应（尽管前端已经在同时轮询 `/api/admin/sync/progress`，多余的等待造成体验问题）；
- 长时间占用一个 threadpool 线程（默认上限 40，一般够用，但没必要占）。

前端已经有完整的轮询进度逻辑（`web/src/App.vue` 的 `startSyncPolling` / `pollSyncProgress`），改成异步启动是自然选择。

**改法**

`MijiaRuntime.sync_all` 改为非阻塞，在后台线程执行，立即返回：

```python
def sync_all(self) -> dict[str, Any]:
    """启动后台同步，立即返回。若同步已在进行中则抛出 SyncInProgressError。"""
    if not self._sync_lock.acquire(blocking=False):
        raise SyncInProgressError("同步正在进行中，请稍后再试")
    thread = threading.Thread(
        target=self._sync_background,
        daemon=True,
    )
    thread.start()
    return {"status": "started", "message": "同步已在后台启动，请轮询 /api/admin/sync/progress"}

def _sync_background(self) -> None:
    try:
        self._sync_all_unlocked()
    except Exception:
        # 已经在 _sync_all_unlocked 内被记录到 progress，此处静默即可
        pass
    finally:
        self._sync_lock.release()
```

`_sync_all_unlocked` 保持不变（`try/finally` 内的 `cleanup_progress` 逻辑保留）。

`server/app.py` 中 `admin_sync` 路由：由于 sync 已异步启动，改为只审计"sync started"：

```python
@app.post("/api/admin/sync")
def admin_sync(
    _admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    result = runtime.sync_all()
    current_store.add_audit("mijia.sync.start", "success", actor_type="admin")
    return result
```

**注意**：现有测试 `tests/unit/server/test_mijia_runtime.py::test_sync_all_rejects_second_request_while_running` 依赖 sync 是阻塞的。改成后台线程后，第二次调用仍会因 `_sync_lock` 已被后台线程占用而抛 `SyncInProgressError`，测试逻辑基本兼容——但如果测试断言 sync 返回的结果字段（如 `homes` / `devices`），需要相应调整。另一个测试 `test_sync_all` 直接断言 `result["homes"] == 2` 等——**这个需要改为等待后台完成后再断言**（例如 join 后台线程，或轮询 `get_sync_progress` 直到 status=completed）。执行时同步修改测试。

**验收**
- `POST /api/admin/sync` 在 500ms 内返回 `{"status": "started", ...}`。
- 后续轮询 `/api/admin/sync/progress` 能看到进度从 0 推进到 100。
- 同步期间其他 API 请求正常响应。
- `tests/unit/server/test_mijia_runtime.py::test_sync_all` 调整后仍能通过（等待后台完成再断言结果）。
- `test_sync_all_rejects_second_request_while_running` 仍能通过（锁仍生效）。

---

### TASK-04：`app.on_event` 弃用警告，迁移到 `lifespan`

**文件**：`server/app.py`

**问题**
FastAPI 0.93+ 已将 `@app.on_event("startup")` / `@app.on_event("shutdown")` 标记为弃用，未来版本将移除。当前代码会在启动时打印 DeprecationWarning。

**改法**
用 `contextlib.asynccontextmanager` 定义 `lifespan`，替换两个 `on_event` 装饰器：

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # startup
    runtime: MijiaRuntime = app.state.runtime
    runtime.start_credential_refresh_timer()

    from server.config_watcher import ConfigWatcher
    config_file = resolved_settings.config_file_path
    if config_file.exists():
        watcher = ConfigWatcher(
            config_file,
            callback=lambda path: _on_config_changed(path, app),
            interval=10,
        )
        watcher.start()
        app.state.config_watcher = watcher

    yield

    # shutdown
    runtime.stop_credential_refresh_timer()
    if hasattr(app.state, "config_watcher"):
        app.state.config_watcher.stop()
```

然后在 `FastAPI(...)` 构造时传入：
```python
app = FastAPI(
    title="Mijia API Server",
    version=mijiaAPI_V2.__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=OPENAPI_JSON_ROUTE,
    lifespan=lifespan,
)
```

删除原来的两个 `@app.on_event` 函数。

**验收**
- 启动日志中不再出现 `DeprecationWarning: on_event is deprecated`。
- 服务正常启动、正常关闭，credential refresh timer 和 config watcher 生命周期行为与原来一致。

---

## P2 — 代码质量 / 封装问题

---

### TASK-05：消除 `api_client.py` 中对私有成员的直接访问

**文件**：`mijiaAPI_V2/api_client.py`、`mijiaAPI_V2/services/device_service.py`

**问题**
```python
# api_client.py 第 301 行
return self._device_service._spec_repo.get_spec(model)

# api_client.py 第 322 行
return self._device_service._device_repo.batch_get_properties(requests, self._credential)
```
直接穿透服务层访问仓储层私有成员，破坏封装。

**改法**
在 `DeviceService` 中新增两个公开方法。注意 `DeviceService.get_device_properties` 已存在（返回单设备全部属性），新方法必须换名以避免冲突：

```python
# device_service.py
def get_device_spec(self, model: str) -> Optional["DeviceSpec"]:
    """获取设备规格，获取失败返回 None。"""
    try:
        return self._spec_repo.get_spec(model)
    except Exception:
        return None

def batch_get_properties(
    self, requests: List[Dict[str, Any]], credential: Credential
) -> List[Dict[str, Any]]:
    """按 (did, siid, piid) 批量读取属性值。"""
    return self._device_repo.batch_get_properties(requests, credential)
```

`api_client.py` 中对应改为：
```python
def get_device_spec(self, model: str) -> Optional[Any]:
    return self._device_service.get_device_spec(model)

def get_device_properties(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return self._device_service.batch_get_properties(requests, self._credential)
```

**验收**
- `api_client.py` 中不再出现 `._spec_repo` 或 `._device_repo` 的直接引用。
- 功能行为不变。

---

### TASK-06：修复 `get_scenes` 的类型注解 + 补齐 Async 参数

**文件**：`mijiaAPI_V2/api_client.py`

**问题**
```python
def get_scenes(self, home_id: str, owner_uid: str = None) -> List[Scene]:
```
`owner_uid` 默认值为 `None` 但类型注解为 `str`，mypy strict 模式报错。

`AsyncMijiaAPI.get_scenes` 目前没有 `owner_uid` 参数，与同步版本不一致；`SceneService.get_scenes` 支持第三参数。

**改法**
```python
from typing import Optional

# MijiaAPI
def get_scenes(self, home_id: str, owner_uid: Optional[str] = None) -> List[Scene]:
    return self._scene_service.get_scenes(home_id, self._credential, owner_uid)

# AsyncMijiaAPI
async def get_scenes(self, home_id: str, owner_uid: Optional[str] = None) -> List[Scene]:
    import asyncio
    return await asyncio.to_thread(
        self._scene_service.get_scenes, home_id, self._credential, owner_uid
    )
```

**验收**
- `mypy mijiaAPI_V2/api_client.py` 不再报 `owner_uid` 相关的类型错误。
- 现有测试仍能通过。

---

### TASK-07：删除 `device_spec_repository.py` 中的死代码

**文件**：`mijiaAPI_V2/repositories/device_spec_repository.py`

**问题**
以下方法已无任何调用路径，是遗留的旧格式解析代码：
- `_parse_spec`（home.miot-spec.com 旧格式）
- `_parse_property_v2`
- `_parse_action_v2`

`grep` 验证：这三个方法只在文件内被 `_parse_spec` 自身引用，没有其他调用者。

**改法**
直接删除上述三个方法（共约 90 行）。

**验收**
- 删除后运行 `python -m pytest tests/` 无新增失败。
- 项目内搜索 `_parse_spec\|_parse_property_v2\|_parse_action_v2` 仅在旧规格文档中出现（不再出现在 `mijiaAPI_V2/`）。

---

### TASK-08：`FileCredentialStore.save` 在 Windows 下的 `chmod` 无效调用

**文件**：`mijiaAPI_V2/infrastructure/credential_store.py`

**问题**
```python
file_path.chmod(0o600)
```
Windows 上该调用不报错但无任何效果。

**改法**
```python
import sys
# 保存文件后
if sys.platform != "win32":
    file_path.chmod(0o600)
```

**验收**
- Windows 下运行保存凭据流程，不报错，无异常。
- Linux/macOS 下保存后 `stat` 文件权限仍为 `0o600`。

---

## P3 — 轻微问题

---

### TASK-09：`CacheManager` 文件缓存缺少过期检查

**文件**：`mijiaAPI_V2/infrastructure/cache_manager.py`

**问题**
`_save_to_file` 只写入数据，不写入过期时间；`_load_from_file` 只检查文件是否存在，不检查是否过期。设备规格以 TTL=1年 写入文件后永远不会因 TTL 失效，只能手动清理。

**改法**
保存时把 `{"expires_at": time.time() + ttl, "data": value}` 写入文件；读取时检查 `expires_at`，过期则删除文件并返回 `None`。同时保留对旧格式（顶层无 `data` 键）的兼容：

```python
import time

def _save_to_file(self, key: str, value: Any, ttl: int) -> None:
    file_path = self._cache_dir / self._hash_key(key)
    payload = {
        "expires_at": time.time() + ttl if ttl > 0 else None,
        "data": value,
    }
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"文件缓存保存失败: {e}", extra={"key": key})

def _load_from_file(self, key: str) -> Optional[Any]:
    file_path = self._cache_dir / self._hash_key(key)
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        logger.warning(f"文件缓存加载失败: {e}", extra={"key": key})
        return None
    # 兼容旧格式：如果不是包含 "data" 键的字典，则整个内容就是数据
    if not isinstance(payload, dict) or "data" not in payload:
        return payload
    expires_at = payload.get("expires_at")
    if expires_at is not None and time.time() > expires_at:
        file_path.unlink(missing_ok=True)
        return None
    return payload["data"]
```

`set` 方法中对 `_save_to_file` 的调用需同步传入 `ttl` 参数：
```python
# 原来
self._save_to_file(full_key, value)
# 改为
self._save_to_file(full_key, value, ttl)
```

**验收**
- 写入 TTL=10s 的缓存文件，10s 后再次读取返回 `None`，缓存文件被删除。
- 旧格式缓存文件仍能被正确读取。

---

## 执行注意事项

1. **执行顺序**：TASK-01 → TASK-02 → TASK-04 → TASK-03 → TASK-05 → TASK-06 → TASK-07 → TASK-08 → TASK-09。TASK-03 依赖 TASK-04 之后执行（lifespan 重构完成后再改 sync，避免两次改动 app.py 冲突）。

2. **数据库迁移**：TASK-01 新增列和索引通过 `db.py` 的 `_ensure_columns` 和 `SCHEMA_STATEMENTS` 追加，不做破坏性 migration。存量 session 的 `token_prefix` 为 NULL，会随过期清理自然淘汰。

3. **不要动的部分**：
   - `server/security.py` 的 PBKDF2 参数（260000 轮是合理的密码学配置）
   - `web/` 目录（前端不在本次优化范围内）
   - `CHANGELOG.md` 和 `plan.md`（文档由人工维护）
   - `_slugify`（原 TASK-10）：`str.isalnum()` 对中文字符返回 True，当前代码对中文名不会 fallback 成 `device-xxxxx`。原问题描述与实际行为不符，本次不改。

4. **每个 TASK 完成后**运行 `python -m pytest tests/` 确认无回归，再继续下一个。
