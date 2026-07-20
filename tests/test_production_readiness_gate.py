import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
TOOLS_DIR = ROOT / "tools"
sys.path.insert(0, str(MODEL_DIR))
sys.path.insert(0, str(TOOLS_DIR))

import artifact_loader  # noqa: E402
import fact_enrichment as facts  # noqa: E402
import production_readiness_gate as gate  # noqa: E402


class ProductionReadinessGateTests(unittest.TestCase):
    def test_current_repo_passes_production_readiness_gate(self):
        report = gate.build_report()

        self.assertTrue(report["passed"], report["failed_checks"])
        self.assertGreaterEqual(report["check_count"], 30)

    def test_runtime_image_contract_removes_only_audited_build_and_probe_tools(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("python -m playwright install --with-deps chromium", dockerfile)
        self.assertIn("apt-get purge -y xvfb xserver-common", dockerfile)
        self.assertNotIn("apt-get autoremove", dockerfile)
        self.assertIn('page.goto("about:blank")', dockerfile)
        self.assertIn("python -m pip uninstall -y setuptools wheel", dockerfile)
        self.assertIn("python -m pip check", dockerfile)
        self.assertNotIn("CMD curl", dockerfile)
        self.assertNotIn('"curl"', compose)
        self.assertEqual(compose.count("import http.client, sys"), 2)

    def test_cloud_runtime_gate_fails_with_fixed_code_when_meituan_cli_is_missing(self):
        with mock.patch.dict(os.environ, {
            "NOTEAI_CLOUD_RUNTIME": "1",
            "NOTEAI_FACT_SEARCH": "1",
            "NOTEAI_MEITUAN_TRAVEL_ENABLED": "1",
            "MEITUAN_AI_HUB_TOKEN": "",
            "MEITUAN_OPEN_TOKEN": "",
        }), mock.patch.object(facts, "_meituan_travel_cli_path", return_value="/missing/mttravel"), mock.patch.object(
            facts,
            "_meituan_travel_config_token",
            return_value="",
        ):
            checks = gate.check_optional_runtime_dependencies()

        self.assertFalse(checks[0]["passed"])
        self.assertEqual(checks[0]["detail"], "MEITUAN_TRAVEL_CLI_MISSING")

    def test_cloud_runtime_gate_fails_with_fixed_code_when_meituan_token_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "mttravel"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)
            with mock.patch.dict(os.environ, {
                "NOTEAI_CLOUD_RUNTIME": "1",
                "NOTEAI_FACT_SEARCH": "1",
                "NOTEAI_MEITUAN_TRAVEL_ENABLED": "1",
                "MEITUAN_AI_HUB_TOKEN": "",
                "MEITUAN_OPEN_TOKEN": "",
            }), mock.patch.object(facts, "_meituan_travel_cli_path", return_value=str(executable)), mock.patch.object(
                facts,
                "_meituan_travel_config_token",
                return_value="",
            ):
                checks = gate.check_optional_runtime_dependencies()

        self.assertFalse(checks[0]["passed"])
        self.assertEqual(checks[0]["detail"], "MEITUAN_TRAVEL_TOKEN_MISSING")

    def test_secret_scanner_flags_real_values_but_allows_placeholders(self):
        self.assertEqual(gate._line_has_secret_value("ANTHROPIC_API_KEY=test-key"), (False, ""))
        self.assertEqual(gate._line_has_secret_value("ADMIN_PASSWORD=${{ secrets.ADMIN_PASSWORD }}"), (False, ""))

        fake_key = "abcd1234" + "ef567890abcd1234ef567890"
        has_secret, name = gate._line_has_secret_value(f"AMAP_WEB_KEY={fake_key}")
        self.assertTrue(has_secret)
        self.assertEqual(name, "AMAP_WEB_KEY")

    def test_human_model_release_manifest_hashes_match_all_declared_files(self):
        declared = gate._load_human_release_hashes(gate.HUMAN_MODEL_RELEASE_MANIFEST)

        self.assertGreaterEqual(len(declared), 8)
        self.assertEqual(gate._declared_sha256_mismatches(declared), [])

    def test_human_model_release_manifest_hash_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "model" / "artifacts" / "evidence.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}", encoding="utf-8")

            mismatches = gate._declared_sha256_mismatches(
                {"model/artifacts/evidence.json": "0" * 64},
                root=root,
            )

        self.assertEqual(mismatches, ["model/artifacts/evidence.json"])

    def test_artifact_loader_cli_respects_required_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest = tmp_path / "manifest.json"
            manifest.write_text(json.dumps({
                "release": "test",
                "run_id": "missing",
                "artifacts": [{
                    "role": "quality_regressor",
                    "path": str(tmp_path / "missing.lgb"),
                    "sha256": "0" * 64,
                }],
            }), encoding="utf-8")

            old_env = os.environ.get("NOTEAI_MODEL_ARTIFACT_REQUIRED")
            old_argv = list(sys.argv)
            try:
                os.environ["NOTEAI_MODEL_ARTIFACT_REQUIRED"] = "1"
                sys.argv = ["artifact_loader", "--manifest", str(manifest)]
                with self.assertRaises(RuntimeError):
                    artifact_loader.main()
            finally:
                sys.argv = old_argv
                if old_env is None:
                    os.environ.pop("NOTEAI_MODEL_ARTIFACT_REQUIRED", None)
                else:
                    os.environ["NOTEAI_MODEL_ARTIFACT_REQUIRED"] = old_env


if __name__ == "__main__":
    unittest.main()
