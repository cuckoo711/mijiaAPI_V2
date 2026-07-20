"""Shared FastAPI dependencies for the server app."""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import Depends, Header, HTTPException, Request, status

from server.mijia_runtime import LoginJobManager, MijiaRuntime
from server.store import AuthenticationFailedError, ServerStore


def get_store(request: Request) -> ServerStore:
    return request.app.state.store


def get_runtime(request: Request) -> MijiaRuntime:
    return request.app.state.runtime


def get_login_jobs(request: Request) -> LoginJobManager:
    return request.app.state.login_jobs


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
