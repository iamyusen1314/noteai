import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import production_managed_secret_distribution_audit as audit


class ProductionManagedSecretDistributionAuditTests(unittest.TestCase):
    def _file(self, root: Path, name: str, body: str) -> Path:
        path = root / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_api_c_reports_present_and_missing_without_values(self):
        synthetic = "never-emit-managed-secret-value"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "etc"
            systemd_root = root / "systemd"
            sbin_root = root / "sbin"
            env_root.mkdir()
            systemd_root.mkdir()
            sbin_root.mkdir()
            self._file(
                env_root,
                "api.env",
                f"DATABASE_URL={synthetic}\nNOTEAI_FACT_SEARCH=0\n",
            )
            self._file(
                env_root,
                "admin.env",
                f"ADMIN_PASSWORD={synthetic}\n",
            )
            (systemd_root / "noteai-api.service").write_text(
                "EnvironmentFile=/etc/noteai/api.env\n",
                encoding="utf-8",
            )
            (systemd_root / "noteai-admin.service").write_text(
                "EnvironmentFile=/etc/noteai/admin.env\n",
                encoding="utf-8",
            )

            result = audit.collect(
                "API-C",
                env_root=env_root,
                systemd_root=systemd_root,
                sbin_root=sbin_root,
            )
            encoded = json.dumps(result, sort_keys=True)

        self.assertEqual(result["expected_file_count"], 4)
        self.assertEqual(result["present_file_count"], 2)
        self.assertEqual(result["missing_file_count"], 2)
        self.assertEqual(result["root_only_file_count"], 0)
        self.assertEqual(
            [row["mode"] for row in result["files"][:2]],
            ["0600", "0600"],
        )
        self.assertFalse(any(row["root_owned"] for row in result["files"]))
        self.assertEqual(result["rejected_key_count"], 0)
        self.assertNotIn(synthetic, encoded)

    def test_complete_api_f_files_are_distinct_and_role_bound(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "etc"
            systemd_root = root / "systemd"
            sbin_root = root / "sbin"
            env_root.mkdir()
            systemd_root.mkdir()
            sbin_root.mkdir()
            self._file(env_root, "api.env", "DATABASE_URL=test\n")
            self._file(
                env_root,
                "xhs.env",
                "NOTEAI_XHS_COOKIES_JSON=test\n",
            )
            self._file(
                env_root,
                "xhs-trends.env",
                "DATABASE_URL=test\nNOTEAI_XHS_COOKIES_JSON=test\n",
            )
            self._file(
                env_root,
                "xhs-tracking.env",
                "DATABASE_URL=test\nNOTEAI_XHS_COOKIES_JSON=test\n",
            )
            (systemd_root / "noteai-api.service").write_text(
                "EnvironmentFile=/etc/noteai/api.env\n",
                encoding="utf-8",
            )

            result = audit.collect(
                "API-F",
                env_root=env_root,
                systemd_root=systemd_root,
                sbin_root=sbin_root,
            )

        self.assertEqual(result["expected_file_count"], 3)
        self.assertEqual(result["present_file_count"], 3)
        self.assertEqual(result["distinct_present_file_count"], 3)
        self.assertEqual(result["root_only_file_count"], 0)
        self.assertFalse(any(row["root_owned"] for row in result["files"]))
        self.assertEqual(result["rejected_key_count"], 0)
        self.assertTrue(result["legacy_file"]["present"])
        self.assertEqual(result["legacy_file"]["file_label"], "xhs.env")
        self.assertEqual(result["legacy_file"]["rejected_key_count"], 0)

    def test_overexposed_duplicate_and_cross_role_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "etc"
            systemd_root = root / "systemd"
            sbin_root = root / "sbin"
            env_root.mkdir()
            systemd_root.mkdir()
            sbin_root.mkdir()
            api = self._file(
                env_root,
                "api.env",
                "ADMIN_PASSWORD=${TEST_VALUE}\n"
                "ADMIN_PASSWORD=${TEST_VALUE}\n",
            )
            api.chmod(0o640)
            (systemd_root / "noteai-api.service").write_text(
                "",
                encoding="utf-8",
            )

            result = audit.collect(
                "API-F",
                env_root=env_root,
                systemd_root=systemd_root,
                sbin_root=sbin_root,
            )

        api_result = result["files"][0]
        self.assertFalse(api_result["root_only"])
        self.assertEqual(api_result["duplicate_key_count"], 1)
        self.assertEqual(api_result["rejected_key_count"], 2)

    def test_cli_output_never_contains_values(self):
        synthetic = "never-print-cli-managed-secret"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "etc"
            systemd_root = root / "systemd"
            sbin_root = root / "sbin"
            env_root.mkdir()
            systemd_root.mkdir()
            sbin_root.mkdir()
            self._file(env_root, "api.env", f"DATABASE_URL={synthetic}\n")
            (systemd_root / "noteai-api.service").write_text(
                "",
                encoding="utf-8",
            )
            output = io.StringIO()
            argv = [
                "production_managed_secret_distribution_audit.py",
                "--host-label",
                "API-F",
                "--env-root",
                os.fspath(env_root),
                "--systemd-root",
                os.fspath(systemd_root),
                "--sbin-root",
                os.fspath(sbin_root),
            ]
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(output):
                exit_code = audit.main()

        self.assertEqual(exit_code, 0)
        self.assertNotIn(synthetic, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["secret_values_emitted"], 0)


if __name__ == "__main__":
    unittest.main()
