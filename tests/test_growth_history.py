import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("growth_history", ROOT / "model/growth_history.py")
growth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(growth)
ORIGINAL = "2026-09-15T04:43:44+00:00"
REPAIRED = "2026-09-19T01:00:00+00:00"


class Storage:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE notes(id TEXT PRIMARY KEY,user_id TEXT,domain TEXT,score REAL,grade TEXT,source TEXT,parent_id TEXT,version INTEGER,created_at TEXT);
        CREATE TABLE saved_diagnoses(id TEXT PRIMARY KEY,user_id TEXT,domain TEXT,ces_percentile REAL,grade TEXT,diagnosis_json TEXT,created_at TEXT);
        CREATE TABLE chat_sessions(id TEXT PRIMARY KEY,user_id TEXT,note_id TEXT,generate_ctx_json TEXT);
        CREATE TABLE idempotency_requests(id TEXT PRIMARY KEY,user_id TEXT,operation TEXT,status TEXT,complete_applied INTEGER,refund_applied INTEGER);
        CREATE TABLE growth_records(id TEXT PRIMARY KEY,user_id TEXT,note_id TEXT,score REAL,grade TEXT,domain TEXT,action TEXT,recorded_at TEXT);
        """)
    def execute(self, *args):
        return self.connection.execute(*args)
    def fetchall(self, *args):
        return self.execute(*args).fetchall()
    def fetchone(self, *args):
        return self.execute(*args).fetchone()


class GrowthHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = Storage()
        self.addCleanup(self.db.connection.close)
        self.visible = lambda *_: True
        self.fence = mock.patch.object(growth, "_write_fence").start()
        self.achievements = mock.patch.object(growth, "_achievements", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)

    def note(self, identity="note-a", *, owner="u", score=72, source="generate", parent=None, version=1):
        self.db.execute("INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?)",
                        (identity, owner, "美食", score, "良好", source, parent, version, ORIGINAL))
        return identity

    def generation(self, *, status="completed", score=72, complete=1, refund=0, saved_id="note-a"):
        self.note(score=score)
        result = {"saved_note_id": saved_id, "ces_percentile": score, "note_body": "PRIVATE_BODY_NOT_OUTPUT"}
        context = {"task_continuation": {"operation": "generate", "status": "completed", "result": result}}
        self.db.execute("INSERT INTO chat_sessions VALUES(?,?,?,?)", ("task-a", "u", "note-a", json.dumps(context)))
        self.db.execute("INSERT INTO idempotency_requests VALUES(?,?,?,?,?,?)", ("task-a", "u", "generate", status, complete, refund))

    def diagnosis(self, identity="diag-a", *, note_id=None, score=72, extra=None):
        data = {"report_quality_status": "checked", "report_quality_issues": [], **(extra or {})}
        if note_id is not None:
            data["saved_note_id"] = note_id
        self.db.execute("INSERT INTO saved_diagnoses VALUES(?,?,?,?,?,?,?)", (identity, "u", "美食", score, "良好", json.dumps(data), ORIGINAL))

    def project(self):
        return growth.project_growth_history(self.db, "u", is_visible=self.visible)

    def repair(self):
        return growth.repair_growth_history_with_storage(self.db, "u", repaired_at=REPAIRED, is_visible=self.visible)

    def test_completed_generation_is_readable_without_silent_repair(self):
        self.generation()
        before = self.db.connection.total_changes
        first, second = self.project(), self.project()
        self.assertEqual(first, second)
        self.assertEqual(self.db.connection.total_changes, before)
        record = first["records"][0]
        self.assertEqual((record["source_type"], record["source_id"], record["note_id"]), ("generation", "task-a", "note-a"))
        self.assertFalse(record["persisted"])
        self.assertEqual(record["record_origin"], "recoverable")
        self.assertNotIn("PRIVATE_BODY_NOT_OUTPUT", json.dumps(first))
        self.achievements.assert_not_called()

    def test_waiting_unknown_failed_or_refunded_task_cannot_fallback_to_note(self):
        for status, complete, refund in [("waiting_for_input", 0, 0), ("outcome_unknown", 0, 0), ("failed", 0, 1), ("completed", 1, 1)]:
            with self.subTest(status=status):
                self.db.execute("DELETE FROM notes")
                self.db.execute("DELETE FROM chat_sessions")
                self.db.execute("DELETE FROM idempotency_requests")
                self.generation(status=status, complete=complete, refund=refund)
                self.assertEqual(self.project()["records"], [])

    def test_generation_exact_result_binding_required(self):
        self.generation(saved_id="different")
        self.assertEqual(self.project()["records"], [])

    def test_unbound_saved_diagnosis_remains_independent_event(self):
        self.diagnosis()
        record = self.project()["records"][0]
        self.assertEqual(record["source_type"], "diagnosis")
        self.assertIsNone(record["note_id"])
        self.assertEqual(self.repair()["inserted_count"], 1)

    def test_foreign_or_expired_note_binding_is_not_relabelled_as_unbound(self):
        self.note(owner="other", source="diagnose")
        self.diagnosis(note_id="note-a")
        self.assertEqual(self.project()["records"], [])
        self.db.execute("UPDATE notes SET user_id='u'")
        self.visible = lambda kind, *_: kind != "note"
        self.assertEqual(self.project()["records"], [])

    def test_unconfirmed_diagnosis_does_not_become_growth(self):
        self.note(source="diagnose")
        self.diagnosis(note_id="note-a", extra={"report_quality_status": "needs_confirmation"})
        self.assertEqual(self.project()["records"], [])

    def test_optimization_has_actual_version_not_invented_starting_zero(self):
        self.note("parent", score=68)
        self.note("child", source="chat", parent="parent", version=2, score=72)
        records = self.project()["records"]
        child = next(r for r in records if r["note_id"] == "child")
        self.assertEqual(child["source_type"], "optimization")
        self.assertEqual([r["score"] for r in records], [72, 68])
        self.assertFalse(any("delta" in r or "baseline_score" in r for r in records))

    def test_optimization_missing_or_foreign_parent_not_guessed(self):
        self.note("child", source="chat", parent="absent", version=2)
        self.assertEqual(self.project()["records"], [])

    def test_existing_legacy_note_record_is_not_duplicated_or_rewritten(self):
        self.generation()
        self.db.execute("INSERT INTO growth_records VALUES(?,?,?,?,?,?,?,?)", ("legacy-random", "u", "note-a", 72, "良好", "美食", "generate", ORIGINAL))
        self.assertEqual(len(self.project()["records"]), 1)
        self.assertEqual(self.repair()["inserted_count"], 0)
        self.assertEqual(self.db.fetchone("SELECT id FROM growth_records")["id"], "legacy-random")
        self.achievements.assert_called_once()

    def test_explicit_repair_preserves_both_times_and_is_idempotent(self):
        self.generation()
        self.assertEqual(self.repair()["inserted_count"], 1)
        self.assertEqual(self.repair()["inserted_count"], 0)
        stored = self.db.fetchone("SELECT * FROM growth_records")
        self.assertEqual(stored["recorded_at"], REPAIRED)
        self.assertEqual(stored["id"], "recovered:generation:task-a")
        record = self.project()["records"][0]
        self.assertEqual(record["recorded_at"], ORIGINAL)
        self.assertEqual(record["recovered_at"], REPAIRED)
        self.assertEqual(record["source_recorded_at"], ORIGINAL)
        self.assertTrue(record["persisted"])

    def test_zero_score_is_preserved_in_stats(self):
        self.generation(score=0)
        stats = self.project()["stats"]
        self.assertEqual((stats["latest_score"], stats["best_score"], stats["avg_score"]), (0, 0, 0))

    def test_score_validation_rejects_nonfinite_bool_and_outside_range(self):
        for score in (True, float("inf"), float("nan"), -1, 101, "72"):
            with self.subTest(score=score), self.assertRaises(ValueError):
                growth.record_saved_note_with_storage(self.db, user_id="u", note_id=None, domain="美食", score=score, grade="", action="diagnose")

    def test_completion_hook_uses_note_binding_and_deduplicates(self):
        self.note()
        args = dict(user_id="u", note_id="note-a", domain="美食", score=72, grade="良好", action="generate", recorded_at=ORIGINAL)
        growth.record_saved_note_with_storage(self.db, **args)
        growth.record_saved_note_with_storage(self.db, **args)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM growth_records")["n"], 1)
        with self.assertRaises(ValueError):
            growth.record_saved_note_with_storage(self.db, **{**args, "user_id": "other"})

    def test_caller_transaction_rolls_back_growth_when_achievement_fails(self):
        self.generation()
        self.db.connection.commit()
        self.achievements.side_effect = RuntimeError("synthetic failure")
        with self.assertRaises(RuntimeError), self.db.connection:
            self.repair()
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM growth_records")["n"], 0)

    def test_performance_record_retains_separate_kind_and_id(self):
        self.db.execute("INSERT INTO growth_records VALUES(?,?,?,?,?,?,?,?)", ("tracking-deterministic", "u", None, 61, "良好", "美食", "url_crawl_7d", ORIGINAL))
        record = self.project()["records"][0]
        self.assertEqual((record["id"], record["score_kind"]), ("tracking-deterministic", "performance"))
        self.assertEqual(self.repair()["inserted_count"], 0)
        self.achievements.assert_not_called()

    def test_performance_does_not_change_prediction_score_stats(self):
        self.generation(score=72)
        self.db.execute("INSERT INTO growth_records VALUES(?,?,?,?,?,?,?,?)", ("tracking", "u", None, 95, "优秀", "美食", "url_track", REPAIRED))
        projected = self.project()
        stats = projected["stats"]
        self.assertEqual((stats["latest_score"], stats["best_score"], stats["avg_score"]), (72, 72, 72))
        self.assertEqual((stats["total_sessions"], stats["prediction_sessions"], stats["performance_sessions"]), (2, 1, 1))
        self.assertEqual(projected["performance_records"][0]["score"], 95)

    def test_existing_score_conflict_is_not_silently_overwritten(self):
        self.generation()
        self.db.execute("INSERT INTO growth_records VALUES(?,?,?,?,?,?,?,?)", ("legacy", "u", "note-a", 60, "良好", "美食", "generate", ORIGINAL))
        with self.assertRaisesRegex(ValueError, "growth_existing_source_conflict"):
            self.repair()
        self.assertEqual(self.db.fetchone("SELECT score FROM growth_records")["score"], 60)
        self.achievements.assert_not_called()

    def test_duplicate_reports_for_same_saved_version_are_not_new_versions(self):
        self.note(source="diagnose")
        self.diagnosis("diag-a", note_id="note-a")
        self.diagnosis("diag-b", note_id="note-a")
        self.assertEqual(len(self.project()["records"]), 1)
        self.assertEqual(self.repair()["inserted_count"], 1)

    def test_malformed_legacy_identity_and_result_are_skipped(self):
        self.diagnosis(extra={"saved_note_id": {"invalid": "shape"}})
        self.assertEqual(self.project()["records"], [])
        self.db.execute("UPDATE saved_diagnoses SET diagnosis_json='[]'")
        self.assertEqual(self.project()["records"][0]["source_type"], "diagnosis")

    def test_repair_before_source_rejects_without_writes(self):
        self.generation()
        with self.assertRaisesRegex(ValueError, "growth_repair_before_source"):
            growth.repair_growth_history_with_storage(self.db, "u", repaired_at="2026-09-14T00:00:00+00:00", is_visible=self.visible)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM growth_records")["n"], 0)


if __name__ == "__main__":
    unittest.main()
