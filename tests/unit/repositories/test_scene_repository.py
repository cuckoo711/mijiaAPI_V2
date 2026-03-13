"""场景仓储单元测试"""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.http_client import HttpClient
from mijiaAPI_V2.repositories.scene_repository import SceneRepositoryImpl


@pytest.fixture
def mock_http_client():
    """创建Mock HTTP客户端"""
    return Mock(spec=HttpClient)


@pytest.fixture
def scene_repository(mock_http_client):
    """创建场景仓储实例"""
    return SceneRepositoryImpl(mock_http_client)


@pytest.fixture
def test_credential():
    """创建测试凭据"""
    return Credential(
        user_id="test_user",
        service_token="test_token",
        ssecurity="test_ssecurity",
        c_user_id="test_c_user",
        device_id="test_device",
        user_agent="test_agent",
        expires_at=datetime.now() + timedelta(days=7),
    )


class TestGetAll:
    """测试get_all方法"""

    def test_get_all_success(self, scene_repository, mock_http_client, test_credential):
        """测试成功获取场景列表"""
        # 准备API响应
        api_response = {
            "code": 0,
            "result": {
                "manual_scene_info_list": [
                    {
                        "scene_id": 123456,
                        "name": "回家模式",
                        "icon": "home_icon",
                    },
                    {
                        "scene_id": 234567,
                        "name": "离家模式",
                        "icon": "away_icon",
                    },
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        scenes = scene_repository.get_all("home1", test_credential)

        # 验证结果
        assert len(scenes) == 2
        assert scenes[0].scene_id == "123456"
        assert scenes[0].name == "回家模式"
        assert scenes[0].home_id == "home1"
        assert scenes[0].icon == "home_icon"
        assert scenes[1].scene_id == "234567"
        assert scenes[1].name == "离家模式"
        assert scenes[1].home_id == "home1"
        assert scenes[1].icon == "away_icon"

        # 验证HTTP调用
        mock_http_client.post.assert_called_once_with(
            "/appgateway/miot/appsceneservice/AppSceneService/GetSimpleSceneList",
            json={
                "app_version": 12,
                "get_type": 2,
                "home_id": "home1",
                "owner_uid": "test_user"
            },
            credential=test_credential
        )

    def test_get_all_empty_list(self, scene_repository, mock_http_client, test_credential):
        """测试获取空场景列表"""
        # 准备API响应（空列表）
        api_response = {"code": 0, "result": {"manual_scene_info_list": []}}
        mock_http_client.post.return_value = api_response

        # 调用方法
        scenes = scene_repository.get_all("home1", test_credential)

        # 验证结果
        assert len(scenes) == 0
        assert isinstance(scenes, list)

        # 验证HTTP调用
        mock_http_client.post.assert_called_once_with(
            "/appgateway/miot/appsceneservice/AppSceneService/GetSimpleSceneList",
            json={
                "app_version": 12,
                "get_type": 2,
                "home_id": "home1",
                "owner_uid": "test_user"
            },
            credential=test_credential
        )

    def test_get_all_missing_fields(self, scene_repository, mock_http_client, test_credential):
        """测试API响应缺少字段的情况"""
        # 准备API响应（缺少部分字段）
        api_response = {
            "code": 0,
            "result": {
                "manual_scene_info_list": [
                    {
                        "scene_id": 123456,
                        "name": "回家模式",
                        # 缺少 icon 字段
                    }
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        scenes = scene_repository.get_all("home1", test_credential)

        # 验证结果
        assert len(scenes) == 1
        assert scenes[0].scene_id == "123456"
        assert scenes[0].name == "回家模式"
        assert scenes[0].home_id == "home1"
        assert scenes[0].icon is None  # 默认值

    def test_get_all_missing_scene_id(self, scene_repository, mock_http_client, test_credential):
        """测试API响应缺少scene_id字段的情况"""
        # 准备API响应（缺少scene_id）
        api_response = {
            "code": 0,
            "result": {
                "manual_scene_info_list": [
                    {
                        # 缺少 scene_id
                        "name": "回家模式",
                        "icon": "home_icon",
                    }
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        scenes = scene_repository.get_all("home1", test_credential)

        # 验证结果
        assert len(scenes) == 1
        assert scenes[0].scene_id == ""  # 默认值
        assert scenes[0].name == "回家模式"

    def test_get_all_missing_name(self, scene_repository, mock_http_client, test_credential):
        """测试API响应缺少name字段的情况"""
        # 准备API响应（缺少name）
        api_response = {
            "code": 0,
            "result": {
                "manual_scene_info_list": [
                    {
                        "scene_id": 123456,
                        # 缺少 name
                        "icon": "home_icon",
                    }
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        scenes = scene_repository.get_all("home1", test_credential)

        # 验证结果
        assert len(scenes) == 1
        assert scenes[0].scene_id == "123456"
        assert scenes[0].name == ""  # 默认值

    def test_get_all_multiple_homes(self, scene_repository, mock_http_client, test_credential):
        """测试不同家庭的场景列表"""
        # 准备API响应
        api_response = {
            "code": 0,
            "result": {
                "manual_scene_info_list": [
                    {
                        "scene_id": 123456,
                        "name": "回家模式",
                        "icon": "home_icon",
                    }
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法 - 家庭1
        scenes1 = scene_repository.get_all("home1", test_credential)
        assert len(scenes1) == 1
        assert scenes1[0].home_id == "home1"

        # 调用方法 - 家庭2
        scenes2 = scene_repository.get_all("home2", test_credential)
        assert len(scenes2) == 1
        assert scenes2[0].home_id == "home2"

        # 验证HTTP调用了两次，使用不同的home_id
        assert mock_http_client.post.call_count == 2
        calls = mock_http_client.post.call_args_list
        assert calls[0][1]["json"]["home_id"] == "home1"
        assert calls[1][1]["json"]["home_id"] == "home2"


class TestExecute:
    """测试execute方法"""

    def test_execute_success(self, scene_repository, mock_http_client, test_credential):
        """测试成功执行场景"""
        # 准备API响应（成功）
        api_response = {"code": 0, "message": "success"}
        mock_http_client.post.return_value = api_response

        # 调用方法
        result = scene_repository.execute("scene123", "home1", test_credential)

        # 验证结果
        assert result is True

        # 验证HTTP调用
        mock_http_client.post.assert_called_once_with(
            "/appgateway/miot/appsceneservice/AppSceneService/NewRunScene",
            json={
                "scene_id": "scene123",
                "scene_type": 2,
                "phone_id": "null",
                "home_id": "home1",
                "owner_uid": "test_user"
            },
            credential=test_credential
        )

    def test_execute_failure(self, scene_repository, mock_http_client, test_credential):
        """测试执行场景失败"""
        # 准备API响应（失败）
        api_response = {"code": -1, "message": "场景不存在"}
        mock_http_client.post.return_value = api_response

        # 调用方法
        result = scene_repository.execute("scene999", "home1", test_credential)

        # 验证结果
        assert result is False

        # 验证HTTP调用
        mock_http_client.post.assert_called_once_with(
            "/appgateway/miot/appsceneservice/AppSceneService/NewRunScene",
            json={
                "scene_id": "scene999",
                "scene_type": 2,
                "phone_id": "null",
                "home_id": "home1",
                "owner_uid": "test_user"
            },
            credential=test_credential
        )

    def test_execute_different_scenes(self, scene_repository, mock_http_client, test_credential):
        """测试执行不同的场景"""
        # 准备API响应
        api_response = {"code": 0, "message": "success"}
        mock_http_client.post.return_value = api_response

        # 执行场景1
        result1 = scene_repository.execute("scene1", "home1", test_credential)
        assert result1 is True

        # 执行场景2
        result2 = scene_repository.execute("scene2", "home1", test_credential)
        assert result2 is True

        # 验证HTTP调用了两次，使用不同的scene_id
        assert mock_http_client.post.call_count == 2
        calls = mock_http_client.post.call_args_list
        assert calls[0][1]["json"]["scene_id"] == "scene1"
        assert calls[1][1]["json"]["scene_id"] == "scene2"

    def test_execute_with_error_code(self, scene_repository, mock_http_client, test_credential):
        """测试执行场景返回错误码"""
        # 准备API响应（各种错误码）
        error_codes = [1, -1, 404, 500]

        for error_code in error_codes:
            api_response = {"code": error_code, "message": f"错误码{error_code}"}
            mock_http_client.post.return_value = api_response

            # 调用方法
            result = scene_repository.execute("scene123", "home1", test_credential)

            # 验证结果（只有code=0才返回True）
            assert result is False


class TestIntegration:
    """集成测试"""

    def test_get_all_and_execute(self, scene_repository, mock_http_client, test_credential):
        """测试获取场景列表后执行场景"""
        # 准备获取场景列表的响应
        list_response = {
            "code": 0,
            "result": {
                "manual_scene_info_list": [
                    {
                        "scene_id": 123456,
                        "name": "回家模式",
                        "icon": "home_icon",
                    }
                ]
            },
        }

        # 准备执行场景的响应
        execute_response = {"code": 0, "message": "success"}

        # 设置mock返回值
        mock_http_client.post.side_effect = [list_response, execute_response]

        # 获取场景列表
        scenes = scene_repository.get_all("home1", test_credential)
        assert len(scenes) == 1

        # 执行第一个场景
        result = scene_repository.execute(scenes[0].scene_id, "home1", test_credential)
        assert result is True

        # 验证HTTP调用了两次
        assert mock_http_client.post.call_count == 2

    def test_multiple_users_isolation(self, scene_repository, mock_http_client):
        """测试多用户场景隔离"""
        # 创建两个不同的凭据
        credential1 = Credential(
            user_id="user1",
            service_token="token1",
            ssecurity="ssecurity1",
            c_user_id="c_user1",
            device_id="device1",
            user_agent="agent1",
            expires_at=datetime.now() + timedelta(days=7),
        )

        credential2 = Credential(
            user_id="user2",
            service_token="token2",
            ssecurity="ssecurity2",
            c_user_id="c_user2",
            device_id="device2",
            user_agent="agent2",
            expires_at=datetime.now() + timedelta(days=7),
        )

        # 准备API响应
        api_response = {"code": 0, "result": {"manual_scene_info_list": []}}
        mock_http_client.post.return_value = api_response

        # 用户1获取场景
        scene_repository.get_all("home1", credential1)

        # 用户2获取场景
        scene_repository.get_all("home2", credential2)

        # 验证HTTP调用使用了不同的凭据
        calls = mock_http_client.post.call_args_list
        assert calls[0][1]["credential"] == credential1
        assert calls[1][1]["credential"] == credential2

        # 验证使用了不同的home_id和owner_uid
        assert calls[0][1]["json"]["home_id"] == "home1"
        assert calls[0][1]["json"]["owner_uid"] == "user1"
        assert calls[1][1]["json"]["home_id"] == "home2"
        assert calls[1][1]["json"]["owner_uid"] == "user2"
