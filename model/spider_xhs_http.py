"""Bounded, read-only Spider_XHS direct HTTP adapter.

Only the explicitly listed discovery/detail operations are exposed.  The
adapter has no write, login, proxy, challenge-bypass, or browser capability.
Production callers must opt in with the exact adapter name and may suspend all
outbound XHS traffic with ``NOTEAI_XHS_COLLECTION_SUSPENDED``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

import runtime_settings


ADAPTER_NAME = "spider_xhs_http"
BASE_URL = "https://edith.xiaohongshu.com"
REQUEST_HOST = "edith.xiaohongshu.com"
MAX_PAGES = 3
MAX_ITEMS = 60
MAX_QUERY_LENGTH = 100
REQUEST_TIMEOUT_SECONDS = 20.0

VENDOR_DIR = Path(__file__).parent / "vendor" / "spider_xhs"
SIGNER_WRAPPER = VENDOR_DIR / "signer.js"
PINNED_ASSET_SHA256 = {
    "xhs_main_260411.js": "723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d",
    "xhs_rap.js": "e79fe1c79c97a73fbf5fdb6420af114ff591902aa60b436ac4b803a99b806d2e",
}
_NOTE_ID_RE = re.compile(r"^[A-Za-z0-9]{8,64}$")
_EXPLICIT_COLLECTION_UNLOCK_VALUES = frozenset({"0", "false", "off", "no"})
_EXPLICIT_COLLECTION_SUSPEND_VALUES = frozenset({"1", "true", "yes", "on"})
_AUTH_COOKIE_NAMES = frozenset({"web_session", "id_token"})
_ALLOWED_RESPONSE_KEYS = frozenset({"xs", "xt", "xs_common", "x_rap_param"})
_ALLOWED_ENDPOINTS = frozenset({
    ("POST", "/api/sns/web/v1/homefeed"),
    ("GET", "/api/sns/web/v1/search/recommend"),
    ("POST", "/api/sns/web/v1/search/notes"),
    ("POST", "/api/sns/web/v1/feed"),
})
_LEGACY_BROWSER_RUNTIME_ROLES = frozenset({"local", "legacy"})


class XHSAdapterError(RuntimeError):
    """Secret-free, stable adapter failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Signer(Protocol):
    def sign(
        self,
        *,
        api: str,
        data: dict[str, Any] | str,
        a1: str,
        method: str,
        needs_rap: bool,
    ) -> dict[str, str]: ...


def collection_suspended() -> bool:
    """Fail closed unless collection is explicitly unlocked.

    Missing, empty and unknown values are intentionally treated as suspended.
    This protects a production xhs-http role from becoming active when an
    environment variable is omitted or misspelled.
    """
    value = os.environ.get("NOTEAI_XHS_COLLECTION_SUSPENDED", "").strip().lower()
    return value not in _EXPLICIT_COLLECTION_UNLOCK_VALUES


def collection_route_suspended(route: str) -> bool:
    """Apply the operator stop to direct and explicit legacy routes safely."""
    if route == "direct":
        return collection_suspended()
    if route == "legacy-browser":
        value = os.environ.get("NOTEAI_XHS_COLLECTION_SUSPENDED")
        return bool(
            value is not None
            and value.strip().lower() in _EXPLICIT_COLLECTION_SUSPEND_VALUES
        )
    return True


def _assert_adapter_selected() -> None:
    if os.environ.get("NOTEAI_XHS_ACQUISITION_ADAPTER", "").strip() != ADAPTER_NAME:
        raise XHSAdapterError("adapter_not_selected")


def runtime_role_allowed() -> bool:
    """Only the isolated xhs-http role may perform direct XHS requests."""
    return os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() == "xhs-http"


def collection_route(
    adapter_name: str | None = None,
    runtime_role: str | None = None,
) -> str:
    """Select a safe collection route or fail closed with a fixed code."""
    adapter = (
        os.environ.get("NOTEAI_XHS_ACQUISITION_ADAPTER", "").strip()
        if adapter_name is None else str(adapter_name).strip()
    )
    role = (
        os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip()
        if runtime_role is None else str(runtime_role).strip()
    )
    if role == "xhs-http":
        if adapter == ADAPTER_NAME:
            return "direct"
        raise XHSAdapterError("adapter_not_selected")
    if role in {"api", "admin"}:
        raise XHSAdapterError("runtime_role_not_allowed")
    if adapter:
        raise XHSAdapterError(
            "runtime_role_not_allowed" if adapter == ADAPTER_NAME else "adapter_not_selected"
        )
    if role in _LEGACY_BROWSER_RUNTIME_ROLES:
        return "legacy-browser"
    raise XHSAdapterError("runtime_role_not_allowed")


