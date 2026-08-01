from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_export_plan_v12 as plan  # noqa: E402


class AdminDependencyCacheExportPlanV12Tests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    @staticmethod
    def _init(root: Path) -> str:
        AdminDependencyCacheExportPlanV12Tests._git(root, "init", "-q")
        AdminDependencyCacheExportPlanV12Tests._git(
            root,
            "config",
            "user.name",
            "NoteAI Test",
        )
        AdminDependencyCacheExportPlanV12Tests._git(
            root,
            "config",
            "user.email",
            "noteai@example.invalid",
        )
        (root / "README").write_text("seed\n", encoding="utf-8")
        AdminDependencyCacheExportPlanV12Tests._git(root, "add", "README")
        AdminDependencyCacheExportPlanV12Tests._git(
            root,
            "commit",
            "-q",
            "-m",
            "seed",
        )
        AdminDependencyCacheExportPlanV12Tests._git(
            root,
            "branch",
            "-M",
            "trunk",
        )
        return AdminDependencyCacheExportPlanV12Tests._git(
            root,
            "rev-parse",
            "HEAD",
        )

    @staticmethod
    def _template() -> dict:
        return json.loads(plan.TEMPLATE_PATH.read_text(encoding="utf-8"))

    def _fast_validate(self, **kwargs) -> list[str]:
        kwargs.setdefault("verify_git_state", False)
        with mock.patch.object(
            plan.v11_plan,
            "validate_plan",
            return_value=[],
        ):
            return plan.validate_plan(**kwargs)

    @staticmethod
    def _ledger_api_fixture() -> tuple[dict, object]:
        contract = plan._expected_ledger_contract()
        current_run_id = 40_000_000_001
        current_workflow_id = 400_000_001
        current_head = "a" * 40
        current_branch = "codex/quality-stabilization-real-chain"
        collections: dict[str, dict[str, object]] = {}
        singles: dict[str, dict[str, object]] = {}

        for version in contract["legacy"][:-1]:
            workflow_runs = []
            for expected in version["runs"]:
                workflow_runs.append(
                    {
                        key: copy.deepcopy(expected[key])
                        for key in (
                            "id",
                            "head_sha",
                            "event",
                            "run_attempt",
                            "status",
                            "conclusion",
                        )
                    }
                )
                jobs = [
                    {
                        "id": job_id,
                        "run_id": expected["id"],
                        "run_attempt": 1,
                        "head_sha": expected["head_sha"],
                        "status": "completed",
                        "conclusion": "failure",
                    }
                    for job_id in expected["job_ids"]
                ]
                collections[
                    f"/actions/runs/{expected['id']}/jobs?filter=all"
                ] = {"key": "jobs", "items": jobs}
                collections[f"/actions/runs/{expected['id']}/artifacts"] = {
                    "key": "artifacts",
                    "items": [],
                }
            collections[
                f"/actions/workflows/{version['workflow_ref']}/runs"
            ] = {"key": "workflow_runs", "items": workflow_runs}

        current_run = {
            "id": current_run_id,
            "workflow_id": current_workflow_id,
            "head_sha": current_head,
            "head_branch": current_branch,
            "path": plan.V12_WORKFLOW_PATH,
            "event": "push",
            "run_attempt": 1,
            "status": "in_progress",
            "conclusion": None,
        }
        singles[f"/actions/runs/{current_run_id}"] = copy.deepcopy(current_run)
        collections[f"/actions/workflows/{current_workflow_id}/runs"] = {
            "key": "workflow_runs",
            "items": [copy.deepcopy(current_run)],
        }
        collections[f"/actions/runs/{current_run_id}/artifacts"] = {
            "key": "artifacts",
            "items": [],
        }
        collections["/actions/runs"] = {
            "key": "workflow_runs",
            "items": [
                {
                    "id": current_run_id,
                    "path": plan.V12_WORKFLOW_PATH,
                },
                {
                    "id": current_run_id - 1,
                    "path": ".github/workflows/ci.yml",
                },
            ],
        }
        state = {
            "contract": contract,
            "collections": collections,
            "singles": singles,
            "calls": [],
            "current_run_id": current_run_id,
            "current_workflow_id": current_workflow_id,
            "current_head": current_head,
            "current_branch": current_branch,
        }

        def fetch(path: str) -> dict:
            state["calls"].append(path)
            if path in state["singles"]:
                return copy.deepcopy(state["singles"][path])
            if "&per_page=" in path:
                base, suffix = path.split("&per_page=", 1)
            elif "?per_page=" in path:
                base, suffix = path.split("?per_page=", 1)
            else:
                raise RuntimeError(f"unexpected fixture path: {path}")
            query = f"per_page={suffix}"
            parameters = dict(
                item.split("=", 1) for item in query.split("&")
            )
            per_page = int(parameters["per_page"])
            page = int(parameters["page"])
            collection = state["collections"].get(base)
            if collection is None:
                raise RuntimeError(f"unexpected fixture collection: {base}")
            items = collection["items"]
            start = (page - 1) * per_page
            return {
                "total_count": len(items),
                collection["key"]: copy.deepcopy(items[start : start + per_page]),
            }

        return state, fetch

    @staticmethod
    def _collect_fixture(
        state: dict,
        fetch: object,
        *,
        phase: str = "pre_resource",
        pre_snapshot: dict | None = None,
    ) -> dict:
        return plan.collect_live_ledger_snapshot(
            phase=phase,
            repository="noteai/example",
            run_id=state["current_run_id"],
            head_sha=state["current_head"],
            head_branch=state["current_branch"],
            fetch=fetch,
            pre_snapshot=pre_snapshot,
        )

    def test_exact_plan_passes_before_and_after_activation(self) -> None:
        self.assertEqual(plan.validate_plan(), [])
        self.assertEqual(plan.validate_v11_untriggered_supersession(), [])
        anchor, anchor_errors = plan._authority_anchor()
        self.assertEqual(anchor_errors, [])
        self.assertEqual(
            plan.v11_untriggered_supersession_state(),
            (
                "V11_UNTRIGGERED_SUPERSESSION_PENDING"
                if anchor is None
                else "V11_UNTRIGGERED_SUPERSEDED_EXACT"
            ),
        )
        additions = plan._true_additions(
            path=plan.ACTIVE_REQUEST_PATH.relative_to(plan.ROOT)
        )
        if plan.ACTIVE_REQUEST_PATH.exists():
            self.assertEqual(plan.plan_state(), "V12_ARMED_OR_TRIGGERED_EXACT")
            self.assertEqual(len(additions), 1)
        else:
            self.assertEqual(plan.plan_state(), "PREPARED_V12_NOT_TRIGGERED")
            self.assertEqual(additions, [])

    def test_v11_supersession_state_fails_closed(self) -> None:
        with mock.patch.object(
            plan,
            "_validate_legacy_history",
            return_value=["V11 frozen history drift"],
        ):
            self.assertEqual(
                plan.validate_v11_untriggered_supersession(),
                ["V11 frozen history drift"],
            )
            self.assertEqual(
                plan.v11_untriggered_supersession_state(),
                "INVALID",
            )

    def test_exact_control_and_reused_runtime_hashes_are_bound(self) -> None:
        for path, expected in (
            *plan.FROZEN_ACTIVATION_FILES,
            *plan.FROZEN_RUNTIME_FILES,
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    hashlib.sha256((plan.ROOT / path).read_bytes()).hexdigest(),
                    expected,
                )
        self.assertEqual(len(plan.FROZEN_ACTIVATION_FILES), 2)
        self.assertEqual(len(plan.FROZEN_RUNTIME_FILES), 4)
        self.assertEqual(len(plan.SAME_ANCHOR_FILES), 4)
        self.assertEqual(len(set(plan.SAME_ANCHOR_FILES)), 4)
        self.assertIn(
            Path("tools/verify_admin_dependency_cache_export_plan_v12.py"),
            plan.SAME_ANCHOR_FILES,
        )
        self.assertEqual(len(plan.INERT_CHECKPOINT_FILES), 11)
        self.assertEqual(len(set(plan.INERT_CHECKPOINT_FILES)), 11)
        self.assertEqual(len(plan.INERT_RECEIPT_FILES), 4)
        self.assertEqual(len(set(plan.INERT_RECEIPT_FILES)), 4)
        self.assertLessEqual(
            set(plan.INERT_RECEIPT_FILES),
            set(plan.INERT_CHECKPOINT_FILES),
        )
        self.assertEqual(len(plan.V12_NEW_CHECKPOINT_FILES), 4)
        self.assertEqual(len(set(plan.V12_NEW_CHECKPOINT_FILES)), 4)
        self.assertEqual(len(plan.CHECKPOINT_IMMUTABLE_FILES), 7)
        self.assertEqual(
            set(plan.CHECKPOINT_IMMUTABLE_FILES),
            set(plan.INERT_CHECKPOINT_FILES) - set(plan.INERT_RECEIPT_FILES),
        )

    def test_v2_through_v11_authority_is_lexically_frozen(self) -> None:
        self.assertEqual(
            len(plan.LEGACY_FROZEN_PATHS),
            len(set(plan.LEGACY_FROZEN_PATHS)),
        )
        for required in (
            Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v2.json"
            ),
            Path(
                ".github/release-requests/"
                "admin-5335bda-dependency-cache-v10.json"
            ),
            Path(".github/workflows/admin-dependency-cache-export-v10.yml"),
            Path("tools/verify_admin_dependency_cache_export_plan_v10.py"),
            Path("tools/verify_admin_dependency_cache_v10_failure_evidence.py"),
            Path(".github/workflows/admin-dependency-cache-export-v11.yml"),
            Path("tools/verify_admin_dependency_cache_export_plan_v11.py"),
        ):
            self.assertIn(required, plan.LEGACY_FROZEN_PATHS)
        self.assertTrue(
            all(
                not path.is_absolute() and ".." not in path.parts
                for path in plan.LEGACY_FROZEN_PATHS
            )
        )

    def test_workflow_is_request_only_and_uses_v10_concurrency_lock(self) -> None:
        workflow = plan.WORKFLOW_PATH.read_text(encoding="utf-8")
        parsed = yaml.load(workflow, Loader=yaml.BaseLoader)
        self.assertEqual(
            workflow.split("\npermissions:", 1)[0],
            plan.EXPECTED_WORKFLOW_HEADER,
        )
        self.assertEqual(
            parsed["concurrency"]["group"],
            "admin-dependency-cache-export-v10",
        )
        self.assertEqual(parsed["permissions"], {
            "contents": "read",
            "actions": "read",
        })
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertEqual(workflow.count("actions/upload-artifact@"), 1)
        self.assertEqual(workflow.count("retention-days: 1"), 1)
        self.assertLess(
            workflow.find("Remove V12 builders and all transient Docker state"),
            workflow.find(
                "Snapshot V2 through V12 ledgers after cleanup and before upload"
            ),
        )
        self.assertLess(
            workflow.find(
                "Snapshot V2 through V12 ledgers after cleanup and before upload"
            ),
            workflow.find(
                "Upload one-day V12 public-repository dependency cache artifact"
            ),
        )

    def test_workflow_ledgers_are_unfiltered_fully_paginated_and_twice_fresh(
        self,
    ) -> None:
        workflow = plan.WORKFLOW_PATH.read_text(encoding="utf-8")
        contract = plan._expected_ledger_contract()
        self.assertEqual(len(contract["legacy"][0]["runs"]), 2)
        self.assertEqual(contract["legacy"][-1], {
            "version": "v11",
            "workflow_path": plan.V11_WORKFLOW_PATH,
            "runs": [],
        })
        self.assertEqual(
            workflow.count(
                "Snapshot V2 through V12 ledgers before resource creation"
            ),
            1,
        )
        self.assertEqual(
            workflow.count(
                "Snapshot V2 through V12 ledgers after cleanup and before upload"
            ),
            1,
        )
        for forbidden in ("exclude_pull_requests=", "def paginate(path, key):"):
            self.assertNotIn(forbidden, workflow)
        self.assertNotIn("assert ", workflow)
        self.assertEqual(workflow.count("live-ledger"), 2)
        self.assertEqual(workflow.count("--phase pre_resource"), 1)
        self.assertEqual(
            workflow.count("--phase post_cleanup_pre_upload"),
            1,
        )
        self.assertIn(
            "if: ${{ always() && steps.cleanup.outputs.cleanup_passed == 'true' }}",
            workflow,
        )
        self.assertNotIn(
            'test -z "$(\n                  git diff-tree',
            workflow,
        )
        self.assertIn('test ! -s "${legacy_change_file}"', workflow)
        self.assertIn('test ! -s "${v12_change_file}"', workflow)
        self.assertIn("and .schema_version == 12", workflow)
        self.assertNotIn("and .schema_version == 11", workflow)
        self.assertIn(
            ".control_plane.inert_checkpoint_exact_changed_path_count == 11",
            workflow,
        )
        self.assertIn(
            ".control_plane.checkpoint_nonreceipt_immutable_path_count == 7",
            workflow,
        )
        self.assertIn("V2_WORKFLOW_HAS_TWO_IMMUTABLE_RUN_RECORDS", workflow)
        self.assertEqual(
            workflow.count("steps.control.outputs.ledger_verifier_copy"),
            2,
        )
        self.assertNotIn(
            "python3 tools/verify_admin_dependency_cache_export_plan_v12.py \\\n            live-ledger",
            workflow,
        )
        self.assertIn(".import.v11_rawjson_diagnostic.schema_version", workflow)
        self.assertNotIn(".import.v12_rawjson_diagnostic", workflow)

    def test_live_ledger_exact_fixture_passes_twice_with_fresh_reads(
        self,
    ) -> None:
        state, fetch = self._ledger_api_fixture()
        pre = self._collect_fixture(state, fetch)
        pre_call_count = len(state["calls"])
        post = self._collect_fixture(
            state,
            fetch,
            phase="post_cleanup_pre_upload",
            pre_snapshot=pre,
        )
        self.assertGreater(pre_call_count, 0)
        self.assertEqual(len(state["calls"]), pre_call_count * 2)
        self.assertEqual(pre["legacy"], post["legacy"])
        self.assertEqual(len(pre["legacy"][0]["runs"]), 2)
        self.assertEqual(pre["legacy"][0]["runs"][0]["jobs"], [])
        self.assertEqual(
            [job["id"] for job in pre["legacy"][0]["runs"][1]["jobs"]],
            [91033410635],
        )
        self.assertEqual(state["calls"].count(
            "/actions/runs?per_page=100&page=1"
        ), 4)

    def test_live_ledger_rejects_v2_inventory_job_and_artifact_drift(
        self,
    ) -> None:
        v2_workflow = "/actions/workflows/323980939/runs"
        parser_jobs = "/actions/runs/30572921215/jobs?filter=all"
        terminal_jobs = "/actions/runs/30591103183/jobs?filter=all"
        terminal_artifacts = "/actions/runs/30591103183/artifacts"

        def missing_parser(state: dict) -> None:
            state["collections"][v2_workflow]["items"].pop(0)

        def duplicate_terminal(state: dict) -> None:
            item = state["collections"][v2_workflow]["items"][1]
            state["collections"][v2_workflow]["items"].append(
                copy.deepcopy(item)
            )

        def changed_run(state: dict) -> None:
            state["collections"][v2_workflow]["items"][1]["head_sha"] = "b" * 40

        def parser_gains_job(state: dict) -> None:
            state["collections"][parser_jobs]["items"].append(
                {
                    "id": 1,
                    "run_id": 30572921215,
                    "run_attempt": 1,
                    "head_sha": "c0d049b56aa6efaff7133ac44a9fef7f010cd097",
                    "status": "completed",
                    "conclusion": "failure",
                }
            )

        def terminal_loses_job(state: dict) -> None:
            state["collections"][terminal_jobs]["items"].clear()

        def terminal_job_drifts(state: dict) -> None:
            state["collections"][terminal_jobs]["items"][0]["run_attempt"] = 2

        def terminal_gains_artifact(state: dict) -> None:
            state["collections"][terminal_artifacts]["items"].append({"id": 1})

        for name, mutate in (
            ("missing-parser", missing_parser),
            ("duplicate-terminal", duplicate_terminal),
            ("run-field", changed_run),
            ("parser-job", parser_gains_job),
            ("terminal-job-missing", terminal_loses_job),
            ("terminal-job-field", terminal_job_drifts),
            ("terminal-artifact", terminal_gains_artifact),
        ):
            with self.subTest(name=name):
                state, fetch = self._ledger_api_fixture()
                mutate(state)
                with self.assertRaises(RuntimeError):
                    self._collect_fixture(state, fetch)

    def test_live_ledger_rejects_each_v3_v10_run_inventory_drift(
        self,
    ) -> None:
        for version in plan._expected_ledger_contract()["legacy"][1:-1]:
            endpoint = f"/actions/workflows/{version['workflow_ref']}/runs"
            for mutation in ("missing", "extra", "field"):
                with self.subTest(version=version["version"], mutation=mutation):
                    state, fetch = self._ledger_api_fixture()
                    items = state["collections"][endpoint]["items"]
                    if mutation == "missing":
                        items.clear()
                    elif mutation == "extra":
                        extra = copy.deepcopy(items[0])
                        extra["id"] += 1_000_000
                        items.append(extra)
                    else:
                        items[0]["event"] = "pull_request"
                    with self.assertRaises(RuntimeError):
                        self._collect_fixture(state, fetch)

    def test_live_ledger_rejects_v11_run_inventory(self) -> None:
        state, fetch = self._ledger_api_fixture()
        state["collections"]["/actions/runs"]["items"].append(
            {"id": 40_000_000_002, "path": plan.V11_WORKFLOW_PATH}
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "V11 workflow run inventory is not zero",
        ):
            self._collect_fixture(state, fetch)

    def test_live_ledger_rejects_current_run_and_artifact_drift(self) -> None:
        for area, field, value in (
            ("single", "id", 1),
            ("single", "head_sha", "b" * 40),
            ("single", "head_branch", "main"),
            ("single", "path", ".github/workflows/other.yml"),
            ("single", "event", "workflow_dispatch"),
            ("single", "run_attempt", 2),
            ("single", "workflow_id", True),
            ("single", "status", "completed"),
            ("single", "conclusion", "failure"),
            ("list", "workflow_id", 1),
            ("list", "head_sha", "b" * 40),
            ("list", "head_branch", "main"),
            ("list", "path", ".github/workflows/other.yml"),
            ("list", "event", "workflow_dispatch"),
            ("list", "run_attempt", 2),
            ("list", "status", "completed"),
            ("list", "conclusion", "failure"),
        ):
            with self.subTest(area=area, field=field):
                state, fetch = self._ledger_api_fixture()
                if area == "single":
                    target = state["singles"][
                        f"/actions/runs/{state['current_run_id']}"
                    ]
                else:
                    target = state["collections"][
                        f"/actions/workflows/{state['current_workflow_id']}/runs"
                    ]["items"][0]
                target[field] = value
                with self.assertRaises(RuntimeError):
                    self._collect_fixture(state, fetch)

        state, fetch = self._ledger_api_fixture()
        current_runs = state["collections"][
            f"/actions/workflows/{state['current_workflow_id']}/runs"
        ]["items"]
        extra = copy.deepcopy(current_runs[0])
        extra["id"] += 1
        current_runs.append(extra)
        with self.assertRaisesRegex(RuntimeError, "V12 workflow run count changed"):
            self._collect_fixture(state, fetch)

        state, fetch = self._ledger_api_fixture()
        state["collections"][
            f"/actions/runs/{state['current_run_id']}/artifacts"
        ]["items"].append({"id": 1})
        with self.assertRaisesRegex(
            RuntimeError,
            "current artifact inventory changed",
        ):
            self._collect_fixture(state, fetch)

        state, fetch = self._ledger_api_fixture()
        state["collections"]["/actions/runs"]["items"][0]["path"] = None
        with self.assertRaisesRegex(RuntimeError, "repository run path changed"):
            self._collect_fixture(state, fetch)

    def test_live_ledger_pagination_is_complete_unique_and_strict(self) -> None:
        def paginated_fetch(
            count: int,
            *,
            total_for_page: dict[int, object] | None = None,
            mutate_page: object | None = None,
        ) -> object:
            items = [{"id": index} for index in range(1, count + 1)]

            def fetch(path: str) -> dict:
                query = path.split("?", 1)[1]
                parameters = dict(
                    item.split("=", 1) for item in query.split("&")
                )
                page = int(parameters["page"])
                per_page = int(parameters["per_page"])
                start = (page - 1) * per_page
                page_items = copy.deepcopy(items[start : start + per_page])
                if mutate_page is not None:
                    mutate_page(page, page_items)
                total = (
                    total_for_page.get(page, count)
                    if total_for_page is not None
                    else count
                )
                return {"total_count": total, "items": page_items}

            return fetch

        for count in (0, 1, 100, 101, 1_000):
            with self.subTest(valid_count=count):
                result = plan._paginate_api(
                    paginated_fetch(count),
                    "/items",
                    "items",
                )
                self.assertEqual(len(result), count)

        cases = (
            (
                "total-drift",
                paginated_fetch(101, total_for_page={2: 102}),
            ),
            (
                "incomplete",
                lambda _path: {"total_count": 2, "items": [{"id": 1}]},
            ),
            (
                "boolean-total",
                lambda _path: {"total_count": True, "items": []},
            ),
            (
                "boolean-id",
                lambda _path: {"total_count": 1, "items": [{"id": True}]},
            ),
            (
                "over-maximum",
                lambda _path: {"total_count": 1_001, "items": []},
            ),
            (
                "wrong-key",
                lambda _path: {"total_count": 0, "other": []},
            ),
        )
        for name, fetch in cases:
            with self.subTest(invalid=name), self.assertRaises(RuntimeError):
                plan._paginate_api(fetch, "/items", "items")

        def duplicate_second_page(page: int, items: list[dict]) -> None:
            if page == 2:
                items[0]["id"] = 1

        with self.assertRaisesRegex(RuntimeError, "ledger item id duplicated"):
            plan._paginate_api(
                paginated_fetch(101, mutate_page=duplicate_second_page),
                "/items",
                "items",
            )

    def test_repository_inventory_rejects_same_total_snapshot_shift(self) -> None:
        state, base_fetch = self._ledger_api_fixture()
        first = [
            {
                "id": item,
                "path": (
                    plan.V11_WORKFLOW_PATH
                    if item == 101
                    else ".github/workflows/ci.yml"
                ),
            }
            for item in range(1, 102)
        ]
        second = [
            {"id": item, "path": ".github/workflows/ci.yml"}
            for item in (*range(1, 101), 102)
        ]
        repo_calls = 0

        def shifting_fetch(path: str) -> dict:
            nonlocal repo_calls
            if path.startswith("/actions/runs?per_page="):
                repo_calls += 1
                items = first if repo_calls <= 2 else second
                query = path.split("?", 1)[1]
                parameters = dict(
                    item.split("=", 1) for item in query.split("&")
                )
                page = int(parameters["page"])
                start = (page - 1) * 100
                return {
                    "total_count": 101,
                    "workflow_runs": copy.deepcopy(items[start : start + 100]),
                }
            return base_fetch(path)

        with self.assertRaisesRegex(
            RuntimeError,
            "repository run inventory changed during snapshot",
        ):
            self._collect_fixture(state, shifting_fetch)

    def test_post_ledger_requires_untampered_pre_snapshot(self) -> None:
        state, fetch = self._ledger_api_fixture()
        pre = self._collect_fixture(state, fetch)
        for mutation in (
            "missing",
            "extra-root-field",
            "schema",
            "repository",
            "phase",
            "legacy",
            "contract",
            "current-empty",
            "current-head",
            "current-artifact",
        ):
            with self.subTest(mutation=mutation):
                candidate = copy.deepcopy(pre)
                if mutation == "missing":
                    candidate = None
                elif mutation == "extra-root-field":
                    candidate["extra"] = True
                elif mutation == "schema":
                    candidate["schema"] = "wrong"
                elif mutation == "repository":
                    candidate["repository"] = "other/repository"
                elif mutation == "phase":
                    candidate["phase"] = "post_cleanup_pre_upload"
                elif mutation == "legacy":
                    candidate["legacy"][0]["runs"][0]["head_sha"] = "b" * 40
                elif mutation == "contract":
                    candidate["contract_sha256"] = "0" * 64
                elif mutation == "current-empty":
                    candidate["current"] = {}
                elif mutation == "current-head":
                    candidate["current"]["head_sha"] = "b" * 40
                else:
                    candidate["current"]["artifacts"] = [{"id": 1}]
                with self.assertRaises(RuntimeError):
                    self._collect_fixture(
                        state,
                        fetch,
                        phase="post_cleanup_pre_upload",
                        pre_snapshot=candidate,
                    )

    def test_ledger_snapshot_io_is_exclusive_canonical_and_private(self) -> None:
        state, fetch = self._ledger_api_fixture()
        snapshot = self._collect_fixture(state, fetch)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.json"
            plan._write_snapshot(path, snapshot)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(plan._load_snapshot(path), snapshot)
            with self.assertRaises(FileExistsError):
                plan._write_snapshot(path, snapshot)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "snapshot mode changed"):
                plan._load_snapshot(path)

    def test_live_api_fetcher_is_uncached_and_response_bounded(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(
            plan.urllib.request,
            "urlopen",
            return_value=response,
        ) as urlopen:
            fetch = plan._live_api_fetcher(
                repository="owner/repository",
                token="redacted-test-token",
                deadline=plan.time.monotonic() + 5,
            )
            self.assertEqual(fetch("/actions/runs/1"), {})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Cache-control"), "no-cache")
        self.assertEqual(request.get_header("Pragma"), "no-cache")
        response.__enter__.return_value.read.assert_called_once_with(
            plan.LEDGER_RESPONSE_MAXIMUM_BYTES + 1
        )

        oversized = mock.MagicMock()
        oversized.__enter__.return_value.read.return_value = b"{}\n"
        with (
            mock.patch.object(plan, "LEDGER_RESPONSE_MAXIMUM_BYTES", 2),
            mock.patch.object(
                plan.urllib.request,
                "urlopen",
                return_value=oversized,
            ),
        ):
            fetch = plan._live_api_fetcher(
                repository="owner/repository",
                token="redacted-test-token",
                deadline=plan.time.monotonic() + 5,
            )
            with self.assertRaisesRegex(RuntimeError, "response is too large"):
                fetch("/actions/runs/1")

    def test_live_ledger_runner_is_standalone_after_release_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = Path(temporary) / "ledger-verifier.py"
            runner.write_bytes(plan.PLAN_VERIFIER_PATH.read_bytes())
            probe = (
                "import runpy,sys; "
                "path=sys.argv[1]; "
                "sys.argv=[path,'live-ledger']; "
                "value=runpy.run_path(path); "
                "print(value['LEDGER_SCHEMA'])"
            )
            result = subprocess.run(
                [sys.executable, "-c", probe, str(runner)],
                cwd=temporary,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(result.stdout.strip(), plan.LEDGER_SCHEMA)

    def test_workflow_has_exact_sibling_targets_and_frozen_full_replay(self) -> None:
        workflow = plan.WORKFLOW_PATH.read_text(encoding="utf-8")
        export = plan.EXPORT_HELPER_PATH.read_text(encoding="utf-8")
        import_helper = plan.IMPORT_HELPER_PATH.read_text(encoding="utf-8")
        for helper in (export, import_helper):
            self.assertIn("noteai-cache-export-anchor", helper)
            self.assertIn("noteai-cache-import-observer", helper)
            self.assertIn(
                "c665ac4356bec6751d44878a416bbaa278a77df77754f5461ba0adb13f43c2a0",
                helper,
            )
            self.assertNotIn("--no-cache-filter", helper)
        self.assertIn("--target noteai-cache-export-anchor", export)
        self.assertIn("--target noteai-cache-import-observer", import_helper)
        self.assertEqual(import_helper.count("--target runtime-common"), 1)
        self.assertEqual(import_helper.count("--cache-from"), 1)
        self.assertIn("NOTEAI_V10_BUNDLE_VERIFIER_PATH", workflow)

    def test_template_exact_semantics_pass(self) -> None:
        self.assertEqual(plan._template_errors(self._template()), [])

    def test_template_mutations_fail_closed(self) -> None:
        cases = (
            ("schema", ("schema_version",), 10),
            (
                "predecessor",
                ("predecessor", "run_id"),
                1,
            ),
            (
                "combined",
                ("recovery_basis", "combined_dockerfile_sha256"),
                "0" * 64,
            ),
            (
                "pair",
                (
                    "build_evidence_recovery",
                    "runtime_pip_pair_classification_required",
                ),
                "SAME_DIGEST_NONCACHED",
            ),
            (
                "latest-stage",
                (
                    "control_plane",
                    "canonical_branch_latest_exact_stage_required",
                ),
                False,
            ),
            (
                "predicate",
                (
                    "build_evidence_recovery",
                    "runtime_pip_cached_false_accepted",
                ),
                True,
            ),
            (
                "deployment",
                ("deployment_authorized",),
                True,
            ),
        )
        for name, keys, value in cases:
            with self.subTest(name=name):
                payload = copy.deepcopy(self._template())
                target = payload
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.assertTrue(plan._template_errors(payload))

    def test_workflow_mutations_fail_closed(self) -> None:
        workflow = plan.WORKFLOW_PATH.read_text(encoding="utf-8")
        for name, mutated in (
            (
                "manual",
                workflow.replace("on:\n", "on:\n  workflow_dispatch:\n", 1),
            ),
            (
                "concurrency",
                workflow.replace(
                    "group: admin-dependency-cache-export-v10",
                    "group: admin-dependency-cache-export-v12",
                    1,
                ),
            ),
            (
                "upload-before-cleanup",
                workflow.replace(
                    "Remove V12 builders and all transient Docker state",
                    "Destroy transient Docker state",
                    1,
                ),
            ),
            (
                "workspace-live-ledger",
                workflow.replace(
                    "steps.control.outputs.ledger_verifier_copy",
                    "tools/verify_admin_dependency_cache_export_plan_v12.py",
                    1,
                ),
            ),
            (
                "wrong-runtime-diagnostic",
                workflow.replace(
                    ".import.v11_rawjson_diagnostic.schema_version",
                    ".import.v12_rawjson_diagnostic.schema_version",
                    1,
                ),
            ),
            ("push", workflow + "\ndocker push forbidden\n"),
        ):
            with self.subTest(name=name):
                self.assertTrue(plan._workflow_errors(mutated))

    def test_exact_active_request_passes_without_git(self) -> None:
        parent = "1" * 40
        active = self._template()
        active["plan_checkpoint_commit"] = parent
        self.assertEqual(
            self._fast_validate(active_request=active),
            [],
        )

    def test_active_request_parent_and_bytes_fail_closed(self) -> None:
        active = self._template()
        active["plan_checkpoint_commit"] = "not-a-commit"
        self.assertIn(
            "V12 active request differs from reviewed template",
            self._fast_validate(active_request=active),
        )
        active = self._template()
        active["plan_checkpoint_commit"] = "2" * 40
        active["deployment_authorized"] = True
        self.assertIn(
            "V12 active request differs from reviewed template",
            self._fast_validate(active_request=active),
        )

    def test_state_classifier_is_fail_closed(self) -> None:
        self.assertEqual(
            plan.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=[],
            ),
            "PREPARED_V12_NOT_TRIGGERED",
        )
        self.assertEqual(
            plan.classify_plan_state(
                base_errors=[],
                active_present=True,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V12_ARMED_OR_TRIGGERED_EXACT",
        )
        self.assertEqual(
            plan.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V12_CONSUMED_OR_INVALID",
        )
        for kwargs in (
            {
                "base_errors": ["bad"],
                "active_present": False,
                "active_git_errors": [],
                "additions": [],
            },
            {
                "base_errors": [],
                "active_present": True,
                "active_git_errors": ["bad"],
                "additions": ["a" * 40],
            },
            {
                "base_errors": [],
                "active_present": True,
                "active_git_errors": [],
                "additions": ["a" * 40, "b" * 40],
            },
        ):
            self.assertEqual(plan.classify_plan_state(**kwargs), "INVALID")

    def test_partial_authority_set_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._init(root)
            first = Path("authority/first")
            second = Path("authority/second")
            (root / first).parent.mkdir(parents=True)
            (root / first).write_text("first\n", encoding="utf-8")
            self._git(root, "add", first.as_posix())
            self._git(root, "commit", "-q", "-m", "partial")
            with mock.patch.object(
                plan,
                "SAME_ANCHOR_FILES",
                (first, second),
            ):
                anchor, errors = plan._authority_anchor(root=root)
            self.assertIsNone(anchor)
            self.assertEqual(
                errors,
                ["V12 frozen authorities are only partially present"],
            )

    def test_inert_checkpoint_exact_delta_and_modes_fail_closed(self) -> None:
        for mutation in ("none", "extra", "mode"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                predecessor = self._init(root)
                authority_a = Path("authority/a")
                authority_b = Path("authority/b")
                receipt_a = Path("state/a")
                receipt_b = Path("state/b")
                checkpoint = (
                    authority_a,
                    authority_b,
                    receipt_a,
                    receipt_b,
                )
                for relative in checkpoint:
                    (root / relative).parent.mkdir(parents=True, exist_ok=True)
                    (root / relative).write_text(
                        relative.as_posix() + "\n",
                        encoding="utf-8",
                    )
                if mutation == "extra":
                    (root / "unexpected").write_text("extra\n", encoding="utf-8")
                if mutation == "mode":
                    (root / receipt_b).chmod(0o755)
                self._git(root, "add", ".")
                self._git(root, "commit", "-q", "-m", "checkpoint")
                hashes = tuple(
                    (
                        relative,
                        hashlib.sha256((root / relative).read_bytes()).hexdigest(),
                    )
                    for relative in (authority_a, authority_b)
                )
                with mock.patch.multiple(
                    plan,
                    V11_INERT_CHECKPOINT=predecessor,
                    SAME_ANCHOR_FILES=(authority_a, authority_b),
                    FROZEN_ACTIVATION_FILES=hashes,
                    INERT_CHECKPOINT_FILES=checkpoint,
                    INERT_RECEIPT_FILES=(receipt_a, receipt_b),
                    CHECKPOINT_IMMUTABLE_FILES=(authority_a, authority_b),
                ), mock.patch.dict(
                    os.environ,
                    {"GITHUB_ACTIONS": "false"},
                ):
                    errors = plan._validate_same_anchor(root=root)
                if mutation == "none":
                    self.assertEqual(errors, [])
                elif mutation == "extra":
                    self.assertIn(
                        "V12 inert checkpoint is not the exact 11-file delta",
                        errors,
                    )
                else:
                    self.assertIn(
                        f"V12 inert checkpoint mode changed: {receipt_b}",
                        errors,
                    )

    def _activation_fixture(
        self,
        root: Path,
        *,
        with_receipt: bool,
    ) -> tuple[dict, dict[str, object]]:
        predecessor = self._init(root)
        workflow = Path("workflow.yml")
        template = Path("template.json")
        handoff = Path("handoff.md")
        readiness = Path("readiness.json")
        gate = Path("gate.py")
        active_relative = Path("requests/active.json")
        (root / template).write_text(
            '{\n  "plan_checkpoint_commit": "__DIRECT_PARENT_COMMIT__"\n}\n',
            encoding="utf-8",
        )
        (root / workflow).write_text("workflow\n", encoding="utf-8")
        (root / handoff).write_text("anchor\n", encoding="utf-8")
        (root / readiness).write_text("anchor\n", encoding="utf-8")
        (root / gate).write_text("anchor\n", encoding="utf-8")
        self._git(root, "add", ".")
        self._git(root, "commit", "-q", "-m", "checkpoint")
        anchor = self._git(root, "rev-parse", "HEAD")
        parent = anchor
        if with_receipt:
            (root / handoff).write_text("receipt\n", encoding="utf-8")
            (root / readiness).write_text("receipt\n", encoding="utf-8")
            self._git(root, "add", handoff.as_posix(), readiness.as_posix())
            self._git(root, "commit", "-q", "-m", "receipt")
            parent = self._git(root, "rev-parse", "HEAD")
        active_payload = {
            "plan_checkpoint_commit": parent,
        }
        (root / active_relative).parent.mkdir(parents=True)
        (root / active_relative).write_bytes(
            (root / template).read_bytes().replace(
                b"__DIRECT_PARENT_COMMIT__",
                parent.encode("ascii"),
            )
        )
        self._git(root, "add", active_relative.as_posix())
        self._git(root, "commit", "-q", "-m", "activation")
        frozen = tuple(
            (
                relative,
                hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            )
            for relative in (workflow, template)
        )
        return active_payload, {
            "ROOT": root,
            "V11_INERT_CHECKPOINT": predecessor,
            "SAME_ANCHOR_FILES": (workflow, template),
            "FROZEN_ACTIVATION_FILES": frozen,
            "INERT_CHECKPOINT_FILES": (
                workflow,
                template,
                handoff,
                readiness,
                gate,
            ),
            "INERT_RECEIPT_FILES": (handoff, readiness),
            "CHECKPOINT_IMMUTABLE_FILES": (workflow, template, gate),
            "V12_NEW_CHECKPOINT_FILES": (workflow, template),
            "ACTIVE_REQUEST_PATH": root / active_relative,
            "TEMPLATE_PATH": root / template,
        }

    def test_activation_requires_exact_direct_receipt(self) -> None:
        for with_receipt in (True, False):
            with self.subTest(with_receipt=with_receipt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                active, patches = self._activation_fixture(
                    root,
                    with_receipt=with_receipt,
                )
                with mock.patch.multiple(plan, **patches), mock.patch.dict(
                    os.environ,
                    {"GITHUB_ACTIONS": "false"},
                ):
                    errors = plan._validate_active_git(active, root=root)
                if with_receipt:
                    self.assertEqual(errors, [])
                else:
                    self.assertIn(
                        "V12 activation parent is not the exact inert receipt",
                        errors,
                    )

    def test_prepared_state_rejects_checkpoint_pollution_and_prior_addition(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            predecessor = self._init(root)
            authority_a = Path("authority/a")
            authority_b = Path("authority/b")
            checkpoint_only = Path("tests/v12.py")
            (root / checkpoint_only).parent.mkdir(parents=True)
            (root / checkpoint_only).write_text("polluted\n", encoding="utf-8")
            self._git(root, "add", checkpoint_only.as_posix())
            self._git(root, "commit", "-q", "-m", "partial checkpoint")
            with mock.patch.multiple(
                plan,
                ROOT=root,
                V11_INERT_CHECKPOINT=predecessor,
                SAME_ANCHOR_FILES=(authority_a, authority_b),
                V12_NEW_CHECKPOINT_FILES=(
                    authority_a,
                    authority_b,
                    checkpoint_only,
                ),
                ACTIVE_REQUEST_PATH=root / "requests/active.json",
            ), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
                errors = plan._validate_same_anchor(root=root)
            self.assertIn(
                "V12 prepared branch HEAD is not the V11 inert checkpoint",
                errors,
            )
            self.assertTrue(
                any("prior addition history" in error for error in errors)
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            predecessor = self._init(root)
            authority_a = Path("authority/a")
            authority_b = Path("authority/b")
            self._git(root, "checkout", "-q", "-b", "pollution")
            for relative in (authority_a, authority_b):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text("added\n", encoding="utf-8")
            self._git(root, "add", ".")
            self._git(root, "commit", "-q", "-m", "add authorities")
            for relative in (authority_a, authority_b):
                (root / relative).unlink()
            self._git(root, "add", "-u")
            self._git(root, "commit", "-q", "-m", "delete authorities")
            self._git(root, "checkout", "-q", "trunk")
            with mock.patch.multiple(
                plan,
                ROOT=root,
                V11_INERT_CHECKPOINT=predecessor,
                SAME_ANCHOR_FILES=(authority_a, authority_b),
                V12_NEW_CHECKPOINT_FILES=(authority_a, authority_b),
                ACTIVE_REQUEST_PATH=root / "requests/active.json",
            ), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
                errors = plan._validate_same_anchor(root=root)
            self.assertTrue(
                any("prior addition history" in error for error in errors)
            )

    def test_side_chain_merge_is_rejected_but_github_pr_projection_passes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active, patches = self._activation_fixture(
                root,
                with_receipt=True,
            )
            activation = self._git(root, "rev-parse", "HEAD")
            predecessor = str(patches["V11_INERT_CHECKPOINT"])
            self._git(root, "branch", "recovery", activation)
            self._git(root, "checkout", "-q", "recovery")
            self._git(root, "branch", "-f", "trunk", predecessor)
            self._git(root, "checkout", "-q", "trunk")
            (root / "README").write_text("trunk\n", encoding="utf-8")
            self._git(root, "add", "README")
            self._git(root, "commit", "-q", "-m", "trunk advance")
            self._git(
                root,
                "merge",
                "-q",
                "--no-ff",
                "recovery",
                "-m",
                "synthetic projection",
            )
            merge = self._git(root, "rev-parse", "HEAD")

            with mock.patch.multiple(plan, **patches), mock.patch.dict(
                os.environ,
                {"GITHUB_ACTIONS": "false"},
            ):
                self.assertIn(
                    "V12 frozen anchor is not on the branch first-parent chain",
                    plan._validate_same_anchor(root=root),
                )
                _receipt, receipt_errors = plan._validate_inert_receipt(root=root)
                self.assertIn(
                    "V12 inert receipt is not on the branch first-parent chain",
                    receipt_errors,
                )
                self.assertIn(
                    "V12 activation is not on the branch first-parent chain",
                    plan._validate_active_git(active, root=root),
                )
                self.assertIn(
                    "V12 canonical branch HEAD is not the latest exact stage",
                    plan._validate_latest_stage_head(
                        active_present=True,
                        root=root,
                    ),
                )

            github_pr = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_REF": "refs/pull/1/merge",
                "GITHUB_SHA": merge,
            }
            with mock.patch.multiple(plan, **patches), mock.patch.dict(
                os.environ,
                github_pr,
            ):
                self.assertEqual(plan._validate_same_anchor(root=root), [])
                receipt, receipt_errors = plan._validate_inert_receipt(root=root)
                self.assertIsNotNone(receipt)
                self.assertEqual(receipt_errors, [])
                self.assertEqual(
                    plan._validate_active_git(active, root=root),
                    [],
                )
                self.assertEqual(
                    plan._validate_latest_stage_head(
                        active_present=True,
                        root=root,
                    ),
                    [],
                )

    def test_each_exact_stage_must_remain_the_canonical_head(self) -> None:
        for stage in ("checkpoint", "receipt", "activation"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _active, patches = self._activation_fixture(
                    root,
                    with_receipt=True,
                )
                activation = self._git(root, "rev-parse", "HEAD")
                receipt = self._git(root, "rev-parse", f"{activation}^")
                checkpoint = self._git(root, "rev-parse", f"{receipt}^")
                selected = {
                    "checkpoint": checkpoint,
                    "receipt": receipt,
                    "activation": activation,
                }[stage]
                self._git(root, "checkout", "-q", "-b", f"stage-{stage}", selected)
                (root / "unrelated").write_text("later\n", encoding="utf-8")
                self._git(root, "add", "unrelated")
                self._git(root, "commit", "-q", "-m", "later unrelated")
                with mock.patch.multiple(plan, **patches), mock.patch.dict(
                    os.environ,
                    {"GITHUB_ACTIONS": "false"},
                ):
                    errors = plan._validate_latest_stage_head(
                        active_present=stage == "activation",
                        root=root,
                    )
                self.assertEqual(
                    errors,
                    ["V12 canonical branch HEAD is not the latest exact stage"],
                )

    def test_post_activation_checkpoint_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _active, patches = self._activation_fixture(
                root,
                with_receipt=True,
            )
            gate = root / "gate.py"
            gate.write_text("tampered\n", encoding="utf-8")
            self._git(root, "add", "gate.py")
            self._git(root, "commit", "-q", "-m", "tamper checkpoint path")
            with mock.patch.multiple(plan, **patches), mock.patch.dict(
                os.environ,
                {"GITHUB_ACTIONS": "false"},
            ):
                errors = plan._validate_same_anchor(root=root)
            self.assertIn(
                "V12 immutable checkpoint path changed after add anchor",
                errors,
            )

    def test_active_request_worktree_mode_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "active.json"
            path.write_text("{}\n", encoding="utf-8")
            path.chmod(0o755)
            present, value, errors = plan._active_request(path=path)
            self.assertTrue(present)
            self.assertIsNone(value)
            self.assertEqual(
                errors,
                ["V12 active request worktree mode changed"],
            )

    def test_true_addition_ignores_synthetic_merge_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = self._init(root)
            self._git(root, "checkout", "-q", "-b", "feature")
            relative = Path("frozen/value.txt")
            (root / relative).parent.mkdir(parents=True)
            (root / relative).write_text("value\n", encoding="utf-8")
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "anchor")
            anchor = self._git(root, "rev-parse", "HEAD")
            self._git(root, "checkout", "-q", "-b", "main", seed)
            (root / "README").write_text("main\n", encoding="utf-8")
            self._git(root, "add", "README")
            self._git(root, "commit", "-q", "-m", "main")
            self._git(root, "merge", "-q", "--no-ff", "feature", "-m", "synthetic")
            self.assertEqual(
                plan._true_additions(root=root, path=relative),
                [anchor],
            )
            self.assertEqual(
                plan._lineage_path_changes(
                    root=root,
                    anchor=anchor,
                    paths=(relative,),
                ),
                [],
            )

    def test_lineage_detects_merged_side_branch_change_and_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._init(root)
            relative = Path("frozen/value.txt")
            (root / relative).parent.mkdir(parents=True)
            (root / relative).write_text("value\n", encoding="utf-8")
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "anchor")
            anchor = self._git(root, "rev-parse", "HEAD")
            self._git(root, "checkout", "-q", "-b", "side")
            (root / relative).write_text("tampered\n", encoding="utf-8")
            self._git(root, "add", relative.as_posix())
            self._git(root, "commit", "-q", "-m", "side tamper")
            side = self._git(root, "rev-parse", "HEAD")
            self._git(root, "checkout", "-q", "trunk")
            (root / "README").write_text("receipt\n", encoding="utf-8")
            self._git(root, "add", "README")
            self._git(root, "commit", "-q", "-m", "receipt")
            self._git(root, "merge", "-q", "--no-ff", "side", "-m", "merge side")
            changes = plan._lineage_path_changes(
                root=root,
                anchor=anchor,
                paths=(relative,),
            )
            self.assertIn(side, changes)

    def test_true_addition_rejects_merge_only_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = self._init(root)
            relative = Path("frozen/value.txt")
            self._git(root, "checkout", "-q", "-b", "left")
            (root / "left").write_text("left\n", encoding="utf-8")
            self._git(root, "add", "left")
            self._git(root, "commit", "-q", "-m", "left")
            left = self._git(root, "rev-parse", "HEAD")
            self._git(root, "checkout", "-q", "-b", "right", seed)
            (root / "right").write_text("right\n", encoding="utf-8")
            self._git(root, "add", "right")
            self._git(root, "commit", "-q", "-m", "right")
            right = self._git(root, "rev-parse", "HEAD")
            tree_root = Path(temporary) / "tree"
            tree_root.mkdir()
            self._git(root, "read-tree", "--empty")
            # Restore both parents' trees into the index, then add only at merge.
            self._git(root, "read-tree", "-m", left, right)
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text("merge-only\n", encoding="utf-8")
            self._git(root, "add", relative.as_posix())
            tree = self._git(root, "write-tree")
            merge = subprocess.run(
                ["git", "commit-tree", tree, "-p", left, "-p", right],
                cwd=root,
                check=True,
                input="merge-only\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            self._git(root, "reset", "-q", "--hard", merge)
            self.assertEqual(
                plan._true_additions(root=root, path=relative),
                [merge],
            )

    def test_predecessor_errors_propagate_without_relaxation(self) -> None:
        with mock.patch.object(
            plan.v11_plan,
            "validate_plan",
            return_value=["V11 plan drift"],
        ):
            errors = plan.validate_plan(verify_git_state=False)
        self.assertIn("V11 plan drift", errors)

    def test_frozen_worktree_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("value\n", encoding="utf-8")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                plan._regular_file(link)


if __name__ == "__main__":
    unittest.main()
