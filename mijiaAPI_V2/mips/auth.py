"""MIoT Pub/Sub 云推送的 OAuth2 登录与令牌存储

登录流程（授权码模式）：
1. ``auth_url()`` 生成授权链接，浏览器完成小米账号登录；
2. 授权后小米固定重定向到 ``http://homeassistant.local:8123``（该回调地址
   注册在小米 OAuth 服务上，无法更改），浏览器会打开一个无法访问的地址；
3. 把浏览器地址栏里带 ``code=`` 的完整地址（或直接贴 code）交给
   ``exchange_code()`` 换取 access_token / refresh_token；
4. 令牌过期前用 ``refresh()`` 续期，全程无需再次登录。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from mijiaAPI_V2.core.logging import get_logger
from mijiaAPI_V2.infrastructure.credential_store import (
    FileCredentialStore,
    _sdk_default_data_dir,
)

logger = get_logger(__name__)

# 小米 OAuth 服务上注册的应用与回调地址（与官方 HA 集成一致）
MIPS_CLIENT_ID = "2882303761520251711"
MIPS_REDIRECT_URI = "http://homeassistant.local:8123"
MIPS_AUTH_URL = "https://account.xiaomi.com/oauth2/authorize"
MIPS_API_HOST = "ha.api.io.mi.com"
MIPS_USER_PROFILE_URL = "https://open.account.xiaomi.com/user/profile"

# 提前续期比例：过期时间走到 70% 就刷新
TOKEN_REFRESH_RATIO = 0.7


class MipsAuthError(Exception):
    """登录 / 令牌错误"""


@dataclass
class MipsTokens:
    """OAuth 令牌"""

    access_token: str
    refresh_token: str
    expires_at: float  # epoch 秒，按 TOKEN_REFRESH_RATIO 折算后的续期触发点
    device_uuid: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "device_uuid": self.device_uuid,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MipsTokens":
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=float(data["expires_at"]),
            device_uuid=str(data["device_uuid"]),
        )

    def needs_refresh(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at


class MipsTokenStore(FileCredentialStore):
    """OAuth 令牌加密存储（AES-256-GCM，与 credential.json 共用密钥文件）"""

    def __init__(self, default_path: Optional[Path] = None):
        if default_path is None:
            default_path = _sdk_default_data_dir() / "mips_tokens.json"
        super().__init__(default_path=default_path)

    def save_tokens(self, tokens: MipsTokens) -> None:
        file_path = self._default_path
        plaintext = json.dumps(tokens.to_dict(), ensure_ascii=False).encode("utf-8")
        envelope = self._encrypt(plaintext, file_path)
        file_path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._chmod_private(file_path)
        logger.info("MIPS 令牌已加密保存")

    def load_tokens(self) -> Optional[MipsTokens]:
        file_path = self._default_path
        if not file_path.exists():
            return None
        try:
            envelope = json.loads(file_path.read_text(encoding="utf-8"))
            plaintext = self._decrypt(envelope, file_path)
            return MipsTokens.from_dict(json.loads(plaintext.decode("utf-8")))
        except Exception as exc:
            logger.error("MIPS 令牌加载失败", extra={"error_type": type(exc).__name__})
            return None

    def delete_tokens(self) -> None:
        self.delete()


class MipsOAuthClient:
    """小米 OAuth2 客户端（授权码换令牌 / 刷新）"""

    def __init__(
        self,
        cloud_server: str = "cn",
        device_uuid: str = "mips-default",
        timeout: float = 30.0,
    ) -> None:
        self._cloud_server = cloud_server
        self._device_uuid = device_uuid
        self._timeout = timeout
        self._client_id = MIPS_CLIENT_ID
        self._redirect_uri = MIPS_REDIRECT_URI

    @property
    def device_id(self) -> str:
        return f"ha.{self._device_uuid}"

    @property
    def api_host(self) -> str:
        if self._cloud_server == "cn":
            return MIPS_API_HOST
        return f"{self._cloud_server}.{MIPS_API_HOST}"

    def auth_url(self, state: Optional[str] = None) -> str:
        params = {
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "response_type": "code",
            "device_id": self.device_id,
            "state": state or self.device_id,
            "skip_confirm": "true",
        }
        return f"{MIPS_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> MipsTokens:
        """用授权码换取令牌"""
        return self._get_token(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "code": code,
                "device_id": self.device_id,
            }
        )

    def refresh(self, refresh_token: str) -> MipsTokens:
        """用 refresh_token 续期"""
        return self._get_token(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "refresh_token": refresh_token,
            }
        )

    def user_info(self, access_token: str) -> Dict[str, Any]:
        """查询登录账号昵称等基本信息"""
        try:
            response = httpx.get(
                MIPS_USER_PROFILE_URL,
                params={"clientId": self._client_id, "token": access_token},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise MipsAuthError(f"查询用户信息失败: {exc}") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if payload.get("code") != 0 or not isinstance(data, dict):
            raise MipsAuthError(f"用户信息响应无效: {payload}")
        return data

    def _get_token(self, data: Dict[str, Any]) -> MipsTokens:
        try:
            response = httpx.get(
                f"https://{self.api_host}/app/v2/ha/oauth/get_token",
                params={"data": json.dumps(data)},
                timeout=self._timeout,
            )
        except Exception as exc:
            raise MipsAuthError(f"令牌请求失败: {exc}") from exc
        if response.status_code == 401:
            raise MipsAuthError("授权码或 refresh_token 无效（401）")
        if response.status_code != 200:
            raise MipsAuthError(f"令牌服务返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise MipsAuthError("令牌响应不是 JSON") from exc
        result = payload.get("result") if isinstance(payload, dict) else None
        if payload.get("code") != 0 or not isinstance(result, dict):
            raise MipsAuthError(f"令牌响应无效: {payload}")
        if not all(k in result for k in ("access_token", "refresh_token", "expires_in")):
            raise MipsAuthError(f"令牌响应缺少字段: {result}")
        expires_in = float(result.get("expires_in") or 0)
        return MipsTokens(
            access_token=str(result["access_token"]),
            refresh_token=str(result["refresh_token"]),
            expires_at=time.time() + expires_in * TOKEN_REFRESH_RATIO,
            device_uuid=self._device_uuid,
        )


def extract_code_from_redirect(redirect_input: str) -> str:
    """从用户粘贴的重定向地址（或纯 code）中提取授权码"""
    text = (redirect_input or "").strip()
    if not text:
        raise MipsAuthError("授权码不能为空")
    if "://" not in text and "?" not in text and "=" not in text:
        return text
    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    code = query.get("code", [None])[0]
    if code:
        return code
    raise MipsAuthError("地址里没有找到 code 参数，请粘贴完整的重定向地址")