def _assert_runtime_role_allowed() -> None:
    if not runtime_role_allowed():
        raise XHSAdapterError("runtime_role_not_allowed")


def _assert_collection_allowed() -> None:
    if collection_suspended():
        raise XHSAdapterError("collection_suspended")
    try:
        import xhs_acquisition

        if xhs_acquisition.collection_safety_status().get("session_blocked"):
            raise XHSAdapterError("server_session_logged_out")
    except XHSAdapterError:
        raise
    except Exception as exc:
        # A broken safety-state read must never silently permit an XHS call.
        raise XHSAdapterError("collection_safety_unavailable") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_pinned_signer_assets() -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, expected in PINNED_ASSET_SHA256.items():
        path = VENDOR_DIR / name
        if not path.is_file():
            raise XHSAdapterError("signer_asset_missing")
        value = _sha256(path)
        if value != expected:
            raise XHSAdapterError("signer_asset_integrity_failed")
        actual[name] = value
    if not SIGNER_WRAPPER.is_file():
        raise XHSAdapterError("signer_wrapper_missing")
    return actual


@dataclass(frozen=True)
class SessionCredentials:
    cookie_header: str
    a1: str
    cookie_count: int
    auth_cookie_present: bool
    auth_cookie_expired: bool

    @classmethod
    def from_records(cls, records: Any) -> "SessionCredentials":
        cookies = records if isinstance(records, list) else []
        safe_pairs: dict[str, str] = {}
        saw_matching_auth = False
        auth_present = False
        a1 = ""
        now = time.time()
        for item in cookies:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "")
            if not name or not value or any(char in name + value for char in "\r\n;"):
                continue
            domain = str(item.get("domain") or "").strip().lower().lstrip(".")
            if domain and not (
                REQUEST_HOST == domain or REQUEST_HOST.endswith("." + domain)
            ):
                continue
            try:
                expires = float(item.get("expires") or 0)
            except (TypeError, ValueError):
                expires = 0
            if name in _AUTH_COOKIE_NAMES:
                saw_matching_auth = True
            if expires > 0 and expires <= now:
                continue
            safe_pairs[name] = value
            if name == "a1":
                a1 = value
            if name in _AUTH_COOKIE_NAMES:
                auth_present = True
        return cls(
            cookie_header="; ".join(f"{name}={value}" for name, value in safe_pairs.items()),
            a1=a1,
            cookie_count=len(safe_pairs),
            auth_cookie_present=auth_present,
            auth_cookie_expired=bool(saw_matching_auth and not auth_present),
        )

    @classmethod
    def from_runtime_settings(cls) -> "SessionCredentials":
        return cls.from_records(runtime_settings.get_json("xhs_cookies", []))

    def public_health(self) -> dict[str, Any]:
        configured = bool(self.cookie_count and self.a1 and self.auth_cookie_present)
        return {
            "adapter": ADAPTER_NAME,
            "configured": configured,
            "cookie_count": self.cookie_count,
            "a1_present": bool(self.a1),
            "auth_cookie_present": self.auth_cookie_present,
            "auth_cookie_expired": self.auth_cookie_expired,
            "status": "ready" if configured and not self.auth_cookie_expired else "login_required",
        }


class NodeSigner:
    """Invoke the pinned signer over stdin/stdout; credentials never use argv/env."""

    def __init__(self, *, node_binary: str = "node", timeout: float = 10.0):
        self.node_binary = node_binary
        self.timeout = timeout
        verify_pinned_signer_assets()

    def sign(
        self,
        *,
        api: str,
        data: dict[str, Any] | str,
        a1: str,
        method: str,
        needs_rap: bool,
    ) -> dict[str, str]:
        payload = json.dumps(
            {"api": api, "data": data, "a1": a1, "method": method, "needs_rap": needs_rap},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "NODE_PATH": os.environ.get("NOTEAI_XHS_NODE_PATH", "/opt/noteai/xhs-node/node_modules"),
        }
        try:
            result = subprocess.run(
                [self.node_binary, str(SIGNER_WRAPPER)],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=self.timeout,
                env=env,
                cwd=str(VENDOR_DIR),
            )
        except Exception as exc:
            raise XHSAdapterError("signer_unavailable") from exc
        if result.returncode != 0 or len(result.stdout) > 64 * 1024:
            raise XHSAdapterError("signer_failed")
        try:
            parsed = json.loads(result.stdout.decode("utf-8"))
        except Exception as exc:
            raise XHSAdapterError("signer_invalid_response") from exc
        if not isinstance(parsed, dict) or set(parsed) - _ALLOWED_RESPONSE_KEYS:
            raise XHSAdapterError("signer_invalid_response")
        required = {"xs", "xt", "xs_common"}
        if needs_rap:
            required.add("x_rap_param")
        if any(not isinstance(parsed.get(key), str) or not parsed[key] for key in required):
            raise XHSAdapterError("signer_invalid_response")
        return {key: str(value) for key, value in parsed.items()}


