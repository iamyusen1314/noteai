"""Real pinned SDK, bounded short header waits, real local owner accounting.

The transport is HTTPMock only. These cases do not claim design/render quality
or production acceptance. Set the existing approved SDK installation explicitly.
"""
import errno
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_agent_runtime as runtime
import cover_agent_provider as provider
import cover_jobs
import cover_runtime
import db
import httpx
from tests import test_cover_agent_provider as provider_fixtures


class ResponseDeliveryDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job_id = str(uuid.uuid4())
        self.directory = self.root / self.job_id
        self.directory.mkdir()
        self.bridge = runtime.Bridge(job_id=self.job_id, directory=self.directory, sources=[], hooks=mock.Mock())

    def run_closed_pipe(self, *, model_error=None, diagnostic_error=False):
        class Pipe(io.BytesIO):
            writes = 0
            def write(pipe, body):
                pipe.writes += 1
                if pipe.writes > 1:
                    raise BrokenPipeError(errno.EPIPE, "PRIVATE_PIPE_DETAIL")
                return super().write(body)
        pipe = Pipe()
        event = {"type":"model_request", "id":"local-event", "method":"POST", "path":"/chat/completions", "body":{}}
        process = mock.Mock(stdin=pipe, stdout=io.BytesIO(json.dumps(event).encode() + b"\n"))
        def known(_body):
            if model_error is not None:
                raise model_error
            self.bridge.ordinal = 1
            return {"PRIVATE_RESPONSE_CONTENT":"NOT_FOR_RECEIPTS"}, "known-local-call"
        with mock.patch.object(runtime.subprocess, "Popen", return_value=process), \
                mock.patch.object(runtime, "_stop_host"), \
                mock.patch.object(runtime.public_product, "assert_result_known"), \
                mock.patch.object(self.bridge, "model", side_effect=known):
            writer = runtime._write_response_delivery_diagnostic
            with mock.patch.object(runtime, "_write_response_delivery_diagnostic",
                    side_effect=OSError("PRIVATE_DISK_DETAIL") if diagnostic_error else writer):
                with self.assertRaises(Exception) as caught:
                    self.bridge.run("PRIVATE_ORIGINAL_PROMPT", deadline=time.time() + 5)
        return caught.exception, pipe.writes

    def test_known_response_send_failure_has_local_code_without_supplier_unknown(self):
        error, writes = self.run_closed_pipe()
        self.assertEqual(writes, 2)
        self.assertEqual(error.code, "COVER_AGENT_HOST_RESPONSE_UNDELIVERED")
        self.assertFalse(error.outcome_unknown)
        self.assertIsInstance(error.__cause__, BrokenPipeError)
        pending = {"ordinal":1, "body_sha256":"a" * 64, "label":"primary"}
        state = self.directory / "host-state/host-checkpoint.json"
        state.write_text(json.dumps({"status":"UNKNOWN", "model_requests":1, "pending_request":pending}))
        with mock.patch.object(runtime, "workspace_root", return_value=self.root):
            runtime.cleanup_workspace(self.job_id)
        receipt = json.loads((self.root / "receipts" / (self.job_id + ".json")).read_text())
        self.assertEqual(receipt["status"], "UNKNOWN")
        self.assertEqual(receipt["pending_request"], pending)
        self.assertTrue(receipt["model_response_delivery_failure"]["supplier_result_known"])
        self.assertEqual(receipt["model_response_delivery_failure"]["os_errno"], errno.EPIPE)
        self.assertNotIn("host_result_failure", receipt)
        self.assertNotIn("PRIVATE_", json.dumps(receipt))

    def test_optional_diagnostic_failure_does_not_replace_or_retry_the_known_failure(self):
        with self.assertLogs(level="WARNING") as logs:
            error, writes = self.run_closed_pipe(diagnostic_error=True)
        self.assertEqual(error.code, "COVER_AGENT_HOST_RESPONSE_UNDELIVERED")
        self.assertFalse(error.outcome_unknown)
        self.assertEqual(writes, 2)
        self.assertNotIn("PRIVATE_", "\n".join(logs.output))

    def test_supplier_unknown_is_preserved_and_never_misclassified_as_known_delivery(self):
        original = provider.CoverAgentProviderError("COVER_AGENT_PROVIDER_RESULT_UNKNOWN", outcome_unknown=True)
        error, writes = self.run_closed_pipe(model_error=original)
        self.assertIs(error, original)
        self.assertTrue(error.outcome_unknown)
        self.assertEqual(writes, 1)
        self.assertIsNone(runtime._read_response_delivery_diagnostic(self.directory, self.job_id))

    def test_diagnostic_is_immutable_and_rejects_untrusted_fields_and_owner(self):
        diagnostic = {"code":"COVER_AGENT_HOST_RESPONSE_UNDELIVERED", "phase":"model_response_send",
            "call_id":"known-local-call", "ordinal":1, "exception_type":"BrokenPipeError",
            "os_errno":errno.EPIPE, "supplier_result_known":True}
        runtime._write_response_delivery_diagnostic(self.directory, self.job_id, diagnostic)
        self.assertEqual(runtime._read_response_delivery_diagnostic(self.directory, self.job_id), diagnostic)
        with self.assertRaises(FileExistsError):
            runtime._write_response_delivery_diagnostic(self.directory, self.job_id, diagnostic)
        self.assertIsNone(runtime._read_response_delivery_diagnostic(self.directory, str(uuid.uuid4())))
        self.assertIsNone(runtime._response_delivery_diagnostic({**diagnostic,"response_body":"PRIVATE"}))
        self.assertIsNone(runtime._response_delivery_diagnostic({**diagnostic,"supplier_result_known":False}))


