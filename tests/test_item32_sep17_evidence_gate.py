"""Isolated Sep17 continuation evidence, never a production result or dispatch."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from tests import test_item32_v5_evidence_gate as v5

gate, ROOT = v5.gate, v5.ROOT


class Item32Sep17EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        base = v5.Item32V5EvidenceGateTests()
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.f = f = base.f

        def next_window(value):
            if isinstance(value, dict):
                return {key: next_window(item) for key, item in value.items()}
            if isinstance(value, list):
                return [next_window(item) for item in value]
            if isinstance(value, str) and value.startswith("2026-09-16T"):
                return (datetime.fromisoformat(value) + timedelta(days=1, hours=-2, minutes=-40)).isoformat()
            return "2026-09-17" if value == "2026-09-16" else value

        f.payload, f.attempt_payload, f.proof_payload = map(
            next_window, (f.payload, f.attempt_payload, f.proof_payload))
        snapshot = f.root / f.snapshot_ref
        snapshot.write_text(json.dumps(next_window(json.loads(snapshot.read_text())), ensure_ascii=False))
        f.payload["quality"].update(snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                                    snapshot_size=len(snapshot.read_bytes()))
        f.rewrite_bound_artifact(f.payload["production_database"]["proof_ref"], f.proof_payload,
                                 f.payload["production_database"])
        template = json.loads((ROOT / gate.ITEM32_V5_SEP17_EXECUTION_PLAN).read_bytes())
        f.plan["admission"] = copy.deepcopy(template["admission"])
        f.plan["previous_v5_successor"] = copy.deepcopy(template["previous_v5_successor"])
        self.seal = f.root / gate.ITEM32_V5_SEP16_FINAL_REF
        self.seal.write_bytes((ROOT / gate.ITEM32_V5_SEP16_FINAL_REF).read_bytes())
        f.plan_target = f.root / gate.ITEM32_V5_SEP17_EXECUTION_PLAN
        f.payload["successor"].update(
            predecessor_provider_call_count=14,
            work_root_identity_sha256=hashlib.sha256(
                b"noteai-item32:successor-work-root:/var/lib/noteai/item32-v5-successor-20260917").hexdigest(),
            previous_v5_successor={**copy.deepcopy(f.plan["previous_v5_successor"]),
                "host_final_readback_verified": True, "database_readonly_probes_verified": True})
        self.rebind_plan()

    def rebind_plan(self):
        f = self.f
        f.plan["authorization"] = {"status": "AUTHORIZED",
            "confirmed_at_utc": "2026-09-16T02:17:00.658000+00:00",
            "approved_scope_sha256": f.approval_digest(f.plan)}
        f.plan_target.write_text(json.dumps(f.plan))
        f.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(f.plan_target.read_bytes()).hexdigest()

    def validate(self):
        f = self.f
        f.rewrite_bound_artifact(f.attempt_ref, f.attempt_payload, f.payload["execution"])
        f.path.write_text(json.dumps(f.payload))
        return gate.validate_item32_trends_evidence(f.control, root=f.root,
            now=datetime(2026, 9, 17, 2, tzinfo=timezone.utc))

    def test_accepts_new_bucket_with_exact_original_hold_and_both_readbacks(self):
        self.assertEqual(len(self.f.plan["previous_v5_successor"]["files"]), 9)
        self.assertEqual(self.validate(), [])

    def test_terminal_requires_full_original_previous_binding_and_exact_counters(self):
        original = copy.deepcopy(self.f.payload["successor"]["previous_v5_successor"])
        mutations = {"collection_admissions": 10, "initialization_count": 1, "physical_http_count": 11,
            "outcome_unknown_count": False, "automatic_retry_count": False, "no_replay": 1,
            "status": "VERIFIED", "call_date_utc": "2026-09-17", "work_root": "changed"}
        for key, value in mutations.items():
            with self.subTest(key=key):
                changed = {**copy.deepcopy(original), key: value}
                self.f.payload["successor"]["previous_v5_successor"] = changed
                self.assertIn("Item32 Sep16 v5 HOLD closure mismatch", self.validate())
        self.f.payload["successor"]["previous_v5_successor"] = original
        self.f.payload["successor"]["predecessor_provider_call_count"] = True
        self.assertIn("Item32 successor predecessor binding mismatch", self.validate())

    def test_missing_previous_cannot_fall_back_to_sep16_accepted_profile(self):
        self.f.payload["successor"].pop("previous_v5_successor")
        self.assertTrue(self.validate())

    def test_plan_cannot_rebind_changed_original_hash_mode_count_or_date(self):
        original = copy.deepcopy(self.f.plan["previous_v5_successor"])
        file_name = next(iter(original["files"]))
        cases = []
        for key, value in (("sha256", "0" * 64), ("mode", "0o644"), ("bytes", True)):
            changed = copy.deepcopy(original)
            changed["files"][file_name][key] = value
            cases.append(changed)
        for key, value in (("collection_admissions", True), ("call_date_utc", "2026-09-17")):
            cases.append({**copy.deepcopy(original), key: value})
        changed = copy.deepcopy(original)
        changed["files"].pop(file_name)
        cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed):
                self.f.plan["previous_v5_successor"] = changed
                self.rebind_plan()  # Even a self-consistent altered plan is not the pinned predecessor.
                self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_both_fresh_host_and_original_database_proof_verifications_are_required(self):
        previous = self.f.payload["successor"]["previous_v5_successor"]
        for key in ("host_final_readback_verified", "database_readonly_probes_verified"):
            for value in (False, 1, None):
                with self.subTest(key=key, value=value):
                    previous[key] = value
                    self.assertIn("Item32 Sep16 v5 HOLD closure mismatch", self.validate())
            previous.pop(key)
            self.assertIn("Item32 Sep16 v5 HOLD closure mismatch", self.validate())
            previous[key] = True

    def test_actual_final_seal_must_exist_with_original_bytes(self):
        raw = self.seal.read_bytes()
        self.seal.write_bytes(raw + b"\n")
        self.assertIn("Item32 Sep16 v5 HOLD closure mismatch", self.validate())
        self.seal.unlink()
        self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_authorization_scope_includes_predecessor_and_fixed_window(self):
        scope = self.f.plan["authorization"]["approved_scope_sha256"]
        changed = copy.deepcopy(self.f.plan)
        changed.pop("previous_v5_successor")
        self.assertNotEqual(scope, self.f.approval_digest(changed))
        for key, value in (("not_before_utc", "2026-09-17T00:50:00+00:00"),
                           ("dispatch_deadline_utc", "2026-09-17T01:50:00+00:00"),
                           ("must_finish_before_utc", "2026-09-17T03:00:00+00:00")):
            original = self.f.plan["admission"][key]
            self.f.plan["admission"][key] = value
            self.assertNotEqual(scope, self.f.approval_digest(self.f.plan))
            self.rebind_plan()
            self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())
            self.f.plan["admission"][key] = original
        self.rebind_plan()
        self.f.plan["authorization"]["status"] = "PENDING"
        self.f.plan_target.write_text(json.dumps(self.f.plan))
        self.f.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(self.f.plan_target.read_bytes()).hexdigest()
        self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())


if __name__ == "__main__":
    unittest.main()
