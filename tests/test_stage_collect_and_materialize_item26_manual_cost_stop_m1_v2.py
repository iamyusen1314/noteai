from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import socket
import subprocess
import sys
import threading
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    ROOT
    / "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py"
)


def load_stager() -> tuple[types.ModuleType, bytes]:
    raw = TARGET.read_bytes()
    module = types.ModuleType("item26_m1_capture_materializer_stager_test")
    module.__file__ = str(TARGET)
    module.__package__ = None
    exec(compile(raw, str(TARGET), "exec"), module.__dict__)
    return module, raw


class ExplodingArgument:
    def __getattribute__(self, name: str):
        if name.startswith("__"):
            return object.__getattribute__(self, name)
        raise AssertionError("argument inspected before execution gate")

    def __iter__(self):
        raise AssertionError("argument iterated before execution gate")

    def __str__(self) -> str:
        raise AssertionError("argument rendered before execution gate")


def git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["/usr/bin/git", "--no-replace-objects", *arguments],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )


def child_success_raw(capture: types.ModuleType) -> bytes:
    return capture.canonical(
        {
            "schema": capture.CHILD_STATUS_SCHEMA,
            "status": "ONE_READ_DISPATCH_COMPLETED",
            "cloud_dispatch_count": 1,
            "cloud_write_count": 0,
            "automatic_retry_count": 0,
            "raw_value_emitted_count": 0,
        }
    )


def collector_status(
    capture: types.ModuleType,
    status: str,
    *,
    slot: str | None = None,
    digest_key: str | None = None,
    digest: str | None = None,
    sequence: int = 1,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "noteai.item26.manual-cost-stop-collector-status.v2",
        "status": status,
        "cloud_call_count": 0,
        "raw_value_emitted_count": 0,
    }
    if slot is not None:
        value["slot"] = slot
        value["sequence"] = sequence
    if digest_key is not None:
        value[digest_key] = digest
    if status == "UNKNOWN_INFLIGHT":
        value["reason"] = "TRANSPORT_TIMEOUT"
        value["cloud_request_replay_allowed"] = False
    return value


FAKE_STS_RAW = b"fake-temporary-sts"
FAKE_ACCOUNT_BINDING_SHA256 = "a" * 64


def initial_credential_probe(
    *,
    raw: bytes = FAKE_STS_RAW,
    remaining_seconds: float = 2000,
) -> dict[str, object]:
    return {
        "remaining_seconds": remaining_seconds,
        "account_binding_sha256": FAKE_ACCOUNT_BINDING_SHA256,
        "credential_envelope_sha256": hashlib.sha256(raw).hexdigest(),
        "refresh_count": 0,
        "configure_count": 0,
    }


def expected_credential_capsule(
    *,
    raw: bytes = FAKE_STS_RAW,
    initial_remaining_seconds: float = 2000,
) -> dict[str, object]:
    return {
        "account_binding_sha256": FAKE_ACCOUNT_BINDING_SHA256,
        "credential_envelope_sha256": hashlib.sha256(raw).hexdigest(),
        "initial_remaining_seconds": initial_remaining_seconds,
        "last_remaining_seconds": initial_remaining_seconds,
    }


def dispatch_credential(
    *,
    raw: bytes = FAKE_STS_RAW,
    remaining_seconds: float = 1200,
) -> dict[str, object]:
    return {
        "envelope": bytearray(raw),
        "remaining_seconds": remaining_seconds,
        "account_binding_sha256": FAKE_ACCOUNT_BINDING_SHA256,
        "credential_envelope_sha256": hashlib.sha256(raw).hexdigest(),
        "refresh_count": 0,
        "configure_count": 0,
    }


def fake_child_identity_snapshot(capture: types.ModuleType) -> dict[str, object]:
    return {path: {"path": path} for path in capture.CHILD_TOOL_BINDINGS}


def fake_capture_runtime_arguments() -> tuple[str, ...]:
    return ("f" * 40, "1", "a" * 64, "1", "b" * 64)


def fake_capture_runtime_identity(capture: types.ModuleType) -> dict[str, object]:
    return {
        capture.CAPTURE_PROGRAM_PATH: {"path": capture.CAPTURE_PROGRAM_PATH},
        capture.CAPTURE_MANIFEST_PATH: {"path": capture.CAPTURE_MANIFEST_PATH},
    }


