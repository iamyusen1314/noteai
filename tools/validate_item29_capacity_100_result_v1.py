#!/usr/bin/env python3
"""Strict host-only semantic validator for the Item 29 executor result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = ROOT / "deploy" / "production"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

from capacity_100_jobs import (  # noqa: E402
    DEPENDENCY_SCHEMA,
    EXPECTED_CREDITS_MILLI,
    MIN_API_C_MEMORY_HEADROOM_BYTES,
    MIN_API_C_PID_HEADROOM,
    MIN_DATABASE_IDLE_CONNECTION_HEADROOM,
    RESULT_SCHEMA,
    TASK_ID,
)


VALIDATOR_REF = "tools/validate_item29_capacity_100_result_v1.py"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _strict(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _strict(left, right) for left, right in zip(value, expected)
        )
    return value == expected


EXPECTED_PROVIDER = {
    "fake_call_count": 100,
    "unique_fake_operation_count": 100,
    "duplicate_fake_call_count": 0,
    "real_provider_call_count": 0,
    "claude_label_count": 50,
    "kimi_label_count": 50,
    "ai_model_call_count": 0,
    "input_token_count": 0,
    "output_token_count": 0,
    "provider_cost_milli": 0,
}

EXPECTED_ROUTING = {
    "exact_operation_claim_count": 102,
    "takeover_count": 2,
    "global_recovery_call_count": 0,
    "global_claim_call_count": 0,
    "worker_c_index_start": 0,
    "worker_c_index_end": 49,
    "worker_f_index_start": 50,
    "worker_f_index_end": 99,
    "worker_c_takeover_index": 0,
    "worker_f_takeover_index": 50,
    "pre_provider_interrupt_count": 2,
    "stale_owner_provider_call_count": 0,
}

EXPECTED_RUNTIME = {
    "maximum_concurrent_admission_count": 100,
    "unique_operation_count": 100,
    "outbox_count": 100,
    "delivered_count": 100,
    "succeeded_count": 100,
    "lost_operation_count": 0,
    "claim_count": 102,
    "takeover_count": 2,
    "provider_attempt_count": 100,
    "provider_attempt_number_not_one_count": 0,
    "worker_c_completed_count": 50,
    "worker_f_completed_count": 50,
    "worker_c_takeover_index": 0,
    "worker_f_takeover_index": 50,
    "settlement_completed_count": 100,
    "settlement_refunded_count": 0,
    "settlement_needs_manual_count": 0,
    "charge_applied_count": 100,
    "complete_applied_count": 100,
    "usage_record_count": 100,
    "expected_credits_milli": EXPECTED_CREDITS_MILLI,
    "actual_credits_milli": EXPECTED_CREDITS_MILLI,
    "overcharge_credits_milli": 0,
    "payment_record_delta_count": 0,
    "cash_balance_delta_milli": 0,
    "ready_request_object_residue_count": 0,
    "ready_result_object_residue_count": 0,
    "primary_user_residue_count": 0,
    "admission_residue_count": 0,
    "idempotency_residue_count": 0,
    "pseudonymous_operation_audit_count": 100,
    "pseudonymous_provider_attempt_audit_count": 100,
    "pseudonymous_usage_audit_count": 100,
}


def validate_executor_result(value: Any):
    errors: list[str] = []
    top_keys = {
        "schema", "task_id", "status", "item28_dependency", "headroom",
        "admission", "routing_and_recovery", "provider",
        "runtime_projection", "execution_boundary",
    }
    if type(value) is not dict or set(value) != top_keys:
        return ["Item29 result schema mismatch"], None
    if (
        value.get("schema") != RESULT_SCHEMA
        or value.get("task_id") != TASK_ID
        or value.get("status") != "PASS"
    ):
        errors.append("Item29 result identity mismatch")
    dependency = value.get("item28_dependency")
    dependency_keys = {
        "schema", "authority_root", "verifier_path", "verifier_sha256",
        "evidence_path", "evidence_sha256", "receipt_path", "receipt_sha256",
        "checkpoint_path", "checkpoint_sha256", "terminal_acceptance_sha256",
    }
    if type(dependency) is not dict or set(dependency) != dependency_keys:
        errors.append("Item29 Item28 dependency schema mismatch")
    else:
        if dependency.get("schema") != DEPENDENCY_SCHEMA:
            errors.append("Item29 Item28 dependency version mismatch")
        if not str(dependency.get("verifier_path", "")).startswith("tools/"):
            errors.append("Item29 Item28 dependency path mismatch")
        if any(
            not str(dependency.get(key, "")).startswith(
                "deploy/production/evidence/"
            )
            for key in ("evidence_path", "receipt_path", "checkpoint_path")
        ):
            errors.append("Item29 Item28 dependency path mismatch")
        for key in (
            "authority_root", "verifier_sha256", "evidence_sha256",
            "receipt_sha256", "checkpoint_sha256",
            "terminal_acceptance_sha256",
        ):
            if type(dependency.get(key)) is not str or HEX64.fullmatch(
                dependency[key]
            ) is None:
                errors.append("Item29 Item28 dependency authority mismatch")
                break
    headroom = value.get("headroom")
    headroom_keys = {
        "database_idle_connection_headroom",
        "database_idle_connection_headroom_required",
        "api_c_memory_headroom_bytes",
        "api_c_memory_headroom_bytes_required",
        "api_c_pid_headroom",
        "api_c_pid_headroom_required",
        "headroom_gate_passed",
    }
    if type(headroom) is not dict or set(headroom) != headroom_keys:
        errors.append("Item29 headroom schema mismatch")
    else:
        expected_minima = {
            "database_idle_connection_headroom": (
                MIN_DATABASE_IDLE_CONNECTION_HEADROOM
            ),
            "api_c_memory_headroom_bytes": MIN_API_C_MEMORY_HEADROOM_BYTES,
            "api_c_pid_headroom": MIN_API_C_PID_HEADROOM,
        }
        if any(
            type(headroom.get(key)) is not int or headroom[key] < minimum
            for key, minimum in expected_minima.items()
        ):
            errors.append("Item29 headroom insufficient")
        if not _strict(
            {
                "database_idle_connection_headroom_required": headroom.get(
                    "database_idle_connection_headroom_required"
                ),
                "api_c_memory_headroom_bytes_required": headroom.get(
                    "api_c_memory_headroom_bytes_required"
                ),
                "api_c_pid_headroom_required": headroom.get(
                    "api_c_pid_headroom_required"
                ),
                "headroom_gate_passed": headroom.get("headroom_gate_passed"),
            },
            {
                "database_idle_connection_headroom_required": (
                    MIN_DATABASE_IDLE_CONNECTION_HEADROOM
                ),
                "api_c_memory_headroom_bytes_required": (
                    MIN_API_C_MEMORY_HEADROOM_BYTES
                ),
                "api_c_pid_headroom_required": MIN_API_C_PID_HEADROOM,
                "headroom_gate_passed": True,
            },
        ):
            errors.append("Item29 headroom contract mismatch")
    admission = value.get("admission")
    if (
        type(admission) is not dict
        or set(admission) != {
            "barrier_participant_count", "concurrent_admission_count",
            "unique_operation_count", "operation_set_sha256",
        }
        or admission.get("barrier_participant_count") != 100
        or admission.get("concurrent_admission_count") != 100
        or admission.get("unique_operation_count") != 100
        or type(admission.get("operation_set_sha256")) is not str
        or HEX64.fullmatch(admission["operation_set_sha256"]) is None
    ):
        errors.append("Item29 admission mismatch")
    if not _strict(value.get("routing_and_recovery"), EXPECTED_ROUTING):
        errors.append("Item29 exact routing/recovery mismatch")
    if not _strict(value.get("provider"), EXPECTED_PROVIDER):
        errors.append("Item29 provider projection mismatch")
    if not _strict(value.get("runtime_projection"), EXPECTED_RUNTIME):
        errors.append("Item29 runtime projection mismatch")
    expected_boundary = {
        "provider_client_token_readback_supported": False,
        "provider_history_key": "Name",
        "automatic_retry_count": 0,
        "real_provider_credentials_loaded": False,
        "cloud_control_plane_call_count": 0,
        "public_request_count": 0,
    }
    if not _strict(value.get("execution_boundary"), expected_boundary):
        errors.append("Item29 execution boundary mismatch")
    serialized = _canonical(value).decode("ascii") if type(value) is dict else ""
    if "ClientToken" in serialized or "operation_id" in serialized:
        errors.append("Item29 result contains forbidden provider/private identity")
    if errors:
        return errors, None
    binding = {
        "result_semantic_sha256": _sha(value),
        "item28_terminal_acceptance_sha256": dependency[
            "terminal_acceptance_sha256"
        ],
        "operation_set_sha256": admission["operation_set_sha256"],
        "admission_count": 100,
        "takeover_count": 2,
        "fake_provider_call_count": 100,
        "settlement_completed_count": 100,
        "actual_credits_milli": EXPECTED_CREDITS_MILLI,
        "pseudonymous_audit_count_each": 100,
    }
    return [], binding


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = args.result.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("item29_result=BLOCK code=result_read")
        return 1
    if _canonical(value) + b"\n" != raw:
        print("item29_result=BLOCK code=result_canonical")
        return 1
    errors, binding = validate_executor_result(value)
    if errors or binding is None:
        print("item29_result=BLOCK code=" + (errors[0] if errors else "unknown"))
        return 1
    print(json.dumps(binding, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
