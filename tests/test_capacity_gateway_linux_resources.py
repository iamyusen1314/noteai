"""One Gateway-only resource profile; no API, real supplier, AWS or sockets.

Large valid text envelopes stress transport memory, not real model context or
token eligibility. Actual DynamoDB and Anthropic capacity are not measured.
"""

import asyncio
from collections import Counter
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import socket
import sys
import threading
import time
import unittest
from unittest import mock

import httpx

from tests.test_capacity_gateway_resources import (
    SharedStore, USAGE, gateway, protocol, OperationState,
)


MIB = 1024 * 1024
BODY_BUDGET = 32 * MIB
TARGET = ("tests.test_capacity_gateway_linux_resources.GatewayLinuxResourcesTests."
          "test_sixty_four_signed_calls_and_near_body_budget_preserve_control_and_cleanup")


def resources():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {"python_pid": os.getpid(), "python_threads": threading.active_count(),
              "process_ru_maxrss_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
              "cpu_user_seconds": usage.ru_utime, "cpu_system_seconds": usage.ru_stime}
    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:", "Threads:")):
                key, value = line.split(":", 1)
                result[key] = int(value.split()[0]) * (1 if key == "Threads" else 1024)
    for directory in ("/proc/self/fd", "/dev/fd"):
        if Path(directory).is_dir():
            result["file_descriptors"] = len(list(Path(directory).iterdir()))
            break
    root = Path("/sys/fs/cgroup")
    for name in ("memory.current", "memory.peak", "memory.max", "memory.swap.max",
                 "pids.current", "pids.max", "cpu.max"):
        path = root / name
        if path.is_file():
            value = path.read_text().strip()
            result[name] = int(value) if value.isdigit() else value
    for name in ("memory.events", "cpu.stat"):
        path = root / name
        if path.is_file():
            result[name] = {key: int(value) for key, value in
                            (line.split() for line in path.read_text().splitlines())}
    return result


class ObservedStore(SharedStore):
    def __init__(self):
        super().__init__()
        self.begins, self.finishes = Counter(), Counter()

    async def begin_provider(self, operation, lease, dispatch_hash, model, now):
        result = await super().begin_provider(operation, lease, dispatch_hash, model, now)
        if result:
            self.begins[operation] += 1
        return result

    async def finish_operation(self, operation, lease, state, now, **kwargs):
        result = await super().finish_operation(operation, lease, state, now, **kwargs)
        if result:
            self.finishes[operation] += 1
        return result


class HeldProvider:
    def __init__(self):
        self.calls, self.closed = Counter(), Counter()
        self.gates, self.entered = {}, asyncio.Queue()

    async def _start(self, payload):
        operation = payload["operation_id"]
        self.calls[operation] += 1
        gate = self.gates.setdefault(operation, asyncio.Event())
        self.entered.put_nowait(operation)
        return operation, gate

    async def create(self, payload):
        operation, gate = await self._start(payload)
        try:
            await gate.wait()
            return ["synthetic-resource-result"], dict(USAGE)
        finally:
            self.closed[operation] += 1

    async def stream(self, payload):
        operation, gate = await self._start(payload)
        try:
            yield {"type": "content", "text": "synthetic-partial-result"}
            await gate.wait()
            yield {"type": "usage", "usage": dict(USAGE)}
        finally:
            self.closed[operation] += 1


