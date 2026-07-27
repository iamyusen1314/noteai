import contextlib
import io
import json
import os
import re
import unittest
from unittest import mock

from tools import collect_production_database_preflight as collector
from tools import production_readonly_preflight_gate as gate


class FakeCursor:
    def __init__(
        self,
        migration_rows=None,
        aggregate_override=None,
        migration_has_sha256=True,
        migration_selectable=True,
    ):
        hashes = gate._current_migration_hashes()
        filenames = {
            path.name.split("_", 1)[0]: path.name
            for path in gate.MIGRATION_DIR.glob("*.sql")
        }
        self.migration_rows = migration_rows or [
            (filenames[version], hashes[version])
            for version in collector.EXPECTED_APPLIED_VERSIONS
        ]
        self.aggregate_override = aggregate_override or {}
        self.migration_has_sha256 = migration_has_sha256
        self.migration_selectable = migration_selectable
        self.current_query = ""
        self.current_params = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=()):
        self.current_query = " ".join(str(query).split())
        self.current_params = params

    def fetchone(self):
        if self.current_query.startswith("SHOW "):
            return ("on",)
        if self.current_query == " ".join(
            collector.MIGRATION_SHA256_COLUMN_COUNT_QUERY.split()
        ):
            return (int(self.migration_has_sha256),)
        if self.current_query == " ".join(
            collector.MIGRATION_SELECT_CAPABILITY_QUERY.split()
        ):
            return (int(self.migration_selectable),)
        for name, query in collector.SOURCE_AGGREGATE_QUERIES.items():
            if " ".join(query.split()) == self.current_query:
                return (self.aggregate_override.get(name, 0),)
        scalar_queries = {
            " ".join(collector.OWNER_COUNT_QUERY.split()): 0,
            " ".join(collector.MEMBERSHIP_COUNT_QUERY.split()): 0,
            " ".join(collector.DATABASE_CAPABILITY_COUNT_QUERY.split()): 0,
            " ".join(collector.SCHEMA_CAPABILITY_COUNT_QUERY.split()): 0,
            " ".join(collector.MIGRATION_PRIVILEGE_COUNT_QUERY.split()): 0,
            " ".join(collector.GRANT_OPTION_COUNT_QUERY.split()): 0,
            " ".join(
                collector.TABLE_PRIVILEGE_MISMATCH_COUNT_QUERY.split()
            ): 0,
            " ".join(
                collector.SEQUENCE_PRIVILEGE_MISMATCH_COUNT_QUERY.split()
            ): 0,
        }
        if self.current_query in scalar_queries:
            return (scalar_queries[self.current_query],)
        raise AssertionError(f"unexpected scalar query: {self.current_query}")

    def fetchall(self):
        if self.current_query == " ".join(collector.MIGRATION_QUERY.split()):
            return self.migration_rows
        if self.current_query == " ".join(
            collector.LEGACY_MIGRATION_QUERY.split()
        ):
            return [(row[0],) for row in self.migration_rows]
        if self.current_query == " ".join(collector.ROLE_QUERY.split()):
            return [
                (
                    role,
                    False,
                    False,
                    False,
                    False,
                    True,
                    False,
                    False,
                )
                for role, state in gate.EXPECTED_ROLE_STATE.items()
                if state == "present"
            ]
        raise AssertionError(f"unexpected row query: {self.current_query}")


class FakeConnection:
    def __init__(self, cursor=None, rollback_error=False, close_error=False):
        self.fake_cursor = cursor or FakeCursor()
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def rollback(self):
        self.rolled_back = True
        if self.rollback_error:
            raise RuntimeError("sensitive rollback detail")

    def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError("sensitive close detail")


