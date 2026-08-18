#!/usr/bin/env python3
"""Build and sign the Item 26 runtime activation receipt v3.

The library API accepts already-loaded key bytes and source bindings so the
caller controls custody.  The command entry point remains install-disabled
even after public-root finalization and fails before parsing paths or doing
file I/O.  A receipt signature covers the complete outer context and payload.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any, Optional

import verify_item26_manual_cost_stop_authority_v2 as authority


def _validate_scratch(directory: Path) -> None:
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
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
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
    _validate_scratch(scratch_directory)
    before = authority._tool_identity(authority.OPENSSL)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".item26-receipt-v3-sign-",
            dir=scratch_directory,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            key_path = base / "private-key.pem"
            message_path = base / "message.bin"
            signature_path = base / "signature.bin"
            _write_exclusive(key_path, private_key_pem)
            _write_exclusive(message_path, message)
            _write_exclusive(signature_path, b"")
            result = subprocess.run(
                [
                    str(authority.OPENSSL),
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(key_path),
                    "-out",
                    str(signature_path),
                    str(message_path),
                ],
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
    """Return one canonical, fully context-signed receipt-v3 envelope."""
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
    root_hash = authority.EXPECTED_ROOT_SHA
    private_public = _private_public_key(
        local_ci_observation_private_key_pem
    )
    if private_public != root_keys["local_ci_observation"][0]:
        raise ValueError("manual activation receipt v3 signing key identity")
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
            "ledger_stop_terminal": (
                authority.EXPECTED_LEDGER_STOP_TERMINAL
            ),
            "rejected_bootstrap_source_terminal": (
                authority.EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL
            ),
            "helper_source_terminal": (
                authority.EXPECTED_HELPER_SOURCE_TERMINAL
            ),
            "bootstrap_ledger_terminal": (
                authority.EXPECTED_BOOTSTRAP_LEDGER_TERMINAL
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
    unsigned = {
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
    message = authority.RECEIPT_SIGNATURE_DOMAIN + authority.canonical_bytes(
        unsigned
    )
    signature = _sign(
        message,
        local_ci_observation_private_key_pem,
        scratch_directory=scratch_directory,
    )
    envelope = {
        **unsigned,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    return authority.canonical_bytes(envelope)


def main(argv: Optional[list[str]] = None) -> int:
    """Remain install-disabled before argument/path processing."""
    del argv
    authority._require_finalized()
    raise ValueError("manual activation receipt v3 command is install-disabled")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_activation_receipt", "main"]
