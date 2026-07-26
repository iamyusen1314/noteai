"""Disposable PostgreSQL proof for migration 0014 and payment roles."""

import hashlib
import importlib
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
payment = importlib.import_module("payment_contract")


@unittest.skipUnless(
    os.environ.get("NOTEAI_RUN_PAYMENT_POSTGRES_TEST") == "1"
    and os.environ.get("NOTEAI_TEST_POSTGRES_URL", "").strip(),
    "approved disposable PostgreSQL payment database is not configured",
)
class PaymentPostgresContractTests(unittest.TestCase):
    ROLES = (
        "noteai_app",
        "noteai_payment",
        "noteai_admin",
        "noteai_ai_worker",
        "noteai_ai_dispatcher",
        "noteai_xhs_tracking",
        "noteai_xhs_trends",
    )
    TABLES = (
        "payment_orders",
        "payment_refunds",
        "payment_events",
        "payment_cash_ledger",
        "payment_entitlement_ledger",
        "payment_credit_positions",
        "payment_credit_consumptions",
        "payment_reconciliation_runs",
        "payment_reconciliation_items",
        "payment_settlement_summaries",
    )
    TRIGGER_FUNCTIONS = (
        "noteai_payment_order_identity_guard_v1()",
        "noteai_payment_refund_identity_guard_v1()",
        "noteai_payment_event_identity_guard_v1()",
        "noteai_payment_credit_position_identity_guard_v1()",
        "noteai_payment_credit_position_user_guard_v1()",
        "noteai_payment_credit_consumption_guard_v1()",
        "noteai_payment_refund_insert_guard_v1()",
        "noteai_payment_append_only_guard_v1()",
    )

    @classmethod
    def setUpClass(cls):
        cls.old_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        cls.first_apply = db.apply_postgres_migrations()
        cls.second_apply = db.apply_postgres_migrations()
        cls.conn = db.get_conn()
        for role in cls.ROLES:
            cls.conn.execute(f"DROP ROLE IF EXISTS {role}")
            cls.conn.execute(
                f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            cls.conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        for function in cls.TRIGGER_FUNCTIONS:
            cls.conn.execute(
                f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC"
            )

        cls.conn.execute(
            "GRANT SELECT,INSERT ON payment_orders TO noteai_app"
        )
        cls.conn.execute(
            "GRANT UPDATE("
            "user_id,provider_payment_id,payment_status,updated_at,terminal_at"
            ") ON payment_orders TO noteai_app"
        )
        cls.conn.execute(
            "GRANT SELECT ON payment_credit_positions,"
            "payment_credit_consumptions TO noteai_app"
        )
        cls.conn.execute(
            "GRANT UPDATE(user_id,remaining_milli,state,updated_at) "
            "ON payment_credit_positions TO noteai_app"
        )
        cls.conn.execute(
            "GRANT INSERT ON payment_credit_consumptions TO noteai_app"
        )
        cls.conn.execute(
            "GRANT UPDATE(state,updated_at) "
            "ON payment_credit_consumptions TO noteai_app"
        )

        cls.conn.execute(
            "GRANT SELECT ON "
            + ",".join(cls.TABLES)
            + " TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT UPDATE("
            "provider_payment_id,payment_status,entitlement_status,"
            "entitlement_ref,refund_status,refunded_fen,refund_count,"
            "updated_at,succeeded_at,terminal_at"
            ") ON payment_orders TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT INSERT ON payment_refunds,payment_events,"
            "payment_cash_ledger,payment_entitlement_ledger,"
            "payment_credit_positions,payment_reconciliation_runs,"
            "payment_reconciliation_items,payment_settlement_summaries "
            "TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT UPDATE(provider_refund_id,status,updated_at,terminal_at) "
            "ON payment_refunds TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT UPDATE(processing_state,reason_code,order_id,refund_id,"
            "processed_at) ON payment_events TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT UPDATE(user_id,remaining_milli,state,updated_at) "
            "ON payment_credit_positions TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT SELECT(id,deletion_requested_at) "
            "ON users TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT SELECT(id,user_id,tier,started_at,is_active),INSERT "
            "ON subscriptions TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT UPDATE(is_active) ON subscriptions TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT SELECT(user_id,balance,total_purchased),INSERT "
            "ON credits TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT UPDATE(balance,total_purchased,updated_at) "
            "ON credits TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT INSERT ON credit_transactions TO noteai_payment"
        )
        cls.conn.execute(
            "GRANT SELECT(user_id,recorded_at,credits_used,source) "
            "ON usage_records TO noteai_payment"
        )

        cls.conn.execute(
            "GRANT SELECT ON "
            + ",".join(cls.TABLES)
            + " TO noteai_admin"
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
            "GRANT UPDATE(state,updated_at) "
            "ON payment_credit_consumptions TO noteai_ai_worker"
        )
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        for role in cls.ROLES:
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
        self.user_id = f"pay-user-{uuid.uuid4()}"
        self.conn.execute(
            "INSERT INTO users("
            "id,username,email,password_hash,password_salt,created_at"
            ") VALUES(%s,%s,%s,'hash','salt',%s)",
            (
                self.user_id,
                self.user_id,
                f"{self.user_id}@example.com",
                self.clock,
            ),
        )

    def tearDown(self):
        self.conn.rollback()

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def order_values(self, label: str = "order") -> tuple:
        order_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{label}:{self.user_id}"))
        return (
            order_id,
            self.user_id,
            self.digest(f"subject:{self.user_id}"),
            "credit_package",
            "starter",
            "first-launch-v1-2026-07-26",
            1200,
            "CNY",
            "adapay",
            "mock",
            "NA_" + order_id.replace("-", ""),
            self.digest("app:test"),
            self.digest(f"idempotency:{label}"),
            self.digest(f"request:{label}"),
            "created",
            "pending",
            "none",
            0,
            0,
            self.clock,
            self.clock,
        )

    def insert_order(self, values: tuple | None = None) -> str:
        values = values or self.order_values()
        self.conn.execute(
            "INSERT INTO payment_orders("
            "id,user_id,subject_hash,product_kind,product_id,catalog_version,"
            "amount_fen,currency,provider,provider_mode,merchant_order_no,"
            "app_id_hash,idempotency_key_hash,request_hash,payment_status,"
            "entitlement_status,refund_status,refunded_fen,refund_count,"
            "created_at,updated_at"
            ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s,%s,%s)",
            values,
        )
        return str(values[0])

    def event(
        self,
        order_id: str,
        *,
        label: str = "event",
        state: str = "processed",
    ) -> str:
        event_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{label}:{self.user_id}"))
        self.conn.execute(
            "INSERT INTO payment_events("
            "id,provider_event_id_hash,event_type,payload_sha256,"
            "signature_sha256,app_id_hash,prod_mode,provider_created_at,"
            "processing_state,reason_code,order_id,received_at,processed_at"
            ") VALUES(%s,%s,'payment.succeeded',%s,%s,%s,0,1785052800,"
            "%s,'payment_applied',%s,%s,%s)",
            (
                event_id,
                self.digest(f"provider:{label}:{self.user_id}"),
                self.digest(f"payload:{label}"),
                self.digest(f"signature:{label}"),
                self.digest("app:test"),
                state,
                order_id,
                self.clock,
                self.clock if state != "accepted" else None,
            ),
        )
        return event_id

    def test_apply_twice_sha_ledger_and_schema(self):
        self.assertTrue(
            not self.first_apply
            or "0014_payment_execution_contract.sql" in self.first_apply,
            self.first_apply,
        )
        self.assertEqual(self.second_apply, [])
        migration_path = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0014_payment_execution_contract.sql"
        )
        expected = hashlib.sha256(migration_path.read_bytes()).hexdigest()
        row = self.conn.execute(
            "SELECT sha256 FROM schema_migrations WHERE version=%s",
            ("0014_payment_execution_contract.sql",),
        ).fetchone()
        self.assertEqual(row["sha256"], expected)
        tables = {
            row["table_name"]
            for row in self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            ).fetchall()
        }
        self.assertTrue(set(self.TABLES).issubset(tables))

    def test_persistent_money_refund_transition_and_append_only_guards(self):
        invalid_catalog = list(self.order_values("invalid-catalog"))
        invalid_catalog[6] = 1300
        self.conn.execute("SAVEPOINT invalid_catalog")
        with self.assertRaises(Exception):
            self.insert_order(tuple(invalid_catalog))
        self.conn.execute("ROLLBACK TO SAVEPOINT invalid_catalog")

        order_id = self.insert_order()
        self.conn.execute(
            "UPDATE payment_orders SET provider_payment_id='provider_pay_1',"
            "payment_status='succeeded',entitlement_status='applied',"
            "updated_at=%s,succeeded_at=%s,terminal_at=%s WHERE id=%s",
            (self.clock, self.clock, self.clock, order_id),
        )
        event_id = self.event(order_id)
        cash_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO payment_cash_ledger("
            "id,order_id,entry_type,amount_fen,currency,source_event_id,recorded_at"
            ") VALUES(%s,%s,'payment_received',1200,'CNY',%s,%s)",
            (cash_id, order_id, event_id, self.clock),
        )
        self.conn.execute("SAVEPOINT immutable_cash")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE payment_cash_ledger SET amount_fen=1 WHERE id=%s",
                (cash_id,),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT immutable_cash")

        self.conn.execute("SAVEPOINT duplicate_receipt")
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO payment_cash_ledger("
                "id,order_id,entry_type,amount_fen,currency,source_event_id,"
                "recorded_at) VALUES(%s,%s,'payment_received',1200,'CNY',%s,%s)",
                (
                    str(uuid.uuid4()),
                    order_id,
                    self.event(order_id, label="second-event"),
                    self.clock,
                ),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT duplicate_receipt")

        self.conn.execute("SAVEPOINT duplicate_receipt_variant")
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO payment_cash_ledger("
                "id,order_id,entry_type,amount_fen,currency,source_event_id,"
                "recorded_at) VALUES(%s,%s,'payment_received_unmatched',"
                "1200,'CNY',%s,%s)",
                (
                    str(uuid.uuid4()),
                    order_id,
                    self.event(order_id, label="variant-event"),
                    self.clock,
                ),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT duplicate_receipt_variant")

        self.conn.execute("SAVEPOINT partial_refund")
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO payment_refunds("
                "id,order_id,merchant_refund_no,amount_fen,currency,status,"
                "reason_code,created_at,updated_at"
                ") VALUES(%s,%s,%s,100,'CNY','requested',"
                "'customer_request',%s,%s)",
                (
                    str(uuid.uuid4()),
                    order_id,
                    "NR_partial",
                    self.clock,
                    self.clock,
                ),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT partial_refund")

        self.conn.execute("SAVEPOINT downgrade_success")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE payment_orders SET payment_status='failed' "
                "WHERE id=%s",
                (order_id,),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT downgrade_success")

        self.conn.execute(
            "INSERT INTO payment_credit_positions("
            "order_id,user_id,subject_hash,granted_milli,remaining_milli,state,"
            "created_at,updated_at"
            ") VALUES(%s,%s,%s,30000,24000,'active',%s,%s)",
            (
                order_id,
                self.user_id,
                self.digest(f"subject:{self.user_id}"),
                self.clock,
                self.clock,
            ),
        )
        consumption_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO payment_credit_consumptions("
            "id,order_id,usage_id,amount_milli,state,created_at,updated_at"
            ") VALUES(%s,%s,%s,6000,'consumed',%s,%s)",
            (
                consumption_id,
                order_id,
                f"usage-{uuid.uuid4()}",
                self.clock,
                self.clock,
            ),
        )
        self.conn.execute(
            "UPDATE payment_credit_consumptions SET state='restored' "
            "WHERE id=%s",
            (consumption_id,),
        )
        self.conn.execute("SAVEPOINT consumption_terminal")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE payment_credit_consumptions SET state='consumed' "
                "WHERE id=%s",
                (consumption_id,),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT consumption_terminal")
        self.conn.execute("SAVEPOINT position_repoint")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE payment_credit_positions SET user_id=%s WHERE order_id=%s",
                (f"other-{uuid.uuid4()}", order_id),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT position_repoint")

    def test_rls_exact_positive_and_complete_negative_matrix(self):
        privileges = (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        )
        positive = {
            "noteai_app": {
                "payment_orders": {"SELECT", "INSERT"},
                "payment_credit_positions": {"SELECT"},
                "payment_credit_consumptions": {"SELECT", "INSERT"},
            },
            "noteai_payment": {
                table: {"SELECT"}
                for table in self.TABLES
            },
            "noteai_admin": {
                table: {"SELECT"}
                for table in self.TABLES
            },
            "noteai_ai_worker": {
                "payment_credit_positions": {"SELECT"},
                "payment_credit_consumptions": {"SELECT"},
            },
        }
        for table in (
            "payment_refunds",
            "payment_events",
            "payment_cash_ledger",
            "payment_entitlement_ledger",
            "payment_credit_positions",
            "payment_reconciliation_runs",
            "payment_reconciliation_items",
            "payment_settlement_summaries",
        ):
            positive["noteai_payment"][table].add("INSERT")

        for role in self.ROLES:
            attributes = self.conn.execute(
                "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                "rolcanlogin,rolreplication,rolbypassrls "
                "FROM pg_roles WHERE rolname=%s",
                (role,),
            ).fetchone()
            self.assertFalse(any(attributes.values()))
            self.assertFalse(
                self.conn.execute(
                    "SELECT has_schema_privilege(%s,'public','CREATE') AS allowed",
                    (role,),
                ).fetchone()["allowed"]
            )
            self.assertFalse(
                self.conn.execute(
                    "SELECT has_table_privilege("
                    "%s,'schema_migrations','SELECT') AS allowed",
                    (role,),
                ).fetchone()["allowed"]
            )
            for table in self.TABLES:
                for privilege in privileges:
                    expected = privilege in positive.get(role, {}).get(
                        table,
                        set(),
                    )
                    actual = self.conn.execute(
                        "SELECT has_table_privilege(%s,%s,%s) AS allowed",
                        (role, table, privilege),
                    ).fetchone()["allowed"]
                    self.assertEqual(
                        actual,
                        expected,
                        (role, table, privilege),
                    )

        column_updates = {
            ("noteai_app", "payment_orders"): {
                "user_id",
                "provider_payment_id",
                "payment_status",
                "updated_at",
                "terminal_at",
            },
            ("noteai_app", "payment_credit_positions"): {
                "user_id",
                "remaining_milli",
                "state",
                "updated_at",
            },
            ("noteai_app", "payment_credit_consumptions"): {
                "state",
                "updated_at",
            },
            ("noteai_ai_worker", "payment_credit_positions"): {
                "remaining_milli",
                "state",
                "updated_at",
            },
            ("noteai_ai_worker", "payment_credit_consumptions"): {
                "state",
                "updated_at",
            },
            ("noteai_payment", "subscriptions"): {"is_active"},
            ("noteai_payment", "credits"): {
                "balance",
                "total_purchased",
                "updated_at",
            },
        }
        for (role, table), expected_columns in column_updates.items():
            columns = [
                row["column_name"]
                for row in self.conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (table,),
                ).fetchall()
            ]
            for column in columns:
                actual = self.conn.execute(
                    "SELECT has_column_privilege(%s,%s,%s,'UPDATE') AS allowed",
                    (role, table, column),
                ).fetchone()["allowed"]
                self.assertEqual(
                    actual,
                    column in expected_columns,
                    (role, table, column),
                )

        payment_existing_table_privileges = {
            "subscriptions": {"INSERT"},
            "credits": {"INSERT"},
            "credit_transactions": {"INSERT"},
        }
        all_tables = [
            row["table_name"]
            for row in self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            ).fetchall()
        ]
        for table in all_tables:
            if table in self.TABLES:
                expected = positive["noteai_payment"][table]
            else:
                expected = payment_existing_table_privileges.get(table, set())
            for privilege in privileges:
                actual = self.conn.execute(
                    "SELECT has_table_privilege("
                    "'noteai_payment',%s,%s) AS allowed",
                    (table, privilege),
                ).fetchone()["allowed"]
                self.assertEqual(
                    actual,
                    privilege in expected,
                    ("noteai_payment", table, privilege),
                )

        selected_columns = {
            "users": {"id", "deletion_requested_at"},
            "subscriptions": {
                "id",
                "user_id",
                "tier",
                "started_at",
                "is_active",
            },
            "credits": {"user_id", "balance", "total_purchased"},
            "usage_records": {
                "user_id",
                "recorded_at",
                "credits_used",
                "source",
            },
        }
        for table, expected_columns in selected_columns.items():
            columns = [
                row["column_name"]
                for row in self.conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (table,),
                ).fetchall()
            ]
            for column in columns:
                actual = self.conn.execute(
                    "SELECT has_column_privilege("
                    "'noteai_payment',%s,%s,'SELECT') AS allowed",
                    (table, column),
                ).fetchone()["allowed"]
                self.assertEqual(
                    actual,
                    column in expected_columns,
                    ("noteai_payment", table, column, "SELECT"),
                )

        sequences = [
            row["sequence_name"]
            for row in self.conn.execute(
                "SELECT sequence_name FROM information_schema.sequences "
                "WHERE sequence_schema='public'"
            ).fetchall()
        ]
        for sequence in sequences:
            for privilege in ("USAGE", "SELECT", "UPDATE"):
                self.assertFalse(
                    self.conn.execute(
                        "SELECT has_sequence_privilege("
                        "'noteai_payment',%s,%s) AS allowed",
                        (sequence, privilege),
                    ).fetchone()["allowed"],
                    (sequence, privilege),
                )

        for role in self.ROLES:
            for function in self.TRIGGER_FUNCTIONS:
                self.assertFalse(
                    self.conn.execute(
                        "SELECT has_function_privilege("
                        "%s,%s,'EXECUTE') AS allowed",
                        (role, f"public.{function}"),
                    ).fetchone()["allowed"],
                    (role, function, "EXECUTE"),
                )
                self.assertFalse(
                    self.conn.execute(
                        "SELECT has_function_privilege("
                        "%s,%s,'EXECUTE WITH GRANT OPTION') AS allowed",
                        (role, f"public.{function}"),
                    ).fetchone()["allowed"],
                    (role, function, "GRANT OPTION"),
                )
        for function in (
            "pg_catalog.hashtext(text)",
            "pg_catalog.pg_advisory_xact_lock(bigint)",
        ):
            self.assertTrue(
                self.conn.execute(
                    "SELECT has_function_privilege("
                    "'noteai_payment',%s,'EXECUTE') AS allowed",
                    (function,),
                ).fetchone()["allowed"],
                function,
            )

    def test_app_payment_admin_and_unrelated_role_behavior(self):
        values = self.order_values("roles")
        self.conn.execute("SET LOCAL ROLE noteai_app")
        order_id = self.insert_order(values)
        invalid_insert = list(self.order_values("app-invalid-state"))
        invalid_insert[14] = "succeeded"
        self.conn.execute("SAVEPOINT app_invalid_insert")
        with self.assertRaises(Exception):
            self.insert_order(tuple(invalid_insert))
        self.conn.execute("ROLLBACK TO SAVEPOINT app_invalid_insert")
        self.conn.execute(
            "UPDATE payment_orders SET provider_payment_id='provider_roles',"
            "payment_status='pending',updated_at=%s WHERE id=%s",
            (self.clock, order_id),
        )
        self.conn.execute("SAVEPOINT app_cannot_repoint_order")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE payment_orders SET user_id=%s WHERE id=%s",
                (f"other-{uuid.uuid4()}", order_id),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT app_cannot_repoint_order")
        self.conn.execute("SAVEPOINT app_cannot_smuggle_on_null")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE payment_orders SET user_id=NULL,"
                "payment_status='succeeded' WHERE id=%s",
                (order_id,),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT app_cannot_smuggle_on_null")
        self.conn.execute("SAVEPOINT app_cannot_succeed")
        with self.assertRaises(Exception):
            self.conn.execute(
                "UPDATE payment_orders SET payment_status='succeeded' "
                "WHERE id=%s",
                (order_id,),
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT app_cannot_succeed")
        self.conn.execute("SAVEPOINT app_cannot_cash")
        with self.assertRaises(Exception):
            self.conn.execute("SELECT * FROM payment_cash_ledger")
        self.conn.execute("ROLLBACK TO SAVEPOINT app_cannot_cash")
        self.conn.execute("RESET ROLE")

        self.conn.execute("SET LOCAL ROLE noteai_payment")
        self.conn.execute(
            "UPDATE payment_orders SET payment_status='succeeded',"
            "entitlement_status='needs_manual',updated_at=%s,"
            "succeeded_at=%s,terminal_at=%s WHERE id=%s",
            (self.clock, self.clock, self.clock, order_id),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT payment_status FROM payment_orders WHERE id=%s",
                (order_id,),
            ).fetchone()["payment_status"],
            "succeeded",
        )
        self.conn.execute("RESET ROLE")

        self.conn.execute("SET LOCAL ROLE noteai_app")
        self.conn.execute(
            "UPDATE payment_orders SET user_id=NULL WHERE id=%s",
            (order_id,),
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT user_id FROM payment_orders WHERE id=%s",
                (order_id,),
            ).fetchone()["user_id"]
        )
        self.conn.execute("RESET ROLE")

        self.conn.execute("SET LOCAL ROLE noteai_admin")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS count FROM payment_orders WHERE id=%s",
                (order_id,),
            ).fetchone()["count"],
            1,
        )
        self.conn.execute("SAVEPOINT admin_insert_denied")
        with self.assertRaises(Exception):
            self.insert_order(self.order_values("admin-denied"))
        self.conn.execute("ROLLBACK TO SAVEPOINT admin_insert_denied")
        self.conn.execute("RESET ROLE")

        self.conn.execute("SET LOCAL ROLE noteai_xhs_trends")
        self.conn.execute("SAVEPOINT unrelated_denied")
        with self.assertRaises(Exception):
            self.conn.execute("SELECT * FROM payment_orders")
        self.conn.execute("ROLLBACK TO SAVEPOINT unrelated_denied")
        self.conn.execute("RESET ROLE")

    def test_payment_role_runs_provider_isolated_full_cash_lifecycle(self):
        now = datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc)
        user_id = f"role-pay-{uuid.uuid4()}"
        app_id = "app_role_test"
        db.execute(
            "INSERT INTO users("
            "id,username,email,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?,?)",
            (
                user_id,
                user_id,
                f"{user_id}@example.com",
                "hash",
                "salt",
                now.isoformat(),
            ),
        )
        billing.get_subscription(user_id)
        order = payment.create_order(
            user_id,
            "credit_package",
            "starter",
            idempotency_key=f"role-{uuid.uuid4()}",
            app_id=app_id,
            prod_mode=False,
            now=now,
        )
        order_row = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        payment_id = f"pay_role_{uuid.uuid4().hex}"
        payment_data = json.dumps(
            {
                "id": f"evt_role_payment_{uuid.uuid4().hex}",
                "type": "payment.succeeded",
                "created_time": int(now.timestamp()),
                "prod_mode": False,
                "app_id": app_id,
                "data": {
                    "id": payment_id,
                    "order_no": order_row["merchant_order_no"],
                    "pay_amt": "12.00",
                },
            },
            separators=(",", ":"),
        )
        base_url = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        role_url = (
            base_url
            + ("&" if "?" in base_url else "?")
            + "options=-c%20role%3Dnoteai_payment"
        )
        os.environ["DATABASE_URL"] = role_url
        try:
            with mock.patch.object(
                payment,
                "verify_adapay_signature",
                return_value=True,
            ):
                paid = payment.process_signed_callback(
                    payment_data,
                    "synthetic-signature",
                    "synthetic-public-key",
                    expected_app_id=app_id,
                    expected_prod_mode=False,
                    now=now,
                )
            self.assertTrue(paid["ok"])
            prepared = payment.prepare_full_refund(
                order["id"],
                reason_code="customer_request",
                now=now + timedelta(minutes=1),
            )
            refund_row = dict(
                db.fetchone(
                    "SELECT * FROM payment_refunds WHERE id=?",
                    (prepared["id"],),
                )
            )
            refund_provider_id = f"refund_role_{uuid.uuid4().hex}"
            self.assertTrue(
                payment.admit_refund_submission(
                    refund_row["id"],
                    now=now + timedelta(minutes=2),
                )
            )
            self.assertFalse(
                payment.admit_refund_submission(
                    refund_row["id"],
                    now=now + timedelta(minutes=2),
                )
            )
            payment.mark_refund_submission(
                refund_row["id"],
                payment.ProviderRefundResult(
                    merchant_refund_no=refund_row["merchant_refund_no"],
                    provider_refund_id=refund_provider_id,
                    status="pending",
                    amount_fen=1200,
                    response_verified=True,
                ),
                now=now + timedelta(minutes=2),
            )
            refund_data = json.dumps(
                {
                    "id": f"evt_role_refund_{uuid.uuid4().hex}",
                    "type": "refund.succeeded",
                    "created_time": int(now.timestamp()),
                    "prod_mode": False,
                    "app_id": app_id,
                    "data": {
                        "id": refund_provider_id,
                        "refund_order_no": refund_row["merchant_refund_no"],
                        "payment_id": payment_id,
                        "refund_amt": "12.00",
                    },
                },
                separators=(",", ":"),
            )
            with mock.patch.object(
                payment,
                "verify_adapay_signature",
                return_value=True,
            ):
                refunded = payment.process_signed_callback(
                    refund_data,
                    "synthetic-signature",
                    "synthetic-public-key",
                    expected_app_id=app_id,
                    expected_prod_mode=False,
                    now=now + timedelta(minutes=3),
                )
            self.assertTrue(refunded["ok"])
        finally:
            os.environ["DATABASE_URL"] = base_url
        final = db.fetchone(
            "SELECT entitlement_status,refund_status,refunded_fen "
            "FROM payment_orders WHERE id=?",
            (order["id"],),
        )
        self.assertEqual(final["entitlement_status"], "reversed")
        self.assertEqual(final["refund_status"], "refunded")
        self.assertEqual(final["refunded_fen"], 1200)
        self.assertEqual(
            db.fetchone(
                "SELECT SUM(amount_fen) AS total FROM payment_cash_ledger "
                "WHERE order_id=?",
                (order["id"],),
            )["total"],
            0,
        )


