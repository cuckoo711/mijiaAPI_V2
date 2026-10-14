"""Offline acceptance of the packaged native dependencies and real HTTP server.

Only call from the debug instrumentation runner on a disposable device.
No Xiaomi credentials or physical actions are used.
"""

import base64
import hashlib
import json
from pathlib import Path
import platform
import re
import secrets
import struct


def run(data_dir):
    import httpx
    import mijiaAPI_V2
    import pydantic_core
    from Crypto.Cipher import AES
    from pydantic import BaseModel
    from server.mijia_runtime import render_qr_data_url
    from server.store import ServerStore
    from mijia_android.runtime import settings_for

    checks = []
    cipher = AES.new(secrets.token_bytes(32), AES.MODE_GCM)
    plaintext = b"android-native-compatibility"
    encrypted, tag = cipher.encrypt_and_digest(plaintext)
    assert encrypted != plaintext and len(tag) == 16

    class Probe(BaseModel):
        value: int

    assert Probe(value="7").value == 7
    checks.append("native_aes_and_pydantic")
    png = render_qr_data_url("https://account.xiaomi.com/android-smoke-only")
    assert base64.b64decode(png.split(",", 1)[1]).startswith(b"\x89PNG\r\n\x1a\n")
    checks.append("qr_png_without_pillow")
    client = httpx.Client(base_url="http://127.0.0.1:8123", timeout=10)
    with client:
        assert client.get("/healthz").json()["version"] == mijiaAPI_V2.__version__
        ready = client.get("/readyz").json()
        assert ready["status"] == "ready" and all(ready["checks"].values())
        checks.append("real_http_health_readiness")
        html = client.get("/").text
        assets = set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', html))
        assert assets
        for asset in assets:
            assert client.get(asset).status_code == 200
        checks.append("bundled_frontend_assets")
        assert not client.get("/api/admin/bootstrap/state").json()[
            "initialized"
        ], "Use a fresh disposable device"
        password = secrets.token_urlsafe(24)
        response = client.post(
            "/api/admin/bootstrap/admin", json={"username": "android-smoke", "password": password}
        )
        assert response.status_code == 201
        login = client.post(
            "/api/admin/auth/login", json={"username": "android-smoke", "password": password}
        )
        assert login.status_code == 200
        token = login.json()["token"]
        client.cookies.clear()
        admin = {"Authorization": "Bearer " + token}
        assert client.get("/api/admin/devices").status_code == 401
        checks.append("bootstrap_login_and_authentication")
        key = client.post(
            "/api/admin/api-keys",
            headers=admin,
            json={"name": "android-smoke", "scopes": ["read:devices"]},
        )
        assert key.status_code == 201
        api = {"Authorization": "Bearer " + key.json()["key"]}
        assert client.get("/api/v1/devices", headers=api).status_code == 200
        assert client.get("/api/v1/logs", headers=api).status_code == 403
        assert (
            client.patch(
                "/api/admin/api-keys/" + key.json()["id"], headers=admin, json={"is_active": False}
            ).status_code
            == 200
        )
        assert client.get("/api/v1/devices", headers=api).status_code == 401
        checks.append("api_key_scopes_and_revocation")
    store = ServerStore(settings_for(data_dir))
    store.set_config("ANDROID_SMOKE_MARKER", "persisted", source="android-smoke")
    result = {
        "passed": True,
        "version": mijiaAPI_V2.__version__,
        "bits": struct.calcsize("P") * 8,
        "machine": platform.machine(),
        "pydantic_core": pydantic_core.__version__,
        "checks": checks,
        "cloud_device_acceptance": False,
    }
    path = Path(data_dir) / "android-smoke.json"
    path.write_text(json.dumps(result, indent=2))
    return json.dumps(result)


def verify_restart(data_dir):
    from server.store import ServerStore
    from mijia_android.runtime import settings_for

    store = ServerStore(settings_for(data_dir))
    assert store.has_admin()
    assert store.get_config_map()["ANDROID_SMOKE_MARKER"] == "persisted"
    assert len(store.list_api_keys()) == 1
    result = {"passed": True, "admin_and_api_key_persisted": True, "config_persisted": True}
    (Path(data_dir) / "android-restart-smoke.json").write_text(json.dumps(result, indent=2))
    return json.dumps(result)
