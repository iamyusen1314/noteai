"""Bounded recovery profile checks; no host, provider or production connection."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import sys
import unittest
from unittest import mock

from tests import test_item32_v5_profile as v5

e, ROOT = v5.e, v5.ROOT


class NetworkRepairProfileTests(unittest.TestCase):
    def setUp(self):
        self.f = v5.V5ProfileTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.plan['admission']['work_root'] = str(e.V5_NETWORK_WORK_ROOT)
        self.f.plan['previous_v5_successor'] = e._sep17_previous_binding(ROOT)
        self.f.plan.update(e._network_repair_bindings(ROOT))
        self.f.authorize()

    def test_fixed_profile_keeps_old_unknown_and_original_collection_budget_separate(self):
        plan, _ = self.f.load()
        self.assertEqual(e.WORK_ROOT, e.V5_NETWORK_WORK_ROOT)
        self.assertEqual(plan['physical_http_budget'], {'initialization': 2, 'collection': 34, 'total': 36})
        old = plan['previous_v5_initialization_hold']
        self.assertEqual((old['collection_admissions'], old['initialization_outcome_unknown_count']), (0, 1))
        self.assertEqual(len(old['files']), 10)
        self.assertEqual(plan['network_repair_preflight']['sha256'], e.V5_NETWORK_D0_SHA256)

    def test_reauthorized_scope_cannot_erase_unknown_or_change_seal_d0_or_physical_budget(self):
        original = copy.deepcopy(self.f.plan)
        for key, value in (('initialization_outcome_unknown_count', 0), ('collection_admissions', 1),
                           ('automatic_retry_count', False), ('no_replay', 1)):
            with self.subTest(key=key):
                self.f.plan = copy.deepcopy(original)
                self.f.plan['previous_v5_initialization_hold'][key] = value
                self.f.authorize()
                with self.assertRaisesRegex(e.Item32Error, 'plan_binding'): self.f.load()
        for field in ('previous_v5_initialization_hold', 'network_repair_preflight'):
            self.f.plan = copy.deepcopy(original); self.f.plan.pop(field); self.f.authorize()
            with self.assertRaisesRegex(e.Item32Error, 'plan_binding'): self.f.load()
        self.f.plan = copy.deepcopy(original)
        self.f.plan['physical_http_budget']['initialization'] = 3; self.f.authorize()
        with self.assertRaisesRegex(e.Item32Error, 'plan_binding'): self.f.load()

    def test_scope_authorization_and_post_d0_window_required(self):
        self.f.plan['authorization']['status'] = 'PENDING'
        with self.assertRaisesRegex(e.Item32Error, 'plan_not_authorized'): self.f.load()
        self.f.plan['admission'].update(not_before_utc='2026-09-17T01:00:00+00:00',
            dispatch_deadline_utc='2026-09-17T01:40:00+00:00', must_finish_before_utc='2026-09-17T02:00:00+00:00',
            bucket_date_utc='2026-09-17')
        self.f.authorize()
        with self.assertRaises(e.Item32Error): self.f.load()

    def test_package_original_seal_and_d0_bytes_are_pinned(self):
        for ref in (e.V5_SEP17_FINAL_REF, e.V5_NETWORK_D0_REF,
                    *[f'deploy/production/evidence/production-item32-network-repair-{name}-20260917.json' for name in ('d1', 'd2')]):
            target = self.f.path / ref; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / ref).read_bytes())
        self.assertEqual(e._network_repair_bindings(self.f.path), e._network_repair_bindings(ROOT))
        path = self.f.path / e.V5_NETWORK_D0_REF
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(e.Item32Error, 'network_preflight_binding'):
            e._network_repair_bindings(self.f.path)

    def test_diagnostic_failure_missing_receipt_and_changed_d2_cannot_enable_formal_profile(self):
        for name in ('d1', 'd2'):
            ref = f'deploy/production/evidence/production-item32-network-repair-{name}-20260917.json'
            target = self.f.path / ref; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / ref).read_bytes())
        actual = e._network_diagnostics_bindings(self.f.path)
        self.assertEqual(actual['d2']['sha256'], e.V5_NETWORK_D2_SHA256)
        path = self.f.path / actual['d2']['ref']; original = path.read_bytes()
        value = json.loads(original); value['result']['worker']['state'] = 'REQUEST_UNKNOWN'
        path.write_bytes(e._json_bytes(value))
        with self.assertRaisesRegex(e.Item32Error, 'network_diagnostic_binding'):
            e._network_diagnostics_bindings(self.f.path)
        path.unlink()
        with self.assertRaises(FileNotFoundError): e._network_diagnostics_bindings(self.f.path)

    def test_all_five_prior_locks_and_busy_september17_are_guarded(self):
        names = ('SEALED_ORIGINAL_ROOT', 'SEALED_DIAGNOSTIC_ROOT', 'SEALED_SUCCESSOR_ROOT',
                 'V5_WORK_ROOT', 'V5_SEP17_WORK_ROOT')
        roots = []
        for name in names:
            root = self.f.path / name; root.mkdir(); (root / 'executor.lock').touch(mode=0o600)
            self.f.stack.enter_context(mock.patch.object(e, name, root)); roots.append(root)
        self.f.stack.enter_context(mock.patch.object(e, 'ACTIVE_V5_PLAN', self.f.plan))
        held = e._acquire_predecessor_locks()
        try: self.assertEqual(len(held), 5)
        finally:
            for fd in held: os.close(fd)
        busy = os.open(roots[-1] / 'executor.lock', os.O_RDONLY)
        try:
            fcntl.flock(busy, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(e.Item32Error, 'predecessor_active'): e._acquire_predecessor_locks()
        finally: os.close(busy)

    def test_new_readback_selects_only_new_identity(self):
        with mock.patch.object(e, 'read_retained_result', return_value={'status': 'RETAINED_BYTES_READBACK_ONLY'}), \
                mock.patch.object(e, 'execute') as dispatch, mock.patch('builtins.print'):
            self.assertEqual(e.main(['--v5-network-repair-readback-only']), 0)
            self.assertEqual(e.WORK_ROOT, e.V5_NETWORK_WORK_ROOT)
            dispatch.assert_not_called()
            with self.assertRaises(SystemExit): e.main(['--v5-network-repair-readback-only', '--v5-sep17-readback-only'])

    def test_network_none_constructor_probe_checks_six_infos_and_always_closes(self):
        names = ('NAMELOOKUP_TIME', 'CONNECT_TIME', 'APPCONNECT_TIME', 'PRETRANSFER_TIME', 'STARTTRANSFER_TIME', 'TOTAL_TIME')
        const = SimpleNamespace(CurlInfo=SimpleNamespace(**dict(zip(names, range(6)))))
        for infos in (list(range(6)), []):
            client = SimpleNamespace(session=SimpleNamespace(curl_infos=infos), close=mock.Mock(), request=mock.Mock())
            with mock.patch.dict(sys.modules, {'curl_cffi': SimpleNamespace(), 'curl_cffi.const': const}):
                if infos:
                    exec(compile(e.V5_NETWORK_CLIENT_PREFLIGHT, '<network-none-client-probe>', 'exec'), {'v': SimpleNamespace(TrendsCurlClient=lambda: client)})
                else:
                    with self.assertRaises(AssertionError):
                        exec(compile(e.V5_NETWORK_CLIENT_PREFLIGHT, '<network-none-client-probe>', 'exec'), {'v': SimpleNamespace(TrendsCurlClient=lambda: client)})
            client.close.assert_called_once(); client.request.assert_not_called()
        self.f.test_v5_preflight_compiles_bound_import_script_without_secret_or_network()

    def test_collection_freshness_does_not_reclassify_initialization_unknown(self):
        self.f.load()
        from datetime import datetime, timedelta
        now = datetime.fromisoformat(self.f.plan['admission']['not_before_utc']) + timedelta(seconds=1)
        previous = {'call_dates': ['2026-09-06', '2026-09-06', '2026-09-15'] + ['2026-09-16'] * 11}
        self.assertEqual(e._admission_budget(self.f.plan, previous, now=now)['remaining_before'], 34)
        previous['call_dates'].append(now.date().isoformat())
        with self.assertRaisesRegex(e.Item32Error, 'utc_budget_not_available'):
            e._admission_budget(self.f.plan, previous, now=now)

    def test_host_history_reads_exact_originals_and_immutable_empty_ledger(self):
        seal = json.loads((ROOT / e.V5_SEP17_FINAL_REF).read_bytes())
        base = self.f.path / 'old'; run = base / 'run-arx52z4k'; run.mkdir(parents=True)
        self.f.stack.enter_context(mock.patch.object(e, 'V5_SEP17_WORK_ROOT', base))
        store = run / 'task-store/hot_keywords.db'; store.parent.mkdir()
        with sqlite3.connect(store) as c: c.execute('CREATE TABLE xhs_trends_provider_attempts (ordinal INTEGER)')
        files = {base / 'item32-admission.json': seal['admission'], run / 'worker-receipt.json': seal['worker_receipt']}
        files.update({run / f'database-{phase}-probe.json': seal['database_probes'][phase] for phase in ('before', 'after')})
        for path, value in files.items(): path.write_bytes(e._json_bytes(value)); path.chmod(0o600)
        store.chmod(0o644)
        binding = copy.deepcopy(self.f.plan['previous_v5_initialization_hold'])
        def rebind():
            binding['files'] = {str(p): {'bytes': p.stat().st_size, 'mode': oct(p.stat().st_mode & 0o777),
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (*files, store)}
        rebind()
        raw = json.dumps(seal).encode(); raw += b' ' * (6794 - len(raw)); self.assertEqual(len(raw), 6794)
        sealed = base / 'hold-final-readback.json'; sealed.write_bytes(raw); sealed.chmod(0o600)
        binding['final_readback']['host_ref'] = str(sealed)
        self.f.stack.enter_context(mock.patch.object(e, 'V5_SEP17_FINAL_SHA256', hashlib.sha256(raw).hexdigest()))
        d0 = self.f.path / 'd0.json'; d0.write_bytes((ROOT / e.V5_NETWORK_D0_REF).read_bytes()); d0.chmod(0o600)
        preflight = {**self.f.plan['network_repair_preflight'], 'host_ref': str(d0)}
        preflight = copy.deepcopy(preflight)
        for name, record in preflight['diagnostics'].items():
            local = self.f.path / f'{name}.json'; local.write_bytes((ROOT / record['ref']).read_bytes()); local.chmod(0o600)
            record['host_ref'] = str(local)
        env = self.f.path / 'synthetic.env'; env.write_bytes(b'synthetic non-secret'); env.chmod(0o600)
        self.f.stack.enter_context(mock.patch.object(e, 'SECRET_ENV', env))
        self.f.stack.enter_context(mock.patch.object(e, 'V5_SESSION_SHA256', hashlib.sha256(env.read_bytes()).hexdigest()))
        plan = {'previous_v5_initialization_hold': binding, 'network_repair_preflight': preflight}
        # Local test fixture permits non-root file ownership; production metadata routine is unchanged.
        self.f.stack.enter_context(mock.patch.object(e, '_read_regular_file', side_effect=lambda p, **kw: p.read_bytes()))
        before = store.read_bytes()
        previous, proof = e._verify_sep17_initialization_hold(plan)
        self.assertTrue(proof['host_readback_verified']); self.assertEqual(previous['initialization_outcome_unknown_count'], 1)
        self.assertEqual(before, store.read_bytes()); self.assertFalse(Path(str(store) + '-wal').exists())
        d2_path = Path(preflight['diagnostics']['d2']['host_ref']); original_d2 = d2_path.read_bytes()
        d2_path.write_bytes(b'changed')
        with self.assertRaisesRegex(e.Item32Error, 'network_diagnostic_binding'): e._verify_sep17_initialization_hold(plan)
        d2_path.write_bytes(original_d2)
        with sqlite3.connect(store) as c: c.execute('INSERT INTO xhs_trends_provider_attempts VALUES (1)')
        rebind()
        with self.assertRaisesRegex(e.Item32Error, 'predecessor_store_shape'): e._verify_sep17_initialization_hold(plan)


if __name__ == '__main__': unittest.main()
