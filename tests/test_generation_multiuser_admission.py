"""Offline ten-user/nine-image shared-admission and generation scenarios.

All supplier HTTP below is httpx.MockTransport.  The real public Invocation,
shared SQLite admission/accounting, endpoint/SSE/save path and image batch run.
Content/quality predictions are deterministic fixtures, not model acceptance.
The slow-progress regression exercises the new shared admission API. The prior
exact current-behavior run remains in the immutable offline evidence directory.
"""
import asyncio
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx
from PIL import Image

MODEL = Path(__file__).resolve().parents[1] / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))
api = importlib.import_module("api")
ark = importlib.import_module("ark_media")
db = importlib.import_module("db")
billing = importlib.import_module("billing")
public = importlib.import_module("public_product")
admission = importlib.import_module("model_admission")


class _AdmissionClock:
    """Virtual admission time only; real asyncio/SQLite/HTTP clocks stay intact."""
    def __init__(self):
        self.now = 0.0
        self.waiters = set()
        self.changed = threading.Condition()

    def monotonic(self):
        with self.changed:
            return self.now

    def sleep(self, _seconds):
        with self.changed:
            self.waiters.add(threading.get_ident())
            self.changed.notify_all()
        time.sleep(.001)  # Yield real threads, but never silently advance time.

    def advance(self, seconds):
        with self.changed:
            self.now += seconds
            self.changed.notify_all()

    def wait_for_waiters(self, count):
        with self.changed:
            return self.changed.wait_for(lambda: len(self.waiters) >= count, 8)


