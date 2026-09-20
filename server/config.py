"""Runtime configuration for the Mijia API Server."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Python 3.11+ 自带 tomllib，3.9-3.10 回退到 tomli（依赖见 pyproject.toml）。
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[import-not-found, no-redef]
    except ImportError:  # pragma: no cover - tomli 是声明的依赖，正常不会触发
        tomllib = None  # type: ignore[assignment]


def _bundled_base_dir() -> Path:
    """Return the base directory for bundled assets when running as a PyInstaller exe.

    When frozen (packaged with PyInstaller), ``sys._MEIPASS`` points to the
    temporary directory where all datas are extracted.  When running from
    source, we fall back to the project root (the directory that contains the
    ``server/`` package).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # Running from source: __file__ is server/config.py, so go up one level.
    return Path(__file__).resolve().parent.parent


def _load_toml_config(path: Path) -> dict[str, Any]:
    """加载 TOML 配置文件，失败或不存在时返回空字典（不影响其他配置来源）。"""

    if tomllib is None or not path.exists():
        return {}
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except Exception as exc:
        print(f"读取配置文件失败，将忽略 {path}: {exc}")
        return {}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    return Path(value).expanduser()


def _toml_str(section: dict[str, Any], key: str, default: str) -> str:
    value = section.get(key, default)
    return str(value) if value is not None else default


