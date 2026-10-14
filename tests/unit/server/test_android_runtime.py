"""Android storage and restart semantics must not invoke desktop migrations."""

import importlib.util
from pathlib import Path


def load_runtime():
    path = (
        Path(__file__).resolve().parents[3] / "android/app/src/main/python/mijia_android/runtime.py"
    )
    spec = importlib.util.spec_from_file_location("android_runtime_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_android_settings_keep_mutable_data_under_private_root(tmp_path, monkeypatch):
    from server.config import ServerSettings

    def reject_migration(*args, **kwargs):
        raise AssertionError("Android must not use desktop environment discovery")

    monkeypatch.setattr(ServerSettings, "from_env", reject_migration)
    runtime = load_runtime()
    settings = runtime.settings_for(tmp_path / "private")
    assert settings.host == "127.0.0.1"
    assert settings.database_path.is_relative_to(settings.data_dir)
    assert settings.credential_path == settings.data_dir / "credential.json"
    assert settings.config_file_path == settings.data_dir / "server.toml"
    assert not settings.web_dist_dir.is_relative_to(settings.data_dir)
    assert runtime.settings_for(tmp_path / "private", True).host == "0.0.0.0"


def test_android_stop_before_start_can_be_reset_for_a_new_service():
    runtime = load_runtime()
    runtime.stop()
    assert runtime._stop_requested
    runtime.prepare()
    assert not runtime._stop_requested
