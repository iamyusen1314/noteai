"""Local image work must release CPU before waiting on a remote model.

Actual handlers, media admission, private references, Pillow and MockTransport
accounting run. These are local resource contracts, not production throughput.
"""
import asyncio
import base64
import concurrent.futures
from contextlib import asynccontextmanager
import io
import json
import os
import socket
import threading
import unittest
from unittest import mock

import httpx
from PIL import Image
from starlette.datastructures import Headers, UploadFile

from tests import test_private_storage_recovery as storage_fixture
from tests.test_generation_multiuser_admission import api, ark, admission, db, billing, public
import postdelivery


class CapacityMediaStageIsolationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = storage_fixture.PrivateStorageRecoveryContractTests()
        self.fixture.setUp()
        self.environment = mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
            "NOTEAI_MODEL_CAPACITY_SCOPE": "ark-primary", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "",
            "NOTEAI_MODEL_REMOTE_CONCURRENCY": "16", "NOTEAI_MEDIA_WORKER_CONCURRENCY": "2",
            "NOTEAI_ARK_API_KEY": "synthetic-offline-only"})
        self.environment.start()
        self.sockets = [mock.patch.object(socket.socket, name,
            side_effect=AssertionError("No external socket allowed")) for name in ("connect", "connect_ex")]
        for patch in self.sockets:
            patch.start()
        db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
        self.manager = admission.Admission()
        self.manager_patch = mock.patch.object(admission, "_instance", self.manager)
        self.manager_patch.start()
        image = io.BytesIO()
        Image.new("RGB", (300, 200), (210, 140, 60)).save(image, "JPEG", quality=90)
        self.photo = image.getvalue()

    def tearDown(self):
        self.manager.close_remote_workers()
        self.manager_patch.stop()
        for patch in reversed(self.sockets):
            patch.stop()
        self.environment.stop()
        self.fixture.tearDown()

    def observation(self, user):
        self.fixture.create_user(user)
        reference = api._private_storage.store_media_bytes(user, purpose="image", content_type="image/jpeg",
            payload=self.photo, item_count=1)
        claim = postdelivery.reserve_claim(user_id=user, operation="generate",
            request_id="image-stage-" + user, payload={"fixture": True})
        operation, _ = self.manager.register(user, user, route="/generate/stream")
        invocation = public.Invocation(user, claim["request_id"], route="/generate/stream", admission_state=operation)
        return reference, claim, invocation, operation

    def test_two_held_remote_calls_leave_image_cpu_available_to_upload_and_sse(self):
        self._run_two_held_remote_upload()

    def test_saturated_default_executor_keeps_upload_and_sse_live(self):
        self._run_two_held_remote_upload(default_workers=2)

    def _run_two_held_remote_upload(self, default_workers=None):
        cases = [self.observation("media-observer-" + str(index)) for index in range(2)]
        upload_user = "media-upload-owner"
        self.fixture.create_user(upload_user)
        both_http, release_http = threading.Event(), threading.Event()
        sent, buffer_sizes, remote_threads = [], [], []
        buffered = {"current": 0, "peak": 0}
        lock = threading.Lock()
        original_buffer_slot = getattr(public, "media_buffer_slot", None)

        @asynccontextmanager
        async def tracked_buffer(size):
            self.assertIsNotNone(original_buffer_slot, "The actual weighted buffer guard must exist")
            async with original_buffer_slot(size):
                with lock:
                    buffer_sizes.append(size)
                    buffered["current"] += size
                    buffered["peak"] = max(buffered["peak"], buffered["current"])
                try:
                    yield
                finally:
                    with lock:
                        buffered["current"] -= size

        def supplier(request):
            with lock:
                sent.append(len(request.content))
                remote_threads.append(threading.current_thread().name)
                if len(sent) == 2:
                    both_http.set()
            if not release_http.wait(5):
                raise AssertionError("Controlled remote model was not released")
            return httpx.Response(200, json={"model": ark.MODEL,
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "prompt_tokens_details": {"cached_tokens": 0}},
                "choices": [{"finish_reason": "stop", "message": {"content": "真实庭院与光线清晰可见。"}}]})

        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)

        async def scenario():
            if default_workers is not None:
                asyncio.get_running_loop().set_default_executor(concurrent.futures.ThreadPoolExecutor(
                    max_workers=default_workers, thread_name_prefix="controlled-default-cpu"))
            heartbeat_seen = asyncio.Event()
            source_stop = asyncio.Event()
            async def source():
                await source_stop.wait()
                if False:
                    yield ""

            async def watch_sse():
                stream = api._timed_sse_stream(source(), operation="generate", success_types={"complete"})
                try:
                    async for chunk in stream:
                        if json.loads(chunk.removeprefix("data: ").strip())["type"] == "heartbeat":
                            heartbeat_seen.set()
                            return
                finally:
                    await stream.aclose()

            async def observe(index):
                reference, claim, invocation, operation = cases[index]
                im = public._invocation.set(invocation)
                um = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
                try:
                    return await api._generation_image_observation(reference.id, "休闲娱乐体验", "真实照片", index)
                finally:
                    billing._ACTIVE_USAGE_ID.reset(um)
                    public._invocation.reset(im)
                    self.manager.finish(operation)

            async def upload():
                marker = public._invocation.set(public.Invocation(upload_user, "upload-during-http", route="/upload-image"))
                try:
                    file = UploadFile(file=io.BytesIO(self.photo), filename="original.jpg",
                        headers=Headers({"content-type": "image/jpeg"}))
                    return await api.upload_image(file, {"id": upload_user}, [])
                finally:
                    public._invocation.reset(marker)

            watcher = asyncio.create_task(watch_sse())
            observers = [asyncio.create_task(observe(index)) for index in range(2)]
            upload_task = None
            try:
                async def both_remote_started():
                    while not both_http.is_set():
                        await asyncio.sleep(.005)
                await asyncio.wait_for(both_remote_started(), 3)
                upload_task = asyncio.create_task(upload())
                completed_during_http = True
                try:
                    result = await asyncio.wait_for(asyncio.shield(upload_task), 1)
                except asyncio.TimeoutError:
                    completed_during_http = False
                self.assertTrue(completed_during_http,
                    "Remote Ark HTTP saturated the CPU/upload default executor" if default_workers is not None
                    else "Remote Ark HTTP held both local image CPU slots and blocked a new upload")
                self.assertFalse(release_http.is_set())
                self.assertTrue(heartbeat_seen.is_set())
                reference, body = api._private_storage.load_media_bytes(result["media_ref"], user_id=upload_user, purpose="image")
                self.assertEqual((reference.content_type, result["width"], result["height"]), ("image/jpeg", 300, 200))
                self.assertTrue(body)
                with lock:
                    self.assertEqual(len(sent), 2)
                    if default_workers is not None:
                        self.assertTrue(all(name.startswith("noteai-model-io") for name in remote_threads))
                    self.assertEqual(len(buffer_sizes), 2)
                    self.assertGreaterEqual(buffered["current"], 3 * sum(sent))
                with self.manager.media.lock:
                    self.assertEqual(self.manager.media.active, {})
                with self.manager.buffers.lock:
                    self.assertEqual(sum(ticket.weight for ticket in self.manager.buffers.active.values()), buffered["current"])
                    self.assertLessEqual(buffered["current"], self.manager.buffers.capacity)
            finally:
                if upload_task is not None and not upload_task.done():
                    upload_task.cancel()
                release_http.set()
                results = await asyncio.gather(*observers, return_exceptions=True)
                if upload_task is not None:
                    await asyncio.gather(upload_task, return_exceptions=True)
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            self.assertEqual(results, ["真实庭院与光线清晰可见。"] * 2)
            self.assertEqual(buffered["current"], 0)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='responded' AND http_status=200")[0], 2)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 2)
            self.assertEqual(self.manager.calls.active, {})
            self.assertEqual(self.manager.media.active, {})
            self.assertEqual(self.manager.buffers.active, {})
            self.assertEqual(self.manager.buffers._tickets(), [])

        with mock.patch.object(ark, "_client", side_effect=client), \
             mock.patch.object(public, "media_buffer_slot", tracked_buffer, create=True), \
             mock.patch.object(api, "_SSE_HEARTBEAT_SECONDS", .01):
            asyncio.run(scenario())

    def test_cancelled_remote_worker_joins_original_http_and_accounting_before_buffer_release(self):
        reference, claim, invocation, operation = self.observation("remote-cancel-owner")
        started, release = threading.Event(), threading.Event()
        sent = []

        def supplier(request):
            sent.append(threading.current_thread().name)
            started.set()
            if not release.wait(5):
                raise AssertionError("Original remote worker was not released")
            return httpx.Response(200, json={"model": ark.MODEL,
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "prompt_tokens_details": {"cached_tokens": 0}},
                "choices": [{"finish_reason": "stop", "message": {"content": "原请求已完成。"}}]})

        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)

        async def observe():
            im = public._invocation.set(invocation)
            um = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
            try:
                return await api._generation_image_observation(reference.id, "休闲娱乐体验", "真实照片", 0)
            finally:
                billing._ACTIVE_USAGE_ID.reset(um)
                public._invocation.reset(im)
                self.manager.finish(operation)

        async def scenario():
            asyncio.get_running_loop().set_default_executor(concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="controlled-cancel-cpu"))
            task = asyncio.create_task(observe())
            try:
                async def wait_for_http():
                    while not started.is_set():
                        await asyncio.sleep(.005)
                await asyncio.wait_for(wait_for_http(), 2)
                self.assertEqual(len(sent), 1)
                self.assertTrue(sent[0].startswith("noteai-model-io"))
                for _ in range(2):
                    task.cancel()
                    await asyncio.sleep(.01)
                    self.assertFalse(task.done(), "Disconnect must join the original HTTP and accounting")
                    self.assertEqual(len(self.manager.buffers.active), 1)
                    self.assertEqual(len(self.manager.calls.active), 1)
                    self.assertEqual(self.manager.media.active, {})
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 0)
            finally:
                release.set()
                result = (await asyncio.gather(task, return_exceptions=True))[0]
            self.assertIsInstance(result, asyncio.CancelledError)
            self.assertEqual(len(sent), 1)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='responded' AND http_status=200")[0], 1)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 1)
            self.assertEqual(self.manager.calls.active, {})
            self.assertEqual(self.manager.buffers.active, {})
            self.assertEqual(self.manager.buffers._tickets(), [])

        with mock.patch.object(ark, "_client", side_effect=client):
            asyncio.run(scenario())

    def test_large_prepared_bodies_wait_within_weighted_budget_before_more_cpu_preparation(self):
        import random
        raw = random.Random(7).randbytes(768 * 768 * 3)
        photo = io.BytesIO()
        Image.frombytes("RGB", (768, 768), raw).save(photo, "JPEG", quality=90)
        self.photo = photo.getvalue()
        prepared, bound = api._prepare_buffered_image_observation(
            base64.b64encode(self.photo).decode(), "休闲娱乐体验", "真实照片")
        self.assertGreater(bound, len(self.photo) * 3)
        self.assertGreaterEqual(bound, len(json.dumps(prepared, ensure_ascii=False, separators=(",", ":")).encode()) * 3)
        # An exact one-body memory fixture, not a changed production setting.
        self.manager.buffers.capacity = bound
        cases = [self.observation("buffered-observer-" + str(index)) for index in range(4)]
        first_http, prepared_three, release_http = threading.Event(), threading.Event(), threading.Event()
        sent, prepared_count = [], []
        lock = threading.Lock()
        original_prepare = api._prepare_buffered_image_observation

        def preparation(*args):
            value = original_prepare(*args)
            with lock:
                prepared_count.append(value[1])
                if len(prepared_count) == 3:
                    prepared_three.set()
            return value

        def supplier(request):
            with lock:
                ordinal = len(sent)
                sent.append(len(request.content))
            if ordinal == 0:
                first_http.set()
                if not release_http.wait(5):
                    raise AssertionError("Controlled buffer owner was not released")
            return httpx.Response(200, json={"model": ark.MODEL,
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "prompt_tokens_details": {"cached_tokens": 0}},
                "choices": [{"finish_reason": "stop", "message": {"content": "真实图片已读取。"}}]})

        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)

        async def observe(index):
            reference, claim, invocation, operation = cases[index]
            im = public._invocation.set(invocation)
            um = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
            try:
                return await api._generation_image_observation(reference.id, "休闲娱乐体验", "真实照片", index)
            finally:
                billing._ACTIVE_USAGE_ID.reset(um)
                public._invocation.reset(im)
                self.manager.finish(operation)

        async def scenario():
            tasks = [asyncio.create_task(observe(index)) for index in range(4)]
            try:
                self.assertTrue(await asyncio.to_thread(first_http.wait, 3))
                self.assertTrue(await asyncio.to_thread(prepared_three.wait, 3))
                await asyncio.sleep(.03)
                with lock:
                    self.assertEqual(len(sent), 1)
                    self.assertEqual(prepared_count, [bound] * 3)
                    self.assertGreaterEqual(bound, sent[0] * 3)
                with self.manager.buffers.lock:
                    self.assertEqual(sum(ticket.weight for ticket in self.manager.buffers.active.values()), bound)
                    self.assertEqual(len(self.manager.buffers._tickets()), 2)
                with self.manager.media.lock:
                    self.assertEqual(len(self.manager.media.active), 2)
                    self.assertEqual(len(self.manager.media._tickets()), 1)
            finally:
                release_http.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
            self.assertEqual(results, ["真实图片已读取。"] * 4)
            self.assertEqual(len(sent), 4)
            self.assertEqual(self.manager.buffers.active, {})
            self.assertEqual(self.manager.buffers._tickets(), [])
            self.assertEqual(self.manager.media.active, {})
            self.assertEqual(self.manager.calls.active, {})
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 4)

        with mock.patch.object(ark, "_client", side_effect=client), \
             mock.patch.object(api, "_prepare_buffered_image_observation", side_effect=preparation):
            asyncio.run(scenario())

    def test_p0_real_local_features_and_semantic_result_match_legacy_without_holding_cpu_for_http(self):
        reference, claim, invocation, operation = self.observation("p0-semantic-owner")
        semantic = {"has_text_overlay": True, "text_prominence": .1, "composition_score": .7,
                    "aesthetic_score": .8, "emotion_intensity": .6, "visual_clarity": .9}
        calls = []
        mode = [False]
        def remote(prompt, parts, **kwargs):
            calls.append((prompt, parts, kwargs))
            self.assertEqual(base64.b64decode(parts[0]["image_url"]["url"].split(",", 1)[1]), self.photo)
            with self.manager.media.lock:
                self.assertEqual(len(self.manager.media.active), 0 if mode[0] else 1)
            with self.manager.buffers.lock:
                held = sum(ticket.weight for ticket in self.manager.buffers.active.values())
                if mode[0]:
                    self.assertGreater(held, 0)
                else:
                    self.assertEqual(held, 0)
            return "```json\n" + json.dumps(semantic) + "\n```"

        async def scenario():
            im = public._invocation.set(invocation)
            um = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
            try:
                with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0"}):
                    legacy = await api._bounded_extract_cover(reference.id, True)
                mode[0] = True
                result = await api._bounded_extract_cover(reference.id, True)
                self.assertEqual(result, legacy)
                self.assertEqual(calls[0], calls[1])
                self.assertEqual(result[0], 78.5)
                self.assertEqual(calls[1][2], {"max_tokens": 2048, "json_output": True})
                self.assertTrue({"cover_brightness", "cover_face_count", "cover_aesthetic_score"} <= set(result[1]))
                self.assertEqual(result[1]["cover_aesthetic_score"], .8)
                self.assertEqual(self.manager.buffers.active, {})
                self.assertEqual(self.manager.media.active, {})
                # Invalid semantic fields still fail, never become default scores.
                for enabled in ("0", "1"):
                    with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": enabled}), \
                         mock.patch.object(ark, "chat", return_value='{"has_text_overlay":true}'):
                        with self.assertRaises(api.HTTPException) as failed:
                            await api._bounded_extract_cover(reference.id, True)
                    self.assertEqual(failed.exception.status_code, 502)
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 0)
            finally:
                billing._ACTIVE_USAGE_ID.reset(um)
                public._invocation.reset(im)
                self.manager.finish(operation)

        with mock.patch.object(ark, "chat", side_effect=remote):
            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
