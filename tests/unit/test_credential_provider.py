"""CredentialProvider单元测试"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from mijiaAPI_V2.core.config import ConfigManager
from mijiaAPI_V2.domain.exceptions import LoginFailedError, TokenExpiredError
from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.credential_provider import CredentialProvider


@pytest.fixture
def config():
    """创建配置管理器"""
    return ConfigManager()


@pytest.fixture
def provider(config):
    """创建凭据提供者"""
    return CredentialProvider(config)


@pytest.fixture
def mock_credential():
    """创建模拟凭据"""
    return Credential(
        user_id="test_user_123",
        service_token="test_service_token",
        ssecurity="test_ssecurity",
        pass_token="test_pass_token",
        c_user_id="test_c_user_id",
        device_id="test_device_id",
        user_agent="iOS-14.4-6.0.103-iPhone12,1",
        expires_at=datetime.now() + timedelta(days=7),
    )


class TestCredentialProvider:
    """CredentialProvider测试类"""

    def test_init(self, config):
        """测试初始化"""
        provider = CredentialProvider(config)
        assert provider._config == config
        assert isinstance(provider._client, httpx.Client)

    def test_generate_device_id(self, provider):
        """测试生成设备ID"""
        device_id = provider._generate_device_id()
        assert isinstance(device_id, str)
        assert len(device_id) == 36  # UUID格式长度
        assert device_id.count("-") == 4  # UUID有4个连字符

        # 测试每次生成的ID不同
        device_id2 = provider._generate_device_id()
        assert device_id != device_id2

    def test_generate_user_agent(self, provider):
        """测试生成User-Agent"""
        user_agent = provider._generate_user_agent()
        assert isinstance(user_agent, str)
        assert user_agent.startswith(("iOS-", "Android-"))

    def test_calculate_expires_at_with_expires_in(self, provider):
        """测试计算过期时间（使用expires_in）"""
        token_data = {"expires_in": 3600}  # 1小时
        expires_at = provider._calculate_expires_at(token_data)

        assert isinstance(expires_at, datetime)
        # 验证过期时间大约在1小时后（允许几秒误差）
        expected = datetime.now() + timedelta(seconds=3600)
        assert abs((expires_at - expected).total_seconds()) < 5

    def test_calculate_expires_at_default(self, provider):
        """测试计算过期时间（使用默认值）"""
        token_data = {}
        expires_at = provider._calculate_expires_at(token_data)

        assert isinstance(expires_at, datetime)
        # 验证过期时间大约在7天后
        expected = datetime.now() + timedelta(days=7)
        assert abs((expires_at - expected).total_seconds()) < 5

    def test_calculate_expires_at_custom_default(self, provider):
        """测试计算过期时间（自定义默认天数）"""
        token_data = {}
        expires_at = provider._calculate_expires_at(token_data, default_days=30)

        assert isinstance(expires_at, datetime)
        # 验证过期时间大约在30天后
        expected = datetime.now() + timedelta(days=30)
        assert abs((expires_at - expected).total_seconds()) < 5

    @patch("httpx.Client.get")
    def test_get_qrcode_url_success(self, mock_get, provider):
        """测试成功获取二维码URL"""
        # 模拟成功响应
        mock_response = Mock()
        mock_response.text = '&&&START&&&{"code":0,"qr":"https://test.qr.url"}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        qr_url = provider._get_qrcode_url()

        assert qr_url == "https://test.qr.url"
        mock_get.assert_called_once()

    @patch("httpx.Client.get")
    def test_get_qrcode_url_failure(self, mock_get, provider):
        """测试获取二维码URL失败"""
        # 模拟失败响应
        mock_response = Mock()
        mock_response.text = '&&&START&&&{"code":1,"desc":"获取失败"}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(LoginFailedError) as exc_info:
            provider._get_qrcode_url()

        assert "获取二维码URL失败" in str(exc_info.value)

    @patch("httpx.Client.get")
    def test_get_qrcode_url_network_error(self, mock_get, provider):
        """测试获取二维码URL网络错误"""
        # 模拟网络错误
        mock_get.side_effect = httpx.RequestError("网络错误")

        with pytest.raises(LoginFailedError) as exc_info:
            provider._get_qrcode_url()

        assert "获取二维码URL失败" in str(exc_info.value)

    @patch("mijiaAPI_V2.infrastructure.credential_provider.QRCode")
    @patch("builtins.print")
    def test_display_qrcode(self, mock_print, mock_qrcode_class, provider):
        """测试显示二维码"""
        # 模拟QRCode对象
        mock_qr = Mock()
        mock_qrcode_class.return_value = mock_qr

        provider._display_qrcode("https://test.qr.url")

        # 验证QRCode被正确调用
        mock_qr.add_data.assert_called_once_with("https://test.qr.url")
        mock_qr.make.assert_called_once()
        mock_qr.print_ascii.assert_called_once()

        # 验证打印了提示信息
        assert mock_print.call_count >= 2

    @patch("httpx.Client.get")
    @patch("time.sleep")
    def test_wait_for_scan_success(self, mock_sleep, mock_get, provider):
        """测试等待扫码成功"""
        # 模拟第一次返回等待状态，第二次返回成功
        mock_response1 = Mock()
        mock_response1.text = '&&&START&&&{"code":87001}'

        mock_response2 = Mock()
        mock_response2.text = '&&&START&&&{"code":0,"userId":"test_user"}'

        mock_get.side_effect = [mock_response1, mock_response2]

        result = provider._wait_for_scan("https://test.qr.url")

        assert result["code"] == 0
        assert result["userId"] == "test_user"
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("httpx.Client.get")
    @patch("time.sleep")
    def test_wait_for_scan_timeout(self, mock_sleep, mock_get, provider):
        """测试等待扫码超时"""
        # 模拟一直返回等待状态
        mock_response = Mock()
        mock_response.text = '&&&START&&&{"code":87001}'
        mock_get.return_value = mock_response

        with pytest.raises(LoginFailedError) as exc_info:
            provider._wait_for_scan("https://test.qr.url", timeout=1)

        assert "扫码超时" in str(exc_info.value)

    @patch("httpx.Client.get")
    def test_wait_for_scan_error(self, mock_get, provider):
        """测试等待扫码错误"""
        # 模拟返回错误状态
        mock_response = Mock()
        mock_response.text = '&&&START&&&{"code":999,"desc":"扫码失败"}'
        mock_get.return_value = mock_response

        with pytest.raises(LoginFailedError) as exc_info:
            provider._wait_for_scan("https://test.qr.url")

        assert "扫码失败" in str(exc_info.value)

    @patch("httpx.Client.get")
    def test_get_service_token_success(self, mock_get, provider):
        """测试成功获取service token"""
        # 模拟第一次请求返回serviceToken
        mock_response1 = Mock()
        mock_response1.cookies = {"serviceToken": "test_token"}
        mock_response1.raise_for_status = Mock()

        # 模拟第二次请求返回ssecurity
        mock_response2 = Mock()
        mock_response2.text = '&&&START&&&{"code":0,"ssecurity":"test_ssecurity"}'
        mock_response2.raise_for_status = Mock()

        mock_get.side_effect = [mock_response1, mock_response2]

        login_result = {"location": "https://test.location"}
        result = provider._get_service_token(login_result)

        assert result["serviceToken"] == "test_token"
        assert result["ssecurity"] == "test_ssecurity"
        assert mock_get.call_count == 2

    @patch("httpx.Client.get")
    def test_get_service_token_missing_location(self, mock_get, provider):
        """测试获取service token缺少location"""
        login_result = {}

        with pytest.raises(LoginFailedError) as exc_info:
            provider._get_service_token(login_result)

        assert "缺少location字段" in str(exc_info.value)

    @patch("httpx.Client.get")
    def test_get_service_token_missing_service_token(self, mock_get, provider):
        """测试获取service token失败（缺少serviceToken）"""
        # 模拟响应中没有serviceToken
        mock_response = Mock()
        mock_response.cookies = {}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        login_result = {"location": "https://test.location"}

        with pytest.raises(LoginFailedError) as exc_info:
            provider._get_service_token(login_result)

        assert "未能获取serviceToken" in str(exc_info.value)

    @patch("httpx.Client.get")
    def test_refresh_service_token_success(self, mock_get, provider):
        """测试成功刷新service token"""
        # 模拟 serviceLogin 返回 location，再由 location 返回 serviceToken cookie
        mock_response = Mock()
        mock_response.text = (
            '&&&START&&&{"code":0,"location":"https://test.location",'
            '"ssecurity":"new_ssecurity"}'
        )
        mock_response.raise_for_status = Mock()

        mock_location_response = Mock()
        mock_location_response.status_code = 200
        mock_location_response.cookies = {"serviceToken": "new_token"}
        mock_get.side_effect = [mock_response, mock_location_response]

        credential = Credential(
            user_id="test_user",
            service_token="old_token",
            ssecurity="old_ssecurity",
            pass_token="test_pass_token",
            c_user_id="test_user",
            device_id="test_device",
            user_agent="iOS-14.4-6.0.103-iPhone12,1",
            expires_at=datetime.now() + timedelta(days=1),
        )
        result = provider._refresh_service_token(credential)

        assert result["serviceToken"] == "new_token"
        assert result["ssecurity"] == "new_ssecurity"

    @patch("httpx.Client.get")
    def test_refresh_service_token_failure(self, mock_get, provider):
        """测试刷新service token失败"""
        # 模拟失败响应
        mock_response = Mock()
        mock_response.text = '&&&START&&&{"code":1,"desc":"刷新失败"}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TokenExpiredError) as exc_info:
            provider._refresh_service_token(mock_credential)

        assert "刷新service token失败" in str(exc_info.value)

    @patch("httpx.Client.get")
    def test_refresh_service_token_missing_ssecurity(self, mock_get, provider):
        """测试刷新service token缺少ssecurity"""
        # 模拟响应缺少ssecurity
        mock_response = Mock()
        mock_response.text = '&&&START&&&{"code":0,"serviceToken":"new_token"}'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(TokenExpiredError) as exc_info:
            provider._refresh_service_token(mock_credential)

        assert "刷新service token失败" in str(exc_info.value)

    @patch("httpx.Client.post")
    def test_revoke_success(self, mock_post, provider, mock_credential):
        """测试成功撤销凭据"""
        # 模拟成功响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = provider.revoke(mock_credential)

        assert result is True
        mock_post.assert_called_once()

    @patch("httpx.Client.post")
    def test_revoke_failure(self, mock_post, provider, mock_credential):
        """测试撤销凭据失败"""
        # 模拟失败响应
        mock_response = Mock()
        mock_response.status_code = 400
        mock_post.return_value = mock_response

        result = provider.revoke(mock_credential)

        assert result is False

    @patch("httpx.Client.post")
    def test_revoke_exception(self, mock_post, provider, mock_credential):
        """测试撤销凭据异常"""
        # 模拟异常
        mock_post.side_effect = Exception("网络错误")

        result = provider.revoke(mock_credential)

        assert result is False

    @patch.object(CredentialProvider, "_get_location")
    @patch.object(CredentialProvider, "_get_qrcode_data")
    @patch.object(CredentialProvider, "_display_qrcode")
    @patch.object(CredentialProvider, "_long_poll_for_scan")
    @patch("httpx.Client.get")
    def test_login_by_qrcode_success(
        self, mock_get, mock_poll, mock_display, mock_get_qr_data, mock_get_location, provider
    ):
        """测试二维码登录成功"""
        # 设置模拟返回值
        mock_get_location.return_value = {
            "qs": "test_qs",
            "sid": "xiaomiio",
            "_sign": "test_sign",
        }

        mock_get_qr_data.return_value = {
            "loginUrl": "https://test.login.url",
            "qr": "https://test.qr.url",
            "lp": "https://test.poll.url",
        }

        mock_poll.return_value = {
            "userId": "test_user_123",
            "ssecurity": "test_ssecurity",
            "location": "https://test.callback.url",
        }

        # 模拟callback请求返回serviceToken
        mock_response = Mock()
        mock_response.cookies = {"serviceToken": "test_token"}
        mock_get.return_value = mock_response

        credential = provider.login_by_qrcode()

        # 验证返回的凭据
        assert isinstance(credential, Credential)
        assert credential.user_id == "test_user_123"
        assert credential.service_token == "test_token"
        assert credential.ssecurity == "test_ssecurity"
        assert len(credential.device_id) == 36  # UUID格式
        assert credential.user_agent.startswith(("iOS-", "Android-"))
        assert credential.expires_at > datetime.now()

        # 验证方法调用
        mock_get_location.assert_called_once()
        mock_get_qr_data.assert_called_once()
        mock_display.assert_called_once()
        mock_poll.assert_called_once()
        mock_get.assert_called_once()

    @patch.object(CredentialProvider, "_get_location")
    def test_login_by_qrcode_failure(self, mock_get_location, provider):
        """测试二维码登录失败"""
        # 模拟获取location失败
        mock_get_location.side_effect = Exception("获取失败")

        with pytest.raises(LoginFailedError) as exc_info:
            provider.login_by_qrcode()

        assert "二维码登录失败" in str(exc_info.value)

    @patch.object(CredentialProvider, "_refresh_service_token")
    def test_refresh_success(self, mock_refresh_token, provider, mock_credential):
        """测试刷新凭据成功"""
        # 设置模拟返回值
        mock_refresh_token.return_value = {
            "serviceToken": "new_token",
            "ssecurity": "new_ssecurity",
        }

        new_credential = provider.refresh(mock_credential)

        # 验证返回的新凭据
        assert isinstance(new_credential, Credential)
        assert new_credential.user_id == mock_credential.user_id
        assert new_credential.service_token == "new_token"
        assert new_credential.ssecurity == "new_ssecurity"
        assert new_credential.device_id == mock_credential.device_id
        assert new_credential.user_agent == mock_credential.user_agent
        assert new_credential.expires_at > datetime.now()

        mock_refresh_token.assert_called_once_with(mock_credential)

    @patch.object(CredentialProvider, "_refresh_service_token")
    def test_refresh_failure(self, mock_refresh_token, provider, mock_credential):
        """测试刷新凭据失败"""
        # 模拟刷新失败
        mock_refresh_token.side_effect = Exception("刷新失败")

        with pytest.raises(TokenExpiredError) as exc_info:
            provider.refresh(mock_credential)

        assert "凭据刷新失败" in str(exc_info.value)
