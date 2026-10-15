"""deploy/scripts/publish_gitee_release.py 的单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "deploy" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from publish_gitee_release import expand_paths  # noqa: E402


def test_expand_paths_keeps_order_and_dedupes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.bin").write_bytes(b"a")
    (tmp_path / "b.bin").write_bytes(b"b")
    result = expand_paths(["a.bin", "b.bin", "a.bin"])
    assert [p.name for p in result] == ["a.bin", "b.bin"]


def test_expand_paths_supports_glob(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mijia-server-linux-x64").write_bytes(b"1")
    (tmp_path / "mijia-server-linux-arm64").write_bytes(b"2")
    (tmp_path / "other.txt").write_bytes(b"3")
    result = expand_paths(["mijia-server-*"])
    assert sorted(p.name for p in result) == [
        "mijia-server-linux-arm64",
        "mijia-server-linux-x64",
    ]


def test_expand_paths_keeps_missing_literal_for_clear_error(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = expand_paths(["does-not-exist.bin"])
    assert [p.name for p in result] == ["does-not-exist.bin"]
