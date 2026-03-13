"""AsyncHttpClient 异步客户端测试"""

import base64
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import httpx
import pytest

from mijiaAPI_V2.core.config import ConfigManager
from mijiaAPI_V2.domain.exceptions import (
    ConnectionError,
    NetworkError,
    TimeoutError,
    TokenExpiredError,
)
from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.crypto_service import CryptoService
from mijiaAPI_V2.infrastructure.http_client import AsyncHttpClient


@pytest.fixture
def config():
    """创建配置管理器"""
    return ConfigManager()


@pytest.fixture
def crypto():
    """创建加密服务"""
    return CryptoService()


@pytest.fixture
def credential():
    """创建测试凭据"""
    return Credential(
        user_id="test_user_123",
        service_token="test_token",
        ssecurity="dGVzdF9zc2VjdXJpdHk=",
        c_user_id="test_c_user_id",
        device_id="test_device_id",
        user_agent="MiHome/1.0.0",
        expires_at=datetime.now() + timedelta(days=7),
    )


@pytest.fixture
async def async_http_client(config, crypto):
    """创建异步HTTP客户端"""
    client = AsyncHttpClient(config, crypto)
    yield client
    await client.close()


def create_mock_response(status_code: int, text: str) -> Mock:
    """创建mock响应对象"""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.headers = {}
    mock_response.content = text.encode()
    mock_response.text = text
    return mock_response


class TestAsyncHttpClientInit:
    """测试 AsyncHttpClient 初始化"""

    @pytest.mark.asyncio
    async def test_init_with_default_config(self, config, crypto):
        """测试使用默认配置初始化"""
        client = AsyncHttpClient(config, crypto)

        assert client._config == config
        assert client._crypto == crypto
        assert isinstance(client._client, httpx.AsyncClient)

        await client.close()

    @pytest.mark.asyncio
    async def test_init_creates_connection_pool(self, config, crypto):
        """测试初始化时创建连接池"""
        client = AsyncHttpClient(config, crypto)

        assert client._client._transport is not None

        await client.close()


class TestAsyncHttpClientPost:
    """测试 AsyncHttpClient.post 方法"""

    @pytest.mark.asyncio
    async def test_post_success(self, async_http_client, credential):
        """测试异步POST请求成功"""
        response_text = base64.b64encode(b'{"code": 0, "result": {"data": "test"}}').decode()
        mock_response = create_mock_response(200, response_text)

        with patch.object(async_http_client._client, "post", return_value=mock_response):
            with patch.object(
                async_http_client._crypto,
                "encrypt_params",
                return_value={
                    "data": "encrypted",
                    "_nonce": "test_nonce",
                    "signature": "sig",
                    "ssecurity": credential.ssecurity,
                },
            ):
                with patch.object(
                    async_http_client._crypto,
                    "decrypt_response",
                    return_value='{"code": 0, "result": {"data": "test"}}',
                ):
                    result = await async_http_client.post("/test/path", {"key": "value"}, credential)

        assert result == {"code": 0, "result": {"data": "test"}}

    @pytest.mark.asyncio
    async def test_post_builds_correct_url(self, async_http_client, credential):
        """测试异步POST请求构建正确的URL"""
        response_text = base64.b64encode(b'{"code": 0}').decode()
        mock_response = create_mock_response(200, response_text)

        with patch.object(async_http_client._client, "post", return_value=mock_response) as mock_post:
            with patch.object(
                async_http_client._crypto,
                "encrypt_params",
                return_value={
                    "data": "encrypted",
                    "_nonce": "test_nonce",
                    "signature": "sig",
                    "ssecurity": credential.ssecurity,
                },
            ):
                with patch.object(
                    async_http_client._crypto,
                    "decrypt_response",
                    return_value='{"code": 0}',
                ):
                    await async_http_client.post("/test/path", {}, credential)

                    call_args = mock_post.call_args
                    assert call_args[0][0] == "https://api.mijia.tech/app/test/path"

    @pytest.mark.asyncio
    async def test_post_includes_correct_headers(self, async_http_client, credential):
        """测试异步POST请求包含正确的请求头"""
        response_text = base64.b64encode(b'{"code": 0}').decode()
        mock_response = create_mock_response(200, response_text)

        with patch.object(async_http_client._client, "post", return_value=mock_response) as mock_post:
            with patch.object(
                async_http_client._crypto,
                "encrypt_params",
                return_value={
                    "data": "encrypted",
                    "_nonce": "test_nonce",
                    "signature": "sig",
                    "ssecurity": credential.ssecurity,
                },
            ):
                with patch.object(
                    async_http_client._crypto,
                    "decrypt_response",
                    return_value='{"code": 0}',
                ):
                    await async_http_client.post("/test/path", {}, credential)

                    call_kwargs = mock_post.call_args[1]
                    headers = call_kwargs["headers"]
                    assert headers["User-Agent"] == credential.user_agent
                    assert headers["x-xiaomi-protocal-flag-cli"] == "PROTOCAL-HTTP2"