class StageCollectAndMaterializeItem26M1V2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stager, cls.raw = load_stager()
        cls.capture = types.ModuleType("item26_m1_capture_root_test")
        exec(
            compile(
                cls.stager.CAPTURE_ROOT_PROGRAM,
                "<item26-m1-capture-root-test>",
                "exec",
            ),
            cls.capture.__dict__,
        )
        cls.materialize = types.ModuleType("item26_m1_materialize_root_test")
        exec(
            compile(
                cls.stager.MATERIALIZE_ROOT_PROGRAM,
                "<item26-m1-materialize-root-test>",
                "exec",
            ),
            cls.materialize.__dict__,
        )
        cls.stage_root = types.ModuleType("item26_m1_stage_root_test")
        exec(
            compile(
                cls.stager.STAGE_ROOT_PROGRAM,
                "<item26-m1-stage-root-test>",
                "exec",
            ),
            cls.stage_root.__dict__,
        )

    def setUp(self) -> None:
        self.capture.ACTIVE_ADAPTER_PROCESS = None
        self.capture.CAPTURE_TERMINATION_REQUESTED = False
        self.materialize.ACTIVE_MATERIALIZE_PROCESS = None
        self.materialize.MATERIALIZE_TERMINATION_REQUESTED = False

    def test_source_and_both_physical_root_programs_compile_normal_and_optimized(self) -> None:
        compile(self.raw, str(TARGET), "exec", optimize=0)
        compile(self.raw, str(TARGET), "exec", optimize=2)
        for label, source in (
            ("capture", self.stager.CAPTURE_ROOT_PROGRAM),
            ("materialize", self.stager.MATERIALIZE_ROOT_PROGRAM),
            ("stage", self.stager.STAGE_ROOT_PROGRAM),
        ):
            with self.subTest(label=label):
                compile(source, "<item26-m1-" + label + ">", "exec", optimize=0)
                compile(source, "<item26-m1-" + label + ">", "exec", optimize=2)

    def test_source_implementation_is_complete_but_authorizes_no_action(self) -> None:
        status = self.stager.SOURCE_ONLY_STATUS
        expected = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
        self.assertEqual(status["status"], expected)
        self.assertIs(status["implementation_complete"], True)
        self.assertIs(status["operational_ready"], False)
        self.assertIs(status["authorizes_future_execution"], False)
        self.assertEqual(
            status["credential_interface_status"],
            "NOT_PROVISIONED",
        )
        self.assertIs(status["readiness_credit_added"], False)
        for contract in (
            self.stager.FUTURE_CAPTURE_CONTRACT,
            self.stager.FUTURE_MATERIALIZE_CONTRACT,
            self.stager.FD_ONLY_AUTHORITY_VERIFIER_CONTRACT,
            self.stager.ROOT_PARTITION_CONTRACT,
        ):
            self.assertEqual(contract["status"], expected)
            self.assertIs(contract["implementation_complete"], True)
            self.assertIs(contract["operational_ready"], False)
            self.assertIs(contract["requires_new_cto_authorization"], True)
        self.assertIs(
            self.stager.FUTURE_CAPTURE_CONTRACT["scaffold_execution_enabled"],
            False,
        )
        self.assertIs(
            self.stager.FUTURE_MATERIALIZE_CONTRACT["scaffold_execution_enabled"],
            False,
        )
        self.assertIs(
            self.stager.ROOT_PARTITION_CONTRACT["scaffold_execution_enabled"],
            False,
        )
        for embedded_status in (
            self.capture.STATUS,
            self.materialize.STATUS,
            self.stage_root.INERT_STATUS,
        ):
            self.assertEqual(embedded_status["status"], expected)
            self.assertIs(embedded_status["implementation_complete"], True)
            self.assertIs(embedded_status["operational_ready"], False)
            self.assertIs(embedded_status["authorizes_execution"], False)
        self.assertIs(self.capture.CONTRACT["implementation_complete"], True)
        self.assertIs(self.materialize.CONTRACT["implementation_complete"], True)
        self.assertIs(self.capture.EXECUTION_ENABLED, False)
        self.assertIs(self.materialize.EXECUTION_ENABLED, False)
        self.assertIs(self.stage_root.EXECUTION_ENABLED, False)
        for key in (
            "sudo_dispatch_count",
            "root_write_count",
            "oauth_configuration_count",
            "credential_read_count",
            "provider_dispatch_count",
            "database_connection_count",
            "capture_count",
            "materialization_count",
            "cleanup_count",
            "automatic_retry_count",
            "replay_count",
        ):
            self.assertEqual(status[key], 0)

    def test_global_zero_action_contract_is_frozen_in_all_scopes(self) -> None:
        zero = self.stager.GLOBAL_ZERO_ACTION_CONTRACT
        self.assertEqual(zero["authorized_cny"], "0.00")
        self.assertEqual(zero["incurred_cny"], "0.00")
        for key in (
            "cloud_write_count",
            "database_connection_count",
            "database_transaction_count",
            "database_write_count",
            "private_key_read_count",
            "private_key_write_count",
            "private_key_output_count",
            "oauth_configuration_count",
            "oauth_refresh_count",
            "materialize_provider_dispatch_count",
        ):
            self.assertEqual(zero[key], 0)
        self.assertEqual(
            self.stager.FUTURE_CAPTURE_CONTRACT["zero_action_contract"],
            zero,
        )
        self.assertEqual(
            self.stager.FUTURE_MATERIALIZE_CONTRACT["zero_action_contract"],
            zero,
        )

    def test_source_main_is_inert_and_rejects_future_arguments(self) -> None:
        output = types.SimpleNamespace(buffer=io.BytesIO())
        with mock.patch.object(self.stager.sys, "stdout", output):
            self.assertEqual(self.stager.main([]), 0)
        value = json.loads(output.buffer.getvalue())
        self.assertEqual(value, self.stager.SOURCE_ONLY_STATUS)
        with self.assertRaisesRegex(
            self.stager.StagerError,
            "^source_only_arguments$",
        ):
            self.stager.main(["capture"])

    def test_future_mode_gate_precedes_argument_or_dependency_access(self) -> None:
        self.assertIs(self.stager.EXECUTION_ENABLED, False)
        with mock.patch.object(
            self.stager,
            "_run_future_mode_after_gate",
            side_effect=AssertionError("post-gate implementation reached"),
        ):
            with self.assertRaisesRegex(
                self.stager.StagerError,
                "^future_execution_disabled$",
            ):
                self.stager._run_future_mode(ExplodingArgument())
        self.assertTrue(callable(self.stager._default_future_capture))
        self.assertTrue(callable(self.stager._default_future_materialize))

        tree = ast.parse(self.raw)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_run_future_mode"
        )
        first = function.body[0]
        self.assertIsInstance(first, ast.Expr)
        self.assertIsInstance(first.value, ast.Call)
        self.assertIsInstance(first.value.func, ast.Name)
        self.assertEqual(first.value.func.id, "_execution_gate")

    def test_base_topology_and_exact_source_paths_are_frozen(self) -> None:
        stager = self.stager
        self.assertEqual(
            stager.BASE_REVISION,
            "a30b879d06c388a4a0e230b5a23b2eaedc93649d",
        )
        self.assertEqual(
            stager.ADAPTER_REVISION,
            "65b82ffd890479315c9a93769cf11e2a9d27074b",
        )
        self.assertEqual(stager.ADAPTER_SOURCE_REVISION, stager.ADAPTER_REVISION)
        self.assertEqual(stager.ADAPTER_ACCEPTANCE_REVISION, stager.BASE_REVISION)
        self.assertEqual(
            stager.CONTROL_REVISION,
            "68aa82ffbdd43e78e585d8956d13d3030ef6a640",
        )
        self.assertEqual(
            stager.SOURCE_REFS,
            stager.LEDGER_REFS | {stager.STAGER_REF, stager.TEST_REF},
        )
        self.assertEqual(len(stager.SOURCE_REFS), 6)
        self.assertEqual(stager.ACCEPTANCE_REFS, stager.LEDGER_REFS)
        self.assertEqual(len(stager.ACCEPTANCE_REFS), 4)

    def test_fixed_bindings_are_secret_free_static_identities(self) -> None:
        bindings = self.stager.FIXED_BINDINGS
        adapter = bindings[self.stager.ADAPTER_REF]
        self.assertEqual(adapter["revision"], self.stager.BASE_REVISION)
        self.assertEqual(
            adapter["source_revision"],
            self.stager.ADAPTER_SOURCE_REVISION,
        )
        for ref, binding in bindings.items():
            with self.subTest(ref=ref):
                self.assertEqual(len(binding["revision"]), 40)
                self.assertEqual(set(binding["revision"]) - set("0123456789abcdef"), set())
                self.assertEqual(len(binding["git_blob_oid"]), 40)
                self.assertEqual(set(binding["git_blob_oid"]) - set("0123456789abcdef"), set())
                self.assertEqual(len(binding["file_sha256"]), 64)
                self.assertEqual(set(binding["file_sha256"]) - set("0123456789abcdef"), set())
                self.assertGreater(binding["size"], 0)

    def test_fixed_bindings_match_actual_accepted_git_objects(self) -> None:
        for ref, binding in self.stager.FIXED_BINDINGS.items():
            with self.subTest(ref=ref):
                revision = binding["revision"]
                oid_result = git("rev-parse", revision + ":" + ref)
                self.assertEqual(oid_result.returncode, 0, oid_result.stderr)
                oid = oid_result.stdout.decode("ascii").strip()
                self.assertEqual(oid, binding["git_blob_oid"])
                raw_result = git("cat-file", "blob", oid)
                self.assertEqual(raw_result.returncode, 0, raw_result.stderr)
                raw = raw_result.stdout
                self.assertEqual(len(raw), binding["size"])
                self.assertEqual(
                    hashlib.sha256(raw).hexdigest(),
                    binding["file_sha256"],
                )

    def test_m1_outputs_are_exactly_two_and_checkpoint_is_forbidden(self) -> None:
        contract = self.stager.FUTURE_MATERIALIZE_CONTRACT
        self.assertEqual(
            set(contract["public_artifact_refs"]),
            {self.stager.M1_RECEIPT_REF, self.stager.M1_EVIDENCE_REF},
        )
        self.assertNotIn(
            self.stager.M2_CHECKPOINT_REF,
            contract["public_artifact_refs"],
        )
        self.assertIs(contract["terminal_checkpoint_create_allowed"], False)

    def test_m1_and_m2_artifacts_are_absent_at_base_revision(self) -> None:
        for ref in (
            self.stager.M1_RECEIPT_REF,
            self.stager.M1_EVIDENCE_REF,
            self.stager.M2_CHECKPOINT_REF,
        ):
            with self.subTest(ref=ref):
                result = git("cat-file", "-e", self.stager.BASE_REVISION + ":" + ref)
                self.assertNotEqual(result.returncode, 0)

    def test_capture_contract_freezes_exact_collector_slots_and_operations(self) -> None:
        contract = self.stager.FUTURE_CAPTURE_CONTRACT
        self.assertEqual(contract["collector_control_revision"], self.stager.CONTROL_REVISION)
        self.assertEqual(contract["logical_slots"], list(self.stager.CAPTURE_SLOTS))
        self.assertEqual(
            self.stager.CAPTURE_SLOTS,
            (
                "cost_stop_rds_write_lookup_page",
                "clone_create_lookup_page",
                "fresh_clone_inventory",
                "fresh_source_inventory",
                "historical_billing_snapshot",
            ),
        )
        self.assertEqual(
            contract["logical_slot_operations"],
            {
                slot: list(operation)
                for slot, operation in self.stager.CAPTURE_SLOT_OPERATIONS.items()
            },
        )
        self.assertEqual(
            self.stager.CAPTURE_SLOT_OPERATIONS,
            {
                "cost_stop_rds_write_lookup_page": (
                    "LookupEvents",
                    "2020-07-06",
                ),
                "clone_create_lookup_page": (
                    "LookupEvents",
                    "2020-07-06",
                ),
                "fresh_clone_inventory": (
                    "DescribeDBInstances",
                    "2014-08-15",
                ),
                "fresh_source_inventory": (
                    "DescribeDBInstances",
                    "2014-08-15",
                ),
                "historical_billing_snapshot": (
                    "QueryInstanceBill",
                    "2017-12-14",
                ),
            },
        )
        self.assertEqual(contract["logical_slot_count"], 5)
        self.assertEqual(contract["maximum_provider_dispatches"], 64)
        self.assertEqual(contract["maximum_begin_to_finish_seconds"], 840)
        self.assertEqual(contract["full_capture_timeout_seconds"], 840)
        self.assertEqual(contract["maximum_active_adapter_children"], 1)
        self.assertEqual(contract["parallel_provider_dispatch_count"], 0)
        self.assertEqual(contract["adapter_child_count_per_record"], 1)
        self.assertEqual(contract["adapter_child_isolated_flags"], ["-I", "-S", "-B"])
        self.assertIs(
            contract["parent_concurrent_feed_response_status_drain_required"],
            True,
        )
        self.assertIs(
            contract["second_provider_dispatch_during_drain_allowed"],
            False,
        )
        self.assertIs(contract["automatic_retry_allowed"], False)
        self.assertIs(contract["historical_replay_allowed"], False)
        self.assertIs(contract["cleanup_allowed"], False)

    def test_capture_page_order_identity_and_failure_matrix_are_at_most_once(self) -> None:
        contract = self.stager.FUTURE_CAPTURE_CONTRACT
        self.assertEqual(
            contract["per_page_sequence"],
            list(self.stager.CAPTURE_PAGE_SEQUENCE),
        )
        self.assertEqual(
            self.stager.CAPTURE_PAGE_SEQUENCE,
            (
                "collector_begin_success_observed",
                "adapter_child_spawned_exactly_once",
                "request_credential_feed_and_response_status_concurrent_drain",
                "child_exit_reap_and_process_group_absence_observed",
                "collector_finish_invoked_at_most_once_with_same_raw_response",
                "collector_finish_success_observed",
                "pagination_token_or_identifier_derived",
            ),
        )
        self.assertIs(
            contract["begin_success_must_be_observed_before_child_spawn"],
            True,
        )
        self.assertIs(
            contract["finish_receives_exact_adapter_raw_response_bytes"],
            True,
        )
        self.assertIs(
            contract["token_or_identity_before_finish_success_allowed"],
            False,
        )
        identity = self.stager.IDENTITY_DERIVATION_CONTRACT
        self.assertIs(identity["cost_stop_candidate_raw_values_all_equal"], True)
        self.assertEqual(len(identity["cost_stop_candidate_old_clone_sha256"]), 64)
        self.assertEqual(identity["clone_create_source_candidate_count"], 1)
        self.assertEqual(len(identity["clone_create_source_sha256"]), 64)
        self.assertIs(identity["candidate_raw_persistence_allowed"], False)

        matrix = self.stager.CAPTURE_AT_MOST_ONCE_FAILURE_MATRIX
        self.assertEqual(
            matrix["child_status_lost_after_group_absence"][
                "second_child_spawn_allowed"
            ],
            False,
        )
        self.assertEqual(
            matrix["finish_records_unknown_and_raises"][
                "bridge_mark_unknown_maximum_count"
            ],
            0,
        )
        self.assertEqual(
            matrix["begin_status_lost_after_single_invocation"][
                "second_begin_call_allowed"
            ],
            False,
        )
        self.assertEqual(
            matrix["child_failure_without_process_group_absence_proof"][
                "bridge_mark_unknown_maximum_count"
            ],
            0,
        )
        self.assertEqual(
            matrix[
                "bridge_mark_unknown_status_lost_after_single_invocation"
            ]["second_mark_unknown_call_allowed"],
            False,
        )
        self.assertEqual(
            matrix["finalize_status_lost_after_single_invocation"][
                "second_finalize_call_allowed"
            ],
            False,
        )
        for phase, row in matrix.items():
            with self.subTest(phase=phase):
                self.assertEqual(row["automatic_retry_count"], 0)
                self.assertLessEqual(row.get("child_spawn_count", 0), 1)
                self.assertLessEqual(row.get("finish_call_count", 0), 1)
                self.assertLessEqual(
                    row["bridge_mark_unknown_maximum_count"],
                    1,
                )

        materialize_matrix = self.stager.MATERIALIZE_AT_MOST_ONCE_FAILURE_MATRIX
        for phase, row in materialize_matrix.items():
            with self.subTest(materialize_phase=phase):
                self.assertEqual(row["root_invocation_count"], 1)
                self.assertIs(row["root_reinvoke_allowed"], False)
                self.assertEqual(row["automatic_retry_count"], 0)
        self.assertEqual(
            materialize_matrix["receipt_write_fsync_or_readback_failure"][
                "evidence_write_count"
            ],
            0,
        )

    def test_capture_contract_freezes_four_fd_raw_and_process_group_boundary(self) -> None:
        contract = self.stager.FUTURE_CAPTURE_CONTRACT
        self.assertEqual(
            contract["anonymous_fd_channels"],
            list(self.stager.ADAPTER_FD_CHANNELS),
        )
        self.assertEqual(contract["anonymous_fd_channel_count"], 4)
        self.assertEqual(
            contract["anonymous_fd_transport"],
            "AF_UNIX_SOCK_STREAM",
        )
        self.assertIs(
            contract["anonymous_fd_unique_open_file_descriptions_required"],
            True,
        )
        self.assertIs(
            contract["anonymous_fd_f_getfl_direction_preflight_required"],
            True,
        )
        self.assertIs(contract["anonymous_fd_blocking_required"], True)
        self.assertEqual(contract["anonymous_fd_access_mode_required"], "O_RDWR")
        self.assertIs(contract["anonymous_fd_async_flag_allowed"], False)
        self.assertEqual(
            contract["anonymous_fd_directions"],
            {
                "logical_request": "CHILD_READ_PARENT_WRITE",
                "temporary_sts": "CHILD_READ_PARENT_WRITE",
                "raw_response": "CHILD_WRITE_PARENT_READ",
                "fixed_status": "CHILD_WRITE_PARENT_READ",
            },
        )
        self.assertIs(contract["child_close_fds"], True)
        self.assertEqual(
            contract["child_pass_fds_exactly"],
            list(self.stager.ADAPTER_FD_CHANNELS),
        )
        self.assertIs(
            contract["child_core_limit_and_clean_environment_before_fd_read"],
            True,
        )
        for key in (
            "request_parent_shutdown_write_after_exact_bytes",
            "credential_parent_shutdown_write_after_exact_bytes",
            "response_child_shutdown_write_required",
            "status_child_shutdown_write_required",
            "response_parent_drain_to_eof_required",
            "status_parent_drain_to_eof_required",
        ):
            self.assertIs(contract[key], True)
        self.assertEqual(
            contract["maximum_response_bytes"],
            8 * 1024 * 1024,
        )
        self.assertEqual(contract["maximum_status_bytes"], 4096)
        self.assertEqual(contract["child_stdout"], "DEVNULL")
        self.assertEqual(contract["child_stderr"], "DEVNULL")
        status = contract["child_status_contract"]
        self.assertEqual(status["schema"], "noteai.item26.m1-adapter-child-status.v1")
        self.assertEqual(status["success_cloud_dispatch_count"], 1)
        self.assertEqual(status["success_automatic_retry_count"], 0)
        self.assertIs(status["status_loss_second_dispatch_allowed"], False)
        identity = contract["child_identity_contract"]
        self.assertIs(
            identity["adapter_python_ca_pre_post_inode_hash_size_mode_equal"],
            True,
        )
        self.assertIs(
            identity["credential_fd_pre_post_inode_size_mode_equal"],
            True,
        )
        for key in (
            "raw_in_argv_allowed",
            "raw_in_environment_allowed",
            "raw_in_regular_file_allowed",
            "raw_in_stdout_allowed",
            "raw_in_stderr_allowed",
        ):
            self.assertIs(contract[key], False)
        self.assertIs(contract["adapter_child_new_process_group"], True)
        self.assertEqual(
            contract["adapter_child_timeout_kill_scope"],
            "PROCESS_GROUP",
        )
        self.assertIs(contract["adapter_child_wait_and_reap_required"], True)
        self.assertIs(
            contract["adapter_child_group_absence_proof_required"],
            True,
        )

    def test_capture_unknown_pagination_identity_and_credential_rules_are_closed(self) -> None:
        contract = self.stager.FUTURE_CAPTURE_CONTRACT
        self.assertIs(
            contract["collector_finish_unknown_excludes_bridge_mark_unknown"],
            True,
        )
        self.assertEqual(contract["bridge_mark_unknown_maximum_count"], 1)
        for key in (
            "bridge_mark_unknown_requires_future_explicit_authorization",
            "bridge_mark_unknown_requires_process_group_absent",
            "bridge_mark_unknown_requires_begin_committed",
            "bridge_mark_unknown_requires_finish_not_invoked",
            "bridge_mark_unknown_requires_no_existing_unknown",
        ):
            self.assertIs(contract[key], True)
        self.assertIs(
            contract["bridge_mark_unknown_without_all_conditions_allowed"],
            False,
        )
        self.assertIs(contract["pagination_token_cycle_rejected"], True)
        self.assertIs(contract["global_record_limit_includes_all_pages"], True)
        self.assertIs(contract["identifier_derivation_in_memory_only"], True)
        self.assertIs(contract["identifier_extractor_parity_required"], True)
        self.assertEqual(contract["credential_interface_status"], "NOT_PROVISIONED")
        self.assertEqual(contract["credential_reader_uid"], 0)
        self.assertEqual(
            contract["credential_minimum_remaining_validity_seconds"],
            16 * 60,
        )
        self.assertEqual(
            contract["credential_initial_minimum_validity_seconds"],
            31 * 60,
        )
        self.assertIs(
            contract["credential_validity_checked_before_every_begin"],
            True,
        )
        self.assertEqual(
            contract["credential_below_per_dispatch_minimum_begin_count"],
            0,
        )
        self.assertIs(contract["credential_refresh_allowed"], False)
        self.assertIs(contract["oauth_configure_allowed"], False)
        self.assertIs(contract["default_user_config_read_allowed"], False)
        self.assertIs(contract["provider_account_binding_required"], True)

    def test_materialize_contract_has_two_public_outputs_and_no_operational_transport(self) -> None:
        contract = self.stager.FUTURE_MATERIALIZE_CONTRACT
        self.assertEqual(
            contract["public_artifact_refs"],
            [self.stager.M1_RECEIPT_REF, self.stager.M1_EVIDENCE_REF],
        )
        self.assertEqual(contract["public_artifact_count"], 2)
        self.assertEqual(contract["terminal_checkpoint_ref"], self.stager.M2_CHECKPOINT_REF)
        self.assertIs(contract["terminal_checkpoint_must_remain_absent"], True)
        self.assertIs(contract["outer_precreates_exclusive_files"], True)
        self.assertEqual(
            contract["outer_open_flags"],
            ["O_EXCL", "O_NOFOLLOW", "O_RDWR"],
        )
        self.assertEqual(contract["outer_output_mode"], "0600")
        self.assertIs(
            contract["outer_precreates_both_before_root_dispatch"],
            True,
        )
        self.assertIs(contract["outer_holds_output_file_descriptors"], True)
        self.assertIs(contract["outer_output_alias_rejected"], True)
        self.assertIs(contract["outer_output_inode_identity_required"], True)
        self.assertIs(contract["outer_fsync_before_and_after_write"], True)
        self.assertIs(contract["outer_parent_directory_fsync_required"], True)
        self.assertIs(contract["outer_readback_exact_bytes_required"], True)
        self.assertEqual(
            contract["root_output_fd_channels"],
            ["receipt", "evidence", "fixed_status"],
        )
        self.assertEqual(contract["root_output_fd_count"], 3)
        self.assertEqual(
            contract["root_output_fd_transport"],
            "AF_UNIX_SOCK_STREAM",
        )
        self.assertIs(
            contract["root_output_child_fd_identity_preflight_required"],
            True,
        )
        self.assertIs(
            contract["root_output_fd_unique_open_file_descriptions_required"],
            True,
        )
        self.assertIs(contract["root_output_fd_blocking_required"], True)
        self.assertEqual(contract["root_output_fd_access_mode_required"], "O_RDWR")
        self.assertIs(contract["root_output_fd_async_flag_allowed"], False)
        self.assertEqual(
            contract["root_output_fd_directions"],
            {
                "receipt": "CHILD_WRITE_PARENT_READ",
                "evidence": "CHILD_WRITE_PARENT_READ",
                "fixed_status": "CHILD_WRITE_PARENT_READ",
            },
        )
        self.assertIs(contract["root_output_concurrent_drain_required"], True)
        self.assertEqual(
            contract["root_output_limits"],
            {
                "receipt": 8 * 1024 * 1024,
                "evidence": 8 * 1024 * 1024,
                "fixed_status": 4096,
            },
        )
        self.assertIs(contract["root_output_each_requires_eof"], True)
        status = contract["root_fixed_status_contract"]
        self.assertEqual(
            status["schema"],
            "noteai.item26.m1-materialize-child-status.v1",
        )
        self.assertEqual(status["receipt_build_count"], 1)
        self.assertEqual(status["evidence_build_count"], 1)
        self.assertEqual(status["checkpoint_build_count"], 0)
        self.assertEqual(status["network_dispatch_count"], 0)
        self.assertIs(contract["network_path_present"], False)
        self.assertIs(contract["provider_transport_present"], False)
        self.assertIs(contract["oauth_path_present"], False)
        self.assertIs(contract["database_path_present"], False)
        self.assertIs(contract["dynamic_network_guard_required"], True)
        self.assertIs(contract["dynamic_subprocess_guard_required"], True)
        self.assertIs(
            contract["dynamic_guards_installed_before_module_load"],
            True,
        )
        self.assertEqual(
            contract["process_guard_exact_executable_exceptions"],
            ["/usr/bin/git", "/usr/bin/openssl"],
        )
        self.assertIs(
            contract["process_guard_openssl_fd_only_signature_verification"],
            True,
        )
        self.assertIs(contract["process_guard_all_other_executables_denied"], True)
        self.assertIs(
            contract["authority_verifier_ref_exact_source_load_required"],
            True,
        )
        self.assertEqual(
            contract["authority_signature_patch_contract"]["patch_target"],
            "_verify_signature",
        )
        self.assertIs(contract["authority_original_signature_callable_allowed"], False)
        self.assertIs(contract["capture_or_provider_dispatch_allowed"], False)
        self.assertIs(contract["empty_or_partial_output_residue_preserved"], True)
        self.assertIs(
            contract["first_output_preserved_if_second_precreate_fails"],
            True,
        )
        self.assertIs(contract["output_pair_cleanup_allowed"], False)
        self.assertEqual(
            contract["builder_allowed_entrypoints"],
            ["build_receipt", "build_evidence"],
        )
        self.assertEqual(
            contract["verifier_allowed_entrypoints"],
            ["validate_receipt", "validate_evidence"],
        )
        self.assertIs(contract["checkpoint_builder_entrypoint_allowed"], False)
        self.assertEqual(
            contract["drain_validate_write_order"][-3:],
            [
                "write_fsync_readback_receipt",
                "write_fsync_readback_evidence",
                "fsync_both_files_and_parent_directories",
            ],
        )
        self.assertIs(contract["receipt_write_failure_prevents_evidence_write"], True)
        self.assertIs(contract["readiness_credit_added"], False)

    def test_materialize_fake_pipeline_calls_only_two_build_and_two_validate_entries(self) -> None:
        builder_calls: list[str] = []
        verifier_calls: list[str] = []

        class FakeBuilder:
            def build_receipt(self, **kwargs):
                self.assert_kwargs(kwargs)
                builder_calls.append("build_receipt")
                receipt = {"receipt": True}
                verifier.validate_receipt(
                    receipt,
                    expected_control_revision=kwargs[
                        "expected_control_revision"
                    ],
                )
                return receipt

            def build_evidence(self, receipt, **kwargs):
                self.assert_kwargs(kwargs)
                self.assertEqual(receipt, {"receipt": True})
                builder_calls.append("build_evidence")
                evidence = {"evidence": True}
                verifier.validate_receipt(
                    receipt,
                    expected_control_revision=kwargs[
                        "expected_control_revision"
                    ],
                )
                verifier.validate_evidence(
                    evidence,
                    receipt,
                    self_outer.stager.canonical_bytes(receipt),
                    expected_control_revision=kwargs[
                        "expected_control_revision"
                    ],
                )
                return evidence

            def assert_kwargs(self, kwargs):
                self.assertEqual(
                    set(kwargs),
                    {"expected_control_revision", "root", "authority_directory"},
                )

            assertEqual = unittest.TestCase().assertEqual

            def __getattr__(self, name):
                raise AssertionError("unexpected builder entrypoint: " + name)

        class FakeVerifier:
            def validate_receipt(self, value, **kwargs):
                self.assertEqual(value, {"receipt": True})
                self.assertEqual(set(kwargs), {"expected_control_revision"})
                verifier_calls.append("validate_receipt")
                return [], "accepted"

            def validate_evidence(self, value, receipt, receipt_raw, **kwargs):
                self.assertEqual(value, {"evidence": True})
                self.assertEqual(receipt, {"receipt": True})
                self.assertEqual(
                    receipt_raw,
                    self_outer.stager.canonical_bytes(receipt),
                )
                self.assertEqual(set(kwargs), {"expected_control_revision"})
                verifier_calls.append("validate_evidence")
                return []

            assertEqual = unittest.TestCase().assertEqual

            def __getattr__(self, name):
                raise AssertionError("unexpected verifier entrypoint: " + name)

        self_outer = self
        builder = FakeBuilder()
        verifier = FakeVerifier()
        receipt, evidence = self.stager._materialize_build_and_validate_once(
            builder,
            verifier,
            expected_control_revision=self.stager.CONTROL_REVISION,
            root=self.stager.REPOSITORY_ROOT,
            authority_directory=self.stager.AUTHORITY_DIRECTORY,
        )
        self.assertEqual(builder_calls, ["build_receipt", "build_evidence"])
        self.assertEqual(
            verifier_calls,
            [
                "validate_receipt",
                "validate_receipt",
                "validate_evidence",
                "validate_receipt",
                "validate_evidence",
            ],
        )
        self.stager._materialize_independent_validate_once(
            verifier,
            receipt,
            evidence,
            expected_control_revision=self.stager.CONTROL_REVISION,
        )
        self.assertEqual(
            verifier_calls,
            [
                "validate_receipt",
                "validate_receipt",
                "validate_evidence",
                "validate_receipt",
                "validate_evidence",
                "validate_receipt",
                "validate_evidence",
            ],
        )
        contract = self.stager.MATERIALIZE_ENTRYPOINT_CALL_CONTRACT
        self.assertEqual(contract["builder_call_count"], 2)
        self.assertEqual(contract["root_receipt_validation_call_count"], 3)
        self.assertEqual(contract["root_evidence_validation_call_count"], 2)
        self.assertEqual(contract["outer_receipt_validation_call_count"], 1)
        self.assertEqual(contract["outer_evidence_validation_call_count"], 1)
        self.assertEqual(contract["global_receipt_validation_call_count"], 4)
        self.assertEqual(contract["global_evidence_validation_call_count"], 3)
        self.assertEqual(contract["builder_root"], self.stager.REPOSITORY_ROOT)
        self.assertEqual(
            contract["builder_authority_directory"],
            self.stager.AUTHORITY_DIRECTORY,
        )
        self.assertEqual(contract["checkpoint_entrypoint_call_count"], 0)
        self.assertEqual(contract["network_dispatch_count"], 0)
        self.assertEqual(contract["database_connection_count"], 0)

    def test_materialize_process_guard_allows_only_exact_git_and_openssl(self) -> None:
        stager = self.stager
        self.assertEqual(stager.MATERIALIZE_PROCESS_ENV["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(stager.MATERIALIZE_PROCESS_ENV["GIT_TERMINAL_PROMPT"], "0")
        git_contract = stager.MATERIALIZE_GIT_CONTRACT
        self.assertIs(git_contract["promisor_remote_allowed"], False)
        self.assertIs(git_contract["partial_clone_extension_allowed"], False)
        self.assertIs(git_contract["required_objects_missing_allowed"], False)
        patch_contract = stager.AUTHORITY_GIT_PATCH_CONTRACT
        self.assertIs(patch_contract["required_in_capture"], True)
        self.assertIs(patch_contract["required_in_materialize"], True)
        self.assertEqual(patch_contract["patch_target"], "_git")
        self.assertEqual(
            patch_contract["required_object_absence_provider_child_count"],
            0,
        )
        git_prefix = stager.MATERIALIZE_GIT_CONTRACT["fixed_prefix"]
        git_argv = [
            *git_prefix,
            "show",
            stager.CONTROL_REVISION + ":" + stager.EXTRACTOR_REF,
        ]
        self.assertIs(
            stager._materialize_process_allowed(
                "/usr/bin/git",
                git_argv,
                dict(stager.MATERIALIZE_PROCESS_ENV),
                stager.REPOSITORY_ROOT,
            ),
            True,
        )
        for tail in (
            ["fetch", "origin"],
            ["show", "--help"],
            ["cat-file", "blob", "deadbeef"],
        ):
            with self.subTest(tail=tail):
                self.assertIs(
                    stager._materialize_process_allowed(
                        "/usr/bin/git",
                        [*git_prefix, *tail],
                        dict(stager.MATERIALIZE_PROCESS_ENV),
                        stager.REPOSITORY_ROOT,
                    ),
                    False,
                )
        dirty_env = dict(stager.MATERIALIZE_PROCESS_ENV)
        dirty_env["EXTRA"] = "1"
        self.assertIs(
            stager._materialize_process_allowed(
                "/usr/bin/git",
                git_argv,
                dirty_env,
                stager.REPOSITORY_ROOT,
            ),
            False,
        )
        self.assertIs(
            stager._materialize_audit_event_allowed("socket.connect"),
            False,
        )
        self.assertIs(
            stager._materialize_audit_event_allowed("socket.getaddrinfo"),
            False,
        )
        self.assertIs(stager._materialize_audit_event_allowed("os.fork"), False)
        self.assertIs(
            stager._materialize_audit_event_allowed(
                "subprocess.Popen",
                "/usr/bin/git",
                git_argv,
                dict(stager.MATERIALIZE_PROCESS_ENV),
                stager.REPOSITORY_ROOT,
            ),
            True,
        )
        self.assertIs(
            stager._materialize_audit_event_allowed("pathlib.Path.glob"),
            True,
        )

        self.assertIs(
            stager._materialize_process_allowed(
                "/usr/bin/openssl",
                ["/usr/bin/openssl", "pkey", "-pubin", "-pubout"],
                dict(stager.OPENSSL_PROCESS_ENV),
                stager.MATERIALIZE_RUNTIME_DIRECTORY,
            ),
            True,
        )
        self.assertIs(
            stager._materialize_process_allowed(
                "/usr/bin/openssl",
                ["/usr/bin/openssl", "pkey", "-pubin", "-pubout"],
                dict(stager.OPENSSL_PROCESS_ENV),
                None,
                parent_cwd_verified=True,
            ),
            True,
        )
        self.assertIs(
            stager._materialize_process_allowed(
                "/usr/bin/openssl",
                ["/usr/bin/openssl", "pkey", "-pubin", "-pubout"],
                dict(stager.OPENSSL_PROCESS_ENV),
                None,
                parent_cwd_verified=False,
            ),
            False,
        )
        signature_argv = [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-verify",
            "/dev/fd/7",
            "-signature",
            "/dev/fd/8",
            "/dev/fd/9",
        ]
        self.assertIs(
            stager._materialize_process_allowed(
                "/usr/bin/openssl",
                signature_argv,
                dict(stager.OPENSSL_PROCESS_ENV),
                stager.MATERIALIZE_RUNTIME_DIRECTORY,
            ),
            True,
        )
        signature_argv[-1] = "/dev/fd/8"
        self.assertIs(
            stager._materialize_process_allowed(
                "/usr/bin/openssl",
                signature_argv,
                dict(stager.OPENSSL_PROCESS_ENV),
                stager.MATERIALIZE_RUNTIME_DIRECTORY,
            ),
            False,
        )
        self.assertIs(
            stager._materialize_process_allowed(
                "/bin/sh",
                ["/bin/sh", "-c", "true"],
                {},
                stager.MATERIALIZE_RUNTIME_DIRECTORY,
            ),
            False,
        )

    def test_root_partitions_and_runtime_inventories_are_disjoint_and_closed(self) -> None:
        stager = self.stager
        capture = Path(stager.CAPTURE_RUNTIME_DIRECTORY)
        materialize = Path(stager.MATERIALIZE_RUNTIME_DIRECTORY)
        existing = {Path(value) for value in stager.EXISTING_ROOT_PARTITIONS.values()}
        self.assertEqual(capture.parent, materialize.parent)
        self.assertNotEqual(capture, materialize)
        self.assertNotIn(capture, existing)
        self.assertNotIn(materialize, existing)
        for old in existing:
            self.assertNotIn(old, capture.parents)
            self.assertNotIn(old, materialize.parents)
        contract = stager.ROOT_PARTITION_CONTRACT
        self.assertEqual(contract["new_partition_mode"], "0700")
        self.assertEqual(contract["new_partition_uid"], 0)
        self.assertEqual(contract["new_partition_gid"], 0)
        self.assertEqual(contract["existing_partition_stage_write_count"], 0)
        self.assertIs(contract["rollback_allowed"], False)
        self.assertIs(contract["cleanup_allowed"], False)
        self.assertEqual(
            contract["noteai_parent_stable_identity_fields"],
            ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid"],
        )
        self.assertEqual(
            contract["noteai_parent_expected_direct_child_create_count"],
            2,
        )
        self.assertIs(
            contract[
                "noteai_parent_nlink_mtime_ctime_change_allowed_for_direct_child_mkdirs"
            ],
            True,
        )
        self.assertIs(
            contract["noteai_parent_other_identity_drift_allowed"],
            False,
        )

        inventories = (
            stager.CAPTURE_RUNTIME_INVENTORY,
            stager.MATERIALIZE_RUNTIME_INVENTORY,
        )
        self.assertTrue(set(inventories[0]).isdisjoint(set(inventories[1])))
        for inventory in inventories:
            for name, row in inventory.items():
                with self.subTest(name=name):
                    self.assertNotIn("/", name)
                    self.assertIn(row["mode"], {"0500", "0600"})
        self.assertNotIn(
            stager.ADAPTER_REF,
            stager.MATERIALIZE_DEPENDENCY_ALLOWLIST,
        )
        self.assertEqual(
            set(stager.MATERIALIZE_DEPENDENCY_ALLOWLIST),
            {
                stager.BUILDER_REF,
                stager.EVIDENCE_VERIFIER_REF,
                stager.EXTRACTOR_REF,
                stager.AUTHORITY_VERIFIER_REF,
            },
        )
        self.assertEqual(
            set(stager.CAPTURE_DEPENDENCY_LOCATIONS),
            set(stager.CAPTURE_DEPENDENCY_ALLOWLIST),
        )
        self.assertEqual(
            set(stager.MATERIALIZE_DEPENDENCY_LOCATIONS),
            set(stager.MATERIALIZE_DEPENDENCY_ALLOWLIST),
        )
        self.assertIn("capture-root-program.py", stager.CAPTURE_RUNTIME_INVENTORY)
        self.assertIn(
            "materialize-root-program.py",
            stager.MATERIALIZE_RUNTIME_INVENTORY,
        )
        self.assertEqual(
            set(stager.MATERIALIZE_RUNTIME_INVENTORY),
            {
                "materialize-root-program.py",
                "build_item26_manual_cost_stop_evidence_v2.py",
                "verify_item26_manual_cost_stop_evidence_v2.py",
                "extract_item26_manual_cost_stop_raw_v2.py",
                "verify_item26_manual_cost_stop_authority_v2.py",
                "materialize-runtime-manifest.json",
            },
        )

    def test_runtime_manifest_specs_bind_every_payload_field(self) -> None:
        required = set(self.stager.RUNTIME_MANIFEST_PAYLOAD_FIELDS)
        for label, inventory, manifest in (
            (
                "capture",
                self.stager.CAPTURE_RUNTIME_INVENTORY,
                self.stager.CAPTURE_RUNTIME_MANIFEST_SPEC,
            ),
            (
                "materialize",
                self.stager.MATERIALIZE_RUNTIME_INVENTORY,
                self.stager.MATERIALIZE_RUNTIME_MANIFEST_SPEC,
            ),
        ):
            with self.subTest(label=label):
                self.assertEqual(manifest["schema"], self.stager.RUNTIME_MANIFEST_SCHEMA)
                self.assertEqual(
                    set(inventory),
                    set(manifest["payloads"]) | {manifest["manifest_name"]},
                )
                self.assertEqual(manifest["manifest_mode"], "0600")
                for name, row in manifest["payloads"].items():
                    self.assertEqual(set(row), required)
                    self.assertEqual(row["name"], name)
                    self.assertEqual(row["mode"], inventory[name]["mode"])
        capture_root = self.stager.CAPTURE_RUNTIME_MANIFEST_SPEC["payloads"][
            "capture-root-program.py"
        ]
        self.assertEqual(
            capture_root["sha256"],
            "EXPECTED_CAPTURE_ROOT_SHA256_ARGUMENT",
        )
        self.assertIs(self.stager.EXECUTION_ENABLED, False)

    def test_existing_root_inventory_snapshot_never_reads_custody_bytes(self) -> None:
        stager = self.stager
        contract = stager.EXISTING_INVENTORY_SNAPSHOT_CONTRACT
        self.assertEqual(
            tuple(contract["authority_names"]),
            stager.EXISTING_AUTHORITY_ACTIVATION_INVENTORY,
        )
        self.assertEqual(
            tuple(contract["runtime_names"]),
            stager.EXISTING_RUNTIME_INVENTORY,
        )
        self.assertEqual(contract["journal_names"], [])
        self.assertEqual(
            tuple(contract["custody_names"]),
            stager.EXISTING_CUSTODY_INVENTORY,
        )
        self.assertEqual(contract["directory_mode"], "0700")
        self.assertIs(contract["directory_pre_post_name_inode_mode_equal"], True)
        self.assertEqual(contract["custody_file_mode"], "0600")
        self.assertEqual(contract["custody_content_read_count"], 0)
        self.assertIs(contract["custody_content_hash_allowed"], False)
        self.assertIs(contract["custody_metadata_manifest_sha256_required"], True)
        self.assertIs(contract["journal_pre_post_empty_required"], True)
        self.assertEqual(
            contract["authority_runtime_journal_custody_stage_write_count"],
            0,
        )
        self.assertEqual(
            contract["noteai_parent_stable_identity_fields"],
            ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid"],
        )
        self.assertEqual(
            contract["noteai_parent_expected_direct_child_create_count"],
            2,
        )

    @unittest.skipUnless(sys.platform == "darwin", "frozen macOS tool identity")
    def test_system_tool_nlink_symlink_hash_and_parent_chain_bindings(self) -> None:
        contract = self.stager.SYSTEM_TOOL_IDENTITY_CONTRACT
        self.assertIs(contract["pre_post_inode_hash_size_mode_uid_gid_nlink_equal"], True)
        self.assertIs(contract["file_symlink_allowed"], False)
        for raw_path, binding in self.stager.SYSTEM_TOOL_BINDINGS.items():
            with self.subTest(path=raw_path):
                path = Path(raw_path)
                row = path.lstat()
                self.assertTrue(stat.S_ISREG(row.st_mode))
                self.assertFalse(stat.S_ISLNK(row.st_mode))
                self.assertEqual(row.st_uid, binding["uid"])
                self.assertEqual(row.st_gid, binding["gid"])
                self.assertEqual(row.st_nlink, binding["nlink"])
                self.assertEqual(row.st_size, binding["size"])
                self.assertEqual(
                    format(stat.S_IMODE(row.st_mode), "04o"),
                    binding["mode"],
                )
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    binding["sha256"],
                )
                for parent in path.parents:
                    parent_row = parent.lstat()
                    if stat.S_ISLNK(parent_row.st_mode):
                        expected = contract["allowed_parent_symlinks"].get(
                            str(parent)
                        )
                        self.assertIsNotNone(expected)
                        self.assertEqual(os.readlink(parent), expected)
                    else:
                        self.assertTrue(stat.S_ISDIR(parent_row.st_mode))
                        self.assertEqual(parent_row.st_uid, 0)
                        self.assertEqual(stat.S_IMODE(parent_row.st_mode) & 0o022, 0)

    def test_fd_only_verifier_replaces_tempfile_path_in_both_modes(self) -> None:
        contract = self.stager.FD_ONLY_AUTHORITY_VERIFIER_CONTRACT
        self.assertIs(contract["implementation_complete"], True)
        self.assertIs(contract["replacement_required_in_capture"], True)
        self.assertIs(contract["replacement_required_in_materialize"], True)
        self.assertIs(contract["legacy_tempfile_signature_path_allowed"], False)
        self.assertEqual(contract["temporary_directory_create_count"], 0)
        self.assertEqual(contract["regular_file_create_count"], 0)
        self.assertEqual(contract["openssl_executable"], "/usr/bin/openssl")
        self.assertEqual(
            contract["fd_channels"],
            ["public_key", "signature", "message", "fixed_status"],
        )
        self.assertEqual(contract["fd_channel_count"], 4)
        self.assertEqual(contract["fd_transport"], "ANONYMOUS_PIPE")
        self.assertIs(
            contract["fd_unique_open_file_descriptions_required"],
            True,
        )
        self.assertIs(contract["fd_f_getfl_direction_preflight_required"], True)
        self.assertEqual(
            contract["fd_directions"],
            {
                "public_key": "PIPE_CHILD_READ_PARENT_WRITE",
                "signature": "PIPE_CHILD_READ_PARENT_WRITE",
                "message": "PIPE_CHILD_READ_PARENT_WRITE",
                "fixed_status": "PIPE_CHILD_WRITE_PARENT_READ",
            },
        )
        self.assertIs(contract["close_fds"], True)
        self.assertEqual(
            contract["pass_fds_exactly"],
            ["public_key", "signature", "message"],
        )
        self.assertIs(
            contract["core_limit_and_clean_environment_before_fd_read"],
            True,
        )
        self.assertEqual(contract["argv_material"], "FD_NUMBERS_ONLY")
        self.assertIs(
            contract["domain_message_signature_key_semantic_parity_required"],
            True,
        )

    def test_capture_core_helpers_are_real_but_public_gate_remains_first(self) -> None:
        capture = self.capture
        for name in (
            "_early_core0_clean_env_preflight",
            "_validate_runtime_and_local_objects",
            "_install_fd_only_authority_patches",
            "_prepare_capture_dependencies",
            "_build_page_request",
            "_spawn_feed_drain_once",
            "_kill_reap_prove_group_absent",
            "_record_page_once",
            "_maybe_mark_unknown_once",
            "_run_capture_once",
            "_adapter_child_main",
        ):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(capture, name)))
        self.assertIs(capture.EXECUTION_ENABLED, False)
        with mock.patch.object(
            capture,
            "_run_capture_once",
            side_effect=AssertionError("gate crossed"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "^future_execution_disabled$",
            ):
                capture.future_capture(ExplodingArgument())

    def test_capture_early_preflight_and_dependency_patch_order(self) -> None:
        capture = self.capture
        flags = types.SimpleNamespace(
            isolated=1,
            ignore_environment=1,
            no_user_site=1,
            no_site=1,
            dont_write_bytecode=1,
        )
        self.assertIs(
            capture._early_core0_clean_env_preflight(
                getrlimit=lambda _which: (0, 0),
                environ=dict(capture.CHILD_ENV),
                geteuid=lambda: 0,
                flags=flags,
                executable=capture.PYTHON_RUNTIME_EXECUTABLE,
                realpath=lambda _path: capture.PYTHON_RESOLVED_EXECUTABLE,
            ),
            True,
        )
        for limits, environment, uid, expected in (
            ((1, 1), dict(capture.CHILD_ENV), 0, "core_dump_enabled"),
            ((0, 0), {**capture.CHILD_ENV, "SECRET": "x"}, 0, "child_environment"),
            ((0, 0), dict(capture.CHILD_ENV), 501, "root_required"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(capture.CaptureError, "^" + expected + "$"):
                    capture._early_core0_clean_env_preflight(
                        getrlimit=lambda _which, value=limits: value,
                        environ=environment,
                        geteuid=lambda value=uid: value,
                        flags=flags,
                        executable=capture.PYTHON_RUNTIME_EXECUTABLE,
                        realpath=lambda _path: capture.PYTHON_RESOLVED_EXECUTABLE,
                    )

        order: list[str] = []
        original_signature = lambda *_args: False
        original_git = lambda *_args: b""
        original_openssl = lambda *_args: b""
        signature = lambda *_args: True
        local_git = lambda *_args: b"ok"
        fd_openssl = lambda *_args: b"fixed"
        authority = types.SimpleNamespace(
            _verify_signature=original_signature,
            _git=original_git,
            _openssl=original_openssl,
        )
        collector = types.SimpleNamespace(
            begin=lambda **_kwargs: None,
            finish=lambda **_kwargs: None,
            mark_unknown=lambda **_kwargs: None,
            finalize=lambda **_kwargs: None,
        )
        extractor = types.SimpleNamespace(
            validate_offline_import_response=lambda *_args: None,
        )

        def load_collector(patched):
            order.append("collector")
            self.assertIs(patched._verify_signature, signature)
            self.assertIs(patched._git, local_git)
            self.assertIs(patched._openssl, fd_openssl)
            return collector

        def load_extractor(patched):
            order.append("extractor")
            self.assertIs(patched._verify_signature, signature)
            self.assertIs(patched._git, local_git)
            self.assertIs(patched._openssl, fd_openssl)
            return extractor

        observed = capture._prepare_capture_dependencies(
            runtime_validator=lambda: order.append("runtime"),
            authority_loader=lambda: (order.append("authority"), authority)[1],
            collector_loader=load_collector,
            extractor_loader=load_extractor,
            fd_signature_verifier=signature,
            local_only_git=local_git,
            fd_only_openssl=fd_openssl,
        )
        self.assertEqual(order, ["runtime", "authority", "collector", "extractor"])
        self.assertEqual(observed, (collector, extractor))

    def test_capture_runtime_manifest_and_local_object_interface_fails_closed(self) -> None:
        capture = self.capture
        program_raw = b"capture-program\n"
        adapter_raw = b"adapter\n"
        existing_raw = {
            "collector.py": b"collector\n",
            "extractor.py": b"extractor\n",
        }
        local_bindings = {
            "tools/adapter.py": {
                "accepted_revision": "a" * 40,
                "source_revision": "b" * 40,
                "blob_oid": "c" * 40,
                "sha256": hashlib.sha256(adapter_raw).hexdigest(),
                "size": len(adapter_raw),
            }
        }
        existing_bindings = {
            name: (len(raw), hashlib.sha256(raw).hexdigest(), 0o600)
            for name, raw in existing_raw.items()
        }
        acceptance = "d" * 40
        manifest = {
            "schema": capture.RUNTIME_MANIFEST_SCHEMA,
            "manifest_name": "capture-runtime-manifest.json",
            "manifest_mode": "0600",
            "payloads": {
                "capture-root-program.py": {
                    "name": "capture-root-program.py",
                    "byte_count": len(program_raw),
                    "sha256": hashlib.sha256(program_raw).hexdigest(),
                    "mode": "0500",
                    "source_revision": acceptance,
                    "source_ref": "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py:CAPTURE_ROOT_PROGRAM",
                },
                "item26_aliyun_official_read_v2.py": {
                    "name": "item26_aliyun_official_read_v2.py",
                    "byte_count": len(adapter_raw),
                    "sha256": hashlib.sha256(adapter_raw).hexdigest(),
                    "mode": "0500",
                    "source_revision": capture.ADAPTER_ACCEPTANCE_REVISION,
                    "source_ref": "tools/item26_aliyun_official_read_v2.py",
                },
            },
        }
        manifest_raw = capture.canonical(manifest)
        capture_raw = {
            "capture-root-program.py": program_raw,
            "item26_aliyun_official_read_v2.py": adapter_raw,
            "capture-runtime-manifest.json": manifest_raw,
        }

        def row(raw, mode):
            return {
                "regular": True,
                "symlink": False,
                "uid": 0,
                "gid": 0,
                "nlink": 1,
                "mode": mode,
                "size": len(raw),
            }

        capture_modes = {
            "capture-root-program.py": 0o500,
            "item26_aliyun_official_read_v2.py": 0o500,
            "capture-runtime-manifest.json": 0o600,
        }
        probe_calls: list[str] = []

        def probe(ref, binding):
            probe_calls.append(ref)
            return {
                **binding,
                "object_local": True,
                "promisor_remote_count": 0,
                "partial_clone_extension_count": 0,
            }

        patches = (
            mock.patch.object(capture, "ADAPTER_BYTES", len(adapter_raw)),
            mock.patch.object(
                capture,
                "ADAPTER_SHA256",
                hashlib.sha256(adapter_raw).hexdigest(),
            ),
            mock.patch.object(capture, "EXISTING_RUNTIME_BINDINGS", existing_bindings),
            mock.patch.object(capture, "LOCAL_OBJECT_BINDINGS", local_bindings),
        )
        with patches[0], patches[1], patches[2], patches[3]:
            observed = capture._validate_runtime_and_local_objects(
                list_capture_names=lambda: list(capture_raw),
                read_capture_file=capture_raw.__getitem__,
                stat_capture_file=lambda name: row(
                    capture_raw[name], capture_modes[name]
                ),
                list_existing_names=lambda: list(existing_raw),
                read_existing_file=existing_raw.__getitem__,
                stat_existing_file=lambda name: row(existing_raw[name], 0o600),
                git_probe=probe,
                expected_program_bytes=len(program_raw),
                expected_program_sha256=hashlib.sha256(program_raw).hexdigest(),
                expected_manifest_bytes=len(manifest_raw),
                expected_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                expected_acceptance_revision=acceptance,
            )
            self.assertEqual(observed, manifest)
            self.assertEqual(probe_calls, ["tools/adapter.py"])

            def promisor_probe(_ref, binding):
                return {
                    **binding,
                    "object_local": True,
                    "promisor_remote_count": 1,
                    "partial_clone_extension_count": 0,
                }

            with self.assertRaisesRegex(capture.CaptureError, "^local_object_binding$"):
                capture._validate_runtime_and_local_objects(
                    list_capture_names=lambda: list(capture_raw),
                    read_capture_file=capture_raw.__getitem__,
                    stat_capture_file=lambda name: row(
                        capture_raw[name], capture_modes[name]
                    ),
                    list_existing_names=lambda: list(existing_raw),
                    read_existing_file=existing_raw.__getitem__,
                    stat_existing_file=lambda name: row(existing_raw[name], 0o600),
                    git_probe=promisor_probe,
                    expected_program_bytes=len(program_raw),
                    expected_program_sha256=hashlib.sha256(program_raw).hexdigest(),
                    expected_manifest_bytes=len(manifest_raw),
                    expected_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                    expected_acceptance_revision=acceptance,
                )

    def test_capture_request_builder_and_post_finish_identity_parity(self) -> None:
        capture = self.capture
        old_identifier = "fake-old-identifier"
        source_identifier = "fake-source-identifier"

        def identity_hash(value):
            if value == old_identifier:
                return capture.EXPECTED_OLD_CLONE_SHA256
            if value == source_identifier:
                return capture.EXPECTED_SOURCE_SHA256
            return hashlib.sha256(value.encode("utf-8")).hexdigest()

        cost_raw = capture._build_page_request(
            capture.SLOTS[0],
            {},
            value_sha256=identity_hash,
        )
        create_raw = capture._build_page_request(
            capture.SLOTS[1],
            {"old_clone": old_identifier},
            "next-token",
            value_sha256=identity_hash,
        )
        create = json.loads(create_raw)
        self.assertEqual(
            create["LookupAttribute"],
            [
                {"Key": "EventName", "Value": "CloneDBInstance"},
                {"Key": "ResourceName", "Value": old_identifier},
            ],
        )
        self.assertEqual(create["NextToken"], "next-token")
        clone = json.loads(
            capture._build_page_request(
                capture.SLOTS[2],
                {"old_clone": old_identifier},
                value_sha256=identity_hash,
            )
        )
        self.assertEqual(clone["DBInstanceId"], old_identifier)
        source = json.loads(
            capture._build_page_request(
                capture.SLOTS[3],
                {"source": source_identifier},
                value_sha256=identity_hash,
            )
        )
        self.assertEqual(source["DBInstanceId"], source_identifier)
        billing = json.loads(
            capture._build_page_request(
                capture.SLOTS[4],
                {"old_clone": old_identifier, "source": source_identifier},
                value_sha256=identity_hash,
            )
        )
        self.assertEqual(billing["Action"], "QueryInstanceBill")

        parity_calls: list[tuple[str, dict[str, object], dict[str, object]]] = []
        extractor = types.SimpleNamespace(
            validate_offline_import_response=lambda slot, request, response: (
                parity_calls.append((slot, request, response))
            )
        )
        response_raw = b'{"Events":[{"requestParameters":{"DBInstanceId":"fake-old-identifier"}}],"NextToken":"page-2"}\n'
        derived = capture._derive_after_finish(
            capture.SLOTS[0],
            cost_raw,
            response_raw,
            extractor,
        )
        self.assertEqual(derived["next_token"], "page-2")
        self.assertEqual(derived["identifier_candidates"], [old_identifier])
        self.assertEqual(len(parity_calls), 1)
        self.assertEqual(
            capture._terminal_identifier(
                [old_identifier, old_identifier],
                capture.EXPECTED_OLD_CLONE_SHA256,
                value_sha256=identity_hash,
            ),
            old_identifier,
        )
        with self.assertRaisesRegex(
            capture.CaptureError,
            "^terminal_identifier_binding$",
        ):
            capture._terminal_identifier(
                [old_identifier, "different"],
                capture.EXPECTED_OLD_CLONE_SHA256,
                value_sha256=identity_hash,
            )

    def test_capture_child_pump_uses_four_fd_concurrent_drain_and_scrubs_sts(self) -> None:
        capture = self.capture
        request_raw = capture.canonical(
            {
                "Action": "QueryInstanceBill",
                "Version": "2017-12-14",
                "BillingCycle": "2026-08",
                "ProductCode": "rds",
                "SubscriptionType": "PayAsYouGo",
                "IsBillingItem": False,
                "IsHideZeroCharge": False,
                "Granularity": "MONTHLY",
                "PageNum": 1,
                "PageSize": 300,
            }
        )
        credential = bytearray(b'{"temporary":"fake-sts"}\n')
        original_credential = bytes(credential)
        response_raw = b'{"z":1, "a":2}\n'
        popen_calls: list[tuple[list[str], dict[str, object]]] = []

        class FakeProcess:
            pid = 64001

            def __init__(self, thread):
                self.thread = thread
                self.returncode = None
                self.wait_count = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.wait_count += 1
                if self.wait_count == 1:
                    raise subprocess.TimeoutExpired("fake", timeout)
                self.thread.join(timeout)
                if self.thread.is_alive():
                    raise subprocess.TimeoutExpired("fake", timeout)
                return self.returncode

        def read_all(channel):
            chunks = []
            while True:
                chunk = channel.recv(65536)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)

        def fake_popen(argv, **kwargs):
            popen_calls.append((list(argv), dict(kwargs)))
            duplicated = [os.dup(fd) for fd in kwargs["pass_fds"]]
            process_box: list[FakeProcess] = []

            def child():
                channels = [
                    capture.socket.socket(fileno=fd) for fd in duplicated
                ]
                try:
                    self.assertEqual(read_all(channels[0]), request_raw)
                    self.assertEqual(read_all(channels[1]), original_credential)
                    channels[2].sendall(response_raw)
                    channels[2].shutdown(capture.socket.SHUT_WR)
                    channels[3].sendall(child_success_raw(capture))
                    channels[3].shutdown(capture.socket.SHUT_WR)
                    process_box[0].returncode = 0
                finally:
                    for channel in channels:
                        channel.close()

            thread = threading.Thread(target=child, daemon=True)
            process = FakeProcess(thread)
            process_box.append(process)
            thread.start()
            return process

        kill_calls: list[int] = []

        def absent_group(_pid, sig):
            kill_calls.append(sig)
            if sig == 0:
                raise ProcessLookupError

        result = capture._spawn_feed_drain_once(
            request_raw,
            credential,
            runtime_arguments=fake_capture_runtime_arguments(),
            popen=fake_popen,
            killpg=absent_group,
            identity_snapshot=lambda: fake_child_identity_snapshot(capture),
            runtime_identity_snapshot=lambda _arguments: (
                fake_capture_runtime_identity(capture)
            ),
        )
        self.assertEqual(result["response_raw"], response_raw)
        self.assertEqual(result["status_raw"], child_success_raw(capture))
        self.assertEqual(result["cloud_dispatch_count"], 1)
        self.assertIs(result["group_absent"], True)
        self.assertEqual(kill_calls, [capture.signal.SIGKILL, 0])
        self.assertEqual(credential, bytearray(len(original_credential)))
        self.assertEqual(len(popen_calls), 1)
        argv, kwargs = popen_calls[0]
        self.assertEqual(argv[:5], [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-B",
            capture.CAPTURE_PROGRAM_PATH,
        ])
        self.assertEqual(argv[5], "--adapter-child")
        self.assertEqual(len(argv), 15)
        self.assertNotIn("fake-sts", repr((argv, kwargs)))
        self.assertEqual(kwargs["env"], capture.CHILD_ENV)
        self.assertIs(kwargs["close_fds"], True)
        self.assertEqual(len(kwargs["pass_fds"]), 4)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)

    def test_capture_socket_identity_is_portable_and_rejects_nonanonymous_shapes(self) -> None:
        capture = self.capture
        left, right = capture.socket.socketpair(
            capture.socket.AF_UNIX,
            capture.socket.SOCK_STREAM,
        )

        class SocketView:
            def __init__(self, channel, *, family=None, socket_type=None, local=None, peer=None):
                self.channel = channel
                self.family = channel.family if family is None else family
                self.socket_type = socket_type
                self.local = local
                self.peer = peer

            def fileno(self):
                return self.channel.fileno()

            def getsockopt(self, level, option):
                if option == capture.socket.SO_TYPE and self.socket_type is not None:
                    return self.socket_type
                return self.channel.getsockopt(level, option)

            def getblocking(self):
                return self.channel.getblocking()

            def getsockname(self):
                return self.channel.getsockname() if self.local is None else self.local

            def getpeername(self):
                return self.channel.getpeername() if self.peer is None else self.peer

        try:
            fake_row = types.SimpleNamespace(st_dev=7, st_ino=9, st_nlink=1)
            with mock.patch.object(capture.os, "fstat", return_value=fake_row):
                self.assertEqual(capture._socket_identity(left), (7, 9))
            for label, view in (
                (
                    "named",
                    SocketView(left, local="/tmp/forbidden-named-socket"),
                ),
                (
                    "tcp",
                    SocketView(left, family=capture.socket.AF_INET),
                ),
                (
                    "seqpacket",
                    SocketView(
                        left,
                        socket_type=getattr(capture.socket, "SOCK_SEQPACKET", 5),
                    ),
                ),
                (
                    "named-peer",
                    SocketView(left, peer="/tmp/forbidden-peer"),
                ),
            ):
                with self.subTest(label=label):
                    with self.assertRaisesRegex(capture.CaptureError, "^fd_identity$"):
                        capture._socket_identity(view)
            capture_tree = ast.parse(self.stager.CAPTURE_ROOT_PROGRAM)
            function = next(
                node
                for node in ast.walk(capture_tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "_socket_identity"
            )
            function_source = ast.get_source_segment(
                self.stager.CAPTURE_ROOT_PROGRAM,
                function,
            )
            self.assertNotIn("st_nlink", function_source)
            self.assertIn("getsockname", function_source)
            self.assertIn("getpeername", function_source)
        finally:
            left.close()
            right.close()

    def test_capture_adapter_child_rejects_each_nonblocking_fd_before_load(self) -> None:
        capture = self.capture
        for blocked_index in range(4):
            with self.subTest(blocked_index=blocked_index):
                pairs = [
                    capture.socket.socketpair(
                        capture.socket.AF_UNIX,
                        capture.socket.SOCK_STREAM,
                    )
                    for _ in range(4)
                ]
                child_fds = tuple(pair[1].fileno() for pair in pairs)
                capture.os.set_blocking(child_fds[blocked_index], False)
                calls = {"runtime": 0, "loader": 0, "dispatch": 0}

                def runtime_validator():
                    calls["runtime"] += 1

                def adapter_loader():
                    calls["loader"] += 1

                    def dispatch(*_args):
                        calls["dispatch"] += 1

                    return types.SimpleNamespace(
                        dispatch_authorized_fds=dispatch
                    )

                try:
                    with self.assertRaisesRegex(
                        capture.CaptureError,
                        "^fd_identity$",
                    ):
                        capture._adapter_child_main(
                            [
                                "--adapter-child",
                                *(str(fd) for fd in child_fds),
                                *fake_capture_runtime_arguments(),
                            ],
                            runtime_validator=runtime_validator,
                            adapter_loader=adapter_loader,
                            preflight=lambda: True,
                        )
                    self.assertEqual(
                        calls,
                        {"runtime": 0, "loader": 0, "dispatch": 0},
                    )
                finally:
                    for pair in pairs:
                        for channel in pair:
                            channel.close()

    def test_capture_python_resolved_python_and_ca_identity_snapshot_is_stable(self) -> None:
        capture = self.capture
        self.assertEqual(
            capture.CHILD_TOOL_BINDINGS[capture.ADAPTER_PATH],
            {
                "sha256": capture.ADAPTER_SHA256,
                "size": capture.ADAPTER_BYTES,
                "mode": 0o500,
                "uid": 0,
                "gid": 0,
                "nlink": 1,
            },
        )
        leaf_calls: list[tuple[str, dict[str, object]]] = []

        def snapshot_bound_file(path, binding):
            leaf_calls.append((path, binding))
            parent_chain = [
                {
                    "path": "/",
                    "kind": "directory",
                    "target": None,
                    "mode": 0o755,
                    "uid": 0,
                    "gid": 0,
                }
            ]
            if path == "/etc/ssl/cert.pem":
                parent_chain.insert(
                    0,
                    {
                        "path": "/etc",
                        "kind": "allowed_symlink",
                        "target": "private/etc",
                        "mode": 0o755,
                        "uid": 0,
                        "gid": 0,
                    },
                )
            return {
                "path": path,
                "sha256": binding["sha256"],
                "size": binding["size"],
                "mode": binding["mode"],
                "uid": binding["uid"],
                "gid": binding["gid"],
                "nlink": binding["nlink"],
                "parent_chain": parent_chain,
            }

        with mock.patch.object(
            capture,
            "_snapshot_bound_file",
            side_effect=snapshot_bound_file,
        ):
            first = capture._capture_system_identity_snapshot()
            second = capture._capture_system_identity_snapshot()
        self.assertEqual(first, second)
        self.assertEqual(
            leaf_calls,
            [
                (path, binding)
                for _unused in range(2)
                for path, binding in capture.CHILD_SYSTEM_TOOL_BINDINGS.items()
            ],
        )
        self.assertEqual(set(first), set(capture.CHILD_SYSTEM_TOOL_BINDINGS))
        for path, binding in capture.CHILD_SYSTEM_TOOL_BINDINGS.items():
            with self.subTest(path=path):
                self.assertEqual(first[path]["path"], path)
                self.assertEqual(first[path]["sha256"], binding["sha256"])
                self.assertEqual(first[path]["size"], binding["size"])
                self.assertEqual(first[path]["mode"], binding["mode"])
                self.assertEqual(first[path]["uid"], 0)
                self.assertEqual(first[path]["gid"], 0)
                self.assertEqual(first[path]["nlink"], binding["nlink"])
                self.assertTrue(first[path]["parent_chain"])
                for row in first[path]["parent_chain"]:
                    self.assertEqual(row["uid"], 0)
                    self.assertEqual(row["gid"], 0)
                    if row["kind"] == "directory":
                        self.assertEqual(row["mode"] & 0o022, 0)
                    else:
                        self.assertEqual(row["path"], "/etc")
                        self.assertEqual(row["target"], "private/etc")

    def test_capture_child_parent_exception_always_kills_reaps_and_proves_group(self) -> None:
        capture = self.capture
        request_raw = capture.canonical({"Action": "fake"})

        class FakeProcess:
            pid = 64002

            def __init__(self):
                self.wait_count = 0

            def poll(self):
                return None

            def wait(self, timeout=None):
                self.wait_count += 1
                self.timeout = timeout
                return -9

        class ExplodingSelector:
            def register(self, *_args):
                raise RuntimeError("selector registration failed")

            def close(self):
                self.closed = True

        process = FakeProcess()
        kill_calls: list[int] = []

        def killpg(_pid, sig):
            kill_calls.append(sig)
            if sig == 0:
                raise ProcessLookupError

        credential = bytearray(b"fake-temporary-sts")
        with self.assertRaisesRegex(capture.CaptureError, "^child_internal$") as caught:
            capture._spawn_feed_drain_once(
                request_raw,
                credential,
                runtime_arguments=fake_capture_runtime_arguments(),
                popen=lambda *_args, **_kwargs: process,
                selector_factory=ExplodingSelector,
                killpg=killpg,
                identity_snapshot=lambda: fake_child_identity_snapshot(capture),
                runtime_identity_snapshot=lambda _arguments: (
                    fake_capture_runtime_identity(capture)
                ),
            )
        self.assertEqual(kill_calls, [capture.signal.SIGKILL, 0])
        self.assertEqual(process.wait_count, 1)
        self.assertGreater(process.timeout, 0)
        self.assertIs(caught.exception.state["group_absent"], True)
        self.assertEqual(credential, bytearray(len(credential)))

        process = FakeProcess()
        kill_calls.clear()

        def group_still_present(_pid, sig):
            kill_calls.append(sig)

        clock_value = [0.0]

        def bounded_clock():
            clock_value[0] += 1.0
            return clock_value[0]

        with self.assertRaisesRegex(
            capture.CaptureError,
            "^process_group_absence_unproven$",
        ) as unproven:
            capture._spawn_feed_drain_once(
                request_raw,
                bytearray(b"fake-temporary-sts"),
                runtime_arguments=fake_capture_runtime_arguments(),
                popen=lambda *_args, **_kwargs: process,
                selector_factory=ExplodingSelector,
                killpg=group_still_present,
                monotonic=bounded_clock,
                sleep=lambda _seconds: None,
                identity_snapshot=lambda: fake_child_identity_snapshot(capture),
                runtime_identity_snapshot=lambda _arguments: (
                    fake_capture_runtime_identity(capture)
                ),
            )
        self.assertEqual(kill_calls, [capture.signal.SIGKILL, 0])
        self.assertEqual(process.wait_count, 1)
        self.assertIs(unproven.exception.state["group_absent"], False)
        forbidden = types.SimpleNamespace(
            mark_unknown=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("mark-unknown without group proof")
            )
        )
        self.assertIs(
            capture._maybe_mark_unknown_once(
                forbidden,
                slot=capture.SLOTS[0],
                reason="TRANSPORT_TIMEOUT",
                state={
                    "begin_observed": True,
                    "finish_invoked": False,
                    "group_absent": False,
                },
                explicitly_authorized=True,
            ),
            False,
        )

    def test_capture_reaped_leader_with_descendant_group_is_killed_and_reprobed(self) -> None:
        capture = self.capture

        class ReapedLeader:
            pid = 64003

            def __init__(self):
                self.wait_count = 0

            def wait(self, timeout=None):
                self.wait_count += 1
                self.timeout = timeout
                return 0

        process = ReapedLeader()
        calls: list[int] = []

        def residual_then_absent(_pid, sig):
            calls.append(sig)
            if calls == [0, capture.signal.SIGKILL, 0]:
                raise ProcessLookupError

        proof = capture._kill_reap_prove_group_absent(
            process,
            force_kill=False,
            wait_timeout=1.0,
            reap_timeout=2.0,
            killpg=residual_then_absent,
        )
        self.assertEqual(calls, [0, capture.signal.SIGKILL, 0])
        self.assertEqual(process.wait_count, 1)
        self.assertIs(proof["reaped"], True)
        self.assertIs(proof["group_absent"], True)
        self.assertIs(proof["kill_sent"], True)

    def test_record_page_at_most_once_failure_matrix_is_enforced(self) -> None:
        capture = self.capture
        slot = capture.SLOTS[0]
        request_raw = capture._build_page_request(slot, {})
        response_raw = b'{"Events":[{"requestParameters":{"DBInstanceId":"fake-old"}}]}\n'
        events: list[str] = []

        class Collector:
            def begin(self, **kwargs):
                events.append("begin")
                return collector_status(
                    capture,
                    "REQUEST_FROZEN",
                    slot=slot,
                    digest_key="request_sha256",
                    digest=hashlib.sha256(kwargs["request_raw"]).hexdigest(),
                )

            def finish(self, **kwargs):
                events.append("finish")
                self.assert_same = kwargs["response_raw"] is response_raw
                return collector_status(
                    capture,
                    "RESPONSE_RECORDED",
                    slot=slot,
                    digest_key="response_sha256",
                    digest=hashlib.sha256(kwargs["response_raw"]).hexdigest(),
                )

            def mark_unknown(self, **_kwargs):
                events.append("mark_unknown")
                return collector_status(capture, "UNKNOWN_INFLIGHT", slot=slot)

        collector = Collector()
        extractor = types.SimpleNamespace(
            validate_offline_import_response=lambda *_args: events.append("extract")
        )
        issued: list[bytearray] = []

        def credential_supplier():
            value = dispatch_credential()
            issued.append(value["envelope"])
            return value

        def child_runner(_request, _credential, **_kwargs):
            events.append("child")
            return {
                "response_raw": response_raw,
                "status_raw": child_success_raw(capture),
                "cloud_dispatch_count": 1,
                "group_absent": True,
                "child_spawned": True,
            }

        result = capture._record_page_once(
            collector,
            extractor,
            slot=slot,
            request_raw=request_raw,
            credential_supplier=credential_supplier,
            expected_credential_capsule=expected_credential_capsule(),
            expected_sequence=1,
            child_runner=child_runner,
        )
        self.assertEqual(events, ["begin", "child", "finish", "extract"])
        self.assertIs(collector.assert_same, True)
        self.assertEqual(result["cloud_dispatch_count"], 1)
        self.assertTrue(all(value == bytearray(len(value)) for value in issued))

        class BeginLost(Collector):
            def begin(self, **_kwargs):
                events.append("begin_lost")
                raise RuntimeError("secret must not escape")

        events.clear()
        with self.assertRaisesRegex(capture.CaptureError, "^begin_result_unknown$") as caught:
            capture._record_page_once(
                BeginLost(),
                extractor,
                slot=slot,
                request_raw=request_raw,
                credential_supplier=credential_supplier,
                expected_credential_capsule=expected_credential_capsule(),
                expected_sequence=1,
                child_runner=lambda *_args, **_kwargs: events.append("forbidden_child"),
                explicitly_authorized_mark_unknown=True,
            )
        self.assertEqual(events, ["begin_lost"])
        self.assertEqual(caught.exception.state["child_spawn_count"], 0)

        events.clear()

        def failed_child(_request, _credential, **_kwargs):
            events.append("child_failed")
            raise capture.CaptureError(
                "child_timeout",
                {"child_spawned": True, "group_absent": True},
            )

        with self.assertRaisesRegex(capture.CaptureError, "^child_timeout$"):
            capture._record_page_once(
                collector,
                extractor,
                slot=slot,
                request_raw=request_raw,
                credential_supplier=credential_supplier,
                expected_credential_capsule=expected_credential_capsule(),
                expected_sequence=1,
                child_runner=failed_child,
                explicitly_authorized_mark_unknown=True,
            )
        self.assertEqual(events, ["begin", "child_failed", "mark_unknown"])

        events.clear()

        def unproven_child(_request, _credential, **_kwargs):
            events.append("child_unproven")
            raise capture.CaptureError(
                "child_timeout",
                {"child_spawned": True, "group_absent": False},
            )

        with self.assertRaisesRegex(capture.CaptureError, "^child_timeout$"):
            capture._record_page_once(
                collector,
                extractor,
                slot=slot,
                request_raw=request_raw,
                credential_supplier=credential_supplier,
                expected_credential_capsule=expected_credential_capsule(),
                expected_sequence=1,
                child_runner=unproven_child,
                explicitly_authorized_mark_unknown=True,
            )
        self.assertEqual(events, ["begin", "child_unproven"])

        events.clear()

        class FinishLost(Collector):
            def finish(self, **_kwargs):
                events.append("finish_lost")
                raise RuntimeError("unknown finish result")

        with self.assertRaisesRegex(capture.CaptureError, "^finish_result_unknown$") as finish_lost:
            capture._record_page_once(
                FinishLost(),
                extractor,
                slot=slot,
                request_raw=request_raw,
                credential_supplier=credential_supplier,
                expected_credential_capsule=expected_credential_capsule(),
                expected_sequence=1,
                child_runner=child_runner,
                explicitly_authorized_mark_unknown=True,
            )
        self.assertEqual(events, ["begin", "child", "finish_lost"])
        self.assertIs(finish_lost.exception.state["finish_invoked"], True)
        self.assertIs(finish_lost.exception.state["mark_unknown_invoked"], False)

        events.clear()

        class MarkLost(Collector):
            def mark_unknown(self, **_kwargs):
                events.append("mark_lost")
                raise RuntimeError("unknown mark result")

        with self.assertRaisesRegex(
            capture.CaptureError,
            "^mark_unknown_result_unknown$",
        ) as mark_lost:
            capture._record_page_once(
                MarkLost(),
                extractor,
                slot=slot,
                request_raw=request_raw,
                credential_supplier=credential_supplier,
                expected_credential_capsule=expected_credential_capsule(),
                expected_sequence=1,
                child_runner=failed_child,
                explicitly_authorized_mark_unknown=True,
            )
        self.assertEqual(events, ["begin", "child_failed", "mark_lost"])
        self.assertIs(mark_lost.exception.state["mark_unknown_invoked"], True)

        events.clear()
        begin_count = 0

        def too_short_sts():
            return dispatch_credential(remaining_seconds=959)

        class CountBegin(Collector):
            def begin(self, **kwargs):
                nonlocal begin_count
                begin_count += 1
                return super().begin(**kwargs)

        with self.assertRaisesRegex(capture.CaptureError, "^temporary_sts_pre_begin$"):
            capture._record_page_once(
                CountBegin(),
                extractor,
                slot=slot,
                request_raw=request_raw,
                credential_supplier=too_short_sts,
                expected_credential_capsule=expected_credential_capsule(),
                expected_sequence=1,
                child_runner=child_runner,
            )
        self.assertEqual(begin_count, 0)

    def test_capture_credential_capsule_is_constant_finite_and_never_refreshed(self) -> None:
        capture = self.capture
        capsule = capture._initial_credential_capsule(
            initial_credential_probe()
        )
        first = dispatch_credential(remaining_seconds=1500)
        first_envelope = first["envelope"]
        self.assertIs(
            capture._validate_dispatch_credential(first, capsule),
            first_envelope,
        )
        self.assertEqual(capsule["last_remaining_seconds"], 1500)
        second = dispatch_credential(remaining_seconds=1200)
        self.assertIs(
            capture._validate_dispatch_credential(second, capsule),
            second["envelope"],
        )
        self.assertEqual(capsule["last_remaining_seconds"], 1200)

        bad_values = []
        increasing = dispatch_credential(remaining_seconds=1300)
        bad_values.append(increasing)
        nan_ttl = dispatch_credential()
        nan_ttl["remaining_seconds"] = float("nan")
        bad_values.append(nan_ttl)
        refreshed = dispatch_credential()
        refreshed["refresh_count"] = 1
        bad_values.append(refreshed)
        reconfigured = dispatch_credential()
        reconfigured["configure_count"] = 1
        bad_values.append(reconfigured)
        wrong_account = dispatch_credential()
        wrong_account["account_binding_sha256"] = "b" * 64
        bad_values.append(wrong_account)
        wrong_envelope = dispatch_credential(raw=b"different-fake-sts")
        bad_values.append(wrong_envelope)
        for index, value in enumerate(bad_values):
            envelope = value["envelope"]
            with self.subTest(index=index):
                with self.assertRaisesRegex(
                    capture.CaptureError,
                    "^temporary_sts_pre_begin$",
                ):
                    capture._validate_dispatch_credential(value, capsule)
                self.assertEqual(envelope, bytearray(len(envelope)))

        for invalid_initial in (
            initial_credential_probe(remaining_seconds=float("nan")),
            initial_credential_probe(remaining_seconds=1859),
        ):
            with self.assertRaisesRegex(
                capture.CaptureError,
                "^initial_temporary_sts$",
            ):
                capture._initial_credential_capsule(invalid_initial)

    def test_capture_orchestrator_runs_exact_slots_tokens_limit_and_finalize_once(self) -> None:
        capture = self.capture
        old_identifier = "fake-old-identifier"
        source_identifier = "fake-source-identifier"

        def identity_hash(value):
            return {
                old_identifier: capture.EXPECTED_OLD_CLONE_SHA256,
                source_identifier: capture.EXPECTED_SOURCE_SHA256,
            }.get(value, hashlib.sha256(value.encode("utf-8")).hexdigest())

        class Collector:
            def __init__(self):
                self.begin_slots: list[str] = []
                self.finish_slots: list[str] = []
                self.finalize_calls = 0

            def begin(self, **kwargs):
                self.begin_slots.append(kwargs["slot"])
                return collector_status(
                    capture,
                    "REQUEST_FROZEN",
                    slot=kwargs["slot"],
                    digest_key="request_sha256",
                    digest=hashlib.sha256(kwargs["request_raw"]).hexdigest(),
                    sequence=len(self.begin_slots),
                )

            def finish(self, **kwargs):
                self.finish_slots.append(kwargs["slot"])
                return collector_status(
                    capture,
                    "RESPONSE_RECORDED",
                    slot=kwargs["slot"],
                    digest_key="response_sha256",
                    digest=hashlib.sha256(kwargs["response_raw"]).hexdigest(),
                    sequence=len(self.finish_slots),
                )

            def mark_unknown(self, **_kwargs):
                raise AssertionError("unexpected mark-unknown")

            def finalize(self, **kwargs):
                self.assert_control = kwargs["control_revision"]
                self.finalize_calls += 1
                return {
                    "schema": "noteai.item26.manual-cost-stop-collector-status.v2",
                    "status": "CAPTURE_INSTALLED",
                    "provider_raw_file_sha256": "a" * 64,
                    "actiontrail_raw_file_sha256": "b" * 64,
                    "cloud_call_count": 0,
                    "raw_value_emitted_count": 0,
                }

        collector = Collector()
        extractor = types.SimpleNamespace(
            validate_offline_import_response=lambda *_args: None
        )
        cost_pages = 0

        def child_runner(request_raw, _credential, **_kwargs):
            nonlocal cost_pages
            request = json.loads(request_raw)
            action = request["Action"]
            if action == "LookupEvents" and request["LookupAttribute"][0]["Key"] == "ServiceName":
                cost_pages += 1
                response = {
                    "Events": [
                        {"requestParameters": {"DBInstanceId": old_identifier}}
                    ]
                }
                if cost_pages == 1:
                    response["NextToken"] = "cost-page-2"
            elif action == "LookupEvents":
                response = {
                    "Events": [
                        {
                            "requestParameters": {
                                "SourceDBInstanceId": source_identifier
                            }
                        }
                    ]
                }
            else:
                response = {"RequestId": "fake"}
            return {
                "response_raw": capture.canonical(response),
                "status_raw": child_success_raw(capture),
                "cloud_dispatch_count": 1,
                "group_absent": True,
                "child_spawned": True,
            }

        credentials: list[bytearray] = []

        def supply():
            value = dispatch_credential()
            credentials.append(value["envelope"])
            return value

        result = capture._run_capture_once(
            prepare_dependencies=lambda: (collector, extractor),
            credential_probe=initial_credential_probe,
            credential_supplier=supply,
            child_runner=child_runner,
            value_sha256=identity_hash,
        )
        expected_slots = [
            capture.SLOTS[0],
            capture.SLOTS[0],
            capture.SLOTS[1],
            capture.SLOTS[2],
            capture.SLOTS[3],
            capture.SLOTS[4],
        ]
        self.assertEqual(collector.begin_slots, expected_slots)
        self.assertEqual(collector.finish_slots, expected_slots)
        self.assertEqual(collector.finalize_calls, 1)
        self.assertEqual(collector.assert_control, capture.CONTROL_REVISION)
        self.assertEqual(result["provider_dispatch_count"], 6)
        self.assertEqual(result["logical_slot_count"], 5)
        self.assertEqual(result["parallel_provider_dispatch_count"], 0)
        self.assertEqual(result["finalize_call_count"], 1)
        self.assertTrue(all(value == bytearray(len(value)) for value in credentials))

    def test_capture_orchestrator_rejects_token_cycle_and_global_64_without_finalize(self) -> None:
        capture = self.capture
        old_identifier = "fake-old-identifier"

        def identity_hash(value):
            if value == old_identifier:
                return capture.EXPECTED_OLD_CLONE_SHA256
            return hashlib.sha256(value.encode("utf-8")).hexdigest()

        class Collector:
            def __init__(self):
                self.begin_count = 0
                self.finish_count = 0
                self.finalize_count = 0

            def begin(self, **kwargs):
                self.begin_count += 1
                return collector_status(
                    capture,
                    "REQUEST_FROZEN",
                    slot=kwargs["slot"],
                    digest_key="request_sha256",
                    digest=hashlib.sha256(kwargs["request_raw"]).hexdigest(),
                    sequence=self.begin_count,
                )

            def finish(self, **kwargs):
                self.finish_count += 1
                return collector_status(
                    capture,
                    "RESPONSE_RECORDED",
                    slot=kwargs["slot"],
                    digest_key="response_sha256",
                    digest=hashlib.sha256(kwargs["response_raw"]).hexdigest(),
                    sequence=self.finish_count,
                )

            def mark_unknown(self, **_kwargs):
                raise AssertionError("unexpected mark")

            def finalize(self, **_kwargs):
                self.finalize_count += 1
                raise AssertionError("unexpected finalize")

        extractor = types.SimpleNamespace(
            validate_offline_import_response=lambda *_args: None
        )

        def supply():
            return dispatch_credential()

        def run_with_token(token_factory, expected_code, expected_count):
            collector = Collector()
            calls = 0

            def child(_request, _credential, **_kwargs):
                nonlocal calls
                calls += 1
                response = {
                    "Events": [
                        {"requestParameters": {"DBInstanceId": old_identifier}}
                    ],
                    "NextToken": token_factory(calls),
                }
                return {
                    "response_raw": capture.canonical(response),
                    "status_raw": child_success_raw(capture),
                    "cloud_dispatch_count": 1,
                    "group_absent": True,
                    "child_spawned": True,
                }

            with self.assertRaisesRegex(capture.CaptureError, "^" + expected_code + "$"):
                capture._run_capture_once(
                    prepare_dependencies=lambda: (collector, extractor),
                    credential_probe=initial_credential_probe,
                    credential_supplier=supply,
                    child_runner=child,
                    value_sha256=identity_hash,
                    monotonic=lambda: 0.0,
                )
            self.assertEqual(calls, expected_count)
            self.assertEqual(collector.begin_count, expected_count)
            self.assertEqual(collector.finish_count, expected_count)
            self.assertEqual(collector.finalize_count, 0)

        run_with_token(lambda _call: "same-token", "pagination_token_cycle", 2)
        run_with_token(
            lambda call: "token-" + str(call),
            "global_record_limit",
            64,
        )

    def test_capture_finalize_result_and_post_finalize_deadline_are_never_retried(self) -> None:
        capture = self.capture
        old_identifier = "fake-old-identifier"
        source_identifier = "fake-source-identifier"

        def identity_hash(value):
            return {
                old_identifier: capture.EXPECTED_OLD_CLONE_SHA256,
                source_identifier: capture.EXPECTED_SOURCE_SHA256,
            }.get(value, hashlib.sha256(value.encode("utf-8")).hexdigest())

        def fake_record(_collector, _extractor, *, slot, **_kwargs):
            candidates = (
                [old_identifier]
                if slot == capture.SLOTS[0]
                else [source_identifier]
                if slot == capture.SLOTS[1]
                else []
            )
            return {
                "next_token": None,
                "identifier_candidates": candidates,
                "cloud_dispatch_count": 1,
                "state": {},
            }

        valid_finalize = {
            "schema": "noteai.item26.manual-cost-stop-collector-status.v2",
            "status": "CAPTURE_INSTALLED",
            "provider_raw_file_sha256": "a" * 64,
            "actiontrail_raw_file_sha256": "b" * 64,
            "cloud_call_count": 0,
            "raw_value_emitted_count": 0,
        }

        class Finalizer:
            def __init__(self, *, lose=False, clock=None):
                self.calls = 0
                self.lose = lose
                self.clock = clock

            def finalize(self, **_kwargs):
                self.calls += 1
                if self.clock is not None:
                    self.clock[0] = 900.0
                if self.lose:
                    raise RuntimeError("finalize result lost")
                return dict(valid_finalize)

        extractor = types.SimpleNamespace()
        with mock.patch.object(capture, "_record_page_once", side_effect=fake_record):
            lost = Finalizer(lose=True)
            with self.assertRaisesRegex(
                capture.CaptureError,
                "^finalize_result_unknown$",
            ):
                capture._run_capture_once(
                    prepare_dependencies=lambda: (lost, extractor),
                    credential_probe=initial_credential_probe,
                    credential_supplier=dispatch_credential,
                    value_sha256=identity_hash,
                    monotonic=lambda: 0.0,
                )
            self.assertEqual(lost.calls, 1)

            clock = [0.0]
            late = Finalizer(clock=clock)
            with self.assertRaisesRegex(
                capture.CaptureError,
                "^finalize_completed_after_deadline$",
            ):
                capture._run_capture_once(
                    prepare_dependencies=lambda: (late, extractor),
                    credential_probe=initial_credential_probe,
                    credential_supplier=dispatch_credential,
                    value_sha256=identity_hash,
                    monotonic=lambda: clock[0],
                )
            self.assertEqual(late.calls, 1)

    def test_capture_enabled_main_has_distinct_child_and_orchestrator_modes(self) -> None:
        capture = self.capture
        runtime_arguments = fake_capture_runtime_arguments()
        child_calls: list[list[str]] = []
        self.assertEqual(
            capture._enabled_main(
                [
                    "--adapter-child",
                    "3",
                    "4",
                    "5",
                    "6",
                    *runtime_arguments,
                ],
                adapter_child_runner=lambda argv: (
                    child_calls.append(list(argv)),
                    17,
                )[1],
            ),
            17,
        )
        self.assertEqual(
            child_calls,
            [[
                "--adapter-child",
                "3",
                "4",
                "5",
                "6",
                *runtime_arguments,
            ]],
        )
        output = io.BytesIO()
        result = {
            "schema": capture.CAPTURE_SUCCESS_SCHEMA,
            "status": "FIVE_STREAM_CAPTURE_FINALIZED",
            "raw_value_emitted_count": 0,
        }
        self.assertEqual(
            capture._enabled_main(
                ["--capture", *runtime_arguments],
                capture_runner=lambda _arguments: result,
                status_stream=output,
            ),
            0,
        )
        self.assertEqual(json.loads(output.getvalue()), result)
        with self.assertRaisesRegex(capture.CaptureError, "^capture_root_arguments$"):
            capture._enabled_main([], capture_runner=lambda _arguments: result)
        blocked_output = io.BytesIO()
        secret = "forbidden-raw-secret"

        def fail_without_escape(_argv):
            raise RuntimeError(secret)

        self.assertEqual(
            capture._public_enabled_main(
                ["--capture"],
                enabled_runner=fail_without_escape,
                status_stream=blocked_output,
            ),
            78,
        )
        self.assertNotIn(secret.encode("ascii"), blocked_output.getvalue())
        self.assertEqual(
            json.loads(blocked_output.getvalue()),
            {
                "schema": capture.CAPTURE_PUBLIC_STATUS_SCHEMA,
                "status": "BLOCKED_FIXED_FAILURE",
                "provider_dispatch_count_known": False,
                "automatic_retry_count": 0,
                "cleanup_count": 0,
                "raw_value_emitted_count": 0,
            },
        )

    def test_capture_concrete_module_closure_patches_authority_before_collector(self) -> None:
        capture = self.capture
        names = (
            "extract_item26_manual_cost_stop_raw_v2",
            "verify_item26_manual_cost_stop_authority_v2",
            "collect_item26_manual_cost_stop_raw_v2",
        )
        previous = {name: sys.modules.get(name) for name in names}
        for name in names:
            sys.modules.pop(name, None)
        validated = {
            "runtime_raw": {
                "extractor": (
                    b"def validate_offline_import_response(*args):\n"
                    b"    return None\n"
                ),
                "authority": (
                    b"def _verify_signature(*args):\n"
                    b"    return False\n"
                    b"def _git(*args, **kwargs):\n"
                    b"    return None\n"
                    b"def _openssl(*args, **kwargs):\n"
                    b"    return b''\n"
                    b"def _git_repository_identity(root):\n"
                    b"    return ('authority-repository', str(root))\n"
                ),
                "collector": (
                    b"import extract_item26_manual_cost_stop_raw_v2 as extractor\n"
                    b"import verify_item26_manual_cost_stop_authority_v2 as authority\n"
                    b"def begin(**kwargs): return None\n"
                    b"def finish(**kwargs): return None\n"
                    b"def mark_unknown(**kwargs): return None\n"
                    b"def finalize(**kwargs): return None\n"
                ),
            }
        }
        try:
            collector, extractor = capture._default_prepare_capture_dependencies(
                lambda: validated
            )
            authority = sys.modules[names[1]]
            self.assertIs(collector.extractor, extractor)
            self.assertIs(collector.authority, authority)
            self.assertIs(authority._item26_m1_patched, True)
            self.assertIs(authority._verify_signature, capture._fd_only_verify_signature)
            self.assertIs(authority._openssl, capture._fd_only_openssl)
            self.assertEqual(extractor.__file__, capture.EXTRACTOR_PATH)
            self.assertEqual(authority.__file__, capture.AUTHORITY_PATH)
            self.assertEqual(collector.__file__, capture.COLLECTOR_PATH)
        finally:
            for name in names:
                sys.modules.pop(name, None)
                if previous[name] is not None:
                    sys.modules[name] = previous[name]

    def test_capture_child_inventory_is_checked_before_any_runtime_read(self) -> None:
        capture = self.capture
        reads: list[str] = []
        tools: list[str] = []
        validator = capture._capture_child_runtime_validator_from_arguments(
            fake_capture_runtime_arguments()
        )
        with mock.patch.object(
            capture.os,
            "listdir",
            return_value=["capture-root-program.py"],
        ), mock.patch.object(
            capture,
            "_read_runtime_regular",
            side_effect=lambda path, _maximum: reads.append(path),
        ), mock.patch.object(
            capture,
            "_capture_system_identity_snapshot",
            side_effect=lambda: tools.append("tools"),
        ):
            with self.assertRaisesRegex(
                capture.CaptureError,
                "^capture_runtime_inventory$",
            ):
                validator()
        self.assertEqual(reads, [])
        self.assertEqual(tools, [])

    def test_capture_post_identity_is_bounded_process_free_and_exact(self) -> None:
        capture = self.capture
        arguments = fake_capture_runtime_arguments()
        capture_rows = {
            name: {"name": name}
            for name in sorted(capture.CAPTURE_RUNTIME_NAMES)
        }
        existing_rows = {
            name: {"name": name}
            for name in sorted(capture.EXISTING_RUNTIME_BINDINGS)
        }
        expected = {
            "tools": {"tools": True},
            "dynamic": {"dynamic": True},
            "repository": {"repository": True},
            "capture": capture_rows,
            "existing": existing_rows,
        }

        def listdir(path):
            if path == capture.RUNTIME_DIRECTORY:
                return list(capture.CAPTURE_RUNTIME_NAMES)
            if path == capture.EXISTING_RUNTIME_DIRECTORY:
                return list(capture.EXISTING_RUNTIME_BINDINGS)
            raise AssertionError(path)

        def read(path, _maximum):
            name = path.rsplit("/", 1)[-1]
            rows = capture_rows if path.startswith(capture.RUNTIME_DIRECTORY + "/") else existing_rows
            return b"fixed", rows[name]

        with mock.patch.object(capture.os, "listdir", side_effect=listdir), mock.patch.object(
            capture,
            "_capture_system_identity_snapshot",
            return_value=expected["tools"],
        ), mock.patch.object(
            capture,
            "_capture_runtime_identity_snapshot",
            return_value=expected["dynamic"],
        ), mock.patch.object(
            capture,
            "_repository_local_identity",
            return_value=expected["repository"],
        ), mock.patch.object(
            capture,
            "_read_runtime_regular",
            side_effect=read,
        ), mock.patch.object(
            capture,
            "_runtime_row",
            return_value=None,
        ), mock.patch.object(
            capture.subprocess,
            "Popen",
            side_effect=AssertionError("post identity spawned a process"),
        ):
            self.assertEqual(
                capture._capture_post_identity_snapshot(
                    arguments,
                    expected,
                    monotonic=lambda: 0.0,
                ),
                expected,
            )
            clock = iter((0.0, 31.0))
            with self.assertRaisesRegex(
                capture.CaptureError,
                "^post_capture_identity_timeout$",
            ):
                capture._capture_post_identity_snapshot(
                    arguments,
                    expected,
                    monotonic=lambda: next(clock),
                )
        tree = ast.parse(self.stager.CAPTURE_ROOT_PROGRAM)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_capture_post_identity_snapshot"
        )
        source = ast.get_source_segment(self.stager.CAPTURE_ROOT_PROGRAM, function)
        for forbidden in (
            "_local_only_git",
            "_capture_local_object_probe",
            "subprocess",
            "Popen",
        ):
            self.assertNotIn(forbidden, source)
        self.assertEqual(capture.FULL_CAPTURE_TIMEOUT_SECONDS, 840)
        self.assertEqual(capture.POST_CAPTURE_IDENTITY_DEADLINE_SECONDS, 30)
        self.assertEqual(capture.POST_CAPTURE_MAX_FILE_READ_COUNT, 18)
        self.assertLess(
            capture.FULL_CAPTURE_TIMEOUT_SECONDS
            + capture.POST_CAPTURE_IDENTITY_DEADLINE_SECONDS,
            self.stager.CAPTURE_SUPERVISOR_RUNTIME_TIMEOUT_SECONDS,
        )

    def test_capture_repository_is_fixed_local_and_git_child_drops_privilege(self) -> None:
        capture = self.capture
        counter = iter(range(100, 10000))

        def row(mode, *, size=0):
            value = next(counter)
            return types.SimpleNamespace(
                st_dev=1,
                st_ino=value,
                st_size=size,
                st_mode=mode,
                st_uid=capture.REPOSITORY_OWNER_UID,
                st_gid=capture.REPOSITORY_OWNER_GID,
                st_nlink=1,
                st_mtime_ns=10,
                st_ctime_ns=11,
            )

        def lstat(path):
            if path.endswith((
                "/.git/objects/info/alternates",
                "/.git/objects/info/http-alternates",
                "/.git/shallow",
                "/.git/commondir",
                "/.git/worktrees",
            )):
                raise FileNotFoundError(path)
            if path.endswith("/.git/config"):
                return row(stat.S_IFREG | 0o644, size=16)
            if path.endswith(".pack") or path.endswith(".idx"):
                return row(stat.S_IFREG | 0o644, size=32)
            return row(stat.S_IFDIR | 0o755)

        clean_config = b"[core]\n\tbare = false\n"
        with mock.patch.object(capture.os, "lstat", side_effect=lstat), mock.patch.object(
            capture.os,
            "listdir",
            return_value=["pack-a.pack", "pack-a.idx"],
        ), mock.patch.object(
            capture,
            "_read_runtime_regular",
            return_value=(clean_config, {}),
        ):
            identity = capture._repository_local_identity()
        self.assertEqual(identity["repository_uid"], 501)
        self.assertEqual(identity["repository_gid"], 20)
        self.assertEqual([row[0] for row in identity["pack_rows"]], [
            "pack-a.idx",
            "pack-a.pack",
        ])

        for names, config in (
            (["pack-a.promisor"], clean_config),
            ([], b"[include]\npath = /forbidden\n"),
            ([f"pack-{index}.idx" for index in range(4097)], clean_config),
        ):
            with self.subTest(names=len(names), config=config[:12]):
                with mock.patch.object(capture.os, "lstat", side_effect=lstat), mock.patch.object(
                    capture.os,
                    "listdir",
                    return_value=names,
                ), mock.patch.object(
                    capture,
                    "_read_runtime_regular",
                    return_value=(config, {}),
                ):
                    with self.assertRaisesRegex(
                        capture.CaptureError,
                        "^capture_repository_nonlocal$",
                    ):
                        capture._repository_local_identity()

        calls: list[object] = []
        with mock.patch.object(
            capture.resource,
            "setrlimit",
            side_effect=lambda *args: calls.append(("setrlimit", args)),
        ), mock.patch.object(
            capture.resource,
            "getrlimit",
            return_value=(0, 0),
        ), mock.patch.object(
            capture.os,
            "setgroups",
            side_effect=lambda groups: calls.append(("setgroups", groups)),
        ), mock.patch.object(
            capture.os,
            "setgid",
            side_effect=lambda gid: calls.append(("setgid", gid)),
        ), mock.patch.object(
            capture.os,
            "setuid",
            side_effect=lambda uid: calls.append(("setuid", uid)),
        ), mock.patch.object(capture.os, "umask", return_value=0o022), mock.patch.object(
            capture.os,
            "geteuid",
            return_value=501,
        ), mock.patch.object(capture.os, "getegid", return_value=20), mock.patch.object(
            capture.os,
            "getgroups",
            return_value=[],
        ):
            capture._git_preexec(501, 20)
        self.assertIn(("setgroups", []), calls)
        self.assertIn(("setgid", 20), calls)
        self.assertIn(("setuid", 501), calls)
        with mock.patch.object(capture.os, "_exit", side_effect=SystemExit(78)):
            with self.assertRaises(SystemExit):
                capture._git_preexec(0, 0)

    def test_capture_default_entrypoints_reach_concrete_orchestrator_and_adapter(self) -> None:
        capture = self.capture
        runtime_arguments = fake_capture_runtime_arguments()
        old_identifier = "fake-default-old"
        source_identifier = "fake-default-source"
        order: list[str] = []

        def identity_hash(value):
            return {
                old_identifier: capture.EXPECTED_OLD_CLONE_SHA256,
                source_identifier: capture.EXPECTED_SOURCE_SHA256,
            }.get(value, hashlib.sha256(value.encode("utf-8")).hexdigest())

        class Collector:
            def __init__(self):
                self.sequence = 0

            def begin(self, **kwargs):
                self.sequence += 1
                order.append("begin:" + kwargs["slot"])
                return collector_status(
                    capture,
                    "REQUEST_FROZEN",
                    slot=kwargs["slot"],
                    digest_key="request_sha256",
                    digest=hashlib.sha256(kwargs["request_raw"]).hexdigest(),
                    sequence=self.sequence,
                )

            def finish(self, **kwargs):
                order.append("finish:" + kwargs["slot"])
                return collector_status(
                    capture,
                    "RESPONSE_RECORDED",
                    slot=kwargs["slot"],
                    digest_key="response_sha256",
                    digest=hashlib.sha256(kwargs["response_raw"]).hexdigest(),
                    sequence=self.sequence,
                )

            def mark_unknown(self, **_kwargs):
                raise AssertionError("default path marked unknown")

            def finalize(self, **_kwargs):
                order.append("finalize")
                return {
                    "schema": "noteai.item26.manual-cost-stop-collector-status.v2",
                    "status": "CAPTURE_INSTALLED",
                    "provider_raw_file_sha256": "a" * 64,
                    "actiontrail_raw_file_sha256": "b" * 64,
                    "cloud_call_count": 0,
                    "raw_value_emitted_count": 0,
                }

        collector = Collector()
        extractor = types.SimpleNamespace(
            validate_offline_import_response=lambda *_args: None
        )
        identities = {
            "tools": {},
            "dynamic": {},
            "repository": {},
            "capture": {},
            "existing": {},
        }
        validated = {
            "manifest": {"fixed": True},
            "runtime_raw": {},
            "identities": identities,
        }

        def validator_factory(arguments):
            self.assertEqual(tuple(arguments), runtime_arguments)

            def validate():
                order.append("runtime")
                return validated

            return validate

        def prepare(validator):
            self.assertIs(validator(), validated)
            order.append("dependencies")
            return collector, extractor

        def child(request_raw, credential, **kwargs):
            self.assertEqual(kwargs["runtime_arguments"], runtime_arguments)
            request = json.loads(request_raw)
            if request["Action"] == "LookupEvents":
                if request["LookupAttribute"][0]["Key"] == "ServiceName":
                    parameters = {"DBInstanceId": old_identifier}
                else:
                    parameters = {"SourceDBInstanceId": source_identifier}
                response = {"Events": [{"requestParameters": parameters}]}
            else:
                response = {"RequestId": "fake-default"}
            credential[:] = b"\0" * len(credential)
            return {
                "response_raw": capture.canonical(response),
                "status_raw": child_success_raw(capture),
                "cloud_dispatch_count": 1,
                "group_absent": True,
                "child_spawned": True,
            }

        original_run = capture._run_capture_once

        def run_capture(**kwargs):
            return original_run(value_sha256=identity_hash, **kwargs)

        def post(arguments, expected):
            self.assertEqual(tuple(arguments), runtime_arguments)
            self.assertIs(expected, identities)
            order.append("post")
            return expected

        output = io.BytesIO()
        with mock.patch.object(
            capture,
            "_capture_runtime_validator_from_arguments",
            side_effect=validator_factory,
        ), mock.patch.object(
            capture,
            "_default_prepare_capture_dependencies",
            side_effect=prepare,
        ), mock.patch.object(
            capture,
            "_root_custody_temporary_sts_probe",
            side_effect=lambda: (order.append("credential_probe"), initial_credential_probe())[1],
        ), mock.patch.object(
            capture,
            "_root_custody_temporary_sts_supplier",
            side_effect=dispatch_credential,
        ), mock.patch.object(
            capture,
            "_spawn_feed_drain_once",
            side_effect=child,
        ), mock.patch.object(
            capture,
            "_run_capture_once",
            side_effect=run_capture,
        ), mock.patch.object(
            capture,
            "_capture_post_identity_snapshot",
            side_effect=post,
        ):
            self.assertEqual(
                capture._enabled_main(
                    ["--capture", *runtime_arguments],
                    status_stream=output,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "FIVE_STREAM_CAPTURE_FINALIZED")
        self.assertEqual(result["provider_dispatch_count"], 5)
        self.assertEqual(order[:3], ["runtime", "dependencies", "credential_probe"])
        self.assertEqual(order[-2:], ["finalize", "post"])

        pairs = [
            capture.socket.socketpair(capture.socket.AF_UNIX, capture.socket.SOCK_STREAM)
            for _ in range(4)
        ]
        child_fds = tuple(pair[1].fileno() for pair in pairs)
        adapter_order: list[str] = []

        def child_validator_factory(arguments):
            self.assertEqual(tuple(arguments), runtime_arguments)

            def validate():
                adapter_order.append("runtime")
                return {"runtime_raw": {"adapter": b"fixed"}}

            return validate

        def load_adapter(validated_value):
            self.assertEqual(validated_value["runtime_raw"]["adapter"], b"fixed")
            adapter_order.append("loader")

            def dispatch(_request_fd, _credential_fd, _response_fd):
                adapter_order.append("dispatch")
                return {
                    "request_fd_read_count": 1,
                    "credential_fd_read_count": 1,
                    "response_fd_write_count": 1,
                    "cloud_dispatch_count": 1,
                    "cloud_write_count": 0,
                    "automatic_retry_count": 0,
                }

            return types.SimpleNamespace(dispatch_authorized_fds=dispatch)

        try:
            with mock.patch.object(
                capture,
                "_capture_child_runtime_validator_from_arguments",
                side_effect=child_validator_factory,
            ), mock.patch.object(
                capture,
                "_load_adapter_from_validation",
                side_effect=load_adapter,
            ):
                self.assertEqual(
                    capture._adapter_child_main(
                        [
                            "--adapter-child",
                            *(str(fd) for fd in child_fds),
                            *runtime_arguments,
                        ],
                        preflight=lambda: True,
                    ),
                    0,
                )
            self.assertEqual(adapter_order, ["runtime", "loader", "dispatch"])
            self.assertEqual(
                json.loads(pairs[3][0].recv(capture.MAX_STATUS_BYTES)),
                {
                    "schema": capture.CHILD_STATUS_SCHEMA,
                    "status": "ONE_READ_DISPATCH_COMPLETED",
                    "cloud_dispatch_count": 1,
                    "cloud_write_count": 0,
                    "automatic_retry_count": 0,
                    "raw_value_emitted_count": 0,
                },
            )
        finally:
            for pair in pairs:
                for channel in pair:
                    channel.close()

    def test_capture_default_chain_composes_with_only_leaf_boundaries_faked(self) -> None:
        capture = self.capture
        module_names = (
            "extract_item26_manual_cost_stop_raw_v2",
            "verify_item26_manual_cost_stop_authority_v2",
            "collect_item26_manual_cost_stop_raw_v2",
            "item26_aliyun_official_read_v2",
        )
        previous_modules = {
            name: sys.modules.get(name) for name in module_names
        }
        for name in module_names:
            sys.modules.pop(name, None)
        extractor_raw = (
            b"def validate_offline_import_response(*args):\n"
            b"    return None\n"
        )
        authority_raw = (
            b"def _verify_signature(*args): return False\n"
            b"def _git(*args, **kwargs): return None\n"
            b"def _openssl(*args, **kwargs): return b''\n"
            b"def _git_repository_identity(root): return ('authority', str(root))\n"
        )
        collector_raw = (
            b"import hashlib\n"
            b"import extract_item26_manual_cost_stop_raw_v2 as extractor\n"
            b"import verify_item26_manual_cost_stop_authority_v2 as authority\n"
            b"sequence = 0\n"
            b"source_hash_calls = 0\n"
            b"def _source_hashes(owner_uid=None):\n"
            b"    global source_hash_calls\n"
            b"    if owner_uid != 0: raise RuntimeError('owner')\n"
            b"    source_hash_calls += 1\n"
            b"    return {'collector_source_sha256':'a'*64,'extractor_source_sha256':'b'*64,'authority_source_sha256':'c'*64}\n"
            b"def begin(*, control_revision, slot, request_raw):\n"
            b"    global sequence\n"
            b"    _source_hashes(0)\n"
            b"    sequence += 1\n"
            b"    return {'schema':'noteai.item26.manual-cost-stop-collector-status.v2','status':'REQUEST_FROZEN','slot':slot,'sequence':sequence,'request_sha256':hashlib.sha256(request_raw).hexdigest(),'cloud_call_count':0,'raw_value_emitted_count':0}\n"
            b"def finish(*, control_revision, slot, response_raw):\n"
            b"    return {'schema':'noteai.item26.manual-cost-stop-collector-status.v2','status':'RESPONSE_RECORDED','slot':slot,'sequence':sequence,'response_sha256':hashlib.sha256(response_raw).hexdigest(),'cloud_call_count':0,'raw_value_emitted_count':0}\n"
            b"def mark_unknown(**kwargs): raise RuntimeError('unexpected')\n"
            b"def finalize(*, control_revision):\n"
            b"    return {'schema':'noteai.item26.manual-cost-stop-collector-status.v2','status':'CAPTURE_INSTALLED','provider_raw_file_sha256':'d'*64,'actiontrail_raw_file_sha256':'e'*64,'cloud_call_count':0,'raw_value_emitted_count':0}\n"
        )
        adapter_raw = (
            b"import os\n"
            b"def dispatch_authorized_fds(request_fd, credential_fd, response_fd):\n"
            b"    os.write(response_fd, b'{\"fixed\":true}\\n')\n"
            b"    return {'request_fd_read_count':1,'credential_fd_read_count':1,'response_fd_write_count':1,'cloud_dispatch_count':1,'cloud_write_count':0,'automatic_retry_count':0}\n"
        )
        activation_raw = b"fixed-activation\n"
        program_raw = b"fixed-capture-program\n"
        accepted_revision = "d" * 40
        adapter_acceptance = "a" * 40
        adapter_source = "b" * 40
        existing_raw = {
            "collect_item26_manual_cost_stop_raw_v2.py": collector_raw,
            "extract_item26_manual_cost_stop_raw_v2.py": extractor_raw,
            "verify_item26_manual_cost_stop_authority_v2.py": authority_raw,
            "runtime-activation-receipt-v3.json": activation_raw,
        }
        existing_bindings = {
            name: (len(raw), hashlib.sha256(raw).hexdigest(), 0o600)
            for name, raw in existing_raw.items()
        }
        ref_raw = {
            "tools/item26_aliyun_official_read_v2.py": adapter_raw,
            "tools/collect_item26_manual_cost_stop_raw_v2.py": collector_raw,
            "tools/extract_item26_manual_cost_stop_raw_v2.py": extractor_raw,
            "tools/verify_item26_manual_cost_stop_authority_v2.py": authority_raw,
        }
        local_bindings = {}
        oid_to_raw = {}
        for index, (ref, raw) in enumerate(ref_raw.items(), start=1):
            oid = hashlib.sha1(
                b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
            ).hexdigest()
            oid_to_raw[oid] = raw
            local_bindings[ref] = {
                "accepted_revision": format(index + 5, "x") * 40,
                "source_revision": format(index + 9, "x") * 40,
                "blob_oid": oid,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        manifest = {
            "schema": capture.RUNTIME_MANIFEST_SCHEMA,
            "manifest_name": "capture-runtime-manifest.json",
            "manifest_mode": "0600",
            "payloads": {
                "capture-root-program.py": {
                    "name": "capture-root-program.py",
                    "byte_count": len(program_raw),
                    "sha256": hashlib.sha256(program_raw).hexdigest(),
                    "mode": "0500",
                    "source_revision": accepted_revision,
                    "source_ref": "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py:CAPTURE_ROOT_PROGRAM",
                },
                "item26_aliyun_official_read_v2.py": {
                    "name": "item26_aliyun_official_read_v2.py",
                    "byte_count": len(adapter_raw),
                    "sha256": hashlib.sha256(adapter_raw).hexdigest(),
                    "mode": "0500",
                    "source_revision": adapter_acceptance,
                    "source_ref": "tools/item26_aliyun_official_read_v2.py",
                },
            },
        }
        manifest_raw = capture.canonical(manifest)
        runtime_arguments = (
            accepted_revision,
            str(len(program_raw)),
            hashlib.sha256(program_raw).hexdigest(),
            str(len(manifest_raw)),
            hashlib.sha256(manifest_raw).hexdigest(),
        )
        runtime_raw = {
            capture.CAPTURE_PROGRAM_PATH: (program_raw, 0o500),
            capture.ADAPTER_PATH: (adapter_raw, 0o500),
            capture.CAPTURE_MANIFEST_PATH: (manifest_raw, 0o600),
            **{
                capture.EXISTING_RUNTIME_DIRECTORY + "/" + name: (raw, 0o600)
                for name, raw in existing_raw.items()
            },
        }
        rows = {}
        for index, (path, (raw, mode)) in enumerate(runtime_raw.items(), start=1):
            rows[path] = {
                "regular": True,
                "symlink": False,
                "uid": 0,
                "gid": 0,
                "nlink": 1,
                "mode": mode,
                "size": len(raw),
                "dev": 7,
                "ino": index,
                "mtime_ns": 10,
                "ctime_ns": 11,
            }
        tools_identity = {"fixed-tools": True}
        dynamic_identity = {
            capture.CAPTURE_PROGRAM_PATH: rows[capture.CAPTURE_PROGRAM_PATH],
            capture.CAPTURE_MANIFEST_PATH: rows[capture.CAPTURE_MANIFEST_PATH],
        }
        repository_identity = {
            "fixed-repository": True,
            "repository_uid": 501,
            "repository_gid": 20,
        }

        def listdir(path):
            if path == capture.RUNTIME_DIRECTORY:
                return list(capture.CAPTURE_RUNTIME_NAMES)
            if path == capture.EXISTING_RUNTIME_DIRECTORY:
                return list(existing_bindings)
            raise AssertionError(path)

        def read_runtime(path, maximum):
            raw, _mode = runtime_raw[path]
            self.assertGreaterEqual(maximum, len(raw))
            return raw, dict(rows[path])

        def local_git(arguments, *, root, stdout=subprocess.PIPE, **_kwargs):
            self.assertEqual(str(root), capture.REPOSITORY_ROOT)
            if arguments[0] == "rev-parse":
                revision_ref = arguments[-1]
                ref = revision_ref.split(":", 1)[1]
                oid = local_bindings[ref]["blob_oid"]
                raw = (oid + "\n").encode("ascii")
            elif arguments[:2] == ["cat-file", "blob"]:
                raw = oid_to_raw[arguments[2]]
            else:
                raise AssertionError(arguments)
            return subprocess.CompletedProcess(arguments, 0, raw, None)

        old_identifier = "leaf-old"
        source_identifier = "leaf-source"

        def value_sha(value):
            return {
                old_identifier: capture.EXPECTED_OLD_CLONE_SHA256,
                source_identifier: capture.EXPECTED_SOURCE_SHA256,
            }.get(value, hashlib.sha256(value.encode()).hexdigest())

        def provider_leaf(request_raw, credential, **kwargs):
            self.assertEqual(kwargs["runtime_arguments"], runtime_arguments)
            request = json.loads(request_raw)
            if request["Action"] == "LookupEvents":
                if request["LookupAttribute"][0]["Key"] == "ServiceName":
                    parameters = {"DBInstanceId": old_identifier}
                else:
                    parameters = {"SourceDBInstanceId": source_identifier}
                response = {"Events": [{"requestParameters": parameters}]}
            else:
                response = {"RequestId": "leaf"}
            credential[:] = b"\0" * len(credential)
            return {
                "response_raw": capture.canonical(response),
                "status_raw": child_success_raw(capture),
                "cloud_dispatch_count": 1,
                "group_absent": True,
                "child_spawned": True,
            }

        original_value_sha = capture._run_capture_once.__kwdefaults__["value_sha256"]
        capture._run_capture_once.__kwdefaults__["value_sha256"] = value_sha
        output = io.BytesIO()
        patches = (
            mock.patch.object(capture, "ADAPTER_BYTES", len(adapter_raw)),
            mock.patch.object(capture, "ADAPTER_SHA256", hashlib.sha256(adapter_raw).hexdigest()),
            mock.patch.object(capture, "ADAPTER_ACCEPTANCE_REVISION", adapter_acceptance),
            mock.patch.object(capture, "ADAPTER_SOURCE_REVISION", adapter_source),
            mock.patch.object(capture, "EXISTING_RUNTIME_BINDINGS", existing_bindings),
            mock.patch.object(capture, "LOCAL_OBJECT_BINDINGS", local_bindings),
            mock.patch.object(capture.os, "listdir", side_effect=listdir),
            mock.patch.object(capture, "_read_runtime_regular", side_effect=read_runtime),
            mock.patch.object(capture, "_capture_system_identity_snapshot", return_value=tools_identity),
            mock.patch.object(capture, "_capture_runtime_identity_snapshot", return_value=dynamic_identity),
            mock.patch.object(capture, "_repository_local_identity", return_value=repository_identity),
            mock.patch.object(capture, "_local_only_git", side_effect=local_git),
            mock.patch.object(capture, "_root_custody_temporary_sts_probe", side_effect=initial_credential_probe),
            mock.patch.object(capture, "_root_custody_temporary_sts_supplier", side_effect=dispatch_credential),
            mock.patch.object(capture, "_spawn_feed_drain_once", side_effect=provider_leaf),
        )
        try:
            for patcher in patches:
                patcher.start()
            self.assertEqual(
                capture._enabled_main(
                    ["--capture", *runtime_arguments],
                    status_stream=output,
                ),
                0,
            )
            result = json.loads(output.getvalue())
            self.assertEqual(result["provider_dispatch_count"], 5)
            self.assertEqual(
                sys.modules["collect_item26_manual_cost_stop_raw_v2"].source_hash_calls,
                5,
            )

            pairs = [
                capture.socket.socketpair(capture.socket.AF_UNIX, capture.socket.SOCK_STREAM)
                for _ in range(4)
            ]
            try:
                self.assertEqual(
                    capture._adapter_child_main(
                        [
                            "--adapter-child",
                            *(str(pair[1].fileno()) for pair in pairs),
                            *runtime_arguments,
                        ],
                        preflight=lambda: True,
                    ),
                    0,
                )
                self.assertEqual(
                    pairs[2][0].recv(1024),
                    b'{"fixed":true}\n',
                )
                self.assertEqual(
                    json.loads(pairs[3][0].recv(capture.MAX_STATUS_BYTES))["status"],
                    "ONE_READ_DISPATCH_COMPLETED",
                )
            finally:
                for pair in pairs:
                    for channel in pair:
                        channel.close()
        finally:
            capture._run_capture_once.__kwdefaults__["value_sha256"] = original_value_sha
            for patcher in reversed(patches):
                patcher.stop()
            for name in module_names:
                sys.modules.pop(name, None)
                if previous_modules[name] is not None:
                    sys.modules[name] = previous_modules[name]

    def test_materialize_runtime_manifest_inventory_and_local_objects_are_exact(self) -> None:
        materialize = self.materialize
        program_raw = b"fixed-materialize-program\n"
        program_sha256 = hashlib.sha256(program_raw).hexdigest()
        accepted_revision = "f" * 40
        stager_raw = program_raw + b"fixed-outer-stager\n"
        stager_sha256 = hashlib.sha256(stager_raw).hexdigest()
        stager_oid = "a" * 40
        fixed_raw = {
            name: ("fixed-" + name + "\n").encode("ascii")
            for name in materialize.FIXED_RUNTIME_BINDINGS
        }
        fixed_bindings = {}
        local_bindings = {}
        for index, (name, raw) in enumerate(sorted(fixed_raw.items()), 1):
            source_ref = "tools/fixed-" + name
            digest = hashlib.sha256(raw).hexdigest()
            fixed_bindings[name] = (len(raw), digest, 0o500, source_ref)
            local_bindings[source_ref] = (
                format(index, "x") * 40,
                len(raw),
                digest,
            )
        authority_raw = b"fixed-authority-root\n"
        provider_raw = b'{"provider":true}\n'
        trail_raw = b'{"trail":true}\n'
        authority_binding = (
            len(authority_raw),
            hashlib.sha256(authority_raw).hexdigest(),
            0o600,
        )
        capture_bindings = {
            "authority-root-v2.json": authority_binding,
            "provider-raw-v2.json": (
                len(provider_raw),
                hashlib.sha256(provider_raw).hexdigest(),
                0o600,
            ),
            "actiontrail-raw-v2.json": (
                len(trail_raw),
                hashlib.sha256(trail_raw).hexdigest(),
                0o600,
            ),
        }
        with (
            mock.patch.object(
                materialize,
                "FIXED_RUNTIME_BINDINGS",
                fixed_bindings,
            ),
            mock.patch.object(
                materialize,
                "LOCAL_OBJECT_BINDINGS",
                local_bindings,
            ),
            mock.patch.object(
                materialize,
                "AUTHORITY_ROOT_BINDING",
                authority_binding,
            ),
        ):
            manifest_raw = materialize.canonical(
                materialize._expected_manifest(
                    len(program_raw),
                    program_sha256,
                    accepted_revision,
                )
            )
            material = {
                materialize.RUNTIME_DIRECTORY
                + "/materialize-root-program.py": program_raw,
                materialize.RUNTIME_DIRECTORY
                + "/materialize-runtime-manifest.json": manifest_raw,
                materialize.AUTHORITY_DIRECTORY
                + "/authority-root-v2.json": authority_raw,
                materialize.AUTHORITY_DIRECTORY
                + "/provider-raw-v2.json": provider_raw,
                materialize.AUTHORITY_DIRECTORY
                + "/actiontrail-raw-v2.json": trail_raw,
            }
            material.update(
                {
                    materialize.RUNTIME_DIRECTORY + "/" + name: raw
                    for name, raw in fixed_raw.items()
                }
            )

            def read_file(path, maximum):
                raw = material[path]
                self.assertLessEqual(len(raw), maximum)
                return raw

            def list_names(path):
                if path == materialize.RUNTIME_DIRECTORY:
                    return list(materialize.RUNTIME_NAMES)
                if path == materialize.AUTHORITY_DIRECTORY:
                    return list(materialize.CAPTURE_NAMES)
                raise AssertionError(path)

            def lstater(path):
                if path in (
                    materialize.RUNTIME_DIRECTORY,
                    materialize.AUTHORITY_DIRECTORY,
                ):
                    return types.SimpleNamespace(
                        st_mode=stat.S_IFDIR | 0o700,
                        st_uid=0,
                        st_gid=0,
                        st_nlink=2,
                        st_dev=1,
                        st_ino=1 if path == materialize.RUNTIME_DIRECTORY else 2,
                    )
                raw = material[path]
                if path.endswith("materialize-root-program.py"):
                    mode = 0o500
                elif path.endswith("materialize-runtime-manifest.json"):
                    mode = 0o600
                elif path.startswith(materialize.AUTHORITY_DIRECTORY + "/"):
                    mode = 0o600
                else:
                    mode = 0o500
                return types.SimpleNamespace(
                    st_mode=stat.S_IFREG | mode,
                    st_uid=0,
                    st_gid=0,
                    st_nlink=1,
                    st_dev=3,
                    st_ino=abs(hash(path)),
                    st_size=len(raw),
                )

            object_calls: list[tuple[object, ...]] = []

            def object_probe(revision, source_ref, oid, size, digest):
                object_calls.append((revision, source_ref, oid, size, digest))
                value = {
                    "present": True,
                    "git_blob_oid": oid,
                    "byte_count": size,
                    "sha256": digest,
                    "promisor_remote_count": 0,
                    "partial_clone_config_count": 0,
                }
                if source_ref == materialize.STAGER_REF:
                    value.update(
                        {
                            "embedded_literal_name": "MATERIALIZE_ROOT_PROGRAM",
                            "embedded_literal_byte_count": len(program_raw),
                            "embedded_literal_sha256": program_sha256,
                        }
                    )
                return value

            tool_calls: list[str] = []

            result = materialize._validate_runtime_capture_and_local_objects(
                program_size=len(program_raw),
                program_sha256=program_sha256,
                accepted_source_revision=accepted_revision,
                stager_size=len(stager_raw),
                stager_sha256=stager_sha256,
                stager_blob_oid=stager_oid,
                manifest_size=len(manifest_raw),
                manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                capture_bindings=capture_bindings,
                list_names=list_names,
                lstater=lstater,
                read_file=read_file,
                object_probe=object_probe,
                tool_probe=lambda path, _expected: (
                    tool_calls.append(path) is None
                ),
                preserved_snapshot=lambda **_kwargs: {"preserved": (1, 2)},
                parent_probe=lambda _path, **_kwargs: (("fixed-parent",),),
            )
            self.assertEqual(set(result["runtime_raw"]), materialize.RUNTIME_NAMES)
            self.assertEqual(set(result["capture_sha256"]), materialize.CAPTURE_NAMES)
            self.assertEqual(len(object_calls), len(fixed_bindings) + 1)
            self.assertEqual(tool_calls, sorted(materialize.SYSTEM_TOOL_BINDINGS))
            self.assertEqual(
                json.loads(manifest_raw)["payloads"][
                    "materialize-root-program.py"
                ]["source_revision"],
                accepted_revision,
            )

            def nonlocal_probe(revision, source_ref, oid, size, digest):
                value = object_probe(revision, source_ref, oid, size, digest)
                value["promisor_remote_count"] = 1
                return value

            with self.assertRaisesRegex(
                materialize.MaterializeError,
                "^materialize_local_object$",
            ):
                materialize._validate_runtime_capture_and_local_objects(
                    program_size=len(program_raw),
                    program_sha256=program_sha256,
                    accepted_source_revision=accepted_revision,
                    stager_size=len(stager_raw),
                    stager_sha256=stager_sha256,
                    stager_blob_oid=stager_oid,
                    manifest_size=len(manifest_raw),
                    manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                    capture_bindings=capture_bindings,
                    list_names=list_names,
                    lstater=lstater,
                    read_file=read_file,
                    object_probe=nonlocal_probe,
                    tool_probe=lambda _path, _expected: True,
                    preserved_snapshot=lambda **_kwargs: {
                        "preserved": (1, 2)
                    },
                    parent_probe=lambda _path, **_kwargs: (
                        ("fixed-parent",),
                    ),
                )

    def test_materialize_guards_precede_exact_module_load_and_authority_patch(self) -> None:
        materialize = self.materialize
        events: list[str] = []
        runtime_raw = {
            name: ("source-" + name).encode("ascii")
            for name in materialize.RUNTIME_NAMES
            if name != "materialize-runtime-manifest.json"
        }
        validated = {
            "runtime_raw": runtime_raw,
            "identities": {"fixed": 1},
            "capture_sha256": {"fixed": "a" * 64},
            "manifest_sha256": "b" * 64,
        }
        modules: dict[str, types.SimpleNamespace] = {}

        def loader(name, _path, raw):
            events.append("load:" + name)
            self.assertEqual(raw, runtime_raw[name + ".py"])
            module = types.SimpleNamespace()
            if name == "verify_item26_manual_cost_stop_authority_v2":
                module._verify_signature = lambda *_args: False
                module._git = lambda *_args, **_kwargs: None
            modules[name] = module
            return module

        def patcher(authority):
            events.append("patch:authority")
            self.assertIs(
                authority,
                modules["verify_item26_manual_cost_stop_authority_v2"],
            )

        def patcher_with_fd(authority, *, null_fd):
            self.assertEqual(null_fd, 77)
            patcher(authority)

        result = materialize._prepare_materialize_dependencies(
            lambda: (events.append("validate:runtime") or validated),
            null_fd=77,
            guard_installer=lambda: events.append("install:guards"),
            loader=loader,
            patcher=patcher_with_fd,
        )
        self.assertIs(result[0], validated)
        self.assertEqual(
            events,
            [
                "validate:runtime",
                "install:guards",
                "load:extract_item26_manual_cost_stop_raw_v2",
                "load:verify_item26_manual_cost_stop_authority_v2",
                "patch:authority",
                "load:verify_item26_manual_cost_stop_evidence_v2",
                "load:build_item26_manual_cost_stop_evidence_v2",
            ],
        )
        authority = types.SimpleNamespace(
            _verify_signature=lambda *_args: False,
            _git=lambda *_args, **_kwargs: None,
            _openssl=lambda *_args, **_kwargs: None,
            _git_repository_identity=lambda _root: ("repository",),
        )
        signature = lambda *_args, **_kwargs: True
        local_git = lambda *_args, **_kwargs: None
        local_openssl = lambda *_args, **_kwargs: b"fixed"
        materialize._install_authority_patches(
            authority,
            null_fd=77,
            signature_verifier=signature,
            git_runner=local_git,
            openssl_runner=local_openssl,
        )
        self.assertTrue(callable(authority._verify_signature))
        self.assertTrue(callable(authority._git))
        self.assertTrue(callable(authority._openssl))

    def test_materialize_dynamic_guard_denies_all_socket_and_nonexact_processes(self) -> None:
        materialize = self.materialize
        installed: list[object] = []
        guard = materialize._install_dynamic_guards(
            add_hook=lambda value: installed.append(value)
        )
        self.assertEqual(installed, [guard])
        for event in (
            "socket.__new__",
            "socket.connect",
            "socket.getaddrinfo",
            "os.fork",
            "os.exec",
        ):
            with self.subTest(event=event):
                with self.assertRaisesRegex(
                    materialize.MaterializeError,
                    "^materialize_dynamic_guard$",
                ):
                    guard(event, ())
        for event in (
            "os.remove",
            "os.rename",
            "os.mkdir",
            "os.rmdir",
            "os.chmod",
            "os.chown",
            "os.truncate",
            "os.link",
            "os.symlink",
            "os.utime",
            "os.setxattr",
        ):
            with self.subTest(mutation_event=event):
                with self.assertRaisesRegex(
                    materialize.MaterializeError,
                    "^materialize_dynamic_guard$",
                ):
                    guard(event, ("fixed",))
        guard("open", ("/fixed/read-only", "r", os.O_RDONLY))
        with self.assertRaises(materialize.MaterializeError):
            guard("open", ("/fixed/write", "w", os.O_WRONLY | os.O_CREAT))
        git_arguments = [
            "/usr/bin/git",
            "-c",
            "safe.directory=" + materialize.REPOSITORY_ROOT,
            "--no-replace-objects",
            "show",
            materialize.CONTROL_REVISION + ":tools/fixed.py",
        ]
        guard(
            "subprocess.Popen",
            (
                "/usr/bin/git",
                git_arguments,
                materialize.REPOSITORY_ROOT,
                dict(materialize.GIT_ENV),
            ),
        )
        openssl_arguments = [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-verify",
            "/dev/fd/7",
            "-signature",
            "/dev/fd/8",
            "/dev/fd/9",
        ]
        guard(
            "subprocess.Popen",
            (
                "/usr/bin/openssl",
                openssl_arguments,
                materialize.RUNTIME_DIRECTORY,
                dict(materialize.CHILD_ENV),
            ),
        )
        for arguments in (
            ["/usr/bin/openssl", "pkey", "-pubin", "-pubout"],
            [
                "/usr/bin/openssl",
                "pkey",
                "-pubin",
                "-inform",
                "PEM",
                "-outform",
                "DER",
            ],
        ):
            guard(
                "subprocess.Popen",
                (
                    "/usr/bin/openssl",
                    arguments,
                    materialize.RUNTIME_DIRECTORY,
                    dict(materialize.CHILD_ENV),
                ),
            )
        with self.assertRaises(materialize.MaterializeError):
            guard(
                "subprocess.Popen",
                ("/bin/sh", ["/bin/sh", "-c", "true"], None, {}),
            )

    def test_materialize_finalized_capture_uses_only_exact_context(self) -> None:
        materialize = self.materialize
        calls: list[dict[str, object]] = []
        authority = types.SimpleNamespace(
            CAPTURE_INVENTORY=materialize.CAPTURE_ORDER,
            load_verified_projection=lambda **kwargs: (
                calls.append(kwargs)
                or (
                    object(),
                    {
                        "control_revision": materialize.CONTROL_REVISION,
                        "authority_root_file_sha256": (
                            materialize.AUTHORITY_ROOT_BINDING[1]
                        ),
                        "authorizes_new_action": False,
                    },
                )
            ),
        )
        _projection, binding = materialize._verify_finalized_capture(authority)
        self.assertIs(binding["authorizes_new_action"], False)
        self.assertEqual(
            calls,
            [
                {
                    "expected_control_revision": materialize.CONTROL_REVISION,
                    "expected_authority_root_file_sha256": (
                        materialize.AUTHORITY_ROOT_BINDING[1]
                    ),
                    "root": Path(materialize.REPOSITORY_ROOT),
                    "authority_directory": Path(
                        materialize.AUTHORITY_DIRECTORY
                    ),
                    "runtime_directory": Path(
                        materialize.EXISTING_RUNTIME_DIRECTORY
                    ),
                }
            ],
        )
        authority.CAPTURE_INVENTORY = tuple(reversed(materialize.CAPTURE_ORDER))
        with self.assertRaisesRegex(
            materialize.MaterializeError,
            "^materialize_capture_inventory$",
        ):
            materialize._verify_finalized_capture(authority)

    def test_materialize_real_build_helper_has_root_validation_counts_three_two(self) -> None:
        materialize = self.materialize
        calls: list[str] = []
        receipt = {"schema": materialize.RECEIPT_SCHEMA, "value": 1}
        evidence = {"schema": materialize.EVIDENCE_SCHEMA, "value": 2}

        class Verifier:
            def validate_receipt(self, value, **kwargs):
                self_outer.assertIs(value, receipt)
                self_outer.assertEqual(
                    kwargs,
                    {"expected_control_revision": materialize.CONTROL_REVISION},
                )
                calls.append("validate_receipt")
                return [], "accepted"

            def validate_evidence(self, value, bound_receipt, receipt_raw, **kwargs):
                self_outer.assertIs(value, evidence)
                self_outer.assertIs(bound_receipt, receipt)
                self_outer.assertEqual(receipt_raw, materialize.canonical(receipt))
                self_outer.assertEqual(
                    kwargs,
                    {"expected_control_revision": materialize.CONTROL_REVISION},
                )
                calls.append("validate_evidence")
                return []

        verifier = Verifier()

        class Builder:
            def build_receipt(self, **kwargs):
                self_outer.assertEqual(
                    kwargs,
                    {
                        "expected_control_revision": materialize.CONTROL_REVISION,
                        "root": Path(materialize.REPOSITORY_ROOT),
                        "authority_directory": Path(
                            materialize.AUTHORITY_DIRECTORY
                        ),
                    },
                )
                calls.append("build_receipt")
                verifier.validate_receipt(
                    receipt,
                    expected_control_revision=materialize.CONTROL_REVISION,
                )
                return receipt

            def build_evidence(self, value, **kwargs):
                self_outer.assertIs(value, receipt)
                calls.append("build_evidence")
                verifier.validate_receipt(
                    receipt,
                    expected_control_revision=materialize.CONTROL_REVISION,
                )
                verifier.validate_evidence(
                    evidence,
                    receipt,
                    materialize.canonical(receipt),
                    expected_control_revision=materialize.CONTROL_REVISION,
                )
                return evidence

            def build_checkpoint(self, **_kwargs):
                raise AssertionError("checkpoint entrypoint called")

        self_outer = self
        result = materialize._build_validate_artifacts(Builder(), verifier)
        self.assertEqual(result[2], materialize.canonical(receipt))
        self.assertEqual(result[3], materialize.canonical(evidence))
        self.assertEqual(calls.count("build_receipt"), 1)
        self.assertEqual(calls.count("build_evidence"), 1)
        self.assertEqual(calls.count("validate_receipt"), 3)
        self.assertEqual(calls.count("validate_evidence"), 2)
        self.assertNotIn("checkpoint", " ".join(calls))

    def test_materialize_three_output_fds_are_anonymous_blocking_unique_and_emit_once(self) -> None:
        materialize = self.materialize
        pairs = [socket.socketpair() for _unused in range(3)]
        children = [pair[0] for pair in pairs]
        parents = [pair[1] for pair in pairs]
        try:
            channels = materialize._preflight_output_fds(
                *(value.fileno() for value in children)
            )
            state: dict[str, object] = {
                "receipt": 0,
                "evidence": 0,
                "status": 0,
                "_channels": channels,
            }
            receipt_raw = materialize.canonical(
                {"schema": materialize.RECEIPT_SCHEMA, "value": 1}
            )
            evidence_raw = materialize.canonical(
                {"schema": materialize.EVIDENCE_SCHEMA, "value": 2}
            )
            materialize._emit_outputs_once(
                children[0].fileno(),
                children[1].fileno(),
                children[2].fileno(),
                receipt_raw,
                evidence_raw,
                state,
                channels,
            )
            self.assertEqual(parents[0].recv(65536), receipt_raw)
            self.assertEqual(parents[0].recv(1), b"")
            self.assertEqual(parents[1].recv(65536), evidence_raw)
            self.assertEqual(parents[1].recv(1), b"")
            status_raw = parents[2].recv(65536)
            self.assertEqual(parents[2].recv(1), b"")
            self.assertEqual(json.loads(status_raw), materialize.SUCCESS_STATUS)
            self.assertEqual(
                {key: state[key] for key in ("receipt", "evidence", "status")},
                {"receipt": 1, "evidence": 1, "status": 1},
            )
            materialize._close_output_channels(state)
        finally:
            for value in children + parents:
                value.close()

        alias_pair = socket.socketpair()
        other_pair = socket.socketpair()
        try:
            with self.assertRaisesRegex(
                materialize.MaterializeError,
                "^materialize_output_alias$",
            ):
                materialize._preflight_output_fds(
                    alias_pair[0].fileno(),
                    alias_pair[0].fileno(),
                    other_pair[0].fileno(),
                )
            alias_pair[0].setblocking(False)
            with self.assertRaisesRegex(
                materialize.MaterializeError,
                "^materialize_output_fd$",
            ):
                materialize._preflight_output_fds(
                    alias_pair[0].fileno(),
                    other_pair[0].fileno(),
                    other_pair[1].fileno(),
                )
        finally:
            for value in alias_pair + other_pair:
                value.close()

    def test_materialize_orchestrator_fakes_recheck_identity_before_any_emit(self) -> None:
        materialize = self.materialize
        receipt = {"schema": materialize.RECEIPT_SCHEMA}
        evidence = {"schema": materialize.EVIDENCE_SCHEMA}
        snapshot = {
            "runtime_raw": {},
            "identities": {"fixed": (1, 2)},
            "capture_sha256": {"fixed": "a" * 64},
            "manifest_sha256": "b" * 64,
        }
        events: list[str] = []
        runtime_calls = 0

        def runtime_validator():
            nonlocal runtime_calls
            runtime_calls += 1
            events.append("runtime:" + str(runtime_calls))
            return dict(snapshot)

        def dependency_preparer(validator, *, null_fd):
            self.assertEqual(null_fd, 99)
            first = validator()
            events.append("dependencies")
            return first, object(), object(), object(), object()

        class Wrapper:
            def shutdown(self, _direction):
                events.append("shutdown")

            def close(self):
                events.append("close")

        channels = {
            role: ((index, index), Wrapper())
            for index, role in enumerate(("receipt", "evidence", "status"), 1)
        }
        state = {"receipt": 0, "evidence": 0, "status": 0}
        result = materialize._materialize_once(
            7,
            8,
            9,
            runtime_validator=runtime_validator,
            dependency_preparer=dependency_preparer,
            capture_verifier=lambda _authority: events.append("capture"),
            artifact_builder=lambda _builder, _verifier: (
                receipt,
                evidence,
                materialize.canonical(receipt),
                materialize.canonical(evidence),
            ),
            output_emitter=lambda *_args: events.append("emit"),
            early_preflight=lambda: (events.append("early") or 99),
            output_preflight=lambda *_fds: (
                events.append("output-preflight") or channels
            ),
            state=state,
        )
        self.assertEqual(result, materialize.SUCCESS_STATUS)
        self.assertEqual(
            events,
            [
                "early",
                "output-preflight",
                "runtime:1",
                "dependencies",
                "capture",
                "runtime:2",
                "emit",
            ],
        )
        self.assertEqual(runtime_calls, 2)

        events.clear()
        runtime_calls = 0

        def tampered_runtime():
            nonlocal runtime_calls
            runtime_calls += 1
            value = dict(snapshot)
            value["identities"] = {"fixed": (runtime_calls, 2)}
            return value

        with self.assertRaisesRegex(
            materialize.MaterializeError,
            "^materialize_post_identity$",
        ):
            materialize._materialize_once(
                7,
                8,
                9,
                runtime_validator=tampered_runtime,
                dependency_preparer=lambda validator, **_kwargs: (
                    validator(),
                    object(),
                    object(),
                    object(),
                    object(),
                ),
                capture_verifier=lambda _authority: None,
                artifact_builder=lambda _builder, _verifier: (
                    receipt,
                    evidence,
                    materialize.canonical(receipt),
                    materialize.canonical(evidence),
                ),
                output_emitter=lambda *_args: events.append("emit"),
                early_preflight=lambda: 99,
                output_preflight=lambda *_fds: channels,
                state={"receipt": 0, "evidence": 0, "status": 0},
            )
        self.assertEqual(events, [])

    def test_materialize_fixed_failure_status_is_at_most_once_and_secret_free(self) -> None:
        materialize = self.materialize
        secret = "never-emit-this-private-value"
        calls: list[bytes] = []

        class Wrapper:
            def close(self):
                pass

        state: dict[str, object] = {"receipt": 0, "evidence": 0, "status": 0}

        def failing_runner(
            _receipt_fd,
            _evidence_fd,
            _status_fd,
            *,
            runtime_validator,
            state,
        ):
            self.assertTrue(callable(runtime_validator))
            state["_channels"] = {"status": ((1, 1), Wrapper())}
            raise RuntimeError(secret)

        def losing_writer(role, _descriptor, raw, emission, **_kwargs):
            self.assertEqual(role, "status")
            emission[role] = 1
            calls.append(raw)
            raise OSError("status lost")

        self.assertEqual(
            materialize._public_enabled_main(
                [
                    "--materialize",
                    "7",
                    "8",
                    "9",
                    "f" * 40,
                    "100000",
                    "a" * 64,
                    "b" * 40,
                    "50000",
                    "c" * 64,
                    "1000",
                    "d" * 64,
                    "1000",
                    "e" * 64,
                ],
                runner=failing_runner,
                failure_writer=losing_writer,
                state=state,
            ),
            78,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0]), materialize.FAILURE_STATUS)
        self.assertNotIn(secret.encode("ascii"), calls[0])
        self.assertEqual(state["status"], 1)

    def test_materialize_fd_signature_seam_uses_pipes_and_never_tempfiles(self) -> None:
        materialize = self.materialize
        calls: list[tuple[bytes, bytes, bytes]] = []

        def invoke(payload, signature, key):
            calls.append((payload, signature, key))
            return True

        self.assertIs(
            materialize._fd_only_verify_signature(
                b"message",
                b"signature",
                b"public-key",
                invoke=invoke,
            ),
            True,
        )
        self.assertEqual(calls, [(b"message", b"signature", b"public-key")])
        self.assertIs(
            materialize._fd_only_verify_signature(
                b"message",
                b"signature",
                b"public-key",
                invoke=lambda *_args: (_ for _ in ()).throw(RuntimeError("x")),
            ),
            False,
        )
        source = self.stager.MATERIALIZE_ROOT_PROGRAM
        self.assertIn("os.pipe()", source)
        self.assertNotIn("TemporaryDirectory", source)
        self.assertNotIn("NamedTemporaryFile", source)

    def test_materialize_pipe_preflight_is_directional_blocking_and_before_process(self) -> None:
        materialize = self.materialize
        pairs = [os.pipe() for _unused in range(4)]
        try:
            identities = materialize._preflight_pipe_pairs(pairs)
            self.assertEqual(len(identities), 8)
            self.assertEqual(len(set(identities)), 8)
            os.set_blocking(pairs[0][1], False)
            with self.assertRaisesRegex(
                materialize.MaterializeError,
                "^materialize_pipe_identity$",
            ):
                materialize._preflight_pipe_pairs(pairs)
        finally:
            for reader, writer in pairs:
                for descriptor in (reader, writer):
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

        process_calls: list[object] = []
        tool_calls: list[tuple[str, object]] = []
        null_fd = os.open("/dev/null", os.O_RDWR)
        try:
            with mock.patch.object(
                materialize,
                "_preflight_pipe_pairs",
                side_effect=materialize.MaterializeError(
                    "materialize_pipe_identity"
                ),
            ):
                self.assertIs(
                    materialize._invoke_fd_signature(
                        b"message",
                        b"signature",
                        b"public-key",
                        null_fd=null_fd,
                        popen=lambda *_args, **_kwargs: process_calls.append(
                            object()
                        ),
                        tool_probe=lambda path, expected: (
                            tool_calls.append((path, expected))
                            or ("fixed-tool-identity",)
                        ),
                    ),
                    False,
                )
            self.assertEqual(process_calls, [])
            self.assertEqual(
                tool_calls,
                [
                    (
                        "/usr/bin/openssl",
                        materialize.SYSTEM_TOOL_BINDINGS["/usr/bin/openssl"],
                    )
                ],
            )
        finally:
            os.close(null_fd)

    def test_materialize_process_group_absence_is_bounded_and_descendants_are_killed(self) -> None:
        materialize = self.materialize
        probes = iter([False, False, True])
        sleeps: list[float] = []
        clock = iter([0.0, 0.01, 0.02, 0.03])
        self.assertIs(
            materialize._prove_group_absent(
                17,
                probe=lambda _pgid: next(probes),
                monotonic=lambda: next(clock),
                sleeper=lambda value: sleeps.append(value),
                timeout=0.25,
            ),
            True,
        )
        self.assertEqual(len(sleeps), 2)

        class ReapedLeader:
            pid = 23
            returncode = 0

            def poll(self):
                return 0

        absence = iter([False, True])
        killed: list[tuple[int, int]] = []
        self.assertEqual(
            materialize._settle_process(
                ReapedLeader(),
                kill_group=lambda pgid, signal_number: killed.append(
                    (pgid, signal_number)
                ),
                prove_group_absent=lambda _pgid: next(absence),
            ),
            0,
        )
        self.assertEqual(killed, [(23, materialize.signal.SIGKILL)])

    def test_materialize_early_preflight_binds_root_isolation_python_and_null_fd(self) -> None:
        materialize = self.materialize
        flags = types.SimpleNamespace(
            isolated=1,
            ignore_environment=1,
            no_user_site=1,
            no_site=1,
            dont_write_bytecode=1,
        )
        limits = {"value": (1, 1)}

        def set_limit(_kind, value):
            limits["value"] = value

        descriptor = materialize._early_core0_clean_env_preflight(
            get_limit=lambda _kind: limits["value"],
            set_limit=set_limit,
            environ=dict(materialize.CHILD_ENV),
            get_euid=lambda: 0,
            getcwd=lambda: materialize.RUNTIME_DIRECTORY,
            executable="/Library/Developer/CommandLineTools/usr/bin/python3",
            flags=flags,
            realpath=lambda _path: (
                "/Library/Developer/CommandLineTools/Library/Frameworks/"
                "Python3.framework/Versions/3.9/bin/python3.9"
            ),
        )
        try:
            self.assertGreaterEqual(descriptor, 3)
            self.assertEqual(limits["value"], (0, 0))
        finally:
            os.close(descriptor)

        opened: list[str] = []
        with self.assertRaisesRegex(
            materialize.MaterializeError,
            "^materialize_early_identity$",
        ):
            materialize._early_core0_clean_env_preflight(
                environ=dict(materialize.CHILD_ENV),
                get_euid=lambda: 501,
                getcwd=lambda: materialize.RUNTIME_DIRECTORY,
                executable="/Library/Developer/CommandLineTools/usr/bin/python3",
                flags=flags,
                realpath=lambda _path: "fixed",
                opener=lambda path, _flags: (opened.append(path) or 99),
            )
        self.assertEqual(opened, [])

    def test_materialize_preserved_partition_snapshot_never_reads_custody(self) -> None:
        materialize = self.materialize
        runtime_raw = {
            name: ("installed-" + name).encode("ascii")
            for name in materialize.EXISTING_RUNTIME_BINDINGS
        }
        runtime_bindings = {
            name: (len(raw), hashlib.sha256(raw).hexdigest(), 0o600)
            for name, raw in runtime_raw.items()
        }
        read_paths: list[str] = []

        def list_names(path):
            if path == materialize.EXISTING_RUNTIME_DIRECTORY:
                return list(runtime_bindings)
            if path == materialize.JOURNAL_DIRECTORY:
                return []
            if path == materialize.CUSTODY_DIRECTORY:
                return list(materialize.CUSTODY_NAMES)
            raise AssertionError(path)

        def lstater(path):
            if path in (
                materialize.EXISTING_RUNTIME_DIRECTORY,
                materialize.JOURNAL_DIRECTORY,
                materialize.CUSTODY_DIRECTORY,
            ):
                return types.SimpleNamespace(
                    st_mode=stat.S_IFDIR | 0o700,
                    st_uid=0,
                    st_gid=0,
                    st_nlink=2,
                    st_dev=1,
                    st_ino=abs(hash(path)),
                )
            name = Path(path).name
            raw = runtime_raw.get(name)
            return types.SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600,
                st_uid=0,
                st_gid=0,
                st_nlink=1,
                st_dev=2,
                st_ino=abs(hash(path)),
                st_size=len(raw) if raw is not None else 4096,
                st_mtime_ns=101,
                st_ctime_ns=202,
            )

        def read_file(path, maximum):
            read_paths.append(path)
            raw = runtime_raw[Path(path).name]
            self.assertLessEqual(len(raw), maximum)
            return raw

        with mock.patch.object(
            materialize,
            "EXISTING_RUNTIME_BINDINGS",
            runtime_bindings,
        ):
            snapshot = materialize._snapshot_preserved_partitions(
                list_names=list_names,
                lstater=lstater,
                read_file=read_file,
                parent_probe=lambda _path, **_kwargs: (
                    ("fixed-parent",),
                ),
            )
        self.assertEqual(
            {Path(path).name for path in read_paths},
            set(runtime_bindings),
        )
        self.assertFalse(
            any("private-key" in path for path in read_paths),
            read_paths,
        )
        self.assertEqual(
            {key for key in snapshot if key.startswith("custody/")},
            {"custody/" + name for name in materialize.CUSTODY_NAMES},
        )
        for name in materialize.CUSTODY_NAMES:
            self.assertEqual(snapshot["custody/" + name][-2:], (101, 202))

    def test_materialize_local_object_probe_binds_whole_stager_and_embedded_literal(self) -> None:
        materialize = self.materialize
        literal = "fixed embedded payload\n"
        whole = (
            "MATERIALIZE_ROOT_PROGRAM = " + repr(literal) + "\n"
        ).encode("ascii")
        oid = materialize._git_blob_oid(whole)
        calls: list[list[str]] = []

        def local_git(arguments, **_kwargs):
            calls.append(arguments)
            if arguments[0] in ("merge-base", "cat-file"):
                return types.SimpleNamespace(returncode=0, stdout=b"")
            if arguments[0] == "rev-parse":
                return types.SimpleNamespace(
                    returncode=0,
                    stdout=(oid + "\n").encode("ascii"),
                )
            if arguments[0] == "show":
                return types.SimpleNamespace(returncode=0, stdout=whole)
            raise AssertionError(arguments)

        with (
            mock.patch.object(materialize, "_local_only_git", local_git),
            mock.patch.object(
                materialize,
                "_default_repository_probe",
                return_value=("fixed",),
            ),
        ):
            result = materialize._local_object_probe(
                "f" * 40,
                materialize.STAGER_REF,
                oid,
                len(whole),
                hashlib.sha256(whole).hexdigest(),
                null_fd=77,
            )
        self.assertEqual(result["byte_count"], len(whole))
        self.assertEqual(result["sha256"], hashlib.sha256(whole).hexdigest())
        self.assertEqual(result["embedded_literal_byte_count"], len(literal))
        self.assertEqual(
            result["embedded_literal_sha256"],
            hashlib.sha256(literal.encode("ascii")).hexdigest(),
        )
        self.assertEqual(
            [arguments[0] for arguments in calls],
            ["merge-base", "cat-file", "rev-parse", "show"],
        )

    def test_materialize_git_runner_is_bounded_contained_and_checks_post_identity(self) -> None:
        materialize = self.materialize

        class Process:
            pid = 41
            stdout = object()

        process = Process()
        popen_calls: list[tuple[list[str], dict[str, object]]] = []
        tool_calls: list[str] = []
        repository_calls: list[str] = []

        def popen(arguments, **kwargs):
            popen_calls.append((arguments, kwargs))
            return process

        def tool_probe(path, _expected):
            tool_calls.append(path)
            return (path, "fixed-tool-and-parent-identity")

        def repository_probe(root):
            repository_calls.append(str(root))
            return ("fixed-repository-identity",)

        settle_calls: list[bool] = []

        with (
            mock.patch.object(
                materialize,
                "_drain_git_stdout",
                return_value=b"data",
            ) as drain,
            mock.patch.object(
                materialize,
                "_settle_process",
                side_effect=lambda _process, force_kill=False: (
                    settle_calls.append(force_kill) or 0
                ),
            ),
        ):
            result = materialize._local_only_git(
                ["show", materialize.CONTROL_REVISION + ":tools/fixed.py"],
                root=Path(materialize.REPOSITORY_ROOT),
                null_fd=77,
                maximum_stdout=4,
                popen=popen,
                tool_probe=tool_probe,
                repository_probe=repository_probe,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"data")
        drain.assert_called_once_with(process, 4)
        self.assertEqual(settle_calls, [False])
        self.assertEqual(len(popen_calls), 1)
        self.assertIs(popen_calls[0][1]["start_new_session"], True)
        self.assertIs(popen_calls[0][1]["close_fds"], True)
        self.assertEqual(popen_calls[0][1]["stdin"], 77)
        self.assertEqual(popen_calls[0][1]["stderr"], 77)
        self.assertEqual(popen_calls[0][1]["stdout"], subprocess.PIPE)
        self.assertEqual(len(tool_calls), 4)
        self.assertEqual(len(repository_calls), 2)

        for code in ("materialize_git_timeout", "materialize_git_output_limit"):
            with self.subTest(code=code):
                contained: list[bool] = []
                with (
                    mock.patch.object(
                        materialize,
                        "_drain_git_stdout",
                        side_effect=materialize.MaterializeError(code),
                    ),
                    mock.patch.object(
                        materialize,
                        "_settle_process",
                        side_effect=lambda _process, force_kill=False: (
                            contained.append(force_kill) or -9
                        ),
                    ),
                ):
                    with self.assertRaisesRegex(
                        materialize.MaterializeError,
                        "^" + code + "$",
                    ):
                        materialize._local_only_git(
                            [
                                "show",
                                materialize.CONTROL_REVISION
                                + ":tools/fixed.py",
                            ],
                            root=Path(materialize.REPOSITORY_ROOT),
                            null_fd=77,
                            maximum_stdout=4,
                            popen=popen,
                            tool_probe=tool_probe,
                            repository_probe=repository_probe,
                        )
                self.assertEqual(contained, [True])

    @unittest.skipUnless(sys.platform == "darwin", "frozen macOS tool identity")
    def test_materialize_tool_probe_freezes_file_and_each_parent_identity(self) -> None:
        materialize = self.materialize
        for path, expected in materialize.SYSTEM_TOOL_BINDINGS.items():
            with self.subTest(path=path):
                before = materialize._default_tool_probe(path, expected)
                after = materialize._default_tool_probe(path, expected)
                self.assertEqual(after, before)
                file_identity, parents = before
                self.assertEqual(file_identity[0], path)
                self.assertEqual(file_identity[-1], expected[1])
                self.assertGreaterEqual(len(parents), 2)
                for row in parents:
                    if row[1] == "symlink":
                        self.assertEqual(
                            materialize.ALLOWED_PARENT_SYMLINKS[row[0]],
                            row[2],
                        )
                    else:
                        self.assertEqual(row[1], "directory")

    def test_materialize_public_parse_failure_cannot_write_unpreflighted_status_fd(self) -> None:
        materialize = self.materialize
        writes: list[bytes] = []
        argv = [
            "--materialize",
            "7",
            "8",
            "9",
            "f" * 40,
            "100000",
            "a" * 64,
            "b" * 40,
            "50000",
            "c" * 64,
            "1000",
            "d" * 64,
            "1000",
            "e" * 64,
        ]
        self.assertEqual(
            materialize._public_enabled_main(
                argv,
                runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("fixed")
                ),
                failure_writer=lambda _role, _fd, raw, _state, **_kwargs: (
                    writes.append(raw)
                ),
            ),
            78,
        )
        self.assertEqual(writes, [])

    def _make_stage_fixture(self):
        stager = self.stager
        source_revision = "1" * 40
        acceptance_revision = "2" * 40
        test_raw = Path(__file__).read_bytes()
        source_values = {}
        for ref in stager.SOURCE_REFS:
            if ref == stager.STAGER_REF:
                first = self.raw
                second = self.raw
            elif ref == stager.TEST_REF:
                first = test_raw
                second = test_raw
            else:
                first = ("source:" + ref).encode("ascii")
                second = ("acceptance:" + ref).encode("ascii")
            source_values[(source_revision, ref)] = first
            source_values[(acceptance_revision, ref)] = second

        cached = getattr(self.__class__, "_stage_fixed_raw", None)
        if cached is None:
            cached = {}
            for ref, binding in stager.FIXED_BINDINGS.items():
                result = git("cat-file", "blob", binding["git_blob_oid"])
                if result.returncode != 0:
                    raise AssertionError(result.stderr.decode("utf-8", "replace"))
                cached[ref] = result.stdout
            self.__class__._stage_fixed_raw = cached

        def git_reader(revision, ref):
            raw = source_values.get((revision, ref))
            if raw is None and ref in cached:
                binding = stager.FIXED_BINDINGS[ref]
                allowed = {
                    binding["revision"],
                    acceptance_revision,
                }
                if binding.get("source_revision") is not None:
                    allowed.add(binding["source_revision"])
                if revision in allowed:
                    raw = cached[ref]
            if raw is None:
                raise AssertionError((revision, ref))
            return {
                "raw": raw,
                "git_blob_oid": stager._git_blob_oid_bytes(raw),
            }

        topology = {
            "parents": {
                source_revision: [stager.BASE_REVISION],
                acceptance_revision: [source_revision],
            },
            "base_to_source_paths": sorted(stager.SOURCE_REFS),
            "source_to_acceptance_paths": sorted(stager.ACCEPTANCE_REFS),
            "head_revision": acceptance_revision,
            "upstream_revision": acceptance_revision,
            "origin_main_revision": acceptance_revision,
            "tracked_changes": [],
        }
        tools = {
            path: {"fixed": path}
            for path in (
                set(stager.STAGE_SYSTEM_TOOL_BINDINGS)
                | set(stager.STAGE_SYSTEM_SYMLINK_BINDINGS)
            )
        }
        repository = {
            "directories": {"repo": [1, 2, 3]},
            "files": {"HEAD": [4, 5, 6]},
            "absent": ["alternates", "shallow"],
        }
        bundle = stager._build_stage_bundle(
            source_revision,
            acceptance_revision,
            topology_snapshot=topology,
            git_reader=git_reader,
            system_tool_snapshot=tools,
            repository_snapshot=repository,
        )
        return types.SimpleNamespace(
            source_revision=source_revision,
            acceptance_revision=acceptance_revision,
            topology=topology,
            tools=tools,
            repository=repository,
            git_reader=git_reader,
            bundle=bundle,
        )

    def test_stage_bundle_canonical_roundtrip_and_root_exact_staging_order(self) -> None:
        fixture = self._make_stage_fixture()
        root = self.stage_root
        raw = self.stager.canonical_bytes(fixture.bundle)
        parsed = root._read_bundle(io.BytesIO(raw))
        self.assertEqual(parsed, fixture.bundle)

        events = []
        topology_calls = []
        git_calls = []

        def root_git_reader(revision, ref):
            git_calls.append((revision, ref))
            return fixture.git_reader(revision, ref)

        def topology_reader(source_revision, acceptance_revision):
            topology_calls.append((source_revision, acceptance_revision))
            return fixture.topology

        def mkdir_one(path):
            events.append(("mkdir", path, 0o700))

        def write_one(path, value, mode):
            events.append(("write", path, mode, len(value)))

        def fsync_directory(path):
            events.append(("fsync", path))

        observed_noteai_nlinks = []
        simulated_noteai_nlinks = iter((10, 10, 12))

        def inventory_snapshot():
            observed_noteai_nlinks.append(next(simulated_noteai_nlinks))
            return {
                "noteai": [7, 8, stat.S_IFDIR | 0o755, 0, 0],
                "existing": "fixed",
            }

        result = root._stage_once(
            parsed,
            topology_reader=topology_reader,
            git_reader=root_git_reader,
            inventory_snapshot=inventory_snapshot,
            tool_snapshot=lambda: fixture.tools,
            repository_snapshot=lambda: fixture.repository,
            absence_checker=lambda: events.append(("absent",)),
            new_inventory_verifier=lambda capture, materialize: {
                root.CAPTURE_DIRECTORY: tuple(capture),
                root.MATERIALIZE_DIRECTORY: tuple(materialize),
            },
            mkdir_one=mkdir_one,
            write_one=write_one,
            fsync_directory=fsync_directory,
        )
        self.assertEqual(result["status"], "BOTH_RUNTIME_PARTITIONS_STAGED")
        self.assertEqual(result["sudo_dispatch_count"], 1)
        self.assertEqual(result["automatic_retry_count"], 0)
        self.assertEqual(result["cleanup_count"], 0)
        self.assertEqual(result["rollback_count"], 0)
        self.assertEqual(result["private_key_read_count"], 0)
        self.assertEqual(observed_noteai_nlinks, [10, 10, 12])
        self.assertIn(
            "noteai = _directory_identity(NOTEAI_ROOT, lstater=lstater)[:5]",
            self.stager.STAGE_ROOT_PROGRAM,
        )
        self.assertNotIn(
            "noteai = _directory_identity(NOTEAI_ROOT, lstater=lstater)[:6]",
            self.stager.STAGE_ROOT_PROGRAM,
        )
        self.assertEqual(len(topology_calls), 3)
        self.assertEqual(events.count(("absent",)), 2)
        self.assertEqual(
            [event[1] for event in events if event[0] == "mkdir"],
            [root.CAPTURE_DIRECTORY, root.MATERIALIZE_DIRECTORY],
        )
        self.assertEqual(
            [Path(event[1]).name for event in events if event[0] == "write"],
            list(root.CAPTURE_ORDER) + list(root.MATERIALIZE_ORDER),
        )
        for event in events:
            if event[0] == "write":
                expected = 0o600 if event[1].endswith("manifest.json") else 0o500
                self.assertEqual(event[2], expected)
        for ref, row in fixture.bundle["fixed_rows"].items():
            expected_revisions = {
                row["revision"],
                fixture.acceptance_revision,
            }
            if row["source_revision"] is not None:
                expected_revisions.add(row["source_revision"])
            for revision in expected_revisions:
                self.assertEqual(git_calls.count((revision, ref)), 3)

    def test_stage_root_rejects_noteai_parent_stable_field_drift(self) -> None:
        fixture = self._make_stage_fixture()
        root = self.stage_root
        parsed = root._read_bundle(
            io.BytesIO(self.stager.canonical_bytes(fixture.bundle))
        )
        snapshots = iter(
            (
                {"noteai": [7, 8, stat.S_IFDIR | 0o755, 0, 0]},
                {"noteai": [7, 8, stat.S_IFDIR | 0o755, 0, 0]},
                {"noteai": [7, 9, stat.S_IFDIR | 0o755, 0, 0]},
            )
        )
        with self.assertRaisesRegex(
            root.StageRootError,
            "^stage_root_existing_drift$",
        ):
            root._stage_once(
                parsed,
                topology_reader=lambda _source, _acceptance: fixture.topology,
                git_reader=fixture.git_reader,
                inventory_snapshot=lambda: next(snapshots),
                tool_snapshot=lambda: fixture.tools,
                repository_snapshot=lambda: fixture.repository,
                absence_checker=lambda: None,
                new_inventory_verifier=lambda capture, materialize: {
                    root.CAPTURE_DIRECTORY: tuple(capture),
                    root.MATERIALIZE_DIRECTORY: tuple(materialize),
                },
                mkdir_one=lambda _path: None,
                write_one=lambda _path, _raw, _mode: None,
                fsync_directory=lambda _path: None,
            )

    def test_stage_root_second_partition_failure_keeps_append_only_residue(self) -> None:
        fixture = self._make_stage_fixture()
        root = self.stage_root
        parsed = root._read_bundle(
            io.BytesIO(self.stager.canonical_bytes(fixture.bundle))
        )
        residue = []
        cleanup = []

        def mkdir_one(path):
            if path == root.MATERIALIZE_DIRECTORY:
                raise root.StageRootError("fixed_second_directory_failure")
            residue.append(("directory", path))

        def write_one(path, raw, mode):
            residue.append(("file", path, mode, len(raw)))

        with self.assertRaisesRegex(
            root.StageRootError,
            "^fixed_second_directory_failure$",
        ):
            root._stage_once(
                parsed,
                topology_reader=lambda _source, _acceptance: fixture.topology,
                git_reader=fixture.git_reader,
                inventory_snapshot=lambda: {"existing": "fixed"},
                tool_snapshot=lambda: fixture.tools,
                repository_snapshot=lambda: fixture.repository,
                absence_checker=lambda: None,
                new_inventory_verifier=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("post inventory reached")
                ),
                mkdir_one=mkdir_one,
                write_one=write_one,
                fsync_directory=lambda path: residue.append(("fsync", path)),
            )
        self.assertEqual(residue[0], ("directory", root.CAPTURE_DIRECTORY))
        self.assertEqual(
            [Path(row[1]).name for row in residue if row[0] == "file"],
            list(root.CAPTURE_ORDER),
        )
        self.assertEqual(cleanup, [])

    def test_stage_root_tool_and_repo_preflight_precede_every_git_read(self) -> None:
        fixture = self._make_stage_fixture()
        root = self.stage_root
        parsed = root._read_bundle(
            io.BytesIO(self.stager.canonical_bytes(fixture.bundle))
        )
        for label, tools, repository, expected in (
            ("tool", {"wrong": True}, fixture.repository, "stage_root_tools"),
            ("repository", fixture.tools, {"wrong": True}, "stage_root_repository"),
        ):
            with self.subTest(label=label):
                topology_calls = []
                git_calls = []
                with self.assertRaisesRegex(
                    root.StageRootError,
                    "^" + expected + "$",
                ):
                    root._stage_once(
                        parsed,
                        tool_snapshot=lambda: tools,
                        repository_snapshot=lambda: repository,
                        topology_reader=lambda *_args: topology_calls.append(1),
                        git_reader=lambda *_args: git_calls.append(1),
                        inventory_snapshot=lambda: (_ for _ in ()).throw(
                            AssertionError("inventory reached before trust gates")
                        ),
                    )
                self.assertEqual(topology_calls, [])
                self.assertEqual(git_calls, [])

    def test_stage_single_sudo_uses_visible_tty_and_four_anonymous_fds(self) -> None:
        fixture = self._make_stage_fixture()
        stager = self.stager
        bundle_raw = stager.canonical_bytes(fixture.bundle)
        status_raw = stager.canonical_bytes(
            {
                "schema": stager.STAGE_CHILD_STATUS_SCHEMA,
                "status": "BOTH_RUNTIME_PARTITIONS_STAGED",
                "source_revision": fixture.source_revision,
                "acceptance_revision": fixture.acceptance_revision,
                "capture_directory_create_count": 1,
                "materialize_directory_create_count": 1,
                "capture_file_create_count": 3,
                "materialize_file_create_count": 6,
                "sudo_dispatch_count": 1,
                "automatic_retry_count": 0,
                "cleanup_count": 0,
                "rollback_count": 0,
                "private_key_read_count": 0,
            }
        )
        calls = []

        class FakeProcess:
            pid = 98765

            def __init__(self, thread):
                self.thread = thread
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, *args, **kwargs):
                self.thread.join(2)
                if self.thread.is_alive():
                    raise AssertionError("fake root did not exit")
                self.returncode = 0
                return 0

            def terminate(self):
                raise AssertionError("outer must not terminate interactive sudo")

            def kill(self):
                raise AssertionError("outer must not kill interactive sudo")

        def popen(arguments, **kwargs):
            calls.append((arguments, kwargs))
            incoming = socket.socket(fileno=os.dup(kwargs["stdin"]))
            outgoing = socket.socket(fileno=os.dup(kwargs["stdout"]))

            def child():
                received = bytearray()
                while True:
                    chunk = incoming.recv(65536)
                    if not chunk:
                        break
                    received.extend(chunk)
                self.assertEqual(bytes(received), bundle_raw)
                outgoing.sendall(status_raw)
                outgoing.shutdown(socket.SHUT_WR)
                incoming.close()
                outgoing.close()

            thread = threading.Thread(target=child)
            thread.start()
            return FakeProcess(thread)

        observed = stager._dispatch_stage_root_once(
            bundle_raw,
            expected_tool_snapshot=fixture.tools,
            tool_snapshot=lambda: fixture.tools,
            popen=popen,
        )
        self.assertEqual(observed, status_raw)
        self.assertEqual(len(calls), 1)
        arguments, kwargs = calls[0]
        self.assertEqual(arguments[:4], ["/usr/bin/sudo", "-T", "120", "--"])
        self.assertEqual(arguments[4:8], ["/usr/bin/python3", "-I", "-S", "-B"])
        self.assertNotIn("-S", arguments[:4])
        self.assertIs(kwargs["stderr"], None)
        self.assertIs(kwargs["start_new_session"], False)
        self.assertIs(kwargs["close_fds"], True)
        self.assertEqual(kwargs["cwd"], stager.REPOSITORY_ROOT)
        self.assertEqual(kwargs["env"], stager.STAGE_SUDO_ENVIRONMENT)
        self.assertIsInstance(kwargs["stdin"], int)
        self.assertIsInstance(kwargs["stdout"], int)
        self.assertNotEqual(kwargs["stdin"], kwargs["stdout"])

    def test_stage_child_status_rejects_unknown_fields_before_public_copy(self) -> None:
        fixture = self._make_stage_fixture()
        value = {
            "schema": self.stager.STAGE_CHILD_STATUS_SCHEMA,
            "status": "BOTH_RUNTIME_PARTITIONS_STAGED",
            "source_revision": fixture.source_revision,
            "acceptance_revision": fixture.acceptance_revision,
            "capture_directory_create_count": 1,
            "materialize_directory_create_count": 1,
            "capture_file_create_count": 3,
            "materialize_file_create_count": 6,
            "sudo_dispatch_count": 1,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "rollback_count": 0,
            "private_key_read_count": 0,
            "unexpected": "must-not-copy",
        }
        with self.assertRaisesRegex(
            self.stager.StagerError,
            "^stage_child_status$",
        ):
            self.stager._validate_stage_child_status(
                self.stager.canonical_bytes(value),
                fixture.source_revision,
                fixture.acceptance_revision,
            )

    def test_stage_public_result_is_fsynced_empty_before_single_sudo(self) -> None:
        stager = self.stager
        acceptance = "2" * 40
        path = stager._future_result_path(acceptance)
        opens = []
        fsyncs = []
        closes = []
        uid = os.geteuid()
        parent = types.SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o700,
            st_uid=uid,
            st_gid=os.getegid(),
            st_dev=7,
            st_ino=8,
            st_nlink=2,
        )
        output = types.SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=uid,
            st_gid=os.getegid(),
            st_dev=7,
            st_ino=9,
            st_nlink=1,
            st_size=0,
        )

        descriptor, identity = stager._precreate_stage_result(
            path,
            opener=lambda opened, flags, mode: (
                opens.append((opened, flags, mode)) or 10
            ),
            lstater=lambda _path: parent,
            fstater=lambda fd: output if fd == 10 else (_ for _ in ()).throw(
                AssertionError(fd)
            ),
            closer=lambda fd: closes.append(fd),
            fsyncer=lambda fd: fsyncs.append(fd),
            directory_opener=lambda opened, flags: (
                opens.append((opened, flags, None)) or 11
            ),
        )
        self.assertEqual(descriptor, 10)
        self.assertEqual(identity["path"], path)
        self.assertTrue(opens[0][1] & os.O_EXCL)
        self.assertTrue(opens[0][1] & os.O_NOFOLLOW)
        self.assertEqual(opens[0][2], 0o600)
        self.assertEqual(fsyncs, [10, 11])
        self.assertEqual(closes, [11])

    def test_stage_result_directory_close_cannot_reverse_durable_success(self) -> None:
        fixture = self._make_stage_fixture()
        stager = self.stager
        path = fixture.bundle["result_path"]
        parent_path = str(Path(path).parent)
        uid = os.geteuid()
        gid = os.getegid()
        parent = types.SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o700,
            st_uid=uid,
            st_gid=gid,
            st_dev=7,
            st_ino=8,
            st_nlink=2,
        )
        storage = bytearray()
        offset = [0]
        events = []
        identity = {
            "path": path,
            "parent": (7, 8, parent.st_mode, uid, gid, 2),
            "file": (7, 9, stat.S_IFREG | 0o600, uid, gid, 1),
        }

        def file_row():
            return types.SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600,
                st_uid=uid,
                st_gid=gid,
                st_dev=7,
                st_ino=9,
                st_nlink=1,
                st_size=len(storage),
            )

        def writer(_descriptor, view):
            raw = bytes(view)
            storage.extend(raw)
            events.append(("write", len(raw)))
            return len(raw)

        def seeker(_descriptor, position, whence):
            self.assertEqual((position, whence), (0, os.SEEK_SET))
            offset[0] = 0
            return 0

        def reader(_descriptor, maximum):
            raw = bytes(storage[offset[0] : offset[0] + maximum])
            offset[0] += len(raw)
            return raw

        def lstater(observed):
            if observed == path:
                return file_row()
            if observed == parent_path:
                return parent
            raise AssertionError(observed)

        writer_returns = []

        def durable_writer(descriptor, value, **kwargs):
            observed = stager._write_stage_result_once(
                descriptor,
                value,
                path=kwargs["path"],
                identity=kwargs["identity"],
                writer=writer,
                seeker=seeker,
                reader=reader,
                fsyncer=lambda fd: events.append(("fsync", fd)),
                fstater=lambda fd: file_row()
                if fd == 33
                else (_ for _ in ()).throw(AssertionError(fd)),
                lstater=lstater,
                directory_opener=lambda opened, _flags: (
                    events.append(("open-directory", opened)) or 44
                ),
                closer=lambda fd: (
                    events.append(("close", fd))
                    or (_ for _ in ()).throw(RuntimeError("durable-dir-close"))
                ),
            )
            writer_returns.append(observed)
            return observed

        child = {
            "schema": stager.STAGE_CHILD_STATUS_SCHEMA,
            "status": "BOTH_RUNTIME_PARTITIONS_STAGED",
            "source_revision": fixture.source_revision,
            "acceptance_revision": fixture.acceptance_revision,
            "capture_directory_create_count": 1,
            "materialize_directory_create_count": 1,
            "capture_file_create_count": 3,
            "materialize_file_create_count": 6,
            "sudo_dispatch_count": 1,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "rollback_count": 0,
            "private_key_read_count": 0,
        }
        result = stager._future_stage_once(
            fixture.source_revision,
            fixture.acceptance_revision,
            topology_snapshot=fixture.topology,
            git_reader=fixture.git_reader,
            system_tool_snapshot=fixture.tools,
            repository_snapshot=fixture.repository,
            dispatcher=lambda _raw: stager.canonical_bytes(child),
            result_precreator=lambda observed: (
                33,
                identity
                if observed == path
                else (_ for _ in ()).throw(AssertionError(observed)),
            ),
            result_writer=durable_writer,
            closer=lambda fd: events.append(("outer-close", fd)),
            outer_identity_validator=lambda: None,
            result_identity_checker=lambda *_args, **_kwargs: None,
        )
        self.assertEqual(result["status"], "BOTH_RUNTIME_PARTITIONS_STAGED")
        self.assertEqual(writer_returns, [stager.canonical_bytes(result)])
        self.assertIn(("fsync", 44), events)
        self.assertIn(("close", 44), events)
        self.assertEqual(events[-1], ("outer-close", 33))

    def test_future_stage_public_result_uses_only_exact_child_whitelist(self) -> None:
        fixture = self._make_stage_fixture()
        stager = self.stager
        child = {
            "schema": stager.STAGE_CHILD_STATUS_SCHEMA,
            "status": "BOTH_RUNTIME_PARTITIONS_STAGED",
            "source_revision": fixture.source_revision,
            "acceptance_revision": fixture.acceptance_revision,
            "capture_directory_create_count": 1,
            "materialize_directory_create_count": 1,
            "capture_file_create_count": 3,
            "materialize_file_create_count": 6,
            "sudo_dispatch_count": 1,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "rollback_count": 0,
            "private_key_read_count": 0,
        }
        result_rows = []
        identity_sizes = []
        outer_checks = []
        closes = []

        result = stager._future_stage_once(
            fixture.source_revision,
            fixture.acceptance_revision,
            topology_snapshot=fixture.topology,
            git_reader=fixture.git_reader,
            system_tool_snapshot=fixture.tools,
            repository_snapshot=fixture.repository,
            dispatcher=lambda _raw: stager.canonical_bytes(child),
            result_precreator=lambda path: (99, {"path": path}),
            result_writer=lambda fd, value, **kwargs: result_rows.append(
                (fd, value, kwargs)
            ),
            closer=lambda fd: closes.append(fd),
            outer_identity_validator=lambda: outer_checks.append(True),
            result_identity_checker=lambda _fd, _identity, **kwargs: (
                identity_sizes.append(kwargs.get("expected_size"))
            ),
        )
        self.assertEqual(result["schema"], stager.STAGE_RESULT_SCHEMA)
        self.assertNotIn("result_sha256", result)
        self.assertNotIn("unexpected", result)
        self.assertEqual(result["sudo_dispatch_count"], 1)
        self.assertEqual(len(result_rows), 1)
        self.assertEqual(result_rows[0][0], 99)
        self.assertEqual(
            result_rows[0][2]["path"],
            fixture.bundle["result_path"],
        )
        self.assertEqual(identity_sizes, [0, 0])
        self.assertEqual(len(outer_checks), 2)
        self.assertEqual(closes, [99])

        committed = stager._future_stage_once(
            fixture.source_revision,
            fixture.acceptance_revision,
            topology_snapshot=fixture.topology,
            git_reader=fixture.git_reader,
            system_tool_snapshot=fixture.tools,
            repository_snapshot=fixture.repository,
            dispatcher=lambda _raw: stager.canonical_bytes(child),
            result_precreator=lambda path: (100, {"path": path}),
            result_writer=lambda _fd, _value, **_kwargs: None,
            closer=lambda _fd: (_ for _ in ()).throw(
                RuntimeError("post-commit-close")
            ),
            outer_identity_validator=lambda: None,
            result_identity_checker=lambda *_args, **_kwargs: None,
        )
        self.assertEqual(committed["status"], "BOTH_RUNTIME_PARTITIONS_STAGED")

        failed_outer_checks = []
        failed_identity_sizes = []
        with self.assertRaisesRegex(RuntimeError, "^dispatch-failed$"):
            stager._future_stage_once(
                fixture.source_revision,
                fixture.acceptance_revision,
                topology_snapshot=fixture.topology,
                git_reader=fixture.git_reader,
                system_tool_snapshot=fixture.tools,
                repository_snapshot=fixture.repository,
                dispatcher=lambda _raw: (_ for _ in ()).throw(
                    RuntimeError("dispatch-failed")
                ),
                result_precreator=lambda path: (101, {"path": path}),
                result_writer=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("writer reached")
                ),
                closer=lambda _fd: None,
                outer_identity_validator=lambda: failed_outer_checks.append(
                    True
                ),
                result_identity_checker=lambda _fd, _identity, **kwargs: (
                    failed_identity_sizes.append(kwargs.get("expected_size"))
                ),
            )
        self.assertEqual(failed_outer_checks, [True, True])
        self.assertEqual(failed_identity_sizes, [0, 0])

    def test_stage_root_signal_handler_contains_active_git_for_ctrl_c(self) -> None:
        root = self.stage_root
        calls = []

        class Process:
            pid = 76543

        process = Process()
        root._ACTIVE_GIT_PROCESS = process
        try:
            with mock.patch.object(
                root,
                "_settle_git_process",
                side_effect=lambda observed, **kwargs: (
                    calls.append((observed, kwargs)) or -9
                ),
            ):
                with self.assertRaisesRegex(
                    root.StageRootError,
                    "^stage_root_terminated$",
                ):
                    root._root_termination_handler(root.signal.SIGINT, None)
        finally:
            root._ACTIVE_GIT_PROCESS = None
        self.assertEqual(calls, [(process, {"force_kill": True})])

    def test_stage_root_settle_refuses_unreaped_or_live_descendant_group(self) -> None:
        root = self.stage_root

        class Clock:
            def __init__(self):
                self.value = 0.0

            def monotonic(self):
                return self.value

            def sleep(self, duration):
                self.value += max(duration, 0.25)

        for label, wait_result in (
            ("wait-timeout", subprocess.TimeoutExpired("git", 0.05)),
            ("leader-reaped-descendant-live", 0),
        ):
            with self.subTest(label=label):
                clock = Clock()
                calls = []

                class Process:
                    pid = 76544

                    def wait(self, timeout):
                        calls.append(("wait", timeout))
                        if isinstance(wait_result, BaseException):
                            raise wait_result
                        return wait_result

                def killpg(pid, sig):
                    calls.append(("killpg", pid, sig))
                    # SIGKILL is delivered, but killpg(pid, 0) continues to
                    # prove either an unreaped leader or a live descendant.
                    return None

                with mock.patch.object(root.os, "killpg", side_effect=killpg):
                    with self.assertRaisesRegex(
                        root.StageRootError,
                        "^stage_root_git_containment$",
                    ):
                        root._settle_git_process(
                            Process(),
                            force_kill=True,
                            monotonic=clock.monotonic,
                            sleep=clock.sleep,
                        )
                self.assertEqual(
                    calls[0],
                    ("killpg", 76544, root.signal.SIGKILL),
                )
                self.assertGreaterEqual(
                    calls.count(("killpg", 76544, 0)),
                    2,
                )

    def test_stage_git_selector_failure_occurs_before_any_child_spawn(self) -> None:
        for module, function_name, error in (
            (self.stager, "_stage_local_git", RuntimeError("outer-selector")),
            (self.stage_root, "_local_git", RuntimeError("root-selector")),
        ):
            with self.subTest(function=function_name):
                popen_calls = []
                with self.assertRaises(RuntimeError):
                    getattr(module, function_name)(
                        ["rev-parse", "HEAD"],
                        128,
                        selector_factory=lambda: (_ for _ in ()).throw(error),
                        popen=lambda *_args, **_kwargs: popen_calls.append(1),
                    )
                self.assertEqual(popen_calls, [])

    def test_stage_root_git_child_drops_root_privilege_before_repo_read(self) -> None:
        root = self.stage_root
        popen_calls = []
        signal_mask_calls = []

        class Stdout:
            def fileno(self):
                return 55

        class Process:
            pid = 22222
            stdout = Stdout()

        process = Process()

        class Selector:
            def __init__(self):
                self.done = False

            def register(self, fileobj, _events):
                self.fileobj = fileobj

            def select(self, _timeout):
                if self.done:
                    return []
                self.done = True
                return [(types.SimpleNamespace(fileobj=self.fileobj), 1)]

            def unregister(self, _fileobj):
                return None

            def close(self):
                return None

        def popen(arguments, **kwargs):
            popen_calls.append((arguments, kwargs))
            return process

        def pthread_sigmask(how, values):
            signal_mask_calls.append(
                (
                    how,
                    tuple(values),
                    root._ACTIVE_GIT_PROCESS,
                )
            )
            return frozenset()

        with (
            mock.patch.object(root.os, "set_blocking"),
            mock.patch.object(root.os, "read", return_value=b""),
            mock.patch.object(root, "_settle_git_process", return_value=0),
            mock.patch.object(
                root.signal,
                "pthread_sigmask",
                side_effect=pthread_sigmask,
            ),
        ):
            self.assertEqual(
                root._local_git(
                    ["rev-parse", "HEAD"],
                    128,
                    popen=popen,
                    selector_factory=Selector,
                    monotonic=lambda: 0.0,
                ),
                (0, b""),
            )
        self.assertEqual(len(popen_calls), 1)
        arguments, kwargs = popen_calls[0]
        self.assertIn("safe.directory=" + root.REPOSITORY_ROOT, arguments)
        self.assertIn("--no-replace-objects", arguments)
        self.assertIs(kwargs["start_new_session"], True)
        self.assertIs(kwargs["preexec_fn"], root._git_child_preexec)
        self.assertEqual(len(signal_mask_calls), 4)
        self.assertEqual(signal_mask_calls[0][0], root.signal.SIG_BLOCK)
        self.assertIsNone(signal_mask_calls[0][2])
        self.assertEqual(signal_mask_calls[1][0], root.signal.SIG_SETMASK)
        self.assertIs(signal_mask_calls[1][2], process)
        self.assertEqual(signal_mask_calls[2][0], root.signal.SIG_BLOCK)
        self.assertIs(signal_mask_calls[2][2], process)
        self.assertEqual(signal_mask_calls[3][0], root.signal.SIG_SETMASK)
        self.assertIsNone(signal_mask_calls[3][2])
        self.assertEqual(
            set(signal_mask_calls[0][1]),
            set(root._TERMINATION_SIGNALS),
        )

        calls = []
        with (
            mock.patch.object(
                root.resource,
                "setrlimit",
                side_effect=lambda name, value: calls.append(
                    ("setrlimit", name, value)
                ),
            ),
            mock.patch.object(
                root.resource,
                "getrlimit",
                return_value=(0, 0),
            ),
            mock.patch.object(
                root.os,
                "setgroups",
                side_effect=lambda value: calls.append(("setgroups", value)),
            ),
            mock.patch.object(
                root.os,
                "setgid",
                side_effect=lambda value: calls.append(("setgid", value)),
            ),
            mock.patch.object(
                root.os,
                "setuid",
                side_effect=lambda value: calls.append(("setuid", value)),
            ),
            mock.patch.object(
                root.os,
                "umask",
                side_effect=lambda value: calls.append(("umask", value)),
            ),
            mock.patch.object(
                root.os,
                "geteuid",
                return_value=root.REPOSITORY_OWNER_UID,
            ),
            mock.patch.object(
                root.os,
                "getegid",
                return_value=root.REPOSITORY_OWNER_GID,
            ),
            mock.patch.object(root.os, "getgroups", return_value=[]),
            mock.patch.object(
                root.os,
                "_exit",
                side_effect=AssertionError("drop verification unexpectedly failed"),
            ),
        ):
            root._git_child_preexec()
        self.assertEqual(
            calls[:4],
            [
                ("setrlimit", root.resource.RLIMIT_CORE, (0, 0)),
                ("setgroups", []),
                ("setgid", root.REPOSITORY_OWNER_GID),
                ("setuid", root.REPOSITORY_OWNER_UID),
            ],
        )

    def test_stage_root_nofollow_snapshots_never_read_rejected_symlinks(self) -> None:
        root = self.stage_root
        reader_calls = []
        inode = iter(range(100, 1000))

        def row(mode, *, uid=0, gid=0, size=1, nlink=1):
            return types.SimpleNamespace(
                st_mode=mode,
                st_uid=uid,
                st_gid=gid,
                st_nlink=nlink,
                st_size=size,
                st_dev=7,
                st_ino=next(inode),
                st_mtime_ns=11,
                st_ctime_ns=12,
            )

        repository_directories = {
            root.REPOSITORY_ROOT,
            root.REPOSITORY_ROOT + "/.git",
            root.REPOSITORY_ROOT + "/.git/objects",
            root.REPOSITORY_ROOT + "/.git/objects/info",
        }
        repository_absent = {
            root.REPOSITORY_ROOT + "/.git/shallow",
            root.REPOSITORY_ROOT + "/.git/commondir",
            root.REPOSITORY_ROOT + "/.git/worktrees",
            root.REPOSITORY_ROOT + "/.git/objects/info/alternates",
            root.REPOSITORY_ROOT + "/.git/objects/info/http-alternates",
        }

        def repository_lstat(path):
            if path in repository_absent:
                raise FileNotFoundError(path)
            if path in repository_directories:
                return row(
                    stat.S_IFDIR | 0o700,
                    uid=root.REPOSITORY_OWNER_UID,
                    gid=root.REPOSITORY_OWNER_GID,
                    size=0,
                    nlink=2,
                )
            if path.endswith("/.git/HEAD"):
                return row(
                    stat.S_IFLNK | 0o777,
                    uid=root.REPOSITORY_OWNER_UID,
                    gid=root.REPOSITORY_OWNER_GID,
                )
            raise AssertionError(path)

        with self.assertRaisesRegex(
            root.StageRootError,
            "^stage_root_repository$",
        ):
            root._repository_snapshot(
                lstater=repository_lstat,
                reader=lambda *args: reader_calls.append(args),
            )
        self.assertEqual(reader_calls, [])

        def oversize_repository_lstat(path):
            if path in repository_absent:
                raise FileNotFoundError(path)
            if path in repository_directories:
                return row(
                    stat.S_IFDIR | 0o700,
                    uid=root.REPOSITORY_OWNER_UID,
                    gid=root.REPOSITORY_OWNER_GID,
                    size=0,
                    nlink=2,
                )
            name = path.rsplit("/", 1)[-1]
            if name in root.REPOSITORY_METADATA_MAXIMUMS:
                size = (
                    root.REPOSITORY_METADATA_MAXIMUMS[name] + 1
                    if name == "config"
                    else 1
                )
                return row(
                    stat.S_IFREG | 0o644,
                    uid=root.REPOSITORY_OWNER_UID,
                    gid=root.REPOSITORY_OWNER_GID,
                    size=size,
                )
            raise AssertionError(path)

        with self.assertRaisesRegex(
            root.StageRootError,
            "^stage_root_repository$",
        ):
            root._repository_snapshot(
                lstater=oversize_repository_lstat,
                reader=lambda *args: reader_calls.append(args),
            )
        self.assertEqual(reader_calls, [])

        directory_names = {
            root.AUTHORITY_DIRECTORY: {"authority-root-v2.json"},
            root.RUNTIME_DIRECTORY: set(root.EXISTING_RUNTIME_NAMES),
            root.JOURNAL_DIRECTORY: set(),
            root.CUSTODY_DIRECTORY: set(root.CUSTODY_NAMES),
        }

        def existing_lstat(path):
            if path == root.NOTEAI_ROOT or path in directory_names:
                return row(stat.S_IFDIR | 0o700, size=0, nlink=2)
            if path in root.PUBLIC_EXISTING_BINDINGS:
                return row(stat.S_IFLNK | 0o777)
            raise AssertionError(path)

        with self.assertRaisesRegex(
            root.StageRootError,
            "^stage_root_existing_public$",
        ):
            root._snapshot_existing(
                lstater=existing_lstat,
                lister=lambda path: directory_names[path],
                reader=lambda *args: reader_calls.append(args),
            )
        self.assertEqual(reader_calls, [])

        capture = {
            name: (b"x", 0o600 if name.endswith("manifest.json") else 0o500)
            for name in root.CAPTURE_ORDER
        }
        materialize = {
            name: (b"x", 0o600 if name.endswith("manifest.json") else 0o500)
            for name in root.MATERIALIZE_ORDER
        }

        def new_lstat(path):
            if path in (root.CAPTURE_DIRECTORY, root.MATERIALIZE_DIRECTORY):
                return row(stat.S_IFDIR | 0o700, size=0, nlink=2)
            return row(stat.S_IFLNK | 0o777)

        with self.assertRaisesRegex(
            root.StageRootError,
            "^stage_root_new_inventory$",
        ):
            root._verify_new_partitions(
                capture,
                materialize,
                lstater=new_lstat,
                lister=lambda path: (
                    set(root.CAPTURE_ORDER)
                    if path == root.CAPTURE_DIRECTORY
                    else set(root.MATERIALIZE_ORDER)
                ),
                reader=lambda *args: reader_calls.append(args),
            )
        self.assertEqual(reader_calls, [])

    def test_stage_repository_snapshot_rejects_group_writable_git_metadata(self) -> None:
        stager = self.stager
        root = stager.REPOSITORY_ROOT
        directories = {
            root,
            root + "/.git",
            root + "/.git/objects",
            root + "/.git/objects/info",
        }
        files = {
            root + "/.git/HEAD": b"ref: refs/heads/main\n",
            root + "/.git/index": b"index",
            root + "/.git/config": b"config",
        }
        absent = {
            root + "/.git/shallow",
            root + "/.git/commondir",
            root + "/.git/worktrees",
            root + "/.git/objects/info/alternates",
            root + "/.git/objects/info/http-alternates",
        }
        reader_calls = []

        def row(mode, size=0):
            return types.SimpleNamespace(
                st_mode=mode,
                st_uid=501,
                st_gid=20,
                st_nlink=1,
                st_size=size,
                st_dev=7,
                st_ino=9,
            )

        def lstater(path):
            if path in absent:
                raise FileNotFoundError(path)
            if path in directories:
                return row(stat.S_IFDIR | 0o700)
            if path in files:
                mode = 0o660 if path.endswith("/config") else 0o644
                return row(stat.S_IFREG | mode, len(files[path]))
            raise AssertionError(path)

        with self.assertRaisesRegex(
            stager.StagerError,
            "^stage_repository$",
        ):
            stager._stage_repository_snapshot(
                lstater=lstater,
                reader=lambda *args: (
                    reader_calls.append(args) or files[str(args[0])]
                ),
            )
        self.assertEqual(reader_calls, [])

        def oversize_lstat(path):
            if path in absent:
                raise FileNotFoundError(path)
            if path in directories:
                return row(stat.S_IFDIR | 0o700)
            if path in files:
                size = (
                    stager.REPOSITORY_METADATA_MAXIMUMS["config"] + 1
                    if path.endswith("/config")
                    else len(files[path])
                )
                return row(stat.S_IFREG | 0o644, size)
            raise AssertionError(path)

        with self.assertRaisesRegex(
            stager.StagerError,
            "^stage_repository$",
        ):
            stager._stage_repository_snapshot(
                lstater=oversize_lstat,
                reader=lambda *args: reader_calls.append(args),
            )
        self.assertEqual(reader_calls, [])

    def test_4b_supervisors_use_internal_status_and_payload_signal_containment(self) -> None:
        for label, source, payload in (
            (
                "capture",
                self.stager.CAPTURE_EXEC_BOOTSTRAP,
                self.stager.CAPTURE_ROOT_PROGRAM,
            ),
            (
                "materialize",
                self.stager.MATERIALIZE_STDIO_BOOTSTRAP,
                self.stager.MATERIALIZE_ROOT_PROGRAM,
            ),
        ):
            with self.subTest(label=label):
                compile(source, "<" + label + "-supervisor>", "exec", optimize=0)
                compile(source, "<" + label + "-supervisor>", "exec", optimize=2)
                self.assertIn("socket.socketpair", source)
                self.assertIn("drain_payload_status", source)
                self.assertIn("emit_payload(payload_status)", source)
                self.assertIn(
                    "process.wait(timeout=NORMAL_WAIT_SECONDS)",
                    source,
                )
                self.assertIn("os.killpg(pid, signal.SIGTERM)", source)
                self.assertIn("os.killpg(pid, signal.SIGKILL)", source)
                self.assertLess(
                    source.index("os.killpg(pid, signal.SIGTERM)"),
                    source.index("os.killpg(pid, signal.SIGKILL)"),
                )
                self.assertIn("start_new_session=True", source)
                self.assertIn("canonical(value) != bytes(raw)", source)
                self.assertNotIn("bytes(raw) + b\"\\n\"", source)
                self.assertIn("GATE_CODE", source)
                self.assertIn("supervisor_ack", source)
                self.assertIn("payload_release_count", source)
                self.assertIn("os.getpgid(payload_pgid) != payload_pgid", source)
                self.assertLess(
                    source.index('"status": "READY"'),
                    source.index('os.write(gate_writer, b"G")'),
                )
                payload_sha256 = hashlib.sha256(
                    payload.encode("ascii")
                ).hexdigest()
                self.assertEqual(
                    source.count(
                        '"payload_program_sha256": "'
                        + payload_sha256
                        + '"'
                    ),
                    2,
                )

        capture = self.stager.CAPTURE_ROOT_PROGRAM
        materialize = self.stager.MATERIALIZE_ROOT_PROGRAM
        for signame in ("SIGTERM", "SIGINT", "SIGHUP", "SIGQUIT", "SIGALRM"):
            self.assertIn(signame, capture)
            self.assertIn(signame, materialize)
        self.assertIn("ACTIVE_ADAPTER_PROCESS", capture)
        self.assertIn("_install_capture_signal_handlers", capture)
        self.assertIn("ACTIVE_MATERIALIZE_PROCESS", materialize)
        self.assertIn("_install_materialize_signal_handlers", materialize)
        self.assertIn("_spawn_materialize_process", materialize)
        self.assertIn("_settle_materialize_process", materialize)

    def test_4b_nested_containment_deadlines_are_strictly_budgeted(self) -> None:
        stager = self.stager

        def literal_bindings(source):
            bindings = {}
            for node in ast.parse(source).body:
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    try:
                        bindings[node.targets[0].id] = ast.literal_eval(
                            node.value
                        )
                    except (ValueError, TypeError):
                        pass
            return bindings

        capture_supervisor = literal_bindings(stager.CAPTURE_EXEC_BOOTSTRAP)
        materialize_supervisor = literal_bindings(
            stager.MATERIALIZE_STDIO_BOOTSTRAP
        )
        for bindings, runtime_timeout in (
            (
                capture_supervisor,
                stager.CAPTURE_SUPERVISOR_RUNTIME_TIMEOUT_SECONDS,
            ),
            (
                materialize_supervisor,
                stager.MATERIALIZE_SUPERVISOR_RUNTIME_TIMEOUT_SECONDS,
            ),
        ):
            self.assertEqual(
                bindings["ACK_TIMEOUT_SECONDS"],
                stager.SUPERVISOR_ACK_TIMEOUT_SECONDS,
            )
            self.assertEqual(
                bindings["NORMAL_WAIT_SECONDS"],
                stager.SUPERVISOR_NORMAL_WAIT_SECONDS,
            )
            self.assertEqual(
                bindings["TERM_GRACE_SECONDS"],
                stager.SUPERVISOR_TERM_GRACE_SECONDS,
            )
            self.assertEqual(
                bindings["KILL_GRACE_SECONDS"],
                stager.SUPERVISOR_KILL_GRACE_SECONDS,
            )
            self.assertEqual(
                bindings["TERMINAL_EMIT_BUDGET_SECONDS"],
                stager.SUPERVISOR_TERMINAL_EMIT_BUDGET_SECONDS,
            )
            self.assertEqual(
                bindings["RUNTIME_TIMEOUT_SECONDS"], runtime_timeout
            )

        capture_bindings = literal_bindings(stager.CAPTURE_ROOT_PROGRAM)
        capture_inner = capture_bindings["CHILD_REAP_GRACE_SECONDS"]
        materialize_tree = ast.parse(stager.MATERIALIZE_ROOT_PROGRAM)
        materialize_settle = next(
            node
            for node in materialize_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_settle_process"
        )
        materialize_waits = []
        for node in ast.walk(materialize_settle):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "wait"
            ):
                timeout = next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "timeout"
                    ),
                    None,
                )
                if timeout is not None:
                    materialize_waits.append(ast.literal_eval(timeout))
        materialize_probe = next(
            node
            for node in materialize_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_prove_group_absent"
        )
        materialize_probe_defaults = {
            argument.arg: default
            for argument, default in zip(
                materialize_probe.args.kwonlyargs,
                materialize_probe.args.kw_defaults,
            )
        }
        materialize_probe_timeout = ast.literal_eval(
            materialize_probe_defaults["timeout"]
        )
        materialize_inner = max(materialize_waits) + materialize_probe_timeout

        self.assertLess(
            max(capture_inner, materialize_inner),
            stager.SUPERVISOR_TERM_GRACE_SECONDS,
        )
        supervisor_containment = (
            stager.SUPERVISOR_TERM_GRACE_SECONDS
            + stager.SUPERVISOR_KILL_GRACE_SECONDS
            + stager.SUPERVISOR_TERMINAL_EMIT_BUDGET_SECONDS
        )
        self.assertLess(
            supervisor_containment,
            stager.OUTER_TERMINATE_GRACE_SECONDS,
        )
        for runtime_timeout, sudo_timeout in (
            (
                stager.CAPTURE_SUPERVISOR_RUNTIME_TIMEOUT_SECONDS,
                stager.CAPTURE_SUDO_MONITOR_TIMEOUT_SECONDS,
            ),
            (
                stager.MATERIALIZE_SUPERVISOR_RUNTIME_TIMEOUT_SECONDS,
                stager.MATERIALIZE_SUDO_MONITOR_TIMEOUT_SECONDS,
            ),
        ):
            total = (
                stager.SUPERVISOR_ACK_TIMEOUT_SECONDS
                + runtime_timeout
                + stager.SUPERVISOR_NORMAL_WAIT_SECONDS
                + supervisor_containment
            )
            self.assertLess(total, sudo_timeout)
            self.assertGreaterEqual(sudo_timeout - total, 3)

    def test_4b_supervisor_normal_wait_and_term_escalation_are_bounded(self) -> None:
        for label, source in (
            ("capture", self.stager.CAPTURE_EXEC_BOOTSTRAP),
            ("materialize", self.stager.MATERIALIZE_STDIO_BOOTSTRAP),
        ):
            tree = ast.parse(source)
            settle_node = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "settle"
            )
            namespace = {
                "os": os,
                "signal": self.stager.signal,
                "time": types.SimpleNamespace(
                    monotonic=lambda: 0.0,
                    sleep=lambda _seconds: None,
                ),
            }
            for node in tree.body:
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    try:
                        namespace[node.targets[0].id] = ast.literal_eval(
                            node.value
                        )
                    except (ValueError, TypeError):
                        pass
            exec(
                compile(
                    ast.fix_missing_locations(
                        ast.Module(body=[settle_node], type_ignores=[])
                    ),
                    "<" + label + "-settle>",
                    "exec",
                ),
                namespace,
            )
            settle = namespace["settle"]

            class NormalProcess:
                pid = 91
                returncode = None

                def poll(self):
                    return None

                def wait(self, *, timeout):
                    self.returncode = 0
                    return 0

            calls = []
            with mock.patch.object(
                os,
                "killpg",
                side_effect=lambda pid, signum: (
                    calls.append((pid, signum))
                    or (_ for _ in ()).throw(ProcessLookupError())
                ),
            ):
                self.assertEqual(settle(NormalProcess(), False), 0)
            self.assertEqual(calls, [(91, 0)])

            class SlowProcess:
                pid = 92
                returncode = None

                def __init__(self):
                    self.waits = 0

                def poll(self):
                    return self.returncode

                def wait(self, *, timeout):
                    self.waits += 1
                    if self.waits == 1:
                        raise TimeoutError()
                    self.returncode = 78
                    return 78

            calls = []
            def killpg(pid, signum):
                calls.append((pid, signum))
                if signum == 0:
                    raise ProcessLookupError()
            with mock.patch.object(os, "killpg", side_effect=killpg):
                self.assertEqual(settle(SlowProcess(), False), 78)
            self.assertEqual(
                calls,
                [(92, self.stager.signal.SIGTERM), (92, 0)],
            )

    def test_4b_outer_second_signal_waits_for_containment_proof(self) -> None:
        stager = self.stager

        class Process:
            pid = 777

        runtime_arguments = (
            "c" * 40,
            "1",
            "a" * 64,
            "d" * 40,
            "1",
            "b" * 64,
            "1",
            "c" * 64,
            "1",
            "d" * 64,
        )

        for label in ("capture", "materialize"):
            with self.subTest(label=label):
                order = []
                duplicated_stdio = []

                def drain(
                    _process,
                    channels,
                    _limits,
                    *,
                    readiness_state,
                    output_state,
                    **_kwargs,
                ):
                    order.append("first_failure")
                    ready = stager._supervisor_ready_frame(
                        payload_mode=label.upper(),
                        payload_program_sha256=(
                            hashlib.sha256(
                                (
                                    stager.CAPTURE_ROOT_PROGRAM
                                    if label == "capture"
                                    else stager.MATERIALIZE_ROOT_PROGRAM
                                ).encode("ascii")
                            ).hexdigest()
                        ),
                    )
                    readiness_state.update(json.loads(ready))
                    output_state.update(
                        {name: bytearray() for name in channels}
                    )
                    output_state["status"].extend(ready)
                    raise KeyboardInterrupt("first")

                def cancel(*_args, **_kwargs):
                    order.append("cancel")
                    return True

                def settle(*_args, **_kwargs):
                    order.append("settle")
                    return {
                        "reaped": True,
                        "returncode": 78,
                        "terminate_sent": False,
                        "kill_sent": False,
                    }

                def prove(_readiness):
                    order.append("absence")
                    return True

                def mask(how, _values):
                    if how == stager.signal.SIG_BLOCK:
                        order.append("block")
                        return "previous"
                    self.assertEqual(how, stager.signal.SIG_SETMASK)
                    order.append("restore")
                    raise KeyboardInterrupt("second")

                def popen(*_args, **options):
                    if label == "materialize":
                        for name in ("stdin", "stdout", "stderr"):
                            descriptor = options[name]
                            duplicated_stdio.append(os.dup(descriptor))
                    return Process()

                with mock.patch.object(
                    stager,
                    "_drain_output_channels_to_eof",
                    side_effect=drain,
                ), mock.patch.object(
                    stager,
                    "_cancel_and_drain_for_containment",
                    side_effect=cancel,
                ):
                    with self.assertRaisesRegex(
                        KeyboardInterrupt,
                        "second",
                    ):
                        if label == "capture":
                            stager._dispatch_capture_root_once(
                                stager._build_capture_runtime_arguments(
                                    "d" * 40
                                ),
                                tool_snapshot={"tool": True},
                                tool_snapshot_reader=lambda: {
                                    "tool": True
                                },
                                popen=popen,
                                settler=settle,
                                signal_masker=mask,
                                absence_prover=prove,
                            )
                        else:
                            stager._dispatch_materialize_root_once(
                                runtime_arguments,
                                tool_snapshot={"tool": True},
                                tool_snapshot_reader=lambda: {
                                    "tool": True
                                },
                                popen=popen,
                                settler=settle,
                                signal_masker=mask,
                                absence_prover=prove,
                            )
                self.assertEqual(
                    order,
                    [
                        "first_failure",
                        "block",
                        "cancel",
                        "settle",
                        "absence",
                        "restore",
                    ],
                )
                for descriptor in duplicated_stdio:
                    os.close(descriptor)

    def test_4b_drain_buffers_cross_socket_output_until_partial_ready_completes(self) -> None:
        stager = self.stager
        ready = stager._supervisor_ready_frame()
        ready_value = json.loads(ready)
        payload = stager.canonical_bytes({"payload": "ok"})
        terminal = stager.canonical_bytes(
            {
                "schema": stager.ROOT_PAYLOAD_SUPERVISOR_SCHEMA,
                "status": "PAYLOAD_GROUP_ABSENT",
                "payload_started": True,
                "payload_released": True,
                "supervisor_pid": ready_value["supervisor_pid"],
                "payload_pgid": ready_value["payload_pgid"],
                "payload_release_count": 1,
                "payload_mode": ready_value["payload_mode"],
                "payload_program_sha256": ready_value[
                    "payload_program_sha256"
                ],
                "pre_release_action_count": 0,
                "payload_returncode": 0,
                "group_absent": True,
                "automatic_retry_count": 0,
                "cleanup_count": 0,
                "raw_value_emitted_count": 0,
            }
        )

        class Channel:
            def __init__(self, name, chunks):
                self.name = name
                self.chunks = list(chunks)

            def setblocking(self, value):
                self.blocking = value

            def recv(self, _maximum):
                return self.chunks.pop(0)

            def send(self, raw):
                self.sent = getattr(self, "sent", b"") + raw
                return len(raw)

        receipt = Channel("receipt", [b"receipt", b""])
        evidence = Channel("evidence", [b"evidence", b""])
        status = Channel(
            "status",
            [ready[:7], ready[7:] + payload + terminal, b""],
        )
        channels = {
            "receipt": receipt,
            "evidence": evidence,
            "status": status,
        }

        class Selector:
            def __init__(self):
                self.registered = {}
                self.batches = [
                    ("receipt", "status"),
                    ("evidence", "status"),
                    ("receipt", "evidence", "status"),
                ]

            def register(self, channel, _events, name):
                self.registered[name] = channel

            def unregister(self, channel):
                self.registered.pop(channel.name, None)

            def select(self, _timeout):
                names = self.batches.pop(0)
                return [
                    (
                        types.SimpleNamespace(
                            data=name,
                            fileobj=self.registered[name],
                        ),
                        stager.selectors.EVENT_READ,
                    )
                    for name in names
                    if name in self.registered
                ]

            def close(self):
                pass

        result = stager._drain_output_channels_to_eof(
            types.SimpleNamespace(poll=lambda: None),
            channels,
            {"receipt": 32, "evidence": 32, "status": 4096},
            hard_timeout=10,
            authentication_timeout=10,
            readiness_role="status",
            readiness_frame=ready,
            selector_factory=Selector,
        )
        self.assertEqual(result["receipt"], b"receipt")
        self.assertEqual(result["evidence"], b"evidence")
        self.assertEqual(result["status"], ready + payload + terminal)
        self.assertEqual(status.sent, b"A")
        self.assertEqual(stager._unwrap_supervised_status(result["status"]), payload)

    def test_4b_failure_cancel_drains_before_pid_and_pgid_absence_proof(self) -> None:
        stager = self.stager
        readiness = json.loads(stager._supervisor_ready_frame(301, 302))
        probes = []

        def absent(identifier, signum):
            probes.append((identifier, signum))
            raise ProcessLookupError()

        self.assertIs(
            stager._prove_root_supervisor_absent(
                readiness,
                kill=absent,
                killpg=absent,
                sleep=lambda _seconds: None,
            ),
            True,
        )
        self.assertEqual(
            probes,
            [(301, 0), (302, 0), (301, 0), (302, 0)],
        )
        self.assertIs(
            stager._prove_root_supervisor_absent(
                readiness,
                kill=lambda *_args: (_ for _ in ()).throw(PermissionError()),
                killpg=absent,
                sleep=lambda _seconds: None,
            ),
            False,
        )

        events = []
        class Channel:
            def __init__(self, name):
                self.name = name

            def setblocking(self, value):
                events.append((self.name, "blocking", value))

            def send(self, raw):
                events.append((self.name, "send", raw))
                return len(raw)

            def shutdown(self, how):
                events.append((self.name, "shutdown", how))

            def recv(self, _maximum):
                events.append((self.name, "recv"))
                return b""

        channels = {name: Channel(name) for name in ("receipt", "evidence", "status")}
        class Selector:
            def __init__(self):
                self.rows = {}

            def register(self, channel, _mask, name):
                self.rows[name] = channel

            def unregister(self, channel):
                self.rows.pop(channel.name, None)

            def select(self, _timeout):
                return [
                    (
                        types.SimpleNamespace(fileobj=channel, data=name),
                        stager.selectors.EVENT_READ,
                    )
                    for name, channel in list(self.rows.items())
                ]

            def close(self):
                pass

        self.assertIs(
            stager._cancel_and_drain_for_containment(
                channels,
                {name: bytearray() for name in channels},
                {name: 1024 for name in channels},
                readiness,
                readiness_role="status",
                selector_factory=Selector,
            ),
            True,
        )
        self.assertEqual(events[0], ("status", "send", b"C"))
        self.assertEqual(events[1], ("status", "shutdown", socket.SHUT_WR))

    def test_4b_materialize_public_fds_never_reuse_standard_descriptors(self) -> None:
        stager = self.stager
        parent = (1, 2, stat.S_IFDIR | 0o700, os.geteuid(), os.getegid(), 2)
        for descriptor in (0, 1, 2):
            closed = []
            with self.subTest(descriptor=descriptor):
                with self.assertRaisesRegex(
                    stager.StagerError,
                    "^materialize_public_fd$",
                ):
                    stager._precreate_one_materialize_output(
                        stager.MATERIALIZE_PUBLIC_PATHS[0],
                        parent,
                        opener=lambda *_args, value=descriptor: value,
                        closer=closed.append,
                    )
                self.assertEqual(closed, [descriptor])
            closed = []
            with self.subTest(parent_descriptor=descriptor):
                with self.assertRaisesRegex(
                    stager.StagerError,
                    "^materialize_public_parent_fd$",
                ):
                    stager._fsync_materialize_parent(
                        str(Path(stager.MATERIALIZE_PUBLIC_PATHS[0]).parent),
                        opener=lambda *_args, value=descriptor: value,
                        closer=closed.append,
                    )
                self.assertEqual(closed, [descriptor])

    def test_4b_capsule_count_and_validity_fields_require_exact_ints(self) -> None:
        stager = self.stager
        valid = {
            "schema": stager.CAPTURE_CREDENTIAL_CAPSULE_SCHEMA,
            "status": "ROOT_CUSTODY_TEMPORARY_STS_READY",
            "account_binding_sha256": "a" * 64,
            "minimum_remaining_validity_seconds": (
                stager.INITIAL_MINIMUM_STS_VALIDITY_SECONDS
            ),
            "credential_payload_exposed": False,
            "oauth_refresh_count": 0,
            "oauth_configure_count": 0,
        }
        self.assertEqual(stager._validate_capture_credential_capsule(valid), valid)
        for key, value in (
            ("minimum_remaining_validity_seconds", float(stager.INITIAL_MINIMUM_STS_VALIDITY_SECONDS)),
            ("oauth_refresh_count", False),
            ("oauth_configure_count", 0.0),
        ):
            changed = dict(valid)
            changed[key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(
                    stager.StagerError,
                    "^capture_credential_capsule$",
                ):
                    stager._validate_capture_credential_capsule(changed)

        dependencies = []
        with mock.patch.object(
            stager,
            "_stage_system_tool_snapshot",
            side_effect=lambda: dependencies.append("tools"),
        ), mock.patch.object(
            stager,
            "_stage_repository_snapshot",
            side_effect=lambda: dependencies.append("repository"),
        ), mock.patch.object(
            stager,
            "_stage_topology_snapshot",
            side_effect=lambda *_args: dependencies.append("topology"),
        ):
            with self.assertRaisesRegex(
                stager.StagerError,
                "^capture_credential_capsule$",
            ):
                stager._default_future_capture(
                    "c" * 40,
                    "d" * 40,
                    credential_capsule_probe=lambda: {"malformed": True},
                )
        self.assertEqual(dependencies, [])

    def test_4b_materialize_write_order_residue_and_durable_close_terminal(self) -> None:
        stager = self.stager
        receipt_raw = stager.canonical_bytes({"schema": stager.M1_RECEIPT_SCHEMA})
        evidence_raw = stager.canonical_bytes({"schema": stager.M1_EVIDENCE_SCHEMA})
        child = {key: 0 for key in stager.MATERIALIZE_CHILD_SUCCESS_KEYS}
        child.update(
            {
                "schema": stager.MATERIALIZE_CHILD_STATUS_SCHEMA,
                "status": "RECEIPT_AND_EVIDENCE_BUILT_AND_VERIFIED",
                "receipt_build_count": 1,
                "evidence_build_count": 1,
                "receipt_validation_count": 3,
                "evidence_validation_count": 2,
            }
        )
        status_raw = stager.canonical_bytes(child)
        held = (
            (31, {"path": stager.MATERIALIZE_PUBLIC_PATHS[0], "file": (1, 11)}),
            (32, {"path": stager.MATERIALIZE_PUBLIC_PATHS[1], "file": (1, 12)}),
        )

        class Verifier:
            def validate_receipt(self, _value, *, expected_control_revision):
                self.assert_revision = expected_control_revision
                return [], "accepted"

            def validate_evidence(self, *_args, **_kwargs):
                return []

        def run_with_writer(
            writer,
            closer=lambda _fd: None,
            commit_state=None,
        ):
            return stager._future_materialize_once(
                "c" * 40,
                "d" * 40,
                precreator=lambda: held,
                capture_capsule_supplier=lambda: {"capsule": True},
                runtime_arguments_builder=lambda *_args: ("runtime",),
                dispatcher=lambda _args: {
                    "receipt": receipt_raw,
                    "evidence": evidence_raw,
                    "status": status_raw,
                },
                verifier_loader=Verifier,
                output_writer=writer,
                identity_checker=lambda *_args, **_kwargs: None,
                closer=closer,
                commit_state=commit_state,
            )

        writes = []
        commit_state = {}
        result = run_with_writer(
            lambda fd, _identity, _raw, *, maximum: writes.append((fd, maximum)),
            closer=lambda _fd: (_ for _ in ()).throw(OSError("close")),
            commit_state=commit_state,
        )
        self.assertEqual(result["status"], "M1_RECEIPT_AND_EVIDENCE_MATERIALIZED")
        self.assertEqual([row[0] for row in writes], [31, 32])
        self.assertEqual(commit_state["durable_result"], result)

        writes.clear()
        failed_commit_state = {}
        def fail_first(fd, _identity, _raw, *, maximum):
            writes.append(fd)
            raise OSError("first")
        with self.assertRaisesRegex(OSError, "first"):
            run_with_writer(fail_first, commit_state=failed_commit_state)
        self.assertEqual(writes, [31])
        self.assertEqual(failed_commit_state, {})

        writes.clear()
        failed_commit_state = {}
        def fail_second(fd, _identity, _raw, *, maximum):
            writes.append(fd)
            if fd == 32:
                raise OSError("second")
        with self.assertRaisesRegex(OSError, "second"):
            run_with_writer(fail_second, commit_state=failed_commit_state)
        self.assertEqual(writes, [31, 32])
        self.assertEqual(failed_commit_state, {})

        pending_commit_state = {}
        masks = []
        def pending_signal_mask(how, values):
            masks.append((how, values))
            if len(masks) == 2:
                raise KeyboardInterrupt()
            return "previous"
        with mock.patch.object(
            stager.signal,
            "pthread_sigmask",
            side_effect=pending_signal_mask,
        ):
            with self.assertRaises(KeyboardInterrupt):
                run_with_writer(
                    lambda *_args, **_kwargs: None,
                    commit_state=pending_commit_state,
                )
        self.assertEqual(
            pending_commit_state["durable_result"]["status"],
            "M1_RECEIPT_AND_EVIDENCE_MATERIALIZED",
        )

        order = []
        closed = []
        with self.assertRaisesRegex(
            stager.StagerError,
            "^materialize_capture_interface_not_provisioned$",
        ):
            stager._future_materialize_once(
                "c" * 40,
                "d" * 40,
                precreator=lambda: (
                    order.append("precreate") or held
                ),
                capture_capsule_supplier=lambda: (
                    order.append("capsule")
                    or (_ for _ in ()).throw(
                        stager.StagerError(
                            "materialize_capture_interface_not_provisioned"
                        )
                    )
                ),
                runtime_arguments_builder=lambda *_args: (
                    order.append("arguments")
                ),
                dispatcher=lambda _args: order.append("dispatch"),
                verifier_loader=lambda: order.append("verifier"),
                identity_checker=lambda *_args, **_kwargs: None,
                closer=closed.append,
            )
        self.assertEqual(order, ["precreate", "capsule"])
        self.assertEqual(closed, [31, 32])

    def test_4b_frozen_outer_verifier_rejects_all_io_and_process_effects(self) -> None:
        stager = self.stager

        class Evidence:
            def validate_receipt(self, *_args, **_kwargs):
                open(TARGET, "rb")

            def validate_evidence(self, *_args, **_kwargs):
                subprocess.run(["/usr/bin/git", "status"], check=False)

        verifier = stager._FrozenOuterVerifier({}, Evidence())
        with self.assertRaisesRegex(
            stager.StagerError,
            "^materialize_outer_verifier_guard$",
        ):
            verifier.validate_receipt({})
        with self.assertRaisesRegex(
            stager.StagerError,
            "^materialize_outer_verifier_guard$",
        ):
            verifier.validate_evidence({})

        names = {
            "extract_item26_manual_cost_stop_raw_v2",
            "verify_item26_manual_cost_stop_authority_v2",
            "verify_item26_manual_cost_stop_evidence_v2",
        }
        before = {name: sys.modules.get(name) for name in names}
        fixture = self._make_stage_fixture()
        git_reads = []

        def git_reader(revision, ref):
            git_reads.append((revision, ref))
            return fixture.git_reader(revision, ref)

        loaded = stager._load_outer_evidence_verifier(git_reader=git_reader)
        self.assertIsInstance(loaded, stager._FrozenOuterVerifier)
        self.assertEqual(
            git_reads,
            [
                (
                    stager.FIXED_BINDINGS[ref]["revision"],
                    ref,
                )
                for ref in (
                    stager.EXTRACTOR_REF,
                    stager.AUTHORITY_VERIFIER_REF,
                    stager.EVIDENCE_VERIFIER_REF,
                )
            ],
        )
        self.assertEqual(
            {name: sys.modules.get(name) for name in names},
            before,
        )

    def test_4b_materialize_pending_signal_during_spawn_is_self_contained(self) -> None:
        materialize = self.materialize
        process = types.SimpleNamespace(pid=991)
        masks = []
        settled = []

        def mask(how, values):
            masks.append((how, values))
            if len(masks) == 2:
                raise materialize.MaterializeSignal()
            return "previous"

        with mock.patch.object(materialize.signal, "pthread_sigmask", side_effect=mask), mock.patch.object(
            materialize,
            "_settle_process",
            side_effect=lambda value, force_kill: (
                settled.append((value, force_kill)) or 78
            ),
        ):
            with self.assertRaises(materialize.MaterializeSignal):
                materialize._spawn_materialize_process(
                    lambda *_args, **_kwargs: process,
                    ["/usr/bin/git"],
                )
        self.assertEqual(settled, [(process, True)])
        self.assertIsNone(materialize.ACTIVE_MATERIALIZE_PROCESS)

    def test_4b_durable_materialize_commit_cannot_be_reversed_by_cli_status_loss(self) -> None:
        stager = self.stager
        result = {
            "schema": stager.MATERIALIZE_OUTER_RESULT_SCHEMA,
            "status": "M1_RECEIPT_AND_EVIDENCE_MATERIALIZED",
        }

        def committed_then_signal(_source, _acceptance, *, commit_state):
            commit_state["durable_result"] = dict(result)
            raise KeyboardInterrupt()

        output = types.SimpleNamespace(buffer=io.BytesIO())
        with mock.patch.object(stager, "EXECUTION_ENABLED", True), mock.patch.object(
            stager,
            "_default_future_materialize",
            side_effect=committed_then_signal,
        ), mock.patch.object(stager.sys, "stdout", output):
            self.assertEqual(
                stager.main(["--materialize", "c" * 40, "d" * 40]),
                0,
            )
        self.assertEqual(output.buffer.getvalue(), b"")

        class BrokenBuffer:
            def __init__(self):
                self.write_count = 0
                self.flush_count = 0

            def write(self, _raw):
                self.write_count += 1
                raise BrokenPipeError("status lost")

            def flush(self):
                self.flush_count += 1
                raise BrokenPipeError("status lost")

        broken = BrokenBuffer()
        def committed_then_return(_source, _acceptance, *, commit_state):
            commit_state["durable_result"] = dict(result)
            return dict(result)

        with mock.patch.object(stager, "EXECUTION_ENABLED", True), mock.patch.object(
            stager,
            "_default_future_materialize",
            side_effect=committed_then_return,
        ), mock.patch.object(
            stager.sys,
            "stdout",
            types.SimpleNamespace(buffer=broken),
        ):
            self.assertEqual(
                stager.main(["--materialize", "c" * 40, "d" * 40]),
                0,
            )
        self.assertEqual(broken.write_count, 1)
        self.assertEqual(broken.flush_count, 0)

    def test_root_payloads_are_physically_distinct_and_materialize_has_no_transport_surface(self) -> None:
        capture = self.stager.CAPTURE_ROOT_PROGRAM
        materialize = self.stager.MATERIALIZE_ROOT_PROGRAM
        self.assertNotEqual(capture, materialize)
        self.assertNotEqual(
            hashlib.sha256(capture.encode("ascii")).hexdigest(),
            hashlib.sha256(materialize.encode("ascii")).hexdigest(),
        )
        capture_tree = ast.parse(capture)
        materialize_tree = ast.parse(materialize)
        capture_imports = {
            alias.name
            for node in ast.walk(capture_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        materialize_imports = {
            alias.name
            for node in ast.walk(materialize_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertEqual(
            capture_imports,
            {
                "fcntl",
                "hashlib",
                "json",
                "math",
                "os",
                "resource",
                "selectors",
                "signal",
                "socket",
                "stat",
                "subprocess",
                "sys",
                "time",
            },
        )
        self.assertEqual(
            materialize_imports,
            {
                "ast",
                "fcntl",
                "hashlib",
                "json",
                "os",
                "pathlib",
                "resource",
                "selectors",
                "signal",
                "socket",
                "stat",
                "subprocess",
                "sys",
                "time",
            },
        )
        lowered = materialize.lower()
        for forbidden in ("af_inet", "http", "oauth", "adapter"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)

    def test_both_root_payload_future_functions_gate_before_argument_access(self) -> None:
        for label, source, function_name in (
            ("capture", self.stager.CAPTURE_ROOT_PROGRAM, "future_capture"),
            (
                "materialize",
                self.stager.MATERIALIZE_ROOT_PROGRAM,
                "future_materialize",
            ),
        ):
            with self.subTest(label=label):
                module = types.ModuleType("item26_" + label + "_root_gate_test")
                exec(
                    compile(source, "<item26-m1-" + label + ">", "exec"),
                    module.__dict__,
                )
                self.assertIs(module.EXECUTION_ENABLED, False)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^future_execution_disabled$",
                ):
                    getattr(module, function_name)(ExplodingArgument())
                self.assertEqual(
                    module.STATUS["status"],
                    "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED",
                )
                self.assertIs(module.STATUS["authorizes_execution"], False)
                self.assertIs(module.STATUS["implementation_complete"], True)
                self.assertIs(module.STATUS["operational_ready"], False)
                self.assertEqual(module.STATUS["authorized_cny"], "0.00")
                self.assertEqual(module.STATUS["incurred_cny"], "0.00")
                for key in (
                    "cloud_write_count",
                    "database_connection_count",
                    "database_transaction_count",
                    "database_write_count",
                    "private_key_read_count",
                    "private_key_write_count",
                    "private_key_output_count",
                ):
                    self.assertEqual(module.STATUS[key], 0)
                credential_prefix = "oauth" if label == "capture" else "credential"
                self.assertEqual(
                    module.STATUS[credential_prefix + "_configuration_count"],
                    0,
                )
                self.assertEqual(
                    module.STATUS[credential_prefix + "_refresh_count"],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
