#!/usr/bin/env python3
"""Item 29 provider-free 100-job capacity acceptance orchestrator.

This module contains no database discovery, global queue recovery, real model
provider, payment, or cloud control-plane client.  A separately bound runtime
adapter must expose only exact-operation primitives.  The source checkpoint is
therefore inert until the Item 28 terminal dependency and an exact production
adapter are frozen by the request renderer.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import re
import threading
from typing import Any, Callable, Protocol
import uuid


TASK_ID = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
RESULT_SCHEMA = "noteai.item29.capacity-100-result.v1"
DEPENDENCY_SCHEMA = "noteai.item29.item28-dependency.v1"
OPERATION_COUNT = 100
LEASE_SECONDS = 15
EXPECTED_CREDITS_MILLI = 600_000
MIN_DATABASE_IDLE_CONNECTION_HEADROOM = 120
MIN_API_C_MEMORY_HEADROOM_BYTES = 1_073_741_824
MIN_API_C_PID_HEADROOM = 160
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


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
    """Exact-operation-only runtime surface required by the orchestrator."""

    def preflight(self) -> dict[str, Any]: ...

    def admit_exact(self, index: int, request_id: str, provider: str) -> dict[str, Any]: ...

    def deliver_exact(self, operation_id: str) -> bool: ...

    def claim_exact(
        self,
        operation_id: str,
        *,
        owner: str,
        lease_seconds: int,
        now: datetime,
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


def _strict_int(value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CapacityError("integer_contract")
    return value


def _provider_for(index: int) -> str:
    return "claude" if index < 50 else "kimi"


def _worker_for(index: int) -> str:
    return "Worker-C" if index < 50 else "Worker-F"


def _request_id(plan_nonce: str, index: int) -> str:
    return str(uuid.uuid5(uuid.UUID(plan_nonce), f"item29-admission:{index:03d}"))


class FixedFakeProvider:
    """Content-free provider used only after a durable provider-start fence."""

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

    def projection(self) -> dict[str, Any]:
        with self._lock:
            rows = list(self._calls)
        operation_ids = [row[0] for row in rows]
        return {
            "fake_call_count": len(rows),
            "unique_fake_operation_count": len(set(operation_ids)),
            "duplicate_fake_call_count": len(rows) - len(set(operation_ids)),
            "real_provider_call_count": 0,
            "claude_label_count": sum(row[1] == "claude" for row in rows),
            "kimi_label_count": sum(row[1] == "kimi" for row in rows),
            "ai_model_call_count": 0,
            "input_token_count": 0,
            "output_token_count": 0,
            "provider_cost_milli": 0,
        }


def _require_preflight(value: Any) -> dict[str, int]:
    if type(value) is not dict or set(value) != {
        "database_idle_connection_headroom",
        "api_c_memory_headroom_bytes",
        "api_c_pid_headroom",
    }:
        raise CapacityError("headroom_schema")
    db_idle = _strict_int(value["database_idle_connection_headroom"])
    memory = _strict_int(value["api_c_memory_headroom_bytes"])
    pids = _strict_int(value["api_c_pid_headroom"])
    if (
        db_idle < MIN_DATABASE_IDLE_CONNECTION_HEADROOM
        or memory < MIN_API_C_MEMORY_HEADROOM_BYTES
        or pids < MIN_API_C_PID_HEADROOM
    ):
        raise CapacityError("headroom_insufficient")
    return {
        "database_idle_connection_headroom": db_idle,
        "database_idle_connection_headroom_required": (
            MIN_DATABASE_IDLE_CONNECTION_HEADROOM
        ),
        "api_c_memory_headroom_bytes": memory,
        "api_c_memory_headroom_bytes_required": MIN_API_C_MEMORY_HEADROOM_BYTES,
        "api_c_pid_headroom": pids,
        "api_c_pid_headroom_required": MIN_API_C_PID_HEADROOM,
        "headroom_gate_passed": True,
    }


def _admit_concurrently(
    runtime: CapacityRuntime,
    *,
    plan_nonce: str,
) -> list[str]:
    ready = threading.Barrier(OPERATION_COUNT + 1, timeout=30)
    release = threading.Barrier(OPERATION_COUNT + 1, timeout=30)

    def admit(index: int) -> tuple[int, str]:
        ready.wait()
        release.wait()
        row = runtime.admit_exact(
            index,
            _request_id(plan_nonce, index),
            _provider_for(index),
        )
        if type(row) is not dict or set(row) != {"operation_id", "state"}:
            raise CapacityError("admission_schema")
        if row["state"] != "admitted":
            raise CapacityError("admission_state")
        return index, _uuid(row["operation_id"], "admission_operation_id")

    with ThreadPoolExecutor(max_workers=OPERATION_COUNT) as pool:
        futures = [pool.submit(admit, index) for index in range(OPERATION_COUNT)]
        ready.wait()
        release.wait()
        indexed = [future.result() for future in futures]
    indexed.sort()
    operation_ids = [value for _index, value in indexed]
    if len(operation_ids) != OPERATION_COUNT or len(set(operation_ids)) != OPERATION_COUNT:
        raise CapacityError("operation_identity_count")
    return operation_ids


def _claim_and_process(
    runtime: CapacityRuntime,
    operation_ids: list[str],
    *,
    fake: FixedFakeProvider,
) -> None:
    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    t1 = t0 + timedelta(seconds=LEASE_SECONDS)

    # Two deliberate pre-provider interruptions.  Neither stale owner is ever
    # allowed to start a provider attempt.
    stale_50 = runtime.claim_exact(
        operation_ids[50], owner="Worker-C-preinterrupt-index-050",
        lease_seconds=LEASE_SECONDS, now=t0,
    )
    stale_0 = runtime.claim_exact(
        operation_ids[0], owner="Worker-F-preinterrupt-index-000",
        lease_seconds=LEASE_SECONDS, now=t0,
    )
    if stale_50 is None or stale_0 is None:
        raise CapacityError("preinterrupt_claim")

    replacements = {
        0: runtime.claim_exact(
            operation_ids[0], owner="Worker-C-item29-000",
            lease_seconds=LEASE_SECONDS, now=t1,
        ),
        50: runtime.claim_exact(
            operation_ids[50], owner="Worker-F-item29-050",
            lease_seconds=LEASE_SECONDS, now=t1,
        ),
    }
    if any(lease is None or lease.fence != 2 for lease in replacements.values()):
        raise CapacityError("takeover_claim")
    for stale, index in ((stale_0, 0), (stale_50, 50)):
        rejected = runtime.begin_provider_exact(
            stale,
            provider=_provider_for(index),
            request_hash=_digest(f"item29-stale-request:{stale.operation_id}"),
            model_hash=_digest(f"item29-fake-model:{_provider_for(index)}"),
            now=t1 + timedelta(milliseconds=1),
        )
        if rejected is not None:
            raise CapacityError("stale_provider_fence")

    def process(index: int) -> None:
        operation_id = operation_ids[index]
        owner = _worker_for(index)
        lease = replacements.get(index)
        if lease is None:
            lease = runtime.claim_exact(
                operation_id,
                owner=f"{owner}-item29-{index:03d}",
                lease_seconds=LEASE_SECONDS,
                now=t1,
            )
        if lease is None or lease.operation_id != operation_id:
            raise CapacityError("exact_claim")
        expected_fence = 2 if index in {0, 50} else 1
        if lease.fence != expected_fence:
            raise CapacityError("claim_fence")
        provider = _provider_for(index)
        started = runtime.begin_provider_exact(
            lease,
            provider=provider,
            request_hash=_digest(f"item29-request:{operation_id}"),
            model_hash=_digest(f"item29-fake-model:{provider}"),
            now=t1 + timedelta(seconds=1),
        )
        if type(started) is not dict or set(started) != {
            "attempt_id", "attempt_number",
        }:
            raise CapacityError("provider_attempt_schema")
        attempt_id = _uuid(started["attempt_id"], "provider_attempt_id")
        if started["attempt_number"] != 1:
            raise CapacityError("provider_attempt_number")
        response_hash = fake.call(operation_id, provider, attempt_id)
        if not runtime.complete_success_exact(
            lease,
            attempt_id,
            response_hash=response_hash,
            now=t1 + timedelta(seconds=2),
        ):
            raise CapacityError("settlement")

    # Range ownership is fixed: Worker-C handles 0..49 and Worker-F 50..99.
    with ThreadPoolExecutor(max_workers=OPERATION_COUNT) as pool:
        futures = [pool.submit(process, index) for index in range(OPERATION_COUNT)]
        for future in futures:
            future.result()

    # Stale pre-interruption leases remain observable only as fenced history.
    if stale_0.fence != 1 or stale_50.fence != 1:
        raise CapacityError("stale_fence")


def _require_runtime_projection(value: Any) -> dict[str, Any]:
    expected = {
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
    if type(value) is not dict or set(value) != set(expected):
        raise CapacityError("runtime_projection_schema")
    for key, expected_value in expected.items():
        if type(value[key]) is not type(expected_value) or value[key] != expected_value:
            raise CapacityError("runtime_projection_" + key)
    return dict(value)


def run_rehearsal(
    runtime: CapacityRuntime,
    *,
    plan_nonce: str,
    item28_dependency: dict[str, str],
) -> dict[str, Any]:
    plan_nonce = _uuid(plan_nonce, "plan_nonce")
    if type(item28_dependency) is not dict or set(item28_dependency) != {
        "schema", "authority_root", "verifier_path", "verifier_sha256",
        "evidence_path", "evidence_sha256", "receipt_path", "receipt_sha256",
        "checkpoint_path", "checkpoint_sha256", "terminal_acceptance_sha256",
    }:
        raise CapacityError("item28_dependency_schema")
    if item28_dependency["schema"] != DEPENDENCY_SCHEMA:
        raise CapacityError("item28_dependency_version")
    for key in (
        "authority_root", "verifier_sha256", "evidence_sha256",
        "receipt_sha256", "checkpoint_sha256", "terminal_acceptance_sha256",
    ):
        if HEX64_RE.fullmatch(item28_dependency[key]) is None:
            raise CapacityError("item28_dependency_authority")
    if not item28_dependency["verifier_path"].startswith("tools/"):
        raise CapacityError("item28_dependency_path")
    for key in ("evidence_path", "receipt_path", "checkpoint_path"):
        if not item28_dependency[key].startswith("deploy/production/evidence/"):
            raise CapacityError("item28_dependency_path")

    headroom = _require_preflight(runtime.preflight())
    operation_ids = _admit_concurrently(runtime, plan_nonce=plan_nonce)
    for operation_id in operation_ids:
        if not runtime.deliver_exact(operation_id):
            raise CapacityError("outbox_delivery")
    fake = FixedFakeProvider()
    _claim_and_process(runtime, operation_ids, fake=fake)
    for operation_id in operation_ids:
        cleanup = runtime.cleanup_exact(operation_id)
        if cleanup != {
            "status": "primary_deleted",
            "request_object_residue_count": 0,
            "result_object_residue_count": 0,
        }:
            raise CapacityError("cleanup")
    runtime_projection = _require_runtime_projection(
        runtime.project_exact(operation_ids)
    )
    provider_projection = fake.projection()
    if provider_projection != {
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
    }:
        raise CapacityError("fake_provider_projection")
    operation_set_sha256 = _digest("\n".join(sorted(operation_ids)) + "\n")
    return {
        "schema": RESULT_SCHEMA,
        "task_id": TASK_ID,
        "status": "PASS",
        "item28_dependency": item28_dependency,
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
        "provider": provider_projection,
        "runtime_projection": runtime_projection,
        "execution_boundary": {
            "provider_client_token_readback_supported": False,
            "provider_history_key": "Name",
            "automatic_retry_count": 0,
            "real_provider_credentials_loaded": False,
            "cloud_control_plane_call_count": 0,
            "public_request_count": 0,
        },
    }


def _load_factory(spec: str) -> Callable[[], CapacityRuntime]:
    if type(spec) is not str or spec.count(":") != 1:
        raise CapacityError("runtime_factory")
    module_name, attribute = spec.split(":", 1)
    if not module_name or not attribute:
        raise CapacityError("runtime_factory")
    try:
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise CapacityError("runtime_factory") from exc
    if not callable(factory):
        raise CapacityError("runtime_factory")
    return factory


def create_runtime() -> CapacityRuntime:
    """Fail-closed source-checkpoint placeholder for the production adapter.

    Item 28 dependency authorities and the host-bound multi-runtime adapter
    must be frozen together.  The FakeRuntime used by tests is never selected
    by the production CLI.
    """
    raise CapacityError("production_runtime_not_bound")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-factory", required=True)
    parser.add_argument("--plan-nonce", required=True)
    parser.add_argument("--item28-dependency-json", required=True)
    args = parser.parse_args(argv)
    try:
        dependency = json.loads(args.item28_dependency_json)
        runtime = _load_factory(args.runtime_factory)()
        result = run_rehearsal(
            runtime,
            plan_nonce=args.plan_nonce,
            item28_dependency=dependency,
        )
    except (CapacityError, json.JSONDecodeError) as exc:
        code = exc.code if isinstance(exc, CapacityError) else "dependency_json"
        print(f"item29_capacity_100=FAIL code={code}", file=__import__("sys").stderr)
        return 1
    except BaseException:
        print("item29_capacity_100=FAIL code=unexpected", file=__import__("sys").stderr)
        return 1
    print(_canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
