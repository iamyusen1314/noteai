from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "recover_minimal_api_runtimes.sh"


class RecoverMinimalApiRuntimesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_and_offline_unit_render(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--offline-self-test"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout,
            "NOTEAI_RUNTIME_RECOVERY_OFFLINE_SELF_TEST=PASS\n",
        )
        self.assertEqual(result.stderr, "")

        rollback = subprocess.run(
            ["bash", str(SCRIPT), "--offline-rollback-self-test"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            rollback.stdout,
            "NOTEAI_RUNTIME_RECOVERY_ROLLBACK_SELF_TEST=PASS "
            "faults=7 cleanup_failure=fail_closed\n",
        )
        self.assertEqual(rollback.stderr, "")

    def test_exact_three_unit_topology_and_image_identities_are_fixed(self) -> None:
        production = self.source.split("trap on_exit EXIT", 1)[1]
        for value in (
            "target_units=(noteai-api.service noteai-admin.service)",
            "target_containers=(noteai-api-c noteai-admin-c)",
            "target_units=(noteai-api.service)",
            "target_containers=(noteai-api-f)",
        ):
            self.assertEqual(production.count(value), 1, value)

        expected_once = (
            "b55f11882100e9ef919522540729e366a511f88f",
            "sha256:dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53",
            "a635692a899ee02c6905cd694611c14e0da4594a",
            "sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f",
        )
        for value in expected_once:
            self.assertEqual(self.source.count(value), 1, value)
        for value in (
            "sha256:612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620",
            "sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733",
        ):
            self.assertEqual(self.source.count(value), 2, value)

    def test_fresh_absent_baseline_precedes_first_mutation(self) -> None:
        preflight = self.source.index("phase='host_preflight'")
        task_root = self.source.index('install -d -o root -g root -m 0700 "$TASK_ROOT"')
        render = self.source.index("phase='unit_render_and_verify'")
        install = self.source.index("phase='unit_install'")
        self.assertLess(preflight, task_root)
        self.assertLess(task_root, render)
        self.assertLess(render, install)
        for gate in (
            "unit_is_absent",
            "container_is_absent",
            "listener_not_absent",
            "unexpected_runtime",
            "database_connection_baseline",
        ):
            self.assertIn(gate, self.source[preflight:render])

    def test_secret_files_are_metadata_and_key_name_only(self) -> None:
        self.assertIn("regular_root_0600", self.source)
        self.assertIn("parse_env_keys", self.source)
        self.assertIn("candidate_count=$((candidate_count + 1))", self.source)
        self.assertIn("[ \"$candidate_count\" = '1' ]", self.source)
        for key in (
            "NOTEAI_PRIVATE_STORAGE_BACKEND",
            "NOTEAI_OSS_PRIVATE_BUCKET",
            "NOTEAI_OSS_REGION",
            "NOTEAI_OSS_ENDPOINT",
            "NOTEAI_OSS_RAM_ROLE",
            "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH",
            "NOTEAI_OSS_KEY_PREFIX",
        ):
            self.assertIn(key, self.source)
        self.assertNotIn("cat \"$API_ENV\"", self.source)
        self.assertNotIn("cat \"$ADMIN_ENV\"", self.source)

    def test_units_enforce_loopback_read_only_db_and_hardening(self) -> None:
        for value in (
            "--pull=never",
            "--user=999:999",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--network=bridge",
            "--ipc=private",
            "--rm",
            "--pids-limit=512",
            "--publish=127.0.0.1:8000:8000",
            "--publish=127.0.0.1:8001:8001",
            'PGOPTIONS=-c default_transaction_read_only=on',
            "Restart=no",
        ):
            self.assertIn(value, self.source)
        self.assertNotIn("--publish=0.0.0.0", self.source)
        self.assertNotIn("--network=host", self.source)
        self.assertNotIn("ExecStartPre=", self.source)
        self.assertNotIn("ExecStopPost=", self.source)
        self.assertIn("com.noteai.recovery.owner", self.source)

    def test_systemd_verify_is_before_install_reload_enable_and_start(self) -> None:
        production = self.source.split("phase='unit_render_and_verify'", 1)[1]
        verify = production.index("systemd-analyze verify")
        install = production.index("phase='unit_install'")
        reload = production.index("systemctl daemon-reload")
        enable = production.index("phase='unit_enable'")
        start = production.index("phase='unit_start'")
        self.assertLess(verify, install)
        self.assertLess(install, reload)
        self.assertLess(reload, enable)
        self.assertLess(enable, start)

    def test_api_c_is_all_or_nothing_and_rollback_requires_absence(self) -> None:
        rollback = self.source.split("rollback_mutation() {", 1)[1].split("\n}\n", 1)[0]
        for value in (
            "systemctl stop",
            "systemctl disable",
            "docker container rm --force",
            "sha256sum",
            "unit_is_absent",
            "container_is_absent",
            "port_listener_count",
            "cleanup_unknown=1",
        ):
            self.assertIn(value, rollback)
        self.assertIn("NOTEAI_RUNTIME_RECOVERY=CLEANUP_UNKNOWN", self.source)
        self.assertIn('installed_units+=("$unit")', self.source)

    def test_success_requires_exactly_three_health_rounds_and_final_checks(self) -> None:
        acceptance = self.source.split("phase='three_round_health_acceptance'", 1)[1]
        self.assertEqual(acceptance.count("for round in 1 2 3"), 1)
        self.assertIn("health_request api 8000 live", acceptance)
        self.assertIn("health_request api 8000 ready", acceptance)
        self.assertIn("health_request admin 8001 live", acceptance)
        self.assertIn("health_request admin 8001 ready", acceptance)
        self.assertIn("database_connection_count", acceptance)
        self.assertIn("verify_no_container_connections", acceptance)
        self.assertIn("health_rounds=3", acceptance)

    def test_executor_has_no_forbidden_control_plane_or_database_commands(self) -> None:
        forbidden = (
            "docker pull",
            "docker login",
            "docker push",
            "docker tag",
            "docker build",
            "buildx",
            "buildkit",
            "aliyun ",
            "aliyuncli",
            "CreateRole",
            "AttachPolicy",
            "VpcEndpoint",
            "psql",
            "render_predeploy",
            "apply_postgres_migrations",
            "migrate_sqlite",
        )
        for value in forbidden:
            self.assertNotIn(value, self.source)


if __name__ == "__main__":
    unittest.main()
