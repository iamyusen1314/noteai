import base64
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_item26_manual_cost_stop_activation_receipt_v3 as builder  # noqa: E402
import build_item26_manual_cost_stop_authority_root_v2 as root_builder  # noqa: E402
import verify_item26_manual_cost_stop_authority_v2 as authority  # noqa: E402
from tests.test_verify_item26_manual_cost_stop_authority_v2 import (  # noqa: E402
    SyntheticRsa3072Keys,
)


CONTROL_REVISION = "f" * 40


def ci_row(run_id, event, completed_at):
    return {
        "run_id": run_id,
        "job_id": run_id + 1000,
        "event": event,
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": CONTROL_REVISION,
        "created_at_utc": "2026-08-17T05:00:00Z",
        "started_at_utc": "2026-08-17T05:00:01Z",
        "completed_at_utc": completed_at,
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": authority.CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "failed_step_count": 0,
        "step_count": 22,
        "unit_test_count": 2500,
        "unit_test_failure_count": 0,
        "unit_test_error_count": 0,
        "unit_test_skip_count": 34,
        "frozen_topology_test_counts": [10, 1, 12, 22, 21],
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "quality_gate_pass_count": 7,
        "quality_expected_fail_count": 1,
        "error_annotation_count": 0,
        "compose_config_success": True,
    }