def _compact_json(data: dict[str, Any] | str) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _message_markers(payload: dict[str, Any]) -> str:
    values = [payload.get(key) for key in ("msg", "message", "code")]
    data = payload.get("data")
    if isinstance(data, dict):
        values.extend(data.get(key) for key in ("msg", "message", "code"))
    return " ".join(str(value).lower() for value in values if value is not None)[:500]


def _validate_response(status_code: int, payload: Any) -> dict[str, Any]:
    if status_code == 429:
        raise XHSAdapterError("cooldown")
    if status_code in {401, 403}:
        raise XHSAdapterError("login_or_challenge_required")
    if status_code < 200 or status_code >= 300:
        raise XHSAdapterError("remote_http_error")
    if not isinstance(payload, dict):
        raise XHSAdapterError("remote_schema_error")
    markers = _message_markers(payload)
    if any(marker in markers for marker in ("captcha", "challenge", "risk", "verify", "验证", "风控")):
        raise XHSAdapterError("challenge")
    if any(marker in markers for marker in ("login", "登录", "未登陆", "未登录")):
        raise XHSAdapterError("login_required")
    if any(marker in markers for marker in ("频繁", "too many", "cooldown", "rate limit")):
        raise XHSAdapterError("cooldown")
    if payload.get("success") is False:
        raise XHSAdapterError("remote_business_error")
    code = payload.get("code")
    if code not in (None, 0, "0", "", "ok", "success"):
        raise XHSAdapterError("remote_business_error")
    return payload


