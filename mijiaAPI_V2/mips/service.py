"""MIoT Pub/Sub 推送服务

把 OAuth 登录、云 MQTT 连接和事件分发组装成一个可直接使用的服务：
装饰器订阅事件、webhook 转发、令牌自动续期。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

import httpx

from mijiaAPI_V2.core.logging import get_logger
from mijiaAPI_V2.mips.auth import (
    MipsOAuthClient,
    MipsTokenStore,
    MipsTokens,
    extract_code_from_redirect,
)
from mijiaAPI_V2.mips.cloud import MipsCloudClient
from mijiaAPI_V2.mips.events import (
    DeviceEvent,
    DeviceStateEvent,
    MipsEvent,
    PropertyChangeEvent,
)

logger = get_logger(__name__)


class MipsService:
    """MIPS 推送服务

    使用方式::

        service = MipsService()
        service.load_or_login(interactive_login)  # 或 service.complete_login(url)

        @service.on_property_change()
        def handler(event): ...

        service.start()
    """

    def __init__(
        self,
        cloud_server: str = "cn",
        devices: Optional[Iterable[Union[str, int]]] = None,
        webhook_url: Optional[str] = None,
        token_path: Optional[str] = None,
    ) -> None:
        self._cloud_server = cloud_server
        self._devices: Optional[List[str]] = (
            [str(d) for d in devices] if devices is not None else None
        )
        self._webhook_url = webhook_url
        self._store = MipsTokenStore(
            default_path=Path(token_path) if token_path else None
        )
        self._tokens: Optional[MipsTokens] = None
        self._oauth: Optional[MipsOAuthClient] = None
        self._client: Optional[MipsCloudClient] = None
        self._prop_handlers: List[tuple] = []  # (did_filter, handler)
        self._event_handlers: List[tuple] = []
        self._state_handlers: List[tuple] = []
        self._refresh_lock = threading.Lock()
        self._refresh_stop: Optional[threading.Event] = None

    # ---- 登录 / 令牌 ----

    @property
    def tokens(self) -> Optional[MipsTokens]:
        return self._tokens

    @property
    def is_logged_in(self) -> bool:
        return self._tokens is not None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def auth_url(self) -> str:
        """生成小米账号授权链接"""
        return self._oauth_client().auth_url()

    def complete_login(self, redirect_or_code: str) -> MipsTokens:
        """用重定向地址或授权码完成登录并保存令牌"""
        code = extract_code_from_redirect(redirect_or_code)
        tokens = self._oauth_client().exchange_code(code)
        self._store.save_tokens(tokens)
        self._tokens = tokens
        logger.info("MIPS 登录成功")
        return tokens

    def logout(self) -> None:
        self.stop()
        self._store.delete_tokens()
        self._tokens = None

    def load_tokens(self) -> bool:
        """加载已保存的令牌，过期则自动续期"""
        tokens = self._store.load_tokens()
        if tokens is None:
            return False
        self._tokens = tokens
        if tokens.needs_refresh():
            self._refresh_tokens()
        return True

    def user_info(self) -> Dict[str, Any]:
        if self._tokens is None:
            raise RuntimeError("尚未登录")
        return self._oauth_client().user_info(self._tokens.access_token)

    def _oauth_client(self) -> MipsOAuthClient:
        if self._oauth is None:
            device_uuid = self._tokens.device_uuid if self._tokens else "mips-default"
            self._oauth = MipsOAuthClient(
                cloud_server=self._cloud_server, device_uuid=device_uuid
            )
        return self._oauth

    def _refresh_tokens(self) -> None:
        with self._refresh_lock:
            if self._tokens is None:
                return
            try:
                tokens = self._oauth_client().refresh(self._tokens.refresh_token)
            except Exception as exc:
                logger.error(
                    "令牌续期失败，请重新登录",
                    extra={"error_type": type(exc).__name__},
                )
                return
            self._store.save_tokens(tokens)
            self._tokens = tokens
            if self._client is not None:
                self._client.update_access_token(tokens.access_token)
            logger.info("MIPS 令牌已续期")

    # ---- 事件订阅（装饰器）----

    def on_property_change(
        self, did: Optional[Union[str, int]] = None
    ) -> Callable[[Callable[[PropertyChangeEvent], None]], Callable]:
        """装饰器：订阅属性变化推送

        Args:
            did: 只接收该设备的推送；None 表示全部设备
        """

        def decorator(handler):
            self._prop_handlers.append((_norm_did(did), handler))
            return handler

        return decorator

    def on_device_event(
        self, did: Optional[Union[str, int]] = None
    ) -> Callable[[Callable[[DeviceEvent], None]], Callable]:
        """装饰器：订阅 MIoT spec 事件（按键、告警等）"""

        def decorator(handler):
            self._event_handlers.append((_norm_did(did), handler))
            return handler

        return decorator

    def on_device_state(
        self, did: Optional[Union[str, int]] = None
    ) -> Callable[[Callable[[DeviceStateEvent], None]], Callable]:
        """装饰器：订阅设备上下线"""

        def decorator(handler):
            self._state_handlers.append((_norm_did(did), handler))
            return handler

        return decorator

    # ---- 生命周期 ----

    def start(self) -> None:
        """连接云 MQTT 并开始接收推送（需已登录）"""
        if self._tokens is None:
            raise RuntimeError("尚未登录，请先完成登录")
        if self._tokens.needs_refresh():
            self._refresh_tokens()
        client = MipsCloudClient(
            app_id=self._oauth_client()._client_id,
            access_token=self._tokens.access_token,
            cloud_server=self._cloud_server,
            client_id=f"ha.{self._tokens.device_uuid}",
        )
        client.on_property_change(self._dispatch_property)
        client.on_device_event(self._dispatch_event)
        client.on_device_state(self._dispatch_state)
        client.connect()
        if self._devices:
            client.subscribe_devices(self._devices)
        else:
            client.subscribe_all()
        self._client = client
        self._start_refresh_watchdog()
        logger.info("MIPS 推送服务已启动")

    def stop(self) -> None:
        if self._refresh_stop is not None:
            self._refresh_stop.set()
            self._refresh_stop = None
        if self._client is not None:
            self._client.disconnect()
            self._client = None

    def _start_refresh_watchdog(self) -> None:
        """后台守护线程：令牌到期前自动续期，保证服务可长期运行"""
        if self._refresh_stop is not None:
            return
        stop = threading.Event()
        self._refresh_stop = stop

        def _loop() -> None:
            while not stop.wait(60):
                if self._tokens is not None and self._tokens.needs_refresh():
                    self._refresh_tokens()

        threading.Thread(
            target=_loop, name="mips-token-refresh", daemon=True
        ).start()

    # ---- 内部分发 ----

    def _dispatch_property(self, event: PropertyChangeEvent) -> None:
        for did_filter, handler in list(self._prop_handlers):
            if did_filter is None or did_filter == event.did:
                _safe_call(handler, event, "属性变化")
        self._post_webhook(
            {"type": "property_change", **_event_payload(event)}
        )

    def _dispatch_event(self, event: DeviceEvent) -> None:
        for did_filter, handler in list(self._event_handlers):
            if did_filter is None or did_filter == event.did:
                _safe_call(handler, event, "设备事件")
        self._post_webhook({"type": "device_event", **_event_payload(event)})

    def _dispatch_state(self, event: DeviceStateEvent) -> None:
        for did_filter, handler in list(self._state_handlers):
            if did_filter is None or did_filter == event.did:
                _safe_call(handler, event, "设备状态")
        self._post_webhook({"type": "device_state", **_event_payload(event)})

    def _post_webhook(self, payload: Dict[str, Any]) -> None:
        if not self._webhook_url:
            return
        try:
            httpx.post(self._webhook_url, json=payload, timeout=5.0)
        except Exception as exc:
            logger.warning(
                "webhook 投递失败",
                extra={"url": self._webhook_url, "error_type": type(exc).__name__},
            )


def _norm_did(did: Optional[Union[str, int]]) -> Optional[str]:
    return None if did is None else str(did)


def _safe_call(handler, event: MipsEvent, kind: str) -> None:
    try:
        handler(event)
    except Exception:
        logger.error(f"{kind}回调失败", exc_info=True)


def _event_payload(event: MipsEvent) -> Dict[str, Any]:
    if isinstance(event, PropertyChangeEvent):
        return {
            "did": event.did,
            "siid": event.siid,
            "piid": event.piid,
            "value": event.value,
            "topic": event.topic,
            "received_at": event.received_at.isoformat(),
        }
    if isinstance(event, DeviceEvent):
        return {
            "did": event.did,
            "siid": event.siid,
            "eiid": event.eiid,
            "arguments": event.arguments,
            "topic": event.topic,
            "received_at": event.received_at.isoformat(),
        }
    return {
        "did": event.did,
        "state": event.state,
        "topic": event.topic,
        "received_at": event.received_at.isoformat(),
    }
