"""Smoke-test a frozen release executable without source files or cloud credentials.

Only the Python standard library is used. The executable is copied into an
otherwise empty temporary directory, so a successful check proves that the
configuration template and frontend came from the executable's own bundle.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import locale
import os
import platform
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


class SmokeFailure(RuntimeError):
    """An intentionally credential-free failure message."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def decode_output(data: bytes) -> str:
    """Accept UTF-8 and native Windows GBK console output without crashing."""

    for encoding in dict.fromkeys(("utf-8", locale.getpreferredencoding(False), "gbk")):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def parse_cli_json(data: bytes, command: str) -> dict[str, Any]:
    # First-run initialization may print a human-readable notice before JSON.
    output = decode_output(data)
    decoder = json.JSONDecoder()
    for position, character in enumerate(output):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(output[position:])
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    raise SmokeFailure(f"{command} did not return a JSON object")


class EntryAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: set[str] = set()
        self.has_app = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id") == "app":
            self.has_app = True
        for key in ("src", "href"):
            value = values.get(key)
            if value and urlsplit(value).path.startswith("/assets/"):
                self.urls.add(value)


class FrozenSmoke:
    def __init__(self, executable: Path, expected_version: str, timeout: float) -> None:
        self.original = executable
        self.expected_version = expected_version.removeprefix("v")
        self.timeout = timeout
        self.checks: list[dict[str, Any]] = []
        self.diagnostics: dict[str, Any] = {}
        self.http = build_opener(ProxyHandler({}))

    def passed(self, name: str, **details: Any) -> None:
        self.checks.append({"name": name, "passed": True, **details})
        print(f"PASS {name}", flush=True)

    def cli(self, *arguments: str, as_json: bool = True) -> Any:
        command = arguments[0]
        try:
            result = subprocess.run(
                [str(self.executable), *arguments],
                cwd=self.cwd,
                env=self.env,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure(f"{command} timed out") from exc
        require(result.returncode == 0, f"{command} exited with code {result.returncode}")
        # Never print stdout/stderr: commands can contain administrator details.
        return parse_cli_json(result.stdout, command) if as_json else decode_output(result.stdout)

    def request(self, path: str, payload: dict[str, Any] | None = None) -> tuple[bytes, str]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with self.http.open(request, timeout=5) as response:
                require(response.status == 200, f"{path} did not return HTTP 200")
                return response.read(), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            if path == "/readyz":
                try:
                    readiness = json.loads(exc.read())
                    checks = readiness.get("checks", {})
                    self.diagnostics["readiness"] = {
                        "http_status": exc.code,
                        "checks": {
                            name: checks[name]
                            for name in ("sqlite", "frontend", "audit")
                            if type(checks.get(name)) is bool
                        },
                    }
                except (ValueError, AttributeError):
                    pass
            raise SmokeFailure(f"{path} returned HTTP {exc.code}") from exc

    def json_request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body, content_type = self.request(path, payload)
        require("application/json" in content_type, f"{path} is not JSON")
        try:
            result = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SmokeFailure(f"{path} returned invalid JSON") from exc
        require(isinstance(result, dict), f"{path} is not a JSON object")
        return result

    def start(self, attempt: int) -> subprocess.Popen[bytes]:
        # Logs go to a file to avoid filling a subprocess pipe during startup.
        with (self.cwd / f"server-{attempt}.log").open("wb") as log:
            process = subprocess.Popen(
                [str(self.executable), "run"],
                cwd=self.cwd,
                env=self.env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                require(process.poll() is None, "run exited before becoming healthy")
                try:
                    health = self.json_request("/healthz")
                except (URLError, TimeoutError, ConnectionError):
                    time.sleep(0.2)
                    continue
                require(health.get("status") == "ok", "Liveness status is not ok")
                require(health.get("version") == self.expected_version, "Liveness version mismatch")
                return process
            raise SmokeFailure("run did not become healthy before timeout")
        except BaseException:
            self.stop(process)
            raise

    @staticmethod
    def stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            # A one-file PyInstaller executable has a parent and child process.
            # Terminating only the parent can leave a server holding SQLite open.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=20,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)

    def verify_server(self, label: str) -> None:
        ready = self.json_request("/readyz")
        require(ready.get("status") == "ready", "Readiness status is not ready")
        require(
            ready.get("checks") == {"sqlite": True, "frontend": True, "audit": True},
            "Readiness must pass SQLite, bundled frontend and audit storage",
        )
        self.passed(f"{label}_health_and_readiness")

        state = self.json_request("/api/admin/bootstrap/state")
        require(state.get("initialized") is True, "Persisted administrator is missing")
        login = self.json_request(
            "/api/admin/auth/login", {"username": self.username, "password": self.password}
        )
        require(login.get("admin", {}).get("username") == self.username, "Admin login failed")
        require(bool(login.get("token")), "Admin login did not create a session")
        # The token and cookies are never copied to the report or printed.
        self.passed(f"{label}_administrator_login")

    def verify_frontend(self) -> None:
        body, content_type = self.request("/")
        require("text/html" in content_type, "Homepage is not bundled HTML")
        parser = EntryAssets()
        parser.feed(body.decode("utf-8"))
        require(parser.has_app and bool(parser.urls), "Homepage has no app or entry assets")
        for value in sorted(parser.urls):
            resolved = urlsplit(urljoin(self.base_url + "/", value))
            require(
                resolved.scheme == "http" and resolved.netloc == urlsplit(self.base_url).netloc,
                "Homepage entry assets must be served locally",
            )
            asset_path = resolved.path + (f"?{resolved.query}" if resolved.query else "")
            content, mime = self.request(asset_path)
            require(bool(content), "An entry asset is empty")
            require("text/html" not in mime, "An entry asset returned the SPA fallback")
            if resolved.path.endswith(".js"):
                require("javascript" in mime, "JavaScript entry asset has incorrect content type")
            if resolved.path.endswith(".css"):
                require("text/css" in mime, "CSS entry asset has incorrect content type")
        self.passed("bundled_frontend_and_all_entry_assets", asset_count=len(parser.urls))

    def run(self) -> None:
        require(self.original.is_file(), "Executable does not exist")
        with tempfile.TemporaryDirectory(prefix="mijia-frozen-smoke-") as directory:
            # macOS's default /var temporary directory is an alias for
            # /private/var. Use the physical path so the audit store's
            # deliberate symlink-ancestor rejection remains enabled.
            self.cwd = Path(directory).resolve()
            self.executable = self.cwd / self.original.name
            shutil.copy2(self.original, self.executable)
            require(
                not any((self.cwd / name).exists() for name in ("configs", "web", "server")),
                "Smoke directory must not contain source or runtime assets",
            )
            self.env = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith("MIJIA_")
                and key.upper() not in {"PYTHONPATH", "PYTHONHOME"}
            }
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            database = self.cwd / "data" / "server.sqlite3"
            credential = self.cwd / "data" / "credential.json"
            self.env.update(
                {
                    "MIJIA_SERVER_HOST": "127.0.0.1",
                    "MIJIA_SERVER_PORT": str(port),
                    "MIJIA_SERVER_DATA_DIR": str(self.cwd / "data"),
                    "MIJIA_SERVER_DATABASE_PATH": str(database),
                    "MIJIA_CREDENTIAL_PATH": str(credential),
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                }
            )
            self.base_url = f"http://127.0.0.1:{port}"
            self.username = "frozen_smoke_admin"
            self.password = secrets.token_urlsafe(24)

            help_text = self.cli("--help", as_json=False)
            require("write-config" in help_text and "status" in help_text, "CLI help is incomplete")
            self.passed("cli_help")
            status = self.cli("status")
            require(status.get("version") == self.expected_version, "CLI version mismatch")
            require(status.get("web_dist_exists") is True, "Bundled frontend is missing")
            require(status.get("credential_exists") is False, "Smoke must not load credentials")
            self.passed("cli_status_version_and_bundled_frontend")

            config_output = self.cwd / "exported-config" / "server.toml"
            config = self.cli("write-config", "--output", str(config_output))
            require(config.get("written") == str(config_output), "write-config ignored --output")
            require(config_output.is_file(), "write-config did not export its bundled template")
            template = config_output.read_text(encoding="utf-8")
            require(
                "[server]" in template and "[storage]" in template, "Config template is incomplete"
            )
            default_config = self.cli("write-config", "--force")
            require(
                Path(default_config.get("written", "")) == Path("configs/server.toml")
                and (self.cwd / "configs" / "server.toml").is_file(),
                "write-config did not populate its default runtime path",
            )
            self.passed("write_config_from_bundled_template")

            initialized = self.cli("init", "--admin", self.username, "--password", self.password)
            require(initialized.get("initialized") is True, "SQLite initialization failed")
            require(
                initialized.get("admin", {}).get("username") == self.username,
                "Initial administrator was not created",
            )
            self.passed("cli_init_sqlite_and_administrator")

            process = self.start(1)
            try:
                self.verify_server("first_start")
                self.verify_frontend()
            finally:
                self.stop(process)

            process = self.start(2)
            try:
                self.verify_server("restart")
            finally:
                self.stop(process)

            require(database.is_file() and database.stat().st_size > 0, "SQLite was not persisted")
            with closing(sqlite3.connect(database)) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                require(integrity == ("ok",), "Persisted SQLite failed integrity check")
                count = connection.execute(
                    "SELECT COUNT(*) FROM admin_users WHERE username = ?", (self.username,)
                ).fetchone()
                require(count == (1,), "Administrator did not persist exactly once")
            checks = self.cli("check").get("checks", [])
            by_name = {check.get("key"): check.get("status") for check in checks}
            require(by_name.get("admin_configured") == "pass", "CLI lost persisted administrator")
            require(by_name.get("audit_storage") == "pass", "Persisted audit storage is unhealthy")
            require(not credential.exists(), "Smoke unexpectedly created cloud credentials")
            self.passed("restart_sqlite_integrity_and_cli_checks")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    executable = args.executable.resolve()
    smoke = FrozenSmoke(executable, args.expected_version, args.timeout)
    report: dict[str, Any] = {
        "schema": "mijia-frozen-smoke-v1",
        "expected_version": smoke.expected_version,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "executable": executable.name,
        "sha256": (
            hashlib.sha256(executable.read_bytes()).hexdigest() if executable.is_file() else None
        ),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": smoke.checks,
        "diagnostics": smoke.diagnostics,
        "success": False,
    }
    try:
        smoke.run()
        report["success"] = True
    except SmokeFailure as exc:
        report["error"] = str(exc)
        print(f"FAIL {exc}", file=sys.stderr)
    except Exception as exc:
        # Unexpected exceptions may contain request bodies or secret arguments.
        report["error"] = f"Unexpected {type(exc).__name__} during frozen smoke test"
        smoke.diagnostics["unexpected_exception"] = {
            "type": type(exc).__name__,
            "frames": [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)
            ],
        }
        print(report["error"], file=sys.stderr)
    finally:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
