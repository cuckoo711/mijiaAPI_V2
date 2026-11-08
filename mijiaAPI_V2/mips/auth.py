"""MIoT Pub/Sub 云推送的 OAuth2 登录与令牌存储

登录流程（授权码模式）：
1. ``auth_url()`` 生成授权链接，浏览器完成小米账号登录；
2. 授权后小米固定重定向到注册的回调地址（``http://homeassistant.local:8123``
   前缀，带 ``/api/webhook/<id>`` 路径），浏览器会打开一个无法访问的地址；
3. 把浏览器地址栏里带 ``code=`` 的完整地址（或直接贴 code）交给
   ``exchange_code()`` 换取 access_token / refresh_token；
4. 令牌过期前用 ``refresh()`` 续期，全程无需再次登录。

请求形态与小米官方集成保持一致（回调地址、state 摘要、UA 等），
否则令牌交换会报 invalid request。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlencode
from uuid import uuid4

import httpx

from mijiaAPI_V2.core.logging import get_logger
from mijiaAPI_V2.infrastructure.credential_store import (
    FileCredentialStore,
    _sdk_default_data_dir,
)

logger = get_logger(__name__)

# 小米 OAuth 服务上注册的应用与回调地址前缀（与官方 HA 集成一致）
MIPS_CLIENT_ID = "2882303761520251711"
MIPS_REDIRECT_URI = "http://homeassistant.local:8123"
MIPS_AUTH_URL = "https://account.xiaomi.com/oauth2/authorize"
MIPS_API_HOST = "ha.api.io.mi.com"
MIPS_USER_PROFILE_URL = "https://open.account.xiaomi.com/user/profile"
# 官方集成的客户端标识（其云接口按此形态校验请求）
MIPS_USER_AGENT = "ha_xiaomi_home/v0.5.0 client/{device_id}"

# 提前续期比例：过期时间走到 70% 就刷新
TOKEN_REFRESH_RATIO = 0.7


class MipsAuthError(Exception):
    """登录 / 令牌错误"""


def is_instance_id(value: str) -> bool:
    """云 MQTT 的 client_id 要求 ha.<32位hex>，不满足会被拒（Not authorized）"""
    return bool(re.fullmatch(r"[0-9a-f]{32}", value or ""))


def new_instance_id() -> str:
    return uuid4().hex


@dataclass
class MipsTokens:
    """OAuth 令牌"""

    access_token: str
    refresh_token: str
    expires_at: float  # epoch 秒，按 TOKEN_REFRESH_RATIO 折算后的续期触发点
    device_uuid: str
    redirect_uri: str = field(default=MIPS_REDIRECT_URI)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "device_uuid": self.device_uuid,
            "redirect_uri": self.redirect_uri,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MipsTokens":
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=float(data["expires_at"]),
            device_uuid=str(data["device_uuid"]),
            redirect_uri=str(data.get("redirect_uri") or MIPS_REDIRECT_URI),
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
        device_uuid: Optional[str] = None,
        timeout: float = 30.0,
        redirect_uri: Optional[str] = None,
    ) -> None:
        self._cloud_server = cloud_server
        self._device_uuid = device_uuid if is_instance_id(device_uuid or "") else new_instance_id()
        self._timeout = timeout
        self._client_id = MIPS_CLIENT_ID
        # 令牌交换必须使用与授权请求完全一致的 redirect_uri；
        # 官方集成使用注册前缀 + webhook 路径，这里保持同一形态。
        self._redirect_uri = redirect_uri or (
            f"{MIPS_REDIRECT_URI}/api/webhook/{secrets.randbits(64)}"
        )

    @property
    def device_id(self) -> str:
        return f"ha.{self._device_uuid}"

    @property
    def redirect_uri(self) -> str:
        return self._redirect_uri

    @property
    def api_host(self) -> str:
        if self._cloud_server == "cn":
            return MIPS_API_HOST
        return f"{self._cloud_server}.{MIPS_API_HOST}"

    @property
    def state(self) -> str:
        # 与官方集成一致：state = sha1("d=" + device_id)
        return hashlib.sha1(f"d={self.device_id}".encode("utf-8")).hexdigest()

    def auth_url(self) -> str:
        params: Dict[str, Any] = {
            "redirect_uri": self._redirect_uri,
            "client_id": int(self._client_id),
            "response_type": "code",
            "device_id": self.device_id,
            "state": self.state,
        }
        params["skip_confirm"] = False
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
        # 与官方集成客户端一致的请求形态：client_id 数值、完整 redirect_uri、
        # 带 UA 与表单 Content-Type
        payload = dict(data)
        payload["client_id"] = int(self._client_id)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": MIPS_USER_AGENT.format(device_id=self.device_id),
        }
        try:
            response = httpx.get(
                f"https://{self.api_host}/app/v2/ha/oauth/get_token",
                params={"data": json.dumps(payload)},
                headers=headers,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise MipsAuthError(f"令牌请求失败: {exc}") from exc
        if response.status_code == 401:
            raise MipsAuthError(
                "授权码或 refresh_token 无效（401），请重新登录获取新的授权码"
            )
        if response.status_code != 200:
            raise MipsAuthError(f"令牌服务返回 HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise MipsAuthError("令牌响应不是 JSON") from exc
        result = body.get("result") if isinstance(body, dict) else None
        if body.get("code") != 0 or not isinstance(result, dict):
            raise MipsAuthError(
                f"令牌响应无效: {body}；请重新点登录获取新的授权码"
                "（每个授权码只能用一次，过期或用过即失效）"
            )
        if not all(k in result for k in ("access_token", "refresh_token", "expires_in")):
            raise MipsAuthError(f"令牌响应缺少字段: {result}")
        expires_in = float(result.get("expires_in") or 0)
        return MipsTokens(
            access_token=str(result["access_token"]),
            refresh_token=str(result["refresh_token"]),
            expires_at=time.time() + expires_in * TOKEN_REFRESH_RATIO,
            device_uuid=self._device_uuid,
            redirect_uri=self._redirect_uri,
        )


def extract_code_from_redirect(redirect_input: str) -> str:
    """从用户粘贴的重定向地址（或纯 code）中提取授权码

    注意只做 %XX 解码，绝不把 ``+`` 当空格——OAuth 授权码常含 base64 字符
    ``+ / =``，浏览器地址栏显示的又是解码后的网址，一旦 ``+`` 被转成空格
    服务端就会报 invalid request。
    """
    text = (redirect_input or "").strip()
    if not text:
        raise MipsAuthError("授权码不能为空")
    match = re.search(r"code=([^&#\s]*)", text)
    if match:
        code = unquote(match.group(1))
        if code:
            return code
        raise MipsAuthError("code 参数为空，请粘贴完整的重定向地址")
    if "://" in text:
        raise MipsAuthError("地址里没有找到 code 参数，请粘贴完整的重定向地址")
    # 用户直接粘贴授权码（可能含 base64 的 + / = 填充符）
    return text
