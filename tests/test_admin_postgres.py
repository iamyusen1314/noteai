"""Disposable PostgreSQL proof for the dedicated Admin runtime role."""

import hashlib
import importlib
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")


@unittest.skipUnless(
    os.environ.get("NOTEAI_RUN_ADMIN_POSTGRES_TEST") == "1"
    and os.environ.get("NOTEAI_TEST_POSTGRES_URL", "").strip(),
    "approved disposable PostgreSQL Admin database is not configured",
)
class AdminPostgresContractTests(unittest.TestCase):
    FULL_SELECT_TABLES = {
        "subscriptions",
        "credits",
        "usage_records",
        "model_usage_records",
        "managed_prompts",
        "prompt_history",
        "system_settings",
        "tracked_notes",
        "ai_operations",
        "ai_operation_settlements",
        "ai_operation_outbox",
        "xhs_freshness_ledger",
        "xhs_crawler_health",
        "xhs_trends_runs",
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
    }
    COLUMN_SELECT = {
        "users": {
            "id",
            "username",
            "email",
            "phone",
            "nickname",
            "avatar_emoji",
            "created_at",
            "last_login",
        },
        "notes": {"id", "user_id", "score"},
        "credit_transactions": {
            "user_id",
            "type",
            "amount",
            "balance_after",
            "description",
            "paid_rmb",
            "package_id",
            "recorded_at",
        },
    }

    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict

        cls.old_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        cls.first_apply = db.apply_postgres_migrations()
        cls.second_apply = db.apply_postgres_migrations()
        cls.owner = db.get_conn()
        if cls.owner.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='noteai_admin_runtime'"
        ).fetchone():
            cls.owner.execute("DROP OWNED BY noteai_admin_runtime")
        cls.owner.execute("DROP ROLE IF EXISTS noteai_admin_runtime")
        cls.owner.execute(
            "CREATE ROLE noteai_admin_runtime LOGIN PASSWORD "
            "'admin-role-contract-disposable-only' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS"
        )
        cls.owner.execute(
            "INSERT INTO system_settings(key,value_json,is_secret,updated_at) "
            "VALUES('model_registry','{}',0,'2026-07-27T00:00:00+00:00'),"
            "('xhs_cookies','[\"synthetic-secret\"]',1,'2026-07-27T00:00:00+00:00') "
            "ON CONFLICT(key) DO UPDATE SET "
            "value_json=excluded.value_json,is_secret=excluded.is_secret,"
            "updated_at=excluded.updated_at"
        )
        role_sql = (
            ROOT / "scripts" / "postgres" / "noteai_admin_runtime_role.sql"
        ).read_text(encoding="utf-8")
        cls.owner.execute(role_sql)
        cls.owner.commit()

        params = conninfo_to_dict(os.environ["NOTEAI_TEST_POSTGRES_URL"])
        params.update(
            user="noteai_admin_runtime",
            password="admin-role-contract-disposable-only",
        )
        from psycopg.rows import dict_row

        cls.admin = psycopg.connect(**params, row_factory=dict_row)

    @classmethod
    def tearDownClass(cls):
        cls.admin.close()
        cls.owner.execute("DROP OWNED BY noteai_admin_runtime")
        cls.owner.execute("DROP ROLE IF EXISTS noteai_admin_runtime")
        cls.owner.commit()
        cls.owner.close()
        if cls.old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.old_database_url

    def test_apply_twice_and_migration_sha(self):
        version = "0016_admin_runtime_role_collision.sql"
        self.assertEqual(self.second_apply, [])
        expected = hashlib.sha256(
            (MODEL_DIR / "migrations" / "postgres" / version).read_bytes()
        ).hexdigest()
        row = self.owner.execute(
            "SELECT sha256 FROM schema_migrations WHERE version=%s",
            (version,),
        ).fetchone()
        self.assertEqual(row["sha256"], expected)

    def test_real_role_login_session_lifecycle_and_secret_filter(self):
        digest = "a" * 64
        self.admin.execute(
            "INSERT INTO admin_sessions(token,username,created_at,expires_at) "
            "VALUES(%s,'synthetic-admin',1,2)",
            (digest,),
        )
        row = self.admin.execute(
            "SELECT username FROM admin_sessions WHERE token=%s",
            (digest,),
        ).fetchone()
        self.assertEqual(row["username"], "synthetic-admin")
        visible = self.admin.execute(
            "SELECT key FROM system_settings ORDER BY key"
        ).fetchall()
        self.assertEqual([row["key"] for row in visible], ["model_registry"])
        self.admin.execute(
            "DELETE FROM admin_sessions WHERE token=%s",
            (digest,),
        )
        self.admin.commit()

    def test_complete_table_column_sequence_and_role_matrix(self):
        attrs = self.owner.execute(
            "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
            "rolreplication,rolbypassrls FROM pg_roles "
            "WHERE rolname='noteai_admin_runtime'"
        ).fetchone()
        self.assertEqual(
            dict(attrs),
            {
                "rolsuper": False,
                "rolinherit": False,
                "rolcreaterole": False,
                "rolcreatedb": False,
                "rolcanlogin": True,
                "rolreplication": False,
                "rolbypassrls": False,
            },
        )
        self.assertFalse(
            self.owner.execute(
                "SELECT EXISTS("
                "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
                "WHERE r.rolname='noteai_admin_runtime') AS present"
            ).fetchone()["present"]
        )
        privileges = (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        )
        tables = [
            row["table_name"]
            for row in self.owner.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            ).fetchall()
        ]
        for table in tables:
            expected = set()
            if table in self.FULL_SELECT_TABLES:
                expected.add("SELECT")
            if table == "admin_sessions":
                expected.update({"SELECT", "INSERT", "DELETE"})
            for privilege in privileges:
                actual = self.owner.execute(
                    "SELECT has_table_privilege("
                    "'noteai_admin_runtime',%s,%s) AS allowed",
                    (table, privilege),
                ).fetchone()["allowed"]
                self.assertEqual(actual, privilege in expected, (table, privilege))

            columns = [
                row["column_name"]
                for row in self.owner.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (table,),
                ).fetchall()
            ]
            for column in columns:
                expected_select = (
                    table in self.FULL_SELECT_TABLES
                    or table == "admin_sessions"
                    or column in self.COLUMN_SELECT.get(table, set())
                )
                actual_select = self.owner.execute(
                    "SELECT has_column_privilege("
                    "'noteai_admin_runtime',%s,%s,'SELECT') AS allowed",
                    (table, column),
                ).fetchone()["allowed"]
                self.assertEqual(
                    actual_select,
                    expected_select,
                    (table, column, "SELECT"),
                )

        sequences = self.owner.execute(
            "SELECT sequence_name FROM information_schema.sequences "
            "WHERE sequence_schema='public'"
        ).fetchall()
        for row in sequences:
            for privilege in ("USAGE", "SELECT", "UPDATE"):
                self.assertFalse(
                    self.owner.execute(
                        "SELECT has_sequence_privilege("
                        "'noteai_admin_runtime',%s,%s) AS allowed",
                        (row["sequence_name"], privilege),
                    ).fetchone()["allowed"],
                    (row["sequence_name"], privilege),
                )
        self.assertFalse(
            self.owner.execute(
                "SELECT has_schema_privilege("
                "'noteai_admin_runtime','public','CREATE') AS allowed"
            ).fetchone()["allowed"]
        )
        self.assertFalse(
            self.owner.execute(
                "SELECT has_database_privilege("
                "'noteai_admin_runtime',current_database(),'TEMP') AS allowed"
            ).fetchone()["allowed"]
        )
        self.assertFalse(
            self.owner.execute(
                "SELECT has_table_privilege("
                "'noteai_admin_runtime','schema_migrations','SELECT') AS allowed"
            ).fetchone()["allowed"]
        )
        self.assertFalse(
            self.owner.execute(
                "SELECT EXISTS("
                "SELECT 1 FROM pg_proc p WHERE p.prosecdef "
                "AND has_function_privilege("
                "'noteai_admin_runtime',p.oid,'EXECUTE')) "
                "AS allowed"
            ).fetchone()["allowed"]
        )

    def test_direct_negative_operations_fail_closed(self):
        probes = (
            "SELECT password_hash FROM users LIMIT 1",
            "SELECT payment_ref FROM credit_transactions LIMIT 1",
            "SELECT * FROM schema_migrations",
            "UPDATE admin_sessions SET username='forbidden'",
            "INSERT INTO users(id,username,password_hash,password_salt,created_at) "
            "VALUES('forbidden','forbidden','x','x','2026-07-27T00:00:00+00:00')",
            "CREATE TEMP TABLE forbidden_temp(id integer)",
            "CREATE TABLE public.forbidden_table(id integer)",
        )
        for sql in probes:
            with self.subTest(sql=sql):
                self.admin.execute("SAVEPOINT denied_probe")
                with self.assertRaises(Exception):
                    self.admin.execute(sql)
                self.admin.execute("ROLLBACK TO SAVEPOINT denied_probe")
        self.admin.rollback()


if __name__ == "__main__":
    unittest.main()
