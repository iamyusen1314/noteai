"""Application input-bound fit; synthetic known history and isolated accounting."""
import contextlib
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

import httpx
from tests import test_cover_agent_provider as financial
from tests import test_cover_agent_runtime as fixture

provider, runtime, db = fixture.provider, fixture.runtime, financial.db
OLD_BOUND = 131072
R12_BOUND = 162809


def sized_text(prefix, size):
    extra = size - len(json.dumps(prefix, ensure_ascii=False, separators=(",", ":")).encode())
    if extra < 0:
        raise AssertionError("Fixture prefix does not fit")
    return prefix + "X" * extra


def observed_shape(bridge, ledger):
    """R12's retained numeric shape, never reconstructed merchant content.

    Keep the complete real vendor Skill and synthetic cipher/reasoning. The
    six synthetic images use explicit vision ceilings matching the observed
    28704 bound. No original R12 prompt, ciphertext or images were retained.
    """
    skill = (runtime.ROOT / "cover_editable/vendor/editable-design/SKILL.md").read_text()
    picture = fixture.synthetic_png((512, 384), "#315d4b")
    image = runtime.ark_media.image_part(picture)
    image["image_url"]["image_pixel_limit"] = {"min_pixels": 1764, "max_pixels": 7987392}
    payload = {"model": provider.MODEL, "max_completion_tokens": provider.MAX_OUTPUT_TOKENS,
        "messages": [{"role": "system", "content": sized_text(skill, 48479)},
            {"role": "user", "content": [{"type": "text", "text": "Synthetic measurement, not R12 content."},
                *[deepcopy(image) for _ in range(6)]]}],
        "tools": [{"type": "function", "function": {"name": name,
            "description": "Synthetic actual-shape tool schema", "parameters": {"type": "object"}}}
            for name in sorted(runtime._LOCAL_TOOL_NAMES)], "stream": False}
    # Ten complete known assistant/tool pairs, with original identities kept in
    # ThinkingState. Only the first needs the large synthetic private fields.
    original = []
    for index in range(10):
        message = {"role": "assistant", "content": "" if index else "A" * 1224,
            "tool_calls": [{"id": "known_" + str(index), "type": "function", "function": {
                "name": "cover_write", "arguments": json.dumps({"path": "draft-" + str(index) + ".md", "text": ""}, separators=(",", ":"))}}]}
        if index == 0:
            message.update(reasoning_content="R" * 15610, encrypted_content="C" * 34008)
        original.append(message)
    argument_size = sum(len(json.dumps(m["tool_calls"][0]["function"]["arguments"]).encode()) for m in original)
    args = json.loads(original[0]["tool_calls"][0]["function"]["arguments"])
    args["text"] = "W" * (8836 - argument_size)
    original[0]["tool_calls"][0]["function"]["arguments"] = json.dumps(args, separators=(",", ":"))
    for index, message in enumerate(original):
        response = ledger.response(); response["choices"][0]["message"] = message
        response["choices"][0]["finish_reason"] = "tool_calls"
        safe = bridge.thinking.remember(response)["choices"][0]["message"]
        payload["messages"].extend([safe, {"role": "tool", "tool_call_id": "known_" + str(index),
            "content": "" if index else "T" * 6595}])
    payload["messages"].append({"role": "user", "content": "Continue the exact saved design."})
    restored = bridge._restore_thinking(payload)
    _, measurement = provider._validate_and_measure_payload(restored)
    extra = R12_BOUND - measurement["total_bound"]
    if extra < 0:
        raise AssertionError("Synthetic observed shape exceeds target before padding")
    payload["messages"][-1]["content"] += "U" * extra
    restored = bridge._restore_thinking(payload)
    _, measurement = provider._validate_and_measure_payload(restored)
    assert measurement["total_bound"] == R12_BOUND and measurement["text_bytes"] == 129369
    assert (measurement["message_count"], measurement["tool_count"], measurement["image_count"],
        measurement["image_tokens"], measurement["framing_tokens"]) == (23, 6, 6, 28704, 4736)
    assert measurement["text_breakdown"]["encrypted_content_bytes"] == 34010
    assert measurement["text_breakdown"]["reasoning_content_bytes"] == 15612
    assert skill in restored["messages"][0]["content"]
    return payload, restored, measurement


