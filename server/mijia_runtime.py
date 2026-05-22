"""Bridge between the FastAPI server and the core Mijia SDK."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from mijiaAPI_V2 import create_api_client, create_auth_service
from mijiaAPI_V2.core.config import ConfigManager
from mijiaAPI_V2.domain.models import Credential, Device, Home
from mijiaAPI_V2.infrastructure.credential_provider import CredentialProvider
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from server.config import ServerSettings
from server.store import ServerStore, isoformat, utc_now


def model_to_dict(value: Any) -> dict[str, Any]:
    """Convert Pydantic models or plain objects to dictionaries."""

    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return dict(value)


@dataclass
class LoginJob:
    """In-memory state for a QR login session."""

    id: str
    qr_url: str
    login_url: str
    poll_url: str
    status: str = "pending"
    message: str = "等待扫码"
    created_at: str = field(default_factory=lambda: isoformat(utc_now()))
    completed_at: Optional[str] = None
    user_id: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "qr_url": self.qr_url,
            "login_url": self.login_url,
            "poll_url": self.poll_url,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "user_id": self.user_id,
        }


class LoginJobManager:
    """Create and track QR login sessions for the web UI."""

    def __init__(self, settings: ServerSettings):
        self._settings = settings
        self._jobs: dict[str, LoginJob] = {}
        self._lock = threading.Lock()

    def start(self) -> dict[str, Any]:
        provider = CredentialProvider(ConfigManager())
        location_data = provider._get_location()
        if location_data.get("code") == 0:
            raise RuntimeError("已有有效登录态，请加载已保存凭据")
        qr_data = provider._get_qrcode_data(location_data)
        job = LoginJob(
            id=str(uuid.uuid4()),
            qr_url=str(qr_data["qr"]),
            login_url=str(qr_data["loginUrl"]),
            poll_url=str(qr_data["lp"]),
        )
        with self._lock:
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._wait_and_save,
            args=(provider, job.id),
            daemon=True,
        )
        thread.start()
        return job.as_dict()

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Login job not found: {job_id}")
            return job.as_dict()

    def _wait_and_save(self, provider: CredentialProvider, job_id: str) -> None:
        try:
            with self._lock:
                job = self._jobs[job_id]
                job.status = "scanning"
                job.message = "二维码已生成，等待确认"

            result = provider._long_poll_for_scan(self._jobs[job_id].poll_url)
            callback_response = provider._client.get(result["location"])
            service_token = callback_response.cookies.get("serviceToken")
            if not service_token:
                raise RuntimeError("未能从登录回调获取 serviceToken")

            credential = Credential(
                user_id=str(result["userId"]),
                service_token=service_token,
                ssecurity=str(result["ssecurity"]),
                pass_token=str(result.get("passToken", "")),
                c_user_id=str(result.get("cUserId", result["userId"])),
                device_id=provider._generate_device_id(),
                user_agent=provider._generate_user_agent(),
                expires_at=provider._calculate_expires_at({}),
            )
            FileCredentialStore(self._settings.credential_path).save(credential)
            with self._lock:
                job = self._jobs[job_id]
                job.status = "success"
                job.message = "登录成功"
                job.completed_at = datetime.now(timezone.utc).isoformat()
                job.user_id = credential.user_id
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.message = str(exc)
                job.completed_at = datetime.now(timezone.utc).isoformat()


class MijiaRuntime:
    """Runtime helper that loads credentials and calls the SDK."""

    def __init__(self, settings: ServerSettings, store: ServerStore):
        self._settings = settings
        self._store = store

    def load_credential(self) -> Optional[Credential]:
        return FileCredentialStore(self._settings.credential_path).load()

    def credential_status(self) -> dict[str, Any]:
        credential = self.load_credential()
        if credential is None:
            return {"exists": False, "valid": False}
        return {
            "exists": True,
            "valid": credential.is_valid(),
            "user_id": credential.user_id,
            "expires_at": credential.expires_at.isoformat(),
            "expires_in": credential.expires_in(),
        }

    def refresh_credential(self) -> dict[str, Any]:
        credential = self._require_credential()
        auth = create_auth_service(
            credential_store=FileCredentialStore(self._settings.credential_path)
        )
        refreshed = auth.refresh_credential(credential)
        auth.save_credential(refreshed)
        return self.credential_status()

    def delete_credential(self) -> None:
        FileCredentialStore(self._settings.credential_path).delete()

    def sync_all(self) -> dict[str, Any]:
        api = self._api()
        homes = api.get_homes()
        home_dicts = [model_to_dict(home) for home in homes]
        self._store.replace_home_registry(home_dicts)

        devices: list[dict[str, Any]] = []
        scenes: list[dict[str, Any]] = []
        for home in homes:
            devices.extend(self._device_dicts(api, home))
            scenes.extend(self._scene_dicts(api, home))
        self._store.upsert_devices(devices)
        self._store.upsert_scenes(scenes)
        return {
            "homes": len(home_dicts),
            "devices": len(devices),
            "scenes": len(scenes),
        }

    def get_device_state(self, device_slug: str) -> list[dict[str, Any]]:
        device = self._store.get_device(device_slug)
        api = self._api()
        spec = device.get("spec") or self.get_device_spec(device_slug)
        requests = self._readable_property_requests(device["did"], spec)
        if not requests:
            return []
        return api.get_device_properties(requests)

    def set_device_property(
        self, device_slug: str, siid: int, piid: int, value: Any
    ) -> dict[str, Any]:
        device = self._store.get_device(device_slug)
        if device["access_mode"] != "write":
            raise PermissionError("设备未授权控制")
        success = self._api().control_device(device["did"], siid, piid, value)
        return {"success": bool(success)}

    def call_device_action(
        self, device_slug: str, siid: int, aiid: int, params: Optional[dict[str, Any]]
    ) -> dict[str, Any]:
        device = self._store.get_device(device_slug)
        if device["access_mode"] != "write":
            raise PermissionError("设备未授权控制")
        result = self._api().call_device_action(device["did"], siid, aiid, params or {})
        return {"result": result}

    def batch_set_properties(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        api_requests = []
        for request in requests:
            device = self._store.get_device(str(request["device"]))
            if device["access_mode"] != "write":
                raise PermissionError(f"设备未授权控制: {device['slug']}")
            api_requests.append(
                {
                    "device_id": device["did"],
                    "siid": request["siid"],
                    "piid": request["piid"],
                    "value": request["value"],
                }
            )
        return {"items": self._api().batch_control_devices(api_requests)}

    def get_device_spec(self, device_slug: str) -> dict[str, Any] | None:
        device = self._store.get_device(device_slug)
        spec = self._api().get_device_spec(device["model"])
        if spec is None:
            return None
        return model_to_dict(spec)

    def execute_scene(self, scene_id: str) -> dict[str, Any]:
        scene = self._store.get_scene(scene_id)
        if not scene["executable"]:
            raise PermissionError("场景未授权执行")
        success = self._api().execute_scene(scene["scene_id"], scene["home_id"])
        return {"success": bool(success)}

    def refresh_cache(self, home_id: Optional[str] = None) -> None:
        self._api().refresh_cache(home_id=home_id)

    def clear_sdk_cache(self) -> None:
        self._api().clear_all_cache()

    def _require_credential(self) -> Credential:
        credential = self.load_credential()
        if credential is None:
            raise RuntimeError("米家凭据不存在，请先扫码登录")
        return credential

    def _api(self) -> Any:
        credential = self._require_credential()
        return create_api_client(credential, cache_dir=self._settings.data_dir / "cache")

    def _device_dicts(self, api: Any, home: Home) -> list[dict[str, Any]]:
        devices = []
        for device in api.get_devices(home.id):
            payload = model_to_dict(device)
            payload["id"] = str(uuid.uuid4())
            payload["status"] = str(payload.get("status", "unknown")).split(".")[-1]
            payload["spec"] = self._safe_spec(api, device)
            devices.append(payload)
        return devices

    def _scene_dicts(self, api: Any, home: Home) -> list[dict[str, Any]]:
        scenes = []
        for scene in api.get_scenes(home.id):
            payload = model_to_dict(scene)
            payload["id"] = str(uuid.uuid4())
            scenes.append(payload)
        return scenes

    def _safe_spec(self, api: Any, device: Device) -> dict[str, Any] | None:
        try:
            spec = api.get_device_spec(device.model)
            return model_to_dict(spec) if spec is not None else None
        except Exception:
            return None

    def _readable_property_requests(
        self, did: str, spec: Optional[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not spec:
            return []
        properties = spec.get("properties") or []
        requests = []
        for prop in properties[:30]:
            access = str(prop.get("access", ""))
            if "read" in access:
                requests.append({"did": did, "siid": prop["siid"], "piid": prop["piid"]})
        return requests
