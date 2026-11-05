"""Actual screenshot/chat image call blocks retain their contracts under load.

Pillow parsing, local resource queues and cancellation joins are real. Supplier
HTTP is MockTransport, with no database, billing or external model operations.
"""
import ast
import asyncio
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
import importlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx
from fastapi import HTTPException
from PIL import Image

MODEL = Path(__file__).resolve().parents[1] / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))
public = importlib.import_module("public_product")
admission = importlib.import_module("model_admission")
ark = importlib.import_module("ark_media")
capacity = importlib.import_module("model_capacity")
SOURCE = (MODEL / "api.py").read_text()


def _load_api(backend):
    tree = ast.parse(SOURCE)
    selected = {"_await_media_worker", "_await_media_completion", "_await_remote_media_worker",
        "_read_image_input", "_image_media_type", "_data_url_from_image_b64",
        "_prepared_media_buffer_bytes", "_prepare_buffered_ark_image_chat", "_buffered_ark_image_chat"}
    namespace = {"asyncio": asyncio, "AsyncExitStack": AsyncExitStack,
        "_public_product": public, "_ark_media": backend, "base64": base64,
        "_json": json, "re": re, "HTTPException": HTTPException}
    functions = [copy.deepcopy(n) for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in selected]
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])),
                 "actual_aux_image_helpers", "exec"), namespace)
    screenshot = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "extract_screenshot")
    finish = next(n for n in screenshot.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "finish")
    prompt = next(n for n in finish.body if isinstance(n, ast.Assign))
    image_try = next(n for n in finish.body if isinstance(n, ast.Try))
    raw_index = next(i for i, n in enumerate(image_try.body) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "raw" for target in n.targets for t in ast.walk(target)))
    chat = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_chat_sse_generator")
    image_if = next(n for n in chat.body if isinstance(n, ast.If)
                    and isinstance(n.test, ast.Name) and n.test.id == "image_base64")
    chat_try = next(n for n in image_if.body if isinstance(n, ast.Try))
    for name, setup, body, result in (
        ("actual_screenshot_image_call", "req = SimpleNamespace(image_base64=image)",
         [prompt, *image_try.body[:raw_index + 1]], "(raw, media_type)"),
        ("actual_chat_image_call", "session = {'domain':'休闲娱乐体验'}; image_base64 = image",
         chat_try.body, "image_analysis"),
    ):
        wrapper = ast.parse("async def " + name + "(image):\n pass\n").body[0]
        wrapper.body = ast.parse(setup).body + copy.deepcopy(body) + ast.parse("return " + result).body
        namespace["SimpleNamespace"] = SimpleNamespace
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                     "actual_aux_image_entry_call", "exec"), namespace)
    return namespace


class AuxiliaryImageResourcesTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64",
            "NOTEAI_MEDIA_WORKER_CONCURRENCY": "2", "NOTEAI_MODEL_BUFFER_MIB": "256",
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": ""}, clear=True)
        self.environment.start()
        self.manager = admission.Admission()
        self.manager_patch = mock.patch.object(admission, "_instance", self.manager)
        self.manager_patch.start()
        self.network = [mock.patch.object(socket.socket, name,
            side_effect=AssertionError("External model socket forbidden")) for name in ("connect", "connect_ex")]
        for patch in self.network:
            patch.start()
        photo = io.BytesIO()
        Image.new("RGB", (180, 120), (72, 140, 210)).save(photo, "JPEG", quality=90)
        self.photo = photo.getvalue()
        self.image = base64.b64encode(self.photo).decode()
        self.release, self.both = threading.Event(), threading.Event()
        self.started, self.finished, self.kwargs, self.prompts, self.parts = [], [], [], [], []
        self.lock = threading.Lock()
        self.unknown = False
        self.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,
            text="complete original image observation")), trust_env=False)
        self.api = _load_api(SimpleNamespace(image_part=ark.image_part, chat=self._remote, MODEL=ark.MODEL))
        original_reader = self.api["_read_image_input"]

        def reader(image):
            if capacity.enabled() and "_buffered_ark_image_chat" in self.api:
                owner = public._invocation.get().user_id
                with self.manager.media.lock:
                    self.assertTrue(any(t.operation.user_id == owner for t in self.manager.media.active.values()),
                                    "Image read/decode occurred outside CPU preparation admission")
            return original_reader(image)
        self.api["_read_image_input"] = reader

    def tearDown(self):
        self.release.set()
        self.manager.close_remote_workers()
        self.client.close()
        for queue in (self.manager.media, self.manager.buffers):
            self.assertEqual(queue.active, {})
            self.assertEqual(queue._tickets(), [])
        self.assertEqual(self.manager.operations, {})
        self.manager_patch.stop()
        for patch in reversed(self.network):
            patch.stop()
        self.environment.stop()

    def _remote(self, prompt, parts, **kwargs):
        owner = public._invocation.get().user_id
        if capacity.enabled() and "_buffered_ark_image_chat" in self.api:
            with self.manager.buffers.lock:
                self.assertTrue(any(t.operation.user_id == owner for t in self.manager.buffers.active.values()),
                                "Image wire lost its prepared-body memory budget")
            with self.manager.media.lock:
                self.assertFalse(any(t.operation.user_id == owner for t in self.manager.media.active.values()),
                                 "Long image HTTP retained a CPU permit")
        with self.lock:
            self.started.append((owner, threading.current_thread().name))
            self.prompts.append(prompt)
            self.parts.append(parts)
            self.kwargs.append(kwargs)
            if len(self.started) == 2:
                self.both.set()
        if not self.release.wait(8):
            raise AssertionError("Controlled image HTTP not released")
        response = self.client.post("https://synthetic.invalid/image", json={"prompt": prompt, "parts": parts, **kwargs})
        self.finished.append(owner)
        if self.unknown:
            raise public.TrialProviderStopped("ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY")
        return response.text

    async def _run(self, name, owner, image=None):
        op, owns = self.manager.register(owner, owner, route="/extract-screenshot" if "screenshot" in name else "/chat/message")
        self.assertTrue(owns)
        marker = public._invocation.set(public.Invocation(owner, owner, admission_state=op))
        try:
            return await self.api[name](self.image if image is None else image)
        finally:
            public._invocation.reset(marker)
            self.manager.finish(op)

    async def _wait(self, predicate):
        async def ready():
            while not predicate():
                await asyncio.sleep(.001)
        await asyncio.wait_for(ready(), 4)

    def test_actual_two_image_entries_leave_cpu_available_and_retain_original_wire_options(self):
        async def scenario():
            asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2,
                thread_name_prefix="controlled-aux-cpu"))
            tasks = [asyncio.create_task(self._run(name, owner)) for name, owner in
                     (("actual_screenshot_image_call", "aux-screenshot"), ("actual_chat_image_call", "aux-chat"))]
            cpu = None
            try:
                await self._wait(self.both.is_set)
                cpu = asyncio.create_task(self.api["_await_media_worker"](lambda: "CPU_READY"))
                self.assertEqual(await asyncio.wait_for(asyncio.shield(cpu), .5), "CPU_READY")
                self.assertFalse(self.release.is_set())
                self.assertTrue(all(n.startswith("noteai-model-io") for _, n in self.started))
                self.assertEqual(self.manager.media.active, {})
                self.assertEqual(len(self.manager.buffers.active), 2)
                self.release.set()
                screenshot, chat = await asyncio.gather(*tasks)
                self.assertEqual(screenshot, ("complete original image observation", "image/jpeg"))
                self.assertEqual(chat, "complete original image observation")
                observed = {owner: kwargs for (owner, _), kwargs in zip(self.started, self.kwargs)}
                self.assertEqual(observed, {"aux-screenshot": {"max_tokens": 8192, "json_output": True},
                                            "aux-chat": {"max_tokens": 4096}})
                self.assertTrue(all(p == [ark.image_part(self.photo)] for p in self.parts))
            finally:
                self.release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                if cpu is not None:
                    await cpu
        asyncio.run(scenario())

    def test_cancel_retains_body_until_original_unknown_call_finishes_without_retry(self):
        self.unknown = True
        async def scenario():
            task = asyncio.create_task(self._run("actual_screenshot_image_call", "aux-cancel"))
            try:
                await self._wait(lambda: len(self.started) == 1)
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done())
                self.assertEqual(len(self.manager.buffers.active), 1)
                self.assertEqual(self.finished, [])
                self.release.set()
                with self.assertRaisesRegex(public.TrialProviderStopped, "ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY"):
                    await task
                self.assertEqual(len(self.started), 1)
                self.assertEqual(self.finished, ["aux-cancel"])
            finally:
                self.release.set()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(scenario())

    def test_screenshot_validation_precedes_provider_and_legacy_options_remain_compatible(self):
        async def invalid():
            with self.assertRaises(HTTPException) as error:
                await self._run("actual_screenshot_image_call", "aux-invalid", "invalid!base64")
            self.assertEqual(error.exception.status_code, 422)
            self.assertEqual(self.started, [])
        asyncio.run(invalid())
        self.release.set()
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0"}):
            result = asyncio.run(self._run("actual_screenshot_image_call", "aux-legacy"))
        self.assertEqual(result, ("complete original image observation", "image/jpeg"))
        self.assertEqual(self.kwargs, [{"max_tokens": 8192, "json_output": True}])


if __name__ == "__main__":
    unittest.main()
