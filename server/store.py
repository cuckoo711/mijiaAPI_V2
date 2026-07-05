"""Repository-style access to server-local data."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from server.config import ServerSettings
from server.db import ServerDatabase
from server.security import (
    generate_api_key,
    generate_session_token,
    hash_secret,
    secret_prefix,
    verify_secret,
)

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


class ServerStore:
    """High-level data operations for the server application."""

    def __init__(self, settings: ServerSettings):
        self._settings = settings
        self._database = ServerDatabase(settings)

    @property
    def settings(self) -> ServerSettings:
        """Return server settings used by this store."""

        return self._settings

    def initialize(self) -> None:
        """Initialize persistent storage."""

        self._database.initialize()
        self.purge_expired_sessions()

    def purge_expired_sessions(self) -> int:
        """Delete admin sessions whose ``expires_at`` has already passed."""

        with self._database.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM admin_sessions WHERE expires_at < ?",
                (isoformat(utc_now()),),
            )
            return int(cursor.rowcount)

    def has_admin(self) -> bool:
        """Return whether the bootstrap administrator already exists."""

        with self._database.connect() as conn:
            row = conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone()
            return row is not None

    def create_initial_admin(self, username: str, password: str) -> dict[str, Any]:
        """Create the first administrator account."""

        if self.has_admin():
            raise BootstrapAlreadyCompletedError("Administrator already exists")

        now = isoformat(utc_now())
        admin_id = str(uuid.uuid4())
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_users(
                    id, username, password_hash, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (admin_id, username, hash_secret(password), now, now),
            )
        return {"id": admin_id, "username": username, "created_at": now}

    def authenticate_admin(self, username: str, password: str) -> dict[str, Any]:
        """Validate administrator credentials and create a session token."""

        now = utc_now()
        with self._database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM admin_users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                raise AuthenticationFailedError("Invalid administrator credentials")

            locked_until = parse_datetime(row["locked_until"])
            if locked_until and locked_until > now:
                raise AuthenticationFailedError("Administrator account is locked")

            if not verify_secret(password, row["password_hash"]):
                failed_attempts = int(row["failed_attempts"]) + 1
                lock_until_value = None
                if failed_attempts >= 5:
                    lock_until_value = isoformat(now + timedelta(minutes=15))
                    failed_attempts = 0
                conn.execute(
                    """
                    UPDATE admin_users
                    SET failed_attempts = ?, locked_until = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (failed_attempts, lock_until_value, isoformat(now), row["id"]),
                )
                raise AuthenticationFailedError("Invalid administrator credentials")

            conn.execute(
                """
                UPDATE admin_users
                SET failed_attempts = 0,
                    locked_until = NULL,
                    last_login_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (isoformat(now), isoformat(now), row["id"]),
            )

        token = generate_session_token()
        expires_at = now + timedelta(hours=self._settings.admin_session_hours)
        # Best-effort cleanup so expired sessions do not accumulate indefinitely.
        try:
            self.purge_expired_sessions()
        except Exception:
            pass
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_sessions(
                    token_hash, token_prefix, admin_id, expires_at, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    hash_secret(token),
                    secret_prefix(token),
                    row["id"],
                    isoformat(expires_at),
                    isoformat(now),
                ),
            )
        return {
            "token": token,
            "expires_at": isoformat(expires_at),
            "admin": {"id": row["id"], "username": row["username"]},
        }

    def validate_admin_session(self, token: str) -> dict[str, Any]:
        """Validate an administrator session token."""

        now = utc_now()
        prefix = secret_prefix(token)
        with self._database.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.token_hash, s.expires_at, s.revoked_at, u.id, u.username
                FROM admin_sessions s
                JOIN admin_users u ON u.id = s.admin_id
                WHERE s.token_prefix = ? AND s.revoked_at IS NULL
                """,
                (prefix,),
            ).fetchall()

            for row in rows:
                if not verify_secret(token, row["token_hash"]):
                    continue
                expires_at = parse_datetime(row["expires_at"])
                if expires_at is None or expires_at <= now:
                    raise AuthenticationFailedError("Administrator session expired")
                return {"id": row["id"], "username": row["username"]}

        raise AuthenticationFailedError("Invalid administrator session")

    def refresh_admin_session(self, token: str) -> dict[str, Any]:
        """Extend a valid administrator session and return its new expiry."""

        now = utc_now()
        expires_at = now + timedelta(hours=self._settings.admin_session_hours)
        prefix = secret_prefix(token)
        with self._database.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.token_hash, s.expires_at, s.revoked_at, u.id, u.username
                FROM admin_sessions s
                JOIN admin_users u ON u.id = s.admin_id
                WHERE s.token_prefix = ? AND s.revoked_at IS NULL
                """,
                (prefix,),
            ).fetchall()

            for row in rows:
                if not verify_secret(token, row["token_hash"]):
                    continue
                current_expires_at = parse_datetime(row["expires_at"])
                if current_expires_at is None or current_expires_at <= now:
                    raise AuthenticationFailedError("Administrator session expired")
                conn.execute(
                    "UPDATE admin_sessions SET expires_at = ? WHERE token_hash = ?",
                    (isoformat(expires_at), row["token_hash"]),
                )
                return {
                    "token": token,
                    "expires_at": isoformat(expires_at),
                    "admin": {"id": row["id"], "username": row["username"]},
                }

        raise AuthenticationFailedError("Invalid administrator session")

    def create_api_key(
        self,
        name: str,
        scopes: list[str],
        resource_policy: Optional[dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Create an API key and return the plaintext value once."""

        key = generate_api_key()
        key_id = str(uuid.uuid4())
        now = isoformat(utc_now())
        policy = resource_policy or DEFAULT_API_KEY_POLICY
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys(
                    id, name, key_prefix, key_hash, scopes_json,
                    resource_policy_json, expires_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key_id,
                    name,
                    secret_prefix(key),
                    hash_secret(key),
                    json.dumps(scopes, ensure_ascii=False),
                    json.dumps(policy, ensure_ascii=False),
                    isoformat(expires_at) if expires_at else None,
                    now,
                ),
            )
        return {
            "id": key_id,
            "name": name,
            "key": key,
            "key_prefix": secret_prefix(key),
            "scopes": scopes,
            "resource_policy": policy,
            "created_at": now,
            "expires_at": isoformat(expires_at) if expires_at else None,
        }

    def list_api_keys(self) -> list[dict[str, Any]]:
        """List API keys without returning plaintext values."""

        with self._database.connect() as conn:
            rows = conn.execute("""
                SELECT id, name, key_prefix, scopes_json, resource_policy_json,
                       is_active, expires_at, created_at, last_used_at,
                       last_used_ip, use_count
                FROM api_keys
                ORDER BY created_at DESC
                """).fetchall()
        return [
            {
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
            for row in rows
        ]

    def validate_api_key(
        self, key: str, required_scope: Optional[str] = None, source_ip: Optional[str] = None
    ) -> dict[str, Any]:
        """Validate an API key and optionally require a scope."""

        now = utc_now()
        prefix = secret_prefix(key)
        with self._database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_prefix = ? AND is_active = 1",
                (prefix,),
            ).fetchone()
            if row is None or not verify_secret(key, row["key_hash"]):
                raise AuthenticationFailedError("Invalid API key")

            expires_at = parse_datetime(row["expires_at"])
            if expires_at and expires_at <= now:
                raise AuthenticationFailedError("API key expired")

            scopes = json.loads(row["scopes_json"])
            if required_scope and required_scope not in scopes:
                raise AuthenticationFailedError("API key does not have required scope")

            conn.execute(
                """
                UPDATE api_keys
                SET last_used_at = ?, last_used_ip = ?, use_count = use_count + 1
                WHERE id = ?
                """,
                (isoformat(now), source_ip, row["id"]),
            )

        return {
            "id": row["id"],
            "name": row["name"],
            "key_prefix": row["key_prefix"],
            "scopes": scopes,
            "resource_policy": json.loads(row["resource_policy_json"]),
        }

    def update_api_key_status(self, key_id: str, is_active: bool) -> dict[str, Any]:
        """Enable or disable an API key."""

        with self._database.connect() as conn:
            conn.execute(
                "UPDATE api_keys SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, key_id),
            )
            row = conn.execute(
                """
                SELECT id, name, key_prefix, scopes_json, resource_policy_json,
                       is_active, expires_at, created_at, last_used_at,
                       last_used_ip, use_count
                FROM api_keys WHERE id = ?
                """,
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

    def delete_api_key(self, key_id: str) -> None:
        """Delete an API key."""

        with self._database.connect() as conn:
            conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))

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
        return {"key": key, "value": value, "source": source, "updated_at": now}

    def get_config_map(self) -> dict[str, Any]:
        """Return runtime configuration as a dictionary."""

        return {item["key"]: item["value"] for item in self.list_config()}

    def replace_home_registry(self, homes: list[dict[str, Any]]) -> None:
        """Persist synced homes."""

        now = isoformat(utc_now())
        with self._database.connect() as conn:
            for home in homes:
                conn.execute(
                    """
                    INSERT INTO home_registry(id, name, uid, rooms_json, last_synced_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        uid = excluded.uid,
                        rooms_json = excluded.rooms_json,
                        last_synced_at = excluded.last_synced_at
                    """,
                    (
                        str(home["id"]),
                        str(home.get("name", "")),
                        str(home.get("uid", "")),
                        json.dumps(home.get("rooms", []), ensure_ascii=False),
                        now,
                    ),
                )

    def upsert_devices(self, devices: list[dict[str, Any]]) -> None:
        """Persist synced devices while preserving local aliases and permissions."""

        now = isoformat(utc_now())
        with self._database.connect() as conn:
            for device in devices:
                miot_did = str(device["did"])
                slug = self._unique_slug(
                    conn,
                    base=device.get("slug") or self._slugify(device.get("name") or miot_did),
                    current_did=miot_did,
                )
                conn.execute(
                    """
                    INSERT INTO device_registry(
                        id, miot_did, slug, name, alias, model, home_id, room_id,
                        tags_json, group_name, hidden, access_mode, status,
                        raw_json, spec_json, last_synced_at
                    )
                    VALUES (?, ?, ?, ?, NULL, ?, ?, ?, '[]', NULL, 0, 'read',
                            ?, ?, ?, ?)
                    ON CONFLICT(miot_did) DO UPDATE SET
                        name = excluded.name,
                        model = excluded.model,
                        home_id = excluded.home_id,
                        room_id = excluded.room_id,
                        status = excluded.status,
                        raw_json = excluded.raw_json,
                        spec_json = COALESCE(excluded.spec_json, device_registry.spec_json),
                        last_synced_at = excluded.last_synced_at
                    """,
                    (
                        str(device.get("id") or uuid.uuid4()),
                        miot_did,
                        slug,
                        str(device.get("name", "")),
                        str(device.get("model", "")),
                        str(device.get("home_id", "")),
                        device.get("room_id"),
                        str(device.get("status", "unknown")),
                        json.dumps(device, ensure_ascii=False, default=str),
                        (
                            json.dumps(device.get("spec"), ensure_ascii=False, default=str)
                            if device.get("spec") is not None
                            else None
                        ),
                        now,
                    ),
                )

    def upsert_scenes(self, scenes: list[dict[str, Any]]) -> None:
        """Persist synced scenes while preserving local executable flags."""

        now = isoformat(utc_now())
        with self._database.connect() as conn:
            for scene in scenes:
                scene_id = str(scene["scene_id"])
                conn.execute(
                    """
                    INSERT INTO scene_registry(
                        id, miot_scene_id, name, home_id, hidden, executable,
                        raw_json, last_synced_at
                    )
                    VALUES (?, ?, ?, ?, 0, 0, ?, ?)
                    ON CONFLICT(miot_scene_id) DO UPDATE SET
                        name = excluded.name,
                        home_id = excluded.home_id,
                        raw_json = excluded.raw_json,
                        last_synced_at = excluded.last_synced_at
                    """,
                    (
                        str(scene.get("id") or uuid.uuid4()),
                        scene_id,
                        str(scene.get("name", "")),
                        str(scene.get("home_id", "")),
                        json.dumps(scene, ensure_ascii=False, default=str),
                        now,
                    ),
                )

    def list_homes(self) -> list[dict[str, Any]]:
        """List locally synced homes."""

        with self._database.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, uid, rooms_json, last_synced_at FROM home_registry ORDER BY name"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "uid": row["uid"],
                "rooms": json.loads(row["rooms_json"]),
                "last_synced_at": row["last_synced_at"],
            }
            for row in rows
        ]

    def list_devices(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        """List locally synced devices."""

        where = "" if include_hidden else "WHERE hidden = 0"
        with self._database.connect() as conn:
            rows = conn.execute(f"""
                SELECT * FROM device_registry
                {where}
                ORDER BY home_id, group_name, COALESCE(alias, name), name
                """).fetchall()
        return [self._device_from_row(row) for row in rows]

    def get_device(self, device_slug_or_id: str) -> dict[str, Any]:
        """Get a device by slug, internal id, or original did."""

        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM device_registry
                WHERE slug = ? OR id = ? OR miot_did = ?
                """,
                (device_slug_or_id, device_slug_or_id, device_slug_or_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Device not found: {device_slug_or_id}")
        return self._device_from_row(row)

    def update_device(self, device_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update local device presentation and authorization metadata."""

        current = self.get_device(device_id)
        allowed = {"slug", "alias", "tags", "group_name", "hidden", "access_mode"}
        values = {key: value for key, value in updates.items() if key in allowed}
        if "tags" in values:
            values["tags_json"] = json.dumps(values.pop("tags"), ensure_ascii=False)
        if not values:
            return current

        assignments = ", ".join(f"{key} = ?" for key in values)
        params = list(values.values()) + [current["id"]]
        with self._database.connect() as conn:
            conn.execute(f"UPDATE device_registry SET {assignments} WHERE id = ?", params)
        return self.get_device(current["id"])

    def list_scenes(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        """List locally synced scenes."""

        where = "" if include_hidden else "WHERE hidden = 0"
        with self._database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM scene_registry {where} ORDER BY home_id, name"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "scene_id": row["miot_scene_id"],
                "name": row["name"],
                "home_id": row["home_id"],
                "hidden": bool(row["hidden"]),
                "executable": bool(row["executable"]),
                "raw": json.loads(row["raw_json"]),
                "last_synced_at": row["last_synced_at"],
            }
            for row in rows
        ]

    def get_scene(self, scene_id: str) -> dict[str, Any]:
        """Get a scene by internal id or original scene id."""

        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM scene_registry
                WHERE id = ? OR miot_scene_id = ?
                """,
                (scene_id, scene_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Scene not found: {scene_id}")
        return {
            "id": row["id"],
            "scene_id": row["miot_scene_id"],
            "name": row["name"],
            "home_id": row["home_id"],
            "hidden": bool(row["hidden"]),
            "executable": bool(row["executable"]),
            "raw": json.loads(row["raw_json"]),
            "last_synced_at": row["last_synced_at"],
        }

    def update_scene(self, scene_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update local scene presentation and authorization metadata."""

        current = self.get_scene(scene_id)
        allowed = {"hidden", "executable"}
        values = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return current
        assignments = ", ".join(f"{key} = ?" for key in values)
        params = [
            1 if value is True else 0 if value is False else value for value in values.values()
        ]
        params.append(current["id"])
        with self._database.connect() as conn:
            conn.execute(f"UPDATE scene_registry SET {assignments} WHERE id = ?", params)
        return self.get_scene(current["id"])

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
        return [self._with_check_metadata(check) for check in checks]

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

    def _device_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "did": row["miot_did"],
            "did_masked": self._mask_secret(row["miot_did"]),
            "slug": row["slug"],
            "name": row["name"],
            "alias": row["alias"],
            "display_name": row["alias"] or row["name"],
            "model": row["model"],
            "home_id": row["home_id"],
            "room_id": row["room_id"],
            "tags": json.loads(row["tags_json"]),
            "group_name": row["group_name"],
            "hidden": bool(row["hidden"]),
            "access_mode": row["access_mode"],
            "status": row["status"],
            "raw": json.loads(row["raw_json"]),
            "spec": json.loads(row["spec_json"]) if row["spec_json"] else None,
            "last_synced_at": row["last_synced_at"],
        }

    def _unique_slug(self, conn: Any, base: str, current_did: str) -> str:
        slug = self._slugify(base)
        candidate = slug
        index = 2
        while True:
            row = conn.execute(
                "SELECT miot_did FROM device_registry WHERE slug = ?",
                (candidate,),
            ).fetchone()
            if row is None or row["miot_did"] == current_did:
                return candidate
            candidate = f"{slug}-{index}"
            index += 1

    def _slugify(self, value: str) -> str:
        chars = []
        for char in value.lower().strip():
            if char.isalnum():
                chars.append(char)
            elif char in {" ", "_", "-", ".", "/"}:
                chars.append("-")
        slug = "".join(chars).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        return slug or f"device-{uuid.uuid4().hex[:8]}"

    def _mask_secret(self, value: str) -> str:
        if len(value) <= 6:
            return "***"
        return f"{value[:3]}***{value[-3:]}"
