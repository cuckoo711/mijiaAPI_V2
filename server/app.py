"""FastAPI application factory for the Mijia API Server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import mijiaAPI_V2
from server.config import ServerSettings
from server.mijia_runtime import LoginJobManager, MijiaRuntime, SyncInProgressError
from server.store import (
    AuthenticationFailedError,
    AdminNotFoundError,
    BootstrapAlreadyCompletedError,
    InvalidCurrentPasswordError,
    ServerStore,
)
from server.updater import UpdateChecker

DEFAULT_TRUSTED_PROXY_CIDRS = ("127.0.0.1/32", "::1/128")
DOCS_ROUTES = {"/docs", "/redoc", "/docs/oauth2-redirect"}
OPENAPI_JSON_ROUTE = "/api/v1/openapi.json"


class ErrorEnvelope(BaseModel):
    """Standard API error envelope."""

    error: dict[str, Any]


class BootstrapStateResponse(BaseModel):
    """Current bootstrap state."""

    initialized: bool
    status: str
    version: str


class CreateAdminRequest(BaseModel):
    """Create the initial administrator."""

    username: str = Field(default="admin", min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    """Administrator login payload."""

    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    """Change the current administrator password."""

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class CreateApiKeyRequest(BaseModel):
    """Create a scoped API key."""

    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["read:status"])
    resource_policy: dict[str, Any] = Field(default_factory=dict)
    expires_at: Optional[datetime] = None


class SetApiKeyStatusRequest(BaseModel):
    """Enable or disable an API key."""

    is_active: bool


class SetConfigRequest(BaseModel):
    """Set a runtime configuration value."""

    value: Any
    source: str = "database"


class UpdateDeviceRequest(BaseModel):
    """Update local device metadata."""

    slug: Optional[str] = None
    alias: Optional[str] = None
    tags: Optional[list[str]] = None
    group_name: Optional[str] = None
    hidden: Optional[bool] = None
    access_mode: Optional[str] = None


class UpdateSceneRequest(BaseModel):
    """Update local scene metadata."""

    hidden: Optional[bool] = None
    executable: Optional[bool] = None


class SetPropertyRequest(BaseModel):
    """Set a MiOT property."""

    siid: int
    piid: int
    value: Any


class CallActionRequest(BaseModel):
    """Call a MiOT action."""

    siid: int
    aiid: int
    params: dict[str, Any] = Field(default_factory=dict)


class BatchPropertyRequest(BaseModel):
    """Batch set properties."""

    items: list[dict[str, Any]]


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return authorization.removeprefix("Bearer ").strip()


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


def _resource_allowed(api_key: dict[str, Any], kind: str, resource: dict[str, Any]) -> bool:
    policy = api_key.get("resource_policy") or {}
    allowed = policy.get(kind) or []
    if not allowed:
        return True
    candidates = {
        str(resource.get("id", "")),
        str(resource.get("slug", "")),
        str(resource.get("did", "")),
        str(resource.get("scene_id", "")),
        str(resource.get("home_id", "")),
    }
    return any(str(item) in candidates for item in allowed)


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
    if not _config_bool(config, "TRUST_PROXY_HEADERS", default=True):
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
    if path == OPENAPI_JSON_ROUTE:
        return False
    return path == "/healthz" or path == "/api/v1" or path.startswith("/api/v1/")


def _docs_route_disabled(path: str, config: dict[str, Any]) -> bool:
    normalized_path = path.rstrip("/") or "/"
    docs_enabled = _config_bool(config, "DOCS_ENABLED")
    openapi_enabled = _config_bool(config, "OPENAPI_ENABLED")
    if normalized_path in DOCS_ROUTES:
        return not docs_enabled
    if normalized_path == OPENAPI_JSON_ROUTE:
        return not (docs_enabled or openapi_enabled)
    return False


def create_app(  # noqa: C901
    settings: Optional[ServerSettings] = None,
    store: Optional[ServerStore] = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    resolved_settings = settings or ServerSettings.from_env()
    resolved_settings.ensure_directories()
    resolved_store = store or ServerStore(resolved_settings)
    resolved_store.initialize()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        runtime: MijiaRuntime = app.state.runtime
        runtime.start_credential_refresh_timer()

        # 启动配置文件监控
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
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    def get_store() -> ServerStore:
        return app.state.store

    def get_runtime() -> MijiaRuntime:
        return app.state.runtime

    def get_login_jobs() -> LoginJobManager:
        return app.state.login_jobs

    def get_started_at() -> datetime:
        return app.state.started_at

    def require_admin(
        authorization: Annotated[Optional[str], Header()] = None,
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        token = _extract_bearer_token(authorization)
        try:
            return current_store.validate_admin_session(token)
        except AuthenticationFailedError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "ADMIN_AUTH_FAILED", "message": str(exc)},
            ) from exc

    def require_api_key_scope(required_scope: str) -> Any:
        def dependency(
            request: Request,
            authorization: Annotated[Optional[str], Header()] = None,
            current_store: ServerStore = Depends(get_store),
        ) -> dict[str, Any]:
            key = _extract_bearer_token(authorization)
            try:
                return current_store.validate_api_key(
                    key,
                    required_scope=required_scope,
                    source_ip=getattr(request.state, "source_ip", None),
                )
            except AuthenticationFailedError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "API_KEY_FORBIDDEN", "message": str(exc)},
                ) from exc

        return dependency

    def require_status_api_key(
        request: Request,
        authorization: Annotated[Optional[str], Header()] = None,
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        key = _extract_bearer_token(authorization)
        try:
            return current_store.validate_api_key(
                key,
                required_scope="read:status",
                source_ip=getattr(request.state, "source_ip", None),
            )
        except AuthenticationFailedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "API_KEY_FORBIDDEN", "message": str(exc)},
            ) from exc

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "version": mijiaAPI_V2.__version__}

    @app.get("/api/admin/bootstrap/state", response_model=BootstrapStateResponse)
    def bootstrap_state(current_store: ServerStore = Depends(get_store)) -> dict[str, Any]:
        return {
            "initialized": current_store.has_admin(),
            "status": "ok",
            "version": mijiaAPI_V2.__version__,
        }

    @app.post("/api/admin/bootstrap/admin", status_code=status.HTTP_201_CREATED)
    def create_initial_admin(
        payload: CreateAdminRequest,
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            return current_store.create_initial_admin(payload.username, payload.password)
        except BootstrapAlreadyCompletedError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "BOOTSTRAP_ALREADY_COMPLETED", "message": str(exc)},
            ) from exc

    @app.post("/api/admin/auth/login")
    def admin_login(
        payload: LoginRequest,
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            return current_store.authenticate_admin(payload.username, payload.password)
        except AuthenticationFailedError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "ADMIN_AUTH_FAILED", "message": str(exc)},
            ) from exc

    @app.post("/api/admin/auth/refresh")
    def admin_refresh_session(
        authorization: Annotated[Optional[str], Header()] = None,
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        token = _extract_bearer_token(authorization)
        try:
            return current_store.refresh_admin_session(token)
        except AuthenticationFailedError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "ADMIN_AUTH_FAILED", "message": str(exc)},
            ) from exc

    @app.post("/api/admin/auth/change-password")
    def admin_change_password(
        payload: ChangePasswordRequest,
        authorization: Annotated[Optional[str], Header()] = None,
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        token = _extract_bearer_token(authorization)
        try:
            admin = current_store.validate_admin_session(token)
            result = current_store.change_admin_password(
                admin["id"],
                payload.current_password,
                payload.new_password,
                keep_session_token=token,
            )
        except InvalidCurrentPasswordError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "CURRENT_PASSWORD_INVALID", "message": str(exc)},
            ) from exc
        except AuthenticationFailedError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "ADMIN_AUTH_FAILED", "message": str(exc)},
            ) from exc
        except AdminNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ADMIN_NOT_FOUND", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "PASSWORD_CHANGE_REJECTED", "message": str(exc)},
            ) from exc

        current_store.add_audit(
            "admin.password.change",
            "success",
            actor_type="admin",
            actor_id=admin["id"],
        )
        return result

    @app.get("/api/admin/system/check")
    def admin_system_check(
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        checks = current_store.system_checks()
        return {"checks": checks}

    @app.get("/api/admin/app-info")
    def admin_app_info(
        _admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        checker: UpdateChecker = app.state.update_checker
        return {
            "name": "米家 API Server",
            "version": mijiaAPI_V2.__version__,
            "description": "米家智能家居 Python SDK 与管理台",
            "license": "MIT",
            "authors": "MijiaAPI Contributors",
            "repository_url": checker.repository_url,
            "issues_url": f"{checker.repository_url}/issues",
            "releases_url": f"{checker.repository_url}/releases",
        }

    @app.get("/api/admin/updates/check")
    def admin_updates_check(
        force: bool = False,
        _admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        checker: UpdateChecker = app.state.update_checker
        return checker.check(force=force)

    @app.get("/api/admin/config")
    def admin_list_config(
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {"items": current_store.list_config()}

    @app.put("/api/admin/config/{key}")
    def admin_set_config(
        key: str,
        payload: SetConfigRequest,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return current_store.set_config(key, payload.value, payload.source)

    @app.post("/api/admin/api-keys", status_code=status.HTTP_201_CREATED)
    def create_api_key(
        payload: CreateApiKeyRequest,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return current_store.create_api_key(
            name=payload.name,
            scopes=payload.scopes,
            resource_policy=payload.resource_policy,
            expires_at=payload.expires_at,
        )

    @app.get("/api/admin/api-keys")
    def list_api_keys(
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {"items": current_store.list_api_keys()}

    @app.patch("/api/admin/api-keys/{key_id}")
    def update_api_key_status(
        key_id: str,
        payload: SetApiKeyStatusRequest,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return current_store.update_api_key_status(key_id, payload.is_active)

    @app.delete("/api/admin/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_api_key(
        key_id: str,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> None:
        current_store.delete_api_key(key_id)

    @app.get("/api/admin/mijia/account")
    def admin_mijia_account(
        _admin: dict[str, Any] = Depends(require_admin),
        runtime: MijiaRuntime = Depends(get_runtime),
    ) -> dict[str, Any]:
        return runtime.credential_status()

    @app.post("/api/admin/mijia/login/start", status_code=status.HTTP_201_CREATED)
    def admin_start_mijia_login(
        _admin: dict[str, Any] = Depends(require_admin),
        jobs: LoginJobManager = Depends(get_login_jobs),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        job = jobs.start()
        current_store.add_audit("mijia.login.start", "success", actor_type="admin")
        return job

    @app.get("/api/admin/mijia/login/{job_id}")
    def admin_get_mijia_login(
        job_id: str,
        _admin: dict[str, Any] = Depends(require_admin),
        jobs: LoginJobManager = Depends(get_login_jobs),
    ) -> dict[str, Any]:
        return jobs.get(job_id)

    @app.post("/api/admin/mijia/credential/refresh")
    def admin_refresh_credential(
        _admin: dict[str, Any] = Depends(require_admin),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = runtime.refresh_credential()
        current_store.add_audit("mijia.credential.refresh", "success", actor_type="admin")
        return result

    @app.delete("/api/admin/mijia/credential", status_code=status.HTTP_204_NO_CONTENT)
    def admin_delete_credential(
        _admin: dict[str, Any] = Depends(require_admin),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> None:
        result = runtime.delete_credential()
        current_store.add_audit(
            "mijia.credential.delete",
            "success",
            actor_type="admin",
            metadata=result,
        )

    @app.post("/api/admin/sync")
    def admin_sync(
        _admin: dict[str, Any] = Depends(require_admin),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = runtime.sync_all()
        current_store.add_audit("mijia.sync.start", "success", actor_type="admin")
        return result

    @app.get("/api/admin/sync/progress")
    def admin_sync_progress(
        _admin: dict[str, Any] = Depends(require_admin),
        runtime: MijiaRuntime = Depends(get_runtime),
    ) -> dict[str, Any]:
        progress = runtime.get_sync_progress()
        if progress is None:
            return {"status": "idle"}
        return progress

    @app.get("/api/admin/homes")
    def admin_homes(
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {"items": current_store.list_homes()}

    @app.get("/api/admin/devices")
    def admin_devices(
        include_hidden: bool = False,
        include_spec: bool = False,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {
            "items": current_store.list_devices(
                include_hidden=include_hidden, include_spec=include_spec
            )
        }

    @app.patch("/api/admin/devices/{device_id}")
    def admin_update_device(
        device_id: str,
        payload: UpdateDeviceRequest,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return current_store.update_device(
            device_id,
            payload.model_dump(exclude_unset=True),
        )

    @app.get("/api/admin/scenes")
    def admin_scenes(
        include_hidden: bool = False,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {"items": current_store.list_scenes(include_hidden=include_hidden)}

    @app.patch("/api/admin/scenes/{scene_id}")
    def admin_update_scene(
        scene_id: str,
        payload: UpdateSceneRequest,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return current_store.update_scene(scene_id, payload.model_dump(exclude_unset=True))

    @app.get("/api/admin/audit")
    def admin_audit(
        limit: int = Query(default=100, ge=1, le=500),
        action: Optional[str] = None,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {"items": current_store.list_audit(limit=limit, action=action)}

    @app.post("/api/admin/cache/clear")
    def admin_clear_cache(
        namespace: Optional[str] = None,
        _admin: dict[str, Any] = Depends(require_admin),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        deleted = current_store.clear_cache(namespace=namespace)
        return {"deleted": deleted}

    @app.get("/api/v1/status")
    def api_status(
        _api_key: dict[str, Any] = Depends(require_status_api_key),
        started_at: datetime = Depends(get_started_at),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "name": "mijia-api-server",
            "version": mijiaAPI_V2.__version__,
            "started_at": started_at.isoformat(),
            "uptime_seconds": int((now - started_at).total_seconds()),
            "initialized": current_store.has_admin(),
        }

    @app.get("/api/v1/account")
    def api_account(
        _api_key: dict[str, Any] = Depends(require_api_key_scope("read:status")),
        runtime: MijiaRuntime = Depends(get_runtime),
    ) -> dict[str, Any]:
        return runtime.credential_status()

    @app.get("/api/v1/homes")
    def api_homes(
        api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        homes = current_store.list_homes()
        return {"items": [home for home in homes if _resource_allowed(api_key, "homes", home)]}

    @app.get("/api/v1/devices")
    def api_devices(
        include_spec: bool = False,
        api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        devices = current_store.list_devices(include_spec=include_spec)
        return {
            "items": [device for device in devices if _resource_allowed(api_key, "devices", device)]
        }

    @app.get("/api/v1/devices/{device_slug}")
    def api_device(
        device_slug: str,
        api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        device = current_store.get_device(device_slug)
        if not _resource_allowed(api_key, "devices", device):
            raise PermissionError("API key cannot access this device")
        return device

    @app.get("/api/v1/devices/{device_slug}/state")
    def api_device_state(
        device_slug: str,
        api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        device = current_store.get_device(device_slug)
        if not _resource_allowed(api_key, "devices", device):
            raise PermissionError("API key cannot access this device")
        return {"items": runtime.get_device_state(device_slug)}

    @app.get("/api/v1/devices/{device_slug}/spec")
    def api_device_spec(
        device_slug: str,
        api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        device = current_store.get_device(device_slug)
        if not _resource_allowed(api_key, "devices", device):
            raise PermissionError("API key cannot access this device")
        return {"spec": runtime.get_device_spec(device_slug)}

    @app.post("/api/v1/devices/{device_slug}/properties")
    def api_set_device_property(
        device_slug: str,
        payload: SetPropertyRequest,
        api_key: dict[str, Any] = Depends(require_api_key_scope("write:devices")),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        device = current_store.get_device(device_slug)
        if not _resource_allowed(api_key, "devices", device):
            raise PermissionError("API key cannot access this device")
        result = runtime.set_device_property(device_slug, payload.siid, payload.piid, payload.value)
        current_store.add_audit(
            "device.property.set",
            "success",
            actor_type="api_key",
            actor_id=api_key["key_prefix"],
            metadata={"device": device_slug, "siid": payload.siid, "piid": payload.piid},
        )
        return result

    @app.post("/api/v1/devices/{device_slug}/actions")
    def api_call_device_action(
        device_slug: str,
        payload: CallActionRequest,
        api_key: dict[str, Any] = Depends(require_api_key_scope("write:devices")),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        device = current_store.get_device(device_slug)
        if not _resource_allowed(api_key, "devices", device):
            raise PermissionError("API key cannot access this device")
        result = runtime.call_device_action(device_slug, payload.siid, payload.aiid, payload.params)
        current_store.add_audit(
            "device.action.call",
            "success",
            actor_type="api_key",
            actor_id=api_key["key_prefix"],
            metadata={"device": device_slug, "siid": payload.siid, "aiid": payload.aiid},
        )
        return result

    @app.post("/api/v1/batch/devices/properties")
    def api_batch_set_properties(
        payload: BatchPropertyRequest,
        api_key: dict[str, Any] = Depends(require_api_key_scope("write:devices")),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        for item in payload.items:
            device = current_store.get_device(str(item["device"]))
            if not _resource_allowed(api_key, "devices", device):
                raise PermissionError("API key cannot access one or more devices")
        result = runtime.batch_set_properties(payload.items)
        current_store.add_audit(
            "device.property.batch_set",
            "success",
            actor_type="api_key",
            actor_id=api_key["key_prefix"],
            metadata={"count": len(payload.items)},
        )
        return result

    @app.get("/api/v1/scenes")
    def api_scenes(
        api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        scenes = current_store.list_scenes()
        return {"items": [scene for scene in scenes if _resource_allowed(api_key, "scenes", scene)]}

    @app.post("/api/v1/scenes/{scene_id}/execute")
    def api_execute_scene(
        scene_id: str,
        api_key: dict[str, Any] = Depends(require_api_key_scope("write:scenes")),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        scene = current_store.get_scene(scene_id)
        if not _resource_allowed(api_key, "scenes", scene):
            raise PermissionError("API key cannot access this scene")
        result = runtime.execute_scene(scene_id)
        current_store.add_audit(
            "scene.execute",
            "success",
            actor_type="api_key",
            actor_id=api_key["key_prefix"],
            metadata={"scene": scene_id},
        )
        return result

    @app.post("/api/v1/cache/refresh")
    def api_refresh_cache(
        home_id: Optional[str] = None,
        _api_key: dict[str, Any] = Depends(require_api_key_scope("manage:cache")),
        runtime: MijiaRuntime = Depends(get_runtime),
    ) -> dict[str, Any]:
        runtime.refresh_cache(home_id=home_id)
        return {"success": True}

    @app.post("/api/v1/cache/clear")
    def api_clear_cache(
        _api_key: dict[str, Any] = Depends(require_api_key_scope("manage:cache")),
        runtime: MijiaRuntime = Depends(get_runtime),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        runtime.clear_sdk_cache()
        deleted = current_store.clear_cache()
        return {"success": True, "deleted": deleted}

    @app.get("/api/v1/logs")
    def api_logs(
        limit: int = Query(default=100, ge=1, le=500),
        _api_key: dict[str, Any] = Depends(require_api_key_scope("read:logs")),
        current_store: ServerStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {"items": current_store.list_audit(limit=limit)}

    _mount_frontend(app, resolved_settings.web_dist_dir)

    return app


def _on_config_changed(path: Path, app: FastAPI) -> None:
    """配置文件变化回调"""
    print(f"配置文件已更新: {path}")


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
