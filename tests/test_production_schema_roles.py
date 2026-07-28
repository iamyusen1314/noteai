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

        advisory_call = source.index(
            "SELECT pg_advisory_xact_lock("
            "hashtext('noteai_schema_migrations'))"
        )
        legacy_name_select = source.index(
            '"SELECT version FROM schema_migrations ORDER BY version"',
            advisory_call,
        )
        retention_precondition = source.index(
            '"(SELECT COUNT(*) FROM saved_diagnoses)"',
            legacy_name_select,
        )
        prepare_call = source.index("\n        _prepare_migration_ledger(conn)\n")
        ledger_update = source.index(
            '"UPDATE schema_migrations SET sha256=%s "',
            prepare_call,
        )
        self.assertLess(advisory_call, legacy_name_select)
        self.assertLess(legacy_name_select, retention_precondition)
        self.assertLess(retention_precondition, prepare_call)
        self.assertLess(prepare_call, ledger_update)
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS sha256 TEXT",
            source,
        )
        self.assertIn(
            schema_roles.MIGRATION_LEDGER_CONSTRAINT,
            source,
        )

    def test_two_accepted_role_risks_are_exact_and_not_configurable(self):
        source = schema_roles.Path(schema_roles.__file__).read_text(
            encoding="utf-8"
        )
        acl = schema_roles.ACL_PATH.read_text(encoding="utf-8")

        self.assertEqual(
            schema_roles.ACCEPTED_ROLE_RISK_PROFILE,
            "FIRST_LAUNCH_LEGACY_ROLE_RISK_V1",
        )
        self.assertEqual(len(schema_roles.ACCEPTED_ROLE_RISK_IDS), 2)
        self.assertIn("current_user <> 'noteai_xhs'", source)
        self.assertIn("session_user <> 'noteai_xhs'", source)
        self.assertIn("session_user=current_user", source)
        self.assertIn("member.rolname='noteai_app'", source)
        self.assertIn("pg_has_role('noteai_app',role.oid,'USAGE')", source)
        self.assertIn("WITH GRANT OPTION", source)
        self.assertEqual(
            schema_roles.COLUMN_PRIVILEGES,
            ("SELECT", "INSERT", "UPDATE", "REFERENCES"),
        )
        self.assertIn("default_acl", source)
        self.assertIn("public_function_execute_count", source)
        self.assertIn("granted.rolname = 'noteai_xhs'", acl)
        self.assertIn("member.rolname = 'noteai_admin'", acl)
        self.assertIn("membership.admin_option", acl)
        self.assertIn("session_user = 'noteai_xhs'", acl)
        self.assertIn("session_user <> current_user", acl)
        self.assertIn("accepted runtime role membership changed", acl)
        self.assertNotIn("ACCEPTED_ROLE_RISK_PROFILE", os.environ)

    def test_postconditions_bind_exact_seed_and_write_counts(self):
        source = schema_roles.Path(schema_roles.__file__).read_text(
            encoding="utf-8"
        )

        self.assertIn("migration_hash_backfill_count", source)
        self.assertIn("migration_ledger_insert_count", source)
        self.assertIn("expected_backfills = 8", source)
        self.assertIn("service_key='market_timing'", source)
        self.assertIn("lease_fence=0", source)
        self.assertIn("session_blocked IS FALSE", source)
        self.assertIn("service_key='durable_ai'", source)
        self.assertIn(
            "updated_at='1970-01-01T00:00:00+00:00'",
            source,
        )

    def test_protected_call_can_supply_dsn_and_confirmation_without_env(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                schema_roles,
                "_connect",
                side_effect=schema_roles.SchemaRoleError(
                    "database_url_missing"
                ),
            ) as connect,
            contextlib.redirect_stderr(stderr),
        ):
            result = schema_roles.main(
                ["--apply"],
                database_url="opaque-protected-input",
                confirmation=schema_roles.TASK_ID,
            )

        self.assertEqual(result, 1)
        connect.assert_called_once_with("opaque-protected-input")
        self.assertNotIn("opaque-protected-input", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
