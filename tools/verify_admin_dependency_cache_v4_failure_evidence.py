#!/usr/bin/env python3
"""Verify the Secret-free terminal receipt for cache-export V4 attempt 1."""

from __future__ import annotations

import hashlib
import json
import math
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
    / "admin-dependency-cache-v4-attempt1-failed-20260731.json"
)
EVIDENCE_FILE_SHA256 = (
    "237891f4f1a1c7ff387965d0b98d2791"
    "404e33815d1688ecb271761526e16fb1"
)
EXPECTED_SEMANTIC_SHA256 = (
    "48aa288058c738e702f96a46eef251e9"
    "e77f90def4201f4583479e1a77c2824a"
)
PLAN_CHECKPOINT_COMMIT = "afeba532e9dee9c8fa27dfccadcb9f2414534451"
CONTROL_COMMIT = "d5aa7e537590ed138d254b9909a1ac105ee321ce"
REQUEST_PATH = Path(
    ".github/release-requests/admin-5335bda-dependency-cache-v4.json"
)
REQUEST_SHA256 = (
    "ad398386b7f01e8481a741c634da8e66"
    "ff1ba1d091bfaf0dff2f719b29172ec4"
)
FROZEN_PATHS = {
    Path(".github/workflows/admin-dependency-cache-export-v4.yml"): (
        "5331e03bd2080651c5374b6f051e34da"
        "569eb16d50ed3f8b3b9856edc94304cc"
    ),
    Path("deploy/production/plans/admin-dependency-cache-export-request-v4.json"): (
        "6e2a7ba6f6f242ef1bcaa84cc47cbab4"
        "d51763d2425b4999b6f506e769a614da"
    ),
    Path("tools/verify_admin_dependency_cache_export_plan_v4.py"): (
        "b8f05cc19cdc59171f4e41d6b31f5c1"
        "5809852e18b61046164dafedc2c8b9fbf"
    ),
    Path("tools/verify_admin_dependency_cache_transient_state_v4.py"): (
        "a6578845bc220f38ffc819ced26d8d0c3"
        "530b37e53ebc4c74cceeb4b523ea432"
    ),
    Path("scripts/ci/cleanup_admin_dependency_cache_v4.sh"): (
        "6cc130389abcd60a6f1e901160957ab2f"
        "2c33e0986e4b8c2a6c6fa89caa23ab2"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v3.py"): (
        "c2e318d5d9cbe196d8b9294277c85e1e"
        "e986ccb3e1970b3d25a31d28c8da0fef"
    ),
}


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


def verify_frozen_git() -> list[str]:
    errors: list[str] = []
    request_name = REQUEST_PATH.as_posix()
    try:
        parents = _git_text(
            "rev-list",
            "--parents",
            "-n",
            "1",
            CONTROL_COMMIT,
        ).split()
        if parents != [CONTROL_COMMIT, PLAN_CHECKPOINT_COMMIT]:
            errors.append("V4 controller parent binding changed")

        changed = _git_text(
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-status",
            "-r",
            PLAN_CHECKPOINT_COMMIT,
            CONTROL_COMMIT,
        )
        if changed != f"A\t{request_name}":
            errors.append("V4 controller is no longer request-only")

        additions_output = _git_text(
            "log",
            "--all",
            "--diff-filter=A",
            "--format=%H",
            "--",
            request_name,
        )
        additions = additions_output.splitlines() if additions_output else []
        if additions != [CONTROL_COMMIT]:
            errors.append("V4 request addition history changed")

        control_request = _git_bytes(
            "show",
            f"{CONTROL_COMMIT}:{request_name}",
        )
        if sha256_bytes(control_request) != REQUEST_SHA256:
            errors.append("V4 control request bytes changed")
        if _git_bytes("show", f"HEAD:{request_name}") != control_request:
            errors.append("V4 request is not retained byte-exact at HEAD")

        tree_fields = _git_text(
            "ls-tree",
            "HEAD",
            "--",
            request_name,
        ).split()
        if tree_fields[:2] != ["100644", "blob"]:
            errors.append("V4 request retained mode changed")

        for commit, label in (
            (PLAN_CHECKPOINT_COMMIT, "plan"),
            (CONTROL_COMMIT, "control"),
        ):
            for path, expected_sha256 in FROZEN_PATHS.items():
                historical = _git_bytes(
                    "show",
                    f"{commit}:{path.as_posix()}",
                )
                if sha256_bytes(historical) != expected_sha256:
                    errors.append(
                        f"V4 {label} tree file hash changed: {path.as_posix()}"
                    )
                historical_mode = _git_text(
                    "ls-tree",
                    commit,
                    "--",
                    path.as_posix(),
                ).split()
                if historical_mode[:2] != ["100644", "blob"]:
                    errors.append(
                        f"V4 {label} tree file mode changed: {path.as_posix()}"
                    )

        template_path = next(
            path
            for path in FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-request-v4.json"
        )
        template_bytes = _git_bytes(
            "show",
            f"{PLAN_CHECKPOINT_COMMIT}:{template_path.as_posix()}",
        )
        expected_request = template_bytes.replace(
            b"__DIRECT_PARENT_COMMIT__",
            PLAN_CHECKPOINT_COMMIT.encode("ascii"),
        )
        if control_request != expected_request:
            errors.append("V4 control request differs from its frozen template")
        request = json.loads(
            control_request.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
            parse_float=parse_float,
        )
        if request.get("plan_checkpoint_commit") != PLAN_CHECKPOINT_COMMIT:
            errors.append("V4 request embedded parent changed")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify frozen V4 Git state: {exc}")
    return errors


def verify(payload: dict[str, Any], *, verify_git_state: bool = True) -> list[str]:
    errors: list[str] = []

    if semantic_sha256(payload) != EXPECTED_SEMANTIC_SHA256:
        errors.append("V4 failure evidence semantics changed")
    try:
        if sha256_bytes(EVIDENCE_PATH.read_bytes()) != EVIDENCE_FILE_SHA256:
            errors.append("V4 failure evidence file bytes changed")
        for path, expected_sha256 in FROZEN_PATHS.items():
            if sha256_bytes((ROOT / path).read_bytes()) != expected_sha256:
                errors.append(f"frozen V4 file hash changed: {path.as_posix()}")
    except OSError as exc:
        errors.append(f"cannot load frozen V4 evidence closure: {exc}")

    if verify_git_state:
        errors.extend(verify_frozen_git())
    return errors


def main() -> int:
    try:
        payload = load_strict()
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    errors = verify(payload)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("admin_dependency_cache_v4_failure_evidence=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
