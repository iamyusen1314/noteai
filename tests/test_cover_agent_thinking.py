"""Pure synthetic opaque-state tests: no business imports, files or network."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
from cover_agent_thinking import ThinkingError, ThinkingState, validated_thinking_diagnostics


def response(content=None, calls=None, cipher="fake-opaque", **extra):
    message = {"role": "assistant", "content": content, **extra}
    if calls is not None:
        message["tool_calls"] = calls
    if cipher is not None:
        message["encrypted_content"] = cipher
    return {"model": "synthetic", "id": "not-retained", "usage": {"total_tokens": 42},
            "choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}]}


def call(identifier="call-1", arguments='{"text":"中文", "n":1.0, "z":-0.0}'):
    return {"id": identifier, "type": "function",
            "function": {"name": "cover_write", "arguments": arguments}}


class ThinkingStateTests(unittest.TestCase):
    def setUp(self):
        self.no_network = mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)
        self.state = ThinkingState("job-1")

    def assert_code(self, code, action):
        with self.assertRaises(ThinkingError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def test_roundtrip_normalizes_only_json_values_and_preserves_original_wire(self):
        original = response(calls=[call()], reasoning_content="原思考摘要", unwanted="not-retained")
        clean = self.state.remember(original)
        self.assertNotIn("encrypted_content", clean["choices"][0]["message"])
        self.assertEqual(original["choices"][0]["message"]["encrypted_content"], "fake-opaque")
        self.assertEqual(clean["usage"], original["usage"])
        incoming = {"model": "synthetic", "max_completion_tokens": 123,
                    "messages": [{"role": "user", "content": "原问题"},
                        {"role": "assistant", "content": "", "tool_calls": [call(arguments='{"z":0,"n":1,"text":"中文"}')]},
                        {"role": "tool", "tool_call_id": "call-1", "content": "saved"}]}
        expected = deepcopy(original["choices"][0]["message"])
        expected.pop("unwanted")
        for _ in range(2):
            restored = self.state.restore(incoming)
            self.assertEqual(restored["messages"][1], expected)
            self.assertEqual(restored["messages"][1]["tool_calls"][0]["function"]["arguments"],
                             original["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
            self.assertEqual(restored["max_completion_tokens"], 123)
            restored["messages"][1]["content"] = "mutated-copy"
        self.assertEqual(incoming["messages"][1]["content"], "")
        clean["choices"][0]["message"]["content"] = "mutated-clean"
        self.assertEqual(self.state.entry_count, 1)

    def test_no_cipher_turn_is_registered_and_full_text_is_exact(self):
        original = response("完整中文文本\n第二行", cipher=None)
        self.assertEqual(self.state.remember(original), original)
        payload = {"messages": [original["choices"][0]["message"]]}
        self.assertEqual(self.state.restore(payload), payload)
        bad = deepcopy(payload)
        bad["messages"][0]["content"] += " "
        self.assert_code("COVER_AGENT_THINKING_CONTEXT_UNKNOWN", lambda: self.state.restore(bad))
        bad = deepcopy(payload)
        bad["messages"][0]["encrypted_content"] = "unexpected-secret"
        self.assert_code("COVER_AGENT_THINKING_CONTEXT_MISMATCH", lambda: self.state.restore(bad))

    def test_optional_null_fields_and_non_tool_empty_text_are_not_confused(self):
        original = response("done", cipher=None, tool_calls=None, reasoning_content=None)
        original["choices"][0]["message"]["encrypted_content"] = None
        clean = self.state.remember(original)
        self.assertNotIn("encrypted_content", clean["choices"][0]["message"])
        restored = self.state.restore({"messages": [{"role": "assistant", "content": "done"}]})
        self.assertEqual(restored["messages"][0], {"role": "assistant", "content": "done", "tool_calls": None})
        self.state.remember(response(None, cipher="null-only"))
        self.state.remember(response("", cipher="empty-only"))
        self.assertEqual(self.state.restore({"messages": [{"role": "assistant", "content": None}]})["messages"][0]["encrypted_content"], "null-only")
        self.assertEqual(self.state.restore({"messages": [{"role": "assistant", "content": ""}]})["messages"][0]["encrypted_content"], "empty-only")

    def test_all_ordered_tool_calls_must_match_without_partial_or_reordered_groups(self):
        original = response(calls=[call(), call("call-2", '{"path":"poster.json"}')])
        clean = self.state.remember(original)
        message = clean["choices"][0]["message"]
        self.assertEqual(self.state.restore({"messages": [message]})["messages"][0], original["choices"][0]["message"])
        for calls in ([call()], list(reversed(message["tool_calls"])),
                      [call(arguments='{"text":"changed"}'), call("call-2", '{"path":"poster.json"}')]):
            with self.subTest(calls=calls):
                self.assert_code("COVER_AGENT_THINKING_CONTEXT_MISMATCH",
                    lambda: self.state.restore({"messages": [{"role": "assistant", "content": None, "tool_calls": calls}]}))
        self.assert_code("COVER_AGENT_THINKING_CONTEXT_MISMATCH",
                         lambda: self.state.restore({"messages": [message, message]}))

    def test_reused_id_or_text_with_different_cipher_cannot_replace_history(self):
        original = response(calls=[call()])
        self.state.remember(original)
        for changed in (response(calls=[call()], cipher="other-fake"),
                        response(calls=[call(arguments='{"text":"other"}')])):
            self.assert_code("COVER_AGENT_THINKING_CONTEXT_MISMATCH", lambda: self.state.remember(changed))
        before = self.state.retained_bytes
        self.state.remember(deepcopy(original))
        self.assertEqual(self.state.retained_bytes, before)
        self.state.remember(response("done", cipher="text-fake"))
        self.assert_code("COVER_AGENT_THINKING_CONTEXT_MISMATCH",
                         lambda: self.state.remember(response("done", cipher="different-text-fake")))

    def test_existing_cipher_mismatch_and_cross_job_fail_closed(self):
        original = response(calls=[call()])
        clean = self.state.remember(original)
        message = clean["choices"][0]["message"]
        message["encrypted_content"] = "private-sentinel-must-not-appear"
        self.assert_code("COVER_AGENT_THINKING_CONTEXT_MISMATCH",
                         lambda: self.state.restore({"messages": [message]}))
        clean["choices"][0]["message"].pop("encrypted_content")
        self.assert_code("COVER_AGENT_THINKING_CONTEXT_UNKNOWN",
                         lambda: ThinkingState("other-job").restore({"messages": [clean["choices"][0]["message"]]}))

    def test_bad_json_values_and_types_are_rejected_without_content_in_error(self):
        bad = ['{"x":1,"x":2}', '{"x":{"y":1,"y":2}}', '{"x":NaN}',
               '{"x":Infinity}', '{"x":1e309}', '{"x":9007199254740992}',
               '{"x":9007199254740992.0}', '[]', 'null', 'true', '"private-sentinel"']
        for arguments in bad:
            with self.subTest(arguments=arguments):
                self.assert_code("COVER_AGENT_THINKING_CONTEXT_INVALID",
                                 lambda: self.state.remember(response(calls=[call(arguments=arguments)])))
        self.assertEqual(self.state.entry_count, 0)
        self.state.remember(response(calls=[call(arguments='{"x":true}')]))
        self.assert_code("COVER_AGENT_THINKING_CONTEXT_MISMATCH",
                         lambda: self.state.restore({"messages": [response(calls=[call(arguments='{"x":1}')])["choices"][0]["message"]]}))

    def test_fixed_reasons_distinguish_rejections_without_changing_original_codes(self):
        cases = [("JSON_SYNTAX", '{"x":}'), ("DUPLICATE_KEY", '{"x":1,"x":2}'),
            ("NON_OBJECT_ARGUMENTS", "[]"), ("NON_FINITE_NUMBER", '{"x":NaN}'),
            ("NON_FINITE_NUMBER", '{"x":1e309}'), ("UNSAFE_INTEGER", '{"x":9007199254740992}'),
            ("ARGUMENTS_TYPE", 42)]
        for reason, arguments in cases:
            with self.subTest(reason=reason), self.assertRaises(ThinkingError) as caught:
                self.state.remember(response(calls=[call(arguments=arguments)]))
            self.assertEqual(caught.exception.reason, reason)
            self.assertEqual(caught.exception.code, "COVER_AGENT_THINKING_CONTEXT_INVALID")
            self.assertEqual(str(caught.exception), caught.exception.code)
            self.assertEqual(self.state.entry_count, 0)
        for reason, invalid in [("MESSAGE_CONTENT_TYPE", response(content=[])),
                ("TOOL_CALLS_TYPE", response(calls={})),
                ("REASONING_TYPE", response(reasoning_content={})),
                ("OPAQUE_TYPE", response(cipher={}))]:
            with self.subTest(reason=reason), self.assertRaises(ThinkingError) as caught:
                self.state.remember(invalid)
            self.assertEqual(caught.exception.reason, reason)
            self.assertEqual(str(caught.exception), "COVER_AGENT_THINKING_CONTEXT_INVALID")
        checks = [
            ("INVALID_SHAPE", lambda: self.state.remember({"choices": []})),
            ("UNKNOWN_HISTORY", lambda: self.state.restore({"messages": [{"role": "assistant", "content": "unknown"}]})),
            ("MEMORY_LIMIT", lambda: ThinkingState("tiny", max_bytes=1)),
        ]
        self.state.remember(response(calls=[call()]))
        checks.append(("IDENTITY_MISMATCH", lambda: self.state.remember(
            response(calls=[call(arguments='{"text":"changed"}')]))))
        for reason, action in checks:
            with self.subTest(reason=reason), self.assertRaises(ThinkingError) as caught:
                action()
            self.assertEqual(caught.exception.reason, reason)
            self.assertEqual(str(caught.exception), caught.exception.code)
        error = ThinkingError("COVER_AGENT_THINKING_CONTEXT_INVALID", reason="PRIVATE_SENTINEL")
        self.assertEqual(error.reason, "INVALID_SHAPE")
        self.assertNotIn("PRIVATE_SENTINEL", str(error))

    def test_diagnostic_schema_is_fixed_bounded_and_detached(self):
        value = {"phase": "remember", "reason": "JSON_SYNTAX",
            "code": "COVER_AGENT_THINKING_CONTEXT_INVALID", "ordinal": 2,
            "entry_count": 1, "retained_bytes": self.state.retained_bytes}
        validated = validated_thinking_diagnostics(value)
        self.assertEqual(validated, value)
        validated["ordinal"] = 99
        self.assertEqual(value["ordinal"], 2)
        bad = [{**value, "raw": "PRIVATE_SENTINEL"}, {**value, "reason": "PRIVATE_SENTINEL"},
            {**value, "phase": "design"}, {**value, "code": []}, []]
        for key in ("ordinal", "entry_count", "retained_bytes"):
            bad.extend({**value, key: item} for item in (True, -1, None, 10 ** 100))
        for item in bad:
            with self.subTest(item=item):
                self.assertIsNone(validated_thinking_diagnostics(item))

    def test_memory_limit_is_atomic_and_no_export_or_storage_exists(self):
        small = ThinkingState("bounded", max_bytes=4096)
        original = response("known", cipher=None)
        small.remember(original)
        before = small.retained_bytes
        self.assert_code("COVER_AGENT_THINKING_MEMORY_LIMIT",
                         lambda: small.remember(response("new", cipher="fake" * 4096)))
        self.assertEqual(small.entry_count, 1)
        self.assertEqual(small.retained_bytes, before)
        self.assertEqual(small.restore({"messages": [original["choices"][0]["message"]]}),
                         {"messages": [original["choices"][0]["message"]]})
        self.assertFalse(hasattr(small, "save"))
        self.assertFalse(hasattr(small, "export"))

    def test_user_summary_and_fresh_messages_are_detached_without_old_cipher(self):
        self.state.remember(response(calls=[call()]))
        payload = {"messages": [{"role": "system", "content": "fixed skill"},
                    {"role": "user", "content": "serialized summary; not assistant replay"}],
                   "tools": [], "stream": False}
        result = self.state.restore(payload)
        self.assertEqual(result, payload)
        self.assertNotIn("fake-opaque", json.dumps(result))
        result["messages"][0]["content"] = "changed-copy"
        self.assertEqual(payload["messages"][0]["content"], "fixed skill")


if __name__ == "__main__":
    unittest.main()
