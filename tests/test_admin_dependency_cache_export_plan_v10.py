from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_export_plan_v10 as plan  # noqa: E402


class AdminDependencyCacheExportPlanV10Tests(unittest.TestCase):
    def _fast_validate(self, **kwargs) -> list[str]:
        kwargs.setdefault("verify_git_state", False)
        with mock.patch.object(
            plan.v9_plan,
            "validate_plan",
            return_value=[],
        ), mock.patch.object(
            plan.v9_failure,
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

    @staticmethod
    def _workflow_run(name: str) -> str:
        workflow = yaml.load(
            plan.WORKFLOW_PATH.read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        for step in workflow["jobs"]["export-cache"]["steps"]:
            if step.get("name") == name:
                return step["run"]
        raise AssertionError(f"workflow step not found: {name}")

    def _initialize_activation_repository(self, root: Path) -> str:
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "NoteAI Test")
        self._git(root, "config", "user.email", "noteai@example.invalid")
        (root / "README").write_text("base\n", encoding="utf-8")
        self._git(root, "add", "README")
        self._git(root, "commit", "-q", "-m", "seed")
        for relative, _expected_sha256 in plan.FROZEN_ACTIVATION_FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((plan.ROOT / relative).read_bytes())
        self._git(root, "add", ".")
        self._git(root, "commit", "-q", "-m", "frozen anchor")
        return self._git(root, "rev-parse", "HEAD")

    def _request(self, parent: str) -> bytes:
        return plan.TEMPLATE_PATH.read_bytes().replace(
            b"__DIRECT_PARENT_COMMIT__",
            parent.encode("ascii"),
        )

    def _activate(
        self,
        root: Path,
        parent: str,
        *,
        mode: str = "100644",
        request: bytes | None = None,
    ) -> tuple[Path, bytes]:
        relative = Path(
            ".github/release-requests/"
            "admin-5335bda-dependency-cache-v10.json"
        )
        request_path = root / relative
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request = self._request(parent) if request is None else request
        request_path.write_bytes(request)
        self._git(root, "add", relative.as_posix())
        if mode == "100755":
            self._git(root, "update-index", "--chmod=+x", relative.as_posix())
        self._git(root, "commit", "-q", "-m", "activate")
        return relative, request

    def test_exact_plan_passes_before_and_after_activation(self) -> None:
        self.assertEqual(plan.validate_plan(), [])
        if plan.ACTIVE_REQUEST_PATH.exists():
            self.assertEqual(plan.plan_state(), "V10_ARMED_OR_TRIGGERED_EXACT")
            self.assertEqual(len(plan._request_additions()), 1)
        else:
            self.assertEqual(plan.plan_state(), "PREPARED_V10_NOT_TRIGGERED")
            self.assertEqual(plan._request_additions(), [])

    def test_exact_hash_closure_is_frozen(self) -> None:
        expected = {
            plan.WORKFLOW_PATH: plan.WORKFLOW_SHA256,
            plan.TEMPLATE_PATH: plan.TEMPLATE_SHA256,
            plan.SOURCE_FIXTURE_PATH: plan.SOURCE_FIXTURE_SHA256,
            plan.BUNDLE_VERIFIER_PATH: plan.BUNDLE_VERIFIER_SHA256,
            plan.IMPORT_HELPER_PATH: plan.IMPORT_HELPER_SHA256,
            plan.V9_IMPORT_HELPER_PATH: plan.V9_IMPORT_HELPER_SHA256,
            plan.EXPORT_HELPER_PATH: plan.EXPORT_HELPER_SHA256,
            plan.V9_WORKFLOW_PATH: plan.V9_WORKFLOW_SHA256,
            plan.V9_TEMPLATE_PATH: plan.V9_TEMPLATE_SHA256,
            plan.V9_REQUEST_PATH: plan.V9_REQUEST_SHA256,
            plan.V9_PLAN_VERIFIER_PATH: plan.V9_PLAN_VERIFIER_SHA256,
            plan.V9_BUNDLE_VERIFIER_PATH: plan.V9_BUNDLE_VERIFIER_SHA256,
            plan.V9_FAILURE_EVIDENCE_PATH: plan.V9_FAILURE_EVIDENCE_SHA256,
            plan.V9_FAILURE_VERIFIER_PATH: plan.V9_FAILURE_VERIFIER_SHA256,
        }
        for path, expected_hash in expected.items():
            with self.subTest(path=path.name):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    expected_hash,
                )
        self.assertEqual(
            hashlib.sha256(Path(plan.__file__).read_bytes()).hexdigest(),
            "6e89496a983151a953560083c7c327d7c98847f77ed09cb027755f8f1d65c136",
        )
        self.assertEqual(len(plan.LEGACY_FROZEN_PATHS), 70)
        self.assertEqual(len(set(plan.LEGACY_FROZEN_PATHS)), 70)
        for required in (
            Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v2.json"
            ),
            Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v9.json"
            ),
            Path("tools/verify_admin_dependency_cache_export_plan.py"),
            Path("tools/verify_admin_dependency_cache_export_plan_v9.py"),
            Path("tools/verify_admin_dependency_cache_v9_failure_evidence.py"),
        ):
            self.assertIn(required, plan.LEGACY_FROZEN_PATHS)

    def test_import_helper_is_the_only_allowlisted_v9_delta(self) -> None:
        v9_bytes = plan.V9_IMPORT_HELPER_PATH.read_bytes()
        v10_bytes = plan.IMPORT_HELPER_PATH.read_bytes()
        export_bytes = plan.EXPORT_HELPER_PATH.read_bytes()
        self.assertEqual(plan.expected_v10_import_helper(v9_bytes), v10_bytes)
        self.assertEqual(
            hashlib.sha256(
                plan._producer_build_projection(export_bytes)
            ).hexdigest(),
            plan.PRODUCER_BUILD_PROJECTION_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(
                plan._full_replay_projection(v10_bytes)
            ).hexdigest(),
            plan.FULL_REPLAY_PROJECTION_SHA256,
        )
        self.assertEqual(
            plan._full_replay_projection(v10_bytes),
            plan._full_replay_projection(v9_bytes),
        )
        self.assertEqual(v10_bytes.count(b"--target runtime-common"), 1)
        self.assertEqual(v10_bytes.count(b"--target noteai-cache-observer"), 1)
        self.assertEqual(v10_bytes.count(b"--cache-from"), 1)
        self.assertNotIn(b"--no-cache-filter", v10_bytes)
        self.assertNotIn(b"noteai-cache-observer", export_bytes)

    def test_workflow_is_request_only_bounded_and_cleanup_ordered(self) -> None:
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
            "permissions: write",
            "docker login",
            "docker push",
            "NOTEAI_V10_PLAN_VERIFIER_PATH",
        ):
            self.assertNotIn(forbidden, workflow)
        self.assertEqual(workflow.count("docker buildx create \\"), 2)
        self.assertEqual(workflow.count('test "${GITHUB_RUN_ATTEMPT}" = "1"'), 3)
        self.assertEqual(workflow.count("uses: actions/upload-artifact@"), 1)
        self.assertEqual(workflow.count("retention-days: 1"), 1)
        self.assertEqual(
            workflow.count(
                "git log --all --full-history -m --no-renames --diff-filter=A"
            ),
            2,
        )
        self.assertEqual(workflow.count("awk '!seen[$0]++'"), 2)
        self.assertEqual(workflow.count("legacy_frozen_paths=("), 1)
        self.assertEqual(workflow.count("v10_frozen_paths=("), 1)
        self.assertEqual(workflow.count("v10_frozen_anchor_record"), 2)
        self.assertEqual(workflow.count("actions: read"), 1)
        self.assertEqual(
            workflow.count("group: admin-dependency-cache-export-v10\n"),
            1,
        )
        for forbidden_filter in (
            '--data-urlencode "branch=',
            '--data-urlencode "event=',
            '--data-urlencode "head_sha=',
            '--data-urlencode "exclude_pull_requests=',
        ):
            self.assertNotIn(forbidden_filter, workflow)
        self.assertEqual(
            workflow.count("NOTEAI_ACTIONS_READ_TOKEN: ${{ github.token }}"),
            1,
        )
        self.assertNotIn(
            "NOTEAI_ACTIONS_READ_TOKEN",
            workflow.split("\n    steps:", 1)[0],
        )
        self.assertEqual(
            workflow.split("permissions:\n", 1)[1].split(
                "\n\nconcurrency:",
                1,
            )[0],
            "  contents: read\n  actions: read",
        )
        self.assertEqual(
            plan._workflow_literal_path_array(workflow, "legacy_frozen_paths"),
            plan.LEGACY_FROZEN_PATHS,
        )
        self.assertEqual(
            plan._workflow_literal_path_array(workflow, "v10_frozen_paths"),
            tuple(path for path, _sha256 in plan.FROZEN_ACTIVATION_FILES),
        )
        cleanup = workflow.index("Remove V10 builders and all transient Docker state")
        upload = workflow.index(
            "Upload one-day V10 public-repository dependency cache artifact"
        )
        remove = workflow.index("Remove runner-local V10 bundle")
        self.assertLess(cleanup, upload)
        self.assertLess(upload, remove)

    def test_unique_run_ledger_executes_fail_closed_state_machine(self) -> None:
        run_script = self._workflow_run(
            "Prove this is the unique V10 workflow run for the branch lifecycle"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            fake_curl = binary_dir / "curl"
            fake_curl.write_text(
                """#!/usr/bin/env python3
import json
import os
from pathlib import Path

state = Path(os.environ["FAKE_CURL_STATE"])
count = int(state.read_text() or "0") if state.exists() else 0
count += 1
state.write_text(str(count))
mode = os.environ["FAKE_CURL_MODE"]
if mode == "timeout":
    raise SystemExit(28)
run = {
    "id": int(os.environ["GITHUB_RUN_ID"]),
    "run_attempt": 1,
    "head_sha": os.environ["GITHUB_SHA"],
    "head_branch": os.environ["GITHUB_REF_NAME"],
    "event": "push",
}
if mode == "zero_then_one" and count == 1:
    payload = {"total_count": 0, "workflow_runs": []}
elif mode == "always_zero":
    payload = {"total_count": 0, "workflow_runs": []}
elif mode == "duplicate":
    other = dict(run)
    other["id"] += 1
    payload = {"total_count": 2, "workflow_runs": [run, other]}
elif mode == "wrong":
    run["id"] += 1
    run["run_attempt"] = 2
    payload = {"total_count": 1, "workflow_runs": [run]}
else:
    payload = {"total_count": 1, "workflow_runs": [run]}
print(json.dumps(payload, separators=(",", ":")))
""",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            state = root / "curl-state"
            environment = dict(os.environ)
            environment.update(
                {
                    "PATH": f"{binary_dir}:{environment['PATH']}",
                    "RUNNER_TEMP": str(root),
                    "FAKE_CURL_STATE": str(state),
                    "GITHUB_EVENT_NAME": "push",
                    "GITHUB_REF_NAME": "codex/quality-stabilization-real-chain",
                    "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_RUN_ID": "12345",
                    "GITHUB_SHA": "a" * 40,
                    "GITHUB_REPOSITORY": "example/noteai",
                    "NOTEAI_ACTIONS_READ_TOKEN": "test-token",
                    "NOTEAI_PRE_CLEANUP_DEADLINE_EPOCH": str(
                        int(time.time()) + 30
                    ),
                    "NOTEAI_RUN_LEDGER_BUDGET_SECONDS": "20",
                    "NOTEAI_RUN_LEDGER_CALL_MAX_SECONDS": "2",
                    "NOTEAI_RUN_LEDGER_CONNECT_TIMEOUT_SECONDS": "1",
                    "NOTEAI_RUN_LEDGER_MAX_OBSERVATIONS": "3",
                    "NOTEAI_RUN_LEDGER_PAGE_MAXIMUM": "2",
                    "NOTEAI_RUN_LEDGER_POLL_SECONDS": "0",
                    "NOTEAI_RUN_LEDGER_RETRY_DELAY_SECONDS": "0",
                    "NOTEAI_RUN_LEDGER_RETRY_MAXIMUM": "0",
                }
            )

            def execute(mode: str) -> subprocess.CompletedProcess[str]:
                state.unlink(missing_ok=True)
                environment["FAKE_CURL_MODE"] = mode
                return subprocess.run(
                    ["bash"],
                    input=run_script,
                    cwd=root,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )

            result = execute("zero_then_one")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(state.read_text(encoding="utf-8"), "2")

            result = execute("duplicate")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(state.read_text(encoding="utf-8"), "1")

            self.assertNotEqual(execute("wrong").returncode, 0)
            self.assertNotEqual(execute("timeout").returncode, 0)
            result = execute("always_zero")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(state.read_text(encoding="utf-8"), "3")

    def test_exact_derived_active_request_passes_without_git(self) -> None:
        parent = "a" * 40
        request = self._request(parent)
        self.assertEqual(
            self._fast_validate(
                active_request_bytes=request,
                active_plan_parent=parent,
            ),
            [],
        )

    def test_active_request_parent_bytes_and_semantics_fail_closed(self) -> None:
        parent = "a" * 40
        request = self._request(parent)
        errors = self._fast_validate(
            active_request_bytes=request,
            active_plan_parent="b" * 40,
        )
        self.assertIn("V10 active request does not bind its direct parent", errors)

        payload = json.loads(request)
        payload["task"] = "changed"
        errors = self._fast_validate(
            active_request_bytes=self._json_bytes(payload),
            active_plan_parent=parent,
        )
        self.assertIn("V10 active request differs from reviewed template", errors)
        self.assertIn("V10 active request semantics drift", errors)

        payload["plan_checkpoint_commit"] = "not-a-commit"
        errors = self._fast_validate(active_request_bytes=self._json_bytes(payload))
        self.assertIn("V10 active request checkpoint is invalid", errors)

    def test_workflow_template_fixture_and_verifier_mutations_fail(self) -> None:
        workflow = plan.WORKFLOW_PATH.read_bytes()
        template = plan.TEMPLATE_PATH.read_bytes()
        fixture = plan.SOURCE_FIXTURE_PATH.read_bytes()
        bundle = plan.BUNDLE_VERIFIER_PATH.read_bytes()
        helper = plan.IMPORT_HELPER_PATH.read_bytes()
        cases = (
            ("workflow", {"workflow_bytes": workflow.replace(b"timeout-minutes: 120", b"timeout-minutes: 121", 1)}, "V10 workflow hash drift"),
            ("template", {"template_bytes": template.replace(b'"artifact_retention_days": 1', b'"artifact_retention_days": 2', 1)}, "V10 template hash drift"),
            ("fixture", {"source_fixture_bytes": fixture.replace(b'"consumer_only_observer_required": true', b'"consumer_only_observer_required": false', 1)}, "V10 input-omission source fixture hash drift"),
            ("bundle", {"bundle_verifier_bytes": bundle.replace(b"OBSERVER_SUFFIX", b"OBSERVER_SUFFIX_TAMPERED", 1)}, "V10 bundle verifier hash drift"),
            ("helper", {"import_helper_bytes": helper.replace(b"noteai-cache-observer", b"noteai-cache-tampered", 1)}, "V10 import helper hash drift"),
        )
        for label, kwargs, expected_error in cases:
            with self.subTest(label=label):
                errors = self._fast_validate(**kwargs)
                self.assertIn(expected_error, errors)

        legacy_drift = workflow.replace(
            b"admin-5335bda-dependency-cache-v2.json",
            b"admin-5335bda-dependency-cache-v0.json",
            1,
        )
        errors = self._fast_validate(workflow_bytes=legacy_drift)
        self.assertIn("V10 workflow hash drift", errors)
        self.assertIn("V10 workflow legacy frozen authority set changed", errors)

        runtime_drift = workflow.replace(
            b'            "tools/verify_admin_dependency_cache_bundle_v10.py"\n'
            b'            "scripts/ci/import_admin_dependency_cache_v10.sh"',
            b'            "tools/verify_admin_dependency_cache_bundle_v11.py"\n'
            b'            "scripts/ci/import_admin_dependency_cache_v10.sh"',
            1,
        )
        errors = self._fast_validate(workflow_bytes=runtime_drift)
        self.assertIn("V10 workflow hash drift", errors)
        self.assertIn("V10 workflow runtime frozen authority set changed", errors)

        duplicate_run_drift = workflow.replace(
            b"(( ledger_total <= 1 ))",
            b"(( ledger_total >= 0 ))",
            1,
        )
        errors = self._fast_validate(workflow_bytes=duplicate_run_drift)
        self.assertIn("V10 workflow hash drift", errors)
        self.assertIn(
            "V10 workflow contract missing: (( ledger_total <= 1 ))",
            errors,
        )

    def test_helper_and_producer_projection_mutations_fail_closed(self) -> None:
        helper = plan.IMPORT_HELPER_PATH.read_bytes().replace(
            b"--target noteai-cache-observer",
            b"--target runtime-common        ",
            1,
        )
        errors = self._fast_validate(import_helper_bytes=helper)
        self.assertIn("V10 import helper hash drift", errors)
        self.assertIn(
            "V10 import helper differs from the allowlisted V9 delta",
            errors,
        )

        producer = plan.EXPORT_HELPER_PATH.read_bytes().replace(
            b"--target runtime-common",
            b"--target noteai-observer",
            1,
        )
        errors = self._fast_validate(export_helper_bytes=producer)
        self.assertIn("frozen producer export helper hash drift", errors)
        self.assertIn("frozen producer build command projection changed", errors)

    def test_template_authority_and_projection_mutations_fail_closed(self) -> None:
        original = json.loads(plan.TEMPLATE_PATH.read_text(encoding="utf-8"))
        cases = (
            (("predecessor", "terminal_receipt_commit"), "0" * 40),
            (("recovery_basis", "producer_contains_observer"), True),
            (("recovery_basis", "no_cache_filter_authorized"), True),
            (("build_evidence_recovery", "runtime_pip_cached_false_accepted"), True),
            (("build_evidence_recovery", "full_replay_original_dockerfile_and_target_required"), False),
            (("bundle_verifier_chain", "v10_sha256"), "0" * 64),
            (("github_actions_maximum_run_count",), 2),
            (("deployment_authorized",), True),
            (("database_authorized",), True),
            (("public_traffic_authorized",), True),
        )
        for path, value in cases:
            with self.subTest(path=path):
                payload = copy.deepcopy(original)
                target = payload
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                errors = self._fast_validate(
                    template_bytes=self._json_bytes(payload)
                )
                self.assertIn("V10 template hash drift", errors)

    def test_source_projection_overclaims_fail_closed(self) -> None:
        original = json.loads(
            plan.SOURCE_FIXTURE_PATH.read_text(encoding="utf-8")
        )
        cases = (
            (("actual_v9_runtime_metadata_retained",), True),
            (("runtime_v9_cache_miss_cause_reconstructed",), True),
            (("v10_contract", "producer_cache_contains_observer"), True),
            (("v10_contract", "runtime_pip_cached_false_accepted"), True),
            (("v10_contract", "observer_network_none_enum_required"), 1),
            (("full_replay", "cache_from_local"), True),
        )
        for path, value in cases:
            with self.subTest(path=path):
                payload = copy.deepcopy(original)
                target = payload
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                errors = self._fast_validate(
                    source_fixture_bytes=self._json_bytes(payload)
                )
                self.assertIn(
                    "V10 input-omission source fixture hash drift",
                    errors,
                )
                self.assertIn("V10 cache-observer source projection changed", errors)

    def test_duplicate_keys_and_nonfinite_values_are_rejected(self) -> None:
        template = plan.TEMPLATE_PATH.read_bytes().replace(
            b'"schema_version": 10,',
            b'"schema_version": 10,\n  "schema_version": 10,',
            1,
        )
        errors = self._fast_validate(template_bytes=template)
        self.assertTrue(any("invalid V10 request template" in item for item in errors))

        fixture = plan.SOURCE_FIXTURE_PATH.read_bytes().replace(
            b'"actual_v9_runtime_metadata_retained": false',
            b'"actual_v9_runtime_metadata_retained": NaN',
            1,
        )
        errors = self._fast_validate(source_fixture_bytes=fixture)
        self.assertTrue(any("invalid V10 source fixture" in item for item in errors))

    def test_frozen_v9_delegate_and_terminal_errors_propagate(self) -> None:
        with mock.patch.object(
            plan.v9_plan,
            "validate_plan",
            return_value=["sentinel plan drift"],
        ), mock.patch.object(plan.v9_failure, "verify", return_value=[]):
            errors = plan.validate_plan(verify_git_state=False)
        self.assertIn("frozen V9 plan: sentinel plan drift", errors)

        with mock.patch.object(
            plan.v9_plan,
            "validate_plan",
            return_value=[],
        ), mock.patch.object(
            plan.v9_failure,
            "verify",
            return_value=["sentinel evidence drift"],
        ):
            errors = plan.validate_plan(verify_git_state=False)
        self.assertIn("V9 terminal evidence: sentinel evidence drift", errors)

    def test_state_classifier_is_fail_closed(self) -> None:
        self.assertEqual(
            plan.classify_plan_state(
                plan_errors=[],
                active_exists=False,
                additions=[],
                active_git_errors=[],
            ),
            "PREPARED_V10_NOT_TRIGGERED",
        )
        self.assertEqual(
            plan.classify_plan_state(
                plan_errors=[],
                active_exists=True,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V10_ARMED_OR_TRIGGERED_EXACT",
        )
        self.assertEqual(
            plan.classify_plan_state(
                plan_errors=[],
                active_exists=False,
                additions=["a" * 40],
                active_git_errors=[],
            ),
            "V10_CONSUMED_OR_INVALID",
        )
        invalid = (
            (["drift"], False, [], []),
            ([], True, [], []),
            ([], True, ["a" * 40, "b" * 40], []),
            ([], True, ["a" * 40], ["drift"]),
        )
        for errors, exists, additions, git_errors in invalid:
            self.assertEqual(
                plan.classify_plan_state(
                    plan_errors=errors,
                    active_exists=exists,
                    additions=additions,
                    active_git_errors=git_errors,
                ),
                "INVALID",
            )

    def test_request_addition_query_is_merge_and_rename_aware(self) -> None:
        with mock.patch.object(
            plan,
            "_git_at",
            return_value="a" * 40,
        ) as git_at:
            self.assertEqual(plan._request_additions(), ["a" * 40])
        arguments = git_at.call_args.args
        for required in ("--all", "--full-history", "-m", "--no-renames"):
            self.assertIn(required, arguments)

    def test_active_request_git_history_survives_receipt_and_rejects_readd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative, request = self._activate(root, parent)
            template = plan.TEMPLATE_PATH.read_bytes()
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

            (root / relative).unlink()
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "delete")
            (root / relative).write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "readd")
            errors = plan._validate_active_request(
                request,
                template,
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn("V10 active request addition history is not unique", errors)

    def test_merge_addition_and_nonancestor_activation_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative, request = self._activate(root, parent)
            hidden_activation = self._git(root, "rev-parse", "HEAD")
            self._git(root, "branch", "hidden-activation", hidden_activation)

            self._git(root, "checkout", "-q", "-b", "left", parent)
            (root / "left").write_text("left\n", encoding="utf-8")
            self._git(root, "add", "left")
            self._git(root, "commit", "-q", "-m", "left")
            left = self._git(root, "rev-parse", "HEAD")
            self._git(root, "checkout", "-q", "-b", "right", parent)
            (root / "right").write_text("right\n", encoding="utf-8")
            self._git(root, "add", "right")
            self._git(root, "commit", "-q", "-m", "right")
            self._git(root, "checkout", "-q", "left")
            self._git(root, "merge", "--no-ff", "--no-commit", "right")
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "merge adds request")
            additions = plan._request_additions(
                root=root,
                request_path=relative,
            )
            self.assertEqual(len(additions), 2)
            self.assertIn(hidden_activation, additions)
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn("V10 active request addition history is not unique", errors)

            self._git(root, "checkout", "-q", "-B", "unrelated", parent)
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "unrelated request")
            with mock.patch.object(
                plan,
                "_request_additions",
                return_value=[hidden_activation],
            ):
                errors = plan._validate_active_request(
                    request,
                    plan.TEMPLATE_PATH.read_bytes(),
                    plan_parent=parent,
                    verify_git_state=True,
                    root=root,
                    request_path=relative,
                )
            self.assertIn("V10 activation is not an ancestor of HEAD", errors)

    def test_post_activation_request_and_frozen_file_repairs_are_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative, request = self._activate(root, parent)
            request_path = root / relative
            payload = json.loads(request)
            payload["artifact_retention_days"] = 2
            request_path.write_bytes(self._json_bytes(payload))
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "tamper request")
            request_path.write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair request")
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn("V10 request changed after activation", errors)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative, request = self._activate(root, parent)
            frozen_relative, _expected_sha256 = plan.FROZEN_ACTIVATION_FILES[0]
            frozen_path = root / frozen_relative
            frozen_bytes = frozen_path.read_bytes()
            frozen_path.write_bytes(frozen_bytes + b"\n# tampered\n")
            self._git(root, "add", frozen_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "tamper frozen")
            frozen_path.write_bytes(frozen_bytes)
            self._git(root, "add", frozen_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair frozen")
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V10 frozen activation files changed after activation",
                errors,
            )

    def test_preactivation_frozen_file_repairs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._initialize_activation_repository(root)
            frozen_relative, _expected_sha256 = plan.FROZEN_ACTIVATION_FILES[0]
            frozen_path = root / frozen_relative
            frozen_bytes = frozen_path.read_bytes()
            frozen_path.write_bytes(frozen_bytes + b"\n# preactivation tamper\n")
            self._git(root, "add", frozen_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "tamper before activation")
            frozen_path.write_bytes(frozen_bytes)
            self._git(root, "add", frozen_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair before activation")
            parent = self._git(root, "rev-parse", "HEAD")
            relative, request = self._activate(root, parent)
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V10 frozen activation file changed after its addition: "
                f"{frozen_relative}",
                errors,
            )

    def test_frozen_files_require_one_shared_addition_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "NoteAI Test")
            self._git(root, "config", "user.email", "noteai@example.invalid")
            (root / "README").write_text("base\n", encoding="utf-8")
            self._git(root, "add", "README")
            self._git(root, "commit", "-q", "-m", "seed")
            for relative, _expected_sha256 in plan.FROZEN_ACTIVATION_FILES[:-1]:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((plan.ROOT / relative).read_bytes())
            self._git(root, "add", ".")
            self._git(root, "commit", "-q", "-m", "first frozen anchor")
            last_relative, _expected_sha256 = plan.FROZEN_ACTIVATION_FILES[-1]
            last_target = root / last_relative
            last_target.parent.mkdir(parents=True, exist_ok=True)
            last_target.write_bytes((plan.ROOT / last_relative).read_bytes())
            self._git(root, "add", last_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "second frozen anchor")
            parent = self._git(root, "rev-parse", "HEAD")
            relative, request = self._activate(root, parent)
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V10 frozen activation files have different add anchors",
                errors,
            )

    def test_frozen_file_merge_anchor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "NoteAI Test")
            self._git(root, "config", "user.email", "noteai@example.invalid")
            (root / "README").write_text("seed\n", encoding="utf-8")
            self._git(root, "add", "README")
            self._git(root, "commit", "-q", "-m", "seed")
            seed = self._git(root, "rev-parse", "HEAD")
            self._git(root, "checkout", "-q", "-b", "left", seed)
            (root / "left").write_text("left\n", encoding="utf-8")
            self._git(root, "add", "left")
            self._git(root, "commit", "-q", "-m", "left")
            self._git(root, "checkout", "-q", "-b", "right", seed)
            (root / "right").write_text("right\n", encoding="utf-8")
            self._git(root, "add", "right")
            self._git(root, "commit", "-q", "-m", "right")
            self._git(root, "checkout", "-q", "left")
            self._git(root, "merge", "--no-ff", "--no-commit", "right")
            for relative, _expected_sha256 in plan.FROZEN_ACTIVATION_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((plan.ROOT / relative).read_bytes())
            self._git(root, "add", ".")
            self._git(root, "commit", "-q", "-m", "merge frozen anchor")
            parent = self._git(root, "rev-parse", "HEAD")
            relative, request = self._activate(root, parent)
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V10 frozen activation anchor is not single-parent",
                errors,
            )

    def test_legacy_receipt_history_rejects_tamper_and_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "NoteAI Test")
            self._git(root, "config", "user.email", "noteai@example.invalid")
            legacy_relative = Path("legacy-authority")
            legacy_path = root / legacy_relative
            legacy_path.write_text("frozen\n", encoding="utf-8")
            self._git(root, "add", legacy_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "trusted receipt")
            anchor = self._git(root, "rev-parse", "HEAD")
            (root / "unrelated").write_text("allowed\n", encoding="utf-8")
            self._git(root, "add", "unrelated")
            self._git(root, "commit", "-q", "-m", "unrelated")
            self.assertEqual(
                plan._validate_legacy_frozen_history(
                    root=root,
                    anchor=anchor,
                    frozen_paths=(legacy_relative,),
                ),
                [],
            )
            legacy_path.write_text("tampered\n", encoding="utf-8")
            self._git(root, "add", legacy_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "tamper legacy")
            legacy_path.write_text("frozen\n", encoding="utf-8")
            self._git(root, "add", legacy_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair legacy")
            self.assertIn(
                "V2-V9 frozen authority changed after terminal receipt",
                plan._validate_legacy_frozen_history(
                    root=root,
                    anchor=anchor,
                    frozen_paths=(legacy_relative,),
                ),
            )

    def test_legacy_paths_are_lexical_and_symlink_touch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "NoteAI Test")
            self._git(root, "config", "user.email", "noteai@example.invalid")
            legacy_relative = Path("legacy-authority")
            legacy_path = root / legacy_relative
            legacy_bytes = b"frozen authority\n"
            legacy_path.write_bytes(legacy_bytes)
            self._git(root, "add", legacy_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "trusted receipt")
            anchor = self._git(root, "rev-parse", "HEAD")
            payload = root / "same-bytes-copy"
            payload.write_bytes(legacy_bytes)
            legacy_path.unlink()
            legacy_path.symlink_to(payload)
            self._git(root, "add", legacy_relative.as_posix())
            self._git(root, "commit", "-q", "-m", "symlink legacy")
            with mock.patch.object(plan, "ROOT", root):
                self.assertEqual(
                    plan._repo_relative_path(legacy_path),
                    legacy_relative,
                )
            self.assertIn(
                "V2-V9 frozen authority changed after terminal receipt",
                plan._validate_legacy_frozen_history(
                    root=root,
                    anchor=anchor,
                    frozen_paths=(legacy_relative,),
                ),
            )

    def test_active_request_loader_is_lexical_and_never_reads_special_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broken = root / "broken-request"
            broken.symlink_to(root / "missing-target")
            present, payload, errors = plan._load_active_request(broken)
            self.assertTrue(present)
            self.assertIsNone(payload)
            self.assertEqual(
                errors,
                ["V10 active request worktree file is not regular"],
            )

            fifo = root / "request-fifo"
            os.mkfifo(fifo)
            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("special file must not be read"),
            ):
                present, payload, errors = plan._load_active_request(fifo)
            self.assertTrue(present)
            self.assertIsNone(payload)
            self.assertEqual(
                errors,
                ["V10 active request worktree file is not regular"],
            )

        with mock.patch.object(plan, "validate_plan", return_value=[]), mock.patch.object(
            plan,
            "_request_additions",
            return_value=[],
        ), mock.patch.object(
            plan,
            "_load_active_request",
            return_value=(
                True,
                None,
                ["V10 active request worktree file is not regular"],
            ),
        ):
            self.assertEqual(plan.plan_state(), "INVALID")

    def test_worktree_symlinks_are_rejected_for_frozen_and_request_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "NoteAI Test")
            self._git(root, "config", "user.email", "noteai@example.invalid")
            (root / "README").write_text("base\n", encoding="utf-8")
            self._git(root, "add", "README")
            self._git(root, "commit", "-q", "-m", "base")
            payload_path = root / "payload"
            payload = b"exact frozen bytes\n"
            payload_path.write_bytes(payload)
            frozen_relative = Path("frozen")
            (root / frozen_relative).symlink_to(payload_path)
            self.assertIn(
                f"V10 frozen worktree file is not regular: {frozen_relative}",
                plan._validate_v10_worktree_files(
                    root=root,
                    frozen_files=(
                        (
                            frozen_relative,
                            hashlib.sha256(payload).hexdigest(),
                        ),
                    ),
                ),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative, request = self._activate(root, parent)
            request_copy = root / "request-copy"
            request_copy.write_bytes(request)
            (root / relative).unlink()
            (root / relative).symlink_to(request_copy)
            self.assertIn(
                "V10 active request worktree file is not regular",
                plan._validate_active_request(
                    request,
                    plan.TEMPLATE_PATH.read_bytes(),
                    plan_parent=parent,
                    verify_git_state=True,
                    root=root,
                    request_path=relative,
                ),
            )

    def test_activation_bytes_mode_and_frozen_files_cannot_be_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            request = self._request(parent)
            tampered = json.loads(request)
            tampered["artifact_retention_days"] = 2
            relative, _ = self._activate(
                root,
                parent,
                request=self._json_bytes(tampered),
            )
            (root / relative).write_bytes(request)
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair bytes")
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn(
                "V10 request activation bytes differ from reviewed request",
                errors,
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            relative, request = self._activate(root, parent, mode="100755")
            self._git(root, "update-index", "--chmod=-x", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "repair mode")
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn("V10 request activation mode is not 100644", errors)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._initialize_activation_repository(root)
            frozen_relative, _ = plan.FROZEN_ACTIVATION_FILES[0]
            target = root / frozen_relative
            target.write_bytes(target.read_bytes() + b"\n# tampered\n")
            relative, request = self._activate(root, parent)
            self._git(root, "add", frozen_relative.as_posix())
            self._git(root, "commit", "--amend", "-q", "--no-edit")
            errors = plan._validate_active_request(
                request,
                plan.TEMPLATE_PATH.read_bytes(),
                plan_parent=parent,
                verify_git_state=True,
                root=root,
                request_path=relative,
            )
            self.assertIn("V10 activation changes more than its request", errors)
            self.assertTrue(
                any("V10 activation frozen file" in item for item in errors)
            )


if __name__ == "__main__":
    unittest.main()
