import base64
import copy
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_item26_manual_cost_stop_authority_v1 as authority  # noqa: E402
import extract_item26_manual_cost_stop_raw_v1 as raw_extractor  # noqa: E402
import tests.test_extract_item26_manual_cost_stop_raw_v1 as raw_fixtures  # noqa: E402


def key_row(role):
    raw = ("test-public-key-" + role).encode("ascii")
    return {
        "issuer": f"noteai-item26-manual-cost-stop-{role}-v1",
        "audience": "noteai-item26-manual-cost-stop-verifier-v1",
        "public_key_pem_base64": base64.b64encode(raw).decode("ascii"),
        "public_key_sha256": authority._sha(raw),
        "public_key_spki_sha256": authority._sha(raw + b"-spki"),
    }


def root_object():
    return {
        "schema": authority.ROOT_SCHEMA,
        "task_id": authority.TASK_ID,
        "operation_id": authority.OPERATION_ID,
        "status": "FROZEN_BEFORE_POST_ACTION_READBACK",
        "repository": authority.REPOSITORY,
        "source_ref": authority.SOURCE_REF,
        "m0_anchor_revision": authority.M0_ANCHOR_REVISION,
        "m0_ci": copy.deepcopy(authority.EXPECTED_M0_CI),
        "root_frozen_before_action": False,
        "post_action_readback_only": True,
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
        "contract": {
            "ref": authority.CONTRACT_REF,
            "file_sha256": authority.EXPECTED_CONTRACT_FILE_SHA256,
        },
        "no_replay": {
            "ref": authority.NO_REPLAY_REF,
            "file_sha256": authority.EXPECTED_NO_REPLAY_FILE_SHA256,
            "registry_sha256": authority.EXPECTED_NO_REPLAY_REGISTRY_SHA256,
            "entry_count": 29,
            "consumed_manual_mutation_set_sha256": (
                authority.EXPECTED_MUTATION_SET_SHA256
            ),
        },
        "ledger_context": {
            "handoff_ref": authority.HANDOFF_REF,
            "handoff_revision": authority.M0_ANCHOR_REVISION,
            "handoff_file_sha256": authority.EXPECTED_HANDOFF_FILE_SHA256,
            "ledger_context_revision": authority.LEDGER_CONTEXT_REVISION,
            "source_pre_tuple_sha256": (
                authority.EXPECTED_SOURCE_PRE_TUPLE_SHA256
            ),
            "historical_confirmation": {
                "projection": {
                    "task_id": authority.TASK_ID,
                    "operation_id": authority.OPERATION_ID,
                    "action": "IMMEDIATE_EXACT_OLD_CLONE_COST_STOP",
                    "confirmed_at_utc": "2026-08-16T14:39:11.475Z",
                    "old_clone_sha256": (
                        "820121638125fcebe3b7c03f3416ddae1fef1a0a9f1de731320fa75dd69a1525"
                    ),
                    "allowed_mutations": [
                        "ModifyDBInstanceDeletionProtection",
                        "DeleteDBInstance",
                    ],
                    "future_fee_reusable": False,
                    "root_frozen_before_action": False,
                },
                "projection_sha256": (
                    authority.EXPECTED_HISTORICAL_CONFIRMATION_SHA256
                ),
                "reusable_for_future_fee": False,
                "retroactive_root_authority": False,
            },
            "old_clone_create_identity_requires_actiontrail_rederivation": True,
        },
        "provider": key_row("provider"),
        "confirmation": key_row("confirmation"),
        "ci": key_row("ci"),
    }


