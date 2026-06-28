"""
NoteAI Pro 管理员认证模块
- 完全独立于用户认证体系
- 管理员账号存 .env，不入数据库
- admin token 存内存（重启失效，需重新登录）
"""
import os
import secrets
import time
from typing import Optional
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ── 管理员 token 内存存储（{token: {username, created_at}}）──
_admin_sessions: dict[str, dict] = {}
_ADMIN_TOKEN_EXPIRE = 86400 * 7  # 7天

_admin_bearer = HTTPBearer(auto_error=False)


def get_admin_credentials() -> tuple[str, str]:
    username = os.environ.get("ADMIN_USERNAME", "noteai_admin")
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        raise RuntimeError("ADMIN_PASSWORD 未配置，请在 .env 中设置")
    return username, password


def admin_login(username: str, password: str) -> str:
    """验证管理员凭据，返回 admin token。"""
    admin_user, admin_pass = get_admin_credentials()
    if not (secrets.compare_digest(username, admin_user) and
            secrets.compare_digest(password, admin_pass)):
        raise HTTPException(status_code=401, detail="管理员账号或密码错误")
    token = "admin_" + secrets.token_urlsafe(32)
    _admin_sessions[token] = {"username": username, "created_at": time.time()}
    return token


def admin_logout(token: str) -> None:
    _admin_sessions.pop(token, None)


def _verify_admin_token(token: str) -> Optional[dict]:
    if not token or not token.startswith("admin_"):
        return None
    session = _admin_sessions.get(token)
    if not session:
        return None
    if time.time() - session["created_at"] > _ADMIN_TOKEN_EXPIRE:
        _admin_sessions.pop(token, None)
        return None
    return session


def get_admin_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_admin_bearer),
) -> dict:
    """FastAPI 依赖：要求 admin token，否则 403。"""
    if not creds:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    session = _verify_admin_token(creds.credentials)
    if not session:
        raise HTTPException(status_code=403, detail="管理员 token 无效或已过期，请重新登录")
    return {**session, "token": creds.credentials}
