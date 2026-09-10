"""Bounded PC v5 cookie initialization and owned-note read path.

Only DSL, existing-session user/me and feed are reachable. No login/profile,
credential replacement, proxies, redirects or automatic retry. State is per task.
"""
from __future__ import annotations
import json
import base64
import os
import re
import time
from datetime import datetime, timezone

import httpx
from security_redaction import xhs_response_diagnostics
from vendor.spider_xhs.v5 import headers as wire
from vendor.spider_xhs.v5 import runtime
from vendor.spider_xhs.v5.state import PcDeviceProfile
from spider_xhs_http import XHSAdapterError, _validate_response

DSL_URL = "https://as.xiaohongshu.com/api/sec/v1/ds?appId=xhs-pc-web"
SESSION_API = "/api/sns/web/v2/user/me"
DETAIL_API = "/api/sns/web/v1/feed"
BASE = "https://edith.xiaohongshu.com"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_DSL = re.compile(r"function\s+getdss\s*\(\s*\)\s*\{\s*return\s+['\"]([0-9]{13})['\"]")


def session_signing_storage(raw):
    """Accept only optional existing PC signing state, never synthesize it."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if (len(raw) > 4096 or not isinstance(value, dict) or set(value) != {"xhs-pc-web"}
                or not isinstance(value["xhs-pc-web"], str)
                or not 32 <= len(base64.b64decode(value["xhs-pc-web"], validate=True)) <= 1024):
            raise ValueError()
        return {"webSsk": value}
    except (ValueError, TypeError):
        raise XHSAdapterError("invalid_session_signing_state") from None


class CurlClient:
    """Pinned upstream transport profile with explicit bounded response handling."""
    def __init__(self):
        from curl_cffi import requests
        self.session = requests.Session(impersonate="chrome146", default_headers=False,
                                        discard_cookies=True, http_version="v2tls", trust_env=False)

    def request(self, method, url, *, headers, content=None):
        from curl_cffi.curl import CURL_WRITEFUNC_ERROR
        chunks = bytearray()
        def collect(chunk):
            if len(chunks) + len(chunk) > MAX_RESPONSE_BYTES:
                return CURL_WRITEFUNC_ERROR  # curl_cffi otherwise ignores a short write.
            chunks.extend(chunk)
            return len(chunk)
        result = self.session.request(
            method, url, headers=headers, data=content, allow_redirects=False,
            timeout=20, content_callback=collect, proxies={"all": ""},
            accept_encoding=wire.DEFAULT_ACCEPT_ENCODING,
        )
        # Only safe status/body for in-memory parsing crosses this boundary.
        return httpx.Response(result.status_code, content=bytes(chunks))

    def close(self):
        self.session.close()


class V5Detail:
    def __init__(self, *, credentials, assert_ready, client=None, observe=None):
        runtime.verify_assets()
        self.profile = PcDeviceProfile(cookies=credentials.cookie_header,
            local_storage=session_signing_storage(os.environ.get("NOTEAI_XHS_WEB_SSK_JSON", "")))
        self.credentials = credentials
        self.assert_ready = assert_ready
        self.client = client
        self.observe = observe or self._stdout_event
        self.count = 0
        self.dsl = None
        self.dsl_fetched_at = None
        self.user_id = None
        self.last_response_diagnostics = {}
        self.last_owned_metrics = None

    @staticmethod
    def _stdout_event(value):
        print(json.dumps({"xhs_http": value}, sort_keys=True), flush=True)

    def _send(self, kind, method, url, headers, data=""):
        self.assert_ready()
        expected = {"dsl": ("GET", DSL_URL), "session": ("GET", BASE + SESSION_API),
                    "detail": ("POST", BASE + DETAIL_API)}
        if expected.get(kind) != (method, url) or self.count >= 3:
            raise XHSAdapterError("operation_not_allowed")
        self.count += 1
        sequence = self.count
        self.last_response_diagnostics = {}
        body = (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                if isinstance(data, dict) else data).encode()
        self.observe({"phase": "dispatch", "request_kind": kind, "sequence": sequence,
                      "at": datetime.now(timezone.utc).isoformat(), "request_body_bytes": len(body)})
        try:
            response = self.client.request(method, url, headers=headers, content=body or None)
        except Exception:
            self.observe({"phase": "unknown", "request_kind": kind, "sequence": sequence,
                          "at": datetime.now(timezone.utc).isoformat()})
            raise XHSAdapterError("network_error") from None
        raw = response.content
        try:
            payload = response.json()
        except Exception:
            payload = None
        meta = xhs_response_diagnostics(response.status_code, payload, json_decoded=payload is not None)
        self.last_response_diagnostics = meta
        self.observe({"phase": "response", "request_kind": kind, "sequence": sequence,
                      "at": datetime.now(timezone.utc).isoformat(), "response_bytes": len(raw),
                      "response_diagnostics": meta})
        if len(raw) > MAX_RESPONSE_BYTES:
            raise XHSAdapterError("remote_response_too_large", diagnostics=meta)
        if kind == "dsl" and 200 <= response.status_code < 300:
            match = _DSL.search(raw.decode("utf-8", errors="replace"))
            if match:
                return match.group(1)
            raise XHSAdapterError("remote_schema_error", diagnostics=meta)
        try:
            if payload is None:
                if response.status_code in {401, 403, 429} or not 200 <= response.status_code < 300:
                    _validate_response(response.status_code, {})
                raise XHSAdapterError("remote_non_json", diagnostics=meta)
            return _validate_response(response.status_code, payload)
        except XHSAdapterError as exc:
            exc.diagnostics = meta
            raise

    def _headers(self, api, data):
        if not self.dsl or time.monotonic() - self.dsl_fetched_at >= 300:
            raise XHSAdapterError("signing_context_expired")
        self.assert_ready()
        try:
            signed, context = runtime.sign(self.profile, api, data, self.dsl)
            headers = wire.get_request_headers_template(context, method="GET" if data == "" else "POST",
                                                       include_client_hints=False, has_body=data != "")
            headers.update({"x-s": signed["xs"], "x-t": signed["xt"],
                            "x-s-common": signed["xs_common"], "x-b3-traceid": wire.generate_x_b3_traceid()})
            if api == DETAIL_API:
                if not self.user_id:
                    raise XHSAdapterError("session_identity_unproven")
                headers["xy-direction"] = str(wire.generate_xy_direction(self.user_id))
                headers["x-rap-param"] = signed["x_rap_param"]
            else:
                headers.update({"cache-control": "no-cache", "pragma": "no-cache"})
            return wire.build_pc_business_headers(headers, self.profile.cookie_map, api=api,
                                                   method="GET" if data == "" else "POST")
        except XHSAdapterError:
            raise
        except Exception:
            raise XHSAdapterError("signer_failed") from None

    def read(self, data):
        self.assert_ready()
        if not self.profile.cookie_map.get("web_session"):
            raise XHSAdapterError("login_required")
        owned_client = self.client is None
        if owned_client:
            self.client = CurlClient()
        try:
            if self.count:
                raise XHSAdapterError("operation_not_allowed")  # One finite read chain per instance.
            self.dsl = self._send("dsl", "GET", DSL_URL, {
                "user-agent": wire.PC_CURRENT_BROWSER_UA, "referer": "https://www.xiaohongshu.com/",
                "accept": "*/*",
            })
            self.dsl_fetched_at = time.monotonic()
            session = self._send("session", "GET", BASE + SESSION_API, self._headers(SESSION_API, ""))
            user_id = session.get("data", {}).get("user_id") if isinstance(session.get("data"), dict) else None
            if not isinstance(user_id, str) or not re.fullmatch(r"[A-Za-z0-9]{8,64}", user_id):
                raise XHSAdapterError("session_identity_unproven", diagnostics=self.last_response_diagnostics)
            self.user_id = user_id
            payload = self._send("detail", "POST", BASE + DETAIL_API, self._headers(DETAIL_API, data), data)
            items = payload.get("data", {}).get("items") if isinstance(payload.get("data"), dict) else None
            if not isinstance(items, list):
                raise XHSAdapterError("remote_schema_error", diagnostics=self.last_response_diagnostics)
            matches = [item for item in items if isinstance(item, dict) and
                       (item.get("id") == data["source_note_id"] or
                        isinstance(item.get("note_card"), dict) and item["note_card"].get("note_id") == data["source_note_id"])]
            if len(matches) != 1:
                raise XHSAdapterError("remote_schema_error", diagnostics=self.last_response_diagnostics)
            card = matches[0].get("note_card", {})
            if (isinstance(card, dict) and matches[0].get("id") is not None and
                    card.get("note_id") is not None and matches[0]["id"] != card["note_id"]):
                raise XHSAdapterError("remote_schema_error", diagnostics=self.last_response_diagnostics)
            author = card.get("user", {}) if isinstance(card, dict) else {}
            if not isinstance(author, dict) or author.get("user_id") != self.user_id:
                raise XHSAdapterError("owned_note_identity_unproven", diagnostics=self.last_response_diagnostics)
            metrics = card.get("interact_info", {})
            normalized = {}
            for local, remote in (("likes", "liked_count"), ("saves", "collected_count"), ("comments", "comment_count")):
                value = metrics.get(remote) if isinstance(metrics, dict) else None
                if type(value) is int:
                    number = value
                elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value):
                    number = int(value)
                else:
                    raise XHSAdapterError("invalid_provider_metrics", diagnostics=self.last_response_diagnostics)
                if not 0 <= number <= 2147483647:
                    raise XHSAdapterError("invalid_provider_metrics", diagnostics=self.last_response_diagnostics)
                normalized[local] = number
            self.last_owned_metrics = normalized
            return payload
        finally:
            if owned_client:
                self.client.close()
