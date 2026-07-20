"""凭据存储

提供凭据的存储和加载功能。默认以 AES-256-GCM 加密落盘；
仍可读旧版明文 JSON，并在下次保存时自动迁移为密文。
"""

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

from mijiaAPI_V2.core.logging import get_logger
from mijiaAPI_V2.domain.models import Credential

ENCRYPTED_FORMAT_VERSION = 1
PBKDF2_ITERATIONS = 200_000
KEY_ENV = "MIJIA_CREDENTIAL_SECRET"


def _sdk_default_data_dir() -> Path:
    """Return the default on-disk data directory (``configs/``).

    - PyInstaller single-file exe: next to the binary.
    - Source / installed package: project root (directory with ``pyproject.toml``),
      else ``cwd()``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "configs"

    current = Path(__file__).resolve()
    for _ in range(10):
        current = current.parent
        if (current / "pyproject.toml").exists():
            return current / "configs"
        if current.parent == current:
            break

    return Path.cwd() / "configs"


def _sdk_default_credential_path() -> Path:
    """Return the default credential path: ``configs/credential.json``."""

    return _sdk_default_data_dir() / "credential.json"


logger = get_logger(__name__)


class ICredentialStore(ABC):
    """凭据存储接口"""

    @abstractmethod
    def save(self, credential: Credential, path: Optional[str] = None) -> None:
        """保存凭据"""

    @abstractmethod
    def load(self, path: Optional[str] = None) -> Optional[Credential]:
        """加载凭据"""

    @abstractmethod
    def delete(self, path: Optional[str] = None) -> None:
        """删除凭据"""


class FileCredentialStore(ICredentialStore):
    """文件凭据存储（AES-256-GCM）。

    密钥来源优先级：
    1. 环境变量 ``MIJIA_CREDENTIAL_SECRET``
    2. 与凭据同目录的 ``.credential_key``（不存在则自动生成）
    """

    def __init__(self, default_path: Optional[Path] = None):
        self._default_path = default_path if default_path else _sdk_default_credential_path()
        self._default_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, credential: Credential, path: Optional[str] = None) -> None:
        file_path = self._get_path(path)
        try:
            plaintext = json.dumps(
                credential.to_dict(),
                ensure_ascii=False,
                indent=2,
                default=str,
            ).encode("utf-8")
            envelope = self._encrypt(plaintext, file_path)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(envelope, f, ensure_ascii=False, indent=2)
            self._chmod_private(file_path)
            logger.info(f"凭据已加密保存到: {file_path}")
        except Exception as e:
            logger.error(f"保存凭据失败: {e}")
            raise

    def load(self, path: Optional[str] = None) -> Optional[Credential]:
        file_path = self._get_path(path)
        if not file_path.exists():
            logger.warning(f"凭据文件不存在: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if self._is_encrypted_envelope(data):
                plaintext = self._decrypt(data, file_path)
                payload = json.loads(plaintext.decode("utf-8"))
            else:
                # 兼容旧版明文；下次 save 时迁移为密文
                logger.warning(f"检测到明文凭据，建议重新登录或保存以迁移加密: {file_path}")
                payload = data

            credential = Credential.from_dict(payload)
            logger.info(f"凭据已加载，用户ID: {credential.user_id}")
            return credential
        except Exception as e:
            logger.error(f"加载凭据失败: {e}")
            return None

    def delete(self, path: Optional[str] = None) -> None:
        file_path = self._get_path(path)
        if file_path.exists():
            file_path.unlink()
            logger.info(f"凭据已删除: {file_path}")

    def _get_path(self, path: Optional[str]) -> Path:
        if path:
            file_path = Path(path)
            if str(file_path).startswith("~"):
                file_path = file_path.expanduser()
            return file_path
        return self._default_path

    def _key_path_for(self, credential_path: Path) -> Path:
        return credential_path.parent / ".credential_key"

    def _resolve_secret(self, credential_path: Path) -> bytes:
        env_secret = os.environ.get(KEY_ENV, "").strip()
        if env_secret:
            return env_secret.encode("utf-8")

        key_path = self._key_path_for(credential_path)
        if key_path.exists():
            # 密钥为原始随机字节，不可 strip：首尾若恰为空白字节会被剥掉，
            # 导致偶发 AES-GCM MAC check failed（CI/本地间歇红）。
            secret = key_path.read_bytes()
            if not secret:
                raise ValueError(f"凭据密钥文件为空: {key_path}")
            return secret

        secret = get_random_bytes(32)
        key_path.write_bytes(secret)
        self._chmod_private(key_path)
        logger.info(f"已生成凭据加密密钥文件: {key_path}")
        return secret

    def _derive_key(self, secret: bytes, salt: bytes) -> bytes:
        return PBKDF2(secret, salt, dkLen=32, count=PBKDF2_ITERATIONS, hmac_hash_module=SHA256)

    def _encrypt(self, plaintext: bytes, credential_path: Path) -> dict[str, Any]:
        secret = self._resolve_secret(credential_path)
        salt = get_random_bytes(16)
        nonce = get_random_bytes(12)
        key = self._derive_key(secret, salt)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        return {
            "version": ENCRYPTED_FORMAT_VERSION,
            "alg": "aes-256-gcm",
            "kdf": "pbkdf2-sha256",
            "iterations": PBKDF2_ITERATIONS,
            "salt": salt.hex(),
            "nonce": nonce.hex(),
            "ciphertext": ciphertext.hex(),
            "tag": tag.hex(),
        }

    def _decrypt(self, envelope: dict[str, Any], credential_path: Path) -> bytes:
        secret = self._resolve_secret(credential_path)
        salt = bytes.fromhex(str(envelope["salt"]))
        nonce = bytes.fromhex(str(envelope["nonce"]))
        ciphertext = bytes.fromhex(str(envelope["ciphertext"]))
        tag = bytes.fromhex(str(envelope["tag"]))
        iterations = int(envelope.get("iterations") or PBKDF2_ITERATIONS)
        key = PBKDF2(secret, salt, dkLen=32, count=iterations, hmac_hash_module=SHA256)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)

    @staticmethod
    def _is_encrypted_envelope(data: Any) -> bool:
        return isinstance(data, dict) and data.get("alg") == "aes-256-gcm" and "ciphertext" in data

    @staticmethod
    def _chmod_private(file_path: Path) -> None:
        if sys.platform != "win32":
            file_path.chmod(0o600)
