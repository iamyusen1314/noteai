"""Isolated collector lifecycle tests; real LISTEN/SQL tests live with runtime."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tools import item33_trends_capture_service as service
from tools import item33_trends_runtime_capture as capture
from tests import test_item33_trends_runtime_capture as fixtures


@unittest.skipUnless(os.geteuid() == 0, "isolated container root metadata fixture required")
class CaptureServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.config = fixtures.config_fixture()
        self.current = datetime.now(timezone.utc)
        self.connections = []
        self.events = []
        self.auto_request = True
        self.bad_request = False
        self.failed = False
        test = self

        class Session:
            failure = False
            def __init__(self, config, root, clock):
                test.events.append("session")
            def start(self, listener, control):
                test.assertIsNot(listener, control)
                test.events.append("listening")
            def serve(self, path):
                test.events.append("serving")
                self.failure = test.failed
                if test.auto_request:
                    binding = {"activation_identity_sha256": test.config["activation_identity_sha256"],
                        "configuration_sha256": capture.sha(capture.encoded(test.config)),
                        "bucket_key": test.config["bucket_key"]}
                    if test.bad_request:
                        binding["activation_identity_sha256"] = "f" * 64
                    capture.exclusive(test.root / "seal-request.json", capture.encoded(
                        {"schema": "noteai.item33.capture_seal_request.v1", **binding}) + b"\n")
            def seal(self, control, *, catalog_proof_factory):
                test.events.append("writers_closed_and_end_barrier")
                proof = catalog_proof_factory()
                test.assertEqual(proof, {"proof": "synthetic"})
                return {"run_identity_sha256": "c" * 64, "proof": proof}
            def close(self):
                test.events.append("session_closed")
        self.session_factory = Session

    def connection(self):
        conn = SimpleNamespace(autocommit=True, info=SimpleNamespace(transaction_status=0), closed=False)
        def close():
            conn.closed = True
        conn.close = close
        self.connections.append(conn)
        return conn

    def catalog(self, connection, *, config, now):
        self.assertIs(connection, self.connections[2])
        self.events.append("catalog")
        return {"observed": len(self.events)}

    def build(self, before, after, *, config):
        self.assertLessEqual(before["observed"], after["observed"])
        self.events.append("preflight_proof" if before is after else "proof")
        return {"proof": "synthetic"}

    def run_capture(self, **kwargs):
        args = dict(config=self.config, root=self.root, deadline=self.current + timedelta(minutes=1),
            connection_factory=self.connection, catalog_reader=self.catalog, proof_builder=self.build,
            session_factory=self.session_factory, now=lambda:self.current, monotonic=lambda:0,
            pause=lambda _:self.fail("ready request must not wait"))
        args.update(kwargs)
        return service.run_service(**args)

    def test_seal_reads_after_catalog_only_after_real_session_barrier_callback(self):
        result = self.run_capture()
        self.assertEqual(result["state"], "SEALED")
        self.assertEqual(self.events, ["catalog", "preflight_proof", "session", "listening", "serving",
            "writers_closed_and_end_barrier", "catalog", "proof", "session_closed"])
        self.assertTrue(all(conn.closed for conn in self.connections))
        close = json.loads((self.root / "service-close.json").read_bytes())
        self.assertEqual(close["state"], "CONNECTIONS_CLOSED")
        self.assertEqual(close["connection_count"], 3)

    def test_second_start_preserves_unknown_and_does_not_connect(self):
        self.run_capture()
        original = (self.root / "service-started.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_capture()
        self.assertEqual(len(self.connections), 3)
        self.assertEqual((self.root / "service-started.json").read_bytes(), original)

    def test_wrong_activation_seal_request_stops_without_sealing(self):
        self.bad_request = True
        with self.assertRaisesRegex(service.CaptureServiceError, "capture_service_unknown"):
            self.run_capture()
        self.assertNotIn("writers_closed_and_end_barrier", self.events)
        self.assertFalse((self.root / "service-result.json").exists())
        self.assertTrue(all(conn.closed for conn in self.connections))

    def test_listener_failure_closes_connections_and_preserves_partial_files(self):
        self.failed = True
        with self.assertRaises(service.CaptureServiceError):
            self.run_capture()
        self.assertTrue((self.root / "service-ready.json").exists())
        self.assertTrue((self.root / "service-failure.json").exists())
        self.assertTrue(all(conn.closed for conn in self.connections))

    def test_connection_error_never_escapes_or_enters_receipt(self):
        def broken():
            raise RuntimeError("postgresql://synthetic-secret@example.invalid/database")
        with self.assertRaisesRegex(service.CaptureServiceError, "^capture_service_unknown$"):
            self.run_capture(connection_factory=broken)
        self.assertNotIn("synthetic-secret", (self.root / "service-failure.json").read_text())
        self.assertFalse((self.root / "service-ready.json").exists())

    def test_expired_deadline_never_opens_connection(self):
        with self.assertRaisesRegex(service.CaptureServiceError, "service_window"):
            self.run_capture(deadline=self.current)
        self.assertEqual(self.connections, [])
        self.assertFalse((self.root / "service-started.json").exists())

    def test_monotonic_timeout_cannot_be_extended_by_wall_clock(self):
        values = iter((0, 100))
        with self.assertRaisesRegex(service.CaptureServiceError, "capture_service_unknown"):
            self.run_capture(monotonic=lambda:next(values))
        self.assertNotIn("writers_closed_and_end_barrier", self.events)

    def test_unsafe_catalog_is_rejected_before_listener_ready_or_any_worker(self):
        def invalid(before, after, *, config):
            self.assertIs(before, after)
            raise ValueError("synthetic unsafe closure")
        with self.assertRaisesRegex(service.CaptureServiceError, "capture_service_unknown"):
            self.run_capture(proof_builder=invalid)
        self.assertNotIn("session", self.events)
        self.assertFalse((self.root / "service-ready.json").exists())
        self.assertTrue(all(conn.closed for conn in self.connections))


if __name__ == "__main__":
    unittest.main()
