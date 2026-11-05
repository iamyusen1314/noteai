"""Real queue only: 100 accepted reports' four concurrent diagnostic experts.

This verifies local fanout accommodation/fairness, never supplier throughput,
400 physical requests, report completion, financial settlement or production.
"""
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import model_admission as admission


class CapacityFanoutAdmissionTests(unittest.TestCase):
    def test_one_hundred_admitted_reports_four_experts_queue_without_late_rejection(self):
        # api.py diagnosis task_specs runs four experts concurrently; arbitration
        # follows their completion. Do not substitute a 100 independent-call load.
        fanout, users, remote = 4, 100, 64
        with mock.patch.dict(os.environ, {
                "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
                "NOTEAI_MODEL_REMOTE_CONCURRENCY": str(remote),
                "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": ""}, clear=True):
            manager = admission.Admission()
            operations, tickets = [], []
            try:
                for index in range(users):
                    operation, owns = manager.register("fanout-user-%03d" % index,
                        "original-report-%03d" % index, route="/analyze/stream")
                    self.assertTrue(owns)
                    operations.append(operation)
                    if index == 0:
                        duplicate, owns = manager.register(operation.user_id,
                            operation.request_hash, route="/analyze/stream")
                        self.assertIs(duplicate, operation); self.assertFalse(owns)
                        with self.assertRaisesRegex(admission.AdmissionError, "MODEL_USER_OPERATION_BUSY"):
                            manager.register(operation.user_id, "different-report", route="/analyze/stream")
                self.assertEqual(len(manager.operations), users)
                with self.assertRaisesRegex(admission.AdmissionError, "MODEL_OPERATIONS_BUSY"):
                    manager.register("fanout-user-overflow", "overflow", route="/analyze/stream")
                rejected = []
                for user_index, operation in enumerate(operations):
                    for expert in range(fanout):
                        call_id = "fanout-%03d-expert-%d" % (user_index, expert)
                        try:
                            tickets.append(manager.calls.enqueue(operation, call_id, "doubao",
                                model_id="doubao-seed-2-0-lite-260428"))
                        except admission.AdmissionError as exc:
                            rejected.append((call_id, str(exc)))
                self.assertEqual((len(tickets), len(rejected)), (users * fanout, 0),
                    "Already registered reports lost expert admission; first rejection: %r" % rejected[:1])
                self.assertEqual(len({t.call_id for t in tickets}), users * fanout)
                self.assertEqual(len(manager.calls.active), remote)
                self.assertEqual(len(manager.calls._tickets()), users * fanout - remote)
                self.assertTrue(all(op.outstanding == fanout for op in operations))
                self.assertEqual(len(manager.operations), users)
                initial = list(manager.calls.active.values())
                initially_served = {t.operation.user_id for t in initial}
                not_yet_served = {op.user_id for op in operations} - initially_served
                later_grants, completed = [], []
                # Leaving an accepted request marks it exiting; its original
                # operation is retained until every outstanding expert releases.
                for operation in operations:
                    manager.finish(operation)
                self.assertEqual(len(manager.operations), users)
                while manager.calls.active:
                    self.assertLessEqual(len(manager.calls.active), remote)
                    before = set(manager.calls.active)
                    ticket = next(iter(manager.calls.active.values()))
                    ticket.progress = True
                    manager.calls.release(ticket)
                    completed.append(ticket.call_id)
                    later_grants.extend(manager.calls.active[key].operation.user_id
                        for key in set(manager.calls.active) - before)
                # Original per-user RR gives every waiting user a first turn
                # before any of those waiting users receives its second turn.
                self.assertEqual(set(later_grants[:len(not_yet_served)]), not_yet_served)
                self.assertEqual(len(set(later_grants[:len(not_yet_served)])), len(not_yet_served))
                self.assertEqual(len(set(completed)), users * fanout)
                self.assertTrue(all(op.outstanding == 0 and op.completed_calls == fanout for op in operations))
                self.assertEqual(manager.calls.active, {})
                self.assertEqual(manager.calls.waiting, {})
                self.assertEqual(manager.calls.deferred, {})
                self.assertEqual(manager.operations, {})
                self.assertEqual(manager.aliases, {})
            finally:
                for ticket in tickets:
                    manager.calls.release(ticket)
                for operation in operations:
                    manager.finish(operation)
                manager.close_remote_workers()
            os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "0"
            legacy = admission.Admission()
            self.assertEqual((legacy.calls.capacity, legacy.limits.operations,
                legacy.limits.pending_calls), (2, 10, 64))
            os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "1"
            os.environ["NOTEAI_MODEL_PENDING_CALLS"] = "4096"
            self.assertEqual(admission.Limits.environment().pending_calls, 4096)


if __name__ == "__main__":
    unittest.main()
