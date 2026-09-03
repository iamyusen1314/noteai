import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class CiModelArtifactRestoreTests(unittest.TestCase):
    def test_ci_avoids_lfs_budget_and_restores_commit_bound_artifacts(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        document = yaml.safe_load(workflow)
        job = document["jobs"]["test"]
        checkout = next(step for step in job["steps"] if step["name"] == "Checkout")

        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn('GIT_LFS_SKIP_SMUDGE: "1"', workflow)
        self.assertEqual(job["env"]["GIT_LFS_SKIP_SMUDGE"], "1")
        self.assertIs(checkout["with"]["lfs"], False)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("lfs: false", workflow)
        self.assertNotIn("lfs: true", workflow)
        self.assertNotIn("git lfs pull", workflow)
        self.assertNotIn("media.githubusercontent.com", workflow)
        self.assertIn("Restore required model artifacts", workflow)
        self.assertIn(
            '[[ "${GITHUB_REPOSITORY}" =~ '
            '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]',
            workflow,
        )
        self.assertIn(
            '[[ "${GITHUB_SHA}" =~ ^[0-9a-f]{40}$ ]]',
            workflow,
        )
        self.assertIn(
            'https://github.com/${GITHUB_REPOSITORY}/raw/${GITHUB_SHA}',
            workflow,
        )
        self.assertIn("python scripts/fetch_model_artifacts.py \\", workflow)
        self.assertIn("--base-url", workflow)
        self.assertIn("--required", workflow)
        self.assertIn("python scripts/fetch_model_artifacts.py --check-only --required", workflow)

        restore_index = workflow.index("Restore required model artifacts")
        verify_index = workflow.index("Verify model artifacts")
        unit_index = workflow.index("Unit tests")
        self.assertLess(restore_index, verify_index)
        self.assertLess(verify_index, unit_index)


if __name__ == "__main__":
    unittest.main()
