#!/usr/bin/env python3
"""One-shot root-custody bootstrap for Item 26 authority generation v2.

This tool has no cloud, database, Git, billing, mutation, or cleanup
capability.  It must be copied from an accepted Git blob into the fixed
root-owned execution directory with exclusive creation.  The operator must
compare the installed file's SHA-256 with that accepted blob before invoking
it.  The tool then independently verifies its fixed path, exact one-file
inventory, ownership, modes, stable identity, pinned system interpreter, and
pinned OpenSSL binary.

Private keys are created directly at their final root-owned paths.  OpenSSL
writes each key to an already-open ``O_EXCL`` descriptor and later reads that
descriptor to export only the public key.  Python never reads private-key
bytes.  Every failure leaves any residue in place and forbids retry, overwrite,
rollback, or deletion.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, BinaryIO, Optional


ROOT_UID = 0
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
AUTHORITY_EPOCH_ID = "noteai.item26.manual-cost-stop-authority-generation.v2"
PUBLIC_EXPORT_SCHEMA = (
    "noteai.item26.manual-cost-stop-key-bootstrap-public-export.v2"
)
EXECUTION_FLAG = "--execute-authorized-key-bootstrap"

NOTEAI_DIRECTORY = Path("/Library/Application Support/NoteAI")
EXECUTION_DIRECTORY = NOTEAI_DIRECTORY / "item26-manual-cost-stop-v2-bootstrap"
CUSTODY_DIRECTORY = NOTEAI_DIRECTORY / "item26-manual-cost-stop-v2-custody"
BOOTSTRAP_REF = "tools/bootstrap_item26_manual_cost_stop_keys_v2.py"
BOOTSTRAP_FILE = Path(BOOTSTRAP_REF).name
EXECUTION_INVENTORY = (BOOTSTRAP_FILE,)
ROLE_FILES = {
    "provider": "provider-private-key.pem",
    "confirmation": "confirmation-private-key.pem",
    "local_ci_observation": "local-ci-observation-private-key.pem",
}

OPENSSL = Path("/usr/bin/openssl")
EXPECTED_OPENSSL_SHA256 = (
    "517827f877751b6d7abebe404a296fa8e82425c63694a73ab06db35e6d9a8362"
)
SYSTEM_PYTHON_LAUNCHER = Path("/usr/bin/python3")
SYSTEM_PYTHON_ENTRY = Path(
    "/Library/Developer/CommandLineTools/usr/bin/python3"
)
SYSTEM_PYTHON_EXECUTABLE = Path(
    "/Library/Developer/CommandLineTools/Library/Frameworks/"
    "Python3.framework/Versions/3.9/bin/python3.9"
)
EXPECTED_SYSTEM_PYTHON_LAUNCHER_SHA256 = (
    "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
)
EXPECTED_SYSTEM_PYTHON_EXECUTABLE_SHA256 = (
    "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"
)
EXPECTED_SYSTEM_PYTHON_ENTRY_TARGET = (
    "../../Library/Frameworks/Python3.framework/Versions/3.9/bin/python3"
)

MAX_TOOL_BYTES = 24 * 1024 * 1024
MAX_PUBLIC_KEY_BYTES = 64 * 1024
PRIVATE_KEY_TIMEOUT_SECONDS = 180
PUBLIC_KEY_TIMEOUT_SECONDS = 30
MINIMAL_ENV = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "LANG": "C",
}


class BootstrapError(ValueError):
    """Fixed, non-sensitive bootstrap failure."""


def _owner_uid() -> int:
    return ROOT_UID


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


def _identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
    )


def _canonical_bytes(value: Any) -> bytes:
    try:
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
    except (TypeError, ValueError, UnicodeError) as exc:
        raise BootstrapError("bootstrap_public_export") from exc


def _validate_parent_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid not in {ROOT_UID, _owner_uid()}
        or stat.S_IMODE(row.st_mode) & 0o022
    ):
        raise BootstrapError("bootstrap_parent_identity")


def _validate_parent_chain(target: Path, *, include_target: bool = False) -> None:
    if (
        not isinstance(target, Path)
        or not target.is_absolute()
        or any(part in {".", ".."} for part in target.parts)
    ):
        raise BootstrapError("bootstrap_path")
    current = Path(target.anchor)
    components = target.parts[1:] if include_target else target.parts[1:-1]
    for component in (None, *components):
        if component is not None:
            current = current / component
        try:
            row = current.lstat()
        except OSError as exc:
            raise BootstrapError("bootstrap_parent_identity") from exc
        _validate_parent_row(row)


def _validate_regular_file(
    row: os.stat_result,
    *,
    mode: int,
    allow_empty: bool,
) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != mode
        or row.st_uid != _owner_uid()
        or row.st_nlink != 1
        or (not allow_empty and not 1 <= row.st_size <= MAX_TOOL_BYTES)
    ):
        raise BootstrapError("bootstrap_file_identity")


def _validate_directory(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != _owner_uid()
    ):
        raise BootstrapError("bootstrap_directory_identity")


def _read_stable_binary(path: Path, expected_sha256: str) -> None:
    _validate_parent_chain(path)
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != ROOT_UID
            or stat.S_IMODE(before.st_mode) != 0o755
            or before.st_nlink < 1
        ):
            raise BootstrapError("bootstrap_tool_identity")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_TOOL_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65536, MAX_TOOL_BYTES + 1 - size),
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
        raise BootstrapError("bootstrap_tool_identity") from exc
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= MAX_TOOL_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise BootstrapError("bootstrap_tool_binding")


def _validate_system_interpreter() -> None:
    if Path(sys.executable).absolute() != SYSTEM_PYTHON_ENTRY:
        raise BootstrapError("bootstrap_interpreter_path")
    _read_stable_binary(
        SYSTEM_PYTHON_LAUNCHER,
        EXPECTED_SYSTEM_PYTHON_LAUNCHER_SHA256,
    )
    _validate_parent_chain(SYSTEM_PYTHON_ENTRY)
    try:
        before = SYSTEM_PYTHON_ENTRY.lstat()
        target = os.readlink(SYSTEM_PYTHON_ENTRY)
        after = SYSTEM_PYTHON_ENTRY.lstat()
        resolved = SYSTEM_PYTHON_ENTRY.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError("bootstrap_interpreter_entry") from exc
    if (
        not stat.S_ISLNK(before.st_mode)
        or before.st_uid != ROOT_UID
        or target != EXPECTED_SYSTEM_PYTHON_ENTRY_TARGET
        or _stable(before) != _stable(after)
        or resolved != SYSTEM_PYTHON_EXECUTABLE
    ):
        raise BootstrapError("bootstrap_interpreter_entry")
    _read_stable_binary(
        SYSTEM_PYTHON_EXECUTABLE,
        EXPECTED_SYSTEM_PYTHON_EXECUTABLE_SHA256,
    )


def _validate_execution_boundary() -> None:
    if (
        sys.flags.ignore_environment != 1
        or sys.flags.no_site != 1
        or sys.flags.dont_write_bytecode != 1
    ):
        raise BootstrapError("bootstrap_execution_flags")
    _validate_system_interpreter()
    if Path(__file__).absolute() != EXECUTION_DIRECTORY / BOOTSTRAP_FILE:
        raise BootstrapError("bootstrap_execution_path")
    _validate_parent_chain(EXECUTION_DIRECTORY, include_target=True)
    try:
        before = EXECUTION_DIRECTORY.lstat()
        _validate_directory(before)
        descriptor = os.open(
            EXECUTION_DIRECTORY,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            _validate_directory(opened)
            names_before = os.listdir(descriptor)
            if set(names_before) != set(EXECUTION_INVENTORY):
                raise BootstrapError("bootstrap_execution_inventory")
            source_before = os.stat(
                BOOTSTRAP_FILE,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            _validate_regular_file(source_before, mode=0o600, allow_empty=False)
            source_fd = os.open(
                BOOTSTRAP_FILE,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=descriptor,
            )
            try:
                source_opened = os.fstat(source_fd)
                _validate_regular_file(
                    source_opened,
                    mode=0o600,
                    allow_empty=False,
                )
            finally:
                os.close(source_fd)
            source_after = os.stat(
                BOOTSTRAP_FILE,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            names_after = os.listdir(descriptor)
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = EXECUTION_DIRECTORY.lstat()
    except OSError as exc:
        raise BootstrapError("bootstrap_execution_identity") from exc
    if (
        _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
        or _stable(source_before) != _stable(source_opened)
        or _stable(source_opened) != _stable(source_after)
        or set(names_after) != set(names_before)
    ):
        raise BootstrapError("bootstrap_execution_changed")
    _read_stable_binary(OPENSSL, EXPECTED_OPENSSL_SHA256)


def _run_openssl(
    arguments: list[str],
    *,
    stdin: Any,
    stdout: Any,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    try:
        before = OPENSSL.lstat()
        result = subprocess.run(
            [str(OPENSSL), *arguments],
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            env=MINIMAL_ENV,
            timeout=timeout,
            check=False,
            close_fds=True,
        )
        after = OPENSSL.lstat()
    except (OSError, subprocess.SubprocessError) as exc:
        raise BootstrapError("bootstrap_openssl") from exc
    if result.returncode != 0 or _stable(before) != _stable(after):
        raise BootstrapError("bootstrap_openssl")
    return result


def _der_tlv(raw: bytes, offset: int) -> tuple[int, bytes, int]:
    if type(raw) is not bytes or not 0 <= offset < len(raw):
        raise BootstrapError("bootstrap_public_key_der")
    tag = raw[offset]
    offset += 1
    if offset >= len(raw):
        raise BootstrapError("bootstrap_public_key_der")
    first = raw[offset]
    offset += 1
    if first & 0x80:
        count = first & 0x7F
        if (
            count == 0
            or count > 4
            or offset + count > len(raw)
            or raw[offset] == 0
        ):
            raise BootstrapError("bootstrap_public_key_der")
        length = int.from_bytes(raw[offset : offset + count], "big")
        offset += count
        if length < 128:
            raise BootstrapError("bootstrap_public_key_der")
    else:
        length = first
    end = offset + length
    if end > len(raw):
        raise BootstrapError("bootstrap_public_key_der")
    return tag, raw[offset:end], end


def _positive_der_integer(raw: bytes) -> int:
    if (
        not raw
        or raw[0] & 0x80
        or (len(raw) > 1 and raw[0] == 0 and raw[1] & 0x80 == 0)
    ):
        raise BootstrapError("bootstrap_public_key_integer")
    return int.from_bytes(raw, "big")


def _validate_rsa3072_der(der: bytes) -> None:
    outer_tag, outer, outer_end = _der_tlv(der, 0)
    algorithm_tag, algorithm, algorithm_end = _der_tlv(outer, 0)
    oid_tag, oid, oid_end = _der_tlv(algorithm, 0)
    null_tag, null_value, null_end = _der_tlv(algorithm, oid_end)
    bit_tag, bit_value, bit_end = _der_tlv(outer, algorithm_end)
    if (
        outer_tag != 0x30
        or outer_end != len(der)
        or algorithm_tag != 0x30
        or oid_tag != 0x06
        or oid != bytes.fromhex("2a864886f70d010101")
        or null_tag != 0x05
        or null_value != b""
        or null_end != len(algorithm)
        or bit_tag != 0x03
        or bit_end != len(outer)
        or not bit_value
        or bit_value[0] != 0
    ):
        raise BootstrapError("bootstrap_public_key_algorithm")
    rsa_der = bit_value[1:]
    rsa_tag, rsa_value, rsa_end = _der_tlv(rsa_der, 0)
    modulus_tag, modulus_raw, modulus_end = _der_tlv(rsa_value, 0)
    exponent_tag, exponent_raw, exponent_end = _der_tlv(rsa_value, modulus_end)
    modulus = _positive_der_integer(modulus_raw)
    exponent = _positive_der_integer(exponent_raw)
    if not (
        rsa_tag == 0x30
        and rsa_end == len(rsa_der)
        and modulus_tag == 0x02
        and exponent_tag == 0x02
        and exponent_end == len(rsa_value)
        and modulus.bit_length() == 3072
        and 3 <= exponent <= 0xFFFFFFFF
        and exponent % 2 == 1
    ):
        raise BootstrapError("bootstrap_public_key_rsa3072")


def _openssl_public_bytes(arguments: list[str], raw: bytes) -> bytes:
    try:
        before = OPENSSL.lstat()
        result = subprocess.run(
            [str(OPENSSL), *arguments],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=MINIMAL_ENV,
            timeout=PUBLIC_KEY_TIMEOUT_SECONDS,
            check=False,
            close_fds=True,
        )
        after = OPENSSL.lstat()
    except (OSError, subprocess.SubprocessError) as exc:
        raise BootstrapError("bootstrap_public_key_openssl") from exc
    if (
        result.returncode != 0
        or not 1 <= len(result.stdout) <= MAX_PUBLIC_KEY_BYTES
        or _stable(before) != _stable(after)
    ):
        raise BootstrapError("bootstrap_public_key_openssl")
    return result.stdout


def _public_identity_from_bytes(public_key: bytes) -> tuple[bytes, str]:
    if (
        type(public_key) is not bytes
        or not 1 <= len(public_key) <= MAX_PUBLIC_KEY_BYTES
    ):
        raise BootstrapError("bootstrap_public_key_size")
    canonical = _openssl_public_bytes(
        ["pkey", "-pubin", "-pubout"],
        public_key,
    )
    if canonical != public_key:
        raise BootstrapError("bootstrap_public_key_canonical")
    der = _openssl_public_bytes(
        ["pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
        public_key,
    )
    _validate_rsa3072_der(der)
    return canonical, hashlib.sha256(der).hexdigest()


def _generate_private_key(descriptor: int) -> None:
    result = _run_openssl(
        ["genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"],
        stdin=subprocess.DEVNULL,
        stdout=descriptor,
        timeout=PRIVATE_KEY_TIMEOUT_SECONDS,
    )
    if result.stdout is not None:
        raise BootstrapError("bootstrap_private_key_output")


def _export_public_key(descriptor: int) -> bytes:
    result = _run_openssl(
        ["pkey", "-pubout"],
        stdin=descriptor,
        stdout=subprocess.PIPE,
        timeout=PUBLIC_KEY_TIMEOUT_SECONDS,
    )
    if type(result.stdout) is not bytes or not result.stdout:
        raise BootstrapError("bootstrap_public_key_export")
    return result.stdout


def _open_custody(
    *,
    noteai_directory: Path,
    execution_directory: Path,
    custody_directory: Path,
) -> tuple[int, int]:
    if (
        execution_directory.parent != noteai_directory
        or custody_directory.parent != noteai_directory
        or execution_directory == custody_directory
        or execution_directory.name in {"", ".", ".."}
        or custody_directory.name in {"", ".", ".."}
    ):
        raise BootstrapError("bootstrap_directory_partition")
    _validate_parent_chain(noteai_directory, include_target=True)
    try:
        noteai_before = noteai_directory.lstat()
        _validate_directory(noteai_before)
        noteai_fd = os.open(
            noteai_directory,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        noteai_opened = os.fstat(noteai_fd)
        _validate_directory(noteai_opened)
        names = os.listdir(noteai_fd)
        if set(names) != {execution_directory.name}:
            raise BootstrapError("bootstrap_noteai_inventory")
        os.mkdir(custody_directory.name, 0o700, dir_fd=noteai_fd)
        os.fsync(noteai_fd)
        custody_fd = os.open(
            custody_directory.name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=noteai_fd,
        )
        os.fchmod(custody_fd, 0o700)
        custody_row = os.fstat(custody_fd)
        _validate_directory(custody_row)
        if os.listdir(custody_fd):
            raise BootstrapError("bootstrap_custody_inventory")
        noteai_after = os.fstat(noteai_fd)
        _validate_directory(noteai_after)
    except BaseException:
        if "custody_fd" in locals():
            os.close(custody_fd)
        if "noteai_fd" in locals():
            os.close(noteai_fd)
        raise
    if not (
        _stable(noteai_before) == _stable(noteai_opened)
        and _identity(noteai_opened) == _identity(noteai_after)
    ):
        os.close(custody_fd)
        os.close(noteai_fd)
        raise BootstrapError("bootstrap_parent_changed")
    return noteai_fd, custody_fd


def _create_role_file(custody_fd: int, name: str) -> None:
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=custody_fd,
        )
    except OSError as exc:
        raise BootstrapError("bootstrap_private_key_exclusive") from exc
    try:
        os.fchmod(descriptor, 0o600)
        _generate_private_key(descriptor)
        os.fsync(descriptor)
        row = os.fstat(descriptor)
        _validate_regular_file(row, mode=0o600, allow_empty=False)
    finally:
        os.close(descriptor)


def _read_public_from_role(custody_fd: int, name: str) -> tuple[bytes, str]:
    before = os.stat(name, dir_fd=custody_fd, follow_symlinks=False)
    _validate_regular_file(before, mode=0o600, allow_empty=False)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=custody_fd,
        )
    except OSError as exc:
        raise BootstrapError("bootstrap_private_key_open") from exc
    try:
        opened = os.fstat(descriptor)
        _validate_regular_file(opened, mode=0o600, allow_empty=False)
        public_key = _export_public_key(descriptor)
        closed = os.fstat(descriptor)
        _validate_regular_file(closed, mode=0o600, allow_empty=False)
    finally:
        os.close(descriptor)
    after = os.stat(name, dir_fd=custody_fd, follow_symlinks=False)
    _validate_regular_file(after, mode=0o600, allow_empty=False)
    if not (
        _stable(before) == _stable(opened)
        and _stable(opened) == _stable(closed)
        and _stable(closed) == _stable(after)
    ):
        raise BootstrapError("bootstrap_private_key_changed")
    return _public_identity_from_bytes(public_key)


def bootstrap_keys(
    *,
    noteai_directory: Path = NOTEAI_DIRECTORY,
    execution_directory: Path = EXECUTION_DIRECTORY,
    custody_directory: Path = CUSTODY_DIRECTORY,
) -> dict[str, Any]:
    """Create exactly three role keys and return only public material."""
    if os.geteuid() != _owner_uid():
        raise BootstrapError("bootstrap_root_required")
    if _owner_uid() == ROOT_UID:
        if (
            noteai_directory != NOTEAI_DIRECTORY
            or execution_directory != EXECUTION_DIRECTORY
            or custody_directory != CUSTODY_DIRECTORY
        ):
            raise BootstrapError("bootstrap_production_path")
        # The mutation primitive owns this check so importing the module cannot
        # bypass the fixed root-owned source/interpreter/tool boundary.
        _validate_execution_boundary()
    old_umask = os.umask(0o077)
    noteai_fd = -1
    custody_fd = -1
    try:
        noteai_fd, custody_fd = _open_custody(
            noteai_directory=noteai_directory,
            execution_directory=execution_directory,
            custody_directory=custody_directory,
        )
        for role in ROLE_FILES:
            _create_role_file(custody_fd, ROLE_FILES[role])
            os.fsync(custody_fd)
        if set(os.listdir(custody_fd)) != set(ROLE_FILES.values()):
            raise BootstrapError("bootstrap_custody_inventory")
        generated_rows = {
            name: os.stat(name, dir_fd=custody_fd, follow_symlinks=False)
            for name in ROLE_FILES.values()
        }
        for row in generated_rows.values():
            _validate_regular_file(row, mode=0o600, allow_empty=False)
        public_keys: dict[str, str] = {}
        public_hashes: dict[str, str] = {}
        spki_hashes: dict[str, str] = {}
        for role, name in ROLE_FILES.items():
            public_key, spki_hash = _read_public_from_role(custody_fd, name)
            try:
                public_text = public_key.decode("ascii")
            except UnicodeError as exc:
                raise BootstrapError("bootstrap_public_key_encoding") from exc
            public_keys[role] = public_text
            public_hashes[role] = hashlib.sha256(public_key).hexdigest()
            spki_hashes[role] = spki_hash
        if len(set(spki_hashes.values())) != len(ROLE_FILES):
            raise BootstrapError("bootstrap_public_keys_not_distinct")
        os.fsync(custody_fd)
        os.fsync(noteai_fd)
        final_names = os.listdir(custody_fd)
        final_rows = {
            name: os.stat(name, dir_fd=custody_fd, follow_symlinks=False)
            for name in ROLE_FILES.values()
        }
        for row in final_rows.values():
            _validate_regular_file(row, mode=0o600, allow_empty=False)
        if (
            set(final_names) != set(ROLE_FILES.values())
            or any(
                _stable(generated_rows[name]) != _stable(final_rows[name])
                for name in ROLE_FILES.values()
            )
        ):
            raise BootstrapError("bootstrap_custody_changed")
        return {
            "schema": PUBLIC_EXPORT_SCHEMA,
            "task_id": TASK_ID,
            "authority_epoch_id": AUTHORITY_EPOCH_ID,
            "status": "THREE_RSA3072_KEYS_CREATED_PUBLIC_KEYS_EXPORTED",
            "public_keys": public_keys,
            "public_key_sha256": public_hashes,
            "public_key_spki_sha256": spki_hashes,
            "private_key_generation_count": 3,
            "private_key_python_read_count": 0,
            "private_key_output_count": 0,
            "public_key_export_count": 3,
            "custody_inventory_count": 3,
            "automatic_retry_count": 0,
            "residue_cleanup_count": 0,
            "cloud_call_count": 0,
            "database_connection_count": 0,
            "journal_write_count": 0,
            "authorizes_new_action": False,
            "readiness_credit_added": False,
        }
    finally:
        if custody_fd >= 0:
            os.close(custody_fd)
        if noteai_fd >= 0:
            os.close(noteai_fd)
        os.umask(old_umask)


def main(
    argv: Optional[list[str]] = None,
    *,
    stdout: Optional[BinaryIO] = None,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    output = sys.stdout.buffer if stdout is None else stdout
    if arguments != [EXECUTION_FLAG]:
        raise BootstrapError("bootstrap_arguments")
    if output.isatty():
        raise BootstrapError("bootstrap_tty_output")
    if os.geteuid() != ROOT_UID:
        raise BootstrapError("bootstrap_root_required")
    result = bootstrap_keys()
    output.write(_canonical_bytes(result))
    output.flush()
    return 0


def _entrypoint() -> int:
    try:
        return main()
    except BaseException as exc:
        reason = str(exc) if isinstance(exc, BootstrapError) else "bootstrap_internal"
        try:
            sys.stderr.write(
                json.dumps(
                    {
                        "schema": PUBLIC_EXPORT_SCHEMA,
                        "status": "BLOCKED_RESIDUE_REVIEW_REQUIRED",
                        "reason": reason,
                        "automatic_retry_allowed": False,
                        "cleanup_authorized": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                + "\n"
            )
            sys.stderr.flush()
        except BaseException:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(_entrypoint())


__all__ = [
    "BOOTSTRAP_FILE",
    "BootstrapError",
    "CUSTODY_DIRECTORY",
    "EXECUTION_DIRECTORY",
    "EXECUTION_FLAG",
    "PUBLIC_EXPORT_SCHEMA",
    "ROLE_FILES",
    "bootstrap_keys",
    "main",
]
