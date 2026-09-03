"""
NoteAI 认证模块 — 纯 stdlib，无需额外依赖。
密码：PBKDF2-SHA256（100000 轮）
令牌：secrets.token_urlsafe(32) 存 SQLite user_sessions
"""
import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# 导出供 api.py 使用
__all__ = [
    "get_current_user", "get_optional_user", "create_user", "login_user",
    "login_user_by_id", "delete_token", "delete_user_tokens",
    "set_verified_phone", "set_verified_email", "reset_password_for_user",
    "HTTPAuthorizationCredentials", "_bearer",
]

import db
import account_security as _security
from content_retention import CONTRACT_VERSION as _CONTRACT_VERSION

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
    with db.transaction(write=True) as tx:
        row = tx.fetchone(
            "SELECT id,deletion_requested_at FROM users WHERE id=?"
            + (" FOR UPDATE" if db.using_postgres() else ""),
            (user_id,),
        )
        if not row or row["deletion_requested_at"]:
            raise ValueError("用户不存在")
        return _create_token_with_storage(tx, user_id, user_agent)


def _create_token_with_storage(storage, user_id: str, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    storage.execute(
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


def delete_user_tokens(user_id: str) -> None:
    with db.transaction(write=True) as tx:
        tx.fetchone(
            "SELECT id FROM users WHERE id=?"
            + (" FOR UPDATE" if db.using_postgres() else ""),
            (user_id,),
        )
        tx.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))


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
    if not row or row["deletion_requested_at"]:
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
    return dict(row) if row and not row["deletion_requested_at"] else None


# ─────────────────────────────────────────────────────────────
# 用户 CRUD
# ─────────────────────────────────────────────────────────────

def _validate_phone(phone: str) -> str:
    """标准化手机号：仅支持11位中国大陆手机号，返回标准化格式 +86XXXXXXXXXXX"""
    return _security.normalize_phone(phone)


def create_user(
    username: str,
    password: str,
    email: str = "",
    phone: str = "",
    *,
    phone_verified: bool = False,
    email_verified: bool = False,
    contract_version: str = "",
    privacy_accepted: bool = False,
    cross_border_notice_acknowledged: bool = False,
) -> dict:
    with db.transaction(write=True) as tx:
        return create_user_with_storage(
            tx,
            username,
            password,
            email,
            phone,
            phone_verified=phone_verified,
            email_verified=email_verified,
            contract_version=contract_version,
            privacy_accepted=privacy_accepted,
            cross_border_notice_acknowledged=(
                cross_border_notice_acknowledged
            ),
        )


def _is_unique_violation(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.IntegrityError) or (
        str(getattr(exc, "sqlstate", "") or "") == "23505"
    )


def create_user_with_storage(
    storage,
    username: str,
    password: str,
    email: str = "",
    phone: str = "",
    *,
    phone_verified: bool = False,
    email_verified: bool = False,
    contract_version: str = "",
    privacy_accepted: bool = False,
    cross_border_notice_acknowledged: bool = False,
) -> dict:
    username = str(username or "").strip()
    if not 3 <= len(username) <= 40:
        raise ValueError("用户名长度需为3至40位")
    normalized_email = _security.normalize_email(email) if email else None
    normalized_phone = _validate_phone(phone) if phone else None
    _security.validate_password(
        password,
        identity_values=(username, normalized_email or "", normalized_phone or ""),
    )
    if normalized_phone:
        if not phone_verified:
            raise ValueError("手机号必须先完成验证码验证")
    if contract_version and (
        contract_version != _CONTRACT_VERSION
        or not privacy_accepted
        or not cross_border_notice_acknowledged
    ):
        raise ValueError("必须确认当前版本的服务、隐私及跨境处理说明")
    uid = str(uuid.uuid4())
    salt = _gen_salt()
    phash = hash_password(password, salt)
    now = _now_iso()
    if storage.fetchone("SELECT id FROM users WHERE username=?", (username,)):
        raise ValueError("用户名已存在")
    if normalized_email and storage.fetchone(
            "SELECT id FROM users WHERE email=?",
            (normalized_email,),
    ):
        raise ValueError("邮箱已被注册")
    if normalized_phone and storage.fetchone(
            "SELECT id FROM users WHERE phone=?",
            (normalized_phone,),
    ):
        raise ValueError("该手机号已被注册")
    try:
        storage.execute(
            "INSERT INTO users("
            "id,username,email,phone,password_hash,password_salt,created_at,"
            "phone_verified_at,email_verified_at,password_changed_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                username,
                normalized_email,
                normalized_phone,
                phash,
                salt,
                now,
                now if normalized_phone and phone_verified else None,
                now if normalized_email and email_verified else None,
                now,
            ),
        )
        if contract_version:
            storage.execute(
                "INSERT INTO user_contract_acceptances("
                "user_id,contract_version,privacy_accepted_at,"
                "cross_border_notice_acknowledged_at,source"
                ") VALUES(?,?,?,?,?)",
                (uid, contract_version, now, now, "registration"),
            )
    except BaseException as exc:
        if _is_unique_violation(exc):
            raise ValueError("用户名或联系方式已被使用") from exc
        raise
    return {"id": uid, "username": username, "email": normalized_email or "",
            "phone": normalized_phone or "", "created_at": now}


