"""Shared Claude Gateway control-plane contracts.

Implementations may persist only digests, fixed enums, timestamps, model names,
and numeric usage summaries. Provider inputs and outputs never cross this API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class ControlStoreUnavailable(RuntimeError):
    pass


class OperationState(str, Enum):
    CLAIMED = "CLAIMED"
    PROVIDER_STARTED = "PROVIDER_STARTED"
    TERMINAL_USAGE = "TERMINAL_USAGE"
    AMBIGUOUS = "AMBIGUOUS"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({
    OperationState.TERMINAL_USAGE,
    OperationState.AMBIGUOUS,
    OperationState.PARTIAL,
    OperationState.CANCELLED,
})


@dataclass(frozen=True)
class OperationClaim:
    state: OperationState
    created: bool


@dataclass(frozen=True)
class Lease:
    slot: int
    operation_hash: str
    owner_token: str
    fence: int
    expires_at: int


class ControlStore(Protocol):
    async def claim_nonce(
        self,
        principal_id: str,
        nonce: str,
        now_epoch: int,
        expires_at: int,
    ) -> bool: ...

    async def admit_rate(
        self,
        principal_id: str,
        now_epoch: float,
        limit: int,
        window_seconds: int,
    ) -> bool: ...

    async def claim_operation(
        self,
        principal_id: str,
        operation_id: str,
    ) -> OperationClaim: ...

    async def acquire_lease(
        self,
        operation_id: str,
        slot_count: int,
        now_epoch: int,
        lease_seconds: int,
    ) -> Lease | None: ...

    async def begin_provider(
        self,
        operation_id: str,
        lease: Lease,
        dispatch_hash: str,
        model: str,
        now_epoch: int,
    ) -> bool: ...

    async def renew_lease(
        self,
        lease: Lease,
        now_epoch: int,
        lease_seconds: int,
    ) -> Lease | None: ...

    async def finish_operation(
        self,
        operation_id: str,
        lease: Lease,
        state: OperationState,
        now_epoch: int,
        *,
        retention_seconds: int,
        usage: dict[str, Any] | None = None,
        error_code: str = "",
    ) -> bool: ...

    async def release_lease(self, lease: Lease) -> bool: ...

    async def health(self) -> bool: ...