class InputWindowTests(unittest.TestCase):
    def setUp(self):
        self.ledger = financial.CoverAgentProviderTests(); self.ledger.setUp()
        self.addCleanup(self.ledger.tearDown)

    def bridge(self):
        def before(stage, call, _estimate):
            financial.cover_jobs.before_text_call(self.ledger.claim, stage, call)
        return runtime.Bridge(job_id=self.ledger.claim["request_id"], directory=Path(self.ledger.fixture.temp.name),
            sources=[], hooks=fixture.cover_runtime.RuntimeHooks(before, lambda *_: None),
            model_transport=self.ledger.transport())

    def test_R12_observed_shape_old_overflow_new_primary_preserves_full_known_history(self):
        with self.ledger.editable_claim():
            bridge = self.bridge(); payload, restored, measurement = observed_shape(bridge, self.ledger)
            with mock.patch.object(provider, "MAX_INPUT_TOKENS", OLD_BOUND):
                decision = bridge.preflight(payload)
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["measurement"]["total_bound"], R12_BOUND)
            self.assertFalse(self.ledger.requests)
            self.assertEqual(bridge.ordinal, 0)
            self.assertEqual(bridge.preflight(payload), {"allowed": True})
            bridge.request_deadline = time.time() + 600
            _, call = bridge.model(payload)
            body = json.loads(self.ledger.requests[-1].content)
            expected, bound = provider.prepare_payload(restored)
            self.assertEqual((body, bound), (expected, R12_BOUND))
            rows = db.fetchall("SELECT state,http_status,reserve_milli_cny FROM public_trial_calls WHERE usage_record_id=?",
                (self.ledger.claim["charge"]["usage_id"],))
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["state"], rows[0]["http_status"], rows[0]["reserve_milli_cny"]), ("responded", 200, 3146))
            self.assertEqual(self.ledger.call_row(call)["model_usage_record_id"], self.ledger.model_row(call)["id"])
            print("INPUT_BOUND_OBSERVED_SHAPE_PROOF=" + json.dumps({"old_bound": OLD_BOUND,
                "new_bound": provider.MAX_INPUT_TOKENS, "measurement": measurement,
                "same_restored_body_dispatched": True, "known_local_primary_calls": 1,
                "compaction_intents": 0, "supplier_calls": 0, "production_DB_writes": 0}))

    def test_exact_new_boundary_and_one_over_remain_authoritative_before_intent(self):
        for output in (provider.MAX_OUTPUT_TOKENS, provider.QC_OUTPUT_TOKENS):
            body = {"messages": [{"role": "user", "content": ""}], "max_completion_tokens": output}
            overhead = provider._validate_and_measure_payload(body)[1]["total_bound"]
            body["messages"][0]["content"] = "X" * (provider.MAX_INPUT_TOKENS - overhead)
            prepared, bound = provider.prepare_payload(body)
            self.assertEqual(bound, provider.MAX_INPUT_TOKENS)
            self.assertEqual(prepared["max_completion_tokens"], output)
            body["messages"][0]["content"] += "X"
            self.assertFalse(provider.admit_payload(body)["allowed"])
            with mock.patch.object(bridge := self.bridge(), "_check_model_deadline"), \
                    self.assertRaisesRegex(financial.public_product.TrialProviderStopped, "COVER_AGENT_INPUT_LIMIT_EXCEEDED"):
                bridge.model(body)
            self.assertEqual(bridge.ordinal, 0)
        self.assertFalse(self.ledger.requests)
        self.assertFalse(db.fetchall("SELECT id FROM public_trial_calls WHERE usage_record_id=?", (self.ledger.claim["charge"]["usage_id"],)))

    def test_reservation_matrix_and_configured_SDK_context_close_without_output_change(self):
        self.assertEqual((provider.MAX_INPUT_TOKENS, provider.MAX_OUTPUT_TOKENS, provider.SDK_CONTEXT_TOKENS),
            (196608, 65536, 262144))
        self.assertEqual(provider.MAX_INPUT_TOKENS + provider.MAX_OUTPUT_TOKENS, provider.SDK_CONTEXT_TOKENS)
        for output, amount, reserve in ((65536, "3.145728", 3146), (32768, "2.162688", 2163), (8192, "1.425408", 1426)):
            quote = provider.estimate(output)
            self.assertEqual(quote["estimated_cost"], amount)
            self.assertEqual(int((Decimal(amount) * 1000).to_integral_value(rounding=ROUND_CEILING)), reserve)
            self.assertEqual(provider.pricing(196608), provider.pricing(131072))

    def test_original_atomic_scope_refuses_new_max_reserve_without_physical_intent(self):
        # The optional production guard applies to the formal owner-metered
        # route, not the independent historical acceptance budget.
        from tests import test_cover_verification_budget as verification
        scope = verification.CoverVerificationBudgetTests(); scope.setUp()
        try:
            scope.configure(cap="3145")
            body = deepcopy(self.ledger.body); body["max_tokens"] = provider.MAX_OUTPUT_TOKENS
            call = "bound-reserve-test"
            financial.cover_jobs.before_text_call(scope.claim, "design", call)
            with self.assertRaisesRegex(financial.public_product.TrialProviderStopped, "COVER_VERIFY_BUDGET_EXHAUSTED"):
                provider.complete(body, call_id=call, transport=self.ledger.transport())
            self.assertFalse(self.ledger.requests)
            self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call,)))
            self.assertFalse(db.fetchall("SELECT id FROM model_usage_records WHERE usage_record_id=?", (scope.claim["charge"]["usage_id"],)))
        finally:
            scope.tearDown()


