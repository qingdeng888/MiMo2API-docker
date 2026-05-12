"""管理面板密码认证模块"""

import os
import hashlib
import secrets
import time
from typing import Optional

# 从环境变量读取管理密码
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# 已认证的 session token 存储 {token: expire_time}
_sessions: dict = {}

# Session 有效期：24小时
SESSION_TTL = 86400


def is_auth_enabled() -> bool:
    """是否启用了密码认证"""
    return bool(ADMIN_PASSWORD)


def _generate_token() -> str:
    """生成安全的 session token"""
    return secrets.token_hex(32)


def _cleanup_expired():
    """清理过期 session"""
    now = time.time()
    expired = [k for k, v in _sessions.items() if v < now]
    for k in expired:
        del _sessions[k]


def verify_password(password: str) -> Optional[str]:
    """验证密码，成功返回 session token，失败返回 None"""
    if not ADMIN_PASSWORD:
        return None
    if password == ADMIN_PASSWORD:
        _cleanup_expired()
        token = _generate_token()
        _sessions[token] = time.time() + SESSION_TTL
        return token
    return None


def validate_session(token: str) -> bool:
    """验证 session token 是否有效"""
    if not token:
        return False
    _cleanup_expired()
    return token in _sessions


def check_admin_auth(auth_token: Optional[str]) -> bool:
    """检查管理面板认证

    如果未设置 ADMIN_PASSWORD，则不需要认证（向后兼容）。
    如果设置了，则必须提供有效的 session token。
    """
    if not is_auth_enabled():
        return True
    if not auth_token:
        return False
    return validate_session(auth_token)