class ManualCostStopActivationReceiptV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = SyntheticRsa3072Keys()
        cls.root_raw = root_builder.build_authority_root(cls.keys.public)
        cls.root_hash = authority._sha(cls.root_raw)
        cls.control_ci = {
            "push": ci_row(401, "push", "2026-08-17T05:20:00Z"),
            "pull_request": ci_row(
                402,
                "pull_request",
                    "2026-08-17T05:21:00Z",
            ),
        }
        cls.sources = {}
        for index, ref in enumerate(authority.CONTROL_SOURCE_REFS, 1):
            cls.sources[ref] = {
                "git_blob_oid": f"{index:x}" * 40,
                "file_sha256": f"{index:x}" * 64,
            }
        cls.sources[authority.PUBLIC_ROOT_REF] = {
            "git_blob_oid": "a" * 40,
            "file_sha256": cls.root_hash,
        }
        cls.sources[authority.CONTRACT_REF] = {
            "git_blob_oid": "b" * 40,
            "file_sha256": authority.EXPECTED_CONTRACT_FILE_SHA256,
        }

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    @contextmanager
    def finalized_authority(self):
        with mock.patch.object(
            authority, "AUTHORITY_V2_FINALIZED", True
        ), mock.patch.object(
            authority, "EXPECTED_ROOT_SHA", self.root_hash
        ), mock.patch.object(
            authority,
            "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
            self.root_hash,
        ), mock.patch.object(
            authority,
            "revision_is_strict_ancestor",
            return_value=True,
        ), mock.patch.object(
            authority,
            "_git_blob_record",
            side_effect=self.git_record,
        ), mock.patch.object(
            authority,
            "_validate_ledger_git_bindings",
            return_value=None,
        ), self.keys.builder_patches(), self.keys.verification_patcher():
            yield

    def build(
        self,
        *,
        control_ci=None,
        control_source_blobs=None,
        activated_at_utc="2026-08-17T05:22:00Z",
    ):
        with tempfile.TemporaryDirectory(
            prefix=".item26-v3-receipt-scratch-",
            dir=ROOT,
        ) as temporary:
            scratch = Path(temporary)
            scratch.chmod(0o700)
            with self.finalized_authority():
                raw = builder.build_activation_receipt(
                    root_raw=self.root_raw,
                    local_ci_observation_private_key_pem=(
                        self.keys.signing_handles["local_ci_observation"]
                    ),
                    control_revision=CONTROL_REVISION,
                    control_ci=copy.deepcopy(
                        self.control_ci if control_ci is None else control_ci
                    ),
                    control_source_blobs=copy.deepcopy(
                        self.sources
                        if control_source_blobs is None
                        else control_source_blobs
                    ),
                    activated_at_utc=activated_at_utc,
                    scratch_directory=scratch,
                )
            self.assertEqual(list(scratch.iterdir()), [])
            return raw

    def git_record(self, _revision, ref, *, root):
        del root
        row = self.sources[ref]
        raw = self.root_raw if ref == authority.PUBLIC_ROOT_REF else b"bound"
        return {
            "raw": raw,
            "git_blob_oid": row["git_blob_oid"],
            "git_blob_sha256": row["file_sha256"],
            "file_sha256": row["file_sha256"],
        }

    def validate(self, raw):
        root_value, keys = authority._validate_root(
            self.root_raw,
            expected_hash=self.root_hash,
        )
        installed = {
            ref: self.sources[ref]["file_sha256"]
            for ref in authority.RUNTIME_SOURCE_REFS
        }
        with mock.patch.object(authority, "AUTHORITY_V2_FINALIZED", True), \
                mock.patch.object(
                    authority,
                    "EXPECTED_ROOT_SHA",
                    self.root_hash,
                ), mock.patch.object(
                    authority,
                    "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                    self.root_hash,
                ), mock.patch.object(
                    authority,
                    "revision_is_strict_ancestor",
                    return_value=True,
                ), mock.patch.object(
                    authority,
                    "_git_blob_record",
                    side_effect=self.git_record,
                ), self.keys.verification_patcher():
            return authority.validate_runtime_activation_receipt(
                raw,
                root_value=root_value,
                keys=keys,
                control_revision=CONTROL_REVISION,
                expected_authority_root_file_sha256=self.root_hash,
                expected_source_hashes=installed,
            )

    def test_receipt_binds_root_epoch_a3_ci_history_sources_and_zero_state(self):
        raw = self.build()
        value = json.loads(raw.decode("ascii"))
        payload = value["payload"]
        self.assertEqual(authority.canonical_bytes(value), raw)
        self.assertEqual(
            value["root_git_binding"]["file_sha256"], self.root_hash
        )
        self.assertEqual(value["authority_epoch_id"], authority.AUTHORITY_EPOCH_ID)
        self.assertEqual(
            payload["historical_checkpoints"]["a2_terminal"],
            authority.EXPECTED_A2_TERMINAL,
        )
        self.assertEqual(
            payload["historical_checkpoints"]["ledger_stop_terminal"],
            authority.EXPECTED_LEDGER_STOP_TERMINAL,
        )
        self.assertEqual(
            payload["historical_source_blobs"],
            authority.HISTORICAL_SOURCE_BLOBS,
        )
        self.assertEqual(payload["control_ci"], self.control_ci)
        self.assertEqual(payload["control_source_blobs"], self.sources)
        self.assertFalse(payload["readback_started"])
        for key in (
            "cloud_read_count",
            "cloud_write_count",
            "database_connection_count",
            "database_write_count",
            "journal_write_count",
        ):
            with self.subTest(key=key):
                self.assertEqual(payload[key], 0)
        self.assertEqual(
            payload["fallback"],
            {
                "authority_v1_used": False,
                "collector_v1_used": False,
                "receipt_v2_used": False,
            },
        )
        binding = self.validate(raw)
        self.assertEqual(binding["activation_receipt_sha256"], authority._sha(raw))
        self.assertEqual(binding["authority_root_git_blob_sha256"], self.root_hash)
        self.assertEqual(binding["authority_epoch_id"], authority.AUTHORITY_EPOCH_ID)

    def test_signature_covers_domain_complete_outer_context_and_payload(self):
        raw = self.build()
        original = json.loads(raw.decode("ascii"))
        signature = base64.b64decode(
            original["signature_base64"], validate=True
        )
        public_key = self.keys.public["local_ci_observation"]
        mutations = {
            "domain": lambda value: value.__setitem__("domain", "changed-domain"),
            "outer_audience": lambda value: value.__setitem__(
                "audience", "changed-audience"
            ),
            "root_context": lambda value: value["root_git_binding"].__setitem__(
                "git_blob_oid", "b" * 40
            ),
            "payload": lambda value: value["payload"].__setitem__(
                "cloud_read_count", 1
            ),
        }
        original_message = (
            authority.RECEIPT_SIGNATURE_DOMAIN
            + authority.canonical_bytes(authority._signature_projection(original))
        )
        self.assertTrue(
            self.keys.verify(original_message, signature, public_key)
        )
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                message = (
                    authority.RECEIPT_SIGNATURE_DOMAIN
                    + authority.canonical_bytes(
                        authority._signature_projection(changed)
                    )
                )
                self.assertNotEqual(message, original_message)
                self.assertFalse(
                    self.keys.verify(message, signature, public_key)
                )

    def test_wrong_private_key_cannot_sign_local_ci_role(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-v3-wrong-key-",
            dir=ROOT,
        ) as temporary:
            scratch = Path(temporary)
            scratch.chmod(0o700)
            with self.finalized_authority(), self.assertRaisesRegex(
                ValueError, "signing key identity"
            ):
                builder.build_activation_receipt(
                    root_raw=self.root_raw,
                    local_ci_observation_private_key_pem=(
                        self.keys.signing_handles["provider"]
                    ),
                    control_revision=CONTROL_REVISION,
                    control_ci=self.control_ci,
                    control_source_blobs=self.sources,
                    activated_at_utc="2026-08-17T05:22:00Z",
                    scratch_directory=scratch,
                )

    def test_invalid_unsigned_inputs_do_not_call_sign(self):
        cases = {}
        reused = copy.deepcopy(self.control_ci)
        reused["push"]["run_id"] = authority.EXPECTED_LEDGER_STOP_TERMINAL[
            "push"
        ]["run_id"]
        cases["reused_run_id"] = (reused, self.sources, "2026-08-17T05:22:00Z")
        early = copy.deepcopy(self.control_ci)
        early["push"]["created_at_utc"] = "2026-08-17T04:00:00Z"
        early["push"]["started_at_utc"] = "2026-08-17T04:00:01Z"
        cases["early_control"] = (early, self.sources, "2026-08-17T05:22:00Z")
        drifted_sources = copy.deepcopy(self.sources)
        drifted_sources[authority.COLLECTOR_REF]["file_sha256"] = "f" * 64
        cases["source_drift"] = (
            self.control_ci,
            drifted_sources,
            "2026-08-17T05:22:00Z",
        )
        for name, (control_ci, sources, activated) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=".item26-v3-presign-",
                dir=ROOT,
            ) as temporary:
                scratch = Path(temporary)
                scratch.chmod(0o700)
                with self.finalized_authority(), mock.patch.object(
                    builder,
                    "_sign",
                    side_effect=AssertionError("sign must not run"),
                ) as sign, self.assertRaises(ValueError):
                    builder.build_activation_receipt(
                        root_raw=self.root_raw,
                        local_ci_observation_private_key_pem=(
                            self.keys.signing_handles[
                                "local_ci_observation"
                            ]
                        ),
                        control_revision=CONTROL_REVISION,
                        control_ci=control_ci,
                        control_source_blobs=sources,
                        activated_at_utc=activated,
                        scratch_directory=scratch,
                    )
                sign.assert_not_called()

    def test_non_0700_scratch_is_rejected_before_private_key_copy(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-v3-unsafe-scratch-",
            dir=ROOT,
        ) as temporary:
            scratch = Path(temporary)
            scratch.chmod(0o755)
            with mock.patch.object(
                builder,
                "_write_exclusive",
                side_effect=AssertionError("private key must not be copied"),
            ), self.assertRaisesRegex(ValueError, "scratch identity"):
                builder._sign(
                    b"message",
                    self.keys.signing_handles["local_ci_observation"],
                    scratch_directory=scratch,
                )

    def test_command_entry_fails_before_file_io(self):
        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("file read must not start"),
        ), mock.patch.object(
            os,
            "open",
            side_effect=AssertionError("file write must not start"),
        ), self.assertRaisesRegex(ValueError, "not finalized"):
            builder.main(["--key", "/should/not/be/read"])


if __name__ == "__main__":
    unittest.main()
