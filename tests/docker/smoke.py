#!/usr/bin/env python3
"""Exercise an already-built server image with disposable Docker resources.

Run from any directory: python tests/docker/smoke.py --image mijia-server:test
The host needs only Python 3.9+ and the Docker CLI. No Xiaomi credentials are used.
All containers/volumes have a random run prefix and an ownership label; cleanup
never enumerates or removes other Docker resources. The image is never pulled.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from html.parser import HTMLParser
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any, Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
import uuid

OWNER_LABEL = "io.mijia.docker-smoke.run"
FIXTURE_USER = "synthetic-docker-smoke-user"
ADMIN_COOKIE = "mijia_admin_session"
CSRF_COOKIE = "mijia_csrf"

SEED_CREDENTIAL = """
from datetime import datetime, timedelta
from pathlib import Path
from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
FileCredentialStore(Path('/data/credential.json')).save(Credential(
    user_id='synthetic-docker-smoke-user',
    service_token='synthetic-token-never-sent-to-xiaomi',
    ssecurity='AAAAAAAAAAAAAAAAAAAAAA==', pass_token='',
    c_user_id='synthetic-cookie-user', device_id='synthetic-device',
    user_agent='Docker integration smoke',
    expires_at=datetime.now() + timedelta(days=365),
))
"""

READ_CREDENTIAL_METADATA = """
import hashlib, json, stat
from pathlib import Path
credential = Path('/data/credential.json')
key = Path('/data/.credential_key')
envelope = json.loads(credential.read_text())
print(json.dumps({
    'encrypted': envelope.get('alg') == 'aes-256-gcm',
    'key_sha256': hashlib.sha256(key.read_bytes()).hexdigest(),
    'credential_sha256': hashlib.sha256(credential.read_bytes()).hexdigest(),
    'key_mode': stat.S_IMODE(key.stat().st_mode),
    'credential_mode': stat.S_IMODE(credential.stat().st_mode),
}))
"""

BACKUP_DATA = """
from pathlib import Path
import tarfile
root = Path('/source')
for required in ('server/server.sqlite3', 'credential.json', '.credential_key'):
    assert (root / required).is_file(), required
with tarfile.open('/backup/data.tar.gz', 'w:gz') as archive:
    for child in root.iterdir():
        archive.add(child, arcname=child.name)
"""

RESTORE_DATA = """
from pathlib import Path
import tarfile
root = Path('/restore')
assert not any(root.iterdir()), 'restore target must be empty'
with tarfile.open('/backup/data.tar.gz', 'r:gz') as archive:
    archive.extractall(root, filter='data')
for required in ('server/server.sqlite3', 'credential.json', '.credential_key'):
    assert (root / required).is_file(), required
"""


class SmokeError(RuntimeError):
    """A failed integration assertion without secret response bodies."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


@dataclass
class Response:
    status: int
    body: Any
    headers: Any


