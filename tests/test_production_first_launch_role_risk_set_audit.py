import contextlib
import hashlib
import io
import pathlib
import unittest
from unittest import mock

from tools import production_first_launch_role_risk_set_audit as set_audit


class ProductionFirstLaunchRoleRiskSetAuditTests(unittest.TestCase):
    def test_source_registry_and_fixed_ids_are_exact(self):
        registry = set_audit._source_registry()

        self.assertEqual(set_audit.AUDIT_ID, (
            "PROD-FIRST-LAUNCH-LEGACY-ROLE-RISK-SET-AUDIT-002"
        ))
        self.assertEqual(set_audit.RUN_ID, (
            "PROD-FIRST-LAUNCH-LEGACY-ROLE-RISK-SET-AUDIT-RUN-001"
        ))
        self.assertEqual(
            set_audit.APPLICATION_NAME,
            "noteai_role_risk_set_audit_v2",
        )
        self.assertEqual(len(set_audit.RISK_IDS), 2)
        self.assertEqual(set_audit.STAGE_ORDER, (
            "session",
            "ledger_inventory",
            "role_graph",
            "xhs_acl",
            "rollback",
        ))
        self.assertEqual(len(registry), 21)
        for digest in registry.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_sql_contract_is_four_fixed_set_queries(self):
        self.assertIn(
            "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
            pathlib.Path(set_audit.__file__).read_text(encoding="utf-8"),
        )
        self.assertIn("session_user <> 'noteai_xhs'", set_audit.SESSION_SQL)
        self.assertIn(
            "retention_backfill_source_count",
            set_audit.LEDGER_INVENTORY_SQL,
        )
        self.assertIn("app_high_privilege_inheritance_count", (
            set_audit.ROLE_GRAPH_SQL
        ))
        self.assertIn("column_mismatch_count", set_audit.XHS_ACL_SQL)
        self.assertIn("database_grantable_count", set_audit.XHS_ACL_SQL)
        self.assertIn("schema_grantable_count", set_audit.XHS_ACL_SQL)
        self.assertIn("default_acl_entry_count", set_audit.XHS_ACL_SQL)
        self.assertIn("public_function_execute_count", set_audit.XHS_ACL_SQL)
        source = pathlib.Path(set_audit.__file__).read_text(encoding="utf-8")
        self.assertIn(
            'role_graph["membership_inherit"] is False',
            source,
        )

    def test_no_dsn_is_preconnect_without_connection_attempt(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                set_audit,
                "_connect",
                side_effect=AssertionError("must not connect"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            code = set_audit.main(database_url=None)

        self.assertEqual(code, 2)
        self.assertIn("incident_class=PRE_CONNECT", stderr.getvalue())
        self.assertIn("database_connected=0", stderr.getvalue())

    def test_runner_uses_stdin_and_no_service_env_or_secret_argv(self):
        runner_path = (
            pathlib.Path(set_audit.__file__).resolve().parent
            / "production_first_launch_role_risk_set_audit_runner.sh"
        )
        runner = runner_path.read_text(encoding="utf-8")
        auditor_sha256 = hashlib.sha256(
            pathlib.Path(set_audit.__file__).read_bytes()
        ).hexdigest()

        self.assertIn(
            "task_root=/var/lib/noteai/role-risk-set-audit-v2",
            runner,
        )
        self.assertIn(f"auditor_sha256={auditor_sha256}", runner)
        self.assertIn("IFS= read -r database_url", runner)
        self.assertIn("unset database_url", runner)
        self.assertNotIn("/etc/noteai/api.env", runner)
        self.assertNotIn("-e NOTEAI_", runner)
        self.assertNotIn("postgresql://", runner)
        self.assertIn("--network none", runner)
        self.assertIn("--network host", runner)
        self.assertIn("SAFE_ROLE_RISK_SET_RUN", runner)


if __name__ == "__main__":
    unittest.main()
