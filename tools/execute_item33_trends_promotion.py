#!/usr/bin/env python3
"""Fail-closed orchestration for the dependency-gated Item33 promotion.

This module does not open the production database, read Secrets, call XHS, or
invoke systemd/Docker itself.  A production wrapper supplies narrow callables
for the already implemented Trends cycle and the managed unit transitions.
The outer controller fixes ordering, request budget, no-replay behavior, and
the one rollback/reapply rehearsal required by Item33.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UNIT_NAME = "noteai-xhs-trends.service"
SUSPENDED_UNIT_SHA256 = (
    "3ed7e555d61c8286ab6d1116d99171d23d073b6a318dbd4890ce3106b976e3b6"
)
PROMOTED_UNIT_SHA256 = (
    "13d777c7705cc1dbc539c3dad3e034ba0ce5226b038e355d91bd3a440e565f8c"
)
PROVIDER_REQUEST_LIMIT = 34
ENDPOINTS = ("homefeed", "search_recommend", "search_notes")
AUTHORIZATION_SCHEMA = "noteai.item33.execution_authorization.v1"
RESULT_SCHEMA = "noteai.item33.execution_result.v1"
ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST_REF = "deploy/production/internal-deployment-readiness.json"
DEPENDENCY_EVIDENCE_REFS = {
    "real_xhs_trends": (
        "deploy/production/evidence/"
        "production-item32-xhs-trends-readonly-verified.json"
    ),
    "internal_failure_rollback": (
        "deploy/production/evidence/"
        "production-internal-failure-rollback-verified-20260814.json"
    ),
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PREFLIGHT_FRESHNESS = timedelta(minutes=5)


class Item33ExecutionError(RuntimeError):
    """Stable failure code that never includes callback or Secret content."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Item33ExecutionError(code)
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], code: str) -> None:
    if set(value) != keys:
        raise Item33ExecutionError(code)


