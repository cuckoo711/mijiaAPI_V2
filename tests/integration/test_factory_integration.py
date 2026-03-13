"""工厂函数集成测试"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mijiaAPI_V2.api_client import AsyncMijiaAPI, MijiaAPI
from mijiaAPI_V2.core.config import ConfigManager
from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.factory import (
    _find_project_root,
    create_api_client,
    create_api_client_from_file,
    create_async_api_client,
    create_auth_service,
    create_config_manager,
    create_multi_user_clients,
)
from mijiaAPI_V2.services.auth_service import AuthService


@pytest.fixture
def test_credential() -> Credential:
    """创建测试凭据"""
    return Credential(
        user_id="test_user_123",
        service_token="test_service_token",
        ssecurity="test_ssecurity",
        c_user_id="c_test_user",
        device_id="test_device_id",
        user_agent="test_user_agent",
        expires_at=datetime.now() + timedelta(days=30),
    )


@pytest.fixture
def temp_credential_file(test_credential: Credential) -> Path:
    """创建临时凭据文件"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        # 使用 default=str 来处理 datetime 序列化
        json.dump(test_credential.to_dict(), f, ensure_ascii=False, default=str)
        temp_path = Path(f.name)

    yield temp_path

    # 清理
    if temp_path.exists():
        temp_path.unlink()


class TestFindProjectRoot:
    """测试查找项目根目录"""

    def test_find_project_root(self) -> None:
        """测试查找项目根目录"""
        root = _find_project_root()

        # 验证返回 Path 对象
        assert isinstance(root, Path)

        # 验证路径存在
        assert root.exists()


class TestCreateConfigManager:
    """测试创建配置管理器"""

    def test_create_config_manager_default(self) -> None:
        """测试创建默认配置管理器"""
        config = create_config_manager()

        # 验证返回 ConfigManager 实例
        assert isinstance(config, ConfigManager)

    def test_create_config_manager_with_custom_path(self) -> None:
        """测试使用自定义路径创建配置管理器"""
        # 创建临时配置文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write('[test]\nvalue = "custom"\n')
            temp_path = Path(f.name)

        try:
            config = create_config_manager(config_path=temp_path)

            # 验证配置已加载
            assert isinstance(config, ConfigManager)
        finally:
            temp_path.unlink()


class TestCreateApiClient:
    """测试创建API客户端"""

    def test_create_api_client_basic(self, test_credential: Credential) -> None:
        """测试基本创建API客户端"""
        api = create_api_client(test_credential)

        # 验证返回 MijiaAPI 实例
        assert isinstance(api, MijiaAPI)

        # 验证凭据已设置
        assert api.credential.user_id == test_credential.user_id

    def test_create_api_client_with_cache_dir(
        self, test_credential: Credential
    ) -> None:
        """测试指定缓存目录创建API客户端"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            api = create_api_client(test_credential, cache_dir=cache_dir)

            # 验证API客户端创建成功
            assert isinstance(api, MijiaAPI)

    def test_create_api_client_with_custom_config(
        self, test_credential: Credential
    ) -> None:
        """测试使用自定义配置创建API客户端"""
        # 创建临时配置文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write('[api]\nbase_url = "https://api.io.mi.com/app"\n')
            temp_path = Path(f.name)

        try:
            api = create_api_client(test_credential, config_path=temp_path)

            # 验证API客户端创建成功
            assert isinstance(api, MijiaAPI)
        finally:
            temp_path.unlink()


class TestCreateAsyncApiClient:
    """测试创建异步API客户端"""

    def test_create_async_api_client_basic(
        self, test_credential: Credential
    ) -> None:
        """测试基本创建异步API客户端"""
        api = create_async_api_client(test_credential)

        # 验证返回 AsyncMijiaAPI 实例
        assert isinstance(api, AsyncMijiaAPI)

        # 验证凭据已设置
        assert api.credential.user_id == test_credential.user_id

    def test_create_async_api_client_with_cache_dir(
        self, test_credential: Credential
    ) -> None:
        """测试指定缓存目录创建异步API客户端"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            api = create_async_api_client(test_credential, cache_dir=cache_dir)

            # 验证API客户端创建成功
            assert isinstance(api, AsyncMijiaAPI)


class TestCreateAuthService:
    """测试创建认证服务"""

    def test_create_auth_service_basic(self) -> None:
        """测试基本创建认证服务"""
        service = create_auth_service()

        # 验证返回 AuthService 实例
        assert isinstance(service, AuthService)

    def test_create_auth_service_with_custom_config(self) -> None:
        """测试使用自定义配置创建认证服务"""
        # 创建临时配置文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write('[auth]\ntimeout = 60\n')
            temp_path = Path(f.name)

        try:
            service = create_auth_service(config_path=temp_path)

            # 验证认证服务创建成功
            assert isinstance(service, AuthService)
        finally:
            temp_path.unlink()


