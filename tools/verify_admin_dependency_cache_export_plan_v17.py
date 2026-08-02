#!/usr/bin/env python3
"""Verify the append-only V17 Admin dependency-cache successor plan."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


LIVE_LEDGER_MODE = len(sys.argv) > 1 and sys.argv[1] == "live-ledger"
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v17.yml"
CI_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
TEMPLATE_PATH = ROOT / "deploy" / "production" / "plans" / "admin-dependency-cache-export-request-v17.json"
ACTIVE_REQUEST_PATH = ROOT / ".github" / "release-requests" / "admin-5335bda-dependency-cache-v17.json"
EXPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "export_admin_dependency_cache_v17.sh"
IMPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "import_admin_dependency_cache_v17.sh"
SOURCE_FIXTURE_PATH = ROOT / "tests" / "fixtures" / (
    "admin_dependency_cache_v17_frontend_lifecycle_and_"
    "localstate_projection.json"
)
TRANSIENT_VERIFIER_PATH = ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v17.py"
TRANSIENT_TEST_PATH = ROOT / "tests" / "test_admin_dependency_cache_transient_state_v17.py"
BUNDLE_VERIFIER_PATH = ROOT / "tools" / "verify_admin_dependency_cache_bundle_v17.py"
BUNDLE_TEST_PATH = ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v17.py"
PLAN_TEST_PATH = ROOT / "tests" / "test_admin_dependency_cache_export_plan_v17.py"
PLAN_VERIFIER_PATH = Path(__file__).resolve()
V16_TERMINAL_VERIFIER_PATH = ROOT / "tools" / "verify_admin_dependency_cache_v16_failure_evidence.py"
V16_TERMINAL_TEST_PATH = ROOT / "tests" / "test_admin_dependency_cache_v16_failure_evidence.py"
V16_EVIDENCE_PATH = ROOT / "deploy" / "production" / "evidence" / "admin-dependency-cache-v16-attempt1-failed-20260802.json"
PRODUCTION_GATE_PATH = ROOT / "tools" / "production_readiness_gate.py"
PRODUCTION_GATE_TEST_PATH = ROOT / "tests" / "test_production_readiness_gate.py"

WORKFLOW_SHA256 = "d14214a0f9cdfee9befb593b01c844d4233a43e20f2b036de70c7b51691c44ea"
TEMPLATE_SHA256 = "60f9b84550373665f1ce1652fdf218e7dc38233090faec71015274708256941f"
EXPORT_HELPER_SHA256 = "e2eb4b1466b245880fbb3bef7b34ae5f868ca8c1279def268038642d061b6eda"
IMPORT_HELPER_SHA256 = "b39b98d969052417d779a124c7c942fe89d4bcd50db0ad1bcde5121800b8185d"
SOURCE_FIXTURE_SHA256 = "5c020473f8f8e7cc189c3e936a8b41c76bdc2a9fde38fc79c7d11d31e9050b54"
BUNDLE_VERIFIER_SHA256 = "d25fc0ea403b12f87810dd12d9bcdd304ed6e73730873a980782d621293e9402"
BUNDLE_TEST_SHA256 = "6934d3e83053d0d5e91ce58625dc402667274b8811bb1ae486a364ced9c21902"
TRANSIENT_VERIFIER_SHA256 = "967e3545b6ca080574d33c137d77e89449dd6affc3a48473bbc460f8dfbf7e20"
TRANSIENT_TEST_SHA256 = "4fbb5e711e6ab44ce8d83d70880397db0d94c6a17cc050f696d7af1b8725c9fa"
PLAN_TEST_SHA256 = "e96a6bbbf8d55e3a2db7d6063d93dc0335a0202ba1a078e45285046a844378f8"
CI_WORKFLOW_SHA256 = "8a4e96f9539be4ee1a53688247706976084370047205831103322e330f1e6b04"
PRODUCTION_GATE_SHA256 = "975e90a6c5513da6d92afc52064f26a239244b9f7468fb66dd81964d8a1b3935"
PRODUCTION_GATE_TEST_SHA256 = "c3f203a50d0257edba735bfe2ad314a3129e5cfcfa5a60f727f3abb995ebc923"
V16_TERMINAL_VERIFIER_SHA256 = "1d6f53c9f812e2dfc93a4ec8c7c452e47585d1b0186777a25ea84d97ecc67d34"
V16_TERMINAL_TEST_SHA256 = "8834e00c732f84dbb9866c31b038d74b4f3bd35922b80ac95878aed3a2d9f9b4"
V16_EVIDENCE_SHA256 = "3b5881161d560b2a20da313a828faa04b7d0da374136eab3cc7f171a6f1f5d97"
V16_WORKFLOW_SHA256 = "8a86d032b03c3f9df624cb68c53509cb4729cb3687f3736d8697876a0474e170"
V16_TEMPLATE_SHA256 = "e49c8d94d347cd4afabcd2d116036b2a9dda1e008bb9f0759d01abf259e517d6"
V16_PLAN_VERIFIER_SHA256 = "491200312909caca12b243b408c07579c0dbede906d039ced2fe484f0c6ba27a"
V16_PLAN_TEST_SHA256 = "cd90fa85a48f2e31ca42acc883ec4d35f995ba880d8d6884e993e6f29ec77444"

RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
V15_ACTIVATION = "c61ba14ab77f98dbc63697dc2b3cbe26afdf9df1"
V15_TERMINAL_RECEIPT = "a94ee2b2feb81eafbcb523be2c95da4ee952cbc4"
V16_ACTIVATION = "fd1444d0a62549b3c353cbc1188e6ba25a77e96e"
V16_TERMINAL_CHECKPOINT = "4c2df3b19b4f5493adba78eed89c3a015d76972d"
V16_TERMINAL_RECEIPT = "751da973dd7136d792adfafa11e50f5e5e0bd689"
PREDECESSOR_COMMIT = V16_TERMINAL_RECEIPT
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BRANCH = "codex/quality-stabilization-real-chain"
V11_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v11.yml"
V12_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v12.yml"
V13_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v13.yml"
V14_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v14.yml"
V15_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v15.yml"
V16_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v16.yml"
V17_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v17.yml"

LEDGER_SCHEMA = "noteai.admin-dependency-cache-ledger.v17"
LEDGER_PAGE_SIZE = 100
LEDGER_PAGE_MAXIMUM = 10
LEDGER_ITEM_MAXIMUM = 1000
LEDGER_DEADLINE_SECONDS = 60
LEDGER_RESPONSE_MAXIMUM_BYTES = 16 * 1024 * 1024
LEGACY_LEDGER_SHA256 = "897016081024d8a45dcf1fccf828dd51887714e34ae0ae1947bc4db57c7c93e4"

INERT_CHECKPOINT_FILES = tuple(Path(value) for value in (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    ".github/workflows/admin-dependency-cache-export-v17.yml",
    ".github/workflows/ci.yml",
    "deploy/production/internal-deployment-readiness.json",
    "deploy/production/plans/admin-dependency-cache-export-request-v17.json",
    "scripts/ci/export_admin_dependency_cache_v17.sh",
    "scripts/ci/import_admin_dependency_cache_v17.sh",
    "tests/fixtures/admin_dependency_cache_v17_frontend_lifecycle_and_localstate_projection.json",
    "tests/test_admin_dependency_cache_bundle_verifier_v17.py",
    "tests/test_admin_dependency_cache_export_plan_v17.py",
    "tests/test_admin_dependency_cache_transient_state_v17.py",
    "tests/test_internal_deployment_readiness_gate.py",
    "tests/test_production_readiness_gate.py",
    "tools/production_readiness_gate.py",
    "tools/verify_admin_dependency_cache_bundle_v17.py",
    "tools/verify_admin_dependency_cache_export_plan_v17.py",
    "tools/verify_admin_dependency_cache_transient_state_v17.py",
))
INERT_RECEIPT_FILES = tuple(Path(value) for value in (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    "deploy/production/internal-deployment-readiness.json",
    "tests/test_internal_deployment_readiness_gate.py",
))
SAME_ANCHOR_FILES = tuple(Path(value) for value in (
    ".github/workflows/admin-dependency-cache-export-v17.yml",
    "deploy/production/plans/admin-dependency-cache-export-request-v17.json",
    "scripts/ci/export_admin_dependency_cache_v17.sh",
    "scripts/ci/import_admin_dependency_cache_v17.sh",
    "tests/fixtures/admin_dependency_cache_v17_frontend_lifecycle_and_localstate_projection.json",
    "tests/test_admin_dependency_cache_bundle_verifier_v17.py",
    "tests/test_admin_dependency_cache_export_plan_v17.py",
    "tests/test_admin_dependency_cache_transient_state_v17.py",
    "tools/verify_admin_dependency_cache_bundle_v17.py",
    "tools/verify_admin_dependency_cache_export_plan_v17.py",
    "tools/verify_admin_dependency_cache_transient_state_v17.py",
))
CHECKPOINT_IMMUTABLE_FILES = tuple(
    path for path in INERT_CHECKPOINT_FILES
    if path not in set(INERT_RECEIPT_FILES)
)
FROZEN_WORKTREE_FILES = (
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

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n").encode("utf-8")


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
    canonical = (json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
    ) + "\n").encode("utf-8")
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


def _commit_parents(root: Path, commit: str) -> list[str]:
    record = _git_at(
        root, "rev-list", "--parents", "-n", "1", commit
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
        if _tree_entry(root, commit, path) and all(
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


def _on_first_parent_chain(root: Path, commit: str, *, head: str) -> bool:
    return commit in _git_at(
        root, "rev-list", "--first-parent", head
    ).splitlines()


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
    errors: list[str] = []
    try:
        if _commit_parents(root, V16_TERMINAL_CHECKPOINT) != [V16_ACTIVATION]:
            errors.append("V16 terminal checkpoint parent changed")
        if _commit_parents(root, V16_TERMINAL_RECEIPT) != [V16_TERMINAL_CHECKPOINT]:
            errors.append("V16 terminal receipt parent changed")
        if not _on_first_parent_chain(
            root,
            V16_TERMINAL_RECEIPT,
            head=_canonical_branch_head(root),
        ):
            errors.append("V16 terminal receipt is not on first-parent chain")
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
                payload = terminal.load_strict()
                semantic_errors = terminal.verify(
                    payload,
                    verify_git_state=False,
                )
                if semantic_errors:
                    errors.append(
                        "V16 terminal semantic validation failed: "
                        + "; ".join(semantic_errors[:5])
                    )
                # The frozen V16 verifier intentionally treats CI and the
                # other V16 control files as immutable through its own
                # terminal receipt. A versioned successor must update CI, so
                # evaluate that historical contract at the fixed receipt,
                # never against the mutable V17 branch head. The module is a
                # private hash-pinned copy; restore its resolver immediately.
                original_canonical_head = terminal._canonical_head
                try:
                    terminal._canonical_head = lambda: V16_TERMINAL_RECEIPT
                    historical_git_errors = terminal.verify_frozen_git()
                finally:
                    terminal._canonical_head = original_canonical_head
                if historical_git_errors:
                    errors.append(
                        "V16 terminal historical Git validation failed: "
                        + "; ".join(historical_git_errors[:5])
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


def _authority_anchor(
    *,
    root: Path = ROOT,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    head = _canonical_branch_head(root)
    entries = {path: _tree_entry(root, head, path) for path in SAME_ANCHOR_FILES}
    present = [path for path, entry in entries.items() if entry]
    if not present:
        return None, []
    if len(present) != len(SAME_ANCHOR_FILES):
        return None, ["V17 frozen authorities are only partially present"]
    anchors: list[str] = []
    for path in SAME_ANCHOR_FILES:
        additions = _true_additions(root=root, path=path)
        if len(additions) != 1:
            errors.append(f"V17 frozen addition history is not unique: {path}")
        else:
            anchors.append(additions[0])
    if errors:
        return None, errors
    if len(set(anchors)) != 1:
        return None, ["V17 frozen authorities have different add anchors"]
    return anchors[0], []


def _validate_same_anchor(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        branch_head = _canonical_branch_head(root)
        anchor, anchor_errors = _authority_anchor(root=root)
        errors.extend(anchor_errors)
        if anchor is None:
            errors.append("V17 inert checkpoint is missing")
            return errors
        if _commit_parents(root, anchor) != [PREDECESSOR_COMMIT]:
            errors.append("V17 inert checkpoint parent changed")
        if _changed_paths(root, PREDECESSOR_COMMIT, anchor) != set(
            INERT_CHECKPOINT_FILES
        ):
            errors.append("V17 inert checkpoint is not the exact 18-file delta")
        if not _on_first_parent_chain(root, anchor, head=branch_head):
            errors.append("V17 inert checkpoint is not on first-parent chain")
        for relative in INERT_CHECKPOINT_FILES:
            entry = _tree_entry(root, anchor, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V17 inert checkpoint mode changed: {relative}")
        if _lineage_path_changes(
            root=root,
            anchor=anchor,
            paths=CHECKPOINT_IMMUTABLE_FILES,
            head=branch_head,
        ):
            errors.append("V17 immutable checkpoint authority changed")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V17 inert checkpoint: {exc}")
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
            head=branch_head,
        )
        if not changes:
            return None, []
        if len(changes) != 1:
            return None, ["V17 inert receipt history is not unique"]
        receipt = changes[0]
        if _commit_parents(root, receipt) != [anchor]:
            errors.append("V17 inert receipt is not the direct child of anchor")
        elif _changed_paths(root, anchor, receipt) != set(INERT_RECEIPT_FILES):
            errors.append("V17 inert receipt is not the exact 4-file delta")
        for relative in INERT_RECEIPT_FILES:
            entry = _tree_entry(root, receipt, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V17 inert receipt mode changed: {relative}")
        if not _on_first_parent_chain(root, receipt, head=branch_head):
            errors.append("V17 inert receipt is not on first-parent chain")
        return receipt, errors
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        return None, [f"cannot verify V17 inert receipt: {exc}"]


def _active_request(
    *,
    path: Path = ACTIVE_REQUEST_PATH,
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
            return ["V17 active request addition history is not unique"]
        activation = additions[0]
        if not _on_first_parent_chain(root, activation, head=branch_head):
            errors.append("V17 activation is not on first-parent chain")
        parents = _commit_parents(root, activation)
        if len(parents) != 1:
            return ["V17 activation is not single-parent"]
        parent = parents[0]
        receipt, receipt_errors = _validate_inert_receipt(root=root)
        errors.extend(receipt_errors)
        if receipt is None or parent != receipt:
            errors.append("V17 activation parent is not the exact receipt")
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
        if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
            errors.append("V17 request activation mode changed")
        template = _read_frozen_bytes(TEMPLATE_PATH, label="V17 template")
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
            errors.append("V17 activation request differs from template")
        if _lineage_path_changes(
            root=root,
            anchor=activation,
            paths=(relative,),
            head=branch_head,
        ):
            errors.append("V17 active request changed after activation")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V17 active request Git state: {exc}")
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
        return [] if branch_head == expected else [
            "V17 canonical branch HEAD is not the latest exact stage"
        ]
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        return [f"cannot verify V17 latest exact stage: {exc}"]


def _template_errors(template: dict[str, Any]) -> list[str]:
    """Validate the V17 request as a closed, one-shot authorization contract."""
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(
        set(template) == {
            "schema_version",
            "task",
            "release_commit",
            "plan_checkpoint_commit",
            "release_scope",
            "trigger_mode",
            "predecessor",
            "recovery_basis",
            "bundle_verifier_chain",
            "control_plane",
            "run_ledger_contract",
            "build_evidence_recovery",
            "provider_artifact_protocol",
            "recovery_run_authorized_after_predecessor_failure",
            "github_actions_maximum_run_count",
            "github_actions_maximum_runtime_minutes",
            "artifact_retention_days",
            "artifact_compressed_maximum_bytes",
            "artifact_input_maximum_bytes",
            "artifact_provider_maximum_bytes",
            "authenticated_artifact_download_maximum_count",
            "cross_provider_transfer_maximum_count",
            "artifact_visibility_assumption",
            "dependency_cache_export_authorized",
            "public_repository_artifact_authorized",
            "cross_provider_transfer_authorized",
            "registry_publication_authorized",
            "deployment_authorized",
            "database_authorized",
            "service_mutation_authorized",
            "public_traffic_authorized",
        },
        "V17 request root key set changed",
    )
    require(template.get("schema_version") == 17, "V17 schema changed")
    require(
        template.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "V17 task changed",
    )
    require(template.get("release_commit") == RELEASE_COMMIT, "V17 release changed")
    require(
        template.get("plan_checkpoint_commit") == "__DIRECT_PARENT_COMMIT__",
        "V17 parent placeholder changed",
    )
    require(
        template.get("trigger_mode") == "one_shot_added_request_v17",
        "V17 trigger mode changed",
    )
    require(
        template.get("predecessor")
        == {
            "state": "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
            "activation_commit": V16_ACTIVATION,
            "terminal_checkpoint_commit": V16_TERMINAL_CHECKPOINT,
            "terminal_receipt_commit": V16_TERMINAL_RECEIPT,
            "workflow_path": V16_WORKFLOW_PATH,
            "workflow_sha256": V16_WORKFLOW_SHA256,
            "template_sha256": V16_TEMPLATE_SHA256,
            "plan_verifier_sha256": V16_PLAN_VERIFIER_SHA256,
            "plan_test_sha256": V16_PLAN_TEST_SHA256,
            "failure_evidence_sha256": V16_EVIDENCE_SHA256,
            "active_request_path": (
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v16.json"
            ),
            "active_request_addition_count": 1,
            "workflow_run_count": 1,
            "run_id": 30739167701,
            "job_id": 91473336858,
            "run_attempt": 1,
            "conclusion": "failure",
            "artifact_count": 0,
            "receipt_created": True,
            "rerun_authorized": False,
            "supersession_reason": (
                "GIT_SOURCE_LIFECYCLE_ASSERTION_WITHOUT_RETAINED_TIMESTAMPS_"
                "AND_REMOTE_LOCALSTATE_RUNTIME_PAYLOAD_NOT_RETAINED"
            ),
        },
        "V17 V16 predecessor contract changed",
    )

    recovery = template.get("recovery_basis")
    require(isinstance(recovery, dict), "V17 recovery basis missing")
    if isinstance(recovery, dict):
        require(
            recovery.get("git_main_context_identity_source_projection_sha256")
            == SOURCE_FIXTURE_SHA256
            and recovery.get("canonical_git_context_query")
            == (
                "https://github.com/iamyusen1314/noteai.git?"
                "ref=5335bdaed933b1f999b5f819c047ec50c11821ae&"
                "checksum=5335bdaed933b1f999b5f819c047ec50c11821ae&"
                "submodules=false&mtime=commit&fetch-by-commit=true"
            )
            and recovery.get("canonical_git_source_identifier")
            == (
                "git://github.com/iamyusen1314/noteai.git#"
                "5335bdaed933b1f999b5f819c047ec50c11821ae"
            )
            and recovery.get("full_committed_git_context_supplied") is True
            and recovery.get("local_workspace_main_context_supplied") is False
            and recovery.get("dockerfile_transport") == "stdin"
            and recovery.get("buildx_send_git_query_as_input") is False
            and recovery.get("v17_export_helper_sha256") == EXPORT_HELPER_SHA256
            and recovery.get("v17_import_helper_sha256") == IMPORT_HELPER_SHA256
            and recovery.get("v17_bundle_verifier_sha256")
            == BUNDLE_VERIFIER_SHA256
            and recovery.get("v17_transient_state_verifier_sha256")
            == TRANSIENT_VERIFIER_SHA256
            and recovery.get("v17_transient_state_test_sha256")
            == TRANSIENT_TEST_SHA256
            and recovery.get("command_envelope_required_for_all_three_solves")
            is True
            and recovery.get("command_envelope_precision")
            == "UTC_RFC3339_NANOSECONDS"
            and recovery.get("git_source_lifecycle_policy")
            == (
                "COMMAND_START_LE_GIT_START_LE_GIT_COMPLETE_LE_"
                "PROVENANCE_FINISH_LE_COMMAND_COMPLETE"
            )
            and recovery.get("git_source_start_before_provenance_start_allowed")
            is True
            and recovery.get("network_exec_lifecycle_predicate_remains_frozen")
            is True
            and recovery.get("requirements_fileop_lifecycle_predicate_remains_frozen")
            is True
            and recovery.get("pre_assertion_git_lifecycle_diagnostic_required")
            is True
            and recovery.get("git_lifecycle_diagnostic_maximum_bytes") == 16384
            and recovery.get("git_lifecycle_diagnostic_maximum_intervals") == 32
            and recovery.get(
                "git_lifecycle_diagnostic_secret_free_projection_required"
            )
            is True
            and recovery.get("git_lifecycle_evidence_reread_hash_binding_required")
            is True
            and recovery.get(
                "transient_local_state_exact_canonical_query_required"
            )
            is True
            and recovery.get("transient_local_state_generic_remote_url_allowed")
            is False
            and recovery.get("transient_local_state_group_ref_allowed") is False
            and recovery.get("transient_local_state_dockerfile_path") == "-"
            and recovery.get("external_cache_removed_same_consumer_builder_required")
            is True
            and recovery.get("true_empty_cache_replay_claimed") is False
            and recovery.get("cache_config_vertex_digest_binding_authorized")
            is False
            and recovery.get("cache_config_structural_validation_required")
            is True
            and recovery.get(
                "fresh_consumer_same_source_copy_pip_digests_cached_required"
            )
            is True
            and recovery.get("dependency_cache_predicate_relaxed") is False,
            "V17 Git-context recovery contract changed",
        )

    chain = template.get("bundle_verifier_chain")
    require(
        isinstance(chain, dict)
        and chain.get("v13_sha256")
        == "c9a0f130879f8381ea94584a600b3ee388b91d380c079ec0b5efa145bff8b2d9",
        "V17 frozen V13 chain changed",
    )
    control = template.get("control_plane")
    require(
        isinstance(control, dict)
        and control.get("inert_checkpoint_exact_changed_path_count") == 18
        and control.get("inert_receipt_exact_changed_path_count") == 4
        and control.get("activation_exact_changed_path_count") == 1
        and control.get("checkpoint_nonreceipt_immutable_path_count") == 14
        and control.get("ci_workflow_sha256") == CI_WORKFLOW_SHA256
        and control.get("run_ledger_snapshot_count") == 2
        and control.get("v11_run_zero_required") is True
        and control.get("v12_unique_attempt1_failure_artifact0_required") is True
        and control.get("v13_run_zero_required") is True
        and control.get("v14_run_zero_required") is True
        and control.get("v15_unique_attempt1_failure_artifact0_required") is True
        and control.get("v15_terminal_receipt_commit") == V15_TERMINAL_RECEIPT
        and control.get("v16_unique_attempt1_failure_artifact0_required") is True
        and control.get("v16_terminal_receipt_commit") == V16_TERMINAL_RECEIPT
        and control.get("v17_current_attempt1_artifact0_required") is True,
        "V17 control-plane contract changed",
    )

    ledger = template.get("run_ledger_contract")
    legacy = ledger.get("legacy") if isinstance(ledger, dict) else None
    v11 = legacy[9] if isinstance(legacy, list) and len(legacy) == 15 else None
    v12 = legacy[10] if isinstance(legacy, list) and len(legacy) == 15 else None
    v13 = legacy[11] if isinstance(legacy, list) and len(legacy) == 15 else None
    v14 = legacy[12] if isinstance(legacy, list) and len(legacy) == 15 else None
    v15 = legacy[13] if isinstance(legacy, list) and len(legacy) == 15 else None
    v16 = legacy[14] if isinstance(legacy, list) and len(legacy) == 15 else None
    require(
        isinstance(ledger, dict)
        and ledger.get("schema") == LEDGER_SCHEMA
        and ledger.get("page_size") == LEDGER_PAGE_SIZE
        and ledger.get("page_maximum") == LEDGER_PAGE_MAXIMUM
        and ledger.get("item_maximum") == LEDGER_ITEM_MAXIMUM
        and ledger.get("deadline_seconds") == LEDGER_DEADLINE_SECONDS
        and isinstance(legacy, list)
        and len(legacy) == 15
        and hashlib.sha256(_canonical_json_bytes(legacy)).hexdigest()
        == LEGACY_LEDGER_SHA256
        and v11
        == {"version": "v11", "workflow_path": V11_WORKFLOW_PATH, "runs": []}
        and isinstance(v12, dict)
        and v12.get("version") == "v12"
        and v12.get("workflow_ref") == "325026609"
        and v12.get("workflow_path") == V12_WORKFLOW_PATH
        and isinstance(v12.get("runs"), list)
        and len(v12["runs"]) == 1
        and v12["runs"][0].get("id") == 30696298423
        and v13
        == {"version": "v13", "workflow_path": V13_WORKFLOW_PATH, "runs": []}
        and v14
        == {"version": "v14", "workflow_path": V14_WORKFLOW_PATH, "runs": []}
        and isinstance(v15, dict)
        and v15.get("version") == "v15"
        and v15.get("workflow_ref") == "admin-dependency-cache-export-v15.yml"
        and v15.get("workflow_path") == V15_WORKFLOW_PATH
        and isinstance(v15.get("runs"), list)
        and len(v15["runs"]) == 1
        and v15["runs"][0]
        == {
            "id": 30724578319,
            "head_sha": V15_ACTIVATION,
            "event": "push",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "failure",
            "job_ids": [91433793914],
            "artifact_count": 0,
        }
        and v16
        == {
            "version": "v16",
            "workflow_ref": "admin-dependency-cache-export-v16.yml",
            "workflow_path": V16_WORKFLOW_PATH,
            "runs": [
                {
                    "id": 30739167701,
                    "head_sha": V16_ACTIVATION,
                    "event": "push",
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "failure",
                    "job_ids": [91473336858],
                    "artifact_count": 0,
                }
            ],
        }
        and ledger.get("current")
        == {
            "version": "v17",
            "workflow_path": V17_WORKFLOW_PATH,
            "expected_run_count": 1,
            "event": "push",
            "run_attempt": 1,
            "artifact_count": 0,
        },
        "V17 run-ledger contract changed",
    )

    evidence = template.get("build_evidence_recovery")
    require(
        isinstance(evidence, dict)
        and evidence.get("frozen_v13_private_compatibility_projection_required")
        is True
        and evidence.get(
            "frozen_v13_high_level_delegate_executed_on_original_git_metadata"
        )
        is False
        and evidence.get("original_git_identity_validated_before_compatibility_projection")
        is True
        and evidence.get("identity_pair_classification_required")
        == "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED"
        and evidence.get("source_copy_pip_digest_equality_required") is True
        and evidence.get(
            "runtime_portability_proven_only_by_fresh_consumer_and_same_builder_replay"
        )
        is True
        and evidence.get(
            "requirements_copy_all_intervals_cached_required_on_consumer_and_replay"
        )
        is True
        and evidence.get("true_empty_cache_replay_claimed") is False
        and evidence.get("runtime_pip_cached_false_accepted") is False,
        "V17 build-evidence contract changed",
    )
    require(
        template.get("recovery_run_authorized_after_predecessor_failure") is True
        and template.get("github_actions_maximum_run_count") == 1
        and template.get("github_actions_maximum_runtime_minutes") == 120
        and template.get("artifact_retention_days") == 1
        and template.get("authenticated_artifact_download_maximum_count") == 1
        and template.get("cross_provider_transfer_maximum_count") == 1
        and template.get("dependency_cache_export_authorized") is True
        and template.get("public_repository_artifact_authorized") is True
        and template.get("cross_provider_transfer_authorized") is True
        and template.get("registry_publication_authorized") is False
        and template.get("deployment_authorized") is False
        and template.get("database_authorized") is False
        and template.get("service_mutation_authorized") is False
        and template.get("public_traffic_authorized") is False,
        "V17 authorization boundary changed",
    )
    return errors


def _workflow_errors(workflow: str) -> list[str]:
    """Validate the inert V17 controller before any external resource exists."""
    errors: list[str] = []
    header = f"""name: Admin dependency cache export V17

