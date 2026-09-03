import copy
import hashlib
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

import validate_item26_cost_containment_abort_result_v1 as result_validator  # noqa: E402
import verify_item26_cost_containment_abort_evidence_v1 as verifier  # noqa: E402
from build_item26_cost_containment_abort_evidence_v1 import (  # noqa: E402
    build_checkpoint,
    build_evidence,
    build_receipt,
    canonical_bytes,
)


EXECUTION_REVISION = "0821ed89880b64da21e4a2b7338749eefe0bc11a"
EVIDENCE_REVISION = "1" * 40


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def identities():
    value = {
        key: digest(key)
        for key in result_validator.IDENTITY_KEYS
    }
    value["inventory_scope_sha256"] = result_validator.inventory_scope_sha256(
        value
    )
    value["builder_disk_tuple_sha256"] = (
        result_validator.builder_disk_tuple_sha256(value)
    )
    value["ram_attachment_sha256"] = result_validator.ram_attachment_sha256(
        value
    )
    return value


def dispositions(identity):
    rows = []
    for slot, kind, identity_key in result_validator.RESOURCE_SLOTS:
        attachment_before = 1 if slot == "ram_attachment" else 0
        dependency_before = 1 if slot == "temporary_account" else 0
        parent, related = {
            "temporary_account": (
                identity["source_rds_sha256"],
                identity["inventory_scope_sha256"],
            ),
            "ram_attachment": (
                identity["ram_role_sha256"],
                identity["ram_policy_sha256"],
            ),
            "ram_policy": (
                identity["account_sha256"],
                identity["ram_role_sha256"],
            ),
            "ram_role": (
                identity["account_sha256"],
                identity["ram_policy_sha256"],
            ),
            "vswitch_a": (
                identity["vpc_sha256"],
                identity["region_sha256"],
            ),
            "vswitch_b": (
                identity["vpc_sha256"],
                identity["region_sha256"],
            ),
            "control_material": (
                identity["inventory_scope_sha256"],
                identity["builder_sha256"],
            ),
        }[slot]
        rows.append({
            "slot": slot,
            "resource_kind": kind,
            "identity_sha256": identity[identity_key],
            "ownership_outcome": "TASK_OWNED",
            "ownership_evidence": {
                "schema": "noteai.item26.cost-containment-abort-ownership.v1",
                "resource_kind": kind,
                "identity_sha256": identity[identity_key],
                "parent_identity_sha256": parent,
                "related_identity_sha256": related,
                "lineage_method": "CREATE_RECEIPT_AND_FULL_INVENTORY",
                "create_receipt_sha256": digest(slot + "-create"),
                "before_inventory_sha256": digest(slot + "-inventory"),
                "task_marker_sha256": digest(slot + "-marker"),
                "topology_tuple_sha256": digest(slot + "-topology"),
                "all_pages_complete": True,
                "task_owned_proven": True,
                "shared_proven": False,
                "absent_proven": False,
            },
            "dependency_count_before": dependency_before,
            "dependency_count_after": 0,
            "attachment_count_before": attachment_before,
            "attachment_count_after": 0,
            "mutation_count": 1,
            "final_state": "ABSENT",
            "final_readback_sha256": digest(slot + "-final"),
        })
    return rows


def actions(identity, disposition_rows):
    by_slot = {row["slot"]: row for row in disposition_rows}
    values = []
    for sequence, (name, kind, identity_key, operation) in enumerate(
        result_validator.EXPECTED_ACTIONS,
        start=1,
    ):
        mode = kind
        mutation_count = 0
        read_count = 1
        same_identity_count = 0
        terminal = "PASS"
        submission_outcome = "NOT_APPLICABLE"
        provider_state_before, provider_state_after = (
            result_validator.ACTION_STATE_BOUNDARIES.get(
                name,
                ("TASK_OWNED_PRESENT", "ABSENT_SAME_IDENTITY"),
            )
        )
        if kind == "EXACT_ONCE_MUTATION":
            mutation_count = 1
            read_count = 0
            terminal = "SUBMITTED_ONCE_NO_REPLAY"
            submission_outcome = "ACCEPTED"
        elif kind == "RESOURCE_DISPOSITION":
            slot = name.removesuffix("_disposition")
            row = by_slot[slot]
            mode = "DELETE_TASK_OWNED"
            mutation_count = row["mutation_count"]
            same_identity_count = 1
            terminal = row["final_state"]
            submission_outcome = "ACCEPTED"
        elif name in {
            "clone_protection_same_identity_readback",
            "clone_absence_same_identity_readback",
            "clone_billing_terminal_readback",
        }:
            same_identity_count = 1
        start_second = sequence - 1
        complete_second = 6 if sequence == 6 else start_second
        if sequence >= 7:
            start_second = sequence
            complete_second = sequence
        values.append({
            "sequence": sequence,
            "name": name,
            "mode": mode,
            "operation": operation,
            "target_sha256": identity[identity_key],
            "request_body_sha256": digest(name + "-request-body"),
            "request_set_sha256": digest(name + "-request"),
            "response_set_sha256": digest(name + "-response"),
            "provider_request_id_set_sha256": digest(name + "-request-id"),
            "observation_set_sha256": digest(name + "-observations"),
            "client_token_used": name == "clone_deletion_protection_disable",
            "client_token_sha256": (
                digest("protection-disable-client-token")
                if name == "clone_deletion_protection_disable"
                else hashlib.sha256(b"").hexdigest()
            ),
            "started_at_utc": f"2026-08-16T00:00:{start_second:02d}Z",
            "completed_at_utc": f"2026-08-16T00:00:{complete_second:02d}Z",
            "read_request_count": read_count,
            "mutation_submit_count": mutation_count,
            "same_identity_readback_count": same_identity_count,
            "automatic_retry_count": 0,
            "manual_resend_count": 0,
            "parameter_change_count": 0,
            "replacement_target_count": 0,
            "submission_outcome": submission_outcome,
            "provider_state_before": provider_state_before,
            "provider_state_after": provider_state_after,
            "terminal_outcome": terminal,
        })
    return values


