"""Runtime configuration for the Mijia API Server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    return Path(value).expanduser()


@dataclass(frozen=True)
class ServerSettings:
    """Settings used by the server shell around the core SDK."""

    host: str = "127.0.0.1"
    port: int = 8123
    data_dir: Path = Path(".mijia/server")
    database_path: Path = Path(".mijia/server/server.sqlite3")
    credential_path: Path = Path(".mijia/credential.json")
    public_base_url: str = ""
    audit_retention_days: int = 30
    admin_session_hours: int = 12
    openapi_enabled: bool = False
    docs_enabled: bool = False
    web_dist_dir: Path = Path("web/dist")

    @classmethod
    def from_env(cls) -> "ServerSettings":
        """Create settings from environment variables."""

        data_dir = _env_path("MIJIA_SERVER_DATA_DIR", Path(".mijia/server"))
        database_path = _env_path("MIJIA_SERVER_DATABASE_PATH", data_dir / "server.sqlite3")
        return cls(
            host=os.getenv("MIJIA_SERVER_HOST", "127.0.0.1"),
            port=_env_int("MIJIA_SERVER_PORT", 8123),
            data_dir=data_dir,
            database_path=database_path,
            credential_path=_env_path("MIJIA_CREDENTIAL_PATH", Path(".mijia/credential.json")),
            public_base_url=os.getenv("MIJIA_PUBLIC_BASE_URL", ""),
            audit_retention_days=_env_int("MIJIA_AUDIT_RETENTION_DAYS", 30),
            admin_session_hours=_env_int("MIJIA_ADMIN_SESSION_HOURS", 12),
            openapi_enabled=_env_bool("MIJIA_OPENAPI_ENABLED", False),
            docs_enabled=_env_bool("MIJIA_DOCS_ENABLED", False),
            web_dist_dir=_env_path("MIJIA_WEB_DIST_DIR", Path("web/dist")),
        )

    def ensure_directories(self) -> None:
        """Create runtime directories required before opening the database."""

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
