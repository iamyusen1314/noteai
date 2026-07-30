#!/usr/bin/env python3
"""Verify the exact API-F b55 runtime deployment evidence.

This verifier is offline and fail closed. It binds API-F's own exact pull,
fresh historical unit, ordered attempt ledger, single canary generation,
reversible promotion, explicit restart, read-only database sessions, peer
non-regression and final residue state. It grants neither public-launch nor
full-system rollback credit.
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
    "production-api-f-current-release-verified-20260730.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
TASK_ID = "PROD-FIRST-LAUNCH-API-F-INTERNAL-001"
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
    "32d552e3daba29130677d98927dff1701711763ef63573d5d9c199c99bf44268"
)
CANDIDATE_UNIT_SHA256 = (
    "23750496447ad6e31ad27b1461f1164bbf14c28296a0ac28be7e5886eb4e65c1"
)
API_C_UNIT_SHA256 = (
    "364a5e539b14a83d24ef9c1726ee3e14b988c398206b2711db5613b9e0a1fc77"
)
ADMIN_UNIT_SHA256 = (
    "c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2"
)
ADMIN_IMAGE_ID = (
    "sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f"
)
PULL_RESULT_SHA256 = (
    "4c4cb5b73f8ac18485201be07ac4b58f32938d6be36b21000f90f9dfbbc45652"
)
EXPECTED_SEMANTIC_SHA256 = (
    "a02ad81cb985d60baefff4576e8341d21db48784b730b7bef826285bafc94814"
)
SHA256_HEX_LENGTH = 64

EXPECTED_MANIFEST_EVIDENCE = [
    {"kind": "git", "ref": RELEASE_REVISION},
    {"kind": "path", "ref": EVIDENCE_REF},
    {
        "kind": "path",
        "ref": "tools/verify_api_f_current_release_evidence.py",
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
    (
        "deploy/production/evidence/"
        "production-api-c-current-release-verified-20260730.json",
        "f5e71305408e3ec415537649813362a1b3f52b0314effebf840b0480e2c61c35",
    ),
]
EXPECTED_ATTEMPT_IDS = (
    "baseline-browser-template-backref",
    "baseline-host-readonly-collector",
    "baseline-narrow-template-shell-collision",
    "baseline-narrow-readonly",
    "registry-pull-executor-v1",
    "registry-pull-executor-v2",
    "candidate-generator-v1",
    "candidate-generator-v2",
    "canary-mount-probe",
    "canary-start-combined-validation",
    "canary-validation-v2",
    "canary-db-wrapper-v1",
    "canary-db-session-v1",
    "promotion-attempt-1",
    "canary-rearm-v3",
    "promotion-v2-guard-wrong-path",
    "promotion-attempt-2",
    "formal-validator-syntax-v1",
    "formal-validator-mount-parser-v2",
    "formal-initial-validation-v3",
    "explicit-restart-syntax-v1",
    "explicit-managed-restart",
    "formal-postrestart-validation",
    "formal-db-session",
    "peer-audit-path-v1",
    "peer-audit-hash-followups",
    "canary-cleanup",
    "final-runtime-guard-v1",
    "final-runtime-validation-v2",
    "final-postcheck-v1",
    "final-postcheck-v2",
    "backup-explorer-refresh",
)
EXPECTED_ATTEMPT_RESULTS = (
    "FAILED",
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
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "FAILED",
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "PASS",
    "PASS",
    "FAILED",
    "PASS",
    "PASS",
    "FAILED",
    "PASS",
    "FAILED",
    "PASS",
    "FAILED",
)
ATTEMPT_COUNTER_FIELDS = (
    "database_connection_count",
    "database_transaction_count",
    "database_rollback_count",
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
    *ATTEMPT_COUNTER_FIELDS,
    "rollback_required",
    "rollback_result",
    "material_correction",
    "successor_attempt",
}
EXPECTED_REMOTE_HASHES = {
    "pull": PULL_RESULT_SHA256,
    "candidate": "4af3ef95659d5560696e5941c78f17dd84871b1ed2af350593ebc9adf64cd252",
    "canary_initial": "a8057cbba521276c7b8ba900c7aebab834febcc5045c39251424020eb25b8fd4",
    "canary_database": "d2eb6dad685c7097eed175b51d28310acf21e1bf0794431a167363001437e9de",
    "promotion_failed": "de656f8f8984d10bbc7394919610b8b006ad8c6078c88eeb9fa18a77e3216895",
    "canary_rearm": "9271273d9302c2ed7318c296787cdd8de8f7db88f517dd35061f41816cc02325",
    "promotion_success": "90078e429523323f0f1531859a025cf1954cd0928423807414cd2b6e276d60dd",
    "formal_initial": "f6726b17a34dd557b4ddbea3d5957d9bc6c3f8faa797c02a6e6c0ca80ad27c9d",
    "explicit_restart": "b0fc128a13797f47e514b03dbbc982596290504ee583ff1c6ab93756c0331fcd",
    "formal_postrestart": "6f22be7da9f6dfa4dbb2b20a486935bed53b241d138d449ecf684b03910cb1e4",
    "formal_database": "addc5b90decbd94c9892902a1545e63f204fa470809a74abd8660fca33343c80",
    "canary_cleanup": "51d5f8943de4630382a4e340c1b638741170f6788fc0e623530fe5b9d764b39b",
    "formal_final": "f392c3d2d63c259b7bdc89d8f7058dd5cc81b55458bb95a5ca7ee3b488643973",
    "final_postcheck_v1": "9bc22bfc43b19d5fa886d78f1eb03d29ef08f21bc79628701dca47a7075bd076",
    "final_postcheck_v2": "a98f5778ed9617e67affeb1010a1225c65a396736dd1207aaff8ed8242756b7f",
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


def _append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _all_zero(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and bool(payload)
        and all(isinstance(value, int) and value == 0 for value in payload.values())
    )


def _binding_rows(payload: Any) -> list[tuple[str, str]]:
    if not isinstance(payload, list):
        return []
    rows: list[tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            return []
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            return []
        rows.append((path, digest))
    return rows


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
        elif _sha256_path(target) != digest:
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
    _append(
        errors,
        [item.get("successor_attempt") for item in attempts]
        == [*EXPECTED_ATTEMPT_IDS[1:], None],
        "attempt successor chain mismatch",
    )
    for attempt in attempts:
        attempt_id = str(attempt.get("attempt_id"))
        _append(
            errors,
            set(attempt) == REQUIRED_ATTEMPT_FIELDS,
            f"{attempt_id}: attempt fields mismatch",
        )
        for field in ATTEMPT_COUNTER_FIELDS:
            _append(
                errors,
                isinstance(attempt.get(field), int) and attempt[field] >= 0,
                f"{attempt_id}: invalid {field}",
            )
        _append(
            errors,
            attempt.get("automatic_retry_count") == 0,
            f"{attempt_id}: automatic retry forbidden",
        )
        _append(
            errors,
            attempt.get("database_write_count") == 0,
            f"{attempt_id}: database write forbidden",
        )
        _append(
            errors,
            attempt.get("canary_restart_count") == 0,
            f"{attempt_id}: canary restart must remain zero",
        )
        _append(
            errors,
            attempt.get("incident_class") != "CONNECTED_UNKNOWN",
            "connected unknown attempt forbidden",
        )
        if attempt.get("result") == "FAILED" and attempt.get(
            "service_mutation_started"
        ):
            _append(
                errors,
                attempt.get("rollback_required") is True
                and attempt.get("rollback_result") == "PASS"
                and attempt.get("rollback_service_restart_count") == 1,
                "mutating failed attempt missing successful rollback",
            )
        if attempt.get("database_transaction_count", 0) > 0:
            _append(
                errors,
                attempt.get("incident_class") == "CONNECTED_KNOWN"
                and attempt.get("database_connection_count") == 1
                and attempt.get("database_transaction_count") == 1
                and attempt.get("database_rollback_count") == 1
                and attempt.get("rollback_required") is True
                and attempt.get("rollback_result") == "PASS",
                f"{attempt_id}: connected transaction not rolled back",
            )

    sums = {
        field: sum(int(item[field]) for item in attempts)
        for field in ATTEMPT_COUNTER_FIELDS
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
            item["incident_class"] == "CONNECTED_UNKNOWN" for item in attempts
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
        "database_rollback_count": sums["database_rollback_count"],
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

    source = evidence.get("source_binding") or {}
    source_identity = {
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
        all(source.get(key) == value for key, value in source_identity.items()),
        "source identity mismatch",
    )
    _append(
        errors,
        source.get("image_identity_binding")
        == {
            "source": "api_f_exact_pull_result",
            "pull_result_sha256": PULL_RESULT_SHA256,
            "unit_image_digest_match": True,
            "canary_config_image_match": True,
            "formal_config_image_match": True,
            "repo_digest_match": True,
            "revision_role_platform_entrypoint_cmd_match": True,
        },
        "API-F pull identity binding mismatch",
    )
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
    api_f = pre.get("api_f_api") or {}
    _append(
        errors,
        api_f.get("registry_manifest_digest") == OLD_MANIFEST_DIGEST
        and api_f.get("config_image_id") == OLD_IMAGE_ID
        and api_f.get("revision") == OLD_REVISION
        and api_f.get("unit_sha256") == OLD_UNIT_SHA256
        and api_f.get("active") is True
        and api_f.get("enabled") is True
        and api_f.get("service_result") == "success"
        and api_f.get("restart_count") == 0
        and api_f.get("live_http_status") == 200
        and api_f.get("ready_http_status") == 200
        and api_f.get("ready_core_checks_exact") == ["database", "model"]
        and api_f.get("bind_scope") == "loopback"
        and api_f.get("port") == 8000
        and api_f.get("hardening_exact") is True,
        "fresh API-F pre-state mismatch",
    )
    _append(
        errors,
        (pre.get("api_c_api") or {}).get("unit_sha256") == API_C_UNIT_SHA256
        and (pre.get("api_c_admin") or {}).get("unit_sha256")
        == ADMIN_UNIT_SHA256,
        "fresh peer pre-state mismatch",
    )
    _validate_attempts(evidence, errors)

    _append(
        errors,
        evidence.get("exact_pull")
        == {
            "result_sha256": PULL_RESULT_SHA256,
            "token_issuance_count": 2,
            "successful_login_count": 1,
            "successful_pull_count": 1,
            "automatic_retry_count": 0,
            "config_image_id_exact": True,
            "repo_digest_exact": True,
            "revision_exact": True,
            "role_exact": True,
            "platform_exact": True,
            "entrypoint_cmd_exact": True,
            "final_auth_entry_count": 0,
            "final_rsa_key_count": 0,
            "final_ciphertext_count": 0,
        },
        "exact pull evidence mismatch",
    )
    _append(
        errors,
        evidence.get("candidate_unit")
        == {
            "source_unit_sha256": OLD_UNIT_SHA256,
            "sha256": CANDIDATE_UNIT_SHA256,
            "bytes": 1447,
            "source_bytes": 1404,
            "systemd_verify_passed": True,
            "semantic_change_count": 2,
            "image_digest_change_count": 1,
            "storage_env_file_addition_count": 1,
            "other_token_change_count": 0,
        },
        "candidate unit mismatch",
    )

    canary = evidence.get("canary_acceptance") or {}
    canary_expected = {
        "generation_count": 1,
        "container_create_count": 1,
        "container_start_count": 1,
        "container_restart_count": 0,
        "container_remove_count": 1,
        "command_sha256": "0c0ace0bd7736148d25f4ba7c829e87103ea5cdbed99872bc472ace2d517c642",
        "initial_validation_result_sha256": "a8057cbba521276c7b8ba900c7aebab834febcc5045c39251424020eb25b8fd4",
        "rearm_validation_result_sha256": "9271273d9302c2ed7318c296787cdd8de8f7db88f517dd35061f41816cc02325",
        "passed_validation_dispatch_count": 2,
        "health_rounds_per_pass": 3,
        "live_200_count": 6,
        "ready_200_count": 6,
        "ready_core_exact_count": 6,
        "database_session_result_sha256": "d2eb6dad685c7097eed175b51d28310acf21e1bf0794431a167363001437e9de",
        "database_read_only_transaction_count": 1,
        "database_rollback_count": 1,
        "database_write_count": 0,
        "provider_call_count": 0,
        "object_write_count": 0,
        "final_container_count": 0,
        "final_listener_count": 0,
        "final_data_directory_count": 0,
    }
    _append(errors, canary == canary_expected, "canary acceptance mismatch")
    aggregates = evidence.get("attempt_aggregates") or {}
    _append(
        errors,
        canary.get("generation_count") == aggregates.get("canary_create_count")
        == aggregates.get("canary_start_count")
        == aggregates.get("canary_remove_count")
        == 1
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
        and promotion.get("final_postcleanup_health_rounds") == 3
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
        and post.get("final_assertion_count") == 33
        and post.get("final_assertion_failure_count") == 0
        and post.get("final_api_live_http_status") == 200
        and post.get("final_api_ready_http_status") == 200
        and post.get("ready_core_checks_exact") == ["database", "model"]
        and post.get("managed_container_count") == 1
        and post.get("unexpected_container_count") == 0
        and post.get("installed_unit_matches_candidate") is True
        and post.get("rollback_unit_matches_fresh_pre_state") is True
        and post.get("old_image_retained") is True
        and post.get("current_image_identity_exact") is True
        and post.get("current_repo_digest_exact") is True
        and post.get("current_platform_exact") is True
        and post.get("current_command_contract_exact") is True
        and post.get("hardening_exact") is True
        and post.get("public_mode_json_count") == 6
        and post.get("public_mode_json_sanitized") is True,
        "independent postcheck mismatch",
    )
    _append(
        errors,
        post.get("remote_evidence_hashes") == EXPECTED_REMOTE_HASHES,
        "remote evidence hash set mismatch",
    )

    database = evidence.get("database_runtime_postcheck") or {}
    _append(
        errors,
        database.get("canary_connection_count") == 1
        and database.get("formal_connection_count") == 1
        and database.get("read_only_transaction_count") == 2
        and database.get("runtime_role") == "noteai_app"
        and database.get("default_transaction_read_only") is True
        and database.get("transaction_read_only") is True
        and database.get("xid_unassigned") is True
        and database.get("transaction_tuple_write_count") == 0
        and database.get("transaction_rollback_count") == 2
        and database.get("schema_migrations_select_attempted") is False
        and database.get("database_write_count") == 0
        and database.get("schema_write_count") == 0
        and database.get("role_write_count") == 0
        and database.get("business_write_count") == 0
        and database.get("business_values_persisted_in_evidence") == 0
        and database.get("final_established_connection_count") == 0
        and database.get("connected_unknown_count") == 0,
        "database postcheck mismatch",
    )

    managed = evidence.get("managed_secret_and_storage_non_regression") or {}
    _append(
        errors,
        managed.get("managed_secret_file_count") == 3
        and managed.get("managed_secret_regular_root_0600_count") == 3
        and managed.get("managed_secret_distinct_count") == 3
        and managed.get("managed_secret_missing_count") == 0
        and managed.get("managed_secret_duplicate_key_count") == 0
        and managed.get("managed_secret_rejected_key_count") == 0
        and managed.get("managed_secret_backup_residue_count") == 0
        and managed.get("managed_secret_hashes_unchanged") is True
        and managed.get("lifecycle_tool_file_count") == 2
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
        _all_zero(logs),
        "bounded log review mismatch",
    )

    non_regression = evidence.get("final_non_regression") or {}
    api_c = non_regression.get("api_c_api") or {}
    _append(
        errors,
        api_c.get("unit_sha256_before")
        == api_c.get("unit_sha256_after")
        == API_C_UNIT_SHA256
        and api_c.get("config_image_id_before")
        == api_c.get("config_image_id_after")
        == CONFIG_IMAGE_ID
        and api_c.get("revision_before")
        == api_c.get("revision_after")
        == RELEASE_REVISION
        and api_c.get("container_identity_unchanged") is True
        and api_c.get("restart_count") == 0
        and api_c.get("live_http_status") == 200
        and api_c.get("ready_http_status") == 200
        and api_c.get("bind_scope") == "loopback",
        "API-C non-regression mismatch",
    )
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
    _append(
        errors,
        non_regression.get("schema_role_mutation_count") == 0
        and non_regression.get("managed_secret_mutation_count") == 0
        and non_regression.get("storage_config_mutation_count") == 0,
        "protected dependency mutation detected",
    )

    _append(
        errors,
        evidence.get("fresh_control_plane_postcheck")
        == {
            "observed_at_utc": "2026-07-30T10:02:00Z",
            "backup_observed_at_utc": "2026-07-30T08:35:18Z",
            "running_postgresql_16_instance_count": 1,
            "vpc_instance_count": 1,
            "intranet_instance_count": 1,
            "private_endpoint_count": 1,
            "public_endpoint_count": 0,
            "account_count": 8,
            "super_account_count": 1,
            "task_account_count": 0,
            "available_account_count": 8,
            "rds_task_count": 0,
            "successful_automated_full_snapshot_count_in_window": 7,
            "latest_successful_backup_age_hours_floor": 19,
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
        "unexpected_container_count",
        "established_database_connection_count",
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
            "internal_verified_before": 18,
            "internal_verified_after": 19,
            "internal_total": 29,
            "internal_percentage_after": 66,
            "complete_public_verified_before": 18,
            "complete_public_verified_after": 19,
            "complete_public_total": 38,
            "complete_public_percentage_after": 50,
            "next_task": "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
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
        "API-F runtime evidence semantic hash mismatch",
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
        return [f"cannot load API-F runtime evidence: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    args = parser.parse_args()
    errors = validate_bundle(args.evidence)
    if errors:
        print("api_f_current_release_evidence=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("api_f_current_release_evidence=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
