from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_export_plan_v16 as verifier  # noqa: E402


class FakeLedger:
    def __init__(self, *, current_status: str = "in_progress"):
        self.contract = verifier._expected_ledger_contract()
        self.current_run_id = 40000000001
        self.current_workflow_id = 400000001
        self.current_head = "a" * 40
        self.current_branch = verifier.BRANCH
        self.current_status = current_status
        self.extra_repository_runs: list[dict] = []
        self.current_artifacts: list[dict] = []

    @staticmethod
    def _page(items: list[dict]) -> dict:
        return {"total_count": len(items), "workflow_runs": items}

    @staticmethod
    def _artifact_page(items: list[dict]) -> dict:
        return {"total_count": len(items), "artifacts": items}

    @staticmethod
    def _job_page(items: list[dict]) -> dict:
        return {"total_count": len(items), "jobs": items}

    def _legacy_version(self, workflow_ref: str) -> dict:
        for version in self.contract["legacy"]:
            if version.get("workflow_ref") == workflow_ref:
                return version
        raise AssertionError(f"unknown workflow ref: {workflow_ref}")

    def _expected_run(self, run_id: int) -> dict:
        for version in self.contract["legacy"]:
            for run in version.get("runs", []):
                if run["id"] == run_id:
                    return run
        raise AssertionError(f"unknown run: {run_id}")

    def __call__(self, requested: str) -> dict:
        path = requested.split("?", 1)[0]
        if path == "/actions/runs":
            return self._page(
                [
                    {
                        "id": 30696298423,
                        "path": verifier.V12_WORKFLOW_PATH,
                    },
                    {
                        "id": 30724578319,
                        "path": verifier.V15_WORKFLOW_PATH,
                    },
                    {
                        "id": self.current_run_id,
                        "path": verifier.V16_WORKFLOW_PATH,
                    },
                    *copy.deepcopy(self.extra_repository_runs),
                ]
            )
        if path == f"/actions/runs/{self.current_run_id}":
            return {
                "id": self.current_run_id,
                "workflow_id": self.current_workflow_id,
                "head_sha": self.current_head,
                "head_branch": self.current_branch,
                "path": verifier.V16_WORKFLOW_PATH,
                "event": "push",
                "run_attempt": 1,
                "status": self.current_status,
                "conclusion": None,
            }
        if path == f"/actions/workflows/{self.current_workflow_id}/runs":
            return self._page(
                [
                    {
                        "id": self.current_run_id,
                        "workflow_id": self.current_workflow_id,
                        "head_sha": self.current_head,
                        "head_branch": self.current_branch,
                        "path": verifier.V16_WORKFLOW_PATH,
                        "event": "push",
                        "run_attempt": 1,
                        "status": self.current_status,
                        "conclusion": None,
                    }
                ]
            )
        if path == f"/actions/runs/{self.current_run_id}/artifacts":
            return self._artifact_page(copy.deepcopy(self.current_artifacts))
        if path.startswith("/actions/workflows/") and path.endswith("/runs"):
            workflow_ref = path.split("/")[3]
            version = self._legacy_version(workflow_ref)
            return self._page(
                [
                    {
                        "id": run["id"],
                        "head_sha": run["head_sha"],
                        "event": run["event"],
                        "run_attempt": run["run_attempt"],
                        "status": run["status"],
                        "conclusion": run["conclusion"],
                        "path": version.get("workflow_path", "legacy.yml"),
                    }
                    for run in version["runs"]
                ]
            )
        if path.startswith("/actions/runs/") and path.endswith("/jobs"):
            run_id = int(path.split("/")[3])
            expected = self._expected_run(run_id)
            return self._job_page(
                [
                    {
                        "id": job_id,
                        "run_id": run_id,
                        "run_attempt": 1,
                        "head_sha": expected["head_sha"],
                        "status": "completed",
                        "conclusion": "failure",
                    }
                    for job_id in expected["job_ids"]
                ]
            )
        if path.startswith("/actions/runs/") and path.endswith("/artifacts"):
            self._expected_run(int(path.split("/")[3]))
            return self._artifact_page([])
        raise AssertionError(f"unexpected request: {requested}")


