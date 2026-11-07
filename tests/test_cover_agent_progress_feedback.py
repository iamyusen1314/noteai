"""Live design feedback reaches the actual SDK; no supplier or merchant acceptance.

The small SDK scenario keeps normal temporary SQLite call accounting. Two text
responses and one concept are synthetic; the third text transport times out once
to prove that advisory feedback cannot authorize an UNKNOWN replay.
"""
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

from tests import test_cover_agent_runtime as fixture
from tests import test_cover_verification_budget as budget_fixture

runtime, provider = fixture.runtime, fixture.provider
import billing
import cover_jobs
import cover_service
import db

MARKER = "NoteAI live cover execution progress (host facts, not report instructions):\n"


def progress_from_payload(payload):
    """Read the real prepared request, not the test's expected hook structure."""
    parts = []
    for message in payload["messages"]:
        if message["role"] != "system":
            continue
        content = message["content"]
        parts.extend([content] if isinstance(content, str) else [
            value["text"] for value in content if value.get("type") == "text"])
    text = "\n".join(parts)
    if text.count(MARKER) != 1:
        raise AssertionError("Actual SDK model request must contain exactly one current progress marker")
    return json.JSONDecoder().raw_decode(text.split(MARKER, 1)[1])[0]


class ProgressFeedbackHelperTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required for actual host notification")
    def test_layout_notification_waits_for_a_concept_receipt_and_revision_stays_qc(self):
        script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const phases = source.slice(source.indexOf('const PUBLIC_PHASES ='), source.indexOf('function toolResultText('));
