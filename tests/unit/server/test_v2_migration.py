"""Tests for the one-shot v2 → v3 data-directory migration."""

from __future__ import annotations

from pathlib import Path

from server.config import ServerSettings


def test_migrate_moves_legacy_mijia_tree(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    old = tmp_path / ".mijia"
    (old / "server").mkdir(parents=True)
    (old / "cache").mkdir()
    (old / "credential.json").write_text("{}", encoding="utf-8")
    (old / "server" / "server.sqlite3").write_text("db", encoding="utf-8")
    (old / "cache" / "a").write_text("c", encoding="utf-8")

    ServerSettings._migrate_v2_to_v3_if_needed()

    assert not old.exists()
    assert (tmp_path / "configs" / "credential.json").read_text(encoding="utf-8") == "{}"
    assert (tmp_path / "configs" / "server" / "server.sqlite3").exists()
    assert (tmp_path / "configs" / "cache" / "a").exists()
    out = capsys.readouterr().out
    assert "迁移到 v3.0" in out
    assert "迁移完成" in out


def test_migrate_is_silent_and_clears_leftover_when_already_done(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    # New layout already present
    new = tmp_path / "configs"
    (new / "server").mkdir(parents=True)
    (new / "cache").mkdir()
    (new / "credential.json").write_text('{"ok":1}', encoding="utf-8")
    (new / "server" / "server.sqlite3").write_text("live", encoding="utf-8")

    # Leftover old tree that previously blocked rename (plus empty backup dir)
    old = tmp_path / ".mijia"
    (old / "server").mkdir(parents=True)
    (old / "server" / "server.sqlite3").write_text("stale", encoding="utf-8")
    (tmp_path / ".mijia_backup").mkdir()

    ServerSettings._migrate_v2_to_v3_if_needed()

    assert not old.exists()
    assert (new / "server" / "server.sqlite3").read_text(encoding="utf-8") == "live"
    assert "迁移到 v3.0" not in capsys.readouterr().out

    # Second call: nothing left to do, still silent
    ServerSettings._migrate_v2_to_v3_if_needed()
    assert "迁移到 v3.0" not in capsys.readouterr().out


def test_migrate_removes_orphaned_server_cache_dir(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    new = tmp_path / "configs"
    (new / "cache").mkdir(parents=True)
    (new / "server" / "cache").mkdir(parents=True)
    (new / "cache" / "keep").write_text("1", encoding="utf-8")
    (new / "server" / "cache" / "dup").write_text("2", encoding="utf-8")

    ServerSettings._migrate_v2_to_v3_if_needed()

    assert (new / "cache" / "keep").exists()
    assert not (new / "server" / "cache").exists()
