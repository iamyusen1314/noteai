import importlib
import json
import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

api = importlib.import_module("api")
db = importlib.import_module("db")
admin_server = importlib.import_module("admin_server")


def _healthy_market_payload():
    return {
        "ok": True,
        "blocking_readiness": False,
        "freshness_hours": 1.5,
        "xhs_cumulative_fresh": True,
        "latest_run_source_health": {
            "available": True,
            "ok": True,
            "status": "healthy",
            "error_code": "",
            "evidence_count": 20,
            "source_breakdown": {
                "homefeed": 3,
                "search_result": 8,
                "search_recommend": 5,
                "hot_search": 4,
                "other": 0,
            },
            "missing_sources": [],
            "run_id": "safe-run-id",
            "checked_at": "2026-07-11T12:00:00+00:00",
            "domains": ["美食"],
        },
        "source_observation_action_required": False,
    }


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class MarketReadinessCacheTests(unittest.TestCase):
    def test_unknown_market_booleans_keep_legacy_types(self):
        unknown = api._unknown_market_readiness_observation()
        self.assertIs(type(unknown["ok"]), bool)
        self.assertIs(type(unknown["xhs_cumulative_fresh"]), bool)
        self.assertFalse(unknown["ok"])
        self.assertFalse(unknown["xhs_cumulative_fresh"])

        with (
            mock.patch.object(api, "db_status", return_value={"latest_capture": "now"}),
            mock.patch.object(api._xhs_acq, "freshness_overview", side_effect=RuntimeError("down")),
        ):
            failed_collection = api._collect_market_readiness_observation()
        self.assertIs(type(failed_collection["xhs_cumulative_fresh"]), bool)
        self.assertFalse(failed_collection["xhs_cumulative_fresh"])

    def test_cold_cache_returns_unknown_without_waiting_for_collector(self):
        started = threading.Event()
        release = threading.Event()

        def collector():
            started.set()
            release.wait(2)
            return _healthy_market_payload()

        cache = api._MarketReadinessCache(
            collector,
            ttl_seconds=60,
            max_stale_seconds=300,
        )
        began = time.perf_counter()
        snapshot = cache.snapshot()
        elapsed = time.perf_counter() - began

        self.assertLess(elapsed, 0.25)
        self.assertEqual(snapshot["observation_status"], "unknown")
        self.assertFalse(snapshot["ok"])
        self.assertTrue(snapshot["observation_refreshing"])
        self.assertTrue(started.wait(1))

        release.set()
        self.assertTrue(cache.wait_for_refresh(1))
        fresh = cache.snapshot()
        self.assertEqual(fresh["observation_status"], "fresh")
        self.assertTrue(fresh["ok"])

    def test_twenty_concurrent_probes_start_only_one_refresh(self):
        started = threading.Event()
        release = threading.Event()
        calls = 0
        calls_lock = threading.Lock()

        def collector():
            nonlocal calls
            with calls_lock:
                calls += 1
            started.set()
            release.wait(2)
            return _healthy_market_payload()

        cache = api._MarketReadinessCache(
            collector,
            ttl_seconds=60,
            max_stale_seconds=300,
        )
        with (
            ThreadPoolExecutor(max_workers=20) as pool,
        ):
            snapshots = list(pool.map(lambda _: cache.snapshot(), range(20)))

        self.assertTrue(started.wait(1))
        self.assertEqual(calls, 1)
        self.assertTrue(all(row["observation_status"] == "unknown" for row in snapshots))
        release.set()
        self.assertTrue(cache.wait_for_refresh(1))
        self.assertFalse(cache.snapshot()["observation_refreshing"])

    def test_stale_and_max_stale_states_are_explicit_and_cache_is_not_mutable(self):
        now = [0.0]
        second_started = threading.Event()
        second_release = threading.Event()
        calls = 0

        def collector():
            nonlocal calls
            calls += 1
            if calls > 1:
                second_started.set()
                second_release.wait(2)
            return _healthy_market_payload()

        cache = api._MarketReadinessCache(
            collector,
            clock=lambda: now[0],
            ttl_seconds=10,
            max_stale_seconds=30,
        )
        cache.snapshot()
        self.assertTrue(cache.wait_for_refresh(1))

        fresh = cache.snapshot()
        fresh["latest_run_source_health"]["run_id"] = "mutated-by-caller"
        self.assertEqual(
            cache.snapshot()["latest_run_source_health"]["run_id"],
            "safe-run-id",
        )

        now[0] = 11.0
        stale = cache.snapshot()
        self.assertEqual(stale["observation_status"], "stale")
        self.assertTrue(stale["observation_stale"])
        self.assertTrue(stale["ok"])
        self.assertTrue(second_started.wait(1))

        now[0] = 31.0
        expired = cache.snapshot()
        self.assertEqual(expired["observation_status"], "unknown")
        self.assertFalse(expired["ok"])
        self.assertTrue(expired["source_observation_action_required"])

        second_release.set()
        self.assertTrue(cache.wait_for_refresh(1))

    def test_hung_refresh_has_bounded_recovery_and_old_generation_cannot_overwrite(self):
        now = [0.0]
        first_release = threading.Event()
        first_started = threading.Event()
        second_done = threading.Event()
        calls = 0

        def collector():
            nonlocal calls
            calls += 1
            if calls == 1:
                first_started.set()
                first_release.wait(2)
                payload = _healthy_market_payload()
                payload["freshness_hours"] = 99
                return payload
            payload = _healthy_market_payload()
            payload["freshness_hours"] = 2
            second_done.set()
            return payload

        cache = api._MarketReadinessCache(
            collector,
            clock=lambda: now[0],
            ttl_seconds=10,
            max_stale_seconds=30,
            refresh_hard_age_seconds=5,
        )
        self.assertEqual(cache.snapshot()["observation_status"], "unknown")
        self.assertTrue(first_started.wait(1))

        now[0] = 6
        recovering = cache.snapshot()
        self.assertLessEqual(recovering["observation_refresh_workers"], 2)
        self.assertTrue(second_done.wait(1))
        self.assertTrue(_wait_until(lambda: cache.snapshot()["freshness_hours"] == 2))

        first_release.set()
        self.assertTrue(_wait_until(lambda: cache.snapshot()["observation_refresh_workers"] == 0))
        final = cache.snapshot()
        self.assertEqual(final["freshness_hours"], 2)
        self.assertEqual(calls, 2)

    def test_two_hung_refreshes_remain_bounded_under_repeated_probes(self):
        now = [0.0]
        release = threading.Event()
        two_started = threading.Event()
        calls = 0
        lock = threading.Lock()

        def collector():
            nonlocal calls
            with lock:
                calls += 1
                if calls == 2:
                    two_started.set()
            release.wait(2)
            return _healthy_market_payload()

        cache = api._MarketReadinessCache(
            collector,
            clock=lambda: now[0],
            ttl_seconds=10,
            max_stale_seconds=30,
            refresh_hard_age_seconds=5,
        )
        try:
            cache.snapshot()
            now[0] = 6
            cache.snapshot()
            self.assertTrue(two_started.wait(1))
            for tick in range(7, 100):
                now[0] = float(tick)
                snapshot = cache.snapshot()
                self.assertLessEqual(snapshot["observation_refresh_workers"], 2)
            self.assertEqual(calls, 2)
            self.assertEqual(snapshot["observation_status"], "unknown")
        finally:
            release.set()
            self.assertTrue(cache.wait_for_refresh(1))

    def test_refresh_exception_keeps_last_good_then_retries(self):
        now = [0.0]
        calls = 0

        def collector():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("safe failure")
            payload = _healthy_market_payload()
            payload["freshness_hours"] = calls
            return payload

        cache = api._MarketReadinessCache(
            collector,
            clock=lambda: now[0],
            ttl_seconds=10,
            max_stale_seconds=40,
            refresh_hard_age_seconds=5,
        )
        cache.snapshot()
        self.assertTrue(cache.wait_for_refresh(1))
        self.assertEqual(cache.snapshot()["freshness_hours"], 1)

        now[0] = 11
        cache.snapshot()
        self.assertTrue(cache.wait_for_refresh(1))
        failed = cache.snapshot()
        self.assertEqual(failed["freshness_hours"], 1)
        self.assertTrue(failed["observation_refresh_failed"])

        now[0] = 21
        cache.snapshot()
        self.assertTrue(cache.wait_for_refresh(1))
        recovered = cache.snapshot()
        self.assertEqual(recovered["freshness_hours"], 3)
        self.assertFalse(recovered["observation_refresh_failed"])

    def test_readiness_does_not_call_optional_or_external_dependencies(self):
        cache = SimpleNamespace(snapshot=mock.Mock(side_effect=AssertionError("market called")))
        database_health = mock.Mock(return_value={"ok": True})
        database_probe = api._DatabaseReadinessProbe(
            database_health,
            timeout_seconds=0.1,
            result_ttl_seconds=0,
        )
        with (
            mock.patch.object(api, "_market_readiness_cache", cache, create=True),
            mock.patch.object(api, "_database_readiness_probe", database_probe),
            mock.patch.object(api, "get_v04_composite_model", return_value=object()),
            mock.patch.object(api, "db_status", side_effect=AssertionError("sync market query")),
            mock.patch.object(api._xhs_acq, "freshness_overview", side_effect=AssertionError("sync market query")),
            mock.patch.object(api._mr, "claude_transport_readiness", side_effect=AssertionError("gateway called")),
            mock.patch.object(api._facts, "meituan_travel_runtime_status", side_effect=AssertionError("meituan called")),
        ):
            payload, status_code = api._readiness_payload()

        self.assertEqual(status_code, 200)
        self.assertEqual(set(payload["checks"]), {"database", "model"})
        cache.snapshot.assert_not_called()
        database_health.assert_called_once_with()

    def test_market_collector_preserves_only_safe_source_health_fields(self):
        latest = {
            **_healthy_market_payload()["latest_run_source_health"],
            "cookie": "must-not-leak",
            "source_url": "https://private.invalid/path",
            "response_body": "must-not-leak",
        }
        with (
            mock.patch.object(api, "db_status", return_value={"latest_capture": "now", "freshness_hours": 1}),
            mock.patch.object(api._xhs_acq, "freshness_overview", return_value={"ok": True, "latest_run_source_health": latest}),
        ):
            result = api._collect_market_readiness_observation()

        serialized = json.dumps(result).lower()
        self.assertNotIn("cookie", serialized)
        self.assertNotIn("private.invalid", serialized)
        self.assertNotIn("response_body", serialized)
        self.assertEqual(result["latest_run_source_health"]["run_id"], "safe-run-id")


