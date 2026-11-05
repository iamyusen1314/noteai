"""Real quota-ticket deferral versus provider execution time; no HTTP or DB."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import model_admission as admission
import model_router as router
import public_product as public


class CapacityRouterDeadlineTests(unittest.TestCase):
    async def scenario(self, *, enabled=True, hang=False):
        environment = {"NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1" if enabled else "0",
            "NOTEAI_MODEL_REMOTE_CONCURRENCY": "4", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({
                router.CLAUDE_HAIKU: {"rpm": 100, "itpm": 1000000, "otpm": 100000,
                                      "evidence_ref": "synthetic-deadline-regression"}})}
        with mock.patch.dict(os.environ, environment):
            manager = admission.Admission()
            operation, _ = manager.register("synthetic-owner", "f" * 64, route="/generate/stream")
            invocation = public.Invocation("synthetic-owner", "synthetic-task",
                route="/generate/stream", admission_state=operation)
            marker = public._invocation.set(invocation)
            parked, release, dispatched = asyncio.Event(), asyncio.Event(), asyncio.Event()
            result = {"value": None, "error": None, "usage_audit_required": False}
            async def release_quota():
                await parked.wait()
                await asyncio.sleep(.4)
                release.set()
            try:
                with mock.patch.object(admission, "_instance", manager):
                    async with public.model_admission("synthetic-call-000001", "claude",
                                                       model_id=router.CLAUDE_HAIKU) as ticket:
                        async def vendor_like_call():
                            try:
                                manager.calls.defer(ticket)
                                parked.set()
                                await release.wait()
                                await manager.calls.resume_async(ticket)
                                public.mark_model_dispatched(ticket.call_id)
                                dispatched.set()
                                if hang:
                                    await asyncio.Event().wait()
                                await asyncio.sleep(.03)
                                return "complete-original-response"
                            except asyncio.CancelledError:
                                raise router.ClaudeRequestCancelled(
                                    usage_audit_required=dispatched.is_set()) from None
                        releaser = asyncio.create_task(release_quota())
                        loop = asyncio.get_running_loop(); started = loop.time()
                        try:
                            result["value"] = await router._await_with_gateway_deadline(
                                vendor_like_call(), started + .2)
                        except router.ClaudeGatewayError as error:
                            result["error"] = error.code
                            result["usage_audit_required"] = error.usage_audit_required
                        finally:
                            result["elapsed"] = loop.time() - started
                            if not releaser.done(): releaser.cancel()
                            with contextlib.suppress(asyncio.CancelledError): await releaser
                        result["dispatched"] = dispatched.is_set()
                        result["ticket_wait"] = getattr(ticket, "capacity_wait_seconds", None)
                self.assertEqual((manager.calls.active, manager.calls.deferred), ({}, {}))
                return result
            finally:
                public._invocation.reset(marker)
                manager.finish(operation)

    def test_real_quota_deferral_does_not_consume_original_provider_deadline(self):
        outcome = asyncio.run(self.scenario())
        self.assertIsNone(outcome["error"], outcome)
        self.assertEqual(outcome["value"], "complete-original-response")
        self.assertTrue(outcome["dispatched"])
        self.assertGreaterEqual(outcome["elapsed"], .4)
        self.assertLess(outcome["elapsed"], 1.5)

    def test_real_provider_hang_after_quota_wait_retains_original_timeout(self):
        outcome = asyncio.run(self.scenario(hang=True))
        self.assertTrue(outcome["dispatched"], outcome)
        self.assertEqual(outcome["error"], "CLAUDE_OUTCOME_UNKNOWN")
        self.assertTrue(outcome["usage_audit_required"])
        self.assertGreaterEqual(outcome["elapsed"], .55)
        self.assertLess(outcome["elapsed"], 1.5)

    def test_capacity_mode_off_does_not_extend_original_deadline(self):
        outcome = asyncio.run(self.scenario(enabled=False))
        self.assertEqual(outcome["error"], "GATEWAY_PRE_DISPATCH_TIMEOUT")
        self.assertFalse(outcome["dispatched"])
        self.assertLess(outcome["elapsed"], .38)


if __name__ == "__main__": unittest.main()
