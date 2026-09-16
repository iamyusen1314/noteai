"""One fixed successor: synthetic local receipts/SQLite only, no provider or host."""
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest import mock

from tests import test_item32_v5_profile as v5

e, ROOT = v5.e, v5.ROOT


class Sep17ProfileTests(unittest.TestCase):
    def setUp(self):
        self.f = v5.V5ProfileTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.plan = json.loads((ROOT / 'deploy/production/plans/item32-v5-sep17-successor-prospective.json').read_bytes())
        self.f.plan['outer_executor_sha256'] = hashlib.sha256(Path(e.__file__).read_bytes()).hexdigest()
        self.f.authorize()

    def test_fixed_new_root_keeps_the_original_readback_identity(self):
        plan, _ = self.f.load()
        self.assertEqual(e.WORK_ROOT, e.V5_SEP17_WORK_ROOT)
        self.assertEqual(str(e.V5_WORK_ROOT), '/var/lib/noteai/item32-v5-successor-20260916')
        self.assertEqual(plan['previous_v5_successor'], e._sep17_previous_binding(ROOT))
        self.assertEqual(len(plan['previous_v5_successor']['files']), 9)

    def test_scope_binds_new_predecessor_before_host_or_secret_access(self):
        self.f.plan['previous_v5_successor']['collection_admissions'] = 0
        with mock.patch.object(e, '_read_regular_file') as read_host:
            with self.assertRaisesRegex(e.Item32Error, 'plan_authorization_binding'):
                self.f.load()
        read_host.assert_not_called()

    def test_even_rebound_scope_cannot_alter_fixed_history_or_window(self):
        baseline = copy.deepcopy(self.f.plan)
        for mutation in ('missing', 'count', 'mode', 'hash', 'host_ref', 'date', 'window'):
            with self.subTest(mutation=mutation):
                self.f.plan = copy.deepcopy(baseline)
                previous = self.f.plan['previous_v5_successor']
                if mutation == 'missing': self.f.plan.pop('previous_v5_successor')
                elif mutation == 'count': previous['outcome_unknown_count'] = False
                elif mutation in ('mode', 'hash'):
                    record = next(iter(previous['files'].values()))
                    record['mode' if mutation == 'mode' else 'sha256'] = '0o644' if mutation == 'mode' else 'a' * 64
                elif mutation == 'host_ref': previous['final_readback']['host_ref'] = '/different/seal.json'
                elif mutation == 'date': previous['call_date_utc'] = '2026-09-15'
                else: self.f.plan['admission']['dispatch_deadline_utc'] = '2026-09-17T01:39:00+00:00'
                self.f.authorize()
                with self.assertRaisesRegex(e.Item32Error, 'plan_binding'):
                    self.f.load()

    def test_same_or_future_date_ledger_blocks_even_when_production_today_would_be_zero(self):
        self.f.load()
        now = datetime(2026, 9, 17, 1, 1, tzinfo=timezone.utc)
        dates = ['2026-09-06', '2026-09-06', '2026-09-15'] + ['2026-09-16'] * 11
        self.assertEqual(e._admission_budget(self.f.plan, {'call_dates': dates}, now=now)['used_before'], 0)
        for date in ('2026-09-17', '2026-09-18'):
            with self.subTest(date=date), self.assertRaisesRegex(e.Item32Error, 'utc_budget_not_available'):
                e._admission_budget(self.f.plan, {'call_dates': dates + [date]}, now=now)

    def test_readback_flags_select_only_their_fixed_root_without_execution(self):
        with mock.patch.object(e, 'read_retained_result', return_value={'status': 'RETAINED_BYTES_READBACK_ONLY'}) as readback, \
                mock.patch.object(e, 'execute') as execute, mock.patch('builtins.print'):
            self.assertEqual(e.main(['--v5-readback-only']), 0)
            self.assertEqual(e.WORK_ROOT, e.V5_WORK_ROOT)
            self.assertEqual(e.main(['--v5-sep17-readback-only']), 0)
            self.assertEqual(e.WORK_ROOT, e.V5_SEP17_WORK_ROOT)
            self.assertEqual(readback.call_count, 2)
            execute.assert_not_called()
            with self.assertRaises(SystemExit):
                e.main(['--v5-readback-only', '--v5-sep17-readback-only'])

    def history(self):
        base = self.f.path / 'sep16'
        run = base / 'run-synthetic'
        run.mkdir(parents=True)
        store = run / 'task-store/hot_keywords.db'
        store.parent.mkdir()
        self.f.stack.enter_context(mock.patch.object(e, 'V5_WORK_ROOT', base))
        start = datetime(2026, 9, 16, 14, 30, 30, tzinfo=timezone.utc)
        observations, rows = [], []
        for index, kind in enumerate(['dsl', 'session', *e.ENDPOINT_SEQUENCE[:11]]):
            first = start + timedelta(seconds=index)
            last = first + timedelta(milliseconds=250)
            observations.extend([
                {'phase': 'dispatch', 'request_kind': kind, 'sequence': index + 1, 'at': first.isoformat()},
                {'phase': 'response', 'request_kind': kind, 'sequence': index + 1, 'at': last.isoformat()}])
            if index >= 2:
                rows.append((index - 1, kind, 'succeeded' if index < 12 else 'failed',
                             first.isoformat(), '2026-09-16', (last + timedelta(milliseconds=250)).isoformat()))
        with sqlite3.connect(store) as connection:
            connection.execute('CREATE TABLE xhs_trends_provider_attempts '
                '(ordinal INTEGER,endpoint TEXT,status TEXT,admitted_at TEXT,admitted_date TEXT,completed_at TEXT)')
            connection.executemany('INSERT INTO xhs_trends_provider_attempts VALUES (?,?,?,?,?,?)', rows)
        summary = {'initialization_dispatches_observed': 2, 'initialization_request_counts': {'dsl': 1, 'session': 1},
            'collection_dispatches_observed': 11, 'response_events_observed': 13, 'unknown_events_observed': 0,
            'unresolved_dispatches_observed': 0, 'invalid_observations': 0, 'observation_complete': True}
        admission = {'run_directory_name': run.name, 'status': 'HOLD', 'provider_calls': 11,
            'outcome_unknown_count': 0, 'automatic_retry_count': 0, 'no_replay': True,
            'budget': {'bucket_date': '2026-09-16'}, 'physical_http_budget': e.V5_PHYSICAL_BUDGET}
        receipt = {'exit_code': 1, 'secret_values_recorded': False,
                   'physical_http_summary': summary, 'physical_http_observations': observations}
        def write(path, value):
            path.write_bytes(e._json_bytes(value)); path.chmod(0o600)
        write(base / 'item32-admission.json', admission)
        write(run / 'worker-receipt.json', receipt)
        probe = {'server_enforced_read_only': True, 'write_count': 0, 'tuple_write_count': 0,
            'active_or_manual_count': 0, 'session_blocked_count': 0, 'today_attempt_count': 0,
            'write_tables': [], 'xid_assigned': False, 'transaction_rolled_back': True,
            'secret_values_recorded': False, 'readback_query_sha256': e.DB_PROBE_QUERYSET_SHA256,
            'session_identity_sha256': 'a' * 64}
        for phase, clock in (('before', start - timedelta(seconds=1)), ('after', start + timedelta(seconds=14))):
            write(run / f'database-{phase}-probe.json', dict(probe, observed_at=clock.isoformat()))
        stage = self.f.path / 'old-package'; stage.mkdir()
        for name in ('dispatch-started.json', 'dispatch-child.json', 'dispatch-done.json', 'dispatch.log'):
            write(stage / name, {})
        store.chmod(0o644)
        paths = [base / 'item32-admission.json', run / 'worker-receipt.json', store,
                 run / 'database-before-probe.json', run / 'database-after-probe.json', *stage.iterdir()]
        def bind():
            return {str(p): {'bytes': p.stat().st_size, 'mode': oct(p.stat().st_mode & 0o777),
                            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths}
        raw = e._json_bytes({'at': '2026-09-16T14:40:08+00:00'})
        raw += b' ' * (2386 - len(raw))
        seal = base / 'hold-final-readback.json'; seal.write_bytes(raw); seal.chmod(0o600)
        self.f.stack.enter_context(mock.patch.object(e, 'V5_SEP16_FINAL_SHA256', hashlib.sha256(raw).hexdigest()))
        binding = {'files': bind(), 'final_readback': {'host_ref': str(seal)}}
        return binding, base, run, store, bind

    def test_original_eleven_rows_and_database_probes_are_read_without_mutation(self):
        binding, base, run, store, _ = self.history()
        before = {p: Path(p).read_bytes() for p in binding['files']}
        result, dates = e._verify_sep16_v5_previous(binding)
        self.assertEqual(dates, ['2026-09-16'] * 11)
        self.assertIs(result['host_final_readback_verified'], True)
        self.assertIs(result['database_readonly_probes_verified'], True)
        self.assertEqual(before, {p: Path(p).read_bytes() for p in binding['files']})
        self.assertFalse(Path(str(store) + '-wal').exists())

    def test_missing_or_altered_host_seal_cannot_use_bundle_copy(self):
        binding, *_ = self.history()
        seal = Path(binding['final_readback']['host_ref'])
        seal.write_bytes(b'changed')
        with self.assertRaisesRegex(e.Item32Error, 'predecessor_final_seal'):
            e._verify_sep16_v5_previous(binding)
        seal.unlink()
        with self.assertRaises(FileNotFoundError): e._verify_sep16_v5_previous(binding)

    def test_ledger_dates_outcomes_and_admission_unknowns_remain_semantically_checked(self):
        binding, base, run, store, bind = self.history()
        original = store.read_bytes()
        for sql in ("UPDATE xhs_trends_provider_attempts SET admitted_date='2026-09-17' WHERE ordinal=11",
                    "UPDATE xhs_trends_provider_attempts SET status='outcome_unknown' WHERE ordinal=11",
                    "DELETE FROM xhs_trends_provider_attempts WHERE ordinal=11"):
            with self.subTest(sql=sql):
                store.write_bytes(original)
                with sqlite3.connect(store) as connection: connection.execute(sql)
                binding['files'] = bind()  # Isolate semantic checking from the separate byte-hash check.
                with self.assertRaisesRegex(e.Item32Error, 'predecessor_store_shape'):
                    e._verify_sep16_v5_previous(binding)
        store.write_bytes(original)
        admission = base / 'item32-admission.json'
        value = json.loads(admission.read_bytes()); value['outcome_unknown_count'] = 1
        admission.write_bytes(e._json_bytes(value)); binding['files'] = bind()
        with self.assertRaisesRegex(e.Item32Error, 'predecessor_shape'): e._verify_sep16_v5_previous(binding)

    def test_original_database_proof_cannot_be_unknown_changed_or_new_day(self):
        binding, _, run, _, bind = self.history()
        after = run / 'database-after-probe.json'; original = after.read_bytes()
        for change in ({'write_count': 1}, {'session_identity_sha256': 'b' * 64},
                       {'observed_at': '2026-09-17T00:00:00+00:00'}, {'today_attempt_count': False}):
            with self.subTest(change=change):
                value = json.loads(original); value.update(change)
                after.write_bytes(e._json_bytes(value)); binding['files'] = bind()
                with self.assertRaisesRegex(e.Item32Error, 'predecessor_database_proof'):
                    e._verify_sep16_v5_previous(binding)

    def test_original_sep16_lock_is_held_and_active_owner_blocks_before_admission(self):
        roots = []
        for name in ('SEALED_ORIGINAL_ROOT', 'SEALED_DIAGNOSTIC_ROOT', 'SEALED_SUCCESSOR_ROOT', 'V5_WORK_ROOT'):
            path = self.f.path / name; path.mkdir(); lock = path / 'executor.lock'
            lock.touch(mode=0o600); lock.chmod(0o600); roots.append(path)
            self.f.stack.enter_context(mock.patch.object(e, name, path))
        self.f.stack.enter_context(mock.patch.object(e, 'ACTIVE_V5_PLAN', self.f.plan))
        descriptors = e._acquire_predecessor_locks()
        try:
            self.assertEqual(len(descriptors), 4)
        finally:
            for descriptor in descriptors: os.close(descriptor)
        lock = os.open(roots[-1] / 'executor.lock', os.O_RDWR)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(e.Item32Error, 'predecessor_active'): e._acquire_predecessor_locks()
        finally: os.close(lock)


if __name__ == '__main__': unittest.main()
