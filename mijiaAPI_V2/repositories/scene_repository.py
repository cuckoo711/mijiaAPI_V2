"""智能仓储实现

基于HTTP的智能仓储实现。
"""

from typing import List, Optional

from ..domain.exceptions import ExecutionUnknownError, MijiaAPIException
from ..domain.models import Credential, Scene
from ..infrastructure.http_client import HttpClient
from .interfaces import ISceneRepository


class SceneRepositoryImpl(ISceneRepository):
    """智能仓储实现

    基于HTTP API的智能仓储实现。
    """

    def __init__(self, http_client: HttpClient):
        """初始化智能仓储

        Args:
            http_client: HTTP客户端
        """
        self._http = http_client

    def get_all(
        self, home_id: str, credential: Credential, owner_uid: Optional[str] = None
    ) -> List[Scene]:
        """获取家庭下所有智能

        Args:
            home_id: 家庭ID
            credential: 用户凭据
            owner_uid: 家庭拥有者用户ID（共享家庭时需要传入家庭拥有者的uid）

        Returns:
            智能列表
        """
        owner_uid = owner_uid or credential.user_id
        # 从API获取智能列表
        response = self._http.post(
            "/appgateway/miot/appsceneservice/AppSceneService/GetSimpleSceneList",
            json={
                "app_version": 12,
                "get_type": 2,
                "home_id": str(home_id),
                "owner_uid": owner_uid,
            },
            credential=credential,
        )

        # 解析智能列表
        if (
            not isinstance(response, dict)
            or type(response.get("code")) is not int
            or response["code"] != 0
        ):
            raise MijiaAPIException("场景清单响应未确认成功，已保留原有场景")
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(
            result.get("manual_scene_info_list"), list
        ):
            raise MijiaAPIException("场景清单响应缺少有效列表，已保留原有场景")
        scene_list = result["manual_scene_info_list"]
        scenes = []
        seen_ids = set()
        for scene_data in scene_list:
            scene_id = self._scene_id(scene_data)
            if scene_id in seen_ids:
                raise MijiaAPIException("场景清单包含重复ID，已保留原有场景")
            seen_ids.add(scene_id)
            # 映射API字段到领域模型
            scene = Scene(
                scene_id=scene_id,
                name=scene_data.get("name", ""),
                home_id=home_id,
                icon=scene_data.get("icon"),
                owner_uid=owner_uid,
            )
            scenes.append(scene)

        return scenes

    @staticmethod
    def _scene_id(scene_data: dict) -> str:
        value = scene_data.get("scene_id") if isinstance(scene_data, dict) else None
        if type(value) not in (str, int) or not str(value).strip():
            raise MijiaAPIException("场景清单缺少有效ID，已保留原有场景")
        if type(value) is int and value <= 0:
            raise MijiaAPIException("场景清单缺少有效ID，已保留原有场景")
        return str(value).strip()

    def execute(
        self,
        scene_id: str,
        home_id: str,
        credential: Credential,
        owner_uid: Optional[str] = None,
    ) -> bool:
        """执行智能

        Args:
            scene_id: 智能ID
            home_id: 家庭ID
            credential: 用户凭据
            owner_uid: 共享家庭拥有者用户ID，省略时使用当前用户

        Returns:
            执行成功返回True，失败返回False
        """
        # 调用API执行智能
        response = self._http.post(
            "/appgateway/miot/appsceneservice/AppSceneService/NewRunScene",
            json={
                "scene_id": scene_id,
                "scene_type": 2,
                "phone_id": "null",
                "home_id": str(home_id),
                "owner_uid": owner_uid or credential.user_id,
            },
            credential=credential,
        )

        # A missing acknowledgement does not prove the scene did not execute.
        if not isinstance(response, dict) or type(response.get("code")) is not int:
            raise ExecutionUnknownError(
                "场景执行响应缺少有效确认，结果未知；请核对场景效果，勿直接重试",
                context={"retry_safe": False},
            )
        return response["code"] == 0
