"""设备规格仓储实现

从网络或缓存获取设备规格信息，并解析为标准化的设备规格模型。
"""

import threading
from typing import Dict, Optional

import httpx

from ..core.logging import get_logger
from ..domain.exceptions import MijiaAPIException
from ..domain.models import ActionParameter, DeviceAction, DeviceProperty, PropertyAccess, PropertyType
from ..infrastructure.cache_manager import CacheManager
from ..infrastructure.http_client import HttpClient
from .interfaces import DeviceSpec, IDeviceSpecRepository

logger = get_logger(__name__)

# miot-spec.org 全量设备清单接口。该响应体约 1.8MB / 上万条记录，
# 每次同步都对每台设备重新拉一遍会造成明显的 CPU/网络占用。
_INSTANCES_URL = "https://miot-spec.org/miot-spec-v2/instances?status=released"
_SPEC_INSTANCE_URL = "https://miot-spec.org/miot-spec-v2/instance"
_INSTANCES_CACHE_TTL = 24 * 3600  # 全量清单变化不频繁，缓存 24 小时


class DeviceSpecRepositoryImpl(IDeviceSpecRepository):
    """设备规格仓储实现

    负责从米家规格网站获取设备规格信息，解析并缓存到本地。
    设备规格信息包括：
    - 设备名称和型号
    - 属性列表（SIID、PIID、名称、类型、访问权限、值范围等）
    - 操作列表（SIID、AIID、名称、参数列表）

    缓存策略：
    - 全量 instances 清单缓存 24 小时（L3 文件缓存 + 进程内 model->type 映射）
    - 单个设备规格永久缓存到文件（L3 缓存）
    - 首次获取从网络加载，后续从缓存加载
    """

    # 进程内共享：不同实例可以复用同一份 model→type 映射，避免每次同步都反序列化。
    _model_type_map_lock = threading.Lock()
    _model_type_map: Optional[Dict[str, str]] = None

    def __init__(self, http_client: HttpClient, cache_manager: CacheManager):
        """初始化设备规格仓储

        Args:
            http_client: HTTP客户端
            cache_manager: 缓存管理器
        """
        self._http = http_client
        self._cache = cache_manager

    def get_spec(self, model: str) -> Optional[DeviceSpec]:
        """获取设备规格

        首先从缓存查找，如果不存在则从网络获取并缓存。

        Args:
            model: 设备型号（如 "xiaomi.light.ceiling1"）

        Returns:
            设备规格对象，获取失败返回None

        Raises:
            MijiaAPIException: 网络请求失败或解析失败
        """
        # 检查缓存（使用永久缓存，TTL设置为很大的值）
        cache_key = f"device_spec:{model}"
        cached = self._cache.get(cache_key, namespace="specs")

        if cached:
            logger.info(f"从缓存加载设备规格: {model}")
            try:
                return DeviceSpec.model_validate(cached)
            except Exception as e:
                logger.warning(f"缓存的设备规格解析失败: {e}", extra={"model": model})
                # 缓存数据损坏，清除缓存并重新获取
                self._cache.invalidate(cache_key, namespace="specs")

        # 从网络获取
        logger.info(f"从网络获取设备规格: {model}")
        try:
            spec = self._fetch_spec_from_network(model)
            if spec:
                # 缓存到文件（永久缓存，TTL设置为1年）
                self.cache_spec(model, spec)
            return spec
        except Exception as e:
            logger.error(f"获取设备规格失败: {e}", extra={"model": model}, exc_info=e)
            raise MijiaAPIException(f"获取设备规格失败: {model}") from e

    def cache_spec(self, model: str, spec: DeviceSpec) -> None:
        """缓存设备规格到文件

        Args:
            model: 设备型号
            spec: 设备规格对象
        """
        cache_key = f"device_spec:{model}"
        # 使用很长的TTL（1年）实现永久缓存
        self._cache.set(cache_key, spec.model_dump(), ttl=365 * 24 * 3600, namespace="specs")
        logger.info(f"设备规格已缓存: {model}")

    def _fetch_spec_from_network(self, model: str) -> Optional[DeviceSpec]:
        """从网络获取设备规格

        Args:
            model: 设备型号

        Returns:
            设备规格对象，获取失败返回None

        Raises:
            MijiaAPIException: 网络请求失败或解析失败
        """
        try:
            device_type = self._resolve_device_type(model)
            if not device_type:
                raise MijiaAPIException(f"未找到设备型号 {model} 的规格定义")

            headers = {"User-Agent": "mijiaAPI_V2/2.0.0"}
            spec_url = f"{_SPEC_INSTANCE_URL}?type={device_type}"
            response = httpx.get(spec_url, headers=headers, timeout=30)
            response.raise_for_status()
            spec_data = response.json()

            # 解析规格数据（使用标准miot-spec格式）
            return self._parse_spec_standard(model, spec_data)

        except MijiaAPIException:
            raise
        except httpx.HTTPError as e:
            logger.error(f"获取设备规格网络错误: {e}", extra={"model": model})
            raise MijiaAPIException(f"获取设备规格网络错误: {str(e)}") from e
        except Exception as e:
            logger.error(f"解析设备规格失败: {e}", extra={"model": model})
            raise MijiaAPIException(f"解析设备规格失败: {str(e)}") from e

    def _resolve_device_type(self, model: str) -> Optional[str]:
        """通过 miot-spec.org 的 instances 清单把设备 model 解析为 type。

        清单响应约 1.8MB / 上万条，进程内共享一份 model→type 映射，避免每台设备
        同步时都重复反序列化并线性扫描全表。
        """
        mapping = self._get_model_type_mapping()
        return mapping.get(model)

    def _get_model_type_mapping(self) -> Dict[str, str]:
        """获取（或懒加载）model→type 映射。

        优先级：进程内内存 → CacheManager 缓存（文件层，24h TTL）→ 网络获取。
        """
        cached_map = DeviceSpecRepositoryImpl._model_type_map
        if cached_map is not None:
            return cached_map

        with DeviceSpecRepositoryImpl._model_type_map_lock:
            # 双检锁，避免并发同步时重复下载。
            cached_map = DeviceSpecRepositoryImpl._model_type_map
            if cached_map is not None:
                return cached_map

            cache_key = "miot_spec:instances_model_map"
            cached = self._cache.get(cache_key, namespace="specs")
            if isinstance(cached, dict) and cached and all(
                isinstance(k, str) and isinstance(v, str) for k, v in cached.items()
            ):
                logger.info(f"从缓存加载设备型号映射（{len(cached)} 条）")
                DeviceSpecRepositoryImpl._model_type_map = cached
                return cached
            if cached is not None:
                # 缓存内容格式不对（例如被单个 spec 的 mock 数据污染），忽略并重新拉取
                logger.warning("缓存的设备型号映射格式异常，忽略并重新获取")

            mapping = self._fetch_model_type_mapping_from_network()
            self._cache.set(
                cache_key, mapping, ttl=_INSTANCES_CACHE_TTL, namespace="specs"
            )
            DeviceSpecRepositoryImpl._model_type_map = mapping
            return mapping

    def _fetch_model_type_mapping_from_network(self) -> Dict[str, str]:
        """一次性从网络下载 instances 清单并建立 model→type 映射。"""
        headers = {"User-Agent": "mijiaAPI_V2/2.0.0"}
        logger.info(f"从网络获取设备型号映射: {_INSTANCES_URL}")
        response = httpx.get(_INSTANCES_URL, headers=headers, timeout=30)
        response.raise_for_status()
        instances_data = response.json()
        mapping: Dict[str, str] = {}
        for instance in instances_data.get("instances", []):
            model = instance.get("model")
            device_type = instance.get("type")
            if isinstance(model, str) and isinstance(device_type, str):
                # 同一 model 出现多条时保留首个；官方数据未见冲突，保持稳定。
                mapping.setdefault(model, device_type)
        logger.info(f"设备型号映射构建完成，共 {len(mapping)} 条")
        return mapping

    @classmethod
    def clear_model_type_mapping_cache(cls) -> None:
        """清空进程内的 model→type 映射缓存（供测试或运维强制刷新使用）。"""
        with cls._model_type_map_lock:
            cls._model_type_map = None
    
    def _parse_spec_standard(self, model: str, spec_data: dict) -> DeviceSpec:
        """解析设备规格数据（标准miot-spec格式）

        Args:
            model: 设备型号
            spec_data: 从miot-spec.org获取的标准格式规格数据

        Returns:
            设备规格对象

        Raises:
            MijiaAPIException: 解析失败
        """
        try:
            # 提取设备名称
            device_name = spec_data.get("description", model)

            # 解析属性列表
            properties = []
            actions = []

            # 遍历服务列表
            services = spec_data.get("services", [])
            for service in services:
                siid = service.get("iid")
                if not siid:
                    continue

                # 解析属性
                for prop in service.get("properties", []):
                    device_property = self._parse_property(siid, prop)
                    if device_property:
                        properties.append(device_property)

                # 解析操作
                for action in service.get("actions", []):
                    device_action = self._parse_action(siid, action)
                    if device_action:
                        actions.append(device_action)

            return DeviceSpec(model=model, name=device_name, properties=properties, actions=actions)

        except Exception as e:
            logger.error(f"解析设备规格数据失败: {e}", extra={"model": model})
            raise MijiaAPIException(f"解析设备规格数据失败: {str(e)}") from e

    def _parse_property(self, siid: int, prop_data: dict) -> Optional[DeviceProperty]:
        """解析设备属性（标准miot-spec格式）

        Args:
            siid: 服务ID
            prop_data: 属性数据

        Returns:
            设备属性对象，解析失败返回None
        """
        try:
            piid = prop_data.get("iid")
            if not piid:
                return None

            # 属性名称
            name = prop_data.get("description", f"property_{piid}")

            # 属性类型
            prop_type = self._parse_property_type(prop_data.get("format", "string"))

            # 访问权限
            access = self._parse_property_access(prop_data.get("access", []))

            # 值范围
            value_range = None
            if "value-range" in prop_data:
                range_data = prop_data["value-range"]
                # 处理两种格式：字典格式和列表格式
                if isinstance(range_data, dict):
                    # 字典格式: {"min": 0, "max": 100, "step": 1}
                    value_range = [range_data.get("min"), range_data.get("max")]
                    # 如果有步长，也添加进去
                    if "step" in range_data:
                        value_range.append(range_data.get("step"))
                elif isinstance(range_data, list):
                    # 列表格式: [min, max, step]
                    value_range = range_data

            # 枚举值列表
            value_list = None
            if "value-list" in prop_data:
                value_list = [item.get("value") for item in prop_data["value-list"]]

            return DeviceProperty(
                siid=siid,
                piid=piid,
                name=name,
                type=prop_type,
                access=access,
                value_range=value_range,
                value_list=value_list,
            )

        except Exception as e:
            logger.warning(f"解析属性失败: {e}", extra={"siid": siid, "prop_data": prop_data})
            return None

    def _parse_property_type(self, format_str: str) -> PropertyType:
        """解析属性类型

        Args:
            format_str: 格式字符串（如 "bool", "int32", "uint8", "float", "string"）

        Returns:
            属性类型枚举
        """
        format_lower = format_str.lower()

        if format_lower == "bool":
            return PropertyType.BOOL
        elif "int" in format_lower and "uint" not in format_lower:
            return PropertyType.INT
        elif "uint" in format_lower:
            return PropertyType.UINT
        elif "float" in format_lower or "double" in format_lower:
            return PropertyType.FLOAT
        else:
            return PropertyType.STRING

    def _parse_property_access(self, access_list: list) -> PropertyAccess:
        """解析属性访问权限

        Args:
            access_list: 访问权限列表（如 ["read"], ["write"], ["read", "write"]）

        Returns:
            属性访问权限枚举
        """
        has_read = "read" in access_list
        has_write = "write" in access_list

        if has_read and has_write:
            return PropertyAccess.READ_WRITE
        elif has_read:
            return PropertyAccess.READ_ONLY
        elif has_write:
            return PropertyAccess.WRITE_ONLY
        else:
            # 默认为只读
            return PropertyAccess.READ_ONLY

    def _parse_action(self, siid: int, action_data: dict) -> Optional[DeviceAction]:
        """解析设备操作

        Args:
            siid: 服务ID
            action_data: 操作数据

        Returns:
            设备操作对象，解析失败返回None
        """
        try:
            aiid = action_data.get("iid")
            if not aiid:
                return None

            # 操作名称
            name = action_data.get("description", f"action_{aiid}")

            # 参数列表（暂时不解析参数，后续可以扩展）
            parameters: list[ActionParameter] = []

            return DeviceAction(siid=siid, aiid=aiid, name=name, parameters=parameters)

        except Exception as e:
            logger.warning(f"解析操作失败: {e}", extra={"siid": siid, "action_data": action_data})
            return None
