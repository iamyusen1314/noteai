"""Small, opt-in Official Account JS-SDK signer; no OAuth or user data fetch.

Protocol reference: WxJava 1b22c250810f79da2e33a51ab06d740c768ae4cf,
weixin-java-mp/.../api/impl/{BaseWxMpServiceImpl,WxMpServiceHttpClientImpl}.java.
Only stable_token with force_refresh=false is supported, never legacy gettoken.
The operator must verify this account's token ownership before enabling it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import http.client
import json
import os
import re
import secrets
import ssl
import threading
import time
from urllib.parse import urlencode, urlsplit


MAX_URL_LENGTH = 2048
MAX_RESPONSE_BYTES = 16384
COOLDOWN_SECONDS = 60
JS_API_LIST = ("updateAppMessageShareData", "updateTimelineShareData")
_API_HOST = "api.weixin.qq.com"
_STABLE_PATH = "/cgi-bin/stable_token"
_TICKET_PATH = "/cgi-bin/ticket/getticket"


class ShareUnavailable(RuntimeError):
    def __init__(self, code="WECHAT_SHARE_UNAVAILABLE", retry_after=60):
        self.code, self.retry_after = code, retry_after
        super().__init__(code)


class ShareRateLimited(ShareUnavailable):
    pass


class ShareURLInvalid(ValueError):
    pass


@dataclass(frozen=True)
class Configuration:
    app_id: str
    app_secret: str = field(repr=False)

    @property
    def identity(self):
        return hashlib.sha256((self.app_id + "\0" + self.app_secret).encode()).digest()


def configuration():
    # New names deliberately do not borrow payment or an old site's credentials.
    if os.environ.get("NOTEAI_WECHAT_SHARE_ENABLED") != "1":
        raise ShareUnavailable("WECHAT_SHARE_DISABLED")
    app_id = os.environ.get("NOTEAI_WECHAT_SHARE_APP_ID", "")
    secret = os.environ.get("NOTEAI_WECHAT_SHARE_APP_SECRET", "")
    if (os.environ.get("NOTEAI_WECHAT_SHARE_TOKEN_MODE") != "stable"
            or not re.fullmatch(r"wx[0-9a-f]{16}", app_id)
            or not re.fullmatch(r"[A-Za-z0-9]{16,128}", secret)):
        raise ShareUnavailable("WECHAT_SHARE_NOT_CONFIGURED")
    return Configuration(app_id, secret)


def signing_url(url):
    if (type(url) is not str or not 1 <= len(url) <= MAX_URL_LENGTH
            or any(ord(c) < 33 or ord(c) > 126 for c in url)):
        raise ShareURLInvalid("分享页面地址无效")
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise ShareURLInvalid("分享页面地址无效") from None
    if (not url.startswith("https://") or parsed.scheme != "https"
            or parsed.netloc not in {"noteaipro.com", "www.noteaipro.com"}
            or parsed.path not in {"/", "/index.html"}):
        raise ShareURLInvalid("分享页面地址无效")
    # Preserve browser query encoding/order exactly; JS-SDK excludes fragments.
    return url.split("#", 1)[0]


def signature(ticket, nonce, timestamp, url):
    raw = ("jsapi_ticket=" + ticket + "&noncestr=" + nonce
           + "&timestamp=" + str(timestamp) + "&url=" + signing_url(url))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _request_json(method, path, payload):
    # http.client has no automatic URL logging: getticket's token stays private.
    # Fixed TLS host, no proxy, redirects, arbitrary URL fetch or automatic retry.
    connection = http.client.HTTPSConnection(_API_HOST, 443, timeout=4,
                                               context=ssl.create_default_context())
    try:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if response.status != 200 or len(raw) > MAX_RESPONSE_BYTES:
            raise ShareUnavailable("WECHAT_SHARE_UPSTREAM_UNAVAILABLE")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ShareUnavailable("WECHAT_SHARE_UPSTREAM_INVALID")
        return data
    finally:
        connection.close()


def _credential(data, name):
    value, lifetime = data.get(name), data.get("expires_in")
    if (data.get("errcode", 0) != 0 or type(value) is not str
            or not 8 <= len(value) <= 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in value)
            or type(lifetime) is not int or not 120 <= lifetime <= 7200):
        raise ShareUnavailable("WECHAT_SHARE_UPSTREAM_INVALID")
    return value, lifetime - 60


class ShareService:
    def __init__(self, *, transport=None, clock=None, wall_clock=None, nonce=None):
        self._transport = transport or _request_json
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._nonce = nonce or (lambda: secrets.token_hex(16))
        self._lock = threading.Lock()
        self._refresh = threading.Lock()
        self._identity = None
        self._token = self._ticket = None
        self._cooldown = 0
        self._buckets = {}
        self._global_window = -1
        self._global_count = 0

    def _select(self, config):
        if self._identity != config.identity:
            self._identity = config.identity
            self._token = self._ticket = None
            self._cooldown = 0

    def _admit(self, client_key, now):
        window = int(now // 60)
        if self._global_window != window:
            self._global_window, self._global_count = window, 0
            self._buckets = {}
        if self._global_count >= 600:
            raise ShareRateLimited("WECHAT_SHARE_RATE_LIMITED")
        key = hashlib.sha256(str(client_key)[:200].encode()).digest()
        if key not in self._buckets and len(self._buckets) >= 1024:
            raise ShareRateLimited("WECHAT_SHARE_RATE_LIMITED")
        if self._buckets.get(key, 0) >= 60:
            raise ShareRateLimited("WECHAT_SHARE_RATE_LIMITED")
        self._global_count += 1
        self._buckets[key] = self._buckets.get(key, 0) + 1

    def _ticket_for(self, config):
        with self._lock:
            self._select(config)
            now = self._clock()
            if self._ticket and self._ticket[1] > now:
                return self._ticket[0]
            if self._cooldown > now:
                raise ShareUnavailable("WECHAT_SHARE_COOLDOWN")
        # Concurrent misses never queue multiple provider refreshes or retries.
        if not self._refresh.acquire(blocking=False):
            raise ShareUnavailable("WECHAT_SHARE_REFRESH_IN_PROGRESS", retry_after=2)
        try:
            with self._lock:
                self._select(config)
                now = self._clock()
                if self._ticket and self._ticket[1] > now:
                    return self._ticket[0]
                if self._cooldown > now:
                    raise ShareUnavailable("WECHAT_SHARE_COOLDOWN")
                token = self._token[0] if self._token and self._token[1] > now else None
            if token is None:
                response = self._transport("POST", _STABLE_PATH, {
                    "grant_type": "client_credential", "appid": config.app_id,
                    "secret": config.app_secret, "force_refresh": False})
                token, lifetime = _credential(response, "access_token")
                with self._lock:
                    if self._identity != config.identity:
                        raise ShareUnavailable("WECHAT_SHARE_CONFIGURATION_CHANGED")
                    self._token = (token, self._clock() + lifetime)
            response = self._transport("GET", _TICKET_PATH + "?" + urlencode({
                "access_token": token, "type": "jsapi"}), None)
            ticket, lifetime = _credential(response, "ticket")
            with self._lock:
                if self._identity != config.identity:
                    raise ShareUnavailable("WECHAT_SHARE_CONFIGURATION_CHANGED")
                self._ticket = (ticket, self._clock() + lifetime)
            return ticket
        except Exception:
            with self._lock:
                if self._identity == config.identity:
                    self._cooldown = self._clock() + COOLDOWN_SECONDS
            # Never expose request paths, credentials, provider body or exception.
            raise ShareUnavailable("WECHAT_SHARE_PROVIDER_UNAVAILABLE") from None
        finally:
            self._refresh.release()

    def share_config(self, url, *, client_key="", config=None):
        url = signing_url(url)
        config = config or configuration()
        with self._lock:
            self._admit(client_key, self._clock())
        ticket = self._ticket_for(config)
        timestamp, nonce = int(self._wall_clock()), self._nonce()
        return {"enabled": True, "appId": config.app_id, "timestamp": timestamp,
                "nonceStr": nonce, "signature": signature(ticket, nonce, timestamp, url),
                "jsApiList": list(JS_API_LIST)}


_service = ShareService()


def share_config(url, *, client_key=""):
    return _service.share_config(url, client_key=client_key)
