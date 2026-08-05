#!/usr/bin/env python3
"""Verify the bounded Admin current-release production acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-admin-current-release-verified-20260805.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
STAGE_B_PATH = (
    ROOT
    / "deploy/production/evidence/"
    "production-admin-stage-b-private-publication-verified-20260804.json"
)
API_C_EVIDENCE_PATH = (
    ROOT
    / "deploy/production/evidence/"
    "production-api-c-current-release-verified-20260730.json"
)
API_F_EVIDENCE_PATH = (
    ROOT
    / "deploy/production/evidence/"
    "production-api-f-current-release-verified-20260730.json"
)
BASELINE_EVIDENCE_PATH = (
    ROOT
    / "deploy/production/evidence/"
    "production-minimal-runtime-baseline-reconciled-20260804.json"
)
RUNTIME_PATH = ROOT / "deploy/production/admin_stagec_runtime.py"
TASK_ID = "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
REVISION = "5335bdaed933b1f999b5f819c047ec50c11821ae"
MANIFEST_DIGEST = (
    "sha256:d417718ff16ae9a456d2e099182661d320283c2755d3b3978eb82a5cee928c2a"
)
CONFIG_IMAGE_ID = (
    "sha256:fa0e658cba59a0adda16f64efb9bdfe543f459d90fe35997bd39046eb7743bd4"
)
RUNTIME_SHA256 = (
    "f8ccd0cc2bd1c939e23986719c7c64c663183f2e4fb8ee856ebf3215d8ae2356"
)
CANDIDATE_UNIT_SHA256 = (
    "101f8814d89736c2aa920f3107916b9b1ab53cabffdde0d69908285fd6d1fe8a"
)
API_C_UNIT_SHA256 = (
    "364a5e539b14a83d24ef9c1726ee3e14b988c398206b2711db5613b9e0a1fc77"
)
API_F_UNIT_SHA256 = (
    "23750496447ad6e31ad27b1461f1164bbf14c28296a0ac28be7e5886eb4e65c1"
)
API_IMAGE_ID = (
    "sha256:dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53"
)
EXPECTED_MODE_ORDER = (
    "canary-start",
    "canary-validate",
    "acl-audit",
    "session-open",
    "promote",
    "formal-validate",
    "explicit-restart",
    "session-close",
    "cleanup",
)
INVOKE_ID = re.compile(r"^[tf]-[a-z0-9]+$")
REQUEST_ID = re.compile(r"^[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}$")


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: root must be an object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(
    errors: list[str], condition: bool, message: str
) -> None:
    if not condition:
        errors.append(message)


def _matches(item: Any, expected: dict[str, Any]) -> bool:
    return isinstance(item, dict) and all(item.get(key) == value for key, value in expected.items())


def validate_document(
    payload: dict[str, Any], *, root: Path = ROOT
) -> list[str]:
    errors: list[str] = []
    _require(errors, payload.get("schema_version") == 1, "schema mismatch")
    _require(errors, payload.get("task_id") == TASK_ID, "task mismatch")
    _require(errors, payload.get("status") == "VERIFIED", "status mismatch")

    source = payload.get("source_binding")
    _require(
        errors,
        _matches(
            source,
            {
                "revision": REVISION,
                "tag": "git-5335bda-amd64-admin-r1",
                "registry_manifest_digest": MANIFEST_DIGEST,
                "config_image_id": CONFIG_IMAGE_ID,
                "platform": "linux/amd64",
                "runtime_role": "admin",
                "entrypoint": "/app/scripts/docker_entrypoint.sh",
                "command": "/app/scripts/render_start_admin.sh",
            },
        ),
        "source identity mismatch",
    )

    implementation = payload.get("implementation")
    _require(
        errors,
        _matches(
            implementation,
            {
                "runtime_path": "deploy/production/admin_stagec_runtime.py",
                "runtime_sha256": RUNTIME_SHA256,
                "candidate_unit_sha256": CANDIDATE_UNIT_SHA256,
                "minimal_correction": "named_dict_row_xid_lookup",
                "build_image_or_production_resource_semantics_changed": False,
                "custom_ledger_receipt_or_topology_added": False,
            },
        ),
        "implementation binding mismatch",
    )
    _require(
        errors,
        RUNTIME_PATH.is_file() and _sha256(RUNTIME_PATH) == RUNTIME_SHA256,
        "runtime bytes mismatch",
    )
    dependencies = payload.get("dependency_evidence")
    expected_dependencies = {
        "stage_b_private_publication_sha256": (
            STAGE_B_PATH,
            "6cda5b874def208b8b38120b27d7404c2787da8fea5e591b68d2011a56e04071",
        ),
        "api_c_current_release_sha256": (
            API_C_EVIDENCE_PATH,
            "f5e71305408e3ec415537649813362a1b3f52b0314effebf840b0480e2c61c35",
        ),
        "api_f_current_release_sha256": (
            API_F_EVIDENCE_PATH,
            "14bc2b71f7b5b02eae143234b166f26a476cf34b69beff04652ebd8e03a6784b",
        ),
        "runtime_baseline_reconciliation_sha256": (
            BASELINE_EVIDENCE_PATH,
            "4cbbe50595ea810b417ef61698478c8ef5c73ffc4582d1d2568c54f7d12d3e57",
        ),
    }
    _require(errors, isinstance(dependencies, dict), "dependency evidence missing")
    for key, (path, digest) in expected_dependencies.items():
        _require(
            errors,
            isinstance(dependencies, dict)
            and dependencies.get(key) == digest
            and path.is_file()
            and _sha256(path) == digest,
            f"{key}: dependency evidence mismatch",
        )
    focused = implementation.get("focused_tests") if isinstance(implementation, dict) else None
    _require(
        errors,
        _matches(
            focused,
            {
                "normal": "8/8",
                "optimized": "8/8",
                "python_compile": True,
                "diff_check": True,
            },
        ),
        "focused verification mismatch",
    )

    pull = payload.get("private_pull")
    _require(
        errors,
        _matches(
            pull,
            {
                "initial_cache_state": "ABSENT",
                "registry_credential_issuance_count": 1,
                "registry_login_count": 2,
                "registry_pull_count": 1,
                "automatic_retry_count": 0,
                "successful_pull_result": "EXACT_IMAGE_CACHED",
                "pulled_manifest_digest": MANIFEST_DIGEST,
                "pulled_config_image_id": CONFIG_IMAGE_ID,
                "auth_key_cipher_residue_count": 0,
                "registry_push_count": 0,
                "registry_tag_count": 0,
                "iam_mutation_count": 0,
                "registry_link_mutation_count": 0,
                "builder_start_count": 0,
            },
        ),
        "private pull accounting mismatch",
    )

    v3 = payload.get("historical_v3_incident")
    _require(
        errors,
        _matches(
            v3,
            {
                "session_open_status": "FAILED",
                "failure_detail_code": "subprocess_failed",
                "root_cause": "dict_row_result_was_accessed_positionally",
                "task_session_insert_count": 1,
                "failure_cleanup_task_session_delete_count": 1,
                "task_session_residue_count": 0,
                "connected_unknown_count": 0,
                "automatic_retry_count": 0,
                "abort_cleanup_status": "PASS",
                "abort_release_accepted": False,
                "abort_service_outcome": "KNOWN_ROLLED_BACK",
                "abort_canary_container_count": 0,
                "abort_canary_listener_count": 0,
                "historical_result_rewritten": False,
            },
        ),
        "historical V3 incident mismatch",
    )

    transport = payload.get("v4_preflight_and_transport")
    _require(
        errors,
        _matches(
            transport,
            {
                "historical_admin_active_enabled_healthy": True,
                "v4_namespace_initially_absent": True,
                "canary_initially_absent": True,
                "canary_listener_initially_absent": True,
                "image_cached_exact": True,
                "rollback_snapshot_sha_exact": True,
                "candidate_sha_exact": True,
                "runtime_source_sha_exact": True,
                "runtime_compile_passed": True,
                "input_owner_mode_exact": True,
            },
        ),
        "V4 preflight or transport mismatch",
    )

    modes = payload.get("ordered_modes")
    _require(errors, isinstance(modes, list), "ordered modes missing")
    if not isinstance(modes, list):
        modes = []
    _require(
        errors,
        tuple(item.get("mode") for item in modes if isinstance(item, dict))
        == EXPECTED_MODE_ORDER,
        "mode order mismatch",
    )
    invoke_ids: set[str] = set()
    for item in modes:
        if not isinstance(item, dict):
            errors.append("invalid mode result")
            continue
        invoke_id = item.get("invoke_id")
        result_request_id = item.get("result_request_id")
        _require(
            errors,
            isinstance(invoke_id, str)
            and bool(INVOKE_ID.fullmatch(invoke_id))
            and invoke_id not in invoke_ids,
            f"{item.get('mode')}: invalid or duplicate invoke id",
        )
        if isinstance(invoke_id, str):
            invoke_ids.add(invoke_id)
        _require(
            errors,
            isinstance(result_request_id, str)
            and bool(REQUEST_ID.fullmatch(result_request_id)),
            f"{item.get('mode')}: invalid result request id",
        )
        _require(
            errors,
            _matches(
                item,
                {
                    "status": "PASS",
                    "exit_code": 0,
                    "repeats": 1,
                    "automatic_retry_count": 0,
                    "connected_unknown_count": 0,
                },
            ),
            f"{item.get('mode')}: terminal result mismatch",
        )

    by_mode = {
        item["mode"]: item
        for item in modes
        if isinstance(item, dict) and isinstance(item.get("mode"), str)
    }
    expected_modes = {
        "canary-start": {
            "canary_create_count": 1,
            "canary_start_count": 1,
            "canary_restart_count": 0,
            "health_rounds": 3,
            "database_write_count": 0,
        },
        "canary-validate": {
            "live_200_count": 3,
            "ready_200_count": 3,
            "container_exact": True,
            "image_config_id": CONFIG_IMAGE_ID,
            "restart_count": 0,
            "database_write_count": 0,
            "provider_call_count": 0,
            "object_write_count": 0,
        },
        "acl-audit": {
            "table_count": 56,
            "table_privilege_check_count": 392,
            "table_allow_count": 27,
            "table_deny_count": 365,
            "table_mismatch_count": 0,
            "column_privilege_check_count": 2432,
            "column_allow_count": 329,
            "column_mismatch_count": 0,
            "sequence_count": 5,
            "sequence_privilege_check_count": 15,
            "sequence_allowed_count": 0,
            "grantable_count": 0,
            "function_execute_count": 0,
            "role_and_rls_exact": True,
            "read_only_transaction_count": 1,
            "database_rollback_count": 1,
            "database_write_count": 0,
            "business_value_read_count": 0,
            "xid_unassigned": True,
        },
        "session-open": {
            "successful_login_count": 1,
            "successful_login_status": 200,
            "task_session_insert_count": 1,
            "task_session_residue_count": 1,
            "database_session_write_count": 1,
            "database_business_write_count": 0,
            "side_effect_snapshot_exact": True,
            "side_effect_observation_rounds": 8,
            "side_effect_detected_count": 0,
            "process_spawn_count": 0,
            "provider_call_count": 0,
            "object_write_count": 0,
        },
        "promote": {
            "installed_unit_sha256": CANDIDATE_UNIT_SHA256,
            "promotion_restart_count": 1,
            "rollback_required": False,
            "rollback_restart_count": 0,
            "service_outcome": "KNOWN_ACTIVE",
            "systemd_active_enabled_success": True,
            "systemd_automatic_restart_count": 0,
            "database_write_count": 0,
            "provider_call_count": 0,
            "object_write_count": 0,
        },
        "formal-validate": {
            "container_exact": True,
            "image_config_id": CONFIG_IMAGE_ID,
            "loopback_port": 8001,
            "health_rounds": 3,
            "restart_count": 0,
            "transaction_read_only": "on",
            "xid_unassigned": True,
            "database_write_count": 0,
            "rollback_required": False,
        },
        "explicit-restart": {
            "explicit_restart_count": 1,
            "container_identity_changed": True,
            "health_rounds": 3,
            "rollback_required": False,
            "systemd_automatic_restart_count": 0,
        },
        "session-close": {
            "successful_logout_count": 1,
            "logout_status": 200,
            "task_session_insert_count": 1,
            "task_session_delete_count": 1,
            "task_session_residue_count": 0,
            "token_file_count": 0,
            "token_database_digest_count": 0,
            "canary_replay_status": 403,
            "formal_replay_status": 403,
            "database_business_write_count": 0,
            "rollback_required": False,
        },
        "cleanup": {
            "canary_remove_count": 1,
            "canary_container_count": 0,
            "canary_listener_count": 0,
            "canary_data_directory_count": 0,
            "token_file_count": 0,
            "formal_container_exact": True,
            "formal_image_config_id": CONFIG_IMAGE_ID,
            "formal_health_rounds": 3,
            "api_c_peer_non_regression": True,
            "database_write_count": 0,
            "provider_call_count": 0,
            "object_write_count": 0,
            "public_traffic_change_count": 0,
        },
    }
    for mode, expected in expected_modes.items():
        _require(errors, _matches(by_mode.get(mode), expected), f"{mode}: acceptance mismatch")

    postchecks = payload.get("independent_postchecks")
    api_c_admin = postchecks.get("api_c_and_admin") if isinstance(postchecks, dict) else None
    api_f = postchecks.get("api_f") if isinstance(postchecks, dict) else None
    _require(
        errors,
        _matches(
            api_c_admin,
            {
                "exit_code": 0,
                "repeats": 1,
                "api_unit_sha256": API_C_UNIT_SHA256,
                "admin_unit_sha256": CANDIDATE_UNIT_SHA256,
                "api_image_config_id": API_IMAGE_ID,
                "admin_image_config_id": CONFIG_IMAGE_ID,
                "systemd_active_enabled_success": True,
                "live_ready_200_rounds": 3,
                "loopback_only": True,
                "restart_count": 0,
                "established_database_connection_count": 0,
                "canary_count": 0,
                "runtime_temp_root_count": 0,
            },
        ),
        "API-C/Admin independent postcheck mismatch",
    )
    _require(
        errors,
        _matches(
            api_f,
            {
                "exit_code": 0,
                "repeats": 1,
                "api_unit_sha256": API_F_UNIT_SHA256,
                "api_image_config_id": API_IMAGE_ID,
                "systemd_active_enabled_success": True,
                "live_ready_200_rounds": 3,
                "loopback_only": True,
                "restart_count": 0,
                "established_database_connection_count": 0,
                "canary_count": 0,
            },
        ),
        "API-F independent postcheck mismatch",
    )
    _require(
        errors,
        _matches(
            payload.get("final_temp_cleanup"),
            {
                "exit_code": 0,
                "repeats": 1,
                "v3_stage_root_count": 0,
                "v4_stage_root_count": 0,
                "runtime_root_count": 0,
                "canary_count": 0,
                "canary_listener_count": 0,
                "api_c_and_admin_units_exact": True,
                "api_c_and_admin_healthy": True,
            },
        ),
        "final temporary cleanup mismatch",
    )

    final = payload.get("final_acceptance")
    _require(
        errors,
        _matches(
            final,
            {
                "admin_current_release": "VERIFIED",
                "admin_loopback_listener": "127.0.0.1:8001",
                "admin_database_role": "noteai_admin_runtime",
                "normal_session_insert_delete": "1/1",
                "normal_session_residue_count": 0,
                "business_database_write_count": 0,
                "schema_role_acl_mutation_count": 0,
                "provider_call_count": 0,
                "object_write_count": 0,
                "public_traffic_change_count": 0,
                "public_listener_count": 0,
                "registry_push_or_tag_count": 0,
                "iam_or_registry_link_mutation_count": 0,
                "builder_start_count": 0,
                "connected_unknown_count": 0,
                "automatic_retry_count": 0,
                "stage_a_or_ci_or_full_gate_repeated_before_acceptance": False,
                "release_accepted": True,
                "public_launch_authorized": False,
                "full_system_failure_rollback_verified": False,
            },
        ),
        "final acceptance mismatch",
    )
    _require(
        errors,
        _matches(
            payload.get("readiness"),
            {
                "internal_verified_before": 19,
                "internal_verified_after": 20,
                "internal_total": 29,
                "public_verified_after": 20,
                "public_total": 38,
                "credit_added": 1,
                "next_task": "PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001",
            },
        ),
        "readiness transition mismatch",
    )

    try:
        stage_b = _load(STAGE_B_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load Stage B evidence: {exc}")
    else:
        publication = stage_b.get("exact_one_publication")
        native = stage_b.get("native_registry_acceptance")
        decision = stage_b.get("acceptance_decision")
        _require(
            errors,
            _matches(
                publication,
                {
                    "status": "Success",
                    "exit_code": 0,
                    "publisher_invocation_count": 1,
                    "docker_push_invocation_count": 1,
                    "automatic_retry_count": 0,
                    "manual_retry_count": 0,
                    "published_count": 1,
                    "release_commit": REVISION,
                    "push_digest": MANIFEST_DIGEST,
                    "manifest_descriptor_digest": MANIFEST_DIGEST,
                    "manifest_config_digest": CONFIG_IMAGE_ID,
                },
            ),
            "Stage B publication dependency mismatch",
        )
        _require(
            errors,
            _matches(
                native,
                {
                    "is_success": True,
                    "status": "NORMAL",
                    "control_plane_digest": MANIFEST_DIGEST,
                    "control_plane_image_id": CONFIG_IMAGE_ID,
                    "push_manifest_control_plane_digest_agreement": True,
                    "manifest_config_local_image_id_agreement": True,
                },
            ),
            "Stage B native digest dependency mismatch",
        )
        _require(
            errors,
            isinstance(decision, dict) and decision.get("stage_c_open") is True,
            "Stage B did not open Stage C",
        )
    return errors


def validate_bundle(
    *, root: Path = ROOT, evidence_path: Path | None = None
) -> list[str]:
    path = evidence_path or (root / EVIDENCE_REF)
    try:
        payload = _load(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load Admin current-release evidence: {exc}"]
    return validate_document(payload, root=root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    args = parser.parse_args()
    errors = validate_bundle(evidence_path=args.evidence)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: exact Admin current-release production evidence verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
