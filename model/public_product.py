"""Scoped public use of the existing product, credit ledger and model pipeline.

No provider payload, credentials or returned content is persisted here. Cumulative
reservations retain conservative estimates, including unknown outcomes; actual
returned usage is separately settled and is never inferred from the reservation.
"""
from __future__ import annotations

import asyncio
import contextvars
from contextlib import asynccontextmanager, contextmanager
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
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
    ("POST", "/wechat/share-config"),
    ("POST", "/auth/contracts/accept"),
    ("GET", "/billing/tiers"), ("GET", "/billing/plan"),
    ("GET", "/billing/usage"), ("GET", "/billing/credits"), ("GET", "/billing/quote"),
    ("GET", "/notes"), ("POST", "/notes"), ("GET", "/notes/tracking"),
    ("POST", "/notes/track-url"),
    ("GET", "/account/export"), ("GET", "/account/archive/recovery"),
    ("POST", "/account/archive/recover"), ("POST", "/auth/sessions/revoke-all"),
    ("POST", "/auth/password-reset"), ("POST", "/auth/change-password"), ("DELETE", "/account"),
    ("GET", "/diagnoses"), ("GET", "/reports"), ("GET", "/covers"),
    ("GET", "/profile/growth"), ("GET", "/profile/memories"),
    ("GET", "/profile/achievements"),
    ("PUT", "/auth/profile"), ("PATCH", "/auth/profile"), ("PUT", "/auth/avatar"),
    ("POST", "/analyze/stream"), ("POST", "/generate/stream"),
    ("POST", "/chat/start"), ("POST", "/chat/message"),
    ("POST", "/chat/select-plan"),
    ("GET", "/chat/tasks"),
})
PAID_ROUTES = {"/analyze/stream", "/generate/stream", "/chat/message", "/extract-screenshot", "/validate-ocr"}
MEDIA_UPLOAD_ROUTES = {"/upload-image", "/upload-video"}
MEDIA_PAYLOAD_ROUTES = {"/analyze/stream", "/generate/stream", "/chat/message", "/extract-screenshot", "/validate-ocr"}


def image_enabled() -> bool:
    import ark_media
    import private_storage
    return (enabled() and os.environ.get("NOTEAI_PUBLIC_MEDIA_ENABLED", "0") == "1"
            and ark_media.configured() and private_storage.object_backend_configured())


def video_enabled() -> bool:
    return image_enabled() and os.environ.get("NOTEAI_PUBLIC_VIDEO_ENABLED", "0") == "1"


def media_enabled() -> bool:
    # Shared authentication, bounded body and concurrency path; capability
    # checks below remain modality-specific.
    return image_enabled() or video_enabled()


def enabled() -> bool:
    return os.environ.get("NOTEAI_PUBLIC_PRODUCT", "0") == "1"


def wechat_configured(*, callback: bool = False) -> bool:
    """Current Native-first scope; flags alone do not certify provider readiness."""
    flag = "NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED" if callback else "NOTEAI_PAYMENT_ORDERING_ENABLED"
    return (enabled() and os.environ.get("NOTEAI_RUNTIME_ROLE") == "api"
            and os.environ.get(flag, "").lower() in {"1", "true", "yes"}
            and os.environ.get("NOTEAI_PAYMENT_ORDER_PROVIDERS", "").strip() == "wechatpay_direct")


def allowed_route(method: str, path: str) -> bool:
    if method in {"GET", "DELETE"} and re.fullmatch(r"/notes/tracking/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", path):
        return True
    if method == "POST" and re.fullmatch(r"/notes/tracking/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/fill", path):
        return True
    if method in {"PATCH", "DELETE"} and re.fullmatch(r"/profile/memories/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", path):
        return True
    if method == "GET" and re.fullmatch(r"/reports/(?:analyze|generate)/(?:[0-9a-f]{32}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})", path):
        return True
    if re.fullmatch(r"/reports/(?:analyze|generate)/(?:[0-9a-f]{32}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})/cover-sources(?:/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})?", path):
        return method == "GET" or (method == "PUT" and path.endswith("/cover-sources") and image_enabled())
    if re.fullmatch(r"/reports/(?:analyze|generate)/(?:[0-9a-f]{32}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})/covers", path):
        return method in {"GET", "POST"}
    if re.fullmatch(r"/covers/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}(?:/(?:download|adjust))?", path):
        return (method == "GET" and not path.endswith("/adjust")) or (method == "POST" and path.endswith("/adjust"))
    if method == "GET" and re.fullmatch(r"/chat/tasks/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", path):
        return True
    if method == "POST" and re.fullmatch(r"/chat/tasks/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/cancel", path):
        return True
    if method == "POST" and image_enabled() and path in {"/upload-image", "/extract-screenshot", "/validate-ocr"}:
        return True
    if method == "POST" and video_enabled() and path == "/upload-video":
        return True
    if (method, path) in EXACT_ROUTES:
        return True
    # Original order ownership is still enforced by the API when ordering is
    # paused; a pause must not hide payment/refund reconciliation from its owner.
    if method == "GET" and (path in {"/payments/capabilities", "/payments/orders"}
            or re.fullmatch(r"/payments/orders/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", path)):
        return True
    if wechat_configured():
        if (method, path) in {("GET", "/payments/capabilities"), ("GET", "/payments/orders"), ("POST", "/payments/orders")}:
            return True
        if method == "GET" and re.fullmatch(r"/payments/orders/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", path):
            return True
    if method == "DELETE" and re.fullmatch(r"/(?:notes|diagnoses)/(?:[0-9a-f]{32}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})", path):
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
    observed_models: set = field(default_factory=set)
    fact_observation: dict | None = None
    admission_state: object | None = field(default=None, repr=False)
    budget_id: str | None = None


_invocation = contextvars.ContextVar("public_product_invocation", default=None)
_model_lease = contextvars.ContextVar("public_product_model_lease", default=None)


def _cover_scope():
    current = _invocation.get()
    return current is not None and current.route == "/covers"


def _admission_operation():
    import model_admission
    current = _invocation.get()
    if current is None:
        raise TrialProviderStopped("PUBLIC_TRIAL_REQUIRES_USER_REQUEST")
    if current.admission_state is None:
        # Internal/test callers still use their genuine Invocation identity;
        # ordinary HTTP requests register bounded capacity before charging.
        current.admission_state = model_admission.Operation(
            current.user_id, hashlib.sha256(current.request_id.encode()).hexdigest())
    return current.admission_state


