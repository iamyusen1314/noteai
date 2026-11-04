"""Pinned native malformed-input projection; no suppliers or production DB."""
import contextlib
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import httpx
from tests import test_cover_agent_thinking as thinking_fixture
from tests import test_cover_agent_runtime as fixture
from tests import test_cover_agent_provider as ledger_fixture
import cover_agent_thinking as thinking

BAD = '{"path":"bad.md","text":}'


def original(number=1, *, raw=BAD):
    return thinking_fixture.response(calls=[
        thinking_fixture.call("good_" + str(number), '{"path":"good.md","text":"safe"}'),
        thinking_fixture.call("bad_" + str(number), raw)],
        cipher="SYNTHETIC_CIPHER_" + str(number), reasoning_content="SYNTHETIC_REASONING")


def projected(response):
    message = deepcopy(response["choices"][0]["message"])
    message.pop("encrypted_content", None)
    message["tool_calls"][1]["function"]["arguments"] = "{}"
    bad = response["choices"][0]["message"]["tool_calls"][1]
    return {"messages": [message, {"role": "tool", "tool_call_id": message["tool_calls"][0]["id"], "content": "safe"},
        {"role": "tool", "tool_call_id": bad["id"], "content": json.dumps(
            thinking._native_json_error(bad["function"]["arguments"]), ensure_ascii=True)}]}


class NativeThinkingRepairTests(unittest.TestCase):
    def test_known_raw_turn_requires_native_nonexecution_proof_and_restores_complete_original(self):
        state = thinking.ThinkingState("local")
        response = original()
        clean = state.remember(response)
        self.assertNotIn("encrypted_content", clean["choices"][0]["message"])
        incoming = projected(response)
        restored = state.restore(incoming)
        self.assertEqual(restored["messages"][0], response["choices"][0]["message"])
        self.assertEqual(restored["messages"][1:], incoming["messages"][1:])
        self.assertNotIn("SYNTHETIC_CIPHER", json.dumps(incoming))
        self.assertNotEqual(incoming["messages"][0], restored["messages"][0])
        with self.assertRaises(thinking.ThinkingError):
            state.restore({"messages": [clean["choices"][0]["message"]]})
        with self.assertRaises(thinking.ThinkingError):
            thinking.ThinkingState("other").restore(incoming)

    def test_changed_groups_arguments_cipher_or_native_failure_are_rejected(self):
        response = original()
        state = thinking.ThinkingState("local")
        state.remember(response)
        base = projected(response)
        cases = []
        def change(callback):
            value = deepcopy(base); callback(value); cases.append(value)
        change(lambda v: v["messages"][0]["tool_calls"].reverse())
        change(lambda v: v["messages"][0]["tool_calls"].pop())
        change(lambda v: v["messages"][0]["tool_calls"][0]["function"].update(arguments='{}'))
        change(lambda v: v["messages"][0]["tool_calls"][1]["function"].update(arguments='{ }'))
        change(lambda v: v["messages"][0]["tool_calls"][1]["function"].update(name='cover_read'))
        change(lambda v: v["messages"][0].update(content='changed'))
        change(lambda v: v["messages"][0].update(encrypted_content='other'))
        change(lambda v: v["messages"].pop())
        change(lambda v: v["messages"].append(deepcopy(v["messages"][-1])))
        change(lambda v: v["messages"].insert(1, {"role": "user", "content": "nonadjacent"}))
        change(lambda v: v["messages"][-1].update(tool_call_id='unknown'))
        change(lambda v: v["messages"][-1].update(content='{"error":{"type":"tool.input-json","message":"json"},"content":[]}'))
        change(lambda v: v["messages"][-1].update(content=v["messages"][-1]["content"][:-1] + ',"extra":true}'))
        change(lambda v: v["messages"][-1].update(content=v["messages"][-1]["content"].replace('tool.input-json','tool.input-schema')))
        change(lambda v: v["messages"][-1].update(content=v["messages"][-1]["content"].replace('"content": []','"content": ["executed"]')))
        change(lambda v: v["messages"].extend(deepcopy(v["messages"])))
        for value in cases:
            with self.subTest(case=cases.index(value)), self.assertRaises(thinking.ThinkingError):
                state.restore(value)

    def test_two_turn_limit_and_memory_failure_are_atomic_and_empty_raw_stays_rejected(self):
        state = thinking.ThinkingState("local")
        for number in (1, 2):
            response = original(number)
            state.remember(response)
            before = state.retained_bytes
            state.remember(deepcopy(response))
            self.assertEqual(state.retained_bytes, before)
            self.assertEqual(state.restore(projected(response))["messages"][0], response["choices"][0]["message"])
        before = (state.entry_count, state.retained_bytes, deepcopy(state._messages), deepcopy(state._ids), deepcopy(state._malformed))
        with self.assertRaises(thinking.ThinkingError) as caught:
            state.remember(original(3))
        self.assertEqual(caught.exception.reason, "JSON_SYNTAX_REPAIR_LIMIT")
        self.assertEqual((state.entry_count, state.retained_bytes, state._messages, state._ids, state._malformed), before)
        normal = thinking.ThinkingState("empty")
        with self.assertRaises(thinking.ThinkingError) as caught:
            normal.remember(original(raw=''))
        self.assertEqual(caught.exception.reason, "JSON_SYNTAX")
        self.assertEqual(normal.entry_count, 0)
        measured = thinking.ThinkingState("bounded")
        measured.remember(original())
        no_projection = thinking._size((measured._job_id, measured._messages, measured._ids, {}))
        self.assertGreater(measured.retained_bytes, no_projection)
        bounded = thinking.ThinkingState("bounded", max_bytes=no_projection)
        before = (bounded.entry_count, bounded.retained_bytes, deepcopy(bounded._malformed))
        with self.assertRaises(thinking.ThinkingError) as caught:
            bounded.remember(original())
        self.assertEqual(caught.exception.code, "COVER_AGENT_THINKING_MEMORY_LIMIT")
        self.assertEqual((bounded.entry_count, bounded.retained_bytes, bounded._malformed), before)


