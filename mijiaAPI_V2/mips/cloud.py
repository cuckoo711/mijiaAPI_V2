"""MIoT Pub/Sub 云 MQTT 客户端

连接小米云 MQTT Broker（``{cloud}-ha.mqtt.io.mi.com:8883``，MQTT v5 over TLS），
订阅设备的属性变化 / 事件 / 上下线推送并解析分发。

Topic 约定（源自 MIoT Pub/Sub 协议）：
- ``device/{did}/up/properties_changed/{siid}/{piid}``
- ``device/{did}/up/event_occured/{siid}/{eiid}``（官方即此拼写）
- ``device/{did}/state/#``

本模块为独立实现，未复用任何第三方项目源码。
"""

from __future__ import annotations

import ssl
import threading
from typing import Callable, Dict, Iterable, List, Optional, Union

from mijiaAPI_V2.core.logging import get_logger
from mijiaAPI_V2.mips.events import (
    DeviceEvent,
    DeviceStateEvent,
    PropertyChangeEvent,
    parse_device_event,
    parse_device_state,
    parse_property_change,
)

logger = get_logger(__name__)

MIPS_BROKER_HOST = "ha.mqtt.io.mi.com"
MIPS_BROKER_PORT = 8883
MIPS_KEEPALIVE = 60

PropertyHandler = Callable[[PropertyChangeEvent], None]
EventHandler = Callable[[DeviceEvent], None]
StateHandler = Callable[[DeviceStateEvent], None]


def broker_host(cloud_server: str = "cn") -> str:
    return f"{cloud_server}-{MIPS_BROKER_HOST}"


