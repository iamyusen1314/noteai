import base64
import copy
from contextlib import contextmanager
import io
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
        "created_at_utc": "2026-08-18T14:00:00Z",
        "started_at_utc": "2026-08-18T14:00:01Z",
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
            "push": ci_row(401, "push", "2026-08-18T14:30:00Z"),
            "pull_request": ci_row(
                402,
                "pull_request",
                    "2026-08-18T14:31:00Z",
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
        cls.sources[authority.BOOTSTRAP_REF] = {
            "git_blob_oid": authority.EXPECTED_BOOTSTRAP_GIT_BLOB_OID,
            "file_sha256": authority.EXPECTED_BOOTSTRAP_FILE_SHA256,
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
        activated_at_utc="2026-08-18T14:32:00Z",
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
        if ref == authority.PUBLIC_ROOT_REF:
            raw = self.root_raw
        elif ref == authority.BOOTSTRAP_REF:
            raw = (ROOT / authority.BOOTSTRAP_REF).read_bytes()
        else:
            raw = b"bound"
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
            payload["historical_checkpoints"]["helper_source_terminal"],
            authority.EXPECTED_HELPER_SOURCE_TERMINAL,
        )
        self.assertEqual(
            payload["historical_checkpoints"][
                "rejected_bootstrap_source_terminal"
            ],
            authority.EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL,
        )
        self.assertEqual(
            payload["historical_checkpoints"]["bootstrap_ledger_terminal"],
            authority.EXPECTED_BOOTSTRAP_LEDGER_TERMINAL,
        )
        self.assertEqual(
            payload["historical_checkpoints"][
                "rejected_root_activation_terminal"
            ],
            authority.EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL,
        )
        self.assertEqual(
            payload["bootstrap_ledger_acceptance_revision"],
            authority.BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
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
                    activated_at_utc="2026-08-18T14:32:00Z",
                    scratch_directory=scratch,
                )

    def test_invalid_unsigned_inputs_do_not_call_sign(self):
        cases = {}
        reused = copy.deepcopy(self.control_ci)
        reused["push"]["run_id"] = authority.EXPECTED_BOOTSTRAP_LEDGER_TERMINAL[
            "push"
        ]["run_id"]
        cases["reused_run_id"] = (reused, self.sources, "2026-08-18T14:32:00Z")
        reused_job = copy.deepcopy(self.control_ci)
        reused_job["pull_request"]["job_id"] = (
            authority.EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"][
                "job_id"
            ]
        )
        cases["reused_helper_job_id"] = (
            reused_job,
            self.sources,
            "2026-08-18T14:32:00Z",
        )
        reused_rejected = copy.deepcopy(self.control_ci)
        reused_rejected["push"]["run_id"] = (
            authority.EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"][
                "run_id"
            ]
        )
        cases["reused_rejected_run_id"] = (
            reused_rejected,
            self.sources,
            "2026-08-18T14:32:00Z",
        )
        reused_rejected_job = copy.deepcopy(self.control_ci)
        reused_rejected_job["pull_request"]["job_id"] = (
            authority.EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL[
                "pull_request"
            ]["job_id"]
        )
        cases["reused_rejected_job_id"] = (
            reused_rejected_job,
            self.sources,
            "2026-08-18T14:32:00Z",
        )
        reused_root_activation = copy.deepcopy(self.control_ci)
        reused_root_activation["push"]["run_id"] = (
            authority.EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"][
                "run_id"
            ]
        )
        cases["reused_root_activation_run_id"] = (
            reused_root_activation,
            self.sources,
            "2026-08-18T14:32:00Z",
        )
        reused_root_activation_job = copy.deepcopy(self.control_ci)
        reused_root_activation_job["pull_request"]["job_id"] = (
            authority.EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL[
                "pull_request"
            ]["job_id"]
        )
        cases["reused_root_activation_job_id"] = (
            reused_root_activation_job,
            self.sources,
            "2026-08-18T14:32:00Z",
        )
        early = copy.deepcopy(self.control_ci)
        early["push"]["created_at_utc"] = "2026-08-18T13:00:00Z"
        early["push"]["started_at_utc"] = "2026-08-18T13:00:01Z"
        cases["early_control"] = (early, self.sources, "2026-08-18T14:32:00Z")
        drifted_sources = copy.deepcopy(self.sources)
        drifted_sources[authority.COLLECTOR_REF]["file_sha256"] = "f" * 64
        cases["source_drift"] = (
            self.control_ci,
            drifted_sources,
            "2026-08-18T14:32:00Z",
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

    def sign_request_raw(self):
        return authority.canonical_bytes(
            {
                "schema": builder.SIGN_REQUEST_SCHEMA,
                "control_ci": self.control_ci,
                "control_source_blobs": self.sources,
                "activated_at_utc": "2026-08-18T14:32:00Z",
            }
        )

    @contextmanager
    def custody(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-v3-custody-", dir=ROOT
        ) as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            for name in builder.CUSTODY_ROLE_FILES:
                path = directory / name
                path.write_bytes(b"synthetic-key-handle")
                path.chmod(0o600)
            with mock.patch.object(
                builder, "CUSTODY_DIRECTORY", directory
            ), mock.patch.object(
                authority, "CUSTODY_DIRECTORY", directory
            ), mock.patch.object(
                builder, "_owner_uid", return_value=os.geteuid()
            ), mock.patch.object(
                builder, "_validate_parent_chain", return_value=None
            ):
                yield directory

    def test_default_repository_execution_rejects_before_custody(self):
        with mock.patch.object(os, "geteuid", return_value=0), \
                mock.patch.object(
                    builder, "_validate_execution_flags", return_value=None
                ), mock.patch.object(
                    builder,
                    "_sign_from_custody",
                    side_effect=AssertionError("custody must not open"),
                ) as custody, self.assertRaisesRegex(
                    builder.SignerError, "execution_path"
                ):
            builder.main(
                [
                    "--control-revision",
                    CONTROL_REVISION,
                    "--repository-root",
                    str(ROOT),
                ],
                stdin=io.BytesIO(self.sign_request_raw()),
                stdout=io.BytesIO(),
            )
        custody.assert_not_called()

    def test_invalid_public_input_never_opens_private_key(self):
        staged = {
            authority.RECEIPT_BUILDER_REF: b"builder",
            authority.VERIFIER_REF: b"authority",
        }
        with mock.patch.object(os, "geteuid", return_value=0), \
                mock.patch.object(
                    builder,
                    "_validate_execution_boundary",
                    return_value=staged,
                ), mock.patch.object(
                    builder,
                    "_sign_from_custody",
                    side_effect=AssertionError("private key must not open"),
                ) as custody, self.assertRaisesRegex(
                    builder.SignerError, "request_invalid"
                ):
            builder.main(
                [
                    "--control-revision",
                    CONTROL_REVISION,
                    "--repository-root",
                    str(ROOT),
                ],
                stdin=io.BytesIO(b'{"schema":"duplicate","schema":"x"}\n'),
                stdout=io.BytesIO(),
            )
        custody.assert_not_called()

    def test_staged_source_drift_rejects_before_public_validator_and_custody(self):
        request = self.sign_request_raw()
        staged = {
            authority.RECEIPT_BUILDER_REF: b"builder-staged",
            authority.VERIFIER_REF: b"authority-staged",
        }

        def record(_revision, ref, *, root):
            del root
            raw = {
                authority.RECEIPT_BUILDER_REF: b"builder-git",
                authority.VERIFIER_REF: b"authority-staged",
                authority.PUBLIC_ROOT_REF: self.root_raw,
            }[ref]
            return {
                "raw": raw,
                "git_blob_oid": "a" * 40,
                "git_blob_sha256": authority._sha(raw),
                "file_sha256": authority._sha(raw),
            }

        with mock.patch.object(
            authority, "_git_blob_record", side_effect=record
        ), mock.patch.object(
            builder,
            "_prepare_unsigned_receipt",
            side_effect=AssertionError("public validator must not run"),
        ) as validate, self.assertRaisesRegex(
            builder.SignerError, "staged_source_drift"
        ):
            builder._prepare_cli_receipt(
                request_raw=request,
                control_revision=CONTROL_REVISION,
                repository_root=ROOT,
                staged_sources=staged,
            )
        validate.assert_not_called()

    def test_interpreter_and_execution_flags_are_pinned_without_asserts(self):
        with mock.patch.object(
            builder.sys, "executable", "/untrusted/python"
        ), self.assertRaisesRegex(builder.SignerError, "interpreter_path"):
            builder._validate_system_interpreter()
        flags = mock.Mock(
            ignore_environment=1,
            no_site=0,
            dont_write_bytecode=1,
        )
        with mock.patch.object(builder.sys, "flags", flags), \
                mock.patch.object(
                    builder,
                    "_validate_system_interpreter",
                    side_effect=AssertionError("wrong flags must reject first"),
                ) as interpreter, self.assertRaisesRegex(
                    builder.SignerError, "execution_flags"
                ):
            builder._validate_execution_flags()
        interpreter.assert_not_called()

    def test_custody_path_inventory_symlink_and_hardlink_reject(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-v3-custody-matrix-", dir=ROOT
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            with mock.patch.object(
                builder, "CUSTODY_DIRECTORY", base
            ), self.assertRaisesRegex(builder.SignerError, "custody_path"):
                builder._open_validated_custody()

        for case in ("extra", "symlink", "hardlink"):
            with self.subTest(case=case), self.custody() as directory:
                local = directory / builder.LOCAL_CI_PRIVATE_KEY_FILE
                if case == "extra":
                    (directory / "extra").write_bytes(b"x")
                elif case == "symlink":
                    local.unlink()
                    local.symlink_to(directory / builder.CUSTODY_ROLE_FILES[0])
                else:
                    other = directory / builder.CUSTODY_ROLE_FILES[0]
                    other.unlink()
                    os.link(local, other)
                with self.assertRaisesRegex(
                    builder.SignerError,
                    "custody_(inventory|file_identity)",
                ):
                    descriptor, _rows = builder._open_validated_custody()
                    os.close(descriptor)

    def test_success_uses_private_fd_without_python_read_and_restores_exact3(self):
        expected_public = b"synthetic-public\n"
        observed = []
        real_open = os.open
        real_read = os.read
        key_fds = set()

        def guarded_open(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == builder.LOCAL_CI_PRIVATE_KEY_FILE:
                key_fds.add(descriptor)
                self.assertTrue(flags & os.O_NOFOLLOW)
            return descriptor

        def guarded_read(descriptor, size):
            if descriptor in key_fds:
                raise AssertionError("Python must never read the private fd")
            return real_read(descriptor, size)

        def openssl(arguments, *, pass_fds, stdout):
            observed.append((list(arguments), pass_fds, stdout))
            if arguments[0] == "pkey":
                self.assertEqual(pass_fds, tuple(key_fds))
                return subprocess.CompletedProcess([], 0, expected_public, b"")
            signature_fd = int(arguments[arguments.index("-out") + 1].rsplit("/", 1)[1])
            self.assertIn(signature_fd, pass_fds)
            os.write(signature_fd, b"s" * 384)
            return subprocess.CompletedProcess([], 0, b"", b"")

        with self.custody() as directory, mock.patch.object(
            builder.os, "open", side_effect=guarded_open
        ), mock.patch.object(
            builder.os, "read", side_effect=guarded_read
        ), mock.patch.object(
            builder, "_run_openssl_fd", side_effect=openssl
        ):
            signature = builder._sign_from_custody(
                b"message", expected_public
            )
            self.assertEqual(signature, b"s" * 384)
            self.assertEqual(
                set(os.listdir(directory)), set(builder.CUSTODY_ROLE_FILES)
            )
        self.assertEqual(len(observed), 2)
        self.assertIn("/dev/fd/", " ".join(observed[1][0]))

    def test_sign_failure_leaves_residue_and_second_call_cannot_retry(self):
        expected_public = b"synthetic-public\n"
        calls = 0

        def openssl(arguments, *, pass_fds, stdout):
            nonlocal calls
            del pass_fds, stdout
            calls += 1
            if arguments[0] == "pkey":
                return subprocess.CompletedProcess([], 0, expected_public, b"")
            return subprocess.CompletedProcess([], 1, b"", b"")

        with self.custody() as directory, mock.patch.object(
            builder, "_run_openssl_fd", side_effect=openssl
        ):
            with self.assertRaisesRegex(
                builder.SignerError, "signature"
            ):
                builder._sign_from_custody(b"message", expected_public)
            residue = directory / builder.SCRATCH_NAME
            self.assertEqual(
                set(residue.iterdir()),
                {
                    residue / builder.MESSAGE_FILE,
                    residue / builder.SIGNATURE_FILE,
                },
            )
            with self.assertRaisesRegex(
                builder.SignerError, "custody_inventory"
            ):
                builder._sign_from_custody(b"message", expected_public)
        self.assertEqual(calls, 2)

    def test_main_writes_only_canonical_receipt_after_prevalidation(self):
        unsigned = {
            "schema": "test",
            "payload": {"control_revision": CONTROL_REVISION},
        }
        output = io.BytesIO()
        staged = {
            authority.RECEIPT_BUILDER_REF: b"builder",
            authority.VERIFIER_REF: b"authority",
        }
        with mock.patch.object(os, "geteuid", return_value=0), \
                mock.patch.object(
                    builder,
                    "_validate_execution_boundary",
                    return_value=staged,
                ), mock.patch.object(
                    builder,
                    "_prepare_cli_receipt",
                    return_value=(unsigned, b"message", b"public"),
                ), mock.patch.object(
                    builder, "_sign_from_custody", return_value=b"s" * 384
                ) as sign:
            self.assertEqual(
                builder.main(
                    [
                        "--control-revision",
                        CONTROL_REVISION,
                        "--repository-root",
                        str(ROOT),
                    ],
                    stdin=io.BytesIO(self.sign_request_raw()),
                    stdout=output,
                ),
                0,
            )
        expected = builder._complete_receipt(unsigned, b"s" * 384)
        self.assertEqual(output.getvalue(), expected)
        self.assertEqual(authority.canonical_bytes(json.loads(expected)), expected)
        sign.assert_called_once_with(b"message", b"public")

    def test_source_contract_has_no_private_read_or_retry_cli_path(self):
        source = (ROOT / authority.RECEIPT_BUILDER_REF).read_text()
        self.assertIn("os.O_NOFOLLOW", source)
        self.assertIn("pass_fds=pass_fds", source)
        self.assertIn("/dev/fd/{key_fd}", source)
        self.assertNotIn('base / "private-key.pem"', source)
        self.assertNotIn("retry", source.lower())
        self.assertNotIn("private_key_pem=", source)


if __name__ == "__main__":
    unittest.main()
