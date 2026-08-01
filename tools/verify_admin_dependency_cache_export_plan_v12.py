#!/usr/bin/env python3
"""Verify the inert, append-only V12 Admin dependency-cache recovery plan."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


LIVE_LEDGER_MODE = len(sys.argv) > 1 and sys.argv[1] == "live-ledger"
if LIVE_LEDGER_MODE:
    v11_plan = None
    v12_failure = None
else:
    import verify_admin_dependency_cache_export_plan_v11 as v11_plan
    import verify_admin_dependency_cache_v12_failure_evidence as v12_failure


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v12.yml"
)
TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v12.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v12.json"
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
PLAN_TEST_PATH = ROOT / "tests" / "test_admin_dependency_cache_export_plan_v12.py"

WORKFLOW_SHA256 = (
    "5370b9dd93c52be420c492cfc92fd459"
    "5934b87b4becac7a602019ed55b5531d"
)
TEMPLATE_SHA256 = (
    "c5a88fe6deadca0281a1a0fabebc3da0"
    "ad5bafb48357aa9d4319561ac1c3fe86"
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
V11_PLAN_VERIFIER_SHA256 = (
    "be6203f63a1c35603c1e7a851cd0a4f"
    "e0577807a28bf64c10e87530f953a28fe"
)
V11_PLAN_TEST_SHA256 = (
    "7ea3089a1bdbbe011ad1594b474766d50"
    "70410c837748d96003aaf22b6c4def5"
)
V11_TERMINAL_RECEIPT = "458f2482f9a3267bb9050a274f33ae21fc546ed7"
V11_INERT_CHECKPOINT = "606c474d347b4dad4e08e6f9fd038a82bdae5315"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
LEDGER_SCHEMA = "noteai.admin-dependency-cache-ledger.v12"
LEDGER_PAGE_SIZE = 100
LEDGER_PAGE_MAXIMUM = 10
LEDGER_ITEM_MAXIMUM = 1000
LEDGER_DEADLINE_SECONDS = 60
LEDGER_RESPONSE_MAXIMUM_BYTES = 16 * 1024 * 1024
V11_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v11.yml"
V12_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v12.yml"
LEGACY_LEDGER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "version": "v2",
        "workflow_ref": "323980939",
        "runs": (
            (
                30572921215,
                "c0d049b56aa6efaff7133ac44a9fef7f010cd097",
                (),
            ),
            (
                30591103183,
                "83b89262a33aed2cfa9fd623f232a66824398c2e",
                (91033410635,),
            ),
        ),
    },
    {
        "version": "v3",
        "workflow_ref": "324138560",
        "runs": ((30596283342, "443bb1e534f98232541f44b744d753bfa7c09168", (91049234229,)),),
    },
    {
        "version": "v4",
        "workflow_ref": "324161234",
        "runs": ((30599069993, "d5aa7e537590ed138d254b9909a1ac105ee321ce", (91057664696,)),),
    },
    {
        "version": "v5",
        "workflow_ref": "324220718",
        "runs": ((30606218502, "58871b0be3427ed643f44bc198c9fe3c87a01600", (91078891364,)),),
    },
    {
        "version": "v6",
        "workflow_ref": "324291491",
        "runs": ((30613707689, "5770f00d7e5756302d34b5f9159066dc3fd5d36d", (91101989637,)),),
    },
    {
        "version": "v7",
        "workflow_ref": "324378036",
        "runs": ((30622876575, "4494f50bf9a18422cef6252792bb9c6bbeaf1135", (91131267190,)),),
    },
    {
        "version": "v8",
        "workflow_ref": "324467538",
        "runs": ((30632611051, "354bec3b2d36bfaabc5c3307d49f5dc66255cbbf", (91162335850,)),),
    },
    {
        "version": "v9",
        "workflow_ref": "324655362",
        "runs": ((30651679657, "fbe629daad669191d4ea9903ffb488c98055f000", (91226182660,)),),
    },
    {
        "version": "v10",
        "workflow_ref": "324820330",
        "runs": ((30672160324, "ea2a3b489e74b21a88ea21ecd243cd6a433c7fac", (91291967175,)),),
    },
)
EXPECTED_WORKFLOW_HEADER = """name: Admin dependency cache export V12

