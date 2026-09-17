"""Offline preservation of bounded candidate diagnostics after a failed cycle."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import execute_item32_readonly_trends_successor as launcher

PRIVATE = "PRIVATE_CANDIDATE_OR_COOKIE_DO_NOT_RECORD"
DOMAINS = ("美食", "旅行", "穿搭", "美妆", "家居", "健身")


def event(stage="selection"):
    checked = stage == "evidence_check"
    return {
        "event": "xhs_trends_candidate_diagnostics", "stage": stage,
        "freshness_ok": False if checked else None, "collection_blocked": False,
        "domains": {domain: {
            "input_count": 30, "selected_count": 15,
            "input_sources": {"search_result": 15, "search_recommend": 15, "other": 0},
            "selected_sources": {"search_result": 0, "search_recommend": 15, "other": 0},
            "evidence_count": 15 if checked else None,
            "source_health_ok": False if checked else None,
            "reason_codes": ["latest_run_search_result_missing"] if checked else [],
        } for domain in DOMAINS},
    }


class CandidateReceiptTests(unittest.TestCase):
    def receipt(self, values):
        binding = dict(launcher.RUNTIME_OVERLAY_SHA256)
        binding["model/security_redaction.py"] = hashlib.sha256(
            (ROOT / "model/security_redaction.py").read_bytes()).hexdigest()
        raw = b"\n".join(json.dumps(value, ensure_ascii=False).encode() for value in values)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            launcher, "RUNTIME_OVERLAY_SHA256", binding
        ):
            launcher._record_worker_receipt(Path(directory), raw, exit_code=1, secret_values=[])
            return json.loads((Path(directory) / "worker-receipt.json").read_bytes())

    def test_failed_worker_keeps_actual_candidate_counts_without_claiming_success(self):
        values = [event(), event("evidence_check"), {
            "event": "trends_run_failed", "status": "failed", "provider_calls": 34,
            "error_code": "trends_current_run_xhs_evidence_incomplete",
        }]
        receipt = self.receipt(values)
        self.assertEqual(receipt["candidate_diagnostics"], values[:2])
        self.assertEqual(receipt["invalid_candidate_diagnostics"], 0)
        self.assertEqual(receipt["exit_code"], 1)
        self.assertEqual(receipt["structured_events"][0]["status"], "failed")
        self.assertFalse(receipt["physical_http_summary"]["observation_complete"])

    def test_receipt_reprojects_raw_fields_without_keyword_cookie_or_unknown_reason(self):
        value = event("evidence_check")
        value.update(cookie=PRIVATE, response=PRIVATE, keyword=PRIVATE)
        for row in value["domains"].values():
            row["keyword"] = PRIVATE
            row["reason_codes"].append(PRIVATE)
        receipt = self.receipt([event(), value])
        self.assertNotIn(PRIVATE, json.dumps(receipt))
        self.assertEqual(len(receipt["candidate_diagnostics"]), 2)
        self.assertEqual(receipt["candidate_diagnostics"][1]["domains"]["美食"]["reason_codes"],
                         ["latest_run_search_result_missing"])

    def test_duplicate_and_out_of_order_events_are_bounded_and_reported(self):
        receipt = self.receipt([event("evidence_check"), event(), event(),
                                event("evidence_check"), event("evidence_check")])
        self.assertEqual([value["stage"] for value in receipt["candidate_diagnostics"]],
                         ["selection", "evidence_check"])
        self.assertEqual(receipt["invalid_candidate_diagnostics"], 3)

    def test_old_receipt_has_no_invented_candidate_counts(self):
        receipt = self.receipt([{"event": "trends_run_failed", "status": "failed",
                                 "error_code": "trends_current_run_xhs_evidence_incomplete"}])
        self.assertEqual(receipt["candidate_diagnostics"], [])
        self.assertEqual(receipt["invalid_candidate_diagnostics"], 0)

    def test_invalid_stage_does_not_enter_receipt(self):
        receipt = self.receipt([event(PRIVATE)])
        self.assertEqual(receipt["candidate_diagnostics"], [])
        self.assertEqual(receipt["invalid_candidate_diagnostics"], 1)
        self.assertNotIn(PRIVATE, json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
