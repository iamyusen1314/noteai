"""Actual cover provider/Bridge with an isolated ledger and mocked HTTP only."""
import contextlib
import io
import json
from pathlib import Path
import time
import unittest
from unittest import mock

import httpx
from tests import test_cover_agent_provider as fixtures
import cover_agent_provider as provider
import cover_agent_runtime as runtime
import cover_jobs
import cover_runtime
import db
import public_product


class TailAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CoverAgentProviderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.body["max_tokens"] = provider.MAX_OUTPUT_TOKENS
        self.clock = [time.time()]
        self.before, self.requests = [], []

    def run_call(self, remaining, *, queue_delay=0, read_timeout=False):
        def before(stage, call_id, _estimate):
            self.before.append(stage)
            cover_jobs.before_text_call(self.fixture.claim, "design", call_id)

        def transport(request):
            self.requests.append(request)
            if read_timeout:
                raise httpx.ReadTimeout("PRIVATE_SYNTHETIC_TIMEOUT", request=request)
            return httpx.Response(200, json=self.fixture.response())

        self.bridge = runtime.Bridge(job_id=self.fixture.claim["request_id"],
            directory=Path(self.fixture.fixture.temp.name), sources=[],
            hooks=cover_runtime.RuntimeHooks(before, lambda _record: None),
            model_transport=httpx.MockTransport(transport))
        self.bridge.request_deadline = self.clock[0] + remaining
        original = public_product.model_admission_sync
        waited = [False]

        @contextlib.contextmanager
        def permit(*args, **kwargs):
            with original(*args, **kwargs):
                if queue_delay and not waited[0]:
                    self.clock[0] += queue_delay
                    waited[0] = True
                yield

        with mock.patch.object(provider.time, "time", side_effect=lambda: self.clock[0]), \
                mock.patch.object(public_product, "model_admission_sync", side_effect=permit):
            return self.bridge.model(self.fixture.body)

    def calls(self):
        return db.fetchall("SELECT * FROM public_trial_calls WHERE usage_record_id=?",
            (self.fixture.claim["charge"]["usage_id"],))

    def assert_no_intent_or_dispatch(self):
        self.assertEqual(self.before, [])
        self.assertEqual(self.requests, [])
        self.assertEqual(self.calls(), [])
        row = db.fetchone("SELECT call_intents_json FROM cover_jobs WHERE id=?",
            (self.fixture.claim["request_id"],))
        self.assertEqual(json.loads(row["call_intents_json"]), {})

    def test_observed_short_tail_stops_before_intent_and_fails_without_customer_charge(self):
        with self.assertRaises(provider.CoverAgentProviderError) as caught:
            self.run_call(140 + 58.275)
        self.assertEqual(caught.exception.code, "COVER_AGENT_TASK_DEADLINE")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(self.bridge.ordinal, 0)
        self.assert_no_intent_or_dispatch()
        cover_jobs.fail_job(self.fixture.claim, failure_code=caught.exception.code, outcome_unknown=False)
        job = cover_jobs.get_job(self.fixture.fixture.user, self.fixture.claim["request_id"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["billing"]["credits_used"], 0)

    def test_just_below_useful_window_is_not_admitted(self):
        with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_TASK_DEADLINE"):
            self.run_call(319.999)
        self.assert_no_intent_or_dispatch()

    def test_exact_boundary_keeps_normal_once_accounting(self):
        self.run_call(320)
        self.assertEqual(len(self.before), 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].extensions["timeout"]["read"], 180)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["state"], calls[0]["http_status"]), ("responded", 200))
        self.assertIsNotNone(calls[0]["model_usage_record_id"])
        self.assertEqual(len(self.bridge.costs), 1)

    def test_shared_queue_time_is_rechecked_before_the_original_intent(self):
        with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_TASK_DEADLINE"):
            self.run_call(400, queue_delay=100)
        self.assert_no_intent_or_dispatch()

    def test_sufficient_window_keeps_the_existing_900_second_read_ceiling(self):
        self.run_call(1500)
        self.assertEqual(self.requests[0].extensions["timeout"],
            {"connect": 10, "read": 900, "write": 90, "pool": 10})
        self.assertEqual(len(self.calls()), 1)

    def test_read_timeout_after_transport_invocation_remains_unknown_and_is_never_retried(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                self.run_call(1500, read_timeout=True)
        self.assertTrue(caught.exception.outcome_unknown)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["state"], calls[0]["reserve_milli_cny"]), ("unknown", 2753))
        self.assertIsNone(calls[0]["model_usage_record_id"])
        with self.assertRaises(public_product.TrialProviderStopped):
            self.bridge.model(self.fixture.body)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(self.calls()), 1)


if __name__ == "__main__":
    unittest.main()
