import contextlib
import io
import os
import unittest
from unittest import mock

from tools import production_durable_ai_schema_0017 as schema_0017


class ProductionDurableAiSchema0017Tests(unittest.TestCase):
    def test_source_contract_is_exact_and_incremental(self):
        contract = schema_0017.source_contract()

        self.assertEqual(
            contract["migration_sha256"],
            schema_0017.MIGRATION_SHA256,
        )
        self.assertEqual(
            tuple(contract["migration_hashes"]),
            schema_0017.EXPECTED_MIGRATION_NAMES,
        )
        self.assertEqual(
            schema_0017.WORKER_SELECT_AFTER["ai_operation_outbox"],
            {"id", "operation_id", "state", "delivered_at"},
        )
        self.assertNotIn("acl_payload", contract)

    def test_role_snapshot_accepts_existing_worker_login(self):
        connection = mock.Mock()
        connection.execute.return_value.fetchone.return_value = {
            "role_count": 2,
            "snapshot": '{"roles":[{"rolcanlogin":true}]}',
        }

        snapshot = schema_0017._runtime_role_snapshot(connection)

        self.assertIn('"rolcanlogin":true', snapshot)

    def test_apply_requires_exact_confirmation_before_connecting(self):
        stderr = io.StringIO()
        with (
            mock.patch.dict(
                os.environ,
                {
                    schema_0017.CONFIRM_ENV: "",
                    schema_0017.DATABASE_URL_ENV: "",
                },
                clear=False,
            ),
            mock.patch.object(
                schema_0017,
                "_connect",
                side_effect=AssertionError("must not connect"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = schema_0017.main(["--apply"])

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_durable_ai_schema_0017=FAIL code=confirmation_missing",
        )

    def test_verify_is_read_only_and_closes_connection(self):
        connection = mock.Mock()
        verified = {
            "status": "verified",
            "mode": "verify",
            "read_only": True,
            "database_writes": 0,
            "provider_calls": 0,
        }
        stdout = io.StringIO()
        with (
            mock.patch.object(schema_0017, "_connect", return_value=connection),
            mock.patch.object(
                schema_0017,
                "verify_schema",
                return_value=verified,
            ) as verify,
            contextlib.redirect_stdout(stdout),
        ):
            result = schema_0017.main(["--verify"])

        self.assertEqual(result, 0)
        verify.assert_called_once()
        connection.close.assert_called_once_with()
        self.assertNotIn("DATABASE_URL", stdout.getvalue())
        self.assertIn('"read_only":true', stdout.getvalue())

    def test_source_preserves_owner_bound_bounded_transaction(self):
        source = schema_0017.Path(schema_0017.__file__).read_text(
            encoding="utf-8"
        )

        self.assertIn("SET LOCAL ROLE", source)
        self.assertIn("SET TRANSACTION READ ONLY", source)
        self.assertIn("pg_advisory_xact_lock", source)
        self.assertIn("SET LOCAL statement_timeout='60s'", source)
        self.assertIn("SET LOCAL lock_timeout='5s'", source)
        self.assertIn("PRIOR_MIGRATION_NAMES", source)
        self.assertIn("runtime_roles_unchanged", source)
        self.assertNotIn("acl_payload", source)
        self.assertNotIn("noteai_production_runtime_roles_0017.sql", source)
        self.assertNotIn("apply_postgres_migrations()", source)
        self.assertNotIn("render_predeploy.py", source)


if __name__ == "__main__":
    unittest.main()