def authority_binding():
    value = {
        key: digest(key)
        for key in verifier.AUTHORITY_BINDING_KEYS
        if key.endswith("_sha256")
    }
    value.update({
        "authority_keys_distinct": True,
        "root_frozen_before_execution": True,
        "raw_projection_rederived": True,
    })
    return value


def receipt_candidate():
    identity = identities()
    resource_dispositions = dispositions(identity)
    tree_sha256, tracked_file_count = verifier.git_tree_binding(
        EXECUTION_REVISION,
        root=ROOT,
    )
    registry = json.loads((ROOT / verifier.NO_REPLAY_REGISTRY_REF).read_text())
    candidate = {
        "schema_version": 1,
        "schema": verifier.RECEIPT_SCHEMA,
        "task_id": verifier.TASK_ID,
        "operation_id": verifier.OPERATION_ID,
        "action": "COST_CONTAINMENT_ABORT",
        "status": verifier.TERMINAL_STATUS,
        "observed_at_utc": "2026-08-16T00:00:16Z",
        "source_revision": EXECUTION_REVISION,
        "source_binding": {
            "revision": EXECUTION_REVISION,
            "tree_sha256": tree_sha256,
            "tracked_file_count": tracked_file_count,
            "dirty_path_count": 0,
        },
        "authorization": {
            "action": "COST_CONTAINMENT_ABORT",
            "approval_kind": "USER_ACTION_TIME_CONFIRMATION",
            "approval_statement_sha256": digest("approval-statement"),
            "confirmation_envelope_sha256": digest("confirmation-envelope"),
            "plan_sha256": digest("unbound-plan"),
            "preflight_sha256": digest("unbound-preflight"),
            "confirmation_nonce_sha256": digest("nonce"),
            "protection_disable_client_token_sha256": digest(
                "protection-disable-client-token"
            ),
            "approved_at_utc": "2026-08-16T00:00:01Z",
            "expires_at_utc": "2026-08-16T00:10:00Z",
            "allowed_mutations": copy.deepcopy(result_validator.ALLOWED_MUTATIONS),
            "destructive_clone_target_count": 1,
            "new_paid_resource_allowed": False,
        },
        "identity_ledger": identity,
        "preflight": {
            "observed_at_utc": "2026-08-16T00:00:00Z",
            "raw_projection_sha256": digest("unbound-preflight"),
            "all_pages_complete": True,
            "exact_clone_count": 1,
            "clone_identity_sha256": identity["old_clone_sha256"],
            "clone_status": "Running",
            "clone_charge_type": "Postpaid",
            "clone_postgresql_major_version": 16,
            "clone_deletion_protection": True,
            "clone_capture_status": "NOT_STARTED",
            "clone_reconciliation_status": "PENDING",
            "clone_terminal_acceptance": False,
            "source_identity_sha256": identity["source_rds_sha256"],
            "source_status": "Running",
            "source_charge_type": "Prepaid",
            "builder_identity_sha256": identity["builder_sha256"],
            "builder_status": "Stopped",
            "builder_stop_charging_mode": "StopCharging",
            "shared_disk_identity_sha256": identity["shared_disk_sha256"],
            "shared_disk_size_gib": 120,
            "shared_disk_charge_type": "PostPaid",
            "shared_disk_attached_to_builder": True,
            "cost_ceiling_breached": True,
            "billing_observed_at_utc": "2026-08-16T00:00:00Z",
            "billing_cycle": "2026-08",
            "billing_resource_sha256": identity["old_clone_sha256"],
            "billing_pretax_gross_cny": "185.658",
            "billing_service_seconds": 331200,
            "billing_readback_sha256": digest("preflight-billing-readback"),
            "recorded_baseline_pretax_gross_cny": "185.658",
            "recorded_baseline_service_seconds": 331200,
        },
        "ordered_actions": actions(identity, resource_dispositions),
        "billing_closure": {
            "resource_sha256": identity["old_clone_sha256"],
            "release_billing_contract_ref": (
                result_validator.RELEASE_BILLING_CONTRACT_REF
            ),
            "release_billing_contract_sha256": (
                result_validator.EXPECTED_RELEASE_BILLING_CONTRACT_SHA256
            ),
            "currency": "CNY",
            "billing_cycle": "2026-08",
            "approved_24h_ceiling_cny": "76.824",
            "pre_abort_gross_cny": "185.658",
            "pre_abort_service_seconds": 331200,
            "final_gross_cny": "186",
            "final_service_seconds": 331800,
            "incremental_after_preflight_cny": "0.342",
            "deletion_accepted_at_utc": "2026-08-16T00:00:03Z",
            "first_absent_at_utc": "2026-08-16T00:00:04Z",
            "final_observed_at_utc": "2026-08-16T00:00:06Z",
            "billed_through_at_utc": "2026-08-16T00:00:04Z",
            "closure_method": "OFFICIAL_RELEASE_CONTRACT_PLUS_EXACT_ABSENCE",
            "release_contract_outcome": (
                "DELETE_ACCEPTED_EXACT_ID_ABSENT_CONTRACT_APPLIED"
            ),
            "stable_readback_count": 1,
            "open_meter_row_count": 0,
            "metering_closed": True,
            "historical_charge_retained": True,
            "observations": [
                {
                    "observed_at_utc": "2026-08-16T00:00:06Z",
                    "resource_sha256": identity["old_clone_sha256"],
                    "gross_cny": "186",
                    "service_seconds": 331800,
                    "billed_through_at_utc": "2026-08-16T00:00:04Z",
                    "settlement_watermark_at_utc": "2026-08-16T00:00:04Z",
                    "open_meter_row_count": 0,
                    "full_page_complete": True,
                    "raw_observation_sha256": digest("billing-observation-1"),
                },
            ],
        },
        "resource_dispositions": resource_dispositions,
        "final_state": {
            "old_clone_sha256": identity["old_clone_sha256"],
            "old_clone_absent": True,
            "source_rds_sha256": identity["source_rds_sha256"],
            "source_running_prepaid_unchanged": True,
            "source_readback_sha256": digest("source-final-readback"),
            "builder_sha256": identity["builder_sha256"],
            "builder_stopped_stop_charging": True,
            "builder_deleted": False,
            "builder_readback_sha256": digest("builder-final-readback"),
            "shared_disk_sha256": identity["shared_disk_sha256"],
            "shared_disk_retained_attached_120gib_postpaid": True,
            "shared_disk_readback_sha256": digest("disk-final-readback"),
            "builder_disk_tuple_sha256": identity["builder_disk_tuple_sha256"],
            "item26_builder_cost_attribution_proven": False,
            "task_owned_cleanup_terminal": True,
            "unresolved_ownership_count": 0,
        },
        "raw_closure": {
            "schema": "noteai.item26.cost-containment-abort-raw-closure.v1",
            "root_owned_raw_file_sha256": digest("raw-file"),
            "root_owned_raw_semantic_sha256": digest("raw-semantic"),
            "plan_sha256": digest("unbound-plan"),
            "preflight_sha256": digest("unbound-preflight"),
            "confirmation_envelope_sha256": digest("confirmation-envelope"),
            "provider_request_set_sha256": digest("unbound-provider-requests"),
            "provider_response_set_sha256": digest("unbound-provider-responses"),
            "response_projection_sha256": digest("unbound-response-projection"),
            "page_inventory_sha256": digest("unbound-page-inventory"),
            "billing_observation_set_sha256": digest("unbound-billing"),
            "release_evidence_projection_sha256": digest(
                "unbound-release-evidence"
            ),
            "resource_disposition_set_sha256": digest("unbound-dispositions"),
            "final_state_sha256": digest("unbound-final-state"),
            "raw_record_count": 32,
            "full_page_readback_count": 12,
            "raw_provider_payload_retained_in_repository": False,
            "secret_value_emitted_count": 0,
        },
        "no_replay": {
            "registry_ref": verifier.NO_REPLAY_REGISTRY_REF,
            "registry_sha256": registry["registry_sha256"],
            "historical_entry_count": 25,
            "historical_replay_count": 0,
            "historical_replacement_count": 0,
            "historical_automatic_retry_count": 0,
            "untracked_script_execution_count": 0,
            "mutation_automatic_retry_count": 0,
            "mutation_manual_resend_count": 0,
            "mutation_parameter_change_count": 0,
            "replacement_target_count": 0,
            "terminal_unknown_count": 0,
            "unknown_same_identity_readback_only": True,
            "automatic_retry_allowed": False,
            "confirmation_nonce_sha256": digest("nonce"),
            "protection_disable_client_token_sha256": digest(
                "protection-disable-client-token"
            ),
            "abort_mutation_identity_set_sha256": digest("unbound-mutations"),
            "abort_mutation_submit_count": 9,
            "abort_mutation_unknown_resolution_count": 0,
        },
        "execution_boundary": {
            "rds_instance_control_plane_write_count": 2,
            "rds_account_control_plane_write_count": 1,
            "ram_control_plane_write_count": 3,
            "vpc_control_plane_write_count": 2,
            "root_control_material_write_count": 1,
            "deletion_protection_disable_count": 1,
            "clone_delete_count": 1,
            "task_cleanup_mutation_count": 7,
            "cloud_control_plane_write_count": 8,
            "total_mutation_count": 9,
            "new_clone_count": 0,
            "restore_time_change_count": 0,
            "new_paid_resource_count": 0,
            "database_connection_count": 0,
            "database_transaction_count": 0,
            "database_write_count": 0,
            "object_write_count": 0,
            "source_permission_mutation_count": 0,
            "builder_start_count": 0,
            "builder_stop_count": 0,
            "builder_reboot_count": 0,
            "builder_delete_count": 0,
            "disk_detach_count": 0,
            "disk_resize_count": 0,
            "disk_delete_count": 0,
            "cloud_assistant_dispatch_count": 0,
            "sendfile_dispatch_count": 0,
            "historical_command_replay_count": 0,
            "public_request_count": 0,
            "workload_provider_call_count": 0,
            "service_restart_count": 0,
        },
        "readiness": copy.deepcopy(result_validator.READINESS_25_TO_25),
        "terminal_acceptance_sha256": "",
    }
    return rebind_candidate(candidate)


