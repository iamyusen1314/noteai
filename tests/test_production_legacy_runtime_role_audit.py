import contextlib
import hashlib
import io
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import production_legacy_runtime_role_audit as role_audit


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


class ExactConflictConnection:
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
        if normalized == "SELECT current_user":
            return FakeResult([("task account must stay private",)])
        if "FROM information_schema.columns" in normalized:
            return FakeResult([(0,)])
        if normalized.startswith("SELECT version FROM"):
            return FakeResult([
                {"version": version}
                for version in role_audit.EXPECTED_LEDGER_NAMES
            ])
        if "FROM information_schema.tables" in normalized:
            return FakeResult([
                {"table_name": table}
                for table in role_audit.LEGACY_TABLES
            ])
        if "FROM information_schema.sequences" in normalized:
            return FakeResult([
                {"sequence_name": sequence}
                for sequence in role_audit.EXPECTED_SEQUENCES
            ])
        if "FROM pg_catalog.pg_roles WHERE rolname" in normalized:
            return FakeResult([
                {
                    "rolname": "noteai_app",
                    "rolsuper": False,
                    "rolinherit": True,
                    "rolcreaterole": False,
                    "rolcreatedb": False,
                    "rolcanlogin": True,
                    "rolreplication": False,
                    "rolbypassrls": False,
                },
                {
                    "rolname": "noteai_xhs",
                    "rolsuper": False,
                    "rolinherit": False,
                    "rolcreaterole": False,
                    "rolcreatedb": False,
                    "rolcanlogin": True,
                    "rolreplication": False,
                    "rolbypassrls": False,
                },
            ])
        if "FROM pg_catalog.pg_auth_members" in normalized:
            return FakeResult([{
                "granted_name": "provider_control_role",
                "granted_canlogin": False,
                "granted_super": False,
                "member_name": "noteai_app",
                "member_canlogin": True,
                "member_super": False,
                "admin_option": False,
                "inherit_option": None,
                "set_option": None,
            }])
        if normalized.startswith(
            "SELECT ((SELECT COUNT(*) FROM pg_catalog.pg_class"
        ):
            return FakeResult([(0,)])
        return FakeResult()

    def close(self):
        return None


