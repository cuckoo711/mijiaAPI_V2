"""Admin routes for homes/devices/scenes registry, config, api-keys and system info."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

import mijiaAPI_V2
from server.deps import get_store, get_update_checker, require_admin
from server.logging_utils import get_server_logger
from server.store import ServerStore
from server.updater import UpdateChecker

router = APIRouter(tags=["admin-resources"])
logger = get_server_logger(__name__)


def _audit_admin(store: ServerStore, admin: dict[str, Any], action: str, **metadata: Any) -> None:
    try:
        store.add_audit(
            action, "success", actor_type="admin", actor_id=admin["id"], metadata=metadata
        )
    except Exception as exc:
        logger.warning("failed to audit admin action %s (%s)", action, type(exc).__name__)


class CreateApiKeyRequest(BaseModel):
    """Create a scoped API key."""

    name: str = Field(min_length=1, max_length=120)
    scopes: list[
        Literal[
            "read:status",
            "read:devices",
            "write:devices",
            "write:scenes",
            "read:logs",
            "manage:cache",
        ]
    ] = Field(default_factory=lambda: ["read:status"], min_length=1)
    resource_policy: dict[Literal["homes", "devices", "scenes"], list[str]] = Field(
        default_factory=dict
    )
    expires_at: Optional[datetime] = None

    @field_validator("resource_policy")
    @classmethod
    def validate_resource_identifiers(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        for items in value.values():
            if any(not item.strip() for item in items):
                raise ValueError("资源标识不能为空")
        return {
            kind: list(dict.fromkeys(item.strip() for item in items))
            for kind, items in value.items()
        }


class SetApiKeyStatusRequest(BaseModel):
    """Enable or disable an API key."""

    is_active: bool


class RotateApiKeyRequest(BaseModel):
    expires_at: Optional[datetime] = None


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
    access_mode: Optional[str] = Field(default=None, pattern="^(read|write)$")


class UpdateSceneRequest(BaseModel):
    """Update local scene metadata."""

    hidden: Optional[bool] = None
    executable: Optional[bool] = None


class BulkAuthorizationRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=10000)
    enabled: bool = Field(strict=True)

    @field_validator("ids")
    @classmethod
    def nonempty_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("资源标识不能为空")
        return list(dict.fromkeys(value))


@router.post("/api/admin/{kind}/authorization/batch")
def admin_bulk_authorization(
    kind: Literal["devices", "scenes"],
    payload: BulkAuthorizationRequest,
    admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    result = current_store.set_resource_authorization(kind, payload.ids, payload.enabled)
    _audit_admin(
        current_store,
        admin,
        "resource.authorization.batch",
        kind=kind,
        ids=result["ids"],
        count=result["count"],
        enabled=payload.enabled,
    )
    return result


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
    result = current_store.set_config(key, payload.value, payload.source)
    _audit_admin(current_store, _admin, "config.update", key=key)
    return result


@router.post("/api/admin/api-keys", status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: CreateApiKeyRequest,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = current_store.create_api_key(
            name=payload.name,
            scopes=payload.scopes,
            resource_policy=payload.resource_policy,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_API_KEY", "message": str(exc)}) from exc
    _audit_admin(current_store, _admin, "api_key.create", key_id=result["id"])
    return result


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
    result = current_store.update_api_key_status(key_id, payload.is_active)
    _audit_admin(
        current_store, _admin, "api_key.status", key_id=key_id, is_active=payload.is_active
    )
    return result


@router.post("/api/admin/api-keys/{key_id}/rotate", status_code=status.HTTP_201_CREATED)
def rotate_api_key(
    key_id: str,
    payload: Optional[RotateApiKeyRequest] = None,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = current_store.rotate_api_key(
            key_id,
            expires_at=payload.expires_at if payload else None,
            replace_expiry=payload is not None and "expires_at" in payload.model_fields_set,
        )
    except ValueError as exc:
        raise HTTPException(
            422, detail={"code": "KEY_ROTATION_REJECTED", "message": str(exc)}
        ) from exc
    _audit_admin(current_store, _admin, "api_key.rotate", old_key_id=key_id, key_id=result["id"])
    return result


@router.delete("/api/admin/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    key_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
    current_store: ServerStore = Depends(get_store),
) -> None:
    current_store.delete_api_key(key_id)
    _audit_admin(current_store, _admin, "api_key.delete", key_id=key_id)


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
    result = current_store.update_device(
        device_id,
        payload.model_dump(exclude_unset=True),
    )
    _audit_admin(
        current_store,
        _admin,
        "device.authorization.update",
        device=device_id,
        fields=list(payload.model_fields_set),
    )
    return result


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
    result = current_store.update_scene(scene_id, payload.model_dump(exclude_unset=True))
    _audit_admin(
        current_store,
        _admin,
        "scene.authorization.update",
        scene=scene_id,
        fields=list(payload.model_fields_set),
    )
    return result


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
