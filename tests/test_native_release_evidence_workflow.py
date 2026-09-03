import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "native-release-evidence.yml"
SCRIPT = ROOT / "scripts" / "ci" / "native_release_evidence.sh"
SUCCESSOR_SCRIPT = ROOT / "scripts" / "ci" / "native_release_evidence_v2.sh"
ADMIN_REQUEST = (
    ROOT / ".github" / "release-requests" / "admin-5335bda-v2.json"
)
ADMIN_REQUEST_SHA256 = (
    "c5bd56148af0d780d3955ebb9ed5dafe0c7507ba6974da86b5830323c77009ef"
)


class NativeReleaseEvidenceWorkflowTests(unittest.TestCase):
    def test_legacy_build_script_remains_exact_for_historical_evidence(self):
        self.assertEqual(
            hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            "639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2",
        )

    def test_workflow_is_bounded_read_only_and_native_amd64(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("release_scope:", workflow)
        self.assertIn("default: five", workflow)
        self.assertIn("          - five\n          - admin", workflow)
        self.assertNotRegex(workflow, r"(?m)^  (?:push|pull_request|schedule):")
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

        self.assertNotIn("github.event.head_commit.added", workflow)
        self.assertNotIn("GITHUB_EVENT_PATH", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("Checkout controller commit with full history", workflow)
        self.assertIn("Resolve and validate release control", workflow)
        self.assertIn(
            "git diff-tree --no-commit-id --no-renames --diff-filter=A",
            workflow,
        )
        self.assertIn('--name-only -z -r "${controller_parent}" "${GITHUB_SHA}"', workflow)
        self.assertIn('test "${#added_requests[@]}" -eq 1', workflow)
        self.assertIn(
            'test "${added_requests[0]}" = "${NOTEAI_ADMIN_PUSH_REQUEST}"',
            workflow,
        )
        self.assertNotIn("mapfile -t added_requests < <(", workflow)
        self.assertNotIn("mapfile", workflow)
        self.assertIn('read -r -a parent_fields <<<"${parent_record}"', workflow)
        self.assertIn('test "${#parent_fields[@]}" -eq 2', workflow)
        self.assertIn('test "${parent_fields[0]}" = "${GITHUB_SHA}"', workflow)
        self.assertIn('git merge-base --is-ancestor "${release_commit}" "${GITHUB_SHA}"', workflow)
        self.assertIn('test "${#request_add_commits[@]}" -eq 1', workflow)
        self.assertIn('test "${request_add_commits[0]}" = "${GITHUB_SHA}"', workflow)
        self.assertIn(
            'git log --diff-filter=A --format=%H "${GITHUB_SHA}" --',
            workflow,
        )
        self.assertIn("type == \"object\"", workflow)
        self.assertIn("(keys | sort) == [", workflow)
        self.assertIn("and .schema_version == 2", workflow)
        self.assertIn(
            'and .trigger_mode == "one_shot_controller_diff_v2"',
            workflow,
        )
        self.assertIn(
            f"NOTEAI_ADMIN_PUSH_REQUEST_SHA256: {ADMIN_REQUEST_SHA256}",
            workflow,
        )
        self.assertIn(
            'test "${request_sha256}" = "${NOTEAI_ADMIN_PUSH_REQUEST_SHA256}"',
            workflow,
        )
        self.assertIn(
            "ref: ${{ steps.control.outputs.release_commit }}",
            workflow,
        )
        self.assertIn(
            "NOTEAI_RELEASE_SCOPE: ${{ steps.control.outputs.release_scope }}",
            workflow,
        )
        self.assertIn(
            "NOTEAI_CONTROL_COMMIT: ${{ steps.control.outputs.control_commit }}",
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
        self.assertIn('.roles[0].role == "admin"', workflow)
        self.assertIn('.roles[0].target == "admin-runtime"', workflow)
        self.assertIn('release_scope: "admin"', workflow)
        self.assertIn("source_tree_clean_after_execution: true", workflow)
        self.assertIn(
            'resolution: "controller-checkout-single-parent-git-diff-tree-v2"',
            workflow,
        )
        self.assertIn(
            'release_commit='
            '"5335bdaed933b1f999b5f819c047ec50c11821ae"',
            workflow,
        )
        self.assertIn("request_sha256: $request_sha256", workflow)
        self.assertIn(
            "native-amd64-release-evidence-"
            "${{ steps.control.outputs.release_commit }}"
            "${{ steps.control.outputs.release_scope == 'admin' && '-admin' || '' }}",
            workflow,
        )

    def test_admin_v2_request_is_exact_secret_free_and_hash_pinned(self):
        request_bytes = ADMIN_REQUEST.read_bytes()
        request = json.loads(request_bytes)

        self.assertEqual(hashlib.sha256(request_bytes).hexdigest(), ADMIN_REQUEST_SHA256)
        self.assertEqual(
            set(request),
            {
                "schema_version",
                "task",
                "release_commit",
                "release_scope",
                "trigger_mode",
                "registry_publication_authorized",
                "deployment_authorized",
                "database_authorized",
                "service_mutation_authorized",
                "public_traffic_authorized",
            },
        )
        self.assertEqual(request["schema_version"], 2)
        self.assertEqual(
            request["release_commit"],
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
        )
        self.assertEqual(request["release_scope"], "admin")
        self.assertEqual(request["trigger_mode"], "one_shot_controller_diff_v2")
        for authorization in (
            "registry_publication_authorized",
            "deployment_authorized",
            "database_authorized",
            "service_mutation_authorized",
            "public_traffic_authorized",
        ):
            self.assertIs(request[authorization], False)

    def test_actions_and_scanner_archives_are_immutable(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        action_uses = re.findall(r"uses:\s*([^@\s]+)@([^\s]+)", workflow)
        self.assertEqual(len(action_uses), 3)
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
        workflow = WORKFLOW.read_text(encoding="utf-8")
        source = SUCCESSOR_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'cp scripts/ci/native_release_evidence_v2.sh "${control_script}"',
            workflow,
        )
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
        source = SUCCESSOR_SCRIPT.read_text(encoding="utf-8")

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
        self.assertIn('.name == "cryptography" and .version == "50.0.0"', source)
        self.assertIn("cryptography_version", source)
        self.assertIn("cryptography_components", source)
        self.assertIn('noteai.native-release-evidence.v2', source)
        self.assertNotIn("cryptography_48_0_1_components", source)
        self.assertIn("forbidden_os_count", source)
        self.assertIn("all($roles[]; .passed == true)", source)

    def test_existing_ci_fetches_evidence_history(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("fetch-depth: 0", workflow)


if __name__ == "__main__":
    unittest.main()
