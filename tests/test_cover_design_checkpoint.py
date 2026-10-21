"""Validated v2 design retention with temporary SQLite and no external network."""
import copy
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from tests import test_cover_layered_integration as layered_fixtures

import cover_design
import cover_jobs as jobs
import cover_renderer as renderer
import cover_runtime as runtime
import cover_service as service
import db


class CoverDesignCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.layered = layered_fixtures.LayeredCoverIntegrationTests()
        self.layered.setUp()
        self.addCleanup(self.layered.tearDown)
        for name in ("socket.create_connection", "socket.socket.connect_ex"):
            patch = mock.patch(name, side_effect=AssertionError("Offline checkpoint test"))
            patch.start()
            self.addCleanup(patch.stop)
        self.fixture = self.layered.f

    def claim(self, key="checkpoint"):
        job = self.layered.submit(key)
        return job, jobs.claim_job(job["job_id"])

    def snapshot(self, claim):
        context = runtime._report_context(claim["input_snapshot"])
        refs = [item["media_ref"] for item in claim["source_manifest"]]
        response = layered_fixtures.layered_plan(refs)
        drawing = cover_design.materialize_design_response(response, context)
        decision = cover_design.validate_design(drawing, context, set(refs))
        sources = [{"media_ref": ref, "width": 1671, "height": 941} for ref in refs]
        return json.loads(json.dumps({**decision,
            "input_brief": cover_design.build_design_brief(context, sources)}))

    def row(self, job):
        return db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (job["job_id"],))

    def assert_failed_without_delivery(self, job, code):
        row = self.row(job)
        self.assertEqual((row["status"], row["failure_code"], row["asset_revision"]), ("failed", code, 0))
        self.assertIsNone(row["final_media_ref"])
        self.assertIsNone(row["base_media_ref"])
        self.assertEqual(json.loads(row["qc_json"] or "{}"), {})
        self.assertEqual(db.fetchone("SELECT count(*) n FROM cover_asset_revisions WHERE job_id=?", (job["job_id"],))["n"], 0)
        financial = db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (job["job_id"],))
        self.assertEqual((financial["complete_applied"], financial["refund_applied"]), (0, 1))
        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?", (row["usage_id"],))[0], 0)

    def test_actual_render_overflow_retains_validated_plan_without_qc_or_assets(self):
        job, claim = self.claim()
        references_before = db.fetchone("SELECT count(*) FROM private_media_refs")[0]

        def narrow(plan):
            plan["text_layers"][0]["bbox"] = [.04, .02, .07, .115]

        with mock.patch.object(service, "_store_image", wraps=service._store_image) as store:
            result = service._run_claim(claim, runtime=self.layered.wrapper(design_mutation=narrow))
        self.assertEqual(result["failure_code"], "COVER_TEXT_OVERFLOW")
        self.assert_failed_without_delivery(job, "COVER_TEXT_OVERFLOW")
        store.assert_not_called()
        self.assertEqual(len(self.layered.requests), 1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM model_usage_records")[0], 1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM private_media_refs")[0], references_before)
        saved = json.loads(self.row(job)["design_json"])
        self.assertEqual(saved["text_layers"][0]["bbox"], [.04, .02, .07, .115])
        self.assertEqual(saved["text"], "周末咖啡\n时光")
        self.assertEqual(saved["input_brief"]["approved_titles"], ["周末咖啡时光"])
        self.assertNotIn("design_json", jobs.get_job(self.fixture.user, job["job_id"]))
        self.assertNotIn("design_snapshot", jobs.get_job(self.fixture.user, job["job_id"]))

    def test_real_checkpoint_write_failure_stops_before_compose_qc_and_storage(self):
        job, claim = self.claim()
        db.execute("CREATE TRIGGER checkpoint_write_failure BEFORE UPDATE OF design_json ON cover_jobs "
            "BEGIN SELECT RAISE(ABORT, 'offline checkpoint failure'); END")
        with mock.patch.object(renderer, "compose_sources") as compose, \
                mock.patch.object(service, "_store_image") as store:
            result = service._run_claim(claim, runtime=self.layered.wrapper())
        self.assertEqual(result["failure_code"], "COVER_DESIGN_CHECKPOINT_FAILED")
        self.assert_failed_without_delivery(job, "COVER_DESIGN_CHECKPOINT_FAILED")
        compose.assert_not_called()
        store.assert_not_called()
        self.assertEqual(len(self.layered.requests), 1)
        self.assertEqual(json.loads(self.row(job)["design_json"] or "{}"), {})

    def test_live_owner_fence_and_write_once_snapshot(self):
        job, claim = self.claim()
        snapshot = self.snapshot(claim)
        self.assertTrue(jobs.record_design_snapshot(claim, snapshot))
        self.assertFalse(jobs.record_design_snapshot(claim, copy.deepcopy(snapshot)))
        changed = {**snapshot, "background_color": "#000000"}
        with self.assertRaises(ValueError):
            jobs.record_design_snapshot(claim, changed)
        for key, value in (("user_id", self.fixture.other), ("request_id", str(uuid.uuid4())),
                           ("lease_token", "stale-token"), ("cover_fence", claim["cover_fence"] + 1)):
            with self.subTest(fence=key), self.assertRaises(ValueError):
                jobs.record_design_snapshot({**claim, key: value}, snapshot)
        expired = datetime.fromisoformat(self.row(job)["lease_expires_at"]) + timedelta(seconds=1)
        with self.assertRaises(ValueError):
            jobs.record_design_snapshot(claim, snapshot, now=expired)
        for status in ("queued", "failed", "outcome_unknown"):
            db.execute("UPDATE cover_jobs SET status=? WHERE id=?", (status, job["job_id"]))
            with self.subTest(status=status), self.assertRaises(ValueError):
                jobs.record_design_snapshot(claim, snapshot)
        db.execute("UPDATE cover_jobs SET status='running',deadline_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), job["job_id"]))
        with self.assertRaises(ValueError):
            jobs.record_design_snapshot(claim, snapshot)
        self.assertEqual(json.loads(self.row(job)["design_json"]), snapshot)

    def test_first_checkpoint_requires_design_stage(self):
        job, claim = self.claim()
        jobs.mark_stage(claim, "qc")
        with self.assertRaises(ValueError):
            jobs.record_design_snapshot(claim, self.snapshot(claim))
        self.assertEqual(json.loads(self.row(job)["design_json"] or "{}"), {})

    def test_successful_delivery_keeps_the_exact_checkpoint(self):
        original = jobs.record_design_snapshot
        snapshots = []
        claims = []

        def retain(claim, snapshot):
            claims.append(dict(claim))
            snapshots.append(json.loads(json.dumps(snapshot)))
            return original(claim, snapshot)

        with mock.patch.object(jobs, "record_design_snapshot", side_effect=retain):
            result = self.layered.complete()
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(json.loads(self.row(result)["design_json"]), snapshots[0])
        self.assertEqual(len(self.layered.requests), 2)
        self.assertEqual(result["billing"]["credits_used"], 8)
        with self.assertRaises(ValueError):
            jobs.record_design_snapshot(claims[0], snapshots[0])

    def test_completion_cannot_replace_checkpoint_before_asset_registration(self):
        job, claim = self.claim()
        snapshot = self.snapshot(claim)
        jobs.record_design_snapshot(claim, snapshot)
        sources = {item["media_ref"]: item["sha256"] for item in claim["source_manifest"]}
        selected = next(iter(sources))
        layout = {"schema_version": 2, "input_source_hashes": sources,
            "photos": [{"source_ref": selected, "source_sha256": sources[selected]}],
            "source_hashes": {selected: sources[selected]}, "base_sha256": "base-hash"}
        expiry = (datetime.now(timezone.utc) + timedelta(days=91)).isoformat()
        final = SimpleNamespace(id="fixture-final", content_sha256="final-hash", expires_at=expiry)
        base = SimpleNamespace(id="fixture-base", content_sha256="base-hash", expires_at=expiry)
        with mock.patch.object(jobs, "_layout", return_value="{}"), \
                mock.patch.object(jobs, "_verified_image", side_effect=[final, base]), \
                mock.patch.object(jobs.private_storage, "lock_ready_media_refs") as refs:
            with self.assertRaisesRegex(ValueError, "design snapshot changed"):
                jobs.complete_job(claim, final_media_ref=final.id, base_media_ref=base.id,
                    layout=layout, qc_passed=True, design_snapshot={**snapshot, "background_color": "#000000"})
        refs.assert_not_called()
        self.assertEqual(json.loads(self.row(job)["design_json"]), snapshot)
        self.assertEqual(self.row(job)["asset_revision"], 0)

    def test_v1_runtime_does_not_emit_the_new_checkpoint(self):
        self.fixture.policy = {**self.fixture.policy, "design_version": 1}
        job = self.layered.submit("v1-checkpoint-compatibility")
        claim = jobs.claim_job(job["job_id"])
        with mock.patch.object(jobs, "record_design_snapshot") as checkpoint:
            result = service._run_claim(claim, runtime=self.layered.h.wrapper())
        self.assertEqual(result["status"], "completed", result)
        checkpoint.assert_not_called()
        self.assertNotIn("schema_version", json.loads(self.row(job)["design_json"]))


if __name__ == "__main__":
    unittest.main()
