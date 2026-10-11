"""Verify smoke client behavior and cleanup boundaries without a Docker daemon."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import sqlite3
import subprocess
import threading
from urllib.error import URLError

import pytest

from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from tests.docker import smoke


def test_unregistered_production_volume_is_rejected_before_inspection(monkeypatch):
    docker = smoke.DockerRun("synthetic-image")
    inspected = []
    monkeypatch.setattr(docker, "inspect", lambda *args: inspected.append(args))
    with pytest.raises(smoke.SmokeError, match="unregistered volume"):
        docker.owned("volume", "mijia-data")
    assert inspected == []


def test_cleanup_never_removes_resources_with_a_different_owner(monkeypatch):
    docker = smoke.DockerRun("synthetic-image")
    docker.resources = {
        "container": [f"{docker.prefix}-container"],
        "volume": [f"{docker.prefix}-volume"],
    }
    commands = []
    monkeypatch.setattr(
        docker,
        "inspect",
        lambda kind, name: {
            "Config": {"Labels": {smoke.OWNER_LABEL: "another-run"}},
            "Labels": {smoke.OWNER_LABEL: "another-run"},
        },
    )
    monkeypatch.setattr(docker, "command", lambda *args, **kwargs: commands.append(args))
    errors = docker.cleanup()
    assert len(errors) == 2
    assert all("Refusing foreign" in error for error in errors)
    assert commands == []


def test_cleanup_removes_only_registered_exact_names(monkeypatch):
    docker = smoke.DockerRun("synthetic-image")
    container, volume = f"{docker.prefix}-container", f"{docker.prefix}-volume"
    docker.resources = {"container": [container], "volume": [volume]}
    commands = []
    monkeypatch.setattr(
        docker,
        "inspect",
        lambda kind, name: {
            "Config": {"Labels": {smoke.OWNER_LABEL: docker.run_id}},
            "Labels": {smoke.OWNER_LABEL: docker.run_id},
        },
    )
    monkeypatch.setattr(docker, "command", lambda *args, **kwargs: commands.append(args))
    assert docker.cleanup() == []
    assert commands == [
        ("container", "rm", "--force", container),
        ("volume", "rm", volume),
    ]


@pytest.mark.parametrize(
    ("stderr", "missing"),
    [
        ("Error response from daemon: No such container: gone", True),
        ("Cannot connect to the Docker daemon", False),
    ],
)
def test_inspect_does_not_hide_daemon_failure_as_successful_cleanup(monkeypatch, stderr, missing):
    docker = smoke.DockerRun("synthetic-image")
    monkeypatch.setattr(
        docker,
        "command",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", stderr),
    )
    if missing:
        assert docker.inspect("container", "gone") is None
    else:
        with pytest.raises(smoke.SmokeError, match="Cannot connect"):
            docker.inspect("container", "gone")


def test_helper_pins_local_image_and_avoids_anonymous_data_volumes(monkeypatch):
    docker = smoke.DockerRun("synthetic-image")
    docker.image_id = "sha256:synthetic-built-image"
    volume = f"{docker.prefix}-data"
    docker.resources["volume"].append(volume)
    commands = []
    monkeypatch.setattr(docker, "owned", lambda kind, name: {})

    def command(*args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "synthetic-output", "")

    monkeypatch.setattr(docker, "command", command)
    assert (
        docker.helper("print('synthetic-output')", {"/source": (volume, True)})
        == "synthetic-output"
    )
    arguments = commands[0]
    assert arguments[:2] == ("run", "--rm")
    assert docker.image_id in arguments
    assert f"type=volume,source={volume},target=/data,readonly" in arguments
    assert f"{smoke.OWNER_LABEL}={docker.run_id}" in arguments
    assert len(docker.resources["container"]) == 1


@pytest.mark.parametrize("process_uids", [[1000] * 4, [0] * 4])
def test_start_checks_application_pid_one_uid_instead_of_exec_caller(monkeypatch, process_uids):
    docker = smoke.DockerRun("synthetic-image")
    docker.image_id = "sha256:synthetic-built-image"
    volume = f"{docker.prefix}-data"
    docker.resources["volume"].append(volume)
    commands = []
    monkeypatch.setattr(docker, "wait_ready", lambda name: None)
    monkeypatch.setattr(
        docker,
        "wait_host_ready",
        lambda name, client: setattr(client, "base_url", docker.published_url(name)),
    )
    monkeypatch.setattr(
        docker,
        "owned",
        lambda kind, name: {
            "State": {"Running": True},
            "NetworkSettings": {
                "Ports": {"8123/tcp": [{"HostIp": "127.0.0.1", "HostPort": "32812"}]}
            },
        },
    )

    def command(*args, **kwargs):
        commands.append(args)
        output = json.dumps(process_uids) if args[0] == "exec" else "synthetic-container-id"
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(docker, "command", command)
    if process_uids[0] == 1000:
        _, url = docker.start(volume)
        assert url == "http://127.0.0.1:32812"
    else:
        with pytest.raises(smoke.SmokeError, match="application privileges"):
            docker.start(volume)
    assert "--init" not in commands[0]
    assert commands[1][0] == "exec" and "/proc/1/status" in commands[1][-1]


def test_backup_restore_preserves_a_decryptable_credential_and_its_key(tmp_path):
    source, restored, backup = (tmp_path / name for name in ("source", "restored", "backup"))
    for directory in (source, restored, backup):
        directory.mkdir()
    (source / "server").mkdir()
    with sqlite3.connect(source / "server/server.sqlite3") as database:
        database.execute("CREATE TABLE smoke_marker(value TEXT)")
        database.execute("INSERT INTO smoke_marker VALUES ('persisted')")
    credential_path = source / "credential.json"
    seed = smoke.SEED_CREDENTIAL.replace(
        "Path('/data/credential.json')", f"Path({str(credential_path)!r})"
    )
    exec(seed, {})
    assert json.loads(credential_path.read_text())["alg"] == "aes-256-gcm"
    archive_path = backup / "data.tar.gz"
    backup_script = smoke.BACKUP_DATA.replace("Path('/source')", f"Path({str(source)!r})").replace(
        "'/backup/data.tar.gz'", repr(str(archive_path))
    )
    exec(backup_script, {})
    restore_script = smoke.RESTORE_DATA.replace(
        "Path('/restore')", f"Path({str(restored)!r})"
    ).replace("'/backup/data.tar.gz'", repr(str(archive_path)))
    exec(restore_script, {})
    for name in ("credential.json", ".credential_key"):
        assert (
            hashlib.sha256((source / name).read_bytes()).digest()
            == hashlib.sha256((restored / name).read_bytes()).digest()
        )
    with sqlite3.connect(restored / "server/server.sqlite3") as database:
        assert database.execute("SELECT value FROM smoke_marker").fetchone()[0] == "persisted"
    credential = FileCredentialStore(restored / "credential.json").load()
    assert credential is not None and credential.user_id == smoke.FIXTURE_USER
    # A database/credential-only backup is insufficient: the key must accompany it.
    (restored / ".credential_key").unlink()
    assert FileCredentialStore(restored / "credential.json").load() is None


@pytest.fixture
def http_server():
    class Handler(BaseHTTPRequestHandler):
        dropped_calls = 0
        received_authorization = []
        static_requests = []

        def log_message(self, *args):
            pass

        def reply(self, status, payload, cookies=()):
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            type(self).static_requests.append(self.path)
            if self.path == "/api/admin/bootstrap/state":
                self.reply(200, {"initialized": True})
                return
            resources = {
                "/": (
                    "text/html; charset=utf-8",
                    b'<div id="app"></div><script src="/assets/app.js"></script>'
                    b'<link rel="stylesheet" href="/assets/app.css">',
                ),
                "/assets/app.js": ("text/javascript", b"document.getElementById('app');"),
                "/assets/app.css": ("text/css", b"body { color: black; }"),
            }
            content_type, content = resources[self.path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/login":
                self.reply(
                    200,
                    {"status": "ok"},
                    (
                        "mijia_admin_session=synthetic-session; Path=/; HttpOnly",
                        "mijia_csrf=synthetic-csrf; Path=/",
                    ),
                )
            else:
                type(self).dropped_calls += 1
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()

        def do_PUT(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            type(self).received_authorization.append(self.headers.get("Authorization"))
            cookies = self.headers.get("Cookie", "")
            allowed = (
                "mijia_admin_session=synthetic-session" in cookies
                and self.headers.get("X-CSRF-Token") == "synthetic-csrf"
            )
            self.reply(
                200 if allowed else 403,
                {"status": "ok"} if allowed else {"error": {"code": "CSRF_FAILED"}},
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_client_sends_cookie_and_matching_csrf_without_bearer(http_server):
    url, handler = http_server
    client = smoke.HttpClient(url)
    client.expect("POST", "/login")
    client.expect("PUT", "/config", 403, payload={"value": True}, error_code="CSRF_FAILED")
    client.expect("PUT", "/config", payload={"value": True}, headers=client.csrf_headers())
    assert handler.received_authorization == [None, None]


def published_info(port):
    return {
        "State": {"Running": True},
        "NetworkSettings": {
            "Ports": {"8123/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}
        },
    }


def test_restart_refreshes_host_port_and_preserves_cookie_session(http_server, monkeypatch):
    url, handler = http_server
    client = smoke.HttpClient(url)
    client.expect("POST", "/login")
    jar = client.cookies
    client.base_url = "http://127.0.0.1:1"  # Simulate the no-longer-published old endpoint.
    docker = smoke.DockerRun("synthetic-image")
    inspected = []

    def owned(kind, name):
        inspected.append((kind, name))
        return published_info(url.rsplit(":", 1)[1])

    monkeypatch.setattr(docker, "owned", owned)
    docker.wait_host_ready("owned-test-container", client)
    assert client.base_url == url
    assert client.cookies is jar
    assert client.cookie(smoke.ADMIN_COOKIE) == "synthetic-session"
    client.expect("PUT", "/config", payload={"value": True}, headers=client.csrf_headers())
    assert inspected == [("container", "owned-test-container")]
    assert handler.static_requests == ["/api/admin/bootstrap/state"]
    assert handler.received_authorization == [None]


def test_host_readiness_reinspects_port_and_retries_only_get(monkeypatch):
    docker = smoke.DockerRun("synthetic-image")
    ports = iter((31001, 31002))
    monkeypatch.setattr(docker, "owned", lambda *args: published_info(next(ports)))
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    client = smoke.HttpClient("http://127.0.0.1:1")
    jar = client.cookies
    requests = []

    def request(method, path):
        requests.append((method, path, client.base_url))
        if len(requests) == 1:
            raise URLError("connection refused while publish endpoint comes up")
        return smoke.Response(200, {"initialized": True}, {})

    monkeypatch.setattr(client, "request", request)
    docker.wait_host_ready("owned-test-container", client)
    assert requests == [
        ("GET", "/api/admin/bootstrap/state", "http://127.0.0.1:31001"),
        ("GET", "/api/admin/bootstrap/state", "http://127.0.0.1:31002"),
    ]
    assert client.cookies is jar


def test_bootstrap_fetches_actual_html_and_all_compiled_assets_without_relaxing_json(http_server):
    url, handler = http_server
    client = smoke.HttpClient(url)
    run = smoke.Smoke(smoke.DockerRun("synthetic-image"))
    run.check_frontend(client)
    assert handler.static_requests == ["/", "/assets/app.css", "/assets/app.js"]
    assert run.metadata["bootstrap_frontend_assets_verified"] == 2
    with pytest.raises(smoke.SmokeError, match="Non-JSON response"):
        client.expect("GET", "/")


def test_http_client_does_not_retry_mutations_after_losing_a_response(http_server):
    url, handler = http_server
    with pytest.raises(OSError):
        smoke.HttpClient(url).request("POST", "/lost-response", {"value": True})
    assert handler.dropped_calls == 1


def test_failed_run_still_records_phase_and_writes_report_without_secrets(monkeypatch, tmp_path):
    def fail(self):
        with self.phase("synthetic-failure"):
            raise smoke.SmokeError("expected synthetic failure")

    monkeypatch.setattr(smoke.Smoke, "execute", fail)
    monkeypatch.setattr(smoke.DockerRun, "diagnostics", lambda self: None)
    monkeypatch.setattr(smoke.DockerRun, "cleanup", lambda self: [])
    report_path = tmp_path / "results/report.json"
    assert smoke.main(["--image", "synthetic-image", "--report", str(report_path)]) == 1
    report_text = report_path.read_text()
    report = json.loads(report_text)
    assert report["status"] == "failed"
    assert report["checks"][0]["status"] == "failed"
    assert report["cleanup_errors"] == []
    assert "password" not in report_text and "synthetic-session" not in report_text
    assert "mk_live_" not in report_text


def test_fixture_exec_requires_its_exact_owned_data_mount_and_app_uid(monkeypatch):
    docker = smoke.DockerRun("synthetic-image")
    commands = []
    container, volume = f"{docker.prefix}-server", f"{docker.prefix}-data"
    monkeypatch.setattr(
        docker,
        "owned",
        lambda kind, name: {
            "Mounts": [
                {"Type": "volume", "Name": volume, "Destination": "/data"},
            ]
        },
    )
    monkeypatch.setattr(
        docker,
        "command",
        lambda *args: commands.append(args) or subprocess.CompletedProcess(args, 0, "fixture", ""),
    )
    assert docker.exec_python(container, volume, "print('fixture')") == "fixture"
    assert commands[0][:5] == ("exec", "--user", "1000:1000", container, "python")
    with pytest.raises(smoke.SmokeError, match="registered smoke data volume"):
        docker.exec_python(container, "foreign-volume", "must never execute")
    assert len(commands) == 1


def test_audit_recovery_smoke_uses_real_permission_denials_sqlite_and_queue(monkeypatch, tmp_path):
    from server.rate_limit import SlidingWindowRateLimiter
    from server.routers import admin_auth
    from tests.unit.server.test_app import make_client_with_store

    monkeypatch.setattr(
        admin_auth,
        "ADMIN_AUTH_RATE_LIMITER",
        SlidingWindowRateLimiter(max_requests=20, window_seconds=300),
    )
    client, store = make_client_with_store(tmp_path)
    store.settings.web_dist_dir.mkdir()
    (store.settings.web_dist_dir / "index.html").write_text('<div id="app"></div>')
    store.create_initial_admin("smoke-admin", "strong-smoke-password")
    assert (
        client.post(
            "/api/admin/auth/login",
            json={
                "username": "smoke-admin",
                "password": "strong-smoke-password",
            },
        ).status_code
        == 200
    )
    sdk_calls = []

    def refuse_sdk(*args, **kwargs):
        sdk_calls.append(True)
        raise AssertionError("Smoke permission probes must never enter Xiaomi SDK")

    monkeypatch.setattr(client.app.state.runtime, "_api_with_generation", refuse_sdk)

    class LocalHttp(smoke.HttpClient):
        def cookie(self, name):
            return client.cookies.get(name, "")

        def request(self, method, path, payload=None, headers=None):
            response = client.request(method, path, json=payload, headers=headers)
            return smoke.Response(response.status_code, response.json(), response.headers)

    docker = smoke.DockerRun("synthetic-image")
    container, volume = f"{docker.prefix}-server", f"{docker.prefix}-data"
    metadata = {"Mounts": [{"Type": "volume", "Name": volume, "Destination": "/data"}]}
    monkeypatch.setattr(docker, "owned", lambda kind, name: metadata)
    executed = []

    def local_fixture(*args):
        assert args[:5] == ("exec", "--user", "1000:1000", container, "python")
        script = args[-1]
        executed.append(script)
        script = (
            script.replace(
                "store = ServerStore(ServerSettings.from_env())",
                "store = TEST_STORE",
            )
            .replace(
                "'/data/server/server.sqlite3'",
                repr(str(store.settings.database_path)),
            )
            .replace("'/data/credential.json'", repr(str(store.settings.credential_path)))
        )
        from contextlib import redirect_stdout
        from io import StringIO

        output = StringIO()
        with redirect_stdout(output):
            exec(script, {"TEST_STORE": store})
        return subprocess.CompletedProcess(args, 0, output.getvalue(), "")

    monkeypatch.setattr(docker, "command", local_fixture)
    run = smoke.Smoke(docker)
    run.audit_recovery(container, volume, LocalHttp("http://synthetic-local-asgi"))
    assert sdk_calls == []
    assert run.metadata["queued_refusal_receipts_recovered"] == 2
    assert run.metadata["manual_audit_replay_delivered"] == 2
    events = store.list_audit(action="device.property.set")
    assert len(events) == 2 and all(row["result"] == "failed" for row in events)
    assert store.audit_status() == {"pending": 0, "invalid": 0, "unavailable": 0}
    assert client.get("/readyz").status_code == 200
    assert smoke.BLOCK_AUDIT_INSERTS in executed and smoke.UNBLOCK_AUDIT_INSERTS in executed
    assert not store.settings.credential_path.exists()


def test_failed_audit_probe_always_removes_its_insert_trigger(monkeypatch):
    docker = smoke.DockerRun("synthetic-image")
    scripts = []
    monkeypatch.setattr(docker, "exec_python", lambda name, volume, script: scripts.append(script))

    class FailingHttp:
        def expect(self, method, path, *args, **kwargs):
            return {"status": "ready"}

        def csrf_headers(self):
            return {"X-CSRF-Token": "synthetic"}

        def request(self, *args, **kwargs):
            return smoke.Response(200, {"success": True}, {})

    with pytest.raises(smoke.SmokeError, match="did not refuse control"):
        smoke.Smoke(docker).audit_recovery("owned-container", "owned-volume", FailingHttp())
    assert scripts[-1] == smoke.UNBLOCK_AUDIT_INSERTS


@pytest.mark.skipif(
    __import__("os").name != "posix",
    reason="Packaged probe requires Linux-style symlinks and modes",
)
def test_packaged_journal_probe_checks_real_posix_boundaries_as_unprivileged_user(
    monkeypatch, capsys
):
    import os
    from server.audit_journal import logger

    # The container smoke runs this script as uid 1000. Host unit tests verify
    # the same physical filesystem operations without requiring that uid.
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(logger, "disabled", logger.disabled)
    exec(smoke.CHECK_JOURNAL_POSIX, {})
    report = json.loads(capsys.readouterr().out)
    assert all(report.values()) and len(report) == 4
