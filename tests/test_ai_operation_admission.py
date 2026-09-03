import hashlib
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
ai_operations = importlib.import_module("ai_operations")
idempotency = importlib.import_module("idempotency")


class AiOperationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        billing.clear_active_usage()

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        self.temp.cleanup()

    def create_user(self, user_id: str) -> None:
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                user_id,
                f"{user_id}_name",
                f"{user_id}@example.com",
                "hash",
                "salt",
                "2026-07-14T00:00:00+00:00",
            ),
        )

    @staticmethod
    def payload(label: str = "a") -> dict:
        return {"domain": "美食", "content": f"private-payload-{label}"}

    def admit(
        self,
        user_id: str,
        key: str,
        *,
        payload: dict | None = None,
        operation: str = "analyze",
    ) -> dict:
        return idempotency.admit_operation(
            user_id=user_id,
            operation=operation,
            request_id=key,
            payload=payload or self.payload(),
        )

    def assert_no_admission_writes(self) -> None:
        for table in (
            "idempotency_requests",
            "ai_operations",
            "ai_operation_events",
            "ai_operation_admissions",
            "usage_records",
            "subscriptions",
            "credits",
            "credit_transactions",
        ):
            self.assertEqual(
                db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")["c"],
                0,
                table,
            )

    def test_sqlite_and_postgres_link_schema_match_and_store_no_content(self):
        db.init_db()
        conn = db.get_conn()
        try:
            columns = {
                row["name"]: dict(row)
                for row in conn.execute(
                    "PRAGMA table_info(ai_operation_admissions)"
                ).fetchall()
            }
            foreign_keys = {
                row["from"]: (row["table"], row["to"], row["on_delete"])
                for row in conn.execute(
                    "PRAGMA foreign_key_list(ai_operation_admissions)"
                ).fetchall()
            }
            indexes = [
                (
                    dict(row),
                    tuple(
                        item["name"]
                        for item in conn.execute(
                            f"PRAGMA index_info({row['name']})"
                        ).fetchall()
                    ),
                )
                for row in conn.execute(
                    "PRAGMA index_list(ai_operation_admissions)"
                ).fetchall()
            ]
        finally:
            conn.close()

        self.assertEqual(
            set(columns),
            {"operation_id", "idempotency_request_id", "created_at"},
        )
        self.assertEqual(columns["operation_id"]["pk"], 1)
        self.assertEqual(columns["operation_id"]["notnull"], 1)
        self.assertEqual(columns["idempotency_request_id"]["notnull"], 1)
        self.assertEqual(
            foreign_keys,
            {
                "operation_id": ("ai_operations", "id", "RESTRICT"),
                "idempotency_request_id": (
                    "idempotency_requests",
                    "id",
                    "RESTRICT",
                ),
            },
        )
        self.assertIn(
            ("idempotency_request_id",),
            {columns for index, columns in indexes if index["unique"]},
        )

        migration = (
            ROOT
            / "model"
            / "migrations"
            / "postgres"
            / "0008_ai_operation_admissions.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS ai_operation_admissions", migration)
        self.assertIn("operation_id", migration)
        self.assertIn("idempotency_request_id", migration)
        self.assertIn("ON DELETE RESTRICT", migration)
        for forbidden in (
            "raw_key",
            "request_body",
            "prompt",
            "reasoning",
            "owner_token",
            "lease_token",
        ):
            self.assertNotIn(forbidden, migration)

        conn = db.get_conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO ai_operation_admissions("
                    "operation_id,idempotency_request_id,created_at) "
                    "VALUES(NULL,'missing-idempotency','2026-07-14T00:00:00+00:00')"
                )
        finally:
            conn.close()

    def test_twenty_concurrent_same_key_create_one_job_link_usage_and_charge(self):
        self.create_user("u-admit-concurrent")

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(
                pool.map(
                    lambda _index: self.admit(
                        "u-admit-concurrent", "same-admission-key"
                    ),
                    range(20),
                )
            )

        self.assertEqual(sum(row["state"] == "admitted" for row in results), 1)
        self.assertEqual(sum(row["state"] == "existing" for row in results), 19)
        operation_ids = {row["operation_id"] for row in results}
        self.assertEqual(len(operation_ids), 1)
        for table in (
            "idempotency_requests",
            "ai_operations",
            "ai_operation_events",
            "ai_operation_admissions",
            "usage_records",
        ):
            self.assertEqual(
                db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")["c"],
                1,
                table,
            )
        self.assertEqual(
            db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions "
                "WHERE user_id=? AND is_active=1",
                ("u-admit-concurrent",),
            )["used_monthly_credits"],
            6,
        )
        self.assertIsNone(billing._ACTIVE_USAGE_ID.get())

    def test_duplicate_payload_returns_same_job_and_conflict_does_not_charge(self):
        self.create_user("u-admit-conflict")
        first = self.admit("u-admit-conflict", "stable-key")
        duplicate = self.admit("u-admit-conflict", "stable-key")
        conflict = self.admit(
            "u-admit-conflict",
            "stable-key",
            payload=self.payload("different"),
        )

        self.assertEqual(first["state"], "admitted")
        self.assertEqual(duplicate["state"], "existing")
        self.assertEqual(duplicate["operation_id"], first["operation_id"])
        self.assertEqual(conflict, {"state": "conflict"})
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"], 1)

    def test_operation_insert_failure_rolls_back_idempotency_claim(self):
        self.create_user("u-fail-operation")
        with mock.patch.object(
            ai_operations,
            "enqueue_operation_in_transaction",
            side_effect=RuntimeError("synthetic operation insert failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "operation insert failure"):
                self.admit("u-fail-operation", "fail-operation-key")
        self.assert_no_admission_writes()

    def test_billing_failure_after_job_insert_rolls_back_job_event_and_link(self):
        self.create_user("u-fail-billing")
        with mock.patch.object(
            billing,
            "check_and_deduct_in_transaction",
            side_effect=HTTPException(status_code=402, detail="synthetic quota failure"),
        ):
            with self.assertRaises(HTTPException) as failed:
                self.admit("u-fail-billing", "fail-billing-key")
        self.assertEqual(failed.exception.status_code, 402)
        self.assert_no_admission_writes()

    def test_charge_marker_failure_rolls_back_charge_job_event_link_and_usage(self):
        self.create_user("u-fail-marker")
        original_execute = db.Transaction.execute

        def fail_charge_marker(tx, sql, params=()):
            if sql.startswith("UPDATE idempotency_requests SET usage_id="):
                raise RuntimeError("synthetic charge marker failure")
            return original_execute(tx, sql, params)

        with mock.patch.object(db.Transaction, "execute", new=fail_charge_marker):
            with self.assertRaisesRegex(RuntimeError, "charge marker failure"):
                self.admit("u-fail-marker", "fail-marker-key")
        self.assert_no_admission_writes()

    def test_legacy_idempotency_row_is_rejected_without_backfill_and_legacy_stays_zero_job(self):
        self.create_user("u-legacy-unlinked")
        legacy = idempotency.claim_and_charge(
            user_id="u-legacy-unlinked",
            operation="analyze",
            request_id="legacy-key",
            payload=self.payload(),
        )
        self.assertEqual(legacy["state"], "owner")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"], 0)
        self.assertIsNotNone(billing._ACTIVE_USAGE_ID.get())

        billing.clear_active_usage()
        rejected = self.admit("u-legacy-unlinked", "legacy-key")
        self.assertEqual(rejected, {"state": "legacy_unlinked"})
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"], 0)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operation_admissions")["c"],
            0,
        )
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)
        self.assertIsNone(billing._ACTIVE_USAGE_ID.get())

    def test_subject_and_request_are_domain_separated_digests_and_raw_values_are_absent(self):
        user_id = "u-private-subject"
        raw_key = "raw-private-request-key"
        raw_body = "raw-private-body https://secret.invalid prompt reasoning"
        self.create_user(user_id)
        admitted = self.admit(
            user_id,
            raw_key,
            payload={"body": raw_body},
        )

        operation = dict(
            db.fetchone(
                "SELECT * FROM ai_operations WHERE id=?",
                (admitted["operation_id"],),
            )
        )
        link = dict(
            db.fetchone(
                "SELECT * FROM ai_operation_admissions WHERE operation_id=?",
                (admitted["operation_id"],),
            )
        )
        serialized = json.dumps({"operation": operation, "link": link})
        expected_subject = hashlib.sha256(
            f"noteai:ai-operation:subject:v1\0{user_id}".encode("utf-8")
        ).hexdigest()
        self.assertEqual(operation["subject_hash"], expected_subject)
        self.assertEqual(
            operation["request_hash"],
            idempotency.payload_hash({"body": raw_body}),
        )
        for raw_value in (user_id, raw_key, raw_body, "secret.invalid"):
            self.assertNotIn(raw_value, serialized)
        self.assertEqual(operation["provider_attempt_count"], 0)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_provider_attempts")["c"],
            0,
        )

    def test_owner_scoped_reader_has_fixed_allowlist_and_hides_existence(self):
        self.create_user("u-owner")
        self.create_user("u-other")
        admitted = self.admit("u-owner", "owner-read-key")

        owned = idempotency.get_admitted_operation_for_user(
            "u-owner", admitted["operation_id"]
        )
        self.assertIsNotNone(owned)
        self.assertEqual(owned["operation_id"], admitted["operation_id"])
        self.assertEqual(
            set(owned),
            {
                "operation_id",
                "operation_kind",
                "status",
                "provider_phase",
                "priority",
                "available_at",
                "claim_count",
                "provider_attempt_count",
                "event_sequence",
                "result_count",
                "created_at",
                "updated_at",
                "started_at",
                "terminal_at",
            },
        )
        forbidden = {
            "subject_hash",
            "request_hash",
            "lease_owner_hash",
            "lease_expires_at",
            "idempotency_request_id",
            "user_id",
            "key_hash",
            "payload_hash",
            "usage_id",
        }
        self.assertFalse(forbidden & set(owned))
        self.assertIsNone(
            idempotency.get_admitted_operation_for_user(
                "u-other", admitted["operation_id"]
            )
        )
        self.assertIsNone(
            idempotency.get_admitted_operation_for_user(
                "u-other", "00000000-0000-0000-0000-000000000000"
            )
        )
        self.assertIsNone(
            idempotency.get_admitted_operation_for_user("u-other", "not-a-uuid")
        )

    def test_one_hundred_distinct_admissions_persist_without_provider_attempts(self):
        user_id = "u-one-hundred"
        self.create_user(user_id)
        billing.get_subscription(user_id)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 "
            "WHERE user_id=? AND is_active=1",
            (user_id,),
        )
        db.execute(
            "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
            "VALUES(?,1000,1000,0,?)",
            (user_id, "2026-07-14T00:00:00+00:00"),
        )

        results = [
            self.admit(
                user_id,
                f"distinct-key-{index}",
                payload=self.payload(str(index)),
                operation="chat_rewrite",
            )
            for index in range(100)
        ]

        self.assertTrue(all(result["state"] == "admitted" for result in results))
        for table in (
            "idempotency_requests",
            "ai_operations",
            "ai_operation_events",
            "ai_operation_admissions",
            "usage_records",
        ):
            self.assertEqual(
                db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")["c"],
                100,
                table,
            )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_provider_attempts")["c"],
            0,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT SUM(provider_attempt_count) AS c FROM ai_operations"
            )["c"],
            0,
        )
        self.assertEqual(
            db.fetchone("SELECT SUM(model_calls) AS c FROM usage_records")["c"],
            0,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM model_usage_records")["c"],
            0,
        )
        self.assertIsNone(billing._ACTIVE_USAGE_ID.get())


if __name__ == "__main__":
    unittest.main()
