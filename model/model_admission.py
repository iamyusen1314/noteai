"""Bounded, fair admission for the single user-API process.

This queue owns no provider calls, money, durable jobs or request payloads.  The
existing database reservation remains the final physical-call/budget guard.
Waiting for a permit is separate from a provider's HTTP/business deadline.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import threading
import time


class AdmissionError(RuntimeError):
    pass


def _number(name, default, minimum, maximum):
    value = int(os.environ.get(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError("invalid model admission configuration: " + name)
    return value


@dataclass(frozen=True)
class Limits:
    # These are operational ceilings, not claims about supplier entitlement.
    physical: int = 2
    claude: int = 2
    kimi: int = 2
    doubao: int = 2
    claude_rpm: int = 30
    media_workers: int = 2
    operations: int = 10
    operations_per_user: int = 1
    pending_calls: int = 64
    queue_seconds: float = 1800.0
    no_progress_seconds: float = 300.0

    @classmethod
    def environment(cls):
        physical = _number("NOTEAI_MODEL_PHYSICAL_CONCURRENCY", 2, 1, 16)
        return cls(
            physical=physical,
            claude=_number("NOTEAI_CLAUDE_CONCURRENCY", 2, 1, 16),
            kimi=_number("NOTEAI_KIMI_TEXT_CONCURRENCY", 2, 1, 16),
            doubao=_number("NOTEAI_DOUBAO_CONCURRENCY", 2, 1, 16),
            claude_rpm=_number("NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE", 30, 1, 6000),
            media_workers=_number("NOTEAI_MEDIA_WORKER_CONCURRENCY", 2, 1, 8),
            operations=_number("NOTEAI_MODEL_ADMITTED_OPERATIONS", 10, 1, 64),
            operations_per_user=_number("NOTEAI_MODEL_OPERATIONS_PER_USER", 1, 1, 4),
            pending_calls=_number("NOTEAI_MODEL_PENDING_CALLS", 64, 1, 256),
            queue_seconds=_number("NOTEAI_MODEL_QUEUE_SECONDS", 1800, 30, 1800),
            no_progress_seconds=_number("NOTEAI_MODEL_NO_PROGRESS_SECONDS", 300, 250, 900),
        )


@dataclass(eq=False)
class Operation:
    user_id: str
    request_hash: str
    route: str = ""
    cancelled: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    outstanding: int = 0
    completed_calls: int = 0
    last_progress: float = field(default_factory=lambda: time.monotonic())
    last_progress_at: str | None = None
    exiting: bool = False
    on_idle: object = None


@dataclass(eq=False)
class Ticket:
    operation: Operation
    call_id: str
    provider: str
    queued_at: float
    event: threading.Event = field(default_factory=threading.Event)
    asynchronous: tuple | None = None
    granted: bool = False
    granted_at: float | None = None
    last_activity: float | None = None
    dispatched: bool = False
    progress: bool = False
    held_by_stream: bool = False
    closed: bool = False

    def notify(self):
        self.event.set()
        if self.asynchronous is not None:
            loop, event = self.asynchronous
            if not loop.is_closed():
                loop.call_soon_threadsafe(event.set)


class FairQueue:
    """Round robin by user, then request; one ticket per physical operation."""

    def __init__(self, capacity, families, pending, wait_seconds, no_progress_seconds,
                 progress_source=None, rates=None):
        self.capacity = capacity
        self.families = dict(families)
        self.pending_limit = pending
        self.wait_seconds = wait_seconds
        self.no_progress_seconds = no_progress_seconds
        self.lock = threading.RLock()
        self.waiting = OrderedDict()
        self.active = {}
        self.last_user = None
        self.last_progress = time.monotonic()
        self.progress_source = progress_source
        self.rates = dict(rates or {})
        self.grants = {provider: deque() for provider in self.rates}

    def _tickets(self):
        return [t for tasks in self.waiting.values() for items in tasks.values() for t in items]

    def _remove(self, ticket):
        tasks = self.waiting.get(ticket.operation.user_id)
        if tasks is None:
            return
        items = tasks.get(ticket.operation.request_hash)
        if items is not None and ticket in items:
            items.remove(ticket)
            if not items:
                del tasks[ticket.operation.request_hash]
        if not tasks:
            del self.waiting[ticket.operation.user_id]

    def _grant(self):
        now = time.monotonic()
        for history in self.grants.values():
            while history and now - history[0] >= 60.:
                history.popleft()
        while len(self.active) < self.capacity and self.waiting:
            users = list(self.waiting)
            if len(users) > 1 and users[0] == self.last_user:
                users = users[1:] + users[:1]
            selected = None
            for uid in users:
                tasks = self.waiting[uid]
                for key, items in list(tasks.items()):
                    candidate = items[0]
                    if candidate.operation.cancelled.is_set():
                        candidate.notify()
                        continue
                    if now - max(candidate.queued_at, candidate.operation.last_progress) >= self.wait_seconds:
                        candidate.notify()
                        continue
                    used = sum(t.provider == candidate.provider for t in self.active.values())
                    history = self.grants.get(candidate.provider)
                    rate_available = history is None or len(history) < self.rates[candidate.provider]
                    if rate_available and used < self.families.get(candidate.provider, self.capacity):
                        selected = candidate
                        tasks.move_to_end(key)
                        break
                if selected is not None:
                    break
            if selected is None:
                return
            self._remove(selected)
            selected.granted = True
            selected.granted_at = time.monotonic()
            selected.last_activity = selected.granted_at
            self.active[selected.call_id] = selected
            if selected.provider in self.grants:
                # Reserve an RPM place at grant, including a later cancelled
                # grant. This conservative local ceiling is never a usage bill.
                self.grants[selected.provider].append(now)
            self.last_user = selected.operation.user_id
            if selected.operation.user_id in self.waiting:
                self.waiting.move_to_end(selected.operation.user_id)
            selected.notify()

    def enqueue(self, operation, call_id, provider):
        with self.lock:
            if operation.cancelled.is_set():
                raise AdmissionError("MODEL_OPERATION_CANCELLED")
            pending = self._tickets()
            if call_id in self.active or any(t.call_id == call_id for t in pending):
                raise AdmissionError("MODEL_CALL_ALREADY_ADMITTED")
            if len(pending) >= self.pending_limit:
                raise AdmissionError("MODEL_QUEUE_FULL")
            ticket = Ticket(operation, call_id, provider, time.monotonic())
            with operation.lock:
                operation.outstanding += 1
            tasks = self.waiting.setdefault(operation.user_id, OrderedDict())
            tasks.setdefault(operation.request_hash, deque()).append(ticket)
            self._grant()
            return ticket

    def _check(self, ticket):
        if ticket.operation.cancelled.is_set():
            raise AdmissionError("MODEL_OPERATION_CANCELLED")
        with self.lock:
            # A rate-limited queue can have no active call left to wake it.
            self._grant()
            if ticket.granted:
                return True
        now = time.monotonic()
        # This is a task-starvation bound, not the age of a sibling call. A
        # healthy task completing its earlier expert calls may continue waiting
        # for the remaining ones. Other users' progress cannot renew this bound.
        if now - max(ticket.queued_at, ticket.operation.last_progress) >= self.wait_seconds:
            raise AdmissionError("MODEL_QUEUE_WAIT_EXCEEDED")
        # A long queue making progress is different from stuck in-flight calls.
        # Media workers can be waiting for a healthy model queue. Observe its
        # real completions without taking the calls lock under the media lock.
        progress = self.progress_source() if self.progress_source else self.last_progress
        with self.lock:
            if self.active and now - max(self.last_progress, progress,
                                         max(t.last_activity for t in self.active.values())) >= self.no_progress_seconds:
                raise AdmissionError("MODEL_QUEUE_NO_PROGRESS")
        return False

    def progress_snapshot(self):
        with self.lock:
            return max([self.last_progress] + [t.last_activity for t in self.active.values()])

    def note_activity(self, ticket):
        # Wire progress is only a liveness observation. It never settles usage,
        # increments completed calls, or renews a paid task's durable claim.
        with self.lock:
            if (not ticket.closed and ticket.dispatched
                    and self.active.get(ticket.call_id) is ticket):
                ticket.last_activity = time.monotonic()

    def acquire(self, operation, call_id, provider):
        ticket = self.enqueue(operation, call_id, provider)
        try:
            while not self._check(ticket):
                ticket.event.wait(.1)
                ticket.event.clear()
            return ticket
        except BaseException:
            self.release(ticket)
            raise

    async def acquire_async(self, operation, call_id, provider):
        ticket = self.enqueue(operation, call_id, provider)
        wake = asyncio.Event()
        ticket.asynchronous = (asyncio.get_running_loop(), wake)
        try:
            while not self._check(ticket):
                try:
                    await asyncio.wait_for(wake.wait(), .25)
                except asyncio.TimeoutError:
                    pass
                wake.clear()
            return ticket
        except BaseException:
            self.release(ticket)
            raise

    def release(self, ticket):
        callback = None
        with self.lock:
            if ticket.closed:
                return
            ticket.closed = True
            self._remove(ticket)
            self.active.pop(ticket.call_id, None)
            with ticket.operation.lock:
                ticket.operation.outstanding -= 1
                if ticket.progress:
                    self.last_progress = time.monotonic()
                    ticket.operation.last_progress = self.last_progress
                    ticket.operation.last_progress_at = datetime.now(timezone.utc).isoformat()
                    ticket.operation.completed_calls += 1
                if ticket.operation.exiting and ticket.operation.outstanding == 0:
                    callback = ticket.operation.on_idle
            self._grant()
        if callable(callback):
            callback()

    def cancel(self, operation):
        operation.cancelled.set()
        with self.lock:
            for ticket in self._tickets():
                if ticket.operation is operation:
                    ticket.notify()
            self._grant()

    def status(self, operation):
        with self.lock:
            waiting = [t for t in self._tickets() if t.operation is operation]
            active = [t for t in self.active.values() if t.operation is operation]
            now = time.monotonic()
            result = {"active": True, "can_cancel": bool(waiting or active) and not operation.cancelled.is_set(),
                      "state": "queued" if waiting else "running" if active else "idle",
                      "provider": (waiting or active)[0].provider if waiting or active else None,
                      "waiting_seconds": round(max((now - t.queued_at for t in waiting), default=0), 1),
                      "completed_calls": operation.completed_calls,
                      "last_progress_at": operation.last_progress_at,
                      "last_progress_seconds": round(max(0, now - operation.last_progress), 1),
                      "cancel_requested": operation.cancelled.is_set()}
            # RR has no stable FIFO position or reliable ETA. Report counts,
            # rather than presenting arrival order as actual execution order.
            result["queued_calls"] = len(waiting)
            result["waiting_operations"] = len({(t.operation.user_id, t.operation.request_hash)
                                                 for t in self._tickets()})
            if operation.cancelled.is_set():
                result["state"] = "settling" if any(t.dispatched for t in active) else "cancelling"
            return result


class Admission:
    def __init__(self, limits=None):
        self.limits = limits or Limits.environment()
        self.lock = threading.RLock()
        self.operations = {}
        self.aliases = {}
        self.calls = FairQueue(self.limits.physical,
                               {k: getattr(self.limits, k) for k in ("claude", "kimi", "doubao")},
                               self.limits.pending_calls, self.limits.queue_seconds,
                               self.limits.no_progress_seconds,
                               rates={"claude": self.limits.claude_rpm})
        self.media = FairQueue(self.limits.media_workers, {}, self.limits.pending_calls,
                               self.limits.queue_seconds, self.limits.no_progress_seconds,
                               progress_source=self.calls.progress_snapshot)

    def register(self, user_id, request_hash, *, route=""):
        key = (user_id, request_hash)
        with self.lock:
            existing = self.operations.get(key) or self.aliases.get(key)
            if existing is not None:
                # Original idempotency keys include the business operation.
                # Only retransmissions of the same HTTP route may borrow its
                # in-flight scope; a different paid route is a separate task.
                if existing.route != route:
                    raise AdmissionError("MODEL_USER_OPERATION_BUSY")
                return existing, False
            if len(self.operations) >= self.limits.operations:
                raise AdmissionError("MODEL_OPERATIONS_BUSY")
            if sum(uid == user_id for uid, _key in self.operations) >= self.limits.operations_per_user:
                raise AdmissionError("MODEL_USER_OPERATION_BUSY")
            operation = Operation(user_id, request_hash, route=route)
            operation.on_idle = lambda: self.finish(operation)
            self.operations[key] = operation
            return operation, True

    def finish(self, operation):
        with self.lock, operation.lock:
            operation.exiting = True
            if operation.outstanding == 0:
                key = (operation.user_id, operation.request_hash)
                if self.operations.get(key) is operation:
                    del self.operations[key]
                for key, value in list(self.aliases.items()):
                    if value is operation:
                        del self.aliases[key]

    def find(self, user_id, request_hash):
        with self.lock:
            key = (user_id, request_hash)
            return self.operations.get(key) or self.aliases.get(key)

    def bind_claim(self, operation, original_key_hash):
        # A clarification resume has a new HTTP request ID but retains its
        # original paid claim. Cancellation/status must still address that task.
        key = (operation.user_id, original_key_hash)
        with self.lock:
            existing = self.find(*key)
            if existing is not None and existing is not operation:
                raise AdmissionError("MODEL_TASK_ALREADY_RUNNING")
            if self.operations.get((operation.user_id, operation.request_hash)) is operation:
                self.aliases[key] = operation

    def cancel(self, operation):
        self.calls.cancel(operation)
        self.media.cancel(operation)

    def cancel_active(self, operation):
        # Use the same calls->media lock order for the active check and Event
        # update. Last release either wins (save is no longer cancellable), or
        # cancellation wins and the existing pre-save gate observes it.
        with self.calls.lock, self.media.lock:
            if operation.cancelled.is_set():
                return True
            tickets = (self.calls._tickets() + list(self.calls.active.values())
                       + self.media._tickets() + list(self.media.active.values()))
            if not any(t.operation is operation for t in tickets):
                return False
            self.cancel(operation)
            return True


_instance = None
_instance_lock = threading.Lock()


def current():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = Admission()
        return _instance
