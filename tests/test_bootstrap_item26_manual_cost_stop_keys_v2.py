import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import bootstrap_item26_manual_cost_stop_keys_v2 as bootstrap  # noqa: E402
from tests.test_verify_item26_manual_cost_stop_authority_v2 import (  # noqa: E402
    SyntheticRsa3072Keys,
)


class NonTtyBytesIO(io.BytesIO):
    def isatty(self):
        return False


class ManualCostStopKeyBootstrapV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = SyntheticRsa3072Keys()

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            dir=ROOT,
            prefix=".item26-bootstrap-v2-test-",
        )
        self.base = Path(self.temporary.name).resolve()
        self.noteai = self.base / "NoteAI"
        self.execution = (
            self.noteai / "item26-manual-cost-stop-v2-bootstrap"
        )
        self.custody = self.noteai / "item26-manual-cost-stop-v2-custody"
        self.noteai.mkdir(mode=0o700)
        self.execution.mkdir(mode=0o700)
        self.source = self.execution / bootstrap.BOOTSTRAP_FILE
        self.source.write_bytes(b"reviewed bootstrap source\n")
        self.source.chmod(0o600)
        self.owner_patch = mock.patch.object(
            bootstrap,
            "_owner_uid",
            return_value=os.geteuid(),
        )
        self.owner_patch.start()

    def tearDown(self):
        self.owner_patch.stop()
        self.temporary.cleanup()

    @staticmethod
    def _write_test_private(descriptor):
        os.write(descriptor, b"synthetic-test-private-material\n")

    def _run_success(self):
        public = [self.keys.public[role] for role in bootstrap.ROLE_FILES]
        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=self._write_test_private,
        ), mock.patch.object(
            bootstrap,
            "_export_public_key",
            side_effect=public,
        ):
            return bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )

    def test_success_creates_exact_private_inventory_and_exports_only_public(self):
        result = self._run_success()
        self.assertEqual(
            result["status"],
            "THREE_RSA3072_KEYS_CREATED_PUBLIC_KEYS_EXPORTED",
        )
        self.assertEqual(set(result["public_keys"]), set(bootstrap.ROLE_FILES))
        self.assertEqual(result["private_key_generation_count"], 3)
        self.assertEqual(result["private_key_python_read_count"], 0)
        self.assertEqual(result["private_key_output_count"], 0)
        self.assertEqual(result["public_key_export_count"], 3)
        self.assertFalse(result["authorizes_new_action"])
        self.assertFalse(result["readiness_credit_added"])
        serialized = bootstrap._canonical_bytes(result)
        self.assertNotIn(b"synthetic-test-private-material", serialized)
        self.assertNotIn(b"PRIVATE KEY", serialized)
        self.assertEqual(
            set(os.listdir(self.custody)),
            set(bootstrap.ROLE_FILES.values()),
        )
        self.assertEqual(stat.S_IMODE(self.custody.stat().st_mode), 0o700)
        for name in bootstrap.ROLE_FILES.values():
            row = (self.custody / name).stat()
            self.assertEqual(stat.S_IMODE(row.st_mode), 0o600)
            self.assertEqual(row.st_nlink, 1)
            self.assertGreater(row.st_size, 0)

    def test_mocked_pipeline_exports_three_distinct_public_only_fixtures(self):
        with mock.patch.object(
            bootstrap,
            "_run_openssl",
            side_effect=AssertionError("tests must not generate private keys"),
        ):
            result = self._run_success()
        self.assertEqual(result["private_key_generation_count"], 3)
        self.assertEqual(result["private_key_python_read_count"], 0)
        self.assertEqual(len(set(result["public_key_spki_sha256"].values())), 3)
        self.assertEqual(
            set(os.listdir(self.custody)),
            set(bootstrap.ROLE_FILES.values()),
        )

    def test_shared_role_fixture_contains_public_data_and_no_private_keys(self):
        fixture_source = (
            ROOT / "tests/test_verify_item26_manual_cost_stop_authority_v2.py"
        ).read_text(encoding="utf-8")
        self.assertFalse(hasattr(self.keys, "private"))
        self.assertNotIn("genpkey", fixture_source)
        self.assertNotIn("BEGIN PRIVATE KEY", fixture_source)
        self.assertEqual(set(self.keys.public), set(bootstrap.ROLE_FILES))

    def test_generation_uses_preopened_descriptor_and_never_openssl_out(self):
        read_fd, write_fd = os.pipe()
        try:
            completed = subprocess.CompletedProcess([], 0, stdout=None)
            with mock.patch.object(
                bootstrap,
                "_run_openssl",
                return_value=completed,
            ) as run:
                bootstrap._generate_private_key(write_fd)
            arguments = run.call_args.args[0]
            keywords = run.call_args.kwargs
            self.assertEqual(
                arguments,
                [
                    "genpkey",
                    "-algorithm",
                    "RSA",
                    "-pkeyopt",
                    "rsa_keygen_bits:3072",
                ],
            )
            self.assertNotIn("-out", arguments)
            self.assertEqual(keywords["stdout"], write_fd)
            self.assertEqual(keywords["stdin"], subprocess.DEVNULL)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_public_export_passes_private_descriptor_as_stdin(self):
        public = self.keys.public["provider"]
        completed = subprocess.CompletedProcess([], 0, stdout=public)
        read_fd, write_fd = os.pipe()
        try:
            with mock.patch.object(
                bootstrap,
                "_run_openssl",
                return_value=completed,
            ) as run:
                self.assertEqual(bootstrap._export_public_key(read_fd), public)
            self.assertEqual(run.call_args.args[0], ["pkey", "-pubout"])
            self.assertEqual(run.call_args.kwargs["stdin"], read_fd)
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_python_never_reads_private_descriptors(self):
        public = [self.keys.public[role] for role in bootstrap.ROLE_FILES]
        identities = [
            (value, f"{index:064x}")
            for index, value in enumerate(public, 1)
        ]
        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=self._write_test_private,
        ), mock.patch.object(
            bootstrap,
            "_export_public_key",
            side_effect=public,
        ), mock.patch.object(
            bootstrap,
            "_public_identity_from_bytes",
            side_effect=identities,
        ), mock.patch.object(
            bootstrap.os,
            "read",
            side_effect=AssertionError("Python must not read private bytes"),
        ):
            result = bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        self.assertEqual(result["private_key_python_read_count"], 0)

    def test_second_invocation_never_overwrites_existing_custody(self):
        first = self._run_success()
        before = {
            name: bootstrap._stable((self.custody / name).stat())
            for name in bootstrap.ROLE_FILES.values()
        }
        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=AssertionError("generation must not repeat"),
        ), self.assertRaisesRegex(BootstrapError, "noteai_inventory"):
            bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        self.assertEqual(first["private_key_generation_count"], 3)
        self.assertEqual(
            before,
            {
                name: bootstrap._stable((self.custody / name).stat())
                for name in bootstrap.ROLE_FILES.values()
            },
        )

    def test_second_key_failure_leaves_partial_residue_without_cleanup(self):
        calls = 0

        def generate(descriptor):
            nonlocal calls
            calls += 1
            os.write(descriptor, b"partial-private\n")
            if calls == 2:
                raise bootstrap.BootstrapError("synthetic_generation_failure")

        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=generate,
        ), mock.patch.object(
            bootstrap.os,
            "unlink",
            side_effect=AssertionError("cleanup is forbidden"),
        ), mock.patch.object(
            bootstrap.os,
            "rmdir",
            side_effect=AssertionError("cleanup is forbidden"),
        ), self.assertRaisesRegex(BootstrapError, "synthetic_generation_failure"):
            bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        self.assertTrue(self.custody.is_dir())
        self.assertEqual(
            set(os.listdir(self.custody)),
            {
                bootstrap.ROLE_FILES["provider"],
                bootstrap.ROLE_FILES["confirmation"],
            },
        )

    def test_public_export_failure_leaves_all_three_keys(self):
        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=self._write_test_private,
        ), mock.patch.object(
            bootstrap,
            "_export_public_key",
            side_effect=bootstrap.BootstrapError("synthetic_export_failure"),
        ), self.assertRaisesRegex(BootstrapError, "synthetic_export_failure"):
            bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        self.assertEqual(
            set(os.listdir(self.custody)),
            set(bootstrap.ROLE_FILES.values()),
        )

    def test_duplicate_public_keys_are_terminal_residue(self):
        duplicate = self.keys.public["provider"]
        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=self._write_test_private,
        ), mock.patch.object(
            bootstrap,
            "_export_public_key",
            side_effect=[duplicate, duplicate, duplicate],
        ), self.assertRaisesRegex(BootstrapError, "not_distinct"):
            bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        self.assertEqual(len(os.listdir(self.custody)), 3)

    def test_invalid_public_key_is_rejected_without_private_output(self):
        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=self._write_test_private,
        ), mock.patch.object(
            bootstrap,
            "_export_public_key",
            return_value=b"not-a-public-key\n",
        ), self.assertRaises(BootstrapError):
            bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        self.assertEqual(len(os.listdir(self.custody)), 3)

    def test_extra_noteai_entry_rejects_before_custody_creation(self):
        (self.noteai / "unexpected").mkdir(mode=0o700)
        with mock.patch.object(
            bootstrap,
            "_generate_private_key",
            side_effect=AssertionError("generation must not start"),
        ), self.assertRaisesRegex(BootstrapError, "noteai_inventory"):
            bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        self.assertFalse(self.custody.exists())

    def test_world_writable_parent_rejects_before_custody_creation(self):
        self.base.chmod(0o777)
        try:
            with mock.patch.object(
                bootstrap,
                "_generate_private_key",
                side_effect=AssertionError("generation must not start"),
            ), self.assertRaisesRegex(BootstrapError, "parent_identity"):
                bootstrap.bootstrap_keys(
                    noteai_directory=self.noteai,
                    execution_directory=self.execution,
                    custody_directory=self.custody,
                )
            self.assertFalse(self.custody.exists())
        finally:
            self.base.chmod(0o700)

    def test_symlink_execution_entry_is_rejected(self):
        source_target = self.base / "source-target.py"
        source_target.write_bytes(b"source\n")
        source_target.chmod(0o600)
        self.source.unlink()
        self.source.symlink_to(source_target)
        fake_flags = types.SimpleNamespace(
            ignore_environment=1,
            no_site=1,
            dont_write_bytecode=1,
        )
        with mock.patch.object(bootstrap, "__file__", str(self.source)), \
                mock.patch.object(bootstrap, "EXECUTION_DIRECTORY", self.execution), \
                mock.patch.object(bootstrap, "_validate_system_interpreter"), \
                mock.patch.object(bootstrap, "OPENSSL", self.source), \
                mock.patch.object(bootstrap, "EXPECTED_OPENSSL_SHA256", "0" * 64), \
                mock.patch.object(sys, "flags", fake_flags), \
                self.assertRaises(BootstrapError):
            bootstrap._validate_execution_boundary()

    def test_hardlinked_role_file_identity_is_rejected(self):
        first = self.base / "first"
        second = self.base / "second"
        first.write_bytes(b"x")
        first.chmod(0o600)
        os.link(first, second)
        with self.assertRaisesRegex(BootstrapError, "file_identity"):
            bootstrap._validate_regular_file(
                first.stat(),
                mode=0o600,
                allow_empty=False,
            )

    def test_main_rejects_arguments_tty_and_nonroot_before_execution_io(self):
        with mock.patch.object(
            bootstrap,
            "_validate_execution_boundary",
            side_effect=AssertionError("execution boundary must not run"),
        ), self.assertRaisesRegex(BootstrapError, "arguments"):
            bootstrap.main([], stdout=NonTtyBytesIO())
        tty = NonTtyBytesIO()
        tty.isatty = lambda: True
        with mock.patch.object(bootstrap.os, "geteuid", return_value=os.geteuid()), \
                mock.patch.object(bootstrap, "ROOT_UID", os.geteuid()), \
                mock.patch.object(
                    bootstrap,
                    "_validate_execution_boundary",
                    side_effect=AssertionError("execution boundary must not run"),
                ), self.assertRaisesRegex(BootstrapError, "tty_output"):
            bootstrap.main([bootstrap.EXECUTION_FLAG], stdout=tty)
        with mock.patch.object(bootstrap.os, "geteuid", return_value=501), \
                mock.patch.object(bootstrap, "ROOT_UID", 0), \
                mock.patch.object(
                    bootstrap,
                    "_validate_execution_boundary",
                    side_effect=AssertionError("execution boundary must not run"),
                ), self.assertRaisesRegex(BootstrapError, "root_required"):
            bootstrap.main(
                [bootstrap.EXECUTION_FLAG],
                stdout=NonTtyBytesIO(),
            )

    def test_production_library_path_cannot_bypass_execution_boundary(self):
        with mock.patch.object(bootstrap, "_owner_uid", return_value=0), \
                mock.patch.object(bootstrap.os, "geteuid", return_value=0), \
                mock.patch.object(
                    bootstrap,
                    "_validate_execution_boundary",
                    side_effect=bootstrap.BootstrapError("verified_boundary"),
                ) as boundary, self.assertRaisesRegex(
                    BootstrapError,
                    "production_path",
                ):
            bootstrap.bootstrap_keys(
                noteai_directory=self.noteai,
                execution_directory=self.execution,
                custody_directory=self.custody,
            )
        boundary.assert_not_called()
        with mock.patch.object(bootstrap, "_owner_uid", return_value=0), \
                mock.patch.object(bootstrap.os, "geteuid", return_value=0), \
                mock.patch.object(
                    bootstrap,
                    "_validate_execution_boundary",
                    side_effect=bootstrap.BootstrapError("verified_boundary"),
                ) as boundary, mock.patch.object(
                    bootstrap,
                    "_open_custody",
                    side_effect=AssertionError("mutation must not start"),
                ), self.assertRaisesRegex(BootstrapError, "verified_boundary"):
            bootstrap.bootstrap_keys()
        boundary.assert_called_once_with()

    def test_main_writes_only_canonical_public_result(self):
        output = NonTtyBytesIO()
        candidate = {
            "schema": bootstrap.PUBLIC_EXPORT_SCHEMA,
            "status": "PUBLIC_ONLY_TEST",
            "public_keys": {"provider": "PUBLIC"},
        }
        with mock.patch.object(bootstrap.os, "geteuid", return_value=os.geteuid()), \
                mock.patch.object(bootstrap, "ROOT_UID", os.geteuid()), \
                mock.patch.object(bootstrap, "_validate_execution_boundary"), \
                mock.patch.object(bootstrap, "bootstrap_keys", return_value=candidate):
            self.assertEqual(
                bootstrap.main([bootstrap.EXECUTION_FLAG], stdout=output),
                0,
            )
        self.assertEqual(output.getvalue(), bootstrap._canonical_bytes(candidate))

    def test_checkout_cli_fails_fixed_without_traceback_or_custody(self):
        result = subprocess.run(
            [
                sys.executable,
                "-E",
                "-S",
                "-B",
                str(ROOT / bootstrap.BOOTSTRAP_REF),
                bootstrap.EXECUTION_FLAG,
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"Traceback", result.stderr)
        value = json.loads(result.stderr.decode("ascii"))
        self.assertEqual(value["status"], "BLOCKED_RESIDUE_REVIEW_REQUIRED")
        self.assertFalse(value["automatic_retry_allowed"])
        self.assertFalse(value["cleanup_authorized"])
        self.assertFalse(self.custody.exists())

    def test_source_contains_no_private_read_cleanup_or_openssl_out_path(self):
        source = (ROOT / bootstrap.BOOTSTRAP_REF).read_text(encoding="utf-8")
        self.assertNotIn("os.unlink(", source)
        self.assertNotIn("os.rmdir(", source)
        self.assertNotIn("rm -", source)
        self.assertNotIn('"-out",', source)
        self.assertIn("stdout=descriptor", source)
        self.assertIn("stdin=descriptor", source)
        self.assertIn("O_EXCL", source)
        self.assertIn("O_NOFOLLOW", source)


BootstrapError = bootstrap.BootstrapError


if __name__ == "__main__":
    unittest.main()
