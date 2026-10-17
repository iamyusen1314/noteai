"""Offline checks for inference failure provenance and accounting state."""
import contextlib
import asyncio
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
import model_router
import model_admission


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

    def _accounting_response(self, request):
        self.wires.append(request)
        return httpx.Response(200, json={"model": ark_media.MODEL,
            "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                      "prompt_tokens_details": {"cached_tokens": 0}},
            "choices": [{"finish_reason": "stop", "message": {"content": "observed image"}}]})

    def _chat(self):
        return ark_media.chat("synthetic material", [{"type": "text", "text": "fixture"}],
                              transport=httpx.MockTransport(self._accounting_response))

    def _physical(self):
        return dict(self.db.fetchone("SELECT * FROM public_trial_calls"))

    def test_http200_usage_write_failure_closes_wire_but_fences_delivery(self):
        class AccountingFailure(RuntimeError):
            sqlstate = "22000"
        original = AccountingFailure("SECRET query/body/token must not enter logs")
        self.wires, log = [], io.StringIO()
        with contextlib.redirect_stderr(log), mock.patch.object(
                self.billing, "record_model_usage", side_effect=original) as meter:
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED") as failure:
                self._chat()
        row = self._physical()
        self.assertEqual((row["state"], row["http_status"]), ("responded", 200))
        self.assertIsNone(row["model_usage_record_id"])
        self.assertEqual(self.db.fetchone("SELECT count(*) FROM model_usage_records")[0], 0)
        self.assertIs(failure.exception.__cause__, original)
        self.assertEqual((len(self.wires), meter.call_count), (1, 1))
        with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                    "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED"):
            public_product.assert_result_known()
        with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                    "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED"):
            self._chat()
        self.assertEqual(len(self.wires), 1)
        self.assertFalse(model_admission.current().calls.active)
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual(events[0]["schema"], "noteai.model_usage_failure.v1")
        self.assertEqual(events[0]["exception_class"], "AccountingFailure")
        self.assertEqual(events[0]["sqlstate"], "22000")
        self.assertEqual(events[0]["call_id"], row["id"])
        self.assertNotIn("SECRET", log.getvalue())
        self.assertNotIn("query/body/token", log.getvalue())

    def test_nonterminal_video_accounting_failure_does_not_become_known_success(self):
        wires, log = [], io.StringIO()
        def respond(request):
            wires.append(request)
            return httpx.Response(200, json={"model": ark_media.MODEL, "status": "in_progress",
                "usage": {"input_tokens": 100, "output_tokens": 10,
                    "input_tokens_details": {"audio_tokens": 30, "cached_tokens": 0}},
                "output": []})
        with contextlib.redirect_stderr(log), mock.patch.object(self.billing,
                "record_model_usage", side_effect=RuntimeError("private local failure")):
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED"):
                ark_media.video("fixture", [ark_media.file_video_part("file-original")],
                                transport=httpx.MockTransport(respond))
        self.assertEqual((len(wires), self._physical()["state"]), (1, "unknown"))
        self.assertIsNone(self._physical()["model_usage_record_id"])

    def test_usage_commit_ack_unknown_keeps_one_real_usage_and_no_model_retry(self):
        self.wires, log = [], io.StringIO()
        original = self.billing.record_model_usage
        def commit_then_lose_ack(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("private usage commit acknowledgement lost")
        with contextlib.redirect_stderr(log), mock.patch.object(
                self.billing, "record_model_usage", side_effect=commit_then_lose_ack) as meter:
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED"):
                self._chat()
        row = self._physical()
        self.assertEqual((row["state"], row["http_status"]), ("responded", 200))
        self.assertIsNotNone(row["model_usage_record_id"])
        self.assertEqual(self.db.fetchone("SELECT count(*) FROM model_usage_records")[0], 1)
        self.assertGreater(self.db.fetchone("SELECT known_cost_rmb FROM model_usage_records")[0], 0)
        self.assertEqual((len(self.wires), meter.call_count), (1, 1))
        self.assertNotIn("private usage", log.getvalue())

    def test_terminal_commit_ack_unknown_reads_original_without_second_update(self):
        self.wires, log, updates = [], io.StringIO(), []
        original = public_product._record_response
        execute = self.db.Transaction.execute
        attempts = []
        def terminal(*args, **kwargs):
            attempts.append((args, kwargs))
            original(*args, **kwargs)
            if len(attempts) == 1:
                raise public_product.TrialProviderStopped("PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN")
        def track(tx, sql, *args, **kwargs):
            if sql.startswith("UPDATE public_trial_calls SET state="):
                updates.append(sql)
            return execute(tx, sql, *args, **kwargs)
        with contextlib.redirect_stderr(log), mock.patch.object(
                public_product, "_record_response", side_effect=terminal), \
                mock.patch.object(self.db.Transaction, "execute", new=track):
            self.assertEqual(self._chat(), "observed image")
        self.assertEqual((len(self.wires), len(attempts), len(updates)), (1, 2, 1))
        self.assertEqual(self._physical()["state"], "responded")
        self.assertEqual(self.db.fetchone("SELECT count(*) FROM model_usage_records")[0], 1)
        # Do not clear a shared invocation failure just because this call's
        # acknowledgement was reconciled; a sibling may still be unconfirmed.
        with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                    "PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN"):
            public_product.assert_result_known()

    def test_terminal_write_failure_has_only_one_local_retry_and_stays_unconfirmed(self):
        self.wires, log = [], io.StringIO()
        def unavailable(*args, **kwargs):
            raise public_product.TrialProviderStopped("PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN")
        with contextlib.redirect_stderr(log), mock.patch.object(public_product, "_record_response",
                side_effect=unavailable) as terminal:
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN"):
                self._chat()
        self.assertEqual((len(self.wires), terminal.call_count), (1, 2))
        self.assertEqual(self._physical()["state"], "dispatched")
        self.assertEqual(self.db.fetchone("SELECT count(*) FROM model_usage_records")[0], 1)
        self.assertEqual(len([json.loads(line) for line in log.getvalue().splitlines()
            if json.loads(line).get("failure_role") == "terminal_persistence"]), 2)

    def test_accounting_and_terminal_storage_failures_preserve_primary_without_more_calls(self):
        self.wires, log = [], io.StringIO()
        def unavailable(*args, **kwargs):
            raise public_product.TrialProviderStopped("PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN")
        with contextlib.redirect_stderr(log), mock.patch.object(self.billing,
                "record_model_usage", side_effect=RuntimeError("private usage failure")), \
                mock.patch.object(public_product, "_record_response",
                side_effect=unavailable) as terminal:
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED"):
                self._chat()
        self.assertEqual((len(self.wires), terminal.call_count), (1, 2))
        self.assertEqual(self._physical()["state"], "dispatched")
        self.assertEqual(self.db.fetchone("SELECT count(*) FROM model_usage_records")[0], 0)
        self.assertNotIn("private usage failure", log.getvalue())

    def test_normal_success_preserves_usage_once_and_releases_physical_slot(self):
        self.wires = []
        self.assertEqual(self._chat(), "observed image")
        self.assertEqual(len(self.wires), 1)
        self.assertEqual(self._physical()["state"], "responded")
        self.assertIsNotNone(self._physical()["model_usage_record_id"])
        self.assertEqual(self.db.fetchone("SELECT count(*) FROM model_usage_records")[0], 1)
        self.assertFalse(model_admission.current().calls.active)

    def test_cancelled_wire_is_unknown_without_usage_and_releases_queue_slot(self):
        calls, log = [], io.StringIO()
        def cancelled(request):
            calls.append(request)
            raise asyncio.CancelledError()
        with contextlib.redirect_stderr(log):
            with self.assertRaises(asyncio.CancelledError):
                ark_media.chat("fixture", [{}], transport=httpx.MockTransport(cancelled))
        self.assertEqual((len(calls), self._physical()["state"]), (1, "unknown"))
        self.assertIsNone(self._physical()["model_usage_record_id"])
        self.assertEqual(self.db.fetchone("SELECT count(*) FROM model_usage_records")[0], 0)
        self.assertFalse(model_admission.current().calls.active)


if __name__ == "__main__":
    unittest.main()
