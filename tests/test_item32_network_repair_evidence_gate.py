"""New scoped continuation retains both sealed holds; synthetic terminal only."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from tests import test_item32_sep17_evidence_gate as prior

gate, ROOT = prior.gate, prior.ROOT


class NetworkRepairEvidenceTests(unittest.TestCase):
    def setUp(self):
        base = prior.Item32Sep17EvidenceGateTests(); base.setUp()
        self.addCleanup(base.doCleanups); self.f = f = base.f
        def shift(value):
            if isinstance(value, dict): return {k: shift(v) for k, v in value.items()}
            if isinstance(value, list): return [shift(v) for v in value]
            if isinstance(value, str) and value.startswith('2026-09-17T'):
                return (datetime.fromisoformat(value) + timedelta(hours=16)).isoformat()
            return value
        f.payload, f.attempt_payload, f.proof_payload = map(shift, (f.payload, f.attempt_payload, f.proof_payload))
        snapshot = f.root / f.snapshot_ref
        snapshot.write_text(json.dumps(shift(json.loads(snapshot.read_text())), ensure_ascii=False))
        f.payload['quality'].update(snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(), snapshot_size=len(snapshot.read_bytes()))
        f.rewrite_bound_artifact(f.payload['production_database']['proof_ref'], f.proof_payload, f.payload['production_database'])
        f.plan['admission'].update(work_root=gate.ITEM32_V5_NETWORK_WORK_ROOT,
            not_before_utc='2026-09-17T17:00:00+00:00', dispatch_deadline_utc='2026-09-17T17:40:00+00:00',
            must_finish_before_utc='2026-09-17T18:00:00+00:00')
        for ref in (gate.ITEM32_V5_SEP17_FINAL_REF, gate.ITEM32_V5_NETWORK_D0_REF,
                    *[f'deploy/production/evidence/production-item32-network-repair-{name}-20260917.json' for name in ('d1', 'd2')]):
            target = f.root / ref; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((ROOT / ref).read_bytes())
        f.plan.update(gate._item32_network_repair_bindings(root=f.root))
        f.plan_target = f.root / gate.ITEM32_V5_NETWORK_EXECUTION_PLAN
        f.payload['successor'].update(
            work_root_identity_sha256=hashlib.sha256(('noteai-item32:successor-work-root:' + gate.ITEM32_V5_NETWORK_WORK_ROOT).encode()).hexdigest(),
            previous_v5_initialization_hold={**copy.deepcopy(f.plan['previous_v5_initialization_hold']),
                'host_final_readback_verified': True, 'database_readonly_probes_verified': True},
            network_repair_preflight={**copy.deepcopy(f.plan['network_repair_preflight']), 'host_readback_verified': True})
        self.rebind()

    def rebind(self):
        f = self.f
        f.plan['authorization'] = {'status': 'AUTHORIZED', 'confirmed_at_utc': '2026-09-17T16:00:00+00:00',
            'approved_scope_sha256': f.approval_digest(f.plan)}
        f.plan_target.write_text(json.dumps(f.plan))
        f.payload['execution']['execution_plan_sha256'] = hashlib.sha256(f.plan_target.read_bytes()).hexdigest()

    def validate(self):
        f = self.f
        f.rewrite_bound_artifact(f.attempt_ref, f.attempt_payload, f.payload['execution'])
        f.path.write_text(json.dumps(f.payload))
        return gate.validate_item32_trends_evidence(f.control, root=f.root, now=datetime(2026, 9, 17, 18, tzinfo=timezone.utc))

    def test_same_day_new_window_can_accept_full_cycle_without_erasing_old_initialization_unknown(self):
        self.assertEqual(self.validate(), [])
        self.assertEqual(self.f.payload['successor']['previous_v5_initialization_hold']['initialization_outcome_unknown_count'], 1)

    def test_old_unknown_is_not_replaced_by_current_success(self):
        binding = self.f.payload['successor']['previous_v5_initialization_hold']
        original = copy.deepcopy(binding)
        for key, value in (('initialization_outcome_unknown_count', 0), ('collection_outcome_unknown_count', 1),
                           ('collection_admissions', 1), ('physical_http_count', 0), ('automatic_retry_count', False),
                           ('host_final_readback_verified', False), ('database_readonly_probes_verified', 1)):
            with self.subTest(key=key):
                self.f.payload['successor']['previous_v5_initialization_hold'] = {**original, key: value}
                self.assertIn('Item32 Sep17 initialization UNKNOWN closure mismatch', self.validate())

    def test_plan_reauthorization_cannot_alter_d0_or_ten_original_bindings(self):
        original = copy.deepcopy(self.f.plan)
        cases = [('network_repair_preflight', 'sha256', 'a' * 64),
                 ('previous_v5_initialization_hold', 'initialization_outcome_unknown_count', 0)]
        for field, key, value in cases:
            self.f.plan = copy.deepcopy(original); self.f.plan[field][key] = value; self.rebind()
            self.assertIn('Item32 canonical execution plan binding mismatch', self.validate())
        self.f.plan = copy.deepcopy(original)
        self.f.plan['previous_v5_initialization_hold']['files'].pop(next(iter(self.f.plan['previous_v5_initialization_hold']['files'])))
        self.rebind(); self.assertIn('Item32 canonical execution plan binding mismatch', self.validate())

    def test_missing_d0_or_missing_old_hold_never_falls_back_to_old_profile(self):
        self.f.payload['successor'].pop('network_repair_preflight')
        self.assertTrue(self.validate())
        (self.f.root / gate.ITEM32_V5_NETWORK_D0_REF).unlink()
        self.assertIn('Item32 canonical execution plan binding mismatch', self.validate())

    def test_current_unknown_or_extra_physical_call_still_fails_original_full_cycle_contract(self):
        self.f.payload['execution']['outcome_unknown_count'] = 1
        self.assertTrue(self.validate())
        self.f.payload['execution']['outcome_unknown_count'] = 0
        self.f.payload['execution']['physical_http']['total_count'] = 37
        self.assertTrue(self.validate())

    def test_success_requires_both_original_diagnostics_and_host_binding_in_terminal(self):
        preflight = self.f.payload['successor']['network_repair_preflight']
        original = copy.deepcopy(preflight)
        preflight['diagnostics']['d2']['sha256'] = 'a' * 64
        self.assertIn('Item32 Sep17 initialization UNKNOWN closure mismatch', self.validate())
        self.f.payload['successor']['network_repair_preflight'] = original
        record = self.f.root / original['diagnostics']['d1']['ref']; record.unlink()
        self.assertIn('Item32 canonical execution plan binding mismatch', self.validate())

    def test_new_window_cannot_precede_d0_or_reuse_pre_failure_owner_scope(self):
        self.f.plan['admission'].update(not_before_utc='2026-09-17T01:00:00+00:00',
            dispatch_deadline_utc='2026-09-17T01:40:00+00:00', must_finish_before_utc='2026-09-17T02:00:00+00:00')
        self.rebind(); self.assertIn('Item32 canonical execution plan binding mismatch', self.validate())


if __name__ == '__main__': unittest.main()
