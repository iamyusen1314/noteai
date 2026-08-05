from __future__ import annotations

import hashlib
import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGE_A = ROOT / "deploy" / "production" / "durable_ai_cad5_stage_a.sh"
IMPORTER = (
    ROOT / "deploy" / "production" / "durable_ai_cad5_fresh_importer.sh"
)


class DurableAICad5StageATests(unittest.TestCase):
    def test_shell_syntax_and_offline_self_tests(self) -> None:
        for script, arguments, expected in (
            (
                STAGE_A,
                ["--offline-self-test", str(ROOT)],
                "NOTEAI_DURABLE_AI_CAD5_STAGE_A_OFFLINE_SELF_TEST=PASS\n",
            ),
            (
                IMPORTER,
                ["--offline-self-test"],
                "NOTEAI_DURABLE_AI_CAD5_FRESH_IMPORTER_OFFLINE_SELF_TEST=PASS\n",
            ),
        ):
            subprocess.run(["bash", "-n", str(script)], cwd=ROOT, check=True)
            result = subprocess.run(
                ["bash", str(script), *arguments],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.stdout, expected)
            self.assertEqual(result.stderr, "")

    def test_source_bundle_and_product_identity_are_exact(self) -> None:
        source = STAGE_A.read_text(encoding="utf-8")
        for expected in (
            "cad5ce35664f617c6e19f90a6159285ddf975594",
            "a1ce9c812a74a7e3824851581d1b4b6aaaaddb1c",
            "cfc838b040e2582eca199f5c4d7dea94efa97f50",
            "b55f11882100e9ef919522540729e366a511f88f",
            "2026-08-05T14:30:09Z",
            "source_delta_commit_count='121'",
            "source_total_commit_count='307'",
            "source_bundle_size='1513408'",
            "2a37c49c9284a3f354508601882ff4bbc07fc93aa754003aa7fe29fc307bd19b",
            "refs/remotes/origin/codex/quality-stabilization-real-chain",
            "git-cad5ce3-amd64-ai-worker-r1",
        ):
            self.assertIn(expected, source)

    def test_current_source_inputs_and_v2_projection_are_fixed(self) -> None:
        source = STAGE_A.read_text(encoding="utf-8")
        for expected in (
            "ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447",
            "7a6adb458c44521dae7aa9cfa7fc36ae0f5ff0603e810901d7ce6da2e3ae4f6a",
            "1ef4150536e98b8057069981b1aadb469ca12f0f30f188a291af2f31e238724a",
            "71d04b071c2352cfe53ef951c9333b8e24fcd5dfa1dcd1389de09b80002c9093",
            "35f59b31cd7038160c23746909aea6e325251d914cb91b645f65cf8bc7d509a9",
            "f6793eaeeef666511d910335f0257bad644abad13c57decfd69d36cbc7d636a8",
            "roles=(ai-worker)",
            "native_release_evidence_v2.sh",
        ):
            self.assertIn(expected, source)
        self.assertNotIn("cryptography_48_0_1_components", source)
        self.assertNotIn("render_start_admin.sh", source)
        self.assertNotIn("crawler_config", source)

    def test_three_inputs_are_hash_checked_before_build_state(self) -> None:
        source = STAGE_A.read_text(encoding="utf-8")
        checks = (
            'sha256sum "$source_bundle_path"',
            'sha256sum "$wheelhouse_archive_path"',
            'sha256sum "$scanner_archive_path"',
        )
        for check in checks:
            self.assertIn(check, source)
            self.assertLess(source.index(check), source.index("phase='offline_input_extract'"))
        self.assertIn("verify_archive_members", source)
        self.assertIn("verify_embedded_manifest", source)
        self.assertIn("scanner-bundle/SHA256SUMS", source.replace('"$root/', "scanner-bundle/"))

    def test_appledouble_metadata_is_validated_but_not_extracted(self) -> None:
        source = STAGE_A.read_text(encoding="utf-8")
        self.assertIn('"$prefix"|"$prefix"/*|"._$prefix") ;;', source)
        self.assertIn(
            "tar --exclude='._*' --exclude='*/._*' -xf \"$archive\"",
            source,
        )

        payload = b"fixed scanner payload\n"
        manifest = f"{hashlib.sha256(payload).hexdigest()}  bin/scanner\n".encode()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "scanner.tar"
            destination = root / "out"
            destination.mkdir()
            with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as bundle:
                for name, content in (
                    ("._scanner-bundle", b"appledouble"),
                    ("scanner-bundle/bin/._scanner", b"appledouble"),
                    ("scanner-bundle/bin/scanner", payload),
                    ("scanner-bundle/SHA256SUMS", manifest),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    bundle.addfile(member, io.BytesIO(content))
            subprocess.run(
                [
                    "tar",
                    "--exclude=._*",
                    "--exclude=*/._*",
                    "-xf",
                    str(archive),
                    "-C",
                    str(destination),
                ],
                check=True,
            )
            extracted = destination / "scanner-bundle"
            self.assertEqual((extracted / "bin/scanner").read_bytes(), payload)
            self.assertEqual((extracted / "SHA256SUMS").read_bytes(), manifest)
            self.assertFalse(any(path.name.startswith("._") for path in root.rglob("*")))

    def test_build_is_offline_and_pip_has_no_index_fallback(self) -> None:
        source = STAGE_A.read_text(encoding="utf-8")
        for expected in (
            "args=(buildx build --network=none",
            "--mount=type=bind,from=noteai_wheelhouse,target=/wheelhouse,ro",
            "pip install --no-cache-dir --no-index --find-links=/wheelhouse",
            "--skip-db-update --skip-java-db-update --offline-scan",
            'if [ "$arg" = --pull ]',
            '[ "$pull_count" = 1 ]',
            "network=none pip_index=none",
        ):
            self.assertIn(expected, source)
        for forbidden in (
            "pip download",
            "--download-db-only",
            "ghcr.io/aquasecurity/trivy-db",
            "public.ecr.aws",
            "curl ",
            "wget ",
            "sleep ",
        ):
            self.assertNotIn(forbidden, source)

    def test_build_acceptance_is_ai_worker_only_and_unsuppressed(self) -> None:
        source = STAGE_A.read_text(encoding="utf-8")
        for expected in (
            '.roles[0].role == "ai-worker"',
            '.roles[0].target == "ai-worker-runtime"',
            ".roles[0].findings.critical == 4",
            ".roles[0].findings.high == 19",
            '.roles[0].findings.cryptography_version == "50.0.0"',
            ".roles[0].findings.cryptography_components == 1",
            '["python","durable_ai_worker.py","--once"]',
            "NOTEAI_DURABLE_AI_SUSPENDED=1",
            '["NONE"]',
            "noteai:x:999:999:",
        ):
            self.assertIn(expected, source)

    def test_publisher_is_exact_one_push_and_keeps_digest_domains_distinct(self) -> None:
        source = STAGE_A.read_text(encoding="utf-8")
        self.assertEqual(source.count('docker push "$remote_image"'), 1)
        self.assertEqual(source.count("push_started=1"), 1)
        for expected in (
            "--password-stdin",
            "extract_push_digest",
            "extract_descriptor_digest",
            'remote_digest_ref="${registry_host}/${repository}@${push_digest}"',
            'imagetools inspect "$remote_digest_ref" --raw',
            '[ "$push_digest" = "$manifest_digest" ]',
            '[ "$manifest_config_digest" = "$local_image_id" ]',
            '[ "$manifest_digest" != "$local_image_id" ]',
            "pushes=1 manual_retries=0",
            "publication_state='unknown'",
            "publication_state='verified'",
            "reconcile_control_plane_before_any_next_action=required",
            "no_rerun=1",
        ):
            self.assertIn(expected, source)
        self.assertNotIn(
            "18db7ceff942788bc4ca1c77a466c17570c3fcc6f109957661e1a35f047ba62f",
            source,
        )
        self.assertNotIn("phase='immutable_tag_absence'", source)

    def test_importer_is_pull_only_and_uses_exact_manifest_reference(self) -> None:
        source = IMPORTER.read_text(encoding="utf-8")
        self.assertEqual(
            source.count('docker pull --platform linux/amd64 "$digest_ref"'), 1
        )
        for expected in (
            'digest_ref="${repository_ref}@${manifest_digest}"',
            "single_exact_digest_pull",
            "2700s",
            "pulls=1 retries=0 containers_started=0",
            "--password-stdin",
            "RepoDigests == [$digest_ref]",
        ):
            self.assertIn(expected, source)
        for forbidden in (
            "docker push",
            "docker build",
            "buildx build",
            "docker run",
            "docker create",
            "docker compose",
            "systemctl start",
            "psql",
            "DATABASE_URL",
            "curl ",
            "wget ",
            "retry",
            "sleep ",
        ):
            self.assertNotIn(forbidden, source)

    def test_importer_proves_freshness_and_exact_runtime_metadata(self) -> None:
        source = IMPORTER.read_text(encoding="utf-8")
        for expected in (
            "docker image ls -aq",
            "docker ps -aq",
            "docker volume ls -q",
            "Build Cache",
            '[ "$actual_config_digest" = "$expected_config_digest" ]',
            "amd64/linux",
            "RepoTags == []",
            ".[0].Size > 0",
            "all(.[0].RootFS.Layers[]",
            "/app/model",
            '["/app/scripts/docker_entrypoint.sh"]',
            '["python","durable_ai_worker.py","--once"]',
            "NOTEAI_DURABLE_AI_SUSPENDED=1",
            "NOTEAI_RUNTIME_ROLE=ai-worker",
            '["NONE"]',
            "images=0 build_cache=0",
            "host_reuse=forbidden",
        ):
            self.assertIn(expected, source)
        self.assertNotIn(
            "18db7ceff942788bc4ca1c77a466c17570c3fcc6f109957661e1a35f047ba62f",
            source,
        )

    def test_scope_does_not_add_control_plane_or_production_mutation(self) -> None:
        combined = STAGE_A.read_text(encoding="utf-8") + IMPORTER.read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "workflow_dispatch",
            "ledger",
            "receipt",
            "topology",
            "V18",
            "R17",
            "CreateRole",
            "DeleteRole",
            "CreateInstance",
            "DeleteRepoTag",
            "systemctl enable",
            "systemctl restart",
            "docker compose",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
