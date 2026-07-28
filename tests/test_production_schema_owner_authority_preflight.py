import contextlib
import hashlib
import io
import pathlib
import unittest
from unittest import mock

from tools import production_schema_owner_authority_preflight as preflight


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return list(self.rows)


class ExactOwnerConnection:
    def __init__(self, *, activation_error=None, state_overrides=None):
        self.calls = []
        self.activation_error = activation_error
        self.state_overrides = state_overrides or {}

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split())
        self.calls.append((normalized, params))
        if normalized == "SET LOCAL ROLE noteai_admin":
            if self.activation_error is not None:
                raise self.activation_error
            return FakeResult()
        if normalized.startswith("WITH executor AS"):
            return FakeResult([{
                "default_ro": True,
                "transaction_ro": True,
                "identity_unchanged": True,
                "executor_not_runtime": True,
                "executor_is_owner": True,
                "owner_activation_capable": True,
                "transient_executor_dependency_count": 0,
                "unexpected_runtime_membership_count": 0,
                "direct_owner_set_membership_count": 0,
            }])
        if normalized.startswith("WITH owner_role AS"):
            return FakeResult([{
                "owner_activated": True,
                "executor_not_runtime": True,
                "owner_non_superuser": True,
                "owner_createrole": True,
                "owner_database_exact": True,
                "owner_schema_usage": True,
                "owner_schema_create_grantable": True,
                "public_relation_count": 37,
                "public_function_count": 0,
                "owner_mismatch_count": 0,
            }])
        if normalized.startswith("WITH ledger AS"):
            state = {
                "ledger_exact": True,
                "ledger_count": 8,
                "tables_exact": True,
                "table_count": 30,
                "sequences_exact": True,
                "sequence_count": 5,
                "ledger_sha_column_count": 0,
                "runtime_role_count": 2,
                "new_runtime_role_count": 0,
                "app_attributes_exact": True,
                "xhs_attributes_exact": True,
                "runtime_membership_count": 1,
                "accepted_membership_count": 1,
                "accepted_membership_admin": True,
                "accepted_membership_inherit": False,
                "accepted_membership_set": False,
                "app_incoming_membership_count": 0,
                "app_high_privilege_inheritance_count": 0,
                "retention_backfill_source_count": 0,
                "task_role_residue_count": 0,
            }
            state.update(self.state_overrides)
            return FakeResult([state])
        return FakeResult()

    def close(self):
        self.calls.append(("CLOSE", ()))


