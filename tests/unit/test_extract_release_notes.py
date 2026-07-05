"""scripts/extract_release_notes.py 的单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

# 让脚本包路径可 import
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from extract_release_notes import extract_notes  # noqa: E402


SAMPLE_CHANGELOG = """\
# 更新日志

前言

## v3.2.2 - 2026-07-06

### 修复

- 修复 A
- 修复 B

### 内部改动

- 内部 X

## v3.2.1 - 2026-07-05

### 修复

- 老版本内容

## 2026-05-23

### 变更

- 无版本前缀的旧段落
"""


def test_extract_notes_with_v_prefix() -> None:
    body = extract_notes(SAMPLE_CHANGELOG, "v3.2.2")
    assert body is not None
    assert "修复 A" in body
    assert "内部 X" in body
    # 不应包含下一个版本的内容
    assert "老版本内容" not in body


def test_extract_notes_without_v_prefix() -> None:
    body = extract_notes(SAMPLE_CHANGELOG, "3.2.2")
    assert body is not None
    assert "修复 A" in body


def test_extract_notes_returns_none_for_missing_version() -> None:
    assert extract_notes(SAMPLE_CHANGELOG, "v9.9.9") is None


def test_extract_notes_isolates_target_section() -> None:
    body = extract_notes(SAMPLE_CHANGELOG, "v3.2.1")
    assert body is not None
    assert "老版本内容" in body
    # 不应"越过"到 2026-05-23 段落
    assert "无版本前缀的旧段落" not in body


def test_extract_notes_handles_heading_without_date() -> None:
    changelog = "## v3.2.2\n\n- 简短说明\n\n## v3.2.1\n\n- 旧内容\n"
    body = extract_notes(changelog, "v3.2.2")
    assert body is not None
    assert body.strip() == "- 简短说明"


def test_extract_notes_returns_last_section_when_no_next() -> None:
    changelog = "## v3.2.2\n\n- 最后一段\n"
    body = extract_notes(changelog, "v3.2.2")
    assert body == "- 最后一段"
