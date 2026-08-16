import copy
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_item26_external_authority_v1 as authority  # noqa: E402


EXECUTION = "a" * 40
EVIDENCE_REVISION = "d" * 40
TERMINAL = "b" * 40
RECEIPT = "1" * 64
EVIDENCE = "2" * 64
CHECKPOINT = "3" * 64
ACCEPTANCE = "4" * 64


def closure():
    key = {
        "issuer": "independent",
        "audience": authority.TASK_ID,
        "public_key_pem_base64": "ignored",
        "public_key_sha256": "5" * 64,
        "public_key_spki_sha256": "6" * 64,
    }
    root = {
        "schema": authority.ROOT_SCHEMA,
        "task_id": authority.TASK_ID,
        "status": "FROZEN_BEFORE_EXECUTION",
        "repository": authority.REPOSITORY,
        "source_ref": authority.SOURCE_REF,
        "frozen_before_revision": "c" * 40,
        "provider": copy.deepcopy(key),
        "confirmation": copy.deepcopy(key),
        "ci": copy.deepcopy(key),
    }
    source_manifest = {"manifest_sha256": "a" * 64}
    restored_manifest = {"manifest_sha256": "b" * 64}
    confirmation = {
        "schema": authority.CONFIRMATION_SCHEMA,
        "task_id": authority.TASK_ID,
        "execution_revision": EXECUTION,
        "abort_terminal_acceptance_sha256": "d" * 64,
        "successor_clone_identity_set_sha256": "e" * 64,
        "fee_authorization_sha256": "f" * 64,
        "fee_confirmation_sha256": "1" * 64,
        "fee_authorization_nonce_sha256": "2" * 64,
        "fee_authorization_cap_cny": "10.000000",
        "fee_authorization_approved_at_utc": "2026-08-16T00:00:01Z",
        "fee_authorization_expires_at_utc": "2026-08-16T00:05:00Z",
    }
    provider = {
        "schema": authority.PROVIDER_SCHEMA,
        "task_id": authority.TASK_ID,
        "execution_revision": EXECUTION,
        "observed_at_utc": "2026-08-16T00:00:00Z",
        "receipt_file_sha256": RECEIPT,
        "terminal_acceptance_sha256": ACCEPTANCE,
        "raw_closure_sha256": "7" * 64,
        "abort_dependency_authority_root": "c" * 64,
        "abort_terminal_acceptance_sha256": "d" * 64,
        "successor_clone_identity_set_sha256": "e" * 64,
        "successor_fee_authorization_sha256": "f" * 64,
        "successor_confirmation_export_semantic_sha256": authority._semantic(
            confirmation
        ),
        "source_manifest_file_sha256": authority._sha(
            authority._canonical(source_manifest)
        ),
        "source_manifest_sha256": source_manifest["manifest_sha256"],
        "restored_manifest_file_sha256": authority._sha(
            authority._canonical(restored_manifest)
        ),
        "restored_manifest_sha256": restored_manifest["manifest_sha256"],
    }
    def run(event, head_sha, index):
        return {
            "event": event,
            "head_sha": head_sha,
            "attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "job_count": 1,
            "failed_step_count": 0,
            "run_id_sha256": f"{index:064x}",
            "job_id_sha256": f"{index + 100:064x}",
            "step_count": 22,
            "unit_test_count": 2243,
            "postgres_test_count": 6,
            "readiness_check_count": 138,
            "error_annotation_count": 0,
        }
    ci = {
        "schema": authority.CI_SCHEMA,
        "task_id": authority.TASK_ID,
        "execution_revision": EXECUTION,
        "evidence_revision": EVIDENCE_REVISION,
        "terminal_revision": TERMINAL,
        "repository": authority.REPOSITORY,
        "ref": authority.SOURCE_REF,
        "evidence_file_sha256": EVIDENCE,
        "receipt_file_sha256": RECEIPT,
        "checkpoint_file_sha256": CHECKPOINT,
        "no_replay_registry_file_sha256": "8" * 64,
        "control_sources": [
            {
                "path": ref,
                "sha256": "9" * 64,
                "unchanged_across_stages": True,
            }
            for ref in authority.REQUIRED_CONTROL_SOURCE_REFS
        ],
        "execution_push": run("push", EXECUTION, 1),
        "execution_pull_request": run("pull_request", EXECUTION, 2),
        "evidence_push": run("push", EVIDENCE_REVISION, 3),
        "evidence_pull_request": run(
            "pull_request", EVIDENCE_REVISION, 4
        ),
        "terminal_push": run("push", TERMINAL, 5),
        "terminal_pull_request": run("pull_request", TERMINAL, 6),
    }
    bundle = {
        "schema": authority.BUNDLE_SCHEMA,
        "task_id": authority.TASK_ID,
        "execution_revision": EXECUTION,
        "evidence_revision": EVIDENCE_REVISION,
        "terminal_revision": TERMINAL,
        "provider": {"payload": provider},
        "confirmation": {"payload": confirmation},
        "ci": {"payload": ci},
    }
    return (
        root,
        bundle,
        source_manifest,
        restored_manifest,
        provider,
        confirmation,
        ci,
    )


