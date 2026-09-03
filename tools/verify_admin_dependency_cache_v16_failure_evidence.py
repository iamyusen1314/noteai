#!/usr/bin/env python3
"""Verify the Secret-free terminal supersession for the unique V16 run."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "deploy" / "production" / "evidence" / (
    "admin-dependency-cache-v16-attempt1-failed-20260802.json"
)
EVIDENCE_FILE_SHA256 = (
    "3b5881161d560b2a20da313a828faa04b"
    "7d0da374136eab3cc7f171a6f1f5d97"
)
EXPECTED_SEMANTIC_SHA256 = (
    "a04cb8246e07bf800ce284e3c1e5f60f"
    "1a8e672c74bd409f9144dcd56fd20558"
)

V15_TERMINAL_RECEIPT = "a94ee2b2feb81eafbcb523be2c95da4ee952cbc4"
V16_INERT_CHECKPOINT = "b6f642e68c21341c90bb3c66f810945ada4e084a"
V16_INERT_RECEIPT = "095529e03f735494a98ce2302a6e1be570291d8c"
CONTROL_COMMIT = "fd1444d0a62549b3c353cbc1188e6ba25a77e96e"
DIRECT_PARENT_COMMIT = V16_INERT_RECEIPT
REQUEST_PATH = Path(
    ".github/release-requests/admin-5335bda-dependency-cache-v16.json"
)
REQUEST_SHA256 = (
    "65f606dbb8033cf0c63c104a702c359d"
    "82e46fd75c6259dbb8dfc6abcf06ff28"
)
REQUEST_BLOB = "3353fa696363a5b7f023c2f4aab44f04464d491f"
REQUEST_BYTES = 18342
TEMPLATE_PATH = Path(
    "deploy/production/plans/admin-dependency-cache-export-request-v16.json"
)

INERT_CHECKPOINT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        ".github/workflows/admin-dependency-cache-export-v16.yml",
        ".github/workflows/ci.yml",
        "deploy/production/internal-deployment-readiness.json",
        "deploy/production/plans/admin-dependency-cache-export-request-v16.json",
        "scripts/ci/export_admin_dependency_cache_v16.sh",
        "scripts/ci/import_admin_dependency_cache_v16.sh",
        "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_git_main_context_identity_projection.json",
        "tests/test_admin_dependency_cache_bundle_verifier_v16.py",
        "tests/test_admin_dependency_cache_export_plan_v16.py",
        "tests/test_internal_deployment_readiness_gate.py",
        "tests/test_production_readiness_gate.py",
        "tools/production_readiness_gate.py",
        "tools/verify_admin_dependency_cache_bundle_v16.py",
        "tools/verify_admin_dependency_cache_export_plan_v16.py",
    )
)
RECEIPT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        "deploy/production/internal-deployment-readiness.json",
        "tests/test_internal_deployment_readiness_gate.py",
    )
)
TERMINAL_CHECKPOINT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        "deploy/production/evidence/admin-dependency-cache-v16-attempt1-failed-20260802.json",
        "deploy/production/internal-deployment-readiness.json",
        "tests/test_admin_dependency_cache_export_plan_v16.py",
        "tests/test_admin_dependency_cache_v16_failure_evidence.py",
        "tests/test_internal_deployment_readiness_gate.py",
        "tests/test_production_readiness_gate.py",
        "tools/production_readiness_gate.py",
        "tools/verify_admin_dependency_cache_export_plan_v16.py",
        "tools/verify_admin_dependency_cache_v16_failure_evidence.py",
    )
)
TERMINAL_ADDITION_FILES = (
    EVIDENCE_PATH.relative_to(ROOT),
    Path("tests/test_admin_dependency_cache_v16_failure_evidence.py"),
    Path("tools/verify_admin_dependency_cache_v16_failure_evidence.py"),
)
TERMINAL_IMMUTABLE_FILES = TERMINAL_ADDITION_FILES

FROZEN_UNCHANGED_FILES = {
    Path(".github/workflows/admin-dependency-cache-export-v16.yml"): (
        "8a86d032b03c3f9df624cb68c53509cb"
        "4729cb3687f3736d8697876a0474e170"
    ),
    Path(".github/workflows/ci.yml"): (
        "2244fd150eed055c6da1a9ce52a043cf4"
        "8bd95e6a3784920f180662b5746875e"
    ),
    TEMPLATE_PATH: (
        "e49c8d94d347cd4afabcd2d116036b2a"
        "9dda1e008bb9f0759d01abf259e517d6"
    ),
    Path("scripts/ci/export_admin_dependency_cache_v16.sh"): (
        "84100721415675268a3617398b1b58d87"
        "51cede9adfa3acd2351811538090ed0"
    ),
    Path("scripts/ci/import_admin_dependency_cache_v16.sh"): (
        "41150005187726281752ed5b39e03ceb"
        "a7618d77319c9a92d134a3a106546ba6"
    ),
    Path(
        "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_"
        "git_main_context_identity_projection.json"
    ): (
        "2010890934f05c8ada09328c433962d5"
        "ae648346351accdeec62e1aafdb1f701"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v16.py"): (
        "0a7198daccea5463e33b5d19fbe64ea3"
        "d8eed3d96f6fb3f63060ed0928acd74c"
    ),
    Path("tests/test_admin_dependency_cache_bundle_verifier_v16.py"): (
        "7930b1060299bf50d8e50588e4d19b6a"
        "d0c8fa5157383a0db125f418895b9dca"
    ),
}
ACTIVATION_SUPERSEDED_FILES = {
    Path("tools/verify_admin_dependency_cache_export_plan_v16.py"): (
        "da84f3d02617b6f18ea9d3ea0e690994"
        "20ae90fce83049337ebd152ba0b64fff"
    ),
    Path("tests/test_admin_dependency_cache_export_plan_v16.py"): (
        "b14943cc6058f0814faa8b714f963da0"
        "49ad44cfb889434431e0746651818607"
    ),
    Path("tools/production_readiness_gate.py"): (
        "9cc39316770768d04b100f6f1b64bbd8"
        "ea21718caf76fba235b784b810766c7e"
    ),
    Path("tests/test_production_readiness_gate.py"): (
        "f5436caeb0c491aa214abd5daaa7c3af"
        "0e758d064bb136eb0246f91b8b3558fa"
    ),
}

EXPECTED_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "task",
        "classification",
        "repository",
        "branch",
        "git",
        "github_run",
        "runner",
        "step_outcome",
        "failure",
        "cleanup",
        "run_ledger",
        "provider_artifact",
        "native_job_log",
        "control_head_ci",
        "execution_scope",
        "authorization_outcome",
        "readiness",
    }
)


def reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str):
    raise ValueError(f"non-finite JSON number: {value}")


def parse_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def load_strict(path: Path = EVIDENCE_PATH) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_pairs,
        parse_constant=reject_constant,
        parse_float=parse_float,
    )
    if not isinstance(payload, dict):
        raise ValueError("V16 failure evidence root must be an object")
    return payload


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def semantic_sha256(payload: dict[str, Any]) -> str:
    return sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _git_text(*args: str) -> str:
    return _git_bytes(*args).decode("utf-8").strip()


def _commit_parents(commit: str) -> list[str]:
    fields = _git_text("rev-list", "--parents", "-n", "1", commit).split()
    if not fields or fields[0] != commit:
        raise ValueError(f"cannot resolve commit parents: {commit}")
    return fields[1:]


def _tree_entry(commit: str, path: Path) -> str:
    return _git_text("ls-tree", commit, "--", path.as_posix())


def _regular_blob_mode(commit: str, path: Path) -> bool:
    return _tree_entry(commit, path).split()[:2] == ["100644", "blob"]


def _canonical_head() -> str:
    head = _git_text("rev-parse", "HEAD")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return head
    if os.environ.get("GITHUB_SHA") != head:
        raise ValueError("GitHub checkout SHA does not match HEAD")
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return head
    if re.fullmatch(
        r"refs/pull/[1-9][0-9]*/merge",
        os.environ.get("GITHUB_REF", ""),
    ) is None:
        raise ValueError("GitHub pull-request merge ref changed")
    parents = _commit_parents(head)
    if len(parents) != 2:
        raise ValueError("GitHub pull-request checkout is not a two-parent merge")
    return parents[1]


def _true_additions(path: Path) -> list[str]:
    output = _git_text(
        "log",
        "--all",
        "--full-history",
        "-m",
        "--no-renames",
        "--diff-filter=A",
        "--format=%H",
        "--",
        path.as_posix(),
    )
    additions: list[str] = []
    for candidate in output.splitlines():
        if not candidate or candidate in additions:
            continue
        parents = _commit_parents(candidate)
        if _tree_entry(candidate, path) and all(
            not _tree_entry(parent, path) for parent in parents
        ):
            additions.append(candidate)
    return additions


def _changed_paths(parent: str, commit: str) -> set[Path]:
    return {
        Path(value)
        for value in _git_text(
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            parent,
            commit,
        ).splitlines()
        if value
    }


def _lineage_path_changes(
    anchor: str,
    paths: tuple[Path, ...],
    *,
    head: str,
) -> list[str]:
    records = [
        line.split()
        for line in _git_text(
            "rev-list",
            "--ancestry-path",
            "--parents",
            f"{anchor}..{head}",
        ).splitlines()
        if line
    ]
    lineage = {anchor, *(record[0] for record in records)}
    names = tuple(path.as_posix() for path in paths)
    changes: list[str] = []
    for record in records:
        commit, parents = record[0], record[1:]
        for parent in (value for value in parents if value in lineage):
            if _git_text(
                "diff-tree",
                "--no-commit-id",
                "--no-renames",
                "--name-only",
                "-r",
                parent,
                commit,
                "--",
                *names,
            ):
                changes.append(commit)
                break
    return changes


def terminal_checkpoint() -> str | None:
    additions = [_true_additions(path) for path in TERMINAL_ADDITION_FILES]
    if any(len(items) != 1 for items in additions):
        return None
    values = {items[0] for items in additions}
    return next(iter(values)) if len(values) == 1 else None


def terminal_receipt(checkpoint: str) -> str | None:
    head = _canonical_head()
    successors = _git_text(
        "rev-list",
        "--first-parent",
        "--reverse",
        f"{checkpoint}..{head}",
    ).splitlines()
    if not successors:
        return None
    candidate = successors[0]
    if (
        _commit_parents(candidate) != [checkpoint]
        or _changed_paths(checkpoint, candidate) != set(RECEIPT_FILES)
    ):
        return None
    return candidate


def verify_frozen_git() -> list[str]:
    errors: list[str] = []
    try:
        head = _canonical_head()
        if _commit_parents(V16_INERT_CHECKPOINT) != [V15_TERMINAL_RECEIPT]:
            errors.append("V16 inert checkpoint parent changed")
        if _changed_paths(V15_TERMINAL_RECEIPT, V16_INERT_CHECKPOINT) != set(
            INERT_CHECKPOINT_FILES
        ):
            errors.append("V16 inert checkpoint path set changed")
        if _commit_parents(V16_INERT_RECEIPT) != [V16_INERT_CHECKPOINT]:
            errors.append("V16 inert receipt parent changed")
        if _changed_paths(V16_INERT_CHECKPOINT, V16_INERT_RECEIPT) != set(
            RECEIPT_FILES
        ):
            errors.append("V16 inert receipt path set changed")
        if _commit_parents(CONTROL_COMMIT) != [DIRECT_PARENT_COMMIT]:
            errors.append("V16 control parent changed")
        if _changed_paths(DIRECT_PARENT_COMMIT, CONTROL_COMMIT) != {REQUEST_PATH}:
            errors.append("V16 control is no longer request-only")
        if _true_additions(REQUEST_PATH) != [CONTROL_COMMIT]:
            errors.append("V16 request addition history changed")
        request = _git_bytes("show", f"{CONTROL_COMMIT}:{REQUEST_PATH.as_posix()}")
        if len(request) != REQUEST_BYTES or sha256_bytes(request) != REQUEST_SHA256:
            errors.append("V16 control request bytes changed")
        entry = _tree_entry(CONTROL_COMMIT, REQUEST_PATH).split()
        if entry[:3] != ["100644", "blob", REQUEST_BLOB]:
            errors.append("V16 control request blob or mode changed")
        if _git_bytes("show", f"{head}:{REQUEST_PATH.as_posix()}") != request:
            errors.append("V16 request is not retained byte-exact")
        if _lineage_path_changes(
            CONTROL_COMMIT,
            (REQUEST_PATH,),
            head=head,
        ):
            errors.append("V16 request changed after activation")

        checkpoint = terminal_checkpoint()
        if checkpoint is None:
            errors.append("V16 terminal addition anchor is not exact")
            return errors
        if _commit_parents(checkpoint) != [CONTROL_COMMIT]:
            errors.append("V16 terminal checkpoint is not the first post-activation write")
        if _changed_paths(CONTROL_COMMIT, checkpoint) != set(
            TERMINAL_CHECKPOINT_FILES
        ):
            errors.append("V16 terminal checkpoint is not the exact 11-file delta")
        for path in TERMINAL_CHECKPOINT_FILES:
            if not _regular_blob_mode(checkpoint, path):
                errors.append(f"V16 terminal checkpoint mode changed: {path}")
        if checkpoint not in _git_text(
            "rev-list", "--first-parent", head
        ).splitlines():
            errors.append("V16 terminal checkpoint left the first-parent chain")

        for path, expected in FROZEN_UNCHANGED_FILES.items():
            for commit in (CONTROL_COMMIT, checkpoint, head):
                if sha256_bytes(
                    _git_bytes("show", f"{commit}:{path.as_posix()}")
                ) != expected:
                    errors.append(f"V16 frozen authority changed: {path}")
                if not _regular_blob_mode(commit, path):
                    errors.append(f"V16 frozen authority mode changed: {path}")
            if _lineage_path_changes(CONTROL_COMMIT, (path,), head=head):
                errors.append(f"V16 frozen authority touched after activation: {path}")
        for path, expected in ACTIVATION_SUPERSEDED_FILES.items():
            if sha256_bytes(
                _git_bytes("show", f"{CONTROL_COMMIT}:{path.as_posix()}")
            ) != expected:
                errors.append(f"V16 activation superseded hash changed: {path}")
            if not _regular_blob_mode(CONTROL_COMMIT, path):
                errors.append(f"V16 activation superseded mode changed: {path}")
        if set(
            _lineage_path_changes(
                CONTROL_COMMIT,
                tuple(ACTIVATION_SUPERSEDED_FILES),
                head=head,
            )
        ) != {checkpoint}:
            errors.append("V16 versioned terminal authority history changed")
        if _lineage_path_changes(
            checkpoint,
            TERMINAL_IMMUTABLE_FILES,
            head=head,
        ):
            errors.append("V16 terminal nonreceipt authority changed")

        receipt = terminal_receipt(checkpoint)
        if head != checkpoint and receipt is None:
            errors.append("V16 terminal checkpoint first successor is not its receipt")
        if receipt is not None:
            for path in RECEIPT_FILES:
                if not _regular_blob_mode(receipt, path):
                    errors.append(f"V16 terminal receipt mode changed: {path}")
            if receipt not in _git_text(
                "rev-list", "--first-parent", head
            ).splitlines():
                errors.append("V16 terminal receipt left the first-parent chain")
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify frozen V16 terminal Git state: {exc}")
    return errors


def verify(
    payload: dict[str, Any],
    *,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []
    if set(payload) != EXPECTED_ROOT_KEYS:
        errors.append("V16 failure evidence root key set changed")
    if semantic_sha256(payload) != EXPECTED_SEMANTIC_SHA256:
        errors.append("V16 failure evidence semantic hash drift")
    if not (
        payload.get("schema_version")
        == "noteai.admin-dependency-cache-attempt-failure.v16"
        and payload.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and payload.get("classification")
        == (
            "V16_TRIGGERED_ATTEMPT1_FAILED_CLOSED_PRODUCER_GIT_SOURCE_"
            "LIFECYCLE_ASSERTION_ARTIFACT0_CLEANUP_EFFECTIVE_OVERALL_"
            "FAIL_CLOSED_PORTABILITY_UNKNOWN"
        )
        and payload.get("repository") == "iamyusen1314/noteai"
        and payload.get("branch") == "codex/quality-stabilization-real-chain"
    ):
        errors.append("V16 failure evidence identity changed")

    run = payload.get("github_run", {})
    if not (
        run.get("workflow_id") == 325446435
        and run.get("run_id") == 30739167701
        and run.get("job_id") == 91473336858
        and run.get("run_number") == 1
        and run.get("attempt") == 1
        and run.get("event") == "push"
        and run.get("status") == "completed"
        and run.get("conclusion") == "failure"
        and run.get("head_sha") == CONTROL_COMMIT
        and run.get("workflow_run_count_global") == 1
        and run.get("attempt_two_absent") is True
        and run.get("rerun_count") == 0
        and run.get("rerun_authorized") is False
    ):
        errors.append("V16 unique run contract changed")

    steps = payload.get("step_outcome", {})
    if not (
        steps.get("dependency_cache_export_and_producer_verification")
        == "failure"
        and steps.get("fresh_consumer_portability") == "skipped"
        and steps.get("transient_docker_cleanup") == "failure"
        and steps.get("post_cleanup_ledger_snapshot") == "skipped"
        and steps.get("artifact_upload") == "skipped"
        and steps.get("runner_local_bundle_cleanup") == "success"
    ):
        errors.append("V16 step outcome boundary changed")

    failure = payload.get("failure", {})
    if not (
        failure.get("primary_message")
        == "FAIL: BuildKit git_main_context lifecycle changed"
        and failure.get("workflow_step_exit_code") == 1
        and failure.get("source_correlated_failure_code")
        == "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD"
        and failure.get("failed_role") == "git_main_context"
        and failure.get("buildx_build_and_local_cache_export_command_completed")
        is True
        and failure.get("producer_identity_validation_completed") is False
        and failure.get("metadata_retained") is False
        and failure.get("rawjson_retained") is False
        and failure.get("actual_lifecycle_timestamp_values_observed") is False
        and failure.get("specific_failed_lifecycle_relation_observed") is False
        and failure.get("secondary_message")
        == "FAIL: transient_state_contract_changed"
        and failure.get("secondary_phase") == "cleanup-active"
        and failure.get("secondary_runtime_payload_retained") is False
        and failure.get("consumer_import_reached") is False
        and failure.get(
            "external_cache_removed_same_consumer_builder_replay_reached"
        )
        is False
        and failure.get("portable_cache_verdict") == "UNKNOWN_NOT_REACHED"
    ):
        errors.append("V16 producer failure boundary changed")

    cleanup = payload.get("cleanup", {})
    if not (
        cleanup.get("compact_log_payload_sha256")
        == "a59dbbfef7b29eb8335db275d51f50fc84231144551496d3d9cecd42b09abc73"
        and cleanup.get("compact_log_payload_bytes") == 560
        and cleanup.get("pre_state") == "drift"
        and cleanup.get("producer_builder_remove") == "removed"
        and cleanup.get("producer_builder_absent") == "pass"
        and cleanup.get("consumer_builder_remove") == "removed"
        and cleanup.get("consumer_builder_absent") == "pass"
        and cleanup.get("post_builder_state") == "pass"
        and cleanup.get("docker_baseline_state") == "pass"
        and cleanup.get("images_parity") == "pass"
        and cleanup.get("containers_parity") == "pass"
        and cleanup.get("volumes_parity") == "pass"
        and cleanup.get("networks_parity") == "pass"
        and cleanup.get("docker_root_absent") == "pass"
        and cleanup.get("buildx_root_absent") == "pass"
        and cleanup.get("diagnostic_files_absent") == "pass"
        and cleanup.get("cleanup_effective") is True
        and cleanup.get("overall_pass") is False
        and cleanup.get("github_hosted_ephemeral_builder_create_count") == 2
        and cleanup.get("github_hosted_ephemeral_builder_remove_count") == 2
    ):
        errors.append("V16 cleanup evidence changed")

    ledger = payload.get("run_ledger", {})
    if not (
        ledger.get("pre_resource_outcome") == "pass"
        and ledger.get("post_cleanup_pre_upload_outcome") == "skipped"
        and ledger.get("repository_page_count") == 5
        and ledger.get("repository_advertised_run_count") == 498
        and ledger.get("repository_fetched_run_count") == 498
        and ledger.get("repository_unique_run_count") == 498
        and ledger.get("v11_workflow_path_run_count") == 0
        and ledger.get("v12_workflow_path_run_count") == 1
        and ledger.get("v13_workflow_path_run_count") == 0
        and ledger.get("v14_workflow_path_run_count") == 0
        and ledger.get("v15_workflow_path_run_count") == 1
        and ledger.get("v16_workflow_path_run_count") == 1
        and ledger.get("v16_unique_run_id") == 30739167701
        and ledger.get("v16_unique_job_id") == 91473336858
        and ledger.get("v16_unique_run_conclusion") == "failure"
        and ledger.get("v16_artifact_count") == 0
        and ledger.get("a16_exact_head_run_count") == 3
        and ledger.get("rerun_or_duplicate_count") == 0
    ):
        errors.append("V16 terminal ledger changed")

    artifact = payload.get("provider_artifact", {})
    if not (
        artifact.get("api_total_count") == 0
        and artifact.get("api_fetched_count") == 0
        and artifact.get("api_unique_count") == 0
        and artifact.get("upload_step_outcome") == "skipped"
        and artifact.get("provider_identity_step_outcome") == "skipped"
        and artifact.get("artifact_id") is None
        and artifact.get("authenticated_download_count") == 0
        and artifact.get("cross_provider_transfer_count") == 0
    ):
        errors.append("V16 artifact-zero boundary changed")

    log = payload.get("native_job_log", {})
    if not (
        log.get("sha256")
        == "9747f32b44d2c534b81525b72b42ee51426176aa225b170bb4ae92e605d8e33b"
        and log.get("byte_count") == 288946
        and log.get("line_count") == 3011
        and log.get("high_risk_unmasked_pattern_match_count") == 0
        and log.get("masked_value_occurrence_count") == 7
        and log.get("masked_actions_read_token_occurrence_count") == 2
        and log.get("primary_failure_occurrence_count") == 1
        and log.get("secondary_failure_occurrence_count") == 1
        and log.get("producer_identity_diagnostic_occurrence_count") == 0
        and log.get("compatibility_diagnostic_occurrence_count") == 0
        and log.get("cleanup_fail_closed_occurrence_count") == 1
        and log.get("cleanup_receipt_occurrence_count") == 1
        and log.get("pre_resource_ledger_pass_occurrence_count") == 1
        and log.get("post_cleanup_ledger_pass_occurrence_count") == 0
    ):
        errors.append("V16 native job log projection changed")

    ci = payload.get("control_head_ci", {})
    if not (
        ci.get("exact_activation_head_run_count") == 3
        and ci.get("push_ci_run_id") == 30739167685
        and ci.get("push_ci_job_id") == 91473336783
        and ci.get("push_ci_attempt") == 1
        and ci.get("push_ci_conclusion") == "success"
        and ci.get("push_ci_total_test_count") == 1714
        and ci.get("push_ci_skipped_count") == 28
        and ci.get("push_ci_production_readiness_gate_passed") == 135
        and ci.get("pull_request_ci_run_id") == 30739168799
        and ci.get("pull_request_ci_job_id") == 91473339876
        and ci.get("pull_request_ci_attempt") == 1
        and ci.get("pull_request_ci_conclusion") == "success"
        and ci.get("pull_request_ci_total_test_count") == 1714
        and ci.get("pull_request_ci_skipped_count") == 28
        and ci.get("pull_request_ci_production_readiness_gate_passed") == 135
        and ci.get("quality_gate_passed") is True
        and ci.get("docker_compose_passed") is True
    ):
        errors.append("V16 control-head CI evidence changed")

    authorization = payload.get("authorization_outcome", {})
    readiness = payload.get("readiness", {})
    scope = payload.get("execution_scope", {})
    if not (
        authorization.get("github_v16_one_shot_run_consumed") is True
        and authorization.get("v16_attempt_may_not_be_rerun") is True
        and authorization.get("authenticated_download_authorization_consumed")
        is False
        and authorization.get("conditional_cloud_builder_authorization_activated")
        is False
        and authorization.get("successor_external_run_requires_new_authorization")
        is True
        and readiness.get("internal_verified_count") == 19
        and readiness.get("internal_total_count") == 29
        and readiness.get("public_verified_count") == 19
        and readiness.get("public_total_count") == 38
        and readiness.get("credit_added") is False
        and scope.get("builder_create_count") == 2
        and scope.get("builder_remove_count") == 2
        and scope.get("provider_artifact_count") == 0
        and scope.get("production_service_mutation_count") == 0
        and scope.get("production_database_write_count") == 0
        and scope.get("public_traffic_mutation_count") == 0
    ):
        errors.append("V16 authorization, scope or readiness boundary changed")

    if verify_git_state:
        errors.extend(verify_frozen_git())
    return errors


def terminal_state() -> str:
    try:
        payload = load_strict()
        errors = verify(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "INVALID"
    if errors:
        return "INVALID"
    checkpoint = terminal_checkpoint()
    if checkpoint is None:
        return "INVALID"
    return (
        "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT"
        if terminal_receipt(checkpoint) is not None
        else "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT"
    )


def main() -> int:
    try:
        payload_bytes = EVIDENCE_PATH.read_bytes()
        if sha256_bytes(payload_bytes) != EVIDENCE_FILE_SHA256:
            print("FAIL: V16 failure evidence file hash drift")
            return 1
        payload = load_strict()
        errors = verify(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: cannot load V16 failure evidence: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "admin_dependency_cache_v16_failure_evidence=PASS "
        f"state={terminal_state()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
