"""设备仓储实现

基于HTTP的设备仓储实现，支持缓存。
"""

from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from ..domain.exceptions import ExecutionUnknownError, MijiaAPIException
from ..domain.models import Credential, Device, DeviceProperty, DeviceStatus
from ..infrastructure.cache_manager import CacheManager
from ..infrastructure.http_client import HttpClient
from .interfaces import IDeviceRepository
from .home_repository import HomeRepositoryImpl, _inventory_identifier

logger = get_logger(__name__)
# Operational request budget, rather than an assumed Xiaomi inventory limit.
MAX_DEVICE_PAGES = 1000


def _device_from_payload(payload: Any, home_id: Optional[str] = None) -> Device:
    if not isinstance(payload, dict):
        raise MijiaAPIException("设备清单项必须为对象")
    try:
        did = _inventory_identifier(payload.get("did"), "device did")
        actual_home = _inventory_identifier(payload.get("home_id"), "device home id")
        if home_id is not None and actual_home != home_id:
            raise MijiaAPIException("设备清单归属家庭与请求不符")
        return Device.model_validate({**payload, "did": did, "home_id": actual_home})
    except MijiaAPIException:
        raise
    except Exception as exc:
        raise MijiaAPIException("设备清单项格式无效") from exc


def _device_collection(payloads: Any, home_id: str) -> List[Device]:
    if not isinstance(payloads, list):
        raise MijiaAPIException("设备清单必须为列表")
    devices = [_device_from_payload(payload, home_id) for payload in payloads]
    if len({device.did for device in devices}) != len(devices):
        raise MijiaAPIException("设备清单包含重复 did")
    return devices


def _device_page(response: Any, start_did: str, seen_cursors: set[str]) -> tuple[list, str, bool]:
    if (
        not isinstance(response, dict)
        or type(response.get("code")) is not int
        or response["code"] != 0
    ):
        raise MijiaAPIException("设备清单响应未明确成功")
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("device_info"), list):
        raise MijiaAPIException("设备清单响应缺少有效 result/device_info")
    more = result.get("has_more")
    if type(more) not in (bool, int) or more not in (0, 1):
        raise MijiaAPIException("设备清单缺少有效 has_more 完整性标记")
    cursor = ""
    if more:
        cursor = _inventory_identifier(result.get("max_did"), "pagination max_did")
        if not result["device_info"] or cursor == start_did or cursor in seen_cursors:
            raise MijiaAPIException("设备分页未推进，清单未完整返回")
    return result["device_info"], cursor, bool(more)


def _unknown_ack() -> ExecutionUnknownError:
    return ExecutionUnknownError("控制响应缺少有效确认，结果未知；请先核对设备状态，勿直接重试")


def _control_result(response: Any) -> Any:
    if not isinstance(response, dict):
        raise _unknown_ack()
    code = response.get("code")
    if "code" in response and type(code) is not int:
        raise _unknown_ack()
    if type(code) is int and code != 0:
        raise MijiaAPIException("米家服务拒绝控制请求", code=code)
    if "result" not in response:
        raise _unknown_ack()
    return response["result"]


def _confirmed_miot_ack(item: Any, target: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict) or type(item.get("code")) is not int:
        raise _unknown_ack()
    # Providers may omit identity fields. When present, they must identify
    # the request whose result we are returning.
    for field in ("did", "siid", "piid", "aiid"):
        if field not in item or field not in target:
            continue
        if field == "did":
            matches = str(item[field]) == str(target[field])
        else:
            matches = type(item[field]) is int and item[field] == target[field]
        if not matches:
            raise _unknown_ack()
    return item


