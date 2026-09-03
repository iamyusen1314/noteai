"""Account security contracts that are safe to exercise without real providers.

The OTP delivery adapter is deliberately disabled by default. ``test`` mode is
available only outside a production deployment stage and never returns a code
through an API response. Production SMS/email delivery remains a later,
separately approved integration.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import db


PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_FAILURES = 5
LOGIN_BLOCK_MINUTES = 15
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_MAX_REQUESTS_PER_HOUR = 5
OTP_MAX_REQUESTS_PER_REQUESTER_HOUR = 10

_ALLOWED_PURPOSE_CHANNELS = {
    "register_phone": {"phone"},
    "bind_phone": {"phone"},
    "verify_email": {"email"},
    "login_phone": {"phone"},
    "password_reset": {"phone", "email"},
}
_COMMON_PASSWORDS = {
    "1234567890",
    "password123",
    "qwerty12345",
    "noteai12345",
    "1111111111",
}


class VerificationDeliveryUnavailable(RuntimeError):
    pass


class VerificationRejected(ValueError):
    pass


class LoginTemporarilyBlocked(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def normalize_phone(phone: str) -> str:
    raw = str(phone or "").strip().replace(" ", "").replace("-", "")
    if raw.startswith("+86"):
        raw = raw[3:]
    elif raw.startswith("86") and len(raw) == 13:
        raw = raw[2:]
    if not re.fullmatch(r"1[3-9][0-9]{9}", raw):
        raise ValueError("手机号格式错误，请输入11位中国大陆手机号")
    return f"+86{raw}"


def normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if len(normalized) > 254 or not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
        normalized,
        flags=re.I,
    ):
        raise ValueError("邮箱格式错误")
    return normalized


def validate_password(password: str, *, identity_values: tuple[str, ...] = ()) -> str:
    value = str(password or "")
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"密码至少{PASSWORD_MIN_LENGTH}位")
    if len(value) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"密码不得超过{PASSWORD_MAX_LENGTH}位")
    if value.lower() in _COMMON_PASSWORDS:
        raise ValueError("密码过于常见，请更换")
    categories = sum((
        bool(re.search(r"[A-Za-z]", value)),
        bool(re.search(r"\d", value)),
        bool(re.search(r"[^A-Za-z0-9]", value)),
    ))
    if categories < 2:
        raise ValueError("密码需至少包含字母、数字或符号中的两类")
    lowered = value.lower()
    password_digits = re.sub(r"\D+", "", lowered)
    identity_tokens: set[str] = set()
    identity_phone_numbers: set[str] = set()
    for identity in identity_values:
        token = re.sub(r"\s+", "", str(identity or "")).lower()
        if token:
            identity_tokens.add(token)
        digits = re.sub(r"\D+", "", token)
        if len(digits) == 13 and digits.startswith("86"):
            identity_phone_numbers.add(digits[2:])
            identity_tokens.add(digits[2:])
            identity_tokens.add(f"+{digits}")
        elif len(digits) == 11 and digits.startswith("1"):
            identity_phone_numbers.add(digits)
            identity_tokens.add(digits)
            identity_tokens.add(f"86{digits}")
            identity_tokens.add(f"+86{digits}")
    for token in identity_tokens:
        if len(token) >= 4 and token in lowered:
            raise ValueError("密码不得包含完整用户名或联系方式")
    if any(phone in password_digits for phone in identity_phone_numbers):
        raise ValueError("密码不得包含完整用户名或联系方式")
    return value


def _contact(channel: str, destination: str) -> str:
    if channel == "phone":
        return normalize_phone(destination)
    if channel == "email":
        return normalize_email(destination)
    raise ValueError("不支持的验证渠道")


def _digest(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}:{value}".encode("utf-8")).hexdigest()


def _mask_contact(channel: str, destination: str) -> str:
    if channel == "phone":
        raw = normalize_phone(destination).removeprefix("+86")
        return f"{raw[:3]}****{raw[-4:]}"
    normalized = normalize_email(destination)
    local, domain = normalized.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _deployment_stage() -> str:
    return (
        os.environ.get("NOTEAI_DEPLOYMENT_STAGE")
        or os.environ.get("NOTEAI_ENVIRONMENT")
        or ""
    ).strip().lower()


def _test_delivery_code() -> str:
    mode = os.environ.get("NOTEAI_OTP_MODE", "disabled").strip().lower()
    if mode != "test":
        raise VerificationDeliveryUnavailable("验证码发送服务尚未启用")
    if _deployment_stage() not in {"development", "test", "local"}:
        raise VerificationDeliveryUnavailable("测试验证码适配器需要显式非生产环境")
    code = os.environ.get("NOTEAI_OTP_TEST_CODE", "246810").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise VerificationDeliveryUnavailable("测试验证码配置无效")
    return code


def issue_verification(
    *,
    channel: str,
    destination: str,
    purpose: str,
    requested_by_user_id: str | None = None,
    requester_fingerprint: str = "",
) -> dict[str, Any]:
    normalized_channel = str(channel or "").strip().lower()
    normalized_purpose = str(purpose or "").strip().lower()
    if normalized_channel not in _ALLOWED_PURPOSE_CHANNELS.get(normalized_purpose, set()):
        raise ValueError("验证用途与渠道不匹配")
    normalized_destination = _contact(normalized_channel, destination)
    destination_hash = _digest(normalized_channel, normalized_destination)
    requester_hash = (
        _digest("requester", requester_fingerprint)
        if requester_fingerprint
        else ""
    )
    now = _now()
    code = _test_delivery_code()
    challenge_id = str(uuid.uuid4())
    salt = secrets.token_hex(16)
    code_hash = hashlib.pbkdf2_hmac(
        "sha256",
        code.encode("utf-8"),
        salt.encode("utf-8"),
        50_000,
    ).hex()
    with db.transaction(write=True) as tx:
        if db.using_postgres():
            lock_names = [f"otp:{destination_hash}:{normalized_purpose}"]
            if requester_hash:
                lock_names.append(f"otp-requester:{requester_hash}:{normalized_purpose}")
            for lock_name in sorted(lock_names):
                tx.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(?))",
                    (lock_name,),
                )
        recent = tx.fetchone(
            "SELECT COUNT(*) AS c FROM auth_verification_challenges "
            "WHERE destination_hash=? AND purpose=? AND created_at>=?",
            (
                destination_hash,
                normalized_purpose,
                _iso(now - timedelta(hours=1)),
            ),
        )
        if recent and int(recent["c"] or 0) >= OTP_MAX_REQUESTS_PER_HOUR:
            raise VerificationRejected("验证码请求过于频繁，请稍后再试")
        if requester_hash:
            requester_recent = tx.fetchone(
                "SELECT COUNT(*) AS c FROM auth_verification_challenges "
                "WHERE requester_hash=? AND purpose=? AND created_at>=?",
                (
                    requester_hash,
                    normalized_purpose,
                    _iso(now - timedelta(hours=1)),
                ),
            )
            if (
                requester_recent
                and int(requester_recent["c"] or 0)
                >= OTP_MAX_REQUESTS_PER_REQUESTER_HOUR
            ):
                raise VerificationRejected("验证码请求过于频繁，请稍后再试")
        tx.execute(
            "INSERT INTO auth_verification_challenges("
            "id,channel,destination_hash,destination_masked,purpose,code_hash,code_salt,"
            "created_at,expires_at,consumed_at,attempt_count,max_attempts,"
            "requested_by_user_id,requester_hash) VALUES(?,?,?,?,?,?,?,?,?,NULL,0,?,?,?)",
            (
                challenge_id,
                normalized_channel,
                destination_hash,
                _mask_contact(normalized_channel, normalized_destination),
                normalized_purpose,
                code_hash,
                salt,
                _iso(now),
                _iso(now + timedelta(minutes=OTP_TTL_MINUTES)),
                OTP_MAX_ATTEMPTS,
                requested_by_user_id,
                requester_hash,
            ),
        )
    return {
        "challenge_id": challenge_id,
        "delivery": "test",
        "destination_masked": _mask_contact(normalized_channel, normalized_destination),
        "expires_in_seconds": OTP_TTL_MINUTES * 60,
    }


def consume_verification(
    *,
    challenge_id: str,
    code: str,
    channel: str,
    destination: str,
    purpose: str,
    requested_by_user_id: str | None = None,
) -> str:
    rejection: VerificationRejected | None = None
    normalized_destination = ""
    with db.transaction(write=True) as tx:
        try:
            normalized_destination, row = verify_verification_with_storage(
                tx,
                challenge_id=challenge_id,
                code=code,
                channel=channel,
                destination=destination,
                purpose=purpose,
                requested_by_user_id=requested_by_user_id,
            )
            mark_verification_consumed_with_storage(tx, row["id"])
        except VerificationRejected as exc:
            rejection = exc
    if rejection is not None:
        raise rejection
    return normalized_destination


def verify_verification_with_storage(
    storage: Any,
    *,
    challenge_id: str,
    code: str,
    channel: str,
    destination: str,
    purpose: str,
    requested_by_user_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Lock and verify a challenge without consuming it.

    Callers may validate several challenges first, then consume all of them in
    the same transaction as the protected business mutation.
    """
    generic_error = "验证码无效或已过期"
    expected_channel = str(channel or "").strip().lower()
    expected_purpose = str(purpose or "").strip().lower()
    try:
        normalized_destination = _contact(expected_channel, destination)
    except ValueError as exc:
        raise VerificationRejected(generic_error) from exc
    lock_suffix = " FOR UPDATE" if getattr(storage, "postgres", db.using_postgres()) else ""
    row = storage.fetchone(
        "SELECT * FROM auth_verification_challenges WHERE id=?" + lock_suffix,
        (str(challenge_id or "").strip(),),
    )
    now = _now()
    if not row or (
        row["channel"] != expected_channel
        or row["purpose"] != expected_purpose
        or row["destination_hash"] != _digest(expected_channel, normalized_destination)
        or row["consumed_at"]
        or (_parse_iso(row["expires_at"]) or now) <= now
        or int(row["attempt_count"] or 0)
        >= int(row["max_attempts"] or OTP_MAX_ATTEMPTS)
        or (row["requested_by_user_id"] or None) != (requested_by_user_id or None)
    ):
        raise VerificationRejected(generic_error)
    supplied_hash = hashlib.pbkdf2_hmac(
        "sha256",
        str(code or "").encode("utf-8"),
        str(row["code_salt"]).encode("utf-8"),
        50_000,
    ).hex()
    if not secrets.compare_digest(supplied_hash, str(row["code_hash"])):
        storage.execute(
            "UPDATE auth_verification_challenges "
            "SET attempt_count=attempt_count+1 WHERE id=?",
            (row["id"],),
        )
        raise VerificationRejected(generic_error)
    return normalized_destination, dict(row)


