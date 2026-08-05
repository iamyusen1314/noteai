"""Provider-neutral durable AI dispatcher and fenced worker runtime.

The module contains no concrete provider adapter. Production execution stays
suspended until an explicit processor and private PayloadStore are wired.
Unit/integration tests inject bounded processors; health checks are read-only
and provider-free.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import ai_operations
import billing
import db
import durable_ai
import private_storage


class KnownProviderFailure(RuntimeError):
    """A provider definitively rejected/failed without an ambiguous outcome."""


class ProviderOutcomeUnknown(RuntimeError):
    """The provider side effect may have occurred and must not be retried."""


Processor = Callable[[dict[str, Any], "WorkerContext"], Any]
Publisher = Callable[[str], None]
INTERNAL_ACCEPTANCE_LEASE_SECONDS = 15
INTERNAL_ACCEPTANCE_HOLD_SECONDS = 300
_DISPATCHER_FORBIDDEN_STORAGE_ENV = (
    "NOTEAI_PRIVATE_STORAGE_BACKEND",
    "NOTEAI_OSS_PRIVATE_BUCKET",
    "NOTEAI_OSS_REGION",
    "NOTEAI_OSS_ENDPOINT",
    "NOTEAI_OSS_RAM_ROLE",
    "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH",
    "NOTEAI_OSS_KEY_PREFIX",
)


def collection_suspended() -> bool:
    return str(os.environ.get("NOTEAI_DURABLE_AI_SUSPENDED", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _dispatcher_storage_env_present() -> bool:
    return any(name in os.environ for name in _DISPATCHER_FORBIDDEN_STORAGE_ENV)


def _acceptance_operation_id() -> str | None:
    raw = os.environ.get("NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID", "")
    try:
        canonical = str(uuid.UUID(raw))
    except (AttributeError, ValueError):
        return None
    return canonical if raw == canonical else None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


@dataclass
class WorkerContext:
    lease: ai_operations.OperationLease
    user_id: str
    operation_kind: str
    queue: Any
    provider_calls: int = 0
    outcome_unknown: bool = False

    def invoke_provider(
        self,
        *,
        provider: str,
        model: str,
        request: Any,
        call: Callable[[], Any],
        now: datetime | None = None,
    ) -> Any:
        """Fence exactly one externally visible call before invocation."""
        request_body = _canonical_bytes(request)
        attempt = durable_ai.begin_provider_attempt_for_user(
            self.lease,
            user_id=self.user_id,
            provider=provider,
            request_hash=hashlib.sha256(request_body).hexdigest(),
            model_hash=hashlib.sha256(str(model or "").encode("utf-8")).hexdigest(),
            input_count=1,
            now=now,
        )
        if not attempt:
            raise RuntimeError("provider admission fence was rejected")
        self.provider_calls += 1
        try:
            response = call()
        except KnownProviderFailure:
            if not self.queue.record_provider_terminal(
                self.lease,
                attempt,
                state=ai_operations.AttemptState.FAILED,
                now=now,
            ):
                raise RuntimeError("provider failure fence was lost")
            raise
        except BaseException as exc:
            self.outcome_unknown = durable_ai.settle_outcome_unknown(
                self.lease,
                failure_code="provider_outcome_unknown",
                now=now,
            )
            raise ProviderOutcomeUnknown(
                "provider outcome is unknown; automatic retry is prohibited"
            ) from exc
        response_body = _canonical_bytes(response)
        if not self.queue.record_provider_terminal(
            self.lease,
            attempt,
            state=ai_operations.AttemptState.SUCCEEDED,
            response_hash=hashlib.sha256(response_body).hexdigest(),
            output_count=1,
            now=now,
        ):
            raise RuntimeError("provider success fence was lost")
        return response


class OutboxDispatcher:
    """Publish only an operation UUID, then atomically acknowledge the row."""

    def __init__(self, publisher: Publisher):
        self.publisher = publisher

    def run_once(
        self,
        *,
        owner_token: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if collection_suspended():
            return {
                "status": "suspended",
                "provider_called": False,
                "database_write": False,
            }
        lease = durable_ai.claim_outbox(owner_token=owner_token, now=now)
        if not lease:
            return {"status": "idle", "provider_called": False}
        self.publisher(lease.operation_id)
        if not durable_ai.mark_outbox_delivered(lease, now=now):
            return {
                "status": "fence_lost",
                "operation_id": lease.operation_id,
                "provider_called": False,
            }
        return {
            "status": "delivered",
            "operation_id": lease.operation_id,
            "provider_called": False,
        }


class PostgresOutboxDispatcher:
    """Use PostgreSQL commit as both publisher acknowledgement and wake-up."""

    def run_once(
        self,
        *,
        owner_token: str | None = None,
        operation_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if collection_suspended():
            return {
                "status": "suspended",
                "provider_called": False,
                "database_write": False,
            }
        if not db.using_postgres():
            return {
                "status": "blocked",
                "reason": "postgres_required",
                "provider_called": False,
                "database_write": False,
            }
        if _dispatcher_storage_env_present():
            return {
                "status": "blocked",
                "reason": "dispatcher_storage_boundary",
                "provider_called": False,
                "database_write": False,
            }
        if not durable_ai.database_role_matches("noteai_ai_dispatcher"):
            return {
                "status": "blocked",
                "reason": "database_role_mismatch",
                "provider_called": False,
                "database_write": False,
            }
        lease = durable_ai.claim_outbox(
            owner_token=owner_token,
            operation_id=operation_id,
            now=now,
        )
        if not lease:
            return {"status": "idle", "provider_called": False}
        if not durable_ai.mark_outbox_delivered_and_notify(lease, now=now):
            return {
                "status": "fence_lost",
                "operation_id": lease.operation_id,
                "provider_called": False,
            }
        return {
            "status": "delivered",
            "operation_id": lease.operation_id,
            "provider_called": False,
        }


class DurableAiWorker:
    def __init__(
        self,
        *,
        processor: Processor,
        store: durable_ai.PayloadStore | None = None,
        lease_seconds: int = 900,
        enforce_runtime_role: bool = True,
    ):
        if not callable(processor):
            raise TypeError("processor must be callable")
        self.processor = processor
        self.store = store or durable_ai.get_payload_store()
        self.lease_seconds = int(lease_seconds)
        self.enforce_runtime_role = bool(enforce_runtime_role)
        self.queue = __import__("task_queue").DatabaseTaskQueue()

    def run_message(
        self,
        operation_id: str,
        *,
        owner_token: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if collection_suspended():
            return {
                "status": "suspended",
                "provider_called": False,
                "database_write": False,
            }
        if self.enforce_runtime_role and os.environ.get("NOTEAI_RUNTIME_ROLE") != "ai-worker":
            return {
                "status": "blocked",
                "reason": "runtime_role_not_allowed",
                "provider_called": False,
                "database_write": False,
            }
        if (
            os.environ.get("NOTEAI_DURABLE_AI_COMPONENT") == "worker"
            and not durable_ai.database_role_matches("noteai_ai_worker")
        ):
            return {
                "status": "blocked",
                "reason": "database_role_mismatch",
                "provider_called": False,
                "database_write": False,
            }
        lease = durable_ai.claim_delivered_operation(
            operation_id,
            lease_seconds=self.lease_seconds,
            owner_token=owner_token,
            now=now,
        )
        if not lease:
            return {
                "status": "not_claimed",
                "operation_id": operation_id,
                "provider_called": False,
            }
        return self._run_claimed(lease, now=now)

    def run_once(
        self,
        *,
        owner_token: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if collection_suspended():
            return {
                "status": "suspended",
                "provider_called": False,
                "database_write": False,
            }
        if self.enforce_runtime_role and os.environ.get("NOTEAI_RUNTIME_ROLE") != "ai-worker":
            return {
                "status": "blocked",
                "reason": "runtime_role_not_allowed",
                "provider_called": False,
                "database_write": False,
            }
        if (
            os.environ.get("NOTEAI_DURABLE_AI_COMPONENT") == "worker"
            and not durable_ai.database_role_matches("noteai_ai_worker")
        ):
            return {
                "status": "blocked",
                "reason": "database_role_mismatch",
                "provider_called": False,
                "database_write": False,
            }
        lease = durable_ai.claim_next_delivered_operation(
            lease_seconds=self.lease_seconds,
            owner_token=owner_token,
            now=now,
        )
        if not lease:
            return {"status": "idle", "provider_called": False}
        return self._run_claimed(lease, now=now)

    def _run_claimed(
        self,
        lease: ai_operations.OperationLease,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        operation_id = lease.operation_id
        context_data = durable_ai.request_context(operation_id)
        if not context_data:
            settled = durable_ai.settle_failure(
                lease,
                failure_code="worker_failed",
                now=now,
            )
            return {
                "status": "refunded" if settled else "fence_lost",
                "reason": "durable_contract_unavailable",
                "provider_called": False,
            }
        worker_context = WorkerContext(
            lease=lease,
            user_id=context_data["user_id"],
            operation_kind=context_data["operation_kind"],
            queue=self.queue,
        )
        billing.activate_usage(context_data.get("usage_id"))
        try:
            try:
                _loaded_context, payload = durable_ai.load_request(
                    operation_id,
                    store=self.store,
                )
            except durable_ai.PayloadUnavailable as exc:
                permanent = exc.code in {
                    "DURABLE_AI_PAYLOAD_NOT_FOUND",
                    "DURABLE_AI_PAYLOAD_EXPIRED",
                    "DURABLE_AI_PAYLOAD_HASH_MISMATCH",
                    "DURABLE_AI_PAYLOAD_INVALID",
                }
                if permanent:
                    durable_ai.settle_failure(
                        lease,
                        failure_code="payload_unavailable",
                        now=now,
                    )
                    return {
                        "status": "refunded",
                        "reason": "payload_unavailable",
                        "provider_called": False,
                    }
                return {
                    "status": "retryable_storage_unavailable",
                    "provider_called": False,
                }
            try:
                result = self.processor(payload, worker_context)
            except ProviderOutcomeUnknown:
                return {
                    "status": "needs_manual",
                    "reason": "provider_outcome_unknown",
                    "provider_called": True,
                }
            except KnownProviderFailure:
                settled = durable_ai.settle_failure(
                    lease,
                    failure_code="provider_failed",
                    now=now,
                )
                return {
                    "status": "refunded" if settled else "fence_lost",
                    "reason": "provider_failed",
                    "provider_called": True,
                }
            except BaseException:
                if worker_context.provider_calls:
                    settled = durable_ai.settle_outcome_unknown(
                        lease,
                        failure_code="result_store_unknown",
                        now=now,
                    )
                    return {
                        "status": "needs_manual" if settled else "fence_lost",
                        "reason": "result_store_unknown",
                        "provider_called": True,
                    }
                settled = durable_ai.settle_failure(
                    lease,
                    failure_code="worker_failed",
                    now=now,
                )
                return {
                    "status": "refunded" if settled else "fence_lost",
                    "reason": "worker_failed",
                    "provider_called": False,
                }
            if worker_context.provider_calls < 1:
                settled = durable_ai.settle_failure(
                    lease,
                    failure_code="worker_failed",
                    now=now,
                )
                return {
                    "status": "refunded" if settled else "fence_lost",
                    "reason": "provider_call_missing",
                    "provider_called": False,
                }
            try:
                settled = durable_ai.settle_success(
                    lease,
                    result_payload=result,
                    result_count=1,
                    now=now,
                    store=self.store,
                )
            except BaseException:
                settled_unknown = durable_ai.settle_outcome_unknown(
                    lease,
                    failure_code="result_store_unknown",
                    now=now,
                )
                return {
                    "status": "needs_manual" if settled_unknown else "fence_lost",
                    "reason": "result_store_unknown",
                    "provider_called": True,
                }
            return {
                "status": "succeeded" if settled else "fence_lost",
                "operation_id": operation_id,
                "provider_called": True,
            }
        finally:
            billing.clear_active_usage()


class PostgresWakeListener:
    """LISTEN before polling; payloads are ignored and never authorize work."""

    def __init__(self):
        self._connection = None

    def open(self) -> "PostgresWakeListener":
        if not db.using_postgres():
            raise RuntimeError("postgres wake listener requires PostgreSQL")
        import psycopg

        connection = psycopg.connect(
            os.environ["DATABASE_URL"],
            autocommit=True,
            options="-c timezone=UTC",
        )
        try:
            connection.execute(
                f"LISTEN {durable_ai.DURABLE_AI_NOTIFY_CHANNEL}"
            )
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        return self

    def wait(self, timeout_seconds: float = 5.0) -> bool:
        if self._connection is None:
            raise RuntimeError("postgres wake listener is not open")
        timeout = min(60.0, max(0.1, float(timeout_seconds)))
        for _notification in self._connection.notifies(
            timeout=timeout,
            stop_after=1,
        ):
            return True
        return False

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def run_dispatcher_loop(
    *,
    poll_seconds: float = 1.0,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    dispatcher = PostgresOutboxDispatcher()
    iterations = 0
    last = {"status": "idle", "provider_called": False}
    while max_iterations is None or iterations < max_iterations:
        last = dispatcher.run_once()
        iterations += 1
        if last.get("status") in {"blocked", "fence_lost"}:
            raise RuntimeError("durable dispatcher loop stopped")
        if (
            last.get("status") in {"idle", "suspended"}
            and (max_iterations is None or iterations < max_iterations)
        ):
            time.sleep(min(60.0, max(0.1, float(poll_seconds))))
    return {**last, "iterations": iterations}


def run_worker_loop(
    worker: DurableAiWorker,
    *,
    listener: PostgresWakeListener | None = None,
    poll_seconds: float = 5.0,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    wake_listener = (listener or PostgresWakeListener()).open()
    iterations = 0
    last = {"status": "idle", "provider_called": False}
    try:
        while max_iterations is None or iterations < max_iterations:
            last = worker.run_once()
            iterations += 1
            if last.get("status") in {"blocked", "fence_lost"}:
                raise RuntimeError("durable worker loop stopped")
            if (
                last.get("status")
                in {"idle", "suspended", "retryable_storage_unavailable"}
                and (max_iterations is None or iterations < max_iterations)
            ):
                wake_listener.wait(poll_seconds)
    finally:
        wake_listener.close()
    return {**last, "iterations": iterations}


def _internal_acceptance_processor(
    payload: dict[str, Any],
    context: WorkerContext,
) -> Any:
    if (
        os.environ.get("NOTEAI_DURABLE_AI_ACCEPTANCE_MODE") != "1"
        or context.lease.operation_id != _acceptance_operation_id()
        or context.operation_kind != ai_operations.OperationKind.ANALYZE.value
        or payload != {"acceptance": "durable-ai-v1"}
    ):
        raise RuntimeError("internal acceptance contract rejected")
    if not ai_operations.append_progress_event(
        context.lease,
        detail_hash=ai_operations.sha256_digest(
            "durable-ai-v1-payload-loaded"
        ),
    ):
        raise RuntimeError("internal acceptance progress fence lost")
    action = os.environ.get("NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION", "")
    if action == "hold_after_payload":
        time.sleep(INTERNAL_ACCEPTANCE_HOLD_SECONDS)
        raise RuntimeError("internal acceptance hold expired")
    if action == "fail_before_provider":
        raise RuntimeError("internal acceptance stop before provider")
    raise RuntimeError("internal acceptance action rejected")


def _configured_processor() -> Processor | None:
    if collection_suspended():
        return lambda _payload, _context: (_ for _ in ()).throw(
            RuntimeError("suspended processor must not run")
        )
    if (
        os.environ.get("NOTEAI_DURABLE_AI_PROCESSOR")
        == "internal-acceptance-v1"
        and os.environ.get("NOTEAI_DURABLE_AI_ACCEPTANCE_MODE") == "1"
        and _acceptance_operation_id() is not None
    ):
        return _internal_acceptance_processor
    return None


def healthcheck(*, storage_configured: bool | None = None) -> dict[str, Any]:
    if os.environ.get("NOTEAI_RUNTIME_ROLE") not in {"ai-worker", None, ""}:
        return {
            "ok": False,
            "reason": "runtime_role_not_allowed",
            "provider_called": False,
            "database_write": False,
        }
    component = os.environ.get("NOTEAI_DURABLE_AI_COMPONENT", "").strip()
    if component == "dispatcher":
        if _dispatcher_storage_env_present():
            result = {
                "ok": False,
                "reason": "dispatcher_storage_boundary",
                "provider_called": False,
                "database_write": False,
            }
        else:
            result = durable_ai.dispatcher_health()
        result["service"] = "noteai-ai-dispatcher"
    elif component == "worker":
        if storage_configured is not True:
            result = {
                "ok": False,
                "reason": "private_storage_unavailable",
                "provider_called": False,
                "database_write": False,
            }
        else:
            result = durable_ai.worker_health()
        result["service"] = "noteai-ai-worker"
    elif not component:
        result = durable_ai.health()
        result["service"] = "noteai-ai-worker"
    else:
        return {
            "ok": False,
            "reason": "durable_component_not_allowed",
            "provider_called": False,
            "database_write": False,
        }
    result["suspended"] = collection_suspended()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--recover-unstarted", action="store_true")
    parser.add_argument("--reconcile-stale", action="store_true")
    parser.add_argument("--dispatcher-once", action="store_true")
    parser.add_argument("--dispatcher-loop", action="store_true")
    parser.add_argument("--worker-once", action="store_true")
    parser.add_argument("--worker-loop", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    if sum(
        bool(value)
        for value in (
            args.healthcheck,
            args.once,
            args.recover_unstarted,
            args.reconcile_stale,
            args.dispatcher_once,
            args.dispatcher_loop,
            args.worker_once,
            args.worker_loop,
        )
    ) != 1:
        parser.error("one exact command is required")
    component = os.environ.get("NOTEAI_DURABLE_AI_COMPONENT", "").strip()
    dispatcher_command = args.dispatcher_once or args.dispatcher_loop
    worker_command = args.worker_once or args.worker_loop
    storage_configured = component == "dispatcher"
    if component != "dispatcher":
        storage_configured = private_storage.configure_from_environment()
    if args.healthcheck:
        result = healthcheck(storage_configured=storage_configured)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("ok") else 1
    if args.once:
        print(
            json.dumps({
                "status": "blocked",
                "reason": "production_processor_not_configured",
                "provider_called": False,
                "database_write": False,
            }, sort_keys=True),
            file=sys.stderr,
        )
        return 78
    if dispatcher_command:
        if component != "dispatcher":
            print(json.dumps({
                "status": "blocked",
                "reason": "durable_component_not_allowed",
                "provider_called": False,
                "database_write": False,
            }, sort_keys=True), file=sys.stderr)
            return 78
        acceptance_requested = (
            "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE" in os.environ
            or "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID" in os.environ
        )
        dispatch_operation_id = (
            _acceptance_operation_id() if acceptance_requested else None
        )
        if acceptance_requested and (
            os.environ.get("NOTEAI_DURABLE_AI_ACCEPTANCE_MODE") != "1"
            or dispatch_operation_id is None
            or not args.dispatcher_once
        ):
            print(json.dumps({
                "status": "blocked",
                "reason": "acceptance_exact_dispatch_required",
                "provider_called": False,
                "database_write": False,
            }, sort_keys=True), file=sys.stderr)
            return 78
        if args.dispatcher_once:
            result = PostgresOutboxDispatcher().run_once(
                operation_id=dispatch_operation_id,
            )
            print(json.dumps(result, sort_keys=True))
            if acceptance_requested:
                return 0 if result.get("status") == "delivered" else 1
            return 0 if result.get("status") in {"idle", "delivered", "suspended"} else 1
        run_dispatcher_loop(poll_seconds=args.poll_seconds)
        return 0
    if worker_command:
        if component != "worker":
            print(json.dumps({
                "status": "blocked",
                "reason": "durable_component_not_allowed",
                "provider_called": False,
                "database_write": False,
            }, sort_keys=True), file=sys.stderr)
            return 78
        if not storage_configured:
            print(json.dumps({
                "status": "blocked",
                "reason": "private_storage_unavailable",
                "provider_called": False,
                "database_write": False,
            }, sort_keys=True), file=sys.stderr)
            return 78
        processor = _configured_processor()
        if processor is None:
            print(json.dumps({
                "status": "blocked",
                "reason": "production_processor_not_configured",
                "provider_called": False,
                "database_write": False,
            }, sort_keys=True), file=sys.stderr)
            return 78
        acceptance_operation_id = (
            _acceptance_operation_id()
            if os.environ.get("NOTEAI_DURABLE_AI_PROCESSOR")
            == "internal-acceptance-v1"
            else None
        )
        if acceptance_operation_id is not None and args.worker_loop:
            print(json.dumps({
                "status": "blocked",
                "reason": "acceptance_once_required",
                "provider_called": False,
                "database_write": False,
            }, sort_keys=True), file=sys.stderr)
            return 78
        worker = DurableAiWorker(
            processor=processor,
            lease_seconds=(
                INTERNAL_ACCEPTANCE_LEASE_SECONDS
                if acceptance_operation_id is not None
                else 900
            ),
        )
        if args.worker_once:
            result = (
                worker.run_message(acceptance_operation_id)
                if acceptance_operation_id is not None
                else worker.run_once()
            )
            print(json.dumps(result, sort_keys=True))
            return 0 if result.get("status") in {
                "idle", "suspended", "succeeded", "refunded", "needs_manual"
            } else 1
        run_worker_loop(worker, poll_seconds=args.poll_seconds)
        return 0
    if args.recover_unstarted:
        count = durable_ai.recover_unstarted_leases(limit=10)
        print(json.dumps({
            "status": "ok",
            "recovered": count,
            "provider_called": False,
        }, sort_keys=True))
        return 0
    count = durable_ai.reconcile_stale_provider_outcomes(limit=10)
    print(json.dumps({
        "status": "ok",
        "reconciled": count,
        "provider_called": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