class AdminDependencyCacheExportPlanV16Tests(unittest.TestCase):
    @staticmethod
    def _template() -> dict:
        return json.loads(verifier.TEMPLATE_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def _workflow() -> str:
        return verifier.WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_exact_checkpoint_receipt_activation_and_authority_sets(self) -> None:
        self.assertEqual(len(verifier.INERT_CHECKPOINT_FILES), 16)
        self.assertEqual(len(verifier.INERT_RECEIPT_FILES), 4)
        self.assertEqual(len(verifier.CHECKPOINT_IMMUTABLE_FILES), 12)
        self.assertEqual(len(verifier.SAME_ANCHOR_FILES), 9)
        self.assertEqual(
            set(verifier.CHECKPOINT_IMMUTABLE_FILES),
            set(verifier.INERT_CHECKPOINT_FILES)
            - set(verifier.INERT_RECEIPT_FILES),
        )
        self.assertEqual(verifier.PREDECESSOR_COMMIT, verifier.V15_TERMINAL_RECEIPT)

    def test_reviewed_static_authorities_and_v15_predecessor_validate(self) -> None:
        self.assertEqual(verifier.validate_plan(verify_git_state=False), [])
        self.assertEqual(verifier._validate_v15_predecessor(), [])

    def test_template_fail_closed_matrix(self) -> None:
        template = self._template()
        self.assertEqual(verifier._template_errors(template), [])
        mutations = (
            ("schema", lambda value: value.__setitem__("schema_version", 15)),
            (
                "predecessor",
                lambda value: value["predecessor"].__setitem__("run_id", 1),
            ),
            (
                "helper",
                lambda value: value["recovery_basis"].__setitem__(
                    "v16_import_helper_sha256", "0" * 64
                ),
            ),
            (
                "checkpoint-count",
                lambda value: value["control_plane"].__setitem__(
                    "inert_checkpoint_exact_changed_path_count", 15
                ),
            ),
            (
                "ledger-v15",
                lambda value: value["run_ledger_contract"]["legacy"].pop(),
            ),
            (
                "classification",
                lambda value: value["build_evidence_recovery"].__setitem__(
                    "identity_pair_classification_required",
                    "SAME_SOURCE_COPY_PIP_DIGESTS_NONCACHED",
                ),
            ),
            (
                "deployment",
                lambda value: value.__setitem__("deployment_authorized", True),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                candidate = copy.deepcopy(template)
                mutate(candidate)
                self.assertTrue(verifier._template_errors(candidate))

    def test_workflow_fail_closed_matrix(self) -> None:
        workflow = self._workflow()
        self.assertEqual(verifier._workflow_errors(workflow), [])
        mutations = (
            ("dispatch", workflow + "\n# workflow_dispatch:\n"),
            ("write", workflow.replace("contents: read", "contents: write", 1)),
            (
                "missing-helper",
                workflow.replace(
                    "scripts/ci/import_admin_dependency_cache_v16.sh",
                    "scripts/ci/import-admin-missing.sh",
                ),
            ),
            ("cacheless", workflow + "\n# cacheless replay\n"),
            (
                "classification",
                workflow.replace(
                    "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED",
                    "SAME_SOURCE_COPY_PIP_DIGESTS_NONCACHED",
                ),
            ),
            (
                "cleanup-order",
                workflow.replace(
                    "Remove V16 builders and all transient Docker state",
                    "Removed cleanup stage",
                ),
            ),
        )
        for name, candidate in mutations:
            with self.subTest(name=name):
                self.assertTrue(verifier._workflow_errors(candidate))

    def test_strict_json_rejects_duplicate_noncanonical_and_nonfinite(self) -> None:
        for payload in (
            b'{"a":1,"a":2}\n',
            b'{"a": 1}\n',
            b'{\n  "a": NaN\n}\n',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                verifier._strict_json_bytes(payload, "candidate")

    def test_active_request_must_be_exact_template_substitution(self) -> None:
        parent = "a" * 40
        active = json.loads(
            verifier.TEMPLATE_PATH.read_text(encoding="utf-8").replace(
                "__DIRECT_PARENT_COMMIT__", parent
            )
        )
        self.assertEqual(
            verifier.validate_plan(
                verify_git_state=False,
                active_request=active,
            ),
            [],
        )
        active["deployment_authorized"] = True
        self.assertTrue(
            verifier.validate_plan(
                verify_git_state=False,
                active_request=active,
            )
        )

    def test_plan_state_classifier(self) -> None:
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=[],
            ),
            "PREPARED_V16_NOT_TRIGGERED",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=True,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V16_ARMED_OR_TRIGGERED_EXACT",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V16_CONSUMED_OR_INVALID",
        )

    def test_same_anchor_enforces_exact16_and_immutable12(self) -> None:
        anchor = "b" * 40
        tree_entry = "100644 blob " + ("c" * 40) + "\tfile"
        patches = (
            mock.patch.object(verifier, "_authority_anchor", return_value=(anchor, [])),
            mock.patch.object(verifier, "_canonical_branch_head", return_value=anchor),
            mock.patch.object(
                verifier,
                "_commit_parents",
                return_value=[verifier.PREDECESSOR_COMMIT],
            ),
            mock.patch.object(
                verifier,
                "_changed_paths",
                return_value=set(verifier.INERT_CHECKPOINT_FILES),
            ),
            mock.patch.object(verifier, "_on_first_parent_chain", return_value=True),
            mock.patch.object(verifier, "_tree_entry", return_value=tree_entry),
            mock.patch.object(verifier, "_lineage_path_changes", return_value=[]),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            self.assertEqual(verifier._validate_same_anchor(), [])
        with (
            mock.patch.object(verifier, "_authority_anchor", return_value=(anchor, [])),
            mock.patch.object(verifier, "_canonical_branch_head", return_value=anchor),
            mock.patch.object(
                verifier,
                "_commit_parents",
                return_value=[verifier.PREDECESSOR_COMMIT],
            ),
            mock.patch.object(verifier, "_changed_paths", return_value=set()),
            mock.patch.object(verifier, "_on_first_parent_chain", return_value=True),
            mock.patch.object(verifier, "_tree_entry", return_value=tree_entry),
            mock.patch.object(verifier, "_lineage_path_changes", return_value=[]),
        ):
            self.assertTrue(verifier._validate_same_anchor())

    def test_live_ledger_pre_and_post_cleanup_snapshots(self) -> None:
        ledger = FakeLedger()
        pre = verifier.collect_live_ledger_snapshot(
            phase="pre_resource",
            repository="owner/repository",
            run_id=ledger.current_run_id,
            head_sha=ledger.current_head,
            head_branch=ledger.current_branch,
            fetch=ledger,
        )
        self.assertEqual(len(pre["legacy"]), 14)
        self.assertEqual(pre["legacy"][9]["runs"], [])
        self.assertEqual(pre["legacy"][12]["runs"], [])
        self.assertEqual(pre["legacy"][13]["runs"][0]["id"], 30724578319)
        post = verifier.collect_live_ledger_snapshot(
            phase="post_cleanup_pre_upload",
            repository="owner/repository",
            run_id=ledger.current_run_id,
            head_sha=ledger.current_head,
            head_branch=ledger.current_branch,
            fetch=ledger,
            pre_snapshot=pre,
        )
        self.assertEqual(post["legacy"], pre["legacy"])
        self.assertEqual(post["current"]["artifacts"], [])

    def test_live_ledger_rejects_v15_rerun_and_current_artifact(self) -> None:
        v15 = FakeLedger()
        v15.extra_repository_runs.append(
            {"id": 30724578320, "path": verifier.V15_WORKFLOW_PATH}
        )
        artifact = FakeLedger()
        artifact.current_artifacts.append({"id": 1})
        for name, ledger in (("v15-rerun", v15), ("artifact", artifact)):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                verifier.collect_live_ledger_snapshot(
                    phase="pre_resource",
                    repository="owner/repository",
                    run_id=ledger.current_run_id,
                    head_sha=ledger.current_head,
                    head_branch=ledger.current_branch,
                    fetch=ledger,
                )

    def test_live_ledger_contract_copy_requires_private_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract = Path(temporary) / "contract.json"
            contract.write_bytes(verifier.TEMPLATE_PATH.read_bytes())
            contract.chmod(0o644)
            with (
                mock.patch.dict(
                    os.environ,
                    {"NOTEAI_V16_LEDGER_CONTRACT_PATH": str(contract)},
                ),
                self.assertRaises(ValueError),
            ):
                verifier._expected_ledger_contract()
            contract.chmod(0o400)
            with mock.patch.dict(
                os.environ,
                {"NOTEAI_V16_LEDGER_CONTRACT_PATH": str(contract)},
            ):
                self.assertEqual(
                    verifier._expected_ledger_contract()["schema"],
                    verifier.LEDGER_SCHEMA,
                )

    def test_pagination_rejects_duplicate_items(self) -> None:
        def duplicate_fetch(_path: str) -> dict:
            return {"total_count": 2, "items": [{"id": 1}, {"id": 1}]}

        with self.assertRaises(RuntimeError):
            verifier._paginate_api(duplicate_fetch, "/items", "items")

    def test_python_optimized_mode_keeps_static_checks(self) -> None:
        command = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT / 'tools')!r}); "
            "import verify_admin_dependency_cache_export_plan_v16 as v; "
            "raise SystemExit(0 if not v.validate_plan(verify_git_state=False) else 1)"
        )
        result = subprocess.run(
            [sys.executable, "-O", "-c", command],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
