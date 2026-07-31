#!/usr/bin/env python3
"""Verify the Secret-free terminal receipt for cache-export V5 attempt 1."""

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
    / "admin-dependency-cache-v5-attempt1-failed-20260731.json"
)
EVIDENCE_FILE_SHA256 = (
    "0deb75a5e2c1081db3599f30139fabc2"
    "1c2931f0bc05420d7713796329729a06"
)
EXPECTED_SEMANTIC_SHA256 = (
    "a709775ebbff9ce701d48ae8ab2a05b0"
    "264fcfc09597f55afcf1ac9a2ed830bc"
)
SOURCE_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildx_v0.35.0_rawjson_schema_projection.json"
)
SOURCE_PROJECTION_SHA256 = (
    "44429de50d1d823a06cd4b17a10b3a9"
    "d19e674418dd7ff065929ed02237245ce"
)
PLAN_CHECKPOINT_COMMIT = "ec4b806ea7ffe24de6f8005d077bb6d81a0ec1c9"
CONTROL_COMMIT = "58871b0be3427ed643f44bc198c9fe3c87a01600"
REQUEST_PATH = Path(
    ".github/release-requests/admin-5335bda-dependency-cache-v5.json"
)
REQUEST_SHA256 = (
    "417ecf201b61bab280af1f6db59eec98"
    "d4fa8ff672c609765b82bdb4b52b5b93"
)
FROZEN_PATHS = {
    Path(".github/workflows/admin-dependency-cache-export-v5.yml"): (
        "a784ed678e642d0c958ee89d1937dbd1"
        "ac73b88352a56f9ef14b1615a2b3546a"
    ),
    Path("deploy/production/plans/admin-dependency-cache-export-request-v5.json"): (
        "766a87aec122860e325730eeebc24a705"
        "ec777dc157ae603b3e154ffd6d6dfad"
    ),
    Path("tools/verify_admin_dependency_cache_export_plan_v5.py"): (
        "78d58b5bbfa5971a968fa2b52a9ddb27"
        "e791393979ca558efcfae5b902be86ef"
    ),
    Path("tools/verify_admin_dependency_cache_transient_state_v5.py"): (
        "4b81fb25c259a5a5c8a3f115b6d45396"
        "98280c744535c5ff002b658dbec9cb5f"
    ),
    Path("scripts/ci/cleanup_admin_dependency_cache_v5.sh"): (
        "a291c7242a0ac343faca19a921b2ad05"
        "6d212aa2ef175a6b58b33ef028bbf239"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v3.py"): (
        "c2e318d5d9cbe196d8b9294277c85e1e"
        "e986ccb3e1970b3d25a31d28c8da0fef"
    ),
    Path("tools/verify_admin_dependency_cache_bundle.py"): (
        "bf526c29b213dc15d257cb9aedc52790"
        "aa1dc9cf1f82bba0e6e85e41db3edf38"
    ),
    Path("scripts/ci/export_admin_dependency_cache.sh"): (
        "fabcdc2245c537c2fd56e88b6e0aced77"
        "d5c26234fc74d7d934b11ecda8d860c"
    ),
    Path("scripts/ci/import_admin_dependency_cache.sh"): (
        "c4986143d5897140f72ad6835b44f7fc9"
        "89830a30341cb4e3f5718fced3ca777"
    ),
    Path("scripts/ci/download_admin_dependency_cache_artifact.sh"): (
        "66abfd513be7aa81946072493e1472030"
        "a8acccbf7a3e2d4dc461c94712e2a92"
    ),
    Path("tools/verify_admin_dependency_cache_provider_download.py"): (
        "ca05697d12b8c02b183b1c611c33781d"
        "63641c5369bc54b2508a538591a0986b"
    ),
    Path(
        "tests/fixtures/"
        "admin_dependency_cache_buildx_v0.35.0_provenance_gha_disabled_projection.json"
    ): (
        "33de770d1f2d31ab794d914c28e0f148c"
        "b614629fece4dc50ad9a68fe665999d"
    ),
}
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


def cleanup_compact_payload_sha256(
    cleanup: Any,
) -> str | None:
    if not isinstance(cleanup, dict):
        return None
    try:
        projected = {
            key: cleanup[key]
            for key in CLEANUP_COMPACT_KEYS
        }
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
            errors.append("V5 controller parent binding changed")

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
            errors.append("V5 controller is no longer request-only")

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
            errors.append("V5 request addition history changed")

        control_request = _git_bytes(
            "show",
            f"{CONTROL_COMMIT}:{request_name}",
        )
        if sha256_bytes(control_request) != REQUEST_SHA256:
            errors.append("V5 control request bytes changed")
        if _git_bytes("show", f"HEAD:{request_name}") != control_request:
            errors.append("V5 request is not retained byte-exact at HEAD")

        tree_fields = _git_text(
            "ls-tree",
            "HEAD",
            "--",
            request_name,
        ).split()
        if tree_fields[:2] != ["100644", "blob"]:
            errors.append("V5 request retained mode changed")

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
                        f"V5 {label} tree file hash changed: {path.as_posix()}"
                    )
                historical_mode = _git_text(
                    "ls-tree",
                    commit,
                    "--",
                    path.as_posix(),
                ).split()
                if historical_mode[:2] != ["100644", "blob"]:
                    errors.append(
                        f"V5 {label} tree file mode changed: {path.as_posix()}"
                    )

        template_path = next(
            path
            for path in FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-request-v5.json"
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
            errors.append("V5 control request differs from its frozen template")
        request = json.loads(
            control_request.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
            parse_float=parse_float,
        )
        if request.get("plan_checkpoint_commit") != PLAN_CHECKPOINT_COMMIT:
            errors.append("V5 request embedded parent changed")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify frozen V5 Git state: {exc}")
    return errors


def verify(payload: dict[str, Any], *, verify_git_state: bool = True) -> list[str]:
    errors: list[str] = []

    if semantic_sha256(payload) != EXPECTED_SEMANTIC_SHA256:
        errors.append("V5 failure evidence semantics changed")
    try:
        if sha256_bytes(EVIDENCE_PATH.read_bytes()) != EVIDENCE_FILE_SHA256:
            errors.append("V5 failure evidence file bytes changed")
        if (
            sha256_bytes(SOURCE_PROJECTION_PATH.read_bytes())
            != SOURCE_PROJECTION_SHA256
        ):
            errors.append("V5 rawjson source projection hash changed")
        for path, expected_sha256 in FROZEN_PATHS.items():
            if sha256_bytes((ROOT / path).read_bytes()) != expected_sha256:
                errors.append(f"frozen V5 file hash changed: {path.as_posix()}")
    except OSError as exc:
        errors.append(f"cannot load frozen V5 evidence closure: {exc}")

    if verify_git_state:
        errors.extend(verify_frozen_git())
    cleanup = payload.get("cleanup")
    if (
        cleanup_compact_payload_sha256(cleanup)
        != (
            cleanup.get("compact_log_payload_sha256")
            if isinstance(cleanup, dict)
            else None
        )
    ):
        errors.append("V5 cleanup compact payload hash does not derive")
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
    print("admin_dependency_cache_v5_failure_evidence=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
