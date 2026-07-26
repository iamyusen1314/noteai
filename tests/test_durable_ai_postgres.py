"""Disposable PostgreSQL proof for the durable AI migration and RLS contract.

Skipped unless both environment variables are present. The target must be an
approved disposable database; this module creates synthetic NOLOGIN roles and
data, performs no provider call, and never connects to production.
"""

import hashlib
import importlib
import os
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")


@unittest.skipUnless(
    os.environ.get("NOTEAI_RUN_DURABLE_AI_POSTGRES_TEST") == "1"
    and os.environ.get("NOTEAI_TEST_POSTGRES_URL", "").strip(),
    "approved disposable PostgreSQL durable AI database is not configured",
)
class DurableAiPostgresContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        cls.first_apply = db.apply_postgres_migrations()
        cls.second_apply = db.apply_postgres_migrations()
        cls.conn = db.get_conn()
        for role in (
            "noteai_app",
            "noteai_ai_dispatcher",
            "noteai_ai_worker",
        ):
            cls.conn.execute(f"DROP ROLE IF EXISTS {role}")
            cls.conn.execute(
                f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            cls.conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cls.conn.execute(
            "GRANT SELECT,INSERT ON ai_payload_refs TO noteai_app"
        )
        cls.conn.execute(
            "GRANT UPDATE(state,deleted_at) ON ai_payload_refs TO noteai_app"
        )
        cls.conn.execute("GRANT INSERT ON ai_operation_outbox TO noteai_app")
        cls.conn.execute(
            "GRANT SELECT(id,operation_id,state) "
            "ON ai_operation_outbox TO noteai_app"
        )
        cls.conn.execute(
            "GRANT UPDATE(state,updated_at) ON ai_operation_outbox TO noteai_app"
        )
        cls.conn.execute(
            "GRANT SELECT,INSERT ON ai_operation_settlements TO noteai_app"
        )
        cls.conn.execute(
            "GRANT UPDATE(billing_state,failure_code,updated_at,settled_at) "
            "ON ai_operation_settlements TO noteai_app"
        )

        cls.conn.execute(
            "GRANT SELECT ON ai_operation_outbox,ai_dispatch_state "
            "TO noteai_ai_dispatcher"
        )
        cls.conn.execute(
            "GRANT SELECT(id,priority) ON ai_operations TO noteai_ai_dispatcher"
        )
        cls.conn.execute(
            "GRANT UPDATE(state,available_at,attempt_count,lease_owner_hash,"
            "lease_fence,lease_expires_at,updated_at,delivered_at) "
            "ON ai_operation_outbox TO noteai_ai_dispatcher"
        )
        cls.conn.execute(
            "GRANT UPDATE(priority_streak,updated_at) ON ai_dispatch_state "
            "TO noteai_ai_dispatcher"
        )

        cls.conn.execute(
            "GRANT SELECT,INSERT ON ai_payload_refs TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(state,deleted_at) ON ai_payload_refs "
            "TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT SELECT ON ai_operation_settlements TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(result_ref_id,billing_state,failure_code,updated_at,"
            "settled_at) ON ai_operation_settlements TO noteai_ai_worker"
        )
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        for role in (
            "noteai_app",
            "noteai_ai_dispatcher",
            "noteai_ai_worker",
        ):
            cls.conn.execute(f"DROP OWNED BY {role}")
            cls.conn.execute(f"DROP ROLE IF EXISTS {role}")
        cls.conn.commit()
        cls.conn.close()
        if cls.old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.old_database_url

    def setUp(self):
        self.conn.execute("BEGIN")
        self.clock = "2026-07-26T12:00:00+00:00"
        self.expiry = "2026-08-02T12:00:00+00:00"

    def tearDown(self):
        self.conn.rollback()

    def _operation(self, label: str) -> str:
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, label))
        digest = hashlib.sha256(label.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO ai_operations("
            "id,subject_hash,request_hash,operation_kind,status,provider_phase,"
            "priority,available_at,created_at,updated_at) "
            "VALUES(%s,%s,%s,'analyze','queued','not_started',0,%s,%s,%s)",
            (operation_id, digest, digest, self.clock, self.clock, self.clock),
        )
        return operation_id

    def _ref_values(self, operation_id: str, purpose: str):
        reference_id = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"{operation_id}:{purpose}")
        )
        digest = hashlib.sha256(f"{operation_id}:{purpose}".encode()).hexdigest()
        return (
            reference_id,
            operation_id,
            digest,
            purpose,
            hashlib.sha256(f"object:{digest}".encode()).hexdigest(),
            hashlib.sha256(f"content:{digest}".encode()).hexdigest(),
            100,
            1,
            1,
            "provider_managed",
            hashlib.sha256(b"key-epoch").hexdigest(),
            "ready",
            self.expiry,
            self.clock,
            self.clock,
            None,
        )

    def _insert_ref_as_owner(self, operation_id: str, purpose: str) -> str:
        values = self._ref_values(operation_id, purpose)
        self.conn.execute(
            "INSERT INTO ai_payload_refs("
            "id,operation_id,subject_hash,purpose,object_key_hash,content_sha256,"
            "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,"
            "state,expires_at,created_at,ready_at,deleted_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            values,
        )
        return values[0]

    def test_apply_twice_sha_ledger_and_schema(self):
        self.assertIn("0012_durable_ai_execution_contract.sql", self.first_apply)
        self.assertEqual(self.second_apply, [])
        migration_path = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0012_durable_ai_execution_contract.sql"
        )
        expected = hashlib.sha256(migration_path.read_bytes()).hexdigest()
        row = self.conn.execute(
            "SELECT sha256 FROM schema_migrations WHERE version=%s",
            ("0012_durable_ai_execution_contract.sql",),
        ).fetchone()
        self.assertEqual(row["sha256"], expected)
        tables = {
            row["table_name"]
            for row in self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            ).fetchall()
        }
        self.assertTrue({
            "ai_payload_refs",
            "ai_operation_outbox",
            "ai_operation_settlements",
            "ai_dispatch_state",
        }.issubset(tables))

    def test_constraints_reject_bad_size_clock_and_state(self):
        operation_id = self._operation("pg-invalid")
        values = list(self._ref_values(operation_id, "request"))
        for index, invalid in (
            (6, 0),
            (6, 134217729),
            (11, "arbitrary"),
            (12, "2026-07-26 12:00:00"),
            (12, "2026-08-03T20:00:00+08:00"),
        ):
            with self.subTest(index=index, invalid=invalid):
                attempted = list(values)
                attempted[0] = str(uuid.uuid4())
                attempted[index] = invalid
                self.conn.execute("SAVEPOINT invalid_ref")
                with self.assertRaises(Exception):
                    self.conn.execute(
                        "INSERT INTO ai_payload_refs("
                        "id,operation_id,subject_hash,purpose,object_key_hash,"
                        "content_sha256,size_bytes,item_count,schema_version,"
                        "encryption_mode,key_epoch_hash,state,expires_at,"
                        "created_at,ready_at,deleted_at) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        attempted,
                    )
                self.conn.execute("ROLLBACK TO SAVEPOINT invalid_ref")

    def test_rls_separates_api_request_and_worker_result_inserts(self):
        api_operation = self._operation("pg-api-ref")
        worker_operation = self._operation("pg-worker-ref")
        denied_operation = self._operation("pg-denied-ref")

        self.conn.execute("SET LOCAL ROLE noteai_app")
        self.conn.execute(
            "INSERT INTO ai_payload_refs("
            "id,operation_id,subject_hash,purpose,object_key_hash,content_sha256,"
            "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,"
            "state,expires_at,created_at,ready_at,deleted_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            self._ref_values(api_operation, "request"),
        )
        self.conn.execute("SAVEPOINT api_result_denied")
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO ai_payload_refs("
                "id,operation_id,subject_hash,purpose,object_key_hash,content_sha256,"
                "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,"
                "state,expires_at,created_at,ready_at,deleted_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                self._ref_values(denied_operation, "result"),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT api_result_denied")

        self.conn.execute("SET LOCAL ROLE noteai_ai_worker")
        self.conn.execute(
            "INSERT INTO ai_payload_refs("
            "id,operation_id,subject_hash,purpose,object_key_hash,content_sha256,"
            "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,"
            "state,expires_at,created_at,ready_at,deleted_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            self._ref_values(worker_operation, "result"),
        )
        self.conn.execute("SAVEPOINT worker_request_denied")
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO ai_payload_refs("
                "id,operation_id,subject_hash,purpose,object_key_hash,content_sha256,"
                "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,"
                "state,expires_at,created_at,ready_at,deleted_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                self._ref_values(denied_operation, "request"),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT worker_request_denied")

    def test_role_attributes_and_negative_new_table_matrix(self):
        attributes = self.conn.execute(
            "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
            "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
            "WHERE rolname IN ('noteai_app','noteai_ai_dispatcher',"
            "'noteai_ai_worker') ORDER BY rolname"
        ).fetchall()
        self.assertEqual(len(attributes), 3)
        for row in attributes:
            self.assertFalse(row["rolsuper"])
            self.assertFalse(row["rolinherit"])
            self.assertFalse(row["rolcreaterole"])
            self.assertFalse(row["rolcreatedb"])
            self.assertFalse(row["rolcanlogin"])
            self.assertFalse(row["rolreplication"])
            self.assertFalse(row["rolbypassrls"])
        for role in (
            "noteai_app",
            "noteai_ai_dispatcher",
            "noteai_ai_worker",
        ):
            self.assertFalse(
                self.conn.execute(
                    "SELECT has_schema_privilege(%s,'public','CREATE') AS allowed",
                    (role,),
                ).fetchone()["allowed"]
            )
            self.assertFalse(
                self.conn.execute(
                    "SELECT has_table_privilege(%s,'schema_migrations','SELECT') "
                    "AS allowed",
                    (role,),
                ).fetchone()["allowed"]
            )
        self.assertFalse(
            self.conn.execute(
                "SELECT has_table_privilege("
                "'noteai_ai_dispatcher','ai_payload_refs','SELECT') AS allowed"
            ).fetchone()["allowed"]
        )
        self.assertFalse(
            self.conn.execute(
                "SELECT has_table_privilege("
                "'noteai_app','ai_operation_outbox','SELECT') AS allowed"
            ).fetchone()["allowed"]
        )
        self.assertFalse(
            self.conn.execute(
                "SELECT has_table_privilege("
                "'noteai_ai_worker','ai_dispatch_state','SELECT') AS allowed"
            ).fetchone()["allowed"]
        )

    def test_api_can_only_cancel_provider_free_contract_rows(self):
        operation_id = self._operation("pg-api-cancel")
        denied_operation = self._operation("pg-api-manual-denied")
        self.conn.execute("SET LOCAL ROLE noteai_app")
        request_ref_id = self._insert_ref_as_owner(operation_id, "request")
        outbox_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO ai_operation_outbox("
            "id,operation_id,event_type,state,available_at,created_at,updated_at) "
            "VALUES(%s,%s,'operation_ready','pending',%s,%s,%s)",
            (outbox_id, operation_id, self.clock, self.clock, self.clock),
        )
        self.conn.execute(
            "INSERT INTO ai_operation_settlements("
            "operation_id,request_ref_id,billing_state,failure_code,"
            "created_at,updated_at) VALUES(%s,%s,'charged','',%s,%s)",
            (operation_id, request_ref_id, self.clock, self.clock),
        )
        self.conn.execute(
            "UPDATE ai_operation_outbox SET state='dead',updated_at=%s "
            "WHERE id=%s",
            (self.clock, outbox_id),
        )
        self.conn.execute(
            "UPDATE ai_operation_settlements SET billing_state='refunded',"
            "failure_code='cancelled',settled_at=%s,updated_at=%s "
            "WHERE operation_id=%s",
            (self.clock, self.clock, operation_id),
        )
        denied_ref_id = self._insert_ref_as_owner(denied_operation, "request")
        self.conn.execute(
            "INSERT INTO ai_operation_settlements("
            "operation_id,request_ref_id,billing_state,failure_code,"
            "created_at,updated_at) VALUES(%s,%s,'charged','',%s,%s)",
            (denied_operation, denied_ref_id, self.clock, self.clock),
        )
        self.conn.execute("SAVEPOINT api_manual_denied")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE ai_operation_settlements SET billing_state='needs_manual',"
                "failure_code='provider_outcome_unknown',settled_at=%s,updated_at=%s "
                "WHERE operation_id=%s",
                (self.clock, self.clock, denied_operation),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT api_manual_denied")


if __name__ == "__main__":
    unittest.main()
