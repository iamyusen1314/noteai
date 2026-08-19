from __future__ import annotations

import ast
import hashlib
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
TARGET = ROOT / "tools/stage_and_install_item26_manual_cost_stop_runtime_v3.py"
SOURCE = "1" * 40
ACCEPTANCE = "2" * 40


def load_stager() -> tuple[types.ModuleType, bytes]:
    raw = TARGET.read_bytes()
    module = types.ModuleType("stage_and_install_item26_runtime_v3_test")
    module.__file__ = str(TARGET)
    module.__package__ = None
    exec(compile(raw, str(TARGET), "exec"), module.__dict__)
    return module, raw


def completed(
    arguments: list[str],
    *,
    stdout: bytes = b"",
    returncode: int = 0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(arguments, returncode, stdout, b"")


def git_stdout(*arguments: str) -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", "--no-replace-objects", *arguments],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError((arguments, result.returncode, result.stderr))
    return result.stdout


class StageAndInstallItem26RuntimeV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stager, cls.raw = load_stager()

    def topology_git(self, arguments: list[str]):
        stager = self.stager
        if arguments == ["rev-list", "--parents", "-n", "1", SOURCE]:
            return completed(arguments, stdout=(SOURCE + " " + stager.BASE_REVISION + "\n").encode())
        if arguments == ["rev-list", "--parents", "-n", "1", ACCEPTANCE]:
            return completed(arguments, stdout=(ACCEPTANCE + " " + SOURCE + "\n").encode())
        if arguments[:2] == ["merge-base", "--is-ancestor"]:
            return completed(arguments)
        if arguments[:3] == ["diff", "--name-only", "-z"]:
            parent, child = arguments[3:5]
            if (parent, child) == (stager.BASE_REVISION, SOURCE):
                paths = sorted(stager.SOURCE_REFS)
            elif (parent, child) == (SOURCE, ACCEPTANCE):
                paths = sorted(stager.ACCEPTANCE_REFS)
            else:
                raise AssertionError(arguments)
            return completed(arguments, stdout=("\0".join(paths) + "\0").encode())
        if arguments[:2] == ["rev-parse", "HEAD"]:
            return completed(arguments, stdout=(ACCEPTANCE + "\n").encode())
        if arguments[:2] == ["rev-parse", "@{upstream}"]:
            return completed(arguments, stdout=(ACCEPTANCE + "\n").encode())
        if arguments[:2] == ["rev-parse", stager.BRANCH_REF]:
            return completed(arguments, stdout=(ACCEPTANCE + "\n").encode())
        if arguments == ["status", "--porcelain=v1", "--untracked-files=no"]:
            return completed(arguments)
        if arguments and arguments[0] == "rev-list" and "--" in arguments:
            return completed(arguments)
        raise AssertionError(arguments)

    def test_source_and_root_program_compile_with_normal_and_optimized_semantics(self) -> None:
        compile(self.raw, str(TARGET), "exec", optimize=0)
        compile(self.raw, str(TARGET), "exec", optimize=2)
        compile(self.stager.ROOT_PROGRAM, "<item26-installer-root>", "exec", optimize=0)
        compile(self.stager.ROOT_PROGRAM, "<item26-installer-root>", "exec", optimize=2)

    def test_source_is_post_receipt_future_bootstrap_not_current_authority(self) -> None:
        description = self.stager.__doc__ or ""
        self.assertIn("future", description.lower())
        self.assertIn("O_EXCL", description)
        self.assertIn("non-TTY stdin", description)
        self.assertIn("Neither the outer stager nor its root program", description)
        self.assertNotIn("SOURCE_REVISION =", self.raw.decode("utf-8"))
        self.assertNotIn("ACCEPTANCE_REVISION =", self.raw.decode("utf-8"))

    def test_source_only_status_is_zero_action_and_authorizes_nothing(self) -> None:
        status = self.stager.SOURCE_ONLY_STATUS
        self.assertEqual(status["status"], "SOURCE_ONLY_NOT_EXECUTED")
        self.assertIs(status["authorizes_future_execution"], False)
        for key in (
            "sudo_dispatch_count",
            "root_write_count",
            "custody_access_count",
            "private_key_read_count",
            "authority_public_scratch_directory_create_count",
            "authority_public_scratch_file_create_count",
            "authority_public_scratch_cleanup_count",
            "installer_synchronous_rollback_count",
        ):
            self.assertEqual(status[key], 0)

    def test_future_contract_discloses_public_scratch_and_installer_rollback(self) -> None:
        contract = self.stager.FUTURE_EXECUTION_CONTRACT
        self.assertIs(contract["requires_new_cto_authorization"], True)
        self.assertEqual(
            contract["authority_public_scratch_directory_pattern"],
            ".item26-v2-signature-verify-*",
        )
        self.assertEqual(
            contract["authority_public_scratch_files"],
            ["key", "message", "signature"],
        )
        self.assertEqual(
            contract["authority_public_scratch_files_per_verification"],
            3,
        )
        self.assertIs(
            contract["authority_public_scratch_material_is_public"],
            True,
        )
        self.assertIs(
            contract["authority_public_scratch_synchronous_cleanup"],
            True,
        )
        self.assertIs(
            contract["authority_public_scratch_crash_residue_possible"],
            True,
        )
        self.assertIs(
            contract["installer_synchronous_rollback_must_be_authorized"],
            True,
        )
        self.assertIs(contract["stager_failure_cleanup_authorized"], False)
        self.assertIs(contract["automatic_retry_authorized"], False)

    def test_base_control_preservation_and_exact_topology_are_frozen(self) -> None:
        stager = self.stager
        self.assertEqual(stager.BASE_REVISION, "a4e2a0d106e013c9b3ce730a278345c7552cdcd9")
        self.assertEqual(stager.CONTROL_REVISION, "68aa82ffbdd43e78e585d8956d13d3030ef6a640")
        self.assertEqual(stager.PRESERVATION_REVISION, "2cfb58b9f227a37cc86843bef7dc1014bc185391")
        self.assertEqual(
            stager.SOURCE_REFS,
            stager.LEDGER_REFS | {stager.STAGER_REF, stager.TEST_REF},
        )
        self.assertEqual(len(stager.SOURCE_REFS), 6)
        self.assertEqual(stager.ACCEPTANCE_REFS, stager.LEDGER_REFS)
        self.assertEqual(len(stager.ACCEPTANCE_REFS), 4)
        self.assertTrue(stager.SOURCE_REFS.isdisjoint(set(stager.CONTROL_SOURCE_REFS)))
        self.assertEqual(
            stager.EXPECTED_AUTHORITY_ROOT_SHA256,
            "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85",
        )

    def test_exact_public_blob_bindings_are_present_in_repository(self) -> None:
        stager = self.stager
        cases = (
            (stager.CONTROL_REVISION, stager.INSTALLER_REF, stager.INSTALLER_BINDING),
            (stager.CONTROL_REVISION, stager.AUTHORITY_REF, stager.AUTHORITY_BINDING),
            (stager.PRESERVATION_REVISION, stager.RECEIPT_REF, stager.RECEIPT_BINDING),
        )
        for revision, ref, binding in cases:
            with self.subTest(ref=ref):
                oid = git_stdout("rev-parse", revision + ":" + ref).decode().strip()
                raw = git_stdout("cat-file", "blob", oid)
                self.assertEqual(oid, binding["git_blob_oid"])
                self.assertEqual(len(raw), binding["size"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), binding["file_sha256"])

    def test_receipt_and_signed_control_sources_are_untouched_through_base(self) -> None:
        stager = self.stager
        self.assertEqual(
            git_stdout(
                "rev-list",
                stager.PRESERVATION_REVISION + ".." + stager.BASE_REVISION,
                "--",
                stager.RECEIPT_REF,
            ),
            b"",
        )
        self.assertEqual(
            git_stdout(
                "rev-list",
                stager.CONTROL_REVISION + ".." + stager.BASE_REVISION,
                "--",
                *stager.CONTROL_SOURCE_REFS,
            ),
            b"",
        )

    def test_topology_accepts_only_direct_child_exact6_then_exact4(self) -> None:
        with mock.patch.object(self.stager, "_run_git", side_effect=self.topology_git):
            self.stager._validate_topology(SOURCE, ACCEPTANCE)

    def test_topology_rejects_source_path_mutation(self) -> None:
        original = self.topology_git

        def drift(arguments):
            result = original(arguments)
            if arguments[:5] == [
                "diff",
                "--name-only",
                "-z",
                self.stager.BASE_REVISION,
                SOURCE,
            ]:
                paths = sorted(self.stager.SOURCE_REFS | {"unexpected"})
                return completed(arguments, stdout=("\0".join(paths) + "\0").encode())
            return result

        with mock.patch.object(self.stager, "_run_git", side_effect=drift), self.assertRaisesRegex(
            self.stager.StagerError,
            "source_topology",
        ):
            self.stager._validate_topology(SOURCE, ACCEPTANCE)

    def test_topology_rejects_non_direct_acceptance_and_control_touch(self) -> None:
        for kind in ("parent", "control_touch"):
            with self.subTest(kind=kind):
                original = self.topology_git

                def drift(arguments, kind=kind):
                    if kind == "parent" and arguments == [
                        "rev-list",
                        "--parents",
                        "-n",
                        "1",
                        ACCEPTANCE,
                    ]:
                        return completed(arguments, stdout=(ACCEPTANCE + " " + "3" * 40 + "\n").encode())
                    if (
                        kind == "control_touch"
                        and arguments
                        and arguments[0] == "rev-list"
                        and arguments[1].startswith(self.stager.CONTROL_REVISION)
                    ):
                        return completed(arguments, stdout=("4" * 40 + "\n").encode())
                    return original(arguments)

                with mock.patch.object(self.stager, "_run_git", side_effect=drift), self.assertRaises(
                    self.stager.StagerError
                ):
                    self.stager._validate_topology(SOURCE, ACCEPTANCE)

    def test_topology_requires_local_upstream_and_reviewed_remote_at_acceptance(self) -> None:
        def drift(arguments):
            if arguments[:2] == ["rev-parse", self.stager.BRANCH_REF]:
                return completed(arguments, stdout=("5" * 40 + "\n").encode())
            return self.topology_git(arguments)

        with mock.patch.object(self.stager, "_run_git", side_effect=drift), self.assertRaisesRegex(
            self.stager.StagerError,
            "acceptance_revision",
        ):
            self.stager._validate_topology(SOURCE, ACCEPTANCE)

    def test_build_bundle_rechecks_three_blobs_and_contains_no_blob_bytes(self) -> None:
        observed = []

        def bind(revision, ref, expected, code):
            observed.append((revision, ref, expected, code))
            return ("public:" + ref).encode("ascii")

        with mock.patch.object(self.stager, "_git_blob", side_effect=bind):
            raw = self.stager._build_bundle(SOURCE, ACCEPTANCE, "6" * 64, "7" * 64)
        value = json.loads(raw)
        self.assertEqual(len(observed), 3)
        self.assertEqual(value["source_revision"], SOURCE)
        self.assertEqual(value["acceptance_revision"], ACCEPTANCE)
        self.assertEqual(value["launcher_sha256"], "6" * 64)
        self.assertEqual(value["root_program_sha256"], "7" * 64)
        self.assertEqual(
            value["source_only_status"],
            self.stager.SOURCE_ONLY_STATUS,
        )
        self.assertEqual(
            value["future_execution_contract"],
            self.stager.FUTURE_EXECUTION_CONTRACT,
        )
        self.assertNotIn("content", value["installer"])
        self.assertEqual(self.stager.canonical_bytes(value), raw)

    def test_stager_self_binding_uses_explicit_launcher_and_root_hashes(self) -> None:
        self.assertEqual(self.stager.EXPECTED_USER_UID, 501)
        launcher_sha = hashlib.sha256(self.raw).hexdigest()
        root_sha = hashlib.sha256(self.stager.ROOT_PROGRAM.encode("ascii")).hexdigest()
        with mock.patch.object(
            self.stager,
            "_git_text",
            return_value="9" * 40,
        ), mock.patch.object(
            self.stager,
            "_git_stdout",
            return_value=self.raw,
        ), mock.patch.object(
            self.stager,
            "EXPECTED_USER_UID",
            os.getuid(),
        ):
            self.stager._read_and_bind_stager(
                launcher_sha,
                root_sha,
                SOURCE,
                ACCEPTANCE,
            )
            with self.assertRaisesRegex(
                self.stager.StagerError,
                "source_binding",
            ):
                self.stager._read_and_bind_stager(
                    "0" * 64,
                    root_sha,
                    SOURCE,
                    ACCEPTANCE,
                )
        self.assertEqual(self.stager.EXPECTED_USER_UID, 501)

    def test_canonical_parser_rejects_duplicate_keys_and_noncanonical_json(self) -> None:
        for raw in (b'{"a":1,"a":1}\n', b'{"a": 1}\n'):
            with self.subTest(raw=raw), self.assertRaisesRegex(
                self.stager.StagerError,
                "synthetic_canonical",
            ):
                self.stager._parse_canonical(raw, "synthetic_canonical")

    def test_root_program_uses_exact_git_safe_directory_and_cat_file(self) -> None:
        source = self.stager.ROOT_PROGRAM
        self.assertIn('"safe.directory="+str(REPO)', source)
        self.assertIn('["cat-file","blob",oid]', source)
        self.assertIn("no_touch(CONTROL,acceptance,CONTROL_REFS)", source)
        self.assertIn("no_touch(PRESERVE,acceptance,(RECEIPT_REF,))", source)
        self.assertIn("changed(BASE,source)!=SOURCE_PATHS", source)
        self.assertIn("changed(source,acceptance)!=LEDGERS", source)
        self.assertIn(
            'bundle.get("future_execution_contract")!=FUTURE_CONTRACT',
            source,
        )

    def test_root_preflight_is_metadata_only_for_custody_and_precedes_writes(self) -> None:
        source = self.stager.ROOT_PROGRAM
        custody_start = source.index("custody_fd=os.open")
        custody_end = source.index("return parent_fd", custody_start)
        custody_block = source[custody_start:custody_end]
        self.assertIn("os.stat(name,dir_fd=custody_fd", custody_block)
        self.assertNotIn("os.read(custody_fd", custody_block)
        self.assertNotIn("public_file(custody_fd", custody_block)
        self.assertLess(source.index("parent_fd=preflight()"), source.index("os.mkdir(STAGING.name"))
        self.assertLess(
            source.index(
                "for target in (STAGING,AUTHORITY_DIR,RUNTIME_DIR,JOURNAL_DIR): absent(target)"
            ),
            source.index("os.mkdir(STAGING.name"),
        )

    def test_root_staging_is_exact2_o_excl_and_has_no_cleanup_primitive(self) -> None:
        source = self.stager.ROOT_PROGRAM
        self.assertIn("os.O_EXCL", source)
        self.assertIn("set(os.listdir(staging_fd))", source)
        self.assertIn("pathlib.Path(INSTALLER_REF).name", source)
        self.assertIn("pathlib.Path(AUTHORITY_REF).name", source)
        for forbidden in ("os.unlink", "os.rmdir", "shutil", "rm -", "cleanup("):
            self.assertNotIn(forbidden, source)

    def test_root_installer_receives_receipt_on_anonymous_non_tty_stdin(self) -> None:
        tree = ast.parse(self.stager.ROOT_PROGRAM)
        installer_runs = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "run":
                continue
            for keyword in node.keywords:
                if keyword.arg == "input" and isinstance(keyword.value, ast.Name) and keyword.value.id == "receipt":
                    installer_runs.append(node)
        self.assertEqual(len(installer_runs), 1)
        call = installer_runs[0]
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        self.assertIsInstance(keywords["stderr"], ast.Attribute)
        self.assertEqual(keywords["stderr"].attr, "DEVNULL")

    def test_root_epilogue_is_sanitized_for_classified_and_unknown_failure(self) -> None:
        source = self.stager.ROOT_PROGRAM
        epilogue = source[source.rindex("\ntry:\n    status=main()") + 1 :]
        error_type = type("RootError", (Exception,), {})
        for failure, expected in (
            (error_type("root_fixed_failure"), "root_fixed_failure"),
            (RuntimeError("private detail"), "root_unclassified_failure"),
        ):
            with self.subTest(expected=expected):
                stderr = io.StringIO()

                def fail(failure=failure):
                    raise failure

                namespace = {
                    "E": error_type,
                    "json": json,
                    "main": fail,
                    "sys": types.SimpleNamespace(stderr=stderr),
                }
                with self.assertRaises(SystemExit) as stopped:
                    exec(compile(epilogue, "<root-epilogue>", "exec"), namespace)
                self.assertEqual(stopped.exception.code, 1)
                self.assertEqual(json.loads(stderr.getvalue())["reason"], expected)

    def test_missing_cli_arguments_stop_before_validation_capture_or_sudo(self) -> None:
        output = io.BytesIO()
        fake_stdout = types.SimpleNamespace(buffer=output)
        with mock.patch.object(self.stager.sys, "stdout", fake_stdout), mock.patch.object(
            self.stager,
            "_run_once",
            side_effect=AssertionError("run must not start"),
        ), mock.patch.object(
            self.stager,
            "_open_capture",
            side_effect=AssertionError("capture must not start"),
        ), mock.patch.object(
            self.stager.subprocess,
            "run",
            side_effect=AssertionError("sudo must not start"),
        ):
            status = self.stager.main([])
        self.assertEqual(status, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["reason"], "stager_arguments")
        self.assertIs(result["automatic_retry_allowed"], False)
        self.assertIs(result["cleanup_authorized"], False)

    def test_real_default_entrypoint_is_inert_and_returns_fixed_block(self) -> None:
        result = subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-E",
                "-S",
                "-B",
                str(TARGET),
            ],
            cwd=ROOT,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason"], "stager_arguments")
        self.assertIs(payload["automatic_retry_allowed"], False)
        self.assertIs(payload["cleanup_authorized"], False)

    def test_cli_requires_explicit_source_acceptance_launcher_and_root_hashes(self) -> None:
        output = io.BytesIO()
        fake_stdout = types.SimpleNamespace(buffer=output)
        success = {
            "schema": self.stager.OUTER_SCHEMA,
            "status": "synthetic_success",
        }
        with mock.patch.object(self.stager.sys, "stdout", fake_stdout), mock.patch.object(
            self.stager,
            "_run_once",
            return_value=success,
        ) as run_once:
            status = self.stager.main(
                [
                    "--expected-source-revision",
                    SOURCE,
                    "--expected-acceptance-revision",
                    ACCEPTANCE,
                    "--expected-launcher-sha256",
                    "6" * 64,
                    "--expected-root-program-sha256",
                    "7" * 64,
                ]
            )
        self.assertEqual(status, 0)
        run_once.assert_called_once_with(SOURCE, ACCEPTANCE, "6" * 64, "7" * 64)
        self.assertEqual(json.loads(output.getvalue()), success)

    def test_preflight_failure_stops_before_capture_and_sudo(self) -> None:
        with mock.patch.object(
            self.stager,
            "_validate_outer_boundary",
            side_effect=self.stager.StagerError("synthetic_preflight"),
        ), mock.patch.object(
            self.stager,
            "_open_capture",
            side_effect=AssertionError("capture must not start"),
        ), mock.patch.object(
            self.stager.subprocess,
            "run",
            side_effect=AssertionError("sudo must not start"),
        ), self.assertRaisesRegex(
            self.stager.StagerError,
            "synthetic_preflight",
        ):
            self.stager._run_once(SOURCE, ACCEPTANCE, "6" * 64, "7" * 64)

    def test_capture_freezes_post_create_parent_identity(self) -> None:
        self.assertEqual(self.stager.EXPECTED_USER_UID, 501)
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-stager-capture-",
            dir=ROOT,
        ) as temporary:
            repository = Path(temporary)
            capture_parent = repository / ".codex"
            capture_parent.mkdir(mode=0o755)
            before = self.stager._stable(capture_parent.lstat())
            with mock.patch.object(
                self.stager,
                "REPOSITORY_ROOT",
                repository,
            ), mock.patch.object(
                self.stager,
                "EXPECTED_USER_UID",
                os.getuid(),
            ):
                capture_fd, parent_fd, identity = self.stager._open_capture(
                    ACCEPTANCE
                )
                try:
                    after_fd = self.stager._stable(os.fstat(parent_fd))
                    after_path = self.stager._stable(capture_parent.lstat())
                finally:
                    os.close(capture_fd)
                    os.close(parent_fd)
            self.assertNotEqual(before, identity)
            self.assertEqual(identity, after_fd)
            self.assertEqual(identity, after_path)
        self.assertEqual(self.stager.EXPECTED_USER_UID, 501)

    def test_run_once_dispatches_one_sudo_with_bundle_as_non_tty_stdin(self) -> None:
        bundle = b'{"synthetic":true}\n'
        installed = {"activation_receipt_sha256": "8" * 64}
        sudo_row = types.SimpleNamespace(
            st_dev=1,
            st_ino=2,
            st_mode=stat.S_IFREG | 0o4511,
            st_uid=0,
            st_gid=0,
            st_nlink=1,
            st_size=1,
            st_mtime_ns=1,
            st_ctime_ns=1,
        )
        sudo_path = mock.MagicMock(spec=Path)
        sudo_path.__str__.return_value = "/usr/bin/sudo"
        sudo_path.lstat.return_value = sudo_row
        process = completed(["sudo"], returncode=0)
        with mock.patch.object(self.stager, "_validate_outer_boundary"), mock.patch.object(
            self.stager,
            "_build_bundle",
            return_value=bundle,
        ), mock.patch.object(
            self.stager,
            "_open_capture",
            return_value=(30, 31, (1, 2, 3)),
        ), mock.patch.object(
            self.stager,
            "_validate_tool",
            return_value=sudo_row,
        ), mock.patch.object(
            self.stager,
            "SYSTEM_SUDO",
            sudo_path,
        ), mock.patch.object(
            self.stager,
            "_read_validate_capture",
            return_value=(b'{"result":true}\n', installed),
        ), mock.patch.object(
            self.stager.subprocess,
            "run",
            return_value=process,
        ) as run, mock.patch.object(
            self.stager.os,
            "close",
        ), mock.patch.object(
            self.stager.sys,
            "stderr",
            io.StringIO(),
        ):
            result = self.stager._run_once(SOURCE, ACCEPTANCE, "6" * 64, "7" * 64)
        run.assert_called_once()
        arguments, keywords = run.call_args
        command = arguments[0]
        self.assertEqual(command[:3], ["/usr/bin/sudo", "-k", "--"])
        self.assertEqual(keywords["input"], bundle)
        self.assertEqual(keywords["stdout"], 30)
        self.assertIsNone(keywords["stderr"])
        self.assertEqual(result["sudo_dispatch_count"], 1)
        self.assertEqual(result["automatic_retry_count"], 0)
        self.assertEqual(result["stager_cleanup_count"], 0)

    def test_git_wrapper_uses_exact_safe_directory_and_non_tty_stdin(self) -> None:
        git_row = self.stager.SYSTEM_GIT.lstat()
        with mock.patch.object(
            self.stager,
            "_validate_tool",
            return_value=git_row,
        ), mock.patch.object(
            self.stager.subprocess,
            "run",
            return_value=completed(["git"], stdout=b"ok\n"),
        ) as run:
            result = self.stager._run_git(["rev-parse", "HEAD"])
        self.assertEqual(result.stdout, b"ok\n")
        command = run.call_args.args[0]
        self.assertEqual(
            command[:4],
            [
                str(self.stager.SYSTEM_GIT),
                "-c",
                "safe.directory=" + str(self.stager.REPOSITORY_ROOT),
                "--no-replace-objects",
            ],
        )
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_module_has_no_cloud_database_private_key_or_installer_import(self) -> None:
        tree = ast.parse(self.raw.decode("utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        forbidden_prefixes = (
            "boto",
            "http",
            "psycopg",
            "requests",
            "sqlite",
            "install_item26",
            "verify_item26",
        )
        self.assertFalse(any(name.startswith(forbidden_prefixes) for name in imports))
        source = self.raw.decode("utf-8")
        self.assertNotIn("private_key_pem", source)
        self.assertNotIn("read_private", source)


if __name__ == "__main__":
    unittest.main()
