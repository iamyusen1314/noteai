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
                    acceptance.CONFIRM_ENV: "",
                },
                clear=True,
            ),
            mock.patch.object(acceptance.db, "using_postgres", return_value=True),
            mock.patch.object(
                acceptance.durable_ai,
                "database_role_matches",
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
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTEAI_DEPLOYMENT_STAGE": "production",
                    "NOTEAI_RUNTIME_ROLE": "api",
                    "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
                    "ANTHROPIC_API_KEY": "synthetic-never-print",
                },
                clear=True,
            ),
            mock.patch.object(acceptance.db, "using_postgres", return_value=True),
            mock.patch.object(
                acceptance.durable_ai,
                "database_role_matches",
                return_value=True,
            ),
            self.assertRaisesRegex(
                acceptance.AcceptanceError,
                "provider_secret_present",
            ),
        ):
            acceptance._require_context(mutate=False)

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
