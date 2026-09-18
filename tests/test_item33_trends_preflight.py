"""Opt-in disposable PostgreSQL tests; never select a DSN from the environment."""
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest

import psycopg

from tools.item33_trends_preflight import Item33PreflightError, read_database_facts

ROOT = Path(__file__).resolve().parents[1]
CONNECT = dict(host="/var/run/postgresql", dbname="noteai_item33_preflight_local", user="postgres")


@unittest.skipUnless(os.environ.get("NOTEAI_LOCAL_PG16_ITEM33_PREFLIGHT_TEST") == "1",
                     "explicit disposable network-none PG16 socket required")
class Item33PreflightPostgresTests(unittest.TestCase):
    def setUp(self):
        self.owner = psycopg.connect(**CONNECT, autocommit=True)
        version, address, database = self.owner.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr(),current_database()"
        ).fetchone()
        self.assertTrue(160000 <= version < 170000)
        self.assertIsNone(address)
        self.assertEqual(database, CONNECT["dbname"])
        self.owner.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        self.owner.execute("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='noteai_xhs_trends') "
            "THEN CREATE ROLE noteai_xhs_trends LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS; END IF; END $$")
        for name in ("0003_market_timing.sql", "0004_xhs_freshness.sql", "0011_trends_execution_contract.sql"):
            self.owner.execute((ROOT / "model/migrations/postgres" / name).read_text())
        policy = (ROOT / "scripts/postgres/noteai_production_runtime_roles.sql").read_text()
        trends = policy.split("-- NOTEAI-RUNTIME-ACL-STAGE: trends\n", 1)[1].split(
            "GRANT SELECT(id, status, completed_at)", 1)[0]
        self.owner.execute("GRANT USAGE ON SCHEMA public TO noteai_xhs_trends")
        self.owner.execute(trends)
        self.writer = psycopg.connect(**(CONNECT | {"user": "noteai_xhs_trends"}), autocommit=True)
        self.addCleanup(self.writer.close)
        self.addCleanup(self.owner.close)

    def collect(self):
        return read_database_facts(self.writer, now=datetime.now(timezone.utc))

    def test_real_role_acl_and_ledger_are_readonly_and_not_capture_proof(self):
        result = self.collect()
        self.assertTrue(result["server_enforced_read_only"])
        self.assertTrue(result["transaction_rolled_back"])
        self.assertTrue(result["role_exact"])
        self.assertTrue(result["acl_exact"])
        self.assertFalse(result["capture_coverage_verified"])
        self.assertFalse(result["business_ddl_count_verified"])
        self.assertEqual(result["production_database_writes"], 0)
        self.assertEqual(result["utc_provider_budget_remaining_before"], 34)
        self.assertEqual(self.writer.info.transaction_status, 0)
        self.assertTrue(result["triggers"])
        self.assertFalse(any("definition" in key for row in result["triggers"] for key in row))

    def test_existing_transaction_is_left_with_its_owner(self):
        self.writer.execute("BEGIN READ ONLY")
        with self.assertRaisesRegex(Item33PreflightError, "connection_not_idle_autocommit"):
            self.collect()
        self.assertNotEqual(self.writer.info.transaction_status, 0)
        self.writer.rollback()

    def test_extra_delete_acl_rejects_without_database_error_leak(self):
        self.owner.execute("GRANT DELETE ON hot_keywords TO noteai_xhs_trends")
        with self.assertRaisesRegex(Item33PreflightError, "acl_contract"):
            self.collect()
        self.assertEqual(self.writer.info.transaction_status, 0)

    def test_missing_update_column_rejects(self):
        self.owner.execute("REVOKE UPDATE(quality_score) ON hot_keywords FROM noteai_xhs_trends")
        with self.assertRaises(Item33PreflightError):
            self.collect()

    def test_column_only_write_to_other_schema_rejects(self):
        self.owner.execute("CREATE SCHEMA item33_extra; CREATE TABLE item33_extra.extra(id int);")
        self.addCleanup(lambda: self.owner.execute("DROP SCHEMA item33_extra CASCADE"))
        self.owner.execute("GRANT USAGE ON SCHEMA item33_extra TO noteai_xhs_trends; "
                           "GRANT INSERT(id) ON item33_extra.extra TO noteai_xhs_trends")
        with self.assertRaisesRegex(Item33PreflightError, "outside_acl"):
            self.collect()

    def test_role_ownership_or_inherit_is_not_accepted(self):
        self.owner.execute("ALTER ROLE noteai_xhs_trends INHERIT")
        self.addCleanup(lambda: self.owner.execute("ALTER ROLE noteai_xhs_trends NOINHERIT"))
        with self.assertRaisesRegex(Item33PreflightError, "role_contract"):
            self.collect()

    def test_used_bucket_cannot_be_claimed_fresh(self):
        self.owner.execute("""INSERT INTO xhs_trends_runs
            (id,bucket_key,status,lease_token_hash,lease_fence,lease_expires_at,started_at)
            VALUES ('synthetic-run',to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD'),
                    'running',%s,1,CURRENT_TIMESTAMP+interval '30 minutes',CURRENT_TIMESTAMP)""", ("a" * 64,))
        with self.assertRaisesRegex(Item33PreflightError, "ledger_not_fresh"):
            self.collect()

    def test_wrong_session_is_rejected_before_application_reads(self):
        with self.assertRaisesRegex(Item33PreflightError, "role_or_readonly"):
            read_database_facts(self.owner, now=datetime.now(timezone.utc))
        self.assertEqual(self.owner.info.transaction_status, 0)


if __name__ == "__main__":
    unittest.main()
