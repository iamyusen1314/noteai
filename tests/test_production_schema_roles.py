import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import production_first_launch_role_risk_set_audit as risk_set_audit
from tools import production_schema_outcome_audit as outcome_audit
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
        self.assertEqual(
            tuple(
                name for name, _payload in
                schema_roles._runtime_acl_payloads()
            ),
            schema_roles.EXPECTED_ACL_STAGES,
        )
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
        for stage in schema_roles.EXPECTED_ACL_STAGES:
            self.assertIn(
                f"{schema_roles.ACL_STAGE_MARKER}{stage}",
                acl,
            )
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
        self.assertIn("SET LOCAL ROLE", source)
        self.assertIn(schema_roles.MIGRATION_OWNER_ROLE, source)
        self.assertIn("member.rolname='noteai_app'", source)
        self.assertIn("pg_has_role('noteai_app',role.oid,'USAGE')", source)
        self.assertIn(
            'row["inherit_option"] is not False',
            source,
        )
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
        self.assertIn(")::boolean IS FALSE", acl)
        self.assertIn("current_user <> 'noteai_admin'", acl)
        self.assertIn("current_role <> 'noteai_admin'", acl)
        self.assertIn(") <> 7", acl)
        self.assertIn(") <> 6", acl)
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

    def test_apply_unexpected_source_failure_uses_fixed_sanitized_stage(self):
        with (
            mock.patch.object(
                schema_roles,
                "_migration_payloads",
                side_effect=RuntimeError("must-not-leak"),
            ),
            self.assertRaises(schema_roles.SchemaRoleError) as raised,
        ):
            schema_roles.apply_contract(mock.Mock())

        self.assertEqual(raised.exception.code, "apply_local_source_failed")
        self.assertNotIn("must-not-leak", raised.exception.code)

    def test_apply_unexpected_transaction_begin_failure_uses_fixed_stage(self):
        transaction = mock.MagicMock()
        transaction.__enter__.side_effect = RuntimeError("must-not-leak")
        conn = mock.Mock()
        conn.transaction.return_value = transaction

        with self.assertRaises(schema_roles.SchemaRoleError) as raised:
            schema_roles.apply_contract(conn)

        self.assertEqual(
            raised.exception.code,
            "apply_transaction_begin_failed",
        )
        self.assertNotIn("must-not-leak", raised.exception.code)

    def test_apply_preserves_existing_fail_closed_contract_codes(self):
        with (
            mock.patch.object(
                schema_roles,
                "_migration_payloads",
                side_effect=schema_roles.SchemaRoleError("migration_set"),
            ),
            self.assertRaises(schema_roles.SchemaRoleError) as raised,
        ):
            schema_roles.apply_contract(mock.Mock())

        self.assertEqual(raised.exception.code, "migration_set")

    def test_unexpected_connection_failure_is_sanitized_without_dsn(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                schema_roles,
                "_connect",
                side_effect=RuntimeError("opaque-protected-input"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = schema_roles.main(
                ["--verify"],
                database_url="opaque-protected-input",
            )

        self.assertEqual(result, 1)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_schema_roles=FAIL code=database_connection_failed",
        )
        self.assertNotIn("opaque-protected-input", stderr.getvalue())

    def test_v5_runner_is_fixed_stdin_only_and_stage_safe(self):
        runner_path = (
            Path(schema_roles.__file__).resolve().parent
            / "production_schema_roles_runner.sh"
        )
        runner = runner_path.read_text(encoding="utf-8")

        self.assertIn(
            "task_root=/var/lib/noteai/schema-roles-v5-owner",
            runner,
        )
        self.assertIn(
            "incident_id=PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-"
            "ROLES-V5-OWNER-001",
            runner,
        )
        self.assertIn(
            "prepare | preflight | apply | outcome",
            runner,
        )
        self.assertIn(
            "SAFE_SCHEMA_ROLES_V5",
            runner,
        )
        self.assertIn(
            "database_url=value",
            runner,
        )
        self.assertIn(
            hashlib.sha256(
                Path(schema_roles.__file__).read_bytes()
            ).hexdigest(),
            runner,
        )
        self.assertIn(
            hashlib.sha256(
                Path(outcome_audit.__file__).read_bytes()
            ).hexdigest(),
            runner,
        )
        self.assertIn(
            hashlib.sha256(
                Path(risk_set_audit.__file__).read_bytes()
            ).hexdigest(),
            runner,
        )
        self.assertIn("--network none", runner)
        self.assertIn("--network host", runner)
        self.assertEqual(runner.count("-e PYTHONPATH=/task/tools"), 2)
        self.assertIn(
            "import production_schema_roles; "
            "import production_schema_outcome_audit; "
            "import production_first_launch_role_risk_set_audit",
            runner,
        )
        self.assertNotIn("import tools.production_schema_roles", runner)
        self.assertNotIn("from tools.production_schema", runner)
        self.assertNotIn("from tools.production_first_launch", runner)
        self.assertIn("package_manifest_sha", runner)
        self.assertIn("import=passed", runner)
        self.assertIn("validate_result()", runner)
        self.assertIn("json.load(handle)", runner)
        self.assertIn("automatic_retry=0", runner)
        self.assertGreaterEqual(runner.count("cleanup_required=1"), 5)
        self.assertIn("apply_transaction=committed", runner)
        self.assertIn("audit_transaction=rolled_back", runner)
        self.assertNotIn(" transaction=rolled_back", runner)
        self.assertIn('roles.get("membership_count") == 7', runner)
        self.assertIn(
            'roles.get("management_membership_count") == 6',
            runner,
        )
        self.assertIn(
            'roles.get("migration_owner_mismatch_count") == 0',
            runner,
        )
        self.assertIn(
            'roles.get("executor_owned_object_count") == 0',
            runner,
        )
        self.assertIn('"migration_ledger_hash_backfills": 8', runner)
        self.assertIn('"retention_backfill_rows": 0', runner)
        self.assertIn('"existing_business_row_updates": 0', runner)
        self.assertNotIn("/etc/noteai/api.env", runner)
        self.assertNotIn("-e NOTEAI_SCHEMA", runner)
        self.assertNotIn("postgresql://", runner)

    def test_v5_runner_structured_result_validator_rejects_write_drift(self):
        runner_path = (
            Path(schema_roles.__file__).resolve().parent
            / "production_schema_roles_runner.sh"
        )
        runner = runner_path.read_text(encoding="utf-8")
        marker = "python3 - \"${1}\" \"${2}\" <<'PY'\n"
        validator = runner.split(marker, 1)[1].split("\nPY\n}", 1)[0]
        common = {
            "task_id": schema_roles.TASK_ID,
            "provider_calls": 0,
            "service_changes": 0,
            "public_traffic_requests": 0,
            "secret_values_exposed": 0,
        }
        preflight = {
            **common,
            "status": "accepted_risk_observed",
            "incident_class": "CONNECTED_KNOWN",
            "read_only": True,
            "transaction_rolled_back": True,
            "fixed_query_count": 4,
            "database_connection_count": 1,
            "database_write_count": 0,
            "acceptance": {
                "session": True,
                "ledger_inventory": True,
                "role_graph": True,
                "xhs_acl": True,
            },
            "ledger_inventory": {
                "ledger_exact": True,
                "ledger_count": 8,
                "table_count": 30,
                "sequence_count": 5,
                "ledger_sha_column_count": 0,
                "new_runtime_role_count": 0,
                "retention_backfill_source_count": 0,
            },
            "role_graph": {
                "membership_count": 1,
                "membership_admin": True,
                "membership_inherit": False,
                "membership_set": False,
                "app_high_privilege_inheritance_count": 0,
            },
        }
        apply_result = {
            **common,
            "status": "verified",
            "transaction_committed": True,
            "applied_versions": [
                f"{number:04d}" for number in range(9, 17)
            ],
            "database_writes": {
                "migration_ledger_rows": 8,
                "migration_ledger_hash_backfills": 8,
                "schema_seed_rows": 2,
                "retention_backfill_rows": 0,
                "existing_business_row_updates": 0,
            },
            "roles": {
                "membership_count": 7,
                "management_membership_count": 6,
                "migration_owner_mismatch_count": 0,
                "executor_owned_object_count": 0,
                "unexpected_membership_count": 0,
                "unexpected_elevation_count": 0,
                "high_privilege_inheritance_count": 0,
            },
        }
        outcome = {
            **common,
            "status": "classified",
            "database_outcome": "COMMITTED",
            "read_only": True,
            "default_transaction_read_only": True,
            "transaction_read_only": True,
            "observation": {"business_row_values_read": 0},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            for mode, result in (
                ("preflight", preflight),
                ("apply", apply_result),
                ("outcome", outcome),
            ):
                path = Path(temp_dir) / f"{mode}.json"
                path.write_text(json.dumps(result), encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, "-", mode, str(path)],
                    input=validator,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

            apply_result["database_writes"]["retention_backfill_rows"] = 1
            path = Path(temp_dir) / "apply-drift.json"
            path.write_text(json.dumps(apply_result), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-", "apply", str(path)],
                input=validator,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