class TestAsyncHttpClientErrorHandling:
    """测试 AsyncHttpClient 错误处理"""

    @pytest.mark.asyncio
    async def test_handle_token_expired_error(self, async_http_client, credential):
        """测试处理Token过期错误"""
        response_text = base64.b64encode('{"code": 401, "message": "Token已过期"}'.encode()).decode()
        mock_response = create_mock_response(200, response_text)

        with patch.object(async_http_client._client, "post", return_value=mock_response):
            with patch.object(
                async_http_client._crypto,
                "encrypt_params",
                return_value={
                    "data": "encrypted",
                    "_nonce": "test_nonce",
                    "signature": "sig",
                    "ssecurity": credential.ssecurity,
                },
            ):
                with patch.object(
                    async_http_client._crypto,
                    "decrypt_response",
                    return_value='{"code": 401, "message": "Token已过期"}',
                ):
                    with pytest.raises(TokenExpiredError) as exc_info:
                        await async_http_client.post("/test/path", {}, credential)

                    assert "Token已过期" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_timeout_error(self, async_http_client, credential):
        """测试处理超时错误"""
        with patch.object(
            async_http_client._client, "post", side_effect=httpx.TimeoutException("Request timeout")
        ):
            with pytest.raises(TimeoutError) as exc_info:
                await async_http_client.post("/test/path", {}, credential)

            assert "请求超时" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_connect_error(self, async_http_client, credential):
        """测试处理连接错误"""
        with patch.object(
            async_http_client._client, "post", side_effect=httpx.ConnectError("Connection failed")
        ):
            with pytest.raises(ConnectionError) as exc_info:
                await async_http_client.post("/test/path", {}, credential)

            assert "连接失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_generic_http_error(self, async_http_client, credential):
        """测试处理通用HTTP错误"""
        with patch.object(
            async_http_client._client, "post", side_effect=httpx.HTTPError("Generic error")
        ):
            with pytest.raises(NetworkError) as exc_info:
                await async_http_client.post("/test/path", {}, credential)

            assert "网络错误" in str(exc_info.value)


class TestAsyncHttpClientRetry:
    """测试 AsyncHttpClient 重试机制"""

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self, async_http_client, credential):
        """测试超时时自动重试"""
        response_text = base64.b64encode(b'{"code": 0}').decode()
        mock_response = create_mock_response(200, response_text)

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.TimeoutException("Timeout")
            return mock_response

        with patch.object(async_http_client._client, "post", side_effect=side_effect):
            with patch.object(
                async_http_client._crypto,
                "encrypt_params",
                return_value={
                    "data": "encrypted",
                    "_nonce": "test_nonce",
                    "signature": "sig",
                    "ssecurity": credential.ssecurity,
                },
            ):
                with patch.object(
                    async_http_client._crypto,
                    "decrypt_response",
                    return_value='{"code": 0}',
                ):
                    result = await async_http_client.post("/test/path", {}, credential)

        assert result == {"code": 0}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self, async_http_client, credential):
        """测试重试次数耗尽后抛出异常"""
        with patch.object(
            async_http_client._client, "post", side_effect=httpx.TimeoutException("Timeout")
        ):
            with pytest.raises(TimeoutError):
                await async_http_client.post("/test/path", {}, credential)


class TestAsyncHttpClientClose:
    """测试 AsyncHttpClient 关闭"""

    @pytest.mark.asyncio
    async def test_close(self, config, crypto):
        """测试关闭异步客户端"""
        client = AsyncHttpClient(config, crypto)

        with patch.object(client._client, "aclose") as mock_close:
            await client.close()

        mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, config, crypto):
        """测试异步上下文管理器自动关闭"""
        async with AsyncHttpClient(config, crypto) as client:
            assert isinstance(client, AsyncHttpClient)

        # 验证退出时自动关闭（通过检查客户端是否已关闭）
        assert client._client.is_closed
