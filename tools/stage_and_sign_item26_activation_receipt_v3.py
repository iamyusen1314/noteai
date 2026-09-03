#!/usr/bin/env python3
"""Consumed historical correction for the Item 26 receipt-v3 launcher pattern.

The one authorized execution is frozen at ``EXECUTED_ATTEMPT_REVISION``.
``EXECUTION_CONSUMED`` blocks the dispatch path before Git, filesystem, bundle,
capture, or sudo work.  The remaining public implementation is retained only
to correct and test the historical pattern.  It is not executable for another attempt.
"""

from __future__ import annotations

import base64
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import types
from typing import Any, Optional


CONTROL_REVISION = "68aa82ffbdd43e78e585d8956d13d3030ef6a640"
EXECUTED_ATTEMPT_REVISION = "2cfb58b9f227a37cc86843bef7dc1014bc185391"
EXECUTION_CONSUMED = True
REPOSITORY_ROOT = Path("/Users/openclaw/Desktop/noteai")
BRANCH_REF = "refs/remotes/origin/codex/quality-stabilization-real-chain"
EXPECTED_USER_UID = 501
ROOT_UID = 0
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
SYSTEM_OPENSSL = Path("/usr/bin/openssl")
SYSTEM_STUB_SHA256 = (
    "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
)
SYSTEM_PYTHON_EXECUTABLE_SHA256 = (
    "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"
)
SYSTEM_OPENSSL_SHA256 = (
    "517827f877751b6d7abebe404a296fa8e82425c63694a73ab06db35e6d9a8362"
)
SYSTEM_PYTHON_ENTRY_TARGET = (
    "../../Library/Frameworks/Python3.framework/Versions/3.9/bin/python3"
)
SIGNER_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v2-signer"
)
PUBLIC_CAPTURE_PATH = REPOSITORY_ROOT / (
    ".codex/item26-manual-cost-stop-activation-receipt-v3-"
    + CONTROL_REVISION
    + ".json"
)
BUILDER_REF = "tools/build_item26_manual_cost_stop_activation_receipt_v3.py"
AUTHORITY_REF = "tools/verify_item26_manual_cost_stop_authority_v2.py"
PUBLIC_ROOT_REF = (
    "deploy/production/authorities/"
    "item26-manual-cost-stop-authority-root-v2.json"
)
SIGN_REQUEST_SCHEMA = (
    "noteai.item26.manual-cost-stop-activation-sign-request.v3"
)
BUNDLE_SCHEMA = "noteai.item26.activation-receipt-v3-root-staging-bundle.v1"
RECEIPT_SCHEMA = (
    "noteai.item26.manual-cost-stop-runtime-activation-envelope.v3"
)
RECEIPT_DOMAIN_TEXT = (
    "noteai-item26-manual-cost-stop-runtime-activation-receipt-v3"
)
AUTHORITY_EPOCH_ID = "noteai.item26.manual-cost-stop-authority-generation.v2"
RUNTIME_SOURCE_REFS = (
    "tools/collect_item26_manual_cost_stop_raw_v2.py",
    "tools/extract_item26_manual_cost_stop_raw_v2.py",
    AUTHORITY_REF,
)
MAX_BUNDLE_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 4 * 1024 * 1024


CONTROL_CI = {
    "push": {
        "run_id": 32147676628,
        "job_id": 95745356212,
        "event": "push",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": CONTROL_REVISION,
        "created_at_utc": "2026-08-18T14:19:58Z",
        "started_at_utc": "2026-08-18T14:20:01Z",
        "completed_at_utc": "2026-08-18T14:52:40Z",
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
    },
    "pull_request": {
        "run_id": 32147682239,
        "job_id": 95745374406,
        "event": "pull_request",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": CONTROL_REVISION,
        "created_at_utc": "2026-08-18T14:20:01Z",
        "started_at_utc": "2026-08-18T14:20:04Z",
        "completed_at_utc": "2026-08-18T14:46:13Z",
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
    },
}

CONTROL_SOURCE_BLOBS = {
    "tools/collect_item26_manual_cost_stop_raw_v2.py": {
        "git_blob_oid": "e584b87cb7c2dcea46efe5ba01042e7e7e0d94e0",
        "file_sha256": "739b8e8bea29250ccd4c24b400af791c67e687f0cecd23a4b1ddbc8b70750ea4",
    },
    "tools/extract_item26_manual_cost_stop_raw_v2.py": {
        "git_blob_oid": "64b87e4630b894f57f64317e0b3cb70b8367e153",
        "file_sha256": "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4",
    },
    AUTHORITY_REF: {
        "git_blob_oid": "91d5eaf9d63f3595c257ad31502407d1bb9a3cb0",
        "file_sha256": "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d",
    },
    "tools/build_item26_manual_cost_stop_authority_root_v2.py": {
        "git_blob_oid": "bd7e0cfac09ff7ee7b9c5dcc3473f4ef5563344f",
        "file_sha256": "d87685eb33a3bbad6458c71c5291a962414d094dd7a5051cab30a8d7cfd6bb62",
    },
    BUILDER_REF: {
        "git_blob_oid": "0274b4eb97dc5070176331a2f0c3922fb9c84120",
        "file_sha256": "d6ab77d5cd31c03bb5b1949fa9b60e6d2a904e872b31b5c95f63ad41f8b96a08",
    },
    "tools/verify_item26_manual_cost_stop_evidence_v2.py": {
        "git_blob_oid": "95727f7e6b8bcb7ff738ee2b2f0b9c650fc59968",
        "file_sha256": "8834c524165f3104cdf848e26eaefdcb3ed0e0e635e9ec3c1a02d3bcb02c6269",
    },
    "tools/build_item26_manual_cost_stop_evidence_v2.py": {
        "git_blob_oid": "861f355a92505c9e3f000a74acb57598375dd16e",
        "file_sha256": "ecf0a3d984b99b09e9f3d189f28fb8b60bd2355a28bf04565fd7c297fa765acb",
    },
    "tools/install_item26_manual_cost_stop_runtime_v3.py": {
        "git_blob_oid": "ee6d1a6eda2a17d688bace1dccb63066a346933e",
        "file_sha256": "8a851e0cc4f2945444613d63afff87fe498331b4762446e2c0deff2ce78814ef",
    },
    "tools/bootstrap_item26_manual_cost_stop_keys_v2.py": {
        "git_blob_oid": "e2b0b04f2bc5d8dc80185e29c059699209f2965f",
        "file_sha256": "2e35d16c2a2f55ddfa1436190ed8869449dd05fb8ae5fb45878ab9c50c0cd9ff",
    },
    "deploy/production/plans/item26-manual-cost-stop-contract-v2.json": {
        "git_blob_oid": "ecd01f4884efc5f1f5615146d251b1be3c5d9644",
        "file_sha256": "190ed155a410b20c1b081b5bc090bbc4c4a6609789d94c51296ce1460bc5ffd1",
    },
    PUBLIC_ROOT_REF: {
        "git_blob_oid": "a15720151f141e6b783a51d136e94d9957a7b1c6",
        "file_sha256": "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85",
    },
    ".github/workflows/ci.yml": {
        "git_blob_oid": "63fac8f7e588007544c96c32096e220f2d07a61f",
        "file_sha256": "74ab44b32802e969183c1a657ef83318692bdeebc2c598195262b3bb9114f26c",
    },
}

