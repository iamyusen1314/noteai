import contextlib
import hashlib
import io
import pathlib
import unittest
from unittest import mock

from tools import production_first_launch_role_risk_audit as risk_audit


class ProductionFirstLaunchRoleRiskAuditTests(unittest.TestCase):
    def test_source_registry_is_exact_and_secret_free(self):
        registry = risk_audit._source_registry()

        self.assertEqual(
            tuple(registry),
            ("executor", "acl", *(
                f"{number:04d}" for number in range(1, 17)
            )),
        )
        for digest in registry.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_no_dsn_is_proven_preconnect(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                risk_audit,
                "_connect",
                side_effect=AssertionError("must not connect"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            code = risk_audit.main(database_url=None)

        self.assertEqual(code, 2)
        self.assertIn("incident_class=PRE_CONNECT", stderr.getvalue())
        self.assertIn("database_connected=0", stderr.getvalue())

    def test_risk_ids_and_profile_are_not_runtime_configurable(self):
        self.assertEqual(
            risk_audit.RISK_PROFILE,
            "FIRST_LAUNCH_LEGACY_ROLE_RISK_V1",
        )
        self.assertEqual(len(risk_audit.RISK_IDS), 2)
        source = risk_audit.Path(risk_audit.__file__).read_text(
            encoding="utf-8"
        )
        self.assertNotIn("os.environ", source)
        self.assertIn("SET TRANSACTION READ ONLY", source)
        self.assertIn("WITH GRANT OPTION", source)
        self.assertIn("session_user <> 'noteai_xhs'", source)
        self.assertIn("business_row_values_read", source)

    def test_runner_reads_existing_root_env_without_secret_argv_or_env(self):
        runner_path = (
            pathlib.Path(risk_audit.__file__).resolve().parent
            / "production_first_launch_role_risk_audit_runner.sh"
        )
        runner = runner_path.read_text(encoding="utf-8")
        auditor_sha = hashlib.sha256(
            pathlib.Path(risk_audit.__file__).read_bytes()
        ).hexdigest()

        self.assertIn(f"auditor_sha256={auditor_sha}", runner)
        self.assertIn("api_env=/etc/noteai/api.env", runner)
        self.assertIn("database_url=\"${env_line#DATABASE_URL=}\"", runner)
        self.assertIn("unset database_url env_line", runner)
        self.assertNotIn("-e NOTEAI_", runner)
        self.assertNotIn("postgresql://", runner)
        self.assertIn("--network host", runner)
        self.assertIn("SAFE_ROLE_RISK_RUN", runner)


if __name__ == "__main__":
    unittest.main()
