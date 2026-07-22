import asyncio
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

hot_keywords = importlib.import_module("hot_keywords")
market_timing_worker = importlib.import_module("market_timing_worker")
xhs_acquisition = importlib.import_module("xhs_acquisition")
xhs_health_probe = importlib.import_module("xhs_health_probe")
admin_server = importlib.import_module("admin_server")
scheduler_a = importlib.import_module("scheduler_a")


def _real_xhs_rows() -> list[dict]:
    rows = []
    for domain in hot_keywords.CORE_EVIDENCE_DOMAINS:
        for row in hot_keywords.baseline_evidence_rows((domain,), min_per_domain=16):
            cloned = dict(row)
            cloned["source"] = "search_phrase"
            cloned["count"] = 4
            rows.append(cloned)
    return rows


class XHSAcquisitionLedgerTests(unittest.TestCase):
    def setUp(self):
        self._local_runtime = patch.dict(os.environ, {"NOTEAI_RUNTIME_ROLE": "local"})
        self._local_runtime.start()

    def tearDown(self):
        self._local_runtime.stop()

    def _run_scheduler_circuit_scenario(
        self,
        *,
        challenge: bool,
        login: bool = False,
        circuit_state: str = "closed",
        stop: bool = True,
        response_payload: dict | None = None,
        response_url: str = "",
        response_json_error: bool = False,
    ):
        events = {
            "homefeed_gotos": 0,
            "search_gotos": 0,
            "blank_gotos": 0,
            "browser_launches": 0,
            "browser_launch_kwargs": [],
            "input_calls": 0,
            "scrolls": 0,
            "goto_kinds": [],
        }
        payload = {"data": {}} if response_payload is None else response_payload

        class FakeResponse:
            def __init__(self, url):
                self.url = url
                self.status = 200

            async def json(self):
                if response_json_error:
                    raise ValueError("synthetic non-json response")
                return payload

        class FakeMouse:
            async def wheel(self, _x, _y):
                events["scrolls"] += 1
                return None

        class FakePage:
            def __init__(self):
                self.url = "about:blank"
                self.mouse = FakeMouse()
                self.handlers = []

            def on(self, event, handler):
                if event == "response":
                    self.handlers.append(handler)

            def remove_listener(self, event, handler):
                if event == "response" and handler in self.handlers:
                    self.handlers.remove(handler)

            async def goto(self, url, **_kwargs):
                is_search_target = "search_result" in url
                if "search_result" in url:
                    events["search_gotos"] += 1
                    if challenge and events["search_gotos"] == 1:
                        self.url = "https://www.xiaohongshu.com/challenge"
                        events["goto_kinds"].append("search_challenge")
                    elif login and events["search_gotos"] == 1:
                        self.url = "https://www.xiaohongshu.com/login"
                        events["goto_kinds"].append("search_login")
                    else:
                        self.url = url
                        events["goto_kinds"].append("search")
                elif "/explore" in url:
                    events["homefeed_gotos"] += 1
                    self.url = url
                    events["goto_kinds"].append("homefeed")
                elif url == "about:blank":
                    events["blank_gotos"] += 1
                    self.url = url
                    events["goto_kinds"].append("blank")
                else:
                    self.url = url
                    events["goto_kinds"].append("other")
                emitted_url = (
                    response_url
                    if response_url and is_search_target and self.url == url
                    else self.url
                )
                for handler in list(self.handlers):
                    await handler(FakeResponse(emitted_url))

            async def close(self):
                return None

        class FakeContext:
            async def route(self, _pattern, _handler):
                return None

            async def add_init_script(self, _script):
                return None

            async def new_page(self):
                return FakePage()

            async def close(self):
                return None

        class FakeBrowser:
            async def new_context(self, **_kwargs):
                return FakeContext()

            async def close(self):
                return None

        class FakeChromium:
            async def launch(self, **kwargs):
                events["browser_launches"] += 1
                events["browser_launch_kwargs"].append(kwargs)
                return FakeBrowser()

        class FakePlaywrightContext:
            async def __aenter__(self):
                return SimpleNamespace(chromium=FakeChromium())

            async def __aexit__(self, *_args):
                return None

        async def fake_search_input(_page, _seed, diagnostics=None, **_kwargs):
            events["input_calls"] += 1
            if diagnostics is not None:
                diagnostics["input"].update({"found": 1, "visible": 1, "typed": 1})
            return True, ""

        async def no_sleep(_seconds):
            return None

        search_seeds = {
            category: (f"{category}一", f"{category}二")
            for category in ("美食", "美妆", "穿搭", "旅行", "数码", "家居")
        }
        playwright_package = ModuleType("playwright")
        playwright_async_api = ModuleType("playwright.async_api")
        playwright_async_api.async_playwright = lambda: FakePlaywrightContext()
        playwright_package.async_api = playwright_async_api
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {
                "playwright": playwright_package,
                "playwright.async_api": playwright_async_api,
            }))
            for name, value in (
                ("CHANNELS", [("https://www.xiaohongshu.com/explore", "美食")]),
                ("SEARCH_SEEDS", search_seeds),
                ("SEARCH_SEEDS_PER_CATEGORY", 2),
                ("SEARCH_DISCOVERY_ENABLED", True),
                ("BROWSER_TARGETS_PER_SESSION", 1),
                ("STOP_ON_CHALLENGE", stop),
                ("SCROLL_ROUNDS", 0),
                ("SEARCH_SCROLL_ROUNDS", 0),
                ("CHANNEL_SETTLE_SECONDS", 0),
                ("SEARCH_SETTLE_SECONDS", 0),
            ):
                stack.enter_context(patch.object(scheduler_a, name, value))
            stack.enter_context(patch.object(scheduler_a, "_get_session_state", return_value=None))
            stack.enter_context(patch.object(scheduler_a, "_trigger_search_input", fake_search_input))
            stack.enter_context(patch.object(scheduler_a.asyncio, "sleep", no_sleep))
            with scheduler_a.search_circuit_context({"state": circuit_state}):
                result = asyncio.run(scheduler_a.scrape_once())
        return result, events

    def test_baseline_rows_do_not_satisfy_real_xhs_freshness(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                result = xhs_acquisition.record_scrape_freshness(
                    hot_keywords.baseline_evidence_rows(("美食",), min_per_domain=16),
                    run_id="baseline-only",
                    domains=("美食",),
                )

                self.assertFalse(result["overview"]["ok"])
                status = xhs_acquisition.freshness_status("美食")
                self.assertFalse(status["ok"])
                self.assertEqual(status["evidence_count"], 0)
                self.assertEqual(status["status"], "insufficient")
        finally:
            hot_keywords.DB_PATH = original_db

    def test_real_xhs_rows_satisfy_core_domain_freshness(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                result = xhs_acquisition.record_scrape_freshness(_real_xhs_rows(), run_id="real-xhs")

                self.assertTrue(result["overview"]["ok"])
                self.assertEqual(result["overview"]["missing_domains"], [])
                for domain in hot_keywords.CORE_EVIDENCE_DOMAINS:
                    status = xhs_acquisition.freshness_status(domain)
                    self.assertTrue(status["ok"], domain)
                    self.assertGreaterEqual(status["evidence_count"], status["minimum"])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_same_day_real_evidence_accumulates_by_unique_keyword(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                rows = []
                for row in hot_keywords.baseline_evidence_rows(("美食",), min_per_domain=16):
                    cloned = dict(row)
                    cloned["source"] = "search_phrase"
                    cloned["count"] = 4
                    rows.append(cloned)

                first = xhs_acquisition.record_scrape_freshness(
                    rows[:7], run_id="accumulate-1", domains=("美食",), min_count=12,
                    session_status={"configured": True, "auth_cookie_present": True},
                )
                self.assertFalse(first["overview"]["ok"])
                self.assertEqual(first["overview"]["domains"][0]["evidence_count"], 7)

                duplicate = xhs_acquisition.record_scrape_freshness(
                    rows[:7], run_id="accumulate-duplicate", domains=("美食",), min_count=12,
                    session_status={"configured": True, "auth_cookie_present": True},
                )
                self.assertEqual(duplicate["overview"]["domains"][0]["evidence_count"], 7)

                completed = xhs_acquisition.record_scrape_freshness(
                    rows[7:14], run_id="accumulate-2", domains=("美食",), min_count=12,
                    session_status={"configured": True, "auth_cookie_present": True},
                )
                self.assertTrue(completed["overview"]["ok"])
                self.assertEqual(completed["overview"]["domains"][0]["evidence_count"], 13)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_latest_run_source_degradation_does_not_erase_cumulative_freshness(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                rows = []
                for index, row in enumerate(
                    hot_keywords.baseline_evidence_rows(("美食",), min_per_domain=16)
                ):
                    cloned = dict(row)
                    cloned["source"] = "search_recommend" if index % 2 else "search_phrase"
                    cloned["count"] = 4
                    rows.append(cloned)
                session = {"configured": True, "auth_cookie_present": True}

                first = xhs_acquisition.record_scrape_freshness(
                    rows, run_id="source-healthy", domains=("美食",),
                    session_status=session,
                )
                self.assertTrue(first["overview"]["ok"])
                self.assertTrue(first["overview"]["latest_run_source_health"]["ok"])

                degraded_rows = [
                    dict(row, source="search_phrase", keyword=f"{row['keyword']}-latest")
                    for row in rows[:4]
                ]
                second = xhs_acquisition.record_scrape_freshness(
                    degraded_rows, run_id="source-degraded", domains=("美食",),
                    session_status=session,
                )

                latest = second["overview"]["latest_run_source_health"]
                self.assertTrue(second["overview"]["ok"])
                self.assertFalse(latest["ok"])
                self.assertEqual(latest["status"], "degraded")
                self.assertEqual(latest["error_code"], "latest_run_search_recommend_missing")
                self.assertEqual(
                    set(latest["source_breakdown"]),
                    {"homefeed", "search_result", "search_recommend", "hot_search", "other"},
                )
                self.assertGreater(latest["source_breakdown"]["search_result"], 0)
                self.assertEqual(latest["source_breakdown"]["search_recommend"], 0)

                health = xhs_acquisition.recent_health(domain="美食", adapter="scheduler_a")[0]
                self.assertEqual(health["status"], "degraded")
                self.assertEqual(health["error_code"], "latest_run_search_recommend_missing")
                self.assertTrue(health["profile_cookie_valid"])
                self.assertFalse(health["risk_login_detected"])

                probe = xhs_acquisition.freshness_probe(("美食",))
                self.assertTrue(probe["ok"])
                self.assertEqual(probe["missing_domains"], [])
                self.assertTrue(probe["action_required"])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_latest_run_source_health_reads_legacy_source_counts(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                xhs_acquisition.record_health(xhs_acquisition.CrawlerHealth(
                    run_id="legacy-source-details",
                    adapter="scheduler_a",
                    domain="美食",
                    status="ok",
                    evidence_count=3,
                    details={
                        "source_counts": {"search_phrase": 2, "search_recommend": 1},
                        "latest_run_evidence_count": 3,
                    },
                ))

                latest = xhs_acquisition.latest_run_source_health(("美食",))
                self.assertTrue(latest["available"])
                self.assertTrue(latest["ok"])
                self.assertEqual(latest["source_breakdown"]["search_result"], 2)
                self.assertEqual(latest["source_breakdown"]["search_recommend"], 1)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_latest_run_source_health_reports_each_missing_search_source(self):
        cases = (
            (
                {"search_recommend": 2},
                "latest_run_search_result_missing",
                ["search_result"],
            ),
            (
                {"search_phrase": 2},
                "latest_run_search_recommend_missing",
                ["search_recommend"],
            ),
            (
                {"homefeed_phrase": 2},
                "latest_run_search_sources_missing",
                ["search_result", "search_recommend"],
            ),
        )
        for source_counts, error_code, missing_sources in cases:
            with self.subTest(error_code=error_code):
                health = xhs_acquisition._build_latest_run_source_health(
                    source_counts,
                    evidence_count=2,
                )
                self.assertEqual(health["status"], "degraded")
                self.assertEqual(health["error_code"], error_code)
                self.assertEqual(health["missing_sources"], missing_sources)

    def test_challenge_cooldown_scans_past_newer_cooldown_rows(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                now = datetime.now()
                challenge_at = now - timedelta(minutes=20)
                xhs_acquisition.record_health({
                    "run_id": "challenge-run",
                    "adapter": "scheduler_a",
                    "domain": "美食",
                    "status": "degraded",
                    "error_code": "access_challenge_detected",
                    "checked_at": challenge_at.isoformat(),
                    "details": {"access_status": "challenge"},
                })
                xhs_acquisition.record_health({
                    "run_id": "cooldown-run",
                    "adapter": "scheduler_a",
                    "domain": "美食",
                    "status": "degraded",
                    "error_code": "access_challenge_cooldown_active",
                    "checked_at": (now - timedelta(minutes=5)).isoformat(),
                    "details": {"access_status": "cooldown"},
                })

                active = xhs_acquisition.challenge_cooldown_status(
                    now=now,
                    cooldown_minutes=360,
                )
                expired = xhs_acquisition.challenge_cooldown_status(
                    now=now + timedelta(hours=7),
                    cooldown_minutes=360,
                )

                self.assertTrue(active["active"])
                self.assertEqual(active["last_challenge_at"], challenge_at.isoformat())
                self.assertGreater(active["remaining_seconds"], 0)
                self.assertFalse(expired["active"])
                self.assertEqual(expired["remaining_seconds"], 0)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_challenge_health_distinguishes_valid_cookie_and_hides_diagnostics(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                diagnostics = scheduler_a.new_discovery_diagnostics()
                diagnostics["targets"].update({
                    "planned": 12, "started": 1, "completed": 1, "skipped": 11,
                })
                diagnostics["final_page_class"]["challenge"] = 1
                diagnostics["circuit"] = {
                    "state": "open", "skipped_reason": "challenge_detected",
                }
                diagnostics["diagnostic_error_codes"] = [
                    "possible_access_challenge",
                    "search_targets_skipped_after_challenge",
                ]
                xhs_acquisition.record_scrape_freshness(
                    [],
                    run_id="challenge-cookie-valid",
                    domains=("美食",),
                    session_status={
                        "configured": True,
                        "auth_cookie_present": True,
                        "auth_cookie_expired": False,
                    },
                    discovery_diagnostics=diagnostics,
                )

                internal = xhs_acquisition.recent_health(adapter="scheduler_a")[0]
                public = xhs_acquisition.public_recent_health(adapter="scheduler_a")[0]
                self.assertEqual(internal["status"], "degraded")
                self.assertEqual(internal["error_code"], "access_challenge_detected")
                self.assertTrue(internal["profile_cookie_valid"])
                self.assertFalse(internal["risk_login_detected"])
                self.assertEqual(public["access_status"], "challenge")
                self.assertEqual(public["error_code"], "access_challenge_detected")
                self.assertIn("details", public)
                self.assertIn("error_summary", public)
                self.assertNotIn("discovery_diagnostics", json.dumps(public, ensure_ascii=False))
        finally:
            hot_keywords.DB_PATH = original_db

    def test_public_recent_health_preserves_safe_legacy_shape_and_filters_unknown_data(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                base_details = {
                    "access_status": "normal",
                    "latest_run_evidence_count": 3,
                    "session_configured": True,
                    "latest_run_source_breakdown": {
                        "homefeed": 2,
                        "search_result": 1,
                        "private-keyword-source": 99,
                    },
                    "latest_run_source_health": {
                        "available": True,
                        "ok": False,
                        "status": "degraded",
                        "evidence_count": 3,
                        "source_breakdown": {"homefeed": 2, "search_result": 1},
                        "missing_sources": ["search_recommend", "private-source"],
                        "error_code": "latest_run_search_recommend_missing",
                        "cookie": "private-cookie",
                        "source_url": "https://secret.invalid/private",
                    },
                    "discovery_diagnostics": {"response_body": "private-body"},
                    "keyword": "private-keyword",
                }
                rows = (
                    {
                        "run_id": "known-safe-code",
                        "error_code": "selector_changed",
                        "error_summary": "private arbitrary selector exception",
                        "details": base_details,
                    },
                    {
                        "run_id": "unknown-code",
                        "error_code": "private_exception_class",
                        "error_summary": "https://secret.invalid unknown failure private-cookie",
                        "details": {**base_details, "access_status": "private-state"},
                    },
                    {
                        "run_id": "challenge-code",
                        "error_code": "access_challenge_detected",
                        "error_summary": "private challenge body",
                        "details": {**base_details, "access_status": "challenge"},
                    },
                    {
                        "run_id": "cooldown-code",
                        "error_code": "access_challenge_cooldown_active",
                        "error_summary": "private cooldown body",
                        "details": {**base_details, "access_status": "cooldown"},
                    },
                )
                for offset, row in enumerate(rows):
                    xhs_acquisition.record_health({
                        "adapter": "scheduler_a",
                        "domain": "美食",
                        "status": "degraded",
                        "checked_at": f"2026-07-11T08:0{offset}:00",
                        **row,
                    })

                public = {
                    row["run_id"]: row
                    for row in xhs_acquisition.public_recent_health(adapter="scheduler_a")
                }

                known = public["known-safe-code"]
                self.assertIn("error_summary", known)
                self.assertIn("details", known)
                self.assertEqual(known["error_code"], "selector_changed")
                self.assertEqual(
                    known["error_summary"],
                    "Crawler selector validation failed",
                )
                self.assertEqual(known["details"]["latest_run_evidence_count"], 3)
                self.assertEqual(
                    known["details"]["latest_run_source_health"]["error_code"],
                    "latest_run_search_recommend_missing",
                )

                unknown = public["unknown-code"]
                self.assertEqual(unknown["error_code"], "")
                self.assertEqual(unknown["error_summary"], "")
                self.assertEqual(unknown["access_status"], "normal")
                self.assertEqual(unknown["details"]["access_status"], "normal")

                challenge = public["challenge-code"]
                cooldown = public["cooldown-code"]
                self.assertEqual(challenge["access_status"], "challenge")
                self.assertEqual(
                    challenge["error_summary"],
                    "Search discovery stopped after an access challenge",
                )
                self.assertEqual(cooldown["access_status"], "cooldown")
                self.assertEqual(
                    cooldown["error_summary"],
                    "Search discovery skipped during access challenge cooldown",
                )

                serialized = json.dumps(public, ensure_ascii=False)
                for secret in (
                    "secret.invalid",
                    "private-cookie",
                    "private-keyword",
                    "private-body",
                    "private arbitrary selector exception",
                    "private_exception_class",
                    "private challenge body",
                    "private cooldown body",
                    "discovery_diagnostics",
                ):
                    self.assertNotIn(secret, serialized)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_zero_evidence_records_actionable_cookie_health(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                xhs_acquisition.record_scrape_freshness(
                    [], run_id="missing-cookie", domains=("美食",),
                    session_status={"configured": False, "auth_cookie_present": False},
                )
                health = xhs_acquisition.recent_health(domain="美食", adapter="scheduler_a")
                self.assertEqual(health[0]["status"], "failed")
                self.assertEqual(health[0]["error_code"], "cookie_not_configured")
                self.assertTrue(health[0]["risk_login_detected"])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_session_summary_never_exposes_cookie_values(self):
        future = 4_102_444_800
        state = {"cookies": [
            {"name": "web_session", "value": "secret-session", "expires": future},
            {"name": "a1", "value": "secret-device", "expires": future},
        ]}
        with patch.object(scheduler_a, "_get_session_state", return_value=state):
            summary = scheduler_a.session_state_summary()
        self.assertTrue(summary["configured"])
        self.assertTrue(summary["auth_cookie_present"])
        self.assertFalse(summary["auth_cookie_expired"])
        self.assertEqual(summary["cookie_count"], 2)
        self.assertNotIn("secret-session", json.dumps(summary))
        self.assertNotIn("secret-device", json.dumps(summary))

    def test_search_sources_are_reported_separately_from_homefeed(self):
        breakdown = scheduler_a._source_breakdown([
            {"source": "homefeed_phrase"},
            {"source": "search_phrase"},
            {"source": "search_token"},
            {"source": "search_recommend"},
            {"source": "hot_search"},
        ])
        self.assertEqual(breakdown["homefeed"], 1)
        self.assertEqual(breakdown["search_result"], 2)
        self.assertEqual(breakdown["search_recommend"], 1)
        self.assertEqual(breakdown["hot_search"], 1)

    def test_discovery_diagnostics_normal_search_funnel_is_closed(self):
        with (
            patch.object(scheduler_a, "SEARCH_DISCOVERY_ENABLED", True),
            patch.object(scheduler_a, "SEARCH_SEEDS_PER_CATEGORY", 2),
        ):
            self.assertEqual(len(scheduler_a._search_discovery_targets()), 12)
        diagnostics = scheduler_a.new_discovery_diagnostics()
        diagnostics["targets"].update({"planned": 12, "started": 12, "completed": 12})
        diagnostics["navigation"]["ok"] = 12
        diagnostics["input"].update({"found": 12, "visible": 12, "typed": 12})
        diagnostics["search"].update({
            "response_seen": 12, "json_ok": 12, "title_count": 24,
            "phrase_raw": 18, "cleaned": 10,
        })
        diagnostics["recommend"].update({
            "response_seen": 4, "json_ok": 4, "items_raw": 8, "extracted": 6,
        })
        rows = [
            {"source": "homefeed_phrase"},
            {"source": "search_phrase"},
            {"source": "search_recommend"},
            {"source": "hot_search"},
        ]

        result = scheduler_a.discovery_diagnostics_for_results(rows, diagnostics)

        self.assertEqual(result["targets"], {
            "planned": 12, "started": 12, "completed": 12, "skipped": 0,
        })
        self.assertEqual(result["search"]["final"], 1)
        self.assertEqual(result["recommend"]["final"], 1)
        self.assertEqual(result["diagnostic_error_codes"], [])

    def test_discovery_diagnostics_classifies_failure_funnel_reasons(self):
        cases = []

        no_input = scheduler_a.new_discovery_diagnostics()
        no_input["input"]["failed"] = 12
        cases.append((no_input, {"search_input_not_found"}))

        navigation_failed = scheduler_a.new_discovery_diagnostics()
        navigation_failed["targets"].update({"planned": 12, "started": 12, "completed": 12})
        navigation_failed["navigation"]["failed"] = 12
        cases.append((navigation_failed, {"navigation_failed", "all_navigation_failed"}))

        response_missing = scheduler_a.new_discovery_diagnostics()
        cases.append((response_missing, {
            "search_response_not_seen", "recommend_response_not_seen",
            "homefeed_source_zero", "hot_search_source_zero",
        }))

        non_json = scheduler_a.new_discovery_diagnostics()
        non_json["search"].update({"response_seen": 2, "json_failed": 2})
        non_json["recommend"].update({"response_seen": 1, "json_failed": 1})
        cases.append((non_json, {"search_response_non_json", "recommend_response_non_json"}))

        empty_recommend_schema = scheduler_a.new_discovery_diagnostics()
        empty_recommend_schema["recommend"].update({"response_seen": 1, "json_ok": 1})
        cases.append((empty_recommend_schema, {"recommend_schema_empty"}))

        for diagnostics, expected_codes in cases:
            with self.subTest(expected_codes=sorted(expected_codes)):
                result = scheduler_a.discovery_diagnostics_for_results([], diagnostics)
                self.assertTrue(expected_codes.issubset(set(result["diagnostic_error_codes"])))

    def test_discovery_diagnostics_classifies_filtered_and_deduped_candidates(self):
        filtered = scheduler_a.new_discovery_diagnostics()
        filtered["search"].update({
            "response_seen": 1, "json_ok": 1, "title_count": 2,
            "phrase_raw": 2, "filtered": 2,
        })
        filtered["recommend"].update({
            "response_seen": 1, "json_ok": 1, "items_raw": 2,
            "extracted": 2, "filtered": 2,
        })
        filtered_result = scheduler_a.discovery_diagnostics_for_results([], filtered)
        self.assertIn("search_candidates_all_filtered", filtered_result["diagnostic_error_codes"])
        self.assertIn("recommend_candidates_all_filtered", filtered_result["diagnostic_error_codes"])

        deduped = scheduler_a.new_discovery_diagnostics()
        deduped["search"].update({
            "response_seen": 1, "json_ok": 1, "title_count": 2,
            "phrase_raw": 2, "deduped": 2,
        })
        deduped["recommend"].update({
            "response_seen": 1, "json_ok": 1, "items_raw": 2,
            "extracted": 2, "deduped": 2,
        })
        deduped_result = scheduler_a.discovery_diagnostics_for_results([], deduped)
        self.assertIn("search_candidates_all_deduped", deduped_result["diagnostic_error_codes"])
        self.assertIn("recommend_candidates_all_deduped", deduped_result["diagnostic_error_codes"])

    def test_discovery_diagnostics_recognizes_safe_endpoint_and_page_variants(self):
        for path in (
            "https://example.invalid/api/search/recommend?fixed=1",
            "https://example.invalid/api/search_recommend?fixed=1",
            "https://example.invalid/api/search/suggest?fixed=1",
            "https://example.invalid/api/suggest?fixed=1",
        ):
            with self.subTest(path=path):
                self.assertEqual(scheduler_a._classify_discovery_response(path), "recommend")
                self.assertTrue(any(pattern in path for pattern in scheduler_a.HOT_API_PATTERNS))
        self.assertEqual(
            scheduler_a._classify_discovery_response("https://example.invalid/search/trending/query"),
            "trending",
        )
        self.assertEqual(scheduler_a._classify_final_page("https://example.invalid/search_result"), "search")
        self.assertEqual(scheduler_a._classify_final_page("https://example.invalid/explore"), "explore")
        self.assertEqual(scheduler_a._classify_final_page("https://example.invalid/login"), "login")
        self.assertEqual(scheduler_a._classify_final_page("https://example.invalid/challenge"), "challenge")
        self.assertEqual(scheduler_a._classify_final_page("https://example.invalid/blocked"), "other")
        self.assertEqual(
            [scheduler_a._response_status_class(value) for value in (200, 302, 403, 503, None)],
            ["2xx", "3xx", "4xx", "5xx", "unknown"],
        )

    def test_recommend_path_variants_share_sug_items_parser(self):
        payload = {
            "data": {"sug_items": [{"search_word": "家居收纳推荐"}]},
        }
        for path in (
            "https://example.invalid/api/search/recommend",
            "https://example.invalid/api/search_recommend",
            "https://example.invalid/api/search/suggest",
            "https://example.invalid/api/suggest",
        ):
            with self.subTest(path=path):
                result, _events = self._run_scheduler_circuit_scenario(
                    challenge=False,
                    response_payload=payload,
                    response_url=path,
                )
                diagnostics = result.diagnostics
                sources = scheduler_a._source_breakdown(result)

                self.assertEqual(diagnostics["recommend"]["response_seen"], 12)
                self.assertEqual(diagnostics["recommend"]["json_ok"], 12)
                self.assertEqual(diagnostics["recommend"]["items_raw"], 12)
                self.assertEqual(diagnostics["recommend"]["extracted"], 12)
                self.assertGreater(diagnostics["recommend"]["final"], 0)
                self.assertGreater(sources["search_recommend"], 0)
                self.assertEqual(sources["hot_search"], 0)

    def test_unknown_discovery_path_does_not_parse_sug_items(self):
        for path in (
            "https://example.invalid/api/discovery/other",
            "https://example.invalid/api/discovery/other?next=/suggest",
            "https://example.invalid/api/suggestion",
            "https://example.invalid/api/suggest-unknown",
            "https://example.invalid/api/not_search_recommend_extra",
            "https://example.invalid/api/search/suggested",
        ):
            with self.subTest(path=path):
                result, _events = self._run_scheduler_circuit_scenario(
                    challenge=False,
                    response_payload={
                        "data": {"sug_items": [{"search_word": "未知路径不应解析"}]},
                    },
                    response_url=path,
                )
                diagnostics = result.diagnostics
                sources = scheduler_a._source_breakdown(result)

                self.assertEqual(diagnostics["recommend"]["response_seen"], 0)
                self.assertEqual(diagnostics["recommend"]["json_ok"], 0)
                self.assertEqual(diagnostics["recommend"]["items_raw"], 0)
                self.assertEqual(diagnostics["recommend"]["extracted"], 0)
                self.assertEqual(sources["search_recommend"], 0)
                self.assertEqual(sources["hot_search"], 0)

    def test_search_payload_diagnostics_distinguish_fixed_safe_classes(self):
        display_title_payload = {
            "data": {"items": [{"note_card": {"display_title": "真实标题"}}]},
        }
        title_payload = {
            "data": {"items": [{"note_card": {"title": "备用标题"}}]},
        }
        cases = (
            ([{"status": "ok"}], "generic_json"),
            ({"data": {"status": "ok"}}, "generic_json"),
            (display_title_payload, "note_result"),
            (title_payload, "note_result"),
            ({"data": {"items": []}}, "empty_result"),
            ({"data": {"items": [{"note_card": {"desc": "无支持标题"}}]}}, "unknown_schema"),
            ({"success": False, "data": {}}, "business_error"),
            ({"code": 300012, "data": {}}, "business_error"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(scheduler_a._classify_search_payload(payload), expected)

        self.assertEqual(scheduler_a._extract_note_titles(display_title_payload), ["真实标题"])
        self.assertEqual(scheduler_a._extract_note_titles(title_payload), ["备用标题"])

    def test_discovery_diagnostics_sanitizer_drops_sensitive_and_unknown_fields(self):
        diagnostics = scheduler_a.new_discovery_diagnostics()
        diagnostics["raw_url"] = "https://secret.invalid/search?keyword=用户关键词"
        diagnostics["cookie"] = "secret-cookie-value"
        diagnostics["response_body"] = "private-response-body"
        diagnostics["search"]["raw_title"] = "private-note-title"
        diagnostics["diagnostic_error_codes"] = [
            "navigation_failed",
            "private-exception-message",
        ]
        diagnostics["response_status_class"]["private-status"] = 1
        diagnostics["search_response_class"].update({
            "generic_json": 2,
            "private-payload-shape": 3,
        })
        diagnostics["search_target_outcome"].update({
            "endpoint_not_seen": 1,
            "private-target-outcome": 4,
        })
        diagnostics["circuit"] = {
            "state": "private-state",
            "skipped_reason": "private-secret-reason",
            "cookie": "secret-circuit-cookie",
        }

        serialized = json.dumps(
            scheduler_a.sanitize_discovery_diagnostics(diagnostics),
            ensure_ascii=False,
        )

        for secret in (
            "secret.invalid", "用户关键词", "secret-cookie-value", "private-response-body",
            "private-note-title", "private-exception-message", "private-status",
            "private-payload-shape", "private-target-outcome",
            "private-state", "private-secret-reason", "secret-circuit-cookie",
        ):
            self.assertNotIn(secret, serialized)
        self.assertIn("navigation_failed", serialized)
        sanitized = json.loads(serialized)
        self.assertEqual(sanitized["search_response_class"]["generic_json"], 2)
        self.assertEqual(sanitized["search_target_outcome"]["endpoint_not_seen"], 1)

    def test_search_challenge_opens_circuit_and_skips_remaining_targets(self):
        result, events = self._run_scheduler_circuit_scenario(challenge=True)
        diagnostics = result.diagnostics

        self.assertEqual(events["homefeed_gotos"], 1)
        self.assertEqual(events["search_gotos"], 1)
        self.assertEqual(diagnostics["targets"], {
            "planned": 12, "started": 1, "completed": 1, "skipped": 11,
        })
        self.assertEqual(diagnostics["response_status_class"]["2xx"], 1)
        self.assertEqual(diagnostics["final_page_class"]["challenge"], 1)
        self.assertEqual(diagnostics["circuit"], {
            "state": "open", "skipped_reason": "challenge_detected",
        })
        self.assertEqual(diagnostics["search_response_class"]["note_result"], 0)
        self.assertEqual(diagnostics["search_target_outcome"], {
            "endpoint_not_seen": 0,
            "challenge_before_target_payload": 1,
        })
        self.assertIn("possible_access_challenge", diagnostics["diagnostic_error_codes"])
        self.assertIn(
            "search_challenge_before_target_payload",
            diagnostics["diagnostic_error_codes"],
        )
        self.assertIn(
            "search_targets_skipped_after_challenge",
            diagnostics["diagnostic_error_codes"],
        )

    def test_server_login_stops_remaining_targets_without_opening_challenge_circuit(self):
        result, events = self._run_scheduler_circuit_scenario(
            challenge=False,
            login=True,
        )
        diagnostics = result.diagnostics

        self.assertEqual(events["homefeed_gotos"], 1)
        self.assertEqual(events["search_gotos"], 1)
        self.assertEqual(events["browser_launches"], 2)
        self.assertTrue(all(item.get("chromium_sandbox") is True for item in events["browser_launch_kwargs"]))
        self.assertEqual(events["input_calls"], 0)
        self.assertEqual(events["scrolls"], 1)
        self.assertEqual(events["blank_gotos"], 1)
        self.assertEqual(events["goto_kinds"][-1], "search_login")
        self.assertEqual(diagnostics["targets"], {
            "planned": 12, "started": 1, "completed": 1, "skipped": 11,
        })
        self.assertEqual(diagnostics["final_page_class"]["login"], 1)
        self.assertEqual(diagnostics["circuit"], {
            "state": "closed", "skipped_reason": "",
        })
        self.assertIn(
            "server_session_logged_out",
            diagnostics["diagnostic_error_codes"],
        )
        self.assertNotIn(
            "possible_access_challenge",
            diagnostics["diagnostic_error_codes"],
        )

    def test_search_normal_flow_keeps_all_twelve_targets(self):
        result, events = self._run_scheduler_circuit_scenario(challenge=False)
        diagnostics = result.diagnostics

        self.assertEqual(events["homefeed_gotos"], 1)
        self.assertEqual(events["search_gotos"], 12)
        self.assertEqual(diagnostics["targets"], {
            "planned": 12, "started": 12, "completed": 12, "skipped": 0,
        })
        self.assertEqual(diagnostics["circuit"]["state"], "closed")
        self.assertEqual(diagnostics["search"]["json_ok"], 12)
        self.assertEqual(diagnostics["search_response_class"]["generic_json"], 12)
        self.assertEqual(diagnostics["search_response_class"]["note_result"], 0)
        self.assertEqual(diagnostics["search_target_outcome"]["endpoint_not_seen"], 12)

    def test_search_structured_and_non_json_responses_have_distinct_diagnostics(self):
        structured, _events = self._run_scheduler_circuit_scenario(
            challenge=False,
            response_payload={
                "data": {"items": [{"note_card": {"display_title": "真实笔记标题"}}]},
            },
        )
        structured_diagnostics = structured.diagnostics
        self.assertEqual(structured_diagnostics["search_response_class"]["note_result"], 12)
        self.assertEqual(structured_diagnostics["search_response_class"]["generic_json"], 0)
        self.assertEqual(structured_diagnostics["search_target_outcome"]["endpoint_not_seen"], 0)
        self.assertEqual(structured_diagnostics["search"]["title_count"], 12)
        self.assertGreater(structured_diagnostics["search"]["phrase_raw"], 0)
        self.assertGreater(structured_diagnostics["search"]["final"], 0)

        non_json, _events = self._run_scheduler_circuit_scenario(
            challenge=False,
            response_json_error=True,
        )
        non_json_diagnostics = non_json.diagnostics
        self.assertEqual(non_json_diagnostics["search_response_class"]["non_json"], 12)
        self.assertEqual(non_json_diagnostics["search_response_class"]["generic_json"], 0)
        self.assertEqual(non_json_diagnostics["search"]["json_failed"], 12)
        self.assertEqual(non_json_diagnostics["search"]["title_count"], 0)
        self.assertEqual(non_json_diagnostics["search"]["phrase_raw"], 0)
        self.assertEqual(non_json_diagnostics["search"]["final"], 0)

    def test_non_note_search_payloads_never_contribute_title_candidates(self):
        cases = (
            (
                "generic_json",
                {"data": {"status": {"title": "辅助页面标题不应入库"}}},
            ),
            (
                "business_error",
                {
                    "code": 300012,
                    "data": {"items": [{"note_card": {"title": "业务错误标题不应入库"}}]},
                },
            ),
            (
                "empty_result",
                {"title": "空结果辅助标题不应入库", "data": {"items": []}},
            ),
            (
                "unknown_schema",
                {
                    "title": "未知结构辅助标题不应入库",
                    "data": {"items": [{"note_card": {"desc": "缺少支持标题字段"}}]},
                },
            ),
        )

        for response_class, payload in cases:
            with self.subTest(response_class=response_class):
                result, _events = self._run_scheduler_circuit_scenario(
                    challenge=False,
                    response_payload=payload,
                )
                diagnostics = result.diagnostics

                self.assertEqual(
                    diagnostics["search_response_class"][response_class],
                    12,
                )
                self.assertEqual(diagnostics["search"]["title_count"], 0)
                self.assertEqual(diagnostics["search"]["phrase_raw"], 0)
                self.assertEqual(diagnostics["search"]["cleaned"], 0)
                self.assertEqual(diagnostics["search"]["final"], 0)

    def test_search_cooldown_skips_search_but_preserves_homefeed(self):
        result, events = self._run_scheduler_circuit_scenario(
            challenge=False,
            circuit_state="cooldown",
        )
        diagnostics = result.diagnostics

        self.assertEqual(events["homefeed_gotos"], 1)
        self.assertEqual(events["search_gotos"], 0)
        self.assertEqual(diagnostics["targets"], {
            "planned": 12, "started": 0, "completed": 0, "skipped": 12,
        })
        self.assertEqual(diagnostics["circuit"], {
            "state": "cooldown", "skipped_reason": "challenge_cooldown_active",
        })
        self.assertIn("challenge_cooldown_active", diagnostics["diagnostic_error_codes"])

    def test_stop_on_challenge_default_compatible_mode_continues_search(self):
        result, events = self._run_scheduler_circuit_scenario(challenge=True, stop=False)

        self.assertEqual(events["search_gotos"], 12)
        self.assertEqual(result.diagnostics["targets"]["skipped"], 0)
        self.assertEqual(result.diagnostics["circuit"]["state"], "closed")

    def test_trending_search_word_is_a_keyword_candidate(self):
        self.assertEqual(
            scheduler_a._extract_keyword_from_item({"search_word": "家居收纳"}),
            "家居收纳",
        )

    def test_search_input_retries_after_navigation_context_loss(self):
        class FakeLocator:
            def __init__(self, attempt):
                self.attempt = attempt
                self.first = self

            async def count(self):
                if self.attempt == 1:
                    raise RuntimeError("Execution context was destroyed")
                return 1

            async def is_visible(self):
                return self.attempt >= 3

            async def fill(self, value):
                self.filled = value

            async def type(self, value, delay=0):
                self.typed = value

        class FakePage:
            def __init__(self):
                self.attempts = 0

            def locator(self, selector):
                self.attempts += 1
                return FakeLocator(self.attempts)

        page = FakePage()
        diagnostics = scheduler_a.new_discovery_diagnostics()
        typed, error = asyncio.run(
            scheduler_a._trigger_search_input(
                page, "家居收纳", timeout_seconds=2, diagnostics=diagnostics
            )
        )
        self.assertTrue(typed)
        self.assertEqual(error, "")
        self.assertEqual(page.attempts, 3)
        self.assertEqual(diagnostics["input"], {
            "found": 1, "visible": 1, "typed": 1, "failed": 0,
        })

    def test_search_input_all_unavailable_records_fixed_funnel_counts(self):
        class MissingLocator:
            first = None

            def __init__(self):
                self.first = self

            async def count(self):
                return 0

        class MissingPage:
            def locator(self, selector):
                return MissingLocator()

        diagnostics = scheduler_a.new_discovery_diagnostics()
        typed, _error = asyncio.run(
            scheduler_a._trigger_search_input(
                MissingPage(), "private-seed", timeout_seconds=1,
                diagnostics=diagnostics,
            )
        )

        self.assertFalse(typed)
        self.assertEqual(diagnostics["input"], {
            "found": 0, "visible": 0, "typed": 0, "failed": 1,
        })
        finalized = scheduler_a.discovery_diagnostics_for_results([], diagnostics)
        self.assertIn("search_input_not_found", finalized["diagnostic_error_codes"])
        self.assertNotIn("private-seed", json.dumps(finalized))

    def test_worker_xhs_required_exports_baseline_with_warning(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        old_required = os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = "1"

                async def empty_scrape():
                    return []

                market_timing_worker.scrape_once = empty_scrape
                snapshot_path = tmp / "market_timing_snapshot.json"
                result = asyncio.run(market_timing_worker.run_once(snapshot_path))

                self.assertTrue(snapshot_path.exists())
                self.assertFalse(result["xhs_freshness_ok"])
                self.assertIn("XHS_FRESH_EVIDENCE_UNAVAILABLE", result["xhs_freshness_warning"])
                self.assertEqual(result["evidence_mode"], "baseline_or_partial")
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["domains"]["美食"]["keywords"][0]["source"], "industry_baseline")
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            if old_required is None:
                os.environ.pop("NOTEAI_XHS_FRESHNESS_REQUIRED", None)
            else:
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = old_required

    def test_worker_explicit_hard_fail_raises_after_local_snapshot(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        old_required = os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = "1"

                async def empty_scrape():
                    return []

                market_timing_worker.scrape_once = empty_scrape
                snapshot_path = tmp / "market_timing_snapshot.json"
                with self.assertRaisesRegex(RuntimeError, "XHS_FRESH_EVIDENCE_UNAVAILABLE"):
                    asyncio.run(market_timing_worker.run_once(
                        snapshot_path,
                        hard_fail_on_xhs_missing=True,
                    ))
                self.assertTrue(snapshot_path.exists())
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            if old_required is None:
                os.environ.pop("NOTEAI_XHS_FRESHNESS_REQUIRED", None)
            else:
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = old_required

    def test_worker_hard_gate_allows_real_xhs_snapshot(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        old_required = os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = "1"

                async def real_scrape():
                    return _real_xhs_rows()

                market_timing_worker.scrape_once = real_scrape
                snapshot_path = tmp / "market_timing_snapshot.json"
                result = asyncio.run(market_timing_worker.run_once(snapshot_path))
                self.assertTrue(result["xhs_freshness_overview"]["ok"])
                self.assertTrue(snapshot_path.exists())
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                self.assertIn("美食", payload["domains"])
                self.assertNotEqual(payload["domains"]["美食"]["keywords"][0]["source"], "industry_baseline")
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            if old_required is None:
                os.environ.pop("NOTEAI_XHS_FRESHNESS_REQUIRED", None)
            else:
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = old_required

    def test_server_logout_persists_block_and_next_cron_never_calls_scrape(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        original_session_summary = market_timing_worker.session_state_summary
        settings_store = {}
        scrape_calls = 0
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                xhs_acquisition.record_scrape_freshness(
                    _real_xhs_rows(),
                    run_id="previous-fresh-run",
                    session_status={
                        "configured": True,
                        "auth_cookie_present": True,
                        "auth_cookie_expired": False,
                    },
                )
                self.assertTrue(xhs_acquisition.freshness_overview()["ok"])

                async def logged_out_scrape():
                    nonlocal scrape_calls
                    scrape_calls += 1
                    diagnostics = scheduler_a.new_discovery_diagnostics()
                    diagnostics["targets"].update({
                        "planned": 12, "started": 1, "completed": 1, "skipped": 11,
                    })
                    diagnostics["final_page_class"]["login"] = 1
                    diagnostics["diagnostic_error_codes"] = [
                        "server_session_logged_out",
                    ]
                    return scheduler_a.ScrapeResults([], diagnostics)

                market_timing_worker.scrape_once = logged_out_scrape
                market_timing_worker.session_state_summary = lambda: {
                    "configured": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                }
                with (
                    patch.object(
                        xhs_acquisition.runtime_settings,
                        "get_json",
                        side_effect=lambda key, default=None: settings_store.get(key, default),
                    ),
                    patch.object(
                        xhs_acquisition.runtime_settings,
                        "set_json",
                        side_effect=lambda key, value, **_kwargs: settings_store.__setitem__(key, value),
                    ),
                    patch.dict(os.environ, {"NOTEAI_XHS_COLLECTION_SUSPENDED": "0"}),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "XHS_FRESH_EVIDENCE_UNAVAILABLE",
                    ):
                        asyncio.run(market_timing_worker.run_once(
                            tmp / "market_timing_snapshot-first.json",
                            hard_fail_on_xhs_missing=True,
                        ))
                    self.assertEqual(scrape_calls, 1)
                    self.assertTrue(
                        xhs_acquisition.collection_safety_status()["session_blocked"]
                    )

                    with self.assertRaisesRegex(
                        RuntimeError,
                        "XHS_FRESH_EVIDENCE_UNAVAILABLE",
                    ):
                        asyncio.run(market_timing_worker.run_once(
                            tmp / "market_timing_snapshot-second.json",
                            hard_fail_on_xhs_missing=True,
                        ))
                    self.assertEqual(scrape_calls, 1)

                latest_run_id = xhs_acquisition.recent_health(
                    adapter="scheduler_a"
                )[0]["run_id"]
                latest_rows = [
                    row for row in xhs_acquisition.recent_health(
                        limit=20,
                        adapter="scheduler_a",
                    )
                    if row["run_id"] == latest_run_id
                ]
                self.assertEqual(
                    {row["domain"] for row in latest_rows},
                    set(hot_keywords.CORE_EVIDENCE_DOMAINS),
                )
                self.assertEqual(
                    {row["error_code"] for row in latest_rows},
                    {"server_session_logged_out"},
                )
                self.assertTrue(all(row["risk_login_detected"] for row in latest_rows))
                self.assertTrue(all(
                    int(row["details"]["latest_run_evidence_count"]) == 0
                    for row in latest_rows
                ))
                self.assertFalse(
                    xhs_acquisition.challenge_cooldown_status()["active"]
                )
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            market_timing_worker.session_state_summary = original_session_summary

    def test_latest_zero_hard_fails_even_when_cumulative_freshness_is_true(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                xhs_acquisition.record_scrape_freshness(
                    _real_xhs_rows(),
                    run_id="cumulative-fresh-run",
                    session_status={
                        "configured": True,
                        "auth_cookie_present": True,
                        "auth_cookie_expired": False,
                    },
                )
                self.assertTrue(xhs_acquisition.freshness_overview()["ok"])

                async def empty_scrape():
                    return scheduler_a.ScrapeResults(
                        [],
                        scheduler_a.new_discovery_diagnostics(),
                    )

                market_timing_worker.scrape_once = empty_scrape
                with (
                    patch.object(
                        market_timing_worker,
                        "collection_safety_status",
                        return_value={"session_blocked": False, "reason_code": ""},
                    ),
                    patch.dict(
                        os.environ,
                        {"NOTEAI_XHS_COLLECTION_SUSPENDED": "0"},
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "XHS_FRESH_EVIDENCE_UNAVAILABLE",
                    ):
                        asyncio.run(market_timing_worker.run_once(
                            tmp / "market_timing_snapshot.json",
                            hard_fail_on_xhs_missing=True,
                        ))

                self.assertTrue(xhs_acquisition.freshness_overview()["ok"])
                latest = xhs_acquisition.latest_run_source_health()
                self.assertEqual(latest["evidence_count"], 0)
                self.assertEqual(latest["error_code"], "latest_run_no_evidence")
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once

    def test_operator_suspension_skips_scrape_and_hard_fails(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        scrape_calls = 0
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"

                async def forbidden_scrape():
                    nonlocal scrape_calls
                    scrape_calls += 1
                    return []

                market_timing_worker.scrape_once = forbidden_scrape
                with (
                    patch.object(
                        market_timing_worker,
                        "collection_safety_status",
                        return_value={"session_blocked": False, "reason_code": ""},
                    ),
                    patch.dict(
                        os.environ,
                        {
                            "NOTEAI_RUNTIME_ROLE": "xhs-http",
                            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                            "NOTEAI_XHS_COLLECTION_SUSPENDED": "1",
                        },
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "XHS_FRESH_EVIDENCE_UNAVAILABLE",
                    ):
                        asyncio.run(market_timing_worker.run_once(
                            tmp / "market_timing_snapshot.json",
                            hard_fail_on_xhs_missing=True,
                        ))

                self.assertEqual(scrape_calls, 0)
                latest_run_id = xhs_acquisition.recent_health(
                    adapter="spider_xhs_http"
                )[0]["run_id"]
                latest_rows = [
                    row for row in xhs_acquisition.recent_health(
                        limit=20,
                        adapter="spider_xhs_http",
                    )
                    if row["run_id"] == latest_run_id
                ]
                self.assertEqual(len(latest_rows), len(hot_keywords.CORE_EVIDENCE_DOMAINS))
                self.assertEqual(
                    {row["error_code"] for row in latest_rows},
                    {"collection_suspended"},
                )
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once

    def test_worker_uses_cooldown_context_and_keeps_homefeed_evidence(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        original_cooldown = market_timing_worker.challenge_cooldown_status
        original_session_summary = market_timing_worker.session_state_summary
        old_required = os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = "1"
                xhs_acquisition.record_health({
                    "run_id": "prior-challenge",
                    "adapter": "scheduler_a",
                    "domain": "美食",
                    "status": "degraded",
                    "error_code": "access_challenge_detected",
                    "details": {"access_status": "challenge"},
                })

                async def cooldown_scrape():
                    self.assertEqual(
                        (scheduler_a._SEARCH_CIRCUIT_CONTEXT.get() or {}).get("state"),
                        "cooldown",
                    )
                    diagnostics = scheduler_a.new_discovery_diagnostics()
                    diagnostics["targets"].update({
                        "planned": 12, "started": 0, "completed": 0, "skipped": 12,
                    })
                    diagnostics["circuit"] = {
                        "state": "cooldown",
                        "skipped_reason": "challenge_cooldown_active",
                    }
                    diagnostics["diagnostic_error_codes"] = ["challenge_cooldown_active"]
                    homefeed_rows = [
                        dict(row, source="homefeed_phrase") for row in _real_xhs_rows()
                    ]
                    return scheduler_a.ScrapeResults(homefeed_rows, diagnostics)

                market_timing_worker.scrape_once = cooldown_scrape
                market_timing_worker.challenge_cooldown_status = lambda: {
                    "active": True,
                    "last_challenge_at": datetime.now().isoformat(),
                    "remaining_seconds": 300,
                }
                market_timing_worker.session_state_summary = lambda: {
                    "configured": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                }

                result = asyncio.run(market_timing_worker.run_once(
                    tmp / "market_timing_snapshot.json",
                    hard_fail_on_xhs_missing=True,
                ))

                self.assertTrue(result["xhs_freshness_ok"])
                self.assertEqual(result["discovery_diagnostics"]["targets"], {
                    "planned": 12, "started": 0, "completed": 0, "skipped": 12,
                })
                self.assertEqual(
                    result["discovery_diagnostics"]["circuit"]["state"],
                    "cooldown",
                )
                latest = xhs_acquisition.recent_health(adapter="scheduler_a")[0]
                self.assertEqual(latest["error_code"], "access_challenge_cooldown_active")
                self.assertTrue(latest["profile_cookie_valid"])
                self.assertFalse(latest["risk_login_detected"])
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            market_timing_worker.challenge_cooldown_status = original_cooldown
            market_timing_worker.session_state_summary = original_session_summary
            if old_required is None:
                os.environ.pop("NOTEAI_XHS_FRESHNESS_REQUIRED", None)
            else:
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = old_required

    def test_worker_logs_and_persists_only_sanitized_discovery_diagnostics(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        original_session_summary = market_timing_worker.session_state_summary
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                diagnostics = scheduler_a.new_discovery_diagnostics()
                diagnostics["targets"].update({"planned": 12, "started": 12, "completed": 12})
                diagnostics["raw_url"] = "https://secret.invalid/search?keyword=private-keyword"
                diagnostics["cookie"] = "private-cookie-value"
                diagnostics["response_body"] = "private-response-body"
                diagnostics["diagnostic_error_codes"] = [
                    "search_response_not_seen",
                    "private-exception-message",
                ]
                sensitive_keyword = "美食私密关键词"

                async def diagnostic_scrape():
                    rows = _real_xhs_rows()
                    rows[0] = dict(rows[0], keyword=sensitive_keyword)
                    return scheduler_a.ScrapeResults(rows, diagnostics)

                market_timing_worker.scrape_once = diagnostic_scrape
                market_timing_worker.session_state_summary = lambda: {
                    "configured": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                }
                output = io.StringIO()
                with redirect_stdout(output):
                    result = asyncio.run(market_timing_worker.run_once(
                        tmp / "market_timing_snapshot.json"
                    ))

                health = xhs_acquisition.recent_health(adapter="scheduler_a")
                persisted = health[0]["details"]["discovery_diagnostics"]
                conn = hot_keywords._conn()
                try:
                    ledger_row = conn.execute(
                        "SELECT evidence_count, details_json FROM xhs_freshness_ledger WHERE domain=?",
                        ("美食",),
                    ).fetchone()
                finally:
                    conn.close()
                ledger_details = json.loads(ledger_row["details_json"])
                first_evidence_count = int(ledger_row["evidence_count"])
                self.assertIn("evidence_keys", ledger_details)
                self.assertTrue(any(sensitive_keyword in key for key in ledger_details["evidence_keys"]))

                main_output = io.StringIO()
                with patch.object(sys, "argv", [
                    "market_timing_worker.py", "--once",
                    "--snapshot-path", str(tmp / "market_timing_snapshot-main.json"),
                ]):
                    with redirect_stdout(main_output):
                        self.assertEqual(market_timing_worker.main(), 0)

                conn = hot_keywords._conn()
                try:
                    repeated_row = conn.execute(
                        "SELECT evidence_count, details_json FROM xhs_freshness_ledger WHERE domain=?",
                        ("美食",),
                    ).fetchone()
                finally:
                    conn.close()
                repeated_details = json.loads(repeated_row["details_json"])
                self.assertEqual(int(repeated_row["evidence_count"]), first_evidence_count)
                self.assertEqual(repeated_details["evidence_keys"], ledger_details["evidence_keys"])

                nested_internal = {
                    "domains": [{"details": {"evidence_keys": [sensitive_keyword], "safe": 1}}]
                }
                nested_public = market_timing_worker._public_xhs_freshness(nested_internal)
                self.assertIn("evidence_keys", nested_internal["domains"][0]["details"])
                self.assertNotIn("evidence_keys", nested_public["domains"][0]["details"])

                serialized = (
                    output.getvalue()
                    + main_output.getvalue()
                    + json.dumps({"result": result, "persisted": persisted}, ensure_ascii=False)
                )
                self.assertIn("xhs_discovery_diagnostics", serialized)
                self.assertEqual(persisted["targets"]["planned"], 12)
                self.assertNotIn("evidence_keys", json.dumps(result["xhs_freshness"], ensure_ascii=False))
                self.assertNotIn('"evidence_keys"', main_output.getvalue())
                for secret in (
                    "secret.invalid", "private-keyword", sensitive_keyword, "private-cookie-value",
                    "private-response-body", "private-exception-message",
                ):
                    self.assertNotIn(secret, serialized)
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            market_timing_worker.session_state_summary = original_session_summary

    def test_worker_scrape_exception_uses_fixed_code_without_message_leak(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        original_session_summary = market_timing_worker.session_state_summary
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"

                async def failed_scrape():
                    raise RuntimeError(
                        "https://secret.invalid private-cookie private-response private-keyword"
                    )

                market_timing_worker.scrape_once = failed_scrape
                market_timing_worker.session_state_summary = lambda: {
                    "configured": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                }
                output = io.StringIO()
                with redirect_stdout(output):
                    result = asyncio.run(market_timing_worker.run_once(
                        tmp / "market_timing_snapshot.json"
                    ))

                serialized = output.getvalue() + json.dumps(result, ensure_ascii=False)
                self.assertEqual(result["scrape_error"], "scrape_once_failed")
                self.assertIn("scrape_once_failed", result["discovery_diagnostics"]["diagnostic_error_codes"])
                for secret in (
                    "secret.invalid", "private-cookie", "private-response", "private-keyword",
                ):
                    self.assertNotIn(secret, serialized)
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            market_timing_worker.session_state_summary = original_session_summary

    def test_worker_once_exit_code_remains_nonzero_on_failure(self):
        original_run_once = market_timing_worker.run_once
        try:
            async def failed_run_once(*args, **kwargs):
                raise RuntimeError("XHS_FRESH_EVIDENCE_UNAVAILABLE")

            market_timing_worker.run_once = failed_run_once
            with patch.object(sys, "argv", ["market_timing_worker.py", "--once"]):
                stderr = io.StringIO()
                with patch.object(sys, "stderr", stderr):
                    self.assertEqual(market_timing_worker.main(), 1)
                self.assertIn("xhs_fresh_evidence_unavailable", stderr.getvalue())
                self.assertIn("RuntimeError", stderr.getvalue())
        finally:
            market_timing_worker.run_once = original_run_once

    def test_recent_health_probe_and_cli_exit_code(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                xhs_acquisition.record_health(xhs_acquisition.CrawlerHealth(
                    run_id="health-run",
                    adapter="scheduler_a",
                    domain="美食",
                    status="insufficient",
                    evidence_count=3,
                    error_code="selector_changed",
                    error_summary="selector drift",
                ))
                recent = xhs_acquisition.recent_health(domain="美食")
                self.assertEqual(len(recent), 1)
                self.assertEqual(recent[0]["adapter"], "scheduler_a")
                self.assertEqual(recent[0]["error_code"], "selector_changed")

                probe = xhs_acquisition.freshness_probe(("美食",), deadline_hour=0)
                self.assertFalse(probe["ok"])
                self.assertTrue(probe["action_required"])
                self.assertIn("美食", probe["missing_domains"])

                with patch.object(sys, "argv", ["xhs_health_probe.py", "--domain", "美食", "--deadline-hour", "0"]):
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(xhs_health_probe.main(), 2)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_sidecar_not_configured_records_failed_health_without_network(self):
        original_db = hot_keywords.DB_PATH
        old_url = os.environ.pop("NOTEAI_XHS_DOWNLOADER_URL", None)
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                result = xhs_acquisition.fetch_detail_with_sidecar(
                    "https://www.xiaohongshu.com/explore/test",
                    domain="美食",
                    run_id="sidecar-run",
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "sidecar_not_configured")
                health = xhs_acquisition.recent_health(adapter="xhs_downloader")
                self.assertEqual(len(health), 1)
                self.assertEqual(health[0]["status"], "failed")
                self.assertFalse(health[0]["note_page_access_valid"])
        finally:
            hot_keywords.DB_PATH = original_db
            if old_url is not None:
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = old_url

    def test_sidecar_success_normalizes_detail_and_records_health(self):
        original_db = hot_keywords.DB_PATH
        old_url = os.environ.get("NOTEAI_XHS_DOWNLOADER_URL")
        original_client = xhs_acquisition.httpx.Client
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "data": {
                        "note": {
                            "note_id": "note-123",
                            "display_title": "真实笔记标题",
                            "desc": "真实笔记正文",
                            "interact_info": {
                                "liked_count": "1.2万",
                                "collected_count": "88",
                                "comments_count": 7,
                            },
                        }
                    }
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                captured["init"] = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, json=None):
                captured["url"] = url
                captured["payload"] = json
                return FakeResponse()

        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = "http://sidecar.local"
                xhs_acquisition.httpx.Client = FakeClient

                result = xhs_acquisition.fetch_detail_with_sidecar(
                    "https://www.xiaohongshu.com/explore/test",
                    domain="美食",
                    run_id="sidecar-ok",
                )
                self.assertTrue(result["ok"])
                self.assertEqual(captured["url"], "http://sidecar.local/xhs/detail")
                self.assertEqual(captured["payload"]["url"], "https://www.xiaohongshu.com/explore/test")
                self.assertEqual(result["normalized"]["likes"], 12000)
                self.assertEqual(result["normalized"]["saves"], 88)
                health = xhs_acquisition.recent_health(adapter="xhs_downloader")
                self.assertEqual(health[0]["status"], "ok")
                self.assertTrue(health[0]["selector_valid"])
                self.assertEqual(health[0]["evidence_count"], 1)
        finally:
            hot_keywords.DB_PATH = original_db
            xhs_acquisition.httpx.Client = original_client
            if old_url is None:
                os.environ.pop("NOTEAI_XHS_DOWNLOADER_URL", None)
            else:
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = old_url

    def test_sidecar_normalizes_xhs_downloader_chinese_schema(self):
        payload = {
            "data": {
                "作品ID": "6a2264420000000035032a92",
                "作者ID": "author-123",
                "作品标题": "真实笔记标题",
                "作品描述": "真实笔记正文",
                "点赞数量": "1.1万",
                "收藏数量": "2,345",
                "评论数量": "67",
                "分享数量": 8,
                "下载地址": ["https://example.invalid/a.jpg"],
            },
            "message": "success",
        }

        normalized = xhs_acquisition.normalize_sidecar_detail(payload)

        self.assertTrue(normalized["has_content"])
        self.assertTrue(normalized["has_metrics"])
        self.assertEqual(normalized["note_id"], "6a2264420000000035032a92")
        self.assertEqual(normalized["title"], "真实笔记标题")
        self.assertEqual(normalized["desc"], "真实笔记正文")
        self.assertEqual(normalized["likes"], 11000)
        self.assertEqual(normalized["saves"], 2345)
        self.assertEqual(normalized["comments"], 67)
        self.assertEqual(normalized["shares"], 8)

    def test_sidecar_http_failure_records_risk_login(self):
        original_db = hot_keywords.DB_PATH
        old_url = os.environ.get("NOTEAI_XHS_DOWNLOADER_URL")
        original_client = xhs_acquisition.httpx.Client

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, json=None):
                raise xhs_acquisition.httpx.HTTPStatusError(
                    "403 login required",
                    request=None,
                    response=None,
                )

        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = "http://sidecar.local"
                xhs_acquisition.httpx.Client = FakeClient

                result = xhs_acquisition.fetch_detail_with_sidecar(
                    "https://www.xiaohongshu.com/explore/test",
                    domain="美食",
                    run_id="sidecar-fail",
                )
                self.assertFalse(result["ok"])
                health = xhs_acquisition.recent_health(adapter="xhs_downloader")
                self.assertEqual(health[0]["status"], "failed")
                self.assertTrue(health[0]["risk_login_detected"])
        finally:
            hot_keywords.DB_PATH = original_db
            xhs_acquisition.httpx.Client = original_client
            if old_url is None:
                os.environ.pop("NOTEAI_XHS_DOWNLOADER_URL", None)
            else:
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = old_url

    def test_admin_xhs_handlers_read_freshness_and_health(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                xhs_acquisition.record_scrape_freshness(_real_xhs_rows(), run_id="admin-read")
                xhs_acquisition.record_health(xhs_acquisition.CrawlerHealth(
                    run_id="admin-read",
                    adapter="scheduler_a",
                    domain="美食",
                    status="ok",
                    evidence_count=16,
                ))

                freshness = asyncio.run(admin_server.admin_xhs_freshness(admin={"username": "admin"}))
                health = asyncio.run(admin_server.admin_xhs_health(admin={"username": "admin"}))
                self.assertTrue(freshness["ok"])
                self.assertIn("health", health)
                self.assertGreaterEqual(len(health["health"]), 1)
                self.assertIn("sidecar", health)
                self.assertIn("error_summary", health["health"][0])
                self.assertIn("details", health["health"][0])
                self.assertIn(health["health"][0]["access_status"], {
                    "normal", "challenge", "cooldown",
                })
                self.assertNotIn(
                    "discovery_diagnostics",
                    json.dumps(health, ensure_ascii=False),
                )
        finally:
            hot_keywords.DB_PATH = original_db

    def test_admin_cookie_status_prioritizes_server_logout_over_cumulative_evidence(self):
        recent = [{
            "run_id": "logout-run",
            "adapter": "scheduler_a",
            "domain": "美食",
            "profile_cookie_valid": False,
            "evidence_count": 17,
            "status": "failed",
            "error_code": "server_session_logged_out",
            "checked_at": "2026-07-16T14:12:00",
            "details": {
                "access_status": "login_required",
                "latest_run_evidence_count": 0,
            },
        }]

        def fake_setting(key, default=None):
            if key == admin_server._XHS_COOKIES_KEY:
                return [{"name": "redacted"}]
            if key == admin_server._CRAWLER_CONFIG_KEY:
                return {"enabled": True}
            return default

        with (
            patch.object(admin_server._settings, "get_json", side_effect=fake_setting),
            patch.object(admin_server._xhs_acq, "recent_health", return_value=recent),
            patch.object(admin_server.db, "fetchone", return_value={"cnt": 0}),
        ):
            status = asyncio.run(
                admin_server.admin_crawler_status(admin={"username": "admin"})
            )

        self.assertEqual(status["cookie_runtime_status"], "needs_relogin")
        self.assertTrue(status["cookie_action_required"])
        self.assertIsNone(status["cookie_last_verified_at"])

    def test_admin_cookie_update_clears_only_persisted_session_block(self):
        config = {"enabled": True}

        def fake_setting(key, default=None):
            if key == admin_server._CRAWLER_CONFIG_KEY:
                return dict(config)
            return default

        with (
            patch.object(admin_server._settings, "get_json", side_effect=fake_setting),
            patch.object(admin_server._settings, "set_json") as set_json,
            patch.object(
                admin_server._xhs_acq,
                "clear_collection_session_block",
            ) as clear_block,
        ):
            result = asyncio.run(admin_server.admin_update_cookie(
                admin_server.CookieUpdateInput(
                    cookies_json='[{"name":"synthetic-cookie"}]'
                ),
                admin={"username": "admin"},
            ))

        self.assertTrue(result["ok"])
        self.assertEqual(result["cookie_count"], 1)
        clear_block.assert_called_once_with()
        self.assertTrue(any(
            call.args[0] == admin_server._XHS_COOKIES_KEY
            and call.kwargs.get("is_secret") is True
            for call in set_json.call_args_list
        ))

    def test_collection_health_combines_direct_and_legacy_adapter_ledgers(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                for adapter, checked_at in (
                    ("scheduler_a", "2026-07-22T01:00:00"),
                    ("xhs_downloader", "2026-07-22T02:00:00"),
                    ("spider_xhs_http", "2026-07-22T03:00:00"),
                ):
                    xhs_acquisition.record_health({
                        "run_id": adapter,
                        "adapter": adapter,
                        "domain": "美食",
                        "status": "ok",
                        "checked_at": checked_at,
                    })

                rows = xhs_acquisition.recent_collection_health(domain="美食")

                self.assertEqual(
                    [row["adapter"] for row in rows],
                    ["spider_xhs_http", "scheduler_a"],
                )
                self.assertNotIn("xhs_downloader", {row["adapter"] for row in rows})
        finally:
            hot_keywords.DB_PATH = original_db


if __name__ == "__main__":
    unittest.main()
