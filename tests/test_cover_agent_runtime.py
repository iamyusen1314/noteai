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
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

from PIL import Image, ImageDraw

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


def returned_value(body, required):
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
        if message["role"] == "tool":
            value = find(message.get("content"))
            if value is not None:
                return value
    raise AssertionError("SDK did not expose expected tool field: " + required)


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
            calls = [("cover_render", {"request": {"project_dir": ".",
                "sources": [{"ref": source["media_ref"], "path": source["path"], "sha256": source["sha256"]}],
                "text_layers": [{"id": "title", "allowed_rect": {"x": 90, "y": 100, "width": 1600, "height": 350}}],
                "protected_regions": [{"x": 500, "y": 800, "width": 700, "height": 800}]}})]
        elif turn == 6:
            rendered = returned_value(prepared, "png_path")
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
            shutil.copytree(cls.root, target)
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

        try:
            with mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": str(self.root / "jobs")}), mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=fake_image) as image:
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
            edited = artifacts.cli("edit", {"schema_version": artifacts.SCHEMA,
                "output_root": str(self.root / "free-edit-revisions"),
                "parent_revision_dir": str(restored),
                "expected_parent_manifest_sha256": result.layout["manifest_sha256"],
                "initial_qc_ref": result.layout["initial_qc_ref"],
                "edits": [{"layer_id": "title", "text": "原照独立\n图层中文排字测试", "dx": 12, "dy": 8}]})
            adjusted_png, _, adjusted_layout = artifacts.capture(edited,
                expected_sources=result.layout["input_source_hashes"])
            self.assertNotEqual(adjusted_png, old_png)
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
