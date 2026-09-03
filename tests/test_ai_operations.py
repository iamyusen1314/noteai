import importlib
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
ai_operations = importlib.import_module("ai_operations")
task_queue = importlib.import_module("task_queue")


class DurableAiOperationTests(unittest.TestCase):
    OPERATION_NAMESPACE = uuid.UUID("b3f812b8-a477-4b63-90ef-320dadc51aef")

    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        self.queue = task_queue.DatabaseTaskQueue()
        self.t0 = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)

    def tearDown(self):
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        self.temp.cleanup()

    @staticmethod
    def digest(label: str) -> str:
        return ai_operations.sha256_digest(label)

    @classmethod
    def operation_id(cls, label: str) -> str:
        return str(uuid.uuid5(cls.OPERATION_NAMESPACE, label))

    def create(self, label: str = "one", *, priority: int = 0, available_at=None) -> str:
        return self.queue.create_operation(
            operation_id=self.operation_id(label),
            subject_hash=self.digest(f"subject-{label}"),
            request_hash=self.digest(f"request-{label}"),
            operation_kind=ai_operations.OperationKind.ANALYZE,
            priority=priority,
            available_at=available_at,
            now=self.t0,
        )

    def test_sqlite_schema_is_idempotent_and_contains_only_safe_metadata(self):
        db.init_db()
        conn = db.get_conn()
        try:
            operation_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(ai_operations)")
            }
            event_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(ai_operation_events)")
            }
            attempt_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(ai_provider_attempts)")
            }
            indexes = {
                row["name"] for row in conn.execute("PRAGMA index_list(ai_operations)")
            }
            sqlite_definitions = {
                name: conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (name,),
                ).fetchone()["sql"]
                for name in (
                    "ai_operations", "ai_operation_events", "ai_provider_attempts"
                )
            }
            id_not_null = {
                name: next(
                    row["notnull"]
                    for row in conn.execute(f"PRAGMA table_info({name})")
                    if row["name"] == "id"
                )
                for name in (
                    "ai_operations", "ai_operation_events", "ai_provider_attempts"
                )
            }
        finally:
            conn.close()

        self.assertTrue({
            "subject_hash", "request_hash", "status", "provider_phase",
            "lease_owner_hash", "lease_fence", "lease_expires_at", "heartbeat_at",
            "provider_attempt_count", "event_sequence", "result_hash", "result_count",
        }.issubset(operation_columns))
        self.assertTrue({
            "event_type", "operation_status", "fence", "provider", "detail_hash",
            "item_count", "recorded_at",
        }.issubset(event_columns))
        self.assertTrue({
            "attempt_number", "fence", "provider", "state", "request_hash",
            "model_hash", "response_hash", "input_count", "output_count",
        }.issubset(attempt_columns))
        forbidden = {
            "prompt", "body", "image", "url", "cookie", "secret",
            "exception", "error_text", "raw_owner", "owner_token",
        }
        self.assertFalse(forbidden & (operation_columns | event_columns | attempt_columns))
        self.assertIn("idx_ai_operations_claim", indexes)
        self.assertEqual(id_not_null, {
            "ai_operations": 1,
            "ai_operation_events": 1,
            "ai_provider_attempts": 1,
        })

        migration = (
            ROOT / "model" / "migrations" / "postgres" / "0007_ai_operations.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS ai_operations", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS ai_operation_events", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS ai_provider_attempts", migration)
        postgres_definitions = {
            "ai_operations": migration.split(
                "CREATE TABLE IF NOT EXISTS ai_operations", 1
            )[1].split("CREATE INDEX IF NOT EXISTS idx_ai_operations_claim", 1)[0],
            "ai_operation_events": migration.split(
                "CREATE TABLE IF NOT EXISTS ai_operation_events", 1
            )[1].split("CREATE INDEX IF NOT EXISTS idx_ai_operation_events_replay", 1)[0],
            "ai_provider_attempts": migration.split(
                "CREATE TABLE IF NOT EXISTS ai_provider_attempts", 1
            )[1].split("CREATE INDEX IF NOT EXISTS idx_ai_provider_attempts_operation", 1)[0],
        }
        expected_literals = {
            "ai_operations": {
                "subject_hash", "request_hash", "lease_owner_hash", "lease_fence",
                "analyze", "generate", "chat_rewrite", "queued", "running",
                "succeeded", "failed", "outcome_unknown", "cancelled",
                "not_started", "provider_started", "provider_terminal",
            },
            "ai_operation_events": {
                "event_type", "operation_status", "detail_hash", "item_count",
                "enqueued", "claimed", "lease_taken_over", "progress",
                "provider_started", "provider_terminal", "succeeded", "failed",
                "outcome_unknown", "cancelled", "claude", "kimi",
            },
            "ai_provider_attempts": {
                "attempt_number", "request_hash", "model_hash", "response_hash",
                "input_count", "output_count", "provider_started",
                "provider_succeeded", "provider_failed", "outcome_unknown",
                "claude", "kimi",
            },
        }
        for table, literals in expected_literals.items():
            for literal in literals:
                self.assertIn(literal, sqlite_definitions[table], (table, literal, "sqlite"))
                self.assertIn(literal, postgres_definitions[table], (table, literal, "postgres"))
        source = inspect.getsource(ai_operations)
        self.assertIn("FOR UPDATE SKIP LOCKED", source)

    def test_fixed_enums_and_digest_validation_fail_closed(self):
        with self.assertRaises(ValueError):
            self.queue.create_operation(
                operation_id=self.operation_id("invalid-enum"),
                subject_hash=self.digest("subject"),
                request_hash=self.digest("request"),
                operation_kind="arbitrary",
                now=self.t0,
            )
        with self.assertRaises(ValueError):
            self.queue.create_operation(
                operation_id=self.operation_id("raw-data"),
                subject_hash=self.digest("subject"),
                request_hash="raw-request-content",
                operation_kind="analyze",
                now=self.t0,
            )
        with self.assertRaises(ValueError):
            self.queue.create_operation(
                operation_id="secret-token-shaped-operation-id-1234567890",
                subject_hash=self.digest("subject"),
                request_hash=self.digest("request"),
                operation_kind="analyze",
                now=self.t0,
            )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"], 0
        )
        conn = db.get_conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO ai_operations("
                    "id,subject_hash,request_hash,operation_kind,status,provider_phase,"
                    "priority,available_at,created_at,updated_at) "
                    "VALUES(?,?,?,?,'queued','not_started',0,?,?,?)",
                    (
                        "-2345678-1234-1234-1234-123456789abc",
                        self.digest("bypass-subject"),
                        self.digest("bypass-request"),
                        "analyze",
                        self.t0.isoformat(),
                        self.t0.isoformat(),
                        self.t0.isoformat(),
                    ),
                )
        finally:
            conn.close()
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"], 0
        )
        conn = db.get_conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO ai_operations("
                    "id,subject_hash,request_hash,operation_kind,status,provider_phase,"
                    "priority,available_at,created_at,updated_at) "
                    "VALUES(?,?,?,?,'queued','not_started',0,?,?,?)",
                    (
                        None,
                        self.digest("null-id-subject"),
                        self.digest("null-id-request"),
                        "analyze",
                        self.t0.isoformat(),
                        self.t0.isoformat(),
                        self.t0.isoformat(),
                    ),
                )
        finally:
            conn.close()
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"], 0
        )

        op_id = self.create("fixed")
        lease = self.queue.claim_next(
            owner_token="fixed-enum-owner-0001", lease_seconds=30, now=self.t0
        )
        self.assertEqual(lease.operation_id, op_id)
        with self.assertRaises(ValueError):
            self.queue.record_provider_started(
                lease,
                provider="unlisted-provider",
                request_hash=self.digest("provider-request"),
                model_hash=self.digest("model"),
                now=self.t0 + timedelta(seconds=1),
            )
        with self.assertRaises(ValueError):
            self.queue.record_progress(
                lease,
                detail_hash="not-a-digest",
                now=self.t0 + timedelta(seconds=1),
            )

        conn = db.get_conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO ai_operation_events("
                    "id,operation_id,sequence,event_type,operation_status,fence,item_count,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        "bad-event", op_id, 99, "free_text", "running", 1, 0,
                        self.t0.isoformat(),
                    ),
                )
        finally:
            conn.close()

    def test_twenty_concurrent_claims_have_one_winner(self):
        op_id = self.create("concurrent")

        def claim(index):
            return self.queue.claim_next(
                owner_token=f"concurrent-owner-{index:04d}",
                lease_seconds=30,
                now=self.t0,
            )

        with ThreadPoolExecutor(max_workers=20) as pool:
            leases = list(pool.map(claim, range(20)))

        winners = [lease for lease in leases if lease is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].operation_id, op_id)
        operation = self.queue.get(op_id)
        self.assertEqual(operation["status"], "running")
        self.assertEqual(operation["claim_count"], 1)
        self.assertEqual(operation["lease_fence"], 1)
        self.assertNotIn("lease_owner_hash", operation)
        self.assertEqual(
            [event["event_type"] for event in self.queue.events(op_id)],
            ["enqueued", "claimed"],
        )

    def test_one_hundred_distinct_operations_are_persisted_in_one_burst(self):
        def create(index):
            label = f"burst-{index:03d}"
            return self.queue.create_operation(
                operation_id=self.operation_id(label),
                subject_hash=self.digest(f"subject-{label}"),
                request_hash=self.digest(f"request-{label}"),
                operation_kind="generate" if index % 2 else "analyze",
                priority=index % 3,
                now=self.t0,
            )

        with ThreadPoolExecutor(max_workers=20) as pool:
            operation_ids = list(pool.map(create, range(100)))

        self.assertEqual(len(operation_ids), 100)
        self.assertEqual(len(set(operation_ids)), 100)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"], 100
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operation_events")["c"], 100
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM ai_operation_events "
                "WHERE event_type='enqueued' AND sequence=1"
            )["c"],
            100,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_provider_attempts")["c"], 0
        )

    def test_stale_provider_started_is_reaped_before_claim_under_queued_backlog(self):
        stale_id = self.create("starvation-stale")
        stale_lease = self.queue.claim_next(
            owner_token="starvation-stale-owner-01", lease_seconds=10, now=self.t0
        )
        stale_attempt = self.queue.record_provider_started(
            stale_lease,
            provider="claude",
            request_hash=self.digest("starvation-request"),
            model_hash=self.digest("starvation-model"),
            now=self.t0 + timedelta(seconds=1),
        )
        queued_ids = [self.create(f"starvation-queued-{index}") for index in range(5)]

        safe_lease = self.queue.claim_next(
            owner_token="starvation-safe-owner-0002",
            lease_seconds=30,
            now=self.t0 + timedelta(seconds=10),
        )

        self.assertIsNotNone(safe_lease)
        self.assertIn(safe_lease.operation_id, queued_ids)
        self.assertEqual(self.queue.get(stale_id)["status"], "outcome_unknown")
        self.assertEqual(
            self.queue.provider_attempts(stale_id)[0]["state"], "outcome_unknown"
        )
        self.assertEqual(self.queue.get(stale_id)["lease_fence"], stale_lease.fence)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operations WHERE status='running'")["c"],
            1,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operations WHERE status='queued'")["c"],
            4,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_provider_attempts")["c"], 1
        )
        self.assertFalse(
            self.queue.record_provider_terminal(
                stale_lease,
                stale_attempt,
                state="provider_succeeded",
                response_hash=self.digest("late-starvation-response"),
                now=self.t0 + timedelta(seconds=11),
            )
        )

    def test_explicit_reaper_is_bounded_and_validates_limit(self):
        stale_ids = []
        for index in range(2):
            stale_id = self.create(f"bounded-stale-{index}")
            stale_ids.append(stale_id)
            lease = self.queue.claim_next(
                owner_token=f"bounded-stale-owner-{index:04d}",
                lease_seconds=10,
                now=self.t0,
            )
            self.queue.record_provider_started(
                lease,
                provider="kimi",
                request_hash=self.digest(f"bounded-request-{index}"),
                model_hash=self.digest(f"bounded-model-{index}"),
                now=self.t0 + timedelta(seconds=1),
            )

        with self.assertRaises(ValueError):
            self.queue.reap_stale_provider_outcomes(limit=0, now=self.t0)
        with self.assertRaises(ValueError):
            self.queue.reap_stale_provider_outcomes(limit=101, now=self.t0)
        self.assertEqual(
            self.queue.reap_stale_provider_outcomes(
                limit=1, now=self.t0 + timedelta(seconds=10)
            ),
            1,
        )
        statuses = [self.queue.get(operation_id)["status"] for operation_id in stale_ids]
        self.assertEqual(statuses.count("outcome_unknown"), 1)
        self.assertEqual(statuses.count("running"), 1)
        self.assertEqual(
            self.queue.reap_stale_provider_outcomes(
                limit=100, now=self.t0 + timedelta(seconds=10)
            ),
            1,
        )
        self.assertTrue(all(
            self.queue.get(operation_id)["status"] == "outcome_unknown"
            for operation_id in stale_ids
        ))

    def test_expired_unstarted_lease_takeover_fences_old_owner(self):
        op_id = self.create("takeover")
        first = self.queue.claim_next(
            owner_token="first-owner-token-0001", lease_seconds=10, now=self.t0
        )
        replacement = self.queue.claim_next(
            owner_token="second-owner-token-0002",
            lease_seconds=20,
            now=self.t0 + timedelta(seconds=10),
        )

        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.operation_id, op_id)
        self.assertEqual(first.fence, 1)
        self.assertEqual(replacement.fence, 2)
        after = self.t0 + timedelta(seconds=11)
        self.assertIsNone(self.queue.heartbeat(first, lease_seconds=20, now=after))
        self.assertFalse(
            self.queue.record_progress(
                first, detail_hash=self.digest("old-progress"), now=after
            )
        )
        self.assertFalse(
            self.queue.mark_terminal(first, status="failed", now=after)
        )

        renewed = self.queue.heartbeat(replacement, lease_seconds=20, now=after)
        self.assertIsNotNone(renewed)
        self.assertTrue(
            self.queue.record_progress(
                renewed,
                detail_hash=self.digest("new-progress"),
                item_count=3,
                now=after,
            )
        )
        self.assertTrue(
            self.queue.mark_terminal(
                renewed, status=ai_operations.OperationStatus.FAILED, now=after
            )
        )
        self.assertEqual(self.queue.get(op_id)["status"], "failed")
        self.assertEqual(
            [event["event_type"] for event in self.queue.events(op_id)],
            ["enqueued", "claimed", "lease_taken_over", "progress", "failed"],
        )

    def test_expired_provider_started_is_quarantined_and_never_reclaimed(self):
        op_id = self.create("provider-unknown")
        lease = self.queue.claim_next(
            owner_token="provider-owner-token-01", lease_seconds=10, now=self.t0
        )
        attempt = self.queue.record_provider_started(
            lease,
            provider=ai_operations.Provider.CLAUDE,
            request_hash=self.digest("provider-request"),
            model_hash=self.digest("claude-model"),
            input_count=12,
            now=self.t0 + timedelta(seconds=1),
        )
        self.assertIsNotNone(attempt)

        replacement = self.queue.claim_next(
            owner_token="replacement-owner-token-02",
            lease_seconds=10,
            now=self.t0 + timedelta(seconds=10),
        )
        self.assertIsNone(replacement)
        operation = self.queue.get(op_id)
        self.assertEqual(operation["status"], "outcome_unknown")
        self.assertEqual(operation["lease_fence"], 1)
        attempts = self.queue.provider_attempts(op_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["state"], "outcome_unknown")
        self.assertFalse(
            self.queue.record_provider_terminal(
                lease,
                attempt,
                state="provider_succeeded",
                response_hash=self.digest("late-response"),
                now=self.t0 + timedelta(seconds=11),
            )
        )
        self.assertFalse(
            self.queue.mark_terminal(
                lease,
                status="succeeded",
                result_hash=self.digest("late-result"),
                now=self.t0 + timedelta(seconds=11),
            )
        )
        self.assertIsNone(
            self.queue.claim_next(
                owner_token="third-owner-token-00003",
                lease_seconds=10,
                now=self.t0 + timedelta(seconds=12),
            )
        )
        self.assertEqual(self.queue.events(op_id)[-1]["event_type"], "outcome_unknown")

    def test_provider_success_and_operation_terminal_are_fenced_and_replayable(self):
        op_id = self.create("success")
        lease = self.queue.claim_next(
            owner_token="success-owner-token-001", lease_seconds=30, now=self.t0
        )
        attempt = self.queue.record_provider_started(
            lease,
            provider="kimi",
            request_hash=self.digest("kimi-request"),
            model_hash=self.digest("kimi-model"),
            input_count=7,
            now=self.t0 + timedelta(seconds=1),
        )
        self.assertFalse(
            self.queue.mark_terminal(
                lease,
                status="succeeded",
                result_hash=self.digest("too-early"),
                now=self.t0 + timedelta(seconds=2),
            )
        )
        self.assertTrue(
            self.queue.record_provider_terminal(
                lease,
                attempt,
                state=ai_operations.AttemptState.SUCCEEDED,
                response_hash=self.digest("kimi-response"),
                output_count=9,
                now=self.t0 + timedelta(seconds=2),
            )
        )
        self.assertTrue(
            self.queue.mark_terminal(
                lease,
                status="succeeded",
                result_hash=self.digest("durable-result"),
                result_count=2,
                now=self.t0 + timedelta(seconds=3),
            )
        )
        self.assertFalse(
            self.queue.record_progress(
                lease,
                detail_hash=self.digest("after-terminal"),
                now=self.t0 + timedelta(seconds=4),
            )
        )

        operation = self.queue.get(op_id)
        self.assertEqual(operation["status"], "succeeded")
        self.assertEqual(operation["result_hash"], self.digest("durable-result"))
        events = self.queue.events(op_id)
        self.assertEqual(
            [event["sequence"] for event in events], list(range(1, len(events) + 1))
        )
        self.assertEqual(
            [event["event_type"] for event in events],
            ["enqueued", "claimed", "provider_started", "provider_terminal", "succeeded"],
        )
        replay = self.queue.events(op_id, after_sequence=3)
        self.assertEqual(
            [event["event_type"] for event in replay],
            ["provider_terminal", "succeeded"],
        )
        attempts = self.queue.provider_attempts(op_id)
        self.assertEqual(attempts[0]["state"], "provider_succeeded")
        self.assertEqual(attempts[0]["input_count"], 7)
        self.assertEqual(attempts[0]["output_count"], 9)

    def test_delayed_operation_is_not_claimed_early_and_queue_contract_is_abstract(self):
        with self.assertRaises(TypeError):
            task_queue.TaskQueue()
        op_id = self.create(
            "delayed", available_at=self.t0 + timedelta(seconds=30)
        )
        self.assertIsNone(
            self.queue.claim_next(
                owner_token="delayed-owner-token-001",
                lease_seconds=10,
                now=self.t0 + timedelta(seconds=29),
            )
        )
        lease = self.queue.claim_next(
            owner_token="delayed-owner-token-002",
            lease_seconds=10,
            now=self.t0 + timedelta(seconds=30),
        )
        self.assertEqual(lease.operation_id, op_id)


if __name__ == "__main__":
    unittest.main()
