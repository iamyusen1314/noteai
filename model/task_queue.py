"""Provider-neutral task queue contract backed by the primary database."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import ai_operations


class TaskQueue(ABC):
    @abstractmethod
    def create_operation(self, **kwargs) -> str:
        raise NotImplementedError

    @abstractmethod
    def claim_next(self, **kwargs) -> ai_operations.OperationLease | None:
        raise NotImplementedError

    @abstractmethod
    def heartbeat(
        self,
        lease: ai_operations.OperationLease,
        **kwargs,
    ) -> ai_operations.OperationLease | None:
        raise NotImplementedError

    @abstractmethod
    def reap_stale_provider_outcomes(self, **kwargs) -> int:
        raise NotImplementedError

    @abstractmethod
    def record_provider_started(
        self,
        lease: ai_operations.OperationLease,
        **kwargs,
    ) -> ai_operations.ProviderAttempt | None:
        raise NotImplementedError

    @abstractmethod
    def mark_terminal(self, lease: ai_operations.OperationLease, **kwargs) -> bool:
        raise NotImplementedError


class DatabaseTaskQueue(TaskQueue):
    """Short-transaction queue using SQLite serialization or PG row locking."""

    def create_operation(
        self,
        *,
        subject_hash: str,
        request_hash: str,
        operation_kind: str | ai_operations.OperationKind,
        operation_id: str | None = None,
        priority: int = 0,
        available_at: datetime | None = None,
        now: datetime | None = None,
    ) -> str:
        return ai_operations.enqueue_operation(
            subject_hash=subject_hash,
            request_hash=request_hash,
            operation_kind=operation_kind,
            operation_id=operation_id,
            priority=priority,
            available_at=available_at,
            now=now,
        )

    def claim_next(
        self,
        *,
        lease_seconds: int,
        owner_token: str | None = None,
        reap_limit: int = 1,
        now: datetime | None = None,
    ) -> ai_operations.OperationLease | None:
        return ai_operations.claim_next_operation(
            lease_seconds=lease_seconds,
            owner_token=owner_token,
            reap_limit=reap_limit,
            now=now,
        )

    def heartbeat(
        self,
        lease: ai_operations.OperationLease,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ai_operations.OperationLease | None:
        return ai_operations.heartbeat_operation(
            lease,
            lease_seconds=lease_seconds,
            now=now,
        )

    def reap_stale_provider_outcomes(
        self,
        *,
        limit: int = 1,
        now: datetime | None = None,
    ) -> int:
        return ai_operations.reap_stale_provider_outcomes(limit=limit, now=now)

    def record_progress(
        self,
        lease: ai_operations.OperationLease,
        *,
        detail_hash: str | None = None,
        item_count: int = 0,
        now: datetime | None = None,
    ) -> bool:
        return ai_operations.append_progress_event(
            lease,
            detail_hash=detail_hash,
            item_count=item_count,
            now=now,
        )

    def record_provider_started(
        self,
        lease: ai_operations.OperationLease,
        *,
        provider: str | ai_operations.Provider,
        request_hash: str,
        model_hash: str,
        input_count: int = 0,
        now: datetime | None = None,
    ) -> ai_operations.ProviderAttempt | None:
        return ai_operations.begin_provider_attempt(
            lease,
            provider=provider,
            request_hash=request_hash,
            model_hash=model_hash,
            input_count=input_count,
            now=now,
        )

    def record_provider_terminal(
        self,
        lease: ai_operations.OperationLease,
        attempt: ai_operations.ProviderAttempt,
        *,
        state: str | ai_operations.AttemptState,
        response_hash: str | None = None,
        output_count: int = 0,
        now: datetime | None = None,
    ) -> bool:
        return ai_operations.finish_provider_attempt(
            lease,
            attempt,
            state=state,
            response_hash=response_hash,
            output_count=output_count,
            now=now,
        )

    def mark_terminal(
        self,
        lease: ai_operations.OperationLease,
        *,
        status: str | ai_operations.OperationStatus,
        result_hash: str | None = None,
        result_count: int = 0,
        now: datetime | None = None,
    ) -> bool:
        return ai_operations.finish_operation(
            lease,
            status=status,
            result_hash=result_hash,
            result_count=result_count,
            now=now,
        )

    def cancel_queued(self, operation_id: str, *, now: datetime | None = None) -> bool:
        return ai_operations.cancel_queued_operation(operation_id, now=now)

    def get(self, operation_id: str) -> dict[str, Any] | None:
        return ai_operations.get_operation(operation_id)

    def events(self, operation_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        return ai_operations.list_events(operation_id, after_sequence=after_sequence)

    def provider_attempts(self, operation_id: str) -> list[dict[str, Any]]:
        return ai_operations.list_provider_attempts(operation_id)
