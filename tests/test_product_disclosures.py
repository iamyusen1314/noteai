"""Public disclosure API checks: synthetic SQLite and local capability mocks only."""
import os
from unittest import TestCase, mock

# Reuse the existing actual-ASGI fixture; never inherit shell provider settings.
with mock.patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": ""}, clear=True):
    from tests import test_product_integrity_api as fixture

api, db = fixture.api, fixture.db

SERVICES = [
    {"id": "claude", "name": "Claude Haiku / Sonnet", "group": "generation_models",
     "enabled": True, "business": ["diagnose", "generate", "chat"],
     "reason": "Synthetic published route; no supplier request"},
    {"id": "kimi", "name": "Kimi K2.6", "group": "generation_models",
     "enabled": False, "business": [], "reason": "Synthetic inactive route"},
    {"id": "doubao", "name": "Doubao Seed", "group": "media_models",
     "enabled": True, "business": ["video_audio_understanding"]},
    {"id": "amap", "name": "Amap", "group": "data_tools", "enabled": True},
]


class ProductDisclosureTests(TestCase):
    headers = fixture.ProductIntegrityApiTests.headers

    def setUp(self):
        clean = mock.patch.dict(os.environ, {
            "PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": "",
            "NOTEAI_DEPLOYMENT_STAGE": "test",
        }, clear=True)
        clean.start()
        self.addCleanup(clean.stop)
        fixture.ProductIntegrityApiTests.setUp(self)
        self.services = self.stack.enter_context(mock.patch.object(
            api._public_product, "public_services", return_value=SERVICES))
        self.stack.enter_context(mock.patch.object(
            api, "_payment_order_providers", return_value=["wechatpay_direct"]))
        self.stack.enter_context(mock.patch.object(
            api, "_payment_ordering_available", return_value=True))
        self.ready = self.stack.enter_context(mock.patch.object(
            api, "_payment_callback_runtime_ready", new=mock.AsyncMock(return_value=True)))
        self.network = self.stack.enter_context(mock.patch(
            "httpx.HTTPTransport.handle_request", side_effect=AssertionError("network prohibited")))

    def disclosure(self):
        response = self.client.get("/legal/contracts")
        self.assertEqual(response.status_code, 200, response.text)
        self.network.assert_not_called()
        return response.json()

    def test_public_disclosure_uses_current_routes_and_local_payment_readiness(self):
        value = self.disclosure()
        legacy = api._public_account.PRODUCT_CONTRACT_VERSION
        self.assertEqual(value["version"], legacy)
        self.assertEqual(value["acceptance_version"], legacy)
        self.assertEqual(value["disclosure_version"], "product-disclosure-2026-09-19")
        self.assertEqual(value["scope"], "formal_product")
        self.assertEqual(value["acceptance_record_policy"],
                         "historical_acceptances_unchanged_not_proof_of_current_runtime")
        self.assertIs(value["payment_enabled"], True)
        self.assertEqual(value["payment_status"], "available")
        self.assertEqual(value["payment_providers"], ["wechatpay_direct"])
        self.assertEqual(value["payment_status_source"], "local_payment_capabilities")
        self.ready.assert_awaited_once_with()
        privacy = value["privacy"]
        self.assertEqual(privacy["model_routes"], SERVICES[:3])
        self.assertIn("explicit_creator_preferences", privacy["ai_context_data"])
        self.assertIs(privacy["authentication_credentials_in_ai_context"], False)
        for misleading in ("submitted_creation_text_sent_to_kimi", "ai_provider",
                           "account_data_sent_to_ai_providers", "hosting"):
            self.assertNotIn(misleading, privacy)
        self.assertIn("Claude", value["cross_border"]["possible_route"])
        self.assertIs(value["cross_border"]["historical_acceptance_is_new_consent"], False)
        self.assertIs(value["cross_border"]["professional_confirmation_required"], False)

    def test_unavailable_and_unknown_are_distinct_without_provider_calls(self):
        for ready, error, enabled, status, providers in (
            (False, None, False, "unavailable", []),
            (True, RuntimeError("synthetic local readiness failure"), None, "unknown", None),
        ):
            with self.subTest(status=status):
                self.ready.reset_mock()
                self.ready.return_value, self.ready.side_effect = ready, error
                value = self.disclosure()
                self.assertIs(value["payment_enabled"], enabled)
                self.assertEqual(value["payment_status"], status)
                self.assertEqual(value["payment_providers"], providers)
                self.ready.assert_awaited_once_with()
                self.assertNotIn("synthetic local readiness failure", str(value))
                if status == "unknown":
                    self.assertIsNone(value["refund"]["policy"])

    def test_canary_never_advertises_formal_public_checkout(self):
        with mock.patch.dict(os.environ, {"NOTEAI_PAYMENT_CANARY_ENABLED": "1"}):
            for error in (None, RuntimeError("synthetic local readiness failure")):
                with self.subTest(local_ready=error is None):
                    self.ready.side_effect = error
                    value = self.disclosure()
                    self.assertIs(value["payment_enabled"], False)
                    self.assertEqual(value["payment_providers"], [])
                    self.assertEqual(value["payment_status"], "unavailable")

    def test_account_only_has_no_ai_or_payment_lookup(self):
        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0"}):
            value = self.disclosure()
        self.assertEqual(value["scope"], "website_and_accounts")
        self.assertEqual(value["version"], api._public_account.CONTRACT_VERSION)
        self.assertEqual(value["acceptance_version"], api._public_account.CONTRACT_VERSION)
        self.assertEqual(value["privacy"]["model_routes"], [])
        self.assertEqual(value["privacy"]["ai_context_data"], [])
        self.assertIsNone(value["cross_border"]["possible_route"])
        self.assertIs(value["payment_enabled"], False)
        self.assertEqual(value["payment_status"], "unavailable")
        self.assertEqual(value["payment_providers"], [])
        self.services.assert_not_called()
        self.ready.assert_not_awaited()

    def test_reading_disclosure_preserves_existing_acceptance_and_access(self):
        users = [dict(row) for row in db.fetchall("SELECT * FROM users ORDER BY id")]
        acceptances = [dict(row) for row in db.fetchall(
            "SELECT * FROM user_contract_acceptances ORDER BY user_id,contract_version")]
        raw_before = db._DB_PATH.read_bytes()
        self.disclosure()
        me = self.client.get("/auth/me", headers=self.headers())
        self.assertEqual(me.status_code, 200, me.text)
        self.assertIs(me.json()["contract_accepted"], True)
        self.assertEqual(me.json()["contract_version"], api._public_account.PRODUCT_CONTRACT_VERSION)
        # A normal consent-protected route still accepts the original record.
        growth = self.client.get("/profile/growth", headers=self.headers())
        self.assertEqual(growth.status_code, 200, growth.text)
        self.assertEqual(users, [dict(row) for row in db.fetchall("SELECT * FROM users ORDER BY id")])
        self.assertEqual(acceptances, [dict(row) for row in db.fetchall(
            "SELECT * FROM user_contract_acceptances ORDER BY user_id,contract_version")])
        self.assertEqual(raw_before, db._DB_PATH.read_bytes())

