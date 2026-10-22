"""Real local SDK/tool/CLI integration with a scripted synthetic provider.

This deliberately does not exercise billing/UNKNOWN accounting (separate tests
own those). It calls no external model, uses no merchant photo and opens no DB.
Set NOTEAI_COVER_HOST_NODE_MODULES to the approved local SDK installation.
"""
import base64
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
        prepared, bound = provider.prepare_payload(payload)
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
        message = {"role": "assistant", "content": text}
        if calls:
            message["tool_calls"] = [{"id": "fixture_" + str(self.ordinal) + "_" + str(i),
                "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                for i, (name, args) in enumerate(calls)]
        return {"id": "chatcmpl-offline-runtime", "object": "chat.completion", "created": 1,
            "model": provider.MODEL, "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}

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