@contextmanager
def model_admission_sync(operation_id, provider):
    if not enabled() and not _cover_scope():
        yield
        return
    import model_admission as admission
    operation = _admission_operation()
    existing = _model_lease.get()
    if existing is not None:
        if existing.operation is not operation or existing.call_id != operation_id or existing.provider != provider:
            raise TrialProviderStopped("MODEL_ADMISSION_NESTED_CALL")
        yield existing
        return
    queue = admission.current().calls
    try:
        ticket = queue.acquire(operation, operation_id, provider)
    except admission.AdmissionError as exc:
        raise TrialProviderStopped(str(exc)) from None
    marker = _model_lease.set(ticket)
    try:
        yield ticket
    finally:
        _model_lease.reset(marker)
        if not ticket.held_by_stream:
            queue.release(ticket)


@asynccontextmanager
async def model_admission(operation_id, provider):
    if not enabled() and not _cover_scope():
        yield
        return
    import model_admission as admission
    operation = _admission_operation()
    existing = _model_lease.get()
    if existing is not None:
        if existing.operation is not operation or existing.call_id != operation_id or existing.provider != provider:
            raise TrialProviderStopped("MODEL_ADMISSION_NESTED_CALL")
        yield existing
        return
    queue = admission.current().calls
    try:
        ticket = await queue.acquire_async(operation, operation_id, provider)
    except admission.AdmissionError as exc:
        raise TrialProviderStopped(str(exc)) from None
    marker = _model_lease.set(ticket)
    try:
        yield ticket
    finally:
        _model_lease.reset(marker)
        if not ticket.held_by_stream:
            queue.release(ticket)


@asynccontextmanager
async def media_worker_slot(image_index):
    if not enabled():
        yield
        return
    import model_admission as admission
    queue = admission.current().media
    try:
        ticket = await queue.acquire_async(_admission_operation(), str(uuid.uuid4()), "media_worker")
    except admission.AdmissionError as exc:
        raise TrialProviderStopped(str(exc)) from None
    try:
        yield
    finally:
        queue.release(ticket)


def mark_model_dispatched(operation_id):
    ticket = _model_lease.get()
    if ticket is not None:
        import model_admission as admission
        # Dispatch intent and cancel share the same lock. A cancellation that
        # wins first cannot be followed by a newly dispatched physical call.
        with admission.current().calls.lock:
            if ticket.call_id != operation_id or ticket.dispatched or ticket.closed:
                raise TrialProviderStopped("MODEL_CALL_ALREADY_DISPATCHED")
            cancelled = ticket.operation.cancelled.is_set()
            if not cancelled:
                ticket.dispatched = True
                ticket.last_activity = time.monotonic()
        if cancelled:
            _record_response(operation_id, None, not_dispatched=True)
            raise TrialProviderStopped("MODEL_OPERATION_CANCELLED")


def note_model_activity(ticket=None):
    ticket = ticket or _model_lease.get()
    if ticket is not None:
        import model_admission as admission
        admission.current().calls.note_activity(ticket)


def model_dispatch_started():
    ticket = _model_lease.get()
    return bool(ticket and ticket.dispatched)


def queue_status(user_id=None, request_hash=None):
    import model_admission as admission
    manager = admission.current()
    if user_id is None and request_hash is None:
        current = _invocation.get()
        operation = current.admission_state if current is not None else None
    else:
        operation = manager.find(user_id, request_hash)
    if operation is None:
        return {"active": False, "can_cancel": False, "state": "idle"}
    status = manager.calls.status(operation)
    media = manager.media.status(operation)
    if status["state"] == "idle" and media["state"] != "idle":
        status.update({key: media[key] for key in ("state", "provider", "waiting_seconds", "queued_calls", "waiting_operations", "can_cancel")})
    return status


def request_cancel(user_id, request_hash):
    import model_admission as admission
    manager = admission.current()
    operation = manager.find(user_id, request_hash)
    if operation is None:
        return False
    return manager.cancel_active(operation)


def bind_task_claim(claim):
    if not enabled() or not claim:
        return
    import model_admission as admission
    operation = _admission_operation()
    if claim.get("user_id") != operation.user_id:
        raise TrialProviderStopped("MODEL_TASK_OWNER_MISMATCH")
    admission.current().bind_claim(operation, claim["key_hash"])


async def authenticated_user(scope):
    """Authenticate uploads before reading their bodies, using original consent."""
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    import auth
    import db
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    token = headers.get(b"authorization", b"").decode("latin1")
    if not token.startswith("Bearer "):
        raise HTTPException(401, "请先登录")
    user = await run_in_threadpool(auth.get_current_user,
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token[7:]))
    if not user.get("phone_verified_at"):
        raise HTTPException(403, "请先验证本人手机号")
    consent = await run_in_threadpool(db.fetchone,
        "SELECT user_id FROM user_contract_acceptances WHERE user_id=? AND contract_version=?",
        (user["id"], CONTRACT_VERSION))
    if not consent:
        raise HTTPException(403, "请确认当前产品服务条款与隐私说明")
    return user


async def dispatch(app, scope, receive, send, body: bytes, *, authenticated=None):
    import postdelivery
    postdelivery.ensure_request_id(scope)
    path = scope["path"]
    if ((scope["method"], path) == ("POST", "/wechat/share-config")
            or path.startswith("/auth/") or path in {"/health/live", "/public/status", "/legal/contracts", "/billing/tiers", "/payments/capabilities"}):
        return await app(scope, receive, send)
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    import auth
    import db
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    try:
        user = authenticated or await authenticated_user(scope)
        request_id = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        if path in PAID_ROUTES and not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise HTTPException(400, "请携带有效请求标识，避免重复扣额")
        manual_fill = scope["method"] == "POST" and bool(re.fullmatch(
            r"/notes/tracking/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/fill", path))
        if manual_fill and not body:
            raise HTTPException(422, "请明确填写点赞、收藏和评论的整数数量")
        if path == "/notes/track-url" and not body:
            raise HTTPException(403, "当前仅开放手工录入表现，自动采集尚未开放")
        if body:
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                raise HTTPException(400, "请求格式无效")
            if not isinstance(payload, dict):
                raise HTTPException(400, "请求格式无效")
            if manual_fill and (any(type(payload.get(key)) is not int for key in ("likes", "saves", "comments"))
                                or (payload.get("views") is not None and type(payload["views"]) is not int)):
                raise HTTPException(422, "点赞、收藏和评论须明确填写整数；浏览量可不填")
            if path == "/notes/track-url" and payload.get("collection_mode") != "manual":
                raise HTTPException(403, "当前仅开放手工录入表现，自动采集尚未开放")
            if path == "/payments/orders" and payload.get("provider") not in (None, "wechatpay_direct"):
                raise HTTPException(403, "当前仅开放微信支付")
            # Media and Tracking retain their concrete validation/deployment boundaries.
            # Facts use the existing intent/entity decision, never a gift/free downgrade.
            if not image_enabled() and any(payload.get(k) for k in ("cover_image", "cover_images", "extra_images", "image_base64")):
                raise HTTPException(422, "图片输入尚未开放，当前可使用文字输入")
            if not video_enabled() and payload.get("video_file_id"):
                raise HTTPException(422, "视频音画理解尚未开放，请使用当前已开放的输入方式")

        context = Invocation(user["id"], request_id or str(uuid.uuid4()), route=path)
        if path in PAID_ROUTES and os.environ.get("NOTEAI_MODEL_CONFIG_ENABLED") == "1":
            import model_runtime_config
            context.model_config = await run_in_threadpool(model_runtime_config.read)
        if path in PAID_ROUTES:
            import prompt_manager
            context.prompts = await run_in_threadpool(prompt_manager.capture_request)
    except HTTPException as exc:
        return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
    admitted = None
    owns_admission = False
    if path in PAID_ROUTES:
        import model_admission as admission
        try:
            admitted, owns_admission = admission.current().register(
                context.user_id, hashlib.sha256(context.request_id.encode()).hexdigest(), route=path)
            context.admission_state = admitted
        except admission.AdmissionError as exc:
            return await JSONResponse({"detail": {"code": str(exc),
                "message": "当前生成队列已满，或本账号已有任务处理中。本次未受理、未扣积分，请稍后查看原任务或重新提交。"}},
                status_code=429, headers={"Retry-After": "5"})(scope, receive, send)
    marker = _invocation.set(context)
    prompt_marker = prompt_manager.bind_request(context.prompts) if context.prompts is not None else None
    try:
        return await app(scope, receive, send)
    finally:
        if prompt_marker is not None:
            prompt_manager.release_request(prompt_marker)
        _invocation.reset(marker)
        if owns_admission:
            admission.current().cancel(admitted)
            admission.current().finish(admitted)


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


