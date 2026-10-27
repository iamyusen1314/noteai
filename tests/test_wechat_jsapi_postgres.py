"""Opt-in JSAPI migration/role contracts on a new, private Unix-only PG cluster.

The runner must supply an empty disposable database, its owned 0700 socket
directory and an evidence directory. No default or production DSN is accepted.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("NOTEAI_JSAPI_MODEL_SOURCE_DIR", str(ROOT / "model")))
import db
import billing
import payment_contract as payment
import wechat_jsapi as oauth


APP_ID = "wx0123456789abcdef"
OPENID = "openid_synthetic_postgres_jsapi"
ROLES = ("noteai_app", "noteai_payment", "noteai_admin_runtime", "noteai_admin",
         "noteai_ai_worker", "noteai_ai_dispatcher", "noteai_xhs_tracking", "noteai_xhs_trends")
PAYMENT_TABLES = ("payment_orders", "payment_refunds", "payment_events", "payment_cash_ledger",
                  "payment_entitlement_ledger", "payment_credit_positions", "payment_credit_consumptions",
                  "payment_reconciliation_runs", "payment_reconciliation_items", "payment_settlement_summaries")


@unittest.skipUnless(os.environ.get("NOTEAI_RUN_JSAPI_POSTGRES_TEST") == "1",
                     "private disposable JSAPI PostgreSQL fixture is not enabled")
class WechatJsapiPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.rows import dict_row
        cls.psycopg = psycopg
        cls.url = os.environ.get("NOTEAI_TEST_POSTGRES_URL", "")
        info = psycopg.conninfo.conninfo_to_dict(cls.url)
        socket = Path(os.environ.get("NOTEAI_JSAPI_TEST_POSTGRES_SOCKET", "/invalid"))
        if (str(socket) != info.get("host") or not str(socket).startswith("/private/tmp/noteai-jsapi-pg-")
                or socket.stat().st_uid != os.getuid() or socket.stat().st_mode & 0o777 != 0o700
                or info.get("user") != "noteai_jsapi_fixture_owner" or info.get("password")
                or info.get("hostaddr") or not info.get("dbname", "").startswith("noteai_jsapi_")):
            raise RuntimeError("refusing a non-private JSAPI PostgreSQL fixture")
        cls.env = mock.patch.dict(os.environ, {"DATABASE_URL": cls.url, "PYTHON_DOTENV_DISABLED": "1"})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        cls.conn = psycopg.connect(cls.url, autocommit=True, row_factory=dict_row)
        cls.addClassCleanup(cls.conn.close)
        state = cls.conn.execute("SELECT current_database() AS db, inet_server_addr() AS ip, "
                                 "current_setting('listen_addresses') AS listening, "
                                 "current_setting('server_version_num')::int AS version").fetchone()
        if state["ip"] is not None or state["listening"] or not 160000 <= state["version"] < 170000:
            raise RuntimeError("fixture must be PostgreSQL 16 with TCP disabled")
        if cls.conn.execute("SELECT COUNT(*) AS n FROM pg_tables WHERE schemaname='public'").fetchone()["n"]:
            raise RuntimeError("fixture database is not empty")
        for role in ROLES:
            cls.conn.execute("CREATE ROLE " + role + " NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
            cls.conn.execute("GRANT USAGE ON SCHEMA public TO " + role)
        folder = tempfile.TemporaryDirectory(prefix="pg32-baseline-", dir=os.environ["NOTEAI_JSAPI_TEST_EVIDENCE_DIR"])
        cls.addClassCleanup(folder.cleanup)
        baseline = Path(folder.name)
        original = Path(os.environ.get("NOTEAI_JSAPI_MIGRATION_SOURCE_DIR", str(db._POSTGRES_MIGRATIONS_DIR)))
        cls.migration_sha256 = hashlib.sha256((original / "0032_wechat_jsapi.sql").read_bytes()).hexdigest()
        for source in original.glob("*.sql"):
            if source.name < "0032_wechat_jsapi.sql":
                shutil.copyfile(source, baseline / source.name)
        with mock.patch.object(db, "_POSTGRES_MIGRATIONS_DIR", baseline):
            db.apply_postgres_migrations()
        now = datetime.now(timezone.utc).isoformat()
        cls.legacy_id = str(uuid.uuid4())
        cls.conn.execute("INSERT INTO users(id,username,password_hash,password_salt,created_at) VALUES(%s,%s,'fixture','fixture',%s)",
                         ("legacy-native-user", "legacy_native_user", now))
        cls.conn.execute(
            "INSERT INTO payment_orders(id,user_id,subject_hash,product_kind,product_id,catalog_version,amount_fen,"
            "currency,provider,provider_mode,merchant_order_no,app_id_hash,idempotency_key_hash,request_hash,"
            "payment_status,entitlement_status,refund_status,refunded_fen,refund_count,created_at,updated_at) "
            "VALUES(%s,'legacy-native-user',%s,'credit_package','starter',%s,1200,'CNY','wechatpay_direct','live',"
            "%s,%s,%s,%s,'pending','pending','none',0,0,%s,%s)",
            (cls.legacy_id, payment._subject_hash("legacy-native-user"), payment.CATALOG_VERSION,
             uuid.uuid4().hex, payment._app_id_hash(APP_ID, "wechatpay_direct"), "1" * 64, "2" * 64, now, now),
        )
        cls.legacy_before = cls.conn.execute("SELECT * FROM payment_orders WHERE id=%s", (cls.legacy_id,)).fetchone()
        # Prove 0032 removes default grants to other runtime roles.
        cls.conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO noteai_payment,noteai_admin_runtime")
        with mock.patch.object(db, "_POSTGRES_MIGRATIONS_DIR", original):
            cls.applied = db.apply_postgres_migrations()
            cls.second_apply = db.apply_postgres_migrations()
        grants = [
            "GRANT SELECT,INSERT ON payment_orders TO noteai_app",
            "GRANT UPDATE(provider_payment_id,payment_status,updated_at,terminal_at) ON payment_orders TO noteai_app",
            "GRANT SELECT ON users,user_sessions TO noteai_app",
            "GRANT UPDATE(nickname) ON users TO noteai_app",
            "GRANT SELECT ON " + ",".join(PAYMENT_TABLES) + " TO noteai_payment",
            "GRANT UPDATE(provider_payment_id,payment_status,entitlement_status,entitlement_ref,refund_status,refunded_fen,refund_count,updated_at,succeeded_at,terminal_at) ON payment_orders TO noteai_payment",
            "GRANT INSERT ON payment_refunds,payment_events,payment_cash_ledger,payment_entitlement_ledger,payment_credit_positions TO noteai_payment",
            "GRANT UPDATE(provider_refund_id,provider_submitted_at,status,updated_at,terminal_at) ON payment_refunds TO noteai_payment",
            "GRANT UPDATE(processing_state,reason_code,order_id,refund_id,processed_at,duplicate_delivery_count) ON payment_events TO noteai_payment",
            "GRANT UPDATE(user_id,remaining_milli,state,updated_at) ON payment_credit_positions TO noteai_payment",
            "GRANT SELECT(id,deletion_requested_at) ON users TO noteai_payment",
            "GRANT SELECT(id,user_id,tier,started_at,is_active),INSERT ON subscriptions TO noteai_payment",
            "GRANT UPDATE(is_active) ON subscriptions TO noteai_payment",
            "GRANT SELECT(user_id,balance,total_purchased),INSERT ON credits TO noteai_payment",
            "GRANT UPDATE(balance,total_purchased,updated_at) ON credits TO noteai_payment",
            "GRANT INSERT ON credit_transactions TO noteai_payment",
            "GRANT SELECT(user_id,recorded_at,credits_used,source) ON usage_records TO noteai_payment",
        ]
        for statement in grants:
            cls.conn.execute(statement)

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"NOTEAI_WECHAT_JSAPI_ENABLED": "1",
            "NOTEAI_WECHAT_SHARE_APP_ID": APP_ID, "NOTEAI_WECHAT_SHARE_APP_SECRET": "S" * 32})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.now = datetime.now(timezone.utc)
        self.uid, self.other = str(uuid.uuid4()), str(uuid.uuid4())
        self.token, self.other_token = "fixture-" + uuid.uuid4().hex, "fixture-" + uuid.uuid4().hex
        for uid, token in ((self.uid, self.token), (self.other, self.other_token)):
            self.conn.execute("INSERT INTO users(id,username,password_hash,password_salt,created_at) VALUES(%s,%s,'fixture','fixture',%s)",
                              (uid, uid, self.now.isoformat()))
            self.conn.execute("INSERT INTO user_sessions(token,user_id,created_at,expires_at) VALUES(%s,%s,%s,%s)",
                              (token, uid, self.now.isoformat(), (self.now + timedelta(hours=1)).isoformat()))

    @contextmanager
    def role(self, role):
        if role not in ROLES:
            raise AssertionError("unknown fixture role")
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url + "&options=" + quote("-c role=" + role)}):
            yield

    @contextmanager
    def sql_role(self, role, uid=None):
        with self.conn.transaction():
            self.conn.execute("SET LOCAL ROLE " + role)
            if uid is not None:
                self.conn.execute("SELECT set_config('noteai.jsapi_user_id',%s,true)", (uid,))
            yield self.conn

    def begin(self, **overrides):
        values = dict(user_id=self.uid, session_token=self.token, product_kind="credit_package",
                      product_id="starter", idempotency_key="fixture-jsapi-key-001", origin="https://noteaipro.com",
                      payment_app_id=APP_ID, now=self.now)
        values.update(overrides)
        with self.role("noteai_app"):
            return oauth.begin(**values)["state"]

    def complete(self, state, **overrides):
        values = dict(user_id=self.uid, session_token=self.token, state=state, code="fixture-code-001",
                      payment_app_id=APP_ID, now=self.now, transport=lambda config, code: {"openid": OPENID})
        values.update(overrides)
        with self.role("noteai_app"):
            return oauth.complete(**values)

    def resolve(self, state, **overrides):
        values = dict(user_id=self.uid, session_token=self.token, checkout_context=state,
                      product_kind="credit_package", product_id="starter", idempotency_key="fixture-jsapi-key-001",
                      payment_app_id=APP_ID, now=self.now)
        values.update(overrides)
        with self.role("noteai_app"):
            return oauth.resolve(**values)

    def jsapi_order(self):
        with self.role("noteai_app"):
            value = payment.create_order(self.uid, "credit_package", "starter", idempotency_key="fixture-order-" + uuid.uuid4().hex,
                app_id=APP_ID, prod_mode=True, provider_name="wechatpay_direct", now=self.now,
                wechat_jsapi_payer_hash=payment.wechat_jsapi_payer_identity_hash(APP_ID, OPENID))
        return dict(self.conn.execute("SELECT * FROM payment_orders WHERE id=%s", (value["id"],)).fetchone())

    def test_01_additive_migration_preserves_native_and_tracker_is_idempotent(self):
        self.assertEqual(self.applied, ["0032_wechat_jsapi.sql"])
        self.assertEqual(self.second_apply, [])
        after = self.conn.execute("SELECT * FROM payment_orders WHERE id=%s", (self.legacy_id,)).fetchone()
        added = set(after) - set(self.legacy_before)
        self.assertIn("wechat_jsapi_payer_hash", added)
        self.assertTrue(all(after[column] is None for column in added))
        self.assertEqual({key: after[key] for key in self.legacy_before}, self.legacy_before)
        actual = self.conn.execute("SELECT sha256 FROM schema_migrations WHERE version='0032_wechat_jsapi.sql'").fetchone()["sha256"]
        self.assertEqual(actual, self.migration_sha256)

    def test_02_app_order_insert_limited_updates_and_payer_immutability(self):
        row = self.jsapi_order()
        with self.role("noteai_app"):
            self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
            self.assertFalse(payment.admit_payment_submission(row["id"], now=self.now))
        query_clock = int(self.now.timestamp())
        with self.sql_role("noteai_app") as conn:
            conn.execute("UPDATE payment_orders SET wechat_jsapi_last_query_at=%s WHERE id=%s", (query_clock, row["id"]))
            conn.execute("UPDATE payment_orders SET wechat_jsapi_last_query_at=%s WHERE id=%s", (query_clock + 1, row["id"]))
        for value in (None, query_clock):
            with self.assertRaises(self.psycopg.errors.CheckViolation):
                with self.sql_role("noteai_app") as conn:
                    conn.execute("UPDATE payment_orders SET wechat_jsapi_last_query_at=%s WHERE id=%s", (value, row["id"]))
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            with self.sql_role("noteai_app") as conn:
                conn.execute("UPDATE payment_orders SET wechat_jsapi_last_query_at=%s WHERE id=%s", (query_clock, self.legacy_id))
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
            with self.sql_role("noteai_payment") as conn:
                conn.execute("UPDATE payment_orders SET wechat_jsapi_last_query_at=%s WHERE id=%s", (query_clock + 2, row["id"]))
        with self.assertRaises(self.psycopg.Error):
            with self.sql_role("noteai_app") as conn:
                conn.execute("UPDATE payment_orders SET payment_status='succeeded' WHERE id=%s", (row["id"],))
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
            with self.sql_role("noteai_app") as conn:
                conn.execute("UPDATE payment_orders SET wechat_jsapi_payer_hash=NULL WHERE id=%s", (row["id"],))
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            with self.conn.transaction():
                self.conn.execute("UPDATE payment_orders SET wechat_jsapi_payer_hash=NULL WHERE id=%s", (row["id"],))

    def test_03_oauth_acl_excludes_payment_admin_workers_and_public_functions(self):
        privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
        for role in ROLES:
            for privilege in privileges:
                allowed = self.conn.execute("SELECT has_table_privilege(%s,'payment_wechat_oauth_states',%s) AS ok", (role, privilege)).fetchone()["ok"]
                self.assertEqual(allowed, role == "noteai_app" and privilege in {"SELECT", "INSERT", "DELETE"}, (role, privilege))
        for column in ("status", "openid_ciphertext", "updated_at"):
            self.assertTrue(self.conn.execute("SELECT has_column_privilege('noteai_app','payment_wechat_oauth_states',%s,'UPDATE') AS ok", (column,)).fetchone()["ok"])
        self.assertFalse(self.conn.execute("SELECT has_column_privilege('noteai_app','payment_wechat_oauth_states','user_id','UPDATE') AS ok").fetchone()["ok"])
        for role in ROLES[1:]:
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                with self.sql_role(role) as conn:
                    conn.execute("SELECT * FROM payment_wechat_oauth_states")
        for function in ("noteai_payment_jsapi_identity_guard_v1()", "noteai_payment_wechat_oauth_guard_v1()"):
            self.assertFalse(self.conn.execute("SELECT has_function_privilege('noteai_app',%s,'EXECUTE') AS ok", (function,)).fetchone()["ok"])

    def test_04_oauth_rls_prevents_cross_user_reads_updates_inserts_and_cleanup(self):
        state = self.begin()
        with self.sql_role("noteai_app") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM payment_wechat_oauth_states").fetchone()["n"], 0)
        with self.sql_role("noteai_app", self.other) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM payment_wechat_oauth_states WHERE state_hash=%s", (oauth._hash(state),)).fetchone()["n"], 0)
            self.assertEqual(conn.execute("UPDATE payment_wechat_oauth_states SET status='exchanging' WHERE state_hash=%s", (oauth._hash(state),)).rowcount, 0)
            self.assertEqual(conn.execute("DELETE FROM payment_wechat_oauth_states WHERE state_hash=%s", (oauth._hash(state),)).rowcount, 0)
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
            with self.sql_role("noteai_app", self.other) as conn:
                conn.execute("INSERT INTO payment_wechat_oauth_states(state_hash,user_id,session_hash,app_id,product_kind,product_id,idempotency_key_hash,status,openid_ciphertext,created_at,expires_at,updated_at) VALUES(%s,%s,%s,%s,'credit_package','starter',%s,'pending',NULL,%s,%s,%s)",
                    ("f" * 64, self.uid, "e" * 64, APP_ID, "d" * 64, self.now.isoformat(),
                     (self.now + timedelta(seconds=300)).isoformat(), self.now.isoformat()))

    def test_05_real_app_oauth_encrypts_and_binds_session_product_key(self):
        state = self.begin()
        transport = mock.Mock(return_value={"openid": OPENID, "access_token": "fixture-not-stored"})
        self.complete(state, transport=transport)
        self.complete(state, transport=transport)
        transport.assert_called_once()
        self.assertEqual(self.resolve(state), OPENID)
        row = self.conn.execute("SELECT * FROM payment_wechat_oauth_states WHERE state_hash=%s", (oauth._hash(state),)).fetchone()
        for private in (OPENID, self.token, "fixture-not-stored", "S" * 32):
            self.assertNotIn(private, json.dumps(row))
        other_session = "fixture-second-session-" + uuid.uuid4().hex
        self.conn.execute("INSERT INTO user_sessions(token,user_id,created_at,expires_at) VALUES(%s,%s,%s,%s)",
                          (other_session, self.uid, self.now.isoformat(), (self.now + timedelta(hours=1)).isoformat()))
        for overrides in ({"session_token": other_session}, {"product_id": "creator"}, {"idempotency_key": "fixture-wrong-key"}):
            with self.subTest(overrides=overrides), self.assertRaises(oauth.JSAPIError):
                self.resolve(state, **overrides)

    def test_06_oauth_state_cas_ciphertext_check_and_immutable_context(self):
        state = self.begin()
        with self.sql_role("noteai_app", self.uid) as conn:
            self.assertEqual(conn.execute("UPDATE payment_wechat_oauth_states SET status='exchanging' WHERE state_hash=%s AND status='pending'", (oauth._hash(state),)).rowcount, 1)
            self.assertEqual(conn.execute("UPDATE payment_wechat_oauth_states SET status='exchanging' WHERE state_hash=%s AND status='pending'", (oauth._hash(state),)).rowcount, 0)
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            with self.sql_role("noteai_app", self.uid) as conn:
                conn.execute("UPDATE payment_wechat_oauth_states SET status='ready' WHERE state_hash=%s", (oauth._hash(state),))
        with self.sql_role("noteai_app", self.uid) as conn:
            conn.execute("UPDATE payment_wechat_oauth_states SET status='unknown' WHERE state_hash=%s", (oauth._hash(state),))
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            with self.sql_role("noteai_app", self.uid) as conn:
                conn.execute("UPDATE payment_wechat_oauth_states SET status='pending' WHERE state_hash=%s", (oauth._hash(state),))
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            with self.conn.transaction():
                self.conn.execute("UPDATE payment_wechat_oauth_states SET expires_at=%s WHERE state_hash=%s", ((self.now + timedelta(hours=1)).isoformat(), oauth._hash(state)))

    def test_07_expired_context_rejects_and_db_clock_cleanup_is_owner_scoped(self):
        past = self.now - timedelta(seconds=301)
        state = self.begin(now=past)
        self.complete(state, now=past)
        with self.sql_role("noteai_app", self.other) as conn:
            self.assertEqual(conn.execute("DELETE FROM payment_wechat_oauth_states WHERE state_hash=%s", (oauth._hash(state),)).rowcount, 0)
        with self.assertRaisesRegex(oauth.JSAPIError, "STATE_INVALID_OR_EXPIRED"):
            self.resolve(state)
        self.assertIsNone(self.conn.execute("SELECT * FROM payment_wechat_oauth_states WHERE state_hash=%s", (oauth._hash(state),)).fetchone())

    def test_08_payment_role_jsapi_duplicate_and_full_refund_keep_native_ledger_contract(self):
        row = self.jsapi_order()
        event = payment.CallbackEvent(
            provider_event_id="fixture-pg-event-" + uuid.uuid4().hex, event_type="payment.succeeded",
            created_time=int(self.now.timestamp()), prod_mode=True, app_id=APP_ID,
            data={"order_no": row["merchant_order_no"], "payment_id": "fixture-jsapi-pay-" + uuid.uuid4().hex, "pay_amt": "12.00"},
            provider_name="wechatpay_direct", wechat_trade_type="JSAPI", wechat_jsapi_payer_hash=row["wechat_jsapi_payer_hash"],
        )
        options = dict(expected_app_id=APP_ID, expected_provider_name="wechatpay_direct", expected_prod_mode=True, now=self.now)
        with self.role("noteai_payment"):
            self.assertTrue(payment.process_authenticated_callback(event, b'{"synthetic":"verified-payment"}', "synthetic-signature", **options)["ok"])
            self.assertTrue(payment.process_authenticated_callback(event, b'{"synthetic":"verified-payment"}', "synthetic-signature", **options)["duplicate"])
            prepared = payment.prepare_full_refund(row["id"], reason_code="customer_request", now=self.now)
            refund = dict(db.fetchone("SELECT * FROM payment_refunds WHERE id=?", (prepared["id"],)))
            self.assertTrue(payment.admit_refund_submission(refund["id"], now=self.now))
            refund_provider_id = "fixture-jsapi-refund-" + uuid.uuid4().hex
            payment.mark_refund_submission(refund["id"], payment.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"], provider_refund_id=refund_provider_id,
                status="pending", amount_fen=1200, response_verified=True, merchant_order_no=row["merchant_order_no"],
                provider_payment_id=event.data["payment_id"], provider_name="wechatpay_direct", app_id=APP_ID,
                prod_mode=True, provider_submitted_at=int(self.now.timestamp())), now=self.now)
            returned = payment.CallbackEvent(
                provider_event_id="fixture-pg-refund-event-" + uuid.uuid4().hex, event_type="refund.succeeded",
                created_time=int(self.now.timestamp()), prod_mode=True, app_id=APP_ID, provider_name="wechatpay_direct",
                data={"refund_order_no": refund["merchant_refund_no"], "refund_id": refund_provider_id,
                      "payment_id": event.data["payment_id"], "refund_amt": "12.00"})
            self.assertTrue(payment.process_authenticated_callback(returned, b'{"synthetic":"verified-refund"}', "synthetic-signature", **options)["ok"])
        final = self.conn.execute("SELECT * FROM payment_orders WHERE id=%s", (row["id"],)).fetchone()
        self.assertEqual((final["payment_status"], final["entitlement_status"], final["refund_status"]), ("succeeded", "reversed", "refunded"))
        self.assertEqual(final["wechat_jsapi_payer_hash"], row["wechat_jsapi_payer_hash"])
        entries = self.conn.execute("SELECT entry_type,COUNT(*) AS n FROM payment_cash_ledger WHERE order_id=%s GROUP BY entry_type", (row["id"],)).fetchall()
        self.assertTrue(all(entry["n"] == 1 for entry in entries))
        self.assertEqual(self.conn.execute("SELECT SUM(amount_fen) AS total FROM payment_cash_ledger WHERE order_id=%s", (row["id"],)).fetchone()["total"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM payment_entitlement_ledger WHERE order_id=%s AND entry_type='credit_grant'", (row["id"],)).fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
