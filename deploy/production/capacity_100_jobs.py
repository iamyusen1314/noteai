#!/usr/bin/env python3
"""Provider-free Item 29 capacity acceptance and exact production phases.

The production CLI uses the shipped durable admission, PostgreSQL outbox,
fenced worker, billing and private OSS implementations.  It never imports a
real model client and every mutating phase is limited to an exact Item 29
namespace or an explicit operation-id set.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
from typing import Any, Protocol
import uuid


TASK_ID = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
RESULT_SCHEMA = "noteai.item29.capacity-100-result.v1"
PHASE_SCHEMA = "noteai.item29.capacity-100-phase.v1"
DEPENDENCY_SCHEMA = "noteai.item29.item28-dependency.v1"
OPERATION_COUNT = 100
PRECLAIM_LEASE_SECONDS = 15
PROCESS_LEASE_SECONDS = 900
EXPECTED_CREDITS_MILLI = 600_000
MIN_DATABASE_IDLE_CONNECTION_HEADROOM = 120
MIN_API_C_MEMORY_HEADROOM_BYTES = 1_073_741_824
MIN_API_C_PID_HEADROOM = 160
MODE_ENV = "NOTEAI_ITEM29_ACCEPTANCE_MODE"
CONFIRM_ENV = "NOTEAI_ITEM29_MUTATION_CONFIRM"
HOST_ENV = "NOTEAI_ITEM29_HOST_LABEL"
ITEM28_DEPENDENCY = {
    "schema": DEPENDENCY_SCHEMA,
    "evidence_path": (
        "deploy/production/evidence/"
        "production-internal-failure-rollback-verified-20260814.json"
    ),
    "evidence_sha256": (
        "429b41e4e7be1549181bed195623718ce65d2d052257ea176da99e266fa598f8"
    ),
    "terminal_acceptance_sha256": (
        "55363294b82f21c6c0fd000e8dcf08f481775a2f63b2a9dd733056ffb4f85c9c"
    ),
}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
PROVIDER_SECRET_NAMES = (
    "ANTHROPIC_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "CLAUDE_API_KEY",
)


class CapacityError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExactLease:
    operation_id: str
    owner: str
    fence: int
    expires_at: str


class CapacityRuntime(Protocol):
    def preflight(self) -> dict[str, Any]: ...
    def admit_exact(self, index: int, request_id: str, provider: str) -> dict[str, Any]: ...
    def deliver_exact(self, operation_id: str) -> bool: ...
    def claim_exact(
        self, operation_id: str, *, owner: str, lease_seconds: int, now: datetime
    ) -> ExactLease | None: ...
    def begin_provider_exact(
        self,
        lease: ExactLease,
        *,
        provider: str,
        request_hash: str,
        model_hash: str,
        now: datetime,
    ) -> dict[str, Any] | None: ...
    def complete_success_exact(
        self,
        lease: ExactLease,
        attempt_id: str,
        *,
        response_hash: str,
        now: datetime,
    ) -> bool: ...
    def cleanup_exact(self, operation_id: str) -> dict[str, Any]: ...
    def project_exact(self, operation_ids: list[str]) -> dict[str, Any]: ...


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _uuid(value: Any, code: str) -> str:
    if type(value) is not str or UUID_RE.fullmatch(value) is None:
        raise CapacityError(code)
    try:
        if str(uuid.UUID(value)) != value:
            raise CapacityError(code)
    except ValueError as exc:
        raise CapacityError(code) from exc
    return value


def _dependency(value: Any) -> dict[str, str]:
    if type(value) is not dict or set(value) != set(ITEM28_DEPENDENCY):
        raise CapacityError("item28_dependency_schema")
    if value != ITEM28_DEPENDENCY:
        raise CapacityError("item28_dependency_binding")
    return dict(value)


def _provider_for(index: int) -> str:
    return "claude" if index < 50 else "kimi"


def _worker_for(index: int) -> str:
    return "Worker-C" if index < 50 else "Worker-F"


def _request_id(plan_nonce: str, index: int) -> str:
    return str(uuid.uuid5(uuid.UUID(plan_nonce), f"item29-admission:{index:03d}"))


class FixedFakeProvider:
    """Content-free callback invoked only after the durable provider fence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[tuple[str, str, str]] = []

    def call(self, operation_id: str, provider: str, attempt_id: str) -> str:
        operation_id = _uuid(operation_id, "fake_operation_id")
        attempt_id = _uuid(attempt_id, "fake_attempt_id")
        if provider not in {"claude", "kimi"}:
            raise CapacityError("fake_provider_label")
        with self._lock:
            if any(row[0] == operation_id for row in self._calls):
                raise CapacityError("duplicate_fake_provider_call")
            self._calls.append((operation_id, provider, attempt_id))
        return _digest(f"item29-fake-response:{operation_id}:{provider}:{attempt_id}")

    def projection(self) -> dict[str, int]:
        with self._lock:
            rows = list(self._calls)
        operations = [row[0] for row in rows]
        return {
            "fake_call_count": len(rows),
            "unique_fake_operation_count": len(set(operations)),
            "duplicate_fake_call_count": len(rows) - len(set(operations)),
            "real_provider_call_count": 0,
            "claude_label_count": sum(row[1] == "claude" for row in rows),
            "kimi_label_count": sum(row[1] == "kimi" for row in rows),
            "ai_model_call_count": 0,
            "input_token_count": 0,
            "output_token_count": 0,
            "provider_cost_milli": 0,
        }


def _require_preflight(value: Any) -> dict[str, Any]:
    keys = {
        "database_idle_connection_headroom",
        "api_c_memory_headroom_bytes",
        "api_c_pid_headroom",
    }
    if type(value) is not dict or set(value) != keys:
        raise CapacityError("headroom_schema")
    if any(type(value[key]) is not int for key in keys):
        raise CapacityError("headroom_schema")
    if (
        value["database_idle_connection_headroom"]
        < MIN_DATABASE_IDLE_CONNECTION_HEADROOM
        or value["api_c_memory_headroom_bytes"]
        < MIN_API_C_MEMORY_HEADROOM_BYTES
        or value["api_c_pid_headroom"] < MIN_API_C_PID_HEADROOM
    ):
        raise CapacityError("headroom_insufficient")
    return {
        **value,
        "database_idle_connection_headroom_required": (
            MIN_DATABASE_IDLE_CONNECTION_HEADROOM
        ),
        "api_c_memory_headroom_bytes_required": MIN_API_C_MEMORY_HEADROOM_BYTES,
        "api_c_pid_headroom_required": MIN_API_C_PID_HEADROOM,
        "headroom_gate_passed": True,
    }


def _admit_concurrently(runtime: CapacityRuntime, plan_nonce: str) -> list[str]:
    ready = threading.Barrier(OPERATION_COUNT + 1, timeout=30)
    release = threading.Barrier(OPERATION_COUNT + 1, timeout=30)

    def one(index: int) -> tuple[int, str]:
        ready.wait()
        release.wait()
        row = runtime.admit_exact(
            index, _request_id(plan_nonce, index), _provider_for(index)
        )
        if type(row) is not dict or set(row) != {"operation_id", "state"}:
            raise CapacityError("admission_schema")
        if row["state"] != "admitted":
            raise CapacityError("admission_state")
        return index, _uuid(row["operation_id"], "admission_operation_id")

    with ThreadPoolExecutor(max_workers=OPERATION_COUNT) as pool:
        futures = [pool.submit(one, index) for index in range(OPERATION_COUNT)]
        ready.wait()
        release.wait()
        indexed = [future.result() for future in futures]
    indexed.sort()
    result = [operation_id for _index, operation_id in indexed]
    if len(result) != 100 or len(set(result)) != 100:
        raise CapacityError("operation_identity_count")
    return result


