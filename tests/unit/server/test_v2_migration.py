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


def test_migrate_removes_orphaned_server_cache_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    new = tmp_path / "configs"
    (new / "cache").mkdir(parents=True)
    (new / "server" / "cache").mkdir(parents=True)
    (new / "cache" / "keep").write_text("1", encoding="utf-8")
    (new / "server" / "cache" / "dup").write_text("2", encoding="utf-8")

    ServerSettings._migrate_v2_to_v3_if_needed()

    assert (new / "cache" / "keep").exists()
    assert not (new / "server" / "cache").exists()


def test_migrate_removes_orphaned_server_cache_without_canonical_dir(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The orphan must go even when ``configs/cache`` has not been created yet.

    ``CacheManager`` creates the canonical directory lazily, so a fresh install
    that never instantiated it would otherwise keep ``configs/server/cache``
    around forever.
    """
    monkeypatch.chdir(tmp_path)
    new = tmp_path / "configs"
    (new / "server" / "cache").mkdir(parents=True)
    (new / "server" / "cache" / "stale").write_text("x", encoding="utf-8")
    (new / "server" / "server.sqlite3").write_text("live", encoding="utf-8")

    ServerSettings._migrate_v2_to_v3_if_needed()

    assert not (new / "cache").exists(), "迁移不应凭空创建规范缓存目录"
    assert not (new / "server" / "cache").exists()
    # The sibling database must never be touched by cache cleanup.
    assert (new / "server" / "server.sqlite3").read_text(encoding="utf-8") == "live"
    assert "已删除无用缓存目录" in capsys.readouterr().out

    # Idempotent: the orphan is gone, so the second call stays silent.
    ServerSettings._migrate_v2_to_v3_if_needed()
    assert capsys.readouterr().out == ""


def test_ensure_directories_removes_orphaned_cache_under_custom_data_dir(
    tmp_path: Path, capsys
) -> None:
    """复现 Docker 布局：data_dir 不在仓库内，相对路径的迁移逻辑够不到。

    容器里 WORKDIR 是 /app 而数据在 /data，所以孤儿缓存只能靠
    ``ensure_directories`` 按已解析的 data_dir 清理。
    """
    data_dir = tmp_path / "data"
    orphaned = data_dir / "server" / "cache"
    orphaned.mkdir(parents=True)
    (orphaned / "stale").write_text("x", encoding="utf-8")
    (data_dir / "server" / "server.sqlite3").write_text("live", encoding="utf-8")

    settings = ServerSettings(
        data_dir=data_dir,
        database_path=data_dir / "server" / "server.sqlite3",
        credential_path=data_dir / "credential.json",
    )
    settings.ensure_directories()

    assert not orphaned.exists()
    # 同级数据库必须完好无损。
    assert (data_dir / "server" / "server.sqlite3").read_text(encoding="utf-8") == "live"
    assert "已删除无用缓存目录" in capsys.readouterr().out

    # 幂等：孤儿已清掉，再调用不应再输出。
    settings.ensure_directories()
    assert capsys.readouterr().out == ""