class MipsCloudClient:
    """云推送 MQTT 客户端（后台线程 + 回调分发）"""

    def __init__(
        self,
        app_id: str,
        access_token: str,
        cloud_server: str = "cn",
        client_id: Optional[str] = None,
    ) -> None:
        self._app_id = str(app_id)
        self._access_token = access_token
        self._host = broker_host(cloud_server)
        self._client_id = client_id or "mijia-api-mips"
        self._mqtt = None
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._property_handlers: List[PropertyHandler] = []
        self._event_handlers: List[EventHandler] = []
        self._state_handlers: List[StateHandler] = []
        self._subscribed: Dict[str, int] = {}

    # ---- 事件订阅 ----

    def on_property_change(self, handler: PropertyHandler) -> PropertyHandler:
        self._property_handlers.append(handler)
        return handler

    def on_device_event(self, handler: EventHandler) -> EventHandler:
        self._event_handlers.append(handler)
        return handler

    def on_device_state(self, handler: StateHandler) -> StateHandler:
        self._state_handlers.append(handler)
        return handler

    # ---- 连接管理 ----

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def host(self) -> str:
        return self._host

    def connect(self, timeout: float = 15.0) -> None:
        """连接 Broker 并保持后台收包线程（幂等）"""
        with self._lock:
            if self._mqtt is not None:
                return
            from paho.mqtt.client import (
                CallbackAPIVersion,
                Client,
                MQTTv5,
            )

            mqtt = Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id=self._client_id,
                protocol=MQTTv5,
            )
            mqtt.username_pw_set(username=self._app_id, password=self._access_token)
            mqtt.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
            mqtt.on_connect = self._on_connect
            mqtt.on_disconnect = self._on_disconnect
            mqtt.on_message = self._on_message
            self._mqtt = mqtt
            try:
                mqtt.connect(self._host, MIPS_BROKER_PORT, keepalive=MIPS_KEEPALIVE)
            except Exception as exc:
                self._mqtt = None
                raise ConnectionError(f"连接云 MQTT 失败: {exc}") from exc
            mqtt.loop_start()
        if not self._connected.wait(timeout):
            raise ConnectionError(f"云 MQTT {self._host} 连接超时")
        logger.info("云 MQTT 已连接", extra={"host": self._host})

    def disconnect(self) -> None:
        with self._lock:
            mqtt = self._mqtt
            self._mqtt = None
            self._connected.clear()
            self._subscribed.clear()
        if mqtt is not None:
            try:
                mqtt.disconnect()
                mqtt.loop_stop()
            except Exception:
                pass

    def update_access_token(self, access_token: str) -> None:
        """令牌续期后更新 MQTT 密码并重连"""
        with self._lock:
            self._access_token = access_token
            mqtt = self._mqtt
        if mqtt is not None:
            mqtt.username_pw_set(username=self._app_id, password=access_token)
            try:
                mqtt.reconnect()
            except Exception as exc:
                logger.warning(
                    "令牌更新后重连失败", extra={"error_type": type(exc).__name__}
                )

    # ---- 订阅 ----

    def subscribe_all(self) -> None:
        """订阅全部设备（topic 通配符，Broker 不支持时需改用 subscribe_devices）"""
        self._subscribe(
            [
                "device/+/up/properties_changed/#",
                "device/+/up/event_occured/#",
                "device/+/state/#",
            ]
        )

    def subscribe_devices(self, dids: Iterable[Union[str, int]]) -> None:
        """订阅指定设备"""
        topics = []
        for did in dids:
            did = str(did).strip()
            if not did:
                continue
            topics.append(f"device/{did}/up/properties_changed/#")
            topics.append(f"device/{did}/up/event_occured/#")
            topics.append(f"device/{did}/state/#")
        self._subscribe(topics)

    def _subscribe(self, topics: List[str]) -> None:
        if self._mqtt is None:
            raise ConnectionError("尚未连接云 MQTT")
        for topic in topics:
            result, _mid = self._mqtt.subscribe(topic, qos=2)
            if result != 0:
                logger.warning("订阅失败", extra={"topic": topic, "result": result})
            else:
                self._subscribed[topic] = result
                logger.info("已订阅", extra={"topic": topic})

    # ---- MQTT 回调 ----

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        self._connected.set()
        logger.info("云 MQTT 连接成功", extra={"reason": str(reason_code)})
        # 重连后恢复既有订阅
        for topic in list(self._subscribed.keys()):
            client.subscribe(topic, qos=2)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self._connected.clear()
        logger.warning("云 MQTT 断开", extra={"reason": str(reason_code)})

    def _on_message(self, client, userdata, message) -> None:
        topic = message.topic
        parts = topic.split("/")
        try:
            if len(parts) >= 6 and parts[0] == "device" and parts[2] == "up":
                did = parts[1]
                kind = parts[3]
                if kind == "properties_changed":
                    event = parse_property_change(did, topic, message.payload)
                    if event is not None:
                        self._dispatch_property(event)
                elif kind == "event_occured":
                    event = parse_device_event(did, topic, message.payload)
                    if event is not None:
                        self._dispatch_event(event)
            elif len(parts) >= 3 and parts[0] == "device" and parts[2] == "state":
                event = parse_device_state(parts[1], topic, message.payload)
                if event is not None:
                    self._dispatch_state(event)
        except Exception:
            logger.error("推送消息处理失败", extra={"topic": topic}, exc_info=True)

    def _dispatch_property(self, event: PropertyChangeEvent) -> None:
        for handler in list(self._property_handlers):
            try:
                handler(event)
            except Exception:
                logger.error("属性变化回调失败", extra={"did": event.did}, exc_info=True)

    def _dispatch_event(self, event: DeviceEvent) -> None:
        for handler in list(self._event_handlers):
            try:
                handler(event)
            except Exception:
                logger.error("设备事件回调失败", extra={"did": event.did}, exc_info=True)

    def _dispatch_state(self, event: DeviceStateEvent) -> None:
        for handler in list(self._state_handlers):
            try:
                handler(event)
            except Exception:
                logger.error("设备状态回调失败", extra={"did": event.did}, exc_info=True)