STAGED_SOURCE_RECORDS = {
    BUILDER_REF: {
        **CONTROL_SOURCE_BLOBS[BUILDER_REF],
        "size": 34510,
    },
    AUTHORITY_REF: {
        **CONTROL_SOURCE_BLOBS[AUTHORITY_REF],
        "size": 125914,
    },
}

# These bind the exact canonical 29-key CI pair and twelve source rows inside
# the isolated root literal without making that literal import this module.
EXPECTED_CONTROL_CI_SHA256 = (
    "433b39827a358e82dfafac646aa40be838e34174148cadcc27763993afb937f2"
)
EXPECTED_CONTROL_SOURCES_SHA256 = (
    "abbda75774b12bea724a6dca15b20eb375102ac87bb2cfdba39a2591032cded9"
)


class LauncherError(ValueError):
    """A fixed, non-sensitive launcher failure code."""


class FixedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise LauncherError("launcher_arguments")


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


def _parse_canonical(raw: bytes, code: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LauncherError(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                LauncherError(code)
            ),
        )
    except (UnicodeError, json.JSONDecodeError, LauncherError) as exc:
        raise LauncherError(code) from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise LauncherError(code)
    return value


def _require_absent(path: Path, code: str) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LauncherError(code) from exc
    raise LauncherError(code)


def _validate_tool(path: Path, *, mode: Optional[int] = None) -> os.stat_result:
    try:
        row = path.lstat()
    except OSError as exc:
        raise LauncherError("launcher_tool_identity") from exc
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != ROOT_UID
        or stat.S_IMODE(row.st_mode) & 0o022
        or (mode is not None and stat.S_IMODE(row.st_mode) != mode)
    ):
        raise LauncherError("launcher_tool_identity")
    return row


def _run_git(arguments: list[str], *, stdout: int = subprocess.PIPE) -> subprocess.CompletedProcess[bytes]:
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
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LauncherError("launcher_git") from exc
    if _stable(SYSTEM_GIT.lstat()) != _stable(before):
        raise LauncherError("launcher_git_changed")
    return result


def _git_stdout(arguments: list[str], code: str) -> bytes:
    result = _run_git(arguments)
    if result.returncode != 0 or not result.stdout:
        raise LauncherError(code)
    return result.stdout


def _read_and_bind_launcher(
    expected_launcher_sha256: str,
    expected_root_program_sha256: str,
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
        raise LauncherError("launcher_source_identity") from exc
    raw = b"".join(chunks)
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
        or hashlib.sha256(raw).hexdigest() != expected_launcher_sha256
        or hashlib.sha256(ROOT_PROGRAM.encode("ascii")).hexdigest()
        != expected_root_program_sha256
    ):
        raise LauncherError("launcher_source_binding")


