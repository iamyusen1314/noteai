#!/usr/bin/env python3
"""Build and sign the Item 26 runtime activation receipt v3.

The public library API remains compatible with callers that already hold key
bytes. The command entry point is a separate root-custody boundary: it must
run from the fixed root-owned signer inventory with ``/usr/bin/python3
-E -S -B``. It validates every public Git/root/source/CI/timeline input
before opening custody, and passes the private key to OpenSSL only as an
``O_NOFOLLOW`` file descriptor. Python never reads or copies that key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Optional

import verify_item26_manual_cost_stop_authority_v2 as authority


ROOT_UID = 0
MAX_REQUEST_BYTES = 4 * 1024 * 1024
SIGN_REQUEST_SCHEMA = (
    "noteai.item26.manual-cost-stop-activation-sign-request.v3"
)
SIGNER_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v2-signer"
)
SIGNER_INVENTORY = (
    Path(authority.RECEIPT_BUILDER_REF).name,
    Path(authority.VERIFIER_REF).name,
)
CUSTODY_DIRECTORY = authority.CUSTODY_DIRECTORY
CUSTODY_ROLE_FILES = (
    "provider-private-key.pem",
    "confirmation-private-key.pem",
    "local-ci-observation-private-key.pem",
)
LOCAL_CI_PRIVATE_KEY_FILE = "local-ci-observation-private-key.pem"
SCRATCH_NAME = ".item26-receipt-v3-signing"
MESSAGE_FILE = "message.bin"
SIGNATURE_FILE = "signature.bin"
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


class SignerError(ValueError):
    """Fixed, non-sensitive signer failure."""


class FixedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise SignerError("receipt_signer_arguments")


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


def _validate_parent_chain(path: Path, code: str) -> None:
    current = Path(path.anchor)
    for component in (None, *path.parts[1:-1]):
        if component is not None:
            current = current / component
        try:
            row = current.lstat()
        except OSError as exc:
            raise SignerError(code) from exc
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != _owner_uid()
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise SignerError(code)


def _validate_public_file_row(row: os.stat_result, code: str) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != _owner_uid()
        or row.st_nlink != 1
    ):
        raise SignerError(code)


def _read_stable_public_file(path: Path) -> bytes:
    try:
        before = path.lstat()
        _validate_public_file_row(before, "receipt_signer_source_identity")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            _validate_public_file_row(
                opened, "receipt_signer_source_identity"
            )
            chunks: list[bytes] = []
            size = 0
            while size <= authority.MAX_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65536, authority.MAX_BYTES + 1 - size),
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
        raise SignerError("receipt_signer_source_identity") from exc
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= authority.MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise SignerError("receipt_signer_source_changed")
    return raw


def _validate_system_parent_chain(path: Path) -> None:
    _validate_parent_chain(path, "receipt_signer_interpreter_parent")


def _validate_system_binary(path: Path, expected_sha256: str) -> None:
    _validate_system_parent_chain(path)
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != ROOT_UID
            or stat.S_IMODE(before.st_mode) != 0o755
            or before.st_nlink < 1
        ):
            raise SignerError("receipt_signer_interpreter_identity")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            size = 0
            while size <= authority.MAX_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65536, authority.MAX_BYTES + 1 - size),
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
        raise SignerError("receipt_signer_interpreter_identity") from exc
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= authority.MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise SignerError("receipt_signer_interpreter_binding")


def _validate_system_interpreter() -> None:
    if Path(sys.executable).absolute() != SYSTEM_PYTHON_ENTRY:
        raise SignerError("receipt_signer_interpreter_path")
    _validate_system_binary(
        SYSTEM_PYTHON_LAUNCHER,
        EXPECTED_SYSTEM_PYTHON_LAUNCHER_SHA256,
    )
    _validate_system_parent_chain(SYSTEM_PYTHON_ENTRY)
    try:
        before = SYSTEM_PYTHON_ENTRY.lstat()
        target = os.readlink(SYSTEM_PYTHON_ENTRY)
        after = SYSTEM_PYTHON_ENTRY.lstat()
        resolved = SYSTEM_PYTHON_ENTRY.resolve(strict=True)
    except OSError as exc:
        raise SignerError("receipt_signer_interpreter_entry") from exc
    if (
        not stat.S_ISLNK(before.st_mode)
        or before.st_uid != ROOT_UID
        or target != EXPECTED_SYSTEM_PYTHON_ENTRY_TARGET
        or _stable(before) != _stable(after)
        or resolved != SYSTEM_PYTHON_EXECUTABLE
    ):
        raise SignerError("receipt_signer_interpreter_entry")
    _validate_system_binary(
        SYSTEM_PYTHON_EXECUTABLE,
        EXPECTED_SYSTEM_PYTHON_EXECUTABLE_SHA256,
    )


def _validate_execution_flags() -> None:
    if (
        sys.flags.ignore_environment != 1
        or sys.flags.no_site != 1
        or sys.flags.dont_write_bytecode != 1
    ):
        raise SignerError("receipt_signer_execution_flags")
    _validate_system_interpreter()


def _validate_signer_directory_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != _owner_uid()
    ):
        raise SignerError("receipt_signer_execution_identity")


def _validate_execution_boundary() -> dict[str, bytes]:
    _validate_execution_flags()
    builder_path = Path(__file__).absolute()
    authority_path = Path(getattr(authority, "__file__", "")).absolute()
    expected_paths = {
        authority.RECEIPT_BUILDER_REF: (
            SIGNER_DIRECTORY / Path(authority.RECEIPT_BUILDER_REF).name
        ),
        authority.VERIFIER_REF: (
            SIGNER_DIRECTORY / Path(authority.VERIFIER_REF).name
        ),
    }
    if (
        builder_path != expected_paths[authority.RECEIPT_BUILDER_REF]
        or authority_path != expected_paths[authority.VERIFIER_REF]
    ):
        raise SignerError("receipt_signer_execution_path")
    _validate_parent_chain(
        SIGNER_DIRECTORY, "receipt_signer_execution_parent"
    )
    try:
        before = SIGNER_DIRECTORY.lstat()
        _validate_signer_directory_row(before)
        descriptor = os.open(
            SIGNER_DIRECTORY,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            _validate_signer_directory_row(opened)
            names_before = os.listdir(descriptor)
            if (
                _stable(before) != _stable(opened)
                or len(names_before) != len(SIGNER_INVENTORY)
                or set(names_before) != set(SIGNER_INVENTORY)
            ):
                raise SignerError("receipt_signer_execution_inventory")
            material = {
                ref: _read_stable_public_file(path)
                for ref, path in expected_paths.items()
            }
            names_after = os.listdir(descriptor)
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = SIGNER_DIRECTORY.lstat()
        _validate_signer_directory_row(after)
    except OSError as exc:
        raise SignerError("receipt_signer_execution_identity") from exc
    if (
        set(names_after) != set(names_before)
        or len(names_after) != len(names_before)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise SignerError("receipt_signer_execution_changed")
    return material


def _validate_scratch(directory: Path) -> None:
    """Legacy library scratch validation; CLI never stores a key here."""
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise ValueError("manual activation receipt v3 scratch absolute")
    row = directory.lstat()
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != os.geteuid()
    ):
        raise ValueError("manual activation receipt v3 scratch identity")


def _write_exclusive(path: Path, raw: bytes) -> None:
    """Legacy library writer retained for API compatibility."""
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise ValueError("manual activation receipt v3 scratch write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    row = path.lstat()
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != os.geteuid()
        or row.st_nlink != 1
    ):
        raise ValueError("manual activation receipt v3 scratch file")


def _private_public_key(private_key_pem: bytes) -> bytes:
    if type(private_key_pem) is not bytes or not private_key_pem:
        raise ValueError("manual activation receipt v3 private key bytes")
    return authority._openssl(["pkey", "-pubout"], stdin=private_key_pem)


def _sign(
    message: bytes,
    private_key_pem: bytes,
    *,
    scratch_directory: Path,
) -> bytes:
    """Compatibility signer for callers that already supplied key bytes."""
    _validate_scratch(scratch_directory)
    before = authority._tool_identity(authority.OPENSSL)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".item26-receipt-v3-sign-",
            dir=scratch_directory,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            message_path = base / MESSAGE_FILE
            signature_path = base / SIGNATURE_FILE
            _write_exclusive(message_path, message)
            _write_exclusive(signature_path, b"")
            result = subprocess.run(
                [
                    str(authority.OPENSSL),
                    "dgst",
                    "-sha256",
                    "-sign",
                    "/dev/stdin",
                    "-out",
                    str(signature_path),
                    str(message_path),
                ],
                input=private_key_pem,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                timeout=15,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("manual activation receipt v3 signature")
            signature = signature_path.read_bytes()
            signature_row = signature_path.lstat()
            if (
                len(signature) != 384
                or stat.S_IMODE(signature_row.st_mode) != 0o600
                or signature_row.st_nlink != 1
            ):
                raise ValueError("manual activation receipt v3 signature shape")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("manual activation receipt v3 signing tool") from exc
    if authority._stable(authority.OPENSSL.lstat()) != authority._stable(before):
        raise ValueError("manual activation receipt v3 signing tool identity")
    return signature


def _source_bindings(value: Any) -> dict[str, dict[str, str]]:
    if type(value) is not dict or set(value) != set(authority.CONTROL_SOURCE_REFS):
        raise ValueError("manual activation receipt v3 source bindings")
    result: dict[str, dict[str, str]] = {}
    for ref in authority.CONTROL_SOURCE_REFS:
        row = value[ref]
        if (
            type(row) is not dict
            or set(row) != {"git_blob_oid", "file_sha256"}
            or authority.HEX40.fullmatch(row.get("git_blob_oid", "")) is None
            or not authority._hex64(row.get("file_sha256"))
        ):
            raise ValueError("manual activation receipt v3 source binding row")
        result[ref] = dict(row)
    return result


def _unsigned_receipt(
    *,
    root_value: dict[str, Any],
    sources: dict[str, dict[str, str]],
    control_revision: str,
    control_ci: dict[str, dict[str, Any]],
    activated_at_utc: str,
) -> dict[str, Any]:
    root_hash = authority.EXPECTED_ROOT_SHA
    root_binding = sources[authority.PUBLIC_ROOT_REF]
    payload = {
        "schema": authority.ACTIVATION_RECEIPT_SCHEMA,
        "task_id": authority.TASK_ID,
        "historical_operation_id": authority.OPERATION_ID,
        "authority_generation_id": authority.AUTHORITY_GENERATION_ID,
        "authority_epoch_id": authority.AUTHORITY_EPOCH_ID,
        "status": "A3_ROOT_V2_ATTEMPT1_DUAL_CI_SUCCESS_ACTIVATED",
        "repository": authority.REPOSITORY,
        "source_ref": authority.SOURCE_REF,
        "ledger_stop_revision": authority.LEDGER_STOP_REVISION,
        "bootstrap_ledger_acceptance_revision": (
            authority.BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION
        ),
        "historical_checkpoints": {
            "a0_terminal": authority.EXPECTED_A0_TERMINAL,
            "a1_terminal": authority.EXPECTED_A1_TERMINAL,
            "a2_terminal": authority.EXPECTED_A2_TERMINAL,
            "ledger_stop_terminal": authority.EXPECTED_LEDGER_STOP_TERMINAL,
            "rejected_bootstrap_source_terminal": (
                authority.EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL
            ),
            "helper_source_terminal": authority.EXPECTED_HELPER_SOURCE_TERMINAL,
            "bootstrap_ledger_terminal": (
                authority.EXPECTED_BOOTSTRAP_LEDGER_TERMINAL
            ),
            "rejected_root_activation_terminal": (
                authority.EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL
            ),
        },
        "historical_source_blobs": authority.HISTORICAL_SOURCE_BLOBS,
        "control_revision": control_revision,
        "control_ci": control_ci,
        "control_source_blobs": sources,
        "activated_at_utc": activated_at_utc,
        "readback_started": False,
        "cloud_read_count": 0,
        "cloud_write_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
        "journal_write_count": 0,
        "fallback": {
            "authority_v1_used": False,
            "collector_v1_used": False,
            "receipt_v2_used": False,
        },
        "item26_status": "unverified",
        "readiness_credit_added": False,
    }
    key_row = root_value["authorities"]["local_ci_observation"]
    return {
        "schema": authority.ACTIVATION_RECEIPT_ENVELOPE_SCHEMA,
        "domain": authority.RECEIPT_SIGNATURE_DOMAIN_TEXT,
        "authority_role": "local_ci_observation",
        "issuer": key_row["issuer"],
        "audience": key_row["audience"],
        "authority_epoch_id": authority.AUTHORITY_EPOCH_ID,
        "authority_generation_id": authority.AUTHORITY_GENERATION_ID,
        "root_git_binding": {
            "repository": authority.REPOSITORY,
            "source_ref": authority.SOURCE_REF,
            "control_revision": control_revision,
            "public_root_ref": authority.PUBLIC_ROOT_REF,
            "git_blob_oid": root_binding["git_blob_oid"],
            "git_blob_sha256": root_hash,
            "file_sha256": root_hash,
        },
        "payload": payload,
    }


def _complete_receipt(unsigned: dict[str, Any], signature: bytes) -> bytes:
    if type(signature) is not bytes or len(signature) != 384:
        raise ValueError("manual activation receipt v3 signature shape")
    return authority.canonical_bytes(
        {
            **unsigned,
            "signature_base64": base64.b64encode(signature).decode("ascii"),
        }
    )


def _prepare_unsigned_receipt(
    *,
    root_raw: bytes,
    control_revision: str,
    control_ci: dict[str, dict[str, Any]],
    control_source_blobs: dict[str, dict[str, str]],
    activated_at_utc: str,
    root: Path,
) -> tuple[dict[str, Any], dict[str, tuple[bytes, str]]]:
    root_value, root_keys, sources = (
        authority.validate_activation_receipt_unsigned_inputs(
            root_raw=root_raw,
            control_revision=control_revision,
            control_ci=control_ci,
            control_source_blobs=control_source_blobs,
            activated_at_utc=activated_at_utc,
            root=root,
        )
    )
    return (
        _unsigned_receipt(
            root_value=root_value,
            sources=sources,
            control_revision=control_revision,
            control_ci=control_ci,
            activated_at_utc=activated_at_utc,
        ),
        root_keys,
    )


def build_activation_receipt(
    *,
    root_raw: bytes,
    local_ci_observation_private_key_pem: bytes,
    control_revision: str,
    control_ci: dict[str, dict[str, Any]],
    control_source_blobs: dict[str, dict[str, str]],
    activated_at_utc: str,
    scratch_directory: Path,
    root: Path = authority.ROOT,
) -> bytes:
    """Return one canonical receipt; retain the existing library signature."""
    unsigned, root_keys = _prepare_unsigned_receipt(
        root_raw=root_raw,
        control_revision=control_revision,
        control_ci=control_ci,
        control_source_blobs=control_source_blobs,
        activated_at_utc=activated_at_utc,
        root=root,
    )
    private_public = _private_public_key(local_ci_observation_private_key_pem)
    if private_public != root_keys["local_ci_observation"][0]:
        raise ValueError("manual activation receipt v3 signing key identity")
    message = authority.RECEIPT_SIGNATURE_DOMAIN + authority.canonical_bytes(
        unsigned
    )
    signature = _sign(
        message,
        local_ci_observation_private_key_pem,
        scratch_directory=scratch_directory,
    )
    return _complete_receipt(unsigned, signature)


def _stdin_bytes(stream: Any) -> bytes:
    if stream.isatty():
        raise SignerError("receipt_signer_tty_input")
    raw = stream.read(MAX_REQUEST_BYTES + 1)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_REQUEST_BYTES:
        raise SignerError("receipt_signer_request_size")
    return raw


def _parse_sign_request(raw: bytes) -> dict[str, Any]:
    try:
        value = authority._parse(raw, "manual activation receipt sign request")
    except ValueError as exc:
        raise SignerError("receipt_signer_request_invalid") from exc
    if (
        set(value)
        != {
            "schema",
            "control_ci",
            "control_source_blobs",
            "activated_at_utc",
        }
        or value.get("schema") != SIGN_REQUEST_SCHEMA
        or type(value.get("control_ci")) is not dict
        or type(value.get("control_source_blobs")) is not dict
        or type(value.get("activated_at_utc")) is not str
    ):
        raise SignerError("receipt_signer_request_contract")
    return value


def _validate_repository_root(path: str) -> Path:
    root = Path(path)
    if (
        not root.is_absolute()
        or any(part in {".", ".."} for part in root.parts)
    ):
        raise SignerError("receipt_signer_repository_root")
    return root


def _prepare_cli_receipt(
    *,
    request_raw: bytes,
    control_revision: str,
    repository_root: Path,
    staged_sources: dict[str, bytes],
) -> tuple[dict[str, Any], bytes, bytes]:
    """Finish every public precondition before the caller touches custody."""
    request = _parse_sign_request(request_raw)
    if authority.HEX40.fullmatch(control_revision or "") is None:
        raise SignerError("receipt_signer_control_revision")
    expected_staged = {
        authority.RECEIPT_BUILDER_REF,
        authority.VERIFIER_REF,
    }
    if set(staged_sources) != expected_staged:
        raise SignerError("receipt_signer_staged_source_contract")
    records = {
        ref: authority._git_blob_record(
            control_revision, ref, root=repository_root
        )
        for ref in (
            authority.RECEIPT_BUILDER_REF,
            authority.VERIFIER_REF,
            authority.PUBLIC_ROOT_REF,
        )
    }
    for ref in expected_staged:
        raw = staged_sources[ref]
        if (
            type(raw) is not bytes
            or records[ref]["raw"] != raw
            or records[ref]["file_sha256"] != hashlib.sha256(raw).hexdigest()
            or records[ref]["git_blob_sha256"]
            != hashlib.sha256(raw).hexdigest()
        ):
            raise SignerError("receipt_signer_staged_source_drift")
    try:
        unsigned, root_keys = _prepare_unsigned_receipt(
            root_raw=records[authority.PUBLIC_ROOT_REF]["raw"],
            control_revision=control_revision,
            control_ci=request["control_ci"],
            control_source_blobs=request["control_source_blobs"],
            activated_at_utc=request["activated_at_utc"],
            root=repository_root,
        )
    except ValueError as exc:
        raise SignerError("receipt_signer_public_prevalidation") from exc
    message = authority.RECEIPT_SIGNATURE_DOMAIN + authority.canonical_bytes(
        unsigned
    )
    return unsigned, message, root_keys["local_ci_observation"][0]


def _validate_custody_directory_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != _owner_uid()
    ):
        raise SignerError("receipt_signer_custody_identity")


def _validate_private_key_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != _owner_uid()
        or row.st_nlink != 1
        or not 1 <= row.st_size <= authority.MAX_BYTES
    ):
        raise SignerError("receipt_signer_custody_file_identity")


def _open_validated_custody() -> tuple[int, dict[str, os.stat_result]]:
    if CUSTODY_DIRECTORY != authority.CUSTODY_DIRECTORY:
        raise SignerError("receipt_signer_custody_path")
    _validate_parent_chain(CUSTODY_DIRECTORY, "receipt_signer_custody_parent")
    try:
        before = CUSTODY_DIRECTORY.lstat()
        _validate_custody_directory_row(before)
        descriptor = os.open(
            CUSTODY_DIRECTORY,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        _validate_custody_directory_row(opened)
        names = os.listdir(descriptor)
        if (
            _stable(before) != _stable(opened)
            or len(names) != len(CUSTODY_ROLE_FILES)
            or set(names) != set(CUSTODY_ROLE_FILES)
        ):
            raise SignerError("receipt_signer_custody_inventory")
        rows = {
            name: os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            for name in CUSTODY_ROLE_FILES
        }
        for row in rows.values():
            _validate_private_key_row(row)
    except BaseException:
        if "descriptor" in locals():
            os.close(descriptor)
        raise
    return descriptor, rows


def _write_exclusive_at(directory_fd: int, name: str, raw: bytes) -> int:
    descriptor = os.open(
        name,
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise SignerError("receipt_signer_scratch_write")
            offset += written
        os.fsync(descriptor)
        row = os.fstat(descriptor)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_IMODE(row.st_mode) != 0o600
            or row.st_uid != _owner_uid()
            or row.st_nlink != 1
        ):
            raise SignerError("receipt_signer_scratch_file_identity")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _run_openssl_fd(
    arguments: list[str],
    *,
    pass_fds: tuple[int, ...],
    stdout: Any,
) -> subprocess.CompletedProcess[bytes]:
    before = authority._tool_identity(authority.OPENSSL)
    try:
        result = subprocess.run(
            [str(authority.OPENSSL), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            close_fds=True,
            pass_fds=pass_fds,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SignerError("receipt_signer_openssl") from exc
    if authority._stable(authority.OPENSSL.lstat()) != authority._stable(before):
        raise SignerError("receipt_signer_openssl_changed")
    return result


def _public_from_private_fd(key_fd: int) -> bytes:
    os.lseek(key_fd, 0, os.SEEK_SET)
    result = _run_openssl_fd(
        ["pkey", "-in", f"/dev/fd/{key_fd}", "-pubout"],
        pass_fds=(key_fd,),
        stdout=subprocess.PIPE,
    )
    if result.returncode != 0 or not result.stdout:
        raise SignerError("receipt_signer_key_identity")
    return result.stdout


def _read_signature_fd(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    size = 0
    while size <= 384:
        chunk = os.read(descriptor, 385 - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    signature = b"".join(chunks)
    if len(signature) != 384:
        raise SignerError("receipt_signer_signature_shape")
    return signature


def _sign_from_custody(message: bytes, expected_public_key: bytes) -> bytes:
    """Sign once by descriptor; a failed attempt deliberately leaves residue."""
    custody_fd, original_rows = _open_validated_custody()
    key_fd: Optional[int] = None
    scratch_fd: Optional[int] = None
    message_fd: Optional[int] = None
    signature_fd: Optional[int] = None
    signature = b""
    try:
        os.mkdir(SCRATCH_NAME, 0o700, dir_fd=custody_fd)
        scratch_fd = os.open(
            SCRATCH_NAME,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=custody_fd,
        )
        _validate_custody_directory_row(os.fstat(scratch_fd))
        message_fd = _write_exclusive_at(scratch_fd, MESSAGE_FILE, message)
        signature_fd = _write_exclusive_at(scratch_fd, SIGNATURE_FILE, b"")
        if set(os.listdir(scratch_fd)) != {MESSAGE_FILE, SIGNATURE_FILE}:
            raise SignerError("receipt_signer_scratch_inventory")
        key_fd = os.open(
            LOCAL_CI_PRIVATE_KEY_FILE,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=custody_fd,
        )
        key_opened = os.fstat(key_fd)
        _validate_private_key_row(key_opened)
        if (
            _stable(key_opened)
            != _stable(original_rows[LOCAL_CI_PRIVATE_KEY_FILE])
            or _public_from_private_fd(key_fd) != expected_public_key
        ):
            raise SignerError("receipt_signer_key_identity")
        os.lseek(key_fd, 0, os.SEEK_SET)
        os.lseek(message_fd, 0, os.SEEK_SET)
        os.lseek(signature_fd, 0, os.SEEK_SET)
        result = _run_openssl_fd(
            [
                "dgst",
                "-sha256",
                "-sign",
                f"/dev/fd/{key_fd}",
                "-out",
                f"/dev/fd/{signature_fd}",
                f"/dev/fd/{message_fd}",
            ],
            pass_fds=(key_fd, message_fd, signature_fd),
            stdout=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise SignerError("receipt_signer_signature")
        signature = _read_signature_fd(signature_fd)
        if set(os.listdir(scratch_fd)) != {MESSAGE_FILE, SIGNATURE_FILE}:
            raise SignerError("receipt_signer_scratch_inventory")
        for descriptor in (message_fd, signature_fd):
            row = os.fstat(descriptor)
            if (
                not stat.S_ISREG(row.st_mode)
                or stat.S_IMODE(row.st_mode) != 0o600
                or row.st_uid != _owner_uid()
                or row.st_nlink != 1
            ):
                raise SignerError("receipt_signer_scratch_file_identity")
        key_after = os.fstat(key_fd)
        current_rows = {
            name: os.stat(name, dir_fd=custody_fd, follow_symlinks=False)
            for name in CUSTODY_ROLE_FILES
        }
        if (
            _stable(key_opened) != _stable(key_after)
            or any(
                _stable(original_rows[name]) != _stable(current_rows[name])
                for name in CUSTODY_ROLE_FILES
            )
        ):
            raise SignerError("receipt_signer_custody_changed")
        os.close(signature_fd)
        signature_fd = None
        os.close(message_fd)
        message_fd = None
        os.unlink(MESSAGE_FILE, dir_fd=scratch_fd)
        os.unlink(SIGNATURE_FILE, dir_fd=scratch_fd)
        os.fsync(scratch_fd)
        os.close(scratch_fd)
        scratch_fd = None
        os.rmdir(SCRATCH_NAME, dir_fd=custody_fd)
        os.fsync(custody_fd)
        names = os.listdir(custody_fd)
        if (
            len(names) != len(CUSTODY_ROLE_FILES)
            or set(names) != set(CUSTODY_ROLE_FILES)
        ):
            raise SignerError("receipt_signer_custody_changed")
    except OSError as exc:
        raise SignerError("receipt_signer_custody_operation") from exc
    finally:
        for descriptor in (signature_fd, message_fd, scratch_fd, key_fd):
            if descriptor is not None:
                os.close(descriptor)
        os.close(custody_fd)
    return signature


def main(
    argv: Optional[list[str]] = None,
    *,
    stdin: Any = None,
    stdout: Any = None,
) -> int:
    authority._require_finalized()
    if os.geteuid() != ROOT_UID or ROOT_UID != 0:
        raise SignerError("receipt_signer_root_required")
    staged_sources = _validate_execution_boundary()
    parser = FixedArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--control-revision", required=True)
    parser.add_argument("--repository-root", required=True)
    arguments = parser.parse_args(argv)
    repository_root = _validate_repository_root(arguments.repository_root)
    input_stream = stdin if stdin is not None else sys.stdin.buffer
    output_stream = stdout if stdout is not None else sys.stdout.buffer
    unsigned, message, expected_public_key = _prepare_cli_receipt(
        request_raw=_stdin_bytes(input_stream),
        control_revision=arguments.control_revision,
        repository_root=repository_root,
        staged_sources=staged_sources,
    )
    signature = _sign_from_custody(message, expected_public_key)
    receipt = _complete_receipt(unsigned, signature)
    output_stream.write(receipt)
    output_stream.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CUSTODY_DIRECTORY",
    "SIGNER_DIRECTORY",
    "SIGNER_INVENTORY",
    "SIGN_REQUEST_SCHEMA",
    "SignerError",
    "build_activation_receipt",
    "main",
]
