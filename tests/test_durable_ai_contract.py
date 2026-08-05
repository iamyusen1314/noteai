import importlib
import inspect
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
ai_operations = importlib.import_module("ai_operations")
durable_ai = importlib.import_module("durable_ai")
durable_ai_worker = importlib.import_module("durable_ai_worker")
content_retention = importlib.import_module("content_retention")


class DurableAiExecutionContractTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.old_suspended = os.environ.get("NOTEAI_DURABLE_AI_SUSPENDED")
        self.old_runtime_role = os.environ.get("NOTEAI_RUNTIME_ROLE")
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        self.store = durable_ai.InMemoryPayloadStore()
        durable_ai.configure_payload_store(self.store)
        billing.clear_active_usage()
        os.environ["NOTEAI_DURABLE_AI_SUSPENDED"] = "0"
        os.environ["NOTEAI_RUNTIME_ROLE"] = "ai-worker"
        # Keep admissions safely before real-time worker calls. Pinning only the
        # microseconds made these tests race whenever wall-clock microseconds
        # were below 123456 in the same second.
        self.now = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).replace(microsecond=123456)

    def tearDown(self):
        billing.clear_active_usage()
        durable_ai.reset_payload_store()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        else:
            os.environ.pop("DATABASE_URL", None)
        if self.old_suspended is None:
            os.environ.pop("NOTEAI_DURABLE_AI_SUSPENDED", None)
        else:
            os.environ["NOTEAI_DURABLE_AI_SUSPENDED"] = self.old_suspended
        if self.old_runtime_role is None:
            os.environ.pop("NOTEAI_RUNTIME_ROLE", None)
        else:
            os.environ["NOTEAI_RUNTIME_ROLE"] = self.old_runtime_role
        self.temp.cleanup()

    def create_user(self, user_id: str, *, wallet: float = 1000) -> None:
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                user_id,
                f"{user_id}_name",
                f"{user_id}@example.com",
                "hash",
                "salt",
                self.now.isoformat(),
            ),
        )
        billing.get_subscription(user_id)
        db.execute(
            "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance",
            (user_id, wallet, wallet, 0, self.now.isoformat()),
        )

    def admit(
        self,
        user_id: str = "u-durable",
        *,
        key: str = "request-1",
        operation: str = "analyze",
        payload=None,
    ):
        return durable_ai.admit_job(
            user_id=user_id,
            operation=operation,
            request_id=key,
            payload=payload or {"domain": "美食", "content": "private request"},
            now=self.now,
            store=self.store,
        )

    def count(self, table: str) -> int:
        return int(db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")["c"])

    def deliver(self, operation_id: str) -> None:
        lease = durable_ai.claim_outbox(
            owner_token=f"test-dispatch-{operation_id}",
            now=self.now + timedelta(milliseconds=250),
        )
        self.assertIsNotNone(lease)
        self.assertEqual(lease.operation_id, operation_id)
        self.assertTrue(
            durable_ai.mark_outbox_delivered(
                lease,
                now=self.now + timedelta(milliseconds=500),
            )
        )

    def test_worker_initializes_private_storage_before_runtime_command(self):
        with (
            mock.patch.object(
                durable_ai_worker.private_storage,
                "configure_from_environment",
                return_value=True,
            ) as configure,
            mock.patch.object(
                durable_ai_worker,
                "healthcheck",
                return_value={"ok": True},
            ),
        ):
            self.assertEqual(
                durable_ai_worker.main(["--healthcheck"]),
                0,
            )

        configure.assert_called_once_with()

    def test_schema_and_migration_store_only_opaque_bounded_metadata(self):
        conn = db.get_conn()
        try:
            tables = {
                table: {
                    row["name"]
                    for row in conn.execute(f"PRAGMA table_info({table})")
                }
                for table in (
                    "ai_payload_refs",
                    "ai_operation_outbox",
                    "ai_operation_settlements",
                    "ai_dispatch_state",
                )
            }
            definitions = {
                table: conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()["sql"]
                for table in tables
            }
        finally:
            conn.close()
        self.assertIn("object_key_hash", tables["ai_payload_refs"])
        self.assertIn("content_sha256", tables["ai_payload_refs"])
        self.assertIn("key_epoch_hash", tables["ai_payload_refs"])
        self.assertIn("billing_state", tables["ai_operation_settlements"])
        self.assertEqual(
            tables["ai_dispatch_state"],
            {"service_key", "priority_streak", "updated_at"},
        )
        forbidden = {
            "payload",
            "body",
            "prompt",
            "response",
            "reasoning",
            "url",
            "object_key",
            "user_id",
            "owner_token",
            "secret",
            "cookie",
            "exception",
        }
        for table, columns in tables.items():
            self.assertFalse(forbidden & columns, table)
        serialized = json.dumps(definitions)
        self.assertNotIn("raw_", serialized)

        migration = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0012_durable_ai_execution_contract.sql"
        ).read_text(encoding="utf-8")
        for table in tables:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", migration)
        self.assertNotIn("GRANT ", migration.upper())
        self.assertNotIn("REVOKE ", migration.upper())
        self.assertIn("size_bytes BETWEEN 1 AND 134217728", migration)
        self.assertIn("priority_streak BETWEEN 0 AND 3", migration)
        self.assertIn("created_at::timestamptz <= ready_at::timestamptz", migration)

    def test_missing_store_fails_before_charge_or_database_admission(self):
        self.create_user("u-no-store")
        durable_ai.reset_payload_store()
        with self.assertRaises(durable_ai.PayloadUnavailable):
            durable_ai.admit_job(
                user_id="u-no-store",
                operation="analyze",
                request_id="no-store-key",
                payload={"content": "private"},
                now=self.now,
            )
        for table in (
            "idempotency_requests",
            "ai_operations",
            "ai_operation_admissions",
            "ai_payload_refs",
            "ai_operation_outbox",
            "ai_operation_settlements",
            "usage_records",
        ):
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(len(self.store._objects), 0)

    def test_admission_is_atomic_content_free_and_idempotent(self):
        self.create_user("u-admit")
        private = "private prompt https://secret.invalid?token=never-store"
        first = self.admit(
            "u-admit",
            key="stable-key",
            payload={"content": private, "constraints": ["不改标题"]},
        )
        duplicate = self.admit(
            "u-admit",
            key="stable-key",
            payload={"content": private, "constraints": ["不改标题"]},
        )
        conflict = self.admit(
            "u-admit",
            key="stable-key",
            payload={"content": "different"},
        )
        self.assertEqual(first["state"], "admitted")
        self.assertEqual(duplicate["state"], "existing")
        self.assertEqual(duplicate["operation_id"], first["operation_id"])
        self.assertEqual(conflict, {"state": "conflict"})
        expected = {
            "idempotency_requests": 1,
            "ai_operations": 1,
            "ai_operation_events": 1,
            "ai_operation_admissions": 1,
            "ai_payload_refs": 1,
            "ai_operation_outbox": 1,
            "ai_operation_settlements": 1,
            "usage_records": 1,
            "ai_provider_attempts": 0,
        }
        for table, count in expected.items():
            self.assertEqual(self.count(table), count, table)
        rows = {}
        for table in expected:
            rows[table] = [
                dict(row) for row in db.fetchall(f"SELECT * FROM {table}")
            ]
        serialized = json.dumps(rows, ensure_ascii=False)
        for forbidden in (
            private,
            "secret.invalid",
            "stable-key",
            "owner_token",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            db.fetchone("SELECT state FROM ai_operation_outbox")["state"],
            "pending",
        )
        self.assertEqual(
            db.fetchone("SELECT billing_state FROM ai_operation_settlements")[
                "billing_state"
            ],
            "charged",
        )

    def test_billing_failure_rolls_back_all_database_contract_rows(self):
        self.create_user("u-billing-fail", wallet=0)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?",
            ("u-billing-fail",),
        )
        with self.assertRaises(Exception):
            self.admit("u-billing-fail", key="quota-fail")
        for table in (
            "idempotency_requests",
            "ai_operations",
            "ai_operation_events",
            "ai_operation_admissions",
            "ai_payload_refs",
            "ai_operation_outbox",
            "ai_operation_settlements",
            "usage_records",
        ):
            self.assertEqual(self.count(table), 0, table)

    def test_raw_media_and_oversize_payloads_fail_before_writes(self):
        self.create_user("u-media")
        for payload in (
            {"cover_image": "data:image/png;base64,AAAA"},
            {"extra_images": ["AAAA"]},
            {"video_file_id": "node-local-file-id"},
            {"media_refs": ["not-a-canonical-ref"]},
        ):
            with self.subTest(payload=tuple(payload)):
                with self.assertRaises(durable_ai.DurableAiError):
                    self.admit("u-media", key=f"bad-{len(str(payload))}", payload=payload)
        with self.assertRaises(durable_ai.DurableAiError):
            self.admit(
                "u-media",
                key="too-large",
                payload={"content": "x" * (durable_ai.MAX_INLINE_REQUEST_BYTES + 1)},
            )
        self.assertEqual(self.count("ai_operations"), 0)
        self.assertEqual(self.count("usage_records"), 0)

    def test_owner_status_events_and_result_hide_cross_account_existence(self):
        self.create_user("u-owner")
        self.create_user("u-other")
        admitted = self.admit("u-owner")
        owned = durable_ai.status_for_user("u-owner", admitted["operation_id"])
        self.assertEqual(owned["status"], "queued")
        self.assertEqual(owned["billing_state"], "charged")
        forbidden = {
            "subject_hash",
            "request_hash",
            "user_id",
            "request_ref_id",
            "object_key_hash",
            "content_sha256",
            "usage_id",
        }
        self.assertFalse(forbidden & set(owned))
        events = durable_ai.events_for_user("u-owner", admitted["operation_id"])
        self.assertEqual([event["event_type"] for event in events], ["enqueued"])
        self.assertNotIn("detail_hash", events[0])
        self.assertIsNone(
            durable_ai.status_for_user("u-other", admitted["operation_id"])
        )
        self.assertIsNone(
            durable_ai.events_for_user("u-other", admitted["operation_id"])
        )
        with self.assertRaises(durable_ai.DurableAiError) as hidden:
            durable_ai.result_for_user(
                "u-other", admitted["operation_id"], store=self.store
            )
        self.assertEqual(hidden.exception.http_status, 404)

    def test_outbox_publishes_only_uuid_and_is_fenced(self):
        self.create_user("u-outbox")
        admitted = self.admit("u-outbox")
        published = []
        dispatcher = durable_ai_worker.OutboxDispatcher(published.append)
        result = dispatcher.run_once(
            owner_token="dispatcher-owner-token-0001",
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(result["status"], "delivered")
        self.assertEqual(published, [admitted["operation_id"]])
        uuid_value = published[0]
        self.assertEqual(str(__import__("uuid").UUID(uuid_value)), uuid_value)
        row = dict(db.fetchone("SELECT * FROM ai_operation_outbox"))
        self.assertEqual(row["state"], "delivered")
        self.assertIsNone(row["lease_owner_hash"])
        self.assertIsNone(durable_ai.claim_outbox(now=self.now + timedelta(seconds=2)))

    def test_outbox_publisher_failure_is_not_acknowledged(self):
        self.create_user("u-publish-fail")
        self.admit("u-publish-fail")

        def fail(_operation_id):
            raise RuntimeError("synthetic broker unavailable")

        with self.assertRaisesRegex(RuntimeError, "broker unavailable"):
            durable_ai_worker.OutboxDispatcher(fail).run_once(
                owner_token="dispatcher-owner-token-0002",
                now=self.now + timedelta(seconds=1),
            )
        row = dict(db.fetchone("SELECT * FROM ai_operation_outbox"))
        self.assertEqual(row["state"], "pending")
        self.assertEqual(row["attempt_count"], 1)
        self.assertIsNotNone(row["lease_expires_at"])

    def test_exact_outbox_claim_never_mutates_an_unrelated_queue_row(self):
        self.create_user("u-exact-dispatch-first")
        self.create_user("u-exact-dispatch-target")
        first = self.admit("u-exact-dispatch-first")
        target = self.admit("u-exact-dispatch-target")
        before_streak = db.fetchone(
            "SELECT priority_streak FROM ai_dispatch_state "
            "WHERE service_key='durable_ai'"
        )["priority_streak"]

        lease = durable_ai.claim_outbox(
            operation_id=target["operation_id"],
            owner_token="exact-dispatch-owner-token",
            now=self.now + timedelta(seconds=1),
        )

        self.assertEqual(lease.operation_id, target["operation_id"])
        rows = {
            row["operation_id"]: dict(row)
            for row in db.fetchall(
                "SELECT operation_id,attempt_count,lease_owner_hash "
                "FROM ai_operation_outbox"
            )
        }
        self.assertEqual(rows[first["operation_id"]]["attempt_count"], 0)
        self.assertIsNone(rows[first["operation_id"]]["lease_owner_hash"])
        self.assertEqual(rows[target["operation_id"]]["attempt_count"], 1)
        self.assertIsNotNone(
            rows[target["operation_id"]]["lease_owner_hash"]
        )
        self.assertEqual(
            db.fetchone(
                "SELECT priority_streak FROM ai_dispatch_state "
                "WHERE service_key='durable_ai'"
            )["priority_streak"],
            before_streak,
        )

    def test_native_dispatcher_passes_exact_operation_into_sql_claim(self):
        operation_id = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        lease = mock.Mock(operation_id=operation_id)
        with (
            mock.patch.dict(
                os.environ,
                {"NOTEAI_DURABLE_AI_SUSPENDED": "0"},
            ),
            mock.patch.object(db, "using_postgres", return_value=True),
            mock.patch.object(
                durable_ai,
                "database_role_matches",
                return_value=True,
            ),
            mock.patch.object(
                durable_ai,
                "claim_outbox",
                return_value=lease,
            ) as claim,
            mock.patch.object(
                durable_ai,
                "mark_outbox_delivered_and_notify",
                return_value=True,
            ),
        ):
            result = durable_ai_worker.PostgresOutboxDispatcher().run_once(
                operation_id=operation_id,
            )

        self.assertEqual(result["status"], "delivered")
        claim.assert_called_once_with(
            owner_token=None,
            operation_id=operation_id,
            now=None,
        )

    def test_postgres_dispatcher_fails_closed_before_sqlite_claim(self):
        self.create_user("u-native-dispatch-sqlite")
        self.admit("u-native-dispatch-sqlite")
        before = dict(db.fetchone("SELECT * FROM ai_operation_outbox"))

        result = durable_ai_worker.PostgresOutboxDispatcher().run_once()

        after = dict(db.fetchone("SELECT * FROM ai_operation_outbox"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "postgres_required")
        self.assertEqual(after, before)

    def test_native_dispatcher_rejects_wrong_database_session_before_claim(self):
        with (
            mock.patch.object(db, "using_postgres", return_value=True),
            mock.patch.object(
                durable_ai,
                "database_role_matches",
                return_value=False,
            ),
            mock.patch.object(
                durable_ai,
                "claim_outbox",
                side_effect=AssertionError("claim must not run"),
            ),
        ):
            result = durable_ai_worker.PostgresOutboxDispatcher().run_once()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "database_role_mismatch")

    def test_database_role_requires_matching_session_and_current_user(self):
        rows = (
            {
                "session_role": "noteai_ai_worker",
                "database_role": "noteai_ai_worker",
            },
            {
                "session_role": "noteai_admin",
                "database_role": "noteai_ai_worker",
            },
        )
        with mock.patch.object(db, "using_postgres", return_value=True):
            with mock.patch.object(db, "fetchone", return_value=rows[0]):
                self.assertTrue(
                    durable_ai.database_role_matches("noteai_ai_worker")
                )
            with mock.patch.object(db, "fetchone", return_value=rows[1]):
                self.assertFalse(
                    durable_ai.database_role_matches("noteai_ai_worker")
                )

    def test_postgres_notify_helper_rejects_sqlite_without_ack(self):
        self.create_user("u-native-notify-sqlite")
        self.admit("u-native-notify-sqlite")
        lease = durable_ai.claim_outbox(
            owner_token="sqlite-native-notify-owner",
            now=self.now + timedelta(milliseconds=250),
        )
        with self.assertRaises(durable_ai.DurableAiError) as rejected:
            durable_ai.mark_outbox_delivered_and_notify(
                lease,
                now=self.now + timedelta(milliseconds=500),
            )
        self.assertEqual(rejected.exception.code, "DURABLE_AI_POSTGRES_REQUIRED")
        row = dict(db.fetchone("SELECT * FROM ai_operation_outbox"))
        self.assertEqual(row["state"], "pending")
        self.assertIsNone(row["delivered_at"])

    def test_pending_outbox_uuid_never_reaches_processor(self):
        self.create_user("u-pending-worker")
        admitted = self.admit("u-pending-worker")
        processor = mock.Mock()

        result = durable_ai_worker.DurableAiWorker(
            processor=processor,
            store=self.store,
        ).run_message(
            admitted["operation_id"],
            owner_token="pending-worker-owner",
            now=self.now + timedelta(seconds=1),
        )

        self.assertEqual(result["status"], "not_claimed")
        processor.assert_not_called()
        self.assertEqual(self.count("ai_provider_attempts"), 0)
        self.assertEqual(
            db.fetchone("SELECT state FROM ai_operation_outbox")["state"],
            "pending",
        )

    def test_expired_delivered_operation_is_reclaimed_without_requeue(self):
        self.create_user("u-direct-takeover")
        admitted = self.admit("u-direct-takeover")
        self.deliver(admitted["operation_id"])
        first = durable_ai.claim_delivered_operation(
            admitted["operation_id"],
            lease_seconds=10,
            owner_token="direct-takeover-worker-one",
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(first.fence, 1)

        replacement = durable_ai.claim_next_delivered_operation(
            lease_seconds=10,
            owner_token="direct-takeover-worker-two",
            now=self.now + timedelta(seconds=12),
        )

        self.assertEqual(replacement.operation_id, admitted["operation_id"])
        self.assertEqual(replacement.fence, 2)
        self.assertIsNone(
            ai_operations.heartbeat_operation(
                first,
                lease_seconds=10,
                now=self.now + timedelta(seconds=13),
            )
        )
        operation = ai_operations.get_operation(admitted["operation_id"])
        self.assertEqual(operation["claim_count"], 2)
        self.assertEqual(
            [
                event["event_type"]
                for event in ai_operations.list_events(
                    admitted["operation_id"]
                )
            ][-2:],
            ["claimed", "lease_taken_over"],
        )
        outbox = dict(db.fetchone("SELECT * FROM ai_operation_outbox"))
        self.assertEqual(outbox["state"], "delivered")
        self.assertIsNotNone(outbox["delivered_at"])
        self.assertEqual(self.count("ai_provider_attempts"), 0)

    def test_provider_started_delivered_operation_is_not_reclaimed(self):
        self.create_user("u-started-no-takeover")
        admitted = self.admit("u-started-no-takeover")
        self.deliver(admitted["operation_id"])
        lease = durable_ai.claim_delivered_operation(
            admitted["operation_id"],
            lease_seconds=10,
            owner_token="provider-started-worker-one",
            now=self.now + timedelta(seconds=1),
        )
        attempt = durable_ai.begin_provider_attempt_for_user(
            lease,
            user_id="u-started-no-takeover",
            provider="claude",
            request_hash=ai_operations.sha256_digest("started-request"),
            model_hash=ai_operations.sha256_digest("started-model"),
            now=self.now + timedelta(seconds=2),
        )
        self.assertIsNotNone(attempt)

        replacement = durable_ai.claim_next_delivered_operation(
            lease_seconds=10,
            owner_token="provider-started-worker-two",
            now=self.now + timedelta(seconds=12),
        )

        self.assertIsNone(replacement)
        self.assertEqual(
            ai_operations.get_operation(admitted["operation_id"])[
                "provider_phase"
            ],
            "provider_started",
        )

    def test_two_concurrent_delivered_claims_have_one_winner(self):
        self.create_user("u-two-workers")
        admitted = self.admit("u-two-workers")
        self.deliver(admitted["operation_id"])

        def claim(index):
            return durable_ai.claim_delivered_operation(
                admitted["operation_id"],
                lease_seconds=30,
                owner_token=f"concurrent-worker-owner-{index:02d}",
                now=self.now + timedelta(seconds=1),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            leases = list(executor.map(claim, range(2)))
        winners = [lease for lease in leases if lease is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].fence, 1)

    def test_worker_loop_polls_after_lost_notification_timeout(self):
        events = []

        class Listener:
            def open(inner_self):
                events.append("open")
                return inner_self

            def wait(inner_self, _timeout):
                events.append("wait")
                return False

            def close(inner_self):
                events.append("close")

        class Worker:
            def run_once(inner_self):
                events.append("poll")
                return {"status": "idle", "provider_called": False}

        result = durable_ai_worker.run_worker_loop(
            Worker(),
            listener=Listener(),
            max_iterations=2,
        )

        self.assertEqual(result["iterations"], 2)
        self.assertEqual(events, ["open", "poll", "wait", "poll", "close"])

    def test_lost_notification_is_recovered_by_authoritative_database_poll(self):
        self.create_user("u-lost-real-poll")
        admitted = self.admit("u-lost-real-poll")
        processor = mock.Mock(side_effect=RuntimeError("stop before provider"))
        testcase = self

        class Listener:
            def open(inner_self):
                return inner_self

            def wait(inner_self, _timeout):
                testcase.deliver(admitted["operation_id"])
                return False

            def close(inner_self):
                pass

        result = durable_ai_worker.run_worker_loop(
            durable_ai_worker.DurableAiWorker(
                processor=processor,
                store=self.store,
            ),
            listener=Listener(),
            max_iterations=2,
        )

        self.assertEqual(result["status"], "refunded")
        processor.assert_called_once()
        self.assertEqual(self.count("ai_provider_attempts"), 0)

    def test_fail_closed_loops_stop_without_wait_or_repeat(self):
        dispatcher = mock.Mock()
        dispatcher.run_once.return_value = {
            "status": "blocked",
            "provider_called": False,
        }
        with (
            mock.patch.object(
                durable_ai_worker,
                "PostgresOutboxDispatcher",
                return_value=dispatcher,
            ),
            mock.patch.object(durable_ai_worker.time, "sleep") as sleep,
            self.assertRaisesRegex(RuntimeError, "dispatcher loop stopped"),
        ):
            durable_ai_worker.run_dispatcher_loop(max_iterations=2)
        dispatcher.run_once.assert_called_once_with()
        sleep.assert_not_called()

        listener = mock.Mock()
        listener.open.return_value = listener
        worker = mock.Mock()
        worker.run_once.return_value = {
            "status": "fence_lost",
            "provider_called": False,
        }
        with self.assertRaisesRegex(RuntimeError, "worker loop stopped"):
            durable_ai_worker.run_worker_loop(
                worker,
                listener=listener,
                max_iterations=2,
            )
        worker.run_once.assert_called_once_with()
        listener.wait.assert_not_called()
        listener.close.assert_called_once_with()

    def test_listener_closes_connection_when_listen_fails(self):
        connection = mock.Mock()
        connection.execute.side_effect = RuntimeError("listen rejected")
        with (
            mock.patch.object(db, "using_postgres", return_value=True),
            mock.patch("psycopg.connect", return_value=connection),
            mock.patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://synthetic.invalid/db"},
            ),
            self.assertRaisesRegex(RuntimeError, "listen rejected"),
        ):
            durable_ai_worker.PostgresWakeListener().open()
        connection.close.assert_called_once_with()

    def test_internal_acceptance_is_exact_one_with_short_lease(self):
        operation_id = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        worker = mock.Mock()
        worker.run_message.return_value = {
            "status": "refunded",
            "provider_called": False,
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_DURABLE_AI_COMPONENT": "worker",
                    "NOTEAI_DURABLE_AI_SUSPENDED": "0",
                    "NOTEAI_DURABLE_AI_PROCESSOR": "internal-acceptance-v1",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": operation_id,
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION": "fail_before_provider",
                },
            ),
            mock.patch.object(
                durable_ai_worker.private_storage,
                "configure_from_environment",
                return_value=True,
            ),
            mock.patch.object(
                durable_ai_worker,
                "DurableAiWorker",
                return_value=worker,
            ) as worker_type,
        ):
            result = durable_ai_worker.main(["--worker-once"])

        self.assertEqual(result, 0)
        self.assertEqual(
            worker_type.call_args.kwargs["lease_seconds"],
            durable_ai_worker.INTERNAL_ACCEPTANCE_LEASE_SECONDS,
        )
        worker.run_message.assert_called_once_with(operation_id)
        worker.run_once.assert_not_called()

    def test_internal_acceptance_dispatcher_is_exact_one(self):
        operation_id = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        dispatcher = mock.Mock()
        dispatcher.run_once.return_value = {
            "status": "delivered",
            "operation_id": operation_id,
            "provider_called": False,
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_DURABLE_AI_COMPONENT": "dispatcher",
                    "NOTEAI_DURABLE_AI_SUSPENDED": "0",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": operation_id,
                },
            ),
            mock.patch.object(
                durable_ai_worker,
                "PostgresOutboxDispatcher",
                return_value=dispatcher,
            ),
        ):
            result = durable_ai_worker.main(["--dispatcher-once"])

        self.assertEqual(result, 0)
        dispatcher.run_once.assert_called_once_with(
            operation_id=operation_id,
        )

    def test_internal_acceptance_dispatcher_does_not_accept_idle(self):
        operation_id = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        dispatcher = mock.Mock()
        dispatcher.run_once.return_value = {
            "status": "idle",
            "provider_called": False,
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_DURABLE_AI_COMPONENT": "dispatcher",
                    "NOTEAI_DURABLE_AI_SUSPENDED": "0",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": operation_id,
                },
            ),
            mock.patch.object(
                durable_ai_worker,
                "PostgresOutboxDispatcher",
                return_value=dispatcher,
            ),
        ):
            result = durable_ai_worker.main(["--dispatcher-once"])

        self.assertEqual(result, 1)
        dispatcher.run_once.assert_called_once_with(
            operation_id=operation_id,
        )

    def test_internal_acceptance_hold_is_bounded_but_kill_safe(self):
        operation_id = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        context = durable_ai_worker.WorkerContext(
            lease=mock.Mock(operation_id=operation_id),
            user_id="synthetic-acceptance-user",
            operation_kind="analyze",
            queue=mock.Mock(),
        )
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": operation_id,
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION": "hold_after_payload",
                },
            ),
            mock.patch.object(
                ai_operations,
                "append_progress_event",
                return_value=True,
            ),
            mock.patch.object(durable_ai_worker.time, "sleep") as sleep,
            self.assertRaisesRegex(RuntimeError, "hold expired"),
        ):
            durable_ai_worker._internal_acceptance_processor(
                {"acceptance": "durable-ai-v1"},
                context,
            )
        sleep.assert_called_once_with(
            durable_ai_worker.INTERNAL_ACCEPTANCE_HOLD_SECONDS
        )
        self.assertGreaterEqual(
            durable_ai_worker.INTERNAL_ACCEPTANCE_HOLD_SECONDS,
            120,
        )

    def test_worker_component_requires_private_storage_before_command(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_DURABLE_AI_COMPONENT": "worker",
                    "NOTEAI_DURABLE_AI_SUSPENDED": "1",
                },
            ),
            mock.patch.object(
                durable_ai_worker.private_storage,
                "configure_from_environment",
                return_value=False,
            ),
            mock.patch.object(durable_ai_worker, "DurableAiWorker") as worker,
        ):
            result = durable_ai_worker.main(["--worker-once"])

        self.assertEqual(result, 78)
        worker.assert_not_called()

    def test_notification_payload_never_selects_pending_work(self):
        self.create_user("u-fake-notify")
        admitted = self.admit("u-fake-notify")
        processor = mock.Mock()

        class Listener:
            def open(inner_self):
                return inner_self

            def wait(inner_self, _timeout):
                return True

            def close(inner_self):
                pass

        result = durable_ai_worker.run_worker_loop(
            durable_ai_worker.DurableAiWorker(
                processor=processor,
                store=self.store,
            ),
            listener=Listener(),
            max_iterations=2,
        )

        self.assertEqual(result["status"], "idle")
        processor.assert_not_called()
        self.assertEqual(
            durable_ai.status_for_user(
                "u-fake-notify", admitted["operation_id"]
            )["status"],
            "queued",
        )

    def test_dispatch_is_fifo_with_three_to_one_priority_ceiling(self):
        self.create_user("u-standard")
        self.create_user("u-priority")
        billing.upgrade_subscription("u-priority", "pro_plus")
        labels = []
        for index in range(8):
            labels.append(
                (
                    "P",
                    self.admit(
                        "u-priority",
                        key=f"priority-{index}",
                        operation="chat_rewrite",
                        payload={"content": f"priority-{index}"},
                    )["operation_id"],
                )
            )
            labels.append(
                (
                    "S",
                    self.admit(
                        "u-standard",
                        key=f"standard-{index}",
                        operation="chat_rewrite",
                        payload={"content": f"standard-{index}"},
                    )["operation_id"],
                )
            )
        lane_by_id = {operation_id: lane for lane, operation_id in labels}
        sequence = []
        for index in range(8):
            lease = durable_ai.claim_outbox(
                owner_token=f"fair-dispatch-owner-{index:04d}",
                now=self.now + timedelta(seconds=1),
            )
            self.assertIsNotNone(lease)
            sequence.append(lane_by_id[lease.operation_id])
            self.assertTrue(
                durable_ai.mark_outbox_delivered(
                    lease,
                    now=self.now + timedelta(seconds=2),
                )
            )
        self.assertEqual(sequence, ["P", "P", "P", "S", "P", "P", "P", "S"])

    def test_expired_pre_provider_lease_is_safely_redelivered_with_new_fence(self):
        self.create_user("u-safe-redelivery")
        admitted = self.admit("u-safe-redelivery")
        outbox = durable_ai.claim_outbox(
            owner_token="redelivery-dispatcher-0001",
            now=self.now + timedelta(seconds=1),
        )
        self.assertTrue(
            durable_ai.mark_outbox_delivered(
                outbox,
                now=self.now + timedelta(seconds=2),
            )
        )
        first = ai_operations.claim_operation(
            admitted["operation_id"],
            lease_seconds=10,
            owner_token="redelivery-worker-owner-01",
            now=self.now + timedelta(seconds=3),
        )
        self.assertEqual(first.fence, 1)
        self.assertEqual(
            durable_ai.recover_unstarted_leases(
                now=self.now + timedelta(seconds=13),
            ),
            1,
        )
        restored = dict(db.fetchone("SELECT * FROM ai_operation_outbox"))
        self.assertEqual(restored["state"], "pending")
        self.assertIsNone(restored["delivered_at"])
        redelivery = durable_ai.claim_outbox(
            owner_token="redelivery-dispatcher-0002",
            now=self.now + timedelta(seconds=14),
        )
        self.assertEqual(redelivery.operation_id, admitted["operation_id"])
        self.assertTrue(
            durable_ai.mark_outbox_delivered(
                redelivery,
                now=self.now + timedelta(seconds=15),
            )
        )
        replacement = ai_operations.claim_operation(
            admitted["operation_id"],
            lease_seconds=10,
            owner_token="redelivery-worker-owner-02",
            now=self.now + timedelta(seconds=15),
        )
        self.assertEqual(replacement.fence, 2)
        self.assertFalse(
            ai_operations.append_progress_event(
                first,
                detail_hash=ai_operations.sha256_digest("late-old-owner"),
                now=self.now + timedelta(seconds=16),
            )
        )
        self.assertEqual(self.count("ai_provider_attempts"), 0)

    def test_stale_provider_side_effect_becomes_manual_without_retry_or_refund(self):
        self.create_user("u-stale-provider")
        before = billing.get_subscription("u-stale-provider")[
            "used_monthly_credits"
        ]
        admitted = self.admit("u-stale-provider")
        charged = billing.get_subscription("u-stale-provider")[
            "used_monthly_credits"
        ]
        lease = ai_operations.claim_operation(
            admitted["operation_id"],
            lease_seconds=10,
            owner_token="stale-provider-worker-01",
            now=self.now + timedelta(seconds=1),
        )
        attempt = __import__("task_queue").DatabaseTaskQueue().record_provider_started(
            lease,
            provider="claude",
            request_hash=ai_operations.sha256_digest("stale-request"),
            model_hash=ai_operations.sha256_digest("stale-model"),
            now=self.now + timedelta(seconds=2),
        )
        self.assertIsNotNone(attempt)
        self.assertEqual(
            durable_ai.reconcile_stale_provider_outcomes(
                now=self.now + timedelta(seconds=11),
            ),
            1,
        )
        status = durable_ai.status_for_user(
            "u-stale-provider",
            admitted["operation_id"],
        )
        self.assertEqual(status["status"], "outcome_unknown")
        self.assertEqual(status["billing_state"], "needs_manual")
        self.assertEqual(status["failure_code"], "provider_outcome_unknown")
        self.assertEqual(
            billing.get_subscription("u-stale-provider")["used_monthly_credits"],
            charged,
        )
        self.assertNotEqual(before, charged)
        self.assertEqual(
            ai_operations.list_provider_attempts(admitted["operation_id"])[0][
                "state"
            ],
            "outcome_unknown",
        )
        self.assertEqual(
            durable_ai.reconcile_stale_provider_outcomes(
                now=self.now + timedelta(seconds=12),
            ),
            0,
        )
        self.assertFalse(durable_ai.health()["ok"])

    def test_worker_supports_multiple_provider_attempts_and_atomic_success(self):
        self.create_user("u-success")
        admitted = self.admit("u-success")
        self.deliver(admitted["operation_id"])

        def processor(payload, context):
            first = context.invoke_provider(
                provider="claude",
                model="claude-sonnet-4-6",
                request={"content": payload["content"], "step": 1},
                call=lambda: {"draft": "one"},
                now=self.now + timedelta(seconds=2),
            )
            second = context.invoke_provider(
                provider="kimi",
                model="kimi-k2.6",
                request={"draft": first["draft"], "step": 2},
                call=lambda: {"final": "delivered"},
                now=self.now + timedelta(seconds=3),
            )
            return {"result": second["final"]}

        result = durable_ai_worker.DurableAiWorker(
            processor=processor,
            store=self.store,
            enforce_runtime_role=True,
        ).run_message(
            admitted["operation_id"],
            owner_token="worker-owner-success-0001",
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(result["status"], "succeeded")
        operation = ai_operations.get_operation(admitted["operation_id"])
        self.assertEqual(operation["status"], "succeeded")
        self.assertEqual(operation["provider_attempt_count"], 2)
        attempts = ai_operations.list_provider_attempts(admitted["operation_id"])
        self.assertEqual(
            [attempt["state"] for attempt in attempts],
            ["provider_succeeded", "provider_succeeded"],
        )
        settlement = dict(
            db.fetchone(
                "SELECT * FROM ai_operation_settlements WHERE operation_id=?",
                (admitted["operation_id"],),
            )
        )
        self.assertEqual(settlement["billing_state"], "completed")
        self.assertIsNotNone(settlement["result_ref_id"])
        claim = dict(db.fetchone("SELECT * FROM idempotency_requests"))
        self.assertEqual(claim["status"], "completed")
        self.assertEqual(claim["complete_applied"], 1)
        self.assertEqual(
            durable_ai.result_for_user(
                "u-success", admitted["operation_id"], store=self.store
            ),
            {"result": "delivered"},
        )
        self.assertIsNone(billing._ACTIVE_USAGE_ID.get())

    def test_known_provider_failure_refunds_once(self):
        self.create_user("u-known-fail")
        before = billing.get_subscription("u-known-fail")["used_monthly_credits"]
        admitted = self.admit("u-known-fail")
        self.deliver(admitted["operation_id"])
        charged = billing.get_subscription("u-known-fail")["used_monthly_credits"]
        self.assertEqual(charged - before, 6)

        def processor(_payload, context):
            return context.invoke_provider(
                provider="claude",
                model="claude-sonnet-4-6",
                request={"step": 1},
                call=lambda: (_ for _ in ()).throw(
                    durable_ai_worker.KnownProviderFailure("known rejection")
                ),
                now=self.now + timedelta(seconds=2),
            )

        result = durable_ai_worker.DurableAiWorker(
            processor=processor,
            store=self.store,
        ).run_message(
            admitted["operation_id"],
            owner_token="worker-owner-known-fail",
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(result["status"], "refunded")
        self.assertEqual(
            billing.get_subscription("u-known-fail")["used_monthly_credits"],
            before,
        )
        self.assertEqual(
            durable_ai.status_for_user(
                "u-known-fail", admitted["operation_id"]
            )["user_status"],
            "refunded",
        )
        self.assertEqual(
            db.fetchone("SELECT source FROM usage_records")["source"],
            "refunded",
        )
        second = durable_ai.settle_failure(
            ai_operations.OperationLease(
                admitted["operation_id"],
                "worker-owner-known-fail",
                1,
                (self.now + timedelta(minutes=15)).isoformat(),
            ),
            failure_code="provider_failed",
            now=self.now + timedelta(seconds=3),
        )
        self.assertFalse(second)

    def test_unknown_provider_outcome_never_refunds_or_retries(self):
        self.create_user("u-unknown")
        before = billing.get_subscription("u-unknown")["used_monthly_credits"]
        admitted = self.admit("u-unknown")
        self.deliver(admitted["operation_id"])
        charged = billing.get_subscription("u-unknown")["used_monthly_credits"]

        def processor(_payload, context):
            return context.invoke_provider(
                provider="kimi",
                model="kimi-k2.6",
                request={"step": 1},
                call=lambda: (_ for _ in ()).throw(
                    TimeoutError("ambiguous network boundary")
                ),
                now=self.now + timedelta(seconds=2),
            )

        worker = durable_ai_worker.DurableAiWorker(
            processor=processor,
            store=self.store,
        )
        result = worker.run_message(
            admitted["operation_id"],
            owner_token="worker-owner-unknown-01",
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(result["status"], "needs_manual")
        status = durable_ai.status_for_user("u-unknown", admitted["operation_id"])
        self.assertEqual(status["status"], "outcome_unknown")
        self.assertEqual(status["billing_state"], "needs_manual")
        self.assertEqual(status["failure_code"], "provider_outcome_unknown")
        self.assertEqual(
            billing.get_subscription("u-unknown")["used_monthly_credits"],
            charged,
        )
        self.assertNotEqual(charged, before)
        self.assertEqual(
            worker.run_message(
                admitted["operation_id"],
                owner_token="worker-owner-unknown-02",
                now=self.now + timedelta(minutes=20),
            )["status"],
            "not_claimed",
        )
        self.assertEqual(
            ai_operations.list_provider_attempts(admitted["operation_id"])[0][
                "state"
            ],
            "outcome_unknown",
        )

    def test_worker_failure_before_provider_refunds(self):
        self.create_user("u-worker-fail")
        before = billing.get_subscription("u-worker-fail")["used_monthly_credits"]
        admitted = self.admit("u-worker-fail")
        self.deliver(admitted["operation_id"])
        worker = durable_ai_worker.DurableAiWorker(
            processor=lambda _payload, _context: (_ for _ in ()).throw(
                RuntimeError("private processor error")
            ),
            store=self.store,
        )
        result = worker.run_message(
            admitted["operation_id"],
            owner_token="worker-owner-internal-01",
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(result["status"], "refunded")
        self.assertEqual(
            billing.get_subscription("u-worker-fail")["used_monthly_credits"],
            before,
        )
        serialized = json.dumps(result)
        self.assertNotIn("private processor error", serialized)

    def test_terminal_billing_failure_rolls_back_operation_transition(self):
        self.create_user("u-atomic-fail")
        admitted = self.admit("u-atomic-fail")
        self.deliver(admitted["operation_id"])

        def processor(payload, context):
            return context.invoke_provider(
                provider="claude",
                model="claude-sonnet-4-6",
                request=payload,
                call=lambda: (_ for _ in ()).throw(
                    durable_ai_worker.KnownProviderFailure("known failure")
                ),
                now=self.now + timedelta(seconds=2),
            )

        original = billing.refund_operation_charge_in_transaction
        with mock.patch.object(
            billing,
            "refund_operation_charge_in_transaction",
            side_effect=RuntimeError("synthetic settlement write failure"),
        ):
            worker = durable_ai_worker.DurableAiWorker(
                processor=processor,
                store=self.store,
            )
            with self.assertRaisesRegex(RuntimeError, "settlement write failure"):
                worker.run_message(
                    admitted["operation_id"],
                    owner_token="worker-owner-atomic-fail",
                    now=self.now + timedelta(seconds=1),
                )
        self.assertIsNotNone(original)
        operation = ai_operations.get_operation(admitted["operation_id"])
        self.assertEqual(operation["status"], "running")
        self.assertEqual(
            db.fetchone("SELECT billing_state FROM ai_operation_settlements")[
                "billing_state"
            ],
            "charged",
        )
        self.assertEqual(
            db.fetchone("SELECT status FROM idempotency_requests")["status"],
            "running",
        )

    def test_result_object_is_removed_when_terminal_transaction_fails(self):
        self.create_user("u-result-rollback")
        admitted = self.admit("u-result-rollback")
        self.deliver(admitted["operation_id"])

        def processor(payload, context):
            context.invoke_provider(
                provider="claude",
                model="claude-sonnet-4-6",
                request=payload,
                call=lambda: {"ok": True},
                now=self.now + timedelta(seconds=2),
            )
            return {"private_result": "must not become orphaned"}

        with mock.patch.object(
            ai_operations,
            "finish_operation_in_transaction",
            side_effect=RuntimeError("synthetic terminal transaction failure"),
        ):
            result = durable_ai_worker.DurableAiWorker(
                processor=processor,
                store=self.store,
            ).run_message(
                admitted["operation_id"],
                owner_token="worker-owner-result-rollback",
                now=self.now + timedelta(seconds=1),
            )
        self.assertEqual(result["status"], "needs_manual")
        self.assertEqual(self.count("ai_payload_refs"), 1)
        self.assertEqual(len(self.store._objects), 1)
        self.assertEqual(
            db.fetchone("SELECT billing_state FROM ai_operation_settlements")[
                "billing_state"
            ],
            "needs_manual",
        )

    def test_health_and_admin_summary_are_read_only_and_content_free(self):
        self.create_user("u-health")
        self.admit("u-health")
        before = {
            table: self.count(table)
            for table in (
                "ai_operations",
                "ai_operation_events",
                "ai_operation_outbox",
                "ai_operation_settlements",
                "usage_records",
            )
        }
        health = durable_ai.health()
        summary = durable_ai.admin_summary()
        after = {table: self.count(table) for table in before}
        self.assertEqual(before, after)
        self.assertTrue(health["ok"])
        self.assertFalse(health["provider_called"])
        self.assertFalse(health["database_write"])
        self.assertFalse(summary["raw_payload_included"])
        self.assertFalse(summary["provider_called"])
        serialized = json.dumps(summary)
        self.assertNotIn("subject_hash", serialized)
        self.assertNotIn("request_hash", serialized)
        self.assertNotIn("object_key", serialized)

    def test_default_suspension_returns_before_database_or_provider_work(self):
        self.create_user("u-suspended")
        admitted = self.admit("u-suspended")
        os.environ["NOTEAI_DURABLE_AI_SUSPENDED"] = "1"
        processor = mock.Mock()
        with mock.patch.object(
            durable_ai,
            "claim_delivered_operation",
            side_effect=AssertionError("database claim must not run"),
        ):
            result = durable_ai_worker.DurableAiWorker(
                processor=processor,
                store=self.store,
            ).run_message(admitted["operation_id"])
        self.assertEqual(result["status"], "suspended")
        self.assertFalse(result["provider_called"])
        self.assertFalse(result["database_write"])
        processor.assert_not_called()

    def test_account_deletion_cancels_and_refunds_queued_durable_job(self):
        self.create_user("u-delete-queued")
        before = billing.get_subscription("u-delete-queued")[
            "used_monthly_credits"
        ]
        admitted = self.admit("u-delete-queued")
        self.assertGreater(
            billing.get_subscription("u-delete-queued")[
                "used_monthly_credits"
            ],
            before,
        )
        request = content_retention.request_account_deletion("u-delete-queued")
        self.assertEqual(request["status"], "requested")
        self.assertEqual(
            ai_operations.get_operation(admitted["operation_id"])["status"],
            "cancelled",
        )
        self.assertEqual(
            db.fetchone("SELECT billing_state FROM ai_operation_settlements")[
                "billing_state"
            ],
            "refunded",
        )
        self.assertEqual(
            db.fetchone("SELECT state FROM ai_operation_outbox")["state"],
            "dead",
        )
        self.assertEqual(
            db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions "
                "WHERE user_id='u-delete-queued' AND is_active=1"
            )["used_monthly_credits"],
            before,
        )

    def test_account_deletion_invalidates_claimed_provider_free_lease(self):
        self.create_user("u-delete-claimed")
        admitted = self.admit("u-delete-claimed")
        lease = ai_operations.claim_operation(
            admitted["operation_id"],
            lease_seconds=30,
            owner_token="delete-claimed-worker-owner",
            now=self.now + timedelta(seconds=1),
        )
        self.assertIsNotNone(lease)
        content_retention.request_account_deletion("u-delete-claimed")
        self.assertEqual(
            ai_operations.get_operation(admitted["operation_id"])["status"],
            "cancelled",
        )
        self.assertFalse(
            ai_operations.append_progress_event(
                lease,
                now=self.now + timedelta(seconds=2),
            )
        )
        self.assertIsNone(
            durable_ai.begin_provider_attempt_for_user(
                lease,
                user_id="u-delete-claimed",
                provider="claude",
                request_hash=ai_operations.sha256_digest("deleted-request"),
                model_hash=ai_operations.sha256_digest("deleted-model"),
                now=self.now + timedelta(seconds=2),
            )
        )
        self.assertEqual(self.count("ai_provider_attempts"), 0)

    def test_account_deletion_waits_after_provider_admission_without_calling_it(self):
        self.create_user("u-delete-provider-started")
        admitted = self.admit("u-delete-provider-started")
        lease = ai_operations.claim_operation(
            admitted["operation_id"],
            lease_seconds=30,
            owner_token="delete-provider-worker-owner",
            now=self.now + timedelta(seconds=1),
        )
        attempt = durable_ai.begin_provider_attempt_for_user(
            lease,
            user_id="u-delete-provider-started",
            provider="kimi",
            request_hash=ai_operations.sha256_digest("provider-request"),
            model_hash=ai_operations.sha256_digest("provider-model"),
            now=self.now + timedelta(seconds=2),
        )
        self.assertIsNotNone(attempt)
        with self.assertRaisesRegex(ValueError, "正在处理的 AI 请求"):
            content_retention.request_account_deletion(
                "u-delete-provider-started"
            )
        self.assertIsNone(
            db.fetchone(
                "SELECT deletion_requested_at FROM users "
                "WHERE id='u-delete-provider-started'"
            )["deletion_requested_at"]
        )
        self.assertEqual(self.count("account_deletion_requests"), 0)

    def test_account_deletion_erases_objects_before_owner_join(self):
        self.create_user("u-delete-payloads")
        admitted = self.admit("u-delete-payloads")
        self.deliver(admitted["operation_id"])

        def processor(payload, context):
            context.invoke_provider(
                provider="claude",
                model="claude-sonnet-4-6",
                request=payload,
                call=lambda: {"ok": True},
            )
            return {"private_result": "erase me"}

        result = durable_ai_worker.DurableAiWorker(
            processor=processor,
            store=self.store,
        ).run_message(
            admitted["operation_id"],
            owner_token="delete-payload-worker",
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.count("ai_payload_refs"), 2)
        request = content_retention.request_account_deletion(
            "u-delete-payloads"
        )
        completed = content_retention.process_due_account_deletions(
            now=datetime.now(timezone.utc) + timedelta(days=2),
            payload_store=self.store,
        )
        self.assertEqual(completed, [request["id"]])
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM ai_payload_refs WHERE state='ready'"
            )["c"],
            0,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM ai_payload_refs WHERE state='deleted'"
            )["c"],
            2,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM users WHERE id='u-delete-payloads'"
            )["c"],
            0,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM ai_operation_admissions "
                "WHERE operation_id=?",
                (admitted["operation_id"],),
            )["c"],
            0,
        )

    def test_account_deletion_fails_closed_when_object_store_is_unavailable(self):
        self.create_user("u-delete-blocked")
        admitted = self.admit("u-delete-blocked")
        lease = ai_operations.claim_operation(
            admitted["operation_id"],
            lease_seconds=30,
            owner_token="delete-block-worker",
        )
        self.assertTrue(
            durable_ai.settle_failure(
                lease,
                failure_code="worker_failed",
            )
        )
        request = content_retention.request_account_deletion(
            "u-delete-blocked"
        )
        completed = content_retention.process_due_account_deletions(
            now=datetime.now(timezone.utc) + timedelta(days=2),
            payload_store=durable_ai.UnavailablePayloadStore(),
        )
        self.assertEqual(completed, [])
        self.assertEqual(
            db.fetchone(
                "SELECT status FROM account_deletion_requests WHERE id=?",
                (request["id"],),
            )["status"],
            "requested",
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM users WHERE id='u-delete-blocked'"
            )["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM ai_payload_refs "
                "WHERE operation_id=? AND state='ready'",
                (admitted["operation_id"],),
            )["c"],
            1,
        )

    def test_api_admin_and_runtime_contracts_are_explicit_and_default_closed(self):
        api_source = (MODEL_DIR / "api.py").read_text(encoding="utf-8")
        admin_source = (MODEL_DIR / "admin_server.py").read_text(encoding="utf-8")
        entrypoint = (
            ROOT / "scripts" / "docker_entrypoint.sh"
        ).read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        production_compose = (
            ROOT / "deploy" / "production" / "docker-compose.yml"
        ).read_text(encoding="utf-8")
        for route in (
            "/ai/jobs/analyze",
            "/ai/jobs/generate",
            "/ai/jobs/chat-rewrite",
            "/ai/jobs/{operation_id}",
            "/ai/jobs/{operation_id}/events",
            "/ai/jobs/{operation_id}/result",
        ):
            self.assertIn(route, api_source)
        self.assertIn('os.environ.get("NOTEAI_DURABLE_AI_ADMISSION_ENABLED", "0")', api_source)
        self.assertIn("/admin/ai-operations", admin_source)
        self.assertIn("FROM runtime-common AS ai-worker-runtime", dockerfile)
        self.assertIn("ai-worker", entrypoint)
        self.assertIn("NOTEAI_DURABLE_AI_SUSPENDED", entrypoint)
        self.assertIn('NOTEAI_DURABLE_AI_ADMISSION_ENABLED: "0"', production_compose)
        worker_block = production_compose.split("\n  ai-worker:\n", 1)[1].split(
            "\n  xhs-trends:\n", 1
        )[0]
        self.assertIn('restart: "no"', worker_block)
        self.assertIn('cpus: "1.00"', worker_block)
        self.assertIn("mem_limit: 1536m", worker_block)
        self.assertIn("pids_limit: 96", worker_block)
        self.assertNotIn("ports:", worker_block)
        self.assertNotIn("volumes:", worker_block)
        self.assertIn("profiles:", worker_block)

    def test_source_contract_contains_no_implicit_provider_or_storage_adapter(self):
        source = inspect.getsource(durable_ai)
        worker_source = inspect.getsource(durable_ai_worker)
        self.assertIn("_payload_store: PayloadStore = UnavailablePayloadStore()", source)
        self.assertNotIn("boto3", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("httpx.", source)
        self.assertNotIn("anthropic.", worker_source)
        self.assertNotIn("moonshot", worker_source.lower())
        self.assertIn("production_processor_not_configured", worker_source)


if __name__ == "__main__":
    unittest.main()
