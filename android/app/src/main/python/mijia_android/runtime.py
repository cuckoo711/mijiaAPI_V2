"""Run the actual server inside Android's app-private storage."""

import os
from pathlib import Path
import threading

_lock = threading.Lock()
_server = None
_stop_requested = False


def prepare():
    global _stop_requested
    with _lock:
        if _server is not None:
            raise RuntimeError("Previous server is still stopping")
        _stop_requested = False


def settings_for(data_dir, lan=False):
    from server.config import ServerSettings

    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    bundle = Path(__file__).resolve().parent
    return ServerSettings(
        host="0.0.0.0" if lan else "127.0.0.1",
        port=8123,
        data_dir=root,
        database_path=root / "server/server.sqlite3",
        credential_path=root / "credential.json",
        config_file_path=root / "server.toml",
        config_template_path=bundle / "assets/server.toml.template",
        web_dist_dir=bundle / "ui",
    )


def run(data_dir, lan=False):
    global _server, _stop_requested
    # No desktop config discovery/migration: never write to the extracted APK.
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    os.environ["MIJIA_CREDENTIAL_PATH"] = str(root / "credential.json")
    os.environ["MIJIA_SERVER_DATA_DIR"] = str(root)
    import uvicorn
    from server.app import create_app
    from server.store import ServerStore

    settings = settings_for(root, bool(lan))
    store = ServerStore(settings)
    store.initialize()
    store.set_config("ALLOW_LAN_ACCESS", bool(lan), source="android")
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, store=store),
            host=settings.host,
            port=settings.port,
            loop="asyncio",
            http="h11",
            ws="none",
            proxy_headers=False,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=8,
        )
    )
    with _lock:
        _server = server
        server.should_exit = _stop_requested
    try:
        server.run()
    finally:
        with _lock:
            _server = None
            _stop_requested = False


def stop():
    global _stop_requested
    with _lock:
        _stop_requested = True
        if _server is not None:
            _server.should_exit = True
