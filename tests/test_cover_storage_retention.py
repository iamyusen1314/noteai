"""Offline cover-key isolation/legacy-reference checks; no cloud/model calls."""
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import unittest
import uuid
from unittest import mock

from tests import test_cover_jobs as fixtures
from tests import test_cover_agent_artifacts as artifact_fixtures

import cover_agent_artifacts
import db
import durable_ai
import private_storage


class CoverStorageRetentionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CoverJobsTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def legacy_media(self):
        """An old immutable flat key/hash remains readable without fallback."""
        original = private_storage._media_key
        def legacy_key(reference_id, subject_hash, purpose, **kwargs):
            return original(reference_id, subject_hash, purpose)
        with mock.patch.object(private_storage, "_media_key", side_effect=legacy_key):
            return self.fixture.image(self.fixture.user)

    def test_cover_png_isolated_temporary_and_default_payload_keys_unchanged(self):
        source = self.fixture.source
        source_key = private_storage._media_key(source.id, source.subject_hash, "image")
        self.assertEqual(source_key, f"v1/media/image/{source.subject_hash[:12]}/{source.id}.bin")
        self.assertEqual(private_storage._reference_key(source), source_key)
        self.assertEqual(source.object_key_hash, hashlib.sha256(source_key.encode()).hexdigest())
        cover = self.fixture.image(self.fixture.user)
        cover_key = private_storage._reference_key(cover)
        self.assertEqual(cover_key, f"v1/media/image/cover_3d_v1/{cover.subject_hash[:12]}/{cover.id}.bin")
        backend = private_storage.AliyunOssObjectBackend(client=object(), bucket="offline-cover-test")
        self.assertEqual(backend._remote_key(cover_key), "noteai-private/" + cover_key)
        self.assertEqual((datetime.fromisoformat(cover.expires_at)
            - datetime.fromisoformat(cover.created_at)).total_seconds(), 3 * 86400)
        for purpose in ("request", "result"):
            ref = private_storage.PrivateObjectPayloadStore().put(operation_id=str(uuid.uuid4()),
                user_id=self.fixture.user, purpose=purpose, payload=b'{"temporary":true}',
                item_count=1, ttl_seconds=86400)
            key = private_storage._reference_key(ref, payload=True)
            self.assertEqual(key, f"v1/payload/{purpose}/{ref.subject_hash[:12]}/{ref.id}.json")
        for prefix in ("v1/media/image/cover_v1", "v1/payload/result/cover_v1"):
            self.assertEqual(private_storage._object_prefix(prefix), prefix + "/")
        for item in self.fixture.backend.list("v1", limit=100)[0]:
            private_storage.validate_stored_object_descriptor(item)
        with self.assertRaises(ValueError):
            private_storage._object_key(f"v1/media/video/cover_v1/{cover.subject_hash[:12]}/{cover.id}.bin")
        with self.assertRaises(ValueError):
            private_storage._payload_key(cover.id, cover.subject_hash, "request", lifecycle="cover_v1")

    def test_new_and_legacy_media_reopen_expire_and_account_delete(self):
        current = self.fixture.image(self.fixture.user)
        legacy = self.legacy_media()
        for ref in (current, legacy):
            read, body = private_storage.load_media_bytes(ref.id, user_id=self.fixture.user)
            self.assertEqual(read.object_key_hash, ref.object_key_hash)
            self.assertEqual(hashlib.sha256(body).hexdigest(), ref.content_sha256)
        private_storage.expire_media(now=self.fixture.now + timedelta(days=2))
        self.assertIsNone(self.fixture.backend.head(private_storage._reference_key(self.fixture.source)))
        for ref in (current, legacy):
            self.assertIsNotNone(self.fixture.backend.head(private_storage._reference_key(ref)))
        private_storage.expire_media(user_id=self.fixture.user, now=self.fixture.now + timedelta(days=4))
        for ref in (current, legacy):
            self.assertIsNone(self.fixture.backend.head(private_storage._reference_key(ref)))
        remaining = [self.fixture.image(self.fixture.user), self.legacy_media()]
        private_storage.delete_user_media(self.fixture.user)
        for ref in remaining:
            self.assertIsNone(self.fixture.backend.head(private_storage._reference_key(ref)))

    def test_media_hash_selects_one_key_and_never_falls_back_after_missing_object(self):
        ref = self.fixture.image(self.fixture.user)
        current = private_storage._reference_key(ref)
        legacy = private_storage._media_key(ref.id, ref.subject_hash, ref.purpose)
        body, metadata = self.fixture.backend.get(current, max_bytes=private_storage.MAX_IMAGE_BYTES)
        self.fixture.backend.put_if_absent(legacy, body, content_type=ref.content_type, metadata=metadata)
        self.fixture.backend.delete(current)
        with mock.patch.object(self.fixture.backend, "get", wraps=self.fixture.backend.get) as read:
            with self.assertRaises(private_storage.PrivateStorageError):
                private_storage.load_media_bytes(ref.id, user_id=self.fixture.user)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(read.call_args.args[0], current)
        row = dict(db.fetchone("SELECT * FROM private_media_refs WHERE id=?", (ref.id,)))
        with mock.patch.object(db, "fetchone", return_value={**row, "object_key_hash": "0" * 64}), \
                mock.patch.object(self.fixture.backend, "get", wraps=self.fixture.backend.get) as read:
            with self.assertRaises(private_storage.MediaReferenceUnavailable):
                private_storage.load_media_bytes(ref.id, user_id=self.fixture.user)
        read.assert_not_called()
        with self.assertRaises(private_storage.MediaReferenceUnavailable):
            private_storage.load_media_bytes(ref.id, user_id=self.fixture.other)

    def test_payload_old_new_hash_binding_and_delete(self):
        store = private_storage.PrivateObjectPayloadStore()
        for lifecycle in ("temporary", "cover_v1", "cover_3d_v1"):
            ref = store.put(operation_id=str(uuid.uuid4()), user_id=self.fixture.user,
                purpose="result", payload=b'{"design":true}', item_count=1,
                ttl_seconds=(3 if lifecycle == "cover_3d_v1" else 90) * 86400, lifecycle=lifecycle)
            key = private_storage._reference_key(ref, payload=True)
            self.assertEqual("/" + lifecycle + "/" in key, lifecycle != "temporary")
            self.assertEqual(store.get(ref, user_id=self.fixture.user), b'{"design":true}')
            with mock.patch.object(self.fixture.backend, "get", wraps=self.fixture.backend.get) as read:
                with self.assertRaises(durable_ai.PayloadUnavailable):
                    store.get(replace(ref, object_key_hash="0" * 64), user_id=self.fixture.user)
            read.assert_not_called()
            with self.assertRaises(durable_ai.PayloadUnavailable):
                store.get(ref, user_id=self.fixture.other)
            self.assertTrue(store.delete(ref, user_id=self.fixture.user))
            self.assertIsNone(self.fixture.backend.head(key))
        ref = store.put(operation_id=str(uuid.uuid4()), user_id=self.fixture.user,
            purpose="result", payload=b'{}', item_count=1, ttl_seconds=86400, lifecycle="cover_v1")
        current = private_storage._reference_key(ref, payload=True)
        old_key = private_storage._payload_key(ref.id, ref.subject_hash, ref.purpose)
        body, metadata = self.fixture.backend.get(current, max_bytes=100)
        self.fixture.backend.put_if_absent(old_key, body, content_type="application/json", metadata=metadata)
        self.fixture.backend.delete(current)
        with mock.patch.object(self.fixture.backend, "get", wraps=self.fixture.backend.get) as read:
            with self.assertRaises(durable_ai.PayloadUnavailable):
                store.get(ref, user_id=self.fixture.user)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(read.call_args.args[0], current)


