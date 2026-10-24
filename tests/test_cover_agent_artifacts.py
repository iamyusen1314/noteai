"""Offline source-bundle/settlement regression; no aesthetic claim or model IO."""
import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import billing
import cover_agent_artifacts as artifacts
import cover_jobs as jobs
import cover_service
import cover_settings
import db
import durable_ai
import private_storage
from tests import test_cover_jobs as fixtures


class AgentArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.fixture.policy = {**self.fixture.policy, "design_version": 3,
            "workflow_engine": "editable_design_opencode_v1", "max_physical_calls": None,
            "design_model": "doubao-seed-2-1-pro-260915"}

    def tearDown(self):
        self.fixture.tearDown()

    def prepared(self):
        task, claim = self.fixture.claim()
        source, source_bytes = private_storage.load_media_bytes(self.fixture.source.id,
            user_id=self.fixture.user, purpose="image")
        out = io.BytesIO()
        Image.new("RGB", (1776, 2368), "#557788").save(out, "PNG")
        png = out.getvalue()
        files = {"index.html": b"<html><head></head><body>offline contract fixture</body></html>",
            "assets/source.png": source_bytes, "poster.json": b"{}", "out/poster.png": png}
        constraints = {"sources": [{"ref": source.id, "path": "assets/source.png", "sha256": source.content_sha256}],
            "text_layers": [{"id": "title", "allowed_rect": {"x": 0, "y": 0, "width": 1776, "height": 400}}],
            "protected_regions": [{"x": 0, "y": 500, "width": 1776, "height": 1500}]}
        manifest = {"schema_version": artifacts.SCHEMA, "status": "RENDERED", "model_calls": 0,
            "constraints": constraints, "checks": {"width": 1776, "height": 2368, "external_requests": 0,
                "boxes": [{"id": "title", "text": "真实门店", "rect": {"x": 20, "y": 20, "width": 600, "height": 100}}]},
            "files": [{"path": path, "bytes": len(body), "sha256": artifacts.digest(body)} for path, body in files.items()],
            "qc_status": "NOT_VISUALLY_REVIEWED"}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name, body in files.items():
                file = directory / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(body)
            raw = json.dumps(manifest).encode()
            (directory / "render-manifest.json").write_bytes(raw)
            result = {"revision_dir": temporary, "manifest_sha256": artifacts.digest(raw), "png_sha256": artifacts.digest(png)}
            final, bundle, layout = artifacts.capture(result, expected_sources={source.id: source.content_sha256})
        # Existing PNG storage is reused; source retention starts afterwards.
        final_ref = private_storage.store_media_bytes(self.fixture.user, purpose="image", content_type="image/png",
            payload=final, item_count=1, ttl_seconds=90 * 86400, lifecycle="cover_v1")
        layout["editable_ref"] = artifacts.store(self.fixture.user, task["job_id"], bundle)
        return task, claim, final_ref, bundle, layout

    def settle(self, claim, *, designs=4):
        for stage, count in (("design", designs), ("qc", 1)):
            for ordinal in range(1, count + 1):
                call = str(uuid.uuid4())
                jobs.before_text_call(claim, stage + ":" + str(ordinal), call)
                self.fixture.physical(claim, call_id=call)
                billing.record_model_usage("doubao", "doubao-seed-2-1-pro-260915", tokens_in=100,
                    tokens_out=10, usage_status="complete", physical_call_id=call)
        self.fixture.image_call(claim)

    def complete(self):
        task, claim, final, bundle, layout = self.prepared()
        self.settle(claim)
        qc = {"passed": True, "final_sha256": layout["final_sha256"], "source_hashes": layout["source_hashes"]}
        result = jobs.complete_job(claim, final_media_ref=final.id, base_media_ref=final.id,
            layout=layout, qc_passed=True, qc_snapshot=qc, design_snapshot={"schema_version": 3})
        return task, claim, final, bundle, layout, result

    def test_more_than_three_calls_one_settlement_and_owner_reopen(self):
        task, claim, final, bundle, layout, result = self.complete()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["billing"]["credits_used"], 8)
        self.assertEqual(artifacts.validate_saved(self.fixture.user, jobs.get_layout(self.fixture.user, task["job_id"])), bundle)
        self.assertEqual(result["layout"]["engine"], "editable_design")
        self.assertNotIn("editable_ref", result["layout"])
        again = jobs.complete_job(claim, final_media_ref=final.id, base_media_ref=final.id, layout=layout, qc_passed=True)
        self.assertEqual(again["asset_revision"], 1)
        self.assertEqual(self.fixture.balances()[1], 8)
        with self.assertRaises(Exception):
            artifacts.load(self.fixture.other, layout)

    def test_saved_source_survives_orphan_reconcile_and_original_photo_expiry(self):
        task, claim, final, bundle, layout, _ = self.complete()
        future = self.fixture.now + timedelta(days=2)
        result = private_storage.reconcile_orphans(prefix="v1/payload", now=future, apply=True)
        self.assertEqual(result["deleted_count"], 0)
        private_storage.expire_media(now=future)
        self.assertEqual(artifacts.validate_saved(self.fixture.user, layout), bundle)

    def test_account_and_expiry_cleanup_include_editable_sources(self):
        _, _, _, _, layout, _ = self.complete()
        private_storage.delete_user_media(self.fixture.user)
        with self.assertRaises(Exception):
            artifacts.load(self.fixture.user, layout)

    def test_source_candidate_is_managed_before_png_or_revision_commit(self):
        task, claim, final, bundle, layout = self.prepared()
        self.assertEqual(db.fetchone("SELECT count(*) FROM cover_asset_revisions")[0], 0)
        subject = layout["editable_ref"]["subject_hash"]
        with db.transaction(write=False) as tx:
            count, size = artifacts.active_bundle_totals(tx, subject)
        self.assertEqual((count, size), (1, len(bundle)))
        private_storage.reconcile_orphans(prefix="v1/payload", now=self.fixture.now + timedelta(days=2), apply=True)
        self.assertEqual(artifacts.load(self.fixture.user, layout), bundle)
        private_storage.delete_user_media(self.fixture.user)
        with self.assertRaises(Exception):
            artifacts.load(self.fixture.user, layout)
        with db.transaction(write=False) as tx:
            self.assertEqual(artifacts.active_bundle_totals(tx, subject), (0, 0))

    def test_wrong_final_hash_and_unknown_call_cannot_settle(self):
        task, claim, final, bundle, layout = self.prepared()
        self.settle(claim)
        layout["final_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "FINAL_CHANGED"):
            jobs.complete_job(claim, final_media_ref=final.id, base_media_ref=final.id, layout=layout, qc_passed=True)
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_different_png_with_matching_layout_and_qc_cannot_replace_source_bundle(self):
        task, claim, final, bundle, layout = self.prepared()
        self.settle(claim)
        replacement = self.fixture.image(self.fixture.user)
        layout["final_sha256"] = replacement.content_sha256
        with self.assertRaisesRegex(ValueError, "FINAL_CHANGED"):
            jobs.complete_job(claim, final_media_ref=replacement.id, base_media_ref=replacement.id,
                layout=layout, qc_passed=True, qc_snapshot={"passed": True,
                    "final_sha256": replacement.content_sha256, "source_hashes": layout["source_hashes"]})
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_public_edit_text_is_bound_to_actual_editable_source(self):
        _, _, _, _, layout = self.prepared()
        layout["text"] = "被替换的界面文案"
        with self.assertRaisesRegex(ValueError, "TEXT_CHANGED"):
            artifacts.validate_saved(self.fixture.user, layout)

    def test_normal_upload_counts_existing_bundle_bytes_and_objects(self):
        _, _, final, bundle, _, _ = self.complete()
        self.assertEqual(artifacts.active_bundle_totals(db, final.subject_hash), (1, len(bundle)))
        media = db.fetchone("SELECT count(*) n,COALESCE(sum(size_bytes),0) bytes "
            "FROM private_media_refs WHERE subject_hash=? AND state='ready'", (final.subject_hash,))
        quota = 10 * 1024 * 1024
        size = quota - media["bytes"] - len(bundle) // 2
        out = io.BytesIO()
        Image.new("RGB", (32, 24), "#123456").save(out, "PNG")
        # Valid PNG pixels with opaque trailing bytes, accepted by the normal
        # upload parser. This exact size exceeded the combined quota before
        # editable sources participated in its existing capacity check.
        body = out.getvalue() + b"\0" * (size - len(out.getvalue()))
        with mock.patch.dict(os.environ, {"NOTEAI_MEDIA_MAX_BYTES_PER_USER": str(quota)}):
            with self.assertRaises(private_storage.MediaCapacityExceeded):
                private_storage.store_media_bytes(self.fixture.user, purpose="image", content_type="image/png",
                    payload=body, item_count=1, ttl_seconds=86400)
        with mock.patch.dict(os.environ, {"NOTEAI_MEDIA_MAX_OBJECTS_PER_USER": str(media["n"] + 1)}):
            with self.assertRaises(private_storage.MediaCapacityExceeded):
                self.fixture.image(self.fixture.user, small=True)
        after = db.fetchone("SELECT count(*) n,COALESCE(sum(size_bytes),0) bytes "
            "FROM private_media_refs WHERE subject_hash=? AND state='ready'", (final.subject_hash,))
        self.assertEqual((after["n"], after["bytes"]), (media["n"], media["bytes"]))

    def test_expiry_bounds_bundle_deletion_and_releases_quota_after_actual_delete(self):
        deliveries = [self.complete(), self.complete()]
        balances_before_cleanup = self.fixture.balances()
        subject = deliveries[0][2].subject_hash
        original_bytes = sum(len(item[3]) for item in deliveries)
        original_layouts = {row["job_id"]: row["layout_json"] for row in
            db.fetchall("SELECT job_id,layout_json FROM cover_asset_revisions")}
        self.assertEqual(artifacts.active_bundle_totals(db, subject), (2, original_bytes))
        future = self.fixture.now + timedelta(days=91)
        self.assertEqual(artifacts.delete_bundles(user_id=self.fixture.user, expired_only=True,
            backend=self.fixture.backend, now=future, limit=1), 1)
        rows = db.fetchall("SELECT r.job_id,r.layout_json,j.design_json FROM cover_asset_revisions r "
            "JOIN cover_jobs j ON j.id=r.job_id WHERE j.user_id=?", (self.fixture.user,))
        states = []
        remaining_bytes = 0
        for row in rows:
            ref = artifacts.reference(json.loads(row["layout_json"])["editable_ref"])
            key = private_storage._payload_key(ref.id, ref.subject_hash, ref.purpose)
            design = json.loads(row["design_json"])
            deleted = design.get("editable_source_deletions", {})
            states.append("deleted" if ref.id in deleted else "ready")
            self.assertEqual(row["layout_json"], original_layouts[row["job_id"]])
            self.assertEqual(ref.state, "ready")  # Original revision remains immutable.
            self.assertEqual(design["schema_version"], 3)
            if ref.id in deleted:
                self.assertEqual(deleted[ref.id], future.isoformat())
                self.assertIsNone(self.fixture.backend.head(key))
                with self.assertRaises(durable_ai.PayloadUnavailable):
                    artifacts.load(self.fixture.user, json.loads(row["layout_json"]))
            else:
                self.assertIsNotNone(self.fixture.backend.head(key))
                remaining_bytes += ref.size_bytes
        self.assertEqual(sorted(states), ["deleted", "ready"])
        # The second source has passed its TTL but physically remains ready.
        self.assertEqual(artifacts.active_bundle_totals(db, subject), (1, remaining_bytes))
        private_storage.expire_media(user_id=self.fixture.user, now=future, limit=1,
            backend=self.fixture.backend)
        self.assertEqual(artifacts.active_bundle_totals(db, subject), (0, 0))
        self.assertEqual(artifacts.delete_bundles(user_id=self.fixture.user, expired_only=True,
            backend=self.fixture.backend, now=future, limit=1), 0)
        self.assertEqual(self.fixture.balances(), balances_before_cleanup)

    def test_free_edit_recovers_after_source_saved_but_png_save_failed(self):
        task, _, _, bundle, layout, _ = self.complete()
        balances = self.fixture.balances()
        calls = db.fetchone("SELECT count(*) n FROM public_trial_calls")["n"]
        def candidate(name):
            value = json.loads(bundle)
            manifest = json.loads(base64.b64decode(value["files"]["render-manifest.json"]))
            manifest.update(revision=name, qc_status="USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
            raw = json.dumps(manifest).encode()
            value["files"]["render-manifest.json"] = base64.b64encode(raw).decode()
            value["manifest_sha256"] = artifacts.digest(raw)
            updated = deepcopy(layout)
            updated.update(manifest_sha256=artifacts.digest(raw),
                qc_status="USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
            updated.pop("editable_ref", None)
            return base64.b64decode(value["files"]["out/poster.png"]), json.dumps(value).encode(), updated
        # The real CLI adds a new revision/time on each render. Simulate only
        # those local CLI results; retain real source storage, PNG persistence,
        # source validation, revision CAS and existing customer accounting.
        with mock.patch.object(artifacts, "cli", return_value={}), \
                mock.patch.object(artifacts, "capture", return_value=candidate("first-render")):
            with mock.patch.object(private_storage, "store_media_bytes",
                    side_effect=private_storage.ObjectStorageUnavailable("FIXTURE_PNG_SAVE_FAILED")):
                with self.assertRaises(private_storage.ObjectStorageUnavailable):
                    cover_service.adjust(self.fixture.user, task["job_id"], text="真实门店", position=None,
                        expected_revision=1, layer_id="title")
        self.assertEqual(jobs.get_job(self.fixture.user, task["job_id"])["asset_revision"], 1)
        with mock.patch.object(artifacts, "cli", return_value={}), \
                mock.patch.object(artifacts, "capture", return_value=candidate("second-render")):
            result = cover_service.adjust(self.fixture.user, task["job_id"], text="真实门店", position=None,
                expected_revision=1, layer_id="title")
        self.assertEqual(result["asset_revision"], 2)
        self.assertEqual(result["layout"]["qc_status"], "USER_ADJUSTED_NOT_VISUALLY_REVIEWED")
        self.assertEqual(self.fixture.balances(), balances)
        self.assertEqual(db.fetchone("SELECT count(*) n FROM public_trial_calls")["n"], calls)

    def test_v3_first_bundle_save_failure_releases_without_replaying_sdk(self):
        import shutil
        import socket
        import httpx
        import cover_agent_runtime as runtime

        if not os.environ.get("NOTEAI_COVER_HOST_NODE_MODULES") or not shutil.which("node"):
            self.skipTest("Explicit local SDK installation and Node are required")

        # Reuse the real metered SDK/CLI fixture, with one synthetic source.
        # Only supplier HTTP responses and the final bundle write are replaced.
        from tests.frontend_cover_agent_http import MeteredScriptedBridge, TITLE, synthetic_png

        class SingleSourceBridge(MeteredScriptedBridge):
            instances = []

            def respond_image(bridge, request):
                self.assertEqual(request.url.path, "/api/v3/images/generations")
                payload = json.loads(request.content)
                self.assertIsInstance(payload["image"], str)
                raw = base64.b64decode(payload["image"].split(",", 1)[1], validate=True)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), bridge.sources[0]["sha256"])
                bridge.wire_requests.append({"stage": "image", "input_images": 1,
                    "model": payload["model"], "http_status": 200})
                return httpx.Response(200, json={"model": payload["model"],
                    "data": [{"b64_json": base64.b64encode(
                        synthetic_png((1776, 2368), "#A1A8B1")).decode(), "size": "1776x2368"}],
                    "usage": {"input_images": 1, "generated_images": 1}},
                    headers={"x-request-id": "synthetic-single-source-save-failure"})

        config = cover_settings.editable_defaults()
        config.update(enabled=True, account_verified=True,
            account_evidence_ref="SYNTHETIC_LOCAL_SAVE_FAILURE_FIXTURE")
        self.fixture.policy = cover_settings.policy_snapshot(config)
        self.fixture.input = {"title": TITLE, "body": "单图合成保存失败技术测试。",
            "title_variants": [], "domain": "其他", "visual_advice": "保留合成原图和独立文字。"}
        source = private_storage.store_media_bytes(self.fixture.user, purpose="image", content_type="image/png",
            payload=synthetic_png((1671, 941), "#406050"), item_count=1, ttl_seconds=86400)
        self.fixture.source = source
        before_balances = self.fixture.balances()
        before_images = db.fetchone("SELECT count(*) n FROM private_media_refs WHERE state='ready'")["n"]
        saved = {}

        def original_rows(table, usage_id):
            column = "usage_record_id" if table in {"public_trial_calls", "model_usage_records"} else "usage_id"
            return [dict(row) for row in db.fetchall(
                "SELECT * FROM " + table + " WHERE " + column + "=? ORDER BY id", (usage_id,))]

        def fail_bundle(user_id, job_id, bundle):
            self.assertEqual((user_id, job_id), (self.fixture.user, task["job_id"]))
            self.assertIsInstance(bundle, bytes)
            saved["calls"] = original_rows("public_trial_calls", usage_id)
            saved["models"] = original_rows("model_usage_records", usage_id)
            saved["images"] = original_rows("cover_image_usage", usage_id)
            saved["ready_images"] = db.fetchone("SELECT count(*) n FROM private_media_refs WHERE state='ready'")["n"]
            raise private_storage.ObjectStorageUnavailable("FIXTURE_V3_FIRST_BUNDLE_SAVE_FAILED")

        def run(**kwargs):
            try:
                return runtime.run_cover(**kwargs, bridge_class=SingleSourceBridge)
            except Exception as exc:
                import traceback
                saved["runtime_error"] = {"class": type(exc).__name__, "code": getattr(exc, "code", None),
                    "frames": [(Path(frame.filename).name, frame.lineno, frame.name)
                        for frame in traceback.extract_tb(exc.__traceback__)]}
                raise

        with mock.patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": "",
                "NOTEAI_PUBLIC_PRODUCT": "0", "NOTEAI_ARK_API_KEY": "offline-save-failure-fixture",
                "NOTEAI_COVER_AGENT_STATE_ROOT": str(Path(self.fixture.temp.name) / "agent-jobs")}), \
                mock.patch.object(socket.socket, "connect", side_effect=AssertionError("External network forbidden")), \
                mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("External network forbidden")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("External DNS forbidden")):
            task = self.fixture.submit(key="v3-first-bundle-save-failed")
            usage_id = db.fetchone("SELECT usage_id FROM cover_jobs WHERE id=?", (task["job_id"],))["usage_id"]
            with mock.patch.object(artifacts, "store", side_effect=fail_bundle) as store:
                result = cover_service.run_next(runtime=run)
            self.assertEqual(store.call_count, 1, {"job": result, "runtime_error": saved.get("runtime_error")})
            self.assertEqual((result["status"], result["billing"]["status"],
                result["billing"]["credits_used"]), ("failed", "released", 0))
            self.assertFalse(result["has_final"])
            self.assertEqual(result["asset_revision"], 0)
            self.assertEqual(self.fixture.balances(), before_balances)
            self.assertEqual(db.fetchone("SELECT count(*) n FROM cover_asset_revisions")["n"], 0)
            # Both normal PNG writes completed before the editable bundle failed.
            self.assertGreaterEqual(saved["ready_images"], before_images + 2)
            self.assertEqual(len(saved["calls"]), 9)
            self.assertTrue(all(row["state"] == "responded" and row["http_status"] == 200 for row in saved["calls"]))
            self.assertEqual(len(saved["models"]), 8)
            self.assertEqual(len(saved["images"]), 1)
            image = saved["images"][0]
            self.assertEqual((image["state"], image["cost_status"], image["billed_images"]), ("responded", "estimated", 1))
            self.assertIsNone(image["actual_cost"])
            usage = dict(db.fetchone("SELECT * FROM usage_records WHERE id=?", (usage_id,)))
            self.assertEqual(usage["credits_used"], 0)
            self.assertGreater(usage["actual_model_cost_rmb"], 0)
            self.assertAlmostEqual(usage["estimated_cost_rmb"],
                usage["actual_model_cost_rmb"] + float(image["estimated_cost"]))
            financial = db.fetchone("SELECT complete_applied,refund_applied FROM idempotency_requests WHERE id=?", (task["job_id"],))
            self.assertEqual(tuple(financial), (0, 1))
            self.assertEqual(jobs.get_job(self.fixture.user, task["job_id"])["status"], "failed")
            duplicate = self.fixture.submit(key="v3-first-bundle-save-failed")
            self.assertFalse(duplicate["created"])
            self.assertEqual(duplicate["job_id"], task["job_id"])
            self.assertIsNone(jobs.claim_job(task["job_id"]))
            for _ in range(2):
                self.assertIsNone(cover_service.run_next(runtime=run))
            for table, key in (("public_trial_calls", "calls"), ("model_usage_records", "models"),
                               ("cover_image_usage", "images")):
                self.assertEqual(original_rows(table, usage_id), saved[key])
            self.assertEqual(dict(db.fetchone("SELECT * FROM usage_records WHERE id=?", (usage_id,))), usage)
            self.assertEqual(len(SingleSourceBridge.instances), 1)
            self.assertEqual(len(SingleSourceBridge.instances[0].wire_requests), 9)

    def test_old_and_new_settings_are_explicit_and_valid(self):
        old = cover_settings.defaults()
        self.assertNotIn("workflow_engine", cover_settings.validate(old))
        config = cover_settings.editable_defaults()
        config.update(enabled=True, account_verified=True, account_evidence_ref="offline-model-account-fixture")
        policy = cover_settings.policy_snapshot(config)
        self.assertEqual(policy["design_version"], 3)
        self.assertIsNone(policy["max_physical_calls"])
        jobs._policy(policy)


if __name__ == "__main__":
    unittest.main()
