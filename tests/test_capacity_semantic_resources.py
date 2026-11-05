"""Real async semantic call sites must not occupy the image CPU executor.

The original semantic Prompt formatting/parser and all five actual await
expressions run. Responses are synthetic; no remote model, database or payment.
"""
import ast
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
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

MODEL = Path(__file__).resolve().parents[1] / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))
public = importlib.import_module("public_product")
admission = importlib.import_module("model_admission")
SOURCE = (MODEL / "api.py").read_text()
COLUMNS = ("semantic_emotional_intensity", "semantic_empathetic_engagement", "semantic_rhetorical_score")
VALUES = dict(zip(COLUMNS, (.2, .6, .9)))


def _load_api(backend):
    tree = ast.parse(SOURCE)
    names = {"_await_media_worker", "_await_media_completion", "_await_remote_media_worker", "compute_semantic_features"}
    namespace = {"asyncio": asyncio, "_public_product": public,
        "_mr": SimpleNamespace(call_semantic_sync=backend), "SEMANTIC_FEATURE_COLS": COLUMNS,
        "_KIMI_SEMANTIC_PROMPT": lambda: "标题：{title}\n正文：{desc}"}
    selected = [copy.deepcopy(n) for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                 "actual_semantic_feature_helpers", "exec"), namespace)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and isinstance(n.value, ast.Await) and isinstance(n.value.value, ast.Call)
             and n.value.value.args and isinstance(n.value.value.args[0], ast.Name)
             and n.value.value.args[0].id == "compute_semantic_features"]
    hops = []
    for index, assignment in enumerate(sorted(calls, key=lambda n: n.lineno)):
        name = "actual_semantic_hop_%d" % index
        function = ast.parse("async def " + name + "(title, body, req):\n pass\n").body[0]
        target = assignment.targets[0]
        assert isinstance(target, ast.Name)
        function.body = [copy.deepcopy(assignment), ast.Return(ast.Name(id=target.id, ctx=ast.Load()))]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     "actual_semantic_await_entry", "exec"), namespace)
        hops.append((name, assignment.lineno, ast.unparse(assignment.value.value.func)))
    return namespace, hops


class SemanticResourcesTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64",
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": ""}, clear=True)
        self.environment.start()
        self.manager = admission.Admission()
        self.manager_patch = mock.patch.object(admission, "_instance", self.manager)
        self.manager_patch.start()
        self.network = [mock.patch.object(socket.socket, name,
            side_effect=AssertionError("No supplier socket allowed")) for name in ("connect", "connect_ex")]
        for patch in self.network:
            patch.start()
        self.started, self.finished, self.calls = [], [], []
        self.release, self.both = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.unknown = False
        self.api, self.hops = _load_api(self._backend)

    def tearDown(self):
        self.release.set()
        self.manager.close_remote_workers()
        self.assertEqual(self.manager.operations, {})
        self.manager_patch.stop()
        for patch in reversed(self.network):
            patch.stop()
        self.environment.stop()

    def _backend(self, **kwargs):
        owner = public._invocation.get().user_id
        with self.lock:
            self.started.append((owner, threading.current_thread().name))
            self.calls.append(kwargs)
            if len(self.started) == 2:
                self.both.set()
        if not self.release.wait(8):
            raise AssertionError("Controlled semantic response not released")
        self.finished.append(owner)
        if self.unknown:
            public._invocation.get().failure = "PUBLIC_TRIAL_OUTCOME_UNKNOWN"
            raise public.TrialProviderStopped("PUBLIC_TRIAL_OUTCOME_UNKNOWN")
        return "```json\n" + json.dumps(VALUES) + "\n```"

    async def _run(self, hop, owner):
        operation, owns = self.manager.register(owner, owner, route="/generate/stream")
        self.assertTrue(owns)
        marker = public._invocation.set(public.Invocation(owner, owner, admission_state=operation))
        try:
            req = SimpleNamespace(note_title=" 标题 ", desc=" 正文 ", note_body=" 正文 ")
            return await self.api[self.hops[hop][0]](" 标题 ", " 正文 ", req)
        finally:
            public._invocation.reset(marker)
            self.manager.finish(operation)

    async def _wait(self, predicate):
        async def ready():
            while not predicate():
                await asyncio.sleep(.001)
        await asyncio.wait_for(ready(), 4)

    def test_two_held_semantic_calls_leave_cpu_free_and_all_five_entry_contracts_match(self):
        self.assertEqual(len(self.hops), 5)
        async def scenario():
            asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2,
                thread_name_prefix="controlled-semantic-cpu"))
            tasks = [asyncio.create_task(self._run(i, "semantic-%d" % i)) for i in (0, 4)]
            cpu = None
            try:
                await self._wait(self.both.is_set)
                cpu = asyncio.create_task(self.api["_await_media_worker"](lambda: "CPU_READY"))
                self.assertEqual(await asyncio.wait_for(asyncio.shield(cpu), .5), "CPU_READY")
                self.assertFalse(self.release.is_set())
                self.assertTrue(all(name.startswith("noteai-model-io") for _, name in self.started))
                self.release.set()
                self.assertEqual(await asyncio.gather(*tasks), [VALUES, VALUES])
                self.assertEqual(await asyncio.gather(*(self._run(i, "semantic-%d" % i) for i in (1, 2, 3))),
                                 [VALUES, VALUES, VALUES])
                self.assertEqual(len(self.calls), 5)
                self.assertTrue(all(function == "_await_remote_media_worker" for _, _, function in self.hops))
                for call in self.calls:
                    self.assertEqual(call, {"system": "你是小红书笔记语义分析专家，只返回JSON，不要解释。",
                        "user": "标题：标题\n正文：正文", "max_tokens": 120,
                        "trace_step": "semantic_features", "prompt_keys": ("semantic_features",)})
            finally:
                self.release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                if cpu is not None:
                    await cpu
        asyncio.run(scenario())

    def test_cancellation_joins_the_original_unknown_semantic_call_once(self):
        self.unknown = True
        async def scenario():
            task = asyncio.create_task(self._run(4, "semantic-cancel"))
            try:
                await self._wait(lambda: len(self.started) == 1)
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done(), "The old unshielded to_thread discarded semantic accounting")
                self.assertEqual(self.finished, [])
                self.release.set()
                with self.assertRaisesRegex(public.TrialProviderStopped, "PUBLIC_TRIAL_OUTCOME_UNKNOWN"):
                    await task
                self.assertEqual(self.finished, ["semantic-cancel"])
                self.assertEqual(len(self.calls), 1, "Original UNKNOWN call was retried")
            finally:
                self.release.set()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
