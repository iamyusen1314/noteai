"""Scoped public use of the existing product, credit ledger and model pipeline.

No provider payload, credentials or returned content is persisted here. Cumulative
reservations cover the maximum possible token bill, including an unknown result.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
import uuid

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

CONTRACT_VERSION = "free-product-2026-09-12"
BUDGET_ID = "website-free-product-20260912"
LIMIT_MILLI_CNY = 50000
# Official 2026-09-12 pricing: 262144 * CNY6.50/M + 32768 * CNY27/M
# = CNY2.588672. No cache discount; no refund of an uncertain reservation.
RESERVE_MILLI_CNY = 2590
MODEL = "kimi-k2.6"
ENDPOINT = "https://api.moonshot.cn/v1/chat/completions"

EXACT_ROUTES = frozenset({
    ("POST", "/auth/contracts/accept"),
    ("GET", "/billing/tiers"), ("GET", "/billing/plan"),
    ("GET", "/billing/usage"), ("GET", "/billing/credits"),
    ("GET", "/notes"), ("POST", "/notes"),
    ("GET", "/diagnoses"),
    ("GET", "/profile/growth"), ("GET", "/profile/memories"),
    ("GET", "/profile/achievements"),
    ("POST", "/analyze/stream"), ("POST", "/generate/stream"),
    ("POST", "/chat/start"), ("POST", "/chat/message"),
    ("POST", "/chat/select-plan"),
})
PAID_ROUTES = {"/analyze/stream", "/generate/stream", "/chat/message"}


def enabled() -> bool:
    return os.environ.get("NOTEAI_PUBLIC_PRODUCT", "0") == "1"


def allowed_route(method: str, path: str) -> bool:
    if (method, path) in EXACT_ROUTES:
        return True
    return method == "GET" and bool(re.fullmatch(
        r"/(?:notes|diagnoses)/(?:[0-9a-f]{32}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})(?:/versions)?", path
    ))


@dataclass
class Invocation:
    user_id: str
    request_id: str
    failure: str = ""
    model_config: dict | None = None
    prompts: object | None = None
    route: str = ""
    call_ids: set = field(default_factory=set)
    fact_observation: dict | None = None


_invocation = contextvars.ContextVar("public_product_invocation", default=None)


async def dispatch(app, scope, receive, send, body: bytes):
    path = scope["path"]
    if path.startswith("/auth/") or path in {"/health/live", "/public/status", "/legal/contracts", "/billing/tiers"}:
        return await app(scope, receive, send)
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    import auth
    import db
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    try:
        token = headers.get(b"authorization", b"").decode("latin1")
        if not token.startswith("Bearer "):
            raise HTTPException(401, "请先登录")
        user = await run_in_threadpool(auth.get_current_user,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token[7:]))
        if not user.get("phone_verified_at"):
            raise HTTPException(403, "免费试用需要已验证手机号")
        consent = await run_in_threadpool(db.fetchone,
            "SELECT user_id FROM user_contract_acceptances WHERE user_id=? AND contract_version=?",
            (user["id"], CONTRACT_VERSION))
        if not consent:
            raise HTTPException(403, "请确认当前产品服务条款与隐私说明")
        request_id = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        if path in PAID_ROUTES and not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise HTTPException(400, "请携带有效请求标识，避免重复扣额")
        if body:
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                raise HTTPException(400, "请求格式无效")
            if not isinstance(payload, dict):
                raise HTTPException(400, "请求格式无效")
            # Media and Tracking retain their concrete validation/deployment boundaries.
            # Facts use the existing intent/entity decision, never a gift/free downgrade.
            if any(payload.get(k) for k in ("cover_image", "cover_images", "extra_images", "image_base64", "video_file_id")):
                raise HTTPException(422, "当前免费体验支持文字输入；图片和视频尚未开放")

        context = Invocation(user["id"], request_id or str(uuid.uuid4()), route=path)
        if path in PAID_ROUTES and os.environ.get("NOTEAI_MODEL_CONFIG_ENABLED") == "1":
            import model_runtime_config
            context.model_config = await run_in_threadpool(model_runtime_config.read)
        if path in PAID_ROUTES:
            import prompt_manager
            context.prompts = await run_in_threadpool(prompt_manager.capture_request)
    except HTTPException as exc:
        return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
    marker = _invocation.set(context)
    prompt_marker = prompt_manager.bind_request(context.prompts) if context.prompts is not None else None
    try:
        return await app(scope, receive, send)
    finally:
        if prompt_marker is not None:
            prompt_manager.release_request(prompt_marker)
        _invocation.reset(marker)


def available():
    if not enabled():
        return False
    import db
    try:
        budget = db.fetchone("SELECT * FROM public_trial_budget WHERE id=?", (BUDGET_ID,))
        return bool(budget and budget["enabled"] == 1 and (
            dict(budget).get("policy_mode") == "owner_metered"
            or budget["reserved_milli_cny"] + RESERVE_MILLI_CNY <= budget["limit_milli_cny"]))
    except Exception:
        return False


def record_fact_observation(result):
    """Bind non-content retrieval metadata to the existing business call record."""
    current = _invocation.get()
    if current is None:
        return
    calls = result.get("calls") or {}
    def code(value):
        return value if isinstance(value,str) and re.fullmatch(r"[A-Za-z0-9_]{1,80}",value) else None
    def counter(value):
        return value if type(value) is int and 0 <= value <= 1000 else None
    providers = str(result.get("provider") or "").split("+")
    provider = next((name for name in providers if name in
        {"amap","meituan_travel","baidu_map","tencent_map","serpapi","bing","google_cse"}),None)
    observed_at = result.get("observed_at")
    try:
        if not isinstance(observed_at,str) or len(observed_at)>40:
            raise ValueError
        datetime.fromisoformat(observed_at)
    except ValueError:
        observed_at = None
    current.fact_observation = {
        "provider": provider, "observed_at": observed_at,
        "status": code(result.get("status")), "error_code": code(result.get("error_code")),
        "cached": bool(result.get("cached")), "cost_cny": None,
        "http_requests": counter(calls.get("http_requests")), "cli_invocations": counter(calls.get("cli_invocations")),
        "last_http_status": counter(calls.get("last_http_status")),
        "partial_errors": [item for item in (calls.get("partial_errors") or [])[:8] if code(item)],
    }


def runtime_services():
    import fact_enrichment
    import model_runtime_config
    try:
        active = model_runtime_config.read()["active"]
        tasks = [task for task, row in active.items() if row.get("enabled")]
    except Exception:
        tasks = None
    gateway = all(os.environ.get(key) for key in (
        "NOTEAI_CLAUDE_GATEWAY_URL", "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET"))
    rows = [
        {"id": "kimi", "name": "Kimi K2.6", "group": "generation_models",
         "role": "当前已生效的文字诊断、生成、语义、仲裁和对话模型；原设计同时承担视觉分析",
         "business": tasks, "configured": bool(os.environ.get("MOONSHOT_API_KEY")), "enabled": available(),
         "reason": "按已发布业务配置与用户权益执行，实际用量入账；不因赠送来源降质"},
        {"id": "claude", "name": "Claude Haiku / Sonnet", "group": "generation_models",
         "role": "原分工：Haiku 诊断、生成、语义；Sonnet 仲裁、对话",
         "business": [], "configured": bool(gateway), "enabled": False,
         "reason": "当前个人 API 通道的公开地区条款不覆盖中国内地商家场景，未启用；历史 Gateway 调用成功保留，不能作为当前用途通过"},
    ]
    for row in rows:
        row.update(source="api_runtime_configuration", upstream_probed=False)
    return rows + fact_enrichment.runtime_services()


def public_services():
    # Product availability is public; process observations and configuration
    # presence belong to authenticated operations, not registration/status.
    fields = {"id", "name", "group", "role", "business", "enabled", "reason"}
    public = []
    for row in runtime_services():
        summary = {key: value for key, value in row.items() if key in fields}
        if row.get("group") == "data_tools":
            summary["reason"] = "根据业务输入按需查询，缺失信息会明确提示" if row.get("enabled") else "当前未开放该检索来源"
        public.append(summary)
    return public


def validate_startup(storage):
    if os.environ.get("NOTEAI_MODEL_RETRY_ATTEMPTS") != "1":
        raise RuntimeError("public trial requires zero model auto-retries")
    if not os.environ.get("MOONSHOT_API_KEY"):
        raise RuntimeError("public trial Kimi credentials unavailable")
    for flag in ("NOTEAI_API_STARTS_TREND_SCHEDULER", "NOTEAI_DURABLE_AI_ADMISSION_ENABLED"):
        if os.environ.get(flag, "0") != "0":
            raise RuntimeError("public trial cannot start background business tasks")
    budget = storage.fetchone("SELECT * FROM public_trial_budget WHERE id=?", (BUDGET_ID,))
    if not budget or budget["limit_milli_cny"] != LIMIT_MILLI_CNY or budget["enabled"] != 1:
        raise RuntimeError("public trial budget unavailable")


class TrialProviderStopped(RuntimeError):
    def __init__(self, code):
        current = _invocation.get()
        if current is not None:
            current.failure = code
        super().__init__(code)


def assert_result_known():
    current = _invocation.get()
    if enabled() and current is not None and current.failure:
        raise TrialProviderStopped(current.failure)


class _SlotsBusy(Exception):
    pass


def _reserve(request: httpx.Request) -> str:
    import db
    import billing
    import prompt_manager
    current = _invocation.get()
    assert_result_known()
    if current is None:
        raise TrialProviderStopped("PUBLIC_TRIAL_REQUIRES_USER_REQUEST")
    if request.method != "POST" or str(request.url) != ENDPOINT:
        raise TrialProviderStopped("PUBLIC_TRIAL_PROVIDER_NOT_ALLOWED")
    try:
        payload = json.loads(request.content)
        maximum = payload.get("max_tokens")
        messages = payload.get("messages")
        if (payload.get("model") != MODEL or type(maximum) is not int or not 1 <= maximum <= 32768
                or payload.get("n", 1) != 1 or payload.get("tools") or payload.get("tool_choice")
                or not isinstance(messages, list) or len(messages) > 100
                or len(request.content) > 524288
                or any(not isinstance(m, dict) or not isinstance(m.get("content"), str) for m in messages)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise TrialProviderStopped("PUBLIC_TRIAL_REQUEST_OUT_OF_SCOPE") from None
    now = datetime.now(timezone.utc).isoformat()
    call_id = str(uuid.uuid4())
    request_hash = hashlib.sha256((current.user_id + ":" + current.request_id).encode()).hexdigest()
    with db.transaction(write=True) as tx:
        lock = " FOR UPDATE" if tx.postgres else ""
        budget = tx.fetchone("SELECT * FROM public_trial_budget WHERE id=?" + lock, (BUDGET_ID,))
        metered = bool(budget and dict(budget).get("policy_mode") == "owner_metered")
        if (not budget or budget["enabled"] != 1 or (not metered
                and budget["reserved_milli_cny"] + RESERVE_MILLI_CNY > budget["limit_milli_cny"])):
            raise TrialProviderStopped("PUBLIC_TRIAL_BUDGET_EXHAUSTED")
        usage_id = billing._ACTIVE_USAGE_ID.get() if metered else None
        if metered:
            parent = tx.fetchone("SELECT id,source,operation FROM usage_records WHERE id=? AND user_id=?",
                                 (usage_id, current.user_id))
            if not parent:
                raise TrialProviderStopped("PUBLIC_MODEL_REQUIRES_ENTITLEMENT_USAGE")
            pending = tx.fetchall("SELECT id FROM public_trial_calls WHERE request_hash=? "
                                  "AND usage_record_id IS NOT NULL AND model_usage_record_id IS NULL "
                                  "AND state='responded' AND http_status=200", (request_hash,))
            if any(row["id"] not in current.call_ids for row in pending):
                raise TrialProviderStopped("PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED_NO_REPLAY")
        if tx.fetchone("SELECT id FROM public_trial_calls WHERE request_hash=? AND state='unknown' LIMIT 1", (request_hash,)):
            raise TrialProviderStopped("PUBLIC_TRIAL_UNKNOWN_NO_REPLAY")
        # At most two physical calls may be in flight in the entire public scope.
        if tx.fetchone("SELECT COUNT(*) AS n FROM public_trial_calls WHERE state='dispatched'")["n"] >= 2:
            raise _SlotsBusy()
        tx.execute("UPDATE public_trial_budget SET reserved_milli_cny=reserved_milli_cny+? WHERE id=?",
                   (RESERVE_MILLI_CNY, BUDGET_ID))
        if metered:
            provenance = json.dumps({"model": payload["model"], "route": current.route,
                "operation": parent["operation"], "entitlement_source": parent["source"],
                "model_config_revision": (current.model_config or {}).get("active_revision"),
                "prompts": prompt_manager.request_versions(),
                "fact_observation": current.fact_observation}, separators=(",", ":"), sort_keys=True)
            tx.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id,provenance_json) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (call_id,BUDGET_ID,current.user_id,request_hash,"dispatched",RESERVE_MILLI_CNY,now,usage_id,provenance))
        else:
            tx.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at) "
                       "VALUES(?,?,?,?,?,?,?)", (call_id,BUDGET_ID,current.user_id,request_hash,"dispatched",RESERVE_MILLI_CNY,now))
        current.call_ids.add(call_id)
    return call_id


def _record_response(call_id: str, status: int | None, *, unknown=False):
    import db
    # Reservation remains charged even if body/stream subsequently disconnects.
    if (status is None or unknown) and _invocation.get() is not None:
        _invocation.get().failure = "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY"
    try:
        db.execute("UPDATE public_trial_calls SET state=?,http_status=? WHERE id=? AND state='dispatched'",
                   ("responded" if status is not None and not unknown else "unknown", status, call_id))
    except Exception:
        raise TrialProviderStopped("PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN") from None


def _reserve_with_wait(request):
    deadline = time.monotonic() + 90
    while True:
        try:
            return _reserve(request)
        except _SlotsBusy:
            if time.monotonic() >= deadline:
                raise TrialProviderStopped("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED") from None
            time.sleep(0.25)
        except TrialProviderStopped:
            raise
        except Exception:
            raise TrialProviderStopped("PUBLIC_TRIAL_RESERVATION_UNKNOWN") from None


class _TerminalParser:
    def __init__(self):
        self.pending = b""
        self.done = False
        self.content_seen = False
        self.finish_reason = None

    def feed(self, chunk):
        self.pending += chunk
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            self._line(line.rstrip(b"\r"))
        if len(self.pending) > 1048576:
            raise TrialProviderStopped("PUBLIC_TRIAL_RESPONSE_LINE_TOO_LARGE")

    def _line(self, line):
        if line == b"data: [DONE]":
            self.done = self.content_seen and self.finish_reason == "stop"
        elif line.startswith(b"data:"):
            try:
                value = json.loads(line[5:])
                if not isinstance(value, dict) or value.get("error"):
                    raise ValueError()
                for choice in value.get("choices", []):
                    content = choice.get("delta", {}).get("content")
                    if isinstance(content, str) and content:
                        self.content_seen = True
                    if choice.get("finish_reason"):
                        self.finish_reason = choice["finish_reason"]
            except (ValueError, TypeError, AttributeError):
                raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_INVALID") from None

    def finish(self):
        self._line(self.pending.rstrip(b"\r"))
        if not self.done:
            raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_UNKNOWN")


def _validate_response(response):
    if response.status_code != 200:
        raise TrialProviderStopped("PUBLIC_TRIAL_PROVIDER_REJECTED")
    try:
        value = response.json()
        choice = value["choices"][0]
        if value.get("error") or choice.get("finish_reason") != "stop":
            raise ValueError()
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise TrialProviderStopped("PUBLIC_TRIAL_RESPONSE_UNKNOWN") from None


class _TrackedStream(httpx.SyncByteStream):
    def __init__(self, stream, call_id, status):
        self.stream, self.call_id, self.status = stream, call_id, status
        self.parser = _TerminalParser()

    def __iter__(self):
        try:
            for chunk in self.stream:
                self.parser.feed(chunk)
                yield chunk
            self.parser.finish()
        except Exception:
            raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_UNKNOWN") from None

    def close(self):
        try:
            self.stream.close()
        finally:
            _record_response(self.call_id, self.status if self.parser.done else None)


class _TrackedAsyncStream(httpx.AsyncByteStream):
    def __init__(self, stream, call_id, status):
        self.stream, self.call_id, self.status = stream, call_id, status
        self.parser = _TerminalParser()

    async def __aiter__(self):
        try:
            async for chunk in self.stream:
                self.parser.feed(chunk)
                yield chunk
            self.parser.finish()
        except Exception:
            raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_UNKNOWN") from None

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            await run_in_threadpool(_record_response, self.call_id, self.status if self.parser.done else None)


class _KimiClient(httpx.Client):
    def send(self, request, **kwargs):
        call_id = _reserve_with_wait(request)
        try:
            response = super().send(request, **kwargs)
        except BaseException:
            _record_response(call_id, None)
            raise TrialProviderStopped("PUBLIC_TRIAL_TRANSPORT_UNKNOWN") from None
        response.extensions["noteai_call_id"] = call_id
        if kwargs.get("stream") and response.status_code == 200 and response.is_closed:
            parser = _TerminalParser()
            parser.feed(response.content)
            try:
                parser.finish()
            finally:
                _record_response(call_id, response.status_code if parser.done else None)
        elif kwargs.get("stream") and response.status_code == 200:
            response.stream = _TrackedStream(response.stream, call_id, response.status_code)
        else:
            try:
                _validate_response(response)
            except TrialProviderStopped:
                _record_response(call_id, response.status_code, unknown=response.status_code == 200)
                response.close()
                raise
            _record_response(call_id, response.status_code)
        return response


class _KimiAsyncClient(httpx.AsyncClient):
    async def send(self, request, **kwargs):
        call_id = await run_in_threadpool(_reserve_with_wait, request)
        try:
            response = await super().send(request, **kwargs)
        except BaseException:
            await run_in_threadpool(_record_response, call_id, None)
            raise TrialProviderStopped("PUBLIC_TRIAL_TRANSPORT_UNKNOWN") from None
        response.extensions["noteai_call_id"] = call_id
        if kwargs.get("stream") and response.status_code == 200 and response.is_closed:
            parser = _TerminalParser()
            parser.feed(response.content)
            try:
                parser.finish()
            finally:
                await run_in_threadpool(_record_response, call_id, response.status_code if parser.done else None)
        elif kwargs.get("stream") and response.status_code == 200:
            response.stream = _TrackedAsyncStream(response.stream, call_id, response.status_code)
        else:
            try:
                _validate_response(response)
            except TrialProviderStopped:
                await run_in_threadpool(_record_response, call_id, response.status_code, unknown=response.status_code == 200)
                await response.aclose()
                raise
            await run_in_threadpool(_record_response, call_id, response.status_code)
        return response


def kimi_client(**kwargs):
    if not enabled():
        return httpx.Client(**kwargs)
    kwargs.update(follow_redirects=False, trust_env=False)
    return _KimiClient(**kwargs)


def kimi_async_client(**kwargs):
    if not enabled():
        return httpx.AsyncClient(**kwargs)
    kwargs.update(follow_redirects=False, trust_env=False)
    return _KimiAsyncClient(**kwargs)