def mark_verification_consumed_with_storage(storage: Any, challenge_id: str) -> None:
    updated = storage.execute(
        "UPDATE auth_verification_challenges SET consumed_at=? "
        "WHERE id=? AND consumed_at IS NULL",
        (_iso(_now()), challenge_id),
    )
    if int(getattr(updated, "rowcount", 0) or 0) != 1:
        raise VerificationRejected("验证码无效或已过期")


def canonical_login_identifier(identifier: str) -> str:
    raw = str(identifier or "").strip()
    try:
        return f"phone:{normalize_phone(raw)}"
    except ValueError:
        # Username lookup is deliberately case-sensitive, so the limiter must
        # use the same identity semantics and never merge Alice with alice.
        return f"username:{raw}"


def _login_keys(identifier: str, requester_fingerprint: str = "") -> tuple[str, ...]:
    normalized = canonical_login_identifier(identifier)
    requester = str(requester_fingerprint or "").strip()
    keys = [_digest("login_account", normalized)]
    if requester:
        keys.append(_digest("login_pair", f"{normalized}|{requester}"))
    return tuple(keys)


def assert_login_allowed_with_storage(
    storage: Any,
    identifier: str,
    requester_fingerprint: str = "",
    *,
    lock: bool = False,
) -> None:
    for key in _login_keys(identifier, requester_fingerprint):
        if lock:
            now = _now()
            storage.execute(
                "INSERT INTO auth_login_limits("
                "identifier_hash,window_started_at,failure_count,blocked_until,updated_at"
                ") VALUES(?,?,0,NULL,?) ON CONFLICT(identifier_hash) DO NOTHING",
                (key, _iso(now), _iso(now)),
            )
        lock_suffix = " FOR UPDATE" if lock and db.using_postgres() else ""
        row = storage.fetchone(
            "SELECT blocked_until FROM auth_login_limits WHERE identifier_hash=?"
            + lock_suffix,
            (key,),
        )
        blocked_until = _parse_iso(row["blocked_until"]) if row else None
        if blocked_until and blocked_until > _now():
            raise LoginTemporarilyBlocked("登录尝试过多，请稍后再试")


