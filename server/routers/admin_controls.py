"""Explicit manual device and scene operations from the authenticated admin UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from server.control_operations import run_audited_control
from server.deps import get_runtime, get_store, require_admin
from server.mijia_runtime import MijiaRuntime
from server.routers.api_v1 import CallActionRequest, SetPropertyRequest
from server.store import ServerStore

router = APIRouter(tags=["admin-controls"])


def _visible(resource: dict[str, Any]) -> bool:
    return not resource.get("hidden", False)


@router.get("/api/admin/devices/{device_id}/state")
def device_state(
    device_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return {"items": runtime.get_device_state(device_id, internal_only=True)}


@router.get("/api/admin/devices/{device_id}/spec")
def device_spec(
    device_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return {"spec": runtime.get_device_spec(device_id, internal_only=True)}


@router.post("/api/admin/devices/{device_id}/properties")
def set_property(
    request: Request,
    device_id: str,
    payload: SetPropertyRequest,
    admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
    store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return run_audited_control(
        store,
        actor_type="admin",
        actor_id=admin["id"],
        action="device.property.set",
        metadata={"device_id": device_id, "siid": payload.siid, "piid": payload.piid},
        request=request,
        operation=lambda: runtime.set_device_property(
            device_id,
            payload.siid,
            payload.piid,
            payload.value,
            internal_only=True,
            authorize=_visible,
        ),
    )


@router.post("/api/admin/devices/{device_id}/actions")
def call_action(
    request: Request,
    device_id: str,
    payload: CallActionRequest,
    admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
    store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return run_audited_control(
        store,
        actor_type="admin",
        actor_id=admin["id"],
        action="device.action.call",
        metadata={"device_id": device_id, "siid": payload.siid, "aiid": payload.aiid},
        request=request,
        operation=lambda: runtime.call_device_action(
            device_id,
            payload.siid,
            payload.aiid,
            payload.params,
            internal_only=True,
            authorize=_visible,
        ),
    )


@router.post("/api/admin/scenes/{scene_id}/execute")
def execute_scene(
    request: Request,
    scene_id: str,
    admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
    store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    return run_audited_control(
        store,
        actor_type="admin",
        actor_id=admin["id"],
        action="scene.execute",
        metadata={"scene_id": scene_id},
        request=request,
        operation=lambda: runtime.execute_scene(scene_id, internal_only=True, authorize=_visible),
    )


@router.get("/api/admin/operations/{operation_id}")
def operation_receipt(
    operation_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
    store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    event = store.get_audit_event(operation_id)
    return {
        name: event[name]
        for name in (
            "id",
            "occurred_at",
            "actor_type",
            "action",
            "result",
            "request_id",
            "metadata",
            "delivery",
        )
    }


@router.get("/api/admin/audit/health")
def audit_health(
    _admin: dict[str, Any] = Depends(require_admin),
    store: ServerStore = Depends(get_store),
) -> dict[str, int]:
    return store.audit_status()


@router.post("/api/admin/audit/replay")
def replay_audit(
    _admin: dict[str, Any] = Depends(require_admin),
    store: ServerStore = Depends(get_store),
) -> dict[str, int]:
    return store.flush_pending_audit()
