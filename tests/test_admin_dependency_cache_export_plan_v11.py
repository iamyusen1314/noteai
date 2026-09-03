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

import verify_admin_dependency_cache_export_plan_v11 as plan  # noqa: E402
import verify_admin_dependency_cache_export_plan_v12 as v12_plan  # noqa: E402


class AdminDependencyCacheExportPlanV11Tests(unittest.TestCase):
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
        AdminDependencyCacheExportPlanV11Tests._git(root, "init", "-q")
        AdminDependencyCacheExportPlanV11Tests._git(
            root,
            "config",
            "user.name",
            "NoteAI Test",
        )
        AdminDependencyCacheExportPlanV11Tests._git(
            root,
            "config",
            "user.email",
            "noteai@example.invalid",
        )
        (root / "README").write_text("seed\n", encoding="utf-8")
        AdminDependencyCacheExportPlanV11Tests._git(root, "add", "README")
        AdminDependencyCacheExportPlanV11Tests._git(
            root,
            "commit",
            "-q",
            "-m",
            "seed",
        )
        AdminDependencyCacheExportPlanV11Tests._git(
            root,
            "branch",
            "-M",
            "trunk",
        )
        return AdminDependencyCacheExportPlanV11Tests._git(
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
            plan.v10_failure,
            "load_strict",
            return_value={},
        ), mock.patch.object(
            plan.v10_failure,
            "verify",
            return_value=[],
        ), mock.patch.object(
            plan.v10_plan,
            "validate_plan",
            return_value=[],
        ):
            return plan.validate_plan(**kwargs)

    def test_exact_plan_is_preserved_under_explicit_v12_supersession(self) -> None:
        branch_head = v12_plan._canonical_branch_head(ROOT)
        if branch_head == v12_plan.V11_INERT_CHECKPOINT:
            self.assertEqual(plan.validate_plan(), [])
            self.assertEqual(plan.plan_state(), "PREPARED_V11_NOT_TRIGGERED")
        else:
            v11_errors = plan.validate_plan()
            self.assertIn(
                "V11 immutable checkpoint path changed after add anchor",
                v11_errors,
            )
        self.assertEqual(plan.validate_plan(verify_git_state=False), [])
        self.assertEqual(
            v12_plan.validate_v11_untriggered_supersession(),
            [],
        )
        self.assertEqual(
            v12_plan.v11_untriggered_supersession_state(),
            (
                "V11_UNTRIGGERED_SUPERSESSION_PENDING"
                if branch_head == v12_plan.V11_INERT_CHECKPOINT
                else "V11_UNTRIGGERED_SUPERSEDED_EXACT"
            ),
        )
        self.assertEqual(v12_plan.validate_plan(), [])
        additions = plan._true_additions(
            path=plan.ACTIVE_REQUEST_PATH.relative_to(plan.ROOT)
        )
        self.assertFalse(plan.ACTIVE_REQUEST_PATH.exists())
        self.assertEqual(additions, [])
        self.assertIn(
            v12_plan.plan_state(),
            {"PREPARED_V12_NOT_TRIGGERED", "V12_ARMED_OR_TRIGGERED_EXACT"},
        )

    def test_exact_six_hashes_and_seven_anchor_paths_are_bound(self) -> None:
        for path, expected in plan.FROZEN_ACTIVATION_FILES:
            with self.subTest(path=path):
                self.assertEqual(
                    hashlib.sha256((plan.ROOT / path).read_bytes()).hexdigest(),
                    expected,
                )
        self.assertEqual(len(plan.FROZEN_ACTIVATION_FILES), 6)
        self.assertEqual(len(plan.SAME_ANCHOR_FILES), 7)
        self.assertEqual(len(set(plan.SAME_ANCHOR_FILES)), 7)
        self.assertIn(
            Path("tools/verify_admin_dependency_cache_export_plan_v11.py"),
            plan.SAME_ANCHOR_FILES,
        )
        self.assertEqual(len(plan.INERT_CHECKPOINT_FILES), 15)
        self.assertEqual(len(set(plan.INERT_CHECKPOINT_FILES)), 15)
        self.assertEqual(len(plan.INERT_RECEIPT_FILES), 4)
        self.assertEqual(len(set(plan.INERT_RECEIPT_FILES)), 4)
        self.assertLessEqual(
            set(plan.INERT_RECEIPT_FILES),
            set(plan.INERT_CHECKPOINT_FILES),
        )
        self.assertEqual(len(plan.V11_NEW_CHECKPOINT_FILES), 9)
        self.assertEqual(len(set(plan.V11_NEW_CHECKPOINT_FILES)), 9)
        self.assertEqual(len(plan.CHECKPOINT_IMMUTABLE_FILES), 11)
        self.assertEqual(
            set(plan.CHECKPOINT_IMMUTABLE_FILES),
            set(plan.INERT_CHECKPOINT_FILES) - set(plan.INERT_RECEIPT_FILES),
        )

    def test_v2_through_v10_authority_is_lexically_frozen(self) -> None:
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
            workflow.find("Remove V11 builders and all transient Docker state"),
            workflow.find(
                "Snapshot V2 through V11 ledgers after cleanup and before upload"
            ),
        )
        self.assertLess(
            workflow.find(
                "Snapshot V2 through V11 ledgers after cleanup and before upload"
            ),
            workflow.find(
                "Upload one-day V11 public-repository dependency cache artifact"
            ),
        )

    def test_workflow_ledgers_are_unfiltered_fully_paginated_and_twice_fresh(
        self,
    ) -> None:
        workflow = plan.WORKFLOW_PATH.read_text(encoding="utf-8")
        for token in (
            "30591103183",
            "30596283342",
            "30599069993",
            "30606218502",
            "30613707689",
            "30622876575",
            "30632611051",
            "30651679657",
            "30672160324",
        ):
            self.assertGreaterEqual(workflow.count(token), 2)
        self.assertEqual(
            workflow.count(
                "Snapshot V2 through V11 ledgers before resource creation"
            ),
            1,
        )
        self.assertEqual(
            workflow.count(
                "Snapshot V2 through V11 ledgers after cleanup and before upload"
            ),
            1,
        )
        for forbidden in (
            'branch="',
            "head_sha=",
            "exclude_pull_requests=",
            "event=push",
        ):
            self.assertNotIn(forbidden, workflow)
        self.assertGreaterEqual(workflow.count("len(items) == total"), 2)
        self.assertGreaterEqual(workflow.count("artifacts == []"), 2)
        self.assertNotIn("assert ", workflow)
        self.assertEqual(
            workflow.count("deadline = time.monotonic() + budget_seconds"),
            2,
        )
        self.assertGreaterEqual(
            workflow.count("V11 ledger deadline exceeded"),
            2,
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
        self.assertIn('test ! -s "${v11_change_file}"', workflow)

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
                    "group: admin-dependency-cache-export-v11",
                    1,
                ),
            ),
            (
                "upload-before-cleanup",
                workflow.replace(
                    "Remove V11 builders and all transient Docker state",
                    "Destroy transient Docker state",
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
            "V11 active request differs from reviewed template",
            self._fast_validate(active_request=active),
        )
        active = self._template()
        active["plan_checkpoint_commit"] = "2" * 40
        active["deployment_authorized"] = True
        self.assertIn(
            "V11 active request differs from reviewed template",
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
            "PREPARED_V11_NOT_TRIGGERED",
        )
        self.assertEqual(
            plan.classify_plan_state(
                base_errors=[],
                active_present=True,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V11_ARMED_OR_TRIGGERED_EXACT",
        )
        self.assertEqual(
            plan.classify_plan_state(
                base_errors=[],
                active_present=False,
                active_git_errors=[],
                additions=["a" * 40],
            ),
            "V11_CONSUMED_OR_INVALID",
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
                ["V11 frozen authorities are only partially present"],
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
                    V10_TERMINAL_RECEIPT=predecessor,
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
                        "V11 inert checkpoint is not the exact 15-file delta",
                        errors,
                    )
                else:
                    self.assertIn(
                        f"V11 inert checkpoint mode changed: {receipt_b}",
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
            "V10_TERMINAL_RECEIPT": predecessor,
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
            "V11_NEW_CHECKPOINT_FILES": (workflow, template),
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
                        "V11 activation parent is not the exact inert receipt",
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
            checkpoint_only = Path("tests/v11.py")
            (root / checkpoint_only).parent.mkdir(parents=True)
            (root / checkpoint_only).write_text("polluted\n", encoding="utf-8")
            self._git(root, "add", checkpoint_only.as_posix())
            self._git(root, "commit", "-q", "-m", "partial checkpoint")
            with mock.patch.multiple(
                plan,
                ROOT=root,
                V10_TERMINAL_RECEIPT=predecessor,
                SAME_ANCHOR_FILES=(authority_a, authority_b),
                V11_NEW_CHECKPOINT_FILES=(
                    authority_a,
                    authority_b,
                    checkpoint_only,
                ),
                ACTIVE_REQUEST_PATH=root / "requests/active.json",
            ), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
                errors = plan._validate_same_anchor(root=root)
            self.assertIn(
                "V11 prepared branch HEAD is not the V10 terminal receipt",
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
                V10_TERMINAL_RECEIPT=predecessor,
                SAME_ANCHOR_FILES=(authority_a, authority_b),
                V11_NEW_CHECKPOINT_FILES=(authority_a, authority_b),
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
            predecessor = str(patches["V10_TERMINAL_RECEIPT"])
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
                    "V11 frozen anchor is not on the branch first-parent chain",
                    plan._validate_same_anchor(root=root),
                )
                _receipt, receipt_errors = plan._validate_inert_receipt(root=root)
                self.assertIn(
                    "V11 inert receipt is not on the branch first-parent chain",
                    receipt_errors,
                )
                self.assertIn(
                    "V11 activation is not on the branch first-parent chain",
                    plan._validate_active_git(active, root=root),
                )
                self.assertIn(
                    "V11 canonical branch HEAD is not the latest exact stage",
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
                    ["V11 canonical branch HEAD is not the latest exact stage"],
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
                "V11 immutable checkpoint path changed after add anchor",
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
                ["V11 active request worktree mode changed"],
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
            plan.v10_failure,
            "load_strict",
            return_value={},
        ), mock.patch.object(
            plan.v10_failure,
            "verify",
            return_value=["V10 failure drift"],
        ), mock.patch.object(
            plan.v10_plan,
            "validate_plan",
            return_value=["V10 plan drift"],
        ):
            errors = plan.validate_plan(verify_git_state=False)
        self.assertIn("V10 failure drift", errors)
        self.assertIn("V10 plan drift", errors)

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
