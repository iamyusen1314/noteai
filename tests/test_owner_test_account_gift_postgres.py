"""Explicit local PG16 integration for the owner's one-time gift transaction."""
import json
import os
import subprocess
import unittest
from pathlib import Path

CONTAINER = "noteai-prep-owner-gift"
DOCKER = ["docker", "--context", "colima-noteai-prep"]
USER_ID = "7038b0ae-13c5-4cb0-a9ef-6a4d690ac1e2"
SQL = (Path(__file__).resolve().parents[1] / "scripts/postgres/owner-test-account-gift-20260907.sql").read_text()


def query(sql, database="noteai", success=True):
    result = subprocess.run(DOCKER + ["exec", "-i", CONTAINER, "psql", "-X", "-qAt",
                            "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", database],
                            input=sql, text=True, capture_output=True, timeout=45)
    if success and result.returncode:
        raise AssertionError(result.stderr)
    return result


@unittest.skipUnless(os.environ.get("NOTEAI_OWNER_GIFT_PG_TEST") == "1", "explicit isolated PG16 only")
class OwnerGiftPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        metadata = json.loads(subprocess.check_output(DOCKER + ["inspect", CONTAINER]))[0]
        assert metadata["HostConfig"]["NetworkMode"] == "none"
        assert not any(m.get("Type") == "bind" for m in metadata["Mounts"])
        query("CREATE ROLE noteai_admin; CREATE DATABASE noteai;", "postgres")
        query("""CREATE TABLE users(id text PRIMARY KEY,username text UNIQUE,
          deletion_requested_at text,phone text,phone_verified_at text);
        CREATE TABLE credits(user_id text PRIMARY KEY REFERENCES users(id),balance numeric NOT NULL,
          total_purchased numeric NOT NULL,total_used numeric NOT NULL,updated_at text);
        CREATE TABLE credit_transactions(id text PRIMARY KEY,user_id text REFERENCES users(id),
          type text,amount numeric,balance_after numeric,description text,paid_rmb numeric,
          package_id text,payment_ref text,recorded_at text);
        ALTER TABLE users OWNER TO noteai_admin; ALTER TABLE credits OWNER TO noteai_admin;
        ALTER TABLE credit_transactions OWNER TO noteai_admin;""")

    def setUp(self):
        query("ALTER TABLE credit_transactions DROP CONSTRAINT IF EXISTS test_ledger_fail;")
        query("TRUNCATE credit_transactions,credits,users;")
        query("INSERT INTO users(id,username) VALUES('" + USER_ID + "','noteai_19872819531');")

    def apply(self, user_id=USER_ID, success=True):
        return query(SQL.replace("@@USER_ID@@", user_id), success=success)

    def snapshot(self):
        return query("SELECT json_build_object('credits',(SELECT json_agg(c ORDER BY user_id) FROM credits c),"
                     "'ledger',(SELECT json_agg(t ORDER BY id) FROM credit_transactions t));").stdout.strip()

    def test_exact_gift_is_900_with_no_purchase_revenue(self):
        self.apply()
        state = json.loads(self.snapshot())
        self.assertEqual(state["credits"][0]["balance"], 900)
        self.assertEqual(state["credits"][0]["total_purchased"], 0)
        self.assertEqual((state["ledger"][0]["type"], state["ledger"][0]["paid_rmb"]), ("gift", 0))
        self.assertEqual(len(state["ledger"]), 1)

    def test_same_identity_cannot_issue_a_second_gift(self):
        self.apply()
        original = self.snapshot()
        self.apply()
        self.assertEqual(self.snapshot(), original)

    def test_wrong_uuid_or_username_has_no_credit_write(self):
        self.assertNotEqual(self.apply("b74e8187-2e1f-496f-bd90-1d28fafb3b82", False).returncode, 0)
        query("UPDATE users SET username='different-user';")
        self.assertNotEqual(self.apply(success=False).returncode, 0)
        self.assertEqual(json.loads(self.snapshot()), {"credits": None, "ledger": None})

    def test_deleted_account_is_rejected(self):
        query("UPDATE users SET deletion_requested_at='2026-09-07T00:00:00+00:00';")
        self.assertNotEqual(self.apply(success=False).returncode, 0)
        self.assertEqual(json.loads(self.snapshot()), {"credits": None, "ledger": None})

    def test_nonzero_existing_balance_is_not_silently_topped_up(self):
        query("INSERT INTO credits VALUES('" + USER_ID + "',1,0,0,'original');")
        original = self.snapshot()
        self.assertNotEqual(self.apply(success=False).returncode, 0)
        self.assertEqual(self.snapshot(), original)

    def test_ledger_failure_rolls_back_initialization_and_balance(self):
        query("ALTER TABLE credit_transactions ADD CONSTRAINT test_ledger_fail CHECK(amount<900);")
        self.assertNotEqual(self.apply(success=False).returncode, 0)
        self.assertEqual(json.loads(self.snapshot()), {"credits": None, "ledger": None})

    def test_existing_conflicting_gift_is_not_accepted_or_rewritten(self):
        self.apply()
        query("UPDATE credit_transactions SET paid_rmb=1;")
        original = self.snapshot()
        self.assertNotEqual(self.apply(success=False).returncode, 0)
        self.assertEqual(self.snapshot(), original)


if __name__ == "__main__":
    unittest.main()
