import asyncio
import hashlib
import os
import re
import sys
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GATEWAY_DIR = ROOT / "gateway"
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))

from control_store import (
    ControlStoreUnavailable,
    Lease,
    OperationClaim,
    OperationState,
    TERMINAL_STATES,
)
from dynamodb_control_store import (
    DynamoDBControlStore,
    _capture_rehearsal_diagnostics,
)


class _ConditionalError(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _TransactionCancelledError(Exception):
    def __init__(self, reasons):
        self.response = {
            "Error": {"Code": "TransactionCanceledException"},
            "CancellationReasons": [{"Code": code} for code in reasons],
        }


class _SyntheticServiceError(Exception):
    def __init__(self, code, *, reasons=None, message="sensitive-message-sentinel"):
        super().__init__(message)
        self.response = {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"RequestId": "sensitive-request-id-sentinel"},
            "SensitiveFields": {
                "url": "https://sensitive.example.invalid/control",
                "table": "sensitive-table-sentinel",
                "role": "arn:aws:iam::123456789012:role/sensitive-role-sentinel",
                "principal": "sensitive-principal-sentinel",
                "operation": "sensitive-operation-sentinel",
            },
        }
        if reasons is not None:
            self.response["CancellationReasons"] = [
                {"Code": reason, "Message": message} for reason in reasons
            ]


class _RecordingClient:
    def __init__(self):
        self.calls = []
        self.conditional_methods = set()
        self.operation_state = OperationState.CLAIMED.value
        self.fence = 1

    def _record(self, method, kwargs):
        self._validate_expression_values(kwargs)
        self.calls.append((method, kwargs))
        if method in self.conditional_methods:
            raise _ConditionalError()

    def _validate_expression_values(self, request):
        if "TransactItems" in request:
            for item in request["TransactItems"]:
                self._validate_expression_values(next(iter(item.values())))
            return
        expressions = " ".join(
            str(value) for key, value in request.items() if key.endswith("Expression")
        )
        expected = set(re.findall(r":[A-Za-z0-9_]+", expressions))
        actual = set(request.get("ExpressionAttributeValues", {}))
        if expected != actual:
            raise AssertionError(
                f"expression placeholders differ: expected={expected}, actual={actual}"
            )

    def put_item(self, **kwargs):
        self._record("put_item", kwargs)
        return {}

    def get_item(self, **kwargs):
        self._record("get_item", kwargs)
        return {"Item": {"state": {"S": self.operation_state}}}

    def update_item(self, **kwargs):
        self._record("update_item", kwargs)
        self.fence += 1
        return {"Attributes": {"fence": {"N": str(self.fence)}}}

    def delete_item(self, **kwargs):
        self._record("delete_item", kwargs)
        return {}

    def transact_write_items(self, **kwargs):
        self._record("transact_write_items", kwargs)
        return {}

    def describe_table(self, **kwargs):
        self._record("describe_table", kwargs)
        return {"Table": {"TableStatus": "ACTIVE"}}


class _NonceConditionClient(_RecordingClient):
    def __init__(self):
        super().__init__()
        self.expiry = None

    def put_item(self, **kwargs):
        self._record("put_item", kwargs)
        self.assert_nonce_condition(kwargs)
        now = int(kwargs["ExpressionAttributeValues"][":now"]["N"])
        if self.expiry is not None and self.expiry > now:
            raise _ConditionalError()
        self.expiry = int(kwargs["Item"]["expires_at"]["N"])
        return {}

    @staticmethod
    def assert_nonce_condition(kwargs):
        expression = kwargs.get("ConditionExpression", "")
        if expression != "attribute_not_exists(pk) OR expires_at <= :now":
            raise AssertionError(f"unexpected nonce condition: {expression}")


class _OperationConditionClient(_RecordingClient):
    def __init__(self):
        super().__init__()
        self.expiry = None

    def put_item(self, **kwargs):
        self._record("put_item", kwargs)
        expression = kwargs.get("ConditionExpression", "")
        if expression != "attribute_not_exists(pk)":
            raise AssertionError(f"unexpected operation condition: {expression}")
        if self.expiry is not None:
            raise _ConditionalError()
        self.expiry = 1
        self.operation_state = kwargs["Item"]["state"]["S"]
        return {}


