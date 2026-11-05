"""Actual nine-image entry blocks share bounded CPU admission for 100 owners.

Only the affected blocks/functions are loaded from api.py. Image preparation
and supplier content are synthetic; real media/buffer queues, remote executor,
and the original cancellation join run. No database or external supplier runs.
"""
import ast
import asyncio
import copy
from contextlib import AsyncExitStack
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx
from fastapi import HTTPException


MODEL = Path(__file__).resolve().parents[1] / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))
public = importlib.import_module("public_product")
admission = importlib.import_module("model_admission")
SOURCE = (MODEL / "api.py").read_text()


def _api_blocks(source, namespace):
    tree = ast.parse(source)
    names = {"_await_media_worker", "_await_media_completion",
             "_await_remote_media_worker", "_generation_image_observation",
             "_generation_image_observation_batch"}
    functions = [copy.deepcopy(n) for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])),
                 "actual_api_nine_image_helpers", "exec"), namespace)
    candidates = [n for n in ast.walk(tree) if isinstance(n, ast.If)]
    analyze = next(n for n in candidates if isinstance(n.test, ast.Attribute)
                   and isinstance(n.test.value, ast.Name) and n.test.value.id == "req"
                   and n.test.attr == "extra_images")
    video = next(n for n in candidates if isinstance(n.test, ast.Name)
                 and n.test.id == "accompanying_images")
    for name, block, setup, result in (
        ("actual_analysis_images", analyze,
         "extra_image_context = ''; agent_context_parts = []", "extra_results"),
        ("actual_video_images", video,
         "accompanying_images = req.extra_images[:9]; domain = req.domain; "
         "raw_material_brief = req.desc; video_desc = 'synthetic video observation'; "
         "image_desc = video_desc; vis_result = {}", "image_results"),
    ):
        wrapper = ast.parse("async def " + name + "(req):\n pass\n").body[0]
        wrapper.body = (ast.parse(setup).body + [copy.deepcopy(block)]
                        + [ast.Return(value=ast.Name(id=result, ctx=ast.Load()))])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                     "actual_api_nine_image_entry_block", "exec"), namespace)
    return namespace


class NineImageFanoutCapacityTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
            "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64", "NOTEAI_MODEL_PENDING_CALLS": "512",
            "NOTEAI_MEDIA_WORKER_CONCURRENCY": "2", "NOTEAI_MODEL_BUFFER_MIB": "256",
            "NOTEAI_MODEL_ADMITTED_OPERATIONS": "100", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "",
        }, clear=True)
        self.environment.start()
        self.manager = admission.Admission()
        self.manager_patch = mock.patch.object(admission, "_instance", self.manager)
        self.manager_patch.start()
        self.network = [mock.patch.object(socket.socket, n,
            side_effect=AssertionError("No external supplier socket allowed"))
            for n in ("connect", "connect_ex")]
        for patch in self.network:
            patch.start()

    def tearDown(self):
        self.manager.close_remote_workers()
        for queue in (self.manager.media, self.manager.buffers, self.manager.calls):
            self.assertEqual(queue.active, {})
            self.assertEqual(queue._tickets(), [])
        self.assertEqual(self.manager.operations, {})
        self.manager_patch.stop()
        for patch in reversed(self.network):
            patch.stop()
        self.environment.stop()

    def test_hundred_nine_image_diagnoses_keep_all_images_without_queue_full(self):
        self._hundred("actual_analysis_images", start_index=1)

    def test_hundred_video_accompanying_nines_keep_all_images_without_queue_full(self):
        self._hundred("actual_video_images", start_index=0)

    def _hundred(self, entry_name, *, start_index):
        release_cpu = threading.Event()
        state = {"cpu": 0, "peak_cpu": 0, "enqueue": 0, "remote": 0}
        lock = threading.Lock()
        indices, prepared, results = [], [], []

        def prepare(image, domain, brief):
            with lock:
                state["cpu"] += 1
                state["peak_cpu"] = max(state["peak_cpu"], state["cpu"])
                prepared.append((image, domain, brief))
            try:
                if not release_cpu.wait(15):
                    raise AssertionError("Controlled image preparation not released")
                return {"image": image}, 1024
            finally:
                with lock:
                    state["cpu"] -= 1

        def supplier(request):
            with lock:
                state["remote"] += 1
            return httpx.Response(200, text="original image " + request.url.params["image"])

        client = httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)
        self.addCleanup(client.close)

        def observe(prepared_image):
            return client.get("https://synthetic.invalid/observe",
                              params={"image": prepared_image["image"]}).text

        async def progress(*args, **kwargs):
            return None

        namespace = _api_blocks(SOURCE, {"asyncio": asyncio, "AsyncExitStack": AsyncExitStack,
            "_public_product": public, "_emit_progress": progress, "emit": None,
            "HTTPException": HTTPException, "_prepare_buffered_image_observation": prepare,
            "_call_prepared_image_observation": observe})
        original_observation = namespace["_generation_image_observation"]

        async def indexed(image, domain, brief, index):
            indices.append((public._invocation.get().user_id, index, image))
            return await original_observation(image, domain, brief, index)

        namespace["_generation_image_observation"] = indexed
        original_enqueue = self.manager.media.enqueue

        def enqueue(*args, **kwargs):
            state["enqueue"] += 1
            return original_enqueue(*args, **kwargs)

        async def scenario():
            async def task(index):
                user = "nine-fanout-%03d" % index
                op, owns = self.manager.register(user, user, route="/analyze/stream")
                self.assertTrue(owns)
                marker = public._invocation.set(public.Invocation(user, user, admission_state=op))
                req = SimpleNamespace(extra_images=["%03d-%d" % (index, i) for i in range(9)],
                                      domain="休闲娱乐体验", desc="original brief", cover_image=None)
                try:
                    return await namespace[entry_name](req)
                finally:
                    public._invocation.reset(marker)
                    self.manager.finish(op)

            tasks = [asyncio.create_task(task(i)) for i in range(100)]
            # Both the old and new real entry blocks are exercised. Holding the
            # first two preparations makes overflow deterministic, not timing.
            expected_attempts = 200 if "_generation_image_observation_batch" in namespace else 900
            try:
                async def arrived():
                    while state["enqueue"] < expected_attempts or state["peak_cpu"] < 2:
                        await asyncio.sleep(.001)
                await asyncio.wait_for(arrived(), 8)
                before = {**state, "pending": len(self.manager.media._tickets())}
                release_cpu.set()
                results.extend(await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 15))
                failures = [type(value).__name__ for value in results if isinstance(value, BaseException)]
                self.assertEqual(failures, [], "Accepted nine-image reports failed: " + repr(failures[:5]))
                for i, values in enumerate(results):
                    self.assertEqual(values, ["original image %03d-%d" % (i, image) for image in range(9)])
                self.assertEqual((len(prepared), len(indices), state["remote"]), (900, 900, 900))
                for i in range(100):
                    seen = [(index, image) for user, index, image in indices if user == "nine-fanout-%03d" % i]
                    self.assertEqual(seen, [(j + start_index, "%03d-%d" % (i, j)) for j in range(9)])
                self.assertLessEqual(before["pending"], 198)
                self.assertEqual(state["peak_cpu"], 2)
                self.assertTrue(all(domain == "休闲娱乐体验" and brief == "original brief"
                                    for _, domain, brief in prepared))
                print(json.dumps({"entry": entry_name, "owners": 100, "ordered_images": 900,
                    "before_release": before, "mock_http": state["remote"], "supplier_calls": 0,
                    "db_connections": 0, "whole_report_or_real_quality": False}, sort_keys=True))
            finally:
                release_cpu.set()
                for pending in tasks:
                    if not pending.done():
                        pending.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        with mock.patch.object(self.manager.media, "enqueue", enqueue):
            asyncio.run(scenario())

    def test_cancelled_batch_joins_two_started_remote_calls_without_starting_the_other_seven(self):
        started, release = threading.Event(), threading.Event()
        calls, finished = [], []
        lock = threading.Lock()

        def remote(prepared):
            with lock:
                calls.append(prepared["image"])
                if len(calls) == 2:
                    started.set()
            if not release.wait(8):
                raise AssertionError("Controlled cancelled remote not released")
            finished.append(prepared["image"])
            return "original " + prepared["image"]

        namespace = _api_blocks(SOURCE, {"asyncio": asyncio, "AsyncExitStack": AsyncExitStack,
            "_public_product": public, "HTTPException": HTTPException,
            "_prepare_buffered_image_observation": lambda image, *_: ({"image": image}, 1024),
            "_call_prepared_image_observation": remote})

        async def scenario():
            op, _ = self.manager.register("cancel-nine-owner", "cancel-nine", route="/analyze/stream")
            marker = public._invocation.set(public.Invocation("cancel-nine-owner", "cancel-nine",
                                                              admission_state=op))
            task = asyncio.create_task(namespace["_generation_image_observation_batch"](
                [str(i) for i in range(9)], "休闲娱乐体验", "original brief"))
            try:
                async def active():
                    while not started.is_set():
                        await asyncio.sleep(.001)
                await asyncio.wait_for(active(), 3)
                self.assertEqual(self.manager.media.active, {}, "Remote waits held CPU admission")
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done(), "Cancellation dropped already started remote calls")
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertCountEqual(calls, ["0", "1"])
                self.assertCountEqual(finished, calls)
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                public._invocation.reset(marker)
                self.manager.finish(op)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
