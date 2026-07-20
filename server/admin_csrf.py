"""Double-submit CSRF cookie helpers for administrator SPA sessions."""

from __future__ import annotations

import hmac
import secrets
from typing import Optional

from fastapi import Request, Response

from server.admin_session_cookie import ADMIN_SESSION_COOKIE_NAME, optional_bearer_token

CSRF_COOKIE_NAME = "mijia_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Mutating routes that must remain reachable before a CSRF cookie exists.
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/admin/auth/login",
        "/api/admin/bootstrap/admin",
    }
)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(
    response: Response,
    token: str,
    *,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        httponly=False,
        samesite="lax",
        secure=secure,
    )


def clear_csrf_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        httponly=False,
        samesite="lax",
        secure=secure,
    )


def csrf_tokens_match(cookie_token: Optional[str], header_token: Optional[str]) -> bool:
    if not cookie_token or not header_token:
        return False
    cookie = cookie_token.strip()
    header = header_token.strip()
    if not cookie or not header:
        return False
    if len(cookie) != len(header):
        return False
    return hmac.compare_digest(cookie, header)


def request_uses_cookie_admin_session(request: Request) -> bool:
    """True when auth would come from the session cookie (no Bearer)."""

    if optional_bearer_token(request.headers.get("Authorization")):
        return False
    cookie = (request.cookies.get(ADMIN_SESSION_COOKIE_NAME) or "").strip()
    return bool(cookie)


def csrf_protection_required(request: Request) -> bool:
    """Whether this request must present a matching double-submit CSRF token."""

    if request.method.upper() not in UNSAFE_METHODS:
        return False
    path = request.url.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    if path == "/healthz" or path.startswith("/api/v1"):
        return False
    if not path.startswith("/api/admin"):
        return False
    if path in CSRF_EXEMPT_PATHS:
        return False
    return request_uses_cookie_admin_session(request)


def read_csrf_header(request: Request) -> Optional[str]:
    value = request.headers.get(CSRF_HEADER_NAME)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
