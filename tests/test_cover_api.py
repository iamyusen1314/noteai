"""Cover endpoint contracts over isolated SQLite/private PNG objects.

Endpoints are invoked directly with explicit authenticated fixture identities;
no ASGI startup, worker, production configuration, or supplier is started.
"""
import asyncio
from contextlib import ExitStack
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import re
import sys
import unittest
import uuid
from unittest import mock

from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
import api
import ark_media
import billing
import content_retention
import cover_jobs as jobs
import cover_service as service
import cover_settings as settings
import db
import private_storage as storage
from tests import test_cover_jobs as job_fixtures


class CoverApiContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = job_fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.user = {"id": self.fixture.user}
        self.other = {"id": self.fixture.other}
        self.report = self.fixture.report
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1",
            "NOTEAI_PUBLIC_PRODUCT": "0", "NOTEAI_ARK_API_KEY": "offline-fixture"}))
        self.stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("offline API tests prohibit network")))
        self.stack.enter_context(mock.patch.object(ark_media, "chat", side_effect=AssertionError("GET/POST admission must not call a model")))
        self.stack.enter_context(mock.patch.object(ark_media, "_complete_admitted", side_effect=AssertionError("API endpoint must not start runtime")))
        self.readiness = self.stack.enter_context(mock.patch.object(settings, "readiness", return_value=(True, "")))
        self.policy = self.stack.enter_context(mock.patch.object(settings, "policy_snapshot", return_value=self.fixture.policy))
        self.original = {
            "ai_diagnosis": "仅有本人原图的原报告", "suggested_titles": ["店内真实体验"],
            "expert_opinions": [{"role": "视觉专家", "opinion": "保留主体", "suggestions": ["留出文字空间"]}],
            "source_media_refs": [self.fixture.source.id],
            "source_media_items": [{"input_field": "cover_image", "image_index": 1, "media_ref": self.fixture.source.id}],
            "input_diagnostics": {"original_title": "真实门店", "original_desc": "真实素材笔记",
                                  "cover_media_ref": self.fixture.source.id},
        }
        db.execute("UPDATE saved_diagnoses SET diagnosis_json=? WHERE id=?", (json.dumps(self.original, ensure_ascii=False), self.report))

    def tearDown(self):
        self.stack.close()
        self.fixture.tearDown()

    @staticmethod
    def run_async(awaitable):
        return asyncio.run(awaitable)

    def request(self, *, request_id=None, quote=None, refs=None, title=None):
        return api.CoverSubmitInput(request_id=request_id or str(uuid.uuid4()),
            quote_version=quote or jobs.policy_quote_version(self.fixture.policy),
            source_media_refs=refs, title=title)

    def submit(self, request=None, *, user=None, report=None, kind="analyze"):
        return self.run_async(api.submit_report_cover(kind, report or self.report,
            request or self.request(), user or self.user))

    def complete(self, *, middle=True):
        # API tests use already-delivered, ledger-backed real PNG fixtures;
        # the separate service suite exercises actual HTTP adapter accounting.
        queued, claim = self.fixture.claim()
        self.fixture.image_call(claim)
        if middle:
            original_assets = self.fixture.assets
            def assets(**kwargs):
                final, base, layout = original_assets(**kwargs)
                _, photo = storage.load_media_bytes(self.fixture.source.id, user_id=self.fixture.user, purpose="image")
                import cover_renderer
                plan = {**layout, "photo_bbox": [.04, .27, .96, .73], "subject_bbox": [0, 0, 1, 1]}
                base_body, layout = cover_renderer.compose_base(photo, plan)
                final_body, layout = cover_renderer.render_text(base_body, layout)
                def store(body):
                    return storage.store_media_bytes(self.fixture.user, purpose="image", content_type="image/png",
                        payload=body, item_count=1, ttl_seconds=90 * 86400, lifecycle="cover_v1")
                return store(final_body), store(base_body), layout
            self.fixture.assets = assets
        saved, final, base = self.fixture.complete(claim)
        return saved, final, base

    def counts(self):
        return tuple(db.fetchone("SELECT (SELECT count(*) FROM cover_jobs),(SELECT count(*) FROM usage_records),"
            "(SELECT count(*) FROM idempotency_requests),(SELECT count(*) FROM public_trial_calls)"))

    def test_all_cover_routes_require_the_existing_authenticated_user_dependency(self):
        paths = {"/covers", "/covers/{job_id}", "/covers/{job_id}/download", "/covers/{job_id}/adjust",
                 "/reports/{report_type}/{report_id}/covers"}
        found = 0
        for route in api.app.routes:
            if getattr(route, "path", None) in paths:
                self.assertTrue(any(dep.call is api._auth.get_current_user for dep in route.dependant.dependencies), route.path)
                found += 1
        self.assertEqual(found, 6)

    def test_get_and_list_have_no_provider_no_schema_init_and_no_ddl(self):
        saved, _, _ = self.complete()
        statements = []
        original_conn = db.get_conn
        def traced_connection():
            conn = original_conn()
            conn.set_trace_callback(statements.append)
            return conn
        before = self.counts()
        with mock.patch.object(db, "get_conn", side_effect=traced_connection), \
                mock.patch.object(db, "init_db", side_effect=AssertionError("read initialized schema")), \
                mock.patch.object(jobs, "init_sqlite_schema", side_effect=AssertionError("read migrated schema")), \
                mock.patch.object(service, "run_next", side_effect=AssertionError("read started worker")):
            report_list = self.run_async(api.list_report_covers("analyze", self.report, self.user))
            my_list = self.run_async(api.list_my_covers(self.user))
            reopened = self.run_async(api.read_cover_job(saved["job_id"], self.user))
        self.assertTrue(report_list["enabled"])
        self.assertEqual(report_list["latest_success"]["job_id"], saved["job_id"])
        self.assertEqual(len(my_list["jobs"]), 1)
        self.assertEqual(reopened["job_id"], saved["job_id"])
        self.assertEqual(self.counts(), before)
        self.assertFalse(any(re.match(r"\s*(CREATE|ALTER|DROP)\b", sql, re.I) for sql in statements))

    def test_legacy_saved_quality_snapshot_reopens_and_adjusts_without_new_qc(self):
        saved, _, _ = self.complete()
        legacy_qc = json.loads(db.fetchone("SELECT qc_json FROM cover_jobs WHERE id=?", (saved["job_id"],))[0])
        self.assertNotIn("design_checks", legacy_qc)
        before = self.counts()
        before_balance = self.fixture.balances()
        import cover_runtime
        with mock.patch.object(cover_runtime, "_validate_qc", side_effect=AssertionError("legacy read must not revalidate")):
            reopened = self.run_async(api.read_cover_job(saved["job_id"], self.user))
            self.assertTrue(reopened["has_final"])
            self.assertTrue(self.run_async(api.download_cover(saved["job_id"], user=self.user)).body)
            adjusted = self.run_async(api.adjust_cover(saved["job_id"], api.CoverAdjustInput(
                text="真实门店", expected_revision=1), self.user))
        self.assertEqual(adjusted["asset_revision"], 2)
        self.assertEqual(adjusted["expires_at"], saved["expires_at"])
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.fixture.balances(), before_balance)

    def test_post_freezes_public_report_and_uses_canonical_request_uuid(self):
        request_id = str(uuid.uuid4())
        first = self.submit(self.request(request_id=request_id))
        self.assertTrue(first["created"])
        self.assertEqual(first["request_id"], request_id)
        self.assertEqual(first["billing"]["reserved_credits"], 8)
        self.assertEqual(first["billing"]["credits_used"], 0)
        frozen = json.loads(db.fetchone("SELECT input_json FROM cover_jobs WHERE id=?", (first["job_id"],))[0])
        self.assertEqual(frozen["title"], "真实门店")
        self.assertIn("保留主体", frozen["visual_advice"])
        self.assertEqual(frozen["source_items"], self.original["source_media_items"])
        self.assertNotIn("prepared", frozen)
        self.assertEqual(self.submit(self.request(request_id=request_id))["job_id"], first["job_id"])
        before = self.counts()
        for invalid in [request_id.upper(), "x" * 36]:
            with self.subTest(invalid=invalid), self.assertRaises(HTTPException) as error:
                self.submit(self.request(request_id=invalid))
            self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(ValidationError):
            self.request(request_id=uuid.uuid4().hex)
        self.assertEqual(self.counts(), before)

    def test_quote_change_and_insufficient_credit_are_structured_without_a_new_hold(self):
        before = self.counts()
        with self.assertRaises(HTTPException) as changed:
            self.submit(self.request(quote="old-quote-version"))
        self.assertEqual(changed.exception.status_code, 409)
        self.assertEqual(changed.exception.detail["code"], "BILLING_QUOTE_CHANGED")
        self.assertIs(changed.exception.detail["admitted"], False)
        self.assertEqual(changed.exception.detail["reserved_credits"], 0)
        self.assertEqual(self.counts(), before)
        db.execute("UPDATE credits SET balance=0 WHERE user_id=?", (self.fixture.user,))
        db.execute("UPDATE subscriptions SET used_monthly_credits=100000 WHERE user_id=?", (self.fixture.user,))
        with self.assertRaises(HTTPException) as insufficient:
            self.submit(self.request())
        self.assertEqual(insufficient.exception.status_code, 402)
        self.assertEqual(insufficient.exception.detail["code"], "QUOTA_EXCEEDED")
        self.assertIs(insufficient.exception.detail["admitted"], False)
        self.assertEqual(insufficient.exception.detail["reserved_credits"], 0)
        self.assertEqual(self.counts(), before)

    def test_other_user_cannot_submit_list_read_download_or_adjust_this_owners_cover(self):
        saved, _, _ = self.complete()
        before = self.counts()
        with mock.patch.object(storage, "load_media_bytes", side_effect=AssertionError("unauthorized media read")):
            operations = [
                lambda: self.submit(self.request(), user=self.other),
                lambda: self.run_async(api.list_report_covers("analyze", self.report, self.other)),
                lambda: self.run_async(api.read_cover_job(saved["job_id"], self.other)),
                lambda: self.run_async(api.download_cover(saved["job_id"], user=self.other)),
                lambda: self.run_async(api.adjust_cover(saved["job_id"],
                    api.CoverAdjustInput(text="别人的封面", expected_revision=1), self.other)),
            ]
            for operation in operations:
                with self.subTest(operation=operation), self.assertRaises(HTTPException) as denied:
                    operation()
                self.assertEqual(denied.exception.status_code, 404)
            self.assertEqual(self.run_async(api.list_my_covers(self.other))["jobs"], [])
        self.assertEqual(self.counts(), before)

    def test_download_is_actual_private_png_bytes_with_narrow_headers(self):
        saved, final, _ = self.complete()
        expected = storage.load_media_bytes(final.id, user_id=self.fixture.user, purpose="image")[1]
        response = self.run_async(api.download_cover(saved["job_id"], user=self.user))
        self.assertEqual(response.body, expected)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["content-disposition"], 'attachment; filename="noteai-cover.png"')
        with Image.open(io.BytesIO(response.body)) as image:
            self.assertEqual(image.size, (1776, 2368))

    def test_expired_source_rejects_new_submit_but_saved_cover_remains_readable(self):
        saved, _, _ = self.complete()
        future = self.fixture.now + timedelta(days=2)
        actual_utc = storage._utc
        before = self.counts()
        # Advance the test clock instead of rewriting immutable media TTL or
        # bypassing its integrity triggers. The source is 24h, cover is 90d.
        with mock.patch.object(jobs, "_now", return_value=future), \
                mock.patch.object(storage, "_utc", side_effect=lambda value=None: actual_utc(value or future)):
            with self.assertRaises(HTTPException) as expired:
                self.submit(self.request())
            self.assertEqual(expired.exception.status_code, 422)
            self.assertEqual(self.counts(), before)
            self.assertTrue(self.run_async(api.read_cover_job(saved["job_id"], self.user))["has_final"])
            response = self.run_async(api.download_cover(saved["job_id"], user=self.user))
            self.assertGreater(len(response.body), 100)

    def test_expired_report_disables_new_jobs_but_lists_and_reads_original_cover(self):
        saved, _, _ = self.complete()
        old = (self.fixture.now - timedelta(days=8)).isoformat()
        db.execute("UPDATE saved_diagnoses SET created_at=? WHERE id=?", (old, self.report))
        content_retention.record_content("diagnosis", self.report, self.fixture.user, created_at=old)
        self.assertNotEqual(content_retention.status("diagnosis", self.report, self.fixture.user)["state"], "active")
        listing = self.run_async(api.list_report_covers("analyze", self.report, self.user))
        self.assertFalse(listing["enabled"])
        self.assertIsNone(listing["quote"])
        self.assertEqual(listing["latest_success"]["job_id"], saved["job_id"])
        with self.assertRaises(HTTPException) as denied:
            self.submit(self.request())
        self.assertEqual(denied.exception.status_code, 404)
        self.assertTrue(self.run_async(api.read_cover_job(saved["job_id"], self.user))["has_final"])
        self.assertTrue(self.run_async(api.download_cover(saved["job_id"], user=self.user)).body)

    def test_adjust_none_keeps_current_position_and_safe_options_without_provider_or_charge(self):
        saved, _, _ = self.complete()
        row = db.fetchone("SELECT layout_json FROM cover_jobs WHERE id=?", (saved["job_id"],))
        original_layout = json.loads(row["layout_json"])
        self.assertEqual(saved["layout"]["position_options"], ["top", "bottom"])
        before_calls = db.fetchone("SELECT count(*) FROM public_trial_calls")[0]
        before_balance = self.fixture.balances()
        req = api.CoverAdjustInput(text="真实\n门店", expected_revision=1)
        self.assertIsNone(req.position)
        adjusted = self.run_async(api.adjust_cover(saved["job_id"], req, self.user))
        updated_layout = json.loads(db.fetchone("SELECT layout_json FROM cover_jobs WHERE id=?", (saved["job_id"],))[0])
        self.assertEqual(updated_layout["text_bbox"], original_layout["text_bbox"])
        self.assertEqual(adjusted["asset_revision"], 2)
        self.assertEqual(adjusted["expires_at"], saved["expires_at"])
        self.assertEqual(self.fixture.balances(), before_balance)
        self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], before_calls)

    def test_unsafe_position_is_not_offered_and_cannot_overwrite_original_success(self):
        saved, final, _ = self.complete(middle=False)
        self.assertEqual(saved["layout"]["position_options"], ["top"])
        before = self.counts()
        with self.assertRaises(HTTPException) as denied:
            self.run_async(api.adjust_cover(saved["job_id"], api.CoverAdjustInput(
                text="真实门店", position="bottom", expected_revision=1), self.user))
        self.assertEqual(denied.exception.status_code, 422)
        self.assertEqual(jobs.asset_reference(self.fixture.user, saved["job_id"]), final.id)
        self.assertEqual(jobs.get_job(self.fixture.user, saved["job_id"])["asset_revision"], 1)
        self.assertEqual(self.counts(), before)

    def test_disabled_feature_preserves_old_success_reads_and_free_adjustment(self):
        saved, _, _ = self.complete()
        self.readiness.return_value = (False, "封面功能尚未开放")
        listing = self.run_async(api.list_report_covers("analyze", self.report, self.user))
        self.assertFalse(listing["enabled"])
        self.assertEqual(listing["latest_success"]["job_id"], saved["job_id"])
        self.assertEqual(len(self.run_async(api.list_my_covers(self.user))["jobs"]), 1)
        self.assertTrue(self.run_async(api.download_cover(saved["job_id"], user=self.user)).body)
        adjusted = self.run_async(api.adjust_cover(saved["job_id"], api.CoverAdjustInput(
            text="真实门店", expected_revision=1), self.user))
        self.assertEqual(adjusted["asset_revision"], 2)
        with self.assertRaises(HTTPException) as denied:
            self.submit(self.request())
        self.assertEqual(denied.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
