"""Offline cover source-contract tests; no provider or production calls."""

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_sources


class CoverSourceReferencesTests(unittest.TestCase):
    def setUp(self):
        self.refs = [str(uuid.uuid4()) for _ in range(10)]

    def test_single_and_nine_images_keep_order_without_duplicate(self):
        self.assertEqual(cover_sources.normalize_source_refs([self.refs[0]]), self.refs[:1])
        self.assertEqual(cover_sources.normalize_source_refs(self.refs[:9]), self.refs[:9])
        self.assertEqual(
            cover_sources.normalize_source_refs([self.refs[0].upper(), self.refs[0], self.refs[1]]),
            self.refs[:2],
        )

    def test_invalid_sources_cannot_become_public_urls_or_inline_images(self):
        for value in [
            self.refs, self.refs[0], {"media_ref": self.refs[0]},
            ["https://example.invalid/image.jpg"], ["data:image/jpeg;base64,Zm9v"],
            ["Zm9v"], [self.refs[0].replace("-", "")], [None], [1],
        ]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(cover_sources.CoverSourceValidationError):
                    cover_sources.normalize_source_refs(value)
                self.assertEqual(cover_sources.project_source_refs(value), [])

    def test_inputs_extract_only_recoverable_refs_and_honor_generation_precedence(self):
        self.assertEqual(cover_sources.source_refs_from_inputs(
            cover_image=self.refs[9], cover_images=self.refs[:9]), self.refs[:9])
        self.assertEqual(cover_sources.source_refs_from_inputs(
            cover_image=self.refs[0], extra_images=self.refs[1:9]), self.refs[:9])
        self.assertEqual(cover_sources.source_refs_from_inputs(
            cover_image="Zm9v", extra_images=["data:image/jpeg;base64,Zm9v", self.refs[1]]),
            self.refs[1:2])
        self.assertEqual(cover_sources.source_refs_from_inputs(cover_image="Zm9v"), [])

    def test_report_preserves_legacy_ten_image_diagnosis_without_silent_truncation(self):
        self.assertEqual(cover_sources.source_refs_from_inputs(
            cover_image=self.refs[0], extra_images=self.refs[1:]), self.refs)
        self.assertEqual(cover_sources.project_source_refs(self.refs, maximum=10), self.refs)
        self.assertEqual(cover_sources.normalize_source_refs(self.refs, maximum=10), self.refs)
        with self.assertRaises(cover_sources.CoverSourceValidationError):
            cover_sources.source_refs_from_inputs(cover_image=self.refs[0], extra_images=self.refs)
        with self.assertRaises(cover_sources.CoverSourceValidationError):
            cover_sources.normalize_source_refs(self.refs, maximum=11)

    def test_persisted_projection_is_strict_and_does_not_mutate(self):
        value = [self.refs[0], self.refs[0], self.refs[1]]
        self.assertEqual(cover_sources.project_source_refs(value), self.refs[:2])
        self.assertEqual(value, [self.refs[0], self.refs[0], self.refs[1]])
        self.assertEqual(cover_sources.project_source_refs(None), [])


class CoverSourceObservationMappingTests(unittest.TestCase):
    def setUp(self):
        self.refs = [str(uuid.uuid4()) for _ in range(10)]

    def test_mixed_inline_and_duplicate_inputs_keep_original_generation_indices(self):
        images = ["Zm9v", self.refs[0].upper(), "data:image/jpeg;base64,Zm9v",
                  self.refs[0], self.refs[1]]
        items = cover_sources.source_items_from_inputs(
            cover_image=self.refs[9], cover_images=images,
        )
        self.assertEqual(items, [
            {"input_field": "cover_images", "image_index": 2, "media_ref": self.refs[0]},
            {"input_field": "cover_images", "image_index": 4, "media_ref": self.refs[0]},
            {"input_field": "cover_images", "image_index": 5, "media_ref": self.refs[1]},
        ])
        self.assertEqual(cover_sources.source_refs_from_inputs(
            cover_image=self.refs[9], cover_images=images), self.refs[:2])
        self.assertEqual(cover_sources.project_source_items(items), items)

    def test_mixed_diagnosis_keeps_cover_and_extra_observation_positions_separate(self):
        items = cover_sources.source_items_from_inputs(
            cover_image=self.refs[0], extra_images=["Zm9v", self.refs[0], self.refs[2]],
        )
        self.assertEqual(items, [
            {"input_field": "cover_image", "image_index": 1, "media_ref": self.refs[0]},
            {"input_field": "extra_images", "image_index": 2, "media_ref": self.refs[0]},
            {"input_field": "extra_images", "image_index": 3, "media_ref": self.refs[2]},
        ])
        self.assertEqual(cover_sources.project_source_items(items), items)
        no_cover = cover_sources.source_items_from_inputs(
            cover_image="Zm9v", extra_images=[self.refs[0]],
        )
        self.assertEqual(no_cover, [
            {"input_field": "extra_images", "image_index": 1, "media_ref": self.refs[0]},
        ])

    def test_all_ten_diagnosis_originals_remain_addressable(self):
        items = cover_sources.source_items_from_inputs(
            cover_image=self.refs[0], extra_images=self.refs[1:],
        )
        self.assertEqual(len(items), 10)
        self.assertEqual(items[0], {
            "input_field": "cover_image", "image_index": 1, "media_ref": self.refs[0],
        })
        self.assertEqual(items[-1], {
            "input_field": "extra_images", "image_index": 9, "media_ref": self.refs[9],
        })
        self.assertEqual(cover_sources.project_source_items(items), items)
        for kwargs in [
            {"cover_images": self.refs},
            {"cover_image": self.refs[0], "extra_images": self.refs},
            {"cover_images": self.refs[:9], "extra_images": self.refs[:2]},
        ]:
            with self.assertRaises(cover_sources.CoverSourceValidationError):
                cover_sources.source_items_from_inputs(**kwargs)

    def test_invalid_mapping_fails_as_a_whole_without_unknown_key_passthrough(self):
        good = {"input_field": "cover_images", "image_index": 2, "media_ref": self.refs[0]}
        for bad in [
            {**good, "input_field": "video_file_id"},
            {**good, "input_field": []},
            {**good, "image_index": 0}, {**good, "image_index": 10},
            {**good, "image_index": True}, {**good, "image_index": "2"},
            {**good, "input_field": "cover_image", "image_index": 2},
            {**good, "media_ref": "https://example.invalid/a.jpg"},
            {**good, "media_ref": "Zm9v"},
            {**good, "supplier_url": "PRIVATE"},
            {"input_field": "cover_images", "media_ref": self.refs[0]},
            good, None,
        ]:
            with self.subTest(value_type=type(bad).__name__):
                self.assertEqual(cover_sources.project_source_items([good, bad]), [])
        self.assertEqual(cover_sources.project_source_items([good] * 11), [])
        self.assertEqual(cover_sources.project_source_items({"items": [good]}), [])
        self.assertEqual(cover_sources.project_source_items(None), [])
        self.assertEqual(good, {
            "input_field": "cover_images", "image_index": 2, "media_ref": self.refs[0],
        })


