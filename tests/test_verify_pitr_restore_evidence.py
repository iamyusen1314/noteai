import copy
import contextlib
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
MODEL = ROOT / "model"
for path in (TOOLS, MODEL):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import storage_recovery_evidence as recovery  # noqa: E402
import validate_item26_pitr_restore_result_v1 as result_validator  # noqa: E402
import verify_pitr_restore_evidence as verifier  # noqa: E402
from build_item26_pitr_restore_evidence_v1 import (  # noqa: E402
    build_evidence,
    build_receipt,
)


EXECUTION_REVISION = "1860ab5ca1f3eb2e0dc7f90b97a956224895f341"
H = "1" * 64


def abort_dependency():
    value = {
        "schema": verifier.ABORT_DEPENDENCY_SCHEMA,
        "authority_root": "",
        "verifier_path": "tools/verify_item26_cost_containment_abort_evidence_v1.py",
        "verifier_sha256": "1" * 64,
        "validator_path": "tools/validate_item26_cost_containment_abort_result_v1.py",
        "validator_sha256": "e" * 64,
        "builder_path": "tools/build_item26_cost_containment_abort_evidence_v1.py",
        "builder_sha256": "f" * 64,
        "evidence_path": verifier.ABORT_EVIDENCE_REF,
        "evidence_sha256": "2" * 64,
        "receipt_path": verifier.ABORT_RECEIPT_REF,
        "receipt_sha256": "3" * 64,
        "checkpoint_path": verifier.ABORT_CHECKPOINT_REF,
        "checkpoint_sha256": "4" * 64,
        "authority_root_file_sha256": "5" * 64,
        "authority_bundle_file_sha256": "6" * 64,
        "raw_closure_file_sha256": "7" * 64,
        "confirmation_envelope_file_sha256": "8" * 64,
        "terminal_acceptance_sha256": "9" * 64,
        "old_clone_sha256": "a" * 64,
        "billing_closure_sha256": "b" * 64,
        "resource_disposition_sha256": "c" * 64,
        "no_replay_registry_sha256": "d" * 64,
        "old_clone_create_request_sha256": "0" * 64,
        "old_clone_create_body_sha256": "1" * 64,
        "old_clone_client_token_sha256": "2" * 64,
        "old_clone_name_sha256": "3" * 64,
        "abort_terminal_observed_at_utc": "2026-08-16T00:00:00Z",
        "execution_revision": "1" * 40,
        "evidence_revision": "2" * 40,
        "terminal_revision": "3" * 40,
    }
    value["authority_root"] = verifier.abort_dependency_authority_root(value)
    return value


def manifest():
    value = {
        "contract_version": recovery.CONTRACT_VERSION,
        "generated_at": "2026-08-16T00:00:00+00:00",
        "release_commit": EXECUTION_REVISION,
        "database": {
            "engine": "postgresql",
            "schema_sha256": "2" * 64,
            "table_count": 56,
            "tables": {
                name: {
                    "row_count": index,
                    "rowset_sha256": f"{index + 1:064x}",
                }
                for index, name in enumerate(result_validator.EXPECTED_TABLES)
            },
            "migrations": [
                {
                    "version": version,
                    "sha256": sha256,
                }
                for version, sha256 in result_validator.EXPECTED_MIGRATIONS
            ],
            "references": {
                "ai_payload_refs": {
                    "present": True,
                    "total_count": 0,
                    "states": {},
                },
                "private_media_refs": {
                    "present": True,
                    "total_count": 0,
                    "states": {},
                },
            },
        },
        "objects": {
            "object_count": 0,
            "size_bytes": 0,
            "aggregate_sha256": recovery._sha(b""),
            "content_included": False,
            "object_keys_included": False,
        },
        "privacy": {
            "row_values_included": False,
            "object_content_included": False,
            "object_keys_included": False,
            "user_identifiers_included": False,
        },
    }
    value["manifest_sha256"] = recovery._sha(recovery._canonical_json(value))
    return value


