"""智能服务

封装智能相关的业务逻辑。
"""

from typing import List

from mijiaAPI_V2.domain.models import Credential, Scene
from mijiaAPI_V2.repositories.interfaces import ISceneRepository


class SceneService:
    """智能服务

    封装智能管理和执行的业务逻辑。
    """

    def __init__(self, scene_repo: ISceneRepository):
        """初始化智能服务

        Args:
            scene_repo: 智能仓储接口实现
        """
        self._scene_repo = scene_repo

    def get_scenes(self, home_id: str, credential: Credential, owner_uid: str = None) -> List[Scene]:
        """获取智能列表

        Args:
            home_id: 家庭ID
            credential: 用户凭据
            owner_uid: 家庭拥有者用户ID（共享家庭时需要传入家庭拥有者的uid）

        Returns:
            智能列表
        """
        return self._scene_repo.get_all(home_id, credential, owner_uid)

    def execute_scene(self, scene_id: str, home_id: str, credential: Credential) -> bool:
        """执行智能

        Args:
            scene_id: 智能ID
            home_id: 家庭ID
            credential: 用户凭据

        Returns:
            执行是否成功
        """
        return self._scene_repo.execute(scene_id, home_id, credential)
