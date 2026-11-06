"""Select retained, owned note versions through real cover admission, without models."""
from datetime import timedelta
import hashlib
import json
import unittest
import uuid
from unittest import mock

from fastapi import HTTPException

from tests import test_cover_api as fixtures

api = fixtures.api
db = fixtures.db


class CoverSavedNoteVersionTests(unittest.TestCase):
    def setUp(self):
        self.contract = fixtures.CoverApiContractTests()
        self.contract.setUp()
        self.user = self.contract.user

    def tearDown(self):
        self.contract.tearDown()

    def note(self, *, parent=None, version=1, owner=None, created=None, title=None, body=None):
        note_id = str(uuid.uuid4())
        db.execute("INSERT INTO notes(id,user_id,title,body,domain,source,parent_id,version,created_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?)", (note_id, owner or self.user["id"],
                   title or f"真实标题 v{version}", body or f"真实正文 v{version}", "休闲娱乐体验",
                   "chat" if parent else "generate", parent, version,
                   created or (self.contract.fixture.now + timedelta(microseconds=version)).isoformat()))
        return note_id

    def generation(self):
        report_id = self.note(title="原始生成标题", body="原始生成正文")
        stamp = self.contract.fixture.now.isoformat()
        result = {"note_title": "原始生成标题", "note_body": "原始生成正文",
                  "saved_note_id": report_id, "saved_note_version": 1,
                  "title_variants": ["仅属于原稿的备选标题"],
                  "source_media_refs": [self.contract.fixture.source.id],
                  "source_media_items": [{"input_field": "cover_image", "image_index": 1,
                                          "media_ref": self.contract.fixture.source.id}]}
        task = {"operation": "generate", "status": "completed", "result": result}
        db.execute("INSERT INTO idempotency_requests(id,user_id,operation,key_hash,payload_hash,status,"
                   "lease_token_hash,lease_expires_at,complete_applied,created_at,updated_at) "
                   "VALUES(?,?,'generate',?,?,'completed',?,?,1,?,?)",
                   (report_id, self.user["id"], report_id, "fixture", "fixture", stamp, stamp, stamp))
        db.execute("INSERT INTO chat_sessions(id,user_id,note_id,generate_ctx_json,messages_json,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?)", (report_id, self.user["id"], report_id,
                   json.dumps({"task_continuation": task}, ensure_ascii=False), "[]", stamp, stamp))
        return report_id

    def request(self, **kwargs):
        original = self.contract.request()
        return api.CoverSubmitInput(**{**original.model_dump(), **kwargs})

    def submit(self, report_id, request):
        return self.contract.submit(request, report=report_id, kind="generate")

    @staticmethod
    def snapshot(job):
        return json.loads(db.fetchone("SELECT input_json FROM cover_jobs WHERE id=?", (job["job_id"],))[0])

    def test_optimized_version_freezes_real_text_hashes_and_unique_hold_without_replacing_original(self):
        report = self.generation()
        title, body = "优化后保留事实的标题", "第一段真实优化正文。\n\n第二段仍为已保存原文。"
        optimized = self.note(parent=report, version=2, title=title, body=body)
        request = self.request(source_note_id=optimized, title=title)
        job = self.submit(report, request)
        frozen = self.snapshot(job)
        self.assertEqual((frozen["title"], frozen["body"]), (title, body))
        self.assertEqual((frozen["source_note_id"], frozen["source_note_version"]), (optimized, 2))
        self.assertEqual(frozen["title_sha256"], hashlib.sha256(title.encode("utf-8")).hexdigest())
        self.assertEqual(frozen["body_sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest())
        self.assertEqual(frozen["title_variants"], [])
        self.assertEqual(frozen["approved_titles"], [title])
        self.assertEqual(frozen["source_items"][0]["media_ref"], self.contract.fixture.source.id)
        before = self.contract.counts(), self.contract.fixture.balances()
        self.assertEqual(self.submit(report, request)["job_id"], job["job_id"])
        self.assertEqual((self.contract.counts(), self.contract.fixture.balances()), before)
        self.assertEqual((job["billing"]["reserved_credits"], job["billing"]["credits_used"]), (8, 0))
        reopened = self.contract.run_async(api.get_report("generate", report, self.user))["result"]
        self.assertEqual((reopened["note_title"], reopened["note_body"]), ("原始生成标题", "原始生成正文"))
        self.assertEqual(reopened["note_version_group"]["latest"]["id"], optimized)

    def test_legacy_request_keeps_original_even_when_optimized_version_exists(self):
        report = self.generation()
        self.note(parent=report, version=2)
        job = self.submit(report, self.request(title="仅属于原稿的备选标题"))
        frozen = self.snapshot(job)
        self.assertEqual((frozen["title"], frozen["body"]), ("仅属于原稿的备选标题", "原始生成正文"))
        for key in ("source_note_id", "source_note_version", "title_sha256", "body_sha256"):
            self.assertNotIn(key, frozen)

    def test_explicit_original_version_uses_only_its_saved_title(self):
        report = self.generation()
        job = self.submit(report, self.request(source_note_id=report))
        frozen = self.snapshot(job)
        self.assertEqual((frozen["source_note_id"], frozen["source_note_version"]), (report, 1))
        self.assertEqual(frozen["approved_titles"], ["原始生成标题"])
        self.assertEqual(frozen["title_variants"], [])

    def test_foreign_unrelated_expired_deleted_or_cyclic_versions_reject_before_reservation(self):
        report = self.generation()
        foreign = self.note(parent=report, version=2, owner=self.contract.other["id"])
        unrelated = self.generation()
        unrelated_child = self.note(parent=unrelated, version=2)
        expired = self.note(parent=report, version=2,
                            created=(self.contract.fixture.now - timedelta(days=30)).isoformat())
        deleted = self.note(parent=report, version=2)
        fixtures.content_retention.mark_deleted("note", deleted, self.user["id"])
        cyclic = self.note(version=2)
        db.execute("UPDATE notes SET parent_id=? WHERE id=?", (cyclic, cyclic))
        before = self.contract.counts(), self.contract.fixture.balances()
        with mock.patch.object(fixtures.storage, "load_media_bytes", side_effect=AssertionError("invalid note must reject before media or hold")):
            for note_id, status in ((foreign, 404), (unrelated_child, 422), (expired, 404),
                                    (deleted, 404), (cyclic, 422), (str(uuid.uuid4()), 404)):
                with self.subTest(note_id=note_id):
                    with self.assertRaises(HTTPException) as caught:
                        self.submit(report, self.request(source_note_id=note_id))
                    self.assertEqual(caught.exception.status_code, status)
                    self.assertEqual((self.contract.counts(), self.contract.fixture.balances()), before)

    def test_selected_version_rejects_original_title_variants_before_reservation(self):
        report = self.generation()
        optimized = self.note(parent=report, version=2)
        before = self.contract.counts(), self.contract.fixture.balances()
        for wrong_title in ("原始生成标题", "仅属于原稿的备选标题", "自行输入的新标题"):
            with self.subTest(title=wrong_title), self.assertRaises(HTTPException) as caught:
                self.submit(report, self.request(source_note_id=optimized, title=wrong_title))
            self.assertEqual(caught.exception.status_code, 422)
            self.assertEqual((self.contract.counts(), self.contract.fixture.balances()), before)


if __name__ == "__main__":
    unittest.main()
