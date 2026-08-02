import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import verify_admin_dependency_cache_export_plan_v17 as verifier  # noqa: E402


class AdminDependencyCacheExportPlanV17Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.template_bytes = verifier.TEMPLATE_PATH.read_bytes()
        self.template = json.loads(self.template_bytes)
        self.workflow = verifier.WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_template_uses_only_c17_and_native_acceptance_control(self) -> None:
        self.assertEqual(
            self.template["control_plane"],
            verifier._expected_control_plane(),
        )
        self.assertNotIn("predecessor", self.template)
        self.assertNotIn("run_ledger_contract", self.template)
        self.assertEqual(verifier._template_errors(self.template), [])
        self.assertEqual(
            self.template_bytes.count(b"__DIRECT_PARENT_COMMIT__"),
            1,
        )

    def test_workflow_removes_custom_ledger_receipt_and_topology(self) -> None:
        self.assertEqual(verifier._workflow_errors(self.workflow), [])
        for forbidden in (
            "actions: read",
            "NOTEAI_ACTIONS_READ_TOKEN",
            "api.github.com",
            "live-ledger",
            "RUN_LEDGER",
            "pre_ledger",
            "late_ledger",
            "exact18",
            "exact4",
            "ledger_contract_copy",
            "ledger_verifier_copy",
        ):
            self.assertNotIn(forbidden, self.workflow)

    def test_c17_data_plane_and_witnesses_are_immutable(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "",
                "GITHUB_SHA": "",
                "GITHUB_EVENT_NAME": "",
                "GITHUB_REF": "",
            },
            clear=False,
        ):
            self.assertEqual(verifier._validate_c17_data_plane_anchor(), [])
        for relative, expected_sha256 in verifier.DATA_PLANE_FILES:
            payload = subprocess.run(
                [
                    "git",
                    "show",
                    f"{verifier.C17_DATA_PLANE_ANCHOR}:{relative.as_posix()}",
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha256)
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                expected_sha256,
            )

    def test_c17_workflow_build_steps_are_byte_identical(self) -> None:
        anchor_workflow = subprocess.run(
            [
                "git",
                "show",
                f"{verifier.C17_DATA_PLANE_ANCHOR}:{verifier.WORKFLOW_PATH.relative_to(ROOT)}",
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
        for name in verifier.WORKFLOW_DATA_PLANE_STEPS:
            self.assertEqual(
                verifier._extract_workflow_step(self.workflow, name),
                verifier._extract_workflow_step(anchor_workflow, name),
                name,
            )

    def test_template_mutations_fail_closed(self) -> None:
        mutations = (
            lambda value: value["control_plane"].update(
                custom_ledger_required=True
            ),
            lambda value: value["control_plane"].update(
                data_plane_anchor_commit="0" * 40
            ),
            lambda value: value.update(run_ledger_contract={}),
            lambda value: value.update(predecessor={"receipt": "invented"}),
            lambda value: value.update(deployment_authorized=True),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                candidate = copy.deepcopy(self.template)
                mutate(candidate)
                self.assertTrue(verifier._template_errors(candidate))

    def test_workflow_mutations_fail_closed(self) -> None:
        candidates = (
            self.workflow.replace(verifier.C17_DATA_PLANE_ANCHOR, "0" * 40),
            self.workflow + "\n# live-ledger\n",
            self.workflow.replace("GITHUB_RUN_ATTEMPT", "REMOVED_ATTEMPT"),
            self.workflow.replace(
                "workflow_run_id=${GITHUB_RUN_ID}",
                "workflow_run_id=missing",
            ),
        )
        for candidate in candidates:
            with self.subTest():
                self.assertTrue(verifier._workflow_errors(candidate))

    def test_active_request_is_exact_parent_substitution(self) -> None:
        parent = "a" * 40
        active = copy.deepcopy(self.template)
        active["plan_checkpoint_commit"] = parent
        self.assertEqual(
            verifier._active_content_errors(active, self.template_bytes),
            [],
        )
        active["plan_checkpoint_commit"] = "b" * 40
        active["deployment_authorized"] = True
        self.assertTrue(
            verifier._active_content_errors(active, self.template_bytes)
        )

    def test_strict_json_rejects_duplicates_and_noncanonical_bytes(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            verifier._strict_json_bytes(b'{"a": 1, "a": 2}\n', "fixture")
        with self.assertRaisesRegex(ValueError, "not canonical"):
            verifier._strict_json_bytes(b'{"a":1}\n', "fixture")

    def test_classifier_has_only_prepared_or_exact_active_success(self) -> None:
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=[],
            ),
            "PREPARED_V17_NOT_TRIGGERED",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=True,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V17_ARMED_OR_TRIGGERED_EXACT",
        )
        for kwargs in (
            {
                "base_errors": ["drift"],
                "active_present": False,
                "active_git_errors": [],
                "additions": [],
            },
            {
                "base_errors": [],
                "active_present": True,
                "active_git_errors": ["extra file"],
                "additions": ["a" * 40],
            },
            {
                "base_errors": [],
                "active_present": True,
                "active_git_errors": [],
                "additions": ["a" * 40, "b" * 40],
            },
        ):
            self.assertEqual(verifier.classify_plan_state(**kwargs), "INVALID")

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _synthetic_activation(
        self, *, extra_activation_path: bool = False
    ) -> tuple[tempfile.TemporaryDirectory, Path, str, str, dict]:
        temporary = tempfile.TemporaryDirectory()
        repo = Path(temporary.name)
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.name", "NoteAI Test")
        self._git(repo, "config", "user.email", "noteai@example.invalid")
        template_path = repo / verifier.TEMPLATE_PATH.relative_to(ROOT)
        template_path.parent.mkdir(parents=True)
        template_path.write_bytes(self.template_bytes)
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-qm", "C17 data plane")
        c17 = self._git(repo, "rev-parse", "HEAD")
        control_path = repo / "control.txt"
        control_path.write_text("native control\n", encoding="utf-8")
        self._git(repo, "add", "control.txt")
        self._git(repo, "commit", "-qm", "Simplify V17 control")
        parent = self._git(repo, "rev-parse", "HEAD")
        active = copy.deepcopy(self.template)
        active["plan_checkpoint_commit"] = parent
        request_path = repo / verifier.ACTIVE_REQUEST_PATH.relative_to(ROOT)
        request_path.parent.mkdir(parents=True)
        request_path.write_text(
            json.dumps(active, ensure_ascii=False, allow_nan=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        self._git(repo, "add", request_path.relative_to(repo).as_posix())
        if extra_activation_path:
            (repo / "extra.txt").write_text("not authorized\n", encoding="utf-8")
            self._git(repo, "add", "extra.txt")
        self._git(repo, "commit", "-qm", "Activate V17")
        activation = self._git(repo, "rev-parse", "HEAD")
        return temporary, repo, c17, activation, active

    def test_direct_parent_request_only_activation_without_receipt(self) -> None:
        temporary, repo, c17, _activation, active = self._synthetic_activation()
        with temporary, mock.patch.object(
            verifier, "C17_DATA_PLANE_ANCHOR", c17
        ), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}, clear=False):
            self.assertEqual(
                verifier._validate_active_git(active, root=repo),
                [],
            )

    def test_activation_extra_path_and_duplicate_addition_fail(self) -> None:
        temporary, repo, c17, _activation, active = self._synthetic_activation(
            extra_activation_path=True
        )
        with temporary, mock.patch.object(
            verifier, "C17_DATA_PLANE_ANCHOR", c17
        ), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}, clear=False):
            self.assertIn(
                "V17 activation changes more than its request",
                verifier._validate_active_git(active, root=repo),
            )

        temporary, repo, c17, _activation, active = self._synthetic_activation()
        with temporary, mock.patch.object(
            verifier, "C17_DATA_PLANE_ANCHOR", c17
        ), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}, clear=False):
            request = verifier.ACTIVE_REQUEST_PATH.relative_to(ROOT)
            self._git(repo, "rm", "-q", request.as_posix())
            self._git(repo, "commit", "-qm", "Remove request")
            (repo / request).parent.mkdir(parents=True, exist_ok=True)
            (repo / request).write_text(
                json.dumps(active, ensure_ascii=False, allow_nan=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            self._git(repo, "add", request.as_posix())
            self._git(repo, "commit", "-qm", "Add request again")
            self.assertIn(
                "V17 active request addition history is not unique",
                verifier._validate_active_git(active, root=repo),
            )

    def test_normal_and_optimized_verifier_match(self) -> None:
        environment = os.environ.copy()
        for key in ("GITHUB_ACTIONS", "GITHUB_SHA", "GITHUB_EVENT_NAME", "GITHUB_REF"):
            environment.pop(key, None)
        normal = subprocess.run(
            [sys.executable, str(verifier.__file__)],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        optimized = subprocess.run(
            [sys.executable, "-O", str(verifier.__file__)],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(normal.returncode, optimized.returncode)
        self.assertEqual(normal.stdout, optimized.stdout)
        self.assertEqual(normal.returncode, 0, normal.stdout)


if __name__ == "__main__":
    unittest.main()