def assert_login_allowed(identifier: str, requester_fingerprint: str = "") -> None:
    assert_login_allowed_with_storage(db, identifier, requester_fingerprint)


def record_login_failure_with_storage(
    storage: Any,
    identifier: str,
    requester_fingerprint: str = "",
) -> None:
    now = _now()
    for key in _login_keys(identifier, requester_fingerprint):
        storage.execute(
            "INSERT INTO auth_login_limits("
            "identifier_hash,window_started_at,failure_count,blocked_until,updated_at"
            ") VALUES(?,?,0,NULL,?) ON CONFLICT(identifier_hash) DO NOTHING",
            (key, _iso(now), _iso(now)),
        )
        lock_suffix = " FOR UPDATE" if db.using_postgres() else ""
        row = storage.fetchone(
            "SELECT * FROM auth_login_limits WHERE identifier_hash=?"
            + lock_suffix,
            (key,),
        )
        window_start = _parse_iso(row["window_started_at"]) if row else None
        failures = int(row["failure_count"] or 0) if row else 0
        if not window_start or window_start <= now - timedelta(minutes=LOGIN_WINDOW_MINUTES):
            window_start = now
            failures = 0
        failures += 1
        blocked_until = (
            _iso(now + timedelta(minutes=LOGIN_BLOCK_MINUTES))
            if failures >= LOGIN_MAX_FAILURES
            else None
        )
        storage.execute(
            "UPDATE auth_login_limits SET window_started_at=?,failure_count=?,"
            "blocked_until=?,updated_at=? WHERE identifier_hash=?",
            (_iso(window_start), failures, blocked_until, _iso(now), key),
        )


def record_login_failure(identifier: str, requester_fingerprint: str = "") -> None:
    with db.transaction(write=True) as tx:
        record_login_failure_with_storage(tx, identifier, requester_fingerprint)


def clear_login_failures_with_storage(
    storage: Any,
    identifier: str,
    requester_fingerprint: str = "",
) -> None:
    for key in _login_keys(identifier, requester_fingerprint):
        storage.execute(
            "DELETE FROM auth_login_limits WHERE identifier_hash=?",
            (key,),
        )


def clear_login_failures(identifier: str, requester_fingerprint: str = "") -> None:
    with db.transaction(write=True) as tx:
        clear_login_failures_with_storage(tx, identifier, requester_fingerprint)
