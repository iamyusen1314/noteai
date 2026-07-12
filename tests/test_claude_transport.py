import ast
import asyncio
import importlib
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

model_router = importlib.import_module("model_router")
api = importlib.import_module("api")


_ANTHROPIC_CONSTRUCTORS = frozenset({"Anthropic", "AsyncAnthropic"})
_EXPECTED_RUNTIME_CONSTRUCTORS = [
    ("model/model_router.py", "LocalAnthropicTransport._get_async_client", "AsyncAnthropic", "direct"),
    ("model/model_router.py", "LocalAnthropicTransport._get_sync_client", "Anthropic", "direct"),
]
_EXPECTED_GATEWAY_CONSTRUCTORS = [
    ("gateway/claude_gateway.py", "AnthropicProvider._get_client", "AsyncAnthropic", "direct"),
]
_EXPECTED_OFFLINE_CONSTRUCTORS = [
    ("model/extract_cover_features.py", "run_vision_batch", "Anthropic", "direct"),
    ("tools/ai_prelabel_review_batch.py", "_call_claude_json", "Anthropic", "direct"),
    ("tools/live_ai_smoke.py", "_call_claude", "Anthropic", "direct"),
]


class _AnthropicConstructorVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str, tree: ast.AST):
        self.relative_path = relative_path
        self.module_aliases: set[str] = set()
        self.constructor_aliases: dict[str, str] = {}
        self.importlib_aliases: set[str] = set()
        self.import_module_aliases: set[str] = set()
        self.scope: list[str] = []
        self.findings: list[tuple[str, str, str, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "anthropic":
                        self.module_aliases.add(alias.asname or "anthropic")
                    elif alias.name == "importlib":
                        self.importlib_aliases.add(alias.asname or "importlib")
            elif isinstance(node, ast.ImportFrom) and node.module == "anthropic":
                for alias in node.names:
                    if alias.name in _ANTHROPIC_CONSTRUCTORS:
                        self.constructor_aliases[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        self.import_module_aliases.add(alias.asname or alias.name)

    def _scope_name(self) -> str:
        return ".".join(self.scope) or "<module>"

    def _record(self, constructor: str, mode: str) -> None:
        self.findings.append((
            self.relative_path,
            self._scope_name(),
            constructor,
            mode,
        ))

    def _constructor_reference(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.constructor_aliases.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _ANTHROPIC_CONSTRUCTORS
            and isinstance(node.value, ast.Name)
            and node.value.id in self.module_aliases
        ):
            return node.attr
        return None

    def _is_anthropic_module_reference(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in self.module_aliases:
            return True
        if not isinstance(node, ast.Call) or not node.args:
            return False
        imports_anthropic = (
            isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "anthropic"
        )
        if not imports_anthropic:
            return False
        if isinstance(node.func, ast.Name):
            return node.func.id == "__import__" or node.func.id in self.import_module_aliases
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self.importlib_aliases
            and node.func.attr == "import_module"
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        constructor = self._constructor_reference(node.func)
        if constructor:
            self._record(constructor, "direct")
        elif (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and self._is_anthropic_module_reference(node.args[0])
        ):
            dynamic_name = (
                str(node.args[1].value)
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                else "<dynamic>"
            )
            self._record(dynamic_name, "dynamic_getattr")
        elif self._is_anthropic_module_reference(node):
            self._record("<dynamic>", "dynamic_import")
        elif (
            isinstance(node.func, ast.Name)
            and node.func.id in {"eval", "exec"}
            and any(
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and "Anthropic" in arg.value
                for arg in node.args
            )
        ):
            self._record("<dynamic>", "dynamic_eval")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        constructor = self._constructor_reference(node.value)
        if constructor:
            self._record(constructor, "constructor_alias_assignment")
        self.generic_visit(node)


def _repository_anthropic_constructors() -> list[tuple[str, str, str, str]]:
    findings: list[tuple[str, str, str, str]] = []
    for dirname in ("model", "scripts", "tools", "gateway"):
        for path in sorted((ROOT / dirname).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visitor = _AnthropicConstructorVisitor(path.relative_to(ROOT).as_posix(), tree)
            visitor.visit(tree)
            findings.extend(visitor.findings)
    return sorted(findings)


class _FakeClaudeTransport:
    def __init__(self):
        self.async_requests = []
        self.sync_requests = []
        self.stream_requests = []
        self.async_result = model_router.ClaudeMessageResult(("async-result",), {"input_tokens": 1})
        self.sync_result = model_router.ClaudeMessageResult(("sync-", "result"), {"input_tokens": 2})
        self.stream_events = [
            model_router.ClaudeStreamEvent("thinking", text="private"),
            model_router.ClaudeStreamEvent("content", text="public"),
            model_router.ClaudeStreamEvent("usage", usage={"output_tokens": 3}),
        ]

    async def create_message(self, request):
        self.async_requests.append(request)
        return self.async_result

    def create_message_sync(self, request):
        self.sync_requests.append(request)
        return self.sync_result

    async def stream_message(self, request):
        self.stream_requests.append(request)
        for event in self.stream_events:
            yield event


class ClaudeTransportTests(unittest.TestCase):
    def setUp(self):
        self.original_transport = model_router._CLAUDE_TRANSPORT
        self.transport = _FakeClaudeTransport()
        model_router.set_claude_transport(self.transport)

    def tearDown(self):
        model_router.set_claude_transport(self.original_transport)

    def test_non_stream_calls_preserve_temperature_and_thinking_contract(self):
        with mock.patch.object(model_router, "_record_claude_usage") as record_usage:
            fast = asyncio.run(model_router._call_claude(
                model_router.CLAUDE_HAIKU,
                "system-fast",
                "user-fast",
                thinking=False,
                max_tokens=1200,
            ))
            deep = asyncio.run(model_router._call_claude(
                model_router.CLAUDE_SONNET,
                "system-deep",
                "user-deep",
                thinking=True,
                max_tokens=6000,
            ))

        self.assertEqual((fast, deep), ("async-result", "async-result"))
        fast_request, deep_request = self.transport.async_requests
        self.assertEqual(fast_request.temperature, 0.7)
        self.assertIsNone(fast_request.thinking_budget)
        self.assertEqual(fast_request.system, "system-fast")
        self.assertEqual(fast_request.messages, ({"role": "user", "content": "user-fast"},))
        self.assertIsNone(deep_request.temperature)
        self.assertEqual(deep_request.thinking_budget, 5000)
        self.assertEqual(deep_request.model, model_router.CLAUDE_SONNET)
        self.assertEqual(record_usage.call_count, 2)

    def test_stream_and_chat_preserve_history_thinking_and_terminal_usage(self):
        async def collect(stream):
            return [item async for item in stream]

        history = [{"role": "assistant", "content": "prior"}]
        with mock.patch.object(model_router, "_record_claude_usage") as record_usage:
            ordinary = asyncio.run(collect(model_router._stream_claude(
                model_router.CLAUDE_HAIKU,
                "stream-system",
                "next",
                thinking=True,
                max_tokens=16000,
                history=history,
            )))
            chat = asyncio.run(collect(model_router.stream_chat(
                system="chat-system",
                history=[
                    {"role": "system", "content": "ignored"},
                    {"role": "assistant", "content": "kept", "reasoning_content": "removed"},
                ],
                user_content="chat-user",
                thinking=False,
                max_tokens=2048,
            )))

        self.assertEqual(ordinary, [("thinking", "private"), ("content", "public")])
        self.assertEqual(chat, [("thinking", "private"), ("content", "public")])
        ordinary_request, chat_request = self.transport.stream_requests
        self.assertEqual(ordinary_request.thinking_budget, 10000)
        self.assertEqual(ordinary_request.messages[-1], {"role": "user", "content": "next"})
        self.assertEqual(chat_request.model, model_router.CLAUDE_SONNET)
        self.assertEqual(chat_request.temperature, 0.7)
        self.assertIsNone(chat_request.thinking_budget)
        self.assertEqual(chat_request.messages, (
            {"role": "assistant", "content": "kept"},
            {"role": "user", "content": "chat-user"},
        ))
        self.assertEqual(record_usage.call_count, 2)
        self.assertEqual(record_usage.call_args_list[0].args[1], {"output_tokens": 3})

    def test_semantic_sync_uses_same_transport_with_temperature_point_three(self):
        with mock.patch.object(model_router, "_record_claude_usage") as record_usage:
            result = model_router.call_semantic_sync("semantic-system", "semantic-user", 120)

        self.assertEqual(result, "sync-result")
        request = self.transport.sync_requests[0]
        self.assertEqual(request.model, model_router.CLAUDE_HAIKU)
        self.assertEqual(request.temperature, 0.3)
        self.assertEqual(request.system, "semantic-system")
        self.assertEqual(record_usage.call_count, 1)

    def test_legacy_analyze_fallback_uses_transport_boundary_without_system_or_temperature(self):
        xml = (
            "<diagnosis>diag</diagnosis><titles>title</titles>"
            "<plan>plan</plan><body>body</body>"
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             mock.patch.object(api._mr, "call_claude_sync", return_value=xml) as call_sync:
            parsed = api._call_claude("legacy-prompt")

        self.assertEqual(parsed, ("diag", ["title"], "plan", "body"))
        self.assertEqual(call_sync.call_args.kwargs, {
            "model": api.CLAUDE_MODEL,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": "legacy-prompt"}],
            "first_text_block": True,
        })

    def test_runtime_sdk_clients_are_created_only_inside_local_transport(self):
        router_source = (MODEL_DIR / "model_router.py").read_text(encoding="utf-8")
        api_source = (MODEL_DIR / "api.py").read_text(encoding="utf-8")
        local_start = router_source.index("class LocalAnthropicTransport")
        local_end = router_source.index("_CLAUDE_TRANSPORT:", local_start)
        creation_positions = [
            match.start()
            for match in re.finditer(r"anthropic\.(?:AsyncAnthropic|Anthropic)\(", router_source)
        ]
        self.assertEqual(len(creation_positions), 2)
        self.assertTrue(all(local_start < position < local_end for position in creation_positions))
        self.assertNotIn("import anthropic", api_source)
        self.assertNotRegex(api_source, r"anthropic\.(?:AsyncAnthropic|Anthropic)\(")

    def test_repository_anthropic_constructors_match_fixed_runtime_and_offline_allowlists(self):
        observed = _repository_anthropic_constructors()
        expected = sorted(
            _EXPECTED_RUNTIME_CONSTRUCTORS
            + _EXPECTED_GATEWAY_CONSTRUCTORS
            + _EXPECTED_OFFLINE_CONSTRUCTORS
        )
        self.assertEqual(
            observed,
            expected,
            "Anthropic client construction changed; route runtime calls through "
            "ClaudeTransport or explicitly review the offline allowlist",
        )
        self.assertEqual(
            [item for item in observed if item[0] == "model/model_router.py"],
            sorted(_EXPECTED_RUNTIME_CONSTRUCTORS),
        )
        self.assertEqual(
            [item for item in observed if item[0] == "gateway/claude_gateway.py"],
            sorted(_EXPECTED_GATEWAY_CONSTRUCTORS),
        )
        self.assertEqual(
            [
                item for item in observed
                if item[0] not in {"model/model_router.py", "gateway/claude_gateway.py"}
            ],
            sorted(_EXPECTED_OFFLINE_CONSTRUCTORS),
        )

    def test_repository_scanner_detects_import_aliases_and_dynamic_construction(self):
        source = """
import anthropic as provider
from anthropic import AsyncAnthropic as AsyncClient
import importlib as loader

def probe(dynamic_name):
    provider.Anthropic()
    AsyncClient()
    getattr(provider, "Anthropic")()
    getattr(loader.import_module("anthropic"), dynamic_name)()
    __import__("anthropic")
    eval("anthropic.Anthropic()")
"""
        tree = ast.parse(source)
        visitor = _AnthropicConstructorVisitor("synthetic.py", tree)
        visitor.visit(tree)
        modes = [item[3] for item in visitor.findings]
        constructors = [item[2] for item in visitor.findings]
        self.assertEqual(modes.count("direct"), 2)
        self.assertIn("Anthropic", constructors)
        self.assertIn("AsyncAnthropic", constructors)
        self.assertIn("dynamic_getattr", modes)
        self.assertIn("dynamic_import", modes)
        self.assertIn("dynamic_eval", modes)

    def test_local_transport_normalizes_sdk_usage_into_plain_data(self):
        usage = SimpleNamespace(
            input_tokens=10,
            output_tokens=4,
            cache_read_input_tokens=3,
            cache_creation_input_tokens=5,
            cache_creation=SimpleNamespace(
                ephemeral_5m_input_tokens=2,
                ephemeral_1h_input_tokens=3,
            ),
        )
        self.assertEqual(model_router._normalized_claude_usage(usage), {
            "input_tokens": 10,
            "output_tokens": 4,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 5,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 2,
                "ephemeral_1h_input_tokens": 3,
            },
        })


if __name__ == "__main__":
    unittest.main()