@unittest.skipUnless(
    os.environ.get("NOTEAI_RUN_PAYMENT_POSTGRES_TEST") == "1"
    and os.environ.get("NOTEAI_TEST_POSTGRES_URL", "").strip(),
    "approved disposable PostgreSQL payment database is not configured",
)
class PaymentPostgresRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        db.apply_postgres_migrations()

    @classmethod
    def tearDownClass(cls):
        if cls.old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.old_database_url

    def test_provider_isolated_payment_and_full_refund_runtime_chain(self):
        now = datetime(2026, 7, 26, 16, 0, tzinfo=timezone.utc)
        user_id = f"runtime-pay-{uuid.uuid4()}"
        app_id = "app_runtime_test"
        db.execute(
            "INSERT INTO users("
            "id,username,email,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?,?)",
            (
                user_id,
                user_id,
                f"{user_id}@example.com",
                "hash",
                "salt",
                now.isoformat(),
            ),
        )
        billing.get_subscription(user_id)
        order = payment.create_order(
            user_id,
            "credit_package",
            "starter",
            idempotency_key=f"runtime-{uuid.uuid4()}",
            app_id=app_id,
            prod_mode=False,
            now=now,
        )
        self.assertTrue(payment.admit_payment_submission(order["id"], now=now))
        self.assertFalse(payment.admit_payment_submission(order["id"], now=now))
        order_row = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        payment_data = json.dumps(
            {
                "id": f"evt_runtime_payment_{uuid.uuid4().hex}",
                "type": "payment.succeeded",
                "created_time": int(now.timestamp()),
                "prod_mode": False,
                "app_id": app_id,
                "data": {
                    "id": f"pay_runtime_{uuid.uuid4().hex}",
                    "order_no": order_row["merchant_order_no"],
                    "pay_amt": "12.00",
                },
            },
            separators=(",", ":"),
        )
        with mock.patch.object(
            payment,
            "verify_adapay_signature",
            return_value=True,
        ):
            paid = payment.process_signed_callback(
                payment_data,
                "synthetic-signature",
                "synthetic-public-key",
                expected_app_id=app_id,
                expected_prod_mode=False,
                now=now,
            )
        self.assertTrue(paid["ok"])

        prepared = payment.prepare_full_refund(
            order["id"],
            reason_code="customer_request",
            now=now + timedelta(minutes=1),
        )
        refund_row = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        self.assertTrue(
            payment.admit_refund_submission(
                refund_row["id"],
                now=now + timedelta(minutes=2),
            )
        )
        self.assertFalse(
            payment.admit_refund_submission(
                refund_row["id"],
                now=now + timedelta(minutes=2),
            )
        )
        payment.mark_refund_submission(
            refund_row["id"],
            payment.ProviderRefundResult(
                merchant_refund_no=refund_row["merchant_refund_no"],
                provider_refund_id=f"refund_runtime_{uuid.uuid4().hex}",
                status="pending",
                amount_fen=1200,
                response_verified=True,
            ),
            now=now + timedelta(minutes=2),
        )
        refund_row = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        order_row = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        refund_data = json.dumps(
            {
                "id": f"evt_runtime_refund_{uuid.uuid4().hex}",
                "type": "refund.succeeded",
                "created_time": int(now.timestamp()),
                "prod_mode": False,
                "app_id": app_id,
                "data": {
                    "id": refund_row["provider_refund_id"],
                    "refund_order_no": refund_row["merchant_refund_no"],
                    "payment_id": order_row["provider_payment_id"],
                    "refund_amt": "12.00",
                },
            },
            separators=(",", ":"),
        )
        with mock.patch.object(
            payment,
            "verify_adapay_signature",
            return_value=True,
        ):
            refunded = payment.process_signed_callback(
                refund_data,
                "synthetic-signature",
                "synthetic-public-key",
                expected_app_id=app_id,
                expected_prod_mode=False,
                now=now + timedelta(minutes=3),
            )
        self.assertTrue(refunded["ok"])
        final_order = db.fetchone(
            "SELECT payment_status,entitlement_status,refund_status,"
            "refunded_fen FROM payment_orders WHERE id=?",
            (order["id"],),
        )
        self.assertEqual(final_order["payment_status"], "succeeded")
        self.assertEqual(final_order["entitlement_status"], "reversed")
        self.assertEqual(final_order["refund_status"], "refunded")
        self.assertEqual(final_order["refunded_fen"], 1200)
        self.assertEqual(
            db.fetchone(
                "SELECT SUM(amount_fen) AS total FROM payment_cash_ledger "
                "WHERE order_id=?",
                (order["id"],),
            )["total"],
            0,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_entitlement_ledger "
                "WHERE order_id=?",
                (order["id"],),
            )["c"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
