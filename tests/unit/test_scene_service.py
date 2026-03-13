"""SceneService单元测试"""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.models import Credential, Scene
from mijiaAPI_V2.repositories.interfaces import ISceneRepository
from mijiaAPI_V2.services.scene_service import SceneService


@pytest.fixture
def mock_scene_repo() -> Mock:
    """创建模拟的ISceneRepository"""
    return Mock(spec=ISceneRepository)


@pytest.fixture
def sample_credential() -> Credential:
    """创建示例凭据"""
    return Credential(
        user_id="test_user_123",
        service_token="test_token_abc",
        ssecurity="test_ssecurity_xyz",
        c_user_id="test_c_user_id",
        device_id="test_device_456",
        user_agent="iOS-14.4-6.0.103-iPhone12,1",
        expires_at=datetime.now() + timedelta(days=7),
    )


@pytest.fixture
def sample_scenes() -> list[Scene]:
    """创建示例场景列表"""
    return [
        Scene(
            scene_id="scene_001",
            name="回家模式",
            home_id="home_123",
            icon="home",
        ),
        Scene(
            scene_id="scene_002",
            name="离家模式",
            home_id="home_123",
            icon="away",
        ),
        Scene(
            scene_id="scene_003",
            name="睡眠模式",
            home_id="home_123",
            icon="sleep",
        ),
    ]


@pytest.fixture
def scene_service(mock_scene_repo: Mock) -> SceneService:
    """创建SceneService实例"""
    return SceneService(scene_repo=mock_scene_repo)


def test_scene_service_initialization(mock_scene_repo: Mock) -> None:
    """测试SceneService初始化"""
    service = SceneService(scene_repo=mock_scene_repo)
    assert service._scene_repo is mock_scene_repo


def test_get_scenes_delegates_to_repo(
    scene_service: SceneService,
    mock_scene_repo: Mock,
    sample_credential: Credential,
    sample_scenes: list[Scene],
) -> None:
    """测试get_scenes委托给scene_repo"""
    # 设置mock返回值
    mock_scene_repo.get_all.return_value = sample_scenes

    # 调用方法
    result = scene_service.get_scenes("home_123", sample_credential)

    # 验证
    mock_scene_repo.get_all.assert_called_once_with("home_123", sample_credential)
    assert result == sample_scenes
    assert len(result) == 3
    assert result[0].name == "回家模式"


def test_get_scenes_returns_empty_list_when_no_scenes(
    scene_service: SceneService,
    mock_scene_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试get_scenes在没有场景时返回空列表"""
    # 设置mock返回空列表
    mock_scene_repo.get_all.return_value = []

    # 调用方法
    result = scene_service.get_scenes("home_123", sample_credential)

    # 验证
    mock_scene_repo.get_all.assert_called_once_with("home_123", sample_credential)
    assert result == []
    assert len(result) == 0


def test_execute_scene_delegates_to_repo(
    scene_service: SceneService,
    mock_scene_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试execute_scene委托给scene_repo"""
    # 设置mock返回值
    mock_scene_repo.execute.return_value = True

    # 调用方法
    result = scene_service.execute_scene("scene_001", "home_123", sample_credential)

    # 验证
    mock_scene_repo.execute.assert_called_once_with("scene_001", "home_123", sample_credential)
    assert result is True


def test_execute_scene_returns_false_on_failure(
    scene_service: SceneService,
    mock_scene_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试execute_scene在失败时返回False"""
    # 设置mock返回False
    mock_scene_repo.execute.return_value = False

    # 调用方法
    result = scene_service.execute_scene("scene_001", "home_123", sample_credential)

    # 验证
    mock_scene_repo.execute.assert_called_once_with("scene_001", "home_123", sample_credential)
    assert result is False


def test_get_scenes_with_different_home_ids(
    scene_service: SceneService,
    mock_scene_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试get_scenes使用不同的home_id"""
    # 为不同家庭创建不同的场景
    home1_scenes = [
        Scene(scene_id="s1", name="场景1", home_id="home_001"),
    ]
    home2_scenes = [
        Scene(scene_id="s2", name="场景2", home_id="home_002"),
    ]

    # 第一次调用
    mock_scene_repo.get_all.return_value = home1_scenes
    result1 = scene_service.get_scenes("home_001", sample_credential)
    assert result1 == home1_scenes

    # 第二次调用
    mock_scene_repo.get_all.return_value = home2_scenes
    result2 = scene_service.get_scenes("home_002", sample_credential)
    assert result2 == home2_scenes

    # 验证调用次数和参数
    assert mock_scene_repo.get_all.call_count == 2
    mock_scene_repo.get_all.assert_any_call("home_001", sample_credential)
    mock_scene_repo.get_all.assert_any_call("home_002", sample_credential)


def test_execute_scene_with_different_scene_ids(
    scene_service: SceneService,
    mock_scene_repo: Mock,
    sample_credential: Credential,
) -> None:
    """测试execute_scene使用不同的scene_id"""
    # 设置mock返回值
    mock_scene_repo.execute.return_value = True

    # 执行多个场景
    scene_ids = ["scene_001", "scene_002", "scene_003"]
    home_id = "home_123"
    for scene_id in scene_ids:
        result = scene_service.execute_scene(scene_id, home_id, sample_credential)
        assert result is True

    # 验证调用次数和参数
    assert mock_scene_repo.execute.call_count == 3
    for scene_id in scene_ids:
        mock_scene_repo.execute.assert_any_call(scene_id, home_id, sample_credential)
