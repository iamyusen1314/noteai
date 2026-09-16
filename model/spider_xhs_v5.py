"""Bounded PC v5 cookie initialization and owned-note read path.

Only DSL, existing-session user/me and feed are reachable. No login/profile,
credential replacement, proxies, redirects or automatic retry. State is per task.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
from security_redaction import sanitize_xhs_response_diagnostics, xhs_response_diagnostics
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


def trends_recommendation_keywords(payload):
    """Read direct suggestion entries only; never treat sibling metadata as words."""
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("sug_items") if isinstance(data, dict) else None
    found = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        for key in ("keyword", "word", "search_word", "name", "text", "title"):
            value = item.get(key)
            if isinstance(value, str) and len(value.strip()) >= 2:
                found.append(value.strip())
                break
    return found


def session_signing_storage(raw):
    """Accept only optional existing PC signing state, never synthesize it."""
    try:
        return runtime.session_signing_storage(raw)
    except RuntimeError:
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
        if response.status_code in {461, 471}:
            # A safety stop, not a claim about the cause or a CAPTCHA diagnosis.
            raise XHSAdapterError("access_restricted", diagnostics=meta)
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


TRENDS_SEARCH_BASE = "https://so.xiaohongshu.com"
TRENDS_HOME_API = "/api/sns/web/v1/homefeed"
TRENDS_RECOMMEND_API = "/api/sns/web/v1/search/recommend"
TRENDS_SEARCH_API = "/api/sns/web/v2/search/notes"


def trends_budget(raw):
    """Explicit physical-HTTP budget; original collection admissions stay <=34."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        if (not isinstance(value, dict) or set(value) != {"initialization", "collection", "total"}
                or any(type(n) is not int for n in value.values())
                or value["initialization"] != 2 or not 1 <= value["collection"] <= 34
                or value["total"] != value["initialization"] + value["collection"]):
            raise ValueError()
        return dict(value)
    except (ValueError, TypeError):
        raise XHSAdapterError("trends_v5_budget_required") from None


def trends_search_id():
    """Same base36 timestamp/random shape as upstream7077c88 params.py148."""
    import secrets
    number = (int(time.time() * 1000) << 64) + secrets.randbelow(0x7ffffffe) + 1
    result = ""
    while number:
        number, remainder = divmod(number, 36)
        result = "0123456789abcdefghijklmnopqrstuvwxyz"[remainder] + result
    return result


def _trends_sign(profile, api, data, dsl):
    """Separate stdin-only bridge; the proven Item34 bridge/assets stay unchanged."""
    context = profile.next_sign_context(api)
    payload = {key: context[key] for key in (
        "tier", "now", "version", "loadts", "seq", "envConst", "envFpTail",
        "webBuild", "signVersion", "appId", "platform",
    )}
    payload.update({"api": api, "data": data, "a1": profile.cookie_map["a1"],
                    "cookie": profile.document_cookie, "b1": profile.current_b1(context["now"]),
                    "dslPair": profile.dsl_pair(dsl, timestamp_ms=context["now"])})
    if "webSsk" in context:
        payload["webSsk"] = context["webSsk"]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > 65536:
        raise XHSAdapterError("signer_input_limit")
    try:
        result = subprocess.run(["node", str(runtime.ROOT / "trends_bridge.js")], input=raw,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
                                env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
                                cwd=str(runtime.ROOT))
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError()
        signed = json.loads(result.stdout)
        expected = {"xs", "xt", "xs_common"}
        if api in {TRENDS_HOME_API, TRENDS_SEARCH_API}:
            expected.add("x_rap_param")
        if (not isinstance(signed, dict) or set(signed) != expected
                or any(not isinstance(v, str) or not v for v in signed.values())):
            raise ValueError()
        return signed, context
    except Exception:
        raise XHSAdapterError("signer_failed") from None