on:
  push:
    branches:
      - codex/quality-stabilization-real-chain
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v12.json
"""
FROZEN_ACTIVATION_FILES = (
    (WORKFLOW_PATH.relative_to(ROOT), WORKFLOW_SHA256),
    (TEMPLATE_PATH.relative_to(ROOT), TEMPLATE_SHA256),
)
FROZEN_RUNTIME_FILES = (
    (EXPORT_HELPER_PATH.relative_to(ROOT), EXPORT_HELPER_SHA256),
    (IMPORT_HELPER_PATH.relative_to(ROOT), IMPORT_HELPER_SHA256),
    (SOURCE_FIXTURE_PATH.relative_to(ROOT), SOURCE_FIXTURE_SHA256),
    (BUNDLE_VERIFIER_PATH.relative_to(ROOT), BUNDLE_VERIFIER_SHA256),
)
SAME_ANCHOR_FILES = (
    WORKFLOW_PATH.relative_to(ROOT),
    TEMPLATE_PATH.relative_to(ROOT),
    PLAN_VERIFIER_PATH.relative_to(ROOT),
    PLAN_TEST_PATH.relative_to(ROOT),
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
INERT_RECEIPT_FILES = tuple(
    Path(value)
    for value in (
        ".codex/handoffs/current-task.md",
        ".codex/notes/risk-register.md",
        "deploy/production/internal-deployment-readiness.json",
        "tests/test_internal_deployment_readiness_gate.py",
    )
)
V12_NEW_CHECKPOINT_FILES = tuple(
    Path(value)
    for value in (
        ".github/workflows/admin-dependency-cache-export-v12.yml",
        "deploy/production/plans/admin-dependency-cache-export-request-v12.json",
        "tests/test_admin_dependency_cache_export_plan_v12.py",
        "tools/verify_admin_dependency_cache_export_plan_v12.py",
    )
)
CHECKPOINT_IMMUTABLE_FILES = tuple(
    path
    for path in INERT_CHECKPOINT_FILES
    if path not in set(INERT_RECEIPT_FILES)
)
LEGACY_FROZEN_PATHS = (
    tuple(
        sorted(
            {
                *v11_plan.LEGACY_FROZEN_PATHS,
                *(path for path, _sha256 in v11_plan.FROZEN_ACTIVATION_FILES),
                v11_plan.ACTIVE_REQUEST_PATH.relative_to(ROOT),
                Path("tools/verify_admin_dependency_cache_export_plan_v11.py"),
            },
            key=lambda path: path.as_posix(),
        )
    )
    if v11_plan is not None
    else ()
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
        return None, ["V12 frozen authorities are only partially present"]
    anchors: list[str] = []
    for path in SAME_ANCHOR_FILES:
        additions = _true_additions(root=root, path=path)
        if len(additions) != 1:
            errors.append(f"V12 frozen addition history is not unique: {path}")
        else:
            anchors.append(additions[0])
    if errors:
        return None, errors
    if len(set(anchors)) != 1:
        return None, ["V12 frozen authorities have different add anchors"]
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


def _expected_ledger_contract() -> dict[str, Any]:
    legacy: list[dict[str, Any]] = []
    for spec in LEGACY_LEDGER_SPECS:
        runs = []
        for run_id, head_sha, job_ids in spec["runs"]:
            runs.append(
                {
                    "id": run_id,
                    "head_sha": head_sha,
                    "event": "push",
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "failure",
                    "job_ids": list(job_ids),
                    "artifact_count": 0,
                }
            )
        legacy.append(
            {
                "version": spec["version"],
                "workflow_ref": spec["workflow_ref"],
                "runs": runs,
            }
        )
    legacy.append(
        {
            "version": "v11",
            "workflow_path": V11_WORKFLOW_PATH,
            "runs": [],
        }
    )
    return {
        "schema": LEDGER_SCHEMA,
        "page_size": LEDGER_PAGE_SIZE,
        "page_maximum": LEDGER_PAGE_MAXIMUM,
        "item_maximum": LEDGER_ITEM_MAXIMUM,
        "deadline_seconds": LEDGER_DEADLINE_SECONDS,
        "legacy": legacy,
        "current": {
            "version": "v12",
            "workflow_path": V12_WORKFLOW_PATH,
            "expected_run_count": 1,
            "event": "push",
            "run_attempt": 1,
            "artifact_count": 0,
        },
    }


def _template_errors(template: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(template.get("schema_version") == 12, "V12 schema changed")
    require(
        template.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "V12 task changed",
    )
    require(
        template.get("release_commit") == RELEASE_COMMIT,
        "V12 release changed",
    )
    require(
        template.get("plan_checkpoint_commit")
        == "__DIRECT_PARENT_COMMIT__",
        "V12 direct-parent placeholder changed",
    )
    require(
        template.get("trigger_mode") == "one_shot_added_request_v12",
        "V12 trigger mode changed",
    )
    predecessor = template.get("predecessor")
    require(
        predecessor
        == {
            "state": "V11_UNTRIGGERED_SUPERSEDED_EXACT",
            "inert_checkpoint_commit": V11_INERT_CHECKPOINT,
            "direct_parent_commit": V11_TERMINAL_RECEIPT,
            "workflow_path": V11_WORKFLOW_PATH,
            "workflow_sha256": v11_plan.WORKFLOW_SHA256,
            "template_sha256": v11_plan.TEMPLATE_SHA256,
            "plan_verifier_sha256": V11_PLAN_VERIFIER_SHA256,
            "export_helper_sha256": EXPORT_HELPER_SHA256,
            "import_helper_sha256": IMPORT_HELPER_SHA256,
            "source_fixture_sha256": SOURCE_FIXTURE_SHA256,
            "bundle_verifier_sha256": BUNDLE_VERIFIER_SHA256,
            "active_request_path": (
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v11.json"
            ),
            "active_request_addition_count": 0,
            "workflow_run_count": 0,
            "receipt_created": False,
            "activation_created": False,
            "supersession_reason": (
                "V2_WORKFLOW_HAS_TWO_IMMUTABLE_RUN_RECORDS"
            ),
        },
        "V12 predecessor supersession semantics changed",
    )
    recovery = template.get("recovery_basis")
    require(isinstance(recovery, dict), "V12 recovery basis missing")
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
            "V12 combined Dockerfile contract changed",
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
            "V12 target contract changed",
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
            "V12 recovery authority hash changed",
        )
        require(
            recovery.get("no_cache_filter_authorized") is False
            and recovery.get("dependency_cache_predicate_relaxed") is False
            and recovery.get(
                "github_actions_provenance_injection_authorized"
            )
            is False,
            "V12 cache or provenance policy changed",
        )
    chain = template.get("bundle_verifier_chain")
    require(
        isinstance(chain, dict)
        and chain.get("v10_sha256") == v11_plan.v10_plan.BUNDLE_VERIFIER_SHA256
        and chain.get("v11_sha256") == BUNDLE_VERIFIER_SHA256,
        "V12 verifier chain changed",
    )
    require(
        template.get("control_plane")
        == {
            "reused_concurrency_group": "admin-dependency-cache-export-v10",
            "inert_checkpoint_exact_changed_path_count": 11,
            "inert_receipt_exact_changed_path_count": 4,
            "activation_exact_changed_path_count": 1,
            "prepared_branch_head_exact_v11_inert_checkpoint_required": True,
            "canonical_branch_latest_exact_stage_required": True,
            "github_pr_merge_second_parent_projection_only": True,
            "checkpoint_nonreceipt_immutable_path_count": 7,
            "active_request_worktree_mode": "100644",
            "git_diff_errors_must_propagate": True,
            "run_ledger_snapshot_count": 2,
            "run_ledger_fresh_api_reads_required": True,
            "run_ledger_budget_seconds_per_snapshot": 60,
            "run_ledger_page_maximum": 10,
            "v2_exact_two_run_records_required": True,
            "v2_parser_zero_job_and_terminal_unique_job_required": True,
            "v3_v10_unique_attempt1_failure_artifact0_required": True,
            "v11_run_zero_required": True,
            "v12_current_attempt1_artifact0_required": True,
            "late_snapshot_after_cleanup_required": True,
            "late_snapshot_runs_on_prior_failure_after_cleanup": True,
            "python_optimized_mode_must_not_disable_checks": True,
            "post_activation_first_write_versioned_terminal_supersession_required": True,
        },
        "V12 control-plane contract changed",
    )
    require(
        template.get("run_ledger_contract") == _expected_ledger_contract(),
        "V12 run-ledger contract changed",
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
        "V12 evidence contract changed",
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
        "V12 bounded authorization changed",
    )
    return errors


def _workflow_errors(workflow: str) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(
        workflow.split("\npermissions:", 1)[0] == EXPECTED_WORKFLOW_HEADER,
        "V12 trigger block changed",
    )
    require("workflow_dispatch:" not in workflow, "V12 manual trigger enabled")
    require("pull_request:" not in workflow, "V12 pull-request trigger enabled")
    required = (
        "group: admin-dependency-cache-export-v10",
        "Prove this is the unique V12 workflow run for the branch lifecycle",
        'legacy_change_file="${RUNNER_TEMP}/noteai-cache-v12-legacy-change"',
        'test ! -s "${legacy_change_file}"',
        'v12_change_file="${RUNNER_TEMP}/noteai-cache-v12-authority-change"',
        'test ! -s "${v12_change_file}"',
        "Snapshot V2 through V12 ledgers before resource creation",
        "Snapshot V2 through V12 ledgers after cleanup and before upload",
        "if: ${{ always() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
        "and .schema_version == 12",
        ".control_plane.inert_checkpoint_exact_changed_path_count == 11",
        ".control_plane.checkpoint_nonreceipt_immutable_path_count == 7",
        "V2_WORKFLOW_HAS_TWO_IMMUTABLE_RUN_RECORDS",
        'ledger_verifier_copy="${RUNNER_TEMP}/noteai-cache-v12-ledger-verifier.py"',
        "steps.control.outputs.ledger_verifier_copy",
        ".import.v11_rawjson_diagnostic.schema_version",
        "live-ledger",
        "--phase pre_resource",
        "--phase post_cleanup_pre_upload",
        "--pre \"${pre_ledger}\"",
        "steps.pre_ledger.outputs.ledger_path",
        "steps.pre_ledger.outputs.ledger_sha256",
        "steps.late_ledger.outputs.ledger_sha256",
        "/actions/workflows/admin-dependency-cache-export-v12.yml/runs",
        "324820330",
        "30672160324",
        "noteai-cache-export-anchor",
        "noteai-cache-import-observer",
        "scripts/ci/export_admin_dependency_cache_v11.sh",
        "scripts/ci/import_admin_dependency_cache_v11.sh",
        "tools/verify_admin_dependency_cache_bundle_v10.py",
        "tools/verify_admin_dependency_cache_bundle_v11.py",
        "tools/verify_admin_dependency_cache_export_plan_v12.py",
        "Remove V12 builders and all transient Docker state",
        "Upload one-day V12 public-repository dependency cache artifact",
        "Remove runner-local V12 bundle",
    )
    for token in required:
        require(token in workflow, f"V12 workflow contract missing: {token}")
    forbidden = (
        "no-cache-filter",
        "workflow_dispatch",
        "docker login",
        "docker push",
        "az login",
        "az acr",
        "assert ",
        "def paginate(path, key):",
        "and .schema_version == 11",
        ".import.v12_rawjson_diagnostic",
        'test -z "$(\n                  git diff-tree',
    )
    for token in forbidden:
        require(token not in workflow, f"V12 workflow forbidden token: {token}")
    require(
        workflow.count("live-ledger") == 2
        and workflow.count("--phase pre_resource") == 1
        and workflow.count("--phase post_cleanup_pre_upload") == 1
        and workflow.count(
            '"${{ steps.control.outputs.ledger_verifier_copy }}"'
        )
        == 2
        and workflow.count(
            "python3 tools/verify_admin_dependency_cache_export_plan_v12.py"
        )
        == 1,
        "V12 single ledger implementation contract changed",
    )
    require(
        workflow.find("Remove V12 builders and all transient Docker state")
        < workflow.find(
            "Snapshot V2 through V12 ledgers after cleanup and before upload"
        )
        < workflow.find(
            "Upload one-day V12 public-repository dependency cache artifact"
        ),
        "V12 cleanup, late-ledger and upload ordering changed",
    )
    require(
        workflow.count("actions/upload-artifact@") == 1
        and "retention-days: 1" in workflow
        and "compression-level: 0" in workflow,
        "V12 artifact protocol changed",
    )
    return errors


def _validate_frozen_worktree() -> list[str]:
    errors: list[str] = []
    for relative, expected in (
        *FROZEN_ACTIVATION_FILES,
        *FROZEN_RUNTIME_FILES,
        (
            Path("tools/verify_admin_dependency_cache_export_plan_v11.py"),
            V11_PLAN_VERIFIER_SHA256,
        ),
    ):
        path = ROOT / relative
        try:
            payload = _regular_file(path)
            if hashlib.sha256(payload).hexdigest() != expected:
                errors.append(f"V12 frozen worktree hash drift: {relative}")
            if stat.S_IMODE(path.stat().st_mode) != 0o644:
                errors.append(f"V12 frozen worktree mode changed: {relative}")
        except (OSError, ValueError) as exc:
            errors.append(f"cannot verify V12 frozen worktree file {relative}: {exc}")
    try:
        for path in (PLAN_VERIFIER_PATH, PLAN_TEST_PATH):
            _regular_file(path)
            if stat.S_IMODE(path.stat().st_mode) != 0o644:
                errors.append(
                    f"V12 same-anchor worktree mode changed: {path.relative_to(ROOT)}"
                )
    except (OSError, ValueError) as exc:
        errors.append(f"cannot verify V12 same-anchor worktree file: {exc}")
    return errors


def _validate_legacy_history(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        branch_head = _canonical_branch_head(root)
        if _commit_parents(root, V11_INERT_CHECKPOINT) != [
            V11_TERMINAL_RECEIPT
        ]:
            errors.append("V11 inert checkpoint parent changed")
        if _changed_paths(
            root=root,
            parent=V11_TERMINAL_RECEIPT,
            commit=V11_INERT_CHECKPOINT,
        ) != set(v11_plan.INERT_CHECKPOINT_FILES):
            errors.append("V11 inert checkpoint is not the frozen exact 15-file delta")
        if not _on_first_parent_chain(
            root,
            V11_INERT_CHECKPOINT,
            head=branch_head,
        ):
            errors.append("V11 inert checkpoint left the canonical first-parent chain")
        for relative in v11_plan.INERT_CHECKPOINT_FILES:
            entry = _tree_entry(root, V11_INERT_CHECKPOINT, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V11 checkpoint mode changed: {relative}")
        frozen_v11_hashes = {
            **dict(v11_plan.FROZEN_ACTIVATION_FILES),
            Path("tools/verify_admin_dependency_cache_export_plan_v11.py"): (
                V11_PLAN_VERIFIER_SHA256
            ),
            Path("tests/test_admin_dependency_cache_export_plan_v11.py"): (
                V11_PLAN_TEST_SHA256
            ),
        }
        for relative, expected in frozen_v11_hashes.items():
            payload = subprocess.run(
                [
                    "git",
                    "show",
                    f"{V11_INERT_CHECKPOINT}:{relative.as_posix()}",
                ],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            if hashlib.sha256(payload).hexdigest() != expected:
                errors.append(f"V11 checkpoint hash drift: {relative}")
        v11_authorities = tuple(frozen_v11_hashes)[:7]
        if _lineage_path_changes(
            root=root,
            anchor=V11_INERT_CHECKPOINT,
            paths=v11_authorities,
        ):
            errors.append("V11 seven frozen authorities changed after checkpoint")
        v11_active = v11_plan.ACTIVE_REQUEST_PATH.relative_to(ROOT)
        if (root / v11_active).exists() or (root / v11_active).is_symlink():
            errors.append("V11 active request exists after supersession")
        if _true_additions(root=root, path=v11_active):
            errors.append("V11 active request has forbidden addition history")
        errors.extend(v11_plan._validate_legacy_history(root=root))
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        errors.append(f"cannot verify frozen V2-V11 history: {exc}")
    return errors


def validate_v11_untriggered_supersession(
    *,
    root: Path = ROOT,
) -> list[str]:
    """Validate V11 remains never-triggered and eligible for supersession."""
    return _validate_legacy_history(root=root)


def v11_untriggered_supersession_state(*, root: Path = ROOT) -> str:
    if validate_v11_untriggered_supersession(root=root):
        return "INVALID"
    if root == ROOT and v12_failure.terminal_checkpoint() is not None:
        return "V11_UNTRIGGERED_SUPERSEDED_EXACT"
    anchor, anchor_errors = _authority_anchor(root=root)
    if anchor_errors or _validate_same_anchor(root=root):
        return "INVALID"
    return (
        "V11_UNTRIGGERED_SUPERSESSION_PENDING"
        if anchor is None
        else "V11_UNTRIGGERED_SUPERSEDED_EXACT"
    )


def _validate_same_anchor(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        branch_head = _canonical_branch_head(root)
        anchor, anchor_errors = _authority_anchor(root=root)
        if anchor_errors:
            return anchor_errors
        if anchor is None:
            if branch_head != V11_INERT_CHECKPOINT:
                errors.append(
                    "V12 prepared branch HEAD is not the V11 inert checkpoint"
                )
            for relative in (
                *V12_NEW_CHECKPOINT_FILES,
                ACTIVE_REQUEST_PATH.relative_to(ROOT),
            ):
                if _true_additions(root=root, path=relative):
                    errors.append(
                        "V12 prepared state has prior addition history: "
                        f"{relative}"
                    )
            return errors
        if _commit_parents(root, anchor) != [V11_INERT_CHECKPOINT]:
            errors.append("V12 frozen anchor parent changed")
        elif _changed_paths(root, V11_INERT_CHECKPOINT, anchor) != set(
            INERT_CHECKPOINT_FILES
        ):
            errors.append("V12 inert checkpoint is not the exact 11-file delta")
        if not _on_first_parent_chain(root, anchor, head=branch_head):
            errors.append("V12 frozen anchor is not on the branch first-parent chain")
        for relative in INERT_CHECKPOINT_FILES:
            entry = _tree_entry(root, anchor, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V12 inert checkpoint mode changed: {relative}")
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
            errors.append("V12 immutable checkpoint path changed after add anchor")
        expected_hashes = dict(FROZEN_ACTIVATION_FILES)
        for relative in SAME_ANCHOR_FILES:
            entry = _tree_entry(root, "HEAD", relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V12 frozen HEAD mode changed: {relative}")
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
                errors.append(f"V12 frozen HEAD hash drift: {relative}")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        errors.append(f"cannot verify V12 frozen anchor: {exc}")
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
            return None, ["V12 inert receipt history is not unique"]
        receipt = changes[0]
        if _commit_parents(root, receipt) != [anchor]:
            errors.append("V12 inert receipt is not the direct child of anchor")
        elif _changed_paths(root, anchor, receipt) != set(
            INERT_RECEIPT_FILES
        ):
            errors.append("V12 inert receipt is not the exact 4-file delta")
        for relative in INERT_RECEIPT_FILES:
            entry = _tree_entry(root, receipt, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V12 inert receipt mode changed: {relative}")
        if not _on_first_parent_chain(root, receipt, head=branch_head):
            errors.append("V12 inert receipt is not on the branch first-parent chain")
        return receipt, errors
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return None, [f"cannot verify V12 inert receipt: {exc}"]


def _active_request(
    *,
    path: Path = ACTIVE_REQUEST_PATH,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    try:
        if not path.exists() and not path.is_symlink():
            return False, None, []
        payload = _regular_file(path)
        if stat.S_IMODE(path.stat().st_mode) != 0o644:
            return True, None, ["V12 active request worktree mode changed"]
        value = _strict_json_bytes(payload, "V12 active request")
        if not isinstance(value, dict):
            return True, None, ["V12 active request root changed"]
        return True, value, []
    except (OSError, ValueError) as exc:
        return True, None, [f"cannot load V12 active request: {exc}"]


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
            return ["V12 active request addition history is not unique"]
        activation = additions[0]
        if not _on_first_parent_chain(root, activation, head=branch_head):
            errors.append(
                "V12 activation is not on the branch first-parent chain"
            )
        parents = _commit_parents(root, activation)
        if len(parents) != 1:
            return ["V12 activation is not single-parent"]
        parent = parents[0]
        receipt, receipt_errors = _validate_inert_receipt(root=root)
        errors.extend(receipt_errors)
        if receipt is None or parent != receipt:
            errors.append("V12 activation parent is not the exact inert receipt")
        if active.get("plan_checkpoint_commit") != parent:
            errors.append("V12 active request does not bind its direct parent")
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
            errors.append("V12 activation changes more than its request")
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
            errors.append("V12 request was not a unique addition")
        entry = _tree_entry(root, activation, relative).split()
        if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
            errors.append("V12 request activation mode changed")
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
            errors.append("V12 activation request differs from template")
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
            errors.append("V12 active request changed after activation")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        errors.append(f"cannot verify V12 active request Git state: {exc}")
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
            else ["V12 canonical branch HEAD is not the latest exact stage"]
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [f"cannot verify V12 latest exact stage: {exc}"]


def validate_plan(
    *,
    verify_git_state: bool = True,
    active_request: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    terminal_checkpoint = None
    if verify_git_state and active_request is None:
        try:
            terminal_checkpoint = v12_failure.terminal_checkpoint()
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            errors.append(f"cannot resolve V12 terminal checkpoint: {exc}")
    try:
        workflow_bytes = _regular_file(WORKFLOW_PATH)
        template_bytes = _regular_file(TEMPLATE_PATH)
        fixture_bytes = _regular_file(SOURCE_FIXTURE_PATH)
        template = _strict_json_bytes(template_bytes, "V12 request template")
        fixture = _strict_json_bytes(fixture_bytes, "V12 source fixture")
    except (OSError, ValueError) as exc:
        return [f"cannot load V12 dependency-cache plan: {exc}"]
    if hashlib.sha256(workflow_bytes).hexdigest() != WORKFLOW_SHA256:
        errors.append("V12 workflow hash drift")
    if hashlib.sha256(template_bytes).hexdigest() != TEMPLATE_SHA256:
        errors.append("V12 template hash drift")
    if hashlib.sha256(fixture_bytes).hexdigest() != SOURCE_FIXTURE_SHA256:
        errors.append("V12 source fixture hash drift")
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
        errors.append("V12 source fixture semantics changed")
    for path, expected in (
        (EXPORT_HELPER_PATH, EXPORT_HELPER_SHA256),
        (IMPORT_HELPER_PATH, IMPORT_HELPER_SHA256),
        (BUNDLE_VERIFIER_PATH, BUNDLE_VERIFIER_SHA256),
        (Path(v11_plan.__file__), V11_PLAN_VERIFIER_SHA256),
    ):
        try:
            if _sha256(path) != expected:
                errors.append(f"V12 authority hash drift: {path.relative_to(ROOT)}")
        except OSError as exc:
            errors.append(f"cannot read V12 authority {path}: {exc}")
    errors.extend(
        v11_plan.validate_plan(
            verify_git_state=False,
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
            errors.append("V12 active request differs from reviewed template")
        if verify_git_state and not supplied and terminal_checkpoint is None:
            errors.extend(_validate_active_git(active))
    elif present:
        errors.append("V12 active request is invalid")

    if verify_git_state:
        errors.extend(validate_v11_untriggered_supersession())
        if terminal_checkpoint is not None:
            try:
                terminal_payload = v12_failure.load_strict()
                errors.extend(v12_failure.verify(terminal_payload))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ) as exc:
                errors.append(f"cannot load V12 terminal evidence: {exc}")
        else:
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
                        errors.append(
                            "inactive V12 request has prior addition history"
                        )
                except (
                    OSError,
                    subprocess.CalledProcessError,
                    ValueError,
                ) as exc:
                    errors.append(
                        f"cannot verify inactive V12 request history: {exc}"
                    )
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
            "V12_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V12_CONSUMED_OR_INVALID"
    return "PREPARED_V12_NOT_TRIGGERED"


def effective_plan_state() -> str:
    try:
        if v12_failure.terminal_checkpoint() is not None:
            return v12_failure.terminal_state()
    except (OSError, subprocess.CalledProcessError, ValueError):
        return "INVALID"
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
    legacy_errors = validate_v11_untriggered_supersession()
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


def plan_state() -> str:
    """Return the legacy request-activation lifecycle state.

    Frozen V11 consumers predate V12 execution-terminal states.  Preserve
    their public activation view while exposing the authoritative release
    outcome through ``effective_plan_state``.
    """
    state = effective_plan_state()
    if state in {
        "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT",
        "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
    }:
        return "V12_ARMED_OR_TRIGGERED_EXACT"
    return state


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"{label} is not an integer")
    return value


def _paginate_api(
    fetch: Callable[[str], dict[str, Any]],
    path: str,
    key: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    total: int | None = None
    seen_ids: set[int] = set()
    for page in range(1, LEDGER_PAGE_MAXIMUM + 1):
        separator = "&" if "?" in path else "?"
        payload = fetch(
            f"{path}{separator}per_page={LEDGER_PAGE_SIZE}&page={page}"
        )
        if not isinstance(payload, dict):
            raise RuntimeError("ledger page root changed")
        page_total = _strict_int(payload.get("total_count"), "ledger total")
        _require(
            0 <= page_total <= LEDGER_ITEM_MAXIMUM,
            "ledger total out of bounds",
        )
        if total is None:
            total = page_total
        _require(page_total == total, "ledger total changed across pages")
        page_items = payload.get(key)
        _require(isinstance(page_items, list), "ledger page items changed")
        for item in page_items:
            _require(isinstance(item, dict), "ledger item changed")
            item_id = _strict_int(item.get("id"), "ledger item id")
            _require(item_id not in seen_ids, "ledger item id duplicated")
            seen_ids.add(item_id)
            items.append(item)
        if len(items) == total or len(page_items) < LEDGER_PAGE_SIZE:
            break
    else:
        raise RuntimeError("ledger pagination exceeded")
    _require(total is not None and len(items) == total, "ledger pagination incomplete")
    return items


def _project_job(job: dict[str, Any]) -> dict[str, Any]:
    projection = {
        "id": _strict_int(job.get("id"), "job id"),
        "run_id": _strict_int(job.get("run_id"), "job run id"),
        "run_attempt": _strict_int(job.get("run_attempt"), "job run attempt"),
        "head_sha": job.get("head_sha"),
        "status": job.get("status"),
        "conclusion": job.get("conclusion"),
    }
    _require(
        isinstance(projection["head_sha"], str),
        "job head sha changed",
    )
    return projection


def _project_legacy_run(
    run: dict[str, Any],
    *,
    expected: dict[str, Any],
    fetch: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    run_id = _strict_int(run.get("id"), "run id")
    projection = {
        "id": run_id,
        "head_sha": run.get("head_sha"),
        "event": run.get("event"),
        "run_attempt": _strict_int(run.get("run_attempt"), "run attempt"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
    }
    for key in (
        "id",
        "head_sha",
        "event",
        "run_attempt",
        "status",
        "conclusion",
    ):
        _require(projection[key] == expected[key], f"legacy run {key} changed")
    jobs = _paginate_api(
        fetch,
        f"/actions/runs/{run_id}/jobs?filter=all",
        "jobs",
    )
    projected_jobs = sorted((_project_job(job) for job in jobs), key=lambda item: item["id"])
    _require(
        [job["id"] for job in projected_jobs] == expected["job_ids"],
        "legacy job vector changed",
    )
    for job in projected_jobs:
        _require(job["run_id"] == run_id, "legacy job run id changed")
        _require(job["run_attempt"] == 1, "legacy job attempt changed")
        _require(job["head_sha"] == expected["head_sha"], "legacy job head changed")
        _require(job["status"] == "completed", "legacy job status changed")
        _require(job["conclusion"] == "failure", "legacy job conclusion changed")
    artifacts = _paginate_api(
        fetch,
        f"/actions/runs/{run_id}/artifacts",
        "artifacts",
    )
    _require(
        len(artifacts) == expected["artifact_count"] == 0,
        "legacy artifact inventory changed",
    )
    projection["jobs"] = projected_jobs
    projection["artifacts"] = []
    return projection


def _collect_legacy_ledger(
    fetch: Callable[[str], dict[str, Any]],
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    legacy_projection: list[dict[str, Any]] = []
    for expected_version in contract["legacy"][:-1]:
        workflow_ref = expected_version["workflow_ref"]
        runs = _paginate_api(
            fetch,
            f"/actions/workflows/{workflow_ref}/runs",
            "workflow_runs",
        )
        expected_runs = expected_version["runs"]
        _require(len(runs) == len(expected_runs), "legacy workflow run count changed")
        by_id = {_strict_int(run.get("id"), "run id"): run for run in runs}
        _require(len(by_id) == len(runs), "legacy workflow run id duplicated")
        _require(set(by_id) == {run["id"] for run in expected_runs}, "legacy run ids changed")
        projected_runs = [
            _project_legacy_run(
                by_id[expected["id"]],
                expected=expected,
                fetch=fetch,
            )
            for expected in expected_runs
        ]
        legacy_projection.append(
            {
                "version": expected_version["version"],
                "workflow_ref": workflow_ref,
                "runs": projected_runs,
            }
        )
    repository_projections: list[list[dict[str, Any]]] = []
    for _observation in range(2):
        repository_runs = _paginate_api(fetch, "/actions/runs", "workflow_runs")
        projection = []
        for run in repository_runs:
            path = run.get("path")
            _require(isinstance(path, str), "repository run path changed")
            projection.append(
                {
                    "id": _strict_int(run.get("id"), "repository run id"),
                    "path": path,
                }
            )
        repository_projections.append(
            sorted(projection, key=lambda item: item["id"])
        )
    _require(
        _canonical_json_bytes(repository_projections[0])
        == _canonical_json_bytes(repository_projections[1]),
        "repository run inventory changed during snapshot",
    )
    v11_runs = [
        run
        for run in repository_projections[1]
        if run["path"] == V11_WORKFLOW_PATH
    ]
    _require(v11_runs == [], "V11 workflow run inventory is not zero")
    legacy_projection.append(
        {
            "version": "v11",
            "workflow_path": V11_WORKFLOW_PATH,
            "runs": [],
        }
    )
    return legacy_projection


def _collect_current_ledger(
    fetch: Callable[[str], dict[str, Any]],
    *,
    phase: str,
    run_id: int,
    head_sha: str,
    head_branch: str,
) -> dict[str, Any]:
    allowed_status = (
        {"queued", "in_progress"}
        if phase == "pre_resource"
        else {"in_progress"}
    )
    current = fetch(f"/actions/runs/{run_id}")
    _require(isinstance(current, dict), "current run root changed")
    _require(
        _strict_int(current.get("id"), "current endpoint run id") == run_id,
        "current endpoint run id changed",
    )
    _require(current.get("head_sha") == head_sha, "current endpoint head changed")
    _require(
        current.get("head_branch") == head_branch,
        "current endpoint branch changed",
    )
    _require(
        current.get("path") == V12_WORKFLOW_PATH,
        "current endpoint workflow path changed",
    )
    _require(current.get("event") == "push", "current endpoint event changed")
    _require(
        _strict_int(current.get("run_attempt"), "current endpoint attempt") == 1,
        "current endpoint rerun detected",
    )
    _require(
        current.get("status") in allowed_status,
        "current endpoint status changed",
    )
    _require(
        current.get("conclusion") is None,
        "current endpoint concluded early",
    )
    workflow_id = _strict_int(current.get("workflow_id"), "current workflow id")
    runs = _paginate_api(
        fetch,
        f"/actions/workflows/{workflow_id}/runs",
        "workflow_runs",
    )
    _require(len(runs) == 1, "V12 workflow run count changed")
    run = runs[0]
    _require(_strict_int(run.get("id"), "current run id") == run_id, "current run id changed")
    _require(
        _strict_int(run.get("workflow_id"), "current run workflow id")
        == workflow_id,
        "current run workflow id changed",
    )
    _require(run.get("head_sha") == head_sha, "current run head changed")
    _require(run.get("head_branch") == head_branch, "current run branch changed")
    _require(run.get("path") == V12_WORKFLOW_PATH, "current workflow path changed")
    _require(run.get("event") == "push", "current run event changed")
    _require(_strict_int(run.get("run_attempt"), "current attempt") == 1, "current rerun detected")
    _require(run.get("status") in allowed_status, "current run status changed")
    _require(run.get("conclusion") is None, "current run concluded early")
    _require(
        run.get("status") == current.get("status")
        and run.get("conclusion") == current.get("conclusion"),
        "current endpoint and workflow listing diverged",
    )
    artifacts = _paginate_api(
        fetch,
        f"/actions/runs/{run_id}/artifacts",
        "artifacts",
    )
    _require(artifacts == [], "current artifact inventory changed")
    return {
        "workflow_id": workflow_id,
        "id": run_id,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "path": V12_WORKFLOW_PATH,
        "event": "push",
        "run_attempt": 1,
        "status": run["status"],
        "conclusion": None,
        "artifacts": [],
    }


def _validate_prior_snapshot(
    snapshot: dict[str, Any],
    *,
    repository: str,
    run_id: int,
    head_sha: str,
    head_branch: str,
    contract_sha256: str,
) -> None:
    _require(
        set(snapshot) == {
            "schema",
            "repository",
            "phase",
            "contract_sha256",
            "legacy",
            "current",
        },
        "pre-resource ledger fields changed",
    )
    _require(snapshot.get("schema") == LEDGER_SCHEMA, "pre-resource schema changed")
    _require(snapshot.get("repository") == repository, "pre-resource repository changed")
    _require(snapshot.get("phase") == "pre_resource", "pre-resource phase changed")
    _require(
        snapshot.get("contract_sha256") == contract_sha256,
        "pre-resource contract changed",
    )
    _require(isinstance(snapshot.get("legacy"), list), "pre-resource legacy changed")
    current = snapshot.get("current")
    _require(isinstance(current, dict), "pre-resource current run changed")
    _require(
        set(current) == {
            "workflow_id",
            "id",
            "head_sha",
            "head_branch",
            "path",
            "event",
            "run_attempt",
            "status",
            "conclusion",
            "artifacts",
        },
        "pre-resource current fields changed",
    )
    _require(
        _strict_int(current.get("workflow_id"), "pre-resource workflow id") > 0,
        "pre-resource workflow id changed",
    )
    _require(
        _strict_int(current.get("id"), "pre-resource run id") == run_id,
        "pre-resource run id changed",
    )
    _require(current.get("head_sha") == head_sha, "pre-resource head changed")
    _require(
        current.get("head_branch") == head_branch,
        "pre-resource branch changed",
    )
    _require(current.get("path") == V12_WORKFLOW_PATH, "pre-resource path changed")
    _require(current.get("event") == "push", "pre-resource event changed")
    _require(
        _strict_int(current.get("run_attempt"), "pre-resource attempt") == 1,
        "pre-resource rerun detected",
    )
    _require(
        current.get("status") in {"queued", "in_progress"},
        "pre-resource status changed",
    )
    _require(current.get("conclusion") is None, "pre-resource concluded early")
    _require(current.get("artifacts") == [], "pre-resource artifacts changed")


def collect_live_ledger_snapshot(
    *,
    phase: str,
    repository: str,
    run_id: int,
    head_sha: str,
    head_branch: str,
    fetch: Callable[[str], dict[str, Any]],
    pre_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require(
        phase in {"pre_resource", "post_cleanup_pre_upload"},
        "ledger phase changed",
    )
    contract = _expected_ledger_contract()
    legacy = _collect_legacy_ledger(fetch, contract)
    current = _collect_current_ledger(
        fetch,
        phase=phase,
        run_id=run_id,
        head_sha=head_sha,
        head_branch=head_branch,
    )
    contract_sha256 = hashlib.sha256(
        _canonical_json_bytes(contract)
    ).hexdigest()
    snapshot = {
        "schema": LEDGER_SCHEMA,
        "repository": repository,
        "phase": phase,
        "contract_sha256": contract_sha256,
        "legacy": legacy,
        "current": current,
    }
    if phase == "post_cleanup_pre_upload":
        _require(isinstance(pre_snapshot, dict), "pre-resource ledger missing")
        _validate_prior_snapshot(
            pre_snapshot,
            repository=repository,
            run_id=run_id,
            head_sha=head_sha,
            head_branch=head_branch,
            contract_sha256=contract_sha256,
        )
        _require(
            _canonical_json_bytes(pre_snapshot.get("legacy"))
            == _canonical_json_bytes(legacy),
            "legacy ledger changed between snapshots",
        )
        _require(
            pre_snapshot.get("contract_sha256") == snapshot["contract_sha256"],
            "ledger contract changed between snapshots",
        )
        pre_current = dict(pre_snapshot["current"])
        post_current = dict(current)
        pre_current.pop("status")
        post_current.pop("status")
        _require(
            _canonical_json_bytes(pre_current)
            == _canonical_json_bytes(post_current),
            "current run identity changed between snapshots",
        )
    return snapshot


def _live_api_fetcher(
    *,
    repository: str,
    token: str,
    deadline: float,
) -> Callable[[str], dict[str, Any]]:
    def fetch(path: str) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{repository}{path}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": "noteai-v12-ledger",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        last_error: BaseException | None = None
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            _require(remaining > 0, "V12 ledger deadline exceeded")
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=max(0.1, min(15.0, remaining)),
                ) as response:
                    response_bytes = response.read(
                        LEDGER_RESPONSE_MAXIMUM_BYTES + 1
                    )
                _require(
                    len(response_bytes) <= LEDGER_RESPONSE_MAXIMUM_BYTES,
                    "GitHub ledger response is too large",
                )
                payload = json.loads(
                    response_bytes.decode("utf-8"),
                    parse_constant=lambda token: (_ for _ in ()).throw(
                        ValueError(f"non-finite JSON token: {token}")
                    ),
                )
                _require(isinstance(payload, dict), "GitHub response root changed")
                return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code != 429 and not 500 <= exc.code <= 599:
                    raise RuntimeError("non-retryable GitHub ledger response") from exc
            except (
                UnicodeDecodeError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
                ValueError,
            ) as exc:
                last_error = exc
            if attempt < 2:
                remaining = deadline - time.monotonic()
                _require(remaining > 0, "V12 ledger deadline exceeded")
                time.sleep(min(1.0, remaining))
        raise RuntimeError("GitHub ledger request failed") from last_error

    return fetch


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = _regular_file(path)
    _require(stat.S_IMODE(path.stat().st_mode) == 0o600, "ledger snapshot mode changed")
    value = json.loads(payload)
    _require(isinstance(value, dict), "ledger snapshot root changed")
    _require(_canonical_json_bytes(value) == payload, "ledger snapshot is not canonical")
    return value


def _write_snapshot(path: Path, value: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        payload = _canonical_json_bytes(value)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _require(stat.S_IMODE(path.stat().st_mode) == 0o600, "ledger snapshot mode changed")


def _live_ledger_main(arguments: list[str]) -> int:
    options: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        key = arguments[index]
        _require(key in {"--phase", "--output", "--pre"}, "ledger option changed")
        _require(index + 1 < len(arguments), "ledger option value missing")
        _require(key not in options, "ledger option duplicated")
        options[key] = arguments[index + 1]
        index += 2
    phase = options.get("--phase", "")
    output = Path(options.get("--output", ""))
    _require(output.as_posix() not in {"", "."}, "ledger output missing")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("NOTEAI_ACTIONS_READ_TOKEN", "")
    head_sha = os.environ.get("GITHUB_SHA", "")
    head_branch = os.environ.get("GITHUB_REF_NAME", "")
    _require(re.fullmatch(r"[^/\s]+/[^/\s]+", repository) is not None, "repository changed")
    _require(token != "", "Actions read token missing")
    _require(COMMIT_RE.fullmatch(head_sha) is not None, "GitHub head changed")
    _require(head_branch == "codex/quality-stabilization-real-chain", "GitHub branch changed")
    run_id = _strict_int(int(os.environ.get("GITHUB_RUN_ID", "0")), "GitHub run id")
    _require(run_id > 0, "GitHub run id changed")
    deadline = time.monotonic() + LEDGER_DEADLINE_SECONDS
    fetch = _live_api_fetcher(
        repository=repository,
        token=token,
        deadline=deadline,
    )
    pre_snapshot = None
    if phase == "post_cleanup_pre_upload":
        pre_path = Path(options.get("--pre", ""))
        _require(pre_path.as_posix() not in {"", "."}, "pre-resource ledger path missing")
        pre_snapshot = _load_snapshot(pre_path)
    else:
        _require("--pre" not in options, "pre-resource ledger unexpectedly supplied")
    snapshot = collect_live_ledger_snapshot(
        phase=phase,
        repository=repository,
        run_id=run_id,
        head_sha=head_sha,
        head_branch=head_branch,
        fetch=fetch,
        pre_snapshot=pre_snapshot,
    )
    _write_snapshot(output, snapshot)
    print(f"admin_dependency_cache_v12_live_ledger=PASS phase={phase}")
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        _require(sys.argv[1] == "live-ledger", "V12 command changed")
        return _live_ledger_main(sys.argv[2:])
    errors = validate_plan()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "admin_dependency_cache_export_plan_v12=PASS "
        f"state={effective_plan_state()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
