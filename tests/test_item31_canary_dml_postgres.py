"""Synthetic canary DML on a disposable, network-isolated PG16 Unix socket.

Run explicitly in the local test container, never with a supplied production DSN.
Selected database/payment functions are imported; no API runtime, provider call,
dotenv or production database is loaded.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

import psycopg

from tools import collect_item31_canary_dml as dml


ENABLED = os.environ.get("NOTEAI_LOCAL_PG16_CANARY_TEST") == "1"
CONNECT = dict(host="/var/run/postgresql", dbname="noteai_local", user="postgres")


@unittest.skipUnless(ENABLED, "explicit isolated PG16 container required")
class CanaryDmlPostgresTests(unittest.TestCase):
    def setUp(self):
        self.owner = psycopg.connect(**CONNECT, autocommit=True)
        version, addr = self.owner.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr()"
        ).fetchone()
        self.assertTrue(160000 <= version < 170000)
        self.assertIsNone(addr)
        self.owner.execute("DROP TABLE IF EXISTS payment_events,payment_orders CASCADE")
        self.owner.execute("DROP FUNCTION IF EXISTS public.noteai_item31_canary_dml_notice()")
        self.owner.execute("DROP FUNCTION IF EXISTS public.test_canary_event()")
        self.owner.execute("CREATE TABLE payment_orders(id int primary key,canary text,value int)")
        self.owner.execute("CREATE TABLE payment_events(id int primary key,canary text,"
                           "order_id int references payment_orders(id) ON DELETE CASCADE)")
        self.owner.execute("""CREATE FUNCTION test_canary_event() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              INSERT INTO payment_events VALUES(NEW.id,NEW.canary,NEW.id);
              RETURN NEW; END $$""")
        self.owner.execute("CREATE TRIGGER child_event AFTER INSERT ON payment_orders "
                           "FOR EACH ROW EXECUTE FUNCTION test_canary_event()")
        self.activation = str(uuid.uuid4())
        self.targets = {
            "payment_orders": ("canary", "local-only"),
            "payment_events": ("canary", "local-only"),
        }
        for statement in dml.installation_sql(self.activation, self.targets):
            self.owner.execute(statement)
        self.listener = psycopg.connect(**CONNECT, autocommit=True)
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "canary-dml.jsonl"
        self.capture = dml.CanaryCapture(self.listener, self.owner,
                                        activation=self.activation, targets=self.targets,
                                        provider="wechatpay_direct", journal=self.path)
        self.writer = psycopg.connect(**CONNECT, autocommit=True)

    def tearDown(self):
        if not self.capture.handle.closed:
            self.capture.handle.close()
        self.writer.close()
        self.listener.close()
        self.owner.close()
        self.temp.cleanup()

    def begin(self, provider="wechatpay_direct"):
        self.writer.execute("BEGIN")
        binding = dml.bind_transaction(self.writer.cursor(), self.activation, provider)
        self.capture.register(binding)
        return binding

    def commit(self, binding):
        dml.transaction_complete(self.writer.cursor(), self.activation, binding)
        self.writer.execute("COMMIT")

    def test_multirow_nested_trigger_duplicate_savepoint_and_cascade(self):
        b = self.begin()
        self.writer.execute("INSERT INTO payment_orders VALUES(1,'local-only',1),(2,'local-only',1)")
        self.writer.execute("UPDATE payment_orders SET value=value+1 WHERE id=1")
        self.writer.execute("INSERT INTO payment_orders VALUES(1,'local-only',9) ON CONFLICT DO NOTHING")
        self.writer.execute("UPDATE payment_orders SET value=99 WHERE id=99")
        self.writer.execute("SAVEPOINT entitlement")
        self.writer.execute("UPDATE payment_orders SET value=88")
        self.writer.execute("INSERT INTO payment_orders VALUES(3,'local-only',3)")
        self.writer.execute("ROLLBACK TO SAVEPOINT entitlement")
        self.writer.execute("RELEASE SAVEPOINT entitlement")
        self.writer.execute("DELETE FROM payment_orders WHERE id=2")
        self.commit(b)
        result = self.capture.finish(admission_closed=True)
        self.assertEqual(result["status"], "CAPTURE_COMPLETE_NOT_TERMINAL")
        self.assertEqual(result["write_mutations_by_table"],
                         {"payment_orders": 4, "payment_events": 3})
        self.assertEqual(dml.read_journal(self.path, **self.capture.context), result)
        self.assertNotIn("local-only", self.path.read_text())

    def test_outer_rollback_delivers_no_rows(self):
        b = self.begin()
        self.writer.execute("INSERT INTO payment_orders VALUES(1,'local-only',1)")
        self.writer.execute("ROLLBACK")
        self.capture.rolled_back(b)
        self.assertEqual(self.capture.finish(admission_closed=True)["write_mutations_by_table"], {})

    def test_business_mapping_rows_preserve_binding_and_cursor_results(self):
        # Import only inside the explicitly enabled local PG fixture; db must
        # not bootstrap workspace SQLite or inherit a supplied database URL.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
        with mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql:///noteai_local?host=/var/run/postgresql",
            "PYTHON_DOTENV_DISABLED": "1",
        }, clear=True):
            import db

        self.writer.close()
        self.writer = psycopg.connect(**CONNECT, autocommit=True, row_factory=db._compat_row_factory)
        self.writer.execute("BEGIN")
        with self.writer.cursor() as business:
            business.execute("SELECT 17 AS marker")
            binding = dml.bind_transaction(business, self.activation, "wechatpay_direct")
            self.capture.register(binding)
            self.assertIsInstance(binding["pid"], int)
            self.assertTrue(binding["txid"].isdigit())
            self.assertEqual(business.fetchone()["marker"], 17)
            self.writer.execute("INSERT INTO payment_orders VALUES(1,'local-only',1)")
            business.execute("SELECT 29 AS marker")
            dml.transaction_complete(business, self.activation, binding)
            self.assertEqual(business.fetchone()["marker"], 29)
        self.writer.execute("COMMIT")
        self.assertIs(self.writer.row_factory, db._compat_row_factory)
        result = self.capture.finish(admission_closed=True)
        self.assertEqual(result["write_mutations_by_table"], {"payment_orders": 1, "payment_events": 1})
        self.assertEqual(dml.read_journal(self.path, **self.capture.context), result)

    def test_real_payment_event_insert_bind_duplicate_and_savepoint_by_event_hash(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
        with mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql:///noteai_local?host=/var/run/postgresql",
            "PYTHON_DOTENV_DISABLED": "1",
        }, clear=True):
            import db
            import payment_contract as payment

        # Exercise the real event SQL against its original PG schema. The two
        # referenced tables are only FK fixtures; this is not a paid-order test.
        self.capture.handle.close()
        for statement in dml.removal_sql(list(self.targets)):
            self.owner.execute(statement)
        self.owner.execute("DROP TABLE payment_events,payment_orders CASCADE")
        self.owner.execute("DROP TABLE IF EXISTS payment_refunds CASCADE")
        self.owner.execute("CREATE TABLE payment_orders(id text primary key)")
        self.owner.execute("CREATE TABLE payment_refunds(id text primary key)")
        migration = (Path(db.__file__).parent / "migrations/postgres/0014_payment_execution_contract.sql").read_text()
        event_schema = migration.split("CREATE TABLE IF NOT EXISTS payment_events (", 1)[1].split(
            "CREATE INDEX IF NOT EXISTS idx_payment_events_state", 1
        )[0]
        self.owner.execute("CREATE TABLE IF NOT EXISTS payment_events (" + event_schema)
        direct = (Path(db.__file__).parent / "migrations/postgres/0018_direct_payment_providers.sql").read_text()
        self.owner.execute("ALTER TABLE payment_events" + direct.split(
            "ALTER TABLE payment_events", 1
        )[1].split("CREATE OR REPLACE FUNCTION noteai_payment_refund_identity_guard_v1()", 1)[0])
        self.owner.execute(
            "CREATE TRIGGER noteai_payment_event_identity_v1 BEFORE UPDATE ON payment_events "
            "FOR EACH ROW EXECUTE FUNCTION noteai_payment_event_identity_guard_v1()"
        )
        order_id = str(uuid.uuid4())
        self.owner.execute("INSERT INTO payment_orders VALUES(%s)", (order_id,))
        event = payment.CallbackEvent(
            provider_event_id="synthetic-event", event_type="payment.succeeded",
            created_time=1788732000, prod_mode=False, app_id="synthetic-app",
            data={}, provider_name="wechatpay_direct",
        )
        event_hash = payment._hash("noteai-wechatpay_direct-event-id-v1", event.provider_event_id)
        self.targets = {"payment_events": ("provider_event_id_hash", event_hash)}
        for statement in dml.installation_sql(self.activation, self.targets):
            self.owner.execute(statement)
        self.listener.close()
        self.listener = psycopg.connect(**CONNECT, autocommit=True)
        self.path = Path(self.temp.name) / "event-dml.jsonl"
        self.capture = dml.CanaryCapture(
            self.listener, self.owner, activation=self.activation, targets=self.targets,
            provider="wechatpay_direct", journal=self.path,
        )
        self.writer.close()
        self.writer = psycopg.connect(**CONNECT, autocommit=True, row_factory=db._compat_row_factory)
        clock = "2026-09-07T14:00:00+00:00"
        for delivery in range(3):
            binding = self.begin()
            tx = db.Transaction(self.writer, postgres=True)
            if delivery == 2:
                tx.execute("SAVEPOINT duplicate_delivery")
            event_id, duplicate = payment._record_event(
                tx, event, b"synthetic-payload", "synthetic-signature", clock,
            )
            self.assertEqual(duplicate, delivery > 0)
            if delivery == 0:
                self.assertIsNone(tx.fetchone("SELECT order_id FROM payment_events WHERE id=?", (event_id,))["order_id"])
                payment._finish_event(
                    tx, event_id, state="processed", reason="local_fixture",
                    order_id=order_id, refund_id=None, clock=clock,
                )
            if delivery == 2:
                tx.execute("ROLLBACK TO SAVEPOINT duplicate_delivery")
                tx.execute("RELEASE SAVEPOINT duplicate_delivery")
            self.commit(binding)
        row = self.writer.execute("SELECT order_id,duplicate_delivery_count FROM payment_events").fetchone()
        self.assertEqual(row["order_id"], order_id)
        self.assertEqual(row["duplicate_delivery_count"], 1)
        result = self.capture.finish(admission_closed=True)
        self.assertEqual(result["write_mutations_by_table"], {"payment_events": 3})
        self.assertEqual(dml.read_journal(self.path, **self.capture.context), result)
        self.assertNotIn("synthetic-payload", self.path.read_text())

    def test_independent_api_and_payment_writer_processes(self):
        code = """
