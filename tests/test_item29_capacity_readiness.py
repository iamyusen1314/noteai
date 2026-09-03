import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_capacity_100_jobs_evidence as verifier
from tests.test_capacity_100_jobs import FakeRuntime, ITEM28, PLAN_NONCE, capacity


class Item29CapacityReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = capacity.run_rehearsal(
            FakeRuntime(),
            plan_nonce=PLAN_NONCE,
            item28_dependency=ITEM28,
        )
        cls.source_files = {
            verifier.EXECUTOR_REF: b"executor\n",
            verifier.RENDERER_REF: b"renderer\n",
            verifier.VERIFIER_REF: b"verifier\n",
        }
        cls.evidence = cls._fixture()

    @classmethod
    def _fixture(cls):
        stages = []
        targets = {
            "preflight": "API-C", "admit": "API-C",
            "dispatch": "API-C", "dispatch-readback": "API-C",
            "preclaim-c": "Worker-C", "preclaim-f": "Worker-F",
            "process-c": "Worker-C", "process-f": "Worker-F",
            "source-cleanup-worker-c": "Worker-C",
            "source-cleanup-worker-f": "Worker-F",
            "observe": "API-C", "cleanup": "API-C",
            "source-cleanup-api-c": "API-C",
        }
        cursor = datetime(2026, 8, 23, 18, 50, tzinfo=timezone.utc)
        for action in verifier.EXPECTED_STAGE_ACTIONS:
            if action == "process-c":
                cursor += timedelta(seconds=15)
            started = cursor
            finished = started + timedelta(seconds=1)
            cursor = finished + timedelta(seconds=1)
            stages.append({
                "action": action,
                "target": targets[action],
                "command_name": f"noteai-item29-{action}-20260824-v1",
                "terminal_status": "Success",
                "exit_code": 0,
                "repeat_count": 1,
                "dropped_count": 0,
                "stdout_sha256": verifier._sha(action.encode("ascii")),
                "started_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "finished_at_utc": finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        value = {
            "schema_version": 1,
            "schema": verifier.EVIDENCE_SCHEMA,
            "task_id": verifier.TASK_ID,
            "status": "PASS",
            "observed_at_utc": "2026-08-23T19:00:00Z",
            "source_binding": {
                "branch": verifier.SOURCE_BRANCH,
                "execution_source_revision": "a" * 40,
                "executor_ref": verifier.EXECUTOR_REF,
                "renderer_ref": verifier.RENDERER_REF,
                "verifier_ref": verifier.VERIFIER_REF,
                "executed_executor_bytes": len(
                    cls.source_files[verifier.EXECUTOR_REF]
                ),
                "executed_executor_sha256": verifier._sha(
                    cls.source_files[verifier.EXECUTOR_REF]
                ),
                "executed_executor_gzip_sha256": verifier._sha(
                    verifier._gzip(cls.source_files[verifier.EXECUTOR_REF])
                ),
                "executed_renderer_sha256": verifier._sha(
                    cls.source_files[verifier.RENDERER_REF]
                ),
                "executed_verifier_sha256": verifier._sha(
                    cls.source_files[verifier.VERIFIER_REF]
                ),
            },
            "predecessor": {
                "item28_terminal_acceptance_sha256": (
                    verifier.ITEM28_TERMINAL_ACCEPTANCE_SHA256
                ),
            },
            "managed_runtime": {
                "target_instance_sha256": verifier.TARGET_SHA256,
                "c17_revision": verifier.C17_REVISION,
                "c17_image": verifier.IMAGE,
                "c17_image_config": verifier.IMAGE_CONFIG,
                "dispatcher_unit_sha256": verifier.DISPATCHER_UNIT_SHA256,
                "worker_unit_sha256": verifier.WORKER_UNIT_SHA256,
                "api_database_role": "noteai_app",
                "dispatcher_database_role": "noteai_ai_dispatcher",
                "worker_database_role": "noteai_ai_worker",
                "database_credential_transport": "private_docker_env_file",
            },
            "source_transfers": [
                {
                    "target": target,
                    "terminal_status": "Success",
                    "repeat_count": 1,
                    "content_sha256": verifier._sha(
                        verifier._gzip(cls.source_files[verifier.EXECUTOR_REF])
                    ),
                    "overwrite": False,
                    "source_residue_count": 0,
                }
                for target in ("API-C", "Worker-C", "Worker-F")
            ],
            "execution_stages": stages,
            "result": copy.deepcopy(cls.result),
            "final_resource_state": {
                "api_c": {"status": "Running", "charge_type": "PrePaid"},
                "api_f": {"status": "Running", "charge_type": "PrePaid"},
                "builder": {"status": "Stopped", "charge_type": "PostPaid"},
                "worker_c": {"status": "Stopped", "charge_type": "PostPaid"},
                "worker_f": {"status": "Stopped", "charge_type": "PostPaid"},
                "temporary_compute_running_count": 0,
                "task_container_residue_count": 0,
                "task_file_residue_count": 0,
                "public_listener_count": 0,
                "temporary_security_rule_count": 0,
                "temporary_peering_count": 0,
                "temporary_route_count": 0,
            },
            "cost_and_data_boundary": {
                "incremental_cloud_cost_cny": "0.100000",
                "worker_c_billable_seconds": 300,
                "worker_f_billable_seconds": 300,
                "worker_c_hourly_quote_cny": "0.816400",
                "worker_f_hourly_quote_cny": "0.816400",
                "provider_cost_cny": "0.000000",
                "synthetic_user_create_count": 100,
                "synthetic_user_delete_count": 100,
                "real_user_data_read_count": 0,
                "real_user_data_write_count": 0,
                "public_request_count": 0,
                "non_idempotent_replay_count": 0,
                "provider_replay_count": 0,
            },
            "readiness": copy.deepcopy(verifier.DEFAULT_READINESS),
        }
        value["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(value)
        )
        return value

    def test_single_evidence_accepts_exact_managed_result(self):
        self.assertEqual(
            verifier.validate_document(
                copy.deepcopy(self.evidence), verify_git=False
            ),
            [],
        )

    def test_capacity_loss_duplicate_overcharge_and_cleanup_drift_fail(self):
        cases = (
            ("lost", ("result", "runtime_projection", "lost_operation_count"), 1),
            ("duplicate", ("result", "provider", "duplicate_fake_call_count"), 1),
            ("overcharge", ("result", "runtime_projection", "overcharge_credits_milli"), 1),
            ("cleanup", ("result", "runtime_projection", "primary_user_residue_count"), 1),
            ("attempt", ("result", "runtime_projection", "provider_attempt_number_not_one_count"), 1),
        )
        for label, path, replacement in cases:
            with self.subTest(label=label):
                value = copy.deepcopy(self.evidence)
                target = value
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                value["terminal_acceptance_sha256"] = (
                    verifier.terminal_acceptance_sha256(value)
                )
                self.assertTrue(verifier.validate_document(value, verify_git=False))

    def test_numeric_alias_extra_field_and_terminal_hash_fail(self):
        values = []
        boolean = copy.deepcopy(self.evidence)
        boolean["schema_version"] = True
        values.append(boolean)
        floating = copy.deepcopy(self.evidence)
        floating["result"]["runtime_projection"]["claim_count"] = 102.0
        values.append(floating)
        string = copy.deepcopy(self.evidence)
        string["execution_stages"][0]["exit_code"] = "0"
        values.append(string)
        extra = copy.deepcopy(self.evidence)
        extra["unexpected"] = 1
        values.append(extra)
        terminal = copy.deepcopy(self.evidence)
        terminal["terminal_acceptance_sha256"] = "0" * 64
        values.append(terminal)
        early_process = copy.deepcopy(self.evidence)
        preclaim_f = next(
            row for row in early_process["execution_stages"]
            if row["action"] == "preclaim-f"
        )
        process_c = next(
            row for row in early_process["execution_stages"]
            if row["action"] == "process-c"
        )
        process_c["started_at_utc"] = preclaim_f["finished_at_utc"]
        early_process["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(early_process)
        )
        values.append(early_process)
        for value in values:
            with self.subTest(value=value):
                self.assertTrue(verifier.validate_document(value, verify_git=False))

    def test_manifest_binds_one_evidence_and_execution_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / verifier.EVIDENCE_REF
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(self.evidence, ensure_ascii=True, indent=2) + "\n",
                encoding="ascii",
            )
            entries = [
                {"kind": "git", "ref": "a" * 40},
                *(
                    {"kind": "path", "ref": ref}
                    for ref in sorted(verifier.REQUIRED_MANIFEST_PATH_REFS)
                ),
            ]
            with mock.patch.object(
                verifier,
                "_git_file",
                side_effect=lambda _revision, ref, *, root: self.source_files[ref],
            ):
                self.assertEqual(
                    verifier.validate_manifest_evidence(entries, root=root), []
                )
            changed = copy.deepcopy(entries)
            changed.append({"kind": "path", "ref": "receipt.json"})
            self.assertTrue(
                verifier.validate_manifest_evidence(changed, root=root)
            )

    def test_manifest_contract_has_no_receipt_checkpoint_or_external_authority(self):
        serialized = json.dumps(
            sorted(verifier.REQUIRED_MANIFEST_PATH_REFS)
        ).lower()
        self.assertNotIn("receipt", serialized)
        self.assertNotIn("checkpoint", serialized)
        self.assertNotIn("external", serialized)
        self.assertEqual(
            verifier.DEFAULT_READINESS["internal_verified_after"], 29
        )
        self.assertEqual(
            verifier.DEFAULT_READINESS["complete_public_verified_after"], 29
        )
        self.assertIs(
            verifier.DEFAULT_READINESS["public_launch_authorized"], False
        )


if __name__ == "__main__":
    unittest.main()
