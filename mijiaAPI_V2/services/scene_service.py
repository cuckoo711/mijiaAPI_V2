"""场景服务

封装场景相关的业务逻辑。
"""

from typing import List

from mijiaAPI_V2.domain.models import Credential, Scene
from mijiaAPI_V2.repositories.interfaces import ISceneRepository


class SceneService:
    """场景服务

    封装场景管理和执行的业务逻辑。
    """

    def __init__(self, scene_repo: ISceneRepository):
        """初始化场景服务

        Args:
            scene_repo: 场景仓储接口实现
        """
        self._scene_repo = scene_repo

    def get_scenes(self, home_id: str, credential: Credential) -> List[Scene]:
        """获取场景列表

        Args:
            home_id: 家庭ID
            credential: 用户凭据

        Returns:
            场景列表
        """
        return self._scene_repo.get_all(home_id, credential)

    def execute_scene(self, scene_id: str, home_id: str, credential: Credential) -> bool:
        """执行场景

        Args:
            scene_id: 场景ID
            home_id: 家庭ID
            credential: 用户凭据

        Returns:
            执行是否成功
        """
        return self._scene_repo.execute(scene_id, home_id, credential)