class BootstrapPage(HTMLParser):
    """Read the app mount point and compiled assets without executing HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.has_app = False
        self.assets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        self.has_app = self.has_app or attributes.get("id") == "app"
        source = attributes.get("src" if tag == "script" else "href")
        if tag not in {"script", "link"} or not source:
            return
        url = urlsplit(source)
        if not url.scheme and not url.netloc and url.path.startswith("/assets/"):
            self.assets.add(url.path + (f"?{url.query}" if url.query else ""))


class HttpClient:
    """Use actual session cookies and CSRF, with no retries on mutations."""

    def __init__(self, base_url: str, timeout: float = 10) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))

    def cookie(self, name: str) -> str:
        return next((item.value for item in self.cookies if item.name == name), "")

    def csrf_headers(self) -> dict[str, str]:
        token = self.cookie(CSRF_COOKIE)
        require(bool(token), "Login did not set a CSRF cookie")
        return {"X-CSRF-Token": token}

    def static(self, path: str) -> Response:
        """Fetch same-origin HTML or bundle bytes, separately from strict JSON APIs."""
        require(
            path.startswith("/") and not path.startswith("//"), "Static path must be same-origin"
        )
        request = Request(self.base_url + path, method="GET")
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            response = exc
        with response:
            return Response(response.status, response.read(), response.headers)

    def request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Response:
        body = json.dumps(payload).encode() if payload is not None else None
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=body, headers=request_headers, method=method)
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            try:
                decoded = json.loads(raw) if raw else None
            except (ValueError, UnicodeDecodeError) as exc:
                raise SmokeError(f"Non-JSON response from {method} {path}") from exc
            return Response(response.status, decoded, response.headers)

    def expect(
        self,
        method: str,
        path: str,
        status: int = 200,
        *,
        payload: Any = None,
        headers: Optional[dict[str, str]] = None,
        error_code: Optional[str] = None,
    ) -> Any:
        response = self.request(method, path, payload, headers)
        code = (
            (response.body.get("error") or {}).get("code")
            if isinstance(response.body, dict)
            else None
        )
        require(
            response.status == status,
            f"{method} {path}: expected HTTP {status}, got {response.status} (code={code})",
        )
        if error_code is not None:
            require(
                code == error_code, f"{method} {path}: expected error code {error_code}, got {code}"
            )
        return response.body


class DockerRun:
    """Track exact resources and verify their ownership before any removal."""

    def __init__(self, image: str, executable: str = "docker", timeout: float = 90) -> None:
        self.image = image
        self.executable = executable
        self.timeout = timeout
        self.run_id = uuid.uuid4().hex
        self.prefix = f"mijia-smoke-{self.run_id}"
        self.resources: dict[str, list[str]] = {"container": [], "volume": []}
        self.image_id = ""

    def command(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [self.executable, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
        )
        if check and result.returncode:
            raise SmokeError(f"Docker {arguments[0]} failed: {result.stderr.strip()}")
        return result

    def inspect(self, kind: str, name: str) -> Optional[dict[str, Any]]:
        result = self.command(kind, "inspect", name, check=False)
        if result.returncode:
            if "no such" in result.stderr.lower():
                return None
            raise SmokeError(f"Docker {kind} inspect failed: {result.stderr.strip()}")
        return json.loads(result.stdout)[0]

    def owned(self, kind: str, name: str) -> dict[str, Any]:
        require(name in self.resources[kind], f"Refusing unregistered {kind}: {name}")
        info = self.inspect(kind, name)
        require(info is not None, f"Missing owned {kind}: {name}")
        labels = (
            (info.get("Config") or {}).get("Labels") if kind == "container" else info.get("Labels")
        )
        require((labels or {}).get(OWNER_LABEL) == self.run_id, f"Refusing foreign {kind}: {name}")
        return info

    def prepare(self) -> None:
        require(
            self.command("info", "--format", "{{.OSType}}").stdout.strip() == "linux",
            "A Linux Docker engine is required",
        )
        image = self.inspect("image", self.image)
        require(image is not None, "Image is unavailable locally; build it before running smoke")
        self.image_id = image["Id"]
        require(bool((image.get("Config") or {}).get("Healthcheck")), "Image has no HEALTHCHECK")

    def volume(self, suffix: str) -> str:
        name = f"{self.prefix}-{suffix}"
        self.resources["volume"].append(name)
        self.command("volume", "create", "--label", f"{OWNER_LABEL}={self.run_id}", name)
        self.owned("volume", name)
        return name

    def start(self, volume: str, *, allow_private: bool = True) -> tuple[str, str]:
        self.owned("volume", volume)
        name = f"{self.prefix}-server-{len(self.resources['container']) + 1}"
        self.resources["container"].append(name)
        self.command(
            "run",
            "--detach",
            "--name",
            name,
            "--label",
            f"{OWNER_LABEL}={self.run_id}",
            "--publish",
            "127.0.0.1::8123",
            "--mount",
            f"type=volume,source={volume},target=/data",
            "--env",
            f"MIJIA_BOOTSTRAP_ALLOW_PRIVATE={int(allow_private)}",
            "--env",
            "MIJIA_CREDENTIAL_SECRET=",
            "--env",
            "MIJIA_SERVER_LOG_LEVEL=WARNING",
            self.image_id,
        )
        self.wait_ready(name)
        uid_probe = (
            "import json; from pathlib import Path; "
            "line = next(line for line in Path('/proc/1/status').read_text().splitlines() "
            "if line.startswith('Uid:')); print(json.dumps([int(uid) for uid in line.split()[1:]]))"
        )
        process_uids = json.loads(self.command("exec", name, "python", "-c", uid_probe).stdout)
        require(
            process_uids == [1000] * 4, "Entrypoint did not drop application privileges to uid 1000"
        )
        client = HttpClient("http://127.0.0.1")
        self.wait_host_ready(name, client)
        return name, client.base_url

    def published_url(self, name: str) -> Optional[str]:
        """Read the current mapping; Docker may allocate a new port after restart."""
        info = self.owned("container", name)
        require(info["State"]["Running"], f"Container exited before host readiness: {name}")
        bindings = info["NetworkSettings"]["Ports"].get("8123/tcp") or []
        if not bindings:
            return None
        require(len(bindings) == 1, "Smoke server must have exactly one host binding")
        binding = bindings[0]
        require(binding["HostIp"] == "127.0.0.1", "Smoke port must only bind host loopback")
        return f"http://127.0.0.1:{binding['HostPort']}"

    def wait_host_ready(self, name: str, client: HttpClient) -> None:
        """Wait using GET only, updating the endpoint while keeping session cookies."""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            url = self.published_url(name)
            if url is not None:
                client.base_url = url
                try:
                    response = client.request("GET", "/api/admin/bootstrap/state")
                except (URLError, OSError):
                    pass
                else:
                    if response.status in (200, 403):
                        return
            time.sleep(0.5)
        raise SmokeError(f"Timed out waiting for host HTTP readiness: {name}")

    def wait_ready(self, name: str, *, healthy: bool = False) -> None:
        deadline = time.monotonic() + self.timeout
        probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8123/healthz', timeout=2).read()"
        while time.monotonic() < deadline:
            info = self.owned("container", name)
            require(info["State"]["Running"], f"Container exited before readiness: {name}")
            ready = (
                (info["State"].get("Health") or {}).get("Status") == "healthy"
                if healthy
                else self.command("exec", name, "python", "-c", probe, check=False).returncode == 0
            )
            if ready:
                return
            time.sleep(0.5)
        raise SmokeError(
            f"Timed out waiting for {'HEALTHCHECK' if healthy else 'HTTP readiness'}: {name}"
        )

    def helper(self, script: str, mounts: dict[str, tuple[str, bool]]) -> str:
        require(bool(mounts), "Helper requires an owned volume mounted at /data")
        mounts = dict(mounts)
        mounts.setdefault("/data", (next(iter(mounts.values()))[0], True))
        name = f"{self.prefix}-helper-{len(self.resources['container']) + 1}"
        self.resources["container"].append(name)
        arguments = [
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            f"{OWNER_LABEL}={self.run_id}",
            "--user",
            "0",
            "--entrypoint",
            "python",
        ]
        for target, (volume, readonly) in mounts.items():
            self.owned("volume", volume)
            arguments.extend(
                [
                    "--mount",
                    f"type=volume,source={volume},target={target}"
                    + (",readonly" if readonly else ""),
                ]
            )
        return self.command(*arguments, self.image_id, "-c", script).stdout

    def private_request(
        self, name: str, volume: str, path: str, method: str = "GET", payload: Any = None
    ) -> Response:
        info = self.owned("container", name)
        address = info["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
        require(bool(address), "Container has no bridge address")
        script = """
