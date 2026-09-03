import asyncio
import importlib
import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NOTEAI_FACT_SEARCH", "0")

api = importlib.import_module("api")


class _FakeDB:
    def __init__(self, *, fail_note_save=False, note_version=1):
        self.fail_note_save = fail_note_save
        self.note_version = note_version
        self.executed = []

    def fetchone(self, sql, params=()):
        if "FROM chat_sessions" in sql and params == ("historic",):
            return {
                "id": "historic",
                "user_id": "u1",
                "note_id": "note-root",
                "domain": "美食",
                "local_time": "2026071112",
                "messages_json": "[]",
                "user_prefs_json": "{}",
                "iteration_count": 4,
                "current_score": 75.3,
                "generate_ctx_json": "{}",
            }
        if "FROM notes" in sql and params == ("note-root", "u1"):
            return {
                "id": "note-root",
                "title": "旧标题",
                "body": "旧正文有20分钟、吃不出柴感，半小时就能完成。",
                "domain": "美食",
                "score": 75.3,
                "grade": "优秀",
                "version": self.note_version,
                "parent_id": None,
            }
        return None

    def execute(self, sql, params=()):
        if self.fail_note_save and sql.startswith("INSERT INTO notes"):
            raise RuntimeError("simulated note save failure")
        self.executed.append((sql, params))


class ChatDeliveryConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.original_db = api._db
        self.original_sessions = dict(api._chat_sessions)
        self.original_stream_chat = api._mr.stream_chat
        self.original_repair = api._repair_chat_note_if_needed
        self.original_shape = api._shape_body_for_delivery
        self.original_sanitize = api._sanitize_title_for_delivery
        self.original_score = api._score_chat_note
        self.original_achievements = api._memory.check_and_record_achievements
        self.original_add_context = api._memory.add_context
        api._memory.check_and_record_achievements = lambda *_args, **_kwargs: []
        api._memory.add_context = lambda *_args, **_kwargs: None

    def tearDown(self):
        api._db = self.original_db
        api._chat_sessions.clear()
        api._chat_sessions.update(self.original_sessions)
        api._mr.stream_chat = self.original_stream_chat
        api._repair_chat_note_if_needed = self.original_repair
        api._shape_body_for_delivery = self.original_shape
        api._sanitize_title_for_delivery = self.original_sanitize
        api._score_chat_note = self.original_score
        api._memory.check_and_record_achievements = self.original_achievements
        api._memory.add_context = self.original_add_context

    def _install_session(self):
        api._chat_sessions.clear()
        api._chat_sessions["s1"] = {
            "note_title": "旧标题",
            "note_body": "旧正文有20分钟、吃不出柴感，半小时就能完成。",
            "domain": "美食",
            "local_time": "2026071112",
            "user_id": "u1",
            "current_score": 75.3,
            "messages": [],
            "iteration_count": 0,
            "note_id": "note-root",
            "_last_note_id": "note-root",
            "note_version": 1,
            "user_constraints": [],
            "generate_context": {},
        }

    @staticmethod
    def _events():
        async def collect():
            output = []
            async for chunk in api._chat_sse_generator(
                "s1", "请删掉20分钟、吃不出柴感和半小时，不要保留这些未经提供的说法"
            ):
                if chunk.startswith("data: "):
                    output.append(json.loads(chunk.removeprefix("data: ").strip()))
            return output

        return asyncio.run(collect())

    def test_turn_contract_filters_removed_old_claims_from_fact_source(self):
        contract = api._build_chat_turn_constraint_contract(
            "请删掉20分钟、吃不出柴感和半小时，不要保留这些未经提供的说法",
            "旧正文有20分钟、吃不出柴感，半小时就能完成。",
        )

        filtered = api._chat_fact_source_for_turn(
            {"fact_context": "", "note_body": "旧正文有20分钟、吃不出柴感，半小时就能完成。"},
            contract,
        )

        self.assertCountEqual(contract["forbidden_terms"], ["20分钟", "吃不出柴感", "半小时"])
        self.assertNotIn("20分钟", filtered)
        self.assertNotIn("吃不出柴感", filtered)
        self.assertNotIn("半小时", filtered)

        reversed_contract = api._build_chat_turn_constraint_contract(
            "请把吃不出柴感删掉，但保留其他真实描述",
            "旧正文有20分钟、吃不出柴感，半小时就能完成。",
        )
        self.assertEqual(reversed_contract["forbidden_terms"], ["吃不出柴感"])
        keep_contract = api._build_chat_turn_constraint_contract(
            "不要太广告，保留20分钟这个真实信息",
            "旧正文有20分钟、吃不出柴感，半小时就能完成。",
        )
        self.assertEqual(keep_contract["forbidden_terms"], [])

    def test_general_duration_removal_preserves_only_explicitly_confirmed_existing_term(self):
        source = "已确认训练总时长30分钟；旧稿还写了未经确认的20分钟和半小时。"
        contract = api._build_chat_turn_constraint_contract(
            "删除未经提供的具体时长，但保留30分钟这个已确认事实",
            source,
        )

        self.assertTrue(contract["remove_duration_claims"])
        self.assertEqual(contract["protected_terms"], ["30分钟"])
        filtered = api._chat_filter_source_for_turn_contract(source, contract)
        self.assertIn("30分钟", filtered)
        self.assertNotIn("20分钟", filtered)
        self.assertNotIn("半小时", filtered)
        self.assertFalse(api._chat_turn_constraint_violations("标题", "训练总时长30分钟。", contract))
        self.assertTrue(api._chat_turn_constraint_violations("标题", "训练20分钟，半小时完成。", contract))

    def test_bound_note_version_is_authoritative_for_start_and_failure_fallback(self):
        fake_db = _FakeDB(fail_note_save=True, note_version=5)
        api._db = fake_db

        response = asyncio.run(api.chat_start(
            api.ChatStartInput(
                note_title="旧标题",
                note_body="旧正文有20分钟、吃不出柴感，半小时就能完成。",
                note_id="note-root",
                domain="美食",
                generate_context={"current_score": 75.3},
            ),
            user={"id": "u1"},
        ))
        session = api._chat_sessions[response.session_id]
        self.assertEqual(session["note_version"], 5)

        restored = api._load_chat_session_from_db("historic")
        self.assertIsNotNone(restored)
        self.assertEqual(restored["note_version"], 5)

        # Historical sessions may predate note_version persistence; the
        # terminal fallback must still resolve the bound note's DB version.
        session.pop("note_version")
        api._chat_sessions["s1"] = session

        async def fake_stream_chat(**_kwargs):
            yield "content", "已完成。<note><title>新标题</title><body>只保留真实菜品体验。</body></note>"

        async def clean_shape(title, body, domain, fact_source, route):
            return body

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], False

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = clean_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertEqual(canonical["status"], "save_failed")
        self.assertEqual(canonical["saved_note_version"], 5)
        self.assertEqual(api._chat_sessions["s1"].get("note_version"), 5)

    def test_final_constraint_failure_keeps_previous_version_and_never_claims_save(self):
        fake_db = _FakeDB()
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已全部删除。<note><title>新标题</title><body>干净草稿。</body></note>"

        async def reintroducing_shape(*_args, **_kwargs):
            return "后处理又写回20分钟、吃不出柴感和半小时。"

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], True

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = reintroducing_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()

        self.assertFalse(any(ev.get("type") == "note_update" for ev in events))
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertFalse(canonical["saved"])
        self.assertEqual(canonical["status"], "constraint_failed")
        self.assertEqual(canonical["title"], "旧标题")
        self.assertEqual(canonical["body"], "旧正文有20分钟、吃不出柴感，半小时就能完成。")
        self.assertFalse(any(sql.startswith("INSERT INTO notes") for sql, _ in fake_db.executed))
        self.assertEqual(api._chat_sessions["s1"]["note_body"], canonical["body"])
        self.assertEqual(api._chat_sessions["s1"]["note_version"], 1)

    def test_saved_canonical_response_note_update_session_and_insert_are_identical(self):
        fake_db = _FakeDB()
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已删除旧说法。<note><title>新标题</title><body>只保留真实菜品体验。</body></note>"

        async def clean_shape(title, body, domain, fact_source, route):
            self.assertNotIn("20分钟", fact_source)
            self.assertNotIn("吃不出柴感", fact_source)
            self.assertNotIn("半小时", fact_source)
            return body

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], False

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = clean_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()

        note_update = next(ev for ev in events if ev.get("type") == "note_update")
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        inserted = next(params for sql, params in fake_db.executed if sql.startswith("INSERT INTO notes"))
        session = api._chat_sessions["s1"]

        self.assertTrue(canonical["saved"])
        self.assertEqual(canonical["status"], "saved")
        for field in ("title", "body", "score", "grade", "saved_note_id", "saved_note_version"):
            self.assertEqual(canonical[field], note_update[field])
        self.assertEqual((inserted[2], inserted[3], inserted[5], inserted[6], inserted[9]), (
            canonical["title"], canonical["body"], canonical["score"], canonical["grade"], canonical["saved_note_version"],
        ))
        self.assertEqual((session["note_title"], session["note_body"], session["current_score"], session["note_version"]), (
            canonical["title"], canonical["body"], canonical["score"], canonical["saved_note_version"],
        ))
        self.assertFalse(api._chat_turn_constraint_violations(canonical["title"], canonical["body"], canonical["turn_constraint"]))

    def test_note_save_failure_keeps_previous_version_and_emits_no_success_update(self):
        fake_db = _FakeDB(fail_note_save=True)
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已完成。<note><title>新标题</title><body>只保留真实菜品体验。</body></note>"

        async def clean_shape(title, body, domain, fact_source, route):
            return body

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], False

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = clean_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()

        self.assertFalse(any(ev.get("type") == "note_update" for ev in events))
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertFalse(canonical["saved"])
        self.assertEqual(canonical["status"], "save_failed")
        self.assertEqual(canonical["title"], "旧标题")
        self.assertEqual(canonical["saved_note_version"], 1)
        self.assertEqual(api._chat_sessions["s1"]["note_body"], canonical["body"])
        self.assertEqual(api._chat_sessions["s1"]["_last_note_id"], "note-root")

    def test_removal_claim_without_final_note_cannot_masquerade_as_completed_rewrite(self):
        fake_db = _FakeDB()
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已经全部删掉了，你可以直接发布。"

        api._mr.stream_chat = fake_stream_chat

        events = self._events()

        self.assertFalse(any(ev.get("type") == "note_update" for ev in events))
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertEqual(canonical["status"], "no_final_note")
        self.assertFalse(canonical["saved"])
        self.assertEqual(canonical["body"], "旧正文有20分钟、吃不出柴感，半小时就能完成。")
        self.assertNotIn("可以直接发布", json.dumps(api._chat_sessions["s1"]["messages"], ensure_ascii=False))
        self.assertFalse(any(sql.startswith("INSERT INTO notes") for sql, _ in fake_db.executed))


if __name__ == "__main__":
    unittest.main()
