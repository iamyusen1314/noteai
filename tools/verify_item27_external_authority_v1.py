#!/usr/bin/env python3
"""Verify externally signed Item 27 provider and CI authority exports.

Local JSON, git refs and locally generated hashes are not authority.  This
module accepts only detached signatures from separately pinned provider and CI
export signers.  The signer roots deliberately remain empty before execution,
so no offline fixture can grant readiness credit.
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
VERIFIER_REF = "tools/verify_item27_external_authority_v1.py"
PRIOR_AUTHORITY_ROOT_MANIFEST_PATH = Path(
    "/Library/Application Support/NoteAI/"
    "item27-prior-authority-root-v1.json"
)
AUTHORITY_BUNDLE_PATH = Path(
    "/Library/Application Support/NoteAI/"
    "item27-external-authority-bundle-v1.json"
)
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-SMOKE-001"
BUNDLE_SCHEMA = "noteai.item27.external-authority-bundle.v1"
PROVIDER_PAYLOAD_SCHEMA = "noteai.item27.provider-authority-export.v1"
CI_PAYLOAD_SCHEMA = "noteai.item27.ci-authority-export.v1"
MAX_BYTES = 1024 * 1024
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = "iamyusen1314/noteai"
SOURCE_BRANCH = "codex/quality-stabilization-real-chain"
SOURCE_REF = "refs/heads/" + SOURCE_BRANCH
PRIOR_ROOT_SCHEMA = "noteai.item27.prior-external-authority-root.v1"
OPENSSL_PATH = Path("/usr/bin/openssl")
GIT_PATH = Path("/usr/bin/git")
TRUSTED_TOOL_ENV = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "LANG": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
}

# Trust is intentionally outside the repository.  The fixed manifest must be
# installed root-owned before the Item 27 source revision exists.  It is absent
# in the current environment, so Item 27 remains non-dispatchable by default.


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ) + "\n"
    ).encode("ascii")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_equal(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict_equal(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _strict_equal(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _stable_identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns,
    )


def _read_stable_root_owned(path: Path, *, max_bytes: int) -> bytes:
    """Read one prior-authentication artifact without path re-open/TOCTOU."""

    if not path.is_absolute():
        raise ValueError("external authority path must be absolute")
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != 0
        or stat.S_IMODE(parent.st_mode) & 0o022
    ):
        raise ValueError("external authority parent is not root-owned immutable")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    before = path.lstat()
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(descriptor, min(65536, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != 0
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) & 0o022
        or _stable_identity(before) != _stable_identity(opened)
        or _stable_identity(opened) != _stable_identity(closed)
        or _stable_identity(closed) != _stable_identity(after)
        or not 1 <= total <= max_bytes
    ):
        raise ValueError("external authority artifact identity changed")
    return b"".join(chunks)


def _parse_canonical(raw: bytes, label: str) -> dict[str, Any]:
    if not 1 <= len(raw) <= MAX_BYTES or b"\x00" in raw:
        raise ValueError(label + " size")
    value = json.loads(raw.decode("ascii"), object_pairs_hook=_no_duplicates)
    if type(value) is not dict or raw != _canonical(value):
        raise ValueError(label + " canonical")
    return value


def _trusted_tool_identity(path: Path) -> tuple[int, ...]:
    parent = path.parent.lstat()
    row = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != 0
        or stat.S_IMODE(parent.st_mode) & 0o022
        or not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != 0
        or stat.S_IMODE(row.st_mode) & 0o022
    ):
        raise OSError("trusted tool is replaceable")
    return _stable_identity(row)


def _run_trusted(path: Path, arguments: list[str], **kwargs):
    before = _trusted_tool_identity(path)
    result = subprocess.run(
        [str(path), *arguments], env=TRUSTED_TOOL_ENV, **kwargs
    )
    if _trusted_tool_identity(path) != before:
        raise OSError("trusted tool identity changed")
    return result


def _git_is_ancestor(revision: str, descendant: str, *, root: Path) -> bool:
    if type(revision) is not str or HEX40.fullmatch(revision) is None:
        return False
    try:
        result = _run_trusted(
            GIT_PATH,
            ["--no-replace-objects", "merge-base", "--is-ancestor", revision, descendant],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _verify_signature(payload: bytes, signature: bytes, key_bytes: bytes) -> bool:
    try:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            payload_path = base / "payload"
            signature_path = base / "signature"
            key_path = base / "authority-key.pem"
            descriptor = os.open(
                payload_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            try:
                os.write(descriptor, payload)
            finally:
                os.close(descriptor)
            descriptor = os.open(
                signature_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            try:
                os.write(descriptor, signature)
            finally:
                os.close(descriptor)
            descriptor = os.open(
                key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            try:
                os.write(descriptor, key_bytes)
            finally:
                os.close(descriptor)
            result = _run_trusted(
                OPENSSL_PATH,
                [
                    "dgst", "-sha256", "-verify", str(key_path),
                    "-signature", str(signature_path), str(payload_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _spki_der(key_bytes: bytes, label: str) -> bytes:
    try:
        result = _run_trusted(
            OPENSSL_PATH,
            ["pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
            input=key_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(label + " prior key parse") from exc
    if result.returncode != 0 or not 1 <= len(result.stdout) <= 64 * 1024:
        raise ValueError(label + " prior key parse")
    return result.stdout


def _verify_envelope(
    envelope: Any,
    *,
    authority: str,
    issuer: str,
    audience: str,
    key_bytes: bytes,
    payload_schema: str,
) -> tuple[list[str], dict[str, Any] | None]:
    keys = {
        "authority", "issuer", "audience", "immutable_artifact_sha256",
        "payload", "signature_base64",
    }
    if type(envelope) is not dict or set(envelope) != keys:
        return [authority + ": authority envelope fields mismatch"], None
    payload = envelope.get("payload")
    if type(payload) is not dict:
        return [authority + ": authority payload missing"], None
    artifact = envelope.get("immutable_artifact_sha256")
    if (
        envelope.get("authority") != authority
        or envelope.get("issuer") != issuer
        or envelope.get("audience") != audience
        or type(artifact) is not str or HEX64.fullmatch(artifact) is None
        or payload.get("schema") != payload_schema
        or payload.get("task_id") != TASK_ID
        or payload.get("immutable_artifact_sha256") != artifact
    ):
        return [authority + ": authority identity mismatch"], None
    try:
        signature = base64.b64decode(
            envelope.get("signature_base64", "").encode("ascii"),
            validate=True,
        )
        payload_raw = _canonical(payload)
    except (AttributeError, UnicodeError, ValueError, TypeError):
        return [authority + ": authority signature encoding mismatch"], None
    if not signature or not _verify_signature(payload_raw, signature, key_bytes):
        return [authority + ": detached authority signature invalid"], None
    return [], payload


def _decode_prior_key(
    value: Any, label: str
) -> tuple[bytes, str, str, str]:
    keys = {
        "issuer", "audience", "public_key_pem_base64",
        "public_key_pem_sha256", "public_key_spki_sha256",
    }
    if type(value) is not dict or set(value) != keys:
        raise ValueError(label + " prior key fields")
    issuer = value.get("issuer")
    audience = value.get("audience")
    pem_digest = value.get("public_key_pem_sha256")
    spki_digest = value.get("public_key_spki_sha256")
    encoded = value.get("public_key_pem_base64")
    if (
        type(issuer) is not str or not issuer
        or type(audience) is not str or not audience
        or type(pem_digest) is not str or HEX64.fullmatch(pem_digest) is None
        or type(spki_digest) is not str or HEX64.fullmatch(spki_digest) is None
        or type(encoded) is not str or not encoded
    ):
        raise ValueError(label + " prior key identity")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ValueError(label + " prior key encoding") from exc
    if (
        not 1 <= len(raw) <= 64 * 1024
        or _sha256(raw) != pem_digest
        or b"-----BEGIN PUBLIC KEY-----" not in raw
        or b"-----END PUBLIC KEY-----" not in raw
    ):
        raise ValueError(label + " prior key binding")
    spki = _spki_der(raw, label)
    if _sha256(spki) != spki_digest:
        raise ValueError(label + " prior key SPKI binding")
    return raw, issuer, audience, spki_digest


def _load_prior_authority_roots(
    source_revision: str, *, root: Path
) -> dict[str, Any]:
    raw = _read_stable_root_owned(
        PRIOR_AUTHORITY_ROOT_MANIFEST_PATH, max_bytes=MAX_BYTES
    )
    manifest = _parse_canonical(raw, "prior authority root manifest")
    keys = {
        "schema_version", "schema", "task_id", "status", "repository",
        "source_ref", "frozen_before_revision", "provider", "ci",
    }
    frozen = manifest.get("frozen_before_revision")
    if (
        type(manifest) is not dict or set(manifest) != keys
        or not _strict_equal(manifest.get("schema_version"), 1)
        or manifest.get("schema") != PRIOR_ROOT_SCHEMA
        or manifest.get("task_id") != TASK_ID
        or manifest.get("status") != "INDEPENDENTLY_INSTALLED_BEFORE_SOURCE"
        or manifest.get("repository") != REPOSITORY
        or manifest.get("source_ref") != SOURCE_REF
        or type(frozen) is not str or HEX40.fullmatch(frozen) is None
        or type(source_revision) is not str
        or HEX40.fullmatch(source_revision) is None
        or frozen == source_revision
        or not _git_is_ancestor(frozen, source_revision, root=root)
    ):
        raise ValueError("prior authority root did not predate source")
    (
        provider_key, provider_issuer, provider_audience, provider_spki,
    ) = _decode_prior_key(
        manifest.get("provider"), "provider"
    )
    ci_key, ci_issuer, ci_audience, ci_spki = _decode_prior_key(
        manifest.get("ci"), "ci"
    )
    if provider_spki == ci_spki:
        raise ValueError("provider and CI prior roots must be independent")
    return {
        "provider_key": provider_key,
        "provider_issuer": provider_issuer,
        "provider_audience": provider_audience,
        "ci_key": ci_key,
        "ci_issuer": ci_issuer,
        "ci_audience": ci_audience,
        "frozen_before_revision": frozen,
        "manifest_sha256": _sha256(raw),
    }


def _load_external_bundle() -> dict[str, Any]:
    raw = _read_stable_root_owned(AUTHORITY_BUNDLE_PATH, max_bytes=MAX_BYTES)
    return _parse_canonical(raw, "external authority bundle")


def validate_authority_bundle(
    expected_provider_projection: dict[str, Any],
    source_revision: str,
    *,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    """Validate both independent exports and return the signed CI projection."""

    try:
        roots = _load_prior_authority_roots(source_revision, root=root)
        bundle = _load_external_bundle()
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return [f"Item27 independent prior authority unavailable: {exc}"], None
    if (
        type(bundle) is not dict
        or set(bundle) != {
            "schema_version", "schema", "task_id", "status", "provider", "ci",
        }
        or not _strict_equal(bundle.get("schema_version"), 1)
        or bundle.get("schema") != BUNDLE_SCHEMA
        or bundle.get("task_id") != TASK_ID
        or bundle.get("status") != "EXTERNALLY_ATTESTED"
    ):
        return ["Item27 external authority bundle fields mismatch"], None
    provider_errors, provider = _verify_envelope(
        bundle.get("provider"),
        authority="ALIYUN_TRUSTED_CONNECTOR_SIGNED_EXPORT",
        issuer=roots["provider_issuer"],
        audience=roots["provider_audience"],
        key_bytes=roots["provider_key"],
        payload_schema=PROVIDER_PAYLOAD_SCHEMA,
    )
    ci_errors, ci = _verify_envelope(
        bundle.get("ci"),
        authority="GITHUB_TRUSTED_API_SIGNED_EXPORT",
        issuer=roots["ci_issuer"],
        audience=roots["ci_audience"],
        key_bytes=roots["ci_key"],
        payload_schema=CI_PAYLOAD_SCHEMA,
    )
    errors = [*provider_errors, *ci_errors]
    if provider is not None and not _strict_equal(
        provider, expected_provider_projection
    ):
        errors.append("provider authority projection mismatch")
    if errors:
        return errors, None
    return [], ci