class DatabaseHealthTimeoutTests(unittest.TestCase):
    class _FakeConnection:
        def __init__(self):
            self.row_factory = None
            self.progress_handlers = []
            self.functions = []
            self.closed = False

        def create_function(self, name, arity, function, **kwargs):
            self.functions.append((name, arity, function, kwargs))

        def execute(self, _sql, _params=()):
            return self

        def fetchone(self):
            return {"ok": 1}

        def set_progress_handler(self, callback, steps):
            self.progress_handlers.append((callback, steps))

        def close(self):
            self.closed = True

    def test_postgres_health_timeouts_do_not_change_regular_get_conn(self):
        health_conn = self._FakeConnection()
        regular_conn = self._FakeConnection()
        connect = mock.Mock(side_effect=[health_conn, regular_conn])
        fake_psycopg = SimpleNamespace(connect=connect)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_psycopg}),
            mock.patch.object(db, "using_postgres", return_value=True),
            mock.patch.object(db, "_database_url", return_value="postgresql://example.invalid/noteai"),
        ):
            result = db.database_health()
            conn = db.get_conn()
            conn.close()

        self.assertTrue(result["ok"])
        health_kwargs = connect.call_args_list[0].kwargs
        regular_kwargs = connect.call_args_list[1].kwargs
        self.assertEqual(health_kwargs["connect_timeout"], 1)
        self.assertIn("timezone=UTC", health_kwargs["options"])
        self.assertIn("statement_timeout", health_kwargs["options"])
        self.assertIn("=1000", health_kwargs["options"])
        self.assertNotIn("connect_timeout", regular_kwargs)
        self.assertIn("timezone=UTC", regular_kwargs["options"])
        self.assertNotIn("statement_timeout", regular_kwargs["options"])

    def test_sqlite_health_timeout_does_not_change_regular_get_conn(self):
        health_conn = self._FakeConnection()
        regular_conn = self._FakeConnection()
        connect = mock.Mock(side_effect=[health_conn, regular_conn])

        with (
            mock.patch.object(db, "using_postgres", return_value=False),
            mock.patch.object(db.sqlite3, "connect", connect),
        ):
            result = db.database_health()
            conn = db.get_conn()
            conn.close()

        self.assertTrue(result["ok"])
        health_kwargs = connect.call_args_list[0].kwargs
        regular_kwargs = connect.call_args_list[1].kwargs
        self.assertEqual(health_kwargs["timeout"], 1)
        self.assertNotIn("timeout", regular_kwargs)
        self.assertTrue(health_conn.progress_handlers)
        self.assertEqual(health_conn.progress_handlers[-1], (None, 0))
        self.assertFalse(regular_conn.progress_handlers)
        for connection in (health_conn, regular_conn):
            self.assertEqual(
                [
                    (name, arity, options)
                    for name, arity, _, options in connection.functions
                ],
                [
                    (
                        "noteai_retention_clock_valid",
                        1,
                        {"deterministic": True},
                    ),
                    (
                        "noteai_retention_clock_lte",
                        2,
                        {"deterministic": True},
                    ),
                    ("noteai_retention_clock_not_future", 1, {}),
                ],
            )

    def test_sqlite_cleanup_closes_even_when_progress_handler_reset_raises(self):
        conn = self._FakeConnection()
        original_handler = conn.set_progress_handler

        def set_progress_handler(callback, steps):
            if callback is None:
                raise RuntimeError("cleanup failed")
            original_handler(callback, steps)

        conn.set_progress_handler = set_progress_handler
        with (
            mock.patch.object(db, "using_postgres", return_value=False),
            mock.patch.object(db, "_get_sqlite_conn", return_value=conn),
            self.assertRaisesRegex(RuntimeError, "cleanup failed"),
        ):
            db.database_health()
        self.assertTrue(conn.closed)

    def test_sqlite_query_error_still_resets_handler_and_closes(self):
        conn = self._FakeConnection()
        calls = 0

        def execute(_sql, _params=()):
            nonlocal calls
            calls += 1
            raise RuntimeError("query failed")

        conn.execute = execute
        with (
            mock.patch.object(db, "using_postgres", return_value=False),
            mock.patch.object(db, "_get_sqlite_conn", return_value=conn),
            self.assertRaisesRegex(RuntimeError, "query failed"),
        ):
            db.database_health()
        self.assertEqual(calls, 1)
        self.assertEqual(conn.progress_handlers[-1], (None, 0))
        self.assertTrue(conn.closed)

    def test_database_and_model_are_the_only_blocking_contracts(self):
        def readiness(database_result=None, database_error=None, model=object()):
            db_probe = (
                mock.Mock(side_effect=database_error)
                if database_error
                else mock.Mock(return_value=database_result)
            )
            with (
                mock.patch.object(api, "USE_V04_COMPOSITE", True),
                mock.patch.object(
                    api,
                    "_database_readiness_probe",
                    SimpleNamespace(result=db_probe),
                ),
                mock.patch.object(api, "get_v04_composite_model", return_value=model),
                mock.patch.object(api._mr, "claude_transport_readiness", side_effect=AssertionError("gateway called")),
                mock.patch.object(api._facts, "meituan_travel_runtime_status", side_effect=AssertionError("meituan called")),
                mock.patch.object(api._market_readiness_cache, "snapshot", side_effect=AssertionError("market called")),
                mock.patch.dict(os.environ, {}, clear=True),
            ):
                return api._readiness_payload()

        self.assertEqual(readiness({"ok": False})[1], 503)
        self.assertEqual(readiness(database_error=RuntimeError("db down"))[1], 503)
        self.assertEqual(readiness({"ok": True}, model=None)[1], 503)
        payload, status_code = readiness({"ok": True})
        self.assertEqual(status_code, 200)
        self.assertEqual(set(payload["checks"]), {"database", "model"})

    def test_admin_database_exception_returns_503(self):
        with (
            mock.patch.object(admin_server.db, "database_health", side_effect=RuntimeError("db down")),
            mock.patch.dict(os.environ, {"ADMIN_PASSWORD": "configured"}),
        ):
            response = TestClient(admin_server.admin_app).get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["checks"]["database"]["ok"])

        with (
            mock.patch.object(admin_server.db, "database_health", return_value={"ok": True}),
            mock.patch.dict(os.environ, {"ADMIN_PASSWORD": "configured"}),
        ):
            healthy = TestClient(admin_server.admin_app).get("/health/ready")
        self.assertEqual(healthy.status_code, 200)

    def test_live_endpoint_does_not_touch_database_or_market_cache(self):
        with (
            mock.patch.object(api._db, "database_health", side_effect=AssertionError("database touched")),
            mock.patch.object(api, "_market_readiness_cache", create=True) as cache,
            mock.patch.object(api, "_database_readiness_probe", create=True) as database_probe,
        ):
            response = TestClient(api.app).get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "noteai-api"})
        cache.snapshot.assert_not_called()
        database_probe.result.assert_not_called()


