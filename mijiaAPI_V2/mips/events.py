"""MIoT Pub/Sub（MIPS）事件模型

云 MQTT 推送的三类消息：属性变化、MIoT 事件、设备上下线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PropertyChangeEvent:
    """属性变化推送（topic: device/{did}/up/properties_changed/{siid}/{piid}）"""

    did: str
    siid: int
    piid: int
    value: Any
    topic: str
    received_at: datetime = field(default_factory=_now)

    @property
    def key(self) -> str:
        return f"{self.siid}.{self.piid}"


@dataclass(frozen=True)
class DeviceEvent:
    """MIoT spec 事件推送（topic: device/{did}/up/event_occured/{siid}/{eiid}）"""

    did: str
    siid: int
    eiid: int
    arguments: List[Any]
    topic: str
    received_at: datetime = field(default_factory=_now)

    @property
    def key(self) -> str:
        return f"{self.siid}.{self.eiid}"


@dataclass(frozen=True)
class DeviceStateEvent:
    """设备上下线推送（topic: device/{did}/state/#）"""

    did: str
    state: str
    raw: Dict[str, Any] = field(default_factory=dict)
    topic: str = ""
    received_at: datetime = field(default_factory=_now)


MipsEvent = Any  # PropertyChangeEvent | DeviceEvent | DeviceStateEvent


def parse_property_change(did: str, topic: str, payload: bytes) -> Optional[PropertyChangeEvent]:
    """解析属性变化消息，格式不符时返回 None"""
    import json

    try:
        msg = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    params = msg.get("params") if isinstance(msg, dict) else None
    if not isinstance(params, dict):
        return None
    siid, piid, value = params.get("siid"), params.get("piid"), params.get("value")
    if type(siid) is not int or type(piid) is not int or "value" not in params:
        return None
    return PropertyChangeEvent(
        did=did, siid=siid, piid=piid, value=value, topic=topic
    )


def parse_device_event(did: str, topic: str, payload: bytes) -> Optional[DeviceEvent]:
    """解析 MIoT 事件消息，格式不符时返回 None"""
    import json

    try:
        msg = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    params = msg.get("params") if isinstance(msg, dict) else None
    if not isinstance(params, dict):
        return None
    siid, eiid = params.get("siid"), params.get("eiid")
    if type(siid) is not int or type(eiid) is not int:
        return None
    arguments = params.get("arguments")
    if not isinstance(arguments, list):
        arguments = []
    return DeviceEvent(
        did=did, siid=siid, eiid=eiid, arguments=arguments, topic=topic
    )


def parse_device_state(did: str, topic: str, payload: bytes) -> Optional[DeviceStateEvent]:
    """解析设备上下线消息，格式不符时返回 None"""
    import json

    try:
        msg = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None
    state = msg.get("event")
    if not isinstance(state, str):
        return None
    return DeviceStateEvent(
        did=str(msg.get("device_id") or did),
        state=state,
        raw=msg,
        topic=topic,
    )
