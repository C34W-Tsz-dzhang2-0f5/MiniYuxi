"""认证与授权：零依赖实现（HMAC-SHA256 自签 JWT + PBKDF2 口令 + RBAC）。

刻意不引入 PyJWT/passlib——本机环境越轻越好，且这两个能力实现量很小、可完全掌控。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from . import config


# ---------------- 口令 ----------------
def hash_password(pwd: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return h.hex(), salt


def verify_password(pwd: str, hash_hex: str, salt: str) -> bool:
    h = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return hmac.compare_digest(h.hex(), hash_hex)


# ---------------- 自签 JWT ----------------
def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(payload: dict) -> str:
    body = dict(payload)
    body["iat"] = int(time.time())
    body["exp"] = int(time.time()) + config.TOKEN_TTL
    head = {"alg": "HS256", "typ": "JWT"}
    h = _b64u(json.dumps(head, separators=(",", ":")).encode())
    p = _b64u(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(config.SECRET_KEY.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64u(sig)}"


def parse_token(token: str) -> dict | None:
    try:
        h, p, s = token.split(".")
        expect = _b64u(hmac.new(config.SECRET_KEY.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(s, expect):
            return None
        body = json.loads(_b64u_dec(p))
        if body.get("exp", 0) < time.time():
            return None
        return body
    except Exception:
        return None


# ---------------- RBAC ----------------
class Principal:
    """当前请求身份：租户 + 用户 + 角色 + 权限集。"""

    def __init__(self, tenant_id: str, username: str, role: str):
        self.tenant_id = tenant_id
        self.username = username
        self.role = role
        self.perms = config.ROLE_PERMS.get(role, set())

    def can(self, perm: str) -> bool:
        return perm in self.perms

    def require(self, perm: str) -> None:
        if not self.can(perm):
            raise PermissionError(f"角色 {self.role} 缺少权限：{perm}")


def new_id(prefix: str = "x") -> str:
    return f"{prefix}-{secrets.token_hex(8)}"
