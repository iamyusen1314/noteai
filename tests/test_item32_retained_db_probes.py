"""Retain real-shaped safe DB observations without contacting any database."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import execute_item32_readonly_trends_successor as executor


class RetainedProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.evidence = self.root / "evidence"
        self.runtime.mkdir()
        self.evidence.mkdir()
        self.observation = {
            "observed_at": "2026-09-16T02:30:00+00:00",
            "server_enforced_read_only": True, "write_count": 0,
            "tuple_write_count": 0, "write_tables": [], "xid_assigned": False,
            "transaction_rolled_back": True, "session_identity_sha256": "a" * 64,
            "readback_query_sha256": executor.DB_PROBE_QUERYSET_SHA256,
            "active_or_manual_count": 0, "session_blocked_count": 0,
            "today_attempt_count": 0, "secret_values_recorded": False,
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_probe(self, value):
        with mock.patch.object(executor, "_run", return_value=subprocess.CompletedProcess(
                [], 0, (json.dumps(value) + "\n").encode(), b"")), mock.patch.object(
                executor, "_remove_registered_container"):
            return executor._run_db_probe(self.runtime, "synthetic-private-dsn", "after", {}, self.evidence)

    def test_complete_safe_projection_is_retained_and_secret_env_removed(self):
        self.assertEqual(self.run_probe(self.observation), self.observation)
        path = self.evidence / "database-after-probe.json"
        self.assertEqual(json.loads(path.read_bytes()), self.observation)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.runtime / "db-after.env").exists())
        self.assertNotIn(b"synthetic-private-dsn", path.read_bytes())

    def test_rejected_nonfresh_observation_still_has_complete_original_fields(self):
        self.observation["today_attempt_count"] = 1
        with self.assertRaisesRegex(executor.Item32Error, "production_db_preflight"):
            self.run_probe(self.observation)
        self.assertEqual(json.loads((self.evidence / "database-after-probe.json").read_bytes()), self.observation)
        self.assertFalse((self.runtime / "db-after.env").exists())

    def test_arbitrary_output_fields_are_not_saved(self):
        self.observation["connection_string"] = "synthetic-private-dsn"
        with self.assertRaisesRegex(executor.Item32Error, "db_probe_output"):
            self.run_probe(self.observation)
        self.assertEqual(list(self.evidence.iterdir()), [])
        self.assertFalse((self.runtime / "db-after.env").exists())

    def test_second_observation_cannot_overwrite_first(self):
        self.run_probe(self.observation)
        original = (self.evidence / "database-after-probe.json").read_bytes()
        with self.assertRaisesRegex(executor.Item32Error, "db_probe_already_recorded"):
            self.run_probe(self.observation)
        self.assertEqual((self.evidence / "database-after-probe.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
