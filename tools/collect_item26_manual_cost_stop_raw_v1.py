#!/usr/bin/env python3
"""Offline, root-only importer for Item 26 post-action readback bytes.

This program never authenticates to Alibaba Cloud and never sends a request.
An operator first records the exact logical read-only request with ``begin``,
executes that request in an already authenticated official transport, and then
feeds the unmodified JSON response body to ``finish``.  ``finalize`` constructs
the two canonical capture envelopes, validates them with the frozen extractor,
and promotes them without replacing an existing authority artifact.

Raw identifiers, provider responses, browser state, credentials, signed URLs,
headers and cookies are never written to stdout or stderr.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Optional

sys.dont_write_bytecode = True

import extract_item26_manual_cost_stop_raw_v1 as extractor
import verify_item26_manual_cost_stop_authority_v1 as authority


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path("/Users/openclaw/Desktop/noteai")
TASK_ID = extractor.TASK_ID
OPERATION_ID = extractor.OPERATION_ID
M0_ANCHOR_REVISION = extractor.M0_ANCHOR_REVISION
COLLECTOR_REF = "tools/collect_item26_manual_cost_stop_raw_v1.py"
EXTRACTOR_REF = "tools/extract_item26_manual_cost_stop_raw_v1.py"
AUTHORITY_REF = "tools/verify_item26_manual_cost_stop_authority_v1.py"

AUTHORITY_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v1"
)
RUNTIME_DIRECTORY = authority.RUNTIME_DIRECTORY
JOURNAL_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v1-journal"
)
ROOT_FILE = "authority-root-v1.json"
ACTIVATION_RECEIPT_FILE = authority.ACTIVATION_RECEIPT_FILE
PROVIDER_FILE = "provider-raw-v1.json"
ACTIONTRAIL_FILE = "actiontrail-raw-v1.json"
PROVIDER_STAGE_FILE = PROVIDER_FILE + ".pending"
ACTIONTRAIL_STAGE_FILE = ACTIONTRAIL_FILE + ".pending"
STAGE_WRITE_FILES = {
    "." + PROVIDER_STAGE_FILE + ".writing",
    "." + ACTIONTRAIL_STAGE_FILE + ".writing",
}

ROOT_UID = 0
MAX_INPUT_BYTES = extractor.MAX_BODY_BYTES
MAX_RECORDS = extractor.MAX_RECORDS
MAX_RECORD_SECONDS = 15 * 60
MIN_REMAINING_CAPTURE_RECORD_BYTES = 4096
HEX40 = re.compile(r"^[0-9a-f]{40}$")
EVENT_NAME = re.compile(r"^[0-9]{6}-(begin|finish)\.json$")
EVENT_WRITE_NAME = re.compile(
    r"^\.(?P<target>[0-9]{6}-(begin|finish)\.json)\."
    r"(?P<recorded_at_hex>[0-9a-f]{40,60})\.writing$"
)
JOURNAL_SCHEMA = "noteai.item26.manual-cost-stop-import-journal.v1"
COLLECTOR_STATUS_SCHEMA = "noteai.item26.manual-cost-stop-collector-status.v1"
UNKNOWN_MARKER_SCHEMA = (
    "noteai.item26.manual-cost-stop-offline-response-unknown.v1"
)
ACTIVATION_RECEIPT_SCHEMA = authority.ACTIVATION_RECEIPT_SCHEMA
CAPTURE_TRANSPORT = "OFFLINE_OFFICIAL_RESPONSE_IMPORT_V1"
SOURCE_FILES = {
    Path(COLLECTOR_REF).name,
    Path(EXTRACTOR_REF).name,
    Path(AUTHORITY_REF).name,
}
TOOL_INVENTORY = SOURCE_FILES | {ACTIVATION_RECEIPT_FILE}
EXPECTED_A0_TERMINAL = authority.EXPECTED_A0_TERMINAL

COST_SLOT = "cost_stop_rds_write_lookup_page"
CREATE_SLOT = "clone_create_lookup_page"
CLONE_SLOT = "fresh_clone_inventory"
SOURCE_SLOT = "fresh_source_inventory"
BILLING_SLOT = "historical_billing_snapshot"
SLOTS = (COST_SLOT, CREATE_SLOT, CLONE_SLOT, SOURCE_SLOT, BILLING_SLOT)
ACTIONTRAIL_SLOTS = {COST_SLOT, CREATE_SLOT}
PROVIDER_SLOTS = {CLONE_SLOT, SOURCE_SLOT, BILLING_SLOT}
OPERATIONS = {
    COST_SLOT: ("LookupEvents", "2020-07-06"),
    CREATE_SLOT: ("LookupEvents", "2020-07-06"),
    CLONE_SLOT: ("DescribeDBInstances", "2014-08-15"),
    SOURCE_SLOT: ("DescribeDBInstances", "2014-08-15"),
    BILLING_SLOT: ("QueryInstanceBill", "2017-12-14"),
}
UNKNOWN_REASONS = frozenset({
    "TRANSPORT_TIMEOUT",
    "NO_RESPONSE_BODY",
    "OFFICIAL_RESPONSE_EXPORT_FAILED",
    "RESPONSE_BODY_OVERSIZE",
    "SENSITIVE_WRAPPER_DETECTED",
})
SENSITIVE_INGRESS_KEYS = frozenset({
    "authorization",
    "browserstate",
    "cookie",
    "cookies",
    "credentials",
    "har",
    "headers",
    "password",
    "presignedurl",
    "privatekey",
    "requestheaders",
    "responseheaders",
    "securitytoken",
    "sessiontoken",
    "setcookie",
    "signature",
    "signedurl",
    "accesskeysecret",
})
SENSITIVE_INGRESS_VALUE = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    rb"|\"(?:authorization|browserstate|cookie|cookies|credentials|har|"
    rb"headers|password|presignedurl|privatekey|requestheaders|"
    rb"responseheaders|securitytoken|sessiontoken|set-cookie|signature|"
    rb"signedurl|accesskeysecret)\"\s*:"
    rb"|(?:authorization|cookie|set-cookie)\s*:"
    rb"|[?&](?:Signature|AccessKeyId|SecurityToken)=",
    re.IGNORECASE,
)


class CollectorError(ValueError):
    """A fixed, non-sensitive collector failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _finite_json_float(raw: str, code: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise CollectorError(code)
    return value


def _bounded_json_int(raw: str, code: str) -> int:
    digits = raw[1:] if raw.startswith("-") else raw
    if not digits or len(digits) > extractor.MAX_JSON_INTEGER_DIGITS:
        raise CollectorError(code)
    try:
        return int(raw)
    except ValueError as exc:
        raise CollectorError(code) from exc


def _bounded_json_depth(raw: bytes, code: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for item in raw:
        if in_string:
            if escaped:
                escaped = False
            elif item == 0x5C:
                escaped = True
            elif item == 0x22:
                in_string = False
            continue
        if item == 0x22:
            in_string = True
        elif item in {0x5B, 0x7B}:
            depth += 1
            if depth > extractor.MAX_JSON_NESTING_DEPTH:
                raise CollectorError(code)
        elif item in {0x5D, 0x7D}:
            depth -= 1


class FixedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise CollectorError("arguments")


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _utc(value: Any, code: str) -> datetime:
    if type(value) is not str or extractor.RFC3339.fullmatch(value) is None:
        raise CollectorError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CollectorError(code) from exc
    if parsed.tzinfo != timezone.utc:
        raise CollectorError(code)
    return parsed


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


def _validate_directory(row: os.stat_result, owner_uid: int) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != owner_uid
    ):
        raise CollectorError("directory_identity")


def _validate_file(
    row: os.stat_result,
    owner_uid: int,
    *,
    allowed_links: frozenset[int] = frozenset({1}),
) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != owner_uid
        or row.st_nlink not in allowed_links
    ):
        raise CollectorError("file_identity")


