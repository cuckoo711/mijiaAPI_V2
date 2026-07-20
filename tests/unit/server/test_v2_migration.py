"""Tests for the one-shot v2 → v3 data-directory migration."""

from __future__ import annotations

from pathlib import Path

from server.config import ServerSettings


def test_migrate_moves_legacy_mijia_tree_then_deletes_it(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    old = tmp_path / ".mijia"
    (old / "server").mkdir(parents=True)
    (old / "cache").mkdir()
    (old / "credential.json").write_text("{}", encoding="utf-8")
    (old / ".credential_key").write_text("k" * 32, encoding="utf-8")
    (old / "server" / "server.sqlite3").write_text("db", encoding="utf-8")
    (old / "cache" / "a").write_text("c", encoding="utf-8")
    (old / "extra_leftover.txt").write_text("x", encoding="utf-8")

    ServerSettings._migrate_v2_to_v3_if_needed()

    assert not old.exists()
    assert not list(tmp_path.glob(".mijia_backup*"))
    assert (tmp_path / "configs" / "credential.json").read_text(encoding="utf-8") == "{}"
    assert (tmp_path / "configs" / ".credential_key").exists()
    assert (tmp_path / "configs" / "server" / "server.sqlite3").exists()
    assert (tmp_path / "configs" / "cache" / "a").exists()
    out = capsys.readouterr().out
    assert "迁移到 configs/" in out
    assert "已删除旧目录" in out


def test_migrate_deletes_leftover_when_targets_already_exist(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    new = tmp_path / "configs"
    (new / "server").mkdir(parents=True)
    (new / "cache").mkdir()
    (new / "credential.json").write_text('{"ok":1}', encoding="utf-8")
    (new / "server" / "server.sqlite3").write_text("live", encoding="utf-8")

    old = tmp_path / ".mijia"
    (old / "server").mkdir(parents=True)
    (old / "server" / "server.sqlite3").write_text("stale", encoding="utf-8")
    (tmp_path / ".mijia_backup").mkdir()
    (tmp_path / ".mijia_backup_old").mkdir()

    ServerSettings._migrate_v2_to_v3_if_needed()

    assert not old.exists()
    assert not (tmp_path / ".mijia_backup").exists()
    assert not (tmp_path / ".mijia_backup_old").exists()
    assert (new / "server" / "server.sqlite3").read_text(encoding="utf-8") == "live"
    out = capsys.readouterr().out
    assert "已删除旧目录" in out

    # Second call: nothing left, silent
    ServerSettings._migrate_v2_to_v3_if_needed()
    assert "迁移到 configs/" not in capsys.readouterr().out


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
