import hashlib
from http.client import BadStatusLine, IncompleteRead, InvalidURL, RemoteDisconnected
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import artifact_loader  # noqa: E402


class ChunkResponse:
    def __init__(self, events):
        self.events = list(events)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size):
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


class ModelArtifactDownloadRetryTests(unittest.TestCase):
    @staticmethod
    def owned_temps(target):
        return list(target.parent.glob(f".{target.name}.*.tmp"))

    def test_first_attempt_success_has_no_backoff_and_one_atomic_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact.bin"
            sleeps = []
            with mock.patch.object(
                artifact_loader,
                "urlopen",
                return_value=ChunkResponse([b"complete", b""]),
            ) as urlopen, mock.patch.object(
                artifact_loader.os,
                "replace",
                wraps=artifact_loader.os.replace,
            ) as replace:
                artifact_loader._download(
                    "https://example.invalid/artifact.bin",
                    target,
                    sleep=sleeps.append,
                )
            self.assertEqual(urlopen.call_count, 1)
            replace.assert_called_once()
            self.assertEqual(sleeps, [])
            self.assertEqual(target.read_bytes(), b"complete")
            self.assertEqual(self.owned_temps(target), [])

    def test_timeout_then_success_uses_one_fixed_backoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact.bin"
            legacy_tmp = target.with_suffix(target.suffix + ".tmp")
            legacy_tmp.write_bytes(b"not-owned-by-this-download")
            response = ChunkResponse([b"complete", b""])
            sleeps = []
            with mock.patch.object(
                artifact_loader,
                "urlopen",
                side_effect=[TimeoutError("sensitive timeout"), response],
            ) as urlopen:
                artifact_loader._download(
                    "https://user:secret@example.invalid/artifact.bin",
                    target,
                    sleep=sleeps.append,
                )

            self.assertEqual(urlopen.call_count, 2)
            self.assertEqual(
                sleeps,
                [artifact_loader.HTTP_DOWNLOAD_RETRY_DELAY_SECONDS],
            )
            self.assertEqual(target.read_bytes(), b"complete")
            self.assertEqual(
                legacy_tmp.read_bytes(), b"not-owned-by-this-download"
            )
            self.assertEqual(self.owned_temps(target), [])

    def test_retry_exhaustion_is_bounded_secret_free_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact.bin"
            target.write_bytes(b"existing")
            sleeps = []
            failures = [
                URLError("Bearer SECRET at private.example.invalid")
                for _ in range(artifact_loader.HTTP_DOWNLOAD_MAX_ATTEMPTS)
            ]
            with mock.patch.object(
                artifact_loader,
                "urlopen",
                side_effect=failures,
            ) as urlopen, self.assertRaises(RuntimeError) as caught:
                artifact_loader._download(
                    "https://user:secret@example.invalid/artifact.bin",
                    target,
                    sleep=sleeps.append,
                )

            self.assertEqual(
                urlopen.call_count,
                artifact_loader.HTTP_DOWNLOAD_MAX_ATTEMPTS,
            )
            self.assertEqual(
                sleeps,
                [artifact_loader.HTTP_DOWNLOAD_RETRY_DELAY_SECONDS]
                * (artifact_loader.HTTP_DOWNLOAD_MAX_ATTEMPTS - 1),
            )
            self.assertEqual(
                str(caught.exception),
                artifact_loader.HTTP_DOWNLOAD_FAILURE,
            )
            self.assertIsNone(caught.exception.__cause__)
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertEqual(self.owned_temps(target), [])

    def test_partial_tmp_is_removed_before_retry_and_target_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact.bin"
            target.write_bytes(b"existing")
            calls = 0

            def open_response(_url, *, timeout):
                nonlocal calls
                self.assertEqual(timeout, 60)
                calls += 1
                if calls == 1:
                    return ChunkResponse(
                        [b"partial", TimeoutError("sensitive mid-stream timeout")]
                    )
                self.assertEqual(len(self.owned_temps(target)), 1)
                return ChunkResponse([b"replacement", b""])

            def observe_backoff(delay):
                self.assertEqual(
                    delay,
                    artifact_loader.HTTP_DOWNLOAD_RETRY_DELAY_SECONDS,
                )
                self.assertEqual(self.owned_temps(target), [])
                self.assertEqual(target.read_bytes(), b"existing")

            with mock.patch.object(
                artifact_loader,
                "urlopen",
                side_effect=open_response,
            ):
                artifact_loader._download(
                    "https://example.invalid/artifact.bin",
                    target,
                    sleep=observe_backoff,
                )

            self.assertEqual(calls, 2)
            self.assertEqual(target.read_bytes(), b"replacement")
            self.assertEqual(self.owned_temps(target), [])

    def test_http_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact.bin"
            target.write_bytes(b"existing")
            sleeps = []
            error = HTTPError(
                "https://user:secret@example.invalid/artifact.bin",
                404,
                "private detail",
                None,
                None,
            )
            with mock.patch.object(
                error,
                "close",
                wraps=error.close,
            ) as close, mock.patch.object(
                artifact_loader,
                "urlopen",
                side_effect=error,
            ) as urlopen, self.assertRaises(RuntimeError) as caught:
                artifact_loader._download(
                    "https://user:secret@example.invalid/artifact.bin",
                    target,
                    sleep=sleeps.append,
                )

            self.assertEqual(urlopen.call_count, 1)
            close.assert_called_once_with()
            self.assertEqual(sleeps, [])
            self.assertEqual(
                str(caught.exception),
                artifact_loader.HTTP_DOWNLOAD_FAILURE,
            )
            self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertEqual(self.owned_temps(target), [])

    def test_transient_http_status_is_retried_but_auth_status_is_not(self):
        cases = [
            *((code, 2) for code in sorted(artifact_loader.HTTP_DOWNLOAD_RETRY_STATUSES)),
            (401, 1),
            (403, 1),
            (404, 1),
        ]
        for code, expected_calls in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "artifact.bin"
                target.write_bytes(b"existing")
                error = HTTPError(
                    "https://example.invalid/artifact.bin",
                    code,
                    "status",
                    None,
                    None,
                )
                events = [error, ChunkResponse([b"replacement", b""])]
                sleeps = []
                with mock.patch.object(
                    artifact_loader,
                    "urlopen",
                    side_effect=events,
                ) as urlopen:
                    if code in artifact_loader.HTTP_DOWNLOAD_RETRY_STATUSES:
                        artifact_loader._download(
                            "https://example.invalid/artifact.bin",
                            target,
                            sleep=sleeps.append,
                        )
                        self.assertEqual(target.read_bytes(), b"replacement")
                    else:
                        with self.assertRaises(RuntimeError):
                            artifact_loader._download(
                                "https://example.invalid/artifact.bin",
                                target,
                                sleep=sleeps.append,
                            )
                        self.assertEqual(target.read_bytes(), b"existing")
                self.assertEqual(urlopen.call_count, expected_calls)
                self.assertEqual(len(sleeps), expected_calls - 1)
                self.assertEqual(self.owned_temps(target), [])

    def test_midstream_disconnect_classes_retry_and_clean_owned_temp(self):
        failures = (
            IncompleteRead(b"partial", 100),
            RemoteDisconnected("remote closed"),
            ConnectionResetError("connection reset"),
        )
        for failure in failures:
            with self.subTest(kind=type(failure).__name__), \
                    tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "artifact.bin"
                target.write_bytes(b"existing")
                with mock.patch.object(
                    artifact_loader,
                    "urlopen",
                    side_effect=[
                        ChunkResponse([b"partial", failure]),
                        ChunkResponse([b"complete", b""]),
                    ],
                ) as urlopen:
                    artifact_loader._download(
                        "https://example.invalid/artifact.bin",
                        target,
                        sleep=lambda _delay: None,
                    )
                self.assertEqual(urlopen.call_count, 2)
                self.assertEqual(target.read_bytes(), b"complete")
                self.assertEqual(self.owned_temps(target), [])

    def test_non_transient_http_protocol_errors_are_fixed_and_not_retried(self):
        failures = (
            InvalidURL("SECRET credential in malformed URL"),
            BadStatusLine("SECRET response detail"),
        )
        for failure in failures:
            with self.subTest(kind=type(failure).__name__), \
                    tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "artifact.bin"
                target.write_bytes(b"existing")
                sleeps = []
                with mock.patch.object(
                    artifact_loader,
                    "urlopen",
                    side_effect=failure,
                ) as urlopen, self.assertRaises(RuntimeError) as caught:
                    artifact_loader._download(
                        "https://example.invalid/artifact.bin",
                        target,
                        sleep=sleeps.append,
                    )

                self.assertEqual(urlopen.call_count, 1)
                self.assertEqual(sleeps, [])
                self.assertEqual(
                    str(caught.exception), artifact_loader.HTTP_DOWNLOAD_FAILURE
                )
                self.assertIsNone(caught.exception.__cause__)
                self.assertNotIn("SECRET", str(caught.exception))
                self.assertEqual(target.read_bytes(), b"existing")
                self.assertEqual(self.owned_temps(target), [])

    def test_local_atomic_replace_error_is_not_retried_and_cleans_owned_temp(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact.bin"
            target.write_bytes(b"existing")
            sleeps = []
            with mock.patch.object(
                artifact_loader,
                "urlopen",
                return_value=ChunkResponse([b"complete", b""]),
            ) as urlopen, mock.patch.object(
                artifact_loader.os,
                "replace",
                side_effect=OSError("local replace failure"),
            ) as replace, self.assertRaises(RuntimeError) as caught:
                artifact_loader._download(
                    "https://example.invalid/artifact.bin",
                    target,
                    sleep=sleeps.append,
                )
            self.assertEqual(urlopen.call_count, 1)
            replace.assert_called_once()
            self.assertEqual(sleeps, [])
            self.assertEqual(
                str(caught.exception), artifact_loader.HTTP_DOWNLOAD_FAILURE
            )
            self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertEqual(self.owned_temps(target), [])

    def test_local_parent_creation_error_is_fixed_and_does_not_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "missing" / "artifact.bin"
            sleeps = []
            with mock.patch.object(
                artifact_loader.Path,
                "mkdir",
                side_effect=OSError("sensitive local path detail"),
            ) as mkdir, mock.patch.object(
                artifact_loader,
                "urlopen",
            ) as urlopen, self.assertRaises(RuntimeError) as caught:
                artifact_loader._download(
                    "https://example.invalid/artifact.bin",
                    target,
                    sleep=sleeps.append,
                )

            mkdir.assert_called_once_with(parents=True, exist_ok=True)
            urlopen.assert_not_called()
            self.assertEqual(sleeps, [])
            self.assertEqual(
                str(caught.exception), artifact_loader.HTTP_DOWNLOAD_FAILURE
            )
            self.assertIsNone(caught.exception.__cause__)
            self.assertFalse(target.exists())

    def test_downloaded_bytes_still_require_manifest_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "artifact.bin"
            manifest = base / "manifest.json"
            raw_path = "model/artifacts/artifact.bin"
            manifest.write_text(
                json.dumps(
                    {
                        "release": "test",
                        "run_id": "retry-checksum",
                        "artifacts": [
                            {
                                "path": raw_path,
                                "sha256": hashlib.sha256(b"expected").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def write_invalid(_url, destination):
                self.assertEqual(destination, target)
                destination.write_bytes(b"invalid")

            with mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_MODEL_ARTIFACT_S3_BUCKET": "",
                    "NOTEAI_MODEL_ARTIFACT_S3_PREFIX": "",
                },
                clear=False,
            ), mock.patch.object(
                artifact_loader,
                "_target_path",
                return_value=target,
            ), mock.patch.object(
                artifact_loader,
                "_download",
                side_effect=write_invalid,
            ) as download, self.assertRaisesRegex(
                RuntimeError,
                "model artifacts missing or checksum mismatch",
            ):
                artifact_loader.ensure_model_artifacts(
                    manifest,
                    "https://example.invalid/base",
                    required=True,
                )

            download.assert_called_once()
            self.assertEqual(target.read_bytes(), b"invalid")


if __name__ == "__main__":
    unittest.main()