import json,sys,psycopg
from tools import collect_item31_canary_dml as d
c=psycopg.connect(host='/var/run/postgresql',dbname='noteai_local',user='postgres',autocommit=True)
c.execute('BEGIN')
b=d.bind_transaction(c.cursor(),sys.argv[1],sys.argv[2])
print(json.dumps(b),flush=True)
assert sys.stdin.readline().strip()=='admit'
c.execute("INSERT INTO payment_orders VALUES(%s,'local-only',1)",(int(sys.argv[3]),))
d.transaction_complete(c.cursor(),sys.argv[1],b)
c.execute('COMMIT')
c.close()
"""
        for number, provider in enumerate(["wechatpay_direct", "wechatpay_direct"], 1):
            child = subprocess.Popen([sys.executable, "-c", code, self.activation, provider, str(number)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True)
            try:
                self.capture.register(json.loads(child.stdout.readline()))
                _, error = child.communicate("admit\n", timeout=20)
                self.assertEqual(child.returncode, 0, error)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
        self.assertEqual(self.capture.finish(admission_closed=True)["write_mutations_by_table"],
                         {"payment_orders": 2, "payment_events": 2})

    def test_autocommit_or_changed_transaction_cannot_seal(self):
        with self.assertRaises(ValueError):
            dml.bind_transaction(self.writer.cursor(), self.activation, "alipay_direct")
        b = self.begin()
        self.writer.execute("COMMIT")
        self.writer.execute("BEGIN")
        with self.assertRaises(ValueError):
            dml.transaction_complete(self.writer.cursor(), self.activation, b)
        self.writer.execute("ROLLBACK")
        self.assertEqual(dml.read_journal(self.path, **self.capture.context)["status"], "UNKNOWN")

    def test_inflight_or_disconnect_is_unknown(self):
        self.begin()
        with self.assertRaisesRegex(ValueError, "in flight"):
            self.capture.finish(admission_closed=True)
        self.assertEqual(dml.read_journal(self.path, **self.capture.context)["status"], "UNKNOWN")

    def test_listener_loss_is_unknown(self):
        b = self.begin()
        self.commit(b)
        self.listener.close()
        with self.assertRaises(psycopg.Error):
            self.capture.finish(admission_closed=True)
        self.assertEqual(dml.read_journal(self.path, **self.capture.context)["status"], "UNKNOWN")

    def test_outside_canary_is_unknown(self):
        b = self.begin()
        self.writer.execute("INSERT INTO payment_orders VALUES(1,'wrong-object',1)")
        self.commit(b)
        with self.assertRaisesRegex(ValueError, "out-of-contract"):
            self.capture.finish(admission_closed=True)
        self.assertEqual(dml.read_journal(self.path, **self.capture.context)["status"], "UNKNOWN")

    def test_tail_fsync_failure_cannot_publish_complete(self):
        b = self.begin()
        self.writer.execute("ROLLBACK")
        self.capture.rolled_back(b)
        with mock.patch.object(dml.os, "fsync", side_effect=OSError("local injected failure")):
            with self.assertRaises(OSError):
                self.capture.finish(admission_closed=True)
        self.assertEqual(dml.read_journal(self.path, **self.capture.context)["status"], "UNKNOWN")

    def test_failed_fsync_and_unavailable_truncate_keep_tail_unpublished(self):
        b = self.begin()
        self.writer.execute("ROLLBACK")
        self.capture.rolled_back(b)
        original = self.capture.handle
        proxy = mock.Mock(wraps=original)
        proxy.truncate.side_effect = OSError("truncate unavailable")
        self.capture.handle = proxy
        with mock.patch.object(dml.os, "fsync", side_effect=OSError("fsync unavailable")):
            with self.assertRaises(OSError):
                self.capture.finish(admission_closed=True)
        self.capture.handle = original
        self.assertFalse(self.path.exists())
        partial = self.capture.incomplete_path
        self.assertEqual(json.loads(partial.read_text().splitlines()[-1])["kind"], "end")
        self.assertEqual(dml.read_journal(partial, **self.capture.context)["status"], "UNKNOWN")
        self.assertEqual(dml.read_journal(self.path, **self.capture.context)["status"], "UNKNOWN")

    def test_retained_binding_mismatch_is_unknown(self):
        b = self.begin()
        self.commit(b)
        self.capture.finish(admission_closed=True)
        records = [json.loads(x) for x in self.path.read_text().splitlines()]
        records[-2]["txid"] = "99999999"
        self.path.write_text("".join(json.dumps(x)+"\n" for x in records))
        self.assertEqual(dml.read_journal(self.path, **self.capture.context)["status"], "UNKNOWN")

    def test_retained_capture_cannot_be_rebound_or_follow_a_link(self):
        b = self.begin()
        self.commit(b)
        self.capture.finish(admission_closed=True)
        context = {**self.capture.context, "activation": str(uuid.uuid4())}
        self.assertEqual(dml.read_journal(self.path, **context)["status"], "UNKNOWN")
        linked = self.path.with_name("linked.jsonl")
        linked.symlink_to(self.path)
        self.assertEqual(dml.read_journal(linked, **self.capture.context)["status"], "UNKNOWN")
        with self.assertRaises(ValueError):
            self.capture.register({**b, "nonce": str(uuid.uuid4())})

    def test_wrong_notification_channel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "channel"):
            self.capture._consume(SimpleNamespace(channel="other", payload="{}", pid=1))


if __name__ == "__main__":
    unittest.main()
