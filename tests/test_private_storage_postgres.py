"""Disposable PostgreSQL proof for migration 0013 and private-media roles."""

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
    os.environ.get("NOTEAI_RUN_PRIVATE_STORAGE_POSTGRES_TEST") == "1"
    and os.environ.get("NOTEAI_TEST_POSTGRES_URL", "").strip(),
    "approved disposable PostgreSQL private-storage database is not configured",
)
class PrivateStoragePostgresContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        cls.first_apply = db.apply_postgres_migrations()
        cls.second_apply = db.apply_postgres_migrations()
        cls.conn = db.get_conn()
        for role in (
            "noteai_app",
            "noteai_ai_worker",
            "noteai_ai_dispatcher",
            "noteai_admin",
            "noteai_xhs_tracking",
            "noteai_xhs_trends",
        ):
            cls.conn.execute(f"DROP ROLE IF EXISTS {role}")
            cls.conn.execute(
                f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            cls.conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cls.conn.execute(
            "GRANT SELECT,INSERT ON private_media_refs TO noteai_app"
        )
        cls.conn.execute(
            "GRANT UPDATE(state,deleted_at) ON private_media_refs TO noteai_app"
        )
        cls.conn.execute(
            "GRANT SELECT,INSERT ON ai_operation_media_refs TO noteai_app"
        )
        cls.conn.execute(
            "GRANT SELECT(id,subject_hash) ON ai_operations TO noteai_app"
        )
        cls.conn.execute(
            "GRANT SELECT ON private_media_refs,ai_operation_media_refs "
            "TO noteai_ai_worker"
        )
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        for role in (
            "noteai_app",
            "noteai_ai_worker",
            "noteai_ai_dispatcher",
            "noteai_admin",
            "noteai_xhs_tracking",
            "noteai_xhs_trends",
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
        self.expiry = "2026-07-27T12:00:00+00:00"

    def tearDown(self):
        self.conn.rollback()

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def operation(self, label: str, *, subject_hash: str | None = None) -> str:
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, label))
        subject = subject_hash or self.digest(f"subject:{label}")
        self.conn.execute(
            "INSERT INTO ai_operations("
            "id,subject_hash,request_hash,operation_kind,status,provider_phase,"
            "priority,available_at,created_at,updated_at) "
            "VALUES(%s,%s,%s,'analyze','queued','not_started',0,%s,%s,%s)",
            (
                operation_id,
                subject,
                self.digest(f"request:{label}"),
                self.clock,
                self.clock,
                self.clock,
            ),
        )
        return operation_id

    def media_values(
        self,
        label: str,
        *,
        subject_hash: str,
        purpose: str = "image",
        state: str = "ready",
        expiry: str | None = None,
    ) -> tuple:
        reference_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, label))
        content_type = (
            "image/jpeg"
            if purpose == "image"
            else "application/vnd.noteai.video-frames+zip"
        )
        count = 1 if purpose == "image" else 2
        return (
            reference_id,
            subject_hash,
            purpose,
            content_type,
            self.digest(f"object:{label}"),
            self.digest(f"content:{label}"),
            100,
            count,
            1,
            "provider_managed",
            self.digest("key-epoch"),
            state,
            expiry or self.expiry,
            self.clock,
            self.clock,
            None,
        )

    def insert_media(self, values: tuple) -> str:
        self.conn.execute(
            "INSERT INTO private_media_refs("
            "id,subject_hash,purpose,content_type,object_key_hash,content_sha256,"
            "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,"
            "state,expires_at,created_at,ready_at,deleted_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            values,
        )
        return values[0]

    def test_apply_twice_sha_ledger_and_schema(self):
        self.assertIn(
            "0013_private_storage_recovery_contract.sql",
            self.first_apply,
        )
        self.assertEqual(self.second_apply, [])
        migration_path = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0013_private_storage_recovery_contract.sql"
        )
        expected = hashlib.sha256(migration_path.read_bytes()).hexdigest()
        row = self.conn.execute(
            "SELECT sha256 FROM schema_migrations WHERE version=%s",
            ("0013_private_storage_recovery_contract.sql",),
        ).fetchone()
        self.assertEqual(row["sha256"], expected)
        tables = {
            row["table_name"]
            for row in self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            ).fetchall()
        }
        self.assertTrue(
            {"private_media_refs", "ai_operation_media_refs"}.issubset(tables)
        )

    def test_persistent_constraints_reject_size_type_clock_and_state(self):
        subject = self.digest("constraint-owner")
        base = list(self.media_values("constraint-media", subject_hash=subject))
        cases = (
            (6, 0),
            (6, 10485761),
            (3, "text/plain"),
            (7, 2),
            (11, "arbitrary"),
            (12, "2026-07-26 13:00:00"),
            (12, "2026-07-28T20:00:00+08:00"),
        )
        for index, invalid in cases:
            with self.subTest(index=index, invalid=invalid):
                values = list(base)
                values[0] = str(uuid.uuid4())
                values[index] = invalid
                self.conn.execute("SAVEPOINT invalid_media")
                with self.assertRaises(Exception):
                    self.insert_media(tuple(values))
                self.conn.execute("ROLLBACK TO SAVEPOINT invalid_media")

    def test_owner_guard_rejects_cross_subject_expired_and_nonready_links(self):
        owner_subject = self.digest("link-owner")
        other_subject = self.digest("link-other")
        operation_id = self.operation(
            "link-operation",
            subject_hash=owner_subject,
        )
        valid_id = self.insert_media(
            self.media_values("valid-media", subject_hash=owner_subject)
        )
        self.conn.execute(
            "INSERT INTO ai_operation_media_refs("
            "operation_id,media_ref_id,ordinal,created_at) "
            "VALUES(%s,%s,0,%s)",
            (operation_id, valid_id, self.clock),
        )

        cross_id = self.insert_media(
            self.media_values("cross-media", subject_hash=other_subject)
        )
        expired_values = list(
            self.media_values(
                "expired-media",
                subject_hash=owner_subject,
                expiry="2026-07-26T11:00:00+00:00",
            )
        )
        expired_values[13] = "2026-07-25T12:00:00+00:00"
        expired_values[14] = "2026-07-25T12:00:00+00:00"
        expired_id = self.insert_media(tuple(expired_values))
        deleted_values = list(
            self.media_values("deleted-media", subject_hash=owner_subject)
        )
        deleted_values[11] = "deleted"
        deleted_values[15] = self.clock
        deleted_id = self.insert_media(tuple(deleted_values))
        for media_id in (cross_id, expired_id, deleted_id):
            with self.subTest(media_id=media_id):
                self.conn.execute("SAVEPOINT invalid_link")
                with self.assertRaises(Exception):
                    self.conn.execute(
                        "INSERT INTO ai_operation_media_refs("
                        "operation_id,media_ref_id,ordinal,created_at) "
                        "VALUES(%s,%s,1,%s)",
                        (operation_id, media_id, self.clock),
                    )
                self.conn.execute("ROLLBACK TO SAVEPOINT invalid_link")

    def test_rls_and_complete_negative_role_matrix(self):
        subject = self.digest("rls-owner")
        operation_id = self.operation("rls-operation", subject_hash=subject)
        values = self.media_values("rls-media", subject_hash=subject)
        self.conn.execute("SET LOCAL ROLE noteai_app")
        media_id = self.insert_media(values)
        self.conn.execute(
            "INSERT INTO ai_operation_media_refs("
            "operation_id,media_ref_id,ordinal,created_at) "
            "VALUES(%s,%s,0,%s)",
            (operation_id, media_id, self.clock),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS count FROM private_media_refs"
            ).fetchone()["count"],
            1,
        )
        self.conn.execute("RESET ROLE")

        self.conn.execute("SET LOCAL ROLE noteai_ai_worker")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS count FROM ai_operation_media_refs"
            ).fetchone()["count"],
            1,
        )
        self.conn.execute("SAVEPOINT worker_insert_denied")
        with self.assertRaises(Exception):
            self.insert_media(
                self.media_values("worker-denied", subject_hash=subject)
            )
        self.conn.execute("ROLLBACK TO SAVEPOINT worker_insert_denied")
        self.conn.execute("RESET ROLE")

        positive_tables = {
            "noteai_app": {
                "private_media_refs": {"SELECT", "INSERT"},
                "ai_operation_media_refs": {"SELECT", "INSERT"},
            },
            "noteai_ai_worker": {
                "private_media_refs": {"SELECT"},
                "ai_operation_media_refs": {"SELECT"},
            },
        }
        roles = (
            "noteai_app",
            "noteai_ai_worker",
            "noteai_ai_dispatcher",
            "noteai_admin",
            "noteai_xhs_tracking",
            "noteai_xhs_trends",
        )
        tables = ("private_media_refs", "ai_operation_media_refs")
        privileges = (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        )
        for role in roles:
            attributes = self.conn.execute(
                "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
                "rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s",
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
                    "SELECT has_table_privilege(%s,'schema_migrations','SELECT') "
                    "AS allowed",
                    (role,),
                ).fetchone()["allowed"]
            )
            for table in tables:
                for privilege in privileges:
                    expected = privilege in positive_tables.get(role, {}).get(
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
        allowed_updates = {"state", "deleted_at"}
        columns = [
            row["column_name"]
            for row in self.conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='private_media_refs'"
            ).fetchall()
        ]
        for column in columns:
            self.assertEqual(
                self.conn.execute(
                    "SELECT has_column_privilege("
                    "'noteai_app','private_media_refs',%s,'UPDATE') AS allowed",
                    (column,),
                ).fetchone()["allowed"],
                column in allowed_updates,
                column,
            )


if __name__ == "__main__":
    unittest.main()
