import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import collect_production_host_preflight as collector


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], str | None]):
        self.responses = responses

    def run(self, *args: str, timeout: int = 15) -> str:
        del timeout
        key = tuple(args)
        if key not in self.responses or self.responses[key] is None:
            raise collector.CollectionError(f"missing fake command: {args[0]}")
        return str(self.responses[key])

    def optional(self, *args: str, timeout: int = 15) -> str | None:
        del timeout
        return self.responses.get(tuple(args))

    def combined(self, *args: str, timeout: int = 15) -> str:
        return self.run(*args, timeout=timeout)


class ProductionHostPreflightCollectorTests(unittest.TestCase):
    def test_env_evidence_never_contains_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "api.env"
            moonshot_key = "MOONSHOT_" + "API_KEY"
            path.write_text(
                "DATABASE_URL=postgresql://private-value\n"
                f"{moonshot_key}=opaque-private-value\n"
                "NOTEAI_CLOUD_RUNTIME=1\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            evidence = collector._env_file_evidence("api", path)

        serialized = json.dumps(evidence, sort_keys=True)
        self.assertEqual(evidence["key_count"], 3)
        self.assertEqual(evidence["duplicate_key_count"], 0)
        self.assertEqual(evidence["rejected_key_count"], 0)
        self.assertNotIn("private-value", serialized)
        self.assertNotIn("DATABASE_URL", serialized)
        self.assertNotIn(moonshot_key, serialized)

    def test_env_duplicates_unknown_secret_and_mode_fail_closed_in_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "xhs.env"
            path.write_text(
                "DATABASE_URL=one\nDATABASE_URL=two\nUNEXPECTED_TOKEN=three\n",
                encoding="utf-8",
            )
            path.chmod(0o644)
            evidence = collector._env_file_evidence("xhs", path)

        self.assertEqual(evidence["mode"], "0644")
        self.assertEqual(evidence["duplicate_key_count"], 1)
        self.assertEqual(evidence["rejected_key_count"], 1)

    def test_private_acr_route_uses_dns_and_route_without_registry_request(self):
        private = FakeRunner(
            {
                (
                    "getent",
                    "ahostsv4",
                    collector.PRIVATE_REGISTRY,
                ): "10.1.2.3 STREAM registry\n10.1.2.3 DGRAM registry",
                ("ip", "route", "get", "10.1.2.3"): "10.1.2.3 dev eth0",
            }
        )
        public = FakeRunner(
            {
                (
                    "getent",
                    "ahostsv4",
                    collector.PRIVATE_REGISTRY,
                ): "8.8.8.8 STREAM registry",
            }
        )

        self.assertEqual(collector._private_acr_route(private), (True, True))
        self.assertEqual(collector._private_acr_route(public), (False, False))

        shared_vpc = FakeRunner(
            {
                (
                    "getent",
                    "ahostsv4",
                    collector.PRIVATE_REGISTRY,
                ): "100.64.1.2 STREAM registry",
                ("ip", "route", "get", "100.64.1.2"): "100.64.1.2 dev eth0",
            }
        )
        self.assertEqual(collector._private_acr_route(shared_vpc), (True, True))

    def test_log_scan_outputs_only_counts(self):
        runner = FakeRunner(
            {
                (
                    "docker",
                    "logs",
                    "--tail",
                    "200",
                    "noteai-api-c",
                ): (
                    "startup complete\n"
                    "schema_migrations checked\n"
                    "moonshot request\n"
                    "token=private-value\n"
                )
            }
        )
        result = collector._log_counts(runner, "noteai-api-c")
        self.assertEqual(result, (1, 1, 1))
        self.assertNotIn("private-value", json.dumps(result))

    def test_network_scope_rejects_public_address(self):
        private = FakeRunner(
            {
                ("ip", "-o", "-4", "addr", "show", "scope", "global"): (
                    "2: eth0 inet 10.1.2.3/24 scope global eth0"
                )
            }
        )
        public = FakeRunner(
            {
                ("ip", "-o", "-4", "addr", "show", "scope", "global"): (
                    "2: eth0 inet 8.8.8.8/24 scope global eth0"
                )
            }
        )
        self.assertTrue(collector._private_network_only(private))
        self.assertFalse(collector._private_network_only(public))

    def test_temporary_process_scan_ignores_canary_named_data_mount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            proc_root = Path(temp_dir)
            process_dir = proc_root / "101"
            process_dir.mkdir()
            (process_dir / "cmdline").write_bytes(
                b"/usr/bin/docker\0run\0--mount\0"
                b"type=bind,src=/var/lib/noteai-canary-data,"
                b"dst=/app/model/data\0--name\0noteai-api-c\0"
            )

            self.assertEqual(collector._temporary_process_count(proc_root), 0)

    def test_temporary_process_scan_detects_workers_and_temporary_runtime_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            proc_root = Path(temp_dir)
            worker_dir = proc_root / "201"
            worker_dir.mkdir()
            (worker_dir / "cmdline").write_bytes(
                b"/usr/bin/python3\0-u\0/app/crawler_worker.py\0"
            )
            canary_dir = proc_root / "202"
            canary_dir.mkdir()
            (canary_dir / "cmdline").write_bytes(
                b"/usr/bin/docker\0run\0--name=noteai-xhs-canary\0"
            )

            self.assertEqual(collector._temporary_process_count(proc_root), 2)

    def test_host_labels_and_root_requirement_fail_closed(self):
        with self.assertRaisesRegex(collector.CollectionError, "host label"):
            collector.collect_host("UNKNOWN", FakeRunner({}))

        with mock.patch.object(os, "geteuid", return_value=501):
            with self.assertRaisesRegex(collector.CollectionError, "root"):
                collector.collect_host("API-C", FakeRunner({}))


if __name__ == "__main__":
    unittest.main()
