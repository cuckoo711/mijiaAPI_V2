"""HttpOnly cookie helpers for administrator SPA sessions."""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any, Optional

from fastapi import Request, Response

ADMIN_SESSION_COOKIE_NAME = "mijia_admin_session"
DEFAULT_TRUSTED_PROXY_CIDRS = ("127.0.0.1/32", "::1/128")


def _config_bool(config: dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _config_string_list(
    config: dict[str, Any], key: str, default: tuple[str, ...]
) -> list[str]:
    value = config.get(key, list(default))
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(default)


def _parse_ip(host: str) -> Any:
    value = host.strip()
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and value.rsplit(":", 1)[1].isdigit():
        value = value.rsplit(":", 1)[0]
    try:
        return ip_address(value)
    except ValueError:
        return None


def _host_in_cidrs(host: str, cidrs: list[str]) -> bool:
    address = _parse_ip(host)
    if address is None:
        return False
    for cidr in cidrs:
        try:
            network = ip_network(cidr, strict=False)
        except ValueError:
            continue
        if address.version == network.version and address in network:
            return True
    return False


def request_is_https(request: Request, config: Optional[dict[str, Any]] = None) -> bool:
    """True when the client connection is HTTPS, or a trusted proxy says so."""

    if request.url.scheme == "https":
        return True
    if not config or not _config_bool(config, "TRUST_PROXY_HEADERS", default=False):
        return False
    direct_host = request.client.host if request.client else ""
    trusted_cidrs = _config_string_list(
        config,
        "TRUSTED_PROXY_CIDRS",
        DEFAULT_TRUSTED_PROXY_CIDRS,
    )
    if not _host_in_cidrs(direct_host, trusted_cidrs):
        return False
    proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    return proto == "https"


def admin_session_max_age_seconds(admin_session_hours: int) -> int:
    return max(60, int(admin_session_hours) * 3600)


def set_admin_session_cookie(
    response: Response,
    token: str,
    *,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_admin_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def optional_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def read_admin_session_token(
    request: Request,
    authorization: Optional[str] = None,
) -> Optional[str]:
    """Prefer Authorization Bearer, then fall back to the HttpOnly session cookie."""

    bearer = optional_bearer_token(authorization)
    if bearer:
        return bearer
    cookie = request.cookies.get(ADMIN_SESSION_COOKIE_NAME)
    if cookie:
        return cookie.strip() or None
    return None
