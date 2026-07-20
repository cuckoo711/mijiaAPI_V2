"""FastAPI application factory for the Mijia API Server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import mijiaAPI_V2
from server.admin_session_cookie import ADMIN_SESSION_COOKIE_NAME, optional_bearer_token
from server.config import ServerSettings
from server.mijia_runtime import LoginJobManager, MijiaRuntime, SyncInProgressError
from server.routers import admin_auth, admin_mijia, admin_resources, api_v1
from server.store import AuthenticationFailedError, ServerStore
from server.updater import UpdateChecker

DEFAULT_TRUSTED_PROXY_CIDRS = ("127.0.0.1/32", "::1/128")
DOCS_ROUTES = {"/docs", "/redoc", "/docs/oauth2-redirect"}
OPENAPI_JSON_ROUTE = "/api/v1/openapi.json"


class ErrorEnvelope(BaseModel):
    """Standard API error envelope."""

    error: dict[str, Any]


def _json_error(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": request_id,
            }
        },
    )


def _config_bool(config: dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _config_string_list(
    config: dict[str, Any],
    key: str,
    default: tuple[str, ...] = (),
) -> list[str]:
    value = config.get(key, default)
    if isinstance(value, str):
        items = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value]
    else:
        items = list(default)
    return [item.strip() for item in items if item.strip()]


def _parse_ip(host: str) -> Any:
    value = host.strip()
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and value.rsplit(":", 1)[1].isdigit():
        value = value.rsplit(":", 1)[0]
    try:
        return ip_address(value)
    except ValueError:
        return None


def _host_in_cidrs(host: str, cidrs: list[str]) -> bool:
    address = _parse_ip(host)
    if address is None:
        return False
    for cidr in cidrs:
        try:
            network = ip_network(cidr, strict=False)
        except ValueError:
            continue
        if address.version == network.version and address in network:
            return True
    return False


def _forwarded_client_host(request: Request) -> str:
    x_forwarded_for = request.headers.get("X-Forwarded-For", "")
    if x_forwarded_for:
        forwarded_host = x_forwarded_for.split(",", 1)[0].strip()
        if _parse_ip(forwarded_host) is not None:
            return forwarded_host
    x_real_ip = request.headers.get("X-Real-IP", "").strip()
    if x_real_ip and _parse_ip(x_real_ip) is not None:
        return x_real_ip
    return ""


def _request_source_host(request: Request, config: dict[str, Any]) -> str:
    direct_host = request.client.host if request.client else ""
    if not _config_bool(config, "TRUST_PROXY_HEADERS", default=False):
        return direct_host
    trusted_cidrs = _config_string_list(
        config,
        "TRUSTED_PROXY_CIDRS",
        DEFAULT_TRUSTED_PROXY_CIDRS,
    )
    if not _host_in_cidrs(direct_host, trusted_cidrs):
        return direct_host
    return _forwarded_client_host(request) or direct_host


def _request_network_allowed(host: str, config: dict[str, Any]) -> bool:
    if not host:
        return True
    address = _parse_ip(host)
    if address is None:
        return True
    if address.is_loopback:
        return True
    if address.is_private or address.is_link_local:
        return _config_bool(config, "ALLOW_LAN_ACCESS")
    return _config_bool(config, "ALLOW_PUBLIC_ACCESS")


def _network_policy_required(path: str) -> bool:
    """Apply source-IP policy to the whole surface (admin, docs, SPA, API)."""

    return True


def _docs_route_disabled(path: str, config: dict[str, Any]) -> bool:
    normalized_path = path.rstrip("/") or "/"
    docs_enabled = _config_bool(config, "DOCS_ENABLED")
    openapi_enabled = _config_bool(config, "OPENAPI_ENABLED")
    if normalized_path in DOCS_ROUTES:
        return not docs_enabled
    if normalized_path == OPENAPI_JSON_ROUTE:
        return not (docs_enabled or openapi_enabled)
    return False


def _is_docs_or_openapi_path(path: str) -> bool:
    normalized_path = path.rstrip("/") or "/"
    return normalized_path in DOCS_ROUTES or normalized_path == OPENAPI_JSON_ROUTE


def _request_has_docs_access(request: Request, store: ServerStore) -> bool:
    """Allow docs/OpenAPI only with a valid admin session or API key."""

    bearer = optional_bearer_token(request.headers.get("Authorization"))
    if bearer:
        try:
            store.validate_admin_session(bearer)
            return True
        except AuthenticationFailedError:
            pass
        try:
            store.validate_api_key(bearer)
            return True
        except AuthenticationFailedError:
            pass

    cookie = (request.cookies.get(ADMIN_SESSION_COOKIE_NAME) or "").strip()
    if cookie:
        try:
            store.validate_admin_session(cookie)
            return True
        except AuthenticationFailedError:
            pass
    return False


def create_app(  # noqa: C901
    settings: Optional[ServerSettings] = None,
    store: Optional[ServerStore] = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    resolved_settings = settings or ServerSettings.from_env()
    resolved_settings.ensure_directories()
    resolved_settings.apply_log_level()
    resolved_store = store or ServerStore(resolved_settings)
    resolved_store.initialize()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        runtime: MijiaRuntime = app.state.runtime
        runtime.start_credential_refresh_timer()

        # 监控 configs/server.toml：仅日志级别可以安全热更新，host/port/存储路径
        # 等字段已经用于监听端口和已打开的数据库连接，修改后必须重启进程。
        from server.config_watcher import ConfigWatcher

        config_file = resolved_settings.config_file_path
        if config_file.exists():
            watcher = ConfigWatcher(
                config_file,
                callback=lambda path: _on_config_changed(path, app),
                interval=10,
            )
            watcher.start()
            app.state.config_watcher = watcher

        try:
            yield
        finally:
            runtime.stop_credential_refresh_timer()
            if hasattr(app.state, "config_watcher"):
                app.state.config_watcher.stop()

    app = FastAPI(
        title="Mijia API Server",
        version=mijiaAPI_V2.__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=OPENAPI_JSON_ROUTE,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.store = resolved_store
    app.state.runtime = MijiaRuntime(resolved_settings, resolved_store)
    app.state.login_jobs = LoginJobManager(resolved_settings)
    app.state.started_at = datetime.now(timezone.utc)
    app.state.update_checker = UpdateChecker(current_version=mijiaAPI_V2.__version__)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return _json_error(
                exc.status_code,
                str(exc.detail["code"]),
                str(exc.detail["message"]),
                request_id,
            )
        return _json_error(exc.status_code, "HTTP_ERROR", str(exc.detail), request_id)

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        return _json_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc), request_id)

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        return _json_error(status.HTTP_403_FORBIDDEN, "FORBIDDEN", str(exc), request_id)

    @app.exception_handler(SyncInProgressError)
    async def sync_in_progress_error_handler(
        request: Request, exc: SyncInProgressError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        return _json_error(
            status.HTTP_409_CONFLICT,
            "SYNC_IN_PROGRESS",
            str(exc),
            request_id,
        )

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        return _json_error(status.HTTP_400_BAD_REQUEST, "RUNTIME_ERROR", str(exc), request_id)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-ID") or f"req_{id(request)}"
        setattr(request.state, "request_id", request_id)
        config_map = resolved_store.get_config_map()
        source_host = _request_source_host(request, config_map)
        setattr(request.state, "source_ip", source_host)
        if _docs_route_disabled(request.url.path, config_map):
            return _json_error(
                status.HTTP_404_NOT_FOUND,
                "NOT_FOUND",
                "API documentation is disabled",
                request_id,
            )
        if _network_policy_required(request.url.path) and not _request_network_allowed(
            source_host, config_map
        ):
            return _json_error(
                status.HTTP_403_FORBIDDEN,
                "NETWORK_ACCESS_DENIED",
                "当前访问来源未被允许，请在系统安全中开启局域网或公网访问",
                request_id,
            )
        if _is_docs_or_openapi_path(request.url.path):
            if not _request_has_docs_access(request, resolved_store):
                return _json_error(
                    status.HTTP_401_UNAUTHORIZED,
                    "DOCS_AUTH_REQUIRED",
                    "查看 API 文档需要管理员会话或有效 API Key",
                    request_id,
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'",
        )
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "version": mijiaAPI_V2.__version__}

    app.include_router(admin_auth.router)
    app.include_router(admin_mijia.router)
    app.include_router(admin_resources.router)
    app.include_router(api_v1.router)

    _mount_frontend(app, resolved_settings.web_dist_dir)

    return app


def _on_config_changed(path: Path, app: FastAPI) -> None:
    """配置文件变化回调。

    只有日志级别可以安全地热更新；``host``/``port``/存储路径等字段已经用于
    已监听的端口和已打开的数据库连接，这里只提醒需要重启，不做任何处理。
    """
    settings: ServerSettings = app.state.settings
    restart_required, log_level_changed = settings.reload_from_toml(path)

    if log_level_changed:
        print(f"配置文件已更新: {path}（日志级别已热更新为 {settings.log_level}）")
    else:
        print(f"配置文件已更新: {path}")

    if restart_required:
        print(
            "以下配置项已在 "
            f"{path} 中修改，但需要重启服务才能生效: {', '.join(restart_required)}"
        )


def _mount_frontend(app: FastAPI, web_dist_dir: Path) -> None:
    """Serve the built web application when it is available."""

    index_html = web_dist_dir / "index.html"
    assets_dir = web_dist_dir / "assets"

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    if index_html.exists():

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            return FileResponse(index_html)

    else:

        @app.get("/", include_in_schema=False)
        def frontend_placeholder() -> dict[str, str]:
            return {
                "name": "mijia-api-server",
                "message": "Web assets are not built yet",
            }
