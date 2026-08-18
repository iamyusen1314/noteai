import ast
import base64
import copy
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_item26_manual_cost_stop_authority_root_v2 as root_builder  # noqa: E402
import build_item26_manual_cost_stop_activation_receipt_v3 as receipt_builder  # noqa: E402
import extract_item26_manual_cost_stop_raw_v2 as extractor  # noqa: E402
import verify_item26_manual_cost_stop_authority_v2 as authority  # noqa: E402
from tests.test_extract_item26_manual_cost_stop_raw_v2 import (  # noqa: E402
    CLONE_ID,
    SOURCE_ID,
    SOURCE_NAME,
    actiontrail_capture,
    encoded,
    provider_capture,
)


V1_FREEZE = {
    "tools/verify_item26_manual_cost_stop_authority_v1.py": (
        "9d7c95981bd40d055ad6b69591efcedd8753ec930bf0f5c7230d6824a50961e2"
    ),
    "tools/collect_item26_manual_cost_stop_raw_v1.py": (
        "0d75d63e16e17b73e86fb9f42c74d3764aae08ecc58f3956d9fedd997ae4f143"
    ),
    "tools/extract_item26_manual_cost_stop_raw_v1.py": (
        "d097c052aea5758c27a3be10e2b072abb32fe51fcaf5b8ff4158c370b474d017"
    ),
    "tools/verify_item26_manual_cost_stop_evidence_v1.py": (
        "0f37dd9fd775ecf898e16ee7747c0b842f07c1bed2aa8800609077d13f7327c4"
    ),
    "tools/build_item26_manual_cost_stop_evidence_v1.py": (
        "1c785038c6fcde1d1ef46ef59540668afa6978cfca4ab5335eab207a522e4929"
    ),
}

CONTROL_REVISION = "c" * 40
EVIDENCE_REVISION = "d" * 40
TERMINAL_REVISION = "e" * 40
TEST_PUBLIC_SPKI_SHA256 = {
    "provider": "c42203e2129b43dda82acb727f1c0413d00919ba3c43e7c9f3b3cb831618d609",
    "confirmation": "3e1ed2f23a5e9109e4f74c8fab750b7aba6abc5c819e45fd0e5e96e1239b8d16",
    "local_ci_observation": (
        "113ac96a787bc0d161d845fee420e0d7f2e22bc5f0e4ec6666cfead209094500"
    ),
}


