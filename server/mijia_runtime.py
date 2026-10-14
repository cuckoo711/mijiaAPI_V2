"""Bridge between the FastAPI server and the core Mijia SDK."""

from __future__ import annotations

import base64
import io
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import qrcode
from mijiaAPI_V2 import create_api_client, create_auth_service
from mijiaAPI_V2.core.config import ConfigManager
from mijiaAPI_V2.domain.models import Credential, Device, Home
from mijiaAPI_V2.infrastructure.credential_provider import CredentialProvider
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore
from server.config import ServerSettings
from server.logging_utils import get_server_logger
from server.store import ServerStore, isoformat, utc_now

logger = get_server_logger(__name__)


def model_to_dict(value: Any) -> dict[str, Any]:
    """Convert Pydantic models or plain objects to dictionaries."""

    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return dict(value)


def render_qr_data_url(content: str, *, box_size: int = 6, border: int = 2) -> str:
    """Render ``content`` as a PNG data URL for the admin UI.

    The browser must not fetch Xiaomi's ``qr`` image URL directly — CSP and
    cross-origin restrictions routinely break ``<img src="https://account.xiaomi.com/...">``.
    Generating the QR locally from ``loginUrl`` matches the CLI path and stays same-origin.
    """

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(content)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@dataclass
class LoginJob:
    """In-memory state for a QR login session."""

    id: str
    qr_url: str
    login_url: str
    poll_url: str
    qr_image: str = ""
    status: str = "pending"
    message: str = "等待扫码"
    created_at: str = field(default_factory=lambda: isoformat(utc_now()))
    completed_at: Optional[str] = None
    user_id: Optional[str] = None
    attempt: tuple[int, int] = (0, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "qr_url": self.qr_url,
            "qr_image": self.qr_image,
            "login_url": self.login_url,
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


class AccountChangedError(RuntimeError):
    """An operation belongs to a removed or superseded account session."""


class LoginJobManager:
    """Create and track QR login sessions for the web UI."""

    def __init__(self, settings: ServerSettings, runtime: MijiaRuntime):
        self._settings = settings
        self._runtime = runtime
        self._jobs: dict[str, LoginJob] = {}
        self._lock = threading.Lock()
        runtime.register_login_canceller(self.cancel_pending)

    def cancel_pending(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                if job.status in {"pending", "scanning"}:
                    job.status = "canceled"
                    job.message = "登录任务已取消，请重新扫码"
                    job.completed_at = isoformat(utc_now())

    def start(self) -> dict[str, Any]:
        attempt = self._runtime.begin_login_attempt()
        provider = CredentialProvider(ConfigManager())
        try:
            location_data = provider._get_location()
            if location_data.get("code") == 0:
                raise RuntimeError("已有有效登录态，请加载已保存凭据")
            qr_data = provider._get_qrcode_data(location_data)
            login_url = str(qr_data["loginUrl"])
            job = LoginJob(
                id=str(uuid.uuid4()),
                qr_url=str(qr_data["qr"]),
                login_url=login_url,
                poll_url=str(qr_data["lp"]),
                qr_image=render_qr_data_url(login_url),
                attempt=attempt,
            )
        except Exception:
            provider._client.close()
            raise
        with self._lock:
            self._jobs[job.id] = job

        if not self._runtime.is_current_login_attempt(attempt):
            with self._lock:
                job.status = "canceled"
                job.message = "登录任务已取消，请重新扫码"
                job.completed_at = isoformat(utc_now())
            provider._client.close()
            return job.as_dict()

        thread = threading.Thread(
            target=self._wait_and_save,
            args=(provider, job.id),
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            provider._client.close()
            with self._lock:
                job.status = "failed"
                job.message = "无法启动登录任务，请重试"
                job.completed_at = isoformat(utc_now())
            raise
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
                if job.status == "canceled":
                    return
                job.status = "scanning"
                job.message = "二维码已生成，等待确认"
                attempt = job.attempt
                poll_url = job.poll_url

            result = provider._long_poll_for_scan(poll_url)
            if not self._runtime.is_current_login_attempt(attempt):
                raise AccountChangedError("登录任务已取消，请重新扫码")
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
            self._runtime.commit_login_credential(credential, attempt)
            with self._lock:
                job = self._jobs[job_id]
                if job.status == "canceled":
                    return
                job.status = "success"
                job.message = "登录成功"
                job.completed_at = datetime.now(timezone.utc).isoformat()
                job.user_id = credential.user_id
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                if job.status == "canceled":
                    return
                job.status = "canceled" if isinstance(exc, AccountChangedError) else "failed"
                job.message = (
                    "登录任务已取消，请重新扫码"
                    if isinstance(exc, AccountChangedError)
                    else "米家登录失败，请重新扫码或稍后重试"
                )
                job.completed_at = datetime.now(timezone.utc).isoformat()
        finally:
            provider._client.close()


class SyncInProgressError(RuntimeError):
    """Raised when a new sync is requested while another sync is running."""


class MijiaRuntime:
    """Runtime helper that loads credentials and calls the SDK."""

    def __init__(self, settings: ServerSettings, store: ServerStore):
        self._settings = settings
        self._store = store
        self._credential_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._account_generation = 0
        self._login_sequence = 0
        self._login_canceller: Optional[Callable[[], None]] = None
        self._sync_lock = threading.Lock()
        self._sync_progress: Optional[SyncProgress] = None
        self._progress_cleanup_delay_seconds = 5.0
        self._refresh_timer: Optional[threading.Timer] = None
        self._refresh_timer_lock = threading.Lock()
        self._refresh_timer_enabled = False
        self._refresh_timer_generation = 0
        self._refresh_interval = 24 * 60 * 60  # 每 24 小时检查一次
        # 复用同一个 MijiaAPI，避免每次请求重建 HttpClient / CacheManager 导致 L1 缓存永远失效。
        self._api_client: Optional[Any] = None
        self._api_client_credential_id: Optional[str] = None
        self._api_lock = threading.Lock()

    def load_credential(self) -> Optional[Credential]:
        with self._credential_lock:
            return FileCredentialStore(self._settings.credential_path).load()

    def register_login_canceller(self, callback: Callable[[], None]) -> None:
        self._login_canceller = callback

    def begin_login_attempt(self) -> tuple[int, int]:
        with self._credential_lock:
            self._login_sequence += 1
            if self._login_canceller is not None:
                self._login_canceller()
            return self._account_generation, self._login_sequence

    def is_current_login_attempt(self, attempt: tuple[int, int]) -> bool:
        with self._credential_lock:
            return attempt == (self._account_generation, self._login_sequence)

    def _check_account_generation(self, generation: int) -> None:
        if generation != self._account_generation:
            raise AccountChangedError("米家账号已移除或重新登录，旧任务结果已丢弃")

    def commit_login_credential(self, credential: Credential, attempt: tuple[int, int]) -> None:
        with self._credential_lock:
            if not self.is_current_login_attempt(attempt):
                raise AccountChangedError("登录任务已取消，请重新扫码")
            previous = self.load_credential()
            self._account_generation += 1
            old_api = self._detach_api_client()
            if previous is None or previous.user_id != credential.user_id:
                # Fail closed if registry cleanup or credential persistence fails.
                FileCredentialStore(self._settings.credential_path).delete()
                self._store.clear_synced_registries()
            FileCredentialStore(self._settings.credential_path).save(credential)
        self._clear_detached_cache(old_api)

    def credential_status(self) -> dict[str, Any]:
        credential = self.load_credential()
        if credential is None:
            return {"exists": False, "valid": False}

        expires_in_seconds = credential.expires_in()
        expires_in_hours = expires_in_seconds / 3600
        expires_in_days = expires_in_hours / 24

        # 判断状态：与定时刷新阈值对齐，避免 UI「即将过期」与后台刷新旋钮不一致
        refresh_before = self._settings.credential_refresh_before_seconds
        if not credential.is_valid():
            status = "expired"
            status_text = "已过期，请重新登录"
        elif expires_in_seconds < refresh_before:
            status = "expiring_soon"
            status_text = f"即将过期（剩余 {expires_in_days:.1f} 天）"
        else:
            status = "valid"
            status_text = f"有效（剩余 {expires_in_days:.1f} 天）"

        return {
            "exists": True,
            "valid": credential.is_valid(),
            "user_id": credential.user_id,
            "expires_at": credential.expires_at.isoformat(),
            "expires_in": expires_in_seconds,
            "expires_in_hours": round(expires_in_hours, 1),
            "expires_in_days": round(expires_in_days, 1),
            "status": status,
            "status_text": status_text,
        }

    def refresh_credential(self) -> dict[str, Any]:
        with self._credential_lock:
            credential = self._load_required_credential()
            generation = self._account_generation
        self._refresh_credential(credential, generation)
        return self.credential_status()

    def _refresh_credential(self, credential: Credential, generation: int) -> Credential:
        # Refresh serialization does not block account removal or login commits.
        with self._refresh_lock:
            with self._credential_lock:
                self._check_account_generation(generation)
                current = self._load_required_credential()
                if current.user_id != credential.user_id:
                    raise AccountChangedError("米家账号已变更，旧刷新任务已取消")
                if current.service_token != credential.service_token:
                    return current
            auth = create_auth_service(
                credential_store=FileCredentialStore(self._settings.credential_path)
            )
            refreshed = auth.refresh_credential(current)
            with self._credential_lock:
                self._check_account_generation(generation)
                latest = self._load_required_credential()
                if (
                    latest.user_id != current.user_id
                    or latest.service_token != current.service_token
                ):
                    raise AccountChangedError("米家凭据已变更，旧刷新结果已丢弃")
                auth.save_credential(refreshed)
            return refreshed

    def delete_credential(self) -> dict[str, Any]:
        """删除米家凭据，同时清理该账号同步下来的数据与 SDK 缓存。

        返回受影响的行数摘要，便于上层审计。
        """
        with self._credential_lock:
            self._account_generation += 1
            self._login_sequence += 1
            if self._login_canceller is not None:
                self._login_canceller()
            old_api = self._detach_api_client()
            FileCredentialStore(self._settings.credential_path).delete()
            cleared = self._store.clear_synced_registries()
        self._clear_detached_cache(old_api)
        return {"cleared": cleared}

    @staticmethod
    def _clear_detached_cache(api: Any) -> None:
        try:
            if api is not None:
                api.clear_all_cache()
        except Exception:
            logger.warning("failed to clear detached SDK cache", exc_info=True)

    def start_credential_refresh_timer(self) -> None:
        """启动定时刷新凭据的后台任务"""
        with self._refresh_timer_lock:
            if self._refresh_timer_enabled:
                return
            self._refresh_timer_enabled = True
            self._refresh_timer_generation += 1
            self._schedule_refresh_timer_locked(self._refresh_timer_generation)

    def _schedule_refresh_timer_locked(self, generation: int) -> None:
        timer = threading.Timer(
            self._refresh_interval, lambda: self._credential_refresh_job(generation)
        )
        timer.daemon = True
        self._refresh_timer = timer
        timer.start()

    def stop_credential_refresh_timer(self) -> None:
        """停止定时刷新凭据的后台任务"""
        with self._refresh_timer_lock:
            self._refresh_timer_enabled = False
            self._refresh_timer_generation += 1
            if self._refresh_timer is not None:
                self._refresh_timer.cancel()
                self._refresh_timer = None

    def _credential_refresh_job(self, timer_generation: int) -> None:
        """定时刷新凭据的任务"""
        with self._refresh_timer_lock:
            if (
                not self._refresh_timer_enabled
                or timer_generation != self._refresh_timer_generation
            ):
                return
            self._refresh_timer = None
        try:
            with self._credential_lock:
                credential = self.load_credential()
                generation = self._account_generation
            if credential is None:
                return
            threshold = self._settings.credential_refresh_before_seconds
            if credential.expires_in() < threshold:
                self._refresh_credential(credential, generation)
        except Exception as exc:
            logger.warning(
                "credential refresh job failed", extra={"error_type": type(exc).__name__}
            )
        finally:
            with self._refresh_timer_lock:
                if (
                    self._refresh_timer_enabled
                    and timer_generation == self._refresh_timer_generation
                ):
                    self._schedule_refresh_timer_locked(timer_generation)

    def sync_all(self) -> dict[str, Any]:
        """启动后台同步任务并立即返回。

        同步在守护线程中执行，前端可通过 ``/api/admin/sync/progress`` 轮询进度。
        若已有同步在运行则抛出 :class:`SyncInProgressError`。

        在启动后台线程前即写入新的 ``running`` progress，避免前端短暂读到
        上一轮 ``completed`` 终态而误判同步已结束。
        """
        if not self._sync_lock.acquire(blocking=False):
            raise SyncInProgressError("同步正在进行中，请稍后再试")

        try:
            with self._credential_lock:
                generation = self._account_generation
                task_id = str(uuid.uuid4())
                self._sync_progress = SyncProgress(
                    task_id=task_id,
                    status="running",
                    step="排队中",
                    started_at=isoformat(utc_now()),
                )
            thread = threading.Thread(target=self._sync_background, args=(generation,), daemon=True)
            thread.start()
        except Exception:
            self._sync_lock.release()
            raise
        return {
            "status": "started",
            "task_id": task_id,
            "message": "同步已在后台启动，请轮询 /api/admin/sync/progress",
        }

    def _sync_background(self, generation: int) -> None:
        """后台线程入口：执行同步逻辑并确保锁被释放。"""
        task_id: Optional[str] = None
        try:
            result = self._sync_all_unlocked(generation)
            try:
                self._store.add_audit(
                    "mijia.sync.completed",
                    "warning" if result.get("warnings") else "success",
                    actor_type="system",
                    metadata=result,
                )
            except Exception:
                logger.warning("failed to audit completed sync", exc_info=True)
        except Exception as exc:
            try:
                self._store.add_audit(
                    "mijia.sync.completed",
                    "failed",
                    actor_type="system",
                    metadata={"error_type": type(exc).__name__},
                )
            except Exception:
                logger.warning("failed to audit failed sync", exc_info=True)
            logger.warning(
                "sync background thread failed", extra={"error_type": type(exc).__name__}
            )
        finally:
            task_id = self._sync_progress.task_id if self._sync_progress else None
            # 先释放锁，再安排延迟清理，避免前端已看到终态却仍无法立刻发起下一轮同步。
            self._sync_lock.release()
            if task_id is not None:
                delay = self._progress_cleanup_delay_seconds

                def cleanup_progress() -> None:
                    time.sleep(delay)
                    self._clear_progress_if_task(task_id)

                threading.Thread(target=cleanup_progress, daemon=True).start()

    def get_sync_progress(self) -> Optional[dict[str, Any]]:
        """Get current sync progress."""
        with self._credential_lock:
            if self._sync_progress is None:
                return None
            return self._sync_progress.as_dict()

    def _sync_all_unlocked(self, generation: int) -> dict[str, Any]:
        # Prefer the progress seeded by sync_all(); create one only as fallback.
        if self._sync_progress is None:
            self._sync_progress = SyncProgress(
                task_id=str(uuid.uuid4()),
                status="running",
                step="初始化",
                started_at=isoformat(utc_now()),
            )

        try:
            # Step 1: Initialize
            self._update_progress(step="初始化同步任务", progress=0, status="running")

            # Step 2: Get homes
            self._update_progress(step="获取家庭列表", progress=5)
            api, _ = self._api_with_generation(generation)
            api.refresh_cache()
            homes = api.get_homes()

            # Step 3: Save homes
            self._update_progress(step="保存家庭数据", progress=10, homes_total=len(homes))
            home_dicts = [model_to_dict(home) for home in homes]

            devices: list[dict[str, Any]] = []
            scenes: list[dict[str, Any]] = []
            warnings: list[dict[str, Any]] = []
            reconciled_device_homes: list[str] = []
            reconciled_scene_homes: list[str] = []

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
                    reconciled_device_homes.append(str(home.id))
                    self._update_progress(devices_found=len(devices))
                except Exception as exc:
                    warnings.append(self._sync_warning("devices", home, exc))

                # Get scenes
                try:
                    scenes.extend(self._scene_dicts(api, home))
                    reconciled_scene_homes.append(str(home.id))
                    self._update_progress(scenes_found=len(scenes))
                except Exception as exc:
                    warnings.append(self._sync_warning("scenes", home, exc))

                self._update_progress(homes_processed=i + 1)

            # Step 7: Save devices
            self._update_progress(step="保存设备数据", progress=90)
            # Step 8: Commit the complete snapshot atomically.
            self._update_progress(step="保存家庭、设备和场景数据", progress=95)
            with self._credential_lock:
                self._check_account_generation(generation)
                self._store.replace_synced_snapshot(
                    home_dicts,
                    devices,
                    scenes,
                    reconciled_device_home_ids=reconciled_device_homes,
                    reconciled_scene_home_ids=reconciled_scene_homes,
                )

            # Complete
            self._update_progress(
                status="completed",
                step="同步完成",
                progress=100,
                homes_processed=len(home_dicts),
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
                error=(
                    "米家账号已移除或重新登录，旧同步结果已丢弃"
                    if isinstance(e, AccountChangedError)
                    else "同步失败，请检查账号或网络状态后重试"
                ),
                completed_at=isoformat(utc_now()),
            )
            raise

    def _clear_progress_if_task(self, task_id: Optional[str]) -> None:
        """仅在当前 progress 属于指定 task 时清空，避免误清新一轮任务。"""
        with self._credential_lock:
            current = self._sync_progress
            if current is not None and current.task_id == task_id:
                self._sync_progress = None

    def _update_progress(self, **kwargs) -> None:
        """Update sync progress."""
        with self._credential_lock:
            if self._sync_progress is None:
                return

            for key, value in kwargs.items():
                if hasattr(self._sync_progress, key):
                    setattr(self._sync_progress, key, value)

            self._sync_progress.updated_at = isoformat(utc_now())

    @staticmethod
    def _authorize_resource(
        resource: dict[str, Any], authorize: Optional[Callable[[dict[str, Any]], bool]]
    ) -> None:
        if authorize is not None and not authorize(resource):
            raise PermissionError("API key cannot access the current resource")

    def get_device_state(
        self,
        device_slug: str,
        *,
        internal_only: bool = False,
        authorize: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[dict[str, Any]]:
        with self._credential_lock:
            generation = self._account_generation
            device = self._store.get_device(device_slug, internal_only=internal_only)
            self._authorize_resource(device, authorize)
        api, _ = self._api_with_generation(generation)
        spec = device.get("spec")
        if not spec:
            fetched = api.get_device_spec(device["model"])
            spec = model_to_dict(fetched) if fetched is not None else None
        if not spec:
            raise RuntimeError("设备规格不可用，暂无法读取实时状态")
        requests = self._readable_property_requests(device["did"], spec)
        if not requests:
            return []
        return api.get_device_properties(requests)

    def set_device_property(
        self,
        device_slug: str,
        siid: int,
        piid: int,
        value: Any,
        *,
        internal_only: bool = False,
        authorize: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> dict[str, Any]:
        with self._credential_lock:
            generation = self._account_generation
            device = self._store.get_device(device_slug, internal_only=internal_only)
            self._authorize_resource(device, authorize)
            if device["access_mode"] != "write":
                raise PermissionError("设备未授权控制")
        api, _ = self._api_with_generation(generation)
        success = api.control_device(
            device["did"], siid, piid, value, home_id=device.get("home_id")
        )
        return {"success": bool(success)}

    def call_device_action(
        self,
        device_slug: str,
        siid: int,
        aiid: int,
        params: Optional[dict[str, Any]],
        *,
        internal_only: bool = False,
        authorize: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> dict[str, Any]:
        with self._credential_lock:
            generation = self._account_generation
            device = self._store.get_device(device_slug, internal_only=internal_only)
            self._authorize_resource(device, authorize)
            if device["access_mode"] != "write":
                raise PermissionError("设备未授权控制")
        api, _ = self._api_with_generation(generation)
        result = api.call_device_action(
            device["did"], siid, aiid, params or {}, home_id=device.get("home_id")
        )
        return {"result": result}

    def batch_set_properties(
        self,
        requests: list[dict[str, Any]],
        *,
        internal_only: bool = False,
        authorize: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> dict[str, Any]:
        api_requests = []
        with self._credential_lock:
            generation = self._account_generation
            for request in requests:
                device_ref = request.get("device") or request.get("device_id")
                if not device_ref:
                    raise ValueError("每项必须包含 device 或 device_id")
                device = self._store.get_device(str(device_ref), internal_only=internal_only)
                self._authorize_resource(device, authorize)
                if device["access_mode"] != "write":
                    raise PermissionError(f"设备未授权控制: {device['slug']}")
                api_requests.append(
                    {
                        "did": device["did"],
                        "home_id": device.get("home_id"),
                        "siid": request["siid"],
                        "piid": request["piid"],
                        "value": request["value"],
                    }
                )
        api, _ = self._api_with_generation(generation)
        return {"items": api.batch_control_devices(api_requests)}

    def get_device_spec(
        self,
        device_slug: str,
        *,
        internal_only: bool = False,
        authorize: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> dict[str, Any] | None:
        with self._credential_lock:
            generation = self._account_generation
            device = self._store.get_device(device_slug, internal_only=internal_only)
            self._authorize_resource(device, authorize)
        api, _ = self._api_with_generation(generation)
        spec = api.get_device_spec(device["model"])
        if spec is None:
            return None
        return model_to_dict(spec)

    def execute_scene(
        self,
        scene_id: str,
        *,
        internal_only: bool = False,
        authorize: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> dict[str, Any]:
        with self._credential_lock:
            generation = self._account_generation
            scene = self._store.get_scene(scene_id, internal_only=internal_only)
            self._authorize_resource(scene, authorize)
            if not scene["executable"]:
                raise PermissionError("场景未授权执行")
            owner_uid = (scene.get("raw") or {}).get("owner_uid")
            try:
                home = self._store.get_home(scene["home_id"])
                owner_uid = home.get("uid") or owner_uid
            except KeyError:
                pass
        api, _ = self._api_with_generation(generation)
        if owner_uid is None:
            success = api.execute_scene(scene["scene_id"], scene["home_id"])
        else:
            success = api.execute_scene(scene["scene_id"], scene["home_id"], owner_uid=owner_uid)
        return {"success": bool(success)}

    def refresh_cache(self, home_id: Optional[str] = None) -> None:
        self._api().refresh_cache(home_id=home_id)

    def clear_sdk_cache(self) -> None:
        self._api().clear_all_cache()

    def _require_credential(self, generation: int) -> Credential:
        with self._credential_lock:
            self._check_account_generation(generation)
            credential = self._load_required_credential()
        if credential.expires_in() > self._settings.credential_refresh_before_seconds:
            return credential
        try:
            return self._refresh_credential(credential, generation)
        except AccountChangedError:
            raise
        except Exception as exc:
            with self._credential_lock:
                self._check_account_generation(generation)
                credential = self._load_required_credential()
                if credential.is_valid():
                    return credential
            raise RuntimeError("米家凭据已过期且自动刷新失败，请重新扫码登录") from exc

    def _load_required_credential(self) -> Credential:
        credential = self.load_credential()
        if credential is None:
            raise RuntimeError("米家凭据不存在，请先扫码登录")
        return credential

    def _api(self) -> Any:
        """返回共享的 MijiaAPI 实例。

        只在以下情况重建：
        - 首次调用；
        - 凭据文件被替换到另一个 ``user_id``。
        凭据 token 因刷新更新时，直接调用 ``update_credential`` 避免全量重建。
        """
        return self._api_with_generation()[0]

    def _api_with_generation(self, expected: Optional[int] = None) -> tuple[Any, int]:
        with self._credential_lock:
            generation = self._account_generation if expected is None else expected
            self._check_account_generation(generation)
        self._require_credential(generation)
        with self._credential_lock:
            self._check_account_generation(generation)
            credential = self._load_required_credential()
            with self._api_lock:
                api = self._api_client
                if api is not None and self._api_client_credential_id == credential.user_id:
                    api.update_credential(credential)
                else:
                    api = create_api_client(credential, cache_dir=self._settings.data_dir / "cache")
                    self._api_client = api
                    self._api_client_credential_id = credential.user_id
                return api, generation

    def _invalidate_api_client(self) -> None:
        """凭据被删除或替换用户时，丢弃当前 MijiaAPI 实例。"""
        self._detach_api_client()

    def _detach_api_client(self) -> Any:
        with self._api_lock:
            previous = self._api_client
            self._api_client = None
            self._api_client_credential_id = None
            return previous

    def _device_dicts(self, api: Any, home: Home) -> list[dict[str, Any]]:
        devices = []
        for device in api.get_devices(home.id):
            payload = model_to_dict(device)
            payload["id"] = str(uuid.uuid4())
            status = payload.get("status", "unknown")
            status = str(getattr(status, "value", status)).lower()
            payload["status"] = status if status in {"online", "offline", "unknown"} else "unknown"
            payload["spec"] = self._safe_spec(api, device)
            devices.append(payload)
        return devices

    def _scene_dicts(self, api: Any, home: Home) -> list[dict[str, Any]]:
        scenes = []
        for scene in api.get_scenes(home.id, owner_uid=home.uid):
            payload = model_to_dict(scene)
            payload["id"] = str(uuid.uuid4())
            payload["owner_uid"] = home.uid or payload.get("owner_uid")
            scenes.append(payload)
        return scenes

    def _sync_warning(self, kind: str, home: Home, exc: Exception) -> dict[str, Any]:
        label = "设备" if kind == "devices" else "场景"
        code = getattr(exc, "code", None)
        return {
            "kind": kind,
            "home_id": str(home.id),
            "home_name": str(home.name),
            "message": f"该家庭的{label}读取失败，已保留上次同步数据",
            "error_type": type(exc).__name__,
            **({"code": code} if type(code) is int else {}),
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
        for prop in properties:
            access = prop.get("access", "")
            access = getattr(access, "value", access)
            readable = access in ("read", "read_write")
            if isinstance(access, (list, tuple, set)):
                readable = "read" in access
            if readable:
                requests.append({"did": did, "siid": prop["siid"], "piid": prop["piid"]})
        return requests
