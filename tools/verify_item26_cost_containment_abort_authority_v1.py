#!/usr/bin/env python3
"""Verify the pre-action authority for the Item 26 cost-containment abort.

This module contains no cloud executor.  It loads an exact root-owned
pre-action directory, rederives the RDS/source/billing preflight from native
provider responses, validates a canonical exact plan, and verifies detached
provider and user-confirmation signatures under three pre-frozen distinct
SPKI keys.  The CI key verifies the exact execution-revision push/PR runs here
and is cross-bound again by the later terminal authority bundle.

The main abort verifier keeps its root hash empty until an operator installs
this directory and commits a new exact source revision.  Consequently this
module is reviewable and testable without authorizing a cloud mutation.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any

from extract_item26_cost_containment_abort_raw_v1 import (
    ExtractionError,
    parse_capture,
    project_instance_bill,
    project_rds_inventory,
    require_exact_capture_slots,
)


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":COST_CONTAINMENT_ABORT:v1"
REPOSITORY = "iamyusen1314/noteai"
SOURCE_REF = "refs/heads/codex/quality-stabilization-real-chain"
ANCHOR_REVISION = "80c5091f9736c79f9034be3b83522f8025b9f364"
PREACTION_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/"
    "item26-cost-containment-abort-v1/preaction"
)
PREACTION_FILES = (
    "authority-root-v1.json",
    "preflight-raw-v1.json",
    "exact-plan-v1.json",
    "state-manifest-v1.json",
    "provider-preflight-envelope-v1.json",
    "execution-ci-envelope-v1.json",
    "confirmation-envelope-v1.json",
)
ROOT_SCHEMA = "noteai.item26.cost-containment-abort-authority-root.v1"
PLAN_SCHEMA = "noteai.item26.cost-containment-abort-exact-plan.v1"
STATE_SCHEMA = "noteai.item26.cost-containment-abort-state-manifest.v1"
PROVIDER_PREFLIGHT_SCHEMA = (
    "noteai.item26.cost-containment-abort-provider-preflight-authority.v1"
)
CONFIRMATION_SCHEMA = (
    "noteai.item26.cost-containment-abort-user-confirmation-authority.v1"
)
EXECUTION_CI_SCHEMA = (
    "noteai.item26.cost-containment-abort-execution-ci-authority.v1"
)
ENVELOPE_SCHEMA = "noteai.item26.cost-containment-abort-signed-envelope.v1"
RELEASE_CONTRACT_REF = (
    "deploy/production/plans/item26-rds-release-billing-contract-v1.json"
)
RELEASE_CONTRACT_SHA256 = (
    "985d08f9fb5350b3c48e11b1193a683991e60ad4b8dd4ca087c00ae4ebb908e2"
)
NO_REPLAY_REGISTRY_REF = "deploy/production/plans/item26-no-replay-registry-v1.json"
NO_REPLAY_REGISTRY_SHA256 = (
    "763ae967af95f55347e427f9df8e6c7014b16e645957417915e3ccd44d20e5d9"
)
CONTROL_SOURCE_REFS = (
    "tools/extract_item26_cost_containment_abort_raw_v1.py",
    "tools/verify_item26_cost_containment_abort_authority_v1.py",
    "tools/validate_item26_cost_containment_abort_result_v1.py",
    RELEASE_CONTRACT_REF,
    NO_REPLAY_REGISTRY_REF,
)
ROOT_UID = 0
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_CONFIRMATION_TTL = timedelta(minutes=10)
MAX_PREFLIGHT_AGE = timedelta(minutes=2)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DECIMAL_CNY = re.compile(r"^(0|[1-9]\d*)(?:\.\d{1,6})?$")
PLAN_DOMAIN = b"noteai-item26-cost-containment-abort-exact-plan-file-v1\0"
OPENSSL = Path("/usr/bin/openssl")
GIT = Path("/usr/bin/git")


class AuthorityError(ValueError):
    """A fixed non-sensitive authority failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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


def _semantic(value: Any) -> str:
    return _sha(_canonical(value)[:-1])


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


def _utc(value: Any, label: str) -> datetime:
    if type(value) is not str or UTC.fullmatch(value) is None:
        raise AuthorityError(label)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise AuthorityError(label) from exc


