from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_export_plan_v6 as verifier  # noqa: E402


class AdminDependencyCacheExportPlanV6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = verifier.WORKFLOW_PATH.read_bytes()
        cls.template = verifier.TEMPLATE_PATH.read_bytes()
        cls.transient = verifier.TRANSIENT_VERIFIER_PATH.read_bytes()
        cls.cleanup = verifier.CLEANUP_HELPER_PATH.read_bytes()
        cls.fixture = verifier.PROVENANCE_FIXTURE_PATH.read_bytes()
        cls.rawjson_fixture = verifier.RAWJSON_FIXTURE_PATH.read_bytes()
        cls.structural_fixture = (
            verifier.STRUCTURAL_FIXTURE_PATH.read_bytes()
        )

    def test_exact_v6_plan_passes_before_and_after_activation(self) -> None:
        self.assertEqual(verifier.validate_plan(), [])
        if verifier.ACTIVE_REQUEST_PATH.exists():
            self.assertEqual(
                verifier.plan_state(),
                "V6_ARMED_OR_TRIGGERED_EXACT",
            )
            self.assertEqual(len(verifier._request_additions()), 1)
        else:
            self.assertEqual(
                verifier.plan_state(),
                "PREPARED_V6_NOT_TRIGGERED",
            )
            self.assertEqual(verifier._request_additions(), [])

    def test_state_classification_keeps_consumed_distinct(self) -> None:
        self.assertEqual(
            verifier.classify_plan_state(
                plan_errors=[],
                active_exists=False,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V6_CONSUMED_OR_INVALID",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                plan_errors=[],
                active_exists=True,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V6_ARMED_OR_TRIGGERED_EXACT",
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

    def test_v5_chain_and_terminal_receipt_are_frozen(self) -> None:
        self.assertEqual(verifier.v5_plan.validate_plan(), [])
        evidence = verifier.v5_failure.load_strict()
        self.assertEqual(verifier.v5_failure.verify(evidence), [])
        self.assertEqual(
            verifier.sha256_bytes(verifier.V5_REQUEST_PATH.read_bytes()),
            verifier.V5_REQUEST_SHA256,
        )
        self.assertEqual(
            verifier.sha256_bytes(
                verifier.V5_FAILURE_EVIDENCE_PATH.read_bytes()
            ),
            verifier.V5_FAILURE_EVIDENCE_SHA256,
        )
        self.assertEqual(
            verifier.v5_plan._request_additions(),
            [verifier.V5_CONTROL_COMMIT],
        )

    def test_workflow_timeout_and_permissions_fail_closed(self) -> None:
        cases = (
            (
                b"timeout-minutes: 120",
                b"timeout-minutes: 121",
                "V6 runtime cap changed",
            ),
            (
                b"permissions:\n  contents: read",
                b"permissions:\n  contents: write",
                "V6 workflow permissions changed",
            ),
            (
                b'NOTEAI_PRE_CLEANUP_BUDGET_SECONDS: "5700"',
                b'NOTEAI_PRE_CLEANUP_BUDGET_SECONDS: "5701"',
                "V6 pre-cleanup budget changed",
            ),
            (
                b'NOTEAI_CLEANUP_BUDGET_SECONDS: "6300"',
                b'NOTEAI_CLEANUP_BUDGET_SECONDS: "6301"',
                "V6 cleanup budget changed",
            ),
            (
                b'NOTEAI_EXPORT_CALL_MAX_SECONDS: "3600"',
                b'NOTEAI_EXPORT_CALL_MAX_SECONDS: "3601"',
                "V6 export call timeout changed",
            ),
            (
                b'NOTEAI_IMPORT_CALL_MAX_SECONDS: "900"',
                b'NOTEAI_IMPORT_CALL_MAX_SECONDS: "901"',
                "V6 import call timeout changed",
            ),
            (
                b'NOTEAI_CLEANUP_COMMAND_TIMEOUT_SECONDS: "15"',
                b'NOTEAI_CLEANUP_COMMAND_TIMEOUT_SECONDS: "16"',
                "V6 cleanup call timeout changed",
            ),
        )
        for old, new, expected in cases:
            with self.subTest(expected=expected):
                broken = self.workflow.replace(old, new, 1)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn("V6 workflow hash drift", errors)
                self.assertIn(expected, errors)

    def test_trigger_branch_and_path_are_exact_singletons(self) -> None:
        cases = (
            (
                (
                    b"    branches:\n"
                    b"      - codex/quality-stabilization-real-chain"
                ),
                (
                    b"    branches:\n"
                    b"      - codex/quality-stabilization-real-chain\n"
                    b"      - main"
                ),
            ),
            (
                (
                    b"    paths:\n"
                    b"      - .github/release-requests/"
                    b"admin-5335bda-dependency-cache-v6.json"
                ),
                (
                    b"    paths:\n"
                    b"      - .github/release-requests/"
                    b"admin-5335bda-dependency-cache-v6.json\n"
                    b"      - .github/workflows/**"
                ),
            ),
        )
        for old, new in cases:
            with self.subTest(old=old):
                self.assertIn(old, self.workflow)
                errors = verifier.validate_plan(
                    workflow_bytes=self.workflow.replace(old, new, 1)
                )
                self.assertIn("V6 workflow hash drift", errors)
                self.assertIn("V6 trigger block changed", errors)

    def test_deadline_wrappers_and_atomic_baseline_fail_closed(self) -> None:
        cases = (
            (
                b"--kill-after=15s",
                b"--kill-after=16s",
                "V6 cleanup headroom control changed",
            ),
            (
                (
                    b"    steps:\n"
                    b"      - name: Initialize V6 bounded job deadlines"
                ),
                (
                    b"    steps:\n"
                    b"      - name: Delayed V6 bounded job deadlines"
                ),
                "V6 deadline is not initialized before checkout",
            ),
            (
                (
                    b'run_before_cleanup_deadline \\\n'
                    b'            "${NOTEAI_EXPORT_CALL_MAX_SECONDS}" \\\n'
                    b'            "${NOTEAI_EXPORT_HELPER_PATH}"'
                ),
                (
                    b'run_before_cleanup_deadline \\\n'
                    b'            "${NOTEAI_SETUP_CALL_MAX_SECONDS}" \\\n'
                    b'            "${NOTEAI_EXPORT_HELPER_PATH}"'
                ),
                "V6 helper timeout envelope changed",
            ),
            (
                b'LC_ALL=C sort -u > "${images_before}.tmp"',
                b'LC_ALL=C sort -u > "${images_before}"',
                (
                    "V6 workflow contract missing: "
                    'LC_ALL=C sort -u > "${images_before}.tmp"'
                ),
            ),
            (
                b'mv -- "${baseline_marker}.tmp" "${baseline_marker}"',
                b'true # baseline marker not committed',
                (
                    "V6 workflow contract missing: "
                    'mv -- "${baseline_marker}.tmp" "${baseline_marker}"'
                ),
            ),
        )
        for old, new, expected in cases:
            with self.subTest(expected=expected):
                broken = self.workflow.replace(old, new, 1)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn("V6 workflow hash drift", errors)
                self.assertIn(expected, errors)

    def test_all_four_baselines_and_final_marker_order_fail_closed(self) -> None:
        mutations = (
            (
                b'LC_ALL=C sort -u > "${containers_before}.tmp"',
                b'LC_ALL=C sort -u > "${containers_before}"',
            ),
            (
                b'chmod 0600 "${volumes_before}.tmp"',
                b'chmod 0644 "${volumes_before}.tmp"',
            ),
            (
                b'mv -- "${networks_before}.tmp" "${networks_before}"',
                b'true # network baseline not atomically committed',
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                broken = self.workflow.replace(old, new, 1)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn("V6 workflow hash drift", errors)
                self.assertIn(
                    "V6 Docker baseline atomic sequence changed",
                    errors,
                )

        marker_line = (
            b'          mv -- "${baseline_marker}.tmp" '
            b'"${baseline_marker}"\n'
        )
        network_line = (
            b'          mv -- "${networks_before}.tmp" '
            b'"${networks_before}"\n'
        )
        without_marker = self.workflow.replace(marker_line, b"", 1)
        broken_order = without_marker.replace(
            network_line,
            marker_line + network_line,
            1,
        )
        errors = verifier.validate_plan(workflow_bytes=broken_order)
        self.assertIn("V6 workflow hash drift", errors)
        self.assertIn(
            "V6 Docker baseline atomic sequence changed",
            errors,
        )

    def test_provenance_driver_option_matrix_fails_closed(self) -> None:
        exact = b'--driver-opt "provenance-add-gha=false"'
        mutations = (
            b'--driver-opt "provenance-add-gha=true"',
            b'--driver-opt "provenance-add-gha=0"',
            b'--driver-opt "provenance-add-gha=False"',
            b'--driver-opt "provenance-add-gha=FALSE"',
            b'--driver-opt "provenance_add_gha=false"',
            b'--driver-opt "provenance-add-gha="',
            b'--driver-opt "network=host"',
        )
        for replacement in mutations:
            with self.subTest(replacement=replacement):
                broken = self.workflow.replace(exact, replacement, 1)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn("V6 isolated builder options changed", errors)
                self.assertIn("V6 provenance driver option changed", errors)
        duplicated = self.workflow.replace(
            exact,
            exact + b" \\\n            " + exact,
            1,
        )
        self.assertIn(
            "V6 isolated builder options changed",
            verifier.validate_plan(workflow_bytes=duplicated),
        )
        extra = self.workflow.replace(
            exact,
            exact + b' \\\n            --driver-opt "default-load=true"',
            1,
        )
        self.assertIn(
            "V6 isolated builder options changed",
            verifier.validate_plan(workflow_bytes=extra),
        )

    def test_both_builders_and_exact_option_order_are_required(self) -> None:
        image = b'--driver-opt "image=${NOTEAI_BUILDKIT_IMAGE}"'
        provenance = b'--driver-opt "provenance-add-gha=false"'
        ordered = image + b" \\\n            " + provenance
        reversed_options = provenance + b" \\\n            " + image
        broken = self.workflow.replace(ordered, reversed_options, 1)
        self.assertIn(
            "V6 isolated builder options changed",
            verifier.validate_plan(workflow_bytes=broken),
        )
        missing_consumer = self.workflow.rsplit(provenance, 1)
        broken = missing_consumer[0] + b"--driver-opt \"missing=false\"" + missing_consumer[1]
        errors = verifier.validate_plan(workflow_bytes=broken)
        self.assertIn("V6 isolated builder options changed", errors)
        self.assertIn("V6 provenance driver option changed", errors)

    def test_provenance_gate_shape_and_order_fail_closed(self) -> None:
        cases = (
            (
                b'"${root}"/.[!.]*.json',
                b'"${root}"/visible-only.json',
                'V6 provenance gate missing: "${root}"/.[!.]*.json',
            ),
            (
                b"</dev/null >/dev/null 2>&1",
                b"</dev/null",
                "V6 provenance gate missing: </dev/null >/dev/null 2>&1",
            ),
            (
                b'docker exec "${container_name}" sh -eu -c',
                b'docker exec "${NOTEAI_PRODUCER_BUILDER}" sh -eu -c',
                (
                    "V6 provenance gate missing: "
                    'docker exec "${container_name}" sh -eu -c'
                ),
            ),
        )
        for old, new, expected in cases:
            with self.subTest(expected=expected):
                broken = self.workflow.replace(old, new, 1)
                self.assertIn(
                    expected,
                    verifier.validate_plan(workflow_bytes=broken),
                )

    def test_bypass_controls_are_forbidden(self) -> None:
        anchor = b"      BUILDX_METADATA_PROVENANCE: max"
        mutations = (
            b"      BUILDX_METADATA_PROVENANCE: min",
            anchor + b"\n      BUILDX_NO_DEFAULT_ATTESTATIONS: 1",
            anchor + b"\n      GITHUB_ACTIONS: false",
            anchor + b'\n      GITHUB_EVENT_NAME: ""',
        )
        for replacement in mutations:
            with self.subTest(replacement=replacement):
                broken = self.workflow.replace(anchor, replacement, 1)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertTrue(
                    "V6 workflow hash drift" in errors
                    and (
                        "V6 workflow forbidden token: "
                        in "\n".join(errors)
                        or "V6 workflow contract missing" in "\n".join(errors)
                        or "V6 max provenance setting changed" in errors
                    )
                )

    def test_client_token_control_requires_exact_job_wide_value(self) -> None:
        client_token_key = b"BUILDKIT_NO_CLIENT_TOKEN"
        for replacement in (b'"0"', b'"true"', b"1", b'"01"'):
            with self.subTest(replacement=replacement):
                broken = self.workflow.replace(
                    client_token_key + b': "1"',
                    client_token_key + b": " + replacement,
                    1,
                )
                self.assertIn(
                    "V6 client-token control changed",
                    verifier.validate_plan(workflow_bytes=broken),
                )

    def test_transient_cleanup_and_fixture_mutations_fail_closed(self) -> None:
        broken_transient = self.transient.replace(
            b'"provenance-add-gha": "false"',
            b'"provenance-add-gha": "true"',
            1,
        )
        self.assertIn(
            "V6 transient verifier hash drift",
            verifier.validate_plan(
                transient_verifier_bytes=broken_transient
            ),
        )
        broken_cleanup = self.cleanup.replace(
            b"cleanup_effective",
            b"cleanup_skipped",
        )
        errors = verifier.validate_plan(cleanup_helper_bytes=broken_cleanup)
        self.assertIn("V6 cleanup helper hash drift", errors)
        self.assertIn(
            "V6 cleanup contract missing: cleanup_effective",
            errors,
        )
        fixture_payload = json.loads(self.fixture)
        fixture_payload["actual_v5_runtime_metadata_retained"] = True
        broken_fixture = json.dumps(fixture_payload).encode()
        errors = verifier.validate_plan(
            provenance_fixture_bytes=broken_fixture
        )
        self.assertIn("V6 provenance source fixture hash drift", errors)
        self.assertIn(
            "V6 provenance fixture overclaims runtime evidence",
            errors,
        )
        rawjson = json.loads(self.rawjson_fixture)
        rawjson["actual_v5_runtime_progress_retained"] = True
        errors = verifier.validate_plan(
            rawjson_fixture_bytes=json.dumps(rawjson).encode()
        )
        self.assertIn("V6 rawjson source fixture hash drift", errors)
        self.assertIn("V6 rawjson source projection changed", errors)

        structural = json.loads(self.structural_fixture)
        structural["v6_binding_contract"]["ordered_chain"].reverse()
        errors = verifier.validate_plan(
            structural_fixture_bytes=json.dumps(structural).encode()
        )
        self.assertIn("V6 structural source fixture hash drift", errors)
        self.assertIn("V6 structural source projection changed", errors)

    def test_three_layer_bundle_trust_matrix_fails_closed(self) -> None:
        cases = (
            (
                b"tools/verify_admin_dependency_cache_bundle.py",
                b"tools/verify_admin_dependency_cache_bundle-bad.py",
            ),
            (
                verifier.BASE_BUNDLE_VERIFIER_SHA256.encode(),
                b"0" * 64,
            ),
            (
                b"tools/verify_admin_dependency_cache_bundle_v3.py",
                b"tools/verify_admin_dependency_cache_bundle_v2.py",
            ),
            (
                verifier.V3_BUNDLE_VERIFIER_SHA256.encode(),
                b"1" * 64,
            ),
            (
                b"tools/verify_admin_dependency_cache_bundle_v6.py",
                b"tools/verify_admin_dependency_cache_bundle_v3.py",
            ),
            (
                verifier.BUNDLE_VERIFIER_SHA256.encode(),
                b"2" * 64,
            ),
            (
                (
                    b"NOTEAI_V3_BUNDLE_VERIFIER_PATH: "
                    b"${{ steps.control.outputs.v3_verifier_copy }}"
                ),
                (
                    b"NOTEAI_V3_BUNDLE_VERIFIER_PATH: "
                    b"${{ steps.control.outputs.base_verifier_copy }}"
                ),
            ),
            (
                (
                    b"NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH: "
                    b"${{ steps.control.outputs.bundle_verifier_copy }}"
                ),
                (
                    b"NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH: "
                    b"${{ steps.control.outputs.v3_verifier_copy }}"
                ),
            ),
            (
                (
                    b'"${{ steps.control.outputs.bundle_verifier_copy }}" \\\n'
                    b"            verify-final"
                ),
                (
                    b'"${{ steps.control.outputs.v3_verifier_copy }}" \\\n'
                    b"            verify-final"
                ),
            ),
        )
        for old, new in cases:
            with self.subTest(old=old):
                self.assertIn(old, self.workflow)
                broken = self.workflow.replace(old, new, 1)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn("V6 workflow hash drift", errors)
                self.assertIn(
                    "V6 three-layer bundle trust matrix changed",
                    errors,
                )

    def test_outer_v6_and_frozen_inner_v5_namespaces_fail_closed(
        self,
    ) -> None:
        inner_cases = (
            (
                b"noteai-empty-docker-config-v5",
                b"noteai-empty-docker-config-v6",
            ),
            (
                b"noteai-buildx-state-v5",
                b"noteai-buildx-state-v6",
            ),
            (
                b"noteai-admin-cache-v5-producer-",
                b"noteai-admin-cache-v6-producer-",
            ),
            (
                b"noteai-docker-baseline-v5.complete",
                b"noteai-docker-baseline-v6.complete",
            ),
            (
                b"noteai-admin-dependency-cache-cleanup-v5.json",
                b"noteai-admin-dependency-cache-cleanup-v6.json",
            ),
        )
        for old, new in inner_cases:
            with self.subTest(inner=old):
                broken = self.workflow.replace(old, new)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn(
                    "V6 frozen V5 runtime namespace changed",
                    errors,
                )

        outer_cases = (
            (
                b"admin-dependency-prefix-cache-5335bda-v6",
                b"admin-dependency-prefix-cache-5335bda-v5",
            ),
            (
                b"noteai-admin-dependency-cache-bundle-v6",
                b"noteai-admin-dependency-cache-bundle-v5",
            ),
            (
                b"unused-v6-import-evidence",
                b"unused-v5-import-evidence",
            ),
            (
                b"noteai-final-cache-v6-validation",
                b"noteai-final-cache-v5-validation",
            ),
        )
        for old, new in outer_cases:
            with self.subTest(outer=old):
                broken = self.workflow.replace(old, new)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertTrue(
                    "V6 outer workflow identity changed" in errors
                    or "V6 outer workflow retains V5 identity" in errors
                )

    def test_authorized_caps_and_predecessor_chain_fail_closed(self) -> None:
        cap_cases = (
            (b"github_actions_maximum_run_count == 1", b"== 2"),
            (
                b"artifact_compressed_maximum_bytes == 3758096384",
                b"artifact_compressed_maximum_bytes == 3758096385",
            ),
            (
                b"authenticated_artifact_download_maximum_count == 1",
                b"authenticated_artifact_download_maximum_count == 2",
            ),
            (
                b"cross_provider_transfer_maximum_count == 1",
                b"cross_provider_transfer_maximum_count == 2",
            ),
        )
        for old, new in cap_cases:
            with self.subTest(cap=old):
                broken = self.workflow.replace(old, new, 1)
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn(
                    "V6 authorized artifact bounds changed",
                    errors,
                )

        predecessor_cases = (
            verifier.V5_PLAN_PARENT,
            verifier.V5_CONTROL_COMMIT,
            verifier.V5_REQUEST_SHA256,
            verifier.V5_FAILURE_EVIDENCE_SHA256,
            verifier.V5_FAILURE_VERIFIER_SHA256,
            verifier.RAWJSON_FIXTURE_SHA256,
        )
        for value in predecessor_cases:
            with self.subTest(predecessor=value):
                broken = self.workflow.replace(
                    value.encode(),
                    b"f" * len(value),
                    1,
                )
                errors = verifier.validate_plan(workflow_bytes=broken)
                self.assertIn(
                    "V6 predecessor terminal chain changed",
                    errors,
                )

    def test_template_predecessor_limits_and_authority_fail_closed(self) -> None:
        mutations = (
            ("predecessor", "run_id", 30606218503),
            ("predecessor", "artifact_count", 1),
            ("predecessor", "rerun_authorized", True),
            ("recovery_basis", "export_call_maximum_seconds", 3601),
            ("recovery_basis", "atomic_docker_baseline_required", False),
            (None, "artifact_retention_days", 2),
            (None, "github_actions_maximum_run_count", 2),
            (None, "artifact_compressed_maximum_bytes", 3_758_096_385),
            (None, "artifact_input_maximum_bytes", 4_026_531_841),
            (
                None,
                "authenticated_artifact_download_maximum_count",
                2,
            ),
            (None, "cross_provider_transfer_maximum_count", 2),
            (None, "registry_publication_authorized", True),
            (None, "deployment_authorized", True),
        )
        for parent, key, value in mutations:
            with self.subTest(parent=parent, key=key):
                payload = json.loads(self.template)
                target = payload if parent is None else payload[parent]
                target[key] = value
                broken = json.dumps(payload, indent=2).encode() + b"\n"
                errors = verifier.validate_plan(template_bytes=broken)
                self.assertIn("V6 template hash drift", errors)
                self.assertIn("V6 request template drift", errors)

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
            "V6 active request does not bind its direct parent",
            errors,
        )

    def test_git_history_requires_one_request_only_addition_across_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path = Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v6.json"
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
            run("branch", "retained-activation")
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
                "V6 active request addition history is not unique",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
