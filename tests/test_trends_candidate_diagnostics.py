"""Offline counts survive failed publication without retaining candidate content."""
import asyncio
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import hot_keywords
import market_timing_worker as worker
import security_redaction as safe
import trends_contract

PRIVATE = "PRIVATE_CANDIDATE_OR_COOKIE_NOT_FOR_LOGGING"


def candidate(source="search_phrase", domain="美食", keyword=PRIVATE):
    return {"keyword": keyword, "category": domain, "source": source,
            "count": 2, "search_vol": 80}


class CandidateProjectionTests(unittest.TestCase):
    def test_fixed_projection_has_only_six_domains_and_numeric_source_counts(self):
        rows = [candidate(), candidate("search_recommend"), candidate("homefeed_phrase"),
                candidate(PRIVATE), candidate(domain=PRIVATE)]
        value = worker._candidate_diagnostics(worker._candidate_domain_counts(rows), rows)
        self.assertEqual(set(value["domains"]), set(trends_contract.REQUIRED_DOMAINS))
        observed = value["domains"]["美食"]
        self.assertEqual(observed["input_count"], 4)
        self.assertEqual(observed["input_sources"], {"search_result": 1, "search_recommend": 1, "other": 2})
        self.assertIsNone(observed["evidence_count"])
        self.assertIsNone(observed["source_health_ok"])
        self.assertIsNone(value["freshness_ok"])
        self.assertIs(value["collection_blocked"], False)
        self.assertNotIn(PRIVATE, json.dumps(value))
        self.assertEqual(safe.sanitize_trends_candidate_diagnostics(value), value)

    def test_selection_loss_is_distinct_from_input_missing(self):
        rows = [candidate(), candidate("search_recommend")]
        value = worker._candidate_diagnostics(worker._candidate_domain_counts(rows), rows[1:])
        self.assertEqual(value["domains"]["美食"]["reason_codes"],
                         ["selection_dropped_search_result", "selection_reduced_count"])
        self.assertEqual(value["domains"]["旅行"]["reason_codes"], ["input_empty", "selected_empty"])

    def test_health_uses_actual_filtered_count_and_fixed_error(self):
        rows = [candidate(), candidate("search_recommend")]
        freshness = {"latest_run_domain_counts": {"美食": 1},
                     "latest_run_domain_source_health": {"美食": {
                         "ok": False, "error_code": "latest_run_search_result_missing",
                         "evidence_keys": [PRIVATE]}}}
        value = worker._candidate_diagnostics(worker._candidate_domain_counts(rows), rows, freshness)
        food = value["domains"]["美食"]
        self.assertEqual(food["selected_count"], 2)
        self.assertEqual(food["evidence_count"], 1)
        self.assertIs(food["source_health_ok"], False)
        self.assertEqual(food["reason_codes"], ["evidence_below_minimum", "latest_run_search_result_missing"])
        self.assertIsNone(value["domains"]["旅行"]["evidence_count"])
        self.assertIsNone(value["domains"]["旅行"]["source_health_ok"])
        self.assertIn("evidence_count_unavailable", value["domains"]["旅行"]["reason_codes"])
        self.assertNotIn(PRIVATE, json.dumps(value))

    def test_hostile_text_is_dropped_and_invalid_numbers_are_not_zeroed(self):
        rows = [candidate()]
        baseline = worker._candidate_diagnostics(worker._candidate_domain_counts(rows), rows)
        hostile = copy.deepcopy(baseline)
        hostile.update(cookie=PRIVATE, raw_response=PRIVATE)
        hostile["domains"][PRIVATE] = PRIVATE
        hostile["domains"]["美食"].update(keyword=PRIVATE, reason_codes=[PRIVATE, "selection_reduced_count"])
        projected = safe.sanitize_trends_candidate_diagnostics(hostile)
        self.assertNotIn(PRIVATE, json.dumps(projected))
        self.assertEqual(projected["domains"]["美食"]["reason_codes"], ["selection_reduced_count"])
        for invalid in (True, -1, "1", 1.5, 2**31, None):
            value = copy.deepcopy(baseline)
            value["domains"]["美食"]["input_count"] = invalid
            with self.subTest(invalid=invalid):
                self.assertEqual(safe.sanitize_trends_candidate_diagnostics(value), {})

    def test_missing_domain_source_mismatch_and_premature_health_are_rejected(self):
        rows = [candidate()]
        baseline = worker._candidate_diagnostics(worker._candidate_domain_counts(rows), rows)
        bad = copy.deepcopy(baseline)
        del bad["domains"]["健身"]
        self.assertEqual(safe.sanitize_trends_candidate_diagnostics(bad), {})
        for key, replacement in (("input_sources", {"search_result": 0, "search_recommend": 0, "other": 0}),
                                 ("evidence_count", 1), ("source_health_ok", False)):
            bad = copy.deepcopy(baseline)
            bad["domains"]["美食"][key] = replacement
            with self.subTest(key=key):
                self.assertEqual(safe.sanitize_trends_candidate_diagnostics(bad), {})

    def test_healthy_counts_do_not_claim_failed_or_unknown_quality(self):
        rows = [candidate("search_phrase" if index == 0 else "search_recommend", domain,
                          f"{domain}合成候选{index}")
                for domain in trends_contract.REQUIRED_DOMAINS for index in range(12)]
        freshness = {"latest_run_domain_counts": {domain: 12 for domain in trends_contract.REQUIRED_DOMAINS},
                     "latest_run_domain_source_health": {domain: {"ok": True, "error_code": ""}
                         for domain in trends_contract.REQUIRED_DOMAINS}}
        value = worker._candidate_diagnostics(worker._candidate_domain_counts(rows), rows, freshness)
        self.assertTrue(all(item["source_health_ok"] is True and item["reason_codes"] == []
                            for item in value["domains"].values()))

    def test_overall_freshness_and_collection_block_remain_separate_observations(self):
        counts = worker._candidate_domain_counts([])
        self.assertIsNone(worker._candidate_diagnostics(counts, [], {})["freshness_ok"])
        value = worker._candidate_diagnostics(counts, [], {"overview": {"ok": False}}, collection_blocked=True)
        self.assertIs(value["freshness_ok"], False)
        self.assertIs(value["collection_blocked"], True)
        self.assertEqual(safe.sanitize_trends_candidate_diagnostics({**value, "freshness_ok": 0}), {})