@unittest.skipUnless(os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") and shutil.which("node"),
    "Explicit approved task-local SDK and Node required")
class HeaderWaitRealSDKTests(unittest.TestCase):
    proof = []

    @classmethod
    def tearDownClass(cls):
        node = os.environ.get("NOTEAI_COVER_NODE", "node")
        result = {"state":"REAL_SDK_TWO_HEADER_LAYERS_AND_KNOWN_LEDGER_PASS" if len(cls.proof) == 3 else "INCOMPLETE", "cases":cls.proof,
            "node":subprocess.check_output([node,"--version"],text=True).strip(),
            "sdk_version":json.loads((Path(os.environ["NOTEAI_COVER_HOST_NODE_MODULES"]) / "@opencode/sdk/package.json").read_text())["version"],
            "real_provider_calls":0, "production_changes":0,
            "limits":"Scaled short timeout equivalence; no claim that a real 300s wait, design quality or production chain was tested."}
        output = os.environ.get("NOTEAI_COVER_HEADER_PROOF_OUTPUT")
        if output:
            target = Path(output)
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            output_file = target / "header-wait-sdk-proof.json"
            output_file.write_text(json.dumps(result,indent=2) + "\n")
            output_file.chmod(0o600)
        print("HEADER_WAIT_REAL_SDK_PROOF=" + json.dumps(result,sort_keys=True))

    def exercise(self, *, sdk_short=False, native_short=False):
        fixture = provider_fixtures.CoverAgentProviderTests()
        fixture.setUp()
        try:
            with tempfile.TemporaryDirectory(prefix="noteai-sdk-header-proof-") as temporary:
                root = Path(temporary)
                model = root / "model"
                host = model / "cover_agent_host"
                host.mkdir(parents=True)
                for leaf in ("worker.mjs","thumbnail.mjs"):
                    shutil.copyfile(runtime.ROOT / "cover_agent_host" / leaf, host / leaf)
                text = (runtime.ROOT / "cover_agent_host/host.mjs").read_text()
                if sdk_short:
                    token = "encoding: 'none', headerTimeout: Math.max(1, job.deadline_epoch_ms - Date.now())"
                    self.assertEqual(text.count(token),1)
                    text = text.replace(token,"encoding: 'none', headerTimeout: 200",1)
                if native_short:
                    token = "new Agent({ headersTimeout: Math.max(1, job.deadline_epoch_ms - Date.now()) })"
                    self.assertEqual(text.count(token),1)
                    text = text.replace(token,"new Agent({ headersTimeout: 200 })",1)
                (host / "host.mjs").write_text(text)
                (model / "cover_editable").symlink_to(runtime.ROOT / "cover_editable",target_is_directory=True)
                directory = root / fixture.claim["request_id"]
                directory.mkdir()
                requests, before = [], []
                def transport(request):
                    requests.append(time.monotonic())
                    time.sleep(2)
                    return httpx.Response(200,json=fixture.response())
                def before_call(stage,call_id,_estimate):
                    before.append((stage,call_id))
                    cover_jobs.before_text_call(fixture.claim,"design",call_id)
                bridge = runtime.Bridge(job_id=fixture.claim["request_id"],directory=directory,sources=[],
                    hooks=cover_runtime.RuntimeHooks(before_call,lambda _record:None),
                    model_transport=httpx.MockTransport(transport))
                started = time.monotonic()
                with mock.patch.object(runtime,"ROOT",model):
                    with self.assertRaises(cover_runtime.CoverRuntimeError) as caught:
                        bridge.run("PRIVATE_SYNTHETIC_HEADER_FIXTURE; return a short answer without tools.",deadline=time.time()+300)
                checkpoint = json.loads((directory / "host-state/host-checkpoint.json").read_text())
                calls = [dict(row) for row in db.fetchall("SELECT id,state,http_status,model_usage_record_id FROM public_trial_calls WHERE usage_record_id=?",(fixture.claim["charge"]["usage_id"],))]
                self.assertEqual((len(requests),len(before),len(calls),len(bridge.costs)),(1,1,1,1),
                    {"code":caught.exception.code,"terminal":checkpoint.get("terminal_diagnostic"),
                        "local_result":runtime._read_host_result_diagnostic(directory,fixture.claim["request_id"])})
                self.assertEqual((calls[0]["state"],calls[0]["http_status"]),("responded",200))
                self.assertIsNotNone(calls[0]["model_usage_record_id"])
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records WHERE usage_record_id=?",(fixture.claim["charge"]["usage_id"],))[0],1)
                self.assertFalse(caught.exception.outcome_unknown)
                short = sdk_short or native_short
                if short:
                    self.assertEqual(caught.exception.code,"COVER_AGENT_HOST_RESPONSE_UNDELIVERED")
                    self.assertEqual(checkpoint["status"],"UNKNOWN")
                    self.assertTrue(checkpoint.get("pending_request"))
                    cover_jobs.fail_job(fixture.claim,failure_code=caught.exception.code,outcome_unknown=False)
                    self.assertEqual(cover_jobs.get_job(fixture.fixture.user,fixture.claim["request_id"])["billing"]["credits_used"],0)
                else:
                    # No rendered artifact is intentional in this transport fixture.
                    self.assertEqual(caught.exception.code,"COVER_AGENT_DESIGN_INCOMPLETE")
                    self.assertEqual(checkpoint["status"],"COMPLETE")
                    self.assertFalse(checkpoint.get("pending_request"))
                with mock.patch.object(runtime,"workspace_root",return_value=root):
                    runtime.cleanup_workspace(fixture.claim["request_id"])
                receipt = json.loads((root / "receipts" / (fixture.claim["request_id"] + ".json")).read_text())
                self.assertNotIn("PRIVATE_",json.dumps(receipt))
                if short:
                    self.assertTrue(receipt["model_response_delivery_failure"]["supplier_result_known"])
                    self.assertNotIn("host_result_failure",receipt)
                else:
                    self.assertNotIn("model_response_delivery_failure",receipt)
                self.proof.append({"case":"SDK_short" if sdk_short else "native_short" if native_short else "both_job_bounded",
                    "elapsed_seconds":round(time.monotonic()-started,3),"provider_delay_seconds":2,
                    "physical_HTTP_mock_requests":1,"before_call_count":1,"known_model_usage_records":1,
                    "supplier_unknown_count":0,"host_status":checkpoint["status"],"error_code":caught.exception.code,
                    "host_pending_request_present":bool(checkpoint.get("pending_request")),
                    "model_response_delivery_failure":short,"customer_failure_net_credits_zero":True if short else None})
        finally:
            fixture.tearDown()

    def test_short_sdk_wait_reproduces_known_response_undelivered(self):
        self.exercise(sdk_short=True)

    def test_short_native_wait_reproduces_known_response_undelivered(self):
        self.exercise(native_short=True)

    def test_both_production_header_waits_accept_the_late_known_response_once(self):
        self.exercise()


if __name__ == "__main__":
    unittest.main()
