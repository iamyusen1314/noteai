"""Content-free tool/admission receipts; no providers or product DB."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
from unittest import mock

from tests.test_cover_agent_runtime import runtime


class WorkflowDiagnosticTests(unittest.TestCase):
    def activity(self):
        return {"attempts": {name: 0 for name in runtime._LOCAL_TOOL_NAMES},
            "last_name": "cover_view", "last_outcome": "returned", "elapsed_ms": 1234}

    def deadline(self):
        return {"phase": "before_shared_permit", "reason": "insufficient_read_window",
            "remaining_ms": 300000, "useful_read_ms": 160000, "minimum_read_ms": 180000,
            "request_margin_ms": 140000, "next_ordinal": 5, "dispatched": False}

    def test_strict_projection_rejects_content_unknown_names_and_invalid_types(self):
        activity, deadline = self.activity(), self.deadline()
        self.assertEqual(runtime._local_tool_diagnostic(activity), activity)
        self.assertEqual(runtime._deadline_admission_diagnostic(deadline), deadline)
        for change in ({"arguments": "PRIVATE_PROMPT"}, {"last_name": "not-a-tool"},
                {"last_name": []}, {"last_outcome": "PRIVATE_DETAIL"}, {"elapsed_ms": True},
                {"attempts": {**activity["attempts"], "cover_view": -1}}):
            self.assertIsNone(runtime._local_tool_diagnostic({**activity, **change}))
        for change in ({"prompt": "PRIVATE_PROMPT"}, {"phase": []}, {"reason": "PRIVATE_REASON"},
                {"dispatched": True}, {"next_ordinal": True}, {"remaining_ms": float("inf")},
                {"useful_read_ms": "PRIVATE_BODY"}):
            self.assertIsNone(runtime._deadline_admission_diagnostic({**deadline, **change}))

    def test_cleanup_keeps_optional_safe_evidence_and_original_unknown_state(self):
        for include_new in (False, True):
            with self.subTest(include_new=include_new), tempfile.TemporaryDirectory() as root, \
                    mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": root}):
                job = str(uuid.uuid4())
                directory = Path(root) / job
                state = directory / "host-state"
                state.mkdir(parents=True)
                checkpoint = {"job_id": job, "session_id": "offline-session", "status": "UNKNOWN",
                    "model_requests": 4, "pending_request": {"ordinal": 4, "label": "primary", "body_sha256": "a" * 64},
                    "private_prompt": "NEVER_RETAIN_THIS"}
                if include_new:
                    checkpoint["local_tool_activity"] = self.activity()
                    path = state / runtime._DEADLINE_ADMISSION_DIAGNOSTIC_FILE
                    path.write_text(json.dumps({"job_id": job, "diagnostic": self.deadline()}))
                    path.chmod(0o600)
                (state / "host-checkpoint.json").write_text(json.dumps(checkpoint))
                runtime.cleanup_workspace(job)
                receipt = json.loads((Path(root) / "receipts" / (job + ".json")).read_text())
                self.assertEqual(receipt["status"], "UNKNOWN")
                self.assertEqual(receipt["pending_request"], checkpoint["pending_request"])
                self.assertNotIn("NEVER_RETAIN_THIS", json.dumps(receipt))
                self.assertEqual("local_tool_activity" in receipt, include_new)
                self.assertEqual("deadline_admission" in receipt, include_new)
                self.assertFalse(directory.exists())

    def test_invalid_deadline_is_recorded_without_payload_or_changing_original_error(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path(root), sources=[], hooks=mock.Mock())
            bridge.request_deadline = float("nan")
            with self.assertRaisesRegex(runtime.provider.CoverAgentProviderError, "COVER_AGENT_TASK_DEADLINE"):
                bridge._check_model_deadline("before_shared_permit", 1)
            diagnostic = runtime._read_deadline_admission_diagnostic(Path(root), bridge.job_id)
            self.assertEqual(diagnostic["reason"], "invalid_deadline")
            self.assertIsNone(diagnostic["remaining_ms"])
            self.assertIsNone(diagnostic["useful_read_ms"])
            bridge.hooks.before_call.assert_not_called()
            self.assertEqual(bridge.ordinal, 0)

    @unittest.skipUnless(shutil.which("node"), "Node required for actual tool wrapper")
    def test_actual_serial_tool_wrapper_records_only_finite_fields_and_diagnostic_failure_is_optional(self):
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const helper=source.slice(source.indexOf('const LOCAL_TOOL_NAMES ='),source.indexOf('const sha ='));
const wrapper=source.slice(source.indexOf('  let localToolTail ='),source.indexOf('  const tools ='));
let writes=[],failWrites=false,clock=0;const critical={pending_request:{ordinal:3},pending_tool:{name:'cover_seedream'},concept_requested:true};
const checkpoint=JSON.parse(JSON.stringify(critical));
const ctx=vm.createContext({performance:{now:()=>++clock},checkpoint,checkpointPath:'/unused',inputClosed:false,
 job:{deadline_epoch_ms:Date.now()+60000},error:code=>Object.assign(new Error(code),{code}),
 atomicJSON:async(_p,value)=>{if(failWrites)throw new Error('PRIVATE_FS_PATH');writes.push(JSON.parse(JSON.stringify(value)));}});
vm.runInContext(helper+'\n'+wrapper+'\nglobalThis.tool=tool;',ctx);
(async()=>{
 const order=[];
 const a=ctx.tool('cover_read','',{},async()=>{order.push('read');return {content:'PRIVATE_BODY'};});
 const b=ctx.tool('cover_write','',{},async()=>{order.push('write');throw Object.assign(new Error('PRIVATE_HTML'),{code:'FIXTURE_REJECTION'});});
 const results=await Promise.all([a.execute({path:'PRIVATE_PATH'}),b.execute({text:'PRIVATE_PROMPT'})]);
 assert.deepEqual(order,['read','write']);assert.equal(results[0].content,'PRIVATE_BODY');
 assert.equal(JSON.parse(results[1].content).code,'FIXTURE_REJECTION');
 assert.equal(checkpoint.local_tool_activity.attempts.cover_read,1);assert.equal(checkpoint.local_tool_activity.attempts.cover_write,1);
 assert.equal(checkpoint.local_tool_activity.last_outcome,'failed');assert.equal(checkpoint.local_tool_activity.last_name,'cover_write');
 assert.ok(!JSON.stringify(checkpoint).includes('PRIVATE_'));
 for(const [key,value] of Object.entries(critical))assert.deepEqual(checkpoint[key],value);
 failWrites=true;assert.equal((await a.execute({})).content,'PRIVATE_BODY');
 const c=ctx.tool('cover_view','',{},async()=>{throw Object.assign(new Error('PRIVATE_UNKNOWN'),{code:'SUPPLIER_RESULT_UNKNOWN'});});
 failWrites=false;await c.execute({});assert.equal(checkpoint.status,'UNKNOWN');assert.equal(checkpoint.local_tool_activity.last_outcome,'unknown');
 for(const [key,value] of Object.entries(critical))assert.deepEqual(checkpoint[key],value);
 console.log(JSON.stringify({actual_wrapper:true,serial_order:true,optional_write_failure_preserved_result:true,unknown_pending_preserved:true}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "-e", script,
            str(runtime.ROOT / "cover_agent_host/host.mjs")], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["unknown_pending_preserved"])


if __name__ == "__main__":
    unittest.main()
