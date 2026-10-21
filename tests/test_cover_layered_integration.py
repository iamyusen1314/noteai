"""Offline v2 wire/storage/accounting tests, not supplier or aesthetic QA."""
import io
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import httpx
from PIL import Image

from tests import test_cover_service as service_fixtures
from tests.test_cover_design import model_brief
import ark_media
import cover_jobs as jobs
import cover_renderer as renderer
import cover_runtime as runtime
import cover_service as service
import db
import private_storage as storage


def layered_plan(refs):
    """Mock supplier response: title spans only, never model-retyped copy."""
    brief = model_brief(refs[0])
    brief["industry"] = "美食"
    brief["reader_question"] = "真实咖啡环境有什么看点"
    brief["source_reasons"] = [{"source_ref": ref, "reason": "实拍完整且清晰"} for ref in refs]
    boxes = [[0, .16, 1, .58], [0, .58, 1, 1]] if len(refs) == 2 else [[0, .16, 1, 1]]
    return {
        "schema_version": 2, "route": "photo", "background_color": "#FFFFFF",
        "photos": [{"source_ref": ref, "crop": [0, 0, 1, 1], "subject_bbox": [0, 0, 1, 1], "bbox": box}
                   for ref, box in zip(refs, boxes)],
        "text_layers": [
            {"copy_span": {"title_id": "t1", "start": 0, "end": 4},
             "bbox": [.04, .02, .96, .115], "font_id": "SourceHanSansSC-Bold",
             "font_size": 144, "align": "left", "color": "#111111"},
            {"copy_span": {"title_id": "t1", "start": 4, "end": 6},
             "bbox": [.04, .115, .96, .155], "font_id": "SourceHanSerifSC-Regular",
             "font_size": 64, "align": "left", "color": "#444444"},
        ],
        "design_brief": brief,
    }


class LayeredCoverIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing temporary database, no-network fence, private
        # in-memory storage and shared model-admission fixtures.
        self.h = service_fixtures.CoverServiceIntegrationTests()
        self.h.setUp()
        self.f = self.h.fixture
        self.f.policy = {**self.f.policy, "design_version": 2}
        self.f.input = {**self.f.input, "approved_titles": [self.f.input["title"]]}
        self.refs = []
        for color in ("#3D6861", "#8E7254"):
            stream = io.BytesIO()
            Image.new("RGB", (1671, 941), color).save(stream, "PNG")
            ref = storage.store_media_bytes(self.f.user, purpose="image", content_type="image/png",
                payload=stream.getvalue(), item_count=1, ttl_seconds=86400)
            self.refs.append(ref.id)
        self.requests = []

    def tearDown(self):
        self.h.tearDown()

    def submit(self, key="layered-cover"):
        return self.f.submit(key=key, source_refs=self.refs)

    def wrapper(self, *, design_mutation=None, result_mutation=None, unknown=False):
        def run(**kwargs):
            plan = layered_plan([source["media_ref"] for source in kwargs["sources"]])
            if design_mutation:
                design_mutation(plan)
            calls = []

            def handle(request):
                payload = json.loads(request.content)
                self.assertEqual(payload["model"], ark_media.MODEL)
                self.assertNotIn("/images/", request.url.path)
                self.requests.append(payload)
                calls.append(payload)
                is_design = len(calls) == 1
                if unknown:
                    raise httpx.ReadTimeout("offline result unknown", request=request)
                from tests.test_cover_runtime import approved_qc
                content = plan if is_design else approved_qc()
                return httpx.Response(200, json={"model": ark_media.MODEL,
                    "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
                        "content": json.dumps(content, ensure_ascii=False)}}],
                    "usage": {"prompt_tokens": 800, "completion_tokens": 160,
                              "prompt_tokens_details": {"cached_tokens": 0}}})

            transport = httpx.MockTransport(handle)
            result = runtime.run_cover(**kwargs, design_transport=transport, qc_transport=transport)
            if result_mutation:
                result_mutation(result)
            return result
        return run

    def complete(self, **kwargs):
        job = self.submit()
        claim = jobs.claim_job(job["job_id"])
        return service._run_claim(claim, runtime=self.wrapper(**kwargs))

    def test_two_photo_wire_storage_reopen_and_unique_settlement(self):
        job = self.complete()
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["billing"]["credits_used"], 8)
        self.assertEqual(len(self.requests), 2)
        layout = jobs.get_layout(self.f.user, job["job_id"])
        self.assertEqual(layout["runtime_version"], runtime.LAYERED_VERSION)
        self.assertEqual(set(layout["source_hashes"]), set(self.refs))
        self.assertEqual(len(layout["text_layers"]), 2)
        self.assertEqual([layer["text"] for layer in layout["text_layers"]], ["周末咖啡", "时光"])
        self.assertTrue(all("copy_span" not in layer for layer in layout["text_layers"]))
        self.assertEqual(len(self.requests[1]["messages"][0]["content"]), 5)
        self.assertIn("第3张为最终封面", self.requests[1]["messages"][0]["content"][-1]["text"])
        self.assertIn("导演设计提案（仅解释目的与选材，不是事实认证或质量结论", self.requests[1]["messages"][0]["content"][-1]["text"])
        self.assertIn("真实咖啡环境有什么看点", self.requests[1]["messages"][0]["content"][-1]["text"])
        self.assertEqual(jobs.get_job(self.f.user, job["job_id"])["layout"]["text"], "周末咖啡\n时光")
        duplicate = self.submit()
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["job_id"], job["job_id"])
        self.assertEqual(self.f.balances()[1], 8)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 2)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM cover_image_usage")[0], 0)
        reference = jobs.asset_reference(self.f.user, job["job_id"])
        _, payload = storage.load_media_bytes(reference, user_id=self.f.user, purpose="image")
        self.assertTrue(renderer.validate_artifact(payload, layout)["valid"])
        with self.assertRaises(Exception):
            jobs.asset_reference(self.f.other, job["job_id"])

    def test_free_short_edit_after_originals_expire_keeps_base_and_no_new_charge(self):
        job = self.complete()
        before = jobs.get_layout(self.f.user, job["job_id"])
        old_ref = jobs.asset_reference(self.f.user, job["job_id"], revision=1)
        storage.expire_media(now=datetime.now(timezone.utc) + timedelta(days=2), user_id=self.f.user)
        for reference in self.refs:
            self.assertEqual(db.fetchone("SELECT state FROM private_media_refs WHERE id=?", (reference,))[0], "expired")
        updated = service.adjust(self.f.user, job["job_id"], text="咖啡", position=None, expected_revision=1)
        self.assertEqual(updated["asset_revision"], 2)
        self.assertEqual(updated["layout"]["text"], "咖啡")
        after = jobs.get_layout(self.f.user, job["job_id"])
        for key in ("photos", "source_hashes", "base_sha256", "input_source_hashes", "runtime_version"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(len(after["text_layers"]), 1)
        self.assertEqual(jobs.asset_reference(self.f.user, job["job_id"], revision=1), old_ref)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.f.balances()[1], 8)
        self.assertEqual(updated["expires_at"], job["expires_at"])

    def test_single_photo_uses_same_two_call_saved_delivery_contract(self):
        self.refs = self.refs[:1]
        job = self.complete()
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(jobs.get_layout(self.f.user, job["job_id"])["photos"]), 1)
        self.assertEqual(job["billing"]["credits_used"], 8)

    def test_complete_long_brief_reaches_pixel_qc_and_settles_only_once(self):
        def change(plan):
            for field in ("industry", "subtype", "content_intent", "reader_question", "visual_strategy"):
                plan["design_brief"][field] = "说明" * 40
            plan["design_brief"]["factual_exclusions"] = ["不新增价格", "不借用他店设施"]
        job = self.complete(design_mutation=change)
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(len(self.requests), 2)
        qc_prompt = self.requests[1]["messages"][0]["content"][-1]["text"]
        self.assertIn("不新增价格", qc_prompt)
        self.assertIn("不借用他店设施", qc_prompt)
        saved = json.loads(db.fetchone("SELECT design_json FROM cover_jobs WHERE id=?", (job["job_id"],))[0])
        self.assertEqual(saved["design_brief"]["visual_strategy"], "说明" * 40)
        self.assertEqual(saved["design_brief"]["factual_exclusions"], ["不新增价格", "不借用他店设施"])
        self.assertEqual(jobs.get_job(self.f.user, job["job_id"])["layout"]["text"], "周末咖啡\n时光")
        duplicate = self.submit()
        self.assertEqual(duplicate["job_id"], job["job_id"])
        self.assertFalse(duplicate["created"])
        self.assertEqual(self.f.balances()[1], 8)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 2)

    def test_oversized_brief_field_stops_before_qc_storage_or_final_charge(self):
        def change(plan):
            plan["design_brief"]["visual_strategy"] = "字" * 101
        with mock.patch.object(service, "_store_image") as store:
            job = self.complete(design_mutation=change)
        self.assertEqual(job["status"], "failed", job)
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(job["has_final"])
        self.assertEqual(self.f.balances()[1], 0)
        store.assert_not_called()

    def test_foreign_selected_photo_fails_before_qc_or_storage(self):
        def change(plan):
            plan["photos"][1]["source_ref"] = str(uuid.uuid4())
        with mock.patch.object(service, "_store_image") as store:
            job = self.complete(design_mutation=change)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.f.balances()[1], 0)
        store.assert_not_called()

    def test_discontinuous_title_span_stops_after_design_before_qc_or_storage(self):
        def change(plan):
            # The first span ends at 4; overlapping at 3 is not a continuous excerpt.
            plan["text_layers"][1]["copy_span"]["start"] = 3
        with mock.patch.object(service, "_store_image") as store:
            job = self.complete(design_mutation=change)
        self.assertEqual(job["status"], "failed", job)
        self.assertFalse(job["has_final"])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 1)
        self.assertEqual(self.f.balances()[1], 0)
        store.assert_not_called()

    def test_second_source_hash_must_match_frozen_task(self):
        def change(result):
            reference = result.layout["photos"][1]["source_ref"]
            result.layout["photos"][1]["source_sha256"] = "f" * 64
            result.layout["source_hashes"][reference] = "f" * 64
        job = self.complete(result_mutation=change)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.f.balances()[1], 0)
        self.assertFalse(job["has_final"])

    def test_locally_corrected_cannot_bypass_storage_quality_gate(self):
        def change(result):
            result.qc.update(approved=False, locally_corrected=True)
        with mock.patch.object(service, "_store_image") as store:
            job = self.complete(result_mutation=change)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.f.balances()[1], 0)
        store.assert_not_called()

    def test_mismatched_editable_base_never_delivers_or_charges(self):
        def change(result):
            result.layout["base_sha256"] = "f" * 64
        job = self.complete(result_mutation=change)
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["has_final"])
        self.assertEqual(self.f.balances()[1], 0)

    def test_unknown_design_has_one_dispatch_and_no_automatic_restart(self):
        job = self.complete(unknown=True)
        self.assertEqual(job["status"], "outcome_unknown")
        self.assertEqual(len(self.requests), 1)
        self.assertIsNone(jobs.claim_job(job["job_id"]))
        self.assertEqual(self.f.balances()[1], 0)

    def test_new_policy_and_legacy_policy_do_not_silently_share_quote(self):
        legacy = {k: v for k, v in self.f.policy.items() if k != "design_version"}
        self.assertNotEqual(jobs.policy_quote_version(legacy), jobs.policy_quote_version(self.f.policy))
        with self.assertRaises(ValueError):
            jobs.policy_quote_version({**self.f.policy, "design_version": True})
