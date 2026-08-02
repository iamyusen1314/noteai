#!/usr/bin/env python3
"""Verify the Secret-free terminal supersession for the unique V15 run."""

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
    "admin-dependency-cache-v15-attempt1-failed-20260802.json"
)
EVIDENCE_FILE_SHA256 = (
    "277aa193041b7010a3ecc75de79b98b3"
    "0846e60bf72b0763612d30e359a4f378"
)
EXPECTED_SEMANTIC_SHA256 = (
    "5537639d669fbf18b3ff9b9620dd2d4"
    "acd9fc9d4c590ce0e1d3ce1081fc520c8"
)

V14_FAILURE_RECEIPT = "1ca885d61c48f3cfdb4e99eeedc6fb9f17238bb4"
V15_INERT_CHECKPOINT = "90f9606d6eb860572814cc3ccc0731fb9d366a5a"
V15_INERT_RECEIPT = "788a2b48d3dc04bea0f7c26fe7207887131436a7"
CONTROL_COMMIT = "c61ba14ab77f98dbc63697dc2b3cbe26afdf9df1"
DIRECT_PARENT_COMMIT = V15_INERT_RECEIPT
REQUEST_PATH = Path(
    ".github/release-requests/admin-5335bda-dependency-cache-v15.json"
)
REQUEST_SHA256 = (
    "0de3959f100e272e98b19238b670b99d"
    "d8fa096ad49179375014063420c37c4a"
)
REQUEST_BLOB = "c56a004085b88891a347c341473eb03e751baeea"
REQUEST_BYTES = 16424
TEMPLATE_PATH = Path(
    "deploy/production/plans/admin-dependency-cache-export-request-v15.json"
)

INERT_CHECKPOINT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        ".github/workflows/admin-dependency-cache-export-v15.yml",
        ".github/workflows/ci.yml",
        "deploy/production/internal-deployment-readiness.json",
        "deploy/production/plans/admin-dependency-cache-export-request-v15.json",
        "tests/test_admin_dependency_cache_export_plan_v15.py",
        "tests/test_internal_deployment_readiness_gate.py",
        "tests/test_production_readiness_gate.py",
        "tools/production_readiness_gate.py",
        "tools/verify_admin_dependency_cache_export_plan_v15.py",
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
        "deploy/production/evidence/admin-dependency-cache-v15-attempt1-failed-20260802.json",
        "deploy/production/internal-deployment-readiness.json",
        "tests/test_admin_dependency_cache_export_plan_v15.py",
        "tests/test_admin_dependency_cache_v15_failure_evidence.py",
        "tests/test_internal_deployment_readiness_gate.py",
        "tests/test_production_readiness_gate.py",
        "tools/production_readiness_gate.py",
        "tools/verify_admin_dependency_cache_export_plan_v15.py",
        "tools/verify_admin_dependency_cache_v15_failure_evidence.py",
    )
)
TERMINAL_ADDITION_FILES = (
    EVIDENCE_PATH.relative_to(ROOT),
    Path("tests/test_admin_dependency_cache_v15_failure_evidence.py"),
    Path("tools/verify_admin_dependency_cache_v15_failure_evidence.py"),
)
TERMINAL_IMMUTABLE_FILES = TERMINAL_ADDITION_FILES

