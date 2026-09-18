"""Real isolated SQLite reads for the compatible Admin monthly projections."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

MODEL = Path(__file__).resolve().parents[1] / 'model'
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))
db = importlib.import_module('db')
admin = importlib.import_module('admin_server')
reporting = importlib.import_module('usage_reporting')
NOW = datetime(2026, 9, 19, 0, 15, tzinfo=timezone.utc)
AT = '2026-09-18T12:00:00+00:00'


class AdminUserMonthAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / 'synthetic.db'
        db.init_db()
        for uid in ('owner', 'other'):
            db.execute('INSERT INTO users(id,username,email,password_hash,password_salt,created_at) '
                       'VALUES(?,?,?,?,?,?)', (uid, uid, uid + '@example.invalid', 'hash', 'salt', AT))
        self.clock = mock.patch.object(reporting, 'datetime')
        self.clock.start().now.return_value = NOW
        self.addCleanup(self.clock.stop)

    def tearDown(self):
        db._DB_PATH = self.old_path
        self.temp.cleanup()

    def usage(self, uid='owner', *, operation='generate', cost=0, estimate=0,
              mode='estimated', at=AT, status='completed'):
        key = str(uuid4())
        db.execute('INSERT INTO usage_records(id,user_id,operation,cost_rmb,estimated_cost_rmb,'
                   'cost_mode,recorded_at) VALUES(?,?,?,?,?,?,?)',
                   (key, uid, operation, cost, estimate, mode, at))
        db.execute('INSERT INTO idempotency_requests(id,user_id,operation,key_hash,payload_hash,status,'
                   'lease_token_hash,lease_expires_at,usage_id,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (str(uuid4()), uid, operation, key, 'payload', status, 'lease', AT, key, at, at))
        return key

    def model(self, usage, *, cost=0, pricing='exact', status='complete'):
        key = str(uuid4())
        db.execute('INSERT INTO model_usage_records(id,usage_record_id,provider,model,price_currency,'
                   'usd_cny,price_version,known_cost_rmb,pricing_status,usage_status,recorded_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (key, usage, 'synthetic', 'synthetic', 'CNY', 1, 'fixture', cost, pricing, status, AT))
        return key

    def detail(self, uid='owner'):
        return asyncio.run(admin.admin_user_detail(uid, {}))

    def users(self, **kwargs):
        return asyncio.run(admin.admin_users(admin={}, **kwargs))

    def test_known_and_estimated_amounts_and_52_plus_4_are_preserved_without_writes(self):
        first = self.usage(cost=83.7313, mode='actual')
        self.model(first, cost=83.7313)
        self.usage(cost=3.04, estimate=3.04, status='failed')
        for _ in range(50):
            self.usage()
        for _ in range(4):
            self.usage(operation='extra_image', mode='included_in_parent')
        self.usage('other', cost=999, estimate=999)
        before = hashlib.sha256(db._DB_PATH.read_bytes()).hexdigest()
        listed = self.users(search='owner')['users'][0]
        detail = self.detail()
        self.assertEqual(listed['month_ops'], 56)
        self.assertEqual(listed['month_cost'], 86.7713)
        self.assertEqual(sum(r['cnt'] for r in detail['month_usage']), 56)
        for key in ('month_window', 'month_accounting', 'month_operation_accounting'):
            self.assertEqual(listed[key], detail[key])
        value = detail['month_accounting']
        self.assertEqual(value['business']['recorded'], 52)
        self.assertEqual(value['business']['completed'], 51)
        self.assertEqual(value['business']['failed'], 1)
        self.assertEqual(value['auxiliary']['recorded'], 4)
        self.assertEqual(value['cost']['known_calculated_rmb'], 83.7313)
        self.assertEqual(value['cost']['estimated_only_rmb'], 3.04)
        self.assertFalse(value['cost']['complete'])
        self.assertIsNone(value['cost']['supplier_bill_paid_rmb'])
        self.assertEqual(before, hashlib.sha256(db._DB_PATH.read_bytes()).hexdigest())

    def test_only_unpriced_incomplete_usage_is_unresolved_not_confirmed_zero_cost(self):
        usage = self.usage()
        self.model(usage, pricing='unpriced', status='usage_missing')
        for value in (self.detail(), self.users(search='owner')['users'][0]):
            accounting = value['month_accounting']
            self.assertFalse(accounting['cost']['complete'])
            self.assertEqual(accounting['cost']['unknown_records'], 1)
            self.assertIsNone(accounting['cost']['supplier_bill_paid_rmb'])
            self.assertEqual(accounting['models']['pricing_gaps'], 1)
            self.assertEqual(accounting['models']['usage_incomplete'], 1)
            self.assertEqual(accounting['models']['token_coverage'], 'partial')
            self.assertFalse(value['month_operation_accounting']['generate']['cost_complete'])

    def test_missing_model_details_retain_estimate_and_missing_token_coverage(self):
        self.usage(cost=3.04, estimate=3.04)
        value = self.detail()['month_accounting']
        self.assertEqual(value['cost']['estimated_only_rmb'], 3.04)
        self.assertEqual(value['cost']['unknown_records'], 1)
        self.assertEqual(value['models']['token_coverage'], 'not_recorded')
        self.assertIsNone(value['physical']['actual_http_requests'])

    def test_utc_window_and_owner_bindings_do_not_infer_cross_user_calls(self):
        usage = self.usage(cost=2, estimate=2)
        self.usage(at='2026-08-31T23:59:59+00:00', cost=50, estimate=50)
        self.usage(at='2026-09-19T00:16:00+00:00', cost=60, estimate=60)
        self.usage('other', cost=900, estimate=900)
        db.execute('INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,'
                   'reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)',
                   (str(uuid4()), 'website-free-product-20260912', 'other', 'fixture', 'unknown', 0, AT, usage))
        value = self.detail()
        self.assertEqual(value['month_window']['start'], '2026-09-01T00:00:00+00:00')
        self.assertEqual(value['month_window']['as_of'], NOW.isoformat())
        self.assertEqual(value['month_accounting']['business']['recorded'], 1)
        self.assertEqual(value['month_accounting']['physical']['recorded'], 0)
        self.assertEqual(value['month_accounting']['cost']['estimated_only_rmb'], 2)
        self.assertEqual(self.users(search='other')['users'][0]['month_accounting']['cost']['estimated_only_rmb'], 900)

    def test_page_uses_one_readonly_snapshot_and_only_selected_user_projections(self):
        self.usage()
        self.usage('other')
        original_tx, original_read = db.transaction, reporting.read_reporting_rows
        connections, projected = [], []

        @contextmanager
        def transaction(*, write=False):
            self.assertFalse(write)
            with original_tx(write=False) as tx:
                connections.append(tx.conn)
                yield tx

        def read(tx, window, *, user_id=None):
            self.assertIs(tx.conn, connections[0])
            self.assertEqual(tx.fetchone('PRAGMA query_only')[0], 1)
            projected.append(user_id)
            return original_read(tx, window, user_id=user_id)

        with mock.patch.object(db, 'transaction', transaction), mock.patch.object(reporting, 'read_reporting_rows', read):
            result = self.users(page_size=1, search='owner')
        self.assertEqual(len(connections), 1)
        self.assertEqual(projected, ['owner'])
        self.assertEqual(len(result['users']), 1)

    def test_call_detail_failure_is_local_to_savepoint_and_month_report_survives(self):
        self.usage(cost=3.04, estimate=3.04)
        with mock.patch.object(admin, '_admin_usage_call_details', side_effect=PermissionError):
            result = self.detail()
        self.assertEqual(result['recent_usage'][0]['call_details']['status'], 'unavailable')
        self.assertEqual(result['month_accounting']['cost']['estimated_only_rmb'], 3.04)

    def test_user_routes_still_require_admin_authentication(self):
        client = TestClient(admin.admin_app)
        for path in ('/admin/users', '/admin/users/owner'):
            self.assertEqual(client.get(path).status_code, 403)
            self.assertEqual(client.get(path, headers={'Authorization': 'Bearer ordinary-user-token'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
