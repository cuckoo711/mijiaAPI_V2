"""Mijia account/credential and sync routes for the admin API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from server.deps import get_login_jobs, get_runtime, get_store, require_admin
from server.mijia_runtime import LoginJobManager, MijiaRuntime
from server.store import ServerStore

router = APIRouter(tags=["admin-mijia"])


@router.get("/api/admin/mijia/account")
def admin_mijia_account(
    _admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return runtime.credential_status()


@router.post("/api/admin/mijia/login/start", status_code=status.HTTP_201_CREATED)
def admin_start_mijia_login(
    _admin: dict[str, Any] = Depends(require_admin),
    jobs: LoginJobManager = Depends(get_login_jobs),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    job = jobs.start()
    current_store.add_audit("mijia.login.start", "success", actor_type="admin")
    return job


@router.get("/api/admin/mijia/login/{job_id}")
def admin_get_mijia_login(
    job_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
    jobs: LoginJobManager = Depends(get_login_jobs),
) -> dict[str, Any]:
    return jobs.get(job_id)


@router.post("/api/admin/mijia/credential/refresh")
def admin_refresh_credential(
    _admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    result = runtime.refresh_credential()
    current_store.add_audit("mijia.credential.refresh", "success", actor_type="admin")
    return result


@router.delete("/api/admin/mijia/credential", status_code=status.HTTP_204_NO_CONTENT)
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


@router.post("/api/admin/sync")
def admin_sync(
    _admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    result = runtime.sync_all()
    current_store.add_audit("mijia.sync.start", "success", actor_type="admin")
    return result


@router.get("/api/admin/sync/progress")
def admin_sync_progress(
    _admin: dict[str, Any] = Depends(require_admin),
    runtime: MijiaRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    progress = runtime.get_sync_progress()
    if progress is None:
        return {"status": "idle"}
    return progress
