#!/usr/bin/env python3
"""Verify the Secret-free terminal supersession for the unique V12 run."""

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
EVIDENCE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "evidence"
    / "admin-dependency-cache-v12-attempt1-failed-20260801.json"
)
EVIDENCE_FILE_SHA256 = (
    "87d262b0bf74e0ddeaf7a5d655a6bb16"
    "d9d974acd78daf92103bf5f284d76da7"
)
EXPECTED_SEMANTIC_SHA256 = (
    "a3de48e89967d8d7cafde734cd660363"
    "a57da758b09abfa7cfe5ca8eb84bcf79"
)

V11_INERT_CHECKPOINT = "606c474d347b4dad4e08e6f9fd038a82bdae5315"
V12_INERT_CHECKPOINT = "8b1f197141b9c84b4ffa812080ecabd6af1bbbce"
V12_INERT_RECEIPT = "328c07ed173754585c635ebb7b1d8c2587cadf57"
CONTROL_COMMIT = "2883d3e216fd64a70b94b1ba27b0838dca280f61"
DIRECT_PARENT_COMMIT = V12_INERT_RECEIPT
REQUEST_PATH = Path(
    ".github/release-requests/admin-5335bda-dependency-cache-v12.json"
)
REQUEST_SHA256 = (
    "1bfd1be7c6a03042397c57e2788180a9"
    "2c51e4843890d141671cc4b29eff432e"
)
REQUEST_BLOB = "5d3112b41ea654479d68b46099f67b5cbe8816b6"
TEMPLATE_PATH = Path(
    "deploy/production/plans/admin-dependency-cache-export-request-v12.json"
)

INERT_CHECKPOINT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        ".github/workflows/admin-dependency-cache-export-v12.yml",
        "deploy/production/internal-deployment-readiness.json",
        "deploy/production/plans/admin-dependency-cache-export-request-v12.json",
        "tests/test_admin_dependency_cache_export_plan_v11.py",
        "tests/test_admin_dependency_cache_export_plan_v12.py",
        "tests/test_internal_deployment_readiness_gate.py",
        "tests/test_production_readiness_gate.py",
        "tools/production_readiness_gate.py",
        "tools/verify_admin_dependency_cache_export_plan_v12.py",
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
        "deploy/production/evidence/admin-dependency-cache-v12-attempt1-failed-20260801.json",
        "deploy/production/internal-deployment-readiness.json",
        "tests/test_admin_dependency_cache_export_plan_v12.py",
        "tests/test_admin_dependency_cache_v12_failure_evidence.py",
        "tests/test_internal_deployment_readiness_gate.py",
        "tests/test_production_readiness_gate.py",
        "tools/production_readiness_gate.py",
        "tools/verify_admin_dependency_cache_export_plan_v12.py",
        "tools/verify_admin_dependency_cache_v12_failure_evidence.py",
    )
)
TERMINAL_ADDITION_FILES = (
    EVIDENCE_PATH.relative_to(ROOT),
    Path("tests/test_admin_dependency_cache_v12_failure_evidence.py"),
    Path("tools/verify_admin_dependency_cache_v12_failure_evidence.py"),
)
TERMINAL_IMMUTABLE_FILES = TERMINAL_ADDITION_FILES