class Item26ExternalAuthorityTests(unittest.TestCase):
    def call(self, root):
        return authority.validate_authority_bundle(
            expected_authority_root_file_sha256=authority._sha(
                authority._canonical(root)
            ),
        )

    def test_unfinalized_inputs_fail_before_authority_read(self):
        with mock.patch.object(authority, "_read_root_owned") as read:
            errors, projection = authority.validate_authority_bundle(
                expected_authority_root_file_sha256="",
            )
        self.assertEqual(errors, ["Item26 external authority inputs are not finalized"])
        self.assertIsNone(projection)
        read.assert_not_called()

    def test_distinct_signed_authorities_accept_exact_three_party_closure(self):
        root, bundle, source, restored, provider, confirmation, ci = closure()
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(root),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ), mock.patch.object(
            authority,
            "_decode_key",
            side_effect=[
                (b"provider", "8" * 64),
                (b"confirmation", "a" * 64),
                (b"ci", "9" * 64),
            ],
        ), mock.patch.object(
            authority,
            "_envelope",
            side_effect=[provider, confirmation, ci],
        ), mock.patch.object(
            authority,
            "_frozen_before",
            return_value=True,
        ), mock.patch.object(
            authority,
            "_git_blob_sha256",
            return_value="9" * 64,
        ), mock.patch.object(
            authority,
            "_current_file_sha256",
            side_effect=lambda ref, **_kwargs: (
                "0" * 64
                if ref == "tools/internal_deployment_readiness_gate.py"
                else "9" * 64
            ),
        ):
            errors, projection = self.call(root)
        self.assertEqual(errors, [])
        self.assertTrue(projection["authority_keys_distinct"])
        self.assertEqual(projection["confirmation_key_spki_sha256"], "a" * 64)
        self.assertEqual(
            projection["confirmation_export_semantic_sha256"],
            authority._semantic(confirmation),
        )
        self.assertEqual(projection["raw_closure_sha256"], "7" * 64)

    def test_same_mathematical_key_is_rejected(self):
        root, bundle, source, restored, _provider, _confirmation, _ci = closure()
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(root),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ), mock.patch.object(
            authority,
            "_decode_key",
            side_effect=[
                (b"one", "8" * 64),
                (b"two", "8" * 64),
                (b"three", "9" * 64),
            ],
        ), mock.patch.object(authority, "_frozen_before", return_value=True):
            errors, projection = self.call(root)
        self.assertTrue(errors)
        self.assertIn("authority_keys_not_distinct", errors[0])
        self.assertIsNone(projection)

    def test_confirmation_payload_tamper_breaks_provider_cross_binding(self):
        root, bundle, source, restored, provider, confirmation, ci = closure()
        confirmation["fee_authorization_cap_cny"] = "11.000000"
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(root),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ), mock.patch.object(
            authority,
            "_decode_key",
            side_effect=[
                (b"provider", "8" * 64),
                (b"confirmation", "a" * 64),
                (b"ci", "9" * 64),
            ],
        ), mock.patch.object(
            authority,
            "_envelope",
            side_effect=[provider, confirmation, ci],
        ), mock.patch.object(
            authority, "_frozen_before", return_value=True
        ):
            errors, projection = self.call(root)
        self.assertTrue(errors)
        self.assertIn("authority_payload_identity", errors[0])
        self.assertIsNone(projection)

    def test_ci_attempt_or_terminal_sha_drift_is_rejected(self):
        root, bundle, source, restored, provider, confirmation, ci = closure()
        ci["terminal_push"]["attempt"] = 2
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(root),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ), mock.patch.object(
            authority,
            "_decode_key",
            side_effect=[
                (b"provider", "8" * 64),
                (b"confirmation", "a" * 64),
                (b"ci", "9" * 64),
            ],
        ), mock.patch.object(
            authority,
            "_envelope",
            side_effect=[provider, confirmation, ci],
        ), mock.patch.object(
            authority, "_frozen_before", return_value=True
        ), mock.patch.object(
            authority, "_git_blob_sha256", return_value="9" * 64
        ), mock.patch.object(
            authority, "_current_file_sha256", return_value="9" * 64
        ):
            errors, projection = self.call(root)
        self.assertTrue(errors)
        self.assertIn("ci_run_identity", errors[0])
        self.assertIsNone(projection)

    def test_duplicate_or_noncanonical_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "root_json"):
            authority._parse(b'{"a":1,"a":2}\n', "root")
        with self.assertRaisesRegex(ValueError, "root_canonical"):
            authority._parse(b'{"a": 1}\n', "root")

    def test_post_execution_root_replacement_is_rejected_by_prefrozen_hash(self):
        root, bundle, source, restored, _provider, _confirmation, _ci = closure()
        replacement = copy.deepcopy(root)
        replacement["provider"]["issuer"] = "replacement"
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(replacement),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ):
            errors, projection = self.call(root)
        self.assertTrue(errors)
        self.assertIn("authority_identity", errors[0])
        self.assertIsNone(projection)

    def test_shared_readiness_gate_drift_in_any_stage_is_rejected(self):
        root, bundle, source, restored, provider, confirmation, ci = closure()
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(root),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ), mock.patch.object(
            authority,
            "_decode_key",
            side_effect=[
                (b"provider", "8" * 64),
                (b"confirmation", "a" * 64),
                (b"ci", "9" * 64),
            ],
        ), mock.patch.object(
            authority,
            "_envelope",
            side_effect=[provider, confirmation, ci],
        ), mock.patch.object(
            authority, "_frozen_before", return_value=True
        ), mock.patch.object(
            authority,
            "_git_blob_sha256",
            side_effect=lambda _revision, ref, **_kwargs: (
                "0" * 64
                if ref == "tools/internal_deployment_readiness_gate.py"
                else "9" * 64
            ),
        ):
            errors, projection = self.call(root)
        self.assertTrue(errors)
        self.assertIn("control_source_identity", errors[0])
        self.assertIsNone(projection)

    def test_current_item26_control_source_drift_is_rejected(self):
        root, bundle, source, restored, provider, confirmation, ci = closure()
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(root),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ), mock.patch.object(
            authority,
            "_decode_key",
            side_effect=[
                (b"provider", "8" * 64),
                (b"confirmation", "a" * 64),
                (b"ci", "9" * 64),
            ],
        ), mock.patch.object(
            authority,
            "_envelope",
            side_effect=[provider, confirmation, ci],
        ), mock.patch.object(
            authority, "_frozen_before", return_value=True
        ), mock.patch.object(
            authority, "_git_blob_sha256", return_value="9" * 64
        ), mock.patch.object(
            authority,
            "_current_file_sha256",
            side_effect=lambda ref, **_kwargs: (
                "0" * 64
                if ref == "tools/verify_pitr_restore_evidence.py"
                else "9" * 64
            ),
        ):
            errors, projection = self.call(root)
        self.assertTrue(errors)
        self.assertIn("control_source_identity", errors[0])
        self.assertIsNone(projection)

    def test_side_branch_evidence_revision_is_rejected(self):
        root, bundle, source, restored, _provider, _confirmation, _ci = closure()
        with mock.patch.object(
            authority,
            "_read_root_owned",
            side_effect=[
                authority._canonical(root),
                authority._canonical(bundle),
                authority._canonical(source),
                authority._canonical(restored),
            ],
        ), mock.patch.object(
            authority,
            "_frozen_before",
            side_effect=[True, False],
        ):
            errors, projection = self.call(root)
        self.assertTrue(errors)
        self.assertIn("authority_identity", errors[0])
        self.assertIsNone(projection)


if __name__ == "__main__":
    unittest.main()