@unittest.skipUnless(os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") and shutil.which("node"),
    "Explicit pinned SDK and Node required")
class NativeThinkingRepairSDKTests(unittest.TestCase):
    def test_native_utf16_excerpt_matches_pinned_SDK_including_split_emoji(self):
        sdk = Path(os.environ["NOTEAI_COVER_HOST_NODE_MODULES"])
        source = sdk / "@opencode/core/dist/chunks/repository-cache-t1r0yajc.js"
        cases = [BAD, ' ', '{"text":"' + 'a' * 2038 + '😀' + 'end', '中' * 2048 + '😀']
        script = r'''
const fs=require('node:fs'),vm=require('node:vm');const source=fs.readFileSync(process.argv[1],'utf8');
const ctx=vm.createContext({});vm.runInContext(source.slice(source.indexOf('var INPUT_EXCERPT_LIMIT ='),source.indexOf('var stringify ='))+'\n'+source.slice(source.indexOf('function inputExcerpt('),source.indexOf('\nexport {')),ctx);
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(raw=>ctx.inputFailure(ctx.inputExcerpt(raw),'malformed'))));
'''
        result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "-e", script, str(source),
            json.dumps(cases, ensure_ascii=True)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [thinking._native_json_error(raw)["error"] for raw in cases])

    def run_case(self, *, tamper=False):
        with tempfile.TemporaryDirectory() as root, contextlib.ExitStack() as stack:
            ledger = ledger_fixture.CoverAgentProviderTests(); ledger.setUp(); stack.callback(ledger.tearDown)
            stack.enter_context(ledger.editable_claim())
            directory = Path(root); (directory / "assets").mkdir()
            payload = fixture.synthetic_png((320, 240), '#316856')
            (directory / "assets/source.png").write_bytes(payload)
            source = {"media_ref": "synthetic", "path": "assets/source.png", "sha256": hashlib.sha256(payload).hexdigest(), "payload": payload}
            responses, requests = [], []
            def transport(request):
                body = json.loads(request.content); requests.append(body)
                self.assertEqual([m for m in body["messages"] if m.get("role") == "assistant"], responses)
                value = ledger.response()
                if len(requests) == 1:
                    message = original()["choices"][0]["message"]
                    if not tamper:
                        message['tool_calls'].insert(1, {'id': 'native_view', 'type': 'function',
                            'function': {'name': 'cover_view', 'arguments': '{"path":"assets/source.png"}'}})
                elif len(requests) == 2:
                    message = thinking_fixture.response(calls=[thinking_fixture.call('fixed',
                        '{"path":"repaired.md","text":"Corrected safe fixture"}')], cipher='SYNTHETIC_FIXED')["choices"][0]["message"]
                else:
                    return httpx.Response(200, json=value)
                responses.append(deepcopy(message)); value["choices"][0].update(message=message, finish_reason='tool_calls')
                return httpx.Response(200, json=value)
            def before(stage, call_id, _estimate):
                ledger_fixture.cover_jobs.before_text_call(ledger.claim, stage, call_id)
            bridge = fixture.runtime.Bridge(job_id=ledger.claim["request_id"], directory=directory,
                sources=[source], hooks=fixture.cover_runtime.RuntimeHooks(before, lambda *_: None),
                model_transport=httpx.MockTransport(transport))
            actual = bridge.preflight
            def preflight(body):
                self.assertNotIn('SYNTHETIC_CIPHER', json.dumps(body))
                if any(message.get('role') == 'tool' for message in body['messages']):
                    print('NATIVE_INPUT_PROTOCOL_SHAPE=' + json.dumps({'roles': [message['role'] for message in body['messages']],
                        'tool_ids': [message.get('tool_call_id') for message in body['messages'] if message['role'] == 'tool']}))
                if tamper:
                    body = deepcopy(body)
                    for message in body["messages"]:
                        if message.get("role") == 'tool' and message.get('tool_call_id') == 'bad_1':
                            message['content'] = '{"error":{"type":"tool.input-json","message":"wrong"},"content":[]}'
                return actual(body)
            bridge.preflight = preflight
            prompt = fixture.runtime._prompt({"title": "本地思考链合同", "body": "合成测试", "title_variants": []},
                [{k: v for k, v in source.items() if k != 'payload'}])
            code = 'COVER_AGENT_THINKING_CONTEXT_MISMATCH' if tamper else 'COVER_AGENT_DESIGN_INCOMPLETE'
            with self.assertRaisesRegex(fixture.cover_runtime.CoverRuntimeError, code):
                bridge.run(prompt, deadline=time.time() + 600)
            self.assertEqual(len(requests), 1 if tamper else 3)
            calls = ledger_fixture.db.fetchall('SELECT state,http_status FROM public_trial_calls WHERE usage_record_id=?',
                (ledger.claim['charge']['usage_id'],))
            self.assertEqual(len(calls), len(requests))
            self.assertTrue(all(row['state'] == 'responded' and row['http_status'] == 200 for row in calls))
            self.assertFalse((directory / 'bad.md').exists())
            self.assertEqual((directory / 'good.md').read_text(), 'safe')
            self.assertEqual((directory / 'repaired.md').exists(), not tamper)
            state = json.loads((directory / 'host-state/host-checkpoint.json').read_text())
            self.assertEqual(state['local_tool_activity']['attempts']['cover_write'], 1 if tamper else 2)
            print('NATIVE_MALFORMED_SDK_PROOF=' + json.dumps({'tampered_native_error': tamper,
                'normal_local_known_HTTP200': len(calls), 'bad_tool_executions': 0,
                'new_corrected_tool_executed': not tamper, 'supplier_calls': 0, 'production_DB_writes': 0}))

    def test_actual_SDK_native_error_then_corrected_call_restores_whole_original_turn(self):
        self.run_case()

    def test_actual_SDK_tampered_native_error_stops_before_second_intent(self):
        self.run_case(tamper=True)


if __name__ == '__main__':
    unittest.main()
