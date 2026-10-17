"""Offline progress/cancel regressions; no provider requests or model calls."""
import asyncio
import contextvars
import hashlib
import importlib
import json
from pathlib import Path
import sys
import threading
import unittest
from contextlib import asynccontextmanager
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
api = importlib.import_module("api")


class LiveGenerationProgressTests(unittest.TestCase):
    def test_heartbeat_keeps_one_generator_context_and_never_advances_work(self):
        context = contextvars.ContextVar("synthetic_stream_context", default="outside")
        calls = []
        status = {"active": True, "state": "queued", "completed_calls": 0,
                  "can_cancel": True, "last_progress_at": None}

        async def source():
            token = context.set("original")
            try:
                yield 'data: {"type":"stage","stage":"p1","progress":10}\n\n'
                await asyncio.sleep(.035)
                calls.append(context.get())
                yield 'data: {"type":"complete","result":"same original"}\n\n'
            finally:
                context.reset(token)

        async def run():
            return [json.loads(chunk[6:]) async for chunk in api._timed_sse_stream(
                source(), operation="generate", success_types={"complete"})]

        with mock.patch.object(api, "_SSE_HEARTBEAT_SECONDS", .005), \
             mock.patch.object(api._public_product, "queue_status", return_value=status, create=True):
            events = asyncio.run(run())
        pulses = [e for e in events if e["type"] == "queue_update"]
        self.assertTrue(pulses)
        self.assertTrue(all(e["work_progress"] is False and "progress" not in e for e in pulses))
        self.assertEqual(calls, ["original"])
        self.assertEqual(context.get(), "outside")
        self.assertEqual(events[-1]["result"], "same original")
        self.assertEqual(sum(e["terminal"] for e in events), 1)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))

    def test_heartbeat_touches_only_an_active_claim_with_actual_provider_progress(self):
        claim = {"request_id": "original-claim"}

        async def run():
            async def source():
                await asyncio.sleep(.018)
                yield 'data: {"type":"complete"}\n\n'
            return [chunk async for chunk in api._timed_sse_stream(
                source(), operation="generate", success_types={"complete"}, claim=claim)]

        for active, progress, expected in ((True, "2026-10-17T04:00:00Z", True),
                                           (True, None, False), (False, "old", False)):
            with self.subTest(active=active, progress=progress), \
                 mock.patch.object(api, "_SSE_HEARTBEAT_SECONDS", .005), \
                 mock.patch.object(api._public_product, "queue_status", return_value={
                     "active": active, "state": "running", "last_progress_at": progress}, create=True), \
                 mock.patch.object(api._idempotency, "touch_active_claim", return_value=True, create=True) as touch:
                asyncio.run(run())
                self.assertEqual(touch.called, expected)
                if expected:
                    touch.assert_called_with(claim, last_progress_at=progress, max_no_progress_seconds=300)

    def test_disconnect_waits_for_the_original_worker_to_finish(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def worker():
            calls.append("original")
            entered.set()
            if not release.wait(3):
                raise AssertionError("synthetic worker not released")
            calls.append("settled")

        async def run():
            async def source():
                await api._await_media_worker(worker)
                yield 'data: {"type":"complete"}\n\n'
            async def consume():
                return [chunk async for chunk in api._timed_sse_stream(
                    source(), operation="generate", success_types={"complete"})]
            task = asyncio.create_task(consume())
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(run())
        self.assertEqual(calls, ["original", "settled"])

    def test_image_gate_is_released_before_primary_claude_summary(self):
        order = []

        @asynccontextmanager
        async def slot(index):
            order.append(("enter", index))
            try:
                yield
            finally:
                order.append(("exit", index))

        async def observe(*_args):
            order.append("observed")
            return "画面中有庭院、木桥和清晰可见的座椅"

        async def summary(*_args, **_kwargs):
            order.append("summary")
            return "<scene>庭院</scene>"

        with mock.patch.object(api._public_product, "media_worker_slot", side_effect=slot, create=True), \
             mock.patch.object(api, "_await_media_worker", side_effect=observe), \
             mock.patch.object(api, "_runtime_prompt", return_value="{domain}"), \
             mock.patch.object(api._mr, "call", side_effect=summary):
            asyncio.run(api._gent_visual("image", "美食", None, {}))
        self.assertEqual(order, [("enter", 0), "observed", ("exit", 0), "summary"])

    def test_analyze_cover_and_extra_preprocessing_use_the_existing_media_gate(self):
        active=0
        entered=[]
        observations=[]
        semaphore=None
        @asynccontextmanager
        async def slot(index):
            nonlocal active
            async with semaphore:
                active+=1;entered.append(index)
                try:
                    yield
                finally:
                    active-=1
        def decode(*_args):
            self.assertGreater(active,0)
            return 73,{}
        def observe(image,*_args):
            self.assertGreater(active,0)
            observations.append(image)
            return "来自原素材的完整视觉观察"
        async def run():
            nonlocal semaphore
            semaphore=asyncio.Semaphore(2)
            req=api.AnalyzeInput(note_title="原始标题",desc="原始正文",domain="美食",
                cover_image="11111111-1111-4111-8111-111111111111",
                extra_images=["22222222-2222-4222-8222-222222222222","33333333-3333-4333-8333-333333333333"])
            await api._run_analyze_pipeline(req,{"id":"owner"},billing_charge={},billing_managed=True)
        with mock.patch.object(api._public_product,"media_worker_slot",side_effect=slot), \
             mock.patch.object(api,"_extract_cover",side_effect=decode), \
             mock.patch.object(api,"_kimi_vision_understand",side_effect=observe), \
             mock.patch.object(api._billing,"record_auxiliary_usage"), \
             mock.patch.object(api,"_maybe_enrich_facts",new=mock.AsyncMock(side_effect=api.HTTPException(503,"synthetic stop after observations"))):
            with self.assertRaises(api.HTTPException):
                asyncio.run(run())
        self.assertEqual(entered,[0,0,1,2])
        self.assertEqual(len(observations),3)
        self.assertEqual(active,0)

    def test_batch_progress_counts_only_validated_images_in_original_order(self):
        primary = {"_image_desc": "第一张图完整观察", "raw": "scene"}
        events = []

        async def emit(event):
            events.append(event)

        with mock.patch.object(api, "_gent_visual", new=mock.AsyncMock(return_value=primary)), \
             mock.patch.object(api, "_generation_image_observation", new=mock.AsyncMock(
                 side_effect=["第二张图完整观察", "第三张图完整观察"])):
            result = asyncio.run(api._generation_visual_batch(["one", "two", "three"], "美食", None, {}, emit=emit))
        self.assertEqual(result, [primary, "第二张图完整观察", "第三张图完整观察"])
        self.assertEqual([e["completed"] for e in events], [1, 2, 3])
        self.assertTrue(all(e["total"] == 3 and e["work_progress"] for e in events))

    def test_cancel_resolves_only_owner_bound_original_hash_and_does_not_refund(self):
        row = {"id": "original-task", "operation": "generate", "key_hash": "original-key-hash", "status": "running"}
        with mock.patch.object(api._db, "fetchone", return_value=row) as read, \
             mock.patch.object(api._public_product, "request_cancel", return_value=True, create=True) as cancel, \
             mock.patch.object(api._public_product, "queue_status", return_value={"state": "settling"}, create=True), \
             mock.patch.object(api._idempotency, "mark_failed_and_refund") as refund:
            result = asyncio.run(api.cancel_chat_task("original-task", {"id": "original-owner"}))
        self.assertEqual(read.call_args.args[1], ("original-task", "original-owner"))
        cancel.assert_called_once_with("original-owner", "original-key-hash")
        refund.assert_not_called()
        self.assertTrue(result["cancel_requested"])
        self.assertIn("结算", result["message"])

    def test_cancel_json_is_accepted_by_actual_public_boundary_and_empty_post_is_rejected(self):
        import os
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from public_account import PublicAccountBoundary
        owner={"id":"synthetic-owner"}
        app=FastAPI()
        app.add_api_route("/chat/tasks/{session_id}/cancel",api.cancel_chat_task,methods=["POST"])
        app.dependency_overrides[api._auth.get_current_user]=lambda:owner
        row={"id":"11111111-1111-4111-8111-111111111111","operation":"generate",
             "key_hash":"owner-resolved-original-hash","status":"running"}
        with mock.patch.dict(os.environ,{"NOTEAI_PUBLIC_PRODUCT":"1","NOTEAI_PUBLIC_ORIGINS":"https://noteaipro.com"}), \
             mock.patch.object(api._public_product,"authenticated_user",new=mock.AsyncMock(return_value=owner)), \
             mock.patch.object(api._db,"fetchone",return_value=row), \
             mock.patch.object(api._public_product,"request_cancel",return_value=True) as cancel, \
             mock.patch.object(api._public_product,"queue_status",return_value={"state":"settling"}), \
             mock.patch.object(api._idempotency,"mark_failed_and_refund") as refund:
            client=TestClient(PublicAccountBoundary(app),headers={"Origin":"https://noteaipro.com","Authorization":"Bearer offline-only"})
            path="/chat/tasks/"+row["id"]+"/cancel"
            rejected=client.post(path)
            self.assertEqual(rejected.status_code,415)
            cancel.assert_not_called()
            accepted=client.post(path,content="{}",headers={"Content-Type":"application/json"})
            self.assertEqual(accepted.status_code,200,accepted.text)
            self.assertTrue(accepted.json()["cancel_requested"])
            cancel.assert_called_once_with(owner["id"],row["key_hash"])
            refund.assert_not_called()

    def test_another_owner_or_terminal_task_cannot_cancel(self):
        for row in (None, {"id": "done", "operation": "generate", "key_hash": "hash", "status": "completed"}):
            with self.subTest(row=row), mock.patch.object(api._db, "fetchone", return_value=row), \
                 mock.patch.object(api._public_product, "request_cancel", create=True) as cancel, \
                 mock.patch.object(api._public_product, "queue_status", return_value={}, create=True):
                if row is None:
                    with self.assertRaises(api.HTTPException) as failure:
                        asyncio.run(api.cancel_chat_task("other-task", {"id": "owner"}))
                    self.assertEqual(failure.exception.status_code, 404)
                else:
                    result = asyncio.run(api.cancel_chat_task("done", {"id": "owner"}))
                    self.assertFalse(result["cancel_requested"])
                cancel.assert_not_called()

    def test_failed_specialist_never_emits_a_completed_expert_event(self):
        events = []

        async def quick_sleep(_seconds):
            return None

        async def run():
            async for event in api._generate_pipeline_stream(
                    "美食", "合成原始说明", None, None, {}, None, "20261017", user_id="synthetic-owner"):
                events.append(event)

        with mock.patch.object(api, "_get_dk", return_value={}), \
             mock.patch.object(api, "_gent_content", new=mock.AsyncMock(side_effect=RuntimeError("synthetic"))), \
             mock.patch.object(api, "_gent_growth", new=mock.AsyncMock(return_value={"raw": "<keywords>构图</keywords>"})), \
             mock.patch.object(api, "_gent_user", new=mock.AsyncMock(return_value={"raw": "<hook>画面整理</hook>"})), \
             mock.patch.object(api.asyncio, "sleep", side_effect=quick_sleep), \
             mock.patch.object(api, "_log_internal_failure"):
            with self.assertRaises(api.HTTPException):
                asyncio.run(run())
        self.assertEqual([e["agent_idx"] for e in events if e["type"] == "expert_failed"], [1])
        self.assertFalse(any(e["type"] == "expert_opinion" and e.get("agent_idx") == 1 for e in events))
        self.assertFalse(any(e["type"] == "complete" for e in events))

    def test_first_failed_specialist_cancels_queued_others_before_further_dispatch(self):
        queued=asyncio.Event()
        dispatched=[]
        cancelled=[]
        waiting_names=[]
        real_sleep=asyncio.sleep

        async def content(*_args):
            await queued.wait()
            raise RuntimeError("synthetic known failure")

        async def waiting(name):
            waiting_names.append(name)
            if len(waiting_names)==2:queued.set()
            try:
                # This models an admission ticket that has not dispatched.
                await asyncio.Event().wait()
                dispatched.append(name)
                return {"raw":"should not run"}
            except asyncio.CancelledError:
                cancelled.append(name)
                raise

        async def growth(*_args):
            return await waiting("growth")

        async def user(*_args):
            return await waiting("user")

        async def quick_sleep(_seconds):
            await real_sleep(0)

        async def run():
            return [event async for event in api._generate_pipeline_stream(
                "美食","合成原始说明",None,None,{},None,"20261017",user_id="synthetic-owner")]

        with mock.patch.object(api,"_get_dk",return_value={}), \
             mock.patch.object(api,"_gent_content",side_effect=content), \
             mock.patch.object(api,"_gent_growth",side_effect=growth), \
             mock.patch.object(api,"_gent_user",side_effect=user), \
             mock.patch.object(api.asyncio,"sleep",side_effect=quick_sleep), \
             mock.patch.object(api,"_log_internal_failure"):
            with self.assertRaises(api.HTTPException):
                asyncio.run(run())
        self.assertEqual(dispatched,[])
        self.assertEqual(sorted(cancelled),["growth","user"])

    def test_failure_inside_either_stagger_prevents_unstarted_specialists_and_joins_dispatched(self):
        real_sleep=asyncio.sleep
        for failing_stagger in (1,2):
            with self.subTest(failing_stagger=failing_stagger):
                started=[];settled=[];events=[]
                content_entered=threading.Event();content_release=threading.Event();content_done=threading.Event()
                growth_entered=threading.Event();growth_release=threading.Event()
                stagger_count=0
                def worker(name):
                    started.append(name)
                    if name=="content":
                        content_entered.set()
                        if not content_release.wait(3):raise AssertionError("content not released")
                        settled.append(name);content_done.set()
                        raise RuntimeError("synthetic known failure during stagger")
                    growth_entered.set()
                    if not growth_release.wait(3):raise AssertionError("growth not released")
                    settled.append(name)
                    return {"raw":"original growth result"}
                async def content(*_args):return await api._await_media_worker(worker,"content")
                async def growth(*_args):return await api._await_media_worker(worker,"growth")
                async def stagger(_seconds):
                    nonlocal stagger_count
                    stagger_count+=1
                    self.assertTrue(await asyncio.to_thread(content_entered.wait,2))
                    if stagger_count==failing_stagger:
                        if failing_stagger==2:self.assertTrue(await asyncio.to_thread(growth_entered.wait,2))
                        content_release.set()
                        self.assertTrue(await asyncio.to_thread(content_done.wait,2))
                        # Let the original child propagate its settled failure.
                        for _ in range(5):await real_sleep(0)
                    else:await real_sleep(0)
                async def run():
                    async def consume():
                        async for event in api._generate_pipeline_stream(
                            "美食","合成原始说明",None,None,{},None,"20261017",user_id="synthetic-owner"):
                            events.append(event)
                    task=asyncio.create_task(consume())
                    if failing_stagger==2:
                        for _ in range(100):
                            if any(e["type"]=="expert_failed" for e in events):break
                            await real_sleep(.001)
                        self.assertTrue(any(e["type"]=="expert_failed" for e in events))
                        self.assertFalse(task.done())
                        growth_release.set()
                    with self.assertRaises(api.HTTPException):await task
                with mock.patch.object(api,"_get_dk",return_value={}), \
                     mock.patch.object(api,"_gent_content",side_effect=content), \
                     mock.patch.object(api,"_gent_growth",side_effect=growth) as growth_call, \
                     mock.patch.object(api,"_gent_user",new=mock.AsyncMock()) as user_call, \
                     mock.patch.object(api.asyncio,"sleep",side_effect=stagger), \
                     mock.patch.object(api,"_log_internal_failure"):
                    asyncio.run(run())
                user_call.assert_not_called()
                if failing_stagger==1:growth_call.assert_not_called()
                self.assertEqual(started,["content"] if failing_stagger==1 else ["content","growth"])
                self.assertEqual(sorted(settled),sorted(started))
                self.assertEqual([e["agent_idx"] for e in events if e["type"]=="expert_failed"],[1])

    def test_closing_parent_joins_already_started_specialists(self):
        release = threading.Event()
        entered = {name: threading.Event() for name in ("growth", "user")}
        settled = []
        real_sleep = asyncio.sleep

        def worker(name):
            entered[name].set()
            if not release.wait(3):
                raise AssertionError("synthetic specialist not released")
            settled.append(name)
            return {"raw": "<hook>合成观察</hook>"}

        async def growth(*_args):
            return await api._await_media_worker(worker, "growth")

        async def user(*_args):
            return await api._await_media_worker(worker, "user")

        async def quick_sleep(_seconds):
            return None

        async def run():
            stream = api._generate_pipeline_stream(
                "美食", "合成原始说明", None, None, {}, None, "20261017", user_id="synthetic-owner")
            async for event in stream:
                if event["type"] == "expert_opinion" and event.get("agent_idx") == 1:
                    break
            for marker in entered.values():
                self.assertTrue(await asyncio.to_thread(marker.wait, 2))
            close = asyncio.create_task(stream.aclose())
            await real_sleep(.01)
            self.assertFalse(close.done())
            release.set()
            await close

        with mock.patch.object(api, "_get_dk", return_value={}), \
             mock.patch.object(api, "_gent_content", new=mock.AsyncMock(return_value={"raw": "<title>合成标题</title>"})), \
             mock.patch.object(api, "_gent_growth", side_effect=growth), \
             mock.patch.object(api, "_gent_user", side_effect=user), \
             mock.patch.object(api.asyncio, "sleep", side_effect=quick_sleep):
            asyncio.run(run())
        self.assertEqual(sorted(settled), ["growth", "user"])

    def test_disconnect_during_stagger_joins_first_specialist_without_starting_others(self):
        entered, release = threading.Event(), threading.Event()
        settled = []
        real_sleep = asyncio.sleep

        def worker():
            entered.set()
            if not release.wait(3):
                raise AssertionError("synthetic first specialist not released")
            settled.append("original")
            return {"raw": "<title>合成标题</title>"}

        async def content(*_args):
            return await api._await_media_worker(worker)

        async def hold_stagger(_seconds):
            await asyncio.Event().wait()

        async def run():
            async def consume():
                return [e async for e in api._generate_pipeline_stream(
                    "美食", "合成原始说明", None, None, {}, None, "20261017", user_id="synthetic-owner")]
            task=asyncio.create_task(consume())
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
            await real_sleep(.01)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with mock.patch.object(api, "_get_dk", return_value={}), \
             mock.patch.object(api, "_gent_content", side_effect=content), \
             mock.patch.object(api, "_gent_growth", new=mock.AsyncMock()) as growth, \
             mock.patch.object(api, "_gent_user", new=mock.AsyncMock()) as user, \
             mock.patch.object(api.asyncio, "sleep", side_effect=hold_stagger):
            asyncio.run(run())
        growth.assert_not_called()
        user.assert_not_called()
        self.assertEqual(settled,["original"])

    def test_resumed_stream_binds_original_claim_for_status_and_cancel_without_recharge(self):
        admission=importlib.import_module("model_admission")
        manager=admission.Admission(admission.Limits())
        current_hash=hashlib.sha256(b"new-clarification-http-request").hexdigest()
        original_hash=hashlib.sha256(b"original-generate-http-request").hexdigest()
        operation,_=manager.register("original-owner",current_hash)
        invocation=api._public_product.Invocation("original-owner","new-clarification-http-request")
        invocation.admission_state=operation
        claim={"state":"owner","request_id":"original-task","user_id":"original-owner",
               "operation":"generate","key_hash":original_hash,"charge":None}

        async def source():
            self.assertIs(manager.find("original-owner",original_hash),operation)
            self.assertIsNone(manager.find("another-owner",original_hash))
            yield 'data: {"type":"stage","stage":"p3"}\n\n'

        async def run():
            stream=api._idempotent_sse_stream(source(),claim,success_types={"complete"},announce_task=True)
            first=json.loads((await anext(stream))[6:])
            self.assertFalse(first["can_cancel"])  # Registered, but no work ticket yet.
            ticket=manager.calls.enqueue(operation,"synthetic-resume-call","claude")
            await anext(stream)
            self.assertTrue(api._public_product.queue_status("original-owner",original_hash)["can_cancel"])
            self.assertFalse(api._public_product.request_cancel("another-owner",original_hash))
            self.assertTrue(api._public_product.request_cancel("original-owner",original_hash))
            self.assertTrue(operation.cancelled.is_set())
            manager.calls.release(ticket)
            await stream.aclose()

        marker=api._public_product._invocation.set(invocation)
        try:
            with mock.patch.object(api._public_product,"enabled",return_value=True), \
                 mock.patch.object(admission,"current",return_value=manager), \
                 mock.patch.object(api._idempotency,"mark_failed_and_refund",return_value=True), \
                 mock.patch.object(api._billing,"get_charge_receipt",return_value={}), \
                 mock.patch.object(api._billing,"check_and_deduct") as charge:
                asyncio.run(run())
                charge.assert_not_called()
                manager.finish(operation)
                self.assertIsNone(manager.find("original-owner",original_hash))
        finally:
            api._public_product._invocation.reset(marker)

    def test_cancel_during_last_provider_stops_before_original_report_save(self):
        admission=importlib.import_module("model_admission")
        manager=admission.Admission(admission.Limits())
        key_hash=hashlib.sha256(b"original-generate-request").hexdigest()
        operation,_=manager.register("owner",key_hash)
        invocation=api._public_product.Invocation("owner","original-generate-request")
        invocation.admission_state=operation
        claim={"state":"owner","request_id":"original-task","user_id":"owner",
               "operation":"generate","key_hash":key_hash,"charge":{}}

        async def pipeline(**_kwargs):
            ticket=manager.calls.enqueue(operation,"synthetic-last-call","claude")
            ticket.dispatched=True
            self.assertTrue(api._public_product.request_cancel("owner",key_hash))
            ticket.progress=True
            manager.calls.release(ticket)
            yield {"type":"complete","note_title":"合成标题","note_body":"合成正文"}

        async def run():
            response=await api.generate_stream_endpoint(api.GenerateInput(domain="美食",brief="合成简报",persist_result=True),
                {"id":"owner"},request_id="original-generate-request",quote_version="synthetic")
            return [json.loads(chunk[6:]) async for chunk in response.body_iterator]

        marker=api._public_product._invocation.set(invocation)
        try:
            with mock.patch.object(api._public_product,"enabled",return_value=True), \
                 mock.patch.object(admission,"current",return_value=manager), \
                 mock.patch.object(api,"_paid_request_claim",return_value=claim), \
                 mock.patch.object(api,"_compute_market_timing_for_delivery",return_value=None), \
                 mock.patch.object(api,"_maybe_enrich_facts",new=mock.AsyncMock(return_value=None)), \
                 mock.patch.object(api,"_generate_pipeline_stream",side_effect=pipeline), \
                 mock.patch.object(api._memory,"build_memory_prompt",return_value=""), \
                 mock.patch.object(api._memory,"check_and_record_achievements"), \
                 mock.patch.object(api._billing,"get_subscription",return_value={}), \
                 mock.patch.object(api._billing,"get_charge_receipt",return_value={}), \
                 mock.patch.object(api._clarification,"enabled",return_value=True), \
                 mock.patch.object(api._clarification,"save_result") as save, \
                 mock.patch.object(api._idempotency,"mark_failed_and_refund",return_value=True), \
                 mock.patch.object(api,"_failed_stream_task_event",return_value={"type":"error"}), \
                 mock.patch.object(api,"_log_internal_failure"):
                events=asyncio.run(run())
            save.assert_not_called()
            self.assertEqual(operation.completed_calls,1)
            self.assertFalse(any(e["type"]=="complete" for e in events))
            self.assertTrue(any(e["type"]=="error" for e in events))
        finally:
            api._public_product._invocation.reset(marker)

    def test_ten_p0_tasks_decode_at_most_two_and_cancel_joins_original_threads(self):
        """Synthetic blocked decoders prove gating, not real pixel/RSS capacity."""
        admission=importlib.import_module("model_admission")
        manager=admission.Admission(admission.Limits(media_workers=2,operations=10))
        release=threading.Event()
        lock=threading.Condition()
        started=[]
        active=peak=0

        def decode(image,use_vision):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active);started.append(image);lock.notify_all()
            try:
                if not release.wait(3):
                    raise AssertionError("synthetic P0 decoder not released")
                return (70,{"synthetic":True})
            finally:
                with lock:
                    active-=1

        def first_two():
            with lock:
                return lock.wait_for(lambda:len(started)==2,2)

        async def run_one(index):
            uid="synthetic-p0-%s"%index
            operation,_=manager.register(uid,uid)
            invocation=api._public_product.Invocation(uid,uid,admission_state=operation)
            marker=api._public_product._invocation.set(invocation)
            try:
                return await api._bounded_extract_cover(index,False)
            finally:
                api._public_product._invocation.reset(marker)
                manager.finish(operation)

        async def run():
            tasks=[asyncio.create_task(run_one(i)) for i in range(10)]
            self.assertTrue(await asyncio.to_thread(first_two))
            with lock: original=started[0]
            self.assertNotIn(9,started)
            tasks[9].cancel()
            tasks[original].cancel()
            await asyncio.sleep(.01)
            self.assertFalse(tasks[original].done())
            self.assertEqual(len(started),2)
            release.set()
            return await asyncio.gather(*tasks,return_exceptions=True)

        with mock.patch.object(api._public_product,"enabled",return_value=True), \
             mock.patch.object(admission,"current",return_value=manager), \
             mock.patch.object(api,"_extract_cover",side_effect=decode):
            results=asyncio.run(run())
        self.assertEqual(peak,2)
        self.assertEqual(len(started),9)
        self.assertEqual(sum(isinstance(result,asyncio.CancelledError) for result in results),2)
        self.assertEqual(manager.media.active,{})
        self.assertEqual(manager.media._tickets(),[])
        self.assertEqual(manager.operations,{})


if __name__ == "__main__":
    unittest.main()
