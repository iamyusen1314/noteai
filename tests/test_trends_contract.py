import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import hot_keywords  # noqa: E402
import market_timing_worker  # noqa: E402
import spider_xhs_http  # noqa: E402
import trends_contract  # noqa: E402
import xhs_acquisition  # noqa: E402


def _valid_snapshot() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-26T00:00:00+00:00",
        "freshness_max_hours": 30,
        "domains": {
            domain: {
                "captured_at": "2026-07-26T00:00:00+00:00",
                "keywords": [
                    {
                        "keyword": f"{domain}趋势{index:02d}",
                        "search_vol": 80,
                        "trend_dir": 1,
                        "source": "search_phrase",
                        "category": domain,
                        "sample_count": 2,
                        "quality_score": 70,
                        "evidence_level": "medium",
                        "quality_reason": "test",
                        "captured_at": "2026-07-26T00:00:00+00:00",
                    }
                    for index in range(12)
                ],
            }
            for domain in trends_contract.REQUIRED_DOMAINS
        },
    }


class TrendsContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = hot_keywords.DB_PATH
        hot_keywords.DB_PATH = Path(self.temp.name) / "trends.db"
        hot_keywords.init_db()

    def tearDown(self):
        hot_keywords.DB_PATH = self.original_path
        self.temp.cleanup()

    def test_claim_is_single_winner_and_daily_bucket_is_idempotent(self):
        lease = trends_contract.claim_daily_run()
        with self.assertRaises(trends_contract.TrendsRunBusy):
            trends_contract.claim_daily_run()
        trends_contract.finish_run(
            lease,
            succeeded=False,
            error_code="synthetic_failure",
        )
        with self.assertRaises(trends_contract.TrendsRunAlreadyCompleted):
            trends_contract.claim_daily_run()

    def test_stale_admission_becomes_unknown_and_requires_explicit_ack(self):
        lease = trends_contract.claim_daily_run(
            now=trends_contract._utc_now() - timedelta(minutes=5)
        )
        with trends_contract.activate_run(lease):
            attempt = trends_contract.admit_provider_request("homefeed")
        expired = (
            trends_contract._utc_now() - timedelta(minutes=1)
        ).isoformat()
        conn = hot_keywords._conn()
        try:
            with conn:
                conn.execute(
                    "UPDATE xhs_trends_service_state SET lease_expires_at=?",
                    (expired,),
                )
                conn.execute(
                    "UPDATE xhs_trends_runs SET lease_expires_at=? WHERE id=?",
                    (expired, lease.run_id),
                )
        finally:
            conn.close()

        with self.assertRaisesRegex(
            trends_contract.TrendsNeedsManualReview,
            "provider_outcome_unknown",
        ):
            trends_contract.claim_daily_run()
        conn = hot_keywords._conn()
        try:
            attempt_row = conn.execute(
                "SELECT status,error_code FROM xhs_trends_provider_attempts WHERE id=?",
                (attempt.attempt_id,),
            ).fetchone()
            run_row = conn.execute(
                "SELECT status,last_error_code FROM xhs_trends_runs WHERE id=?",
                (lease.run_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(attempt_row["status"], "outcome_unknown")
        self.assertEqual(run_row["status"], "needs_manual")
        self.assertEqual(
            trends_contract.readiness_status()["reason"],
            "trends_provider_outcome_unknown",
        )

        ack = trends_contract.acknowledge_provider_outcome_unknown()
        self.assertFalse(ack["retry_performed"])
        self.assertFalse(ack["provider_called"])
        self.assertEqual(trends_contract.readiness_status()["status"], "ready")
        with self.assertRaises(trends_contract.TrendsRunAlreadyCompleted):
            trends_contract.claim_daily_run()

    def test_stale_no_provider_run_is_terminalized_without_rollback(self):
        current = trends_contract._utc_now()
        lease = trends_contract.claim_daily_run(
            now=current - timedelta(hours=1)
        )
        with self.assertRaises(trends_contract.TrendsRunAlreadyCompleted):
            trends_contract.claim_daily_run(now=current)
        conn = hot_keywords._conn()
        try:
            run = conn.execute(
                """
                SELECT status,last_error_code,completed_at
                FROM xhs_trends_runs WHERE id=?
                """,
                (lease.run_id,),
            ).fetchone()
            state = conn.execute(
                """
                SELECT status,active_run_id,lease_token_hash,lease_expires_at
                FROM xhs_trends_service_state
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(run["status"], "failed")
        self.assertEqual(
            run["last_error_code"],
            "lease_expired_before_provider",
        )
        self.assertTrue(run["completed_at"])
        self.assertEqual(state["status"], "idle")
        self.assertIsNone(state["active_run_id"])
        self.assertIsNone(state["lease_token_hash"])
        self.assertIsNone(state["lease_expires_at"])
        self.assertEqual(trends_contract.readiness_status()["status"], "ready")

    def test_provider_budget_is_durable_and_hard_capped(self):
        lease = trends_contract.claim_daily_run()
        with trends_contract.activate_run(lease):
            for _index in range(trends_contract.MAX_PROVIDER_REQUESTS_PER_RUN):
                attempt = trends_contract.admit_provider_request("homefeed")
                trends_contract.complete_provider_request(
                    attempt,
                    outcome="succeeded",
                )
            with self.assertRaises(trends_contract.TrendsDailyLimitReached):
                trends_contract.admit_provider_request("homefeed")
        self.assertEqual(
            trends_contract.provider_attempt_count(lease.run_id),
            34,
        )

    def test_live_admission_is_healthy_but_unlinked_is_not(self):
        lease = trends_contract.claim_daily_run()
        with trends_contract.activate_run(lease):
            trends_contract.admit_provider_request("search_recommend")
        live = trends_contract.readiness_status()
        self.assertEqual(live["status"], "ready")
        self.assertEqual(live["active_provider_attempts"], 1)
        conn = hot_keywords._conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE xhs_trends_service_state
                    SET active_run_id=NULL,status='idle',lease_token_hash=NULL,
                        lease_expires_at=NULL
                    """
                )
        finally:
            conn.close()
        self.assertEqual(
            trends_contract.readiness_status()["reason"],
            "trends_provider_attempt_unlinked",
        )

    def test_historical_success_does_not_hide_current_stale_lease(self):
        base = trends_contract._utc_now()
        completed = trends_contract.claim_daily_run(now=base)
        with trends_contract.activate_run(completed):
            attempt = trends_contract.admit_provider_request("homefeed")
            trends_contract.complete_provider_request(
                attempt,
                outcome="succeeded",
            )
            payload = _valid_snapshot()
            raw = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            with trends_contract.publish_transaction(completed) as connection:
                evidence = trends_contract.record_snapshot_evidence(
                    connection,
                    completed,
                    payload,
                    raw,
                )
                trends_contract.finish_run(
                    completed,
                    succeeded=True,
                    snapshot_sha256=evidence["sha256"],
                    snapshot_size=evidence["size"],
                    _connection=connection,
                )
        conn = hot_keywords._conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE xhs_trends_snapshot_evidence
                    SET domain_counts_json=?
                    WHERE run_id=?
                    """,
                    ('{"美食":12}', completed.run_id),
                )
        finally:
            conn.close()
        tampered = trends_contract.readiness_status()
        self.assertEqual(tampered["status"], "not_ready")
        self.assertEqual(
            tampered["reason"],
            "trends_snapshot_evidence_invalid",
        )
        conn = hot_keywords._conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE xhs_trends_snapshot_evidence
                    SET domain_counts_json=?
                    WHERE run_id=?
                    """,
                    (
                        json.dumps(
                            {
                                domain: 12
                                for domain in trends_contract.REQUIRED_DOMAINS
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        completed.run_id,
                    ),
                )
        finally:
            conn.close()
        active = trends_contract.claim_daily_run(
            now=base + timedelta(days=1)
        )
        health = trends_contract.readiness_status(
            now=active.expires_at + timedelta(seconds=1)
        )
        self.assertEqual(health["status"], "not_ready")
        self.assertEqual(health["reason"], "trends_run_lease_stale")

    def test_keyword_bound_is_deterministic_six_by_fifteen(self):
        rows = []
        for domain in trends_contract.REQUIRED_DOMAINS:
            for index in range(30):
                rows.append({
                    "keyword": f"{domain}测试趋势{index:02d}",
                    "category": domain,
                    "source": "search_phrase",
                    "search_vol": 50 + index,
                    "count": 2,
                })
        rows.append({
            "keyword": "额外领域测试",
            "category": "额外",
            "source": "search_phrase",
            "count": 2,
        })
        first = trends_contract.bound_keyword_rows(rows)
        second = trends_contract.bound_keyword_rows(list(reversed(rows)))
        self.assertEqual(
            [(row["category"], row["keyword"]) for row in first],
            [(row["category"], row["keyword"]) for row in second],
        )
        self.assertEqual(len(first), 90)
        self.assertEqual(
            {
                domain: sum(row["category"] == domain for row in first)
                for domain in trends_contract.REQUIRED_DOMAINS
            },
            {domain: 15 for domain in trends_contract.REQUIRED_DOMAINS},
        )

    def test_snapshot_requires_exact_six_domains_and_bounded_evidence(self):
        payload = _valid_snapshot()
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        evidence = trends_contract.validate_snapshot_payload(payload, raw)
        self.assertEqual(evidence["keyword_count"], 72)
        self.assertEqual(len(evidence["sha256"]), 64)

        extra = json.loads(raw)
        extra["domains"]["额外"] = extra["domains"]["美食"]
        with self.assertRaisesRegex(
            trends_contract.TrendsContractError,
            "domains_invalid",
        ):
            trends_contract.validate_snapshot_payload(
                extra,
                json.dumps(extra, ensure_ascii=False).encode("utf-8"),
            )
        duplicate = _valid_snapshot()
        duplicate["domains"]["美食"]["keywords"] = [
            {
                "keyword": "",
                "category": "美食",
            }
            for _index in range(12)
        ]
        duplicate_raw = json.dumps(
            duplicate,
            ensure_ascii=False,
        ).encode("utf-8")
        with self.assertRaisesRegex(
            trends_contract.TrendsContractError,
            "keyword_invalid",
        ):
            trends_contract.validate_snapshot_payload(
                duplicate,
                duplicate_raw,
            )
        mismatched = _valid_snapshot()
        mismatched_raw = json.dumps(
            _valid_snapshot() | {"generated_at": "2026-07-27T00:00:00+00:00"},
            ensure_ascii=False,
        ).encode("utf-8")
        with self.assertRaisesRegex(
            trends_contract.TrendsContractError,
            "payload_mismatch",
        ):
            trends_contract.validate_snapshot_payload(
                mismatched,
                mismatched_raw,
            )
        with self.assertRaisesRegex(
            trends_contract.TrendsContractError,
            "payload_invalid",
        ):
            trends_contract.validate_snapshot_payload(
                payload,
                b'{"schema_version":NaN}',
            )

    def test_current_run_counts_unique_keywords_not_duplicate_rows(self):
        rows = []
        for domain in trends_contract.REQUIRED_DOMAINS:
            rows.extend({
                "keyword": f"{domain}本轮唯一趋势",
                "category": domain,
                "source": (
                    "search_phrase"
                    if index % 2 else "search_recommend"
                ),
                "count": 2,
                "search_vol": 80,
            } for index in range(12))
        result = xhs_acquisition.record_scrape_freshness(
            rows,
            domains=trends_contract.REQUIRED_DOMAINS,
            min_count=12,
            session_status={
                "configured": True,
                "auth_cookie_present": True,
                "auth_cookie_expired": False,
            },
        )
        self.assertEqual(result["latest_run_evidence_count"], 6)
        self.assertEqual(
            result["latest_run_domain_counts"],
            {domain: 1 for domain in trends_contract.REQUIRED_DOMAINS},
        )

    def test_snapshot_uses_only_current_publish_rows(self):
        historical = []
        current = []
        for domain in trends_contract.REQUIRED_DOMAINS:
            for index in range(15):
                historical.append({
                    "keyword": f"{domain}历史高分{index:02d}",
                    "category": domain,
                    "source": "hot_search",
                    "count": 8,
                    "search_vol": 95,
                })
                current.append({
                    "keyword": f"{domain}本轮趋势{index:02d}",
                    "category": domain,
                    "source": (
                        "search_phrase"
                        if index % 2 else "search_recommend"
                    ),
                    "count": 2,
                    "search_vol": 70,
                })
        hot_keywords.upsert_keywords(historical)
        publish_rows = trends_contract.build_publish_rows(current)
        payload, raw = trends_contract.snapshot_payload_from_rows(
            publish_rows
        )
        trends_contract.validate_snapshot_payload(payload, raw)
        serialized = raw.decode("utf-8")
        self.assertNotIn("历史高分", serialized)
        self.assertIn("本轮趋势", serialized)


    def test_atomic_snapshot_preserves_old_target_on_replace_failure(self):
        hot_keywords.ensure_daily_evidence_pack(
            max_per_domain=15,
            target_total_per_domain=15,
        )
        target = Path(self.temp.name) / "snapshot.json"
        target.write_text("old", encoding="utf-8")
        with patch.object(hot_keywords.os, "replace", side_effect=OSError("fail")):
            with self.assertRaises(OSError):
                hot_keywords.write_keyword_snapshot(
                    target,
                    max_per_domain=15,
                    domains=trends_contract.REQUIRED_DOMAINS,
                )
        self.assertEqual(target.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(target.parent.glob(".*.tmp")), [])

    def test_adapter_admits_before_network_and_finalizes_success(self):
        lease = trends_contract.claim_daily_run()

        class Signer:
            def sign(self, **_kwargs):
                return {"xs": "x", "xt": "t", "xs_common": "c"}

        class Response:
            status_code = 200

            def json(self):
                return {"success": True, "data": {"sug_items": []}}

        class Client:
            def request(_self, *_args, **_kwargs):
                conn = hot_keywords._conn()
                try:
                    row = conn.execute(
                        "SELECT status FROM xhs_trends_provider_attempts"
                    ).fetchone()
                finally:
                    conn.close()
                self.assertEqual(row["status"], "admitted")
                return Response()

        credentials = spider_xhs_http.SessionCredentials(
            cookie_header="a1=a; web_session=b",
            a1="a",
            cookie_count=2,
            auth_cookie_present=True,
            auth_cookie_expired=False,
        )
        adapter = spider_xhs_http.SpiderXHSHTTPAdapter(
            credentials=credentials,
            signer=Signer(),
            client=Client(),
        )
        with (
            patch.dict(os.environ, {
                "NOTEAI_RUNTIME_ROLE": "xhs-http",
                "NOTEAI_XHS_SERVICE": "trends",
                "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
            }, clear=False),
            trends_contract.activate_run(lease),
        ):
            adapter.search_recommend("测试")
        conn = hot_keywords._conn()
        try:
            row = conn.execute(
                "SELECT status FROM xhs_trends_provider_attempts"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "succeeded")

    def test_suspended_production_path_creates_no_database_or_snapshot(self):
        hot_keywords.DB_PATH.unlink()
        snapshot = Path(self.temp.name) / "snapshot.json"
        with patch.dict(os.environ, {
            "NOTEAI_RUNTIME_ROLE": "xhs-http",
            "NOTEAI_XHS_SERVICE": "trends",
            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "1",
        }, clear=False):
            result = asyncio.run(market_timing_worker.run_once(snapshot))
        self.assertTrue(result["skipped"])
        self.assertEqual(result["database_writes"], 0)
        self.assertFalse(result["provider_called"])
        self.assertFalse(hot_keywords.DB_PATH.exists())
        self.assertFalse(snapshot.exists())

    def test_partial_current_run_cannot_bypass_gate_and_writes_no_business_rows(self):
        snapshot = Path(self.temp.name) / "snapshot.json"

        async def partial_scrape(_configured_adapter):
            attempt = trends_contract.admit_provider_request("search_notes")
            trends_contract.complete_provider_request(
                attempt,
                outcome="succeeded",
            )
            return [{
                "keyword": "美食本轮唯一趋势",
                "category": "美食",
                "source": "search_phrase",
                "count": 2,
                "search_vol": 80,
            }]

        environment = {
            "NOTEAI_RUNTIME_ROLE": "xhs-http",
            "NOTEAI_XHS_SERVICE": "trends",
            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
            "NOTEAI_XHS_FRESHNESS_REQUIRED": "0",
            "NOTEAI_MARKET_TIMING_REQUIRED": "0",
        }
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                market_timing_worker,
                "_scrape_selected_adapter",
                new=AsyncMock(side_effect=partial_scrape),
            ),
            patch.object(
                market_timing_worker,
                "session_state_summary",
                return_value={
                    "configured": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                },
            ),
            patch.object(
                market_timing_worker,
                "collection_safety_status",
                return_value={"session_blocked": False, "reason_code": ""},
            ),
            patch.object(
                market_timing_worker,
                "challenge_cooldown_status",
                return_value={"active": False},
            ),
        ):
            with self.assertRaisesRegex(
                trends_contract.TrendsContractError,
                "current_run_xhs_evidence_incomplete",
            ):
                asyncio.run(market_timing_worker.run_once(snapshot))
        conn = hot_keywords._conn()
        try:
            counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table}"
                ).fetchone()["c"]
                for table in (
                    "hot_keywords",
                    "keyword_snapshots",
                    "xhs_crawler_health",
                    "xhs_freshness_ledger",
                    "xhs_trends_snapshot_evidence",
                )
            }
            run = conn.execute(
                """
                SELECT status,last_error_code,provider_attempt_count
                FROM xhs_trends_runs
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(set(counts.values()), {0})
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["provider_attempt_count"], 1)
        self.assertFalse(snapshot.exists())

    def test_success_atomically_binds_business_rows_and_snapshot_to_run(self):
        snapshot = Path(self.temp.name) / "snapshot.json"
        rows = []
        for domain in trends_contract.REQUIRED_DOMAINS:
            for index in range(12):
                rows.append({
                    "keyword": f"{domain}本轮真实趋势{index:02d}",
                    "category": domain,
                    "source": (
                        "search_phrase"
                        if index % 2 else "search_recommend"
                    ),
                    "count": 2,
                    "search_vol": 80 - index,
                })

        async def complete_scrape(_configured_adapter):
            attempt = trends_contract.admit_provider_request("search_notes")
            trends_contract.complete_provider_request(
                attempt,
                outcome="succeeded",
            )
            return rows

        environment = {
            "NOTEAI_RUNTIME_ROLE": "xhs-http",
            "NOTEAI_XHS_SERVICE": "trends",
            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
            "NOTEAI_XHS_FRESHNESS_REQUIRED": "0",
            "NOTEAI_MARKET_TIMING_REQUIRED": "0",
        }
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                market_timing_worker,
                "_scrape_selected_adapter",
                new=AsyncMock(side_effect=complete_scrape),
            ),
            patch.object(
                market_timing_worker,
                "session_state_summary",
                return_value={
                    "configured": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                },
            ),
            patch.object(
                market_timing_worker,
                "collection_safety_status",
                return_value={"session_blocked": False, "reason_code": ""},
            ),
            patch.object(
                market_timing_worker,
                "challenge_cooldown_status",
                return_value={"active": False},
            ),
        ):
            result = asyncio.run(market_timing_worker.run_once(snapshot))
        conn = hot_keywords._conn()
        try:
            run = conn.execute(
                "SELECT * FROM xhs_trends_runs"
            ).fetchone()
            evidence = conn.execute(
                "SELECT * FROM xhs_trends_snapshot_evidence"
            ).fetchone()
            counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table}"
                ).fetchone()["c"]
                for table in (
                    "hot_keywords",
                    "keyword_snapshots",
                    "xhs_crawler_health",
                    "xhs_freshness_ledger",
                    "xhs_trends_snapshot_evidence",
                )
            }
            ledger_run_ids = {
                row["last_run_id"] for row in conn.execute(
                    "SELECT last_run_id FROM xhs_freshness_ledger"
                ).fetchall()
            }
            health_run_ids = {
                row["run_id"] for row in conn.execute(
                    "SELECT run_id FROM xhs_crawler_health"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(result["evidence_mode"], "real_xhs")
        self.assertEqual(result["provider_calls"], 1)
        self.assertEqual(counts["hot_keywords"], 90)
        self.assertEqual(counts["keyword_snapshots"], 90)
        self.assertEqual(counts["xhs_crawler_health"], 6)
        self.assertEqual(counts["xhs_freshness_ledger"], 6)
        self.assertEqual(counts["xhs_trends_snapshot_evidence"], 1)
        self.assertEqual(ledger_run_ids, {run["id"]})
        self.assertEqual(health_run_ids, {run["id"]})
        self.assertEqual(evidence["run_id"], run["id"])
        self.assertEqual(evidence["snapshot_sha256"], run["snapshot_sha256"])
        self.assertEqual(evidence["snapshot_size"], run["snapshot_size"])
        self.assertFalse(snapshot.exists())
        self.assertEqual(trends_contract.readiness_status()["status"], "ready")

    def test_post_write_failure_rolls_back_every_business_row(self):
        rows = []
        for domain in trends_contract.REQUIRED_DOMAINS:
            for index in range(12):
                rows.append({
                    "keyword": f"{domain}事务回滚趋势{index:02d}",
                    "category": domain,
                    "source": (
                        "search_phrase"
                        if index % 2 else "search_recommend"
                    ),
                    "count": 2,
                    "search_vol": 80 - index,
                })

        async def complete_scrape(_configured_adapter):
            attempt = trends_contract.admit_provider_request("search_notes")
            trends_contract.complete_provider_request(
                attempt,
                outcome="succeeded",
            )
            return rows

        environment = {
            "NOTEAI_RUNTIME_ROLE": "xhs-http",
            "NOTEAI_XHS_SERVICE": "trends",
            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
        }
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                market_timing_worker,
                "_scrape_selected_adapter",
                new=AsyncMock(side_effect=complete_scrape),
            ),
            patch.object(
                market_timing_worker,
                "session_state_summary",
                return_value={
                    "configured": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                },
            ),
            patch.object(
                market_timing_worker,
                "collection_safety_status",
                return_value={"session_blocked": False, "reason_code": ""},
            ),
            patch.object(
                market_timing_worker,
                "challenge_cooldown_status",
                return_value={"active": False},
            ),
            patch.object(
                trends_contract,
                "record_snapshot_evidence",
                side_effect=trends_contract.TrendsContractError(
                    "synthetic_snapshot_failure"
                ),
            ),
        ):
            with self.assertRaisesRegex(
                trends_contract.TrendsContractError,
                "synthetic_snapshot_failure",
            ):
                asyncio.run(
                    market_timing_worker.run_once(
                        Path(self.temp.name) / "snapshot.json"
                    )
                )
        conn = hot_keywords._conn()
        try:
            counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table}"
                ).fetchone()["c"]
                for table in (
                    "hot_keywords",
                    "keyword_snapshots",
                    "xhs_crawler_health",
                    "xhs_freshness_ledger",
                    "xhs_trends_snapshot_evidence",
                )
            }
            run = conn.execute(
                "SELECT status,provider_attempt_count FROM xhs_trends_runs"
            ).fetchone()
            attempt = conn.execute(
                "SELECT status FROM xhs_trends_provider_attempts"
            ).fetchone()
            state = conn.execute(
                "SELECT status,active_run_id FROM xhs_trends_service_state"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(set(counts.values()), {0})
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["provider_attempt_count"], 1)
        self.assertEqual(attempt["status"], "succeeded")
        self.assertEqual(state["status"], "idle")
        self.assertIsNone(state["active_run_id"])

    def test_health_missing_sqlite_contract_is_read_only(self):
        hot_keywords.DB_PATH.unlink()
        before = set(Path(self.temp.name).iterdir())
        result = trends_contract.readiness_status()
        after = set(Path(self.temp.name).iterdir())
        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(before, after)

    def test_migration_and_role_contract_are_fail_closed(self):
        migration = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0011_trends_execution_contract.sql"
        ).read_text(encoding="utf-8")
        contract = (
            ROOT / "docs" / "XHS_TRENDS_PRODUCTION_CONTRACT.md"
        ).read_text(encoding="utf-8")
        compose = (
            ROOT / "deploy" / "production" / "docker-compose.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("GRANT ", migration.upper())
        self.assertNotIn("REVOKE ", migration.upper())
        self.assertIn("noteai_xhs_trends", contract)
        self.assertIn("zero access to `tracked_notes`", contract)
        self.assertIn("NOTEAI_XHS_SERVICE: trends", compose)
        self.assertIn('restart: "no"', compose)
        self.assertIn("market_timing_worker.py\", \"--healthcheck", compose)


if __name__ == "__main__":
    unittest.main()