def login_user(
    username_or_phone: str,
    password: str,
    user_agent: str = "",
    requester_fingerprint: str = "",
) -> dict:
    """支持用户名或手机号登录。"""
    raw = str(username_or_phone or "").strip()
    try:
        normalized_phone = _validate_phone(raw)
    except ValueError:
        normalized_phone = None
    failed = False
    result = None
    with db.transaction(write=True) as tx:
        _security.assert_login_allowed_with_storage(
            tx,
            raw,
            requester_fingerprint,
            lock=True,
        )
        lock_suffix = " FOR UPDATE" if db.using_postgres() else ""
        if normalized_phone:
            row = tx.fetchone(
                "SELECT * FROM users WHERE phone=?" + lock_suffix,
                (normalized_phone,),
            )
            eligible = bool(
                row
                and not row["deletion_requested_at"]
                and row["phone_verified_at"]
            )
        else:
            row = tx.fetchone(
                "SELECT * FROM users WHERE username=?" + lock_suffix,
                (raw,),
            )
            eligible = bool(row and not row["deletion_requested_at"])
        if (
            not eligible
            or not verify_password(
                password,
                row["password_salt"],
                row["password_hash"],
            )
        ):
            _security.record_login_failure_with_storage(
                tx,
                raw,
                requester_fingerprint,
            )
            failed = True
        else:
            _security.clear_login_failures_with_storage(
                tx,
                raw,
                requester_fingerprint,
            )
            now = _now_iso()
            tx.execute("UPDATE users SET last_login=? WHERE id=?", (now, row["id"]))
            token = _create_token_with_storage(tx, row["id"], user_agent)
            result = _login_result(dict(row), token)
    if failed or result is None:
        raise ValueError("用户名、手机号或密码错误")
    return result


def login_user_by_id(user_id: str, *, user_agent: str = "") -> dict:
    with db.transaction(write=True) as tx:
        return login_user_by_id_with_storage(
            tx,
            user_id,
            user_agent=user_agent,
        )


def login_user_by_id_with_storage(
    storage,
    user_id: str,
    *,
    user_agent: str = "",
) -> dict:
    row = storage.fetchone(
        "SELECT * FROM users WHERE id=?"
        + (" FOR UPDATE" if getattr(storage, "postgres", db.using_postgres()) else ""),
        (user_id,),
    )
    if not row or row["deletion_requested_at"]:
        raise ValueError("用户不存在")
    storage.execute(
        "UPDATE users SET last_login=? WHERE id=?",
        (_now_iso(), row["id"]),
    )
    token = _create_token_with_storage(storage, row["id"], user_agent)
    return _login_result(dict(row), token)


def _login_result(row: dict, token: str) -> dict:
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