class DatabaseReadinessProbeTests(unittest.TestCase):
    def test_slow_probe_returns_bounded_timeout(self):
        release = threading.Event()

        def collector():
            release.wait(1)
            return {"ok": True, "backend": "postgresql"}

        probe = api._DatabaseReadinessProbe(
            collector,
            timeout_seconds=0.05,
            hard_age_seconds=0.2,
            result_ttl_seconds=0,
        )
        try:
            began = time.perf_counter()
            result = probe.result()
            elapsed = time.perf_counter() - began
            self.assertLess(elapsed, 0.18)
            self.assertEqual(result, {"ok": False, "error": "DatabaseHealthTimeout"})
        finally:
            release.set()
            self.assertTrue(probe.wait_for_workers(1))

    def test_twenty_concurrent_requests_share_one_inflight_db_call(self):
        release = threading.Event()
        started = threading.Event()
        calls = 0
        lock = threading.Lock()

        def collector():
            nonlocal calls
            with lock:
                calls += 1
            started.set()
            release.wait(1)
            return {"ok": True, "backend": "postgresql"}

        probe = api._DatabaseReadinessProbe(
            collector,
            timeout_seconds=0.2,
            hard_age_seconds=1,
            result_ttl_seconds=0,
        )
        try:
            with ThreadPoolExecutor(max_workers=20) as pool:
                futures = [pool.submit(probe.result) for _ in range(20)]
                self.assertTrue(started.wait(1))
                release.set()
                results = [future.result(1) for future in futures]
            self.assertEqual(calls, 1)
            self.assertTrue(all(row["ok"] for row in results))
        finally:
            release.set()
            self.assertTrue(probe.wait_for_workers(1))

    def test_hard_age_replacement_recovers_and_old_result_cannot_overwrite(self):
        now = [0.0]
        first_release = threading.Event()
        first_started = threading.Event()
        calls = 0

        def collector():
            nonlocal calls
            calls += 1
            if calls == 1:
                first_started.set()
                first_release.wait(1)
                return {"ok": False, "backend": "old"}
            return {"ok": True, "backend": "recovered"}

        probe = api._DatabaseReadinessProbe(
            collector,
            clock=lambda: now[0],
            timeout_seconds=0.02,
            hard_age_seconds=5,
            result_ttl_seconds=0,
        )
        self.assertEqual(probe.result()["error"], "DatabaseHealthTimeout")
        self.assertTrue(first_started.wait(1))

        now[0] = 6
        recovered = probe.result()
        self.assertTrue(recovered["ok"])
        self.assertEqual(recovered["backend"], "recovered")
        self.assertEqual(calls, 2)

        first_release.set()
        self.assertTrue(probe.wait_for_workers(1))
        self.assertEqual(probe.latest_result()["backend"], "recovered")

    def test_two_hung_generations_are_resource_upper_bound(self):
        now = [0.0]
        release = threading.Event()
        calls = 0
        lock = threading.Lock()

        def collector():
            nonlocal calls
            with lock:
                calls += 1
            release.wait(1)
            return {"ok": True}

        probe = api._DatabaseReadinessProbe(
            collector,
            clock=lambda: now[0],
            timeout_seconds=0.005,
            hard_age_seconds=5,
            result_ttl_seconds=0,
        )
        try:
            probe.result()
            now[0] = 6
            probe.result()
            for tick in range(7, 30):
                now[0] = float(tick)
                result = probe.result()
                self.assertEqual(result["error"], "DatabaseHealthTimeout")
                self.assertLessEqual(probe.active_worker_count(), 2)
            self.assertEqual(calls, 2)
        finally:
            release.set()
            self.assertTrue(probe.wait_for_workers(1))

    def test_normal_and_exception_results_are_safe(self):
        healthy = api._DatabaseReadinessProbe(
            lambda: {"ok": True, "backend": "postgresql"},
            timeout_seconds=0.05,
            result_ttl_seconds=0,
        )
        self.assertTrue(healthy.result()["ok"])

        failed = api._DatabaseReadinessProbe(
            lambda: (_ for _ in ()).throw(ValueError("sensitive detail")),
            timeout_seconds=0.05,
            result_ttl_seconds=0,
        )
        self.assertEqual(failed.result(), {"ok": False, "error": "ValueError"})

    def test_api_wall_clock_budget_returns_503_without_waiting_forever(self):
        self.assertEqual(api._database_readiness_probe._timeout_seconds, 1.5)
        release = threading.Event()
        probe = api._DatabaseReadinessProbe(
            lambda: (release.wait(1), {"ok": True})[1],
            timeout_seconds=0.05,
            hard_age_seconds=0.2,
            result_ttl_seconds=0,
        )
        market = SimpleNamespace(snapshot=mock.Mock(return_value={
            **api._unknown_market_readiness_observation(),
            "observation_status": "unknown",
        }))
        try:
            began = time.perf_counter()
            with (
                mock.patch.object(api, "_database_readiness_probe", probe, create=True),
                mock.patch.object(api, "_market_readiness_cache", market),
                mock.patch.object(api, "_SCHEDULER_AVAILABLE", True),
                mock.patch.object(api, "USE_V04_COMPOSITE", True),
                mock.patch.object(api, "get_v04_composite_model", return_value=object()),
                mock.patch.dict(os.environ, {"NOTEAI_READINESS_REQUIRE_AI_KEYS": "0"}),
            ):
                payload, status_code = api._readiness_payload()
            elapsed = time.perf_counter() - began
            self.assertLess(elapsed, 0.18)
            self.assertEqual(status_code, 503)
            self.assertEqual(payload["checks"]["database"]["error"], "DatabaseHealthTimeout")
        finally:
            release.set()
            self.assertTrue(probe.wait_for_workers(1))


if __name__ == "__main__":
    unittest.main()
