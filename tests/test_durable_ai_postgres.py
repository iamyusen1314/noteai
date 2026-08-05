"""Disposable PostgreSQL proof for the durable AI migration and RLS contract.

Skipped unless both environment variables are present. The target must be an
approved disposable database; this module creates synthetic NOLOGIN roles and
data, performs no provider call, and never connects to production.
"""

import hashlib
import importlib
import inspect
import os
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
ai_operations = importlib.import_module("ai_operations")
durable_ai = importlib.import_module("durable_ai")
billing = importlib.import_module("billing")


class DurableAiPostgresWakeupSourceTests(unittest.TestCase):
    def test_api_role_cleanup_locks_only_mutable_join_aliases(self):
        deletion_source = inspect.getsource(
            durable_ai.settle_unstarted_user_jobs_for_deletion_with_storage
        )
        payload_source = inspect.getsource(durable_ai.delete_user_payloads)

        self.assertIn('FOR UPDATE OF o,s,i', deletion_source)
        self.assertIn('FOR UPDATE OF r,i', payload_source)
        self.assertNotIn('FOR UPDATE OF a', deletion_source)
        self.assertNotIn('FOR UPDATE OF a', payload_source)

    def test_0017_is_in_the_authoritative_migration_set(self):
        migration_path = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0017_durable_ai_postgres_wakeup.sql"
        )
        self.assertTrue(migration_path.is_file())
        self.assertIn(
            migration_path,
            tuple(sorted(db._POSTGRES_MIGRATIONS_DIR.glob("*.sql"))),
        )
        source = migration_path.read_text(encoding="utf-8")
        normalized = " ".join(source.split())
        self.assertIn(
            "CREATE INDEX IF NOT EXISTS idx_ai_operation_outbox_delivered_claim ",
            normalized,
        )
        self.assertIn("WHERE state = 'delivered'", normalized)
        self.assertIn(
            "CREATE POLICY noteai_ai_outbox_worker_delivered_v1",
            normalized,
        )
        self.assertIn("current_user = 'noteai_ai_worker'", normalized)
        self.assertIn("AND state = 'delivered'", normalized)
        self.assertIn(
            "IF EXISTS ( SELECT 1 FROM pg_roles "
            "WHERE rolname = 'noteai_ai_worker' )",
            normalized,
        )
        for grant in (
            "GRANT SELECT(id, operation_id, state, delivered_at)",
            "GRANT SELECT(id, user_id, period_start, used_monthly_credits)",
            "GRANT SELECT(user_id, balance, total_used)",
            "GRANT SELECT(id, user_id)",
        ):
            self.assertIn(grant, normalized)

    def test_0017_incremental_acl_is_worker_read_only_for_delivered_outbox(self):
        historical_acl_path = (
            ROOT
            / "scripts"
            / "postgres"
            / "noteai_production_runtime_roles.sql"
        )
        self.assertEqual(
            hashlib.sha256(historical_acl_path.read_bytes()).hexdigest(),
            "b5fc9e7074c09b0ca26368049225873a6b342b810a17aab48ec7b89278a672d7",
        )
        acl_path = (
            ROOT
            / "scripts"
            / "postgres"
            / "noteai_production_runtime_roles_0017.sql"
        )
        worker_acl = acl_path.read_text(encoding="utf-8")
        self.assertIn(
            "GRANT SELECT(id, operation_id, state, delivered_at)\n"
            "    ON ai_operation_outbox TO noteai_ai_worker;",
            worker_acl,
        )
        self.assertNotIn(
            "UPDATE(state, available_at, attempt_count, lease_owner_hash",
            worker_acl,
        )
        self.assertNotIn(
            "ON ai_operation_outbox TO noteai_ai_worker;\nGRANT UPDATE",
            worker_acl,
        )
        executable_acl = "\n".join(
            line for line in worker_acl.splitlines()
            if not line.lstrip().startswith("--")
        )
        self.assertNotRegex(
            executable_acl,
            r"(?i)\b(?:LOGIN|PASSWORD|ALTER ROLE)\b",
        )


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
        cls.owner_database_url = os.environ["DATABASE_URL"]
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
        cls.conn.execute(
            "GRANT SELECT ON ai_operations,ai_operation_events,"
            "ai_provider_attempts,ai_operation_admissions,"
            "idempotency_requests TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT INSERT ON ai_operation_events,ai_provider_attempts "
            "TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(status,provider_phase,lease_owner_hash,lease_fence,"
            "lease_expires_at,heartbeat_at,claim_count,provider_attempt_count,"
            "event_sequence,result_hash,result_count,updated_at,started_at,"
            "terminal_at) ON ai_operations TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(status,refund_applied,failure_code,refunded_at,"
            "failed_at,complete_applied,completed_at,updated_at) "
            "ON idempotency_requests TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT SELECT(id,deletion_requested_at) ON users "
            "TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(used_monthly_credits) ON subscriptions "
            "TO noteai_ai_worker"
        )
        cls.conn.execute("GRANT INSERT ON credits TO noteai_ai_worker")
        cls.conn.execute(
            "GRANT UPDATE(balance,total_used,updated_at) ON credits "
            "TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT INSERT ON credit_transactions TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(source,credits_used) ON usage_records "
            "TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT SELECT ON payment_credit_positions,"
            "payment_credit_consumptions TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(remaining_milli,state,updated_at) "
            "ON payment_credit_positions TO noteai_ai_worker"
        )
        cls.conn.execute(
            "GRANT UPDATE(state,updated_at) ON payment_credit_consumptions "
            "TO noteai_ai_worker"
        )
        cls.conn.execute(
            (
                ROOT
                / "scripts"
                / "postgres"
                / "noteai_production_runtime_roles_0017.sql"
            ).read_text(encoding="utf-8")
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

    def _role_database_url(self, role: str) -> str:
        settings = psycopg.conninfo.conninfo_to_dict(self.owner_database_url)
        existing = str(settings.get("options") or "").strip()
        settings["options"] = f"{existing} -c role={role}".strip()
        return psycopg.conninfo.make_conninfo(**settings)

    @contextmanager
    def _database_role(self, role: str):
        previous = os.environ["DATABASE_URL"]
        os.environ["DATABASE_URL"] = self._role_database_url(role)
        try:
            yield
        finally:
            os.environ["DATABASE_URL"] = previous

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

    def _committed_outbox_fixture(
        self,
        label: str,
        *,
        state: str,
    ) -> dict[str, str]:
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, label))
        outbox_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{label}:outbox"))
        reference_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{label}:request"))
        digest = hashlib.sha256(label.encode()).hexdigest()
        delivered_at = self.clock if state == "delivered" else None
        with psycopg.connect(
            self.owner_database_url,
            row_factory=dict_row,
        ) as connection:
            connection.execute(
                "INSERT INTO ai_operations("
                "id,subject_hash,request_hash,operation_kind,status,"
                "provider_phase,priority,available_at,created_at,updated_at) "
                "VALUES(%s,%s,%s,'analyze','queued','not_started',0,%s,%s,%s)",
                (
                    operation_id,
                    digest,
                    digest,
                    self.clock,
                    self.clock,
                    self.clock,
                ),
            )
            connection.execute(
                "INSERT INTO ai_payload_refs("
                "id,operation_id,subject_hash,purpose,object_key_hash,"
                "content_sha256,size_bytes,item_count,schema_version,"
                "encryption_mode,key_epoch_hash,state,expires_at,created_at,"
                "ready_at,deleted_at) "
                "VALUES(%s,%s,%s,'request',%s,%s,100,1,1,"
                "'provider_managed',%s,'ready',%s,%s,%s,NULL)",
                (
                    reference_id,
                    operation_id,
                    digest,
                    hashlib.sha256(f"{label}:object".encode()).hexdigest(),
                    hashlib.sha256(f"{label}:content".encode()).hexdigest(),
                    hashlib.sha256(b"key-epoch").hexdigest(),
                    self.expiry,
                    self.clock,
                    self.clock,
                ),
            )
            connection.execute(
                "INSERT INTO ai_operation_outbox("
                "id,operation_id,event_type,state,available_at,created_at,"
                "updated_at,delivered_at) "
                "VALUES(%s,%s,'operation_ready',%s,%s,%s,%s,%s)",
                (
                    outbox_id,
                    operation_id,
                    state,
                    self.clock,
                    self.clock,
                    self.clock,
                    delivered_at,
                ),
            )
            connection.execute(
                "INSERT INTO ai_operation_settlements("
                "operation_id,request_ref_id,billing_state,failure_code,"
                "created_at,updated_at) "
                "VALUES(%s,%s,'charged','',%s,%s)",
                (operation_id, reference_id, self.clock, self.clock),
            )
        return {
            "operation_id": operation_id,
            "outbox_id": outbox_id,
            "reference_id": reference_id,
        }

    def _delete_committed_fixture(self, fixture: dict[str, str]) -> None:
        operation_id = fixture["operation_id"]
        with psycopg.connect(self.owner_database_url) as connection:
            for statement in (
                "DELETE FROM ai_provider_attempts WHERE operation_id=%s",
                "DELETE FROM ai_operation_events WHERE operation_id=%s",
                "DELETE FROM ai_operation_settlements WHERE operation_id=%s",
                "DELETE FROM ai_operation_outbox WHERE operation_id=%s",
                "DELETE FROM ai_payload_refs WHERE operation_id=%s",
                "DELETE FROM ai_operations WHERE id=%s",
            ):
                connection.execute(statement, (operation_id,))

    def test_apply_twice_sha_ledger_and_schema(self):
        self.assertIn("0012_durable_ai_execution_contract.sql", self.first_apply)
        self.assertIn("0017_durable_ai_postgres_wakeup.sql", self.first_apply)
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
        migration_0017 = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0017_durable_ai_postgres_wakeup.sql"
        )
        row_0017 = self.conn.execute(
            "SELECT sha256 FROM schema_migrations WHERE version=%s",
            (migration_0017.name,),
        ).fetchone()
        self.assertEqual(
            row_0017["sha256"],
            hashlib.sha256(migration_0017.read_bytes()).hexdigest(),
        )
        index_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM pg_indexes "
            "WHERE schemaname='public' "
            "AND indexname='idx_ai_operation_outbox_delivered_claim'"
        ).fetchone()["count"]
        policy_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM pg_policies "
            "WHERE schemaname='public' AND tablename='ai_operation_outbox' "
            "AND policyname='noteai_ai_outbox_worker_delivered_v1'"
        ).fetchone()["count"]
        self.assertEqual(index_count, 1)
        self.assertEqual(policy_count, 1)

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

    def test_worker_rls_sees_only_delivered_outbox_and_cannot_mutate(self):
        pending = self._committed_outbox_fixture(
            f"pg-rls-pending-{uuid.uuid4()}",
            state="pending",
        )
        delivered = self._committed_outbox_fixture(
            f"pg-rls-delivered-{uuid.uuid4()}",
            state="delivered",
        )
        try:
            with psycopg.connect(
                self._role_database_url("noteai_ai_worker"),
                row_factory=dict_row,
            ) as worker:
                rows = worker.execute(
                    "SELECT id,state FROM ai_operation_outbox "
                    "WHERE id IN (%s,%s) ORDER BY id",
                    (pending["outbox_id"], delivered["outbox_id"]),
                ).fetchall()
                self.assertEqual(
                    [(row["id"], row["state"]) for row in rows],
                    [(delivered["outbox_id"], "delivered")],
                )
                worker.rollback()
                with self.assertRaises(psycopg.Error):
                    worker.execute(
                        "UPDATE ai_operation_outbox SET state='dead' "
                        "WHERE id=%s",
                        (delivered["outbox_id"],),
                    )
                worker.rollback()
        finally:
            self._delete_committed_fixture(pending)
            self._delete_committed_fixture(delivered)

    def test_two_postgres_workers_have_one_delivered_claim_winner(self):
        fixture = self._committed_outbox_fixture(
            f"pg-two-worker-{uuid.uuid4()}",
            state="delivered",
        )
        now = datetime.fromisoformat(self.clock) + timedelta(seconds=1)
        try:
            with self._database_role("noteai_ai_worker"):
                def claim(index: int):
                    return durable_ai.claim_delivered_operation(
                        fixture["operation_id"],
                        lease_seconds=30,
                        owner_token=f"postgres-worker-owner-{index:02d}",
                        now=now,
                    )

                with ThreadPoolExecutor(max_workers=2) as executor:
                    leases = list(executor.map(claim, range(2)))
            winners = [lease for lease in leases if lease is not None]
            self.assertEqual(len(winners), 1)
            self.assertEqual(winners[0].fence, 1)
            with psycopg.connect(
                self.owner_database_url,
                row_factory=dict_row,
            ) as connection:
                operation = connection.execute(
                    "SELECT claim_count,lease_fence FROM ai_operations "
                    "WHERE id=%s",
                    (fixture["operation_id"],),
                ).fetchone()
                claimed_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM ai_operation_events "
                    "WHERE operation_id=%s AND event_type='claimed'",
                    (fixture["operation_id"],),
                ).fetchone()["count"]
            self.assertEqual(operation["claim_count"], 1)
            self.assertEqual(operation["lease_fence"], 1)
            self.assertEqual(claimed_count, 1)
        finally:
            self._delete_committed_fixture(fixture)

    def test_delivery_and_notify_commit_and_rollback_together(self):
        fixture = self._committed_outbox_fixture(
            f"pg-notify-{uuid.uuid4()}",
            state="pending",
        )
        now = datetime.fromisoformat(self.clock) + timedelta(seconds=1)

        class RollbackProbe(RuntimeError):
            pass

        listener = psycopg.connect(self.owner_database_url, autocommit=True)
        listener.execute(f"LISTEN {durable_ai.DURABLE_AI_NOTIFY_CHANNEL}")
        try:
            with self._database_role("noteai_ai_dispatcher"):
                lease = durable_ai.claim_outbox(
                    owner_token="postgres-notify-dispatcher-owner",
                    now=now,
                )
                self.assertEqual(lease.operation_id, fixture["operation_id"])
                with self.assertRaises(RollbackProbe):
                    with db.transaction(write=True) as tx:
                        self.assertTrue(
                            durable_ai._mark_outbox_delivered_in_transaction(
                                tx,
                                lease,
                                now_iso=(now + timedelta(seconds=1)).isoformat(),
                                notify=True,
                            )
                        )
                        raise RollbackProbe()
                self.assertEqual(
                    list(listener.notifies(timeout=0.2, stop_after=1)),
                    [],
                )
                with psycopg.connect(
                    self.owner_database_url,
                    row_factory=dict_row,
                ) as owner:
                    state = owner.execute(
                        "SELECT state FROM ai_operation_outbox WHERE id=%s",
                        (fixture["outbox_id"],),
                    ).fetchone()["state"]
                self.assertEqual(state, "pending")
                self.assertTrue(
                    durable_ai.mark_outbox_delivered_and_notify(
                        lease,
                        now=now + timedelta(seconds=2),
                    )
                )
            notifications = list(
                listener.notifies(timeout=2.0, stop_after=1)
            )
            self.assertEqual(len(notifications), 1)
            self.assertEqual(
                notifications[0].channel,
                durable_ai.DURABLE_AI_NOTIFY_CHANNEL,
            )
            self.assertEqual(
                notifications[0].payload,
                fixture["operation_id"],
            )
        finally:
            listener.close()
            self._delete_committed_fixture(fixture)

    def test_exact_dispatcher_skips_an_earlier_unrelated_pending_row(self):
        earlier = self._committed_outbox_fixture(
            f"pg-exact-earlier-{uuid.uuid4()}",
            state="pending",
        )
        target = self._committed_outbox_fixture(
            f"pg-exact-target-{uuid.uuid4()}",
            state="pending",
        )
        now = datetime.fromisoformat(self.clock) + timedelta(seconds=1)
        try:
            with self._database_role("noteai_ai_dispatcher"):
                lease = durable_ai.claim_outbox(
                    operation_id=target["operation_id"],
                    owner_token="postgres-exact-dispatcher-owner",
                    now=now,
                )
                self.assertIsNotNone(lease)
                self.assertEqual(lease.operation_id, target["operation_id"])
                self.assertTrue(
                    durable_ai.mark_outbox_delivered(
                        lease,
                        now=now + timedelta(seconds=1),
                    )
                )
            with psycopg.connect(
                self.owner_database_url,
                row_factory=dict_row,
            ) as connection:
                rows = {
                    row["operation_id"]: row
                    for row in connection.execute(
                        "SELECT operation_id,state,attempt_count,"
                        "lease_owner_hash FROM ai_operation_outbox "
                        "WHERE id IN (%s,%s)",
                        (earlier["outbox_id"], target["outbox_id"]),
                    ).fetchall()
                }
            self.assertEqual(rows[earlier["operation_id"]]["state"], "pending")
            self.assertEqual(
                rows[earlier["operation_id"]]["attempt_count"],
                0,
            )
            self.assertIsNone(
                rows[earlier["operation_id"]]["lease_owner_hash"]
            )
            self.assertEqual(rows[target["operation_id"]]["state"], "delivered")
            self.assertEqual(rows[target["operation_id"]]["attempt_count"], 1)
        finally:
            self._delete_committed_fixture(earlier)
            self._delete_committed_fixture(target)

    def test_worker_role_refunds_without_users_or_admissions_update(self):
        user_id = f"pg-worker-refund-{uuid.uuid4()}"
        now = datetime.now(timezone.utc).replace(microsecond=123456)
        store = durable_ai.InMemoryPayloadStore()
        with psycopg.connect(self.owner_database_url) as owner:
            owner.execute(
                "INSERT INTO users("
                "id,username,email,password_hash,password_salt,created_at) "
                "VALUES(%s,%s,%s,'hash','salt',%s)",
                (user_id, user_id, f"{user_id}@example.invalid", now.isoformat()),
            )
        durable_ai.configure_payload_store(store)
        billing.clear_active_usage()
        admitted = None
        try:
            billing.get_subscription(user_id)
            before = db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions "
                "WHERE user_id=? AND is_active=1",
                (user_id,),
            )["used_monthly_credits"]
            admitted = durable_ai.admit_job(
                user_id=user_id,
                operation="analyze",
                request_id=f"pg-refund-{uuid.uuid4()}",
                payload={"acceptance": "durable-ai-v1"},
                now=now,
                store=store,
            )
            charged = db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions "
                "WHERE user_id=? AND is_active=1",
                (user_id,),
            )["used_monthly_credits"]
            self.assertGreater(float(charged), float(before))

            with self._database_role("noteai_ai_dispatcher"):
                outbox_lease = durable_ai.claim_outbox(
                    owner_token="postgres-refund-dispatch-owner",
                    now=now + timedelta(seconds=1),
                )
                self.assertEqual(
                    outbox_lease.operation_id,
                    admitted["operation_id"],
                )
                self.assertTrue(
                    durable_ai.mark_outbox_delivered(
                        outbox_lease,
                        now=now + timedelta(seconds=2),
                    )
                )

            with self._database_role("noteai_ai_worker"):
                self.assertFalse(
                    durable_ai.database_role_matches("noteai_ai_worker")
                )
                lease = durable_ai.claim_delivered_operation(
                    admitted["operation_id"],
                    lease_seconds=15,
                    owner_token="postgres-refund-worker-owner",
                    now=now + timedelta(seconds=3),
                )
                self.assertIsNotNone(lease)
                self.assertTrue(
                    durable_ai.settle_failure(
                        lease,
                        failure_code="worker_failed",
                        now=now + timedelta(seconds=4),
                    )
                )

            operation = db.fetchone(
                "SELECT status,claim_count FROM ai_operations WHERE id=?",
                (admitted["operation_id"],),
            )
            settlement = db.fetchone(
                "SELECT billing_state,failure_code "
                "FROM ai_operation_settlements WHERE operation_id=?",
                (admitted["operation_id"],),
            )
            after = db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions "
                "WHERE user_id=? AND is_active=1",
                (user_id,),
            )["used_monthly_credits"]
            self.assertEqual(operation["status"], "failed")
            self.assertEqual(operation["claim_count"], 1)
            self.assertEqual(settlement["billing_state"], "refunded")
            self.assertEqual(settlement["failure_code"], "worker_failed")
            self.assertEqual(float(after), float(before))
        finally:
            billing.clear_active_usage()
            durable_ai.reset_payload_store()
            with psycopg.connect(self.owner_database_url) as owner:
                if admitted is not None:
                    operation_id = admitted["operation_id"]
                    owner.execute(
                        "DELETE FROM ai_provider_attempts WHERE operation_id=%s",
                        (operation_id,),
                    )
                    owner.execute(
                        "DELETE FROM ai_operation_events WHERE operation_id=%s",
                        (operation_id,),
                    )
                    owner.execute(
                        "DELETE FROM ai_operation_settlements WHERE operation_id=%s",
                        (operation_id,),
                    )
                    owner.execute(
                        "DELETE FROM ai_operation_outbox WHERE operation_id=%s",
                        (operation_id,),
                    )
                    owner.execute(
                        "DELETE FROM ai_payload_refs WHERE operation_id=%s",
                        (operation_id,),
                    )
                    owner.execute(
                        "DELETE FROM ai_operation_admissions WHERE operation_id=%s",
                        (operation_id,),
                    )
                    owner.execute(
                        "DELETE FROM ai_operations WHERE id=%s",
                        (operation_id,),
                    )
                owner.execute(
                    "DELETE FROM model_usage_records WHERE usage_record_id IN "
                    "(SELECT id FROM usage_records WHERE user_id=%s)",
                    (user_id,),
                )
                owner.execute("DELETE FROM usage_records WHERE user_id=%s", (user_id,))
                owner.execute(
                    "DELETE FROM idempotency_requests WHERE user_id=%s",
                    (user_id,),
                )
                owner.execute(
                    "DELETE FROM credit_transactions WHERE user_id=%s",
                    (user_id,),
                )
                owner.execute("DELETE FROM credits WHERE user_id=%s", (user_id,))
                owner.execute(
                    "DELETE FROM subscriptions WHERE user_id=%s",
                    (user_id,),
                )
                owner.execute("DELETE FROM users WHERE id=%s", (user_id,))

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
