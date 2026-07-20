"""Admin routes for homes/devices/scenes registry, config, api-keys and system info."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

import mijiaAPI_V2
from server.deps import get_store, get_update_checker, require_admin
from server.store import ServerStore
from server.updater import UpdateChecker

router = APIRouter(tags=["admin-resources"])


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


@router.get("/api/admin/system/check")
def admin_system_check(
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    checks = current_store.system_checks()
    return {"checks": checks}


@router.get("/api/admin/app-info")
def admin_app_info(
    _admin: dict[str, Any] = Depends(require_admin),
    checker: UpdateChecker = Depends(get_update_checker),
) -> dict[str, Any]:
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


@router.get("/api/admin/updates/check")
def admin_updates_check(
    force: bool = False,
    _admin: dict[str, Any] = Depends(require_admin),
    checker: UpdateChecker = Depends(get_update_checker),
) -> dict[str, Any]:
    return checker.check(force=force)


@router.get("/api/admin/config")
def admin_list_config(
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return {"items": current_store.list_config()}


@router.put("/api/admin/config/{key}")
def admin_set_config(
    key: str,
    payload: SetConfigRequest,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return current_store.set_config(key, payload.value, payload.source)


@router.post("/api/admin/api-keys", status_code=status.HTTP_201_CREATED)
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


@router.get("/api/admin/api-keys")
def list_api_keys(
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return {"items": current_store.list_api_keys()}


@router.patch("/api/admin/api-keys/{key_id}")
def update_api_key_status(
    key_id: str,
    payload: SetApiKeyStatusRequest,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return current_store.update_api_key_status(key_id, payload.is_active)


@router.delete("/api/admin/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    key_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> None:
    current_store.delete_api_key(key_id)


@router.get("/api/admin/homes")
def admin_homes(
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return {"items": current_store.list_homes()}


@router.get("/api/admin/devices")
def admin_devices(
    include_hidden: bool = False,
    include_spec: bool = False,
    include_raw: bool = False,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return {
        "items": current_store.list_devices(
            include_hidden=include_hidden,
            include_spec=include_spec,
            include_raw=include_raw,
        )
    }


@router.patch("/api/admin/devices/{device_id}")
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


@router.get("/api/admin/scenes")
def admin_scenes(
    include_hidden: bool = False,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return {"items": current_store.list_scenes(include_hidden=include_hidden)}


@router.patch("/api/admin/scenes/{scene_id}")
def admin_update_scene(
    scene_id: str,
    payload: UpdateSceneRequest,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return current_store.update_scene(scene_id, payload.model_dump(exclude_unset=True))


@router.get("/api/admin/audit")
def admin_audit(
    limit: int = Query(default=100, ge=1, le=500),
    action: Optional[str] = None,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return {"items": current_store.list_audit(limit=limit, action=action)}


@router.post("/api/admin/cache/clear")
def admin_clear_cache(
    namespace: Optional[str] = None,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    deleted = current_store.clear_cache(namespace=namespace)
    return {"deleted": deleted}