class V5Trends(V5Detail):
    """One finite Trends session: two init HTTPs, then <=34 admitted reads.

    Any failure/UNKNOWN latches this instance closed. No rebootstrap, login,
    session refresh, endpoint fallback, or automatic retry is performed.
    """
    def __init__(self, *, budget, admit, complete, **kwargs):
        self.budget = trends_budget(budget)
        if not callable(admit) or not callable(complete):
            raise XHSAdapterError("trends_provider_admission_failed")
        super().__init__(**kwargs)
        self.admit, self.complete = admit, complete
        self.initialization_count = self.collection_count = 0
        self.stopped = False
        self.owned_client = self.client is None

    def close(self):
        if self.owned_client and self.client is not None:
            self.client.close()
            self.client = None
        self.stopped = True

    def _headers(self, api, data):
        if api == SESSION_API:
            return super()._headers(api, data)
        if not self.dsl or time.monotonic() - self.dsl_fetched_at >= 300:
            raise XHSAdapterError("signing_context_expired")
        self.assert_ready()
        try:
            signed, context = _trends_sign(self.profile, api, data, self.dsl)
            method = "GET" if data == "" else "POST"
            headers = wire.get_request_headers_template(context, method=method,
                include_client_hints=False, has_body=data != "")
            headers.update({"x-s": signed["xs"], "x-t": signed["xt"],
                            "x-s-common": signed["xs_common"], "x-b3-traceid": wire.generate_x_b3_traceid()})
            if api == TRENDS_HOME_API:
                if not self.user_id:
                    raise XHSAdapterError("session_identity_unproven")
                headers["xy-direction"] = str(wire.generate_xy_direction(self.user_id))
            if "x_rap_param" in signed:
                headers["x-rap-param"] = signed["x_rap_param"]
            return wire.build_pc_business_headers(headers, self.profile.cookie_map, api=api, method=method)
        except XHSAdapterError:
            raise
        except Exception:
            raise XHSAdapterError("signer_failed") from None

    def _send(self, kind, method, url, headers, data=""):
        self.assert_ready()
        allowed = {"dsl": ("GET", DSL_URL), "session": ("GET", BASE + SESSION_API),
                   "homefeed": ("POST", BASE + TRENDS_HOME_API),
                   "search_notes": ("POST", TRENDS_SEARCH_BASE + TRENDS_SEARCH_API)}
        if kind == "search_recommend":
            parsed = urlsplit(url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            valid = (method == "GET" and parsed.scheme == "https" and parsed.netloc == "edith.xiaohongshu.com"
                     and parsed.path == TRENDS_RECOMMEND_API and not parsed.fragment
                     and set(query) == {"keyword"} and len(query["keyword"]) == 1
                     and 0 < len(query["keyword"][0]) <= 100)
        else:
            valid = allowed.get(kind) == (method, url)
        init = kind in {"dsl", "session"}
        category = "initialization" if init else "collection"
        used = self.initialization_count if init else self.collection_count
        if self.stopped or not valid or used >= self.budget[category] or self.count >= self.budget["total"]:
            raise XHSAdapterError("operation_not_allowed")
        attempt = None
        if not init:
            try:
                attempt = self.admit(kind)
            except Exception:
                raise XHSAdapterError("trends_provider_admission_failed") from None
        self.count += 1
        if init:
            self.initialization_count += 1
        else:
            self.collection_count += 1
        sequence = self.count
        body = (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                if isinstance(data, dict) else data).encode()
        received = False
        finalized = False
        self.last_response_diagnostics = {}
        try:
            self.observe({"phase": "dispatch", "request_kind": kind, "sequence": sequence,
                          "at": datetime.now(timezone.utc).isoformat(), "request_body_bytes": len(body)})
            response = self.client.request(method, url, headers=headers, content=body or None)
            received = True
            raw = response.content
            try:
                payload = response.json()
            except Exception:
                payload = None
            meta = xhs_response_diagnostics(response.status_code, payload, json_decoded=payload is not None)
            if kind == "search_recommend" and isinstance(payload, dict):
                data = payload.get("data")
                items = data.get("sug_items") if isinstance(data, dict) else None
                if isinstance(items, list):
                    meta.update(recommendation_items_total=len(items),
                                recommendation_items_usable=len(trends_recommendation_keywords(payload)))
            self.last_response_diagnostics = meta
            self.observe({"phase": "response", "request_kind": kind, "sequence": sequence,
                          "at": datetime.now(timezone.utc).isoformat(), "response_bytes": len(raw),
                          "response_diagnostics": meta})
            if response.status_code in {461, 471}:
                raise XHSAdapterError("access_restricted", diagnostics=meta)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise XHSAdapterError("remote_response_too_large", diagnostics=meta)
            if kind == "dsl" and 200 <= response.status_code < 300:
                match = _DSL.search(raw.decode("utf-8", errors="replace"))
                if not match:
                    raise XHSAdapterError("remote_schema_error", diagnostics=meta)
                return match.group(1)
            if payload is None:
                if not 200 <= response.status_code < 300:
                    _validate_response(response.status_code, {})
                raise XHSAdapterError("remote_non_json", diagnostics=meta)
            code = meta.get("business_code")
            recommend_1000 = kind == "search_recommend" and (
                type(code) is int and code == 1000 or type(code) is str and code == "1000")
            try:
                result = _validate_response(response.status_code, payload)
            except XHSAdapterError as exc:
                # The pinned upstream recommend endpoint uses explicit success;
                # retain its observed 1000 code and check this endpoint's data.
                # HTTP, login, challenge and cooldown failures are never bypassed.
                if not (recommend_1000 and exc.code == "remote_business_error"):
                    raise
                result = payload
            # Trends may continue only on the same explicit business success
            # required by its terminal evidence; legacy Tracking stays unchanged.
            nested = meta.get("nested_business_code")
            if (meta.get("success_state") != "true"
                    or not (recommend_1000 or type(code) is int and code == 0 or type(code) is str and code == "0")
                    or meta.get("message_tags", []) != []
                    or "nested_business_code" in meta and not (
                        type(nested) is int and nested == 0 or type(nested) is str and nested == "0")):
                raise XHSAdapterError("remote_business_error", diagnostics=meta)
            if recommend_1000 and meta.get("recommendation_items_usable", 0) <= 0:
                raise XHSAdapterError("remote_schema_error", diagnostics=meta)
            if kind == "homefeed" and self.collection_count == 1:
                data = result.get("data")
                items = data.get("items") if isinstance(data, dict) else None
                cards = [item.get("note_card", item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
                if not any(isinstance(card, dict) and any(
                        isinstance(card.get(key), str) and card[key].strip()
                        for key in ("display_title", "title")) for card in cards):
                    # Empty/malformed first feed is insufficient data, not proof
                    # of an account freeze. Normal empty searches remain valid.
                    raise XHSAdapterError("remote_schema_error", diagnostics=meta)
            if attempt is not None:
                finalized = True  # Unknown finalization must never be attempted again.
                self.complete(attempt, outcome="succeeded")
            return result
        except Exception as exc:
            self.stopped = True
            if not received:
                self.observe({"phase": "unknown", "request_kind": kind, "sequence": sequence,
                              "at": datetime.now(timezone.utc).isoformat()})
            code = exc.code if isinstance(exc, XHSAdapterError) else "network_error"
            if attempt is not None and not finalized:
                try:
                    self.complete(attempt, outcome="failed" if received else "outcome_unknown", error_code=code)
                except Exception:
                    raise XHSAdapterError("trends_provider_finalize_failed",
                                          diagnostics=self.last_response_diagnostics) from None
            if finalized:
                raise XHSAdapterError("trends_provider_finalize_failed",
                                      diagnostics=self.last_response_diagnostics) from None
            if isinstance(exc, XHSAdapterError):
                if kind == "search_recommend":
                    exc.diagnostics = sanitize_xhs_response_diagnostics(
                        self.last_response_diagnostics, recommendations=True)
                raise
            raise XHSAdapterError("network_error", diagnostics=self.last_response_diagnostics) from None

    def request(self, method, api, data=""):
        endpoint = api.split("?", 1)[0]
        kinds = {TRENDS_HOME_API: "homefeed", TRENDS_RECOMMEND_API: "search_recommend",
                 TRENDS_SEARCH_API: "search_notes"}
        if self.stopped or endpoint not in kinds or not self.profile.cookie_map.get("web_session"):
            raise XHSAdapterError("operation_not_allowed")
        if (method, endpoint) not in {("POST", TRENDS_HOME_API), ("GET", TRENDS_RECOMMEND_API),
                                      ("POST", TRENDS_SEARCH_API)}:
            raise XHSAdapterError("operation_not_allowed")
        if endpoint == TRENDS_RECOMMEND_API:
            parsed = urlsplit(api)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if (parsed.scheme or parsed.netloc or parsed.fragment or set(query) != {"keyword"}
                    or len(query["keyword"]) != 1 or not 0 < len(query["keyword"][0]) <= 100):
                raise XHSAdapterError("operation_not_allowed")
        elif api != endpoint:
            raise XHSAdapterError("operation_not_allowed")
        stage = "preflight"
        try:
            self.assert_ready()
            if self.client is None:
                self.client = CurlClient()
            if self.user_id is None:
                if self.count:
                    raise XHSAdapterError("operation_not_allowed")
                stage = "dsl"
                self.dsl = self._send("dsl", "GET", DSL_URL, {
                    "user-agent": wire.PC_CURRENT_BROWSER_UA, "referer": "https://www.xiaohongshu.com/", "accept": "*/*"})
                self.dsl_fetched_at = time.monotonic()
                stage = "session"
                session = self._send("session", "GET", BASE + SESSION_API, self._headers(SESSION_API, ""))
                user_id = session.get("data", {}).get("user_id") if isinstance(session.get("data"), dict) else None
                if not isinstance(user_id, str) or not re.fullmatch(r"[A-Za-z0-9]{8,64}", user_id):
                    raise XHSAdapterError("session_identity_unproven", diagnostics=self.last_response_diagnostics)
                self.user_id = user_id
            base = TRENDS_SEARCH_BASE if endpoint == TRENDS_SEARCH_API else BASE
            stage = kinds[endpoint]
            return self._send(kinds[endpoint], method, base + api, self._headers(api, data), data)
        except Exception as exc:
            if isinstance(exc, XHSAdapterError):
                exc.stage = stage
            self.close()
            raise
