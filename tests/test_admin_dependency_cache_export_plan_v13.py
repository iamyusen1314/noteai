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

import verify_admin_dependency_cache_export_plan_v13 as verifier  # noqa: E402


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
        self.workflow_overrides: dict[str, list[dict]] = {}
        self.run_overrides: dict[int, dict] = {}

    @staticmethod
    def _page(items: list[dict]) -> dict:
        return {"total_count": len(items), "workflow_runs": items}

    @staticmethod
    def _artifact_page(items: list[dict]) -> dict:
        return {"total_count": len(items), "artifacts": items}

    @staticmethod
    def _job_page(items: list[dict]) -> dict:
        return {"total_count": len(items), "jobs": items}

    def _legacy_runs(self, workflow_ref: str) -> list[dict]:
        for version in self.contract["legacy"]:
            if version.get("workflow_ref") != workflow_ref:
                continue
            if workflow_ref in self.workflow_overrides:
                return copy.deepcopy(self.workflow_overrides[workflow_ref])
            return [
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
            items = [
                {
                    "id": 30696298423,
                    "path": verifier.V12_WORKFLOW_PATH,
                },
                {
                    "id": self.current_run_id,
                    "path": verifier.V13_WORKFLOW_PATH,
                },
                *copy.deepcopy(self.extra_repository_runs),
            ]
            return self._page(items)
        if path == f"/actions/runs/{self.current_run_id}":
            return {
                "id": self.current_run_id,
                "workflow_id": self.current_workflow_id,
                "head_sha": self.current_head,
                "head_branch": self.current_branch,
                "path": verifier.V13_WORKFLOW_PATH,
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
                        "path": verifier.V13_WORKFLOW_PATH,
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
            return self._page(self._legacy_runs(workflow_ref))
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
            run_id = int(path.split("/")[3])
            self._expected_run(run_id)
            return self._artifact_page([])
        if path.startswith("/actions/runs/"):
            run_id = int(path.split("/")[3])
            if run_id in self.run_overrides:
                return copy.deepcopy(self.run_overrides[run_id])
        raise AssertionError(f"unexpected request: {requested}")


class AdminDependencyCacheExportPlanV13Tests(unittest.TestCase):
    @staticmethod
    def _template() -> dict:
        return json.loads(verifier.TEMPLATE_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def _workflow() -> str:
        return verifier.WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_reviewed_authorities_validate_without_git_state(self):
        self.assertEqual(verifier.validate_plan(verify_git_state=False), [])
        self.assertEqual(verifier._validate_v12_terminal_predecessor(), [])

    def test_template_fail_closed_matrix(self):
        for name, mutate in (
            (
                "predecessor",
                lambda value: value["predecessor"].update(artifact_count=1),
            ),
            (
                "terminal-hash",
                lambda value: value["predecessor"].update(
                    terminal_verifier_sha256="0" * 64
                ),
            ),
            (
                "checkpoint-shape",
                lambda value: value["control_plane"].update(
                    inert_checkpoint_exact_changed_path_count=13
                ),
            ),
            (
                "v12-ledger",
                lambda value: value["run_ledger_contract"]["legacy"][10][
                    "runs"
                ][0].update(id=1),
            ),
            (
                "cross-domain-binding",
                lambda value: value["build_evidence_recovery"].update(
                    cache_config_record_digest_vertex_binding_required=True
                ),
            ),
            (
                "record-trust",
                lambda value: value["build_evidence_recovery"].update(
                    core_validated_cache_record_sha256_required=False
                ),
            ),
            (
                "deployment",
                lambda value: value.update(deployment_authorized=True),
            ),
            (
                "database",
                lambda value: value.update(database_authorized=True),
            ),
            (
                "traffic",
                lambda value: value.update(public_traffic_authorized=True),
            ),
        ):
            with self.subTest(name=name):
                candidate = copy.deepcopy(self._template())
                mutate(candidate)
                self.assertTrue(verifier._template_errors(candidate))

    def test_workflow_fail_closed_matrix(self):
        workflow = self._workflow()
        self.assertEqual(verifier._workflow_errors(workflow), [])
        for name, candidate in (
            (
                "manual-trigger",
                workflow.replace("on:\n  push:", "on:\n  workflow_dispatch:\n  push:"),
            ),
            (
                "write-permission",
                workflow.replace(
                    "permissions:\n  contents: read\n  actions: read",
                    "permissions: write-all",
                ),
            ),
            (
                "extra-permission",
                workflow.replace(
                    "  actions: read\n\nconcurrency:",
                    "  actions: read\n  packages: write\n\nconcurrency:",
                ),
            ),
            (
                "job-write-permission",
                workflow.replace(
                    "    runs-on: ubuntu-24.04\n",
                    "    permissions:\n      contents: write\n"
                    "    runs-on: ubuntu-24.04\n",
                    1,
                ),
            ),
            (
                "extra-job",
                workflow
                + "\n  extra-job:\n"
                + "    runs-on: ubuntu-24.04\n"
                + "    steps: []\n",
            ),
            (
                "scheduled-trigger",
                workflow.replace(
                    "\npermissions:\n",
                    "\n  schedule:\n    - cron: '0 * * * *'\n\npermissions:\n",
                    1,
                ),
            ),
            (
                "missing-ledger-contract",
                workflow.replace(
                    "NOTEAI_V13_LEDGER_CONTRACT_PATH: "
                    "${{ steps.control.outputs.ledger_contract_copy }}",
                    "NOTEAI_V13_LEDGER_CONTRACT_PATH_REMOVED: true",
                ),
            ),
            (
                "legacy-identity-path",
                workflow + "\n# .cache_record.direct_path\n",
            ),
            (
                "missing-late-ledger",
                workflow.replace(
                    "Snapshot V2 through V13 ledgers after cleanup and before upload",
                    "late snapshot removed",
                ),
            ),
            (
                "late-ledger-unconditional",
                workflow.replace(
                    "if: ${{ always() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
                    "if: always()",
                    1,
                ),
            ),
            (
                "final-validation-unconditional",
                workflow.replace(
                    "if: ${{ success() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
                    "if: always()",
                    1,
                ),
            ),
        ):
            with self.subTest(name=name):
                self.assertTrue(verifier._workflow_errors(candidate))

    def test_strict_json_rejects_duplicate_noncanonical_and_nonfinite(self):
        for payload in (
            b'{"a":1,"a":2}\n',
            b'{\"a\": 1}\\n',
            b'{\n  \"a\": NaN\n}\n',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                verifier._strict_json_bytes(payload, "candidate")

    def test_plan_state_classifier(self):
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=[],
            ),
            "PREPARED_V13_NOT_TRIGGERED",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=True,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V13_ARMED_OR_TRIGGERED_EXACT",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V13_CONSUMED_OR_INVALID",
        )
        self.assertEqual(
            verifier.classify_plan_state(
                base_errors=["failure"],
                active_present=False,
                active_git_errors=[],
                additions=[],
            ),
            "INVALID",
        )

    def test_live_ledger_pre_and_post_cleanup_snapshots(self):
        ledger = FakeLedger()
        pre = verifier.collect_live_ledger_snapshot(
            phase="pre_resource",
            repository="owner/repository",
            run_id=ledger.current_run_id,
            head_sha=ledger.current_head,
            head_branch=ledger.current_branch,
            fetch=ledger,
        )
        self.assertEqual(pre["schema"], verifier.LEDGER_SCHEMA)
        self.assertEqual(len(pre["legacy"]), 11)
        self.assertEqual(pre["legacy"][9]["runs"], [])
        self.assertEqual(
            pre["legacy"][10]["runs"][0]["id"],
            30696298423,
        )
        post = verifier.collect_live_ledger_snapshot(
            phase="post_cleanup_pre_upload",
            repository="owner/repository",
            run_id=ledger.current_run_id,
            head_sha=ledger.current_head,
            head_branch=ledger.current_branch,
            fetch=ledger,
            pre_snapshot=pre,
        )
        self.assertEqual(post["current"]["artifacts"], [])
        self.assertEqual(post["legacy"], pre["legacy"])

    def test_live_ledger_rejects_history_and_current_drift(self):
        cases = []

        v11 = FakeLedger()
        v11.extra_repository_runs.append(
            {"id": 123, "path": verifier.V11_WORKFLOW_PATH}
        )
        cases.append(("v11-run", v11))

        v12 = FakeLedger()
        v12.extra_repository_runs.append(
            {"id": 124, "path": verifier.V12_WORKFLOW_PATH}
        )
        cases.append(("v12-rerun", v12))

        v13 = FakeLedger()
        v13.extra_repository_runs.append(
            {"id": 125, "path": verifier.V13_WORKFLOW_PATH}
        )
        cases.append(("v13-rerun", v13))

        artifact = FakeLedger()
        artifact.current_artifacts.append({"id": 1})
        cases.append(("current-artifact", artifact))

        attempt = FakeLedger()
        attempt.current_workflow_id = 400000002
        original_call = attempt.__call__

        def rerun(requested: str):
            payload = original_call(requested)
            path = requested.split("?", 1)[0]
            if path == f"/actions/runs/{attempt.current_run_id}":
                payload["run_attempt"] = 2
            return payload

        cases.append(("current-rerun", rerun))

        zero_workflow = FakeLedger()
        zero_workflow.current_workflow_id = 0
        cases.append(("zero-workflow-id", zero_workflow))

        for name, fetch in cases:
            ledger = fetch if isinstance(fetch, FakeLedger) else attempt
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                verifier.collect_live_ledger_snapshot(
                    phase="pre_resource",
                    repository="owner/repository",
                    run_id=ledger.current_run_id,
                    head_sha=ledger.current_head,
                    head_branch=ledger.current_branch,
                    fetch=fetch,
                )

    def test_live_ledger_contract_copy_requires_private_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            contract = Path(temporary) / "contract.json"
            contract.write_bytes(verifier.TEMPLATE_PATH.read_bytes())
            contract.chmod(0o644)
            with (
                mock.patch.dict(
                    os.environ,
                    {"NOTEAI_V13_LEDGER_CONTRACT_PATH": str(contract)},
                ),
                self.assertRaises(ValueError),
            ):
                verifier._expected_ledger_contract()
            contract.chmod(0o400)
            with mock.patch.dict(
                os.environ,
                {"NOTEAI_V13_LEDGER_CONTRACT_PATH": str(contract)},
            ):
                self.assertEqual(
                    verifier._expected_ledger_contract()["schema"],
                    verifier.LEDGER_SCHEMA,
                )

    def test_pagination_rejects_duplicate_and_incomplete_pages(self):
        duplicate = [
            {"id": 1},
            {"id": 1},
        ]

        def duplicate_fetch(_path: str):
            return {"total_count": 2, "items": duplicate}

        with self.assertRaises(RuntimeError):
            verifier._paginate_api(duplicate_fetch, "/items", "items")

        def incomplete_fetch(_path: str):
            return {"total_count": 2, "items": [{"id": 1}]}

        with self.assertRaises(RuntimeError):
            verifier._paginate_api(incomplete_fetch, "/items", "items")

    def test_exact_checkpoint_receipt_and_activation_git_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def git(*arguments: str) -> str:
                return subprocess.run(
                    ["git", *arguments],
                    cwd=root,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ).stdout.strip()

            git("init", "--quiet")
            git("config", "user.name", "NoteAI V13 Test")
            git("config", "user.email", "noteai-v13@example.invalid")
            (root / ".seed").write_text("seed\n", encoding="utf-8")
            git("add", ".seed")
            git("commit", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")

            for relative in verifier.INERT_CHECKPOINT_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"checkpoint:{relative.as_posix()}\n", encoding="utf-8")
            git("add", "--all")
            git("commit", "--quiet", "-m", "exact checkpoint")
            checkpoint = git("rev-parse", "HEAD")

            for relative in verifier.INERT_RECEIPT_FILES:
                path = root / relative
                path.write_text(f"receipt:{relative.as_posix()}\n", encoding="utf-8")
            git("add", "--all")
            git("commit", "--quiet", "-m", "exact receipt")
            receipt = git("rev-parse", "HEAD")

            active_path = root / verifier.ACTIVE_REQUEST_PATH.relative_to(
                verifier.ROOT
            )
            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_bytes = verifier.TEMPLATE_PATH.read_bytes().replace(
                b"__DIRECT_PARENT_COMMIT__",
                receipt.encode("ascii"),
            )
            active_path.write_bytes(active_bytes)
            active = json.loads(active_bytes)
            git("add", active_path.relative_to(root).as_posix())
            git("commit", "--quiet", "-m", "exact activation")
            activation = git("rev-parse", "HEAD")

            with mock.patch.object(verifier, "PREDECESSOR_COMMIT", base):
                self.assertEqual(verifier._validate_same_anchor(root=root), [])
                observed_receipt, receipt_errors = verifier._validate_inert_receipt(
                    root=root
                )
                self.assertEqual(observed_receipt, receipt)
                self.assertEqual(receipt_errors, [])
                self.assertEqual(
                    verifier._validate_active_git(active, root=root),
                    [],
                )
                self.assertEqual(
                    verifier._validate_latest_stage_head(
                        active_present=True,
                        root=root,
                    ),
                    [],
                )

                git("branch", "pr-head", activation)
                git("checkout", "--quiet", "-b", "base-side", checkpoint)
                base_change = root / verifier.CHECKPOINT_IMMUTABLE_FILES[0]
                base_change.write_text("base-side drift\n", encoding="utf-8")
                git("add", base_change.relative_to(root).as_posix())
                git("commit", "--quiet", "-m", "base-side change")
                git("merge", "--quiet", "--no-ff", "pr-head", "-m", "synthetic PR")
                synthetic_merge = git("rev-parse", "HEAD")
                with mock.patch.dict(
                    os.environ,
                    {
                        "GITHUB_ACTIONS": "true",
                        "GITHUB_SHA": synthetic_merge,
                        "GITHUB_EVENT_NAME": "pull_request",
                        "GITHUB_REF": "refs/pull/1/merge",
                    },
                ):
                    self.assertEqual(
                        verifier._validate_same_anchor(root=root),
                        [],
                    )
                    self.assertEqual(
                        verifier._validate_active_git(active, root=root),
                        [],
                    )

                git("checkout", "--quiet", "pr-head")

                immutable = root / verifier.CHECKPOINT_IMMUTABLE_FILES[0]
                immutable.write_text("drift\n", encoding="utf-8")
                git("add", immutable.relative_to(root).as_posix())
                git("commit", "--quiet", "-m", "forbidden drift")
                self.assertTrue(verifier._validate_same_anchor(root=root))

            self.assertEqual(
                git("rev-parse", f"{checkpoint}^"),
                base,
            )

    def test_python_optimized_mode_has_no_assert_contract(self):
        source = verifier.PLAN_VERIFIER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("assert ", source)
        self.assertNotIn("__V13_", source)


if __name__ == "__main__":
    unittest.main()
