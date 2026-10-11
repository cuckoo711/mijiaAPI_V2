"""Readiness distinguishes dependencies from liveness and preserves error headers."""

import sqlite3
from unittest.mock import Mock

from fastapi import HTTPException

from tests.unit.server.test_app import make_client_with_store


def test_readiness_checks_storage_frontend_and_audit_without_mutating_config(tmp_path):
    client, store = make_client_with_store(tmp_path)
    frontend = store.settings.web_dist_dir
    frontend.mkdir()
    (frontend / "index.html").write_text('<div id="app"></div>')
    before = store.list_config()
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {"sqlite": True, "frontend": True, "audit": True}
    assert store.list_config() == before


def test_queued_audit_degrades_readiness_without_faking_liveness_failure(tmp_path, monkeypatch):
    client, store = make_client_with_store(tmp_path)
    frontend = store.settings.web_dist_dir
    frontend.mkdir()
    (frontend / "index.html").write_text('<div id="app"></div>')
    monkeypatch.setattr(
        store, "_persist_audit_event", Mock(side_effect=sqlite3.OperationalError("readonly"))
    )
    store.add_audit("sample", "success")
    assert client.get("/readyz").status_code == 503
    assert client.get("/healthz").status_code == 200


def test_storage_failure_is_503_with_trace_header(tmp_path, monkeypatch):
    client, store = make_client_with_store(tmp_path)
    monkeypatch.setattr(
        store, "get_config_map", Mock(side_effect=sqlite3.OperationalError("secret path"))
    )
    response = client.get("/readyz")
    assert response.status_code == 503 and response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert "secret path" not in response.text


def test_http_error_keeps_retry_after_and_request_id(tmp_path):
    client, _ = make_client_with_store(tmp_path)

    @client.app.get("/test-rate-limit")
    def limited():
        raise HTTPException(
            429,
            detail={"code": "RATE_LIMITED", "message": "Retry later"},
            headers={"Retry-After": "17"},
        )

    response = client.get("/test-rate-limit", headers={"X-Request-ID": "client-trace"})
    assert response.status_code == 429 and response.headers["Retry-After"] == "17"
    assert response.headers["X-Request-ID"] == "client-trace"