def rebind_candidate(candidate):
    actions_value = candidate["ordered_actions"]
    candidate["authorization"]["allowed_mutations"] = list(
        dict.fromkeys(
            row["operation"]
            for row in actions_value
            if row["mutation_submit_count"] == 1
        )
    )
    candidate["preflight"]["raw_projection_sha256"] = (
        result_validator.preflight_projection_sha256(candidate["preflight"])
    )
    candidate["authorization"]["preflight_sha256"] = candidate["preflight"][
        "raw_projection_sha256"
    ]
    candidate["authorization"]["plan_sha256"] = result_validator.abort_plan_sha256(
        candidate["identity_ledger"],
        candidate["preflight"],
        actions_value,
        candidate["resource_dispositions"],
        candidate["authorization"],
    )
    raw = candidate["raw_closure"]
    raw["plan_sha256"] = candidate["authorization"]["plan_sha256"]
    raw["preflight_sha256"] = candidate["preflight"]["raw_projection_sha256"]
    raw["provider_request_set_sha256"] = (
        result_validator.provider_request_set_sha256(actions_value)
    )
    raw["provider_response_set_sha256"] = (
        result_validator.provider_response_set_sha256(actions_value)
    )
    raw["response_projection_sha256"] = (
        result_validator.response_projection_sha256(actions_value)
    )
    raw["page_inventory_sha256"] = result_validator.page_inventory_sha256(
        actions_value
    )
    raw["billing_observation_set_sha256"] = (
        result_validator.billing_observation_set_sha256(
            candidate["billing_closure"]
        )
    )
    raw["release_evidence_projection_sha256"] = (
        result_validator.release_evidence_projection_sha256(
            candidate["billing_closure"],
            actions_value,
            candidate["final_state"],
            candidate["execution_boundary"],
        )
    )
    raw["resource_disposition_set_sha256"] = (
        result_validator.resource_disposition_set_sha256(
            candidate["resource_dispositions"]
        )
    )
    raw["final_state_sha256"] = result_validator.final_state_sha256(
        candidate["final_state"]
    )
    mutation_rows = [
        row for row in actions_value if row["mutation_submit_count"] == 1
    ]
    operations = [row["operation"] for row in mutation_rows]
    no_replay = candidate["no_replay"]
    no_replay["abort_mutation_identity_set_sha256"] = (
        result_validator.abort_mutation_identity_set_sha256(actions_value)
    )
    no_replay["abort_mutation_submit_count"] = len(mutation_rows)
    no_replay["abort_mutation_unknown_resolution_count"] = sum(
        row["submission_outcome"]
        == "RESPONSE_LOST_RESOLVED_SAME_IDENTITY"
        for row in mutation_rows
    )
    boundary = candidate["execution_boundary"]
    boundary["rds_instance_control_plane_write_count"] = sum(
        operation
        in {"ModifyDBInstanceDeletionProtection", "DeleteDBInstance"}
        for operation in operations
    )
    boundary["rds_account_control_plane_write_count"] = operations.count(
        "DeleteAccount"
    )
    boundary["ram_control_plane_write_count"] = sum(
        operation in {"DetachPolicyFromRole", "DeletePolicy", "DeleteRole"}
        for operation in operations
    )
    boundary["vpc_control_plane_write_count"] = operations.count("DeleteVSwitch")
    boundary["root_control_material_write_count"] = operations.count(
        "DeleteTaskControlMaterial"
    )
    boundary["task_cleanup_mutation_count"] = sum(
        row["mutation_count"] for row in candidate["resource_dispositions"]
    )
    boundary["cloud_control_plane_write_count"] = len(operations) - operations.count(
        "DeleteTaskControlMaterial"
    )
    boundary["total_mutation_count"] = len(operations)
    return candidate


