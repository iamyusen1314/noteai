"""Internal renderer permits; no SDK, browser, supplier or production database."""
import contextlib
import io
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

from tests.test_cover_agent_runtime import runtime, cover_runtime


class CapturedInput(io.BytesIO):
    def close(self):
        self.sent = self.getvalue()
        super().close()


class RendererBridgeLeaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job_id = str(uuid.uuid4())
        directory = self.root / job_id
        directory.mkdir()
        self.bridge = runtime.Bridge(job_id=job_id, directory=directory,
            sources=[], hooks=mock.Mock())
        self.order = []
        self.lease_id = str(uuid.uuid4())

    def event(self, kind, **fields):
        return {"type": kind, "id": str(uuid.uuid4()), "lease_id": self.lease_id, **fields}

    @contextlib.contextmanager
    def slot(self, *, deadline):
        self.assertGreater(deadline, time.monotonic())
        self.assertLess(deadline, time.monotonic() + 60)
        self.order.append("enter")
        try:
            yield
        finally:
            self.order.append("release")

    def run_events(self, events, *, cleanup_error=None, send_error=False, cancel_error=None):
        process = mock.Mock(stdin=CapturedInput(), stdout=io.BytesIO(
            b"".join(json.dumps(event).encode() + b"\n" for event in events)))
        if send_error:
            original_write = process.stdin.write
            def write(body):
                if b'"renderer_response"' in body:
                    raise BrokenPipeError("controlled renderer ACK disconnect")
                return original_write(body)
            process.stdin.write = write
        def stop(_process):
            self.assertIs(_process, process)
            self.order.append("stop")
            if cleanup_error:
                raise cleanup_error
        def known():
            if cancel_error is not None and self.order == ["enter"]:
                raise cancel_error
        with mock.patch.object(runtime.subprocess, "Popen", return_value=process), \
                mock.patch.object(runtime, "_stop_host", side_effect=stop), \
                mock.patch.object(runtime.public_product, "assert_result_known", side_effect=known), \
                mock.patch.object(runtime.artifacts, "render_slot", side_effect=self.slot), \
                mock.patch.object(runtime.provider, "complete") as supplier:
            try:
                value = self.bridge.run("internal transport fixture", deadline=time.time() + 30)
            finally:
                supplier.assert_not_called()
                self.assertTrue(process.stdin.closed)
                self.assertTrue(process.stdout.closed)
        return value, [json.loads(line) for line in process.stdin.sent.splitlines()]

    def test_matching_end_ack_releases_only_after_entire_callback(self):
        events = [self.event("renderer_begin", operation="render"),
            {"type": "render_finished", "artifact": {}, "preview": {"fixture": True}},
            self.event("renderer_end", clean=True), {"type": "result", "ok": True, "artifact": {}}]
        original = self.bridge._renderer_event
        def observe(event, **kw):
            if event["type"] == "renderer_end":
                self.assertEqual(self.order, ["enter"])
                self.assertEqual(self.bridge.last_preview, {"fixture": True})
            return original(event, **kw)
        with mock.patch.object(self.bridge, "_renderer_event", side_effect=observe):
            value, sent = self.run_events(events)
        self.assertTrue(value["ok"])
        self.assertEqual(self.order, ["enter", "release", "stop"])
        acks = [item for item in sent if item["type"] == "renderer_response"]
        self.assertEqual([item["result"] for item in acks], [
            {"allowed": True, "lease_id": self.lease_id},
            {"released": True, "lease_id": self.lease_id}])
        self.assertEqual([item["id"] for item in acks], [events[0]["id"], events[2]["id"]])

    def test_abort_disconnect_protocol_error_and_ack_failure_stop_before_release(self):
        cases = [
            ([self.event("renderer_begin", operation="render"), self.event("renderer_end", clean=False)],
                "COVER_AGENT_RENDER_ABORTED", False),
            ([self.event("renderer_begin", operation="check_fonts")], "COVER_AGENT_HOST_INTERRUPTED", False),
            ([self.event("renderer_begin", operation="check_contract"),
                self.event("renderer_end", clean=True, extra="forbidden")], "COVER_AGENT_HOST_PROTOCOL_INVALID", False),
            ([self.event("renderer_begin", operation="check_poster"),
                self.event("renderer_end", clean=True, lease_id=str(uuid.uuid4()))], "COVER_AGENT_HOST_PROTOCOL_INVALID", False),
            ([self.event("renderer_begin", operation="render"),
                self.event("renderer_begin", operation="render")], "COVER_AGENT_HOST_PROTOCOL_INVALID", False),
            ([self.event("renderer_begin", operation="render")], "ACK disconnect", True),
        ]
        for events, code, send_error in cases:
            with self.subTest(code=code, events=events):
                self.order.clear()
                with self.assertRaisesRegex(Exception, code):
                    self.run_events(events, send_error=send_error)
                self.assertEqual(self.order, ["enter", "stop", "release"])
                self.assertIsNone(self.bridge._renderer_lease)
        self.order.clear()
        cancelled = runtime.public_product.TrialProviderStopped("MODEL_OPERATION_CANCELLED")
        with self.assertRaisesRegex(runtime.public_product.TrialProviderStopped, "MODEL_OPERATION_CANCELLED"):
            self.run_events([self.event("renderer_begin", operation="render"),
                self.event("renderer_end", clean=True)], cancel_error=cancelled)
        self.assertEqual(self.order, ["enter", "stop", "release"])

    def test_cleanup_failure_retains_context_even_for_unexpected_stop_error(self):
        before = len(runtime._UNCONFIRMED_RENDERER_LEASES)
        events = [self.event("renderer_begin", operation="render"), self.event("renderer_end", clean=False)]
        try:
            with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_RENDER_ABORTED") as caught:
                self.run_events(events, cleanup_error=RuntimeError("controlled group cleanup failure"))
            self.assertEqual(self.order, ["enter", "stop"])
            self.assertEqual(len(runtime._UNCONFIRMED_RENDERER_LEASES), before + 1)
            self.assertIn("COVER_RENDERER_LEASE_RETAINED_CLEANUP_UNCONFIRMED", caught.exception.__notes__)
            diagnostic = json.loads((self.bridge.directory / "host-state/renderer-resource-diagnostic.json").read_text())
            self.assertEqual(diagnostic, {"job_id": self.bridge.job_id,
                "code": "COVER_RENDERER_LEASE_RETAINED_CLEANUP_UNCONFIRMED", "lease_retained": True})
            with mock.patch.object(runtime, "workspace_root", return_value=self.root):
                runtime.cleanup_workspace(self.bridge.job_id)
            receipt = json.loads((self.root / "receipts" / (self.bridge.job_id + ".json")).read_text())
            self.assertEqual(receipt["renderer_cleanup"], {"code": diagnostic["code"], "lease_retained": True})
            self.assertFalse(self.bridge.directory.exists())
            with mock.patch.object(runtime.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "LEASE_RETAINED_CLEANUP_UNCONFIRMED"):
                    self.bridge.run("must not resume a quarantined renderer", deadline=time.time() + 10)
                popen.assert_not_called()
        finally:
            # Only this synthetic context is released, after the retention
            # assertion. There is no native process or actual media permit.
            for _job, context in runtime._UNCONFIRMED_RENDERER_LEASES[before:]:
                context.__exit__(None, None, None)
            del runtime._UNCONFIRMED_RENDERER_LEASES[before:]

    def test_malformed_or_duplicate_packets_cannot_acquire_or_release_twice(self):
        with mock.patch.object(runtime.artifacts, "render_slot", side_effect=self.slot) as slots:
            for event in [self.event("renderer_begin", operation=[]),
                    self.event("renderer_begin", operation="font_add"),
                    self.event("renderer_begin", operation="render", extra=True),
                    self.event("renderer_end", clean=True)]:
                with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "HOST_PROTOCOL_INVALID"):
                    self.bridge._renderer_event(event, deadline=time.monotonic() + 10)
            slots.assert_not_called()
            self.bridge._renderer_event(self.event("renderer_begin", operation="render"), deadline=time.monotonic() + 10)
            self.bridge._renderer_event(self.event("renderer_end", clean=True), deadline=time.monotonic() + 10)
            with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "HOST_PROTOCOL_INVALID"):
                self.bridge._renderer_event(self.event("renderer_end", clean=True), deadline=time.monotonic() + 10)
        self.assertEqual(self.order, ["enter", "release"])