def _decimal(value: Any, label: str) -> Decimal:
    if type(value) is not str or DECIMAL_CNY.fullmatch(value) is None:
        raise AuthorityError(label)
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise AuthorityError(label) from exc
    if not parsed.is_finite() or parsed < 0:
        raise AuthorityError(label)
    return parsed


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityError("duplicate_json_key")
        result[key] = value
    return result


def _parse(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_FILE_BYTES or b"\0" in raw:
        raise AuthorityError(label + "_shape")
    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                AuthorityError(label + "_number")
            ),
        )
    except AuthorityError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityError(label + "_json") from exc
    if type(value) is not dict or _canonical(value) != raw:
        raise AuthorityError(label + "_canonical")
    return value


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
        or row.st_uid != ROOT_UID
        or stat.S_IMODE(row.st_mode) != 0o700
    ):
        raise AuthorityError("preaction_directory_identity")


def _validate_file(row: os.stat_result) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != ROOT_UID
        or row.st_nlink != 1
        or stat.S_IMODE(row.st_mode) != 0o600
    ):
        raise AuthorityError("preaction_file_identity")


def _read_at(directory_fd: int, name: str) -> bytes:
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
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_FILE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= MAX_FILE_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise AuthorityError("preaction_file_unstable")
    return raw


