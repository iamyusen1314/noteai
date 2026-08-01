#!/usr/bin/env python3
"""Verify the inert, append-only V11 Admin dependency-cache recovery plan."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import verify_admin_dependency_cache_export_plan_v10 as v10_plan
import verify_admin_dependency_cache_v10_failure_evidence as v10_failure


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v11.yml"
)
TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v11.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v11.json"
)
EXPORT_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "export_admin_dependency_cache_v11.sh"
)
IMPORT_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "import_admin_dependency_cache_v11.sh"
)
SOURCE_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "export_anchor_observer_projection.json"
)
BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v11.py"
)
PLAN_VERIFIER_PATH = Path(__file__).resolve()

WORKFLOW_SHA256 = (
    "61d72e35823730851e45900219935e12"
    "324ff42862fd9920285ade5ececbaca6"
)
TEMPLATE_SHA256 = (
    "ca97b59c409e478a5f375a9446a58041"
    "5004f90451d2219a3a8abf432b43c0ac"
)
EXPORT_HELPER_SHA256 = (
    "40618ad0db154061b1480dfd7b1e630f"
    "d6cc2f1529b54407509b412efb90b141"
)
IMPORT_HELPER_SHA256 = (
    "e131246229e90ecb81dea1957d3ebe721"
    "73562a47803f67213b9eedddb1f31df"
)
SOURCE_FIXTURE_SHA256 = (
    "70e38ea8f77db46dd9a2325ac7fda224"
    "28c17dfe6d9318c7244107699ae9eb49"
)
BUNDLE_VERIFIER_SHA256 = (
    "27c3788bce8065440ccf370cf3a7192c"
    "227546d30ed96c612f9acadebca97ca7"
)
V10_PLAN_VERIFIER_SHA256 = (
    "bcd29ac744be75e05cd1ea90dec4c92c"
    "2175171e5d372ca739d04833ea4346cf"
)
V10_FAILURE_VERIFIER_SHA256 = (
    "9afae89edb9af2dce53ee5583b8ce8e"
    "671037568773849e26f7e164578cc548f"
)
V10_FAILURE_EVIDENCE_SHA256 = (
    "9b8a1e3a28c5ca2e1a6d4c495e2404"
    "f7ea027abf42bfa27ccd4649909f043103"
)
V10_FAILURE_EVIDENCE_SEMANTIC_SHA256 = (
    "352debb0294df5c442bf1b0ea0594576"
    "e49f649c830c2e1f568d4f0a4e9e4336"
)
V10_CONTROL_COMMIT = "ea2a3b489e74b21a88ea21ecd243cd6a433c7fac"
V10_PLAN_PARENT = "b02c4a18d6b77024f17d0e56c1d081a578854b1f"
V10_TERMINAL_CHECKPOINT = "b01c65d507cf087bea0d80038eafdb08a8e23bf1"
V10_TERMINAL_RECEIPT = "458f2482f9a3267bb9050a274f33ae21fc546ed7"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_WORKFLOW_HEADER = """name: Admin dependency cache export V11