import json, urllib.request, urllib.error
request = urllib.request.Request(URL, data=PAYLOAD, method=METHOD,
    headers={'Content-Type': 'application/json'})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    response = opener.open(request, timeout=10)
except urllib.error.HTTPError as exc:
    response = exc
with response:
    print(json.dumps({'status': response.status, 'body': json.load(response)}))
"""
        script = (
            f"URL={f'http://{address}:8123{path}'!r}\nMETHOD={method!r}\nPAYLOAD={json.dumps(payload).encode() if payload is not None else None!r}\n"
            + script
        )
        result = json.loads(self.helper(script, {"/data": (volume, True)}))
        return Response(result["status"], result["body"], {})

    def remove_container(self, name: str) -> None:
        self.owned("container", name)
        self.command("container", "rm", "--force", name)

    def diagnostics(self) -> None:
        for name in self.resources["container"]:
            if self.inspect("container", name) is not None:
                self.owned("container", name)
                result = self.command("logs", "--tail", "60", name, check=False)
                print(
                    f"Container diagnostics: {name}\n{result.stdout}{result.stderr}",
                    file=sys.stderr,
                )

    def cleanup(self) -> list[str]:
        errors = []
        for kind in ("container", "volume"):
            for name in reversed(self.resources[kind]):
                try:
                    if self.inspect(kind, name) is not None:
                        self.owned(kind, name)
                        arguments = ("--force", name) if kind == "container" else (name,)
                        self.command(kind, "rm", *arguments)
                except (SmokeError, OSError, subprocess.TimeoutExpired) as exc:
                    errors.append(str(exc))
        return errors


class Smoke:
    def __init__(self, docker: DockerRun) -> None:
        self.docker = docker
        self.username = "smoke-admin"
        self.password = secrets.token_urlsafe(32)
        self.marker = secrets.token_hex(16)
        self.events: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        print(f"[{name}]", flush=True)
        started = time.monotonic()
        event = {"name": name, "status": "failed"}
        try:
            yield
            event["status"] = "passed"
        finally:
            event["duration_seconds"] = round(time.monotonic() - started, 3)
            self.events.append(event)

    def login(self, client: HttpClient) -> None:
        response = client.request(
            "POST", "/api/admin/auth/login", {"username": self.username, "password": self.password}
        )
        require(response.status == 200, f"Administrator login failed: HTTP {response.status}")
        require(bool(client.cookie(ADMIN_COOKIE)), "Login did not set a session cookie")
        require(bool(client.cookie(CSRF_COOKIE)), "Login did not set a CSRF cookie")
        require(
            any(
                ADMIN_COOKIE in header and "httponly" in header.lower()
                for header in response.headers.get_all("Set-Cookie", [])
            ),
            "Session cookie is not HttpOnly",
        )
        client.expect("GET", "/api/admin/config")

    def check_frontend(self, client: HttpClient) -> None:
        index = client.static("/")
        require(
            index.status == 200 and bool(index.body),
            f"Bootstrap homepage failed: HTTP {index.status}",
        )
        require(
            index.headers.get("Content-Type", "").startswith("text/html"),
            "Bootstrap homepage did not return HTML",
        )
        page = BootstrapPage()
        page.feed(index.body.decode("utf-8"))
        require(page.has_app, "Bootstrap homepage has no app mount point")
        require(
            bool(page.assets) and any(urlsplit(path).path.endswith(".js") for path in page.assets),
            "Bootstrap homepage has no compiled JavaScript asset",
        )
        for path in sorted(page.assets):
            asset = client.static(path)
            require(
                asset.status == 200 and bool(asset.body),
                f"Bootstrap static asset failed: HTTP {asset.status} at {path}",
            )
            require(
                "text/html" not in asset.headers.get("Content-Type", ""),
                f"Bootstrap static asset returned an HTML fallback at {path}",
            )
        self.metadata["bootstrap_frontend_assets_verified"] = len(page.assets)

    def config(self, client: HttpClient) -> dict[str, Any]:
        return {
            item["key"]: item["value"]
            for item in client.expect("GET", "/api/admin/config")["items"]
        }

    def status(self, client: HttpClient, key: str, *, accepted: bool = True) -> None:
        result = client.expect(
            "GET",
            "/api/v1/status",
            200 if accepted else 403,
            headers={"Authorization": f"Bearer {key}"},
            error_code=None if accepted else "API_KEY_FORBIDDEN",
        )
        if accepted:
            require(
                result.get("initialized") is True,
                "Key status did not identify an initialized server",
            )

    def check_persisted(self, client: HttpClient, key: dict[str, Any], rejected: list[str]) -> None:
        require(
            client.expect("GET", "/api/admin/bootstrap/state")["initialized"] is True,
            "Administrator initialization was lost",
        )
        # Reuse the existing Cookie session before issuing a fresh login.
        config = self.config(client)
        require(
            config.get("SMOKE_PERSISTENCE_MARKER") == self.marker, "Runtime configuration was lost"
        )
        require(config.get("ALLOW_LAN_ACCESS") is True, "LAN policy did not persist")
        require(
            not config.get("ALLOW_PUBLIC_ACCESS", False), "Public access was unexpectedly enabled"
        )
        self.login(client)
        listed = client.expect("GET", "/api/admin/api-keys")["items"]
        record = next((item for item in listed if item["id"] == key["id"]), None)
        require(
            record is not None and record["is_active"] is True,
            "Persistent API Key was lost or disabled",
        )
        require(
            record["scopes"] == key["scopes"]
            and record["resource_policy"] == key["resource_policy"],
            "API Key policy did not persist",
        )
        require(
            "key" not in record and key["key"] not in json.dumps(listed),
            "List API leaked a plaintext API Key",
        )
        self.status(client, key["key"])
        for plaintext in rejected:
            self.status(client, plaintext, accepted=False)

    def check_account(self, client: HttpClient, key: str) -> None:
        account = client.expect(
            "GET", "/api/v1/account", headers={"Authorization": f"Bearer {key}"}
        )
        require(
            account.get("exists") is True
            and account.get("valid") is True
            and account.get("user_id") == FIXTURE_USER,
            "Encrypted synthetic credential could not be read through HTTP",
        )

    def denied_bootstrap(self) -> None:
        volume = self.docker.volume("bootstrap-denied")
        container, _ = self.docker.start(volume, allow_private=False)
        for path, method, payload in (
            ("/api/admin/bootstrap/state", "GET", None),
            (
                "/api/admin/bootstrap/admin",
                "POST",
                {"username": "denied-admin", "password": "synthetic-denied-password"},
            ),
        ):
            response = self.docker.private_request(container, volume, path, method, payload)
            require(
                response.status == 403
                and response.body["error"]["code"] == "NETWORK_ACCESS_DENIED",
                f"Flag 0 unexpectedly permitted private {path}",
            )
        self.docker.remove_container(container)

    def bootstrap(self, container: str, volume: str, client: HttpClient) -> None:
        for path in ("/healthz", "/api/admin/api-keys", "/api/v1/status"):
            response = self.docker.private_request(container, volume, path)
            require(
                response.status == 403
                and response.body["error"]["code"] == "NETWORK_ACCESS_DENIED",
                f"Initial LAN policy unexpectedly permitted {path}",
            )
        self.check_frontend(client)
        require(
            client.expect("GET", "/api/admin/bootstrap/state")["initialized"] is False,
            "Fresh test volume already contains an administrator",
        )
        client.expect(
            "POST",
            "/api/admin/bootstrap/admin",
            201,
            payload={"username": self.username, "password": self.password},
        )
        self.login(client)
        config = self.config(client)
        require(
            config.get("ALLOW_LAN_ACCESS") is True,
            "Private bootstrap did not atomically enable LAN for subsequent login",
        )
        require(not config.get("ALLOW_PUBLIC_ACCESS", False), "Bootstrap enabled public access")
        client.expect(
            "POST",
            "/api/admin/bootstrap/admin",
            409,
            payload={"username": "second-admin", "password": "synthetic-second-password"},
            error_code="BOOTSTRAP_ALREADY_COMPLETED",
        )
        client.expect(
            "PUT",
            "/api/admin/config/SMOKE_PERSISTENCE_MARKER",
            403,
            payload={"value": self.marker},
            error_code="CSRF_FAILED",
        )
        client.expect(
            "PUT",
            "/api/admin/config/SMOKE_PERSISTENCE_MARKER",
            payload={"value": self.marker},
            headers=client.csrf_headers(),
        )

    def key_lifecycle(self, client: HttpClient) -> tuple[dict[str, Any], list[str]]:
        payload = {
            "name": "docker-smoke-reader",
            "scopes": ["read:status"],
            "resource_policy": {"devices": ["synthetic-device"]},
        }
        client.expect("POST", "/api/admin/api-keys", 403, payload=payload, error_code="CSRF_FAILED")
        old = client.expect(
            "POST", "/api/admin/api-keys", 201, payload=payload, headers=client.csrf_headers()
        )
        self.status(client, old["key"])
        client.expect(
            "GET",
            "/api/v1/devices",
            403,
            headers={"Authorization": f"Bearer {old['key']}"},
            error_code="API_KEY_FORBIDDEN",
        )
        self.status(client, "mk_live_invalid-synthetic-smoke-key", accepted=False)
        for enabled in (False, True):
            client.expect(
                "PATCH",
                f"/api/admin/api-keys/{old['id']}",
                payload={"is_active": enabled},
                headers=client.csrf_headers(),
            )
            self.status(client, old["key"], accepted=enabled)
        replacement = client.expect(
            "POST", f"/api/admin/api-keys/{old['id']}/rotate", 201, headers=client.csrf_headers()
        )
        require(
            replacement["id"] != old["id"] and replacement["key"] != old["key"],
            "Rotation did not issue a new key",
        )
        require(
            replacement["scopes"] == old["scopes"]
            and replacement["resource_policy"] == old["resource_policy"],
            "Rotation changed key policy",
        )
        self.status(client, old["key"], accepted=False)
        self.status(client, replacement["key"])
        revoked = client.expect(
            "POST",
            "/api/admin/api-keys",
            201,
            payload={"name": "docker-smoke-revoked", "scopes": ["read:status"]},
            headers=client.csrf_headers(),
        )
        self.status(client, revoked["key"])
        client.expect(
            "DELETE", f"/api/admin/api-keys/{revoked['id']}", 204, headers=client.csrf_headers()
        )
        self.status(client, revoked["key"], accepted=False)
        return replacement, [old["key"], revoked["key"]]

    def execute(self) -> None:
        with self.phase("image-and-engine"):
            self.docker.prepare()
        with self.phase("private-bootstrap-disabled"):
            self.denied_bootstrap()
        volume = self.docker.volume("data")
        with self.phase("host-http-bootstrap-cookie-csrf"):
            container, url = self.docker.start(volume)
            client = HttpClient(url)
            self.bootstrap(container, volume, client)
        with self.phase("api-key-lifecycle"):
            key, rejected = self.key_lifecycle(client)
            self.check_persisted(client, key, rejected)
        with self.phase("encrypted-credential-fixture"):
            self.docker.command(
                "exec", "--user", "1000:1000", container, "python", "-c", SEED_CREDENTIAL
            )
            metadata = json.loads(
                self.docker.command(
                    "exec", container, "python", "-c", READ_CREDENTIAL_METADATA
                ).stdout
            )
            require(
                metadata["encrypted"]
                and metadata["key_mode"] == 0o600
                and metadata["credential_mode"] == 0o600,
                "Credential/keypair is not encrypted with private permissions",
            )
            self.check_account(client, key["key"])
        with self.phase("container-restart-persistence"):
            self.docker.command("restart", "--time", "10", container)
            self.docker.wait_ready(container)
            self.docker.wait_host_ready(container, client)
            self.check_persisted(client, key, rejected)
            self.check_account(client, key["key"])
        with self.phase("container-recreate-persistence"):
            self.docker.remove_container(container)
            container, client.base_url = self.docker.start(volume, allow_private=False)
            self.check_persisted(client, key, rejected)
            self.check_account(client, key["key"])
        with self.phase("stopped-data-keypair-backup-and-restore"):
            self.docker.command("stop", "--time", "10", container)
            backup = self.docker.volume("backup")
            restored = self.docker.volume("restored")
            self.docker.helper(BACKUP_DATA, {"/source": (volume, True), "/backup": (backup, False)})
            self.docker.helper(
                RESTORE_DATA, {"/backup": (backup, True), "/restore": (restored, False)}
            )
            container, client.base_url = self.docker.start(restored)
            restored_metadata = json.loads(
                self.docker.command(
                    "exec", container, "python", "-c", READ_CREDENTIAL_METADATA
                ).stdout
            )
            require(
                restored_metadata == metadata,
                "Backup did not preserve encrypted credential/keypair and permissions",
            )
            self.check_persisted(client, key, rejected)
            self.check_account(client, key["key"])
            self.metadata["backup_restored_encrypted_credential_and_key"] = True
        with self.phase("restored-image-healthcheck-and-session-logout"):
            self.docker.wait_ready(container, healthy=True)
            client.expect("POST", "/api/admin/auth/logout", headers=client.csrf_headers())
            require(
                not client.cookie(ADMIN_COOKIE) and not client.cookie(CSRF_COOKIE),
                "Logout did not clear session and CSRF cookies",
            )
            client.expect("GET", "/api/admin/config", 401)
            self.status(client, key["key"])
        with self.phase("initialized-private-bootstrap-flag-does-not-bypass-disabled-lan"):
            self.login(client)
            client.expect(
                "PUT",
                "/api/admin/config/ALLOW_LAN_ACCESS",
                payload={"value": False},
                headers=client.csrf_headers(),
            )
            for path, method, payload in (
                ("/api/admin/bootstrap/state", "GET", None),
                (
                    "/api/admin/bootstrap/admin",
                    "POST",
                    {"username": "denied-admin", "password": "synthetic-denied-password"},
                ),
                ("/api/v1/status", "GET", None),
            ):
                response = self.docker.private_request(container, restored, path, method, payload)
                require(
                    response.status == 403
                    and response.body["error"]["code"] == "NETWORK_ACCESS_DENIED",
                    f"Initialized instance bypassed disabled LAN policy at {path}",
                )


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Already-built local Docker image/tag/id")
    parser.add_argument("--docker", default="docker", help="Docker CLI executable")
    parser.add_argument(
        "--timeout", type=float, default=90, help="Readiness and command timeout, seconds"
    )
    parser.add_argument(
        "--report", type=Path, help="Write a secret-free JSON result even on failure"
    )
    args = parser.parse_args(argv)
    require(args.timeout > 0, "Timeout must be positive")
    docker = DockerRun(args.image, args.docker, args.timeout)
    smoke = Smoke(docker)
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": docker.run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "image": args.image,
        "status": "failed",
    }
    started = time.monotonic()
    result = 1
    try:
        smoke.execute()
        report["status"] = "passed"
        result = 0
    except (SmokeError, OSError, ValueError, URLError, subprocess.TimeoutExpired) as exc:
        report["error"] = str(exc)
        print(f"Docker smoke FAILED: {exc}", file=sys.stderr, flush=True)
        try:
            docker.diagnostics()
        except (SmokeError, OSError, subprocess.TimeoutExpired) as diagnostic_error:
            print(f"Diagnostics unavailable: {diagnostic_error}", file=sys.stderr)
    except KeyboardInterrupt:
        report["error"] = "Interrupted"
        result = 130
    finally:
        cleanup_errors = docker.cleanup()
        report.update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(time.monotonic() - started, 3),
                "image_id": docker.image_id,
                "checks": smoke.events,
                "evidence": smoke.metadata,
                "resources": docker.resources,
                "cleanup_errors": cleanup_errors,
            }
        )
        if cleanup_errors:
            result = 1
            report["status"] = "failed"
            print("Cleanup failed: " + "; ".join(cleanup_errors), file=sys.stderr)
        if args.report:
            write_report(args.report, report)
    if result == 0:
        print("Docker smoke PASSED; all disposable containers and volumes removed", flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
