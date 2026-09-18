"""Live-mode password reset contracts, with disposable DB and fake delivery."""
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from tests.test_public_sms import ENV, PNVS_ENV, db, security, sms


class PhonePasswordResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "reset.db"
        self.env = mock.patch.dict(os.environ, {**ENV, "DATABASE_URL": ""})
        self.env.start()
        db.init_db()
        db.execute("UPDATE auth_sms_budget SET enabled=1")

    def tearDown(self):
        self.env.stop()
        db._DB_PATH = self.old_path
        self.temp.cleanup()

    def issue(self, *, purpose="password_reset", phone="13800138000", source="192.0.2.1"):
        return security.issue_verification(
            channel="phone", destination=phone, purpose=purpose,
            requester_fingerprint=source,
        )

    def reserved(self):
        return db.fetchone("SELECT reserved_milli_cny FROM auth_sms_budget")[0]

    def test_live_reset_reserves_before_one_send_in_both_existing_modes(self):
        for index, mode in enumerate((ENV, PNVS_ENV)):
            with self.subTest(mode=mode["NOTEAI_OTP_MODE"]), mock.patch.dict(os.environ, mode):
                def send(config, **kwargs):
                    self.assertEqual(config.provider, mode["NOTEAI_OTP_MODE"])
                    self.assertEqual(self.reserved(), (index + 1) * sms.RESERVE_MILLI_CNY)
                    row = db.fetchone("SELECT * FROM auth_verification_challenges WHERE id=?",
                                      (kwargs["challenge_id"],))
                    self.assertEqual(row["purpose"], "password_reset")
                    self.assertIsNone(row["requested_by_user_id"])
                    self.assertNotEqual(row["code_hash"], kwargs["code"])
                    return sms.DeliveryResult("accepted", "OK", "synthetic-request", "synthetic-biz")
                with mock.patch.object(sms, "send", side_effect=send) as provider:
                    issued = self.issue(phone=f"1380013800{index}", source=f"192.0.2.{index + 1}")
                self.assertEqual(provider.call_count, 1)
                self.assertEqual(issued["delivery"], "sms")
                self.assertNotIn("code", issued)

    def test_register_login_reset_codes_cannot_be_used_for_other_purposes(self):
        purposes = ("register_phone", "login_phone", "password_reset")
        for index, purpose in enumerate(purposes):
            phone = f"1380013800{index}"
            captured = {}
            def send(config, **kwargs):
                captured.update(kwargs)
                return sms.DeliveryResult("accepted", "OK")
            with mock.patch.object(sms, "send", side_effect=send):
                issued = self.issue(purpose=purpose, phone=phone, source=f"192.0.2.{index + 1}")
            args = dict(challenge_id=issued["challenge_id"], code=captured["code"],
                        channel="phone", destination=phone)
            for wrong_purpose in set(purposes) - {purpose}:
                with self.subTest(issued=purpose, used=wrong_purpose), self.assertRaises(security.VerificationRejected):
                    security.consume_verification(**args, purpose=wrong_purpose)
            self.assertEqual(security.consume_verification(**args, purpose=purpose), "+86" + phone)
            with self.assertRaises(security.VerificationRejected):
                security.consume_verification(**args, purpose=purpose)

    def test_unknown_reset_keeps_reservation_and_never_resends(self):
        captured = {}
        def send(config, **kwargs):
            captured.update(kwargs)
            return sms.DeliveryResult("unknown", "TRANSPORT_UNKNOWN")
        with mock.patch.object(sms, "send", side_effect=send) as provider:
            issued = self.issue()
            self.assertEqual(issued["delivery"], "sms_unknown")
            args = dict(challenge_id=issued["challenge_id"], code=captured["code"],
                        channel="phone", destination="13800138000", purpose="password_reset")
            security.consume_verification(**args)
            with self.assertRaises(security.VerificationRejected):
                security.consume_verification(**args)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.reserved(), sms.RESERVE_MILLI_CNY)

    def test_reset_uses_existing_cross_purpose_contact_and_requester_limits(self):
        with mock.patch.object(sms, "send", return_value=sms.DeliveryResult("accepted", "OK")) as provider:
            self.issue(purpose="register_phone")
            for phone, source in (("13800138000", "192.0.2.2"), ("13800138001", "192.0.2.1")):
                with self.assertRaises(security.VerificationRejected):
                    self.issue(phone=phone, source=source)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.reserved(), sms.RESERVE_MILLI_CNY)

    def test_reset_budget_exhaustion_stops_before_dispatch(self):
        db.execute("UPDATE auth_sms_budget SET reserved_milli_cny=limit_milli_cny")
        with mock.patch.object(sms, "send") as provider:
            with self.assertRaises(security.VerificationDeliveryUnavailable):
                self.issue()
            provider.assert_not_called()
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM auth_verification_challenges")[0], 0)

    def test_live_email_and_phone_binding_remain_unavailable_without_writes(self):
        with mock.patch.object(sms, "send") as provider:
            for mode in (ENV, PNVS_ENV):
                with mock.patch.dict(os.environ, mode):
                    for purpose in ("verify_email", "password_reset"):
                        with self.subTest(mode=mode["NOTEAI_OTP_MODE"], purpose=purpose):
                            with self.assertRaisesRegex(security.VerificationDeliveryUnavailable, "邮箱验证码发送服务尚未启用"):
                                security.issue_verification(channel="email", destination="synthetic@example.invalid",
                                                            purpose=purpose, requester_fingerprint="192.0.2.1")
                    with self.assertRaises(security.VerificationDeliveryUnavailable):
                        self.issue(purpose="bind_phone")
            provider.assert_not_called()
        self.assertEqual(self.reserved(), 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM auth_verification_challenges")[0], 0)


class PublicPhonePasswordResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "public-reset.db"
        self.env = mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "NOTEAI_OTP_MODE": "test",
            "NOTEAI_OTP_TEST_CODE": "246810", "NOTEAI_DEPLOYMENT_STAGE": "test",
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_PUBLIC_ACCOUNT_ONLY": "1",
            "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com",
        })
        self.env.start()
        db.init_db()
        self.api = importlib.import_module("api")
        self.client = TestClient(self.api.app, headers={"Origin": "https://noteaipro.com"})
        self.provider = mock.patch.object(sms, "send", side_effect=AssertionError("unexpected provider dispatch"))
        self.provider.start()

    def tearDown(self):
        self.provider.stop()
        self.client.close()
        self.env.stop()
        db._DB_PATH = self.old_path
        self.temp.cleanup()

    def issue(self, purpose):
        response = self.client.post("/auth/verification/request", json={
            "channel": "phone", "destination": "13800138000", "purpose": purpose,
        })
        self.assertEqual(response.status_code, 202, response.text)
        self.assertNotIn("246810", response.text)
        return response.json()["challenge_id"]

    def register(self):
        response = self.client.post("/auth/register/otp", json={
            "phone": "13800138000", "challenge_id": self.issue("register_phone"),
            "code": "246810", "contract_version": self.api._public_account.contract_version(),
            "privacy_accepted": True,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def reset(self, challenge_id):
        return self.client.post("/auth/password-reset", json={
            "channel": "phone", "destination": "13800138000", "challenge_id": challenge_id,
            "code": "246810", "new_password": "Reset!Password2026",
        })

    def test_otp_only_account_can_reset_relogin_and_request_deletion_with_known_password(self):
        session = self.register()
        old_headers = {"Authorization": "Bearer " + session["token"]}
        self.assertEqual(self.client.get("/auth/me", headers=old_headers).status_code, 200)
        self.assertEqual(self.reset(self.issue("password_reset")).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=old_headers).status_code, 401)
        login = self.client.post("/auth/login/otp", json={
            "phone": "13800138000", "challenge_id": self.issue("login_phone"), "code": "246810",
        })
        self.assertEqual(login.status_code, 200, login.text)
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        deletion = self.client.request("DELETE", "/account", headers=headers,
                                       json={"password": "Reset!Password2026"})
        self.assertEqual(deletion.status_code, 200, deletion.text)
        self.assertTrue(deletion.json()["ok"])
        self.assertIn("final_export", deletion.json())
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM user_sessions")[0], 0)

    def test_public_handlers_reject_cross_purpose_codes_without_consuming_them(self):
        session = self.register()
        headers = {"Authorization": "Bearer " + session["token"]}
        for purpose in ("register_phone", "login_phone"):
            challenge_id = self.issue(purpose)
            self.assertEqual(self.reset(challenge_id).status_code, 400)
            self.assertIsNone(db.fetchone("SELECT consumed_at FROM auth_verification_challenges WHERE id=?",
                                         (challenge_id,))[0])
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 200)
        reset_id = self.issue("password_reset")
        self.assertEqual(self.client.post("/auth/login/otp", json={
            "phone": "13800138000", "challenge_id": reset_id, "code": "246810",
        }).status_code, 401)
        self.assertEqual(self.client.post("/auth/register/otp", json={
            "phone": "13800138000", "challenge_id": reset_id, "code": "246810",
            "contract_version": self.api._public_account.contract_version(), "privacy_accepted": True,
        }).status_code, 400)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM users")[0], 1)
        self.assertEqual(self.reset(reset_id).status_code, 200)
        self.assertEqual(self.reset(reset_id).status_code, 400)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)

    def test_account_only_release_keeps_reset_closed_and_product_keeps_email_closed(self):
        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0"}):
            self.assertEqual(self.client.post("/auth/verification/request", json={
                "channel": "phone", "destination": "13800138000", "purpose": "password_reset",
            }).status_code, 400)
            self.assertEqual(self.reset("not-issued").status_code, 404)
        self.assertEqual(self.client.post("/auth/verification/request", json={
            "channel": "email", "destination": "synthetic@example.invalid", "purpose": "password_reset",
        }).status_code, 400)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM auth_verification_challenges")[0], 0)


if __name__ == "__main__":
    unittest.main()
