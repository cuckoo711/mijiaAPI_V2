"""Configuration template behavior outside a packaged server's source tree."""

import argparse
import shutil
import sys
from pathlib import Path

import pytest

from server.cli import write_config_command
from server.config import ServerSettings


@pytest.fixture
def packaged_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    (bundle / "configs").mkdir(parents=True)
    source_template = Path(__file__).resolve().parents[3] / "configs" / "server.toml.template"
    shutil.copyfile(source_template, bundle / "configs" / "server.toml.template")
    work_dir = tmp_path / "working-directory"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.delenv("MIJIA_WEB_DIST_DIR", raising=False)
    return bundle, work_dir


def test_packaged_write_config_uses_bundled_template(
    packaged_layout: tuple[Path, Path],
) -> None:
    bundle, work_dir = packaged_layout
    template = bundle / "configs" / "server.toml.template"
    assert ServerSettings().config_template_path == template
    assert ServerSettings.from_env().config_template_path == template

    output = work_dir / "generated" / "server.toml"
    write_config_command(argparse.Namespace(output=output, force=False))

    assert output.read_text(encoding="utf-8") == template.read_text(encoding="utf-8")


def test_packaged_defaults_do_not_copy_template_or_override_bundled_frontend(
    packaged_layout: tuple[Path, Path],
) -> None:
    bundle, work_dir = packaged_layout
    settings = ServerSettings.from_env()
    settings.ensure_config_file()

    assert settings.web_dist_dir == bundle / "web" / "dist"
    assert not (work_dir / "configs" / "server.toml").exists()


def test_exported_default_config_keeps_bundled_frontend(
    packaged_layout: tuple[Path, Path],
) -> None:
    bundle, work_dir = packaged_layout
    write_config_command(argparse.Namespace(output=None, force=False))

    assert (work_dir / "configs" / "server.toml").is_file()
    assert ServerSettings.from_env().web_dist_dir == bundle / "web" / "dist"


def test_local_template_takes_priority_and_keeps_default_creation(
    packaged_layout: tuple[Path, Path],
) -> None:
    _, work_dir = packaged_layout
    local_template = work_dir / "configs" / "server.toml.template"
    local_template.parent.mkdir()
    local_template.write_text('[server]\nport = 8124\n', encoding="utf-8")

    assert ServerSettings().config_template_path == Path("configs/server.toml.template")
    settings = ServerSettings.from_env()

    assert settings.config_template_path == Path("configs/server.toml.template")
    assert (work_dir / "configs" / "server.toml").read_text(encoding="utf-8") == (
        local_template.read_text(encoding="utf-8")
    )

    output = work_dir / "generated.toml"
    write_config_command(argparse.Namespace(output=output, force=False))
    assert output.read_text(encoding="utf-8") == local_template.read_text(encoding="utf-8")
