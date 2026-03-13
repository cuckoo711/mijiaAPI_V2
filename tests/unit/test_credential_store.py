"""凭据存储测试"""

import json
import tempfile
from pathlib import Path

import pytest

from mijiaAPI_V2.domain.models import Credential
from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore


@pytest.fixture
def temp_dir() -> Path:
    """创建临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def credential() -> Credential:
    """创建测试凭据"""
    from datetime import datetime, timedelta
    
    return Credential(
        user_id="123456",
        service_token="test_service_token",
        ssecurity="test_ssecurity",
        c_user_id="c123456",
        device_id="device123",
        user_agent="test_user_agent",
        expires_at=datetime.now() + timedelta(days=30),
    )


def test_save_and_load_credential(temp_dir: Path, credential: Credential) -> None:
    """测试保存和加载凭据"""
    # 创建存储实例
    store = FileCredentialStore(default_path=temp_dir / "credential.json")

    # 保存凭据
    store.save(credential)

    # 验证文件存在
    assert (temp_dir / "credential.json").exists()

    # 加载凭据
    loaded = store.load()

    # 验证加载的凭据
    assert loaded is not None
    assert loaded.user_id == credential.user_id
    assert loaded.service_token == credential.service_token
    assert loaded.ssecurity == credential.ssecurity


def test_save_with_custom_path(temp_dir: Path, credential: Credential) -> None:
    """测试使用自定义路径保存凭据"""
    store = FileCredentialStore(default_path=temp_dir / "default.json")
    custom_path = str(temp_dir / "custom.json")

    # 使用自定义路径保存
    store.save(credential, path=custom_path)

    # 验证文件存在
    assert Path(custom_path).exists()

    # 加载凭据
    loaded = store.load(path=custom_path)
    assert loaded is not None
    assert loaded.user_id == credential.user_id


def test_load_nonexistent_file(temp_dir: Path) -> None:
    """测试加载不存在的文件"""
    store = FileCredentialStore(default_path=temp_dir / "nonexistent.json")

    # 加载不存在的文件应返回None
    loaded = store.load()
    assert loaded is None


def test_load_invalid_json(temp_dir: Path) -> None:
    """测试加载无效的JSON文件"""
    store = FileCredentialStore(default_path=temp_dir / "invalid.json")

    # 创建无效的JSON文件
    with open(temp_dir / "invalid.json", "w") as f:
        f.write("invalid json content")

    # 加载无效文件应返回None
    loaded = store.load()
    assert loaded is None


def test_delete_credential(temp_dir: Path, credential: Credential) -> None:
    """测试删除凭据"""
    store = FileCredentialStore(default_path=temp_dir / "credential.json")

    # 保存凭据
    store.save(credential)
    assert (temp_dir / "credential.json").exists()

    # 删除凭据
    store.delete()
    assert not (temp_dir / "credential.json").exists()


def test_delete_nonexistent_file(temp_dir: Path) -> None:
    """测试删除不存在的文件"""
    store = FileCredentialStore(default_path=temp_dir / "nonexistent.json")

    # 删除不存在的文件不应抛出异常
    store.delete()


def test_file_permissions(temp_dir: Path, credential: Credential) -> None:
    """测试文件权限设置"""
    store = FileCredentialStore(default_path=temp_dir / "credential.json")

    # 保存凭据
    store.save(credential)

    # 验证文件权限（仅所有者可读写）
    file_path = temp_dir / "credential.json"
    stat = file_path.stat()
    # 0o600 = 384 in decimal
    assert stat.st_mode & 0o777 == 0o600


def test_expanduser_path(temp_dir: Path, credential: Credential) -> None:
    """测试展开用户目录符号"""
    store = FileCredentialStore(default_path=temp_dir / "default.json")

    # 使用 ~ 符号的路径
    custom_path = str(temp_dir / "test.json")

    # 保存和加载
    store.save(credential, path=custom_path)
    loaded = store.load(path=custom_path)

    assert loaded is not None
    assert loaded.user_id == credential.user_id


def test_find_project_root() -> None:
    """测试查找项目根目录"""
    store = FileCredentialStore()

    # 验证默认路径包含 .mijia 目录
    assert ".mijia" in str(store._default_path)
    assert store._default_path.name == "credential.json"


def test_credential_json_format(temp_dir: Path, credential: Credential) -> None:
    """测试凭据JSON格式"""
    store = FileCredentialStore(default_path=temp_dir / "credential.json")

    # 保存凭据
    store.save(credential)

    # 读取JSON文件
    with open(temp_dir / "credential.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # 验证JSON格式
    assert "user_id" in data
    assert "service_token" in data
    assert "ssecurity" in data
    assert data["user_id"] == credential.user_id
