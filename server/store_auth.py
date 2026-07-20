"""Administrator authentication and session management for ServerStore."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from server.security import (
    generate_session_token,
    hash_secret,
    secret_prefix,
    verify_secret,
)
from server.store import (
    ADMIN_SESSION_CACHE_TTL,
    AdminNotFoundError,
    AuthenticationFailedError,
    BootstrapAlreadyCompletedError,
    InvalidCurrentPasswordError,
    isoformat,
    parse_datetime,
    utc_now,
)


class AdminAuthMixin:
    """Mixin providing administrator auth, password, and session operations."""

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
                self._record_admin_auth_failure(conn, row, now)
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
            from server.logging_utils import get_server_logger

            get_server_logger(__name__).warning(
                "purge_expired_sessions during login failed",
                exc_info=True,
            )
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

    def _record_admin_auth_failure(self, conn: Any, row: Any, now: datetime) -> None:
        """Increment failed-login counters and optionally lock the account."""

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

    def _revoke_admin_sessions(
        self,
        conn: Any,
        admin_id: str,
        *,
        keep_token: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> None:
        """Revoke administrator sessions, optionally keeping the caller's token."""

        revoked_at = isoformat(now or utc_now())
        if keep_token is None:
            conn.execute(
                """
                UPDATE admin_sessions
                SET revoked_at = ?
                WHERE admin_id = ? AND revoked_at IS NULL
                """,
                (revoked_at, admin_id),
            )
            return

        rows = conn.execute(
            """
            SELECT token_hash
            FROM admin_sessions
            WHERE admin_id = ? AND revoked_at IS NULL
            """,
            (admin_id,),
        ).fetchall()
        for row in rows:
            if verify_secret(keep_token, row["token_hash"]):
                continue
            conn.execute(
                "UPDATE admin_sessions SET revoked_at = ? WHERE token_hash = ?",
                (revoked_at, row["token_hash"]),
            )

    def change_admin_password(
        self,
        admin_id: str,
        current_password: str,
        new_password: str,
        *,
        keep_session_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Change an administrator password after verifying the current one."""

        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if current_password == new_password:
            raise ValueError("New password must differ from the current password")

        now = utc_now()
        with self._database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM admin_users WHERE id = ?",
                (admin_id,),
            ).fetchone()
            if row is None:
                raise AdminNotFoundError("Administrator not found")

            locked_until = parse_datetime(row["locked_until"])
            if locked_until and locked_until > now:
                raise AuthenticationFailedError("Administrator account is locked")

            if not verify_secret(current_password, row["password_hash"]):
                self._record_admin_auth_failure(conn, row, now)
                raise InvalidCurrentPasswordError("Invalid current password")

            updated_at = isoformat(now)
            conn.execute(
                """
                UPDATE admin_users
                SET password_hash = ?,
                    failed_attempts = 0,
                    locked_until = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (hash_secret(new_password), updated_at, admin_id),
            )
            self._revoke_admin_sessions(
                conn,
                admin_id,
                keep_token=keep_session_token,
                now=now,
            )

        self._invalidate_admin_session_cache()
        return {
            "id": row["id"],
            "username": row["username"],
            "updated_at": updated_at,
        }

    def reset_admin_password(
        self,
        new_password: str,
        *,
        username: Optional[str] = None,
    ) -> dict[str, Any]:
        """Reset an administrator password without knowing the current one.

        Intended for local CLI recovery. Revokes every active admin session.
        """

        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")

        now = utc_now()
        with self._database.connect() as conn:
            if username:
                row = conn.execute(
                    "SELECT * FROM admin_users WHERE username = ?",
                    (username,),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM admin_users LIMIT 1").fetchone()
            if row is None:
                raise AdminNotFoundError("Administrator not found")

            updated_at = isoformat(now)
            conn.execute(
                """
                UPDATE admin_users
                SET password_hash = ?,
                    failed_attempts = 0,
                    locked_until = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (hash_secret(new_password), updated_at, row["id"]),
            )
            self._revoke_admin_sessions(conn, row["id"], now=now)

        self._invalidate_admin_session_cache()
        return {
            "id": row["id"],
            "username": row["username"],
            "updated_at": updated_at,
        }

    def validate_admin_session(self, token: str) -> dict[str, Any]:
        """Validate an administrator session token.

        为避免每个请求都跑一次 PBKDF2，正例结果会在短 TTL 内被缓存；
        缓存条目仍会检查 session 的 ``expires_at``，过期立即淘汰。
        """

        now_epoch = utc_now().timestamp()
        now_mono = time.monotonic()

        cached = self._admin_session_cache.get(token)
        if cached is not None:
            admin, session_expires_at, cache_until = cached
            if now_epoch <= session_expires_at and now_mono <= cache_until:
                return admin
            # 缓存过期或 session 到期：主动清理
            with self._admin_session_cache_lock:
                if self._admin_session_cache.get(token) is cached:
                    self._admin_session_cache.pop(token, None)

        prefix = secret_prefix(token)
        now = utc_now()
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
                admin = {"id": row["id"], "username": row["username"]}
                cache_until = time.monotonic() + ADMIN_SESSION_CACHE_TTL
                with self._admin_session_cache_lock:
                    self._admin_session_cache[token] = (
                        admin,
                        expires_at.timestamp(),
                        cache_until,
                    )
                return admin

        raise AuthenticationFailedError("Invalid administrator session")

    def _invalidate_admin_session_cache(self, token: Optional[str] = None) -> None:
        """使 admin session 缓存条目失效。``token=None`` 清空全部。"""
        with self._admin_session_cache_lock:
            if token is None:
                self._admin_session_cache.clear()
            else:
                self._admin_session_cache.pop(token, None)

    def revoke_admin_session(self, token: str) -> bool:
        """Revoke a single administrator session token. Returns True if found."""

        self._invalidate_admin_session_cache(token)
        prefix = secret_prefix(token)
        revoked_at = isoformat(utc_now())
        with self._database.connect() as conn:
            rows = conn.execute(
                """
                SELECT token_hash
                FROM admin_sessions
                WHERE token_prefix = ? AND revoked_at IS NULL
                """,
                (prefix,),
            ).fetchall()
            for row in rows:
                if not verify_secret(token, row["token_hash"]):
                    continue
                conn.execute(
                    "UPDATE admin_sessions SET revoked_at = ? WHERE token_hash = ?",
                    (revoked_at, row["token_hash"]),
                )
                return True
        return False

    def refresh_admin_session(self, token: str) -> dict[str, Any]:
        """Extend a valid administrator session and return its new expiry."""

        # session 的 expires_at 会变，先清掉缓存中该 token 的旧条目
        self._invalidate_admin_session_cache(token)

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
