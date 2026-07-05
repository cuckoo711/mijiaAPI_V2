"""测试项目结构

验证项目的基本结构和导入是否正常。
"""

import pytest


def test_import_main_package() -> None:
    """测试主包导入"""
    import mijiaAPI_V2

    assert mijiaAPI_V2.__version__ == "3.2.2"


def test_import_domain_models() -> None:
    """测试领域模型导入"""
    from mijiaAPI_V2.domain.models import (
        Credential,
        Device,
        DeviceAction,
        DeviceProperty,
        Home,
        Scene,
    )

    assert Credential is not None
    assert Device is not None
    assert DeviceProperty is not None
    assert DeviceAction is not None
    assert Home is not None
    assert Scene is not None


def test_import_domain_exceptions() -> None:
    """测试异常类导入"""
    from mijiaAPI_V2.domain.exceptions import (
        AuthenticationError,
        DeviceError,
        MijiaAPIException,
        NetworkError,
        ValidationError,
    )

    assert MijiaAPIException is not None
    assert AuthenticationError is not None
    assert DeviceError is not None
    assert NetworkError is not None
    assert ValidationError is not None


def test_import_repositories() -> None:
    """测试仓储接口导入"""
    from mijiaAPI_V2.repositories.interfaces import (
        IDeviceRepository,
        IDeviceSpecRepository,
        IHomeRepository,
        ISceneRepository,
    )

    assert IHomeRepository is not None
    assert IDeviceRepository is not None
    assert ISceneRepository is not None
    assert IDeviceSpecRepository is not None


def test_import_infrastructure() -> None:
    """测试基础设施组件导入"""
    from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
    from mijiaAPI_V2.infrastructure.credential_provider import CredentialProvider
    from mijiaAPI_V2.infrastructure.credential_store import (
        FileCredentialStore,
        ICredentialStore,
    )
    from mijiaAPI_V2.infrastructure.crypto_service import CryptoService
    from mijiaAPI_V2.infrastructure.http_client import AsyncHttpClient, HttpClient

    assert HttpClient is not None
    assert AsyncHttpClient is not None
    assert CacheManager is not None
    assert CryptoService is not None
    assert CredentialProvider is not None
    assert ICredentialStore is not None
    assert FileCredentialStore is not None


def test_import_core() -> None:
    """测试核心组件导入"""
    from mijiaAPI_V2.core.config import ConfigManager
    from mijiaAPI_V2.core.logging import StructuredLogger, get_logger

    assert ConfigManager is not None
    assert StructuredLogger is not None
    assert get_logger is not None
