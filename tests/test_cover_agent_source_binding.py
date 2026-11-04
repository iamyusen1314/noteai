"""Frozen-photo identity through the real SDK/CLI/capture boundary, no providers.

The optional authorized-nine manifest is an explicit local/isolated QA input.
The concept and final QC responses are technical stubs, never quality acceptance.
"""
import base64
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
import uuid
from unittest import mock

from tests import test_cover_agent_runtime as fixture

runtime, artifacts, provider = fixture.runtime, fixture.artifacts, fixture.provider
cover_runtime = fixture.cover_runtime


class RenderSourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "job"
        self.root.mkdir()
        self.body = fixture.synthetic_png((40, 30), "#367450")
        self.source = {"media_ref": "frozen-original", "path": "original.png", "payload": self.body,
            "sha256": artifacts.digest(self.body)}
        (self.root / "original.png").write_bytes(self.body)
        self.bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=self.root,
            sources=[self.source], hooks=mock.Mock())
        self.bridge.concept_hash = "seen-concept"
        self.bridge.seen_images.add("seen-concept")

    def request(self, **change):
        return {"name": "cover_render", "arguments": {"sources": [
            {"ref": "model-alias", "path": "original.png", "sha256": self.source["sha256"], **change}]}}

    def test_original_alias_and_project_copy_bind_to_the_frozen_media_identity(self):
        (self.root / "project").mkdir()
        (self.root / "project/copy.png").write_bytes(self.body)
        for project, path, authored_ref in ((".", "original.png", "frozen-original"),
                (".", "original.png", "model-alias"), ("project", "copy.png", "another-alias")):
            request = self.request(path=path, ref=authored_ref)
            request["arguments"]["project_dir"] = project
            before = deepcopy(request)
            answer = self.bridge.tool(request)
            self.assertEqual(answer, {"allowed": True, "canonical_sources": [
                {"ref": "frozen-original", "path": path, "sha256": self.source["sha256"]}]})
            self.assertEqual(request, before)

    def test_wrong_or_missing_authored_identity_is_replaced_only_for_real_frozen_bytes(self):
        for item in ({"path": "original.png"}, {"path": "original.png", "ref": "wrong-owner-alias", "sha256": "0" * 64},
                {"path": "original.png", "ref": "", "sha256": "not-a-checksum"}):
            request = {"name": "cover_render", "arguments": {"sources": [item]}}
            before = deepcopy(request)
            self.assertEqual(self.bridge.tool(request), {"allowed": True, "canonical_sources": [
                {"ref": self.source["media_ref"], "path": "original.png", "sha256": self.source["sha256"]}]})
            self.assertEqual(request, before)
            self.assertEqual(self.bridge.render_source_repairs, 0)

    def test_paths_other_photos_concept_and_symlinks_cannot_grant_original_identity(self):
        other = fixture.synthetic_png((40, 30), "#814276")
        (self.root / "other.png").write_bytes(other)
        (self.root / "concept.png").write_bytes(other)
        outside = self.root.parent / "outside.png"; outside.write_bytes(self.body)
        (self.root / "linked.png").symlink_to(outside)
        for path in ("missing.png", "../outside.png"):
            self.assertFalse(self.bridge.tool(self.request(path=path))["allowed"])
        for path in ("other.png", "concept.png", "linked.png"):
            with self.subTest(path=path), self.assertRaisesRegex(cover_runtime.CoverRuntimeError,
                    "COVER_AGENT_RENDER_SOURCE_INVALID"):
                self.bridge.tool(self.request(path=path, sha256=self.source["sha256"]))

    def test_oversize_file_is_rejected_without_reading_model_selected_bytes(self):
        (self.root / "too-large.png").write_bytes(self.body + b"X")
        real_fdopen = runtime.os.fdopen
        class Guarded:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def read(self, *_): raise AssertionError("Oversize source must never be read")
        def guarded(fd, *args, **kwargs): return Guarded(real_fdopen(fd, *args, **kwargs))
        with mock.patch.object(runtime.os, "fdopen", side_effect=guarded), \
                mock.patch.object(runtime, "_write_render_source_diagnostic"), \
                self.assertRaises(runtime._RenderSourceRejection) as caught:
            self.bridge.tool(self.request(path="too-large.png"))
        self.assertEqual(caught.exception.reason, "SOURCE_BYTES_CHANGED")

    def test_changed_bytes_and_duplicate_aliases_cannot_rebind_an_original(self):
        (self.root / "changed.png").write_bytes(b"x" * len(self.body))
        with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_RENDER_SOURCE_INVALID"):
            self.bridge.tool(self.request(path="changed.png"))
        request = self.request()
        request["arguments"]["sources"].append({**request["arguments"]["sources"][0], "ref": "second-alias"})
        rejection = self.bridge.tool(request)
        self.assertEqual(rejection["reason"], "DUPLICATE_ORIGINAL")
        self.assertFalse(rejection["allowed"])
        self.assertFalse(rejection["dispatched"])

    def test_duplicate_photo_bytes_choose_by_original_path_then_frozen_order_not_alias(self):
        second = {**self.source, "media_ref": "second-original", "path": "second.png"}
        self.bridge.sources.append(second)
        (self.root / "second.png").write_bytes(self.body)
        (self.root / "copy.png").write_bytes(self.body)
        self.assertEqual(self.bridge.tool(self.request(path="second.png"))["canonical_sources"][0]["ref"],
            "second-original")
        for alias in ("first-alias", "second-original"):
            self.assertEqual(self.bridge.tool(self.request(path="copy.png", ref=alias))["canonical_sources"][0]["ref"],
                "frozen-original")


