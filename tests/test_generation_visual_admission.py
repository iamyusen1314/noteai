"""Offline regression for one nine-image batch sharing the two public slots."""
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


class _AdmissionClock:
    """Only Ark's admission clock advances; asyncio and DB clocks stay real."""
    def __init__(self):
        self.now = 0.0
        self.waiters = set()
        self.changed = threading.Condition()

    def monotonic(self):
        with self.changed:
            return self.now

    def sleep(self, seconds):
        with self.changed:
            until = self.now + seconds
            self.waiters.add(threading.get_ident())
            self.changed.notify_all()
            if not self.changed.wait_for(lambda: self.now >= until, timeout=5):
                raise AssertionError("synthetic admission clock was not released")

    def wait_for_waiters(self, count):
        with self.changed:
            return self.changed.wait_for(lambda: len(self.waiters) >= count, timeout=5)

    def advance(self, seconds):
        with self.changed:
            self.now += seconds
            self.changed.notify_all()


class GenerationVisualAdmissionTests(unittest.TestCase):
    def test_single_image_keeps_one_primary_observation(self):
        primary = {"role": "视觉专家", "raw": "<scene>主图完整概要</scene>", "_image_desc": "主图完整观察"}
        with mock.patch.object(api, "_gent_visual", new=mock.AsyncMock(return_value=primary)) as main, \
             mock.patch.object(api, "_await_media_worker", new=mock.AsyncMock()) as extra:
            result = asyncio.run(api._generation_visual_batch(["only-image"], "美食", "原始说明", {}))
        main.assert_awaited_once()
        self.assertEqual(main.call_args.args, ("only-image", "美食", "原始说明", {}))
        self.assertEqual(set(main.call_args.kwargs), {"_batch_can_continue"})
        self.assertTrue(main.call_args.kwargs["_batch_can_continue"]())
        extra.assert_not_called()
        self.assertEqual(result, [primary])

    def test_nine_images_do_not_expire_while_waiting_for_own_two_slots(self):
        """Nine real Ark adapters, synthetic clock/wire, no external call."""
        self._run_nine_images()

    def test_first_fatal_failure_stops_queued_images_and_joins_dispatched_ledger(self):
        self._run_nine_images(fail_first_http=True)

    def test_cancelled_batch_joins_dispatched_ledger_without_starting_queued_images(self):
        self._run_nine_images(cancel_batch=True)

    def test_empty_extra_image_stops_main_summary_after_dispatched_images_settle(self):
        self._run_nine_images(short_extra=True)

    def test_admission_busy_log_requires_the_exact_provider_stop_code(self):
        for error, status in (
            (public.TrialProviderStopped("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED"), "admission_busy"),
            (public.TrialProviderStopped("ARK_HTTP_502"), "failed"),
            (RuntimeError("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED"), "failed"),
        ):
            with self.subTest(error=type(error).__name__, status=status), \
                 mock.patch.object(api, "_gent_visual", new=mock.AsyncMock(side_effect=error)), \
                 mock.patch.object(api, "_await_media_worker", new=mock.AsyncMock()) as extra, \
                 mock.patch.object(api, "_log_internal_failure") as logged:
                result = asyncio.run(api._generation_visual_batch(["main", "queued"], "美食", None, {}))
            self.assertIs(result[0], error)
            self.assertEqual(result[1:], [None])
            extra.assert_not_called()
            logged.assert_called_once_with("generate", error, phase="generation_visual_image_1", status=status)

    def _run_nine_images(self, *, fail_first_http=False, cancel_batch=False, short_extra=False):
        clock = _AdmissionClock()
        two_sent, release_first, release_supplier = (threading.Event() for _ in range(3))
        invalid_extra = threading.Event()
        thread_image = threading.local()
        failure_changed = threading.Condition()
        failed_jobs = 0
        wire_lock = threading.Lock()
        physical_requests, started_jobs, summary_calls, batch_results = [], [], [], []
        images = ["synthetic-image-" + str(i) for i in range(9)]
        active_http = max_http = 0
        observation = "素材中的庭院、木桥和光线均清晰可见。"
        payload = {"model": ark.MODEL,
                   "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                             "prompt_tokens_details": {"cached_tokens": 0}},
                   "choices": [{"finish_reason": "stop", "message": {"content": observation}}]}
        pixels = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(pixels, format="PNG")
        real_worker, real_vision, real_batch = api._await_media_worker, api._kimi_vision_understand, api._generation_visual_batch
        real_log = api._log_internal_failure

        def observe_log(*args, **kwargs):
            if kwargs.get("phase") == "generation_visual_image_2" and kwargs.get("status") == "invalid_result":
                invalid_extra.set()
            return real_log(*args, **kwargs)

        async def observe_worker(function, *args, **kwargs):
            started_jobs.append(args[0])
            return await real_worker(function, *args, **kwargs)

        def observe_vision(*args, **kwargs):
            nonlocal failed_jobs
            try:
                thread_image.value = args[0]
                result = real_vision(*args, **kwargs)
                return "" if short_extra and args[0] == images[1] else result + " " + args[0]
            except public.TrialProviderStopped:
                with failure_changed:
                    failed_jobs += 1
                    failure_changed.notify_all()
                raise

        async def observe_batch(*args, **kwargs):
            results = await real_batch(*args, **kwargs)
            batch_results.extend(results)
            return results

        def wait_for_failed(count):
            with failure_changed:
                return failure_changed.wait_for(lambda: failed_jobs >= count, timeout=5)

        def supplier(request):
            nonlocal active_http, max_http
            # This is httpx.MockTransport, never a real provider request.
            with wire_lock:
                physical_requests.append(request.headers.get("content-type"))
                ordinal = len(physical_requests)
                active_http += 1
                max_http = max(max_http, active_http)
                if len(physical_requests) == 2:
                    two_sent.set()
            try:
                release = release_first if (fail_first_http and ordinal == 1 or
                                             short_extra and thread_image.value == images[1]) else release_supplier
                if not release.wait(timeout=5):
                    raise AssertionError("synthetic supplier was not released")
                if fail_first_http and ordinal == 1:
                    return httpx.Response(502, json={"error": "synthetic supplier rejection"})
                return httpx.Response(200, json=payload)
            finally:
                with wire_lock:
                    active_http -= 1

        def client(**_kwargs):
            return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)

        async def summary(*args, **kwargs):
            public.assert_result_known()
            self.assertEqual(args[0], "content_gen")
            self.assertEqual(kwargs, {"max_tokens": 16000, "trace_step": "generation_visual",
                                      "prompt_keys": ("gent_visual_system",), "prompt_domain": "休闲娱乐体验"})
            summary_calls.append("generation_visual")
            return "<image_desc>庭院与木桥</image_desc><inspiration>素材角度</inspiration>"

        async def run():
            events = []
            async def consume():
                stream = api._generate_pipeline_stream(
                    "休闲娱乐体验", "本地合成排队测试", None, None, {}, None, "2026101712",
                    cover_images=images, user_id="queue-owner")
                try:
                    async for event in stream:
                        events.append(event)
                        if event.get("type") == "stage" and event.get("stage") == "p2":
                            break  # Do not run unrelated creator/arbitration stages.
                finally:
                    await stream.aclose()
            task = asyncio.create_task(consume())
            failure = None
            try:
                self.assertTrue(await asyncio.to_thread(two_sent.wait, 5))
                await asyncio.sleep(0)  # Let the batch's initial jobs reach their wait.
                queued = max(0, len(started_jobs) - 2)
                self.assertTrue(await asyncio.to_thread(clock.wait_for_waiters, queued))
                # The first two HTTP operations are still inside their valid
                # 240s read window; only their queued siblings see 91s elapsed.
                clock.advance(91)
                if queued:
                    self.assertTrue(await asyncio.to_thread(wait_for_failed, queued))
                if short_extra:
                    release_first.set()
                    self.assertTrue(await asyncio.to_thread(invalid_extra.wait, 5))
                    self.assertFalse(task.done())
                    self.assertEqual(len(physical_requests), 2)
                    self.assertEqual(summary_calls, [])
                    inflight = db.fetchall("SELECT state,http_status FROM public_trial_calls WHERE user_id=?",
                                           ("queue-owner",))
                    self.assertEqual(sorted((r["state"], r["http_status"]) for r in inflight),
                                     [("dispatched", None), ("responded", 200)])
                elif fail_first_http:
                    release_first.set()
                    self.assertTrue(await asyncio.to_thread(wait_for_failed, 1))
                    await asyncio.sleep(0)
                    # One original HTTP call is still in flight: do not return
                    # the batch or erase its supplier accounting prematurely.
                    self.assertFalse(task.done())
                    inflight = db.fetchall("SELECT state,http_status FROM public_trial_calls WHERE user_id=?",
                                           ("queue-owner",))
                    self.assertEqual(sorted((r["state"], r["http_status"]) for r in inflight),
                                     [("dispatched", None), ("responded", 502)])
                elif cancel_batch:
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    inflight = db.fetchall("SELECT state FROM public_trial_calls WHERE user_id=?", ("queue-owner",))
                    self.assertEqual([r["state"] for r in inflight], ["dispatched", "dispatched"])
            finally:
                release_first.set()
                release_supplier.set()
                clock.advance(1000)
                try:
                    await task
                except BaseException as exc:
                    failure = exc
            return events, failure

        old_path = db._DB_PATH
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {
                "DATABASE_URL": "", "NOTEAI_PUBLIC_PRODUCT": "1",
                "NOTEAI_ARK_API_KEY": "synthetic-offline-only"}))
            db._DB_PATH = Path(temporary) / "queue.sqlite"
            stack.callback(setattr, db, "_DB_PATH", old_path)
            stack.callback(billing.clear_active_usage)
            db.init_db()
            db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
                       "VALUES(?,?,?,?,?,?)", ("queue-owner", "queue-owner", "queue@example.invalid",
                                              "synthetic", "synthetic", "2026-10-17T00:00:00+00:00"))
            db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
            billing.record_free_usage("queue-owner", "generate")
            usage_id = billing._ACTIVE_USAGE_ID.get()
            invocation = public.Invocation("queue-owner", "synthetic-nine-image-original")
            marker = public._invocation.set(invocation)
            stack.callback(public._invocation.reset, marker)
            stack.enter_context(mock.patch.object(ark, "time", clock))
            stack.enter_context(mock.patch.object(ark, "_client", side_effect=client))
            stack.enter_context(mock.patch.object(api, "_read_image_input", return_value=pixels.getvalue()))
            stack.enter_context(mock.patch.object(api, "_await_media_worker", side_effect=observe_worker))
            stack.enter_context(mock.patch.object(api, "_kimi_vision_understand", side_effect=observe_vision))
            stack.enter_context(mock.patch.object(api, "_generation_visual_batch", side_effect=observe_batch))
            stack.enter_context(mock.patch.object(api, "_log_internal_failure", side_effect=observe_log))
            stack.enter_context(mock.patch.object(api, "_runtime_prompt", return_value="本地视觉测试{domain}"))
            stack.enter_context(mock.patch.object(api._mr, "call", side_effect=summary))
            events, failure = asyncio.run(run())
            rows = db.fetchall("SELECT state,http_status,usage_record_id,model_usage_record_id "
                               "FROM public_trial_calls WHERE user_id=?", ("queue-owner",))
            diagnostic = {"synthetic_only": True, "started_image_jobs": len(started_jobs),
                          "physical_mock_HTTP": len(physical_requests), "max_physical_inflight": max_http,
                          "usage_count": len({r["usage_record_id"] for r in rows}),
                          "stop_code": invocation.failure, "p2_entered": any(e.get("stage") == "p2" for e in events)}
            print("SYNTHETIC_NINE_IMAGE_SELF_QUEUE", json.dumps(diagnostic, sort_keys=True))
            self.assertLessEqual(max_http, 2)
            self.assertTrue(all(r["state"] == "responded" and r["usage_record_id"] == usage_id for r in rows))
            if short_extra:
                self.assertIsInstance(failure, api.HTTPException)
                self.assertEqual(failure.status_code, 502)
                self.assertEqual(invocation.failure, "")
                self.assertEqual(len(physical_requests), 2)
                self.assertEqual(started_jobs, images[:2])
                self.assertTrue(all(r["http_status"] == 200 and r["model_usage_record_id"] for r in rows))
                self.assertEqual(summary_calls, [])
                self.assertIsInstance(batch_results[0], api.HTTPException)
                self.assertEqual(batch_results[1], "")
                self.assertEqual(batch_results[2:], [None] * 7)
                self.assertFalse(any(e.get("stage") == "p2" for e in events))
                self.assertFalse(any(e.get("type") in {"expert", "material_observed"} for e in events))
            elif cancel_batch:
                self.assertIsInstance(failure, asyncio.CancelledError)
                self.assertEqual(len(physical_requests), 2)
                self.assertEqual(started_jobs, images[:2])
                self.assertTrue(all(r["http_status"] == 200 and r["model_usage_record_id"] for r in rows))
                self.assertEqual(summary_calls, [])
                self.assertEqual(batch_results, [])
                self.assertFalse(any(e.get("stage") == "p2" for e in events))
                self.assertFalse(any(e.get("type") in {"expert", "material_observed"} for e in events))
            elif fail_first_http:
                self.assertEqual(len(batch_results), 9)
                self.assertIsInstance(failure, api.HTTPException)
                self.assertEqual(failure.status_code, 502)
                self.assertEqual(invocation.failure, "ARK_HTTP_502")
                self.assertEqual(len(physical_requests), 2)
                self.assertEqual(started_jobs, images[:2])
                self.assertEqual([r["http_status"] for r in rows].count(200), 1)
                self.assertEqual([r["http_status"] for r in rows].count(502), 1)
                self.assertTrue(all(bool(r["model_usage_record_id"]) == (r["http_status"] == 200) for r in rows))
                self.assertEqual(summary_calls, [])
                self.assertEqual(batch_results[2:], [None] * 7)
                self.assertFalse(any(e.get("stage") == "p2" for e in events))
                self.assertFalse(any(e.get("type") in {"expert", "material_observed"} for e in events))
            else:
                self.assertEqual(len(batch_results), 9)
                self.assertTrue(all(r["http_status"] == 200 and r["model_usage_record_id"] for r in rows))
                self.assertIsNone(failure, "Own queued images expired before admission: " + json.dumps(diagnostic, sort_keys=True))
                self.assertEqual(len(physical_requests), 9)
                self.assertEqual(started_jobs, images)
                self.assertEqual(summary_calls, ["generation_visual"])
                self.assertTrue(any(e.get("stage") == "p2" for e in events))
                self.assertIsInstance(batch_results[0], dict)
                self.assertTrue(batch_results[0]["_image_desc"].endswith(images[0]))
                self.assertEqual(batch_results[1:], [observation + " " + image for image in images[1:]])
