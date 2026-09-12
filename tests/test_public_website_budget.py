"""Secret-free durability checks for the website's byte prepayment."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

_path = Path(__file__).resolve().parents[1] / 'deploy/production/public_website_budget.py'
_spec = importlib.util.spec_from_file_location('web_budget', _path)
budget = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(budget)


class WebsiteBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def state(self):
        return json.loads((self.root / 'budget.json').read_text())

    def test_prepaid_before_kernel_grant_and_no_periodic_reset(self):
        def grant(size):
            self.assertEqual(self.state()['reserved_bytes'], budget.BLOCK)
            self.assertEqual(size, budget.BLOCK)
        with mock.patch.object(budget, 'remaining_quota', return_value=0), \
             mock.patch.object(budget, 'install_quota', side_effect=grant):
            budget.tick(self.root, initialize=True)
        with mock.patch.object(budget, 'remaining_quota', return_value=budget.BLOCK // 2), \
             mock.patch.object(budget, 'install_quota') as install:
            budget.tick(self.root)
            install.assert_not_called()
        self.assertEqual(self.state()['reserved_bytes'], budget.BLOCK)

    def test_crash_after_reserve_burns_block_before_recovery(self):
        def fail_grant(size):
            if size:
                raise RuntimeError('simulated grant failure')
        with mock.patch.object(budget, 'remaining_quota', return_value=0), \
             mock.patch.object(budget, 'install_quota', side_effect=fail_grant):
            with self.assertRaises(RuntimeError):
                budget.tick(self.root, initialize=True)
        self.assertEqual(self.state()['reserved_bytes'], budget.BLOCK)
        with mock.patch.object(budget, 'remaining_quota', return_value=0), \
             mock.patch.object(budget, 'install_quota'):
            budget.tick(self.root)
        self.assertEqual(self.state()['reserved_bytes'], 2 * budget.BLOCK)

    def test_exhaustion_and_corruption_never_grant(self):
        budget.save_state(self.root / 'budget.json', {'limit_bytes': budget.LIMIT, 'reserved_bytes': budget.LIMIT})
        with mock.patch.object(budget, 'remaining_quota', return_value=0), \
             mock.patch.object(budget, 'install_quota') as install:
            self.assertEqual(budget.tick(self.root)['status'], 'EXHAUSTED')
            install.assert_called_once_with(0)
        (self.root / 'budget.json').write_text('{bad')
        with mock.patch.object(budget, 'install_quota') as install:
            with self.assertRaises(ValueError):
                budget.tick(self.root)
            install.assert_called_once_with(0)

    def test_reinitialize_rejected_preserves_total(self):
        with mock.patch.object(budget, 'remaining_quota', return_value=0), \
             mock.patch.object(budget, 'install_quota'):
            budget.tick(self.root, initialize=True)
            with self.assertRaises(ValueError):
                budget.tick(self.root, initialize=True)
        self.assertEqual(self.state()['reserved_bytes'], budget.BLOCK)

    def test_io_failure_stops_only_nginx_even_without_kernel_enforcement(self):
        with mock.patch.object(budget.socket, 'gethostname', return_value='noteai-api-c'), \
             mock.patch.object(budget.os, 'geteuid', return_value=0), \
             mock.patch.object(budget, 'tick', side_effect=OSError('ledger unavailable')), \
             mock.patch.object(budget.subprocess, 'run') as stop, \
             mock.patch('sys.argv', ['public_website_budget.py']):
            with self.assertRaises(SystemExit) as exited:
                budget.main()
            self.assertEqual(exited.exception.code, 1)
            self.assertEqual(stop.call_args.args[0], ['systemctl', '--no-block', 'stop', 'nginx.service'])

    def test_atomic_nft_transaction_touches_only_website(self):
        with mock.patch.object(budget, 'table_exists', return_value=True), \
             mock.patch.object(budget, 'nft') as run:
            budget.install_quota(budget.BLOCK)
        script = run.call_args.kwargs['input']
        self.assertTrue(script.startswith('delete table inet noteai_public_budget\n'))
        self.assertIn('ip saddr 10.42.10.44 tcp sport { 80, 443 }', script)
        self.assertNotIn('flush ruleset', script)
        self.assertNotIn('hook forward', script)
        self.assertNotIn('hook input', script)


if __name__ == '__main__':
    unittest.main()
