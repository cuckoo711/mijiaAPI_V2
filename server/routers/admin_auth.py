"""Administrator bootstrap and authentication routes."""

from __future__ import annotations

import os
from ipaddress import ip_address
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

import mijiaAPI_V2
from server.deps import extract_bearer_token, get_store
from server.rate_limit import ADMIN_AUTH_RATE_LIMITER
from server.store import (
    AdminNotFoundError,
    AuthenticationFailedError,
    BootstrapAlreadyCompletedError,
    InvalidCurrentPasswordError,
    ServerStore,
)


class BootstrapStateResponse(BaseModel):
    initialized: bool
    status: str
    version: str


class CreateAdminRequest(BaseModel):
    username: str = Field(default="admin", min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


def _bootstrap_source_allowed(host: str) -> bool:
    """Bootstrap is loopback-only unless explicitly relaxed for Docker/LAN setup."""

    try:
        address = ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    allow_private = os.getenv("MIJIA_BOOTSTRAP_ALLOW_PRIVATE", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return bool(allow_private and (address.is_private or address.is_link_local))


router = APIRouter(tags=["admin-auth"])


@router.get("/api/admin/bootstrap/state", response_model=BootstrapStateResponse)
def bootstrap_state(current_store: ServerStore = Depends(get_store)) -> dict[str, Any]:
    return {
        "initialized": current_store.has_admin(),
        "status": "ok",
        "version": mijiaAPI_V2.__version__,
    }


@router.post("/api/admin/bootstrap/admin", status_code=status.HTTP_201_CREATED)
def create_initial_admin(
    request: Request,
    payload: CreateAdminRequest,
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    source_ip = getattr(request.state, "source_ip", "") or ""
    if not _bootstrap_source_allowed(source_ip):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "BOOTSTRAP_LOCAL_ONLY",
                "message": "首次创建管理员仅允许本机回环地址访问（Docker 可设 MIJIA_BOOTSTRAP_ALLOW_PRIVATE=1）",
            },
        )
    limit = ADMIN_AUTH_RATE_LIMITER.check(f"bootstrap:{source_ip or 'unknown'}")
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": f"尝试过于频繁，请 {limit.retry_after_seconds} 秒后重试",
            },
            headers={"Retry-After": str(limit.retry_after_seconds)},
        )
    try:
        return current_store.create_initial_admin(payload.username, payload.password)
    except BootstrapAlreadyCompletedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BOOTSTRAP_ALREADY_COMPLETED", "message": str(exc)},
        ) from exc


@router.post("/api/admin/auth/login")
def admin_login(
    request: Request,
    payload: LoginRequest,
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    source_ip = getattr(request.state, "source_ip", "") or "unknown"
    limit = ADMIN_AUTH_RATE_LIMITER.check(f"login:{source_ip}")
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": f"登录尝试过于频繁，请 {limit.retry_after_seconds} 秒后重试",
            },
            headers={"Retry-After": str(limit.retry_after_seconds)},
        )
    try:
        return current_store.authenticate_admin(payload.username, payload.password)
    except AuthenticationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "ADMIN_AUTH_FAILED", "message": str(exc)},
        ) from exc


@router.post("/api/admin/auth/refresh")
def admin_refresh_session(
    authorization: Annotated[Optional[str], Header()] = None,
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    token = extract_bearer_token(authorization)
    try:
        return current_store.refresh_admin_session(token)
    except AuthenticationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "ADMIN_AUTH_FAILED", "message": str(exc)},
        ) from exc


@router.post("/api/admin/auth/change-password")
def admin_change_password(
    payload: ChangePasswordRequest,
    authorization: Annotated[Optional[str], Header()] = None,
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    token = extract_bearer_token(authorization)
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
