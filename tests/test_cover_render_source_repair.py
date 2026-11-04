"""Bounded pre-render source declaration feedback; no external suppliers."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest import mock

from tests import test_cover_agent_runtime as fixture
from tests import test_cover_agent_source_binding as binding

runtime, artifacts, cover_runtime = fixture.runtime, fixture.artifacts, fixture.cover_runtime


class RenderSourceRepairTests(unittest.TestCase):
    setUp = binding.RenderSourceBindingTests.setUp
    request = binding.RenderSourceBindingTests.request

    def test_authored_declaration_errors_are_rejected_without_file_access_or_render(self):
        cases = [({"path": "missing.png"}, "PATH_NOT_FOUND"),
            ({"path": "../outside.png"}, "PATH_NOT_ALLOWED"),
            ({"path": "/not-owned/photo.png"}, "PATH_NOT_ALLOWED"),
            ({"path": "./original.png"}, "PATH_NOT_ALLOWED")]
        for change, reason in cases:
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=self.root,
                sources=[self.source], hooks=mock.Mock())
            bridge.concept_hash = "seen-concept"; bridge.seen_images.add("seen-concept")
            with self.subTest(reason=reason, path=change.get("path")):
                answer = bridge.tool(self.request(**change))
                self.assertEqual(answer, {"allowed": False, "code": "COVER_AGENT_RENDER_SOURCE_INVALID",
                    "recoverable": True, "dispatched": False, "reason": reason,
                    "repair_attempt": 1, "repair_limit": 2, "originals": [{"ref": self.source["media_ref"],
                    "path": self.source["path"], "sha256": self.source["sha256"]}]})
                self.assertFalse((self.root / "revisions").exists())
                bridge.hooks.before_call.assert_not_called()
        with mock.patch.object(runtime.artifacts, "relative", side_effect=ValueError("private path")), \
                mock.patch.object(runtime, "_write_render_source_diagnostic"), \
                mock.patch.object(runtime.Path, "is_symlink", side_effect=AssertionError("No outside probe")):
            self.assertEqual(self.bridge.tool(self.request(path="../outside.png"))["reason"], "PATH_NOT_ALLOWED")

    def test_repair_budget_is_job_wide_and_valid_render_approval_does_not_reset_it(self):
        rejected = self.bridge.tool(self.request(path="missing.png"))
        self.assertEqual(rejected["repair_attempt"], 1)
        self.assertTrue(self.bridge.tool(self.request())["allowed"])
        duplicate = self.request()
        duplicate["arguments"]["sources"] *= 2
        rejected = self.bridge.tool(duplicate)
        self.assertEqual((rejected["reason"], rejected["repair_attempt"]), ("DUPLICATE_ORIGINAL", 2))
        self.assertTrue(self.bridge.tool(self.request())["allowed"])
        with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_RENDER_SOURCE_INVALID"):
            self.bridge.tool(self.request(path="missing.png"))
        self.assertEqual(self.bridge.render_source_repairs, 2)
        self.assertIsNone(self.bridge.concept_record)
        self.assertEqual(self.bridge.seen_images, {"seen-concept"})

    def test_changed_missing_linked_special_or_corrupt_originals_are_still_terminal(self):
        changed = self.root / "changed.png"; changed.write_bytes(b"x" * len(self.body))
        linked = self.root / "linked.png"; linked.symlink_to(self.root / "original.png")
        (self.root / "directory.png").mkdir()
        for path, reason in (("changed.png", "SOURCE_BYTES_CHANGED"), ("linked.png", "SOURCE_LINK"),
                ("directory.png", "SOURCE_NOT_REGULAR")):
            with self.subTest(path=path), self.assertRaises(runtime._RenderSourceRejection) as caught:
                self.bridge.tool(self.request(path=path))
            self.assertEqual(caught.exception.reason, reason)
        (self.root / "original.png").unlink()
        with self.assertRaises(runtime._RenderSourceRejection) as caught:
            self.bridge.tool(self.request())
        self.assertEqual(caught.exception.reason, "SOURCE_ORIGINAL_MISSING")
        (self.root / "original.png").write_bytes(self.body)
        self.source["payload"] = b"corrupt frozen bytes"
        with self.assertRaises(runtime._RenderSourceRejection) as caught:
            self.bridge.tool(self.request())
        self.assertEqual(caught.exception.reason, "FROZEN_ORIGINAL_INVALID")
        self.assertEqual(self.bridge.render_source_repairs, 0)

    def test_first_safe_reason_survives_cleanup_without_authored_fields_or_pending_changes(self):
        job = self.bridge.job_id
        # cleanup expects the normal UUID directory beneath the configured root.
        directory = self.root.parent / job
        self.root.rename(directory); self.bridge.directory = directory
        self.root = directory
        state = directory / "host-state"; state.mkdir()
        pending = {"ordinal": 3, "label": "primary", "body_sha256": "a" * 64}
        checkpoint = {"status": "UNKNOWN", "model_requests": 3, "pending_request": pending}
        (state / "host-checkpoint.json").write_text(json.dumps(checkpoint))
        self.bridge.tool(self.request(path="private-authored-missing.png"))
        first = (state / runtime._RENDER_SOURCE_DIAGNOSTIC_FILE).read_bytes()
        self.bridge.tool(self.request(path="missing.png"))
        self.assertEqual((state / runtime._RENDER_SOURCE_DIAGNOSTIC_FILE).read_bytes(), first)
        with mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": str(directory.parent)}):
            runtime.cleanup_workspace(job)
        receipt = json.loads((directory.parent / "receipts" / (job + ".json")).read_text())
        self.assertEqual(receipt["pending_request"], pending)
        self.assertEqual(receipt["status"], "UNKNOWN")
        self.assertEqual(receipt["first_render_source_rejection"], {"reason": "PATH_NOT_FOUND",
            "repair_attempt": 1, "repair_limit": 2, "recoverable": True, "dispatched": False})
        self.assertNotIn("private-authored", json.dumps(receipt))
        self.assertNotIn("originals", json.dumps(receipt))
        diagnostic = receipt["first_render_source_rejection"]
        for value in ({**diagnostic, "rawargs": "private"}, {**diagnostic, "reason": "PRIVATE"},
                {**diagnostic, "dispatched": True}, {**diagnostic, "repair_attempt": True},
                {**diagnostic, "repair_attempt": 3}, {**diagnostic, "repair_limit": True}):
            self.assertIsNone(runtime._render_source_diagnostic(value))

    def test_optional_diagnostic_failure_never_changes_the_rejection_or_hard_error(self):
        with mock.patch.object(runtime, "_write_render_source_diagnostic", side_effect=OSError("PRIVATE")), \
                self.assertLogs(level="WARNING") as logs:
            answer = self.bridge.tool(self.request(path="missing.png"))
            (self.root / "original.png").write_bytes(b"x" * len(self.body))
            with self.assertRaises(runtime._RenderSourceRejection) as caught:
                self.bridge.tool(self.request())
        self.assertEqual(caught.exception.reason, "SOURCE_BYTES_CHANGED")
        self.assertTrue(answer["recoverable"])
        self.assertNotIn("PRIVATE", json.dumps(logs.output))

    def test_actual_host_only_accepts_exact_authoritative_feedback_and_never_runs_cli(self):
        source = Path(__file__).resolve().parents[1] / "model/cover_agent_host/host.mjs"
        script = r'''
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';import assert from 'node:assert/strict';
const source=fs.readFileSync(process.argv[1],'utf8');let handler,answer,cli=0,writes=0;
const image={name:'original',path:'assets/source.png',sha256:'a'.repeat(64)};
const make=attempt=>({allowed:false,code:'COVER_AGENT_RENDER_SOURCE_INVALID',dispatched:false,recoverable:true,
 reason:'PATH_NOT_ALLOWED',repair_attempt:attempt,repair_limit:2,originals:[{ref:image.name,path:image.path,sha256:image.sha256}]});
const ctx=vm.createContext({path,process:{execPath:process.execPath},fs:{realpath:async x=>x},
 job:{work_dir:'/owned',images:[image]},checkpoint:{pending_request:{ordinal:7},concept_requested:true},checkpointPath:'owned',
 error:code=>Object.assign(new Error(code),{code}),inside:()=>true,objectSchema:()=>({}),
 tool:(n,d,s,callback)=>{handler=callback;},bridge:async()=>answer,
 atomicJSON:async()=>{writes++;},runLocal:async()=>{cli++;assert.fail('CLI must not run for rejected source');}});
vm.runInContext(source.slice(source.indexOf('function recoverableRenderSourceRejection('),source.indexOf('const send ='))
 +source.slice(source.indexOf("    tool('cover_render',"),source.indexOf("    tool('cover_check',")).trim().replace(/,$/,''),ctx);
for(const attempt of [1,2]){answer={result:make(attempt)};const result=await handler({request:{project_dir:'.'}});
 assert.equal(JSON.parse(result.content).repair_attempt,attempt);assert.equal(ctx.checkpoint.render_source_repairs,attempt);}
assert.equal(ctx.checkpoint.pending_request.ordinal,7);assert.equal(ctx.checkpoint.concept_requested,true);
answer={result:make(3)};await assert.rejects(handler({request:{}}),/RENDER_SOURCE_REPAIR_INVALID/);
for(const mutate of [x=>x.originals[0].ref='other',x=>x.originals[0].path='../outside',x=>x.originals[0].sha256='b'.repeat(64),
 x=>x.originals.push(x.originals[0]),x=>x.dispatched=true,x=>x.recoverable=false,x=>x.reason='PRIVATE',x=>x.extra='raw',x=>x.repair_attempt=2]){
 ctx.checkpoint.render_source_repairs=0;const bad=make(1);mutate(bad);answer={result:bad};
 await assert.rejects(handler({request:{}}),/RENDER_SOURCE_REPAIR_INVALID/);}
ctx.checkpoint.render_source_repairs=0;answer={unknown:true,result:make(1)};
await assert.rejects(handler({request:{}}),/SUPPLIER_RESULT_UNKNOWN/);
assert.equal(cli,0);assert.equal(writes,2);console.log(JSON.stringify({pass:true,cli:0,accepted_rejections:2,forged_feedback_rejected:true}));
'''
        result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "--input-type=module", "-e", script,
            str(source)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["pass"])


class SourceRepairScriptedBridge(fixture.ScriptedBridge):
    instances = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rejections = []; self.repair_phase = None; self.valid_request = None
        self.fixed_call_id = None

    def response(self, text, calls=None):
        if calls and self.design_turn == 5 and self.repair_phase is None:
            calls = deepcopy(calls)
            for name, args in calls:
                if name == "cover_render":
                    self.valid_request = deepcopy(args)
                    args["request"]["sources"][0]["path"] = "missing-original.png"
                    self.repair_phase = "rejected"
        return super().response(text, calls)

    def model(self, payload, stage="design"):
        if stage == "qc" or self.repair_phase is None:
            return super().model(payload, stage=stage)
        prepared, bound = fixture.provider.prepare_payload(self._restore_thinking(payload))
        self.ordinal += 1
        hashes = runtime._images_in(prepared); self.seen_images.update(hashes)
        self.requests.append({"stage": stage, "input_bound": bound, "image_sha256": sorted(hashes)})
        if self.repair_phase == "rejected":
            rejection = fixture.returned_value(prepared, "recoverable")
            assert rejection["allowed"] is False and rejection["dispatched"] is False
            assert rejection["originals"] == [{"ref": s["media_ref"], "path": s["path"], "sha256": s["sha256"]} for s in self.sources]
            assert not list((self.directory / "revisions").glob("*/render-manifest.json"))
            self.rejections.append({key: rejection[key] for key in ("reason", "repair_attempt", "repair_limit", "dispatched")})
            request = deepcopy(self.valid_request)
            if len(self.rejections) == 1:
                request["request"]["sources"][0]["path"] = "../outside.png"
            else:
                self.repair_phase = "rendered"
            self.fixed_call_id = "fixture_" + str(self.ordinal) + "_0"
            return self.response(None, [("cover_render", request)]), "offline-source-repair"
        if self.repair_phase == "rendered":
            rendered = fixture.returned_value(prepared, "png_path", tool_call_id=self.fixed_call_id)
            self.rendered_tool = rendered; self.repair_phase = "reviewed"
            return self.response(None, [("cover_view", {"path": rendered["image_path"]})]), "offline-render-view"
        assert self.rendered_tool["png_sha256"] in hashes and self.rendered_tool["thumbnail_sha256"] in hashes
        return self.response("Synthetic source declaration corrected and actual render inspected."), "offline-stop"


@unittest.skipUnless(os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") and shutil.which("node"),
    "Explicit pinned SDK and Node required")
class RenderSourceRepairSDKTests(unittest.TestCase):
    def test_actual_sdk_two_precli_rejections_then_new_valid_request_renders_and_captures(self):
        body = fixture.synthetic_png((600, 400), "#367450")
        source = {"media_ref": "synthetic-original", "payload": body, "sha256": artifacts.digest(body)}
        concept = fixture.synthetic_png((1776, 2368), "#a1a8b1")
        candidates = []
        hooks = cover_runtime.RuntimeHooks(lambda *_: None, lambda *_: None, lambda *_: None,
            on_candidate=lambda snapshot, final: candidates.append({"sha256": artifacts.digest(final), **snapshot}))
        def image_stub(**kwargs):
            record = {"stage": "image", "status": "responded", "provider": "synthetic-local-stub", "call_id": kwargs["call_id"]}
            kwargs["before_call"]("image", kwargs["call_id"], {}); kwargs["on_call"](record)
            return concept, record
        SourceRepairScriptedBridge.instances = []
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": root}), \
                mock.patch.object(fixture.provider, "complete", side_effect=AssertionError("Supplier forbidden")) as complete, \
                mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=image_stub) as image:
            job = str(uuid.uuid4())
            result = runtime.run_cover(job_id=job, user_id="synthetic-owner", sources=[source], hooks=hooks,
                report={"title": "原照独立图层中文排字测试", "body": "合成技术测试，不代表实际商家成品或审美验收。", "title_variants": []},
                bridge_class=SourceRepairScriptedBridge)
            bridge = SourceRepairScriptedBridge.instances[-1]
            self.assertEqual([r["reason"] for r in bridge.rejections], ["PATH_NOT_FOUND", "PATH_NOT_ALLOWED"])
            self.assertEqual([r["repair_attempt"] for r in bridge.rejections], [1, 2])
            self.assertEqual(result.layout["source_hashes"], {source["media_ref"]: source["sha256"]})
            self.assertEqual(result.layout["final_sha256"], artifacts.digest(result.final_bytes))
            self.assertTrue(bridge.host_results[-1]["ok"])
            self.assertEqual(bridge.render_source_repairs, 2)
            self.assertEqual(image.call_count, 1)
            complete.assert_not_called()
            self.assertEqual(len(candidates), 2)
            bundle = artifacts.restore(result.artifact["editable_bundle"], Path(root) / "restored")
            self.assertEqual((bundle / "assets/source-1.png").read_bytes(), body)
            state = json.loads((Path(root) / job / "host-state/host-checkpoint.json").read_text())
            self.assertEqual(state["render_source_repairs"], 2)
            self.assertEqual(state["local_tool_activity"]["attempts"]["cover_render"], 3)
            print("SOURCE_REPAIR_SDK_PROOF=" + json.dumps({"rejections": bridge.rejections,
                "CLI_before_repair": 0, "actual_PNG_bytes": len(result.final_bytes), "actual_PNG_sha256": artifacts.digest(result.final_bytes),
                "actual_source_captured": True, "actual_candidate_callbacks": len(candidates), "QC_is_stub": True,
                "synthetic_model_responses": len(bridge.requests), "concept_stub_calls": image.call_count,
                "physical_supplier_calls": 0, "production_DB_writes": 0}))
            runtime.cleanup_workspace(job)