def capture(manifest_sha256):
    return {
        "manifest_sha256": manifest_sha256,
        "postgresql_major_version": 16,
        "server_version_num": 160010,
        "table_count": 56,
        "migration_count": 17,
        "rls_table_count": 19,
        "rls_tables": list(result_validator.EXPECTED_RLS_TABLES),
        "force_rls_table_count": 0,
        "force_rls_tables": [],
        "owner_role": "noteai_admin",
        "owner_mismatch_count": 0,
        "reader_role_sha256": "f" * 64,
        "reader_superuser": False,
        "reader_can_login": True,
        "reader_direct_membership_count": 1,
        "reader_member_of_managed_role": True,
        "reader_can_set_owner_role": True,
        "managed_role_can_set_owner_role": True,
        "session_identity_matches_reader_before_set_role": True,
        "active_role": "noteai_admin",
        "public_schema_usage": True,
        "search_path": "pg_catalog, public",
        "row_security": "off",
        "database_connection_count": 1,
        "database_transaction_count": 1,
        "transaction_read_only": True,
        "transaction_isolation": "repeatable read",
        "default_transaction_read_only": True,
        "rollback_terminal_idle": True,
        "database_write_count": 0,
        "object_read_mode": "LIST_HEAD_ONLY",
        "object_list_count": 1,
        "object_head_count": 0,
        "object_content_read_count": 0,
        "object_key_emitted_count": 0,
        "object_get_content_count": 0,
        "object_put_count": 0,
        "object_delete_count": 0,
        "object_acl_mutation_count": 0,
        "object_multipart_mutation_count": 0,
        "content_included": False,
        "object_keys_included": False,
        "secret_values_included": False,
    }


def action(name, index):
    digest = f"{index + 300:064x}"
    return {
        "name": name,
        "target_sha256": digest,
        "request_sha256": digest,
        "response_sha256": digest,
        "provider_request_id_sha256": digest,
        "provider_execution_id_sha256": digest,
        "client_token_sha256": digest,
        "terminal_status": "PASS",
        "exit_code": 0,
        "repeat_count": 1,
        "drop_count": 0,
        "prehistory_count": 0,
        "posthistory_count": 1,
        "automatic_retry_allowed": False,
        "manual_resend_count": 0,
    }


