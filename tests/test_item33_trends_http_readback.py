"""Synthetic supplied stdout, with no process, network, database or app imports."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest import mock

from tools import item33_trends_http_readback as reader


class Item33HttpReadbackTests(unittest.TestCase):
    def setUp(self):
        self.run = "6c2f3b23-33ac-4a92-a579-9f455d27e2b3"
        self.base = datetime(2026, 9, 19, 0, 5, tzinfo=timezone.utc)
        self.cycle = {"run_identity_sha256": hashlib.sha256(self.run.encode()).hexdigest(),
            "bucket_key": "2026-09-19", "started_at": self.base.isoformat(),
            "completed_at": (self.base + timedelta(seconds=40)).isoformat(), "attempts": []}
        self.lines = [{"event": "trends_run_started", "run_id": self.run,
                       "bucket_key": "2026-09-19", "status": "running"}]
        kinds = ["dsl", "session"] + ["homefeed"] * 10 + [kind for _ in range(12)
                                                                          for kind in ("search_recommend", "search_notes")]
        for index, kind in enumerate(kinds):
            start = self.base + timedelta(seconds=index + 1)
            end = start + timedelta(milliseconds=200)
            self.lines.append({"event": "xhs_trends_http_observation", "phase": "dispatch",
                "request_kind": kind, "sequence": index + 1, "at": start.isoformat()})
            diag = {"http_status": 200, "payload_kind": "non_json"} if kind == "dsl" else {
                "http_status": 200, "payload_kind": "object", "success_state": "true",
                "business_code_kind": "integer", "business_code": 0, "message_tags": []}
            if kind == "search_recommend":
                diag.update(business_code=1000, recommendation_items_total=10, recommendation_items_usable=10)
            self.lines.append({"event": "xhs_trends_http_observation", "phase": "response",
                "request_kind": kind, "sequence": index + 1, "at": end.isoformat(), "response_diagnostics": diag})
            if index >= 2:
                self.cycle["attempts"].append({"attempt_identity_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
                    "ordinal": index - 1, "endpoint": kind, "status": "succeeded",
                    "admitted_at": start.isoformat(), "completed_at": end.isoformat()})
        self.lines += [{"event": "trends_run_succeeded", "run_id": self.run, "bucket_key": "2026-09-19",
                        "status": "succeeded", "provider_calls": 34},
                       {"ok": True, "run_id": self.run, "bucket_key": "2026-09-19", "provider_calls": 34}]

    def read(self, *, lines=None):
        raw = b"\n".join(reader.encoded(item).rstrip(b"\n") for item in (self.lines if lines is None else lines))
        return reader.read_http_facts(raw, cycle=self.cycle, observed_at=self.base + timedelta(minutes=1))

    def test_complete_current_daemon_cycle_has_no_fabricated_exit(self):
        result = self.read()
        self.assertTrue(result["physical_http_verified"])
        self.assertIsNone(result["daemon_exit_code"])
        self.assertFalse(result["raw_output_saved"])
        self.assertEqual(result["physical_http"]["total_count"], 36)
        self.assertEqual(result["worker_receipt_sha256"], reader.digest(reader.encoded(result["worker_receipt"])))
        self.assertNotIn(self.run, json.dumps(result))

    def test_missing_boundary_or_success_return_stays_incomplete(self):
        for index in (0, -1, -2):
            with self.subTest(index=index):
                lines = copy.deepcopy(self.lines); lines.pop(index)
                result = self.read(lines=lines)
                self.assertFalse(result["physical_http_verified"])
                self.assertIsNone(result["physical_http"]["automatic_retry_count"])

    def test_wrong_identity_second_run_and_http_outside_range_are_rejected(self):
        for change in ("identity", "second", "outside"):
            lines = copy.deepcopy(self.lines)
            if change == "identity": lines[0]["run_id"] = "different-run"
            if change == "second": lines.append(dict(lines[0]))
            if change == "outside": lines.insert(0, lines.pop(1))
            with self.subTest(change=change): self.assertFalse(self.read(lines=lines)["physical_http_verified"])

    def test_unknown_is_retained_and_does_not_become_zero_retry(self):
        self.lines[2]["phase"] = "unknown"
        result = self.read()
        self.assertFalse(result["physical_http_verified"])
        self.assertEqual(result["worker_receipt"]["physical_http_summary"]["unknown_events_observed"], 1)
        self.assertIsNone(result["physical_http"]["automatic_retry_count"])

    def test_code1000_retains_original_value_and_requires_usable_data(self):
        response = next(row for row in self.lines if row.get("phase") == "response" and row["request_kind"] == "search_recommend")
        self.assertEqual(response["response_diagnostics"]["business_code"], 1000)
        response["response_diagnostics"]["recommendation_items_usable"] = 0
        self.assertFalse(self.read()["physical_http_verified"])

    def test_raw_secret_fields_and_unstructured_logs_are_not_copied(self):
        secret = "synthetic-never-copy-me"
        self.lines[2].update(cookie=secret, url=secret, headers={"x-private": secret})
        self.lines[2]["response_diagnostics"]["body"] = secret
        self.lines.insert(0, {"event": [secret], "unstructured": secret})
        result = self.read()
        self.assertTrue(result["physical_http_verified"])
        self.assertNotIn(secret, json.dumps(result))

    def test_partial_failure_diagnostics_keep_only_safe_fields(self):
        self.lines.insert(3, {"event": "xhs_trends_provider_failure", "stage": "dsl",
            "error_code": "adapter_failure_unknown", "exception": "private-value",
            "transport_diagnostics": {"failure_phase": "transport", "request_started": True}})
        result = self.read()
        self.assertFalse(result["physical_http_verified"])
        self.assertEqual(result["worker_receipt"]["provider_failures"][0]["stage"], "dsl")
        self.assertNotIn("private-value", json.dumps(result))

    def test_reused_clock_or_changed_attempt_ledger_rejects(self):
        self.cycle["attempts"][0]["endpoint"] = "search_notes"
        self.assertFalse(self.read()["physical_http_verified"])
        self.cycle["attempts"][0]["endpoint"] = "homefeed"
        self.lines[1]["at"] = "2026-09-18T00:05:00+00:00"
        self.assertFalse(self.read()["physical_http_verified"])

    def test_skipped_same_bucket_return_after_completed_cycle_adds_no_http(self):
        self.lines += [{"event": "trends_run_skipped", "status": "skipped", "provider_calls": 0},
                       {"ok": True, "skipped": True, "provider_called": False}]
        self.assertTrue(self.read()["physical_http_verified"])

    def test_size_and_source_binding_fail_before_parsing(self):
        with self.assertRaisesRegex(reader.Item33HttpReadbackError, "output_size"):
            reader.read_http_facts(b"x" * (reader.MAX_OUTPUT + 1), cycle=self.cycle, observed_at=self.base)
        with mock.patch.dict(reader.gate.ITEM33_V5_RUNTIME_OVERLAY_SHA256, {"model/security_redaction.py": "0" * 64}):
            with self.assertRaisesRegex(reader.Item33HttpReadbackError, "diagnostic_source_binding"):
                self.read()

    def test_saved_receipt_rechecks_exact_source_and_projection(self):
        result = self.read()
        cycle = {**self.cycle, "physical_http": result["physical_http"]}
        receipt = result["worker_receipt"]
        self.assertTrue(reader.verify_worker_receipt(receipt, cycle))
        for key, value in (("reader_source_sha256", "0" * 64), ("output_size", True),
                           ("provider_failures", [{}]), ("reason_codes", ["run_not_completed"]),
                           ("secret_values_recorded", 0)):
            with self.subTest(key=key):
                changed = {**copy.deepcopy(receipt), key: value}
                cycle["physical_http"]["worker_receipt_sha256"] = reader.digest(reader.encoded(changed))
                self.assertFalse(reader.verify_worker_receipt(changed, cycle))


if __name__ == "__main__":
    unittest.main()
