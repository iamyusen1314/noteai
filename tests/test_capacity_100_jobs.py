import importlib.util
from datetime import timedelta
from pathlib import Path
import sys
import threading
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy" / "production" / "capacity_100_jobs.py"
SPEC = importlib.util.spec_from_file_location("capacity_100_jobs", SOURCE)
capacity = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = capacity
SPEC.loader.exec_module(capacity)


PLAN_NONCE = "9a494159-0673-4fc4-8a12-63689ca95565"
ITEM28 = dict(capacity.ITEM28_DEPENDENCY)


class FakeRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.operations = {}
        self.claim_calls = []
        self.cleanup_calls = []
        self.active_admissions = 0
        self.maximum_active_admissions = 0
        self.admission_hold = threading.Barrier(100, timeout=30)

    def preflight(self):
        return {
            "database_idle_connection_headroom": 120,
            "api_c_memory_headroom_bytes": 1_073_741_824,
            "api_c_pid_headroom": 160,
        }

    def admit_exact(self, index, request_id, provider):
        with self.lock:
            self.active_admissions += 1
            self.maximum_active_admissions = max(
                self.maximum_active_admissions,
                self.active_admissions,
            )
        self.admission_hold.wait()
        operation_id = str(uuid.uuid5(uuid.UUID(request_id), "operation"))
        with self.lock:
            self.operations[operation_id] = {
                "index": index,
                "provider": provider,
                "delivered": False,
                "status": "queued",
                "fence": 0,
                "lease": None,
                "claims": 0,
                "takeovers": 0,
                "attempt_id": None,
                "attempt_number": 0,
                "cleaned": False,
            }
            self.active_admissions -= 1
        return {"operation_id": operation_id, "state": "admitted"}

    def deliver_exact(self, operation_id):
        with self.lock:
            row = self.operations[operation_id]
            if row["delivered"]:
                return False
            row["delivered"] = True
            return True

    def claim_exact(self, operation_id, *, owner, lease_seconds, now):
        with self.lock:
            row = self.operations[operation_id]
            prior = row["lease"]
            if not row["delivered"] or row["status"] == "succeeded":
                return None
            if prior is not None and prior.expires_at > now.isoformat():
                return None
            takeover = prior is not None
            row["fence"] += 1
            row["claims"] += 1
            row["takeovers"] += int(takeover)
            row["status"] = "running"
            lease = capacity.ExactLease(
                operation_id,
                owner,
                row["fence"],
                (now + timedelta(seconds=lease_seconds)).isoformat(),
            )
            row["lease"] = lease
            self.claim_calls.append((operation_id, owner))
            return lease

    def begin_provider_exact(
        self,
        lease,
        *,
        provider,
        request_hash,
        model_hash,
        now,
    ):
        with self.lock:
            row = self.operations[lease.operation_id]
            if row["lease"] != lease or row["attempt_id"] is not None:
                return None
            self.assert_digest(request_hash)
            self.assert_digest(model_hash)
            if row["provider"] != provider:
                return {}
            row["attempt_number"] += 1
            attempt_id = str(
                uuid.uuid5(uuid.UUID(lease.operation_id), "provider-attempt-1")
            )
            row["attempt_id"] = attempt_id
            return {
                "attempt_id": attempt_id,
                "attempt_number": row["attempt_number"],
            }

    @staticmethod
    def assert_digest(value):
        if len(value) != 64 or set(value) - set("0123456789abcdef"):
            raise AssertionError("digest")

    def complete_success_exact(
        self,
        lease,
        attempt_id,
        *,
        response_hash,
        now,
    ):
        with self.lock:
            row = self.operations[lease.operation_id]
            self.assert_digest(response_hash)
            if row["lease"] != lease or row["attempt_id"] != attempt_id:
                return False
            row["status"] = "succeeded"
            return True

    def cleanup_exact(self, operation_id):
        with self.lock:
            row = self.operations[operation_id]
            if row["status"] != "succeeded" or row["cleaned"]:
                return {"status": "invalid"}
            row["cleaned"] = True
            self.cleanup_calls.append(operation_id)
        return {
            "status": "primary_deleted",
            "request_object_residue_count": 0,
            "result_object_residue_count": 0,
        }

    def project_exact(self, operation_ids):
        with self.lock:
            rows = [self.operations[value] for value in operation_ids]
        return {
            "maximum_concurrent_admission_count": self.maximum_active_admissions,
            "unique_operation_count": len(set(operation_ids)),
            "outbox_count": len(rows),
            "delivered_count": sum(row["delivered"] for row in rows),
            "succeeded_count": sum(row["status"] == "succeeded" for row in rows),
            "lost_operation_count": sum(row["status"] != "succeeded" for row in rows),
            "claim_count": sum(row["claims"] for row in rows),
            "takeover_count": sum(row["takeovers"] for row in rows),
            "provider_attempt_count": sum(row["attempt_id"] is not None for row in rows),
            "provider_attempt_number_not_one_count": sum(
                row["attempt_number"] != 1 for row in rows
            ),
            "worker_c_completed_count": sum(row["index"] < 50 for row in rows),
            "worker_f_completed_count": sum(row["index"] >= 50 for row in rows),
            "worker_c_takeover_index": 0,
            "worker_f_takeover_index": 50,
            "settlement_completed_count": 100,
            "settlement_refunded_count": 0,
            "settlement_needs_manual_count": 0,
            "charge_applied_count": 100,
            "complete_applied_count": 100,
            "usage_record_count": 100,
            "expected_credits_milli": 600_000,
            "actual_credits_milli": 600_000,
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


class FakeAdmissionDB:
    def __init__(self):
        self.lock = threading.RLock()
        self.users = {}

    def fetchone(self, sql, params):
        with self.lock:
            if "COUNT(*) AS c" in sql:
                return {"c": len(self.users)}
            username = params[0]
            row = self.users.get(username)
            return dict(row) if row else None


class FakeAdmissionAuth:
    def __init__(self, database):
        self.database = database

    def create_user(self, username, _password):
        with self.database.lock:
            if username in self.database.users:
                raise ValueError("duplicate")
            row = {
                "id": str(uuid.uuid5(uuid.UUID(PLAN_NONCE), username)),
                "username": username,
                "email": None,
                "phone": None,
                "deletion_requested_at": None,
            }
            self.database.users[username] = row
            return dict(row)


class FakeAdmissionDurable:
    def __init__(self):
        self.lock = threading.RLock()
        self.operations = {}

    @staticmethod
    def operation_id_for(user_id, _operation, request_id):
        return str(uuid.uuid5(uuid.UUID(request_id), user_id))

    def admit_job(self, *, user_id, operation, request_id, payload):
        self.assert_payload(operation, payload)
        operation_id = self.operation_id_for(user_id, operation, request_id)
        with self.lock:
            state = "existing" if operation_id in self.operations else "admitted"
            self.operations[operation_id] = dict(payload)
        return {
            "state": state,
            "operation_id": operation_id,
            "status": "queued",
            "billing_state": "charged",
        }

    @staticmethod
    def assert_payload(operation, payload):
        if operation != "analyze" or payload.get("item29_index") not in range(100):
            raise AssertionError("payload")


class FakeAdmissionStorage:
    @staticmethod
    def configure_from_environment():
        return True


class Capacity100JobsTests(unittest.TestCase):
    def test_cleanup_retry_reuses_exact_fenced_deletion_request(self):
        user_id = str(uuid.uuid5(uuid.UUID(PLAN_NONCE), "cleanup-user"))
        request_id = str(uuid.uuid5(uuid.UUID(PLAN_NONCE), "item29-delete:000"))
        subject = "deleted:" + capacity.hashlib.sha256(
            user_id.encode("utf-8")
        ).hexdigest()[:32]

        class Transaction:
            postgres = True

            def fetchone(self, sql, params):
                self.sql = sql
                self.params = params
                return {
                    "id": request_id,
                    "user_id": user_id,
                    "subject_ref": subject,
                    "status": "requested",
                    "contract_version": "first-launch-test",
                }

        class Retention:
            CONTRACT_VERSION = "first-launch-test"
            create_called = False

            @staticmethod
            def lock_user_write_fence_with_storage(
                _tx, value, *, allow_deletion_requested
            ):
                if value != user_id or allow_deletion_requested is not True:
                    raise AssertionError("fence")
                return {"id": user_id, "deletion_requested_at": "set"}

            @classmethod
            def request_account_deletion_with_storage(cls, *_args, **_kwargs):
                cls.create_called = True
                raise AssertionError("must reuse")

        tx = Transaction()
        result = capacity._cleanup_deletion_request(
            retention=Retention,
            tx=tx,
            user_id=user_id,
            request_id=request_id,
            now=capacity.datetime.now(capacity.timezone.utc),
        )
        self.assertEqual(result["id"], request_id)
        self.assertIn("FOR UPDATE", tx.sql)
        self.assertEqual(tx.params, (request_id,))
        self.assertIs(Retention.create_called, False)

    def test_production_admission_retry_reuses_users_and_operations(self):
        database = FakeAdmissionDB()
        durable = FakeAdmissionDurable()
        context = {
            "auth": FakeAdmissionAuth(database),
            "db": database,
            "durable_ai": durable,
            "storage": FakeAdmissionStorage(),
        }
        first = capacity._phase_admit(context, PLAN_NONCE)
        second = capacity._phase_admit(context, PLAN_NONCE)

        self.assertEqual(first["new_user_count"], 100)
        self.assertEqual(first["new_admission_count"], 100)
        self.assertEqual(second["existing_user_count"], 100)
        self.assertEqual(second["existing_admission_count"], 100)
        self.assertEqual(first["operation_ids"], second["operation_ids"])
        self.assertEqual(len(database.users), 100)
        self.assertEqual(len(durable.operations), 100)

    def test_namespace_pattern_and_cleanup_order_are_fail_closed(self):
        pattern = capacity._prefix_like(PLAN_NONCE)
        self.assertIn("!_", pattern)
        self.assertNotIn("item29_", pattern)
        source = SOURCE.read_text(encoding="utf-8")
        fence = source.index("retention.request_account_deletion_with_storage")
        orphan_scan = source.index("for key, expected in object_targets.items()")
        primary_delete = source.index("retention.process_due_account_deletions")
        self.assertLess(fence, orphan_scan)
        self.assertLess(orphan_scan, primary_delete)

    def test_exact_100_concurrent_two_takeovers_provider_and_cleanup(self):
        runtime = FakeRuntime()
        result = capacity.run_rehearsal(
            runtime,
            plan_nonce=PLAN_NONCE,
            item28_dependency=ITEM28,
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(runtime.maximum_active_admissions, 100)
        self.assertEqual(len(runtime.claim_calls), 102)
        self.assertEqual(len(runtime.cleanup_calls), 100)
        self.assertEqual(result["provider"]["fake_call_count"], 100)
        self.assertEqual(result["provider"]["duplicate_fake_call_count"], 0)
        self.assertEqual(result["runtime_projection"]["actual_credits_milli"], 600_000)
        self.assertEqual(result["runtime_projection"]["takeover_count"], 2)
        self.assertEqual(
            result["routing_and_recovery"]["global_recovery_call_count"], 0
        )

    def test_dependency_is_versioned_and_hash_drift_fails_closed(self):
        dependency = dict(ITEM28)
        dependency["evidence_sha256"] = "0" * 64
        with self.assertRaisesRegex(capacity.CapacityError, "item28_dependency_binding"):
            capacity.run_rehearsal(
                FakeRuntime(),
                plan_nonce=PLAN_NONCE,
                item28_dependency=dependency,
            )

    def test_headroom_gate_stops_before_admission(self):
        runtime = FakeRuntime()
        runtime.preflight = lambda: {
            "database_idle_connection_headroom": 119,
            "api_c_memory_headroom_bytes": 1_073_741_824,
            "api_c_pid_headroom": 160,
        }
        with self.assertRaisesRegex(capacity.CapacityError, "headroom_insufficient"):
            capacity.run_rehearsal(
                runtime,
                plan_nonce=PLAN_NONCE,
                item28_dependency=ITEM28,
            )
        self.assertEqual(runtime.operations, {})

    def test_source_has_no_global_claim_or_recovery_or_real_provider_client(self):
        source = SOURCE.read_text(encoding="utf-8")
        forbidden = (
            "recover_" + "unstarted_leases",
            "claim_" + "next_delivered_operation",
            "anthropic" + ".",
            "moonshot" + ".",
        )
        for value in forbidden:
            self.assertNotIn(value, source)
        self.assertNotIn("Client" + "Token", source)

    def test_production_assembly_binds_every_measured_phase(self):
        runtime = FakeRuntime()
        expected = capacity.run_rehearsal(
            runtime,
            plan_nonce=PLAN_NONCE,
            item28_dependency=ITEM28,
        )
        operation_set = expected["admission"]["operation_set_sha256"]
        base = {
            "schema": capacity.PHASE_SCHEMA,
            "task_id": capacity.TASK_ID,
            "plan_nonce": PLAN_NONCE,
            "status": "PASS",
        }
        cleanup_keys = {
            "ready_request_object_residue_count",
            "ready_result_object_residue_count",
            "primary_user_residue_count",
            "admission_residue_count",
            "idempotency_residue_count",
            "pseudonymous_operation_audit_count",
            "pseudonymous_provider_attempt_audit_count",
            "pseudonymous_usage_audit_count",
        }
        def process_projection(worker):
            is_c = worker == "Worker-C"
            return {
                **base,
                "phase": "process",
                "operation_set_sha256": operation_set,
                "worker": worker,
                "assigned_count": 50,
                "index_start": 0 if is_c else 50,
                "index_end": 49 if is_c else 99,
                "row_count": 50,
                "succeeded_count": 50,
                "safe_unstarted_count": 0,
                "unsafe_terminal_count": 0,
                "fake_call_count": 50,
                "unique_fake_operation_count": 50,
                "duplicate_fake_call_count": 0,
                "provider_attempt_count": 50,
                "provider_terminal_succeeded_count": 50,
                "attempt_number_not_one_count": 0,
                "wrong_provider_label_count": 0,
                "wrong_fence_count": 0,
                "claim_count_mismatch_count": 0,
                "missing_provider_attempt_count": 0,
                "claude_label_count": 50 if is_c else 0,
                "kimi_label_count": 0 if is_c else 50,
                "takeover_index": 0 if is_c else 50,
                "takeover_fence": 2,
                "stale_owner_provider_call_count": 0,
                "real_provider_call_count": 0,
                "safe_unstarted_operation_ids": [],
                "unsafe_operation_ids": [],
            }
        process_c = process_projection("Worker-C")
        process_f = process_projection("Worker-F")
        assembled = capacity.assemble_production_result(
            preflight={
                **base,
                "phase": "preflight",
                "headroom": {
                    "database_idle_connection_headroom": 120,
                    "api_c_memory_headroom_bytes": 1_073_741_824,
                    "api_c_pid_headroom": 160,
                },
            },
            admit={
                **base,
                "phase": "admit",
                "operation_set_sha256": operation_set,
                "barrier_participant_count": 100,
                "maximum_concurrent_admission_count": 100,
                "user_count": 100,
                "new_user_count": 100,
                "existing_user_count": 0,
                "new_admission_count": 100,
                "existing_admission_count": 0,
                "unique_operation_count": 100,
            },
            dispatch_readback={
                **base,
                "phase": "dispatch-readback",
                "operation_set_sha256": operation_set,
                "outbox_row_count": 100,
                "delivered_count": 100,
                "non_delivered_operation_ids": [],
            },
            preclaim_c={
                **base,
                "phase": "preclaim",
                "operation_set_sha256": operation_set,
                "worker": "Worker-C",
                "preinterrupt_index": 50,
                "fence": 1,
            },
            preclaim_f={
                **base,
                "phase": "preclaim",
                "operation_set_sha256": operation_set,
                "worker": "Worker-F",
                "preinterrupt_index": 0,
                "fence": 1,
            },
            process_c=process_c,
            process_f=process_f,
            observe={
                **base,
                "phase": "observe",
                "operation_set_sha256": operation_set,
                "runtime_projection": {
                    key: value
                    for key, value in expected["runtime_projection"].items()
                    if key not in cleanup_keys | {
                        "maximum_concurrent_admission_count",
                        "outbox_count", "delivered_count",
                        "provider_attempt_number_not_one_count",
                        "worker_c_completed_count", "worker_f_completed_count",
                        "worker_c_takeover_index", "worker_f_takeover_index",
                    }
                },
            },
            cleanup={
                **base,
                "phase": "cleanup",
                "operation_set_sha256": operation_set,
                "primary_deleted_count": 100,
                "deleted_payload_object_count": 200,
                "orphan_payload_object_deleted_count": 0,
                "cleanup_projection": {
                    key: expected["runtime_projection"][key]
                    for key in cleanup_keys
                },
            },
            item28_dependency=ITEM28,
        )
        self.assertEqual(assembled, expected)

        readback_c = dict(process_c, phase="process-readback")
        self.assertEqual(
            capacity.assemble_production_result(
                preflight={
                    **base,
                    "phase": "preflight",
                    "headroom": {
                        "database_idle_connection_headroom": 120,
                        "api_c_memory_headroom_bytes": 1_073_741_824,
                        "api_c_pid_headroom": 160,
                    },
                },
                admit={
                    **base,
                    "phase": "admit",
                    "operation_set_sha256": operation_set,
                    "barrier_participant_count": 100,
                    "maximum_concurrent_admission_count": 100,
                    "user_count": 100,
                    "new_user_count": 0,
                    "existing_user_count": 100,
                    "new_admission_count": 0,
                    "existing_admission_count": 100,
                    "unique_operation_count": 100,
                },
                dispatch_readback={
                    **base,
                    "phase": "dispatch-readback",
                    "operation_set_sha256": operation_set,
                    "outbox_row_count": 100,
                    "delivered_count": 100,
                    "non_delivered_operation_ids": [],
                },
                preclaim_c={
                    **base, "phase": "preclaim",
                    "operation_set_sha256": operation_set,
                    "worker": "Worker-C", "preinterrupt_index": 50, "fence": 1,
                },
                preclaim_f={
                    **base, "phase": "preclaim",
                    "operation_set_sha256": operation_set,
                    "worker": "Worker-F", "preinterrupt_index": 0, "fence": 1,
                },
                process_c=readback_c,
                process_f=process_f,
                observe={
                    **base, "phase": "observe",
                    "operation_set_sha256": operation_set,
                    "runtime_projection": {
                        key: value
                        for key, value in expected["runtime_projection"].items()
                        if key not in cleanup_keys | {
                            "maximum_concurrent_admission_count", "outbox_count",
                            "delivered_count", "provider_attempt_number_not_one_count",
                            "worker_c_completed_count", "worker_f_completed_count",
                            "worker_c_takeover_index", "worker_f_takeover_index",
                        }
                    },
                },
                cleanup={
                    **base, "phase": "cleanup",
                    "operation_set_sha256": operation_set,
                    "primary_deleted_count": 100,
                    "deleted_payload_object_count": 200,
                    "orphan_payload_object_deleted_count": 0,
                    "cleanup_projection": {
                        key: expected["runtime_projection"][key]
                        for key in cleanup_keys
                    },
                },
                item28_dependency=ITEM28,
            ),
            expected,
        )

        wrong_provider = dict(process_c, wrong_provider_label_count=1)
        with self.assertRaisesRegex(capacity.CapacityError, "phase_terminal_binding"):
            capacity._require_terminal_process_projection(
                wrong_provider, "Worker-C"
            )


if __name__ == "__main__":
    unittest.main()