class LegacyEditableBundleTests(unittest.TestCase):
    def test_legacy_bundle_pending_and_revision_delete_without_descriptor_update(self):
        flow = artifact_fixtures.AgentArtifactTests()
        flow.setUp()
        try:
            old_put = private_storage.PrivateObjectPayloadStore.put
            def legacy_put(store, **kwargs):
                kwargs.pop("lifecycle", None)
                return old_put(store, **kwargs)
            with mock.patch.object(private_storage.PrivateObjectPayloadStore, "put", new=legacy_put):
                task, _, _, bundle, layout, _ = flow.complete()
            balances = flow.fixture.balances()
            self.assertEqual(cover_agent_artifacts.validate_saved(flow.fixture.user, layout), bundle)
            old_ref = cover_agent_artifacts.reference(layout["editable_ref"])
            self.assertNotIn("/cover_v1/", private_storage._reference_key(old_ref, payload=True))
            pending = cover_agent_artifacts.store(flow.fixture.user, task["job_id"], bundle, revision=2)
            self.assertIn("/cover_3d_v1/", private_storage._reference_key(
                cover_agent_artifacts.reference(pending), payload=True))
            private_storage.reconcile_orphans(prefix="v1/payload", now=flow.fixture.now + timedelta(days=2), apply=True)
            self.assertEqual(cover_agent_artifacts.load(flow.fixture.user, layout), bundle)
            revision = db.fetchone("SELECT layout_json FROM cover_asset_revisions WHERE job_id=? AND revision=1",
                (task["job_id"],))["layout_json"]
            original_design = json.loads(db.fetchone("SELECT design_json FROM cover_jobs WHERE id=?",
                (task["job_id"],))["design_json"])
            self.assertEqual(len(original_design["editable_pending_refs"]), 2)
            private_storage.delete_user_media(flow.fixture.user)
            for descriptor in original_design["editable_pending_refs"].values():
                ref = cover_agent_artifacts.reference(descriptor)
                self.assertIsNone(flow.fixture.backend.head(private_storage._reference_key(ref, payload=True)))
            self.assertEqual(db.fetchone("SELECT layout_json FROM cover_asset_revisions WHERE job_id=? AND revision=1",
                (task["job_id"],))["layout_json"], revision)
            self.assertEqual(flow.fixture.balances(), balances)
        finally:
            flow.tearDown()
