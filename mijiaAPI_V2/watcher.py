"""设备状态变化监听

通过周期性拉取设备属性并与上一次快照对比，把状态变化分发给注册的处理函数。
轮询只覆盖被显式订阅的设备；首次轮询只建立基线，不触发回调。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import threading
import time
from typing import Any, Callable, Iterable, List, Optional, Union

from mijiaAPI_V2.core.logging import get_logger
from mijiaAPI_V2.domain.exceptions import ValidationError
from mijiaAPI_V2.domain.models import Credential, DeviceProperty
from mijiaAPI_V2.services.device_service import DeviceService

logger = get_logger(__name__)

# 轮询间隔下限：再快也只允许 5 秒一次，避免触发云端风控
MIN_POLL_INTERVAL = 5.0
DEFAULT_POLL_INTERVAL = 30.0

_MISSING = object()


@dataclass(frozen=True)
class StateChangeEvent:
    """单个属性的状态变化事件"""

    did: str
    siid: int
    piid: int
    name: str
    old: Any
    new: Any
    changed_at: datetime


StateChangeHandler = Callable[[StateChangeEvent], None]


@dataclass
class _Subscription:
    devices: tuple
    interval: float
    handler: StateChangeHandler
    next_due: float
    baselines: dict


def _normalize_devices(devices: Union[str, int, Iterable[Union[str, int]]]) -> tuple:
    if isinstance(devices, (str, int)):
        items: List[Any] = [devices]
    else:
        try:
            items = list(devices)
        except TypeError as exc:
            raise ValidationError("devices 必须是设备ID或设备ID列表") from exc
    dids: List[str] = []
    for item in items:
        if not isinstance(item, (str, int)) or not str(item).strip():
            raise ValidationError("设备ID必须是非空字符串")
        did = str(item).strip()
        if did not in dids:
            dids.append(did)
    if not dids:
        raise ValidationError("设备列表不能为空")
    return tuple(dids)


def _normalize_interval(interval: Any) -> float:
    if isinstance(interval, bool) or not isinstance(interval, (int, float)):
        raise ValidationError("轮询间隔必须是数字（秒）")
    value = float(interval)
    if not math.isfinite(value) or value <= 0:
        raise ValidationError("轮询间隔必须是正数")
    return max(MIN_POLL_INTERVAL, value)


class DeviceStateWatcher:
    """设备状态监听器

    在后台线程中按订阅的间隔轮询设备属性，状态变化时调用注册的处理函数。
    处理函数在轮询线程中同步执行，应当尽快返回。
    """

    def __init__(
        self,
        device_service: DeviceService,
        credential: Credential,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device_service = device_service
        self._credential = credential
        self._clock = clock
        self._subs: List[_Subscription] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def on_change(
        self,
        devices: Union[str, int, Iterable[Union[str, int]]],
        interval: float = DEFAULT_POLL_INTERVAL,
    ) -> Callable[[StateChangeHandler], StateChangeHandler]:
        """装饰器：注册设备状态变化回调

        Args:
            devices: 设备ID，或设备ID列表
            interval: 轮询间隔（秒），默认30秒；低于5秒会被钳制到5秒

        Returns:
            装饰器，返回原函数，可继续正常调用
        """
        dids = _normalize_devices(devices)
        seconds = _normalize_interval(interval)

        def decorator(handler: StateChangeHandler) -> StateChangeHandler:
            if not callable(handler):
                raise ValidationError("状态变化回调必须是可调用对象")
            sub = _Subscription(
                devices=dids,
                interval=seconds,
                handler=handler,
                next_due=self._clock() + seconds,
                baselines={},
            )
            with self._lock:
                self._subs.append(sub)
            self.start()
            logger.info(
                "已注册设备状态监听",
                extra={"devices": list(dids), "interval": seconds, "handler": getattr(handler, "__name__", "")},
            )
            return handler

        return decorator

    def update_credential(self, credential: Credential) -> None:
        """凭据刷新后同步到监听器"""
        self._credential = credential

    def poll_once(self) -> int:
        """立即轮询全部订阅并分发变化，忽略轮询间隔。

        Returns:
            本次触发的事件数
        """
        with self._lock:
            subs = list(self._subs)
        total = 0
        for sub in subs:
            total += self._poll_subscription(sub)
        return total

    def start(self) -> None:
        """启动后台轮询线程（幂等）"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="mijia-state-watcher", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台轮询线程"""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            now = self._clock()
            with self._lock:
                subs = list(self._subs)
            for sub in subs:
                if now < sub.next_due:
                    continue
                # 先推进截止时间，轮询耗时过长也不会堆积补跑
                sub.next_due = self._clock() + sub.interval
                try:
                    self._poll_subscription(sub)
                except Exception:
                    logger.error("设备状态轮询失败", exc_info=True)
            with self._lock:
                subs = list(self._subs)
            if subs:
                next_due = min(sub.next_due for sub in subs)
                timeout = max(0.05, min(1.0, next_due - self._clock()))
            else:
                timeout = 1.0
            self._stop.wait(timeout)

    def _poll_subscription(self, sub: _Subscription) -> int:
        events: List[StateChangeEvent] = []
        for did in sub.devices:
            try:
                properties: List[DeviceProperty] = self._device_service.get_device_properties(
                    did, self._credential, fresh=True
                )
            except Exception as exc:
                logger.warning(
                    "读取设备属性失败",
                    extra={"did": did, "error_type": type(exc).__name__},
                )
                continue
            readable = [p for p in properties if p.is_readable()]
            current = {(p.siid, p.piid): p for p in readable}
            baseline = sub.baselines.get(did)
            if baseline is None:
                sub.baselines[did] = {key: prop.value for key, prop in current.items()}
                continue
            changed_at = datetime.now(timezone.utc)
            for key, prop in current.items():
                old = baseline.get(key, _MISSING)
                if old is not _MISSING and old != prop.value:
                    events.append(
                        StateChangeEvent(
                            did=did,
                            siid=prop.siid,
                            piid=prop.piid,
                            name=prop.name,
                            old=old,
                            new=prop.value,
                            changed_at=changed_at,
                        )
                    )
            sub.baselines[did] = {key: prop.value for key, prop in current.items()}
        for event in events:
            self._dispatch(sub.handler, event)
        return len(events)

    def _dispatch(self, handler: StateChangeHandler, event: StateChangeEvent) -> None:
        try:
            handler(event)
        except Exception:
            logger.error(
                "状态变化回调执行失败",
                extra={"did": event.did, "siid": event.siid, "piid": event.piid},
                exc_info=True,
            )
