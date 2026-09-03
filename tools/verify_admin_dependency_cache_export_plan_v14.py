#!/usr/bin/env python3
"""Verify the append-only V14 Admin dependency-cache successor plan."""

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
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v14.yml"
CI_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
TEMPLATE_PATH = ROOT / "deploy" / "production" / "plans" / "admin-dependency-cache-export-request-v14.json"
ACTIVE_REQUEST_PATH = ROOT / ".github" / "release-requests" / "admin-5335bda-dependency-cache-v14.json"
IMPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "import_admin_dependency_cache_v13.sh"
SOURCE_FIXTURE_PATH = ROOT / "tests" / "fixtures" / (
    "admin_dependency_cache_buildkit_v0.31.2_"
    "cache_record_identity_domains_projection.json"
)
BUNDLE_VERIFIER_PATH = ROOT / "tools" / "verify_admin_dependency_cache_bundle_v13.py"
BUNDLE_TEST_PATH = ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v13.py"
PLAN_TEST_PATH = ROOT / "tests" / "test_admin_dependency_cache_export_plan_v14.py"
PLAN_VERIFIER_PATH = Path(__file__).resolve()
V13_PLAN_VERIFIER_PATH = ROOT / "tools" / "verify_admin_dependency_cache_export_plan_v13.py"
V12_TERMINAL_VERIFIER_PATH = ROOT / "tools" / "verify_admin_dependency_cache_v12_failure_evidence.py"
V12_EVIDENCE_PATH = ROOT / "deploy" / "production" / "evidence" / (
    "admin-dependency-cache-v12-attempt1-failed-20260801.json"
)

WORKFLOW_SHA256 = "98850e28f74d5b4d4bafacffed07d118cba3378c81a0c93457cb46dc83ac7db1"
TEMPLATE_SHA256 = "9fd2f7d07eb7d9495ba4b27b2b71e6df650d8ef6dd6f599fb8a0da2edeadb4ca"
V13_WORKFLOW_SHA256 = "d0abfed05cd57ab297d3864d13147a46d88f8241887040e64695ec797d01bc87"
V13_TEMPLATE_SHA256 = "e86dd938c98048e0d647c2803abb16e2d9bbd3a041fdf011fd83c860cc098edd"
V13_PLAN_VERIFIER_SHA256 = "d2b476db591a347a56e4828e3af3981e609c5f8978a16f8b882e5ac66173f5a7"
IMPORT_HELPER_SHA256 = "ab824fa6ec1ed54b21c748736a81b80a418f179a82b701131a8a01c981d061b7"
SOURCE_FIXTURE_SHA256 = "176fd702836a46ab30584aa3b0d0072c6c2a31ea8eda6c306d3d7cdfd87d6b66"
BUNDLE_VERIFIER_SHA256 = "c9a0f130879f8381ea94584a600b3ee388b91d380c079ec0b5efa145bff8b2d9"
BUNDLE_TEST_SHA256 = "c2b7df625850556c60dc38409226edff41861765dfa4623439274e9a73e2313b"
PLAN_TEST_SHA256 = "f908bf33fda2e6c49e95fda43589a9f3376aec9681a038245b12ac55d9055a7d"
CI_WORKFLOW_SHA256 = "cf21455c03887657ecafb0c4a224144bf4fbe63c3a5de204ffdb31fd0480201e"
V12_TERMINAL_VERIFIER_SHA256 = "5295308cf72cf5348785c2abb6f261966b2cf7b3c8d797f092162bef1b2cea45"
V12_EVIDENCE_SHA256 = "87d262b0bf74e0ddeaf7a5d655a6bb16d9d974acd78daf92103bf5f284d76da7"

RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
V12_CORRECTION_RECEIPT = "ae7ce751d842b2880cdb2d31213a983bcb1f7484"
V13_INERT_CHECKPOINT = "4df6a77e39f2488b852414bb0649babbb37eb98a"
V13_FAILURE_RECEIPT = "585edfcb2789b112bbf559bf1d6d75e1843dd54c"
PREDECESSOR_COMMIT = V13_FAILURE_RECEIPT
V12_TERMINAL_CHECKPOINT = "efef71395fce4319ef11c8065b45db482ba12669"
V12_TERMINAL_RECEIPT = "37c3b3fdc24ad90ff6135a7f1e254f92062470b3"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BRANCH = "codex/quality-stabilization-real-chain"
V11_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v11.yml"
V12_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v12.yml"
V13_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v13.yml"
V14_WORKFLOW_PATH = ".github/workflows/admin-dependency-cache-export-v14.yml"