def receipt_candidate():
    source = manifest()
    tree_sha256, tracked_file_count = verifier.git_tree_binding(
        EXECUTION_REVISION,
        root=ROOT,
    )
    source_capture = capture(source["manifest_sha256"])
    restored_capture = copy.deepcopy(source_capture)
    value = {
        "schema_version": 1,
        "schema": verifier.RECEIPT_SCHEMA,
        "task_id": verifier.TASK_ID,
        "status": "PROVIDER_TERMINAL_VERIFIED_CLEAN",
        "observed_at_utc": "2026-08-16T00:10:00Z",
        "source_revision": EXECUTION_REVISION,
        "source_binding": {
            "revision": EXECUTION_REVISION,
            "tree_sha256": tree_sha256,
            "tracked_file_count": tracked_file_count,
            "dirty_path_count": 0,
        },
        "abort_dependency": abort_dependency(),
        "provider_identity": {
            "source_rds_sha256": "5" * 64,
            "successor_clone_sha256": "6" * 64,
            "successor_clone_name_sha256": "d" * 64,
            "successor_clone_create_request_sha256": "e" * 64,
            "successor_clone_create_body_sha256": "f" * 64,
            "successor_clone_client_token_sha256": "4" * 64,
            "successor_clone_identity_set_sha256": "0" * 64,
            "builder_sha256": "7" * 64,
            "restore_time_sha256": "8" * 64,
            "region_sha256": "9" * 64,
            "vpc_sha256": "a" * 64,
            "vswitch_set_sha256": "b" * 64,
            "postgresql_major_version": 16,
            "private_endpoint_count": 1,
            "public_endpoint_count": 0,
            "source_clone_distinct": True,
        },
        "raw_closure": {
            "provider_response_set_sha256": "c" * 64,
            "command_history_sha256": "d" * 64,
            "sendfile_history_sha256": "e" * 64,
            "billing_readback_sha256": "f" * 64,
            "account_inventory_sha256": "1" * 64,
            "network_inventory_sha256": "2" * 64,
            "successor_clone_identity_set_sha256": "0" * 64,
            "fee_authorization_sha256": "7" * 64,
            "raw_payload_retained_in_repository": False,
            "secret_value_emitted_count": 0,
        },
        "ordered_actions": [
            action(name, index)
            for index, name in enumerate(verifier.EXPECTED_ACTIONS)
        ],
        "source_capture": source_capture,
        "restored_capture": restored_capture,
        "reconciliation": {
            "verified": True,
            "mismatch_codes": [],
            "source_manifest_sha256": source["manifest_sha256"],
            "restored_manifest_sha256": source["manifest_sha256"],
            "equal_fields": [
                "release_commit",
                "database_engine",
                "database_schema",
                "database_migrations",
                "database_tables",
                "database_references",
                "private_objects",
            ],
            "content_included": False,
        },
        "cleanup": {
            "successor_clone_absent": True,
            "clone_billing_closed": True,
            "builder_stopped_stop_charging": True,
            "temporary_account_count": 0,
            "ram_role_count": 0,
            "ram_policy_count": 0,
            "ram_attachment_count": 0,
            "task_vswitch_count": 0,
            "temporary_reader_count": 0,
            "key_residue_count": 0,
            "envelope_residue_count": 0,
            "host_residue_count": 0,
            "container_residue_count": 0,
            "process_residue_count": 0,
            "source_rds_unchanged": True,
            "source_rds_deleted": False,
            "shared_builder_deleted": False,
        },
        "cost_boundary": {
            "currency": "CNY",
            "approved_cap_cny": "10.000000",
            "fee_authorization_cap_cny": "10.000000",
            "fee_authorization_sha256": "7" * 64,
            "fee_confirmation_sha256": "8" * 64,
            "fee_authorization_nonce_sha256": "9" * 64,
            "fee_authorization_issued_at_utc": "2026-08-16T00:00:01Z",
            "fee_authorization_approved_at_utc": "2026-08-16T00:00:01Z",
            "fee_authorization_expires_at_utc": "2026-08-16T00:05:00Z",
            "clone_create_started_at_utc": "2026-08-16T00:00:02Z",
            "fee_authorization_postdates_abort": True,
            "actual_incremental_cny": "5.000000",
            "rds_incremental_cny": "4.000000",
            "builder_incremental_cny": "1.000000",
            "disk_incremental_cny": "0",
            "other_incremental_cny": "0",
            "attribution_proven": True,
            "noncleanup_paid_action_after_breach_count": 0,
        },
        "no_replay": {
            "registry_sha256": "3" * 64,
            "historical_entry_count": 18,
            "historical_replay_count": 0,
            "historical_replacement_count": 0,
            "successor_names_disjoint": True,
            "successor_identity_set_sha256": "0" * 64,
            "successor_fee_authorization_nonce_sha256": "9" * 64,
            "old_clone_identity_reuse_count": 0,
            "provider_unknown_count": 0,
            "automatic_retry_count": 0,
            "manual_resend_count": 0,
            "second_clone_count": 0,
            "restore_time_change_count": 0,
            "untracked_script_execution_count": 0,
        },
        "execution_boundary": {
            "clone_create_count": 1,
            "clone_delete_count": 1,
            "builder_start_count": 1,
            "builder_stop_count": 1,
            "cloud_assistant_dispatch_count": 4,
            "sendfile_dispatch_count": 2,
            "database_write_count": 0,
            "object_write_count": 0,
            "persistent_permission_mutation_count": 0,
            "public_request_count": 0,
            "workload_provider_call_count": 0,
            "service_restart_count": 0,
            "automatic_retry_allowed": False,
        },
        "terminal_acceptance_sha256": "",
    }
    successor_identity = value["provider_identity"]
    successor_identity["successor_clone_identity_set_sha256"] = (
        verifier.successor_clone_identity_set_sha256(successor_identity)
    )
    clone_create = value["ordered_actions"][1]
    clone_create["target_sha256"] = successor_identity[
        "successor_clone_name_sha256"
    ]
    clone_create["request_sha256"] = successor_identity[
        "successor_clone_create_body_sha256"
    ]
    clone_create["provider_request_id_sha256"] = successor_identity[
        "successor_clone_create_request_sha256"
    ]
    clone_create["client_token_sha256"] = successor_identity[
        "successor_clone_client_token_sha256"
    ]
    value["raw_closure"]["successor_clone_identity_set_sha256"] = (
        successor_identity["successor_clone_identity_set_sha256"]
    )
    value["no_replay"]["successor_identity_set_sha256"] = (
        successor_identity["successor_clone_identity_set_sha256"]
    )
    return value, source


