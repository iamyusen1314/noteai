#!/usr/bin/env python3
"""Verify the Secret-free failed Admin private-publication attempt receipt."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "evidence"
    / "production-admin-private-publication-attempt-blocked-clean-20260731.json"
)
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
CONTROLLER_COMMIT = "e7039a3fe73b539325593cf1ba78dcd4a9949910"
TAKEOVER_CHECKPOINT = "1c7c9c51f74664c1120d77ae6aa720202cd71945"
ATTEMPT_ID = "PROD-FIRST-LAUNCH-ADMIN-PRIVATE-PUBLICATION-ATTEMPT-20260731"
EXPECTED_CANONICAL_SHA256 = (
    "2a6d8e2f70d61efd4597e6d76cc5c3939d86e0047b75130fbd88f194cafe13d7"
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(
        r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)"
        r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"
    ),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://",
        re.IGNORECASE,
    ),
    re.compile(r"\b[\w.-]+\.(?:aliyuncs|amazonaws)\.com\b", re.IGNORECASE),
    re.compile(
        r"\b(?:i|vpc|vsw|sg|eip|slb|alb|rds|cr|acr)-"
        r"[A-Za-z0-9][A-Za-z0-9-]{5,}\b"
    ),
    re.compile(
        r"\b(?:password|passwd|secret|token|access[_-]?key)"
        r"\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
)


def reject_duplicate_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_evidence(path: Path = EVIDENCE_PATH) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_object_pairs,
    )
    if not isinstance(payload, dict):
        raise ValueError("attempt evidence root must be an object")
    return payload


def canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def iter_string_values(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_string_values(child)
    elif isinstance(value, str):
        yield value


def validate_evidence(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(
        canonical_sha256(payload) == EXPECTED_CANONICAL_SHA256,
        "canonical evidence hash mismatch",
    )
    for value in iter_string_values(payload):
        if any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
            errors.append("receipt contains a forbidden sensitive value")
            break

    require(payload.get("manifest_version") == 1, "invalid manifest version")
    require(
        payload.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "invalid task",
    )
    require(payload.get("attempt_id") == ATTEMPT_ID, "invalid attempt id")
    require(
        payload.get("outcome") == "BLOCKED_BEFORE_BUILD_COMPLETION",
        "invalid outcome",
    )
    require(
        payload.get("application_revision") == RELEASE_COMMIT,
        "invalid application revision",
    )
    require(
        payload.get("controller_revision") == CONTROLLER_COMMIT,
        "invalid controller revision",
    )
    require(
        payload.get("takeover_checkpoint") == TAKEOVER_CHECKPOINT,
        "invalid takeover checkpoint",
    )

    authorization = payload.get("authorization") or {}
    require(authorization.get("existing_builder_only") is True, "builder scope drift")
    require(authorization.get("builder_architecture") == "x86_64", "architecture drift")
    require(
        authorization.get("builder_capacity") == {"vcpu": 4, "memory_gib": 16},
        "builder capacity drift",
    )
    require(authorization.get("maximum_runtime_seconds") == 7200, "runtime cap drift")
    require(
        authorization.get("authorization_started_at")
        == "2026-07-30T22:59:08+08:00",
        "authorization start drift",
    )
    require(
        authorization.get("authorization_deadline")
        == "2026-07-31T00:59:08+08:00",
        "authorization deadline drift",
    )
    require(
        authorization.get("admin_private_publication_count_limit") == 1,
        "publication count limit drift",
    )
    require(
        authorization.get("full_cleanup_required") is True,
        "full cleanup requirement drift",
    )
    for key in (
        "new_paid_resources_authorized",
        "production_service_mutation_authorized",
        "database_authorized",
        "public_traffic_authorized",
    ):
        require(authorization.get(key) is False, f"authorization expanded: {key}")
    try:
        authorization_started = datetime.fromisoformat(
            authorization["authorization_started_at"]
        )
        authorization_deadline = datetime.fromisoformat(
            authorization["authorization_deadline"]
        )
        require(
            int((authorization_deadline - authorization_started).total_seconds())
            == authorization["maximum_runtime_seconds"],
            "authorization window does not match runtime cap",
        )
    except (KeyError, TypeError, ValueError):
        errors.append("invalid authorization timestamp")

    preflight = payload.get("fresh_preflight") or {}
    require(preflight.get("native_x86_64") is True, "native preflight missing")
    require(preflight.get("docker_active") is True, "Docker preflight missing")
    for key in (
        "running_containers",
        "docker_auth_entries",
        "build_or_push_processes",
        "database_connections",
        "historical_source_other_changes",
    ):
        require(preflight.get(key) == 0, f"preflight not clean: {key}")
    require(
        preflight.get("exact_release_checked_out_in_fresh_task") is True,
        "exact release checkout missing",
    )
    require(preflight.get("fresh_task_root_only") is True, "fresh task not root-only")
    require(preflight.get("available_memory_mib") == 15028, "memory baseline drift")
    require(preflight.get("available_disk_mib") == 83010, "disk baseline drift")
    require(
        preflight.get("historical_source_repositories") == 2,
        "historical repository count drift",
    )
    require(
        preflight.get("historical_source_revision")
        == "b55f11882100e9ef919522540729e366a511f88f",
        "historical revision drift",
    )
    require(
        preflight.get("historical_source_expected_lfs_materializations_per_repository")
        == 3,
        "historical LFS count drift",
    )
    require(
        preflight.get("exact_upstream_checkpoint_reachable_from_both_repositories")
        is True,
        "upstream checkpoint reachability drift",
    )
    require(
        preflight.get("upstream_urls_same_and_credential_free_https") is True,
        "upstream origin safety drift",
    )
    require(
        preflight.get("exact_release_tree_sha")
        == "38e574e56406ba3380acb78edbe784508cc537cd",
        "release tree drift",
    )
    require(preflight.get("exact_model_artifact_count") == 3, "model count drift")
    require(
        preflight.get("exact_model_artifact_aggregate_sha256")
        == "7ff62a16da80f03fd405d114fcaaa3c3c93e5c2b379514cb689b234cf6298ca7",
        "model aggregate drift",
    )
    for key in (
        "historical_acceptance_sha256_match_count",
        "historical_manifest_sha256_match_count",
        "historical_publication_sha256sums_match_count",
    ):
        require(preflight.get(key) == 1, f"historical hash match drift: {key}")

    fixed = payload.get("fixed_build_inputs") or {}
    require(fixed.get("canonical_build_pull_preserved") is True, "canonical pull weakened")
    require(fixed.get("canonical_script_bytes_preserved") is True, "canonical script changed")
    require(fixed.get("trivy_database_fresh_at_gate") is True, "scanner database stale")
    require(fixed.get("trivy_version") == "0.72.0", "Trivy version drift")
    require(fixed.get("syft_version") == "1.49.0", "Syft version drift")
    require(
        fixed.get("trivy_updated_age_seconds_at_gate") == 51425,
        "Trivy update age drift",
    )
    require(
        fixed.get("trivy_downloaded_age_seconds_at_gate") == 51027,
        "Trivy download age drift",
    )
    require(
        0 <= fixed.get("trivy_updated_age_seconds_at_gate", 86400) < 86400,
        "Trivy database update is not fresh",
    )
    require(
        fixed.get("trivy_next_update_seconds_at_gate") == 34975,
        "Trivy next-update window drift",
    )
    require(
        fixed.get("restricted_trivy_shim_negative_results") == [64, 1],
        "restricted Trivy negative checks drift",
    )
    for key in (
        "canonical_script_sha256",
        "admin_only_script_sha256",
        "trivy_database_sha256",
        "trivy_metadata_sha256",
        "restricted_trivy_shim_sha256",
        "restricted_docker_wrapper_sha256",
    ):
        value = fixed.get(key)
        require(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            f"invalid fixed hash: {key}",
        )

    attempts = payload.get("attempts")
    require(isinstance(attempts, list) and len(attempts) == 2, "attempt count drift")
    if isinstance(attempts, list) and len(attempts) == 2:
        first, second = attempts
        require(first.get("attempt") == 1, "first attempt order drift")
        require(first.get("exit_code") == 1, "first attempt exit drift")
        require(first.get("duration_seconds") == 61, "first duration drift")
        require(first.get("stage") == "python_base_index_inspect", "first stage drift")
        require(
            first.get("classification") == "PRE_BUILD_PUBLIC_REGISTRY_TIMEOUT",
            "first attempt classification drift",
        )
        require(first.get("local_image_created") is False, "first attempt image drift")
        require(first.get("trivy_call_count") == 0, "first attempt scan drift")
        require(
            first.get("log_sha256")
            == "25cc1dcded2d91a0397ff443b39891b1a09d3fab511904c927092d2292a73762",
            "first log hash drift",
        )
        require(first.get("log_bytes") == 249, "first log size drift")
        require(first.get("partial_evidence_file_count") == 1, "first partial count drift")
        require(second.get("attempt") == 2, "second attempt order drift")
        require(second.get("exit_code") == 124, "second attempt exit drift")
        require(second.get("duration_seconds") == 1800, "second timeout drift")
        require(
            second.get("stage") == "admin_runtime_python_dependency_install",
            "second stage drift",
        )
        require(
            second.get("classification") == "BOUNDED_BUILD_TIMEOUT",
            "second attempt classification drift",
        )
        require(
            second.get("base_index_call_order") == ["python", "node"],
            "base-index call order drift",
        )
        require(second.get("local_image_created") is False, "second attempt image drift")
        require(second.get("trivy_call_count") == 0, "second attempt scan drift")
        require(
            second.get("log_sha256")
            == "f46e64660695845285913155caef3f51d7a3b88b23b846a5f50dd321233a3722",
            "second log hash drift",
        )
        require(second.get("log_bytes") == 8350, "second log size drift")
        require(second.get("partial_evidence_file_count") == 2, "second partial count drift")
        require(
            second.get("partial_evidence_sha256")
            == {
                "node-base-index.json": (
                    "8fc034c9f2bbccb406ceaef6802be9a8921c17bc2109feccfcc33b901a56c8bc"
                ),
                "python-base-index.json": (
                    "2cbba3aeca891b77c06479ae266614557b6bfef925df37472d4c690b878c587d"
                ),
            },
            "second partial evidence hashes drift",
        )
        for attempt in attempts:
            require(attempt.get("command_invocations") == 1, "invocation count drift")
            require(attempt.get("automatic_retry_count") == 0, "automatic retry drift")
            require(attempt.get("manual_retry_count") == 0, "manual retry drift")
            require(attempt.get("registry_login_count") == 0, "Registry login drift")
            require(attempt.get("registry_push_count") == 0, "Registry push drift")
            require(
                attempt.get("database_connection_count") == 0,
                "database connection drift",
            )
            require(attempt.get("service_mutation_count") == 0, "service mutation drift")

    publication = payload.get("publication") or {}
    for key in (
        "private_repository_read_count",
        "target_tag_read_count",
        "registry_token_count",
        "registry_login_count",
        "registry_push_count",
        "manifest_readback_count",
        "control_plane_digest_readback_count",
    ):
        require(publication.get(key) == 0, f"publication activity drift: {key}")
    require(publication.get("stage_a_accepted") is False, "Stage A falsely accepted")
    require(publication.get("registry_digest") is None, "Registry digest must remain null")
    for key in (
        "temporary_publisher_created",
        "builder_private_registry_link_created",
        "production_private_registry_link_changed",
        "public_registry_endpoint_changed",
    ):
        require(publication.get(key) is False, f"publication control changed: {key}")

    impact = payload.get("production_impact") or {}
    for key in ("api_c_changed", "api_f_changed", "admin_changed"):
        require(impact.get(key) is False, f"production peer changed: {key}")
    for key in (
        "database_connections",
        "database_transactions",
        "database_writes",
        "service_restarts",
        "provider_calls",
        "public_traffic_changes",
    ):
        require(impact.get(key) == 0, f"production impact drift: {key}")

    cleanup = payload.get("cleanup") or {}
    for key in (
        "running_containers",
        "task_containers",
        "build_or_push_processes",
        "database_connections",
        "docker_auth_entries",
        "retained_failure_links",
        "retained_failure_special_files",
        "retained_failure_unsafe_modes",
        "retained_failure_credential_pattern_matches",
    ):
        require(cleanup.get(key) == 0, f"cleanup not zero: {key}")
    for key in (
        "target_local_image_present",
        "temporary_source_present",
        "temporary_tools_present",
        "temporary_scanner_cache_present",
        "temporary_wrappers_present",
        "temporary_build_environment_present",
        "temporary_docker_config_present",
    ):
        require(cleanup.get(key) is False, f"temporary residue remains: {key}")
    require(
        cleanup.get("temporary_task_paths_removed")
        == [
            "source",
            "tools",
            "scanner_cache",
            "binary_and_wrapper_directory",
            "base_index_cache",
            "docker_config",
            "build_environment",
            "admin_script",
        ],
        "temporary path cleanup drift",
    )
    require(cleanup.get("retained_failure_roots") == 2, "retained root drift")
    require(
        cleanup.get("retained_failure_directory_count_total") == 5,
        "retained directory count drift",
    )
    require(cleanup.get("retained_failure_files") == 6, "retained file drift")
    require(
        cleanup.get("retained_failure_roots_root_only") is True,
        "retained failure roots not root-only",
    )
    require(cleanup.get("builder_stop_mode") == "saving", "stop mode drift")
    require(cleanup.get("builder_stopped") is True, "builder not stopped")
    require(
        cleanup.get("builder_stopped_before_authorization_deadline") is True,
        "builder runtime cap exceeded",
    )
    require(
        cleanup.get("builder_stop_observed_before")
        == "2026-07-31T00:35:46+08:00",
        "builder stop timestamp drift",
    )
    try:
        stop_observed = datetime.fromisoformat(cleanup["builder_stop_observed_before"])
        authorization_deadline = datetime.fromisoformat(
            authorization["authorization_deadline"]
        )
        require(
            stop_observed < authorization_deadline,
            "builder stop timestamp exceeded authorization deadline",
        )
    except (KeyError, TypeError, ValueError):
        errors.append("invalid builder stop timestamp")

    decision = payload.get("decision") or {}
    for key in (
        "publication_verified",
        "deployment_authorized",
        "canary_authorized",
        "readiness_credit_awarded",
    ):
        require(decision.get(key) is False, f"decision falsely advanced: {key}")
    require(decision.get("readiness_status") == "UNVERIFIED", "readiness status drift")
    require(decision.get("internal_readiness") == "19/29", "internal count drift")
    require(decision.get("public_readiness") == "19/38", "public count drift")

    return errors


def main() -> int:
    try:
        payload = load_evidence()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: cannot load Admin publication attempt evidence: {exc}")
        return 1
    errors = validate_evidence(payload)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS: bounded Admin private-publication attempt remained pre-publication, "
        "fully cleaned and stopped with readiness unchanged"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