class CaptureFailureDiagnosticTests(unittest.TestCase):
    def test_known_capture_failure_keeps_domain_code_and_survives_workspace_cleanup(self):
        for code in ("COVER_EDITABLE_SOURCE_CHANGED", "COVER_EDITABLE_LAYOUT_INVALID", "COVER_EDITABLE_HASH_INVALID"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ,
                    {"NOTEAI_COVER_AGENT_STATE_ROOT": root}):
                job = str(uuid.uuid4())
                directory = Path(root) / job
                directory.mkdir()
                with mock.patch.object(artifacts, "capture", side_effect=ValueError(code)):
                    with self.assertRaises(cover_runtime.CoverRuntimeError) as raised:
                        runtime._capture_artifact({}, expected_sources={}, directory=directory, job_id=job)
                self.assertEqual(raised.exception.code, code)
                runtime.cleanup_workspace(job)
                receipt = json.loads((Path(root) / "receipts" / (job + ".json")).read_text())
                self.assertEqual(receipt["post_host_failure"], {"stage": "artifact_capture",
                    "code": code, "exception_type": "ValueError"})

    def test_unexpected_capture_failure_records_only_fixed_code_and_exception_type(self):
        with tempfile.TemporaryDirectory() as root:
            directory, job = Path(root), str(uuid.uuid4())
            with mock.patch.object(artifacts, "capture", side_effect=KeyError("private fixture content")):
                with self.assertRaises(cover_runtime.CoverRuntimeError) as raised:
                    runtime._capture_artifact({}, expected_sources={}, directory=directory, job_id=job)
            self.assertEqual(raised.exception.code, "COVER_AGENT_CAPTURE_FAILED")
            diagnostic = runtime._read_post_host_diagnostic(directory, job)
            self.assertEqual(diagnostic, {"stage": "artifact_capture", "code": "COVER_AGENT_CAPTURE_FAILED",
                "exception_type": "KeyError"})
            self.assertNotIn("private fixture content", (directory / "host-state" /
                runtime._POST_HOST_DIAGNOSTIC_FILE).read_text())

    def test_original_unknown_and_domain_errors_are_not_reclassified(self):
        class UnknownError(RuntimeError):
            outcome_unknown = True
        with tempfile.TemporaryDirectory() as root:
            for original in (UnknownError("fixture unknown"), cover_runtime.CoverRuntimeError("COVER_SOURCE_HASH_CHANGED")):
                with mock.patch.object(artifacts, "capture", side_effect=original):
                    with self.assertRaises(type(original)) as raised:
                        runtime._capture_artifact({}, expected_sources={}, directory=Path(root), job_id=str(uuid.uuid4()))
                self.assertIs(raised.exception, original)
            self.assertEqual(list(Path(root).rglob("*.json")), [])