def refresh_successor_bindings(value):
    identity = value["provider_identity"]
    identity["successor_clone_identity_set_sha256"] = (
        verifier.successor_clone_identity_set_sha256(identity)
    )
    clone_create = value["ordered_actions"][1]
    clone_create["target_sha256"] = identity["successor_clone_name_sha256"]
    clone_create["request_sha256"] = identity[
        "successor_clone_create_body_sha256"
    ]
    clone_create["provider_request_id_sha256"] = identity[
        "successor_clone_create_request_sha256"
    ]
    clone_create["client_token_sha256"] = identity[
        "successor_clone_client_token_sha256"
    ]
    value["raw_closure"]["successor_clone_identity_set_sha256"] = identity[
        "successor_clone_identity_set_sha256"
    ]
    value["no_replay"]["successor_identity_set_sha256"] = identity[
        "successor_clone_identity_set_sha256"
    ]
    return value


def no_replay_registry():
    value = {
        "all_replacement_allowed_false": True,
        "all_replay_allowed_false": True,
        "automatic_retry_allowed": False,
        "entries": verifier._expected_no_replay_entries(),
        "entry_count": len(verifier.FROZEN_NO_REPLAY_IDENTITIES),
        "registry_sha256": "",
        "schema": verifier.NO_REPLAY_REGISTRY_SCHEMA,
        "status": "FROZEN_SOURCE_CHECKPOINT_POLICY",
        "task_id": verifier.TASK_ID,
        "unknown_resolution_policy": "EXACT_EXISTING_IDENTITY_READBACK_ONLY",
        "untracked_script_execution_authorized": False,
    }
    value["registry_sha256"] = verifier.no_replay_registry_sha256(value)
    return value


def refresh_manifest(value):
    value = copy.deepcopy(value)
    value.pop("manifest_sha256", None)
    value["manifest_sha256"] = recovery._sha(
        recovery._canonical_json(value)
    )
    return value


def terminal_projection(source, restored):
    source_capture = capture(source["manifest_sha256"])
    restored_capture = capture(restored["manifest_sha256"])
    reconciliation = {
        "verified": True,
        "mismatch_codes": [],
        "source_manifest_sha256": source["manifest_sha256"],
        "restored_manifest_sha256": restored["manifest_sha256"],
        "equal_fields": list(result_validator.EXPECTED_EQUAL_FIELDS),
        "content_included": False,
    }
    return source_capture, restored_capture, reconciliation


