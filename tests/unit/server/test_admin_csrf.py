"""Tests for administrator CSRF double-submit helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from server.admin_csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    csrf_protection_required,
    csrf_tokens_match,
    generate_csrf_token,
)
from server.admin_session_cookie import ADMIN_SESSION_COOKIE_NAME


def test_csrf_tokens_match_requires_both_sides() -> None:
    token = generate_csrf_token()
    assert csrf_tokens_match(token, token) is True
    assert csrf_tokens_match(token, "other") is False
    assert csrf_tokens_match(token, None) is False
    assert csrf_tokens_match(None, token) is False
    assert csrf_tokens_match("", token) is False


def test_csrf_protection_required_for_cookie_session_posts() -> None:
    request = MagicMock()
    request.method = "POST"
    request.url.path = "/api/admin/api-keys"
    request.headers = {}
    request.cookies = {ADMIN_SESSION_COOKIE_NAME: "ms_session"}
    assert csrf_protection_required(request) is True


def test_csrf_protection_skips_bearer_login_bootstrap_get_and_api_v1() -> None:
    request = MagicMock()
    request.method = "POST"
    request.url.path = "/api/admin/api-keys"
    request.headers = {"Authorization": "Bearer tok"}
    request.cookies = {ADMIN_SESSION_COOKIE_NAME: "ms_session"}
    assert csrf_protection_required(request) is False

    request.headers = {}
    request.url.path = "/api/admin/auth/login"
    assert csrf_protection_required(request) is False

    request.url.path = "/api/admin/bootstrap/admin"
    assert csrf_protection_required(request) is False

    request.url.path = "/api/v1/status"
    assert csrf_protection_required(request) is False

    request.method = "GET"
    request.url.path = "/api/admin/app-info"
    assert csrf_protection_required(request) is False

    assert CSRF_COOKIE_NAME == "mijia_csrf"
    assert CSRF_HEADER_NAME == "X-CSRF-Token"
