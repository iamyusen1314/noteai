import contextlib
import hashlib
import io
import pathlib
import unittest
from unittest import mock

from tools import production_schema_privileged_owner_preflight as preflight


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return list(self.rows)


class PrivilegedOwnerConnection:
    def __init__(
        self,
        *,
        activation_error=None,
        session_overrides=None,
        state_overrides=None,
    ):
        self.calls = []
        self.activation_error = activation_error
        self.session_overrides = session_overrides or {}
        self.state_overrides = state_overrides or {}

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split())
        self.calls.append((normalized, params))
        if normalized == "SET LOCAL ROLE noteai_admin":
            if self.activation_error is not None:
                raise self.activation_error
            return FakeResult()
        if normalized.startswith("WITH executor AS"):
            session = {
                "default_ro": True,
                "transaction_ro": True,
                "identity_unchanged": True,
                "executor_not_runtime": True,
                "executor_is_expected_task_account": True,
                "executor_is_owner": False,
                "executor_non_superuser": True,
                "executor_can_login": True,
                "executor_rds_privileged": True,
                "owner_activation_capable": True,
                "managed_role_owner_activation_capable": True,
                "transient_executor_dependency_count": 0,
                "executor_shared_dependency_count": 0,
                "unexpected_runtime_membership_count": 0,
                "direct_managed_privileged_membership_count": 1,
                "unexpected_direct_membership_count": 0,
                "direct_owner_membership_count": 0,
                "direct_owner_set_membership_count": 0,
            }
            session.update(self.session_overrides)
            return FakeResult([session])
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


