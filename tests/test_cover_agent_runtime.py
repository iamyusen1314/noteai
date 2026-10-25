"""Real local SDK/tool/CLI integration with a scripted synthetic provider.

This deliberately does not exercise billing/UNKNOWN accounting (separate tests
own those). It calls no external model, uses no merchant photo and opens no DB.
Set NOTEAI_COVER_HOST_NODE_MODULES to the approved local SDK installation.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

import httpx
from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_agent_artifacts as artifacts
import cover_agent_provider as provider
import cover_agent_runtime as runtime
import cover_runtime


def synthetic_png(size, color):
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.ellipse((size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4), fill="#CBAE70")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def returned_value(body, required, *, tool_call_id=None):
    """Decode the actual SDK tool message, rather than a test-specific shortcut."""
    def find(value):
        if isinstance(value, str):
            try:
                return find(json.loads(value))
            except (ValueError, TypeError):
                return None
        if isinstance(value, dict):
            if required in value:
                return value
            for child in reversed(list(value.values())):
                answer = find(child)
                if answer is not None:
                    return answer
        if isinstance(value, list):
            for child in reversed(value):
                answer = find(child)
                if answer is not None:
                    return answer
        return None
    for message in reversed(body["messages"]):
        if message["role"] == "tool" and (tool_call_id is None or message.get("tool_call_id") == tool_call_id):
            value = find(message.get("content"))
            if value is not None:
                return value
    raise AssertionError("SDK did not expose expected tool field: " + required)


class ProviderDeadlineBridgeTests(unittest.TestCase):
    def test_short_host_deadline_stops_before_intent_or_supplier(self):
        with tempfile.TemporaryDirectory() as root:
            hooks = mock.Mock()
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path(root), sources=[], hooks=hooks)
            bridge.request_deadline = time.time() + 139
            with mock.patch.object(runtime.public_product, "assert_result_known"), \
                    mock.patch.object(provider, "complete") as complete:
                with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_TASK_DEADLINE"):
                    bridge.model({"messages": [{"role": "user", "content": "deadline fixture"}]})
            hooks.before_call.assert_not_called()
            complete.assert_not_called()
            self.assertEqual(bridge.ordinal, 0)

    def test_qc_reuses_the_original_host_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path(root), sources=[], hooks=mock.Mock())
            bridge.request_deadline = time.time() + 500
            response = {"choices": [{"message": {"role": "assistant", "content": "synthetic QC"}}]}
            with mock.patch.object(runtime.public_product, "assert_result_known"), \
                    mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                    mock.patch.object(provider, "complete", return_value=response) as complete:
                bridge.model({"messages": [{"role": "user", "content": "deadline fixture"}]}, stage="qc")
            self.assertEqual(complete.call_args.kwargs["deadline"], bridge.request_deadline)
            self.assertEqual(bridge.ordinal, 1)


class TitleScopeBridgeTests(unittest.TestCase):
    def test_render_scope_comes_from_report_not_authored_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path(root), sources=[], hooks=mock.Mock())
            bridge.concept_hash = "seen-concept"
            bridge.seen_images.add(bridge.concept_hash)
            bridge.approved_titles = ["水石清池：藏在高楼里的日式枯山水汤泉"]
            answer = bridge.tool({"name": "cover_render", "arguments": {"approved_titles": ["任意新宣传词"]}})
            self.assertEqual(answer, {"allowed": True, "approved_titles": bridge.approved_titles})
            answer["approved_titles"].append("mutated response")
            self.assertEqual(len(bridge.approved_titles), 1)


class ReturnedValueTests(unittest.TestCase):
    def test_contract_and_render_results_keep_their_tool_call_identity(self):
        body = {"messages": [
            {"role": "tool", "tool_call_id": "fixture_5_0", "content": json.dumps({
                "code": 0, "stdout": json.dumps({"pass": True, "checks": []}), "stderr": ""})},
            {"role": "tool", "tool_call_id": "fixture_5_1", "content": json.dumps({
                "ok": False, "code": "UPSTREAM_EDITABLE_CONTRACT_FAILED", "model_calls": 0})},
        ]}
        self.assertEqual(returned_value(body, "code")["code"], "UPSTREAM_EDITABLE_CONTRACT_FAILED")
        contract = returned_value(body, "code", tool_call_id="fixture_5_0")
        self.assertEqual(contract["code"], 0)
        self.assertIs(json.loads(contract["stdout"])["pass"], True)
        self.assertEqual(returned_value(body, "code", tool_call_id="fixture_5_1")["code"],
            "UPSTREAM_EDITABLE_CONTRACT_FAILED")
        with self.assertRaisesRegex(AssertionError, "png_path"):
            returned_value(body, "png_path", tool_call_id="fixture_5_1")
        with self.assertRaisesRegex(AssertionError, "code"):
            returned_value(body, "code", tool_call_id="missing")


class HostFontBoundaryTests(unittest.TestCase):
    def test_actual_render_tool_overrides_authored_title_scope_and_returns_local_error(self):
        node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        if not node:
            self.skipTest("Node required for actual host tool boundary")
        source = Path(__file__).resolve().parents[1] / "model/cover_agent_host/host.mjs"
        script = r'''
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(process.argv[1],'utf8');
const segment=source.slice(source.indexOf("    tool('cover_render',"),source.indexOf("    tool('cover_check',")).trim().replace(/,$/,'');
let handler, scope, rendered;
const local={ok:false,code:'COVER_DESIGN_TEXT_NOT_FROM_TITLE',detail:'headline'};
const ctx=vm.createContext({path,process:{execPath:process.execPath},
  fs:{realpath:async p=>p},job:{work_dir:'/owned-job',editable_cli:'/existing-cli'},
  inside:()=>true,error:code=>new Error(code),objectSchema:()=>({}),
  tool:(name,description,schema,callback)=>{assert.equal(name,'cover_render');handler=callback;},
  bridge:async()=>({result:{allowed:true,...(scope===undefined?{}:{approved_titles:scope})}}),
  runLocal:async(command,args,cwd,input)=>{rendered=JSON.parse(input);return {code:1,stdout:JSON.stringify(local)};}});
vm.runInContext(segment,ctx);
for (const trusted of [['原标题'],undefined]) {
  scope=trusted;
  const response=await handler({request:{project_dir:'.',approved_titles:['伪造范围']}});
  if(trusted) assert.deepEqual(rendered.approved_titles,trusted);
  else assert.equal(Object.hasOwn(rendered,'approved_titles'),false);
  assert.deepEqual(JSON.parse(response.content),local);
}
console.log(JSON.stringify({pass:true,real_host_tool:true,model_calls:0}));
'''
        result = subprocess.run([node, "--input-type=module", "-e", script, str(source)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["pass"])

    def test_actual_helpers_preserve_authored_content_and_do_not_mask_original_errors(self):
        node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        if not node:
            self.skipTest("Node required for actual host helper checks")
        source = Path(__file__).resolve().parents[1] / "model/cover_agent_host/host.mjs"
        script = r'''
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const source=fs.readFileSync(process.argv[1],'utf8');
const segment=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end));
const ctx=vm.createContext({Buffer,checkpoint:{},requests:14,
  sha:(v)=>createHash('sha256').update(v).digest('hex'),
  error:(code)=>Object.assign(new Error(code),{code})});
vm.runInContext(segment('function fontFaces(', 'async function atomicJSON(')
  +segment('function inputMeasurement(', 'function summaryMaterial('),ctx);
const quoted='<style>/* --font-title: serif; */ .x{content:" --font-title: fake; "}</style>';
assert.throws(()=>ctx.bindFontRole(quoted,'cjk-serif','--font-title'),/FONT_ROLE_DECLARATION_MUST_BE_UNIQUE/);
const html=quoted.replace('</style>', ':root{--font-title:"System Serif",serif;--color:#123}</style>');
assert.equal(ctx.bindFontRole(html,'cjk-serif','--font-title',true),html);
const bound=ctx.bindFontRole(html,'cjk-serif','--font-title');
assert.equal(bound,html.replace('--font-title:"System Serif",serif;','--font-title: var(--font-kit-cjk-serif);'));
assert.throws(()=>ctx.bindFontRole(html,'cjk-serif','--font-kit-cjk-serif'),/FONT_ROLE_VARIABLE_INVALID/);
const unknown='@font-face {font-family:"Authored";src:url("./assets/fonts/cjk-serif/custom.woff2");}';
const known='@font-face {font-family:"Installed";src:url("./assets/fonts/cjk-serif/known.woff2");}';
const before='<style>'+unknown+':root{--font-title:serif;}</style><h1>KEEP_ORIGINAL_TITLE</h1>';
const after=before.replace('<style>','<style>'+known);
const faces=ctx.registeredFontFaces(ctx.fontFaces(before,'cjk-serif'),ctx.fontFaces(after,'cjk-serif'),[]);
assert.deepEqual(Array.from(faces),[known]);
ctx.checkpoint={managed_fonts:{'index.html':{'cjk-serif':{family:'Installed',faces}}}};
const projected=JSON.parse(ctx.authoredRead('index.html',after));
assert.equal(projected.omitted_font_faces,1);
assert.equal(projected.text,before);
assert(projected.text.includes(unknown));
assert.equal(ctx.restoreManagedFonts('index.html',projected.text),after);
assert.equal(ctx.authoredRead('unknown.html',after),after);
assert.equal(ctx.authoredRead('index.html',after.replace(known,known.replace('Installed','Different'))),
  after.replace(known,known.replace('Installed','Different')));
ctx.checkpoint={last_input_measurement:{label:'PRIVATE_SENTINEL',text_bytes:'bad'}};
const diagnostic=ctx.failureDiagnostic('COMPACTION_CONTINUATION_NOT_ALLOWED','gateway');
assert.equal(diagnostic.code,'COMPACTION_CONTINUATION_NOT_ALLOWED');
assert(!('last_input_measurement' in diagnostic));
assert(!JSON.stringify(diagnostic).includes('PRIVATE_SENTINEL'));
Object.defineProperty(ctx.checkpoint,'terminal_diagnostic',{set(){throw new Error('diagnostic denied')}});
assert.doesNotThrow(()=>ctx.rememberFailure('MODEL_REQUEST_LIMIT','gateway'));
const start=source.indexOf("      rememberFailure(e.code, 'gateway');");
const catchBody=source.slice(start,source.indexOf('\n    }\n  });',start));
ctx.atomicJSON=async()=>{throw new Error('core checkpoint denied')};
ctx.checkpointPath='synthetic';ctx.checkpoint={};
const failure=vm.runInContext('(async function(e,physical,res){'+catchBody+'})',ctx);
const response={writeHead(code){this.code=code},end(body){this.body=JSON.parse(body)}};
await failure({code:'COMPACTION_CONTINUATION_NOT_ALLOWED'},false,response);
assert.equal(response.code,502);
assert.equal(response.body.error.message,'COMPACTION_CONTINUATION_NOT_ALLOWED');
ctx.checkpoint={pending_request:{ordinal:1}};
await assert.rejects(failure({code:'SUPPLIER_RESULT_UNKNOWN'},true,response),/core checkpoint denied/);
assert.equal(ctx.checkpoint.status,'UNKNOWN');
console.log('PASS actual helpers: comments/strings, unknown fonts, exact authored roundtrip, diagnostic errors, strict UNKNOWN checkpoint');
'''
        result = subprocess.run([node, "--input-type=module", "--eval", script, str(source)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS actual helpers", result.stdout)


class ReservationDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job_id = str(uuid.uuid4())
        self.directory = self.root / self.job_id
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / "host-state/provider-reservation-diagnostic.json"
        self.diagnostic = {"phase": "reservation", "exception_type": "OperationalError",
            "sqlite_errorcode": 5, "os_errno": None, "call_id": str(uuid.uuid4()),
            "reserve_milli_cny": 2753}

    def raw_file(self, envelope, *, mode=0o600, extra_bytes=0):
        self.path.parent.mkdir(mode=0o700, exist_ok=True)
        self.path.write_bytes(json.dumps(envelope).encode() + b" " * extra_bytes)
        self.path.chmod(mode)

    def test_original_unknown_error_and_safe_diagnostic_survive_cleanup_exactly(self):
        hooks = mock.Mock()
        bridge = runtime.Bridge(job_id=self.job_id, directory=self.directory, sources=[], hooks=hooks)
        original = provider.CoverAgentProviderError("COVER_AGENT_RESERVATION_UNCONFIRMED",
            outcome_unknown=True, call_id=self.diagnostic["call_id"],
            reservation_diagnostics=self.diagnostic)
        with mock.patch.object(runtime.public_product, "assert_result_known"), \
                mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                mock.patch.object(provider, "complete", side_effect=original) as complete:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                bridge.model({"messages": [{"role": "user", "content": "synthetic reservation fixture"}]})
        self.assertIs(caught.exception, original)
        self.assertTrue(original.outcome_unknown)
        self.assertEqual(original.call_id, self.diagnostic["call_id"])
        complete.assert_called_once()
        hooks.before_call.assert_called_once()
        self.assertEqual(bridge.ordinal, 1)
        self.assertEqual(bridge.costs, [])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(runtime._read_reservation_diagnostic(self.directory, self.job_id), self.diagnostic)
        pending = {"ordinal": 11, "body_sha256": "a" * 64, "label": "primary"}
        (self.path.parent / "host-checkpoint.json").write_text(json.dumps({
            "session_id": "synthetic-session", "status": "UNKNOWN", "model_requests": 11,
            "pending_request": pending, "encrypted_content": "PRIVATE_CIPHER_SENTINEL",
            "raw_exception": "PRIVATE_SQL_SENTINEL"}))
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        self.assertFalse(self.directory.exists())
        receipt = json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())
        self.assertEqual(receipt["reservation_failure"], self.diagnostic)
        self.assertEqual((receipt["status"], receipt["model_requests"], receipt["pending_request"]),
                         ("UNKNOWN", 11, pending))
        self.assertNotIn("PRIVATE_", json.dumps(receipt))

    def test_optional_write_failure_does_not_mask_or_repeat_original_error(self):
        hooks = mock.Mock()
        bridge = runtime.Bridge(job_id=self.job_id, directory=self.directory, sources=[], hooks=hooks)
        original = provider.CoverAgentProviderError("COVER_AGENT_RESERVATION_UNCONFIRMED",
            outcome_unknown=True, call_id=self.diagnostic["call_id"],
            reservation_diagnostics=self.diagnostic)
        with mock.patch.object(runtime.public_product, "assert_result_known"), \
                mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                mock.patch.object(provider, "complete", side_effect=original) as complete, \
                mock.patch.object(runtime, "_write_reservation_diagnostic", side_effect=OSError("PRIVATE_SQL_SENTINEL")), \
                self.assertLogs(level="WARNING") as logged:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                bridge.model({"messages": [{"role": "user", "content": "synthetic reservation fixture"}]})
        self.assertIs(caught.exception, original)
        self.assertTrue(caught.exception.outcome_unknown)
        complete.assert_called_once()
        hooks.before_call.assert_called_once()
        self.assertEqual(bridge.costs, [])
        self.assertNotIn("PRIVATE_SQL_SENTINEL", " ".join(logged.output))

    def test_first_diagnostic_wins_without_overwriting_original_bytes(self):
        runtime._write_reservation_diagnostic(self.directory, self.job_id, self.diagnostic)
        original = self.path.read_bytes()
        replacement = {**self.diagnostic, "exception_type": "IntegrityError", "sqlite_errorcode": 2067,
                       "reserve_milli_cny": 1033}
        with self.assertRaises(FileExistsError):
            runtime._write_reservation_diagnostic(self.directory, self.job_id, replacement)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(runtime._read_reservation_diagnostic(self.directory, self.job_id), self.diagnostic)

    def test_reader_and_provider_projection_reject_forged_fields_and_numeric_types(self):
        bad_values = [None, [], "PRIVATE_SQL_SENTINEL",
            {**self.diagnostic, "raw_exception": "PRIVATE_SQL_SENTINEL"},
            {**self.diagnostic, "phase": "transport"},
            {**self.diagnostic, "exception_type": "PRIVATE_SQL_SENTINEL"},
            {**self.diagnostic, "exception_type": []}]
        bad_values.extend({**self.diagnostic, key: value}
                          for key in ("sqlite_errorcode", "os_errno")
                          for value in (True, 1.0, -1, 65536, "5"))
        bad_values.extend({**self.diagnostic, "reserve_milli_cny": value}
                          for value in (True, 1.0, -1, 1000000001, "2753"))
        bad_values.extend([{**self.diagnostic, "call_id": "private\nSQL"},
                           {**self.diagnostic, "call_id": ""},
                           {key: value for key, value in self.diagnostic.items() if key != "phase"}])
        for diagnostic in bad_values:
            with self.subTest(diagnostic=diagnostic):
                self.assertIsNone(provider.validated_reservation_diagnostics(diagnostic))
                self.raw_file({"job_id": self.job_id, "diagnostic": diagnostic})
                self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))

    def test_reader_rejects_wrong_envelope_or_invalid_json(self):
        for envelope in ({"job_id": str(uuid.uuid4()), "diagnostic": self.diagnostic},
                         {"job_id": self.job_id, "diagnostic": self.diagnostic, "raw": "PRIVATE_SQL"},
                         {"diagnostic": self.diagnostic}, []):
            with self.subTest(envelope=envelope):
                self.raw_file(envelope)
                self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))
        self.path.write_text("not-json PRIVATE_SQL")
        self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))

    def test_reader_rejects_symlink_hardlink_directory_and_oversize(self):
        self.raw_file({"job_id": self.job_id, "diagnostic": self.diagnostic})
        target = self.root / "synthetic-target.json"
        self.path.rename(target)
        self.path.symlink_to(target)
        self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))
        self.path.unlink()
        os.link(target, self.path)
        self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))
        self.path.unlink()
        self.path.mkdir()
        self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))
        self.path.rmdir()
        self.raw_file({"job_id": self.job_id, "diagnostic": self.diagnostic}, extra_bytes=4097)
        self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))

    def test_reader_requires_owner_and_private_mode_but_accepts_frozen_original(self):
        envelope = {"job_id": self.job_id, "diagnostic": self.diagnostic}
        self.raw_file(envelope, mode=0o400)
        self.assertEqual(runtime._read_reservation_diagnostic(self.directory, self.job_id), self.diagnostic)
        with mock.patch.object(runtime.os, "getuid", return_value=self.path.stat().st_uid + 1):
            self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))
        self.path.chmod(0o644)
        self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))

    def test_deep_bounded_json_is_discarded_without_losing_unknown_cleanup_receipt(self):
        self.path.parent.mkdir(mode=0o700)
        deep = b"[" * 1500 + b"0" + b"]" * 1500
        self.assertEqual(len(deep), 3001)
        self.path.write_bytes(deep)
        self.path.chmod(0o600)
        self.assertIsNone(runtime._read_reservation_diagnostic(self.directory, self.job_id))
        pending = {"ordinal": 11, "body_sha256": "b" * 64, "label": "primary"}
        (self.path.parent / "host-checkpoint.json").write_text(json.dumps({
            "status": "UNKNOWN", "model_requests": 11, "pending_request": pending}))
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        self.assertFalse(self.directory.exists())
        receipt = json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())
        self.assertEqual((receipt["status"], receipt["model_requests"], receipt["pending_request"]),
                         ("UNKNOWN", 11, pending))
        self.assertNotIn("reservation_failure", receipt)


class HostResultDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job_id = str(uuid.uuid4())
        self.directory = self.root / self.job_id
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / "host-state/bridge-host-result.json"
        self.event = {"type": "result", "ok": False, "status": "FAILED", "code": "ENOENT",
            "model_requests": 0, "artifact": None, "detail": "PRIVATE_PATH_SENTINEL",
            "context": {"encrypted_content": "PRIVATE_CIPHER_SENTINEL"}}

    def run_failed_bridge(self, event):
        process = mock.Mock(stdin=io.BytesIO(), stdout=io.BytesIO(json.dumps(event).encode() + b"\n"))
        bridge = runtime.Bridge(job_id=self.job_id, directory=self.directory, sources=[], hooks=mock.Mock())
        with mock.patch.object(runtime.subprocess, "Popen", return_value=process), \
                mock.patch.object(runtime, "_stop_host"), \
                mock.patch.object(runtime.public_product, "assert_result_known"), \
                mock.patch.object(provider, "complete", side_effect=AssertionError("no supplier")) as supplier:
            with self.assertRaises(cover_runtime.CoverRuntimeError) as caught:
                bridge.run("synthetic host failure", deadline=time.time() + 5)
        supplier.assert_not_called()
        self.assertEqual(caught.exception.code, "COVER_AGENT_DESIGN_INCOMPLETE")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(bridge.ordinal, 0)

    def test_actual_bridge_preserves_result_when_checkpoint_is_stale_running(self):
        self.path.parent.mkdir(mode=0o700)
        (self.path.parent / "host-checkpoint.json").write_text(json.dumps({
            "status": "RUNNING", "model_requests": 0, "pending_request": None}))
        self.run_failed_bridge(self.event)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        receipt = json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())
        self.assertEqual(receipt["status"], "RUNNING")
        self.assertEqual(receipt["host_result_failure"], {"ok": False, "status": "FAILED",
            "code": "ENOENT", "model_requests": 0, "artifact_is_dict": False})
        self.assertNotIn("PRIVATE_", json.dumps(receipt))

    def test_missing_artifact_and_optional_io_failure_keep_original_business_error(self):
        self.run_failed_bridge({**self.event, "ok": True, "status": "COMPLETE", "code": None})
        self.assertEqual(runtime._read_host_result_diagnostic(self.directory, self.job_id)["code"],
                         "RENDER_ARTIFACT_MISSING")
        before = self.path.read_bytes()
        self.run_failed_bridge(self.event)  # O_EXCL: the first actual diagnostic remains immutable.
        self.assertEqual(self.path.read_bytes(), before)
        with mock.patch.object(runtime, "_write_host_result_diagnostic", side_effect=OSError("PRIVATE_IO")):
            self.run_failed_bridge(self.event)

    def test_untrusted_result_cannot_copy_detail_or_unbounded_values(self):
        projected = runtime._host_result_diagnostic({**self.event, "code": "PRIVATE_PATH_SENTINEL"})
        self.assertEqual(projected["code"], "HOST_LOCAL_FAILURE")
        self.assertNotIn("PRIVATE_", json.dumps(projected))
        for patch in ({"ok": 1}, {"status": []}, {"model_requests": True},
                      {"model_requests": -1}, {"model_requests": 1000001}):
            self.assertIsNone(runtime._host_result_diagnostic({**self.event, **patch}))

    def test_reader_rejects_malicious_state_and_cleanup_still_finishes(self):
        runtime._write_host_result_diagnostic(self.directory, self.job_id, self.event)
        original = self.path.read_bytes()
        self.path.chmod(0o644)
        self.assertIsNone(runtime._read_host_result_diagnostic(self.directory, self.job_id))
        self.path.chmod(0o600)
        alias = self.root / "alias"
        os.link(self.path, alias)
        self.assertIsNone(runtime._read_host_result_diagnostic(self.directory, self.job_id))
        alias.unlink()
        self.path.unlink()
        alias.write_bytes(original)
        self.path.symlink_to(alias)
        self.assertIsNone(runtime._read_host_result_diagnostic(self.directory, self.job_id))
        self.path.unlink()
        self.path.write_bytes(b"[" * 1500 + b"0" + b"]" * 1500)
        self.path.chmod(0o600)
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        self.assertFalse(self.directory.exists())
        self.assertFalse((self.root / "receipts" / (self.job_id + ".json")).exists())


class SeedreamDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job_id = str(uuid.uuid4())
        self.directory = self.root / self.job_id
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / "host-state/seedream-http-failure.json"
        self.diagnostic = {"http_status": 400, "body_kind": "json_error",
            "provider_code": "InvalidParameter", "parameter": "size",
            "provider_request_id": "synthetic-image-request", "response_hash": "a" * 64}

    def bridge(self, **kwargs):
        payload = synthetic_png((200, 200), "#557788")
        source = {"payload": payload, "sha256": hashlib.sha256(payload).hexdigest()}
        bridge = runtime.Bridge(job_id=self.job_id, directory=self.directory,
            sources=[source], hooks=mock.Mock(), **kwargs)
        bridge.seen_images.add(source["sha256"])
        return bridge

    def cleanup_receipt(self):
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        self.assertFalse(self.directory.exists())
        return json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())

    def test_actual_image_adapter_failure_survives_bridge_cleanup_without_raw_response(self):
        requests = []
        def transport(request):
            requests.append(request)
            return httpx.Response(400, json={"error": {"code": "InvalidParameter", "param": "size",
                "message": "PRIVATE_PROMPT_TOKEN_PATH", "innererror": "PRIVATE_INTERNAL"}},
                headers={"x-request-id": "synthetic-image-request"})
        bridge = self.bridge(image_transport=httpx.MockTransport(transport))
        with mock.patch.object(runtime.ark_media, "_headers", return_value={}), \
                mock.patch.object(runtime.public_product, "assert_result_known"), \
                mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                mock.patch.object(runtime.public_product, "_reserve_payload"), \
                mock.patch.object(runtime.public_product, "mark_model_dispatched"), \
                mock.patch.object(runtime.public_product, "_record_response") as terminal:
            with self.assertRaises(runtime.cover_seedream.SeedreamError) as caught:
                bridge.tool({"name": "cover_seedream", "arguments": {"prompt": "synthetic concept"}})
        self.assertEqual(len(requests), 1)
        self.assertEqual(caught.exception.code, "COVER_SEEDREAM_HTTP_400")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(caught.exception.call_id, cover_runtime.physical_call_id(self.job_id, "image"))
        terminal.assert_called_once_with(caught.exception.call_id, 400)
        record = bridge.hooks.on_call.call_args.args[0]
        self.assertIsNone(record["actual_cost"])
        self.assertIsNone(record["billed_images"])
        self.assertEqual(record["status"], "failed")
        self.assertEqual(bridge.costs, [])
        self.assertIsNone(bridge.concept_hash)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        diagnostic = caught.exception.response_diagnostics
        receipt = self.cleanup_receipt()
        self.assertEqual(receipt["seedream_http_failure"], diagnostic)
        self.assertNotIn("PRIVATE_", json.dumps(receipt))

    def test_optional_write_failure_preserves_original_exception_and_never_repeats(self):
        bridge = self.bridge()
        original = runtime.cover_seedream.SeedreamError("COVER_SEEDREAM_HTTP_400",
            call_id=cover_runtime.physical_call_id(self.job_id, "image"),
            response_diagnostics=self.diagnostic)
        with mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=original) as generate, \
                mock.patch.object(runtime, "_write_seedream_diagnostic", side_effect=OSError("PRIVATE_IO")), \
                self.assertLogs(level="WARNING") as logs:
            with self.assertRaises(runtime.cover_seedream.SeedreamError) as caught:
                bridge.tool({"name": "cover_seedream", "arguments": {"prompt": "synthetic concept"}})
        self.assertIs(caught.exception, original)
        generate.assert_called_once()
        self.assertIn("cover_seedream_diagnostic_unavailable", logs.output[0])
        self.assertNotIn("PRIVATE_", "".join(logs.output))
        self.assertFalse(self.path.exists())

    def test_first_diagnostic_is_immutable_and_does_not_rewrite_original_host_unknown(self):
        runtime._write_seedream_diagnostic(self.directory, self.job_id, self.diagnostic)
        first = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            runtime._write_seedream_diagnostic(self.directory, self.job_id,
                {**self.diagnostic, "provider_code": "OTHER"})
        self.assertEqual(first, self.path.read_bytes())
        (self.path.parent / "host-checkpoint.json").write_text(json.dumps({
            "status": "UNKNOWN", "model_requests": 4, "pending_request": None}))
        receipt = self.cleanup_receipt()
        self.assertEqual((receipt["status"], receipt["model_requests"]), ("UNKNOWN", 4))
        self.assertEqual(receipt["seedream_http_failure"], self.diagnostic)

    def test_reader_rejects_untrusted_files_and_cleanup_can_discard_deep_json(self):
        runtime._write_seedream_diagnostic(self.directory, self.job_id, self.diagnostic)
        original = self.path.read_bytes()
        self.path.chmod(0o644)
        self.assertIsNone(runtime._read_seedream_diagnostic(self.directory, self.job_id))
        self.path.chmod(0o600)
        alias = self.root / "alias"
        os.link(self.path, alias)
        self.assertIsNone(runtime._read_seedream_diagnostic(self.directory, self.job_id))
        alias.unlink()
        self.path.unlink()
        alias.write_bytes(original)
        self.path.symlink_to(alias)
        self.assertIsNone(runtime._read_seedream_diagnostic(self.directory, self.job_id))
        self.path.unlink()
        for invalid in ({"job_id": str(uuid.uuid4()), "diagnostic": self.diagnostic},
                        {"job_id": self.job_id, "diagnostic": {**self.diagnostic, "message": "PRIVATE"}},
                        {"job_id": self.job_id, "diagnostic": {**self.diagnostic, "provider_code": "PRIVATE"}}):
            self.path.write_text(json.dumps(invalid)); self.path.chmod(0o600)
            self.assertIsNone(runtime._read_seedream_diagnostic(self.directory, self.job_id))
        self.path.write_bytes(b" " * 4097)
        self.assertIsNone(runtime._read_seedream_diagnostic(self.directory, self.job_id))
        self.path.write_bytes(b"[" * 1500 + b"0" + b"]" * 1500)
        (self.path.parent / "host-checkpoint.json").write_text(json.dumps({
            "status": "UNKNOWN", "model_requests": 4, "pending_request": None}))
        receipt = self.cleanup_receipt()
        self.assertEqual(receipt["status"], "UNKNOWN")
        self.assertNotIn("seedream_http_failure", receipt)


class InputRejectionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.job_id = str(uuid.uuid4())
        self.directory = self.root / self.job_id
        self.directory.mkdir(mode=0o700)
        self.hooks = mock.Mock()
        self.http_requests = []
        self.bridge = runtime.Bridge(job_id=self.job_id, directory=self.directory, sources=[], hooks=self.hooks,
            model_transport=httpx.MockTransport(lambda request: self.http_requests.append(request)))

    def oversized(self):
        return {"messages": [{"role": "user", "content": "PRIVATE_REPORT_SENTINEL_" + "a" * provider.MAX_INPUT_TOKENS}]}

    def test_real_model_rejection_is_before_ordinal_hooks_http_and_survives_cleanup(self):
        with mock.patch.object(provider, "complete", wraps=provider.complete) as complete:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                self.bridge.model(self.oversized())
        complete.assert_not_called()
        self.hooks.before_call.assert_not_called()
        self.assertEqual(self.bridge.ordinal, 0)
        self.assertFalse(self.http_requests)
        path = self.directory / "host-state/provider-input-limit.json"
        raw = path.read_text()
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("PRIVATE_REPORT_SENTINEL", raw)
        self.assertEqual(json.loads(raw)["measurement"], caught.exception.input_diagnostics)
        (self.directory / "host-state/host-checkpoint.json").write_text(json.dumps({
            "session_id": "offline-session", "status": "AWAITING_MODEL", "model_requests": 1,
            "pending_request": {"ordinal": 1, "body_sha256": "a" * 64, "label": "primary"}}))
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        self.assertFalse(self.directory.exists())
        receipt = json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())
        self.assertEqual(receipt["status"], "AWAITING_MODEL")  # Not a supplier UNKNOWN claim.
        self.assertEqual(receipt["input_rejection"], {"code": "COVER_AGENT_INPUT_LIMIT_EXCEEDED",
            "measurement": caught.exception.input_diagnostics})
        self.assertNotIn("PRIVATE_REPORT_SENTINEL", json.dumps(receipt))

    def test_diagnostic_write_failure_never_masks_original_rejection(self):
        with mock.patch.object(runtime, "_write_input_diagnostic", side_effect=OSError("PRIVATE_ERROR_SENTINEL")), \
                self.assertLogs(level="WARNING") as logged:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                self.bridge.model(self.oversized())
        self.assertEqual(caught.exception.code, "COVER_AGENT_INPUT_LIMIT_EXCEEDED")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertNotIn("PRIVATE_ERROR_SENTINEL", " ".join(logged.output))
        self.hooks.before_call.assert_not_called()
        self.assertFalse(self.http_requests)

    def test_terminal_reason_survives_cleanup_without_replacing_first_input_measurement(self):
        first = self.bridge.preflight(self.oversized())["measurement"]
        latest = {**first, "text_bytes": first["text_bytes"] + 10, "total_bound": first["total_bound"] + 10}
        diagnostic = {"code": "COMPACTION_CONTINUATION_NOT_ALLOWED", "stage": "gateway",
            "model_requests": 14, "compaction_requests": 1, "local_input_rejections": 2,
            "last_input_label": "primary", "last_input_measurement": latest}
        (self.directory / "host-state/host-checkpoint.json").write_text(json.dumps({
            "status": "FAILED", "model_requests": 14, "pending_request": None,
            "terminal_diagnostic": diagnostic, "managed_fonts": {"PRIVATE_SENTINEL": "private"},
            "error": "PRIVATE_SENTINEL"}))
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        receipt = json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())
        self.assertEqual(receipt["terminal_diagnostic"], diagnostic)
        self.assertEqual(receipt["input_rejection"]["measurement"], first)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(receipt))
        self.assertFalse(self.directory.exists())
        self.hooks.before_call.assert_not_called()
        self.assertFalse(self.http_requests)

    def test_terminal_diagnostic_rejects_arbitrary_error_payloads_and_invalid_types(self):
        valid = {"code": "SDK_IDLE_FAILED", "stage": "sdk_idle", "model_requests": 1,
            "compaction_requests": 0, "local_input_rejections": 0}
        self.assertEqual(runtime._host_failure_diagnostic(valid), valid)
        for bad in ({**valid, "code": "PRIVATE_REPORT_SENTINEL"}, {**valid, "code": []},
                    {**valid, "stage": []}, {**valid, "model_requests": True},
                    {**valid, "raw_message": "PRIVATE_REPORT_SENTINEL"},
                    {**valid, "last_input_label": "primary"}):
            with self.subTest(bad=bad):
                self.assertIsNone(runtime._host_failure_diagnostic(bad))

    def test_preflight_recovers_only_local_input_overflow_without_mutating_failure(self):
        invocation = runtime.public_product.Invocation("offline-owner", self.job_id, route="/covers",
            budget_id="noteai-xhs-cover-20261019-acceptance")
        marker = runtime.public_product._invocation.set(invocation)
        try:
            with mock.patch.object(provider, "complete", wraps=provider.complete) as complete:
                decision = self.bridge.preflight(self.oversized())
                self.assertFalse(decision["allowed"])
                self.assertEqual(decision["code"], "COVER_AGENT_INPUT_LIMIT_EXCEEDED")
                self.assertGreater(decision["measurement"]["total_bound"], provider.MAX_INPUT_TOKENS)
                self.assertEqual(invocation.failure, "")
                self.assertEqual(self.bridge.preflight({"messages": [{"role": "user", "content": "small"}]}),
                    {"allowed": True})
                complete.assert_not_called()
            self.hooks.before_call.assert_not_called()
            self.assertEqual(self.bridge.ordinal, 0)
            self.assertFalse(self.http_requests)
            with self.assertRaisesRegex(provider.CoverAgentProviderError, "MODEL_OR_STREAM"):
                self.bridge.preflight({"messages": [{"role": "user", "content": "small"}], "stream": True})
            self.assertEqual(invocation.failure, "COVER_AGENT_MODEL_OR_STREAM_INVALID")
            invocation.failure = "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY"
            with self.assertRaisesRegex(runtime.public_product.TrialProviderStopped, "UNKNOWN_NO_REPLAY"):
                self.bridge.preflight(self.oversized())
            self.assertEqual(invocation.failure, "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY")
        finally:
            runtime.public_product._invocation.reset(marker)

    def test_preflight_stdio_decision_uses_original_id_without_provider_dispatch(self):
        class InputLog(io.BytesIO):
            def close(self):
                self.captured = self.getvalue()
                super().close()

        process = mock.Mock()
        process.stdin = InputLog()
        process.stdout = io.BytesIO((json.dumps({"type": "model_preflight", "id": "offline-preflight",
            "method": "POST", "path": "/chat/completions", "body": self.oversized()}) + "\n"
            + json.dumps({"type": "result", "ok": True, "artifact": {}}) + "\n").encode())
        with mock.patch.object(runtime.subprocess, "Popen", return_value=process), \
                mock.patch.object(runtime, "_stop_host"), mock.patch.object(provider, "complete") as complete:
            self.bridge.run("synthetic protocol only", deadline=time.time() + 2)
        frames = [json.loads(line) for line in process.stdin.captured.splitlines()]
        self.assertEqual((frames[0]["output_tokens"], frames[0]["context_tokens"], frames[0]["compaction_output_tokens"]),
            (65536, 262144, 8192))
        decision = frames[-1]
        self.assertEqual((decision["type"], decision["id"], decision["allowed"]),
            ("model_preflight_response", "offline-preflight", False))
        self.assertEqual(decision["code"], "COVER_AGENT_INPUT_LIMIT_EXCEEDED")
        complete.assert_not_called()
        self.hooks.before_call.assert_not_called()
        self.assertEqual(self.bridge.ordinal, 0)
        self.assertFalse(self.http_requests)

    def test_cleanup_discards_untrusted_diagnostic_fields(self):
        measurement = provider.admit_payload(self.oversized())["measurement"]
        runtime._write_input_diagnostic(self.directory, self.job_id, measurement)
        path = self.directory / "host-state/provider-input-limit.json"
        forged = json.loads(path.read_text())
        forged["measurement"]["raw_request"] = "PRIVATE_FORGED_PAYLOAD"
        path.write_text(json.dumps(forged))
        (self.directory / "host-state/host-checkpoint.json").write_text(json.dumps({
            "status": "FAILED", "session_id": "offline-session"}))
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        raw = (self.root / "receipts" / (self.job_id + ".json")).read_text()
        self.assertNotIn("PRIVATE_FORGED_PAYLOAD", raw)
        self.assertNotIn("input_rejection", json.loads(raw))

    def test_known_output_limit_diagnostic_survives_cleanup_without_private_payload(self):
        diagnostic = {"finish_reason": "length", "completion_tokens": 8192,
                      "max_completion_tokens": 8192, "reasoning_tokens": 7000}
        original = provider.CoverAgentProviderError("COVER_AGENT_OUTPUT_LIMIT_REACHED", output_diagnostics=diagnostic)
        with mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                mock.patch.object(provider, "complete", side_effect=original) as complete:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                self.bridge.model({"messages": [{"role": "user", "content": "PRIVATE_FACT_CIPHER_SENTINEL"}],
                                   "max_completion_tokens": 8192})
        self.assertIs(caught.exception, original)
        complete.assert_called_once()
        self.assertEqual(self.bridge.ordinal, 1)
        path = self.directory / "host-state/provider-output-diagnostic.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("PRIVATE", path.read_text())
        self.assertEqual(runtime._read_output_diagnostic(self.directory, self.job_id), diagnostic)
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        receipt = json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())
        self.assertEqual(receipt["status"], "OUTPUT_REJECTED_AFTER_KNOWN_RESPONSE")
        self.assertEqual(receipt["output_rejection"], diagnostic)
        self.assertFalse(self.directory.exists())

    def test_output_diagnostic_failure_never_masks_known_original_error(self):
        diagnostic = {"finish_reason": "other", "completion_tokens": 30,
                      "max_completion_tokens": 8192, "reasoning_tokens": None}
        original = provider.CoverAgentProviderError("COVER_AGENT_OUTPUT_INCOMPLETE", output_diagnostics=diagnostic)
        with mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                mock.patch.object(provider, "complete", side_effect=original), \
                mock.patch.object(runtime, "_write_output_diagnostic", side_effect=OSError("PRIVATE_FAILURE")), \
                self.assertLogs(level="WARNING") as logged:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                self.bridge.model({"messages": [{"role": "user", "content": "synthetic"}]})
        self.assertIs(caught.exception, original)
        self.assertFalse(original.outcome_unknown)
        self.assertNotIn("PRIVATE_FAILURE", " ".join(logged.output))

    def test_cleanup_discards_forged_output_diagnostic_and_preserves_original_unknown(self):
        diagnostic = {"finish_reason": "length", "completion_tokens": 30,
                      "max_completion_tokens": 8192, "reasoning_tokens": None}
        runtime._write_output_diagnostic(self.directory, self.job_id, diagnostic)
        path = self.directory / "host-state/provider-output-diagnostic.json"
        forged = json.loads(path.read_text())
        forged["diagnostic"]["encrypted_content"] = "PRIVATE_CIPHER"
        path.write_text(json.dumps(forged))
        (self.directory / "host-state/host-checkpoint.json").write_text(json.dumps({
            "status": "UNKNOWN", "pending_request": {"ordinal": 1, "body_sha256": "a" * 64, "label": "primary"}}))
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        raw = (self.root / "receipts" / (self.job_id + ".json")).read_text()
        self.assertNotIn("PRIVATE_CIPHER", raw)
        self.assertNotIn("output_rejection", json.loads(raw))
        self.assertEqual(json.loads(raw)["status"], "UNKNOWN")

    def test_thinking_restore_failure_is_before_meter_ordinal_and_http(self):
        original = runtime.ThinkingError("COVER_AGENT_THINKING_CONTEXT_MISMATCH")
        body = {"messages": [{"role": "user", "content": "synthetic"}]}
        for method in (self.bridge.preflight, self.bridge.model):
            with self.subTest(method=method.__name__), \
                    mock.patch.object(self.bridge.thinking, "restore", side_effect=original), \
                    mock.patch.object(provider, "prepare_payload") as prepare, \
                    mock.patch.object(provider, "admit_payload") as admit:
                with self.assertRaisesRegex(cover_runtime.CoverRuntimeError,
                        "COVER_AGENT_THINKING_CONTEXT_MISMATCH"):
                    method(body)
                prepare.assert_not_called()
                admit.assert_not_called()
        self.assertEqual(self.bridge.ordinal, 0)
        self.hooks.before_call.assert_not_called()
        self.assertFalse(self.http_requests)

    def test_nonhelper_failure_after_response_is_not_hidden_or_retried(self):
        original = RuntimeError("synthetic helper implementation failure")
        with mock.patch.object(runtime.public_product, "model_admission_sync", return_value=contextlib.nullcontext()), \
                mock.patch.object(provider, "complete", return_value={"choices": []}) as complete, \
                mock.patch.object(self.bridge.thinking, "remember", side_effect=original):
            with self.assertRaises(RuntimeError) as caught:
                self.bridge.model({"messages": [{"role": "user", "content": "synthetic"}]})
        self.assertIs(caught.exception, original)
        complete.assert_called_once()
        self.assertEqual(self.bridge.ordinal, 1)
        self.assertEqual(len(self.bridge.costs), 1)
        self.assertFalse(self.http_requests)

    def test_unknown_precedes_thinking_restore_and_nonhelper_failures_are_not_hidden(self):
        invocation = runtime.public_product.Invocation("offline-owner", self.job_id, route="/covers",
            budget_id="noteai-xhs-cover-20261019-acceptance")
        marker = runtime.public_product._invocation.set(invocation)
        body = {"messages": [{"role": "user", "content": "synthetic"}]}
        try:
            invocation.failure = "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY"
            with mock.patch.object(self.bridge.thinking, "restore") as restore:
                for method in (self.bridge.preflight, self.bridge.model):
                    with self.assertRaisesRegex(runtime.public_product.TrialProviderStopped, "UNKNOWN_NO_REPLAY"):
                        method(body)
                restore.assert_not_called()
            self.assertEqual(invocation.failure, "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY")
        finally:
            runtime.public_product._invocation.reset(marker)
        original = RuntimeError("synthetic helper implementation failure")
        with mock.patch.object(self.bridge.thinking, "restore", side_effect=original):
            for method in (self.bridge.preflight, self.bridge.model):
                with self.assertRaises(RuntimeError) as caught:
                    method(body)
                self.assertIs(caught.exception, original)
        self.assertEqual(self.bridge.ordinal, 0)
        self.hooks.before_call.assert_not_called()
        self.assertFalse(self.http_requests)


@unittest.skipUnless(os.name == "posix", "POSIX owned process groups")
class OwnedHostCleanupTests(unittest.TestCase):
    def test_permission_error_is_not_ignored_for_an_extant_group(self):
        process = mock.Mock(pid=12345)
        process.poll.return_value = 0
        denied = PermissionError("controlled signal denial")
        with mock.patch.object(runtime.os, "killpg", side_effect=[denied, None]) as kill:
            with self.assertRaises(PermissionError) as raised:
                runtime._stop_host(process)
        self.assertIs(raised.exception, denied)
        self.assertEqual(kill.call_args_list, [mock.call(process.pid, signal.SIGTERM), mock.call(process.pid, 0)])

    def test_deadline_and_completed_host_stop_owned_descendants(self):
        original_popen = subprocess.Popen
        original_stop = runtime._stop_host

        def executing(pid):
            result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                capture_output=True, text=True, check=False)
            return bool(result.stdout.strip() and not result.stdout.strip().startswith("Z"))

        for mode, cleanup_error in (("deadline", False), ("complete", False),
                                    ("deadline", True), ("complete", True)):
            with self.subTest(mode=mode, cleanup_error=cleanup_error), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                child_info = root / "child.json"
                child = root / "child.py"
                child.write_text("import os,signal,time\n"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                    "time.sleep(20)\n")
                host = root / "host.py"
                host.write_text("import json,os,signal,subprocess,sys,time\n"
                    "json.loads(sys.stdin.readline())\n"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                    "p=subprocess.Popen([sys.executable,sys.argv[1]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                    "open(sys.argv[2],'w').write(json.dumps({'pid':p.pid,'pgid':os.getpgid(p.pid)}))\n"
                    "if sys.argv[3]=='complete':\n"
                    " print(json.dumps({'type':'result','ok':True,'artifact':{}}),flush=True)\n"
                    "else: time.sleep(20)\n")
                processes = []
                sentinel = original_popen([sys.executable, "-c", "import time;time.sleep(20)"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)

                def redirect(command, **kwargs):
                    self.assertEqual(Path(command[1]), runtime.ROOT / "cover_agent_host/worker.mjs")
                    self.assertIs(kwargs["start_new_session"], True)
                    process = original_popen([sys.executable, str(host), str(child), str(child_info), mode], **kwargs)
                    processes.append(process)
                    return process

                def stop(process):
                    original_stop(process)
                    if cleanup_error:
                        raise PermissionError("Controlled cleanup failure after fixture teardown")

                try:
                    bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=root, sources=[], hooks=None)
                    with mock.patch.object(runtime.subprocess, "Popen", side_effect=redirect), \
                            mock.patch.object(runtime, "_stop_host", side_effect=stop):
                        if mode == "deadline":
                            with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_TASK_DEADLINE") as raised:
                                bridge.run("Local cleanup fixture", deadline=time.time() + .4)
                            if cleanup_error:
                                self.assertIn("COVER_HOST_CLEANUP_FAILED: PermissionError", raised.exception.__notes__)
                        elif cleanup_error:
                            with self.assertRaises(PermissionError):
                                bridge.run("Local cleanup fixture", deadline=time.time() + 2)
                        else:
                            self.assertTrue(bridge.run("Local cleanup fixture", deadline=time.time() + 2)["ok"])
                    self.assertEqual(len(processes), 1)
                    process = processes[0]
                    info = json.loads(child_info.read_text())
                    self.assertEqual(info["pgid"], process.pid)
                    end = time.monotonic() + 1
                    while executing(info["pid"]) and time.monotonic() < end:
                        time.sleep(.01)
                    self.assertFalse(executing(info["pid"]))
                    self.assertIsNotNone(process.returncode)
                    self.assertTrue(process.stdin.closed)
                    self.assertTrue(process.stdout.closed)
                    self.assertIsNone(sentinel.poll(), "Cleanup must not signal another host's group")
                finally:
                    if child_info.exists():
                        pid = json.loads(child_info.read_text())["pid"]
                        if executing(pid):
                            os.kill(pid, signal.SIGKILL)
                    for process in processes:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=3)
                    sentinel.kill()
                    sentinel.wait(timeout=3)


class ScriptedBridge(runtime.Bridge):
    instances = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.requests, self.host_results = [], []
        self.design_turn = 0
        self.instances.append(self)

    def run(self, prompt, *, deadline):
        result = super().run(prompt, deadline=min(deadline, time.time() + 150))
        self.host_results.append(result)
        return result

    def model(self, payload, stage="design"):
        # Keep the production Ark payload contract in the test. Only the
        # physical provider/ledger is replaced, not SDK messages or tools.
        prepared, bound = provider.prepare_payload(self._restore_thinking(payload))
        self.ordinal += 1
        call_id = str(uuid.uuid5(uuid.UUID(self.job_id), "offline:" + str(self.ordinal)))
        hashes = runtime._images_in(prepared)
        self.seen_images.update(hashes)
        self.requests.append({"stage": stage, "input_bound": bound, "body": prepared,
            "image_sha256": sorted(hashes), "call_id": call_id})
        if stage == "qc":
            parts = prepared["messages"][0]["content"]
            images = [base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
                for part in parts if part.get("type") == "image_url"]
            if len(images) != 3 or images[0] != self.sources[0]["payload"]:
                raise AssertionError("QC lacks actual original/final/thumbnail inputs")
            with Image.open(io.BytesIO(images[1])) as final, Image.open(io.BytesIO(images[2])) as thumb:
                if final.size != (1776, 2368) or thumb.size != (240, 320):
                    raise AssertionError("QC actual final/thumbnail dimensions invalid")
            qc = {"approved": True, "text_matches": True, "facts_preserved": True,
                "subject_preserved": True, "issues": [], "local_adjustment": None,
                "design_checks": {key: True for key in ("main_visual", "message_focus",
                    "typographic_hierarchy", "layout_balance", "thumbnail_legibility", "style_fits_subject")}}
            return self.response(json.dumps(qc)), call_id

        self.design_turn += 1
        turn = self.design_turn
        if turn == 1:
            serialized = json.dumps(prepared, ensure_ascii=False)
            if "Create an art-directed composition reference" not in serialized or "## Read the render" not in serialized:
                raise AssertionError("Complete Skill was not activated")
            calls = [("cover_seedream", {"prompt": "Offline synthetic technical concept only. Preserve source identity. Full 3:4 poster composition with exact Chinese title, no new merchant facts."})]
        elif turn == 2:
            # Follow the tool's actual path; do not hide an absolute/relative
            # integration defect by rewriting it in the test.
            concept = returned_value(prepared, "role")
            calls = [("cover_view", {"path": concept["path"]})]
        elif turn == 3:
            if self.concept_hash not in self.seen_images:
                raise AssertionError("Concept byte identity was lost before design planning")
            source = self.sources[0]
            html = self.html(source["path"])
            calls = [("cover_write", {"path": "index.html", "text": html}),
                ("cover_write", {"path": "poster.json", "text": json.dumps({"canvas": {"width": 1776, "height": 2368}, "scale": 1, "dpi": None})}),
                ("cover_write", {"path": "brief.md", "text": "Synthetic integration fixture: exact retained source and live Chinese text."}),
                ("cover_write", {"path": "design-plan.md", "text": "Written only after the actual concept image reached the model. Synthetic technical fixture, not merchant aesthetic acceptance."})]
        elif turn == 4:
            calls = [("cover_check", {"action": "font_add", "html": "index.html", "font_id": "cjk-sans"})]
        elif turn == 5:
            source = self.sources[0]
            calls = [("cover_check", {"action": "contract", "html": "index.html"}),
                ("cover_render", {"request": {"project_dir": ".",
                "sources": [{"ref": source["media_ref"], "path": source["path"], "sha256": source["sha256"]}],
                "text_layers": [{"id": "title", "allowed_rect": {"x": 90, "y": 100, "width": 1600, "height": 350}}],
                "protected_regions": [{"x": 500, "y": 800, "width": 700, "height": 800}]}})]
        elif turn == 6:
            contract = returned_value(prepared, "code", tool_call_id="fixture_5_0")
            if contract["code"] != 0 or json.loads(contract.get("stdout") or "{}").get("pass") is not True:
                raise AssertionError("Actual SDK contract check did not pass: " + json.dumps(contract))
            rendered = returned_value(prepared, "png_path", tool_call_id="fixture_5_1")
            self.rendered_tool = rendered
            calls = [("cover_view", {"path": rendered.get("image_path", rendered["png_path"])})]
        elif turn == 7:
            # A declared preview path is insufficient. Check the full-size PNG
            # and actual thumbnail bytes in the subsequent real SDK request.
            if self.rendered_tool["png_sha256"] not in hashes or self.rendered_tool["thumbnail_sha256"] not in hashes:
                raise AssertionError("SDK omitted actual final or thumbnail pixels")
            thumbnail = self.directory / self.rendered_tool["thumbnail_path"]
            with Image.open(thumbnail) as image:
                if image.size != (240, 320):
                    raise AssertionError("Design review thumbnail dimensions invalid")
            return self.response("Synthetic local SDK and renderer workflow complete."), call_id
        else:
            raise AssertionError("Unexpected extra model continuation: " + str(turn))
        return self.response(None, calls), call_id

    def response(self, text, calls=None):
        message = {"role": "assistant", "content": text,
            "encrypted_content": "TEST_OPAQUE_COVER_runtime_" + str(self.ordinal)}
        if calls:
            message["tool_calls"] = [{"id": "fixture_" + str(self.ordinal) + "_" + str(i),
                "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                for i, (name, args) in enumerate(calls)]
        body = {"id": "chatcmpl-offline-runtime", "object": "chat.completion", "created": 1,
            "model": provider.MODEL, "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
        return self.thinking.remember(body)

    @staticmethod
    def html(source_path):
        return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>合成技术夹具</title><style>
:root {--ink:#203a34;--paper:#f6f2e9;--font-title:"Noto Sans SC Variable",sans-serif}
* {box-sizing:border-box} html,body {margin:0;padding:0} .poster {position:relative;width:1776px;height:2368px;overflow:hidden;background:var(--paper)}
.photo {position:absolute;left:120px;top:520px;width:1536px;height:1440px;object-fit:contain}
.title {position:absolute;left:120px;top:150px;width:1480px;height:260px;margin:0;font-family:var(--font-title);font-size:96px;line-height:1.18;font-weight:600;color:var(--ink);white-space:pre-wrap}
</style></head><body><main class="poster" data-canvas-width="1776" data-canvas-height="2368"><img class="photo" data-layer-id="source" src="''' + source_path + '''" alt="synthetic source"><h1 class="title hf-slot" data-layer-id="title">原照独立图层\n中文排字测试</h1></main></body></html>'''


class CoverAgentRuntimeSDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") or not shutil.which("node"):
            raise unittest.SkipTest("Explicit approved task-local SDK and Node required")
        cls.root = Path(tempfile.mkdtemp(prefix="noteai-cover-runtime-proof-"))

    @classmethod
    def tearDownClass(cls):
        destination = os.environ.get("NOTEAI_COVER_RUNTIME_PROOF_OUTPUT")
        if destination:
            target = Path(destination) / cls.root.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(cls.root, target, symlinks=True)
        print("COVER_AGENT_RUNTIME_PROOF=" + str(cls.root))

    def test_real_sdk_controlled_tools_renderer_photo_qc_and_source_bundle(self):
        original = synthetic_png((2400, 1800), "#5A7F75")
        concept = synthetic_png((1776, 2368), "#A1A8B1")
        source = {"media_ref": str(uuid.uuid4()), "payload": original,
            "sha256": hashlib.sha256(original).hexdigest()}
        records, stages = [], []
        hooks = cover_runtime.RuntimeHooks(lambda *_args: None, records.append, stages.append)
        ScriptedBridge.instances = []

        def fake_image(**kwargs):
            self.assertEqual(kwargs["source_images"], [original])
            record = {"stage": "image", "status": "responded", "provider": "synthetic-fixture", "call_id": kwargs["call_id"]}
            kwargs["before_call"]("image", kwargs["call_id"], {})
            kwargs["on_call"](record)
            return concept, record

        original_html = ScriptedBridge.html

        def offset_canvas(source_path):
            # A viewport screenshot would include this margin and truncate the
            # tall canvas. The delivered image must be the checked canvas.
            return original_html(source_path).replace("html,body {margin:0;padding:0}",
                "html,body {margin:0;padding:0} body {margin:17px;background:#ff00ff}")

        try:
            with mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": str(self.root / "jobs")}), mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=fake_image) as image, mock.patch.object(ScriptedBridge, "html", side_effect=offset_canvas):
                result = runtime.run_cover(job_id=str(uuid.uuid4()), user_id="offline-owner",
                    report={"title": "原照独立图层中文排字测试", "body": "合成技术图验证，非商家样本。", "title_variants": []},
                    sources=[source], hooks=hooks, bridge_class=ScriptedBridge)
            bridge = ScriptedBridge.instances[-1]
            self.assertNotIn("TEST_OPAQUE_COVER_runtime_", json.dumps(bridge.host_results))
            self.assertEqual(image.call_count, 1)
            self.assertEqual(bridge.design_turn, 7)
            self.assertEqual(sum(r["stage"] == "qc" for r in bridge.requests), 1)
            self.assertIn(source["sha256"], bridge.requests[0]["image_sha256"])
            self.assertIn(artifacts.digest(concept), bridge.requests[2]["image_sha256"])
            self.assertEqual(result.layout["final_sha256"], artifacts.digest(result.final_bytes))
            self.assertEqual(result.qc["source_hashes"], {source["media_ref"]: source["sha256"]})
            bundle = result.artifact["editable_bundle"]
            restored = artifacts.restore(bundle, self.root / "restored")
            self.assertEqual((restored / "assets/source-1.png").read_bytes(), original)
            self.assertEqual((restored / "reference/composition-reference.png").read_bytes(), concept)
            self.assertIn("Written only after", (restored / "design-plan.md").read_text())
            self.assertEqual(result.layout["qc_status"], "INITIAL_VISUAL_QC_PASSED")
            old_png = (restored / "out/poster.png").read_bytes()
            manifest = json.loads((restored / "render-manifest.json").read_bytes())
            capture = manifest["checks"]["screenshot"]
            self.assertEqual((capture["renderer"], capture["operation"]),
                ("editable_design_browser", "page.screenshot"))
            self.assertEqual(capture["device_scale_factor"], 1)
            self.assertEqual((capture["canvas_clip"]["x"], capture["canvas_clip"]["y"]), (17, 17))
            with Image.open(io.BytesIO(old_png)) as image:
                delivered = image.convert("RGB")
            self.assertEqual(delivered.size, (1776, 2368))
            self.assertEqual(delivered.getpixel((0, 0)), (246, 242, 233))
            self.assertEqual(delivered.getpixel((140, 700)), (90, 127, 117))
            self.assertEqual(delivered.getpixel((888, 1240)), (203, 174, 112))
            self.assertEqual(delivered.getpixel((888, 600)), (246, 242, 233))
            title = delivered.crop((90, 100, 1690, 450))
            self.assertGreater(sum(max(pixel) < 100 for pixel in title.getdata()), 1000)
            edited = artifacts.cli("edit", {"schema_version": artifacts.SCHEMA,
                "output_root": str(self.root / "free-edit-revisions"),
                "parent_revision_dir": str(restored),
                "expected_parent_manifest_sha256": result.layout["manifest_sha256"],
                "initial_qc_ref": result.layout["initial_qc_ref"],
                "edits": [{"layer_id": "title", "text": "原照独立\n图层中文排字测试", "dx": 12, "dy": 8}]})
            adjusted_png, _, adjusted_layout = artifacts.capture(edited,
                expected_sources=result.layout["input_source_hashes"])
            self.assertNotEqual(adjusted_png, old_png)
            with Image.open(io.BytesIO(adjusted_png)) as image:
                adjusted = image.convert("RGB")
            difference = ImageChops.difference(delivered, adjusted).getbbox()
            self.assertIsNotNone(difference)
            self.assertTrue(difference[0] >= 90 and difference[1] >= 100
                and difference[2] <= 1690 and difference[3] <= 450, difference)
            self.assertIsNone(ImageChops.difference(delivered.crop((0, 500, 1776, 2368)),
                adjusted.crop((0, 500, 1776, 2368))).getbbox())
            self.assertEqual((restored / "out/poster.png").read_bytes(), old_png)
            self.assertEqual(adjusted_layout["qc_status"], "USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
            self.assertEqual(adjusted_layout["initial_qc_ref"], result.layout["initial_qc_ref"])
            self.assertEqual(len(bridge.requests), 8, "Free edit must make no model request")
            (self.root / "free-edit-result.json").write_text(json.dumps(edited, ensure_ascii=False, indent=2))
        finally:
            if ScriptedBridge.instances:
                bridge = ScriptedBridge.instances[-1]
                # Keep only synthetic inputs. No private source/model content exists.
                (self.root / "scripted-requests.json").write_text(json.dumps(bridge.requests, ensure_ascii=False, indent=2))
                (self.root / "host-results.json").write_text(json.dumps(bridge.host_results, ensure_ascii=False, indent=2))
                (self.root / "proof-summary.json").write_text(json.dumps({"real_model_calls": 0,
                    "real_image_calls": 0, "merchant_materials": 0, "synthetic_model_messages": len(bridge.requests),
                    "stages": stages, "records": records}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    unittest.main()
