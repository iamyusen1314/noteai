import copy
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_internal_zero_provider_smoke_evidence as verifier  # noqa: E402
import build_item27_internal_smoke_evidence_v1 as receipt_builder  # noqa: E402
import render_item27_internal_smoke_requests_v1 as request_renderer  # noqa: E402
from tests.test_build_item27_internal_smoke_evidence_v1 import (  # noqa: E402
    make_capture as make_raw_capture,
)


def _projection(path, status=200, **values):
    return {"path": path, "status": status, **values}


def _endpoints(mode):
    if mode not in {"api-c", "api-f"}:
        return []
    rows = [
        _projection(
            "/health/live", service="noteai-api", state="ok"
        ),
        _projection(
            "/health/ready", service="noteai-api", state="ready",
            checks=["database", "model"],
        ),
        _projection("/legal/contracts", sha256="a" * 64),
        _projection("/billing/tiers", sha256="b" * 64),
        _projection(
            "/payments/capabilities", ordering_available=False,
            currency="CNY", auto_renewal=False,
        ),
    ]
    if mode == "api-c":
        rows.extend([
            _projection(
                "/health/live", service="noteai-admin", state="ok"
            ),
            _projection(
                "/health/ready", service="noteai-admin", state="ready",
                checks=["database", "model"],
            ),
            _projection(
                "/admin/capabilities", 403, authorization="REJECTED"
            ),
        ])
    return rows


def _role(role):
    value = {
        "role": role,
        "health_passed": True,
        "suspended_one_shot_passed": role != "payment",
        "expected_negative_passed": role == "payment",
    }
    if role == "dispatcher":
        value.update({"pending_outbox": 2, "exhausted_outbox": 0})
    elif role == "worker":
        value.update({
            "needs_manual": 0,
            "expired_ready": 0,
            "stale_provider_outcome": 0,
            "recoverable_unstarted": 1,
        })
    elif role == "trends":
        value["provider_attempt_counts"] = {
            "active": 0, "unknown": 0, "unlinked": 0,
        }
    elif role == "tracking":
        value["provider_attempt_counts"] = {
            "active": 0, "stale": 0, "unlinked": 0,
        }
    return value


def _result(mode, roles):
    endpoints = _endpoints(mode)
    return {
        "schema": verifier.RESULT_SCHEMA,
        "task_id": verifier.TASK_ID,
        "status": "PASS",
        "mode": mode,
        "loopback_endpoint_count": len(endpoints),
        "endpoint_projections": endpoints,
        "roles": [_role(role) for role in roles],
        "active_runtime_identity_unchanged": True,
        "public_listener_count": 0,
        "service_start_count": len(roles),
        "service_stop_count": len(roles),
        "original_state_restored": True,
        "provider_call_count": 0,
        "provider_attempt_count": 0,
        "oss_mutation_count": 0,
        "production_database_mutation_count": 0,
        "synthetic_record_count": 0,
        "public_request_count": 0,
        "cleanup": "RESTORED",
        "automatic_retry_allowed": False,
        "same_invocation_replay_allowed": False,
    }