class GatewayLinuxResourcesTests(unittest.TestCase):
    def test_sixty_four_signed_calls_and_near_body_budget_preserve_control_and_cleanup(self):
        required = os.environ.get("NOTEAI_CAPACITY_GATEWAY_LINUX_PROFILE_REQUIRED") == "1"
        proof = {"state": "STARTED", "platform": sys.platform, "python": sys.version,
                 "linux_profile_required": required, "supplier_calls": 0, "aws_calls": 0,
                 "external_socket_connect_calls": 0, "process_role": "Gateway-only ASGI in one Python process",
                 "body_budget": BODY_BUDGET, "concurrency": 64,
                 "heartbeat_kind": "event-loop scheduling observation; not a lease-renewal acceptance",
                 "transport_stress_only_not_model_context_or_token_eligibility": True}
        expected_versions = {"anthropic": "0.97.0", "boto3": "1.43.44", "certifi": "2026.10.19",
                             "fastapi": "0.136.1", "httpx": "0.28.1", "uvicorn": "0.46.0"}
        proof["dependency_versions"] = {}
        for name, expected in expected_versions.items():
            try:
                installed = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                installed = None
            proof["dependency_versions"][name] = {"actual": installed, "gateway_expected": expected,
                                                   "matches_gateway_image_pin": installed == expected}
        proof["dependencies_are_not_proof_of_actual_Render_image"] = True
        before = resources()
        proof["before"] = before
        if required:
            self.assertEqual(sys.platform, "linux")
            self.assertEqual(sys.version_info[:2], (3, 11))
            self.assertEqual(before.get("memory.max"), 512 * MIB)
            self.assertEqual(before.get("memory.swap.max"), 0)
            quota, period = map(int, str(before.get("cpu.max", "")).split())
            self.assertEqual(quota * 2, period)
        blocked = []
        def forbidden(*_args, **_kwargs):
            blocked.append("socket_attempt")
            raise AssertionError("real network forbidden in Gateway resource QA")
        env = {
            "ANTHROPIC_API_KEY": "synthetic-never-used",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "synthetic-resource-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "synthetic-resource-secret",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": "gateway.test",
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "resource-config",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "resource-epoch",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "dynamodb",
            "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID": "synthetic-resource-principal",
            "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE": "synthetic-never-used",
            "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "ap-southeast-1",
            "NOTEAI_CLAUDE_GATEWAY_CAPACITY_ENABLED": "1",
            "NOTEAI_CLAUDE_GATEWAY_CONCURRENCY": "64",
            "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "20000",
            "NOTEAI_CLAUDE_GATEWAY_INFLIGHT_BODY_BYTES": str(BODY_BUDGET),
            "NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES": str(8 * MIB),
        }
        async def scenario():
            store, provider = ObservedStore(), HeldProvider()
            tasks, samples, heartbeat, control = {}, [], [], []
            halt = asyncio.Event()
            started = time.monotonic()
            async def sample():
                previous = time.monotonic()
                while not halt.is_set():
                    now = time.monotonic()
                    heartbeat.append(now - previous)
                    previous = now
                    samples.append({"t": now - started, **resources(),
                                    "active_leases": len(store.leases),
                                    "body_bytes": gateway._BODY_LIMITER.active_bytes})
                    await asyncio.sleep(.02)
            def request(name, heavy=False, path=protocol.MESSAGES_PATH):
                operation = "gateway_resource_operation_" + name
                text = "x" * (1_660_000 if heavy else 32)
                messages = [{"role": "user", "content": text} for _ in range(5 if heavy else 1)]
                body = json.dumps({"operation_id": operation,
                    "model": "claude-haiku-4-5-20251001", "max_tokens": 100,
                    "messages": messages}, separators=(",", ":")).encode()
                headers = protocol.auth_headers(key_id=env["NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID"],
                    secret=env["NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET"], method="POST", path=path,
                    authority="gateway.test", config_epoch="resource-config", key_epoch="resource-epoch", body=body)
                return operation, body, headers
            async def control_ready(client, phase):
                nonce_before, calls_before = len(store.nonces), sum(provider.calls.values())
                then = time.monotonic()
                for path in ("/health/live", "/health/ready"):
                    response = await client.get(path)
                    self.assertEqual(response.status_code, 200)
                headers = protocol.auth_headers(key_id=env["NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID"],
                    secret=env["NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET"], method="GET", path=protocol.READINESS_PATH,
                    authority="gateway.test", config_epoch="resource-config", key_epoch="resource-epoch", body=b"")
                headers[protocol.HEADER_READINESS_CHALLENGE] = "synthetic-resource-challenge-1234"
                response = await client.get(protocol.READINESS_PATH, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(protocol.verify_readiness_attestation(
                    env["NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET"], response.json()))
                self.assertEqual((len(store.nonces), sum(provider.calls.values())), (nonce_before, calls_before))
                control.append({"phase": phase, "three_control_calls_elapsed_seconds": time.monotonic() - then,
                                "active_leases": len(store.leases), "body_bytes": gateway._BODY_LIMITER.active_bytes})
            with mock.patch.object(gateway, "_CONTROL_STORE", store), \
                 mock.patch.object(gateway, "_PROVIDER", provider), \
                 mock.patch.object(gateway, "_BODY_LIMITER", gateway.AggregateBodyLimiter()), \
                 mock.patch.object(gateway, "_dynamodb_identity_environment_valid", return_value=True):
                sampler = asyncio.create_task(sample())
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),
                                              base_url="https://gateway.test") as client:
                    try:
                        small = []
                        for index in range(64):
                            operation, body, headers = request("small_" + str(index))
                            small.append(operation)
                            tasks[operation] = asyncio.create_task(client.post(protocol.MESSAGES_PATH,
                                content=body, headers=headers))
                        for _ in range(64):
                            await asyncio.wait_for(provider.entered.get(), 10)
                        self.assertEqual((len(store.leases), gateway._BODY_LIMITER.active_requests), (64, 64))
                        proof["small_calls_held_simultaneously"] = 64
                        proof["after_64_small_held"] = resources()
                        await control_ready(client, "64_small_held")
                        # Retain60 small calls; release exactly4 places before
                        # introducing4 large bodies under the same64 lease cap.
                        for operation in small[:4]:
                            provider.gates[operation].set()
                        for operation in small[:4]:
                            self.assertEqual((await tasks[operation]).status_code, 200)
                        heavy_ops, heavy_lengths = [], []
                        for index in range(4):
                            path = protocol.STREAM_PATH if index == 0 else protocol.MESSAGES_PATH
                            operation, body, headers = request("heavy_" + str(index), True, path)
                            heavy_ops.append(operation)
                            heavy_lengths.append(len(body))
                            tasks[operation] = asyncio.create_task(client.post(path, content=body, headers=headers))
                            self.assertEqual(await asyncio.wait_for(provider.entered.get(), 10), operation)
                        mixed_bytes = gateway._BODY_LIMITER.active_bytes
                        self.assertGreaterEqual(mixed_bytes, int(BODY_BUDGET * .98))
                        self.assertLessEqual(mixed_bytes, BODY_BUDGET)
                        self.assertEqual((len(store.leases), gateway._BODY_LIMITER.active_requests), (64, 64))
                        proof.update(mixed_large_calls_held=4, mixed_small_calls_held=60,
                                     heavy_body_lengths=heavy_lengths, mixed_body_bytes=mixed_bytes,
                                     mixed_body_budget_ratio=mixed_bytes / BODY_BUDGET)
                        proof["near_body_budget_held"] = resources()
                        await control_ready(client, "near_32MiB_64_mixed_held")
                        operation, body, headers = request("rejected_over_budget", True)
                        before_reject = (len(store.nonces), sum(provider.calls.values()), len(store.operations))
                        rejected = await client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
                        self.assertEqual(rejected.status_code, 429)
                        self.assertEqual(rejected.json()["error"]["code"], "CONCURRENCY_LIMIT")
                        self.assertEqual((len(store.nonces), sum(provider.calls.values()), len(store.operations)), before_reject)
                        self.assertNotIn(operation, store.operations)
                        proof["oversize_aggregate_rejected_before_nonce_and_provider"] = True
                        await asyncio.sleep(.25)
                        # Cancel one active nonstream and the partial stream;
                        # their original known fences remain and bodies drain.
                        for operation in (small[4], heavy_ops[0]):
                            tasks[operation].cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await tasks[operation]
                        self.assertEqual(store.operations[small[4]], OperationState.CANCELLED)
                        self.assertEqual(store.operations[heavy_ops[0]], OperationState.PARTIAL)
                        for gate in provider.gates.values():
                            gate.set()
                        remaining = [task for task in tasks.values() if not task.cancelled()]
                        for response in await asyncio.gather(*remaining):
                            self.assertEqual(response.status_code, 200)
                        self.assertEqual((len(store.leases), gateway._BODY_LIMITER.active_bytes,
                                          gateway._BODY_LIMITER.active_requests), (0, 0, 0))
                        self.assertEqual(len(provider.calls), 68)
                        self.assertTrue(all(value == 1 for value in provider.calls.values()))
                        self.assertEqual(provider.calls, provider.closed)
                        self.assertEqual(provider.calls, store.begins)
                        self.assertEqual(provider.calls, store.finishes)
                        self.assertEqual(Counter(store.operations.values()), {
                            OperationState.TERMINAL_USAGE: 66, OperationState.CANCELLED: 1, OperationState.PARTIAL: 1})
                        self.assertTrue(all(limit == 64 for limit in store.limits))
                        await control_ready(client, "after_terminal_and_cancel_cleanup")
                        proof.update(mock_provider_calls=68, unique_original_operations=68,
                                     provider_begin_and_terminal_once=True, cancelled_known=1,
                                     partial_stream_known=1, terminal_usage=66,
                                     final_lease_count=0, final_body_bytes=0, final_body_requests=0)
                    finally:
                        for gate in provider.gates.values():
                            gate.set()
                        for task in tasks.values():
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks.values(), return_exceptions=True)
                        halt.set()
                        await sampler
                numeric = ("process_ru_maxrss_bytes", "VmRSS", "VmHWM", "python_threads", "Threads",
                           "file_descriptors", "memory.current", "memory.peak", "pids.current",
                           "active_leases", "body_bytes")
                proof.update(sample_count=len(samples),
                             sampled_maxima={name: max((sample[name] for sample in samples if name in sample), default=None)
                                             for name in numeric}, heartbeat_count=len(heartbeat),
                             heartbeat_max_gap_seconds=max(heartbeat, default=0), control=control,
                             elapsed_seconds=time.monotonic() - started)
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(socket.socket, "connect", side_effect=forbidden), \
             mock.patch.object(socket.socket, "connect_ex", side_effect=forbidden):
            asyncio.run(scenario())
        after = resources()
        self.assertEqual(blocked, [])
        self.assertGreater(proof["heartbeat_count"], 2)
        proof.update(after=after, blocked_network_attempts=len(blocked),
                     cpu_used_seconds=(after["cpu_user_seconds"] + after["cpu_system_seconds"]
                                       - before["cpu_user_seconds"] - before["cpu_system_seconds"]))
        if required:
            for name in ("oom", "oom_kill"):
                self.assertEqual(after["memory.events"][name], before["memory.events"][name])
            self.assertLessEqual(after["memory.peak"], 512 * MIB)
        for prohibited in ("api", "model_router", "public_product", "db"):
            self.assertNotIn(prohibited, sys.modules, "Gateway resource profile must not import API fixture")
        proof["state"] = "PASS_LINUX_EXACT_LIMITS" if required else "PASS_LOCAL_NOT_LINUX_RESOURCE_ACCEPTANCE"
        path = os.environ.get("NOTEAI_CAPACITY_GATEWAY_LINUX_PROOF")
        if path:
            Path(path).write_text(json.dumps(proof, sort_keys=True) + "\n")
        print(json.dumps({"gateway_resource_proof": proof}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
