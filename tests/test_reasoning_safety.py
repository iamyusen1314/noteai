import asyncio
import contextlib
import importlib
import inspect
import io
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


SENTINEL = "SEC002_PRIVATE_REASONING_SENTINEL"


class ReasoningSafetyTests(unittest.TestCase):
    def test_public_expert_projection_keeps_explanation_without_provider_raw(self):
        provider_private = "SEC003_PROVIDER_PRIVATE"
        opinion = api._public_expert_opinion({
            "role": "内容专家<img src=x onerror=sentinel()>",
            "raw": (
                "<opinion><svg onload=sentinel()>保留字面意见</svg></opinion>"
                "<evidence>证据一\n证据二</evidence>"
                "<impact>影响说明</impact>"
                "<suggestions>建议一\n建议二</suggestions>"
                "<confidence>0.88</confidence>"
                f"<{provider_private}>内部原文</{provider_private}>"
            ),
            "provider": provider_private,
            "reasoning_content": provider_private,
            "_image_desc": provider_private,
        })

        self.assertEqual(
            set(opinion),
            {"role", "opinion", "reason", "impact", "evidence", "evidence_binding", "suggestions", "confidence"},
        )
        self.assertEqual(opinion["confidence"], 0.88)
        self.assertEqual(opinion["reason"], "影响说明")
        self.assertEqual(opinion["impact"], "影响说明")
        self.assertEqual(opinion["evidence_binding"], "")
        self.assertEqual(opinion["suggestions"], ["建议一", "建议二"])
        serialized = json.dumps(opinion, ensure_ascii=False)
        self.assertNotIn(provider_private, serialized)
        for blocked in ('"raw"', '"provider"', '"reasoning_content"', '"_image_desc"'):
            self.assertNotIn(blocked, serialized)

        malformed = api._public_expert_opinion({
            "role": "内容专家",
            "raw": f"<{provider_private}>内部原文</{provider_private}>",
        })
        self.assertEqual(malformed["opinion"], "内容专家已完成分析。")
        self.assertNotIn(provider_private, json.dumps(malformed, ensure_ascii=False))

        bound = api._public_expert_opinion({
            "role": "内容专家",
            "opinion": "公开意见",
            "evidence_binding": "v04_structured",
        })
        untrusted_binding = api._public_expert_opinion({
            "role": "内容专家",
            "opinion": "公开意见",
            "evidence_binding": provider_private,
        })
        self.assertEqual(bound["evidence_binding"], "v04_structured")
        self.assertEqual(untrusted_binding["evidence_binding"], "")

    def test_historical_diagnosis_projection_is_on_read_and_preserves_business_provider(self):
        historical = {
            "expert_opinions": [{
                "role": "增长专家",
                "raw": "<opinion>增长意见</opinion><confidence>0.7</confidence>",
                "provider": "internal-model-provider",
                "reasoning": SENTINEL,
            }],
            "fact_enrichment": {"provider": "amap", "raw_title": "业务字段"},
            "reasoning_content": SENTINEL,
        }

        projected = api._public_diagnosis_value(historical)
        self.assertEqual(projected["fact_enrichment"], {"provider": "amap", "raw_title": "业务字段"})
        self.assertNotIn("reasoning_content", projected)
        self.assertEqual(projected["expert_opinions"][0]["opinion"], "增长意见")
        self.assertNotIn("raw", projected["expert_opinions"][0])

    def test_public_expert_projection_is_applied_at_every_delivery_boundary(self):
        analyze_source = inspect.getsource(api._run_analyze_pipeline)
        generate_source = inspect.getsource(api.generate)
        generate_stream_source = inspect.getsource(api._generate_pipeline_stream)
        chat_start_source = inspect.getsource(api.chat_start)
        diagnosis_source = inspect.getsource(api.get_diagnosis)
        for source in (analyze_source, generate_source, generate_stream_source, chat_start_source):
            self.assertIn("_public_expert_opinions", source)
        self.assertIn("_public_diagnosis_value", diagnosis_source)

    def test_generate_and_chat_application_paths_never_serialize_thinking(self):
        generate_source = inspect.getsource(api._generate_pipeline_stream)
        chat_source = inspect.getsource(api._chat_sse_generator)
        for source in (generate_source, chat_source):
            self.assertNotIn('"type": "thinking_chunk"', source)
            self.assertNotIn("'type': 'thinking_chunk'", source)
            self.assertNotIn("full_reasoning", source)
            self.assertIn("_public_model_content_chunks", source)

    def test_public_model_stream_drops_provider_reasoning_for_all_routes(self):
        async def provider_stream():
            yield "thinking", SENTINEL
            yield "content", "公开正文"
            yield "thinking", SENTINEL + "_fallback"
            yield "content", "完成"

        async def collect():
            return [chunk async for chunk in api._public_model_content_chunks(provider_stream())]

        output = asyncio.run(collect())
        self.assertEqual(output, ["公开正文", "完成"])
        self.assertNotIn(SENTINEL, "".join(output))

    def test_process_events_are_code_only_and_drop_unknown_raw_values(self):
        event = api._safe_process_event(
            "final_explanation",
            phase="verify",
            agent="quality",
            status_code="generation_ready",
            reason_codes=["quality_gate_checked", SENTINEL],
            facts={
                "score": 72.345,
                "saved": False,
                "raw": SENTINEL,
                "provider": SENTINEL,
                "title": SENTINEL,
            },
            progress=999,
        )

        serialized = json.dumps(event, ensure_ascii=False)
        self.assertNotIn(SENTINEL, serialized)
        self.assertEqual(event["reason_codes"], ["quality_gate_checked"])
        self.assertEqual(event["facts"], {"score": 72.34, "saved": False})
        self.assertEqual(event["progress"], 100)

    def test_chat_sse_drops_reasoning_and_emits_explanation_after_persist(self):
        original_db = api._db
        original_sessions = dict(api._chat_sessions)
        original_stream_chat = api._mr.stream_chat
        original_repair = api._repair_chat_note_if_needed
        original_shape = api._shape_body_for_delivery
        original_sanitize = api._sanitize_title_for_delivery
        original_check_achievements = api._memory.check_and_record_achievements
        original_add_context = api._memory.add_context

        class FakeDB:
            def __init__(self):
                self.executed = []

            def fetchone(self, sql, params=()):
                if "FROM notes" in sql and params == ("note-root", "u1"):
                    return {
                        "id": "note-root",
                        "title": "旧标题",
                        "body": "旧正文",
                        "domain": "美食",
                        "score": 60.0,
                        "grade": "待改进",
                        "version": 1,
                        "parent_id": None,
                    }
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        async def fake_stream_chat(**_kwargs):
            yield "thinking", SENTINEL
            yield "content", "<note><title>新版标题</title><body>新版正文 #上海美食</body></note>"
            yield "thinking", SENTINEL + "_fallback"

        async def fake_repair(title, body, session, user_msg):
            return title, body, 72.0, {}, "良好", [], False

        async def fake_shape(title, body, domain, fact_source, route):
            return body

        fake_db = FakeDB()
        try:
            api._db = fake_db
            api._chat_sessions.clear()
            api._chat_sessions["s1"] = {
                "note_title": "旧标题",
                "note_body": "旧正文",
                "domain": "美食",
                "local_time": "2026071112",
                "user_id": "u1",
                "current_score": 60.0,
                "messages": [],
                "iteration_count": 0,
                "note_id": "note-root",
                "_last_note_id": "note-root",
                "user_constraints": [],
                "generate_context": {},
            }
            api._mr.stream_chat = fake_stream_chat
            api._repair_chat_note_if_needed = fake_repair
            api._shape_body_for_delivery = fake_shape
            api._sanitize_title_for_delivery = lambda title, fact_source, domain: title
            api._memory.check_and_record_achievements = lambda *_args, **_kwargs: []
            api._memory.add_context = lambda *_args, **_kwargs: None

            async def collect_events():
                events = []
                async for chunk in api._chat_sse_generator("s1", "帮我重写一版"):
                    if chunk.startswith("data: "):
                        events.append(json.loads(chunk.removeprefix("data: ").strip()))
                return events

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                events = asyncio.run(collect_events())

            serialized_events = json.dumps(events, ensure_ascii=False)
            serialized_session = json.dumps(api._chat_sessions["s1"], ensure_ascii=False)
            serialized_writes = json.dumps(fake_db.executed, ensure_ascii=False, default=str)
            self.assertNotIn(SENTINEL, serialized_events)
            self.assertNotIn(SENTINEL, serialized_session)
            self.assertNotIn(SENTINEL, serialized_writes)
            self.assertNotIn(SENTINEL, stderr.getvalue())
            self.assertNotIn("reasoning_content", serialized_session)
            self.assertFalse(any(event.get("type") == "thinking_chunk" for event in events))
            self.assertTrue(any(event.get("type") == "content_chunk" for event in events))
            request_process = next(event for event in events if event.get("status_code") == "request_analysis_started")
            self.assertEqual(request_process["reason_codes"], ["request_received"])

            types = [event.get("type") for event in events]
            self.assertLess(types.index("note_update"), types.index("final_explanation"))
            self.assertLess(types.index("final_explanation"), types.index("done"))
            explanation = next(event for event in events if event.get("type") == "final_explanation")
            self.assertTrue(explanation["facts"]["saved"])
            self.assertTrue(explanation["facts"]["session_persisted"])
            self.assertEqual(explanation["facts"]["version"], 2)
        finally:
            api._db = original_db
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)
            api._mr.stream_chat = original_stream_chat
            api._repair_chat_note_if_needed = original_repair
            api._shape_body_for_delivery = original_shape
            api._sanitize_title_for_delivery = original_sanitize
            api._memory.check_and_record_achievements = original_check_achievements
            api._memory.add_context = original_add_context

    def test_historical_chat_load_and_rewrite_strip_internal_metadata_recursively(self):
        original_db = api._db
        original_sessions = dict(api._chat_sessions)

        class FakeDB:
            def __init__(self):
                self.executed = []
                self.row = {
                    "id": "historic",
                    "user_id": "u1",
                    "note_id": None,
                    "domain": "美食",
                    "local_time": "2026071112",
                    "messages_json": json.dumps([
                        {
                            "role": "assistant",
                            "content": "可公开回复",
                            "reasoning_content": SENTINEL,
                            "metadata": {
                                "provider": "private-provider",
                                "thinking_delta": SENTINEL,
                            },
                        }
                    ]),
                    "user_prefs_json": "{}",
                    "iteration_count": 1,
                    "current_score": 66.0,
                    "generate_ctx_json": json.dumps({
                        "expert_opinions": [{"role": "专家", "raw": SENTINEL}],
                        "system_prompt": SENTINEL,
                        "provider_metadata": {"model": SENTINEL},
                    }),
                }

            def fetchone(self, sql, params=()):
                if "FROM chat_sessions" in sql:
                    return self.row
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        fake_db = FakeDB()
        try:
            api._db = fake_db
            recovered = api._load_chat_session_from_db("historic")
            self.assertIsNotNone(recovered)
            self.assertNotIn(SENTINEL, json.dumps(recovered, ensure_ascii=False))
            self.assertEqual(recovered["messages"][0]["content"], "可公开回复")

            api._chat_sessions.clear()
            api._chat_sessions["historic"] = recovered
            self.assertTrue(api._persist_chat_session("historic"))
            persisted = json.dumps(fake_db.executed, ensure_ascii=False, default=str)
            self.assertNotIn(SENTINEL, persisted)
            for blocked in ("reasoning_content", "thinking_delta", "system_prompt", "provider_metadata", '"raw"'):
                self.assertNotIn(blocked, persisted)
        finally:
            api._db = original_db
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)


if __name__ == "__main__":
    unittest.main()
