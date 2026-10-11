"""家庭仓储单元测试"""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.infrastructure.http_client import HttpClient
from mijiaAPI_V2.repositories.home_repository import HomeRepositoryImpl


@pytest.fixture
def mock_http_client():
    """创建Mock HTTP客户端"""
    return Mock(spec=HttpClient)


@pytest.fixture
def mock_cache_manager():
    """创建Mock缓存管理器"""
    return Mock(spec=CacheManager)


@pytest.fixture
def home_repository(mock_http_client, mock_cache_manager):
    """创建家庭仓储实例"""
    return HomeRepositoryImpl(mock_http_client, mock_cache_manager)


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

    def test_get_all_from_cache(self, home_repository, mock_cache_manager, test_credential):
        """测试从缓存获取家庭列表"""
        # 准备缓存数据
        cached_homes = [
            {
                "id": "home1",
                "name": "我的家",
                "uid": "user1",
                "rooms": [{"id": "room1", "name": "客厅"}],
            },
            {
                "id": "home2",
                "name": "办公室",
                "uid": "user1",
                "rooms": [],
            },
        ]
        mock_cache_manager.get.return_value = cached_homes

        # 调用方法
        homes = home_repository.get_all(test_credential)

        # 验证结果
        assert len(homes) == 2
        assert homes[0].id == "home1"
        assert homes[0].name == "我的家"
        assert homes[0].uid == "user1"
        assert len(homes[0].rooms) == 1
        assert homes[1].id == "home2"
        assert homes[1].name == "办公室"

        # 验证缓存被调用
        mock_cache_manager.get.assert_called_once_with("homes", namespace=test_credential.user_id)

    def test_get_all_from_api(
        self, home_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试从API获取家庭列表"""
        # 缓存未命中
        mock_cache_manager.get.return_value = None

        # 准备API响应（使用实际的 API 路径和参数）
        api_response = {
            "code": 0,
            "result": {
                "homelist": [
                    {
                        "id": 123456,
                        "name": "我的家",
                        "uid": 789012,
                        "roomlist": [{"id": "room1", "name": "客厅"}],
                    },
                    {
                        "id": 234567,
                        "name": "办公室",
                        "uid": 789012,
                        "roomlist": [],
                    },
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        homes = home_repository.get_all(test_credential)

        # 验证结果
        assert len(homes) == 2
        assert homes[0].id == "123456"
        assert homes[0].name == "我的家"
        assert len(homes[0].rooms) == 1

        # 验证HTTP调用（使用实际的 API 路径和参数）
        mock_http_client.post.assert_called_once_with(
            "/v2/homeroom/gethome_merged",
            json={
                "fg": True,
                "fetch_share": True,
                "fetch_share_dev": True,
                "fetch_cariot": True,
                "limit": 300,
                "app_ver": 7,
                "plat_form": 0,
            },
            credential=test_credential,
        )

        # 验证缓存被设置
        mock_cache_manager.set.assert_called_once()

    def test_get_all_empty_list(
        self, home_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试获取空家庭列表"""
        # 缓存未命中
        mock_cache_manager.get.return_value = None

        # 准备API响应（空列表）
        api_response = {"code": 0, "result": {"homelist": []}}
        mock_http_client.post.return_value = api_response

        # 调用方法
        homes = home_repository.get_all(test_credential)

        # 验证结果
        assert len(homes) == 0
        assert isinstance(homes, list)

    def test_get_all_missing_fields(
        self, home_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试API响应缺少字段的情况"""
        # 缓存未命中
        mock_cache_manager.get.return_value = None

        # 准备API响应（缺少部分字段）
        api_response = {
            "code": 0,
            "result": {
                "homelist": [
                    {
                        "id": 123456,
                        "name": "我的家",
                        "uid": 789012,
                        # 可选 roomlist 未返回
                    }
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        homes = home_repository.get_all(test_credential)

        # 验证结果
        assert len(homes) == 1
        assert homes[0].id == "123456"
        assert homes[0].name == "我的家"
        assert homes[0].uid == "789012"
        assert homes[0].rooms == []  # 默认值


class TestGetById:
    """测试get_by_id方法"""

    def test_get_by_id_from_cache(self, home_repository, mock_cache_manager, test_credential):
        """测试从缓存获取单个家庭"""
        # 准备缓存数据
        cached_home = {
            "id": "home1",
            "name": "我的家",
            "uid": "user1",
            "rooms": [{"id": "room1", "name": "客厅"}],
        }
        mock_cache_manager.get.return_value = cached_home

        # 调用方法
        home = home_repository.get_by_id("home1", test_credential)

        # 验证结果
        assert home is not None
        assert home.id == "home1"
        assert home.name == "我的家"
        assert len(home.rooms) == 1

        # 验证缓存被调用
        mock_cache_manager.get.assert_called_once_with(
            "home:home1", namespace=test_credential.user_id
        )

    def test_get_by_id_from_get_all(
        self, home_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试通过get_all获取单个家庭"""
        # 第一次缓存未命中（单个家庭缓存）
        # 第二次缓存未命中（所有家庭缓存）
        mock_cache_manager.get.side_effect = [None, None]

        # 准备API响应
        api_response = {
            "code": 0,
            "result": {
                "homelist": [
                    {
                        "id": 123456,
                        "name": "我的家",
                        "uid": 789012,
                        "roomlist": [{"id": "room1", "name": "客厅"}],
                    },
                    {
                        "id": 234567,
                        "name": "办公室",
                        "uid": 789012,
                        "roomlist": [],
                    },
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        home = home_repository.get_by_id("123456", test_credential)

        # 验证结果
        assert home is not None
        assert home.id == "123456"
        assert home.name == "我的家"

        # 验证HTTP调用
        mock_http_client.post.assert_called_once()

        # 验证缓存被设置（get_all设置一次，get_by_id设置一次）
        assert mock_cache_manager.set.call_count == 2

    def test_get_by_id_not_found(
        self, home_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试获取不存在的家庭"""
        # 缓存未命中
        mock_cache_manager.get.side_effect = [None, None]

        # 准备API响应（不包含目标家庭）
        api_response = {
            "code": 0,
            "result": {
                "homelist": [
                    {
                        "id": 123456,
                        "name": "我的家",
                        "uid": 789012,
                        "roomlist": [],
                    }
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        home = home_repository.get_by_id("999999", test_credential)

        # 验证结果
        assert home is None

    def test_get_by_id_caches_result(
        self, home_repository, mock_http_client, mock_cache_manager, test_credential
    ):
        """测试get_by_id会缓存找到的家庭"""
        # 缓存未命中
        mock_cache_manager.get.side_effect = [None, None]

        # 准备API响应
        api_response = {
            "code": 0,
            "result": {
                "homelist": [
                    {
                        "id": 123456,
                        "name": "我的家",
                        "uid": 789012,
                        "roomlist": [],
                    }
                ]
            },
        }
        mock_http_client.post.return_value = api_response

        # 调用方法
        home = home_repository.get_by_id("123456", test_credential)

        # 验证结果
        assert home is not None

        # 验证缓存被设置两次：一次是get_all，一次是get_by_id
        assert mock_cache_manager.set.call_count == 2

        # 验证第二次set调用（get_by_id的缓存）
        second_call = mock_cache_manager.set.call_args_list[1]
        assert second_call[0][0] == "home:123456"  # key
        assert second_call[1]["ttl"] == 300  # TTL
        assert second_call[1]["namespace"] == test_credential.user_id


class TestIntegration:
    """集成测试"""

    def test_multiple_users_isolation(self, home_repository, mock_http_client, mock_cache_manager):
        """测试多用户缓存隔离"""
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

        # 缓存未命中
        mock_cache_manager.get.return_value = None

        # 准备API响应
        api_response = {"code": 0, "result": {"homelist": []}}
        mock_http_client.post.return_value = api_response

        # 用户1调用
        home_repository.get_all(credential1)

        # 用户2调用
        home_repository.get_all(credential2)

        # 验证缓存使用了不同的命名空间
        cache_calls = mock_cache_manager.get.call_args_list
        assert cache_calls[0][1]["namespace"] == "user1"
        assert cache_calls[1][1]["namespace"] == "user2"

        # 验证缓存设置使用了不同的命名空间
        set_calls = mock_cache_manager.set.call_args_list
        assert set_calls[0][1]["namespace"] == "user1"
        assert set_calls[1][1]["namespace"] == "user2"