class ProductionSchemaOwnerAuthorityPreflightTests(unittest.TestCase):
    def test_source_registry_and_fixed_ids_are_exact(self):
        registry = preflight._source_registry()

        self.assertEqual(preflight.TASK_ID, (
            "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-"
            "OWNER-AUTHORITY-PREFLIGHT-004"
        ))
        self.assertEqual(
            preflight.APPLICATION_NAME,
            "noteai_schema_owner_authority_preflight_v1",
        )
        self.assertEqual(preflight.MIGRATION_OWNER_ROLE, "noteai_admin")
        self.assertEqual(preflight.STAGE_ORDER, (
            "session",
            "migration_owner_activation",
            "owner_contract",
            "production_state",
            "rollback",
        ))
        self.assertEqual(len(registry), 21)
        for digest in registry.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_sql_contract_is_three_fixed_queries_and_one_activation(self):
        source = pathlib.Path(preflight.__file__).read_text(encoding="utf-8")

        self.assertIn(
            "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
            source,
        )
        self.assertIn("SET LOCAL ROLE", source)
        self.assertIn("pg_has_role(session_user, %s, 'SET')", (
            preflight.SESSION_SQL
        ))
        self.assertIn(
            "transient_executor_dependency_count",
            preflight.SESSION_SQL,
        )
        self.assertIn(
            "CREATE WITH GRANT OPTION",
            preflight.OWNER_CONTRACT_SQL,
        )
        self.assertIn("owner_mismatch_count", preflight.OWNER_CONTRACT_SQL)
        self.assertIn("task_role_residue_count", preflight.PRODUCTION_STATE_SQL)
        for verb in (
            "INSERT", "UPDATE", "DELETE", "ALTER",
            "CREATE", "DROP", "GRANT", "REVOKE",
        ):
            self.assertNotIn(f'conn.execute("{verb} ', source)

    def test_exact_owner_path_is_verified_and_terminally_rolled_back(self):
        connection = ExactOwnerConnection()

        result = preflight.collect_owner_authority(connection)

        self.assertEqual(result["status"], "owner_authority_verified")
        self.assertEqual(result["database_connection_count"], 1)
        self.assertEqual(result["database_write_count"], 0)
        self.assertEqual(result["business_row_values_read"], 0)
        self.assertTrue(result["transaction_rolled_back"])
        statements = [statement for statement, _params in connection.calls]
        self.assertEqual(
            statements[0],
            "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
        )
        self.assertIn("SET LOCAL ROLE noteai_admin", statements)
        self.assertEqual(statements[-1], "ROLLBACK")
        self.assertFalse(any(
            statement.startswith((
                "INSERT ", "UPDATE ", "DELETE ", "ALTER ", "CREATE ",
                "DROP ", "GRANT ", "REVOKE ",
            ))
            for statement in statements
        ))

    def test_any_owner_or_production_drift_is_state_changed(self):
        for mismatch in (
            {"ledger_count": 9},
            {"tables_exact": False},
            {"sequence_count": 4},
            {"runtime_membership_count": 2},
            {"accepted_membership_inherit": True},
            {"app_high_privilege_inheritance_count": 1},
            {"retention_backfill_source_count": 1},
            {"task_role_residue_count": 1},
        ):
            with self.subTest(mismatch=mismatch):
                result = preflight.collect_owner_authority(
                    ExactOwnerConnection(state_overrides=mismatch)
                )
                self.assertEqual(result["status"], "state_changed")

    def test_activation_failure_rolls_back_and_is_connected_known(self):
        connection = ExactOwnerConnection(
            activation_error=RuntimeError("must-not-render")
        )

        with self.assertRaises(
            preflight.OwnerAuthorityPreflightError
        ) as raised:
            preflight.collect_owner_authority(connection)

        self.assertEqual(raised.exception.code, "owner_activation_failed")
        self.assertEqual(
            raised.exception.stage,
            "migration_owner_activation",
        )
        self.assertEqual(
            raised.exception.incident_class,
            "CONNECTED_KNOWN",
        )
        self.assertEqual(connection.calls[-1][0], "ROLLBACK")
        self.assertNotIn("must-not-render", str(raised.exception))

    def test_no_dsn_is_preconnect_without_connection_attempt(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                preflight,
                "_connect",
                side_effect=AssertionError("must not connect"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            code = preflight.main(database_url=None)

        self.assertEqual(code, 2)
        self.assertIn("incident_class=PRE_CONNECT", stderr.getvalue())
        self.assertIn("database_connected=0", stderr.getvalue())

    def test_protected_input_never_reaches_output(self):
        connection = mock.Mock()
        stdout = io.StringIO()
        with (
            mock.patch.object(
                preflight,
                "_connect",
                return_value=connection,
            ) as connect,
            mock.patch.object(
                preflight,
                "collect_owner_authority",
                return_value={"status": "owner_authority_verified"},
            ),
            contextlib.redirect_stdout(stdout),
        ):
            code = preflight.main(database_url="opaque-protected-input")

        self.assertEqual(code, 0)
        connect.assert_called_once_with("opaque-protected-input")
        connection.close.assert_called_once_with()
        self.assertNotIn("opaque-protected-input", stdout.getvalue())

    def test_runner_is_fixed_local_secret_pipe_and_stage_safe(self):
        runner_path = (
            pathlib.Path(preflight.__file__).resolve().parent
            / "production_schema_owner_authority_preflight_runner.sh"
        )
        runner = runner_path.read_text(encoding="utf-8")
        auditor_sha256 = hashlib.sha256(
            pathlib.Path(preflight.__file__).read_bytes()
        ).hexdigest()

        self.assertIn(
            "task_root=/var/lib/noteai/"
            "schema-owner-authority-preflight-v1",
            runner,
        )
        self.assertIn("admin_env=/etc/noteai/admin.env", runner)
        self.assertIn(f"auditor_sha256={auditor_sha256}", runner)
        self.assertIn("prepare | audit", runner)
        self.assertIn("--network none", runner)
        self.assertIn("--network host", runner)
        self.assertIn("package_manifest_sha", runner)
        self.assertIn("SAFE_OWNER_AUTHORITY_PREFLIGHT", runner)
        self.assertIn("automatic_retry=0", runner)
        self.assertIn('"owner_activation_command_count":1', runner)
        self.assertNotIn("source \"${admin_env}\"", runner)
        self.assertNotIn("IFS= read -r database_url", runner)
        self.assertNotIn("-e NOTEAI_", runner)
        self.assertNotIn("postgres" + "ql://", runner)


if __name__ == "__main__":
    unittest.main()