def terminal_ci_row(
    revision,
    run_id,
    event,
    created_at_utc,
    started_at_utc,
    completed_at_utc,
):
    return {
        "run_id": run_id,
        "job_id": run_id + 1_000_000,
        "event": event,
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": revision,
        "created_at_utc": created_at_utc,
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
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


def _der_length(value):
    if value < 0x80:
        return bytes([value])
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _der_value(tag, raw):
    return bytes([tag]) + _der_length(len(raw)) + raw


def _test_public_key(role):
    """Return a deterministic public-only RSA-3072 SPKI fixture.

    The modulus is test-only public structure.  No private material is
    generated, stored or required by this fixture.
    """
    material = bytearray()
    counter = 0
    while len(material) < 384:
        material.extend(
            hashlib.sha512(
                b"noteai-item26-public-only-rsa3072-v1\0"
                + role.encode("ascii")
                + counter.to_bytes(4, "big")
            ).digest()
        )
        counter += 1
    modulus = material[:384]
    modulus[0] |= 0x80
    modulus[-1] |= 1
    rsa_public = _der_value(
        0x30,
        _der_value(0x02, b"\0" + bytes(modulus))
        + _der_value(0x02, b"\x01\x00\x01"),
    )
    algorithm = bytes.fromhex("300d06092a864886f70d0101010500")
    spki = _der_value(0x30, algorithm + _der_value(0x03, b"\0" + rsa_public))
    encoded = base64.b64encode(spki).decode("ascii")
    lines = [encoded[index:index + 64] for index in range(0, len(encoded), 64)]
    return (
        "-----BEGIN PUBLIC KEY-----\n"
        + "\n".join(lines)
        + "\n-----END PUBLIC KEY-----\n"
    ).encode("ascii")


class SyntheticRsa3072Keys:
    """Public-only role fixtures with deterministic non-key signature mocks."""

    def __init__(self):
        self.public = {
            role: _test_public_key(role) for role in authority.ROLE_NAMES
        }
        observed = {
            role: hashlib.sha256(
                base64.b64decode(b"".join(value.splitlines()[1:-1]))
            ).hexdigest()
            for role, value in self.public.items()
        }
        if observed != TEST_PUBLIC_SPKI_SHA256:
            raise RuntimeError("public-only RSA fixture drift")
        self.signing_handles = {
            role: ("TEST-ONLY-NON-KEY-SIGNER:" + role).encode("ascii")
            for role in authority.ROLE_NAMES
        }

    def cleanup(self):
        self.public.clear()
        self.signing_handles.clear()

    def _role_for_handle(self, handle):
        for role, expected in self.signing_handles.items():
            if handle == expected:
                return role
        raise ValueError("synthetic non-key signing handle")

    def public_for_handle(self, handle):
        return self.public[self._role_for_handle(handle)]

    @staticmethod
    def _signature(message, public_key):
        digest = hashlib.sha256(
            b"noteai-item26-test-signature-v1\0"
            + public_key
            + b"\0"
            + message
        ).digest()
        return digest * 12

    def sign(self, message, handle, *, scratch_directory):
        del scratch_directory
        return self._signature(message, self.public_for_handle(handle))

    def verify(self, message, signature, public_key):
        return signature == self._signature(message, public_key)

    @contextmanager
    def builder_patches(self):
        with mock.patch.object(
            receipt_builder,
            "_private_public_key",
            side_effect=self.public_for_handle,
        ), mock.patch.object(
            receipt_builder,
            "_sign",
            side_effect=self.sign,
        ):
            yield

    def verification_patcher(self):
        return mock.patch.object(
            authority,
            "_verify_signature",
            side_effect=self.verify,
        )


class SyntheticTerminalAuthorityV2:
    """A three-key, fully signed terminal bundle with synthetic Git state."""

    def __init__(self, keys, root_raw):
        self.keys = keys
        self.root_raw = root_raw
        self.root_hash = authority._sha(root_raw)
        self.root_value, _ = authority._validate_root(
            root_raw, expected_hash=self.root_hash
        )
        self.runtime_material = {
            Path(authority.COLLECTOR_REF).name: b"synthetic collector v2\n",
            Path(authority.EXTRACTOR_REF).name: b"synthetic extractor v2\n",
            Path(authority.VERIFIER_REF).name: b"synthetic authority v2\n",
        }
        self.records = {}
        self.control_sources = {}
        contract_raw = (ROOT / authority.CONTRACT_REF).read_bytes()
        source_raw = {
            authority.COLLECTOR_REF: self.runtime_material[
                Path(authority.COLLECTOR_REF).name
            ],
            authority.EXTRACTOR_REF: self.runtime_material[
                Path(authority.EXTRACTOR_REF).name
            ],
            authority.VERIFIER_REF: self.runtime_material[
                Path(authority.VERIFIER_REF).name
            ],
            authority.PUBLIC_ROOT_REF: root_raw,
            authority.CONTRACT_REF: contract_raw,
            authority.BOOTSTRAP_REF: (
                ROOT / authority.BOOTSTRAP_REF
            ).read_bytes(),
        }
        for ref in authority.CONTROL_SOURCE_REFS:
            raw = source_raw.get(
                ref, ("synthetic control source: " + ref + "\n").encode()
            )
            record = self._record(raw, b"control:" + ref.encode())
            if ref == authority.BOOTSTRAP_REF:
                record["git_blob_oid"] = (
                    authority.EXPECTED_BOOTSTRAP_GIT_BLOB_OID
                )
            self.control_sources[ref] = {
                "git_blob_oid": record["git_blob_oid"],
                "file_sha256": record["file_sha256"],
            }
            for revision in (
                CONTROL_REVISION,
                EVIDENCE_REVISION,
                TERMINAL_REVISION,
            ):
                self.records[(revision, ref)] = record

        self.control_ci = {
            "push": terminal_ci_row(
                CONTROL_REVISION,
                400001,
                "push",
                "2026-08-18T01:30:00Z",
                "2026-08-18T01:30:01Z",
                "2026-08-18T02:00:00Z",
            ),
            "pull_request": terminal_ci_row(
                CONTROL_REVISION,
                400002,
                "pull_request",
                "2026-08-18T01:30:02Z",
                "2026-08-18T01:30:03Z",
                "2026-08-18T02:01:00Z",
            ),
        }
        with tempfile.TemporaryDirectory(
            prefix=".item26-v2-terminal-receipt-", dir=ROOT
        ) as temporary:
            scratch = Path(temporary)
            scratch.chmod(0o700)
            with self.core_patches(), keys.builder_patches():
                self.activation_receipt_raw = (
                    receipt_builder.build_activation_receipt(
                        root_raw=root_raw,
                        local_ci_observation_private_key_pem=(
                            keys.signing_handles["local_ci_observation"]
                        ),
                        control_revision=CONTROL_REVISION,
                        control_ci=copy.deepcopy(self.control_ci),
                        control_source_blobs=copy.deepcopy(
                            self.control_sources
                        ),
                        activated_at_utc="2026-08-18T02:02:00Z",
                        scratch_directory=scratch,
                    )
                )
        self.activation_receipt_sha = authority._sha(
            self.activation_receipt_raw
        )
        self.runtime_material[authority.ACTIVATION_RECEIPT_FILE] = (
            self.activation_receipt_raw
        )

        provider_value = provider_capture()
        trail_value = actiontrail_capture()
        self._add_request_authority(trail_value)
        for value in (provider_value, trail_value):
            value["control_revision"] = CONTROL_REVISION
            value["observed_at_utc"] = "2026-08-18T03:00:10.475Z"
            value["collector_source_sha256"] = authority._sha(
                self.runtime_material[Path(authority.COLLECTOR_REF).name]
            )
            value["extractor_source_sha256"] = authority._sha(
                self.runtime_material[Path(authority.EXTRACTOR_REF).name]
            )
            value["authority_source_sha256"] = authority._sha(
                self.runtime_material[Path(authority.VERIFIER_REF).name]
            )
            value["authority_epoch"] = authority.AUTHORITY_EPOCH_ID
            value["authority_root_file_sha256"] = self.root_hash
            value["authority_root_git_blob_sha256"] = self.root_hash
            value["activation_receipt_schema"] = (
                authority.ACTIVATION_RECEIPT_SCHEMA
            )
            value["activation_receipt_sha256"] = (
                self.activation_receipt_sha
            )
            for row in value["records"]:
                second = row["sequence"] * 2
                row["started_at_utc"] = (
                    f"2026-08-18T03:00:{second:02d}.475Z"
                )
                row["completed_at_utc"] = (
                    f"2026-08-18T03:00:{second + 1:02d}.475Z"
                )
        self.provider_raw = extractor.canonical_bytes(provider_value)
        self.actiontrail_raw = extractor.canonical_bytes(trail_value)
        billing_response = extractor.decode_canonical_json(
            provider_value["records"][2]["response_json_base64"],
            "synthetic billing",
        )
        self.extractor_values = {
            "EXPECTED_OLD_CLONE_SHA256": extractor.value_sha256(CLONE_ID),
            "EXPECTED_SOURCE_SHA256": extractor.value_sha256(SOURCE_ID),
            "EXPECTED_SOURCE_NAME_SHA256": extractor.value_sha256(
                SOURCE_NAME
            ),
            "EXPECTED_OLD_CLONE_NAME_SHA256": extractor.value_sha256(
                SOURCE_NAME.replace("source", "old-clone")
            ),
            "EXPECTED_BILLING_RESPONSE_SHA256": extractor.sha256(
                extractor.canonical_bytes(billing_response)
            ),
            "EXPECTED_PROTECTION_REQUEST_ID_SHA256": (
                extractor.value_sha256("test-protection-request-id")
            ),
            "EXPECTED_DELETE_REQUEST_ID_SHA256": extractor.value_sha256(
                "test-delete-request-id"
            ),
            "EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256": (
                extractor.value_sha256("test-protection-token")
            ),
        }
        with self.extractor_patches():
            self.projection = extractor.extract_verified_projection(
                self.provider_raw,
                self.actiontrail_raw,
                expected_control_revision=CONTROL_REVISION,
            )
        provider_projection = self.projection.provider
        trail_projection = self.projection.actiontrail
        events = {
            row["event_name"]: row for row in trail_projection["events"]
        }
        protection = events["ModifyDBInstanceDeletionProtection"]
        deletion = events["DeleteDBInstance"]
        clone_create = trail_projection["clone_create"]
        self.mutation_set = (
            extractor.consumed_mutation_identity_set_sha256(
                protection_request_id_sha256=protection[
                    "provider_request_id_sha256"
                ],
                protection_request_body_sha256=protection[
                    "request_body_sha256"
                ],
                protection_client_token_sha256=protection[
                    "client_token_sha256"
                ],
                delete_request_id_sha256=deletion[
                    "provider_request_id_sha256"
                ],
                delete_request_body_sha256=deletion[
                    "request_body_sha256"
                ],
                delete_client_token_present=deletion[
                    "client_token_present"
                ],
            )
        )
        self.source_tuple = provider_projection["source"]["tuple_sha256"]

        provider_receipt = {
            "schema": "synthetic.item26.provider-receipt.v2",
            "control_revision": CONTROL_REVISION,
            "terminal": True,
        }
        self.provider_receipt_raw = authority.canonical_bytes(
            provider_receipt
        )
        self.evidence_raw = authority.canonical_bytes({
            "schema": "synthetic.item26.evidence.v2",
            "control_revision": CONTROL_REVISION,
        })
        self.checkpoint_raw = authority.canonical_bytes({
            "schema": "synthetic.item26.checkpoint.v2",
            "evidence_revision": EVIDENCE_REVISION,
        })
        self.receipt_binding = {
            "receipt_file_sha256": authority._sha(
                self.provider_receipt_raw
            ),
            "receipt_semantic_sha256": authority._semantic(
                provider_receipt
            ),
            "terminal_acceptance_sha256": authority._sha(
                b"synthetic terminal acceptance v2"
            ),
            "raw_closure_sha256": authority._sha(
                authority.canonical_bytes({
                    "provider_raw_file_sha256": authority._sha(
                        self.provider_raw
                    ),
                    "actiontrail_raw_file_sha256": authority._sha(
                        self.actiontrail_raw
                    ),
                })
            ),
        }
        artifact_raw = {
            authority.RECEIPT_REF: self.provider_receipt_raw,
            authority.EVIDENCE_REF: self.evidence_raw,
            authority.CHECKPOINT_REF: self.checkpoint_raw,
        }
        for ref in (authority.RECEIPT_REF, authority.EVIDENCE_REF):
            record = self._record(artifact_raw[ref], b"artifact:" + ref.encode())
            self.records[(EVIDENCE_REVISION, ref)] = record
            self.records[(TERMINAL_REVISION, ref)] = record
        checkpoint_record = self._record(
            self.checkpoint_raw, b"artifact:checkpoint"
        )
        self.records[(TERMINAL_REVISION, authority.CHECKPOINT_REF)] = (
            checkpoint_record
        )

        common = {
            "task_id": authority.TASK_ID,
            "historical_operation_id": authority.OPERATION_ID,
            "authority_generation_id": authority.AUTHORITY_GENERATION_ID,
            "authority_epoch_id": authority.AUTHORITY_EPOCH_ID,
            "control_revision": CONTROL_REVISION,
            "authority_root_file_sha256": self.root_hash,
            "authority_root_git_blob_sha256": self.root_hash,
            "activation_receipt_sha256": self.activation_receipt_sha,
            "provider_raw_file_sha256": authority._sha(self.provider_raw),
            "actiontrail_raw_file_sha256": authority._sha(
                self.actiontrail_raw
            ),
            "provider_projection_sha256": authority._semantic(
                provider_projection
            ),
            "actiontrail_projection_sha256": authority._semantic(
                trail_projection
            ),
            **self.receipt_binding,
        }
        confirmation_payload = {
            "schema": authority.CONFIRMATION_SCHEMA,
            **common,
            "confirmed_at_utc": "2026-08-18T06:00:00Z",
            "post_action_observed_at_utc": provider_projection[
                "observed_at_utc"
            ],
            "historical_user_confirmation_sha256": (
                authority.EXPECTED_HISTORICAL_CONFIRMATION_SHA256
            ),
            "no_replay_registry_sha256": (
                authority.EXPECTED_NO_REPLAY_REGISTRY_SHA256
            ),
            "consumed_mutation_identity_set_sha256": self.mutation_set,
            "retroactive_action_authorization": False,
            "new_action_authorization": False,
            "readiness_credit_added": False,
        }
        self.confirmation_envelope = self.make_envelope(
            "confirmation", confirmation_payload
        )
        provider_payload = {
            "schema": authority.PROVIDER_SCHEMA,
            **common,
            "observed_at_utc": provider_projection["observed_at_utc"],
            "signed_at_utc": "2026-08-18T06:01:00Z",
            "confirmation_export_semantic_sha256": authority._semantic(
                confirmation_payload
            ),
            "historical_user_confirmation_sha256": (
                authority.EXPECTED_HISTORICAL_CONFIRMATION_SHA256
            ),
            "no_replay_registry_sha256": (
                authority.EXPECTED_NO_REPLAY_REGISTRY_SHA256
            ),
            "consumed_mutation_identity_set_sha256": self.mutation_set,
            "old_clone_sha256": self.extractor_values[
                "EXPECTED_OLD_CLONE_SHA256"
            ],
            "old_clone_name_sha256": self.extractor_values[
                "EXPECTED_OLD_CLONE_NAME_SHA256"
            ],
            "old_clone_create_request_sha256": clone_create[
                "provider_request_id_sha256"
            ],
            "old_clone_create_body_sha256": clone_create[
                "request_body_sha256"
            ],
            "old_clone_client_token_sha256": clone_create[
                "client_token_sha256"
            ],
            "protection_disable_request_id_sha256": protection[
                "provider_request_id_sha256"
            ],
            "protection_disable_request_body_sha256": protection[
                "request_body_sha256"
            ],
            "protection_disable_client_token_sha256": protection[
                "client_token_sha256"
            ],
            "delete_request_id_sha256": deletion[
                "provider_request_id_sha256"
            ],
            "delete_request_body_sha256": deletion[
                "request_body_sha256"
            ],
            "delete_client_token_present": False,
            "source_pre_tuple_sha256": self.source_tuple,
            "source_post_tuple_sha256": self.source_tuple,
            "billing_snapshot_sha256": authority._semantic(
                provider_projection["billing"]
            ),
            "old_clone_absent": True,
            "source_unchanged": True,
            "historical_billing_only": True,
            "new_action_authorized": False,
            "readiness_credit_added": False,
        }
        self.provider_envelope = self.make_envelope(
            "provider", provider_payload
        )
        self.ci_payload = {
            "schema": authority.LOCAL_CI_SCHEMA,
            "task_id": authority.TASK_ID,
            "historical_operation_id": authority.OPERATION_ID,
            "authority_generation_id": authority.AUTHORITY_GENERATION_ID,
            "authority_epoch_id": authority.AUTHORITY_EPOCH_ID,
            "status": "POST_ACTION_RECONCILIATION_TERMINAL_AUTHORITY_V2",
            "control_revision": CONTROL_REVISION,
            "evidence_revision": EVIDENCE_REVISION,
            "terminal_revision": TERMINAL_REVISION,
            "repository": authority.REPOSITORY,
            "source_ref": authority.SOURCE_REF,
            "authority_root_file_sha256": self.root_hash,
            "authority_root_git_blob_sha256": self.root_hash,
            "activation_receipt_sha256": self.activation_receipt_sha,
            "provider_export_semantic_sha256": authority._semantic(
                provider_payload
            ),
            "confirmation_export_semantic_sha256": authority._semantic(
                confirmation_payload
            ),
            "provider_raw_file_sha256": authority._sha(self.provider_raw),
            "actiontrail_raw_file_sha256": authority._sha(
                self.actiontrail_raw
            ),
            "provider_projection_sha256": authority._semantic(
                provider_projection
            ),
            "actiontrail_projection_sha256": authority._semantic(
                trail_projection
            ),
            **self.receipt_binding,
            "evidence_file_sha256": authority._sha(self.evidence_raw),
            "checkpoint_file_sha256": authority._sha(
                self.checkpoint_raw
            ),
            "control_sources": copy.deepcopy(self.control_sources),
            "control_push": copy.deepcopy(self.control_ci["push"]),
            "control_pull_request": copy.deepcopy(
                self.control_ci["pull_request"]
            ),
            "evidence_push": terminal_ci_row(
                EVIDENCE_REVISION,
                400003,
                "push",
                "2026-08-18T04:00:00Z",
                "2026-08-18T04:00:01Z",
                "2026-08-18T04:20:00Z",
            ),
            "evidence_pull_request": terminal_ci_row(
                EVIDENCE_REVISION,
                400004,
                "pull_request",
                "2026-08-18T04:00:02Z",
                "2026-08-18T04:00:03Z",
                "2026-08-18T04:21:00Z",
            ),
            "terminal_push": terminal_ci_row(
                TERMINAL_REVISION,
                400005,
                "push",
                "2026-08-18T05:00:00Z",
                "2026-08-18T05:00:01Z",
                "2026-08-18T05:20:00Z",
            ),
            "terminal_pull_request": terminal_ci_row(
                TERMINAL_REVISION,
                400006,
                "pull_request",
                "2026-08-18T05:00:02Z",
                "2026-08-18T05:00:03Z",
                "2026-08-18T05:21:00Z",
            ),
            "terminal_accepted_at_utc": "2026-08-18T06:02:00Z",
        }
        self.local_ci_envelope = self.make_envelope(
            "local_ci_observation", self.ci_payload
        )
        self.bundle = {
            "schema": authority.BUNDLE_SCHEMA,
            "task_id": authority.TASK_ID,
            "historical_operation_id": authority.OPERATION_ID,
            "authority_generation_id": authority.AUTHORITY_GENERATION_ID,
            "authority_epoch_id": authority.AUTHORITY_EPOCH_ID,
            "status": "POST_ACTION_RECONCILIATION_TERMINAL_AUTHORITY_V2",
            "control_revision": CONTROL_REVISION,
            "evidence_revision": EVIDENCE_REVISION,
            "terminal_revision": TERMINAL_REVISION,
            "provider": self.provider_envelope,
            "confirmation": self.confirmation_envelope,
            "local_ci_observation": self.local_ci_envelope,
        }
        self.authority_material = self.material_for_bundle(self.bundle)

    @staticmethod
    def _record(raw, salt):
        return {
            "raw": raw,
            "git_blob_oid": hashlib.sha1(salt + raw).hexdigest(),
            "git_blob_sha256": authority._sha(raw),
            "file_sha256": authority._sha(raw),
        }

    @staticmethod
    def _add_request_authority(value):
        protection_response = extractor.decode_canonical_json(
            value["records"][0]["response_json_base64"], "fixture"
        )
        delete_response = extractor.decode_canonical_json(
            value["records"][1]["response_json_base64"], "fixture"
        )
        protection_response["Events"][0]["requestId"] = (
            "test-protection-request-id"
        )
        protection_response["Events"][0]["requestParameters"] = {
            "ClientToken": "test-protection-token",
            "DBInstanceId": CLONE_ID,
            "DeletionProtection": False,
        }
        delete_response["Events"][0]["requestId"] = (
            "test-delete-request-id"
        )
        delete_response["Events"][0]["requestParameters"] = {
            "DBInstanceId": CLONE_ID
        }
        value["records"][0]["response_json_base64"] = encoded(
            protection_response
        )
        value["records"][1]["response_json_base64"] = encoded(
            delete_response
        )

    def git_record(self, revision, ref, *, root, records=None):
        del root
        source = self.records if records is None else records
        try:
            return copy.deepcopy(source[(revision, ref)])
        except KeyError as exc:
            raise ValueError("synthetic Git object absent") from exc

    def git_absent(self, revision, ref, *, root, records=None):
        del root
        source = self.records if records is None else records
        return (revision, ref) not in source

    @contextmanager
    def core_patches(self, *, records=None):
        source = self.records if records is None else records
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                authority, "AUTHORITY_V2_FINALIZED", True
            ))
            stack.enter_context(mock.patch.object(
                authority, "EXPECTED_ROOT_SHA", self.root_hash
            ))
            stack.enter_context(mock.patch.object(
                authority,
                "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                self.root_hash,
            ))
            stack.enter_context(mock.patch.object(
                authority,
                "revision_is_strict_ancestor",
                return_value=True,
            ))
            stack.enter_context(mock.patch.object(
                authority,
                "_validate_ledger_git_bindings",
                return_value=None,
            ))
            stack.enter_context(mock.patch.object(
                authority,
                "_git_blob_record",
                side_effect=lambda revision, ref, *, root: self.git_record(
                    revision, ref, root=root, records=source
                ),
            ))
            stack.enter_context(mock.patch.object(
                authority,
                "git_blob_absent",
                side_effect=lambda revision, ref, *, root: self.git_absent(
                    revision, ref, root=root, records=source
                ),
            ))
            stack.enter_context(self.keys.verification_patcher())
            yield

    @contextmanager
    def extractor_patches(self):
        with ExitStack() as stack:
            for name, value in self.extractor_values.items():
                stack.enter_context(mock.patch.object(extractor, name, value))
            yield

    @contextmanager
    def validation_patches(self, *, records=None):
        with self.core_patches(records=records), self.extractor_patches(), \
                mock.patch.object(authority, "ROOT_UID", os.getuid()), \
                mock.patch.object(authority, "_validate_parent_chain"), \
                mock.patch.object(
                    authority,
                    "EXPECTED_MUTATION_SET_SHA256",
                    self.mutation_set,
                ), mock.patch.object(
                    authority,
                    "EXPECTED_SOURCE_PRE_TUPLE_SHA256",
                    self.source_tuple,
                ):
            yield

    def make_envelope(self, role, payload):
        unsigned = authority.terminal_unsigned_envelope(
            role=role,
            payload=payload,
            root_value=self.root_value,
            authority_root_file_sha256=self.root_hash,
        )
        signature = self.keys.sign(
            authority.terminal_signature_message(unsigned, role=role),
            self.keys.signing_handles[role],
            scratch_directory=ROOT,
        )
        return {
            **unsigned,
            "signature_base64": base64.b64encode(signature).decode("ascii"),
        }

    def resign_role(self, bundle, role):
        bundle[role] = self.make_envelope(
            role,
            copy.deepcopy(bundle[role]["payload"]),
        )

    def material_for_bundle(self, bundle):
        return {
            authority.ROOT_FILE: self.root_raw,
            authority.PROVIDER_RAW_FILE: self.provider_raw,
            authority.ACTIONTRAIL_RAW_FILE: self.actiontrail_raw,
            authority.CONFIRMATION_FILE: authority.canonical_bytes(
                bundle["confirmation"]
            ),
            authority.BUNDLE_FILE: authority.canonical_bytes(bundle),
        }

    @contextmanager
    def installed(self, *, authority_material=None, runtime_material=None):
        authority_rows = (
            self.authority_material
            if authority_material is None
            else authority_material
        )
        runtime_rows = (
            self.runtime_material
            if runtime_material is None
            else runtime_material
        )
        with tempfile.TemporaryDirectory(
            prefix=".item26-v2-terminal-authority-", dir=ROOT
        ) as authority_temporary, tempfile.TemporaryDirectory(
            prefix=".item26-v2-terminal-runtime-", dir=ROOT
        ) as runtime_temporary:
            authority_directory = Path(authority_temporary)
            runtime_directory = Path(runtime_temporary)
            authority_directory.chmod(0o700)
            runtime_directory.chmod(0o700)
            for directory, rows in (
                (authority_directory, authority_rows),
                (runtime_directory, runtime_rows),
            ):
                for name, raw in rows.items():
                    path = directory / name
                    path.write_bytes(raw)
                    path.chmod(0o600)
            yield authority_directory, runtime_directory

    def validate(
        self,
        *,
        authority_material=None,
        runtime_material=None,
        records=None,
    ):
        with self.installed(
            authority_material=authority_material,
            runtime_material=runtime_material,
        ) as (authority_directory, runtime_directory), \
                self.validation_patches(records=records):
            return authority.validate_authority_bundle(
                expected_authority_root_file_sha256=self.root_hash,
                expected_receipt_binding=self.receipt_binding,
                authority_directory=authority_directory,
                runtime_directory=runtime_directory,
            )