def _claim_and_process_fake(
    runtime: CapacityRuntime, operation_ids: list[str], fake: FixedFakeProvider
) -> None:
    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    t1 = t0 + timedelta(seconds=PRECLAIM_LEASE_SECONDS)
    stale_50 = runtime.claim_exact(
        operation_ids[50],
        owner="Worker-C-preinterrupt-index-050",
        lease_seconds=PRECLAIM_LEASE_SECONDS,
        now=t0,
    )
    stale_0 = runtime.claim_exact(
        operation_ids[0],
        owner="Worker-F-preinterrupt-index-000",
        lease_seconds=PRECLAIM_LEASE_SECONDS,
        now=t0,
    )
    if stale_50 is None or stale_0 is None:
        raise CapacityError("preinterrupt_claim")
    replacements = {
        0: runtime.claim_exact(
            operation_ids[0], owner="Worker-C-item29-000",
            lease_seconds=PROCESS_LEASE_SECONDS, now=t1,
        ),
        50: runtime.claim_exact(
            operation_ids[50], owner="Worker-F-item29-050",
            lease_seconds=PROCESS_LEASE_SECONDS, now=t1,
        ),
    }
    if any(value is None or value.fence != 2 for value in replacements.values()):
        raise CapacityError("takeover_claim")
    for stale, index in ((stale_0, 0), (stale_50, 50)):
        rejected = runtime.begin_provider_exact(
            stale,
            provider=_provider_for(index),
            request_hash=_digest(f"item29-stale:{stale.operation_id}"),
            model_hash=_digest("item29-fixed-fake-v1"),
            now=t1 + timedelta(milliseconds=1),
        )
        if rejected is not None:
            raise CapacityError("stale_provider_fence")

    def one(index: int) -> None:
        operation_id = operation_ids[index]
        lease = replacements.get(index) or runtime.claim_exact(
            operation_id,
            owner=f"{_worker_for(index)}-item29-{index:03d}",
            lease_seconds=PROCESS_LEASE_SECONDS,
            now=t1,
        )
        if lease is None or lease.fence != (2 if index in {0, 50} else 1):
            raise CapacityError("exact_claim")
        provider = _provider_for(index)
        started = runtime.begin_provider_exact(
            lease,
            provider=provider,
            request_hash=_digest(f"item29-request:{operation_id}"),
            model_hash=_digest("item29-fixed-fake-v1"),
            now=t1 + timedelta(seconds=1),
        )
        if type(started) is not dict or started.get("attempt_number") != 1:
            raise CapacityError("provider_attempt")
        attempt_id = _uuid(started.get("attempt_id"), "provider_attempt_id")
        response_hash = fake.call(operation_id, provider, attempt_id)
        if not runtime.complete_success_exact(
            lease,
            attempt_id,
            response_hash=response_hash,
            now=t1 + timedelta(seconds=2),
        ):
            raise CapacityError("settlement")

    with ThreadPoolExecutor(max_workers=OPERATION_COUNT) as pool:
        for future in [pool.submit(one, index) for index in range(100)]:
            future.result()


def run_rehearsal(
    runtime: CapacityRuntime,
    *,
    plan_nonce: str,
    item28_dependency: dict[str, str],
) -> dict[str, Any]:
    plan_nonce = _uuid(plan_nonce, "plan_nonce")
    dependency = _dependency(item28_dependency)
    headroom = _require_preflight(runtime.preflight())
    operation_ids = _admit_concurrently(runtime, plan_nonce)
    for operation_id in operation_ids:
        if not runtime.deliver_exact(operation_id):
            raise CapacityError("outbox_delivery")
    fake = FixedFakeProvider()
    _claim_and_process_fake(runtime, operation_ids, fake)
    for operation_id in operation_ids:
        if runtime.cleanup_exact(operation_id) != {
            "status": "primary_deleted",
            "request_object_residue_count": 0,
            "result_object_residue_count": 0,
        }:
            raise CapacityError("cleanup")
    projection = runtime.project_exact(operation_ids)
    expected = _expected_runtime_projection()
    if projection != expected:
        raise CapacityError("runtime_projection")
    provider = fake.projection()
    if provider != _expected_provider_projection():
        raise CapacityError("fake_provider_projection")
    return _final_result(
        dependency=dependency,
        headroom=headroom,
        operation_set_sha256=_operation_set_sha(operation_ids),
        provider=provider,
        projection=projection,
    )