def load_root_owned_preaction(directory: Path = PREACTION_DIRECTORY) -> dict[str, bytes]:
    """Load the exact stable root-owned file set without following links."""

    if not isinstance(directory, Path) or not directory.is_absolute():
        raise AuthorityError("preaction_directory_absolute")
    try:
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
            inventory_before = os.listdir(descriptor)
            if (
                len(inventory_before) != len(PREACTION_FILES)
                or set(inventory_before) != set(PREACTION_FILES)
            ):
                raise AuthorityError("preaction_inventory")
            files = {name: _read_at(descriptor, name) for name in PREACTION_FILES}
            inventory_after = os.listdir(descriptor)
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = directory.lstat()
    except AuthorityError:
        raise
    except OSError as exc:
        raise AuthorityError("preaction_read") from exc
    if (
        set(inventory_after) != set(inventory_before)
        or len(inventory_after) != len(inventory_before)
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise AuthorityError("preaction_directory_unstable")
    return files


def _trusted_tool(path: Path, label: str) -> os.stat_result:
    try:
        row = path.lstat()
    except OSError as exc:
        raise AuthorityError(label + "_identity") from exc
    if (
        not path.is_absolute()
        or not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != 0
        or stat.S_IMODE(row.st_mode) & 0o022
    ):
        raise AuthorityError(label + "_identity")
    return row


def _canonical_spki_der(key: bytes) -> bytes:
    before = _trusted_tool(OPENSSL, "openssl")
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
        raise AuthorityError("openssl_identity") from exc
    if (
        result.returncode != 0
        or not 1 <= len(result.stdout) <= MAX_FILE_BYTES
        or _stable(OPENSSL.lstat()) != _stable(before)
    ):
        raise AuthorityError("public_key_spki")
    return result.stdout


def _decode_key(value: Any, label: str) -> tuple[bytes, str]:
    keys = {
        "issuer",
        "audience",
        "public_key_pem_base64",
        "public_key_sha256",
        "public_key_spki_sha256",
    }
    if type(value) is not dict or set(value) != keys:
        raise AuthorityError(label + "_key_schema")
    try:
        key = base64.b64decode(value["public_key_pem_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise AuthorityError(label + "_key_encoding") from exc
    if (
        type(value["issuer"]) is not str
        or not value["issuer"]
        or type(value["audience"]) is not str
        or not value["audience"]
        or type(value["public_key_sha256"]) is not str
        or HEX64.fullmatch(value["public_key_sha256"]) is None
        or type(value["public_key_spki_sha256"]) is not str
        or HEX64.fullmatch(value["public_key_spki_sha256"]) is None
        or _sha(key) != value["public_key_sha256"]
        or b"-----BEGIN PUBLIC KEY-----" not in key
        or b"-----END PUBLIC KEY-----" not in key
    ):
        raise AuthorityError(label + "_key_identity")
    spki = _sha(_canonical_spki_der(key))
    if spki != value["public_key_spki_sha256"]:
        raise AuthorityError(label + "_key_spki")
    return key, spki


def _verify_signature(payload: bytes, signature: bytes, key: bytes) -> bool:
    before = _trusted_tool(OPENSSL, "openssl")
    try:
        with tempfile.TemporaryDirectory(prefix="noteai-item26-abort-signature-") as directory:
            base = Path(directory)
            for name, raw in {"payload": payload, "signature": signature, "key": key}.items():
                descriptor = os.open(
                    base / name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    offset = 0
                    while offset < len(raw):
                        offset += os.write(descriptor, raw[offset:])
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


def _envelope(
    value: Any,
    *,
    authority: str,
    key_row: dict[str, Any],
    key: bytes,
    payload_schema: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema", "authority", "issuer", "audience", "payload", "signature_base64"
    }:
        raise AuthorityError(authority + "_envelope_schema")
    payload = value["payload"]
    if (
        value["schema"] != ENVELOPE_SCHEMA
        or value["authority"] != authority
        or value["issuer"] != key_row["issuer"]
        or value["audience"] != key_row["audience"]
        or type(payload) is not dict
        or payload.get("schema") != payload_schema
        or payload.get("task_id") != TASK_ID
        or payload.get("operation_id") != OPERATION_ID
    ):
        raise AuthorityError(authority + "_envelope_identity")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise AuthorityError(authority + "_signature_encoding") from exc
    if not signature or not _verify_signature(_canonical(payload), signature, key):
        raise AuthorityError(authority + "_signature")
    return payload


def _git_blob_sha256(revision: str, ref: str, *, root: Path) -> str:
    if HEX40.fullmatch(revision or "") is None or ref not in CONTROL_SOURCE_REFS:
        raise AuthorityError("control_source_identity")
    before = _trusted_tool(GIT, "git")
    try:
        result = subprocess.run(
            [str(GIT), "--no-replace-objects", "show", revision + ":" + ref],
            cwd=root,
            env={
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "LANG": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthorityError("control_source_unavailable") from exc
    if (
        result.returncode != 0
        or not 1 <= len(result.stdout) <= MAX_FILE_BYTES
        or _stable(GIT.lstat()) != _stable(before)
    ):
        raise AuthorityError("control_source_unavailable")
    return _sha(result.stdout)


def _current_control_source_sha256(ref: str, *, root: Path) -> str:
    if ref not in CONTROL_SOURCE_REFS:
        raise AuthorityError("control_source_identity")
    path = root / ref
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise AuthorityError("current_control_source_identity")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            total = 0
            while total <= MAX_FILE_BYTES:
                chunk = os.read(
                    descriptor, min(65536, MAX_FILE_BYTES + 1 - total)
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except AuthorityError:
        raise
    except OSError as exc:
        raise AuthorityError("current_control_source_unavailable") from exc
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= MAX_FILE_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise AuthorityError("current_control_source_unstable")
    return _sha(raw)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _strict_ancestor(ancestor: str, descendant: str, *, root: Path) -> bool:
    if (
        HEX40.fullmatch(ancestor or "") is None
        or HEX40.fullmatch(descendant or "") is None
        or ancestor == descendant
    ):
        return False
    before = _trusted_tool(GIT, "git")
    try:
        result = subprocess.run(
            [str(GIT), "--no-replace-objects", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            env={
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "LANG": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and _stable(GIT.lstat()) == _stable(before)


def plan_sha256(plan: dict[str, Any]) -> str:
    projection = dict(plan)
    projection.pop("plan_sha256", None)
    return _sha(PLAN_DOMAIN + _canonical(projection))


def _validate_plan(plan: Any, *, execution_revision: str) -> None:
    keys = {
        "schema",
        "task_id",
        "operation_id",
        "execution_revision",
        "region_id",
        "clone_instance_id",
        "source_instance_id",
        "preflight_slots",
        "billing_cycle",
        "release_billing_contract_ref",
        "release_billing_contract_sha256",
        "recorded_minimum_pretax_gross_cny",
        "recorded_minimum_service_seconds",
        "approved_24h_ceiling_cny",
        "protection_disable_client_token",
        "planned_mutations",
        "new_paid_resource_allowed",
        "database_connection_allowed",
        "readiness_credit_allowed",
        "partial_state_policy",
        "plan_sha256",
    }
    if type(plan) is not dict or set(plan) != keys:
        raise AuthorityError("plan_schema")
    expected_requests = [
        {
            "sequence": 1,
            "operation": "ModifyDBInstanceDeletionProtection",
            "request": {
                "Action": "ModifyDBInstanceDeletionProtection",
                "Version": "2014-08-15",
                "RegionId": plan.get("region_id"),
                "DBInstanceId": plan.get("clone_instance_id"),
                "DeletionProtection": False,
                "ClientToken": plan.get("protection_disable_client_token"),
            },
        },
        {
            "sequence": 2,
            "operation": "DeleteDBInstance",
            "request": {
                "Action": "DeleteDBInstance",
                "Version": "2014-08-15",
                "RegionId": plan.get("region_id"),
                "DBInstanceId": plan.get("clone_instance_id"),
            },
        },
    ]
    if (
        plan["schema"] != PLAN_SCHEMA
        or plan["task_id"] != TASK_ID
        or plan["operation_id"] != OPERATION_ID
        or plan["execution_revision"] != execution_revision
        or type(plan["region_id"]) is not str
        or not plan["region_id"]
        or type(plan["clone_instance_id"]) is not str
        or not plan["clone_instance_id"]
        or type(plan["source_instance_id"]) is not str
        or not plan["source_instance_id"]
        or plan["clone_instance_id"] == plan["source_instance_id"]
        or not _strict(
            plan["preflight_slots"],
            {"clone": "clone_preflight", "source": "source_preflight", "billing": "billing_preflight"},
        )
        or plan["billing_cycle"] != "2026-08"
        or plan["release_billing_contract_ref"] != RELEASE_CONTRACT_REF
        or plan["release_billing_contract_sha256"] != RELEASE_CONTRACT_SHA256
        or plan["recorded_minimum_pretax_gross_cny"] != "185.658"
        or plan["recorded_minimum_service_seconds"] != 331200
        or plan["approved_24h_ceiling_cny"] != "76.824"
        or type(plan["protection_disable_client_token"]) is not str
        or not plan["protection_disable_client_token"]
        or not _strict(plan["planned_mutations"], expected_requests)
        or plan["new_paid_resource_allowed"] is not False
        or plan["database_connection_allowed"] is not False
        or plan["readiness_credit_allowed"] is not False
        or plan["partial_state_policy"] != "STOP_NO_RESUME_V1"
        or type(plan["plan_sha256"]) is not str
        or plan["plan_sha256"] != plan_sha256(plan)
    ):
        raise AuthorityError("plan_identity")


def _validate_ci_run(value: Any, *, event: str, revision: str) -> None:
    keys = {
        "event",
        "head_sha",
        "attempt",
        "status",
        "conclusion",
        "job_count",
        "failed_step_count",
        "run_id_sha256",
        "job_id_sha256",
        "unit_test_count",
        "postgres_test_count",
        "readiness_check_count",
        "error_annotation_count",
    }
    if (
        type(value) is not dict
        or set(value) != keys
        or value["event"] != event
        or value["head_sha"] != revision
        or value["attempt"] != 1
        or value["status"] != "completed"
        or value["conclusion"] != "success"
        or value["job_count"] != 1
        or value["failed_step_count"] != 0
        or type(value["run_id_sha256"]) is not str
        or HEX64.fullmatch(value["run_id_sha256"]) is None
        or type(value["job_id_sha256"]) is not str
        or HEX64.fullmatch(value["job_id_sha256"]) is None
        or type(value["unit_test_count"]) is not int
        or value["unit_test_count"] < 1
        or value["postgres_test_count"] != 6
        or type(value["readiness_check_count"]) is not int
        or value["readiness_check_count"] < 138
        or value["error_annotation_count"] != 0
    ):
        raise AuthorityError("execution_ci_run")


def validate_preaction_authority(
    *,
    expected_authority_root_file_sha256: str,
    expected_execution_revision: str,
    root: Path = ROOT,
    directory: Path = PREACTION_DIRECTORY,
) -> tuple[list[str], dict[str, Any] | None]:
    """Validate one fresh signed pre-action package without emitting raw IDs."""

    if (
        HEX64.fullmatch(expected_authority_root_file_sha256 or "") is None
        or HEX40.fullmatch(expected_execution_revision or "") is None
    ):
        return ["abort preaction authority inputs are not finalized"], None
    try:
        files = load_root_owned_preaction(directory)
        authority_root = _parse(files["authority-root-v1.json"], "root")
        plan = _parse(files["exact-plan-v1.json"], "plan")
        state = _parse(files["state-manifest-v1.json"], "state")
        provider_envelope = _parse(
            files["provider-preflight-envelope-v1.json"], "provider_preflight"
        )
        ci_envelope = _parse(files["execution-ci-envelope-v1.json"], "execution_ci")
        confirmation_envelope = _parse(
            files["confirmation-envelope-v1.json"], "confirmation"
        )
        root_keys = {
            "schema", "task_id", "operation_id", "status", "repository", "source_ref",
            "frozen_before_revision", "release_billing_contract_ref",
            "release_billing_contract_sha256", "no_replay_registry_ref",
            "no_replay_registry_sha256", "control_sources", "provider", "confirmation",
            "ci", "partial_state_policy",
        }
        if type(authority_root) is not dict or set(authority_root) != root_keys:
            raise AuthorityError("root_schema")
        if (
            authority_root["schema"] != ROOT_SCHEMA
            or authority_root["task_id"] != TASK_ID
            or authority_root["operation_id"] != OPERATION_ID
            or authority_root["status"] != "FROZEN_BEFORE_ABORT_EXECUTION"
            or authority_root["repository"] != REPOSITORY
            or authority_root["source_ref"] != SOURCE_REF
            or authority_root["frozen_before_revision"] != ANCHOR_REVISION
            or authority_root["release_billing_contract_ref"] != RELEASE_CONTRACT_REF
            or authority_root["release_billing_contract_sha256"] != RELEASE_CONTRACT_SHA256
            or authority_root["no_replay_registry_ref"] != NO_REPLAY_REGISTRY_REF
            or authority_root["no_replay_registry_sha256"] != NO_REPLAY_REGISTRY_SHA256
            or authority_root["partial_state_policy"] != "STOP_NO_RESUME_V1"
            or _sha(files["authority-root-v1.json"])
            != expected_authority_root_file_sha256
            or not _strict_ancestor(ANCHOR_REVISION, expected_execution_revision, root=root)
        ):
            raise AuthorityError("root_identity")
        control_sources = authority_root["control_sources"]
        if type(control_sources) is not list or len(control_sources) != len(CONTROL_SOURCE_REFS):
            raise AuthorityError("root_control_sources")
        for ref, row in zip(CONTROL_SOURCE_REFS, control_sources):
            if (
                type(row) is not dict
                or set(row) != {"path", "sha256"}
                or row["path"] != ref
                or type(row["sha256"]) is not str
                or HEX64.fullmatch(row["sha256"]) is None
                or _git_blob_sha256(expected_execution_revision, ref, root=root)
                != row["sha256"]
                or _current_control_source_sha256(ref, root=root)
                != row["sha256"]
            ):
                raise AuthorityError("root_control_source_identity")
        provider_key, provider_spki = _decode_key(authority_root["provider"], "provider")
        confirmation_key, confirmation_spki = _decode_key(
            authority_root["confirmation"], "confirmation"
        )
        ci_key, ci_spki = _decode_key(authority_root["ci"], "ci")
        if len({provider_spki, confirmation_spki, ci_spki}) != 3:
            raise AuthorityError("root_authority_keys_not_distinct")
        _validate_plan(plan, execution_revision=expected_execution_revision)
        capture = parse_capture(files["preflight-raw-v1.json"], expected_phase="PREFLIGHT")
        if capture.source_revision != expected_execution_revision:
            raise AuthorityError("preflight_capture_revision")
        slots = plan["preflight_slots"]
        require_exact_capture_slots(
            capture,
            {
                slots["clone"]: "DescribeDBInstances",
                slots["source"]: "DescribeDBInstances",
                slots["billing"]: "QueryInstanceBill",
            },
        )
        clone = project_rds_inventory(
            capture,
            slot=slots["clone"],
            region_id=plan["region_id"],
            instance_id=plan["clone_instance_id"],
            expected_count=1,
        )
        source = project_rds_inventory(
            capture,
            slot=slots["source"],
            region_id=plan["region_id"],
            instance_id=plan["source_instance_id"],
            expected_count=1,
        )
        billing = project_instance_bill(
            capture,
            slot=slots["billing"],
            instance_id=plan["clone_instance_id"],
            billing_cycle=plan["billing_cycle"],
        )
        clone_state = clone["instances"][0]
        source_state = source["instances"][0]
        if (
            clone_state["status"] != "Running"
            or clone_state["pay_type"] != "Postpaid"
            or clone_state["engine"] != "PostgreSQL"
            or not clone_state["engine_version"].startswith("16")
            or clone_state["deletion_protection"] is not True
            or source_state["status"] != "Running"
            or source_state["pay_type"] != "Prepaid"
            or _decimal(billing["pretax_gross_cny"], "billing_gross")
            < _decimal(plan["recorded_minimum_pretax_gross_cny"], "billing_minimum")
            or billing["service_seconds"] < plan["recorded_minimum_service_seconds"]
            or not _decimal(billing["pretax_gross_cny"], "billing_gross")
            > _decimal(plan["approved_24h_ceiling_cny"], "billing_ceiling")
        ):
            raise AuthorityError("preflight_state")
        provider = _envelope(
            provider_envelope,
            authority="provider",
            key_row=authority_root["provider"],
            key=provider_key,
            payload_schema=PROVIDER_PREFLIGHT_SCHEMA,
        )
        execution_ci = _envelope(
            ci_envelope,
            authority="ci",
            key_row=authority_root["ci"],
            key=ci_key,
            payload_schema=EXECUTION_CI_SCHEMA,
        )
        confirmation = _envelope(
            confirmation_envelope,
            authority="confirmation",
            key_row=authority_root["confirmation"],
            key=confirmation_key,
            payload_schema=CONFIRMATION_SCHEMA,
        )
        provider_expected = {
            "schema": PROVIDER_PREFLIGHT_SCHEMA,
            "task_id": TASK_ID,
            "operation_id": OPERATION_ID,
            "execution_revision": expected_execution_revision,
            "authority_root_file_sha256": expected_authority_root_file_sha256,
            "preflight_raw_file_sha256": _sha(files["preflight-raw-v1.json"]),
            "plan_file_sha256": _sha(files["exact-plan-v1.json"]),
            "plan_sha256": plan["plan_sha256"],
            "state_manifest_file_sha256": _sha(files["state-manifest-v1.json"]),
            "execution_ci_semantic_sha256": _semantic(execution_ci),
            "observed_at_utc": capture.observed_at_utc,
            "clone_projection_sha256": _semantic(clone),
            "source_projection_sha256": _semantic(source),
            "billing_projection_sha256": _semantic(billing),
            "release_billing_contract_sha256": RELEASE_CONTRACT_SHA256,
            "no_replay_registry_sha256": NO_REPLAY_REGISTRY_SHA256,
        }
        if not _strict(provider, provider_expected):
            raise AuthorityError("provider_preflight_payload")
        ci_expected_keys = {
            "schema", "task_id", "operation_id", "execution_revision",
            "authority_root_file_sha256", "repository", "ref", "control_sources",
            "execution_push", "execution_pull_request",
        }
        if type(execution_ci) is not dict or set(execution_ci) != ci_expected_keys:
            raise AuthorityError("execution_ci_payload_schema")
        if (
            execution_ci["schema"] != EXECUTION_CI_SCHEMA
            or execution_ci["task_id"] != TASK_ID
            or execution_ci["operation_id"] != OPERATION_ID
            or execution_ci["execution_revision"] != expected_execution_revision
            or execution_ci["authority_root_file_sha256"]
            != expected_authority_root_file_sha256
            or execution_ci["repository"] != REPOSITORY
            or execution_ci["ref"] != SOURCE_REF
            or not _strict(execution_ci["control_sources"], control_sources)
        ):
            raise AuthorityError("execution_ci_payload_identity")
        _validate_ci_run(
            execution_ci["execution_push"],
            event="push",
            revision=expected_execution_revision,
        )
        _validate_ci_run(
            execution_ci["execution_pull_request"],
            event="pull_request",
            revision=expected_execution_revision,
        )
        if (
            execution_ci["execution_push"]["run_id_sha256"]
            == execution_ci["execution_pull_request"]["run_id_sha256"]
            or execution_ci["execution_push"]["job_id_sha256"]
            == execution_ci["execution_pull_request"]["job_id_sha256"]
        ):
            raise AuthorityError("execution_ci_identity_reuse")
        state_keys = {
            "schema", "task_id", "operation_id", "execution_revision",
            "confirmation_nonce_sha256", "state", "consumed_nonce_count",
            "mutation_intent_count", "mutation_result_count", "partial_state_count",
            "automatic_retry_allowed",
        }
        if type(state) is not dict or set(state) != state_keys:
            raise AuthorityError("state_schema")
        confirmation_nonce = confirmation.get("confirmation_nonce_sha256")
        if (
            state["schema"] != STATE_SCHEMA
            or state["task_id"] != TASK_ID
            or state["operation_id"] != OPERATION_ID
            or state["execution_revision"] != expected_execution_revision
            or state["confirmation_nonce_sha256"] != confirmation_nonce
            or state["state"] != "FRESH_NO_INTENT"
            or state["consumed_nonce_count"] != 0
            or state["mutation_intent_count"] != 0
            or state["mutation_result_count"] != 0
            or state["partial_state_count"] != 0
            or state["automatic_retry_allowed"] is not False
        ):
            raise AuthorityError("state_identity")
        confirmation_expected = {
            "schema": CONFIRMATION_SCHEMA,
            "task_id": TASK_ID,
            "operation_id": OPERATION_ID,
            "execution_revision": expected_execution_revision,
            "authority_root_file_sha256": expected_authority_root_file_sha256,
            "provider_preflight_semantic_sha256": _semantic(provider),
            "preflight_raw_file_sha256": _sha(files["preflight-raw-v1.json"]),
            "plan_file_sha256": _sha(files["exact-plan-v1.json"]),
            "plan_sha256": plan["plan_sha256"],
            "state_manifest_file_sha256": _sha(files["state-manifest-v1.json"]),
            "execution_ci_semantic_sha256": _semantic(execution_ci),
            "confirmation_nonce_sha256": confirmation_nonce,
            "approved_at_utc": confirmation.get("approved_at_utc"),
            "expires_at_utc": confirmation.get("expires_at_utc"),
            "allowed_mutations": [
                "ModifyDBInstanceDeletionProtection", "DeleteDBInstance"
            ],
            "new_paid_resource_allowed": False,
            "database_connection_allowed": False,
            "readiness_credit_allowed": False,
            "partial_state_policy": "STOP_NO_RESUME_V1",
        }
        if not _strict(confirmation, confirmation_expected) or not (
            type(confirmation_nonce) is str and HEX64.fullmatch(confirmation_nonce)
        ):
            raise AuthorityError("confirmation_payload")
        observed = _utc(capture.observed_at_utc, "preflight_observed_at")
        approved = _utc(confirmation["approved_at_utc"], "confirmation_approved_at")
        expires = _utc(confirmation["expires_at_utc"], "confirmation_expires_at")
        if (
            not observed <= approved < expires
            or approved - observed > MAX_PREFLIGHT_AGE
            or expires - approved > MAX_CONFIRMATION_TTL
            or not approved <= _now_utc() < expires
        ):
            raise AuthorityError("confirmation_time_boundary")
        return [], {
            "execution_revision": expected_execution_revision,
            "authority_root_file_sha256": expected_authority_root_file_sha256,
            "preflight_raw_file_sha256": _sha(files["preflight-raw-v1.json"]),
            "plan_file_sha256": _sha(files["exact-plan-v1.json"]),
            "plan_sha256": plan["plan_sha256"],
            "provider_preflight_envelope_file_sha256": _sha(
                files["provider-preflight-envelope-v1.json"]
            ),
            "execution_ci_envelope_file_sha256": _sha(
                files["execution-ci-envelope-v1.json"]
            ),
            "confirmation_envelope_file_sha256": _sha(
                files["confirmation-envelope-v1.json"]
            ),
            "state_manifest_file_sha256": _sha(files["state-manifest-v1.json"]),
            "confirmation_nonce_sha256": confirmation_nonce,
            "provider_key_spki_sha256": provider_spki,
            "confirmation_key_spki_sha256": confirmation_spki,
            "ci_key_spki_sha256": ci_spki,
            "fresh_no_intent": True,
            "dispatch_scope": "EXACT_CLONE_PROTECTION_DISABLE_AND_DELETE_ONLY",
        }
    except (
        AuthorityError,
        ExtractionError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        IndexError,
    ) as exc:
        code = exc.code if isinstance(exc, (AuthorityError, ExtractionError)) else "unavailable"
        return ["abort preaction authority rejected: " + code], None


__all__ = [
    "ANCHOR_REVISION",
    "AuthorityError",
    "CONTROL_SOURCE_REFS",
    "PREACTION_DIRECTORY",
    "PREACTION_FILES",
    "ROOT_SCHEMA",
    "EXECUTION_CI_SCHEMA",
    "load_root_owned_preaction",
    "plan_sha256",
    "validate_preaction_authority",
]
