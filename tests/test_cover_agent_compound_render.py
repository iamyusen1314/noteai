"""Real SDK/CLI compound rendering; no suppliers or merchant-quality claims."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import httpx
from PIL import Image

from tests import test_cover_agent_inspection_previews as inspection

fixtures, runtime, provider = inspection.fixtures, inspection.runtime, inspection.provider
artifacts = fixtures.fixture.artifacts


class CompoundRenderSDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") or not shutil.which("node"):
            raise unittest.SkipTest("Explicit approved existing SDK and Node required")
        if not Path(os.environ.get("EDITABLE_DESIGN_BROWSER", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")).is_file():
            raise unittest.SkipTest("Actual existing browser required")

    def test_one_actual_compound_callback_renders_captures_restores_and_free_edits(self):
        scope = fixtures.budget_fixture.CoverVerificationBudgetTests()
        scope.setUp()
        self.addCleanup(scope.tearDown)
        scope.configure("100000")
        original = fixtures.fixture.synthetic_png((2400, 1800), "#5A7F75")
        concept = fixtures.fixture.synthetic_png((1776, 2368), "#A1A8B1")
        source = {"media_ref": "synthetic-original", "payload": original, "sha256": hashlib.sha256(original).hexdigest()}
        bridges, wire, assertions = [], [], []
        html = fixtures.fixture.ScriptedBridge.html("assets/source-1.png").replace(
            '--font-title:"Noto Sans SC Variable",sans-serif}',
            '--font-title:"Noto Sans SC Variable",sans-serif;}')
        packet = {"files": [{"path": "index.html", "text": html},
            {"path": "poster.json", "text": json.dumps({"canvas": {"width": 1776, "height": 2368}, "scale": 1, "dpi": None})},
            {"path": "brief.md", "text": "Synthetic complete design brief."},
            {"path": "design-plan.md", "text": "Synthetic integrated design; preserve original photo and editable text."},
            {"path": "asset-plan.json", "text": '{"source":"assets/source-1.png"}'},
            {"path": "prompts.md", "text": "Synthetic nonshipping concept prompt retained."}],
            "fonts": [{"font_id": "cjk-sans", "css_var": "--font-title"}]}
        request = {"project_dir": ".", "sources": [{"path": "assets/source-1.png"}],
            "text_layers": [{"id": "title", "allowed_rect": {"x": 90, "y": 100, "width": 1600, "height": 350}}],
            "protected_regions": [{"x": 500, "y": 800, "width": 700, "height": 800}]}
        rendered, prepared = {}, {}

        class Witness(runtime.Bridge):
            def __init__(inner, **kwargs):
                super().__init__(**kwargs)
                bridges.append(inner)

        def transport(http_request):
            payload = json.loads(http_request.content)
            wire.append(payload)
            turn = len(wire)
            if turn == 1:
                calls = [("cover_seedream", {"prompt": "Synthetic technical composition; preserve actual photo facts."})]
            elif turn == 2:
                calls = [("cover_view", {"path": "reference/composition-reference.png"})]
            elif turn == 3:
                self.assertIn(hashlib.sha256(concept).hexdigest(), runtime._images_in(payload))
                calls = [("cover_render", {"request": request, "prepare": packet})]
            elif turn == 4:
                try:
                    result = fixtures.fixture.returned_value(payload, "render", tool_call_id="inspection_3_0")
                except AssertionError as error:
                    original_error = fixtures.fixture.returned_value(payload, "ok", tool_call_id="inspection_3_0")
                    raise AssertionError("Actual compound tool returned: " + json.dumps(original_error, ensure_ascii=False)) from error
                self.assertIsNone(result["prepare"]["failed_step"])
                self.assertEqual(result["prepare"]["not_run"], [])
                self.assertEqual((len(result["prepare"]["files"]), len(result["prepare"]["fonts"])), (6, 1))
                self.assertTrue(result["render"]["ok"])
                rendered.update(result["render"])
                prepared.update(result["prepare"])
                receipt = next(item for item in result["prepare"]["files"] if item["path"] == "index.html")
                self.assertEqual(receipt["input_sha256"], hashlib.sha256(html.encode()).hexdigest())
                self.assertEqual(receipt["sha256"], hashlib.sha256((bridges[0].directory / "index.html").read_bytes()).hexdigest())
                calls = [("cover_view", {"path": rendered["image_path"]})]
            elif turn == 5:
                self.assertIn(rendered["png_sha256"], runtime._images_in(payload))
                self.assertIn(rendered["thumbnail_sha256"], runtime._images_in(payload))
                calls = [("cover_write", {"path": "render-review.md", "text": "Actual synthetic PNG inspected; not merchant acceptance."})]
            elif turn == 6:
                return httpx.Response(200, json=inspection.model_reply(turn, text="Synthetic technical design complete."))
            else:
                self.assertEqual(turn, 7)
                images = [item for item in payload["messages"][0]["content"] if item.get("type") == "image_url"]
                import base64
                self.assertEqual(base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1]), original)
                qc = {"approved": True, "text_matches": True, "facts_preserved": True,
                    "subject_preserved": True, "issues": [], "local_adjustment": None,
                    "design_checks": {key: True for key in ("main_visual", "message_focus", "typographic_hierarchy",
                        "layout_balance", "thumbnail_legibility", "style_fits_subject")}}
                return httpx.Response(200, json=inspection.model_reply(turn, text=json.dumps(qc)))
            return httpx.Response(200, json=inspection.model_reply(turn, calls))

        def checked_transport(request):
            try:
                return transport(request)
            except AssertionError as error:
                assertions.append(error)
                raise

        def concept_stub(**kwargs):
            self.assertEqual(kwargs["source_images"], [original])
            return concept, {"call_id": kwargs["call_id"], "stage": "image", "status": "responded"}

        with tempfile.TemporaryDirectory(prefix="compound-sdk-") as folder, \
                mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": folder,
                    "NOTEAI_ARK_API_KEY": "offline-compound-no-supplier", "NOTEAI_MODEL_CAPACITY_ENABLED": "0"}), \
                mock.patch.object(fixtures.billing, "_pricing_snapshot", side_effect=inspection.price_fixture(fixtures.billing._pricing_snapshot)), \
                mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=concept_stub):
            try:
                result = runtime.run_cover(job_id=scope.task["job_id"], user_id=scope.owner,
                    report={"title": "原照独立图层中文排字测试", "body": "Synthetic integration fixture.", "title_variants": []},
                    sources=[source], hooks=runtime.cover_runtime.RuntimeHooks(lambda *_: None, lambda *_: None, lambda *_: None),
                    model_transport=httpx.MockTransport(checked_transport), bridge_class=Witness)
            except BaseException:
                if assertions:
                    raise assertions[0]
                raise
            restored = artifacts.restore(result.artifact["editable_bundle"], Path(folder) / "restored")
            self.assertEqual((restored / "assets/source-1.png").read_bytes(), original)
            self.assertEqual((restored / "reference/composition-reference.png").read_bytes(), concept)
            original_png = (restored / "out/poster.png").read_bytes()
            self.assertEqual(hashlib.sha256(original_png).hexdigest(), result.layout["final_sha256"])
            with Image.open(io.BytesIO(original_png)) as image:
                self.assertEqual(image.size, (1776, 2368))
            edited = artifacts.cli("edit", {"schema_version": artifacts.SCHEMA,
                "output_root": str(Path(folder) / "free-edit"), "parent_revision_dir": str(restored),
                "expected_parent_manifest_sha256": result.layout["manifest_sha256"],
                "initial_qc_ref": result.layout["initial_qc_ref"],
                "edits": [{"layer_id": "title", "text": "原照独立\n图层中文排字测试", "dx": 12, "dy": 8}]})
            adjusted, _, layout = artifacts.capture(edited, expected_sources=result.layout["input_source_hashes"])
            self.assertNotEqual(adjusted, original_png)
            self.assertEqual((restored / "out/poster.png").read_bytes(), original_png)
            self.assertEqual(layout["qc_status"], "USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
            for kind, code in (("geometry", "TEXT_OVERFLOW_OR_OUTSIDE_ALLOWED_REGION"),
                    ("subject", "TEXT_OVER_PROTECTED_SUBJECT")):
                negative = {**request, "schema_version": artifacts.SCHEMA,
                    "project_dir": str(restored), "output_root": str(Path(folder) / ("negative-" + kind)),
                    "approved_titles": ["原照独立图层中文排字测试"],
                    "sources": [{"path": "assets/source-1.png", "ref": source["media_ref"], "sha256": source["sha256"]}]}
                if kind == "geometry":
                    negative["text_layers"] = [{"id": "title", "allowed_rect": {"x": 0, "y": 0, "width": 1, "height": 1}}]
                else:
                    negative["protected_regions"] = [{"x": 90, "y": 100, "width": 1600, "height": 350}]
                with self.assertRaisesRegex(ValueError, "COVER_EDITABLE_" + code):
                    artifacts.cli("render", negative)
                self.assertEqual(list(Path(negative["output_root"]).rglob("poster.png")), [])
            self.assertEqual((restored / "out/poster.png").read_bytes(), original_png)
            self.assertEqual(len(wire), 7, "Compound local steps and free edit cannot insert model calls")
        print("COVER_COMPOUND_SDK_PROOF=" + json.dumps({"actual_sdk": True,
            "one_compound_callback": True, "files": 6, "fonts": 1,
            "checks_render_PNG_restore_freeedit": True, "middle_model_calls": 0,
            "original_and_concept_bytes_unchanged": True, "QC_actual_original_bytes": True,
            "html_input_stored_dual_SHA": True, "geometry_subject_checks_retained": True,
            "render_review_only_after_actual_pixels": True, "mock_200": 7, "real_supplier_calls": 0,
            "merchant_quality_acceptance": False}, sort_keys=True))


class CompoundRenderBoundaryTests(unittest.TestCase):
    def test_real_wrapper_packet_partial_failure_cancel_and_no_deadlock(self):
        script = r'''
import fs from 'node:fs/promises';import path from 'node:path';import vm from 'node:vm';
import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
const [sourcePath,root]=process.argv.slice(1),source=await fs.readFile(sourcePath,'utf8');
const sha=x=>createHash('sha256').update(x).digest('hex');
const helpers=source.slice(source.indexOf('function inside('),source.indexOf('async function atomicJSON('));
const wrapper=source.slice(source.indexOf('  const localExecutors ='),source.indexOf('  const tools = ['));
assert.ok(wrapper.includes('executePreparedRender'),'Actual source has no compound wrapper');
const activity=source.slice(source.indexOf('function localToolActivity('),source.indexOf('const PROGRESS_MARKER'));
const request={project_dir:'.',sources:[{path:'assets/original.png'}],text_layers:[]};
const packet=()=>({files:[{path:'brief.md',text:'Synthetic brief'}],fonts:[]});
let cases=0;
async function setup(mode){
 const directory=path.join(root,String(cases++));await fs.mkdir(path.join(directory,'host-state'),{recursive:true});
 let renders=0,fonts=0,ctx;
 const localFS={...fs,writeFile:async(file,...args)=>{await fs.writeFile(file,...args);if(mode==='cancel'&&file===path.join(directory,'brief.md'))ctx.inputClosed=true;}};
 ctx=vm.createContext({fs:localFS,path,Buffer,performance,sha,
  job:{work_dir:directory,state_dir:path.join(directory,'host-state'),deadline_epoch_ms:Date.now()+60000},
  checkpoint:{status:'RUNNING'},checkpointPath:path.join(directory,'host-state/checkpoint.json'),
  hostStarted:performance.now(),localToolTail:Promise.resolve(),progressFacts:{},geometryRepair:null,
  inputClosed:false,lastRender:null,lastPreview:null,error:code=>Object.assign(new Error(code),{code}),
  textGeometryNeedsRecheck:()=>null,textGeometryRepairHint:()=>null,renderRejection:()=>null,
  atomicJSON:async(file,value)=>fs.writeFile(file,JSON.stringify(value))});
 vm.runInContext(helpers+activity+wrapper+'\nglobalThis.register=tool;',ctx);
 ctx.raw={ok:false,code:'UPSTREAM_POSTER_CONTRACT_FAILED',detail:'retained original CLI detail'};
 const render=ctx.register('cover_render','fixture',{},async()=>{renders++;if(mode==='unknown')throw Object.assign(new Error('supplier unknown'),{code:'SUPPLIER_RESULT_UNKNOWN'});return {content:JSON.stringify(ctx.raw)};});
 ctx.register('cover_check','fixture',{},async()=>{fonts++;return {content:JSON.stringify({code:23,stdout:'original-font-stdout',stderr:'original-font-stderr'})};});
 return {ctx,directory,run:async prepare=>JSON.parse((await render.execute({request,...(prepare===undefined?{}:{prepare})})).content),counts:()=>({renders,fonts})};
}
for(const [name,mutate,code]of[
 ['traversal',p=>{p.files[0].path='../brief.md'},'RENDER_PREPARE_INVALID'],
 ['duplicate',p=>{p.files.push({...p.files[0]})},'RENDER_PREPARE_INVALID'],
 ['bytes',p=>{p.files[0].text='x'.repeat(262145)},'RENDER_PREPARE_TOO_LARGE'],
 ['activeHTML',p=>{p.files.push({path:'index.html',text:'<html><head></head><script>bad()</script></html>'})},'ACTIVE_HTML_FORBIDDEN'],
 ['font',p=>{p.fonts=[{font_id:'not-an-installed-font'}]},'RENDER_PREPARE_INVALID']]){
 const s=await setup(name),p=packet();mutate(p);const out=await s.run(p);
 assert.equal(out.code,code);assert.deepEqual(s.counts(),{renders:0,fonts:0});
 assert.equal(await fs.stat(path.join(s.directory,'brief.md')).then(()=>true,()=>false),false);
}
const partial=await setup('partial');await fs.mkdir(path.join(partial.directory,'poster.json'));
const pp=packet();pp.files.push({path:'poster.json',text:'{}'},{path:'prompts.md',text:'not written'});
const pr=await partial.run(pp);assert.equal(pr.prepare.files.length,1);assert.equal(pr.prepare.failed_step.kind,'write');assert.equal(pr.prepare.failed_step.index,1);assert.equal(pr.prepare.failed_step.code,'EISDIR');assert.equal(pr.render,null);assert.equal(pr.prepare.not_run.length,2);assert.equal(partial.counts().renders,0);
const font=await setup('fontfail'),fp=packet();fp.files=[{path:'index.html',text:'<!doctype html><html><head></head><body></body></html>'}];fp.fonts=[{font_id:'cjk-sans'}];
const fr=await font.run(fp);assert.equal(fr.prepare.failed_step.kind,'font_add');assert.equal(fr.prepare.fonts[0].stdout,'original-font-stdout');assert.equal(fr.prepare.fonts[0].stderr,'original-font-stderr');assert.equal(fr.render,null);assert.equal(font.counts().renders,0);
const contract=await setup('contract'),cr=await contract.run(packet());assert.deepEqual(cr.render,contract.ctx.raw);assert.equal(cr.prepare.failed_step.kind,'render');
const cancelled=await setup('cancel'),cp=packet();cp.files.push({path:'prompts.md',text:'must not write'});
const cc=await cancelled.run(cp);assert.equal(cc.prepare.failed_step.code,'LOCAL_TOOL_DEADLINE');assert.equal(cc.prepare.files.length,1);assert.equal(cancelled.counts().renders,0);cancelled.ctx.inputClosed=false;
assert.deepEqual(await cancelled.run(undefined),cancelled.ctx.raw); // Tail released, legacy unchanged.
const unknown=await setup('unknown'),ur=await unknown.run(packet());assert.equal(ur.code,'SUPPLIER_RESULT_UNKNOWN');assert.equal(unknown.ctx.checkpoint.status,'UNKNOWN');assert.equal(unknown.counts().renders,1);
console.log('COVER_COMPOUND_BOUNDARY_PROOF='+JSON.stringify({actual_serialized_wrapper:true,
 invalid_before_write:true,partial_write_preserved:true,font_error_preserved:true,CLI_error_preserved:true,
 cancellation_stops_remaining_steps:true,legacy_and_tail_release:true,UNKNOWN_not_retried:true,
 model_calls:0,real_supplier_calls:0}));
'''
        with tempfile.TemporaryDirectory(prefix="compound-boundaries-") as folder:
            result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "--input-type=module", "-e", script,
                str(runtime.ROOT / "cover_agent_host/host.mjs"), str(Path(folder).resolve())], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        print(result.stdout.strip())


class CompoundRenderCompactionTests(unittest.TestCase):
    def test_actual_compaction_requires_success_and_dual_hashes(self):
        script = r'''
import fs from 'node:fs/promises';import path from 'node:path';import vm from 'node:vm';
import assert from 'node:assert/strict';import {createHash}from'node:crypto';
const [sourcePath,root]=process.argv.slice(1),source=await fs.readFile(sourcePath,'utf8');
const sha=x=>createHash('sha256').update(x).digest('hex');let hook;
const helpers=source.slice(source.indexOf('function inside('),source.indexOf('async function atomicJSON('));
const summary=source.slice(source.indexOf('function summaryMaterial('),source.indexOf('\nlet sdk,'));
const block=source.slice(source.indexOf("    await ctx.session.hook('compaction',"),source.indexOf("    await ctx.session.hook('context',"));
const ctx=vm.createContext({fs,path,Buffer,sha,MAX_FILE:8388608,checkpoint:{},
 job:{work_dir:root,state_dir:path.join(root,'state'),compaction_output_tokens:8192},error:code=>new Error(code),
 ctx:{session:{hook:async(name,fn)=>{assert.equal(name,'compaction');hook=fn;}}}});
vm.runInContext(helpers+summary,ctx);await vm.runInContext('(async()=>{'+block+'})()',ctx);
const authored='<html>AUTHORED_ONCE_KEEP_ON_FAILURE</html>',stored='<meta>managed font and CSP</meta>'+authored;
const receipt={path:'index.html',bytes:Buffer.byteLength(stored),sha256:sha(stored),input_bytes:Buffer.byteLength(authored),input_sha256:sha(authored)};
async function invoke(mode){
 await fs.writeFile(path.join(root,'index.html'),mode==='changed'?stored+'changed':stored);
 const r={...receipt};if(mode==='wrong_input')r.input_sha256='a'.repeat(64);if(mode==='wrong_stored')r.sha256='b'.repeat(64);
 const value={prepare:{files:[r],fonts:[],failed_step:['failed','partial'].includes(mode)?{kind:mode==='partial'?'write':'render',index:0,code:'CHECK_FAILED'}:null,not_run:[]},render:mode==='partial'?null:{ok:mode!=='failed'}};
 const input={request:{project_dir:'.'},prepare:{files:[{path:'index.html',text:authored}],fonts:[]}};
 const event={messages:[{role:'assistant',content:[{type:'tool-call',id:'compound',name:'cover_render',input}]},
  {role:'tool',content:[{type:'tool-result',id:'compound',name:'cover_render',result:{type:'text',value:JSON.stringify(value)}}]}],options:{}};
 await hook(event);assert.equal(event.options.maxTokens,8192);return JSON.stringify(event.messages);
}
const good=await invoke('good');assert.ok(good.includes('[Authored input verified;'));assert.ok(!good.includes(authored));
for(const mode of ['failed','partial','changed','wrong_input','wrong_stored']){const out=await invoke(mode);assert.ok(out.includes(authored),mode+' discarded unverified authored input');}
console.log('COVER_COMPOUND_COMPACTION_PROOF='+JSON.stringify({actual_compaction_hook:true,
 successful_dual_SHA_only:true,failed_partial_kept:true,changed_stored_kept:true,forged_input_or_stored_SHA_kept:true,
 original_summary_branch_used:true,model_calls:0,real_supplier_calls:0}));
'''
        with tempfile.TemporaryDirectory(prefix="compound-compaction-") as folder:
            result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"), "--input-type=module", "-e", script,
                str(runtime.ROOT / "cover_agent_host/host.mjs"), str(Path(folder).resolve())], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        print(result.stdout.strip())
