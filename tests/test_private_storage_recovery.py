import asyncio
import hashlib
import importlib
import io
import json
import os
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
        Image.new("RGBA", (4, 3), (255, 0, 0, 128)).save(
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
            self.assertEqual(restored.size, (4, 3))
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
            ):
                self.assertTrue(private_storage.configure_from_environment())
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
