from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import types
import unittest
from unittest import mock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tools/stage_and_sign_item26_activation_receipt_v3.py"
EXECUTED_RECEIPT_REF = (
    ".codex/item26-manual-cost-stop-activation-receipt-v3-"
    "68aa82ffbdd43e78e585d8956d13d3030ef6a640.json"
)
EXECUTED_ARTIFACTS = {
    EXECUTED_RECEIPT_REF: {
        "mode": "100644",
        "git_blob_oid": "2a52e03416a096ccfca5ef9958d61a25290b10ac",
        "file_sha256": "61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a",
        "size": 22068,
    },
    "tests/test_stage_and_sign_item26_activation_receipt_v3.py": {
        "mode": "100644",
        "git_blob_oid": "0d1335c064944dbd257535fa336689834658490a",
        "file_sha256": "299fbb53f79896493f5bb3f41318539ba632fceb65534e617dc0a4952cf70f24",
        "size": 19529,
    },
    "tools/stage_and_sign_item26_activation_receipt_v3.py": {
        "mode": "100644",
        "git_blob_oid": "165019c53aa4a25adde0a7a3a636c36007094b3a",
        "file_sha256": "ea42ea7c24cbc747e03165f13be2c67619d4d93a61d13068aeb2ae20cd2f072c",
        "size": 46833,
    },
}
EXECUTED_RECEIPT_SEMANTIC_SHA256 = (
    "df46796224ec4aea6adc078eba06dc436273335a6db227b1e0cfe48eec3c1985"
)
EXECUTED_ROOT_PROGRAM_SHA256 = (
    "572629239fa0c3f7eb6b125071cc30e9bde64136bd02b6024b636f05f0cbbf9e"
)
PROVIDER_OUTPUT_REFS = (
    "deploy/production/evidence/"
    "item26-manual-cost-stop-provider-receipt-v2-20260817.json",
    "deploy/production/evidence/"
    "production-item26-manual-cost-stop-v2-20260817.json",
    "deploy/production/evidence/"
    "item26-manual-cost-stop-terminal-checkpoint-v2-20260817.json",
)
FAILED_CORRECTION_REVISION = "9f2ac29c58f4e9ec63bb3265b1bfe41c4f11c5e8"
FAILED_CORRECTION_TREE = "70b7df3d0b35181919fadabc8c268a15ce851811"
FAILED_CORRECTION_PATHS = {
    ".codex/handoffs/current-task.md",
    ".codex/notes/architecture-summary.md",
    ".codex/notes/risk-register.md",
    "deploy/production/internal-deployment-readiness.json",
    "tests/test_stage_and_sign_item26_activation_receipt_v3.py",
    "tools/stage_and_sign_item26_activation_receipt_v3.py",
}
PORTABILITY_SUCCESSOR_PATHS = FAILED_CORRECTION_PATHS - {
    "tools/stage_and_sign_item26_activation_receipt_v3.py",
}


def load_launcher() -> tuple[types.ModuleType, bytes]:
    raw = TARGET.read_bytes()
    module = types.ModuleType("stage_and_sign_item26_activation_receipt_v3_test")
    module.__file__ = str(TARGET)
    module.__package__ = None
    exec(compile(raw, str(TARGET), "exec"), module.__dict__)
    return module, raw