class VerifyPitrRestoreEvidenceTests(unittest.TestCase):
    def test_default_terminal_roots_fail_closed(self):
        errors, acceptance = verifier.validate_manifest_evidence([])
        self.assertEqual(
            errors, ["Item26 terminal semantic verifier is not finalized"]
        )
        self.assertIsNone(acceptance)

    def test_strict_receipt_and_builder_accept_exact_terminal_projection(self):
        candidate, source = receipt_candidate()
        receipt = build_receipt(
            candidate,
            source_manifest=source,
            restored_manifest=copy.deepcopy(source),
            expected_abort_dependency=abort_dependency(),
        )
        errors, acceptance = verifier.validate_receipt(
            receipt,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertEqual(errors, [])
        self.assertEqual(acceptance, receipt["terminal_acceptance_sha256"])
        evidence = build_evidence(
            receipt,
            source_manifest=source,
            restored_manifest=copy.deepcopy(source),
            expected_abort_dependency=abort_dependency(),
        )
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["readiness"], verifier.DEFAULT_READINESS)

    def test_capture_write_or_semantic_drift_fails(self):
        candidate, _source = receipt_candidate()
        candidate["source_capture"]["database_write_count"] = 1
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertTrue(any("database_write_count" in error for error in errors))
        self.assertIsNone(acceptance)

    def test_receipt_cannot_self_assert_abort_dependency(self):
        candidate, _source = receipt_candidate()
        candidate["abort_dependency"]["terminal_acceptance_sha256"] = "f" * 64
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertIn("receipt strict abort dependency mismatch", errors)
        self.assertIsNone(acceptance)

    def test_default_abort_dependency_is_unfinalized(self):
        errors, dependency = verifier.validate_abort_dependency(
            expected_successor_revision=EXECUTION_REVISION,
            root=ROOT,
        )
        self.assertEqual(
            errors,
            ["Item26 cost-containment abort dependency is not finalized"],
        )
        self.assertIsNone(dependency)

    def test_frozen_abort_verifier_runs_in_isolated_process(self):
        poisoned = types.ModuleType(
            "validate_item26_cost_containment_abort_result_v1"
        )
        poisoned.validate_abort_result = lambda _value: []
        with mock.patch.dict(
            sys.modules,
            {"validate_item26_cost_containment_abort_result_v1": poisoned},
        ):
            errors, binding = verifier._run_frozen_abort_verifier(
                verifier_raw=(ROOT / verifier.ABORT_VERIFIER_REF).read_bytes(),
                validator_raw=(ROOT / verifier.ABORT_VALIDATOR_REF).read_bytes(),
                root=ROOT,
            )
        self.assertIsNone(binding)
        self.assertEqual(
            errors,
            ["abort external authority/raw extractor is not finalized"],
        )

    def test_abort_dependency_authority_root_is_domain_separated(self):
        dependency = abort_dependency()
        bare = hashlib.sha256(
            verifier._canonical({
                key: dependency[key]
                for key in sorted(dependency)
                if key != "authority_root"
            })[:-1]
        ).hexdigest()
        self.assertNotEqual(dependency["authority_root"], bare)

    def test_successor_clone_must_not_reuse_aborted_clone_identity(self):
        candidate, _source = receipt_candidate()
        dependency = abort_dependency()
        candidate["provider_identity"]["successor_clone_sha256"] = dependency[
            "old_clone_sha256"
        ]
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=dependency,
        )
        self.assertIn("receipt provider identity mismatch", errors)
        self.assertIsNone(acceptance)

    def test_successor_request_name_body_and_token_must_be_disjoint(self):
        dependency = abort_dependency()
        pairs = (
            (
                "successor_clone_name_sha256",
                "old_clone_name_sha256",
            ),
            (
                "successor_clone_create_request_sha256",
                "old_clone_create_request_sha256",
            ),
            (
                "successor_clone_create_body_sha256",
                "old_clone_create_body_sha256",
            ),
            (
                "successor_clone_client_token_sha256",
                "old_clone_client_token_sha256",
            ),
        )
        for successor_key, old_key in pairs:
            with self.subTest(successor_key=successor_key):
                candidate, _source = receipt_candidate()
                candidate["provider_identity"][successor_key] = dependency[old_key]
                candidate["provider_identity"][
                    "successor_clone_identity_set_sha256"
                ] = verifier.successor_clone_identity_set_sha256(
                    candidate["provider_identity"]
                )
                candidate["terminal_acceptance_sha256"] = (
                    verifier.terminal_acceptance_sha256(candidate)
                )
                errors, acceptance = verifier.validate_receipt(
                    candidate,
                    expected_execution_revision=EXECUTION_REVISION,
                    expected_abort_dependency=dependency,
                )
                self.assertTrue(any("provider identity" in error for error in errors))
                self.assertIsNone(acceptance)

    def test_successor_fee_authorization_must_postdate_abort(self):
        candidate, _source = receipt_candidate()
        dependency = abort_dependency()
        candidate["cost_boundary"]["fee_authorization_issued_at_utc"] = dependency[
            "abort_terminal_observed_at_utc"
        ]
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=dependency,
        )
        self.assertTrue(any("cost boundary" in error for error in errors))
        self.assertIsNone(acceptance)

    def test_successor_fee_authorization_cannot_postdate_receipt(self):
        candidate, _source = receipt_candidate()
        cost = candidate["cost_boundary"]
        cost["fee_authorization_issued_at_utc"] = "2026-08-16T00:11:00Z"
        cost["fee_authorization_approved_at_utc"] = "2026-08-16T00:11:00Z"
        cost["clone_create_started_at_utc"] = "2026-08-16T00:11:01Z"
        cost["fee_authorization_expires_at_utc"] = "2026-08-16T00:12:00Z"
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertTrue(any("cost boundary" in error for error in errors))
        self.assertIsNone(acceptance)

    def test_successor_identity_cross_swap_with_old_set_fails(self):
        candidate, _source = receipt_candidate()
        dependency = abort_dependency()
        identity = candidate["provider_identity"]
        identity["successor_clone_create_request_sha256"] = dependency[
            "old_clone_create_body_sha256"
        ]
        identity["successor_clone_create_body_sha256"] = dependency[
            "old_clone_create_request_sha256"
        ]
        refresh_successor_bindings(candidate)
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=dependency,
        )
        self.assertTrue(any("provider identity" in error for error in errors))
        self.assertIsNone(acceptance)

    def test_clone_create_action_must_bind_successor_request_identity(self):
        candidate, _source = receipt_candidate()
        candidate["ordered_actions"][1]["client_token_sha256"] = "a" * 64
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertIn("receipt successor clone request identity mismatch", errors)
        self.assertIsNone(acceptance)

    def test_source_tree_binding_must_match_the_exact_git_revision(self):
        candidate, _source = receipt_candidate()
        candidate["source_binding"]["tree_sha256"] = "f" * 64
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
            root=ROOT,
        )
        self.assertIn("receipt source binding mismatch", errors)
        self.assertIsNone(acceptance)

    def test_unknown_retry_second_clone_or_action_reorder_fails(self):
        candidate, _source = receipt_candidate()
        candidate["no_replay"]["provider_unknown_count"] = 1
        candidate["no_replay"]["second_clone_count"] = 1
        candidate["ordered_actions"][0]["automatic_retry_allowed"] = True
        candidate["ordered_actions"].reverse()
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, _acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertTrue(any("no-replay" in error for error in errors))
        self.assertTrue(any("ordered action" in error for error in errors))

    def test_cleanup_residue_or_shared_resource_deletion_fails(self):
        candidate, _source = receipt_candidate()
        candidate["cleanup"]["ram_attachment_count"] = 1
        candidate["cleanup"]["shared_builder_deleted"] = True
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, _acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertIn("receipt cleanup mismatch", errors)

    def test_cost_over_cap_or_noncanonical_number_fails(self):
        candidate, _source = receipt_candidate()
        candidate["cost_boundary"]["approved_cap_cny"] = "4.0"
        candidate["cost_boundary"]["actual_incremental_cny"] = 5.0
        candidate["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(candidate)
        )
        errors, _acceptance = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            expected_abort_dependency=abort_dependency(),
        )
        self.assertTrue(any("canonical CNY" in error for error in errors))

    def test_terminal_acceptance_covers_cleanup_cost_and_no_replay(self):
        candidate, _source = receipt_candidate()
        first = verifier.terminal_acceptance_sha256(candidate)
        candidate["cleanup"]["host_residue_count"] = 1
        second = verifier.terminal_acceptance_sha256(candidate)
        candidate["cleanup"]["host_residue_count"] = 0
        candidate["cost_boundary"]["rds_incremental_cny"] = "4.000001"
        third = verifier.terminal_acceptance_sha256(candidate)
        candidate["cost_boundary"]["rds_incremental_cny"] = "4.000000"
        candidate["no_replay"]["manual_resend_count"] = 1
        fourth = verifier.terminal_acceptance_sha256(candidate)
        self.assertEqual(len({first, second, third, fourth}), 4)

    def test_no_replay_registry_accepts_only_the_exact_frozen_set(self):
        registry = no_replay_registry()
        self.assertEqual(verifier.validate_no_replay_registry(registry), [])
        self.assertEqual(
            registry["entry_count"], len(verifier.FROZEN_NO_REPLAY_IDENTITIES)
        )

        removed = copy.deepcopy(registry)
        removed["entries"].pop()
        removed["entry_count"] -= 1
        removed["registry_sha256"] = verifier.no_replay_registry_sha256(
            removed
        )
        self.assertEqual(
            verifier.validate_no_replay_registry(removed),
            ["Item26 no-replay registry schema mismatch"],
        )

    def test_committed_no_replay_registry_is_canonical_and_exact(self):
        value, raw, error = verifier._load(
            ROOT / verifier.NO_REPLAY_REGISTRY_REF
        )
        self.assertIsNone(error)
        self.assertIsNotNone(raw)
        self.assertEqual(verifier.validate_no_replay_registry(value), [])

    def test_no_replay_registry_rejects_policy_or_artifact_drift(self):
        registry = no_replay_registry()
        registry["entries"][-1]["replay_allowed"] = True
        registry["entries"][-1]["artifact_sha256"] = "f" * 64
        registry["registry_sha256"] = verifier.no_replay_registry_sha256(
            registry
        )
        self.assertEqual(
            verifier.validate_no_replay_registry(registry),
            ["Item26 no-replay registry schema mismatch"],
        )

        registry = no_replay_registry()
        registry["registry_sha256"] = "f" * 64
        self.assertEqual(
            verifier.validate_no_replay_registry(registry),
            ["Item26 no-replay registry digest mismatch"],
        )

    def test_identical_fake_table_or_migration_inventory_is_rejected(self):
        source = manifest()
        source["database"]["tables"].pop("users")
        source["database"]["tables"]["fake_users"] = {
            "row_count": 0,
            "rowset_sha256": "f" * 64,
        }
        source["database"]["migrations"][0] = {
            "version": "0001_fake.sql",
            "sha256": "f" * 64,
        }
        source = refresh_manifest(source)
        restored = copy.deepcopy(source)
        source_capture, restored_capture, reconciliation = terminal_projection(
            source, restored
        )
        errors = result_validator.validate_terminal_result(
            source_manifest=source,
            restored_manifest=restored,
            source_capture=source_capture,
            restored_capture=restored_capture,
            reconciliation=reconciliation,
            expected_execution_revision=EXECUTION_REVISION,
        )
        self.assertTrue(any("projection mismatch" in error for error in errors))

    def test_uncaptured_objects_or_absent_reference_tables_are_rejected(self):
        source = manifest()
        source["objects"]["not_captured"] = True
        source["database"]["references"]["ai_payload_refs"]["present"] = False
        source = refresh_manifest(source)
        restored = copy.deepcopy(source)
        source_capture, restored_capture, reconciliation = terminal_projection(
            source, restored
        )
        errors = result_validator.validate_terminal_result(
            source_manifest=source,
            restored_manifest=restored,
            source_capture=source_capture,
            restored_capture=restored_capture,
            reconciliation=reconciliation,
            expected_execution_revision=EXECUTION_REVISION,
        )
        self.assertTrue(any("projection mismatch" in error for error in errors))

    def test_manifest_release_must_equal_frozen_execution_revision(self):
        source = manifest()
        source["release_commit"] = "f" * 40
        source = refresh_manifest(source)
        restored = copy.deepcopy(source)
        source_capture, restored_capture, reconciliation = terminal_projection(
            source, restored
        )
        errors = result_validator.validate_terminal_result(
            source_manifest=source,
            restored_manifest=restored,
            source_capture=source_capture,
            restored_capture=restored_capture,
            reconciliation=reconciliation,
            expected_execution_revision=EXECUTION_REVISION,
        )
        self.assertTrue(any("projection mismatch" in error for error in errors))

    def test_cli_loads_item26_manifest_evidence_instead_of_permanent_none(self):
        payload = {
            "layers": [
                {
                    "controls": [
                        {
                            "id": "backup_pitr_restore",
                            "evidence": [{"kind": "git", "ref": EXECUTION_REVISION}],
                        }
                    ]
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readiness.json"
            path.write_text(
                verifier._canonical(payload).decode("ascii"),
                encoding="ascii",
            )
            output = io.StringIO()
            with mock.patch.object(
                verifier,
                "validate_manifest_evidence",
                return_value=([], "a" * 64),
            ) as validate, mock.patch.object(
                sys,
                "argv",
                ["verify_pitr_restore_evidence.py", "--manifest", str(path)],
            ), contextlib.redirect_stdout(output):
                result = verifier.main()
        self.assertEqual(result, 0)
        self.assertIn("pitr_restore_evidence=PASS", output.getvalue())
        validate.assert_called_once_with(payload["layers"][0]["controls"][0]["evidence"])


if __name__ == "__main__":
    unittest.main()