class ProductionDatabasePreflightCollectorTests(unittest.TestCase):
    def test_collection_is_exact_sanitized_and_rolled_back(self):
        connection = FakeConnection()
        evidence = collector.collect(
            {collector.DATABASE_URL_ENV: "postgresql://secret"},
            connector=lambda value: connection,
        )

        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)
        self.assertTrue(evidence["metadata_session_read_only"])
        self.assertEqual(evidence["business_row_values_read"], 0)
        self.assertEqual(
            evidence["aggregate_query_count"],
            len(gate.SOURCE_ZERO_AGGREGATES)
            + len(gate.SOURCE_INFORMATIONAL_AGGREGATES),
        )
        self.assertEqual(
            evidence["pending_versions"],
            list(collector.EXPECTED_PENDING_VERSIONS),
        )
        self.assertEqual(evidence["migration_ledger_source"], "stored_sha256")
        self.assertEqual(evidence["stored_migration_drift_count"], 0)
        self.assertEqual(evidence["source_preflight_blocker_count"], 0)
        self.assertEqual(evidence["unexpected_grant_count"], 0)
        self.assertEqual(evidence["role_state"], gate.EXPECTED_ROLE_STATE)
        self.assertEqual(len(collector.EXPECTED_PUBLIC_TABLES), 30)
        self.assertEqual(len(collector.APP_TABLE_PRIVILEGES), 29)
        self.assertEqual(
            len(collector.EXPECTED_TABLE_PRIVILEGE_ROWS),
            82 + 20,
        )
        self.assertEqual(
            len(collector.EXPECTED_SEQUENCE_PRIVILEGE_ROWS),
            5 + 3,
        )
        self.assertNotIn("secret", json.dumps(evidence))

    def test_source_blocker_is_counted_without_row_values(self):
        cursor = FakeCursor(
            aggregate_override={"tracking_active_legacy_work_count": 2}
        )
        evidence = collector.collect(
            {collector.DATABASE_URL_ENV: "hidden"},
            connector=lambda value: FakeConnection(cursor),
        )
        self.assertEqual(evidence["source_preflight_blocker_count"], 2)
        self.assertEqual(
            evidence["source_aggregates"][
                "tracking_active_legacy_work_count"
            ],
            2,
        )
        self.assertEqual(evidence["business_row_values_read"], 0)

    def test_migration_drift_is_sanitized_and_fails_gate(self):
        hashes = gate._current_migration_hashes()
        filenames = {
            path.name.split("_", 1)[0]: path.name
            for path in gate.MIGRATION_DIR.glob("*.sql")
        }
        rows = [
            (filenames[version], hashes[version])
            for version in collector.EXPECTED_APPLIED_VERSIONS[:-1]
        ]
        rows.append(("attacker-controlled-value", "not-a-hash"))
        evidence = collector.collect(
            {collector.DATABASE_URL_ENV: "hidden"},
            connector=lambda value: FakeConnection(FakeCursor(rows)),
        )
        self.assertGreater(evidence["stored_migration_drift_count"], 0)
        self.assertNotIn("attacker-controlled-value", json.dumps(evidence))

    def test_legacy_version_only_ledger_uses_explicit_pinned_trust(self):
        evidence = collector.collect(
            {collector.DATABASE_URL_ENV: "hidden"},
            connector=lambda value: FakeConnection(
                FakeCursor(migration_has_sha256=False)
            ),
        )
        self.assertEqual(
            evidence["migration_ledger_source"],
            "pinned_legacy_versions",
        )
        self.assertEqual(evidence["stored_migration_drift_count"], 0)
        self.assertEqual(
            evidence["pending_versions"],
            list(collector.EXPECTED_PENDING_VERSIONS),
        )

    def test_runtime_without_migration_select_returns_partial_fragment(self):
        evidence = collector.collect(
            {collector.DATABASE_URL_ENV: "hidden"},
            connector=lambda value: FakeConnection(
                FakeCursor(migration_selectable=False)
            ),
        )
        self.assertEqual(
            evidence["migration_ledger_source"],
            "external_required",
        )
        self.assertEqual(evidence["applied_migration_hashes"], {})
        self.assertEqual(evidence["pending_versions"], [])
        self.assertIsNone(evidence["stored_migration_drift_count"])
        self.assertTrue(evidence["source_preflight_complete"])
        with self.assertRaises(gate.PreflightEvidenceError):
            gate._verify_database(evidence)

    def test_missing_url_and_failures_emit_only_fixed_error_codes(self):
        with self.assertRaisesRegex(
            collector.CollectionError, "database_url_missing"
        ):
            collector.collect({})

        with mock.patch.object(
            collector,
            "collect",
            side_effect=collector.CollectionError(
                "database_connection_failed"
            ),
        ):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(collector.main(), 1)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(
            payload,
            {
                "status": "error",
                "error_code": "database_connection_failed",
            },
        )
        self.assertNotIn("postgres", stderr.getvalue())

    def test_query_failure_emits_only_fixed_stage_code(self):
        with mock.patch.object(
            collector,
            "collect",
            side_effect=collector.CollectionError(
                "database_query_failed",
                stage="source_aggregate:tracking_duplicate_url_count",
            ),
        ):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(collector.main(), 1)
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {
                "status": "error",
                "error_code": "database_query_failed",
                "error_stage": (
                    "source_aggregate:tracking_duplicate_url_count"
                ),
            },
        )
        self.assertNotIn("postgres", stderr.getvalue())

    def test_cleanup_failures_are_sanitized(self):
        connection = FakeConnection(rollback_error=True)
        with self.assertRaisesRegex(
            collector.CollectionError, "database_cleanup_failed"
        ):
            collector.collect(
                {collector.DATABASE_URL_ENV: "sensitive"},
                connector=lambda value: connection,
            )
        self.assertTrue(connection.closed)

    def test_all_database_statements_are_read_only(self):
        statements = [
            *collector.SOURCE_AGGREGATE_QUERIES.values(),
            collector.MIGRATION_SELECT_CAPABILITY_QUERY,
            collector.MIGRATION_SHA256_COLUMN_COUNT_QUERY,
            collector.MIGRATION_QUERY,
            collector.LEGACY_MIGRATION_QUERY,
            collector.ROLE_QUERY,
            collector.OWNER_COUNT_QUERY,
            collector.MEMBERSHIP_COUNT_QUERY,
            collector.DATABASE_CAPABILITY_COUNT_QUERY,
            collector.SCHEMA_CAPABILITY_COUNT_QUERY,
            collector.MIGRATION_PRIVILEGE_COUNT_QUERY,
            collector.GRANT_OPTION_COUNT_QUERY,
            collector.TABLE_PRIVILEGE_MISMATCH_COUNT_QUERY,
            collector.SEQUENCE_PRIVILEGE_MISMATCH_COUNT_QUERY,
            "BEGIN TRANSACTION READ ONLY",
            "SHOW default_transaction_read_only",
            "SHOW transaction_read_only",
        ]
        forbidden = re.compile(
            r"\b(?:INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|TRUNCATE|"
            r"GRANT|REVOKE|COPY|CALL|DO|VACUUM|ANALYZE|LOCK)\b",
            re.IGNORECASE,
        )
        for statement in statements:
            with self.subTest(statement=" ".join(statement.split())[:80]):
                self.assertIsNone(
                    re.search(r"(?<!%)%I", statement),
                    "psycopg would treat raw %I as an invalid placeholder",
                )
                without_literals = re.sub(
                    r"'(?:''|[^'])*'",
                    "''",
                    statement,
                )
                self.assertIsNone(forbidden.search(without_literals))
                command = statement.strip().split(None, 1)[0].upper()
                self.assertIn(command, {"SELECT", "WITH", "SHOW", "BEGIN"})

    def test_connect_forces_session_read_only_before_queries(self):
        fake_psycopg = mock.Mock()
        fake_psycopg.connect.return_value = object()
        with mock.patch.dict(
            os.environ, {"PYTHONPATH": ""}, clear=False
        ), mock.patch.dict(
            "sys.modules", {"psycopg": fake_psycopg}
        ):
            result = collector._connect("hidden-dsn")
        self.assertIs(result, fake_psycopg.connect.return_value)
        kwargs = fake_psycopg.connect.call_args.kwargs
        self.assertTrue(kwargs["autocommit"])
        self.assertEqual(kwargs["connect_timeout"], 10)
        self.assertIn("default_transaction_read_only=on", kwargs["options"])
        self.assertIn("statement_timeout=15000", kwargs["options"])


if __name__ == "__main__":
    unittest.main()
