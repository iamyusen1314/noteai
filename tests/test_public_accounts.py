"""Offline checks of the public route boundary and existing OTP transactions."""
import importlib
import json
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

    def test_native_capabilities_use_exact_owner_fence_and_orders_stay_readable(self):
        import time
        activation='00000000-0000-4000-8000-000000000031'
        key='item31-native-'+activation
        env={'NOTEAI_PAYMENT_ORDERING_ENABLED':'1','NOTEAI_PAYMENT_ORDER_PROVIDERS':'wechatpay_direct',
             'NOTEAI_PAYMENT_CANARY_ENABLED':'1','NOTEAI_PAYMENT_CANARY_ACTION':'create-payment',
             'NOTEAI_PAYMENT_CANARY_PROVIDER':'wechatpay_direct','NOTEAI_PAYMENT_CANARY_ACTIVATION_ID':activation,
             'NOTEAI_PAYMENT_CANARY_USER_ID_SHA256':api._item31_identity(self.user['id'],'payment-canary-user-v1'),
             'NOTEAI_PAYMENT_CANARY_SUBJECT_HASH':api._payment._subject_hash(self.user['id']),
             'NOTEAI_PAYMENT_CANARY_IDEMPOTENCY_KEY_SHA256':api._item31_identity(key,'noteai-item31-create-idempotency-v1'),
             'NOTEAI_PAYMENT_CANARY_AMOUNT_FEN':'1200','NOTEAI_PAYMENT_CANARY_OWNER_TEST_ASSERTION':'ITEM31-OWNER-CONTROLLED-TEST-ORDER',
             'NOTEAI_PAYMENT_CANARY_NOT_BEFORE_EPOCH':str(int(time.time())-5),
             'NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH':str(int(time.time())+300),
             'NOTEAI_RUNTIME_ROLE':'api','NOTEAI_DEPLOYMENT_STAGE':'production'}
        with mock.patch.dict(os.environ,env), mock.patch.object(api,'_payment_ordering_available',return_value=True), \
             mock.patch.object(api,'_payment_callback_runtime_ready',new=mock.AsyncMock(return_value=True)):
            value=self.client.get('/payments/capabilities').json()
            self.assertTrue(value['ordering_available'])
            self.assertEqual(value['canary_checkout']['idempotency_key'],key)
            self.assertEqual(value['canary_checkout']['amount_fen'],1200)
            self.assertFalse(TestClient(api.app).get('/payments/capabilities').json()['ordering_available'])
            with mock.patch.dict(os.environ,{'NOTEAI_PAYMENT_CANARY_USER_ID_SHA256':'0'*64}):
                self.assertFalse(self.client.get('/payments/capabilities').json()['ordering_available'])
            with mock.patch.dict(os.environ,{'NOTEAI_PAYMENT_CANARY_IDEMPOTENCY_KEY_SHA256':'0'*64}):
                self.assertIsNone(self.client.get('/payments/capabilities').json()['canary_checkout'])
            with mock.patch.dict(os.environ,{'NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH':'1'}):
                self.assertFalse(self.client.get('/payments/capabilities').json()['ordering_available'])
            self.assertFalse(self.client.get('/public/status').json()['payment_open'])
            with mock.patch.dict(os.environ,{'NOTEAI_PAYMENT_CANARY_ENABLED':'0'}):
                self.assertTrue(self.client.get('/public/status').json()['payment_open'])
                with mock.patch.object(api,'_payment_callback_runtime_ready',new=mock.AsyncMock(return_value=False)):
                    self.assertFalse(self.client.get('/public/status').json()['payment_open'])
        self.assertEqual(db.fetchone('SELECT count(*) FROM payment_orders')[0],0)
        # A local unpaid intent is sufficient to test read ownership; no provider
        # transport, paid status, balance or entitlement is invented.
        order=api._payment.create_order(self.user['id'],'credit_package','starter',
            idempotency_key=key,app_id='wxSyntheticApp01',prod_mode=True,provider_name='wechatpay_direct')
        with mock.patch.dict(os.environ,{'NOTEAI_PAYMENT_ORDERING_ENABLED':'0'}):
            detail=self.client.get('/payments/orders/'+order['id'])
            self.assertEqual(detail.status_code,200)
            recovered=self.client.get('/payments/orders',headers={'Idempotency-Key':key})
            self.assertEqual(recovered.json()['orders'][0]['id'],order['id'])
            self.assertEqual(self.client.get('/payments/orders',headers={'Idempotency-Key':'other-key-123'}).json()['orders'],[])
            self.assertEqual(TestClient(api.app).get('/payments/orders/'+order['id']).status_code,401)
            other=api._auth.create_user('other_native_reader','SyntheticPassword!42',phone='+8613800138001',
                phone_verified=True,contract_version=public.PRODUCT_CONTRACT_VERSION,privacy_accepted=True)
            other_client=TestClient(api.app,headers={'Origin':'https://noteaipro.com',
                'Authorization':'Bearer '+api._auth.create_token(other['id'])})
            self.assertEqual(other_client.get('/payments/orders/'+order['id']).status_code,404)
            self.assertEqual(other_client.get('/payments/orders',headers={'Idempotency-Key':key}).json()['orders'],[])


    def test_ark_screenshot_actual_parent_once_and_replay_refused(self):
        import base64, io, httpx, ark_media
        from PIL import Image
        self.metered_usage()
        db.execute('DELETE FROM usage_records')
        photo=io.BytesIO();Image.new('RGB',(300,200),'green').save(photo,'PNG')
        seen=[]
        def respond(request):
            value=json.loads(request.content);seen.append(value)
            self.assertEqual(base64.b64decode(value['messages'][0]['content'][0]['image_url']['url'].split(',')[1]),photo.getvalue())
            return httpx.Response(200,json={'model':ark_media.MODEL,
                'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':0}},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'type':'B','title':'','body':'','tags':[],'domain':'美食','cover_desc':'隔离测试绿色画面'})}}]})
        original=httpx.Client
        with mock.patch.dict(os.environ,{'NOTEAI_PUBLIC_MEDIA_ENABLED':'1','NOTEAI_ARK_API_KEY':'isolated-only'}), \
             mock.patch.object(api._private_storage,'object_backend_configured',return_value=True), \
             mock.patch.object(ark_media,'_client',side_effect=lambda **kw: original(transport=httpx.MockTransport(respond),trust_env=False)):
            headers={'X-Request-ID':'isolated-screenshot-001'}
            result=self.client.post('/extract-screenshot',headers=headers,json={'image_base64':base64.b64encode(photo.getvalue()).decode()})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['model_used'],ark_media.MODEL)
            again=self.client.post('/extract-screenshot',headers=headers,json={'image_base64':base64.b64encode(photo.getvalue()).decode()})
            self.assertEqual(again.status_code,409,again.text)
            self.assertEqual(len(seen),1)
            merge=self.client.post('/validate-ocr',headers={'X-Request-ID':'isolated-merge-001'},json={
                'ocr_results':[result.json()], 'ocr_request_ids':[result.json()['ocr_request_id']]})
            self.assertEqual(merge.status_code,200,merge.text)
            merge2=self.client.post('/validate-ocr',headers={'X-Request-ID':'isolated-merge-new'},json={
                'ocr_results':[result.json()], 'ocr_request_ids':[result.json()['ocr_request_id']]})
            self.assertEqual(merge2.status_code,409)
        self.assertEqual(db.fetchone('SELECT COUNT(*) FROM model_usage_records')[0],1)
        call=db.fetchone('SELECT * FROM public_trial_calls')
        parent=db.fetchone('SELECT * FROM usage_records WHERE id=?',(call['usage_record_id'],))
        self.assertEqual(parent['operation'],'screenshot')
        self.assertEqual(parent['cost_mode'],'actual')
        self.assertEqual(parent['model_calls'],1)
        self.assertGreater(parent['actual_model_cost_rmb'],0)
        self.assertIsNotNone(call['model_usage_record_id'])
        self.assertEqual(db.fetchone('SELECT COUNT(*) FROM idempotency_requests WHERE complete_applied=1')[0],2)

    def test_private_image_to_ark_owned_pixels_and_bounded_ocr_append(self):
        import base64, io, httpx, ark_media, private_storage
        from PIL import Image
        self.metered_usage()
        backend = private_storage.InMemoryObjectBackend()
        private_storage.configure_object_backend(backend, key_epoch='isolated-media-input')
        self.addCleanup(private_storage.reset_object_backend)
        photo = io.BytesIO(); Image.new('RGB', (300, 200), 'green').save(photo, 'PNG')
        stored = []
        def respond(request):
            value = json.loads(request.content)
            actual = base64.b64decode(value['messages'][0]['content'][0]['image_url']['url'].split(',')[1])
            self.assertEqual(actual, stored[0])
            return httpx.Response(200,json={'model':ark_media.MODEL,
                'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':0}},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'type':'B','title':'','body':'','tags':[],'domain':'美食','cover_desc':'真实上传的绿色画面，由隔离传输fixture返回'})}}]})
        original = httpx.Client
        with mock.patch.dict(os.environ,{'NOTEAI_PUBLIC_MEDIA_ENABLED':'1','NOTEAI_ARK_API_KEY':'isolated-only'}), \
             mock.patch.object(ark_media,'_client',side_effect=lambda **kw: original(transport=httpx.MockTransport(respond),trust_env=False)):
            tiny = io.BytesIO(); Image.new('RGB', (1, 1), 'green').save(tiny, 'PNG')
            rejected = self.client.post('/upload-image', files={'file':('tiny.png',tiny.getvalue(),'image/png')})
            self.assertEqual(rejected.status_code,422)
            uploaded = self.client.post('/upload-image', files={'file':('source.png',photo.getvalue(),'image/png')})
            self.assertEqual(uploaded.status_code,200,uploaded.text)
            ref = uploaded.json()['media_ref']
            stored.append(private_storage.load_media_bytes(ref,user_id=self.user['id'],purpose='image')[1])
            with self.assertRaises(private_storage.MediaReferenceUnavailable):
                private_storage.load_media_bytes(ref,user_id='another-user',purpose='image')
            first = self.client.post('/extract-screenshot',headers={'X-Request-ID':'owned-ocr-one'},json={'image_base64':ref})
            self.assertEqual(first.status_code,200,first.text)
            def merge(values):
                return self.client.post('/validate-ocr',headers={'X-Request-ID':'owned-merge-submit'},json={
                    'ocr_results':values,'ocr_request_ids':[v['ocr_request_id'] for v in values]})
            tampered = {**first.json(), 'cover_desc':'invented changed object'}
            self.assertEqual(merge([tampered]).status_code,409)
            self.assertEqual(merge([first.json()]).status_code,200)
            second = self.client.post('/extract-screenshot',headers={'X-Request-ID':'owned-ocr-two'},json={'image_base64':ref})
            self.assertEqual(second.status_code,200,second.text)
            appended = merge([first.json(),second.json()])
            self.assertEqual(appended.status_code,200,appended.text)
            self.assertEqual(merge([second.json()]).status_code,409)
            # A completed merge is not an original screenshot and cannot fund
            # recursive free model calls, even when its deterministic key is known.
            sources = tuple(sorted(['owned-ocr-one','owned-ocr-two']))
            import hashlib
            forged = {**appended.json(),'ocr_request_id':'ocr-merge-'+hashlib.sha256(json.dumps(sources).encode()).hexdigest()}
            self.assertEqual(merge([forged]).status_code,409)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls c JOIN model_usage_records m ON m.id=c.model_usage_record_id WHERE m.provider='doubao'")[0],2)


    def test_ark_cancel_joins_one_physical_call_before_refund(self):
        import asyncio, base64, io, threading, httpx, ark_media
        from PIL import Image
        self.metered_usage()
        entered, release=threading.Event(),threading.Event()
        photo=io.BytesIO();Image.new('RGB',(300,200),'green').save(photo,'PNG')
        calls=[]
        def respond(request):
            calls.append(request);entered.set()
            if not release.wait(5):raise AssertionError('isolated release not signaled')
            return httpx.Response(200,json={'model':ark_media.MODEL,
                'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':0}},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'type':'B','title':'','body':'','tags':[],'cover_desc':'隔离测试画面'})}}]})
        async def run():
            task=asyncio.create_task(api.extract_screenshot(api.ScreenshotExtractInput(image_base64=base64.b64encode(photo.getvalue()).decode()),self.user,'isolated-cancel-ocr'))
            try:
                for _ in range(400):
                    if entered.is_set():break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set())
                task.cancel();await asyncio.sleep(.02);task.cancel();await asyncio.sleep(.02)
                self.assertFalse(task.done())
                self.assertEqual(db.fetchone("SELECT refund_applied FROM idempotency_requests WHERE operation='screenshot'")[0],0)
            finally:release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        original=httpx.Client
        with mock.patch.dict(os.environ,{'NOTEAI_ARK_API_KEY':'isolated-only'}), \
             mock.patch.object(ark_media,'_client',side_effect=lambda **kw: original(transport=httpx.MockTransport(respond),trust_env=False)):
            asyncio.run(run())
        self.assertEqual(len(calls),1)
        row=db.fetchone("SELECT usage_id,status,refund_applied FROM idempotency_requests WHERE operation='screenshot'")
        self.assertEqual((row['status'],row['refund_applied']),('failed',1))
        usage=db.fetchone('SELECT actual_model_cost_rmb,model_calls FROM usage_records WHERE id=?',(row['usage_id'],))
        self.assertGreater(usage['actual_model_cost_rmb'],0)
        self.assertEqual(usage['model_calls'],1)

    def test_media_unauthorized_body_not_read_and_origin_still_required(self):
        import asyncio
        from public_account import PublicAccountBoundary
        reads=[];sent=[]
        async def forbidden(*args):raise AssertionError('handler reached')
        async def receive():reads.append(1);return {'type':'http.request','body':b'should-not-read','more_body':False}
        async def send(message):sent.append(message)
        scope={'type':'http','method':'POST','path':'/upload-video','raw_path':b'/upload-video',
               'headers':[(b'origin',b'https://noteaipro.com'),(b'content-type',b'multipart/form-data; boundary=offline')],
               'query_string':b'', 'server':('test',80),'client':('127.0.0.1',1000),'scheme':'http','http_version':'1.1'}
        with mock.patch.object(self.product,'media_enabled',return_value=True):
            asyncio.run(PublicAccountBoundary(forbidden)(scope,receive,send))
        self.assertEqual(reads,[])
        self.assertEqual(sent[0]['status'],401)

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

    def test_native_callback_has_exact_provider_boundary_without_browser_credentials(self):
        import httpx
        seen = []
        async def upstream(request):
            seen.append((str(request.url), await request.aread(), list(request.headers.raw)))
            return httpx.Response(401, json={"code": "SIGNATURE_INVALID"})
        original_client = httpx.AsyncClient
        env = {"NOTEAI_RUNTIME_ROLE": "api", "NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED": "1",
               "NOTEAI_PAYMENT_ORDERING_ENABLED": "1", "NOTEAI_PAYMENT_ORDER_PROVIDERS": "wechatpay_direct"}
        unsigned = TestClient(api.app)
        with mock.patch.dict(os.environ, env), mock.patch.object(api._httpx, "AsyncClient",
                side_effect=lambda **kw: original_client(transport=httpx.MockTransport(upstream), **kw)):
            response = unsigned.post("/payments/wechat/callback", content=b'{"raw": true}',
                headers={"Content-Type": "application/json", "Wechatpay-Nonce": "test-nonce"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][0], "http://127.0.0.1:8002/payments/wechat/callback")
            self.assertEqual(seen[0][1], b'{"raw": true}')
            for path in ("/payments/alipay/callback", "/payments/wechat/callback/", "/payments%2Fwechat%2Fcallback"):
                self.assertEqual(unsigned.post(path, content=b'{}').status_code, 404)
            self.assertEqual(unsigned.get("/payments/wechat/callback").status_code, 404)
            self.assertEqual(unsigned.post("/payments/wechat/callback",content=b'x'*32769).status_code, 413)
            self.assertEqual(len(seen), 1)
            self.assertEqual(unsigned.get("/payments/orders").status_code, 401)
            self.assertEqual(unsigned.post("/payments/orders",json={}).status_code, 403)
            self.assertEqual(self.client.post("/payments/orders",json={"provider":"alipay_direct"}).status_code, 403)
        self.assertEqual(unsigned.post("/payments/wechat/callback",content=b'{}').status_code, 404)

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
        db.execute("CREATE TRIGGER fail_result_write BEFORE UPDATE OF state ON public_trial_calls "
                   "BEGIN SELECT RAISE(ABORT, 'synthetic result write failure'); END")
        with self.product.kimi_client(transport=httpx.MockTransport(transport)) as client:
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

    def test_public_status_does_not_disclose_private_supplier_observations(self):
        import fact_enrichment
        with mock.patch.object(fact_enrichment,'_LAST_READ',{'amap':{'at':'private-time','http_requests':2}}):
            suppliers=self.client.get('/public/status').json()['suppliers']
        self.assertTrue(suppliers)
        for supplier in suppliers:
            self.assertFalse({'configured','latest','http_requests','cli_invocations','observation_scope'} & set(supplier))
        self.assertNotIn('private-time',str(suppliers))

    def metered_usage(self):
        import billing
        billing.clear_active_usage()
        self.addCleanup(billing.clear_active_usage)
        db.execute("UPDATE public_trial_budget SET policy_mode='owner_metered',reserved_milli_cny=49000")
        billing.record_free_usage(self.user['id'], 'score')
        return billing._ACTIVE_USAGE_ID.get()

    def claude_request(self):
        import model_router
        return model_router.ClaudeMessageRequest(model=model_router.CLAUDE_HAIKU,
            max_tokens=1200, messages=({'role':'user','content':'isolated fixture'},),
            operation_id=model_router._new_operation_id())

    def test_claude_operation_has_one_actual_usage_link_and_shared_slots(self):
        import model_router
        usage_id = self.metered_usage()
        request = self.claude_request()
        self.product.admit_claude_sync(request, b'{}')
        second = self.product._reserve_payload(self.payload(), 2590)
        with self.assertRaises(self.product._SlotsBusy):
            self.product._reserve_claude_once(self.claude_request(), b'{}')
        usage = {'input_tokens':100, 'output_tokens':20, 'cache_read_input_tokens':0,
                 'cache_creation_input_tokens':0}
        for _ in range(2):
            model_router._record_request_claude_usage(request, usage, request.model)
        self.product._record_response(request.operation_id, 200)
        self.product._record_response(second, None, not_dispatched=True)
        row = db.fetchone('SELECT * FROM public_trial_calls WHERE id=?', (request.operation_id,))
        self.assertEqual(row['usage_record_id'], usage_id)
        self.assertEqual(json.loads(row['provenance_json'])['operation_id'], request.operation_id)
        self.assertEqual(db.fetchone('SELECT COUNT(*) FROM model_usage_records')[0], 1)
        self.assertGreater(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0], 50000)

    def test_claude_repeated_cancel_waits_for_admission_then_records_no_dispatch(self):
        import asyncio, threading
        self.metered_usage()
        request = self.claude_request()
        entered, release = threading.Event(), threading.Event()
        reserve = self.product._reserve_claude_once
        def blocked(*args):
            entered.set()
            if not release.wait(3):
                raise AssertionError('test did not release transaction')
            return reserve(*args)
        async def run():
            task = asyncio.create_task(self.product.admit_claude(request, b'{}'))
            try:
                for _ in range(200):
                    if entered.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set())
                task.cancel()
                await asyncio.sleep(.01)
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        with mock.patch.object(self.product, '_reserve_claude_once', side_effect=blocked):
            asyncio.run(run())
        self.assertTrue(request.call_state['finalized'])
        self.assertNotIn('sent', request.call_state)
        row = db.fetchone('SELECT state,http_status FROM public_trial_calls WHERE id=?', (request.operation_id,))
        self.assertEqual(tuple(row), ('responded', None))

    def test_call_terminal_compare_and_set_never_overwrites_unknown(self):
        self.metered_usage()
        request = self.claude_request()
        self.product.admit_claude_sync(request, b'{}')
        self.product._record_response(request.operation_id, 200, unknown=True)
        self.product._record_response(request.operation_id, 200, unknown=True)
        with self.assertRaises(self.product.TrialProviderStopped):
            self.product._record_response(request.operation_id, 200)
        with self.assertRaises(self.product.TrialProviderStopped):
            self.product._record_response('missing-operation', 200)
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls')[0], 'unknown')

    def test_semantic_failure_or_invalid_scores_cannot_become_default_success(self):
        import model_router
        for raw in ('{}', '{"bad":"output"}'):
            self.product._invocation.get().failure = ''
            with mock.patch.object(model_router, 'call_semantic_sync', return_value=raw):
                with self.assertRaises(self.product.TrialProviderStopped):
                    api.compute_semantic_features('title', 'owner text')
        self.product._invocation.get().failure = ''
        def unavailable(**kwargs):
            raise model_router.ClaudeGatewayError('GATEWAY_NOT_CONFIGURED', fallback_safe=True)
        with mock.patch.object(model_router, 'call_semantic_sync', side_effect=unavailable):
            with self.assertRaisesRegex(self.product.TrialProviderStopped, 'GATEWAY_NOT_CONFIGURED'):
                api.compute_semantic_features('title', 'owner text')

    def test_semantic_prompt_keeps_the_complete_note(self):
        text = '素材' * 400 + '不得虚构的尾部事实'
        values = {key:.75 for key in api.SEMANTIC_FEATURE_COLS}
        with mock.patch.object(api._mr, 'call_semantic_sync', return_value=json.dumps(values)) as call:
            self.assertEqual(api.compute_semantic_features('title', text), values)
        self.assertIn(text, call.call_args.kwargs['user'])

    def test_necessary_expert_failure_drains_peers_and_never_arbitrates(self):
        import asyncio, model_router
        completed = []
        async def rejected(*args, **kwargs):
            raise model_router.ClaudeGatewayError('RATE_LIMIT', 429, fallback_safe=True)
        async def peer(*args, **kwargs):
            await asyncio.sleep(.01)
            completed.append(True)
            return {'role':'isolated expert','raw':'real fixture'}
        note = api.NoteInput(note_title='test',desc='owner fixture',domain='美食')
        with mock.patch.object(api,'_agent_content',side_effect=rejected), \
             mock.patch.object(api,'_agent_visual',side_effect=peer), \
             mock.patch.object(api,'_agent_growth',side_effect=peer), \
             mock.patch.object(api,'_agent_user',side_effect=peer), \
             mock.patch.object(api,'_agent_arbitrate') as arbitrate:
            with self.assertRaisesRegex(self.product.TrialProviderStopped,'RATE_LIMIT'):
                asyncio.run(api._run_five_agents(note,50,'B',[],{},None,None,{},{}))
        self.assertEqual(len(completed),3)
        arbitrate.assert_not_called()

    def test_metered_actual_usage_is_bound_once_without_resetting_old_reserve(self):
        import billing, model_router, httpx
        usage_id = self.metered_usage()
        self.product.record_fact_observation({'provider':'local_verified+amap','observed_at':'2026-09-13T06:00:00+00:00',
            'status':'partial','query':'PRIVATE QUERY','provider_response':'PRIVATE RESPONSE','facts':{'private':'value'},
            'calls':{'http_requests':2,'cli_invocations':0,'last_http_status':200,'partial_errors':['AMAP_BUSINESS_10003']}})
        result = {'choices':[{'message':{'content':'offline fixture'},'finish_reason':'stop'}],
                  'usage':{'prompt_tokens':100,'completion_tokens':20,'cached_tokens':10}}
        with self.product.kimi_client(transport=httpx.MockTransport(lambda _: httpx.Response(200,json=result))) as client:
            response = client.post(self.product.ENDPOINT,json=self.payload())
        call_id = response.extensions['noteai_call_id']
        # The bound operation survives an asynchronous caller losing its local context.
        billing.clear_active_usage()
        for _ in range(2):
            model_router._record_kimi_usage('kimi-k2.6', result['usage'], physical_call_id=call_id)
        row = db.fetchone('SELECT * FROM public_trial_calls WHERE id=?',(call_id,))
        self.assertEqual(row['usage_record_id'], usage_id)
        provenance=json.loads(row['provenance_json'])
        self.assertEqual(provenance['fact_observation']['provider'],'amap')
        self.assertEqual(provenance['fact_observation']['http_requests'],2)
        self.assertNotIn('PRIVATE',row['provenance_json'])
        self.assertTrue(row['model_usage_record_id'])
        self.assertEqual(db.fetchone('SELECT COUNT(*) FROM model_usage_records')[0],1)
        parent=db.fetchone('SELECT * FROM usage_records WHERE id=?',(usage_id,))
        self.assertEqual(parent['model_calls'],1)
        self.assertEqual(parent['cost_mode'],'actual')
        self.assertEqual(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0],51590)
        self.assertTrue(self.product.available())
        with self.assertRaises(self.product.TrialProviderStopped):
            model_router._record_kimi_usage('kimi-k2.6', {'prompt_tokens':101,'completion_tokens':20}, physical_call_id=call_id)
        self.assertEqual(db.fetchone('SELECT COUNT(*) FROM model_usage_records')[0],1)

    def test_metered_accounting_failure_is_explicit_and_new_invocation_cannot_replay(self):
        import billing, model_router, httpx
        self.metered_usage()
        with self.product.kimi_client(transport=httpx.MockTransport(lambda _: httpx.Response(200,json={
                'choices':[{'message':{'content':'offline fixture'},'finish_reason':'stop'}]}))) as client:
            response=client.post(self.product.ENDPOINT,json=self.payload())
        with mock.patch.object(billing,'_record_model_usage_for_usage_id',side_effect=RuntimeError('isolated DB failure')):
            with self.assertRaisesRegex(self.product.TrialProviderStopped,'ACCOUNTING_UNCONFIRMED'):
                model_router._record_kimi_usage('kimi-k2.6', {'prompt_tokens':100,'completion_tokens':20},
                    physical_call_id=response.extensions['noteai_call_id'])
        self.assertEqual(db.fetchone('SELECT state FROM public_trial_calls')[0],'responded')
        with self.assertRaisesRegex(self.product.TrialProviderStopped,'ACCOUNTING_UNCONFIRMED'):
            self.product.assert_result_known()
        with self.product.kimi_client(transport=httpx.MockTransport(lambda _: self.fail('same invocation must stop'))) as client:
            with self.assertRaisesRegex(self.product.TrialProviderStopped,'ACCOUNTING_UNCONFIRMED'):
                client.post(self.product.ENDPOINT,json=self.payload())
        current=self.product._invocation.set(self.product.Invocation(self.user['id'],'trial-request-123'))
        try:
            with self.product.kimi_client(transport=httpx.MockTransport(lambda _: self.fail('must not replay'))) as client:
                with self.assertRaisesRegex(self.product.TrialProviderStopped,'ACCOUNTING_UNCONFIRMED_NO_REPLAY'):
                    client.post(self.product.ENDPOINT,json=self.payload())
        finally:
            self.product._invocation.reset(current)

    def test_metered_requires_existing_owned_entitlement_operation(self):
        import billing, httpx
        billing.clear_active_usage()
        db.execute("UPDATE public_trial_budget SET policy_mode='owner_metered'")
        with self.product.kimi_client(transport=httpx.MockTransport(lambda _: self.fail('no owned operation'))) as client:
            with self.assertRaisesRegex(self.product.TrialProviderStopped,'REQUIRES_ENTITLEMENT_USAGE'):
                client.post(self.product.ENDPOINT,json=self.payload())
        self.assertEqual(db.fetchone('SELECT COUNT(*) FROM public_trial_calls')[0],0)

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
        with cls.pg.psycopg.connect(cls.pg.owner_dsn,autocommit=True) as conn:
            # Match the existing API-C runtime grants, independently read back
            # on September13. No owner credentials enter application execution.
            conn.execute('GRANT SELECT,INSERT,UPDATE ON subscriptions,usage_records TO noteai_app')
            conn.execute('GRANT SELECT,INSERT ON model_usage_records TO noteai_app')

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

    def test_pg16_admin_reads_only_noncontent_observation_columns(self):
        with self.pg.psycopg.connect(self.pg.owner_dsn,autocommit=True) as conn:
            conn.execute('SET ROLE noteai_admin_runtime')
            conn.execute('SELECT created_at,provenance_json FROM public_trial_calls').fetchall()
            for sql in ['SELECT user_id FROM public_trial_calls','SELECT request_hash FROM public_trial_calls',
                        "UPDATE public_trial_calls SET provenance_json='{}'"]:
                with self.assertRaises(self.pg.psycopg.errors.InsufficientPrivilege): conn.execute(sql)

    def test_pg16_claude_and_kimi_share_capacity_and_bind_actual_cost_once(self):
        import billing, model_router, httpx, time, threading
        from concurrent.futures import ThreadPoolExecutor
        with self.pg.psycopg.connect(self.pg.owner_dsn,autocommit=True) as conn:
            conn.execute("UPDATE public_trial_budget SET policy_mode='owner_metered',reserved_milli_cny=44030")
        active=0; maximum=0; lock=threading.Lock()
        def upstream(request):
            nonlocal active, maximum
            with lock: active+=1; maximum=max(maximum,active)
            time.sleep(.03)
            with lock: active-=1
            payload=json.loads(request.content)
            if payload['model'].startswith('claude'):
                return httpx.Response(200,json={'protocol_version':model_router._cgp.PROTOCOL_VERSION,
                    'text_blocks':['isolated actual output'],'model':payload['model'],'stop_reason':'end_turn',
                    'usage':{'input_tokens':100,'output_tokens':20,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}})
            return httpx.Response(200,json={'choices':[{'message':{'content':'isolated actual output'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':20}})
        def run(i):
            billing.clear_active_usage(); billing.record_free_usage(self.user['id'],'score')
            marker=self.product._invocation.set(self.product.Invocation(self.user['id'],f'pg-mixed-{i}'))
            try:
                if i % 2:
                    request=model_router.ClaudeMessageRequest(model=model_router.CLAUDE_HAIKU,max_tokens=1200,
                        messages=({'role':'user','content':'isolated'},),operation_id=model_router._new_operation_id())
                    transport=model_router.GatewayClaudeTransport(base_url='https://gateway.example.invalid',
                        key_id='isolated-key',secret='isolated-secret',http_transport=httpx.MockTransport(upstream))
                    result=transport.create_message_sync(request)
                    for _ in range(2): model_router._record_request_claude_usage(request,result.usage,result.model)
                    model_router._require_claude_completion(request,result)
                    model_router._finish_claude_call(request,complete=True)
                    return request.operation_id
                with self.product.kimi_client(transport=httpx.MockTransport(upstream)) as client:
                    result=client.post(self.product.ENDPOINT,json={'model':'kimi-k2.6','max_tokens':100,'messages':[{'content':'isolated'}]})
                call_id=result.extensions['noteai_call_id']
                for _ in range(2): model_router._record_kimi_usage('kimi-k2.6',result.json()['usage'],physical_call_id=call_id)
                return call_id
            finally:
                self.product._invocation.reset(marker); billing.clear_active_usage()
        with mock.patch.dict(os.environ,{'NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH':'isolated-config',
                                        'NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH':'isolated-epoch'}):
            with ThreadPoolExecutor(max_workers=4) as pool: calls=list(pool.map(run,range(4)))
        self.assertEqual(len(set(calls)),4)
        self.assertLessEqual(maximum,2)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='responded' AND model_usage_record_id IS NOT NULL")[0],4)
        self.assertEqual(db.fetchone('SELECT COUNT(DISTINCT model_usage_record_id) FROM public_trial_calls')[0],4)
        self.assertGreater(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0],50000)

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

    def test_pg16_metered_concurrent_calls_keep_exact_accounting_and_minimum_role(self):
        import billing, model_router, httpx, time, threading
        from concurrent.futures import ThreadPoolExecutor
        with self.pg.psycopg.connect(self.pg.owner_dsn,autocommit=True) as conn:
            conn.execute("UPDATE public_trial_budget SET policy_mode='owner_metered',reserved_milli_cny=44030")
        active=0; maximum=0; lock=threading.Lock()
        def upstream(request):
            nonlocal active, maximum
            with lock: active+=1; maximum=max(maximum,active)
            time.sleep(.03)
            with lock: active-=1
            return httpx.Response(200,json={'choices':[{'message':{'content':'offline fixture'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':20}})
        def run(i):
            billing.clear_active_usage()
            billing.record_free_usage(self.user['id'],'score')
            marker=self.product._invocation.set(self.product.Invocation(self.user['id'],f'pg-metered-{i}'))
            try:
                with self.product.kimi_client(transport=httpx.MockTransport(upstream)) as client:
                    response=client.post(self.product.ENDPOINT,json={'model':'kimi-k2.6','max_tokens':100,'messages':[{'content':'fixture'}]})
                call_id=response.extensions['noteai_call_id']
                for _ in range(2):
                    model_router._record_kimi_usage('kimi-k2.6',response.json()['usage'],physical_call_id=call_id)
                return call_id
            finally:
                self.product._invocation.reset(marker); billing.clear_active_usage()
        with ThreadPoolExecutor(max_workers=6) as pool: calls=list(pool.map(run,range(8)))
        self.assertEqual(len(set(calls)),8)
        self.assertLessEqual(maximum,2)
        self.assertEqual(db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0],44030+2590*8)
        self.assertEqual(db.fetchone('SELECT COUNT(DISTINCT model_usage_record_id) FROM public_trial_calls')[0],8)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls c JOIN usage_records u ON u.id=c.usage_record_id WHERE u.model_calls=1 AND u.cost_mode='actual'")[0],8)
        for sql in ["UPDATE public_trial_budget SET policy_mode='legacy_capped'",'UPDATE public_trial_calls SET usage_record_id=NULL']:
            with self.assertRaises(self.pg.psycopg.errors.InsufficientPrivilege): db.execute(sql)


if __name__ == '__main__': unittest.main()
