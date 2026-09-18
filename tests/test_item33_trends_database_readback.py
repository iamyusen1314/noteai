"""Real PG16, synthetic business fixtures; no DSN discovery or provider calls."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import unittest

from tests import test_item33_trends_preflight as preflight_tests
from tools.item33_trends_database_readback import Item33ReadbackError, read_cycle_facts
from tools import execute_item32_readonly_trends_successor as accepted


@unittest.skipUnless(os.environ.get("NOTEAI_LOCAL_PG16_ITEM33_PREFLIGHT_TEST") == "1",
                     "explicit disposable network-none PG16 socket required")
class Item33DatabaseReadbackTests(unittest.TestCase):
    def setUp(self):
        preflight_tests.Item33PreflightPostgresTests.setUp(self)
        self.now = datetime.now(timezone.utc)
        self.started = self.now - timedelta(seconds=30)
        self.finished = self.now - timedelta(seconds=5)
        self.bucket = self.started.date().isoformat()
        self.run_id = "synthetic-private-run-identity"
        captured = (self.started + timedelta(seconds=20)).isoformat()
        self.payload = {"schema_version": 1, "generated_at": captured, "freshness_max_hours": 48,
            "domains": {domain: {"captured_at": captured, "keywords": [
                {"keyword": domain + "合成测试词" + str(index), "search_vol": 70, "trend_dir": 0,
                 "source": "search_phrase" if index == 0 else "search_recommend", "category": domain,
                 "sample_count": 3, "quality_score": 70, "evidence_level": "medium",
                 "quality_reason": "synthetic-test", "captured_at": captured}
                for index in range(12)]} for domain in sorted(accepted.DOMAINS)}}
        self.raw = json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.owner.execute("""INSERT INTO xhs_trends_runs
            (id,bucket_key,status,lease_token_hash,lease_fence,lease_expires_at,started_at,completed_at,
             provider_attempt_count,snapshot_sha256,snapshot_size)
            VALUES (%s,%s,'succeeded',%s,1,%s,%s,%s,34,%s,%s)""",
            (self.run_id, self.bucket, "a" * 64, self.started + timedelta(minutes=30), self.started,
             self.finished, hashlib.sha256(self.raw).hexdigest(), len(self.raw)))
        for ordinal, endpoint in enumerate(accepted.ENDPOINT_SEQUENCE, 1):
            self.owner.execute("""INSERT INTO xhs_trends_provider_attempts
                (id,run_id,ordinal,endpoint,status,admitted_at,admitted_date,completed_at)
                VALUES (%s,%s,%s,%s,'succeeded',%s,%s,%s)""", ("private-attempt-" + str(ordinal),
                self.run_id, ordinal, endpoint, self.started + timedelta(seconds=1), self.bucket,
                self.finished - timedelta(seconds=1)))
        self.owner.execute("""INSERT INTO xhs_trends_snapshot_evidence
            (run_id,schema_version,snapshot_sha256,snapshot_size,keyword_count,domain_counts_json,payload_json,created_at)
            VALUES (%s,1,%s,%s,72,%s,%s,%s)""", (self.run_id, hashlib.sha256(self.raw).hexdigest(),
                len(self.raw), json.dumps({domain: 12 for domain in accepted.DOMAINS}), self.raw.decode(),
                self.finished - timedelta(seconds=1)))

    def collect(self, **kwargs):
        return read_cycle_facts(self.writer, bucket_key=self.bucket, now=self.now, **kwargs)

    def test_reads_real_rows_and_hashes_without_fabricating_missing_proof(self):
        result = self.collect()
        self.assertEqual(result["run_identity_sha256"], hashlib.sha256(self.run_id.encode()).hexdigest())
        self.assertEqual(result["provider_request_count"], 34)
        self.assertEqual(result["endpoint_counts"], {"homefeed": 10, "search_recommend": 12, "search_notes": 12})
        self.assertEqual(result["quality"]["keyword_count"], 72)
        self.assertEqual(result["snapshot"]["payload"], self.payload)
        self.assertEqual(result["ledger"]["same_bucket_run_count"], 1)
        self.assertEqual(result["health_rows"], [])
        self.assertFalse(result["physical_http_verified"])
        self.assertFalse(result["production_write_set_verified"])
        self.assertIsNone(result["automatic_retry_count"])
        self.assertTrue(result["transaction_rolled_back"])
        self.assertEqual(self.writer.info.transaction_status, 0)
        self.assertNotIn(self.run_id, json.dumps(result))
        self.assertNotIn("private-attempt-", json.dumps(result))

    def test_expected_actual_run_binding_rejects_another_run(self):
        with self.assertRaisesRegex(Item33ReadbackError, "run_identity"):
            self.collect(expected_run_identity_sha256="f" * 64)
        self.assertEqual(self.writer.info.transaction_status, 0)

    def test_hash_mismatch_is_not_quality_success(self):
        self.owner.execute("UPDATE xhs_trends_runs SET snapshot_sha256=%s WHERE id=%s", ("b" * 64, self.run_id))
        with self.assertRaisesRegex(Item33ReadbackError, "snapshot_binding"):
            self.collect()

    def test_failed_attempt_is_not_hidden_by_successful_run(self):
        self.owner.execute("UPDATE xhs_trends_provider_attempts SET status='failed',error_code='synthetic' WHERE ordinal=1")
        with self.assertRaisesRegex(Item33ReadbackError, "attempt_contract"):
            self.collect()

    def test_matching_snapshot_hash_does_not_replace_source_quality(self):
        domain = sorted(accepted.DOMAINS)[0]
        self.payload["domains"][domain]["keywords"][0]["source"] = "search_recommend"
        changed = json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        changed_hash = hashlib.sha256(changed).hexdigest()
        self.owner.execute("UPDATE xhs_trends_snapshot_evidence SET payload_json=%s,snapshot_sha256=%s,snapshot_size=%s",
                           (changed.decode(), changed_hash, len(changed)))
        self.owner.execute("UPDATE xhs_trends_runs SET snapshot_sha256=%s,snapshot_size=%s WHERE id=%s",
                           (changed_hash, len(changed), self.run_id))
        with self.assertRaisesRegex(Item33ReadbackError, "snapshot_quality"):
            self.collect()

    def test_wrong_session_rejected_and_rolled_back(self):
        with self.assertRaisesRegex(Item33ReadbackError, "role_or_readonly"):
            read_cycle_facts(self.owner, bucket_key=self.bucket, now=self.now)
        self.assertEqual(self.owner.info.transaction_status, 0)

    def test_existing_transaction_not_taken_over(self):
        self.writer.execute("BEGIN READ ONLY")
        with self.assertRaisesRegex(Item33ReadbackError, "connection_not_idle_autocommit"):
            self.collect()
        self.assertNotEqual(self.writer.info.transaction_status, 0)
        self.writer.rollback()

    def test_unknown_bucket_does_not_fall_back_to_latest(self):
        with self.assertRaisesRegex(Item33ReadbackError, "cycle_count"):
            read_cycle_facts(self.writer, bucket_key="2000-01-01", now=self.now)

    def test_non_utc_connection_preserves_utc_bucket_and_restores_timezone(self):
        self.writer.execute("SET TIME ZONE 'Pacific/Kiritimati'")
        result = self.collect()
        self.assertEqual(result["bucket_key"], self.bucket)
        self.assertTrue(result["started_at"].endswith("+00:00"))
        self.assertEqual(self.writer.execute("SHOW TIME ZONE").fetchone()[0], "Pacific/Kiritimati")


if __name__ == "__main__":
    unittest.main()
