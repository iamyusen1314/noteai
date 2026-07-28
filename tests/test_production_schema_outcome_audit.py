import contextlib
import io
import os
import unittest
from unittest import mock

from tools import production_schema_outcome_audit as outcome_audit
from tools import production_schema_roles as schema_roles


def _observation(**overrides):
    value = {
        "ledger_versions": outcome_audit.EXPECTED_VERSIONS,
        "legacy_ledger_names_exact": False,
        "complete_ledger_names_exact": True,
        "canonical_migration_name_count": 16,
        "sha_column_count": 1,
        "sha_data_type": "text",
        "sha_nullable": "NO",
        "sha_constraint_count": 1,
        "sha_constraint_exact_count": 1,
        "matching_migration_hash_count": 16,
        "tables": outcome_audit.EXPECTED_TABLES,
        "sequences": outcome_audit.EXPECTED_SEQUENCES,
        "present_runtime_roles": outcome_audit.EXPECTED_PRESENT_RUNTIME_ROLES,
        "new_runtime_role_count": 6,
        "new_runtime_login_count": 0,
        "runtime_elevation_count": 1,
        "runtime_membership_count": 1,
        "accepted_role_risk_exact": True,
        "app_incoming_membership_count": 0,
        "app_high_privilege_inheritance_count": 0,
        "executor_not_xhs": True,
        "runtime_ownership_count": 0,
        "trends_seed_count": 1,
        "trends_seed_exact_count": 1,
        "dispatcher_seed_count": 1,
        "dispatcher_seed_exact_count": 1,
        "retention_row_count": 0,
        "full_contract_matrix_verified": True,
        "table_privilege_checks": 3136,
        "table_grant_option_count": 0,
        "column_privilege_checks": 1,
        "column_grant_option_count": 0,
        "sequence_privilege_checks": 120,
        "sequence_grant_option_count": 0,
        "default_acl_entry_count": 0,
    }
    value.update(overrides)
    return value


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class CommittedConnection:
    def __init__(self):
        self.calls = []

    def transaction(self):
        return FakeTransaction()

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split())
        self.calls.append((normalized, params))
        if normalized == "SHOW default_transaction_read_only":
            return FakeResult([("on",)])
        if normalized == "SHOW transaction_read_only":
            return FakeResult([("on",)])
        if "FROM information_schema.tables" in normalized:
            return FakeResult([
                {"table_name": table}
                for table in outcome_audit.EXPECTED_TABLES
            ])
        if "FROM information_schema.columns" in normalized:
            return FakeResult([
                {
                    "column_name": "version",
                    "data_type": "text",
                    "is_nullable": "NO",
                },
                {
                    "column_name": "sha256",
                    "data_type": "text",
                    "is_nullable": "NO",
                },
            ])
        if "FROM pg_constraint" in normalized:
            return FakeResult([{
                "contype": "c",
                "convalidated": True,
                "definition": "CHECK ((sha256 ~ "
                "'^[0-9a-f]{64}$'::text))",
            }])
        if normalized.startswith("SELECT version,sha256"):
            names, hashes = outcome_audit._migration_manifest()
            return FakeResult([
                {
                    "version": name,
                    "sha256": hashes[name.split("_", 1)[0]],
                }
                for name in names
            ])
        if "FROM information_schema.sequences" in normalized:
            return FakeResult([
                {"sequence_name": sequence}
                for sequence in outcome_audit.EXPECTED_SEQUENCES
            ])
        if "FROM pg_roles WHERE rolname" in normalized:
            return FakeResult([
                {
                    "rolname": role,
                    "rolsuper": False,
                    "rolinherit": role == "noteai_app",
                    "rolcreaterole": False,
                    "rolcreatedb": False,
                    "rolcanlogin": role in outcome_audit.LEGACY_RUNTIME_ROLES,
                    "rolreplication": False,
                    "rolbypassrls": False,
                }
                for role in outcome_audit.EXPECTED_PRESENT_RUNTIME_ROLES
            ])
        if "FROM pg_auth_members membership JOIN pg_roles granted_role" in normalized:
            return FakeResult([{
                "granted_name": "noteai_xhs",
                "member_name": "noteai_admin",
                "admin_option": True,
                "inherit_option": False,
                "set_option": False,
            }])
        if "WHERE member.rolname='noteai_app'" in normalized:
            return FakeResult([(0,)])
        if "AND pg_has_role('noteai_app'" in normalized:
            return FakeResult([(0,)])
        if "SELECT session_user <> 'noteai_xhs'" in normalized:
            return FakeResult([(True,)])
        if normalized.startswith("SELECT ((SELECT COUNT(*) FROM pg_class"):
            return FakeResult([(0,)])
        if "FROM public.xhs_trends_service_state" in normalized:
            return FakeResult([(1,)])
        if "FROM public.ai_dispatch_state" in normalized:
            return FakeResult([(1,)])
        if normalized == "SELECT COUNT(*) FROM public.content_retention":
            return FakeResult([(0,)])
        return FakeResult()