on:
  push:
    branches:
      - codex/quality-stabilization-real-chain
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v11.json
"""
FROZEN_ACTIVATION_FILES = (
    (WORKFLOW_PATH.relative_to(ROOT), WORKFLOW_SHA256),
    (TEMPLATE_PATH.relative_to(ROOT), TEMPLATE_SHA256),
    (EXPORT_HELPER_PATH.relative_to(ROOT), EXPORT_HELPER_SHA256),
    (IMPORT_HELPER_PATH.relative_to(ROOT), IMPORT_HELPER_SHA256),
    (SOURCE_FIXTURE_PATH.relative_to(ROOT), SOURCE_FIXTURE_SHA256),
    (BUNDLE_VERIFIER_PATH.relative_to(ROOT), BUNDLE_VERIFIER_SHA256),
)
SAME_ANCHOR_FILES = tuple(
    path for path, _sha256 in FROZEN_ACTIVATION_FILES
) + (PLAN_VERIFIER_PATH.relative_to(ROOT),)
INERT_CHECKPOINT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        ".github/workflows/admin-dependency-cache-export-v11.yml",
        "deploy/production/internal-deployment-readiness.json",
        "deploy/production/plans/admin-dependency-cache-export-request-v11.json",
        "scripts/ci/export_admin_dependency_cache_v11.sh",
        "scripts/ci/import_admin_dependency_cache_v11.sh",
        "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_export_anchor_observer_projection.json",
        "tests/test_admin_dependency_cache_bundle_verifier_v11.py",
        "tests/test_admin_dependency_cache_export_plan_v11.py",
        "tests/test_internal_deployment_readiness_gate.py",
        "tests/test_production_readiness_gate.py",
        "tools/production_readiness_gate.py",
        "tools/verify_admin_dependency_cache_bundle_v11.py",
        "tools/verify_admin_dependency_cache_export_plan_v11.py",
    )
)
INERT_RECEIPT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        "deploy/production/internal-deployment-readiness.json",
        "tests/test_internal_deployment_readiness_gate.py",
    )
)
V11_NEW_CHECKPOINT_FILES = tuple(
    Path(value)
    for value in (
        ".github/workflows/admin-dependency-cache-export-v11.yml",
        "deploy/production/plans/admin-dependency-cache-export-request-v11.json",
        "scripts/ci/export_admin_dependency_cache_v11.sh",
        "scripts/ci/import_admin_dependency_cache_v11.sh",
        "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_export_anchor_observer_projection.json",
        "tests/test_admin_dependency_cache_bundle_verifier_v11.py",
        "tests/test_admin_dependency_cache_export_plan_v11.py",
        "tools/verify_admin_dependency_cache_bundle_v11.py",
        "tools/verify_admin_dependency_cache_export_plan_v11.py",
    )
)
CHECKPOINT_IMMUTABLE_FILES = tuple(
    path
    for path in INERT_CHECKPOINT_FILES
    if path not in set(INERT_RECEIPT_FILES)
)
LEGACY_FROZEN_PATHS = tuple(
    sorted(
        {
            *v10_plan._legacy_frozen_paths(),
            *(path for path, _sha256 in v10_plan.FROZEN_ACTIVATION_FILES),
            v10_plan.ACTIVE_REQUEST_PATH.relative_to(ROOT),
            Path("tools/verify_admin_dependency_cache_export_plan_v10.py"),
            v10_failure.EVIDENCE_PATH.relative_to(ROOT),
            Path("tools/verify_admin_dependency_cache_v10_failure_evidence.py"),
        },
        key=lambda path: path.as_posix(),
    )
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_at(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _git(*args: str) -> str:
    return _git_at(ROOT, *args)


def _commit_parents(root: Path, commit: str) -> list[str]:
    record = _git_at(
        root,
        "rev-list",
        "--parents",
        "-n",
        "1",
        commit,
    ).split()
    if not record or record[0] != commit:
        raise ValueError(f"cannot resolve commit parents: {commit}")
    return record[1:]


def _tree_entry(root: Path, commit: str, relative: Path) -> str:
    return _git_at(root, "ls-tree", commit, "--", relative.as_posix())


def _true_additions(
    *,
    root: Path = ROOT,
    path: Path,
) -> list[str]:
    output = _git_at(
        root,
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
    for commit in output.splitlines():
        if not commit or commit in additions:
            continue
        parents = _commit_parents(root, commit)
        current = _tree_entry(root, commit, path)
        if current and all(
            not _tree_entry(root, parent, path) for parent in parents
        ):
            additions.append(commit)
    return additions


def _lineage_path_changes(
    *,
    root: Path,
    anchor: str,
    paths: tuple[Path, ...],
    head: str = "HEAD",
) -> list[str]:
    output = _git_at(
        root,
        "rev-list",
        "--ancestry-path",
        "--parents",
        f"{anchor}..{head}",
    )
    records = [line.split() for line in output.splitlines() if line]
    lineage = {anchor, *(record[0] for record in records)}
    names = tuple(path.as_posix() for path in paths)
    changes: list[str] = []
    for record in records:
        commit, parents = record[0], record[1:]
        for parent in (item for item in parents if item in lineage):
            changed = _git_at(
                root,
                "diff-tree",
                "--no-commit-id",
                "--no-renames",
                "--name-only",
                "-r",
                parent,
                commit,
                "--",
                *names,
            )
            if changed:
                changes.append(commit)
                break
    return changes


def _changed_paths(root: Path, parent: str, commit: str) -> set[Path]:
    output = _git_at(
        root,
        "diff-tree",
        "--no-commit-id",
        "--no-renames",
        "--name-only",
        "-r",
        parent,
        commit,
    )
    return {Path(value) for value in output.splitlines() if value}


def _canonical_branch_head(root: Path) -> str:
    head = _git_at(root, "rev-parse", "HEAD")
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
    parents = _commit_parents(root, head)
    if len(parents) != 2:
        raise ValueError("GitHub pull-request checkout is not a two-parent merge")
    return parents[1]


def _on_first_parent_chain(
    root: Path,
    commit: str,
    *,
    head: str,
) -> bool:
    return commit in _git_at(root, "rev-list", "--first-parent", head).splitlines()


def _authority_anchor(
    *,
    root: Path = ROOT,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    head = _git_at(root, "rev-parse", "HEAD")
    entries = {
        path: _tree_entry(root, head, path) for path in SAME_ANCHOR_FILES
    }
    present = [path for path, entry in entries.items() if entry]
    if not present:
        return None, []
    if len(present) != len(SAME_ANCHOR_FILES):
        return None, ["V11 frozen authorities are only partially present"]
    anchors: list[str] = []
    for path in SAME_ANCHOR_FILES:
        additions = _true_additions(root=root, path=path)
        if len(additions) != 1:
            errors.append(f"V11 frozen addition history is not unique: {path}")
        else:
            anchors.append(additions[0])
    if errors:
        return None, errors
    if len(set(anchors)) != 1:
        return None, ["V11 frozen authorities have different add anchors"]
    return anchors[0], []


def _strict_json_bytes(payload: bytes, label: str) -> Any:
    try:
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON token: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    canonical = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    if payload != canonical:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _regular_file(path: Path, *, maximum_bytes: int = 4_194_304) -> bytes:
    flags = Path(path)
    if flags.is_symlink():
        raise ValueError(f"file is symlink: {path}")
    state = flags.stat()
    if (
        not stat.S_ISREG(state.st_mode)
        or state.st_nlink != 1
        or not 0 < state.st_size <= maximum_bytes
    ):
        raise ValueError(f"file contract changed: {path}")
    return flags.read_bytes()


def _template_errors(template: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(template.get("schema_version") == 11, "V11 schema changed")
    require(
        template.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "V11 task changed",
    )
    require(
        template.get("release_commit") == RELEASE_COMMIT,
        "V11 release changed",
    )
    require(
        template.get("plan_checkpoint_commit")
        == "__DIRECT_PARENT_COMMIT__",
        "V11 direct-parent placeholder changed",
    )
    require(
        template.get("trigger_mode") == "one_shot_added_request_v11",
        "V11 trigger mode changed",
    )
    predecessor = template.get("predecessor")
    require(
        predecessor
        == {
            "control_commit": V10_CONTROL_COMMIT,
            "direct_parent_commit": V10_PLAN_PARENT,
            "terminal_checkpoint_commit": V10_TERMINAL_CHECKPOINT,
            "terminal_receipt_commit": V10_TERMINAL_RECEIPT,
            "workflow_id": 324820330,
            "run_id": 30672160324,
            "job_id": 91291967175,
            "run_attempt": 1,
            "conclusion": "failure",
            "artifact_count": 0,
            "rerun_count": 0,
            "rerun_authorized": False,
            "request_sha256": (
                "4b3c8950bea4a0e9cdc578a69f193fb6"
                "3cccb5be447bba777951718249d96db0"
            ),
            "failure_evidence_sha256": V10_FAILURE_EVIDENCE_SHA256,
            "failure_evidence_semantic_sha256": (
                V10_FAILURE_EVIDENCE_SEMANTIC_SHA256
            ),
            "failure_verifier_sha256": V10_FAILURE_VERIFIER_SHA256,
        },
        "V11 predecessor terminal semantics changed",
    )
    recovery = template.get("recovery_basis")
    require(isinstance(recovery, dict), "V11 recovery basis missing")
    if isinstance(recovery, dict):
        require(
            recovery.get("base_dependency_prefix_sha256")
            == (
                "93fd024e5af678b7885bcab8e72d980a"
                "9f92cfc70de4f2fd2870284e25b8ec1e"
            )
            and recovery.get("combined_suffix_sha256")
            == (
                "7b7a5a5877567f568f6a5ff6b00481e"
                "4cf92bcc24939231098a5f2623e5104c0"
            )
            and recovery.get("combined_dockerfile_sha256")
            == (
                "c665ac4356bec6751d44878a416bbaa27"
                "8a77df77754f5461ba0adb13f43c2a0"
            )
            and recovery.get("combined_dockerfile_line_count") == 86,
            "V11 combined Dockerfile contract changed",
        )
        require(
            recovery.get("producer_target")
            == "noteai-cache-export-anchor"
            and recovery.get("consumer_target")
            == "noteai-cache-import-observer"
            and recovery.get("producer_run_start_line") == 83
            and recovery.get("consumer_run_start_line") == 86
            and recovery.get("child_network_mode") == "NONE"
            and recovery.get("child_network_enum") == 2,
            "V11 target contract changed",
        )
        require(
            recovery.get("v11_export_helper_sha256")
            == EXPORT_HELPER_SHA256
            and recovery.get("v11_import_helper_sha256")
            == IMPORT_HELPER_SHA256
            and recovery.get(
                "export_anchor_observer_source_projection_sha256"
            )
            == SOURCE_FIXTURE_SHA256,
            "V11 recovery authority hash changed",
        )
        require(
            recovery.get("no_cache_filter_authorized") is False
            and recovery.get("dependency_cache_predicate_relaxed") is False
            and recovery.get(
                "github_actions_provenance_injection_authorized"
            )
            is False,
            "V11 cache or provenance policy changed",
        )
    chain = template.get("bundle_verifier_chain")
    require(
        isinstance(chain, dict)
        and chain.get("v10_sha256") == v10_plan.BUNDLE_VERIFIER_SHA256
        and chain.get("v11_sha256") == BUNDLE_VERIFIER_SHA256,
        "V11 verifier chain changed",
    )
    require(
        template.get("control_plane")
        == {
            "reused_concurrency_group": "admin-dependency-cache-export-v10",
            "inert_checkpoint_exact_changed_path_count": 15,
            "inert_receipt_exact_changed_path_count": 4,
            "activation_exact_changed_path_count": 1,
            "prepared_branch_head_exact_v10_terminal_receipt_required": True,
            "canonical_branch_latest_exact_stage_required": True,
            "github_pr_merge_second_parent_projection_only": True,
            "checkpoint_nonreceipt_immutable_path_count": 11,
            "active_request_worktree_mode": "100644",
            "git_diff_errors_must_propagate": True,
            "run_ledger_snapshot_count": 2,
            "run_ledger_fresh_api_reads_required": True,
            "run_ledger_budget_seconds_per_snapshot": 60,
            "run_ledger_page_maximum": 10,
            "v2_v10_unique_attempt1_failure_artifact0_required": True,
            "v11_current_attempt1_artifact0_required": True,
            "late_snapshot_after_cleanup_required": True,
            "late_snapshot_runs_on_prior_failure_after_cleanup": True,
            "python_optimized_mode_must_not_disable_checks": True,
        },
        "V11 control-plane contract changed",
    )
    evidence = template.get("build_evidence_recovery")
    require(
        isinstance(evidence, dict)
        and evidence.get(
            "frozen_v2_v9_delegate_required_for_combined_prefix"
        )
        is True
        and evidence.get("producer_export_anchor_required") is True
        and evidence.get("consumer_import_observer_required") is True
        and evidence.get(
            "cache_config_anchor_single_identity_link_to_runtime_pip_required"
        )
        is True
        and evidence.get("runtime_pip_pair_classification_required")
        == "SAME_DIGEST_CACHED"
        and evidence.get(
            "pre_predicate_and_terminal_diagnostics_persisted_required"
        )
        is True
        and evidence.get("runtime_pip_cached_false_accepted") is False
        and evidence.get(
            "latest_interval_only_cache_acceptance_allowed"
        )
        is False
        and evidence.get("historical_v10_root_cause_status")
        == "UNKNOWN_NOT_RETAINED",
        "V11 evidence contract changed",
    )
    require(
        template.get("github_actions_maximum_run_count") == 1
        and template.get("github_actions_maximum_runtime_minutes") == 120
        and template.get("artifact_retention_days") == 1
        and template.get("registry_publication_authorized") is False
        and template.get("deployment_authorized") is False
        and template.get("database_authorized") is False
        and template.get("service_mutation_authorized") is False
        and template.get("public_traffic_authorized") is False,
        "V11 bounded authorization changed",
    )
    return errors


def _workflow_errors(workflow: str) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(
        workflow.split("\npermissions:", 1)[0] == EXPECTED_WORKFLOW_HEADER,
        "V11 trigger block changed",
    )
    require("workflow_dispatch:" not in workflow, "V11 manual trigger enabled")
    require("pull_request:" not in workflow, "V11 pull-request trigger enabled")
    required = (
        "group: admin-dependency-cache-export-v10",
        "Prove this is the unique V11 workflow run for the branch lifecycle",
        'legacy_change_file="${RUNNER_TEMP}/noteai-cache-v11-legacy-change"',
        'test ! -s "${legacy_change_file}"',
        'v11_change_file="${RUNNER_TEMP}/noteai-cache-v11-authority-change"',
        'test ! -s "${v11_change_file}"',
        "Snapshot V2 through V11 ledgers before resource creation",
        "Snapshot V2 through V11 ledgers after cleanup and before upload",
        "if: ${{ always() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
        'budget_seconds = int(os.environ["NOTEAI_RUN_LEDGER_BUDGET_SECONDS"])',
        'deadline = time.monotonic() + budget_seconds',
        "V11 ledger deadline exceeded",
        "/actions/workflows/admin-dependency-cache-export-v11.yml/runs",
        "324820330",
        "30672160324",
        "noteai-cache-export-anchor",
        "noteai-cache-import-observer",
        "scripts/ci/export_admin_dependency_cache_v11.sh",
        "scripts/ci/import_admin_dependency_cache_v11.sh",
        "tools/verify_admin_dependency_cache_bundle_v10.py",
        "tools/verify_admin_dependency_cache_bundle_v11.py",
        "tools/verify_admin_dependency_cache_export_plan_v11.py",
        "Remove V11 builders and all transient Docker state",
        "Upload one-day V11 public-repository dependency cache artifact",
        "Remove runner-local V11 bundle",
    )
    for token in required:
        require(token in workflow, f"V11 workflow contract missing: {token}")
    forbidden = (
        "no-cache-filter",
        "workflow_dispatch",
        "docker login",
        "docker push",
        "az login",
        "az acr",
        "assert ",
        'test -z "$(\n                  git diff-tree',
    )
    for token in forbidden:
        require(token not in workflow, f"V11 workflow forbidden token: {token}")
    require(
        workflow.count('deadline = time.monotonic() + budget_seconds') == 2
        and workflow.count("V11 ledger deadline exceeded") >= 2,
        "V11 ledger deadline contract changed",
    )
    require(
        workflow.find("Remove V11 builders and all transient Docker state")
        < workflow.find(
            "Snapshot V2 through V11 ledgers after cleanup and before upload"
        )
        < workflow.find(
            "Upload one-day V11 public-repository dependency cache artifact"
        ),
        "V11 cleanup, late-ledger and upload ordering changed",
    )
    require(
        workflow.count("actions/upload-artifact@") == 1
        and "retention-days: 1" in workflow
        and "compression-level: 0" in workflow,
        "V11 artifact protocol changed",
    )
    return errors


def _validate_frozen_worktree() -> list[str]:
    errors: list[str] = []
    for relative, expected in FROZEN_ACTIVATION_FILES:
        path = ROOT / relative
        try:
            payload = _regular_file(path)
            if hashlib.sha256(payload).hexdigest() != expected:
                errors.append(f"V11 frozen worktree hash drift: {relative}")
            if stat.S_IMODE(path.stat().st_mode) != 0o644:
                errors.append(f"V11 frozen worktree mode changed: {relative}")
        except (OSError, ValueError) as exc:
            errors.append(f"cannot verify V11 frozen worktree file {relative}: {exc}")
    try:
        _regular_file(PLAN_VERIFIER_PATH)
        if stat.S_IMODE(PLAN_VERIFIER_PATH.stat().st_mode) != 0o644:
            errors.append("V11 plan verifier worktree mode changed")
    except (OSError, ValueError) as exc:
        errors.append(f"cannot verify V11 plan verifier: {exc}")
    return errors


def _validate_legacy_history(*, root: Path = ROOT) -> list[str]:
    try:
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                V10_TERMINAL_RECEIPT,
                "HEAD",
            ],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        changes = _lineage_path_changes(
            root=root,
            anchor=V10_TERMINAL_RECEIPT,
            paths=LEGACY_FROZEN_PATHS,
        )
        return (
            ["V2-V10 frozen authority changed after V10 terminal receipt"]
            if changes
            else []
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [f"cannot verify V2-V10 frozen history: {exc}"]


def _validate_same_anchor(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        branch_head = _canonical_branch_head(root)
        anchor, anchor_errors = _authority_anchor(root=root)
        if anchor_errors:
            return anchor_errors
        if anchor is None:
            if branch_head != V10_TERMINAL_RECEIPT:
                errors.append(
                    "V11 prepared branch HEAD is not the V10 terminal receipt"
                )
            for relative in (
                *V11_NEW_CHECKPOINT_FILES,
                ACTIVE_REQUEST_PATH.relative_to(ROOT),
            ):
                if _true_additions(root=root, path=relative):
                    errors.append(
                        "V11 prepared state has prior addition history: "
                        f"{relative}"
                    )
            return errors
        if _commit_parents(root, anchor) != [V10_TERMINAL_RECEIPT]:
            errors.append("V11 frozen anchor parent changed")
        elif _changed_paths(root, V10_TERMINAL_RECEIPT, anchor) != set(
            INERT_CHECKPOINT_FILES
        ):
            errors.append("V11 inert checkpoint is not the exact 15-file delta")
        if not _on_first_parent_chain(root, anchor, head=branch_head):
            errors.append("V11 frozen anchor is not on the branch first-parent chain")
        for relative in INERT_CHECKPOINT_FILES:
            entry = _tree_entry(root, anchor, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V11 inert checkpoint mode changed: {relative}")
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", anchor, "HEAD"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if _lineage_path_changes(
            root=root,
            anchor=anchor,
            paths=CHECKPOINT_IMMUTABLE_FILES,
        ):
            errors.append("V11 immutable checkpoint path changed after add anchor")
        expected_hashes = dict(FROZEN_ACTIVATION_FILES)
        for relative in SAME_ANCHOR_FILES:
            entry = _tree_entry(root, "HEAD", relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V11 frozen HEAD mode changed: {relative}")
                continue
            expected = expected_hashes.get(relative)
            if expected is None:
                continue
            payload = subprocess.run(
                ["git", "show", f"HEAD:{relative.as_posix()}"],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            if hashlib.sha256(payload).hexdigest() != expected:
                errors.append(f"V11 frozen HEAD hash drift: {relative}")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        errors.append(f"cannot verify V11 frozen anchor: {exc}")
    return errors


def _validate_inert_receipt(
    *,
    root: Path = ROOT,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    try:
        branch_head = _canonical_branch_head(root)
        anchor, anchor_errors = _authority_anchor(root=root)
        if anchor_errors:
            return None, anchor_errors
        if anchor is None:
            return None, []
        changes = _lineage_path_changes(
            root=root,
            anchor=anchor,
            paths=INERT_RECEIPT_FILES,
        )
        if not changes:
            return None, []
        if len(changes) != 1:
            return None, ["V11 inert receipt history is not unique"]
        receipt = changes[0]
        if _commit_parents(root, receipt) != [anchor]:
            errors.append("V11 inert receipt is not the direct child of anchor")
        elif _changed_paths(root, anchor, receipt) != set(
            INERT_RECEIPT_FILES
        ):
            errors.append("V11 inert receipt is not the exact 4-file delta")
        for relative in INERT_RECEIPT_FILES:
            entry = _tree_entry(root, receipt, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V11 inert receipt mode changed: {relative}")
        if not _on_first_parent_chain(root, receipt, head=branch_head):
            errors.append("V11 inert receipt is not on the branch first-parent chain")
        return receipt, errors
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return None, [f"cannot verify V11 inert receipt: {exc}"]


def _active_request(
    *,
    path: Path = ACTIVE_REQUEST_PATH,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    try:
        if not path.exists() and not path.is_symlink():
            return False, None, []
        payload = _regular_file(path)
        if stat.S_IMODE(path.stat().st_mode) != 0o644:
            return True, None, ["V11 active request worktree mode changed"]
        value = _strict_json_bytes(payload, "V11 active request")
        if not isinstance(value, dict):
            return True, None, ["V11 active request root changed"]
        return True, value, []
    except (OSError, ValueError) as exc:
        return True, None, [f"cannot load V11 active request: {exc}"]


def _validate_active_git(
    active: dict[str, Any],
    *,
    root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    relative = ACTIVE_REQUEST_PATH.relative_to(ROOT)
    try:
        branch_head = _canonical_branch_head(root)
        additions = _true_additions(root=root, path=relative)
        if len(additions) != 1:
            return ["V11 active request addition history is not unique"]
        activation = additions[0]
        if not _on_first_parent_chain(root, activation, head=branch_head):
            errors.append(
                "V11 activation is not on the branch first-parent chain"
            )
        parents = _commit_parents(root, activation)
        if len(parents) != 1:
            return ["V11 activation is not single-parent"]
        parent = parents[0]
        receipt, receipt_errors = _validate_inert_receipt(root=root)
        errors.extend(receipt_errors)
        if receipt is None or parent != receipt:
            errors.append("V11 activation parent is not the exact inert receipt")
        if active.get("plan_checkpoint_commit") != parent:
            errors.append("V11 active request does not bind its direct parent")
        changed = _git_at(
            root,
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            parent,
            activation,
        ).splitlines()
        if changed != [relative.as_posix()]:
            errors.append("V11 activation changes more than its request")
        status = _git_at(
            root,
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--diff-filter=A",
            "--name-status",
            "-r",
            parent,
            activation,
            "--",
            relative.as_posix(),
        )
        if status != f"A\t{relative.as_posix()}":
            errors.append("V11 request was not a unique addition")
        entry = _tree_entry(root, activation, relative).split()
        if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
            errors.append("V11 request activation mode changed")
        template = TEMPLATE_PATH.read_bytes()
        expected = template.replace(
            b"__DIRECT_PARENT_COMMIT__",
            parent.encode("ascii"),
        )
        payload = subprocess.run(
            ["git", "show", f"{activation}:{relative.as_posix()}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if payload != expected:
            errors.append("V11 activation request differs from template")
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", activation, "HEAD"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if _lineage_path_changes(
            root=root,
            anchor=activation,
            paths=(relative,),
        ):
            errors.append("V11 active request changed after activation")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        errors.append(f"cannot verify V11 active request Git state: {exc}")
    return errors


def _validate_latest_stage_head(
    *,
    active_present: bool,
    root: Path = ROOT,
) -> list[str]:
    try:
        branch_head = _canonical_branch_head(root)
        anchor, anchor_errors = _authority_anchor(root=root)
        if anchor_errors or anchor is None:
            return []
        expected = anchor
        receipt, receipt_errors = _validate_inert_receipt(root=root)
        if not receipt_errors and receipt is not None:
            expected = receipt
        if active_present:
            additions = _true_additions(
                root=root,
                path=ACTIVE_REQUEST_PATH.relative_to(ROOT),
            )
            if len(additions) != 1:
                return []
            expected = additions[0]
        return (
            []
            if branch_head == expected
            else ["V11 canonical branch HEAD is not the latest exact stage"]
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [f"cannot verify V11 latest exact stage: {exc}"]


def validate_plan(
    *,
    verify_git_state: bool = True,
    active_request: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        workflow_bytes = _regular_file(WORKFLOW_PATH)
        template_bytes = _regular_file(TEMPLATE_PATH)
        fixture_bytes = _regular_file(SOURCE_FIXTURE_PATH)
        template = _strict_json_bytes(template_bytes, "V11 request template")
        fixture = _strict_json_bytes(fixture_bytes, "V11 source fixture")
    except (OSError, ValueError) as exc:
        return [f"cannot load V11 dependency-cache plan: {exc}"]
    if hashlib.sha256(workflow_bytes).hexdigest() != WORKFLOW_SHA256:
        errors.append("V11 workflow hash drift")
    if hashlib.sha256(template_bytes).hexdigest() != TEMPLATE_SHA256:
        errors.append("V11 template hash drift")
    if hashlib.sha256(fixture_bytes).hexdigest() != SOURCE_FIXTURE_SHA256:
        errors.append("V11 source fixture hash drift")
    errors.extend(_template_errors(template))
    errors.extend(_workflow_errors(workflow_bytes.decode("utf-8")))
    if (
        not isinstance(fixture, dict)
        or fixture.get("classification")
        != (
            "SOURCE_REVIEWED_GRAPH_CONTRACT_AND_V11_IMPLEMENTATION_REVIEW_"
            "NOT_V10_RUNTIME_EVIDENCE"
        )
        or fixture.get("actual_v10_runtime_metadata_retained") is not False
        or fixture.get("actual_v10_runtime_progress_retained") is not False
        or fixture.get("actual_v10_runtime_role_digest_retained") is not False
        or fixture.get("historical_v10_root_cause_status")
        != "UNKNOWN_NOT_RETAINED"
        or fixture.get("cache_config_claim_provenance")
        != (
            "V11_IMPLEMENTATION_REVIEWED_NOT_SOURCE_PROVEN_BY_LISTED_"
            "BUILDKIT_FILES"
        )
        or fixture.get("v11_contract", {}).get(
            "runtime_pip_cached_false_accepted"
        )
        is not False
        or fixture.get("combined_dockerfile", {}).get("derived_sha256")
        != (
            "c665ac4356bec6751d44878a416bbaa27"
            "8a77df77754f5461ba0adb13f43c2a0"
        )
    ):
        errors.append("V11 source fixture semantics changed")
    for path, expected in (
        (EXPORT_HELPER_PATH, EXPORT_HELPER_SHA256),
        (IMPORT_HELPER_PATH, IMPORT_HELPER_SHA256),
        (BUNDLE_VERIFIER_PATH, BUNDLE_VERIFIER_SHA256),
        (Path(v10_plan.__file__), V10_PLAN_VERIFIER_SHA256),
        (
            ROOT / "tools" / "verify_admin_dependency_cache_v10_failure_evidence.py",
            V10_FAILURE_VERIFIER_SHA256,
        ),
        (v10_failure.EVIDENCE_PATH, V10_FAILURE_EVIDENCE_SHA256),
    ):
        try:
            if _sha256(path) != expected:
                errors.append(f"V11 authority hash drift: {path.relative_to(ROOT)}")
        except OSError as exc:
            errors.append(f"cannot read V11 authority {path}: {exc}")
    try:
        v10_evidence = v10_failure.load_strict()
        errors.extend(
            v10_failure.verify(
                v10_evidence,
                verify_git_state=verify_git_state,
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot load frozen V10 failure evidence: {exc}")
    errors.extend(
        v10_plan.validate_plan(
            verify_git_state=verify_git_state,
        )
    )
    errors.extend(_validate_frozen_worktree())

    supplied = active_request is not None
    if supplied:
        present = True
        active = active_request
        active_errors: list[str] = []
    else:
        present, active, active_errors = _active_request()
    errors.extend(active_errors)
    if present and active is not None:
        expected = template_bytes.replace(
            b"__DIRECT_PARENT_COMMIT__",
            str(active.get("plan_checkpoint_commit", "")).encode("ascii"),
        )
        try:
            active_bytes = (
                json.dumps(
                    active,
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError):
            active_bytes = b""
        if (
            not COMMIT_RE.fullmatch(
                str(active.get("plan_checkpoint_commit", ""))
            )
            or active_bytes != expected
        ):
            errors.append("V11 active request differs from reviewed template")
        if verify_git_state and not supplied:
            errors.extend(_validate_active_git(active))
    elif present:
        errors.append("V11 active request is invalid")

    if verify_git_state:
        errors.extend(_validate_legacy_history())
        errors.extend(_validate_same_anchor())
        _receipt, receipt_errors = _validate_inert_receipt()
        errors.extend(receipt_errors)
        errors.extend(
            _validate_latest_stage_head(active_present=present)
        )
        if not present:
            try:
                if _true_additions(
                    root=ROOT,
                    path=ACTIVE_REQUEST_PATH.relative_to(ROOT),
                ):
                    errors.append("inactive V11 request has prior addition history")
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                errors.append(f"cannot verify inactive V11 request history: {exc}")
    return errors


def classify_plan_state(
    *,
    base_errors: list[str],
    active_present: bool,
    active_git_errors: list[str],
    additions: list[str],
) -> str:
    if base_errors:
        return "INVALID"
    if active_present:
        return (
            "V11_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V11_CONSUMED_OR_INVALID"
    return "PREPARED_V11_NOT_TRIGGERED"


def plan_state() -> str:
    base_errors = validate_plan(verify_git_state=False)
    present, active, active_errors = _active_request()
    try:
        additions = _true_additions(
            root=ROOT,
            path=ACTIVE_REQUEST_PATH.relative_to(ROOT),
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return "INVALID"
    git_errors = list(active_errors)
    if present and active is not None:
        git_errors.extend(_validate_active_git(active))
    if not present and additions:
        git_errors.append("inactive request has prior history")
    same_anchor_errors = _validate_same_anchor()
    _receipt, receipt_errors = _validate_inert_receipt()
    legacy_errors = _validate_legacy_history()
    latest_stage_errors = _validate_latest_stage_head(
        active_present=present,
    )
    return classify_plan_state(
        base_errors=(
            base_errors
            + same_anchor_errors
            + receipt_errors
            + legacy_errors
            + latest_stage_errors
        ),
        active_present=present,
        active_git_errors=git_errors,
        additions=additions,
    )


def main() -> int:
    errors = validate_plan()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"admin_dependency_cache_export_plan_v11=PASS state={plan_state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
