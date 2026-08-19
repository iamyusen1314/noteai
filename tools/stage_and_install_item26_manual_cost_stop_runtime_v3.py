#!/usr/bin/env python3
"""Future visible-terminal bootstrap for the Item 26 runtime-v3 installer.

This source is intentionally inert until two future, operator-supplied Git
revisions exist with the frozen ``E -> S(exact6) -> F(exact4)`` topology.  A
valid future invocation performs every repository and system preflight before
creating an O_EXCL public result, then dispatches exactly one interactive
``sudo``.  The root program receives only a canonical public control bundle on
non-TTY stdin, independently reads the exact public Git blobs, preflights the
root-owned NoteAI inventory without reading private-key bytes, O_EXCL-stages
the installer and authority sources, and passes the tracked receipt to the
staged installer on anonymous non-TTY stdin.

Neither the outer stager nor its root program has a cleanup or retry path.
Failure residue must be reviewed under a separate authorization.  The staged
installer's own synchronous rollback semantics are unchanged and require the
future execution authorization that permits running that installer.

That future authorization must also cover the immutable authority verifier's
internal public scratch lifecycle.  During receipt verification it creates a
root-owned ``.item26-v2-signature-verify-*`` temporary directory under the
NoteAI root and three O_EXCL 0600 files named ``message``, ``signature`` and
``key``.  Those bytes are public signed material, not private keys.  The
existing verifier removes that scratch on synchronous exit; a process crash
can still leave residue, and this stager never cleans it.  This source-only
change creates or cleans none of that inventory and authorizes no execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Optional


BASE_REVISION = "a4e2a0d106e013c9b3ce730a278345c7552cdcd9"
CONTROL_REVISION = "68aa82ffbdd43e78e585d8956d13d3030ef6a640"
PRESERVATION_REVISION = "2cfb58b9f227a37cc86843bef7dc1014bc185391"
REPOSITORY_ROOT = Path("/Users/openclaw/Desktop/noteai")
BRANCH_REF = "refs/remotes/origin/codex/quality-stabilization-real-chain"
EXPECTED_USER_UID = 501
ROOT_UID = 0

STAGER_REF = "tools/stage_and_install_item26_manual_cost_stop_runtime_v3.py"
TEST_REF = "tests/test_stage_and_install_item26_manual_cost_stop_runtime_v3.py"
INSTALLER_REF = "tools/install_item26_manual_cost_stop_runtime_v3.py"
AUTHORITY_REF = "tools/verify_item26_manual_cost_stop_authority_v2.py"
RECEIPT_REF = (
    ".codex/item26-manual-cost-stop-activation-receipt-v3-"
    + CONTROL_REVISION
    + ".json"
)
LEDGER_REFS = frozenset(
    {
        ".codex/handoffs/current-task.md",
        ".codex/notes/architecture-summary.md",
        ".codex/notes/risk-register.md",
        "deploy/production/internal-deployment-readiness.json",
    }
)
SOURCE_REFS = frozenset({STAGER_REF, TEST_REF, *LEDGER_REFS})
ACCEPTANCE_REFS = LEDGER_REFS

CONTROL_SOURCE_REFS = (
    "tools/collect_item26_manual_cost_stop_raw_v2.py",
    "tools/extract_item26_manual_cost_stop_raw_v2.py",
    AUTHORITY_REF,
    "tools/build_item26_manual_cost_stop_authority_root_v2.py",
    "tools/build_item26_manual_cost_stop_activation_receipt_v3.py",
    "tools/verify_item26_manual_cost_stop_evidence_v2.py",
    "tools/build_item26_manual_cost_stop_evidence_v2.py",
    INSTALLER_REF,
    "tools/bootstrap_item26_manual_cost_stop_keys_v2.py",
    "deploy/production/plans/item26-manual-cost-stop-contract-v2.json",
    "deploy/production/authorities/"
    "item26-manual-cost-stop-authority-root-v2.json",
    ".github/workflows/ci.yml",
)

INSTALLER_BINDING = {
    "git_blob_oid": "ee6d1a6eda2a17d688bace1dccb63066a346933e",
    "file_sha256": (
        "8a851e0cc4f2945444613d63afff87fe498331b4762446e2c0deff2ce78814ef"
    ),
    "size": 34304,
}
AUTHORITY_BINDING = {
    "git_blob_oid": "91d5eaf9d63f3595c257ad31502407d1bb9a3cb0",
    "file_sha256": (
        "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d"
    ),
    "size": 125914,
}
RECEIPT_BINDING = {
    "git_blob_oid": "2a52e03416a096ccfca5ef9958d61a25290b10ac",
    "file_sha256": (
        "61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a"
    ),
    "size": 22068,
}
EXPECTED_AUTHORITY_ROOT_SHA256 = (
    "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85"
)

SYSTEM_PYTHON = Path("/usr/bin/python3")
SYSTEM_PYTHON_ENTRY = Path(
    "/Library/Developer/CommandLineTools/usr/bin/python3"
)
SYSTEM_PYTHON_EXECUTABLE = Path(
    "/Library/Developer/CommandLineTools/Library/Frameworks/"
    "Python3.framework/Versions/3.9/bin/python3.9"
)
SYSTEM_GIT = Path("/usr/bin/git")
SYSTEM_SUDO = Path("/usr/bin/sudo")
SYSTEM_STUB_SHA256 = (
    "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
)
SYSTEM_PYTHON_EXECUTABLE_SHA256 = (
    "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"
)
SYSTEM_PYTHON_ENTRY_TARGET = (
    "../../Library/Frameworks/Python3.framework/Versions/3.9/bin/python3"
)

BUNDLE_SCHEMA = "noteai.item26.runtime-v3-installer-root-staging-bundle.v1"
OUTER_SCHEMA = "noteai.item26.runtime-v3-visible-terminal-installer.v1"
MAX_BUNDLE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 1024 * 1024
SOURCE_ONLY_STATUS = {
    "schema": "noteai.item26.runtime-v3-installer-stager-source-only.v1",
    "status": "SOURCE_ONLY_NOT_EXECUTED",
    "authorizes_future_execution": False,
    "sudo_dispatch_count": 0,
    "root_write_count": 0,
    "custody_access_count": 0,
    "private_key_read_count": 0,
    "authority_public_scratch_directory_create_count": 0,
    "authority_public_scratch_file_create_count": 0,
    "authority_public_scratch_cleanup_count": 0,
    "installer_synchronous_rollback_count": 0,
}
FUTURE_EXECUTION_CONTRACT = {
    "schema": "noteai.item26.runtime-v3-installer-future-execution-contract.v1",
    "requires_new_cto_authorization": True,
    "authority_public_scratch_directory_pattern": (
        ".item26-v2-signature-verify-*"
    ),
    "authority_public_scratch_parent": str(
        Path("/Library/Application Support/NoteAI")
    ),
    "authority_public_scratch_directory_mode": "0700",
    "authority_public_scratch_file_mode": "0600",
    "authority_public_scratch_files": ["key", "message", "signature"],
    "authority_public_scratch_files_per_verification": 3,
    "authority_public_scratch_material_is_public": True,
    "authority_public_scratch_synchronous_cleanup": True,
    "authority_public_scratch_crash_residue_possible": True,
    "installer_synchronous_rollback_must_be_authorized": True,
    "stager_failure_cleanup_authorized": False,
    "automatic_retry_authorized": False,
}


class StagerError(ValueError):
    """A fixed non-sensitive stager failure code."""


class FixedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise StagerError("stager_arguments")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def _stable(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
    )


def _hex(value: str, length: int, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StagerError(code)
    return value


def _validate_tool(path: Path, *, mode: Optional[int] = None) -> os.stat_result:
    try:
        row = path.lstat()
    except OSError as exc:
        raise StagerError("stager_tool_identity") from exc
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != ROOT_UID
        or stat.S_IMODE(row.st_mode) & 0o022
        or (mode is not None and stat.S_IMODE(row.st_mode) != mode)
    ):
        raise StagerError("stager_tool_identity")
    return row


def _run_git(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    before = _validate_tool(SYSTEM_GIT, mode=0o755)
    try:
        result = subprocess.run(
            [
                str(SYSTEM_GIT),
                "-c",
                "safe.directory=" + str(REPOSITORY_ROOT),
                "--no-replace-objects",
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
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
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StagerError("stager_git") from exc
    if _stable(SYSTEM_GIT.lstat()) != _stable(before):
        raise StagerError("stager_git_changed")
    return result


def _git_stdout(arguments: list[str], code: str, *, allow_empty: bool = False) -> bytes:
    result = _run_git(arguments)
    if result.returncode != 0 or (not allow_empty and not result.stdout):
        raise StagerError(code)
    return result.stdout


def _git_text(arguments: list[str], code: str) -> str:
    try:
        return _git_stdout(arguments, code).decode("ascii").strip()
    except UnicodeError as exc:
        raise StagerError(code) from exc


def _changed_paths(parent: str, child: str, code: str) -> frozenset[str]:
    raw = _git_stdout(
        ["diff", "--name-only", "-z", parent, child, "--"],
        code,
        allow_empty=True,
    )
    try:
        rows = raw.decode("utf-8").split("\0")
    except UnicodeError as exc:
        raise StagerError(code) from exc
    if not rows or rows[-1] != "":
        raise StagerError(code)
    paths = rows[:-1]
    if any(not path or "\0" in path for path in paths):
        raise StagerError(code)
    return frozenset(paths)


def _require_direct_child(child: str, parent: str, code: str) -> None:
    row = _git_text(["rev-list", "--parents", "-n", "1", child], code).split()
    if row != [child, parent]:
        raise StagerError(code)


def _require_ancestor(ancestor: str, descendant: str, code: str) -> None:
    result = _run_git(["merge-base", "--is-ancestor", ancestor, descendant])
    if result.returncode != 0 or result.stdout:
        raise StagerError(code)


def _require_no_path_touch(
    start: str,
    end: str,
    refs: tuple[str, ...],
    code: str,
) -> None:
    raw = _git_stdout(
        ["rev-list", start + ".." + end, "--", *refs],
        code,
        allow_empty=True,
    )
    if raw != b"":
        raise StagerError(code)


def _git_blob(
    revision: str,
    ref: str,
    expected: dict[str, Any],
    code: str,
) -> bytes:
    oid = _git_text(["rev-parse", revision + ":" + ref], code)
    raw = _git_stdout(["cat-file", "blob", oid], code)
    if (
        oid != expected["git_blob_oid"]
        or len(raw) != expected["size"]
        or hashlib.sha256(raw).hexdigest() != expected["file_sha256"]
    ):
        raise StagerError(code)
    return raw


def _read_and_bind_stager(
    expected_launcher_sha256: str,
    expected_root_program_sha256: str,
    expected_source_revision: str,
    expected_acceptance_revision: str,
) -> None:
    path = Path(__file__).absolute()
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_BUNDLE_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65536, MAX_BUNDLE_BYTES + 1 - size),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except OSError as exc:
        raise StagerError("stager_source_identity") from exc
    raw = b"".join(chunks)
    source_oid = _git_text(
        ["rev-parse", expected_source_revision + ":" + STAGER_REF],
        "stager_source_binding",
    )
    acceptance_oid = _git_text(
        ["rev-parse", expected_acceptance_revision + ":" + STAGER_REF],
        "stager_source_binding",
    )
    source_raw = _git_stdout(
        ["cat-file", "blob", source_oid],
        "stager_source_binding",
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o644
        or before.st_uid != EXPECTED_USER_UID
        or before.st_nlink != 1
        or not 1 <= len(raw) <= MAX_BUNDLE_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
        or raw != source_raw
        or source_oid != acceptance_oid
        or hashlib.sha256(raw).hexdigest() != expected_launcher_sha256
        or hashlib.sha256(ROOT_PROGRAM.encode("ascii")).hexdigest()
        != expected_root_program_sha256
    ):
        raise StagerError("stager_source_binding")


def _validate_topology(
    expected_source_revision: str,
    expected_acceptance_revision: str,
) -> None:
    _require_direct_child(
        expected_source_revision,
        BASE_REVISION,
        "stager_source_topology",
    )
    _require_direct_child(
        expected_acceptance_revision,
        expected_source_revision,
        "stager_acceptance_topology",
    )
    _require_ancestor(
        BASE_REVISION,
        expected_source_revision,
        "stager_source_ancestry",
    )
    _require_ancestor(
        PRESERVATION_REVISION,
        expected_acceptance_revision,
        "stager_preservation_ancestry",
    )
    if (
        _changed_paths(
            BASE_REVISION,
            expected_source_revision,
            "stager_source_topology",
        )
        != SOURCE_REFS
    ):
        raise StagerError("stager_source_topology")
    if (
        _changed_paths(
            expected_source_revision,
            expected_acceptance_revision,
            "stager_acceptance_topology",
        )
        != ACCEPTANCE_REFS
    ):
        raise StagerError("stager_acceptance_topology")
    for arguments in (
        ["rev-parse", "HEAD"],
        ["rev-parse", "@{upstream}"],
        ["rev-parse", BRANCH_REF],
    ):
        if (
            _git_text(arguments, "stager_acceptance_revision")
            != expected_acceptance_revision
        ):
            raise StagerError("stager_acceptance_revision")
    status = _run_git(["status", "--porcelain=v1", "--untracked-files=no"])
    if status.returncode != 0 or status.stdout != b"":
        raise StagerError("stager_tracked_tree_dirty")
    _require_no_path_touch(
        CONTROL_REVISION,
        expected_acceptance_revision,
        CONTROL_SOURCE_REFS,
        "stager_control_source_touch",
    )
    _require_no_path_touch(
        PRESERVATION_REVISION,
        expected_acceptance_revision,
        (RECEIPT_REF,),
        "stager_receipt_touch",
    )


def _validate_system_boundary() -> None:
    if (
        os.getuid() != EXPECTED_USER_UID
        or os.geteuid() != EXPECTED_USER_UID
        or Path.cwd() != REPOSITORY_ROOT
        or Path.cwd().resolve(strict=True) != REPOSITORY_ROOT
        or Path(__file__).absolute() != REPOSITORY_ROOT / STAGER_REF
        or sys.flags.isolated != 1
        or sys.flags.ignore_environment != 1
        or sys.flags.no_site != 1
        or sys.flags.dont_write_bytecode != 1
        or Path(sys.executable).absolute() != SYSTEM_PYTHON_ENTRY
    ):
        raise StagerError("stager_execution_boundary")
    try:
        tty_names = tuple(os.ttyname(descriptor) for descriptor in (0, 1, 2))
    except OSError as exc:
        raise StagerError("stager_tty_012") from exc
    if (
        any(not os.isatty(descriptor) for descriptor in (0, 1, 2))
        or len(set(tty_names)) != 1
    ):
        raise StagerError("stager_tty_012")
    for path, expected in (
        (SYSTEM_PYTHON, SYSTEM_STUB_SHA256),
        (SYSTEM_GIT, SYSTEM_STUB_SHA256),
        (SYSTEM_PYTHON_EXECUTABLE, SYSTEM_PYTHON_EXECUTABLE_SHA256),
    ):
        before = _validate_tool(path, mode=0o755)
        raw = path.read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != expected
            or _stable(path.lstat()) != _stable(before)
        ):
            raise StagerError("stager_tool_binding")
    _validate_tool(SYSTEM_SUDO, mode=0o4511)
    try:
        entry_before = SYSTEM_PYTHON_ENTRY.lstat()
        target = os.readlink(SYSTEM_PYTHON_ENTRY)
        entry_after = SYSTEM_PYTHON_ENTRY.lstat()
    except OSError as exc:
        raise StagerError("stager_python_entry") from exc
    if (
        not stat.S_ISLNK(entry_before.st_mode)
        or entry_before.st_uid != ROOT_UID
        or target != SYSTEM_PYTHON_ENTRY_TARGET
        or _stable(entry_before) != _stable(entry_after)
        or SYSTEM_PYTHON_ENTRY.resolve(strict=True) != SYSTEM_PYTHON_EXECUTABLE
    ):
        raise StagerError("stager_python_entry")


def _validate_outer_boundary(
    expected_source_revision: str,
    expected_acceptance_revision: str,
    expected_launcher_sha256: str,
    expected_root_program_sha256: str,
) -> None:
    _validate_system_boundary()
    _validate_topology(
        expected_source_revision,
        expected_acceptance_revision,
    )
    _read_and_bind_stager(
        expected_launcher_sha256,
        expected_root_program_sha256,
        expected_source_revision,
        expected_acceptance_revision,
    )


def _build_bundle(
    expected_source_revision: str,
    expected_acceptance_revision: str,
    expected_launcher_sha256: str,
    expected_root_program_sha256: str,
) -> bytes:
    _git_blob(
        CONTROL_REVISION,
        INSTALLER_REF,
        INSTALLER_BINDING,
        "stager_installer_binding",
    )
    _git_blob(
        CONTROL_REVISION,
        AUTHORITY_REF,
        AUTHORITY_BINDING,
        "stager_authority_binding",
    )
    _git_blob(
        PRESERVATION_REVISION,
        RECEIPT_REF,
        RECEIPT_BINDING,
        "stager_receipt_binding",
    )
    bundle = canonical_bytes(
        {
            "schema": BUNDLE_SCHEMA,
            "base_revision": BASE_REVISION,
            "control_revision": CONTROL_REVISION,
            "preservation_revision": PRESERVATION_REVISION,
            "source_revision": expected_source_revision,
            "acceptance_revision": expected_acceptance_revision,
            "repository_root": str(REPOSITORY_ROOT),
            "stager_ref": STAGER_REF,
            "launcher_sha256": expected_launcher_sha256,
            "root_program_sha256": expected_root_program_sha256,
            "source_only_status": SOURCE_ONLY_STATUS,
            "future_execution_contract": FUTURE_EXECUTION_CONTRACT,
            "installer": INSTALLER_BINDING,
            "authority": AUTHORITY_BINDING,
            "receipt": {"ref": RECEIPT_REF, **RECEIPT_BINDING},
        }
    )
    if not 1 <= len(bundle) <= MAX_BUNDLE_BYTES:
        raise StagerError("stager_bundle_size")
    return bundle


ROOT_PROGRAM = r'''
import fcntl, hashlib, json, os, pathlib, stat, subprocess, sys

BASE="a4e2a0d106e013c9b3ce730a278345c7552cdcd9"
CONTROL="68aa82ffbdd43e78e585d8956d13d3030ef6a640"
PRESERVE="2cfb58b9f227a37cc86843bef7dc1014bc185391"
REPO=pathlib.Path("/Users/openclaw/Desktop/noteai")
BRANCH="refs/remotes/origin/codex/quality-stabilization-real-chain"
STAGER_REF="tools/stage_and_install_item26_manual_cost_stop_runtime_v3.py"
TEST_REF="tests/test_stage_and_install_item26_manual_cost_stop_runtime_v3.py"
INSTALLER_REF="tools/install_item26_manual_cost_stop_runtime_v3.py"
AUTHORITY_REF="tools/verify_item26_manual_cost_stop_authority_v2.py"
RECEIPT_REF=".codex/item26-manual-cost-stop-activation-receipt-v3-68aa82ffbdd43e78e585d8956d13d3030ef6a640.json"
LEDGERS={".codex/handoffs/current-task.md",".codex/notes/architecture-summary.md",".codex/notes/risk-register.md","deploy/production/internal-deployment-readiness.json"}
SOURCE_PATHS=LEDGERS|{STAGER_REF,TEST_REF}
CONTROL_REFS=("tools/collect_item26_manual_cost_stop_raw_v2.py","tools/extract_item26_manual_cost_stop_raw_v2.py",AUTHORITY_REF,"tools/build_item26_manual_cost_stop_authority_root_v2.py","tools/build_item26_manual_cost_stop_activation_receipt_v3.py","tools/verify_item26_manual_cost_stop_evidence_v2.py","tools/build_item26_manual_cost_stop_evidence_v2.py",INSTALLER_REF,"tools/bootstrap_item26_manual_cost_stop_keys_v2.py","deploy/production/plans/item26-manual-cost-stop-contract-v2.json","deploy/production/authorities/item26-manual-cost-stop-authority-root-v2.json",".github/workflows/ci.yml")
INSTALLER=("ee6d1a6eda2a17d688bace1dccb63066a346933e","8a851e0cc4f2945444613d63afff87fe498331b4762446e2c0deff2ce78814ef",34304)
AUTHORITY=("91d5eaf9d63f3595c257ad31502407d1bb9a3cb0","19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d",125914)
RECEIPT=("2a52e03416a096ccfca5ef9958d61a25290b10ac","61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a",22068)
SCHEMA="noteai.item26.runtime-v3-installer-root-staging-bundle.v1"
SOURCE_ONLY={"schema":"noteai.item26.runtime-v3-installer-stager-source-only.v1","status":"SOURCE_ONLY_NOT_EXECUTED","authorizes_future_execution":False,"sudo_dispatch_count":0,"root_write_count":0,"custody_access_count":0,"private_key_read_count":0,"authority_public_scratch_directory_create_count":0,"authority_public_scratch_file_create_count":0,"authority_public_scratch_cleanup_count":0,"installer_synchronous_rollback_count":0}
FUTURE_CONTRACT={"schema":"noteai.item26.runtime-v3-installer-future-execution-contract.v1","requires_new_cto_authorization":True,"authority_public_scratch_directory_pattern":".item26-v2-signature-verify-*","authority_public_scratch_parent":"/Library/Application Support/NoteAI","authority_public_scratch_directory_mode":"0700","authority_public_scratch_file_mode":"0600","authority_public_scratch_files":["key","message","signature"],"authority_public_scratch_files_per_verification":3,"authority_public_scratch_material_is_public":True,"authority_public_scratch_synchronous_cleanup":True,"authority_public_scratch_crash_residue_possible":True,"installer_synchronous_rollback_must_be_authorized":True,"stager_failure_cleanup_authorized":False,"automatic_retry_authorized":False}
PYTHON=pathlib.Path("/usr/bin/python3")
PYTHON_ENTRY=pathlib.Path("/Library/Developer/CommandLineTools/usr/bin/python3")
PYTHON_BIN=pathlib.Path("/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9")
GIT=pathlib.Path("/usr/bin/git")
STUB_SHA="179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
PYTHON_SHA="4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"
PARENT=pathlib.Path("/Library/Application Support/NoteAI")
BOOTSTRAP=PARENT/"item26-manual-cost-stop-v2-bootstrap"
CUSTODY=PARENT/"item26-manual-cost-stop-v2-custody"
SIGNER=PARENT/"item26-manual-cost-stop-v2-signer"
STAGING=PARENT/"item26-manual-cost-stop-v2-installer"
AUTHORITY_DIR=PARENT/"item26-manual-cost-stop-v2"
RUNTIME_DIR=PARENT/"item26-manual-cost-stop-v2-tools"
JOURNAL_DIR=PARENT/"item26-manual-cost-stop-v2-journal"
BOOTSTRAP_FILE="bootstrap_item26_manual_cost_stop_keys_v2.py"
BOOTSTRAP_BINDING=("2e35d16c2a2f55ddfa1436190ed8869449dd05fb8ae5fb45878ab9c50c0cd9ff",26443)
SIGNER_BINDINGS={"build_item26_manual_cost_stop_activation_receipt_v3.py":("d6ab77d5cd31c03bb5b1949fa9b60e6d2a904e872b31b5c95f63ad41f8b96a08",34510),"verify_item26_manual_cost_stop_authority_v2.py":("19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d",125914)}
CUSTODY_FILES={"provider-private-key.pem","confirmation-private-key.pem","local-ci-observation-private-key.pem"}
MAX=1024*1024

class E(Exception): pass
def fail(code): raise E(code)
def canon(value): return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")+b"\n"
def stable(row): return (row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
def tool(path,digest,mode=0o755):
    try:
        a=path.lstat(); fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0)); b=os.fstat(fd); chunks=[]; total=0
        while total<=MAX:
            chunk=os.read(fd,min(65536,MAX+1-total))
            if not chunk: break
            chunks.append(chunk); total+=len(chunk)
        c=os.fstat(fd); os.close(fd); d=path.lstat(); raw=b"".join(chunks)
    except OSError: fail("root_tool_identity")
    if not stat.S_ISREG(a.st_mode) or stat.S_ISLNK(a.st_mode) or a.st_uid!=0 or stat.S_IMODE(a.st_mode)!=mode or stable(a)!=stable(b) or stable(b)!=stable(c) or stable(c)!=stable(d) or hashlib.sha256(raw).hexdigest()!=digest: fail("root_tool_binding")
def repo_identity():
    paths=[]; current=pathlib.Path("/"); paths.append(current)
    for part in REPO.parts[1:]: current=current/part; paths.append(current)
    paths.append(REPO/".git")
    try: rows=[path.lstat() for path in paths]
    except OSError: fail("root_repository_identity")
    for index,row in enumerate(rows):
        if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or stat.S_IMODE(row.st_mode)&0o022 or (index>=2 and row.st_uid not in (0,501)): fail("root_repository_identity")
    return tuple((str(path),stable(row)) for path,row in zip(paths,rows))
def git(args,empty=False):
    before=GIT.lstat(); identity=repo_identity()
    try: result=subprocess.run([str(GIT),"-c","safe.directory="+str(REPO),"--no-replace-objects",*args],cwd=REPO,env={"PATH":"/usr/bin:/bin","LC_ALL":"C","LANG":"C","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null","GIT_NO_REPLACE_OBJECTS":"1","GIT_OPTIONAL_LOCKS":"0"},stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20,check=False)
    except (OSError,subprocess.SubprocessError): fail("root_git")
    if result.returncode!=0 or stable(GIT.lstat())!=stable(before) or repo_identity()!=identity or (not empty and not result.stdout): fail("root_git")
    return result.stdout
def text(args):
    try: return git(args).decode("ascii").strip()
    except UnicodeError: fail("root_git_output")
def parse(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: fail("root_bundle_canonical")
            result[key]=value
        return result
    try: value=json.loads(raw.decode("ascii"),object_pairs_hook=pairs,parse_constant=lambda _value: fail("root_bundle_canonical"))
    except E: raise
    except Exception: fail("root_bundle_canonical")
    if type(value) is not dict or canon(value)!=raw: fail("root_bundle_canonical")
    return value
def read_stdin():
    chunks=[]; total=0
    while total<=MAX:
        chunk=os.read(0,min(65536,MAX+1-total))
        if not chunk: break
        chunks.append(chunk); total+=len(chunk)
    raw=b"".join(chunks)
    if not 1<=len(raw)<=MAX: fail("root_bundle_size")
    return raw
def changed(parent,child):
    try:
        rows=git(["diff","--name-only","-z",parent,child,"--"],empty=True).decode("utf-8").split("\0")
    except UnicodeError: fail("root_topology")
    if not rows or rows[-1]!="" or any(not path for path in rows[:-1]): fail("root_topology")
    return set(rows[:-1])
def direct(child,parent):
    if text(["rev-list","--parents","-n","1",child]).split()!=[child,parent]: fail("root_topology")
def no_touch(start,end,refs):
    if git(["rev-list",start+".."+end,"--",*refs],empty=True)!=b"": fail("root_source_touch")
def blob(revision,ref,binding):
    oid=text(["rev-parse",revision+":"+ref]); raw=git(["cat-file","blob",oid])
    if oid!=binding[0] or len(raw)!=binding[2] or hashlib.sha256(raw).hexdigest()!=binding[1]: fail("root_blob_binding")
    return raw
def directory(row,code):
    if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or stat.S_IMODE(row.st_mode)!=0o700 or row.st_uid!=0 or row.st_nlink<2: fail(code)
def public_file(directory_fd,name,binding):
    try:
        a=os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
        if not stat.S_ISREG(a.st_mode) or stat.S_ISLNK(a.st_mode) or stat.S_IMODE(a.st_mode)!=0o600 or a.st_uid!=0 or a.st_nlink!=1 or a.st_size!=binding[1]: fail("root_public_file_identity")
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=directory_fd); b=os.fstat(fd); chunks=[]; total=0
        while total<=binding[1]:
            chunk=os.read(fd,min(65536,binding[1]+1-total))
            if not chunk: break
            chunks.append(chunk); total+=len(chunk)
        c=os.fstat(fd); os.close(fd); d=os.stat(name,dir_fd=directory_fd,follow_symlinks=False); raw=b"".join(chunks)
    except E: raise
    except OSError: fail("root_public_file_identity")
    if stable(a)!=stable(b) or stable(b)!=stable(c) or stable(c)!=stable(d) or len(raw)!=binding[1] or hashlib.sha256(raw).hexdigest()!=binding[0]: fail("root_public_file_binding")
def absent(path):
    try: path.lstat()
    except FileNotFoundError: return
    except OSError: fail("root_target_absence")
    fail("root_target_absence")
def preflight():
    try:
        before=PARENT.lstat(); directory(before,"root_noteai_identity")
        parent_fd=os.open(PARENT,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0)); opened=os.fstat(parent_fd); directory(opened,"root_noteai_identity")
        if stable(before)!=stable(opened) or set(os.listdir(parent_fd))!={BOOTSTRAP.name,CUSTODY.name,SIGNER.name}: fail("root_noteai_inventory")
        bootstrap_fd=os.open(BOOTSTRAP.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=parent_fd); directory(os.fstat(bootstrap_fd),"root_bootstrap_identity")
        if set(os.listdir(bootstrap_fd))!={BOOTSTRAP_FILE}: fail("root_bootstrap_inventory")
        public_file(bootstrap_fd,BOOTSTRAP_FILE,BOOTSTRAP_BINDING); os.close(bootstrap_fd)
        signer_fd=os.open(SIGNER.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=parent_fd); directory(os.fstat(signer_fd),"root_signer_identity")
        if set(os.listdir(signer_fd))!=set(SIGNER_BINDINGS): fail("root_signer_inventory")
        for name,binding in SIGNER_BINDINGS.items(): public_file(signer_fd,name,binding)
        os.close(signer_fd)
        custody_fd=os.open(CUSTODY.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=parent_fd); directory(os.fstat(custody_fd),"root_custody_identity")
        if set(os.listdir(custody_fd))!=CUSTODY_FILES: fail("root_custody_inventory")
        before_keys={}
        for name in CUSTODY_FILES:
            row=os.stat(name,dir_fd=custody_fd,follow_symlinks=False); before_keys[name]=stable(row)
            if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or stat.S_IMODE(row.st_mode)!=0o600 or row.st_uid!=0 or row.st_nlink!=1 or not 1<=row.st_size<=MAX: fail("root_custody_file_identity")
        after_keys={name:stable(os.stat(name,dir_fd=custody_fd,follow_symlinks=False)) for name in CUSTODY_FILES}
        if before_keys!=after_keys or set(os.listdir(custody_fd))!=CUSTODY_FILES: fail("root_custody_changed")
        os.close(custody_fd)
        for target in (STAGING,AUTHORITY_DIR,RUNTIME_DIR,JOURNAL_DIR): absent(target)
        after_fd=os.fstat(parent_fd); after=PARENT.lstat()
        if stable(opened)!=stable(after_fd) or stable(after_fd)!=stable(after) or set(os.listdir(parent_fd))!={BOOTSTRAP.name,CUSTODY.name,SIGNER.name}: fail("root_noteai_changed")
    except E: raise
    except OSError: fail("root_noteai_identity")
    return parent_fd
def write_at(directory_fd,name,raw):
    try:
        fd=os.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),0o600,dir_fd=directory_fd)
        try:
            os.fchmod(fd,0o600); offset=0
            while offset<len(raw):
                wrote=os.write(fd,raw[offset:])
                if wrote<=0: fail("root_stage_write")
                offset+=wrote
            os.fsync(fd); os.lseek(fd,0,os.SEEK_SET); chunks=[]
            while True:
                chunk=os.read(fd,65536)
                if not chunk: break
                chunks.append(chunk)
            row=os.fstat(fd)
        finally: os.close(fd)
    except E: raise
    except OSError: fail("root_stage_write")
    if not stat.S_ISREG(row.st_mode) or stat.S_IMODE(row.st_mode)!=0o600 or row.st_uid!=0 or row.st_nlink!=1 or b"".join(chunks)!=raw: fail("root_stage_identity")
def main():
    if os.getuid()!=0 or os.geteuid()!=0 or pathlib.Path.cwd()!=pathlib.Path("/") or sys.flags.isolated!=1 or sys.flags.ignore_environment!=1 or sys.flags.no_site!=1 or sys.flags.dont_write_bytecode!=1 or pathlib.Path(sys.executable).absolute()!=PYTHON_ENTRY: fail("root_execution_boundary")
    if os.isatty(0) or not os.isatty(2): fail("root_stdio_boundary")
    out=os.fstat(1); flags=fcntl.fcntl(1,fcntl.F_GETFL)
    if not stat.S_ISREG(out.st_mode) or stat.S_IMODE(out.st_mode)!=0o600 or out.st_uid!=501 or out.st_nlink!=1 or out.st_size!=0 or os.lseek(1,0,os.SEEK_CUR)!=0 or flags&os.O_APPEND or flags&os.O_ACCMODE not in (os.O_WRONLY,os.O_RDWR): fail("root_capture_boundary")
    tool(PYTHON,STUB_SHA); tool(GIT,STUB_SHA); tool(PYTHON_BIN,PYTHON_SHA)
    try: entry=PYTHON_ENTRY.lstat(); target=os.readlink(PYTHON_ENTRY)
    except OSError: fail("root_python_entry")
    if not stat.S_ISLNK(entry.st_mode) or entry.st_uid!=0 or target!="../../Library/Frameworks/Python3.framework/Versions/3.9/bin/python3" or PYTHON_ENTRY.resolve(strict=True)!=PYTHON_BIN: fail("root_python_entry")
    if REPO.resolve(strict=True)!=REPO: fail("root_repository_identity")
    identity=repo_identity(); bundle=parse(read_stdin())
    expected_keys={"schema","base_revision","control_revision","preservation_revision","source_revision","acceptance_revision","repository_root","stager_ref","launcher_sha256","root_program_sha256","source_only_status","future_execution_contract","installer","authority","receipt"}
    if set(bundle)!=expected_keys or bundle.get("schema")!=SCHEMA or bundle.get("base_revision")!=BASE or bundle.get("control_revision")!=CONTROL or bundle.get("preservation_revision")!=PRESERVE or bundle.get("repository_root")!=str(REPO) or bundle.get("stager_ref")!=STAGER_REF: fail("root_bundle_binding")
    source=bundle.get("source_revision"); acceptance=bundle.get("acceptance_revision")
    if type(source) is not str or len(source)!=40 or type(acceptance) is not str or len(acceptance)!=40 or any(c not in "0123456789abcdef" for c in source+acceptance): fail("root_bundle_binding")
    if bundle.get("installer")!={"git_blob_oid":INSTALLER[0],"file_sha256":INSTALLER[1],"size":INSTALLER[2]} or bundle.get("authority")!={"git_blob_oid":AUTHORITY[0],"file_sha256":AUTHORITY[1],"size":AUTHORITY[2]} or bundle.get("receipt")!={"ref":RECEIPT_REF,"git_blob_oid":RECEIPT[0],"file_sha256":RECEIPT[1],"size":RECEIPT[2]}: fail("root_bundle_binding")
    if bundle.get("source_only_status")!=SOURCE_ONLY or bundle.get("future_execution_contract")!=FUTURE_CONTRACT: fail("root_bundle_binding")
    for key in ("launcher_sha256","root_program_sha256"):
        value=bundle.get(key)
        if type(value) is not str or len(value)!=64 or any(c not in "0123456789abcdef" for c in value): fail("root_bundle_binding")
    direct(source,BASE); direct(acceptance,source)
    if changed(BASE,source)!=SOURCE_PATHS or changed(source,acceptance)!=LEDGERS: fail("root_topology")
    for ref in ("HEAD","@{upstream}",BRANCH):
        if text(["rev-parse",ref])!=acceptance: fail("root_acceptance_revision")
    if git(["status","--porcelain=v1","--untracked-files=no"],empty=True)!=b"": fail("root_tracked_tree_dirty")
    no_touch(CONTROL,acceptance,CONTROL_REFS); no_touch(PRESERVE,acceptance,(RECEIPT_REF,))
    source_oid=text(["rev-parse",source+":"+STAGER_REF]); acceptance_oid=text(["rev-parse",acceptance+":"+STAGER_REF]); source_raw=git(["cat-file","blob",source_oid])
    if source_oid!=acceptance_oid or hashlib.sha256(source_raw).hexdigest()!=bundle["launcher_sha256"]: fail("root_stager_binding")
    installer=blob(CONTROL,INSTALLER_REF,INSTALLER); authority=blob(CONTROL,AUTHORITY_REF,AUTHORITY); receipt=blob(PRESERVE,RECEIPT_REF,RECEIPT)
    if text(["rev-parse",acceptance+":"+RECEIPT_REF])!=RECEIPT[0] or repo_identity()!=identity: fail("root_receipt_binding")
    parent_fd=preflight()
    try:
        os.mkdir(STAGING.name,0o700,dir_fd=parent_fd)
        staging_fd=os.open(STAGING.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=parent_fd); os.fchmod(staging_fd,0o700); directory(os.fstat(staging_fd),"root_staging_identity")
        write_at(staging_fd,pathlib.Path(INSTALLER_REF).name,installer); write_at(staging_fd,pathlib.Path(AUTHORITY_REF).name,authority); os.fsync(staging_fd); os.fsync(parent_fd)
        if set(os.listdir(staging_fd))!={pathlib.Path(INSTALLER_REF).name,pathlib.Path(AUTHORITY_REF).name} or set(os.listdir(parent_fd))!={BOOTSTRAP.name,CUSTODY.name,SIGNER.name,STAGING.name}: fail("root_staging_inventory")
        os.close(staging_fd); os.close(parent_fd)
    except E: raise
    except OSError: fail("root_stage_operation")
    try: result=subprocess.run([str(PYTHON),"-E","-S","-B",str(STAGING/pathlib.Path(INSTALLER_REF).name),"--control-revision",CONTROL,"--repository-root",str(REPO)],input=receipt,stdout=None,stderr=subprocess.DEVNULL,cwd="/",env={"PATH":"/usr/bin:/bin","LC_ALL":"C","LANG":"C","PYTHONDONTWRITEBYTECODE":"1"},close_fds=True,timeout=180,check=False)
    except (OSError,subprocess.SubprocessError): fail("root_installer_dispatch")
    if result.returncode!=0: fail("root_installer_failed")
    os.fsync(1); return 0
try:
    status=main()
except E as exc:
    sys.stderr.write('{"schema":"noteai.item26.runtime-v3-root-installer-stager.v1","status":"BLOCKED_RESIDUE_REVIEW_REQUIRED","reason":'+json.dumps(str(exc),separators=(",",":"))+'}\n'); raise SystemExit(1)
except BaseException:
    sys.stderr.write('{"schema":"noteai.item26.runtime-v3-root-installer-stager.v1","status":"BLOCKED_RESIDUE_REVIEW_REQUIRED","reason":"root_unclassified_failure"}\n'); raise SystemExit(1)
raise SystemExit(status)
'''


def _capture_path(acceptance_revision: str) -> Path:
    _hex(acceptance_revision, 40, "stager_arguments")
    return REPOSITORY_ROOT / (
        ".codex/item26-manual-cost-stop-runtime-v3-install-result-"
        + acceptance_revision
        + ".json"
    )


def _open_capture(acceptance_revision: str) -> tuple[int, int, tuple[int, ...]]:
    path = _capture_path(acceptance_revision)
    parent = path.parent
    try:
        before = parent.lstat()
        if (
            parent.resolve(strict=True) != parent
            or not stat.S_ISDIR(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != EXPECTED_USER_UID
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise StagerError("stager_capture_parent")
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(parent_fd)
        if _stable(before) != _stable(opened):
            raise StagerError("stager_capture_parent")
        capture_fd = os.open(
            path.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        os.fchmod(capture_fd, 0o600)
        os.fsync(parent_fd)
        row = os.fstat(capture_fd)
        parent_after_fd = os.fstat(parent_fd)
        parent_after_path = parent.lstat()
    except BaseException as exc:
        if "capture_fd" in locals():
            os.close(capture_fd)
        if "parent_fd" in locals():
            os.close(parent_fd)
        if isinstance(exc, StagerError):
            raise
        if isinstance(exc, OSError):
            raise StagerError("stager_capture_create") from exc
        raise
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != EXPECTED_USER_UID
        or row.st_nlink != 1
        or row.st_size != 0
        or not stat.S_ISDIR(parent_after_fd.st_mode)
        or stat.S_ISLNK(parent_after_path.st_mode)
        or parent_after_fd.st_uid != EXPECTED_USER_UID
        or stat.S_IMODE(parent_after_fd.st_mode) & 0o022
        or _stable(parent_after_fd) != _stable(parent_after_path)
    ):
        os.close(capture_fd)
        os.close(parent_fd)
        raise StagerError("stager_capture_identity")
    # O_EXCL directory-entry creation changes the parent mtime/ctime.  Freeze
    # the durable post-create identity, not the pre-create identity above.
    return capture_fd, parent_fd, _stable(parent_after_fd)


def _parse_canonical(raw: bytes, code: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise StagerError(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                StagerError(code)
            ),
        )
    except (UnicodeError, json.JSONDecodeError, StagerError) as exc:
        raise StagerError(code) from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise StagerError(code)
    return value


def _read_validate_capture(
    capture_fd: int,
    parent_fd: int,
    parent_identity: tuple[int, ...],
    acceptance_revision: str,
) -> tuple[bytes, dict[str, Any]]:
    path = _capture_path(acceptance_revision)
    try:
        os.fsync(capture_fd)
        row = os.fstat(capture_fd)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_IMODE(row.st_mode) != 0o600
            or row.st_uid != EXPECTED_USER_UID
            or row.st_nlink != 1
            or not 1 <= row.st_size <= MAX_RESULT_BYTES
        ):
            raise StagerError("stager_result_identity")
        os.lseek(capture_fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_RESULT_BYTES:
            chunk = os.read(
                capture_fd,
                min(65536, MAX_RESULT_BYTES + 1 - size),
            )
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        closed = os.fstat(capture_fd)
        parent_row = os.fstat(parent_fd)
        path_row = path.lstat()
    except OSError as exc:
        raise StagerError("stager_result_identity") from exc
    raw = b"".join(chunks)
    if (
        _stable(row) != _stable(closed)
        or _stable(closed) != _stable(path_row)
        or _stable(parent_row) != parent_identity
    ):
        raise StagerError("stager_result_changed")
    result = _parse_canonical(raw, "stager_result_canonical")
    expected_counts = {
        "status": "ROOT_V2_RUNTIME_V3_INSTALLED",
        "control_revision": CONTROL_REVISION,
        "authority_epoch_id": (
            "noteai.item26.manual-cost-stop-authority-generation.v2"
        ),
        "authority_file_count": 1,
        "runtime_file_count": 4,
        "journal_file_count": 0,
        "private_key_read_count": 0,
        "private_key_write_count": 0,
        "cloud_call_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
    }
    for key, value in expected_counts.items():
        if result.get(key) != value:
            raise StagerError("stager_result_binding")
    expected_keys = set(expected_counts) | {
        "authority_root_file_sha256",
        "authority_root_git_blob_sha256",
        "activation_receipt_sha256",
    }
    if set(result) != expected_keys:
        raise StagerError("stager_result_binding")
    if (
        result["authority_root_file_sha256"]
        != EXPECTED_AUTHORITY_ROOT_SHA256
        or result["authority_root_git_blob_sha256"]
        != EXPECTED_AUTHORITY_ROOT_SHA256
        or result["activation_receipt_sha256"]
        != RECEIPT_BINDING["file_sha256"]
    ):
        raise StagerError("stager_result_binding")
    return raw, result


def _run_once(
    expected_source_revision: str,
    expected_acceptance_revision: str,
    expected_launcher_sha256: str,
    expected_root_program_sha256: str,
) -> dict[str, Any]:
    _validate_outer_boundary(
        expected_source_revision,
        expected_acceptance_revision,
        expected_launcher_sha256,
        expected_root_program_sha256,
    )
    bundle = _build_bundle(
        expected_source_revision,
        expected_acceptance_revision,
        expected_launcher_sha256,
        expected_root_program_sha256,
    )
    capture_fd, parent_fd, parent_identity = _open_capture(
        expected_acceptance_revision
    )
    sudo_before = _validate_tool(SYSTEM_SUDO, mode=0o4511)
    command = [
        str(SYSTEM_SUDO),
        "-k",
        "--",
        str(SYSTEM_PYTHON),
        "-I",
        "-E",
        "-S",
        "-B",
        "-c",
        ROOT_PROGRAM,
    ]
    try:
        sys.stderr.write(
            "将出现 macOS 管理员密码提示；密码只输入到当前终端。\n"
        )
        sys.stderr.flush()
        result = subprocess.run(
            command,
            input=bundle,
            stdout=capture_fd,
            stderr=None,
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            close_fds=True,
            check=False,
        )
        if result.returncode != 0:
            raise StagerError("stager_single_sudo_failed")
        if _stable(SYSTEM_SUDO.lstat()) != _stable(sudo_before):
            raise StagerError("stager_sudo_changed")
        result_raw, installed = _read_validate_capture(
            capture_fd,
            parent_fd,
            parent_identity,
            expected_acceptance_revision,
        )
    finally:
        os.close(capture_fd)
        os.close(parent_fd)
    return {
        "schema": OUTER_SCHEMA,
        "status": "ROOT_V2_RUNTIME_V3_STAGED_INSTALLED_AND_VERIFIED",
        "source_revision": expected_source_revision,
        "acceptance_revision": expected_acceptance_revision,
        "result_path": str(_capture_path(expected_acceptance_revision)),
        "result_sha256": hashlib.sha256(result_raw).hexdigest(),
        "activation_receipt_sha256": installed["activation_receipt_sha256"],
        "sudo_dispatch_count": 1,
        "automatic_retry_count": 0,
        "stager_cleanup_count": 0,
        "private_key_read_count": 0,
        "private_key_output_count": 0,
        "cloud_call_count": 0,
        "database_connection_count": 0,
        "readiness_credit_added": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    try:
        parser = FixedArgumentParser(add_help=False, allow_abbrev=False)
        parser.add_argument("--expected-source-revision", required=True)
        parser.add_argument("--expected-acceptance-revision", required=True)
        parser.add_argument("--expected-launcher-sha256", required=True)
        parser.add_argument("--expected-root-program-sha256", required=True)
        arguments = parser.parse_args(argv)
        source_revision = _hex(
            arguments.expected_source_revision,
            40,
            "stager_arguments",
        )
        acceptance_revision = _hex(
            arguments.expected_acceptance_revision,
            40,
            "stager_arguments",
        )
        launcher_sha256 = _hex(
            arguments.expected_launcher_sha256,
            64,
            "stager_arguments",
        )
        root_program_sha256 = _hex(
            arguments.expected_root_program_sha256,
            64,
            "stager_arguments",
        )
        result = _run_once(
            source_revision,
            acceptance_revision,
            launcher_sha256,
            root_program_sha256,
        )
    except StagerError as exc:
        result = {
            "schema": OUTER_SCHEMA,
            "status": "BLOCKED_RESIDUE_REVIEW_REQUIRED",
            "reason": str(exc),
            "automatic_retry_allowed": False,
            "cleanup_authorized": False,
        }
        sys.stdout.buffer.write(canonical_bytes(result))
        sys.stdout.buffer.flush()
        return 1
    except BaseException:
        result = {
            "schema": OUTER_SCHEMA,
            "status": "BLOCKED_RESIDUE_REVIEW_REQUIRED",
            "reason": "stager_unclassified_failure",
            "automatic_retry_allowed": False,
            "cleanup_authorized": False,
        }
        sys.stdout.buffer.write(canonical_bytes(result))
        sys.stdout.buffer.flush()
        return 1
    sys.stdout.buffer.write(canonical_bytes(result))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCEPTANCE_REFS",
    "BASE_REVISION",
    "CONTROL_REVISION",
    "PRESERVATION_REVISION",
    "ROOT_PROGRAM",
    "SOURCE_REFS",
    "SOURCE_ONLY_STATUS",
    "FUTURE_EXECUTION_CONTRACT",
    "StagerError",
    "canonical_bytes",
    "main",
]
