#!/usr/bin/env python3
"""Verify the Secret-free terminal receipt for cache-export V2 attempt 1."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "evidence"
    / "admin-dependency-cache-v2-attempt1-failed-20260731.json"
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


def verify(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(
        set(payload)
        == {
            "schema_version",
            "task",
            "classification",
            "repository",
            "branch",
            "git",
            "github_run",
            "step_outcome",
            "failure",
            "provider_artifact",
            "conditional_builder_and_publication",
            "ordinary_ci",
            "authorization_outcome",
            "readiness",
        },
        "evidence keys changed",
    )
    require(
        payload.get("schema_version")
        == "noteai.admin-dependency-cache-attempt-failure.v1",
        "schema changed",
    )
    require(
        payload.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "task changed",
    )
    require(
        payload.get("classification") == "TRIGGERED_ATTEMPT1_FAILED_ARTIFACT0",
        "classification changed",
    )
    require(payload.get("repository") == "iamyusen1314/noteai", "repository changed")
    require(
        payload.get("branch") == "codex/quality-stabilization-real-chain",
        "branch changed",
    )
    require(
        payload.get("git")
        == {
            "plan_checkpoint_commit": "2306f4e1c446e33f4bf9bcab402c04d1016941d7",
            "control_commit": "83b89262a33aed2cfa9fd623f232a66824398c2e",
            "request_path": (
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v2.json"
            ),
            "request_sha256": (
                "28e684e752d2991afb835de74fea558cb"
                "23f3eaa5d7e9ec230931a4a106fa75c"
            ),
            "workflow_path": (
                ".github/workflows/admin-dependency-cache-export.yml"
            ),
            "workflow_sha256": (
                "d01bf03d4725bb82c2ff34d35aeb0379"
                "a6987200278321a436d77d0b7fcd4870"
            ),
        },
        "Git binding changed",
    )
    run = payload.get("github_run") or {}
    require(
        run
        == {
            "run_id": 30591103183,
            "job_id": 91033410635,
            "attempt": 1,
            "event": "push",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-07-30T23:37:44Z",
            "updated_at": "2026-07-30T23:39:14Z",
            "head_sha": "83b89262a33aed2cfa9fd623f232a66824398c2e",
            "rerun_count": 0,
            "rerun_authorized": False,
        },
        "GitHub run outcome changed",
    )
    require(
        payload.get("step_outcome")
        == {
            "controller_checkout": "success",
            "exact_request_resolution": "success",
            "release_checkout": "success",
            "immutable_source_verification": "success",
            "isolated_builder_creation": "success",
            "dependency_cache_export": "failure",
            "fresh_consumer_portability": "skipped",
            "transient_docker_cleanup": "failure",
            "final_bundle_validation": "skipped",
            "artifact_upload": "skipped",
            "provider_identity_confirmation": "skipped",
        },
        "step outcome changed",
    )
    require(
        payload.get("failure")
        == {
            "primary_message": "FAIL: BuildKit platform changed",
            "primary_exit_code": 1,
            "primary_boundary": (
                "post-build local evidence validation before portability or upload"
            ),
            "actual_metadata_file_retained": False,
            "source_proven_incompatibility": {
                "buildkit_version": "v0.31.2",
                "buildkit_tag_object": (
                    "37aba93910a245e9196ccf67f4afb55f18b39f81"
                ),
                "buildkit_commit": (
                    "e42e1bfd389af7203238cce77b1f7dad447285e9"
                ),
                "builder_platform_semantics": (
                    "current build machine, not build result"
                ),
                "dockerfile_frontend_version": "1.25.0",
                "v2_assertion_compared_entire_environment_object": True,
            },
            "cleanup_message": "rmdir: Directory not empty",
            "cleanup_exit_code": 1,
            "cleanup_boundary": (
                "task-owned empty Docker config also held default Buildx state"
            ),
        },
        "failure detail changed",
    )
    artifact = payload.get("provider_artifact") or {}
    require(
        artifact
        == {
            "api_total_count": 0,
            "artifacts": [],
            "upload_count": 0,
            "provider_identity_confirmation_count": 0,
            "authenticated_download_count": 0,
            "cross_provider_transfer_count": 0,
        },
        "provider artifact outcome changed",
    )
    external = payload.get("conditional_builder_and_publication") or {}
    require(
        external
        == {
            "cache_acceptance_passed": False,
            "builder_authorization_activated": False,
            "new_builder_start_count": 0,
            "admin_acr_repository_read_count": 0,
            "admin_acr_token_issuance_count": 0,
            "admin_acr_login_count": 0,
            "admin_acr_push_count": 0,
            "admin_acr_manifest_readback_count": 0,
            "production_service_mutation_count": 0,
            "database_connection_count": 0,
            "database_transaction_count": 0,
            "database_write_count": 0,
            "public_traffic_mutation_count": 0,
        },
        "conditional builder/publication outcome changed",
    )
    require(
        payload.get("ordinary_ci")
        == [
            {
                "run_id": 30591103151,
                "event": "push",
                "head_sha": "83b89262a33aed2cfa9fd623f232a66824398c2e",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "run_id": 30591105105,
                "event": "pull_request",
                "head_sha": "83b89262a33aed2cfa9fd623f232a66824398c2e",
                "status": "completed",
                "conclusion": "success",
            },
        ],
        "ordinary CI outcome changed",
    )
    require(
        payload.get("authorization_outcome")
        == {
            "github_one_shot_run_consumed": True,
            "artifact_download_transfer_not_consumed": True,
            "conditional_builder_publication_not_consumed": True,
            "v2_attempt_may_not_be_rerun": True,
            "new_versioned_request_and_new_run_authorization_required": True,
        },
        "authorization outcome changed",
    )
    require(
        payload.get("readiness")
        == {
            "internal_verified": 19,
            "internal_total": 29,
            "public_verified": 19,
            "public_total": 38,
            "credit_added": False,
            "last_credited_item": "api_f_current_release",
        },
        "readiness outcome changed",
    )
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
    print("admin_dependency_cache_v2_failure_evidence=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