class SpiderXHSHTTPAdapter:
    """Read-only allowlisted XHS Web API client."""

    def __init__(
        self,
        *,
        credentials: SessionCredentials | None = None,
        signer: Signer | None = None,
        client: httpx.Client | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ):
        self.credentials = credentials or SessionCredentials.from_runtime_settings()
        self.signer = signer or NodeSigner()
        self._client = client
        self.timeout = min(max(float(timeout), 1.0), 30.0)

    def session_health(self) -> dict[str, Any]:
        return self.credentials.public_health()

    def _assert_ready(self) -> None:
        _assert_adapter_selected()
        _assert_runtime_role_allowed()
        _assert_collection_allowed()
        health = self.session_health()
        if not health["configured"] or health["auth_cookie_expired"]:
            raise XHSAdapterError("login_required")

    def _request(
        self,
        method: str,
        api: str,
        *,
        data: dict[str, Any] | str = "",
        needs_rap: bool = False,
    ) -> dict[str, Any]:
        self._assert_ready()
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise XHSAdapterError("operation_not_allowed")
        endpoint = api.partition("?")[0]
        if (method, endpoint) not in _ALLOWED_ENDPOINTS:
            raise XHSAdapterError("operation_not_allowed")
        body = _compact_json(data) if data else ""
        signed = self.signer.sign(
            api=api,
            data=data,
            a1=self.credentials.a1,
            method=method,
            needs_rap=needs_rap,
        )
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://www.xiaohongshu.com",
            "referer": "https://www.xiaohongshu.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
            "cookie": self.credentials.cookie_header,
            "x-s": signed["xs"],
            "x-t": signed["xt"],
            "x-s-common": signed["xs_common"],
            "x-b3-traceid": secrets.token_hex(8),
            "x-xray-traceid": secrets.token_hex(16),
        }
        if needs_rap:
            headers["x-rap-param"] = signed["x_rap_param"]
        if endpoint == "/api/sns/web/v1/feed":
            headers["xy-direction"] = "13"
        client = self._client or httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        )
        owns_client = self._client is None
        try:
            response = client.request(
                method,
                BASE_URL + api,
                headers=headers,
                content=body.encode("utf-8") if body else None,
            )
            try:
                payload = response.json()
            except Exception as exc:
                raise XHSAdapterError("remote_non_json") from exc
            return _validate_response(response.status_code, payload)
        except XHSAdapterError:
            raise
        except httpx.HTTPError as exc:
            raise XHSAdapterError("network_error") from exc
        finally:
            if owns_client:
                client.close()

    def homefeed(
        self,
        *,
        category: str = "homefeed_recommend",
        max_pages: int = 1,
        max_items: int = 20,
    ) -> dict[str, Any]:
        pages = min(max(int(max_pages), 1), MAX_PAGES)
        limit = min(max(int(max_items), 1), MAX_ITEMS)
        cursor = ""
        seen_cursors: set[str] = set()
        items: list[dict[str, Any]] = []
        note_index = 0
        for page_index in range(pages):
            data = {
                "cursor_score": cursor,
                "num": 20,
                "refresh_type": 1 if page_index == 0 else 3,
                "note_index": note_index,
                "unread_begin_note_id": "",
                "unread_end_note_id": "",
                "unread_note_count": 0,
                "category": str(category)[:100],
                "search_key": "",
                "need_num": min(20, limit - len(items)),
                "image_formats": ["jpg", "webp", "avif"],
                "need_filter_image": False,
            }
            payload = self._request("POST", "/api/sns/web/v1/homefeed", data=data)
            response_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            page_items = response_data.get("items") if isinstance(response_data.get("items"), list) else []
            items.extend(item for item in page_items if isinstance(item, dict))
            next_cursor = str(response_data.get("cursor_score") or "")
            if len(items) >= limit or not page_items or not next_cursor or next_cursor in seen_cursors:
                cursor = next_cursor
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            note_index += len(page_items)
        return {"items": items[:limit], "cursor": cursor, "pages": page_index + 1}

    def search_recommend(self, keyword: str) -> dict[str, Any]:
        keyword = str(keyword).strip()
        if not keyword or len(keyword) > MAX_QUERY_LENGTH:
            raise XHSAdapterError("invalid_query")
        api = "/api/sns/web/v1/search/recommend?" + urlencode({"keyword": keyword})
        return self._request("GET", api)

    def search_notes(
        self,
        keyword: str,
        *,
        max_pages: int = 1,
        max_items: int = 20,
    ) -> dict[str, Any]:
        keyword = str(keyword).strip()
        if not keyword or len(keyword) > MAX_QUERY_LENGTH:
            raise XHSAdapterError("invalid_query")
        pages = min(max(int(max_pages), 1), MAX_PAGES)
        limit = min(max(int(max_items), 1), MAX_ITEMS)
        search_id = f"{int(time.time() * 1000):x}{secrets.token_hex(8)}"
        items: list[dict[str, Any]] = []
        has_more = False
        for page in range(1, pages + 1):
            data = {
                "keyword": keyword,
                "page": page,
                "page_size": min(20, limit - len(items)),
                "search_id": search_id,
                "sort": "general",
                "note_type": 0,
                "ext_flags": [],
                "filters": [
                    {"tags": ["general"], "type": "sort_type"},
                    {"tags": ["不限"], "type": "filter_note_type"},
                    {"tags": ["不限"], "type": "filter_note_time"},
                    {"tags": ["不限"], "type": "filter_note_range"},
                    {"tags": ["不限"], "type": "filter_pos_distance"},
                ],
                "geo": "",
                "image_formats": ["jpg", "webp", "avif"],
            }
            payload = self._request(
                "POST", "/api/sns/web/v1/search/notes", data=data, needs_rap=True
            )
            response_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            page_items = response_data.get("items") if isinstance(response_data.get("items"), list) else []
            items.extend(item for item in page_items if isinstance(item, dict))
            has_more = bool(response_data.get("has_more"))
            if len(items) >= limit or not page_items or not has_more:
                break
        return {"items": items[:limit], "has_more": has_more, "pages": page}

    def note_detail(self, note_url: str) -> dict[str, Any]:
        parsed = urlparse(str(note_url).strip())
        if parsed.scheme != "https" or parsed.hostname not in {"www.xiaohongshu.com", "xiaohongshu.com"}:
            raise XHSAdapterError("invalid_note_url")
        parts = [part for part in parsed.path.split("/") if part]
        valid_path = (
            len(parts) == 2 and parts[0] == "explore"
        ) or (
            len(parts) == 3 and parts[:2] == ["discovery", "item"]
        )
        if not valid_path:
            raise XHSAdapterError("invalid_note_url")
        note_id = parts[-1]
        if not _NOTE_ID_RE.fullmatch(note_id):
            raise XHSAdapterError("invalid_note_url")
        query = parse_qs(parsed.query, keep_blank_values=False)
        xsec_source = str((query.get("xsec_source") or ["pc_search"])[-1])[:40]
        xsec_token = str((query.get("xsec_token") or [""])[-1])[:512]
        data = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        return self._request("POST", "/api/sns/web/v1/feed", data=data, needs_rap=True)


def session_health() -> dict[str, Any]:
    """Return local, secret-free session health without creating a network client."""
    return SessionCredentials.from_runtime_settings().public_health()