class ManualCostStopAuthorityV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = SyntheticRsa3072Keys()
        cls.root_raw = root_builder.build_authority_root(cls.keys.public)
        cls.terminal = SyntheticTerminalAuthorityV2(
            cls.keys, cls.root_raw
        )

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def test_default_authority_is_finalized_with_tracked_canonical_public_root(self):
        self.assertTrue(authority.AUTHORITY_V2_FINALIZED)
        self.assertEqual(
            authority.EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
            authority.EXPECTED_ROOT_SHA,
        )
        path = ROOT / authority.PUBLIC_ROOT_REF
        self.assertTrue(path.is_file())
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), authority.EXPECTED_ROOT_SHA)
        value, keys = authority._validate_root(
            raw,
            expected_hash=authority.EXPECTED_ROOT_SHA,
        )
        self.assertEqual(authority.canonical_bytes(value), raw)
        self.assertEqual(set(keys), set(authority.ROLE_NAMES))

    def test_receipt_validation_checks_full_bootstrap_lineage_before_parsing_or_io(self):
        with mock.patch.object(
            authority,
            "_parse",
            side_effect=AssertionError("receipt parse must not start"),
        ), mock.patch.object(
            authority,
            "revision_is_strict_ancestor",
            return_value=False,
        ), mock.patch.object(
            authority,
            "_git_blob_record",
            side_effect=AssertionError("blob I/O must not start"),
        ), self.assertRaisesRegex(ValueError, "control revision"):
            authority.validate_runtime_activation_receipt(
                b"not-json",
                root_value={},
                keys={},
                control_revision="f" * 40,
                expected_authority_root_file_sha256=authority.EXPECTED_ROOT_SHA,
                expected_source_hashes={},
            )

    def test_control_lineage_includes_authorization_and_rejected_source_edges(self):
        expected = [
            (authority.A0_REVISION, authority.A1_REVISION),
            (authority.A1_REVISION, authority.A2_REVISION),
            (authority.A2_REVISION, authority.LEDGER_STOP_REVISION),
            (
                authority.LEDGER_STOP_REVISION,
                authority.BOOTSTRAP_AUTHORIZATION_ANCHOR_REVISION,
            ),
            (
                authority.BOOTSTRAP_AUTHORIZATION_ANCHOR_REVISION,
                authority.REJECTED_BOOTSTRAP_SOURCE_REVISION,
            ),
            (
                authority.REJECTED_BOOTSTRAP_SOURCE_REVISION,
                authority.HELPER_SOURCE_ACCEPTED_REVISION,
            ),
            (
                authority.HELPER_SOURCE_ACCEPTED_REVISION,
                authority.BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
            ),
            (authority.BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION, CONTROL_REVISION),
        ]
        observed = []

        def ancestor(earlier, later, *, root):
            self.assertEqual(root, ROOT)
            observed.append((earlier, later))
            return True

        with mock.patch.object(
            authority,
            "revision_is_strict_ancestor",
            side_effect=ancestor,
        ):
            self.assertTrue(
                authority._control_lineage_is_valid(
                    CONTROL_REVISION,
                    root=ROOT,
                )
            )
        self.assertEqual(observed, expected)
        with mock.patch.object(
            authority,
            "revision_is_strict_ancestor",
            side_effect=lambda earlier, later, *, root: not (
                earlier == authority.BOOTSTRAP_AUTHORIZATION_ANCHOR_REVISION
                and later == authority.REJECTED_BOOTSTRAP_SOURCE_REVISION
            ),
        ):
            self.assertFalse(
                authority._control_lineage_is_valid(
                    CONTROL_REVISION,
                    root=ROOT,
                )
            )

    def test_complete_root_binds_epoch_history_ledger_registry_and_roles(self):
        value, keys = authority._validate_root(
            self.root_raw,
            expected_hash=authority._sha(self.root_raw),
        )
        self.assertEqual(value["task_id"], authority.TASK_ID)
        self.assertEqual(value["historical_operation_id"], authority.OPERATION_ID)
        self.assertEqual(
            value["authority_generation_id"], authority.AUTHORITY_GENERATION_ID
        )
        self.assertEqual(value["authority_epoch_id"], authority.AUTHORITY_EPOCH_ID)
        self.assertEqual(
            value["ledger_stop"]["revision"], authority.LEDGER_STOP_REVISION
        )
        self.assertEqual(value["no_replay"]["entry_count"], 29)
        self.assertEqual(
            value["historical_checkpoints"]["a2_terminal"],
            authority.EXPECTED_A2_TERMINAL,
        )
        self.assertEqual(
            value["historical_checkpoints"]["helper_source_terminal"],
            authority.EXPECTED_HELPER_SOURCE_TERMINAL,
        )
        self.assertEqual(
            value["historical_checkpoints"][
                "rejected_bootstrap_source_terminal"
            ],
            authority.EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL,
        )
        self.assertEqual(
            value["historical_checkpoints"]["bootstrap_ledger_terminal"],
            authority.EXPECTED_BOOTSTRAP_LEDGER_TERMINAL,
        )
        self.assertEqual(value["bootstrap_source"]["ref"], authority.BOOTSTRAP_REF)
        self.assertFalse(value["v1_custody"]["root_bytes_locatable"])
        self.assertFalse(value["v1_custody"]["destroyed_proven"])
        self.assertFalse(value["v1_custody"]["revoked_proven"])
        self.assertFalse(value["v1_custody"]["rotated_proven"])
        self.assertFalse(value["v1_custody"]["compromised_proven"])
        self.assertFalse(value["independent_organizational_key_custody_proven"])
        self.assertEqual(set(keys), set(authority.ROLE_NAMES))
        self.assertEqual(len({row[1] for row in keys.values()}), 3)
        for role in authority.ROLE_NAMES:
            with self.subTest(role=role):
                row = value["authorities"][role]
                self.assertEqual(
                    row["public_key_pem"].encode("ascii"),
                    self.keys.public[role],
                )
                self.assertEqual(row["algorithm"], "RSA-3072")
                self.assertEqual(
                    row["signature_algorithm"],
                    "RSASSA-PKCS1-v1_5-SHA256",
                )
                self.assertEqual(
                    row["signature_domain"],
                    authority.ROLE_SIGNATURE_DOMAIN_TEXT[role],
                )
                self.assertFalse(row["organizational_independence_proven"])
        self.assertTrue(value["single_local_root_custody"])
        self.assertFalse(value["provider_native_signature"])
        self.assertFalse(value["github_native_signature"])

    def test_public_only_crypto_seam_never_invokes_private_key_tooling(self):
        handle = self.keys.signing_handles["provider"]
        message = b"public-only synthetic signature contract"
        with self.keys.builder_patches(), mock.patch.object(
            receipt_builder.subprocess,
            "run",
            side_effect=AssertionError("private-key tooling must not run"),
        ):
            public_key = receipt_builder._private_public_key(handle)
            signature = receipt_builder._sign(
                message,
                handle,
                scratch_directory=ROOT,
            )
        self.assertEqual(public_key, self.keys.public["provider"])
        self.assertEqual(len(signature), 384)
        self.assertTrue(self.keys.verify(message, signature, public_key))
        self.assertFalse(self.keys.verify(message + b"!", signature, public_key))

    def test_rsa_validation_requires_rsa_encryption_algorithm_oid(self):
        der = authority._canonical_spki_der(self.keys.public["provider"])
        rsa_oid = bytes.fromhex("2a864886f70d010101")
        self.assertEqual(der.count(rsa_oid), 1)
        non_rsa_same_size = der.replace(
            rsa_oid,
            bytes.fromhex("2a864886f70d010102"),
        )
        with mock.patch.object(
            authority,
            "_canonical_spki_der",
            return_value=non_rsa_same_size,
        ):
            self.assertFalse(authority._rsa_3072(b"synthetic-non-rsa"))

    def test_duplicate_spki_is_rejected(self):
        duplicated = dict(self.keys.public)
        duplicated["confirmation"] = duplicated["provider"]
        with self.assertRaisesRegex(ValueError, "keys not distinct"):
            root_builder.build_authority_root(duplicated)

    def test_load_root_binds_installed_bytes_to_tracked_git_blob(self):
        digest = authority._sha(self.root_raw)
        control_revision = "f" * 40
        with tempfile.TemporaryDirectory(
            prefix=".item26-v2-authority-test-",
            dir=ROOT,
        ) as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            root_path = directory / authority.ROOT_FILE
            root_path.write_bytes(self.root_raw)
            root_path.chmod(0o600)

            def blob_record(_revision, ref, *, root):
                del root
                if ref == authority.PUBLIC_ROOT_REF:
                    return {
                        "raw": self.root_raw,
                        "git_blob_oid": "a" * 40,
                        "git_blob_sha256": digest,
                        "file_sha256": digest,
                    }
                if ref == authority.CONTRACT_REF:
                    return {
                        "raw": b"contract",
                        "git_blob_oid": "b" * 40,
                        "git_blob_sha256": authority.EXPECTED_CONTRACT_FILE_SHA256,
                        "file_sha256": authority.EXPECTED_CONTRACT_FILE_SHA256,
                    }
                raise AssertionError(ref)

            with mock.patch.object(authority, "AUTHORITY_V2_FINALIZED", True), \
                    mock.patch.object(authority, "EXPECTED_ROOT_SHA", digest), \
                    mock.patch.object(
                        authority,
                        "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                        digest,
                    ), mock.patch.object(authority, "ROOT_UID", os.getuid()), \
                    mock.patch.object(authority, "_validate_parent_chain"), \
                    mock.patch.object(
                        authority,
                        "revision_is_strict_ancestor",
                        return_value=True,
                    ), mock.patch.object(
                        authority,
                        "_validate_ledger_git_bindings",
                    ), mock.patch.object(
                        authority,
                        "_git_blob_record",
                        side_effect=blob_record,
                    ):
                binding = authority.load_activation_root(
                    expected_control_revision=control_revision,
                    expected_authority_root_file_sha256=digest,
                    authority_directory=directory,
                )
            self.assertEqual(binding["authority_root_file_sha256"], digest)
            self.assertEqual(binding["authority_root_git_blob_sha256"], digest)
            self.assertEqual(binding["authority_root_git_blob_oid"], "a" * 40)
            self.assertEqual(binding["authority_epoch_id"], authority.AUTHORITY_EPOCH_ID)
            self.assertIn("root_value", binding)
            self.assertIn("authority_keys", binding)

    def test_v1_tracked_bytes_are_frozen_at_ledger_stop(self):
        for ref, expected in V1_FREEZE.items():
            with self.subTest(ref=ref):
                historical = subprocess.run(
                    [
                        str(authority.GIT),
                        "--no-replace-objects",
                        "show",
                        authority.LEDGER_STOP_REVISION + ":" + ref,
                    ],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LC_ALL": "C",
                        "LANG": "C",
                        "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_CONFIG_GLOBAL": "/dev/null",
                        "GIT_NO_REPLACE_OBJECTS": "1",
                        "GIT_OPTIONAL_LOCKS": "0",
                    },
                    timeout=15,
                    check=False,
                )
                self.assertEqual(historical.returncode, 0)
                self.assertEqual(
                    hashlib.sha256(historical.stdout).hexdigest(), expected
                )
                self.assertEqual(
                    hashlib.sha256((ROOT / ref).read_bytes()).hexdigest(),
                    expected,
                )

    def test_v2_modules_have_no_v1_import_or_fallback(self):
        refs = (
            "tools/verify_item26_manual_cost_stop_authority_v2.py",
            "tools/build_item26_manual_cost_stop_authority_root_v2.py",
            "tools/build_item26_manual_cost_stop_activation_receipt_v3.py",
        )
        for ref in refs:
            with self.subTest(ref=ref):
                source = (ROOT / ref).read_text(encoding="utf-8")
                tree = ast.parse(source)
                imported = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imported.append(node.module or "")
                self.assertFalse(any(name.endswith("_v1") for name in imported))

    def test_contract_bytes_match_baked_hash(self):
        raw = (ROOT / authority.CONTRACT_REF).read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            authority.EXPECTED_CONTRACT_FILE_SHA256,
        )
        value = json.loads(raw)
        self.assertEqual(
            value["public_root"]["expected_file_state_in_this_revision"],
            "PRESENT_COMPLETE_CANONICAL",
        )
        self.assertFalse(value["public_root"]["placeholder_permitted"])
        self.assertEqual(
            value["authority_generation"]["status"],
            "PUBLIC_ROOT_V2_FINALIZED_AWAITING_ATTEMPT_ONE_DUAL_CI",
        )
        self.assertEqual(
            value["side_effects_in_this_revision"][
                "private_key_generation_count"
            ],
            3,
        )
        self.assertEqual(
            value["side_effects_in_this_revision"][
                "public_root_generation_count"
            ],
            1,
        )
        self.assertEqual(
            value["side_effects_in_this_revision"][
                "public_key_export_count"
            ],
            3,
        )
        self.assertEqual(
            value["bootstrap_source"]["acceptance_ledger_revision"],
            authority.BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
        )
        rejected = value["bootstrap_source"]["rejected_revision_terminal"]
        self.assertFalse(rejected["accepted"])
        self.assertFalse(rejected["rerun_allowed"])
        self.assertEqual(rejected["push"]["run_id"], 32045476729)
        self.assertEqual(rejected["push"]["job_id"], 95432282589)
        self.assertEqual(rejected["push"]["conclusion"], "failure")
        self.assertEqual(rejected["pull_request"]["run_id"], 32045480527)
        self.assertEqual(rejected["pull_request"]["job_id"], 95432294279)
        self.assertEqual(rejected["pull_request"]["conclusion"], "success")
        self.assertNotIn("expected_root_sha256", value)
        self.assertNotIn("control_revision", value)

    def test_control_source_set_includes_public_root_and_bootstrap_once(self):
        self.assertEqual(len(authority.CONTROL_SOURCE_REFS), 12)
        self.assertEqual(len(set(authority.CONTROL_SOURCE_REFS)), 12)
        self.assertIn(authority.PUBLIC_ROOT_REF, authority.CONTROL_SOURCE_REFS)
        self.assertIn(authority.BOOTSTRAP_REF, authority.CONTROL_SOURCE_REFS)

    def test_control_source_loader_rejects_bootstrap_drift(self):
        def record(_revision, ref, *, root):
            del root
            raw = (ROOT / ref).read_bytes()
            if ref == authority.BOOTSTRAP_REF:
                raw += b"drift\n"
            return {
                "raw": raw,
                "git_blob_oid": hashlib.sha1(raw).hexdigest(),
                "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
                "file_sha256": hashlib.sha256(raw).hexdigest(),
            }

        with mock.patch.object(
            authority,
            "_git_blob_record",
            side_effect=record,
        ), self.assertRaisesRegex(ValueError, "bootstrap drift"):
            authority._expected_control_source_blobs(
                CONTROL_REVISION,
                root=ROOT,
            )

    def test_rejected_bootstrap_revision_is_bound_to_same_helper_bytes(self):
        real_record = authority._git_blob_record

        def record(revision, ref, *, root):
            value = real_record(revision, ref, root=root)
            if (
                revision == authority.REJECTED_BOOTSTRAP_SOURCE_REVISION
                and ref == authority.BOOTSTRAP_REF
            ):
                value = dict(value)
                value["file_sha256"] = "f" * 64
            return value

        with mock.patch.object(
            authority,
            "_git_blob_record",
            side_effect=record,
        ), self.assertRaisesRegex(ValueError, "bootstrap binding"):
            authority._validate_ledger_git_bindings(root=ROOT)

    def test_run_rows_and_zero_counts_reject_bool_and_string_numbers(self):
        row = terminal_ci_row(
            CONTROL_REVISION,
            900001,
            "push",
            "2026-08-17T10:00:00Z",
            "2026-08-17T10:00:01Z",
            "2026-08-17T10:20:00Z",
        )
        self.assertTrue(
            authority._run_row(
                row, event="push", revision=CONTROL_REVISION
            )
        )
        numeric_fields = (
            "run_id",
            "job_id",
            "attempt",
            "dispatch_count",
            "rerun_count",
            "job_count",
            "failed_step_count",
            "step_count",
            "unit_test_count",
            "unit_test_failure_count",
            "unit_test_error_count",
            "unit_test_skip_count",
            "postgres_test_count",
            "readiness_check_count",
            "quality_gate_pass_count",
            "quality_expected_fail_count",
            "error_annotation_count",
        )
        for field in numeric_fields:
            for invalid in (True, str(row[field])):
                with self.subTest(field=field, invalid=invalid):
                    changed = copy.deepcopy(row)
                    changed[field] = invalid
                    self.assertFalse(
                        authority._run_row(
                            changed,
                            event="push",
                            revision=CONTROL_REVISION,
                        )
                    )
        self.assertTrue(authority._exact_zero(0))
        self.assertFalse(authority._exact_zero(False))
        self.assertFalse(authority._exact_zero("0"))

    def test_complete_signed_terminal_bundle_is_accepted(self):
        errors, result = self.terminal.validate()
        self.assertEqual(errors, [])
        self.assertIsNotNone(result)
        self.assertEqual(
            result["authority_root_file_sha256"],
            self.terminal.root_hash,
        )
        self.assertEqual(
            result["activation_receipt_sha256"],
            self.terminal.activation_receipt_sha,
        )
        self.assertEqual(
            result["receipt_file_sha256"],
            self.terminal.receipt_binding["receipt_file_sha256"],
        )
        self.assertTrue(result["authority_keys_distinct"])
        self.assertFalse(result["authorizes_new_action"])
        self.assertFalse(result["readiness_credit_allowed"])

    def test_terminal_outer_context_signature_is_not_payload_only(self):
        bundle = copy.deepcopy(self.terminal.bundle)
        bundle["provider"]["audience"] = "synthetic wrong audience"
        original_signature = base64.b64decode(
            self.terminal.bundle["provider"]["signature_base64"],
            validate=True,
        )
        changed_message = authority.terminal_signature_message(
            authority._signature_projection(bundle["provider"]),
            role="provider",
        )
        self.assertFalse(
            self.keys.verify(
                changed_message,
                original_signature,
                self.keys.public["provider"],
            )
        )
        errors, result = self.terminal.validate(
            authority_material=self.terminal.material_for_bundle(bundle)
        )
        self.assertIsNone(result)
        self.assertTrue(any("context envelope identity" in row for row in errors))

    def test_terminal_root_raw_and_activation_receipt_dag_tamper(self):
        root_material = copy.deepcopy(self.terminal.authority_material)
        root_material[authority.ROOT_FILE] = (
            self.terminal.root_raw[:-1] + b" "
        )

        provider_value = json.loads(self.terminal.provider_raw)
        provider_value["activation_receipt_sha256"] = "9" * 64
        raw_material = copy.deepcopy(self.terminal.authority_material)
        raw_material[authority.PROVIDER_RAW_FILE] = authority.canonical_bytes(
            provider_value
        )

        receipt_value = json.loads(self.terminal.activation_receipt_raw)
        receipt_value["payload"]["cloud_read_count"] = 1
        runtime_material = copy.deepcopy(self.terminal.runtime_material)
        runtime_material[authority.ACTIVATION_RECEIPT_FILE] = (
            authority.canonical_bytes(receipt_value)
        )
        cases = {
            "installed_root": (root_material, None),
            "raw_receipt_binding": (raw_material, None),
            "receipt_signature": (None, runtime_material),
        }
        for name, (material, runtime) in cases.items():
            with self.subTest(name=name):
                errors, result = self.terminal.validate(
                    authority_material=material,
                    runtime_material=runtime,
                )
                self.assertIsNone(result)
                self.assertTrue(errors)

    def test_control_evidence_terminal_and_runtime_source_freeze(self):
        cases = {}
        for name, revision in (
            ("control", CONTROL_REVISION),
            ("evidence", EVIDENCE_REVISION),
            ("terminal", TERMINAL_REVISION),
        ):
            records = copy.deepcopy(self.terminal.records)
            records[(revision, authority.COLLECTOR_REF)] = (
                self.terminal._record(
                    (name + " source drift\n").encode(),
                    (name + ":source-drift").encode(),
                )
            )
            cases[name] = (records, None)
        runtime = copy.deepcopy(self.terminal.runtime_material)
        runtime[Path(authority.COLLECTOR_REF).name] = b"runtime drift\n"
        cases["runtime"] = (None, runtime)
        for name, (records, runtime_material) in cases.items():
            with self.subTest(name=name):
                errors, result = self.terminal.validate(
                    records=records,
                    runtime_material=runtime_material,
                )
                self.assertIsNone(result)
                self.assertTrue(errors)

    def test_terminal_artifact_appearance_and_hash_stages_are_exact(self):
        cases = {}
        control_present = copy.deepcopy(self.terminal.records)
        control_present[(CONTROL_REVISION, authority.RECEIPT_REF)] = (
            self.terminal._record(
                self.terminal.provider_receipt_raw,
                b"premature-control-receipt",
            )
        )
        cases["control_artifact_present"] = control_present

        evidence_checkpoint = copy.deepcopy(self.terminal.records)
        evidence_checkpoint[(EVIDENCE_REVISION, authority.CHECKPOINT_REF)] = (
            self.terminal._record(
                self.terminal.checkpoint_raw,
                b"premature-evidence-checkpoint",
            )
        )
        cases["evidence_checkpoint_present"] = evidence_checkpoint

        evidence_missing = copy.deepcopy(self.terminal.records)
        del evidence_missing[(EVIDENCE_REVISION, authority.RECEIPT_REF)]
        cases["evidence_receipt_missing"] = evidence_missing

        terminal_drift = copy.deepcopy(self.terminal.records)
        terminal_drift[(TERMINAL_REVISION, authority.CHECKPOINT_REF)] = (
            self.terminal._record(
                b'{"synthetic":"wrong checkpoint"}\n',
                b"terminal-checkpoint-drift",
            )
        )
        cases["terminal_checkpoint_drift"] = terminal_drift
        for name, records in cases.items():
            with self.subTest(name=name):
                errors, result = self.terminal.validate(records=records)
                self.assertIsNone(result)
                self.assertTrue(errors)

    def test_terminal_ci_global_ids_and_timeline_are_exact(self):
        cases = {}
        historical_reuse = copy.deepcopy(self.terminal.bundle)
        historical_reuse["local_ci_observation"]["payload"][
            "evidence_push"
        ]["run_id"] = authority.EXPECTED_A2_TERMINAL["push"]["run_id"]
        self.terminal.resign_role(
            historical_reuse, "local_ci_observation"
        )
        cases["historical_run_reuse"] = historical_reuse

        m1_m2_reuse = copy.deepcopy(self.terminal.bundle)
        m1_m2_reuse["local_ci_observation"]["payload"][
            "terminal_push"
        ]["job_id"] = m1_m2_reuse["local_ci_observation"]["payload"][
            "evidence_push"
        ]["job_id"]
        self.terminal.resign_role(m1_m2_reuse, "local_ci_observation")
        cases["evidence_terminal_job_reuse"] = m1_m2_reuse

        early_evidence = copy.deepcopy(self.terminal.bundle)
        evidence_push = early_evidence["local_ci_observation"]["payload"][
            "evidence_push"
        ]
        evidence_push["created_at_utc"] = "2026-08-17T05:50:00Z"
        evidence_push["started_at_utc"] = "2026-08-17T05:50:01Z"
        evidence_push["completed_at_utc"] = "2026-08-17T06:20:00Z"
        self.terminal.resign_role(early_evidence, "local_ci_observation")
        cases["evidence_before_raw"] = early_evidence

        early_acceptance = copy.deepcopy(self.terminal.bundle)
        early_acceptance["local_ci_observation"]["payload"][
            "terminal_accepted_at_utc"
        ] = "2026-08-17T09:00:30Z"
        self.terminal.resign_role(early_acceptance, "local_ci_observation")
        cases["acceptance_before_provider"] = early_acceptance

        for name, bundle in cases.items():
            with self.subTest(name=name):
                errors, result = self.terminal.validate(
                    authority_material=self.terminal.material_for_bundle(
                        bundle
                    )
                )
                self.assertIsNone(result)
                self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
