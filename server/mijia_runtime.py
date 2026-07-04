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


@dataclass
class SyncProgress:
    """In-memory state for sync progress tracking."""

    task_id: str
    status: str = "idle"  # idle, running, completed, failed
    step: str = ""
    step_number: int = 0
    total_steps: int = 8
    progress: float = 0.0
    current_home: str = ""
    homes_total: int = 0
    homes_processed: int = 0
    devices_found: int = 0
    scenes_found: int = 0
    warnings: list = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "step": self.step,
            "step_number": self.step_number,
            "total_steps": self.total_steps,
            "progress": self.progress,
            "current_home": self.current_home,
            "homes_total": self.homes_total,
            "homes_processed": self.homes_processed,
            "devices_found": self.devices_found,
            "scenes_found": self.scenes_found,
            "warnings": self.warnings,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
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


class SyncInProgressError(RuntimeError):
    """Raised when a new sync is requested while another sync is running."""


class MijiaRuntime:
    """Runtime helper that loads credentials and calls the SDK."""

    def __init__(self, settings: ServerSettings, store: ServerStore):
        self._settings = settings
        self._store = store
        self._credential_lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._sync_progress: Optional[SyncProgress] = None
        self._refresh_timer: Optional[threading.Timer] = None
        self._refresh_interval = 6 * 60 * 60  # 每 6 小时检查一次

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
        credential = self._load_required_credential()
        self._refresh_credential(credential)
        return self.credential_status()

    def _refresh_credential(self, credential: Credential) -> Credential:
        auth = create_auth_service(
            credential_store=FileCredentialStore(self._settings.credential_path)
        )
        refreshed = auth.refresh_credential(credential)
        auth.save_credential(refreshed)
        return refreshed

    def delete_credential(self) -> None:
        FileCredentialStore(self._settings.credential_path).delete()

    def start_credential_refresh_timer(self) -> None:
        """启动定时刷新凭据的后台任务"""
        if self._refresh_timer is not None:
            return
        self._refresh_timer = threading.Timer(
            self._refresh_interval, self._credential_refresh_job
        )
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def stop_credential_refresh_timer(self) -> None:
        """停止定时刷新凭据的后台任务"""
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
            self._refresh_timer = None

    def _credential_refresh_job(self) -> None:
        """定时刷新凭据的任务"""
        try:
            credential = self.load_credential()
            if credential is None:
                return
            # 如果凭据即将过期（剩余时间 < 24小时），自动刷新
            if credential.is_valid() and credential.expires_in() < self._settings.credential_refresh_before_seconds:
                self._refresh_credential(credential)
        except Exception:
            pass  # 静默处理，不影响服务
        finally:
            # 重新启动定时器
            self.start_credential_refresh_timer()

    def sync_all(self) -> dict[str, Any]:
        if not self._sync_lock.acquire(blocking=False):
            raise SyncInProgressError("同步正在进行中，请稍后再试")
        try:
            return self._sync_all_unlocked()
        finally:
            self._sync_lock.release()

    def get_sync_progress(self) -> Optional[dict[str, Any]]:
        """Get current sync progress."""
        if self._sync_progress is None:
            return None
        return self._sync_progress.as_dict()

    def _sync_all_unlocked(self) -> dict[str, Any]:
        # Initialize progress
        self._sync_progress = SyncProgress(
            task_id=str(uuid.uuid4()),
            status="running",
            step="初始化",
            started_at=isoformat(utc_now()),
        )
        
        try:
            # Step 1: Initialize
            self._update_progress(step="初始化同步任务", progress=0)
            
            # Step 2: Get homes
            self._update_progress(step="获取家庭列表", progress=5)
            api = self._api()
            homes = api.get_homes()
            
            # Step 3: Save homes
            self._update_progress(step="保存家庭数据", progress=10, homes_total=len(homes))
            home_dicts = [model_to_dict(home) for home in homes]
            self._store.replace_home_registry(home_dicts)

            devices: list[dict[str, Any]] = []
            scenes: list[dict[str, Any]] = []
            warnings: list[dict[str, str]] = []
            
            # Step 4-6: Process each home
            for i, home in enumerate(homes):
                # Update progress
                progress = 10 + (i / len(homes)) * 50  # 10% - 60%
                self._update_progress(
                    step=f"处理家庭 {i+1}/{len(homes)}",
                    progress=progress,
                    current_home=str(home.name),
                    homes_processed=i,
                )
                
                # Get devices
                try:
                    devices.extend(self._device_dicts(api, home))
                    self._update_progress(devices_found=len(devices))
                except Exception as exc:
                    warnings.append(self._sync_warning("devices", home, exc))
                
                # Get scenes
                try:
                    scenes.extend(self._scene_dicts(api, home))
                    self._update_progress(scenes_found=len(scenes))
                except Exception as exc:
                    warnings.append(self._sync_warning("scenes", home, exc))
            
            # Step 7: Save devices
            self._update_progress(step="保存设备数据", progress=90)
            self._store.upsert_devices(devices)
            
            # Step 8: Save scenes
            self._update_progress(step="保存场景数据", progress=95)
            self._store.upsert_scenes(scenes)
            
            # Complete
            self._update_progress(
                status="completed",
                step="同步完成",
                progress=100,
                completed_at=isoformat(utc_now()),
                warnings=warnings,
            )
            
            return {
                "homes": len(home_dicts),
                "devices": len(devices),
                "scenes": len(scenes),
                "warnings": warnings,
            }
            
        except Exception as e:
            self._update_progress(
                status="failed",
                error=str(e),
                completed_at=isoformat(utc_now()),
            )
            raise
        finally:
            # Cleanup: delay cleanup to let frontend get final state
            def cleanup_progress():
                import time
                time.sleep(5)  # 5 seconds delay
                self._sync_progress = None
            
            threading.Thread(target=cleanup_progress, daemon=True).start()

    def _update_progress(self, **kwargs) -> None:
        """Update sync progress."""
        if self._sync_progress is None:
            return
        
        for key, value in kwargs.items():
            if hasattr(self._sync_progress, key):
                setattr(self._sync_progress, key, value)
        
        self._sync_progress.updated_at = isoformat(utc_now())

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
        credential = self._load_required_credential()
        if credential.expires_in() > self._settings.credential_refresh_before_seconds:
            return credential
        with self._credential_lock:
            credential = self._load_required_credential()
            if credential.expires_in() > self._settings.credential_refresh_before_seconds:
                return credential
            try:
                return self._refresh_credential(credential)
            except Exception as exc:
                if credential.is_valid():
                    return credential
                raise RuntimeError(f"米家凭据已过期且自动刷新失败：{exc}") from exc

    def _load_required_credential(self) -> Credential:
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
        for scene in api.get_scenes(home.id, owner_uid=home.uid):
            payload = model_to_dict(scene)
            payload["id"] = str(uuid.uuid4())
            scenes.append(payload)
        return scenes

    def _sync_warning(self, kind: str, home: Home, exc: Exception) -> dict[str, str]:
        return {
            "kind": kind,
            "home_id": str(home.id),
            "home_name": str(home.name),
            "message": str(exc),
        }

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
