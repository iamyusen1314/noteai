"""Report source recovery against isolated SQLite and a private in-memory backend.

No provider/model transports, production data or credentials are used.
"""
import asyncio
import io
import json
import os
import re
import unittest
from contextlib import ExitStack
from datetime import timedelta
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image

from tests import test_report_history as history
from tests import test_postdelivery_api as delivery

api, db = history.api, history.db
storage = api._private_storage


class ReportCoverSourcesTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1"})
        self.environment.start()
        self.fixture = history.ReportHistoryTests()
        self.fixture.setUp()
        self.user, self.other = self.fixture.user, self.fixture.other
        self.rid = self.fixture.report_id
        self.backend = storage.InMemoryObjectBackend()
        storage.configure_object_backend(self.backend, key_epoch="cover-offline-test")

    def tearDown(self):
        storage.reset_object_backend()
        self.fixture.tearDown()
        self.environment.stop()

    def upload(self, *, user=None, expired=False, purpose="image"):
        image = io.BytesIO()
        Image.new("RGB", (80, 100), (70, 100, 130)).save(image, "JPEG")
        return storage.store_media_bytes((user or self.user)["id"], purpose=purpose,
            content_type="image/jpeg" if purpose == "image" else "video/mp4",
            payload=image.getvalue(), item_count=1, ttl_seconds=60,
            now=self.fixture.now - timedelta(minutes=5) if expired else None)

    def generation_result(self):
        context = json.loads(db.fetchone("SELECT generate_ctx_json FROM chat_sessions WHERE id=?", (self.rid,))[0])
        return context, context[api._clarification.KEY]["result"]

    def set_original_sources(self, refs):
        context, result = self.generation_result()
        result["source_media_refs"] = refs
        db.execute("UPDATE chat_sessions SET generate_ctx_json=? WHERE id=?", (json.dumps(context), self.rid))

    def read(self, kind="generate", rid=None, user=None):
        return asyncio.run(api.get_report_cover_sources(kind, rid or self.rid, user or self.user))

    def attach(self, refs, kind="generate", rid=None, user=None):
        return asyncio.run(api.set_report_cover_sources(kind, rid or self.rid,
            api.ReportCoverSourcesInput(media_refs=refs), user or self.user))

    def test_nine_original_refs_survive_public_report_reopen_and_verified_read(self):
        refs = [self.upload().id for _ in range(9)]
        self.set_original_sources(refs)
        self.assertEqual(self.fixture.detail()["result"]["source_media_refs"], refs)
        self.assertEqual((self.read()["status"], self.read()["ready_count"]), ("ready", 9))
        self.assertEqual(db.fetchone("SELECT count(*) FROM usage_records")[0], 0)

    def test_missing_and_expired_sources_give_explicit_upload_paths(self):
        missing = self.read()
        self.assertEqual(missing["status"], "reupload_required")
        self.assertEqual(missing["upload_path"], "/upload-image")
        self.assertEqual(missing["attach_path"], f"/reports/generate/{self.rid}/cover-sources")
        self.set_original_sources([self.upload(expired=True).id])
        self.assertEqual(self.read()["status"], "reupload_required")

    def test_replacement_persists_without_mutating_original_facts_billing_or_ttl(self):
        original = self.upload(expired=True)
        replacement = self.upload()
        self.set_original_sources([original.id])
        _, before = self.generation_result()
        self.attach([replacement.id, replacement.id])
        self.attach([replacement.id])
        _, after = self.generation_result()
        self.assertEqual({k: v for k, v in after.items() if k != "cover_source_media_refs"}, before)
        self.assertEqual(self.fixture.detail()["result"]["cover_source_media_refs"], [replacement.id])
        self.assertEqual(self.read()["ready_count"], 1)
        self.assertEqual(db.fetchone("SELECT expires_at FROM private_media_refs WHERE id=?", (replacement.id,))[0], replacement.expires_at)
        self.assertEqual(db.fetchone("SELECT count(*) FROM usage_records")[0], 0)
        self.assertEqual(db.fetchone("SELECT count(*) FROM notes")[0], 1)

    def test_diagnosis_ten_original_sources_and_separate_replacements_survive_white_list(self):
        did = self.fixture.diagnosis()
        refs = [self.upload().id for _ in range(10)]
        row = db.fetchone("SELECT diagnosis_json FROM saved_diagnoses WHERE id=?", (did,))
        result = json.loads(row[0])
        result["source_media_refs"] = refs
        db.execute("UPDATE saved_diagnoses SET diagnosis_json=? WHERE id=?", (json.dumps(result), did))
        self.assertEqual(self.read("analyze", did)["ready_count"], 10)
        self.attach(refs[:1], "analyze", did)
        saved = asyncio.run(api.get_report("analyze", did, self.user))["result"]
        self.assertEqual(saved["source_media_refs"], refs)
        self.assertEqual(saved["cover_source_media_refs"], refs[:1])

    def test_legacy_diagnosis_can_recover_its_retained_cover_ref(self):
        did = self.fixture.diagnosis()
        ref = self.upload().id
        result = {"ai_diagnosis": "原诊断", "input_diagnostics": {"cover_media_ref": ref}}
        db.execute("UPDATE saved_diagnoses SET diagnosis_json=? WHERE id=?", (json.dumps(result), did))
        self.assertEqual(self.read("analyze", did)["ready_count"], 1)

    def test_legacy_rejected_envelope_does_not_swallow_the_new_attachment_field(self):
        did = self.fixture.diagnosis()
        raw = {"ai_diagnosis": "原历史内容", "internal_request": "PRIVATE LEGACY TRANSPORT"}
        db.execute("UPDATE saved_diagnoses SET diagnosis_json=? WHERE id=?", (json.dumps(raw), did))
        ref = self.upload().id
        for fallback in (None, {"ai_diagnosis": "原接续公开诊断", "cover_source_media_refs": [str(uuid4())]}):
            with self.subTest(fallback=bool(fallback)), mock.patch.object(api._clarification,
                    "completed_diagnosis_result", return_value=fallback):
                self.attach([ref], "analyze", did)
                self.assertEqual(self.read("analyze", did)["sources"][0]["media_ref"], ref)
                reopened = asyncio.run(api.get_diagnosis(did, self.user))
                self.assertEqual(reopened["cover_source_media_refs"], [ref])
                self.assertNotIn("PRIVATE LEGACY", repr(reopened))
        saved = json.loads(db.fetchone("SELECT diagnosis_json FROM saved_diagnoses WHERE id=?", (did,))[0])
        self.assertEqual({k: v for k, v in saved.items() if k != "cover_source_media_refs"}, raw)
        self.assertEqual(api._sanitize_persisted_diagnosis(saved), {})

    def test_foreign_report_denied_before_private_storage_read_or_write(self):
        ref = self.upload(user=self.other).id
        with mock.patch.object(storage, "load_media_bytes", side_effect=AssertionError("unauthorized read")):
            for action in (lambda: self.read(user=self.other), lambda: self.attach([ref], user=self.other)):
                with self.assertRaises(HTTPException) as denied:
                    action()
                self.assertEqual(denied.exception.status_code, 404)

    def test_foreign_expired_and_wrong_purpose_uploads_cannot_attach(self):
        for ref in (self.upload(user=self.other), self.upload(expired=True), self.upload(purpose="video")):
            with self.assertRaises(HTTPException) as denied:
                self.attach([ref.id])
            self.assertEqual(denied.exception.status_code, 422)
        self.assertNotIn("cover_source_media_refs", self.generation_result()[1])

    def test_object_outage_does_not_tell_user_their_source_expired(self):
        ref = self.upload().id
        self.set_original_sources([ref])
        with mock.patch.object(self.backend, "get", side_effect=storage.ObjectStorageUnavailable()):
            self.assertEqual(self.read()["status"], "storage_unavailable")
            with self.assertRaises(HTTPException) as denied:
                self.attach([ref])
            self.assertEqual(denied.exception.status_code, 503)
        self.assertNotIn("cover_source_media_refs", self.generation_result()[1])

    def test_expiry_between_inspection_and_attach_rolls_back_without_overwriting_previous(self):
        old, new = self.upload().id, self.upload().id
        self.attach([old])
        with mock.patch.object(storage, "lock_ready_media_refs", side_effect=storage.MediaReferenceUnavailable()):
            with self.assertRaises(HTTPException):
                self.attach([new])
        self.assertEqual(self.read()["sources"][0]["media_ref"], old)

    def test_source_image_requires_report_membership_and_returns_private_verified_bytes(self):
        ref, unrelated = self.upload(), self.upload()
        self.set_original_sources([ref.id])
        response = asyncio.run(api.read_report_cover_source("generate", self.rid, ref.id, self.user))
        with Image.open(io.BytesIO(response.body)) as image:
            self.assertEqual(image.size, (80, 100))
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(api.read_report_cover_source("generate", self.rid, unrelated.id, self.user))
        self.assertEqual(denied.exception.status_code, 404)

    def test_deleted_report_and_user_write_fence_prevent_supplement(self):
        ref = self.upload().id
        db.execute("UPDATE users SET deletion_requested_at=? WHERE id=?", (self.fixture.now.isoformat(), self.user["id"]))
        with self.assertRaises(HTTPException) as denied:
            self.attach([ref])
        self.assertEqual(denied.exception.status_code, 409)
        db.execute("UPDATE users SET deletion_requested_at=NULL WHERE id=?", (self.user["id"],))
        db.execute("UPDATE content_retention SET deleted_at=? WHERE content_id=?", (self.fixture.now.isoformat(), self.rid))
        with self.assertRaises(HTTPException) as denied:
            self.attach([ref])
        self.assertEqual(denied.exception.status_code, 404)

    def test_public_projection_rejects_urls_base64_and_unknown_nested_fields(self):
        for malformed in (["https://example.invalid/private.jpg"], ["data:image/jpeg;base64,YQ=="], list(map(str, range(11)))):
            result = api._generation_report_result({"source_media_refs": malformed, "private_transport": "PRIVATE"})
            self.assertEqual(result["source_media_refs"], [])
            self.assertNotIn("PRIVATE", repr(result))
        safe = api._sanitize_persisted_diagnosis({"source_media_refs": [self.upload().id], "input_diagnostics": {"source_media_refs": [str(uuid4())]}})
        self.assertEqual(len(safe["source_media_refs"]), 1)
        for refs in ([], ["https://example.invalid/image.jpg"]):
            with self.assertRaises(HTTPException):
                self.attach(refs)

    def test_source_routes_have_narrow_allow_list_without_enabling_paid_cover_jobs(self):
        path = f"/reports/generate/{self.rid}/cover-sources"
        self.assertTrue(api._public_product.allowed_route("GET", path))
        with mock.patch.object(api._public_product, "image_enabled", return_value=True):
            self.assertTrue(api._public_product.allowed_route("PUT", path))
            self.assertFalse(api._public_product.allowed_route("PUT", path + "/" + str(uuid4())))
        self.assertFalse(api._public_product.allowed_route("POST", path))
        self.assertFalse(api._public_product.allowed_route("POST", "/cover/jobs"))

    def test_same_origin_source_proxy_is_narrow_and_has_no_paid_job_location(self):
        text = (history.ROOT / "deploy/production/public-account.locations.conf").read_text()
        locations = re.findall(r'location ~ "([^"\n]*cover-sources[^"\n]*)" \{([^}]+\}[^}]+)\}', text)
        self.assertEqual(len(locations), 2)
        for kind in ("analyze", "generate"):
            for rid in (self.rid, self.rid.replace("-", "")):
                collection = f"/reports/{kind}/{rid}/cover-sources"
                image = collection + "/" + str(uuid4())
                matches = [(p, b) for p, b in locations if re.fullmatch(p, collection)]
                self.assertEqual(len(matches), 1)
                self.assertIn("limit_except GET PUT", matches[0][1])
                self.assertIn("client_max_body_size 8k", matches[0][1])
                self.assertEqual(sum(bool(re.fullmatch(p, image)) for p, _ in locations), 1)
                for invalid in (collection + "/bad", image + "/tail", collection.replace("/reports/", "/admin/")):
                    self.assertFalse(any(re.fullmatch(p, invalid) for p, _ in locations))


class GenerationSourcePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = delivery.PostDeliveryApiTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_original_nine_refs_are_in_complete_event_saved_report_and_resume_metadata(self):
        refs = [str(uuid4()) for _ in range(9)]
        metadata = []

        async def pipeline(**_kwargs):
            metadata.append(api._clarification.execution.get()["metadata"])
            self.fixture.active_call()
            yield {"type": "complete", "note_title": "模拟标题", "note_body": "模拟正文", "ces_percentile": 72, "grade": "良好"}

        async def run():
            response = await api.generate_stream_endpoint(api.GenerateInput(domain="美食", cover_images=refs), self.fixture.user, None, None)
            return await self.fixture.collect(response)

        with mock.patch.object(api, "_generate_pipeline_stream", new=pipeline), \
             mock.patch.object(api, "_bounded_extract_cover", new=mock.AsyncMock(return_value=(None, {}))), \
             mock.patch.object(api, "_maybe_enrich_facts", new=mock.AsyncMock(return_value=None)), \
             mock.patch.object(api, "_compute_market_timing_for_delivery", return_value=None), \
             mock.patch.object(api._memory, "build_memory_prompt", return_value=""), \
             mock.patch.object(api._memory, "check_and_record_achievements"):
            events = asyncio.run(run())
        complete = next(event for event in events if event["type"] == "complete")
        self.assertEqual(complete["source_media_refs"], refs)
        self.assertEqual(metadata[0]["source_media_refs"], refs)
        items = [{"input_field": "cover_images", "image_index": i + 1, "media_ref": ref} for i, ref in enumerate(refs)]
        self.assertEqual(complete["source_media_items"], items)
        self.assertEqual(metadata[0]["source_media_items"], items)
        saved = asyncio.run(api.get_report("generate", complete["saved_note_id"], self.fixture.user))
        self.assertEqual(saved["result"]["source_media_refs"], refs)
        self.assertEqual(saved["result"]["source_media_items"], items)
        self.assertEqual(complete["billing"]["credits_used"], 8)

    def test_diagnosis_save_and_reopen_preserve_source_mapping_with_original_settlement(self):
        refs = [str(uuid4()) for _ in range(10)]
        req = api.AnalyzeInput(note_title="原题", desc="原文", cover_image=refs[0], extra_images=refs[1:])
        claim = api._paid_request_claim("diagnosis-source-reservation", user_id=self.fixture.user["id"],
                                       operation="analyze", payload=req)
        self.fixture.fixture.known_call(claim)
        response = self.fixture.response()
        response.source_media_refs = refs
        response.source_media_items = api._cover_sources.source_items_from_inputs(cover_image=refs[0], extra_images=refs[1:])
        response.input_diagnostics = {"source_media_refs": refs, "source_media_items": response.source_media_items}
        with mock.patch.object(api._memory, "check_and_record_achievements"):
            api._persist_postdelivery_diagnosis(claim, response, self.fixture.user, req, "原文", False)
        reopened = asyncio.run(api.get_diagnosis(claim["request_id"], self.fixture.user))
        self.assertEqual(reopened["source_media_refs"], refs)
        self.assertEqual(reopened["source_media_items"], response.source_media_items)
        self.assertEqual(reopened["input_diagnostics"]["source_media_items"], response.source_media_items)
        self.assertEqual(reopened["billing"]["credits_used"], 6)

    def test_diagnosis_preparation_freezes_original_indices_and_resume_does_not_reobserve(self):
        refs = [str(uuid4()) for _ in range(2)]
        req = api.AnalyzeInput(note_title="本人笔记", desc="原始内容", domain="美食",
            cover_image=refs[0], extra_images=["legacy-inline-image", refs[1], refs[1]])
        captures = []

        def stop(*_args, **kwargs):
            captures.append(kwargs["clarification_prepared"])
            raise HTTPException(418, "offline stop after input preparation")

        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "offline-fixture-not-a-provider-key"}))
            stack.enter_context(mock.patch("httpx.Client.send", side_effect=AssertionError("offline fixture")))
            stack.enter_context(mock.patch("httpx.AsyncClient.send", side_effect=AssertionError("offline fixture")))
            for name, value in (("_bounded_extract_cover", mock.AsyncMock(return_value=(80, {}))),
                                ("_generation_image_observation", mock.AsyncMock(return_value="本人实际图片的离线观察内容")),
                                ("_maybe_enrich_facts", mock.AsyncMock(return_value=None)),
                                ("_compute_market_timing_for_delivery", mock.Mock(return_value=None)),
                                ("compute_semantic_features", mock.Mock(return_value={})),
                                ("_predict", mock.Mock(return_value=(70, {}))),
                                ("_find_weaknesses", mock.Mock(return_value=[])),
                                ("_MEM0_AVAILABLE", False), ("_run_five_agents", stop)):
                stack.enter_context(mock.patch.object(api, name, value))
            stack.enter_context(mock.patch.object(api._memory, "build_memory_prompt", return_value=""))
            stack.enter_context(mock.patch.object(api._billing, "record_auxiliary_usage"))
            with self.assertRaises(HTTPException) as stopped:
                asyncio.run(api._run_analyze_pipeline(req, self.fixture.user,
                    billing_charge={}, billing_managed=True))
            self.assertEqual(stopped.exception.status_code, 418)
            original = captures[0]["original_input"]
            self.assertEqual(original["source_media_refs"], refs)
            self.assertEqual([(i["input_field"], i["image_index"]) for i in original["source_media_items"]],
                             [("cover_image", 1), ("extra_images", 2), ("extra_images", 3)])
            prepared = {**captures[0], "opinions": []}
            with mock.patch.object(api, "_generation_image_observation", side_effect=AssertionError("resume reobserved")):
                with self.assertRaises(HTTPException) as stopped:
                    asyncio.run(api._run_analyze_pipeline(api.AnalyzeInput(**prepared["request"]), self.fixture.user,
                        billing_charge={}, billing_managed=True, prepared=prepared))
                self.assertEqual(stopped.exception.status_code, 418)
            self.assertEqual(captures[1]["original_input"], original)


if __name__ == "__main__":
    unittest.main()
