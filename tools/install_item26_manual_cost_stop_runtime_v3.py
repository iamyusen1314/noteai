#!/usr/bin/env python3
"""Install the exact Item 26 root-v2 and receipt-v3 runtime inventory.

The default scaffold is inert and rejects before filesystem or Git I/O.  Once
the public root is finalized, production execution is permitted only from the
fixed root-owned staging inventory with ``/usr/bin/python3 -E -S -B``.  The
repository is then only a read-only source of exact Git objects.  This is a
root-custody bootstrap boundary, not self-attestation by a user-owned script.
The installer never reads or writes a private key and has no cloud or database
capability.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Optional

import verify_item26_manual_cost_stop_authority_v2 as authority


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_DIRECTORY = authority.AUTHORITY_DIRECTORY
RUNTIME_DIRECTORY = authority.RUNTIME_DIRECTORY
JOURNAL_DIRECTORY = authority.JOURNAL_DIRECTORY
CUSTODY_DIRECTORY = authority.CUSTODY_DIRECTORY
CUSTODY_ROLE_FILES = (
    "provider-private-key.pem",
    "confirmation-private-key.pem",
    "local-ci-observation-private-key.pem",
)
ROOT_UID = 0
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
HEX40 = re.compile(r"^[0-9a-f]{40}$")
INSTALLER_REF = "tools/install_item26_manual_cost_stop_runtime_v3.py"
# Creating this directory is intentionally out of scope.  The authorized
# operator must use system ``git show``/``install``/``cmp`` to place the exact
# signed-control installer and authority blobs here as root, then invoke this
# file with ``/usr/bin/python3 -E -S -B``.  Running it from the repository is
# always rejected.
EXECUTION_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v2-installer"
)
EXECUTION_INVENTORY = (
    Path(INSTALLER_REF).name,
    Path(authority.VERIFIER_REF).name,
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


class InstallError(ValueError):
    """Fixed non-sensitive installation failure."""


class FixedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise InstallError("installer_arguments")


def _file_owner_uid() -> int:
    return ROOT_UID


def _execution_owner_uid() -> int:
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


def _directory_partition(directories: tuple[Path, ...]) -> None:
    if (
        any(
            not isinstance(path, Path)
            or not path.is_absolute()
            or any(part in {".", ".."} for part in path.parts)
            for path in directories
        )
        or len(set(directories)) != len(directories)
        or any(
            first in second.parents or second in first.parents
            for index, first in enumerate(directories)
            for second in directories[index + 1 :]
        )
    ):
        raise InstallError("installer_directory_partition")


def _validate_parent_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != _file_owner_uid()
        or stat.S_IMODE(row.st_mode) & 0o022
    ):
        raise InstallError("installer_parent_identity")


def _validate_parent_chain(target: Path) -> None:
    current = Path(target.anchor)
    try:
        _validate_parent_row(current.lstat())
    except OSError as exc:
        raise InstallError("installer_parent_identity") from exc
    for component in target.parts[1:-1]:
        current = current / component
        try:
            row = current.lstat()
        except OSError as exc:
            raise InstallError("installer_parent_identity") from exc
        _validate_parent_row(row)


def _open_absent_target_parent(target: Path) -> tuple[int, os.stat_result]:
    _validate_parent_chain(target)
    if target.name in {"", ".", ".."} or Path(target.name).name != target.name:
        raise InstallError("installer_target_name")
    try:
        before = target.parent.lstat()
        _validate_parent_row(before)
        descriptor = os.open(
            target.parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        _validate_parent_row(opened)
        if _stable(before) != _stable(opened):
            raise InstallError("installer_parent_changed")
        try:
            os.stat(target.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise InstallError("installer_target_not_new")
    except BaseException:
        if "descriptor" in locals():
            os.close(descriptor)
        raise
    return descriptor, opened


def _validate_source_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != _execution_owner_uid()
        or row.st_nlink != 1
    ):
        raise InstallError("installer_loaded_source_identity")


def _read_stable_source(path: Path) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise InstallError("installer_loaded_source_path")
    try:
        before = path.lstat()
        _validate_source_row(before)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            _validate_source_row(opened)
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
            _validate_source_row(closed)
        finally:
            os.close(descriptor)
        after = path.lstat()
        _validate_source_row(after)
    except OSError as exc:
        raise InstallError("installer_loaded_source_identity") from exc
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= authority.MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise InstallError("installer_loaded_source_changed")
    return raw


def _validate_execution_parent_chain(directory: Path) -> None:
    current = Path(directory.anchor)
    for component in (None, *directory.parts[1:]):
        if component is not None:
            current = current / component
        try:
            row = current.lstat()
        except OSError as exc:
            raise InstallError("installer_execution_parent_identity") from exc
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != _execution_owner_uid()
            or (
                current == directory
                and stat.S_IMODE(row.st_mode) != 0o700
            )
            or (
                current != directory
                and stat.S_IMODE(row.st_mode) & 0o022
            )
        ):
            raise InstallError("installer_execution_parent_identity")


def _validate_system_parent_chain(path: Path) -> None:
    current = Path(path.anchor)
    for component in (None, *path.parts[1:-1]):
        if component is not None:
            current = current / component
        try:
            row = current.lstat()
        except OSError as exc:
            raise InstallError("installer_interpreter_parent_identity") from exc
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != ROOT_UID
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise InstallError("installer_interpreter_parent_identity")


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
            raise InstallError("installer_interpreter_identity")
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
        raise InstallError("installer_interpreter_identity") from exc
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= authority.MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise InstallError("installer_interpreter_binding")


def _validate_system_interpreter() -> None:
    observed = Path(sys.executable).absolute()
    if observed != SYSTEM_PYTHON_ENTRY:
        raise InstallError("installer_interpreter_path")
    _validate_system_binary(
        SYSTEM_PYTHON_LAUNCHER,
        EXPECTED_SYSTEM_PYTHON_LAUNCHER_SHA256,
    )
    _validate_system_parent_chain(SYSTEM_PYTHON_ENTRY)
    try:
        before = SYSTEM_PYTHON_ENTRY.lstat()
        link_target = os.readlink(SYSTEM_PYTHON_ENTRY)
        after = SYSTEM_PYTHON_ENTRY.lstat()
        resolved = SYSTEM_PYTHON_ENTRY.resolve(strict=True)
    except OSError as exc:
        raise InstallError("installer_interpreter_entry") from exc
    if (
        not stat.S_ISLNK(before.st_mode)
        or before.st_uid != ROOT_UID
        or link_target != EXPECTED_SYSTEM_PYTHON_ENTRY_TARGET
        or _stable(before) != _stable(after)
        or resolved != SYSTEM_PYTHON_EXECUTABLE
    ):
        raise InstallError("installer_interpreter_entry")
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
        raise InstallError("installer_execution_flags")
    _validate_system_interpreter()


def _validate_execution_directory_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != _execution_owner_uid()
    ):
        raise InstallError("installer_execution_identity")


def _validate_execution_boundary() -> dict[str, bytes]:
    _validate_execution_flags()
    installer_path = Path(__file__).absolute()
    authority_path = Path(getattr(authority, "__file__", "")).absolute()
    expected_paths = {
        INSTALLER_REF: EXECUTION_DIRECTORY / Path(INSTALLER_REF).name,
        authority.VERIFIER_REF: (
            EXECUTION_DIRECTORY / Path(authority.VERIFIER_REF).name
        ),
    }
    if (
        installer_path != expected_paths[INSTALLER_REF]
        or authority_path != expected_paths[authority.VERIFIER_REF]
        or not EXECUTION_DIRECTORY.is_absolute()
    ):
        raise InstallError("installer_execution_path")
    _validate_execution_parent_chain(EXECUTION_DIRECTORY)
    try:
        before = EXECUTION_DIRECTORY.lstat()
        _validate_execution_directory_row(before)
        descriptor = os.open(
            EXECUTION_DIRECTORY,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            _validate_execution_directory_row(opened)
            names_before = os.listdir(descriptor)
            if (
                _stable(before) != _stable(opened)
                or len(names_before) != len(EXECUTION_INVENTORY)
                or set(names_before) != set(EXECUTION_INVENTORY)
            ):
                raise InstallError("installer_execution_inventory")
            material = {
                ref: _read_stable_source(path)
                for ref, path in expected_paths.items()
            }
            names_after = os.listdir(descriptor)
            closed = os.fstat(descriptor)
            _validate_execution_directory_row(closed)
        finally:
            os.close(descriptor)
        after = EXECUTION_DIRECTORY.lstat()
        _validate_execution_directory_row(after)
    except OSError as exc:
        raise InstallError("installer_execution_identity") from exc
    if (
        len(names_after) != len(names_before)
        or set(names_after) != set(names_before)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise InstallError("installer_execution_changed")
    return material


def _validate_custody_metadata(custody_directory: Path) -> None:
    """Prove the three root-custody files exist without reading key bytes."""

    if (
        not isinstance(custody_directory, Path)
        or not custody_directory.is_absolute()
        or (
            _file_owner_uid() == ROOT_UID
            and custody_directory != CUSTODY_DIRECTORY
        )
    ):
        raise InstallError("installer_custody_path")
    _validate_parent_chain(custody_directory)
    try:
        before = custody_directory.lstat()
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != _file_owner_uid()
        ):
            raise InstallError("installer_custody_identity")
        descriptor = os.open(
            custody_directory,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            names_before = os.listdir(descriptor)
            if (
                _stable(before) != _stable(opened)
                or len(names_before) != len(CUSTODY_ROLE_FILES)
                or set(names_before) != set(CUSTODY_ROLE_FILES)
            ):
                raise InstallError("installer_custody_inventory")
            rows_before = {
                name: os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                for name in CUSTODY_ROLE_FILES
            }
            for row in rows_before.values():
                if (
                    not stat.S_ISREG(row.st_mode)
                    or stat.S_ISLNK(row.st_mode)
                    or stat.S_IMODE(row.st_mode) != 0o600
                    or row.st_uid != _file_owner_uid()
                    or row.st_nlink != 1
                    or not 1 <= row.st_size <= authority.MAX_BYTES
                ):
                    raise InstallError("installer_custody_file_identity")
            rows_after = {
                name: os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                for name in CUSTODY_ROLE_FILES
            }
            names_after = os.listdir(descriptor)
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = custody_directory.lstat()
    except OSError as exc:
        raise InstallError("installer_custody_identity") from exc
    if (
        len(names_after) != len(names_before)
        or set(names_after) != set(names_before)
        or any(
            _stable(rows_before[name]) != _stable(rows_after[name])
            for name in CUSTODY_ROLE_FILES
        )
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise InstallError("installer_custody_changed")


def _validate_loaded_source_bindings(
    records: dict[str, dict[str, Any]],
    loaded_sources: dict[str, bytes],
    *,
    root: Path,
) -> None:
    authority_installer_ref = getattr(authority, "INSTALLER_REF", None)
    control_refs = getattr(authority, "CONTROL_SOURCE_REFS", ())
    if (
        authority_installer_ref != INSTALLER_REF
        or INSTALLER_REF not in control_refs
        or authority.VERIFIER_REF not in control_refs
        or not isinstance(root, Path)
        or not root.is_absolute()
        or any(part in {".", ".."} for part in root.parts)
    ):
        raise InstallError("installer_control_source_contract")
    if set(loaded_sources) != {INSTALLER_REF, authority.VERIFIER_REF}:
        raise InstallError("installer_loaded_source_contract")
    for ref, raw in loaded_sources.items():
        record = records.get(ref)
        if (
            type(record) is not dict
            or record.get("raw") != raw
            or record.get("file_sha256")
            != hashlib.sha256(raw).hexdigest()
            or record.get("git_blob_sha256")
            != hashlib.sha256(raw).hexdigest()
        ):
            raise InstallError("installer_loaded_source_binding")


def _open_created_directory(parent_fd: int, name: str) -> int:
    descriptor = os.open(
        name,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )
    os.fchmod(descriptor, 0o700)
    row = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != _file_owner_uid()
        or row.st_nlink < 1
    ):
        os.close(descriptor)
        raise InstallError("installer_directory_identity")
    return descriptor


def _validate_installed_file_row(row: os.stat_result) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != _file_owner_uid()
        or row.st_nlink != 1
    ):
        raise InstallError("installer_file_identity")


def _readback_exact(
    directory_fd: int,
    name: str,
    expected: bytes,
    *,
    written_row: Optional[os.stat_result] = None,
) -> None:
    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    _validate_installed_file_row(before)
    reader = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(reader)
        _validate_installed_file_row(opened)
        chunks: list[bytes] = []
        size = 0
        while size <= len(expected):
            chunk = os.read(reader, min(65536, len(expected) + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        closed = os.fstat(reader)
        _validate_installed_file_row(closed)
    finally:
        os.close(reader)
    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    _validate_installed_file_row(after)
    if (
        b"".join(chunks) != expected
        or (written_row is not None and _stable(written_row) != _stable(before))
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise InstallError("installer_file_readback")


def _write_exclusive(directory_fd: int, name: str, raw: bytes) -> None:
    if (
        type(name) is not str
        or Path(name).name != name
        or name in {"", ".", ".."}
        or type(raw) is not bytes
        or not 1 <= len(raw) <= authority.MAX_BYTES
    ):
        raise InstallError("installer_file_input")
    descriptor = os.open(
        name,
        os.O_WRONLY
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
                raise InstallError("installer_file_write")
            offset += written
        os.fsync(descriptor)
        written_row = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    _validate_installed_file_row(written_row)
    if written_row.st_size != len(raw):
        raise InstallError("installer_file_identity")
    _readback_exact(
        directory_fd,
        name,
        raw,
        written_row=written_row,
    )


def _validate_control_lineage(
    control_revision: str,
    *,
    root: Path,
) -> None:
    lineage = (
        (authority.A0_REVISION, authority.A1_REVISION),
        (authority.A1_REVISION, authority.A2_REVISION),
        (authority.A2_REVISION, authority.LEDGER_STOP_REVISION),
        (authority.LEDGER_STOP_REVISION, control_revision),
    )
    if any(
        not authority.revision_is_strict_ancestor(
            earlier,
            later,
            root=root,
        )
        for earlier, later in lineage
    ):
        raise InstallError("installer_control_lineage")


def _validated_git_material(
    *,
    control_revision: str,
    receipt_raw: bytes,
    root: Path,
    loaded_sources: dict[str, bytes],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    if (
        type(receipt_raw) is not bytes
        or not 1 <= len(receipt_raw) <= MAX_RECEIPT_BYTES
        or HEX40.fullmatch(control_revision or "") is None
    ):
        raise InstallError("installer_input")
    refs = (
        authority.PUBLIC_ROOT_REF,
        authority.COLLECTOR_REF,
        authority.EXTRACTOR_REF,
        authority.VERIFIER_REF,
        INSTALLER_REF,
    )
    records = {
        ref: authority._git_blob_record(control_revision, ref, root=root)
        for ref in refs
    }
    root_record = records[authority.PUBLIC_ROOT_REF]
    if (
        root_record["file_sha256"] != authority.EXPECTED_ROOT_SHA
        or root_record["git_blob_sha256"] != authority.EXPECTED_ROOT_SHA
    ):
        raise InstallError("installer_root_git_binding")
    _validate_loaded_source_bindings(
        records,
        loaded_sources,
        root=root,
    )
    root_value, keys = authority._validate_root(
        root_record["raw"],
        expected_hash=authority.EXPECTED_ROOT_SHA,
        root=root,
    )
    _validate_control_lineage(control_revision, root=root)
    authority._validate_ledger_git_bindings(root=root)
    source_hashes = {
        "collector_source_sha256": records[authority.COLLECTOR_REF][
            "file_sha256"
        ],
        "extractor_source_sha256": records[authority.EXTRACTOR_REF][
            "file_sha256"
        ],
        "authority_source_sha256": records[authority.VERIFIER_REF][
            "file_sha256"
        ],
    }
    receipt = authority.validate_runtime_activation_receipt(
        receipt_raw,
        root_value=root_value,
        keys=keys,
        control_revision=control_revision,
        expected_authority_root_file_sha256=authority.EXPECTED_ROOT_SHA,
        expected_source_hashes=source_hashes,
        root=root,
    )
    if (
        receipt.get("authority_epoch_id") != authority.AUTHORITY_EPOCH_ID
        or receipt.get("authority_root_file_sha256")
        != authority.EXPECTED_ROOT_SHA
        or receipt.get("authority_root_git_blob_sha256")
        != authority.EXPECTED_ROOT_SHA
        or receipt.get("control_revision") != control_revision
        or receipt.get("source_file_sha256")
        != {
            authority.COLLECTOR_REF: source_hashes[
                "collector_source_sha256"
            ],
            authority.EXTRACTOR_REF: source_hashes[
                "extractor_source_sha256"
            ],
            authority.VERIFIER_REF: source_hashes[
                "authority_source_sha256"
            ],
        }
        or receipt.get("readback_started") is not False
        or receipt.get("cloud_read_count") != 0
        or receipt.get("cloud_write_count") != 0
        or receipt.get("database_connection_count") != 0
        or receipt.get("journal_write_count") != 0
    ):
        raise InstallError("installer_receipt_binding")
    material = {
        authority.ROOT_FILE: root_record["raw"],
        Path(authority.COLLECTOR_REF).name: records[authority.COLLECTOR_REF][
            "raw"
        ],
        Path(authority.EXTRACTOR_REF).name: records[authority.EXTRACTOR_REF][
            "raw"
        ],
        Path(authority.VERIFIER_REF).name: records[authority.VERIFIER_REF][
            "raw"
        ],
        authority.ACTIVATION_RECEIPT_FILE: receipt_raw,
    }
    return material, receipt


def _rollback(
    *,
    created_files: dict[str, list[str]],
    directory_fds: dict[str, int],
    created_directories: list[str],
    parent_fds: dict[str, int],
    targets: dict[str, Path],
) -> None:
    failed = False
    for label in reversed(tuple(created_files)):
        descriptor = directory_fds.get(label)
        if descriptor is None:
            continue
        for name in reversed(created_files[label]):
            try:
                os.unlink(name, dir_fd=descriptor)
            except FileNotFoundError:
                pass
            except OSError:
                failed = True
    for label, descriptor in tuple(directory_fds.items()):
        try:
            os.close(descriptor)
        except OSError:
            failed = True
        directory_fds.pop(label, None)
    for label in reversed(created_directories):
        try:
            os.rmdir(targets[label].name, dir_fd=parent_fds[label])
        except FileNotFoundError:
            pass
        except OSError:
            failed = True
    for label in reversed(created_directories):
        try:
            os.fsync(parent_fds[label])
        except OSError:
            failed = True
    if failed:
        raise InstallError("installer_rollback_incomplete")


def install_runtime(
    *,
    control_revision: str,
    receipt_raw: bytes,
    root: Path = ROOT,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    runtime_directory: Path = RUNTIME_DIRECTORY,
    journal_directory: Path = JOURNAL_DIRECTORY,
    custody_directory: Path = CUSTODY_DIRECTORY,
) -> dict[str, Any]:
    """Install three new directories with exception rollback and durable sync.

    A process crash can leave only a fsynced subset.  Such residue is never
    resumed, overwritten, or deleted here: the next invocation rejects it as
    ``installer_target_not_new`` so a separately authorized read-only audit
    and cleanup decision can recover safely.  This is deliberately fail-closed,
    not a claim of cross-directory crash atomicity.
    """
    authority._require_finalized()
    if os.geteuid() != ROOT_UID or ROOT_UID != 0:
        raise InstallError("installer_root_required")
    loaded_sources = _validate_execution_boundary()
    directories = (
        authority_directory,
        runtime_directory,
        journal_directory,
        custody_directory,
        EXECUTION_DIRECTORY,
    )
    _directory_partition(directories)
    material, receipt = _validated_git_material(
        control_revision=control_revision,
        receipt_raw=receipt_raw,
        root=root,
        loaded_sources=loaded_sources,
    )
    _validate_custody_metadata(custody_directory)
    targets = {
        "authority": authority_directory,
        "runtime": runtime_directory,
        "journal": journal_directory,
    }
    parent_fds: dict[str, int] = {}
    directory_fds: dict[str, int] = {}
    created_directories: list[str] = []
    created_files = {"authority": [], "runtime": [], "journal": []}
    try:
        target_identities: set[tuple[int, int, str]] = set()
        for label, target in targets.items():
            descriptor, row = _open_absent_target_parent(target)
            parent_fds[label] = descriptor
            identity = (row.st_dev, row.st_ino, target.name)
            if identity in target_identities:
                raise InstallError("installer_directory_partition")
            target_identities.add(identity)
        for label, target in targets.items():
            os.mkdir(target.name, 0o700, dir_fd=parent_fds[label])
            created_directories.append(label)
            directory_fds[label] = _open_created_directory(
                parent_fds[label], target.name
            )
        created_files["authority"].append(authority.ROOT_FILE)
        _write_exclusive(
            directory_fds["authority"],
            authority.ROOT_FILE,
            material[authority.ROOT_FILE],
        )
        runtime_names = (
            Path(authority.COLLECTOR_REF).name,
            Path(authority.EXTRACTOR_REF).name,
            Path(authority.VERIFIER_REF).name,
            authority.ACTIVATION_RECEIPT_FILE,
        )
        for name in runtime_names:
            created_files["runtime"].append(name)
            _write_exclusive(directory_fds["runtime"], name, material[name])
        for descriptor in directory_fds.values():
            os.fsync(descriptor)
        if set(os.listdir(directory_fds["authority"])) != {authority.ROOT_FILE}:
            raise InstallError("installer_authority_inventory")
        if set(os.listdir(directory_fds["runtime"])) != set(runtime_names):
            raise InstallError("installer_runtime_inventory")
        if os.listdir(directory_fds["journal"]):
            raise InstallError("installer_journal_inventory")
        _readback_exact(
            directory_fds["authority"],
            authority.ROOT_FILE,
            material[authority.ROOT_FILE],
        )
        for name in runtime_names:
            _readback_exact(
                directory_fds["runtime"],
                name,
                material[name],
            )
        for label, descriptor in directory_fds.items():
            row = os.fstat(descriptor)
            if (
                stat.S_IMODE(row.st_mode) != 0o700
                or row.st_uid != _file_owner_uid()
            ):
                raise InstallError("installer_final_directory_identity")
        for descriptor in directory_fds.values():
            os.fsync(descriptor)
        for descriptor in parent_fds.values():
            os.fsync(descriptor)
    except BaseException as exc:
        try:
            _rollback(
                created_files=created_files,
                directory_fds=directory_fds,
                created_directories=created_directories,
                parent_fds=parent_fds,
                targets=targets,
            )
        except InstallError as rollback_exc:
            raise rollback_exc from exc
        raise
    finally:
        for descriptor in tuple(directory_fds.values()):
            os.close(descriptor)
        directory_fds.clear()
        for descriptor in tuple(parent_fds.values()):
            os.close(descriptor)
        parent_fds.clear()
    return {
        "status": "ROOT_V2_RUNTIME_V3_INSTALLED",
        "control_revision": control_revision,
        "authority_epoch_id": authority.AUTHORITY_EPOCH_ID,
        "authority_root_file_sha256": authority.EXPECTED_ROOT_SHA,
        "authority_root_git_blob_sha256": receipt[
            "authority_root_git_blob_sha256"
        ],
        "activation_receipt_sha256": receipt[
            "activation_receipt_sha256"
        ],
        "authority_file_count": 1,
        "runtime_file_count": 4,
        "journal_file_count": 0,
        "private_key_read_count": 0,
        "private_key_write_count": 0,
        "cloud_call_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
    }


def _stdin_bytes(stream: Any) -> bytes:
    if stream.isatty():
        raise InstallError("installer_tty_input")
    raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RECEIPT_BYTES:
        raise InstallError("installer_receipt_size")
    return raw


def main(
    argv: Optional[list[str]] = None,
    *,
    stdin: Any = None,
    stdout: Any = None,
) -> int:
    authority._require_finalized()
    _validate_execution_boundary()
    parser = FixedArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--control-revision", required=True)
    parser.add_argument("--repository-root", required=True)
    arguments = parser.parse_args(argv)
    repository_root = Path(arguments.repository_root)
    if (
        not repository_root.is_absolute()
        or any(part in {".", ".."} for part in repository_root.parts)
    ):
        raise InstallError("installer_repository_root")
    input_stream = stdin if stdin is not None else sys.stdin.buffer
    output_stream = stdout if stdout is not None else sys.stdout.buffer
    result = install_runtime(
        control_revision=arguments.control_revision,
        receipt_raw=_stdin_bytes(input_stream),
        root=repository_root,
    )
    output_stream.write(authority.canonical_bytes(result))
    output_stream.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORITY_DIRECTORY",
    "CUSTODY_DIRECTORY",
    "EXECUTION_DIRECTORY",
    "EXECUTION_INVENTORY",
    "InstallError",
    "INSTALLER_REF",
    "JOURNAL_DIRECTORY",
    "RUNTIME_DIRECTORY",
    "install_runtime",
    "main",
]
