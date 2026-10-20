"""Offline rendering and bounded workflow tests; not real supplier QA."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest import mock

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_renderer as renderer
import cover_runtime as runtime


def synthetic_photo(label=0):
    image = Image.new("RGB", (1200, 1000), (232 - label * 4, 221, 199))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 650, 1200, 1000), fill="#795D43")
    draw.ellipse((350, 700, 850, 830), fill="#D8D1BD")
    draw.ellipse((430, 310, 790, 680), fill="#EEEDE6")
    draw.ellipse((475, 345, 745, 435), fill="#6F4832")
    draw.ellipse((700, 400, 840, 560), outline="#EEEDE6", width=40)
    draw.rectangle((100, 90, 300, 580), fill="#557F61")
    draw.rectangle((120, 570, 280, 690), fill="#B8875B")
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def plan(reference, route="photo"):
    return {"route": route, "source_ref": reference, "crop": [0, 0, 1, 1],
            "subject_bbox": [.08, .08, .95, .88], "photo_bbox": [.04, .27, .96, .97],
            "text_bbox": [.055, .035, .945, .235], "text": "周末咖啡时光", "font_size": 112,
            "align": "left", "background_color": "#F5F0E8", "panel_color": "#F5F0E8",
            "text_color": "#213A2C"}


def approved_qc():
    return {"approved": True, "text_matches": True, "facts_preserved": True,
            "subject_preserved": True, "issues": [], "local_adjustment": None,
            "design_checks": {key: True for key in ("main_visual", "message_focus", "typographic_hierarchy",
                "layout_balance", "thumbnail_legibility", "style_fits_subject")}}


class CoverRendererTests(unittest.TestCase):
    def setUp(self):
        self.ref = str(uuid.uuid4())
        self.photo = synthetic_photo()
        self.plan = plan(self.ref)

    def test_exact_chinese_typography_and_original_photo_are_retained(self):
        base, layout = renderer.compose_base(self.photo, self.plan)
        final, layout = renderer.render_text(base, layout)
        proof = renderer.validate_artifact(final, layout)
        self.assertTrue(proof["valid"])
        self.assertEqual(layout["rendered_lines"], ["周末咖啡时光"])
        original = renderer.read_image(self.photo)
        output = renderer.read_image(final)
        x0, y0, x1, y1 = layout["photo_pixels"]
        expected = original.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
        self.assertEqual(output.crop((x0, y0, x1, y1)).tobytes(), expected.tobytes())
        self.assertNotEqual(hashlib.sha256(base).digest(), hashlib.sha256(final).digest())
        self.assertEqual(proof["content_type"], "image/png")
        self.assertEqual((proof["width"], proof["height"]), (1776, 2368))

    def test_crop_cannot_remove_protected_subject_and_text_cannot_cover_photo(self):
        for update, error in [
            ({"crop": [.3, 0, 1, 1]}, "COVER_SUBJECT_CROPPED"),
            ({"text_bbox": [.1, .3, .9, .5]}, "COVER_TEXT_OVER_SUBJECT"),
            ({"photo_bbox": [.1, .3, .4, .6]}, "COVER_PHOTO_TOO_SMALL"),
        ]:
            with self.subTest(error=error), self.assertRaisesRegex(renderer.CoverRenderError, error):
                renderer.compose_base(self.photo, {**self.plan, **update})

    def test_free_text_linebreak_and_position_edits_do_not_change_photo(self):
        base, layout = renderer.compose_base(self.photo, self.plan)
        final, layout = renderer.render_text(base, layout)
        edited, updated = runtime.free_adjust(base, layout, text="咖啡时光", lines=["咖啡", "时光"], position=[.04, .025])
        self.assertEqual(updated["rendered_lines"], ["咖啡", "时光"])
        original_final, edited_image = renderer.read_image(final), renderer.read_image(edited)
        self.assertEqual(original_final.crop(tuple(layout["photo_pixels"])).tobytes(),
                         edited_image.crop(tuple(layout["photo_pixels"])).tobytes())
        with self.assertRaisesRegex(renderer.CoverRenderError, "COVER_LINEBREAK_CONTENT_MISMATCH"):
            runtime.free_adjust(base, layout, lines=["新设施"])
        with self.assertRaisesRegex(renderer.CoverRenderError, "COVER_TEXT_OVER_SUBJECT"):
            runtime.free_adjust(base, layout, position=[.05, .5])

    def test_unsupported_glyph_and_overflow_fail_instead_of_truncating_copy(self):
        with self.assertRaisesRegex(renderer.CoverRenderError, "COVER_TEXT_GLYPH_UNSUPPORTED"):
            renderer.compose_base(self.photo, {**self.plan, "text": "咖啡\U0010FFFF"})
        base, layout = renderer.compose_base(self.photo, self.plan)
        with self.assertRaisesRegex(renderer.CoverRenderError, "COVER_TEXT_OVERFLOW"):
            renderer.render_text(base, {**layout, "text": "咖" * 64, "text_bbox": [.1, .02, .4, .08]})

    def test_local_contrast_correction_is_deterministic(self):
        base, layout = renderer.compose_base(self.photo, {**self.plan, "text_color": "#F5F0E8"})
        final, layout = renderer.render_text(base, layout)
        self.assertEqual(layout["text_color"], "#111111")
        self.assertTrue(renderer.validate_artifact(final, layout)["valid"])


class CoverRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"media_ref": str(uuid.uuid4()), "payload": synthetic_photo(i)} for i in range(9)]
        self.report = {"title": "周末咖啡时光", "body": "本人拍摄的咖啡练习图。", "domain": "美食",
                       "visual_advice": "选清晰完整主体，顶部留白", "title_variants": ["咖啡时光"]}
        self.before, self.records, self.stages = [], [], []
        self.hooks = runtime.RuntimeHooks(lambda *args: self.before.append(args), self.records.append, self.stages.append)
        self.admission = mock.patch("public_product.model_admission_sync", side_effect=lambda *_args: contextlib.nullcontext())
        self.admission.start()
        self.cost = mock.patch.object(runtime, "_text_usage_cost", side_effect=lambda _id, estimate: estimate)
        self.cost.start()

    def tearDown(self):
        self.cost.stop()
        self.admission.stop()

    def run_task(self, *, sources=None, design=None, qc=None, image_call=None):
        call = mock.Mock(side_effect=[json.dumps(design or plan(self.sources[0]["media_ref"]), ensure_ascii=False),
                                     json.dumps(qc or approved_qc())])
        result = runtime.run_cover(job_id=str(uuid.uuid4()), user_id="fixture-owner", report=self.report,
            sources=sources if sources is not None else self.sources, hooks=self.hooks,
            vision_call=call, image_call=image_call)
        return result, call

    def test_design_sees_all_nine_once_and_qc_compares_original_and_final_once(self):
        result, call = self.run_task()
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(call.call_args_list[0].args[2]), 9)
        self.assertEqual(len(call.call_args_list[1].args[2]), 3)
        import base64
        thumbnail_part = call.call_args_list[1].args[2][2]
        thumbnail_bytes = base64.b64decode(thumbnail_part["image_url"]["url"].split(",", 1)[1])
        with Image.open(io.BytesIO(thumbnail_bytes)) as thumbnail:
            self.assertEqual(thumbnail.size, (240, 320))
        self.assertEqual([args[0] for args in self.before], ["design", "qc"])
        self.assertEqual(self.stages, ["design", "render", "qc", "ready_to_save"])
        self.assertIsNone(result.layout["image_model"])
        self.assertTrue(result.artifact["valid"])

    def test_design_candidate_number_does_not_replace_original_observation_index(self):
        self.report["source_items"] = [
            {"input_field": "cover_images", "image_index": 5, "media_ref": self.sources[0]["media_ref"]},
            {"input_field": "cover_images", "image_index": 8, "media_ref": self.sources[0]["media_ref"]},
        ]
        result, call = self.run_task(sources=self.sources[:1])
        prompt = call.call_args_list[0].args[1]
        self.assertIn('"candidate_number": 1', prompt)
        self.assertIn('"image_index": 5', prompt)
        self.assertIn('"image_index": 8', prompt)
        self.assertIn("候选编号不等于报告观察原图号", prompt)

    def test_single_source_supported_without_report_regeneration(self):
        result, call = self.run_task(sources=self.sources[:1])
        self.assertEqual(len(call.call_args_list[0].args[2]), 1)
        self.assertEqual(result.design["source_ref"], self.sources[0]["media_ref"])

    def test_seedream_route_uses_only_selected_reference_and_one_image_call(self):
        def image_call(**kwargs):
            self.assertEqual(kwargs["source_images"], [self.sources[2]["payload"]])
            self.assertIn("No text", kwargs["prompt"])
            record = {"stage": "image", "call_id": kwargs["call_id"], "status": "responded"}
            kwargs["before_call"]("image", kwargs["call_id"], {})
            kwargs["on_call"](record)
            out = io.BytesIO()
            Image.new("RGB", (1776, 2368), "#9A876F").save(out, "PNG")
            return out.getvalue(), record
        image = mock.Mock(side_effect=image_call)
        result, call = self.run_task(design=plan(self.sources[2]["media_ref"], "seedream_background"), image_call=image)
        self.assertEqual(image.call_count, 1)
        self.assertEqual(call.call_count, 2)
        self.assertEqual([args[0] for args in self.before], ["design", "image", "qc"])
        self.assertEqual(result.layout["image_model"], runtime.seedream.MODEL)

    def test_invented_title_fact_invalid_selected_ref_and_bad_crop_stop_before_image(self):
        for update in [{"text": "全店免费"}, {"source_ref": str(uuid.uuid4())}, {"crop": [.5, 0, 1, 1]}]:
            with self.subTest(update=update):
                image = mock.Mock()
                with self.assertRaises(runtime.CoverRuntimeError):
                    self.run_task(design={**plan(self.sources[0]["media_ref"]), **update}, image_call=image)
                image.assert_not_called()

    def test_qc_fact_or_subject_failure_never_delivers_or_retries(self):
        for field in ("text_matches", "facts_preserved", "subject_preserved"):
            with self.subTest(field=field):
                bad = {**approved_qc(), "approved": False, field: False, "issues": ["subject_or_fact"]}
                with self.assertRaisesRegex(runtime.CoverRuntimeError, "COVER_QC_REJECTED"):
                    self.run_task(qc=bad)

    def test_design_rejection_cannot_be_overridden_by_approved_or_local_fix(self):
        for key in approved_qc()["design_checks"]:
            with self.subTest(key=key):
                qc = approved_qc()
                qc["design_checks"][key] = False
                qc["local_adjustment"] = {"font_size": 120}
                with self.assertRaisesRegex(runtime.CoverRuntimeError, "COVER_QC_DESIGN_REJECTED"):
                    self.run_task(qc=qc)

    def test_legacy_or_malformed_qc_cannot_silently_skip_design_acceptance(self):
        for value in (None, {}, {**approved_qc()["design_checks"], "main_visual": "true"}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(runtime.CoverRuntimeError, "COVER_QC_CONTRACT_INVALID"):
                    self.run_task(qc={**approved_qc(), "design_checks": value})
        for issue in ("composition_weak", "message_unfocused", "typography_weak", "empty_layout",
                      "thumbnail_unreadable", "style_mismatch"):
            with self.subTest(issue=issue):
                with self.assertRaisesRegex(runtime.CoverRuntimeError, "COVER_QC_REJECTED"):
                    self.run_task(qc={**approved_qc(), "issues": [issue]})

    def test_qc_rejection_or_adjustment_cannot_save_a_different_unchecked_final(self):
        for approved in (True, False):
            with self.subTest(approved=approved):
                qc = {**approved_qc(), "approved": approved, "issues": ["small_text"],
                      "local_adjustment": {"font_size": 120}}
                with self.assertRaisesRegex(runtime.CoverRuntimeError, "COVER_QC_REJECTED"):
                    self.run_task(qc=qc)
                self.assertNotIn("local_adjustment", self.stages)
                self.assertNotIn("ready_to_save", self.stages)

    def test_unknown_design_never_dispatches_an_image_or_paid_retry(self):
        image = mock.Mock()
        with self.assertRaises(runtime.CoverRuntimeError) as failure:
            runtime.run_cover(job_id=str(uuid.uuid4()), user_id="fixture-owner", report=self.report,
                sources=self.sources[:1], hooks=self.hooks,
                vision_call=mock.Mock(side_effect=RuntimeError("ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY")),
                image_call=image)
        self.assertTrue(failure.exception.outcome_unknown)
        self.assertEqual(len(self.before), 1)
        self.assertEqual(self.records[-1]["status"], "unknown")
        image.assert_not_called()

    def test_hash_change_duplicate_and_invalid_source_fail_before_any_call(self):
        cases = [[{**self.sources[0], "sha256": "0" * 64}], [self.sources[0], self.sources[0]], []]
        for sources in cases:
            with self.subTest(count=len(sources)), self.assertRaises(runtime.CoverRuntimeError):
                self.run_task(sources=sources)
        self.assertEqual(self.before, [])

    def test_call_identity_is_stable_per_original_task_and_distinct_per_stage(self):
        job = str(uuid.uuid4())
        ids = [runtime.physical_call_id(job, stage) for stage in ("design", "image", "qc")]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids[0], runtime.physical_call_id(job, "design"))


if __name__ == "__main__":
    unittest.main()
