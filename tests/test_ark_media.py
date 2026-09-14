import io
import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media as ark
import public_product
import model_router


class ArkVideoAdmissionTests(unittest.TestCase):
    def setUp(self):
        import db, auth, billing
        self.db, self.billing = db, billing
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db._DB_PATH
        self.env = mock.patch.dict(os.environ, {'DATABASE_URL':'','NOTEAI_PUBLIC_PRODUCT':'1'})
        self.env.start()
        db._DB_PATH = Path(self.temp.name)/'isolated.sqlite'
        db.init_db()
        self.user = auth.create_user('video-owner-fixture','SyntheticPassword42!')
        db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
        billing.record_free_usage(self.user['id'],'score')
        self.marker = public_product._invocation.set(public_product.Invocation(self.user['id'],'video-one'))

    def tearDown(self):
        public_product._invocation.reset(self.marker)
        self.billing.clear_active_usage()
        self.db._DB_PATH = self.old_path
        self.env.stop()
        self.temp.cleanup()

    def payload(self, ref='11111111-1111-4111-8111-111111111111', digest='a'*64):
        return {'model':ark.MODEL,'max_tokens':8192,'modality':'video_audio',
                'media':{'ref':ref,'sha256':digest,'transport':'private_oss'}}

    def test_unknown_media_cannot_be_replayed_by_new_request_or_reupload(self):
        original = public_product._reserve_payload(self.payload(), 100, require_metered=True)
        self.db.execute("UPDATE public_trial_calls SET state='unknown' WHERE id=?",(original,))
        for new_ref in ('11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222'):
            next_marker=public_product._invocation.set(public_product.Invocation(self.user['id'],'different-request-'+new_ref))
            try:
                with self.assertRaisesRegex(public_product.TrialProviderStopped,'PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY'):
                    public_product._reserve_payload(self.payload(ref=new_ref),100,require_metered=True)
            finally:
                public_product._invocation.reset(next_marker)
        self.assertEqual(self.db.fetchone('SELECT count(*) FROM public_trial_calls')[0],1)
        self.assertEqual(self.db.fetchone('SELECT reserved_milli_cny FROM public_trial_budget')[0],100)
        # A distinct material can progress; no blanket stop on unrelated work.
        next_marker=public_product._invocation.set(public_product.Invocation(self.user['id'],'different-material'))
        try:
            public_product._reserve_payload(self.payload(ref='33333333-3333-4333-8333-333333333333',digest='b'*64),100,require_metered=True)
        finally:
            public_product._invocation.reset(next_marker)
        self.assertEqual(self.db.fetchone('SELECT count(*) FROM public_trial_calls')[0],2)

    def test_pending_media_and_unsettled_success_both_block_duplicate_inference(self):
        original=public_product._reserve_payload(self.payload(),100,require_metered=True)
        for state,status in [('dispatched',None),('responded',200)]:
            self.db.execute('UPDATE public_trial_calls SET state=?,http_status=? WHERE id=?',(state,status,original))
            marker=public_product._invocation.set(public_product.Invocation(self.user['id'],'next-'+state))
            try:
                with self.assertRaisesRegex(public_product.TrialProviderStopped,'PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY'):
                    public_product._reserve_payload(self.payload(),100,require_metered=True)
            finally:
                public_product._invocation.reset(marker)
        saved=json.loads(self.db.fetchone('SELECT provenance_json FROM public_trial_calls')[0])
        self.assertEqual(saved['media'],self.payload()['media'])
        self.assertNotIn('url',json.dumps(saved))

    def test_nonterminal_responses_usage_is_retained_but_new_request_cannot_replay(self):
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(200,json={'model':ark.MODEL,'status':'in_progress',
                'usage':{'input_tokens':100,'output_tokens':10,
                    'input_tokens_details':{'audio_tokens':30,'cached_tokens':0}},'output':[]})
        with mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic'}):
            with self.assertRaises(public_product.TrialProviderStopped):
                ark.video('完整视频',[ark.file_video_part('file-original')],media=self.payload()['media'],
                          transport=httpx.MockTransport(respond))
            original=self.db.fetchone('SELECT state,model_usage_record_id FROM public_trial_calls')
            self.assertEqual(original['state'],'unknown')
            self.assertIsNotNone(original['model_usage_record_id'])
            marker=public_product._invocation.set(public_product.Invocation(self.user['id'],'new-id-after-in-progress'))
            try:
                with self.assertRaisesRegex(public_product.TrialProviderStopped,'PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY'):
                    ark.video('原同视频',[ark.file_video_part('file-original')],media=self.payload()['media'],
                              transport=httpx.MockTransport(respond))
            finally:
                public_product._invocation.reset(marker)
        self.assertEqual(len(calls),1)

    def test_unknown_media_isolated_from_other_user_and_preupload_check(self):
        import auth
        original=public_product._reserve_payload(self.payload(),100,require_metered=True)
        self.db.execute("UPDATE public_trial_calls SET state='unknown' WHERE id=?",(original,))
        marker=public_product._invocation.set(public_product.Invocation(self.user['id'],'preupload-check'))
        try:
            with self.assertRaisesRegex(public_product.TrialProviderStopped,'PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY'):
                public_product.assert_media_result_known(self.payload()['media'])
        finally:
            public_product._invocation.reset(marker)
        other=auth.create_user('separate-video-owner','SyntheticPassword42!')
        self.billing.record_free_usage(other['id'],'score')
        marker=public_product._invocation.set(public_product.Invocation(other['id'],'independent-owner'))
        try:
            public_product.assert_media_result_known(self.payload()['media'])
            public_product._reserve_payload(self.payload(),100,require_metered=True)
        finally:
            public_product._invocation.reset(marker)

    def test_real_sdk_signs_only_original_object_get_for_ten_minutes(self):
        import private_storage as storage, alibabacloud_oss_v2 as oss, hashlib
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        from urllib.parse import urlsplit, parse_qs
        cfg=oss.config.load_default()
        cfg.region='cn-shenzhen';cfg.endpoint='https://oss-cn-shenzhen.aliyuncs.com'
        cfg.credentials_provider=oss.credentials.StaticCredentialsProvider('SYNTHETIC-ID','SYNTHETIC-SECRET')
        signer=oss.Client(cfg)
        ref=SimpleNamespace(id='11111111-1111-4111-8111-111111111111',subject_hash='a'*64,
                            purpose='video',expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        key=storage._media_key(ref.id,ref.subject_hash,'video')
        ref.object_key_hash=hashlib.sha256(key.encode()).hexdigest()
        backend=storage.AliyunOssObjectBackend(client=mock.Mock(),bucket='isolated-fixture',
                    signing_client=signer,region='cn-shenzhen')
        parsed=urlsplit(backend.video_read_url(ref))
        self.assertEqual(parsed.netloc,'isolated-fixture.oss-cn-shenzhen.aliyuncs.com')
        self.assertEqual(parsed.path,'/noteai-private/'+key)
        seconds=int(parse_qs(parsed.query)['x-oss-expires'][0])
        self.assertLessEqual(seconds,600)
        self.assertGreaterEqual(seconds,598)  # SDK floors the remaining duration.
        backend.client.assert_not_called()
        ref.object_key_hash='b'*64
        with self.assertRaises(storage.MediaReferenceUnavailable):backend.video_read_url(ref)


class ArkMediaTests(unittest.TestCase):
    def test_nullable_audio_usage_does_not_invent_unknown_video_cost(self):
        def classify(details, audio_possible):
            return ark.usage_dimensions({"usage": {"prompt_tokens": 1000,
                "completion_tokens": 120, "prompt_tokens_details": details}},
                audio_possible=audio_possible)
        image = classify({"cached_tokens": 0, "audio_tokens": None,
                          "audio_cached_tokens": None}, False)
        self.assertEqual(image["usage_status"], "complete")
        self.assertEqual(image["tokens_in"], 1000)
        no_cache = classify({"cached_tokens": 0, "audio_tokens": 300,
                             "audio_cached_tokens": None}, True)
        self.assertEqual(no_cache["audio_input_tokens"], 300)
        self.assertEqual(no_cache["tokens_in"], 700)
        for details in ({"cached_tokens": 0, "audio_tokens": None},
                        {"cached_tokens": 200, "audio_tokens": 300,
                         "audio_cached_tokens": None}):
            self.assertEqual(classify(details, True)["usage_status"], "usage_incomplete")

    def test_four_disjoint_dimensions_and_missing_audio_are_explicit(self):
        response = {"usage": {"prompt_tokens": 1000, "completion_tokens": 120,
            "prompt_tokens_details": {"audio_tokens": 300, "cached_tokens": 200, "audio_cached_tokens": 50},
            "completion_tokens_details": {"reasoning_tokens": 40}}}
        self.assertEqual(ark.usage_dimensions(response, audio_possible=True), {
            "tokens_in": 550, "tokens_out": 120, "cache_read_tokens": 150,
            "audio_input_tokens": 250, "audio_cache_read_tokens": 50, "usage_status": "complete"})
        for details in ({"cached_tokens": 0}, {"audio_tokens": 300},
                        {"audio_tokens": 300, "cached_tokens": 200},
                        {"audio_tokens": 900, "cached_tokens": 900, "audio_cached_tokens": 0}):
            with self.subTest(details=details):
                result = ark.usage_dimensions({"usage": {"prompt_tokens": 1000,
                    "completion_tokens": 120, "prompt_tokens_details": details}}, audio_possible=True)
                self.assertEqual(result["usage_status"], "usage_incomplete")
                self.assertEqual(result["unclassified_input_tokens"], 1000)
                self.assertEqual(result["tokens_out"], 120)

    def test_price_tiers_use_total_input_not_text_only(self):
        self.assertEqual([ark.pricing(n)["input"] for n in (32768,32769,131072,131073)], [.6,.9,.9,1.8])
        self.assertEqual(ark.pricing(32769)["audio_input"], 13.5)

    def test_png_mime_and_pixels_are_read_from_real_image(self):
        image = io.BytesIO()
        Image.new("RGB", (300,200), "green").save(image, "PNG")
        part = ark.image_part(image.getvalue())
        self.assertTrue(part["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(part["image_url"]["detail"], "xhigh")
        with self.assertRaises(ark.ArkMediaError):
            ark.image_part(b"filename-is-not-image")

    def test_video_files_reference_and_audio_capable_preprocessing(self):
        calls, states = [], []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={"id": "file-test001", "status": "processing"})
        with mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline"}):
            file_id = ark.upload_video(b"isolated-video-fixture", mime="video/mp4", persist=states.append,
                                       transport=httpx.MockTransport(respond))
        body = calls[0].content
        self.assertIn(b'preprocess_configs[video][model]', body)
        self.assertIn(ark.MODEL.encode(), body)
        self.assertIn(b'preprocess_configs[video][fps]', body)
        self.assertEqual(ark.file_video_part(file_id), {"type": "input_video", "file_id": file_id})
        self.assertEqual(states, [{"state": "uploaded", "file_id": file_id, "model": ark.MODEL}])
        self.assertEqual(len(calls), 1)

    def test_file_upload_unknown_is_not_retried(self):
        calls, states = [], []
        def fail(request):
            calls.append(request)
            raise httpx.ReadTimeout("offline timeout")
        with mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline"}):
            with self.assertRaisesRegex(ark.ArkMediaError, "UNKNOWN_NO_REPLAY"):
                ark.upload_video(b"isolated-video-fixture", mime="video/mp4", persist=states.append,
                                 transport=httpx.MockTransport(fail))
        self.assertEqual(states, [{"state": "unknown"}])
        self.assertEqual(len(calls), 1)

    def test_upload_failure_log_preserves_phase_not_private_exception_text(self):
        private = 'Cookie=synthetic-private; Bearer synthetic-secret https://private.invalid/owner'
        cases = [(httpx.WriteTimeout(private), 'writetimeout'),
                 (httpx.ReadTimeout(private), 'readtimeout')]
        for failure, expected in cases:
            calls, states, log = [], [], io.StringIO()
            def fail(request):
                calls.append(request)
                raise failure
            with self.subTest(expected=expected), contextlib.redirect_stderr(log), \
                 mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY': 'synthetic-secret'}):
                with self.assertRaisesRegex(ark.ArkMediaError, 'UNKNOWN_NO_REPLAY'):
                    ark.upload_video(b'original-video', mime='video/mp4', persist=states.append,
                        upload_ref='12345678-1234-4234-8234-123456789abc',
                        transport=httpx.MockTransport(fail))
            event = json.loads(log.getvalue())
            self.assertEqual(event['error_code'], expected)
            self.assertEqual(event['phase'], 'ark_file_upload_transport')
            self.assertFalse(event['response_received'])
            self.assertNotIn('synthetic', log.getvalue())
            self.assertNotIn('private.invalid', log.getvalue())
            self.assertIn(b'material-12345678-1234-4234-8234-123456789abc.mp4', calls[0].content)
            self.assertEqual(states, [{'state':'unknown'}])
            self.assertEqual(len(calls), 1)

    def test_large_upload_streams_complete_bytes_in_bounded_writes(self):
        payload = b'original-audio-video' * 100000
        chunks, calls = [], []
        class CaptureTransport(httpx.BaseTransport):
            def handle_request(self, request):
                calls.append(request.method)
                chunks.extend(request.stream)
                return httpx.Response(200, json={'id':'file-streamed','status':'processing'})
        with mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic'}):
            ark.upload_video(payload, mime='video/mp4', persist=lambda value: None,
                             transport=CaptureTransport())
        self.assertEqual(calls, ['POST'])
        self.assertLessEqual(max(map(len, chunks)), 65536)
        self.assertIn(payload, b''.join(chunks))

    def test_committed_file_identity_survives_lost_ack_and_failed_unknown_cas(self):
        row, calls, log = {}, [], io.StringIO()
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={'id':'file-committed', 'status':'processing'})
        def persist(value):
            if not row:
                row.update(value)
                raise RuntimeError('private database acknowledgement lost')
            raise ValueError('CAS rejected: original state already committed')
        with contextlib.redirect_stderr(log), mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic'}):
            with self.assertRaisesRegex(ark.ArkMediaError, 'UNKNOWN_NO_REPLAY'):
                ark.upload_video(b'original-video', mime='video/mp4', persist=persist,
                    transport=httpx.MockTransport(respond))
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual([e['phase'] for e in events],
                         ['ark_file_upload_persist_result','ark_file_upload_persist_unknown'])
        self.assertEqual([e['error_code'] for e in events], ['runtimeerror','valueerror'])
        self.assertTrue(all(e['file_id']=='file-committed' and e['response_received'] for e in events))
        self.assertEqual(row['state'], 'uploaded')
        self.assertEqual(row['file_id'], 'file-committed')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('private database', log.getvalue())

    def test_invalid_upload_response_is_distinct_from_transport_failure(self):
        for body in (b'not-json', b'null', b'{}'):
            calls, states, log = [], [], io.StringIO()
            def respond(request):
                calls.append(request)
                return httpx.Response(200, content=body)
            with contextlib.redirect_stderr(log), mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic'}):
                with self.assertRaises(ark.ArkMediaError):
                    ark.upload_video(b'original-video', mime='video/mp4', persist=states.append,
                        transport=httpx.MockTransport(respond))
            event = json.loads(log.getvalue())
            self.assertEqual(event['phase'],'ark_file_upload_response_decode')
            self.assertTrue(event['response_received'])
            self.assertEqual(event['http_status'],200)
            self.assertEqual(states,[{'state':'unknown'}])
            self.assertEqual(len(calls),1)

    def test_official_failed_file_state_is_readable_without_inference(self):
        calls = []
        def respond(request):
            calls.append(request.method)
            return httpx.Response(200,json={'id':'file-original','status':'failed',
                'error':{'message':'private material details'}})
        with mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic'}):
            self.assertEqual(ark.read_file_state('file-original',transport=httpx.MockTransport(respond)), 'failed')
        self.assertEqual(calls,['GET'])

    def test_responses_video_keeps_full_audio_input_and_existing_physical_cost_identity(self):
        payload = {'model':ark.MODEL, 'status':'completed', 'usage':{
            'input_tokens':1000, 'output_tokens':120, 'total_tokens':1120,
            'input_tokens_details':{'audio_tokens':300,'cached_tokens':200,'audio_cached_tokens':50},
            'output_tokens_details':{'reasoning_tokens':40}},
            'output':[{'type':'reasoning','summary':[]}, {'type':'message','role':'assistant',
                'status':'completed','content':[{'type':'output_text','text':'画面与原口播结果'}]}]}
        requests, actions = [], []
        def respond(request):
            requests.append(request)
            return httpx.Response(200,json=payload)
        marker = public_product._invocation.set(public_product.Invocation('owner-fixture','video-request-fixture'))
        try:
            with mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic'}), \
                 mock.patch.object(public_product, '_reserve_payload') as reserve, \
                 mock.patch.object(public_product, '_record_response', side_effect=lambda *a,**k: actions.append('response')) as recorded, \
                 mock.patch.object(model_router, '_record_usage', side_effect=lambda *a,**k: actions.append('usage')) as usage:
                result=ark.video('完整音画', [ark.video_part(b'original-audio-video',mime='video/mp4',fps=2)],
                                 transport=httpx.MockTransport(respond))
            self.assertEqual(result,'画面与原口播结果')
            self.assertEqual(str(requests[0].url),ark.RESPONSES_URL)
            sent=json.loads(requests[0].content)
            self.assertFalse(sent['store'])
            self.assertFalse(sent['stream'])
            self.assertNotIn('messages',sent)
            self.assertEqual(sent['input'][0]['content'][0]['fps'],2)
            self.assertEqual(sent['input'][0]['content'][0]['type'],'input_video')
            self.assertEqual(actions,['usage','response'])
            self.assertEqual(usage.call_args.kwargs['audio_input_tokens'],250)
            self.assertEqual(usage.call_args.kwargs['audio_cache_read_tokens'],50)
            self.assertEqual(usage.call_args.kwargs['tokens_in'],550)
            self.assertEqual(usage.call_args.kwargs['tokens_out'],120)
            self.assertEqual(usage.call_args.kwargs['physical_call_id'],reserve.call_args.kwargs['call_id'])
            self.assertEqual(recorded.call_args.args[0],usage.call_args.kwargs['physical_call_id'])
        finally:
            public_product._invocation.reset(marker)

    def test_responses_incomplete_or_unmetered_video_does_not_fallback_or_repeat(self):
        usage={'input_tokens':100,'output_tokens':10,'input_tokens_details':{'audio_tokens':30,'cached_tokens':0}}
        message={'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':'partial video'}]}
        base={'model':ark.MODEL,'status':'completed','usage':usage,'output':[message]}
        for body,code in (({**base,'status':'incomplete'},'ARK_OUTPUT_INCOMPLETE'),
                ({**base,'output':[{**message,'partial':True}]},'ARK_OUTPUT_INCOMPLETE'),
                ({**base,'output':[{**message,'status':'in_progress'}]},'ARK_OUTPUT_INCOMPLETE'),
                ({**base,'output':[{'type':'function_call'}]},'ARK_OUTPUT_INCOMPLETE'),
                ({**base,'usage':{**usage,'input_tokens_details':{'cached_tokens':0}}},'ARK_USAGE_INCOMPLETE'),
                ({**base,'model':'other-model'},'ARK_MODEL_IDENTITY_MISMATCH')):
            marker=public_product._invocation.set(public_product.Invocation('owner-fixture','video-request-fixture'))
            calls,actions=[],[]
            def respond(request):
                calls.append(request)
                return httpx.Response(200,json=body)
            try:
                with self.subTest(code=code), mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic','NOTEAI_PUBLIC_PRODUCT':'1'}), \
                     mock.patch.object(public_product,'_reserve_payload'), \
                     mock.patch.object(public_product,'_record_response',side_effect=lambda *a,**k:actions.append('response')), \
                     mock.patch.object(model_router,'_record_usage',side_effect=lambda *a,**k:actions.append('usage')):
                    for _ in range(2):
                        with self.assertRaisesRegex(public_product.TrialProviderStopped,code):
                            ark.video('原完整音画',[ark.file_video_part('file-original')],transport=httpx.MockTransport(respond))
                self.assertEqual(len(calls),1)
                self.assertEqual(actions,['usage','response'])
            finally:
                public_product._invocation.reset(marker)

    def test_broken_log_sink_cannot_skip_durable_unknown(self):
        states=[]
        class BrokenLog(io.StringIO):
            def write(self, value):
                raise OSError('unavailable stderr')
        def fail(request):
            raise httpx.WriteTimeout('synthetic failure')
        with contextlib.redirect_stderr(BrokenLog()), mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic'}):
            with self.assertRaisesRegex(ark.ArkMediaError,'UNKNOWN_NO_REPLAY'):
                ark.upload_video(b'original-video',mime='video/mp4',persist=states.append,
                                 transport=httpx.MockTransport(fail))
        self.assertEqual(states,[{'state':'unknown'}])

    def test_file_poll_and_cleanup_only_use_original_id(self):
        calls = []
        def respond(request):
            calls.append((request.method, str(request.url)))
            return httpx.Response(200, json={"id": "file-test001", "status": "active", "deleted": True})
        with mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline"}):
            ark.wait_file("file-test001", transport=httpx.MockTransport(respond))
            ark.delete_file("file-test001", transport=httpx.MockTransport(respond))
        self.assertEqual(calls, [("GET", ark.BASE_URL+"/files/file-test001"),
                                 ("DELETE", ark.BASE_URL+"/files/file-test001")])

    def test_usage_is_recorded_before_length_missing_or_invalid_output_stops(self):
        base = {"model": ark.MODEL, "usage": {"prompt_tokens": 100, "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 0}},
            "choices": [{"finish_reason": "stop", "message": {"content": "actual understanding"}}]}
        cases = [
            ({**base, "choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}, "ARK_OUTPUT_INCOMPLETE"),
            ({**base, "usage": {}}, "ARK_USAGE_INCOMPLETE"),
            ({**base, "model": "other-model"}, "ARK_MODEL_IDENTITY_MISMATCH"),
            ({**base, "choices": [None]}, "ARK_OUTPUT_INCOMPLETE"),
            ({**base, "choices": [{"finish_reason": "stop", "message": None}]}, "ARK_OUTPUT_EMPTY"),
        ]
        for payload, expected in cases:
            with self.subTest(expected=expected):
                invocation = public_product.Invocation("owner-fixture", "request-fixture")
                marker = public_product._invocation.set(invocation)
                calls, actions = [], []
                def respond(request):
                    calls.append(request)
                    return httpx.Response(200, json=payload)
                try:
                    with mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline", "NOTEAI_PUBLIC_PRODUCT": "1"}), \
                         mock.patch.object(public_product, "_reserve_payload"), \
                         mock.patch.object(public_product, "_record_response", side_effect=lambda *a,**k: actions.append("response")), \
                         mock.patch.object(model_router, "_record_usage", side_effect=lambda *a,**k: actions.append("usage")):
                        with self.assertRaisesRegex(public_product.TrialProviderStopped, expected):
                            ark.chat("Read actual material", [{"type":"image_url","image_url":{"url":"data:image/png;base64,AA=="}}],
                                     transport=httpx.MockTransport(respond))
                        with self.assertRaisesRegex(public_product.TrialProviderStopped, expected):
                            ark.chat("Must not dispatch", [{}], transport=httpx.MockTransport(respond))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(actions, ["usage", "response"])
                finally:
                    public_product._invocation.reset(marker)

    def test_redirect_does_not_forward_credentials_or_start_second_call(self):
        calls = []
        marker = public_product._invocation.set(public_product.Invocation("owner-fixture", "request-fixture"))
        def respond(request):
            calls.append(request)
            return httpx.Response(302, headers={"Location":"https://example.invalid/redirect"})
        try:
            with mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline"}), \
                 mock.patch.object(public_product, "_reserve_payload"), \
                 mock.patch.object(public_product, "_record_response") as terminal:
                with self.assertRaisesRegex(public_product.TrialProviderStopped, "ARK_HTTP_302"):
                    ark.chat("Read material", [{}], transport=httpx.MockTransport(respond))
            self.assertEqual(len(calls),1)
            self.assertEqual(terminal.call_args.args[1],302)
        finally:
            public_product._invocation.reset(marker)

    def test_file_upload_server_error_and_lost_persistence_keep_unknown_identity(self):
        with mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline"}):
            for status, expected in ((503,'unknown'),(401,'failed')):
                events=[]
                with self.assertRaises(ark.ArkMediaError):
                    ark.upload_video(b'original-video',mime='video/mp4',persist=events.append,
                        transport=httpx.MockTransport(lambda request: httpx.Response(status,json={})))
                self.assertEqual([v['state'] for v in events],[expected])
            events=[]
            def persist(value):
                events.append(value)
                if len(events)==1: raise RuntimeError('simulated lost write acknowledgement')
            with self.assertRaisesRegex(ark.ArkMediaError,'UNKNOWN'):
                ark.upload_video(b'original-video',mime='video/mp4',persist=persist,
                    transport=httpx.MockTransport(lambda request: httpx.Response(200,json={'id':'file-original','status':'active'})))
            self.assertEqual(events[-1],{'state':'unknown','file_id':'file-original'})

    def test_file_reconcile_does_not_call_delete_or_guess_404_success(self):
        calls=[]
        def respond(request):
            calls.append(request.method)
            return httpx.Response(404,json={'error':{'code':'unconfirmed'}})
        with mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline"}):
            with self.assertRaisesRegex(ark.ArkMediaError,'HTTP_404'):
                ark.read_file_state('file-original',transport=httpx.MockTransport(respond))
        self.assertEqual(calls,['GET'])
