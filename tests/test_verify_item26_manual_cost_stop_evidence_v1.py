import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_item26_manual_cost_stop_evidence_v1 as verifier  # noqa: E402
import verify_item26_manual_cost_stop_authority_v1 as authority  # noqa: E402
import build_item26_manual_cost_stop_evidence_v1 as builder  # noqa: E402
from build_item26_manual_cost_stop_evidence_v1 import (  # noqa: E402
    build_checkpoint,
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
            "pre_tuple_sha256": verifier.EXPECTED_SOURCE_PRE_TUPLE_SHA256,
            "post_tuple_sha256": verifier.EXPECTED_SOURCE_PRE_TUPLE_SHA256,
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
            "recorded_baseline_pretax_gross_cny": "198.462",
            "recorded_baseline_service_seconds": 345600,
            "recorded_baseline_response_sha256": (
                verifier.EXPECTED_RECORDED_BILLING_RESPONSE_SHA256
            ),
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
            "activation_receipt_sha256": "8" * 64,
            "provider_raw_file_sha256": "4" * 64,
            "actiontrail_raw_file_sha256": "5" * 64,
            "provider_projection_sha256": "6" * 64,
            "actiontrail_projection_sha256": "7" * 64,
            "complete_pagination_proven": True,
            "secret_free_projection": True,
            "historical_response_commitments_are_ledger_context": True,
            "historical_response_bytes_rederived_from_fresh_raw": False,
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

    def test_candidate_evidence_and_checkpoint_add_no_credit(self):
        receipt = candidate()
        receipt["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(receipt)
        )
        errors, acceptance = verifier.validate_receipt(
            receipt,
            expected_control_revision=control_revision,
        )
        self.assertEqual(errors, [])
        self.assertEqual(acceptance, receipt["terminal_acceptance_sha256"])
        evidence = build_evidence(
            receipt, expected_control_revision=control_revision
        )
        self.assertEqual(evidence["status"], "CANDIDATE_NO_READINESS_CREDIT")
        self.assertTrue(
            evidence["external_authority"]["terminal_authority_pending"]
        )
        self.assertFalse(evidence["readiness"]["readiness_credit_added"])
        checkpoint = build_checkpoint(
            receipt=receipt,
            evidence=evidence,
            expected_control_revision=control_revision,
            evidence_revision="2" * 40,
        )
        self.assertEqual(
            checkpoint["status"],
            "MANUAL_COST_STOP_CANDIDATE_AWAITING_AUTHORITY",
        )
        self.assertFalse(checkpoint["readiness_credit_added"])

    def test_checkpoint_builder_rejects_invalid_evidence(self):
        receipt = candidate()
        receipt["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(receipt)
        )
        with self.assertRaisesRegex(
            ValueError, "manual cost-stop evidence mismatch"
        ):
            build_checkpoint(
                receipt=receipt,
                evidence={},
                expected_control_revision=control_revision,
                evidence_revision="2" * 40,
            )

    def test_builder_rejects_caller_supplied_receipt_dict(self):
        with self.assertRaises(TypeError):
            build_receipt(
                candidate(), expected_control_revision=control_revision
            )

    def test_receipt_builder_uses_only_verified_projection(self):
        value = candidate()
        events = []
        for name, row in (
            (
                "ModifyDBInstanceDeletionProtection",
                value["mutation_outcomes"]["protection_disable"],
            ),
            ("DeleteDBInstance", value["mutation_outcomes"]["delete"]),
        ):
            events.append({
                "event_name": name,
                "provider_request_id_sha256": row["request_id_sha256"],
                "request_body_sha256": row["request_body_sha256"],
                "client_token_present": row.get("client_token_present", True),
                "client_token_sha256": row.get("client_token_sha256"),
            })
        projection = SimpleNamespace(
            control_revision=control_revision,
            provider={
                "observed_at_utc": value["observed_at_utc"],
                "activation_receipt_sha256": "8" * 64,
                "source": {
                    "tuple_sha256": verifier.EXPECTED_SOURCE_PRE_TUPLE_SHA256,
                    "status": "Running",
                    "pay_type": "Prepaid",
                },
                "billing": copy.deepcopy(value["billing_snapshot"]),
                "provider_raw_file_sha256": "4" * 64,
            },
            actiontrail={
                "observed_at_utc": value["observed_at_utc"],
                "activation_receipt_sha256": "8" * 64,
                "events": events,
                "clone_create": {
                    "provider_request_id_sha256": value["identity_ledger"][
                        "old_clone_create_request_sha256"
                    ],
                    "request_body_sha256": value["identity_ledger"][
                        "old_clone_create_body_sha256"
                    ],
                    "client_token_sha256": value["identity_ledger"][
                        "old_clone_client_token_sha256"
                    ],
                },
                "historical_mutation_request_ids_rederived": True,
                "historical_request_bodies_rederived": True,
                "historical_client_tokens_rederived": True,
                "old_clone_create_identity_rederived": True,
                "actiontrail_raw_file_sha256": "5" * 64,
            },
        )
        fixture_digest = value["mutation_outcomes"][
            "ordered_mutation_set_sha256"
        ]
        with mock.patch.object(
            builder, "load_verified_projection", return_value=(projection, {})
        ), mock.patch.object(
            builder,
            "EXPECTED_CONSUMED_MANUAL_MUTATION_SET_SHA256",
            fixture_digest,
        ):
            receipt = build_receipt(
                expected_control_revision=control_revision
            )
        errors, acceptance = verifier.validate_receipt(
            receipt, expected_control_revision=control_revision
        )
        self.assertEqual(errors, [])
        self.assertEqual(acceptance, receipt["terminal_acceptance_sha256"])

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

    def test_malformed_nested_receipt_fails_closed_without_exception(self):
        value = candidate()
        value["identity_ledger"] = None
        value["mutation_outcomes"]["protection_disable"] = None
        value["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(value)
        )
        errors, acceptance = verifier.validate_receipt(
            value, expected_control_revision=control_revision
        )
        self.assertIn("manual receipt identity ledger mismatch", errors)
        self.assertIn("manual mutation-set digest mismatch", errors)
        self.assertIsNotNone(acceptance)

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
        self.assertTrue(errors)
        self.assertIn("terminal artifacts are not installed", errors[0])
        self.assertIsNone(binding)

    def test_terminal_invalid_receipt_schema_fails_without_exception(self):
        invalid = verifier.canonical_bytes({})
        with mock.patch.object(
            verifier, "_read_repo_artifact", return_value=invalid
        ):
            errors, binding = verifier.validate_terminal_artifacts(root=ROOT)
        self.assertEqual(
            errors, ["manual cost-stop receipt schema mismatch"]
        )
        self.assertIsNone(binding)

    def terminal_fixture(self):
        receipt = candidate()
        receipt["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(receipt)
        )
        evidence = build_evidence(
            receipt, expected_control_revision=control_revision
        )
        evidence_revision = "2" * 40
        checkpoint = build_checkpoint(
            receipt=receipt,
            evidence=evidence,
            expected_control_revision=control_revision,
            evidence_revision=evidence_revision,
        )
        receipt_raw = verifier.canonical_bytes(receipt)
        evidence_raw = verifier.canonical_bytes(evidence)
        checkpoint_raw = verifier.canonical_bytes(checkpoint)
        authority_binding = {
            "control_revision": control_revision,
            "evidence_revision": evidence_revision,
            "terminal_revision": "3" * 40,
            "receipt_file_sha256": verifier.sha256(receipt_raw),
            "evidence_file_sha256": verifier.sha256(evidence_raw),
            "checkpoint_file_sha256": verifier.sha256(checkpoint_raw),
            "terminal_acceptance_sha256": receipt[
                "terminal_acceptance_sha256"
            ],
            "old_clone_sha256": receipt["identity_ledger"][
                "old_clone_sha256"
            ],
            "old_clone_name_sha256": receipt["identity_ledger"][
                "old_clone_name_sha256"
            ],
            "source_pre_tuple_sha256": receipt[
                "source_reconciliation"
            ]["pre_tuple_sha256"],
            "source_post_tuple_sha256": receipt[
                "source_reconciliation"
            ]["post_tuple_sha256"],
            "billing_snapshot_sha256": verifier.semantic_sha256(
                receipt["billing_snapshot"]
            ),
            "no_replay_registry_sha256": receipt["no_replay"][
                "registry_sha256"
            ],
            "authority_root_file_sha256": "8" * 64,
            "authority_bundle_file_sha256": "9" * 64,
            "activation_receipt_sha256": receipt["raw_closure"][
                "activation_receipt_sha256"
            ],
            "provider_raw_file_sha256": receipt["raw_closure"][
                "provider_raw_file_sha256"
            ],
            "actiontrail_raw_file_sha256": receipt["raw_closure"][
                "actiontrail_raw_file_sha256"
            ],
            "provider_projection_sha256": receipt["raw_closure"][
                "provider_projection_sha256"
            ],
            "actiontrail_projection_sha256": receipt["raw_closure"][
                "actiontrail_projection_sha256"
            ],
            "confirmation_envelope_file_sha256": "a" * 64,
            "old_clone_create_request_sha256": receipt[
                "identity_ledger"
            ]["old_clone_create_request_sha256"],
            "old_clone_create_body_sha256": receipt["identity_ledger"][
                "old_clone_create_body_sha256"
            ],
            "old_clone_client_token_sha256": receipt["identity_ledger"][
                "old_clone_client_token_sha256"
            ],
            "protection_disable_request_id_sha256": receipt[
                "mutation_outcomes"
            ]["protection_disable"]["request_id_sha256"],
            "protection_disable_request_body_sha256": receipt[
                "mutation_outcomes"
            ]["protection_disable"]["request_body_sha256"],
            "protection_disable_client_token_sha256": receipt[
                "mutation_outcomes"
            ]["protection_disable"]["client_token_sha256"],
            "delete_request_id_sha256": receipt["mutation_outcomes"][
                "delete"
            ]["request_id_sha256"],
            "delete_request_body_sha256": receipt["mutation_outcomes"][
                "delete"
            ]["request_body_sha256"],
            "delete_client_token_present": False,
            "consumed_mutation_identity_set_sha256": receipt[
                "mutation_outcomes"
            ]["ordered_mutation_set_sha256"],
            "post_action_observed_at_utc": receipt["observed_at_utc"],
            "terminal_accepted_at_utc": "2026-08-17T02:00:00Z",
        }
        return (
            receipt,
            evidence,
            checkpoint,
            receipt_raw,
            evidence_raw,
            checkpoint_raw,
            authority_binding,
        )

    def run_terminal_fixture(
        self,
        authority_binding,
        *,
        control_contains_artifact=False,
        checkpoint_appears_at_evidence=False,
        terminal_artifact_drift=False,
    ):
        (
            _receipt,
            _evidence,
            _checkpoint,
            receipt_raw,
            evidence_raw,
            checkpoint_raw,
            _original_authority,
        ) = self.terminal_fixture()
        by_name = {
            Path(verifier.RECEIPT_REF).name: receipt_raw,
            Path(verifier.EVIDENCE_REF).name: evidence_raw,
            Path(verifier.CHECKPOINT_REF).name: checkpoint_raw,
        }

        def read_artifact(path):
            return by_name[Path(path).name]

        def blob_absent(revision, ref, *, root):
            if revision == control_revision:
                return not control_contains_artifact
            if revision == "2" * 40 and ref == verifier.CHECKPOINT_REF:
                return not checkpoint_appears_at_evidence
            return False

        def blob_bytes(revision, ref, *, root):
            if revision not in {"2" * 40, "3" * 40}:
                raise ValueError("unexpected revision")
            if (
                terminal_artifact_drift
                and revision == "3" * 40
                and ref == verifier.CHECKPOINT_REF
            ):
                return b"drift\n"
            return by_name[Path(ref).name]

        with mock.patch.object(
            verifier, "_read_repo_artifact", side_effect=read_artifact
        ), mock.patch.object(
            verifier,
            "validate_authority_bundle",
            return_value=([], authority_binding),
        ), mock.patch.object(
            verifier, "revision_is_strict_ancestor", return_value=True
        ), mock.patch.object(
            verifier, "git_blob_absent", side_effect=blob_absent
        ), mock.patch.object(
            verifier, "git_blob_bytes", side_effect=blob_bytes
        ):
            return verifier.validate_terminal_artifacts(root=ROOT)

    def test_terminal_artifacts_bind_git_stages_and_raw_authority(self):
        fixture = self.terminal_fixture()
        errors, binding = self.run_terminal_fixture(fixture[-1])
        self.assertEqual(errors, [])
        self.assertEqual(binding["status"], verifier.TERMINAL_STATUS)
        self.assertFalse(binding["readiness"]["readiness_credit_added"])

    def test_signed_but_semantically_drifted_receipt_is_rejected(self):
        authority_binding = copy.deepcopy(self.terminal_fixture()[-1])
        authority_binding["protection_disable_request_body_sha256"] = (
            "f" * 64
        )
        errors, binding = self.run_terminal_fixture(authority_binding)
        self.assertIn(
            "manual cost-stop receipt/raw authority mismatch", errors
        )
        self.assertIsNone(binding)

    def test_terminal_rejects_artifact_present_at_control_revision(self):
        authority_binding = self.terminal_fixture()[-1]
        errors, binding = self.run_terminal_fixture(
            authority_binding,
            control_contains_artifact=True,
        )
        self.assertIn(
            "manual cost-stop control revision contains artifact", errors
        )
        self.assertIsNone(binding)

    def test_terminal_rejects_checkpoint_before_m2(self):
        authority_binding = self.terminal_fixture()[-1]
        errors, binding = self.run_terminal_fixture(
            authority_binding,
            checkpoint_appears_at_evidence=True,
        )
        self.assertIn(
            "manual cost-stop checkpoint appeared before terminal", errors
        )
        self.assertIsNone(binding)

    def test_terminal_rejects_m2_artifact_drift(self):
        authority_binding = self.terminal_fixture()[-1]
        errors, binding = self.run_terminal_fixture(
            authority_binding,
            terminal_artifact_drift=True,
        )
        self.assertIn(
            "manual cost-stop terminal revision artifact mismatch", errors
        )
        self.assertIsNone(binding)

    def test_evidence_uses_the_single_authority_root_constant(self):
        self.assertEqual(
            verifier.EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
            authority.EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
        )
        self.assertTrue(verifier.MANUAL_RAW_EXTRACTOR_FINALIZED)


if __name__ == "__main__":
    unittest.main()
