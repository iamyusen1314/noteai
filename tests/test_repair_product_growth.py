from contextlib import closing, contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("repair_product_growth", ROOT / "tools/repair_product_growth.py")
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
growth_spec = importlib.util.spec_from_file_location("growth_history", ROOT / "model/growth_history.py")
growth = importlib.util.module_from_spec(growth_spec)
growth_spec.loader.exec_module(growth)
CLOCK = "2026-09-19T01:00:00+00:00"


class Transaction:
    def __init__(self, conn, postgres=False):
        self.conn = conn
        self.postgres = postgres
    def execute(self, *args):
        return self.conn.execute(*args)
    def fetchone(self, *args):
        return self.execute(*args).fetchone()
    def fetchall(self, *args):
        return self.execute(*args).fetchall()


class GrowthRepairCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "synthetic.sqlite"
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY,deletion_requested_at TEXT);
            CREATE TABLE notes(id TEXT PRIMARY KEY,user_id TEXT,domain TEXT,score REAL,grade TEXT,source TEXT,parent_id TEXT,version INTEGER,created_at TEXT);
            CREATE TABLE saved_diagnoses(id TEXT PRIMARY KEY,user_id TEXT,domain TEXT,ces_percentile REAL,grade TEXT,diagnosis_json TEXT,created_at TEXT);
            CREATE TABLE chat_sessions(id TEXT PRIMARY KEY,user_id TEXT,note_id TEXT,generate_ctx_json TEXT);
            CREATE TABLE idempotency_requests(id TEXT PRIMARY KEY,user_id TEXT,operation TEXT,status TEXT,complete_applied INTEGER,refund_applied INTEGER);
            CREATE TABLE growth_records(id TEXT PRIMARY KEY,user_id TEXT,note_id TEXT,score REAL,grade TEXT,domain TEXT,action TEXT,recorded_at TEXT);
            CREATE TABLE user_memories(id TEXT PRIMARY KEY,user_id TEXT,memory_type TEXT,content TEXT,source_note_id TEXT,created_at TEXT,updated_at TEXT);
            INSERT INTO users VALUES('user-a',NULL),('user-b',NULL),('deleted','2026-09-18T00:00:00+00:00');
            INSERT INTO notes VALUES('note-a','user-a','美食',72,'良好','generate',NULL,1,'2026-09-15T00:00:00+00:00');
            INSERT INTO notes VALUES('note-b','user-b','旅行',65,'良好','manual',NULL,1,'2026-09-16T00:00:00+00:00');
            INSERT INTO notes VALUES('note-deleted','deleted','旅行',65,'良好','manual',NULL,1,'2026-09-16T00:00:00+00:00');
            INSERT INTO saved_diagnoses VALUES('private-diagnosis','user-a','美食',55,'良好','{"ai_diagnosis":"PRIVATE_BODY_MUST_NOT_EXPORT"}','2026-09-14T00:00:00+00:00');
            """)
        def get_conn():
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            return conn
        self.db = SimpleNamespace(using_postgres=lambda: False, _DB_PATH=self.path, get_conn=get_conn, Transaction=Transaction)
        self.transaction = lambda **kwargs: repair.database_transaction(self.db, **kwargs)
        self.fence = mock.patch.object(growth, "_write_fence").start()
        self.memory = mock.patch.object(growth, "_achievements", return_value=[]).start()
        self.visible = mock.patch.object(growth, "_visible", return_value=True).start()
        self.addCleanup(mock.patch.stopall)
        self.counter = 0

    def run_tool(self, **kwargs):
        self.counter += 1
        path = self.root / f"report-{self.counter}.jsonl"
        report = repair.PrivateReport(path)
        try:
            result = repair.run_repair(transaction=self.transaction, growth=growth, report=report,
                                      now=lambda: CLOCK, **kwargs)
            self.assertEqual(report.hash.hexdigest(), hashlib.sha256(path.read_bytes()).hexdigest())
        finally:
            report.close()
        return result, [json.loads(line) for line in path.read_text().splitlines()], path

    def count(self, user_id):
        with self.transaction(write=False) as tx:
            return tx.fetchone("SELECT count(*) n FROM growth_records WHERE user_id=?", (user_id,))["n"]

    def test_default_preview_is_database_readonly_and_no_repair(self):
        result, records, path = self.run_tool(user_ids=["user-a"])
        self.assertEqual(result["state"], "DRY_RUN_COMPLETE")
        self.assertEqual((result["inserted_records"], self.count("user-a")), (0, 0))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("PRIVATE_BODY_MUST_NOT_EXPORT", path.read_text())
        self.assertEqual(records[1]["sources"]["diagnoses"]["ids"], ["private-diagnosis"])
        self.memory.assert_not_called()
        with self.transaction(write=False) as tx:
            with self.assertRaises(sqlite3.OperationalError):
                tx.execute("INSERT INTO growth_records(id) VALUES('forbidden')")

    def test_apply_scopes_exact_user_and_is_idempotent(self):
        first, _, _ = self.run_tool(user_ids=["user-a"], apply=True)
        second, _, _ = self.run_tool(user_ids=["user-a"], apply=True)
        self.assertEqual(first["inserted_records"], 2)
        self.assertEqual(second["inserted_records"], 0)
        self.assertEqual((self.count("user-a"), self.count("user-b")), (2, 0))

    def test_all_eligible_uses_distinct_user_transactions_and_excludes_deletion(self):
        seen = []
        self.fence.side_effect = lambda _, user: seen.append(user)
        result, _, _ = self.run_tool(all_eligible=True, apply=True)
        self.assertEqual(result["users_selected"], 2)
        self.assertEqual(set(seen), {"user-a", "user-b"})
        self.assertEqual(self.count("deleted"), 0)

    def test_user_failure_rolls_back_only_that_user_and_never_retries(self):
        self.memory.side_effect = lambda _, user, *a, **k: (_ for _ in ()).throw(RuntimeError("SECRET_DSN")) if user == "user-a" else []
        result, records, path = self.run_tool(all_eligible=True, apply=True)
        self.assertEqual(result["state"], "PARTIAL_UNKNOWN_READBACK_ONLY")
        self.assertEqual((self.count("user-a"), self.count("user-b")), (0, 1))
        self.assertEqual(result["users_unknown"], 1)
        self.assertEqual(sum(r["event"] == "user_unconfirmed" for r in records), 1)
        self.assertNotIn("SECRET_DSN", path.read_text())

    def test_commit_uncertainty_retains_before_record_without_replay(self):
        actual = self.transaction
        commits = []
        @contextmanager
        def uncertain(*, write=False):
            with actual(write=write) as tx:
                yield tx
            if write:
                commits.append(True)
                raise OSError("synthetic uncertain reply")
        self.transaction = uncertain
        result, records, _ = self.run_tool(user_ids=["user-a"], apply=True)
        self.assertEqual(len(commits), 1)
        self.assertEqual(result["users_unknown"], 1)
        failure = next(r for r in records if r["event"] == "user_unconfirmed")
        self.assertEqual(failure["phase"], "commit")
        self.assertTrue(any(r["event"] == "snapshot_before" for r in records))
        self.assertEqual(self.count("user-a"), 2)

    def test_original_source_mutation_detected_and_transaction_rolled_back(self):
        original = growth.repair_growth_history_with_storage
        def bad(storage, user, **kwargs):
            result = original(storage, user, **kwargs)
            storage.execute("UPDATE notes SET score=99 WHERE user_id=?", (user,))
            return result
        with mock.patch.object(growth, "repair_growth_history_with_storage", side_effect=bad):
            result, _, _ = self.run_tool(user_ids=["user-a"], apply=True)
        self.assertEqual(result["users_unknown"], 1)
        self.assertEqual(self.count("user-a"), 0)
        with self.transaction(write=False) as tx:
            self.assertEqual(tx.fetchone("SELECT score FROM notes WHERE id='note-a'")["score"], 72)

    def test_snapshot_hash_changes_with_original_json_but_never_exports_content(self):
        _, before, _ = self.run_tool(user_ids=["user-a"])
        with self.transaction(write=True) as tx:
            tx.execute("UPDATE saved_diagnoses SET diagnosis_json=?", ('{"ai_diagnosis":"OTHER_PRIVATE_BODY"}',))
        _, after, path = self.run_tool(user_ids=["user-a"])
        self.assertNotEqual(before[1]["source_digest"], after[1]["source_digest"])
        self.assertNotIn("OTHER_PRIVATE_BODY", path.read_text())

    def test_report_is_exclusive_and_symlink_not_followed(self):
        path = self.root / "once.jsonl"
        report = repair.PrivateReport(path)
        report.close()
        with self.assertRaises(FileExistsError):
            repair.PrivateReport(path)
        link = self.root / "linked.jsonl"
        link.symlink_to(path)
        with self.assertRaises(FileExistsError):
            repair.PrivateReport(link)

    def test_stdout_summary_has_no_user_or_source_identities(self):
        result, _, _ = self.run_tool(user_ids=["user-a"])
        encoded = json.dumps(result)
        for value in ("user-a", "note-a", "private-diagnosis", "PRIVATE_BODY"):
            self.assertNotIn(value, encoded)

    def test_no_implicit_all_user_scope(self):
        with self.assertRaisesRegex(ValueError, "exactly_one_user_scope"):
            self.run_tool()
        with self.assertRaisesRegex(ValueError, "exactly_one_user_scope"):
            self.run_tool(user_ids=["user-a"], all_eligible=True)

    def test_postgres_preview_requires_server_readonly_and_always_rolls_back(self):
        for observed in ("on", "off"):
            with self.subTest(observed=observed):
                conn = mock.Mock()
                conn.execute.return_value.fetchone.return_value = {"transaction_read_only": observed}
                module = SimpleNamespace(using_postgres=lambda: True, get_conn=lambda: conn, Transaction=Transaction)
                if observed == "on":
                    with repair.database_transaction(module) as tx:
                        self.assertIs(tx.conn, conn)
                else:
                    with self.assertRaisesRegex(ValueError, "database_readonly_not_enforced"):
                        with repair.database_transaction(module):
                            self.fail("unsafe transaction was yielded")
                self.assertEqual(conn.execute.call_args_list[0].args, ("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",))
                conn.commit.assert_not_called()
                conn.rollback.assert_called_once()
                conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