class _MonotonicRateClient(_RecordingClient):
    def __init__(self):
        super().__init__()
        self.window_start = None
        self.count = 0
        self.rate_keys = []

    def update_item(self, **kwargs):
        self._record("update_item", kwargs)
        key = kwargs["Key"]["pk"]["S"]
        self.rate_keys.append(key)
        condition = kwargs.get("ConditionExpression", "")
        values = kwargs.get("ExpressionAttributeValues", {})
        if condition == "attribute_not_exists(window_start) OR window_start < :window":
            candidate = int(values[":window"]["N"])
            if self.window_start is not None and self.window_start >= candidate:
                raise _ConditionalError()
            self.window_start = candidate
            self.count = 1
            return {}
        if condition == "attribute_exists(window_start) AND request_count < :limit":
            limit = int(values[":limit"]["N"])
            if self.window_start is None or self.count >= limit:
                raise _ConditionalError()
            self.count += 1
            return {}
        raise AssertionError(f"unexpected rate condition: {condition}")


class _AfterApplyFailureClient(_RecordingClient):
    def transact_write_items(self, **kwargs):
        self._record("transact_write_items", kwargs)
        self.operation_state = OperationState.PROVIDER_STARTED.value
        raise RuntimeError("connection dropped after durable apply")


class _TransactionFailureClient(_RecordingClient):
    def __init__(self, reasons):
        super().__init__()
        self.reasons = reasons

    def transact_write_items(self, **kwargs):
        self._record("transact_write_items", kwargs)
        raise _TransactionCancelledError(self.reasons)


class _BeginFailureClient(_RecordingClient):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def transact_write_items(self, **kwargs):
        self._record("transact_write_items", kwargs)
        raise self.error