def _validate_outer_boundary(
    expected_launcher_sha256: str,
    expected_root_program_sha256: str,
) -> None:
    if (
        os.getuid() != EXPECTED_USER_UID
        or os.geteuid() != EXPECTED_USER_UID
        or Path.cwd().resolve(strict=True) != REPOSITORY_ROOT
        or Path.cwd() != REPOSITORY_ROOT
        or Path(__file__).absolute()
        != REPOSITORY_ROOT / "tools/stage_and_sign_item26_activation_receipt_v3.py"
        or sys.flags.isolated != 1
        or sys.flags.ignore_environment != 1
        or sys.flags.no_site != 1
        or sys.flags.dont_write_bytecode != 1
        or Path(sys.executable).absolute() != SYSTEM_PYTHON_ENTRY
    ):
        raise LauncherError("launcher_execution_boundary")
    try:
        tty_names = tuple(os.ttyname(fd) for fd in (0, 1, 2))
    except OSError as exc:
        raise LauncherError("launcher_tty_012") from exc
    if any(not os.isatty(fd) for fd in (0, 1, 2)) or len(set(tty_names)) != 1:
        raise LauncherError("launcher_tty_012")
    _read_and_bind_launcher(
        expected_launcher_sha256,
        expected_root_program_sha256,
    )
    for path, expected in (
        (SYSTEM_PYTHON, SYSTEM_STUB_SHA256),
        (SYSTEM_GIT, SYSTEM_STUB_SHA256),
        (SYSTEM_OPENSSL, SYSTEM_OPENSSL_SHA256),
        (SYSTEM_PYTHON_EXECUTABLE, SYSTEM_PYTHON_EXECUTABLE_SHA256),
    ):
        row = _validate_tool(path, mode=0o755)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected or _stable(path.lstat()) != _stable(row):
            raise LauncherError("launcher_tool_binding")
    _validate_tool(SYSTEM_SUDO, mode=0o4511)
    try:
        entry_before = SYSTEM_PYTHON_ENTRY.lstat()
        target = os.readlink(SYSTEM_PYTHON_ENTRY)
        entry_after = SYSTEM_PYTHON_ENTRY.lstat()
    except OSError as exc:
        raise LauncherError("launcher_python_entry") from exc
    if (
        not stat.S_ISLNK(entry_before.st_mode)
        or entry_before.st_uid != ROOT_UID
        or target != SYSTEM_PYTHON_ENTRY_TARGET
        or _stable(entry_before) != _stable(entry_after)
        or SYSTEM_PYTHON_ENTRY.resolve(strict=True) != SYSTEM_PYTHON_EXECUTABLE
    ):
        raise LauncherError("launcher_python_entry")
    for arguments in (
        ["rev-parse", "HEAD"],
        ["rev-parse", "@{upstream}"],
        ["rev-parse", BRANCH_REF],
    ):
        if _git_stdout(arguments, "launcher_control_revision").decode("ascii").strip() != CONTROL_REVISION:
            raise LauncherError("launcher_control_revision")
    status = _run_git(["status", "--porcelain=v1", "--untracked-files=no"])
    if status.returncode != 0 or status.stdout != b"":
        raise LauncherError("launcher_tracked_tree_dirty")
    _require_absent(PUBLIC_CAPTURE_PATH, "launcher_capture_residue")


def _git_blob(ref: str) -> bytes:
    expected = CONTROL_SOURCE_BLOBS[ref]
    oid = _git_stdout(
        ["rev-parse", CONTROL_REVISION + ":" + ref],
        "launcher_source_binding",
    ).decode("ascii").strip()
    raw = _git_stdout(
        ["show", CONTROL_REVISION + ":" + ref],
        "launcher_source_binding",
    )
    if oid != expected["git_blob_oid"] or hashlib.sha256(raw).hexdigest() != expected["file_sha256"]:
        raise LauncherError("launcher_source_binding")
    return raw


def _build_public_bundle() -> tuple[bytes, dict[str, bytes]]:
    if (
        hashlib.sha256(canonical_bytes(CONTROL_CI)).hexdigest()
        != EXPECTED_CONTROL_CI_SHA256
        or hashlib.sha256(canonical_bytes(CONTROL_SOURCE_BLOBS)).hexdigest()
        != EXPECTED_CONTROL_SOURCES_SHA256
    ):
        raise LauncherError("launcher_embedded_public_binding")
    all_raw = {ref: _git_blob(ref) for ref in CONTROL_SOURCE_BLOBS}
    staged: dict[str, dict[str, Any]] = {}
    for ref, record in STAGED_SOURCE_RECORDS.items():
        raw = all_raw[ref]
        if len(raw) != record["size"]:
            raise LauncherError("launcher_staged_source_size")
        staged[ref] = {
            **record,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }
    bundle = canonical_bytes(
        {
            "schema": BUNDLE_SCHEMA,
            "control_revision": CONTROL_REVISION,
            "repository_root": str(REPOSITORY_ROOT),
            "control_ci": CONTROL_CI,
            "control_source_blobs": CONTROL_SOURCE_BLOBS,
            "staged_sources": staged,
        }
    )
    if not 1 <= len(bundle) <= MAX_BUNDLE_BYTES:
        raise LauncherError("launcher_bundle_size")
    return bundle, all_raw