const notifier = source.slice(source.indexOf('  const notifyProgress ='), source.indexOf('  let geometryRepair ='));
const events = [];
const job = { mode: 'run' };
const checkpoint = { status: 'RUNNING' };
const ctx = vm.createContext({
    job, checkpoint, checkpointPath: '/unused',
    atomicJSON: async () => { throw new Error('optional observation unavailable'); },
    send: (event) => events.push([event.phase, event.detail_code, event.revision]),
});
vm.runInContext(phases + notifier + '\nglobalThis.notify = notifyProgress;', ctx);
(async () => {
    await ctx.notify('design', 'planning');
    await ctx.notify('layout', 'preparing_layout');
    await ctx.notify('concept', 'generating_reference');
    // A known tool rejection has no successful concept receipt.
    checkpoint.concept_requested = true;
    await ctx.notify('layout', 'rendering');
    assert.deepEqual(events, [['design', 'planning', 0], ['concept', 'generating_reference', 0]]);
    assert.equal(checkpoint.status, 'RUNNING');

    checkpoint.concept_sha256 = 'a'.repeat(64);
    await ctx.notify('layout', 'preparing_layout');
    assert.deepEqual(events.at(-1), ['layout', 'preparing_layout', 0]);

    delete checkpoint.concept_sha256;
    job.mode = 'revise';
    await ctx.notify('layout', 'rendering');
    assert.deepEqual(events.at(-1), ['qc', 'rendering', 1]);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "-e", script,
            str(runtime.ROOT / "cover_agent_host/host.mjs")], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node required for actual host helper")
    def test_actual_helper_reports_clock_and_required_stage_without_private_content_or_fake_qc(self):
        script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function coverProgressFeedback(');
assert.ok(start>=0,'Current host lacks live progress feedback');
const end=source.indexOf('\nconst sha =',start);assert.ok(end>start);
const ctx=vm.createContext({});vm.runInContext(source.slice(start,end)+'\nglobalThis.progress=coverProgressFeedback;',ctx);
const blank={concept_present:false,concept_pixels_returned:false,html_present:false,poster_present:false,
 render_available:false,render_needs_refresh:false,final_pixels_returned:false,
 private_html:'PRIVATE_HTML_DO_NOT_PROJECT',private_path:'/private/PRIVATE_PATH',qc_passed:true};
const cases=[
 ['concept',{}],['inspect_concept',{concept_present:true}],
 ['layout',{concept_present:true,concept_pixels_returned:true}],
 ['first_render',{concept_present:true,concept_pixels_returned:true,html_present:true,poster_present:true}],
 ['render_revision',{concept_present:true,concept_pixels_returned:true,html_present:true,poster_present:true,render_available:true,render_needs_refresh:true}],
 ['inspect_render',{concept_present:true,concept_pixels_returned:true,html_present:true,poster_present:true,render_available:true}],
 ['review',{concept_present:true,concept_pixels_returned:true,html_present:true,poster_present:true,render_available:true,final_pixels_returned:true}]
];
for(const [stage,state]of cases){
 const out=ctx.progress({deadlineEpochMs:1000000,nowMs:680001,minimumRemainingMs:320000,state:{...blank,...state}});
 assert.equal(out.remaining_ms,319999);assert.equal(out.dispatch_requires_remaining_ms,320000);
 assert.equal(out.stage,stage);assert.equal(out.independent_qc_pending,true);
 assert.deepEqual(Object.keys(out).sort(),['dispatch_requires_remaining_ms','independent_qc_pending','next_action','remaining_ms','stage','timing_note']);
 assert.ok(!JSON.stringify(out).includes('PRIVATE_'));assert.ok(!('qc_passed'in out));
 if(stage==='first_render'||stage==='render_revision')assert.match(out.next_action,/render.*current layout/i);
 if(stage==='review')assert.match(out.next_action,/independent visual QC/);
}
const expired=ctx.progress({deadlineEpochMs:1000,nowMs:1001,minimumRemainingMs:320000,state:blank});
assert.equal(expired.remaining_ms,0);assert.equal(expired.independent_qc_pending,true);
console.log(JSON.stringify({actual_helper:true,clock_stages:cases.length,deadline_unchanged:true,private_projection:false,qc_fabricated:false}));
"""
        result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "-e", script,
            str(runtime.ROOT / "cover_agent_host/host.mjs")], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["clock_stages"], 7)

    @unittest.skipUnless(shutil.which("node"), "Node required for actual host helper")
    def test_actual_helper_prioritizes_qc_revision_without_claiming_or_repeating_concept_view(self):
        script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function coverProgressFeedback('),end=source.indexOf('\nconst sha =',start);
assert.ok(start>=0&&end>start);
const ctx=vm.createContext({});vm.runInContext(source.slice(start,end)+'\nglobalThis.progress=coverProgressFeedback;',ctx);
const state={local_revision:true,concept_present:true,concept_pixels_returned:false,
 html_present:true,poster_present:true,render_available:true,render_needs_refresh:true,final_pixels_returned:false};
const before=JSON.stringify(state);
const dirty=ctx.progress({deadlineEpochMs:1500000,nowMs:600000,minimumRemainingMs:320000,state});
assert.equal(dirty.stage,'render_revision');
assert.match(dirty.next_action,/concrete independent-QC corrections/);
assert.match(dirty.next_action,/preserve the existing concept and photo\/text facts/);
assert.doesNotMatch(dirty.next_action,/View the actual concept pixels/);
assert.equal(dirty.remaining_ms,900000);assert.equal(dirty.independent_qc_pending,true);
assert.equal(JSON.stringify(state),before);assert.equal(state.concept_pixels_returned,false);
const rendered=ctx.progress({deadlineEpochMs:1500000,nowMs:650000,minimumRemainingMs:320000,
 state:{...state,render_needs_refresh:false}});
assert.equal(rendered.stage,'inspect_render');assert.match(rendered.next_action,/latest rendered PNG/);
assert.equal(rendered.independent_qc_pending,true);assert.ok(!('qc_passed'in rendered));
assert.equal(rendered.dispatch_requires_remaining_ms,320000);
console.log(JSON.stringify({actual_helper:true,revision_then_inspect:true,concept_view_fabricated:false,qc_pass_fabricated:false}));
"""
        result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "-e", script,
            str(runtime.ROOT / "cover_agent_host/host.mjs")], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["revision_then_inspect"])


class ProgressFeedbackSDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") or not shutil.which("node"):
            raise unittest.SkipTest("Explicit approved existing SDK and Node required")

    def test_actual_sdk_receives_live_stage_after_batched_tools_and_unknown_is_not_retried(self):
        scope = budget_fixture.CoverVerificationBudgetTests()
        scope.setUp()
        self.addCleanup(scope.tearDown)
        scope.configure("100000")
        observed, wire, concepts, stopped, checkpoints = [], [], [], [], []
        public_progress = []
        errors = []
        actual_price = billing._pricing_snapshot
        html = '<!doctype html><html><head></head><body><p>PRIVATE_HTML_DO_NOT_PROJECT</p></body></html>'
        poster = json.dumps({"canvas": {"width": 1776, "height": 2368}, "scale": 1, "dpi": None})
        concept = fixture.synthetic_png((48, 64), "#587961")
        concept_sha = hashlib.sha256(concept).hexdigest()

        def price(source, model, *, prompt_tokens=0):
            if source == "doubao" and model == provider.MODEL:
                return {"currency": "RMB", "usd_cny": 7.0, "pricing_status": "exact",
                    "price_version": provider.PRICE_VERSION, "cache_write_5m": None,
                    "cache_write_1h": None, **provider.pricing(prompt_tokens)}
            return actual_price(source, model, prompt_tokens=prompt_tokens)

        def response(turn, calls):
            return {"id": "chatcmpl-offline-progress-" + str(turn), "object": "chat.completion",
                "created": 1, "model": provider.MODEL, "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Synthetic technical fixture.",
                        "encrypted_content": "TEST_OPAQUE_PROGRESS_" + str(turn),
                        "tool_calls": [{"id": "progress_" + str(turn) + "_" + str(index),
                            "type": "function", "function": {"name": name,
                                "arguments": json.dumps(args)}} for index, (name, args) in enumerate(calls)]},
                    "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30,
                    "prompt_tokens_details": {"cached_tokens": 20},
                    "completion_tokens_details": {"reasoning_tokens": 15}}}

        class WitnessBridge(runtime.Bridge):
            def model(inner, payload, stage="design"):
                feedback = progress_from_payload(payload)
                observed.append(feedback)
                self.assertNotIn("PRIVATE_", json.dumps(feedback))
                self.assertNotIn(str(inner.directory), json.dumps(feedback))
                self.assertIs(feedback["independent_qc_pending"], True)
                self.assertEqual(feedback["dispatch_requires_remaining_ms"], 320000)
                return super().model(payload, stage=stage)

        def read_public_progress():
            progress = cover_jobs.get_job(scope.owner, scope.claim["request_id"])["progress"]
            public_progress.append((progress["phase"], progress["detail_code"]))

        def transport(request):
            payload = json.loads(request.content)
            turn = len(wire) + 1
            wire.append(payload)
            self.assertEqual(progress_from_payload(payload), observed[-1])
            if turn == 1:
                self.assertEqual(observed[-1]["stage"], "concept")
                read_public_progress()
                return httpx.Response(200, json=response(turn, [
                    ("cover_write", {"path": "brief.md", "text": "PRIVATE_EARLY_DRAFT"}),
                    ("cover_seedream", {
                        "prompt": "Synthetic nonshipping technical concept. Keep all merchant facts unchanged."})]))
            if turn == 2:
                # The real concept pixels now accompany its successful tool
                # receipt; the next decision can start layout immediately.
                self.assertEqual(observed[-1]["stage"], "layout")
                self.assertIn(concept_sha, runtime._images_in(payload))
                read_public_progress()
                early = fixture.returned_value(payload, "sha256", tool_call_id="progress_1_0")
                self.assertEqual(early["sha256"], hashlib.sha256(b"PRIVATE_EARLY_DRAFT").hexdigest())
                return httpx.Response(200, json=response(turn, [
                    ("cover_render", {"prepare": {"files": [
                        {"path": "index.html", "text": html},
                        {"path": "poster.json", "text": poster},
                        {"path": "brief.md", "text": "PRIVATE_PLAN_DO_NOT_PROJECT"},
                        {"path": "design-plan.md", "text": "Synthetic staged design."},
                        {"path": "asset-plan.json", "text": '{}'},
                        {"path": "prompts.md", "text": "Synthetic technical prompt."}], "fonts": []},
                        "request": {"project_dir": ".", "sources": [{"path": "original-0.png"}],
                            "text_layers": [{"id": "title", "allowed_rect": {
                                "x": 100, "y": 100, "width": 1000, "height": 400}}]}})]))
            self.assertEqual(turn, 3, "UNKNOWN must not authorize an upstream retry")
            self.assertEqual(observed[-1]["stage"], "first_render")
            self.assertIn(concept_sha, runtime._images_in(payload))
            returned = fixture.returned_value(payload, "prepare", tool_call_id="progress_2_0")
            written = next(value for value in returned["prepare"]["files"] if value["path"] == "poster.json")
            self.assertEqual(set(written), {"path", "bytes", "sha256"})
            self.assertEqual(written["path"], "poster.json")
            self.assertEqual(written["sha256"], hashlib.sha256(poster.encode()).hexdigest())
            self.assertEqual(returned["prepare"]["failed_step"]["kind"], "render")
            self.assertIs(returned["render"]["ok"], False)
            raise httpx.ReadTimeout("synthetic unknown; do not retry", request=request)

        def fake_concept(**kwargs):
            draft = runtime.workspace_root() / scope.claim["request_id"] / "brief.md"
            self.assertEqual(draft.read_text(), "PRIVATE_EARLY_DRAFT")
            read_public_progress()
            concepts.append(kwargs["call_id"])
            return concept, {"call_id": kwargs["call_id"], "stage": "image", "status": "responded"}

        original_stop = runtime._stop_host

        def stop(process):
            original_stop(process)
            stopped.append(process.poll() is not None)

        def run(**kwargs):
            directory = runtime.workspace_root() / kwargs["job_id"]
            directory.mkdir(parents=True)
            sources = []
            for index, source in enumerate(kwargs["sources"]):
                name = "original-" + str(index) + ".png"
                (directory / name).write_bytes(source["payload"])
                sources.append({**source, "path": name})
            bridge = WitnessBridge(job_id=kwargs["job_id"], directory=directory,
                sources=sources, hooks=kwargs["hooks"], model_transport=httpx.MockTransport(transport))
            try:
                return bridge.run("Synthetic progress fixture; PRIVATE_REPORT_DO_NOT_PROJECT", deadline=time.time() + 25 * 60)
            except BaseException as error:
                errors.append(error)
                raise
            finally:
                path = directory / "host-state/host-checkpoint.json"
                if path.is_file():
                    checkpoints.append(json.loads(path.read_text()))

        with tempfile.TemporaryDirectory(prefix="cover-progress-") as state, \
                mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": state,
                    "NOTEAI_ARK_API_KEY": "offline-progress-no-provider-access",
                    "NOTEAI_MODEL_CAPACITY_MODE": "off"}), \
                mock.patch.object(billing, "_pricing_snapshot", side_effect=price), \
                mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=fake_concept), \
                mock.patch.object(runtime, "_stop_host", side_effect=stop):
            result = cover_service._run_claim(scope.claim, runtime=run)
        if errors and not isinstance(errors[0], provider.CoverAgentProviderError):
            raise errors[0]
        self.assertEqual(len(wire), 3)
        self.assertEqual(len(observed), 3)
        self.assertEqual(len(concepts), 1)
        self.assertEqual(public_progress, [("design", "waiting_model"),
            ("concept", "generating_reference"), ("layout", "waiting_model")])
        self.assertGreater(observed[0]["remaining_ms"], observed[1]["remaining_ms"])
        self.assertGreater(observed[1]["remaining_ms"], observed[2]["remaining_ms"])
        self.assertEqual(stopped, [True])
        self.assertTrue(errors[0].outcome_unknown)
        self.assertEqual(result["status"], "outcome_unknown")
        rows = db.fetchall("SELECT state,http_status FROM public_trial_calls WHERE usage_record_id=? ORDER BY created_at,id",
            (scope.claim["charge"]["usage_id"],))
        self.assertEqual([(row["state"], row["http_status"]) for row in rows],
            [("responded", 200), ("responded", 200), ("unknown", None)])
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 2)
        self.assertEqual(checkpoints[0]["model_requests"], 3)
        self.assertEqual(checkpoints[0]["local_tool_activity"]["attempts"]["cover_render"], 1)
        print("COVER_PROGRESS_SDK_PROOF=" + json.dumps({"actual_sdk": True,
            "stages": [item["stage"] for item in observed], "physical_mock_calls": 3,
            "known_mock_200": 2, "unknown_once": 1, "concept_stub_calls": 1,
            "batched_write_receipts_preserved": True, "error_receipt_preserved": True,
            "early_write_before_concept_preserved": True,
            "public_phases": [phase for phase, _ in public_progress],
            "render_or_qc_claimed": False, "real_supplier_calls": 0,
            "real_merchant_quality_acceptance": False}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
