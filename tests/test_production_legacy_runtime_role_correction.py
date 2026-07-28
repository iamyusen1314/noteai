import contextlib
import hashlib
import io
import os
import pathlib
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from tools import production_legacy_runtime_role_audit as identity_audit
from tools import production_legacy_runtime_role_correction as correction


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.before = (
            self.connection.elevated,
            self.connection.membership,
        )
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.connection.elevated, self.connection.membership = self.before
        return False


class LegacyConflictConnection:
    def __init__(self):
        self.elevated = True
        self.membership = True
        self.calls = []
        self.closed = False
        self.info = types.SimpleNamespace(
            transaction_status=correction.TransactionStatus.IDLE
        )

    def transaction(self):
        return FakeTransaction(self)

    def close(self):
        self.closed = True

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split())
        self.calls.append((normalized, params))
        if normalized == "SHOW transaction_read_only":
            return FakeResult([("on",)])
        if "FROM information_schema.columns" in normalized:
            return FakeResult([(0,)])
        if normalized.startswith(
            "SELECT version FROM public.schema_migrations"
        ):
            return FakeResult([
                {"version": name}
                for name in correction.EXPECTED_LEDGER_NAMES
            ])
        if "FROM information_schema.tables" in normalized:
            return FakeResult([
                {"table_name": table}
                for table in correction.LEGACY_TABLES
            ])
        if "FROM information_schema.sequences" in normalized:
            return FakeResult([
                {"sequence_name": sequence}
                for sequence in correction.EXPECTED_SEQUENCES
            ])
        if "FROM pg_catalog.pg_roles WHERE rolname" in normalized:
            return FakeResult([
                {
                    "rolname": "noteai_app",
                    "rolsuper": False,
                    "rolinherit": self.elevated,
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
        if "FROM pg_catalog.pg_auth_members membership" in normalized:
            if not self.membership:
                return FakeResult()
            return FakeResult([{
                "granted_name": "noteai_xhs",
                "granted_canlogin": True,
                "granted_super": False,
                "member_name": "noteai_admin",
                "member_canlogin": True,
                "member_super": False,
                "grantor_sql": '"provider_control_role"',
                "grantor_canlogin": True,
                "grantor_super": True,
                "executor_is_grantor": False,
                "executor_super": True,
                "executor_createrole": True,
                "executor_admin_on_app": False,
                "admin_option": True,
                "inherit_option": True,
                "set_option": False,
            }])
        if normalized.startswith(
            "SELECT ((SELECT COUNT(*) FROM pg_catalog.pg_class"
        ):
            return FakeResult([(0,)])
        if normalized == "ALTER ROLE noteai_app NOINHERIT":
            self.elevated = False
            return FakeResult()
        if normalized.startswith("REVOKE noteai_xhs FROM noteai_admin"):
            self.membership = False
            return FakeResult()
        return FakeResult()


class ProductionLegacyRuntimeRoleCorrectionTests(unittest.TestCase):
    def _runner_fixture(self):
        fixture = tempfile.TemporaryDirectory()
        root = pathlib.Path(fixture.name)
        task_root = root / "task"
        source_root = task_root / "source"
        tools_root = source_root / "tools"
        tools_root.mkdir(parents=True)
        source = pathlib.Path(correction.__file__).read_bytes()
        source_path = tools_root / "production_legacy_runtime_role_correction.py"
        source_path.write_bytes(source)
        source_sha = hashlib.sha256(source).hexdigest()
        (source_root / "package.sha256").write_text(
            f"{source_sha}  tools/production_legacy_runtime_role_correction.py\n",
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
            "  if test \"$code\" = 0; then\n"
            "    case \" $* \" in\n"
            "      *--apply*) status=corrected;;\n"
            "      *) status=ready;;\n"
            "    esac\n"
            "    printf '{\"status\":\"%s\",\"task_id\":"
            "\"PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CORRECTION-001\"}' "
            "\"$status\"\n"
            "  elif test \"$code\" = 2; then\n"
            "    printf '%s\\n' "
            "'production_legacy_runtime_role_correction=FAIL "
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
            correction.ROOT
            / "tools"
            / "production_legacy_runtime_role_correction_runner.sh"
        ).read_text(encoding="utf-8")
        runner_source = runner_source.replace(
            "/var/lib/noteai/legacy-role-correction",
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

    def test_source_registry_remains_e5883_pinned_and_current_drift_fails_closed(
        self,
    ):
        self.assertEqual(
            set(correction.EXPECTED_SOURCE_PATH_SHA256.values()),
            set(identity_audit.EXPECTED_SOURCE_SHA256.values()),
        )
        self.assertEqual(len(correction.EXPECTED_SOURCE_PATH_SHA256), 18)
        self.assertIn(
            "model/migrations/postgres/"
            "0016_admin_runtime_role_collision.sql",
            correction.EXPECTED_SOURCE_PATH_SHA256,
        )
        with self.assertRaises(correction.RoleCorrectionError) as raised:
            correction.validate_local_source()

        self.assertEqual(raised.exception.code, "source_drift")
        self.assertEqual(raised.exception.stage, "local_source")

    def test_runner_is_single_use_and_never_persists_plaintext_dsn(self):
        runner = (
            correction.ROOT
            / "tools"
            / "production_legacy_runtime_role_correction_runner.sh"
        ).read_text(encoding="utf-8")
        source_sha = hashlib.sha256(
            correction.Path(correction.__file__).read_bytes()
        ).hexdigest()

        self.assertIn(f"corrector_sha256={source_sha}", runner)
        self.assertIn("preflight.started", runner)
        self.assertIn("apply.started", runner)
        self.assertIn('test ! -e "${dispatch_sentinel}"', runner)
        self.assertIn("--network host", runner)
        self.assertIn("--read-only", runner)
        self.assertIn("--cap-drop=ALL", runner)
        self.assertIn("--security-opt=no-new-privileges:true", runner)
        self.assertIn("openssl pkeyutl", runner)
        self.assertIn("sys.stdin.read()", runner)
        self.assertIn("database_url=value", runner)
        self.assertNotIn('os.environ["NOTEAI_', runner)
        self.assertNotIn("runner.env", runner)
        self.assertNotIn("DATABASE_URL=", runner)
        self.assertNotIn("--env-file", runner)
        self.assertIn("production_legacy_runtime_role_correction=FAIL", runner)
        self.assertIn("set -o pipefail", runner)

    def test_runner_rm_failure_is_preconnect_without_dispatch(self):
        fixture, task_root, bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        fake_rm = bin_root / "rm"
        fake_rm.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        fake_rm.chmod(0o755)

        completed = subprocess.run(
            [str(runner_path), "preflight"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("incident_class=PRE_CONNECT", completed.stdout)
        self.assertFalse((task_root / "preflight.started").exists())

    def test_runner_sentinel_write_failure_is_preconnect(self):
        fixture, task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        source = runner_path.read_text(encoding="utf-8").replace(
            'prepared_sentinel="${task_root}/preflight.prepared"',
            'prepared_sentinel="${task_root}/missing/preflight.prepared"',
        )
        runner_path.write_text(source, encoding="utf-8")

        completed = subprocess.run(
            [str(runner_path), "preflight"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("incident_class=PRE_CONNECT", completed.stdout)
        self.assertFalse((task_root / "preflight.started").exists())

    def test_runner_exit_127_is_proven_preconnect(self):
        fixture, task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)

        completed = subprocess.run(
            [str(runner_path), "preflight"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("incident_class=PRE_CONNECT", completed.stdout)
        self.assertTrue((task_root / "preflight.started").exists())

    def test_runner_unclassified_postdispatch_failure_is_unknown(self):
        fixture, task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        environment["FAKE_DOCKER_RUN_EXIT"] = "50"

        completed = subprocess.run(
            [str(runner_path), "preflight"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("incident_class=CONNECTED_UNKNOWN", completed.stdout)
        self.assertTrue((task_root / "preflight.started").exists())

    def test_runner_postcommit_result_move_failure_reports_two_writes(self):
        fixture, task_root, bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        (task_root / "preflight-result.json").write_text(
            '{"status":"ready","alter_capability_proven":true,'
            '"revoke_capability_proven":true,'
            '"elevated_attribute_count":1,'
            '"bidirectional_membership_count":1}',
            encoding="utf-8",
        )
        fake_mv = bin_root / "mv"
        fake_mv.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        fake_mv.chmod(0o755)
        environment["FAKE_DOCKER_RUN_EXIT"] = "0"

        completed = subprocess.run(
            [str(runner_path), "apply"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 30)
        self.assertIn("database_outcome=COMMITTED", completed.stdout)
        self.assertIn("result_recovery_required=1", completed.stdout)
        self.assertIn("database_write=2", completed.stdout)
        self.assertNotIn("database_write=0", completed.stdout)

    def test_runner_postcommit_result_hash_failure_reports_committed(self):
        fixture, task_root, bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        (task_root / "preflight-result.json").write_text(
            '{"status":"ready","alter_capability_proven":true,'
            '"revoke_capability_proven":true,'
            '"elevated_attribute_count":1,'
            '"bidirectional_membership_count":1}',
            encoding="utf-8",
        )
        real_sha256sum = shutil.which("sha256sum")
        self.assertIsNotNone(real_sha256sum)
        fake_sha256sum = bin_root / "sha256sum"
        fake_sha256sum.write_text(
            "#!/usr/bin/env bash\n"
            "case \" $* \" in *'apply-result.json.tmp'*) exit 1;; esac\n"
            f"exec '{real_sha256sum}' \"$@\"\n",
            encoding="utf-8",
        )
        fake_sha256sum.chmod(0o755)
        environment["FAKE_DOCKER_RUN_EXIT"] = "0"

        completed = subprocess.run(
            [str(runner_path), "apply"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 30)
        self.assertIn("database_outcome=COMMITTED", completed.stdout)
        self.assertIn("database_write=2", completed.stdout)
        self.assertIn("result_recovery_required=1", completed.stdout)

    def test_runner_success_with_residual_container_never_exits_zero(self):
        fixture, _task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        environment["FAKE_DOCKER_RUN_EXIT"] = "0"
        environment["FAKE_DOCKER_RESIDUAL"] = "1"

        completed = subprocess.run(
            [str(runner_path), "preflight"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 30)
        self.assertIn(
            "database_outcome=READ_ONLY_COMPLETED",
            completed.stdout,
        )
        self.assertIn("cleanup_required=1", completed.stdout)
        self.assertIn("database_write=0", completed.stdout)

    def test_runner_committed_apply_with_residual_preserves_outcome(self):
        fixture, task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        (task_root / "preflight-result.json").write_text(
            '{"status":"ready","alter_capability_proven":true,'
            '"revoke_capability_proven":true,'
            '"elevated_attribute_count":1,'
            '"bidirectional_membership_count":1}',
            encoding="utf-8",
        )
        environment["FAKE_DOCKER_RUN_EXIT"] = "0"
        environment["FAKE_DOCKER_RESIDUAL"] = "1"

        completed = subprocess.run(
            [str(runner_path), "apply"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 30)
        self.assertIn("database_outcome=COMMITTED", completed.stdout)
        self.assertIn("database_write=2", completed.stdout)
        self.assertIn("cleanup_required=1", completed.stdout)
        self.assertIn("result_recovery_required=1", completed.stdout)

    def test_runner_child_preconnect_with_residual_requires_cleanup(self):
        fixture, _task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        environment["FAKE_DOCKER_RUN_EXIT"] = "2"
        environment["FAKE_DOCKER_RESIDUAL"] = "1"

        completed = subprocess.run(
            [str(runner_path), "preflight"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("incident_class=PRE_CONNECT", completed.stdout)
        self.assertIn("cleanup_required=1", completed.stdout)

    def test_runner_unknown_with_residual_reports_cleanup_required(self):
        fixture, _task_root, _bin_root, runner_path, environment = (
            self._runner_fixture()
        )
        self.addCleanup(fixture.cleanup)
        environment["FAKE_DOCKER_RUN_EXIT"] = "50"
        environment["FAKE_DOCKER_RESIDUAL"] = "1"

        completed = subprocess.run(
            [str(runner_path), "preflight"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("incident_class=CONNECTED_UNKNOWN", completed.stdout)
        self.assertIn("cleanup_required=1", completed.stdout)

    def test_preflight_is_forced_read_only_and_writes_nothing(self):
        connection = LegacyConflictConnection()

        result = correction.preflight(connection)

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["database_write_count"], 0)
        self.assertEqual(
            result["precondition"]["elevated_attribute_count"],
            1,
        )
        self.assertEqual(
            result["precondition"]["bidirectional_membership_count"],
            1,
        )
        self.assertTrue(result["precondition"]["alter_capability_proven"])
        self.assertTrue(result["precondition"]["revoke_capability_proven"])
        statements = [statement for statement, _params in connection.calls]
        self.assertEqual(statements[0], "SET TRANSACTION READ ONLY")
        self.assertFalse(any(
            statement.startswith(("ALTER ", "REVOKE "))
            for statement in statements
        ))

    def test_apply_executes_only_the_two_authorized_role_mutations(self):
        connection = LegacyConflictConnection()

        result = correction.apply_correction(connection)

        self.assertEqual(result["status"], "corrected")
        self.assertTrue(result["transaction_committed"])
        self.assertEqual(result["database_writes"], {
            "legacy_runtime_role_attribute_changes": 1,
            "legacy_runtime_membership_revocations": 1,
            "migration_ledger_changes": 0,
            "schema_changes": 0,
            "table_row_changes": 0,
            "existing_business_row_updates": 0,
        })
        self.assertEqual(
            result["postcondition"]["elevated_attribute_count"],
            0,
        )
        self.assertEqual(
            result["postcondition"]["bidirectional_membership_count"],
            0,
        )
        mutation_statements = [
            statement
            for statement, _params in connection.calls
            if statement.startswith(("ALTER ", "REVOKE "))
        ]
        self.assertEqual(mutation_statements, [
            "ALTER ROLE noteai_app NOINHERIT",
            "REVOKE noteai_xhs FROM noteai_admin "
            'GRANTED BY "provider_control_role"',
        ])

    def test_changed_membership_fails_before_any_mutation(self):
        connection = LegacyConflictConnection()
        connection.membership = False

        with self.assertRaisesRegex(
            correction.RoleCorrectionError,
            "membership_identity_changed",
        ):
            correction.apply_correction(connection)

        statements = [statement for statement, _params in connection.calls]
        self.assertNotIn("ALTER ROLE noteai_app NOINHERIT", statements)
        self.assertNotIn("REVOKE noteai_xhs FROM noteai_admin", statements)

    def test_confirmation_is_required_before_connection(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                correction,
                "validate_local_source",
                return_value=correction.EXPECTED_SOURCE_PATH_SHA256,
            ),
            mock.patch.object(
                correction,
                "_connect",
                side_effect=AssertionError("must not connect"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = correction.main(
                ["--apply"],
                database_url="postgresql://not-used.invalid/db",
                confirmation=None,
            )

        self.assertEqual(result, 2)
        self.assertIn("incident_class=PRE_CONNECT", stderr.getvalue())
        self.assertIn("connection_attempted=0", stderr.getvalue())

    def test_missing_dsn_is_proven_preconnect(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                correction,
                "validate_local_source",
                return_value=correction.EXPECTED_SOURCE_PATH_SHA256,
            ),
            mock.patch.object(correction, "psycopg", object()),
            contextlib.redirect_stderr(stderr),
        ):
            result = correction.main(["--preflight"], database_url="")

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_legacy_runtime_role_correction=FAIL "
            "stage=connect incident_class=PRE_CONNECT "
            "database_connected=0 connection_attempted=0 "
            "database_outcome=NOT_CONNECTED retry_same_path=0",
        )

    def test_connect_exception_is_connected_unknown(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                correction,
                "validate_local_source",
                return_value=correction.EXPECTED_SOURCE_PATH_SHA256,
            ),
            mock.patch.object(
                correction,
                "_connect",
                side_effect=RuntimeError("must not be rendered"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = correction.main(
                ["--preflight"],
                database_url="postgresql://redacted.invalid/db",
            )

        self.assertEqual(result, 1)
        self.assertIn("incident_class=CONNECTED_UNKNOWN", stderr.getvalue())
        self.assertIn("connection_attempted=1", stderr.getvalue())
        self.assertNotIn("must not be rendered", stderr.getvalue())

    def test_connected_precondition_drift_is_known_and_zero_write(self):
        connection = LegacyConflictConnection()
        connection.membership = False
        stderr = io.StringIO()
        with (
            mock.patch.object(
                correction,
                "validate_local_source",
                return_value=correction.EXPECTED_SOURCE_PATH_SHA256,
            ),
            mock.patch.object(
                correction,
                "_connect",
                return_value=connection,
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = correction.main(
                ["--apply"],
                database_url="postgresql://redacted.invalid/db",
                confirmation=correction.TASK_ID,
            )

        self.assertEqual(result, 30)
        self.assertIn("incident_class=CONNECTED_KNOWN", stderr.getvalue())
        self.assertIn("database_outcome=ROLLED_BACK", stderr.getvalue())
        self.assertIn("database_write=0", stderr.getvalue())

    def test_connected_statement_failure_with_confirmed_rollback_is_known(self):
        connection = LegacyConflictConnection()
        original_execute = connection.execute

        def execute(statement, params=()):
            normalized = " ".join(str(statement).split())
            if normalized.startswith("REVOKE noteai_xhs"):
                raise RuntimeError("must remain secret-free")
            return original_execute(statement, params)

        connection.execute = execute
        stderr = io.StringIO()
        with (
            mock.patch.object(
                correction,
                "validate_local_source",
                return_value=correction.EXPECTED_SOURCE_PATH_SHA256,
            ),
            mock.patch.object(
                correction,
                "_connect",
                return_value=connection,
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = correction.main(
                ["--apply"],
                database_url="postgresql://redacted.invalid/db",
                confirmation=correction.TASK_ID,
            )

        self.assertEqual(result, 30)
        self.assertTrue(connection.elevated)
        self.assertTrue(connection.membership)
        self.assertIn("database_outcome=ROLLED_BACK", stderr.getvalue())
        self.assertNotIn("must remain secret-free", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
