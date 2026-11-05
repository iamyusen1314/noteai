"""ASGI shutdown must close the already-created model I/O pool after drain.

Only local SQLite, private image references, real worker threads and MockTransport
are used. This does not simulate SIGKILL, supplier quality or production capacity.
"""
import asyncio
import json
import threading
import unittest
from unittest import mock

import httpx

from tests import test_capacity_media_stage_isolation as media_fixture

api, ark, admission = media_fixture.api, media_fixture.ark, media_fixture.admission
db, billing, public = media_fixture.db, media_fixture.billing, media_fixture.public


class RemoteWorkerShutdownTests(unittest.TestCase):
    def setUp(self):
        self.fixture = media_fixture.CapacityMediaStageIsolationTests()
        self.fixture.setUp()
        self.manager = self.fixture.manager

    def tearDown(self):
        self.fixture.tearDown()

    def test_shutdown_waits_for_original_and_queued_http_without_blocking_loop_or_cancelling_work(self):
        cases = [self.fixture.observation("shutdown-owner-" + str(index)) for index in range(2)]
        # A one-worker fixture guarantees the second accepted work item is queued.
        # No supplier/global production limit is changed.
        self.manager.calls.capacity = 1
        started, release, closing = threading.Event(), threading.Event(), threading.Event()
        sent, order, closing_threads = [], [], []
        original_close = self.manager.close_remote_workers

        def close():
            closing_threads.append(threading.current_thread().ident)
            order.append("remote-close")
            closing.set()
            return original_close()

        def supplier(request):
            sent.append(json.loads(request.content)["model"])
            if len(sent) == 1:
                started.set()
                if not release.wait(5):
                    raise AssertionError("Original remote HTTP was not released")
            return httpx.Response(200, json={"model": ark.MODEL,
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "prompt_tokens_details": {"cached_tokens": 0}},
                "choices": [{"finish_reason": "stop", "message": {"content": "原请求已知完成。"}}]})

        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)

        async def observe(index):
            reference, claim, invocation, operation = cases[index]
            im = public._invocation.set(invocation)
            um = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
            try:
                return await api._generation_image_observation(reference.id, "休闲娱乐体验", "原始照片", index)
            finally:
                billing._ACTIVE_USAGE_ID.reset(um)
                public._invocation.reset(im)
                self.manager.finish(operation)

        async def cover_drain():
            order.append("cover-drained")

        async def scenario():
            loop_thread = threading.current_thread().ident
            work = [asyncio.create_task(observe(index)) for index in range(2)]
            stopping = None
            try:
                async def wait_for_original_and_queue():
                    while (not started.is_set() or self.manager._remote_executor is None
                           or self.manager._remote_executor._work_queue.qsize() < 1):
                        await asyncio.sleep(.005)
                await asyncio.wait_for(wait_for_original_and_queue(), 2)
                executor = self.manager._remote_executor
                stopping = asyncio.create_task(api.shutdown())
                await asyncio.sleep(.03)
                self.assertFalse(stopping.done(), "ASGI shutdown returned with its model I/O pool still alive")
                self.assertTrue(closing.is_set())
                self.assertEqual(order, ["cover-drained", "remote-close"])
                self.assertNotEqual(closing_threads, [loop_thread], "Joining vendor I/O must not block the event loop")
                self.assertTrue(executor._shutdown)
                self.assertFalse(release.is_set())
                self.assertEqual(len(sent), 1)
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 0)
            finally:
                release.set()
                results = await asyncio.gather(*work, return_exceptions=True)
                if stopping is not None:
                    await asyncio.gather(stopping, return_exceptions=True)
            self.assertEqual(results, ["原请求已知完成。"] * 2)
            self.assertIsNone(self.manager._remote_executor)
            self.assertEqual(len(sent), 2, "Accepted queued work must not be cancelled")
            self.assertTrue(all(not thread.is_alive() for thread in executor._threads))
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='responded' AND http_status=200")[0], 2)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 2)
            self.assertEqual(self.manager.buffers.active, {})
            self.assertEqual(self.manager.calls.active, {})
            for _reference, claim, _invocation, _operation in cases:
                usage = db.fetchone("SELECT complete_applied,refund_applied FROM idempotency_requests WHERE id=?", (claim["request_id"],))
                self.assertEqual(tuple(usage), (0, 0), "Pool closure must not settle or refund the user task")

        worker = mock.Mock()
        worker.stop = mock.AsyncMock(side_effect=cover_drain)
        with mock.patch.object(ark, "_client", side_effect=client), \
             mock.patch.object(api.app.state, "cover_worker", worker, create=True), \
             mock.patch.object(api._public_account, "enabled", return_value=True), \
             mock.patch.object(self.manager, "close_remote_workers", side_effect=close):
            asyncio.run(scenario())
        worker.stop.assert_awaited_once_with()

    def test_shutdown_without_a_remote_manager_preserves_lazy_initialization_and_public_early_return(self):
        runtime = mock.Mock()
        with mock.patch.object(admission, "_instance", None), \
             mock.patch.object(admission, "current", side_effect=AssertionError("Shutdown must not initialize model admission")), \
             mock.patch.object(api.app.state, "cover_worker", None, create=True), \
             mock.patch.object(api.app.state, "item31_canary_runtime", runtime, create=True), \
             mock.patch.object(api._public_account, "enabled", return_value=True):
            asyncio.run(api.shutdown())
        runtime.close.assert_not_called()
