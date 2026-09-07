"""Synthetic canary DML on a disposable, network-isolated PG16 Unix socket.

Run explicitly in the local test container, never with a supplied production DSN.
No provider, NoteAI app, dotenv or business database is loaded.
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
