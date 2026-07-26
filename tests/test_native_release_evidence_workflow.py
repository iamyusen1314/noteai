import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "native-release-evidence.yml"
SCRIPT = ROOT / "scripts" / "ci" / "native_release_evidence.sh"


class NativeReleaseEvidenceWorkflowTests(unittest.TestCase):
    def test_workflow_is_bounded_read_only_and_native_amd64(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("push:\n    branches:\n      - codex/quality-stabilization-real-chain", workflow)
        self.assertIn(
            "paths:\n"
            "      - .github/workflows/native-release-evidence.yml\n"
            "      - scripts/ci/native_release_evidence.sh",
            workflow,
        )
        self.assertNotRegex(workflow, r"(?m)^  (?:pull_request|schedule):")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn('test "$(uname -m)" = "x86_64"', workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("lfs: true", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("docker/login-action", workflow)
        self.assertNotIn("docker push", workflow)
        self.assertNotIn("--push", workflow)

    def test_actions_and_scanner_archives_are_immutable(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        action_uses = re.findall(r"uses:\s*([^@\s]+)@([^\s]+)", workflow)
        self.assertEqual(len(action_uses), 2)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for _, ref in action_uses))
        self.assertIn("SYFT_VERSION: \"1.49.0\"", workflow)
        self.assertIn(
            "SYFT_SHA256: 7aa2f03ee92739cf643279ba3990548b9925d4e22cae13f46831ee62821147fe",
            workflow,
        )
        self.assertIn("TRIVY_VERSION: \"0.72.0\"", workflow)
        self.assertIn(
            "TRIVY_SHA256: bbb64b9695866ce4a7a8f5c9592002c5961cab378577fa3f8a040df362b9b2ea",
            workflow,
        )
        self.assertEqual(workflow.count("sha256sum --check -"), 2)

    def test_build_script_covers_five_roles_and_never_starts_or_publishes(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("roles=(api admin payment ai-worker xhs-http)", source)
        for target in (
            "api-runtime",
            "admin-runtime",
            "payment-runtime",
            "ai-worker-runtime",
            "xhs-http-runtime",
        ):
            self.assertIn(target, source)
        self.assertIn("--platform linux/amd64", source)
        self.assertIn("--metadata-file", source)
        self.assertIn("docker create --name", source)
        self.assertNotIn("docker run", source)
        self.assertNotIn("docker push", source)
        self.assertNotIn("docker login", source)
        self.assertNotIn("--push", source)

    def test_build_script_enforces_provenance_runtime_and_zero_findings(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("org.opencontainers.image.revision", source)
        self.assertIn("org.opencontainers.image.source", source)
        self.assertIn("org.opencontainers.image.version", source)
        self.assertIn("org.opencontainers.image.created", source)
        self.assertIn("com.noteai.runtime.role", source)
        self.assertIn("noteai:x:999:999:", source)
        self.assertIn("NOTEAI_PAYMENT_CALLBACK_ENABLED=0", source)
        self.assertIn("NOTEAI_DURABLE_AI_SUSPENDED=1", source)
        self.assertIn("NOTEAI_XHS_COLLECTION_SUSPENDED=1", source)
        self.assertIn("--scanners vuln --severity HIGH,CRITICAL", source)
        self.assertIn("--scanners secret", source)
        self.assertIn("browser_component_count", source)
        self.assertIn("cryptography_component_count", source)
        self.assertIn('.name == "cryptography" and .version == "48.0.1"', source)
        self.assertIn("forbidden_os_count", source)
        self.assertIn("all($roles[]; .passed == true)", source)

    def test_existing_ci_fetches_evidence_history(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("fetch-depth: 0", workflow)


if __name__ == "__main__":
    unittest.main()