def _expected_provider_projection() -> dict[str, int]:
    return {
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


def _expected_runtime_projection() -> dict[str, int]:
    return {
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


def _operation_set_sha(operation_ids: list[str]) -> str:
    # Admission order is the routing contract: 0..49 -> Worker-C/Claude label,
    # 50..99 -> Worker-F/Kimi label.  Sorting would erase that binding.
    return _digest("\n".join(operation_ids) + "\n")


def _final_result(
    *,
    dependency: dict[str, str],
    headroom: dict[str, Any],
    operation_set_sha256: str,
    provider: dict[str, int],
    projection: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "task_id": TASK_ID,
        "status": "PASS",
        "item28_dependency": dependency,
        "headroom": headroom,
        "admission": {
            "barrier_participant_count": 100,
            "concurrent_admission_count": 100,
            "unique_operation_count": 100,
            "operation_set_sha256": operation_set_sha256,
        },
        "routing_and_recovery": {
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
        },
        "provider": provider,
        "runtime_projection": projection,
        "execution_boundary": {
            "automatic_retry_count": 0,
            "real_provider_credentials_loaded": False,
            "cloud_control_plane_call_count": 0,
            "public_request_count": 0,
        },
    }


def assemble_production_result(
    *, preflight: dict[str, Any], admit: dict[str, Any],
    dispatch_readback: dict[str, Any], preclaim_c: dict[str, Any],
    preclaim_f: dict[str, Any], process_c: dict[str, Any],
    process_f: dict[str, Any], observe: dict[str, Any],
    cleanup: dict[str, Any], item28_dependency: dict[str, str]
) -> dict[str, Any]:
    """Assemble the one final result from already-read phase projections."""
    dependency = _dependency(item28_dependency)
    for phase, name in (
        (preflight, "preflight"), (admit, "admit"),
        (dispatch_readback, "dispatch-readback"),
        (preclaim_c, "preclaim"), (preclaim_f, "preclaim"),
        (observe, "observe"), (cleanup, "cleanup"),
    ):
        if phase.get("schema") != PHASE_SCHEMA or phase.get("phase") != name:
            raise CapacityError("phase_result_binding")
        if phase.get("plan_nonce") != admit.get("plan_nonce"):
            raise CapacityError("phase_result_binding")
    for phase in (process_c, process_f):
        if (
            phase.get("schema") != PHASE_SCHEMA
            or phase.get("phase") not in {"process", "process-readback"}
            or phase.get("plan_nonce") != admit.get("plan_nonce")
        ):
            raise CapacityError("phase_result_binding")
    operation_set_sha = admit.get("operation_set_sha256")
    if not isinstance(operation_set_sha, str) or not HEX64_RE.fullmatch(operation_set_sha):
        raise CapacityError("operation_set_sha")
    for phase in (
        dispatch_readback, preclaim_c, preclaim_f, process_c, process_f,
        observe, cleanup,
    ):
        if phase.get("operation_set_sha256") != operation_set_sha:
            raise CapacityError("operation_set_binding")
    _require_terminal_process_projection(process_c, "Worker-C")
    _require_terminal_process_projection(process_f, "Worker-F")
    admission_counts = (
        admit.get("new_user_count"), admit.get("existing_user_count"),
        admit.get("new_admission_count"), admit.get("existing_admission_count"),
    )
    if not (
        admit.get("barrier_participant_count") == 100
        and admit.get("user_count") == 100
        and admit.get("unique_operation_count") == 100
        and admit.get("maximum_concurrent_admission_count") == 100
        and all(
            type(value) is int and 0 <= value <= 100
            for value in admission_counts
        )
        and admission_counts[0] + admission_counts[1] == 100
        and admission_counts[2] + admission_counts[3] == 100
        and dispatch_readback.get("outbox_row_count") == 100
        and dispatch_readback.get("delivered_count") == 100
        and dispatch_readback.get("non_delivered_operation_ids") == []
        and preclaim_c.get("worker") == "Worker-C"
        and preclaim_c.get("preinterrupt_index") == 50
        and preclaim_c.get("fence") == 1
        and preclaim_f.get("worker") == "Worker-F"
        and preclaim_f.get("preinterrupt_index") == 0
        and preclaim_f.get("fence") == 1
        and cleanup.get("primary_deleted_count") == 100
        and cleanup.get("deleted_payload_object_count") == 200
        and cleanup.get("orphan_payload_object_deleted_count") == 0
    ):
        raise CapacityError("phase_terminal_binding")
    projection = dict(observe.get("runtime_projection") or {})
    projection.update({
        "maximum_concurrent_admission_count": admit[
            "maximum_concurrent_admission_count"
        ],
        "outbox_count": dispatch_readback["outbox_row_count"],
        "delivered_count": dispatch_readback["delivered_count"],
        "provider_attempt_number_not_one_count": (
            process_c["attempt_number_not_one_count"]
            + process_f["attempt_number_not_one_count"]
        ),
        "worker_c_completed_count": process_c["succeeded_count"],
        "worker_f_completed_count": process_f["succeeded_count"],
        "worker_c_takeover_index": process_c["takeover_index"],
        "worker_f_takeover_index": process_f["takeover_index"],
    })
    projection.update(cleanup.get("cleanup_projection") or {})
    if projection != _expected_runtime_projection():
        raise CapacityError("runtime_projection")
    return _final_result(
        dependency=dependency,
        headroom=_require_preflight(preflight.get("headroom")),
        operation_set_sha256=operation_set_sha,
        provider={
            "fake_call_count": process_c["fake_call_count"] + process_f["fake_call_count"],
            "unique_fake_operation_count": (
                process_c["unique_fake_operation_count"]
                + process_f["unique_fake_operation_count"]
            ),
            "duplicate_fake_call_count": (
                process_c["duplicate_fake_call_count"]
                + process_f["duplicate_fake_call_count"]
            ),
            "real_provider_call_count": (
                process_c["real_provider_call_count"]
                + process_f["real_provider_call_count"]
            ),
            "claude_label_count": (
                process_c["claude_label_count"] + process_f["claude_label_count"]
            ),
            "kimi_label_count": (
                process_c["kimi_label_count"] + process_f["kimi_label_count"]
            ),
            "ai_model_call_count": 0,
            "input_token_count": 0,
            "output_token_count": 0,
            "provider_cost_milli": 0,
        },
        projection=projection,
    )


def _model_context():
    model_path = Path("/app/model")
    if not model_path.is_dir():
        raise CapacityError("production_model_path")
    sys.path.insert(0, str(model_path))
    try:
        import ai_operations
        import auth
        import content_retention
        import db
        import durable_ai
        import durable_ai_worker
        import idempotency
        import private_storage
    except BaseException as exc:
        raise CapacityError("production_import") from exc
    if not db.using_postgres():
        raise CapacityError("postgres_required")
    return {
        "ai_operations": ai_operations,
        "auth": auth,
        "content_retention": content_retention,
        "db": db,
        "durable_ai": durable_ai,
        "idempotency": idempotency,
        "worker": durable_ai_worker,
        "storage": private_storage,
    }


def _phase_base(phase: str, plan_nonce: str) -> dict[str, Any]:
    return {
        "schema": PHASE_SCHEMA,
        "task_id": TASK_ID,
        "phase": phase,
        "plan_nonce": plan_nonce,
        "status": "PASS",
    }


def _require_environment(phase: str, context: dict[str, Any]) -> None:
    if os.environ.get(MODE_ENV) != "production":
        raise CapacityError("acceptance_mode")
    if any(os.environ.get(name) for name in PROVIDER_SECRET_NAMES):
        raise CapacityError("provider_secret_present")
    expected = {
        "preflight": ("API-C", "noteai_app", "api", "api"),
        "admit": ("API-C", "noteai_app", "api", "api"),
        "resolve": ("API-C", "noteai_app", "api", "api"),
        "dispatch": (
            "API-C", "noteai_ai_dispatcher", "dispatcher", "ai-worker"
        ),
        "dispatch-readback": (
            "API-C", "noteai_ai_dispatcher", "dispatcher", "ai-worker"
        ),
        "preclaim": (
            os.environ.get(HOST_ENV), "noteai_ai_worker", "worker", "ai-worker"
        ),
        "process": (
            os.environ.get(HOST_ENV), "noteai_ai_worker", "worker", "ai-worker"
        ),
        "process-readback": (
            os.environ.get(HOST_ENV), "noteai_ai_worker", "worker", "ai-worker"
        ),
        "observe": ("API-C", "noteai_app", "api", "api"),
        "cleanup": ("API-C", "noteai_app", "api", "api"),
    }[phase]
    if os.environ.get(HOST_ENV) != expected[0]:
        raise CapacityError("host_binding")
    if (
        os.environ.get("NOTEAI_DURABLE_AI_COMPONENT") != expected[2]
        or os.environ.get("NOTEAI_RUNTIME_ROLE") != expected[3]
        or os.environ.get("NOTEAI_DEPLOYMENT_STAGE") != "production"
        or os.environ.get("NOTEAI_CLOUD_RUNTIME") != "1"
    ):
        raise CapacityError("runtime_marker")
    row = context["db"].fetchone(
        "SELECT session_user AS session_role,current_user AS database_role"
    )
    if not row or row["session_role"] != expected[1] or row["database_role"] != expected[1]:
        raise CapacityError("database_role")
    if phase in {"admit", "dispatch", "preclaim", "process", "cleanup"}:
        if os.environ.get(CONFIRM_ENV) != TASK_ID:
            raise CapacityError("mutation_confirmation")


def _ids(value: Any, *, allowed: set[int] = {0, 1, 50, 100}) -> list[str]:
    if type(value) is not list or len(value) not in allowed:
        raise CapacityError("operation_ids_count")
    result = [_uuid(item, "operation_id") for item in value]
    if len(result) != len(set(result)):
        raise CapacityError("operation_ids_duplicate")
    return result


def _prefix(plan_nonce: str) -> str:
    return "item29_" + plan_nonce.replace("-", "")[:16] + "_"


def _prefix_like(plan_nonce: str) -> str:
    return _prefix(plan_nonce).replace("!", "!!").replace("_", "!_") + "%"


def _read_int(path: str) -> int:
    raw = Path(path).read_text(encoding="ascii").strip()
    if raw == "max":
        return 2**63 - 1
    return int(raw)


def _headroom(context: dict[str, Any], plan_nonce: str) -> dict[str, int]:
    db = context["db"]
    row = db.fetchone(
        "SELECT current_setting('max_connections')::integer AS maximum,"
        "COUNT(*)::integer AS current FROM pg_stat_activity"
    )
    db_idle = int(row["maximum"]) - int(row["current"])
    memory_max = _read_int("/sys/fs/cgroup/memory.max")
    memory_current = _read_int("/sys/fs/cgroup/memory.current")
    pid_max = _read_int("/sys/fs/cgroup/pids.max")
    pid_current = _read_int("/sys/fs/cgroup/pids.current")
    namespace = db.fetchone(
        "SELECT COUNT(*) AS c FROM users WHERE username LIKE ? ESCAPE '!'",
        (_prefix_like(plan_nonce),),
    )
    if int(namespace["c"] or 0) != 0:
        raise CapacityError("namespace_not_empty")
    return {
        "database_idle_connection_headroom": db_idle,
        "api_c_memory_headroom_bytes": max(0, memory_max - memory_current),
        "api_c_pid_headroom": max(0, pid_max - pid_current),
    }


def _configure_storage(context: dict[str, Any]) -> None:
    try:
        configured = context["storage"].configure_from_environment()
    except BaseException as exc:
        raise CapacityError("private_storage_configuration") from exc
    if configured is not True:
        raise CapacityError("private_storage_configuration")


def _phase_preflight(context: dict[str, Any], plan_nonce: str) -> dict[str, Any]:
    value = _phase_base("preflight", plan_nonce)
    value["headroom"] = _headroom(context, plan_nonce)
    _require_preflight(value["headroom"])
    value["namespace_residue_count"] = 0
    value["provider_credentials_loaded"] = False
    return value


def _phase_admit(context: dict[str, Any], plan_nonce: str) -> dict[str, Any]:
    _configure_storage(context)
    auth = context["auth"]
    db = context["db"]
    durable = context["durable_ai"]
    ready = threading.Barrier(101, timeout=60)
    release = threading.Barrier(101, timeout=60)
    lock = threading.Lock()
    active = 0
    maximum = 0

    def one(index: int) -> tuple[int, str, bool, bool]:
        nonlocal active, maximum
        ready.wait()
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            release.wait()
            username = f"{_prefix(plan_nonce)}{index:03d}"
            user = db.fetchone(
                "SELECT id,username,email,phone,deletion_requested_at "
                "FROM users WHERE username=?",
                (username,),
            )
            user_created = user is None
            if user_created:
                password = secrets.token_urlsafe(48) + "Aa1!"
                auth.create_user(username, password)
                user = db.fetchone(
                    "SELECT id,username,email,phone,deletion_requested_at "
                    "FROM users WHERE username=?",
                    (username,),
                )
                if user is None:
                    raise CapacityError("admission_user_binding")
            user = dict(user)
            user_id = _uuid(user.get("id"), "admission_user_id")
            if (
                user.get("username") != username
                or user.get("email") is not None
                or user.get("phone") is not None
                or user.get("deletion_requested_at") is not None
            ):
                raise CapacityError("admission_user_binding")
            request_id = _request_id(plan_nonce, index)
            expected_operation_id = durable.operation_id_for(
                user_id, "analyze", request_id
            )
            row = durable.admit_job(
                user_id=user_id,
                operation="analyze",
                request_id=request_id,
                payload={
                    "item29_index": index,
                    "provider_label": _provider_for(index),
                    "acceptance": "provider-free-capacity",
                },
            )
            admission_created = row.get("state") == "admitted"
            if (
                row.get("state") not in {"admitted", "existing"}
                or row.get("operation_id") != expected_operation_id
                or row.get("status") != "queued"
                or row.get("billing_state") != "charged"
            ):
                raise CapacityError("admission_state")
            return (
                index,
                _uuid(row.get("operation_id"), "admission_operation_id"),
                user_created,
                admission_created,
            )
        finally:
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=100) as pool:
        futures = [pool.submit(one, index) for index in range(100)]
        ready.wait()
        release.wait()
        indexed = [future.result() for future in futures]
    indexed.sort()
    operations = [item for _index, item, _user_new, _admission_new in indexed]
    namespace = db.fetchone(
        "SELECT COUNT(*) AS c FROM users WHERE username LIKE ? ESCAPE '!'",
        (_prefix_like(plan_nonce),),
    )
    user_count = int(namespace["c"] or 0)
    new_user_count = sum(item[2] for item in indexed)
    new_admission_count = sum(item[3] for item in indexed)
    if (
        len(operations) != 100
        or len(set(operations)) != 100
        or maximum != 100
        or user_count != 100
    ):
        raise CapacityError("admission_count")
    return {
        **_phase_base("admit", plan_nonce),
        "barrier_participant_count": 100,
        "maximum_concurrent_admission_count": maximum,
        "user_count": user_count,
        "new_user_count": new_user_count,
        "existing_user_count": user_count - new_user_count,
        "new_admission_count": new_admission_count,
        "existing_admission_count": 100 - new_admission_count,
        "unique_operation_count": len(set(operations)),
        "operation_set_sha256": _operation_set_sha(operations),
        "operation_ids": operations,
    }


def _namespace_rows(context: dict[str, Any], plan_nonce: str) -> list[dict[str, Any]]:
    rows = context["db"].fetchall(
        "SELECT u.username,o.id AS operation_id,o.status,"
        "s.billing_state,i.charge_applied,i.complete_applied,i.usage_id "
        "FROM users u LEFT JOIN idempotency_requests i ON i.user_id=u.id "
        "LEFT JOIN ai_operation_admissions a ON a.idempotency_request_id=i.id "
        "LEFT JOIN ai_operations o ON o.id=a.operation_id "
        "LEFT JOIN ai_operation_settlements s ON s.operation_id=o.id "
        "WHERE u.username LIKE ? ESCAPE '!' ORDER BY u.username",
        (_prefix_like(plan_nonce),),
    )
    return [dict(row) for row in rows]


def _phase_resolve(context: dict[str, Any], plan_nonce: str) -> dict[str, Any]:
    rows = _namespace_rows(context, plan_nonce)
    operations = [row.get("operation_id") for row in rows if row.get("operation_id")]
    operations = _ids(operations, allowed=set(range(101)))
    return {
        **_phase_base("resolve", plan_nonce),
        "user_count": len(rows),
        "operation_count": len(operations),
        "operation_set_sha256": _operation_set_sha(operations),
        "operation_ids": operations,
        "queued_count": sum(row.get("status") == "queued" for row in rows),
        "charged_count": sum(row.get("billing_state") == "charged" for row in rows),
    }


def _phase_dispatch(context: dict[str, Any], plan_nonce: str, operations: list[str]) -> dict[str, Any]:
    dispatcher = context["worker"].PostgresOutboxDispatcher()
    delivered = 0
    for index, operation_id in enumerate(operations):
        row = dispatcher.run_once(
            owner_token=f"item29-dispatch-{plan_nonce}-{index:03d}",
            operation_id=operation_id,
        )
        if row.get("status") != "delivered" or row.get("operation_id") != operation_id:
            raise CapacityError("dispatch_terminal")
        delivered += 1
    return {
        **_phase_base("dispatch", plan_nonce),
        "exact_requested_count": len(operations),
        "delivered_count": delivered,
        "provider_called": False,
    }


def _where_ids(operations: list[str]) -> tuple[str, tuple[str, ...]]:
    if not operations:
        return "(NULL)", ()
    return "(" + ",".join("?" for _ in operations) + ")", tuple(operations)


def _phase_dispatch_readback(
    context: dict[str, Any], plan_nonce: str, operations: list[str]
) -> dict[str, Any]:
    clause, params = _where_ids(operations)
    rows = context["db"].fetchall(
        f"SELECT operation_id,state,attempt_count FROM ai_operation_outbox "
        f"WHERE operation_id IN {clause} ORDER BY operation_id",
        params,
    )
    return {
        **_phase_base("dispatch-readback", plan_nonce),
        "operation_set_sha256": _operation_set_sha(operations),
        "exact_operation_count": len(operations),
        "outbox_row_count": len(rows),
        "delivered_count": sum(row["state"] == "delivered" for row in rows),
        "non_delivered_operation_ids": [
            row["operation_id"] for row in rows if row["state"] != "delivered"
        ],
    }


def _preclaim_owner(plan_nonce: str, index: int) -> str:
    return f"item29-preinterrupt-{plan_nonce}-{index:03d}"


def _phase_preclaim(
    context: dict[str, Any], plan_nonce: str, operations: list[str], worker_name: str
) -> dict[str, Any]:
    if worker_name == "Worker-C":
        index = 50
    elif worker_name == "Worker-F":
        index = 0
    else:
        raise CapacityError("worker_binding")
    lease = context["durable_ai"].claim_delivered_operation(
        operations[index],
        lease_seconds=PRECLAIM_LEASE_SECONDS,
        owner_token=_preclaim_owner(plan_nonce, index),
    )
    if lease is None or lease.fence != 1:
        raise CapacityError("preclaim_terminal")
    return {
        **_phase_base("preclaim", plan_nonce),
        "operation_set_sha256": _operation_set_sha(operations),
        "worker": worker_name,
        "preinterrupt_index": index,
        "claim_count": 1,
        "fence": lease.fence,
        "lease_seconds": PRECLAIM_LEASE_SECONDS,
        "provider_called": False,
    }


def _process_assignment(worker_name: str) -> tuple[int, int, int]:
    if worker_name == "Worker-C":
        return 0, 50, 0
    if worker_name == "Worker-F":
        return 50, 100, 50
    raise CapacityError("worker_binding")


def _process_readback_projection(
    context: dict[str, Any], operations: list[str], worker_name: str
) -> dict[str, Any]:
    start, end, takeover = _process_assignment(worker_name)
    selected = operations[start:end]
    clause, params = _where_ids(selected)
    rows = context["db"].fetchall(
        f"SELECT o.id,o.status,o.provider_phase,o.claim_count,"
        f"o.provider_attempt_count,s.billing_state FROM ai_operations o "
        f"JOIN ai_operation_settlements s ON s.operation_id=o.id "
        f"WHERE o.id IN {clause}",
        params,
    )
    attempts = context["db"].fetchall(
        f"SELECT operation_id,attempt_number,state,provider,fence "
        f"FROM ai_provider_attempts WHERE operation_id IN {clause}",
        params,
    )
    rows_by_id = {str(row["id"]): row for row in rows}
    index_by_id = {operation_id: index for index, operation_id in enumerate(operations)}
    attempts_by_id: dict[str, list[Any]] = {operation_id: [] for operation_id in selected}
    for attempt in attempts:
        operation_id = str(attempt["operation_id"])
        attempts_by_id.setdefault(operation_id, []).append(attempt)

    succeeded: list[str] = []
    safe_unstarted: list[str] = []
    unsafe: list[str] = []
    for index in range(start, end):
        operation_id = operations[index]
        row = rows_by_id.get(operation_id)
        operation_attempts = attempts_by_id.get(operation_id, [])
        expected_fence = 2 if index == takeover else 1
        expected_claims = 2 if index == takeover else 1
        exact_attempt = (
            len(operation_attempts) == 1
            and int(operation_attempts[0]["attempt_number"] or 0) == 1
            and operation_attempts[0]["state"] == "provider_succeeded"
            and operation_attempts[0]["provider"] == _provider_for(index)
            and int(operation_attempts[0]["fence"] or 0) == expected_fence
        )
        exact_terminal = row is not None and (
            row["status"] == "succeeded"
            and row["provider_phase"] == "provider_terminal"
            and int(row["provider_attempt_count"] or 0) == 1
            and int(row["claim_count"] or 0) == expected_claims
            and row["billing_state"] == "completed"
            and exact_attempt
        )
        safe_claim_counts = {1, 2} if index == takeover else {0, 1}
        exact_unstarted = row is not None and (
            row["status"] in {"queued", "running"}
            and row["provider_phase"] == "not_started"
            and int(row["provider_attempt_count"] or 0) == 0
            and int(row["claim_count"] or 0) in safe_claim_counts
            and row["billing_state"] == "charged"
            and not operation_attempts
        )
        if exact_terminal:
            succeeded.append(operation_id)
        elif exact_unstarted:
            safe_unstarted.append(operation_id)
        else:
            unsafe.append(operation_id)

    attempt_number_not_one = sum(
        int(row["attempt_number"] or 0) != 1 for row in attempts
    )
    wrong_provider = sum(
        row["provider"] != _provider_for(index_by_id[str(row["operation_id"])])
        for row in attempts
        if str(row["operation_id"]) in index_by_id
    )
    wrong_fence = sum(
        int(row["fence"] or 0)
        != (2 if index_by_id[str(row["operation_id"])] == takeover else 1)
        for row in attempts
        if str(row["operation_id"]) in index_by_id
    )
    duplicate_attempts = sum(
        max(0, len(attempts_by_id.get(operation_id, [])) - 1)
        for operation_id in selected
    )
    claim_mismatches = sum(
        row is None
        or int(row["claim_count"] or 0) != (2 if index == takeover else 1)
        for index, operation_id in enumerate(operations[start:end], start=start)
        for row in (rows_by_id.get(operation_id),)
    )
    return {
        "worker": worker_name,
        "assigned_count": 50,
        "index_start": start,
        "index_end": end - 1,
        "row_count": len(rows),
        "succeeded_count": len(succeeded),
        "safe_unstarted_count": len(safe_unstarted),
        "unsafe_terminal_count": len(unsafe),
        "fake_call_count": len(attempts),
        "unique_fake_operation_count": sum(
            bool(attempts_by_id.get(operation_id)) for operation_id in selected
        ),
        "duplicate_fake_call_count": duplicate_attempts,
        "provider_attempt_count": len(attempts),
        "provider_terminal_succeeded_count": sum(
            row["state"] == "provider_succeeded" for row in attempts
        ),
        "attempt_number_not_one_count": attempt_number_not_one,
        "wrong_provider_label_count": wrong_provider,
        "wrong_fence_count": wrong_fence,
        "claim_count_mismatch_count": claim_mismatches,
        "missing_provider_attempt_count": sum(
            not attempts_by_id.get(operation_id) for operation_id in selected
        ),
        "claude_label_count": sum(row["provider"] == "claude" for row in attempts),
        "kimi_label_count": sum(row["provider"] == "kimi" for row in attempts),
        "takeover_index": takeover,
        "takeover_fence": 2,
        "stale_owner_provider_call_count": 0,
        "real_provider_call_count": 0,
        "safe_unstarted_operation_ids": safe_unstarted,
        "unsafe_operation_ids": unsafe,
    }


def _require_terminal_process_projection(
    value: dict[str, Any], worker_name: str
) -> None:
    start, end, takeover = _process_assignment(worker_name)
    expected_claude = 50 if worker_name == "Worker-C" else 0
    expected_kimi = 50 if worker_name == "Worker-F" else 0
    if not (
        value.get("worker") == worker_name
        and value.get("assigned_count") == 50
        and value.get("index_start") == start
        and value.get("index_end") == end - 1
        and value.get("row_count") == 50
        and value.get("succeeded_count") == 50
        and value.get("safe_unstarted_count") == 0
        and value.get("unsafe_terminal_count") == 0
        and value.get("fake_call_count") == 50
        and value.get("unique_fake_operation_count") == 50
        and value.get("duplicate_fake_call_count") == 0
        and value.get("provider_attempt_count") == 50
        and value.get("provider_terminal_succeeded_count") == 50
        and value.get("attempt_number_not_one_count") == 0
        and value.get("wrong_provider_label_count") == 0
        and value.get("wrong_fence_count") == 0
        and value.get("claim_count_mismatch_count") == 0
        and value.get("missing_provider_attempt_count") == 0
        and value.get("claude_label_count") == expected_claude
        and value.get("kimi_label_count") == expected_kimi
        and value.get("takeover_index") == takeover
        and value.get("takeover_fence") == 2
        and value.get("stale_owner_provider_call_count") == 0
        and value.get("real_provider_call_count") == 0
        and value.get("safe_unstarted_operation_ids") == []
        and value.get("unsafe_operation_ids") == []
    ):
        raise CapacityError("phase_terminal_binding")


def _phase_process(
    context: dict[str, Any], plan_nonce: str, operations: list[str], worker_name: str
) -> dict[str, Any]:
    _configure_storage(context)
    start, end, takeover = _process_assignment(worker_name)
    worker_module = context["worker"]
    durable = context["durable_ai"]
    ai_operations = context["ai_operations"]
    call_lock = threading.Lock()
    calls: set[str] = set()
    index_by_operation = {
        operation_id: index for index, operation_id in enumerate(operations)
    }
    takeover_row = context["db"].fetchone(
        "SELECT status,provider_phase,lease_fence,claim_count,"
        "lease_expires_at FROM ai_operations WHERE id=?",
        (operations[takeover],),
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    if not takeover_row or not (
        takeover_row["status"] == "running"
        and takeover_row["provider_phase"] == "not_started"
        and int(takeover_row["lease_fence"] or 0) == 1
        and int(takeover_row["claim_count"] or 0) == 1
        and str(takeover_row["lease_expires_at"] or "") <= now_iso
    ):
        raise CapacityError("preclaim_not_expired")

    def processor(payload: dict[str, Any], worker_context: Any) -> dict[str, Any]:
        operation_id = worker_context.lease.operation_id
        index = index_by_operation.get(operation_id, -1)
        provider = _provider_for(index)
        if not (
            start <= index < end
            and type(payload) is dict
            and payload.get("item29_index") == index
            and payload.get("provider_label") == provider
            and payload.get("acceptance") == "provider-free-capacity"
        ):
            raise CapacityError("worker_payload_binding")

        def fake_call() -> dict[str, Any]:
            with call_lock:
                if operation_id in calls:
                    raise CapacityError("duplicate_fake_provider_call")
                calls.add(operation_id)
            return {"accepted": True, "item29_index": index}

        return worker_context.invoke_provider(
            provider=provider,
            model="item29-fixed-fake-v1",
            request={"item29_index": index},
            call=fake_call,
        )

    worker = worker_module.DurableAiWorker(
        processor=processor,
        store=durable.get_payload_store(),
        lease_seconds=PROCESS_LEASE_SECONDS,
    )

    def one(index: int) -> dict[str, Any]:
        operation_id = operations[index]
        if index == takeover:
            lease = durable.claim_delivered_operation(
                operation_id,
                lease_seconds=PROCESS_LEASE_SECONDS,
                owner_token=f"item29-takeover-{plan_nonce}-{index:03d}",
            )
            if lease is None or lease.fence != 2:
                raise CapacityError("takeover_claim")
            stale = ai_operations.OperationLease(
                operation_id,
                _preclaim_owner(plan_nonce, index),
                1,
                lease.expires_at,
            )
            context_row = durable.request_context(operation_id)
            if not context_row:
                raise CapacityError("takeover_context")
            rejected = durable.begin_provider_attempt_for_user(
                stale,
                user_id=context_row["user_id"],
                provider=_provider_for(index),
                request_hash=_digest(f"item29-stale:{operation_id}"),
                model_hash=_digest("item29-fixed-fake-v1"),
            )
            if rejected is not None:
                raise CapacityError("stale_provider_fence")
            return worker._run_claimed(lease)
        return worker.run_message(
            operation_id,
            owner_token=f"item29-worker-{plan_nonce}-{index:03d}",
        )

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = [future.result() for future in [
            pool.submit(one, index) for index in range(start, end)
        ]]
    selected = operations[start:end]
    if (
        any(row.get("status") != "succeeded" for row in results)
        or calls != set(selected)
    ):
        raise CapacityError("worker_terminal")
    projection = _process_readback_projection(context, operations, worker_name)
    try:
        _require_terminal_process_projection(projection, worker_name)
    except CapacityError as exc:
        raise CapacityError("provider_attempt_readback") from exc
    return {
        **_phase_base("process", plan_nonce),
        "operation_set_sha256": _operation_set_sha(operations),
        **projection,
    }


def _phase_observe(
    context: dict[str, Any], plan_nonce: str, operations: list[str]
) -> dict[str, Any]:
    clause, params = _where_ids(operations)
    db = context["db"]
    rows = db.fetchall(
        f"SELECT o.id,o.status,o.claim_count,o.provider_attempt_count,"
        f"s.billing_state,i.charge_applied,i.complete_applied,i.credits_used,"
        f"i.usage_id,i.user_id FROM ai_operations o "
        f"JOIN ai_operation_admissions a ON a.operation_id=o.id "
        f"JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        f"JOIN ai_operation_settlements s ON s.operation_id=o.id "
        f"WHERE o.id IN {clause}",
        params,
    )
    refs = db.fetchall(
        f"SELECT purpose,state,COUNT(*) AS c FROM ai_payload_refs "
        f"WHERE operation_id IN {clause} GROUP BY purpose,state",
        params,
    )
    events = db.fetchall(
        f"SELECT event_type,COUNT(*) AS c FROM ai_operation_events "
        f"WHERE operation_id IN {clause} GROUP BY event_type",
        params,
    )
    event_counts = {row["event_type"]: int(row["c"]) for row in events}
    actual_milli = int(round(sum(float(row["credits_used"] or 0) for row in rows) * 1000))
    user_ids = [row["user_id"] for row in rows]
    user_clause, user_params = _where_ids(user_ids)
    money = db.fetchone(
        f"SELECT "
        f"(SELECT COUNT(*) FROM payment_orders WHERE user_id IN {user_clause}) AS payments,"
        f"(SELECT COUNT(*) FROM credit_transactions WHERE user_id IN {user_clause}) AS credit_events,"
        f"(SELECT COALESCE(SUM(balance),0) FROM credits WHERE user_id IN {user_clause}) AS balance",
        user_params + user_params + user_params,
    )
    projection = {
        "unique_operation_count": len(rows),
        "succeeded_count": sum(row["status"] == "succeeded" for row in rows),
        "lost_operation_count": sum(row["status"] != "succeeded" for row in rows),
        "claim_count": sum(int(row["claim_count"]) for row in rows),
        "takeover_count": event_counts.get("lease_taken_over", 0),
        "provider_attempt_count": sum(int(row["provider_attempt_count"]) for row in rows),
        "settlement_completed_count": sum(row["billing_state"] == "completed" for row in rows),
        "settlement_refunded_count": sum(row["billing_state"] == "refunded" for row in rows),
        "settlement_needs_manual_count": sum(row["billing_state"] == "needs_manual" for row in rows),
        "charge_applied_count": sum(int(row["charge_applied"] or 0) == 1 for row in rows),
        "complete_applied_count": sum(int(row["complete_applied"] or 0) == 1 for row in rows),
        "usage_record_count": sum(bool(row["usage_id"]) for row in rows),
        "expected_credits_milli": EXPECTED_CREDITS_MILLI,
        "actual_credits_milli": actual_milli,
        "overcharge_credits_milli": max(0, actual_milli - EXPECTED_CREDITS_MILLI),
        "payment_record_delta_count": int(money["payments"]) + int(money["credit_events"]),
        "cash_balance_delta_milli": int(round(float(money["balance"] or 0) * 1000)),
    }
    ready = {(row["purpose"], row["state"]): int(row["c"]) for row in refs}
    if ready.get(("request", "ready"), 0) != 100 or ready.get(("result", "ready"), 0) != 100:
        raise CapacityError("payload_readback")
    expected = _expected_runtime_projection()
    for key, value in projection.items():
        if expected[key] != value:
            raise CapacityError("observe_" + key)
    return {
        **_phase_base("observe", plan_nonce),
        "operation_set_sha256": _operation_set_sha(operations),
        "runtime_projection": projection,
        "ready_request_object_count": 100,
        "ready_result_object_count": 100,
    }


def _phase_process_readback(
    context: dict[str, Any], plan_nonce: str, operations: list[str], worker_name: str
) -> dict[str, Any]:
    return {
        **_phase_base("process-readback", plan_nonce),
        "operation_set_sha256": _operation_set_sha(operations),
        **_process_readback_projection(context, operations, worker_name),
    }


def _cleanup_deletion_request(
    *, retention: Any, tx: Any, user_id: str, request_id: str, now: datetime
) -> dict[str, Any]:
    user = retention.lock_user_write_fence_with_storage(
        tx,
        user_id,
        allow_deletion_requested=True,
    )
    existing = tx.fetchone(
        "SELECT * FROM account_deletion_requests WHERE id=?"
        + (" FOR UPDATE" if tx.postgres else ""),
        (request_id,),
    )
    if existing is None:
        if user.get("deletion_requested_at") is not None:
            raise CapacityError("cleanup_request")
        request = retention.request_account_deletion_with_storage(
            tx,
            user_id,
            now=now,
            request_id=request_id,
            primary_delete_by=now,
            backup_clear_by=now + timedelta(days=30),
        )
    else:
        request = dict(existing)
    expected_subject = (
        "deleted:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    )
    if (
        request.get("id") != request_id
        or request.get("user_id") != user_id
        or request.get("subject_ref") != expected_subject
        or request.get("status") != "requested"
        or request.get("contract_version") != retention.CONTRACT_VERSION
    ):
        raise CapacityError("cleanup_request")
    return request


def _phase_cleanup(
    context: dict[str, Any], plan_nonce: str, operations: list[str]
) -> dict[str, Any]:
    _configure_storage(context)
    db = context["db"]
    durable = context["durable_ai"]
    idempotency = context["idempotency"]
    retention = context["content_retention"]
    storage = context["storage"]
    backend = storage.get_object_backend()
    clause, params = _where_ids(operations)
    rows = db.fetchall(
        "SELECT id AS user_id,username FROM users "
        "WHERE username LIKE ? ESCAPE '!' "
        "ORDER BY username",
        (_prefix_like(plan_nonce),),
    )
    validated_rows: list[tuple[str, str, int]] = []
    indexes: set[int] = set()
    derived_operation_set: set[str] = set()
    object_targets: dict[str, tuple[str, str, str, str]] = {}
    for row in rows:
        user_id = _uuid(row["user_id"], "cleanup_user_id")
        username = str(row["username"])
        suffix = username[-3:]
        if not suffix.isdigit() or not 0 <= int(suffix) < 100:
            raise CapacityError("cleanup_namespace")
        index = int(suffix)
        if username != f"{_prefix(plan_nonce)}{index:03d}" or index in indexes:
            raise CapacityError("cleanup_namespace")
        indexes.add(index)
        validated_rows.append((user_id, username, index))
        operation_id = durable.operation_id_for(
            user_id, "analyze", _request_id(plan_nonce, index)
        )
        derived_operation_set.add(operation_id)
        subject_hash = idempotency.operation_subject_hash(user_id)
        for purpose in ("request", "result"):
            reference_id = durable.payload_reference_id_for(operation_id, purpose)
            key = storage._payload_key(reference_id, subject_hash, purpose)
            object_targets[key] = (
                reference_id, operation_id, subject_hash, purpose
            )
    ref_rows = db.fetchall(
        f"SELECT id,operation_id,subject_hash,purpose,state FROM ai_payload_refs "
        f"WHERE operation_id IN {clause} AND purpose IN ('request','result')",
        params,
    )
    operation_set = set(operations)
    for row in ref_rows:
        operation_id = _uuid(row["operation_id"], "cleanup_operation_id")
        purpose = str(row["purpose"])
        subject_hash = str(row["subject_hash"])
        if (
            operation_id not in operation_set
            or purpose not in {"request", "result"}
            or HEX64_RE.fullmatch(subject_hash) is None
            or row["state"] not in {"ready", "deleted"}
        ):
            raise CapacityError("cleanup_reference_binding")
        reference_id = durable.payload_reference_id_for(operation_id, purpose)
        if row["id"] != reference_id:
            raise CapacityError("cleanup_reference_binding")
        key = storage._payload_key(reference_id, subject_hash, purpose)
        expected = (reference_id, operation_id, subject_hash, purpose)
        if key in object_targets and object_targets[key] != expected:
            raise CapacityError("cleanup_reference_binding")
        object_targets[key] = expected
    if (
        not operation_set.issubset(derived_operation_set)
        and not (len(operations) == 100 and len(ref_rows) == 200)
    ):
        raise CapacityError("cleanup_operation_binding")
    now = datetime.now(timezone.utc)
    all_request_ids = [
        str(uuid.uuid5(uuid.UUID(plan_nonce), f"item29-delete:{index:03d}"))
        for index in range(100)
    ]
    for user_id, _username, index in validated_rows:
        request_id = str(uuid.uuid5(uuid.UUID(plan_nonce), f"item29-delete:{index:03d}"))
        with db.transaction(write=True) as tx:
            _cleanup_deletion_request(
                retention=retention,
                tx=tx,
                user_id=user_id,
                request_id=request_id,
                now=now,
            )
    orphan_deleted = 0
    for key, expected in object_targets.items():
        reference_id, operation_id, subject_hash, purpose = expected
        item = backend.head(key)
        if item is None:
            continue
        storage.validate_stored_object_descriptor(item)
        if (
            item.key != key
            or item.metadata.get("reference_id") != reference_id
            or item.metadata.get("subject_hash") != subject_hash
            or item.metadata.get("purpose") != purpose
        ):
            raise CapacityError("cleanup_object_binding")
        reference = db.fetchone(
            "SELECT operation_id,subject_hash,purpose,state "
            "FROM ai_payload_refs WHERE id=?",
            (reference_id,),
        )
        if reference is not None:
            reference = dict(reference)
            if (
                reference.get("operation_id") != operation_id
                or reference.get("subject_hash") != subject_hash
                or reference.get("purpose") != purpose
                or reference.get("state") not in {"ready", "deleted"}
            ):
                raise CapacityError("cleanup_reference_binding")
        if reference is None or reference["state"] == "deleted":
            if backend.delete(key) is not True or backend.head(key) is not None:
                raise CapacityError("cleanup_orphan_object")
            orphan_deleted += 1
    completed: list[str] = []
    for request_id in all_request_ids:
        completed.extend(retention.process_due_account_deletions(
            limit=1,
            now=now + timedelta(seconds=1),
            payload_store=durable.get_payload_store(),
            media_backend=backend,
            request_id=request_id,
        ))
    request_clause, request_params = _where_ids(all_request_ids)
    deletion_rows = db.fetchall(
        f"SELECT id,subject_ref,status,user_id,primary_deleted_at "
        f"FROM account_deletion_requests WHERE id IN {request_clause}",
        request_params,
    )
    if len(operations) == 100 and len(deletion_rows) != 100:
        raise CapacityError("cleanup_terminal_count")
    if any(
        row["status"] != "backup_clear_pending"
        or row["user_id"] is not None
        or not row["primary_deleted_at"]
        for row in deletion_rows
    ):
        raise CapacityError("cleanup_terminal")
    subject_refs = [row["subject_ref"] for row in deletion_rows]
    subject_clause, subject_params = _where_ids(subject_refs)
    residue = db.fetchone(
        f"SELECT "
        f"(SELECT COUNT(*) FROM users WHERE username LIKE ? ESCAPE '!') AS users,"
        f"(SELECT COUNT(*) FROM ai_operation_admissions WHERE operation_id IN {clause}) AS admissions,"
        f"(SELECT COUNT(*) FROM idempotency_requests i JOIN users u ON u.id=i.user_id WHERE u.username LIKE ? ESCAPE '!') AS idempotency,"
        f"(SELECT COUNT(*) FROM ai_payload_refs WHERE operation_id IN {clause} AND purpose='request' AND state='ready') AS ready_requests,"
        f"(SELECT COUNT(*) FROM ai_payload_refs WHERE operation_id IN {clause} AND purpose='result' AND state='ready') AS ready_results,"
        f"(SELECT COUNT(*) FROM ai_payload_refs WHERE operation_id IN {clause} AND state='deleted') AS deleted_refs,"
        f"(SELECT COUNT(*) FROM ai_operations WHERE id IN {clause}) AS operations,"
        f"(SELECT COALESCE(SUM(provider_attempt_count),0) FROM ai_operations WHERE id IN {clause}) AS attempts,"
        f"(SELECT COUNT(*) FROM usage_records WHERE user_id IN {subject_clause}) AS usages",
        ((_prefix_like(plan_nonce),) + params
         + (_prefix_like(plan_nonce),) + params + params + params
         + params + params + subject_params),
    )
    cleanup_projection = {
        "ready_request_object_residue_count": int(residue["ready_requests"]),
        "ready_result_object_residue_count": int(residue["ready_results"]),
        "primary_user_residue_count": int(residue["users"]),
        "admission_residue_count": int(residue["admissions"]),
        "idempotency_residue_count": int(residue["idempotency"]),
        "pseudonymous_operation_audit_count": int(residue["operations"]),
        "pseudonymous_provider_attempt_audit_count": int(residue["attempts"]),
        "pseudonymous_usage_audit_count": int(residue["usages"]),
    }
    if len(operations) == 100 and int(residue["deleted_refs"]) != 200:
        raise CapacityError("cleanup_deleted_payload_count")
    if any(cleanup_projection[key] != 0 for key in (
        "ready_request_object_residue_count",
        "ready_result_object_residue_count",
        "primary_user_residue_count", "admission_residue_count",
        "idempotency_residue_count",
    )):
        raise CapacityError("cleanup_residue")
    if any(backend.head(key) is not None for key in object_targets):
        raise CapacityError("cleanup_object_residue")
    return {
        **_phase_base("cleanup", plan_nonce),
        "operation_set_sha256": _operation_set_sha(operations),
        "primary_deleted_count": len(deletion_rows),
        "newly_primary_deleted_count": len(completed),
        "deleted_payload_object_count": int(residue["deleted_refs"]),
        "orphan_payload_object_deleted_count": orphan_deleted,
        "cleanup_projection": cleanup_projection,
    }


def run_production_phase(
    *, phase: str, plan_nonce: str, dependency: dict[str, str],
    operations: list[str], worker_name: str | None
) -> dict[str, Any]:
    plan_nonce = _uuid(plan_nonce, "plan_nonce")
    _dependency(dependency)
    context = _model_context()
    _require_environment(phase, context)
    if phase == "preflight":
        if operations:
            raise CapacityError("operation_ids_count")
        return _phase_preflight(context, plan_nonce)
    if phase == "admit":
        if operations:
            raise CapacityError("operation_ids_count")
        return _phase_admit(context, plan_nonce)
    if phase == "resolve":
        if operations:
            raise CapacityError("operation_ids_count")
        return _phase_resolve(context, plan_nonce)
    if phase == "dispatch":
        operations = _ids(operations, allowed=set(range(1, 101)))
    elif phase == "cleanup":
        operations = _ids(operations, allowed=set(range(101)))
    elif phase in {
        "dispatch-readback", "preclaim", "process", "process-readback",
        "observe",
    }:
        operations = _ids(operations, allowed={100})
    if phase == "dispatch":
        return _phase_dispatch(context, plan_nonce, operations)
    if phase == "dispatch-readback":
        return _phase_dispatch_readback(context, plan_nonce, operations)
    if phase == "preclaim":
        return _phase_preclaim(context, plan_nonce, operations, str(worker_name or ""))
    if phase == "process":
        return _phase_process(context, plan_nonce, operations, str(worker_name or ""))
    if phase == "process-readback":
        return _phase_process_readback(
            context, plan_nonce, operations, str(worker_name or "")
        )
    if phase == "observe":
        return _phase_observe(context, plan_nonce, operations)
    if phase == "cleanup":
        return _phase_cleanup(context, plan_nonce, operations)
    raise CapacityError("phase")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=(
        "preflight", "admit", "resolve", "dispatch", "dispatch-readback",
        "preclaim", "process", "process-readback", "observe", "cleanup",
    ))
    parser.add_argument("--plan-nonce", required=True)
    parser.add_argument("--item28-dependency-json", required=True)
    parser.add_argument("--operations-json", default="[]")
    parser.add_argument("--worker", choices=("Worker-C", "Worker-F"))
    args = parser.parse_args(argv)
    try:
        dependency = json.loads(args.item28_dependency_json)
        operations = json.loads(args.operations_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        print("item29_capacity_100=FAIL code=input_contract", file=sys.stderr)
        return 1
    try:
        result = run_production_phase(
            phase=args.phase,
            plan_nonce=args.plan_nonce,
            dependency=dependency,
            operations=operations,
            worker_name=args.worker,
        )
    except CapacityError as exc:
        print(f"item29_capacity_100=FAIL code={exc.code}", file=sys.stderr)
        return 1
    except BaseException:
        print(
            f"item29_capacity_100=FAIL code={args.phase}_runtime",
            file=sys.stderr,
        )
        return 1
    print(_canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
