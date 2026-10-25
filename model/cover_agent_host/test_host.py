"""Offline integration proof against the installed, real OpenCode 2.1.2 SDK.

NOTEAI_COVER_HOST_NODE_MODULES points to the task-local exact installation.
No remote model endpoint, credential, account, or product database is involved.
"""
import ast
import base64
from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

from PIL import Image

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
sys.path.insert(0, str(PROJECT / "model"))
from cover_agent_thinking import ThinkingState
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGNQKJhAEmIY1TCqYfhqAACs2CAQru0W7wAAAABJRU5ErkJggg==")


def provider_admission():
    """Execute the actual pure validator, without importing DB/env/provider I/O."""
    names = {"MODEL", "MAX_INPUT_TOKENS", "MAX_OUTPUT_TOKENS", "_NAME", "_KEYS",
             "_INPUT_DIAGNOSTIC_KEYS", "_TEXT_BREAKDOWN_KEYS", "CoverAgentProviderError", "validated_input_diagnostics",
             "validated_text_breakdown", "_text_breakdown",
             "_OUTPUT_DIAGNOSTIC_KEYS", "_OUTPUT_FINISH_REASONS", "validated_output_diagnostics",
             "_RESERVATION_DIAGNOSTIC_KEYS", "_RESERVATION_EXCEPTION_TYPES", "validated_reservation_diagnostics",
             "_measure_input", "_invalid", "_image_tokens", "_validate_and_measure_payload",
             "_check_request_size", "prepare_payload", "admit_payload"}
    source = PROJECT / "model/cover_agent_provider.py"
    tree = ast.parse(source.read_text(), filename=str(source))
    selected = [node for node in tree.body if (
        isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets))]
    found = {node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else node.targets[0].id
             for node in selected}
    if found != names:
        raise AssertionError("Pure provider contract changed: " + repr(names ^ found))
    media_source = PROJECT / "model/ark_media.py"
    media_tree = ast.parse(media_source.read_text(), filename=str(media_source))
    media_nodes = [node for node in media_tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id in {"MAX_IMAGE_BYTES", "MAX_REQUEST_BYTES"}
                           for t in node.targets)]
    media = {}
    exec(compile(ast.Module(body=media_nodes, type_ignores=[]), str(media_source), "exec"), media)
    namespace = {"base64": base64, "deepcopy": deepcopy, "io": io, "json": json,
                 "math": math, "re": re, "Image": Image,
                 "ark_media": SimpleNamespace(**{key: media[key] for key in ("MAX_IMAGE_BYTES", "MAX_REQUEST_BYTES")}),
                 "public_product": SimpleNamespace(TrialProviderStopped=RuntimeError)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def text_values(value):
    if isinstance(value, str):
        return [] if value.startswith("data:image/") else [value]
    if isinstance(value, list):
        return [text for item in value for text in text_values(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in text_values(item)]
    return []


def image_hashes(body):
    return [hashlib.sha256(base64.b64decode(part["image_url"]["url"].split(",", 1)[1])).hexdigest()
            for message in body["messages"] if isinstance(message.get("content"), list)
            for part in message["content"] if part.get("type") == "image_url"]


class HostProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES")
        cls.node = os.environ.get("NOTEAI_COVER_NODE") or shutil.which("node")
        if not cls.modules or not cls.node:
            raise unittest.SkipTest("Explicit task-local OpenCode installation and node required")
        cls.node_version = subprocess.run([cls.node, "--version"], capture_output=True,
                                          text=True, check=True, timeout=5).stdout.strip()
        cls.root = Path(tempfile.mkdtemp(prefix="noteai-cover-host-proof-"))
        cls.receipts = []

    @classmethod
    def tearDownClass(cls):
        receipt = {"real_model_requests": 0, "sdk_version": "2.1.2", "node_version": cls.node_version,
                   "fixtures": cls.receipts}
        (cls.root / "proof-results.json").write_text(json.dumps(receipt, indent=2))
        output = os.environ.get("NOTEAI_COVER_HOST_PROOF_OUTPUT")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            shutil.copytree(cls.root, Path(output) / cls.root.name)
        print("HOST_PROOF_EVIDENCE=" + str(cls.root))

    def request(self, case, *, mode="run", limit=None, behavior="success", session_id=None,
                forbidden_path=None, admission=None, respond=None, nine_photos=False, thinking=None,
                tool_respond=None):
        root = self.root / case
        (root / "work").mkdir(parents=True, exist_ok=True)
        (root / "work/photo.png").write_bytes(PNG)
        photos = [{"path": "photo.png"}]
        if nine_photos:
            photos = []
            for index in range(1, 10):
                target = root / ("work/source-" + str(index) + ".png")
                image = Image.new("RGB", (32, 32), (index * 23, index * 17, index * 11))
                image.save(target)
                photos.append({"path": target.name, "name": "original-" + str(index)})
        prompt = "Offline proof only. Follow the returned tool calls and finish. Do not generate artwork."
        if nine_photos:
            prompt += "\n批准事实：真实庭院；批准标题：城市里的日式庭院。不得增加价格或服务。\n原照索引=" + json.dumps([
                {"path": photo["path"], "sha256": hashlib.sha256((root / "work" / photo["path"]).read_bytes()).hexdigest()}
                for photo in photos], ensure_ascii=False)
        start = {
            "type": "start", "job_id": case, "state_dir": str(root / "state"),
            "work_dir": str(root / "work"),
            "skill_dir": str(PROJECT / "model/cover_editable/vendor/editable-design"),
            "editable_cli": str(PROJECT / "model/cover_editable/cli.mjs"),
            "model_id": admission["MODEL"] if admission else "offline-fixture", "prompt": prompt,
            "images": photos, "max_model_requests": limit,
            "deadline_epoch_ms": int((time.time() + 60) * 1000), "mode": mode,
        }
        if session_id:
            start["session_id"] = session_id
        env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "NOTEAI_COVER_HOST_NODE_MODULES": self.modules}
        for key in ["EDITABLE_DESIGN_BROWSER", "PUPPETEER_EXECUTABLE_PATH", "NO_SANDBOX", "EDITABLE_DESIGN_NO_SANDBOX"]:
            if os.environ.get(key):
                env[key] = os.environ[key]
        proc = subprocess.Popen([self.node, str(HERE / "worker.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, bufsize=1)
        host_sha = hashlib.sha256((HERE / "host.mjs").read_bytes()).hexdigest()
        proc.stdin.write(json.dumps(start) + "\n"); proc.stdin.flush()
        events, calls, preflights, responses, supplier_bodies = [], [], [], [], []
        selector = selectors.DefaultSelector(); selector.register(proc.stdout, selectors.EVENT_READ)
        until = time.time() + 75
        try:
            while time.time() < until:
                if not selector.select(1):
                    if proc.poll() is not None:
                        break
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                event = json.loads(line); events.append(event)
                if event["type"] == "tool_request" and tool_respond is not None:
                    # Explicit synthetic business approval only; the real host
                    # still invokes its ordinary pinned CLI/browser itself.
                    answer = {"type": "tool_response", "id": event["id"],
                              "result": tool_respond(event)}
                    proc.stdin.write(json.dumps(answer) + "\n"); proc.stdin.flush()
                if event["type"] == "model_preflight":
                    self.assertEqual((event["method"], event["path"]), ("POST", "/chat/completions"))
                    wire = thinking.restore(event["body"]) if thinking is not None else event["body"]
                    outcome = admission["admit_payload"](wire) if admission else {"allowed": True}
                    preflights.append({"label": event.get("label"), "outcome": outcome,
                                       "measurement": admission["_validate_and_measure_payload"](wire)[1] if admission else None,
                                       "body_sha256": hashlib.sha256(json.dumps(wire, sort_keys=True).encode()).hexdigest()})
                    answer = {"type": "model_preflight_response", "id": event["id"], **outcome}
                    proc.stdin.write(json.dumps(answer) + "\n"); proc.stdin.flush()
                if event["type"] == "model_request":
                    calls.append(event)
                    wire = thinking.restore(event["body"]) if thinking is not None else event["body"]
                    self.assertEqual(preflights[-1]["body_sha256"], hashlib.sha256(json.dumps(wire, sort_keys=True).encode()).hexdigest())
                    supplier_bodies.append(wire)
                    if behavior == "disconnect":
                        proc.stdin.close()
                        continue
                    if respond:
                        answer = respond({**event, "body": wire}, calls)
                    elif behavior == "unknown":
                        answer = {"type": "model_response", "id": event["id"], "unknown": True}
                    elif behavior == "503":
                        answer = {"type": "model_response", "id": event["id"], "status": 503, "body": {"error": {"message": "controlled offline failure", "type": "server_error"}}}
                    else:
                        ordinal = len(calls)
                        if ordinal == 1 and forbidden_path:
                            fn, args = "cover_write", {"path": forbidden_path, "text": "{}"}
                        elif ordinal == 1 and behavior == "unsafe_html":
                            fn, args = "cover_write", {"path": "unsafe.html", "text": '<html><head></head><body><script>fetch("https://example.invalid")</script></body></html>'}
                        elif ordinal == 1:
                            fn, args = "cover_write", {"path": "evidence.md", "text": "offline tool execution"}
                        elif ordinal == 2:
                            fn, args = "cover_view", {"path": "photo.png"}
                        else:
                            fn, args = None, None
                        message = {"role": "assistant", "content": "OFFLINE_COMPLETE" if fn is None else None}
                        if fn:
                            message["tool_calls"] = [{"id": "call_" + str(ordinal), "type": "function", "function": {"name": fn, "arguments": json.dumps(args)}}]
                        body = {"id": "chatcmpl_fixture", "object": "chat.completion", "created": 1, "model": "offline-fixture", "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if fn else "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}
                        answer = {"type": "model_response", "id": event["id"], "status": 200, "body": body}
                    if thinking is not None and answer.get("status") == 200:
                        answer = {**answer, "body": thinking.remember(answer["body"])}
                    responses.append(answer)
                    proc.stdin.write(json.dumps(answer) + "\n"); proc.stdin.flush()
                if event["type"] == "result":
                    break
            if not proc.stdin.closed:
                proc.stdin.close()
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()
            stderr = proc.stderr.read()
            proc.stdout.close(); proc.stderr.close()
            selector.close()
        (root / (mode + "-" + behavior + "-events.json")).write_text(json.dumps(events, indent=2))
        (root / (mode + "-" + behavior + "-responses.json")).write_text(json.dumps(responses, indent=2))
        (root / (mode + "-" + behavior + "-synthetic-supplier-bodies.json")).write_text(json.dumps(supplier_bodies, indent=2))
        (root / (mode + "-" + behavior + "-stderr.txt")).write_text(stderr)
        result = next((event for event in reversed(events) if event["type"] == "result"), None)
        self.assertIsNotNone(result, stderr)
        self.receipts.append({"case": case, "mode": mode, "behavior": behavior,
                              "host_sha256": host_sha,
                              "model_bridge_requests": len(calls), "preflights": preflights,
                              "result": result, "events_file": str(root / (mode + "-" + behavior + "-events.json"))})
        return result, calls, events, root

    def test_complete_skill_image_tool_loop_and_reopen_without_dispatch(self):
        result, calls, events, root = self.request("success")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(calls), 3)
        self.assertEqual([call["ordinal"] for call in calls], [1, 2, 3])
        self.assertTrue(all(call["body"]["stream"] is False for call in calls))
        first = json.dumps(calls[0]["body"])
        self.assertTrue("Create an art-directed composition reference" in first, "Full Skill body missing")
        self.assertTrue("## Read the render" in first and "## Deliver" in first, "Full Skill final phases missing")
        self.assertTrue(base64.b64encode(PNG).decode() in first, "Photo pixels did not reach transport")
        tool_names = {tool["function"]["name"] for tool in calls[0]["body"]["tools"]}
        self.assertEqual(tool_names, {"cover_read", "cover_write", "cover_view", "cover_seedream", "cover_render", "cover_check"})
        self.assertEqual((root / "work/evidence.md").read_text(), "offline tool execution")
        # The image produced by the view tool really reached the next provider request.
        images = []
        for message in calls[-1]["body"]["messages"]:
            for part in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if part.get("type") == "image_url":
                    images.append(part["image_url"]["url"])
        self.assertGreaterEqual(len(images), 2)
        self.assertEqual({hashlib.sha256(base64.b64decode(url.split(",", 1)[1])).hexdigest() for url in images}, {hashlib.sha256(PNG).hexdigest()})
        self.assertNotIn("data:image", json.dumps(result))
        reopened, dispatched, _, _ = self.request("success", mode="inspect")
        self.assertTrue(reopened["ok"], reopened)
        self.assertEqual(reopened["session_id"], result["session_id"])
        self.assertEqual(dispatched, [])

    def test_managed_font_variable_scope_uses_actual_helpers(self):
        source = HERE / "host.mjs"
        script = r'''
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function fontFaces('),end=source.indexOf('async function atomicJSON(');
assert(start>=0 && end>start);
const declaration='--font-kit-cjk-serif: "Installed", serif;';
const ctx=vm.createContext({Buffer,path,checkpoint:{managed_fonts:{'index.html':{
  'cjk-serif':{family:'Installed',faces:[],declaration}}}},
  error:code=>Object.assign(new Error(code),{code}),
  sha:v=>createHash('sha256').update(v).digest('hex')});
const relativeStart=source.indexOf('function relative('),relativeEnd=source.indexOf('async function safeExisting(');
const summaryStart=source.indexOf('function summaryMaterial('),summaryEnd=source.indexOf('\nlet sdk,',summaryStart);
assert(relativeStart>=0 && relativeEnd>relativeStart && summaryStart>=0 && summaryEnd>summaryStart);
vm.runInContext(source.slice(start,end)+source.slice(relativeStart,relativeEnd)
  +source.slice(summaryStart,summaryEnd),ctx);
const outcomes=[];
const rejected=[
  ['unused_selector','.unused{'+declaration+'}'],
  ['conditional_root','@media(min-width:1px){:root{'+declaration+'}}'],
  ['duplicate_root',':root{'+declaration+'}:root{'+declaration+'}'],
  ['global_and_unused',':root{'+declaration+'}.unused{'+declaration+'}'],
  ['wrong_root_no_semicolon',':root{--font-kit-cjk-serif:"Wrong",serif}'],
  ['wrong_root_no_semicolon_whitespace',':root{--font-kit-cjk-serif:"Wrong", serif \n }'],
  ['unused_no_semicolon','.unused{--font-kit-cjk-serif:"Installed",serif}'],
  ['conditional_no_semicolon','@media(min-width:1px){:root{--font-kit-cjk-serif:"Installed",serif}}'],
];
for(const [name,css] of rejected){
  let code='NO_ERROR';
  try{ctx.restoreManagedFonts('index.html','<style>'+css+'</style><h1>UNCHANGED_DOM</h1>');}
  catch(e){code=e.code;}
  outcomes.push({name,code});
}
const normal='<style>:root{'+declaration+'--font-title:explicit-role-sentinel;}</style><h1>UNCHANGED_DOM</h1>';
assert.equal(ctx.restoreManagedFonts('index.html',normal),normal);
outcomes.push({name:'normal_global_root',unchanged:true});
for(const [name,value] of [['correct_no_semicolon','"Installed",serif'],
                          ['correct_no_semicolon_whitespace','"Installed", serif \n ']]){
  const html='<style>:root{--font-title:explicit-role-sentinel;--font-kit-cjk-serif:'+value+'}</style><h1>UNCHANGED_DOM</h1>';
  outcomes.push({name,unchanged:ctx.restoreManagedFonts('index.html',html)===html});
}
const fake=`<style>/* .unused{${declaration}} */ .example{content:' :root{${declaration}} ';}
:root{--font-title:var(--font-kit-cjk-serif);}</style><h1>UNCHANGED_DOM</h1>`;
const restored=ctx.restoreManagedFonts('index.html',fake);
assert.equal(restored,fake.replace('<style>','<style>:root {'+declaration+'}'));
assert.equal(ctx.restoreManagedFonts('index.html',restored),restored);
assert(restored.includes('--font-title:var(--font-kit-cjk-serif);'));
outcomes.push({name:'references_comments_strings_only',tool_global_added:true,role_unchanged:true});
const known='@font-face {font-family:"Installed";src:url("./assets/fonts/cjk-serif/known.woff2");}';
const unknown=known.replace('Installed','UNKNOWN_AUTHOR_FACE');
ctx.checkpoint.managed_fonts['index.html']['cjk-serif'].faces=[known];
const raw='<html><head><style>'+known+unknown+':root{--field:#123456;}</style></head>'
  +'<body><h1>完整非字体DOM与原文字</h1><!--UNCHANGED_DOM_TAIL--></body></html>';
const input=[{role:'assistant',content:[
  {type:'tool-call',id:'raw-text-read',name:'cover_read',input:{path:'snapshot.html'}},
  {type:'tool-call',id:'raw-content-read',name:'cover_read',input:{path:'another.html'}},
  {type:'tool-call',id:'skill-read',name:'cover_read',input:{path:'skill:references/example.html'}},
]},{role:'tool',content:[
  {type:'tool-result',id:'raw-text-read',name:'cover_read',result:{type:'text',value:raw}},
  {type:'tool-result',id:'raw-content-read',name:'cover_read',result:{type:'content',value:[{type:'text',text:raw}]}},
  {type:'tool-result',id:'skill-read',name:'cover_read',result:{type:'text',value:raw}},
]}];
const original=JSON.stringify(input),summary=ctx.summaryMaterial(input);
assert.equal(JSON.stringify(input),original);
assert.equal(summary.length,1);assert.equal(summary[0].role,'user');
const prefix='Recorded tool result: ';
const results=summary[0].content.filter(part=>part.type==='text' && part.text.startsWith(prefix))
  .map(part=>JSON.parse(part.text.slice(prefix.length)).result);
const textView=JSON.parse(results[0].value),contentView=JSON.parse(results[1].value[0].text);
for(const view of [textView,contentView]){
  assert.equal(view.omitted_font_faces,1);
  assert.equal(view.text,raw.replace(known,''));
  assert(view.text.includes(unknown));
}
assert.equal(results[2].value,raw);
outcomes.push({name:'summary_raw_read_views',text_wrapper:true,content_wrapper:true,
  unknown_face_retained:true,skill_html_unchanged:true,original_messages_unchanged:true});
console.log(JSON.stringify({host_sha256:createHash('sha256').update(source).digest('hex'),
  actual_helper_segment:true,sdk_imported:false,supplier_calls:0,outcomes}));
assert(outcomes.slice(0,rejected.length).every(item=>item.code==='MANAGED_FONT_VARIABLE_CONFLICT'),
  'Non-global or duplicate font-kit declaration was accepted as restored');
assert(outcomes.filter(item=>item.name.startsWith('correct_no_semicolon')).every(item=>item.unchanged),
  'Correct global final declaration without semicolon was unnecessarily replaced');
'''
        result = subprocess.run([self.node, "--input-type=module", "-e", script, str(source)],
            capture_output=True, text=True, timeout=10,
            env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin"})
        (self.root / "font-scope-vm.stdout.json").write_text(result.stdout)
        (self.root / "font-scope-vm.stderr.txt").write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["outcomes"]), 13)

    def test_real_sdk_managed_cjk_fonts_keep_complete_authored_html_editable(self):
        case = "managed_font_edit"
        work = self.root / case / "work"
        (work / "assets").mkdir(parents=True)
        photo = work / "assets/synthetic-photo.png"
        Image.new("RGB", (800, 1000), (117, 154, 131)).save(photo)
        photo_bytes = photo.read_bytes()
        (work / "poster.json").write_text(json.dumps({"canvas": {"width": 1776, "height": 2368},
                                                     "scale": 1, "dpi": None}))
        tail = "AUTHORED_DOM_TAIL_AFTER_MANAGED_FONTS"
        original_text, edited_text = "原始中文排字", "调整后的中文排字"
        authored = ("<!doctype html><html><head><meta charset=\"utf-8\"><style>\n"
                    ":root { --font-title: \"Songti SC\", serif; --field: #242421; }\n"
                    "*{box-sizing:border-box}html,body{margin:0;padding:0;width:1776px}\n"
                    "#poster {position:relative;width:1776px;height:2368px;overflow:hidden;background:var(--field)}\n"
                    ".headline{position:absolute;left:120px;top:150px;width:1500px;height:260px;"
                    "font-family:var(--font-title);font-size:118px;line-height:1.3;color:#ffffff}\n"
                    ".photo{position:absolute;left:120px;top:600px;width:1536px;height:1600px;object-fit:contain}\n"
                    "</style></head><body><div id=\"poster\" data-canvas-width=\"1776\" "
                    "data-canvas-height=\"2368\"><img class=\"photo\" src=\"assets/synthetic-photo.png\" alt=\"\">"
                    "<div class=\"hf-slot headline\" data-layer-id=\"headline\">" + original_text + "</div>"
                    "<!--" + tail + "--></div></body></html>")
        faces = re.compile(r"@font-face\s*\{[^{}]*\}")
        kit = re.compile(r"--font-kit-cjk-serif\s*:[^;{}]+;?")
        observed = {"synthetic_fixture": True, "external_provider_calls": 0}
        saved = {}

        def font_files():
            return {p.relative_to(work).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((work / "assets/fonts/cjk-serif").rglob("*")) if p.is_file()}

        def tool_text(body, call_id):
            message = next((m for m in reversed(body["messages"])
                            if m.get("role") == "tool" and m.get("tool_call_id") == call_id), {})
            value = message.get("content", "")
            return value if isinstance(value, str) else "".join(text_values(value))

        def respond(event, calls):
            ordinal = len(calls)
            fn, arguments = None, None
            if ordinal == 1:
                fn, arguments = "cover_write", {"path": "index.html", "text": authored}
            elif ordinal == 2:
                fn, arguments = "cover_check", {"action": "font_add", "html": "index.html",
                                                "font_id": "cjk-serif", "css_var": "--font-title"}
            elif ordinal == 3:
                data = (work / "index.html").read_bytes()
                saved.update(before=data, faces=faces.findall(data.decode()), font_files=font_files())
                observed.update(installed_html_bytes=len(data), installed_faces=len(saved["faces"]),
                                font_add_tool_text=tool_text(event["body"], "managed-font-call-2"))
                fn, arguments = "cover_read", {"path": "index.html"}
            elif ordinal == 4:
                raw = tool_text(event["body"], "managed-font-call-3")
                view = json.loads(raw)
                observed.update(first_read_bytes=len(raw.encode()), first_view=view,
                    physical_file_unchanged_by_read=(work / "index.html").read_bytes() == saved["before"])
                # Drop only the tool-owned kit declaration and managed faces;
                # retain the explicit role, every authored style and whole DOM.
                saved["edited"] = kit.sub("", view["text"]).replace("#242421", "#303030", 1).replace(original_text, edited_text, 1)
                fn, arguments = "cover_write", {"path": "index.html", "text": saved["edited"]}
            elif ordinal == 5:
                after = (work / "index.html").read_bytes(); saved["after"] = after
                observed.update(edited_html_bytes=len(after), font_files_unchanged=font_files() == saved["font_files"],
                    managed_faces_unchanged=faces.findall(after.decode()) == saved["faces"],
                    kit_definition_restored=bool(kit.search(after.decode())),
                    transformed_write_receipt=json.loads(tool_text(event["body"], "managed-font-call-4")))
                fn, arguments = "cover_read", {"path": "index.html"}
            elif ordinal == 6:
                observed["second_view"] = json.loads(tool_text(event["body"], "managed-font-call-5"))
                saved["unknown_face"] = saved["faces"][0].replace("Noto Serif SC Variable", "UNKNOWN_SYNTHETIC_FONT", 1)
                self.assertNotEqual(saved["unknown_face"], saved["faces"][0])
                saved["snapshot"] = ("<html><head><style>" + saved["faces"][0] + saved["unknown_face"]
                    + ":root{--font-title:explicit-role-sentinel;}</style></head>"
                    "<body>SNAPSHOT_KNOWN_AND_UNKNOWN_DOM_TAIL</body></html>")
                fn, arguments = "cover_write", {"path": "snapshot.html", "text": saved["snapshot"]}
            elif ordinal == 7:
                fn, arguments = "cover_read", {"path": "snapshot.html"}
            elif ordinal == 8:
                raw = tool_text(event["body"], "managed-font-call-7")
                observed["snapshot_read"] = raw
                fn, arguments = "cover_write", {"path": "notes.txt", "text": "普通文件逐字原文。\n"}
            elif ordinal == 9:
                fn, arguments = "cover_read", {"path": "notes.txt"}
            elif ordinal == 10:
                observed["ordinary_read"] = tool_text(event["body"], "managed-font-call-9")
                fn, arguments = "cover_render", {"request": {"project_dir": ".",
                    "sources": [{"ref": "synthetic-source", "path": "assets/synthetic-photo.png",
                                 "sha256": hashlib.sha256(photo_bytes).hexdigest()}],
                    "text_layers": [{"id": "headline", "allowed_rect": {"x": 100, "y": 100, "width": 1576, "height": 380}}],
                    "protected_regions": []}}
            elif ordinal == 11:
                rendered = json.loads(tool_text(event["body"], "managed-font-call-10"))
                observed["render_result"] = rendered
                if rendered.get("ok"):
                    fn, arguments = "cover_view", {"path": rendered["image_path"]}
            message = {"role": "assistant", "content": "OFFLINE_FONT_EDIT_COMPLETE" if fn is None else None}
            if fn:
                message["tool_calls"] = [{"id": "managed-font-call-" + str(ordinal), "type": "function",
                    "function": {"name": fn, "arguments": json.dumps(arguments, ensure_ascii=False)}}]
            return {"type": "model_response", "id": event["id"], "status": 200, "body": {
                "id": "chatcmpl_managed_font_fixture", "object": "chat.completion", "created": 1,
                "model": event["body"]["model"], "choices": [{"index": 0, "message": message,
                    "finish_reason": "tool_calls" if fn else "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}}

        def tool_respond(event):
            self.assertEqual(event["name"], "cover_render")
            return {"allowed": True, "approved_titles": [edited_text]}

        result, calls, _, root = self.request(case, respond=respond, tool_respond=tool_respond)
        (root / "managed-font-observations.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2))
        self.assertTrue(result["ok"], result)
        self.assertGreater(observed["installed_html_bytes"], 50 * 1024)
        self.assertEqual(observed["installed_faces"], 101)
        self.assertTrue(observed["physical_file_unchanged_by_read"])
        self.assertTrue(observed["kit_definition_restored"], "Successful font_add's own kit declaration was lost during authored rewrite")
        self.assertTrue(observed["font_files_unchanged"])
        self.assertTrue(observed["managed_faces_unchanged"])
        self.assertTrue(any(p.endswith("/LICENSE.txt") for p in saved["font_files"]))
        self.assertTrue(any(p.endswith(".woff2") for p in saved["font_files"]))
        view = observed["first_view"]
        self.assertEqual(view["view"], "authored_html_with_managed_font_faces_elided")
        self.assertEqual((view["path"], view["bytes"], view["sha256"]),
                         ("index.html", len(saved["before"]), hashlib.sha256(saved["before"]).hexdigest()))
        self.assertEqual(view["omitted_font_faces"], 101)
        self.assertEqual(view["text"], faces.sub("", saved["before"].decode()))
        self.assertEqual(observed["second_view"]["text"], faces.sub("", saved["after"].decode()))
        self.assertEqual(observed["second_view"]["sha256"], hashlib.sha256(saved["after"]).hexdigest())
        self.assertEqual(re.search(r"<body>[\s\S]*</body>", saved["after"].decode())[0],
                         re.search(r"<body>[\s\S]*</body>", saved["edited"])[0])
        self.assertIn("#303030", saved["after"].decode())
        self.assertRegex(saved["after"].decode(), r"--font-title\s*:\s*var\(--font-kit-cjk-serif\)")
        snapshot = json.loads(observed["snapshot_read"])
        self.assertEqual(snapshot["omitted_font_faces"], 1)
        self.assertNotIn(saved["faces"][0], snapshot["text"])
        self.assertIn(saved["unknown_face"], snapshot["text"])
        snapshot_bytes = (work / "snapshot.html").read_bytes()
        self.assertEqual(snapshot["sha256"], hashlib.sha256(snapshot_bytes).hexdigest())
        self.assertIn("SNAPSHOT_KNOWN_AND_UNKNOWN_DOM_TAIL", snapshot["text"])
        self.assertIn("--font-title:explicit-role-sentinel;", snapshot["text"])
        self.assertEqual(observed["ordinary_read"], "普通文件逐字原文。\n")
        self.assertTrue(observed["render_result"]["ok"], observed["render_result"])
        rendered = observed["render_result"]
        png = work / rendered["image_path"]; thumb = work / rendered["thumbnail_path"]
        with Image.open(png) as image:self.assertEqual(image.size, (1776, 2368));image.verify()
        with Image.open(thumb) as image:self.assertEqual(image.size, (240, 320));image.verify()
        manifest = json.loads((work / rendered["manifest_path"]).read_text())
        self.assertEqual(manifest["checks"]["boxes"][0]["text"], edited_text)
        self.assertEqual((manifest["model_calls"], manifest["checks"]["screenshot"]["external_requests"]), (0, 0))
        self.assertEqual(photo.read_bytes(), photo_bytes)
        self.assertEqual(len(calls), 12)

    def test_real_sdk_transformed_font_write_compacts_by_input_and_stored_hashes(self):
        case = "font_transformed_compaction"
        admission = provider_admission()
        thinking = ThinkingState(case)
        work = self.root / case / "work"
        observed = {"synthetic_fixture": True, "external_provider_calls": 0}
        state = {"primary": 0, "compactions": 0, "continued": 0}
        marker = "TRANSFORMED_WRITE_INPUT_SENTINEL"
        authored = ("<html><head><style>:root{--font-title:serif;}"
                    "#canvas{position:relative;width:1776px;height:2368px}"
                    ".title{font-family:var(--font-title)}</style></head><body>"
                    "<div id=\"canvas\" data-canvas-width=\"1776\" data-canvas-height=\"2368\">"
                    "<div class=\"title\" data-layer-id=\"title\">城市里的日式庭院</div>"
                    "<!--FONT_COMPACTION_BASE_DOM--></div></body></html>")
        paragraph = "离线设计说明，保留真实照片与批准标题，不增添商家事实。\n"
        rewritten = {}

        def tool_text(body, call_id):
            row = next((m for m in body["messages"]
                        if m.get("role") == "tool" and m.get("tool_call_id") == call_id), {})
            value = row.get("content", "")
            return value if isinstance(value, str) else "".join(text_values(value))

        def respond(event, calls):
            fn, arguments = None, None
            if event.get("label") == "compaction":
                state["compactions"] += 1
                content = ("## Objective\n- Finish the offline font fixture.\n"
                    "## Requirements\n- Preserve approved title and original photos.\n"
                    "## Decisions\n- Installed faces belong to the font kit.\n"
                    "## Work State\n### Completed\n- Saved index.html and notes.\n"
                    "### Active\n- View source-1.png.\n### Blocked\n- (none)\n"
                    "## Next Move\n1. View source-1.png and finish.\n"
                    "## Relevant Files\n- index.html: complete authored design.\n"
                    "## Important Context\n- Synthetic provider-free fixture.")
            elif state["compactions"]:
                state["continued"] += 1
                content = "OFFLINE_FONT_COMPACTION_COMPLETE"
                if state["continued"] == 1:
                    fn, arguments = "cover_view", {"path": "source-1.png"};content = None
            else:
                state["primary"] += 1
                n = state["primary"];self.assertLessEqual(n, 20, "Real input meter never reached overflow")
                content = None
                if n == 1:
                    fn, arguments = "cover_write", {"path": "index.html", "text": authored}
                elif n == 2:
                    fn, arguments = "cover_check", {"action": "font_add", "html": "index.html",
                        "font_id": "cjk-serif", "css_var": "--font-title"}
                elif n == 3:
                    fn, arguments = "cover_read", {"path": "index.html"}
                elif n == 4:
                    view = json.loads(tool_text(event["body"], "font-compact-3"))
                    rewritten["text"] = re.sub(r"--font-kit-cjk-serif\s*:[^;{}]+;?", "", view["text"])
                    rewritten["text"] = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", rewritten["text"])
                    rewritten["text"] = rewritten["text"].replace("</body>", "<!--" + marker + "--></body>")
                    fn, arguments = "cover_write", {"path": "index.html", "text": rewritten["text"]}
                else:
                    if n == 5:
                        observed["transformed_receipt"] = json.loads(tool_text(event["body"], "font-compact-4"))
                        data = (work / "index.html").read_bytes()
                        observed["stored_html_bytes"] = len(data)
                        observed["stored_html_sha256"] = hashlib.sha256(data).hexdigest()
                        observed["input_bytes"] = len(rewritten["text"].encode())
                        observed["input_sha256"] = hashlib.sha256(rewritten["text"].encode()).hexdigest()
                    fn, arguments = "cover_write", {"path": "long-step-" + str(n) + ".md",
                        "text": paragraph * 160}
            message = {"role": "assistant", "content": content}
            if fn:
                message["tool_calls"] = [{"id": "font-compact-" + str(len(calls)), "type": "function",
                    "function": {"name": fn, "arguments": json.dumps(arguments, ensure_ascii=False)}}]
            return {"type": "model_response", "id": event["id"], "status": 200, "body": {
                "id": "chatcmpl_font_compaction_fixture", "object": "chat.completion", "created": 1,
                "model": event["body"]["model"], "choices": [{"index": 0, "message": message,
                    "finish_reason": "tool_calls" if fn else "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}}

        replying, originals, ciphers = self.opaque_responder(respond, prefix="font_transform")
        result, calls, events, root = self.request(case, admission=admission, respond=replying,
            nine_photos=True, thinking=thinking)
        summaries = [call for call in calls if call.get("label") == "compaction"]
        observed["summary_count"] = len(summaries)
        if summaries:
            material = "\n".join(text_values(summaries[0]["body"]))
            observed["rewritten_input_ref_collapsed"] = marker not in material
            observed["input_and_stored_reference_present"] = ("index.html" in material
                and observed["input_sha256"] in material and observed["stored_html_sha256"] in material)
        (root / "font-transform-observations.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2))
        self.assertTrue(result["ok"], result)
        receipt = observed["transformed_receipt"]
        self.assertEqual(set(receipt), {"path", "bytes", "sha256", "input_bytes", "input_sha256"})
        self.assertEqual((receipt["input_bytes"], receipt["input_sha256"]),
                         (observed["input_bytes"], observed["input_sha256"]))
        self.assertEqual((receipt["bytes"], receipt["sha256"]),
                         (observed["stored_html_bytes"], observed["stored_html_sha256"]))
        self.assertGreater(receipt["bytes"], receipt["input_bytes"] + 50 * 1024)
        self.assertEqual(len(summaries), 1)
        self.assertTrue(observed["rewritten_input_ref_collapsed"], "Automatically expanded successful write stayed in summary text")
        self.assertTrue(observed["input_and_stored_reference_present"])
        summary_index = calls.index(summaries[0])
        skill = (PROJECT / "model/cover_editable/vendor/editable-design/SKILL.md").read_text()
        for call in calls[summary_index + 1:]:
            material = "\n".join(text_values(call["body"]))
            self.assertIn(skill, material)
            self.assertIn("批准事实：真实庭院；批准标题：城市里的日式庭院。不得增加价格或服务。", material)
        self.assertTrue(any(event["type"] == "model_preflight" and
            admission["admit_payload"](thinking.restore(event["body"]))["allowed"] is False for event in events))
        for call in calls:
            self.assertLessEqual(admission["prepare_payload"](thinking.restore(call["body"]))[1], 131072)
        responses = json.loads((root / "run-success-responses.json").read_text())
        expected = {}
        for response in responses:
            for choice in response.get("body", {}).get("choices", []):
                for tool in choice["message"].get("tool_calls", []):
                    if tool["function"]["name"] != "cover_write":continue
                    args = json.loads(tool["function"]["arguments"])
                    expected.setdefault(tool["id"], {"id": tool["id"], "path": args["path"],
                        "bytes": len(args["text"].encode()), "sha256": hashlib.sha256(args["text"].encode()).hexdigest()})
        stored = {row["id"]: row for row in self.stored_write_receipts(root, result["session_id"])}
        self.assertEqual(stored, expected, "Compaction changed original synthetic SDK write arguments")
        visible = json.dumps(events) + (root / "run-success-responses.json").read_text()
        for cipher in ciphers:self.assertNotIn(cipher, visible)
        checkpoint = json.loads((root / "state/host-checkpoint.json").read_text())
        self.assertEqual(checkpoint["compaction_requests"], 1)
        self.assertIsNone(checkpoint.get("pending_request"))

    def test_explicit_revision_continues_only_known_original_session_once(self):
        first, _, _, _ = self.request("revision")
        self.assertTrue(first["ok"], first)
        result, calls, _, _ = self.request("revision", mode="revise", session_id=first["session_id"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["session_id"], first["session_id"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["ordinal"], 4)
        again, calls, _, _ = self.request("revision", mode="revise", session_id=first["session_id"])
        self.assertFalse(again["ok"])
        self.assertEqual(again["code"], "REVISION_REQUIRES_KNOWN_COMPLETE_SESSION")
        self.assertEqual(calls, [])
        reopened, calls, _, _ = self.request("revision", mode="inspect")
        self.assertTrue(reopened["ok"], reopened)
        self.assertEqual(calls, [])

    def test_503_vetoes_automatic_retry(self):
        result, calls, events, _ = self.request("failure", behavior="503")
        self.assertFalse(result["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len([event for event in events if event["type"] == "retry_veto"]), 1)

    def test_active_html_cannot_reach_browser_tools(self):
        result, calls, _, root = self.request("unsafe", behavior="unsafe_html")
        self.assertTrue(result["ok"], result)
        self.assertFalse((root / "work/unsafe.html").exists())
        self.assertTrue("ACTIVE_HTML_FORBIDDEN" in json.dumps(calls[1]["body"]), "Unsafe markup was not refused")

    def test_internal_and_hidden_paths_are_not_agent_writable(self):
        for index, forbidden in enumerate(["noteai-input.json", "host-session.json", "host-state/host-checkpoint.json", ".hidden/design.json", "project/.state.json", "qc-0.json"]):
            with self.subTest(path=forbidden):
                result, calls, _, _ = self.request("internal" + str(index), forbidden_path=forbidden)
                self.assertTrue(result["ok"], result)
                self.assertTrue("INTERNAL_PATH_FORBIDDEN" in json.dumps(calls[1]["body"]), "Internal write not refused: " + forbidden)

    def test_physical_limit_applies_before_second_bridge_dispatch(self):
        result, calls, _, _ = self.request("cap", limit=1)
        self.assertFalse(result["ok"])
        self.assertEqual(len(calls), 1)

    def test_unknown_persists_and_reopen_never_replays(self):
        result, calls, _, _ = self.request("unknown", behavior="unknown")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        reopened, dispatched, _, _ = self.request("unknown", mode="inspect")
        self.assertFalse(reopened["ok"])
        self.assertEqual(reopened["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(dispatched, [])

    def test_bridge_disconnect_retains_original_pending_request(self):
        result, calls, _, _ = self.request("disconnect", behavior="disconnect")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        reopened, calls, _, _ = self.request("disconnect", mode="inspect")
        self.assertEqual(reopened["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(calls, [])

    def context_responder(self, *, malformed_summary=False, view_before_compaction=False):
        state = {"primary": 0, "compactions": 0, "viewed_after_compaction": False}
        paragraph = "离线设计说明，保留真实照片与批准标题，不增添商家事实。\n"

        def respond(event, calls):
            label = event.get("label")
            fn, arguments = None, None
            if label == "compaction":
                state["compactions"] += 1
                content = "NOT_A_STRUCTURED_SUMMARY" if malformed_summary else (
                    "## Objective\n- Continue the offline cover fixture.\n"
                    "## Requirements\n- Preserve approved facts, title and original files.\n"
                    "## Decisions\n- No generated photos are deliverable.\n"
                    "## Work State\n### Completed\n- Wrote local design notes.\n"
                    "### Active\n- Inspect the original photo and finish.\n"
                    "### Blocked\n- (none)\n## Next Move\n1. View source-1.png.\n"
                    "## Relevant Files\n- source-1.png: original pixels.\n"
                    "## Important Context\n- This is a synthetic, provider-free fixture.")
            elif state["compactions"]:
                if not state["viewed_after_compaction"]:
                    state["viewed_after_compaction"] = True
                    fn, arguments = "cover_view", {"path": "source-1.png"}
                    content = None
                else:
                    content = "OFFLINE_COMPLETE"
            else:
                state["primary"] += 1
                self.assertLessEqual(state["primary"], 16, "Long SDK transcript never exercised the real input bound")
                if view_before_compaction and state["primary"] == 1:
                    fn, arguments = "cover_view", {"path": "source-2.png"}
                else:
                    fn, arguments = "cover_write", {"path": "design-step-" + str(state["primary"]) + ".md",
                                                     "text": paragraph * 160}
                content = None
            message = {"role": "assistant", "content": content}
            if fn:
                message["tool_calls"] = [{"id": "context_call_" + str(len(calls)), "type": "function",
                                          "function": {"name": fn, "arguments": json.dumps(arguments, ensure_ascii=False)}}]
            body = {"id": "chatcmpl_context_fixture", "object": "chat.completion", "created": 1,
                    "model": event["body"]["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if fn else "stop"}],
                    "usage": {"prompt_tokens": max(1, sum(len(t) for t in text_values(event["body"])) // 4
                                                      + 1500 * len(image_hashes(event["body"]))),
                              "completion_tokens": 2000 if fn == "cover_write" else 100}}
            body["usage"]["total_tokens"] = body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
            return {"type": "model_response", "id": event["id"], "status": 200, "body": body}

        return respond

    def stored_write_receipts(self, root, session_id):
        # Read only this test's own synthetic session through the public SDK.
        # No direct SQLite access, provider transport, or live application state.
        script = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
const [modules, root, sessionID] = process.argv.slice(1);
globalThis.fetch = async () => { throw new Error('OFFLINE_HISTORY_FORBIDS_NETWORK'); };
const load = (name) => import(pathToFileURL(path.join(modules, name)).href);
const { create } = await load('@opencode/sdk/dist/promise.js');
const { Global } = await load('@opencode/util/dist/global.js');
const { Config } = await load('@opencode/core/dist/config.js');
const home = path.join(root, 'state', 'isolated');
const cfg = { project: false, global: false, system: false, claude: false,
  content: JSON.stringify({ providers: {}, skills: [], update: 'disable' }) };
const sdk = await create({ config: cfg, database: { path: path.join(root, 'state/session.sqlite') },
  models: { fetch: false, snapshot: false }, fs: { filewatcher: false, fff: false }, log: { level: 'error' } },
  { overrides: [Global.node.replace(Global.layerWith({ home, data: path.join(home, 'data'),
    config: path.join(home, 'config'), cache: path.join(home, 'cache'), state: path.join(home, 'state'),
    tmp: path.join(home, 'tmp'), bin: path.join(home, 'bin'), log: path.join(home, 'log'),
    repos: path.join(home, 'repos') })), Config.node.replace(Config.configured(cfg))] });
try {
  const { messages: context } = await sdk.sessions.export({ sessionID, sanitize: false });
  const writes = context.flatMap((message) => message.type === 'assistant' ? (message.content || []) : [])
    .filter((part) => part.type === 'tool' && part.name === 'cover_write' && typeof part.state?.input?.text === 'string')
    .map((part) => ({ id: part.id, path: part.state.input.path, bytes: Buffer.byteLength(part.state.input.text),
      sha256: createHash('sha256').update(part.state.input.text).digest('hex') }));
  console.log(JSON.stringify({ writes, opaque_present: JSON.stringify(context).includes('TEST_OPAQUE_COVER_') }));
} finally { await sdk.close(); }
"""
        env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "HOME": str(root / "state/isolated"),
               "OPENCODE_TEST_HOME": str(root / "state/isolated"), "OPENCODE_DISABLE_FREE_MODELS": "true"}
        checked = subprocess.run([self.node, "--input-type=module", "-e", script,
                                  self.modules, str(root), session_id], env=env,
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stderr[-2000:])
        exported = json.loads(checked.stdout)
        self.assertFalse(exported["opaque_present"], "Opaque thinking leaked into public SDK export")
        receipts = exported["writes"]
        (root / "stored-original-write-receipts.json").write_text(json.dumps(receipts, indent=2))
        return receipts

    def opaque_responder(self, responder, *, prefix, empty_at=()):
        originals, ciphers = [], []

        def respond(event, calls):
            for message in event["body"]["messages"]:
                if message["role"] == "assistant":
                    self.assertIn(message, originals, "Supplier replay changed the original signed assistant message")
            answer = responder(event, calls)
            if answer.get("status") == 200:
                message = answer["body"]["choices"][0]["message"]
                message["reasoning_content"] = "合成思考摘要，不是加密原文"
                message["encrypted_content"] = ("" if len(calls) in empty_at else
                    "TEST_OPAQUE_COVER_" + prefix + "_" + str(len(calls)))
                originals.append(deepcopy(message)); ciphers.append(message["encrypted_content"])
            return answer

        return respond, originals, ciphers

    def assert_no_sdk_cipher(self, result, events, root, ciphers, *, mode="run"):
        visible = json.dumps(events) + (root / (mode + "-success-responses.json")).read_text()
        visible += (root / (mode + "-success-stderr.txt")).read_text()
        visible += (root / "state/host-checkpoint.json").read_text()
        self.assertTrue(ciphers)
        for cipher in ciphers:
            if cipher:
                self.assertNotIn(cipher, visible)
        self.stored_write_receipts(root, result["session_id"])

    def test_real_sdk_empty_encrypted_turn_keeps_exact_history_and_compacts(self):
        respond, originals, ciphers = self.opaque_responder(
            self.context_responder(view_before_compaction=True), prefix="empty", empty_at=(2,))
        result, calls, events, root = self.request("empty_context", admission=provider_admission(),
            respond=respond, nine_photos=True, thinking=ThinkingState("empty_context"))
        self.assertTrue(result["ok"], result)
        supplier = json.loads((root / "run-success-synthetic-supplier-bodies.json").read_text())
        replayed = [message for body in supplier for message in body["messages"]
                    if message["role"] == "assistant" and "encrypted_content" in message]
        self.assertTrue(any(message["encrypted_content"] == "" for message in replayed))
        self.assertTrue(any(message["encrypted_content"] for message in replayed))
        self.assertTrue(all(message in originals for message in replayed))
        self.assertEqual(sum(call.get("label") == "compaction" for call in calls), 1)
        responses = json.loads((root / "run-success-responses.json").read_text())
        self.assertTrue(all("encrypted_content" not in response["body"]["choices"][0]["message"]
                            for response in responses))
        self.assert_no_sdk_cipher(result, events, root, ciphers)

    def test_real_sdk_opaque_replay_and_fresh_summary_keep_original_state(self):
        admission = provider_admission()
        thinking = ThinkingState("opaque_context")
        respond, originals, ciphers = self.opaque_responder(
            self.context_responder(view_before_compaction=True), prefix="context")
        result, calls, events, root = self.request("opaque_context", admission=admission,
            respond=respond, nine_photos=True, thinking=thinking)
        self.assertTrue(result["ok"], result)
        supplier = json.loads((root / "run-success-synthetic-supplier-bodies.json").read_text())
        self.assertTrue(any(message.get("encrypted_content") for body in supplier
                            for message in body["messages"] if message["role"] == "assistant"))
        summaries = [body for body, call in zip(supplier, calls) if call.get("label") == "compaction"]
        self.assertEqual(len(summaries), 1)
        self.assertTrue(all(message["role"] in {"system", "user"} for message in summaries[0]["messages"]))
        self.assertEqual(summaries[0].get("max_tokens", summaries[0].get("max_completion_tokens")), 8192)
        summary_text = "\n".join(text_values(summaries[0]))
        self.assertIn("Previously viewed image; retrieve the original file with cover_view", summary_text)
        self.assertIn(hashlib.sha256((root / "work/source-2.png").read_bytes()).hexdigest(), summary_text)
        self.assertNotIn("data:image/", summary_text, "Summary serialized tool image bytes into text")
        self.assert_no_sdk_cipher(result, events, root, ciphers)

    def test_real_sdk_same_python_memory_replays_across_two_hosts(self):
        thinking = ThinkingState("opaque_revision")
        originals, ciphers = [], []

        def reply(phase):
            def respond(event, calls):
                for message in event["body"]["messages"]:
                    if message["role"] == "assistant":
                        self.assertIn(message, originals)
                ordinal = len(calls)
                message = {"role": "assistant", "content": "COMPLETE_" + phase}
                if ordinal == 1:
                    message["content"] = ""
                    message["tool_calls"] = [{"id": "call_" + phase, "type": "function", "function": {
                        "name": "cover_write", "arguments": '{ "text" : "真实中文与参数 1", "path" : "' + phase + '.md" }'}}]
                message["encrypted_content"] = "TEST_OPAQUE_COVER_" + phase + "_" + str(ordinal)
                originals.append(deepcopy(message)); ciphers.append(message["encrypted_content"])
                return {"type": "model_response", "id": event["id"], "status": 200, "body": {
                    "id": "fixture", "object": "chat.completion", "created": 1, "model": event["body"]["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if ordinal == 1 else "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}}
            return respond

        first, calls, events, root = self.request("opaque_revision", respond=reply("first"), thinking=thinking)
        self.assertTrue(first["ok"], first)
        self.assertEqual(len(calls), 2)
        self.assert_no_sdk_cipher(first, events, root, ciphers)
        count_before = thinking.entry_count
        revised, next_calls, next_events, _ = self.request("opaque_revision", mode="revise",
            session_id=first["session_id"], respond=reply("revised"), thinking=thinking)
        self.assertTrue(revised["ok"], revised)
        self.assertEqual(len(next_calls), 2)
        self.assertGreater(thinking.entry_count, count_before)
        self.assertEqual(revised["session_id"], first["session_id"])
        self.assert_no_sdk_cipher(revised, next_events, root, ciphers, mode="revise")

    def test_real_sdk_opaque_memory_does_not_replay_unknown_response(self):
        thinking = ThinkingState("opaque_unknown")

        def respond(event, calls):
            if len(calls) > 1:
                return {"type": "model_response", "id": event["id"], "unknown": True}
            return {"type": "model_response", "id": event["id"], "status": 200, "body": {
                "id": "fixture", "object": "chat.completion", "created": 1, "model": event["body"]["model"],
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                    "encrypted_content": "TEST_OPAQUE_COVER_unknown_1", "tool_calls": [{"id": "unknown_first", "type": "function",
                        "function": {"name": "cover_write", "arguments": '{"path":"known.md","text":"known before unknown"}'}}]}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}}

        result, calls, events, _ = self.request("opaque_unknown", respond=respond, thinking=thinking)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 2)
        self.assertEqual(thinking.entry_count, 1)
        self.assertFalse(any(call.get("label") == "compaction" for call in calls))
        inspected, new_calls, _, _ = self.request("opaque_unknown", mode="inspect", thinking=thinking)
        self.assertEqual(inspected["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(new_calls, [])

    def test_real_sdk_nine_photos_compacts_before_local_input_bound_without_supplier(self):
        admission = provider_admission()
        result, calls, events, root = self.request("context_bound", admission=admission,
            respond=self.context_responder(), nine_photos=True)
        self.assertTrue(result["ok"], {"status": result.get("status"), "errors": [
            entry["error"] for entry in result.get("context", []) if entry.get("error")]})
        rejections = [event for event in events if event["type"] == "model_preflight"]
        measured = [admission["admit_payload"](event["body"]) for event in rejections]
        rejected = [value for value in measured if value["allowed"] is False]
        self.assertTrue(rejected, "Actual SDK never reached the unchanged real provider bound")
        self.assertTrue(all(value["code"] == "COVER_AGENT_INPUT_LIMIT_EXCEEDED"
                            and value["measurement"]["total_bound"] > admission["MAX_INPUT_TOKENS"]
                            for value in rejected))
        compactions = [call for call in calls if call.get("label") == "compaction"]
        self.assertEqual(len(compactions), 1)
        self.assertEqual(compactions[0]["body"].get("max_tokens", compactions[0]["body"].get("max_completion_tokens")), 8192)
        self.assertTrue(all(message["role"] in {"system", "user"}
                            and not message.get("tool_calls") for message in compactions[0]["body"]["messages"]),
                        "Standalone summary reused active assistant/tool records")
        self.assertTrue(all(call["body"].get("max_tokens", call["body"].get("max_completion_tokens")) == 65536
                            for call in calls if call.get("label") == "primary"))
        compact_index = calls.index(compactions[0])
        continued = calls[compact_index + 1:]
        self.assertEqual(len(continued), 2, "Expected fresh original view then normal completion")
        skill = (PROJECT / "model/cover_editable/vendor/editable-design/SKILL.md").read_text()
        for call in continued:
            text = "\n".join(text_values(call["body"]))
            self.assertIn(skill, text, "Full fixed Skill did not survive SDK compaction")
            self.assertIn("批准事实：真实庭院；批准标题：城市里的日式庭院。不得增加价格或服务。", text)
            for index in range(1, 10):
                photo = root / ("work/source-" + str(index) + ".png")
                self.assertIn(photo.name, text)
                self.assertIn(hashlib.sha256(photo.read_bytes()).hexdigest(), text)
        original_hashes = {hashlib.sha256((root / ("work/source-" + str(index) + ".png")).read_bytes()).hexdigest()
                           for index in range(1, 10)}
        self.assertEqual(set(image_hashes(calls[0]["body"])), original_hashes)
        self.assertLess(len(image_hashes(continued[0]["body"])), 9, "Compaction reinserted all original image bytes")
        self.assertIn(hashlib.sha256((root / "work/source-1.png").read_bytes()).hexdigest(), image_hashes(continued[-1]["body"]))
        for call in calls:
            _, bound = admission["prepare_payload"](call["body"])
            self.assertLessEqual(bound, admission["MAX_INPUT_TOKENS"])
        checkpoint = json.loads((root / "state/host-checkpoint.json").read_text())
        self.assertEqual(checkpoint["model_requests"], len(calls))
        self.assertEqual(checkpoint["local_input_rejections"], len(rejected))
        self.assertEqual(checkpoint["compaction_requests"], 1)
        self.assertIsNone(checkpoint.get("pending_request"))
        responses = json.loads((root / "run-success-responses.json").read_text())
        original_writes = [tool for response in responses for choice in response.get("body", {}).get("choices", [])
                           for tool in choice["message"].get("tool_calls", [])
                           if tool["function"]["name"] == "cover_write"]
        expected = {}
        for tool in original_writes:
            arguments = json.loads(tool["function"]["arguments"])
            expected.setdefault(tool["id"], {"id": tool["id"], "path": arguments["path"],
                                             "bytes": len(arguments["text"].encode()),
                                             "sha256": hashlib.sha256(arguments["text"].encode()).hexdigest()})
        stored = {row["id"]: row for row in self.stored_write_receipts(root, result["session_id"])}
        self.assertTrue(expected)
        self.assertEqual(stored, expected, "Compaction mutated original session write text")
        for event in events:
            if event["type"] != "model_preflight" or event.get("label") != "primary":
                continue
            for message in event["body"]["messages"]:
                for tool in message.get("tool_calls", []):
                    if tool["id"] not in expected:
                        continue
                    arguments = json.loads(tool["function"]["arguments"])
                    self.assertEqual(hashlib.sha256(arguments["text"].encode()).hexdigest(),
                                     expected[tool["id"]]["sha256"], "UTF-8 primary replay changed original text")

    def test_real_sdk_unknown_nine_photo_result_never_compacts_or_replays(self):
        admission = provider_admission()
        result, calls, events, _ = self.request("context_unknown", admission=admission, nine_photos=True,
            respond=lambda event, _: {"type": "model_response", "id": event["id"], "unknown": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("label"), "primary")
        self.assertFalse(any(event["type"] == "model_preflight" and event.get("label") == "compaction" for event in events))
        reopened, calls, _, _ = self.request("context_unknown", mode="inspect")
        self.assertEqual(reopened["code"], "PREVIOUS_REQUEST_UNKNOWN_NO_REPLAY")
        self.assertEqual(calls, [])

    def test_real_sdk_two_summaries_each_consume_a_new_primary_overflow(self):
        admission = provider_admission()
        state = {"compactions": 0, "writes": [0, 0], "viewed": False, "tickets": [], "rejection_receipts": []}
        paragraph = "离线设计进度：保留真实原照、批准标题与已保存文件，不增添商家事实。\n"
        case = "two_primary_overflows"

        def respond(event, calls):
            label = event.get("label")
            fn, arguments = None, None
            if label == "compaction":
                state["compactions"] += 1
                self.assertLessEqual(state["compactions"], 2)
                checkpoint = json.loads((self.root / case / "state/host-checkpoint.json").read_text())
                state["tickets"].append(deepcopy(checkpoint.get("overflow_ticket")))
                state["rejection_receipts"].append({
                    "body_sha256": checkpoint["last_input_measurement"]["body_sha256"],
                    "requests_before_summary": checkpoint["model_requests"] - 1,
                    "compaction_ordinal": event["ordinal"],
                    "rejection_number": checkpoint["local_input_rejections"]})
                content = ("## Objective\n- Complete the same offline cover.\n"
                    "## Requirements\n- Keep the approved facts, title and original photographs.\n"
                    "## Decisions\n- Use only original photo pixels.\n"
                    "## Work State\n### Completed\n- Progress notes are saved in phase files.\n"
                    "### Active\n- Continue the saved design.\n### Blocked\n- (none)\n"
                    "## Next Move\n1. Continue from the saved phase notes.\n"
                    "## Relevant Files\n- phase-0-1.md and phase-1-1.md: saved design progress.\n"
                    "## Important Context\n- Synthetic, provider-free fixture; preserve original facts.\n"
                    "- Completed summary round " + str(state["compactions"]) + ".")
            elif state["compactions"] < 2:
                phase = state["compactions"]
                state["writes"][phase] += 1
                self.assertLessEqual(state["writes"][phase], 16, "Phase never reached the real local input bound")
                fn, arguments = "cover_write", {"path": "phase-" + str(phase) + "-"
                    + str(state["writes"][phase]) + ".md", "text": paragraph * 160}
                content = None
            elif not state["viewed"]:
                state["viewed"] = True
                fn, arguments, content = "cover_view", {"path": "source-1.png"}, None
            else:
                content = "OFFLINE_COMPLETE"
            message = {"role": "assistant", "content": content}
            if fn:
                message["tool_calls"] = [{"id": "two_overflows_" + str(len(calls)), "type": "function",
                    "function": {"name": fn, "arguments": json.dumps(arguments, ensure_ascii=False)}}]
            body = {"id": "chatcmpl_two_overflows", "object": "chat.completion", "created": 1,
                "model": event["body"]["model"], "choices": [{"index": 0, "message": message,
                    "finish_reason": "tool_calls" if fn else "stop"}], "usage": {
                    "prompt_tokens": max(1, sum(len(text) for text in text_values(event["body"])) // 4
                        + 1500 * len(image_hashes(event["body"]))),
                    "completion_tokens": 2000 if fn == "cover_write" else 100}}
            body["usage"]["total_tokens"] = body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
            return {"type": "model_response", "id": event["id"], "status": 200, "body": body}

        thinking = ThinkingState(case)
        response, originals, ciphers = self.opaque_responder(respond, prefix="two_overflows")
        result, calls, events, root = self.request(case, admission=admission,
            respond=response, nine_photos=True, thinking=thinking)
        self.assertTrue(result["ok"], {"code": result.get("code"), "status": result.get("status"),
            "compactions": state["compactions"]})
        self.assertEqual(state["compactions"], 2)
        self.assertTrue(all(state["writes"]))
        self.assertEqual([ticket["consumed"] for ticket in state["tickets"]], [True, True])
        compactions = [call for call in calls if call.get("label") == "compaction"]
        self.assertEqual(len(compactions), 2)
        rejected = []
        for event in events:
            if event["type"] != "model_preflight":
                continue
            decision = admission["admit_payload"](thinking.restore(event["body"]))
            if decision["allowed"] is False:
                self.assertEqual(event.get("label"), "primary", "A summary overflow minted a primary ticket")
                rejected.append(event)
        self.assertEqual(len(rejected), 2)
        for index, summary_call in enumerate(compactions):
            eligible = [event for event in rejected if events.index(event) < events.index(summary_call)]
            self.assertEqual(len(eligible), index + 1)
            rejection = eligible[-1]
            receipt = state["rejection_receipts"][index]
            self.assertEqual(receipt["body_sha256"], hashlib.sha256(json.dumps(
                rejection["body"], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
            self.assertEqual(receipt["requests_before_summary"], summary_call["ordinal"] - 1)
            self.assertEqual(receipt["compaction_ordinal"], summary_call["ordinal"])
            self.assertEqual(receipt["rejection_number"], index + 1)
            self.assertEqual(state["tickets"][index], {"body_sha256": receipt["body_sha256"],
                "request_ordinal": receipt["requests_before_summary"], "consumed": True})
            self.assertTrue(all(message["role"] in {"system", "user"}
                and not message.get("tool_calls") for message in summary_call["body"]["messages"]))
            self.assertEqual(summary_call["body"].get("max_tokens",
                summary_call["body"].get("max_completion_tokens")), 8192)
            self.assertLess(sum(len(text) for text in text_values(summary_call["body"])), 131072)
        skill = (PROJECT / "model/cover_editable/vendor/editable-design/SKILL.md").read_text()
        for call in calls:
            _, bound = admission["prepare_payload"](thinking.restore(call["body"]))
            self.assertLessEqual(bound, admission["MAX_INPUT_TOKENS"])
            if call.get("label") == "primary" and calls.index(call) > calls.index(compactions[0]):
                text = "\n".join(text_values(call["body"]))
                self.assertIn(skill, text)
                self.assertIn("批准事实：真实庭院；批准标题：城市里的日式庭院。不得增加价格或服务。", text)
                for index in range(1, 10):
                    photo = root / ("work/source-" + str(index) + ".png")
                    self.assertIn(photo.name, text)
                    self.assertIn(hashlib.sha256(photo.read_bytes()).hexdigest(), text)
        checkpoint = json.loads((root / "state/host-checkpoint.json").read_text())
        self.assertEqual(checkpoint["local_input_rejections"], 2)
        self.assertEqual(checkpoint["compaction_requests"], 2)
        self.assertEqual(checkpoint["overflow_ticket"], state["tickets"][-1])
        self.assertEqual(checkpoint["last_compacted_primary_sha256"], state["tickets"][-1]["body_sha256"])
        self.assertEqual(checkpoint["last_compaction_request_ordinal"], compactions[-1]["ordinal"])
        self.assertEqual(checkpoint["model_requests"], len(calls))
        self.assertIsNone(checkpoint.get("pending_request"))
        self.assertNotEqual(state["rejection_receipts"][0]["body_sha256"],
            state["rejection_receipts"][1]["body_sha256"])
        self.assertGreater(compactions[1]["ordinal"], compactions[0]["ordinal"] + 1,
            "Second summary had no successful primary progress after the first")
        (root / "two-summary-ticket-receipts.json").write_text(json.dumps(state["rejection_receipts"], indent=2))
        expected = {}
        for original in originals:
            for tool in original.get("tool_calls", []):
                if tool["function"]["name"] != "cover_write":
                    continue
                arguments = json.loads(tool["function"]["arguments"])
                expected[tool["id"]] = {"id": tool["id"], "path": arguments["path"],
                    "bytes": len(arguments["text"].encode()),
                    "sha256": hashlib.sha256(arguments["text"].encode()).hexdigest()}
        stored = {row["id"]: row for row in self.stored_write_receipts(root, result["session_id"])}
        self.assertEqual(stored, expected, "Summary projection mutated original signed write history")
        self.assert_no_sdk_cipher(result, events, root, ciphers)

    def test_compaction_tickets_allow_shrink_but_cannot_be_reused(self):
        script = r'''
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const source=fs.readFileSync(process.argv[1],'utf8');
const section=(start,end)=>{const a=source.indexOf(start),b=source.indexOf(end,a);
  assert(a>=0 && b>a);return source.slice(a,b);};
const helpers=section('function overflowTicket(', 'const RENDER_REJECTION_CODES');
const measure=section('function inputMeasurement(', 'const FAILURE_CODES');
const rejected=section('      if (admission.allowed !== true) {', '\n      requests += 1; physical = true;');
const admitted=section('      // Another HTTP request may have consumed the ticket while Python was',
  "\n      const answer = await bridge('model_request'");
const earlyGate=section("      if (label === 'compaction' && !compactionTicketAllowed(checkpoint, requests))",
  '\n      // Use the actual Python provider meter');
const persisted=[],responses=[];
const ctx=vm.createContext({Buffer,checkpointPath:'synthetic-only',
  sha:value=>createHash('sha256').update(value).digest('hex'),
  error:code=>Object.assign(new Error(code),{code}),
  atomicJSON:async(_path,value)=>persisted.push(JSON.parse(JSON.stringify(value))),
  res:{writeHead:status=>responses.push(status),end:()=>{}},requests:3,physical:false});
vm.runInContext(helpers+measure+'\nasync function rejectOnly(){'+rejected+'}\n'
  +'async function admitOnly(){'+admitted+'}\n'
  +'async function concurrentAdmission(waiter){'+earlyGate+'\nawait waiter;\n'+admitted+'}\n',ctx);
const A='a'.repeat(64),B='b'.repeat(64);
ctx.body={messages:[{role:'user',content:'X'.repeat(140000)}]};
const bytes=Buffer.byteLength(JSON.stringify(ctx.body));
ctx.admission={allowed:false,code:'COVER_AGENT_INPUT_LIMIT_EXCEEDED',measurement:{
  text_bytes:bytes,image_count:0,image_tokens:0,message_count:1,tool_count:0,
  framing_tokens:1152,total_bound:bytes+1152,max_input_tokens:131072}};
const minted=ctx.overflowTicket({},A,3);
ctx.checkpoint={compaction_requests:0,local_input_rejections:1,overflow_ticket:minted};
assert.equal(ctx.compactionTicketAllowed(ctx.checkpoint,3),true);
ctx.label='compaction';
await ctx.rejectOnly();
assert.equal(ctx.requests,3);assert.equal(ctx.physical,false);
assert.equal(ctx.checkpoint.compaction_requests,0);
assert.equal(ctx.checkpoint.local_input_rejections,2);
assert.equal(ctx.checkpoint.last_input_measurement.label,'compaction');
assert.equal(ctx.checkpoint.overflow_ticket,minted);assert.equal(minted.consumed,false);
assert.equal(ctx.compactionTicketAllowed(ctx.checkpoint,3),true,
  'A local summary shrink lost the unconsumed original primary ticket');
assert.equal(persisted.length,1);assert.deepEqual(responses,[400]);
ctx.body={messages:[{role:'user',content:'Shrunk standalone summary.'}]};
ctx.admission={allowed:true};
await ctx.admitOnly();
assert.equal(ctx.requests,4);assert.equal(ctx.checkpoint.compaction_requests,1);
assert.equal(ctx.checkpoint.overflow_ticket.consumed,true);
assert.equal(ctx.checkpoint.pending_request.ordinal,4);
assert.equal(persisted.length,2);assert.equal(persisted[1].overflow_ticket.consumed,true);
assert.equal(persisted[1].pending_request.ordinal,4,
  'Ticket was not consumed with the same durable request intent');
assert.equal(ctx.compactionTicketAllowed(ctx.checkpoint,4),false,'NUDGE reused the consumed ticket');
const first={compaction_requests:1,last_compacted_primary_sha256:A,
  last_compaction_request_ordinal:4,last_successful_primary_request:4,
  overflow_ticket:{body_sha256:A,request_ordinal:3,consumed:true}};
assert.equal(ctx.overflowTicket(first,B,7),null,'No known primary progress after summary');
const progressed={...first,last_successful_primary_request:7};
assert.equal(ctx.overflowTicket(progressed,A,7),null,'Same rejected body minted a second ticket');
const second=ctx.overflowTicket(progressed,B,7);
assert.equal(ctx.compactionTicketAllowed({...progressed,overflow_ticket:second},7),true);
assert.equal(ctx.compactionTicketAllowed({...progressed,overflow_ticket:second},8),false);
assert.equal(ctx.overflowTicket({...progressed,compaction_requests:2},'c'.repeat(64),9),null);
assert.equal(ctx.compactionTicketAllowed({...progressed,compaction_requests:2,overflow_ticket:second},7),false);
assert.equal(Boolean(ctx.compactionTicketAllowed({compaction_requests:1,local_input_rejections:2},7)),false);
assert.equal(ctx.overflowTicket({compaction_requests:1,local_input_rejections:2},B,7),null);
ctx.checkpoint={compaction_requests:0,local_input_rejections:0};ctx.requests=0;ctx.physical=false;
ctx.admission={allowed:false,code:'COVER_AGENT_INPUT_LIMIT_EXCEEDED',measurement:{
  text_bytes:bytes,image_count:0,image_tokens:0,message_count:1,tool_count:0,
  framing_tokens:1152,total_bound:bytes+1152,max_input_tokens:131072}};
await ctx.rejectOnly();
assert.equal(ctx.checkpoint.overflow_ticket,undefined,'Summary overflow created a primary ticket');
assert.equal(Boolean(ctx.compactionTicketAllowed(ctx.checkpoint,0)),false);
ctx.checkpoint={compaction_requests:0,overflow_ticket:ctx.overflowTicket({},A,3)};
ctx.requests=3;ctx.body={messages:[{role:'user',content:'Short concurrent summary.'}]};
let physicalTransitions=0,physicalValue=false;
Object.defineProperty(ctx,'physical',{configurable:true,get:()=>physicalValue,
  set:value=>{physicalValue=value;if(value===true)physicalTransitions++;}});
let firstReady,secondReady;
const firstWait=new Promise(resolve=>{firstReady=resolve;});
const secondWait=new Promise(resolve=>{secondReady=resolve;});
const beforeRace=persisted.length;
const firstCall=ctx.concurrentAdmission(firstWait),secondCall=ctx.concurrentAdmission(secondWait);
assert.equal(ctx.requests,3);firstReady();secondReady();
const results=await Promise.allSettled([firstCall,secondCall]);
assert.equal(results.filter(result=>result.status==='fulfilled').length,1);
assert.equal(results.filter(result=>result.status==='rejected'
  && result.reason.code==='COMPACTION_CONTINUATION_NOT_ALLOWED').length,1);
assert.equal(ctx.requests,4);assert.equal(ctx.checkpoint.compaction_requests,1);
assert.equal(persisted.length-beforeRace,1);assert.equal(physicalTransitions,1);
const unknown=source.indexOf("if (checkpoint.status === 'UNKNOWN' || checkpoint.pending_tool)");
const gate=source.indexOf("if (label === 'compaction' && !compactionTicketAllowed(checkpoint, requests))");
assert(unknown>=0 && unknown<gate,'Existing UNKNOWN server gate must run before ticket admission');
console.log(JSON.stringify({cases:['two_ticket_admission','summary_shrink_preserves_ticket',
  'same_intent_atomic_consume','NUDGE_consumed_ticket','no_primary_progress','same_body_SHA',
  'stale_request_ordinal','third_summary','old_checkpoint_missing_ticket','summary_cannot_mint',
  'concurrent_preflights_one_dispatch'],
  real_provider_calls:0,product_DB_operations:0,
  unknown_scope:'Static ordering of existing server gate only; pure helpers do not claim UNKNOWN runtime coverage.'}));
'''
        checked = subprocess.run([self.node, "--input-type=module", "-e", script, str(HERE / "host.mjs")],
            capture_output=True, text=True, timeout=10,
            env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin"})
        self.assertEqual(checked.returncode, 0, checked.stderr[-2000:])
        detail = json.loads(checked.stdout)
        self.assertEqual(len(detail["cases"]), 11)
        self.receipts.append({"case": "compaction_ticket_vm", "host_sha256":
            hashlib.sha256((HERE / "host.mjs").read_bytes()).hexdigest(), "result": detail})

    def test_real_sdk_malformed_summary_cannot_dispatch_a_second_paid_attempt(self):
        admission = provider_admission()
        result, calls, _, root = self.request("context_malformed", admission=admission,
            respond=self.context_responder(malformed_summary=True), nine_photos=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "FAILED")
        compactions = [call for call in calls if call.get("label") == "compaction"]
        self.assertEqual(len(compactions), 1, "SDK NUDGE generated another admitted model call")
        self.assertEqual(calls[-1], compactions[0])
        checkpoint = json.loads((root / "state/host-checkpoint.json").read_text())
        self.assertEqual(checkpoint["compaction_requests"], 1)
        self.assertIsNone(checkpoint.get("pending_request"))


if __name__ == "__main__":
    unittest.main()
