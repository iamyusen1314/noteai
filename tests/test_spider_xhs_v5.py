import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import spider_xhs_http as legacy
import spider_xhs_v5 as v5
from vendor.spider_xhs.v5 import runtime
from vendor.spider_xhs.v5.state import PcDeviceProfile


class V5ReadTests(unittest.TestCase):
    def credentials(self):
        return legacy.SessionCredentials.from_records([
            {"name": "a1", "value": "a" * 52},
            {"name": "web_session", "value": "FAKE_TEST_SESSION"},
        ])

    def reader(self, responses, *, safety=lambda: None):
        sent, events = [], []
        queue = list(responses)
        def request(req):
            sent.append(req)
            response = queue.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        client = httpx.Client(transport=httpx.MockTransport(request), follow_redirects=False, trust_env=False)
        self.addCleanup(client.close)
        reader = v5.V5Detail(credentials=self.credentials(), assert_ready=safety,
                             client=client, observe=events.append)
        return reader, sent, events

    def detail(self):
        return {"source_note_id": "6a7954010000000026034707", "image_formats": ["jpg", "webp", "avif"],
                "extra": {"need_body_topic": "1"}, "xsec_source": "pc_search", "xsec_token": ""}

    def dsl(self):
        return httpx.Response(200, text="function getdss() { return '1789010000000'; }; DO_NOT_EXECUTE()")

    def test_real_node_signing_and_normal_cookie_chain(self):
        reader, sent, events = self.reader([
            self.dsl(), httpx.Response(200, json={"success": True, "code": 0, "data": {"user_id": "0123456789abcdef01234567"}}),
            httpx.Response(200, json={"success": True, "code": 0, "data": {"items": [{
                "id": self.detail()["source_note_id"], "note_card": {
                    "user": {"user_id": "0123456789abcdef01234567"},
                    "interact_info": {"liked_count": "4", "collected_count": "2", "comment_count": "0"}}}]}}),
        ])
        self.assertTrue(reader.read(self.detail())["success"])
        self.assertEqual([str(r.url) for r in sent], [v5.DSL_URL, v5.BASE + v5.SESSION_API, v5.BASE + v5.DETAIL_API])
        self.assertEqual([r.method for r in sent], ["GET", "GET", "POST"])
        self.assertNotIn("cookie", sent[0].headers)
        self.assertEqual(json.loads(sent[-1].content), self.detail())
        self.assertEqual(sent[-1].headers["xy-direction"], str(v5.wire.generate_xy_direction(reader.user_id)))
        self.assertIn("x-rap-param", sent[-1].headers)
        self.assertIn("Chrome/152", sent[-1].headers["user-agent"])
        self.assertFalse(reader.profile.session.fingerprint_ready)  # No fabricated gid/readiness.
        self.assertEqual(reader.last_owned_metrics, {"likes": 4, "saves": 2, "comments": 0})
        self.assertEqual(len(events), 6)
        self.assertEqual([e["sequence"] for e in events], [1,1,2,2,3,3])
        self.assertNotIn("FAKE_TEST_SESSION", json.dumps(events))
        self.assertNotIn(reader.user_id, json.dumps(events))
        with self.assertRaises(legacy.XHSAdapterError):
            reader.read(self.detail())
        self.assertEqual(len(sent), 3)

    def test_session_rejection_stops_without_detail_or_auth_retry(self):
        reader, sent, events = self.reader([self.dsl(), httpx.Response(200, json={
            "success": False, "code": -3, "msg": "FAKE_PRIVATE_MESSAGE",
        })])
        with self.assertRaises(legacy.XHSAdapterError) as caught:
            reader.read(self.detail())
        self.assertEqual(caught.exception.code, "remote_business_error")
        self.assertEqual(len(sent), 2)
        self.assertEqual(events[-1]["response_diagnostics"]["business_code"], -3)
        self.assertNotIn("FAKE", json.dumps(events))

    def test_conflicting_returned_note_id_is_never_a_verified_owned_read(self):
        reader, sent, events = self.reader([
            self.dsl(), httpx.Response(200, json={"success": True, "code": 0, "data": {"user_id": "0123456789abcdef01234567"}}),
            httpx.Response(200, json={"success": True, "code": 0, "data": {"items": [{
                "id": self.detail()["source_note_id"], "note_card": {"note_id": "different-note",
                    "user": {"user_id": "0123456789abcdef01234567"},
                    "interact_info": {"liked_count": "4", "collected_count": "2", "comment_count": "0"}}}]}}),
        ])
        with self.assertRaisesRegex(legacy.XHSAdapterError, "remote_schema_error"):
            reader.read(self.detail())
        self.assertIsNone(reader.last_owned_metrics)
        self.assertEqual(len(sent), 3)

    def test_dsl_redirect_and_malformed_response_never_executes_script(self):
        for response in [httpx.Response(302, headers={"Location": "https://example.invalid/?token=FAKE"}),
                         httpx.Response(200, text="require('child_process').execSync('false')")]:
            reader, sent, events = self.reader([response])
            with mock.patch.object(runtime, "sign") as signer:
                with self.assertRaises(legacy.XHSAdapterError):
                    reader.read(self.detail())
            signer.assert_not_called()
            self.assertEqual(len(sent), 1)
            self.assertNotIn("FAKE", json.dumps(events))

    def test_safety_stop_precedes_all_network(self):
        def stopped():
            raise legacy.XHSAdapterError("server_session_logged_out")
        reader, sent, events = self.reader([], safety=stopped)
        with self.assertRaisesRegex(legacy.XHSAdapterError, "server_session_logged_out"):
            reader.read(self.detail())
        self.assertEqual(sent, [])
        self.assertEqual(events, [])

    def test_timeout_does_not_repeat_or_initialize_new_identity(self):
        reader, sent, events = self.reader([httpx.ReadTimeout("FAKE_SECRET")])
        with self.assertRaisesRegex(legacy.XHSAdapterError, "network_error"):
            reader.read(self.detail())
        self.assertEqual(len(sent), 1)
        self.assertEqual(events[-1]["phase"], "unknown")
        self.assertNotIn("FAKE", json.dumps(events))

    def test_signer_uses_stdin_and_rejects_creator_or_remote_program(self):
        with mock.patch.object(runtime.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=b'{"b1":"fake"}')
            runtime.invoke({"operation": "b1", "options": {"test": "FAKE_PRIVATE"}})
        self.assertNotIn("FAKE_PRIVATE", str(run.call_args.args))
        self.assertIn(b"FAKE_PRIVATE", run.call_args.kwargs["input"])
        self.assertEqual(set(run.call_args.kwargs["env"]), {"PATH"})
        with self.assertRaisesRegex(RuntimeError, "signer_failed"):
            runtime.invoke({"operation": "sign", "payload": {"appId": "ugc", "dsfProgram": "FAKE_SCRIPT"}})

    def test_old_cookie_load_timestamp_refreshes_dsl_anchor(self):
        profile = PcDeviceProfile(cookies="a1=" + "a" * 52 + "; web_session=FAKE; loadts=1600000000000")
        with mock.patch.object(runtime, "invoke", return_value={"xs": "fake", "xt": "fake", "xs_common": "fake"}) as invoke, \
             mock.patch.object(profile, "current_b1", return_value="fake"):
            runtime.sign(profile, v5.SESSION_API, "", "1789010000000")
        payload = invoke.call_args.args[0]["payload"]
        self.assertEqual(payload["dslPair"], str(payload["now"]) + ";1789010000000")

    def test_curl_transport_is_bounded_and_disables_redirect_proxy_environment(self):
        from curl_cffi.curl import CURL_WRITEFUNC_ERROR
        with mock.patch("curl_cffi.requests.Session") as session:
            client = v5.CurlClient()
            def send(*args, **kwargs):
                self.assertFalse(kwargs["allow_redirects"])
                self.assertEqual(kwargs["proxies"], {"all": ""})
                self.assertEqual(kwargs["accept_encoding"], "gzip, deflate, br, zstd")
                cb = kwargs["content_callback"]
                self.assertEqual(cb(b"test"), 4)
                self.assertEqual(cb(b"x" * v5.MAX_RESPONSE_BYTES), CURL_WRITEFUNC_ERROR)
                return mock.Mock(status_code=200)
            session.return_value.request.side_effect = send
            response = client.request("GET", v5.DSL_URL, headers={})
            self.assertEqual(response.content, b"test")
            self.assertFalse(session.call_args.kwargs["trust_env"])
            client.close()

    def test_missing_web_session_stops_before_initialization(self):
        reader, sent, events = self.reader([])
        reader.profile = PcDeviceProfile(cookies="a1=" + "a" * 52 + "; id_token=FAKE")
        with self.assertRaisesRegex(legacy.XHSAdapterError, "login_required"):
            reader.read(self.detail())
        self.assertEqual(sent, [])
        self.assertEqual(events, [])

    def test_real_curl_aborts_large_local_response_and_never_follows_redirect(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                calls.append(self.path)
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/must-not-follow")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "65536")
                    self.end_headers()
                    try:
                        self.wfile.write(b"x" * 65536)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = v5.CurlClient()
        try:
            origin = "http://127.0.0.1:" + str(server.server_port)
            # curl_cffi trust_env=False alone does not disable libcurl proxies.
            with mock.patch.dict(os.environ, {
                "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
                "https_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
                "NO_PROXY": "", "no_proxy": "",
            }):
                self.assertEqual(client.request("GET", origin + "/redirect", headers={}).status_code, 302)
            with mock.patch.object(v5, "MAX_RESPONSE_BYTES", 128):
                with self.assertRaises(Exception):
                    client.request("GET", origin + "/large", headers={})
            self.assertEqual(calls, ["/redirect", "/large"])
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
