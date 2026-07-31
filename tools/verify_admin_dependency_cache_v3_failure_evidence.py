#!/usr/bin/env python3
"""Verify the Secret-free terminal receipt for cache-export V3 attempt 1."""

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
    / "admin-dependency-cache-v3-attempt1-failed-20260731.json"
)
DEFAULT_FLAGS = ["--allow-insecure-entitlement=network.host"]


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
            "runner",
            "step_outcome",
            "failure",
            "cleanup",
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
        == "noteai.admin-dependency-cache-attempt-failure.v2",
        "schema changed",
    )
    require(
        payload.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "task changed",
    )
    require(
        payload.get("classification")
        == "V3_TRIGGERED_ATTEMPT1_FAILED_CLOSED_ARTIFACT0",
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
            "plan_checkpoint_commit": "72f590ddb788bd2268fffdc7c27163188751dd81",
            "control_commit": "443bb1e534f98232541f44b744d753bfa7c09168",
            "request_path": (
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v3.json"
            ),
            "request_sha256": (
                "7c7eff9d0cf7c20009f57237bc50f2b"
                "06b3c6f3f28ec1401eefeeff1c91583b9"
            ),
            "template_path": (
                "deploy/production/plans/"
                "admin-dependency-cache-export-request-v3.json"
            ),
            "template_sha256": (
                "2ddca5c392f21cfa3b623197d07c2f8"
                "a983715a95ec58042aa0eece8930cd2f3"
            ),
            "workflow_path": (
                ".github/workflows/admin-dependency-cache-export-v3.yml"
            ),
            "workflow_sha256": (
                "60b48606e98ce9ea8b81b6afcc910701"
                "798cd3dff307661e11ff383dbb2eed39"
            ),
            "plan_verifier_path": (
                "tools/verify_admin_dependency_cache_export_plan_v3.py"
            ),
            "plan_verifier_sha256": (
                "f1de65d37f7bac35fcf1df7ac490a69"
                "df0057bef4d0800fbbdaa0ce0b4c85924"
            ),
            "transient_verifier_path": (
                "tools/verify_admin_dependency_cache_transient_state_v3.py"
            ),
            "transient_verifier_sha256": (
                "da19c4908fc73ee7bdd74342cf0c626a"
                "2db79299672ba5aa0511a7c9d92baae0"
            ),
            "cleanup_helper_path": (
                "scripts/ci/cleanup_admin_dependency_cache_v3.sh"
            ),
            "cleanup_helper_sha256": (
                "b6115cc641c563f90236bcbdea432e0c"
                "a18ff9908834f663c6eeadd27ffa3101"
            ),
        },
        "Git binding changed",
    )
    require(
        payload.get("github_run")
        == {
            "run_id": 30596283342,
            "job_id": 91049234229,
            "run_number": 1,
            "attempt": 1,
            "event": "push",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-07-31T01:25:07Z",
            "updated_at": "2026-07-31T01:25:39Z",
            "head_sha": "443bb1e534f98232541f44b744d753bfa7c09168",
            "workflow_run_count_for_branch": 1,
            "rerun_count": 0,
            "rerun_authorized": False,
        },
        "GitHub run outcome changed",
    )
    require(
        payload.get("runner")
        == {
            "operating_system": "Ubuntu 24.04.4 LTS",
            "image": "ubuntu-24.04",
            "image_version": "20260720.247.2",
            "included_software_ref": (
                "actions/runner-images/ubuntu24/20260720.247/"
                "images/ubuntu/Ubuntu2404-Readme.md"
            ),
            "docker_buildx_version": "0.35.0",
            "docker_client_version": "28.0.4",
            "docker_server_version": "28.0.4",
            "buildx_source_tag": "v0.35.0",
            "buildx_tag_object": "151a92201622eeb80e19bdd9681af2266772875f",
            "buildx_source_commit": "a319e5b15052cf6557ceb666eb8ff6e32380b782",
            "version_basis": (
                "exact runner included-software manifest referenced by the job log"
            ),
        },
        "runner/source binding changed",
    )
    require(
        payload.get("step_outcome")
        == {
            "controller_checkout": "success",
            "exact_request_resolution": "success",
            "release_checkout": "success",
            "immutable_source_verification": "success",
            "isolated_builder_creation": "failure",
            "dependency_cache_export": "skipped",
            "fresh_consumer_portability": "skipped",
            "transient_docker_cleanup": "failure",
            "final_bundle_validation": "skipped",
            "artifact_upload": "skipped",
            "provider_identity_confirmation": "skipped",
            "runner_local_bundle_cleanup": "success",
        },
        "step outcome changed",
    )
    require(
        payload.get("failure")
        == {
            "primary_message": (
                "FAIL: Buildx state instances/"
                "noteai-admin-cache-v3-consumer-30596283342.flags changed"
            ),
            "primary_exit_code": 1,
            "primary_boundary": (
                "after both pinned BuildKit builders bootstrapped "
                "and before cache export"
            ),
            "actual_flags_payload_retained": False,
            "source_proven_incompatibility": {
                "v3_assertion": 'node["Flags"] in (None, [])',
                "buildx_source_path": "builder/builder.go",
                "buildx_source_lines": "650-688",
                "buildx_test_path": "builder/builder_test.go",
                "buildx_test_lines": "64-75",
                "command_driver": "docker-container",
                "explicit_buildkitd_flags": [],
                "source_proven_default_flags": DEFAULT_FLAGS,
                "additional_flags_authorized": False,
                "security_insecure_authorized": False,
                "build_network_host_requested": False,
                "classification_basis": (
                    "Buildx 0.35.0 deterministically appends the one "
                    "network.host daemon entitlement for an isolated container "
                    "driver when no entitlement or config is supplied; the "
                    "frozen build commands do not request that entitlement"
                ),
            },
            "remediation_contract": {
                "accept_exact_default_flags_only": DEFAULT_FLAGS,
                "reject_empty_flags_after_builder_creation": True,
                "reject_security_insecure": True,
                "reject_additional_or_reordered_flags": True,
                "require_exact_buildx_version_and_commit": True,
                "require_no_build_network_host_request": True,
            },
        },
        "failure detail changed",
    )
    require(
        payload.get("cleanup")
        == {
            "step_conclusion": "failure",
            "initial_transient_validation": "same exact flags failure",
            "builder_removal_attempted": True,
            "post_removal_transient_validation": "PASS",
            "docker_parity_checks_attempted": True,
            "task_owned_root_removal_attempted": True,
            "task_owned_root_removal_error_observed": False,
            "final_failure_message": (
                "Admin dependency-cache cleanup failed closed"
            ),
            "final_failure_reason": (
                "aggregate retained the pre-removal validation failure"
            ),
            "ephemeral_runner_completed": True,
        },
        "cleanup outcome changed",
    )
    require(
        payload.get("provider_artifact")
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
    require(
        payload.get("conditional_builder_and_publication")
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
    expected_ci = []
    for run_id, job_id, event in (
        (30596283325, 91049234143, "push"),
        (30596285651, 91049240950, "pull_request"),
    ):
        expected_ci.append(
            {
                "run_id": run_id,
                "job_id": job_id,
                "event": event,
                "head_sha": "443bb1e534f98232541f44b744d753bfa7c09168",
                "status": "completed",
                "conclusion": "failure",
                "failed_step": "Unit tests",
                "test_count": 1212,
                "failure_count": 1,
                "skip_count": 28,
                "sole_failure": (
                    "test_admin_dependency_cache_export_plan_v3."
                    "AdminDependencyCacheExportPlanV3Tests."
                    "test_exact_inert_v3_plan_passes"
                ),
                "failure_classification": (
                    "activation-state expectation remained "
                    "PREPARED_V3_NOT_TRIGGERED after the exact request-only "
                    "activation changed state to V3_ARMED_OR_TRIGGERED_EXACT"
                ),
            }
        )
    require(payload.get("ordinary_ci") == expected_ci, "ordinary CI outcome changed")
    require(
        payload.get("authorization_outcome")
        == {
            "github_v3_one_shot_run_consumed": True,
            "artifact_download_transfer_not_consumed": True,
            "conditional_builder_publication_not_consumed": True,
            "v3_attempt_may_not_be_rerun": True,
            "new_append_only_versioned_request_required": True,
            "bounded_cto_recovery_authority_active": True,
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
    print("admin_dependency_cache_v3_failure_evidence=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
