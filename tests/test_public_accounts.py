"""Offline checks of the public route boundary and existing OTP transactions."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
_temp = tempfile.TemporaryDirectory()
os.environ["NOTEAI_SQLITE_PATH"] = str(Path(_temp.name) / "import.db")
db = importlib.import_module("db")
api = importlib.import_module("api")
security = importlib.import_module("account_security")
public = importlib.import_module("public_account")


class PublicAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "accounts.db"
        self.env = mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "NOTEAI_DEPLOYMENT_STAGE": "test",
            "NOTEAI_PUBLIC_ACCOUNT_ONLY": "1", "NOTEAI_OTP_MODE": "test",
            "NOTEAI_OTP_TEST_CODE": "246810",
            "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com,https://www.noteaipro.com",
        })
        self.env.start()
        db.init_db()
        self.client = TestClient(api.app, headers={"Origin": "https://noteaipro.com"})

    def tearDown(self):
        self.env.stop()
        db._DB_PATH = self.old_db
        self.temp.cleanup()

    def issue(self, purpose="register_phone", phone="13800138000"):
        result = self.client.post("/auth/verification/request", json={
            "channel": "phone", "destination": phone, "purpose": purpose,
        })
        self.assertEqual(result.status_code, 202, result.text)
        self.assertNotIn("246810", result.text)
        return result.json()["challenge_id"]

    def register(self, challenge, code="246810"):
        return self.client.post("/auth/register/otp", json={
            "phone": "13800138000", "challenge_id": challenge, "code": code,
            "contract_version": public.CONTRACT_VERSION, "privacy_accepted": True,
        })

    def test_register_login_me_logout_and_single_use(self):
        challenge = self.issue()
        result = self.register(challenge)
        self.assertEqual(result.status_code, 200, result.text)
        token = result.json()["token"]
        headers = {"Authorization": "Bearer " + token}
        me = self.client.get("/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json()["phone_verified"])
        self.assertEqual(me.json()["contract_version"], public.CONTRACT_VERSION)
        self.assertEqual(self.register(challenge).status_code, 400)
        acceptance = db.fetchone("SELECT * FROM user_contract_acceptances LIMIT 1")
        self.assertEqual(acceptance["cross_border_notice_acknowledged_at"], "")
        self.assertEqual(self.client.post("/auth/logout", json={}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
        challenge = self.issue("login_phone")
        login = self.client.post("/auth/login/otp", json={
            "phone": "13800138000", "challenge_id": challenge, "code": "246810",
        })
        self.assertEqual(login.status_code, 200, login.text)
        other = self.client.get("/auth/me", headers={"Authorization": "Bearer invalid"})
        self.assertEqual(other.status_code, 401)

    def test_every_unopened_route_rejected_before_handler(self):
        protected = [(method, route.path) for route in api.app.routes
                     for method in getattr(route, "methods", [])
                     if (method, route.path) not in public.ALLOWED_ROUTES]
        self.assertGreater(len(protected), 50)
        with mock.patch.object(db, "transaction", side_effect=AssertionError("unexpected DB")), \
             mock.patch.object(db, "fetchone", side_effect=AssertionError("unexpected DB")):
            for method, path in protected:
                with self.subTest(method=method, path=path):
                    response = self.client.request(method, path, content=b"{}", headers={"Content-Type": "application/json"})
                    self.assertEqual(response.status_code, 404)

    def test_origin_content_type_and_body_size_fail_closed(self):
        path = "/auth/register/otp"
        with mock.patch.object(db, "transaction", side_effect=AssertionError("unexpected DB")):
            self.assertEqual(self.client.post(path, json={}, headers={"Origin": "https://attacker.invalid"}).status_code, 403)
            self.assertEqual(self.client.post(path, content="phone=123").status_code, 415)
            self.assertEqual(self.client.post(path, content="x" * 8193, headers={"Content-Type": "application/json"}).status_code, 413)
            self.assertEqual(self.client.post("/auth/register/otp/", json={}).status_code, 404)
            self.assertEqual(self.client.post("/auth%2Fregister%2Fotp", json={}).status_code, 404)

    def test_unopened_otp_purpose_and_phone_less_registration_rejected(self):
        for channel, purpose in [("email", "verify_email"), ("phone", "password_reset"), ("phone", "bind_phone")]:
            result = self.client.post("/auth/verification/request", json={
                "channel": channel, "destination": "13800138000", "purpose": purpose,
            })
            self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.post("/auth/register", json={}).status_code, 404)
        self.assertEqual(self.client.post("/auth/register/otp", json={
            "challenge_id": "a", "code": "246810", "contract_version": public.CONTRACT_VERSION,
            "privacy_accepted": True,
        }).status_code, 422)

    def test_otp_wrong_attempts_persist_no_user_or_session_created(self):
        challenge = self.issue()
        for _ in range(5):
            self.assertEqual(self.register(challenge, "000000").status_code, 400)
        self.assertEqual(self.register(challenge).status_code, 400)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM users")["n"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM user_sessions")["n"], 0)

    def test_account_startup_skips_all_business_initialization(self):
        with mock.patch.object(api._private_storage, "configure_from_environment", side_effect=AssertionError("private storage")), \
             mock.patch.object(api, "_ensure_model_artifacts_once", side_effect=AssertionError("model")), \
             mock.patch.object(api._pm, "apply_versioned_baseline", side_effect=AssertionError("prompts")), \
             mock.patch.object(api, "stop_scheduler", side_effect=AssertionError("scheduler")):
            with TestClient(api.app) as client:
                self.assertEqual(client.get("/health/live").status_code, 200)
        with mock.patch.dict(os.environ, {"NOTEAI_DEPLOYMENT_STAGE": "production", "NOTEAI_OTP_MODE": "test"}):
            with self.assertRaises(RuntimeError):
                public.validate_startup(db)

    def test_user_agent_cannot_create_another_source_quota(self):
        from starlette.requests import Request
        first = Request({"type": "http", "headers": [(b"user-agent", b"one")], "client": ("192.0.2.1", 12)})
        second = Request({"type": "http", "headers": [(b"user-agent", b"two")], "client": ("192.0.2.1", 34)})
        self.assertEqual(api._auth_request_fingerprint(first), api._auth_request_fingerprint(second))




class PublicProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / 'product.db'
        self.env = mock.patch.dict(os.environ, {
            'DATABASE_URL':'', 'NOTEAI_DEPLOYMENT_STAGE':'test',
            'NOTEAI_PUBLIC_PRODUCT':'1', 'NOTEAI_PUBLIC_ACCOUNT_ONLY':'0',
            'NOTEAI_OTP_MODE':'test','NOTEAI_OTP_TEST_CODE':'246810',
            'NOTEAI_PUBLIC_ORIGINS':'https://noteaipro.com',
        })
        self.env.start()
        db.init_db()
        db.execute('UPDATE public_trial_budget SET enabled=1')
        import auth
        import public_product
        self.product = public_product
        self.user = auth.create_user('verified_trial','NotARealPassword!42',phone='+8613800138000',
            phone_verified=True,contract_version=public.PRODUCT_CONTRACT_VERSION,privacy_accepted=True)
        self.token = auth.create_token(self.user['id'])
        self.client = TestClient(api.app, headers={'Origin':'https://noteaipro.com',
            'Authorization':'Bearer '+self.token})
        self.marker = public_product._invocation.set(public_product.Invocation(self.user['id'],'trial-request-123'))

    def tearDown(self):
        self.product._invocation.reset(self.marker)
        self.env.stop()
        db._DB_PATH = self.old_db
        self.temp.cleanup()

    def payload(self):
        return {'model':'kimi-k2.6','max_tokens':100,'messages':[{'role':'user','content':'自有测试文本'}]}

    def test_free_plan_ownership_and_closed_routes(self):
        plan = self.client.get('/billing/plan')
        self.assertEqual(plan.status_code,200,plan.text)
        self.assertIn('12',plan.text)
        for method,path in [('POST','/payments/orders'),('POST','/billing/topup'),
                            ('GET','/notes/tracking'),('POST','/notes/track-url'),
                            ('GET','/admin'),('POST','/auth/register'),
                            ('POST','/quick-diagnose'),('GET','/notes/tracking/versions')]:
            with self.subTest(path=path):
                self.assertEqual(self.client.request(method,path,json={}).status_code,404)
        no_id = self.client.post('/generate/stream',json={'fact_source_policy':'skip'})
        self.assertEqual(no_id.status_code,400)
        denied_media = self.client.post('/analyze/stream',headers={'X-Request-ID':'media-test-123'},
            json={'fact_source_policy':'skip','cover_image':'image-not-allowed'})
        self.assertEqual(denied_media.status_code,422)
        self.assertEqual(self.client.get('/notes',headers={'Authorization':'Bearer invalid'}).status_code,401)

    def test_physical_call_reserves_before_transport_and_never_resets(self):
        import httpx
        seen=[]
        def upstream(request):
            seen.append(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0])
            return httpx.Response(200,json={'choices':[{'message':{'content':'真实传输由离线fixture代替'},'finish_reason':'stop'}]})
        with self.product.kimi_client(transport=httpx.MockTransport(upstream)) as client:
            client.post(self.product.ENDPOINT,json=self.payload())
        self.assertEqual(seen,[2590])
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls')[0],'responded')
        with self.assertRaises(Exception):
            db.execute('UPDATE public_trial_budget SET reserved_milli_cny=0')

    def test_unknown_stops_further_provider_requests(self):
        import httpx
        calls=[]
        def upstream(request):
            calls.append(1)
            raise httpx.ReadTimeout('synthetic disconnected request')
        with self.product.kimi_client(transport=httpx.MockTransport(upstream)) as client:
            with self.assertRaises(self.product.TrialProviderStopped): client.post(self.product.ENDPOINT,json=self.payload())
            with self.assertRaises(self.product.TrialProviderStopped): client.post(self.product.ENDPOINT,json=self.payload())
        self.assertEqual(len(calls),1)
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls')[0],'unknown')

    def test_budget_and_unapproved_provider_fail_before_transport(self):
        import httpx
        db.execute('UPDATE public_trial_budget SET reserved_milli_cny=49000')
        with self.product.kimi_client(transport=httpx.MockTransport(lambda _: self.fail('must not dispatch'))) as client:
            for url in [self.product.ENDPOINT, 'https://example.invalid/provider']:
                with self.assertRaises(self.product.TrialProviderStopped): client.post(url,json=self.payload())
        self.assertEqual(db.fetchone('SELECT COUNT(*) FROM public_trial_calls')[0],0)

    def test_partial_stream_is_unknown_and_preserves_reservation(self):
        import httpx
        with self.product.kimi_client(transport=httpx.MockTransport(lambda _: httpx.Response(
                200,text='data: {"choices":[]}\n\n'))) as client:
            with self.assertRaises(self.product.TrialProviderStopped):
                with client.stream('POST',self.product.ENDPOINT,json=self.payload()) as response:
                    list(response.iter_lines())
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls')[0],'unknown')
        self.assertEqual(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0],2590)

    def test_stream_done_releases_inflight_slot_but_not_cumulative_reserve(self):
        import httpx
        with self.product.kimi_client(transport=httpx.MockTransport(lambda _: httpx.Response(
                200,text='data: {"choices":[{"delta":{"content":"test"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'))) as client:
            with client.stream('POST',self.product.ENDPOINT,json=self.payload()) as response:
                list(response.iter_lines())
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls')[0],'responded')
        self.assertEqual(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0],2590)

    def test_invalid_response_is_persisted_unknown_and_cannot_complete(self):
        import httpx
        for value in [None, {}, {'choices':[1]}, {'choices':[{'message':{'content':'partial'},'finish_reason':'length'}]}]:
            self.product._invocation.get().failure=''
            with self.product.kimi_client(transport=httpx.MockTransport(lambda _: httpx.Response(200,json=value))) as client:
                with self.assertRaises(self.product.TrialProviderStopped):
                    client.post(self.product.ENDPOINT,json=self.payload())
            with self.assertRaises(self.product.TrialProviderStopped): self.product.assert_result_known()
        row=db.fetchone('SELECT state,http_status FROM public_trial_calls')
        self.assertEqual(tuple(row),('unknown',200))

    def test_parser_rejects_embedded_marker_error_and_missing_content(self):
        for body in [b'data: {"choices":[],"text":"data: [DONE]"}\n',
                     b'data: {"error":{"message":"synthetic"}}\ndata: [DONE]\n',
                     b'data: [DONE]\n']:
            parser=self.product._TerminalParser()
            with self.assertRaises(self.product.TrialProviderStopped):
                parser.feed(body); parser.finish()
        parser=self.product._TerminalParser()
        body=b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n'
        for char in body: parser.feed(bytes([char]))
        parser.finish(); self.assertTrue(parser.done)

    def test_result_write_failure_stops_completion_and_followup(self):
        import httpx
        transport=mock.Mock(return_value=httpx.Response(200,json={'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}))
        with self.product.kimi_client(transport=httpx.MockTransport(transport)) as client, \
             mock.patch.object(db,'execute',side_effect=RuntimeError('synthetic result write failure')):
            with self.assertRaises(self.product.TrialProviderStopped): client.post(self.product.ENDPOINT,json=self.payload())
            with self.assertRaises(self.product.TrialProviderStopped): client.post(self.product.ENDPOINT,json=self.payload())
        self.assertEqual(transport.call_count,1)
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls')[0],'dispatched')
        with self.assertRaises(self.product.TrialProviderStopped): self.product.assert_result_known()

    def test_account_consent_upgrade_is_explicit_and_domestic(self):
        db.execute('DELETE FROM user_contract_acceptances WHERE user_id=?',(self.user['id'],))
        self.assertEqual(self.client.get('/notes').status_code,403)
        self.assertEqual(self.client.post('/auth/contracts/accept',json={
            'contract_version':self.product.CONTRACT_VERSION,'privacy_accepted':False}).status_code,400)
        accepted=self.client.post('/auth/contracts/accept',json={
            'contract_version':self.product.CONTRACT_VERSION,'privacy_accepted':True})
        self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(db.fetchone('SELECT cross_border_notice_acknowledged_at FROM user_contract_acceptances')[0],'')
        self.assertEqual(self.client.get('/notes').status_code,200)

    def test_budget_exhaustion_closes_status(self):
        self.assertTrue(self.client.get('/public/status').json()['ai_open'])
        db.execute('UPDATE public_trial_budget SET reserved_milli_cny=49000')
        self.assertFalse(self.client.get('/public/status').json()['ai_open'])

    def test_semantic_failure_cannot_become_default_success(self):
        with mock.patch.object(api._mr,'call_semantic_sync',side_effect=lambda **kw: self.product.TrialProviderStopped('synthetic')):
            # A real raise sets the shared request failure even through old catches.
            def stopped(**kw): raise self.product.TrialProviderStopped('synthetic')
            with mock.patch.object(api._mr,'call_semantic_sync',side_effect=stopped):
                with self.assertRaises(self.product.TrialProviderStopped): api.compute_semantic_features('x','y')


@unittest.skipUnless(os.environ.get('NOTEAI_ISOLATED_SMS_PG16')=='1','dedicated isolated PG16 required')
class PublicProductPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_public_sms import SmsPostgresTests
        SmsPostgresTests.setUpClass()
        cls.pg=SmsPostgresTests

    def setUp(self):
        import public_product, auth, uuid
        self.product=public_product
        with self.pg.psycopg.connect(self.pg.owner_dsn,autocommit=True) as conn:
            conn.execute('TRUNCATE public_trial_calls,public_trial_budget')
            conn.execute("INSERT INTO public_trial_budget(id,limit_milli_cny,enabled) VALUES('website-free-product-20260912',50000,1)")
        self.env=mock.patch.dict(os.environ,{'DATABASE_URL':self.pg.app_dsn,'NOTEAI_PUBLIC_PRODUCT':'1'})
        self.env.start()
        self.user=auth.create_user('trial_pg_'+uuid.uuid4().hex[:12],'NotARealPassword!42')

    def tearDown(self): self.env.stop()

    def test_pg16_global_concurrency_and_ceiling_at_application_role(self):
        import threading, httpx, time
        from concurrent.futures import ThreadPoolExecutor
        seen=[]; lock=threading.Lock(); active=0; maximum=0
        def upstream(request):
            nonlocal active, maximum
            with lock: active+=1; maximum=max(maximum,active)
            time.sleep(.04)
            with lock: active-=1
            return httpx.Response(200,json={'choices':[{'message':{'content':'fixture'},'finish_reason':'stop'}]})
        def call(i):
            marker=self.product._invocation.set(self.product.Invocation(self.user['id'],f'pg-test-{i}'))
            try:
                with self.product.kimi_client(transport=httpx.MockTransport(upstream)) as client:
                    client.post(self.product.ENDPOINT,json={'model':'kimi-k2.6','max_tokens':100,'messages':[{'content':'test'}]})
                return True
            except self.product.TrialProviderStopped: return False
            finally: self.product._invocation.reset(marker)
        with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(call,range(25)))
        self.assertEqual(sum(results),19)
        self.assertLessEqual(maximum,2)
        self.assertEqual(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0],49210)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='responded'")[0],19)
        for sql in ['UPDATE public_trial_budget SET enabled=0','UPDATE public_trial_budget SET limit_milli_cny=100000','DELETE FROM public_trial_calls']:
            with self.assertRaises(self.pg.psycopg.errors.InsufficientPrivilege): db.execute(sql)


if __name__ == '__main__': unittest.main()