class Item26CostContainmentAbortEvidenceTests(unittest.TestCase):
    def terminal_receipt(self):
        return build_receipt(receipt_candidate(), root=ROOT)

    def test_valid_receipt_evidence_and_checkpoint(self):
        receipt = self.terminal_receipt()
        errors, acceptance = verifier.validate_receipt(
            receipt,
            expected_execution_revision=EXECUTION_REVISION,
            root=ROOT,
        )
        self.assertEqual(errors, [])
        self.assertEqual(acceptance, receipt["terminal_acceptance_sha256"])
        authority = authority_binding()
        evidence = build_evidence(receipt, authority_binding=authority, root=ROOT)
        checkpoint = build_checkpoint(
            receipt=receipt,
            evidence=evidence,
            evidence_revision=EVIDENCE_REVISION,
        )
        self.assertEqual(evidence["status"], "PASS_NO_READINESS_CREDIT")
        self.assertFalse(evidence["readiness"]["readiness_credit_added"])
        self.assertFalse(checkpoint["readiness_credit_added"])

    def test_source_scaffold_fails_closed(self):
        self.assertEqual(verifier.EXPECTED_AUTHORITY_ROOT_FILE_SHA256, "")
        self.assertFalse(verifier.RAW_PROVIDER_EXTRACTOR_FINALIZED)
        errors, binding = verifier.validate_terminal_artifacts(root=ROOT)
        self.assertIsNone(binding)
        self.assertTrue(any("not finalized" in error for error in errors))

    def test_builder_rejects_preissued_acceptance(self):
        candidate = receipt_candidate()
        candidate["terminal_acceptance_sha256"] = digest("self-issued")
        with self.assertRaisesRegex(ValueError, "builder-owned"):
            build_receipt(candidate, root=ROOT)

    def test_wrong_action_order_fails(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][1], candidate["ordered_actions"][2] = (
            candidate["ordered_actions"][2],
            candidate["ordered_actions"][1],
        )
        candidate["terminal_acceptance_sha256"] = verifier.terminal_acceptance_sha256(candidate)
        errors, _ = verifier.validate_receipt(
            candidate,
            expected_execution_revision=EXECUTION_REVISION,
            root=ROOT,
        )
        self.assertTrue(any("order" in error for error in errors))

    def test_mutation_retry_fails(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][1]["automatic_retry_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_protection_disable_requires_prebound_client_token(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][1]["client_token_used"] = False
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_mutation_resend_fails(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][3]["manual_resend_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_wrong_replacement_target_fails(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][3]["replacement_target_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_confirmation_after_first_mutation_fails(self):
        candidate = receipt_candidate()
        candidate["authorization"]["approved_at_utc"] = "2026-08-16T00:00:03Z"
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_cleanup_mutation_after_confirmation_expiry_fails(self):
        candidate = receipt_candidate()
        candidate["authorization"]["expires_at_utc"] = "2026-08-16T00:00:08Z"
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_expired_confirmation_fails(self):
        candidate = receipt_candidate()
        candidate["authorization"]["expires_at_utc"] = "2026-08-16T00:00:01Z"
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_confirmation_ttl_over_ten_minutes_fails_after_rebinding(self):
        candidate = receipt_candidate()
        candidate["authorization"]["expires_at_utc"] = "2026-08-16T00:20:00Z"
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_wrong_plan_binding_fails(self):
        candidate = receipt_candidate()
        candidate["raw_closure"]["plan_sha256"] = digest("other-plan")
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_action_request_commitments_cannot_all_alias(self):
        candidate = receipt_candidate()
        shared = digest("shared-action-request")
        for row in candidate["ordered_actions"]:
            row["request_body_sha256"] = shared
            row["request_set_sha256"] = shared
        rebind_candidate(candidate)
        errors = result_validator.validate_abort_result(candidate)
        self.assertTrue(any("not distinct" in error for error in errors))

    def test_provider_request_id_sets_cannot_alias(self):
        candidate = receipt_candidate()
        shared = digest("shared-provider-request-id")
        for row in candidate["ordered_actions"]:
            row["provider_request_id_set_sha256"] = shared
        rebind_candidate(candidate)
        errors = result_validator.validate_abort_result(candidate)
        self.assertTrue(any("provider request ID" in error for error in errors))

    def test_clone_source_identity_collision_fails(self):
        candidate = receipt_candidate()
        candidate["identity_ledger"]["source_rds_sha256"] = candidate[
            "identity_ledger"
        ]["old_clone_sha256"]
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_wrong_preflight_clone_fails(self):
        candidate = receipt_candidate()
        candidate["preflight"]["clone_status"] = "Deleting"
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_boolean_cannot_alias_integer_count(self):
        candidate = receipt_candidate()
        candidate["preflight"]["exact_clone_count"] = True
        candidate["billing_closure"]["open_meter_row_count"] = False
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_malformed_nested_projection_fails_without_exception(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][0] = "not-an-action"
        candidate["no_replay"] = "not-a-ledger"
        errors = result_validator.validate_abort_result(candidate)
        self.assertTrue(errors)

    def test_clone_absence_does_not_replace_billing_closure(self):
        candidate = receipt_candidate()
        candidate["billing_closure"]["metering_closed"] = False
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_release_billing_contract_identity_is_frozen(self):
        candidate = receipt_candidate()
        candidate["billing_closure"]["release_billing_contract_sha256"] = (
            digest("wrong-release-billing-contract")
        )
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_known_billing_baseline_cannot_be_replaced_and_rebound(self):
        candidate = receipt_candidate()
        candidate["billing_closure"]["billing_cycle"] = "2099-12"
        candidate["billing_closure"]["approved_24h_ceiling_cny"] = "1"
        candidate["billing_closure"]["pre_abort_gross_cny"] = "2"
        candidate["billing_closure"]["pre_abort_service_seconds"] = 1
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_runtime_billing_preflight_may_advance_above_recorded_baseline(self):
        candidate = receipt_candidate()
        preflight = candidate["preflight"]
        billing = candidate["billing_closure"]
        preflight["billing_pretax_gross_cny"] = "200"
        preflight["billing_service_seconds"] = 400000
        billing["pre_abort_gross_cny"] = "200"
        billing["pre_abort_service_seconds"] = 400000
        billing["final_gross_cny"] = "201"
        billing["final_service_seconds"] = 400100
        billing["incremental_after_preflight_cny"] = "1"
        billing["observations"][0]["gross_cny"] = "201"
        billing["observations"][0]["service_seconds"] = 400100
        rebind_candidate(candidate)
        self.assertEqual(result_validator.validate_abort_result(candidate), [])

    def test_stale_preflight_cannot_authorize_mutation(self):
        candidate = receipt_candidate()
        candidate["preflight"]["observed_at_utc"] = "2026-08-15T23:57:00Z"
        candidate["preflight"]["billing_observed_at_utc"] = (
            "2026-08-15T23:57:00Z"
        )
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_action_time_preflight_billing_snapshot_is_plan_bound(self):
        candidate = receipt_candidate()
        candidate["preflight"]["billing_pretax_gross_cny"] = "999"
        candidate["preflight"]["billing_service_seconds"] = 1
        candidate["billing_closure"]["pre_abort_gross_cny"] = "999"
        candidate["billing_closure"]["pre_abort_service_seconds"] = 1
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_growing_billing_row_fails(self):
        candidate = receipt_candidate()
        candidate["billing_closure"]["incremental_after_preflight_cny"] = "0"
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_settlement_only_closure_is_not_finalized_in_v1(self):
        candidate = receipt_candidate()
        billing = candidate["billing_closure"]
        billing["closure_method"] = "SETTLEMENT_WATERMARK_STABLE_TWO_READS"
        billing["release_contract_outcome"] = "NOT_APPLICABLE"
        billing["stable_readback_count"] = 2
        first = copy.deepcopy(billing["observations"][0])
        first["observed_at_utc"] = "2026-08-16T00:00:05Z"
        first["raw_observation_sha256"] = digest("settlement-observation-1")
        second = copy.deepcopy(billing["observations"][0])
        second["raw_observation_sha256"] = digest("settlement-observation-2")
        billing["observations"] = [first, second]
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_billing_observations_must_be_distinct_and_ordered(self):
        candidate = receipt_candidate()
        billing = candidate["billing_closure"]
        billing["closure_method"] = "SETTLEMENT_WATERMARK_STABLE_TWO_READS"
        billing["release_contract_outcome"] = "NOT_APPLICABLE"
        billing["stable_readback_count"] = 2
        billing["observations"].append(copy.deepcopy(billing["observations"][0]))
        candidate["billing_closure"]["final_observed_at_utc"] = (
            "2026-08-16T00:00:06Z"
        )
        candidate["billing_closure"]["billed_through_at_utc"] = (
            "2026-08-16T00:00:04Z"
        )
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_shared_builder_delete_fails(self):
        candidate = receipt_candidate()
        candidate["final_state"]["builder_deleted"] = True
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_shared_disk_mutation_fails(self):
        candidate = receipt_candidate()
        candidate["execution_boundary"]["disk_delete_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_builder_start_fails(self):
        candidate = receipt_candidate()
        candidate["execution_boundary"]["builder_start_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_cloud_assistant_dispatch_fails(self):
        candidate = receipt_candidate()
        candidate["execution_boundary"]["cloud_assistant_dispatch_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_vswitch_dependency_fails(self):
        candidate = receipt_candidate()
        candidate["resource_dispositions"][4]["dependency_count_before"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_ram_attachment_lineage_fails(self):
        candidate = receipt_candidate()
        candidate["resource_dispositions"][1]["attachment_count_before"] = 2
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_ownership_commitments_cannot_be_reused_across_resources(self):
        candidate = receipt_candidate()
        for row in candidate["resource_dispositions"]:
            ownership = row["ownership_evidence"]
            for key in (
                "create_receipt_sha256",
                "before_inventory_sha256",
                "task_marker_sha256",
                "topology_tuple_sha256",
            ):
                ownership[key] = digest("shared-ownership-commitment")
        rebind_candidate(candidate)
        errors = result_validator.validate_abort_result(candidate)
        self.assertTrue(any("ownership" in error for error in errors))

    def test_resource_disposition_api_mismatch_fails_even_if_rebound(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][10]["operation"] = "DeleteRole"
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_unknown_ownership_fails(self):
        candidate = receipt_candidate()
        candidate["resource_dispositions"][0]["ownership_outcome"] = "UNKNOWN"
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_proven_shared_resource_is_retained_without_write(self):
        candidate = receipt_candidate()
        row = candidate["resource_dispositions"][0]
        row["ownership_outcome"] = "PROVEN_SHARED"
        row["ownership_evidence"]["task_owned_proven"] = False
        row["ownership_evidence"]["shared_proven"] = True
        row["mutation_count"] = 0
        row["final_state"] = "RETAINED_SHARED"
        row["dependency_count_after"] = row["dependency_count_before"]
        action = candidate["ordered_actions"][6]
        action["mode"] = "RETAIN_PROVEN_SHARED"
        action["operation"] = "DescribeAccountDisposition"
        action["mutation_submit_count"] = 0
        action["submission_outcome"] = "NOT_APPLICABLE"
        action["provider_state_before"] = "PROVEN_SHARED_PRESENT"
        action["provider_state_after"] = "RETAINED_SHARED_UNCHANGED"
        action["terminal_outcome"] = "RETAINED_SHARED"
        rebind_candidate(candidate)
        self.assertEqual(result_validator.validate_abort_result(candidate), [])

    def test_proven_shared_resource_retains_its_dependencies(self):
        candidate = receipt_candidate()
        row = candidate["resource_dispositions"][4]
        row["ownership_outcome"] = "PROVEN_SHARED"
        row["ownership_evidence"]["task_owned_proven"] = False
        row["ownership_evidence"]["shared_proven"] = True
        row["dependency_count_before"] = 2
        row["dependency_count_after"] = 2
        row["mutation_count"] = 0
        row["final_state"] = "RETAINED_SHARED"
        action = candidate["ordered_actions"][10]
        action["mode"] = "RETAIN_PROVEN_SHARED"
        action["operation"] = "DescribeVSwitchDisposition"
        action["mutation_submit_count"] = 0
        action["submission_outcome"] = "NOT_APPLICABLE"
        action["provider_state_before"] = "PROVEN_SHARED_PRESENT"
        action["provider_state_after"] = "RETAINED_SHARED_UNCHANGED"
        action["terminal_outcome"] = "RETAINED_SHARED"
        rebind_candidate(candidate)
        self.assertEqual(result_validator.validate_abort_result(candidate), [])

    def test_unknown_terminal_state_fails(self):
        candidate = receipt_candidate()
        candidate["no_replay"]["terminal_unknown_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_unknown_mutation_requires_same_identity_resolution(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][3]["submission_outcome"] = (
            "RESPONSE_LOST_RESOLVED_SAME_IDENTITY"
        )
        candidate["ordered_actions"][4]["same_identity_readback_count"] = 0
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_unknown_mutation_stops_v1_even_after_same_identity_resolution(self):
        candidate = receipt_candidate()
        candidate["ordered_actions"][1]["submission_outcome"] = (
            "RESPONSE_LOST_RESOLVED_SAME_IDENTITY"
        )
        rebind_candidate(candidate)
        errors = result_validator.validate_abort_result(candidate)
        self.assertTrue(
            any("exact-once mutation boundary" in error for error in errors)
        )

    def test_fake_historical_registry_digest_fails_after_rebinding(self):
        candidate = receipt_candidate()
        candidate["no_replay"]["registry_sha256"] = digest("fake-registry")
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_historical_replay_fails(self):
        candidate = receipt_candidate()
        candidate["no_replay"]["historical_replay_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_untracked_script_execution_fails(self):
        candidate = receipt_candidate()
        candidate["no_replay"]["untracked_script_execution_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_new_clone_fails(self):
        candidate = receipt_candidate()
        candidate["execution_boundary"]["new_clone_count"] = 1
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_readiness_credit_fails(self):
        candidate = receipt_candidate()
        candidate["readiness"]["internal_verified_after"] = 26
        candidate["readiness"]["readiness_credit_added"] = True
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_acceptance_detects_raw_closure_drift(self):
        receipt = self.terminal_receipt()
        original = receipt["terminal_acceptance_sha256"]
        receipt["raw_closure"]["raw_record_count"] += 1
        self.assertNotEqual(verifier.terminal_acceptance_sha256(receipt), original)

    def test_raw_request_aggregate_must_match_ordered_actions(self):
        candidate = receipt_candidate()
        candidate["raw_closure"]["provider_request_set_sha256"] = digest(
            "detached-raw-request-set"
        )
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_release_evidence_projection_cannot_drift(self):
        candidate = receipt_candidate()
        candidate["raw_closure"]["release_evidence_projection_sha256"] = (
            digest("detached-release-evidence")
        )
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_receipt_observation_cannot_precede_actions(self):
        candidate = receipt_candidate()
        candidate["observed_at_utc"] = "2026-08-16T00:00:00Z"
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_shared_builder_disk_final_readbacks_must_be_distinct(self):
        candidate = receipt_candidate()
        candidate["final_state"]["builder_readback_sha256"] = candidate[
            "final_state"
        ]["source_readback_sha256"]
        rebind_candidate(candidate)
        self.assertTrue(result_validator.validate_abort_result(candidate))

    def test_evidence_cannot_claim_item26_verified(self):
        receipt = self.terminal_receipt()
        authority = authority_binding()
        evidence = build_evidence(receipt, authority_binding=authority, root=ROOT)
        evidence["abort_outcome"]["item26_verified"] = True
        errors = verifier.validate_evidence(
            evidence,
            receipt,
            canonical_bytes(receipt),
            expected_execution_revision=EXECUTION_REVISION,
            authority_binding=authority,
        )
        self.assertTrue(errors)

    def test_authority_keys_must_be_distinct(self):
        receipt = self.terminal_receipt()
        authority = authority_binding()
        authority["confirmation_key_spki_sha256"] = authority[
            "provider_key_spki_sha256"
        ]
        with self.assertRaisesRegex(ValueError, "authority binding invalid"):
            build_evidence(receipt, authority_binding=authority, root=ROOT)

    def test_checkpoint_cannot_add_credit(self):
        receipt = self.terminal_receipt()
        authority = authority_binding()
        evidence = build_evidence(receipt, authority_binding=authority, root=ROOT)
        checkpoint = build_checkpoint(
            receipt=receipt,
            evidence=evidence,
            evidence_revision=EVIDENCE_REVISION,
        )
        checkpoint["readiness_credit_added"] = True
        errors = verifier.validate_checkpoint(
            checkpoint,
            evidence,
            canonical_bytes(evidence),
            receipt,
            canonical_bytes(receipt),
            expected_execution_revision=EXECUTION_REVISION,
            expected_evidence_revision=EVIDENCE_REVISION,
        )
        self.assertTrue(errors)

    def test_noncanonical_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text('{"b": 1, "a": 2}\n', encoding="ascii")
            value, raw, error = verifier._load(path)
        self.assertIsNone(value)
        self.assertIsNone(raw)
        self.assertIn("canonical", error)

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text('{"a":1,"a":1}\n', encoding="ascii")
            value, raw, error = verifier._load(path)
        self.assertIsNone(value)
        self.assertIsNone(raw)
        self.assertIn("canonical", error)

    def test_authority_callback_cannot_be_bypassed_by_shape_only_artifacts(self):
        fake = {
            "execution_revision": EXECUTION_REVISION,
            "evidence_revision": EVIDENCE_REVISION,
        }
        with mock.patch.object(
            verifier,
            "validate_abort_authority_bundle",
            return_value=(["provider raw closure missing"], fake),
        ):
            errors, binding = verifier.validate_terminal_artifacts(root=ROOT)
        self.assertIsNone(binding)
        self.assertEqual(errors, ["provider raw closure missing"])


if __name__ == "__main__":
    unittest.main()