def _open_directory(path: Path, owner_uid: int) -> tuple[int, os.stat_result]:
    if not path.is_absolute():
        raise CollectorError("directory_absolute")
    try:
        _validate_root_owned_parent_chain(path, owner_uid)
        before = path.lstat()
        _validate_directory(before, owner_uid)
        descriptor = os.open(
            path,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        _validate_directory(opened, owner_uid)
        if _stable(before) != _stable(opened):
            os.close(descriptor)
            raise CollectorError("directory_unstable")
        return descriptor, opened
    except CollectorError:
        raise
    except OSError as exc:
        raise CollectorError("directory_open") from exc


def _read_file(
    directory_fd: int,
    name: str,
    owner_uid: int,
    *,
    allowed_links: frozenset[int] = frozenset({1}),
) -> bytes:
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _validate_file(before, owner_uid, allowed_links=allowed_links)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            _validate_file(opened, owner_uid, allowed_links=allowed_links)
            raw = b""
            while len(raw) <= extractor.MAX_CAPTURE_BYTES:
                chunk = os.read(
                    descriptor,
                    min(
                        65536,
                        extractor.MAX_CAPTURE_BYTES + 1 - len(raw),
                    ),
                )
                if not chunk:
                    break
                raw += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except CollectorError:
        raise
    except OSError as exc:
        raise CollectorError("file_read") from exc
    if (
        not 1 <= len(raw) <= extractor.MAX_CAPTURE_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise CollectorError("file_unstable")
    return raw


def _read_partial_file(
    directory_fd: int,
    name: str,
    owner_uid: int,
) -> bytes:
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _validate_file(before, owner_uid)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            _validate_file(opened, owner_uid)
            raw = b""
            while len(raw) <= extractor.MAX_CAPTURE_BYTES:
                chunk = os.read(
                    descriptor,
                    min(
                        65536,
                        extractor.MAX_CAPTURE_BYTES + 1 - len(raw),
                    ),
                )
                if not chunk:
                    break
                raw += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except CollectorError:
        raise
    except OSError as exc:
        raise CollectorError("partial_read") from exc
    if (
        len(raw) > extractor.MAX_CAPTURE_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise CollectorError("partial_unstable")
    return raw


def _event_recorded_at(raw: bytes) -> str:
    match = re.search(rb'"recorded_at_utc":"([^"]+)"', raw)
    if match is None:
        raise CollectorError("write_event_time")
    try:
        value = match.group(1).decode("ascii")
    except UnicodeError as exc:
        raise CollectorError("write_event_time") from exc
    _utc(value, "write_event_time")
    return value


def _event_writing_target(name: str) -> Optional[str]:
    match = EVENT_WRITE_NAME.fullmatch(name)
    return None if match is None else match.group("target")


def _event_writing_recorded_at(name: str) -> str:
    match = EVENT_WRITE_NAME.fullmatch(name)
    if match is None:
        raise CollectorError("write_event_name")
    try:
        value = bytes.fromhex(match.group("recorded_at_hex")).decode(
            "ascii"
        )
    except (UnicodeError, ValueError) as exc:
        raise CollectorError("write_event_name") from exc
    _utc(value, "write_event_name")
    return value


def _event_writing_name(name: str, recorded_at: str) -> str:
    if EVENT_NAME.fullmatch(name) is None:
        raise CollectorError("write_event_name")
    _utc(recorded_at, "write_event_name")
    return f".{name}.{recorded_at.encode('ascii').hex()}.writing"


def _event_raw_at_timestamp(
    name: str,
    proposed: bytes,
    recorded_at: str,
) -> bytes:
    if EVENT_NAME.fullmatch(name) is None:
        return proposed
    _bounded_json_depth(proposed, "write_partial_drift")
    try:
        value = json.loads(
            proposed.decode("ascii"),
            parse_float=lambda item: _finite_json_float(
                item, "write_partial_drift"
            ),
            parse_int=lambda item: _bounded_json_int(
                item, "write_partial_drift"
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CollectorError("write_partial_drift")
            ),
        )
    except CollectorError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise CollectorError("write_partial_drift") from exc
    if type(value) is not dict:
        raise CollectorError("write_partial_drift")
    value["recorded_at_utc"] = recorded_at
    candidate = _canonical(value)
    _decode_event(candidate)
    return candidate


def _writing_matches_target(
    writing_files: set[str],
    target_name: str,
) -> bool:
    return (
        len(writing_files) == 1
        and _event_writing_target(next(iter(writing_files))) == target_name
    )


def _write_exclusive(
    directory_fd: int,
    name: str,
    raw: bytes,
    owner_uid: int,
) -> None:
    if not raw or len(raw) > extractor.MAX_CAPTURE_BYTES:
        raise CollectorError("write_size")
    try:
        names = set(os.listdir(directory_fd))
        if EVENT_NAME.fullmatch(name) is not None:
            matching = sorted(
                candidate
                for candidate in names
                if _event_writing_target(candidate) == name
            )
            if len(matching) > 1:
                raise CollectorError("write_recovery_identity")
            if matching:
                temporary_name = matching[0]
                raw = _event_raw_at_timestamp(
                    name,
                    raw,
                    _event_writing_recorded_at(temporary_name),
                )
            else:
                recorded_at = _event_recorded_at(raw)
                temporary_name = _event_writing_name(name, recorded_at)
        else:
            temporary_name = "." + name + ".writing"
        if name in names:
            target_raw = _read_file(
                directory_fd,
                name,
                owner_uid,
                allowed_links=(
                    frozenset({2})
                    if temporary_name in names
                    else frozenset({1})
                ),
            )
            if EVENT_NAME.fullmatch(name) is not None:
                raw = _event_raw_at_timestamp(
                    name,
                    raw,
                    _event_recorded_at(target_raw),
                )
            if temporary_name in names:
                target_row = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                temporary_row = os.stat(
                    temporary_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    (target_row.st_dev, target_row.st_ino)
                    != (temporary_row.st_dev, temporary_row.st_ino)
                    or target_row.st_nlink != 2
                    or temporary_row.st_nlink != 2
                    or target_raw != raw
                ):
                    raise CollectorError("write_recovery_identity")
                os.unlink(temporary_name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            if _read_file(directory_fd, name, owner_uid) != raw:
                raise CollectorError("write_drift")
            return
        if temporary_name not in names:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=directory_fd,
            )
            os.fchmod(descriptor, 0o600)
            if os.fstat(descriptor).st_uid != owner_uid:
                os.close(descriptor)
                raise CollectorError("write_owner")
            os.close(descriptor)
            os.fsync(directory_fd)
        partial = _read_partial_file(
            directory_fd,
            temporary_name,
            owner_uid,
        )
        if len(partial) > len(raw) or not raw.startswith(partial):
            raise CollectorError("write_partial_drift")
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_APPEND
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            _validate_file(opened, owner_uid)
            if opened.st_size != len(partial):
                raise CollectorError("write_partial_drift")
            offset = len(partial)
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                if written <= 0:
                    raise CollectorError("short_write")
                offset += written
            os.fsync(descriptor)
            written_row = os.fstat(descriptor)
            _validate_file(written_row, owner_uid)
            if written_row.st_size != len(raw):
                raise CollectorError("short_write")
        finally:
            os.close(descriptor)
        if _read_file(directory_fd, temporary_name, owner_uid) != raw:
            raise CollectorError("write_drift")
        os.link(
            temporary_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        os.fsync(directory_fd)
        os.unlink(temporary_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        if _read_file(directory_fd, name, owner_uid) != raw:
            raise CollectorError("write_drift")
    except CollectorError:
        raise
    except FileExistsError as exc:
        raise CollectorError("write_exists") from exc
    except OSError as exc:
        raise CollectorError("write_failed") from exc


def _strict_json(raw: bytes, code: str) -> dict[str, Any]:
    if not 1 <= len(raw) <= MAX_INPUT_BYTES or b"\0" in raw:
        raise CollectorError(code + "_shape")
    _bounded_json_depth(raw, code + "_depth")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CollectorError(code + "_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_float=lambda item: _finite_json_float(
                item, code + "_number"
            ),
            parse_int=lambda item: _bounded_json_int(
                item, code + "_number"
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CollectorError(code + "_number")
            ),
        )
    except CollectorError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise CollectorError(code + "_json") from exc
    if type(value) is not dict:
        raise CollectorError(code + "_object")
    return value


def _reject_sensitive_ingress(raw: bytes, value: dict[str, Any]) -> None:
    if SENSITIVE_INGRESS_VALUE.search(raw):
        raise CollectorError("sensitive_ingress")
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > 64:
            raise CollectorError("sensitive_ingress")
        if type(current) is dict:
            for key, item in current.items():
                normalized = re.sub(r"[^a-z0-9]", "", key.lower())
                if normalized in SENSITIVE_INGRESS_KEYS:
                    raise CollectorError("sensitive_ingress")
                stack.append((item, depth + 1))
        elif type(current) is list:
            stack.extend((item, depth + 1) for item in current)
        elif type(current) is str and SENSITIVE_INGRESS_VALUE.search(
            current.encode("utf-8", errors="ignore")
        ):
            raise CollectorError("sensitive_ingress")


def _unknown_marker(reason: str) -> bytes:
    if reason not in UNKNOWN_REASONS:
        raise CollectorError("unknown_reason")
    return _canonical({
        "schema": UNKNOWN_MARKER_SCHEMA,
        "reason": reason,
        "response_bytes_retained": False,
        "cloud_request_replay_allowed": False,
    })


def _stdin_bytes(stream: Any) -> bytes:
    raw = stream.read(MAX_INPUT_BYTES + 1)
    if type(raw) is str:
        try:
            raw = raw.encode("utf-8")
        except UnicodeError as exc:
            raise CollectorError("stdin_type") from exc
    if type(raw) is not bytes:
        raise CollectorError("stdin_type")
    if not raw:
        raise CollectorError("stdin_empty")
    if len(raw) > MAX_INPUT_BYTES:
        raise CollectorError("stdin_oversize")
    return raw


def _validate_root_owned_parent_chain(path: Path, owner_uid: int) -> None:
    if not path.is_absolute():
        raise CollectorError("source_parent_absolute")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            row = current.lstat()
        except OSError as exc:
            raise CollectorError("source_parent_stat") from exc
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid not in {ROOT_UID, owner_uid}
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise CollectorError("source_parent_identity")


def _validate_interpreter() -> None:
    flags = sys.flags
    if (
        flags.ignore_environment != 1
        or flags.no_site != 1
        or flags.dont_write_bytecode != 1
        or sys.version_info < (3, 9)
    ):
        raise CollectorError("interpreter_contract")
    executable_entry = Path(sys.executable)
    if not executable_entry.is_absolute() or not Path(__file__).is_absolute():
        raise CollectorError("interpreter_identity")
    try:
        _validate_root_owned_parent_chain(executable_entry.parent, ROOT_UID)
        entry = executable_entry.lstat()
        if (
            not (stat.S_ISREG(entry.st_mode) or stat.S_ISLNK(entry.st_mode))
            or entry.st_uid != ROOT_UID
        ):
            raise CollectorError("interpreter_identity")
        executable = executable_entry.resolve(strict=True)
        _validate_root_owned_parent_chain(executable.parent, ROOT_UID)
        before = executable.lstat()
        descriptor = os.open(
            executable,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = executable.lstat()
    except OSError as exc:
        raise CollectorError("interpreter_identity") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != ROOT_UID
        or stat.S_IMODE(before.st_mode) & 0o022
        or stat.S_IMODE(before.st_mode) & 0o111 == 0
        or before.st_nlink != 1
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise CollectorError("interpreter_identity")


def _source_hashes(owner_uid: Optional[int] = None) -> dict[str, str]:
    collector_path = Path(__file__)
    extractor_path = Path(extractor.__file__)
    authority_path = Path(authority.__file__)
    paths = (collector_path, extractor_path, authority_path)
    if (
        any(not path.is_absolute() for path in paths)
        or collector_path.name != Path(COLLECTOR_REF).name
        or extractor_path.name != Path(EXTRACTOR_REF).name
        or authority_path.name != Path(AUTHORITY_REF).name
        or len({path.parent for path in paths}) != 1
        or (
            owner_uid is not None
            and collector_path.parent != RUNTIME_DIRECTORY
        )
    ):
        raise CollectorError("source_path")
    try:
        if owner_uid is None:
            raw_by_name = {path.name: path.read_bytes() for path in paths}
        else:
            _validate_root_owned_parent_chain(collector_path.parent, owner_uid)
            directory_fd, _row = _open_directory(
                collector_path.parent,
                owner_uid,
            )
            try:
                if set(os.listdir(directory_fd)) != TOOL_INVENTORY:
                    raise CollectorError("source_inventory")
                raw_by_name = {
                    path.name: _read_file(directory_fd, path.name, owner_uid)
                    for path in paths
                }
            finally:
                os.close(directory_fd)
    except OSError as exc:
        raise CollectorError("source_read") from exc
    return {
        "collector_source_sha256": _sha(
            raw_by_name[collector_path.name]
        ),
        "extractor_source_sha256": _sha(
            raw_by_name[extractor_path.name]
        ),
        "authority_source_sha256": _sha(
            raw_by_name[authority_path.name]
        ),
    }


def _validate_activation(
    *,
    control_revision: str,
    authority_directory: Path,
    owner_uid: int,
    require_root_only: bool,
) -> dict[str, Any]:
    try:
        _validate_root_owned_parent_chain(authority_directory, owner_uid)
        directory_fd, _row = _open_directory(authority_directory, owner_uid)
        try:
            inventory = set(os.listdir(directory_fd))
            allowed = {ROOT_FILE, PROVIDER_FILE, ACTIONTRAIL_FILE}
            if (
                ROOT_FILE not in inventory
                or not inventory.issubset(allowed)
                or (require_root_only and inventory != {ROOT_FILE})
            ):
                raise CollectorError("activation_inventory")
            root_raw = _read_file(directory_fd, ROOT_FILE, owner_uid)
        finally:
            os.close(directory_fd)
        value, keys = authority._validate_root(
            root_raw,
            expected_hash=authority.EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
            root=REPOSITORY_ROOT,
        )
    except CollectorError:
        raise
    except (OSError, ValueError) as exc:
        raise CollectorError("activation_root") from exc
    if (
        not authority.revision_is_strict_ancestor(
            extractor.M0_ANCHOR_REVISION,
            authority.A0_PREDECESSOR_REVISION,
            root=REPOSITORY_ROOT,
        )
        or not authority.revision_is_strict_ancestor(
            authority.A0_PREDECESSOR_REVISION,
            control_revision,
            root=REPOSITORY_ROOT,
        )
        or value.get("post_action_readback_only") is not True
        or value.get("authorizes_new_action") is not False
        or value.get("readiness_credit_allowed") is not False
        or len({row[1] for row in keys.values()}) != 3
    ):
        raise CollectorError("activation_root")
    return {
        "authority_root_file_sha256": _sha(root_raw),
        "control_revision": control_revision,
        "post_action_readback_only": True,
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
        "root_value": value,
        "authority_keys": keys,
    }


def _validate_runtime_activation(
    *,
    control_revision: str,
    authority_root_file_sha256: str,
    source_hashes: dict[str, str],
    root_value: dict[str, Any],
    authority_keys: dict[str, tuple[bytes, str]],
    owner_uid: int,
) -> str:
    tool_directory = Path(__file__).parent
    try:
        directory_fd, _row = _open_directory(tool_directory, owner_uid)
        try:
            raw = _read_file(
                directory_fd,
                ACTIVATION_RECEIPT_FILE,
                owner_uid,
            )
        finally:
            os.close(directory_fd)
        binding = authority.validate_runtime_activation_receipt(
            raw,
            root_value=root_value,
            keys=authority_keys,
            control_revision=control_revision,
            expected_authority_root_file_sha256=(
                authority_root_file_sha256
            ),
            expected_source_hashes=source_hashes,
            root=REPOSITORY_ROOT,
        )
        if _utc(
            _utc_now(),
            "activation_host_time",
        ) <= _utc(
            binding["activated_at_utc"],
            "activation_receipt_time",
        ):
            raise CollectorError("activation_receipt_future")
    except CollectorError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise CollectorError("activation_receipt") from exc
    return binding["activation_receipt_sha256"]


def _trusted_runtime(
    *,
    control_revision: str,
    authority_directory: Path,
    owner_uid: int,
    require_root_only: bool,
) -> dict[str, str]:
    root_binding = _validate_activation(
        control_revision=control_revision,
        authority_directory=authority_directory,
        owner_uid=owner_uid,
        require_root_only=require_root_only,
    )
    source_hashes = _source_hashes(owner_uid)
    receipt_sha256 = _validate_runtime_activation(
        control_revision=control_revision,
        authority_root_file_sha256=root_binding[
            "authority_root_file_sha256"
        ],
        source_hashes=source_hashes,
        root_value=root_binding["root_value"],
        authority_keys=root_binding["authority_keys"],
        owner_uid=owner_uid,
    )
    return {
        **source_hashes,
        "activation_receipt_sha256": receipt_sha256,
    }


def _event_file(sequence: int, phase: str) -> str:
    return f"{sequence:06d}-{phase}.json"


def _decode_event(raw: bytes) -> dict[str, Any]:
    value = _strict_json(raw, "journal_event")
    if _canonical(value) != raw:
        raise CollectorError("journal_event_canonical")
    expected = {
        "schema",
        "task_id",
        "operation_id",
        "control_revision",
        "sequence",
        "phase",
        "slot",
        "recorded_at_utc",
        "payload_base64",
        "payload_sha256",
        "collector_source_sha256",
        "extractor_source_sha256",
        "authority_source_sha256",
        "activation_receipt_sha256",
        "outcome",
    }
    if (
        set(value) != expected
        or value.get("schema") != JOURNAL_SCHEMA
        or value.get("task_id") != TASK_ID
        or value.get("operation_id") != OPERATION_ID
        or HEX40.fullmatch(value.get("control_revision", "")) is None
        or type(value.get("sequence")) is not int
        or not 1 <= value["sequence"] <= MAX_RECORDS
        or value.get("phase") not in {"begin", "finish"}
        or value.get("slot") not in SLOTS
        or type(value.get("payload_base64")) is not str
        or type(value.get("payload_sha256")) is not str
        or len(value["payload_sha256"]) != 64
        or type(value.get("collector_source_sha256")) is not str
        or len(value["collector_source_sha256"]) != 64
        or type(value.get("extractor_source_sha256")) is not str
        or len(value["extractor_source_sha256"]) != 64
        or type(value.get("authority_source_sha256")) is not str
        or len(value["authority_source_sha256"]) != 64
        or type(value.get("activation_receipt_sha256")) is not str
        or len(value["activation_receipt_sha256"]) != 64
        or value.get("outcome")
        not in {"REQUEST_FROZEN", "RESPONSE_RECEIVED", "UNKNOWN_INFLIGHT"}
    ):
        raise CollectorError("journal_event_identity")
    _utc(value.get("recorded_at_utc"), "journal_event_time")
    try:
        payload = base64.b64decode(value["payload_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise CollectorError("journal_event_base64") from exc
    if not payload or _sha(payload) != value["payload_sha256"]:
        raise CollectorError("journal_event_payload")
    value["_payload"] = payload
    return value


def _scan_journal(
    directory_fd: int,
    owner_uid: int,
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise CollectorError("journal_inventory") from exc
    for writing_name in tuple(names):
        if (
            EVENT_WRITE_NAME.fullmatch(writing_name) is None
            and writing_name not in STAGE_WRITE_FILES
        ):
            continue
        target_name = _event_writing_target(writing_name)
        if target_name is None:
            target_name = writing_name[1:-8]
        if target_name not in names:
            continue
        try:
            writing_row = os.stat(
                writing_name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            target_row = os.stat(
                target_name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise CollectorError("write_recovery_stat") from exc
        if (
            (writing_row.st_dev, writing_row.st_ino)
            != (target_row.st_dev, target_row.st_ino)
            or writing_row.st_nlink != 2
            or target_row.st_nlink != 2
        ):
            raise CollectorError("write_recovery_identity")
        os.unlink(writing_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        names.remove(writing_name)
    allowed_stage = {PROVIDER_STAGE_FILE, ACTIONTRAIL_STAGE_FILE}
    writing_names = {
        name
        for name in names
        if EVENT_WRITE_NAME.fullmatch(name) is not None
        or name in STAGE_WRITE_FILES
    }
    if any(
        EVENT_NAME.fullmatch(name) is None
        and name not in allowed_stage
        and name not in writing_names
        for name in names
    ):
        raise CollectorError("journal_inventory")
    event_names = sorted(name for name in names if EVENT_NAME.fullmatch(name))
    events: list[dict[str, Any]] = []
    for name in event_names:
        event = _decode_event(_read_file(directory_fd, name, owner_uid))
        expected_name = _event_file(event["sequence"], event["phase"])
        if name != expected_name:
            raise CollectorError("journal_event_name")
        events.append(event)
    expected_phases: list[tuple[int, str]] = []
    for sequence in range(1, (len(events) // 2) + 1):
        expected_phases.extend(((sequence, "begin"), (sequence, "finish")))
    if len(events) % 2:
        expected_phases.append((len(events) // 2 + 1, "begin"))
    actual_phases = [(row["sequence"], row["phase"]) for row in events]
    if actual_phases != expected_phases:
        raise CollectorError("journal_sequence")
    return events, set(names) & allowed_stage, writing_names


def _response_token(
    slot: str,
    response: dict[str, Any],
) -> Optional[str]:
    if slot not in ACTIONTRAIL_SLOTS:
        return None
    expected = {"RequestId", "Events", "StartTime", "EndTime"}
    if not expected.issubset(response):
        raise CollectorError("actiontrail_response")
    if (
        type(response.get("RequestId")) is not str
        or not response["RequestId"]
        or type(response.get("Events")) is not list
        or any(type(row) is not dict for row in response["Events"])
        or type(response.get("StartTime")) is not str
        or type(response.get("EndTime")) is not str
    ):
        raise CollectorError("actiontrail_response")
    token = response.get("NextToken")
    if token in {None, ""}:
        return None
    if type(token) is not str:
        raise CollectorError("actiontrail_response_token")
    return token


def _validate_response_incrementally(
    *,
    events: list[dict[str, Any]],
    begin_row: dict[str, Any],
    response: dict[str, Any],
) -> None:
    request = _strict_json(begin_row["_payload"], "request")
    slot = begin_row["slot"]
    extractor.validate_offline_import_response(slot, request, response)
    token = _response_token(slot, response)
    if slot not in ACTIONTRAIL_SLOTS:
        return
    prior_tokens: set[str] = set()
    prior_request_ids: set[str] = set()
    stream_events: list[dict[str, Any]] = []
    for row in events:
        if row["phase"] != "finish" or row["slot"] not in ACTIONTRAIL_SLOTS:
            continue
        prior_response = _strict_json(row["_payload"], "response")
        prior_token = _response_token(row["slot"], prior_response)
        if row["slot"] == slot and prior_token is not None:
            prior_tokens.add(prior_token)
        request_id = prior_response.get("RequestId")
        if type(request_id) is not str or not request_id:
            raise CollectorError("actiontrail_request_id")
        prior_request_ids.add(request_id)
        if row["slot"] == slot:
            stream_events.extend(prior_response["Events"])
    if token is not None and token in prior_tokens:
        raise CollectorError("actiontrail_token_reuse")
    if response["RequestId"] in prior_request_ids:
        raise CollectorError("actiontrail_request_id_reuse")
    stream_events.extend(response["Events"])
    if token is None:
        names = [row.get("eventName") for row in stream_events]
        expected_names = (
            sorted(extractor.EXPECTED_ACTIONTRAIL_ACTIONS)
            if slot == COST_SLOT
            else ["CloneDBInstance"]
        )
        if sorted(names) != expected_names:
            raise CollectorError("actiontrail_terminal_event_set")
        if slot == COST_SLOT:
            _validate_cost_stop_terminal_stream(stream_events)


def _validate_cost_stop_terminal_stream(
    stream_events: list[dict[str, Any]],
) -> None:
    if len(stream_events) != 2:
        raise CollectorError("actiontrail_terminal_event_set")
    start = _utc(extractor.COST_STOP_LOOKUP_START, "cost_stream_start")
    end = _utc(extractor.COST_STOP_LOOKUP_END, "cost_stream_end")
    rows: list[tuple[str, str, str, datetime]] = []
    for event in stream_events:
        try:
            event_id, event_name, user_identity, event_time, _base = (
                extractor._event_base(
                    event,
                    allowed_names=set(
                        extractor.EXPECTED_ACTIONTRAIL_ACTIONS
                    ),
                    start=start,
                    end=end,
                )
            )
        except (extractor.ExtractionError, KeyError, TypeError) as exc:
            raise CollectorError("actiontrail_terminal_event_set") from exc
        rows.append((
            event_id,
            event_name,
            extractor.sha256(extractor.canonical_bytes(user_identity)),
            event_time,
        ))
    rows.sort(key=lambda row: (row[3], row[1]))
    confirmation = _utc(
        extractor.EXPECTED_HISTORICAL_CONFIRMATION_AT,
        "confirmation_time",
    )
    absence = _utc(extractor.EXPECTED_FINAL_ABSENCE_AT, "absence_time")
    if (
        len({row[0] for row in rows}) != 2
        or len({row[2] for row in rows}) != 1
        or [row[1] for row in rows]
        != list(extractor.EXPECTED_ACTIONTRAIL_ACTIONS)
        or not confirmation <= rows[0][3] < rows[1][3] <= absence
    ):
        raise CollectorError("actiontrail_terminal_event_set")


def _next_slot(
    events: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    if not events:
        return COST_SLOT, None
    if events[-1]["phase"] == "begin":
        return None, None
    if any(row["outcome"] == "UNKNOWN_INFLIGHT" for row in events):
        raise CollectorError("journal_unknown")
    last = events[-1]
    response = _strict_json(last["_payload"], "response")
    token = _response_token(last["slot"], response)
    if last["slot"] == COST_SLOT:
        return (COST_SLOT, token) if token is not None else (CREATE_SLOT, None)
    if last["slot"] == CREATE_SLOT:
        return (CREATE_SLOT, token) if token is not None else (CLONE_SLOT, None)
    if last["slot"] == CLONE_SLOT:
        return SOURCE_SLOT, None
    if last["slot"] == SOURCE_SLOT:
        return BILLING_SLOT, None
    if last["slot"] == BILLING_SLOT:
        return None, None
    raise CollectorError("journal_slot")


def _lookup_request(
    slot: str,
    request: dict[str, Any],
    token: Optional[str],
) -> None:
    if slot == COST_SLOT:
        start = extractor.COST_STOP_LOOKUP_START
        end = extractor.COST_STOP_LOOKUP_END
        attributes = [
            {"Key": "ServiceName", "Value": "Rds"},
            {"Key": "EventRW", "Value": "Write"},
        ]
    elif slot == CREATE_SLOT:
        start = extractor.CLONE_CREATE_LOOKUP_START
        end = extractor.CLONE_CREATE_LOOKUP_END
        attributes = [
            {"Key": "EventName", "Value": "CloneDBInstance"},
            {"Key": "ResourceName", "Value": request.get("LookupAttribute", [{}, {}])[1].get("Value") if type(request.get("LookupAttribute")) is list and len(request["LookupAttribute"]) == 2 and type(request["LookupAttribute"][1]) is dict else None},
        ]
        resource_name = attributes[1]["Value"]
        if (
            type(resource_name) is not str
            or extractor.value_sha256(resource_name)
            != extractor.EXPECTED_OLD_CLONE_SHA256
        ):
            raise CollectorError("clone_create_resource")
    else:
        raise CollectorError("lookup_slot")
    expected = {
        "Action": "LookupEvents",
        "Version": "2020-07-06",
        "Direction": "FORWARD",
        "StartTime": start,
        "EndTime": end,
        "LookupAttribute": attributes,
        "MaxResults": "50",
    }
    if token is not None:
        expected["NextToken"] = token
    if request != expected:
        raise CollectorError("lookup_request")


def _provider_request(slot: str, request: dict[str, Any]) -> None:
    if slot in {CLONE_SLOT, SOURCE_SLOT}:
        expected_identity = (
            extractor.EXPECTED_OLD_CLONE_SHA256
            if slot == CLONE_SLOT
            else extractor.EXPECTED_SOURCE_SHA256
        )
        expected_keys = {
            "Action",
            "Version",
            "RegionId",
            "DBInstanceId",
            "PageNumber",
            "PageSize",
        }
        if (
            set(request) != expected_keys
            or request.get("Action") != "DescribeDBInstances"
            or request.get("Version") != "2014-08-15"
            or request.get("RegionId") != "cn-shenzhen"
            or type(request.get("DBInstanceId")) is not str
            or extractor.value_sha256(request["DBInstanceId"])
            != expected_identity
            or type(request.get("PageNumber")) is not int
            or request["PageNumber"] != 1
            or type(request.get("PageSize")) is not int
            or request["PageSize"] != 100
        ):
            raise CollectorError("describe_request")
        return
    if slot == BILLING_SLOT:
        expected = {
            "Action": "QueryInstanceBill",
            "Version": "2017-12-14",
            "BillingCycle": "2026-08",
            "ProductCode": "rds",
            "SubscriptionType": "PayAsYouGo",
            "IsBillingItem": False,
            "IsHideZeroCharge": False,
            "Granularity": "MONTHLY",
            "PageNum": 1,
            "PageSize": 300,
        }
        if request != expected:
            raise CollectorError("billing_request")
        return
    raise CollectorError("provider_slot")


def _validate_request(
    slot: str,
    request: dict[str, Any],
    token: Optional[str],
) -> None:
    if slot in ACTIONTRAIL_SLOTS:
        _lookup_request(slot, request, token)
    else:
        if token is not None:
            raise CollectorError("provider_token")
        _provider_request(slot, request)


def _event_value(
    *,
    control_revision: str,
    sequence: int,
    phase: str,
    slot: str,
    recorded_at_utc: str,
    payload: bytes,
    source_hashes: dict[str, str],
    outcome: str,
) -> dict[str, Any]:
    return {
        "schema": JOURNAL_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "control_revision": control_revision,
        "sequence": sequence,
        "phase": phase,
        "slot": slot,
        "recorded_at_utc": recorded_at_utc,
        "payload_base64": base64.b64encode(payload).decode("ascii"),
        "payload_sha256": _sha(payload),
        **source_hashes,
        "outcome": outcome,
    }


def begin(
    *,
    control_revision: str,
    slot: str,
    request_raw: bytes,
    journal_directory: Path = JOURNAL_DIRECTORY,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    owner_uid: int = ROOT_UID,
) -> dict[str, Any]:
    if HEX40.fullmatch(control_revision or "") is None or control_revision in {
        M0_ANCHOR_REVISION,
        extractor.LEDGER_CONTEXT_REVISION,
    }:
        raise CollectorError("control_revision")
    source_hashes = _trusted_runtime(
        control_revision=control_revision,
        authority_directory=authority_directory,
        owner_uid=owner_uid,
        require_root_only=True,
    )
    request = _strict_json(request_raw, "request")
    directory_fd, _ = _open_directory(journal_directory, owner_uid)
    try:
        events, stage_files, writing_files = _scan_journal(
            directory_fd,
            owner_uid,
        )
        if stage_files:
            raise CollectorError("journal_finalized")
        if events and events[-1]["phase"] == "begin" and not writing_files:
            prior = events[-1]
            elapsed = _utc(_utc_now(), "begin_retry_time") - _utc(
                prior["recorded_at_utc"],
                "begin_retry_recorded_time",
            )
            if (
                prior["control_revision"] == control_revision
                and prior["slot"] == slot
                and prior["outcome"] == "REQUEST_FROZEN"
                and prior["_payload"] == request_raw
                and all(
                    prior[key] == source_hashes[key]
                    for key in source_hashes
                )
                and 0 <= elapsed.total_seconds() <= MAX_RECORD_SECONDS
            ):
                return {
                    "schema": COLLECTOR_STATUS_SCHEMA,
                    "status": "REQUEST_FROZEN",
                    "sequence": prior["sequence"],
                    "slot": prior["slot"],
                    "request_sha256": prior["payload_sha256"],
                    "cloud_call_count": 0,
                    "raw_value_emitted_count": 0,
                }
            raise CollectorError("request_retry_identity")
        expected_target = _event_file(len(events) // 2 + 1, "begin")
        if writing_files and not _writing_matches_target(
            writing_files,
            expected_target,
        ):
            raise CollectorError("local_write_recovery")
        expected_slot, token = _next_slot(events)
        if expected_slot is None or slot != expected_slot:
            raise CollectorError("slot_order")
        if any(row["control_revision"] != control_revision for row in events):
            raise CollectorError("control_revision_drift")
        if any(
            row[key] != source_hashes[key]
            for row in events
            for key in source_hashes
        ):
            raise CollectorError("source_drift")
        _validate_request(slot, request, token)
        sequence = len(events) // 2 + 1
        if sequence > MAX_RECORDS:
            raise CollectorError("record_limit")
        host_now = _utc_now()
        recorded_at = host_now
        if writing_files:
            recorded_at = _event_writing_recorded_at(
                next(iter(writing_files))
            )
            elapsed = _utc(host_now, "begin_retry_time") - _utc(
                recorded_at,
                "begin_retry_recorded_time",
            )
            if not 0 <= elapsed.total_seconds() <= MAX_RECORD_SECONDS:
                raise CollectorError("request_retry_expired")
        value = _event_value(
            control_revision=control_revision,
            sequence=sequence,
            phase="begin",
            slot=slot,
            recorded_at_utc=recorded_at,
            payload=request_raw,
            source_hashes=source_hashes,
            outcome="REQUEST_FROZEN",
        )
        _write_exclusive(
            directory_fd,
            _event_file(sequence, "begin"),
            _canonical(value),
            owner_uid,
        )
    finally:
        os.close(directory_fd)
    return {
        "schema": COLLECTOR_STATUS_SCHEMA,
        "status": "REQUEST_FROZEN",
        "sequence": sequence,
        "slot": slot,
        "request_sha256": _sha(request_raw),
        "cloud_call_count": 0,
        "raw_value_emitted_count": 0,
    }


def finish(
    *,
    control_revision: str,
    slot: str,
    response_raw: bytes,
    journal_directory: Path = JOURNAL_DIRECTORY,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    owner_uid: int = ROOT_UID,
) -> dict[str, Any]:
    current_source_hashes = _trusted_runtime(
        control_revision=control_revision,
        authority_directory=authority_directory,
        owner_uid=owner_uid,
        require_root_only=True,
    )
    directory_fd, _ = _open_directory(journal_directory, owner_uid)
    try:
        events, stage_files, writing_files = _scan_journal(
            directory_fd,
            owner_uid,
        )
        if events and events[-1]["phase"] == "finish" and not writing_files:
            prior = events[-1]
            if prior["outcome"] == "UNKNOWN_INFLIGHT":
                raise CollectorError("response_unknown")
            if (
                not stage_files
                and prior["control_revision"] == control_revision
                and prior["slot"] == slot
                and prior["outcome"] == "RESPONSE_RECEIVED"
                and prior["_payload"] == response_raw
                and all(
                    prior[key] == current_source_hashes[key]
                    for key in current_source_hashes
                )
            ):
                return {
                    "schema": COLLECTOR_STATUS_SCHEMA,
                    "status": "RESPONSE_RECORDED",
                    "sequence": prior["sequence"],
                    "slot": prior["slot"],
                    "response_sha256": prior["payload_sha256"],
                    "cloud_call_count": 0,
                    "raw_value_emitted_count": 0,
                }
            raise CollectorError("finish_retry_identity")
        if stage_files or not events or events[-1]["phase"] != "begin":
            raise CollectorError("finish_without_begin")
        begin_row = events[-1]
        expected_target = _event_file(begin_row["sequence"], "finish")
        if writing_files and not _writing_matches_target(
            writing_files,
            expected_target,
        ):
            raise CollectorError("local_write_recovery")
        if (
            begin_row["control_revision"] != control_revision
            or begin_row["slot"] != slot
        ):
            raise CollectorError("finish_identity")
        if any(
            begin_row[key] != current_source_hashes[key]
            for key in current_source_hashes
        ):
            raise CollectorError("source_drift")
        completed = (
            _event_writing_recorded_at(next(iter(writing_files)))
            if writing_files
            else _utc_now()
        )
        elapsed = _utc(completed, "finish_time") - _utc(
            begin_row["recorded_at_utc"], "begin_time"
        )
        outcome = "RESPONSE_RECEIVED"
        event_payload = response_raw
        unknown_reason: Optional[str] = None
        try:
            if SENSITIVE_INGRESS_VALUE.search(response_raw):
                raise CollectorError("sensitive_ingress")
            response = _strict_json(response_raw, "response")
            _reject_sensitive_ingress(response_raw, response)
        except CollectorError as exc:
            outcome = "UNKNOWN_INFLIGHT"
            unknown_reason = (
                "SENSITIVE_WRAPPER_DETECTED"
                if exc.code == "sensitive_ingress"
                else "OFFICIAL_RESPONSE_EXPORT_FAILED"
            )
        else:
            try:
                _validate_response_incrementally(
                    events=events,
                    begin_row=begin_row,
                    response=response,
                )
            except (
                KeyError,
                OverflowError,
                RecursionError,
                TypeError,
                ValueError,
            ):
                outcome = "UNKNOWN_INFLIGHT"
                unknown_reason = "OFFICIAL_RESPONSE_EXPORT_FAILED"
        if elapsed.total_seconds() < 0 or elapsed.total_seconds() > MAX_RECORD_SECONDS:
            outcome = "UNKNOWN_INFLIGHT"
            unknown_reason = "OFFICIAL_RESPONSE_EXPORT_FAILED"
        value = _event_value(
            control_revision=control_revision,
            sequence=begin_row["sequence"],
            phase="finish",
            slot=slot,
            recorded_at_utc=completed,
            payload=event_payload,
            source_hashes=current_source_hashes,
            outcome=outcome,
        )
        if outcome == "RESPONSE_RECEIVED":
            candidate = dict(value)
            candidate["_payload"] = event_payload
            try:
                candidate_events = [*events, candidate]
                provider_candidate, actiontrail_candidate = (
                    _capture_envelopes(
                        candidate_events,
                        control_revision,
                    )
                )
                if (
                    slot == CREATE_SLOT
                    and _response_token(slot, response) is None
                ):
                    extractor.project_actiontrail_readback(
                        actiontrail_candidate,
                        expected_control_revision=control_revision,
                    )
                remaining_actiontrail, remaining_provider = (
                    _remaining_capture_records(candidate_events)
                )
                if (
                    len(candidate_events) // 2
                    + remaining_actiontrail
                    + remaining_provider
                    > MAX_RECORDS
                    or
                    len(provider_candidate)
                    + remaining_provider
                    * MIN_REMAINING_CAPTURE_RECORD_BYTES
                    > extractor.MAX_CAPTURE_BYTES
                    or len(actiontrail_candidate)
                    + remaining_actiontrail
                    * MIN_REMAINING_CAPTURE_RECORD_BYTES
                    > extractor.MAX_CAPTURE_BYTES
                ):
                    raise CollectorError("capture_budget")
                if slot == BILLING_SLOT:
                    _captures(candidate_events, control_revision)
            except (
                KeyError,
                OverflowError,
                RecursionError,
                TypeError,
                ValueError,
            ):
                outcome = "UNKNOWN_INFLIGHT"
                unknown_reason = "OFFICIAL_RESPONSE_EXPORT_FAILED"
        if outcome != "RESPONSE_RECEIVED":
            event_payload = _unknown_marker(
                unknown_reason or "OFFICIAL_RESPONSE_EXPORT_FAILED"
            )
            value = _event_value(
                control_revision=control_revision,
                sequence=begin_row["sequence"],
                phase="finish",
                slot=slot,
                recorded_at_utc=completed,
                payload=event_payload,
                source_hashes=current_source_hashes,
                outcome=outcome,
            )
        _write_exclusive(
            directory_fd,
            _event_file(begin_row["sequence"], "finish"),
            _canonical(value),
            owner_uid,
        )
    finally:
        os.close(directory_fd)
    if outcome != "RESPONSE_RECEIVED":
        raise CollectorError("response_unknown")
    return {
        "schema": COLLECTOR_STATUS_SCHEMA,
        "status": "RESPONSE_RECORDED",
        "sequence": begin_row["sequence"],
        "slot": slot,
        "response_sha256": _sha(response_raw),
        "cloud_call_count": 0,
        "raw_value_emitted_count": 0,
    }


def mark_unknown(
    *,
    control_revision: str,
    slot: str,
    reason: str,
    journal_directory: Path = JOURNAL_DIRECTORY,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    owner_uid: int = ROOT_UID,
) -> dict[str, Any]:
    if reason not in UNKNOWN_REASONS:
        raise CollectorError("unknown_reason")
    current_source_hashes = _trusted_runtime(
        control_revision=control_revision,
        authority_directory=authority_directory,
        owner_uid=owner_uid,
        require_root_only=True,
    )
    directory_fd, _ = _open_directory(journal_directory, owner_uid)
    try:
        events, stage_files, writing_files = _scan_journal(
            directory_fd,
            owner_uid,
        )
        marker = _unknown_marker(reason)
        if events and events[-1]["phase"] == "finish" and not writing_files:
            prior = events[-1]
            if (
                not stage_files
                and prior["control_revision"] == control_revision
                and prior["slot"] == slot
                and prior["outcome"] == "UNKNOWN_INFLIGHT"
                and prior["_payload"] == marker
                and all(
                    prior[key] == current_source_hashes[key]
                    for key in current_source_hashes
                )
            ):
                return {
                    "schema": COLLECTOR_STATUS_SCHEMA,
                    "status": "UNKNOWN_INFLIGHT",
                    "sequence": prior["sequence"],
                    "slot": prior["slot"],
                    "reason": reason,
                    "cloud_call_count": 0,
                    "raw_value_emitted_count": 0,
                    "cloud_request_replay_allowed": False,
                }
            raise CollectorError("unknown_retry_identity")
        if stage_files or not events or events[-1]["phase"] != "begin":
            raise CollectorError("unknown_without_pending")
        begin_row = events[-1]
        expected_target = _event_file(begin_row["sequence"], "finish")
        if writing_files and not _writing_matches_target(
            writing_files,
            expected_target,
        ):
            raise CollectorError("unknown_without_pending")
        if (
            begin_row["control_revision"] != control_revision
            or begin_row["slot"] != slot
            or any(
                begin_row[key] != current_source_hashes[key]
                for key in current_source_hashes
            )
        ):
            raise CollectorError("unknown_identity")
        value = _event_value(
            control_revision=control_revision,
            sequence=begin_row["sequence"],
            phase="finish",
            slot=slot,
            recorded_at_utc=(
                _event_writing_recorded_at(next(iter(writing_files)))
                if writing_files
                else _utc_now()
            ),
            payload=marker,
            source_hashes=current_source_hashes,
            outcome="UNKNOWN_INFLIGHT",
        )
        _write_exclusive(
            directory_fd,
            _event_file(begin_row["sequence"], "finish"),
            _canonical(value),
            owner_uid,
        )
    finally:
        os.close(directory_fd)
    return {
        "schema": COLLECTOR_STATUS_SCHEMA,
        "status": "UNKNOWN_INFLIGHT",
        "sequence": begin_row["sequence"],
        "slot": slot,
        "reason": reason,
        "cloud_call_count": 0,
        "raw_value_emitted_count": 0,
        "cloud_request_replay_allowed": False,
    }


def _pairs(events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if not events or len(events) % 2:
        raise CollectorError("journal_incomplete")
    result = []
    for index in range(0, len(events), 2):
        first, second = events[index], events[index + 1]
        if (
            first["phase"] != "begin"
            or second["phase"] != "finish"
            or first["sequence"] != second["sequence"]
            or first["slot"] != second["slot"]
            or first["outcome"] != "REQUEST_FROZEN"
            or second["outcome"] != "RESPONSE_RECEIVED"
            or first["collector_source_sha256"]
            != second["collector_source_sha256"]
            or first["extractor_source_sha256"]
            != second["extractor_source_sha256"]
            or first["authority_source_sha256"]
            != second["authority_source_sha256"]
            or first["activation_receipt_sha256"]
            != second["activation_receipt_sha256"]
        ):
            raise CollectorError("journal_pair")
        result.append((first, second))
    return result


def _capture_record(
    begin_row: dict[str, Any],
    finish_row: dict[str, Any],
) -> dict[str, Any]:
    operation, version = OPERATIONS[begin_row["slot"]]
    return {
        "sequence": begin_row["sequence"],
        "slot": begin_row["slot"],
        "operation": operation,
        "api_version": version,
        "started_at_utc": begin_row["recorded_at_utc"],
        "completed_at_utc": finish_row["recorded_at_utc"],
        "transport_outcome": "RESPONSE_RECEIVED",
        "read_only": True,
        "request_json_base64": begin_row["payload_base64"],
        "response_json_base64": finish_row["payload_base64"],
    }


def _captures(
    events: list[dict[str, Any]],
    control_revision: str,
) -> tuple[bytes, bytes]:
    expected_slot, token = _next_slot(events)
    if expected_slot is not None or token is not None:
        raise CollectorError("journal_not_terminal")
    provider_raw, actiontrail_raw = _capture_envelopes(
        events,
        control_revision,
    )
    extractor.extract_verified_projection(
        provider_raw,
        actiontrail_raw,
        expected_control_revision=control_revision,
    )
    return provider_raw, actiontrail_raw


def _capture_envelopes(
    events: list[dict[str, Any]],
    control_revision: str,
) -> tuple[bytes, bytes]:
    pairs = _pairs(events)
    observed_at = events[-1]["recorded_at_utc"]
    source_hashes = {
        "collector_source_sha256": events[0]["collector_source_sha256"],
        "extractor_source_sha256": events[0]["extractor_source_sha256"],
        "authority_source_sha256": events[0]["authority_source_sha256"],
        "activation_receipt_sha256": events[0][
            "activation_receipt_sha256"
        ],
    }
    records = [_capture_record(first, second) for first, second in pairs]
    actiontrail = [row for row in records if row["slot"] in ACTIONTRAIL_SLOTS]
    provider = [row for row in records if row["slot"] in PROVIDER_SLOTS]
    provider = [dict(row, sequence=index) for index, row in enumerate(provider, 1)]
    actiontrail = [
        dict(row, sequence=index) for index, row in enumerate(actiontrail, 1)
    ]

    def envelope(schema: str, rows: list[dict[str, Any]]) -> bytes:
        return _canonical({
            "schema": schema,
            "task_id": TASK_ID,
            "operation_id": OPERATION_ID,
            "phase": "POST_ACTION_READBACK_ONLY",
            "m0_anchor_revision": M0_ANCHOR_REVISION,
            "control_revision": control_revision,
            "observed_at_utc": observed_at,
            "capture_transport": CAPTURE_TRANSPORT,
            **source_hashes,
            "records": rows,
        })

    provider_raw = envelope(extractor.PROVIDER_CAPTURE_SCHEMA, provider)
    actiontrail_raw = envelope(
        extractor.ACTIONTRAIL_CAPTURE_SCHEMA,
        actiontrail,
    )
    return provider_raw, actiontrail_raw


def _remaining_capture_records(
    events: list[dict[str, Any]],
) -> tuple[int, int]:
    slot, token = _next_slot(events)
    if slot is None:
        return 0, 0
    if slot == COST_SLOT:
        return (2 if token is not None else 1), 3
    if slot == CREATE_SLOT:
        return 1, 3
    if slot == CLONE_SLOT:
        return 0, 3
    if slot == SOURCE_SLOT:
        return 0, 2
    if slot == BILLING_SLOT:
        return 0, 1
    raise CollectorError("journal_slot")


def _stage(
    directory_fd: int,
    name: str,
    raw: bytes,
    owner_uid: int,
) -> None:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        _write_exclusive(directory_fd, name, raw, owner_uid)
        return
    except OSError as exc:
        raise CollectorError("stage_stat") from exc
    existing = _read_file(
        directory_fd,
        name,
        owner_uid,
        allowed_links=frozenset({1, 2}),
    )
    if existing != raw:
        raise CollectorError("stage_drift")


def _authority_inventory(directory_fd: int) -> set[str]:
    try:
        names = set(os.listdir(directory_fd))
    except OSError as exc:
        raise CollectorError("authority_inventory") from exc
    allowed = {ROOT_FILE, PROVIDER_FILE, ACTIONTRAIL_FILE}
    if not names.issubset(allowed) or ROOT_FILE not in names:
        raise CollectorError("authority_inventory")
    return names


def _promote_one(
    *,
    journal_fd: int,
    authority_fd: int,
    stage_name: str,
    target_name: str,
    raw: bytes,
    owner_uid: int,
) -> None:
    authority_names = _authority_inventory(authority_fd)
    stage_names = set(os.listdir(journal_fd))
    if target_name in authority_names:
        if stage_name in stage_names:
            target = _read_file(
                authority_fd,
                target_name,
                owner_uid,
                allowed_links=frozenset({1, 2}),
            )
            stage = _read_file(
                journal_fd,
                stage_name,
                owner_uid,
                allowed_links=frozenset({1, 2}),
            )
            if target != raw or stage != raw:
                raise CollectorError("authority_target_drift")
            stage_row = os.stat(
                stage_name,
                dir_fd=journal_fd,
                follow_symlinks=False,
            )
            target_row = os.stat(
                target_name,
                dir_fd=authority_fd,
                follow_symlinks=False,
            )
            same_inode = (stage_row.st_dev, stage_row.st_ino) == (
                target_row.st_dev,
                target_row.st_ino,
            )
            if (
                same_inode
                and (stage_row.st_nlink != 2 or target_row.st_nlink != 2)
            ) or (
                not same_inode
                and (stage_row.st_nlink != 1 or target_row.st_nlink != 1)
            ):
                raise CollectorError("promotion_identity")
            os.unlink(stage_name, dir_fd=journal_fd)
            os.fsync(journal_fd)
            _validate_file(
                os.stat(
                    target_name,
                    dir_fd=authority_fd,
                    follow_symlinks=False,
                ),
                owner_uid,
            )
        else:
            target = _read_file(authority_fd, target_name, owner_uid)
            if target != raw:
                raise CollectorError("authority_target_drift")
        return
    if stage_name not in stage_names:
        raise CollectorError("promotion_stage_missing")
    try:
        os.link(
            stage_name,
            target_name,
            src_dir_fd=journal_fd,
            dst_dir_fd=authority_fd,
            follow_symlinks=False,
        )
        os.fsync(authority_fd)
        os.unlink(stage_name, dir_fd=journal_fd)
        os.fsync(journal_fd)
        target = _read_file(authority_fd, target_name, owner_uid)
    except CollectorError:
        raise
    except FileExistsError as exc:
        raise CollectorError("promotion_target_exists") from exc
    except OSError as exc:
        raise CollectorError("promotion_failed") from exc
    if target != raw:
        raise CollectorError("promotion_drift")


def finalize(
    *,
    control_revision: str,
    journal_directory: Path = JOURNAL_DIRECTORY,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    owner_uid: int = ROOT_UID,
) -> dict[str, Any]:
    current_source_hashes = _trusted_runtime(
        control_revision=control_revision,
        authority_directory=authority_directory,
        owner_uid=owner_uid,
        require_root_only=False,
    )
    journal_fd, _ = _open_directory(journal_directory, owner_uid)
    authority_fd, _ = _open_directory(authority_directory, owner_uid)
    try:
        events, _stage_files, writing_files = _scan_journal(
            journal_fd,
            owner_uid,
        )
        if writing_files and not writing_files.issubset(STAGE_WRITE_FILES):
            raise CollectorError("local_write_recovery")
        if any(row["control_revision"] != control_revision for row in events):
            raise CollectorError("control_revision_drift")
        if any(
            row[key] != current_source_hashes[key]
            for row in events
            for key in current_source_hashes
        ):
            raise CollectorError("source_drift")
        try:
            provider_raw, actiontrail_raw = _captures(
                events,
                control_revision,
            )
        except (extractor.ExtractionError, KeyError, TypeError) as exc:
            raise CollectorError("capture_projection") from exc
        _stage(
            journal_fd,
            PROVIDER_STAGE_FILE,
            provider_raw,
            owner_uid,
        )
        _stage(
            journal_fd,
            ACTIONTRAIL_STAGE_FILE,
            actiontrail_raw,
            owner_uid,
        )
        _promote_one(
            journal_fd=journal_fd,
            authority_fd=authority_fd,
            stage_name=PROVIDER_STAGE_FILE,
            target_name=PROVIDER_FILE,
            raw=provider_raw,
            owner_uid=owner_uid,
        )
        _promote_one(
            journal_fd=journal_fd,
            authority_fd=authority_fd,
            stage_name=ACTIONTRAIL_STAGE_FILE,
            target_name=ACTIONTRAIL_FILE,
            raw=actiontrail_raw,
            owner_uid=owner_uid,
        )
        if _authority_inventory(authority_fd) != {
            ROOT_FILE,
            PROVIDER_FILE,
            ACTIONTRAIL_FILE,
        }:
            raise CollectorError("authority_capture_inventory")
    finally:
        os.close(authority_fd)
        os.close(journal_fd)
    return {
        "schema": COLLECTOR_STATUS_SCHEMA,
        "status": "CAPTURE_INSTALLED",
        "provider_raw_file_sha256": _sha(provider_raw),
        "actiontrail_raw_file_sha256": _sha(actiontrail_raw),
        "cloud_call_count": 0,
        "raw_value_emitted_count": 0,
    }


def status(
    *,
    journal_directory: Path = JOURNAL_DIRECTORY,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    owner_uid: int = ROOT_UID,
) -> dict[str, Any]:
    directory_fd, _ = _open_directory(journal_directory, owner_uid)
    try:
        events, stage_files, writing_files = _scan_journal(
            directory_fd,
            owner_uid,
        )
    finally:
        os.close(directory_fd)
    pending = bool(events and events[-1]["phase"] == "begin")
    unknown = any(row["outcome"] == "UNKNOWN_INFLIGHT" for row in events)
    pending_expired = False
    if pending:
        elapsed = _utc(_utc_now(), "status_time") - _utc(
            events[-1]["recorded_at_utc"],
            "status_begin_time",
        )
        pending_expired = (
            elapsed.total_seconds() < 0
            or elapsed.total_seconds() > MAX_RECORD_SECONDS
        )
    terminal = False
    installed = False
    authority_partial = False
    if events and not pending and not unknown and not writing_files:
        expected_slot, token = _next_slot(events)
        terminal = expected_slot is None and token is None
        if terminal:
            provider_raw, actiontrail_raw = _captures(
                events,
                events[0]["control_revision"],
            )
            authority_fd, _ = _open_directory(
                authority_directory,
                owner_uid,
            )
            try:
                inventory = _authority_inventory(authority_fd)
                installed = inventory == {
                    ROOT_FILE,
                    PROVIDER_FILE,
                    ACTIONTRAIL_FILE,
                }
                if installed:
                    installed = (
                        _read_file(
                            authority_fd,
                            PROVIDER_FILE,
                            owner_uid,
                        )
                        == provider_raw
                        and _read_file(
                            authority_fd,
                            ACTIONTRAIL_FILE,
                            owner_uid,
                        )
                        == actiontrail_raw
                    )
                    if not installed:
                        raise CollectorError("authority_target_drift")
                authority_partial = inventory != {ROOT_FILE} and not installed
            finally:
                os.close(authority_fd)
    return {
        "schema": COLLECTOR_STATUS_SCHEMA,
        "status": (
            "UNKNOWN_INFLIGHT"
            if unknown
            else "LOCAL_WRITE_RECOVERY_REQUIRED"
            if writing_files
            else "REQUEST_EXPIRED_UNKNOWN"
            if pending_expired
            else "REQUEST_PENDING"
            if pending
            else "LOCAL_PROMOTION_PENDING"
            if stage_files or authority_partial
            else "CAPTURE_INSTALLED"
            if installed
            else "READY_TO_FINALIZE"
            if terminal
            else "READY_FOR_NEXT_REQUEST"
            if events
            else "EMPTY_JOURNAL_NO_REQUEST_FROZEN"
        ),
        "recorded_request_count": sum(
            row["phase"] == "begin" for row in events
        ),
        "recorded_response_count": sum(
            row["phase"] == "finish" for row in events
        ),
        "cloud_call_count": 0,
        "raw_value_emitted_count": 0,
    }


def _write_status(stream: Any, value: dict[str, Any]) -> None:
    raw = _canonical(value).decode("ascii")
    stream.write(raw)
    stream.flush()


def main(argv: Optional[list[str]] = None) -> int:
    parser = FixedArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("begin", "finish"):
        child = subparsers.add_parser(name)
        child.add_argument("--control-revision", required=True)
        child.add_argument("--slot", required=True, choices=SLOTS)
    final = subparsers.add_parser("finalize")
    final.add_argument("--control-revision", required=True)
    unknown = subparsers.add_parser("mark-unknown")
    unknown.add_argument("--control-revision", required=True)
    unknown.add_argument("--slot", required=True, choices=SLOTS)
    unknown.add_argument(
        "--reason",
        required=True,
        choices=sorted(UNKNOWN_REASONS),
    )
    subparsers.add_parser("status")
    try:
        args = parser.parse_args(argv)
        if os.geteuid() != ROOT_UID:
            raise CollectorError("root_required")
        _validate_interpreter()
        if args.command in {"begin", "finish"} and (
            not hasattr(sys.stdin, "buffer")
            or sys.stdin.buffer.isatty()
        ):
            raise CollectorError("stdin_tty")
        if args.command == "begin":
            result = begin(
                control_revision=args.control_revision,
                slot=args.slot,
                request_raw=_stdin_bytes(sys.stdin.buffer),
            )
        elif args.command == "finish":
            try:
                response_raw = _stdin_bytes(sys.stdin.buffer)
            except CollectorError as exc:
                if exc.code not in {"stdin_empty", "stdin_oversize"}:
                    raise
                result = mark_unknown(
                    control_revision=args.control_revision,
                    slot=args.slot,
                    reason=(
                        "NO_RESPONSE_BODY"
                        if exc.code == "stdin_empty"
                        else "RESPONSE_BODY_OVERSIZE"
                    ),
                )
            else:
                result = finish(
                    control_revision=args.control_revision,
                    slot=args.slot,
                    response_raw=response_raw,
                )
        elif args.command == "finalize":
            result = finalize(control_revision=args.control_revision)
        elif args.command == "mark-unknown":
            result = mark_unknown(
                control_revision=args.control_revision,
                slot=args.slot,
                reason=args.reason,
            )
        else:
            result = status()
    except CollectorError as exc:
        _write_status(
            sys.stderr,
            {
                "schema": COLLECTOR_STATUS_SCHEMA,
                "status": "BLOCKED",
                "code": exc.code,
                "cloud_call_count": 0,
                "raw_value_emitted_count": 0,
            },
        )
        return 2
    _write_status(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
