#!/usr/bin/env python3
"""Shared exact semantic validator for one Item 27 executor result."""

from __future__ import annotations

import re
from typing import Any


VALIDATOR_REF = "tools/validate_item27_internal_smoke_result_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-SMOKE-001"
RESULT_SCHEMA = "noteai.item27.internal-zero-provider-smoke.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTION_CONTRACT = {
    "api_c": ("api-c", 8, ("dispatcher", "payment")),
    "api_f": ("api-f", 5, ("trends", "tracking")),
    "worker_c": ("worker-c", 0, ("worker",)),
    "worker_f": ("worker-f", 0, ("worker",)),
}
COMMON_RESULT_KEYS = {
    "schema", "task_id", "status", "mode", "loopback_endpoint_count",
    "endpoint_projections", "roles", "active_runtime_identity_unchanged",
    "public_listener_count", "service_start_count", "service_stop_count",
    "original_state_restored", "provider_call_count",
    "provider_attempt_count", "oss_mutation_count",
    "production_database_mutation_count", "synthetic_record_count",
    "public_request_count", "cleanup", "automatic_retry_allowed",
    "same_invocation_replay_allowed",
}


def _strict_equal(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(
            _strict_equal(value[key], item) for key, item in expected.items()
        )
    if isinstance(expected, list):
        return len(value) == len(expected) and all(
            _strict_equal(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _endpoint(
    value: Any, *, path: str, status: int,
    service: str | None = None, state: str | None = None,
) -> bool:
    keys = {"path", "status"}
    if service is not None:
        keys.update({"service", "state"})
        if state == "ready":
            keys.add("checks")
    if type(value) is not dict or set(value) != keys:
        return False
    if value.get("path") != path or not _strict_equal(value.get("status"), status):
        return False
    if service is None:
        return True
    if value.get("service") != service or value.get("state") != state:
        return False
    if state == "ready":
        checks = value.get("checks")
        return (
            type(checks) is list and bool(checks)
            and checks == sorted(set(checks))
            and all(type(item) is str and item for item in checks)
        )
    return True


def _validate_endpoints(mode: str, projections: Any, errors: list[str]) -> dict[str, str]:
    if mode not in {"api-c", "api-f"}:
        if projections != []:
            errors.append(f"{mode}: unexpected endpoints")
        return {}
    count = 8 if mode == "api-c" else 5
    if type(projections) is not list or len(projections) != count:
        errors.append(f"{mode}: endpoint projection count mismatch")
        return {}
    checks = (
        _endpoint(
            projections[0], path="/health/live", status=200,
            service="noteai-api", state="ok",
        ),
        _endpoint(
            projections[1], path="/health/ready", status=200,
            service="noteai-api", state="ready",
        ),
    )
    if not checks[0]:
        errors.append(f"{mode}: API live projection mismatch")
    if not checks[1]:
        errors.append(f"{mode}: API ready projection mismatch")
    hashes: dict[str, str] = {}
    for index, path in ((2, "/legal/contracts"), (3, "/billing/tiers")):
        item = projections[index]
        valid = (
            type(item) is dict and set(item) == {"path", "status", "sha256"}
            and item.get("path") == path
            and _strict_equal(item.get("status"), 200)
            and type(item.get("sha256")) is str
            and HEX64.fullmatch(item["sha256"]) is not None
        )
        if not valid:
            errors.append(f"{mode}: {path} projection mismatch")
        else:
            hashes[path] = item["sha256"]
    if not _strict_equal(projections[4], {
        "path": "/payments/capabilities", "status": 200,
        "ordering_available": False, "currency": "CNY", "auto_renewal": False,
    }):
        errors.append(f"{mode}: payment capability projection mismatch")
    if mode == "api-c":
        if not _endpoint(
            projections[5], path="/health/live", status=200,
            service="noteai-admin", state="ok",
        ):
            errors.append("api-c: Admin live projection mismatch")
        if not _endpoint(
            projections[6], path="/health/ready", status=200,
            service="noteai-admin", state="ready",
        ):
            errors.append("api-c: Admin ready projection mismatch")
        if not _strict_equal(projections[7], {
            "path": "/admin/capabilities", "status": 403,
            "authorization": "REJECTED",
        }):
            errors.append("api-c: Admin authorization projection mismatch")
    return hashes


def _validate_role(value: Any, expected: str, label: str, errors: list[str]) -> None:
    base = {
        "role", "health_passed", "suspended_one_shot_passed",
        "expected_negative_passed",
    }
    extras = {
        "dispatcher": {"pending_outbox", "exhausted_outbox"},
        "payment": set(),
        "worker": {
            "needs_manual", "expired_ready", "stale_provider_outcome",
            "recoverable_unstarted",
        },
        "trends": {"provider_attempt_counts"},
        "tracking": {"provider_attempt_counts"},
    }[expected]
    if type(value) is not dict or set(value) != base | extras:
        errors.append(f"{label}: role fields mismatch")
        return
    if (
        value.get("role") != expected
        or value.get("health_passed") is not True
        or value.get("suspended_one_shot_passed") is not (expected != "payment")
        or value.get("expected_negative_passed") is not (expected == "payment")
    ):
        errors.append(f"{label}: role semantics mismatch")
    if expected == "dispatcher" and not (
        _nonnegative_int(value.get("pending_outbox"))
        and _strict_equal(value.get("exhausted_outbox"), 0)
    ):
        errors.append(f"{label}: dispatcher counters mismatch")
    if expected == "worker" and not (
        all(_strict_equal(value.get(key), 0) for key in (
            "needs_manual", "expired_ready", "stale_provider_outcome",
        ))
        and _nonnegative_int(value.get("recoverable_unstarted"))
    ):
        errors.append(f"{label}: worker counters mismatch")
    if expected == "trends" and not _strict_equal(
        value.get("provider_attempt_counts"),
        {"active": 0, "unknown": 0, "unlinked": 0},
    ):
        errors.append(f"{label}: Trends provider-attempt mismatch")
    if expected == "tracking" and not _strict_equal(
        value.get("provider_attempt_counts"),
        {"active": 0, "stale": 0, "unlinked": 0},
    ):
        errors.append(f"{label}: Tracking provider-attempt mismatch")


def validate_executor_result(
    result: Any, action: str
) -> tuple[list[str], dict[str, Any]]:
    """Validate the complete executor result before evidence can say VERIFIED."""

    errors: list[str] = []
    if action not in ACTION_CONTRACT:
        return ["unknown action"], {}
    mode, endpoint_count, roles = ACTION_CONTRACT[action]
    if type(result) is not dict or set(result) != COMMON_RESULT_KEYS:
        return [f"{action}: result fields mismatch"], {}
    starts = len(roles)
    expected = {
        "schema": RESULT_SCHEMA, "task_id": TASK_ID, "status": "PASS",
        "mode": mode, "loopback_endpoint_count": endpoint_count,
        "active_runtime_identity_unchanged": True, "public_listener_count": 0,
        "service_start_count": starts, "service_stop_count": starts,
        "original_state_restored": True, "provider_call_count": 0,
        "provider_attempt_count": 0, "oss_mutation_count": 0,
        "production_database_mutation_count": 0, "synthetic_record_count": 0,
        "public_request_count": 0, "cleanup": "RESTORED",
        "automatic_retry_allowed": False,
        "same_invocation_replay_allowed": False,
    }
    if not all(_strict_equal(result.get(key), value) for key, value in expected.items()):
        errors.append(f"{action}: PASS result semantics mismatch")
    endpoint_hashes = _validate_endpoints(
        mode, result.get("endpoint_projections"), errors
    )
    observed_roles = result.get("roles")
    if type(observed_roles) is not list or len(observed_roles) != len(roles):
        errors.append(f"{action}: role count mismatch")
    else:
        for index, expected_role in enumerate(roles):
            _validate_role(
                observed_roles[index], expected_role,
                f"{action}/{expected_role}", errors,
            )
    return errors, {
        "endpoint_count": endpoint_count,
        "role_count": len(roles),
        "service_start_count": starts,
        "service_stop_count": starts,
        **{f"hash:{key}": value for key, value in endpoint_hashes.items()},
    }
