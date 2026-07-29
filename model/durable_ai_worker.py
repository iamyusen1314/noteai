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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import ai_operations
import billing
import durable_ai
import private_storage


class KnownProviderFailure(RuntimeError):
    """A provider definitively rejected/failed without an ambiguous outcome."""


class ProviderOutcomeUnknown(RuntimeError):
    """The provider side effect may have occurred and must not be retried."""


Processor = Callable[[dict[str, Any], "WorkerContext"], Any]
Publisher = Callable[[str], None]


def collection_suspended() -> bool:
    return str(os.environ.get("NOTEAI_DURABLE_AI_SUSPENDED", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


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
        context_data = durable_ai.request_context(operation_id)
        if not context_data:
            return {
                "status": "rejected",
                "reason": "durable_contract_unavailable",
                "provider_called": False,
            }
        lease = ai_operations.claim_operation(
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
        worker_context = WorkerContext(
            lease=lease,
            user_id=context_data["user_id"],
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


def healthcheck() -> dict[str, Any]:
    if os.environ.get("NOTEAI_RUNTIME_ROLE") not in {"ai-worker", None, ""}:
        return {
            "ok": False,
            "reason": "runtime_role_not_allowed",
            "provider_called": False,
            "database_write": False,
        }
    result = durable_ai.health()
    result["service"] = "noteai-ai-worker"
    result["suspended"] = collection_suspended()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--recover-unstarted", action="store_true")
    parser.add_argument("--reconcile-stale", action="store_true")
    args = parser.parse_args(argv)
    if sum(
        bool(value)
        for value in (
            args.healthcheck,
            args.once,
            args.recover_unstarted,
            args.reconcile_stale,
        )
    ) != 1:
        parser.error("one exact command is required")
    private_storage.configure_from_environment()
    if args.healthcheck:
        result = healthcheck()
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
