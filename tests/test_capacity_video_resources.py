"""Original AV waits share remote I/O, while bytes are guarded before loading.

Actual selected API functions, media/buffer admission and cancellation joins run.
The AV backend is synthetic. Large metadata sizes never allocate large payloads;
these tests prove admission order/lifetime, not video decoding or vendor quality.
"""
import ast
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

from fastapi import HTTPException

MODEL = Path(__file__).resolve().parents[1] / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))
public = importlib.import_module("public_product")
admission = importlib.import_module("model_admission")
capacity = importlib.import_module("model_capacity")
SOURCE = (MODEL / "api.py").read_text()
MIB = 1024 * 1024


def _load_api(storage, metadata):
    names = {"_await_media_worker", "_await_media_completion", "_await_remote_media_worker",
             "_get_video_meta", "_video_buffer_bytes", "_video_meta_context", "_kimi_video_understand"}
    tree = ast.parse(SOURCE)
    selected = [copy.deepcopy(n) for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    namespace = {"asyncio": asyncio, "asynccontextmanager": asynccontextmanager,
        "_public_product": public, "_private_storage": storage,
        "_original_video_metadata": metadata, "_uuid": uuid,
        "_json": json, "os": os, "re": re, "HTTPException": HTTPException}
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                 "actual_capacity_video_helpers", "exec"), namespace)
    return namespace, tree


class VideoResourcesTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
            "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64", "NOTEAI_MODEL_BUFFER_MIB": "256",
            "NOTEAI_MEDIA_WORKER_CONCURRENCY": "2", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "",
            "NOTEAI_ARK_VIDEO_INPUT": "private_oss", "NOTEAI_DEPLOYMENT_STAGE": "production",
        }, clear=True)
        self.environment.start()
        self.manager = admission.Admission()
        self.manager_patch = mock.patch.object(admission, "_instance", self.manager)
        self.manager_patch.start()
        self.network = [mock.patch.object(socket.socket, name,
            side_effect=AssertionError("No supplier socket allowed")) for name in ("connect", "connect_ex")]
        for patch in self.network:
            patch.start()
        self.refs, self.operations, self.metas = {}, {}, {}
        self.events, self.started, self.finished, self.prompts = [], [], [], []
        self.release, self.both_started = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.unknown = False

        class StorageError(Exception):
            pass

        self.storage = SimpleNamespace(PrivateStorageError=StorageError,
            get_ready_media_reference=self._reference, load_media_bytes=self._payload,
            understand_original_video=self._remote)
        self.api, self.tree = _load_api(self.storage, self._metadata)

    def tearDown(self):
        self.release.set()
        self.manager.close_remote_workers()
        for queue in (self.manager.media, self.manager.buffers):
            self.assertEqual(queue.active, {})
            self.assertEqual(queue._tickets(), [])
        self.assertEqual(self.manager.operations, {})
        self.manager_patch.stop()
        for patch in reversed(self.network):
            patch.stop()
        self.environment.stop()

    def _user(self):
        return public._invocation.get().user_id

    def _reference(self, file_id, *, user_id):
        self.assertEqual(self.refs[file_id].owner, user_id)
        self.events.append((user_id, "metadata"))
        return self.refs[file_id]

    def _payload(self, file_id, *, user_id):
        self.assertEqual(self.refs[file_id].owner, user_id)
        if capacity.enabled():
            with self.manager.buffers.lock:
                buffers = [t for t in self.manager.buffers.active.values()
                           if t.operation is self.operations[user_id]]
            with self.manager.media.lock:
                cpu = [t for t in self.manager.media.active.values()
                       if t.operation is self.operations[user_id]]
            self.assertEqual(len(buffers), 1, "Original AV read preceded byte reservation")
            self.assertEqual(len(cpu), 1, "Payload/decode bypassed the existing CPU guard")
        self.events.append((user_id, "payload"))
        return self.refs[file_id], b"synthetic-small-AV"

    def _metadata(self, _body):
        value = {"duration_sec": 12.5, "raw_fps": 30, "frames": [b"preview"],
                 "original_video": True, "analysis_fps": 2.0}
        self.metas[self._user()] = value
        return value

    def _remote(self, reference, body, prompt):
        self.assertEqual(body, b"synthetic-small-AV")
        self.assertEqual(reference.owner, self._user())
        with self.lock:
            self.started.append((reference.owner, threading.current_thread().name))
            self.prompts.append(prompt)
            if len(self.started) == 2:
                self.both_started.set()
        if not self.release.wait(8):
            raise AssertionError("Controlled AV backend was not released")
        self.finished.append(reference.owner)
        if self.unknown:
            raise public.TrialProviderStopped("ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY")
        return "complete synthetic original AV observation"

    async def _run(self, owner, size=MIB):
        file_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, owner))
        self.refs[file_id] = SimpleNamespace(id=file_id, owner=owner, purpose="video", size_bytes=size)
        operation, owns = self.manager.register(owner, owner, route="/generate/stream")
        self.assertTrue(owns)
        self.operations[owner] = operation
        marker = public._invocation.set(public.Invocation(owner, owner, admission_state=operation))
        try:
            return await self.api["_kimi_video_understand"](file_id, "休闲娱乐体验",
                "原始背景", user_id=owner)
        finally:
            public._invocation.reset(marker)
            self.manager.finish(operation)

    async def _wait(self, predicate):
        async def ready():
            while not predicate():
                await asyncio.sleep(.001)
        await asyncio.wait_for(ready(), 4)

    def test_two_remote_videos_leave_default_cpu_executor_available_and_preserve_metadata(self):
        async def scenario():
            asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2,
                thread_name_prefix="controlled-default-cpu"))
            tasks = [asyncio.create_task(self._run("video-cpu-%d" % i)) for i in range(2)]
            cpu = None
            try:
                await self._wait(self.both_started.is_set)
                cpu = asyncio.create_task(self.api["_await_media_worker"](lambda: "CPU_READY"))
                self.assertEqual(await asyncio.wait_for(asyncio.shield(cpu), .5), "CPU_READY",
                                 "Whole AV HTTP occupied the default CPU executor")
                self.assertFalse(self.release.is_set())
                self.assertEqual(self.manager.media.active, {})
                self.assertEqual(len(self.manager.buffers.active), 2)
                self.assertTrue(all(name.startswith("noteai-model-io") for _, name in self.started))
                self.release.set()
                self.assertEqual(await asyncio.gather(*tasks),
                                 ["complete synthetic original AV observation"] * 2)
                for metadata in self.metas.values():
                    self.assertNotIn("original_bytes", metadata)
                    self.assertEqual((metadata["duration_sec"], metadata["frames"]), (12.5, [b"preview"]))
                self.assertTrue(all("画面按2fps处理" in p and "原始背景" in p for p in self.prompts))
            finally:
                self.release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                if cpu is not None:
                    await cpu
        asyncio.run(scenario())

    def test_large_metadata_reserves_before_payload_and_backpressures_other_owners(self):
        async def scenario():
            tasks = [asyncio.create_task(self._run("video-large-%d" % i, 100 * MIB)) for i in range(3)]
            try:
                await self._wait(lambda: len([e for e in self.events if e[1] == "metadata"]) == 3
                                 and len(self.started) == 1)
                self.assertEqual(len([e for e in self.events if e[1] == "payload"]), 1)
                self.assertEqual(sum(t.weight for t in self.manager.buffers.active.values()), 202 * MIB)
                self.assertEqual(len(self.manager.buffers._tickets()), 2)
                self.assertEqual(self.manager.media.active, {})
                self.release.set()
                results = await asyncio.gather(*tasks)
                self.assertEqual(len(results), 3)
                for owner in self.operations:
                    sequence = [event for uid, event in self.events if uid == owner]
                    self.assertEqual(sequence, ["metadata", "payload"])
                    self.assertNotIn("original_bytes", self.metas[owner])
                self.assertEqual(len(self.started), 3)
            finally:
                self.release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.run(scenario())

    def test_cancel_joins_unknown_original_once_before_body_and_budget_release(self):
        self.unknown = True
        async def scenario():
            task = asyncio.create_task(self._run("video-cancel-unknown"))
            try:
                await self._wait(lambda: len(self.started) == 1)
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done())
                self.assertIn("original_bytes", self.metas["video-cancel-unknown"])
                self.assertEqual(len(self.manager.buffers.active), 1)
                self.assertEqual(self.finished, [])
                self.release.set()
                with self.assertRaisesRegex(public.TrialProviderStopped,
                                            "ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY"):
                    await task
                self.assertEqual(len(self.started), 1, "UNKNOWN was dispatched again")
                self.assertEqual(self.finished, ["video-cancel-unknown"])
                self.assertNotIn("original_bytes", self.metas["video-cancel-unknown"])
            finally:
                self.release.set()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(scenario())

    def test_inline_file_budget_legacy_behavior_and_all_current_callers_use_context(self):
        ref = SimpleNamespace(purpose="video", size_bytes=46 * MIB)
        with mock.patch.dict(os.environ, {"NOTEAI_ARK_VIDEO_INPUT": "files"}):
            self.assertEqual(self.api["_video_buffer_bytes"](ref),
                ref.size_bytes + 3 * (4 * ((ref.size_bytes + 2) // 3)) + 2 * MIB)
            self.assertLessEqual(self.api["_video_buffer_bytes"](ref), 256 * MIB)
            ref.size_bytes = 100 * MIB
            self.assertEqual(self.api["_video_buffer_bytes"](ref), 202 * MIB)
        for name in ("_run_analyze_pipeline", "_generate_pipeline_stream"):
            function = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
            contexts = [n for n in ast.walk(function) if isinstance(n, ast.AsyncWith)
                        and any(isinstance(item.context_expr, ast.Call)
                                and isinstance(item.context_expr.func, ast.Name)
                                and item.context_expr.func.id == "_video_meta_context" for item in n.items)]
            self.assertEqual(len(contexts), 1, "Actual caller bypasses the pre-load guard: " + name)
            self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                and n.func.id == "_kimi_video_understand" for n in ast.walk(contexts[0])))
        direct = [(n.lineno, n.func.id) for n in ast.walk(self.tree) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == "_get_video_meta"]
        self.assertEqual(direct, [], "A new direct payload read bypassed the resource context")
        self.release.set()
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0"}):
            asyncio.run(self._run("video-legacy"))
        self.assertIn("original_bytes", self.metas["video-legacy"], "Legacy behavior changed outside modeon")


if __name__ == "__main__":
    unittest.main()
