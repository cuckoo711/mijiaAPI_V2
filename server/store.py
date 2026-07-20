"""Repository-style access to server-local data."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from server.config import ServerSettings
from server.db import ServerDatabase

DEFAULT_API_KEY_POLICY: dict[str, list[str]] = {
    "homes": [],
    "devices": [],
    "scenes": [],
}

SYSTEM_CHECK_METADATA: dict[str, dict[str, str]] = {
    "server": {
        "label": "服务进程",
        "description": "确认 FastAPI 服务进程正在运行并能响应管理台请求。",
    },
    "data_dir": {
        "label": "数据目录",
        "description": "确认数据目录存在，并且当前服务用户有写入权限。",
    },
    "sqlite": {
        "label": "SQLite 数据库",
        "description": "确认本地 SQLite 数据库可连接并能执行基础查询。",
    },
    "admin_configured": {
        "label": "管理员账号",
        "description": "确认管理台初始化管理员已经创建。",
    },
    "credential_file": {
        "label": "米家凭据文件",
        "description": "确认扫码登录后的米家凭据文件是否已经保存到本机。",
    },
    "public_base_url": {
        "label": "公网访问地址",
        "description": "确认 PUBLIC_BASE_URL 是否已配置，供外部调用示例和回调地址展示使用。",
    },
    "api_key_exists": {
        "label": "API Key",
        "description": "确认至少已经创建一个外部调用用的 API Key。",
    },
    "homes_synced": {
        "label": "家庭同步",
        "description": "确认米家家庭数据已经同步到本地数据库。",
    },
    "openapi_enabled": {
        "label": "OpenAPI 文档",
        "description": "显示 OpenAPI 文档接口当前是否对外启用。",
    },
    "docs_enabled": {
        "label": "交互式 API 文档",
        "description": "显示 Swagger UI 与 ReDoc 文档页面当前是否启用。",
    },
    "allow_public_access": {
        "label": "公网请求许可",
        "description": "确认是否已开启允许公网来源访问 API，避免无意暴露服务。",
    },
    "credential_file_permissions": {
        "label": "凭据文件权限",
        "description": "确认米家凭据文件权限未对同组/其他用户开放读取。",
    },
}


def utc_now() -> datetime:
    """Return the current UTC time with timezone information."""

    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    """Serialize datetimes consistently for SQLite."""

    return value.astimezone(timezone.utc).isoformat()


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime from SQLite."""

    if not value:
        return None
    return datetime.fromisoformat(value)


def runtime_config_bool(config: dict[str, Any], key: str, default: bool = False) -> bool:
    """Read a boolean runtime configuration value from SQLite-backed config."""

    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


class AuthenticationFailedError(Exception):
    """Raised when a login or API key check fails."""


class BootstrapAlreadyCompletedError(Exception):
    """Raised when trying to create the initial admin twice."""


class AdminNotFoundError(Exception):
    """Raised when no administrator account exists for an operation."""


class InvalidCurrentPasswordError(Exception):
    """Raised when the provided current password does not match."""


CONFIG_MAP_CACHE_TTL = 5.0  # runtime_config 每请求都查一次很浪费；给一个 5 秒的进程内缓存
# admin session 校验里的 PBKDF2(260k) 单次约 30ms，前端高频轮询会重复消耗；
# 给一个短 TTL 内的正例缓存，敏感度低于常规密码验证：token 本身已通过熵源保护，
# 且我们仍会验证 expires_at 是否有效。
ADMIN_SESSION_CACHE_TTL = 30.0
API_KEY_CACHE_TTL = 30.0

# Import mixins after shared helpers/exceptions/constants are defined so circular
# imports from mixin modules resolve cleanly.
from server.store_api_keys import ApiKeyMixin  # noqa: E402
from server.store_auth import AdminAuthMixin  # noqa: E402
from server.store_registry import RegistryMixin  # noqa: E402