FROZEN_UNCHANGED_FILES = {
    Path(".github/workflows/admin-dependency-cache-export-v15.yml"): (
        "33a57116c7462bb4f73f48f0d94f411"
        "58b8bf676886c19518610d172fc6ba457"
    ),
    Path(".github/workflows/ci.yml"): (
        "d4830c55563e18304c60c04cbe729e9d"
        "6c657c2fb5caa61d983eef50fe8a28e9"
    ),
    TEMPLATE_PATH: (
        "b89820b318f98363b768a43663bdf6c7"
        "30a4d78894c3d1c28547fdb86e42d777"
    ),
    Path("scripts/ci/export_admin_dependency_cache_v11.sh"): (
        "40618ad0db154061b1480dfd7b1e630f"
        "d6cc2f1529b54407509b412efb90b141"
    ),
    Path("scripts/ci/import_admin_dependency_cache_v13.sh"): (
        "ab824fa6ec1ed54b21c748736a81b80a"
        "418f179a82b701131a8a01c981d061b7"
    ),
    Path(
        "tests/fixtures/"
        "admin_dependency_cache_buildkit_v0.31.2_"
        "cache_record_identity_domains_projection.json"
    ): (
        "176fd702836a46ab30584aa3b0d0072c"
        "6c2a31ea8eda6c306d3d7cdfd87d6b66"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v13.py"): (
        "c9a0f130879f8381ea94584a600b3ee3"
        "88b91d380c079ec0b5efa145bff8b2d9"
    ),
    Path("tests/test_admin_dependency_cache_bundle_verifier_v13.py"): (
        "c2b7df625850556c60dc38409226edff"
        "41861765dfa4623439274e9a73e2313b"
    ),
}
ACTIVATION_SUPERSEDED_FILES = {
    Path("tools/verify_admin_dependency_cache_export_plan_v15.py"): (
        "6c22eb50b04c3e7ff4a6957554a70517"
        "9b3d5c5998a670969acafcd6c67e72e5"
    ),
    Path("tests/test_admin_dependency_cache_export_plan_v15.py"): (
        "8e739cd5edc97a33db34ce1fcf508667"
        "1101a629a5aa2fb80ae03c6aa1f7c024"
    ),
    Path("tools/production_readiness_gate.py"): (
        "f0bf27c670bfcae21f992a3a2d4e3d55"
        "303f05da251223e7c7855fe5f130345c"
    ),
    Path("tests/test_production_readiness_gate.py"): (
        "e3a2dde05059b51e5eb3fe113d9295ea"
        "21e8996ac4ccfd2df6200e8935e009fd"
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
        "cache_structure",
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
        raise ValueError("V15 failure evidence root must be an object")
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
        if _commit_parents(V15_INERT_CHECKPOINT) != [V14_FAILURE_RECEIPT]:
            errors.append("V15 inert checkpoint parent changed")
        if _changed_paths(V14_FAILURE_RECEIPT, V15_INERT_CHECKPOINT) != set(
            INERT_CHECKPOINT_FILES
        ):
            errors.append("V15 inert checkpoint path set changed")
        if _commit_parents(V15_INERT_RECEIPT) != [V15_INERT_CHECKPOINT]:
            errors.append("V15 inert receipt parent changed")
        if _changed_paths(V15_INERT_CHECKPOINT, V15_INERT_RECEIPT) != set(
            RECEIPT_FILES
        ):
            errors.append("V15 inert receipt path set changed")
        if _commit_parents(CONTROL_COMMIT) != [DIRECT_PARENT_COMMIT]:
            errors.append("V15 control parent changed")
        if _changed_paths(DIRECT_PARENT_COMMIT, CONTROL_COMMIT) != {REQUEST_PATH}:
            errors.append("V15 control is no longer request-only")
        if _true_additions(REQUEST_PATH) != [CONTROL_COMMIT]:
            errors.append("V15 request addition history changed")
        request = _git_bytes("show", f"{CONTROL_COMMIT}:{REQUEST_PATH.as_posix()}")
        if len(request) != REQUEST_BYTES or sha256_bytes(request) != REQUEST_SHA256:
            errors.append("V15 control request bytes changed")
        entry = _tree_entry(CONTROL_COMMIT, REQUEST_PATH).split()
        if entry[:3] != ["100644", "blob", REQUEST_BLOB]:
            errors.append("V15 control request blob or mode changed")
        if _git_bytes("show", f"{head}:{REQUEST_PATH.as_posix()}") != request:
            errors.append("V15 request is not retained byte-exact")
        if _lineage_path_changes(
            CONTROL_COMMIT,
            (REQUEST_PATH,),
            head=head,
        ):
            errors.append("V15 request changed after activation")

        checkpoint = terminal_checkpoint()
        if checkpoint is None:
            errors.append("V15 terminal addition anchor is not exact")
            return errors
        if _commit_parents(checkpoint) != [CONTROL_COMMIT]:
            errors.append("V15 terminal checkpoint is not the first post-activation write")
        if _changed_paths(CONTROL_COMMIT, checkpoint) != set(
            TERMINAL_CHECKPOINT_FILES
        ):
            errors.append("V15 terminal checkpoint is not the exact 11-file delta")
        for path in TERMINAL_CHECKPOINT_FILES:
            if not _regular_blob_mode(checkpoint, path):
                errors.append(f"V15 terminal checkpoint mode changed: {path}")
        if checkpoint not in _git_text(
            "rev-list", "--first-parent", head
        ).splitlines():
            errors.append("V15 terminal checkpoint left the first-parent chain")

        for path, expected in FROZEN_UNCHANGED_FILES.items():
            for commit in (CONTROL_COMMIT, checkpoint, head):
                if sha256_bytes(
                    _git_bytes("show", f"{commit}:{path.as_posix()}")
                ) != expected:
                    errors.append(f"V15 frozen authority changed: {path}")
                if not _regular_blob_mode(commit, path):
                    errors.append(f"V15 frozen authority mode changed: {path}")
            if _lineage_path_changes(CONTROL_COMMIT, (path,), head=head):
                errors.append(f"V15 frozen authority touched after activation: {path}")
        for path, expected in ACTIVATION_SUPERSEDED_FILES.items():
            if sha256_bytes(
                _git_bytes("show", f"{CONTROL_COMMIT}:{path.as_posix()}")
            ) != expected:
                errors.append(f"V15 activation superseded hash changed: {path}")
            if not _regular_blob_mode(CONTROL_COMMIT, path):
                errors.append(f"V15 activation superseded mode changed: {path}")
        if _lineage_path_changes(
            checkpoint,
            TERMINAL_IMMUTABLE_FILES,
            head=head,
        ):
            errors.append("V15 terminal nonreceipt authority changed")

        receipt = terminal_receipt(checkpoint)
        if head != checkpoint and receipt is None:
            errors.append("V15 terminal checkpoint first successor is not its receipt")
        if receipt is not None:
            for path in RECEIPT_FILES:
                if not _regular_blob_mode(receipt, path):
                    errors.append(f"V15 terminal receipt mode changed: {path}")
            if receipt not in _git_text(
                "rev-list", "--first-parent", head
            ).splitlines():
                errors.append("V15 terminal receipt left the first-parent chain")
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify frozen V15 terminal Git state: {exc}")
    return errors


def verify(
    payload: dict[str, Any],
    *,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []
    if set(payload) != EXPECTED_ROOT_KEYS:
        errors.append("V15 failure evidence root key set changed")
    if semantic_sha256(payload) != EXPECTED_SEMANTIC_SHA256:
        errors.append("V15 failure evidence semantic hash drift")
    if not (
        payload.get("schema_version")
        == "noteai.admin-dependency-cache-attempt-failure.v15"
        and payload.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and payload.get("classification")
        == (
            "V15_TRIGGERED_ATTEMPT1_FAILED_CLOSED_FRESH_CONSUMER_"
            "RUNTIME_PIP_DIGEST_DRIFT_ARTIFACT0_CLEANUP_PASS_"
            "PORTABILITY_FAILED"
        )
        and payload.get("repository") == "iamyusen1314/noteai"
        and payload.get("branch") == "codex/quality-stabilization-real-chain"
    ):
        errors.append("V15 failure evidence identity changed")

    run = payload.get("github_run", {})
    if not (
        run.get("workflow_id") == 325309521
        and run.get("run_id") == 30724578319
        and run.get("job_id") == 91433793914
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
        errors.append("V15 unique run contract changed")

    failure = payload.get("failure", {})
    if not (
        failure.get("primary_message")
        == "FAIL: V13 fresh consumer did not prove SAME_DIGEST_CACHED"
        and failure.get("primary_exit_code") == 3
        and failure.get("failure_code") == "V13_PAIR_CACHE_PREDICATE_FAILED"
        and failure.get("failed_role") == "runtime_pip"
        and failure.get("pair_classification") == "DIGEST_DRIFT"
        and failure.get("producer_runtime_pip_digest")
        == "sha256:f3c7f2ff52b744ba6773ea26aa2a853092202fdc86e7679e93f44646eedb0c9a"
        and failure.get("consumer_runtime_pip_digest")
        == "sha256:8ed38b7ab56a85d1783d009e5ffbedf0d4fe769254004b1ef220c98152357e8a"
        and failure.get("consumer_runtime_pip_cached") is False
        and failure.get("consumer_runtime_pip_interval_count") == 23
        and failure.get("consumer_runtime_pip_cached_interval_count") == 1
        and failure.get("consumer_runtime_pip_noncached_interval_count") == 22
        and failure.get("cacheless_replay_reached") is False
        and failure.get("portable_cache_verdict") == "FAIL"
        and failure.get("actual_local_session_values_retained") is False
    ):
        errors.append("V15 fresh-consumer failure boundary changed")

    cache = payload.get("cache_structure", {})
    if not (
        cache.get("cache_record_projection_sha256")
        == "a0ce4134cefdfb314f54817eff874e35082c1673d95dadef368cf66d8d53a54f"
        and cache.get("cache_config_sha256")
        == "eb3ea9fcc5872a0732915d99b5f58727c46038e570896a5fd288e39c2bd94e20"
        and cache.get("cache_config_bytes") == 4873
        and cache.get("record_count") == 17
        and cache.get("result_bearing_record_count") == 10
        and cache.get("link_count") == 17
        and cache.get("layer_count") == 19
        and cache.get("record_and_layer_dag_validated") is True
        and cache.get("record_and_layer_reachability_validated") is True
        and cache.get("runtime_portability_proven") is False
    ):
        errors.append("V15 cache structure boundary changed")

    cleanup = payload.get("cleanup", {})
    if not (
        cleanup.get("compact_log_payload_sha256")
        == "66150b14b5a1dc05b73125403610c1ab94ec7a4dba9cddd28735b9af612b5194"
        and cleanup.get("compact_log_payload_bytes") == 558
        and cleanup.get("cleanup_effective") is True
        and cleanup.get("overall_pass") is True
        and cleanup.get("github_hosted_ephemeral_builder_create_count") == 2
        and cleanup.get("github_hosted_ephemeral_builder_remove_count") == 2
    ):
        errors.append("V15 cleanup evidence changed")

    ledger = payload.get("run_ledger", {})
    if not (
        ledger.get("pre_resource_outcome") == "pass"
        and ledger.get("post_cleanup_pre_upload_outcome") == "pass"
        and ledger.get("repository_page_count") == 5
        and ledger.get("repository_advertised_run_count") == 487
        and ledger.get("repository_fetched_run_count") == 487
        and ledger.get("repository_unique_run_count") == 487
        and ledger.get("v11_workflow_path_run_count") == 0
        and ledger.get("v12_workflow_path_run_count") == 1
        and ledger.get("v13_workflow_path_run_count") == 0
        and ledger.get("v14_workflow_path_run_count") == 0
        and ledger.get("v15_workflow_path_run_count") == 1
        and ledger.get("v15_unique_run_id") == 30724578319
        and ledger.get("v15_unique_job_id") == 91433793914
        and ledger.get("v15_unique_run_conclusion") == "failure"
        and ledger.get("v15_artifact_count") == 0
        and ledger.get("a15_exact_head_run_count") == 3
        and ledger.get("rerun_or_duplicate_count") == 0
    ):
        errors.append("V15 terminal ledger changed")

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
        errors.append("V15 artifact-zero boundary changed")

    log = payload.get("native_job_log", {})
    if not (
        log.get("sha256")
        == "c9d41f2e7912176a8ddcda7b5431f51580473c4f980e72f60b992c23d5d3acf5"
        and log.get("byte_count") == 342244
        and log.get("line_count") == 3294
        and log.get("high_risk_unmasked_pattern_match_count") == 0
        and log.get("producer_v9_diagnostic_occurrence_count") == 2
        and log.get("producer_v11_export_anchor_occurrence_count") == 2
        and log.get("consumer_v11_progress_diagnostic_occurrence_count") == 1
        and log.get("consumer_v11_retained_diagnostic_occurrence_count") == 1
        and log.get("retained_pair_occurrence_count") == 1
        and log.get("cache_structure_diagnostic_occurrence_count") == 2
        and log.get("primary_failure_occurrence_count") == 1
        and log.get("cleanup_pass_occurrence_count") == 1
        and log.get("pre_resource_ledger_pass_occurrence_count") == 1
        and log.get("post_cleanup_ledger_pass_occurrence_count") == 1
    ):
        errors.append("V15 native job log projection changed")

    ci = payload.get("control_head_ci", {})
    if not (
        ci.get("exact_activation_head_run_count") == 3
        and ci.get("push_ci_run_id") == 30724578299
        and ci.get("push_ci_job_id") == 91433793813
        and ci.get("push_ci_attempt") == 1
        and ci.get("push_ci_conclusion") == "success"
        and ci.get("push_ci_total_test_count") == 1682
        and ci.get("push_ci_skipped_count") == 28
        and ci.get("push_ci_production_readiness_gate_passed") == 133
        and ci.get("pull_request_ci_run_id") == 30724579324
        and ci.get("pull_request_ci_job_id") == 91433796451
        and ci.get("pull_request_ci_attempt") == 1
        and ci.get("pull_request_ci_conclusion") == "success"
        and ci.get("pull_request_ci_total_test_count") == 1682
        and ci.get("pull_request_ci_skipped_count") == 28
        and ci.get("pull_request_ci_production_readiness_gate_passed") == 133
    ):
        errors.append("V15 control-head CI evidence changed")

    authorization = payload.get("authorization_outcome", {})
    readiness = payload.get("readiness", {})
    scope = payload.get("execution_scope", {})
    if not (
        authorization.get("github_v15_one_shot_run_consumed") is True
        and authorization.get("v15_attempt_may_not_be_rerun") is True
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
        errors.append("V15 authorization or readiness boundary changed")

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
        "V15_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT"
        if terminal_receipt(checkpoint) is not None
        else "V15_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT"
    )


def main() -> int:
    try:
        payload_bytes = EVIDENCE_PATH.read_bytes()
        if sha256_bytes(payload_bytes) != EVIDENCE_FILE_SHA256:
            print("FAIL: V15 failure evidence file hash drift")
            return 1
        payload = load_strict()
        errors = verify(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: cannot load V15 failure evidence: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "admin_dependency_cache_v15_failure_evidence=PASS "
        f"state={terminal_state()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