class _AtomicFakeStore:
    """Shared-backend fake used to exercise the required atomic semantics."""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.nonces = {}
        self.rates = {}
        self.operations = {}
        self.slots = {}
        self.fences = {}
        self.available = True

    async def claim_nonce(self, principal, nonce, now, expires):
        async with self.lock:
            key = (principal, hashlib.sha256(nonce.encode()).hexdigest())
            if self.nonces.get(key, 0) > now or expires <= now:
                return False
            self.nonces[key] = expires
            return True

    async def admit_rate(self, principal, now, limit, window):
        async with self.lock:
            candidate_window = int(float(now) // window) * window
            stored_window, count = self.rates.get(principal, (candidate_window, 0))
            if candidate_window > stored_window:
                stored_window, count = candidate_window, 0
            if count >= limit:
                return False
            self.rates[principal] = (stored_window, count + 1)
            return True

    async def claim_operation(self, principal, operation):
        async with self.lock:
            current = self.operations.get(operation)
            if current:
                return OperationClaim(current, False)
            self.operations[operation] = OperationState.CLAIMED
            return OperationClaim(OperationState.CLAIMED, True)

    async def acquire_lease(self, operation, slots, now, seconds):
        async with self.lock:
            for slot in range(slots):
                current = self.slots.get(slot)
                if current and current.expires_at > now:
                    continue
                fence = self.fences.get(slot, 0) + 1
                self.fences[slot] = fence
                lease = Lease(slot, operation, f"owner-{operation}", fence, now + seconds)
                self.slots[slot] = lease
                return lease
            return None

    async def renew_lease(self, lease, now, seconds):
        async with self.lock:
            current = self.slots.get(lease.slot)
            if current != lease or current.expires_at <= now:
                return None
            renewed = Lease(
                lease.slot, lease.operation_hash, lease.owner_token,
                lease.fence, now + seconds,
            )
            self.slots[lease.slot] = renewed
            return renewed

    async def release_lease(self, lease):
        async with self.lock:
            if self.slots.get(lease.slot) != lease:
                return False
            self.slots.pop(lease.slot, None)
            return True

    async def begin_provider(self, operation, lease, _request_hash, _model, now):
        async with self.lock:
            current = self.slots.get(lease.slot)
            if current != lease or current.expires_at <= now:
                return False
            if self.operations.get(operation) != OperationState.CLAIMED:
                return False
            self.operations[operation] = OperationState.PROVIDER_STARTED
            return True

    async def finish_operation(
        self, operation, lease, state, _now, *, retention_seconds, **_kwargs,
    ):
        async with self.lock:
            if state not in TERMINAL_STATES:
                raise ValueError
            if self.slots.get(lease.slot) != lease:
                return False
            if self.operations.get(operation) != OperationState.PROVIDER_STARTED:
                return False
            self.operations[operation] = state
            self.slots.pop(lease.slot, None)
            return True


class AtomicControlStoreTests(unittest.TestCase):
    def test_nonce_and_stable_principal_rate_are_atomic(self):
        async def exercise():
            store = _AtomicFakeStore()
            nonce = await asyncio.gather(*[
                store.claim_nonce("noteai-prod", "same-nonce", 10, 100) for _ in range(8)
            ])
            expired_reclaim = await store.claim_nonce(
                "noteai-prod", "same-nonce", 100, 160,
            )
            invalid_expiry = await store.claim_nonce(
                "noteai-prod", "new-nonce", 100, 100,
            )
            rate = await asyncio.gather(*[
                store.admit_rate("noteai-prod", 61, 3, 60) for _ in range(8)
            ])
            next_window = await store.admit_rate("noteai-prod", 120, 3, 60)
            return nonce, expired_reclaim, invalid_expiry, rate, next_window

        nonce, expired_reclaim, invalid_expiry, rate, next_window = asyncio.run(exercise())
        self.assertEqual(nonce.count(True), 1)
        self.assertTrue(expired_reclaim)
        self.assertFalse(invalid_expiry)
        self.assertEqual(rate.count(True), 3)
        self.assertTrue(next_window)

    def test_n_slot_lease_renewal_expiry_and_fencing(self):
        async def exercise():
            store = _AtomicFakeStore()
            leases = await asyncio.gather(*[
                store.acquire_lease(f"op-{index}", 2, 100, 10) for index in range(3)
            ])
            active = [lease for lease in leases if lease]
            renewed = await store.renew_lease(active[0], 105, 10)
            stale_release = await store.release_lease(active[0])
            replacement = await store.acquire_lease("replacement", 2, 111, 10)
            return active, renewed, stale_release, replacement

        active, renewed, stale_release, replacement = asyncio.run(exercise())
        self.assertEqual(len(active), 2)
        self.assertIsNotNone(renewed)
        self.assertFalse(stale_release)
        self.assertIsNotNone(replacement)
        self.assertGreater(replacement.fence, 1)

    def test_operation_has_one_provider_start_and_one_terminal(self):
        async def exercise():
            store = _AtomicFakeStore()
            await store.claim_operation("principal", "logical-op")
            lease = await store.acquire_lease("logical-op", 1, 100, 30)
            starts = await asyncio.gather(*[
                store.begin_provider("logical-op", lease, "digest", "claude", 100)
                for _ in range(5)
            ])
            terminals = await asyncio.gather(*[
                store.finish_operation(
                    "logical-op", lease, OperationState.TERMINAL_USAGE, 101,
                    retention_seconds=1000,
                    usage={"input_tokens": 1},
                )
                for _ in range(5)
            ])
            return store, starts, terminals

        store, starts, terminals = asyncio.run(exercise())
        self.assertEqual(starts.count(True), 1)
        self.assertEqual(terminals.count(True), 1)
        self.assertEqual(store.operations["logical-op"], OperationState.TERMINAL_USAGE)

    def test_dynamodb_adapter_sends_only_digests_and_fixed_metadata(self):
        client = _RecordingClient()
        store = DynamoDBControlStore("control-table", client)

        async def exercise():
            await store.claim_nonce("principal-raw", "nonce-raw", 90, 100)
            await store.admit_rate("principal-raw", 61, 10, 60)
            await store.claim_operation("principal-raw", "operation-raw")
            lease = await store.acquire_lease("operation-raw", 2, 100, 30)
            await store.begin_provider(
                "operation-raw", lease, "dispatch-digest", "claude-haiku-4-5-20251001", 100,
            )
            await store.finish_operation(
                "operation-raw", lease, OperationState.TERMINAL_USAGE, 101,
                retention_seconds=1000,
                usage={"input_tokens": 2, "output_tokens": 1},
            )

        asyncio.run(exercise())
        serialized = repr(client.calls)
        for raw in ("principal-raw", "nonce-raw", "operation-raw", "owner-operation"):
            self.assertNotIn(raw, serialized)
        self.assertNotIn("prompt", serialized.lower())
        self.assertNotIn("messages", serialized.lower())
        self.assertIn("dispatch-digest", serialized)
        operation_put = next(
            request for method, request in client.calls
            if method == "put_item"
            and request.get("Item", {}).get("kind", {}).get("S") == "OPERATION"
        )
        self.assertNotIn("expires_at", operation_put["Item"])

        lease_updates = [
            request for method, request in client.calls
            if method == "update_item" and request.get("Key", {}).get("pk", {}).get("S", "").startswith("LEASE#")
        ]
        self.assertEqual(
            lease_updates[0]["ConditionExpression"],
            "attribute_not_exists(lease_expires_at) OR lease_expires_at <= :now",
        )
        begin_transaction = next(
            request for method, request in client.calls
            if method == "transact_write_items"
            and any("ConditionCheck" in item for item in request["TransactItems"])
        )
        begin_condition = next(
            item["ConditionCheck"]["ConditionExpression"]
            for item in begin_transaction["TransactItems"]
            if "ConditionCheck" in item
        )
        self.assertIn("lease_expires_at > :now", begin_condition)
        transaction_requests = [
            request for method, request in client.calls
            if method == "transact_write_items"
        ]
        for request in transaction_requests:
            keys = [
                next(iter(item.values()))["Key"]["pk"]["S"]
                for item in request["TransactItems"]
            ]
            self.assertEqual(len(keys), len(set(keys)))
        finish_update = next(
            item["Update"]["UpdateExpression"]
            for request in reversed(transaction_requests)
            for item in request["TransactItems"]
            if "Update" in item and "finished_at" in item["Update"]["UpdateExpression"]
        )
        self.assertIn("expires_at=:expires", finish_update)

    def test_dynamodb_nonce_condition_uses_logical_expiry_not_ttl_cleanup(self):
        client = _NonceConditionClient()
        store = DynamoDBControlStore("control-table", client)

        async def exercise():
            first = await store.claim_nonce("principal", "nonce", 100, 110)
            replay = await store.claim_nonce("principal", "nonce", 109, 120)
            boundary_reclaim = await store.claim_nonce("principal", "nonce", 110, 130)
            return first, replay, boundary_reclaim

        first, replay, boundary_reclaim = asyncio.run(exercise())
        self.assertTrue(first)
        self.assertFalse(replay)
        self.assertTrue(boundary_reclaim)

    def test_dynamodb_live_operation_is_never_reclaimed_by_ttl_time(self):
        client = _OperationConditionClient()
        store = DynamoDBControlStore("control-table", client)

        async def exercise():
            first = await store.claim_operation("principal", "operation")
            replay = await store.claim_operation("principal", "operation")
            return first, replay

        first, replay = asyncio.run(exercise())
        self.assertTrue(first.created)
        self.assertFalse(replay.created)

    def test_rate_uses_one_monotonic_principal_item_across_boundary_and_rollback(self):
        client = _MonotonicRateClient()
        store = DynamoDBControlStore("control-table", client)

        async def exercise():
            before = [
                await store.admit_rate("principal", 59.999, 2, 60)
                for _ in range(3)
            ]
            boundary = await store.admit_rate("principal", 60.000, 2, 60)
            rollback = [
                await store.admit_rate("principal", 59.999, 2, 60)
                for _ in range(2)
            ]
            return before, boundary, rollback

        before, boundary, rollback = asyncio.run(exercise())
        self.assertEqual(before, [True, True, False])
        self.assertTrue(boundary)
        self.assertEqual(rollback, [True, False])
        self.assertEqual(len(set(client.rate_keys)), 1)
        self.assertRegex(client.rate_keys[0], r"^RATE#[0-9a-f]{64}$")

    def test_lease_exact_expiry_allows_takeover_but_not_old_begin_or_renew(self):
        async def exercise():
            store = _AtomicFakeStore()
            await store.claim_operation("principal", "operation")
            old = await store.acquire_lease("operation", 1, 100, 10)
            old_begin = await store.begin_provider(
                "operation", old, "digest", "model", 110,
            )
            old_renew = await store.renew_lease(old, 110, 10)
            replacement = await store.acquire_lease("replacement", 1, 110, 10)
            return old, old_begin, old_renew, replacement

        old, old_begin, old_renew, replacement = asyncio.run(exercise())
        self.assertIsNotNone(old)
        self.assertFalse(old_begin)
        self.assertIsNone(old_renew)
        self.assertIsNotNone(replacement)
        self.assertGreater(replacement.fence, old.fence)

    def test_provider_started_operation_survives_original_claim_horizon(self):
        async def exercise():
            store = _AtomicFakeStore()
            first = await store.claim_operation("principal", "live-operation")
            lease = await store.acquire_lease("live-operation", 1, 100, 10)
            started = await store.begin_provider(
                "live-operation", lease, "digest", "model", 100,
            )
            late_claim = await store.claim_operation("principal", "live-operation")
            replacement = await store.acquire_lease("live-operation", 1, 1000, 10)
            second_start = await store.begin_provider(
                "live-operation", replacement, "digest-2", "model", 1000,
            )
            return first, started, late_claim, second_start

        first, started, late_claim, second_start = asyncio.run(exercise())
        self.assertTrue(first.created)
        self.assertTrue(started)
        self.assertEqual(late_claim.state, OperationState.PROVIDER_STARTED)
        self.assertFalse(late_claim.created)
        self.assertFalse(second_start)

    def test_after_apply_transport_fault_is_uncertain_and_not_retried(self):
        client = _AfterApplyFailureClient()
        store = DynamoDBControlStore("control-table", client)
        lease = Lease(0, store._operation("operation"), "owner", 1, 130)

        with _capture_rehearsal_diagnostics() as captured, \
             self.assertRaises(ControlStoreUnavailable):
            asyncio.run(store.begin_provider(
                "operation", lease, "dispatch-digest", "claude-model", 100,
            ))

        transactions = [method for method, _request in client.calls if method == "transact_write_items"]
        self.assertEqual(transactions, ["transact_write_items"])
        self.assertEqual(client.operation_state, OperationState.PROVIDER_STARTED.value)
        self.assertEqual(captured, [("BEGIN_PROVIDER", "UNKNOWN")])

    def test_begin_failure_diagnostics_are_fixed_enums_without_sensitive_values(self):
        EndpointConnectionError = type("EndpointConnectionError", (Exception,), {})
        endpoint_error = EndpointConnectionError("sensitive-message-sentinel")
        cases = (
            (
                "access_denied",
                _SyntheticServiceError("AccessDeniedException"),
                "ACCESS_DENIED",
            ),
            (
                "validation",
                _SyntheticServiceError(
                    "TransactionCanceledException",
                    reasons=["ValidationError", "None"],
                ),
                "VALIDATION",
            ),
            (
                "transaction_conflict",
                _SyntheticServiceError(
                    "TransactionCanceledException",
                    reasons=["TransactionConflict", "None"],
                ),
                "TRANSACTION_CONFLICT",
            ),
            (
                "transaction_cancelled_missing_reasons",
                _SyntheticServiceError("TransactionCanceledException"),
                "TRANSACTION_CANCELLED",
            ),
            (
                "throttled",
                _SyntheticServiceError(
                    "TransactionCanceledException",
                    reasons=["ThrottlingError", "None"],
                ),
                "THROTTLED",
            ),
            (
                "resource_missing",
                _SyntheticServiceError("ResourceNotFoundException"),
                "RESOURCE_NOT_FOUND",
            ),
            ("timeout", TimeoutError("sensitive-message-sentinel"), "TIMEOUT"),
            ("transport", endpoint_error, "TRANSPORT"),
            (
                "internal",
                _SyntheticServiceError("InternalServerError"),
                "INTERNAL",
            ),
            ("unknown", ValueError("sensitive-message-sentinel"), "UNKNOWN"),
        )
        sensitive_values = (
            "sensitive-message-sentinel",
            "sensitive-request-id-sentinel",
            "https://sensitive.example.invalid/control",
            "sensitive-table-sentinel",
            "arn:aws:iam::123456789012:role/sensitive-role-sentinel",
            "sensitive-principal-sentinel",
            "sensitive-operation-sentinel",
            "Message",
            "RequestId",
            "SensitiveFields",
        )

        async def exercise(error):
            store = DynamoDBControlStore(
                "control-table", _BeginFailureClient(error),
            )
            lease = Lease(0, store._operation("operation"), "owner", 1, 130)
            with _capture_rehearsal_diagnostics() as captured:
                try:
                    await store.begin_provider(
                        "operation", lease, "dispatch", "model", 100,
                    )
                except ControlStoreUnavailable as exc:
                    return list(captured), str(exc)
            self.fail("begin_provider should fail closed")

        with mock.patch("builtins.print") as print_call, \
             mock.patch("logging.Logger._log") as log_call:
            for name, error, expected_reason in cases:
                with self.subTest(name=name):
                    captured, public_message = asyncio.run(exercise(error))
                    self.assertEqual(
                        captured, [("BEGIN_PROVIDER", expected_reason)],
                    )
                    self.assertEqual(public_message, "control store unavailable")
                    serialized = repr((captured, public_message))
                    for sensitive in sensitive_values:
                        self.assertNotIn(sensitive, serialized)
        print_call.assert_not_called()
        log_call.assert_not_called()

    def test_diagnostic_capture_is_isolated_between_concurrent_tasks(self):
        async def exercise(error):
            store = DynamoDBControlStore(
                "control-table", _BeginFailureClient(error),
            )
            lease = Lease(0, store._operation("operation"), "owner", 1, 130)
            with _capture_rehearsal_diagnostics() as captured:
                try:
                    await store.begin_provider(
                        "operation", lease, "dispatch", "model", 100,
                    )
                except ControlStoreUnavailable:
                    await asyncio.sleep(0)
                    return list(captured)
            self.fail("begin_provider should fail closed")

        async def concurrent():
            return await asyncio.gather(
                exercise(_SyntheticServiceError("AccessDeniedException")),
                exercise(_SyntheticServiceError("ValidationException")),
            )

        access, validation = asyncio.run(concurrent())
        self.assertEqual(access, [("BEGIN_PROVIDER", "ACCESS_DENIED")])
        self.assertEqual(validation, [("BEGIN_PROVIDER", "VALIDATION")])

    def test_transaction_cancellation_is_conditional_only_for_pure_condition_failures(self):
        lease = Lease(0, "operation-hash", "owner", 1, 130)

        conditional = DynamoDBControlStore(
            "control-table",
            _TransactionFailureClient(["None", "ConditionalCheckFailed"]),
        )
        with _capture_rehearsal_diagnostics() as conditional_diagnostics:
            self.assertFalse(asyncio.run(conditional.begin_provider(
                "operation", lease, "dispatch", "model", 100,
            )))
        self.assertEqual(conditional_diagnostics, [])

        unavailable = DynamoDBControlStore(
            "control-table",
            _TransactionFailureClient(["TransactionConflict", "None"]),
        )
        with self.assertRaises(ControlStoreUnavailable):
            asyncio.run(unavailable.begin_provider(
                "operation", lease, "dispatch", "model", 100,
            ))

        missing_reasons = DynamoDBControlStore(
            "control-table", _TransactionFailureClient([]),
        )
        with self.assertRaises(ControlStoreUnavailable):
            asyncio.run(missing_reasons.begin_provider(
                "operation", lease, "dispatch", "model", 100,
            ))

    def test_cancelled_store_call_preserves_task_cancellation(self):
        class CancelClient(_RecordingClient):
            def describe_table(self, **kwargs):
                self._record("describe_table", kwargs)
                raise asyncio.CancelledError()

        with _capture_rehearsal_diagnostics() as captured, \
             self.assertRaises(asyncio.CancelledError):
            asyncio.run(DynamoDBControlStore("control-table", CancelClient()).health())
        self.assertEqual(captured, [])

    def test_sdk_hang_and_credential_failures_map_to_store_unavailable(self):
        class HangClient(_RecordingClient):
            def describe_table(self, **kwargs):
                self._record("describe_table", kwargs)
                time.sleep(0.03)
                return {"Table": {"TableStatus": "ACTIVE"}}

        hanging = DynamoDBControlStore(
            "control-table", HangClient(), call_timeout_seconds=0.005,
        )
        with _capture_rehearsal_diagnostics() as captured, \
             self.assertRaises(ControlStoreUnavailable):
            asyncio.run(hanging.health())
        self.assertEqual(captured, [("HEALTH", "TIMEOUT")])

        class CredentialClient(_RecordingClient):
            def __init__(self, error):
                super().__init__()
                self.error = error

            def describe_table(self, **kwargs):
                self._record("describe_table", kwargs)
                raise self.error

        class NoCredentialsError(Exception):
            pass

        expired = RuntimeError("expired")
        expired.response = {"Error": {"Code": "ExpiredToken"}}
        for error in (NoCredentialsError(), expired):
            with self.subTest(error=error.__class__.__name__), self.assertRaises(
                ControlStoreUnavailable
            ):
                asyncio.run(DynamoDBControlStore(
                    "control-table", CredentialClient(error),
                ).health())

    def test_from_env_requires_web_identity_and_disables_sdk_retries(self):
        config_calls = []
        client_calls = []

        class FakeConfig:
            def __init__(self, **kwargs):
                config_calls.append(kwargs)

        class FakeSession:
            credential_method = "assume-role-with-web-identity"

            def get_credentials(self):
                return SimpleNamespace(method=self.credential_method)

            def client(self, service, **kwargs):
                client_calls.append((service, kwargs))
                return _RecordingClient()

        boto3_module = types.ModuleType("boto3")
        boto3_module.Session = FakeSession
        botocore_module = types.ModuleType("botocore")
        config_module = types.ModuleType("botocore.config")
        config_module.Config = FakeConfig
        valid_env = {
            "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE": "control-table",
            "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "ap-southeast-1",
            "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/render",
            "AWS_WEB_IDENTITY_TOKEN_FILE": "/injected/not-read-by-test",
            "AWS_EC2_METADATA_DISABLED": "true",
        }
        modules = {
            "boto3": boto3_module,
            "botocore": botocore_module,
            "botocore.config": config_module,
        }
        with mock.patch.dict(os.environ, valid_env, clear=True), \
             mock.patch.dict(sys.modules, modules):
            store = DynamoDBControlStore.from_env()
        self.assertEqual(store.credential_method, "assume-role-with-web-identity")
        self.assertEqual(client_calls[0][0], "dynamodb")
        self.assertEqual(client_calls[0][1]["region_name"], "ap-southeast-1")
        self.assertEqual(
            config_calls[0]["retries"],
            {"mode": "standard", "total_max_attempts": 1},
        )
        self.assertLessEqual(config_calls[0]["connect_timeout"], 2.0)
        self.assertLessEqual(config_calls[0]["read_timeout"], 3.0)

        for updates in (
            {"AWS_ACCESS_KEY_ID": "static"},
            {"AWS_SECRET_ACCESS_KEY": "static"},
            {"AWS_SESSION_TOKEN": "static"},
            {"AWS_EC2_METADATA_DISABLED": "false"},
            {"AWS_ROLE_ARN": ""},
            {"AWS_WEB_IDENTITY_TOKEN_FILE": ""},
        ):
            with self.subTest(updates=updates), \
                 mock.patch.dict(os.environ, {**valid_env, **updates}, clear=True), \
                 mock.patch.dict(sys.modules, modules), \
                 self.assertRaises(ValueError):
                DynamoDBControlStore.from_env()

        FakeSession.credential_method = "env"
        with mock.patch.dict(os.environ, valid_env, clear=True), \
             mock.patch.dict(sys.modules, modules), self.assertRaises(ValueError):
            DynamoDBControlStore.from_env()


if __name__ == "__main__":
    unittest.main()