class ServerStore(AdminAuthMixin, ApiKeyMixin, RegistryMixin):
    """High-level data operations for the server application."""

    def __init__(self, settings: ServerSettings):
        self._settings = settings
        self._database = ServerDatabase(settings)
        self._config_map_cache: Optional[dict[str, Any]] = None
        self._config_map_cache_at: float = 0.0
        self._config_map_lock = threading.Lock()
        # token → (admin_dict, expires_at_epoch, cached_until_monotonic)
        self._admin_session_cache: dict[str, tuple[dict[str, Any], float, float]] = {}
        self._admin_session_cache_lock = threading.Lock()
        # raw_api_key → (record_dict, cached_until_monotonic, last_usage_write_monotonic)
        self._api_key_cache: dict[str, tuple[dict[str, Any], float, float]] = {}
        self._api_key_cache_lock = threading.Lock()

    @property
    def settings(self) -> ServerSettings:
        """Return server settings used by this store."""

        return self._settings

    def initialize(self) -> None:
        """Initialize persistent storage."""

        self._database.initialize()
        self.purge_expired_sessions()
        try:
            self.purge_expired_audit()
        except Exception:
            pass

    def purge_expired_sessions(self) -> int:
        """Delete admin sessions whose ``expires_at`` has already passed."""

        with self._database.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM admin_sessions WHERE expires_at < ?",
                (isoformat(utc_now()),),
            )
            return int(cursor.rowcount)

    def purge_expired_audit(self, retention_days: Optional[int] = None) -> int:
        """Delete audit rows older than the retention window."""

        days = (
            self._settings.audit_retention_days
            if retention_days is None
            else max(0, int(retention_days))
        )
        cutoff = utc_now() - timedelta(days=days)
        with self._database.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM audit_log WHERE occurred_at < ?",
                (isoformat(cutoff),),
            )
            return int(cursor.rowcount)

    def list_config(self) -> list[dict[str, Any]]:
        """List runtime configuration values."""

        with self._database.connect() as conn:
            rows = conn.execute(
                "SELECT key, value, source, updated_at FROM runtime_config ORDER BY key"
            ).fetchall()
        return [
            {
                "key": row["key"],
                "value": json.loads(row["value"]),
                "source": row["source"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def set_config(self, key: str, value: Any, source: str = "database") -> dict[str, Any]:
        """Set a runtime configuration value."""

        now = isoformat(utc_now())
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_config(key, value, source, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), source, now),
            )
        # 主动失效缓存，让下一次读取拿到最新值
        self._invalidate_config_map_cache()
        return {"key": key, "value": value, "source": source, "updated_at": now}

    def get_config_map(self) -> dict[str, Any]:
        """Return runtime configuration as a dictionary.

        每个 HTTP 请求 middleware 都会调用一次，因此在进程内做一个短 TTL
        缓存，避免每次都打开 SQLite。``set_config`` 会主动失效缓存。
        """
        now = time.monotonic()
        cached = self._config_map_cache
        if cached is not None and now - self._config_map_cache_at < CONFIG_MAP_CACHE_TTL:
            return cached

        with self._config_map_lock:
            cached = self._config_map_cache
            if cached is not None and (
                time.monotonic() - self._config_map_cache_at < CONFIG_MAP_CACHE_TTL
            ):
                return cached
            fresh = {item["key"]: item["value"] for item in self.list_config()}
            self._config_map_cache = fresh
            self._config_map_cache_at = time.monotonic()
            return fresh

    def _invalidate_config_map_cache(self) -> None:
        with self._config_map_lock:
            self._config_map_cache = None
            self._config_map_cache_at = 0.0

    def add_audit(
        self,
        action: str,
        result: str,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        source_ip: Optional[str] = None,
        request_path: Optional[str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
    ) -> dict[str, Any]:
        """Write an audit event."""

        event = {
            "id": str(uuid.uuid4()),
            "occurred_at": isoformat(utc_now()),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "source_ip": source_ip,
            "request_path": request_path,
            "result": result,
            "duration_ms": duration_ms,
            "request_id": request_id,
            "metadata": metadata or {},
        }
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log(
                    id, occurred_at, actor_type, actor_id, action, source_ip,
                    request_path, result, duration_ms, request_id, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["occurred_at"],
                    event["actor_type"],
                    event["actor_id"],
                    event["action"],
                    event["source_ip"],
                    event["request_path"],
                    event["result"],
                    event["duration_ms"],
                    event["request_id"],
                    json.dumps(event["metadata"], ensure_ascii=False, default=str),
                ),
            )
        return event

    def list_audit(self, limit: int = 100, action: Optional[str] = None) -> list[dict[str, Any]]:
        """List recent audit events."""

        limit = max(1, min(limit, 500))
        params: list[Any] = []
        where = ""
        if action:
            where = "WHERE action = ?"
            params.append(action)
        params.append(limit)
        with self._database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM audit_log
                {where}
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": row["id"],
                "occurred_at": row["occurred_at"],
                "actor_type": row["actor_type"],
                "actor_id": row["actor_id"],
                "action": row["action"],
                "source_ip": row["source_ip"],
                "request_path": row["request_path"],
                "result": row["result"],
                "duration_ms": row["duration_ms"],
                "request_id": row["request_id"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def clear_cache(self, namespace: Optional[str] = None) -> int:
        """Clear persistent cache entries."""

        with self._database.connect() as conn:
            if namespace:
                cursor = conn.execute("DELETE FROM cache_entries WHERE namespace = ?", (namespace,))
            else:
                cursor = conn.execute("DELETE FROM cache_entries")
            return int(cursor.rowcount)

    def system_checks(self) -> list[dict[str, Any]]:
        """Return deployment-agnostic checks for the current runtime."""

        checks: list[dict[str, Any]] = []
        config_map = self.get_config_map()
        docs_enabled = runtime_config_bool(config_map, "DOCS_ENABLED")
        openapi_enabled = docs_enabled or runtime_config_bool(config_map, "OPENAPI_ENABLED")
        public_base_url = str(config_map.get("PUBLIC_BASE_URL") or self._settings.public_base_url)
        has_admin = self.has_admin()
        homes = self.list_homes()
        api_keys = self.list_api_keys()
        checks.append(
            {
                "key": "server",
                "status": "pass",
                "message": "Server process is running",
            }
        )
        checks.append(self._check_path_writable("data_dir", self._settings.data_dir))
        checks.append(self._check_sqlite())
        checks.append(
            {
                "key": "admin_configured",
                "status": "pass" if has_admin else "warn",
                "message": (
                    "Administrator is configured"
                    if has_admin
                    else "Initial administrator is not configured"
                ),
            }
        )
        checks.append(
            {
                "key": "credential_file",
                "status": "pass" if self._settings.credential_path.exists() else "warn",
                "message": str(self._settings.credential_path),
            }
        )
        checks.append(
            {
                "key": "public_base_url",
                "status": "pass" if public_base_url else "warn",
                "message": public_base_url or "PUBLIC_BASE_URL is not configured",
            }
        )
        checks.append(
            {
                "key": "api_key_exists",
                "status": "pass" if api_keys else "warn",
                "message": (
                    "At least one API key exists"
                    if api_keys
                    else "No API key has been created"
                ),
            }
        )
        checks.append(
            {
                "key": "homes_synced",
                "status": "pass" if homes else "warn",
                "message": ("Homes have been synced" if homes else "No synced homes"),
            }
        )
        checks.append(
            {
                "key": "docs_enabled",
                "status": "info",
                "message": "enabled" if docs_enabled else "disabled",
            }
        )
        checks.append(
            {
                "key": "openapi_enabled",
                "status": "info",
                "message": "enabled" if openapi_enabled else "disabled",
            }
        )
        checks.append(self._check_allow_public_access(config_map))
        credential_permissions_check = self._check_credential_file_permissions(
            self._settings.credential_path
        )
        if credential_permissions_check is not None:
            checks.append(credential_permissions_check)
        return [self._with_check_metadata(check) for check in checks]

    def _check_allow_public_access(self, config_map: dict[str, Any]) -> dict[str, Any]:
        enabled = runtime_config_bool(config_map, "ALLOW_PUBLIC_ACCESS")
        return {
            "key": "allow_public_access",
            "status": "warn" if enabled else "pass",
            "message": (
                "Public access is enabled; ensure this is intentional"
                if enabled
                else "Public access is disabled"
            ),
        }

    def _check_credential_file_permissions(self, path: Path) -> Optional[dict[str, Any]]:
        """检查凭据文件权限是否对同组/其他用户过度开放（仅 POSIX 系统）。"""

        if os.name != "posix" or not path.exists():
            return None
        try:
            mode = path.stat().st_mode
        except OSError as exc:
            return {
                "key": "credential_file_permissions",
                "status": "fail",
                "message": str(exc),
            }
        if mode & 0o077:
            return {
                "key": "credential_file_permissions",
                "status": "warn",
                "message": f"Credential file permissions are too open ({oct(mode & 0o777)})",
            }
        return {
            "key": "credential_file_permissions",
            "status": "pass",
            "message": f"Credential file permissions are restrictive ({oct(mode & 0o777)})",
        }

    def _with_check_metadata(self, check: dict[str, Any]) -> dict[str, Any]:
        metadata = SYSTEM_CHECK_METADATA.get(
            str(check["key"]),
            {"label": str(check["key"]), "description": "系统运行检查项。"},
        )
        return {**check, **metadata}

    def _check_path_writable(self, key: str, path: Path) -> dict[str, Any]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-check"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return {"key": key, "status": "pass", "message": str(path)}
        except OSError as exc:
            return {"key": key, "status": "fail", "message": str(exc)}

    def _check_sqlite(self) -> dict[str, Any]:
        try:
            with self._database.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return {
                "key": "sqlite",
                "status": "pass",
                "message": str(self._settings.database_path),
            }
        except Exception as exc:
            return {"key": "sqlite", "status": "fail", "message": str(exc)}

    def _mask_secret(self, value: str) -> str:
        if len(value) <= 6:
            return "***"
        return f"{value[:3]}***{value[-3:]}"