class TestCreateMultiUserClients:
    """测试创建多用户客户端"""

    def test_create_multi_user_clients_basic(self) -> None:
        """测试基本创建多用户客户端"""
        credentials = {
            "user1": Credential(
                user_id="user1",
                service_token="token1",
                ssecurity="ssecurity1",
                c_user_id="c_user1",
                device_id="device1",
                user_agent="agent1",
                expires_at=datetime.now() + timedelta(days=30),
            ),
            "user2": Credential(
                user_id="user2",
                service_token="token2",
                ssecurity="ssecurity2",
                c_user_id="c_user2",
                device_id="device2",
                user_agent="agent2",
                expires_at=datetime.now() + timedelta(days=30),
            ),
        }

        clients = create_multi_user_clients(credentials)

        # 验证返回字典
        assert isinstance(clients, dict)

        # 验证包含所有用户的客户端
        assert "user1" in clients
        assert "user2" in clients

        # 验证每个客户端都是 MijiaAPI 实例
        assert isinstance(clients["user1"], MijiaAPI)
        assert isinstance(clients["user2"], MijiaAPI)

        # 验证凭据正确
        assert clients["user1"].credential.user_id == "user1"
        assert clients["user2"].credential.user_id == "user2"

    def test_create_multi_user_clients_empty(self) -> None:
        """测试创建空的多用户客户端"""
        clients = create_multi_user_clients({})

        # 验证返回空字典
        assert isinstance(clients, dict)
        assert len(clients) == 0


class TestCreateApiClientFromFile:
    """测试从文件创建API客户端"""

    def test_create_api_client_from_file_basic(
        self, temp_credential_file: Path
    ) -> None:
        """测试从文件创建API客户端"""
        api = create_api_client_from_file(credential_path=temp_credential_file)

        # 验证返回 MijiaAPI 实例
        assert isinstance(api, MijiaAPI)

        # 验证凭据已加载
        assert api.credential.user_id == "test_user_123"

    def test_create_api_client_from_file_not_found(self) -> None:
        """测试从不存在的文件创建API客户端"""
        # 使用临时目录中的不存在文件，避免只读文件系统错误
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent_path = Path(tmpdir) / "nonexistent.json"
            
            with pytest.raises(FileNotFoundError):
                create_api_client_from_file(credential_path=nonexistent_path)

    def test_create_api_client_from_file_expired(self) -> None:
        """测试从过期凭据文件创建API客户端"""
        # 创建过期凭据
        expired_credential = Credential(
            user_id="expired_user",
            service_token="token",
            ssecurity="ssecurity",
            c_user_id="c_user",
            device_id="device",
            user_agent="agent",
            expires_at=datetime.now() - timedelta(days=1),  # 已过期
        )

        # 创建临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(expired_credential.to_dict(), f, ensure_ascii=False, default=str)
            temp_path = Path(f.name)

        try:
            # 应该抛出 ValueError
            with pytest.raises(ValueError, match="凭据已过期"):
                create_api_client_from_file(credential_path=temp_path)
        finally:
            temp_path.unlink()


class TestIntegrationWorkflow:
    """测试完整的集成工作流"""

    def test_complete_workflow(self, test_credential: Credential) -> None:
        """测试完整的工作流：创建客户端 -> 更新凭据"""
        # 1. 创建API客户端
        api = create_api_client(test_credential)
        assert isinstance(api, MijiaAPI)

        # 2. 验证凭据
        assert api.credential.user_id == test_credential.user_id

        # 3. 更新凭据
        new_credential = Credential(
            user_id="new_user",
            service_token="new_token",
            ssecurity="new_ssecurity",
            c_user_id="c_new_user",
            device_id="new_device",
            user_agent="new_agent",
            expires_at=datetime.now() + timedelta(days=30),
        )

        api.update_credential(new_credential)

        # 4. 验证凭据已更新
        assert api.credential.user_id == "new_user"

    def test_multi_user_isolation(self) -> None:
        """测试多用户隔离"""
        credentials = {
            "user_a": Credential(
                user_id="user_a",
                service_token="token_a",
                ssecurity="ssecurity_a",
                c_user_id="c_user_a",
                device_id="device_a",
                user_agent="agent_a",
                expires_at=datetime.now() + timedelta(days=30),
            ),
            "user_b": Credential(
                user_id="user_b",
                service_token="token_b",
                ssecurity="ssecurity_b",
                c_user_id="c_user_b",
                device_id="device_b",
                user_agent="agent_b",
                expires_at=datetime.now() + timedelta(days=30),
            ),
        }

        clients = create_multi_user_clients(credentials)

        # 验证用户隔离
        assert clients["user_a"].credential.user_id == "user_a"
        assert clients["user_b"].credential.user_id == "user_b"

        # 更新一个用户的凭据不应影响另一个
        new_credential_a = Credential(
            user_id="updated_user_a",
            service_token="updated_token_a",
            ssecurity="updated_ssecurity_a",
            c_user_id="c_updated_user_a",
            device_id="updated_device_a",
            user_agent="updated_agent_a",
            expires_at=datetime.now() + timedelta(days=30),
        )

        clients["user_a"].update_credential(new_credential_a)

        # 验证隔离
        assert clients["user_a"].credential.user_id == "updated_user_a"
        assert clients["user_b"].credential.user_id == "user_b"  # 未受影响
