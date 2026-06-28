"""
NoteAI 认证模块 — 纯 stdlib，无需额外依赖。
密码：PBKDF2-SHA256（100000 轮）
令牌：secrets.token_urlsafe(32) 存 SQLite user_sessions
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# 导出供 api.py 使用
__all__ = [
    "get_current_user", "get_optional_user", "create_user", "login_user",
    "delete_token", "HTTPAuthorizationCredentials", "_bearer",
]

import db

_TOKEN_EXPIRE_DAYS = 30
_bearer = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────────────────────
# 密码工具
# ─────────────────────────────────────────────────────────────

def _gen_salt() -> str:
    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return key.hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_password(password, salt), stored_hash)


# ─────────────────────────────────────────────────────────────
# 令牌工具
# ─────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expire_iso(days: int = _TOKEN_EXPIRE_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def create_token(user_id: str, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO user_sessions(token,user_id,created_at,expires_at,user_agent) VALUES(?,?,?,?,?)",
        (token, user_id, _now_iso(), _expire_iso(), user_agent),
    )
    return token


def _get_user_id_from_token(token: str) -> Optional[str]:
    row = db.fetchone(
        "SELECT user_id, expires_at FROM user_sessions WHERE token=?",
        (token,),
    )
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        db.execute("DELETE FROM user_sessions WHERE token=?", (token,))
        return None
    return row["user_id"]


def delete_token(token: str) -> None:
    db.execute("DELETE FROM user_sessions WHERE token=?", (token,))


# ─────────────────────────────────────────────────────────────
# FastAPI 依赖
# ─────────────────────────────────────────────────────────────

def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """强制认证依赖：返回用户 dict，否则 401。"""
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    user_id = _get_user_id_from_token(creds.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌已过期或无效")
    row = db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return dict(row)


def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """可选认证依赖：有令牌则返回用户，没有则返回 None（向后兼容匿名访问）。"""
    if not creds:
        return None
    user_id = _get_user_id_from_token(creds.credentials)
    if not user_id:
        return None
    row = db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────
# 用户 CRUD
# ─────────────────────────────────────────────────────────────

def _validate_phone(phone: str) -> str:
    """标准化手机号：仅支持11位中国大陆手机号，返回标准化格式 +86XXXXXXXXXXX"""
    import re
    phone = phone.strip().replace(" ", "").replace("-", "")
    # 去掉 +86 或 86 前缀后剩余11位
    if phone.startswith("+86"):
        phone = phone[3:]
    elif phone.startswith("86") and len(phone) == 13:
        phone = phone[2:]
    if not re.match(r"^1[3-9]\d{9}$", phone):
        raise ValueError("手机号格式错误，请输入11位中国大陆手机号")
    return "+86" + phone


def create_user(username: str, password: str, email: str = "", phone: str = "") -> dict:
    if db.fetchone("SELECT id FROM users WHERE username=?", (username,)):
        raise ValueError("用户名已存在")
    if email and db.fetchone("SELECT id FROM users WHERE email=?", (email,)):
        raise ValueError("邮箱已被注册")
    normalized_phone = None
    if phone:
        normalized_phone = _validate_phone(phone)
        if db.fetchone("SELECT id FROM users WHERE phone=?", (normalized_phone,)):
            raise ValueError("该手机号已被注册")
    uid = str(uuid.uuid4())
    salt = _gen_salt()
    phash = hash_password(password, salt)
    now = _now_iso()
    db.execute(
        "INSERT INTO users(id,username,email,phone,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?,?)",
        (uid, username, email or None, normalized_phone, phash, salt, now),
    )
    return {"id": uid, "username": username, "email": email,
            "phone": normalized_phone or "", "created_at": now}


def login_user(username_or_phone: str, password: str, user_agent: str = "") -> dict:
    """支持用户名或手机号登录。"""
    # 判断是否是手机号格式
    import re
    raw = username_or_phone.strip()
    is_phone = bool(re.match(r"^(\+86)?1[3-9]\d{9}$", raw.replace(" ", "")))
    if is_phone:
        try:
            normalized = _validate_phone(raw)
        except ValueError:
            normalized = raw
        row = db.fetchone("SELECT * FROM users WHERE phone=?", (normalized,))
        if not row:
            raise ValueError("手机号未注册或密码错误")
    else:
        row = db.fetchone("SELECT * FROM users WHERE username=?", (raw,))
        if not row:
            raise ValueError("用户名或密码错误")
    if not verify_password(password, row["password_salt"], row["password_hash"]):
        raise ValueError("用户名或密码错误")
    db.execute("UPDATE users SET last_login=? WHERE id=?", (_now_iso(), row["id"]))
    token = create_token(row["id"], user_agent)
    return {
        "token": token,
        "user": {
            "id":          row["id"],
            "username":    row["username"],
            "email":       row["email"] or "",
            "phone":       row["phone"] or "",
            "nickname":    row["nickname"] or row["username"],
            "avatar_emoji": row["avatar_emoji"],
            "created_at":  row["created_at"],
        },
    }


def change_password(user_id: str, old_password: str, new_password: str) -> None:
    """验证旧密码后更新为新密码。"""
    row = db.fetchone("SELECT password_hash, password_salt FROM users WHERE id=?", (user_id,))
    if not row:
        raise ValueError("用户不存在")
    if not verify_password(old_password, row["password_salt"], row["password_hash"]):
        raise ValueError("旧密码错误")
    if len(new_password) < 6:
        raise ValueError("新密码至少6位")
    new_salt = _gen_salt()
    new_hash = hash_password(new_password, new_salt)
    db.execute(
        "UPDATE users SET password_hash=?, password_salt=? WHERE id=?",
        (new_hash, new_salt, user_id)
    )