class ProductionSchemaOutcomeAuditTests(unittest.TestCase):
    def test_static_inventory_matches_executor_without_import_dependency(self):
        self.assertEqual(
            outcome_audit.EXPECTED_VERSIONS,
            schema_roles.EXPECTED_VERSIONS,
        )
        self.assertEqual(
            outcome_audit.EXPECTED_TABLES,
            schema_roles.EXPECTED_TABLES,
        )
        self.assertEqual(
            outcome_audit.EXPECTED_SEQUENCES,
            tuple(sorted(schema_roles.EXPECTED_PUBLIC_SEQUENCES)),
        )
        self.assertEqual(
            outcome_audit.RUNTIME_ROLES,
            schema_roles.RUNTIME_ROLES,
        )
        source = outcome_audit.Path(outcome_audit.__file__).read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'membership_rows[0]["inherit_option"] is False',
            source,
        )
        self.assertEqual(len(outcome_audit.LEGACY_TABLES), 30)
        self.assertEqual(len(outcome_audit.EXPECTED_TABLES), 56)

    def test_exact_committed_state_is_classified(self):
        self.assertEqual(
            outcome_audit._classify(_observation()),
            "COMMITTED",
        )

    def test_exact_legacy_state_is_classified_as_rolled_back(self):
        legacy = _observation(
            ledger_versions=outcome_audit.LEGACY_VERSIONS,
            legacy_ledger_names_exact=True,
            complete_ledger_names_exact=False,
            canonical_migration_name_count=8,
            sha_column_count=0,
            sha_data_type=None,
            sha_nullable=None,
            sha_constraint_count=0,
            sha_constraint_exact_count=0,
            matching_migration_hash_count=0,
            tables=outcome_audit.LEGACY_TABLES,
            present_runtime_roles=outcome_audit.LEGACY_RUNTIME_ROLES,
            new_runtime_role_count=0,
            trends_seed_count=None,
            trends_seed_exact_count=None,
            dispatcher_seed_count=None,
            dispatcher_seed_exact_count=None,
            retention_row_count=None,
            full_contract_matrix_verified=None,
            table_privilege_checks=None,
            table_grant_option_count=None,
            column_privilege_checks=None,
            column_grant_option_count=None,
            sequence_privilege_checks=None,
            sequence_grant_option_count=None,
            default_acl_entry_count=None,
        )
        self.assertEqual(outcome_audit._classify(legacy), "ROLLED_BACK")

    def test_any_partial_or_elevated_state_is_conflict(self):
        for mismatch in (
            {"ledger_versions": outcome_audit.EXPECTED_VERSIONS[:-1]},
            {"complete_ledger_names_exact": False},
            {"matching_migration_hash_count": 15},
            {"sha_constraint_exact_count": 0},
            {"tables": outcome_audit.EXPECTED_TABLES[:-1]},
            {"new_runtime_login_count": 1},
            {"runtime_elevation_count": 2},
            {"runtime_membership_count": 2},
            {"accepted_role_risk_exact": False},
            {"app_incoming_membership_count": 1},
            {"app_high_privilege_inheritance_count": 1},
            {"runtime_ownership_count": 1},
            {"trends_seed_exact_count": 0},
            {"dispatcher_seed_exact_count": 0},
            {"retention_row_count": 1},
            {"full_contract_matrix_verified": False},
            {"table_grant_option_count": 1},
            {"column_grant_option_count": 1},
            {"sequence_grant_option_count": 1},
            {"default_acl_entry_count": 1},
        ):
            with self.subTest(mismatch=mismatch):
                self.assertEqual(
                    outcome_audit._classify(_observation(**mismatch)),
                    "CONFLICT",
                )

    def test_collection_forces_read_only_and_reads_only_aggregates(self):
        connection = CommittedConnection()
        with mock.patch.object(
            outcome_audit.schema_role_contract,
            "validate_contract",
            return_value={
                "table_privilege_checks": 3136,
                "table_grant_option_count": 0,
                "column_privilege_checks": 1,
                "column_grant_option_count": 0,
                "sequence_privilege_checks": 120,
                "sequence_grant_option_count": 0,
                "default_acl_entry_count": 0,
            },
        ):
            result = outcome_audit.collect_outcome(connection)

        self.assertEqual(result["database_outcome"], "COMMITTED")
        self.assertTrue(result["read_only"])
        self.assertTrue(
            result["observation"]["full_contract_matrix_verified"]
        )
        self.assertEqual(result["observation"]["business_row_values_read"], 0)
        statements = [statement for statement, _params in connection.calls]
        self.assertEqual(statements[0], "SET TRANSACTION READ ONLY")
        self.assertIn("SHOW default_transaction_read_only", statements)
        self.assertIn("SHOW transaction_read_only", statements)
        self.assertFalse(any(
            statement.startswith(("INSERT ", "UPDATE ", "DELETE ", "ALTER "))
            for statement in statements
        ))

    def test_local_manifest_failure_happens_before_connection(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                outcome_audit,
                "_migration_manifest",
                side_effect=outcome_audit.OutcomeAuditError(
                    "migration_set",
                    stage="local_source",
                ),
            ),
            mock.patch.object(
                outcome_audit,
                "_connect",
                side_effect=AssertionError("connection must not be attempted"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = outcome_audit.main()

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_schema_outcome_audit=FAIL "
            "stage=local_source incident_class=PRE_CONNECT "
            "database_connected=0 connection_attempted=0 "
            "database_outcome=NOT_CONNECTED retry_same_path=0",
        )

    def test_missing_dsn_fails_before_connection_without_secret_output(self):
        stderr = io.StringIO()
        with (
            mock.patch.dict(
                os.environ,
                {outcome_audit.DATABASE_URL_ENV: ""},
                clear=False,
            ),
            mock.patch.object(
                outcome_audit,
                "psycopg",
                object(),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = outcome_audit.main()

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_schema_outcome_audit=FAIL "
            "stage=connect incident_class=PRE_CONNECT "
            "database_connected=0 connection_attempted=0 "
            "database_outcome=NOT_CONNECTED retry_same_path=0",
        )

    def test_connect_exception_is_connected_unknown_not_preconnect(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                outcome_audit,
                "_connect",
                side_effect=RuntimeError("must not be rendered"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = outcome_audit.main()

        self.assertEqual(result, 1)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_schema_outcome_audit=FAIL "
            "stage=connect incident_class=CONNECTED_UNKNOWN "
            "database_connected=0 connection_attempted=1 "
            "database_outcome=UNKNOWN no_retry=1",
        )


if __name__ == "__main__":
    unittest.main()