LEDGER_SCHEMA = "noteai.admin-dependency-cache-ledger.v14"
LEDGER_PAGE_SIZE = 100
LEDGER_PAGE_MAXIMUM = 10
LEDGER_ITEM_MAXIMUM = 1000
LEDGER_DEADLINE_SECONDS = 60
LEDGER_RESPONSE_MAXIMUM_BYTES = 16 * 1024 * 1024
LEGACY_LEDGER_SHA256 = "168c17c5f14e1dbf69fe4b4e1ae84fb7335b00eef06bb55ebd23657699537ea2"

INERT_CHECKPOINT_FILES = tuple(Path(value) for value in (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    ".github/workflows/admin-dependency-cache-export-v14.yml",
    ".github/workflows/ci.yml",
    "deploy/production/internal-deployment-readiness.json",
    "deploy/production/plans/admin-dependency-cache-export-request-v14.json",
    "tests/test_admin_dependency_cache_export_plan_v14.py",
    "tests/test_internal_deployment_readiness_gate.py",
    "tests/test_production_readiness_gate.py",
    "tools/production_readiness_gate.py",
    "tools/verify_admin_dependency_cache_export_plan_v14.py",
))
INERT_RECEIPT_FILES = tuple(Path(value) for value in (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    "deploy/production/internal-deployment-readiness.json",
    "tests/test_internal_deployment_readiness_gate.py",
))
SAME_ANCHOR_FILES = tuple(Path(value) for value in (
    ".github/workflows/admin-dependency-cache-export-v14.yml",
    "deploy/production/plans/admin-dependency-cache-export-request-v14.json",
    "tests/test_admin_dependency_cache_export_plan_v14.py",
    "tools/verify_admin_dependency_cache_export_plan_v14.py",
))
CHECKPOINT_IMMUTABLE_FILES = tuple(
    path for path in INERT_CHECKPOINT_FILES
    if path not in set(INERT_RECEIPT_FILES)
)
FROZEN_WORKTREE_FILES = (
    (WORKFLOW_PATH, WORKFLOW_SHA256),
    (CI_WORKFLOW_PATH, CI_WORKFLOW_SHA256),
    (TEMPLATE_PATH, TEMPLATE_SHA256),
    (IMPORT_HELPER_PATH, IMPORT_HELPER_SHA256),
    (SOURCE_FIXTURE_PATH, SOURCE_FIXTURE_SHA256),
    (BUNDLE_VERIFIER_PATH, BUNDLE_VERIFIER_SHA256),
    (BUNDLE_TEST_PATH, BUNDLE_TEST_SHA256),
    (PLAN_TEST_PATH, PLAN_TEST_SHA256),
    (V12_TERMINAL_VERIFIER_PATH, V12_TERMINAL_VERIFIER_SHA256),
    (V12_EVIDENCE_PATH, V12_EVIDENCE_SHA256),
)

