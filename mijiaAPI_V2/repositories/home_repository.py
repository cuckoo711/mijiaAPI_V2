"""家庭仓储实现

基于HTTP的家庭仓储实现，支持缓存。
"""

from typing import Any, List, Optional

from ..domain.exceptions import MijiaAPIException
from ..domain.models import Credential, Home
from ..infrastructure.cache_manager import CacheManager
from ..infrastructure.http_client import HttpClient
from .interfaces import IHomeRepository


def _inventory_identifier(value: Any, label: str) -> str:
    if type(value) not in (str, int) or not str(value).strip():
        raise MijiaAPIException(f"清单缺少有效的 {label}")
    return str(value).strip()


def _home_from_payload(payload: Any, *, cached: bool = False) -> Home:
    if not isinstance(payload, dict):
        raise MijiaAPIException("家庭清单项必须为对象")
    try:
        return Home(
            id=_inventory_identifier(payload.get("id"), "home id"),
            uid=_inventory_identifier(payload.get("uid"), "home owner uid"),
            name=payload.get("name", ""),
            rooms=payload.get("rooms" if cached else "roomlist", []),
        )
    except MijiaAPIException:
        raise
    except Exception as exc:
        raise MijiaAPIException("家庭清单项格式无效") from exc


def _home_collection(payloads: Any, *, cached: bool = False) -> List[Home]:
    if not isinstance(payloads, list):
        raise MijiaAPIException("家庭清单必须为列表")
    homes = [_home_from_payload(payload, cached=cached) for payload in payloads]
    if len({home.id for home in homes}) != len(homes):
        raise MijiaAPIException("家庭清单包含重复 id")
    return homes


def _home_response(response: Any) -> List[Home]:
    if (
        not isinstance(response, dict)
        or type(response.get("code")) is not int
        or response["code"] != 0
    ):
        raise MijiaAPIException("家庭清单响应未明确成功")
    result = response.get("result")
    if not isinstance(result, dict) or "homelist" not in result:
        raise MijiaAPIException("家庭清单响应缺少 result/homelist")
    if "has_more" in result and (
        type(result["has_more"]) not in (bool, int) or result["has_more"] != 0
    ):
        raise MijiaAPIException("家庭清单未完整返回")
    return _home_collection(result["homelist"])


class HomeRepositoryImpl(IHomeRepository):
    """家庭仓储实现

    基于HTTP API的家庭仓储实现，集成缓存管理。
    """

    def __init__(self, http_client: HttpClient, cache_manager: CacheManager):
        """初始化家庭仓储

        Args:
            http_client: HTTP客户端
            cache_manager: 缓存管理器
        """
        self._http = http_client
        self._cache = cache_manager

    def get_all(self, credential: Credential) -> List[Home]:
        """获取所有家庭

        Args:
            credential: 用户凭据

        Returns:
            已完整确认的家庭列表，明确空列表表示账号没有家庭

        Raises:
            MijiaAPIException: 清单缺失、畸形或不完整，调用方应保留旧快照
        """
        # 检查缓存
        cache_key = "homes"
        cached = self._cache.get(cache_key, namespace=credential.user_id)
        if cached is not None:
            try:
                return _home_collection(cached, cached=True)
            except MijiaAPIException:
                self._cache.invalidate(cache_key, namespace=credential.user_id)

        # 从API获取（使用旧项目的URI和参数）
        uri = "/v2/homeroom/gethome_merged"
        data = {
            "fg": True,
            "fetch_share": True,
            "fetch_share_dev": True,
            "fetch_cariot": True,
            "limit": 300,
            "app_ver": 7,
            "plat_form": 0,
        }
        response = self._http.post(uri, json=data, credential=credential)

        homes = _home_response(response)

        # 缓存结果（TTL=300秒）
        self._cache.set(
            cache_key, [h.model_dump() for h in homes], ttl=300, namespace=credential.user_id
        )

        return homes

    def get_by_id(self, home_id: str, credential: Credential) -> Optional[Home]:
        """根据ID获取家庭

        Args:
            home_id: 家庭ID
            credential: 用户凭据

        Returns:
            家庭对象，不存在返回None
        """
        home_id = _inventory_identifier(home_id, "home id")
        # 检查缓存
        cache_key = f"home:{home_id}"
        cached = self._cache.get(cache_key, namespace=credential.user_id)
        if cached is not None:
            try:
                home = _home_from_payload(cached, cached=True)
                if home.id != home_id:
                    raise MijiaAPIException("家庭缓存 id 与请求不符")
                return home
            except MijiaAPIException:
                self._cache.invalidate(cache_key, namespace=credential.user_id)

        # 从所有家庭中查找
        homes = self.get_all(credential)
        for home in homes:
            if home.id == home_id:
                # 缓存单个家庭
                self._cache.set(cache_key, home.model_dump(), ttl=300, namespace=credential.user_id)
                return home

        return None
