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
        self.assertIn("release_scope:", workflow)
        self.assertIn("default: five", workflow)
        self.assertIn("          - five\n          - admin", workflow)
        self.assertIn("push:\n    branches:\n      - codex/quality-stabilization-real-chain", workflow)
        self.assertIn(
            "paths:\n"
            "      - .github/workflows/native-release-evidence.yml\n"
            "      - .github/release-requests/admin-5335bda.json\n"
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

    def test_admin_scope_is_source_external_exact_and_single_role(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            'NOTEAI_RELEASE_SCOPE: ${{ github.event_name == '
            "'workflow_dispatch' && inputs.release_scope || "
            "(contains(github.event.head_commit.added, "
            "'.github/release-requests/admin-5335bda.json') && "
            "'admin' || 'five') }}",
            workflow,
        )
        self.assertIn(
            'control_script="${RUNNER_TEMP}/noteai-native-release-evidence.sh"',
            workflow,
        )
        self.assertIn(
            'original = "roles=(api admin payment ai-worker xhs-http)"',
            workflow,
        )
        self.assertIn('replacement = "roles=(admin)"', workflow)
        self.assertIn('source.count(original) != 1', workflow)
        self.assertIn('test -z "$(git status --short)"', workflow)
        self.assertIn(
            'test "$(find "${NOTEAI_EVIDENCE_DIR}" -maxdepth 1 -type f | wc -l)" = "11"',
            workflow,
        )
        self.assertIn('.roles | length == 1', workflow)
        self.assertIn('.[0].role == "admin"', workflow)
        self.assertIn('.[0].target == "admin-runtime"', workflow)
        self.assertIn('release_scope: "admin"', workflow)
        self.assertIn("source_tree_clean_after_execution: true", workflow)
        self.assertIn(
            "contains(github.event.head_commit.added, "
            "'.github/release-requests/admin-5335bda.json')",
            workflow,
        )
        self.assertIn(
            'test "${RELEASE_COMMIT}" = '
            '"5335bdaed933b1f999b5f819c047ec50c11821ae"',
            workflow,
        )
        self.assertIn("ref: ${{ env.RELEASE_COMMIT }}", workflow)
        self.assertIn(
            'request_json="$(git show '
            '"${GITHUB_SHA}:${NOTEAI_ADMIN_PUSH_REQUEST}")"',
            workflow,
        )
        self.assertIn('.trigger_mode == "one_shot_added_path"', workflow)
        self.assertIn("request_sha256: $request_sha256", workflow)
        self.assertIn(
            "native-amd64-release-evidence-${{ env.RELEASE_COMMIT }}"
            "${{ env.NOTEAI_RELEASE_SCOPE == 'admin' && '-admin' || '' }}",
            workflow,
        )

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