def _persist_fact_observation(observation, observation_id):
    """One bounded observation on the existing user's task; never a model call."""
    import billing
    import db
    import content_retention
    current = _invocation.get()
    usage_id = billing._ACTIVE_USAGE_ID.get()
    if current is None or not usage_id:
        return
    row_value = dict(observation, observation_id=observation_id,
                     persisted_at=datetime.now(timezone.utc).isoformat(), route=current.route)
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, current.user_id)
        suffix = " FOR UPDATE" if tx.postgres else ""
        row = tx.fetchone("SELECT fact_observations_json FROM usage_records WHERE id=? AND user_id=?" + suffix,
                          (usage_id, current.user_id))
        if row is None:
            raise RuntimeError("FACT_USAGE_PARENT_NOT_FOUND")
        rows = json.loads(row["fact_observations_json"])
        if not isinstance(rows, list) or any(not isinstance(value, dict) for value in rows):
            raise RuntimeError("FACT_USAGE_METADATA_INVALID")
        prior = next((i for i, value in enumerate(rows) if value.get("observation_id") == observation_id), None)
        if prior is None:
            if sum(value.get("kind") != "local_step" for value in rows) >= 32:
                raise RuntimeError("FACT_USAGE_OBSERVATION_LIMIT")
            rows.append(row_value)
        else:
            if rows[prior].get("status") != "result_pending":
                old = {key: value for key, value in rows[prior].items() if key != "persisted_at"}
                new = {key: value for key, value in row_value.items() if key != "persisted_at"}
                if old != new:
                    raise RuntimeError("FACT_USAGE_RESULT_ALREADY_RECORDED")
                return
            rows[prior] = row_value
        raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(raw.encode()) > 65536:
            raise RuntimeError("FACT_USAGE_METADATA_LIMIT")
        tx.execute("UPDATE usage_records SET fact_observations_json=? WHERE id=? AND user_id=?",
                   (raw, usage_id, current.user_id))


def begin_fact_observation(provider):
    observation_id = str(uuid.uuid4())
    _persist_fact_observation({"provider": provider, "status": "result_pending",
        "observed_at": datetime.now(timezone.utc).isoformat(), "cached": False,
        "cost_cny": None, "cost_status": "unknown", "http_requests": None,
        "cli_invocations": None, "dispatch_basis": "retrieval_started_upstream_dispatch_not_yet_confirmed"}, observation_id)
    return observation_id


