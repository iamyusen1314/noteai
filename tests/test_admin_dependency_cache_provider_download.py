from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_provider_download as verifier  # noqa: E402


class AdminDependencyCacheProviderDownloadTests(unittest.TestCase):
    def _write_zip(self, root: Path, name: str = "manifest.json") -> Path:
        path = root / "artifact.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(name, b"{}")
        return path

    def _write_metadata(
        self,
        root: Path,
        artifact_zip: Path,
        *,
        artifact_id: int = 123,
    ) -> Path:
        digest = hashlib.sha256(artifact_zip.read_bytes()).hexdigest()
        api_url = (
            "https://api.github.com/repos/iamyusen1314/noteai/"
            f"actions/artifacts/{artifact_id}"
        )
        payload = {
            "id": artifact_id,
            "name": verifier.ARTIFACT_NAME,
            "expired": False,
            "size_in_bytes": artifact_zip.stat().st_size,
            "digest": "sha256:" + digest,
            "url": api_url,
            "archive_download_url": api_url + "/zip",
            "created_at": "2026-07-31T00:00:00Z",
            "expires_at": "2026-08-01T00:00:00Z",
            "workflow_run": {
                "id": 456,
                "head_sha": "a" * 40,
            },
        }
        path = root / "metadata.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_provider_metadata_binds_authenticated_digest_size_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_zip = self._write_zip(root)
            metadata = self._write_metadata(root, artifact_zip)
            summary = verifier.validate_provider_metadata(
                metadata,
                artifact_zip,
                expected_control_commit="a" * 40,
                expected_artifact_id=123,
            )
            self.assertEqual(summary["artifact_id"], 123)
            self.assertEqual(summary["run_id"], 456)
            with artifact_zip.open("ab") as output:
                output.write(b"tamper")
            with self.assertRaisesRegex(verifier.DownloadError, "size changed"):
                verifier.validate_provider_metadata(
                    metadata,
                    artifact_zip,
                    expected_control_commit="a" * 40,
                    expected_artifact_id=123,
                )

    def test_provider_metadata_preflight_rejects_oversize_without_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_zip = self._write_zip(root)
            metadata = self._write_metadata(root, artifact_zip)
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            payload["size_in_bytes"] = verifier.MAXIMUM_PROVIDER_ARTIFACT_BYTES + 1
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                verifier.DownloadError,
                "artifact size invalid",
            ):
                verifier.validate_provider_metadata_preflight(
                    metadata,
                    expected_control_commit="a" * 40,
                    expected_artifact_id=123,
                )

    def test_provider_metadata_accepts_exactly_one_day_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_zip = self._write_zip(root)
            metadata = self._write_metadata(root, artifact_zip)
            summary = verifier.validate_provider_metadata_preflight(
                metadata,
                expected_control_commit="a" * 40,
                expected_artifact_id=123,
            )
            self.assertEqual(summary["expires_at"], "2026-08-01T00:00:00Z")

    def test_provider_metadata_rejects_retention_over_one_day(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_zip = self._write_zip(root)
            metadata = self._write_metadata(root, artifact_zip)
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            payload["expires_at"] = "2026-08-01T00:00:01Z"
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                verifier.DownloadError,
                "retention exceeds reviewed window",
            ):
                verifier.validate_provider_metadata_preflight(
                    metadata,
                    expected_control_commit="a" * 40,
                    expected_artifact_id=123,
                )

    def test_provider_zip_receive_is_bounded_and_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact.zip"
            with self.assertRaisesRegex(verifier.DownloadError, "exceeds declared"):
                verifier.receive_provider_zip(
                    io.BytesIO(b"three"),
                    output,
                    expected_bytes=2,
                    expected_sha256=hashlib.sha256(b"th").hexdigest(),
                )
            self.assertFalse(output.exists())

    def test_verify_download_checks_metadata_before_extracting(self) -> None:
        args = Namespace(
            control_commit="a" * 40,
            request_sha256="b" * 64,
            metadata=Path("metadata.json"),
            zip=Path("artifact.zip"),
            artifact_id=123,
        )
        with (
            mock.patch.object(
                verifier,
                "validate_provider_metadata_preflight",
                side_effect=verifier.DownloadError("preflight failed"),
            ),
            mock.patch.object(verifier, "safe_extract_provider_zip") as extract,
            self.assertRaisesRegex(verifier.DownloadError, "preflight failed"),
        ):
            verifier.verify_download(args)
        extract.assert_not_called()

    def test_safe_provider_zip_rejects_traversal_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_zip = self._write_zip(root, "../escape")
            destination = root / "bundle"
            with self.assertRaisesRegex(verifier.DownloadError, "unsafe provider ZIP"):
                verifier.safe_extract_provider_zip(artifact_zip, destination)
            self.assertFalse(destination.exists())

    def test_provider_metadata_rejects_non_finite_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = root / "metadata.json"
            for value in ("NaN", "1e999", "-1e999"):
                with self.subTest(value=value):
                    metadata.write_text(f'{{"id": {value}}}', encoding="utf-8")
                    with self.assertRaisesRegex(
                        verifier.DownloadError,
                        "non-finite JSON",
                    ):
                        verifier.strict_json_file(metadata)

    def test_provider_zip_transport_is_contiguous_and_reassembled_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_zip = self._write_zip(root)
            transport_dir = root / "transport"
            with mock.patch.object(verifier, "TRANSPORT_PART_BYTES", 16):
                transport = verifier.split_provider_zip(
                    artifact_zip,
                    transport_dir,
                )
                assembled = root / "assembled.zip"
                verifier.reassemble_provider_zip(
                    transport_dir,
                    transport,
                    assembled,
                )
                self.assertEqual(assembled.read_bytes(), artifact_zip.read_bytes())
                first = transport_dir / transport["parts"][0]["name"]
                with first.open("ab") as output:
                    output.write(b"x")
                with self.assertRaisesRegex(
                    verifier.DownloadError,
                    "part size changed",
                ):
                    verifier.reassemble_provider_zip(
                        transport_dir,
                        transport,
                        root / "tampered.zip",
                    )


if __name__ == "__main__":
    unittest.main()
