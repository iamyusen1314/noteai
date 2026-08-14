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
ITEM28 = {
    "schema": capacity.DEPENDENCY_SCHEMA,
    "authority_root": "1" * 64,
    "verifier_path": "tools/verify_internal_failure_rollback_evidence.py",
    "verifier_sha256": "2" * 64,
    "evidence_path": (
        "deploy/production/evidence/"
        "production-internal-failure-rollback-verified-20260814.json"
    ),
    "evidence_sha256": "3" * 64,
    "receipt_path": (
        "deploy/production/evidence/"
        "internal-failure-rollback-api-f-provider-receipt-20260814.json"
    ),
    "receipt_sha256": "4" * 64,
    "checkpoint_path": (
        "deploy/production/evidence/"
        "internal-failure-rollback-terminal-checkpoint-20260814.json"
    ),
    "checkpoint_sha256": "5" * 64,
    "terminal_acceptance_sha256": "6" * 64,
}


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


class Capacity100JobsTests(unittest.TestCase):
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

    def test_dependency_is_versioned_and_empty_authority_fails_closed(self):
        dependency = dict(ITEM28)
        dependency["authority_root"] = ""
        with self.assertRaisesRegex(capacity.CapacityError, "item28_dependency_authority"):
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


if __name__ == "__main__":
    unittest.main()
