#!/usr/bin/env python3
"""Detached authority for the Item 26 manual post-action cost stop.

The authority root was created after M0 and before any new provider readback.
It attests only a read-only reconciliation of two already-consumed browser
mutations. It cannot retroactively authorize those mutations, authorize a new
paid action, or add readiness credit.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any

from extract_item26_manual_cost_stop_raw_v1 import (
    EXPECTED_DELETE_REQUEST_ID_SHA256,
    EXPECTED_OLD_CLONE_NAME_SHA256,
    EXPECTED_OLD_CLONE_SHA256,
    EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256,
    EXPECTED_PROTECTION_REQUEST_ID_SHA256,
    M0_ANCHOR_REVISION,
    VerifiedManualProjection,
    canonical_bytes,
    consumed_mutation_identity_set_sha256,
    extract_verified_projection,
)


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":MANUAL-POST-ACTION-COST-STOP:v1"
VERIFIER_REF = "tools/verify_item26_manual_cost_stop_authority_v1.py"
RAW_EXTRACTOR_REF = "tools/extract_item26_manual_cost_stop_raw_v1.py"
EVIDENCE_VERIFIER_REF = "tools/verify_item26_manual_cost_stop_evidence_v1.py"
BUILDER_REF = "tools/build_item26_manual_cost_stop_evidence_v1.py"
SUCCESSOR_VERIFIER_REF = "tools/verify_pitr_restore_evidence.py"
READINESS_GATE_REF = "tools/internal_deployment_readiness_gate.py"
CI_WORKFLOW_REF = ".github/workflows/ci.yml"
CONTRACT_REF = "deploy/production/plans/item26-manual-cost-stop-contract-v1.json"
NO_REPLAY_REF = "deploy/production/plans/item26-no-replay-registry-v2.json"
HANDOFF_REF = ".codex/handoffs/current-task.md"
REQUIRED_CONTROL_SOURCE_REFS = (
    RAW_EXTRACTOR_REF,
    VERIFIER_REF,
    EVIDENCE_VERIFIER_REF,
    BUILDER_REF,
    READINESS_GATE_REF,
    CONTRACT_REF,
    NO_REPLAY_REF,
    CI_WORKFLOW_REF,
)

AUTHORITY_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v1"
)
AUTHORITY_ROOT_PATH = AUTHORITY_DIRECTORY / "authority-root-v1.json"
AUTHORITY_BUNDLE_PATH = AUTHORITY_DIRECTORY / "authority-bundle-v1.json"
PROVIDER_RAW_PATH = AUTHORITY_DIRECTORY / "provider-raw-v1.json"
ACTIONTRAIL_RAW_PATH = AUTHORITY_DIRECTORY / "actiontrail-raw-v1.json"
CONFIRMATION_ENVELOPE_PATH = (
    AUTHORITY_DIRECTORY / "confirmation-envelope-v1.json"
)
ROOT_FILE = AUTHORITY_ROOT_PATH.name
PROVIDER_RAW_FILE = PROVIDER_RAW_PATH.name
ACTIONTRAIL_RAW_FILE = ACTIONTRAIL_RAW_PATH.name
CONFIRMATION_FILE = CONFIRMATION_ENVELOPE_PATH.name
BUNDLE_FILE = AUTHORITY_BUNDLE_PATH.name
ACTIVATION_INVENTORY = (ROOT_FILE,)
CAPTURE_INVENTORY = (ROOT_FILE, PROVIDER_RAW_FILE, ACTIONTRAIL_RAW_FILE)
FINAL_INVENTORY = (
    ROOT_FILE,
    PROVIDER_RAW_FILE,
    ACTIONTRAIL_RAW_FILE,
    CONFIRMATION_FILE,
    BUNDLE_FILE,
)

ROOT_SCHEMA = "noteai.item26.manual-cost-stop-authority-root.v1"
BUNDLE_SCHEMA = "noteai.item26.manual-cost-stop-authority-bundle.v1"
PROVIDER_SCHEMA = "noteai.item26.manual-cost-stop-provider-authority.v1"
CONFIRMATION_SCHEMA = (
    "noteai.item26.manual-cost-stop-confirmation-authority.v1"
)
CI_SCHEMA = "noteai.item26.manual-cost-stop-ci-authority.v1"
EXPECTED_AUTHORITY_ROOT_FILE_SHA256 = (
    "f0f7cfce319009ad696cf762f30ca25b2f237d4bda2f4f0643baeea409514f3c"
)
AUTHORITY_IMPLEMENTED = True
ROOT_UID = 0
REPOSITORY = "iamyusen1314/noteai"
SOURCE_REF = "refs/heads/codex/quality-stabilization-real-chain"
EXPECTED_CONTRACT_FILE_SHA256 = (
    "0bd5ef19c74175b9f7eefa155a56339dd8886e803ccb15e474b821241acde5d6"
)
EXPECTED_NO_REPLAY_FILE_SHA256 = (
    "994c521e22abd9be0c88d4b252ce4d3ef9a47f8131a065ab7964018f224d0f47"
)
EXPECTED_NO_REPLAY_REGISTRY_SHA256 = (
    "93abb46e3e329dd28edab6bab14ec6c1a09177d0effe0e80d881d43f1e878be5"
)
EXPECTED_MUTATION_SET_SHA256 = (
    "8647c02f5879dcb7a986fc87ce3668ac4e35d63d610c4da1e54a57a8b7263105"
)
EXPECTED_HANDOFF_FILE_SHA256 = (
    "22401854f3f0653bdf12c7649cf7e49ac9b910defea3e442f4378ce335975a28"
)
EXPECTED_SOURCE_PRE_TUPLE_SHA256 = (
    "7b19a9ce8091ef52b11cd722d3d3a52671ba7888811ad47adbbae80abe5d5771"
)
EXPECTED_HISTORICAL_CONFIRMATION_SHA256 = (
    "0b2a6a3e3a20b1e9faf94affd8b966082ba58530268f5850b05cc9b1655c1479"
)
LEDGER_CONTEXT_REVISION = "41c489cf5ebfedfa2959bcee1f09183a9491f7f6"
EXPECTED_M0_CI = {
    "push": {
        "run_id": 31962925383,
        "job_id": 95203569966,
        "event": "push",
        "attempt": 1,
        "conclusion": "success",
        "head_sha": M0_ANCHOR_REVISION,
    },
    "pull_request": {
        "run_id": 31962928312,
        "job_id": 95203577020,
        "event": "pull_request",
        "attempt": 1,
        "conclusion": "success",
        "head_sha": M0_ANCHOR_REVISION,
    },
}
PROVIDER_PAYLOAD_KEYS = {
    "schema", "task_id", "operation_id", "control_revision",
    "observed_at_utc", "signed_at_utc", "authority_root_file_sha256",
    "provider_raw_file_sha256", "actiontrail_raw_file_sha256",
    "provider_projection_sha256", "actiontrail_projection_sha256",
    "terminal_acceptance_sha256", "raw_closure_sha256",
    "receipt_file_sha256", "receipt_semantic_sha256",
    "confirmation_export_semantic_sha256",
    "historical_confirmation_sha256", "old_clone_sha256",
    "old_clone_name_sha256", "source_pre_tuple_sha256",
    "source_post_tuple_sha256", "billing_snapshot_sha256",
    "no_replay_registry_sha256", "old_clone_create_request_sha256",
    "old_clone_create_body_sha256", "old_clone_client_token_sha256",
    "protection_disable_request_id_sha256",
    "protection_disable_request_body_sha256",
    "protection_disable_client_token_sha256", "delete_request_id_sha256",
    "delete_request_body_sha256", "delete_client_token_present",
    "consumed_mutation_identity_set_sha256", "old_clone_absent",
    "source_unchanged", "historical_billing_only",
    "new_action_authorized", "readiness_credit_added",
}
CONFIRMATION_PAYLOAD_KEYS = {
    "schema", "task_id", "operation_id", "control_revision",
    "confirmed_at_utc", "post_action_observed_at_utc",
    "authority_root_file_sha256", "terminal_acceptance_sha256",
    "receipt_file_sha256", "receipt_semantic_sha256",
    "raw_closure_sha256",
    "provider_projection_sha256", "actiontrail_projection_sha256",
    "historical_user_confirmation_sha256", "no_replay_registry_sha256",
    "consumed_mutation_identity_set_sha256",
    "retroactive_action_authorization", "new_action_authorization",
    "readiness_credit_added",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)
MAX_BYTES = 24 * 1024 * 1024
HISTORICAL_CONFIRMATION_DOMAIN = (
    b"noteai-item26-manual-cost-stop-historical-confirmation-v1\0"
)
OPENSSL = Path("/usr/bin/openssl")
GIT = Path("/usr/bin/git")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _semantic(value: Any) -> str:
    return _sha(canonical_bytes(value)[:-1])


def _hex64(value: Any) -> bool:
    return type(value) is str and HEX64.fullmatch(value) is not None


def _strict(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _strict(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _utc(value: Any) -> datetime | None:
    if type(value) is not str or RFC3339.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


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


def _validate_directory(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != ROOT_UID
    ):
        raise ValueError("manual authority directory identity")


def _validate_file(row: os.stat_result) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != ROOT_UID
        or row.st_nlink != 1
    ):
        raise ValueError("manual authority file identity")


def _validate_parent_chain(directory: Path) -> None:
    current = Path(directory.anchor)
    for component in directory.parts[1:-1]:
        current = current / component
        row = current.lstat()
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != ROOT_UID
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise ValueError("manual authority parent identity")


def _read_file_at(directory_fd: int, name: str) -> bytes:
    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    _validate_file(before)
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        _validate_file(opened)
        raw = b""
        while len(raw) <= MAX_BYTES:
            chunk = os.read(
                descriptor,
                min(65536, MAX_BYTES + 1 - len(raw)),
            )
            if not chunk:
                break
            raw += chunk
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if (
        not 1 <= len(raw) <= MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise ValueError("manual authority file changed")
    return raw


def _read_exact_directory(
    directory: Path,
    expected_inventory: tuple[str, ...],
) -> dict[str, bytes]:
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise ValueError("manual authority directory absolute")
    _validate_parent_chain(directory)
    before = directory.lstat()
    _validate_directory(before)
    descriptor = os.open(
        directory,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        _validate_directory(opened)
        if _stable(before) != _stable(opened):
            raise ValueError("manual authority directory changed")
        inventory_before = os.listdir(descriptor)
        if (
            len(inventory_before) != len(expected_inventory)
            or set(inventory_before) != set(expected_inventory)
        ):
            raise ValueError("manual authority inventory")
        material = {
            name: _read_file_at(descriptor, name)
            for name in expected_inventory
        }
        inventory_after = os.listdir(descriptor)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = directory.lstat()
    if (
        len(inventory_after) != len(inventory_before)
        or set(inventory_after) != set(inventory_before)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise ValueError("manual authority directory changed")
    return material


def _parse(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(label + " duplicate key")
            result[key] = item
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError(label + " number")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(label + " JSON") from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise ValueError(label + " canonical")
    return value


def _tool_identity(path: Path) -> os.stat_result:
    row = path.lstat()
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != 0
        or stat.S_IMODE(row.st_mode) & 0o022
    ):
        raise ValueError("manual authority tool identity")
    return row


def _canonical_spki_der(key: bytes) -> bytes:
    before = _tool_identity(OPENSSL)
    try:
        result = subprocess.run(
            [str(OPENSSL), "pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
            input=key,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("manual authority openssl") from exc
    if result.returncode != 0 or not result.stdout or _stable(OPENSSL.lstat()) != _stable(before):
        raise ValueError("manual authority public key")
    return result.stdout


def _canonical_public_pem(key: bytes) -> bytes:
    before = _tool_identity(OPENSSL)
    try:
        result = subprocess.run(
            [str(OPENSSL), "pkey", "-pubin", "-pubout"],
            input=key,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("manual authority openssl") from exc
    if (
        result.returncode != 0
        or not result.stdout
        or _stable(OPENSSL.lstat()) != _stable(before)
    ):
        raise ValueError("manual authority public key")
    return result.stdout


def _rsa_3072(key: bytes) -> bool:
    before = _tool_identity(OPENSSL)
    try:
        result = subprocess.run(
            [str(OPENSSL), "pkey", "-pubin", "-text", "-noout"],
            input=key,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    first = result.stdout.splitlines()[0] if result.stdout else b""
    return bool(
        result.returncode == 0
        and re.fullmatch(rb"(?:RSA )?Public-Key: \(3072 bit\)", first)
        and _stable(OPENSSL.lstat()) == _stable(before)
    )


def _decode_key(value: Any, label: str) -> tuple[bytes, str]:
    keys = {
        "issuer", "audience", "public_key_pem_base64",
        "public_key_sha256", "public_key_spki_sha256",
    }
    if type(value) is not dict or set(value) != keys:
        raise ValueError(label + " authority key schema")
    try:
        key = base64.b64decode(value["public_key_pem_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(label + " authority key encoding") from exc
    expected_issuer = f"noteai-item26-manual-cost-stop-{label}-v1"
    if (
        value.get("issuer") != expected_issuer
        or value.get("audience") != "noteai-item26-manual-cost-stop-verifier-v1"
        or not _hex64(value.get("public_key_sha256"))
        or not _hex64(value.get("public_key_spki_sha256"))
        or _sha(key) != value["public_key_sha256"]
        or b"-----BEGIN PUBLIC KEY-----" not in key
        or b"-----END PUBLIC KEY-----" not in key
        or _canonical_public_pem(key) != key
        or not _rsa_3072(key)
    ):
        raise ValueError(label + " authority key identity")
    spki = _sha(_canonical_spki_der(key))
    if spki != value["public_key_spki_sha256"]:
        raise ValueError(label + " authority key SPKI")
    return key, spki


def _verify_signature(payload: bytes, signature: bytes, key: bytes) -> bool:
    before = _tool_identity(OPENSSL)
    try:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, raw in {"payload": payload, "signature": signature, "key": key}.items():
                descriptor = os.open(base / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    os.write(descriptor, raw)
                finally:
                    os.close(descriptor)
            result = subprocess.run(
                [
                    str(OPENSSL), "dgst", "-sha256", "-verify", str(base / "key"),
                    "-signature", str(base / "signature"), str(base / "payload"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                timeout=10,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and _stable(OPENSSL.lstat()) == _stable(before)


def _git(
    args: list[str],
    *,
    root: Path,
    stdout: int = subprocess.PIPE,
) -> subprocess.CompletedProcess[bytes]:
    before = _tool_identity(GIT)
    result = subprocess.run(
        [str(GIT), "--no-replace-objects", *args],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0",
        },
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if _stable(GIT.lstat()) != _stable(before):
        raise ValueError("manual authority git identity")
    return result


def _git_blob_sha256(revision: str, ref: str, *, root: Path) -> str:
    if HEX40.fullmatch(revision or "") is None or not ref or ref.startswith("/") or ".." in Path(ref).parts:
        raise ValueError("manual authority git object")
    result = _git(["show", revision + ":" + ref], root=root)
    if result.returncode != 0 or not 1 <= len(result.stdout) <= MAX_BYTES:
        raise ValueError("manual authority git object")
    return _sha(result.stdout)


def git_blob_bytes(revision: str, ref: str, *, root: Path) -> bytes:
    if (
        HEX40.fullmatch(revision or "") is None
        or not ref
        or ref.startswith("/")
        or ".." in Path(ref).parts
    ):
        raise ValueError("manual authority git object")
    result = _git(["show", revision + ":" + ref], root=root)
    if result.returncode != 0 or not 1 <= len(result.stdout) <= MAX_BYTES:
        raise ValueError("manual authority git object")
    return result.stdout


def git_blob_absent(revision: str, ref: str, *, root: Path) -> bool:
    if (
        HEX40.fullmatch(revision or "") is None
        or not ref
        or ref.startswith("/")
        or ".." in Path(ref).parts
    ):
        raise ValueError("manual authority git object")
    commit = _git(
        ["cat-file", "-e", revision + "^{commit}"],
        root=root,
        stdout=subprocess.DEVNULL,
    )
    if commit.returncode != 0:
        raise ValueError("manual authority git revision")
    result = _git(
        ["cat-file", "-e", revision + ":" + ref],
        root=root,
        stdout=subprocess.DEVNULL,
    )
    return result.returncode != 0


def revision_is_strict_ancestor(
    earlier: str,
    later: str,
    *,
    root: Path,
) -> bool:
    return _ancestor(earlier, later, root=root)


def _ancestor(earlier: str, later: str, *, root: Path) -> bool:
    if earlier == later or HEX40.fullmatch(earlier or "") is None or HEX40.fullmatch(later or "") is None:
        return False
    result = _git(["merge-base", "--is-ancestor", earlier, later], root=root, stdout=subprocess.DEVNULL)
    return result.returncode == 0


def _validate_root(
    raw: bytes,
    *,
    expected_hash: str,
    root: Path,
) -> tuple[dict[str, Any], dict[str, tuple[bytes, str]]]:
    value = _parse(raw, "manual authority root")
    keys = {
        "schema", "task_id", "operation_id", "status", "repository",
        "source_ref", "m0_anchor_revision", "m0_ci",
        "root_frozen_before_action", "post_action_readback_only",
        "authorizes_new_action", "readiness_credit_allowed", "contract",
        "no_replay", "ledger_context", "provider", "confirmation", "ci",
    }
    if type(value) is not dict or set(value) != keys:
        raise ValueError("manual authority root schema")
    expected_contract = {"ref": CONTRACT_REF, "file_sha256": EXPECTED_CONTRACT_FILE_SHA256}
    expected_no_replay = {
        "ref": NO_REPLAY_REF,
        "file_sha256": EXPECTED_NO_REPLAY_FILE_SHA256,
        "registry_sha256": EXPECTED_NO_REPLAY_REGISTRY_SHA256,
        "entry_count": 29,
        "consumed_manual_mutation_set_sha256": EXPECTED_MUTATION_SET_SHA256,
    }
    historical_confirmation_projection = {
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "action": "IMMEDIATE_EXACT_OLD_CLONE_COST_STOP",
        "confirmed_at_utc": "2026-08-16T14:39:11.475Z",
        "old_clone_sha256": (
            "820121638125fcebe3b7c03f3416ddae1fef1a0a9f1de731320fa75dd69a1525"
        ),
        "allowed_mutations": [
            "ModifyDBInstanceDeletionProtection",
            "DeleteDBInstance",
        ],
        "future_fee_reusable": False,
        "root_frozen_before_action": False,
    }
    expected_ledger_context = {
        "handoff_ref": HANDOFF_REF,
        "handoff_revision": M0_ANCHOR_REVISION,
        "handoff_file_sha256": EXPECTED_HANDOFF_FILE_SHA256,
        "ledger_context_revision": LEDGER_CONTEXT_REVISION,
        "source_pre_tuple_sha256": EXPECTED_SOURCE_PRE_TUPLE_SHA256,
        "historical_confirmation": {
            "projection": historical_confirmation_projection,
            "projection_sha256": EXPECTED_HISTORICAL_CONFIRMATION_SHA256,
            "reusable_for_future_fee": False,
            "retroactive_root_authority": False,
        },
        "old_clone_create_identity_requires_actiontrail_rederivation": True,
    }
    computed_confirmation_sha256 = _sha(
        HISTORICAL_CONFIRMATION_DOMAIN
        + canonical_bytes(historical_confirmation_projection)[:-1]
    )
    if (
        not AUTHORITY_IMPLEMENTED
        or expected_hash != EXPECTED_AUTHORITY_ROOT_FILE_SHA256
        or _sha(raw) != expected_hash
        or value["schema"] != ROOT_SCHEMA
        or value["task_id"] != TASK_ID
        or value["operation_id"] != OPERATION_ID
        or value["status"] != "FROZEN_BEFORE_POST_ACTION_READBACK"
        or value["repository"] != REPOSITORY
        or value["source_ref"] != SOURCE_REF
        or value["m0_anchor_revision"] != M0_ANCHOR_REVISION
        or not _strict(value["m0_ci"], EXPECTED_M0_CI)
        or value["root_frozen_before_action"] is not False
        or value["post_action_readback_only"] is not True
        or value["authorizes_new_action"] is not False
        or value["readiness_credit_allowed"] is not False
        or not _strict(value["contract"], expected_contract)
        or not _strict(value["no_replay"], expected_no_replay)
        or not _strict(value["ledger_context"], expected_ledger_context)
        or computed_confirmation_sha256
        != EXPECTED_HISTORICAL_CONFIRMATION_SHA256
        or _git_blob_sha256(M0_ANCHOR_REVISION, CONTRACT_REF, root=root) != EXPECTED_CONTRACT_FILE_SHA256
        or _git_blob_sha256(M0_ANCHOR_REVISION, NO_REPLAY_REF, root=root) != EXPECTED_NO_REPLAY_FILE_SHA256
        or _git_blob_sha256(M0_ANCHOR_REVISION, HANDOFF_REF, root=root)
        != EXPECTED_HANDOFF_FILE_SHA256
    ):
        raise ValueError("manual authority root identity")
    decoded = {
        role: _decode_key(value[role], role)
        for role in ("provider", "confirmation", "ci")
    }
    if len({row[1] for row in decoded.values()}) != 3:
        raise ValueError("manual authority keys not distinct")
    return value, decoded


def load_activation_root(
    *,
    expected_control_revision: str,
    expected_authority_root_file_sha256: str = EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
    root: Path = ROOT,
    authority_directory: Path = AUTHORITY_DIRECTORY,
) -> dict[str, Any]:
    if not _ancestor(M0_ANCHOR_REVISION, expected_control_revision, root=root):
        raise ValueError("manual authority control revision")
    material = _read_exact_directory(authority_directory, ACTIVATION_INVENTORY)
    value, keys = _validate_root(
        material[ROOT_FILE],
        expected_hash=expected_authority_root_file_sha256,
        root=root,
    )
    return {
        "authority_root_file_sha256": _sha(material[ROOT_FILE]),
        "m0_anchor_revision": value["m0_anchor_revision"],
        "control_revision": expected_control_revision,
        "provider_key_spki_sha256": keys["provider"][1],
        "confirmation_key_spki_sha256": keys["confirmation"][1],
        "ci_key_spki_sha256": keys["ci"][1],
        "authority_keys_distinct": True,
        "root_frozen_before_action": False,
        "post_action_readback_only": True,
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
    }


def load_verified_projection(
    *,
    expected_control_revision: str,
    expected_authority_root_file_sha256: str = EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
    root: Path = ROOT,
    authority_directory: Path = AUTHORITY_DIRECTORY,
) -> tuple[VerifiedManualProjection, dict[str, Any]]:
    if not _ancestor(M0_ANCHOR_REVISION, expected_control_revision, root=root):
        raise ValueError("manual authority control revision")
    material = _read_exact_directory(authority_directory, CAPTURE_INVENTORY)
    root_value, keys = _validate_root(
        material[ROOT_FILE],
        expected_hash=expected_authority_root_file_sha256,
        root=root,
    )
    projection = extract_verified_projection(
        material[PROVIDER_RAW_FILE],
        material[ACTIONTRAIL_RAW_FILE],
        expected_control_revision=expected_control_revision,
    )
    binding = {
        "authority_root_file_sha256": _sha(material[ROOT_FILE]),
        "provider_raw_file_sha256": _sha(material[PROVIDER_RAW_FILE]),
        "actiontrail_raw_file_sha256": _sha(material[ACTIONTRAIL_RAW_FILE]),
        "provider_key_spki_sha256": keys["provider"][1],
        "confirmation_key_spki_sha256": keys["confirmation"][1],
        "ci_key_spki_sha256": keys["ci"][1],
        "authority_keys_distinct": True,
        "m0_anchor_revision": root_value["m0_anchor_revision"],
        "control_revision": expected_control_revision,
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
    }
    return projection, binding


def _envelope(
    value: Any,
    *,
    authority: str,
    key_row: dict[str, Any],
    key: bytes,
    schema: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"authority", "issuer", "audience", "payload", "signature_base64"}:
        raise ValueError("manual " + authority + " envelope schema")
    payload = value.get("payload")
    if (
        value.get("authority") != authority
        or value.get("issuer") != key_row["issuer"]
        or value.get("audience") != key_row["audience"]
        or type(payload) is not dict
        or payload.get("schema") != schema
        or payload.get("task_id") != TASK_ID
        or payload.get("operation_id") != OPERATION_ID
    ):
        raise ValueError("manual " + authority + " envelope identity")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("manual " + authority + " signature encoding") from exc
    if not signature or not _verify_signature(canonical_bytes(payload), signature, key):
        raise ValueError("manual " + authority + " signature")
    return payload


def _run_row(value: Any, *, event: str, revision: str) -> bool:
    return bool(
        type(value) is dict
        and set(value) == {
            "run_id", "job_id", "event", "attempt", "status",
            "conclusion", "head_sha", "completed_at_utc",
            "workflow_name", "workflow_path", "job_name", "job_count",
            "failed_step_count", "step_count", "unit_test_count",
            "postgres_test_count", "readiness_check_count",
            "quality_gate_pass_count", "quality_expected_fail_count",
            "error_annotation_count", "compose_config_success",
        }
        and type(value["run_id"]) is int and value["run_id"] > 0
        and type(value["job_id"]) is int and value["job_id"] > 0
        and value["event"] == event
        and type(value["attempt"]) is int
        and value["attempt"] == 1
        and value["status"] == "completed"
        and value["conclusion"] == "success"
        and value["head_sha"] == revision
        and _utc(value["completed_at_utc"]) is not None
        and value["workflow_name"] == "CI"
        and value["workflow_path"] == ".github/workflows/ci.yml"
        and value["job_name"] == "test"
        and type(value["job_count"]) is int
        and value["job_count"] == 1
        and type(value["failed_step_count"]) is int
        and value["failed_step_count"] == 0
        and type(value["step_count"]) is int
        and value["step_count"] == 22
        and type(value["unit_test_count"]) is int
        and value["unit_test_count"] >= 2331
        and type(value["postgres_test_count"]) is int
        and value["postgres_test_count"] == 6
        and type(value["readiness_check_count"]) is int
        and value["readiness_check_count"] >= 138
        and type(value["quality_gate_pass_count"]) is int
        and value["quality_gate_pass_count"] >= 7
        and type(value["quality_expected_fail_count"]) is int
        and value["quality_expected_fail_count"] == 1
        and type(value["error_annotation_count"]) is int
        and value["error_annotation_count"] == 0
        and value["compose_config_success"] is True
    )


def _validated_projection_exports(
    *,
    material: dict[str, bytes],
    root_value: dict[str, Any],
    keys: dict[str, tuple[bytes, str]],
    bundle: dict[str, Any],
    control_revision: str,
    expected_receipt_binding: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], VerifiedManualProjection]:
    expected_binding_keys = {
        "receipt_file_sha256",
        "receipt_semantic_sha256",
        "terminal_acceptance_sha256",
        "raw_closure_sha256",
    }
    if (
        type(expected_receipt_binding) is not dict
        or set(expected_receipt_binding) != expected_binding_keys
        or any(
            not _hex64(expected_receipt_binding.get(key))
            for key in expected_binding_keys
        )
    ):
        raise ValueError("manual receipt authority binding")
    confirmation_file = _parse(
        material[CONFIRMATION_FILE], "manual confirmation file"
    )
    if canonical_bytes(confirmation_file) != canonical_bytes(
        bundle["confirmation"]
    ):
        raise ValueError("manual confirmation envelope mismatch")
    provider = _envelope(
        bundle["provider"],
        authority="provider",
        key_row=root_value["provider"],
        key=keys["provider"][0],
        schema=PROVIDER_SCHEMA,
    )
    confirmation = _envelope(
        bundle["confirmation"],
        authority="confirmation",
        key_row=root_value["confirmation"],
        key=keys["confirmation"][0],
        schema=CONFIRMATION_SCHEMA,
    )
    projection = extract_verified_projection(
        material[PROVIDER_RAW_FILE],
        material[ACTIONTRAIL_RAW_FILE],
        expected_control_revision=control_revision,
    )
    provider_projection = projection.provider
    actiontrail_projection = projection.actiontrail
    actiontrail_events = {
        row.get("event_name"): row
        for row in actiontrail_projection.get("events", [])
        if type(row) is dict
    }
    protection_event = actiontrail_events.get(
        "ModifyDBInstanceDeletionProtection"
    )
    delete_event = actiontrail_events.get("DeleteDBInstance")
    clone_create = actiontrail_projection.get("clone_create")
    if (
        type(provider) is not dict
        or set(provider) != PROVIDER_PAYLOAD_KEYS
        or type(confirmation) is not dict
        or set(confirmation) != CONFIRMATION_PAYLOAD_KEYS
        or type(protection_event) is not dict
        or type(delete_event) is not dict
        or type(clone_create) is not dict
        or actiontrail_projection.get(
            "historical_mutation_request_ids_rederived"
        ) is not True
        or actiontrail_projection.get(
            "historical_request_bodies_rederived"
        ) is not True
        or actiontrail_projection.get(
            "historical_client_tokens_rederived"
        ) is not True
        or actiontrail_projection.get(
            "old_clone_create_identity_rederived"
        ) is not True
    ):
        raise ValueError("manual ActionTrail identity incomplete")
    raw_mutation_set_sha256 = consumed_mutation_identity_set_sha256(
        protection_request_id_sha256=protection_event.get(
            "provider_request_id_sha256"
        ),
        protection_request_body_sha256=protection_event.get(
            "request_body_sha256"
        ),
        protection_client_token_sha256=protection_event.get(
            "client_token_sha256"
        ),
        delete_request_id_sha256=delete_event.get(
            "provider_request_id_sha256"
        ),
        delete_request_body_sha256=delete_event.get(
            "request_body_sha256"
        ),
        delete_client_token_present=delete_event.get(
            "client_token_present"
        ),
    )
    provider_digest_fields = {
        "authority_root_file_sha256",
        "provider_raw_file_sha256",
        "actiontrail_raw_file_sha256",
        "provider_projection_sha256",
        "actiontrail_projection_sha256",
        "terminal_acceptance_sha256",
        "raw_closure_sha256",
        "receipt_file_sha256",
        "receipt_semantic_sha256",
    }
    if (
        any(not _hex64(provider.get(key)) for key in provider_digest_fields)
        or provider.get("control_revision") != control_revision
        or _utc(provider.get("signed_at_utc")) is None
        or provider.get("observed_at_utc")
        != provider_projection.get("observed_at_utc")
        or provider.get("observed_at_utc")
        != actiontrail_projection.get("observed_at_utc")
        or provider.get("authority_root_file_sha256")
        != _sha(material[ROOT_FILE])
        or provider.get("provider_raw_file_sha256")
        != _sha(material[PROVIDER_RAW_FILE])
        or provider.get("actiontrail_raw_file_sha256")
        != _sha(material[ACTIONTRAIL_RAW_FILE])
        or provider.get("provider_projection_sha256")
        != _semantic(provider_projection)
        or provider.get("actiontrail_projection_sha256")
        != _semantic(actiontrail_projection)
        or any(
            provider.get(key) != value
            for key, value in expected_receipt_binding.items()
        )
        or provider.get("confirmation_export_semantic_sha256")
        != _semantic(confirmation)
        or provider.get("historical_confirmation_sha256")
        != EXPECTED_HISTORICAL_CONFIRMATION_SHA256
        or provider.get("old_clone_sha256") != EXPECTED_OLD_CLONE_SHA256
        or provider.get("old_clone_name_sha256")
        != EXPECTED_OLD_CLONE_NAME_SHA256
        or provider.get("source_pre_tuple_sha256")
        != EXPECTED_SOURCE_PRE_TUPLE_SHA256
        or provider.get("source_post_tuple_sha256")
        != provider_projection["source"]["tuple_sha256"]
        or provider.get("source_pre_tuple_sha256")
        != provider.get("source_post_tuple_sha256")
        or provider.get("billing_snapshot_sha256")
        != _semantic(provider_projection["billing"])
        or provider.get("no_replay_registry_sha256")
        != EXPECTED_NO_REPLAY_REGISTRY_SHA256
        or provider.get("consumed_mutation_identity_set_sha256")
        != EXPECTED_MUTATION_SET_SHA256
        or raw_mutation_set_sha256 != EXPECTED_MUTATION_SET_SHA256
        or provider.get("old_clone_create_request_sha256")
        != clone_create.get("provider_request_id_sha256")
        or provider.get("old_clone_create_body_sha256")
        != clone_create.get("request_body_sha256")
        or provider.get("old_clone_client_token_sha256")
        != clone_create.get("client_token_sha256")
        or provider.get("protection_disable_request_id_sha256")
        != EXPECTED_PROTECTION_REQUEST_ID_SHA256
        or provider.get("protection_disable_request_id_sha256")
        != protection_event.get("provider_request_id_sha256")
        or provider.get("protection_disable_request_body_sha256")
        != protection_event.get("request_body_sha256")
        or provider.get("protection_disable_client_token_sha256")
        != EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256
        or provider.get("protection_disable_client_token_sha256")
        != protection_event.get("client_token_sha256")
        or provider.get("delete_request_id_sha256")
        != EXPECTED_DELETE_REQUEST_ID_SHA256
        or provider.get("delete_request_id_sha256")
        != delete_event.get("provider_request_id_sha256")
        or provider.get("delete_request_body_sha256")
        != delete_event.get("request_body_sha256")
        or provider.get("delete_client_token_present") is not False
        or delete_event.get("client_token_present") is not False
        or provider.get("old_clone_absent") is not True
        or provider_projection["old_clone"]["absent"] is not True
        or provider.get("source_unchanged") is not True
        or provider.get("historical_billing_only") is not True
        or provider_projection["billing"][
            "historical_snapshot_only"
        ] is not True
        or provider.get("new_action_authorized") is not False
        or provider.get("readiness_credit_added") is not False
    ):
        raise ValueError("manual provider projection binding")
    confirmation_digest_fields = {
        "authority_root_file_sha256",
        "terminal_acceptance_sha256",
        "receipt_file_sha256",
        "receipt_semantic_sha256",
        "raw_closure_sha256",
        "provider_projection_sha256",
        "actiontrail_projection_sha256",
        "historical_user_confirmation_sha256",
        "no_replay_registry_sha256",
        "consumed_mutation_identity_set_sha256",
    }
    if (
        any(
            not _hex64(confirmation.get(key))
            for key in confirmation_digest_fields
        )
        or confirmation.get("control_revision") != control_revision
        or confirmation.get("authority_root_file_sha256")
        != _sha(material[ROOT_FILE])
        or any(
            confirmation.get(key) != value
            for key, value in expected_receipt_binding.items()
        )
        or confirmation.get("provider_projection_sha256")
        != _semantic(provider_projection)
        or confirmation.get("actiontrail_projection_sha256")
        != _semantic(actiontrail_projection)
        or confirmation.get("no_replay_registry_sha256")
        != EXPECTED_NO_REPLAY_REGISTRY_SHA256
        or confirmation.get("historical_user_confirmation_sha256")
        != EXPECTED_HISTORICAL_CONFIRMATION_SHA256
        or confirmation.get("consumed_mutation_identity_set_sha256")
        != EXPECTED_MUTATION_SET_SHA256
        or confirmation.get("post_action_observed_at_utc")
        != provider.get("observed_at_utc")
        or confirmation.get("retroactive_action_authorization") is not False
        or confirmation.get("new_action_authorization") is not False
        or confirmation.get("readiness_credit_added") is not False
        or _utc(confirmation.get("confirmed_at_utc")) is None
        or _utc(provider.get("observed_at_utc")) is None
        or _utc(confirmation.get("confirmed_at_utc"))
        <= _utc(provider.get("observed_at_utc"))
    ):
        raise ValueError("manual confirmation binding")
    return provider, confirmation, projection


def validate_authority_bundle(
    *,
    expected_authority_root_file_sha256: str,
    expected_receipt_binding: dict[str, str],
    root: Path = ROOT,
    authority_directory: Path = AUTHORITY_DIRECTORY,
) -> tuple[list[str], dict[str, Any] | None]:
    if (
        not AUTHORITY_IMPLEMENTED
        or expected_authority_root_file_sha256 != EXPECTED_AUTHORITY_ROOT_FILE_SHA256
        or not _hex64(expected_authority_root_file_sha256)
    ):
        return ["manual cost-stop authority is not finalized"], None
    try:
        material = _read_exact_directory(authority_directory, FINAL_INVENTORY)
        root_value, keys = _validate_root(
            material[ROOT_FILE],
            expected_hash=expected_authority_root_file_sha256,
            root=root,
        )
        bundle = _parse(material[BUNDLE_FILE], "manual authority bundle")
        confirmation_file = _parse(material[CONFIRMATION_FILE], "manual confirmation file")
        bundle_keys = {
            "schema", "task_id", "operation_id", "status",
            "control_revision", "evidence_revision", "terminal_revision",
            "provider", "confirmation", "ci",
        }
        if type(bundle) is not dict or set(bundle) != bundle_keys:
            raise ValueError("manual authority bundle schema")
        control_revision = bundle["control_revision"]
        evidence_revision = bundle["evidence_revision"]
        terminal_revision = bundle["terminal_revision"]
        if (
            bundle["schema"] != BUNDLE_SCHEMA
            or bundle["task_id"] != TASK_ID
            or bundle["operation_id"] != OPERATION_ID
            or bundle["status"] != "POST_ACTION_RECONCILIATION_TERMINAL_AUTHORITY"
            or any(HEX40.fullmatch(value or "") is None for value in (control_revision, evidence_revision, terminal_revision))
            or not _ancestor(M0_ANCHOR_REVISION, control_revision, root=root)
            or not _ancestor(control_revision, evidence_revision, root=root)
            or not _ancestor(evidence_revision, terminal_revision, root=root)
        ):
            raise ValueError("manual authority bundle identity")
        if canonical_bytes(confirmation_file) != canonical_bytes(bundle["confirmation"]):
            raise ValueError("manual confirmation envelope mismatch")
        provider, confirmation, projection = _validated_projection_exports(
            material=material,
            root_value=root_value,
            keys=keys,
            bundle=bundle,
            control_revision=control_revision,
            expected_receipt_binding=expected_receipt_binding,
        )
        ci = _envelope(
            bundle["ci"], authority="ci",
            key_row=root_value["ci"], key=keys["ci"][0], schema=CI_SCHEMA,
        )
        provider_projection = projection.provider
        actiontrail_projection = projection.actiontrail
        ci_keys = {
            "schema", "task_id", "operation_id", "control_revision",
            "evidence_revision", "terminal_revision", "repository", "ref",
            "authority_root_file_sha256", "provider_export_semantic_sha256",
            "confirmation_export_semantic_sha256", "provider_raw_file_sha256",
            "actiontrail_raw_file_sha256", "receipt_file_sha256",
            "receipt_semantic_sha256", "terminal_acceptance_sha256",
            "raw_closure_sha256",
            "evidence_file_sha256", "checkpoint_file_sha256", "control_sources",
            "control_push", "control_pull_request", "evidence_push",
            "evidence_pull_request", "terminal_push", "terminal_pull_request",
            "terminal_accepted_at_utc",
        }
        if type(ci) is not dict or set(ci) != ci_keys:
            raise ValueError("manual CI payload schema")
        if (
            ci["control_revision"] != control_revision
            or ci["evidence_revision"] != evidence_revision
            or ci["terminal_revision"] != terminal_revision
            or ci["repository"] != REPOSITORY
            or ci["ref"] != SOURCE_REF
            or ci["authority_root_file_sha256"] != _sha(material[ROOT_FILE])
            or ci["provider_export_semantic_sha256"] != _semantic(provider)
            or ci["confirmation_export_semantic_sha256"] != _semantic(confirmation)
            or ci["provider_raw_file_sha256"] != _sha(material[PROVIDER_RAW_FILE])
            or ci["actiontrail_raw_file_sha256"] != _sha(material[ACTIONTRAIL_RAW_FILE])
            or any(
                ci.get(key) != value
                for key, value in expected_receipt_binding.items()
            )
            or any(not _hex64(ci.get(key)) for key in ("receipt_file_sha256", "evidence_file_sha256", "checkpoint_file_sha256"))
            or _utc(ci["terminal_accepted_at_utc"]) is None
            or _utc(ci["terminal_accepted_at_utc"])
            <= _utc(confirmation["confirmed_at_utc"])
            or type(ci["control_sources"]) is not dict
            or set(ci["control_sources"]) != set(REQUIRED_CONTROL_SOURCE_REFS)
        ):
            raise ValueError("manual CI payload identity")
        for ref in REQUIRED_CONTROL_SOURCE_REFS:
            expected = ci["control_sources"].get(ref)
            if not _hex64(expected) or any(
                _git_blob_sha256(revision, ref, root=root) != expected
                for revision in (control_revision, evidence_revision, terminal_revision)
            ):
                raise ValueError("manual control source drift")
        run_rows = (
            (ci["control_push"], "push", control_revision),
            (ci["control_pull_request"], "pull_request", control_revision),
            (ci["evidence_push"], "push", evidence_revision),
            (ci["evidence_pull_request"], "pull_request", evidence_revision),
            (ci["terminal_push"], "push", terminal_revision),
            (ci["terminal_pull_request"], "pull_request", terminal_revision),
        )
        if not all(_run_row(row, event=event, revision=revision) for row, event, revision in run_rows):
            raise ValueError("manual CI run identity")
        if len({row["run_id"] for row, _event, _revision in run_rows}) != 6 or len({row["job_id"] for row, _event, _revision in run_rows}) != 6:
            raise ValueError("manual CI run reuse")
        control_completed = max(
            _utc(ci["control_push"]["completed_at_utc"]),
            _utc(ci["control_pull_request"]["completed_at_utc"]),
        )
        evidence_first_completed = min(
            _utc(ci["evidence_push"]["completed_at_utc"]),
            _utc(ci["evidence_pull_request"]["completed_at_utc"]),
        )
        evidence_completed = max(
            _utc(ci["evidence_push"]["completed_at_utc"]),
            _utc(ci["evidence_pull_request"]["completed_at_utc"]),
        )
        terminal_first_completed = min(
            _utc(ci["terminal_push"]["completed_at_utc"]),
            _utc(ci["terminal_pull_request"]["completed_at_utc"]),
        )
        terminal_completed = max(
            _utc(ci["terminal_push"]["completed_at_utc"]),
            _utc(ci["terminal_pull_request"]["completed_at_utc"]),
        )
        first_raw_started = min(
            _utc(provider_projection["first_started_at_utc"]),
            _utc(actiontrail_projection["first_started_at_utc"]),
        )
        raw_observed = _utc(provider_projection["observed_at_utc"])
        if not (
            control_completed < first_raw_started <= raw_observed
            < evidence_first_completed
            and evidence_completed < terminal_first_completed
            and terminal_completed
            < _utc(confirmation["confirmed_at_utc"])
            <= _utc(provider["signed_at_utc"])
            < _utc(ci["terminal_accepted_at_utc"])
        ):
            raise ValueError("manual authority timeline")
    except OSError:
        return ["manual cost-stop authority material is not installed"], None
    except (KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        return ["manual cost-stop authority rejected: " + str(exc)], None
    return [], {
        "authority_root_file_sha256": _sha(material[ROOT_FILE]),
        "authority_bundle_file_sha256": _sha(material[BUNDLE_FILE]),
        "provider_raw_file_sha256": _sha(material[PROVIDER_RAW_FILE]),
        "actiontrail_raw_file_sha256": _sha(material[ACTIONTRAIL_RAW_FILE]),
        "provider_projection_sha256": _semantic(provider_projection),
        "actiontrail_projection_sha256": _semantic(
            actiontrail_projection
        ),
        "confirmation_envelope_file_sha256": _sha(material[CONFIRMATION_FILE]),
        "receipt_file_sha256": ci["receipt_file_sha256"],
        "receipt_semantic_sha256": ci["receipt_semantic_sha256"],
        "evidence_file_sha256": ci["evidence_file_sha256"],
        "checkpoint_file_sha256": ci["checkpoint_file_sha256"],
        "raw_closure_sha256": ci["raw_closure_sha256"],
        "provider_export_semantic_sha256": _semantic(provider),
        "confirmation_export_semantic_sha256": _semantic(confirmation),
        "provider_key_spki_sha256": keys["provider"][1],
        "confirmation_key_spki_sha256": keys["confirmation"][1],
        "ci_key_spki_sha256": keys["ci"][1],
        "authority_keys_distinct": True,
        "terminal_acceptance_sha256": provider["terminal_acceptance_sha256"],
        "old_clone_sha256": provider["old_clone_sha256"],
        "old_clone_name_sha256": provider["old_clone_name_sha256"],
        "source_pre_tuple_sha256": provider["source_pre_tuple_sha256"],
        "source_post_tuple_sha256": provider["source_post_tuple_sha256"],
        "billing_snapshot_sha256": provider["billing_snapshot_sha256"],
        "no_replay_registry_sha256": provider[
            "no_replay_registry_sha256"
        ],
        "old_clone_create_request_sha256": provider[
            "old_clone_create_request_sha256"
        ],
        "old_clone_create_body_sha256": provider[
            "old_clone_create_body_sha256"
        ],
        "old_clone_client_token_sha256": provider[
            "old_clone_client_token_sha256"
        ],
        "protection_disable_request_id_sha256": provider[
            "protection_disable_request_id_sha256"
        ],
        "protection_disable_request_body_sha256": provider[
            "protection_disable_request_body_sha256"
        ],
        "protection_disable_client_token_sha256": provider[
            "protection_disable_client_token_sha256"
        ],
        "delete_request_id_sha256": provider["delete_request_id_sha256"],
        "delete_request_body_sha256": provider[
            "delete_request_body_sha256"
        ],
        "delete_client_token_present": False,
        "consumed_mutation_identity_set_sha256": provider[
            "consumed_mutation_identity_set_sha256"
        ],
        "post_action_observed_at_utc": provider["observed_at_utc"],
        "control_revision": control_revision,
        "evidence_revision": evidence_revision,
        "terminal_revision": terminal_revision,
        "terminal_accepted_at_utc": ci["terminal_accepted_at_utc"],
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
    }


__all__ = [
    "ACTIONTRAIL_RAW_PATH", "ACTIVATION_INVENTORY", "AUTHORITY_BUNDLE_PATH",
    "AUTHORITY_DIRECTORY", "AUTHORITY_IMPLEMENTED", "AUTHORITY_ROOT_PATH",
    "BUNDLE_SCHEMA", "CAPTURE_INVENTORY", "CONFIRMATION_ENVELOPE_PATH",
    "EXPECTED_AUTHORITY_ROOT_FILE_SHA256", "FINAL_INVENTORY", "OPERATION_ID",
    "PROVIDER_RAW_PATH", "ROOT_SCHEMA", "ROOT_UID", "TASK_ID", "VERIFIER_REF",
    "git_blob_absent", "git_blob_bytes", "load_activation_root",
    "load_verified_projection", "revision_is_strict_ancestor",
    "validate_authority_bundle",
]
