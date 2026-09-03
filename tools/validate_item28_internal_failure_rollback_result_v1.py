#!/usr/bin/env python3
"""Validate the exact Secret-free result emitted by the Item 28 executor."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


VALIDATOR_REF = "tools/validate_item28_internal_failure_rollback_result_v1.py"
SCHEMA = "noteai.item28.internal-failure-rollback.v1"
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_UNIT_FRAGMENT_SHA256 = (
    "f591f43b0377402dbc026c4e7f5eee08bc8b884fd9e3523fe775fa5a8f0bb936"
)
EXPECTED_VOLATILE_DROPIN_SHA256 = (
    "d9fc435118b567a4ef1ea28ab25d7358f0f98e77f83c52e04514b4cb44433305"
)
RESULT_KEYS = {
    "schema", "task_id", "status", "mode", "failure_phase",
    "failure_mechanism", "unit_fragment_sha256", "volatile_dropin_sha256",
    "pre_health", "post_health", "release_identity_sha256",
    "release_identity_unchanged", "restart_attempt_count",
    "restart_return_code_nonzero", "restart_success_count",
    "restart_failed_pre_connect_count", "guardian_rollback_count",
    "guardian_rollback_status", "restored_runtime_start_count",
    "original_release_restored", "volatile_residue_count",
    "daemon_reload_count", "provider_call_count", "provider_attempt_count",
    "oss_mutation_count", "iam_mutation_count",
    "host_executor_database_command_count",
    "production_database_mutation_count", "cloud_resource_create_count",
    "public_request_count", "automatic_retry_allowed",
    "same_invocation_replay_allowed",
}
HEALTH_ROW_KEYS = {"path", "status", "state"}


def canonical(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("ascii")


def _zero(value: Any) -> bool:
    return type(value) is int and value == 0


def _one(value: Any) -> bool:
    return type(value) is int and value == 1


def _health(value: Any) -> bool:
    expected = (
        {"path": "/health/live", "status": 200, "state": "ok"},
        {"path": "/health/ready", "status": 200, "state": "ready"},
    )
    return (
        type(value) is list and len(value) == 2
        and all(type(row) is dict and set(row) == HEALTH_ROW_KEYS
                for row in value)
        and tuple(value) == expected
    )


def validate_executor_result(value: Any) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    if type(value) is not dict or set(value) != RESULT_KEYS:
        return ["result schema mismatch"], None
    expected_scalars = {
        "schema": SCHEMA,
        "task_id": TASK_ID,
        "status": "PASS",
        "mode": "api-f",
        "failure_phase": "PRE_CONNECT",
        "failure_mechanism": "VOLATILE_SYSTEMD_EXECSTARTPRE_FALSE",
        "release_identity_unchanged": True,
        "restart_return_code_nonzero": True,
        "guardian_rollback_status": "RESTORED",
        "original_release_restored": True,
        "automatic_retry_allowed": False,
        "same_invocation_replay_allowed": False,
    }
    for key, expected in expected_scalars.items():
        if type(value.get(key)) is not type(expected) or value.get(key) != expected:
            errors.append(key + " mismatch")
    for key in (
        "unit_fragment_sha256", "volatile_dropin_sha256",
        "release_identity_sha256",
    ):
        if type(value.get(key)) is not str or HEX64.fullmatch(value[key]) is None:
            errors.append(key + " invalid")
    if value.get("unit_fragment_sha256") != EXPECTED_UNIT_FRAGMENT_SHA256:
        errors.append("unit_fragment_sha256 mismatch")
    if value.get("volatile_dropin_sha256") != EXPECTED_VOLATILE_DROPIN_SHA256:
        errors.append("volatile_dropin_sha256 mismatch")
    for key in (
        "restart_attempt_count", "restart_failed_pre_connect_count",
        "guardian_rollback_count",
    ):
        if not _one(value.get(key)):
            errors.append(key + " must be one")
    if (
        type(value.get("restored_runtime_start_count")) is not int
        or value["restored_runtime_start_count"] not in {0, 1}
    ):
        errors.append("restored_runtime_start_count must be zero or one")
    if value.get("daemon_reload_count") != 2 or type(value.get("daemon_reload_count")) is not int:
        errors.append("daemon_reload_count mismatch")
    for key in (
        "restart_success_count", "volatile_residue_count", "provider_call_count",
        "provider_attempt_count", "oss_mutation_count", "iam_mutation_count",
        "host_executor_database_command_count",
        "production_database_mutation_count", "cloud_resource_create_count",
        "public_request_count",
    ):
        if not _zero(value.get(key)):
            errors.append(key + " must be zero")
    if not _health(value.get("pre_health")) or not _health(value.get("post_health")):
        errors.append("health projection mismatch")
    if errors:
        return errors, None
    raw = canonical(value)
    return [], {
        "result_canonical_bytes": len(raw),
        "result_canonical_sha256": hashlib.sha256(raw).hexdigest(),
        "terminal_acceptance_sha256": hashlib.sha256(raw[:-1]).hexdigest(),
    }