def git_result(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
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


def git_stdout(*arguments: str) -> bytes:
    result = git_result(*arguments)
    if result.returncode != 0:
        raise AssertionError((arguments, result.returncode, result.stderr))
    return result.stdout


def reviewed_direct_child(parent_revision: str) -> str:
    rows = [
        line.split()
        for line in git_stdout(
            "rev-list",
            "--ancestry-path",
            "--parents",
            parent_revision + "..HEAD",
        ).decode("ascii").splitlines()
        if line
    ]
    candidates = [
        row[0]
        for row in rows
        if len(row) == 2 and row[1] == parent_revision
    ]
    if len(candidates) != 1:
        raise AssertionError(
            ("reviewed direct-child candidates", candidates, rows)
        )
    return candidates[0]


def test_only_verify_signature(
    payload: bytes,
    signature: bytes,
    public_key_pem: bytes,
) -> bool:
    if any(
        type(value) is not bytes or not value
        for value in (payload, signature, public_key_pem)
    ):
        return False
    try:
        public_key = serialization.load_pem_public_key(public_key_pem)
        if (
            not isinstance(public_key, rsa.RSAPublicKey)
            or public_key.key_size != 3072
        ):
            return False
        public_key.verify(
            signature,
            payload,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (InvalidSignature, TypeError, ValueError):
        return False
    return True


class StageAndSignItem26ActivationReceiptV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launcher, cls.raw = load_launcher()

    def test_source_compiles_with_normal_and_optimized_semantics(self) -> None:
        compile(self.raw, str(TARGET), "exec", optimize=0)
        compile(self.raw, str(TARGET), "exec", optimize=2)

    def test_description_is_consumed_historical_correction_not_an_entrypoint(self) -> None:
        description = self.launcher.__doc__ or ""
        self.assertIn("Consumed historical correction", description)
        self.assertIn("not executable for another attempt", description)
        self.assertIs(self.launcher.EXECUTION_CONSUMED, True)
        self.assertEqual(
            self.launcher.REPOSITORY_ROOT,
            Path("/Users/openclaw/Desktop/noteai"),
        )
        self.assertEqual(self.launcher.EXPECTED_USER_UID, 501)
        self.assertEqual(
            self.launcher.PUBLIC_CAPTURE_PATH,
            self.launcher.REPOSITORY_ROOT / EXECUTED_RECEIPT_REF,
        )
        self.assertEqual(self.launcher.SYSTEM_OPENSSL, Path("/usr/bin/openssl"))
        self.assertEqual(
            self.launcher.SYSTEM_OPENSSL_SHA256,
            "517827f877751b6d7abebe404a296fa8e82425c63694a73ab06db35e6d9a8362",
        )

    def test_control_revision_and_exact_two_ci_rows_are_frozen(self) -> None:
        launcher = self.launcher
        self.assertEqual(
            launcher.CONTROL_REVISION,
            "68aa82ffbdd43e78e585d8956d13d3030ef6a640",
        )
        self.assertEqual(set(launcher.CONTROL_CI), {"push", "pull_request"})
        expected_common = {
            "attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "head_sha": launcher.CONTROL_REVISION,
            "dispatch_count": 1,
            "rerun_count": 0,
            "workflow_name": "CI",
            "workflow_path": ".github/workflows/ci.yml",
            "job_name": "test",
            "job_count": 1,
            "failed_step_count": 0,
            "step_count": 22,
            "unit_test_count": 2621,
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
        self.assertEqual(len(launcher.CONTROL_CI["push"]), 29)
        self.assertEqual(len(launcher.CONTROL_CI["pull_request"]), 29)
        for event, row in launcher.CONTROL_CI.items():
            self.assertEqual(row["event"], event)
            for key, value in expected_common.items():
                self.assertEqual(row[key], value)
        self.assertEqual(
            (
                launcher.CONTROL_CI["push"]["run_id"],
                launcher.CONTROL_CI["push"]["job_id"],
                launcher.CONTROL_CI["push"]["created_at_utc"],
                launcher.CONTROL_CI["push"]["started_at_utc"],
                launcher.CONTROL_CI["push"]["completed_at_utc"],
            ),
            (
                32147676628,
                95745356212,
                "2026-08-18T14:19:58Z",
                "2026-08-18T14:20:01Z",
                "2026-08-18T14:52:40Z",
            ),
        )
        self.assertEqual(
            (
                launcher.CONTROL_CI["pull_request"]["run_id"],
                launcher.CONTROL_CI["pull_request"]["job_id"],
                launcher.CONTROL_CI["pull_request"]["created_at_utc"],
                launcher.CONTROL_CI["pull_request"]["started_at_utc"],
                launcher.CONTROL_CI["pull_request"]["completed_at_utc"],
            ),
            (
                32147682239,
                95745374406,
                "2026-08-18T14:20:01Z",
                "2026-08-18T14:20:04Z",
                "2026-08-18T14:46:13Z",
            ),
        )

    def test_canonical_ci_and_twelve_source_hashes_are_frozen(self) -> None:
        launcher = self.launcher
        self.assertEqual(len(launcher.CONTROL_SOURCE_BLOBS), 12)
        self.assertEqual(
            hashlib.sha256(
                launcher.canonical_bytes(launcher.CONTROL_CI)
            ).hexdigest(),
            launcher.EXPECTED_CONTROL_CI_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(
                launcher.canonical_bytes(launcher.CONTROL_SOURCE_BLOBS)
            ).hexdigest(),
            launcher.EXPECTED_CONTROL_SOURCES_SHA256,
        )
        self.assertEqual(
            launcher.CONTROL_SOURCE_BLOBS[launcher.BUILDER_REF],
            {
                "git_blob_oid": "0274b4eb97dc5070176331a2f0c3922fb9c84120",
                "file_sha256": "d6ab77d5cd31c03bb5b1949fa9b60e6d2a904e872b31b5c95f63ad41f8b96a08",
            },
        )
        self.assertEqual(
            launcher.CONTROL_SOURCE_BLOBS[launcher.AUTHORITY_REF],
            {
                "git_blob_oid": "91d5eaf9d63f3595c257ad31502407d1bb9a3cb0",
                "file_sha256": "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d",
            },
        )

    def test_root_literal_is_fixed_compilable_and_has_no_placeholder(self) -> None:
        launcher = self.launcher
        compile(launcher.ROOT_PROGRAM, "<item26-root-literal>", "exec", optimize=0)
        compile(launcher.ROOT_PROGRAM, "<item26-root-literal>", "exec", optimize=2)
        self.assertNotIn("__CONTROL", launcher.ROOT_PROGRAM)
        self.assertIn(launcher.EXPECTED_CONTROL_CI_SHA256, launcher.ROOT_PROGRAM)
        self.assertIn(
            launcher.EXPECTED_CONTROL_SOURCES_SHA256,
            launcher.ROOT_PROGRAM,
        )

    def test_root_epilogue_success_exits_zero_without_failure_record(self) -> None:
        source = self.launcher.ROOT_PROGRAM
        epilogue = source[source.rindex("\ntry:\n    root_status=main()") + 1 :]
        stderr = io.StringIO()
        namespace = {
            "E": type("RootClassifiedError", (Exception,), {}),
            "json": json,
            "main": lambda: 0,
            "sys": types.SimpleNamespace(stderr=stderr),
        }
        with self.assertRaises(SystemExit) as stopped:
            exec(compile(epilogue, "<real-root-epilogue>", "exec"), namespace)
        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(stderr.getvalue(), "")

    def test_root_epilogue_classifies_expected_and_unclassified_failures(self) -> None:
        source = self.launcher.ROOT_PROGRAM
        epilogue = source[source.rindex("\ntry:\n    root_status=main()") + 1 :]
        error_type = type("RootClassifiedError", (Exception,), {})
        cases = (
            (error_type("root_fixed_failure"), "root_fixed_failure"),
            (RuntimeError("secret detail"), "root_unclassified_failure"),
        )
        for failure, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                stderr = io.StringIO()

                def fail(failure: BaseException = failure) -> int:
                    raise failure

                namespace = {
                    "E": error_type,
                    "json": json,
                    "main": fail,
                    "sys": types.SimpleNamespace(stderr=stderr),
                }
                with self.assertRaises(SystemExit) as stopped:
                    exec(
                        compile(epilogue, "<real-root-epilogue>", "exec"),
                        namespace,
                    )
                self.assertEqual(stopped.exception.code, 1)
                record = json.loads(stderr.getvalue())
                self.assertEqual(record["reason"], expected_reason)
                self.assertEqual(
                    record["status"],
                    "BLOCKED_RESIDUE_REVIEW_REQUIRED",
                )

    def test_executed_attempt_commit_freezes_exact_three_public_artifacts(self) -> None:
        launcher = self.launcher
        revision = launcher.EXECUTED_ATTEMPT_REVISION
        self.assertEqual(revision, "2cfb58b9f227a37cc86843bef7dc1014bc185391")
        self.assertIs(launcher.EXECUTION_CONSUMED, True)
        parents = git_stdout("rev-list", "--parents", "-n", "1", revision).decode(
            "ascii"
        ).split()
        self.assertEqual(parents, [revision, launcher.CONTROL_REVISION])
        changed = git_stdout(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            revision,
        ).decode("utf-8").splitlines()
        self.assertEqual(set(changed), set(EXECUTED_ARTIFACTS))
        self.assertEqual(len(changed), 3)
        tree = git_stdout(
            "ls-tree",
            "-z",
            revision,
            "--",
            *sorted(EXECUTED_ARTIFACTS),
        )
        rows = {}
        for raw_row in tree.rstrip(b"\0").split(b"\0"):
            metadata, path = raw_row.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            self.assertEqual(kind, "blob")
            rows[path.decode("utf-8")] = (mode, oid)
        self.assertEqual(set(rows), set(EXECUTED_ARTIFACTS))
        for ref, expected in EXECUTED_ARTIFACTS.items():
            with self.subTest(ref=ref):
                raw = git_stdout("show", revision + ":" + ref)
                self.assertEqual(rows[ref], (expected["mode"], expected["git_blob_oid"]))
                self.assertEqual(len(raw), expected["size"])
                self.assertEqual(
                    hashlib.sha256(raw).hexdigest(),
                    expected["file_sha256"],
                )

    def test_executed_launcher_freezes_old_root_epilogue_defect(self) -> None:
        launcher = self.launcher
        old_raw = git_stdout(
            "show",
            launcher.EXECUTED_ATTEMPT_REVISION
            + ":tools/stage_and_sign_item26_activation_receipt_v3.py",
        )
        old_launcher = types.ModuleType("executed_item26_launcher_pattern")
        old_launcher.__file__ = str(TARGET)
        old_launcher.__package__ = None
        exec(compile(old_raw, str(TARGET), "exec"), old_launcher.__dict__)
        old_root = old_launcher.ROOT_PROGRAM
        self.assertEqual(
            hashlib.sha256(old_root.encode("ascii")).hexdigest(),
            EXECUTED_ROOT_PROGRAM_SHA256,
        )
        marker = "\ntry:\n    raise SystemExit(main())"
        self.assertIn(marker, old_root)
        old_epilogue = old_root[old_root.rindex(marker) + 1 :]
        stderr = io.StringIO()
        namespace = {
            "E": type("OldRootClassifiedError", (Exception,), {}),
            "json": json,
            "main": lambda: 0,
            "sys": types.SimpleNamespace(stderr=stderr),
        }
        with self.assertRaises(SystemExit) as stopped:
            exec(
                compile(old_epilogue, "<executed-root-epilogue>", "exec"),
                namespace,
            )
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(
            json.loads(stderr.getvalue())["reason"],
            "root_unclassified_failure",
        )

    def test_reviewed_head_is_exact_direct_successor_with_frozen_absences(self) -> None:
        launcher = self.launcher
        failed_parent_row = git_stdout(
            "rev-list", "--parents", "-n", "1", FAILED_CORRECTION_REVISION
        ).decode("ascii").split()
        self.assertEqual(
            failed_parent_row,
            [FAILED_CORRECTION_REVISION, launcher.EXECUTED_ATTEMPT_REVISION],
        )
        self.assertEqual(
            git_stdout(
                "show",
                "-s",
                "--format=%T",
                FAILED_CORRECTION_REVISION,
            ).decode("ascii").strip(),
            FAILED_CORRECTION_TREE,
        )
        failed_changed = git_stdout(
            "diff",
            "--name-only",
            launcher.EXECUTED_ATTEMPT_REVISION
            + ".."
            + FAILED_CORRECTION_REVISION,
        ).decode("utf-8").splitlines()
        self.assertEqual(set(failed_changed), FAILED_CORRECTION_PATHS)
        self.assertEqual(len(failed_changed), 6)

        reviewed = reviewed_direct_child(FAILED_CORRECTION_REVISION)
        parent_row = git_stdout(
            "rev-list", "--parents", "-n", "1", reviewed
        ).decode("ascii").split()
        self.assertEqual(parent_row, [reviewed, FAILED_CORRECTION_REVISION])
        changed = git_stdout(
            "diff",
            "--name-only",
            FAILED_CORRECTION_REVISION + ".." + reviewed,
        ).decode("utf-8").splitlines()
        self.assertEqual(set(changed), PORTABILITY_SUCCESSOR_PATHS)
        self.assertEqual(len(changed), 5)
        receipt_touches = git_stdout(
            "rev-list",
            FAILED_CORRECTION_REVISION + ".." + reviewed,
            "--",
            EXECUTED_RECEIPT_REF,
        )
        self.assertEqual(receipt_touches, b"")
        launcher_touches = git_stdout(
            "rev-list",
            FAILED_CORRECTION_REVISION + ".." + reviewed,
            "--",
            "tools/stage_and_sign_item26_activation_receipt_v3.py",
        )
        self.assertEqual(launcher_touches, b"")
        source_touches = git_stdout(
            "rev-list",
            FAILED_CORRECTION_REVISION + ".." + reviewed,
            "--",
            *sorted(launcher.CONTROL_SOURCE_BLOBS),
        )
        self.assertEqual(source_touches, b"")
        authority_raw = git_stdout(
            "show", launcher.CONTROL_REVISION + ":" + launcher.AUTHORITY_REF
        )
        authority = launcher._load_exact_authority(authority_raw)
        self.assertEqual(
            (
                authority.RECEIPT_REF,
                authority.EVIDENCE_REF,
                authority.CHECKPOINT_REF,
            ),
            PROVIDER_OUTPUT_REFS,
        )
        for ref in PROVIDER_OUTPUT_REFS:
            with self.subTest(ref=ref):
                absent = git_result("cat-file", "-e", reviewed + ":" + ref)
                self.assertNotEqual(absent.returncode, 0)

    def test_root_literal_validates_before_mkdir_and_never_rolls_back(self) -> None:
        source = self.launcher.ROOT_PROGRAM
        self.assertLess(source.index("absent(SIGNER)"), source.index("raw=read_all()"))
        self.assertLess(source.index("root_stage_bundle"), source.index("os.mkdir("))
        self.assertLess(source.index("repo_identity()!=identity"), source.index("os.mkdir("))
        self.assertNotIn("unlink", source)
        self.assertNotIn("rmdir", source)
        self.assertNotIn("TemporaryDirectory", source)
        self.assertNotIn("tempfile", source)

    def test_root_and_signer_process_contracts_are_exact(self) -> None:
        source = self.launcher.ROOT_PROGRAM
        self.assertIn("pathlib.Path.cwd()!=pathlib.Path(\"/\")", source)
        self.assertIn("cwd=REPO", source)
        self.assertIn(
            '["/usr/bin/python3","-E","-S","-B",str(SIGNER/BUILDER_NAME)',
            source,
        )
        self.assertIn('cwd="/"', source)
        self.assertIn("stdout=None", source)
        self.assertEqual(source.count("result=subprocess.run("), 2)

    def test_root_stage_is_dirfd_exclusive_nofollow_and_exact_two(self) -> None:
        source = self.launcher.ROOT_PROGRAM
        self.assertIn("os.mkdir(SIGNER.name,0o700,dir_fd=parent_fd)", source)
        self.assertIn("os.O_EXCL|os.O_NOFOLLOW", source)
        self.assertIn("os.fchmod(fd,0o600)", source)
        self.assertIn("row.st_uid!=0", source)
        self.assertIn("row.st_nlink!=1", source)
        self.assertIn(
            "set(os.listdir(signer_fd))!={BUILDER_NAME,AUTHORITY_NAME}",
            source,
        )

    def test_root_prevalidates_exact_existing_bootstrap_and_custody_metadata(self) -> None:
        source = self.launcher.ROOT_PROGRAM
        self.assertIn(
            "set(os.listdir(parent_fd))!={BOOTSTRAP_DIR_NAME,CUSTODY_DIR_NAME}",
            source,
        )
        self.assertIn("set(os.listdir(bootstrap_fd))!={BOOTSTRAP_FILE}", source)
        self.assertIn("set(os.listdir(custody_fd))!=CUSTODY_FILES", source)
        self.assertIn(
            'BOOTSTRAP_SHA = "2e35d16c2a2f55ddfa1436190ed8869449dd05fb8ae5fb45878ab9c50c0cd9ff"',
            source,
        )
        custody_loop = source[
            source.index("for name in CUSTODY_FILES:") : source.index(
                "os.close(custody_fd)"
            )
        ]
        self.assertIn("os.stat(", custody_loop)
        self.assertNotIn("os.open(", custody_loop)
        self.assertNotIn("os.read(", custody_loop)

    def test_activated_time_is_generated_only_after_stage(self) -> None:
        source = self.launcher.ROOT_PROGRAM
        self.assertLess(source.index("parent_fd=prevalidate_noteai()"), source.index("now=datetime.datetime.now"))
        self.assertLess(source.index("now=datetime.datetime.now"), source.index("os.mkdir("))
        self.assertLess(source.index("now=datetime.datetime.now"), source.index("request=canon("))
        self.assertIn("completed<activated<=after", source)
        self.assertNotIn("activated_at_utc", self.launcher.canonical_bytes({"control_ci": self.launcher.CONTROL_CI}).decode("ascii"))

    def test_launcher_runtime_has_no_filesystem_signature_temporary_cleanup(self) -> None:
        source = self.raw.decode("utf-8")
        self.assertNotIn("import tempfile", source)
        self.assertNotIn("TemporaryDirectory", source)
        self.assertNotIn("os.unlink", source)
        self.assertNotIn("os.rmdir", source)
        self.assertNotIn(".unlink(", source)
        self.assertNotIn(".rmdir(", source)

    def test_external_hashes_bind_launcher_and_root_literal(self) -> None:
        launcher = self.launcher
        production_uid = launcher.EXPECTED_USER_UID
        source_uid = TARGET.lstat().st_uid
        launcher_sha = hashlib.sha256(self.raw).hexdigest()
        root_program_sha = hashlib.sha256(
            launcher.ROOT_PROGRAM.encode("ascii")
        ).hexdigest()
        with mock.patch.object(launcher, "EXPECTED_USER_UID", source_uid):
            launcher._read_and_bind_launcher(launcher_sha, root_program_sha)
            with self.assertRaisesRegex(
                launcher.LauncherError,
                "launcher_source_binding",
            ):
                launcher._read_and_bind_launcher("0" * 64, root_program_sha)
        with mock.patch.object(launcher, "EXPECTED_USER_UID", source_uid + 1):
            with self.assertRaisesRegex(
                launcher.LauncherError,
                "launcher_source_binding",
            ):
                launcher._read_and_bind_launcher(
                    launcher_sha,
                    root_program_sha,
                )
        self.assertEqual(launcher.EXPECTED_USER_UID, production_uid)
        self.assertEqual(production_uid, 501)

    def test_canonical_parser_rejects_duplicates_and_noncanonical_json(self) -> None:
        launcher = self.launcher
        with self.assertRaises(launcher.LauncherError):
            launcher._parse_canonical(b'{"a":1,"a":1}\n', "bad")
        with self.assertRaises(launcher.LauncherError):
            launcher._parse_canonical(b'{"b": 1}\n', "bad")
        self.assertEqual(
            launcher._parse_canonical(b'{"b":1}\n', "bad"),
            {"b": 1},
        )

    def test_public_bundle_contains_only_exact_two_staged_public_blobs(self) -> None:
        launcher = self.launcher
        fake_raw = {
            ref: (b"B" * launcher.STAGED_SOURCE_RECORDS[ref]["size"])
            if ref in launcher.STAGED_SOURCE_RECORDS
            else b"public"
            for ref in launcher.CONTROL_SOURCE_BLOBS
        }
        with mock.patch.object(launcher, "_git_blob", side_effect=lambda ref: fake_raw[ref]):
            bundle, returned = launcher._build_public_bundle()
        value = launcher._parse_canonical(bundle, "bad")
        self.assertEqual(set(value["staged_sources"]), {launcher.BUILDER_REF, launcher.AUTHORITY_REF})
        self.assertEqual(returned, fake_raw)
        self.assertNotIn(b"PRIVATE KEY", bundle)

    def test_open_capture_uses_exclusive_nofollow_user_owned_mode(self) -> None:
        launcher = self.launcher
        production_capture_path = launcher.PUBLIC_CAPTURE_PATH
        production_uid = launcher.EXPECTED_USER_UID
        portable_capture_path = ROOT / EXECUTED_RECEIPT_REF
        parent_row = portable_capture_path.parent.lstat()
        row = types.SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=parent_row.st_uid,
            st_nlink=1,
            st_size=0,
        )
        with mock.patch.object(
            launcher, "PUBLIC_CAPTURE_PATH", portable_capture_path
        ), mock.patch.object(
            launcher, "EXPECTED_USER_UID", parent_row.st_uid
        ), mock.patch.object(
            launcher.os, "open", side_effect=[76, 77]
        ) as opened, mock.patch.object(
            launcher.os, "fchmod"
        ) as fchmod, mock.patch.object(
            launcher.os, "fstat", side_effect=[parent_row, row, parent_row]
        ), mock.patch.object(launcher.os, "fsync"):
            descriptor, parent_descriptor, identity = launcher._open_capture()
        self.assertEqual((descriptor, parent_descriptor), (77, 76))
        self.assertEqual(identity, launcher._stable(parent_row))
        flags = opened.call_args_list[1].args[1]
        self.assertTrue(flags & launcher.os.O_EXCL)
        self.assertTrue(flags & launcher.os.O_NOFOLLOW)
        self.assertTrue(flags & launcher.os.O_CREAT)
        self.assertEqual(opened.call_args_list[1].args[2], 0o600)
        self.assertEqual(opened.call_args_list[1].kwargs["dir_fd"], 76)
        fchmod.assert_called_once_with(77, 0o600)
        with mock.patch.object(
            launcher, "PUBLIC_CAPTURE_PATH", portable_capture_path
        ), mock.patch.object(
            launcher, "EXPECTED_USER_UID", parent_row.st_uid + 1
        ), mock.patch.object(launcher.os, "open") as rejected_open:
            with self.assertRaisesRegex(
                launcher.LauncherError,
                "launcher_capture_parent",
            ):
                launcher._open_capture()
        rejected_open.assert_not_called()
        self.assertEqual(launcher.PUBLIC_CAPTURE_PATH, production_capture_path)
        self.assertEqual(launcher.EXPECTED_USER_UID, production_uid)
        self.assertEqual(production_uid, 501)

    def test_single_sudo_command_has_only_k_before_double_dash(self) -> None:
        launcher = self.launcher
        row = types.SimpleNamespace(
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
        payload = {
            "activated_at_utc": "2026-08-18T15:00:00Z",
        }
        sudo_path = mock.MagicMock()
        sudo_path.__str__.return_value = "/usr/bin/sudo"
        sudo_path.lstat.return_value = row
        with mock.patch.object(launcher, "EXECUTION_CONSUMED", False), mock.patch.object(
            launcher, "_validate_outer_boundary"
        ), mock.patch.object(
            launcher,
            "_build_public_bundle",
            return_value=(b"{}\n", {launcher.AUTHORITY_REF: b"a", launcher.PUBLIC_ROOT_REF: b"r"}),
        ), mock.patch.object(launcher, "_open_capture", return_value=(81, 80, (1,))), mock.patch.object(
            launcher, "_validate_tool", return_value=row
        ), mock.patch.object(launcher, "SYSTEM_SUDO", sudo_path), mock.patch.object(
            launcher, "_stable", return_value=(1,)
        ), mock.patch.object(
            launcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run, mock.patch.object(
            launcher,
            "_read_and_validate_capture",
            return_value=(b"receipt\n", payload),
        ), mock.patch.object(launcher.os, "close"), mock.patch.object(
            launcher.sys, "stderr", io.StringIO()
        ):
            result = launcher._run_once("a" * 64, "b" * 64)
        run.assert_called_once()
        command = run.call_args.args[0]
        marker = command.index("--")
        self.assertEqual(command[: marker + 1], ["/usr/bin/sudo", "-k", "--"])
        self.assertEqual(
            command[marker + 1 : marker + 6],
            ["/usr/bin/python3", "-I", "-E", "-S", "-B"],
        )
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["input"], b"{}\n")
        self.assertEqual(run.call_args.kwargs["stdout"], 81)
        self.assertIsNone(run.call_args.kwargs["stderr"])
        self.assertEqual(run.call_args.kwargs["cwd"], "/")
        self.assertTrue(run.call_args.kwargs["close_fds"])
        self.assertEqual(result["sudo_dispatch_count"], 1)
        self.assertEqual(result["automatic_retry_count"], 0)
        self.assertEqual(result["outer_cleanup_count"], 0)
        self.assertEqual(
            result["authorized_signer_nonsecret_scratch_file_cleanup_count"],
            2,
        )

    def test_consumed_attempt_fails_before_git_path_bundle_capture_or_sudo(self) -> None:
        launcher = self.launcher
        with mock.patch.object(
            launcher, "_validate_outer_boundary"
        ) as boundary, mock.patch.object(
            launcher, "_build_public_bundle"
        ) as bundle, mock.patch.object(
            launcher, "_open_capture"
        ) as capture, mock.patch.object(
            launcher.subprocess, "run"
        ) as dispatched:
            with self.assertRaisesRegex(
                launcher.LauncherError,
                "launcher_replay_forbidden",
            ):
                launcher._run_once("a" * 64, "b" * 64)
        boundary.assert_not_called()
        bundle.assert_not_called()
        capture.assert_not_called()
        dispatched.assert_not_called()

    def test_sudo_failure_stops_without_readback_retry_or_cleanup(self) -> None:
        launcher = self.launcher
        row = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o4511, st_uid=0)
        with mock.patch.object(launcher, "EXECUTION_CONSUMED", False), mock.patch.object(
            launcher, "_validate_outer_boundary"
        ), mock.patch.object(
            launcher,
            "_build_public_bundle",
            return_value=(b"{}\n", {}),
        ), mock.patch.object(launcher, "_open_capture", return_value=(82, 83, (1,))), mock.patch.object(
            launcher, "_validate_tool", return_value=row
        ), mock.patch.object(
            launcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1),
        ) as run, mock.patch.object(
            launcher, "_read_and_validate_capture"
        ) as readback, mock.patch.object(launcher.os, "close") as close, mock.patch.object(
            launcher.sys, "stderr", io.StringIO()
        ):
            with self.assertRaisesRegex(
                launcher.LauncherError,
                "launcher_single_sudo_failed",
            ):
                launcher._run_once("a" * 64, "b" * 64)
        run.assert_called_once()
        readback.assert_not_called()
        self.assertEqual(close.call_args_list, [mock.call(82), mock.call(83)])

    def test_capture_validator_patches_authority_signature_verifier(self) -> None:
        launcher = self.launcher
        expected_payload = {
            "control_revision": launcher.CONTROL_REVISION,
            "control_ci": launcher.CONTROL_CI,
            "control_source_blobs": launcher.CONTROL_SOURCE_BLOBS,
            "item26_status": "unverified",
            "readiness_credit_added": False,
            "activated_at_utc": "2026-08-19T00:15:13Z",
        }
        receipt = launcher.canonical_bytes(
            {"schema": launcher.RECEIPT_SCHEMA, "payload": expected_payload}
        )
        row = types.SimpleNamespace(
            st_dev=1,
            st_ino=2,
            st_mode=stat.S_IFREG | 0o600,
            st_uid=launcher.EXPECTED_USER_UID,
            st_gid=20,
            st_nlink=1,
            st_size=len(receipt),
            st_mtime_ns=1,
            st_ctime_ns=1,
        )
        expected_summary = {
            "activation_receipt_sha256": hashlib.sha256(receipt).hexdigest(),
            "activation_receipt_semantic_sha256": hashlib.sha256(receipt[:-1]).hexdigest(),
            "activated_at_utc": expected_payload["activated_at_utc"],
            "control_revision": launcher.CONTROL_REVISION,
            "authority_epoch_id": launcher.AUTHORITY_EPOCH_ID,
            "authority_root_file_sha256": launcher.CONTROL_SOURCE_BLOBS[
                launcher.PUBLIC_ROOT_REF
            ]["file_sha256"],
            "authority_root_git_blob_sha256": launcher.CONTROL_SOURCE_BLOBS[
                launcher.PUBLIC_ROOT_REF
            ]["file_sha256"],
            "authority_root_git_blob_oid": launcher.CONTROL_SOURCE_BLOBS[
                launcher.PUBLIC_ROOT_REF
            ]["git_blob_oid"],
            "source_file_sha256": {
                ref: launcher.CONTROL_SOURCE_BLOBS[ref]["file_sha256"]
                for ref in launcher.RUNTIME_SOURCE_REFS
            },
            "control_ci": launcher.CONTROL_CI,
            "readback_started": False,
            "cloud_read_count": 0,
            "cloud_write_count": 0,
            "database_connection_count": 0,
            "journal_write_count": 0,
        }
        authority = types.SimpleNamespace()
        authority._validate_root = mock.Mock(return_value=({}, {}))

        def validate(*_args: object, **_kwargs: object) -> dict[str, object]:
            self.assertIs(authority._verify_signature, launcher._verify_signature_fd)
            return expected_summary

        authority.validate_runtime_activation_receipt = mock.Mock(side_effect=validate)
        fake_parent = types.SimpleNamespace(lstat=mock.Mock(return_value=row))
        fake_path = types.SimpleNamespace(
            lstat=mock.Mock(return_value=row),
            parent=fake_parent,
        )
        with mock.patch.object(launcher.os, "fsync"), mock.patch.object(
            launcher.os, "fstat", return_value=row
        ), mock.patch.object(launcher.os, "lseek"), mock.patch.object(
            launcher.os, "read", side_effect=[receipt, b""]
        ), mock.patch.object(launcher, "PUBLIC_CAPTURE_PATH", fake_path), mock.patch.object(
            launcher, "_load_exact_authority", return_value=authority
        ):
            raw, payload = launcher._read_and_validate_capture(
                91,
                parent_descriptor=90,
                parent_identity=launcher._stable(row),
                authority_raw=b"authority",
                root_raw=b"root",
            )
        self.assertEqual(raw, receipt)
        self.assertEqual(payload, expected_payload)
        authority.validate_runtime_activation_receipt.assert_called_once()

    def test_real_executed_receipt_and_real_authority_return_contract(self) -> None:
        launcher = self.launcher
        production_root = launcher.REPOSITORY_ROOT
        production_verifier = launcher._verify_signature_fd
        verified_inputs: list[tuple[bytes, bytes, bytes]] = []

        def verify_and_record(
            payload: bytes,
            signature: bytes,
            public_key_pem: bytes,
        ) -> bool:
            verified_inputs.append((payload, signature, public_key_pem))
            return test_only_verify_signature(
                payload,
                signature,
                public_key_pem,
            )

        revision = launcher.EXECUTED_ATTEMPT_REVISION
        receipt = git_stdout("show", revision + ":" + EXECUTED_RECEIPT_REF)
        authority_raw = git_stdout(
            "show", launcher.CONTROL_REVISION + ":" + launcher.AUTHORITY_REF
        )
        root_raw = git_stdout(
            "show", launcher.CONTROL_REVISION + ":" + launcher.PUBLIC_ROOT_REF
        )
        with mock.patch.object(
            launcher, "REPOSITORY_ROOT", ROOT
        ), mock.patch.object(
            launcher,
            "_verify_signature_fd",
            verify_and_record,
        ):
            payload, summary = launcher._validate_receipt_bytes(
                receipt,
                authority_raw=authority_raw,
                root_raw=root_raw,
            )
            loaded_authority = sys.modules[
                "verify_item26_manual_cost_stop_authority_v2"
            ]
            self.assertEqual(
                Path(loaded_authority.__file__),
                ROOT / launcher.AUTHORITY_REF,
            )
        self.assertEqual(launcher.REPOSITORY_ROOT, production_root)
        self.assertIs(launcher._verify_signature_fd, production_verifier)
        self.assertEqual(
            production_root,
            Path("/Users/openclaw/Desktop/noteai"),
        )
        self.assertEqual(len(verified_inputs), 1)
        signed_payload, signature, public_key_pem = verified_inputs[0]
        self.assertTrue(
            test_only_verify_signature(
                signed_payload,
                signature,
                public_key_pem,
            )
        )
        tampered_signature = bytes([signature[0] ^ 1]) + signature[1:]
        self.assertFalse(
            test_only_verify_signature(
                signed_payload,
                tampered_signature,
                public_key_pem,
            )
        )
        self.assertFalse(
            test_only_verify_signature(
                signed_payload + b"\0",
                signature,
                public_key_pem,
            )
        )
        self.assertEqual(
            hashlib.sha256(receipt).hexdigest(),
            EXECUTED_ARTIFACTS[EXECUTED_RECEIPT_REF]["file_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(receipt[:-1]).hexdigest(),
            EXECUTED_RECEIPT_SEMANTIC_SHA256,
        )
        self.assertEqual(
            summary["activation_receipt_sha256"],
            EXECUTED_ARTIFACTS[EXECUTED_RECEIPT_REF]["file_sha256"],
        )
        self.assertEqual(
            summary["activation_receipt_semantic_sha256"],
            EXECUTED_RECEIPT_SEMANTIC_SHA256,
        )
        self.assertEqual(summary["activated_at_utc"], "2026-08-19T00:15:13Z")
        self.assertEqual(payload["activated_at_utc"], summary["activated_at_utc"])

    def test_visible_failure_record_is_fixed_and_non_retrying(self) -> None:
        launcher = self.launcher
        stream = io.BytesIO()
        stdout = types.SimpleNamespace(buffer=stream)
        with mock.patch.object(
            launcher,
            "_run_once",
            side_effect=launcher.LauncherError("fixed_reason"),
        ), mock.patch.object(launcher.sys, "stdout", stdout):
            self.assertEqual(
                launcher.main(
                    [
                        "--expected-launcher-sha256",
                        "a" * 64,
                        "--expected-root-program-sha256",
                        "b" * 64,
                    ]
                ),
                1,
            )
        value = json.loads(stream.getvalue().decode("ascii"))
        self.assertEqual(value["status"], "BLOCKED_RESIDUE_REVIEW_REQUIRED")
        self.assertEqual(value["reason"], "fixed_reason")
        self.assertIs(value["automatic_retry_allowed"], False)
        self.assertIs(value["cleanup_authorized"], False)


if __name__ == "__main__":
    unittest.main()
