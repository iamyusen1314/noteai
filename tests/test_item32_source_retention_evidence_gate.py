"""Synthetic future acceptance cannot erase the consumed V1 full cycle."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from tests import test_item32_network_repair_evidence_gate as prior

gate, ROOT = prior.gate, prior.ROOT


class SourceRetentionEvidenceTests(unittest.TestCase):
    def setUp(self):
        base = prior.NetworkRepairEvidenceTests(); base.setUp()
        self.addCleanup(base.doCleanups); self.f = f = base.f
        history = {key: copy.deepcopy(f.payload["successor"][key]) for key in (
            "previous_successor", "previous_v5_successor", "previous_v5_initialization_hold", "network_repair_preflight")}
        def shift(value):
            if isinstance(value, dict): return {k: shift(v) for k, v in value.items()}
            if isinstance(value, list): return [shift(v) for v in value]
            if isinstance(value, str) and value.startswith(("2026-09-17T", "2026-09-18T")):
                return (datetime.fromisoformat(value).astimezone(timezone.utc) + timedelta(hours=18, minutes=30)).isoformat()
            return "2026-09-18" if value == "2026-09-17" else value
        f.payload, f.attempt_payload, f.proof_payload = map(shift, (f.payload, f.attempt_payload, f.proof_payload))
        f.payload["successor"].update(history)
        snapshot = f.root / f.snapshot_ref
        snapshot.write_text(json.dumps(shift(json.loads(snapshot.read_text())), ensure_ascii=False))
        f.payload["quality"].update(snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(), snapshot_size=len(snapshot.read_bytes()))
        f.rewrite_bound_artifact(f.payload["production_database"]["proof_ref"], f.proof_payload, f.payload["production_database"])
        target = f.root / gate.ITEM32_V5_NETWORK_FINAL_REF
        target.write_bytes((ROOT / gate.ITEM32_V5_NETWORK_FINAL_REF).read_bytes())
        f.plan["previous_v5_full_cycle_hold"] = gate._item32_source_retention_previous_binding(root=f.root)
        f.plan["runtime_overlay_sha256"] = {n: hashlib.sha256((f.root / n).read_bytes()).hexdigest()
                                            for n in gate.ITEM32_V5_SOURCE_RETENTION_OVERLAYS}
        f.plan["source_sha256"] = {**f.plan["image_source_sha256"], **f.plan["runtime_overlay_sha256"]}
        f.plan["admission"].update(work_root=gate.ITEM32_V5_SOURCE_RETENTION_WORK_ROOT,
            not_before_utc="2026-09-18T11:30:00+00:00", bucket_date_utc="2026-09-18",
            dispatch_deadline_utc="2026-09-18T12:25:00+00:00", must_finish_before_utc="2026-09-18T13:00:00+00:00")
        f.plan_target = f.root / gate.ITEM32_V5_SOURCE_RETENTION_EXECUTION_PLAN
        f.payload["successor"].update(predecessor_provider_call_count=48,
            work_root_identity_sha256=hashlib.sha256(("noteai-item32:successor-work-root:" + gate.ITEM32_V5_SOURCE_RETENTION_WORK_ROOT).encode()).hexdigest(),
            previous_v5_full_cycle_hold={**copy.deepcopy(f.plan["previous_v5_full_cycle_hold"]),
                "host_final_readback_verified": True, "database_readonly_probes_verified": True, "collection_ledger_verified": True})
        f.payload["successor"]["runtime_readback"]["runtime_overlay_sha256"] = dict(f.plan["runtime_overlay_sha256"])
        f.payload["execution"]["source_sha256"] = dict(f.plan["source_sha256"])
        self.rebind()

    def rebind(self, *, status="AUTHORIZED", at="2026-09-18T11:11:25+00:00"):
        f = self.f
        f.plan["authorization"] = {"status": status, "confirmed_at_utc": at if status == "AUTHORIZED" else None,
            "approved_scope_sha256": f.approval_digest(f.plan) if status == "AUTHORIZED" else None}
        f.plan_target.write_text(json.dumps(f.plan))
        f.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(f.plan_target.read_bytes()).hexdigest()

    def validate(self):
        f = self.f
        f.rewrite_bound_artifact(f.attempt_ref, f.attempt_payload, f.payload["execution"])
        f.path.write_text(json.dumps(f.payload))
        return gate.validate_item32_trends_evidence(f.control, root=f.root, now=datetime(2026, 9, 18, 13, 30, tzinfo=timezone.utc))

    def test_future_full_contract_accepts_only_with_eight_sources_and_prior_thirty_four(self):
        self.assertEqual(self.validate(), [])
        self.assertEqual(self.f.payload["successor"]["predecessor_provider_call_count"], 48)
        self.assertEqual(self.f.plan["previous_v5_initialization_hold"]["initialization_outcome_unknown_count"], 1)

    def test_pending_or_pre_failure_approval_cannot_credit_synthetic_success(self):
        self.rebind(status="PENDING")
        self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())
        self.rebind(at="2026-09-17T16:21:02.077195+00:00")
        self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_same_day_or_old_count_cannot_be_relabelled_fresh(self):
        self.f.plan["admission"].update(not_before_utc="2026-09-17T17:00:00+00:00", bucket_date_utc="2026-09-17",
            dispatch_deadline_utc="2026-09-17T17:55:00+00:00", must_finish_before_utc="2026-09-17T18:30:00+00:00")
        self.rebind(); self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())
        self.f.payload["successor"]["predecessor_provider_call_count"] = 14
        self.assertIn("Item32 successor predecessor binding mismatch", self.validate())

    def test_expired_window_cannot_be_reapproved_as_current_success(self):
        self.f.plan["admission"].update(not_before_utc="2026-09-18T00:00:00+00:00",
            dispatch_deadline_utc="2026-09-18T00:55:00+00:00", must_finish_before_utc="2026-09-18T01:30:00+00:00")
        self.rebind(at="2026-09-17T16:22:00+00:00")
        self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_prior_full_cycle_counts_and_each_record_are_not_replaceable(self):
        original = copy.deepcopy(self.f.plan["previous_v5_full_cycle_hold"])
        for key, value in (("collection_admissions", 0), ("initialization_count", 0), ("physical_http_count", 34),
                           ("outcome_unknown_count", False), ("no_replay", 1)):
            self.f.plan["previous_v5_full_cycle_hold"] = {**copy.deepcopy(original), key: value}; self.rebind()
            self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())
        self.f.plan["previous_v5_full_cycle_hold"] = copy.deepcopy(original)
        self.f.plan["previous_v5_full_cycle_hold"]["files"].pop(next(iter(original["files"])))
        self.rebind(); self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_missing_host_ledger_verification_or_actual_seal_is_rejected(self):
        self.f.payload["successor"]["previous_v5_full_cycle_hold"]["collection_ledger_verified"] = False
        self.assertIn("Item32 prior full-cycle HOLD closure mismatch", self.validate())
        (self.f.root / gate.ITEM32_V5_NETWORK_FINAL_REF).unlink()
        self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_missing_repair_overlay_and_using_eight_on_old_profile_both_fail(self):
        original = copy.deepcopy(self.f.plan)
        for name in ("model/trends_contract.py", "model/market_timing_worker.py"):
            self.f.plan = copy.deepcopy(original); self.f.plan["runtime_overlay_sha256"].pop(name); self.rebind()
            self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())
        old = copy.deepcopy(original); old["admission"]["work_root"] = gate.ITEM32_V5_NETWORK_WORK_ROOT
        self.assertFalse(gate._item32_v5_profile_valid(old, root=self.f.root))

    def test_thirty_six_responses_without_snapshot_quality_do_not_pass(self):
        self.f.payload["quality"]["keyword_count"] = 0
        self.assertTrue(self.validate())
        self.f.payload["status"] = "HOLD"; self.f.payload["readiness_credit"] = False
        self.assertIn("Item32 terminal status mismatch", self.validate())


if __name__ == "__main__": unittest.main()
