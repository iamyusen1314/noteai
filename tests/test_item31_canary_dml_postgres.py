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
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid
from urllib.parse import quote, urlencode
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg

from tools import collect_item31_canary_dml as dml


ENABLED = os.environ.get("NOTEAI_LOCAL_PG16_CANARY_TEST") == "1"
CONNECT = dict(host="/var/run/postgresql", dbname="noteai_local", user="postgres")


def local_contract():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
    with mock.patch.dict(os.environ, {
        "DATABASE_URL": "postgresql:///noteai_local?host=/var/run/postgresql",
        "PYTHON_DOTENV_DISABLED": "1",
    }, clear=True):
        import db
        import payment_contract
    return db, payment_contract


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

    def test_writer_business_failure_rolls_back_before_commit(self):
        db, _ = local_contract()
        writer = dml.CanaryWriter(self.capture,
                                 lambda: psycopg.connect(**CONNECT, autocommit=True),
                                 db.Transaction)
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with writer(write=True) as tx:
                tx.execute("INSERT INTO payment_orders VALUES(1,'local-only',1)")
                raise RuntimeError("synthetic failure")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM payment_orders").fetchone()[0], 0)
        result = self.capture.finish(admission_closed=True)
        self.assertEqual(result["status"], "CAPTURE_COMPLETE_NOT_TERMINAL")
        self.assertEqual(result["write_mutations_by_table"], {})
        self.assertEqual(list(self.capture.terminal.values()), ["rollback"])

    def test_writer_rejects_borrowed_transaction_without_rollback_or_close(self):
        db, _ = local_contract()
        self.writer.execute("BEGIN")
        self.writer.execute("INSERT INTO payment_orders VALUES(1,'local-only',1)")
        writer = dml.CanaryWriter(self.capture, lambda: self.writer, db.Transaction)
        with self.assertRaisesRegex(ValueError, "fresh autocommit"):
            with writer(write=True):
                self.fail("borrowed transaction admitted")
        self.assertFalse(self.writer.closed)
        self.assertEqual(self.writer.info.transaction_status, psycopg.pq.TransactionStatus.INTRANS)
        self.assertEqual(self.writer.execute("SELECT count(*) FROM payment_orders").fetchone()[0], 1)
        self.assertEqual(self.capture.bindings, {})
        self.writer.execute("ROLLBACK")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM payment_orders").fetchone()[0], 0)

    def test_writer_lost_commit_ack_keeps_real_commit_unknown_and_stops_next_action(self):
        db, _ = local_contract()

        class LostCommitAck:
            def __init__(self):
                self.inner = psycopg.connect(**CONNECT, autocommit=True)

            def __getattr__(self, key):
                return getattr(self.inner, key)

            def commit(self):
                self.inner.commit()
                raise ConnectionError("synthetic lost commit ack")

        writer = dml.CanaryWriter(self.capture, LostCommitAck, db.Transaction)
        with self.assertRaises(ConnectionError):
            with writer(write=True) as tx:
                tx.execute("INSERT INTO payment_orders VALUES(1,'local-only',1)")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM payment_orders").fetchone()[0], 1)
        self.assertTrue(self.capture.broken)
        self.assertEqual(self.capture.terminal, {})
        with self.assertRaisesRegex(ValueError, "unavailable"):
            with writer(write=True):
                self.fail("next action admitted")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.capture.finish(admission_closed=True)
        self.assertFalse(self.path.exists())
        self.assertNotIn('"kind":"rollback"', self.capture.incomplete_path.read_text())
        self.assertEqual(dml.read_journal(self.capture.incomplete_path, **self.capture.context)["status"], "UNKNOWN")

    def test_writer_and_finish_serialize_before_sealing(self):
        db, _ = local_contract()
        writer = dml.CanaryWriter(self.capture,
                                 lambda: psycopg.connect(**CONNECT, autocommit=True),
                                 db.Transaction)
        waiting, finished = threading.Event(), threading.Event()
        results, errors = [], []

        def seal():
            waiting.set()
            try:
                results.append(self.capture.finish(admission_closed=True))
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        with writer(write=True) as tx:
            tx.execute("INSERT INTO payment_orders VALUES(1,'local-only',1)")
            thread = threading.Thread(target=seal)
            thread.start()
            self.assertTrue(waiting.wait(2))
            self.assertFalse(finished.wait(0.05))
        thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0]["write_mutations_by_table"], {"payment_orders": 1, "payment_events": 1})
        with self.assertRaisesRegex(ValueError, "unavailable"):
            with writer(write=True):
                self.fail("write after sealing")

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