class CoverSourceInspectionContractTests(unittest.TestCase):
    """Check reader delegation separately from private-storage integration."""

    def setUp(self):
        self.refs = [str(uuid.uuid4()) for _ in range(9)]

        class StorageError(RuntimeError):
            def __init__(self, code="PRIVATE_STORAGE_UNAVAILABLE"):
                self.code = code

        class ReferenceUnavailable(StorageError):
            pass

        self.storage = SimpleNamespace(
            PrivateStorageError=StorageError,
            MediaReferenceUnavailable=ReferenceUnavailable,
            load_media_bytes=mock.Mock(side_effect=self.load),
        )
        self.module_patch = mock.patch.dict(sys.modules, {"private_storage": self.storage})
        self.module_patch.start()

    def tearDown(self):
        self.module_patch.stop()

    @staticmethod
    def load(reference_id, **_kwargs):
        return SimpleNamespace(
            id=reference_id, expires_at="2026-10-20T00:00:00+00:00", content_type="image/jpeg",
            object_key="PRIVATE", subject_hash="PRIVATE", ark_file_id="PRIVATE",
        ), b"PRIVATE IMAGE BYTES"

    def test_single_and_nine_verified_reads_use_owner_image_purpose_and_clock(self):
        for refs in [self.refs[:1], self.refs]:
            with self.subTest(count=len(refs)):
                self.storage.load_media_bytes.reset_mock()
                result = cover_sources.inspect_sources("owner-a", refs, now=None)
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["ready_count"], len(refs))
                self.assertEqual(self.storage.load_media_bytes.call_args_list, [
                    mock.call(ref, user_id="owner-a", purpose="image", now=None) for ref in refs
                ])
                self.assertNotIn("PRIVATE", repr(result))
                self.assertEqual(set(result["sources"][0]), {
                    "media_ref", "status", "expires_at", "content_type",
                })

    def test_missing_expired_wrong_owner_or_wrong_purpose_require_real_upload(self):
        self.storage.load_media_bytes.side_effect = self.storage.MediaReferenceUnavailable()
        result = cover_sources.inspect_sources("owner-a", self.refs[:1])
        self.assertEqual(result, {
            "status": "reupload_required", "ready_count": 0,
            "sources": [{"media_ref": self.refs[0], "status": "reupload_required"}],
        })

    def test_missing_object_is_reupload_but_outage_and_integrity_are_not_expiry(self):
        for code, expected in [
            ("PRIVATE_OBJECT_NOT_FOUND", "reupload_required"),
            ("PRIVATE_OBJECT_READ_FAILED", "storage_unavailable"),
            ("PRIVATE_OBJECT_HASH_MISMATCH", "storage_unavailable"),
        ]:
            with self.subTest(code=code):
                self.storage.load_media_bytes.side_effect = self.storage.PrivateStorageError(code)
                result = cover_sources.inspect_sources("owner-a", self.refs[:1])
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["ready_count"], 0)

    def test_partial_ready_set_is_explicit_and_cannot_claim_all_images_ready(self):
        self.storage.load_media_bytes.side_effect = [
            self.load(self.refs[0]), self.storage.MediaReferenceUnavailable(),
        ]
        result = cover_sources.inspect_sources("owner-a", self.refs[:2])
        self.assertEqual(result["status"], "reupload_required")
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual([source["status"] for source in result["sources"]], ["ready", "reupload_required"])

    def test_no_sources_means_reupload_without_storage_access(self):
        self.assertEqual(cover_sources.inspect_sources("owner-a", []), {
            "status": "reupload_required", "sources": [], "ready_count": 0,
        })
        self.storage.load_media_bytes.assert_not_called()

    def test_unauthenticated_and_invalid_refs_never_read_storage(self):
        for owner, refs in [("", self.refs[:1]), (None, self.refs[:1]), ("owner-a", ["https://x.invalid"])]:
            with self.subTest(owner=owner):
                with self.assertRaises(cover_sources.CoverSourceValidationError):
                    cover_sources.inspect_sources(owner, refs)
        self.storage.load_media_bytes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