class ManualCostStopAuthorityTests(unittest.TestCase):
    def make_directory(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name) / "authority"
        directory.mkdir(mode=0o700)
        raw = authority.canonical_bytes(root_object())
        path = directory / authority.ROOT_FILE
        path.write_bytes(raw)
        path.chmod(0o600)
        return directory, raw

    def root_patches(self, raw, *, duplicate_spki=False):
        digest = authority._sha(raw)
        patchers = [
            mock.patch.object(authority, "ROOT_UID", os.getuid()),
            mock.patch.object(authority, "_validate_parent_chain"),
            mock.patch.object(
                authority,
                "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                digest,
            ),
            mock.patch.object(
                authority,
                "_git_blob_sha256",
                side_effect=lambda _revision, ref, root: {
                    authority.CONTRACT_REF: authority.EXPECTED_CONTRACT_FILE_SHA256,
                    authority.NO_REPLAY_REF: authority.EXPECTED_NO_REPLAY_FILE_SHA256,
                    authority.HANDOFF_REF: authority.EXPECTED_HANDOFF_FILE_SHA256,
                }[ref],
            ),
            mock.patch.object(authority, "_ancestor", return_value=True),
            mock.patch.object(
                authority,
                "_decode_key",
                side_effect=lambda _value, label: (
                    (label + "-key").encode("ascii"),
                    "a" * 64 if duplicate_spki else {
                        "provider": "a" * 64,
                        "confirmation": "b" * 64,
                        "ci": "c" * 64,
                    }[label],
                ),
            ),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        return digest

    def test_activation_root_is_exact_and_not_action_authority(self):
        directory, raw = self.make_directory()
        digest = self.root_patches(raw)
        binding = authority.load_activation_root(
            expected_control_revision="2" * 40,
            expected_authority_root_file_sha256=digest,
            root=ROOT,
            authority_directory=directory,
        )
        self.assertFalse(binding["root_frozen_before_action"])
        self.assertFalse(binding["authorizes_new_action"])
        self.assertFalse(binding["readiness_credit_allowed"])
        self.assertTrue(binding["authority_keys_distinct"])

    def test_activation_requires_exact_a0_predecessor(self):
        directory, raw = self.make_directory()
        digest = self.root_patches(raw)
        with mock.patch.object(
            authority,
            "_ancestor",
            side_effect=lambda earlier, later, root: (
                earlier != authority.A0_PREDECESSOR_REVISION
            ),
        ), self.assertRaisesRegex(ValueError, "control revision"):
            authority.load_activation_root(
                expected_control_revision="2" * 40,
                expected_authority_root_file_sha256=digest,
                root=ROOT,
                authority_directory=directory,
            )

    def test_extra_file_breaks_exact_inventory(self):
        directory, raw = self.make_directory()
        digest = self.root_patches(raw)
        extra = directory / "extra.json"
        extra.write_text("{}\n", encoding="ascii")
        extra.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "inventory"):
            authority.load_activation_root(
                expected_control_revision="2" * 40,
                expected_authority_root_file_sha256=digest,
                root=ROOT,
                authority_directory=directory,
            )

    def test_hardlink_root_is_rejected(self):
        directory, raw = self.make_directory()
        digest = self.root_patches(raw)
        outside = directory.parent / "root-hardlink.json"
        os.link(directory / authority.ROOT_FILE, outside)
        with self.assertRaisesRegex(ValueError, "file identity"):
            authority.load_activation_root(
                expected_control_revision="2" * 40,
                expected_authority_root_file_sha256=digest,
                root=ROOT,
                authority_directory=directory,
            )

    def test_group_writable_file_is_rejected(self):
        directory, raw = self.make_directory()
        digest = self.root_patches(raw)
        (directory / authority.ROOT_FILE).chmod(0o620)
        with self.assertRaisesRegex(ValueError, "file identity"):
            authority.load_activation_root(
                expected_control_revision="2" * 40,
                expected_authority_root_file_sha256=digest,
                root=ROOT,
                authority_directory=directory,
            )

    def test_same_spki_under_three_roles_is_rejected(self):
        directory, raw = self.make_directory()
        digest = self.root_patches(raw, duplicate_spki=True)
        with self.assertRaisesRegex(ValueError, "keys not distinct"):
            authority.load_activation_root(
                expected_control_revision="2" * 40,
                expected_authority_root_file_sha256=digest,
                root=ROOT,
                authority_directory=directory,
            )

    def test_default_final_bundle_fails_closed_before_credit(self):
        errors, binding = authority.validate_authority_bundle(
            expected_authority_root_file_sha256=(
                authority.EXPECTED_AUTHORITY_ROOT_FILE_SHA256
            ),
            expected_receipt_binding={
                "receipt_file_sha256": "1" * 64,
                "receipt_semantic_sha256": "2" * 64,
                "terminal_acceptance_sha256": "3" * 64,
                "raw_closure_sha256": "4" * 64,
            },
            root=ROOT,
        )
        self.assertTrue(errors)
        self.assertIsNone(binding)

    def test_ci_row_binds_the_complete_ordinary_workflow(self):
        revision = "2" * 40
        row = {
            "run_id": 1,
            "job_id": 2,
            "event": "push",
            "attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "head_sha": revision,
            "created_at_utc": "2026-08-17T00:59:58Z",
            "started_at_utc": "2026-08-17T00:59:59Z",
            "completed_at_utc": "2026-08-17T01:00:00Z",
            "dispatch_count": 1,
            "rerun_count": 0,
            "workflow_name": "CI",
            "workflow_path": ".github/workflows/ci.yml",
            "job_name": "test",
            "job_count": 1,
            "failed_step_count": 0,
            "step_count": 22,
            "unit_test_count": 2331,
            "postgres_test_count": 6,
            "readiness_check_count": 138,
            "quality_gate_pass_count": 7,
            "quality_expected_fail_count": 1,
            "error_annotation_count": 0,
            "compose_config_success": True,
        }
        self.assertTrue(
            authority._run_row(row, event="push", revision=revision)
        )
        for field, bad_value in (
            ("attempt", True),
            ("dispatch_count", True),
            ("rerun_count", 1),
            ("started_at_utc", "2026-08-17T01:00:01Z"),
            ("workflow_path", ".github/workflows/other.yml"),
            ("job_name", "other"),
            ("failed_step_count", 1),
            ("quality_gate_pass_count", "7"),
            ("postgres_test_count", 0),
            ("readiness_check_count", 137),
            ("compose_config_success", False),
        ):
            changed = copy.deepcopy(row)
            changed[field] = bad_value
            self.assertFalse(
                authority._run_row(
                    changed, event="push", revision=revision
                ),
                field,
            )

    def validate_final_bundle_fixture(
        self,
        *,
        early_evidence=False,
        source_drift_ref=None,
        reuse_a0_evidence_run=False,
    ):
        control_revision = raw_fixtures.CONTROL_REVISION
        evidence_revision = "3" * 40
        terminal_revision = "4" * 40
        old_clone_sha256 = raw_extractor.value_sha256(
            raw_fixtures.CLONE_ID
        )
        source_sha256 = raw_extractor.value_sha256(
            raw_fixtures.SOURCE_ID
        )
        source_name_sha256 = raw_extractor.value_sha256(
            raw_fixtures.SOURCE_NAME
        )
        old_clone_name_sha256 = raw_extractor.value_sha256(
            raw_fixtures.SOURCE_NAME.replace("source", "old-clone")
        )
        protection_request = "test-protection-provider-request"
        deletion_request = "test-delete-provider-request"
        protection_marker = "test-protection-idempotency-marker"
        protection_request_sha256 = raw_extractor.value_sha256(
            protection_request
        )
        deletion_request_sha256 = raw_extractor.value_sha256(
            deletion_request
        )
        protection_marker_sha256 = raw_extractor.value_sha256(
            protection_marker
        )

        def run_row(
            run_id,
            event,
            revision,
            started_at,
            completed_at,
        ):
            return {
                "run_id": run_id,
                "job_id": run_id + 100,
                "event": event,
                "attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "head_sha": revision,
                "created_at_utc": started_at,
                "started_at_utc": started_at,
                "completed_at_utc": completed_at,
                "dispatch_count": 1,
                "rerun_count": 0,
                "workflow_name": "CI",
                "workflow_path": ".github/workflows/ci.yml",
                "job_name": "test",
                "job_count": 1,
                "failed_step_count": 0,
                "step_count": 22,
                "unit_test_count": 2331,
                "postgres_test_count": 6,
                "readiness_check_count": 138,
                "quality_gate_pass_count": 7,
                "quality_expected_fail_count": 1,
                "error_annotation_count": 0,
                "compose_config_success": True,
            }

        control_sources = {
            ref: authority._sha(ref.encode("ascii"))
            for ref in authority.REQUIRED_CONTROL_SOURCE_REFS
        }
        root_raw = authority.canonical_bytes(root_object())
        root_sha256 = authority._sha(root_raw)
        control_push = run_row(
            1,
            "push",
            control_revision,
            "2026-08-17T00:00:00Z",
            "2026-08-17T00:00:01Z",
        )
        control_pull_request = run_row(
            2,
            "pull_request",
            control_revision,
            "2026-08-17T00:00:00.5Z",
            "2026-08-17T00:00:01.5Z",
        )
        activation_payload = {
            "schema": authority.ACTIVATION_RECEIPT_SCHEMA,
            "task_id": authority.TASK_ID,
            "operation_id": authority.OPERATION_ID,
            "status": "A1_ATTEMPT1_DUAL_CI_SUCCESS_ACTIVATED",
            "repository": authority.REPOSITORY,
            "ref": authority.SOURCE_REF,
            "a0_terminal": copy.deepcopy(authority.EXPECTED_A0_TERMINAL),
            "control_revision": control_revision,
            "authority_root_file_sha256": root_sha256,
            "source_file_sha256": {
                authority.COLLECTOR_REF: control_sources[
                    authority.COLLECTOR_REF
                ],
                authority.RAW_EXTRACTOR_REF: control_sources[
                    authority.RAW_EXTRACTOR_REF
                ],
                authority.VERIFIER_REF: control_sources[
                    authority.VERIFIER_REF
                ],
                authority.CI_WORKFLOW_REF: control_sources[
                    authority.CI_WORKFLOW_REF
                ],
            },
            "control_ci": {
                "push": control_push,
                "pull_request": control_pull_request,
            },
            "activated_at_utc": "2026-08-17T00:00:02Z",
            "readback_started": False,
            "cloud_call_count": 0,
            "database_connection_count": 0,
        }
        activation_envelope = {
            "authority": "ci",
            "issuer": root_object()["ci"]["issuer"],
            "audience": root_object()["ci"]["audience"],
            "payload": activation_payload,
            "signature_base64": base64.b64encode(b"signature").decode(
                "ascii"
            ),
        }
        activation_raw = authority.canonical_bytes(activation_envelope)
        provider_value = raw_fixtures.provider_capture()
        actiontrail_value = raw_fixtures.actiontrail_capture()
        for capture in (provider_value, actiontrail_value):
            capture["collector_source_sha256"] = control_sources[
                authority.COLLECTOR_REF
            ]
            capture["extractor_source_sha256"] = control_sources[
                authority.RAW_EXTRACTOR_REF
            ]
            capture["authority_source_sha256"] = control_sources[
                authority.VERIFIER_REF
            ]
            capture["activation_receipt_sha256"] = authority._sha(
                activation_raw
            )
        first_page = raw_extractor.decode_canonical_json(
            actiontrail_value["records"][0]["response_json_base64"],
            "fixture",
        )
        first_page["Events"][0]["requestId"] = protection_request
        first_page["Events"][0]["requestParameters"] = {
            "ClientToken": protection_marker,
            "DBInstanceId": raw_fixtures.CLONE_ID,
            "DeletionProtection": False,
        }
        actiontrail_value["records"][0]["response_json_base64"] = (
            raw_fixtures.encoded(first_page)
        )
        second_page = raw_extractor.decode_canonical_json(
            actiontrail_value["records"][1]["response_json_base64"],
            "fixture",
        )
        second_page["Events"][0]["requestId"] = deletion_request
        second_page["Events"][0]["requestParameters"] = {
            "DBInstanceId": raw_fixtures.CLONE_ID,
        }
        actiontrail_value["records"][1]["response_json_base64"] = (
            raw_fixtures.encoded(second_page)
        )
        provider_raw = raw_extractor.canonical_bytes(provider_value)
        actiontrail_raw = raw_extractor.canonical_bytes(actiontrail_value)
        billing_response_raw = base64.b64decode(
            provider_value["records"][2]["response_json_base64"],
            validate=True,
        )

        with ExitStack() as stack:
            for name, value in (
                ("EXPECTED_OLD_CLONE_SHA256", old_clone_sha256),
                ("EXPECTED_OLD_CLONE_NAME_SHA256", old_clone_name_sha256),
                ("EXPECTED_SOURCE_SHA256", source_sha256),
                ("EXPECTED_SOURCE_NAME_SHA256", source_name_sha256),
                (
                    "EXPECTED_BILLING_RESPONSE_SHA256",
                    raw_extractor.sha256(billing_response_raw),
                ),
                (
                    "EXPECTED_PROTECTION_REQUEST_ID_SHA256",
                    protection_request_sha256,
                ),
                (
                    "EXPECTED_DELETE_REQUEST_ID_SHA256",
                    deletion_request_sha256,
                ),
                (
                    "EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256",
                    protection_marker_sha256,
                ),
            ):
                stack.enter_context(
                    mock.patch.object(raw_extractor, name, value)
                )
            projection = raw_extractor.extract_verified_projection(
                provider_raw,
                actiontrail_raw,
                expected_control_revision=control_revision,
            )
            provider_projection = projection.provider
            actiontrail_projection = projection.actiontrail
            events = {
                row["event_name"]: row
                for row in actiontrail_projection["events"]
            }
            mutation_set_sha256 = (
                authority.consumed_mutation_identity_set_sha256(
                    protection_request_id_sha256=events[
                        "ModifyDBInstanceDeletionProtection"
                    ]["provider_request_id_sha256"],
                    protection_request_body_sha256=events[
                        "ModifyDBInstanceDeletionProtection"
                    ]["request_body_sha256"],
                    protection_client_token_sha256=events[
                        "ModifyDBInstanceDeletionProtection"
                    ]["client_token_sha256"],
                    delete_request_id_sha256=events[
                        "DeleteDBInstance"
                    ]["provider_request_id_sha256"],
                    delete_request_body_sha256=events[
                        "DeleteDBInstance"
                    ]["request_body_sha256"],
                    delete_client_token_present=events[
                        "DeleteDBInstance"
                    ]["client_token_present"],
                )
            )
            for name, value in (
                ("EXPECTED_OLD_CLONE_SHA256", old_clone_sha256),
                ("EXPECTED_OLD_CLONE_NAME_SHA256", old_clone_name_sha256),
                (
                    "EXPECTED_SOURCE_PRE_TUPLE_SHA256",
                    provider_projection["source"]["tuple_sha256"],
                ),
                ("EXPECTED_MUTATION_SET_SHA256", mutation_set_sha256),
                (
                    "EXPECTED_PROTECTION_REQUEST_ID_SHA256",
                    protection_request_sha256,
                ),
                (
                    "EXPECTED_DELETE_REQUEST_ID_SHA256",
                    deletion_request_sha256,
                ),
                (
                    "EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256",
                    protection_marker_sha256,
                ),
            ):
                stack.enter_context(mock.patch.object(authority, name, value))

            receipt_binding = {
                "receipt_file_sha256": "1" * 64,
                "receipt_semantic_sha256": "2" * 64,
                "terminal_acceptance_sha256": "3" * 64,
                "raw_closure_sha256": "4" * 64,
            }
            confirmation = {
                "schema": authority.CONFIRMATION_SCHEMA,
                "task_id": authority.TASK_ID,
                "operation_id": authority.OPERATION_ID,
                "control_revision": control_revision,
                "confirmed_at_utc": "2026-08-17T00:00:15.475Z",
                "post_action_observed_at_utc": provider_projection[
                    "observed_at_utc"
                ],
                "authority_root_file_sha256": root_sha256,
                **receipt_binding,
                "provider_projection_sha256": authority._semantic(
                    provider_projection
                ),
                "actiontrail_projection_sha256": authority._semantic(
                    actiontrail_projection
                ),
                "historical_user_confirmation_sha256": (
                    authority.EXPECTED_HISTORICAL_CONFIRMATION_SHA256
                ),
                "no_replay_registry_sha256": (
                    authority.EXPECTED_NO_REPLAY_REGISTRY_SHA256
                ),
                "consumed_mutation_identity_set_sha256": (
                    mutation_set_sha256
                ),
                "retroactive_action_authorization": False,
                "new_action_authorization": False,
                "readiness_credit_added": False,
            }
            create = actiontrail_projection["clone_create"]
            provider = {
                "schema": authority.PROVIDER_SCHEMA,
                "task_id": authority.TASK_ID,
                "operation_id": authority.OPERATION_ID,
                "control_revision": control_revision,
                "observed_at_utc": provider_projection["observed_at_utc"],
                "signed_at_utc": "2026-08-17T00:00:16.475Z",
                "authority_root_file_sha256": root_sha256,
                "provider_raw_file_sha256": authority._sha(provider_raw),
                "actiontrail_raw_file_sha256": authority._sha(
                    actiontrail_raw
                ),
                "provider_projection_sha256": authority._semantic(
                    provider_projection
                ),
                "actiontrail_projection_sha256": authority._semantic(
                    actiontrail_projection
                ),
                **receipt_binding,
                "confirmation_export_semantic_sha256": authority._semantic(
                    confirmation
                ),
                "historical_confirmation_sha256": (
                    authority.EXPECTED_HISTORICAL_CONFIRMATION_SHA256
                ),
                "old_clone_sha256": old_clone_sha256,
                "old_clone_name_sha256": old_clone_name_sha256,
                "source_pre_tuple_sha256": provider_projection[
                    "source"
                ]["tuple_sha256"],
                "source_post_tuple_sha256": provider_projection[
                    "source"
                ]["tuple_sha256"],
                "billing_snapshot_sha256": authority._semantic(
                    provider_projection["billing"]
                ),
                "no_replay_registry_sha256": (
                    authority.EXPECTED_NO_REPLAY_REGISTRY_SHA256
                ),
                "old_clone_create_request_sha256": create[
                    "provider_request_id_sha256"
                ],
                "old_clone_create_body_sha256": create[
                    "request_body_sha256"
                ],
                "old_clone_client_token_sha256": create[
                    "client_token_sha256"
                ],
                "protection_disable_request_id_sha256": events[
                    "ModifyDBInstanceDeletionProtection"
                ]["provider_request_id_sha256"],
                "protection_disable_request_body_sha256": events[
                    "ModifyDBInstanceDeletionProtection"
                ]["request_body_sha256"],
                "protection_disable_client_token_sha256": events[
                    "ModifyDBInstanceDeletionProtection"
                ]["client_token_sha256"],
                "delete_request_id_sha256": events["DeleteDBInstance"][
                    "provider_request_id_sha256"
                ],
                "delete_request_body_sha256": events["DeleteDBInstance"][
                    "request_body_sha256"
                ],
                "delete_client_token_present": False,
                "consumed_mutation_identity_set_sha256": (
                    mutation_set_sha256
                ),
                "old_clone_absent": True,
                "source_unchanged": True,
                "historical_billing_only": True,
                "new_action_authorized": False,
                "readiness_credit_added": False,
            }

            def envelope(role, payload):
                row = root_object()[role]
                return {
                    "authority": role,
                    "issuer": row["issuer"],
                    "audience": row["audience"],
                    "payload": payload,
                    "signature_base64": base64.b64encode(b"signature").decode(
                        "ascii"
                    ),
                }

            evidence_pull_completed = (
                "2026-08-17T00:00:09.475Z"
                if early_evidence
                else "2026-08-17T00:00:12.475Z"
            )
            ci = {
                "schema": authority.CI_SCHEMA,
                "task_id": authority.TASK_ID,
                "operation_id": authority.OPERATION_ID,
                "control_revision": control_revision,
                "evidence_revision": evidence_revision,
                "terminal_revision": terminal_revision,
                "repository": authority.REPOSITORY,
                "ref": authority.SOURCE_REF,
                "authority_root_file_sha256": root_sha256,
                "provider_export_semantic_sha256": authority._semantic(
                    provider
                ),
                "confirmation_export_semantic_sha256": authority._semantic(
                    confirmation
                ),
                "provider_raw_file_sha256": authority._sha(provider_raw),
                "actiontrail_raw_file_sha256": authority._sha(
                    actiontrail_raw
                ),
                **receipt_binding,
                "evidence_file_sha256": "5" * 64,
                "checkpoint_file_sha256": "6" * 64,
                "control_sources": control_sources,
                "control_push": control_push,
                "control_pull_request": control_pull_request,
                "evidence_push": run_row(
                    3,
                    "push",
                    evidence_revision,
                    "2026-08-17T00:00:10.975Z",
                    "2026-08-17T00:00:11.475Z",
                ),
                "evidence_pull_request": run_row(
                    4,
                    "pull_request",
                    evidence_revision,
                    (
                        "2026-08-17T00:00:08.975Z"
                        if early_evidence
                        else "2026-08-17T00:00:11.975Z"
                    ),
                    evidence_pull_completed,
                ),
                "terminal_push": run_row(
                    5,
                    "push",
                    terminal_revision,
                    "2026-08-17T00:00:12.975Z",
                    "2026-08-17T00:00:13.475Z",
                ),
                "terminal_pull_request": run_row(
                    6,
                    "pull_request",
                    terminal_revision,
                    "2026-08-17T00:00:13.975Z",
                    "2026-08-17T00:00:14.475Z",
                ),
                "terminal_accepted_at_utc": "2026-08-17T00:00:17.475Z",
            }
            if reuse_a0_evidence_run:
                ci["evidence_push"]["run_id"] = (
                    authority.EXPECTED_A0_TERMINAL["push"]["run_id"]
                )
                ci["evidence_push"]["job_id"] = (
                    authority.EXPECTED_A0_TERMINAL["push"]["job_id"]
                )
            provider_envelope = envelope("provider", provider)
            confirmation_envelope = envelope("confirmation", confirmation)
            ci_envelope = envelope("ci", ci)
            bundle = {
                "schema": authority.BUNDLE_SCHEMA,
                "task_id": authority.TASK_ID,
                "operation_id": authority.OPERATION_ID,
                "status": "POST_ACTION_RECONCILIATION_TERMINAL_AUTHORITY",
                "control_revision": control_revision,
                "evidence_revision": evidence_revision,
                "terminal_revision": terminal_revision,
                "provider": provider_envelope,
                "confirmation": confirmation_envelope,
                "ci": ci_envelope,
            }
            material = {
                authority.ROOT_FILE: root_raw,
                authority.PROVIDER_RAW_FILE: provider_raw,
                authority.ACTIONTRAIL_RAW_FILE: actiontrail_raw,
                authority.CONFIRMATION_FILE: authority.canonical_bytes(
                    confirmation_envelope
                ),
                authority.BUNDLE_FILE: authority.canonical_bytes(bundle),
            }
            runtime_material = {
                Path(authority.COLLECTOR_REF).name: (
                    authority.COLLECTOR_REF.encode("ascii")
                ),
                Path(authority.RAW_EXTRACTOR_REF).name: (
                    authority.RAW_EXTRACTOR_REF.encode("ascii")
                ),
                Path(authority.VERIFIER_REF).name: (
                    authority.VERIFIER_REF.encode("ascii")
                ),
                authority.ACTIVATION_RECEIPT_FILE: activation_raw,
            }
            root_value = root_object()
            keys = {
                "provider": (b"provider-key", "a" * 64),
                "confirmation": (b"confirmation-key", "b" * 64),
                "ci": (b"ci-key", "c" * 64),
            }
            stack.enter_context(
                mock.patch.object(
                    authority,
                    "_read_exact_directory",
                    side_effect=lambda directory, _inventory: (
                        runtime_material
                        if directory == authority.RUNTIME_DIRECTORY
                        else material
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    authority,
                    "_validate_root",
                    return_value=(root_value, keys),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    authority, "_verify_signature", return_value=True
                )
            )
            stack.enter_context(
                mock.patch.object(authority, "_ancestor", return_value=True)
            )
            stack.enter_context(
                mock.patch.object(
                    authority,
                    "_git_blob_sha256",
                    side_effect=lambda _revision, ref, root: (
                        "f" * 64
                        if ref == source_drift_ref
                        else control_sources[ref]
                    ),
                )
            )
            return authority.validate_authority_bundle(
                expected_authority_root_file_sha256=(
                    authority.EXPECTED_AUTHORITY_ROOT_FILE_SHA256
                ),
                expected_receipt_binding=receipt_binding,
                root=ROOT,
            )

    def test_final_authority_bundle_is_constructible_without_hash_cycle(self):
        errors, binding = self.validate_final_bundle_fixture()
        self.assertEqual(errors, [])
        self.assertIsNotNone(binding)
        self.assertFalse(binding["authorizes_new_action"])
        self.assertFalse(binding["readiness_credit_allowed"])

    def test_final_authority_rejects_one_early_evidence_ci_run(self):
        errors, binding = self.validate_final_bundle_fixture(
            early_evidence=True
        )
        self.assertTrue(any("timeline" in error for error in errors))
        self.assertIsNone(binding)

    def test_final_authority_rejects_collector_source_drift(self):
        errors, binding = self.validate_final_bundle_fixture(
            source_drift_ref=authority.COLLECTOR_REF,
        )
        self.assertTrue(
            any(
                "runtime activation" in error
                or "projection binding" in error
                for error in errors
            )
        )
        self.assertIsNone(binding)

    def test_final_authority_rejects_m1_reuse_of_a0_native_run(self):
        errors, binding = self.validate_final_bundle_fixture(
            reuse_a0_evidence_run=True,
        )
        self.assertTrue(any("historical CI run reuse" in row for row in errors))
        self.assertIsNone(binding)

    def test_production_root_hash_is_frozen_and_nonempty(self):
        self.assertTrue(authority.AUTHORITY_IMPLEMENTED)
        self.assertEqual(
            authority.EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
            "f0f7cfce319009ad696cf762f30ca25b2f237d4bda2f4f0643baeea409514f3c",
        )


if __name__ == "__main__":
    unittest.main()