def _exact_int(value: Any, code: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise Item33ExecutionError(code)
    return value


def _sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Item33ExecutionError(code)
    return value


def _clock(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise Item33ExecutionError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Item33ExecutionError(code) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Item33ExecutionError(code)
    return parsed.astimezone(timezone.utc)


def _trusted_now(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        raise Item33ExecutionError("execution_clock") from None
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Item33ExecutionError("execution_clock")
    return value.astimezone(timezone.utc)


def _invoke(
    callback: Callable[..., Mapping[str, Any]],
    code: str,
    *args: Any,
) -> Mapping[str, Any]:
    try:
        value = callback(*args)
    except Exception:
        raise Item33ExecutionError(f"{code}_outcome_unknown") from None
    return _mapping(value, code)


def _load_verified_dependencies() -> dict[str, dict[str, Any]]:
    """Bind admission to the validated canonical readiness ledger on disk."""

    try:
        import internal_deployment_readiness_gate as readiness_gate

        manifest_path = ROOT / CANONICAL_MANIFEST_REF
        manifest = readiness_gate.load_manifest(manifest_path)
        readiness_gate.validate_manifest(manifest, root=ROOT)
        controls = {
            control["id"]: control
            for layer in manifest["layers"]
            for control in layer["controls"]
        }
        verified: dict[str, dict[str, Any]] = {}
        for control_id, evidence_ref in DEPENDENCY_EVIDENCE_REFS.items():
            control = controls[control_id]
            evidence = control["evidence"]
            if (
                control["status"] != "verified"
                or not isinstance(evidence, list)
                or {"kind": "path", "ref": evidence_ref} not in evidence
            ):
                raise ValueError("unverified dependency")
            evidence_path = ROOT / evidence_ref
            # Parse as JSON as well as hashing the exact validated bytes.  The
            # semantic validators above remain the authority for each item.
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            verified[control_id] = {
                "verified": True,
                "evidence_sha256": hashlib.sha256(
                    evidence_path.read_bytes()
                ).hexdigest(),
            }
            if control_id == "real_xhs_trends":
                bucket = payload["successor"]["budget"]["bucket_date"]
                if date.fromisoformat(bucket).isoformat() != bucket:
                    raise ValueError("invalid Item32 bucket")
                verified[control_id]["terminal_bucket_date"] = bucket
        return verified
    except Exception:
        raise Item33ExecutionError("dependency_unverified") from None


def _validate_dependencies(
    value: Any,
    trusted: Mapping[str, Any],
) -> date:
    dependencies = _mapping(value, "dependencies")
    _exact_keys(
        dependencies,
        {"real_xhs_trends", "internal_failure_rollback"},
        "dependencies",
    )
    for control_id, dependency in dependencies.items():
        item = _mapping(dependency, "dependencies")
        expected_keys = {"verified", "evidence_sha256"}
        if control_id == "real_xhs_trends":
            expected_keys.add("terminal_bucket_date")
        _exact_keys(item, expected_keys, "dependencies")
        if item["verified"] is not True:
            raise Item33ExecutionError("dependency_unverified")
        _sha256(item["evidence_sha256"], "dependencies")
        if item != trusted.get(control_id):
            raise Item33ExecutionError("dependency_unverified")
    try:
        bucket = date.fromisoformat(
            dependencies["real_xhs_trends"]["terminal_bucket_date"]
        )
    except (KeyError, TypeError, ValueError):
        raise Item33ExecutionError("dependency_unverified") from None
    if bucket.isoformat() != dependencies["real_xhs_trends"][
        "terminal_bucket_date"
    ]:
        raise Item33ExecutionError("dependency_unverified")
    return bucket


def _validate_preflight(
    value: Any,
    *,
    now: datetime,
) -> tuple[Mapping[str, Any], int, str, datetime]:
    preflight = _mapping(value, "preflight")
    _exact_keys(
        preflight,
        {
            "observed_at",
            "canonical_sha256",
            "database_role",
            "role_exact",
            "acl_exact",
            "unit_sha256",
            "unit_active",
            "unit_sub",
            "unit_enabled",
            "collection_suspended",
            "formal_container_count",
            "active_run_count",
            "same_bucket_run_count",
            "outcome_unknown_count",
            "unlinked_attempt_count",
            "utc_provider_budget_used_before",
            "utc_provider_budget_remaining_before",
            "provider_calls",
            "production_database_writes",
        },
        "preflight",
    )
    observed_at = _clock(preflight["observed_at"], "preflight_clock")
    used = _exact_int(
        preflight["utc_provider_budget_used_before"], "preflight_budget"
    )
    remaining = _exact_int(
        preflight["utc_provider_budget_remaining_before"],
        "preflight_budget",
    )
    if (
        not observed_at <= now <= observed_at + _PREFLIGHT_FRESHNESS
        or observed_at.date() != now.date()
        or preflight["database_role"] != "noteai_xhs_trends"
        or preflight["role_exact"] is not True
        or preflight["acl_exact"] is not True
        or preflight["unit_sha256"] != SUSPENDED_UNIT_SHA256
        or preflight["unit_active"] != "inactive"
        or preflight["unit_sub"] != "dead"
        or preflight["unit_enabled"] != "disabled"
        or preflight["collection_suspended"] is not True
        or any(
            _exact_int(preflight[field], "preflight") != 0
            for field in (
                "formal_container_count",
                "active_run_count",
                "same_bucket_run_count",
                "outcome_unknown_count",
                "unlinked_attempt_count",
                "provider_calls",
                "production_database_writes",
            )
        )
        or used != 0
        or remaining != PROVIDER_REQUEST_LIMIT
    ):
        raise Item33ExecutionError("preflight")
    return (
        preflight,
        remaining,
        _sha256(preflight["canonical_sha256"], "preflight"),
        observed_at,
    )


def _validate_cycle(
    value: Any,
    *,
    run_identity: str,
    bucket_key: str,
    remaining: int,
    not_before: datetime,
) -> tuple[Mapping[str, Any], datetime]:
    receipt = _mapping(value, "cycle")
    _exact_keys(
        receipt,
        {
            "run_identity_sha256",
            "bucket_key",
            "started_at",
            "completed_at",
            "lease_expires_at",
            "cycle_count",
            "same_bucket_completed_run_count",
            "provider_request_count",
            "provider_request_succeeded",
            "provider_request_failed",
            "outcome_unknown_count",
            "automatic_retry_count",
            "active_admitted_count",
            "challenge_detected",
            "endpoint_counts",
            "published_keyword_count",
            "minimum_real_keyword_count_per_domain",
            "search_result_domain_count",
            "search_recommend_domain_count",
            "quality_snapshot_verified",
            "production_write_set_verified",
            "post_cycle_health",
            "canonical_result_sha256",
        },
        "cycle",
    )
    request_count = _exact_int(
        receipt["provider_request_count"], "cycle", minimum=1
    )
    started_at = _clock(receipt["started_at"], "cycle")
    completed_at = _clock(receipt["completed_at"], "cycle")
    lease_expires_at = _clock(receipt["lease_expires_at"], "cycle")
    endpoint_counts = receipt["endpoint_counts"]
    endpoints_valid = (
        isinstance(endpoint_counts, Mapping)
        and set(endpoint_counts) == set(ENDPOINTS)
        and all(
            _exact_int(value, "cycle") >= 0
            for value in endpoint_counts.values()
        )
        and sum(endpoint_counts.values()) == request_count
        and endpoint_counts["search_recommend"] > 0
        and endpoint_counts["search_notes"] > 0
    )
    if (
        receipt["run_identity_sha256"] != run_identity
        or receipt["bucket_key"] != bucket_key
        or not_before > started_at
        or started_at > completed_at
        or lease_expires_at != started_at + timedelta(minutes=30)
        or completed_at > lease_expires_at
        or completed_at.date().isoformat() != bucket_key
        or _exact_int(receipt["cycle_count"], "cycle") != 1
        or _exact_int(receipt["same_bucket_completed_run_count"], "cycle")
        != 1
        or request_count > remaining
        or _exact_int(receipt["provider_request_succeeded"], "cycle")
        != request_count
        or _exact_int(receipt["provider_request_failed"], "cycle") != 0
        or _exact_int(receipt["outcome_unknown_count"], "cycle") != 0
        or _exact_int(receipt["automatic_retry_count"], "cycle") != 0
        or _exact_int(receipt["active_admitted_count"], "cycle") != 0
        or receipt["challenge_detected"] is not False
        or not endpoints_valid
        or not 72
        <= _exact_int(receipt["published_keyword_count"], "cycle")
        <= 90
        or not 12
        <= _exact_int(
            receipt["minimum_real_keyword_count_per_domain"], "cycle"
        )
        <= 15
        or _exact_int(receipt["search_result_domain_count"], "cycle") != 6
        or _exact_int(receipt["search_recommend_domain_count"], "cycle")
        != 6
        or receipt["quality_snapshot_verified"] is not True
        or receipt["production_write_set_verified"] is not True
        or receipt["post_cycle_health"] != "ready"
    ):
        raise Item33ExecutionError("cycle")
    _sha256(receipt["canonical_result_sha256"], "cycle")
    return receipt, completed_at


def _validate_action(
    value: Any,
    *,
    phase: str,
    expected_before: str,
    expected_after: str,
) -> Mapping[str, Any]:
    receipt = _mapping(value, phase)
    _exact_keys(
        receipt,
        {
            "phase",
            "status",
            "unit_name",
            "before_unit_sha256",
            "after_unit_sha256",
            "mutation_count",
            "other_unit_actions",
            "provider_calls",
            "production_database_writes",
            "canonical_result_sha256",
        },
        phase,
    )
    if (
        receipt["phase"] != phase
        or receipt["status"] != "applied"
        or receipt["unit_name"] != UNIT_NAME
        or receipt["before_unit_sha256"] != expected_before
        or receipt["after_unit_sha256"] != expected_after
        or any(
            _exact_int(receipt[field], phase) != expected
            for field, expected in (
                ("mutation_count", 1),
                ("other_unit_actions", 0),
                ("provider_calls", 0),
                ("production_database_writes", 0),
            )
        )
    ):
        raise Item33ExecutionError(phase)
    _sha256(receipt["canonical_result_sha256"], phase)
    return receipt


def _validate_state(
    value: Any,
    *,
    phase: str,
    active: bool,
    not_before: datetime,
    expected_attempt_count: int | None,
    allow_unresolved: bool = False,
) -> tuple[Mapping[str, Any], datetime]:
    state = _mapping(value, f"{phase}_readback")
    exact_keys = {
        "phase",
        "observed_at",
        "canonical_sha256",
        "unit_sha256",
        "unit_active",
        "unit_sub",
        "unit_enabled",
        "collection_suspended",
        "formal_unit_count",
        "formal_container_count",
        "process_count",
        "active_run_count",
        "active_attempt_count",
        "outcome_unknown_count",
        "unlinked_attempt_count",
        "health",
        "provider_calls",
        "production_database_writes",
        "task_container_count",
        "inspection_container_count",
        "stage_directory_count",
        "runtime_directory_count",
        "temporary_unit_count",
        "temporary_dropin_count",
    }
    if phase in {"rollback", "final"}:
        exact_keys |= {
            "preserved_run_count",
            "preserved_attempt_count",
            "preserved_snapshot_count",
            "database_audit_deletes",
            "same_bucket_new_run_delta",
            "same_bucket_provider_call_delta",
        }
    _exact_keys(
        state,
        exact_keys,
        f"{phase}_readback",
    )
    expected = {
        "unit_sha256": PROMOTED_UNIT_SHA256 if active else SUSPENDED_UNIT_SHA256,
        "unit_active": "active" if active else "inactive",
        "unit_sub": "running" if active else "dead",
        "unit_enabled": "enabled" if active else "disabled",
        "collection_suspended": not active,
        "formal_unit_count": 1,
        "formal_container_count": 1 if active else 0,
        "process_count": 1 if active else 0,
        "health": "ready" if active else "stopped",
    }
    for field in (
        "formal_unit_count",
        "formal_container_count",
        "process_count",
    ):
        _exact_int(state[field], f"{phase}_readback")
    zero_counts = {
        "active_run_count",
        "active_attempt_count",
        "outcome_unknown_count",
        "unlinked_attempt_count",
        "provider_calls",
        "production_database_writes",
        "task_container_count",
        "inspection_container_count",
        "stage_directory_count",
        "runtime_directory_count",
        "temporary_unit_count",
        "temporary_dropin_count",
    }
    for field in zero_counts:
        value = _exact_int(state[field], f"{phase}_readback")
        if not allow_unresolved or field not in {
            "active_run_count",
            "active_attempt_count",
            "outcome_unknown_count",
            "unlinked_attempt_count",
        }:
            expected[field] = 0
        elif value > PROVIDER_REQUEST_LIMIT:
            raise Item33ExecutionError(f"{phase}_readback")
    if phase in {"rollback", "final"} and expected_attempt_count is not None:
        for field in (
            "preserved_run_count",
            "preserved_attempt_count",
            "preserved_snapshot_count",
            "database_audit_deletes",
            "same_bucket_new_run_delta",
            "same_bucket_provider_call_delta",
        ):
            _exact_int(state[field], f"{phase}_readback")
        expected.update(
            {
                "preserved_run_count": 1,
                "preserved_attempt_count": expected_attempt_count,
                "preserved_snapshot_count": 1,
                "database_audit_deletes": 0,
                "same_bucket_new_run_delta": 0,
                "same_bucket_provider_call_delta": 0,
            }
        )
    elif phase in {"rollback", "final"}:
        for field in (
            "preserved_run_count",
            "preserved_attempt_count",
            "preserved_snapshot_count",
            "database_audit_deletes",
            "same_bucket_new_run_delta",
            "same_bucket_provider_call_delta",
        ):
            _exact_int(state[field], f"{phase}_readback")
        expected.update(
            {
                "database_audit_deletes": 0,
                "same_bucket_new_run_delta": 0,
                "same_bucket_provider_call_delta": 0,
            }
        )
    if state["phase"] != phase or any(
        state.get(key) != expected_value for key, expected_value in expected.items()
    ) or state["collection_suspended"] is not (not active):
        raise Item33ExecutionError(f"{phase}_readback")
    observed_at = _clock(state["observed_at"], f"{phase}_readback")
    if observed_at < not_before:
        raise Item33ExecutionError(f"{phase}_readback")
    _sha256(state["canonical_sha256"], f"{phase}_readback")
    return state, observed_at


def execute_item33_promotion(
    *,
    dependencies: Mapping[str, Any],
    run_identity_sha256: str,
    read_preflight: Callable[[], Mapping[str, Any]],
    read_single_cycle: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    promote_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    read_promoted: Callable[[], Mapping[str, Any]],
    rollback_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    read_rollback: Callable[[], Mapping[str, Any]],
    reapply_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    read_final: Callable[[], Mapping[str, Any]],
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    """Run one cycle and one managed promote/rollback/reapply sequence.

    An exception from any callback means the action outcome is UNKNOWN.  The
    controller never retries it or guesses whether another mutation is safe.
    A known post-promotion validation failure receives one rollback attempt;
    rollback or reapply failures remain sealed for read-only reconciliation.
    """

    trusted_dependencies = _load_verified_dependencies()
    item32_bucket = _validate_dependencies(dependencies, trusted_dependencies)
    run_identity = _sha256(run_identity_sha256, "run_identity")
    admission_now = _trusted_now(clock)
    if admission_now.date() <= item32_bucket:
        raise Item33ExecutionError("utc_budget_not_available")
    preflight_value = _invoke(read_preflight, "preflight")
    now = _trusted_now(clock)
    preflight, remaining, preflight_sha, preflight_at = _validate_preflight(
        preflight_value, now=now
    )
    bucket_key = now.date().isoformat()
    authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        "run_identity_sha256": run_identity,
        "bucket_key": bucket_key,
        "previous_item32_bucket_key": item32_bucket.isoformat(),
        "provider_request_limit": PROVIDER_REQUEST_LIMIT,
        "provider_request_budget_remaining": remaining,
        "permitted_endpoints": list(ENDPOINTS),
        "cycle_count": 1,
        "automatic_retry_limit": 0,
        "expected_unit_sha256": SUSPENDED_UNIT_SHA256,
        "preflight_sha256": preflight_sha,
    }
    promotion_authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        "unit_name": UNIT_NAME,
        "run_identity_sha256": run_identity,
        "cycle_authorization": authorization,
        "controller_provider_calls_permitted": 0,
        "controller_database_writes_permitted": 0,
        "other_unit_actions_permitted": 0,
        "automatic_retry_limit": 0,
    }
    recovery_authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        "unit_name": UNIT_NAME,
        "run_identity_sha256": run_identity,
        "provider_calls_permitted": 0,
        "production_database_writes_permitted": 0,
        "other_unit_actions_permitted": 0,
        "automatic_retry_limit": 0,
    }

    promotion_known = False
    rollback_started = False
    try:
        promotion = _validate_action(
            _invoke(promote_unit, "promotion", promotion_authorization),
            phase="promotion",
            expected_before=SUSPENDED_UNIT_SHA256,
            expected_after=PROMOTED_UNIT_SHA256,
        )
        promotion_known = True
        cycle, cycle_completed_at = _validate_cycle(
            _invoke(read_single_cycle, "cycle", authorization),
            run_identity=run_identity,
            bucket_key=bucket_key,
            remaining=remaining,
            not_before=now,
        )
        request_count = int(cycle["provider_request_count"])
        promoted, promoted_at = _validate_state(
            _invoke(read_promoted, "promoted_readback"),
            phase="promoted",
            active=True,
            not_before=cycle_completed_at,
            expected_attempt_count=request_count,
        )
    except Item33ExecutionError:
        if not promotion_known:
            raise
        rollback_started = True
        try:
            _validate_action(
                _invoke(rollback_unit, "rollback", recovery_authorization),
                phase="rollback",
                expected_before=PROMOTED_UNIT_SHA256,
                expected_after=SUSPENDED_UNIT_SHA256,
            )
            _validate_state(
                _invoke(read_rollback, "rollback_readback"),
                phase="rollback",
                active=False,
                not_before=preflight_at,
                expected_attempt_count=(
                    int(cycle["provider_request_count"])
                    if "cycle" in locals()
                    else None
                ),
                allow_unresolved="cycle" not in locals(),
            )
        except Item33ExecutionError:
            raise Item33ExecutionError("recovery_failed") from None
        raise

    rollback_started = True
    rollback = _validate_action(
        _invoke(rollback_unit, "rollback", recovery_authorization),
        phase="rollback",
        expected_before=PROMOTED_UNIT_SHA256,
        expected_after=SUSPENDED_UNIT_SHA256,
    )
    rollback_state, rollback_at = _validate_state(
        _invoke(read_rollback, "rollback_readback"),
        phase="rollback",
        active=False,
        not_before=promoted_at,
        expected_attempt_count=request_count,
    )
    reapply = _validate_action(
        _invoke(reapply_unit, "reapply", recovery_authorization),
        phase="reapply",
        expected_before=SUSPENDED_UNIT_SHA256,
        expected_after=PROMOTED_UNIT_SHA256,
    )
    final, final_at = _validate_state(
        _invoke(read_final, "final_readback"),
        phase="final",
        active=True,
        not_before=rollback_at,
        expected_attempt_count=request_count,
    )
    observed_at = _trusted_now(clock)
    if observed_at < now or observed_at < final_at:
        raise Item33ExecutionError("execution_clock")
    return {
        "schema": RESULT_SCHEMA,
        "status": "VERIFIED",
        "readiness_credit": False,
        "observed_at": observed_at.isoformat(),
        "run_identity_sha256": run_identity,
        "bucket_key": bucket_key,
        "authorization": authorization,
        "preflight": dict(preflight),
        "cycle": dict(cycle),
        "promotion": dict(promotion),
        "promoted_readback": dict(promoted),
        "rollback": dict(rollback),
        "rollback_readback": dict(rollback_state),
        "reapply": dict(reapply),
        "final_readback": dict(final),
        "action_counts": {
            "cycle": 1,
            "promotion": 1,
            "rollback": 1 if rollback_started else 0,
            "reapply": 1,
            "automatic_retry": 0,
        },
        "secret_values_recorded": False,
    }


__all__ = [
    "AUTHORIZATION_SCHEMA",
    "ENDPOINTS",
    "Item33ExecutionError",
    "PROMOTED_UNIT_SHA256",
    "PROVIDER_REQUEST_LIMIT",
    "RESULT_SCHEMA",
    "SUSPENDED_UNIT_SHA256",
    "UNIT_NAME",
    "execute_item33_promotion",
]