def _h(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _ci_receipt(label, revision):
    event = "pull_request" if "pull" in label or label.endswith("-pr") else "push"
    return {
        "conclusion": "success",
        "run_attempt": 1,
        "exact_revision_verified": True,
        "run_id_sha256": _h(label + "-run"),
        "job_id_sha256": _h(label + "-job"),
        "step_count": 22,
        "unit_test_count": 2100,
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "error_annotation_count": 0,
        "revision": revision,
        "repository": verifier.REPOSITORY,
        "ref": verifier.SOURCE_REF,
        "event": event,
        "head_sha": revision,
    }


def _provider_receipt(
    action, mode, revision, result, ordinal, predecessor_acceptance
):
    _input, _request, _fixture_result, capture = make_raw_capture(
        action, predecessor_acceptance
    )
    results = json.loads(capture["terminal-describe-results.json"])
    results["Invocation"]["InvocationResults"]["InvocationResult"][0][
        "Output"
    ] = base64.b64encode(verifier._canonical_bytes(result)).decode("ascii")
    capture["terminal-describe-results.json"] = verifier._canonical_bytes(results)
    receipt = receipt_builder.build_receipt(
        action=action,
        source_revision=revision,
        observed_at_utc=f"2026-08-13T01:01:0{ordinal}Z",
        capture=capture,
    )
    if receipt["mode"] != mode:
        raise AssertionError("fixture mode")
    return receipt


def make_closure():
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    invocations = []
    receipts = {}
    item26_terminal_acceptance = _h("item26-terminal-acceptance")
    predecessor_acceptance = item26_terminal_acceptance
    for ordinal, (action, mode, _endpoint_count, roles) in enumerate(
        verifier.ACTION_ROWS, 1
    ):
        result = _result(mode, roles)
        receipt = _provider_receipt(
            action, mode, revision, result, ordinal, predecessor_acceptance
        )
        receipts[action] = receipt
        request = receipt["request"]
        terminal = receipt["terminal_readback"]
        result_binding = receipt["result_binding"]
        invocations.append({
            "ordinal": ordinal,
            "action": action,
            "mode": mode,
            "provider_terminal_status": "Finished",
            "provider_result_status": "Success",
            "provider_command_count": 1,
            "provider_invocation_count": 1,
            "provider_result_count": 1,
            "exit_code": 0,
            "dropped_count": 0,
            "repeat_count": 1,
            "automatic_retry_count": 0,
            "same_invocation_replay_allowed": False,
            **verifier._expected_command_binding(action),
            "receipt_ref": verifier.RECEIPT_REFS[action],
            "receipt_file_sha256": hashlib.sha256(
                verifier._canonical_bytes(receipt)
            ).hexdigest(),
            "receipt_semantic_sha256": verifier._semantic_sha256(receipt),
            "request_canonical_bytes": request["canonical_bytes"],
            "request_canonical_sha256": request["canonical_sha256"],
            "client_token_sha256": request["client_token_sha256"],
            "client_token_plan_sha256": request["client_token_plan_sha256"],
            "predecessor_acceptance_sha256": request[
                "predecessor_acceptance_sha256"
            ],
            "terminal_acceptance_sha256": receipt[
                "terminal_acceptance_sha256"
            ],
            "provider_start_time_utc": terminal[
                "provider_start_time_utc"
            ],
            "provider_finished_time_utc": terminal[
                "provider_finished_time_utc"
            ],
            "observed_at_utc": receipt["observed_at_utc"],
            "target_identity_sha256": request["target_identity_sha256"],
            "provider_request_id_sha256": request[
                "provider_request_id_sha256"
            ],
            "provider_command_id_sha256": request[
                "provider_command_id_sha256"
            ],
            "provider_invoke_id_sha256": terminal[
                "provider_invoke_id_sha256"
            ],
            "stdout_canonical_bytes": result_binding[
                "stdout_canonical_bytes"
            ],
            "stdout_canonical_sha256": result_binding[
                "stdout_canonical_sha256"
            ],
            "result": result,
        })
        predecessor_acceptance = receipt["terminal_acceptance_sha256"]
    payload = {
        "schema_version": 1,
        "task_id": verifier.TASK_ID,
        "status": "VERIFIED_CLEAN",
        "observed_at_utc": "2026-08-13T01:02:00Z",
        "source_binding": {
            "release_revision": revision,
            "branch": verifier.SOURCE_BRANCH,
            "origin_branch_ref": (
                "refs/remotes/origin/" + verifier.SOURCE_BRANCH
            ),
            "checkpoint_pushed": True,
            "exact_head_ci": {
                "push": _ci_receipt("push", revision),
                "pull_request": _ci_receipt("pull-request", revision),
                "parity_verified": True,
            },
            "item26_terminal_verified": True,
            "item26_terminal_acceptance_sha256": item26_terminal_acceptance,
            "fresh_runtime_baseline_sha256": _h("fresh-runtime-baseline"),
            "executor": {
                "path": verifier.EXECUTOR_REF,
                "sha256": hashlib.sha256(
                    (ROOT / verifier.EXECUTOR_REF).read_bytes()
                ).hexdigest(),
            },
            "request_renderer": {
                "path": verifier.RENDERER_REF,
                "sha256": hashlib.sha256(
                    (ROOT / verifier.RENDERER_REF).read_bytes()
                ).hexdigest(),
            },
            "raw_closure_builder": {
                "path": verifier.BUILDER_REF,
                "sha256": hashlib.sha256(
                    (ROOT / verifier.BUILDER_REF).read_bytes()
                ).hexdigest(),
            },
            "executor_result_validator": {
                "path": verifier.VALIDATOR_REF,
                "sha256": hashlib.sha256(
                    (ROOT / verifier.VALIDATOR_REF).read_bytes()
                ).hexdigest(),
            },
            "external_authority_verifier": {
                "path": verifier.AUTHORITY_VERIFIER_REF,
                "sha256": hashlib.sha256(
                    (ROOT / verifier.AUTHORITY_VERIFIER_REF).read_bytes()
                ).hexdigest(),
            },
            "action_order": [row[0] for row in verifier.ACTION_ROWS],
        },
        "invocations": invocations,
        "aggregate": {
            "command_count": 4,
            "invocation_count": 4,
            "terminal_result_count": 4,
            "pass_count": 4,
            "loopback_endpoint_count": 13,
            "role_count": 6,
            "service_start_count": 6,
            "service_stop_count": 6,
            "provider_call_count": 0,
            "provider_attempt_count": 0,
            "oss_mutation_count": 0,
            "production_database_mutation_count": 0,
            "synthetic_record_count": 0,
            "public_request_count": 0,
            "public_listener_count": 0,
            "automatic_retry_count": 0,
            "distinct_target_plan_slot_count": 4,
            "client_token_plan_count": 4,
            "unique_client_token_count": 4,
            "fresh_pre_dispatch_history_count": 0,
        },
        "final_runtime_state": {
            "dormant_unit_count": 6,
            "dormant_inactive_dead_disabled_count": 6,
            "task_root_residue_count": 0,
            "owned_container_residue_count": 0,
            "active_runtime_identity_unchanged": True,
            "original_state_restored": True,
            "api_c_api_healthy": True,
            "api_c_admin_healthy": True,
            "api_f_api_healthy": True,
            "new_public_listener_count": 0,
        },
        "mutation_counters": {
            "production_database_mutation_count": 0,
            "provider_attempt_count": 0,
            "provider_call_count": 0,
            "oss_mutation_count": 0,
            "synthetic_record_count": 0,
            "unit_file_write_count": 0,
            "service_enable_count": 0,
            "public_request_count": 0,
        },
        "cost_and_data_boundary": {
            "incremental_cost_cny": 0,
            "paid_resource_create_count": 0,
            "real_supplier_call_count": 0,
            "production_business_row_write_count": 0,
            "public_traffic_change_count": 0,
        },
        "secret_free_evidence": {
            "secret_value_count": 0,
            "private_key_value_count": 0,
            "complete_connection_string_count": 0,
            "resource_id_value_count": 0,
            "private_address_value_count": 0,
            "endpoint_value_count": 0,
            "raw_provider_body_value_emitted_count": 0,
            "raw_provider_body_commitment_count": len(
                verifier.PROVIDER_RAW_RESPONSE_FILES
            ) * 4,
            "provider_request_value_emitted_count": 0,
            "provider_request_commitment_count": len(
                verifier.PROVIDER_REQUEST_FILES
            ) * 4,
            "root_only_plan_input_value_emitted_count": 0,
            "root_only_plan_input_commitment_count": 4,
        },
        "readiness": copy.deepcopy(verifier.DEFAULT_READINESS),
    }
    return payload, receipts


def make_evidence():
    return make_closure()[0]


class InternalZeroProviderSmokeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.revision_binding = mock.patch.object(
            verifier, "_file_binding_at_revision", return_value=True
        )
        self.revision_binding.start()
        self.ancestry = mock.patch.object(
            verifier, "_git_is_ancestor", return_value=True
        )
        self.ancestry.start()

    def tearDown(self):
        self.ancestry.stop()
        self.revision_binding.stop()

    def assertHasError(self, payload, expected):
        _fixture, receipts = make_closure()
        errors = verifier.validate_document(
            payload, receipt_payloads=receipts
        )
        self.assertTrue(
            any(expected in error for error in errors),
            f"{expected!r} missing from {errors}",
        )

    def test_exact_document_and_manifest_binding_pass(self):
        payload, receipts = make_closure()
        evidence_revision = "1" * 40
        self.assertEqual(
            verifier.validate_document(payload, receipt_payloads=receipts), []
        )
        entries = [
            {"kind": "git", "ref": payload["source_binding"]["release_revision"]},
            {"kind": "git", "ref": evidence_revision},
            *[
                {"kind": "path", "ref": ref}
                for ref in sorted(verifier.REQUIRED_MANIFEST_PATH_REFS)
            ],
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / verifier.EVIDENCE_REF
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(payload), encoding="utf-8")
            for action, receipt in receipts.items():
                receipt_path = root / verifier.RECEIPT_REFS[action]
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                receipt_path.write_bytes(verifier._canonical_bytes(receipt))
            terminal_path = root / verifier.TERMINAL_CHECKPOINT_REF
            terminal_path.parent.mkdir(parents=True, exist_ok=True)
            terminal_path.write_bytes(verifier._canonical_bytes({
                "evidence_revision": evidence_revision,
            }))
            errors = verifier.validate_manifest_evidence(
                entries,
                root=root,
                expected_item26_terminal_acceptance_sha256=(
                    payload["source_binding"][
                        "item26_terminal_acceptance_sha256"
                    ]
                ),
                expected_readiness=verifier.DEFAULT_READINESS,
            )
            self.assertTrue(any(
                "Item27 independent prior authority unavailable" in error
                for error in errors
            ))

    def test_invented_commitments_without_raw_builder_closure_never_pass(self):
        payload, receipts = make_closure()
        del receipts["api_c"]["raw_closure"]
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any(
            "raw closure builder attestation missing" in error
            for error in errors
        ))

        payload, receipts = make_closure()
        receipts["api_c"]["result"]["status"] = "invented"
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any(
            "builder result/main evidence mismatch" in error
            for error in errors
        ))

    def test_item26_manifest_status_cannot_supply_terminal_acceptance(self):
        errors, acceptance = verifier.validate_item26_terminal_evidence([
            {"kind": "git", "ref": "0" * 40},
        ])
        self.assertEqual(len(errors), 1)
        self.assertTrue(
            errors[0].startswith("Item26 external authority invalid:")
        )
        self.assertIsNone(acceptance)

    def test_bundle_and_cli_hard_fail_without_independent_item26_acceptance(self):
        self.assertEqual(
            verifier.validate_bundle(),
            ["Item26 terminal acceptance digest is required"],
        )
        with mock.patch.object(
            verifier, "validate_item26_terminal_evidence",
            return_value=(["independent Item26 evidence unavailable"], None),
        ), mock.patch.object(
            verifier, "validate_bundle"
        ) as validate_bundle, mock.patch(
            "sys.argv", ["verify_internal_zero_provider_smoke_evidence.py"]
        ), mock.patch("builtins.print"):
            self.assertEqual(verifier.main(), 1)
        validate_bundle.assert_not_called()

    def test_source_requires_real_origin_ancestry(self):
        payload, receipts = make_closure()
        origin = "refs/remotes/origin/" + verifier.SOURCE_BRANCH
        with mock.patch.object(
            verifier,
            "_git_is_ancestor",
            side_effect=lambda _revision, descendant, **_kwargs: (
                descendant != origin
            ),
        ):
            errors = verifier.validate_document(
                payload, receipt_payloads=receipts
            )
        self.assertTrue(any(
            "source revision origin ancestry" in error for error in errors
        ))

    def test_terminal_checkpoint_binds_evidence_revision_ci_and_exact_blobs(self):
        payload, receipts = make_closure()
        source_revision = payload["source_binding"]["release_revision"]
        evidence_revision = "1" * 40
        current = {
            verifier.EVIDENCE_REF: verifier._canonical_bytes(payload),
            **{
                verifier.RECEIPT_REFS[action]: verifier._canonical_bytes(receipt)
                for action, receipt in receipts.items()
            },
        }
        refs = {
            verifier.EVIDENCE_REF,
            *verifier.RECEIPT_REFS.values(),
            verifier.BUILDER_REF,
            verifier.VALIDATOR_REF,
            verifier.AUTHORITY_VERIFIER_REF,
            verifier.EXECUTOR_REF,
            verifier.RENDERER_REF,
            "tools/verify_internal_zero_provider_smoke_evidence.py",
        }
        checkpoint = {
            "schema_version": 1,
            "schema": verifier.TERMINAL_CHECKPOINT_SCHEMA,
            "task_id": verifier.TASK_ID,
            "status": "EVIDENCE_CHECKPOINT_CI_VERIFIED",
            "observed_at_utc": "2026-08-13T02:00:00Z",
            "source_revision": source_revision,
            "evidence_revision": evidence_revision,
            "branch": verifier.SOURCE_BRANCH,
            "origin_branch_ref": (
                "refs/remotes/origin/" + verifier.SOURCE_BRANCH
            ),
            "checkpoint_pushed": True,
            "exact_head_ci": {
                "push": _ci_receipt("terminal-push", evidence_revision),
                "pull_request": _ci_receipt(
                    "terminal-pull-request", evidence_revision
                ),
                "parity_verified": True,
            },
            "blob_bindings": [
                {
                    "path": ref,
                    "sha256": hashlib.sha256(current[ref]).hexdigest()
                    if ref in current else _h("terminal-blob-" + ref),
                }
                for ref in sorted(refs)
            ],
        }
        with mock.patch.object(
            verifier, "_git_commit_exists", return_value=True
        ):
            errors, revision = verifier._validate_terminal_checkpoint(
                checkpoint, payload, receipts, root=ROOT
            )
        self.assertEqual(errors, [])
        self.assertEqual(revision, evidence_revision)

        changed = copy.deepcopy(checkpoint)
        changed["exact_head_ci"]["push"]["revision"] = source_revision
        with mock.patch.object(
            verifier, "_git_commit_exists", return_value=True
        ):
            errors, revision = verifier._validate_terminal_checkpoint(
                changed, payload, receipts, root=ROOT
            )
        self.assertTrue(any("CI did not pass" in error for error in errors))
        self.assertIsNone(revision)

    def test_signed_authority_requires_four_stage_ci_and_final_exact_blobs(self):
        payload, receipts = make_closure()
        source_revision = payload["source_binding"]["release_revision"]
        evidence_revision = "1" * 40
        terminal_revision = "2" * 40
        final_revision = "3" * 40
        evidence_ci = {
            "push": _ci_receipt("evidence-push", evidence_revision),
            "pull_request": _ci_receipt("evidence-pr", evidence_revision),
            "parity_verified": True,
        }
        checkpoint = {
            "evidence_revision": evidence_revision,
            "exact_head_ci": evidence_ci,
        }
        refs = {
            verifier.EVIDENCE_REF,
            verifier.TERMINAL_CHECKPOINT_REF,
            *verifier.RECEIPT_REFS.values(),
            verifier.EXECUTOR_REF,
            verifier.RENDERER_REF,
            verifier.BUILDER_REF,
            verifier.VALIDATOR_REF,
            verifier.AUTHORITY_VERIFIER_REF,
            "tools/verify_internal_zero_provider_smoke_evidence.py",
        }
        authority = {
            "schema_version": 1,
            "schema": "noteai.item27.ci-authority-export.v1",
            "task_id": verifier.TASK_ID,
            "status": "ALL_EXACT_REVISIONS_CI_VERIFIED",
            "immutable_artifact_sha256": "f" * 64,
            "source_revision": source_revision,
            "evidence_revision": evidence_revision,
            "terminal_revision": terminal_revision,
            "final_revision": final_revision,
            "stage_ci": {
                "source": copy.deepcopy(
                    payload["source_binding"]["exact_head_ci"]
                ),
                "evidence": evidence_ci,
                "terminal": {
                    "push": _ci_receipt("terminal-stage-push", terminal_revision),
                    "pull_request": _ci_receipt("terminal-stage-pr", terminal_revision),
                    "parity_verified": True,
                },
                "final": {
                    "push": _ci_receipt("final-stage-push", final_revision),
                    "pull_request": _ci_receipt("final-stage-pr", final_revision),
                    "parity_verified": True,
                },
            },
            "final_blob_bindings": [
                {"path": ref, "sha256": _h("final-blob-" + ref)}
                for ref in sorted(refs)
            ],
        }
        with mock.patch.object(
            verifier, "_git_commit_exists", return_value=True
        ), mock.patch.object(
            verifier, "_file_binding", return_value=True
        ):
            errors, revision = verifier._validate_external_ci_authority(
                authority, payload, receipts, checkpoint, root=ROOT
            )
        self.assertEqual(errors, [])
        self.assertEqual(revision, final_revision)

        changed = copy.deepcopy(authority)
        changed["stage_ci"]["final"]["push"]["conclusion"] = "failure"
        with mock.patch.object(
            verifier, "_git_commit_exists", return_value=True
        ), mock.patch.object(
            verifier, "_file_binding", return_value=True
        ):
            errors, revision = verifier._validate_external_ci_authority(
                changed, payload, receipts, checkpoint, root=ROOT
            )
        self.assertTrue(any("exact-HEAD CI did not pass" in error for error in errors))
        self.assertIsNone(revision)

        changed = copy.deepcopy(authority)
        changed["final_blob_bindings"].pop()
        with mock.patch.object(
            verifier, "_git_commit_exists", return_value=True
        ), mock.patch.object(
            verifier, "_file_binding", return_value=True
        ):
            errors, revision = verifier._validate_external_ci_authority(
                changed, payload, receipts, checkpoint, root=ROOT
            )
        self.assertIn("Item27 final trust-root blob bindings mismatch", errors)
        self.assertIsNone(revision)

    def test_manifest_refs_are_exact_without_duplicates_or_extras(self):
        payload, receipts = make_closure()
        evidence_revision = "1" * 40
        terminal_revision = "2" * 40
        final_revision = "3" * 40
        entries = [
            {"kind": "git", "ref": payload["source_binding"]["release_revision"]},
            {"kind": "git", "ref": evidence_revision},
            {"kind": "git", "ref": terminal_revision},
            {"kind": "git", "ref": final_revision},
            *[
                {"kind": "path", "ref": ref}
                for ref in sorted(verifier.REQUIRED_MANIFEST_PATH_REFS)
            ],
        ]
        for changed in (
            entries[:-1],
            [*entries, copy.deepcopy(entries[-1])],
            [*entries, {"kind": "path", "ref": "unexpected.json"}],
        ):
            with mock.patch.object(
                verifier, "load_evidence", return_value=payload
            ), mock.patch.object(
                verifier, "_load_terminal_checkpoint",
                return_value={"evidence_revision": evidence_revision},
            ), mock.patch.object(
                verifier, "_load_provider_receipts", return_value=receipts,
            ), mock.patch.object(
                verifier, "validate_authority_bundle",
                return_value=([], {
                    "terminal_revision": terminal_revision,
                    "final_revision": final_revision,
                }),
            ):
                errors = verifier.validate_manifest_evidence(
                    changed,
                    expected_item26_terminal_acceptance_sha256=(
                        payload["source_binding"][
                            "item26_terminal_acceptance_sha256"
                        ]
                    ),
                    expected_readiness=verifier.DEFAULT_READINESS,
                )
            self.assertEqual(errors, ["Item27 exact evidence refs required"])

    def test_rejects_invocation_reorder_nonterminal_exit_or_replay(self):
        payload = make_evidence()
        payload["invocations"][0], payload["invocations"][1] = (
            payload["invocations"][1], payload["invocations"][0]
        )
        self.assertHasError(payload, "invocation identity mismatch")

        cases = []
        for key, value in (
            ("provider_terminal_status", "Running"),
            ("exit_code", 4),
            ("repeat_count", 2),
            ("automatic_retry_count", 1),
            ("same_invocation_replay_allowed", True),
        ):
            payload = make_evidence()
            payload["invocations"][2][key] = value
            cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload["invocations"][2]):
                self.assertHasError(payload, "provider terminal result mismatch")

    def test_rejects_result_mutation_or_cleanup_drift(self):
        for key, value in (
            ("status", "UNKNOWN"),
            ("provider_call_count", 1),
            ("production_database_mutation_count", 1),
            ("service_stop_count", 0),
            ("cleanup", "UNKNOWN"),
            ("same_invocation_replay_allowed", True),
        ):
            payload = make_evidence()
            payload["invocations"][0]["result"][key] = value
            with self.subTest(key=key):
                self.assertHasError(payload, "PASS result semantics mismatch")

    def test_rejects_command_name_or_content_binding_drift(self):
        for key, value in (
            ("command_name", "other-command"),
            ("command_content_sha256", "0" * 64),
            ("wrapper_sha256", "1" * 64),
            ("executor_sha256", "2" * 64),
        ):
            payload = make_evidence()
            payload["invocations"][0][key] = value
            with self.subTest(key=key):
                self.assertHasError(payload, "command content binding mismatch")

    def test_rejects_provider_receipt_target_or_history_drift(self):
        payload, receipts = make_closure()
        receipts["api_f"]["request"]["target_count"] = 2
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any("RunCommand request" in error for error in errors))

        payload, receipts = make_closure()
        receipts["api_f"]["pre_dispatch"][
            "provider_client_token_readback_supported"
        ] = True
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any("history was not exact zero" in error for error in errors))

        for field, value in (
            ("provider_client_token_readback_supported", True),
            ("local_o_excl_plan_nonce_required", False),
            ("derived_client_token_commitment_count", 0),
        ):
            payload, receipts = make_closure()
            receipts["api_f"]["execution_boundary"][field] = value
            errors = verifier.validate_document(
                payload, receipt_payloads=receipts
            )
            with self.subTest(field=field):
                self.assertTrue(any(
                    "no-replay/retention boundary mismatch" in error
                    for error in errors
                ))

    def test_four_actions_require_exact_predecessor_acceptance_and_strict_provider_time(self):
        payload, receipts = make_closure()
        receipts["api_f"]["request"]["predecessor_acceptance_sha256"] = "f" * 64
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any(
            "predecessor terminal acceptance chain mismatch" in error
            for error in errors
        ))

        payload, receipts = make_closure()
        prior_finished = receipts["api_c"]["terminal_readback"][
            "provider_finished_time_utc"
        ]
        receipts["api_f"]["terminal_readback"][
            "provider_start_time_utc"
        ] = prior_finished
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any(
            "provider terminal timestamps are not strictly ordered" in error
            for error in errors
        ))

        payload, receipts = make_closure()
        receipts["worker_c"]["observed_at_utc"] = "2026-99-99T99:99:99Z"
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any(
            "terminal timestamps" in error or "identity mismatch" in error
            for error in errors
        ))

    def test_provider_signed_projection_contains_chain_and_refuses_time_reorder(self):
        payload, receipts = make_closure()
        projection = verifier._provider_authority_projection(receipts)
        self.assertEqual(
            [row["ordinal"] for row in projection["actions"]], [1, 2, 3, 4]
        )
        self.assertEqual(
            projection["actions"][0]["predecessor_acceptance_sha256"],
            payload["source_binding"]["item26_terminal_acceptance_sha256"],
        )
        for previous, current in zip(
            projection["actions"], projection["actions"][1:]
        ):
            self.assertEqual(
                current["predecessor_acceptance_sha256"],
                previous["terminal_acceptance_sha256"],
            )
            self.assertLess(
                previous["provider_finished_time_utc"],
                current["provider_start_time_utc"],
            )

        receipts["api_f"]["terminal_readback"]["provider_start_time_utc"] = (
            receipts["api_c"]["terminal_readback"]["provider_finished_time_utc"]
        )
        with self.assertRaisesRegex(ValueError, "chain/time ordering"):
            verifier._provider_authority_projection(receipts)

    def test_rejects_provider_raw_readback_stdout_or_receipt_binding_drift(self):
        payload, receipts = make_closure()
        receipts["worker_c"]["terminal_readback"][
            "describe_results_raw_sha256"
        ] = "not-a-sha"
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any("raw response commitment" in error for error in errors))

        payload, receipts = make_closure()
        receipts["worker_c"]["result_binding"][
            "stdout_canonical_sha256"
        ] = "0" * 64
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any("stdout/result binding" in error for error in errors))

        payload, receipts = make_closure()
        payload["invocations"][2]["receipt_file_sha256"] = "0" * 64
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any("receipt file binding" in error for error in errors))

    def test_rejects_duplicate_token_target_or_provider_identity_commitments(self):
        for field, section in (
            ("client_token_sha256", "request"),
            ("target_identity_sha256", "request"),
            ("provider_request_id_sha256", "request"),
            ("provider_command_id_sha256", "request"),
            ("provider_invoke_id_sha256", "terminal_readback"),
        ):
            payload, receipts = make_closure()
            receipts["api_f"][section][field] = receipts["api_c"][section][field]
            if field in {
                "target_identity_sha256", "provider_command_id_sha256",
            }:
                terminal = receipts["api_f"]["terminal_readback"]
                terminal[field] = receipts["api_f"][section][field]
            errors = verifier.validate_document(payload, receipt_payloads=receipts)
            with self.subTest(field=field):
                self.assertTrue(any("uniqueness mismatch" in error for error in errors))

    def test_rejects_unpushed_checkpoint_ci_or_item26_binding(self):
        payload, receipts = make_closure()
        payload["source_binding"]["checkpoint_pushed"] = False
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any(
            "source revision origin ancestry/projection" in error
            for error in errors
        ))

        payload, receipts = make_closure()
        payload["source_binding"]["exact_head_ci"]["push"]["conclusion"] = "failure"
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any("CI did not pass" in error for error in errors))

        for key, value in (
            ("repository", "other/repository"),
            ("ref", "refs/heads/other"),
            ("event", "pull_request"),
            ("head_sha", "0" * 40),
        ):
            payload, receipts = make_closure()
            payload["source_binding"]["exact_head_ci"]["push"][key] = value
            errors = verifier.validate_document(payload, receipt_payloads=receipts)
            with self.subTest(key=key):
                self.assertTrue(any("CI did not pass" in error for error in errors))

        payload, receipts = make_closure()
        payload["source_binding"]["item26_terminal_verified"] = False
        errors = verifier.validate_document(payload, receipt_payloads=receipts)
        self.assertTrue(any("Item26 terminal evidence" in error for error in errors))

        payload, receipts = make_closure()
        errors = verifier.validate_document(
            payload,
            receipt_payloads=receipts,
            expected_item26_terminal_acceptance_sha256="0" * 64,
        )
        self.assertTrue(any("Item26 terminal evidence" in error for error in errors))

        payload, receipts = make_closure()
        wrong_readiness = copy.deepcopy(verifier.DEFAULT_READINESS)
        wrong_readiness["internal_verified_before"] = 25
        errors = verifier.validate_document(
            payload,
            receipt_payloads=receipts,
            expected_readiness=wrong_readiness,
        )
        self.assertTrue(any("readiness transition" in error for error in errors))

    def test_rejects_endpoint_contract_or_cross_host_parity_drift(self):
        payload = make_evidence()
        payload["invocations"][0]["result"]["endpoint_projections"][7][
            "authorization"
        ] = "ALLOWED"
        self.assertHasError(payload, "Admin authorization projection mismatch")

        payload = make_evidence()
        payload["invocations"][1]["result"]["endpoint_projections"][2][
            "sha256"
        ] = "c" * 64
        self.assertHasError(payload, "projection parity mismatch")

    def test_rejects_role_or_provider_attempt_drift(self):
        payload = make_evidence()
        payload["invocations"][1]["result"]["roles"][0][
            "provider_attempt_counts"
        ]["unknown"] = 1
        self.assertHasError(payload, "Trends provider-attempt mismatch")

        payload = make_evidence()
        payload["invocations"][2]["result"]["roles"][0][
            "stale_provider_outcome"
        ] = 1
        self.assertHasError(payload, "worker counters mismatch")

    def test_rejects_source_binding_and_unknown_revision(self):
        payload = make_evidence()
        payload["source_binding"]["executor"]["sha256"] = "0" * 64
        _fixture, receipts = make_closure()
        with mock.patch.object(
            verifier, "_file_binding_at_revision", return_value=False
        ):
            errors = verifier.validate_document(
                payload, receipt_payloads=receipts
            )
        self.assertTrue(any(
            "executor revision binding mismatch" in error for error in errors
        ))

        payload = make_evidence()
        payload["source_binding"]["release_revision"] = "0" * 40
        self.assertHasError(payload, "release revision mismatch")

    def test_rejects_aggregate_final_state_mutation_and_readiness_overclaim(self):
        cases = (
            ("aggregate", "provider_call_count", 1, "aggregate mismatch"),
            (
                "final_runtime_state", "owned_container_residue_count", 1,
                "final runtime state mismatch",
            ),
            (
                "mutation_counters", "service_enable_count", 1,
                "mutation counters mismatch",
            ),
            (
                "cost_and_data_boundary", "incremental_cost_cny", 1,
                "cost/data boundary mismatch",
            ),
            (
                "secret_free_evidence", "resource_id_value_count", 1,
                "Secret-free evidence boundary mismatch",
            ),
            (
                "readiness", "public_launch_authorized", True,
                "readiness transition mismatch",
            ),
        )
        for section, key, value, error in cases:
            payload = make_evidence()
            payload[section][key] = value
            with self.subTest(section=section, key=key):
                self.assertHasError(payload, error)

    def test_rejects_boolean_integer_aliases(self):
        cases = []
        payload = make_evidence()
        payload["schema_version"] = True
        cases.append((payload, "schema version mismatch"))
        payload = make_evidence()
        payload["invocations"][0]["provider_command_count"] = True
        cases.append((payload, "provider terminal result mismatch"))
        payload = make_evidence()
        payload["invocations"][0]["result"]["provider_call_count"] = False
        cases.append((payload, "PASS result semantics mismatch"))
        payload = make_evidence()
        payload["invocations"][0]["result"]["roles"][0][
            "exhausted_outbox"
        ] = False
        cases.append((payload, "dispatcher counters mismatch"))
        payload = make_evidence()
        payload["aggregate"]["provider_call_count"] = False
        cases.append((payload, "aggregate mismatch"))
        payload = make_evidence()
        payload["cost_and_data_boundary"]["incremental_cost_cny"] = False
        cases.append((payload, "cost/data boundary mismatch"))
        for payload, error in cases:
            with self.subTest(error=error):
                self.assertHasError(payload, error)

    def test_loader_rejects_duplicates_and_non_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                verifier.load_evidence(path)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "root must be an object"):
                verifier.load_evidence(path)


class InternalZeroProviderSmokeRevisionBindingTests(unittest.TestCase):
    def test_revision_file_binding_rejects_wrong_git_blob(self):
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            stdout=subprocess.PIPE, text=True,
        ).stdout.strip()
        ref = "tools/internal_deployment_readiness_gate.py"
        blob = subprocess.run(
            ["git", "show", f"{revision}:{ref}"], cwd=ROOT, check=True,
            stdout=subprocess.PIPE,
        ).stdout
        value = {
            "path": ref,
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        self.assertTrue(verifier._file_binding_at_revision(
            value, ref, revision, root=ROOT
        ))
        value["sha256"] = "0" * 64
        self.assertFalse(verifier._file_binding_at_revision(
            value, ref, revision, root=ROOT
        ))


if __name__ == "__main__":
    unittest.main()
