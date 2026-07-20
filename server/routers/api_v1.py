"""Public /api/v1/* routes for scoped API-key clients."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

import mijiaAPI_V2
from server.deps import (
    get_runtime,
    get_started_at,
    get_store,
    require_api_key_scope,
    require_status_api_key,
)
from server.mijia_runtime import MijiaRuntime
from server.store import ServerStore

router = APIRouter(tags=["api-v1"])


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


@router.get("/api/v1/status")
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


@router.get("/api/v1/account")
def api_account(
    _api_key: dict[str, Any] = Depends(require_api_key_scope("read:status")),
    runtime: MijiaRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return runtime.credential_status()


@router.get("/api/v1/homes")
def api_homes(
    api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    homes = current_store.list_homes()
    return {"items": [home for home in homes if _resource_allowed(api_key, "homes", home)]}


@router.get("/api/v1/devices")
def api_devices(
    include_spec: bool = False,
    include_raw: bool = False,
    api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    devices = current_store.list_devices(
        include_spec=include_spec, include_raw=include_raw
    )
    return {
        "items": [device for device in devices if _resource_allowed(api_key, "devices", device)]
    }


@router.get("/api/v1/devices/{device_slug}")
def api_device(
    device_slug: str,
    api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    device = current_store.get_device(device_slug)
    if not _resource_allowed(api_key, "devices", device):
        raise PermissionError("API key cannot access this device")
    return device


@router.get("/api/v1/devices/{device_slug}/state")
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


@router.get("/api/v1/devices/{device_slug}/spec")
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


@router.post("/api/v1/devices/{device_slug}/properties")
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


@router.post("/api/v1/devices/{device_slug}/actions")
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


@router.post("/api/v1/batch/devices/properties")
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


@router.get("/api/v1/scenes")
def api_scenes(
    api_key: dict[str, Any] = Depends(require_api_key_scope("read:devices")),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    scenes = current_store.list_scenes()
    return {"items": [scene for scene in scenes if _resource_allowed(api_key, "scenes", scene)]}


@router.post("/api/v1/scenes/{scene_id}/execute")
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


@router.post("/api/v1/cache/refresh")
def api_refresh_cache(
    home_id: Optional[str] = None,
    _api_key: dict[str, Any] = Depends(require_api_key_scope("manage:cache")),
    runtime: MijiaRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    runtime.refresh_cache(home_id=home_id)
    return {"success": True}


@router.post("/api/v1/cache/clear")
def api_clear_cache(
    _api_key: dict[str, Any] = Depends(require_api_key_scope("manage:cache")),
    runtime: MijiaRuntime = Depends(get_runtime),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    runtime.clear_sdk_cache()
    deleted = current_store.clear_cache()
    return {"success": True, "deleted": deleted}


@router.get("/api/v1/logs")
def api_logs(
    limit: int = Query(default=100, ge=1, le=500),
    _api_key: dict[str, Any] = Depends(require_api_key_scope("read:logs")),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return {"items": current_store.list_audit(limit=limit)}