class HostCanonicalSourceReplyTests(unittest.TestCase):
    def test_actual_host_requires_the_authoritative_source_reply_before_cli(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for actual host callback")
        source = Path(runtime.__file__).parent / "cover_agent_host/host.mjs"
        script = r'''
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';import assert from 'node:assert/strict';
const source=fs.readFileSync(process.argv[1],'utf8');let callback,canonical,CLI=0;
const ctx=vm.createContext({path,process:{execPath:process.execPath},fs:{realpath:async x=>x},
 job:{work_dir:'/owned-job',editable_cli:'/cli'},inside:()=>true,objectSchema:()=>({}),
 error:code=>Object.assign(new Error(code),{code}),tool:(_n,_d,_s,execute)=>{callback=execute;},
 bridge:async()=>({result:{allowed:true,canonical_sources:canonical}}),
 runLocal:async()=>{CLI++;throw new Error('CLI must not run');}});
vm.runInContext(source.slice(source.indexOf("    tool('cover_render',"),source.indexOf("    tool('cover_check',")).trim().replace(/,$/,''),ctx);
for(const bad of [undefined,[],[{ref:'alias',path:'source.jpg',sha256:'bad'}]]){
 canonical=bad;await assert.rejects(callback({request:{project_dir:'.'}}),e=>e.code==='RENDER_SOURCE_BINDING_INVALID');
}assert.equal(CLI,0);console.log('canonical-source-required');
'''
        result = subprocess.run([node, "--input-type=module", "-e", script, str(source)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("canonical-source-required", result.stdout)


class CanonicalSourceScriptedBridge(fixture.ScriptedBridge):
    """Extend the existing real-SDK fixture, preserving its actual CLI/capture."""
    case = "original"
    instances = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.first = True
        self.copy_path = None
        if self.case == "project_copy":
            self.copy_path = "assets/copied-photo.jpg"
            target = self.directory / self.copy_path
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(self.sources[0]["payload"])

    def run(self, prompt, *, deadline):
        result = runtime.Bridge.run(self, prompt, deadline=min(deadline, time.time() + 300))
        self.host_results.append(result)
        return result

    def model(self, payload, stage="design"):
        if self.first and stage == "design":
            self.first = False
            prepared, bound = provider.prepare_payload(self._restore_thinking(payload))
            hashes = runtime._images_in(prepared)
            self.seen_images.update(hashes)
            missing = [source for source in self.sources if source["sha256"] not in self.seen_images]
            if not missing:
                return super().model(payload, stage=stage)
            self.ordinal += 1
            self.requests.append({"stage": stage, "input_bound": bound, "image_sha256": sorted(hashes)})
            return self.response(None, [("cover_view", {"path": source["path"]}) for source in missing]), "offline-preface"
        if stage == "design" and self.design_turn == 5 and self.case in {"wrong_path"}:
            rejection = fixture.returned_value(payload, "recoverable")
            if rejection.get("allowed") is not False or rejection.get("dispatched") is not False:
                raise AssertionError("Rejected source was approved")
            # This negative fixture ends here; the recovery SDK fixture owns
            # the subsequent new corrected declaration and actual rendering.
            raise cover_runtime.CoverRuntimeError("COVER_AGENT_RENDER_SOURCE_INVALID")
        try:
            return super().model(payload, stage=stage)
        finally:
            # Retain only content-free request evidence, as production does.
            if self.requests:
                self.requests[-1].pop("body", None)

    def response(self, text, calls=None):
        if calls:
            calls = deepcopy(calls)
            for name, arguments in calls:
                if name != "cover_render":
                    continue
                source = arguments["request"]["sources"][0]
                if self.case in {"alias", "project_copy"}:
                    source["ref"] = "model-local-alias"
                if self.copy_path:
                    source["path"] = self.copy_path
                if self.case in {"wrong_hash", "project_copy"}:
                    source["sha256"] = "not-an-authority"
                if self.case == "path_only":
                    source.pop("ref"); source.pop("sha256")
                if self.case == "wrong_path":
                    source["path"] = "../outside.jpg"
                if self.case == "unauthorized_concept":
                    source.update(path="reference/composition-reference.png", sha256=self.concept_hash)
        # The inherited fixture identifies its contract/render tool responses by
        # design turn. The extra original-view preface adds one physical stub turn.
        message = {"role": "assistant", "content": text,
            "encrypted_content": "TEST_OPAQUE_COVER_runtime_" + str(self.ordinal)}
        if calls:
            message["tool_calls"] = [{"id": "fixture_" + str(self.design_turn) + "_" + str(index),
                "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                for index, (name, args) in enumerate(calls)]
        return self.thinking.remember({"id": "chatcmpl-offline-runtime", "object": "chat.completion", "created": 1,
            "model": provider.MODEL, "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    def html(self, source_path):
        return fixture.ScriptedBridge.html(self.copy_path or source_path)


class CanonicalSourceSDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") or not shutil.which("node"):
            raise unittest.SkipTest("Explicit pinned task-local SDK and Node required")
        manifest = os.environ.get("NOTEAI_COVER_REAL_NINE_MANIFEST")
        cls.sources = []
        if manifest:
            value = json.loads(Path(manifest).read_text())
            for item in value["files"]:
                body = Path(item["path"]).read_bytes()
                if len(body) != item["bytes"] or artifacts.digest(body) != item["sha256"]:
                    raise AssertionError("Authorized original-nine byte/hash mismatch")
                cls.sources.append({"media_ref": item["media_ref"], "sha256": item["sha256"], "payload": body})
        else:
            for index in range(9):
                body = fixture.synthetic_png((600, 400), "#" + format(0x365170 + index * 100, "06x"))
                cls.sources.append({"media_ref": "offline-original-" + str(index),
                    "sha256": artifacts.digest(body), "payload": body})
        if len(cls.sources) != 9 or len({source["sha256"] for source in cls.sources}) != 9:
            raise AssertionError("Nine distinct original images required")
        cls.proofs = []

    @classmethod
    def tearDownClass(cls):
        target = os.environ.get("NOTEAI_COVER_SOURCE_BINDING_PROOF")
        if target:
            Path(target).write_text(json.dumps({"real_original_manifest": bool(os.environ.get("NOTEAI_COVER_REAL_NINE_MANIFEST")),
                "original_count": len(cls.sources), "original_bytes": sum(len(s["payload"]) for s in cls.sources),
                "physical_provider_calls": 0, "production_DB_writes": 0, "QC_is_synthetic_stub": True,
                "cases": cls.proofs}, indent=2) + "\n")

    def saved_edit_identity(self, result):
        # Exercise the normal private-bundle store/load and free-edit functions
        # in the existing isolated owner/SQLite/object-backend fixture. This is
        # not production login, settlement, or merchant aesthetic acceptance.
        from tests.test_cover_jobs import CoverJobsTests
        storage = CoverJobsTests()
        storage.setUp()
        try:
            task, _ = storage.claim()
            layout = deepcopy(result.layout)
            layout["editable_ref"] = artifacts.store(storage.user, task["job_id"],
                result.artifact["editable_bundle"])
            saved = artifacts.validate_saved(storage.user, layout, final_bytes=result.final_bytes)
            self.assertEqual(saved, result.artifact["editable_bundle"])
            before = storage.balances()
            edited, updated = artifacts.adjust(storage.user, task["job_id"], layout,
                text="原照独立\n图层中文排字测试", position=None, layer_id="title",
                revision=2, ttl_seconds=3 * 86400)
            edited_bundle = artifacts.validate_saved(storage.user, updated, final_bytes=edited)
            self.assertEqual(updated["source_hashes"], layout["source_hashes"])
            self.assertEqual(updated["input_source_hashes"], layout["input_source_hashes"])
            self.assertEqual(updated["initial_qc_ref"], layout["initial_qc_ref"])
            self.assertEqual(updated["qc_status"], "USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
            self.assertEqual(storage.balances(), before, "Normal free edit must not charge credits")
            manifest = json.loads(base64.b64decode(json.loads(edited_bundle)["files"]["render-manifest.json"]))
            self.assertEqual({x["ref"]: x["sha256"] for x in manifest["constraints"]["sources"]},
                layout["source_hashes"])
            with self.assertRaises(Exception):
                artifacts.validate_saved(storage.other, updated)
            return {"normal_private_bundle_store_load": True, "actual_free_edit_and_recapture": True,
                "source_identity_unchanged": True, "isolated_owner_check": True,
                "free_edit_credit_delta": 0, "physical_model_calls": 0}
        finally:
            storage.tearDown()

    def run_case(self, case, *, rejected=False):
        concept = fixture.synthetic_png((1776, 2368), "#a1a8b1")
        candidates, stops = [], []
        saved_edit = None
        CanonicalSourceScriptedBridge.instances = []
        CanonicalSourceScriptedBridge.case = case
        def on_candidate(snapshot, body):
            self.assertEqual(artifacts.digest(body), snapshot["final_sha256"])
            candidates.append({"source_hashes": snapshot["source_hashes"], "qc_present": snapshot["qc"] is not None})
        hooks = cover_runtime.RuntimeHooks(lambda *_: None, lambda *_: None, lambda *_: None, on_candidate=on_candidate)
        def concept_stub(**kwargs):
            self.assertEqual(kwargs["source_images"], [s["payload"] for s in self.sources])
            record = {"stage": "image", "status": "responded", "provider": "offline-stub", "call_id": kwargs["call_id"]}
            kwargs["before_call"]("image", kwargs["call_id"], {})
            kwargs["on_call"](record)
            return concept, record
        original_stop = runtime._stop_host
        def real_stop(process):
            original_stop(process)
            stops.append({"reaped": process.poll() is not None, "returncode": process.poll()})
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": root}), \
                mock.patch.object(provider, "complete", side_effect=AssertionError("Physical provider forbidden")) as complete, \
                mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=concept_stub) as image, \
                mock.patch.object(runtime, "_stop_host", side_effect=real_stop):
            job = str(uuid.uuid4())
            try:
                kwargs = dict(job_id=job, user_id="offline-owner", sources=self.sources, hooks=hooks,
                    report={"title": "原照独立图层中文排字测试", "body": "技术边界夹具，不代表商家成品审美验收。", "title_variants": []},
                    bridge_class=CanonicalSourceScriptedBridge)
                if rejected:
                    with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_RENDER_SOURCE_INVALID"):
                        runtime.run_cover(**kwargs)
                    self.assertFalse(list((Path(root) / job / "revisions").glob("*/render-manifest.json")))
                    self.assertEqual(candidates, [])
                else:
                    result = runtime.run_cover(**kwargs)
                    self.assertEqual(result.layout["source_hashes"], {self.sources[0]["media_ref"]: self.sources[0]["sha256"]})
                    self.assertEqual(len(result.layout["input_source_hashes"]), 9)
                    self.assertEqual(len(candidates), 2)
                    self.assertTrue(candidates[-1]["qc_present"])
                    if case == "wrong_hash":
                        saved_edit = self.saved_edit_identity(result)
                bridge = CanonicalSourceScriptedBridge.instances[-1]
                self.assertTrue({s["sha256"] for s in self.sources}.issubset(bridge.seen_images))
                self.assertEqual(image.call_count, 1)
                complete.assert_not_called()
                self.assertEqual(len(stops), 1)
                self.assertTrue(stops[0]["reaped"])
                self.proofs.append({"case": case, "rejected_before_CLI_render": rejected,
                    "actual_host_complete": bool(bridge.host_results and bridge.host_results[-1]["status"] == "COMPLETE"),
                    "originals_wire_seen": 9, "candidate_callbacks": candidates, "real_host_cleanup": stops,
                    "scripted_model_responses": len(bridge.requests), "physical_provider_calls": 0,
                    "saved_edit_identity": saved_edit})
            finally:
                runtime.cleanup_workspace(job)

    def test_original_identity_passes_actual_sdk_cli_capture_and_candidate(self):
        self.run_case("original")

    def test_alias_is_canonicalized_before_actual_cli_capture_and_candidate(self):
        self.run_case("alias")

    def test_project_copy_keeps_exact_original_bytes_and_canonical_identity(self):
        self.run_case("project_copy")

    def test_authored_wrong_hash_is_replaced_by_real_bytes_before_actual_capture(self):
        self.run_case("wrong_hash")

    def test_path_only_tool_input_uses_backend_identity_through_actual_capture(self):
        self.run_case("path_only")

    def test_wrong_path_is_denied_before_actual_cli_render(self):
        self.run_case("wrong_path", rejected=True)

    def test_concept_is_not_an_authorized_shipping_original(self):
        self.run_case("unauthorized_concept", rejected=True)


if __name__ == "__main__":
    unittest.main()
