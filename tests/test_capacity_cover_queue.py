"""Offline first-claim cover execution windows on the original SQLite ledgers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import socket
import unittest
from unittest import mock

from tests import test_cover_jobs as original


jobs, db = original.jobs, original.db


class CoverQueueWindowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = original.CoverJobsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.mode = mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "1"})
        self.mode.start()
        self.addCleanup(self.mode.stop)
        for name in ("connect", "connect_ex"):
            patch = mock.patch.object(socket.socket, name, side_effect=AssertionError("network forbidden"))
            patch.start()
            self.addCleanup(patch.stop)
        self.created = self.fixture.now

    def rows(self, job_id):
        return (dict(db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (job_id,))),
                dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (job_id,))))

    def test_first_claim_after_twenty_five_queued_minutes_keeps_full_execution_window(self):
        task = self.fixture.submit(now=self.created)
        before_job, before_financial = self.rows(task["job_id"])
        before_balances = self.fixture.balances()
        start = self.created + timedelta(minutes=25)
        claim = jobs.claim_job(task["job_id"], now=start)
        self.assertIsNotNone(claim)
        job, financial = self.rows(task["job_id"])
        expected = (start + timedelta(seconds=jobs.HOLD_SECONDS)).isoformat()
        self.assertEqual(job["deadline_at"], expected)
        self.assertEqual(financial["lease_expires_at"], expected)
        self.assertEqual(job["lease_expires_at"], (start + timedelta(seconds=300)).isoformat())
        self.assertEqual((job["status"], job["stage"], job["lease_fence"]), ("running", "design", 1))
        self.assertEqual(job["created_at"], before_job["created_at"])
        self.assertEqual(claim["charge"]["usage_id"], before_financial["usage_id"])
        self.assertEqual((financial["complete_applied"], financial["refund_applied"]), (0, 0))
        self.assertEqual(self.fixture.balances(), before_balances)
        self.assertEqual(db.fetchone("SELECT count(*) n FROM public_trial_calls")["n"], 0)

    def test_exact_queue_expiry_cannot_be_revived_and_releases_original_hold_once(self):
        task = self.fixture.submit(now=self.created)
        before = self.rows(task["job_id"])
        expiry = self.created + timedelta(seconds=jobs.HOLD_SECONDS)
        self.assertIsNone(jobs.claim_job(task["job_id"], now=expiry))
        self.assertEqual(self.rows(task["job_id"]), before)
        self.assertIsNone(jobs.claim_job(task["job_id"], now=expiry + timedelta(microseconds=1)))
        self.assertEqual(jobs.release_expired_unknowns(now=expiry), 1)
        self.assertEqual(jobs.release_expired_unknowns(now=expiry), 0)
        job, financial = self.rows(task["job_id"])
        self.assertEqual((job["status"], job["failure_code"]), ("failed", "cover_queue_expired"))
        self.assertEqual((financial["refund_applied"], financial["complete_applied"]), (1, 0))
        self.assertEqual(self.fixture.balances()[1], 0)
        task = self.fixture.submit(now=self.created)
        just_before = expiry - timedelta(microseconds=1)
        self.assertIsNotNone(jobs.claim_job(task["job_id"], now=just_before))
        self.assertEqual(self.rows(task["job_id"])[0]["deadline_at"],
                         (just_before + timedelta(seconds=jobs.HOLD_SECONDS)).isoformat())

    def test_capacity_claim_rechecks_clock_after_row_locks_before_renewal(self):
        task = self.fixture.submit(now=self.created)
        before = self.rows(task["job_id"])
        expiry = self.created + timedelta(seconds=jobs.HOLD_SECONDS)
        # The claim entered just before expiry, then obtained its row locks at
        # the boundary. Its entry timestamp must not revive an expired queue.
        with mock.patch.object(jobs, "_now", side_effect=[expiry - timedelta(microseconds=1), expiry]) as clock:
            self.assertIsNone(jobs.claim_job(task["job_id"]))
            self.assertEqual(clock.call_count, 2)
        self.assertEqual(self.rows(task["job_id"]), before)

    def test_running_repeat_and_provider_free_recovery_do_not_renew_window_or_break_fence(self):
        task = self.fixture.submit(now=self.created)
        start = self.created + timedelta(minutes=25)
        original_claim = jobs.claim_job(task["job_id"], now=start)
        first = self.rows(task["job_id"])
        self.assertIsNone(jobs.claim_job(task["job_id"], now=start + timedelta(minutes=1)))
        self.assertEqual(self.rows(task["job_id"]), first)
        recovery = start + timedelta(seconds=301)
        self.assertEqual(jobs.recover_jobs(now=recovery), [task["job_id"]])
        recovered_claim = jobs.claim_job(task["job_id"], now=recovery + timedelta(seconds=1))
        recovered, financial = self.rows(task["job_id"])
        self.assertEqual(recovered["deadline_at"], first[0]["deadline_at"])
        self.assertEqual(financial["lease_expires_at"], first[1]["lease_expires_at"])
        self.assertGreater(recovered_claim["cover_fence"], original_claim["cover_fence"])
        with self.assertRaises(ValueError):
            jobs.mark_stage(original_claim, "image", now=recovery + timedelta(seconds=2))
        self.assertTrue(jobs.mark_stage(recovered_claim, "image", now=recovery + timedelta(seconds=2)))
        self.assertEqual(financial["lease_token_hash"], recovered["lease_token_hash"])

    def test_existing_intent_physical_or_unknown_never_receives_a_new_window(self):
        for case in ("intent", "dispatched", "responded", "unknown", "unknown_marker", "unknown_status"):
            with self.subTest(case=case):
                task = self.fixture.submit(now=self.created)
                row, _ = self.rows(task["job_id"])
                if case == "intent":
                    db.execute("UPDATE cover_jobs SET call_intents_json=? WHERE id=?",
                               ('{"design":"retained-original-intent"}', task["job_id"]))
                elif case in {"dispatched", "responded", "unknown"}:
                    self.fixture.physical({"user_id": self.fixture.user,
                        "charge": {"usage_id": row["usage_id"]}}, state=case,
                        http=200 if case == "responded" else None)
                elif case == "unknown_marker":
                    db.execute("UPDATE cover_jobs SET unknown_at=? WHERE id=?",
                               (self.created.isoformat(), task["job_id"]))
                else:
                    db.execute("UPDATE cover_jobs SET status='outcome_unknown',stage='outcome_unknown' WHERE id=?",
                               (task["job_id"],))
                before = self.rows(task["job_id"])
                physical = [dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")]
                self.assertIsNone(jobs.claim_job(task["job_id"], now=self.created + timedelta(minutes=25)))
                self.assertEqual(self.rows(task["job_id"]), before)
                self.assertEqual([dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")], physical)

    def test_settled_or_expired_original_financial_fence_is_not_extended(self):
        for case in ("complete", "released", "failed", "financial_expired", "legacy"):
            with self.subTest(case=case):
                task = self.fixture.submit(now=self.created)
                if case == "complete":
                    sql = "UPDATE idempotency_requests SET complete_applied=1 WHERE id=?"
                elif case == "released":
                    sql = "UPDATE idempotency_requests SET refund_applied=1 WHERE id=?"
                elif case == "failed":
                    sql = "UPDATE idempotency_requests SET status='failed' WHERE id=?"
                elif case == "legacy":
                    sql = "UPDATE idempotency_requests SET charge_source='credits' WHERE id=?"
                else:
                    db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
                               ((self.created + timedelta(minutes=25)).isoformat(), task["job_id"]))
                    sql = None
                if sql:
                    db.execute(sql, (task["job_id"],))
                before = self.rows(task["job_id"])
                self.assertIsNone(jobs.claim_job(task["job_id"], now=self.created + timedelta(minutes=25)))
                self.assertEqual(self.rows(task["job_id"]), before)

    def test_concurrent_first_claim_extends_once_and_both_deadlines_rollback_atomically(self):
        task = self.fixture.submit(now=self.created)
        before = self.rows(task["job_id"])
        original_execute = db.Transaction.execute
        def fail_financial_update(tx, sql, params=()):
            if sql.startswith("UPDATE idempotency_requests SET lease_token_hash="):
                raise RuntimeError("controlled precommit financial update failure")
            return original_execute(tx, sql, params)
        start = self.created + timedelta(minutes=25)
        with mock.patch.object(db.Transaction, "execute", new=fail_financial_update):
            with self.assertRaises(RuntimeError):
                jobs.claim_job(task["job_id"], now=start)
        self.assertEqual(self.rows(task["job_id"]), before)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: jobs.claim_job(task["job_id"], now=start), range(4)))
        self.assertEqual(sum(result is not None for result in results), 1)
        job, financial = self.rows(task["job_id"])
        self.assertEqual(job["lease_fence"], 1)
        self.assertEqual(job["deadline_at"], (start + timedelta(seconds=jobs.HOLD_SECONDS)).isoformat())
        self.assertEqual(financial["lease_expires_at"], job["deadline_at"])
        self.assertEqual(financial["lease_token_hash"], job["lease_token_hash"])

    def test_capacity_off_keeps_original_total_thirty_minute_deadline(self):
        task = self.fixture.submit(now=self.created)
        before = self.rows(task["job_id"])
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0"}):
            self.assertIsNotNone(jobs.claim_job(task["job_id"], now=self.created + timedelta(minutes=25)))
        job, financial = self.rows(task["job_id"])
        self.assertEqual(job["deadline_at"], before[0]["deadline_at"])
        self.assertEqual(financial["lease_expires_at"], before[1]["lease_expires_at"])
        self.assertEqual(job["lease_expires_at"], before[0]["deadline_at"])
        self.assertEqual(jobs.quote_for_user(self.fixture.user, policy_snapshot=self.fixture.policy)["credits"], 8)

    def test_extended_first_claim_still_saves_png_then_settles_original_eight_once(self):
        task = self.fixture.submit(now=self.created)
        start = self.created + timedelta(minutes=25)
        claim = jobs.claim_job(task["job_id"], now=start)
        original_now, original_utc = jobs._now, original.private_storage._utc
        with mock.patch.object(jobs, "_now", side_effect=lambda value=None: original_now(value or start)), \
             mock.patch.object(original.private_storage, "_utc", side_effect=lambda value=None: original_utc(value or start)), \
             mock.patch.object(original.postdelivery.idempotency, "_now", return_value=start):
            self.fixture.image_call(claim)
            saved, final, _ = self.fixture.complete(claim)
            self.assertEqual((saved["status"], saved["billing"]["credits_used"]), ("completed", 8))
            repeated = jobs.complete_job(claim, final_media_ref="unused", base_media_ref="unused",
                                        layout={}, qc_passed=False)
            self.assertEqual(repeated["job_id"], saved["job_id"])
            self.assertEqual(jobs.asset_reference(self.fixture.user, saved["job_id"]), final.id)
        job, financial = self.rows(task["job_id"])
        self.assertEqual((financial["complete_applied"], financial["refund_applied"]), (1, 0))
        self.assertEqual(self.fixture.balances(), ((64, 0), 8))
        self.assertEqual(db.fetchone("SELECT count(*) n FROM usage_records WHERE operation='cover_generate'")["n"], 1)
        self.assertEqual(db.fetchone("SELECT count(*) n FROM cover_asset_revisions")["n"], 1)
        self.assertIsNone(jobs.claim_job(task["job_id"], now=start + timedelta(seconds=1)))


if __name__ == "__main__":
    unittest.main()
