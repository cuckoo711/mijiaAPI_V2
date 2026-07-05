"""UpdateChecker 单元测试。"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from server.updater import UpdateChecker, compare_versions


def test_compare_versions_basic() -> None:
    assert compare_versions("3.1.1", "3.1.2") == -1
    assert compare_versions("3.1.2", "3.1.2") == 0
    assert compare_versions("3.2.0", "3.1.2") == 1
    # 带 v 前缀应被去掉
    assert compare_versions("v3.1.0", "3.1.1") == -1
    # 长度不一致时补零
    assert compare_versions("3", "3.0.0") == 0
    assert compare_versions("3.1", "3.1.1") == -1


def test_compare_versions_falls_back_gracefully() -> None:
    # 无法解析时，字符串相等返回 0；否则保守返回 -1
    assert compare_versions("garbage", "garbage") == 0
    assert compare_versions("garbage", "3.1.0") == -1


def _fake_response(payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_check_reports_update_available_when_newer() -> None:
    checker = UpdateChecker(current_version="3.1.1")
    with patch("httpx.get") as mock_get:
        mock_get.return_value = _fake_response(
            {
                "tag_name": "v3.1.2",
                "html_url": "https://github.com/cuckoo711/mijiaAPI_V2/releases/tag/v3.1.2",
                "published_at": "2026-07-05T07:00:00Z",
                "body": "release notes",
            }
        )
        result = checker.check(force=True)

    assert result["update_available"] is True
    assert result["latest"]["latest_version"] == "3.1.2"
    assert result["latest"]["latest_tag"] == "v3.1.2"
    assert result["error"] is None


def test_check_reports_up_to_date() -> None:
    checker = UpdateChecker(current_version="3.1.2")
    with patch("httpx.get") as mock_get:
        mock_get.return_value = _fake_response(
            {
                "tag_name": "v3.1.2",
                "html_url": "https://example.com/r",
                "published_at": None,
                "body": "",
            }
        )
        result = checker.check(force=True)

    assert result["update_available"] is False
    assert result["latest"]["latest_version"] == "3.1.2"


def test_check_caches_within_ttl() -> None:
    checker = UpdateChecker(current_version="3.1.1", cache_ttl_seconds=3600)
    with patch("httpx.get") as mock_get:
        mock_get.return_value = _fake_response({"tag_name": "v3.1.2"})
        checker.check()
        checker.check()
        checker.check()
    # 二/三次调用应命中缓存，只发一次网络请求
    assert mock_get.call_count == 1


def test_check_swallows_errors_and_returns_partial_state() -> None:
    checker = UpdateChecker(current_version="3.1.1")
    with patch("httpx.get") as mock_get:
        mock_get.side_effect = RuntimeError("network down")
        result = checker.check(force=True)

    assert result["error"] == "network down"
    assert result["latest"] is None
    # 没有 latest 时保持 update_available=False，避免误报
    assert result["update_available"] is False


def test_repository_url_defaults_to_public_repo() -> None:
    checker = UpdateChecker(current_version="3.1.1")
    assert checker.repository_url == "https://github.com/cuckoo711/mijiaAPI_V2"


def test_update_repository_clears_cache() -> None:
    checker = UpdateChecker(current_version="3.1.1")
    with patch("httpx.get") as mock_get:
        mock_get.return_value = _fake_response({"tag_name": "v3.1.2"})
        checker.check()
        assert mock_get.call_count == 1
        # 切换仓库后应触发一次新请求
        checker.update_repository("other-owner", "other-repo")
        checker.check()
        assert mock_get.call_count == 2
        assert checker.repository_url == "https://github.com/other-owner/other-repo"
