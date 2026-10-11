"""设备服务

封装设备相关的业务逻辑。
"""

from typing import Any, Dict, List, Optional

from mijiaAPI_V2.domain.exceptions import (
    DeviceNotFoundError,
    ExecutionUnknownError,
    MijiaAPIException,
    PropertyReadOnlyError,
    ValidationError,
)
from mijiaAPI_V2.domain.models import Credential, Device, DeviceAction, DeviceProperty
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.repositories.interfaces import DeviceSpec, IDeviceRepository, IDeviceSpecRepository


def normalize_property_requests(requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize the public SDK alias before any batch is dispatched."""
    normalized = []
    for request in requests:
        if not isinstance(request, dict):
            raise ValidationError("批量属性请求必须为对象")
        did, legacy = request.get("did"), request.get("device_id")
        if did is not None and legacy is not None and str(did) != str(legacy):
            raise ValidationError("did 与 device_id 不一致")
        device_id = did if did is not None else legacy
        if type(device_id) not in (str, int) or not str(device_id).strip():
            raise ValidationError("批量属性请求必须包含 did")
        for field in ("siid", "piid"):
            if type(request.get(field)) is not int or request[field] <= 0:
                raise ValidationError(f"{field} 必须为正整数")
        if "value" not in request:
            raise ValidationError("批量属性请求缺少 value")
        normalized.append(
            {
                "did": str(device_id),
                "siid": request["siid"],
                "piid": request["piid"],
                "value": request["value"],
                **({"home_id": request["home_id"]} if "home_id" in request else {}),
            }
        )
    return normalized


def _read_property_identity(item: Dict[str, Any]) -> tuple[str, int, int]:
    if not isinstance(item, dict):
        raise ValidationError("属性读取请求必须为对象")
    did = item.get("did", item.get("device_id"))
    if "did" in item and "device_id" in item and str(item["did"]) != str(item["device_id"]):
        raise ValidationError("did 与 device_id 不一致")
    if type(did) not in (str, int) or not str(did).strip():
        raise ValidationError("属性读取必须包含 did")
    for field in ("siid", "piid"):
        if type(item.get(field)) is not int or item[field] <= 0:
            raise ValidationError(f"{field} 必须为正整数")
    return str(did), item["siid"], item["piid"]


def _confirmed_property_reads(
    response: Any, identities: List[tuple[str, int, int]]
) -> Dict[tuple[str, int, int], Dict[str, Any]]:
    if not isinstance(response, list) or len(response) != len(identities):
        raise MijiaAPIException("属性读取响应不完整，无法确认实时状态")
    expected = set(identities)
    confirmed: Dict[tuple[str, int, int], Dict[str, Any]] = {}
    for item in response:
        try:
            identity = _read_property_identity(item)
        except ValidationError as exc:
            raise MijiaAPIException("属性读取响应缺少设备或属性身份") from exc
        if identity not in expected or identity in confirmed:
            raise MijiaAPIException("属性读取响应身份不匹配，无法确认实时状态")
        if type(item.get("code")) is not int:
            raise MijiaAPIException("属性读取响应缺少有效错误码")
        if item["code"] == 0 and "value" not in item:
            raise MijiaAPIException("属性读取成功响应缺少值，无法确认实时状态")
        confirmed[identity] = {**item, "did": identity[0]}
    return confirmed


def _ordered_action_params(action: DeviceAction, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate named inputs, then preserve the action's positional order."""
    if not isinstance(params, dict):
        raise ValidationError("操作参数必须为对象")
    ordered: Dict[str, Any] = {}
    consumed = set()
    for parameter in action.parameters:
        aliases = [parameter.name]
        if parameter.piid is not None:
            aliases.append(str(parameter.piid))
        keys = [key for key in dict.fromkeys(aliases) if key in params]
        if len(keys) > 1:
            raise ValidationError(f"操作参数重复: {parameter.name}")
        if not keys:
            if parameter.required:
                raise ValidationError(f"操作参数缺失: {parameter.name}")
            continue
        key = keys[0]
        if key in consumed or not parameter.validate_value(params[key]):
            raise ValidationError(f"操作参数无效: {parameter.name}")
        consumed.add(key)
        ordered[str(parameter.piid) if parameter.piid is not None else parameter.name] = params[key]
    if set(params) != consumed:
        raise ValidationError("存在未声明的操作参数")
    return ordered


class DeviceService:
    """设备服务

    封装设备相关的业务逻辑，包括设备查询、属性控制、操作调用等。
    """

    def __init__(
        self,
        device_repo: IDeviceRepository,
        spec_repo: IDeviceSpecRepository,
        cache_manager: CacheManager,
    ) -> None:
        """初始化设备服务

        Args:
            device_repo: 设备仓储接口
            spec_repo: 设备规格仓储接口
            cache_manager: 缓存管理器
        """
        self._device_repo = device_repo
        self._spec_repo = spec_repo
        self._cache = cache_manager

    def get_devices(self, home_id: str, credential: Credential) -> List[Device]:
        """获取设备列表

        Args:
            home_id: 家庭ID
            credential: 用户凭据

        Returns:
            设备列表
        """
        return self._device_repo.get_all(home_id, credential)

    def get_device_by_id(self, device_id: str, credential: Credential) -> Optional[Device]:
        """获取单个设备

        Args:
            device_id: 设备ID
            credential: 用户凭据

        Returns:
            设备对象，不存在返回None
        """
        return self._device_repo.get_by_id(device_id, credential)

    def get_device_properties(self, device_id: str, credential: Credential) -> List[DeviceProperty]:
        """获取设备属性

        Args:
            device_id: 设备ID
            credential: 用户凭据

        Returns:
            设备属性列表
        """
        return self._device_repo.get_properties(device_id, credential)

    def set_device_property(
        self, device_id: str, siid: int, piid: int, value: Any, credential: Credential
    ) -> bool:
        """设置设备属性

        包含完整的验证流程：
        1. 检查设备是否存在
        2. 获取设备规格
        3. 验证属性是否可写
        4. 验证属性值是否有效

        Args:
            device_id: 设备ID
            siid: 服务ID
            piid: 属性ID
            value: 属性值
            credential: 用户凭据

        Returns:
            设置成功返回True，失败返回False

        Raises:
            DeviceNotFoundError: 设备不存在
            PropertyReadOnlyError: 属性只读
            ValidationError: 属性值无效
        """
        self._validate_property(device_id, siid, piid, value, credential)
        return self._device_repo.set_property(device_id, siid, piid, value, credential)

    def _required_spec(self, device_id: str, credential: Credential) -> DeviceSpec:
        device = self.get_device_by_id(device_id, credential)
        if not device:
            raise DeviceNotFoundError(f"设备不存在: {device_id}")
        try:
            spec = self._spec_repo.get_spec(device.model)
        except Exception as exc:
            raise RuntimeError(f"设备规格获取失败，未执行控制: {exc}") from exc
        if spec is None:
            raise ValidationError("设备规格不存在，未执行控制")
        return spec

    def _validate_property(
        self,
        device_id: str,
        siid: int,
        piid: int,
        value: Any,
        credential: Credential,
        spec: Optional[DeviceSpec] = None,
    ) -> None:
        if type(siid) is not int or type(piid) is not int or siid <= 0 or piid <= 0:
            raise ValidationError("siid 和 piid 必须为正整数")
        spec = spec if spec is not None else self._required_spec(device_id, credential)
        prop = next((p for p in spec.properties if p.siid == siid and p.piid == piid), None)
        if prop is None:
            raise ValidationError("设备规格未声明该属性")
        if not prop.is_writable():
            raise PropertyReadOnlyError(f"属性只读: {prop.name}")
        if not prop.validate_value(value):
            raise ValidationError(f"属性值无效: {prop.name}")

    def call_device_action(
        self,
        device_id: str,
        siid: int,
        aiid: int,
        params: Dict[str, Any],
        credential: Credential,
    ) -> Any:
        """调用设备操作

        Args:
            device_id: 设备ID
            siid: 服务ID
            aiid: 操作ID
            params: 操作参数
            credential: 用户凭据

        Returns:
            操作执行结果
        """
        if type(siid) is not int or type(aiid) is not int or siid <= 0 or aiid <= 0:
            raise ValidationError("siid 和 aiid 必须为正整数")
        spec = self._required_spec(device_id, credential)
        action = next((a for a in spec.actions if a.siid == siid and a.aiid == aiid), None)
        if action is None:
            raise ValidationError("设备规格未声明该操作")
        ordered = _ordered_action_params(action, params)
        return self._device_repo.call_action(device_id, siid, aiid, ordered, credential)

    def batch_control_devices(
        self, requests: List[Dict[str, Any]], credential: Credential
    ) -> List[Dict[str, Any]]:
        """批量控制设备

        自动分组处理，每组最多20个请求，避免单次请求过大。

        Args:
            requests: 批量请求列表，每个请求包含设备ID、siid、piid、value等信息
            credential: 用户凭据

        Returns:
            批量操作结果列表
        """
        requests = normalize_property_requests(requests)
        specs: Dict[str, DeviceSpec] = {}
        for request in requests:
            did = request["did"]
            if did not in specs:
                specs[did] = self._required_spec(did, credential)
            self._validate_property(
                did, request["siid"], request["piid"], request["value"], credential, specs[did]
            )
        requests = [{k: v for k, v in request.items() if k != "home_id"} for request in requests]
        # Every item is validated before sending the first batch.
        batch_size = 20
        results: List[Dict[str, Any]] = []

        for i in range(0, len(requests), batch_size):
            batch = requests[i : i + batch_size]
            try:
                batch_results = self._device_repo.batch_set_properties(batch, credential)
            except Exception as exc:
                if results:
                    raise ExecutionUnknownError(
                        "批量控制已收到部分执行结果，后续结果未完成；请先核对设备状态",
                        context={
                            **(exc.context if isinstance(exc, ExecutionUnknownError) else {}),
                            "completed_count": len(results),
                            "error_type": type(exc).__name__,
                        },
                    ) from exc
                raise
            results.extend(batch_results)

        return results

    def get_device_spec(self, model: str) -> Optional[DeviceSpec]:
        """获取设备规格，底层异常时返回 None。

        Args:
            model: 设备型号

        Returns:
            设备规格对象，获取失败或不存在返回 None
        """
        try:
            return self._spec_repo.get_spec(model)
        except Exception:
            return None

    def batch_get_properties(
        self, requests: List[Dict[str, Any]], credential: Credential
    ) -> List[Dict[str, Any]]:
        """批量读取设备属性值。

        Args:
            requests: 请求列表，每个请求包含 did、siid、piid
            credential: 用户凭据

        Returns:
            结果列表，每个结果包含 code、siid、piid、value
        """
        identities = [_read_property_identity(request) for request in requests]
        unique = list(dict.fromkeys(identities))
        results: Dict[tuple[str, int, int], Dict[str, Any]] = {}
        for offset in range(0, len(unique), 50):
            group = unique[offset : offset + 50]
            batch = [{"did": did, "siid": siid, "piid": piid} for did, siid, piid in group]
            response = self._device_repo.batch_get_properties(batch, credential)
            results.update(_confirmed_property_reads(response, group))
        return [dict(results[identity]) for identity in identities]
