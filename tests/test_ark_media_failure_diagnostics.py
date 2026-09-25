"""Offline checks for inference failure provenance and accounting state."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media
import public_product


class ArkInferenceFailureDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        import auth
        import billing
        import db

        self.db = db
        self.billing = billing
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db._DB_PATH
        self.env = mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_ARK_API_KEY": "synthetic-secret",
        })
        self.env.start()
        db._DB_PATH = Path(self.temp.name) / "isolated.sqlite"
        db.init_db()
        self.user = auth.create_user("ark-diagnostic-owner", "SyntheticPassword42!")
        db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
        billing.record_free_usage(self.user["id"], "score")
        self.marker = public_product._invocation.set(
            public_product.Invocation(self.user["id"], "diagnostic-request"))

    def tearDown(self):
        public_product._invocation.reset(self.marker)
        self.billing.clear_active_usage()
        self.db._DB_PATH = self.old_path
        self.env.stop()
        self.temp.cleanup()

    def _run(self, handler):
        calls = []
        output = io.StringIO()

        def capture(request):
            calls.append(request)
            return handler(request)

        with contextlib.redirect_stderr(output):
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY"):
                ark_media.video("synthetic prompt", [ark_media.file_video_part("file-original")],
                    media={"ref": "11111111-1111-4111-8111-111111111111",
                           "sha256": "a" * 64, "transport": "private_oss"},
                    transport=httpx.MockTransport(capture))
        event = json.loads(output.getvalue().splitlines()[0])
        physical = self.db.fetchone("SELECT state,http_status FROM public_trial_calls")
        return event, physical, calls, output.getvalue()

    def test_write_timeout_is_unknown_and_original_phase_is_redacted(self):
        private = "Cookie=private-value Bearer synthetic-secret https://private.invalid/path"

        def fail(request):
            raise httpx.WriteTimeout(private)

        event, physical, calls, output = self._run(fail)
        self.assertEqual(len(calls), 1)
        self.assertEqual(physical["state"], "unknown")
        self.assertIsNone(physical["http_status"])
        self.assertEqual(event["error_code"], "ark_media_write_timeout")
        self.assertEqual(event["phase"], "ark_inference_transport")
        self.assertEqual(event["network_phase"], "request_send")
        self.assertEqual(event["dispatch_state"], "unknown")
        self.assertNotIn("synthetic-secret", output)
        self.assertNotIn("private.invalid", output)
        self.assertNotIn("private-value", output)

    def test_connect_error_without_trace_cannot_be_declared_unsubmitted(self):
        event, physical, calls, _ = self._run(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("opaque transport")))
        self.assertEqual(len(calls), 1)
        self.assertEqual(event["network_phase"], "connect")
        self.assertEqual(event["dispatch_state"], "unknown")
        self.assertEqual(physical["state"], "unknown")

    def test_observed_connect_failure_before_send_can_be_released(self):
        def fail(request):
            trace = request.extensions["trace"]
            trace("connection.connect_tcp.started", {})
            trace("connection.connect_tcp.failed", {})
            raise httpx.ConnectError("synthetic connection failure")

        event, physical, calls, _ = self._run(fail)
        self.assertEqual(len(calls), 1)
        self.assertEqual(event["dispatch_state"], "not_dispatched")
        self.assertEqual(event["network_phase"], "connect")
        self.assertEqual(event["transport_event"], "connection.connect_tcp.failed")
        self.assertEqual(physical["state"], "responded")
        self.assertIsNone(physical["http_status"])

    def test_send_observation_overrides_later_connect_error(self):
        def fail(request):
            trace = request.extensions["trace"]
            trace("connection.connect_tcp.failed", {})
            trace("http11.send_request_headers.started", {})
            raise httpx.ConnectError("synthetic later failure")

        event, physical, calls, _ = self._run(fail)
        self.assertEqual(len(calls), 1)
        self.assertEqual(event["dispatch_state"], "unknown")
        self.assertTrue(event["request_send_observed"])
        self.assertEqual(physical["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
