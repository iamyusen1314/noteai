#!/usr/bin/env python3
"""Verify the C17-anchored, GitHub-native V17 cache-export plan."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/admin-dependency-cache-export-v17.yml"
CI_WORKFLOW_PATH = ROOT / ".github/workflows/ci.yml"
TEMPLATE_PATH = ROOT / "deploy/production/plans/admin-dependency-cache-export-request-v17.json"
ACTIVE_REQUEST_PATH = ROOT / ".github/release-requests/admin-5335bda-dependency-cache-v17.json"
EXPORT_HELPER_PATH = ROOT / "scripts/ci/export_admin_dependency_cache_v17.sh"
IMPORT_HELPER_PATH = ROOT / "scripts/ci/import_admin_dependency_cache_v17.sh"
SOURCE_FIXTURE_PATH = ROOT / "tests/fixtures/admin_dependency_cache_v17_frontend_lifecycle_and_localstate_projection.json"
TRANSIENT_VERIFIER_PATH = ROOT / "tools/verify_admin_dependency_cache_transient_state_v17.py"
TRANSIENT_TEST_PATH = ROOT / "tests/test_admin_dependency_cache_transient_state_v17.py"
BUNDLE_VERIFIER_PATH = ROOT / "tools/verify_admin_dependency_cache_bundle_v17.py"
BUNDLE_TEST_PATH = ROOT / "tests/test_admin_dependency_cache_bundle_verifier_v17.py"
PLAN_TEST_PATH = ROOT / "tests/test_admin_dependency_cache_export_plan_v17.py"
V16_TERMINAL_VERIFIER_PATH = ROOT / "tools/verify_admin_dependency_cache_v16_failure_evidence.py"
V16_TERMINAL_TEST_PATH = ROOT / "tests/test_admin_dependency_cache_v16_failure_evidence.py"
V16_EVIDENCE_PATH = ROOT / "deploy/production/evidence/admin-dependency-cache-v16-attempt1-failed-20260802.json"
PRODUCTION_GATE_PATH = ROOT / "tools/production_readiness_gate.py"
PRODUCTION_GATE_TEST_PATH = ROOT / "tests/test_production_readiness_gate.py"

C17_DATA_PLANE_ANCHOR = "7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
BRANCH = "codex/quality-stabilization-real-chain"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

WORKFLOW_SHA256 = "b13e1ed903792e7f036a0b3eedd5aa6f393c29141a66bf75716dd3eb8e733a1a"
TEMPLATE_SHA256 = "be82c35d63f31ea6f3a33f0a2188e8fee12c43df73728dcea4f42421a611f7b1"
EXPORT_HELPER_SHA256 = "e2eb4b1466b245880fbb3bef7b34ae5f868ca8c1279def268038642d061b6eda"
IMPORT_HELPER_SHA256 = "b39b98d969052417d779a124c7c942fe89d4bcd50db0ad1bcde5121800b8185d"
SOURCE_FIXTURE_SHA256 = "5c020473f8f8e7cc189c3e936a8b41c76bdc2a9fde38fc79c7d11d31e9050b54"
BUNDLE_VERIFIER_SHA256 = "d25fc0ea403b12f87810dd12d9bcdd304ed6e73730873a980782d621293e9402"
BUNDLE_TEST_SHA256 = "6934d3e83053d0d5e91ce58625dc402667274b8811bb1ae486a364ced9c21902"
TRANSIENT_VERIFIER_SHA256 = "967e3545b6ca080574d33c137d77e89449dd6affc3a48473bbc460f8dfbf7e20"
TRANSIENT_TEST_SHA256 = "4fbb5e711e6ab44ce8d83d70880397db0d94c6a17cc050f696d7af1b8725c9fa"
PLAN_TEST_SHA256 = "b016fc71aca8dbe01954b62880a590f78c0b637bf6903af52805d1e2fb6353d2"
CI_WORKFLOW_SHA256 = "8a4e96f9539be4ee1a53688247706976084370047205831103322e330f1e6b04"
PRODUCTION_GATE_SHA256 = "6d3c464a7c71888296560dbd21a800705e47d6347911beb634f081266121df49"
PRODUCTION_GATE_TEST_SHA256 = "c2cac2d0390967f59717a1cff6e8f0cb4ab0af071b7a0ee3ca991b2d9ae63b89"
V16_TERMINAL_VERIFIER_SHA256 = "1d6f53c9f812e2dfc93a4ec8c7c452e47585d1b0186777a25ea84d97ecc67d34"
V16_TERMINAL_TEST_SHA256 = "8834e00c732f84dbb9866c31b038d74b4f3bd35922b80ac95878aed3a2d9f9b4"
V16_EVIDENCE_SHA256 = "3b5881161d560b2a20da313a828faa04b7d0da374136eab3cc7f171a6f1f5d97"

V16_ACTIVATION = "fd1444d0a62549b3c353cbc1188e6ba25a77e96e"
V16_TERMINAL_CHECKPOINT = "4c2df3b19b4f5493adba78eed89c3a015d76972d"
V16_TERMINAL_RECEIPT = "751da973dd7136d792adfafa11e50f5e5e0bd689"

DATA_PLANE_FILES = (
    (Path("scripts/ci/export_admin_dependency_cache_v17.sh"), EXPORT_HELPER_SHA256),
    (Path("scripts/ci/import_admin_dependency_cache_v17.sh"), IMPORT_HELPER_SHA256),
    (
        Path("tests/fixtures/admin_dependency_cache_v17_frontend_lifecycle_and_localstate_projection.json"),
        SOURCE_FIXTURE_SHA256,
    ),
    (Path("tools/verify_admin_dependency_cache_bundle_v17.py"), BUNDLE_VERIFIER_SHA256),
    (Path("tests/test_admin_dependency_cache_bundle_verifier_v17.py"), BUNDLE_TEST_SHA256),
    (Path("tools/verify_admin_dependency_cache_transient_state_v17.py"), TRANSIENT_VERIFIER_SHA256),
    (Path("tests/test_admin_dependency_cache_transient_state_v17.py"), TRANSIENT_TEST_SHA256),
)

WORKFLOW_DATA_PLANE_STEPS = (
    "Checkout exact 5335 release source",
    "Verify immutable dependency-prefix source",
    "Create isolated V17 producer and consumer builders",
    "Export V17 dependency-only BuildKit local cache",
    "Prove V17 import and external-cache-removed same-builder replay",
    "Remove V17 builders and all transient Docker state",
)


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json_bytes(payload: bytes, label: str) -> Any:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON token: {token}")
            ),
            parse_float=lambda token: (
                float(token)
                if math.isfinite(float(token))
                else (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON number: {token}")
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    canonical = (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")
    if payload != canonical:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _read_frozen_bytes(
    path: Path,
    *,
    label: str,
    maximum_bytes: int = 4_194_304,
    required_mode: int | None = None,
) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or (
                required_mode is not None
                and stat.S_IMODE(before.st_mode) != required_mode
            )
        ):
            raise ValueError(f"{label} file contract changed")
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > maximum_bytes:
                raise ValueError(f"{label} exceeded size bound")
        after = os.fstat(descriptor)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
            or observed != before.st_size
        ):
            raise ValueError(f"{label} changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _git_at(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _git_blob(root: Path, commit: str, path: Path) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path.as_posix()}"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _commit_parents(root: Path, commit: str) -> list[str]:
    record = _git_at(root, "rev-list", "--parents", "-n", "1", commit).split()
    if not record or record[0] != commit:
        raise ValueError(f"cannot resolve commit parents: {commit}")
    return record[1:]


def _tree_entry(root: Path, commit: str, relative: Path) -> str:
    return _git_at(root, "ls-tree", commit, "--", relative.as_posix())


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


def _true_additions(*, root: Path = ROOT, path: Path) -> list[str]:
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
        if _tree_entry(root, commit, path) and all(
            not _tree_entry(root, parent, path) for parent in parents
        ):
            additions.append(commit)
    return additions


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            stderr=result.stderr,
        )
    return result.returncode == 0


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


def _load_v16_terminal_verifier():
    source = _read_frozen_bytes(
        V16_TERMINAL_VERIFIER_PATH,
        label="V16 terminal verifier",
        required_mode=0o644,
    )
    if hashlib.sha256(source).hexdigest() != V16_TERMINAL_VERIFIER_SHA256:
        raise ValueError("V16 terminal verifier hash drift")
    module_name = "_noteai_v16_terminal_for_v17"
    module = types.ModuleType(module_name)
    module.__file__ = str(V16_TERMINAL_VERIFIER_PATH)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(
            compile(source, str(V16_TERMINAL_VERIFIER_PATH), "exec"),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _validate_v16_predecessor(*, root: Path = ROOT) -> list[str]:
    """Validate frozen V16 history without making it a V17 activation parent."""
    errors: list[str] = []
    try:
        if _commit_parents(root, V16_TERMINAL_CHECKPOINT) != [V16_ACTIVATION]:
            errors.append("V16 terminal checkpoint parent changed")
        if _commit_parents(root, V16_TERMINAL_RECEIPT) != [V16_TERMINAL_CHECKPOINT]:
            errors.append("V16 terminal receipt parent changed")
        if not _is_ancestor(root, V16_TERMINAL_RECEIPT, C17_DATA_PLANE_ANCHOR):
            errors.append("V16 terminal receipt is not an ancestor of C17")
        if root.resolve() == ROOT.resolve():
            evidence = _read_frozen_bytes(
                V16_EVIDENCE_PATH,
                label="V16 terminal evidence",
                required_mode=0o644,
            )
            if hashlib.sha256(evidence).hexdigest() != V16_EVIDENCE_SHA256:
                errors.append("V16 terminal evidence hash drift")
            else:
                terminal = _load_v16_terminal_verifier()
                semantic_errors = terminal.verify(
                    terminal.load_strict(),
                    verify_git_state=False,
                )
                if semantic_errors:
                    errors.append(
                        "V16 terminal semantic validation failed: "
                        + "; ".join(semantic_errors[:5])
                    )
                original_canonical_head = terminal._canonical_head
                try:
                    terminal._canonical_head = lambda: V16_TERMINAL_RECEIPT
                    historical_errors = terminal.verify_frozen_git()
                finally:
                    terminal._canonical_head = original_canonical_head
                if historical_errors:
                    errors.append(
                        "V16 terminal historical Git validation failed: "
                        + "; ".join(historical_errors[:5])
                    )
                if terminal.terminal_checkpoint() != V16_TERMINAL_CHECKPOINT:
                    errors.append("V16 terminal checkpoint changed")
                elif terminal.terminal_receipt(V16_TERMINAL_CHECKPOINT) != V16_TERMINAL_RECEIPT:
                    errors.append("V16 terminal receipt changed")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify V16 terminal predecessor: {exc}")
    return errors


def _expected_control_plane() -> dict[str, Any]:
    return {
        "data_plane_anchor_commit": C17_DATA_PLANE_ANCHOR,
        "data_plane_anchor_kind": "C17_IMMUTABLE_DATA_PLANE",
        "custom_ledger_required": False,
        "custom_receipt_required": False,
        "custom_topology_required": False,
        "activation_request_addition_count": 1,
        "activation_request_mode": "100644",
        "native_acceptance_evidence": [
            "github_workflow_run_id",
            "c17_commit_sha",
            "artifact_digest",
            "fresh_builder_import_success",
        ],
    }


def _template_errors(template: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version": 17,
        "task": "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "release_commit": RELEASE_COMMIT,
        "plan_checkpoint_commit": "__DIRECT_PARENT_COMMIT__",
        "release_scope": "admin_dependency_prefix_cache_recovery",
        "trigger_mode": "one_shot_added_request_v17",
        "control_plane": _expected_control_plane(),
        "github_actions_maximum_run_count": 1,
        "github_actions_maximum_runtime_minutes": 120,
        "artifact_retention_days": 1,
        "dependency_cache_export_authorized": True,
        "public_repository_artifact_authorized": True,
        "registry_publication_authorized": False,
        "deployment_authorized": False,
        "database_authorized": False,
        "service_mutation_authorized": False,
        "public_traffic_authorized": False,
    }
    for key, expected in required.items():
        if template.get(key) != expected:
            errors.append(f"V17 template field changed: {key}")
    if "predecessor" in template:
        errors.append("V17 template still requires a predecessor receipt")
    if "run_ledger_contract" in template:
        errors.append("V17 template still requires a custom run ledger")
    recovery = template.get("recovery_basis")
    build = template.get("build_evidence_recovery")
    provider = template.get("provider_artifact_protocol")
    if not (
        isinstance(recovery, dict)
        and recovery.get("v17_export_helper_sha256") == EXPORT_HELPER_SHA256
        and recovery.get("v17_import_helper_sha256") == IMPORT_HELPER_SHA256
        and recovery.get("git_main_context_identity_source_projection_sha256")
        == SOURCE_FIXTURE_SHA256
        and recovery.get("v17_bundle_verifier_sha256") == BUNDLE_VERIFIER_SHA256
        and recovery.get("v17_transient_state_verifier_sha256")
        == TRANSIENT_VERIFIER_SHA256
        and recovery.get("fresh_consumer_same_source_copy_pip_digests_cached_required")
        is True
    ):
        errors.append("V17 template C17 data-plane binding changed")
    if not (
        isinstance(build, dict)
        and build.get("identity_pair_classification_required")
        == "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED"
        and build.get("runtime_portability_proven_only_by_fresh_consumer_and_same_builder_replay")
        is True
        and build.get("runtime_pip_cached_false_accepted") is False
        and build.get("true_empty_cache_replay_claimed") is False
    ):
        errors.append("V17 template fresh-builder acceptance changed")
    if not (
        isinstance(provider, dict)
        and provider.get("artifact_name")
        == "admin-dependency-prefix-cache-5335bda-v2"
    ):
        errors.append("V17 provider artifact protocol changed")
    return errors


def _workflow_errors(workflow: str) -> list[str]:
    errors: list[str] = []
    required_fragments = (
        "NOTEAI_C17_DATA_PLANE_ANCHOR: " + C17_DATA_PLANE_ANCHOR,
        "Resolve C17-anchored V17 activation request",
        "git merge-base --is-ancestor \"${NOTEAI_C17_DATA_PLANE_ANCHOR}\" \"${controller_parent}\"",
        "PYTHONDONTWRITEBYTECODE=1 python3 tools/verify_admin_dependency_cache_export_plan_v17.py",
        "GITHUB_RUN_ATTEMPT",
        "id: bundle",
        "portability_proof_sha256",
        "workflow_run_id=${GITHUB_RUN_ID}",
        "c17_commit_sha=${NOTEAI_C17_DATA_PLANE_ANCHOR}",
        "artifact_digest=${{ steps.upload.outputs.artifact-digest }}",
        "fresh_builder_import_succeeded=true",
        "fresh_builder_import_proof_sha256=${{ steps.bundle.outputs.portability_proof_sha256 }}",
        "retention-days: 1",
    )
    for fragment in required_fragments:
        if fragment not in workflow:
            errors.append(f"V17 workflow native control missing: {fragment}")
    forbidden_fragments = (
        "actions: read",
        "NOTEAI_ACTIONS_READ_TOKEN",
        "api.github.com",
        "live-ledger",
        "RUN_LEDGER",
        "pre_ledger",
        "late_ledger",
        "exact18",
        "exact4",
        "Snapshot V2 through V17 ledgers",
        "ledger_contract_copy",
        "ledger_verifier_copy",
    )
    for fragment in forbidden_fragments:
        if fragment in workflow:
            errors.append(f"V17 workflow retains custom control: {fragment}")
    step_positions = [workflow.find(f"      - name: {name}\n") for name in WORKFLOW_DATA_PLANE_STEPS]
    if any(position < 0 for position in step_positions):
        errors.append("V17 workflow data-plane step missing")
    if not (
        0
        <= workflow.find("Remove V17 builders and all transient Docker state")
        < workflow.find("Validate final V17 portable bundle after cleanup")
        < workflow.find("Upload one-day V17 public-repository dependency cache artifact")
        < workflow.find("Confirm V17 native acceptance evidence")
    ):
        errors.append("V17 cleanup, validation, upload or native evidence order changed")
    builder = workflow.find("Create isolated V17 producer and consumer builders")
    attempt_guard = workflow.find('test "${GITHUB_RUN_ATTEMPT}" = "1"')
    if not 0 <= attempt_guard < builder:
        errors.append("V17 attempt-one guard does not precede resource creation")
    return errors


def _extract_workflow_step(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.find(marker)
    if start < 0:
        raise ValueError(f"workflow step missing: {name}")
    end = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start:] if end < 0 else workflow[start : end + 1]


def _static_hash_errors() -> list[str]:
    errors: list[str] = []
    frozen = (
        (WORKFLOW_PATH, WORKFLOW_SHA256),
        (CI_WORKFLOW_PATH, CI_WORKFLOW_SHA256),
        (TEMPLATE_PATH, TEMPLATE_SHA256),
        (EXPORT_HELPER_PATH, EXPORT_HELPER_SHA256),
        (IMPORT_HELPER_PATH, IMPORT_HELPER_SHA256),
        (SOURCE_FIXTURE_PATH, SOURCE_FIXTURE_SHA256),
        (BUNDLE_VERIFIER_PATH, BUNDLE_VERIFIER_SHA256),
        (BUNDLE_TEST_PATH, BUNDLE_TEST_SHA256),
        (TRANSIENT_VERIFIER_PATH, TRANSIENT_VERIFIER_SHA256),
        (TRANSIENT_TEST_PATH, TRANSIENT_TEST_SHA256),
        (PLAN_TEST_PATH, PLAN_TEST_SHA256),
        (PRODUCTION_GATE_PATH, PRODUCTION_GATE_SHA256),
        (PRODUCTION_GATE_TEST_PATH, PRODUCTION_GATE_TEST_SHA256),
        (V16_TERMINAL_VERIFIER_PATH, V16_TERMINAL_VERIFIER_SHA256),
        (V16_TERMINAL_TEST_PATH, V16_TERMINAL_TEST_SHA256),
        (V16_EVIDENCE_PATH, V16_EVIDENCE_SHA256),
    )
    for path, expected in frozen:
        try:
            payload = _read_frozen_bytes(
                path,
                label=path.as_posix(),
                required_mode=0o644,
            )
            if hashlib.sha256(payload).hexdigest() != expected:
                errors.append(f"V17 authority hash drift: {path.relative_to(ROOT)}")
        except (OSError, ValueError) as exc:
            errors.append(f"cannot read V17 authority {path}: {exc}")
    return errors


def _validate_c17_data_plane_anchor(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        canonical_head = _canonical_branch_head(root)
        if not _is_ancestor(root, C17_DATA_PLANE_ANCHOR, canonical_head):
            errors.append("canonical branch head is not a C17 descendant")
            return errors
        for relative, expected_sha256 in DATA_PLANE_FILES:
            anchor_entry = _tree_entry(root, C17_DATA_PLANE_ANCHOR, relative).split()
            head_entry = _tree_entry(root, canonical_head, relative).split()
            if len(anchor_entry) < 3 or anchor_entry[:2] != ["100644", "blob"]:
                errors.append(f"C17 data-plane entry changed: {relative}")
                continue
            if head_entry != anchor_entry:
                errors.append(f"C17 data-plane tree drift: {relative}")
            payload = _git_blob(root, C17_DATA_PLANE_ANCHOR, relative)
            if hashlib.sha256(payload).hexdigest() != expected_sha256:
                errors.append(f"C17 data-plane hash changed: {relative}")
        if root.resolve() == ROOT.resolve():
            anchor_workflow = _git_blob(
                root,
                C17_DATA_PLANE_ANCHOR,
                WORKFLOW_PATH.relative_to(ROOT),
            ).decode("utf-8")
            current_workflow = _read_frozen_bytes(
                WORKFLOW_PATH,
                label="V17 workflow",
                required_mode=0o644,
            ).decode("utf-8")
            for name in WORKFLOW_DATA_PLANE_STEPS:
                if _extract_workflow_step(current_workflow, name) != _extract_workflow_step(
                    anchor_workflow,
                    name,
                ):
                    errors.append(f"C17 workflow data-plane step drift: {name}")
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify C17 data-plane anchor: {exc}")
    return errors


def _active_request(
    *, path: Path = ACTIVE_REQUEST_PATH
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    try:
        if not path.exists() and not path.is_symlink():
            return False, None, []
        payload = _read_frozen_bytes(
            path,
            label="V17 active request",
            required_mode=0o644,
        )
        value = _strict_json_bytes(payload, "V17 active request")
        if not isinstance(value, dict):
            return True, None, ["V17 active request root changed"]
        return True, value, []
    except (OSError, ValueError) as exc:
        return True, None, [f"cannot load V17 active request: {exc}"]


def _active_content_errors(
    active: dict[str, Any], template_bytes: bytes
) -> list[str]:
    parent = active.get("plan_checkpoint_commit")
    if not isinstance(parent, str) or COMMIT_RE.fullmatch(parent) is None:
        return ["V17 active request direct parent is invalid"]
    try:
        active_bytes = (
            json.dumps(active, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        return ["V17 active request is not canonical JSON"]
    if template_bytes.count(b"__DIRECT_PARENT_COMMIT__") != 1:
        return ["V17 template parent placeholder count changed"]
    expected = template_bytes.replace(
        b"__DIRECT_PARENT_COMMIT__",
        parent.encode("ascii"),
    )
    return [] if active_bytes == expected else [
        "V17 active request differs from reviewed template"
    ]


def _validate_active_git(
    active: dict[str, Any], *, root: Path = ROOT
) -> list[str]:
    errors: list[str] = []
    relative = ACTIVE_REQUEST_PATH.relative_to(ROOT)
    template_relative = TEMPLATE_PATH.relative_to(ROOT)
    try:
        canonical_head = _canonical_branch_head(root)
        additions = _true_additions(root=root, path=relative)
        if len(additions) != 1:
            return ["V17 active request addition history is not unique"]
        activation = additions[0]
        if not _is_ancestor(root, activation, canonical_head):
            errors.append("V17 activation is not an ancestor of canonical head")
        parents = _commit_parents(root, activation)
        if len(parents) != 1:
            return ["V17 activation is not single-parent"]
        parent = parents[0]
        if not _is_ancestor(root, C17_DATA_PLANE_ANCHOR, parent):
            errors.append("V17 activation parent is not a C17 descendant")
        if active.get("plan_checkpoint_commit") != parent:
            errors.append("V17 active request does not bind direct parent")
        if _changed_paths(root, parent, activation) != {relative}:
            errors.append("V17 activation changes more than its request")
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
            errors.append("V17 request was not a unique addition")
        entry = _tree_entry(root, activation, relative).split()
        if len(entry) < 3 or entry[:2] != ["100644", "blob"]:
            errors.append("V17 request activation mode changed")
        template = _git_blob(root, parent, template_relative)
        if hashlib.sha256(template).hexdigest() != TEMPLATE_SHA256:
            errors.append("V17 activation parent template hash changed")
        elif template.count(b"__DIRECT_PARENT_COMMIT__") != 1:
            errors.append("V17 activation parent template placeholder changed")
        else:
            expected = template.replace(
                b"__DIRECT_PARENT_COMMIT__",
                parent.encode("ascii"),
            )
            activation_payload = _git_blob(root, activation, relative)
            head_payload = _git_blob(root, canonical_head, relative)
            if activation_payload != expected:
                errors.append("V17 activation request differs from parent template")
            if head_payload != activation_payload:
                errors.append("V17 request changed after activation")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V17 active request Git state: {exc}")
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
            "V17_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V17_CONSUMED_OR_INVALID"
    return "PREPARED_V17_NOT_TRIGGERED"


def validate_plan(
    *,
    verify_git_state: bool = True,
    active_request: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        workflow_bytes = _read_frozen_bytes(
            WORKFLOW_PATH,
            label="V17 workflow",
            required_mode=0o644,
        )
        template_bytes = _read_frozen_bytes(
            TEMPLATE_PATH,
            label="V17 template",
            required_mode=0o644,
        )
        template = _strict_json_bytes(template_bytes, "V17 template")
    except (OSError, ValueError) as exc:
        return [f"cannot load V17 dependency-cache plan: {exc}"]
    errors.extend(_static_hash_errors())
    if not isinstance(template, dict):
        errors.append("V17 template root changed")
    else:
        errors.extend(_template_errors(template))
    try:
        workflow = workflow_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"V17 workflow is not UTF-8: {exc}")
    else:
        errors.extend(_workflow_errors(workflow))

    supplied = active_request is not None
    if supplied:
        present, active, active_errors = True, active_request, []
    else:
        present, active, active_errors = _active_request()
    errors.extend(active_errors)
    if present and active is not None:
        errors.extend(_active_content_errors(active, template_bytes))
    elif present:
        errors.append("V17 active request is invalid")

    if verify_git_state:
        errors.extend(_validate_c17_data_plane_anchor())
        if not supplied:
            try:
                additions = _true_additions(
                    root=ROOT,
                    path=ACTIVE_REQUEST_PATH.relative_to(ROOT),
                )
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                errors.append(f"cannot verify V17 request history: {exc}")
            else:
                if present and active is not None:
                    errors.extend(_validate_active_git(active))
                elif not present and additions:
                    errors.append("inactive V17 request has prior addition history")
    return errors


def _activation_plan_state() -> str:
    base_errors = validate_plan(verify_git_state=False)
    base_errors.extend(_validate_c17_data_plane_anchor())
    present, active, active_errors = _active_request()
    try:
        additions = _true_additions(
            root=ROOT,
            path=ACTIVE_REQUEST_PATH.relative_to(ROOT),
        )
    except (OSError, ValueError, subprocess.CalledProcessError):
        return "INVALID"
    git_errors = list(active_errors)
    if present and active is not None:
        git_errors.extend(_validate_active_git(active))
    elif present:
        git_errors.append("V17 active request is invalid")
    if not present and additions:
        git_errors.append("inactive V17 request has prior history")
    return classify_plan_state(
        base_errors=base_errors,
        active_present=present,
        active_git_errors=git_errors,
        additions=additions,
    )


def evaluate_plan() -> tuple[list[str], str, list[str]]:
    errors = validate_plan()
    state = "INVALID" if errors else _activation_plan_state()
    return errors, state, []


def effective_plan_state() -> str:
    return evaluate_plan()[1]


def plan_state() -> str:
    return effective_plan_state()


def main() -> int:
    if len(sys.argv) != 1:
        print("FAIL: V17 verifier accepts no subcommands")
        return 1
    try:
        errors, state, _terminal_errors = evaluate_plan()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"admin_dependency_cache_export_plan_v17=PASS state={state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
