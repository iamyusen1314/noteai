"""Real bounded DNS executor, synthetic resolver, no network or model calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import model_admission as admission
import claude_gateway_protocol as protocol
import model_router as router
import public_product as public


class GatewayDNSCapacityTests(unittest.TestCase):
    def environment(self):
        return mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
            "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({
                router.CLAUDE_HAIKU: {"rpm": 10000, "itpm": 10000000, "otpm": 2000000,
                    "evidence_ref": "synthetic-DNS-capacity-regression"}})})

    def test_six_real_async_preflights_queue_instead_of_overflowing_four_executor_places(self):
        active = 0; peak = 0; calls = 0
        lock, release = threading.Lock(), threading.Event()
        def resolver(_authority):
            nonlocal active, peak, calls
            with lock: active += 1; peak = max(peak, active); calls += 1
            try:
                if not release.wait(3): raise AssertionError("fixture resolver was not released")
                return ("8.8.8.8",)
            finally:
                with lock: active -= 1
        async def scenario():
            manager = admission.Admission()
            transport = router.GatewayClaudeTransport(base_url="https://gateway.example.invalid")
            async def invoke(index):
                operation, _ = manager.register("dns-owner-" + str(index), str(index))
                marker = public._invocation.set(public.Invocation(operation.user_id, str(index), admission_state=operation))
                try:
                    async with public.model_admission("dns-call-" + str(index), "claude", model_id=router.CLAUDE_HAIKU):
                        http = await transport._async_http_transport()
                        await http.aclose()
                        return "prepared-no-HTTP"
                finally:
                    public._invocation.reset(marker); manager.finish(operation)
            with mock.patch.object(admission, "_instance", manager):
                tasks = [asyncio.create_task(invoke(index)) for index in range(6)]
                try:
                    for _ in range(100):
                        if active >= 2: break
                        await asyncio.sleep(.005)
                    await asyncio.sleep(.02)
                    release.set()
                    values = await asyncio.gather(*tasks, return_exceptions=True)
                    self.assertEqual(values, ["prepared-no-HTTP"] * 6)
                    self.assertEqual((manager.calls.active, manager.calls.deferred, manager.operations), ({}, {}, {}))
                finally:
                    release.set()
                    await asyncio.gather(*tasks, return_exceptions=True)
        executor = router._BoundedGatewayDNSExecutor(max_workers=2, max_pending=2)
        try:
            with self.environment(), mock.patch.object(router, "_GATEWAY_DNS_EXECUTOR", executor), \
                 mock.patch.object(router, "_resolve_global_gateway_addresses", side_effect=resolver):
                asyncio.run(scenario())
            self.assertEqual((calls, peak, active), (6, 2, 0))
        finally: executor.shutdown(wait=True)

    def test_sync_async_share_two_dns_places_and_repeated_cancel_drains_original_resolver(self):
        names = ("first-async", "second-sync", "third-async")
        started = {name: threading.Event() for name in names}
        release = {name: threading.Event() for name in names}
        lock = threading.Lock()
        active, peak, calls = 0, 0, []
        def resolver(authority):
            nonlocal active, peak
            name = authority.split(".", 1)[0]
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append(name)
            started[name].set()
            try:
                if not release[name].wait(3):
                    raise AssertionError("controlled resolver was not released")
                return ("8.8.8.8",)
            finally:
                with lock:
                    active -= 1
        async def scenario():
            manager = admission.Admission()
            def transport(name):
                return router.GatewayClaudeTransport(base_url=f"https://{name}.gateway.example.invalid")
            def invoke_sync():
                operation, _ = manager.register("dns-sync-owner", "sync")
                marker = public._invocation.set(public.Invocation(operation.user_id, "sync",
                    admission_state=operation))
                try:
                    with public.model_admission_sync("dns-sync-call", "claude", model_id=router.CLAUDE_HAIKU):
                        prepared = transport("second-sync")._sync_http_transport()
                        prepared.close()
                        return "sync-prepared-no-HTTP"
                finally:
                    public._invocation.reset(marker)
                    manager.finish(operation)
            async def invoke_async(name):
                operation, _ = manager.register("dns-owner-" + name, name)
                marker = public._invocation.set(public.Invocation(operation.user_id, name,
                    admission_state=operation))
                try:
                    async with public.model_admission("dns-call-" + name, "claude", model_id=router.CLAUDE_HAIKU):
                        prepared = await transport(name)._async_http_transport()
                        await prepared.aclose()
                        return "async-prepared-no-HTTP"
                finally:
                    public._invocation.reset(marker)
                    manager.finish(operation)
            async def until(predicate):
                for _ in range(200):
                    if predicate():
                        return
                    await asyncio.sleep(.005)
                self.fail("controlled DNS state was not reached")
            with mock.patch.object(admission, "_instance", manager):
                tasks = []
                try:
                    first = asyncio.create_task(invoke_async("first-async"))
                    tasks.append(first)
                    await until(started["first-async"].is_set)
                    second = asyncio.create_task(asyncio.to_thread(invoke_sync))
                    tasks.append(second)
                    await until(started["second-sync"].is_set)
                    third = asyncio.create_task(invoke_async("third-async"))
                    tasks.append(third)
                    await until(lambda: bool(manager.gateway_dns.waiting))
                    self.assertEqual((active, len(manager.gateway_dns.active)), (2, 2))
                    self.assertFalse(started["third-async"].is_set())
                    for _ in range(3):
                        first.cancel()
                        await asyncio.sleep(.01)
                        self.assertFalse(first.done(), "cancel released DNS while its resolver still runs")
                        self.assertEqual((active, len(manager.gateway_dns.active)), (2, 2))
                        self.assertFalse(started["third-async"].is_set())
                    release["first-async"].set()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                    await until(started["third-async"].is_set)
                    self.assertEqual(calls.count("first-async"), 1)
                    self.assertEqual((active, len(manager.gateway_dns.active)), (2, 2))
                    release["third-async"].set()
                    release["second-sync"].set()
                    self.assertEqual(await third, "async-prepared-no-HTTP")
                    self.assertEqual(await second, "sync-prepared-no-HTTP")
                finally:
                    for event in release.values():
                        event.set()
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                self.assertEqual((manager.calls.active, manager.calls.deferred,
                                  manager.gateway_dns.active, manager.gateway_dns.waiting,
                                  manager.operations), ({}, {}, {}, {}, {}))
        executor = router._BoundedGatewayDNSExecutor(max_workers=2, max_pending=2)
        try:
            with self.environment(), mock.patch.object(router, "_GATEWAY_DNS_EXECUTOR", executor), \
                 mock.patch.object(router, "_resolve_global_gateway_addresses", side_effect=resolver):
                asyncio.run(scenario())
            self.assertEqual((peak, active), (2, 0))
            self.assertCountEqual(calls, names)
        finally:
            for event in release.values():
                event.set()
            executor.shutdown(wait=True)

    def test_no_invocation_readiness_keeps_legacy_dns_and_signed_control_response(self):
        authority, secret = "gateway.example.invalid", "synthetic-readiness-secret"
        resolutions, control_calls = [], []
        def resolver(observed_authority):
            resolutions.append(observed_authority)
            return ("8.8.8.8",)
        def handler(request):
            control_calls.append((request.method, request.url.path, request.content))
            payload = {"protocol_version": protocol.PROTOCOL_VERSION,
                "service": "noteai-claude-gateway", "status": "ready_multi_instance",
                "deployment_scope": "shared_control_plane", "replay_store": "dynamodb_shared_atomic",
                "config_epoch": "synthetic-config", "key_epoch": "synthetic-epoch",
                "server_time": int(time.time()),
                "challenge": request.headers[protocol.HEADER_READINESS_CHALLENGE],
                "nonce": request.headers[protocol.HEADER_NONCE]}
            payload["attestation"] = protocol.readiness_attestation(secret, payload)
            return httpx.Response(200, json=payload)
        original_pin = router._pin_httpx_transport_backend
        def pin_to_synthetic_control(transport, observed_authority, address, *, async_mode):
            # Exercise the original SSRF-safe pinned backend construction first;
            # replace only its eventual network with the controlled HTTP peer.
            pinned = original_pin(transport, observed_authority, address, async_mode=async_mode)
            self.assertEqual((observed_authority, address, async_mode), (authority, "8.8.8.8", False))
            pinned.close()
            return httpx.MockTransport(handler)
        transport = router.GatewayClaudeTransport(base_url="https://" + authority,
            key_id="synthetic-key", secret=secret, config_epoch="synthetic-config", key_epoch="synthetic-epoch")
        invocation = public._invocation.set(None)
        remote = public._model_lease.set(None)
        executor = router._BoundedGatewayDNSExecutor(max_workers=2, max_pending=2)
        try:
            with self.environment(), \
                 mock.patch.object(admission, "current", side_effect=AssertionError("control probe requires no user pool")), \
                 mock.patch.object(router, "_GATEWAY_DNS_EXECUTOR", executor), \
                 mock.patch.object(router, "_resolve_global_gateway_addresses", side_effect=resolver):
                with mock.patch.object(router, "_pin_httpx_transport_backend", side_effect=pin_to_synthetic_control):
                    readiness = transport.probe_readiness()
                self.assertTrue(readiness["remote_ready"])
                self.assertIsNone(readiness["remote_error_code"])
                async def preflight():
                    prepared = await transport._async_http_transport()
                    await prepared.aclose()
                asyncio.run(preflight())
            self.assertEqual(resolutions, [authority, authority])
            self.assertEqual(control_calls, [("GET", protocol.READINESS_PATH, b"")])
        finally:
            executor.shutdown(wait=True)
            public._model_lease.reset(remote)
            public._invocation.reset(invocation)


if __name__ == "__main__": unittest.main()
