#!/usr/bin/env python3
"""Verify the Secret-free terminal receipt for the unique V9 cache run."""

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


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "evidence"
    / "admin-dependency-cache-v9-attempt1-failed-20260731.json"
)
EVIDENCE_FILE_SHA256 = (
    "3769b30bd827adce9bb2e28b258991b5"
    "202e1fc8214a1b8428705e852d2b8fa5"
)
EXPECTED_SEMANTIC_SHA256 = (
    "144200468493e909301ad7d9edb88403"
    "f060d5092a445ab8692c6481b166db01"
)

INERT_CHECKPOINT_COMMIT = "590ffc863d7475b5637e644461c7ac7e8612052b"
DIRECT_PARENT_COMMIT = "c2aebc9bdae9cc26c6c29d994bf55b547349e231"
CONTROL_COMMIT = "fbe629daad669191d4ea9903ffb488c98055f000"
REQUEST_PATH = Path(
    ".github/release-requests/"
    "admin-5335bda-dependency-cache-v9.json"
)
REQUEST_SHA256 = (
    "57c1506bb6e483e2e9f74e510847e278d"
    "be336869cdc113ecc0230aebabd07d6"
)
TEMPLATE_PATH = Path(
    "deploy/production/plans/"
    "admin-dependency-cache-export-request-v9.json"
)