@unittest.skipUnless(os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") and shutil.which("node"),
    "Explicit pinned SDK and Node required")
class InputWindowSDKTests(unittest.TestCase):
    def test_real_sdk_same_known_history_new_bound_continues_primary_without_forced_compaction(self):
        proofs=[]
        for cap in (OLD_BOUND, provider.MAX_INPUT_TOKENS):
            with self.subTest(bound=cap), tempfile.TemporaryDirectory() as root, contextlib.ExitStack() as stack:
                ledger=financial.CoverAgentProviderTests();ledger.setUp();stack.callback(ledger.tearDown)
                stack.enter_context(ledger.editable_claim());stack.enter_context(mock.patch.object(provider,"MAX_INPUT_TOKENS",cap))
                directory=Path(root);(directory/'assets').mkdir();image=fixture.synthetic_png((320,240),'#315d4b')
                (directory/'assets/source.png').write_bytes(image)
                source={'media_ref':'synthetic-input-window','path':'assets/source.png','sha256':fixture.artifacts.digest(image),'payload':image}
                requests=[];primary_bounds=[]
                def transport(request):
                    body=json.loads(request.content);requests.append(body);response=ledger.response()
                    if len(requests)==1:
                        response['choices'][0].update(finish_reason='tool_calls',message={'role':'assistant','content':None,
                            'reasoning_content':'R'*15610,'encrypted_content':'C'*62000,
                            'tool_calls':[{'id':'large_known_write','type':'function','function':{'name':'cover_write',
                                'arguments':json.dumps({'path':'design-plan.md','text':'W'*20000})}}]})
                    elif cap!=OLD_BOUND and len(requests)==2:
                        assistant=next(m for m in body['messages']if m.get('role')=='assistant'and m.get('tool_calls'))
                        self.assertEqual(assistant['encrypted_content'],'C'*62000)
                        self.assertEqual(assistant['reasoning_content'],'R'*15610)
                        self.assertEqual(json.loads(assistant['tool_calls'][0]['function']['arguments'])['text'],'W'*20000)
                    elif cap==OLD_BOUND and len(requests)==2:
                        response['choices'][0]['message']={'role':'assistant','content':'## Objective\nContinue the complete saved cover plan.\n## Work State\nThe exact file is design-plan.md; inspect it if needed.'}
                    return httpx.Response(200,json=response)
                def before(stage,call,_estimate):financial.cover_jobs.before_text_call(ledger.claim,stage,call)
                bridge=runtime.Bridge(job_id=ledger.claim['request_id'],directory=directory,sources=[source],
                    hooks=fixture.cover_runtime.RuntimeHooks(before,lambda *_:None),model_transport=httpx.MockTransport(transport))
                actual=bridge.preflight
                def preflight(body):
                    measurement=provider._validate_and_measure_payload(bridge._restore_thinking(body))[1]
                    primary_bounds.append(measurement['total_bound'])
                    return actual(body)
                bridge.preflight=preflight
                prompt=runtime._prompt({'title':'输入窗口技术验证','body':'合成技术夹具，不是商家验收。','title_variants':[]},
                    [{k:v for k,v in source.items()if k!='payload'}])
                with self.assertRaisesRegex(fixture.cover_runtime.CoverRuntimeError,'COVER_AGENT_DESIGN_INCOMPLETE'):
                    bridge.run(prompt,deadline=time.time()+600)
                state=json.loads((directory/'host-state/host-checkpoint.json').read_text())
                rows=db.fetchall('SELECT state,http_status FROM public_trial_calls WHERE usage_record_id=?',(ledger.claim['charge']['usage_id'],))
                self.assertTrue(all(r['state']=='responded'and r['http_status']==200 for r in rows))
                self.assertEqual((directory/'design-plan.md').read_text(),'W'*20000)
                self.assertGreater(primary_bounds[1],OLD_BOUND)
                self.assertLessEqual(primary_bounds[1],196608)
                self.assertEqual(state.get('compaction_requests',0),1 if cap==OLD_BOUND else 0)
                self.assertEqual(state.get('local_input_rejections',0),1 if cap==OLD_BOUND else 0)
                self.assertEqual(len(requests),3 if cap==OLD_BOUND else 2)
                proofs.append({'bound':cap,'actual_known_HTTP200':len(rows),'preflight_bounds':primary_bounds,
                    'local_input_rejections':state.get('local_input_rejections',0),'compaction_requests':state.get('compaction_requests',0),
                    'cipher_exact_normal_restore':True,'actual_saved_file_bytes':20000,'supplier_calls':0})
        print('INPUT_WINDOW_NATIVE_SDK_PROOF='+json.dumps(proofs))
