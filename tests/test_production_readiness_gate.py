import json
import os
import re
import subprocess
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

    def test_production_roles_exclude_browser_dependencies_and_commands(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        api_requirements = (MODEL_DIR / "requirements-api.txt").read_text(encoding="utf-8")
        worker_requirements = (MODEL_DIR / "requirements-worker.txt").read_text(encoding="utf-8")
        api_stage = dockerfile.split("FROM runtime-common AS api-runtime", 1)[1].split(
            "FROM runtime-common AS admin-runtime", 1
        )[0]
        admin_stage = dockerfile.split("FROM runtime-common AS admin-runtime", 1)[1].split(
            "FROM runtime-common AS ai-worker-runtime", 1
        )[0]
        ai_worker_stage = dockerfile.split(
            "FROM runtime-common AS ai-worker-runtime", 1
        )[1].split(
            "FROM runtime-common AS xhs-http-runtime", 1
        )[0]
        xhs_stage = dockerfile.split("FROM runtime-common AS xhs-http-runtime", 1)[1].split(
            "FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime", 1
        )[0]

        self.assertIn("FROM runtime-common AS api-runtime", dockerfile)
        self.assertIn("FROM runtime-common AS admin-runtime", dockerfile)
        self.assertIn("FROM runtime-common AS ai-worker-runtime", dockerfile)
        self.assertIn("FROM runtime-common AS xhs-http-runtime", dockerfile)
        self.assertNotIn("FROM runtime-common AS worker-runtime", dockerfile)
        self.assertIn("FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime", dockerfile)
        self.assertIn('CMD ["/app/scripts/render_start_api.sh"]', api_stage)
        self.assertIn('CMD ["/app/scripts/render_start_admin.sh"]', admin_stage)
        self.assertIn(
            'CMD ["python", "durable_ai_worker.py", "--once"]',
            ai_worker_stage,
        )
        self.assertIn('CMD ["/bin/false"]', xhs_stage)
        self.assertIn("NOTEAI_XHS_COLLECTION_SUSPENDED=1", xhs_stage)
        self.assertIn("HEALTHCHECK NONE", xhs_stage)
        for stage in (api_stage, admin_stage, ai_worker_stage, xhs_stage):
            self.assertNotIn("playwright", stage.lower())
            self.assertNotIn("chromium", stage.lower())
        for package in ("libgl1", "libglib2.0-0", "libsm6", "libxext6", "libxrender1"):
            self.assertNotIn(package, dockerfile)
        self.assertNotIn("playwright==", api_requirements)
        self.assertIn("playwright==1.56.0", worker_requirements)
        self.assertNotIn("python -m playwright install", dockerfile)
        self.assertNotIn("apt-get autoremove", dockerfile)
        self.assertIn("CRYPTO_JS_VERSION=4.2.0", dockerfile)
        for stage in (api_stage, admin_stage, ai_worker_stage, xhs_stage):
            self.assertIn("USER noteai", stage)
        self.assertIn("python -m pip uninstall -y setuptools wheel", dockerfile)
        self.assertIn("python -m pip check", dockerfile)
        self.assertNotIn("CMD curl", dockerfile)
        self.assertNotIn('"curl"', compose)
        self.assertEqual(compose.count("import http.client, sys"), 2)
        self.assertEqual(compose.count("target: api-runtime"), 1)
        self.assertEqual(compose.count("target: admin-runtime"), 1)
        self.assertEqual(compose.count("target: ai-worker-runtime"), 1)
        self.assertEqual(compose.count("target: xhs-http-runtime"), 2)
        self.assertEqual(compose.count("no-new-privileges:true"), 5)
        self.assertEqual(compose.count("privileged: false"), 5)
        self.assertEqual(compose.count('user: "999:999"'), 5)
        self.assertEqual(compose.count("read_only: true"), 5)
        self.assertEqual(compose.count("cap_drop:"), 5)
        self.assertNotIn("seccomp=", compose)

    def test_role_requirements_are_exactly_pinned_and_compatibility_is_recursive(self):
        api_lines = [
            line.strip()
            for line in (MODEL_DIR / "requirements-api.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        worker_lines = [
            line.strip()
            for line in (MODEL_DIR / "requirements-worker.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        compatibility_lines = [
            line.strip()
            for line in (MODEL_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        self.assertTrue(api_lines)
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s]+", line) for line in api_lines))
        self.assertIn("pillow==12.3.0", api_lines)
        self.assertEqual(worker_lines, ["-r requirements-api.txt", "playwright==1.56.0"])
        self.assertEqual(compatibility_lines, ["-r requirements-api.txt"])

    def _run_entrypoint_guard(
        self,
        image_role,
        declared_role,
        command,
        *,
        marker_state="valid",
        check_pre_artifact=False,
        **extra_env,
    ):
        source = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            marker = tmp_path / "noteai-runtime-role"
            if marker_state == "valid":
                marker.write_text(f"{image_role}\n", encoding="utf-8")
            elif marker_state == "empty":
                marker.write_text("\n", encoding="utf-8")
            elif marker_state == "unreadable":
                marker.write_text(f"{image_role}\n", encoding="utf-8")
                marker.chmod(0o000)
            elif marker_state == "read_failure":
                marker.write_text(image_role, encoding="utf-8")
            elif marker_state != "missing":
                raise AssertionError(f"unknown marker state: {marker_state}")
            artifact_sentinel = tmp_path / "artifact-loader-called"
            script = tmp_path / "docker_entrypoint.sh"
            script.write_text(
                source.replace(
                    "runtime_role_file=/etc/noteai-runtime-role",
                    f"runtime_role_file='{marker}'",
                ).replace(
                    "cd /app/model",
                    f"cd '{MODEL_DIR}'",
                ).replace(
                    "  python -m artifact_loader",
                    f"  printf '%s\\n' called > '{artifact_sentinel}'",
                ).replace(
                    'exec "$@"',
                    "exit 0",
                ),
                encoding="utf-8",
            )
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "NOTEAI_RUNTIME_ROLE": declared_role,
                "NOTEAI_SKIP_MODEL_ARTIFACT_CHECK": "0" if check_pre_artifact else "1",
                **extra_env,
            }
            result = subprocess.run(
                ["sh", str(script), *command],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            return result, artifact_sentinel.exists()

    def test_runtime_role_guard_fails_closed_before_artifact_loading(self):
        cases = (
            ("missing", "api", "api"),
            ("unreadable", "api", "api"),
            ("empty", "api", "api"),
            ("read_failure", "api", "api"),
            ("valid", "api", "admin"),
            ("valid", "api", ""),
            ("valid", "invalid", "invalid"),
        )
        for marker_state, image_role, declared_role in cases:
            with self.subTest(
                marker_state=marker_state,
                image_role=image_role,
                declared_role=declared_role,
            ):
                result, artifact_called = self._run_entrypoint_guard(
                    image_role,
                    declared_role,
                    ["/app/scripts/render_start_api.sh"],
                    marker_state=marker_state,
                    check_pre_artifact=True,
                )

                self.assertEqual(result.returncode, 78, result.stderr)
                self.assertFalse(artifact_called, "artifact loader ran before role rejection")

    def test_runtime_role_allowlists_accept_only_current_service_contracts(self):
        allowed = {
            "api": (
                ["/app/scripts/render_start_api.sh"],
                ["python", "/app/scripts/render_predeploy.py"],
            ),
            "admin": (
                ["/app/scripts/render_start_admin.sh"],
                ["python", "-m", "uvicorn", "admin_server:admin_app", "--host", "0.0.0.0", "--port", "8001"],
            ),
            "ai-worker": (
                ["python", "durable_ai_worker.py", "--healthcheck"],
                ["python", "durable_ai_worker.py", "--once"],
                ["python", "durable_ai_worker.py", "--recover-unstarted"],
                ["python", "durable_ai_worker.py", "--reconcile-stale"],
            ),
            "xhs-http": (
                ["/app/scripts/render_run_market_timing.sh"],
                ["/app/scripts/render_run_crawler.sh"],
                ["python", "market_timing_worker.py"],
                ["python", "market_timing_worker.py", "--once"],
                ["python", "market_timing_worker.py", "--daemon", "--interval", "60"],
                ["python", "market_timing_worker.py", "--healthcheck"],
                ["python", "market_timing_worker.py", "--acknowledge-unknown"],
                ["python", "market_timing_worker.py", "--clear-session-block"],
                ["python", "crawler_worker.py"],
                ["python", "crawler_worker.py", "--once"],
                ["python", "crawler_worker.py", "--healthcheck"],
                ["python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", "50"],
                ["/bin/false"],
            ),
        }
        for role, commands in allowed.items():
            for command in commands:
                with self.subTest(role=role, command=command):
                    result, artifact_called = self._run_entrypoint_guard(
                        role,
                        role,
                        command,
                        **({
                            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                            "NOTEAI_XHS_SERVICE": (
                                "tracking"
                                if any("crawler" in part for part in command)
                                else "trends"
                            ),
                        } if role == "xhs-http" else {}),
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(artifact_called)

    def test_runtime_role_allowlists_reject_bypasses_before_artifact_loading(self):
        rejected = {
            "api": (
                [],
                ["python", "-m", "uvicorn", "api:app"],
                ["python", "api.py"],
                ["python", "-m", "crawler_worker"],
                ["python", "-m", "market_timing_worker"],
                ["python", "/app/model/crawler_worker.py"],
                ["python", "/app/model/market_timing_worker.py"],
                ["sh", "-c", "/app/scripts/render_start_api.sh"],
                ["/app/scripts/render_start_api.sh", "extra"],
                ["python", "/app/scripts/render_predeploy.py", "extra"],
                ["/app/scripts/render_run_crawler.sh"],
                ["python", "market_timing_worker.py", "--daemon", "--interval", "api:app"],
            ),
            "admin": (
                [],
                ["/app/scripts/render_start_api.sh"],
                ["/app/scripts/render_run_crawler.sh"],
                ["python", "/app/scripts/render_predeploy.py"],
                ["python", "crawler_worker.py"],
            ),
            "ai-worker": (
                [],
                ["/app/scripts/render_start_api.sh"],
                ["python", "api.py"],
                ["python", "durable_ai_worker.py"],
                ["python", "durable_ai_worker.py", "--once", "extra"],
                ["sh", "-c", "python durable_ai_worker.py --once"],
            ),
            "xhs-http": (
                [],
                ["/app/scripts/render_start_api.sh"],
                ["/app/scripts/render_start_admin.sh"],
                ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"],
                ["python", "api.py"],
                ["python", "/app/model/api.py"],
                ["python", "-m", "crawler_worker"],
                ["python", "/app/model/crawler_worker.py"],
                ["sh", "-c", "/app/scripts/render_run_crawler.sh"],
                ["/app/scripts/render_run_crawler.sh", "extra"],
                ["python", "/app/scripts/render_predeploy.py"],
                ["/bin/false", "extra"],
                ["python", "-c", "import api"],
                ["python", "crawler_worker.py", "--loop", "--interval-minutes", "api.py", "--limit", "50"],
                ["python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", "api.py"],
            ),
        }
        for role, commands in rejected.items():
            for command in commands:
                with self.subTest(role=role, command=command):
                    result, artifact_called = self._run_entrypoint_guard(
                        role,
                        role,
                        command,
                        check_pre_artifact=True,
                        **({
                            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                            "NOTEAI_XHS_SERVICE": "tracking",
                        } if role == "xhs-http" else {}),
                    )

                    self.assertEqual(result.returncode, 78, result.stderr)
                    self.assertFalse(artifact_called, "artifact loader ran before command rejection")

    def test_api_runtime_guard_rejects_scheduler_before_artifact_loading(self):
        result, artifact_called = self._run_entrypoint_guard(
            "api",
            "api",
            ["/app/scripts/render_start_api.sh"],
            check_pre_artifact=True,
            NOTEAI_API_STARTS_TREND_SCHEDULER="1",
        )

        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn("trend scheduler", result.stderr)
        self.assertFalse(artifact_called)

    def test_ai_worker_unsuspend_requires_exact_processor_before_artifact_loading(self):
        result, artifact_called = self._run_entrypoint_guard(
            "ai-worker",
            "ai-worker",
            ["python", "durable_ai_worker.py", "--once"],
            check_pre_artifact=True,
            NOTEAI_DURABLE_AI_SUSPENDED="0",
        )
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn("exact production processor", result.stderr)
        self.assertFalse(artifact_called)

    def test_readiness_entrypoint_semantic_harness_accepts_current_contract(self):
        source = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")

        passed, detail = gate._check_entrypoint_runtime_contract(source)

        self.assertTrue(passed, detail)
        self.assertIn("allowed=21", detail)

    def test_readiness_entrypoint_semantic_harness_rejects_allowlist_backdoor(self):
        source = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")
        reject_gate = 'if [ "$command_allowed" -ne 1 ]; then'
        mutated = source.replace(
            reject_gate,
            f"command_allowed=1\n\n{reject_gate}",
            1,
        )
        self.assertNotEqual(source, mutated)

        passed, detail = gate._check_entrypoint_runtime_contract(mutated)

        self.assertFalse(passed, detail)
        self.assertIn("reject_contract_failed", detail)

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
        self.assertEqual(gate._line_has_secret_value("HARDENING_TOKENS = ("), (False, ""))

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
