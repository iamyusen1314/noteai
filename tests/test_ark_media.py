import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media as ark
import public_product
import model_router


class ArkMediaTests(unittest.TestCase):
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
        self.assertEqual(ark.file_video_part(file_id), {"type": "video_url", "video_url": {"file_id": file_id}})
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
