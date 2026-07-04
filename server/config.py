"""Runtime configuration for the Mijia API Server."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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


@dataclass
class ServerSettings:
    """Settings used by the server shell around the core SDK."""

    host: str = "127.0.0.1"
    port: int = 8123
    data_dir: Path = Path("configs")
    database_path: Path = Path("configs/server/server.sqlite3")
    credential_path: Path = Path("configs/credential.json")
    public_base_url: str = ""
    audit_retention_days: int = 30
    admin_session_hours: int = 12
    credential_refresh_before_seconds: int = 24 * 60 * 60
    web_dist_dir: Path = Path("web/dist")
    config_file_path: Path = Path("configs/server.toml")
    config_template_path: Path = Path("configs/server.toml.template")

    @classmethod
    def from_env(cls) -> "ServerSettings":
        """Create settings from environment variables."""
        
        # 检查是否有旧版本配置需要迁移
        cls._migrate_v2_to_v3_if_needed()
        
        # 检查配置文件是否存在，不存在则从模板创建
        config_file = Path("configs/server.toml")
        if not config_file.exists():
            cls._create_default_config(config_file)
        
        # 从环境变量读取配置
        data_dir = _env_path("MIJIA_SERVER_DATA_DIR", Path("configs"))
        database_path = _env_path("MIJIA_SERVER_DATABASE_PATH", data_dir / "server" / "server.sqlite3")
        credential_path = _env_path("MIJIA_CREDENTIAL_PATH", Path("configs/credential.json"))
        
        return cls(
            host=os.getenv("MIJIA_SERVER_HOST", "127.0.0.1"),
            port=_env_int("MIJIA_SERVER_PORT", 8123),
            data_dir=data_dir,
            database_path=database_path,
            credential_path=credential_path,
            public_base_url=os.getenv("MIJIA_PUBLIC_BASE_URL", ""),
            audit_retention_days=_env_int("MIJIA_AUDIT_RETENTION_DAYS", 30),
            admin_session_hours=_env_int("MIJIA_ADMIN_SESSION_HOURS", 12),
            credential_refresh_before_seconds=_env_int(
                "MIJIA_CREDENTIAL_REFRESH_BEFORE_SECONDS", 24 * 60 * 60
            ),
            web_dist_dir=_env_path("MIJIA_WEB_DIST_DIR", Path("web/dist")),
            config_file_path=config_file,
            config_template_path=Path("configs/server.toml.template"),
        )

    def ensure_directories(self) -> None:
        """Create runtime directories required before opening the database."""

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        
    def ensure_config_file(self) -> None:
        """确保配置文件存在，不存在则从模板创建"""
        if not self.config_file_path.exists():
            self._create_default_config(self.config_file_path)
            
    @staticmethod
    def _create_default_config(config_file: Path) -> None:
        """从模板创建默认配置文件"""
        template_file = config_file.with_suffix('.toml.template')
        if template_file.exists():
            config_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_file, config_file)
            
    @classmethod
    def _migrate_v2_to_v3_if_needed(cls) -> None:
        """检查并迁移 v2.x 版本的数据"""
        old_dir = Path(".mijia")
        new_dir = Path("configs")
        
        if not old_dir.exists():
            return
            
        print("检测到旧版本数据，正在迁移到 v3.0...")
        
        # 确保新目录存在
        new_dir.mkdir(parents=True, exist_ok=True)
        
        # 迁移凭据文件
        old_credential = old_dir / "credential.json"
        new_credential = new_dir / "credential.json"
        if old_credential.exists() and not new_credential.exists():
            shutil.move(str(old_credential), str(new_credential))
            print(f"  迁移凭据文件: {old_credential} -> {new_credential}")
            
        # 迁移服务器数据
        old_server = old_dir / "server"
        new_server = new_dir / "server"
        if old_server.exists() and not new_server.exists():
            shutil.move(str(old_server), str(new_server))
            print(f"  迁移服务器数据: {old_server} -> {new_server}")
            
        # 迁移缓存
        old_cache = old_dir / "cache"
        new_cache = new_dir / "cache"
        if old_cache.exists() and not new_cache.exists():
            shutil.move(str(old_cache), str(new_cache))
            print(f"  迁移缓存: {old_cache} -> {new_cache}")
            
        # 保留旧目录作为备份
        backup_dir = old_dir.parent / ".mijia_backup"
        if not backup_dir.exists():
            try:
                old_dir.rename(backup_dir)
                print(f"  旧目录已备份到: {backup_dir}")
            except Exception as e:
                print(f"  警告: 无法重命名旧目录: {e}")
                
        print("迁移完成!")
