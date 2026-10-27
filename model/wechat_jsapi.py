"""Short-lived, session-bound Official Account OAuth for JSAPI checkout.

This module never creates a payment or a NoteAI login. A successful exchange
supplies only the payer identity for the existing payment order contract.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import ssl
from urllib.parse import urlencode

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import db
import payment_contract


TTL_SECONDS = 300
MAX_BEGIN_PER_WINDOW = 10
MAX_RESPONSE_BYTES = 16384
_ORIGINS = frozenset({"https://noteaipro.com", "https://www.noteaipro.com"})
_STATE_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_OPENID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_API_HOST = "api.weixin.qq.com"
_KEY_DOMAIN = b"noteai-wechat-jsapi-openid-v1\0"


class JSAPIError(RuntimeError):
    def __init__(self, code="WECHAT_JSAPI_UNAVAILABLE"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Configuration:
    app_id: str
    app_secret: str = field(repr=False)


def configuration(payment_app_id):
    if os.environ.get("NOTEAI_WECHAT_JSAPI_ENABLED") != "1":
        raise JSAPIError("WECHAT_JSAPI_DISABLED")
    app_id = os.environ.get("NOTEAI_WECHAT_SHARE_APP_ID", "")
    app_secret = os.environ.get("NOTEAI_WECHAT_SHARE_APP_SECRET", "")
    if (not re.fullmatch(r"wx[0-9a-f]{16}", app_id)
            or not re.fullmatch(r"[A-Za-z0-9]{16,128}", app_secret)):
        raise JSAPIError("WECHAT_JSAPI_NOT_CONFIGURED")
    if (type(payment_app_id) is not str
            or not re.fullmatch(r"wx[0-9a-f]{16}", payment_app_id)
            or not hmac.compare_digest(app_id, payment_app_id)):
        raise JSAPIError("WECHAT_JSAPI_APP_ID_MISMATCH")
    return Configuration(app_id, app_secret)


def _now(now):
    value = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise JSAPIError("WECHAT_JSAPI_CLOCK_INVALID")
    return value.astimezone(timezone.utc)


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(user_id, session_token):
    if (type(user_id) is not str or not 1 <= len(user_id) <= 128
            or type(session_token) is not str or not 16 <= len(session_token) <= 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in session_token)):
        raise JSAPIError("WECHAT_JSAPI_SESSION_INVALID")
    return user_id, _hash("noteai-wechat-jsapi-session-v1\0" + session_token)


def _purchase(product_kind, product_id, idempotency_key):
    try:
        item = payment_contract._catalog_item(product_kind, product_id)
    except payment_contract.PaymentContractError:
        raise JSAPIError("WECHAT_JSAPI_PRODUCT_INVALID") from None
    if (type(idempotency_key) is not str
            or not re.fullmatch(r"[\x21-\x7e]{8,128}", idempotency_key)):
        raise JSAPIError("WECHAT_JSAPI_IDEMPOTENCY_KEY_INVALID")
    return (item["product_kind"], item["product_id"],
            payment_contract._hash("noteai-payment-idempotency-v1", idempotency_key))


@contextmanager
def _transaction(transaction_factory):
    expired_error = None
    with (db.transaction if transaction_factory is None else transaction_factory)(write=True) as tx:
        try:
            yield tx
        except JSAPIError as exc:
            if exc.code != "WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED":
                raise
            # This error occurs only before any state transition. Commit the
            # admitted owner's expired-row cleanup before returning the error.
            expired_error = exc
    if expired_error is not None:
        raise expired_error


def _admit(tx, user_id, session_token, clock):
    if tx.postgres:
        tx.execute("SELECT set_config('noteai.jsapi_user_id', ?, true)", (user_id,))
    try:
        payment_contract._payment_user_fence(tx, user_id)
    except (ValueError, payment_contract.PaymentContractError):
        raise JSAPIError("WECHAT_JSAPI_ACCOUNT_NOT_WRITABLE") from None
    session = tx.fetchone(
        "SELECT expires_at FROM user_sessions WHERE token=? AND user_id=?",
        (session_token, user_id),
    )
    try:
        expires = datetime.fromisoformat(str(session["expires_at"]).replace("Z", "+00:00"))
        active = expires.tzinfo is not None and expires.astimezone(timezone.utc) > clock
    except (TypeError, ValueError):
        active = False
    if not active:
        raise JSAPIError("WECHAT_JSAPI_SESSION_INVALID")
    # The RLS policy and explicit owner predicate both bound secret cleanup.
    tx.execute(
        "DELETE FROM payment_wechat_oauth_states WHERE user_id=? AND expires_at<=?",
        (user_id, clock.isoformat()),
    )


def _bound_state(tx, state, user_id, session_hash, app_id, clock):
    if type(state) is not str or not _STATE_RE.fullmatch(state):
        raise JSAPIError("WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED")
    row = tx.fetchone(
        "SELECT * FROM payment_wechat_oauth_states WHERE state_hash=? AND user_id=?"
        + (" FOR UPDATE" if tx.postgres else ""),
        (_hash(state), user_id),
    )
    if (row is None or not hmac.compare_digest(str(row["session_hash"]), session_hash)
            or not hmac.compare_digest(str(row["app_id"]), app_id)):
        raise JSAPIError("WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED")
    try:
        expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        active = expires.tzinfo is not None and expires.astimezone(timezone.utc) > clock
    except (TypeError, ValueError):
        active = False
    if not active:
        raise JSAPIError("WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED")
    return row


def _aad(row):
    fields = ("state_hash", "user_id", "session_hash", "app_id", "product_kind",
              "product_id", "idempotency_key_hash")
    return json.dumps([row[name] for name in fields], separators=(",", ":")).encode()


def _key(config):
    return hashlib.sha256(
        _KEY_DOMAIN + config.app_id.encode() + b"\0" + config.app_secret.encode()
    ).digest()


def _encrypt(openid, row, config):
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key(config)).encrypt(nonce, openid.encode(), _aad(row))
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def _decrypt(row, config):
    try:
        value = row["openid_ciphertext"]
        if type(value) is not str or not 1 <= len(value) <= 512:
            raise ValueError
        packed = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        openid = AESGCM(_key(config)).decrypt(packed[:12], packed[12:], _aad(row)).decode()
        if not _OPENID_RE.fullmatch(openid):
            raise ValueError
        return openid
    except (ValueError, TypeError, InvalidTag, UnicodeError):
        raise JSAPIError("WECHAT_JSAPI_CONTEXT_INVALID") from None


def begin(*, user_id, session_token, product_kind, product_id, idempotency_key,
          origin, payment_app_id, now=None, transaction_factory=None):
    config = configuration(payment_app_id)
    uid, session_hash = _identity(user_id, session_token)
    kind, product, key_hash = _purchase(product_kind, product_id, idempotency_key)
    if type(origin) is not str or origin not in _ORIGINS:
        raise JSAPIError("WECHAT_JSAPI_ORIGIN_INVALID")
    clock = _now(now)
    state = secrets.token_hex(32)
    with _transaction(transaction_factory) as tx:
        _admit(tx, uid, session_token, clock)
        count = tx.fetchone(
            "SELECT COUNT(*) AS n FROM payment_wechat_oauth_states "
            "WHERE user_id=? AND created_at>?",
            (uid, (clock - timedelta(seconds=TTL_SECONDS)).isoformat()),
        )
        if int(count["n"]) >= MAX_BEGIN_PER_WINDOW:
            raise JSAPIError("WECHAT_JSAPI_RATE_LIMITED")
        tx.execute(
            "INSERT INTO payment_wechat_oauth_states("
            "state_hash,user_id,session_hash,app_id,product_kind,product_id,"
            "idempotency_key_hash,status,openid_ciphertext,created_at,expires_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,'pending',NULL,?,?,?)",
            (_hash(state), uid, session_hash, config.app_id, kind, product, key_hash,
             clock.isoformat(), (clock + timedelta(seconds=TTL_SECONDS)).isoformat(),
             clock.isoformat()),
        )
    query = urlencode({"appid": config.app_id, "redirect_uri": origin + "/wechat-pay.html",
                       "response_type": "code", "scope": "snsapi_base", "state": state})
    return {"state": state, "authorize_url":
            "https://open.weixin.qq.com/connect/oauth2/authorize?" + query + "#wechat_redirect"}


def _request_openid(config, code):
    # This one-use credential is sent only to WeChat's fixed TLS host. Neither
    # the request path nor response is logged, persisted, redirected or retried.
    path = "/sns/oauth2/access_token?" + urlencode({
        "appid": config.app_id, "secret": config.app_secret, "code": code,
        "grant_type": "authorization_code",
    })
    connection = http.client.HTTPSConnection(
        _API_HOST, 443, timeout=4, context=ssl.create_default_context()
    )
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if response.status != 200 or len(raw) > MAX_RESPONSE_BYTES:
            raise JSAPIError("WECHAT_JSAPI_OAUTH_UNKNOWN")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise JSAPIError("WECHAT_JSAPI_OAUTH_UNKNOWN")
        return data
    except Exception:
        raise JSAPIError("WECHAT_JSAPI_OAUTH_UNKNOWN") from None
    finally:
        connection.close()


def _finish(*, state, user_id, session_token, session_hash, config, status,
            openid=None, now=None, transaction_factory=None):
    clock = _now(now)
    with _transaction(transaction_factory) as tx:
        _admit(tx, user_id, session_token, clock)
        row = _bound_state(tx, state, user_id, session_hash, config.app_id, clock)
        if row["status"] != "exchanging":
            raise JSAPIError("WECHAT_JSAPI_CONTEXT_INVALID")
        ciphertext = _encrypt(openid, row, config) if status == "ready" else None
        changed = tx.execute(
            "UPDATE payment_wechat_oauth_states SET status=?,openid_ciphertext=?,updated_at=? "
            "WHERE state_hash=? AND user_id=? AND status='exchanging'",
            (status, ciphertext, clock.isoformat(), _hash(state), user_id),
        )
        if changed.rowcount != 1:
            raise JSAPIError("WECHAT_JSAPI_CONTEXT_INVALID")


def complete(*, user_id, session_token, state, code, payment_app_id,
             now=None, transaction_factory=None, transport=None):
    config = configuration(payment_app_id)
    uid, session_hash = _identity(user_id, session_token)
    clock = _now(now)
    with _transaction(transaction_factory) as tx:
        _admit(tx, uid, session_token, clock)
        row = _bound_state(tx, state, uid, session_hash, config.app_id, clock)
        if row["status"] == "ready":
            return {"checkout_context": state}
        if row["status"] == "exchanging":
            raise JSAPIError("WECHAT_JSAPI_OAUTH_IN_PROGRESS")
        if row["status"] != "pending":
            raise JSAPIError("WECHAT_JSAPI_OAUTH_ALREADY_USED")
        if type(code) is not str or not _CODE_RE.fullmatch(code):
            raise JSAPIError("WECHAT_JSAPI_CODE_INVALID")
        changed = tx.execute(
            "UPDATE payment_wechat_oauth_states SET status='exchanging',updated_at=? "
            "WHERE state_hash=? AND user_id=? AND status='pending'",
            (clock.isoformat(), _hash(state), uid),
        )
        if changed.rowcount != 1:
            raise JSAPIError("WECHAT_JSAPI_OAUTH_ALREADY_USED")
    # Claim is committed before the one network request; no transaction or
    # provider-level automatic retry can exchange this code a second time.
    status, openid = "unknown", None
    try:
        data = (transport or _request_openid)(config, code)
        if not isinstance(data, dict):
            raise ValueError
        if data.get("errcode", 0) != 0:
            status = "failed"
        elif type(data.get("openid")) is str and _OPENID_RE.fullmatch(data["openid"]):
            status, openid = "ready", data["openid"]
    except Exception:
        # A timeout or malformed response may have consumed the code. Preserve
        # the unknown result without exposing exception text or releasing it.
        status = "unknown"
    _finish(state=state, user_id=uid, session_token=session_token, session_hash=session_hash,
            config=config, status=status, openid=openid, now=now,
            transaction_factory=transaction_factory)
    if status != "ready":
        raise JSAPIError("WECHAT_JSAPI_OAUTH_REJECTED" if status == "failed"
                         else "WECHAT_JSAPI_OAUTH_UNKNOWN")
    return {"checkout_context": state}


def resolve(*, user_id, session_token, product_kind, product_id, idempotency_key,
            checkout_context, payment_app_id, now=None, transaction_factory=None):
    config = configuration(payment_app_id)
    uid, session_hash = _identity(user_id, session_token)
    kind, product, key_hash = _purchase(product_kind, product_id, idempotency_key)
    clock = _now(now)
    with _transaction(transaction_factory) as tx:
        _admit(tx, uid, session_token, clock)
        row = _bound_state(tx, checkout_context, uid, session_hash, config.app_id, clock)
        if (row["status"] != "ready" or row["product_kind"] != kind
                or row["product_id"] != product
                or not hmac.compare_digest(row["idempotency_key_hash"], key_hash)):
            raise JSAPIError("WECHAT_JSAPI_CONTEXT_INVALID")
        return _decrypt(row, config)