# This is passed as one literal argv value.  It imports no repository module,
# creates nothing until every public/system/Git/stdout check has passed, and
# deliberately has no rollback or cleanup path.
ROOT_PROGRAM = r'''
import base64, datetime, fcntl, hashlib, json, os, pathlib, stat, subprocess, sys

CONTROL = "68aa82ffbdd43e78e585d8956d13d3030ef6a640"
REPO = pathlib.Path("/Users/openclaw/Desktop/noteai")
SIGNER = pathlib.Path("/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-signer")
PARENT = SIGNER.parent
BUILDER_REF = "tools/build_item26_manual_cost_stop_activation_receipt_v3.py"
AUTHORITY_REF = "tools/verify_item26_manual_cost_stop_authority_v2.py"
BUILDER_NAME = pathlib.Path(BUILDER_REF).name
AUTHORITY_NAME = pathlib.Path(AUTHORITY_REF).name
SCHEMA = "noteai.item26.activation-receipt-v3-root-staging-bundle.v1"
REQUEST_SCHEMA = "noteai.item26.manual-cost-stop-activation-sign-request.v3"
CI_SHA = "433b39827a358e82dfafac646aa40be838e34174148cadcc27763993afb937f2"
SOURCES_SHA = "abbda75774b12bea724a6dca15b20eb375102ac87bb2cfdba39a2591032cded9"
STAGED = {
    BUILDER_REF: ("0274b4eb97dc5070176331a2f0c3922fb9c84120", "d6ab77d5cd31c03bb5b1949fa9b60e6d2a904e872b31b5c95f63ad41f8b96a08", 34510, BUILDER_NAME),
    AUTHORITY_REF: ("91d5eaf9d63f3595c257ad31502407d1bb9a3cb0", "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d", 125914, AUTHORITY_NAME),
}
SOURCE_REFS = (
    "tools/collect_item26_manual_cost_stop_raw_v2.py",
    "tools/extract_item26_manual_cost_stop_raw_v2.py",
    AUTHORITY_REF,
    "tools/build_item26_manual_cost_stop_authority_root_v2.py",
    BUILDER_REF,
    "tools/verify_item26_manual_cost_stop_evidence_v2.py",
    "tools/build_item26_manual_cost_stop_evidence_v2.py",
    "tools/install_item26_manual_cost_stop_runtime_v3.py",
    "tools/bootstrap_item26_manual_cost_stop_keys_v2.py",
    "deploy/production/plans/item26-manual-cost-stop-contract-v2.json",
    "deploy/production/authorities/item26-manual-cost-stop-authority-root-v2.json",
    ".github/workflows/ci.yml",
)
STUB_SHA = "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
PYTHON_SHA = "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"
OPENSSL_SHA = "517827f877751b6d7abebe404a296fa8e82425c63694a73ab06db35e6d9a8362"
PYTHON_ENTRY = pathlib.Path("/Library/Developer/CommandLineTools/usr/bin/python3")
PYTHON_BIN = pathlib.Path("/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9")
GIT = pathlib.Path("/usr/bin/git")
OPENSSL = pathlib.Path("/usr/bin/openssl")
MAX = 1024 * 1024
BOOTSTRAP_DIR_NAME = "item26-manual-cost-stop-v2-bootstrap"
CUSTODY_DIR_NAME = "item26-manual-cost-stop-v2-custody"
BOOTSTRAP_FILE = "bootstrap_item26_manual_cost_stop_keys_v2.py"
BOOTSTRAP_SHA = "2e35d16c2a2f55ddfa1436190ed8869449dd05fb8ae5fb45878ab9c50c0cd9ff"
BOOTSTRAP_SIZE = 26443
CUSTODY_FILES = {"provider-private-key.pem","confirmation-private-key.pem","local-ci-observation-private-key.pem"}

class E(Exception): pass
def fail(code): raise E(code)
def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
def stable(row):
    return (row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
def tool(path, digest, mode=0o755):
    try:
        a=path.lstat(); raw=path.read_bytes(); b=path.lstat()
    except OSError: fail("root_tool_identity")
    if not stat.S_ISREG(a.st_mode) or stat.S_ISLNK(a.st_mode) or a.st_uid!=0 or stat.S_IMODE(a.st_mode)!=mode or stable(a)!=stable(b) or hashlib.sha256(raw).hexdigest()!=digest: fail("root_tool_binding")
    return a
def repo_identity():
    paths=[]; current=pathlib.Path("/"); paths.append(current)
    for part in REPO.parts[1:]: current=current/part; paths.append(current)
    paths.append(REPO/".git")
    try: rows=[p.lstat() for p in paths]
    except OSError: fail("root_repository_identity")
    for index,row in enumerate(rows):
        if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or stat.S_IMODE(row.st_mode)&0o022 or (index>=2 and row.st_uid not in (0,501)): fail("root_repository_identity")
    return tuple((str(p),stable(r)) for p,r in zip(paths,rows))
def git(args):
    before=GIT.lstat(); identity=repo_identity()
    try:
        result=subprocess.run([str(GIT),"-c","safe.directory="+str(REPO),"--no-replace-objects",*args],cwd=REPO,env={"PATH":"/usr/bin:/bin","LC_ALL":"C","LANG":"C","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null","GIT_NO_REPLACE_OBJECTS":"1","GIT_OPTIONAL_LOCKS":"0"},stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20,check=False)
    except (OSError,subprocess.SubprocessError): fail("root_git")
    if stable(GIT.lstat())!=stable(before) or repo_identity()!=identity or result.returncode!=0: fail("root_git")
    return result.stdout
def parse(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: fail("root_bundle_canonical")
            result[key]=value
        return result
    try: value=json.loads(raw.decode("ascii"),object_pairs_hook=pairs,parse_constant=lambda _x: fail("root_bundle_canonical"))
    except Exception as exc:
        if isinstance(exc,E): raise
        fail("root_bundle_canonical")
    if type(value) is not dict or canon(value)!=raw: fail("root_bundle_canonical")
    return value
def absent(path):
    try: path.lstat()
    except FileNotFoundError: return
    except OSError: fail("root_signer_absence")
    fail("root_signer_absence")
def read_all():
    chunks=[]; total=0
    while total<=MAX:
        chunk=os.read(0,min(65536,MAX+1-total))
        if not chunk: break
        chunks.append(chunk); total+=len(chunk)
    raw=b"".join(chunks)
    if not 1<=len(raw)<=MAX: fail("root_bundle_size")
    return raw
def directory_row(row,code):
    if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or stat.S_IMODE(row.st_mode)!=0o700 or row.st_uid!=0 or row.st_nlink<2: fail(code)
def read_bootstrap(directory_fd):
    try:
        before=os.stat(BOOTSTRAP_FILE,dir_fd=directory_fd,follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or stat.S_IMODE(before.st_mode)!=0o600 or before.st_uid!=0 or before.st_nlink!=1 or before.st_size!=BOOTSTRAP_SIZE: fail("root_bootstrap_identity")
        fd=os.open(BOOTSTRAP_FILE,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=directory_fd)
        opened=os.fstat(fd); chunks=[]; total=0
        while total<=BOOTSTRAP_SIZE:
            chunk=os.read(fd,min(65536,BOOTSTRAP_SIZE+1-total))
            if not chunk: break
            chunks.append(chunk); total+=len(chunk)
        closed=os.fstat(fd); os.close(fd)
        after=os.stat(BOOTSTRAP_FILE,dir_fd=directory_fd,follow_symlinks=False); raw=b"".join(chunks)
    except E: raise
    except OSError: fail("root_bootstrap_identity")
    if stable(before)!=stable(opened) or stable(opened)!=stable(closed) or stable(closed)!=stable(after) or len(raw)!=BOOTSTRAP_SIZE or hashlib.sha256(raw).hexdigest()!=BOOTSTRAP_SHA: fail("root_bootstrap_binding")
def prevalidate_noteai():
    try:
        before=PARENT.lstat(); directory_row(before,"root_signer_parent")
        parent_fd=os.open(PARENT,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0)); opened=os.fstat(parent_fd); directory_row(opened,"root_signer_parent")
        if stable(before)!=stable(opened) or set(os.listdir(parent_fd))!={BOOTSTRAP_DIR_NAME,CUSTODY_DIR_NAME}: fail("root_noteai_inventory")
        bootstrap_fd=os.open(BOOTSTRAP_DIR_NAME,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=parent_fd); directory_row(os.fstat(bootstrap_fd),"root_bootstrap_identity")
        if set(os.listdir(bootstrap_fd))!={BOOTSTRAP_FILE}: fail("root_bootstrap_inventory")
        read_bootstrap(bootstrap_fd); os.close(bootstrap_fd)
        custody_fd=os.open(CUSTODY_DIR_NAME,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=parent_fd); directory_row(os.fstat(custody_fd),"root_custody_identity")
        if set(os.listdir(custody_fd))!=CUSTODY_FILES: fail("root_custody_inventory")
        for name in CUSTODY_FILES:
            row=os.stat(name,dir_fd=custody_fd,follow_symlinks=False)
            if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or stat.S_IMODE(row.st_mode)!=0o600 or row.st_uid!=0 or row.st_nlink!=1 or not 1<=row.st_size<=MAX: fail("root_custody_file_identity")
        os.close(custody_fd)
        after_fd=os.fstat(parent_fd); after=PARENT.lstat()
        if stable(opened)!=stable(after_fd) or stable(after_fd)!=stable(after) or set(os.listdir(parent_fd))!={BOOTSTRAP_DIR_NAME,CUSTODY_DIR_NAME}: fail("root_noteai_changed")
    except E: raise
    except OSError: fail("root_noteai_identity")
    return parent_fd
def write_at(directory_fd,name,raw):
    flags=os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0)
    fd=os.open(name,flags,0o600,dir_fd=directory_fd)
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
        if not stat.S_ISREG(row.st_mode) or stat.S_IMODE(row.st_mode)!=0o600 or row.st_uid!=0 or row.st_nlink!=1 or b"".join(chunks)!=raw: fail("root_stage_identity")
    finally: os.close(fd)
def main():
    if os.getuid()!=0 or os.geteuid()!=0 or pathlib.Path.cwd()!=pathlib.Path("/") or sys.flags.isolated!=1 or sys.flags.ignore_environment!=1 or sys.flags.no_site!=1 or sys.flags.dont_write_bytecode!=1 or pathlib.Path(sys.executable).absolute()!=PYTHON_ENTRY: fail("root_execution_boundary")
    if os.isatty(0) or not os.isatty(2): fail("root_stdio_boundary")
    out=os.fstat(1)
    out_flags=fcntl.fcntl(1,fcntl.F_GETFL)
    if not stat.S_ISREG(out.st_mode) or stat.S_IMODE(out.st_mode)!=0o600 or out.st_uid!=501 or out.st_nlink!=1 or out.st_size!=0 or os.lseek(1,0,os.SEEK_CUR)!=0 or out_flags&os.O_APPEND or out_flags&os.O_ACCMODE not in (os.O_WRONLY,os.O_RDWR): fail("root_capture_boundary")
    tool(pathlib.Path("/usr/bin/python3"),STUB_SHA); tool(GIT,STUB_SHA); tool(OPENSSL,OPENSSL_SHA); tool(PYTHON_BIN,PYTHON_SHA)
    try: entry=PYTHON_ENTRY.lstat(); target=os.readlink(PYTHON_ENTRY)
    except OSError: fail("root_python_entry")
    if not stat.S_ISLNK(entry.st_mode) or entry.st_uid!=0 or target!="../../Library/Frameworks/Python3.framework/Versions/3.9/bin/python3" or PYTHON_ENTRY.resolve(strict=True)!=PYTHON_BIN: fail("root_python_entry")
    if REPO.resolve(strict=True)!=REPO: fail("root_repository_identity")
    identity=repo_identity(); absent(SIGNER)
    raw=read_all(); bundle=parse(raw)
    if set(bundle)!={"schema","control_revision","repository_root","control_ci","control_source_blobs","staged_sources"} or bundle.get("schema")!=SCHEMA or bundle.get("control_revision")!=CONTROL or bundle.get("repository_root")!=str(REPO) or hashlib.sha256(canon(bundle.get("control_ci"))).hexdigest()!=CI_SHA or hashlib.sha256(canon(bundle.get("control_source_blobs"))).hexdigest()!=SOURCES_SHA: fail("root_bundle_binding")
    sources=bundle["control_source_blobs"]
    if type(sources) is not dict or set(sources)!=set(SOURCE_REFS) or type(bundle.get("staged_sources")) is not dict or set(bundle["staged_sources"])!=set(STAGED): fail("root_bundle_shape")
    material={}
    for ref in SOURCE_REFS:
        row=sources[ref]
        if type(row) is not dict or set(row)!={"git_blob_oid","file_sha256"}: fail("root_source_shape")
        oid=git(["rev-parse",CONTROL+":"+ref]).decode("ascii").strip(); blob=git(["show",CONTROL+":"+ref])
        if oid!=row["git_blob_oid"] or hashlib.sha256(blob).hexdigest()!=row["file_sha256"]: fail("root_source_binding")
        if ref in STAGED: material[ref]=blob
    for ref,(oid,digest,size,name) in STAGED.items():
        row=bundle["staged_sources"][ref]
        if type(row) is not dict or set(row)!={"git_blob_oid","file_sha256","size","content_base64"} or row.get("git_blob_oid")!=oid or row.get("file_sha256")!=digest or row.get("size")!=size: fail("root_stage_bundle")
        try: decoded=base64.b64decode(row["content_base64"],validate=True)
        except Exception: fail("root_stage_bundle")
        if decoded!=material[ref] or len(decoded)!=size or hashlib.sha256(decoded).hexdigest()!=digest: fail("root_stage_bundle")
    if repo_identity()!=identity: fail("root_repository_changed")
    parent_fd=prevalidate_noteai()
    now=datetime.datetime.now(datetime.timezone.utc); activated=now.replace(microsecond=0); completed=datetime.datetime.fromisoformat("2026-08-18T14:52:40+00:00"); after=datetime.datetime.now(datetime.timezone.utc)
    if not completed<activated<=after: fail("root_activation_clock")
    request=canon({"schema":REQUEST_SCHEMA,"control_ci":bundle["control_ci"],"control_source_blobs":sources,"activated_at_utc":activated.strftime("%Y-%m-%dT%H:%M:%SZ")})
    try:
        os.mkdir(SIGNER.name,0o700,dir_fd=parent_fd)
        signer_fd=os.open(SIGNER.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0),dir_fd=parent_fd)
        os.fchmod(signer_fd,0o700)
        for ref,(_oid,_digest,_size,name) in STAGED.items(): write_at(signer_fd,name,material[ref])
        os.fsync(signer_fd); os.fsync(parent_fd)
        row=os.fstat(signer_fd)
        if not stat.S_ISDIR(row.st_mode) or stat.S_IMODE(row.st_mode)!=0o700 or row.st_uid!=0 or row.st_nlink<2 or set(os.listdir(signer_fd))!={BUILDER_NAME,AUTHORITY_NAME} or set(os.listdir(parent_fd))!={BOOTSTRAP_DIR_NAME,CUSTODY_DIR_NAME,SIGNER.name}: fail("root_stage_inventory")
        os.close(signer_fd); os.close(parent_fd)
    except E: raise
    except OSError: fail("root_stage_operation")
    if set(os.listdir(SIGNER))!={BUILDER_NAME,AUTHORITY_NAME}: fail("root_stage_inventory")
    try:
        result=subprocess.run(["/usr/bin/python3","-E","-S","-B",str(SIGNER/BUILDER_NAME),"--control-revision",CONTROL,"--repository-root",str(REPO)],input=request,stdout=None,stderr=subprocess.DEVNULL,cwd="/",env={"PATH":"/usr/bin:/bin","LC_ALL":"C","LANG":"C","PYTHONDONTWRITEBYTECODE":"1"},close_fds=True,timeout=120,check=False)
    except (OSError,subprocess.SubprocessError): fail("root_signer_dispatch")
    if result.returncode!=0: fail("root_signer_failed")
    os.fsync(1)
    return 0
try:
    root_status=main()
except E as exc:
    sys.stderr.write('{"schema":"noteai.item26.activation-receipt-v3-root-launcher.v1","status":"BLOCKED_RESIDUE_REVIEW_REQUIRED","reason":'+json.dumps(str(exc),separators=(",",":"))+'}\n')
    raise SystemExit(1)
except BaseException:
    sys.stderr.write('{"schema":"noteai.item26.activation-receipt-v3-root-launcher.v1","status":"BLOCKED_RESIDUE_REVIEW_REQUIRED","reason":"root_unclassified_failure"}\n')
    raise SystemExit(1)
raise SystemExit(root_status)
'''