FROZEN_UNCHANGED_FILES = {
    Path(".github/workflows/admin-dependency-cache-export-v12.yml"): (
        "5370b9dd93c52be420c492cfc92fd459"
        "5934b87b4becac7a602019ed55b5531d"
    ),
    TEMPLATE_PATH: (
        "c5a88fe6deadca0281a1a0fabebc3da0"
        "ad5bafb48357aa9d4319561ac1c3fe86"
    ),
    Path("tests/test_admin_dependency_cache_export_plan_v11.py"): (
        "83afbe6fa2d90775ab7f6a9dff66b4f4"
        "7fdd1cb82534d43331a117ec49e16c7a"
    ),
    Path("scripts/ci/export_admin_dependency_cache_v11.sh"): (
        "40618ad0db154061b1480dfd7b1e630f"
        "d6cc2f1529b54407509b412efb90b141"
    ),
    Path("scripts/ci/import_admin_dependency_cache_v11.sh"): (
        "e131246229e90ecb81dea1957d3ebe721"
        "73562a47803f67213b9eedddb1f31df"
    ),
    Path(
        "tests/fixtures/"
        "admin_dependency_cache_buildkit_v0.31.2_export_anchor_observer_projection.json"
    ): (
        "70e38ea8f77db46dd9a2325ac7fda224"
        "28c17dfe6d9318c7244107699ae9eb49"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v11.py"): (
        "27c3788bce8065440ccf370cf3a7192c2"
        "27546d30ed96c612f9acadebca97ca7"
    ),
}
ACTIVATION_SUPERSEDED_FILES = {
    Path("tests/test_admin_dependency_cache_export_plan_v12.py"): (
        "dcb83af7b29a9d9db8d0e47e0a1a998"
        "59b5a16ed9600d4f2b234a3c93a2d7fd0"
    ),
    Path("tests/test_production_readiness_gate.py"): (
        "2c47c9f39d2b7bf09c7fd1aab176c97"
        "eced862441346d501c6d7dc3d0754f000"
    ),
    Path("tools/production_readiness_gate.py"): (
        "6ac50eefcdc3f4f2d32b2703a52029b5"
        "33870df07ed6bb2a87c55956df33ec7d"
    ),
    Path("tools/verify_admin_dependency_cache_export_plan_v12.py"): (
        "bf9cc81dc4b756a15010515744bc798b"
        "a281285b39e3e467552d26af00655cdb"
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
        "buildkit_source_review",
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
CLEANUP_COMPACT_KEYS = (
    "schema_version",
    "deadline_control_valid",
    "client_token_disabled",
    "pre_state",
    "producer_builder_remove",
    "producer_builder_absent",
    "consumer_builder_remove",
    "consumer_builder_absent",
    "post_builder_state",
    "docker_baseline_state",
    "new_images_remove",
    "images_parity",
    "containers_parity",
    "volumes_parity",
    "networks_parity",
    "docker_root_absent",
    "buildx_root_absent",
    "diagnostic_files_absent",
    "cleanup_effective",
    "overall_pass",
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
        raise ValueError("V12 failure evidence root must be an object")
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


def diagnostic_payload_sha256(diagnostic: Any) -> str | None:
    if not isinstance(diagnostic, dict):
        return None
    projected = dict(diagnostic)
    expected = projected.pop("diagnostic_sha256", None)
    if not isinstance(expected, str):
        return None
    return sha256_bytes(
        json.dumps(
            projected,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def cleanup_compact_payload_sha256(cleanup: Any) -> str | None:
    if not isinstance(cleanup, dict):
        return None
    try:
        projected = {key: cleanup[key] for key in CLEANUP_COMPACT_KEYS}
        encoded = json.dumps(
            projected,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (KeyError, TypeError, ValueError):
        return None
    return sha256_bytes(encoded)


def _git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


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
        if _commit_parents(V12_INERT_CHECKPOINT) != [V11_INERT_CHECKPOINT]:
            errors.append("V12 inert checkpoint parent changed")
        if _changed_paths(V11_INERT_CHECKPOINT, V12_INERT_CHECKPOINT) != set(
            INERT_CHECKPOINT_FILES
        ):
            errors.append("V12 inert checkpoint path set changed")
        if _commit_parents(V12_INERT_RECEIPT) != [V12_INERT_CHECKPOINT]:
            errors.append("V12 inert receipt parent changed")
        if _changed_paths(V12_INERT_CHECKPOINT, V12_INERT_RECEIPT) != set(
            RECEIPT_FILES
        ):
            errors.append("V12 inert receipt path set changed")
        if _commit_parents(CONTROL_COMMIT) != [DIRECT_PARENT_COMMIT]:
            errors.append("V12 control parent changed")
        if _changed_paths(DIRECT_PARENT_COMMIT, CONTROL_COMMIT) != {REQUEST_PATH}:
            errors.append("V12 control is no longer request-only")
        if _true_additions(REQUEST_PATH) != [CONTROL_COMMIT]:
            errors.append("V12 request addition history changed")
        request = _git_bytes("show", f"{CONTROL_COMMIT}:{REQUEST_PATH.as_posix()}")
        if len(request) != 14221 or sha256_bytes(request) != REQUEST_SHA256:
            errors.append("V12 control request bytes changed")
        entry = _tree_entry(CONTROL_COMMIT, REQUEST_PATH).split()
        if entry[:3] != ["100644", "blob", REQUEST_BLOB]:
            errors.append("V12 control request blob or mode changed")
        if _git_bytes("show", f"{head}:{REQUEST_PATH.as_posix()}") != request:
            errors.append("V12 request is not retained byte-exact")
        if _lineage_path_changes(
            CONTROL_COMMIT,
            (REQUEST_PATH,),
            head=head,
        ):
            errors.append("V12 request changed after activation")

        checkpoint = terminal_checkpoint()
        if checkpoint is None:
            errors.append("V12 terminal addition anchor is not exact")
            return errors
        if _commit_parents(checkpoint) != [CONTROL_COMMIT]:
            errors.append("V12 terminal checkpoint is not the first post-activation write")
        if _changed_paths(CONTROL_COMMIT, checkpoint) != set(
            TERMINAL_CHECKPOINT_FILES
        ):
            errors.append("V12 terminal checkpoint is not the exact 11-file delta")
        for path in TERMINAL_CHECKPOINT_FILES:
            if not _regular_blob_mode(checkpoint, path):
                errors.append(f"V12 terminal checkpoint mode changed: {path}")
        first_parent = _git_text("rev-list", "--first-parent", head).splitlines()
        if checkpoint not in first_parent:
            errors.append("V12 terminal checkpoint left the first-parent chain")

        for path, expected in FROZEN_UNCHANGED_FILES.items():
            for commit in (CONTROL_COMMIT, checkpoint, head):
                if sha256_bytes(
                    _git_bytes("show", f"{commit}:{path.as_posix()}")
                ) != expected:
                    errors.append(f"V12 frozen authority changed: {path}")
                if not _regular_blob_mode(commit, path):
                    errors.append(f"V12 frozen authority mode changed: {path}")
            if _lineage_path_changes(CONTROL_COMMIT, (path,), head=head):
                errors.append(f"V12 frozen authority touched after activation: {path}")
        for path, expected in ACTIVATION_SUPERSEDED_FILES.items():
            if sha256_bytes(
                _git_bytes("show", f"{CONTROL_COMMIT}:{path.as_posix()}")
            ) != expected:
                errors.append(f"V12 activation superseded hash changed: {path}")
            if not _regular_blob_mode(CONTROL_COMMIT, path):
                errors.append(f"V12 activation superseded mode changed: {path}")
        if _lineage_path_changes(
            checkpoint,
            TERMINAL_IMMUTABLE_FILES,
            head=head,
        ):
            errors.append("V12 terminal nonreceipt authority changed")

        receipt = terminal_receipt(checkpoint)
        if head != checkpoint and receipt is None:
            errors.append("V12 terminal checkpoint first successor is not its receipt")
        if receipt is not None:
            for path in RECEIPT_FILES:
                if not _regular_blob_mode(receipt, path):
                    errors.append(f"V12 terminal receipt mode changed: {path}")
            if receipt not in _git_text(
                "rev-list",
                "--first-parent",
                head,
            ).splitlines():
                errors.append("V12 terminal receipt left the first-parent chain")
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify frozen V12 terminal Git state: {exc}")
    return errors


def verify(
    payload: dict[str, Any],
    *,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []
    if set(payload) != EXPECTED_ROOT_KEYS:
        errors.append("V12 failure evidence root key set changed")
    if semantic_sha256(payload) != EXPECTED_SEMANTIC_SHA256:
        errors.append("V12 failure evidence semantic hash drift")
    if (
        payload.get("schema_version")
        != "noteai.admin-dependency-cache-attempt-failure.v12"
        or payload.get("task") != "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        or payload.get("classification")
        != (
            "V12_TRIGGERED_ATTEMPT1_FAILED_CLOSED_UNSUPPORTED_CROSS_DOMAIN_"
            "DIGEST_BINDING_ARTIFACT0_CLEANUP_PASS_PORTABILITY_UNKNOWN"
        )
        or payload.get("repository") != "iamyusen1314/noteai"
        or payload.get("branch") != "codex/quality-stabilization-real-chain"
    ):
        errors.append("V12 failure evidence identity changed")

    run = payload.get("github_run", {})
    if not (
        run.get("workflow_id") == 325026609
        and run.get("run_id") == 30696298423
        and run.get("job_id") == 91359681758
        and run.get("run_number") == 1
        and run.get("attempt") == 1
        and run.get("event") == "push"
        and run.get("head_sha") == CONTROL_COMMIT
        and run.get("status") == "completed"
        and run.get("conclusion") == "failure"
        and run.get("workflow_run_count_global") == 1
        and run.get("attempt_two_absent") is True
        and run.get("rerun_count") == 0
        and run.get("rerun_authorized") is False
    ):
        errors.append("V12 unique run contract changed")

    failure = payload.get("failure", {})
    v9 = failure.get("producer_v9_diagnostic")
    v11 = failure.get("producer_v11_diagnostic")
    if not (
        failure.get("primary_message")
        == "FAIL: BuildKit anchor cache record binding changed"
        and failure.get("failure_code")
        == "CACHE_RECORD_DIGEST_BINDING_INVALID"
        and failure.get("verifier_root_cause")
        == "CACHE_CONFIG_CACHE_KEY_DIGEST_WAS_COMPARED_TO_PROGRESS_VERTEX_DIGEST"
        and failure.get("anchor_cache_record_match_cardinality") is None
        and failure.get("anchor_cache_record_match_cardinality_status")
        == "UNKNOWN_NOT_RETAINED"
        and failure.get("runtime_pip_cache_record_validation_reached") is False
        and failure.get("cache_config_retained") is False
        and failure.get("fresh_consumer_import_reached") is False
        and failure.get("underlying_cache_portability_status")
        == "UNKNOWN_NOT_REACHED"
        and failure.get("portable_cache_verdict") == "UNKNOWN_NOT_REACHED"
    ):
        errors.append("V12 failure boundary changed")
    if (
        diagnostic_payload_sha256(v9)
        != "8b165376c7e30970095af1a462fd20a9370048d192912edc47e6f7f7ae65f521"
        or not isinstance(v9, dict)
        or v9.get("verdict") != "pass"
        or v9.get("failure_code") != "NONE"
    ):
        errors.append("V12 producer V9 diagnostic changed")
    if (
        diagnostic_payload_sha256(v11)
        != "5fd793934543c58248998b49d2e6d709431bfafe3cf340d4a72006b9b5967ffd"
        or not isinstance(v11, dict)
        or v11.get("verdict") != "pass"
        or v11.get("failure_code") != "NONE"
        or v11.get("cache_record_projection") is not None
        or v11.get("observer") is not None
    ):
        errors.append("V12 producer V11 diagnostic changed")

    source = payload.get("buildkit_source_review", {})
    if not (
        source.get("commit") == "e42e1bfd389af7203238cce77b1f7dad447285e9"
        and source.get("conclusion")
        == (
            "CACHE_CONFIG_RECORD_DIGEST_AND_PROGRESS_VERTEX_DIGEST_ARE_"
            "DIFFERENT_IDENTITY_DOMAINS"
        )
        and source.get("cache_key_digest_and_vertex_digest_are_distinct_fields")
        is True
        and source.get("root_key_rehashes_cache_map_digest_and_output") is True
        and source.get("cache_config_record_has_vertex_digest_field") is False
        and source.get("source_review_is_runtime_cache_portability_evidence")
        is False
        and isinstance(source.get("sources"), list)
        and len(source["sources"]) == 6
    ):
        errors.append("V12 BuildKit source review changed")

    cleanup = payload.get("cleanup", {})
    if not (
        cleanup_compact_payload_sha256(cleanup)
        == "66150b14b5a1dc05b73125403610c1ab94ec7a4dba9cddd28735b9af612b5194"
        and cleanup.get("compact_log_payload_bytes") == 558
        and cleanup.get("overall_pass") is True
        and cleanup.get("cleanup_effective") is True
        and cleanup.get("github_hosted_ephemeral_builder_create_count") == 2
        and cleanup.get("github_hosted_ephemeral_builder_remove_count") == 2
    ):
        errors.append("V12 cleanup evidence changed")

    ledger = payload.get("run_ledger", {})
    if not (
        ledger.get("contract_sha256")
        == "d3be446996f5fc38f01b175b640f8cb4f63c09c57ea103f6e6ef13f7c49db790"
        and ledger.get("pre_resource_outcome") == "pass"
        and ledger.get("post_cleanup_pre_upload_outcome") == "pass"
        and ledger.get("repository_run_count") == 470
        and ledger.get("repository_unique_run_count") == 470
        and ledger.get("v2_run_count") == 2
        and ledger.get("v3_v10_run_count_each") == 1
        and ledger.get("v11_workflow_path_run_count") == 0
        and ledger.get("v12_workflow_path_run_count") == 1
        and ledger.get("v12_unique_run_conclusion") == "failure"
        and ledger.get("v12_artifact_count") == 0
    ):
        errors.append("V12 terminal ledger changed")

    artifact = payload.get("provider_artifact", {})
    if not (
        artifact.get("api_total_count") == 0
        and artifact.get("upload_step_outcome") == "skipped"
        and artifact.get("provider_identity_step_outcome") == "skipped"
        and artifact.get("artifact_id") is None
        and artifact.get("authenticated_download_count") == 0
        and artifact.get("cross_provider_transfer_count") == 0
    ):
        errors.append("V12 artifact-zero boundary changed")

    log = payload.get("native_job_log", {})
    if not (
        log.get("sha256")
        == "a73eb2dc9608645c99cf4a4b14a1c7a2d7033a1e8199c46c12b187ed851b0cb6"
        and log.get("byte_count") == 285419
        and log.get("line_count") == 2931
        and log.get("high_risk_unmasked_pattern_match_count") == 0
        and log.get("primary_failure_occurrence_count") == 1
        and log.get("pre_resource_ledger_pass_occurrence_count") == 1
        and log.get("post_cleanup_ledger_pass_occurrence_count") == 1
    ):
        errors.append("V12 native job log projection changed")

    ci = payload.get("control_head_ci", {})
    if not (
        ci.get("exact_activation_head_run_count") == 3
        and ci.get("push_ci_run_id") == 30696298410
        and ci.get("push_ci_job_id") == 91359681561
        and ci.get("push_ci_conclusion") == "success"
        and ci.get("push_ci_test_count") == 1612
        and ci.get("push_ci_skipped_count") == 28
        and ci.get("push_ci_production_readiness_gate_passed") == 131
        and ci.get("pull_request_ci_run_id") == 30696299851
        and ci.get("pull_request_ci_job_id") == 91359684931
        and ci.get("pull_request_ci_conclusion") == "success"
        and ci.get("pull_request_ci_test_count") == 1612
        and ci.get("pull_request_ci_skipped_count") == 28
        and ci.get("pull_request_ci_production_readiness_gate_passed") == 131
    ):
        errors.append("V12 control-head CI evidence changed")

    authorization = payload.get("authorization_outcome", {})
    readiness = payload.get("readiness", {})
    scope = payload.get("execution_scope", {})
    if not (
        authorization.get("github_v12_one_shot_run_consumed") is True
        and authorization.get("v12_attempt_may_not_be_rerun") is True
        and authorization.get("authenticated_download_authorization_consumed")
        is False
        and authorization.get("conditional_cloud_builder_authorization_activated")
        is False
        and authorization.get("successor_external_run_requires_new_authorization")
        is True
        and readiness.get("internal_verified_count") == 19
        and readiness.get("internal_total_count") == 29
        and readiness.get("credit_added") is False
        and scope.get("production_service_mutation_count") == 0
        and scope.get("production_database_write_count") == 0
        and scope.get("public_traffic_mutation_count") == 0
    ):
        errors.append("V12 authorization or readiness boundary changed")

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
        "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT"
        if terminal_receipt(checkpoint) is not None
        else "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT"
    )


def main() -> int:
    try:
        payload_bytes = EVIDENCE_PATH.read_bytes()
        if sha256_bytes(payload_bytes) != EVIDENCE_FILE_SHA256:
            print("FAIL: V12 failure evidence file hash drift")
            return 1
        payload = load_strict()
        errors = verify(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: cannot load V12 failure evidence: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"admin_dependency_cache_v12_failure_evidence=PASS state={terminal_state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
