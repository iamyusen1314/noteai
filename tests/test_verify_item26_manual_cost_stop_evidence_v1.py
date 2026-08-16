import copy
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_item26_manual_cost_stop_evidence_v1 as verifier  # noqa: E402
from build_item26_manual_cost_stop_evidence_v1 import (  # noqa: E402
    build_evidence,
    build_receipt,
)


control_revision = "1" * 40
digest = "1" * 64
PRODUCTION_CONSUMED_MUTATION_SET_SHA256 = (
    verifier.EXPECTED_CONSUMED_MANUAL_MUTATION_SET_SHA256
)


def candidate():
    value = {
        "schema_version": 1,
        "schema": verifier.RECEIPT_SCHEMA,
        "task_id": verifier.TASK_ID,
        "operation_id": verifier.OPERATION_ID,
        "kind": verifier.KIND,
        "status": verifier.TERMINAL_STATUS,
        "observed_at_utc": "2026-08-17T00:00:00.475Z",
        "ledger_context_revision": verifier.LEDGER_CONTEXT_REVISION,
        "control_revision": control_revision,
        "action_precedes_control_checkpoint": True,
        "abort_v1_terminal_authority": False,
        "action_authorization_granted": False,
        "item26_verified": False,
        "identity_ledger": {
            "old_clone_sha256": verifier.EXPECTED_IDENTITY_COMMITMENTS[
                "old_clone_sha256"
            ],
            "old_clone_name_sha256": verifier.EXPECTED_IDENTITY_COMMITMENTS[
                "old_clone_name_sha256"
            ],
            "source_rds_sha256": verifier.EXPECTED_IDENTITY_COMMITMENTS[
                "source_rds_sha256"
            ],
            "source_name_sha256": verifier.EXPECTED_IDENTITY_COMMITMENTS[
                "source_name_sha256"
            ],
            "old_clone_create_request_sha256": "5" * 64,
            "old_clone_create_body_sha256": "6" * 64,
            "old_clone_client_token_sha256": "7" * 64,
        },
        "mutation_outcomes": {
            "protection_disable": {
                "operation": "ModifyDBInstanceDeletionProtection",
                "target_sha256": verifier.EXPECTED_IDENTITY_COMMITMENTS[
                    "old_clone_sha256"
                ],
                "request_id_sha256": verifier.EXPECTED_PROTECTION_COMMITMENTS[
                    "request_id_sha256"
                ],
                "request_body_sha256": "9" * 64,
                "response_sha256": verifier.EXPECTED_PROTECTION_COMMITMENTS[
                    "response_sha256"
                ],
                "client_token_sha256": verifier.EXPECTED_PROTECTION_COMMITMENTS[
                    "client_token_sha256"
                ],
                "same_identity_readback_sha256": (
                    verifier.EXPECTED_PROTECTION_COMMITMENTS[
                        "same_identity_readback_sha256"
                    ]
                ),
                "submit_count": 1,
                "automatic_retry_count": 0,
                "manual_resend_count": 0,
                "replacement_count": 0,
                "outcome": "PROTECTION_FALSE_READBACK_CONFIRMED",
            },
            "delete": {
                "operation": "DeleteDBInstance",
                "target_sha256": verifier.EXPECTED_IDENTITY_COMMITMENTS[
                    "old_clone_sha256"
                ],
                "request_id_sha256": verifier.EXPECTED_DELETE_COMMITMENTS[
                    "request_id_sha256"
                ],
                "request_body_sha256": "e" * 64,
                "response_sha256": verifier.EXPECTED_DELETE_COMMITMENTS[
                    "response_sha256"
                ],
                "client_token_present": False,
                "exact_identity_absence_readback_sha256": (
                    verifier.EXPECTED_DELETE_COMMITMENTS[
                        "exact_identity_absence_readback_sha256"
                    ]
                ),
                "submit_count": 1,
                "automatic_retry_count": 0,
                "manual_resend_count": 0,
                "replacement_count": 0,
                "outcome": "DELETE_ACCEPTED_EXACT_ID_ABSENT",
            },
            "ordered_mutation_set_sha256": "",
        },
        "source_reconciliation": {
            "pre_tuple_sha256": "2" * 64,
            "post_tuple_sha256": "2" * 64,
            "source_unchanged": True,
            "source_status": "Running",
            "source_pay_type": "Prepaid",
            "source_deleted": False,
        },
        "billing_snapshot": {
            "currency": "CNY",
            "pretax_gross_cny": "198.462",
            "service_seconds": 345600,
            "response_sha256": "3" * 64,
            "historical_snapshot_only": True,
            "native_non_accruing_marker_proven": False,
            "settlement_terminal_proven": False,
        },
        "residual_resources": {
            "non_clone_resource_disposition": (
                "UNPROVEN_RETAINED_FRESH_PREFLIGHT_REQUIRED"
            ),
            "temporary_account_cleanup_terminal": False,
            "iam_cleanup_terminal": False,
            "vswitch_cleanup_terminal": False,
            "shared_builder_retained": True,
            "shared_disk_retained": True,
        },
        "raw_closure": {
            "provider_raw_file_sha256": "4" * 64,
            "actiontrail_raw_file_sha256": "5" * 64,
            "provider_projection_sha256": "6" * 64,
            "actiontrail_projection_sha256": "7" * 64,
            "complete_pagination_proven": True,
            "secret_free_projection": True,
        },
        "no_replay": {
            "registry_schema": "noteai.item26.no-replay-registry.v2",
            "registry_sha256": verifier.EXPECTED_NO_REPLAY_REGISTRY_SHA256,
            "entry_count": verifier.EXPECTED_NO_REPLAY_ENTRY_COUNT,
            "automatic_retry_allowed": False,
            "manual_resend_allowed": False,
            "replacement_allowed": False,
            "historical_script_execution_count": 0,
        },
        "execution_boundary": {
            "cloud_control_plane_write_count": 2,
            "rds_control_plane_write_count": 2,
            "database_connection_count": 0,
            "database_transaction_count": 0,
            "database_write_count": 0,
            "object_write_count": 0,
            "builder_start_count": 0,
            "cloud_assistant_dispatch_count": 0,
            "sendfile_dispatch_count": 0,
            "new_paid_resource_count": 0,
            "readiness_write_count": 0,
        },
        "readiness": copy.deepcopy(verifier.READINESS_25_TO_25),
        "terminal_acceptance_sha256": "",
    }
    value["mutation_outcomes"]["ordered_mutation_set_sha256"] = (
        verifier.consumed_mutation_identity_set_sha256(value)
    )
    return value


class ManualCostStopEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture_digest = candidate()["mutation_outcomes"][
            "ordered_mutation_set_sha256"
        ]
        patcher = mock.patch.object(
            verifier,
            "EXPECTED_CONSUMED_MANUAL_MUTATION_SET_SHA256",
            fixture_digest,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_receipt_builder_validates_but_evidence_stays_fail_closed(self):
        receipt = build_receipt(
            candidate(), expected_control_revision=control_revision
        )
        errors, acceptance = verifier.validate_receipt(
            receipt,
            expected_control_revision=control_revision,
        )
        self.assertEqual(errors, [])
        self.assertEqual(acceptance, receipt["terminal_acceptance_sha256"])
        with self.assertRaisesRegex(ValueError, "not finalized"):
            build_evidence(
                receipt, expected_control_revision=control_revision
            )

    def test_builder_rejects_prefilled_acceptance(self):
        value = candidate()
        value["terminal_acceptance_sha256"] = digest
        with self.assertRaisesRegex(ValueError, "builder-owned"):
            build_receipt(value, expected_control_revision=control_revision)

    def test_delete_cannot_invent_client_token(self):
        value = candidate()
        value["mutation_outcomes"]["delete"]["client_token_present"] = True
        value["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(value)
        )
        errors, _acceptance = verifier.validate_receipt(
            value, expected_control_revision=control_revision
        )
        self.assertIn("manual delete outcome mismatch", errors)

    def test_mutation_identity_digest_binds_delete_token_absence(self):
        value = candidate()
        expected = value["mutation_outcomes"]["ordered_mutation_set_sha256"]
        value["mutation_outcomes"]["delete"]["client_token_present"] = True
        self.assertNotEqual(
            verifier.consumed_mutation_identity_set_sha256(value),
            expected,
        )

    def test_self_consistent_non_registry_mutation_digest_is_rejected(self):
        value = candidate()
        value["mutation_outcomes"]["delete"]["request_body_sha256"] = "a" * 64
        value["mutation_outcomes"]["ordered_mutation_set_sha256"] = (
            verifier.consumed_mutation_identity_set_sha256(value)
        )
        value["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(value)
        )
        errors, _acceptance = verifier.validate_receipt(
            value, expected_control_revision=control_revision
        )
        self.assertIn("manual mutation-set digest mismatch", errors)

    def test_production_consumed_mutation_digest_is_frozen(self):
        self.assertEqual(
            PRODUCTION_CONSUMED_MUTATION_SET_SHA256,
            "8647c02f5879dcb7a986fc87ce3668ac4e35d63d610c4da1e54a57a8b7263105",
        )

    def test_source_tuple_drift_rejected(self):
        value = candidate()
        value["source_reconciliation"]["post_tuple_sha256"] = "9" * 64
        value["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(value)
        )
        errors, _acceptance = verifier.validate_receipt(
            value, expected_control_revision=control_revision
        )
        self.assertIn("manual source reconciliation mismatch", errors)

    def test_abort_or_readiness_credit_claim_rejected(self):
        value = candidate()
        value["status"] = "COST_CONTAINMENT_ABORT_TERMINAL_CLEAN"
        value["readiness"]["internal_verified_after"] = 26
        value["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(value)
        )
        errors, _acceptance = verifier.validate_receipt(
            value, expected_control_revision=control_revision
        )
        self.assertIn("manual receipt status mismatch", errors)
        self.assertIn("manual readiness boundary mismatch", errors)

    def test_default_terminal_authority_fails_before_read(self):
        errors, binding = verifier.validate_terminal_artifacts(root=ROOT)
        self.assertEqual(
            errors,
            ["manual cost-stop external authority is not finalized"],
        )
        self.assertIsNone(binding)


if __name__ == "__main__":
    unittest.main()
