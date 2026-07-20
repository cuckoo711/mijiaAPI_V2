"""SQLite schema and connection management for the server layer."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from server.config import ServerSettings

SCHEMA_VERSION = 1

# 依赖存量表结构的索引，必须在 ``_ensure_columns`` 之后再创建。
INDEX_STATEMENTS_AFTER_ENSURE = [
    """
    CREATE INDEX IF NOT EXISTS idx_admin_sessions_token_prefix
    ON admin_sessions(token_prefix)
    """,
]

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        last_login_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_sessions (
        token_hash TEXT PRIMARY KEY,
        token_prefix TEXT,
        admin_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        revoked_at TEXT,
        FOREIGN KEY(admin_id) REFERENCES admin_users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'database',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        key_prefix TEXT NOT NULL UNIQUE,
        key_hash TEXT NOT NULL,
        scopes_json TEXT NOT NULL,
        resource_policy_json TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        expires_at TEXT,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        last_used_ip TEXT,
        use_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS home_registry (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        uid TEXT NOT NULL,
        rooms_json TEXT NOT NULL DEFAULT '[]',
        last_synced_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_registry (
        id TEXT PRIMARY KEY,
        miot_did TEXT NOT NULL UNIQUE,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        alias TEXT,
        model TEXT NOT NULL,
        home_id TEXT NOT NULL,
        room_id TEXT,
        tags_json TEXT NOT NULL DEFAULT '[]',
        group_name TEXT,
        hidden INTEGER NOT NULL DEFAULT 0,
        access_mode TEXT NOT NULL DEFAULT 'read',
        status TEXT NOT NULL DEFAULT 'unknown',
        raw_json TEXT NOT NULL DEFAULT '{}',
        spec_json TEXT,
        last_synced_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scene_registry (
        id TEXT PRIMARY KEY,
        miot_scene_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        home_id TEXT NOT NULL,
        hidden INTEGER NOT NULL DEFAULT 0,
        executable INTEGER NOT NULL DEFAULT 0,
        raw_json TEXT NOT NULL DEFAULT '{}',
        last_synced_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        actor_type TEXT NOT NULL,
        actor_id TEXT,
        action TEXT NOT NULL,
        source_ip TEXT,
        request_path TEXT,
        result TEXT NOT NULL,
        duration_ms INTEGER,
        request_id TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_log_occurred_at
    ON audit_log(occurred_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS cache_entries (
        key TEXT PRIMARY KEY,
        namespace TEXT NOT NULL,
        value_json TEXT NOT NULL,
        expires_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cache_entries_namespace
    ON cache_entries(namespace)
    """,
]


class ServerDatabase:
    """Small SQLite wrapper used by repositories and CLI commands."""

    def __init__(self, settings: ServerSettings):
        self._settings = settings

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a configured SQLite connection.

        ``foreign_keys`` 是 per-connection 设置，需要每次打开都设。
        ``journal_mode = WAL`` 是持久化的库级设置，只在 :meth:`initialize`
        里设置一次即可，避免每次连接都产生一次 header 写入。
        """

        self._settings.ensure_directories()
        conn = sqlite3.connect(self._settings.database_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create all first-version tables if they do not exist."""

        with self.connect() as conn:
            # journal_mode 是持久化设置，一次即可
            conn.execute("PRAGMA journal_mode = WAL")
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            self._ensure_columns(conn)
            # 索引依赖新增列，必须在 _ensure_columns 完成后再创建，
            # 否则存量数据库上会因缺列失败。
            for statement in INDEX_STATEMENTS_AFTER_ENSURE:
                conn.execute(statement)
            conn.execute(
                """
                INSERT OR IGNORE INTO schema_version(version, applied_at)
                VALUES (?, datetime('now'))
                """,
                (SCHEMA_VERSION,),
            )

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced during early development to existing DBs."""

        additions = {
            "admin_sessions": {
                "token_prefix": "TEXT",
            },
            "device_registry": {
                "status": "TEXT NOT NULL DEFAULT 'unknown'",
                "raw_json": "TEXT NOT NULL DEFAULT '{}'",
                "spec_json": "TEXT",
            },
            "scene_registry": {
                "raw_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        }
        for table, columns in additions.items():
            existing = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