class CandidateWorkerTests(unittest.TestCase):
    def test_failed_publication_rolls_back_data_but_keeps_safe_counts_in_output(self):
        async def scrape(_adapter):
            attempt = trends_contract.admit_provider_request("search_notes")
            trends_contract.complete_provider_request(attempt, outcome="succeeded")
            return [candidate(keyword="美食本轮唯一合成趋势")]

        environment = {"NOTEAI_RUNTIME_ROLE": "xhs-http", "NOTEAI_XHS_SERVICE": "trends",
                       "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                       "NOTEAI_XHS_COLLECTION_SUSPENDED": "0", "NOTEAI_XHS_FRESHNESS_REQUIRED": "0",
                       "NOTEAI_MARKET_TIMING_REQUIRED": "0"}
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(hot_keywords, "DB_PATH", Path(directory) / "isolated.db"), \
                mock.patch.dict(os.environ, environment), \
                mock.patch.object(worker, "_scrape_selected_adapter", side_effect=scrape), \
                mock.patch.object(worker, "session_state_summary", return_value={
                    "configured": True, "auth_cookie_present": True, "auth_cookie_expired": False}), \
                mock.patch.object(worker, "collection_safety_status", return_value={"session_blocked": False}), \
                mock.patch.object(worker, "challenge_cooldown_status", return_value={"active": False}), \
                contextlib.redirect_stdout(out):
            with self.assertRaisesRegex(trends_contract.TrendsContractError,
                                        "trends_current_run_xhs_evidence_incomplete"):
                asyncio.run(worker.run_once(Path(directory) / "snapshot.json"))
            connection = hot_keywords._conn()
            try:
                for table in ("hot_keywords", "keyword_snapshots", "xhs_freshness_ledger",
                              "xhs_crawler_health", "xhs_trends_snapshot_evidence"):
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT status FROM xhs_trends_runs").fetchone()[0], "failed")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM xhs_trends_provider_attempts").fetchone()[0], 1)
            finally:
                connection.close()
        events = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith("{")]
        observations = [value for value in events if value.get("event") == "xhs_trends_candidate_diagnostics"]
        self.assertEqual([value["stage"] for value in observations], ["selection", "evidence_check"])
        self.assertEqual(observations[0]["domains"]["美食"]["input_count"], 1)
        self.assertEqual(observations[1]["domains"]["美食"]["evidence_count"], 1)
        self.assertIn("latest_run_search_recommend_missing", observations[1]["domains"]["美食"]["reason_codes"])
        self.assertEqual(observations[1]["domains"]["旅行"]["evidence_count"], 0)
        self.assertIs(observations[1]["freshness_ok"], False)
        self.assertIs(observations[1]["collection_blocked"], False)
        self.assertNotIn("美食本轮唯一合成趋势", json.dumps(observations, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