FROZEN_PATHS = {
    Path(".github/workflows/admin-dependency-cache-export-v9.yml"): (
        "ece8eb8e9c9d8a8997faa838c87a3a06"
        "a407bc3382670bf8f294433982e62f34"
    ),
    TEMPLATE_PATH: (
        "ae5114d66eb2aedd4db875b857974b063"
        "1caa1a39ad75a16e22ccbaecc424a3b"
    ),
    Path("tools/verify_admin_dependency_cache_export_plan_v9.py"): (
        "d3d4b32d3a2f98b4311d1576e7c69446"
        "b9e95cbd1e92a85b7562fe9a4d7bb0d0"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v9.py"): (
        "a69103e899dc74b4d34e4837e29f40284"
        "be9b252281fed262a2dd1afee3d6032"
    ),
    Path(
        "tests/fixtures/"
        "admin_dependency_cache_buildkit_v0.31.2_"
        "vertex_input_omission_projection.json"
    ): (
        "3738f1b5bea4490c063cee7749fe39134"
        "b0f63005201496ac74aa1d125efb9fd"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v8.py"): (
        "b07f9dee54862969fe90ef438c357a3445"
        "a9fe9574b69a9f87440e3ed9920300"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v7.py"): (
        "76af4aa0c8dbe68b46cc71fb74f158203"
        "0c5f28a7218a2ee04bcbde5f4198cd7"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v6.py"): (
        "86d93114e804bf6a51fdb160651d6a20c"
        "555f107b88020e0f8d811d0f0d358e5"
    ),
    Path("tools/verify_admin_dependency_cache_bundle_v3.py"): (
        "c2e318d5d9cbe196d8b9294277c85e1e"
        "e986ccb3e1970b3d25a31d28c8da0fef"
    ),
    Path("tools/verify_admin_dependency_cache_bundle.py"): (
        "bf526c29b213dc15d257cb9aedc52790a"
        "a1dc9cf1f82bba0e6e85e41db3edf38"
    ),
    Path(
        "deploy/production/evidence/"
        "admin-dependency-cache-v8-attempt1-failed-20260731.json"
    ): (
        "e4b69bab7c607ec71f44ec390be9acb69"
        "3de53d05c33a62cb21b6691255e206b"
    ),
    Path("tools/verify_admin_dependency_cache_v8_failure_evidence.py"): (
        "4ddeca8a7b60e0c8c60b7c60eeb8cec2"
        "a56366cfab8b39e9c71e3b37535c7027"
    ),
    Path("scripts/ci/export_admin_dependency_cache.sh"): (
        "fabcdc2245c537c2fd56e88b6e0aced77"
        "d5c26234fc74d7d934b11ecda8d860c"
    ),
    Path("scripts/ci/import_admin_dependency_cache.sh"): (
        "c4986143d5897140f72ad6835b44f7fc9"
        "89830a30341cb4e3f5718fced3ca777"
    ),
    Path("tools/verify_admin_dependency_cache_transient_state_v5.py"): (
        "4b81fb25c259a5a5c8a3f115b6d45396"
        "98280c744535c5ff002b658dbec9cb5f"
    ),
    Path("scripts/ci/cleanup_admin_dependency_cache_v5.sh"): (
        "a291c7242a0ac343faca19a921b2ad05"
        "6d212aa2ef175a6b58b33ef028bbf239"
    ),
    Path("scripts/ci/download_admin_dependency_cache_artifact.sh"): (
        "66abfd513be7aa81946072493e1472030"
        "a8acccbf7a3e2d4dc461c94712e2a92"
    ),
    Path("tools/verify_admin_dependency_cache_provider_download.py"): (
        "ca05697d12b8c02b183b1c611c33781d"
        "63641c5369bc54b2508a538591a0986b"
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


def verify_frozen_git() -> list[str]:
    errors: list[str] = []
    request_name = REQUEST_PATH.as_posix()
    try:
        control_parents = _git_text(
            "rev-list", "--parents", "-n", "1", CONTROL_COMMIT
        ).split()
        if control_parents != [CONTROL_COMMIT, DIRECT_PARENT_COMMIT]:
            errors.append("V9 controller parent binding changed")
        receipt_parents = _git_text(
            "rev-list", "--parents", "-n", "1", DIRECT_PARENT_COMMIT
        ).split()
        if receipt_parents != [DIRECT_PARENT_COMMIT, INERT_CHECKPOINT_COMMIT]:
            errors.append("V9 inert remote receipt parent binding changed")

        changed = _git_text(
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-status",
            "-r",
            DIRECT_PARENT_COMMIT,
            CONTROL_COMMIT,
        )
        if changed != f"A\t{request_name}":
            errors.append("V9 controller is no longer request-only")
        additions_text = _git_text(
            "log", "--all", "--diff-filter=A", "--format=%H", "--", request_name
        )
        additions = additions_text.splitlines() if additions_text else []
        if additions != [CONTROL_COMMIT]:
            errors.append("V9 request addition history changed")

        control_request = _git_bytes("show", f"{CONTROL_COMMIT}:{request_name}")
        if sha256_bytes(control_request) != REQUEST_SHA256:
            errors.append("V9 control request bytes changed")
        if _git_bytes("show", f"HEAD:{request_name}") != control_request:
            errors.append("V9 request is not retained byte-exact at HEAD")
        if not _regular_blob_mode("HEAD", REQUEST_PATH):
            errors.append("V9 request retained mode changed")

        for commit, label in (
            (DIRECT_PARENT_COMMIT, "parent"),
            (CONTROL_COMMIT, "control"),
        ):
            for frozen_path, expected_sha256 in FROZEN_PATHS.items():
                historical = _git_bytes(
                    "show", f"{commit}:{frozen_path.as_posix()}"
                )
                if sha256_bytes(historical) != expected_sha256:
                    errors.append(
                        f"V9 {label} tree file hash changed: "
                        f"{frozen_path.as_posix()}"
                    )
                if not _regular_blob_mode(commit, frozen_path):
                    errors.append(
                        f"V9 {label} tree file mode changed: "
                        f"{frozen_path.as_posix()}"
                    )

        for frozen_path, expected_sha256 in FROZEN_PATHS.items():
            local_path = ROOT / frozen_path
            if sha256_bytes(local_path.read_bytes()) != expected_sha256:
                errors.append(f"frozen V9 file hash changed: {frozen_path}")
            if not stat.S_ISREG(local_path.stat().st_mode):
                errors.append(f"frozen V9 file type changed: {frozen_path}")
            head_bytes = _git_bytes("show", f"HEAD:{frozen_path.as_posix()}")
            if sha256_bytes(head_bytes) != expected_sha256:
                errors.append(f"V9 HEAD frozen file hash changed: {frozen_path}")
            if not _regular_blob_mode("HEAD", frozen_path):
                errors.append(f"V9 HEAD frozen file mode changed: {frozen_path}")

        template_bytes = _git_bytes(
            "show", f"{DIRECT_PARENT_COMMIT}:{TEMPLATE_PATH.as_posix()}"
        )
        if template_bytes.count(b"__DIRECT_PARENT_COMMIT__") != 1:
            errors.append("V9 frozen template placeholder count changed")
        expected_request = template_bytes.replace(
            b"__DIRECT_PARENT_COMMIT__",
            DIRECT_PARENT_COMMIT.encode("ascii"),
        )
        if control_request != expected_request:
            errors.append("V9 control request differs from its frozen template")
        request = json.loads(
            control_request.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
            parse_float=parse_float,
        )
        if request.get("plan_checkpoint_commit") != DIRECT_PARENT_COMMIT:
            errors.append("V9 request embedded parent changed")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        errors.append(f"cannot verify frozen V9 Git state: {exc}")
    return errors


def verify(
    payload: dict[str, Any],
    *,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []
    if semantic_sha256(payload) != EXPECTED_SEMANTIC_SHA256:
        errors.append("V9 failure evidence semantics changed")
    try:
        if sha256_bytes(EVIDENCE_PATH.read_bytes()) != EVIDENCE_FILE_SHA256:
            errors.append("V9 failure evidence file bytes changed")
    except OSError as exc:
        errors.append(f"cannot load frozen V9 evidence closure: {exc}")
    if verify_git_state:
        errors.extend(verify_frozen_git())

    failure = payload.get("failure")
    for name in ("producer_diagnostic", "import_diagnostic"):
        diagnostic = failure.get(name) if isinstance(failure, dict) else None
        if diagnostic_payload_sha256(diagnostic) != (
            diagnostic.get("diagnostic_sha256")
            if isinstance(diagnostic, dict)
            else None
        ):
            errors.append(f"V9 {name.replace('_', ' ')} hash does not derive")
    cleanup = payload.get("cleanup")
    if cleanup_compact_payload_sha256(cleanup) != (
        cleanup.get("compact_log_payload_sha256")
        if isinstance(cleanup, dict)
        else None
    ):
        errors.append("V9 cleanup compact payload hash does not derive")
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
    print("admin_dependency_cache_v9_failure_evidence=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