def _toml_int(section: dict[str, Any], key: str, default: int) -> int:
    value = section.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _take_legacy_entry(src: Path, dst: Path, label: str, moved: list[str]) -> None:
    """把旧布局里的一项搬到新位置；目标已存在则丢弃旧项。

    目标存在说明 v3 侧已经是权威数据，旧项直接删掉，避免用陈旧数据覆盖。
    """

    if not src.exists():
        return
    if dst.exists():
        if src.is_dir():
            shutil.rmtree(src, ignore_errors=True)
        else:
            src.unlink(missing_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    moved.append(f"{label}: {src} -> {dst}")


def _drain_legacy_mijia_dir(old_dir: Path, new_dir: Path) -> list[str]:
    """把 ``.mijia`` 里需要的数据搬进 ``configs/``，然后删除整棵旧树。"""

    moved: list[str] = []
    if not old_dir.exists():
        return moved

    new_dir.mkdir(parents=True, exist_ok=True)
    _take_legacy_entry(old_dir / "credential.json", new_dir / "credential.json", "凭据文件", moved)
    _take_legacy_entry(old_dir / ".credential_key", new_dir / ".credential_key", "凭据密钥", moved)
    _take_legacy_entry(old_dir / "server", new_dir / "server", "服务器数据", moved)
    _take_legacy_entry(old_dir / "cache", new_dir / "cache", "缓存", moved)

    # 不保留备份：搬完（或丢弃冲突项）后旧树一律删掉。
    shutil.rmtree(old_dir, ignore_errors=True)
    if old_dir.exists():
        print(f"  警告: 无法删除旧目录 {old_dir}，请手动移除")
    else:
        moved.append(f"已删除旧目录: {old_dir}")
    return moved


def _drop_orphaned_config_cache(new_dir: Path) -> list[str]:
    """删除 ``configs/server/cache``——任何版本里都不是合法的缓存位置。

    不能以「规范目录 ``configs/cache`` 存在」为前提：后者由 ``CacheManager``
    懒创建，全新安装从未实例化过它时，孤儿目录会被永久留下。
    """

    orphaned = new_dir / "server" / "cache"
    if not orphaned.is_dir():
        return []
    shutil.rmtree(orphaned, ignore_errors=True)
    return [] if orphaned.exists() else [f"已删除无用缓存目录: {orphaned}"]


def _drop_legacy_backup_dirs() -> list[str]:
    """清理早期迁移尝试留下的 ``.mijia_backup*`` 目录。"""

    moved: list[str] = []
    for backup in sorted(Path(".").glob(".mijia_backup*")):
        if not backup.is_dir():
            continue
        shutil.rmtree(backup, ignore_errors=True)
        if not backup.exists():
            moved.append(f"已删除旧备份: {backup}")
    return moved


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
    log_level: str = "INFO"
    web_dist_dir: Path = _bundled_base_dir() / "web" / "dist"
    config_file_path: Path = Path("configs/server.toml")
    config_template_path: Path = Path("configs/server.toml.template")

    @classmethod
    def from_env(cls) -> "ServerSettings":
        """Create settings from ``configs/server.toml`` and environment variables.

        优先级（低到高）：dataclass 默认值 < ``configs/server.toml`` < 环境变量。
        环境变量始终覆盖 TOML 文件中的同名配置。
        """

        # 检查是否有旧版本配置需要迁移
        cls._migrate_v2_to_v3_if_needed()

        # 检查配置文件是否存在，不存在则从模板创建
        config_file = Path("configs/server.toml")
        if not config_file.exists():
            cls._create_default_config(config_file)

        toml_config = _load_toml_config(config_file)
        server_section = toml_config.get("server", {}) or {}
        storage_section = toml_config.get("storage", {}) or {}
        security_section = toml_config.get("security", {}) or {}
        logging_section = toml_config.get("logging", {}) or {}

        # 数据目录：TOML -> 环境变量，其余存储路径默认相对于最终的 data_dir。
        data_dir_default = Path(_toml_str(storage_section, "data_dir", "configs"))
        data_dir = _env_path("MIJIA_SERVER_DATA_DIR", data_dir_default)

        database_path_default = Path(
            _toml_str(storage_section, "database_path", str(data_dir / "server" / "server.sqlite3"))
        )
        database_path = _env_path("MIJIA_SERVER_DATABASE_PATH", database_path_default)

        credential_path_default = Path(
            _toml_str(storage_section, "credential_path", "configs/credential.json")
        )
        credential_path = _env_path("MIJIA_CREDENTIAL_PATH", credential_path_default)

        web_dist_dir_default_str = storage_section.get("web_dist_dir")
        web_dist_dir_default = (
            Path(web_dist_dir_default_str)
            if web_dist_dir_default_str
            else _bundled_base_dir() / "web" / "dist"
        )
        web_dist_dir = _env_path("MIJIA_WEB_DIST_DIR", web_dist_dir_default)

        return cls(
            host=_env_str("MIJIA_SERVER_HOST", _toml_str(server_section, "host", "127.0.0.1")),
            port=_env_int("MIJIA_SERVER_PORT", _toml_int(server_section, "port", 8123)),
            data_dir=data_dir,
            database_path=database_path,
            credential_path=credential_path,
            public_base_url=_env_str(
                "MIJIA_PUBLIC_BASE_URL", _toml_str(security_section, "public_base_url", "")
            ),
            audit_retention_days=_env_int(
                "MIJIA_AUDIT_RETENTION_DAYS",
                _toml_int(security_section, "audit_retention_days", 30),
            ),
            admin_session_hours=_env_int(
                "MIJIA_ADMIN_SESSION_HOURS",
                _toml_int(security_section, "admin_session_hours", 12),
            ),
            credential_refresh_before_seconds=_env_int(
                "MIJIA_CREDENTIAL_REFRESH_BEFORE_SECONDS",
                _toml_int(security_section, "credential_refresh_before_seconds", 24 * 60 * 60),
            ),
            log_level=_env_str(
                "MIJIA_SERVER_LOG_LEVEL", _toml_str(logging_section, "level", "INFO")
            ).upper(),
            web_dist_dir=web_dist_dir,
            config_file_path=config_file,
            config_template_path=Path("configs/server.toml.template"),
        )

    def ensure_directories(self) -> None:
        """Create runtime directories required before opening the database."""

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_orphaned_cache_dir()

    def _remove_orphaned_cache_dir(self) -> None:
        """删除 ``<data_dir>/server/cache``——v3.6.7 之前布局留下的无用缓存目录。

        ``_migrate_v2_to_v3_if_needed`` 只看仓库相对的 ``configs/``，够不到自定义
        的 ``data_dir``：Docker 里工作目录是 ``/app`` 而数据在 ``/data``，那条清理
        逻辑对容器完全无效。这里按已解析的 ``data_dir`` 再清一次。

        规范的 SDK 磁盘缓存是 ``<data_dir>/cache``，``server/`` 下的同名目录在任何
        版本里都不是合法位置，因此可以无条件删除；同级的 ``server.sqlite3`` 不受影响。
        """

        orphaned = self.data_dir / "server" / "cache"
        if not orphaned.is_dir():
            return
        shutil.rmtree(orphaned, ignore_errors=True)
        if not orphaned.exists():
            print(f"已删除无用缓存目录: {orphaned}")

    def ensure_config_file(self) -> None:
        """确保配置文件存在，不存在则从模板创建"""
        if not self.config_file_path.exists():
            self._create_default_config(self.config_file_path)

    def apply_log_level(self) -> None:
        """将 ``log_level`` 应用到根 logger，供启动及热更新时调用。"""

        import logging

        level = logging.getLevelName(self.log_level)
        if isinstance(level, str):
            # logging.getLevelName 对未知级别名会原样返回字符串，说明配置无效。
            return
        logging.getLogger().setLevel(level)

    def reload_from_toml(self, path: Optional[Path] = None) -> tuple[list[str], bool]:
        """重新读取 TOML 文件，热更新可以安全生效的字段。

        ``host``/``port``/存储路径等字段已经用于已监听的端口和已打开的数据库
        连接，修改后必须重启进程才能生效；这里只检测差异并把字段名返回给调用方
        用于打日志提醒。目前只有 ``log_level`` 会被真正应用（且仍然遵守
        “环境变量优先于 TOML”的规则，若设置了 ``MIJIA_SERVER_LOG_LEVEL`` 则跳过）。

        Returns:
            (需要重启才能生效的字段列表, 日志级别是否已被热更新)
        """

        toml_path = path or self.config_file_path
        toml_config = _load_toml_config(toml_path)
        server_section = toml_config.get("server", {}) or {}
        storage_section = toml_config.get("storage", {}) or {}
        logging_section = toml_config.get("logging", {}) or {}

        restart_required: list[str] = []
        if _toml_str(server_section, "host", self.host) != self.host:
            restart_required.append("server.host")
        if _toml_int(server_section, "port", self.port) != self.port:
            restart_required.append("server.port")
        if _toml_str(storage_section, "data_dir", str(self.data_dir)) != str(self.data_dir):
            restart_required.append("storage.data_dir")
        if _toml_str(storage_section, "database_path", str(self.database_path)) != str(
            self.database_path
        ):
            restart_required.append("storage.database_path")
        if _toml_str(storage_section, "credential_path", str(self.credential_path)) != str(
            self.credential_path
        ):
            restart_required.append("storage.credential_path")
        if _toml_str(storage_section, "web_dist_dir", str(self.web_dist_dir)) != str(
            self.web_dist_dir
        ):
            restart_required.append("storage.web_dist_dir")

        log_level_changed = False
        if "MIJIA_SERVER_LOG_LEVEL" not in os.environ:
            new_log_level = _toml_str(logging_section, "level", self.log_level).upper()
            if new_log_level != self.log_level:
                self.log_level = new_log_level
                self.apply_log_level()
                log_level_changed = True

        return restart_required, log_level_changed

    @staticmethod
    def _create_default_config(config_file: Path) -> None:
        """从模板创建默认配置文件"""
        template_file = config_file.with_suffix(".toml.template")
        if template_file.exists():
            config_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_file, config_file)

    @classmethod
    def _migrate_v2_to_v3_if_needed(cls) -> None:
        """Migrate leftover ``.mijia`` data into ``configs/``, then delete the old tree.

        Idempotent and silent when already on the v3 layout. After taking what
        we need (or discarding collisions), the project-local ``.mijia``
        directory and any ``.mijia_backup*`` leftovers are removed — no backup
        retention.
        """

        new_dir = Path("configs")
        moved = [
            *_drain_legacy_mijia_dir(Path(".mijia"), new_dir),
            *_drop_orphaned_config_cache(new_dir),
            *_drop_legacy_backup_dirs(),
        ]

        if moved:
            print("检测到旧版本数据，正在迁移到 configs/ ...")
            for line in moved:
                print(f"  {line}")
            print("迁移完成!")