def _load_exact_authority(raw: bytes) -> types.ModuleType:
    name = "verify_item26_manual_cost_stop_authority_v2"
    module = types.ModuleType(name)
    module.__file__ = str(REPOSITORY_ROOT / AUTHORITY_REF)
    module.__package__ = None
    sys.modules[name] = module
    try:
        exec(compile(raw, module.__file__, "exec"), module.__dict__)
    except BaseException as exc:
        raise LauncherError("launcher_authority_load") from exc
    return module


def _write_pipe(descriptor: int, raw: bytes, failures: list[bool]) -> None:
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                failures.append(True)
                return
            offset += written
    except OSError:
        failures.append(True)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            failures.append(True)


def _verify_signature_fd(payload: bytes, signature: bytes, key: bytes) -> bool:
    if any(type(value) is not bytes or not value for value in (payload, signature, key)):
        return False
    before = _validate_tool(SYSTEM_OPENSSL, mode=0o755)
    try:
        openssl_raw = SYSTEM_OPENSSL.read_bytes()
    except OSError:
        return False
    if (
        hashlib.sha256(openssl_raw).hexdigest() != SYSTEM_OPENSSL_SHA256
        or _stable(SYSTEM_OPENSSL.lstat()) != _stable(before)
    ):
        return False
    pipes = [os.pipe() for _ in range(3)]
    read_fds = tuple(pair[0] for pair in pipes)
    write_fds = tuple(pair[1] for pair in pipes)
    process: Optional[subprocess.Popen[bytes]] = None
    failures: list[bool] = []
    threads: list[threading.Thread] = []
    try:
        process = subprocess.Popen(
            [
                str(SYSTEM_OPENSSL),
                "dgst",
                "-sha256",
                "-verify",
                f"/dev/fd/{read_fds[2]}",
                "-signature",
                f"/dev/fd/{read_fds[1]}",
                f"/dev/fd/{read_fds[0]}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            close_fds=True,
            pass_fds=read_fds,
        )
        for descriptor in read_fds:
            os.close(descriptor)
        read_fds = ()
        for descriptor, raw in zip(write_fds, (payload, signature, key)):
            thread = threading.Thread(
                target=_write_pipe,
                args=(descriptor, raw, failures),
                daemon=False,
            )
            thread.start()
            threads.append(thread)
        write_fds = ()
        return_code = process.wait(timeout=20)
        for thread in threads:
            thread.join(timeout=20)
        return (
            return_code == 0
            and not failures
            and all(not thread.is_alive() for thread in threads)
            and _stable(SYSTEM_OPENSSL.lstat()) == _stable(before)
        )
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        for descriptor in (*read_fds, *write_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()


def _read_and_validate_capture(
    descriptor: int,
    *,
    parent_descriptor: int,
    parent_identity: tuple[int, ...],
    authority_raw: bytes,
    root_raw: bytes,
) -> tuple[bytes, dict[str, Any]]:
    try:
        os.fsync(descriptor)
        before = os.fstat(descriptor)
        path_before = PUBLIC_CAPTURE_PATH.lstat()
        parent_before = os.fstat(parent_descriptor)
        parent_path_before = PUBLIC_CAPTURE_PATH.parent.lstat()
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_RECEIPT_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_RECEIPT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        path_after = PUBLIC_CAPTURE_PATH.lstat()
        parent_after = os.fstat(parent_descriptor)
        parent_path_after = PUBLIC_CAPTURE_PATH.parent.lstat()
    except OSError as exc:
        raise LauncherError("launcher_capture_readback") from exc
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= MAX_RECEIPT_BYTES
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != EXPECTED_USER_UID
        or before.st_nlink != 1
        or _stable(before) != _stable(path_before)
        or _stable(before) != _stable(after)
        or _stable(after) != _stable(path_after)
        or _stable(parent_before) != parent_identity
        or _stable(parent_before) != _stable(parent_path_before)
        or _stable(parent_before) != _stable(parent_after)
        or _stable(parent_after) != _stable(parent_path_after)
    ):
        raise LauncherError("launcher_capture_identity")
    payload, _summary = _validate_receipt_bytes(
        raw,
        authority_raw=authority_raw,
        root_raw=root_raw,
    )
    return raw, payload


def _validate_receipt_bytes(
    raw: bytes,
    *,
    authority_raw: bytes,
    root_raw: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = _parse_canonical(raw, "launcher_receipt_canonical")
    if receipt.get("schema") != RECEIPT_SCHEMA or type(receipt.get("payload")) is not dict:
        raise LauncherError("launcher_receipt_contract")
    if any(marker in raw for marker in (b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN RSA PRIVATE KEY-----", b"-----BEGIN EC PRIVATE KEY-----")):
        raise LauncherError("launcher_receipt_private_material")
    authority = _load_exact_authority(authority_raw)
    authority._verify_signature = _verify_signature_fd
    try:
        root_value, keys = authority._validate_root(
            root_raw,
            expected_hash=CONTROL_SOURCE_BLOBS[PUBLIC_ROOT_REF]["file_sha256"],
            root=REPOSITORY_ROOT,
        )
        summary = authority.validate_runtime_activation_receipt(
            raw,
            root_value=root_value,
            keys=keys,
            control_revision=CONTROL_REVISION,
            expected_authority_root_file_sha256=CONTROL_SOURCE_BLOBS[PUBLIC_ROOT_REF]["file_sha256"],
            expected_source_hashes={
                ref: CONTROL_SOURCE_BLOBS[ref]["file_sha256"]
                for ref in (
                    "tools/collect_item26_manual_cost_stop_raw_v2.py",
                    "tools/extract_item26_manual_cost_stop_raw_v2.py",
                    AUTHORITY_REF,
                )
            },
            root=REPOSITORY_ROOT,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise LauncherError("launcher_receipt_validation") from exc
    payload = receipt["payload"]
    if (
        payload.get("control_revision") != CONTROL_REVISION
        or payload.get("control_ci") != CONTROL_CI
        or payload.get("control_source_blobs") != CONTROL_SOURCE_BLOBS
        or payload.get("item26_status") != "unverified"
        or payload.get("readiness_credit_added") is not False
    ):
        raise LauncherError("launcher_receipt_binding")
    expected_runtime_sources = {
        ref: CONTROL_SOURCE_BLOBS[ref]["file_sha256"]
        for ref in RUNTIME_SOURCE_REFS
    }
    expected_summary_keys = {
        "activation_receipt_sha256",
        "activation_receipt_semantic_sha256",
        "activated_at_utc",
        "control_revision",
        "authority_epoch_id",
        "authority_root_file_sha256",
        "authority_root_git_blob_sha256",
        "authority_root_git_blob_oid",
        "source_file_sha256",
        "control_ci",
        "readback_started",
        "cloud_read_count",
        "cloud_write_count",
        "database_connection_count",
        "journal_write_count",
    }
    if (
        type(summary) is not dict
        or set(summary) != expected_summary_keys
        or summary.get("activation_receipt_sha256")
        != hashlib.sha256(raw).hexdigest()
        or summary.get("activation_receipt_semantic_sha256")
        != hashlib.sha256(canonical_bytes(receipt)[:-1]).hexdigest()
        or summary.get("activated_at_utc") != payload.get("activated_at_utc")
        or summary.get("control_revision") != CONTROL_REVISION
        or summary.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or summary.get("authority_root_file_sha256")
        != CONTROL_SOURCE_BLOBS[PUBLIC_ROOT_REF]["file_sha256"]
        or summary.get("authority_root_git_blob_sha256")
        != CONTROL_SOURCE_BLOBS[PUBLIC_ROOT_REF]["file_sha256"]
        or summary.get("authority_root_git_blob_oid")
        != CONTROL_SOURCE_BLOBS[PUBLIC_ROOT_REF]["git_blob_oid"]
        or summary.get("source_file_sha256") != expected_runtime_sources
        or summary.get("control_ci") != CONTROL_CI
        or summary.get("readback_started") is not False
        or any(
            type(summary.get(name)) is not int or summary.get(name) != 0
            for name in (
                "cloud_read_count",
                "cloud_write_count",
                "database_connection_count",
                "journal_write_count",
            )
        )
    ):
        raise LauncherError("launcher_receipt_summary_binding")
    return payload, summary


def _open_capture() -> tuple[int, int, tuple[int, ...]]:
    try:
        parent_path = PUBLIC_CAPTURE_PATH.parent
        parent_before = parent_path.lstat()
        if (
            parent_path.resolve(strict=True) != parent_path
            or not stat.S_ISDIR(parent_before.st_mode)
            or stat.S_ISLNK(parent_before.st_mode)
            or parent_before.st_uid != EXPECTED_USER_UID
            or stat.S_IMODE(parent_before.st_mode) & 0o022
        ):
            raise LauncherError("launcher_capture_parent")
        parent_descriptor = os.open(
            parent_path,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        parent_opened = os.fstat(parent_descriptor)
        if _stable(parent_before) != _stable(parent_opened):
            raise LauncherError("launcher_capture_parent")
        descriptor = os.open(
            PUBLIC_CAPTURE_PATH.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fchmod(descriptor, 0o600)
        os.fsync(parent_descriptor)
        row = os.fstat(descriptor)
        parent_after = os.fstat(parent_descriptor)
        parent_path_after = parent_path.lstat()
    except OSError as exc:
        raise LauncherError("launcher_capture_create") from exc
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != EXPECTED_USER_UID
        or row.st_nlink != 1
        or row.st_size != 0
        or _stable(parent_after) != _stable(parent_path_after)
    ):
        os.close(descriptor)
        raise LauncherError("launcher_capture_identity")
    return descriptor, parent_descriptor, _stable(parent_after)


def _run_once(
    expected_launcher_sha256: str,
    expected_root_program_sha256: str,
) -> dict[str, Any]:
    if EXECUTION_CONSUMED is True:
        raise LauncherError("launcher_replay_forbidden")
    _validate_outer_boundary(
        expected_launcher_sha256,
        expected_root_program_sha256,
    )
    bundle, raw_sources = _build_public_bundle()
    capture_fd, capture_parent_fd, capture_parent_identity = _open_capture()
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
            raise LauncherError("launcher_single_sudo_failed")
        if _stable(SYSTEM_SUDO.lstat()) != _stable(sudo_before):
            raise LauncherError("launcher_sudo_changed")
        receipt_raw, payload = _read_and_validate_capture(
            capture_fd,
            parent_descriptor=capture_parent_fd,
            parent_identity=capture_parent_identity,
            authority_raw=raw_sources[AUTHORITY_REF],
            root_raw=raw_sources[PUBLIC_ROOT_REF],
        )
    finally:
        os.close(capture_fd)
        os.close(capture_parent_fd)
    return {
        "schema": "noteai.item26.activation-receipt-v3-visible-terminal-launcher.v1",
        "status": "ROOT_SIGNER_STAGED_RECEIPT_CAPTURED_AND_VERIFIED",
        "control_revision": CONTROL_REVISION,
        "capture_path": str(PUBLIC_CAPTURE_PATH),
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "activated_at_utc": payload["activated_at_utc"],
        "sudo_dispatch_count": 1,
        "automatic_retry_count": 0,
        "outer_cleanup_count": 0,
        "authorized_signer_nonsecret_scratch_file_cleanup_count": 2,
        "authorized_signer_nonsecret_scratch_directory_cleanup_count": 1,
        "private_key_python_read_count": 0,
        "private_key_output_count": 0,
        "local_ci_private_key_fd_open_count": 1,
        "openssl_private_key_use_count": 2,
        "public_key_identity_export_count": 1,
        "cloud_call_count": 0,
        "database_connection_count": 0,
        "readiness_credit_added": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    try:
        parser = FixedArgumentParser(add_help=False, allow_abbrev=False)
        parser.add_argument("--expected-launcher-sha256", required=True)
        parser.add_argument("--expected-root-program-sha256", required=True)
        arguments = parser.parse_args(argv)
        for value in (
            arguments.expected_launcher_sha256,
            arguments.expected_root_program_sha256,
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise LauncherError("launcher_arguments")
        result = _run_once(
            arguments.expected_launcher_sha256,
            arguments.expected_root_program_sha256,
        )
    except LauncherError as exc:
        result = {
            "schema": "noteai.item26.activation-receipt-v3-visible-terminal-launcher.v1",
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
            "schema": "noteai.item26.activation-receipt-v3-visible-terminal-launcher.v1",
            "status": "BLOCKED_RESIDUE_REVIEW_REQUIRED",
            "reason": "launcher_unclassified_failure",
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
    "CONTROL_CI",
    "CONTROL_REVISION",
    "CONTROL_SOURCE_BLOBS",
    "EXECUTED_ATTEMPT_REVISION",
    "EXECUTION_CONSUMED",
    "PUBLIC_CAPTURE_PATH",
    "ROOT_PROGRAM",
    "SIGNER_DIRECTORY",
    "LauncherError",
    "canonical_bytes",
    "main",
]