@unittest.skipUnless(ENABLED, "explicit isolated PG16 container required")
class CanaryPaymentFlowPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db, cls.payment = local_contract()
        cls.admin = psycopg.connect(**CONNECT, autocommit=True)
        version, addr = cls.admin.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr()"
        ).fetchone()
        if not (160000 <= version < 170000 and addr is None):
            raise RuntimeError("isolated PG16 socket required")
        # Current migrations reference these runtime roles. They are inert
        # fixtures in the explicitly isolated cluster, not production accounts.
        for role in ("noteai_app", "noteai_admin_runtime"):
            attributes = cls.admin.execute(
                "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
                "rolinherit,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s",
                (role,),
            ).fetchone()
            if attributes is None:
                cls.admin.execute(psycopg.sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(psycopg.sql.Identifier(role)))
            elif attributes != (False,) * 7:
                raise RuntimeError("isolated fixture role attributes differ")
        cls.database = "noteai_item31_test_" + uuid.uuid4().hex
        cls.admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(cls.database)))
        cls.connection_args = {**CONNECT, "dbname": cls.database}
        # This fixed local socket is the only database route available in the
        # network-none test container. All migrations apply to this new DB only.
        with mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://postgres@/" + cls.database + "?host=/var/run/postgresql",
            "PYTHON_DOTENV_DISABLED": "1",
        }, clear=True):
            try:
                cls.db.apply_postgres_migrations()
            except BaseException:
                cls.admin.execute(psycopg.sql.SQL("DROP DATABASE {}").format(
                    psycopg.sql.Identifier(cls.database)
                ))
                cls.admin.close()
                raise

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(psycopg.sql.SQL("DROP DATABASE {}").format(psycopg.sql.Identifier(cls.database)))
        cls.admin.close()

    def connect(self):
        return psycopg.connect(**self.connection_args, autocommit=True,
                               row_factory=self.db._compat_row_factory)

    def test_connection_keeps_deployment_readonly_and_timeout_options(self):
        cases = [
            (None, "-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000", None, ("on", "5s", "1s")),
            ("-c default_transaction_read_only=off -c statement_timeout=7000 -c lock_timeout=2000", "-c default_transaction_read_only=on", None, ("off", "7s", "2s")),
            (None, "-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000", 1000, ("on", "1s", "1s")),
            (None, "", None, ("off", "0", "0")),
        ]
        for dsn_options, environment_options, health_timeout, expected in cases:
            query = {"host": "/var/run/postgresql"}
            if dsn_options is not None:
                query["options"] = dsn_options
            url = "postgresql://postgres@/" + self.database + "?" + urlencode(query, quote_via=quote)
            with self.subTest(expected=expected), mock.patch.dict(os.environ, {
                "DATABASE_URL": url, "PGOPTIONS": environment_options,
                "PYTHON_DOTENV_DISABLED": "1",
            }, clear=True):
                connection = self.db._get_postgres_conn(statement_timeout_ms=health_timeout)
                try:
                    self.assertFalse(connection.autocommit)
                    self.assertEqual(connection.info.transaction_status, psycopg.pq.TransactionStatus.IDLE)
                    actual = tuple(connection.execute("SHOW " + setting).fetchone()[0] for setting in
                                   ("default_transaction_read_only", "statement_timeout", "lock_timeout"))
                    self.assertEqual(actual, expected)
                    self.assertEqual(connection.execute("SHOW timezone").fetchone()[0], "UTC")
                    if expected[0] == "on":
                        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                            connection.execute("UPDATE payment_orders SET updated_at=updated_at WHERE false")
                    connection.rollback()
                finally:
                    connection.close()

    @contextmanager
    def stage(self, provider, targets):
        activation = str(uuid.uuid4())
        owner = psycopg.connect(**self.connection_args, autocommit=True)
        listener = psycopg.connect(**self.connection_args, autocommit=True)
        for statement in dml.installation_sql(activation, targets):
            owner.execute(statement)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary-dml.jsonl"
            capture = dml.CanaryCapture(listener, owner, activation=activation,
                                       targets=targets, provider=provider, journal=path)
            try:
                yield dml.CanaryWriter(capture, self.connect, self.db.Transaction)
                result = capture.finish(admission_closed=True)
                self.assertEqual(result["status"], "CAPTURE_COMPLETE_NOT_TERMINAL")
                self.assertEqual(dml.read_journal(path, **capture.context), result)
                self.stage_counts = result["write_mutations_by_table"]
            finally:
                capture.handle.close()
                listener.close()
                # Only this isolated fixture can automatically install/remove
                # DDL. Production predicates may not change under live writers.
                for statement in dml.removal_sql(list(targets)):
                    owner.execute(statement)
                owner.close()

    def test_both_direct_provider_payment_duplicate_and_unused_refund_transactions(self):
        payment = self.payment
        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        app_id = "synthetic_item31_app"
        with mock.patch.object(self.db, "get_conn", self.connect), mock.patch.dict(
            os.environ, {"DATABASE_URL": "postgresql:///noteai_local?host=/var/run/postgresql",
                         "PYTHON_DOTENV_DISABLED": "1"}, clear=True,
        ):
            for provider in ("wechatpay_direct", "alipay_direct"):
                with self.subTest(provider=provider):
                    uid = "local_item31_" + uuid.uuid4().hex
                    self.db.execute(
                        "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
                        "VALUES(?,?,?,'synthetic','synthetic',?)",
                        (uid, uid, uid + "@example.invalid", now.isoformat()),
                    )
                    payment.billing.get_subscription(uid)
                    key = "local_order_" + uuid.uuid4().hex
                    targets = {
                        "payment_orders": ("idempotency_key_hash", payment._hash("noteai-payment-idempotency-v1", key)),
                        "payment_events": ("provider_event_id_hash", "no-event-admitted"),
                        "credits": ("user_id", uid),
                        "credit_transactions": ("user_id", uid),
                        "subscriptions": ("user_id", "forbidden-subscription-write"),
                        "users": ("id", "forbidden-user-write"),
                        "usage_records": ("user_id", "forbidden-usage-write"),
                        "payment_reconciliation_runs": ("id", "no-reconciliation-admitted"),
                        "payment_reconciliation_items": ("id", "no-reconciliation-admitted"),
                        "payment_settlement_summaries": ("id", "no-settlement-admitted"),
                    }
                    for table in ("payment_cash_ledger", "payment_credit_positions",
                                  "payment_entitlement_ledger", "payment_refunds",
                                  "payment_credit_consumptions"):
                        targets[table] = ("order_id", "no-order-admitted")
                    with self.stage(provider, targets) as writer:
                        order = payment.create_order(
                            uid, "credit_package", "starter", idempotency_key=key,
                            app_id=app_id, provider_name=provider, now=now,
                            transaction_factory=writer,
                        )
                    self.assertEqual(self.stage_counts, {"payment_orders": 1})
                    targets["payment_orders"] = ("id", order["id"])
                    for table, (column, _) in list(targets.items()):
                        if column == "order_id":
                            targets[table] = (column, order["id"])
                    with self.stage(provider, targets) as writer:
                        self.assertTrue(payment.admit_payment_submission(order["id"], now=now, transaction_factory=writer))
                        self.assertFalse(payment.admit_payment_submission(order["id"], now=now, transaction_factory=writer))
                        payment.mark_payment_submission_unknown(order["id"], now=now, transaction_factory=writer)
                    self.assertEqual(self.stage_counts, {"payment_orders": 2})
                    row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (order["id"],))
                    event = payment.CallbackEvent(
                        provider_event_id="local_payment_" + uuid.uuid4().hex,
                        event_type="payment.succeeded", created_time=int(now.timestamp()),
                        prod_mode=False, app_id=app_id, provider_name=provider,
                        data={"id": provider + "_local_payment_id", "order_no": row["merchant_order_no"], "pay_amt": "12.00"},
                    )
                    targets["payment_events"] = ("provider_event_id_hash", payment._hash(
                        "noteai-" + provider + "-event-id-v1", event.provider_event_id,
                    ))
                    def callback(event, writer):
                        return payment.process_authenticated_callback(
                            event, b"synthetic-already-verified-event", "synthetic-signature",
                            expected_app_id=app_id, expected_provider_name=provider,
                            expected_prod_mode=False, now=now, transaction_factory=writer,
                        )
                    with self.stage(provider, targets) as writer:
                        self.assertTrue(callback(event, writer)["ok"])
                        self.assertTrue(callback(event, writer)["duplicate"])
                    self.assertEqual(self.stage_counts["payment_events"], 3)
                    self.assertEqual(self.stage_counts["payment_cash_ledger"], 1)
                    self.assertEqual(self.stage_counts["payment_entitlement_ledger"], 1)
                    targets["payment_events"] = ("provider_event_id_hash", "no-event-admitted")
                    with self.stage(provider, targets) as writer:
                        refund = payment.prepare_full_refund(order["id"], reason_code="customer_request", now=now, transaction_factory=writer)
                        refund_row = self.db.fetchone("SELECT * FROM payment_refunds WHERE id=?", (refund["id"],))
                        self.assertTrue(payment.admit_refund_submission(refund["id"], now=now, transaction_factory=writer))
                        self.assertFalse(payment.admit_refund_submission(refund["id"], now=now, transaction_factory=writer))
                        submitted = int(now.timestamp()) if provider == "wechatpay_direct" else None
                        payment.mark_refund_query_submission(payment.ProviderRefundResult(
                            merchant_refund_no=refund_row["merchant_refund_no"],
                            provider_refund_id=provider + "_local_refund_id", status="pending", amount_fen=1200,
                            response_verified=True, provider_name=provider, app_id=app_id,
                            merchant_order_no=row["merchant_order_no"], provider_payment_id=provider + "_local_payment_id",
                            provider_submitted_at=submitted, prod_mode=False,
                        ), now=now, transaction_factory=writer)
                    self.assertEqual(self.stage_counts, {"payment_refunds": 3, "payment_orders": 1})
                    refund_event = payment.CallbackEvent(
                        provider_event_id="local_refund_" + uuid.uuid4().hex,
                        event_type="refund.succeeded", created_time=int(now.timestamp()),
                        prod_mode=False, app_id=app_id, provider_name=provider,
                        data={"id": provider + "_local_refund_id", "refund_order_no": refund_row["merchant_refund_no"],
                              "payment_id": provider + "_local_payment_id", "refund_amt": "12.00", "provider_submitted_at": submitted},
                    )
                    targets["payment_events"] = ("provider_event_id_hash", payment._hash(
                        "noteai-" + provider + "-event-id-v1", refund_event.provider_event_id,
                    ))
                    with self.stage(provider, targets) as writer:
                        self.assertTrue(callback(refund_event, writer)["ok"])
                        self.assertTrue(callback(refund_event, writer)["duplicate"])
                    self.assertEqual(self.stage_counts["payment_events"], 3)
                    self.assertEqual(self.stage_counts["payment_cash_ledger"], 1)
                    final = self.db.fetchone("SELECT refund_status,entitlement_status,refunded_fen FROM payment_orders WHERE id=?", (order["id"],))
                    self.assertEqual(dict(final), {"refund_status": "refunded", "entitlement_status": "reversed", "refunded_fen": 1200})
                    cash = self.db.fetchone("SELECT sum(amount_fen) AS net,count(*) AS count FROM payment_cash_ledger WHERE order_id=?", (order["id"],))
                    self.assertEqual(dict(cash), {"net": 0, "count": 2})


if __name__ == "__main__":
    unittest.main()
