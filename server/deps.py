"""Shared FastAPI dependencies for the server app."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import Depends, Header, HTTPException, Request, status

from server.mijia_runtime import LoginJobManager, MijiaRuntime
from server.store import AuthenticationFailedError, ServerStore
from server.updater import UpdateChecker


def get_store(request: Request) -> ServerStore:
    return request.app.state.store


def get_runtime(request: Request) -> MijiaRuntime:
    return request.app.state.runtime


def get_login_jobs(request: Request) -> LoginJobManager:
    return request.app.state.login_jobs


def get_started_at(request: Request) -> datetime:
    return request.app.state.started_at


def get_update_checker(request: Request) -> UpdateChecker:
    return request.app.state.update_checker


def extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return authorization.removeprefix("Bearer ").strip()


def require_admin(
    authorization: Annotated[Optional[str], Header()] = None,
    current_store: ServerStore = Depends(get_store),
) -> dict[str, Any]:
    token = extract_bearer_token(authorization)
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
        key = extract_bearer_token(authorization)
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
    key = extract_bearer_token(authorization)
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
