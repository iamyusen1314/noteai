"""Configured transport must work for small videos without replaying originals."""
import hashlib
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'model'))
import ark_media
import idempotency
import private_storage as storage
import public_product


class VideoTransportSelectionTests(unittest.TestCase):
    def setUp(self):
        self.body = b'unchanged-original-video-and-audio'
        self.ref = SimpleNamespace(id='11111111-1111-4111-8111-111111111111',
            subject_hash=idempotency.operation_subject_hash('fixture-owner'),
            purpose='video', content_type='video/quicktime',
            content_sha256=hashlib.sha256(self.body).hexdigest())
        self.row = {'state': 'ready', 'ark_state': 'none', 'ark_call_hash': None,
            'expires_at': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        self.backend = mock.Mock(spec=storage.AliyunOssObjectBackend)
        self.backend.video_read_url.return_value = 'https://synthetic.invalid/original?private=fixture'
        self.marker = public_product._invocation.set(public_product.Invocation('fixture-owner','one-request'))
        self.env = mock.patch.dict(os.environ, {'NOTEAI_ARK_API_KEY':'synthetic',
            'NOTEAI_ARK_VIDEO_INPUT':'private_oss'})
        self.env.start()
        self.patches = [mock.patch.object(public_product, 'assert_media_result_known'),
            mock.patch.object(storage.db, 'fetchone', return_value=self.row),
            mock.patch.object(storage, 'get_object_backend', return_value=self.backend),
            mock.patch.object(ark_media, 'video', return_value='complete audio/video observation'),
            mock.patch.object(ark_media, 'upload_video')]
        self.guard, self.read, self.get_backend, self.video, self.upload = [p.start() for p in self.patches]

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        self.env.stop()
        public_product._invocation.reset(self.marker)

    def run_video(self):
        return storage.understand_original_video(self.ref, self.body, 'understand the original')

    def test_private_oss_small_video_uses_original_link_once(self):
        self.assertEqual(self.run_video(), 'complete audio/video observation')
        self.video.assert_called_once()
        parts = self.video.call_args.args[1]
        self.assertEqual(parts, [{'type':'input_video', 'video_url':self.backend.video_read_url.return_value, 'fps':2.0}])
        self.assertEqual(self.video.call_args.kwargs['media'],
            {'ref':self.ref.id, 'sha256':self.ref.content_sha256, 'transport':'private_oss'})
        self.backend.video_read_url.assert_called_once_with(self.ref)
        self.upload.assert_not_called()

    def test_existing_default_small_video_keeps_original_inline_contract(self):
        with mock.patch.dict(os.environ, {'NOTEAI_ARK_VIDEO_INPUT':'files'}): self.run_video()
        part = self.video.call_args.args[1][0]
        self.assertTrue(part['video_url'].startswith('data:video/quicktime;base64,'))
        self.assertEqual(self.video.call_args.kwargs['media']['transport'], 'inline')
        self.get_backend.assert_not_called()

    def test_pending_original_blocks_before_signing_or_inference(self):
        self.guard.side_effect = public_product.TrialProviderStopped('PUBLIC_MEDIA_RESULT_UNCONFIRMED_NO_REPLAY')
        with self.assertRaises(public_product.TrialProviderStopped): self.run_video()
        self.backend.video_read_url.assert_not_called()
        self.video.assert_not_called()

    def test_unknown_prior_files_inference_is_not_bypassed(self):
        self.row.update(ark_state='unknown', ark_call_hash='original-call')
        with self.assertRaises(storage.MediaReferenceUnavailable): self.run_video()
        self.backend.video_read_url.assert_not_called()
        self.video.assert_not_called()

    def test_signing_failure_does_not_silently_fallback_or_resend(self):
        self.backend.video_read_url.side_effect = storage.ObjectStorageUnavailable('PRIVATE_VIDEO_SIGNING_UNAVAILABLE')
        with self.assertRaises(storage.ObjectStorageUnavailable): self.run_video()
        self.video.assert_not_called()
        self.upload.assert_not_called()

    def test_source_bytes_mismatch_never_signs_or_calls(self):
        with self.assertRaises(storage.MediaReferenceUnavailable):
            storage.understand_original_video(self.ref, b'different', 'understand')
        self.backend.video_read_url.assert_not_called()
        self.video.assert_not_called()


if __name__ == '__main__': unittest.main()