class GenerationMultiuserAdmissionTests(unittest.TestCase):
    USERS = tuple("mock-generation-user-%02d" % i for i in range(10))

    def test_ten_users_complete_full_mock_chain_with_nine_images_once_each(self):
        result = self._scenario()
        self.assertEqual(result["completed"], 10)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["ark_calls"], 90)
        self.assertEqual(set(result["first_service_order"]), set(self.USERS))
        # Eventual service in this finite fixture is not a FIFO fairness proof.
        self.assertEqual(result["unknown"], 0)

    def test_ten_slow_progress_users_wait_fairly_and_complete_beyond_old_90s(self):
        result = self._scenario(mode="slow_progress")
        self.assertEqual(result["completed"], 10)
        self.assertEqual(result["failed"], 0)
        self.assertGreater(result["completed_before_90"], 0)
        self.assertEqual(result["busy_stops"], 0)
        self.assertEqual(result["unknown"], 0)
        self.assertEqual(result["dispatched_after_join"], 0)

    def test_no_progress_does_not_reclaim_dispatched_or_forge_http_timeout(self):
        result = self._scenario(mode="no_progress")
        self.assertEqual(result["busy_stops"], 0)
        self.assertEqual(result["completed"], 10)
        self.assertEqual(result["completed_before_90"], 0)
        self.assertEqual(result["held_dispatched_before_release"], 2)
        self.assertEqual(result["unknown"], 0)
        self.assertEqual(result["http_timeouts"], 0)

    def test_one_user_http_timeout_keeps_unknown_and_other_users_complete(self):
        result = self._scenario(mode="http_timeout")
        self.assertEqual(result["http_timeouts"], 1)
        self.assertEqual(result["unknown"], 1)
        self.assertEqual(result["completed"], 9)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["dispatched_after_join"], 0)

    def test_failed_user_joins_dispatched_calls_and_does_not_poison_other_users(self):
        result = self._scenario(mode="http_failure")
        self.assertEqual(result["completed"], 9)
        self.assertEqual(result["failed"], 1)
        self.assertLessEqual(result["failed_user_started_images"], 2)
        self.assertGreaterEqual(result["failed_user_started_images"], 1)
        self.assertEqual(result["unknown"], 0)
        self.assertEqual(result["dispatched_after_join"], 0)

    def test_cancelled_user_joins_dispatched_calls_without_starting_queued_images(self):
        result = self._scenario(mode="cancel")
        self.assertEqual(result["completed"], 9)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["cancelled"], 1)
        self.assertLessEqual(result["failed_user_started_images"], 2)
        self.assertGreaterEqual(result["failed_user_started_images"], 1)
        self.assertEqual(result["unknown"], 0)
        self.assertEqual(result["dispatched_after_join"], 0)

    def test_asgi_test_config_cap2_rejects_eight_early_without_charging(self):
        # Test-only capacity2, never a claim that production has two user seats.
        result = self._scenario(mode="asgi_testcap2", asgi=True)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["asgi_status_counts"], {200: 2, 429: 8})
        self.assertEqual(result["rejected_users_without_usage_or_charge"], 8)
        self.assertEqual(result["unknown"], 0)

    def test_asgi_test_config10_completes_ten_nine_image_full_chains(self):
        result = self._scenario(mode="asgi_testcap10", asgi=True)
        self.assertEqual(result["asgi_status_counts"], {200: 10})
        self.assertEqual(result["completed"], 10)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["ark_calls"], 90)
        self.assertEqual(set(result["first_service_order"]), set(self.USERS))
        self.assertEqual(result["busy_stops"], 0)
        self.assertEqual(result["unknown"], 0)

    def test_same_request_id_cross_paid_route_rejects_before_charge_but_same_route_uses_idempotency(self):
        """Normal bearer boundary and real claim ledger; no model fixture needed."""
        import auth
        import idempotency
        import public_account
        from starlette.responses import JSONResponse

        async def run(boundary, owner, token, manager):
            entered, release = asyncio.Event(), asyncio.Event()
            seen = []
            claims = []
            request_id = "mock-cross-paid-route-original"

            async def app(scope, receive, send):
                current = public._invocation.get()
                self.assertEqual(current.user_id, owner)
                operation = "generate" if scope["path"] == "/generate/stream" else "analyze"
                claim = idempotency.claim_and_charge(user_id=owner, operation=operation,
                    request_id=current.request_id, payload={"synthetic": "same body"})
                seen.append((scope["path"], claim["state"]))
                if claim["state"] == "owner":
                    claims.append(claim)
                    entered.set()
                    await release.wait()
                    self.assertTrue(idempotency.mark_completed(claim))
                    response = JSONResponse({"state": "MOCK_COMPLETED"})
                else:
                    response = JSONResponse({"state": claim["state"]}, status_code=409)
                await response(scope, receive, send)

            boundary.app = app
            headers = {"Origin": "https://noteaipro.com", "Authorization": "Bearer " + token,
                       "X-Request-ID": request_id}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=boundary), base_url="http://synthetic") as client:
                first = asyncio.create_task(client.post("/generate/stream", json={}, headers=headers))
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                    original_operation = next(iter(manager.operations.values()))
                    original_credit = dict(db.fetchone("SELECT * FROM credits WHERE user_id=?", (owner,)))
                    wrong_route = await client.post("/analyze/stream", json={}, headers=headers)
                    self.assertEqual(wrong_route.status_code, 429)
                    self.assertEqual(wrong_route.json()["detail"]["code"], "MODEL_USER_OPERATION_BUSY")
                    self.assertEqual(seen, [("/generate/stream", "owner")], "cross-route conflict must never enter its paid handler")
                    same_route = await client.post("/generate/stream", json={}, headers=headers)
                    self.assertEqual(same_route.status_code, 409)
                    self.assertEqual(same_route.json()["state"], "in_progress")
                    self.assertEqual(seen, [("/generate/stream", "owner"), ("/generate/stream", "in_progress")])
                    self.assertIs(next(iter(manager.operations.values())), original_operation)
                    self.assertFalse(original_operation.cancelled.is_set(), "duplicate request cannot finish/cancel its original owner")
                    self.assertEqual(dict(db.fetchone("SELECT * FROM credits WHERE user_id=?", (owner,))), original_credit)
                    self.assertEqual(db.fetchone("SELECT count(*) n FROM usage_records WHERE user_id=?", (owner,))["n"], 1)
                    self.assertEqual(db.fetchone("SELECT count(*) n FROM idempotency_requests WHERE user_id=?", (owner,))["n"], 1)
                    self.assertEqual(db.fetchone("SELECT count(*) n FROM idempotency_requests WHERE user_id=? AND operation='analyze'", (owner,))["n"], 0)
                finally:
                    release.set()
                    result = await asyncio.wait_for(first, 3)
                self.assertEqual(result.status_code, 200)
            self.assertEqual(len(claims), 1)
            row = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (claims[0]["request_id"],)))
            self.assertEqual((row["status"], row["charge_applied"], row["complete_applied"], row["refund_applied"]), ("completed", 1, 1, 0))
            self.assertEqual(row["credits_used"], 8)
            self.assertEqual(db.fetchone("SELECT count(*) n FROM public_trial_calls")["n"], 0)
            self.assertEqual(manager.operations, {})
            self.assertEqual(manager.aliases, {})

        old_path = db._DB_PATH
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.dict(os.environ, {"DATABASE_URL": "", "NOTEAI_PUBLIC_PRODUCT": "1",
                 "NOTEAI_MODEL_CONFIG_ENABLED": "0", "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com"}):
            try:
                db._DB_PATH = Path(directory) / "cross-paid-route.sqlite"
                db.init_db()
                user = auth.create_user("cross-route-fixture", "SyntheticPassword!42", phone="+8613800990002",
                    phone_verified=True, contract_version=public.CONTRACT_VERSION, privacy_accepted=True,
                    cross_border_notice_acknowledged=True)
                token = auth.create_token(user["id"])
                manager = admission.Admission(admission.Limits(operations=10, operations_per_user=1))
                with mock.patch.object(admission, "_instance", manager):
                    asyncio.run(run(public_account.PublicAccountBoundary(None), user["id"], token, manager))
            finally:
                billing.clear_active_usage()
                db._DB_PATH = old_path

    def _scenario(self, mode="fast", *, asgi=False):
        clock = _AdmissionClock()
        lock = threading.Condition()
        release_all = threading.Event()
        first_pair_release = threading.Event()
        started, returned, active, maximum = [], [], 0, 0
        image_jobs = {uid: [] for uid in self.USERS}
        observations = {uid: [] for uid in self.USERS}
        expert_inputs = {uid: [] for uid in self.USERS}
        events, errors, invocations, responses, tokens = {}, {}, {}, {}, {}
        provider_stops = {uid: [] for uid in self.USERS}
        failed_user = None
        http_timeouts = 0
        deadline_after_permit_checks = []
        ark_timeout_after_permit_checks = []
        completed_before_90 = 0
        held_dispatched_before_release = 0
        pixels = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(pixels, "PNG")
        real_vision = api._kimi_vision_understand
        real_ark_client = ark._client
        real_gateway_deadline = api._mr._gateway_absolute_deadline
        manager = admission.Admission(admission.Limits(physical=2, claude=2, kimi=2, doubao=2,
            media_workers=2, operations=2 if mode == "asgi_testcap2" else 10, operations_per_user=1, pending_calls=64,
            # Fast HTTPX fixtures exercise task fairness/settlement. Actual
            # 30-RPM waiting is separately checked with a controlled clock.
            claude_rpm=6000, queue_seconds=900, no_progress_seconds=300)) if admission is not None else None
        real_async_sleep = asyncio.sleep
        config = {"active": {task: {"model": api._mr.CLAUDE_SONNET if task == "arbitrate" else api._mr.CLAUDE_HAIKU,
                                    "enabled": True, "max_tokens": 16000}
                             for task in api._mr._runtime_config.TASKS}}

        async def quick_sleep(_seconds):
            await real_async_sleep(.001)

        def observed_vision(image, *args):
            uid = public._invocation.get().user_id
            with lock:
                image_jobs[uid].append(image)
            try:
                value = real_vision(image, *args) + " " + image
            except public.TrialProviderStopped as exc:
                with lock:
                    provider_stops[uid].append(str(exc))
                raise
            with lock:
                observations[uid].append(image)
            return value

        def enter_wire(kind):
            nonlocal active, maximum, failed_user
            uid = public._invocation.get().user_id
            with lock:
                active += 1
                maximum = max(maximum, active)
                started.append((uid, kind))
                ordinal = len(started)
                if ordinal == 1:
                    failed_user = uid
                lock.notify_all()
            # The unchanged real public shared gate must already own this slot.
            count = db.fetchone("SELECT count(*) n FROM public_trial_calls WHERE state='dispatched'")["n"]
            self.assertLessEqual(count, 2)
            return uid, ordinal

        def leave_wire(uid, kind):
            nonlocal active
            with lock:
                active -= 1
                returned.append((uid, kind, clock.monotonic()))
                lock.notify_all()

        def supplier(request):
            nonlocal http_timeouts
            uid, ordinal = enter_wire("ark")
            try:
                if mode in {"slow_progress", "no_progress", "cancel", "http_failure", "http_timeout", "asgi_testcap2", "asgi_testcap10"}:
                    gate = first_pair_release if ordinal <= 2 else release_all
                    self.assertTrue(gate.wait(15), "MOCK wire was not released")
                else:
                    time.sleep(.002)
                if ordinal == 1 and mode == "http_timeout":
                    http_timeouts += 1
                    raise httpx.ReadTimeout("synthetic read timeout", request=request)
                if ordinal == 1 and mode == "http_failure":
                    return httpx.Response(502, json={"error": "synthetic rejection"})
                return httpx.Response(200, json={"model": ark.MODEL,
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                              "prompt_tokens_details": {"cached_tokens": 0}},
                    "choices": [{"finish_reason": "stop", "message": {"content": "画面有庭院、木桥、屏风和白色座椅，所有可见素材保留。"}}]})
            finally:
                leave_wire(uid, "ark")

        def gateway_deadline_after_permit(*args, **kwargs):
            if manager is not None:
                ticket = public._model_lease.get()
                self.assertIsNotNone(ticket, "Gateway business deadline must start after its physical permit")
                self.assertTrue(ticket.granted and not ticket.closed and not ticket.dispatched)
                deadline_after_permit_checks.append(ticket.call_id)
            return real_gateway_deadline(*args, **kwargs)

        def ark_client(**_kwargs):
            if manager is not None:
                ticket = public._model_lease.get()
                self.assertIsNotNone(ticket, "Ark HTTP client must start after its physical permit")
                self.assertEqual(ticket.provider, "doubao")
                self.assertTrue(ticket.granted and not ticket.closed)
                ark_timeout_after_permit_checks.append(ticket.call_id)
            client = real_ark_client(transport=httpx.MockTransport(supplier))
            self.assertEqual(client.timeout.read, 240)
            self.assertEqual(client.timeout.connect, 10)
            return client

        def model_text(uid):
            number = uid.rsplit("-", 1)[1]
            title = "合成用户" + number + "九图场景整理与选择"
            body = ("画面保留庭院、木桥、屏风和白色座椅。先看各张图片的构图，再对比光线与材质。" * 7
                    + "哪些场景更适合你的内容方向？#休闲娱乐 #素材整理 #庭院 #构图 #场景")
            return ("<image_desc>保留九张素材</image_desc><inspiration>按画面整理</inspiration>"
                    "<title>" + title + "</title><body>" + body + "</body>"
                    "<variants>九图可见场景整理与素材选择\n庭院屏风九图素材整理参考\n从九图画面寻找构图与光线</variants>"
                    "<keyword_tip>九图素材</keyword_tip><tag_recommendation>休闲娱乐</tag_recommendation>"
                    "<user_angle>按真实画面选择</user_angle><hook>整理可见素材</hook>"
                    "<clarifications>[]</clarifications><rationale>合成并发测试</rationale>")

        async def gateway(request):
            uid, _ordinal = enter_wire("claude")
            try:
                body = json.loads(request.content)
                row = db.fetchone("SELECT provenance_json FROM public_trial_calls WHERE id=?", (body["operation_id"],))
                step = json.loads(row["provenance_json"]).get("step")
                if step in {"generation_content", "generation_growth", "generation_user"}:
                    content = body["messages"][-1]["content"]
                    own = [uid + "/image-%d" % i for i in range(9)]
                    self.assertTrue(all(image in content for image in own), (step, uid))
                    self.assertEqual(sorted(content.index(image) for image in own), [content.index(image) for image in own])
                    self.assertFalse(any(other + "/image-" in content for other in self.USERS if other != uid))
                    expert_inputs[uid].append(step)
                await real_async_sleep(.002)
                usage = {"input_tokens": 100, "output_tokens": 30, "cache_read_input_tokens": 0,
                         "cache_creation_input_tokens": 0}
                raw = model_text(uid)
                base = {"protocol_version": api._mr._cgp.PROTOCOL_VERSION}
                if request.url.path == api._mr._cgp.STREAM_PATH:
                    lines = [{**base, "type": "content", "text": raw},
                             {**base, "type": "usage", "usage": usage, "model": body["model"], "stop_reason": "end_turn"},
                             {**base, "type": "done"}]
                    return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines) + "\n",
                                          headers={"content-type": "application/x-ndjson"})
                return httpx.Response(200, json={**base, "text_blocks": [raw], "usage": usage,
                                                 "model": body["model"], "stop_reason": "end_turn"})
            finally:
                leave_wire(uid, "claude")

        async def consume(uid):
            invocation = public.Invocation(uid, "mock-ten-nine-" + uid, model_config=config, route="/generate/stream")
            # Only direct-call tests bind this context. ASGI obtains its own
            # Invocation from real bearer authentication/public middleware.
            token = None if asgi else public._invocation.set(invocation)
            if not asgi:
                invocations[uid] = invocation
            request = api.GenerateInput(
                domain="休闲娱乐体验", cover_images=[uid + "/image-%d" % i for i in range(9)],
                brief=None, local_time="2026101712", merchant_name="本地合成测试场景", persist_result=True,
                content_intent="seeding", merchant_visibility="show", fact_source_policy="skip")
            try:
                if asgi:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://synthetic") as client:
                        response = await client.post("/generate/stream", json=request.model_dump(), headers={
                            "Origin": "https://noteaipro.com", "Authorization": "Bearer " + tokens[uid],
                            "X-Request-ID": "mock-ten-nine-" + uid})
                    responses[uid] = response
                    if response.status_code == 429:
                        self.assertTrue(response.json().get("detail"), "busy rejection needs a public explanation")
                        events[uid] = []
                        return
                    self.assertEqual(response.status_code, 200)
                    chunks = [response.text]
                else:
                    response = await api.generate_stream_endpoint(request, {"id": uid}, "mock-ten-nine-" + uid, None)
                    chunks = [chunk async for chunk in response.body_iterator]
                events[uid] = []
                for chunk in chunks:
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode()
                    for part in chunk.split("\n\n"):
                        if part.startswith("data: "):
                            events[uid].append(json.loads(part[6:]))
            except BaseException as exc:
                errors[uid] = exc
            finally:
                if token is not None:
                    public._invocation.reset(token)
                billing.clear_active_usage()

        async def wait_until(predicate, label):
            # Never queue the test driver behind the media thread-pool jobs.
            for _ in range(1600):
                if predicate():
                    return
                await real_async_sleep(.005)
            self.fail("MOCK control did not reach " + label)

        async def run():
            nonlocal completed_before_90, held_dispatched_before_release
            tasks = {uid: asyncio.create_task(consume(uid)) for uid in self.USERS}
            try:
                if mode != "fast":
                    await wait_until(lambda: len(started) >= 2, "two dispatched calls")
                    if mode == "asgi_testcap2":
                        await wait_until(lambda: sum(r.status_code == 429 for r in responses.values()) == 8, "eight early ASGI busy/nocharge rejections")
                    elif mode == "asgi_testcap10":
                        await wait_until(lambda: len(manager.operations) == 10, "ten authenticated operations admitted before physical release")
                    else:
                        await wait_until(lambda: (len(manager.media._tickets()) + len(manager.calls._tickets()) >= 2)
                            if manager is not None else len(clock.waiters) >= 2, "cross-user admission waiters")
                    if mode == "slow_progress":
                        clock.advance(45)
                        first_pair_release.set()
                        await wait_until(lambda: len(started) >= 4, "supplier progress and next pair")
                        completed_before_90 = len(returned)
                        clock.advance(46)
                        # Let all original blocked admissions observe the same
                        # deterministic >90s time while a new pair is in flight.
                        for _ in range(100):
                            if any("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED" in values for values in provider_stops.values()):
                                break
                            await real_async_sleep(.005)
                    elif mode == "no_progress":
                        clock.advance(91)
                        for _ in range(100):
                            if any("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED" in values for values in provider_stops.values()):
                                break
                            await real_async_sleep(.005)
                        held_dispatched_before_release = db.fetchone("SELECT count(*) n FROM public_trial_calls WHERE state='dispatched'")["n"]
                    elif mode == "cancel":
                        tasks[failed_user].cancel()
                        await real_async_sleep(.02)
                        self.assertFalse(tasks[failed_user].done(), "dispatched Ark must join before cancellation settles")
                        self.assertEqual(db.fetchone("SELECT count(*) n FROM public_trial_calls WHERE state='dispatched'")["n"], 2)
            finally:
                first_pair_release.set()
                release_all.set()
                await asyncio.wait_for(asyncio.gather(*tasks.values()), 30)

        old_path = db._DB_PATH
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"DATABASE_URL": "", "NOTEAI_PUBLIC_PRODUCT": "1",
                "NOTEAI_ARK_API_KEY": "synthetic-only", "NOTEAI_TASK_CLARIFICATION_ENABLED": "1",
                "NOTEAI_MODEL_CONFIG_ENABLED": "1", "NOTEAI_FACT_SEARCH": "0", "NOTEAI_CLAUDE_TRANSPORT": "gateway",
                "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "mock-config", "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "mock-key",
                "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com"}))
            db._DB_PATH = Path(temporary) / "ten-users.sqlite"
            stack.callback(setattr, db, "_DB_PATH", old_path)
            stack.callback(billing.clear_active_usage)
            db.init_db()
            for uid in self.USERS:
                db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)",
                           (uid, uid, uid + "@example.invalid", "synthetic", "synthetic", "2026-10-17T00:00:00+00:00"))
            if asgi:
                for index, uid in enumerate(self.USERS):
                    db.execute("UPDATE users SET phone=?,phone_verified_at=? WHERE id=?",
                               ("+86138000000%02d" % index, "2026-10-17T00:00:00+00:00", uid))
                    db.execute("INSERT INTO user_contract_acceptances(user_id,contract_version,privacy_accepted_at,cross_border_notice_acknowledged_at,source) VALUES(?,?,?,?,?)",
                               (uid, public.CONTRACT_VERSION, "2026-10-17T00:00:00+00:00", "", "registration"))
                    tokens[uid] = api._auth.create_token(uid)
                # Readiness fixture only: real bearer/consent authentication is
                # not patched. No storage or supplier call config is installed.
                stack.enter_context(mock.patch.object(public, "image_enabled", return_value=True))
            db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
            if manager is not None:
                stack.enter_context(mock.patch.object(admission, "_instance", manager))
                stack.enter_context(mock.patch.object(admission, "time", clock))
            stack.enter_context(mock.patch.object(ark, "time", clock))
            stack.enter_context(mock.patch.object(public, "time", clock))
            stack.enter_context(mock.patch.object(ark, "_client", side_effect=ark_client))
            stack.enter_context(mock.patch.object(api, "_read_image_input", return_value=pixels.getvalue()))
            stack.enter_context(mock.patch.object(api, "_kimi_vision_understand", side_effect=observed_vision))
            stack.enter_context(mock.patch.object(api, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": quick_sleep})))
            stack.enter_context(mock.patch.object(public, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": quick_sleep})))
            transport = api._mr.GatewayClaudeTransport(base_url="https://gateway.example.invalid", key_id="synthetic-key",
                secret="synthetic-secret-only", http_transport=httpx.MockTransport(gateway))
            stack.enter_context(mock.patch.object(api._mr, "get_claude_transport", return_value=transport))
            stack.enter_context(mock.patch.object(api._mr, "_gateway_absolute_deadline", side_effect=gateway_deadline_after_permit))
            stack.enter_context(mock.patch.object(api._mr._runtime_config, "read", return_value=config))
            stack.enter_context(mock.patch.object(api, "_compute_market_timing_for_delivery", return_value=None))
            stack.enter_context(mock.patch.object(api, "_maybe_enrich_facts", new=mock.AsyncMock(return_value={"enabled": False})))
            stack.enter_context(mock.patch.object(api, "_extract_cover", return_value=(None, {})))
            stack.enter_context(mock.patch.object(api._memory, "build_memory_prompt", return_value=""))
            # Local content/quality fixture: concurrency and accounting are real,
            # but these tests do not certify text quality, weights or factuality.
            stack.enter_context(mock.patch.object(api, "_predict", return_value=(85.0, {})))
            stack.enter_context(mock.patch.object(api, "compute_semantic_features", return_value={}))
            stack.enter_context(mock.patch.object(api, "_generated_quality_issues", return_value=[]))
            stack.enter_context(mock.patch.object(api, "_delivery_integrity_issues", return_value=[]))
            stack.enter_context(mock.patch.object(api, "_body_format_issues", return_value=[]))
            stack.enter_context(mock.patch.object(api, "_needs_v04_score_lift", return_value=False))
            stack.enter_context(mock.patch.object(api, "_shape_body_for_delivery", new=mock.AsyncMock(side_effect=lambda _title, body, *_a, **_kw: body)))
            asyncio.run(run())
            if manager is not None:
                self.assertEqual(manager.calls.active, {})
                self.assertEqual(manager.calls._tickets(), [])
                self.assertEqual(manager.media.active, {})
                self.assertEqual(manager.media._tickets(), [])
                self.assertEqual(manager.operations, {})
                self.assertEqual(manager.aliases, {})
            rows = [dict(r) for r in db.fetchall("SELECT user_id,state,http_status,usage_record_id,model_usage_record_id FROM public_trial_calls")]
            claims = [dict(r) for r in db.fetchall("SELECT id,user_id,usage_id,status,charge_applied,complete_applied,refund_applied,credits_used FROM idempotency_requests")]
            self.assertEqual(len(claims), 2 if mode == "asgi_testcap2" else 10)
            self.assertFalse(any(isinstance(e, AssertionError) for e in errors.values()),
                             "MOCK fixture assertion must not be counted as a product failure")
            self.assertTrue(all(r["model_usage_record_id"] for r in rows if r["state"] == "responded" and r["http_status"] == 200))
            self.assertLessEqual(maximum, 2)
            self.assertFalse(any(r["state"] == "dispatched" for r in rows))
            self.assertTrue(all(r["usage_record_id"] == next(c["usage_id"] for c in claims if c["user_id"] == r["user_id"]) for r in rows))
            completed = [c for c in claims if c["status"] == "completed"]
            failed = [c for c in claims if c["status"] == "failed"]
            self.assertEqual(len(completed) + len(failed), 2 if mode == "asgi_testcap2" else 10)
            for claim in claims:
                usage = db.fetchone("SELECT model_calls FROM usage_records WHERE id=? AND user_id=?", (claim["usage_id"], claim["user_id"]))
                self.assertEqual(usage["model_calls"], sum(bool(r["model_usage_record_id"]) for r in rows if r["user_id"] == claim["user_id"]))
                self.assertEqual(claim["charge_applied"], 1)
                self.assertEqual(claim["credits_used"], 8)
                note = db.fetchone("SELECT id FROM notes WHERE user_id=? AND id=?", (claim["user_id"], claim["id"]))
                if claim["status"] == "completed":
                    self.assertEqual((claim["complete_applied"], claim["refund_applied"]), (1, 0))
                    self.assertIsNotNone(note)
                    self.assertCountEqual(image_jobs[claim["user_id"]], [claim["user_id"] + "/image-%d" % i for i in range(9)])
                    self.assertEqual(len(observations[claim["user_id"]]), 9)
                    self.assertEqual(len(expert_inputs[claim["user_id"]]), 3)
                    user_events = events[claim["user_id"]]
                    self.assertTrue(any(e.get("stage") == "p3" for e in user_events))
                    self.assertTrue(any(e.get("stage") == "p4" for e in user_events))
                    self.assertEqual(user_events[-1]["type"], "complete")
                else:
                    self.assertEqual((claim["complete_applied"], claim["refund_applied"]), (0, 1))
                    self.assertIsNone(note)
            rejected_without_charge = 0
            if asgi:
                self.assertFalse(errors, "ASGI fixture errors are not accepted overload results")
                for uid, response in responses.items():
                    if response.status_code == 429:
                        self.assertEqual(db.fetchone("SELECT count(*) n FROM usage_records WHERE user_id=?", (uid,))["n"], 0)
                        self.assertEqual(db.fetchone("SELECT count(*) n FROM idempotency_requests WHERE user_id=?", (uid,))["n"], 0)
                        credit = db.fetchone("SELECT total_used FROM credits WHERE user_id=?", (uid,))
                        self.assertTrue(credit is None or float(credit["total_used"]) == 0)
                        rejected_without_charge += 1
            result = {"MOCK_ONLY": True, "users": 10, "input_images_each": 9, "mode": mode,
                "completed": len(completed), "failed": len(failed), "ark_calls": sum(kind == "ark" for _, kind in started),
                "gateway_calls": sum(kind == "claude" for _, kind in started), "max_physical_inflight": maximum,
                "busy_stops": sum("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED" in values for values in provider_stops.values()),
                "unknown": sum(r["state"] == "unknown" for r in rows), "http_timeouts": http_timeouts,
                "cancelled": sum(isinstance(e, asyncio.CancelledError) for e in errors.values()),
                "dispatched_after_join": sum(r["state"] == "dispatched" for r in rows),
                "completed_before_90": completed_before_90, "held_dispatched_before_release": held_dispatched_before_release,
                "failed_user_started_images": len(image_jobs[failed_user]) if failed_user else 0,
                "first_service_order": list(dict.fromkeys(uid for uid, _ in started)),
                "asgi_status_counts": {code: sum(r.status_code == code for r in responses.values()) for code in sorted({r.status_code for r in responses.values()})},
                "rejected_users_without_usage_or_charge": rejected_without_charge,
                "test_config_capacity2_not_production_user_limit": mode == "asgi_testcap2",
                "test_config_operation_capacity": 2 if mode == "asgi_testcap2" else 10,
                "gateway_business_deadlines_created_after_permit": len(deadline_after_permit_checks),
                "Ark_original_240s_HTTP_clients_created_after_permit": len(ark_timeout_after_permit_checks),
                "default_media_executor_workers": min(32, (os.process_cpu_count() if hasattr(os, "process_cpu_count") else os.cpu_count()) + 4)}
            print("MOCK_TEN_USERS_NINE_IMAGES", json.dumps(result, sort_keys=True))
            return result