class ProductionLegacyRuntimeRoleAuditTests(unittest.TestCase):
    def _runner_fixture(self):
        fixture = tempfile.TemporaryDirectory()
        root = pathlib.Path(fixture.name)
        task_root = root / "task"
        source_root = task_root / "source"
        tools_root = source_root / "tools"
        tools_root.mkdir(parents=True)
        source = pathlib.Path(role_audit.__file__).read_bytes()
        source_path = tools_root / "production_legacy_runtime_role_audit.py"
        source_path.write_bytes(source)
        source_sha = hashlib.sha256(source).hexdigest()
        (source_root / "package.sha256").write_text(
            f"{source_sha}  tools/production_legacy_runtime_role_audit.py\n",
            encoding="utf-8",
        )
        (task_root / "transport_private.pem").write_text(
            "fixture-key\n",
            encoding="utf-8",
        )
        (task_root / "database_url.enc").write_bytes(b"x" * 384)

        bin_root = root / "bin"
        bin_root.mkdir()
        openssl = bin_root / "openssl"
        openssl.write_text(
            "#!/usr/bin/env bash\n"
            "if test \"${1:-}\" = pkey; then exit 0; fi\n"
            "if test \"${1:-}\" = pkeyutl; then "
            "printf 'postgresql://redacted.invalid/db'; exit 0; fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        docker = bin_root / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "if test \"${1:-}\" = inspect; then "
            "printf 'fixture-image\\n'; exit 0; fi\n"
            "if test \"${1:-}\" = ps; then\n"
            "  case \" $* \" in *' -a '*)\n"
            "    if test -e \"${FAKE_DOCKER_STATE}\" "
            "&& test \"${FAKE_DOCKER_RESIDUAL:-0}\" = 1; then "
            "printf 'residual\\n'; fi\n"
            "    exit 0;;\n"
            "  esac\n"
            "  printf 'fixture-api\\n'; exit 0\n"
            "fi\n"
            "if test \"${1:-}\" = run; then\n"
            "  dd of=/dev/null bs=4096 2>/dev/null || :\n"
            "  : >\"${FAKE_DOCKER_STATE}\"\n"
            "  code=\"${FAKE_DOCKER_RUN_EXIT:-127}\"\n"
            "  if test \"$code\" = 0 || test \"$code\" = 30; then\n"
            "    printf '%s' '{\"status\":\"identified\","
            "\"incident_class\":\"CONNECTED_KNOWN\"}'\n"
            "  elif test \"$code\" = 2; then\n"
            "    printf '%s\\n' "
            "'production_legacy_runtime_role_audit=FAIL "
            "stage=connect incident_class=PRE_CONNECT "
            "database_connected=0 connection_attempted=0 "
            "database_outcome=NOT_CONNECTED retry_same_path=0' >&2\n"
            "  fi\n"
            "  exit \"$code\"\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        openssl.chmod(0o755)
        docker.chmod(0o755)

        runner_source = (
            role_audit.ROOT
            / "tools"
            / "production_legacy_runtime_role_audit_runner.sh"
        ).read_text(encoding="utf-8")
        runner_source = runner_source.replace(
            "/var/lib/noteai/legacy-role-audit",
            str(task_root),
        )
        runner_path = root / "runner.sh"
        runner_path.write_text(runner_source, encoding="utf-8")
        runner_path.chmod(0o755)
        environment = dict(os.environ)
        environment.update({
            "PATH": f"{bin_root}:{environment.get('PATH', '')}",
            "FAKE_DOCKER_RUN_EXIT": "127",
            "FAKE_DOCKER_RESIDUAL": "0",
            "FAKE_DOCKER_STATE": str(root / "docker-run.seen"),
        })
        return fixture, task_root, bin_root, runner_path, environment

    def test_runner_uses_memory_only_dsn_and_guarded_classification(self):
        runner = (
            role_audit.ROOT
            / "tools"
            / "production_legacy_runtime_role_audit_runner.sh"
        ).read_text(encoding="utf-8")
        source_sha = hashlib.sha256(
            role_audit.Path(role_audit.__file__).read_bytes()
        ).hexdigest()

        self.assertIn(f"auditor_sha256={source_sha}", runner)
        self.assertIn("database_url=value", runner)
        self.assertNotIn('os.environ["NOTEAI_', runner)
        self.assertIn("runner.prepared", runner)
        self.assertIn("dispatch.started", runner)
        self.assertIn("|| fail_preconnect", runner)
        self.assertIn("|| fail_connected_unknown", runner)
        self.assertIn("production_legacy_runtime_role_audit=FAIL", runner)
        self.assertIn("set -o pipefail", runner)

    def test_runner_preserves_existing_result(self):
        fixture, task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        result_path = task_root / "identity-result.json"
        result_path.write_text("preserve-me", encoding="utf-8")

        completed = subprocess.run(
            [str(runner_path)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(result_path.read_text(encoding="utf-8"), "preserve-me")
        self.assertFalse((task_root / "dispatch.started").exists())

    def test_runner_rm_failure_is_preconnect_without_dispatch(self):
        fixture, task_root, bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        fake_rm = bin_root / "rm"
        fake_rm.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        fake_rm.chmod(0o755)

        completed = subprocess.run(
            [str(runner_path)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("incident_class=PRE_CONNECT", completed.stdout)
        self.assertFalse((task_root / "dispatch.started").exists())

    def test_runner_sentinel_write_failure_is_preconnect(self):
        fixture, task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        source = runner_path.read_text(encoding="utf-8").replace(
            'prepared_sentinel="${task_root}/runner.prepared"',
            'prepared_sentinel="${task_root}/missing/runner.prepared"',
        )
        runner_path.write_text(source, encoding="utf-8")

        completed = subprocess.run(
            [str(runner_path)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertFalse((task_root / "dispatch.started").exists())

    def test_runner_exit_126_and_127_are_proven_preconnect(self):
        for exit_code in ("126", "127"):
            with self.subTest(exit_code=exit_code):
                fixture, task_root, _bin_root, runner_path, environment = (
                    self._runner_fixture()
                )
                try:
                    environment["FAKE_DOCKER_RUN_EXIT"] = exit_code
                    completed = subprocess.run(
                        [str(runner_path)],
                        text=True,
                        capture_output=True,
                        env=environment,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 2)
                    self.assertIn(
                        "incident_class=PRE_CONNECT",
                        completed.stdout,
                    )
                    self.assertTrue((task_root / "dispatch.started").exists())
                finally:
                    fixture.cleanup()

    def test_runner_unclassified_postdispatch_failure_is_unknown(self):
        fixture, task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        environment["FAKE_DOCKER_RUN_EXIT"] = "50"

        completed = subprocess.run(
            [str(runner_path)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("incident_class=CONNECTED_UNKNOWN", completed.stdout)
        self.assertTrue((task_root / "dispatch.started").exists())

    def test_runner_result_hash_failure_is_known_readonly_completion(self):
        fixture, _task_root, bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        real_sha256sum = shutil.which("sha256sum")
        self.assertIsNotNone(real_sha256sum)
        fake_sha256sum = bin_root / "sha256sum"
        fake_sha256sum.write_text(
            "#!/usr/bin/env bash\n"
            "case \" $* \" in *'identity-result.json.tmp'*) exit 1;; esac\n"
            f"exec '{real_sha256sum}' \"$@\"\n",
            encoding="utf-8",
        )
        fake_sha256sum.chmod(0o755)
        environment["FAKE_DOCKER_RUN_EXIT"] = "0"

        completed = subprocess.run(
            [str(runner_path)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 30)
        self.assertIn("database_outcome=READ_ONLY_COMPLETED", completed.stdout)
        self.assertIn("result_recovery_required=1", completed.stdout)

    def test_runner_readonly_completion_with_residual_requires_cleanup(self):
        fixture, _task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        environment["FAKE_DOCKER_RUN_EXIT"] = "0"
        environment["FAKE_DOCKER_RESIDUAL"] = "1"

        completed = subprocess.run(
            [str(runner_path)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 30)
        self.assertIn("database_outcome=READ_ONLY_COMPLETED", completed.stdout)
        self.assertIn("cleanup_required=1", completed.stdout)

    def test_runner_unknown_with_residual_reports_cleanup_required(self):
        fixture, _task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        environment["FAKE_DOCKER_RUN_EXIT"] = "50"
        environment["FAKE_DOCKER_RESIDUAL"] = "1"

        completed = subprocess.run(
            [str(runner_path)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("incident_class=CONNECTED_UNKNOWN", completed.stdout)
        self.assertIn("cleanup_required=1", completed.stdout)

    def test_exact_source_set_remains_pinned_and_current_drift_fails_closed(
        self,
    ):
        self.assertEqual(len(role_audit.EXPECTED_SOURCE_SHA256), 18)
        with self.assertRaises(role_audit.LegacyRoleAuditError) as raised:
            role_audit._validate_local_source()

        self.assertEqual(raised.exception.code, "source_drift")
        self.assertEqual(raised.exception.stage, "local_source")

    def test_exact_conflict_is_identified_without_account_names(self):
        connection = ExactConflictConnection()

        result = role_audit.collect_identity(connection)

        self.assertEqual(result["status"], "identified")
        self.assertEqual(result["incident_class"], "CONNECTED_KNOWN")
        self.assertEqual(result["database_write_count"], 0)
        self.assertEqual(result["business_row_values_read"], 0)
        self.assertEqual(
            result["observation"]["elevated_identity"],
            {
                "runtime_role": "legacy_api_runtime",
                "attribute": "rolinherit",
            },
        )
        self.assertEqual(
            result["observation"]["membership_identity"],
            {
                "direction": "runtime_as_member",
                "granted_endpoint": {
                    "category": "other_nonlogin",
                    "login": False,
                    "superuser": False,
                },
                "member_endpoint": {
                    "category": "legacy_api_runtime",
                    "login": True,
                    "superuser": False,
                },
                "admin_option": False,
                "inherit_option": None,
                "set_option": None,
            },
        )
        rendered = str(result)
        self.assertNotIn("task account must stay private", rendered)
        self.assertNotIn("provider_control_role", rendered)
        statements = [statement for statement, _params in connection.calls]
        self.assertEqual(statements[0], "SET TRANSACTION READ ONLY")
        self.assertFalse(any(
            statement.startswith(
                ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "GRANT ", "REVOKE ")
            )
            for statement in statements
        ))

    def test_state_change_is_deterministic_connected_known(self):
        connection = ExactConflictConnection()
        original_execute = connection.execute

        def execute(statement, params=()):
            normalized = " ".join(statement.split())
            if "FROM pg_catalog.pg_auth_members" in normalized:
                return FakeResult([])
            return original_execute(statement, params)

        connection.execute = execute
        result = role_audit.collect_identity(connection)

        self.assertEqual(result["status"], "state_changed")
        self.assertEqual(
            result["observation"]["bidirectional_membership_count"],
            0,
        )

    def test_source_drift_fails_before_connection(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                role_audit,
                "_validate_local_source",
                side_effect=role_audit.LegacyRoleAuditError(
                    "source_drift",
                    stage="local_source",
                ),
            ),
            mock.patch.object(
                role_audit,
                "_connect",
                side_effect=AssertionError("connection must not be attempted"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = role_audit.main(
                database_url="postgresql://not-used.invalid/db"
            )

        self.assertEqual(result, 2)
        self.assertIn("incident_class=PRE_CONNECT", stderr.getvalue())
        self.assertIn("database_connected=0", stderr.getvalue())

    def test_connect_failure_is_unknown_and_secret_free(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                role_audit,
                "_validate_local_source",
                return_value=role_audit.EXPECTED_SOURCE_SHA256,
            ),
            mock.patch.object(
                role_audit,
                "_connect",
                side_effect=RuntimeError("secret must not render"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = role_audit.main(
                database_url="postgresql://redacted.invalid/db"
            )

        self.assertEqual(result, 1)
        self.assertNotIn("secret must not render", stderr.getvalue())
        self.assertIn("incident_class=CONNECTED_UNKNOWN", stderr.getvalue())

    def test_missing_dsn_is_proven_preconnect(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                role_audit,
                "_validate_local_source",
                return_value=role_audit.EXPECTED_SOURCE_SHA256,
            ),
            mock.patch.object(role_audit, "psycopg", object()),
            contextlib.redirect_stderr(stderr),
        ):
            result = role_audit.main(database_url="")

        self.assertEqual(result, 2)
        self.assertIn("incident_class=PRE_CONNECT", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
