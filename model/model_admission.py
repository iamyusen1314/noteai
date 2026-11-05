"""Bounded, fair admission for the single user-API process.

This queue owns no provider calls, money, durable jobs or request payloads.  The
existing database reservation remains the final physical-call/budget guard.
Waiting for a permit is separate from a provider's HTTP/business deadline.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import functools
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
    seedream: int = 1
    claude_rpm: int = 30
    media_workers: int = 2
    operations: int = 10
    operations_per_user: int = 1
    pending_calls: int = 64
    queue_seconds: float = 1800.0
    no_progress_seconds: float = 300.0

    @classmethod
    def environment(cls):
        import model_capacity
        capacity_mode = model_capacity.enabled()
        physical = _number("NOTEAI_MODEL_PHYSICAL_CONCURRENCY", 2, 1, 16)
        return cls(
            physical=physical,
            claude=_number("NOTEAI_CLAUDE_CONCURRENCY", 2, 1, 16),
            kimi=_number("NOTEAI_KIMI_TEXT_CONCURRENCY", 2, 1, 16),
            doubao=_number("NOTEAI_DOUBAO_CONCURRENCY", 2, 1, 16),
            seedream=_number("NOTEAI_SEEDREAM_CONCURRENCY", 1, 1, 1),
            claude_rpm=_number("NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE", 30, 1,
                               60000 if capacity_mode else 6000),
            media_workers=_number("NOTEAI_MEDIA_WORKER_CONCURRENCY", 2, 1, 8),
            operations=_number("NOTEAI_MODEL_ADMITTED_OPERATIONS", 100 if capacity_mode else 10,
                               1, 1024 if capacity_mode else 64),
            operations_per_user=_number("NOTEAI_MODEL_OPERATIONS_PER_USER", 1, 1, 4),
            pending_calls=_number("NOTEAI_MODEL_PENDING_CALLS", 512 if capacity_mode else 64,
                                  1, 4096 if capacity_mode else 256),
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
    model_id: str | None = None
    rate_granted_at: float | None = None
    weight: int = 1
    capacity_wait_seconds: float = 0.0
    deferred_started: float | None = None
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
        self.deferred = {}
        self.last_user = None
        self.last_progress = time.monotonic()
        self.progress_source = progress_source
        self.rates = dict(rates or {})
        self.grants = {provider: deque() for provider in self.rates}

    def _tickets(self):
        return ([t for tasks in self.waiting.values() for items in tasks.values() for t in items]
                + list(self.deferred.values()))

    def _remove(self, ticket):
        self.deferred.pop(ticket.call_id, None)
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
        while sum(t.weight for t in self.active.values()) < self.capacity and self.waiting:
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
                    family = self._family_key(candidate)
                    used = sum(self._family_key(t) == family for t in self.active.values())
                    rate_key = candidate.provider if family == candidate.provider else None
                    history = self.grants.get(rate_key)
                    retained_rate = (candidate.rate_granted_at is not None
                                     and now - candidate.rate_granted_at < 60.)
                    rate_available = (history is None or retained_rate
                                      or len(history) < self.rates[rate_key])
                    fits_weight = sum(t.weight for t in self.active.values()) + candidate.weight <= self.capacity
                    if rate_available and fits_weight and used < self.families.get(family, self.capacity):
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
            rate_key = selected.provider if self._family_key(selected) == selected.provider else None
            if (rate_key in self.grants and (selected.rate_granted_at is None
                    or now - selected.rate_granted_at >= 60.)):
                # Reserve an RPM place at grant, including a later cancelled
                # grant. This conservative local ceiling is never a usage bill.
                self.grants[rate_key].append(now)
                selected.rate_granted_at = now
            self.last_user = selected.operation.user_id
            if selected.operation.user_id in self.waiting:
                self.waiting.move_to_end(selected.operation.user_id)
            selected.notify()

    def _family_key(self, ticket):
        key = (ticket.provider, ticket.model_id)
        return key if key in self.families else ticket.provider

    def enqueue(self, operation, call_id, provider, *, model_id=None, weight=1):
        with self.lock:
            if type(weight) is not int or not 1 <= weight <= self.capacity:
                raise AdmissionError("MODEL_BUFFER_SIZE_EXCEEDED")
            if operation.cancelled.is_set():
                raise AdmissionError("MODEL_OPERATION_CANCELLED")
            pending = self._tickets()
            if call_id in self.active or any(t.call_id == call_id for t in pending):
                raise AdmissionError("MODEL_CALL_ALREADY_ADMITTED")
            if len(pending) >= self.pending_limit:
                raise AdmissionError("MODEL_QUEUE_FULL")
            ticket = Ticket(operation, call_id, provider, time.monotonic())
            ticket.model_id = model_id
            ticket.weight = weight
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

    def acquire(self, operation, call_id, provider, *, model_id=None, weight=1):
        ticket = self.enqueue(operation, call_id, provider, model_id=model_id, weight=weight)
        try:
            while not self._check(ticket):
                ticket.event.wait(.1)
                ticket.event.clear()
            return ticket
        except BaseException:
            self.release(ticket)
            raise

    async def acquire_async(self, operation, call_id, provider, *, model_id=None, weight=1):
        ticket = self.enqueue(operation, call_id, provider, model_id=model_id, weight=weight)
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

    def defer(self, ticket):
        """Park an unissued call without occupying a socket execution place."""
        with self.lock:
            if (ticket.closed or ticket.dispatched or ticket.held_by_stream
                    or self.active.get(ticket.call_id) is not ticket):
                raise AdmissionError("MODEL_CALL_CANNOT_DEFER")
            del self.active[ticket.call_id]
            ticket.granted = False
            ticket.granted_at = None
            ticket.deferred_started = time.monotonic()
            self.deferred[ticket.call_id] = ticket
            self._grant()

    def _requeue_deferred(self, ticket):
        with self.lock:
            if (ticket.closed or ticket.operation.cancelled.is_set()
                    or self.deferred.get(ticket.call_id) is not ticket):
                raise AdmissionError("MODEL_OPERATION_CANCELLED")
            del self.deferred[ticket.call_id]
            ticket.event.clear()
            tasks = self.waiting.setdefault(ticket.operation.user_id, OrderedDict())
            tasks.setdefault(ticket.operation.request_hash, deque()).append(ticket)
            self._grant()

    def resume(self, ticket):
        """Fairly requeue the same identity; never register another operation."""
        try:
            self._requeue_deferred(ticket)
            while not self._check(ticket):
                ticket.event.wait(.1)
                ticket.event.clear()
            self._finish_deferred_wait(ticket)
            return ticket
        except BaseException:
            self.release(ticket)
            raise

    async def resume_async(self, ticket):
        wake = asyncio.Event()
        ticket.asynchronous = (asyncio.get_running_loop(), wake)
        try:
            self._requeue_deferred(ticket)
            while not self._check(ticket):
                try:
                    await asyncio.wait_for(wake.wait(), .25)
                except asyncio.TimeoutError:
                    pass
                wake.clear()
            self._finish_deferred_wait(ticket)
            return ticket
        except BaseException:
            self.release(ticket)
            raise

    def _finish_deferred_wait(self, ticket):
        with self.lock:
            if ticket.deferred_started is not None:
                ticket.capacity_wait_seconds += max(0., time.monotonic() - ticket.deferred_started)
                ticket.deferred_started = None

    def deferred_seconds(self, ticket):
        with self.lock:
            ongoing = (max(0., time.monotonic() - ticket.deferred_started)
                       if ticket.deferred_started is not None else 0.)
            return ticket.capacity_wait_seconds + ongoing

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
        self._remote_executor = None
        families = {k: getattr(self.limits, k) for k in ("claude", "kimi", "doubao", "seedream")}
        import model_capacity
        remote_capacity = self.limits.physical
        if model_capacity.enabled():
            # This bounds local sockets/threads, not supplier RPM/TPM/IPM.
            # CPU-heavy image preparation remains in the separate media queue.
            remote_capacity = _number("NOTEAI_MODEL_REMOTE_CONCURRENCY", 16, 1, 256)
            for model_id in model_capacity.model_ids():
                policy = model_capacity.policy_for(model_id)
                if policy is not None:
                    provider = ("seedream" if "seedream" in model_id else
                                "claude" if model_id.startswith("claude") else
                                "kimi" if model_id.startswith(("kimi", "moonshot")) else "doubao")
                    families[(provider, model_id)] = policy.concurrency or remote_capacity
        self.calls = FairQueue(remote_capacity, families,
                               self.limits.pending_calls, self.limits.queue_seconds,
                               self.limits.no_progress_seconds,
                               rates={"claude": self.limits.claude_rpm})
        self.media = FairQueue(self.limits.media_workers, {}, self.limits.pending_calls,
                               self.limits.queue_seconds, self.limits.no_progress_seconds,
                               progress_source=self.calls.progress_snapshot)
        self.buffers = FairQueue(_number("NOTEAI_MODEL_BUFFER_MIB", 256, 1, 2048) * 1024 * 1024,
                                 {}, self.limits.pending_calls, self.limits.queue_seconds,
                                 self.limits.no_progress_seconds,
                                 progress_source=self.calls.progress_snapshot)
        self.gateway_bodies = FairQueue(
            _number("NOTEAI_CLAUDE_GATEWAY_INFLIGHT_BODY_BYTES", 32 * 1024 * 1024,
                    1, 256 * 1024 * 1024), {}, self.limits.pending_calls,
            self.limits.queue_seconds, self.limits.no_progress_seconds,
            progress_source=self.calls.progress_snapshot)
        self.gateway_dns = FairQueue(2, {}, self.limits.pending_calls,
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
        self.buffers.cancel(operation)
        self.gateway_bodies.cancel(operation)
        self.gateway_dns.cancel(operation)

    def cancel_active(self, operation):
        # Use the same calls->media lock order for the active check and Event
        # update. Last release either wins (save is no longer cancellable), or
        # cancellation wins and the existing pre-save gate observes it.
        with self.calls.lock, self.media.lock, self.buffers.lock, self.gateway_bodies.lock, self.gateway_dns.lock:
            if operation.cancelled.is_set():
                return True
            tickets = (self.calls._tickets() + list(self.calls.active.values())
                       + self.media._tickets() + list(self.media.active.values())
                       + self.buffers._tickets() + list(self.buffers.active.values())
                       + self.gateway_bodies._tickets() + list(self.gateway_bodies.active.values())
                       + self.gateway_dns._tickets() + list(self.gateway_dns.active.values()))
            if not any(t.operation is operation for t in tickets):
                return False
            self.cancel(operation)
            return True

    def remote_executor(self):
        with self.lock:
            if self._remote_executor is None:
                self._remote_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self.calls.capacity, thread_name_prefix="noteai-model-io")
            return self._remote_executor

    def close_remote_workers(self):
        with self.lock:
            executor, self._remote_executor = self._remote_executor, None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=False)


_instance = None
_instance_lock = threading.Lock()


def current():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = Admission()
        return _instance


async def run_remote(function, *args, **kwargs):
    """Keep long vendor I/O out of the CPU/upload/default worker executor."""
    import model_capacity
    if not model_capacity.enabled():
        return await asyncio.to_thread(function, *args, **kwargs)
    context = contextvars.copy_context()
    work = functools.partial(function, *args, **kwargs)
    return await asyncio.get_running_loop().run_in_executor(
        current().remote_executor(), context.run, work)
