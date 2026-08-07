import contextlib
import io
import os
import unittest
from unittest import mock

from deploy.production import durable_ai_acceptance as acceptance


class ProductionDurableAiAcceptanceTests(unittest.TestCase):
    def test_nonce_namespace_is_canonical_and_bounded(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        self.assertEqual(acceptance._canonical_nonce(nonce), nonce)
        self.assertEqual(
            acceptance._username(nonce),
            "naiacc_57c14a47f10d4bac845634cf",
        )
        self.assertLessEqual(len(acceptance._username(nonce)), 40)
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance._canonical_nonce("not-a-uuid")

    def test_mutation_confirmation_fails_before_storage_configuration(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_DEPLOYMENT_STAGE": "production",
                    "NOTEAI_RUNTIME_ROLE": "api",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
                    acceptance.CARRIER_ENV: acceptance.CARRIER_ROLE,
                    acceptance.CONFIRM_ENV: "",
                },
                clear=True,
            ),
            mock.patch.object(acceptance.db, "using_postgres", return_value=True),
            mock.patch.object(
                acceptance,
                "_api_database_role_matches",
                return_value=True,
            ),
            mock.patch.object(
                acceptance,
                "_carrier_role_matches",
                return_value=True,
            ),
            mock.patch.object(
                acceptance.private_storage,
                "configure_from_environment",
                side_effect=AssertionError("storage must not initialize"),
            ),
            self.assertRaisesRegex(
                acceptance.AcceptanceError,
                "confirmation_missing",
            ),
        ):
            acceptance._require_context(mutate=True)

    def test_provider_secret_presence_fails_closed(self):
        for secret_name in ("ANTHROPIC_API_KEY", "AMAP_WEB_KEY"):
            with (
                self.subTest(secret_name=secret_name),
                mock.patch.dict(
                    os.environ,
                    {
                        "NOTEAI_DEPLOYMENT_STAGE": "production",
                        "NOTEAI_RUNTIME_ROLE": "api",
                        "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
                        acceptance.CARRIER_ENV: acceptance.CARRIER_ROLE,
                        secret_name: "synthetic-never-print",
                    },
                    clear=True,
                ),
                mock.patch.object(
                    acceptance.db, "using_postgres", return_value=True
                ),
                mock.patch.object(
                    acceptance,
                    "_api_database_role_matches",
                    return_value=True,
                ),
                mock.patch.object(
                    acceptance,
                    "_carrier_role_matches",
                    return_value=True,
                ),
                self.assertRaisesRegex(
                    acceptance.AcceptanceError,
                    "provider_secret_present",
                ),
            ):
                acceptance._require_context(mutate=False)

    def test_api_database_role_requires_exact_session_and_current_role(self):
        with mock.patch.object(
            acceptance.db,
            "fetchone",
            return_value={
                "session_role": "noteai_app",
                "database_role": "noteai_app",
            },
        ):
            self.assertTrue(acceptance._api_database_role_matches())
        for row in (
            {"session_role": "task", "database_role": "noteai_app"},
            {"session_role": "noteai_app", "database_role": "noteai_admin"},
            None,
        ):
            with self.subTest(row=row), mock.patch.object(
                acceptance.db, "fetchone", return_value=row
            ):
                self.assertFalse(acceptance._api_database_role_matches())

    def test_carrier_role_requires_exact_env_and_immutable_marker(self):
        with mock.patch.dict(
            os.environ,
            {acceptance.CARRIER_ENV: acceptance.CARRIER_ROLE},
            clear=True,
        ), mock.patch.object(
            acceptance.Path,
            "read_text",
            return_value="ai-worker\n",
        ):
            self.assertTrue(acceptance._carrier_role_matches())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(acceptance._carrier_role_matches())
        with mock.patch.dict(
            os.environ,
            {acceptance.CARRIER_ENV: acceptance.CARRIER_ROLE},
            clear=True,
        ), mock.patch.object(
            acceptance.Path,
            "read_text",
            return_value="api\n",
        ):
            self.assertFalse(acceptance._carrier_role_matches())

    def test_hold_and_terminal_observations_are_exact(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        base = {
            "status": "running",
            "provider_phase": "not_started",
            "claim_count": 1,
            "provider_attempt_count": 0,
            "billing_state": "charged",
            "outbox_state": "delivered",
            "claimed_event_count": 1,
            "takeover_event_count": 0,
            "progress_event_count": 1,
            "idempotency_status": "running",
            "refund_applied": 0,
            "failure_code": "",
            "charge_source": "subscription",
            "monthly_credits_used": 6.0,
            "wallet_credits_used": 0.0,
            "usage_source": "subscription",
            "usage_credits_used": 6.0,
            "subscription_used_monthly_credits": 6.0,
            "provider_calls": 0,
        }
        with mock.patch.object(acceptance, "_snapshot", return_value=base):
            self.assertEqual(acceptance.observe(nonce, "hold")["acceptance"], "hold")
        terminal = {
            **base,
            "status": "failed",
            "claim_count": 2,
            "billing_state": "refunded",
            "claimed_event_count": 1,
            "takeover_event_count": 1,
            "progress_event_count": 2,
            "idempotency_status": "failed",
            "refund_applied": 1,
            "failure_code": "worker_failed",
            "usage_source": "refunded",
            "usage_credits_used": 0.0,
            "subscription_used_monthly_credits": 0.0,
        }
        with mock.patch.object(acceptance, "_snapshot", return_value=terminal):
            self.assertEqual(
                acceptance.observe(nonce, "terminal")["acceptance"],
                "terminal",
            )

    def test_resolve_admission_proves_full_commit_read_only(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        user_id = "00000000-0000-4000-8000-000000000101"
        operation_id = acceptance.durable_ai.operation_id_for(
            user_id,
            "analyze",
            acceptance._request_id(nonce),
        )
        request_ref_id = acceptance.durable_ai.payload_reference_id_for(
            operation_id,
            "request",
        )
        with (
            mock.patch.object(acceptance, "_require_context"),
            mock.patch.object(
                acceptance.db,
                "fetchone",
                side_effect=(
                    {"id": user_id},
                    {
                        "status": "queued",
                        "provider_phase": "not_started",
                        "claim_count": 0,
                        "provider_attempt_count": 0,
                        "idempotency_request_id": acceptance._admission_request_id(
                            operation_id
                        ),
                        "idempotency_status": "running",
                        "charge_applied": 1,
                        "usage_created": 1,
                        "billing_state": "charged",
                        "request_ref_id": request_ref_id,
                        "payload_state": "ready",
                        "purpose": "request",
                        "outbox_state": "pending",
                    },
                ),
            ),
        ):
            result = acceptance.resolve_admission(nonce)
        self.assertEqual(result["status"], "admission_resolved")
        self.assertEqual(result["operation_id"], operation_id)
        self.assertTrue(result["read_only"])

    def test_resolve_admission_classifies_user_only_partial_state(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        user_id = "00000000-0000-4000-8000-000000000101"
        with (
            mock.patch.object(acceptance, "_require_context"),
            mock.patch.object(
                acceptance.db,
                "fetchone",
                side_effect=(
                    {"id": user_id},
                    None,
                    {
                        "operation_count": 0,
                        "admission_count": 0,
                        "idempotency_count": 0,
                        "settlement_count": 0,
                        "outbox_count": 0,
                        "payload_ref_count": 0,
                    },
                ),
            ),
        ):
            result = acceptance.resolve_admission(nonce)
        self.assertEqual(result["status"], "admission_absent")
        self.assertTrue(result["user_present"])
        self.assertTrue(result["recoverable"])

    def test_admit_reuses_only_a_classified_user_only_partial_state(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        user_id = "00000000-0000-4000-8000-000000000101"
        operation_id = acceptance.durable_ai.operation_id_for(
            user_id,
            "analyze",
            acceptance._request_id(nonce),
        )
        with (
            mock.patch.object(acceptance, "_require_context", return_value=object()),
            mock.patch.object(acceptance.db, "fetchone", return_value={"id": user_id}),
            mock.patch.object(
                acceptance,
                "resolve_admission",
                return_value={
                    "status": "admission_absent",
                    "user_present": True,
                },
            ),
            mock.patch.object(
                acceptance,
                "_admission_database_absent",
                return_value=True,
            ),
            mock.patch.object(
                acceptance,
                "_ensure_admission_anchor",
                return_value={
                    "anchor_created": False,
                    "private_object_anchor_writes": 0,
                    "private_object_anchor_reads": 1,
                },
            ),
            mock.patch.object(
                acceptance.durable_ai,
                "admit_job",
                return_value={
                    "state": "admitted",
                    "operation_id": operation_id,
                },
            ) as admit_job,
            mock.patch.object(acceptance.auth, "create_user") as create_user,
        ):
            result = acceptance.admit(nonce)
        self.assertEqual(result["status"], "admitted")
        self.assertEqual(result["operation_id"], operation_id)
        admit_job.assert_called_once()
        create_user.assert_not_called()

    def test_admit_unknown_preserves_new_user_as_deterministic_recovery_anchor(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        user_id = "00000000-0000-4000-8000-000000000101"
        store = acceptance.durable_ai.InMemoryPayloadStore()
        with (
            mock.patch.object(acceptance, "_require_context", return_value=store),
            mock.patch.object(acceptance.db, "fetchone", return_value=None),
            mock.patch.object(
                acceptance.auth,
                "create_user",
                return_value={"id": user_id},
            ),
            mock.patch.object(
                acceptance.durable_ai,
                "admit_job",
                side_effect=OSError("synthetic object outcome unknown"),
            ),
            mock.patch.object(acceptance.db, "transaction") as transaction,
            self.assertRaises(OSError),
        ):
            acceptance.admit(nonce)
        transaction.assert_not_called()
        operation_id = acceptance.durable_ai.operation_id_for(
            user_id,
            "analyze",
            acceptance._request_id(nonce),
        )
        retained = acceptance._ensure_admission_anchor(
            store,
            user_id=user_id,
            operation_id=operation_id,
        )
        self.assertFalse(retained["anchor_created"])

    def test_delete_reuses_deterministic_pending_request(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        operation_id = "00000000-0000-4000-8000-000000000117"
        user_id = "00000000-0000-4000-8000-000000000101"
        deletion_id = acceptance._deletion_request_id(operation_id)
        with (
            mock.patch.object(acceptance, "_require_context", return_value=object()),
            mock.patch.object(
                acceptance,
                "observe",
                return_value={"operation_id": operation_id, "user_id": user_id},
            ),
            mock.patch.object(
                acceptance.db,
                "fetchone",
                return_value={
                    "id": deletion_id,
                    "user_id": user_id,
                    "status": "requested",
                },
            ),
            mock.patch.object(
                acceptance.content_retention,
                "request_account_deletion_with_storage",
            ) as request_deletion,
            mock.patch.object(
                acceptance.content_retention,
                "process_due_account_deletions",
                return_value=[deletion_id],
            ),
            mock.patch.object(
                acceptance,
                "resolve_primary_deletion",
                return_value={
                    "status": "primary_deleted",
                    "nonce": nonce,
                    "operation_id": operation_id,
                    "provider_calls": 0,
                },
            ),
        ):
            result = acceptance.delete_primary(nonce, operation_id)
        self.assertEqual(result["status"], "primary_deleted")
        request_deletion.assert_not_called()

    def test_resolve_primary_deletion_uses_retained_rows_only(self):
        nonce = "57c14a47-f10d-4bac-8456-34cf10e6e88d"
        operation_id = "00000000-0000-4000-8000-000000000117"
        deletion_id = acceptance._deletion_request_id(operation_id)
        request_ref_id = acceptance.durable_ai.payload_reference_id_for(
            operation_id,
            "request",
        )
        subject_ref = "deleted:" + "b" * 32
        with (
            mock.patch.object(acceptance, "_require_context"),
            mock.patch.object(
                acceptance.db,
                "fetchone",
                side_effect=(
                    {
                        "status": "failed",
                        "provider_phase": "not_started",
                        "claim_count": 2,
                        "provider_attempt_count": 0,
                        "subject_hash": "a" * 64,
                        "billing_state": "refunded",
                        "failure_code": "worker_failed",
                        "request_ref_id": request_ref_id,
                        "request_ref_state": "deleted",
                        "deleted_at": "2026-08-08T00:00:00+00:00",
                        "outbox_state": "delivered",
                    },
                    {
                        "id": deletion_id,
                        "user_id": None,
                        "subject_ref": subject_ref,
                        "status": "backup_clear_pending",
                        "primary_deleted_at": "2026-08-08T00:00:00+00:00",
                    },
                    {
                        "user_count": 0,
                        "admission_count": 0,
                        "idempotency_count": 0,
                        "ready_payload_count": 0,
                        "deleted_request_payload_count": 1,
                    },
                    {
                        "claimed_count": 1,
                        "takeover_count": 1,
                        "progress_count": 2,
                    },
                    {
                        "usage_count": 1,
                        "usage_source": "refunded",
                        "min_credits_used": 0,
                        "max_credits_used": 0,
                    },
                ),
            ),
        ):
            result = acceptance.resolve_primary_deletion(nonce, operation_id)
        self.assertEqual(result["deletion_request_id"], deletion_id)
        self.assertEqual(result["status"], "primary_deleted")
        self.assertTrue(result["read_only"])

    def test_cleanup_evidence_is_derived_from_exact_rows(self):
        terminal = {
            "operation_id": "57c14a47-f10d-4bac-8456-34cf10e6e88d",
            "user_id": "synthetic-user-id",
            "idempotency_request_id": "synthetic-request-id",
            "request_ref_id": "00000000-0000-4000-8000-000000000017",
            "usage_id": "synthetic-usage-id",
            "subject_hash": "a" * 64,
        }
        deletion = {
            "id": "00000000-0000-4000-8000-000000000018",
            "subject_ref": "deleted:" + "b" * 32,
        }
        with mock.patch.object(
            acceptance.db,
            "fetchone",
            side_effect=(
                {
                    "user_count": 0,
                    "admission_count": 0,
                    "idempotency_count": 0,
                    "ready_payload_count": 0,
                    "deleted_request_payload_count": 1,
                },
                {
                    "user_id": None,
                    "subject_ref": deletion["subject_ref"],
                    "status": "backup_clear_pending",
                    "primary_deleted_at": "2026-08-05T00:00:00+00:00",
                },
                {
                    "user_id": deletion["subject_ref"],
                    "source": "refunded",
                    "credits_used": 0,
                },
                {"subject_hash": "a" * 64, "status": "failed"},
            ),
        ):
            evidence = acceptance._cleanup_evidence(terminal, deletion)

        self.assertEqual(evidence["external_payload_residue_count"], 0)
        self.assertEqual(evidence["deleted_request_payload_count"], 1)
        self.assertTrue(evidence["usage_subject_ref_match"])
        self.assertTrue(evidence["pseudonymous_audit_retained"])

    def test_cleanup_evidence_rejects_hardcoded_success(self):
        terminal = {
            "operation_id": "57c14a47-f10d-4bac-8456-34cf10e6e88d",
            "user_id": "synthetic-user-id",
            "idempotency_request_id": "synthetic-request-id",
            "request_ref_id": "00000000-0000-4000-8000-000000000017",
            "usage_id": "synthetic-usage-id",
            "subject_hash": "a" * 64,
        }
        deletion = {
            "id": "00000000-0000-4000-8000-000000000018",
            "subject_ref": "deleted:" + "b" * 32,
        }
        with (
            mock.patch.object(
                acceptance.db,
                "fetchone",
                side_effect=(
                    {
                        "user_count": 0,
                        "admission_count": 0,
                        "idempotency_count": 0,
                        "ready_payload_count": 1,
                        "deleted_request_payload_count": 0,
                    },
                    {
                        "user_id": None,
                        "subject_ref": deletion["subject_ref"],
                        "status": "backup_clear_pending",
                        "primary_deleted_at": "2026-08-05T00:00:00+00:00",
                    },
                    {
                        "user_id": deletion["subject_ref"],
                        "source": "refunded",
                        "credits_used": 0,
                    },
                    {"subject_hash": "a" * 64, "status": "failed"},
                ),
            ),
            self.assertRaisesRegex(acceptance.AcceptanceError, "cleanup_contract"),
        ):
            acceptance._cleanup_evidence(terminal, deletion)

    def test_failure_output_is_fixed_and_secret_free(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                acceptance,
                "admit",
                side_effect=acceptance.AcceptanceError("synthetic_failure"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = acceptance.main([
                "--admit",
                "--nonce",
                "57c14a47-f10d-4bac-8456-34cf10e6e88d",
            ])
        self.assertEqual(result, 1)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_durable_ai_acceptance=FAIL code=synthetic_failure",
        )


if __name__ == "__main__":
    unittest.main()
