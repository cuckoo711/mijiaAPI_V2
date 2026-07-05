"""GitHub Releases 更新检查。

提供一个带进程内 TTL 缓存的 :class:`UpdateChecker`，从 GitHub Releases API
拉取最新发行版本并与当前运行版本比对。缓存 + 后台线程避免每次请求都触发网络。

设计原则：
- 网络请求超时较短（8 秒），失败静默降级为"未知"，不阻塞前端 UI。
- TTL 缓存默认 1 小时，避免高频轮询触碰 GitHub 60/hour 的匿名 API 限额。
- 版本比较使用宽松的 PEP 440 / 语义化版本规则；无法解析时降级为字符串相等判断。
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import httpx

from mijiaAPI_V2.core.logging import get_logger

logger = get_logger(__name__)

# 默认指向本项目的公开仓库。运维如需切换 fork，通过 update_repository 更新即可。
DEFAULT_OWNER = "cuckoo711"
DEFAULT_REPO = "mijiaAPI_V2"

_UPDATE_CACHE_TTL_SECONDS = 3600  # 缓存 1 小时，减少 GitHub API 限流风险
_REQUEST_TIMEOUT = 8.0


@dataclass
class ReleaseInfo:
    """一次成功的最新版本查询结果。"""

    latest_version: str
    latest_tag: str
    published_at: Optional[str]
    release_url: str
    release_notes: str
    fetched_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("fetched_at", None)
        return payload


def _parse_version(value: str) -> Optional[tuple[int, ...]]:
    """把 ``v3.1.2`` / ``3.1.2`` / ``3.1.2-rc1`` 解析成数字元组。

    非数字后缀会被丢弃（仅用于比较主/次/修订）。返回 None 表示无法解析。
    """
    if not value:
        return None
    match = re.match(r"^v?(\d+(?:\.\d+)*)", value.strip())
    if not match:
        return None
    try:
        return tuple(int(x) for x in match.group(1).split("."))
    except ValueError:
        return None


def compare_versions(current: str, latest: str) -> int:
    """比较两个版本字符串。返回 -1 表示 current<latest，0 相等，1 表示 current>latest。

    无法解析时降级为字符串相等，不等则返回 -1（保守认为可能有更新）。
    """
    current_parts = _parse_version(current)
    latest_parts = _parse_version(latest)
    if current_parts is None or latest_parts is None:
        if current == latest:
            return 0
        return -1
    # 补齐位数
    length = max(len(current_parts), len(latest_parts))
    padded_current = current_parts + (0,) * (length - len(current_parts))
    padded_latest = latest_parts + (0,) * (length - len(latest_parts))
    if padded_current < padded_latest:
        return -1
    if padded_current > padded_latest:
        return 1
    return 0


class UpdateChecker:
    """从 GitHub Releases 检查最新版本，带进程内缓存。"""

    def __init__(
        self,
        current_version: str,
        owner: str = DEFAULT_OWNER,
        repo: str = DEFAULT_REPO,
        cache_ttl_seconds: int = _UPDATE_CACHE_TTL_SECONDS,
    ) -> None:
        self._current_version = current_version
        self._owner = owner
        self._repo = repo
        self._cache_ttl = cache_ttl_seconds
        self._lock = threading.Lock()
        self._cached: Optional[ReleaseInfo] = None
        self._cached_error: Optional[str] = None
        self._cached_at: float = 0.0

    @property
    def repository_url(self) -> str:
        return f"https://github.com/{self._owner}/{self._repo}"

    def update_repository(self, owner: str, repo: str) -> None:
        """切换到另一个 owner/repo（例如内部 fork）；同时清空缓存。"""
        with self._lock:
            self._owner = owner
            self._repo = repo
            self._cached = None
            self._cached_error = None
            self._cached_at = 0.0

    def check(self, force: bool = False) -> dict[str, Any]:
        """返回 update 状态字典。

        字段：
        - ``current_version``：当前运行版本
        - ``latest``：ReleaseInfo 序列化（或 None）
        - ``update_available``：布尔值
        - ``error``：网络失败时的错误说明；不阻塞返回
        - ``checked_at``：本次检查时间戳（进程内单调时间，仅用于前端展示相对时间）
        - ``repository_url``：仓库主页链接
        """
        now = time.time()
        if not force and self._cached is not None and now - self._cached_at < self._cache_ttl:
            return self._build_result(self._cached, error=self._cached_error, checked_at=self._cached_at)

        with self._lock:
            if not force and self._cached is not None and now - self._cached_at < self._cache_ttl:
                return self._build_result(
                    self._cached, error=self._cached_error, checked_at=self._cached_at
                )
            try:
                fresh = self._fetch_latest_release()
                self._cached = fresh
                self._cached_error = None
                self._cached_at = time.time()
                return self._build_result(fresh, error=None, checked_at=self._cached_at)
            except Exception as exc:  # noqa: BLE001 — 静默降级
                error_message = str(exc)
                logger.warning(f"检查更新失败: {error_message}")
                self._cached_error = error_message
                self._cached_at = time.time()
                return self._build_result(
                    self._cached, error=error_message, checked_at=self._cached_at
                )

    def _fetch_latest_release(self) -> ReleaseInfo:
        api_url = f"https://api.github.com/repos/{self._owner}/{self._repo}/releases/latest"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"mijia-server/{self._current_version}",
        }
        response = httpx.get(api_url, headers=headers, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        tag = str(data.get("tag_name") or "")
        if not tag:
            raise RuntimeError("GitHub Releases 未返回 tag_name")
        # tag 通常是 v3.1.2；version 保留去掉前缀的形式便于比较展示
        version = tag[1:] if tag.startswith("v") else tag
        return ReleaseInfo(
            latest_version=version,
            latest_tag=tag,
            published_at=data.get("published_at"),
            release_url=str(data.get("html_url") or self.repository_url),
            release_notes=str(data.get("body") or ""),
        )

    def _build_result(
        self,
        release: Optional[ReleaseInfo],
        *,
        error: Optional[str],
        checked_at: float,
    ) -> dict[str, Any]:
        update_available = False
        if release is not None:
            update_available = (
                compare_versions(self._current_version, release.latest_version) < 0
            )
        return {
            "current_version": self._current_version,
            "latest": release.as_dict() if release is not None else None,
            "update_available": update_available,
            "error": error,
            "checked_at": checked_at,
            "repository_url": self.repository_url,
        }
