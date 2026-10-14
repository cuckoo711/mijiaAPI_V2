"""Run the actual server inside Android's app-private storage."""

import os
import hmac
from pathlib import Path
import threading

_lock = threading.Lock()
_server = None
_stop_requested = False
_owner_token = None


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


def create_android_app(settings, store, owner_token):
    from fastapi.responses import JSONResponse
    from server.app import create_app

    if not owner_token or len(owner_token) < 32:
        raise ValueError("A private Android initialization token is required")
    app = create_app(settings, store=store)

    @app.middleware("http")
    async def protect_initialization(request, call_next):
        if request.method == "POST" and request.url.path == "/api/admin/bootstrap/admin":
            supplied = request.cookies.get("mijia_android_owner", "")
            if not hmac.compare_digest(supplied.encode("utf-8"), owner_token.encode("ascii")):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "ANDROID_INITIALIZATION_REQUIRED",
                            "message": "请从本机应用初始化管理员",
                        }
                    },
                )
        return await call_next(request)

    return app


def run(data_dir, lan, owner_token):
    global _server, _stop_requested, _owner_token
    # No desktop config discovery/migration: never write to the extracted APK.
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    os.environ["MIJIA_CREDENTIAL_PATH"] = str(root / "credential.json")
    os.environ["MIJIA_SERVER_DATA_DIR"] = str(root)
    import uvicorn
    from server.store import ServerStore

    settings = settings_for(root, bool(lan))
    store = ServerStore(settings)
    store.initialize()
    store.set_config("ALLOW_LAN_ACCESS", bool(lan), source="android")
    _owner_token = owner_token
    server = uvicorn.Server(
        uvicorn.Config(
            create_android_app(settings, store, owner_token),
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