V13_CORE_AUTHORITIES = {
    Path(".github/workflows/admin-dependency-cache-export-v13.yml"): V13_WORKFLOW_SHA256,
    Path("deploy/production/plans/admin-dependency-cache-export-request-v13.json"): V13_TEMPLATE_SHA256,
    Path("scripts/ci/import_admin_dependency_cache_v13.sh"): IMPORT_HELPER_SHA256,
    Path(
        "tests/fixtures/"
        "admin_dependency_cache_buildkit_v0.31.2_cache_record_identity_domains_projection.json"
    ): SOURCE_FIXTURE_SHA256,
    Path("tests/test_admin_dependency_cache_bundle_verifier_v13.py"): BUNDLE_TEST_SHA256,
    Path("tests/test_admin_dependency_cache_export_plan_v13.py"): (
        "c01a6b6b4b7fd63397b335514a44c9eb87cc1175194b51f766836bf7dae34b44"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v13.py"): BUNDLE_VERIFIER_SHA256,
    Path("tools/verify_admin_dependency_cache_export_plan_v13.py"): (
        V13_PLAN_VERIFIER_SHA256
    ),
}

V13_CHECKPOINT_FILES = tuple(Path(value) for value in (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    ".github/workflows/admin-dependency-cache-export-v13.yml",
    "deploy/production/internal-deployment-readiness.json",
    "deploy/production/plans/admin-dependency-cache-export-request-v13.json",
    "scripts/ci/import_admin_dependency_cache_v13.sh",
    "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_cache_record_identity_domains_projection.json",
    "tests/test_admin_dependency_cache_bundle_verifier_v13.py",
    "tests/test_admin_dependency_cache_export_plan_v13.py",
    "tests/test_internal_deployment_readiness_gate.py",
    "tests/test_production_readiness_gate.py",
    "tools/production_readiness_gate.py",
    "tools/verify_admin_dependency_cache_bundle_v13.py",
    "tools/verify_admin_dependency_cache_export_plan_v13.py",
))


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


def _parse_json_bytes(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(
        _read_frozen_bytes(path, label=path.as_posix())
    ).hexdigest()


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


def _load_v12_terminal_verifier():
    source = _read_frozen_bytes(
        V12_TERMINAL_VERIFIER_PATH,
        label="V12 terminal verifier",
    )
    if hashlib.sha256(source).hexdigest() != V12_TERMINAL_VERIFIER_SHA256:
        raise ValueError("V12 terminal verifier hash drift")
    module_name = "_noteai_v12_terminal_for_v14"
    module = types.ModuleType(module_name)
    module.__file__ = str(V12_TERMINAL_VERIFIER_PATH)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(
            compile(source, str(V12_TERMINAL_VERIFIER_PATH), "exec"),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _load_v13_plan_verifier():
    source = _read_frozen_bytes(
        V13_PLAN_VERIFIER_PATH,
        label="V13 plan verifier",
    )
    if hashlib.sha256(source).hexdigest() != V13_PLAN_VERIFIER_SHA256:
        raise ValueError("V13 plan verifier hash drift")
    module_name = "_noteai_v13_plan_for_v14"
    module = types.ModuleType(module_name)
    module.__file__ = str(V13_PLAN_VERIFIER_PATH)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(
            compile(source, str(V13_PLAN_VERIFIER_PATH), "exec"),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _validate_v12_terminal_predecessor() -> list[str]:
    errors: list[str] = []
    try:
        evidence_bytes = _read_frozen_bytes(
            V12_EVIDENCE_PATH,
            label="V12 terminal evidence",
        )
        if hashlib.sha256(evidence_bytes).hexdigest() != V12_EVIDENCE_SHA256:
            return ["V12 terminal evidence hash drift"]
        payload = _parse_json_bytes(evidence_bytes, "V12 terminal evidence")
        if not isinstance(payload, dict):
            return ["V12 terminal evidence root changed"]
        verifier = _load_v12_terminal_verifier()
        errors.extend(verifier.verify(payload))
        checkpoint = verifier.terminal_checkpoint()
        receipt = verifier.terminal_receipt(checkpoint)
        if checkpoint != V12_TERMINAL_CHECKPOINT:
            errors.append("V12 terminal checkpoint changed")
        if receipt != V12_TERMINAL_RECEIPT:
            errors.append("V12 terminal receipt changed")
        if _git_at(ROOT, "rev-parse", f"{V12_CORRECTION_RECEIPT}^") != (
            "81730a511acb553c9a1e29af834924f71650dc9a"
        ):
            errors.append("V12 correction receipt parent changed")
        if _git_at(ROOT, "rev-parse", V12_CORRECTION_RECEIPT) != V12_CORRECTION_RECEIPT:
            errors.append("V12 correction receipt missing")
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        errors.append(f"cannot verify V12 terminal predecessor: {exc}")
    return errors


def _validate_v13_superseded_predecessor(*, root: Path = ROOT) -> list[str]:
    errors = _validate_v12_terminal_predecessor()
    try:
        if root.resolve() == ROOT.resolve():
            v13 = _load_v13_plan_verifier()
            v13_errors = v13.validate_plan(verify_git_state=False)
            if v13_errors:
                errors.append(
                    "V13 frozen semantic validation failed: "
                    + "; ".join(v13_errors[:5])
                )
        if _commit_parents(root, V13_INERT_CHECKPOINT) != [V12_CORRECTION_RECEIPT]:
            errors.append("V13 inert checkpoint parent changed")
        if _changed_paths(
            root,
            V12_CORRECTION_RECEIPT,
            V13_INERT_CHECKPOINT,
        ) != set(V13_CHECKPOINT_FILES):
            errors.append("V13 inert checkpoint is not the exact 14-file delta")
        for relative in V13_CHECKPOINT_FILES:
            entry = _tree_entry(root, V13_INERT_CHECKPOINT, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V13 inert checkpoint mode changed: {relative}")
        if _commit_parents(root, V13_FAILURE_RECEIPT) != [V13_INERT_CHECKPOINT]:
            errors.append("V13 failure receipt parent changed")
        if _changed_paths(
            root,
            V13_INERT_CHECKPOINT,
            V13_FAILURE_RECEIPT,
        ) != set(INERT_RECEIPT_FILES):
            errors.append("V13 failure receipt is not the exact 4-file delta")
        for relative in INERT_RECEIPT_FILES:
            entry = _tree_entry(root, V13_FAILURE_RECEIPT, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V13 failure receipt mode changed: {relative}")
        for relative, expected in V13_CORE_AUTHORITIES.items():
            payload = _read_frozen_bytes(root / relative, label=f"V13 authority {relative}")
            if hashlib.sha256(payload).hexdigest() != expected:
                errors.append(f"V13 superseded authority hash drift: {relative}")
            additions = _true_additions(root=root, path=relative)
            if additions != [V13_INERT_CHECKPOINT]:
                errors.append(f"V13 authority addition history changed: {relative}")
            if _lineage_path_changes(
                root=root,
                anchor=V13_INERT_CHECKPOINT,
                paths=(relative,),
                head=_canonical_branch_head(root),
            ):
                errors.append(f"V13 authority changed after checkpoint: {relative}")
        if _true_additions(
            root=root,
            path=Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v13.json"
            ),
        ):
            errors.append("V13 request history is not zero")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V13 superseded predecessor: {exc}")
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
        return None, ["V14 frozen authorities are only partially present"]
    anchors: list[str] = []
    for path in SAME_ANCHOR_FILES:
        additions = _true_additions(root=root, path=path)
        if len(additions) != 1:
            errors.append(f"V14 frozen addition history is not unique: {path}")
        else:
            anchors.append(additions[0])
    if errors:
        return None, errors
    if len(set(anchors)) != 1:
        return None, ["V14 frozen authorities have different add anchors"]
    return anchors[0], []


def _validate_same_anchor(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        branch_head = _canonical_branch_head(root)
        anchor, anchor_errors = _authority_anchor(root=root)
        errors.extend(anchor_errors)
        if anchor is None:
            errors.append("V14 inert checkpoint is missing")
            return errors
        if _commit_parents(root, anchor) != [PREDECESSOR_COMMIT]:
            errors.append("V14 inert checkpoint parent changed")
        if _changed_paths(root, PREDECESSOR_COMMIT, anchor) != set(
            INERT_CHECKPOINT_FILES
        ):
            errors.append("V14 inert checkpoint is not the exact 11-file delta")
        if not _on_first_parent_chain(root, anchor, head=branch_head):
            errors.append("V14 inert checkpoint is not on first-parent chain")
        for relative in INERT_CHECKPOINT_FILES:
            entry = _tree_entry(root, anchor, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V14 inert checkpoint mode changed: {relative}")
        if _lineage_path_changes(
            root=root,
            anchor=anchor,
            paths=CHECKPOINT_IMMUTABLE_FILES,
            head=branch_head,
        ):
            errors.append("V14 immutable checkpoint authority changed")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V14 inert checkpoint: {exc}")
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
            return None, ["V14 inert receipt history is not unique"]
        receipt = changes[0]
        if _commit_parents(root, receipt) != [anchor]:
            errors.append("V14 inert receipt is not the direct child of anchor")
        elif _changed_paths(root, anchor, receipt) != set(INERT_RECEIPT_FILES):
            errors.append("V14 inert receipt is not the exact 4-file delta")
        for relative in INERT_RECEIPT_FILES:
            entry = _tree_entry(root, receipt, relative).split()
            if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
                errors.append(f"V14 inert receipt mode changed: {relative}")
        if not _on_first_parent_chain(root, receipt, head=branch_head):
            errors.append("V14 inert receipt is not on first-parent chain")
        return receipt, errors
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        return None, [f"cannot verify V14 inert receipt: {exc}"]


def _active_request(
    *,
    path: Path = ACTIVE_REQUEST_PATH,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    try:
        if not path.exists() and not path.is_symlink():
            return False, None, []
        payload = _read_frozen_bytes(
            path,
            label="V14 active request",
            required_mode=0o644,
        )
        value = _strict_json_bytes(payload, "V14 active request")
        if not isinstance(value, dict):
            return True, None, ["V14 active request root changed"]
        return True, value, []
    except (OSError, ValueError) as exc:
        return True, None, [f"cannot load V14 active request: {exc}"]


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
            return ["V14 active request addition history is not unique"]
        activation = additions[0]
        if not _on_first_parent_chain(root, activation, head=branch_head):
            errors.append("V14 activation is not on first-parent chain")
        parents = _commit_parents(root, activation)
        if len(parents) != 1:
            return ["V14 activation is not single-parent"]
        parent = parents[0]
        receipt, receipt_errors = _validate_inert_receipt(root=root)
        errors.extend(receipt_errors)
        if receipt is None or parent != receipt:
            errors.append("V14 activation parent is not the exact receipt")
        if active.get("plan_checkpoint_commit") != parent:
            errors.append("V14 active request does not bind direct parent")
        if _changed_paths(root, parent, activation) != {relative}:
            errors.append("V14 activation changes more than its request")
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
            errors.append("V14 request was not a unique addition")
        entry = _tree_entry(root, activation, relative).split()
        if len(entry) < 3 or entry[0:2] != ["100644", "blob"]:
            errors.append("V14 request activation mode changed")
        template = _read_frozen_bytes(TEMPLATE_PATH, label="V14 template")
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
            errors.append("V14 activation request differs from template")
        if _lineage_path_changes(
            root=root,
            anchor=activation,
            paths=(relative,),
            head=branch_head,
        ):
            errors.append("V14 active request changed after activation")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V14 active request Git state: {exc}")
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
            "V14 canonical branch HEAD is not the latest exact stage"
        ]
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        return [f"cannot verify V14 latest exact stage: {exc}"]


def _template_errors(template: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(template.get("schema_version") == 14, "V14 schema changed")
    require(template.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001", "V14 task changed")
    require(template.get("release_commit") == RELEASE_COMMIT, "V14 release changed")
    require(template.get("plan_checkpoint_commit") == "__DIRECT_PARENT_COMMIT__", "V14 parent placeholder changed")
    require(template.get("trigger_mode") == "one_shot_added_request_v14", "V14 trigger mode changed")
    predecessor = template.get("predecessor")
    require(isinstance(predecessor, dict), "V14 predecessor missing")
    if isinstance(predecessor, dict):
        require(
            predecessor.get("state")
            == "V13_INERT_CHECKPOINT_CI_HERMETICITY_FAILED_RECEIPT_EXACT"
            and predecessor.get("checkpoint_parent_commit") == V12_CORRECTION_RECEIPT
            and predecessor.get("inert_checkpoint_commit") == V13_INERT_CHECKPOINT
            and predecessor.get("failure_receipt_commit") == V13_FAILURE_RECEIPT
            and predecessor.get("workflow_path") == V13_WORKFLOW_PATH
            and predecessor.get("workflow_sha256") == V13_WORKFLOW_SHA256
            and predecessor.get("template_sha256") == V13_TEMPLATE_SHA256
            and predecessor.get("plan_verifier_sha256")
            == V13_CORE_AUTHORITIES[
                Path("tools/verify_admin_dependency_cache_export_plan_v13.py")
            ]
            and predecessor.get("plan_test_sha256")
            == V13_CORE_AUTHORITIES[
                Path("tests/test_admin_dependency_cache_export_plan_v13.py")
            ]
            and predecessor.get("import_helper_sha256") == IMPORT_HELPER_SHA256
            and predecessor.get("source_fixture_sha256") == SOURCE_FIXTURE_SHA256
            and predecessor.get("bundle_verifier_sha256") == BUNDLE_VERIFIER_SHA256
            and predecessor.get("bundle_test_sha256") == BUNDLE_TEST_SHA256
            and predecessor.get("active_request_path")
            == ".github/release-requests/admin-5335bda-dependency-cache-v13.json"
            and predecessor.get("active_request_addition_count") == 0
            and predecessor.get("workflow_run_count") == 0
            and predecessor.get("ordinary_ci_failure_count") == 2
            and predecessor.get("push_ci_run_id") == 30701666137
            and predecessor.get("pull_request_ci_run_id") == 30701667259
            and predecessor.get("receipt_created") is True
            and predecessor.get("activation_created") is False
            and predecessor.get("supersession_reason")
            == "TEMP_REPOSITORY_TEST_INHERITED_GITHUB_CHECKOUT_CONTEXT",
            "V14 V13-supersession predecessor contract changed",
        )
    recovery = template.get("recovery_basis")
    require(isinstance(recovery, dict), "V14 recovery basis missing")
    if isinstance(recovery, dict):
        require(
            recovery.get("buildkit_source_commit") == "e42e1bfd389af7203238cce77b1f7dad447285e9"
            and recovery.get("cache_record_identity_domains_source_projection_sha256") == SOURCE_FIXTURE_SHA256
            and recovery.get("v13_import_helper_sha256") == IMPORT_HELPER_SHA256
            and recovery.get("cache_config_vertex_digest_binding_authorized") is False
            and recovery.get("cache_config_structural_validation_required") is True
            and recovery.get("fresh_consumer_same_digest_cached_required") is True
            and recovery.get("dependency_cache_predicate_relaxed") is False,
            "V14 source-backed recovery contract changed",
        )
    chain = template.get("bundle_verifier_chain")
    require(
        isinstance(chain, dict)
        and chain.get("v13_sha256") == BUNDLE_VERIFIER_SHA256,
        "V14 bundle verifier chain changed",
    )
    control = template.get("control_plane")
    require(
        isinstance(control, dict)
        and control.get("inert_checkpoint_exact_changed_path_count") == 11
        and control.get("inert_receipt_exact_changed_path_count") == 4
        and control.get("activation_exact_changed_path_count") == 1
        and control.get("checkpoint_nonreceipt_immutable_path_count") == 7
        and control.get("ci_workflow_sha256") == CI_WORKFLOW_SHA256
        and control.get("v11_run_zero_required") is True
        and control.get("v12_unique_attempt1_failure_artifact0_required") is True
        and control.get("v13_run_zero_required") is True
        and control.get("v13_ci_hermeticity_failure_receipt_required") is True
        and control.get("v14_current_attempt1_artifact0_required") is True
        and control.get("run_ledger_snapshot_count") == 2,
        "V14 control-plane contract changed",
    )
    ledger = template.get("run_ledger_contract")
    legacy = ledger.get("legacy") if isinstance(ledger, dict) else None
    v11 = legacy[9] if isinstance(legacy, list) and len(legacy) == 12 else None
    v12 = legacy[10] if isinstance(legacy, list) and len(legacy) == 12 else None
    v13 = legacy[11] if isinstance(legacy, list) and len(legacy) == 12 else None
    v12_runs = v12.get("runs") if isinstance(v12, dict) else None
    require(
        isinstance(ledger, dict)
        and ledger.get("schema") == LEDGER_SCHEMA
        and isinstance(legacy, list)
        and len(legacy) == 12
        and hashlib.sha256(_canonical_json_bytes(legacy)).hexdigest()
        == LEGACY_LEDGER_SHA256
        and v11 == {
            "version": "v11",
            "workflow_path": V11_WORKFLOW_PATH,
            "runs": [],
        }
        and isinstance(v12, dict)
        and v12.get("version") == "v12"
        and v12.get("workflow_ref") == "325026609"
        and isinstance(v12_runs, list)
        and len(v12_runs) == 1
        and isinstance(v12_runs[0], dict)
        and v12_runs[0].get("id") == 30696298423
        and v13 == {
            "version": "v13",
            "workflow_path": V13_WORKFLOW_PATH,
            "runs": [],
        }
        and ledger.get("current", {}).get("version") == "v14"
        and ledger.get("current", {}).get("workflow_path") == V14_WORKFLOW_PATH,
        "V14 run-ledger contract changed",
    )
    evidence = template.get("build_evidence_recovery")
    require(
        isinstance(evidence, dict)
        and evidence.get("cache_config_record_digest_vertex_binding_required") is False
        and evidence.get("cache_config_direct_identity_path_claimed") is False
        and evidence.get("runtime_pip_pair_classification_required") == "SAME_DIGEST_CACHED"
        and evidence.get("runtime_portability_proven_only_by_fresh_consumer") is True
        and evidence.get("core_validated_cache_record_sha256_required") is True
        and evidence.get("runtime_pip_cached_false_accepted") is False,
        "V14 cache evidence contract changed",
    )
    require(
        template.get("github_actions_maximum_run_count") == 1
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
        "V14 authorization boundary changed",
    )
    return errors


def _workflow_errors(workflow: str) -> list[str]:
    errors: list[str] = []
    header = f"""name: Admin dependency cache export V14

on:
  push:
    branches:
      - {BRANCH}
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v14.json
"""
    preamble = header + """
permissions:
  contents: read
  actions: read

concurrency:
"""
    if not workflow.startswith(preamble):
        errors.append("V14 workflow trigger header changed")
    job_keys = re.findall(
        r"^  ([A-Za-z0-9_-]+):[ \t]*$",
        workflow.split("\njobs:\n", 1)[1]
        if "\njobs:\n" in workflow
        else "",
        flags=re.MULTILINE,
    )
    if job_keys != ["export-cache"]:
        errors.append("V14 workflow job inventory changed")
    if "\n    permissions:" in workflow:
        errors.append("V14 workflow job-level permissions changed")
    required = (
        "permissions:\n  contents: read\n  actions: read",
        "group: admin-dependency-cache-export-v10",
        "cancel-in-progress: false",
        "timeout-minutes: 120",
        "Prove this is the unique V14 workflow run",
        "Snapshot V2 through V14 ledgers before resource creation",
        "Export V14 dependency-only BuildKit local cache",
        "Prove V14 fresh-consumer import and cacheless replay",
        "Remove V14 builders and all transient Docker state",
        "Snapshot V2 through V14 ledgers after cleanup and before upload",
        "Validate final V14 portable bundle after cleanup",
        "Upload one-day V14 public-repository dependency cache artifact",
        "scripts/ci/import_admin_dependency_cache_v13.sh",
        "tools/verify_admin_dependency_cache_bundle_v13.py",
        "tools/verify_admin_dependency_cache_export_plan_v14.py",
        'ledger_contract_copy="${RUNNER_TEMP}/noteai-cache-v14-ledger-contract.json"',
        'cp "${NOTEAI_REQUEST_TEMPLATE}" "${ledger_contract_copy}"',
        "NOTEAI_V14_LEDGER_CONTRACT_PATH: ${{ steps.control.outputs.ledger_contract_copy }}",
        ".pair.classification == \"SAME_DIGEST_CACHED\"",
        ".cache_record.schema_version ==",
        "\"noteai.admin-dependency-cache-record.v13\"",
        "inert_checkpoint_exact_changed_path_count == 11",
        "checkpoint_nonreceipt_immutable_path_count == 7",
        "v13_run_zero_required == true",
        "python3 \"$"
        "{NOTEAI_V12_FAILURE_VERIFIER_PATH}\"",
        "- name: Remove V14 builders and all transient Docker state\n"
        "        id: cleanup\n"
        "        if: always()",
        "- name: Snapshot V2 through V14 ledgers after cleanup and before upload\n"
        "        id: late_ledger\n"
        "        if: ${{ always() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
        "- name: Validate final V14 portable bundle after cleanup\n"
        "        id: bundle\n"
        "        if: ${{ success() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
        "- name: Upload one-day V14 public-repository dependency cache artifact\n"
        "        id: upload\n"
        "        if: ${{ success() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
    )
    for token in required:
        if token not in workflow:
            errors.append(f"V14 workflow contract missing: {token}")
    if workflow.count(
        "NOTEAI_V14_LEDGER_CONTRACT_PATH: "
        "${{ steps.control.outputs.ledger_contract_copy }}"
    ) != 2:
        errors.append("V14 workflow ledger contract handoff count changed")
    if workflow.count(
        'cp "${NOTEAI_REQUEST_TEMPLATE}" "${ledger_contract_copy}"'
    ) != 1:
        errors.append("V14 workflow ledger contract copy count changed")
    for forbidden in (
        "workflow_dispatch:",
        "pull_request:",
        "permissions: write-all",
        ".cache_record.direct_path",
        "identity_link_count",
        "CACHE_RECORD_DIGEST_BINDING_INVALID",
        "scripts/ci/import_admin_dependency_cache_v14.sh",
        "tools/verify_admin_dependency_cache_bundle_v14.py",
        "python3 tools/verify_admin_dependency_cache_export_plan_v13.py",
    ):
        if forbidden in workflow:
            errors.append(f"V14 workflow forbidden token: {forbidden}")
    cleanup = workflow.find("Remove V14 builders and all transient Docker state")
    late = workflow.find("Snapshot V2 through V14 ledgers after cleanup and before upload")
    final = workflow.find("Validate final V14 portable bundle after cleanup")
    upload = workflow.find("Upload one-day V14 public-repository dependency cache artifact")
    if not 0 <= cleanup < late < final < upload:
        errors.append("V14 cleanup, late-ledger and upload ordering changed")
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
                errors.append(f"V14 authority hash drift: {path.relative_to(ROOT)}")
        except (OSError, ValueError) as exc:
            errors.append(f"cannot read V14 authority {path}: {exc}")
    return errors


def validate_plan(
    *,
    verify_git_state: bool = True,
    active_request: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        workflow_bytes = _read_frozen_bytes(WORKFLOW_PATH, label="V14 workflow")
        template_bytes = _read_frozen_bytes(TEMPLATE_PATH, label="V14 template")
        fixture_bytes = _read_frozen_bytes(SOURCE_FIXTURE_PATH, label="V14 source fixture")
        template = _strict_json_bytes(template_bytes, "V14 template")
        fixture = _strict_json_bytes(fixture_bytes, "V14 source fixture")
    except (OSError, ValueError) as exc:
        return [f"cannot load V14 dependency-cache plan: {exc}"]
    if hashlib.sha256(workflow_bytes).hexdigest() != WORKFLOW_SHA256:
        errors.append("V14 workflow hash drift")
    if hashlib.sha256(template_bytes).hexdigest() != TEMPLATE_SHA256:
        errors.append("V14 template hash drift")
    if hashlib.sha256(fixture_bytes).hexdigest() != SOURCE_FIXTURE_SHA256:
        errors.append("V14 source fixture hash drift")
    if isinstance(template, dict):
        errors.extend(_template_errors(template))
    else:
        errors.append("V14 template root changed")
    errors.extend(_workflow_errors(workflow_bytes.decode("utf-8")))
    if not (
        isinstance(fixture, dict)
        and fixture.get("classification") == "SOURCE_PROVEN_DISTINCT_CACHE_KEY_AND_LLB_VERTEX_IDENTITY_DOMAINS"
        and fixture.get("commit") == "e42e1bfd389af7203238cce77b1f7dad447285e9"
        and fixture.get("claims", {}).get("record_digest_equals_progress_vertex_digest_is_source_supported") is False
        and fixture.get("claims", {}).get("source_review_is_runtime_cache_portability_evidence") is False
        and fixture.get("v13_contract", {}).get("runtime_portability_acceptance") == "FRESH_CONSUMER_SAME_DIGEST_CACHED_ONLY"
    ):
        errors.append("V14 source fixture semantics changed")
    errors.extend(_validate_frozen_worktree())
    supplied = active_request is not None
    if supplied:
        present, active, active_errors = True, active_request, []
    else:
        present, active, active_errors = _active_request()
    errors.extend(active_errors)
    if present and active is not None:
        expected = template_bytes.replace(
            b"__DIRECT_PARENT_COMMIT__",
            str(active.get("plan_checkpoint_commit", "")).encode("ascii"),
        )
        try:
            active_bytes = (json.dumps(
                active,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            ) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            active_bytes = b""
        if (
            COMMIT_RE.fullmatch(str(active.get("plan_checkpoint_commit", ""))) is None
            or active_bytes != expected
        ):
            errors.append("V14 active request differs from reviewed template")
        if verify_git_state and not supplied:
            errors.extend(_validate_active_git(active))
    elif present:
        errors.append("V14 active request is invalid")
    if verify_git_state:
        errors.extend(_validate_v13_superseded_predecessor())
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
                    errors.append("inactive V14 request has prior addition history")
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                errors.append(f"cannot verify inactive V14 request history: {exc}")
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
            "V14_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V14_CONSUMED_OR_INVALID"
    return "PREPARED_V14_NOT_TRIGGERED"


def plan_state() -> str:
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
        git_errors.append("inactive V14 request has prior history")
    base_errors.extend(_validate_v13_superseded_predecessor())
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
def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"{label} is not an integer")
    return value


def _expected_ledger_contract() -> dict[str, Any]:
    configured = os.environ.get("NOTEAI_V14_LEDGER_CONTRACT_PATH")
    path = Path(configured) if configured else TEMPLATE_PATH
    payload = _read_frozen_bytes(
        path,
        label="V14 ledger contract template",
        required_mode=0o400 if configured else 0o644,
    )
    _require(
        hashlib.sha256(payload).hexdigest() == TEMPLATE_SHA256,
        "V14 ledger contract template hash drift",
    )
    template = _strict_json_bytes(payload, "V14 ledger contract template")
    _require(isinstance(template, dict), "V14 ledger template root changed")
    contract = template.get("run_ledger_contract")
    _require(isinstance(contract, dict), "V14 ledger contract missing")
    legacy = contract.get("legacy")
    _require(isinstance(legacy, list) and len(legacy) == 12, "V14 legacy ledger changed")
    _require(
        hashlib.sha256(_canonical_json_bytes(legacy)).hexdigest()
        == LEGACY_LEDGER_SHA256,
        "V14 legacy ledger history changed",
    )
    v11 = legacy[9]
    v12 = legacy[10]
    v13 = legacy[11]
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
        and contract.get("current")
        == {
            "version": "v14",
            "workflow_path": V14_WORKFLOW_PATH,
            "expected_run_count": 1,
            "event": "push",
            "run_attempt": 1,
            "artifact_count": 0,
        },
        "V14 ledger contract changed",
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
        if expected_version.get("version") in {"v11", "v13"}:
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
    v14_run_ids = {
        run["id"]
        for run in repository_projections[1]
        if run["path"] == V14_WORKFLOW_PATH
    }
    _require(
        v14_run_ids == {current_run_id},
        "V14 workflow repository inventory changed",
    )
    result: list[dict[str, Any]] = []
    for expected_version in contract["legacy"]:
        if expected_version["version"] in {"v11", "v13"}:
            version = expected_version["version"]
            workflow_path = (
                V11_WORKFLOW_PATH if version == "v11" else V13_WORKFLOW_PATH
            )
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
        current.get("path") == V14_WORKFLOW_PATH,
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
    _require(len(runs) == 1, "V14 workflow run count changed")
    run = runs[0]
    _require(_strict_int(run.get("id"), "current run id") == run_id, "current run id changed")
    _require(
        _strict_int(run.get("workflow_id"), "current run workflow id")
        == workflow_id,
        "current run workflow id changed",
    )
    _require(run.get("head_sha") == head_sha, "current run head changed")
    _require(run.get("head_branch") == head_branch, "current run branch changed")
    _require(run.get("path") == V14_WORKFLOW_PATH, "current workflow path changed")
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
        "path": V14_WORKFLOW_PATH,
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
    _require(current.get("path") == V14_WORKFLOW_PATH, "pre-resource path changed")
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
                "User-Agent": "noteai-v14-ledger",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        last_error: BaseException | None = None
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            _require(remaining > 0, "V14 ledger deadline exceeded")
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
                _require(remaining > 0, "V14 ledger deadline exceeded")
                time.sleep(min(1.0, remaining))
        raise RuntimeError("GitHub ledger request failed") from last_error

    return fetch


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = _read_frozen_bytes(
        path,
        label="V14 ledger snapshot",
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
    print(f"admin_dependency_cache_v14_live_ledger=PASS phase={phase}")
    return 0


def main() -> int:
    try:
        if len(sys.argv) > 1:
            _require(sys.argv[1] == "live-ledger", "V14 command changed")
            return _live_ledger_main(sys.argv[2:])
        errors = validate_plan()
        if errors:
            for error in errors:
                print(f"FAIL: {error}")
            return 1
        print(
            "admin_dependency_cache_export_plan_v14=PASS "
            f"state={plan_state()}"
        )
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
