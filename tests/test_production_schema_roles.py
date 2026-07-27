import contextlib
import io
import os
import re
import unittest
from unittest import mock

from tools import production_schema_roles as schema_roles


class ProductionSchemaRolesTests(unittest.TestCase):
    def test_migration_and_runtime_role_inventories_are_exact(self):
        payloads = schema_roles._migration_payloads()

        self.assertEqual(tuple(payloads), schema_roles.EXPECTED_VERSIONS)
        self.assertEqual(schema_roles.LEGACY_VERSIONS, tuple(
            f"{number:04d}" for number in range(1, 9)
        ))
        self.assertEqual(schema_roles.NEW_VERSIONS, tuple(
            f"{number:04d}" for number in range(9, 17)
        ))
        self.assertEqual(len(schema_roles.EXPECTED_TABLES), 56)
        self.assertEqual(len(schema_roles.RUNTIME_ROLES), 8)
        self.assertEqual(len(schema_roles.NEW_RUNTIME_ROLES), 6)
        for payload, digest in payloads.values():
            self.assertTrue(payload)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_acl_is_credential_free_and_creates_only_inert_new_roles(self):
        acl = schema_roles.ACL_PATH.read_text(encoding="utf-8")
        executable_sql = "\n".join(
            line for line in acl.splitlines()
            if not line.lstrip().startswith("--")
        )

        for role in schema_roles.NEW_RUNTIME_ROLES:
            self.assertIn(f"'{role}'", acl)
        self.assertIn("CREATE ROLE %I NOLOGIN NOSUPERUSER", acl)
        self.assertIn("NOCREATEDB NOCREATEROLE", acl)
        self.assertIn("NOINHERIT NOREPLICATION NOBYPASSRLS", acl)
        self.assertNotRegex(
            executable_sql,
            re.compile(r"\bPASSWORD\b", re.IGNORECASE),
        )
        self.assertNotRegex(
            executable_sql,
            re.compile(r"\bLOGIN\b", re.IGNORECASE),
        )
        self.assertNotRegex(
            executable_sql,
            re.compile(r"\bALTER\s+ROLE\b", re.IGNORECASE),
        )
        self.assertNotIn("render_predeploy", acl)

    def test_acl_contains_required_contractions_and_isolation(self):
        acl = schema_roles.ACL_PATH.read_text(encoding="utf-8")

        self.assertIn("REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC", acl)
        self.assertIn("REVOKE UPDATE ON notes FROM noteai_app", acl)
        self.assertIn("REVOKE UPDATE ON saved_diagnoses FROM noteai_app", acl)
        self.assertIn("ON xhs_crawler_health TO noteai_xhs_trends", acl)
        self.assertIn("ON tracked_notes TO noteai_xhs_tracking", acl)
        self.assertIn("TO noteai_ai_dispatcher", acl)
        self.assertIn("TO noteai_ai_worker", acl)
        self.assertIn("TO noteai_payment", acl)
        self.assertIn("TO noteai_admin_runtime", acl)
        for signature in schema_roles.TRIGGER_FUNCTIONS[1:]:
            self.assertIn(signature.split(".", 1)[1], acl)

    def test_complete_role_matrix_keeps_ledger_and_schema_capabilities_negative(self):
        for role in schema_roles.RUNTIME_ROLES:
            self.assertNotIn(
                "schema_migrations",
                schema_roles.ROLE_TABLE_PRIVILEGES[role],
            )
        self.assertEqual(
            schema_roles.ROLE_SEQUENCES.get("noteai_admin_runtime", set()),
            set(),
        )
        self.assertEqual(
            schema_roles.ROLE_SEQUENCES.get("noteai_payment", set()),
            set(),
        )
        self.assertEqual(
            schema_roles.ROLE_SEQUENCES.get("noteai_ai_worker", set()),
            set(),
        )
        self.assertEqual(
            schema_roles.TRENDS_PRIVILEGES["xhs_crawler_health"],
            ("SELECT", "INSERT"),
        )
        self.assertEqual(
            schema_roles.TRACKING_PRIVILEGES["tracked_notes"],
            ("SELECT",),
        )

    def test_apply_fails_closed_without_exact_confirmation_before_connecting(self):
        stderr = io.StringIO()
        with (
            mock.patch.dict(
                os.environ,
                {
                    schema_roles.CONFIRM_ENV: "",
                    schema_roles.DATABASE_URL_ENV: "",
                },
                clear=False,
            ),
            mock.patch.object(
                schema_roles,
                "_connect",
                side_effect=AssertionError("connection must not be attempted"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = schema_roles.main(["--apply"])

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_schema_roles=FAIL code=confirmation_missing",
        )

    def test_verify_and_apply_sources_preserve_bounded_contract(self):
        source = schema_roles.Path(schema_roles.__file__).read_text(
            encoding="utf-8"
        )

        self.assertIn('conn.execute("SET TRANSACTION READ ONLY")', source)
        self.assertIn("with conn.transaction():", source)
        self.assertIn("SET LOCAL statement_timeout='120s'", source)
        self.assertIn("SET LOCAL lock_timeout='5s'", source)
        self.assertIn("NOTEAI_SCHEMA_APPLY_CONFIRM", source)
        self.assertIn("existing_business_row_updates", source)
        self.assertIn("migration_ledger_hash_backfills", source)
        self.assertIn('"provider_calls": 0', source)
        self.assertNotIn("apply_postgres_migrations()", source)
        self.assertNotIn("render_predeploy.py", source)

    def test_legacy_ledger_is_upgraded_before_hashes_are_selected(self):
        source = schema_roles.Path(schema_roles.__file__).read_text(
            encoding="utf-8"
        )

        prepare_call = source.index("\n        _prepare_migration_ledger(conn)\n")
        ledger_select = source.index(
            '"SELECT version,sha256 FROM schema_migrations ORDER BY version"',
            prepare_call,
        )
        self.assertLess(prepare_call, ledger_select)
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS sha256 TEXT",
            source,
        )
        self.assertIn(
            schema_roles.MIGRATION_LEDGER_CONSTRAINT,
            source,
        )


if __name__ == "__main__":
    unittest.main()
