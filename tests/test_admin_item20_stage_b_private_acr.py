from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "admin_item20_stage_b_private_acr.sh"


class AdminItem20StageBPrivateACRTests(unittest.TestCase):
    def test_shell_syntax_and_digest_parser_self_test(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--offline-self-test"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout,
            "NOTEAI_ADMIN_STAGE_B_OFFLINE_SELF_TEST=PASS\n",
        )
        self.assertEqual(result.stderr, "")

    def test_fixed_admin_only_private_target_and_source_identity(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for expected in (
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
            "noteai-native-evidence:5335bda-admin",
            "noteai-local:git-5335bda-amd64-admin-r1",
            "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com",
            "repository='noteai/app'",
            "tag='git-5335bda-amd64-admin-r1'",
            "admin-5335-current-public-ecr",
            "evidence_files=11 pushes=1 manual_retries=0",
        ):
            self.assertIn(expected, source)
        self.assertNotIn("registry.cn-shenzhen.cr.aliyuncs.com'", source)
        self.assertEqual(source.count("registry-vpc.cn-shenzhen.cr.aliyuncs.com"), 1)

    def test_exact_stage_a_evidence_and_image_contract_is_rechecked(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for evidence_name in (
            "python-base-index.json",
            "node-base-index.json",
            "admin-build-metadata.json",
            "admin-inspect.json",
            "admin-history.jsonl",
            "admin-sbom.cdx.json",
            "admin-vuln-high-critical.json",
            "admin-secret.json",
            "admin-os-packages.txt",
            "admin-summary.json",
            "summary.json",
        ):
            self.assertIn(evidence_name, source)
        for contract in (
            '.["containerimage.config.digest"] == $image_id',
            '.roles[0].role == "admin"',
            '.roles[0].image_id == $image_id',
            'type == "array" and length == 1 and .[0].Id == $image_id',
            "render_start_admin.sh",
            "com.noteai.runtime.role",
            "stat -c '%u:%g:%a'",
        ):
            self.assertIn(contract, source)

    def test_exactly_one_push_and_no_retry_or_unrelated_mutation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(source.count('docker push "$remote_image"'), 1)
        self.assertEqual(source.count("published=1"), 1)
        self.assertEqual(source.count("push_started=1"), 1)
        self.assertEqual(source.count("manual_retries=0"), 2)
        for forbidden in (
            "docker pull",
            "docker build ",
            "buildx build",
            "docker run",
            "docker compose",
            "systemctl",
            "psql",
            "DATABASE_URL",
            "DeleteRepoTag",
            "--all-tags",
            "docker system prune",
            "curl ",
            "wget ",
            "ossutil",
            "trivy",
            "pip install",
            "retry",
            "sleep ",
        ):
            self.assertNotIn(forbidden, source)

    def test_password_is_stdin_only_and_cleanup_is_fail_closed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--password-stdin", source)
        self.assertIn("IFS= read -r registry_password", source)
        self.assertIn(
            'if IFS= read -r extra_input || [ -n "$extra_input" ]; then',
            source,
        )
        self.assertIn("unset registry_password", source)
        self.assertIn("set +x", source)
        self.assertNotIn("set +e", source)
        self.assertNotIn("--password ", source)
        self.assertNotIn("AuthorizationToken", source)
        self.assertNotIn("REGISTRY_PASSWORD", source)
        self.assertIn("export HOME='/root'", source)
        self.assertIn("export DOCKER_CONTEXT='default'", source)
        self.assertIn("unix:///var/run/docker.sock", source)
        self.assertIn("[ -S /var/run/docker.sock ]", source)
        for docker_environment in (
            "BUILDKIT_HOST",
            "BUILDX_BUILDER",
            "BUILDX_CONFIG",
            "DOCKER_CERT_PATH",
            "DOCKER_CONFIG",
            "DOCKER_CONTEXT",
            "DOCKER_HOST",
            "DOCKER_TLS_VERIFY",
        ):
            self.assertIn(docker_environment, source)
        self.assertIn("trap on_exit EXIT", source)
        self.assertIn("task_root_owned=0", source)
        self.assertIn("remote_alias_created=0", source)
        self.assertIn('mkdir -m 0700 -- "$task_root"', source)
        self.assertIn('if [ "$task_root_owned" = \'1\' ]', source)
        self.assertIn('if [ "$remote_alias_created" = \'1\' ]', source)
        self.assertIn('docker logout "$registry_host"', source)
        self.assertIn('rm -rf -- "$task_root"', source)
        self.assertIn('docker image rm "$remote_image"', source)
        self.assertNotIn('docker image rm "$local_image"', source)
        self.assertNotIn('docker image rm "$canonical_image"', source)

    def test_digest_sources_are_independent_and_not_conflated(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("extract_push_digest", source)
        self.assertIn("extract_descriptor_digest", source)
        self.assertIn('imagetools inspect "$remote_image" > "$descriptor_log"', source)
        self.assertIn('imagetools inspect "$remote_image" --raw', source)
        self.assertIn('[ "$push_digest" = "$manifest_digest" ]', source)
        self.assertIn('[ "$manifest_config_digest" = "$local_image_id" ]', source)
        self.assertIn('[ "$manifest_digest" != "$local_image_id" ]', source)
        self.assertIn('raw_manifest_sha="$(sha256sum "$raw_manifest"', source)
        self.assertNotIn('manifest_digest="$(sha256sum', source)
        self.assertIn("PUSH_MANIFEST_PASS", source)
        self.assertNotIn("STAGE_B=PASS", source)


if __name__ == "__main__":
    unittest.main()