class DeviceRepositoryImpl(IDeviceRepository):
    """设备仓储实现

    基于HTTP API的设备仓储实现，集成缓存管理。
    """

    def __init__(self, http_client: HttpClient, cache_manager: CacheManager):
        """初始化设备仓储

        Args:
            http_client: HTTP客户端
            cache_manager: 缓存管理器
        """
        self._http = http_client
        self._cache = cache_manager

    def get_all(self, home_id: str, credential: Credential) -> List[Device]:
        """获取家庭下所有设备

        Args:
            home_id: 家庭ID
            credential: 用户凭据

        Returns:
            已确认分页完成的设备列表，明确空列表表示家庭没有设备

        Raises:
            MijiaAPIException: 清单缺失、身份不符或分页不完整，调用方应保留旧快照
        """
        home_id = _inventory_identifier(home_id, "home id")
        # 检查缓存
        cache_key = f"devices:{home_id}"
        cached = self._cache.get(cache_key, namespace=credential.user_id)
        if cached is not None:
            try:
                return _device_collection(cached, home_id)
            except MijiaAPIException:
                self._cache.invalidate(cache_key, namespace=credential.user_id)

        # 从API获取（使用旧项目的端点和参数）
        # 首先需要获取home_owner（家庭所有者的UID）
        home_owner = self._get_home_owner(home_id, credential)

        # 分页获取所有设备
        uri = "/home/home_device_list"
        start_did = ""
        has_more = True
        all_devices = []
        seen_cursors: set[str] = set()
        pages_read = 0

        while has_more:
            if pages_read >= MAX_DEVICE_PAGES:
                raise MijiaAPIException("设备清单分页未在读取预算内完成，未获取完整清单")
            data = {
                "home_owner": home_owner,
                "home_id": int(home_id),
                "limit": 200,
                "start_did": start_did,
                "get_split_device": True,
                "support_smart_home": True,
                "get_cariot_device": True,
                "get_third_device": True,
            }

            response = self._http.post(uri, json=data, credential=credential)
            pages_read += 1
            device_info, cursor, has_more = _device_page(response, start_did, seen_cursors)
            all_devices.extend(device_info)
            if has_more:
                seen_cursors.add(cursor)
                start_did = cursor

        # 解析设备列表
        payloads = []
        for device_data in all_devices:
            if not isinstance(device_data, dict):
                raise MijiaAPIException("设备清单项必须为对象")
            if (
                "home_id" in device_data
                and _inventory_identifier(device_data["home_id"], "device home id") != home_id
            ):
                raise MijiaAPIException("设备清单归属家庭与请求不符")
            payloads.append(
                {
                    "did": device_data.get("did"),
                    "name": device_data.get("name", ""),
                    "model": device_data.get("model", ""),
                    "home_id": home_id,
                    "room_id": device_data.get("room_id"),
                    "status": self._parse_device_status(device_data.get("isOnline")),
                    "parent_id": device_data.get("parent_id"),
                    "parent_model": device_data.get("parent_model"),
                }
            )
        devices = _device_collection(payloads, home_id)

        # 缓存结果（TTL=300秒）
        self._cache.set(
            cache_key, [d.model_dump() for d in devices], ttl=300, namespace=credential.user_id
        )

        return devices

    def _get_home_owner(self, home_id: str, credential: Credential) -> int:
        """获取家庭所有者的UID

        Args:
            home_id: 家庭ID
            credential: 用户凭据

        Returns:
            家庭所有者的UID

        Raises:
            MijiaAPIException: 家庭清单无效或找不到对应的家庭所有者
        """
        for home in HomeRepositoryImpl(self._http, self._cache).get_all(credential):
            if home.id == home_id:
                try:
                    return int(home.uid)
                except ValueError as exc:
                    raise MijiaAPIException("家庭所有者 uid 无效，未获取设备清单") from exc
        raise MijiaAPIException("请求家庭不存在于已验证的家庭清单")

    def get_by_id(self, device_id: str, credential: Credential) -> Optional[Device]:
        """根据ID获取设备

        Args:
            device_id: 设备ID
            credential: 用户凭据

        Returns:
            设备对象，不存在返回None
        """
        device_id = _inventory_identifier(device_id, "device did")
        # 检查缓存
        cache_key = f"device:{device_id}"
        cached = self._cache.get(cache_key, namespace=credential.user_id)
        if cached is not None:
            try:
                device = _device_from_payload(cached)
                if device.did != device_id:
                    raise MijiaAPIException("设备缓存 did 与请求不符")
                return device
            except MijiaAPIException:
                self._cache.invalidate(cache_key, namespace=credential.user_id)

        homes = HomeRepositoryImpl(self._http, self._cache).get_all(credential)

        # 遍历每个家庭查找设备
        for home in homes:
            devices = self.get_all(home.id, credential)
            for device in devices:
                if device.did == device_id:
                    # 缓存设备信息
                    self._cache.set(
                        cache_key, device.model_dump(), ttl=300, namespace=credential.user_id
                    )
                    return device

        return None

    def get_properties(self, device_id: str, credential: Credential) -> List[DeviceProperty]:
        """获取设备属性

        Args:
            device_id: 设备ID
            credential: 用户凭据

        Returns:
            设备属性列表
        """
        # 检查缓存
        cache_key = f"device:{device_id}:properties"
        cached = self._cache.get(cache_key, namespace=credential.user_id)
        if cached:
            return [DeviceProperty.model_validate(p) for p in cached]

        # 从API获取
        response = self._http.post(
            "/miotspec/prop/get", json={"did": device_id}, credential=credential
        )

        # 解析属性列表
        properties_data = response.get("result", [])
        properties = []
        for prop_data in properties_data:
            # 这里需要根据实际API响应格式解析
            # 暂时使用简化的映射
            prop = DeviceProperty(
                siid=prop_data.get("siid", 0),
                piid=prop_data.get("piid", 0),
                name=prop_data.get("name", ""),
                type=prop_data.get("type", "string"),
                access=prop_data.get("access", "read_write"),
                value=prop_data.get("value"),
            )
            properties.append(prop)

        # 缓存结果（TTL=30秒，设备状态变化较快）
        self._cache.set(
            cache_key,
            [p.model_dump() for p in properties],
            ttl=30,
            namespace=credential.user_id,
        )

        return properties

    def set_property(
        self, device_id: str, siid: int, piid: int, value: Any, credential: Credential
    ) -> bool:
        """设置设备属性

        Args:
            device_id: 设备ID
            siid: 服务ID
            piid: 属性ID
            value: 属性值
            credential: 用户凭据

        Returns:
            设置成功返回True，失败返回False
        """
        # 调用API设置属性（使用旧项目的参数格式）
        params = [{"did": device_id, "siid": siid, "piid": piid, "value": value}]
        response = self._http.post(
            "/miotspec/prop/set",
            json={"params": params},
            credential=credential,
        )

        if (
            isinstance(response, dict)
            and type(response.get("code")) is int
            and response["code"] != 0
        ):
            return False
        result = _control_result(response)
        if not isinstance(result, list) or len(result) != 1:
            raise _unknown_ack()
        success = _confirmed_miot_ack(result[0], params[0])["code"] == 0

        if success:
            # 失效相关缓存
            self._invalidate_control_cache(device_id, credential)

        return success

    def call_action(
        self, device_id: str, siid: int, aiid: int, params: Dict[str, Any], credential: Credential
    ) -> Any:
        """调用设备操作

        Args:
            device_id: 设备ID
            siid: 服务ID
            aiid: 操作ID
            params: 操作参数字典，会被转换为参数值列表
            credential: 用户凭据

        Returns:
            操作结果
        """
        # 将参数字典转换为参数值列表
        # 如果 params 是空字典，则使用空列表
        # 如果 params 有值，则提取值列表
        param_values = list(params.values()) if params else []

        # 构建请求参数（使用旧版本的格式）
        request_data = {"did": device_id, "siid": siid, "aiid": aiid}

        # 只有当有参数时才添加 value 字段
        if param_values:
            request_data["value"] = param_values

        # 调用API执行操作（使用 params 包装）
        response = self._http.post(
            "/miotspec/action",
            json={"params": request_data},
            credential=credential,
        )

        result = _confirmed_miot_ack(_control_result(response), request_data)
        # 失效相关缓存（操作可能改变设备状态）
        self._invalidate_control_cache(device_id, credential)

        return result

    def batch_get_properties(
        self, requests: List[Dict[str, Any]], credential: Credential
    ) -> List[Dict[str, Any]]:
        """批量获取属性

        Args:
            requests: 请求列表，每个请求包含did、siid、piid
            credential: 用户凭据

        Returns:
            结果列表
        """
        # 调用批量获取API（使用旧项目的参数格式）
        response = self._http.post(
            "/miotspec/prop/get", json={"params": requests, "datasource": 1}, credential=credential
        )

        result: List[Dict[str, Any]] = response.get("result", [])
        return result

    def batch_set_properties(
        self, requests: List[Dict[str, Any]], credential: Credential
    ) -> List[Dict[str, Any]]:
        """批量设置属性

        Args:
            requests: 请求列表，每个请求包含did、siid、piid、value
            credential: 用户凭据

        Returns:
            结果列表
        """
        # 调用批量设置API（使用旧项目的参数格式）
        response = self._http.post(
            "/miotspec/prop/set", json={"params": requests}, credential=credential
        )

        result = _control_result(response)
        if not isinstance(result, list) or len(result) != len(requests):
            raise _unknown_ack()
        for item, target in zip(result, requests):
            _confirmed_miot_ack(item, target)

        # 失效所有相关设备的缓存
        device_ids = {req.get("did") for req in requests if req.get("did")}
        for device_id in device_ids:
            self._invalidate_control_cache(device_id, credential)

        return result

    def _invalidate_control_cache(self, device_id: str, credential: Credential) -> None:
        try:
            self._cache.invalidate_pattern(f"{credential.user_id}:device:{device_id}")
        except Exception as exc:
            logger.warning("控制后的缓存失效失败", extra={"error_type": type(exc).__name__})

    def _parse_device_status(self, is_online: Any) -> DeviceStatus:
        """解析设备在线状态

        Args:
            is_online: API返回的在线状态（可能是bool、int或其他类型）

        Returns:
            DeviceStatus枚举值
        """
        if is_online is None:
            return DeviceStatus.UNKNOWN
        if isinstance(is_online, bool):
            return DeviceStatus.ONLINE if is_online else DeviceStatus.OFFLINE
        if isinstance(is_online, int):
            return DeviceStatus.ONLINE if is_online == 1 else DeviceStatus.OFFLINE
        return DeviceStatus.UNKNOWN