class RendererHostLeaseTests(unittest.TestCase):
    def test_actual_render_thumbnail_and_standalone_check_callbacks_hold_the_same_lease(self):
        node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        self.assertIsNotNone(node)
        source = Path(__file__).resolve().parents[1] / "model/cover_agent_host/host.mjs"
        script = r'''
import fs from 'node:fs/promises';import path from 'node:path';import vm from 'node:vm';
import assert from 'node:assert/strict';import {randomUUID,createHash} from 'node:crypto';
import {EventEmitter} from 'node:events';import {PassThrough} from 'node:stream';
const [sourcePath,root]=process.argv.slice(1),source=await fs.readFile(sourcePath,'utf8');
await fs.mkdir(path.join(root,'host-state'),{recursive:true});
await fs.writeFile(path.join(root,'index.html'),'<!doctype html><html><head></head><body>synthetic</body></html>');
const callbacks=new Map(),events=[];let held=false,mode='success';
const result={ok:true,png_path:path.join(root,'poster.png'),png_sha256:'a'.repeat(64),manifest_path:path.join(root,'render-manifest.json')};
const ctx=vm.createContext({fs,path,Buffer,randomUUID,process:{execPath:process.execPath},
 localChildren:new Set(),requests:0,checkpoint:{},checkpointPath:path.join(root,'host-state/checkpoint.json'),
 job:{work_dir:root,state_dir:path.join(root,'host-state'),editable_cli:'/not-launched-cli',skill_dir:root},
 lastRender:null,lastPreview:null,sha:x=>createHash('sha256').update(x).digest('hex'),
 error:code=>Object.assign(new Error(code),{code}),objectSchema:()=>({}),
 tool:(name,_description,_schema,execute)=>callbacks.set(name,execute),
 bridge:async(type,fields)=>{
  if(type==='tool_request'){assert(!held);events.push('authorize');return{result:{allowed:true,canonical_sources:[{ref:'original',path:'assets/original.png',sha256:'b'.repeat(64)}]}};}
  if(type==='renderer_begin'){assert(!held);held=true;events.push(fields.operation+':begin');return{type:'renderer_response',result:{allowed:true,lease_id:fields.lease_id}};}
  assert.equal(type,'renderer_end');assert(held);events.push('end:'+fields.clean);held=false;
  return{type:'renderer_response',result:{released:true,lease_id:fields.lease_id}};
 },
 runLocal:async(_cmd,args)=>{
  if(args.includes('add')){assert(!held);events.push('font_add');return{code:1,stdout:'original-font-error',stderr:''};}
  assert(held);events.push('CLI');return args.includes('render')
   ?{code:mode==='reject'?1:0,stdout:JSON.stringify(mode==='reject'?{ok:false,code:'UPSTREAM_FONTS_FAILED'}:result)}
   :{code:0,stdout:'original-check',stderr:''};
 },
 makeThumbnail:async()=>{assert(held);events.push('thumbnail');if(mode==='thumbnail-error')throw new Error('controlled thumbnail error');return{path:path.join(root,'thumbnail.png'),sha256:'c'.repeat(64)};},
 withBrowserTemporaryDirectory:async operation=>{assert(held||mode==='font-add');return await operation();},
 send:event=>{assert(held);assert.equal(event.type,'render_finished');events.push('render_finished');}
});
const helper=source.slice(source.indexOf('function inside('),source.indexOf('async function atomicJSON('));
const atomic=source.slice(source.indexOf('async function atomicJSON('),source.indexOf('function imageMime('));
const rejection=source.slice(source.indexOf('const RENDER_REJECTION_CODES ='),source.indexOf('function summaryMaterial('));
vm.runInContext(helper+atomic+rejection,ctx);
vm.runInContext(source.slice(source.indexOf("    tool('cover_render',"),source.indexOf("    tool('cover_check',")).trim().replace(/,$/,''),ctx);
const check=source.slice(source.indexOf("    tool('cover_check',"),source.indexOf('\n  ];',source.indexOf("    tool('cover_check',"))).trim().replace(/,$/,'');
vm.runInContext(check,ctx);
const request={project_dir:'.',sources:[{path:'assets/original.png'}],text_layers:[]};
assert.equal(JSON.parse((await callbacks.get('cover_render')({request})).content).ok,true);
assert.deepEqual(events,['authorize','render:begin','CLI','thumbnail','render_finished','end:true']);
events.length=0;mode='reject';assert.equal(JSON.parse((await callbacks.get('cover_render')({request})).content).code,'UPSTREAM_FONTS_FAILED');
assert.deepEqual(events,['authorize','render:begin','CLI','end:true']);
events.length=0;mode='thumbnail-error';await assert.rejects(callbacks.get('cover_render')({request}),/controlled thumbnail error/);
assert.deepEqual(events,['authorize','render:begin','CLI','thumbnail','end:false']);
for(const action of ['poster','fonts','contract']){
 events.length=0;mode='success';const value=JSON.parse((await callbacks.get('cover_check')({action,html:'index.html'})).content);
 assert.equal(value.stdout,'original-check');assert.deepEqual(events,['check_'+action+':begin','CLI','end:true']);
}
events.length=0;mode='font-add';assert.equal(JSON.parse((await callbacks.get('cover_check')({action:'font_add',html:'index.html',font_id:'cjk-sans'})).content).stdout,'original-font-error');
assert.deepEqual(events,['font_add']);assert(!held);
// Execute the actual runLocal as well: a signalled child has closed, but its
// browser descendants are not proved gone merely because localChildren is empty.
ctx.setTimeout=setTimeout;ctx.clearTimeout=clearTimeout;
let exitCode=null,exitSignal='SIGTERM',overflow=false,signals=[];
ctx.spawn=()=>{
 assert(held);events.push('CLI');const child=new EventEmitter();
 child.stdout=new PassThrough();child.stderr=new PassThrough();let closed=false;
 const close=()=>{if(closed)return;closed=true;child.stdout.end();child.stderr.end();child.emit('close',exitCode,exitSignal);};
 child.kill=signal=>{signals.push(signal);queueMicrotask(close);return true;};
 child.stdin={end:()=>queueMicrotask(()=>{
  child.stdout.write(overflow?'x'.repeat(8*1024*1024+1):JSON.stringify(exitCode===1?{ok:false,code:'UPSTREAM_FONTS_FAILED'}:result));
  if(!overflow)close();
 })};return child;
};
vm.runInContext(source.slice(source.indexOf('async function runLocal('),source.indexOf('function completionSSE(')),ctx);
const invoke=action=>action==='render'?callbacks.get('cover_render')({request})
 :callbacks.get('cover_check')({action,html:'index.html'});
for(const action of ['render','poster','fonts','contract']){
 events.length=0;mode='success';await assert.rejects(invoke(action),/LOCAL_TOOL_INTERRUPTED/);
 assert.deepEqual(events,action==='render'?['authorize','render:begin','CLI','end:false']:['check_'+action+':begin','CLI','end:false']);
 assert.equal(ctx.localChildren.size,0);assert(!held);
}
for(const [code,signal]of[[null,null],[0,'SIGTERM']]){
 events.length=0;exitCode=code;exitSignal=signal;
 await assert.rejects(invoke('render'),/LOCAL_TOOL_INTERRUPTED/);
 assert.deepEqual(events,['authorize','render:begin','CLI','end:false']);
}
events.length=0;exitCode=null;exitSignal='SIGTERM';overflow=true;
await assert.rejects(invoke('render'),/LOCAL_TOOL_INTERRUPTED/);assert.deepEqual(signals,['SIGTERM']);
assert.deepEqual(events,['authorize','render:begin','CLI','end:false']);
events.length=0;overflow=false;exitCode=1;exitSignal=null;
assert.equal(JSON.parse((await invoke('render')).content).code,'UPSTREAM_FONTS_FAILED');
assert.deepEqual(events,['authorize','render:begin','CLI','end:true']);
console.log('COVER_RENDERER_CALLBACK_LEASE_PROOF='+JSON.stringify({actual_callback_source:true,actual_runLocal:true,render_and_thumbnail_same_lease:true,all_three_standalone_checks_protected:true,font_install_not_nested:true,structured_rejection_preserved:true,thumbnail_error_requests_parent_cleanup:true,signal_null_or_overflow_requests_parent_cleanup:true,ordinary_exit_one_keeps_structured_rejection:true,browser_or_model_calls:0}));
'''
        with tempfile.TemporaryDirectory() as folder:
            process = subprocess.run([node, "--input-type=module", "-e", script, str(source), str(Path(folder).resolve())],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        self.assertIn(b'"render_and_thumbnail_same_lease":true', process.stdout)

    def test_actual_host_helper_waits_for_both_acks_and_marks_unclean_operations(self):
        node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        self.assertIsNotNone(node)
        source = Path(__file__).resolve().parents[1] / "model/cover_agent_host/host.mjs"
        script = r'''
import fs from 'node:fs/promises';import vm from 'node:vm';import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
const source=await fs.readFile(process.argv[1],'utf8');
const helper=source.slice(source.indexOf('async function withRendererLease('),source.indexOf('function relative('));
assert(helper.includes('renderer_begin')&&helper.includes('renderer_end'));
const children=new Set(),ctx=vm.createContext({randomUUID,localChildren:children,error:code=>Object.assign(new Error(code),{code})});
vm.runInContext(helper+'\nglobalThis.lease=withRendererLease;',ctx);
let beginResolve,endResolve,executed=false,returned=false,events=[];
const call=ctx.lease(async(type,fields)=>{events.push({type,...fields});return await new Promise(resolve=>{if(type==='renderer_begin')beginResolve=resolve;else endResolve=resolve;});},'render',async()=>{executed=true;return 'original-result';}).then(v=>{returned=true;return v;});
await new Promise(r=>setImmediate(r));assert(!executed);assert(!returned);
beginResolve({type:'renderer_response',result:{allowed:true,lease_id:events[0].lease_id}});
await new Promise(r=>setImmediate(r));assert(executed);assert(!returned);assert.equal(events[1].clean,true);
endResolve({type:'renderer_response',result:{released:true,lease_id:events[0].lease_id}});
assert.equal(await call,'original-result');assert(returned);
for(const mode of ['returned-rejection','throw','pending-child']){
 const out=[];let invoked=0;
 const bridge=async(type,fields)=>{out.push({type,...fields});return{type:'renderer_response',result:{lease_id:fields.lease_id,...(type==='renderer_begin'?{allowed:true}:{released:true})}};};
 const execute=async()=>{invoked++;if(mode==='throw')throw new Error('original failure');if(mode==='pending-child')children.add('owned-pending');return{ok:false,code:'ORIGINAL_CLI_REJECTION'};};
 if(mode==='throw')await assert.rejects(ctx.lease(bridge,'render',execute),/original failure/);
 else assert.equal((await ctx.lease(bridge,'render',execute)).code,'ORIGINAL_CLI_REJECTION');
 assert.equal(invoked,1);assert.deepEqual(out.map(x=>x.type),['renderer_begin','renderer_end']);
 assert.equal(out[1].clean,mode==='returned-rejection');children.clear();
}
let ran=false;
await assert.rejects(ctx.lease(async()=>({type:'renderer_response',result:{allowed:true,lease_id:'wrong'}}),'render',async()=>{ran=true;}),/BEGIN_NOT_ACKNOWLEDGED/);
assert(!ran);
console.log('COVER_RENDERER_HOST_LEASE_PROOF='+JSON.stringify({actual_helper:true,begin_before_execution:true,end_ack_before_return:true,negative_result_preserved:true,throw_or_pending_child_marks_unclean:true,model_calls:0}));
'''
        process = subprocess.run([node, "--input-type=module", "-e", script, str(source)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        self.assertIn(b'"throw_or_pending_child_marks_unclean":true', process.stdout)