def record_fact_observation(result, observation_id=None):
    """Persist retrieval metadata independently of any later model admission."""
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
        "observation_id": observation_id, "provider": provider, "observed_at": observed_at,
        "status": code(result.get("status")), "error_code": code(result.get("error_code")),
        "cached": bool(result.get("cached")), "cost_cny": None,
        "http_requests": counter(calls.get("http_requests")), "cli_invocations": counter(calls.get("cli_invocations")),
        "last_http_status": counter(calls.get("last_http_status")),
        "partial_errors": [item for item in (calls.get("partial_errors") or [])[:8] if code(item)],
    }

    cached_no_call = current.fact_observation["cached"] and calls.get("http_requests") == 0 and calls.get("cli_invocations") == 0
    current.fact_observation.update(
        cost_cny=0.0 if cached_no_call else None,
        cost_status="no_new_retrieval" if cached_no_call else
            "owner_reported_not_charged_pending_confirmation" if provider == "meituan_travel" else "unknown",
        source_count=len(result.get("sources") or []),
        source_identity_sha256=hashlib.sha256(json.dumps(result.get("sources") or [], sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        result_identity_sha256=hashlib.sha256(json.dumps({key:result.get(key) for key in ("status","error_code","facts","sources")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    )
    _persist_fact_observation(current.fact_observation, observation_id or str(uuid.uuid4()))


def runtime_services():
    import fact_enrichment
    import model_runtime_config
    try:
        active = model_runtime_config.read()["active"]
        tasks = {provider: [task for task, row in active.items()
                           if row.get("enabled") and row.get("model", "").startswith(provider)]
                 for provider in ("kimi", "claude")}
    except Exception:
        tasks = {"kimi": None, "claude": None}
    gateway = all(os.environ.get(key) for key in (
        "NOTEAI_CLAUDE_GATEWAY_URL", "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET")) and os.environ.get("NOTEAI_CLAUDE_TRANSPORT") == "gateway"
    import ark_media
    import private_storage
    media_reason = (
        "尚未配置素材理解模型的服务端凭据或精确版本"
        if not ark_media.configured() else
        "私有素材存储尚未就绪"
        if not private_storage.object_backend_configured() else
        "图片入口已开放；视频入口已开放，实际核验见最近调用记录"
        if video_enabled() else
        "图片入口已开放；视频入口尚未开放，实际核验见最近调用记录"
        if image_enabled() else
        "模型与私有存储已配置；公开图片及视频入口尚未开放，最近调用仅代表对应任务结果"
    )
    rows = [
        {"id":"doubao", "name":"Doubao Seed 2.0 Lite 0428", "group":"media_models",
         "model":ark_media.MODEL, "role":"图片、视频及视频原音轨的素材理解，完整观察进入现有行业Prompt和Claude任务",
         "business":["screenshot", "image_understanding", "video_audio_understanding", "cover_analysis", "chat_image"],
         "configured":ark_media.configured(), "enabled":media_enabled(),
         "reason":media_reason},
        {"id": "kimi", "name": "Kimi K2.6", "group": "generation_models",
         "role": "Kimi 文字任务按当前已发布模型路由执行；素材理解单独由豆包负责",
         "business": tasks["kimi"], "configured": bool(os.environ.get("MOONSHOT_API_KEY")),
         "enabled": bool(tasks["kimi"] and os.environ.get("MOONSHOT_API_KEY") and available()),
         "reason": "按已发布业务配置与用户权益执行，实际用量入账；不因赠送来源降质"},
        {"id": "claude", "name": "Claude Haiku / Sonnet", "group": "generation_models",
         "role": "原分工：Haiku 诊断、生成、语义；Sonnet 仲裁、对话",
         "business": tasks["claude"], "configured": bool(gateway),
         "enabled": bool(tasks["claude"] and gateway and available()),
         "reason": ("通过既有 Gateway 执行已发布路由；实际模型、完整结果及用量逐次确认，失败不静默替换"
                    if gateway else "此实例的 Gateway 绑定未齐备；指定 Claude 的请求会明确失败，不静默替换")},
    ]
    for row in rows:
        row.update(source="api_runtime_configuration", upstream_probed=False)
        if row["id"] in tasks and tasks[row["id"]] is None:
            row["reason"] = "当前模型路由读取失败；未将未知状态当作已启用或实时健康"
    return rows + fact_enrichment.runtime_services()


def public_services():
    # Product availability is public; process observations and configuration
    # presence belong to authenticated operations, not registration/status.
    fields = {"id", "name", "group", "role", "business", "enabled", "reason"}
    public = []
    for row in runtime_services():
        summary = {key: value for key, value in row.items() if key in fields}
        if row.get("group") == "data_tools":
            summary["reason"] = ("根据业务输入按需查询，缺失信息会明确提示" if row.get("enabled") else
                row["reason"] if row.get("id") == "amap" and os.environ.get("NOTEAI_AMAP_UNAVAILABLE_REASON") else
                "当前未开放该检索来源")
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
        if current is not None and not current.failure:
            current.failure = code
        super().__init__(code)


def assert_result_known():
    current = _invocation.get()
    if (enabled() or _cover_scope()) and current is not None and current.failure:
        raise TrialProviderStopped(current.failure)
    if ((enabled() or _cover_scope()) and current is not None and current.admission_state is not None
            and current.admission_state.cancelled.is_set()):
        raise TrialProviderStopped("MODEL_OPERATION_CANCELLED")


def record_model_identity(model, *, physical_call_id, usage_status=None):
    current = _invocation.get()
    if (current is not None and physical_call_id in current.call_ids
            and usage_status != "usage_missing"
            and isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", model)):
        current.observed_models.add(model)


def executed_model_label(legacy_label):
    """Report observed, accounted models, never infer them from entitlement/source."""
    current = _invocation.get()
    if not enabled() or current is None:
        return legacy_label
    assert_result_known()
    if not current.observed_models:
        raise TrialProviderStopped("PUBLIC_MODEL_IDENTITY_UNCONFIRMED")
    return " + ".join(sorted(current.observed_models))


class _SlotsBusy(Exception):
    pass


def _reserve(request: httpx.Request) -> str:
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
    return _reserve_payload({**payload, "modality": "text"}, RESERVE_MILLI_CNY,
                            call_id=request.extensions.get("noteai_operation_id"),
                            provenance=request.extensions.get("noteai_provenance"))


def _check_pending_media(tx, user_id, media):
    # Called under the existing budget lock at admission, and read-only before
    # source signing/upload. A different request/ref cannot replay the same bytes.
    pending_media = tx.fetchall(
        "SELECT p.provenance_json,i.status AS task_status,i.refund_applied,"
        "i.complete_applied,i.charge_source,u.source AS usage_source FROM public_trial_calls p "
        "LEFT JOIN idempotency_requests i ON i.usage_id=p.usage_record_id "
        "AND i.user_id=p.user_id LEFT JOIN usage_records u ON u.id=p.usage_record_id "
        "AND u.user_id=p.user_id WHERE p.user_id=? "
        "AND (p.state IN ('dispatched','unknown') OR "
        "(p.state='responded' AND p.http_status=200 AND p.model_usage_record_id IS NULL))",
        (user_id,))
    for pending_row in pending_media:
        # A customer can explicitly start a fresh task after a failed,
        # once-refunded delivery. Preserve the original supplier UNKNOWN/cost
        # and physical identity; this only releases a same-media admission.
        import postdelivery
        policy = str(dict(pending_row).get('charge_source') or '')
        version = policy[len(postdelivery.PREFIX):].split(':') if policy.startswith(postdelivery.PREFIX) else []
        released_reservation = (len(version) == 2 and version[0] in postdelivery.SOURCES
            and version[1] in __import__('billing').TIERS
            and pending_row['usage_source'] == postdelivery.RELEASED_PREFIX + version[0])
        if (pending_row['task_status'] == 'failed'
                and bool(pending_row['refund_applied'])
                and not bool(pending_row['complete_applied'])
                and (pending_row['usage_source'] == 'refunded' or released_reservation)):
            continue
        try:
            prior = json.loads(pending_row['provenance_json'])
        except (TypeError, ValueError):
            raise TrialProviderStopped("PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY") from None
        if not isinstance(prior, dict):
            raise TrialProviderStopped("PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY")
        if prior.get('provider') != 'doubao' and prior.get('model') != 'doubao-seed-2-0-lite-260428':
            continue
        binding = prior.get('media')
        if not isinstance(binding, dict) or binding.get('ref') == media['ref'] or binding.get('sha256') == media['sha256']:
            raise TrialProviderStopped("PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY")


def assert_media_result_known(media):
    import db
    current = _invocation.get()
    assert_result_known()
    if current is None:
        raise TrialProviderStopped("PUBLIC_TRIAL_REQUIRES_USER_REQUEST")
    with db.transaction(write=False) as tx:
        _check_pending_media(tx, current.user_id, media)


def _check_cover_verification_budget(tx, current, usage_id, reserve, budget_id):
    """Optional deployment-scope ceiling, under the existing budget row lock.

    Native cumulative reservations and entitlement charging are never changed.
    The persisted first job binds the scope across worker/process restarts.
    """
    values = [os.environ.get("NOTEAI_COVER_VERIFY_" + name) for name in
              ("USER_ID", "SINCE_UTC", "MAX_MILLI")]
    if all(value is None for value in values):
        return

    def stop(code):
        error = TrialProviderStopped(code)
        error.code = code
        raise error

    owner, since, maximum = values
    try:
        if type(owner) is not str or str(uuid.UUID(owner)) != owner:
            raise ValueError()
        # A correctly configured scope never restricts another user's work.
        if current.user_id != owner:
            return
        if type(since) is not str or len(since) > 40:
            raise ValueError()
        clock = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if clock.tzinfo is None or clock.utcoffset() != timezone.utc.utcoffset(clock):
            raise ValueError()
        if (type(maximum) is not str or not re.fullmatch(r"[1-9][0-9]{0,5}", maximum)
                or int(maximum) > 100000):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        stop("COVER_VERIFY_BUDGET_CONFIG_INVALID")
    first = tx.fetchone("SELECT id,usage_id FROM cover_jobs WHERE user_id=? AND budget_id=? "
        "AND created_at>=? ORDER BY created_at,id LIMIT 1", (owner, budget_id, clock.isoformat()))
    if not first or first["usage_id"] != usage_id:
        stop("COVER_VERIFY_TASK_SCOPE_INVALID")
    rows = tx.fetchall("SELECT c.id,c.user_id,c.budget_id,c.state,c.http_status,c.reserve_milli_cny,"
        "c.model_usage_record_id,m.usage_record_id AS model_usage_id,m.provider AS model_provider,"
        "m.model,m.price_currency,m.pricing_status,m.usage_status,m.known_cost_rmb,"
        "i.id AS image_id,i.job_id AS image_job_id,i.usage_id AS image_usage_id,"
        "i.provider AS image_provider,i.model_id,i.state AS image_state,i.http_status AS image_http,"
        "i.currency,i.cost_status,i.actual_cost FROM public_trial_calls c "
        "LEFT JOIN model_usage_records m ON m.id=c.model_usage_record_id "
        "LEFT JOIN cover_image_usage i ON i.id=c.id WHERE c.usage_record_id=?", (usage_id,))
    total = 0
    for row in rows:
        held = row["reserve_milli_cny"]
        if (type(held) is not int or held < 0 or row["user_id"] != owner
                or row["budget_id"] != budget_id or row["state"] not in {"dispatched", "responded", "unknown"}):
            stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
        amount = None
        if row["model_usage_record_id"] is not None and row["image_id"] is not None:
            stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
        if row["state"] == "responded" and row["http_status"] == 200:
            if row["model_usage_record_id"] is not None:
                if (row["model_usage_id"] != usage_id or row["model_provider"] != "doubao"
                        or row["model"] != "doubao-seed-2-1-pro-260915"
                        or row["price_currency"] not in {"CNY", "RMB"}
                        or row["pricing_status"] != "exact" or row["usage_status"] != "complete"):
                    stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
                amount = row["known_cost_rmb"]
                if amount is None:
                    stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
            elif row["image_id"] is not None:
                if (row["image_usage_id"] != usage_id or row["image_job_id"] != first["id"]
                        or row["image_provider"] != "seedream" or row["model_id"] != "doubao-seedream-5-0-pro-260628"
                        or row["image_state"] != "responded" or row["image_http"] != 200
                        or row["currency"] != "CNY" or row["cost_status"] not in {"estimated", "unknown", "billed"}):
                    stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
                if row["cost_status"] == "billed":
                    amount = row["actual_cost"]
                    if amount is None:
                        stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
                elif row["actual_cost"] is not None:
                    stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
            else:
                stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
        if amount is not None:
            try:
                cost = Decimal(str(amount))
                if isinstance(amount, bool) or not cost.is_finite() or cost < 0:
                    raise ValueError()
                held = int((cost * 1000).to_integral_value(rounding=ROUND_CEILING))
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                stop("COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
        # In-flight, UNKNOWN, non-200 and unbilled images retain their full hold.
        total += held
    if total + reserve > int(maximum):
        stop("COVER_VERIFY_BUDGET_EXHAUSTED")


def _reserve_payload(payload, reserve, *, call_id=None, require_metered=False, provenance=None):
    import db
    import billing
    import prompt_manager
    current = _invocation.get()
    assert_result_known()
    if current is None:
        raise TrialProviderStopped("PUBLIC_TRIAL_REQUIRES_USER_REQUEST")
    now = datetime.now(timezone.utc).isoformat()
    call_id = call_id or str(uuid.uuid4())
    request_hash = hashlib.sha256((current.user_id + ":" + current.request_id).encode()).hexdigest()
    media = payload.get("media")
    if media is not None and (not isinstance(media, dict) or set(media) != {"ref", "sha256", "transport"}
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", str(media.get("ref", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(media.get("sha256", "")))
            or media.get("transport") not in {"inline", "ark_file", "private_oss"}):
        raise TrialProviderStopped("PUBLIC_MEDIA_REFERENCE_INVALID")
    budget_id = current.budget_id or BUDGET_ID
    cover = _cover_scope()
    if budget_id != BUDGET_ID:
        import cover_settings
        if not cover or budget_id not in {cover_settings.BUDGET_ID, cover_settings.FORMAL_BUDGET_ID}:
            raise TrialProviderStopped("PUBLIC_BUDGET_SCOPE_INVALID")
    elif cover:
        raise TrialProviderStopped("COVER_REQUIRES_SEPARATE_BUDGET")
    acceptance = cover and budget_id == cover_settings.BUDGET_ID
    with db.transaction(write=True) as tx:
        lock = " FOR UPDATE" if tx.postgres else ""
        budget = tx.fetchone("SELECT * FROM public_trial_budget WHERE id=?" + lock, (budget_id,))
        metered = bool(budget and dict(budget).get("policy_mode") == "owner_metered")
        if require_metered and not metered:
            raise TrialProviderStopped("PUBLIC_MODEL_ACCOUNTING_NOT_READY")
        if (type(reserve) is not int or reserve < 0 or not budget or budget["enabled"] != 1
                or ((not metered or acceptance)
                    and budget["reserved_milli_cny"] + reserve > budget["limit_milli_cny"])):
            raise TrialProviderStopped("PUBLIC_TRIAL_BUDGET_EXHAUSTED")
        usage_id = billing._ACTIVE_USAGE_ID.get() if metered else None
        if metered:
            parent = tx.fetchone("SELECT id,source,operation FROM usage_records WHERE id=? AND user_id=?",
                                 (usage_id, current.user_id))
            if not parent:
                raise TrialProviderStopped("PUBLIC_MODEL_REQUIRES_ENTITLEMENT_USAGE")
            if cover:
                import cover_settings
                if parent["operation"] != "cover_generate":
                    raise TrialProviderStopped("COVER_ENTITLEMENT_SCOPE_INVALID")
                total_calls = tx.fetchone("SELECT COUNT(*) n FROM public_trial_calls WHERE budget_id=?", (budget_id,))["n"]
                task_calls = tx.fetchone("SELECT COUNT(*) n FROM public_trial_calls WHERE usage_record_id=?", (usage_id,))["n"]
                job = tx.fetchone("SELECT policy_json FROM cover_jobs WHERE usage_id=? AND user_id=?",
                    (usage_id, current.user_id))
                policy = json.loads(job["policy_json"]) if job else {}
                agent_cover = (policy.get("design_version") == 3 and
                    policy.get("workflow_engine") == "editable_design_opencode_v1")
                # The owner lifted the call-count ceiling for A. The same DB
                # money reservation and UNKNOWN/physical-slot guards still apply.
                limit = policy.get("max_physical_calls", 3)
                if ((not agent_cover and acceptance and total_calls >= cover_settings.MAX_ACCEPTANCE_CALLS)
                        or (limit is not None and task_calls >= limit)):
                    raise TrialProviderStopped("COVER_CALL_LIMIT_REACHED")
            pending = tx.fetchall("SELECT id FROM public_trial_calls WHERE request_hash=? "
                                  "AND usage_record_id IS NOT NULL AND model_usage_record_id IS NULL "
                                  "AND state='responded' AND http_status=200", (request_hash,))
            if cover:
                import cover_jobs
                pending = [row for row in pending if not cover_jobs.image_call_settled(tx, row["id"])]
                if pending:
                    raise TrialProviderStopped("COVER_ACCOUNTING_UNCONFIRMED_NO_REPLAY")
            if any(row["id"] not in current.call_ids for row in pending):
                raise TrialProviderStopped("PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED_NO_REPLAY")
        if tx.fetchone("SELECT id FROM public_trial_calls WHERE request_hash=? AND state='unknown' LIMIT 1", (request_hash,)):
            raise TrialProviderStopped("PUBLIC_TRIAL_UNKNOWN_NO_REPLAY")
        if media is not None:
            _check_pending_media(tx, current.user_id, media)
        if cover and budget_id == cover_settings.FORMAL_BUDGET_ID:
            _check_cover_verification_budget(tx, current, usage_id, reserve, budget_id)
        # The fair in-process queue is not a replacement for this shared DB guard.
        import model_admission
        if tx.fetchone("SELECT COUNT(*) AS n FROM public_trial_calls WHERE state='dispatched'")["n"] >= model_admission.current().limits.physical:
            raise _SlotsBusy()
        tx.execute("UPDATE public_trial_budget SET reserved_milli_cny=reserved_milli_cny+? WHERE id=?",
                   (reserve, budget_id))
        if metered:
            call_trace = provenance if isinstance(provenance, dict) else {
                "prompt_scope": "request_snapshot", "prompts": prompt_manager.request_versions()}
            provenance_json = json.dumps({"model": payload["model"], "route": current.route,
                "operation": parent["operation"], "entitlement_source": parent["source"],
                "model_config_revision": (current.model_config or {}).get("active_revision"),
                **{key: call_trace.get(key) for key in ("task", "step", "prompt_domain",
                    "prompt_scope", "prompts", "missing_prompt_keys", "instruction_role", "instruction_sha256")},
                "fact_observation": current.fact_observation,
                "provider": ("seedream" if cover and payload.get("provider") == "seedream" else
                             "claude" if payload["model"].startswith("claude") else
                             "doubao" if payload["model"] in {"doubao-seed-2-0-lite-260428",
                                 "doubao-seed-2-1-pro-260915"} else "kimi"),
                "modality": payload.get("modality"),
                **({"media": media} if media is not None else {}),
                "operation_id": payload.get("operation_id"),
                "max_tokens": payload.get("max_tokens")}, separators=(",", ":"), sort_keys=True)
            tx.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id,provenance_json) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (call_id,budget_id,current.user_id,request_hash,"dispatched",reserve,now,usage_id,provenance_json))
        else:
            tx.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at) "
                       "VALUES(?,?,?,?,?,?,?)", (call_id,budget_id,current.user_id,request_hash,"dispatched",reserve,now))
        current.call_ids.add(call_id)
    return call_id


def _record_response(call_id: str, status: int | None, *, unknown=False, not_dispatched=False):
    import db
    # Reservation remains charged even if body/stream subsequently disconnects.
    if (unknown or (status is None and not not_dispatched)) and _invocation.get() is not None:
        current = _invocation.get()
        if not current.failure:
            current.failure = "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY"
    expected = "responded" if not_dispatched or (status is not None and not unknown) else "unknown"
    try:
        with db.transaction(write=True) as tx:
            lock = " FOR UPDATE" if tx.postgres else ""
            row = tx.fetchone("SELECT state,http_status FROM public_trial_calls WHERE id=?" + lock, (call_id,))
            if not row:
                raise RuntimeError("physical call missing")
            if row["state"] == "dispatched":
                tx.execute("UPDATE public_trial_calls SET state=?,http_status=? WHERE id=? AND state='dispatched'",
                           (expected, status, call_id))
            elif row["state"] != expected or row["http_status"] != status:
                raise RuntimeError("physical call terminal conflict")
            result = tx.fetchone("SELECT state,http_status FROM public_trial_calls WHERE id=?", (call_id,))
            if not result or result["state"] != expected or result["http_status"] != status:
                raise RuntimeError("physical call result not persisted")
    except Exception:
        raise TrialProviderStopped("PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN") from None
    ticket = _model_lease.get()
    if ticket is not None and ticket.call_id == call_id and not not_dispatched:
        ticket.progress = True


def _reserve_with_wait(request):
    # Fair admission has already completed; DB contention is not a queue timer.
    try:
        return _reserve(request)
    except _SlotsBusy:
        raise TrialProviderStopped("MODEL_ADMISSION_UNRECONCILED") from None
    except TrialProviderStopped:
        raise
    except Exception:
        raise TrialProviderStopped("PUBLIC_TRIAL_RESERVATION_UNKNOWN") from None


def _reserve_claude_once(request, body):
    """Use the original Gateway operation identity; no payload is persisted."""
    import billing
    import claude_gateway_protocol as protocol
    if (request.model not in protocol.ALLOWED_MODELS
            or not protocol.valid_operation_id(request.operation_id)
            or type(request.max_tokens) is not int or not 1 <= request.max_tokens <= 32768
            or len(body) > 8 * 1024 * 1024):
        raise TrialProviderStopped("PUBLIC_MODEL_REQUEST_OUT_OF_SCOPE")
    price = billing._pricing_snapshot("claude", request.model)
    if price["pricing_status"] != "exact":
        raise TrialProviderStopped("PUBLIC_MODEL_PRICE_CONFIGURATION_INVALID")
    # Estimate against text bytes (including message overhead) and a context
    # allowance, at the highest cache-write price. Not a claimed supplier bill,
    # quality switch, input truncation or monetary admission cap.
    input_rate = max(price[k] or 0 for k in ("input", "cache_write_5m", "cache_write_1h"))
    reserve = math.ceil((max(200000, len(body)) * input_rate + request.max_tokens * price["output"])
                        * price["usd_cny"] / 1000)
    return _reserve_payload({"model": request.model, "max_tokens": request.max_tokens, "modality": "text",
                             "operation_id": request.operation_id}, reserve,
                            call_id=request.operation_id, require_metered=True,
                            provenance=request.call_state.get("provenance"))


def admit_claude_sync(request, body):
    if not enabled():
        return
    try:
        request.call_state["id"] = _reserve_claude_once(request, body)
    except _SlotsBusy:
        raise TrialProviderStopped("MODEL_ADMISSION_UNRECONCILED") from None
    except TrialProviderStopped:
        raise
    except Exception:
        raise TrialProviderStopped("PUBLIC_TRIAL_RESERVATION_UNKNOWN") from None


async def admit_claude(request, body):
    if not enabled():
        return
    # Only this short reservation transaction runs in a thread. A queued user
    # never occupies a worker, and cancellation cannot orphan a reservation.
    attempt = asyncio.create_task(asyncio.to_thread(_reserve_claude_once, request, body))
    try:
        request.call_state["id"] = await asyncio.shield(attempt)
    except asyncio.CancelledError:
        while not attempt.done():
            try:
                await asyncio.shield(attempt)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            call_id = attempt.result()
        except _SlotsBusy:
            pass
        except TrialProviderStopped:
            raise
        except Exception:
            raise TrialProviderStopped("PUBLIC_TRIAL_RESERVATION_UNKNOWN") from None
        else:
            request.call_state["id"] = call_id
            _record_response(call_id, None, not_dispatched=True)
            request.call_state["finalized"] = True
        raise
    except _SlotsBusy:
        raise TrialProviderStopped("MODEL_ADMISSION_UNRECONCILED") from None
    except TrialProviderStopped:
        raise
    except Exception:
        raise TrialProviderStopped("PUBLIC_TRIAL_RESERVATION_UNKNOWN") from None


class _TerminalParser:
    def __init__(self, ticket=None):
        self.ticket = ticket
        self.pending = b""
        self.done = False
        self.content_seen = False
        self.finish_reason = None
        self.usage = None
        self.model = None

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
                usage = value.get("usage")
                activity = (isinstance(usage, dict) and all(
                    type(usage.get(key)) is int and usage[key] >= 0
                    for key in ("prompt_tokens", "completion_tokens")))
                if isinstance(usage, dict):
                    self.usage = usage
                if isinstance(value.get("model"), str):
                    self.model = value["model"]
                for choice in value.get("choices", []):
                    content = choice.get("delta", {}).get("content")
                    if isinstance(content, str) and content:
                        self.content_seen = True
                        activity = activity or bool(content.strip())
                    if choice.get("finish_reason"):
                        self.finish_reason = choice["finish_reason"]
                if activity:
                    note_model_activity(self.ticket)
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


def _kimi_operation_id(request):
    operation_id = request.extensions.get("noteai_operation_id")
    if operation_id is None or operation_id == "":
        operation_id = str(uuid.uuid4())
        request.extensions["noteai_operation_id"] = operation_id
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", operation_id):
        raise TrialProviderStopped("PUBLIC_MODEL_REQUEST_OUT_OF_SCOPE")
    return operation_id


def _kimi_settlement_deadline(request, client_timeout):
    # Normal execution retains HTTPX's original phase/read timeouts. Only a
    # cancelled/closed consumer gets this finite drain ceiling; no fresh retry.
    timeout = request.extensions.get("timeout", client_timeout)
    values = [timeout.get(name) for name in ("connect", "read", "write", "pool")]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values):
        raise TrialProviderStopped("PUBLIC_MODEL_HTTP_TIMEOUT_UNBOUNDED")
    return time.monotonic() + sum(values)


async def _kimi_settle_awaitable(awaitable, deadline, cancelled):
    task = asyncio.ensure_future(awaitable)
    if not cancelled:
        try:
            await asyncio.wait((task,))
            return task.result()
        except asyncio.CancelledError as exc:
            if task.done() and not asyncio.current_task().cancelling():
                raise
            cancelled["exception"] = exc
    # Once cancellation starts, each read shares the original finite ceiling;
    # receiving another chunk cannot grant a new drain window.
    while not task.done():
        remaining = max(0.0, deadline - time.monotonic())
        if not remaining:
            task.cancel()
            break
        try:
            await asyncio.wait((task,), timeout=remaining)
        except asyncio.CancelledError:
            continue
    try:
        return await task
    except BaseException:
        raise cancelled["exception"]


async def _kimi_reserve_async(request):
    attempt = asyncio.create_task(asyncio.to_thread(_reserve_with_wait, request))
    try:
        return await asyncio.shield(attempt)
    except asyncio.CancelledError:
        while not attempt.done():
            try:
                await asyncio.shield(attempt)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            call_id = attempt.result()
        except TrialProviderStopped:
            raise
        except Exception:
            raise TrialProviderStopped("PUBLIC_TRIAL_RESERVATION_UNKNOWN") from None
        else:
            _record_response(call_id, None, not_dispatched=True)
        raise


def _meter_cancelled_kimi(model, usage, call_id):
    # Normal callers retain their existing accounting. Only cancellation/early
    # close, which prevents the caller's parser from finishing, settles here.
    import model_router
    model_router._record_kimi_usage(model, usage, physical_call_id=call_id)


class _TrackedStream(httpx.SyncByteStream):
    def __init__(self, stream, call_id, status, *, model=MODEL, ticket=None, deadline=None):
        self.stream, self.call_id, self.status = stream, call_id, status
        self.parser = _TerminalParser(ticket=ticket)
        self.iterator = iter(stream)
        self.model, self.ticket, self.deadline = model, ticket, deadline
        self.finalized = False

    def __iter__(self):
        try:
            for chunk in self.iterator:
                self.parser.feed(chunk)
                yield chunk
            self.parser.finish()
        except Exception:
            raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_UNKNOWN") from None

    def close(self):
        if self.finalized:
            return
        self.finalized = True
        interrupted = not self.parser.done
        try:
            if interrupted:
                for chunk in self.iterator:
                    if self.deadline is not None and time.monotonic() >= self.deadline:
                        raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_UNKNOWN")
                    self.parser.feed(chunk)
                self.parser.finish()
        finally:
            try:
                self.stream.close()
            finally:
                try:
                    if interrupted:
                        _meter_cancelled_kimi(self.parser.model or self.model, self.parser.usage, self.call_id)
                finally:
                    try:
                        _record_response(self.call_id, self.status if self.parser.done else None)
                        if self.ticket is not None:
                            self.ticket.progress = True
                    finally:
                        if self.ticket is not None:
                            import model_admission
                            model_admission.current().calls.release(self.ticket)


class _TrackedAsyncStream(httpx.AsyncByteStream):
    def __init__(self, stream, call_id, status, *, model=MODEL, ticket=None, deadline=None):
        self.stream, self.call_id, self.status = stream, call_id, status
        self.parser = _TerminalParser(ticket=ticket)
        self.iterator = stream.__aiter__()
        self.model, self.ticket, self.deadline = model, ticket, deadline
        self.cancelled = {}
        self.finalized = False

    async def __aiter__(self):
        try:
            while True:
                try:
                    chunk = await _kimi_settle_awaitable(
                        self.iterator.__anext__(), self.deadline, self.cancelled)
                except StopAsyncIteration:
                    break
                self.parser.feed(chunk)
                if not self.cancelled:
                    yield chunk
            self.parser.finish()
            if self.cancelled:
                raise self.cancelled["exception"]
        except asyncio.CancelledError:
            raise
        except Exception:
            raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_UNKNOWN") from None

    async def aclose(self):
        if self.finalized:
            return
        self.finalized = True
        interrupted = bool(self.cancelled) or not self.parser.done
        try:
            if not self.parser.done:
                while True:
                    if self.deadline is not None and time.monotonic() >= self.deadline:
                        raise TrialProviderStopped("PUBLIC_TRIAL_STREAM_UNKNOWN")
                    try:
                        chunk = await _kimi_settle_awaitable(
                            self.iterator.__anext__(), self.deadline, self.cancelled)
                    except StopAsyncIteration:
                        break
                    self.parser.feed(chunk)
                self.parser.finish()
        except BaseException:
            if not self.cancelled:
                raise
        finally:
            try:
                await self.stream.aclose()
            finally:
                try:
                    if interrupted:
                        _meter_cancelled_kimi(self.parser.model or self.model, self.parser.usage, self.call_id)
                finally:
                    try:
                        # This short terminal transaction must complete before
                        # releasing the physical permit to the next request.
                        _record_response(self.call_id, self.status if self.parser.done else None)
                        if self.ticket is not None:
                            self.ticket.progress = True
                    finally:
                        if self.ticket is not None:
                            import model_admission
                            model_admission.current().calls.release(self.ticket)

        if self.cancelled:
            raise self.cancelled["exception"]


class _KimiClient(httpx.Client):
    def send(self, request, **kwargs):
        operation_id = _kimi_operation_id(request)
        own_ticket = _model_lease.get() is None
        with model_admission_sync(operation_id, "kimi") as ticket:
            deadline = _kimi_settlement_deadline(request, self.timeout.as_dict())
            call_id = _reserve_with_wait(request)
            mark_model_dispatched(operation_id)
            try:
                response = super().send(request, **kwargs)
            except BaseException:
                _record_response(call_id, None)
                raise TrialProviderStopped("PUBLIC_TRIAL_TRANSPORT_UNKNOWN") from None
            response.extensions["noteai_call_id"] = call_id
            if kwargs.get("stream") and response.status_code == 200 and response.is_closed:
                parser = _TerminalParser()
                try:
                    parser.feed(response.content)
                    parser.finish()
                finally:
                    _record_response(call_id, response.status_code if parser.done else None)
            elif kwargs.get("stream") and response.status_code == 200:
                if own_ticket:
                    ticket.held_by_stream = True
                response.stream = _TrackedStream(response.stream, call_id, response.status_code,
                    model=MODEL, ticket=ticket if own_ticket else None, deadline=deadline)
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
        operation_id = _kimi_operation_id(request)
        own_ticket = _model_lease.get() is None
        async with model_admission(operation_id, "kimi") as ticket:
            deadline = _kimi_settlement_deadline(request, self.timeout.as_dict())
            call_id = await _kimi_reserve_async(request)
            mark_model_dispatched(operation_id)
            cancelled = {}
            try:
                response = await _kimi_settle_awaitable(super().send(request, **kwargs), deadline, cancelled)
            except BaseException:
                try:
                    if cancelled:
                        _meter_cancelled_kimi(MODEL, None, call_id)
                finally:
                    _record_response(call_id, None)
                if cancelled:
                    raise cancelled["exception"]
                raise TrialProviderStopped("PUBLIC_TRIAL_TRANSPORT_UNKNOWN") from None
            response.extensions["noteai_call_id"] = call_id
            if kwargs.get("stream") and response.status_code == 200 and response.is_closed:
                parser = _TerminalParser()
                try:
                    parser.feed(response.content)
                    parser.finish()
                finally:
                    try:
                        if cancelled:
                            _meter_cancelled_kimi(parser.model or MODEL, parser.usage, call_id)
                    finally:
                        _record_response(call_id, response.status_code if parser.done else None)
            elif kwargs.get("stream") and response.status_code == 200:
                if own_ticket:
                    ticket.held_by_stream = True
                response.stream = _TrackedAsyncStream(response.stream, call_id, response.status_code,
                    model=MODEL, ticket=ticket if own_ticket else None, deadline=deadline)
                if cancelled:
                    response.stream.cancelled.update(cancelled)
                    await response.aclose()
            else:
                try:
                    _validate_response(response)
                except TrialProviderStopped:
                    try:
                        if cancelled:
                            try:
                                value = response.json()
                            except ValueError:
                                value = None
                            usage = value.get("usage") if isinstance(value, dict) else None
                            if response.status_code == 200 or (isinstance(usage, dict) and usage):
                                _meter_cancelled_kimi(
                                    (value.get("model") or MODEL) if isinstance(value, dict) else MODEL,
                                    usage, call_id)
                    finally:
                        _record_response(call_id, response.status_code, unknown=response.status_code == 200)
                        await response.aclose()
                    if cancelled:
                        raise cancelled["exception"]
                    raise
                try:
                    if cancelled:
                        value = response.json()
                        _meter_cancelled_kimi(value.get("model") or MODEL, value.get("usage"), call_id)
                finally:
                    _record_response(call_id, response.status_code)
            if cancelled:
                raise cancelled["exception"]
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