class ProductionSchemaPrivilegedOwnerPreflightTests(unittest.TestCase):
    def test_source_registry_and_new_identity_are_exact(self):
        registry = preflight._source_registry()

        self.assertEqual(preflight.TASK_ID, (
            "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-"
            "PRIVILEGED-OWNER-PREFLIGHT-005"
        ))
        self.assertEqual(
            preflight.APPLICATION_NAME,
            "noteai_schema_privileged_owner_preflight_v2",
        )
        self.assertEqual(
            preflight.TASK_ACCOUNT_NAME,
            "noteai_schema_task_owner_pf_005",
        )
        self.assertEqual(
            preflight.MANAGED_PRIVILEGED_ROLE,
            "pg_rds_superuser",
        )
        self.assertEqual(len(registry), 22)
        self.assertIn("base_auditor", registry)
        for digest in registry.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_contract_requires_managed_privilege_without_native_superuser(self):
        source = pathlib.Path(preflight.__file__).read_text(encoding="utf-8")

        self.assertIn("managed_privileged_role AS", preflight.SESSION_SQL)
        self.assertIn("WHERE rolname = %s", preflight.SESSION_SQL)
        self.assertIn("executor_non_superuser", preflight.SESSION_SQL)
        self.assertIn("executor_rds_privileged", preflight.SESSION_SQL)
        self.assertIn(
            "direct_managed_privileged_membership_count",
            preflight.SESSION_SQL,
        )
        self.assertIn(
            "unexpected_direct_membership_count",
            preflight.SESSION_SQL,
        )
        self.assertIn(
            "executor_shared_dependency_count",
            preflight.SESSION_SQL,
        )
        self.assertIn("direct_owner_set_membership_count", (
            preflight.SESSION_SQL
        ))
        self.assertEqual(preflight.SESSION_SQL.count("%s"), 10)
        self.assertEqual(preflight.base.OWNER_CONTRACT_SQL.count("%s"), 6)
        self.assertEqual(preflight.base.PRODUCTION_STATE_SQL.count("%s"), 8)
        self.assertIn(
            "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
            source,
        )
        self.assertIn("SET LOCAL ROLE", source)
        for verb in (
            "INSERT", "UPDATE", "DELETE", "ALTER",
            "CREATE", "DROP", "GRANT", "REVOKE",
        ):
            self.assertNotIn(f'conn.execute("{verb} ', source)

    def test_exact_privileged_path_is_verified_and_rolled_back(self):
        connection = PrivilegedOwnerConnection()

        result = preflight.collect_privileged_owner_authority(connection)

        self.assertEqual(
            result["status"],
            "privileged_owner_authority_verified",
        )
        self.assertEqual(result["database_connection_count"], 1)
        self.assertEqual(result["database_write_count"], 0)
        self.assertTrue(result["transaction_rolled_back"])
        self.assertTrue(result["acceptance"]["session"])
        statements = [statement for statement, _params in connection.calls]
        self.assertEqual(
            statements[0],
            "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
        )
        self.assertIn("SET LOCAL ROLE noteai_admin", statements)
        self.assertEqual(statements[-1], "ROLLBACK")
        session_call = next(
            call
            for call in connection.calls
            if call[0].startswith("WITH executor AS")
        )
        self.assertEqual(session_call[1], (
            preflight.MANAGED_PRIVILEGED_ROLE,
            list(preflight.RUNTIME_ROLES),
            preflight.TASK_ACCOUNT_NAME,
            preflight.MIGRATION_OWNER_ROLE,
            preflight.MIGRATION_OWNER_ROLE,
            preflight.MIGRATION_OWNER_ROLE,
            list(preflight.RUNTIME_ROLES),
            list(preflight.RUNTIME_ROLES),
            preflight.MIGRATION_OWNER_ROLE,
            preflight.MIGRATION_OWNER_ROLE,
        ))
        owner_call = next(
            call
            for call in connection.calls
            if call[0].startswith("WITH owner_role AS")
        )
        self.assertEqual(owner_call[1], (
            preflight.MIGRATION_OWNER_ROLE,
            preflight.MIGRATION_OWNER_ROLE,
            preflight.MIGRATION_OWNER_ROLE,
            list(preflight.RUNTIME_ROLES),
            preflight.MIGRATION_OWNER_ROLE,
            preflight.MIGRATION_OWNER_ROLE,
        ))
        state_call = next(
            call
            for call in connection.calls
            if call[0].startswith("WITH ledger AS")
        )
        self.assertEqual(state_call[1], (
            list(preflight.RUNTIME_ROLES),
            list(preflight.RUNTIME_ROLES),
            list(preflight.RUNTIME_ROLES),
            preflight.MIGRATION_OWNER_ROLE,
            list(preflight.LEGACY_LEDGER_NAMES),
            list(preflight.LEGACY_TABLES),
            list(preflight.LEGACY_SEQUENCES),
            list(preflight.NEW_RUNTIME_ROLES),
        ))

    def test_privilege_or_state_drift_is_rejected(self):
        for session_drift in (
            {"executor_rds_privileged": False},
            {"executor_non_superuser": False},
            {"executor_is_expected_task_account": False},
            {"executor_is_owner": True},
            {"managed_role_owner_activation_capable": False},
            {"direct_managed_privileged_membership_count": 0},
            {"unexpected_direct_membership_count": 1},
            {"direct_owner_membership_count": 1},
            {"direct_owner_set_membership_count": 1},
            {"unexpected_runtime_membership_count": 1},
            {"transient_executor_dependency_count": 1},
            {"executor_shared_dependency_count": 1},
        ):
            with self.subTest(session_drift=session_drift):
                result = preflight.collect_privileged_owner_authority(
                    PrivilegedOwnerConnection(
                        session_overrides=session_drift,
                    )
                )
                self.assertEqual(result["status"], "state_changed")
        result = preflight.collect_privileged_owner_authority(
            PrivilegedOwnerConnection(
                state_overrides={"ledger_count": 9},
            )
        )
        self.assertEqual(result["status"], "state_changed")

    def test_activation_failure_is_connected_known_and_rolled_back(self):
        connection = PrivilegedOwnerConnection(
            activation_error=RuntimeError("must-not-render"),
        )

        with self.assertRaises(
            preflight.base.OwnerAuthorityPreflightError
        ) as raised:
            preflight.collect_privileged_owner_authority(connection)

        self.assertEqual(raised.exception.code, "owner_activation_failed")
        self.assertEqual(
            raised.exception.incident_class,
            "CONNECTED_KNOWN",
        )
        self.assertEqual(connection.calls[-1][0], "ROLLBACK")
        self.assertNotIn("must-not-render", str(raised.exception))

    def test_protected_uri_replacement_is_memory_only_and_exact(self):
        topology = preflight.sanitize_admin_database_topology(
            "postgresql://old-user:old-pass@db.internal.invalid:5432/noteai"
            "?sslmode=require",
        )
        result = preflight.build_task_database_url(
            topology,
            "new pass:/?#[]@",
        )

        self.assertEqual(
            topology,
            "postgresql://db.internal.invalid:5432/noteai"
            "?sslmode=require",
        )
        self.assertTrue(result.startswith(
            "postgresql://noteai_schema_task_owner_pf_005:"
        ))
        self.assertIn("@db.internal.invalid:5432/noteai?sslmode=require", result)
        self.assertNotIn("old-user", result)
        self.assertNotIn("old-pass", result)
        self.assertNotIn("new pass:/?#[]@", result)

    def test_topology_rejects_redirect_and_credential_query_parameters(self):
        invalid_values = (
            "postgresql://user:pass@db.internal.invalid/noteai"
            "?password=hidden",
            "postgresql://user:pass@db.internal.invalid/noteai"
            "?host=elsewhere.invalid",
            "postgresql://user:pass@one.invalid,two.invalid/noteai",
            "postgresql://user:pass@db.internal.invalid/noteai%0Aother",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(
                    preflight.base.OwnerAuthorityPreflightError
                ):
                    preflight.sanitize_admin_database_topology(value)

    def test_protected_input_failures_are_preconnect_and_secret_free(self):
        stderr = io.StringIO()
        protected = b"must-not-render"

        with contextlib.redirect_stderr(stderr):
            code = preflight.main_from_protected_input(protected)

        self.assertEqual(code, 2)
        self.assertIn("incident_class=PRE_CONNECT", stderr.getvalue())
        self.assertNotIn("must-not-render", stderr.getvalue())

    def test_protected_input_success_never_reaches_output(self):
        stdout = io.StringIO()
        admin_uri = (
            b"postgresql://old:old@db.internal.invalid:5432/noteai"
        )
        topology = preflight.sanitize_admin_database_topology(
            admin_uri.decode("utf-8")
        ).encode("utf-8")
        password = b"must-not-render-password"
        with (
            mock.patch.object(preflight, "main", return_value=0) as main,
            contextlib.redirect_stdout(stdout),
        ):
            code = preflight.main_from_protected_input(
                topology + b"\x00" + password
            )

        self.assertEqual(code, 0)
        passed_url = main.call_args.kwargs["database_url"]
        self.assertNotIn("old:old", passed_url)
        self.assertNotIn("must-not-render-password", stdout.getvalue())

    def test_runner_is_new_fixed_encrypted_stdin_path(self):
        runner_path = (
            pathlib.Path(preflight.__file__).resolve().parent
            / "production_schema_privileged_owner_preflight_runner.sh"
        )
        runner = runner_path.read_text(encoding="utf-8")
        auditor_sha256 = hashlib.sha256(
            pathlib.Path(preflight.__file__).read_bytes()
        ).hexdigest()

        self.assertIn(
            "task_root=/var/lib/noteai/"
            "schema-privileged-owner-preflight-v2",
            runner,
        )
        self.assertIn("admin_env=/etc/noteai/admin.env", runner)
        self.assertIn("transport_private.pem", runner)
        self.assertIn("task_password.enc", runner)
        self.assertIn(f"auditor_sha256={auditor_sha256}", runner)
        self.assertIn("prepare | audit", runner)
        self.assertIn("--network none", runner)
        self.assertIn("--network host", runner)
        self.assertIn("rsa_padding_mode:oaep", runner)
        self.assertIn("rsa_oaep_md:sha256", runner)
        self.assertIn("main_from_protected_input", runner)
        self.assertIn("sanitize_admin_topology", runner)
        self.assertIn("validate_result", runner)
        self.assertIn("SAFE_PRIVILEGED_OWNER_PREFLIGHT", runner)
        self.assertIn("automatic_retry=0", runner)
        self.assertIn("cleanup_required=1", runner)
        self.assertIn("decrypt-error.log", runner)
        self.assertIn("audit-error.log", runner)
        self.assertNotIn("source \"${admin_env}\"", runner)
        self.assertNotIn("IFS= read -r", runner)
        self.assertNotIn("-e NOTEAI_", runner)
        self.assertNotIn("postgres" + "ql://", runner)


if __name__ == "__main__":
    unittest.main()
