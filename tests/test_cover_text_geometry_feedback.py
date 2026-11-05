"""Real local text-box repair and SDK feedback; synthetic photo, no suppliers."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

import httpx
from PIL import Image

from tests import test_cover_agent_artifacts as artifact_tests
from tests import test_cover_agent_progress_feedback as progress_tests

runtime, provider = progress_tests.runtime, progress_tests.provider


class TextGeometryCLIContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = artifact_tests.AgentTitleCLIContractTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_fullwidth_leaf_rejected_despite_visible_range_then_leaf_only_repair_and_edit(self):
        fixture = self.fixture
        html_path = fixture.project / "index.html"
        html = html_path.read_text().replace('data-layer-id="title"', 'data-layer-id="title-a"')
        html = html.replace("原照独立图层<br>中文排字测试", "原照中文排字")
        old_css = ".title {position:absolute;left:120px;top:150px;width:1480px;height:260px;margin:0;font-family:var(--font-title);font-size:96px;line-height:1.18;font-weight:600;color:#203a34;white-space:pre-wrap}"
        wide_css = ".title {position:absolute;left:0px;top:226px;width:1776px;height:336px;margin:0;font-family:var(--font-title);font-size:210px;line-height:336px;font-weight:600;color:#203a34;white-space:pre-wrap;text-align:center}"
        self.assertIn(old_css, html)
        html = html.replace(old_css, wide_css)
        html_path.write_text(html)
        fixture.request["text_layers"] = [{"id": "title-a", "allowed_rect": {
            "x": 210, "y": 216, "width": 1380, "height": 360}}]
        fixture.request["approved_titles"] = ["原照中文排字"]
        unchanged = deepcopy(fixture.request)
        rejected = fixture.invoke("render", fixture.request,
            expected_code="TEXT_OVERFLOW_OR_OUTSIDE_ALLOWED_REGION")
        detail = json.loads(rejected["detail"])
        self.assertEqual(detail["id"], "title-a")
        self.assertEqual(detail["element_rect"], {"x": 0, "y": 226, "width": 1776, "height": 336})
        self.assertEqual(detail["allowed_rect"], unchanged["text_layers"][0]["allowed_rect"])
        self.assertFalse(detail["overflow"])
        self.assertGreater(len(detail["ink_rects"]), 0)
        for rect in detail["ink_rects"]:
            self.assertGreaterEqual(rect["x"], 210)
            self.assertLessEqual(rect["x"] + rect["width"], 1590)
            self.assertGreaterEqual(rect["y"], 216)
            self.assertLessEqual(rect["y"] + rect["height"], 576)
        self.assertEqual(list((fixture.directory / "revisions").glob("*/out/poster.png")), [])

        # The contract remains fixed. Only the leaf's CSS left/width changes.
        fixed_css = wide_css.replace("left:0px", "left:210px").replace("width:1776px", "width:1380px")
        html_path.write_text(html.replace(wide_css, fixed_css))
        self.assertEqual(fixture.request, unchanged)
        accepted = fixture.invoke("render", fixture.request)
        manifest = json.loads(Path(accepted["manifest_path"]).read_bytes())
        box = manifest["checks"]["boxes"][0]
        self.assertEqual(box["id"], "title-a")
        self.assertEqual(box["text"], "原照中文排字")
        self.assertFalse(box["overflow"])
        self.assertEqual(box["rect"], {"x": 210, "y": 226, "width": 1380, "height": 336})
        original_png = Path(accepted["png_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(original_png).hexdigest(), accepted["png_sha256"])
        self.assertEqual((fixture.project / "assets/synthetic-photo.png").read_bytes(), fixture.photo)
        expected_sources = {item["ref"]: item["sha256"] for item in fixture.request["sources"]}
        captured_png, bundle, original_layout = artifact_tests.artifacts.capture(accepted,
            expected_sources=expected_sources)
        self.assertEqual(captured_png, original_png)
        restored = artifact_tests.artifacts.restore(bundle, fixture.directory / "restored-bundle")
        self.assertEqual((restored / "assets/synthetic-photo.png").read_bytes(), fixture.photo)

        adjusted = fixture.invoke("edit", {"schema_version": fixture.request["schema_version"],
            "output_root": fixture.request["output_root"],
            "parent_revision_dir": str(restored),
            "expected_parent_manifest_sha256": accepted["manifest_sha256"],
            "edits": [{"layer_id": "title-a", "text": "原照排字", "dx": 0, "dy": 0}]})
        adjusted_manifest = json.loads(Path(adjusted["manifest_path"]).read_bytes())
        self.assertEqual(adjusted_manifest["constraints"], manifest["constraints"])
        self.assertEqual(adjusted_manifest["checks"]["boxes"][0]["text"], "原照排字")
        _, _, adjusted_layout = artifact_tests.artifacts.capture(adjusted, expected_sources=expected_sources)
        self.assertEqual(adjusted_layout["source_hashes"], original_layout["source_hashes"])
        self.assertEqual(adjusted_layout["qc_status"], "USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
        self.assertEqual(Path(accepted["png_path"]).read_bytes(), original_png)
        with Image.open(adjusted["png_path"]) as image:
            self.assertEqual(image.size, (1776, 2368))
        print("COVER_TEXT_GEOMETRY_CLI_PROOF=" + json.dumps({"real_cli_browser": True,
            "synthetic_photo": True, "wide_leaf_rejected": True, "range_inside_overflow_false": True,
            "only_leaf_left_width_changed": True, "allowed_protected_font_text_unchanged": True,
            "actual_png_and_edit": True, "supplier_calls": 0, "merchant_quality_acceptance": False}, sort_keys=True))


class TextGeometrySDKContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") or not shutil.which("node"):
            raise unittest.SkipTest("Explicit installed SDK and Node required")
        if not Path(os.environ.get("EDITABLE_DESIGN_BROWSER",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")).is_file():
            raise unittest.SkipTest("Actual local browser required")

    def test_actual_sdk_geometry_hint_recheck_and_success_clear_with_unchanged_tool_result(self):
        scope = progress_tests.budget_fixture.CoverVerificationBudgetTests()
        scope.setUp()
        self.addCleanup(scope.tearDown)
        scope.configure("100000")
        observed, wire, concepts, errors, checkpoints, transport_assertions = [], [], [], [], [], []
        actual_price = progress_tests.billing._pricing_snapshot
        concept = progress_tests.fixture.synthetic_png((48, 64), "#587961")
        title = "真实门店"
        html = progress_tests.fixture.ScriptedBridge.html("assets/source-1.png")
        html = html.replace("原照独立图层\n中文排字测试", title).replace('data-layer-id="title"', 'data-layer-id="title-a"')
        narrow = ".title {position:absolute;left:120px;top:150px;width:1480px;height:260px;margin:0;font-family:var(--font-title);font-size:96px;line-height:1.18;font-weight:600;color:var(--ink);white-space:pre-wrap}"
        wide = ".title {position:absolute;left:0px;top:226px;width:1776px;height:336px;margin:0;font-family:var(--font-title);font-size:210px;line-height:336px;font-weight:600;color:var(--ink);white-space:pre-wrap;text-align:center}"
        self.assertIn(narrow, html)
        html = html.replace(narrow, wide)
        request = {"project_dir": ".", "sources": [{"path": "assets/source-1.png"}],
            "text_layers": [{"id": "title-a", "allowed_rect": {"x": 210, "y": 216, "width": 1380, "height": 360}}],
            "protected_regions": [{"x": 500, "y": 800, "width": 700, "height": 800}]}
        rendered, rejection = {}, {}

        def price(source, model, *, prompt_tokens=0):
            if source == "doubao" and model == provider.MODEL:
                return {"currency": "RMB", "usd_cny": 7.0, "pricing_status": "exact",
                    "price_version": provider.PRICE_VERSION, "cache_write_5m": None,
                    "cache_write_1h": None, **provider.pricing(prompt_tokens)}
            return actual_price(source, model, prompt_tokens=prompt_tokens)

        def response(turn, calls):
            return {"id": "chatcmpl-offline-geometry-" + str(turn), "object": "chat.completion",
                "created": 1, "model": provider.MODEL, "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Synthetic geometry technical fixture.",
                        "encrypted_content": "TEST_OPAQUE_GEOMETRY_" + str(turn),
                        "tool_calls": [{"id": "geometry_" + str(turn) + "_" + str(index),
                            "type": "function", "function": {"name": name,
                                "arguments": json.dumps(args)}} for index, (name, args) in enumerate(calls)]},
                    "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30,
                    "prompt_tokens_details": {"cached_tokens": 20},
                    "completion_tokens_details": {"reasoning_tokens": 15}}}

        class WitnessBridge(runtime.Bridge):
            def model(inner, payload, stage="design"):
                observed.append(progress_tests.progress_from_payload(payload))
                return super().model(payload, stage=stage)

        def transport(http_request):
            payload = json.loads(http_request.content)
            wire.append(payload)
            turn = len(wire)
            feedback = progress_tests.progress_from_payload(payload)
            self.assertEqual(feedback, observed[-1])
            self.assertIs(feedback["independent_qc_pending"], True)
            self.assertNotIn("PRIVATE_", json.dumps(feedback))
            if turn == 1:
                calls = [("cover_seedream", {"prompt": "Synthetic nonshipping geometry reference; preserve original facts."})]
            elif turn == 2:
                calls = [("cover_view", {"path": "reference/composition-reference.png"}),
                    ("cover_write", {"path": "index.html", "text": html}),
                    ("cover_write", {"path": "poster.json", "text": json.dumps({"canvas": {"width": 1776, "height": 2368}, "scale": 1, "dpi": None})}),
                    ("cover_write", {"path": "brief.md", "text": "PRIVATE_PLAN_DO_NOT_PROJECT"}),
                    ("cover_write", {"path": "design-plan.md", "text": "Synthetic technical geometry, no merchant acceptance."})]
            elif turn == 3:
                calls = [("cover_check", {"action": "font_add", "html": "index.html", "font_id": "cjk-sans"})]
            elif turn == 4:
                font = progress_tests.fixture.returned_value(payload, "code", tool_call_id="geometry_3_0")
                self.assertEqual(font["code"], 0)
                calls = [("cover_render", {"request": request})]
            elif turn in (5, 6):
                raw = progress_tests.fixture.returned_value(payload, "code", tool_call_id="geometry_4_0") if turn == 5 else rejection
                hint = feedback.get("geometry_repair")
                self.assertIsNotNone(hint, "Actual SDK's next model request needs measured geometry guidance: "
                    + json.dumps({"feedback": feedback, "cli": raw}, ensure_ascii=False))
                self.assertEqual(feedback["stage"], "repair_text_geometry")
                self.assertEqual(hint["status"], "MEASURED_REJECTION")
                self.assertEqual(hint["code"], "TEXT_OVERFLOW_OR_OUTSIDE_ALLOWED_REGION")
                self.assertEqual(hint["layer_id"], "title-a")
                self.assertEqual(hint["violations"], ["ELEMENT_BOX_OUTSIDE_ALLOWED"])
                self.assertEqual(hint["element_outside_edges"], ["left", "right"])
                self.assertEqual(hint["range_outside_edges"], [])
                self.assertIs(hint["range_details_complete"], True)
                if turn == 5:
                    self.assertEqual(set(raw), {"ok", "schema_version", "code", "detail", "model_calls"})
                    self.assertFalse(raw["ok"])
                    self.assertEqual(raw["model_calls"], 0)
                    rejection.update(raw)
                    detail = json.loads(raw["detail"])
                    self.assertEqual(hint["geometry"], {key: detail[key] for key in (
                        "element_rect", "allowed_rect", "overflow", "ink_rects", "ink_rect_count")})
                    calls = [("cover_read", {"path": "index.html"})]
                else:
                    view = progress_tests.fixture.returned_value(payload, "text", tool_call_id="geometry_5_0")
                    self.assertIn(wide, view["text"])
                    fixed = view["text"].replace(wide, wide.replace("left:0px", "left:210px").replace("width:1776px", "width:1380px"))
                    calls = [("cover_write", {"path": "index.html", "text": fixed})]
            elif turn == 7:
                hint = feedback.get("geometry_repair")
                self.assertEqual(feedback["stage"], "recheck_layout")
                self.assertEqual(hint["status"], "RECHECK_REQUIRED")
                self.assertEqual(hint["layer_id"], "title-a")
                self.assertNotIn("geometry", hint)
                self.assertNotIn("violations", hint)
                calls = [("cover_render", {"request": request})]
            elif turn == 8:
                self.assertNotIn("geometry_repair", feedback)
                self.assertEqual(feedback["stage"], "inspect_render")
                rendered.update(progress_tests.fixture.returned_value(payload, "png_path", tool_call_id="geometry_7_0"))
                calls = [("cover_view", {"path": rendered["image_path"]})]
            else:
                self.assertEqual(turn, 9, "The synthetic UNKNOWN must not retry")
                self.assertNotIn("geometry_repair", feedback)
                self.assertIn(rendered["png_sha256"], runtime._images_in(payload))
                self.assertIn(rendered["thumbnail_sha256"], runtime._images_in(payload))
                raise httpx.ReadTimeout("synthetic geometry unknown, no retry", request=http_request)
            return httpx.Response(200, json=response(turn, calls))

        def fake_concept(**kwargs):
            concepts.append(kwargs["call_id"])
            return concept, {"call_id": kwargs["call_id"], "stage": "image", "status": "responded"}

        def checked_transport(request):
            # The provider conservatively wraps transport exceptions as UNKNOWN.
            # Keep a test assertion visible instead of reporting only call count.
            try:
                return transport(request)
            except AssertionError as error:
                transport_assertions.append(error)
                raise

        def run(**kwargs):
            directory = runtime.workspace_root() / kwargs["job_id"]
            directory.mkdir(parents=True)
            sources = []
            for index, source in enumerate(kwargs["sources"]):
                name = "assets/source-" + str(index + 1) + ".png"
                (directory / name).parent.mkdir(exist_ok=True)
                (directory / name).write_bytes(source["payload"])
                sources.append({**source, "path": name})
            bridge = WitnessBridge(job_id=kwargs["job_id"], directory=directory, sources=sources,
                hooks=kwargs["hooks"], model_transport=httpx.MockTransport(checked_transport))
            bridge.approved_titles = [title]
            try:
                return bridge.run("Synthetic geometry technical fixture, not merchant quality.", deadline=time.time() + 25 * 60)
            except BaseException as error:
                errors.append(error)
                raise
            finally:
                checkpoint = directory / "host-state/host-checkpoint.json"
                if checkpoint.is_file():
                    checkpoints.append(json.loads(checkpoint.read_text()))

        with tempfile.TemporaryDirectory(prefix="cover-geometry-feedback-") as state, \
                mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": state,
                    "NOTEAI_ARK_API_KEY": "offline-geometry-no-provider-access", "NOTEAI_MODEL_CAPACITY_MODE": "off"}), \
                mock.patch.object(progress_tests.billing, "_pricing_snapshot", side_effect=price), \
                mock.patch.object(runtime.cover_seedream, "generate_background", side_effect=fake_concept):
            result = progress_tests.cover_service._run_claim(scope.claim, runtime=run)
        if transport_assertions:
            raise transport_assertions[0]
        if errors and not isinstance(errors[0], provider.CoverAgentProviderError):
            raise errors[0]
        self.assertEqual(len(wire), 9)
        self.assertEqual(len(concepts), 1)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertTrue(errors[0].outcome_unknown)
        self.assertEqual(checkpoints[0]["last_render_rejection"]["code"], rejection["code"])
        rows = progress_tests.db.fetchall("SELECT state,http_status FROM public_trial_calls WHERE usage_record_id=? ORDER BY created_at,id",
            (scope.claim["charge"]["usage_id"],))
        self.assertEqual([(row["state"], row["http_status"]) for row in rows], [("responded", 200)] * 8 + [("unknown", None)])
        print("COVER_TEXT_GEOMETRY_SDK_PROOF=" + json.dumps({"actual_sdk": True,
            "actual_mock_http_calls": 9, "known_mock_200": 8, "unknown_once": 1,
            "measured_hint_next_wire_payload": True, "recheck_drops_old_coordinates": True,
            "successful_render_clears_hint": True, "original_cli_rejection_unchanged": True,
            "actual_png_pixels_and_thumbnail_reached_sdk": True,
            "real_supplier_calls": 0, "merchant_quality_acceptance": False}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
