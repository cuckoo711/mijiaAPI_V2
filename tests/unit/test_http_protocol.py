"""HTTP协议接口测试"""

from typing import Any, Dict

import pytest

from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.http_protocol import (
    AsyncHttpClientProtocol,
    HttpClientProtocol,
)


class MockHttpClient:
    """模拟HTTP客户端（同步）"""

    def __init__(self) -> None:
        self.closed = False
        self.last_request: Dict[str, Any] = {}

    def post(
        self, path: str, json: Dict[str, Any], credential: Credential, **kwargs: Any
    ) -> Dict[str, Any]:
        """模拟POST请求"""
        self.last_request = {
            "path": path,
            "json": json,
            "credential": credential,
            "kwargs": kwargs,
        }
        return {"code": 0, "message": "success", "result": {"data": "test"}}

    def close(self) -> None:
        """关闭客户端"""
        self.closed = True


class MockAsyncHttpClient:
    """模拟异步HTTP客户端"""

    def __init__(self) -> None:
        self.closed = False
        self.last_request: Dict[str, Any] = {}

    async def post(
        self, path: str, json: Dict[str, Any], credential: Credential, **kwargs: Any
    ) -> Dict[str, Any]:
        """模拟异步POST请求"""
        self.last_request = {
            "path": path,
            "json": json,
            "credential": credential,
            "kwargs": kwargs,
        }
        return {"code": 0, "message": "success", "result": {"data": "test"}}

    async def close(self) -> None:
        """关闭异步客户端"""
        self.closed = True


def test_http_client_protocol_implementation() -> None:
    """测试同步HTTP客户端协议实现"""
    from datetime import datetime, timedelta
    
    # 创建模拟客户端
    client = MockHttpClient()

    # 测试POST请求
    credential = Credential(
        user_id="123456",
        service_token="test_token",
        ssecurity="test_ssecurity",
        c_user_id="c123456",
        device_id="device123",
        user_agent="test_user_agent",
        expires_at=datetime.now() + timedelta(days=30),
    )

    # 验证客户端具有协议要求的方法
    assert hasattr(client, "post")
    assert hasattr(client, "close")
    assert callable(client.post)
    assert callable(client.close)

    response = client.post(
        path="/test/api",
        json={"param": "value"},
        credential=credential,
        timeout=30,
    )

    # 验证响应
    assert response["code"] == 0
    assert response["message"] == "success"

    # 验证请求记录
    assert client.last_request["path"] == "/test/api"
    assert client.last_request["json"]["param"] == "value"
    assert client.last_request["credential"] == credential
    assert client.last_request["kwargs"]["timeout"] == 30

    # 测试关闭
    client.close()
    assert client.closed is True


@pytest.mark.asyncio
async def test_async_http_client_protocol_implementation() -> None:
    """测试异步HTTP客户端协议实现"""
    from datetime import datetime, timedelta
    
    # 创建模拟异步客户端
    client = MockAsyncHttpClient()

    # 测试异步POST请求
    credential = Credential(
        user_id="123456",
        service_token="test_token",
        ssecurity="test_ssecurity",
        c_user_id="c123456",
        device_id="device123",
        user_agent="test_user_agent",
        expires_at=datetime.now() + timedelta(days=30),
    )

    # 验证客户端具有协议要求的方法
    assert hasattr(client, "post")
    assert hasattr(client, "close")
    assert callable(client.post)
    assert callable(client.close)

    response = await client.post(
        path="/test/api",
        json={"param": "value"},
        credential=credential,
        timeout=30,
    )

    # 验证响应
    assert response["code"] == 0
    assert response["message"] == "success"

    # 验证请求记录
    assert client.last_request["path"] == "/test/api"
    assert client.last_request["json"]["param"] == "value"
    assert client.last_request["credential"] == credential
    assert client.last_request["kwargs"]["timeout"] == 30

    # 测试关闭
    await client.close()
    assert client.closed is True
