#!/usr/bin/env python3
"""Verify detached provider/CI authority for Item 29.

Repository files cannot self-authorize readiness.  The two trust files below
must be installed root-owned outside the repository after the Item 29 source
revision exists.  They are absent in the source-only checkpoint, so validation
is BLOCK by default.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_REF = "tools/verify_item29_external_authority_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
ROOT_SCHEMA = "noteai.item29.external-authority-root.v1"
BUNDLE_SCHEMA = "noteai.item29.external-authority-bundle.v1"
PROVIDER_SCHEMA = "noteai.item29.provider-authority-export.v1"
CI_SCHEMA = "noteai.item29.ci-authority-export.v1"
AUTHORITY_ROOT_PATH = Path(
    "/Library/Application Support/NoteAI/item29-external-authority-root-v1.json"
)
AUTHORITY_BUNDLE_PATH = Path(
    "/Library/Application Support/NoteAI/item29-external-authority-bundle-v1.json"
)
OPENSSL = Path("/usr/bin/openssl")
GIT = Path("/usr/bin/git")
REPOSITORY = "iamyusen1314/noteai"
SOURCE_REF = "refs/heads/codex/quality-stabilization-real-chain"
MAX_BYTES = 1024 * 1024
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict(value[key], item) for key, item in expected.items()
        )
    if type(expected) in {list, tuple}:
        return len(value) == len(expected) and all(
            _strict(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _stable(row: os.stat_result):
    return (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns,
    )


def _read_root_owned(path: Path) -> bytes:
    parent = path.parent.lstat()
    before = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) & 0o022
        or not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
        or before.st_uid != 0 or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) & 0o022
    ):
        raise ValueError("authority_identity")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        raw = b""
        while len(raw) <= MAX_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (
        not 1 <= len(raw) <= MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise ValueError("authority_identity")
    return raw


def _parse(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(label + "_json") from exc
    if type(value) is not dict or _canonical(value) != raw:
        raise ValueError(label + "_canonical")
    return value


def _canonical_spki_der(key: bytes) -> bytes:
    try:
        tool = OPENSSL.lstat()
        if (
            not stat.S_ISREG(tool.st_mode)
            or stat.S_ISLNK(tool.st_mode)
            or tool.st_uid != 0
            or stat.S_IMODE(tool.st_mode) & 0o022
        ):
            raise ValueError("openssl_identity")
        result = subprocess.run(
            [
                str(OPENSSL), "pkey", "-pubin", "-inform", "PEM",
                "-outform", "DER",
            ],
            input=key,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("openssl_identity") from exc
    if (
        result.returncode != 0
        or not 1 <= len(result.stdout) <= MAX_BYTES
        or _stable(OPENSSL.lstat()) != _stable(tool)
    ):
        raise ValueError("public_key_spki")
    return result.stdout


def _decode_key(row: Any, label: str) -> tuple[bytes, str]:
    if type(row) is not dict or set(row) != {
        "issuer", "audience", "public_key_pem_base64", "public_key_sha256",
        "public_key_spki_sha256",
    }:
        raise ValueError(label + "_key_schema")
    try:
        key = base64.b64decode(row["public_key_pem_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(label + "_key_encoding") from exc
    if (
        type(row["issuer"]) is not str or not row["issuer"]
        or type(row["audience"]) is not str or not row["audience"]
        or type(row["public_key_sha256"]) is not str
        or HEX64.fullmatch(row["public_key_sha256"]) is None
        or type(row["public_key_spki_sha256"]) is not str
        or HEX64.fullmatch(row["public_key_spki_sha256"]) is None
        or _sha(key) != row["public_key_sha256"]
        or b"-----BEGIN PUBLIC KEY-----" not in key
        or b"-----END PUBLIC KEY-----" not in key
    ):
        raise ValueError(label + "_key_identity")
    spki_sha256 = _sha(_canonical_spki_der(key))
    if spki_sha256 != row["public_key_spki_sha256"]:
        raise ValueError(label + "_key_spki_identity")
    return key, spki_sha256


def _decode_distinct_authority_keys(
    provider_row: Any,
    ci_row: Any,
) -> tuple[bytes, bytes, str, str]:
    provider_key, provider_spki = _decode_key(provider_row, "provider")
    ci_key, ci_spki = _decode_key(ci_row, "ci")
    if provider_spki == ci_spki:
        raise ValueError("authority_mathematical_keys_not_distinct")
    return provider_key, ci_key, provider_spki, ci_spki


def _verify_signature(payload: bytes, signature: bytes, key: bytes) -> bool:
    try:
        tool = OPENSSL.lstat()
        if (
            not stat.S_ISREG(tool.st_mode) or stat.S_ISLNK(tool.st_mode)
            or tool.st_uid != 0 or stat.S_IMODE(tool.st_mode) & 0o022
        ):
            return False
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = {
                "payload": (payload, 0o600),
                "signature": (signature, 0o600),
                "key": (key, 0o600),
            }
            for name, (raw, mode) in paths.items():
                descriptor = os.open(
                    base / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode
                )
                try:
                    os.write(descriptor, raw)
                finally:
                    os.close(descriptor)
            result = subprocess.run(
                [
                    str(OPENSSL), "dgst", "-sha256", "-verify", str(base / "key"),
                    "-signature", str(base / "signature"), str(base / "payload"),
                ],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and _stable(OPENSSL.lstat()) == _stable(tool)


def _frozen_before(frozen: Any, source_revision: str, *, root: Path) -> bool:
    if (
        type(frozen) is not str
        or HEX40.fullmatch(frozen) is None
        or frozen == source_revision
    ):
        return False
    try:
        tool = GIT.lstat()
        if (
            not stat.S_ISREG(tool.st_mode) or stat.S_ISLNK(tool.st_mode)
            or tool.st_uid != 0 or stat.S_IMODE(tool.st_mode) & 0o022
        ):
            return False
        result = subprocess.run(
            [
                str(GIT), "--no-replace-objects", "merge-base", "--is-ancestor",
                frozen, source_revision,
            ],
            cwd=root,
            env={
                "PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and _stable(GIT.lstat()) == _stable(tool)


def _envelope(
    value: Any,
    *,
    authority: str,
    key_row: dict[str, Any],
    key: bytes,
    schema: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "authority", "issuer", "audience", "payload", "signature_base64",
    }:
        raise ValueError(authority + "_envelope_schema")
    payload = value.get("payload")
    if (
        value.get("authority") != authority
        or value.get("issuer") != key_row["issuer"]
        or value.get("audience") != key_row["audience"]
        or type(payload) is not dict
        or payload.get("schema") != schema
        or payload.get("task_id") != TASK_ID
    ):
        raise ValueError(authority + "_envelope_identity")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(authority + "_signature_encoding") from exc
    if not signature or not _verify_signature(_canonical(payload), signature, key):
        raise ValueError(authority + "_signature")
    return payload


def validate_payloads(
    provider: Any,
    ci: Any,
    *,
    source_revision: str,
    receipt_sha256: str,
    terminal_acceptance_sha256: str,
) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    provider_expected = {
        "schema": PROVIDER_SCHEMA,
        "task_id": TASK_ID,
        "status": "PROVIDER_TERMINAL_VERIFIED",
        "source_revision": source_revision,
        "receipt_sha256": receipt_sha256,
        "terminal_acceptance_sha256": terminal_acceptance_sha256,
        "history_key": "Name",
        "provider_client_token_readback_supported": False,
        "command_match_count": 1,
        "invocation_match_count": 1,
        "result_match_count": 1,
        "repeat_count": 1,
        "automatic_retry_count": 0,
    }
    ci_expected = {
        "schema": CI_SCHEMA,
        "task_id": TASK_ID,
        "status": "EXACT_HEAD_CI_ACCEPTED",
        "repository": REPOSITORY,
        "source_ref": SOURCE_REF,
        "source_revision": source_revision,
        "push_conclusion": "success",
        "pull_request_conclusion": "success",
        "push_attempt": 1,
        "pull_request_attempt": 1,
    }
    if not _strict(provider, provider_expected):
        errors.append("provider authority payload mismatch")
    if not _strict(ci, ci_expected):
        errors.append("CI authority payload mismatch")
    if errors:
        return errors, None
    projection = {
        "provider_payload_sha256": _sha(_canonical(provider)),
        "ci_payload_sha256": _sha(_canonical(ci)),
        "source_revision": source_revision,
        "receipt_sha256": receipt_sha256,
        "terminal_acceptance_sha256": terminal_acceptance_sha256,
    }
    projection["external_authority_acceptance_sha256"] = _sha(
        _canonical(projection)
    )
    return [], projection


def validate_authority_bundle(
    *,
    source_revision: str,
    receipt_sha256: str,
    terminal_acceptance_sha256: str,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    if (
        HEX40.fullmatch(source_revision or "") is None
        or HEX64.fullmatch(receipt_sha256 or "") is None
        or HEX64.fullmatch(terminal_acceptance_sha256 or "") is None
    ):
        return ["Item29 external authority inputs invalid"], None
    try:
        authority_root = _parse(
            _read_root_owned(AUTHORITY_ROOT_PATH), "authority_root"
        )
        bundle = _parse(_read_root_owned(AUTHORITY_BUNDLE_PATH), "authority_bundle")
        if type(authority_root) is not dict or set(authority_root) != {
            "schema", "task_id", "status", "frozen_before_revision",
            "provider", "ci",
        } or authority_root.get("schema") != ROOT_SCHEMA \
                or authority_root.get("task_id") != TASK_ID \
                or authority_root.get("status") != "FROZEN_BEFORE_EXECUTION" \
                or not _frozen_before(
                    authority_root.get("frozen_before_revision"), source_revision,
                    root=root,
                ):
            raise ValueError("authority_root_schema")
        if type(bundle) is not dict or set(bundle) != {
            "schema", "task_id", "source_revision", "provider", "ci",
        } or bundle.get("schema") != BUNDLE_SCHEMA \
                or bundle.get("task_id") != TASK_ID \
                or bundle.get("source_revision") != source_revision:
            raise ValueError("authority_bundle_schema")
        (
            provider_key,
            ci_key,
            provider_spki_sha256,
            ci_spki_sha256,
        ) = _decode_distinct_authority_keys(
            authority_root["provider"], authority_root["ci"]
        )
        provider = _envelope(
            bundle["provider"], authority="provider",
            key_row=authority_root["provider"],
            key=provider_key, schema=PROVIDER_SCHEMA,
        )
        ci = _envelope(
            bundle["ci"], authority="ci", key_row=authority_root["ci"],
            key=ci_key,
            schema=CI_SCHEMA,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ["Item29 external authority unavailable or invalid: " + str(exc)], None
    errors, binding = validate_payloads(
        provider, ci, source_revision=source_revision,
        receipt_sha256=receipt_sha256,
        terminal_acceptance_sha256=terminal_acceptance_sha256,
    )
    if errors or binding is None:
        return errors, None
    binding.pop("external_authority_acceptance_sha256")
    binding["provider_public_key_spki_sha256"] = provider_spki_sha256
    binding["ci_public_key_spki_sha256"] = ci_spki_sha256
    binding["external_authority_acceptance_sha256"] = _sha(
        _canonical(binding)
    )
    return [], binding
