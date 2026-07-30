from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_export_plan as verifier  # noqa: E402


class AdminDependencyCacheExportPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = verifier.WORKFLOW_PATH.read_bytes()
        cls.export_helper = verifier.EXPORT_HELPER_PATH.read_bytes()
        cls.import_helper = verifier.IMPORT_HELPER_PATH.read_bytes()
        cls.bundle_verifier = verifier.BUNDLE_VERIFIER_PATH.read_bytes()
        cls.download_helper = verifier.DOWNLOAD_HELPER_PATH.read_bytes()
        cls.provider_download_verifier = (
            verifier.PROVIDER_DOWNLOAD_VERIFIER_PATH.read_bytes()
        )
        cls.template = verifier.REQUEST_TEMPLATE_PATH.read_bytes()

    def test_exact_inert_plan_passes(self) -> None:
        self.assertEqual(verifier.validate_plan(), [])
        self.assertIn(
            verifier.plan_state(),
            {
                "PREPARED_NOT_TRIGGERED",
                "ARMED_OR_TRIGGERED_EXACT",
            },
        )

    def test_workflow_mutation_fails_closed(self) -> None:
        broken = self.workflow.replace(
            b"timeout-minutes: 120",
            b"timeout-minutes: 121",
            1,
        )
        self.assertIn(
            "dependency-cache workflow hash drift",
            verifier.validate_plan(workflow_bytes=broken),
        )

    def test_job_environment_rejects_unavailable_runner_context(self) -> None:
        broken = self.workflow.replace(
            b"      BUILDX_METADATA_PROVENANCE: max",
            (
                b"      DOCKER_CONFIG: "
                b"${{ runner.temp }}/noteai-empty-docker-config\n"
                b"      BUILDX_METADATA_PROVENANCE: max"
            ),
            1,
        )
        self.assertIn(
            "workflow job environment uses unavailable runner context",
            verifier.validate_plan(workflow_bytes=broken),
        )

    def test_export_helper_mutation_fails_closed(self) -> None:
        broken = self.export_helper.replace(b"--pull", b"--pull=false", 1)
        self.assertIn(
            "dependency-cache export helper hash drift",
            verifier.validate_plan(export_helper_bytes=broken),
        )

    def test_import_helper_mutation_fails_closed(self) -> None:
        broken = self.import_helper.replace(b"--cache-from", b"--no-cache-from", 1)
        self.assertIn(
            "dependency-cache import helper hash drift",
            verifier.validate_plan(import_helper_bytes=broken),
        )

    def test_bundle_verifier_mutation_fails_closed(self) -> None:
        broken = self.bundle_verifier.replace(
            b"MAXIMUM_RAW_TAR_BYTES",
            b"UNBOUNDED_RAW_TAR_BYTES",
            1,
        )
        self.assertIn(
            "dependency-cache bundle verifier hash drift",
            verifier.validate_plan(bundle_verifier_bytes=broken),
        )

    def test_provider_download_verifier_mutation_fails_closed(self) -> None:
        broken = self.provider_download_verifier.replace(
            b"MAXIMUM_PROVIDER_ARTIFACT_BYTES",
            b"UNBOUNDED_PROVIDER_ARTIFACT_BYTES",
            1,
        )
        self.assertIn(
            "dependency-cache provider download verifier hash drift",
            verifier.validate_plan(provider_download_verifier_bytes=broken),
        )

    def test_template_mutation_fails_closed(self) -> None:
        payload = json.loads(self.template)
        payload["artifact_retention_days"] = 2
        broken = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
        errors = verifier.validate_plan(template_bytes=broken)
        self.assertIn("dependency-cache request template hash drift", errors)
        self.assertIn("dependency-cache request template drift", errors)

    def test_duplicate_request_key_is_rejected(self) -> None:
        broken = self.template.replace(
            b'  "schema_version": 2,',
            b'  "schema_version": 1,\n  "schema_version": 2,',
            1,
        )
        errors = verifier.validate_plan(template_bytes=broken)
        self.assertTrue(
            any("duplicate JSON key: schema_version" in error for error in errors)
        )

    def test_non_finite_request_number_is_rejected(self) -> None:
        for non_finite in (b"NaN", b"1e999", b"-1e999"):
            with self.subTest(non_finite=non_finite):
                broken = self.template.replace(
                    b'  "github_actions_maximum_runtime_minutes": 120,',
                    b'  "github_actions_maximum_runtime_minutes": '
                    + non_finite
                    + b",",
                    1,
                )
                errors = verifier.validate_plan(template_bytes=broken)
                self.assertTrue(
                    any("non-finite JSON number" in error for error in errors)
                )

    def test_parent_bound_active_request_passes(self) -> None:
        parent = "a" * 40
        request = self.template.replace(
            b"__DIRECT_PARENT_COMMIT__",
            parent.encode("ascii"),
        )
        self.assertEqual(
            verifier.validate_plan(
                active_request_bytes=request,
                active_plan_parent=parent,
                verify_active_git_state=False,
            ),
            [],
        )

    def test_active_request_wrong_parent_fails(self) -> None:
        request = self.template.replace(
            b"__DIRECT_PARENT_COMMIT__",
            b"a" * 40,
        )
        errors = verifier.validate_plan(
            active_request_bytes=request,
            active_plan_parent="b" * 40,
            verify_active_git_state=False,
        )
        self.assertIn("active request does not bind its direct parent", errors)

    def test_exact_prefix_allows_only_requirements_context_copy(self) -> None:
        self.assertEqual(verifier._validate_exact_prefix(), [])
        self.assertNotIn(
            "grep -E '^COPY (model/|scripts/|NoteAI_)'",
            self.export_helper.decode("utf-8"),
        )

    def test_active_request_git_history_accepts_retained_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path = Path(
                ".github/release-requests/admin-5335bda-dependency-cache-v2.json"
            )

            def run(*args: str) -> str:
                return subprocess.run(
                    ["git", *args],
                    cwd=root,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ).stdout.strip()

            run("init", "-q")
            run("config", "user.name", "NoteAI Test")
            run("config", "user.email", "noteai-test@example.invalid")
            (root / "plan.txt").write_text("reviewed\n", encoding="utf-8")
            run("add", "plan.txt")
            run("commit", "-qm", "prepare")
            parent = run("rev-parse", "HEAD")
            request = self.template.replace(
                b"__DIRECT_PARENT_COMMIT__",
                parent.encode("ascii"),
            )
            (root / request_path).parent.mkdir(parents=True)
            (root / request_path).write_bytes(request)
            run("add", request_path.as_posix())
            run("commit", "-qm", "activate")
            activation = run("rev-parse", "HEAD")
            (root / "handoff.txt").write_text("retained\n", encoding="utf-8")
            run("add", "handoff.txt")
            run("commit", "-qm", "retain request")

            self.assertEqual(
                verifier._validate_active_request(
                    request,
                    self.template,
                    plan_parent=None,
                    verify_git_state=True,
                    git_root=root,
                    request_path=request_path,
                ),
                [],
            )
            self.assertEqual(
                verifier._request_additions(
                    git_root=root,
                    request_path=request_path,
                ),
                [activation],
            )

            (root / request_path).unlink()
            run("add", "-u")
            run("commit", "-qm", "consume")
            additions = verifier._request_additions(
                git_root=root,
                request_path=request_path,
            )
            self.assertEqual(additions, [activation])
            self.assertEqual(
                verifier.classify_plan_state(
                    plan_errors=[],
                    active_exists=False,
                    additions=additions,
                    active_git_errors=[],
                ),
                "CONSUMED_OR_INVALID",
            )
            (root / request_path).write_bytes(request)
            errors = verifier._validate_active_request(
                request,
                self.template,
                plan_parent=None,
                verify_git_state=True,
                git_root=root,
                request_path=request_path,
            )
            self.assertIn(
                "active request is not retained in current HEAD",
                errors,
            )

    def test_workflow_uses_trusted_controller_import_helper(self) -> None:
        workflow = self.workflow.decode("utf-8")
        self.assertIn(
            'bash "${{ steps.control.outputs.import_helper_copy }}"',
            workflow,
        )
        self.assertNotIn(
            '"${NOTEAI_CACHE_BUNDLE_DIR}/builder/import_admin_dependency_cache.sh"',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
