"""API key CRUD and validation for ServerStore."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from server.security import generate_api_key, hash_secret, secret_prefix, verify_secret
from server.store import (
    API_KEY_CACHE_TTL,
    DEFAULT_API_KEY_POLICY,
    AuthenticationFailedError,
    isoformat,
    parse_datetime,
    utc_now,
)


class ApiKeyMixin:
    """Mixin providing API key create/list/validate/update/delete operations."""

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
        now_mono = time.monotonic()
        cached = self._api_key_cache.get(key)
        if cached is not None:
            record, cache_until, last_write = cached
            if now_mono <= cache_until:
                expires_at = record.get("expires_at_dt")
                if expires_at and expires_at <= now:
                    self._invalidate_api_key_cache(key=key)
                    raise AuthenticationFailedError("API key expired")
                if required_scope and required_scope not in record["scopes"]:
                    raise AuthenticationFailedError("API key does not have required scope")
                if now_mono - last_write >= API_KEY_CACHE_TTL:
                    self._touch_api_key_usage(record["id"], source_ip, now)
                    with self._api_key_cache_lock:
                        current = self._api_key_cache.get(key)
                        if current is not None:
                            self._api_key_cache[key] = (current[0], current[1], now_mono)
                return {
                    "id": record["id"],
                    "name": record["name"],
                    "key_prefix": record["key_prefix"],
                    "scopes": record["scopes"],
                    "resource_policy": record["resource_policy"],
                }
            with self._api_key_cache_lock:
                if self._api_key_cache.get(key) is cached:
                    self._api_key_cache.pop(key, None)

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
            record = {
                "id": row["id"],
                "name": row["name"],
                "key_prefix": row["key_prefix"],
                "scopes": scopes,
                "resource_policy": json.loads(row["resource_policy_json"]),
                "expires_at_dt": expires_at,
            }

        with self._api_key_cache_lock:
            self._api_key_cache[key] = (record, now_mono + API_KEY_CACHE_TTL, now_mono)
        return {
            "id": record["id"],
            "name": record["name"],
            "key_prefix": record["key_prefix"],
            "scopes": record["scopes"],
            "resource_policy": record["resource_policy"],
        }

    def _touch_api_key_usage(
        self, key_id: str, source_ip: Optional[str], now: datetime
    ) -> None:
        with self._database.connect() as conn:
            conn.execute(
                """
                UPDATE api_keys
                SET last_used_at = ?, last_used_ip = ?, use_count = use_count + 1
                WHERE id = ?
                """,
                (isoformat(now), source_ip, key_id),
            )

    def _invalidate_api_key_cache(
        self, *, key: Optional[str] = None, key_id: Optional[str] = None
    ) -> None:
        with self._api_key_cache_lock:
            if key is not None:
                self._api_key_cache.pop(key, None)
                return
            if key_id is None:
                self._api_key_cache.clear()
                return
            stale = [
                cached_key
                for cached_key, (record, _, _) in self._api_key_cache.items()
                if record.get("id") == key_id
            ]
            for cached_key in stale:
                self._api_key_cache.pop(cached_key, None)

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
        self._invalidate_api_key_cache(key_id=key_id)
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
        self._invalidate_api_key_cache(key_id=key_id)
