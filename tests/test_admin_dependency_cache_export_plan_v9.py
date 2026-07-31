from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_export_plan_v9 as plan  # noqa: E402


class AdminDependencyCacheExportPlanV9Tests(unittest.TestCase):
    def _fast_validate(self, **kwargs) -> list[str]:
        kwargs.setdefault("verify_git_state", False)
        with mock.patch.object(
            plan.v8_plan,
            "validate_plan",
            return_value=[],
        ), mock.patch.object(
            plan.v8_failure,
            "verify",
            return_value=[],
        ):
            return plan.validate_plan(**kwargs)

    @staticmethod
    def _json_bytes(payload: dict) -> bytes:
        return (json.dumps(payload, indent=2) + "\n").encode("utf-8")

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _initialize_activation_repository(self, root: Path) -> str:
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "NoteAI Test")
        self._git(root, "config", "user.email", "noteai@example.invalid")
        (root / "README").write_text("base\n", encoding="utf-8")
        for relative, _expected_sha256 in plan.FROZEN_ACTIVATION_FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((plan.ROOT / relative).read_bytes())
        self._git(root, "add", ".")
        self._git(root, "commit", "-q", "-m", "base")
        return self._git(root, "rev-parse", "HEAD")

    def test_inert_plan_passes_and_has_zero_request_history(self) -> None:
        self.assertFalse(plan.ACTIVE_REQUEST_PATH.exists())
        self.assertEqual(plan._request_additions(), [])
        self.assertEqual(plan.validate_plan(), [])
        self.assertEqual(plan.plan_state(), "PREPARED_V9_NOT_TRIGGERED")

    def test_exact_hash_closure_is_frozen(self) -> None:
        expected = {
            plan.WORKFLOW_PATH: plan.WORKFLOW_SHA256,
            plan.TEMPLATE_PATH: plan.TEMPLATE_SHA256,
            plan.SOURCE_FIXTURE_PATH: plan.SOURCE_FIXTURE_SHA256,
            plan.BUNDLE_VERIFIER_PATH: plan.BUNDLE_VERIFIER_SHA256,
            plan.V8_WORKFLOW_PATH: plan.V8_WORKFLOW_SHA256,
            plan.V8_TEMPLATE_PATH: plan.V8_TEMPLATE_SHA256,
            plan.V8_REQUEST_PATH: plan.V8_REQUEST_SHA256,
            plan.V8_PLAN_VERIFIER_PATH: plan.V8_PLAN_VERIFIER_SHA256,
            plan.V8_BUNDLE_VERIFIER_PATH: plan.V8_BUNDLE_VERIFIER_SHA256,
            plan.V8_FAILURE_EVIDENCE_PATH: (
                plan.V8_FAILURE_EVIDENCE_SHA256
            ),
            plan.V8_FAILURE_VERIFIER_PATH: (
                plan.V8_FAILURE_VERIFIER_SHA256
            ),
        }
        for path, expected_hash in expected.items():
            with self.subTest(path=path.name):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    expected_hash,
                )
        self.assertEqual(
            hashlib.sha256(
                Path(plan.__file__).read_bytes()
            ).hexdigest(),
            "d3d4b32d3a2f98b4311d1576e7c69446b9e95cbd1e92a85b7562fe9a4d7bb0d0",
        )

    def test_workflow_is_request_only_and_six_layer(self) -> None:
        workflow = plan.WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            workflow.split("\npermissions:", 1)[0],
            plan.EXPECTED_WORKFLOW_HEADER,
        )
        for forbidden in (
            "workflow_dispatch:",
            "pull_request:",
            "schedule:",
            "repository_dispatch:",
            "NOTEAI_V9_PLAN_VERIFIER_PATH",
        ):
            self.assertNotIn(forbidden, workflow)
        self.assertEqual(workflow.count("docker buildx create \\"), 2)
        self.assertEqual(workflow.count("uses: actions/upload-artifact@"), 1)
        for layer in ("base", "v3", "v6", "v7", "v8"):
            self.assertIn(f"{layer}_verifier_copy", workflow)
        self.assertIn("bundle_verifier_copy", workflow)
        self.assertIn(
            ".import.v9_rawjson_diagnostic."
            "input_mixed_presence_vertex_digest_count > 0",
            workflow,
        )

    def test_exact_derived_active_request_passes_without_git(self) -> None:
        parent = "a" * 40
        template = plan.TEMPLATE_PATH.read_bytes()
        request = template.replace(
            b"__DIRECT_PARENT_COMMIT__",
            parent.encode("ascii"),
        )
        self.assertEqual(
            self._fast_validate(
                active_request_bytes=request,
                active_plan_parent=parent,
            ),
            [],
        )

    def test_active_request_parent_bytes_and_semantics_fail_closed(
        self,
    ) -> None:
        parent = "a" * 40
        template = plan.TEMPLATE_PATH.read_bytes()
        request = template.replace(
            b"__DIRECT_PARENT_COMMIT__",
            parent.encode("ascii"),
        )
        errors = self._fast_validate(
            active_request_bytes=request,
            active_plan_parent="b" * 40,
        )
        self.assertIn(
            "V9 active request does not bind its direct parent",
            errors,
        )

        payload = json.loads(request)
        payload["task"] = "changed"
        errors = self._fast_validate(
            active_request_bytes=self._json_bytes(payload),
            active_plan_parent=parent,
        )
        self.assertIn(
            "V9 active request differs from reviewed template",
            errors,
        )
        self.assertIn("V9 active request semantics drift", errors)

        payload["plan_checkpoint_commit"] = "not-a-commit"
        errors = self._fast_validate(
            active_request_bytes=self._json_bytes(payload),
        )
        self.assertIn("V9 active request checkpoint is invalid", errors)

    def test_workflow_mutation_matrix_fails(self) -> None:
        original = plan.WORKFLOW_PATH.read_bytes()
        text = original.decode("utf-8")
        mutations = {
            "dispatch": text.replace(
                "on:\n  push:",
                "on:\n  workflow_dispatch:\n  push:",
                1,
            ),
            "branch": text.replace(
                "codex/quality-stabilization-real-chain",
                "main",
                1,
            ),
            "timeout": text.replace(
                "timeout-minutes: 120",
                "timeout-minutes: 121",
                1,
            ),
            "permission": text.replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: write",
                1,
            ),
            "attempt": text.replace(
                'test "${GITHUB_RUN_ATTEMPT}" = "1"',
                'test "${GITHUB_RUN_ATTEMPT}" = "2"',
                1,
            ),
            "mixed-gate": text.replace(
                "input_mixed_presence_vertex_digest_count > 0",
                "input_mixed_presence_vertex_digest_count >= 0",
                1,
            ),
            "v8-path": text.replace(
                "NOTEAI_V8_BUNDLE_VERIFIER_PATH",
                "NOTEAI_V7_BUNDLE_VERIFIER_PATH",
                1,
            ),
            "retention": text.replace(
                "retention-days: 1",
                "retention-days: 2",
                1,
            ),
            "legacy-artifact": text.replace(
                "admin-dependency-prefix-cache-5335bda-v2",
                "admin-dependency-prefix-cache-5335bda-v9",
                1,
            ),
        }
        for label, mutated in mutations.items():
            with self.subTest(label=label):
                self.assertNotEqual(mutated.encode("utf-8"), original)
                errors = self._fast_validate(
                    workflow_bytes=mutated.encode("utf-8")
                )
                self.assertTrue(errors)
                self.assertIn("V9 workflow hash drift", errors)

    def test_template_predecessor_recovery_and_authority_mutations_fail(
        self,
    ) -> None:
        original = json.loads(plan.TEMPLATE_PATH.read_text(encoding="utf-8"))
        cases = (
            ("control", ("predecessor", "control_commit"), "0" * 40),
            ("run", ("predecessor", "run_id"), 1),
            ("attempt", ("predecessor", "run_attempt"), 2),
            ("artifact", ("predecessor", "artifact_count"), 1),
            (
                "evidence",
                ("predecessor", "failure_evidence_sha256"),
                "0" * 64,
            ),
            (
                "runtime-claim",
                (
                    "recovery_basis",
                    "v8_runtime_input_transition_reconstructed",
                ),
                True,
            ),
            (
                "explicit-empty",
                (
                    "recovery_basis",
                    "explicit_empty_inputs_member_allowed",
                ),
                True,
            ),
            (
                "leaf",
                (
                    "recovery_basis",
                    "omission_only_proves_zero_inputs_or_leaf",
                ),
                True,
            ),
            (
                "union",
                (
                    "recovery_basis",
                    "union_append_last_write_or_ignore_recovery_allowed",
                ),
                True,
            ),
            (
                "bundle-v8",
                ("bundle_verifier_chain", "v8_sha256"),
                "0" * 64,
            ),
            (
                "bundle-v9",
                ("bundle_verifier_chain", "v9_sha256"),
                "0" * 64,
            ),
            ("deployment", ("deployment_authorized",), True),
            ("database", ("database_authorized",), True),
            ("traffic", ("public_traffic_authorized",), True),
            ("run-count", ("github_actions_maximum_run_count",), 2),
        )
        for label, path, value in cases:
            with self.subTest(label=label):
                payload = copy.deepcopy(original)
                target = payload
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                errors = self._fast_validate(
                    template_bytes=self._json_bytes(payload)
                )
                self.assertTrue(errors)
                self.assertIn("V9 template hash drift", errors)

    def test_source_projection_overclaims_fail_closed(self) -> None:
        original = json.loads(
            plan.SOURCE_FIXTURE_PATH.read_text(encoding="utf-8")
        )
        cases = (
            ("runtime", ("actual_v8_runtime_progress_retained",), True),
            (
                "digest",
                ("actual_v8_conflicting_digest_retained",),
                True,
            ),
            (
                "transition",
                ("runtime_input_transition_reconstructed",),
                True,
            ),
            (
                "empty",
                ("v9_contract", "explicit_empty_inputs_member_allowed"),
                True,
            ),
            (
                "leaf",
                ("v9_contract", "omission_only_proves_zero_inputs_or_leaf"),
                True,
            ),
            (
                "merge",
                (
                    "source_findings",
                    "field_level_vertex_merge_before_rawjson",
                ),
                True,
            ),
        )
        for label, path, value in cases:
            with self.subTest(label=label):
                payload = copy.deepcopy(original)
                target = payload
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                errors = self._fast_validate(
                    source_fixture_bytes=self._json_bytes(payload)
                )
                self.assertIn(
                    "V9 input-omission source fixture hash drift",
                    errors,
                )
                self.assertIn(
                    "V9 input-omission source projection changed",
                    errors,
                )

    def test_bundle_verifier_mutations_fail_closed(self) -> None:
        original = plan.BUNDLE_VERIFIER_PATH.read_text(encoding="utf-8")
        mutations = (
            original.replace(
                '"inputs" not in vertex',
                '"inputs" in vertex',
                1,
            ),
            original.replace(
                "and bool(inputs)",
                "",
                1,
            ),
            original.replace(
                "state[\"inputs\"] == input_vector",
                "True",
                1,
            ),
            original.replace(
                "input_mixed_presence_vertex_digest_count",
                "mixed_count_removed",
                1,
            ),
        )
        for index, mutated in enumerate(mutations):
            with self.subTest(index=index):
                errors = self._fast_validate(
                    bundle_verifier_bytes=mutated.encode("utf-8")
                )
                self.assertIn("V9 bundle verifier hash drift", errors)
                self.assertTrue(
                    any(
                        "bundle verifier contract" in error
                        or "input recovery broadened" in error
                        or "hash drift" in error
                        for error in errors
                    )
                )

    def test_duplicate_keys_and_nonfinite_values_are_rejected(self) -> None:
        template = plan.TEMPLATE_PATH.read_bytes().replace(
            b'"schema_version": 9,',
            b'"schema_version": 9,\n  "schema_version": 9,',
            1,
        )
        errors = self._fast_validate(template_bytes=template)
        self.assertTrue(
            any("invalid V9 request template" in error for error in errors)
        )

        fixture = plan.SOURCE_FIXTURE_PATH.read_bytes().replace(
            b'"actual_v8_runtime_metadata_retained": false',
            b'"actual_v8_runtime_metadata_retained": NaN',
            1,
        )
        errors = self._fast_validate(source_fixture_bytes=fixture)
        self.assertTrue(
            any("invalid V9 source fixture" in error for error in errors)
        )

    def test_frozen_v8_delegate_and_terminal_errors_propagate(self) -> None:
        with mock.patch.object(
            plan.v8_plan,
            "validate_plan",
            return_value=["sentinel plan drift"],
        ), mock.patch.object(
            plan.v8_failure,
            "verify",
            return_value=[],
        ):
            errors = plan.validate_plan(verify_git_state=False)
        self.assertIn("frozen V8 plan: sentinel plan drift", errors)

        with mock.patch.object(
            plan.v8_plan,
            "validate_plan",
            return_value=[],
        ), mock.patch.object(
            plan.v8_failure,
            "verify",
            return_value=["sentinel evidence drift"],
        ):
            errors = plan.validate_plan(verify_git_state=False)
        self.assertIn(
            "V8 terminal evidence: sentinel evidence drift",
            errors,
        )

    def test_state_classifier_is_fail_closed(self) -> None:
        self.assertEqual(
            plan.classify_plan_state(
                plan_errors=[],
                active_exists=False,
                additions=[],
                active_git_errors=[],
            ),
            "PREPARED_V9_NOT_TRIGGERED",
        )
        self.assertEqual(
            plan.classify_plan_state(
                plan_errors=[],
                active_exists=True,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V9_ARMED_OR_TRIGGERED_EXACT",
        )
        self.assertEqual(
            plan.classify_plan_state(
                plan_errors=[],
                active_exists=False,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V9_CONSUMED_OR_INVALID",
        )
        for kwargs in (
            {
                "plan_errors": ["drift"],
                "active_exists": False,
                "additions": [],
                "active_git_errors": [],
            },
            {
                "plan_errors": [],
                "active_exists": True,
                "additions": [],
                "active_git_errors": [],
            },
            {
                "plan_errors": [],
                "active_exists": True,
                "additions": ["a" * 40, "b" * 40],
                "active_git_errors": [],
            },
            {
                "plan_errors": [],
                "active_exists": True,
                "additions": ["a" * 40],
                "active_git_errors": ["drift"],
            },
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(
                    plan.classify_plan_state(**kwargs),
                    "INVALID",
                )

    def test_active_request_git_history_survives_later_receipt_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)

            relative = Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v9.json"
            )
            request_path = root / relative
            request_path.parent.mkdir(parents=True)
            template = plan.TEMPLATE_PATH.read_bytes()
            request = template.replace(
                b"__DIRECT_PARENT_COMMIT__",
                parent.encode("ascii"),
            )
            request_path.write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "activate")
            self.assertEqual(
                plan._validate_active_request(
                    request,
                    template,
                    plan_parent=parent,
                    verify_git_state=True,
                    root=root,
                    request_path=relative,
                ),
                [],
            )

            (root / "receipt").write_text("accepted\n", encoding="utf-8")
            self._git(root, "add", "receipt")
            self._git(root, "commit", "-q", "-m", "receipt")
            self.assertEqual(
                plan._validate_active_request(
                    request,
                    template,
                    plan_parent=parent,
                    verify_git_state=True,
                    root=root,
                    request_path=relative,
                ),
                [],
            )

            request_path.unlink()
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "delete request")
            request_path.write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "readd request")
            errors = plan._validate_active_request(
                request,
                template,
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V9 active request addition history is not unique",
                errors,
            )

    def test_activation_request_bytes_cannot_be_repaired_later(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative = Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v9.json"
            )
            request_path = root / relative
            request_path.parent.mkdir(parents=True)
            template = plan.TEMPLATE_PATH.read_bytes()
            request = template.replace(
                b"__DIRECT_PARENT_COMMIT__",
                parent.encode("ascii"),
            )
            tampered = json.loads(request)
            tampered["artifact_retention_days"] = 2
            request_path.write_bytes(self._json_bytes(tampered))
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "activate tampered")
            request_path.write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair request")

            errors = plan._validate_active_request(
                request,
                template,
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V9 request activation bytes differ from reviewed request",
                errors,
            )

    def test_activation_request_mode_cannot_be_repaired_later(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative = Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v9.json"
            )
            request_path = root / relative
            request_path.parent.mkdir(parents=True)
            template = plan.TEMPLATE_PATH.read_bytes()
            request = template.replace(
                b"__DIRECT_PARENT_COMMIT__",
                parent.encode("ascii"),
            )
            request_path.write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "update-index", "--chmod=+x", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "activate executable")
            self._git(root, "update-index", "--chmod=-x", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair mode")

            errors = plan._validate_active_request(
                request,
                template,
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V9 request activation mode is not 100644",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
