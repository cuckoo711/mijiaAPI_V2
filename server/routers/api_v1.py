"""Public /api/v1/* routes for scoped API-key clients."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

import mijiaAPI_V2
from mijiaAPI_V2.domain.exceptions import ExecutionUnknownError
from server.deps import (
    get_runtime,
    get_started_at,
    get_store,
    require_api_key_scope,
    require_status_api_key,
)
from server.logging_utils import get_server_logger
from server.mijia_runtime import MijiaRuntime
from server.store import ServerStore

router = APIRouter(tags=["api-v1"])
logger = get_server_logger(__name__)


class SetPropertyRequest(BaseModel):
    """Set a MiOT property."""

    siid: int = Field(gt=0, strict=True)
    piid: int = Field(gt=0, strict=True)
    value: Any


class CallActionRequest(BaseModel):
    """Call a MiOT action."""

    siid: int = Field(gt=0, strict=True)
    aiid: int = Field(gt=0, strict=True)
    params: dict[str, Any] = Field(default_factory=dict)


class BatchPropertyItem(SetPropertyRequest):
    device: str = Field(min_length=1, validation_alias=AliasChoices("device", "device_id"))

    @field_validator("device")
    @classmethod
    def nonempty_device(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("设备标识不能为空")
        return value.strip()

    @model_validator(mode="before")
    @classmethod
    def validate_device_reference(cls, value: Any) -> Any:
        if isinstance(value, dict):
            device, alias = value.get("device"), value.get("device_id")
            if device is not None and alias is not None and device != alias:
                raise ValueError("device 与 device_id 必须引用同一设备")
        return value


class BatchPropertyRequest(BaseModel):
    """Batch set properties."""

    items: list[BatchPropertyItem] = Field(min_length=1)


def _control_audit_status(result: dict[str, Any], expected_count: Optional[int]) -> str:
    """Require explicit SDK success; incomplete batches must not look successful."""

    def miot_succeeded(item: Any) -> bool:
        return isinstance(item, dict) and type(item.get("code")) is int and item["code"] == 0

    if expected_count is not None:
        items = result.get("items")
        if not isinstance(items, list):
            return "failed"
        succeeded = sum(miot_succeeded(item) for item in items)
        if expected_count > 0 and len(items) == expected_count and succeeded == expected_count:
            return "success"
        return "warning" if succeeded else "failed"
    if "success" in result:
        return "success" if result["success"] is True else "failed"
    return "success" if miot_succeeded(result.get("result")) else "failed"


def _run_audited_control(
    current_store: ServerStore,
    api_key: dict[str, Any],
    *,
    action: str,
    metadata: dict[str, Any],
    operation: Callable[[], dict[str, Any]],
    expected_count: Optional[int] = None,
) -> dict[str, Any]:
    """Record the control outcome without masking it if audit storage fails."""

    def record(status: str, details: dict[str, Any]) -> None:
        try:
            current_store.add_audit(
                action,
                status,
                actor_type="api_key",
                actor_id=api_key["key_prefix"],
                metadata=details,
            )
        except Exception as exc:
            # The command may already have executed; do not turn a logging
            # failure into an apparent control failure that invites a retry.
            logger.warning("failed to audit control action %s (%s)", action, type(exc).__name__)

    try:
        result = operation()
    except ExecutionUnknownError as exc:
        details = {**metadata, "error_type": type(exc).__name__, "retry_safe": False}
        completed_count = exc.context.get("completed_count")
        if type(completed_count) is int and completed_count >= 0:
            details["completed_count"] = completed_count
        record("unknown", details)
        raise
    except Exception as exc:
        # Exception messages may contain upstream credentials or payloads.
        record("failed", {**metadata, "error_type": type(exc).__name__})
        raise
    record(_control_audit_status(result, expected_count), metadata)
    return result


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
    candidates.discard("")
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
    devices = current_store.list_devices(include_spec=include_spec, include_raw=include_raw)
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
    return {
        "items": runtime.get_device_state(
            device["id"],
            internal_only=True,
            authorize=lambda resource: _resource_allowed(api_key, "devices", resource),
        )
    }


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
    return {
        "spec": runtime.get_device_spec(
            device["id"],
            internal_only=True,
            authorize=lambda resource: _resource_allowed(api_key, "devices", resource),
        )
    }


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
    return _run_audited_control(
        current_store,
        api_key,
        action="device.property.set",
        metadata={"device": device_slug, "siid": payload.siid, "piid": payload.piid},
        operation=lambda: runtime.set_device_property(
            device["id"],
            payload.siid,
            payload.piid,
            payload.value,
            internal_only=True,
            authorize=lambda resource: _resource_allowed(api_key, "devices", resource),
        ),
    )


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
    return _run_audited_control(
        current_store,
        api_key,
        action="device.action.call",
        metadata={"device": device_slug, "siid": payload.siid, "aiid": payload.aiid},
        operation=lambda: runtime.call_device_action(
            device["id"],
            payload.siid,
            payload.aiid,
            payload.params,
            internal_only=True,
            authorize=lambda resource: _resource_allowed(api_key, "devices", resource),
        ),
    )


@router.post("/api/v1/batch/devices/properties")
def api_batch_set_properties(
    payload: BatchPropertyRequest,
    api_key: dict[str, Any] = Depends(require_api_key_scope("write:devices")),
    runtime: MijiaRuntime = Depends(get_runtime),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    normalized_items: list[dict[str, Any]] = []
    for item in payload.items:
        normalized = item.model_dump()
        device = current_store.get_device(item.device)
        if not _resource_allowed(api_key, "devices", device):
            raise PermissionError("API key cannot access one or more devices")
        normalized["device"] = device["id"]
        normalized_items.append(normalized)
    return _run_audited_control(
        current_store,
        api_key,
        action="device.property.batch_set",
        metadata={"count": len(payload.items)},
        operation=lambda: runtime.batch_set_properties(
            normalized_items,
            internal_only=True,
            authorize=lambda resource: _resource_allowed(api_key, "devices", resource),
        ),
        expected_count=len(normalized_items),
    )


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
    return _run_audited_control(
        current_store,
        api_key,
        action="scene.execute",
        metadata={"scene": scene_id},
        operation=lambda: runtime.execute_scene(
            scene["id"],
            internal_only=True,
            authorize=lambda resource: _resource_allowed(api_key, "scenes", resource),
        ),
    )


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
