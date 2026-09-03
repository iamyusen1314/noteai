#!/usr/bin/env python3
"""Verify the Secret-free terminal receipt for the unique V10 cache run."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import verify_admin_dependency_cache_v9_failure_evidence as v9_failure
import verify_admin_dependency_cache_export_plan_v10 as v10_plan


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "evidence"
    / "admin-dependency-cache-v10-attempt1-failed-20260731.json"
)
EVIDENCE_FILE_SHA256 = (
    "9b8a1e3a28c5ca2e1a6d4c495e2404f7"
    "ea027abf42bfa27ccd4649909f043103"
)
EXPECTED_SEMANTIC_SHA256 = (
    "352debb0294df5c442bf1b0ea0594576e"
    "49f649c830c2e1f568d4f0a4e9e4336"
)

V9_TERMINAL_RECEIPT_COMMIT = "512638647c5851aa3258cd472da42894110465af"
INERT_CHECKPOINT_COMMIT = "9199fb598790a03302c21dd3968c63b58d03f2c2"
INERT_RECEIPT_COMMIT = "b02c4a18d6b77024f17d0e56c1d081a578854b1f"
CONTROL_COMMIT = "ea2a3b489e74b21a88ea21ecd243cd6a433c7fac"
DIRECT_PARENT_COMMIT = INERT_RECEIPT_COMMIT
REQUEST_PATH = Path(
    ".github/release-requests/"
    "admin-5335bda-dependency-cache-v10.json"
)
REQUEST_SHA256 = (
    "4b3c8950bea4a0e9cdc578a69f193fb6"
    "3cccb5be447bba777951718249d96db0"
)
TEMPLATE_PATH = Path(
    "deploy/production/plans/"
    "admin-dependency-cache-export-request-v10.json"
)

INERT_CHECKPOINT_PATHS = (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    ".github/workflows/admin-dependency-cache-export-v10.yml",
    "deploy/production/internal-deployment-readiness.json",
    "deploy/production/plans/admin-dependency-cache-export-request-v10.json",
    "scripts/ci/import_admin_dependency_cache_v10.sh",
    "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_cache_observer_projection.json",
    "tests/test_admin_dependency_cache_bundle_verifier_v10.py",
    "tests/test_admin_dependency_cache_export_plan_v10.py",
    "tests/test_internal_deployment_readiness_gate.py",
    "tests/test_production_readiness_gate.py",
    "tools/production_readiness_gate.py",
    "tools/verify_admin_dependency_cache_bundle_v10.py",
    "tools/verify_admin_dependency_cache_export_plan_v10.py",
)
INERT_RECEIPT_PATHS = (
    ".codex/handoffs/current-task.md",
    ".codex/notes/risk-register.md",
    "deploy/production/internal-deployment-readiness.json",
    "tests/test_internal_deployment_readiness_gate.py",
)

FROZEN_INERT_PATHS = {
    Path(".github/workflows/admin-dependency-cache-export-v10.yml"): (
        "fd9570833c35aa3fc0d8632d26d68cca"
        "9ef33e960c26c4f4410eaaa6f7572d96"
    ),
    TEMPLATE_PATH: (
        "2ac7f6ed83be057ffc79ca349888e8691"
        "d9324f3474942fe65571055e59c8bcc"
    ),
    Path(
        "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_"
        "cache_observer_projection.json"
    ): (
        "f743084bb704d0fd6858510d81ebe6479"
        "ac0c6baae982b353715c328bc6fcd27"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v10.py"): (
        "77c2410406448998c81d09b04d93d12d"
        "b1cb3a4a032a0b78d9fc25626014758f"
    ),
    Path("scripts/ci/import_admin_dependency_cache_v10.sh"): (
        "d8388ff776290b05aa699f3a09363fc20"
        "87c3b8bd5ada23b556d6cb14953b85f"
    ),
    Path("tests/test_admin_dependency_cache_bundle_verifier_v10.py"): (
        "0f5e359904533c19768cf6b0ae2dc872"
        "58cda3a76472537fac4e2fe2d7f90725"
    ),
}
FROZEN_SUPPORT_PATHS = {
    Path("scripts/ci/export_admin_dependency_cache.sh"): (
        "fabcdc2245c537c2fd56e88b6e0aced7"
        "7d5c26234fc74d7d934b11ecda8d860c"
    ),
    Path("scripts/ci/import_admin_dependency_cache.sh"): (
        "c4986143d5897140f72ad6835b44f7fc"
        "989830a30341cb4e3f5718fced3ca777"
    ),
    Path(
        "deploy/production/evidence/"
        "admin-dependency-cache-v9-attempt1-failed-20260731.json"
    ): (
        "3769b30bd827adce9bb2e28b258991b5"
        "202e1fc8214a1b8428705e852d2b8fa5"
    ),
    Path("tools/verify_admin_dependency_cache_v9_failure_evidence.py"): (
        "0db0086f120ade148bafc30b6de143c28"
        "d8cd3e37ec216c055280b1196586743"
    ),
    Path("tools/verify_admin_dependency_cache_transient_state_v5.py"): (
        "4b81fb25c259a5a5c8a3f115b6d45396"
        "98280c744535c5ff002b658dbec9cb5f"
    ),
    Path("scripts/ci/cleanup_admin_dependency_cache_v5.sh"): (
        "a291c7242a0ac343faca19a921b2ad05"
        "6d212aa2ef175a6b58b33ef028bbf239"
    ),
}
ACTIVATION_HISTORICAL_PATHS = {
    Path("tools/verify_admin_dependency_cache_export_plan_v10.py"): (
        "6e89496a983151a953560083c7c327d7c"
        "98847f77ed09cb027755f8f1d65c136"
    ),
    Path("tests/test_admin_dependency_cache_export_plan_v10.py"): (
        "a2c593ef0acbd2bc0833dec9444a82c52"
        "f6a65356155b6a8a6fa6a3162d63698"
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
        raise ValueError("failure evidence root must be an object")
    return payload


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def semantic_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def diagnostic_payload_sha256(diagnostic: Any) -> str | None:
    if not isinstance(diagnostic, dict):
        return None
    projected = copy.deepcopy(diagnostic)
    expected = projected.pop("diagnostic_sha256", None)
    if not isinstance(expected, str):
        return None
    try:
        encoded = json.dumps(
            projected,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return sha256_bytes(encoded)


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


def _regular_blob_mode(commit: str, path: Path) -> bool:
    fields = _git_text("ls-tree", commit, "--", path.as_posix()).split()
    return fields[:2] == ["100644", "blob"]


def _commit_parents(commit: str) -> list[str]:
    record = _git_text("rev-list", "--parents", "-n", "1", commit).split()
    if not record or record[0] != commit:
        raise ValueError(f"cannot resolve commit parents: {commit}")
    return record[1:]


def _tree_entry(commit: str, path: Path) -> str:
    return _git_text("ls-tree", commit, "--", path.as_posix())


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).returncode == 0


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
        current = _tree_entry(candidate, path)
        if current and all(not _tree_entry(parent, path) for parent in parents):
            additions.append(candidate)
    return additions


def _lineage_path_changes(anchor: str, paths: tuple[Path, ...]) -> list[str]:
    output = _git_text(
        "rev-list",
        "--ancestry-path",
        "--parents",
        f"{anchor}..HEAD",
    )
    records = [line.split() for line in output.splitlines() if line]
    lineage = {anchor, *(record[0] for record in records)}
    changes: list[str] = []
    path_names = tuple(path.as_posix() for path in paths)
    for record in records:
        commit, parents = record[0], record[1:]
        for parent in (parent for parent in parents if parent in lineage):
            changed = _git_text(
                "diff-tree",
                "--no-commit-id",
                "--no-renames",
                "--name-only",
                "-r",
                parent,
                commit,
                "--",
                *path_names,
            )
            if changed:
                changes.append(commit)
                break
    return changes


def verify_frozen_git() -> list[str]:
    errors: list[str] = []
    request_name = REQUEST_PATH.as_posix()
    try:
        if _commit_parents(INERT_CHECKPOINT_COMMIT) != [
            V9_TERMINAL_RECEIPT_COMMIT
        ]:
            errors.append("V10 inert checkpoint parent binding changed")
        if _commit_parents(INERT_RECEIPT_COMMIT) != [INERT_CHECKPOINT_COMMIT]:
            errors.append("V10 inert receipt parent binding changed")
        if _commit_parents(CONTROL_COMMIT) != [DIRECT_PARENT_COMMIT]:
            errors.append("V10 controller parent binding changed")

        inert_changed = _git_text(
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            V9_TERMINAL_RECEIPT_COMMIT,
            INERT_CHECKPOINT_COMMIT,
        ).splitlines()
        if tuple(inert_changed) != INERT_CHECKPOINT_PATHS:
            errors.append("V10 inert checkpoint path set changed")
        receipt_changed = _git_text(
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            INERT_CHECKPOINT_COMMIT,
            INERT_RECEIPT_COMMIT,
        ).splitlines()
        if tuple(receipt_changed) != INERT_RECEIPT_PATHS:
            errors.append("V10 inert receipt path set changed")
        activation_changed = _git_text(
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-status",
            "-r",
            DIRECT_PARENT_COMMIT,
            CONTROL_COMMIT,
        )
        if activation_changed != f"A\t{request_name}":
            errors.append("V10 controller is no longer request-only")

        if _true_additions(REQUEST_PATH) != [CONTROL_COMMIT]:
            errors.append("V10 request true-addition history changed")
        if not _is_ancestor(CONTROL_COMMIT, "HEAD"):
            errors.append("V10 controller is not an ancestor of HEAD")
        if _lineage_path_changes(CONTROL_COMMIT, (REQUEST_PATH,)):
            errors.append("V10 request changed after activation")

        control_request = _git_bytes("show", f"{CONTROL_COMMIT}:{request_name}")
        if sha256_bytes(control_request) != REQUEST_SHA256:
            errors.append("V10 control request bytes changed")
        if _git_bytes("show", f"HEAD:{request_name}") != control_request:
            errors.append("V10 request is not retained byte-exact at HEAD")
        if not _regular_blob_mode(CONTROL_COMMIT, REQUEST_PATH):
            errors.append("V10 control request mode changed")
        if not _regular_blob_mode("HEAD", REQUEST_PATH):
            errors.append("V10 request retained mode changed")

        template_bytes = _git_bytes(
            "show", f"{DIRECT_PARENT_COMMIT}:{TEMPLATE_PATH.as_posix()}"
        )
        if template_bytes.count(b"__DIRECT_PARENT_COMMIT__") != 1:
            errors.append("V10 frozen template placeholder count changed")
        expected_request = template_bytes.replace(
            b"__DIRECT_PARENT_COMMIT__",
            DIRECT_PARENT_COMMIT.encode("ascii"),
        )
        if control_request != expected_request:
            errors.append("V10 control request differs from its frozen template")
        request = json.loads(
            control_request.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
            parse_float=parse_float,
        )
        if request.get("plan_checkpoint_commit") != DIRECT_PARENT_COMMIT:
            errors.append("V10 request embedded parent changed")

        for path, expected_sha256 in FROZEN_INERT_PATHS.items():
            if _tree_entry(V9_TERMINAL_RECEIPT_COMMIT, path):
                errors.append(f"V10 inert file existed before checkpoint: {path}")
            for commit, label in (
                (INERT_CHECKPOINT_COMMIT, "checkpoint"),
                (INERT_RECEIPT_COMMIT, "receipt"),
                (CONTROL_COMMIT, "control"),
                ("HEAD", "HEAD"),
            ):
                historical = _git_bytes("show", f"{commit}:{path.as_posix()}")
                if sha256_bytes(historical) != expected_sha256:
                    errors.append(f"V10 {label} inert file hash changed: {path}")
                if not _regular_blob_mode(commit, path):
                    errors.append(f"V10 {label} inert file mode changed: {path}")
            local_path = ROOT / path
            if not stat.S_ISREG(local_path.lstat().st_mode):
                errors.append(f"V10 inert worktree file type changed: {path}")
            elif sha256_bytes(local_path.read_bytes()) != expected_sha256:
                errors.append(f"V10 inert worktree file hash changed: {path}")
        if _lineage_path_changes(
            INERT_CHECKPOINT_COMMIT,
            tuple(FROZEN_INERT_PATHS),
        ):
            errors.append("V10 inert authority changed after checkpoint")

        for path, expected_sha256 in FROZEN_SUPPORT_PATHS.items():
            for commit, label in ((CONTROL_COMMIT, "control"), ("HEAD", "HEAD")):
                historical = _git_bytes("show", f"{commit}:{path.as_posix()}")
                if sha256_bytes(historical) != expected_sha256:
                    errors.append(f"V10 {label} support file hash changed: {path}")
                if not _regular_blob_mode(commit, path):
                    errors.append(f"V10 {label} support file mode changed: {path}")
            local_path = ROOT / path
            if not stat.S_ISREG(local_path.lstat().st_mode):
                errors.append(f"V10 support worktree file type changed: {path}")
            elif sha256_bytes(local_path.read_bytes()) != expected_sha256:
                errors.append(f"V10 support worktree file hash changed: {path}")

        for path, expected_sha256 in ACTIVATION_HISTORICAL_PATHS.items():
            historical = _git_bytes("show", f"{CONTROL_COMMIT}:{path.as_posix()}")
            if sha256_bytes(historical) != expected_sha256:
                errors.append(f"V10 activation authority hash changed: {path}")
            if not _regular_blob_mode(CONTROL_COMMIT, path):
                errors.append(f"V10 activation authority mode changed: {path}")

        if _lineage_path_changes(
            V9_TERMINAL_RECEIPT_COMMIT,
            v10_plan.LEGACY_FROZEN_PATHS,
        ):
            errors.append("V2-V9 frozen authority changed after terminal receipt")

        try:
            v9_payload = v9_failure.load_strict()
            v9_errors = v9_failure.verify(v9_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            v9_errors = [str(exc)]
        errors.extend(f"frozen V9 evidence: {error}" for error in v9_errors)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify frozen V10 Git state: {exc}")
    return errors


def verify(
    payload: dict[str, Any],
    *,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []
    if set(payload) != EXPECTED_ROOT_KEYS:
        errors.append("V10 failure evidence root key set changed")
    if semantic_sha256(payload) != EXPECTED_SEMANTIC_SHA256:
        errors.append("V10 failure evidence semantics changed")
    try:
        if sha256_bytes(EVIDENCE_PATH.read_bytes()) != EVIDENCE_FILE_SHA256:
            errors.append("V10 failure evidence file bytes changed")
    except OSError as exc:
        errors.append(f"cannot load frozen V10 evidence closure: {exc}")
    if verify_git_state:
        errors.extend(verify_frozen_git())

    failure = payload.get("failure")
    for name in (
        "producer_v9_diagnostic",
        "producer_v10_diagnostic",
        "import_v10_diagnostic",
    ):
        diagnostic = failure.get(name) if isinstance(failure, dict) else None
        if diagnostic_payload_sha256(diagnostic) != (
            diagnostic.get("diagnostic_sha256")
            if isinstance(diagnostic, dict)
            else None
        ):
            errors.append(f"V10 {name.replace('_', ' ')} hash does not derive")
    cleanup = payload.get("cleanup")
    if cleanup_compact_payload_sha256(cleanup) != (
        cleanup.get("compact_log_payload_sha256")
        if isinstance(cleanup, dict)
        else None
    ):
        errors.append("V10 cleanup compact payload hash does not derive")
    return errors


def main() -> int:
    try:
        payload = load_strict()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    errors = verify(payload)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("admin_dependency_cache_v10_failure_evidence=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