on:
  push:
    branches:
      - {BRANCH}
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v17.json
"""
    if not workflow.startswith(
        header
        + """
permissions:
  contents: read
  actions: read

concurrency:
"""
    ):
        errors.append("V17 workflow trigger or permission header changed")
    job_section = workflow.split("\njobs:\n", 1)
    job_keys = re.findall(
        r"^  ([A-Za-z0-9_-]+):[ \t]*$",
        job_section[1] if len(job_section) == 2 else "",
        flags=re.MULTILINE,
    )
    if job_keys != ["export-cache"]:
        errors.append("V17 workflow job inventory changed")
    required = (
        "group: admin-dependency-cache-export-v10",
        "cancel-in-progress: false",
        "runs-on: ubuntu-24.04",
        "timeout-minutes: 120",
        "NOTEAI_V16_ACTIVATION: " + V16_ACTIVATION,
        "NOTEAI_V16_TERMINAL_CHECKPOINT: " + V16_TERMINAL_CHECKPOINT,
        "NOTEAI_V16_TERMINAL_RECEIPT: " + V16_TERMINAL_RECEIPT,
        "NOTEAI_EXPORT_HELPER_PATH: scripts/ci/export_admin_dependency_cache_v17.sh",
        "NOTEAI_IMPORT_HELPER_PATH: scripts/ci/import_admin_dependency_cache_v17.sh",
        "NOTEAI_V17_CACHE_IDENTITY_SOURCE_PROJECTION_PATH: tests/fixtures/admin_dependency_cache_v17_frontend_lifecycle_and_localstate_projection.json",
        "NOTEAI_V13_BUNDLE_VERIFIER_PATH: tools/verify_admin_dependency_cache_bundle_v13.py",
        "NOTEAI_BUNDLE_VERIFIER_PATH: tools/verify_admin_dependency_cache_bundle_v17.py",
        "tools/verify_admin_dependency_cache_export_plan_v17.py",
        "Prove this is the unique V17 workflow run for the branch lifecycle",
        "Resolve exact V17 recovery request",
        "Snapshot V2 through V17 ledgers before resource creation",
        "Export V17 dependency-only BuildKit local cache",
        "Prove V17 import and external-cache-removed same-builder replay",
        "Remove V17 builders and all transient Docker state",
        "Snapshot V2 through V17 ledgers after cleanup and before upload",
        "Validate final V17 portable bundle after cleanup",
        "Upload one-day V17 public-repository dependency cache artifact",
        "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
        "inert_checkpoint_exact_changed_path_count == 18",
        "inert_receipt_exact_changed_path_count == 4",
        "activation_exact_changed_path_count == 1",
        "checkpoint_nonreceipt_immutable_path_count == 14",
        "(.run_ledger_contract.legacy | length) == 15",
        ".run_ledger_contract.legacy[14].version == \"v16\"",
        ".run_ledger_contract.legacy[14].runs[0].id == 30739167701",
        '"SAME_SOURCE_COPY_PIP_DIGESTS_CACHED"',
        ".external_cache_removed_same_consumer_builder_replay",
        ".true_empty_cache_replay_claimed == false",
        'ledger_contract_copy="${RUNNER_TEMP}/noteai-cache-v17-ledger-contract.json"',
        'cp "${NOTEAI_REQUEST_TEMPLATE}" "${ledger_contract_copy}"',
        "NOTEAI_V17_LEDGER_CONTRACT_PATH: ${{ steps.control.outputs.ledger_contract_copy }}",
        'BUILDKIT_NO_CLIENT_TOKEN: "1"',
        "NOTEAI_V13_BUNDLE_VERIFIER_PATH: ${{ steps.control.outputs.v13_verifier_copy }}",
    )
    for token in required:
        if token not in workflow:
            errors.append(f"V17 workflow contract missing: {token}")
    if workflow.count(
        "NOTEAI_V17_LEDGER_CONTRACT_PATH: "
        "${{ steps.control.outputs.ledger_contract_copy }}"
    ) != 2:
        errors.append("V17 workflow ledger handoff count changed")
    if workflow.count(
        'cp "${NOTEAI_REQUEST_TEMPLATE}" "${ledger_contract_copy}"'
    ) != 1:
        errors.append("V17 workflow ledger contract copy count changed")
    for forbidden in (
        "workflow_dispatch:",
        "pull_request:",
        "permissions: write-all",
        "contents: write",
        "actions: write",
        "cacheless",
        '"SAME_DIGEST_CACHED"',
        "true_empty_cache_replay_claimed == true",
        "python3 tools/verify_admin_dependency_cache_export_plan_v13.py",
        "python3 tools/verify_admin_dependency_cache_export_plan_v14.py",
        "python3 tools/verify_admin_dependency_cache_export_plan_v15.py",
    ):
        if forbidden in workflow:
            errors.append(f"V17 workflow forbidden token: {forbidden}")
    cleanup = workflow.find("Remove V17 builders and all transient Docker state")
    late = workflow.find(
        "Snapshot V2 through V17 ledgers after cleanup and before upload"
    )
    final = workflow.find("Validate final V17 portable bundle after cleanup")
    upload = workflow.find(
        "Upload one-day V17 public-repository dependency cache artifact"
    )
    if not 0 <= cleanup < late < final < upload:
        errors.append("V17 cleanup, late-ledger, final and upload ordering changed")
    return errors


def _validate_frozen_worktree() -> list[str]:
    errors: list[str] = []
    for path, expected in FROZEN_WORKTREE_FILES:
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
        fixture_bytes = _read_frozen_bytes(
            SOURCE_FIXTURE_PATH,
            label="V17 source fixture",
            required_mode=0o644,
        )
        template = _strict_json_bytes(template_bytes, "V17 template")
        fixture = _strict_json_bytes(fixture_bytes, "V17 source fixture")
    except (OSError, ValueError) as exc:
        return [f"cannot load V17 dependency-cache plan: {exc}"]
    if hashlib.sha256(workflow_bytes).hexdigest() != WORKFLOW_SHA256:
        errors.append("V17 workflow hash drift")
    if hashlib.sha256(template_bytes).hexdigest() != TEMPLATE_SHA256:
        errors.append("V17 template hash drift")
    if hashlib.sha256(fixture_bytes).hexdigest() != SOURCE_FIXTURE_SHA256:
        errors.append("V17 source fixture hash drift")
    if isinstance(template, dict):
        errors.extend(_template_errors(template))
    else:
        errors.append("V17 template root changed")
    try:
        workflow = workflow_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"V17 workflow is not UTF-8: {exc}")
    else:
        errors.extend(_workflow_errors(workflow))
    if not (
        isinstance(fixture, dict)
        and fixture.get("schema_version")
        == "noteai.admin-dependency-cache-frontend-lifecycle-localstate.v17"
        and fixture.get("classification")
        == "SOURCE_PROVEN_POLICY_NOT_V16_RUNTIME_EVIDENCE"
        and fixture.get("fixed_input", {}).get("release_commit")
        == RELEASE_COMMIT
        and fixture.get("fixed_input", {}).get(
            "canonical_git_context_query_sha256"
        )
        == "75a1f8caf4b0d95b0e632fb9f3876031d483688ed32d9dedaaa62cd58946d01c"
        and fixture.get("fixed_input", {}).get("dockerfile_transport") == "stdin"
        and fixture.get("fixed_input", {}).get("dockerfile_path_projection")
        == "-"
        and fixture.get("upstream", {}).get("buildx", {}).get("commit")
        == "a319e5b15052cf6557ceb666eb8ff6e32380b782"
        and fixture.get("upstream", {}).get("buildkit", {}).get("commit")
        == "e42e1bfd389af7203238cce77b1f7dad447285e9"
        and fixture.get("expected_local_state", {}).get("allowed_keys")
        == ["DockerfilePath", "LocalPath", "Target"]
        and fixture.get("expected_local_state", {}).get("group_ref_present")
        is False
        and fixture.get("expected_local_state", {}).get("local_path_policy")
        == "BYTE_EXACT_CANONICAL_QUERY_ONLY"
        and fixture.get("lifecycle_policy", {}).get(
            "git_start_before_provenance_start_allowed"
        )
        is True
        and fixture.get("lifecycle_policy", {}).get(
            "network_exec_predicate_remains_frozen"
        )
        is True
        and fixture.get("lifecycle_policy", {}).get(
            "requirements_fileop_predicate_remains_frozen"
        )
        is True
        and fixture.get("claims", {}).get(
            "source_review_proves_git_interval_runtime_order"
        )
        is False
        and fixture.get("claims", {}).get(
            "v17_policy_is_runtime_evidence"
        )
        is False
        and fixture.get("limitations", {}).get(
            "v17_external_run_has_occurred"
        )
        is False
    ):
        errors.append("V17 source fixture semantics changed")
    errors.extend(_validate_frozen_worktree())

    supplied = active_request is not None
    if supplied:
        present, active, active_errors = True, active_request, []
    else:
        present, active, active_errors = _active_request()
    errors.extend(active_errors)
    if present and active is not None:
        parent = str(active.get("plan_checkpoint_commit", ""))
        expected = template_bytes.replace(
            b"__DIRECT_PARENT_COMMIT__",
            parent.encode("ascii", errors="ignore"),
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
        if COMMIT_RE.fullmatch(parent) is None or active_bytes != expected:
            errors.append("V17 active request differs from reviewed template")
        if verify_git_state and not supplied:
            errors.extend(_validate_active_git(active))
    elif present:
        errors.append("V17 active request is invalid")

    if verify_git_state:
        errors.extend(_validate_v16_predecessor())
        errors.extend(_validate_same_anchor())
        _receipt, receipt_errors = _validate_inert_receipt()
        errors.extend(receipt_errors)
        errors.extend(_validate_latest_stage_head(active_present=present))
        if not present:
            try:
                if _true_additions(
                    root=ROOT,
                    path=ACTIVE_REQUEST_PATH.relative_to(ROOT),
                ):
                    errors.append("inactive V17 request has prior addition history")
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                errors.append(f"cannot verify inactive V17 request history: {exc}")
    return errors


def _activation_plan_state() -> str:
    base_errors = validate_plan(verify_git_state=False)
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
    if not present and additions:
        git_errors.append("inactive V17 request has prior history")
    base_errors.extend(_validate_v16_predecessor())
    base_errors.extend(_validate_same_anchor())
    _receipt, receipt_errors = _validate_inert_receipt()
    base_errors.extend(receipt_errors)
    base_errors.extend(_validate_latest_stage_head(active_present=present))
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


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"{label} is not an integer")
    return value


def _expected_ledger_contract() -> dict[str, Any]:
    configured = os.environ.get("NOTEAI_V17_LEDGER_CONTRACT_PATH")
    path = Path(configured) if configured else TEMPLATE_PATH
    payload = _read_frozen_bytes(
        path,
        label="V17 ledger contract template",
        required_mode=0o400 if configured else 0o644,
    )
    _require(
        hashlib.sha256(payload).hexdigest() == TEMPLATE_SHA256,
        "V17 ledger contract template hash drift",
    )
    template = _strict_json_bytes(payload, "V17 ledger contract template")
    _require(isinstance(template, dict), "V17 ledger template root changed")
    contract = template.get("run_ledger_contract")
    _require(isinstance(contract, dict), "V17 ledger contract missing")
    legacy = contract.get("legacy")
    _require(isinstance(legacy, list) and len(legacy) == 15, "V17 legacy ledger changed")
    _require(
        hashlib.sha256(_canonical_json_bytes(legacy)).hexdigest()
        == LEGACY_LEDGER_SHA256,
        "V17 legacy ledger history changed",
    )
    v11 = legacy[9]
    v12 = legacy[10]
    v13 = legacy[11]
    v14 = legacy[12]
    v15 = legacy[13]
    v16 = legacy[14]
    _require(isinstance(v12, dict), "V12 ledger entry changed")
    v12_runs = v12.get("runs")
    _require(
        contract.get("schema") == LEDGER_SCHEMA
        and contract.get("page_size") == LEDGER_PAGE_SIZE
        and contract.get("page_maximum") == LEDGER_PAGE_MAXIMUM
        and contract.get("item_maximum") == LEDGER_ITEM_MAXIMUM
        and contract.get("deadline_seconds") == LEDGER_DEADLINE_SECONDS
        and v11
        == {
            "version": "v11",
            "workflow_path": V11_WORKFLOW_PATH,
            "runs": [],
        }
        and v12.get("version") == "v12"
        and v12.get("workflow_ref") == "325026609"
        and v12.get("workflow_path")
        == V12_WORKFLOW_PATH
        and isinstance(v12_runs, list)
        and len(v12_runs) == 1
        and isinstance(v12_runs[0], dict)
        and v12_runs[0].get("id")
        == 30696298423
        and v13
        == {
            "version": "v13",
            "workflow_path": V13_WORKFLOW_PATH,
            "runs": [],
        }
        and v14
        == {
            "version": "v14",
            "workflow_path": V14_WORKFLOW_PATH,
            "runs": [],
        }
        and v15
        == {
            "version": "v15",
            "workflow_ref": "admin-dependency-cache-export-v15.yml",
            "workflow_path": V15_WORKFLOW_PATH,
            "runs": [
                {
                    "id": 30724578319,
                    "head_sha": V15_ACTIVATION,
                    "event": "push",
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "failure",
                    "job_ids": [91433793914],
                    "artifact_count": 0,
                }
            ],
        }
        and v16
        == {
            "version": "v16",
            "workflow_ref": "admin-dependency-cache-export-v16.yml",
            "workflow_path": V16_WORKFLOW_PATH,
            "runs": [
                {
                    "id": 30739167701,
                    "head_sha": V16_ACTIVATION,
                    "event": "push",
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "failure",
                    "job_ids": [91473336858],
                    "artifact_count": 0,
                }
            ],
        }
        and contract.get("current")
        == {
            "version": "v17",
            "workflow_path": V17_WORKFLOW_PATH,
            "expected_run_count": 1,
            "event": "push",
            "run_attempt": 1,
            "artifact_count": 0,
        },
        "V17 ledger contract changed",
    )
    return contract


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
    *,
    current_run_id: int,
) -> list[dict[str, Any]]:
    projections: dict[str, dict[str, Any]] = {}
    for expected_version in contract["legacy"]:
        if expected_version.get("version") in {"v11", "v13", "v14"}:
            continue
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
        projection = {
            "version": expected_version["version"],
            "workflow_ref": workflow_ref,
            "runs": projected_runs,
        }
        if "workflow_path" in expected_version:
            projection["workflow_path"] = expected_version["workflow_path"]
        projections[expected_version["version"]] = projection
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
    v12_run_ids = {
        run["id"]
        for run in repository_projections[1]
        if run["path"] == V12_WORKFLOW_PATH
    }
    _require(
        v12_run_ids == {30696298423},
        "V12 workflow repository inventory changed",
    )
    v13_runs = [
        run
        for run in repository_projections[1]
        if run["path"] == V13_WORKFLOW_PATH
    ]
    _require(v13_runs == [], "V13 workflow run inventory is not zero")
    v14_runs = [
        run
        for run in repository_projections[1]
        if run["path"] == V14_WORKFLOW_PATH
    ]
    _require(v14_runs == [], "V14 workflow run inventory is not zero")
    v15_run_ids = {
        run["id"]
        for run in repository_projections[1]
        if run["path"] == V15_WORKFLOW_PATH
    }
    _require(
        v15_run_ids == {30724578319},
        "V15 workflow repository inventory changed",
    )
    v16_run_ids = {
        run["id"]
        for run in repository_projections[1]
        if run["path"] == V16_WORKFLOW_PATH
    }
    _require(
        v16_run_ids == {30739167701},
        "V16 workflow repository inventory changed",
    )
    v17_run_ids = {
        run["id"]
        for run in repository_projections[1]
        if run["path"] == V17_WORKFLOW_PATH
    }
    _require(
        v17_run_ids == {current_run_id},
        "V17 workflow repository inventory changed",
    )
    result: list[dict[str, Any]] = []
    for expected_version in contract["legacy"]:
        if expected_version["version"] in {"v11", "v13", "v14"}:
            version = expected_version["version"]
            workflow_path = {
                "v11": V11_WORKFLOW_PATH,
                "v13": V13_WORKFLOW_PATH,
                "v14": V14_WORKFLOW_PATH,
            }[version]
            result.append(
                {
                    "version": version,
                    "workflow_path": workflow_path,
                    "runs": [],
                }
            )
        else:
            result.append(projections[expected_version["version"]])
    return result


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
        current.get("path") == V17_WORKFLOW_PATH,
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
    _require(workflow_id > 0, "current workflow id changed")
    runs = _paginate_api(
        fetch,
        f"/actions/workflows/{workflow_id}/runs",
        "workflow_runs",
    )
    _require(len(runs) == 1, "V17 workflow run count changed")
    run = runs[0]
    _require(_strict_int(run.get("id"), "current run id") == run_id, "current run id changed")
    _require(
        _strict_int(run.get("workflow_id"), "current run workflow id")
        == workflow_id,
        "current run workflow id changed",
    )
    _require(run.get("head_sha") == head_sha, "current run head changed")
    _require(run.get("head_branch") == head_branch, "current run branch changed")
    _require(run.get("path") == V17_WORKFLOW_PATH, "current workflow path changed")
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
        "path": V17_WORKFLOW_PATH,
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
    _require(current.get("path") == V17_WORKFLOW_PATH, "pre-resource path changed")
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
    legacy = _collect_legacy_ledger(
        fetch,
        contract,
        current_run_id=run_id,
    )
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
                "User-Agent": "noteai-v17-ledger",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        last_error: BaseException | None = None
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            _require(remaining > 0, "V17 ledger deadline exceeded")
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
                _require(remaining > 0, "V17 ledger deadline exceeded")
                time.sleep(min(1.0, remaining))
        raise RuntimeError("GitHub ledger request failed") from last_error

    return fetch


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = _read_frozen_bytes(
        path,
        label="V17 ledger snapshot",
        required_mode=0o600,
    )
    value = json.loads(
        payload,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON token: {token}")
        ),
    )
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
        observed = os.fstat(descriptor)
        _require(
            stat.S_ISREG(observed.st_mode)
            and observed.st_nlink == 1
            and stat.S_IMODE(observed.st_mode) == 0o600
            and observed.st_size == len(payload),
            "ledger snapshot file contract changed",
        )
    finally:
        os.close(descriptor)


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
    print(f"admin_dependency_cache_v17_live_ledger=PASS phase={phase}")
    return 0


def main() -> int:
    try:
        if len(sys.argv) > 1:
            _require(sys.argv[1] == "live-ledger", "V17 command changed")
            return _live_ledger_main(sys.argv[2:])
        errors, state, _terminal_errors = evaluate_plan()
        if errors:
            for error in errors:
                print(f"FAIL: {error}")
            return 1
        print(
            "admin_dependency_cache_export_plan_v17=PASS "
            f"state={state}"
        )
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
