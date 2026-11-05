"""Owner-bound metadata only; isolated SQLite and no object/backend reads."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import db
import private_storage as storage


class VideoReferenceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1"})
        self.environment.start()
        self.temporary = tempfile.TemporaryDirectory()
        self.previous = db._DB_PATH
        db._DB_PATH = Path(self.temporary.name) / "video-metadata.sqlite"
        db.init_db()
        self.now = datetime.now(timezone.utc)
        self.user = "metadata-owner"
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)", (self.user, self.user, self.user + "@example.invalid",
                                   "fixture", "fixture", self.now.isoformat()))
        self.backend = storage.InMemoryObjectBackend()
        storage.configure_object_backend(self.backend, key_epoch="isolated-video-metadata")
        self.body = b"synthetic original video metadata fixture"
        self.reference = storage.store_media_bytes(self.user, purpose="video", content_type="video/mp4",
            payload=self.body, item_count=1, ttl_seconds=60, now=self.now)
        self.no_io = ExitStack()
        for name in ("get", "head", "put_if_absent", "delete", "list"):
            self.no_io.enter_context(mock.patch.object(self.backend, name,
                side_effect=AssertionError("Object backend I/O forbidden during metadata lookup")))
        self.no_io.enter_context(mock.patch.object(storage, "get_object_backend",
            side_effect=AssertionError("Metadata lookup must not select an object backend")))

    def tearDown(self):
        self.no_io.close()
        storage.reset_object_backend()
        db._DB_PATH = self.previous
        self.temporary.cleanup()
        self.environment.stop()

    def test_owner_video_metadata_exposes_exact_size_without_any_backend_io(self):
        for purpose in (None, "video"):
            with self.subTest(purpose=purpose):
                reference = storage.get_ready_media_reference(self.reference.id,
                    user_id=self.user, purpose=purpose, now=self.now + timedelta(seconds=1))
                self.assertIsInstance(reference, storage.MediaReference)
                self.assertEqual(reference.database_values(), self.reference.database_values())
                self.assertEqual(reference.size_bytes, len(self.body))
                self.assertFalse(reference.created)
        self.assertEqual(db.fetchone("SELECT count(*) AS n FROM private_media_refs")["n"], 1)

    def test_original_owner_purpose_expiry_and_uuid_contracts_remain_closed(self):
        for arguments in (
                {"user_id": "different-owner", "purpose": "video", "now": self.now},
                {"user_id": self.user, "purpose": "image", "now": self.now},
                {"user_id": self.user, "purpose": "video", "now": self.now + timedelta(seconds=60)},
                {"user_id": self.user, "purpose": "video", "now": self.now + timedelta(seconds=61)}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(storage.MediaReferenceUnavailable):
                    storage.get_ready_media_reference(self.reference.id, **arguments)
        with self.assertRaises(storage.MediaReferenceUnavailable):
            storage.get_ready_media_reference(str(uuid.uuid4()), user_id=self.user)
        with self.assertRaises(ValueError):
            storage.get_ready_media_reference("not-a-uuid", user_id=self.user)
        with self.assertRaises(ValueError):
            storage.get_ready_media_reference(self.reference.id, user_id=self.user,
                now=self.now.replace(tzinfo=None))

    def test_nonready_reference_is_unavailable_without_touching_retained_object(self):
        before = dict(db.fetchone("SELECT * FROM private_media_refs WHERE id=?", (self.reference.id,)))
        db.execute("UPDATE private_media_refs SET state='expired',deleted_at=? WHERE id=?",
            (self.now.isoformat(), self.reference.id))
        with self.assertRaises(storage.MediaReferenceUnavailable):
            storage.get_ready_media_reference(self.reference.id, user_id=self.user, purpose="video", now=self.now)
        row = dict(db.fetchone("SELECT * FROM private_media_refs WHERE id=?", (self.reference.id,)))
        self.assertEqual(row, {**before, "state": "expired", "deleted_at": self.now.isoformat()})
        self.assertEqual(len(self.backend._objects), 1)


if __name__ == "__main__":
    unittest.main()
