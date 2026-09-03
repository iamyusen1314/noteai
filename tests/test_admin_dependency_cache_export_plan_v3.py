from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_export_plan_v3 as verifier  # noqa: E402


class AdminDependencyCacheExportPlanV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = verifier.WORKFLOW_PATH.read_bytes()
        cls.template = verifier.TEMPLATE_PATH.read_bytes()
        cls.bundle_verifier = verifier.BUNDLE_VERIFIER_PATH.read_bytes()
        cls.transient_verifier = verifier.TRANSIENT_VERIFIER_PATH.read_bytes()
        cls.cleanup_helper = verifier.CLEANUP_HELPER_PATH.read_bytes()

    def test_exact_activated_v3_plan_passes(self) -> None:
        self.assertEqual(verifier.validate_plan(), [])
        self.assertEqual(verifier.plan_state(), "V3_ARMED_OR_TRIGGERED_EXACT")
        self.assertTrue(verifier.ACTIVE_REQUEST_PATH.exists())
        self.assertEqual(
            verifier._request_additions(),
            ["443bb1e534f98232541f44b744d753bfa7c09168"],
        )

    def test_state_classification_keeps_consumed_distinct_from_invalid(self) -> None:
        self.assertEqual(
            verifier.classify_plan_state(
                plan_errors=[],
                active_exists=False,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V3_CONSUMED_OR_INVALID",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                plan_errors=[],
                active_exists=True,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V3_ARMED_OR_TRIGGERED_EXACT",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                plan_errors=[],
                active_exists=True,
                additions=["a" * 40, "b" * 40],
                active_git_errors=[],
            ),
            "INVALID",
        )

    def test_v2_chain_is_frozen_and_terminal_failure_is_bound(self) -> None:
        self.assertEqual(verifier._validate_v2_frozen_git(), [])
        self.assertEqual(
            verifier.sha256_bytes(verifier.V2_REQUEST_PATH.read_bytes()),
            verifier.V2_REQUEST_SHA256,
        )
        self.assertEqual(
            verifier.failure_evidence.verify(
                verifier.failure_evidence.load_strict()
            ),
            [],
        )

    def test_workflow_mutation_fails_closed(self) -> None:
        broken = self.workflow.replace(
            b"timeout-minutes: 120",
            b"timeout-minutes: 121",
            1,
        )
        errors = verifier.validate_plan(workflow_bytes=broken)
        self.assertIn("V3 workflow hash drift", errors)
        self.assertIn("V3 runtime cap changed", errors)

    def test_buildkit_pin_and_separated_roots_fail_closed(self) -> None:
        broken_pin = self.workflow.replace(
            b"moby/buildkit@sha256:2f5adac4",
            b"moby/buildkit@sha256:0f5adac4",
            1,
        )
        self.assertIn(
            "V3 BuildKit pin/version changed",
            verifier.validate_plan(workflow_bytes=broken_pin),
        )
        broken_root = self.workflow.replace(
            b"BUILDX_CONFIG: ${{ runner.temp }}/noteai-buildx-state-v3",
            b"BUILDX_CONFIG: ${{ runner.temp }}/noteai-empty-docker-config-v3",
            1,
        )
        self.assertIn(
            "V3 Buildx config step count changed",
            verifier.validate_plan(workflow_bytes=broken_root),
        )

    def test_bundle_platform_contract_mutation_fails_closed(self) -> None:
        broken = self.bundle_verifier.replace(
            b'EXPECTED_DOCKERFILE_FRONTEND_VERSION = "1.25.0"',
            b'EXPECTED_DOCKERFILE_FRONTEND_VERSION = "1.24.0"',
            1,
        )
        errors = verifier.validate_plan(bundle_verifier_bytes=broken)
        self.assertIn("V3 bundle verifier hash drift", errors)
        self.assertIn(
            (
                "V3 bundle verifier contract missing: "
                'EXPECTED_DOCKERFILE_FRONTEND_VERSION = "1.25.0"'
            ),
            errors,
        )

    def test_transient_and_cleanup_mutations_fail_closed(self) -> None:
        broken_state = self.transient_verifier.replace(
            b'config == {"auths": {}}',
            b'config.get("auths") == {}',
            1,
        )
        self.assertIn(
            'V3 transient-state contract missing: config == {"auths": {}}',
            verifier.validate_plan(transient_verifier_bytes=broken_state),
        )
        broken_cleanup = self.cleanup_helper.replace(
            b'rm -rf --one-file-system -- "${docker_config}"',
            b'rmdir "${docker_config}"',
            1,
        )
        errors = verifier.validate_plan(cleanup_helper_bytes=broken_cleanup)
        self.assertIn(
            (
                "V3 cleanup contract missing: "
                'rm -rf --one-file-system -- "${docker_config}"'
            ),
            errors,
        )
        self.assertIn("V3 cleanup retains V2 rmdir defect", errors)

    def test_template_predecessor_or_authority_mutation_fails_closed(self) -> None:
        for key, value in (
            ("run_id", 30591103184),
            ("artifact_count", 1),
            ("rerun_authorized", True),
        ):
            with self.subTest(key=key):
                payload = json.loads(self.template)
                payload["predecessor"][key] = value
                broken = json.dumps(payload, indent=2).encode() + b"\n"
                errors = verifier.validate_plan(template_bytes=broken)
                self.assertIn("V3 template hash drift", errors)
                self.assertIn("V3 request template drift", errors)
        payload = json.loads(self.template)
        payload["registry_publication_authorized"] = True
        broken = json.dumps(payload, indent=2).encode() + b"\n"
        self.assertIn(
            "V3 request template drift",
            verifier.validate_plan(template_bytes=broken),
        )

    def test_parent_bound_active_request_passes_only_exactly(self) -> None:
        parent = "a" * 40
        request = self.template.replace(
            b"__DIRECT_PARENT_COMMIT__",
            parent.encode("ascii"),
        )
        self.assertEqual(
            verifier.validate_plan(
                active_request_bytes=request,
                active_plan_parent=parent,
                verify_git_state=False,
            ),
            [],
        )
        errors = verifier.validate_plan(
            active_request_bytes=request,
            active_plan_parent="b" * 40,
            verify_git_state=False,
        )
        self.assertIn(
            "V3 active request does not bind its direct parent",
            errors,
        )

    def test_v3_git_history_requires_one_retained_request_only_addition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path = Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v3.json"
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
            (root / "plan").write_text("reviewed\n", encoding="utf-8")
            run("add", "plan")
            run("commit", "-qm", "plan")
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
            self.assertEqual(
                verifier._validate_active_request(
                    request,
                    self.template,
                    plan_parent=None,
                    verify_git_state=True,
                    root=root,
                    request_path=request_path,
                ),
                [],
            )
            self.assertEqual(
                verifier._request_additions(
                    root=root,
                    request_path=request_path,
                ),
                [activation],
            )
            (root / request_path).unlink()
            run("add", "-u")
            run("commit", "-qm", "delete")
            (root / request_path).write_bytes(request)
            run("add", request_path.as_posix())
            run("commit", "-qm", "re-add")
            errors = verifier._validate_active_request(
                request,
                self.template,
                plan_parent=None,
                verify_git_state=True,
                root=root,
                request_path=request_path,
            )
            self.assertIn(
                "V3 active request addition history is not unique",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
