import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
db = importlib.import_module("db")
oauth = importlib.import_module("wechat_jsapi")


class WechatJSAPIOAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "isolated.db"
        self.env = mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "NOTEAI_WECHAT_JSAPI_ENABLED": "1",
            "NOTEAI_WECHAT_SHARE_ENABLED": "0",
            "NOTEAI_WECHAT_SHARE_APP_ID": "wx0123456789abcdef",
            "NOTEAI_WECHAT_SHARE_APP_SECRET": "S" * 32,
        })
        self.env.start()
        db.init_db()
        self.clock = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
        self.app_id = "wx0123456789abcdef"
        self.user_id = "jsapi-user"
        self.token = "session-token-A-" + "a" * 32
        self.openid = "openid_test_0123456789"
        self.block_network = mock.patch.object(
            oauth.http.client, "HTTPSConnection", side_effect=AssertionError("unexpected network")
        )
        self.block_network.start()
        self.add_user(self.user_id, self.token)

    def tearDown(self):
        self.block_network.stop()
        self.env.stop()
        db._DB_PATH = self.old_db_path
        self.temp.cleanup()

    def add_user(self, uid, token):
        db.execute(
            "INSERT INTO users(id,username,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?)", (uid, uid, "testhash", "testsalt", self.clock.isoformat()),
        )
        self.add_session(uid, token)

    def add_session(self, uid, token):
        db.execute(
            "INSERT INTO user_sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (token, uid, self.clock.isoformat(),
             (self.clock + timedelta(hours=1)).isoformat()),
        )

    def begin(self, **overrides):
        values = dict(user_id=self.user_id, session_token=self.token,
                      product_kind="credit_package", product_id="starter",
                      idempotency_key="checkout-idempotency-001", origin="https://noteaipro.com",
                      payment_app_id=self.app_id, now=self.clock)
        values.update(overrides)
        return oauth.begin(**values)

    def complete(self, state, **overrides):
        values = dict(user_id=self.user_id, session_token=self.token, state=state,
                      code="temporarycode001", payment_app_id=self.app_id,
                      now=self.clock, transport=lambda config, code: {
                          "openid": self.openid, "access_token": "not-to-be-stored",
                          "refresh_token": "also-not-stored",
                      })
        values.update(overrides)
        return oauth.complete(**values)

    def resolve(self, state, **overrides):
        values = dict(user_id=self.user_id, session_token=self.token,
                      product_kind="credit_package", product_id="starter",
                      idempotency_key="checkout-idempotency-001", checkout_context=state,
                      payment_app_id=self.app_id, now=self.clock)
        values.update(overrides)
        return oauth.resolve(**values)

    def row(self, state):
        value = db.fetchone("SELECT * FROM payment_wechat_oauth_states WHERE state_hash=?",
                            (oauth._hash(state),))
        return dict(value) if value else None

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(oauth.JSAPIError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def test_config_reuses_credentials_without_enabling_share_or_token_mode(self):
        config = oauth.configuration(self.app_id)
        self.assertEqual(config.app_id, self.app_id)
        self.assertNotIn("S" * 32, repr(config))
        for name, value, code in (
            ("NOTEAI_WECHAT_JSAPI_ENABLED", "0", "WECHAT_JSAPI_DISABLED"),
            ("NOTEAI_WECHAT_SHARE_APP_SECRET", "", "WECHAT_JSAPI_NOT_CONFIGURED"),
        ):
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: value}):
                self.assert_error(code, oauth.configuration, self.app_id)
        self.assert_error("WECHAT_JSAPI_APP_ID_MISMATCH", oauth.configuration,
                          "wxfedcba9876543210")
        self.assert_error("WECHAT_JSAPI_APP_ID_MISMATCH", oauth.configuration, "微信appid")

    def test_authorize_url_is_fixed_scoped_encoded_and_state_is_only_hashed_in_db(self):
        result = self.begin()
        parsed = urlsplit(result["authorize_url"])
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path, parsed.fragment),
                         ("https", "open.weixin.qq.com", "/connect/oauth2/authorize", "wechat_redirect"))
        self.assertEqual(parse_qs(parsed.query), {
            "appid": [self.app_id], "redirect_uri": ["https://noteaipro.com/wechat-pay.html"],
            "response_type": ["code"], "scope": ["snsapi_base"], "state": [result["state"]],
        })
        row = self.row(result["state"])
        self.assertEqual(row["expires_at"], (self.clock + timedelta(seconds=300)).isoformat())
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["openid_ciphertext"])
        self.assertNotIn(result["state"], json.dumps(row))
        self.assertNotIn(self.token, json.dumps(row))
        self.assertNotIn("S" * 32, result["authorize_url"])

    def test_origin_rejects_port_path_query_fragment_userinfo_and_untrusted_host(self):
        for origin in ("http://noteaipro.com", "https://noteaipro.com/", "https://noteaipro.com:443",
                       "https://evil.example", "https://noteaipro.com@evil.example",
                       "https://noteaipro.com?q=1", "https://noteaipro.com#fragment"):
            with self.subTest(origin=origin):
                self.assert_error("WECHAT_JSAPI_ORIGIN_INVALID", self.begin, origin=origin)
        self.assertIn("www.noteaipro.com", self.begin(origin="https://www.noteaipro.com")["authorize_url"])

    def test_begin_requires_actual_live_session_and_writable_account(self):
        self.assert_error("WECHAT_JSAPI_SESSION_INVALID", self.begin, session_token="x" * 40)
        db.execute("UPDATE user_sessions SET expires_at=? WHERE token=?",
                   (self.clock.isoformat(), self.token))
        self.assert_error("WECHAT_JSAPI_SESSION_INVALID", self.begin)
        db.execute("UPDATE users SET deletion_requested_at=? WHERE id=?",
                   (self.clock.isoformat(), self.user_id))
        self.assert_error("WECHAT_JSAPI_ACCOUNT_NOT_WRITABLE", self.begin)

    def test_begin_limit_is_per_user_and_expired_secrets_are_deleted(self):
        states = [self.begin()["state"] for _ in range(oauth.MAX_BEGIN_PER_WINDOW)]
        self.assert_error("WECHAT_JSAPI_RATE_LIMITED", self.begin)
        self.add_user("second-user", "second-token-" + "b" * 32)
        self.begin(user_id="second-user", session_token="second-token-" + "b" * 32)
        self.complete(states[0])
        self.begin(now=self.clock + timedelta(seconds=301))
        self.assertIsNone(self.row(states[0]))
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_wechat_oauth_states "
                                    "WHERE user_id=?", (self.user_id,))["n"], 1)

    def test_success_encrypts_only_openid_and_repeated_complete_never_exchanges_again(self):
        state = self.begin()["state"]
        transport = mock.Mock(return_value={"openid": self.openid, "access_token": "forbidden-token"})
        self.assertEqual(self.complete(state, transport=transport), {"checkout_context": state})
        self.assertEqual(self.complete(state, code="different-code", transport=transport),
                         {"checkout_context": state})
        self.assertEqual(transport.call_count, 1)
        row = self.row(state)
        self.assertEqual(row["status"], "ready")
        self.assertNotIn(self.openid, json.dumps(row))
        self.assertNotIn("forbidden-token", json.dumps(row))
        self.assertNotIn("temporarycode001", json.dumps(row))
        self.assertEqual(self.resolve(state), self.openid)

    def test_context_cannot_cross_user_session_product_key_or_app(self):
        state = self.begin()["state"]
        self.complete(state)
        self.add_user("second-user", "second-token-" + "b" * 32)
        self.add_session(self.user_id, "another-token-" + "c" * 32)
        for overrides, code in (
            ({"user_id": "second-user", "session_token": "second-token-" + "b" * 32},
             "WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED"),
            ({"session_token": "another-token-" + "c" * 32}, "WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED"),
            ({"product_id": "creator"}, "WECHAT_JSAPI_CONTEXT_INVALID"),
            ({"idempotency_key": "another-idempotency-key"}, "WECHAT_JSAPI_CONTEXT_INVALID"),
            ({"payment_app_id": "wxfedcba9876543210"}, "WECHAT_JSAPI_APP_ID_MISMATCH"),
        ):
            with self.subTest(overrides=overrides):
                self.assert_error(code, self.resolve, state, **overrides)
        self.assert_error("WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED", self.resolve, state,
                          now=self.clock + timedelta(seconds=300))
        self.assertIsNone(self.row(state))

    def test_unknown_does_not_repeat_exchange_or_expose_exception(self):
        state = self.begin()["state"]
        transport = mock.Mock(side_effect=TimeoutError("S" * 32 + "private-upstream-url"))
        self.assert_error("WECHAT_JSAPI_OAUTH_UNKNOWN", self.complete, state, transport=transport)
        self.assertEqual(self.row(state)["status"], "unknown")
        self.assert_error("WECHAT_JSAPI_OAUTH_ALREADY_USED", self.complete, state, transport=transport)
        self.assertEqual(transport.call_count, 1)
        self.assertIsNone(self.row(state)["openid_ciphertext"])

    def test_expiry_is_checked_even_when_rls_skips_delete_and_invalid_dates_fail_closed(self):
        state = self.begin()["state"]
        self.complete(state)

        @contextmanager
        def skip_delete(*, write=False):
            with db.transaction(write=write) as tx:
                execute = tx.execute
                def filtered(sql, params=()):
                    if sql.startswith("DELETE FROM payment_wechat_oauth_states"):
                        return mock.Mock(rowcount=0)
                    return execute(sql, params)
                tx.execute = filtered
                yield tx

        self.assert_error("WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED", self.resolve, state,
                          now=self.clock + timedelta(seconds=300), transaction_factory=skip_delete)
        self.assertEqual(self.row(state)["status"], "ready")
        self.assertIsNotNone(self.row(state)["openid_ciphertext"])
        invalid_row = self.row(state)
        for expires_at in ("invalid-date", "2026-10-27T09:05:00", None):
            with self.subTest(expires_at=expires_at):
                invalid_row["expires_at"] = expires_at
                tx = mock.Mock(postgres=False)
                tx.fetchone.return_value = invalid_row
                self.assert_error("WECHAT_JSAPI_STATE_INVALID_OR_EXPIRED", oauth._bound_state,
                                  tx, state, self.user_id, invalid_row["session_hash"], self.app_id,
                                  self.clock)

    def test_rejected_or_malformed_response_never_creates_ready_context(self):
        for response, status, code in (
            ({"errcode": 40029, "errmsg": "must-not-escape"}, "failed", "WECHAT_JSAPI_OAUTH_REJECTED"),
            ({"openid": "contains spaces"}, "unknown", "WECHAT_JSAPI_OAUTH_UNKNOWN"),
            (["unexpected"], "unknown", "WECHAT_JSAPI_OAUTH_UNKNOWN"),
        ):
            with self.subTest(response=response):
                state = self.begin()["state"]
                self.assert_error(code, self.complete, state,
                                  transport=lambda config, value: response)
                self.assertEqual(self.row(state)["status"], status)
                self.assert_error("WECHAT_JSAPI_OAUTH_ALREADY_USED", self.complete, state)

    def test_claim_commits_before_transport_and_concurrent_reentry_cannot_exchange(self):
        state = self.begin()["state"]
        def transport(config, code):
            self.assertEqual(self.row(state)["status"], "exchanging")
            self.assert_error("WECHAT_JSAPI_OAUTH_IN_PROGRESS", self.complete, state,
                              transport=lambda config, code: self.fail("second exchange"))
            return {"openid": self.openid}
        self.complete(state, transport=transport)
        self.assertEqual(self.resolve(state), self.openid)

    def test_logout_during_transport_preserves_claim_and_no_payer_context(self):
        state = self.begin()["state"]
        def transport(config, code):
            db.execute("DELETE FROM user_sessions WHERE token=?", (self.token,))
            return {"openid": self.openid}
        self.assert_error("WECHAT_JSAPI_SESSION_INVALID", self.complete, state, transport=transport)
        self.assertEqual(self.row(state)["status"], "exchanging")
        self.assertIsNone(self.row(state)["openid_ciphertext"])
        self.add_session(self.user_id, self.token)
        self.assert_error("WECHAT_JSAPI_OAUTH_IN_PROGRESS", self.complete, state)

    def test_ciphertext_is_authenticated_to_immutable_purchase_context(self):
        first, second = self.begin()["state"], self.begin()["state"]
        self.complete(first)
        self.complete(second)
        row = self.row(first)
        # The DB independently blocks mutation of ready rows. Exercise the
        # decrypt boundary with an untrusted row, without weakening that guard.
        row["state_hash"] = self.row(second)["state_hash"]
        self.assert_error("WECHAT_JSAPI_CONTEXT_INVALID", oauth._decrypt, row,
                          oauth.configuration(self.app_id))

    def test_transport_fixed_tls_host_bounded_body_and_no_redirect_follow(self):
        self.block_network.stop()
        for status, body, expected in (
            (200, b'{"openid":"openid_test_0123456789"}', None),
            (302, b"", "WECHAT_JSAPI_OAUTH_UNKNOWN"),
            (200, b"x" * (oauth.MAX_RESPONSE_BYTES + 1), "WECHAT_JSAPI_OAUTH_UNKNOWN"),
        ):
            with self.subTest(status=status):
                response = mock.Mock(status=status)
                response.read.return_value = body
                connection = mock.Mock()
                connection.getresponse.return_value = response
                with mock.patch.object(oauth.http.client, "HTTPSConnection", return_value=connection) as create:
                    if expected:
                        self.assert_error(expected, oauth._request_openid,
                                          oauth.configuration(self.app_id), "temporarycode001")
                    else:
                        self.assertEqual(oauth._request_openid(oauth.configuration(self.app_id),
                                                              "temporarycode001")["openid"], self.openid)
                    self.assertEqual(create.call_args.args, ("api.weixin.qq.com", 443))
                    self.assertEqual(create.call_args.kwargs["timeout"], 4)
                    self.assertEqual(connection.request.call_args.args[0], "GET")
                    self.assertTrue(connection.request.call_args.args[1].startswith("/sns/oauth2/access_token?"))
                    response.read.assert_called_once_with(oauth.MAX_RESPONSE_BYTES + 1)
                    connection.request.assert_called_once()
                    connection.close.assert_called_once()
        self.block_network.start()


if __name__ == "__main__":
    unittest.main()
