#!/usr/bin/env python3
"""Verify the exact API-C b55 runtime deployment evidence.

This verifier is deliberately offline. It binds one Secret-free production
observation to the immutable b55 API image, the ordered execution/rollback
history, independent postchecks, final cleanup and non-regression evidence.
It does not grant public-launch or full-system rollback credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-api-c-current-release-verified-20260730.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
TASK_ID = "PROD-FIRST-LAUNCH-API-C-INTERNAL-001"
RELEASE_REVISION = "b55f11882100e9ef919522540729e366a511f88f"
REGISTRY_CHECKPOINT = "84be4da7b6e9d395f1ed3b33716be6a3465f3c4b"
REGISTRY_MANIFEST_DIGEST = (
    "sha256:612a7e57b8a4226e4c23be6267ee60fb"
    "79677cae9eb46ea1843aed11fc517620"
)
CONFIG_IMAGE_ID = (
    "sha256:dd955f9e736fc00df471f39de6e483ed"
    "0873f5855cc0ffffc074823845fefd53"
)
OLD_MANIFEST_DIGEST = (
    "sha256:17706e1802afc136ac8f9a621d4199a7"
    "f9749da733290e923e42268eff42e0d1"
)
OLD_IMAGE_ID = (
    "sha256:b1983bab928ef93495d8be020030917d4"
    "ae54364234390047c3163af5414fedb"
)
OLD_REVISION = "a635692a899ee02c6905cd694611c14e0da4594a"
OLD_UNIT_SHA256 = (
    "872c44e87b938a2ecb459651953196925e72798fa67f4a904c05409fb350cd25"
)
CANDIDATE_UNIT_SHA256 = (
    "364a5e539b14a83d24ef9c1726ee3e14b988c398206b2711db5613b9e0a1fc77"
)
ADMIN_UNIT_SHA256 = (
    "c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2"
)
ADMIN_IMAGE_ID = (
    "sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f"
)
API_F_UNIT_SHA256 = (
    "32d552e3daba29130677d98927dff1701711763ef63573d5d9c199c99bf44268"
)
EXPECTED_SEMANTIC_SHA256 = (
    "00154ac488ca4e3439b5dfd34ae97d9d895850aeed5eca65690ddcaee57e7559"
)
SHA256_HEX_LENGTH = 64

EXPECTED_MANIFEST_EVIDENCE = [
    {"kind": "git", "ref": RELEASE_REVISION},
    {"kind": "path", "ref": EVIDENCE_REF},
    {
        "kind": "path",
        "ref": "tools/verify_api_c_current_release_evidence.py",
    },
]

EXPECTED_REGISTRY_BUNDLE = [
    (
        "security/vex/b55f118-registry-publication-attestation.json",
        "c27205495011debc49d8f4b7bfa235d36b08de6c2c96c0dc38dbb9d552076325",
    ),
    (
        "security/vex/b55f118-registry-release-evidence.json",
        "fa38b5702639c6644b40dc316248d1526dc6ed657ab9c399add3efd5e03bd56b",
    ),
    (
        "security/vex/b55f118-registry-release.vex.cdx.json",
        "140a20bc65091014a87c7cc63ed1e98aea21c5f3762e43f2374832202df3c75e",
    ),
    (
        "security/vex/b55f118-registry-release-review.json",
        "38385fc03c456d6b09602799dcf325b4def1c99b79c7bc7c3a3bfcb8c08c851b",
    ),
]
EXPECTED_DEPENDENCY_EVIDENCE = [
    (
        "deploy/production/evidence/"
        "production-schema-roles-v5-owner-committed-20260729.json",
        "7096f0475837a4ac68585cdc400db53545e152a43e2f1ec7608bf87809589b7e",
    ),
    (
        "deploy/production/evidence/"
        "production-managed-secret-distribution-verified-20260729.json",
        "3db51116f16fec2514012ddd60f09747ab3b3b0d390de2996902abc47e11a8ab",
    ),
    (
        "deploy/production/evidence/"
        "production-private-storage-runtime-verified-20260729.json",
        "28e4647b07c998154c8caa9767b7b3f709a4cc93e31f1e0b73ca1b40000ecbc7",
    ),
]
EXPECTED_ATTEMPT_IDS = (
    "pull-validator-initial",
    "pull-validator-corrected",
    "canary-generation-1",
    "canary-generation-2",
    "promotion-attempt-1",
    "canary-generation-3",
    "promotion-attempt-2",
    "explicit-managed-restart",
    "postcheck-transport-attempt-0",
    "postcheck-ledger-read",
    "postcheck-runtime-session",
    "precleanup-validator-attempt-1",
    "precleanup-validator-attempt-2",
    "canary-cleanup-attempt-1",
    "canary-cleanup-attempt-2",
    "final-validator-attempt-1",
    "final-validator-attempt-2",
    "final-validator-attempt-3",
)
EXPECTED_ATTEMPT_RESULTS = (
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "PASS",
    "PASS",
    "FAILED",
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "FAILED",
    "FAILED",
    "PASS",
)
ATTEMPT_SUM_FIELDS = (
    "database_connection_count",
    "database_transaction_count",
    "database_write_count",
    "canary_create_count",
    "canary_start_count",
    "canary_restart_count",
    "canary_remove_count",
    "managed_service_restart_count",
    "rollback_service_restart_count",
    "registry_token_issuance_count",
    "registry_login_count",
    "registry_pull_count",
    "automatic_retry_count",
)
REQUIRED_ATTEMPT_FIELDS = {
    "ordinal",
    "attempt_id",
    "phase",
    "result",
    "incident_class",
    "failure_stage_code",
    "service_mutation_started",
    "database_connection_count",
    "database_transaction_count",
    "database_outcome",
    "database_write_count",
    "canary_create_count",
    "canary_start_count",
    "canary_restart_count",
    "canary_remove_count",
    "managed_service_restart_count",
    "rollback_service_restart_count",
    "registry_token_issuance_count",
    "registry_login_count",
    "registry_pull_count",
    "automatic_retry_count",
    "material_correction",
    "rollback_required",
    "rollback_result",
    "retained_state",
    "successor_attempt",
}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evidence root must be an object")
    return payload


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _binding_rows(
    payload: Any,
) -> list[tuple[str, str]]:
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            return []
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            return []
        rows.append((path, digest))
    return rows


def _all_zero(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and bool(payload)
        and all(isinstance(value, int) and value == 0 for value in payload.values())
    )


def _append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _validate_file_bindings(
    rows: Any,
    expected: list[tuple[str, str]],
    *,
    root: Path,
    label: str,
    errors: list[str],
) -> None:
    observed = _binding_rows(rows)
    _append(errors, observed == expected, f"{label} binding mismatch")
    if observed != expected:
        return
    for ref, digest in observed:
        path = Path(ref)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"{label} path escaped repository")
            continue
        target = root / path
        if not target.is_file():
            errors.append(f"{label} file missing: {ref}")
            continue
        if _sha256_path(target) != digest:
            errors.append(f"{label} file hash mismatch: {ref}")


def _validate_attempts(evidence: dict[str, Any], errors: list[str]) -> None:
    attempts = evidence.get("attempt_history")
    if not isinstance(attempts, list):
        errors.append("attempt history missing")
        return
    _append(
        errors,
        tuple(item.get("attempt_id") for item in attempts if isinstance(item, dict))
        == EXPECTED_ATTEMPT_IDS,
        "attempt history order mismatch",
    )
    _append(
        errors,
        tuple(item.get("result") for item in attempts if isinstance(item, dict))
        == EXPECTED_ATTEMPT_RESULTS,
        "attempt result history mismatch",
    )
    _append(
        errors,
        [item.get("ordinal") for item in attempts if isinstance(item, dict)]
        == list(range(1, len(EXPECTED_ATTEMPT_IDS) + 1)),
        "attempt ordinals mismatch",
    )
    if len(attempts) != len(EXPECTED_ATTEMPT_IDS) or not all(
        isinstance(item, dict) for item in attempts
    ):
        errors.append("attempt history shape mismatch")
        return
    expected_successors = [*EXPECTED_ATTEMPT_IDS[1:], None]
    _append(
        errors,
        [item.get("successor_attempt") for item in attempts]
        == expected_successors,
        "attempt successor chain mismatch",
    )
    for item in attempts:
        attempt_id = str(item.get("attempt_id"))
        _append(
            errors,
            set(item) == REQUIRED_ATTEMPT_FIELDS,
            f"{attempt_id}: attempt fields mismatch",
        )
        for field in ATTEMPT_SUM_FIELDS:
            _append(
                errors,
                isinstance(item.get(field), int) and item[field] >= 0,
                f"{attempt_id}: invalid {field}",
            )
        _append(
            errors,
            item.get("automatic_retry_count") == 0,
            f"{attempt_id}: automatic retry forbidden",
        )
        _append(
            errors,
            item.get("database_write_count") == 0,
            f"{attempt_id}: database write forbidden",
        )
        _append(
            errors,
            item.get("canary_restart_count") == 0,
            f"{attempt_id}: canary restart must remain zero",
        )
        _append(
            errors,
            item.get("incident_class") != "CONNECTED_UNKNOWN"
            and item.get("database_outcome") != "UNKNOWN",
            "connected unknown attempt forbidden",
        )
        if item.get("result") == "FAILED" and item.get(
            "service_mutation_started"
        ):
            _append(
                errors,
                item.get("rollback_required") is True
                and item.get("rollback_result") == "PASS"
                and item.get("rollback_service_restart_count") == 1,
                "mutating failed attempt missing successful rollback",
            )
        if item.get("database_transaction_count", 0) > 0:
            _append(
                errors,
                item.get("incident_class") == "CONNECTED_KNOWN"
                and item.get("rollback_required") is True
                and item.get("rollback_result") == "PASS",
                f"{attempt_id}: connected transaction not rolled back",
            )

    sums = {
        field: sum(int(item[field]) for item in attempts)
        for field in ATTEMPT_SUM_FIELDS
    }
    expected_aggregates = {
        "attempt_count": len(attempts),
        "failed_attempt_count": sum(
            item["result"] == "FAILED" for item in attempts
        ),
        "passed_attempt_count": sum(
            item["result"] == "PASS" for item in attempts
        ),
        "connected_unknown_count": sum(
            item["incident_class"] == "CONNECTED_UNKNOWN"
            or item["database_outcome"] == "UNKNOWN"
            for item in attempts
        ),
        "automatic_retry_count": sums["automatic_retry_count"],
        "registry_token_issuance_count": sums[
            "registry_token_issuance_count"
        ],
        "registry_login_count": sums["registry_login_count"],
        "registry_pull_count": sums["registry_pull_count"],
        "database_connection_count": sums["database_connection_count"],
        "explicit_read_only_transaction_count": sums[
            "database_transaction_count"
        ],
        "database_write_count": sums["database_write_count"],
        "canary_create_count": sums["canary_create_count"],
        "canary_start_count": sums["canary_start_count"],
        "canary_restart_count": sums["canary_restart_count"],
        "canary_remove_count": sums["canary_remove_count"],
        "managed_service_restart_count": sums[
            "managed_service_restart_count"
        ],
        "rollback_service_restart_count": sums[
            "rollback_service_restart_count"
        ],
    }
    _append(
        errors,
        evidence.get("attempt_aggregates") == expected_aggregates,
        "attempt aggregate mismatch",
    )


def validate_document(
    evidence: dict[str, Any],
    *,
    root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    _append(errors, evidence.get("schema_version") == 1, "schema version mismatch")
    _append(errors, evidence.get("task_id") == TASK_ID, "task id mismatch")
    _append(errors, evidence.get("status") == "VERIFIED_CLEAN", "status mismatch")
    _append(errors, evidence.get("readiness_credit") == 1, "readiness credit mismatch")
    _append(
        errors,
        isinstance(evidence.get("observed_at_utc"), str)
        and evidence["observed_at_utc"].endswith("Z"),
        "UTC observation timestamp required",
    )

    source = evidence.get("source_binding")
    expected_source_identity = {
        "application_revision": RELEASE_REVISION,
        "registry_checkpoint": REGISTRY_CHECKPOINT,
        "registry_manifest_digest": REGISTRY_MANIFEST_DIGEST,
        "config_image_id": CONFIG_IMAGE_ID,
        "platform": "linux/amd64",
        "runtime_role": "api",
        "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
        "cmd": ["/app/scripts/render_start_api.sh"],
    }
    _append(
        errors,
        isinstance(source, dict)
        and all(source.get(key) == value for key, value in expected_source_identity.items()),
        "source identity mismatch",
    )
    if isinstance(source, dict):
        _validate_file_bindings(
            source.get("registry_bundle"),
            EXPECTED_REGISTRY_BUNDLE,
            root=root,
            label="registry bundle",
            errors=errors,
        )
        _validate_file_bindings(
            source.get("dependency_evidence"),
            EXPECTED_DEPENDENCY_EVIDENCE,
            root=root,
            label="dependency evidence",
            errors=errors,
        )
        _append(
            errors,
            source.get("stage_b_decision_preserved")
            == {
                "deployment_authorization": False,
                "api_c_canary_completed": False,
                "production_exception": False,
                "raw_reports_rewritten": False,
            },
            "Stage B decision preservation mismatch",
        )
        try:
            stage_b = _json(
                root
                / "security"
                / "vex"
                / "b55f118-registry-release-evidence.json"
            )
            decision = stage_b.get("decision") or {}
            _append(
                errors,
                decision.get("deployment_authorization") is False
                and decision.get("api_c_canary_completed") is False
                and decision.get("production_exception") is False
                and decision.get("raw_reports_rewritten") is False,
                "Stage B source decision changed",
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"cannot validate Stage B source decision: {exc}")

    pre = evidence.get("fresh_pre_state") or {}
    api_pre = pre.get("api_c_api") or {}
    _append(
        errors,
        api_pre.get("registry_manifest_digest") == OLD_MANIFEST_DIGEST
        and api_pre.get("config_image_id") == OLD_IMAGE_ID
        and api_pre.get("revision") == OLD_REVISION
        and api_pre.get("unit_sha256") == OLD_UNIT_SHA256
        and api_pre.get("active") is True
        and api_pre.get("enabled") is True
        and api_pre.get("service_result") == "success"
        and api_pre.get("live_http_status") == 200
        and api_pre.get("ready_http_status") == 200
        and api_pre.get("bind_scope") == "loopback"
        and api_pre.get("port") == 8000,
        "fresh API-C pre-state mismatch",
    )
    _validate_attempts(evidence, errors)

    candidate = evidence.get("candidate_unit")
    _append(
        errors,
        candidate
        == {
            "sha256": CANDIDATE_UNIT_SHA256,
            "bytes": 1514,
            "systemd_verify_passed": True,
            "semantic_change_count": 2,
            "image_digest_change_count": 1,
            "storage_env_file_addition_count": 1,
            "other_token_change_count": 0,
        },
        "candidate unit mismatch",
    )
    canary = evidence.get("canary_acceptance") or {}
    _append(
        errors,
        canary.get("generation_count") == 3
        and canary.get("passed_generation_count") == 2
        and canary.get("failed_generation_count") == 1
        and canary.get("automatic_restart_count") == 0
        and canary.get("command_hash_unchanged") is True
        and canary.get("bind_scope") == "loopback"
        and canary.get("port") == 18000
        and canary.get("health_rounds_per_passed_generation") == 3
        and canary.get("live_200_count") == 6
        and canary.get("ready_200_count") == 6
        and canary.get("ready_core_checks_exact") == ["database", "model"]
        and canary.get("database_read_only_verified_generation_count") == 2
        and canary.get("provider_call_count") == 0
        and canary.get("object_write_count") == 0
        and canary.get("database_write_count") == 0
        and canary.get("final_container_count") == 0
        and canary.get("final_listener_count") == 0
        and canary.get("final_data_directory_count") == 0,
        "canary acceptance mismatch",
    )
    aggregates = evidence.get("attempt_aggregates") or {}
    _append(
        errors,
        canary.get("generation_count") == aggregates.get("canary_start_count")
        and aggregates.get("canary_create_count") == 3
        and aggregates.get("canary_remove_count") == 3
        and aggregates.get("canary_restart_count") == 0,
        "canary aggregate mismatch",
    )

    promotion = evidence.get("promotion_and_restart") or {}
    _append(
        errors,
        promotion.get("promotion_attempt_count") == 2
        and promotion.get("failed_promotion_count") == 1
        and promotion.get("successful_promotion_count") == 1
        and promotion.get("rollback_required_count") == 1
        and promotion.get("rollback_pass_count") == 1
        and promotion.get("promotion_restart_count") == 2
        and promotion.get("rollback_restart_count") == 1
        and promotion.get("explicit_restart_count") == 1
        and promotion.get("explicit_restart_automatic_retry_count") == 0
        and promotion.get("container_identity_changed_after_explicit_restart")
        is True
        and promotion.get("pre_explicit_restart_health_rounds") == 3
        and promotion.get("post_explicit_restart_health_rounds") == 3
        and promotion.get("installed_unit_sha256") == CANDIDATE_UNIT_SHA256
        and promotion.get("running_config_image_id") == CONFIG_IMAGE_ID
        and promotion.get("service_active") is True
        and promotion.get("service_enabled") is True
        and promotion.get("service_result") == "success"
        and promotion.get("systemd_automatic_restart_count") == 0
        and promotion.get("docker_automatic_restart_count") == 0,
        "promotion or restart mismatch",
    )

    hardening = evidence.get("runtime_hardening")
    _append(
        errors,
        hardening
        == {
            "effective_user": "999:999",
            "read_only_rootfs": True,
            "privileged": False,
            "cap_drop": ["ALL"],
            "cap_add_count": 0,
            "no_new_privileges": True,
            "device_count": 0,
            "host_pid": False,
            "host_ipc": False,
            "host_network": False,
            "restart_policy": "no",
            "memory_bytes": 1610612736,
            "nano_cpus": 2000000000,
            "pids_limit": 512,
            "bounded_tmpfs_count": 1,
            "tmpfs_noexec_nosuid_nodev": True,
            "writable_mount_destinations": ["/app/model/data"],
            "final_bind_scope": "loopback",
            "final_port": 8000,
            "final_non_loopback_listener_count": 0,
        },
        "runtime hardening mismatch",
    )

    post = evidence.get("independent_postcheck") or {}
    _append(
        errors,
        post.get("separate_read_only_dispatch") is True
        and post.get("precleanup_assertion_family_count") == 15
        and post.get("precleanup_assertion_failure_count") == 0
        and post.get("final_assertion_family_count") == 11
        and post.get("final_assertion_failure_count") == 0
        and post.get("final_api_live_http_status") == 200
        and post.get("final_api_ready_http_status") == 200
        and post.get("final_admin_live_http_status") == 200
        and post.get("final_admin_ready_http_status") == 200
        and post.get("ready_core_checks_exact") == ["database", "model"]
        and post.get("managed_container_count") == 1
        and post.get("installed_unit_matches_candidate") is True
        and post.get("unexpected_unit_delta_count") == 0
        and post.get("rollback_unit_matches_fresh_pre_state") is True
        and post.get("old_image_retained") is True
        and post.get("current_image_identity_exact") is True
        and post.get("current_repo_digest_exact") is True
        and post.get("current_platform_exact") is True
        and post.get("current_command_contract_exact") is True
        and post.get("hardening_exact") is True,
        "independent postcheck mismatch",
    )
    remote_hashes = post.get("remote_evidence_hashes") or {}
    _append(
        errors,
        set(remote_hashes)
        == {
            "precleanup",
            "canary_cleanup",
            "final",
            "runtime_session",
            "ledger_read_rejection",
        }
        and all(
            isinstance(value, str)
            and len(value) == SHA256_HEX_LENGTH
            and all(character in "0123456789abcdef" for character in value)
            for value in remote_hashes.values()
        ),
        "remote evidence hash set mismatch",
    )

    database = evidence.get("database_runtime_postcheck") or {}
    _append(
        errors,
        database.get("runtime_role") == "noteai_app"
        and database.get("default_transaction_read_only") is True
        and database.get("transaction_read_only") is True
        and database.get("xid_unassigned") is True
        and database.get("transaction_tuple_write_count") == 0
        and database.get("transaction_rollback_count") == 2
        and database.get("schema_migrations_select_rejected") is True
        and database.get("schema_migrations_select_error_class")
        == "InsufficientPrivilege"
        and database.get("schema_migration_count_from_verified_checkpoint") == 16
        and database.get("runtime_select_and_sequence_usage_checkpoint_preserved")
        is True
        and database.get("truncate_rejection_checkpoint_preserved") is True
        and database.get("database_write_count") == 0
        and database.get("schema_write_count") == 0
        and database.get("role_write_count") == 0
        and database.get("business_write_count") == 0
        and database.get("business_values_persisted_in_evidence") == 0
        and database.get("connected_unknown_count") == 0,
        "database postcheck mismatch",
    )

    managed = evidence.get("managed_secret_and_storage_non_regression") or {}
    _append(
        errors,
        managed.get("managed_secret_file_count") == 4
        and managed.get("managed_secret_regular_root_0600_count") == 4
        and managed.get("managed_secret_distinct_count") == 4
        and managed.get("managed_secret_missing_count") == 0
        and managed.get("managed_secret_duplicate_key_count") == 0
        and managed.get("managed_secret_rejected_key_count") == 0
        and managed.get("managed_secret_backup_residue_count") == 0
        and managed.get("managed_secret_hashes_unchanged") is True
        and managed.get("lifecycle_tool_hashes_unchanged") is True
        and managed.get("storage_config_file_count") == 1
        and managed.get("storage_config_regular_root_0600_count") == 1
        and managed.get("storage_config_key_count") == 7
        and managed.get("storage_runtime_key_match_count") == 7
        and managed.get("static_access_key_name_count") == 0
        and managed.get("object_write_count") == 0
        and managed.get("object_delete_count") == 0,
        "managed secret or storage non-regression mismatch",
    )

    logs = evidence.get("bounded_log_review") or {}
    _append(
        errors,
        logs.get("raw_log_files_persisted_to_repository") == 0
        and logs.get("startup_failure_hit_count") == 0
        and logs.get("migration_execution_hit_count") == 0
        and logs.get("provider_call_hit_count") == 0
        and logs.get("secret_assignment_hit_count") == 0
        and logs.get("traceback_or_fatal_hit_count") == 0,
        "bounded log review mismatch",
    )

    non_regression = evidence.get("final_non_regression") or {}
    admin = non_regression.get("api_c_admin") or {}
    _append(
        errors,
        admin.get("unit_sha256_before")
        == admin.get("unit_sha256_after")
        == ADMIN_UNIT_SHA256
        and admin.get("config_image_id_before")
        == admin.get("config_image_id_after")
        == ADMIN_IMAGE_ID
        and admin.get("container_identity_unchanged") is True
        and admin.get("restart_count") == 0
        and admin.get("live_http_status") == 200
        and admin.get("ready_http_status") == 200
        and admin.get("bind_scope") == "loopback",
        "Admin non-regression mismatch",
    )
    api_f = non_regression.get("api_f_api") or {}
    _append(
        errors,
        api_f.get("unit_sha256_before")
        == api_f.get("unit_sha256_after")
        == API_F_UNIT_SHA256
        and api_f.get("config_image_id_before")
        == api_f.get("config_image_id_after")
        == OLD_IMAGE_ID
        and api_f.get("revision_before")
        == api_f.get("revision_after")
        == OLD_REVISION
        and api_f.get("container_identity_unchanged") is True
        and api_f.get("restart_count") == 0
        and api_f.get("live_http_status") == 200
        and api_f.get("ready_http_status") == 200
        and api_f.get("bind_scope") == "loopback",
        "API-F non-regression mismatch",
    )
    _append(
        errors,
        non_regression.get("schema_role_mutation_count") == 0
        and non_regression.get("managed_secret_mutation_count") == 0
        and non_regression.get("storage_config_mutation_count") == 0,
        "protected dependency mutation detected",
    )

    control_plane = evidence.get("fresh_control_plane_postcheck")
    _append(
        errors,
        control_plane
        == {
            "observed_at_utc": "2026-07-30T07:48:00Z",
            "running_postgresql_16_instance_count": 1,
            "vpc_instance_count": 1,
            "intranet_instance_count": 1,
            "public_endpoint_count": 0,
            "account_count": 8,
            "super_account_count": 1,
            "task_account_count": 0,
            "available_account_count": 8,
            "successful_automated_full_snapshot_count_in_window": 8,
            "latest_successful_backup_age_hours_floor": 18,
            "production_vpc_alb_count": 0,
            "internet_alb_count": 0,
        },
        "fresh control-plane postcheck mismatch",
    )

    cleanup = evidence.get("cleanup") or {}
    cleanup_zero_keys = (
        "canary_container_count",
        "canary_listener_count",
        "canary_data_directory_count",
        "registry_auth_entry_count",
        "temporary_auth_root_count",
        "registry_token_count",
        "rsa_private_key_count",
        "ciphertext_count",
        "task_script_count",
        "task_process_count",
        "temporary_systemd_unit_count",
        "credential_residue_count",
        "raw_log_files_persisted_to_repository",
    )
    _append(
        errors,
        all(cleanup.get(key) == 0 for key in cleanup_zero_keys)
        and cleanup.get("intentional_root_evidence_retained") is True,
        "final cleanup residue mismatch",
    )

    rollback = evidence.get("rollback_ready") or {}
    _append(
        errors,
        rollback.get("fresh_pre_state_unit_sha256")
        == rollback.get("retained_rollback_unit_sha256")
        == OLD_UNIT_SHA256
        and rollback.get("fresh_pre_state_image_id")
        == rollback.get("retained_old_image_id")
        == OLD_IMAGE_ID
        and rollback.get("unit_bytes_retained") is True
        and rollback.get("image_retained") is True
        and rollback.get("rollback_health_verified_after_failed_promotion")
        is True,
        "rollback-ready evidence mismatch",
    )
    _append(
        errors,
        _all_zero(evidence.get("mutation_counters")),
        "mutation counters must remain zero",
    )
    _append(
        errors,
        evidence.get("readiness")
        == {
            "internal_verified_before": 17,
            "internal_verified_after": 18,
            "internal_total": 29,
            "internal_percentage_after": 62,
            "complete_public_verified_before": 17,
            "complete_public_verified_after": 18,
            "complete_public_total": 38,
            "complete_public_percentage_after": 47,
            "next_task": "PROD-FIRST-LAUNCH-API-F-INTERNAL-001",
            "public_launch_authorized": False,
            "full_system_failure_rollback_verified": False,
        },
        "readiness transition mismatch",
    )
    _append(
        errors,
        _all_zero(evidence.get("secret_free_evidence")),
        "Secret-free evidence counters must remain zero",
    )
    _append(
        errors,
        semantic_sha256(evidence) == EXPECTED_SEMANTIC_SHA256,
        "API-C runtime evidence semantic hash mismatch",
    )
    return errors


def validate_bundle(
    evidence_path: Path | None = None,
    *,
    root: Path = ROOT,
) -> list[str]:
    path = evidence_path or root / EVIDENCE_REF
    try:
        return validate_document(_json(path), root=root)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return [f"cannot load API-C runtime evidence: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    args = parser.parse_args()
    errors = validate_bundle(args.evidence)
    if errors:
        print("api_c_current_release_evidence=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("api_c_current_release_evidence=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
