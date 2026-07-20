"""Tests for administrator session cookie helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from server.admin_session_cookie import (
    ADMIN_SESSION_COOKIE_NAME,
    admin_session_max_age_seconds,
    read_admin_session_token,
    request_is_https,
)


def test_admin_session_max_age_seconds() -> None:
    assert admin_session_max_age_seconds(12) == 12 * 3600
    assert admin_session_max_age_seconds(0) == 60


def test_read_admin_session_token_prefers_bearer_over_cookie() -> None:
    request = MagicMock()
    request.cookies = {ADMIN_SESSION_COOKIE_NAME: "cookie-token"}
    assert (
        read_admin_session_token(request, "Bearer bearer-token") == "bearer-token"
    )
    assert read_admin_session_token(request, None) == "cookie-token"
    request.cookies = {}
    assert read_admin_session_token(request, None) is None


def test_request_is_https_direct_and_trusted_proxy() -> None:
    request = MagicMock()
    request.url.scheme = "https"
    request.client.host = "10.0.0.1"
    request.headers = {}
    assert request_is_https(request, {}) is True

    request.url.scheme = "http"
    assert request_is_https(request, {"TRUST_PROXY_HEADERS": False}) is False

    request.client.host = "127.0.0.1"
    request.headers = {"X-Forwarded-Proto": "https"}
    assert (
        request_is_https(
            request,
            {
                "TRUST_PROXY_HEADERS": True,
                "TRUSTED_PROXY_CIDRS": ["127.0.0.1/32"],
            },
        )
        is True
    )

    request.client.host = "203.0.113.10"
    assert (
        request_is_https(
            request,
            {
                "TRUST_PROXY_HEADERS": True,
                "TRUSTED_PROXY_CIDRS": ["127.0.0.1/32"],
            },
        )
        is False
    )
