"""Offline durable cover progress; no provider, browser or production I/O."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest import mock

from tests import test_cover_agent_artifacts as artifact_fixtures
from tests.test_cover_runtime import approved_qc

import cover_agent_runtime
import cover_jobs as jobs
import cover_runtime
import cover_service
import db
import private_storage


class CoverProgressContractTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = artifact_fixtures.AgentArtifactTests()
        self.artifacts.setUp()
        self.addCleanup(self.artifacts.tearDown)
        self.fixture = self.artifacts.fixture
        for name in ("socket.create_connection", "socket.socket.connect_ex"):
            patch = mock.patch(name, side_effect=AssertionError("offline progress test"))
            patch.start()
            self.addCleanup(patch.stop)

    def row(self, job_id):
        return dict(db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (job_id,)))

    def observe(self, claim, phase, detail, *, revision=0, seconds=1):
        start = datetime.fromisoformat(jobs.get_job(self.fixture.user, claim["request_id"])["progress"]["execution_started_at"])
        return jobs.record_progress(claim, {"phase": phase, "detail_code": detail, "revision": revision},
            now=start + timedelta(seconds=seconds))

    def test_queue_start_heartbeat_and_phase_clocks_are_distinct(self):
        task = self.fixture.submit()
        self.assertEqual(task["progress"]["phase"], "queued")
        self.assertIsNone(task["progress"]["execution_started_at"])
        self.assertIsNone(task["progress"]["last_worker_seen_at"])
        claim = jobs.claim_job(task["job_id"])
        initial = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        start = datetime.fromisoformat(initial["execution_started_at"])
        self.assertEqual(initial["phase"], "source_check")
        self.assertTrue(self.observe(claim, "design", "planning", seconds=5))
        designed = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        jobs.heartbeat_job(claim, now=start + timedelta(seconds=35))
        seen = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        self.assertEqual(seen["phase_started_at"], designed["phase_started_at"])
        self.assertEqual(seen["execution_started_at"], initial["execution_started_at"])
        self.assertEqual(seen["last_worker_seen_at"], (start + timedelta(seconds=35)).isoformat())
        self.assertEqual(seen["detail_code"], "planning")
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_quality_revision_does_not_move_business_steps_backwards(self):
        task, claim = self.fixture.claim()
        for second, (phase, detail) in enumerate((("design", "planning"),
                ("concept", "generating_reference"), ("layout", "rendering"),
                ("qc", "checking_quality")), 1):
            self.assertTrue(self.observe(claim, phase, detail, seconds=second))
        before = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        jobs.mark_stage(claim, "design")  # Original legacy stage is retained.
        self.assertFalse(self.observe(claim, "design", "planning", seconds=5))
        self.assertTrue(self.observe(claim, "qc", "adjusting", revision=1, seconds=6))
        self.assertTrue(self.observe(claim, "qc", "rendering", revision=1, seconds=7))
        self.assertFalse(self.observe(claim, "qc", "checking_quality", revision=0, seconds=8))
        after = jobs.get_job(self.fixture.user, task["job_id"])
        self.assertEqual(after["stage"], "design")
        self.assertEqual((after["progress"]["phase"], after["progress"]["revision"]), ("qc", 1))
        self.assertEqual(after["progress"]["phase_started_at"], before["phase_started_at"])

    def test_progress_preserves_frozen_input_idempotency_and_candidate_design(self):
        task, claim = self.fixture.claim()
        row = self.row(task["job_id"])
        identity = dict(db.fetchone("SELECT payload_hash,key_hash FROM idempotency_requests WHERE id=?", (task["job_id"],)))
        self.observe(claim, "layout", "rendering")
        image = self.fixture.image(self.fixture.user)
        jobs.record_agent_candidate(claim, {"final_sha256": image.content_sha256,
            "source_hashes": {self.fixture.source.id: self.fixture.source.content_sha256}, "qc": None}, image.id)
        after = self.row(task["job_id"])
        for key in ("input_json", "source_manifest_json", "policy_json", "quote_version", "usage_id"):
            self.assertEqual(after[key], row[key])
        self.assertEqual(dict(db.fetchone("SELECT payload_hash,key_hash FROM idempotency_requests WHERE id=?", (task["job_id"],))), identity)
        saved = json.loads(after["design_json"])
        self.assertEqual(saved[jobs._PROGRESS_KEY]["phase"], "layout")
        self.assertEqual(saved["candidate_evidence"][0]["final_sha256"], image.content_sha256)
        public = jobs.get_job(self.fixture.user, task["job_id"])
        self.assertNotIn("design_json", public)
        self.assertNotIn("candidate_evidence", public["progress"])
        self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)

    def test_historical_and_invalid_metadata_fall_back_without_get_errors(self):
        task, claim = self.fixture.claim()
        original = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        cases = ["", "{}", "[]", "not-json", json.dumps({"private_path": "DO_NOT_EXPOSE"}),
            json.dumps({jobs._PROGRESS_KEY: {**original, "detail_code": "PRIVATE_TEXT"}}),
            json.dumps({jobs._PROGRESS_KEY: {**original, "last_worker_seen_at": "bad"}}),
            json.dumps({jobs._PROGRESS_KEY: {**original, "detail_code": ["bad"]}})]
        for encoded in cases:
            with self.subTest(encoded=encoded):
                db.execute("UPDATE cover_jobs SET design_json=? WHERE id=?", (encoded, task["job_id"]))
                public = jobs.get_job(self.fixture.user, task["job_id"])
                self.assertIsNone(public["progress"])
                self.assertEqual(public["stage"], "design")
                self.assertNotIn("DO_NOT_EXPOSE", json.dumps(public))
                self.assertFalse(jobs.record_progress(claim,
                    {"phase": "design", "detail_code": "planning", "revision": 0}))
        self.assertIsNone(jobs.get_job(self.fixture.other, task["job_id"]))

    def test_owner_fence_and_content_free_whitelist_are_enforced(self):
        task, claim = self.fixture.claim()
        before = self.row(task["job_id"])["design_json"]
        good = {"phase": "design", "detail_code": "planning", "revision": 0}
        for invalid in ({**good, "text": "PRIVATE_PROMPT"}, {**good, "detail_code": "arbitrary"},
                {**good, "revision": True}, {**good, "revision": 2}):
            with self.assertRaises(ValueError):
                jobs.record_progress(claim, invalid)
        for key, value in (("user_id", self.fixture.other), ("lease_token", "stale"),
                           ("cover_fence", claim["cover_fence"] + 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                jobs.record_progress({**claim, key: value}, good)
        self.assertEqual(self.row(task["job_id"])["design_json"], before)

    def test_metadata_write_failure_does_not_block_claim_or_lease_renewal(self):
        task = self.fixture.submit()
        db.execute("CREATE TRIGGER progress_write_failure BEFORE UPDATE OF design_json ON cover_jobs "
            "BEGIN SELECT RAISE(ABORT, 'offline metadata failure'); END")
        with self.assertLogs(level="WARNING"):
            claim = jobs.claim_job(task["job_id"])
        self.assertIsNotNone(claim)
        self.assertEqual(self.row(task["job_id"])["status"], "running")
        self.assertIsNone(jobs.get_job(self.fixture.user, task["job_id"])["progress"])
        db.execute("DROP TRIGGER progress_write_failure")
        jobs._observe_worker_progress(claim, datetime.now(timezone.utc), initialize=True)
        progress = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        original_lease = self.row(task["job_id"])["lease_expires_at"]
        db.execute("CREATE TRIGGER progress_write_failure BEFORE UPDATE OF design_json ON cover_jobs "
            "BEGIN SELECT RAISE(ABORT, 'offline metadata failure'); END")
        now = datetime.fromisoformat(progress["execution_started_at"]) + timedelta(seconds=30)
        with self.assertLogs(level="WARNING"):
            self.assertTrue(jobs.heartbeat_job(claim, now=now))
        self.assertGreater(self.row(task["job_id"])["lease_expires_at"], original_lease)
        self.assertEqual(jobs.get_job(self.fixture.user, task["job_id"])["progress"], progress)
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_unknown_recovery_retains_original_progress_without_new_claim(self):
        task, claim = self.fixture.claim()
        self.observe(claim, "design", "waiting_model")
        before = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        self.fixture.physical(claim, state="unknown", http=None)
        expiry = datetime.fromisoformat(self.row(task["job_id"])["lease_expires_at"])
        self.assertEqual(jobs.recover_jobs(now=expiry + timedelta(seconds=1)), [])
        result = jobs.get_job(self.fixture.user, task["job_id"])
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(result["progress"], before)
        self.assertIsNotNone(result["unknown_at"])
        self.assertIsNone(jobs.claim_job(task["job_id"]))
        self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 1)

    def test_service_observation_failure_still_saves_and_charges_once(self):
        task, claim, final, bundle, layout = self.artifacts.prepared()
        worker_progress = jobs.get_job(self.fixture.user, task["job_id"])["progress"]
        self.artifacts.settle(claim)
        _, png = private_storage.load_media_bytes(final.id, user_id=self.fixture.user)
        qc = {**approved_qc(), "final_sha256": layout["final_sha256"], "source_hashes": layout["source_hashes"]}
        def result(**kwargs):
            kwargs["hooks"].on_progress({"phase": "layout", "detail_code": "rendering", "revision": 0})
            design = {"schema_version": 3, jobs._PROGRESS_KEY: {**worker_progress,
                "phase": "saving", "detail_code": "storing"}}
            return cover_runtime.CoverResult(png, png, deepcopy(layout), design,
                qc, [], [], {"editable_bundle": bundle})
        # The fixture already owns the exact durable PNG/bundle. Reuse it while
        # injecting only observation failure; the next test covers storage retry.
        with mock.patch.object(cover_agent_runtime, "prepare_original_workspace"), \
                mock.patch.object(cover_agent_runtime, "cleanup_workspace"), \
                mock.patch.object(cover_service, "_store_image", return_value=final), \
                mock.patch.object(jobs, "record_progress", side_effect=RuntimeError("offline observation failure")), \
                self.assertLogs(level="WARNING"):
            saved = cover_service._run_claim(claim, runtime=result)
        self.assertEqual(saved["status"], "completed", saved)
        self.assertEqual(saved["billing"]["credits_used"], 8)
        self.assertEqual(self.fixture.balances()[1], 8)
        self.assertIsNotNone(saved["completed_at"])
        self.assertEqual(saved["progress"], worker_progress)
        again = jobs.get_job(self.fixture.user, task["job_id"])
        self.assertEqual(again["completed_at"], saved["completed_at"])
        self.assertEqual(self.fixture.balances()[1], 8)

    def test_service_waits_for_runtime_source_validation_before_design(self):
        task, claim = self.fixture.claim()
        phases = []
        def reject_invalid_source(**kwargs):
            phases.append(jobs.get_job(self.fixture.user, kwargs["job_id"])["progress"]["phase"])
            raise cover_runtime.CoverRuntimeError("COVER_OFFLINE_SOURCE_VALIDATION")
        with mock.patch.object(cover_agent_runtime, "prepare_original_workspace"), \
                mock.patch.object(cover_agent_runtime, "cleanup_workspace"):
            saved = cover_service._run_claim(claim, runtime=reject_invalid_source)
        self.assertEqual(phases, ["source_check"])
        self.assertEqual(saved["failure_code"], "COVER_OFFLINE_SOURCE_VALIDATION")
        self.assertEqual(saved["progress"]["phase"], "source_check")
        self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_existing_free_edit_recovery_keeps_progress_and_completion_time(self):
        original = self.artifacts.complete
        observed = {}
        def capture():
            values = original()
            observed.update(job_id=values[0]["job_id"], progress=values[-1]["progress"],
                completed_at=values[-1]["completed_at"])
            return values
        with mock.patch.object(self.artifacts, "complete", side_effect=capture):
            self.artifacts.test_free_edit_recovers_after_source_saved_but_png_save_failed()
        saved = jobs.get_job(self.fixture.user, observed["job_id"])
        self.assertEqual(saved["asset_revision"], 2)
        self.assertEqual(saved["progress"], observed["progress"])
        self.assertEqual(saved["completed_at"], observed["completed_at"])


if __name__ == "__main__":
    unittest.main()