def _set_password_with_storage(storage, row, new_password: str) -> None:
    _security.validate_password(
        new_password,
        identity_values=(row["username"], row["email"] or "", row["phone"] or ""),
    )
    new_salt = _gen_salt()
    new_hash = hash_password(new_password, new_salt)
    storage.execute(
        "UPDATE users SET password_hash=?,password_salt=?,password_changed_at=? WHERE id=?",
        (new_hash, new_salt, _now_iso(), row["id"]),
    )
    storage.execute("DELETE FROM user_sessions WHERE user_id=?", (row["id"],))


def change_password(user_id: str, old_password: str, new_password: str) -> None:
    """验证旧密码后更新为新密码。"""
    with db.transaction(write=True) as tx:
        row = tx.fetchone(
            "SELECT id,username,email,phone,password_hash,password_salt,"
            "deletion_requested_at FROM users WHERE id=?"
            + (" FOR UPDATE" if db.using_postgres() else ""),
            (user_id,),
        )
        if not row or row["deletion_requested_at"]:
            raise ValueError("用户不存在")
        if not verify_password(old_password, row["password_salt"], row["password_hash"]):
            raise ValueError("旧密码错误")
        _set_password_with_storage(tx, row, new_password)


def reset_password_for_user(user_id: str, new_password: str) -> None:
    with db.transaction(write=True) as tx:
        reset_password_for_user_with_storage(tx, user_id, new_password)


def reset_password_for_user_with_storage(
    storage,
    user_id: str,
    new_password: str,
) -> None:
    row = storage.fetchone(
        "SELECT id,username,email,phone,deletion_requested_at FROM users WHERE id=?"
        + (" FOR UPDATE" if getattr(storage, "postgres", db.using_postgres()) else ""),
        (user_id,),
    )
    if not row or row["deletion_requested_at"]:
        raise ValueError("用户不存在")
    _set_password_with_storage(storage, row, new_password)


def set_verified_phone(user_id: str, phone: str) -> str:
    with db.transaction(write=True) as tx:
        return set_verified_phone_with_storage(tx, user_id, phone)


def set_verified_phone_with_storage(storage, user_id: str, phone: str) -> str:
    normalized = _validate_phone(phone)
    user = storage.fetchone(
        "SELECT id,deletion_requested_at FROM users WHERE id=?"
        + (" FOR UPDATE" if getattr(storage, "postgres", db.using_postgres()) else ""),
        (user_id,),
    )
    if not user or user["deletion_requested_at"]:
        raise ValueError("用户不存在")
    existing = storage.fetchone(
        "SELECT id FROM users WHERE phone=? AND id!=?",
        (normalized, user_id),
    )
    if existing:
        raise ValueError("该手机号已被其他账号绑定")
    try:
        storage.execute(
            "UPDATE users SET phone=?,phone_verified_at=? WHERE id=?",
            (normalized, _now_iso(), user_id),
        )
    except BaseException as exc:
        if _is_unique_violation(exc):
            raise ValueError("该手机号已被其他账号绑定") from exc
        raise
    return normalized


def set_verified_email(user_id: str, email: str) -> str:
    with db.transaction(write=True) as tx:
        return set_verified_email_with_storage(tx, user_id, email)


def set_verified_email_with_storage(storage, user_id: str, email: str) -> str:
    normalized = _security.normalize_email(email)
    user = storage.fetchone(
        "SELECT id,deletion_requested_at FROM users WHERE id=?"
        + (" FOR UPDATE" if getattr(storage, "postgres", db.using_postgres()) else ""),
        (user_id,),
    )
    if not user or user["deletion_requested_at"]:
        raise ValueError("用户不存在")
    existing = storage.fetchone(
        "SELECT id FROM users WHERE email=? AND id!=?",
        (normalized, user_id),
    )
    if existing:
        raise ValueError("该邮箱已被其他账号绑定")
    try:
        storage.execute(
            "UPDATE users SET email=?,email_verified_at=? WHERE id=?",
            (normalized, _now_iso(), user_id),
        )
    except BaseException as exc:
        if _is_unique_violation(exc):
            raise ValueError("该邮箱已被其他账号绑定") from exc
        raise
    return normalized
