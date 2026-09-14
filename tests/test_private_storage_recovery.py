import asyncio
import hashlib
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
durable_ai = importlib.import_module("durable_ai")
private_storage = importlib.import_module("private_storage")
recovery_evidence = importlib.import_module("storage_recovery_evidence")
api = importlib.import_module("api")
_RECOVERY_TOOL_SPEC = importlib.util.spec_from_file_location(
    "noteai_recovery_evidence_tool",
    ROOT / "tools" / "recovery_evidence.py",
)
assert _RECOVERY_TOOL_SPEC is not None
assert _RECOVERY_TOOL_SPEC.loader is not None
recovery_evidence_tool = importlib.util.module_from_spec(_RECOVERY_TOOL_SPEC)
_RECOVERY_TOOL_SPEC.loader.exec_module(recovery_evidence_tool)


class PrivateStorageRecoveryContractTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        self.backend = private_storage.InMemoryObjectBackend()
        private_storage.configure_object_backend(
            self.backend,
            key_epoch="isolated-test-epoch-1",
        )
        self.payload_store = private_storage.PrivateObjectPayloadStore(
            self.backend,
            key_epoch="isolated-test-epoch-1",
        )
        durable_ai.configure_payload_store(self.payload_store)
        billing.clear_active_usage()
        self.now = (
            datetime.now(timezone.utc) - timedelta(seconds=2)
        ).replace(microsecond=456789)

    def tearDown(self):
        billing.clear_active_usage()
        durable_ai.reset_payload_store()
        private_storage.reset_object_backend()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        else:
            os.environ.pop("DATABASE_URL", None)
        self.temp.cleanup()

    def create_user(self, user_id: str, *, wallet: float = 1000) -> None:
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                user_id,
                f"{user_id}_name",
                f"{user_id}@example.com",
                "hash",
                "salt",
                self.now.isoformat(),
            ),
        )
        billing.get_subscription(user_id)
        db.execute(
            "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance",
            (user_id, wallet, wallet, 0, self.now.isoformat()),
        )

    @staticmethod
    def jpeg(label: str = "frame") -> bytes:
        return b"\xff\xd8" + label.encode("ascii") + b"\xff\xd9"

    def store_video(
        self,
        user_id: str,
        *,
        now: datetime | None = None,
        ttl_seconds: int = private_storage.MEDIA_TTL_SECONDS,
    ):
        bundle = private_storage.build_video_frame_bundle(
            [self.jpeg("one"), self.jpeg("two")],
            duration_sec=2.0,
            raw_fps=30.0,
        )
        return private_storage.store_media_bytes(
            user_id,
            purpose="video_frames",
            content_type="application/vnd.noteai.video-frames+zip",
            payload=bundle,
            item_count=2,
            ttl_seconds=ttl_seconds,
            now=now or self.now,
        )

    def test_original_media_response_survives_commit_ack_loss_without_recharge(self):
        import idempotency
        self.create_user('ocr-owner')
        claim = idempotency.claim_and_charge(user_id='ocr-owner', operation='screenshot',
            request_id='original-ocr-key', payload={'image_base64':'media:opaque'})
        result = {'type':'B','cover_desc':'测试红色招牌','body':'测试红色招牌','ocr_request_id':'original-ocr-key'}
        original = idempotency.mark_completed
        def lost_ack(*args, **kwargs):
            self.assertTrue(original(*args, **kwargs))
            raise RuntimeError('synthetic_commit_ack_lost')
        with mock.patch.object(idempotency, 'mark_completed', side_effect=lost_ack):
            idempotency.complete_media_response(claim, result, kind='screenshot_extract', ocr_result=result)
        row = db.fetchone('SELECT * FROM idempotency_requests WHERE id=?', (claim['request_id'],))
        self.assertNotIn('测试红色招牌', row['response_ref_json'])
        self.assertEqual((row['status'],row['complete_applied'],row['refund_applied']), ('completed',1,0))
        self.assertEqual(idempotency.read_media_response('ocr-owner',claim['request_id'])['result'],result)
        self.assertIsNone(idempotency.read_media_response('other-owner',claim['request_id']))
        duplicate = idempotency.claim_and_charge(user_id='ocr-owner', operation='screenshot',
            request_id='original-ocr-key', payload={'image_base64':'media:opaque'})
        self.assertEqual(duplicate['state'],'completed')
        self.assertEqual(db.fetchone('SELECT count(*) n FROM usage_records WHERE user_id=?',('ocr-owner',))['n'],1)
        orphan = private_storage.reconcile_orphans(prefix='v1/payload/result', now=self.now+timedelta(days=2))
        self.assertEqual(orphan['orphan_count'],0)
        with self.assertRaises(Exception):
            db.execute('DELETE FROM idempotency_requests WHERE id=?',(claim['request_id'],))
        for changes in ({'state':None,'deleted_at':self.now.isoformat()}, {'raw':'private-extra'}):
            edited=json.loads(row['response_ref_json'])
            if 'raw' in changes: del edited['size_bytes']
            edited.update(changes)
            with self.assertRaises(Exception):
                db.execute('UPDATE idempotency_requests SET response_ref_json=? WHERE id=?',
                           (json.dumps(edited),claim['request_id']))
        idempotency.delete_user_responses('ocr-owner')
        self.assertFalse(idempotency.read_media_response('ocr-owner',claim['request_id'])['result_available'])
        db.execute('DELETE FROM idempotency_requests WHERE id=?',(claim['request_id'],))

    def test_media_unknown_and_storage_outage_preserve_original_charge(self):
        import idempotency, base64
        from PIL import Image
        from fastapi import HTTPException
        self.create_user('ocr-unknown')
        data=io.BytesIO();Image.new('RGB',(300,200),'red').save(data,'PNG')
        request=api.ScreenshotExtractInput(image_base64=base64.b64encode(data.getvalue()).decode())
        def unknown(*args,**kwargs):
            claim=db.fetchone("SELECT * FROM idempotency_requests WHERE user_id='ocr-unknown'")
            db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) "
                       "VALUES(?,'website-free-product-20260912',?,?,'unknown',1,?,?)",
                       (str(uuid.uuid4()),'ocr-unknown','a'*64,self.now.isoformat(),claim['usage_id']))
            raise api._public_product.TrialProviderStopped('ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY')
        with mock.patch.object(api._ark_media,'chat',side_effect=unknown) as provider:
            with self.assertRaises(HTTPException) as stopped:
                asyncio.run(api.extract_screenshot(request,user={'id':'ocr-unknown'},request_id='unknown-original'))
        self.assertEqual(stopped.exception.status_code,503)
        self.assertEqual(provider.call_count,1)
        row=dict(db.fetchone("SELECT * FROM idempotency_requests WHERE user_id='ocr-unknown'"))
        self.assertEqual((row['status'],row['refund_applied']),('running',0))
        with db.transaction(write=True) as tx, self.assertRaises(idempotency.ResultRecoveryRequired):
            idempotency.settle_expired_requests_for_account_deletion_with_storage(tx,'ocr-unknown',
                now=datetime.now(timezone.utc)+timedelta(days=1))
        self.create_user('ocr-store')
        claim=idempotency.claim_and_charge(user_id='ocr-store',operation='screenshot',request_id='store-original',payload={'test':'local'})
        with mock.patch.object(self.payload_store,'put',side_effect=RuntimeError('synthetic storage unavailable')):
            with self.assertRaises(idempotency.ResultRecoveryRequired):
                idempotency.complete_media_response(claim,{'body':'synthetic'},kind='screenshot_extract')
        read=idempotency.read_media_response('ocr-store',claim['request_id'])
        self.assertEqual(read['result_state'],'recovery_required')
        with self.assertRaises(idempotency.ResultRecoveryRequired):
            idempotency.mark_failed_and_refund(claim)
        row=db.fetchone('SELECT * FROM idempotency_requests WHERE id=?',(claim['request_id'],))
        self.assertEqual((row['status'],row['refund_applied']),('running',0))

    def test_media_read_outage_is_explicit_without_reinference(self):
        from fastapi import HTTPException
        import idempotency
        self.create_user('ocr-read')
        claim=idempotency.claim_and_charge(user_id='ocr-read',operation='screenshot',request_id='read-original',payload={'test':'local'})
        idempotency.complete_media_response(claim,{'body':'synthetic'},kind='screenshot_extract')
        with mock.patch.object(self.payload_store,'get',side_effect=RuntimeError('private exception must not leak')), \
             mock.patch.object(api._ark_media,'chat',side_effect=AssertionError('read must not infer')):
            with self.assertRaises(HTTPException) as stopped:
                asyncio.run(api.read_chat_task(claim['request_id'],user={'id':'ocr-read'}))
        self.assertEqual(stopped.exception.status_code,503)
        self.assertEqual(stopped.exception.detail['session_id'],claim['request_id'])
        self.assertNotIn('private exception',str(stopped.exception.detail))

    def test_media_disconnect_finishes_original_result_and_free_merge(self):
        import idempotency, threading, base64
        from PIL import Image
        self.create_user('ocr-disconnect')
        data=io.BytesIO();Image.new('RGB',(300,200),'red').save(data,'PNG')
        request=api.ScreenshotExtractInput(image_base64=base64.b64encode(data.getvalue()).decode())
        started=threading.Event();release=threading.Event()
        def recognize(*args,**kwargs):
            started.set();self.assertTrue(release.wait(10))
            return json.dumps({'type':'B','title':'','body':'','domain':'美食','cover_desc':'测试红色招牌'})
        async def workflow():
            with mock.patch.object(api._ark_media,'chat',side_effect=recognize) as model:
                task=asyncio.create_task(api.extract_screenshot(request,user={'id':'ocr-disconnect'},request_id='ocr-disconnect-key'))
                self.assertTrue(await asyncio.to_thread(started.wait,10))
                task.cancel();release.set()
                with self.assertRaises(asyncio.CancelledError):await task
                self.assertEqual(model.call_count,1)
            read=await api.pending_chat_tasks(user={'id':'ocr-disconnect'},request_id='ocr-disconnect-key',operation='screenshot')
            original=read['tasks'][0]
            self.assertTrue(original['result_available'])
            self.assertNotIn('_image_bytes',original['result'])
            self.assertEqual((await api.read_chat_task(original['session_id'],user={'id':'ocr-disconnect'}))['result'],original['result'])
            merge=api.ValidateOcrInput(ocr_results=[original['result']],ocr_request_ids=['ocr-disconnect-key'])
            with mock.patch.object(api._mr,'call',side_effect=AssertionError('pure image merge must not infer')):
                merged=await api.validate_ocr(merge,user={'id':'ocr-disconnect'})
                self.assertTrue(merged['is_photo_only'])
                with self.assertRaises(HTTPException) as duplicate:await api.validate_ocr(merge,user={'id':'ocr-disconnect'})
                self.assertEqual(duplicate.exception.status_code,409)
            rows=[dict(r) for r in db.fetchall('SELECT * FROM idempotency_requests WHERE user_id=?',('ocr-disconnect',))]
            self.assertEqual(len(rows),2)
            self.assertEqual(sum(r['credits_used'] for r in rows),0.5)
            self.assertTrue(all(r['status']=='completed' and not r['refund_applied'] for r in rows))
        from fastapi import HTTPException
        asyncio.run(workflow())

    def test_schema_and_migration_are_content_free_and_grant_free(self):
        conn = db.get_conn()
        try:
            tables = {}
            for table in ("private_media_refs", "ai_operation_media_refs"):
                tables[table] = {
                    row["name"]
                    for row in conn.execute(f"PRAGMA table_info({table})")
                }
        finally:
            conn.close()
        self.assertIn("object_key_hash", tables["private_media_refs"])
        self.assertIn("content_sha256", tables["private_media_refs"])
        self.assertEqual(
            tables["ai_operation_media_refs"],
            {"operation_id", "media_ref_id", "ordinal", "created_at"},
        )
        forbidden = {
            "user_id",
            "object_key",
            "url",
            "filename",
            "payload",
            "body",
            "prompt",
            "secret",
            "cookie",
            "credential",
        }
        for columns in tables.values():
            self.assertFalse(forbidden & columns)
        migration = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0013_private_storage_recovery_contract.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("private_media_refs", migration)
        self.assertIn("ai_operation_media_refs", migration)
        self.assertIn("size_bytes BETWEEN 1 AND 10485760", migration)
        self.assertNotIn("GRANT ", migration.upper())
        self.assertNotIn("REVOKE ", migration.upper())

    def test_local_backend_survives_process_recreation_with_private_permissions(self):
        root = Path(self.temp.name) / "objects"
        first = private_storage.LocalDirectoryObjectBackend(root)
        store = private_storage.PrivateObjectPayloadStore(
            first,
            key_epoch="local-restart-epoch",
        )
        operation_id = str(uuid.uuid4())
        reference = store.put(
            operation_id=operation_id,
            user_id="owner-local",
            purpose="request",
            payload=b'{"content":"private"}',
            item_count=1,
            ttl_seconds=3600,
            now=self.now,
        )
        recreated = private_storage.LocalDirectoryObjectBackend(root)
        second_store = private_storage.PrivateObjectPayloadStore(
            recreated,
            key_epoch="local-restart-epoch",
        )
        self.assertEqual(
            second_store.get(reference, user_id="owner-local"),
            b'{"content":"private"}',
        )
        with self.assertRaises(durable_ai.PayloadUnavailable):
            second_store.get(reference, user_id="other-owner")
        object_files = [path for path in root.rglob("*") if path.is_file()]
        self.assertEqual(len(object_files), 2)
        for path in object_files:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        with self.assertRaises(ValueError):
            first.get("../../escape", max_bytes=10)

    def test_payload_store_is_idempotent_and_detects_tampering(self):
        operation_id = str(uuid.uuid4())
        first = self.payload_store.put(
            operation_id=operation_id,
            user_id="payload-owner",
            purpose="request",
            payload=b'{"value":1}',
            item_count=1,
            ttl_seconds=3600,
            now=self.now,
        )
        second = self.payload_store.put(
            operation_id=operation_id,
            user_id="payload-owner",
            purpose="request",
            payload=b'{"value":1}',
            item_count=1,
            ttl_seconds=3600,
            now=self.now + timedelta(seconds=10),
        )
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.expires_at, second.expires_at)
        key = next(iter(self.backend._objects))
        body, metadata, created_at = self.backend._objects[key]
        self.backend._objects[key] = (body + b"x", metadata, created_at)
        with self.assertRaises(durable_ai.PayloadUnavailable) as raised:
            self.payload_store.get(first, user_id="payload-owner")
        self.assertEqual(raised.exception.code, "PRIVATE_OBJECT_SIZE_MISMATCH")

    def test_media_database_failure_compensates_object(self):
        bundle = private_storage.build_video_frame_bundle(
            [self.jpeg()],
            duration_sec=1,
            raw_fps=30,
        )
        with self.assertRaises(ValueError):
            private_storage.store_media_bytes(
                "missing-user",
                purpose="video_frames",
                content_type="application/vnd.noteai.video-frames+zip",
                payload=bundle,
                item_count=1,
                now=self.now,
            )
        self.assertEqual(self.backend._objects, {})
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS count FROM private_media_refs")["count"],
            0,
        )

    def test_owner_bound_media_cross_node_load_and_bundle_integrity(self):
        self.create_user("media-owner")
        reference = self.store_video("media-owner")
        loaded_reference, body = private_storage.load_media_bytes(
            reference.id,
            user_id="media-owner",
        )
        self.assertEqual(loaded_reference, reference)
        restored = private_storage.read_video_frame_bundle(body)
        self.assertEqual(
            restored["frames"],
            [self.jpeg("one"), self.jpeg("two")],
        )
        self.assertEqual(restored["duration_sec"], 2.0)
        with self.assertRaises(private_storage.MediaReferenceUnavailable):
            private_storage.load_media_bytes(
                reference.id,
                user_id="different-owner",
            )
        corrupted = bytearray(body)
        frame_offset = body.index(b"one")
        corrupted[frame_offset] ^= 0x01
        with self.assertRaises(private_storage.ObjectStorageUnavailable):
            private_storage.read_video_frame_bundle(bytes(corrupted))

    def test_api_private_video_is_owner_bound_and_production_rejects_legacy_cache(self):
        self.create_user("api-media-owner")
        reference = self.store_video("api-media-owner")
        restored = api._get_video_meta(reference.id, "api-media-owner")
        self.assertEqual(
            restored["frames"],
            [self.jpeg("one"), self.jpeg("two")],
        )
        self.assertIsNone(api._get_video_meta(reference.id, "other-owner"))
        legacy_id = "0123456789abcdef0123"
        original_cache = dict(api._video_frames)
        try:
            api._video_frames[legacy_id] = {
                "frames": [self.jpeg()],
                "duration_sec": 1,
                "raw_fps": 30,
            }
            with mock.patch.dict(
                os.environ,
                {"NOTEAI_DEPLOYMENT_STAGE": "production"},
            ):
                self.assertIsNone(api._get_video_meta(legacy_id, "api-media-owner"))
        finally:
            api._video_frames.clear()
            api._video_frames.update(original_cache)

    def test_image_upload_streams_normalizes_and_returns_only_opaque_reference(self):
        from PIL import Image
        from starlette.datastructures import Headers, UploadFile

        self.create_user("image-owner")
        source = io.BytesIO()
        Image.new("RGBA", (300, 200), (255, 0, 0, 128)).save(
            source,
            format="PNG",
            pnginfo=None,
        )
        source.seek(0)
        upload = UploadFile(
            file=source,
            filename="private.png",
            headers=Headers({"content-type": "image/png"}),
        )
        response = asyncio.run(
            api.upload_image(upload, {"id": "image-owner"})
        )
        self.assertEqual(set(response) - {"media_ref"}, {
            "filename",
            "original_size",
            "stored_size",
            "width",
            "height",
            "expires_at",
        })
        uuid.UUID(response["media_ref"])
        reference, body = private_storage.load_media_bytes(
            response["media_ref"],
            user_id="image-owner",
            purpose="image",
        )
        self.assertEqual(reference.content_type, "image/jpeg")
        with Image.open(io.BytesIO(body)) as restored:
            self.assertEqual(restored.mode, "RGB")
            self.assertEqual(restored.size, (300, 200))
            self.assertEqual(len(restored.getexif()), 0)

    def test_streamed_upload_enforces_limit_before_unbounded_read(self):
        from fastapi import HTTPException
        from starlette.datastructures import Headers, UploadFile

        upload = UploadFile(
            file=io.BytesIO(b"0123456789"),
            filename="oversize.bin",
            headers=Headers({"content-type": "application/octet-stream"}),
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                api._stream_upload_to_temp(
                    upload,
                    suffix=".bin",
                    maximum_bytes=5,
                )
            )
        self.assertEqual(raised.exception.status_code, 413)

    def test_durable_admission_locks_and_links_owned_media_before_billing(self):
        self.create_user("job-owner")
        self.create_user("other-owner")
        media = self.store_video("job-owner")
        admitted = durable_ai.admit_job(
            user_id="job-owner",
            operation="analyze",
            request_id="media-job-1",
            payload={"content": "analyze", "media_refs": [media.id]},
            now=self.now,
            store=self.payload_store,
        )
        self.assertEqual(admitted["state"], "admitted")
        link = db.fetchone(
            "SELECT operation_id,media_ref_id,ordinal "
            "FROM ai_operation_media_refs"
        )
        self.assertEqual(link["operation_id"], admitted["operation_id"])
        self.assertEqual(link["media_ref_id"], media.id)
        self.assertEqual(link["ordinal"], 0)

        before = db.fetchone(
            "SELECT balance FROM credits WHERE user_id='other-owner'"
        )["balance"]
        with self.assertRaises(durable_ai.DurableAiError) as raised:
            durable_ai.admit_job(
                user_id="other-owner",
                operation="analyze",
                request_id="cross-owner-job",
                payload={"content": "analyze", "media_refs": [media.id]},
                now=self.now,
                store=self.payload_store,
            )
        self.assertEqual(
            raised.exception.code,
            "DURABLE_AI_MEDIA_REFERENCE_UNAVAILABLE",
        )
        after = db.fetchone(
            "SELECT balance FROM credits WHERE user_id='other-owner'"
        )["balance"]
        self.assertEqual(before, after)
        self.assertIsNone(
            db.fetchone(
                "SELECT 1 FROM idempotency_requests "
                "WHERE user_id='other-owner'"
            )
        )
        self.assertEqual(
            len(
                [
                    key
                    for key in self.backend._objects
                    if "/payload/request/" in key
                ]
            ),
            1,
        )

    def test_expiry_and_account_deletion_delete_objects_before_state_transition(self):
        self.create_user("lifecycle-owner")
        expired_reference = self.store_video(
            "lifecycle-owner",
            now=self.now - timedelta(days=2),
            ttl_seconds=60,
        )
        self.assertEqual(
            private_storage.expire_media(now=self.now, backend=self.backend),
            1,
        )
        expired = db.fetchone(
            "SELECT state,deleted_at FROM private_media_refs WHERE id=?",
            (expired_reference.id,),
        )
        self.assertEqual(expired["state"], "expired")
        self.assertIsNotNone(expired["deleted_at"])

        live_reference = self.store_video("lifecycle-owner")
        self.assertEqual(
            private_storage.delete_user_media(
                "lifecycle-owner",
                backend=self.backend,
                now=self.now + timedelta(seconds=1),
            ),
            1,
        )
        deleted = db.fetchone(
            "SELECT state,deleted_at FROM private_media_refs WHERE id=?",
            (live_reference.id,),
        )
        self.assertEqual(deleted["state"], "deleted")
        self.assertIsNotNone(deleted["deleted_at"])
        self.assertFalse(
            private_storage.has_ready_user_media(db, "lifecycle-owner")
        )
        self.assertEqual(self.backend._objects, {})

    def test_orphan_reconciliation_is_bounded_age_gated_and_dry_run(self):
        reference_id = str(uuid.uuid4())
        subject_hash = "a" * 64
        created = self.now - timedelta(days=2)
        key_epoch_hash = "b" * 64
        body = self.jpeg("orphan")
        key = f"v1/media/image/{subject_hash[:12]}/{reference_id}.bin"
        metadata = private_storage._object_metadata(
            reference_id=reference_id,
            subject_hash=subject_hash,
            purpose="image",
            content_sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            item_count=1,
            expires_at=(created + timedelta(days=7)).isoformat(),
            created_at=created.isoformat(),
            key_epoch_hash=key_epoch_hash,
        )
        self.assertTrue(
            self.backend.put_if_absent(
                key,
                body,
                content_type="image/jpeg",
                metadata=metadata,
            )
        )
        preview = private_storage.reconcile_orphans(
            now=self.now,
            backend=self.backend,
        )
        self.assertEqual(preview["mode"], "dry_run")
        self.assertEqual(preview["orphan_count"], 1)
        self.assertEqual(preview["deleted_count"], 0)
        self.assertEqual(len(preview["orphan_key_hashes"]), 1)
        self.assertIn(key, self.backend._objects)
        applied = private_storage.reconcile_orphans(
            now=self.now,
            backend=self.backend,
            apply=True,
        )
        self.assertEqual(applied["deleted_count"], 1)
        self.assertNotIn(key, self.backend._objects)

    def test_recovery_manifest_matches_isolated_copy_and_detects_drift(self):
        self.create_user("restore-owner")
        self.store_video("restore-owner")
        release_commit = "a" * 40
        original_transaction = db.transaction
        with mock.patch.object(
            recovery_evidence.db,
            "transaction",
            wraps=original_transaction,
        ) as transaction:
            source = recovery_evidence.capture_manifest(
                release_commit=release_commit,
                backend=self.backend,
                now=self.now,
            )
        transaction.assert_called_once_with(write=False)
        self.assertFalse(any(source["privacy"].values()))
        serialized = json.dumps(source, sort_keys=True)
        self.assertNotIn("restore-owner@example.com", serialized)
        self.assertNotIn("v1/media/", serialized)

        restored_path = Path(self.temp.name) / "restored.db"
        shutil.copy2(db._DB_PATH, restored_path)
        db._DB_PATH = restored_path
        restored = recovery_evidence.capture_manifest(
            release_commit=release_commit,
            backend=self.backend,
            now=self.now + timedelta(minutes=1),
        )
        accepted = recovery_evidence.verify_restore(source, restored)
        self.assertTrue(accepted["verified"])
        self.assertEqual(accepted["mismatch_codes"], [])

        db.execute(
            "UPDATE users SET email='changed@example.com' "
            "WHERE id='restore-owner'"
        )
        drifted = recovery_evidence.capture_manifest(
            release_commit=release_commit,
            backend=self.backend,
            now=self.now + timedelta(minutes=2),
        )
        rejected = recovery_evidence.verify_restore(source, drifted)
        self.assertFalse(rejected["verified"])
        self.assertIn("database_tables", rejected["mismatch_codes"])
        self.assertNotIn("changed@example.com", json.dumps(rejected))

        malformed = json.loads(json.dumps(source))
        malformed["privacy"]["unexpected_content_flag"] = False
        malformed.pop("manifest_sha256")
        malformed["manifest_sha256"] = recovery_evidence._sha(
            recovery_evidence._canonical_json(malformed)
        )
        with self.assertRaises(recovery_evidence.RecoveryEvidenceError):
            recovery_evidence.verify_restore(malformed, malformed)

    def test_explicit_environment_contract_rejects_static_credentials(self):
        with mock.patch.dict(
            os.environ,
            {
                "NOTEAI_PRIVATE_STORAGE_BACKEND": "aliyun_oss",
                "NOTEAI_OSS_PRIVATE_BUCKET": "noteai-private-test",
                "NOTEAI_OSS_REGION": "cn-shanghai",
                "NOTEAI_OSS_ENDPOINT": "https://oss-cn-shanghai-internal.aliyuncs.com",
                "NOTEAI_OSS_RAM_ROLE": "noteai-api-role",
                "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH": "epoch-1",
                "ALIBABA_CLOUD_ACCESS_KEY_ID": "prohibited",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "static OSS credentials"):
                private_storage.configure_from_environment()

    def test_recovery_cli_initializes_oss_only_for_object_inventory(self):
        with mock.patch.object(
            recovery_evidence_tool.private_storage,
            "configure_from_environment",
            return_value=True,
        ) as configure:
            recovery_evidence_tool._configure_object_inventory(
                database_only=False
            )
            recovery_evidence_tool._configure_object_inventory(
                database_only=True
            )

        configure.assert_called_once_with()

    def test_recovery_cli_rejects_missing_oss_for_object_inventory(self):
        with mock.patch.object(
            recovery_evidence_tool.private_storage,
            "configure_from_environment",
            return_value=False,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "private OSS configuration is required",
            ):
                recovery_evidence_tool._configure_object_inventory(
                    database_only=False
                )

    def test_explicit_ram_role_environment_builds_without_fetching_credentials(self):
        private_storage.reset_object_backend()
        durable_ai.reset_payload_store()
        try:
            with mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_PRIVATE_STORAGE_BACKEND": "aliyun_oss",
                    "NOTEAI_OSS_PRIVATE_BUCKET": "noteai-private-test",
                    "NOTEAI_OSS_REGION": "cn-shanghai",
                    "NOTEAI_OSS_ENDPOINT": "https://oss-cn-shanghai-internal.aliyuncs.com",
                    "NOTEAI_OSS_RAM_ROLE": "noteai-api-role",
                    "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH": "epoch-1",
                },
                clear=True,
            ), mock.patch(
                "alibabacloud_credentials.client.Client"
            ) as credential_client, mock.patch(
                "alibabacloud_oss_v2.Client"
            ):
                self.assertTrue(private_storage.configure_from_environment())
            credential_config = credential_client.call_args.args[0]
            self.assertTrue(credential_config.enable_imds_v2)
            self.assertTrue(credential_config.disable_imds_v1)
            self.assertEqual(credential_config.metadata_token_duration, 60)
            self.assertIsInstance(
                private_storage.get_object_backend(),
                private_storage.AliyunOssObjectBackend,
            )
            self.assertIsInstance(
                durable_ai.get_payload_store(),
                private_storage.PrivateObjectPayloadStore,
            )
        finally:
            private_storage.configure_object_backend(
                self.backend,
                key_epoch="isolated-test-epoch-1",
            )
            durable_ai.configure_payload_store(self.payload_store)

    def test_public_or_plaintext_oss_endpoint_is_rejected(self):
        for endpoint in (
            "http://oss-cn-shanghai-internal.aliyuncs.com",
            "https://oss-cn-shanghai.aliyuncs.com",
            "https://oss-cn-beijing-internal.aliyuncs.com",
        ):
            with self.subTest(endpoint=endpoint), mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_PRIVATE_STORAGE_BACKEND": "aliyun_oss",
                    "NOTEAI_OSS_PRIVATE_BUCKET": "noteai-private-test",
                    "NOTEAI_OSS_REGION": "cn-shanghai",
                    "NOTEAI_OSS_ENDPOINT": endpoint,
                    "NOTEAI_OSS_RAM_ROLE": "noteai-api-role",
                    "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH": "epoch-1",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "regional internal HTTPS endpoint",
                ):
                    private_storage.configure_from_environment()

    def test_official_oss_adapter_uses_conditional_encrypted_requests(self):
        import alibabacloud_oss_v2 as oss

        class WrappedSdkError(Exception):
            def __init__(self, inner):
                super().__init__("wrapped")
                self.inner = inner

            def unwrap(self):
                return self.inner

        class NotFoundError(Exception):
            status_code = 404

        class FakeClient:
            def __init__(self):
                self.objects = {}
                self.put_request = None

            def put_object(self, request):
                self.put_request = request
                self.objects[request.key] = (
                    bytes(request.body),
                    dict(request.metadata),
                )

            def get_object(self, request):
                body, metadata = self.objects[request.key]
                return oss.GetObjectResult(
                    content_length=len(body),
                    metadata=metadata,
                    body=io.BytesIO(body),
                )

            def head_object(self, request):
                body, metadata = self.objects[request.key]
                return oss.HeadObjectResult(
                    content_length=len(body),
                    metadata=metadata,
                )

            def delete_object(self, request):
                self.objects.pop(request.key, None)

            def list_objects_v2(self, request):
                values = [
                    SimpleNamespace(key=key)
                    for key in sorted(self.objects)
                    if key.startswith(request.prefix)
                ][: request.max_keys]
                return oss.ListObjectsV2Result(
                    contents=values,
                    is_truncated=False,
                )

        client = FakeClient()
        backend = private_storage.AliyunOssObjectBackend(
            client=client,
            bucket="noteai-private-test",
            kms_key_id="kms-test-key",
        )
        self.assertEqual(
            backend._status(WrappedSdkError(NotFoundError())),
            404,
        )
        reference_id = str(uuid.uuid4())
        subject_hash = "c" * 64
        body = self.jpeg("oss")
        key = f"v1/media/image/{subject_hash[:12]}/{reference_id}.bin"
        metadata = private_storage._object_metadata(
            reference_id=reference_id,
            subject_hash=subject_hash,
            purpose="image",
            content_sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            item_count=1,
            expires_at=(self.now + timedelta(days=1)).isoformat(),
            created_at=self.now.isoformat(),
            key_epoch_hash="d" * 64,
        )
        self.assertTrue(
            backend.put_if_absent(
                key,
                body,
                content_type="image/jpeg",
                metadata=metadata,
            )
        )
        request = client.put_request
        self.assertTrue(request.forbid_overwrite)
        self.assertTrue(request.metadata)
        self.assertTrue(
            all(
                re.fullmatch(r"[a-z][a-z0-9-]{0,31}", key)
                for key in request.metadata
            )
        )
        self.assertFalse(any("_" in key for key in request.metadata))
        self.assertEqual(request.server_side_encryption, "KMS")
        self.assertIsNone(request.server_side_data_encryption)
        self.assertEqual(
            request.server_side_encryption_key_id,
            "kms-test-key",
        )
        restored, restored_metadata = backend.get(key, max_bytes=100)
        self.assertEqual(restored, body)
        self.assertEqual(restored_metadata["reference_id"], reference_id)
        listed, cursor = backend.list("v1/media", limit=10)
        self.assertEqual(len(listed), 1)
        self.assertIsNone(cursor)
        self.assertEqual(listed[0].key, key)
        self.assertTrue(backend.delete(key))
        self.assertEqual(client.objects, {})


if __name__ == "__main__":
    unittest.main()
