#!/usr/bin/env python3
"""Verify detached provider and CI authority for Item 26.

Repository artifacts cannot authorize their own production claims.  The
root-owned authority root must be installed and hash-frozen in a source
checkpoint before any successor cloud action.  Only the signed bundle and
content-free source/restored manifests may be installed after execution.  The
pre-execution root is intentionally absent from this source-only checkpoint,
so this verifier fails closed by default.
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
VERIFIER_REF = "tools/verify_item26_external_authority_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
ROOT_SCHEMA = "noteai.item26.external-authority-root.v1"
BUNDLE_SCHEMA = "noteai.item26.external-authority-bundle.v1"
PROVIDER_SCHEMA = "noteai.item26.provider-authority-export.v1"
CI_SCHEMA = "noteai.item26.ci-authority-export.v1"
AUTHORITY_ROOT_PATH = Path(
    "/Library/Application Support/NoteAI/item26-external-authority-root-v1.json"
)
AUTHORITY_BUNDLE_PATH = Path(
    "/Library/Application Support/NoteAI/item26-external-authority-bundle-v1.json"
)
SOURCE_MANIFEST_PATH = Path(
    "/Library/Application Support/NoteAI/item26-source-manifest-v1.json"
)
RESTORED_MANIFEST_PATH = Path(
    "/Library/Application Support/NoteAI/item26-restored-manifest-v1.json"
)
OPENSSL = Path("/usr/bin/openssl")
GIT = Path("/usr/bin/git")
REPOSITORY = "iamyusen1314/noteai"
SOURCE_REF = "refs/heads/codex/quality-stabilization-real-chain"
REQUIRED_CONTROL_SOURCE_REFS = (
    "tools/internal_deployment_readiness_gate.py",
    "tools/verify_pitr_restore_evidence.py",
    "tools/verify_item26_external_authority_v1.py",
    "tools/validate_item26_pitr_restore_result_v1.py",
    "tools/build_item26_pitr_restore_evidence_v1.py",
    "model/storage_recovery_evidence.py",
    "deploy/production/plans/item26-no-replay-registry-v1.json",
)
STAGE_ONLY_CONTROL_SOURCE_REFS = {
    "tools/internal_deployment_readiness_gate.py",
}
MAX_BYTES = 1024 * 1024
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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
    )


def _read_root_owned(path: Path) -> bytes:
    parent = path.parent.lstat()
    before = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != 0
        or stat.S_IMODE(parent.st_mode) & 0o022
        or not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != 0
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) & 0o022
    ):
        raise ValueError("authority_identity")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
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
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(label + "_duplicate_key")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError(label + "_number")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
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
                str(OPENSSL),
                "pkey",
                "-pubin",
                "-inform",
                "PEM",
                "-outform",
                "DER",
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


def _decode_key(value: Any, label: str) -> tuple[bytes, str]:
    expected = {
        "issuer",
        "audience",
        "public_key_pem_base64",
        "public_key_sha256",
        "public_key_spki_sha256",
    }
    if type(value) is not dict or set(value) != expected:
        raise ValueError(label + "_key_schema")
    try:
        key = base64.b64decode(value["public_key_pem_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(label + "_key_encoding") from exc
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
        raise ValueError(label + "_key_identity")
    spki_sha256 = _sha(_canonical_spki_der(key))
    if spki_sha256 != value["public_key_spki_sha256"]:
        raise ValueError(label + "_key_spki_identity")
    return key, spki_sha256


def _verify_signature(payload: bytes, signature: bytes, key: bytes) -> bool:
    try:
        tool = OPENSSL.lstat()
        if (
            not stat.S_ISREG(tool.st_mode)
            or stat.S_ISLNK(tool.st_mode)
            or tool.st_uid != 0
            or stat.S_IMODE(tool.st_mode) & 0o022
        ):
            return False
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, raw in {
                "payload": payload,
                "signature": signature,
                "key": key,
            }.items():
                descriptor = os.open(
                    base / name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                try:
                    os.write(descriptor, raw)
                finally:
                    os.close(descriptor)
            result = subprocess.run(
                [
                    str(OPENSSL),
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(base / "key"),
                    "-signature",
                    str(base / "signature"),
                    str(base / "payload"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
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
            not stat.S_ISREG(tool.st_mode)
            or stat.S_ISLNK(tool.st_mode)
            or tool.st_uid != 0
            or stat.S_IMODE(tool.st_mode) & 0o022
        ):
            return False
        result = subprocess.run(
            [
                str(GIT),
                "--no-replace-objects",
                "merge-base",
                "--is-ancestor",
                frozen,
                source_revision,
            ],
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
    return result.returncode == 0 and _stable(GIT.lstat()) == _stable(tool)


def _git_blob_sha256(revision: str, ref: str, *, root: Path) -> str:
    if (
        HEX40.fullmatch(revision or "") is None
        or ref not in REQUIRED_CONTROL_SOURCE_REFS
    ):
        raise ValueError("control_source_identity")
    try:
        tool = GIT.lstat()
        if (
            not stat.S_ISREG(tool.st_mode)
            or stat.S_ISLNK(tool.st_mode)
            or tool.st_uid != 0
            or stat.S_IMODE(tool.st_mode) & 0o022
        ):
            raise ValueError("git_identity")
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
        raise ValueError("control_source_identity") from exc
    if (
        result.returncode != 0
        or not 1 <= len(result.stdout) <= MAX_BYTES * 2
        or _stable(GIT.lstat()) != _stable(tool)
    ):
        raise ValueError("control_source_identity")
    return _sha(result.stdout)


def git_tree_binding(revision: str, *, root: Path = ROOT) -> tuple[str, int]:
    if HEX40.fullmatch(revision or "") is None:
        raise ValueError("source_tree_identity")
    try:
        tool = GIT.lstat()
        if (
            not stat.S_ISREG(tool.st_mode)
            or stat.S_ISLNK(tool.st_mode)
            or tool.st_uid != 0
            or stat.S_IMODE(tool.st_mode) & 0o022
        ):
            raise ValueError("git_identity")
        result = subprocess.run(
            [
                str(GIT),
                "--no-replace-objects",
                "ls-tree",
                "-r",
                "--full-tree",
                "-z",
                revision,
            ],
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
        raise ValueError("source_tree_identity") from exc
    if (
        result.returncode != 0
        or not result.stdout
        or len(result.stdout) > MAX_BYTES * 16
        or not result.stdout.endswith(b"\0")
        or _stable(GIT.lstat()) != _stable(tool)
    ):
        raise ValueError("source_tree_identity")
    return _sha(result.stdout), result.stdout.count(b"\0")


def _current_file_sha256(ref: str, *, root: Path) -> str:
    if ref not in REQUIRED_CONTROL_SOURCE_REFS:
        raise ValueError("control_source_identity")
    path = root / ref
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) & 0o022
    ):
        raise ValueError("control_source_identity")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        raw = b""
        while len(raw) <= MAX_BYTES * 2:
            chunk = os.read(
                descriptor,
                min(65536, MAX_BYTES * 2 + 1 - len(raw)),
            )
            if not chunk:
                break
            raw += chunk
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (
        not 1 <= len(raw) <= MAX_BYTES * 2
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise ValueError("control_source_identity")
    return _sha(raw)


def _envelope(
    value: Any,
    *,
    authority: str,
    key_row: dict[str, Any],
    key: bytes,
    schema: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "authority",
        "issuer",
        "audience",
        "payload",
        "signature_base64",
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


def validate_authority_bundle(
    *,
    expected_authority_root_file_sha256: str,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    if HEX64.fullmatch(expected_authority_root_file_sha256 or "") is None:
        return ["Item26 external authority inputs are not finalized"], None
    try:
        root_raw = _read_root_owned(AUTHORITY_ROOT_PATH)
        bundle_raw = _read_root_owned(AUTHORITY_BUNDLE_PATH)
        source_manifest_raw = _read_root_owned(SOURCE_MANIFEST_PATH)
        restored_manifest_raw = _read_root_owned(RESTORED_MANIFEST_PATH)
        authority_root = _parse(root_raw, "root")
        bundle = _parse(bundle_raw, "bundle")
        source_manifest = _parse(source_manifest_raw, "source_manifest")
        restored_manifest = _parse(restored_manifest_raw, "restored_manifest")
        if set(authority_root) != {
            "schema",
            "task_id",
            "status",
            "repository",
            "source_ref",
            "frozen_before_revision",
            "provider",
            "ci",
        } or set(bundle) != {
            "schema",
            "task_id",
            "execution_revision",
            "evidence_revision",
            "terminal_revision",
            "provider",
            "ci",
        }:
            raise ValueError("authority_schema")
        execution_revision = bundle["execution_revision"]
        evidence_revision = bundle["evidence_revision"]
        terminal_revision = bundle["terminal_revision"]
        if (
            authority_root["schema"] != ROOT_SCHEMA
            or authority_root["task_id"] != TASK_ID
            or authority_root["status"] != "FROZEN_BEFORE_EXECUTION"
            or authority_root["repository"] != REPOSITORY
            or authority_root["source_ref"] != SOURCE_REF
            or _sha(root_raw) != expected_authority_root_file_sha256
            or bundle["schema"] != BUNDLE_SCHEMA
            or bundle["task_id"] != TASK_ID
            or any(
                HEX40.fullmatch(value or "") is None
                for value in (
                    execution_revision,
                    evidence_revision,
                    terminal_revision,
                )
            )
            or len(
                {execution_revision, evidence_revision, terminal_revision}
            )
            != 3
            or not _frozen_before(
                authority_root["frozen_before_revision"],
                execution_revision,
                root=root,
            )
            or not _frozen_before(
                execution_revision,
                evidence_revision,
                root=root,
            )
            or not _frozen_before(
                evidence_revision,
                terminal_revision,
                root=root,
            )
        ):
            raise ValueError("authority_identity")
        provider_key, provider_spki = _decode_key(
            authority_root["provider"], "provider"
        )
        ci_key, ci_spki = _decode_key(authority_root["ci"], "ci")
        if provider_spki == ci_spki:
            raise ValueError("authority_keys_not_distinct")
        provider = _envelope(
            bundle["provider"],
            authority="provider",
            key_row=authority_root["provider"],
            key=provider_key,
            schema=PROVIDER_SCHEMA,
        )
        ci = _envelope(
            bundle["ci"],
            authority="ci",
            key_row=authority_root["ci"],
            key=ci_key,
            schema=CI_SCHEMA,
        )
        if set(provider) != {
            "schema",
            "task_id",
            "execution_revision",
            "observed_at_utc",
            "receipt_file_sha256",
            "terminal_acceptance_sha256",
            "raw_closure_sha256",
            "source_manifest_file_sha256",
            "source_manifest_sha256",
            "restored_manifest_file_sha256",
            "restored_manifest_sha256",
        } or set(ci) != {
            "schema",
            "task_id",
            "execution_revision",
            "evidence_revision",
            "terminal_revision",
            "repository",
            "ref",
            "evidence_file_sha256",
            "receipt_file_sha256",
            "checkpoint_file_sha256",
            "no_replay_registry_file_sha256",
            "control_sources",
            "execution_push",
            "execution_pull_request",
            "evidence_push",
            "evidence_pull_request",
            "terminal_push",
            "terminal_pull_request",
        }:
            raise ValueError("authority_payload_schema")
        if (
            provider["execution_revision"] != execution_revision
            or UTC.fullmatch(provider["observed_at_utc"] or "") is None
            or any(
                HEX64.fullmatch(provider[key] or "") is None
                for key in (
                    "receipt_file_sha256",
                    "terminal_acceptance_sha256",
                    "raw_closure_sha256",
                    "source_manifest_file_sha256",
                    "source_manifest_sha256",
                    "restored_manifest_file_sha256",
                    "restored_manifest_sha256",
                )
            )
            or provider["source_manifest_file_sha256"]
            != _sha(source_manifest_raw)
            or source_manifest.get("manifest_sha256")
            != provider["source_manifest_sha256"]
            or provider["restored_manifest_file_sha256"]
            != _sha(restored_manifest_raw)
            or restored_manifest.get("manifest_sha256")
            != provider["restored_manifest_sha256"]
            or ci["execution_revision"] != execution_revision
            or ci["evidence_revision"] != evidence_revision
            or ci["terminal_revision"] != terminal_revision
            or ci["repository"] != REPOSITORY
            or ci["ref"] != SOURCE_REF
            or any(
                HEX64.fullmatch(ci[key] or "") is None
                for key in (
                    "evidence_file_sha256",
                    "receipt_file_sha256",
                    "checkpoint_file_sha256",
                    "no_replay_registry_file_sha256",
                )
            )
            or ci["receipt_file_sha256"]
            != provider["receipt_file_sha256"]
        ):
            raise ValueError("authority_payload_identity")
        control_sources = ci["control_sources"]
        if (
            type(control_sources) is not list
            or len(control_sources) != len(REQUIRED_CONTROL_SOURCE_REFS)
        ):
            raise ValueError("control_source_schema")
        for ref, row in zip(REQUIRED_CONTROL_SOURCE_REFS, control_sources):
            if (
                type(row) is not dict
                or set(row) != {"path", "sha256", "unchanged_across_stages"}
                or row["path"] != ref
                or HEX64.fullmatch(row["sha256"] or "") is None
                or row["unchanged_across_stages"] is not True
                or any(
                    _git_blob_sha256(revision, ref, root=root)
                    != row["sha256"]
                    for revision in (
                        execution_revision,
                        evidence_revision,
                        terminal_revision,
                    )
                )
                or (
                    ref not in STAGE_ONLY_CONTROL_SOURCE_REFS
                    and _current_file_sha256(ref, root=root)
                    != row["sha256"]
                )
            ):
                raise ValueError("control_source_identity")
        run_ids: list[str] = []
        job_ids: list[str] = []
        for key, event, revision in (
            ("execution_push", "push", execution_revision),
            (
                "execution_pull_request",
                "pull_request",
                execution_revision,
            ),
            ("evidence_push", "push", evidence_revision),
            (
                "evidence_pull_request",
                "pull_request",
                evidence_revision,
            ),
            ("terminal_push", "push", terminal_revision),
            (
                "terminal_pull_request",
                "pull_request",
                terminal_revision,
            ),
        ):
            row = ci[key]
            if (
                type(row) is not dict
                or set(row) != {
                    "event",
                    "head_sha",
                    "attempt",
                    "status",
                    "conclusion",
                    "job_count",
                    "failed_step_count",
                    "run_id_sha256",
                    "job_id_sha256",
                    "step_count",
                    "unit_test_count",
                    "postgres_test_count",
                    "readiness_check_count",
                    "error_annotation_count",
                }
                or row["event"] != event
                or row["head_sha"] != revision
                or row["attempt"] != 1
                or row["status"] != "completed"
                or row["conclusion"] != "success"
                or row["job_count"] != 1
                or row["failed_step_count"] != 0
                or HEX64.fullmatch(row["run_id_sha256"] or "") is None
                or HEX64.fullmatch(row["job_id_sha256"] or "") is None
                or row["run_id_sha256"] == row["job_id_sha256"]
                or row["step_count"] != 22
                or type(row["unit_test_count"]) is not int
                or row["unit_test_count"] < 2243
                or row["postgres_test_count"] != 6
                or type(row["readiness_check_count"]) is not int
                or row["readiness_check_count"] < 138
                or row["error_annotation_count"] != 0
            ):
                raise ValueError("ci_run_identity")
            run_ids.append(row["run_id_sha256"])
            job_ids.append(row["job_id_sha256"])
        if (
            len(set(run_ids)) != len(run_ids)
            or len(set(job_ids)) != len(job_ids)
            or set(run_ids) & set(job_ids)
        ):
            raise ValueError("ci_run_identity_reused")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ["Item26 external authority invalid: " + str(exc)], None
    return [], {
        "authority_root_file_sha256": _sha(root_raw),
        "authority_bundle_file_sha256": _sha(bundle_raw),
        "provider_export_semantic_sha256": _semantic(provider),
        "ci_export_semantic_sha256": _semantic(ci),
        "provider_key_spki_sha256": provider_spki,
        "ci_key_spki_sha256": ci_spki,
        "authority_keys_distinct": True,
        "execution_revision": execution_revision,
        "evidence_revision": evidence_revision,
        "terminal_revision": terminal_revision,
        "receipt_file_sha256": provider["receipt_file_sha256"],
        "evidence_file_sha256": ci["evidence_file_sha256"],
        "checkpoint_file_sha256": ci["checkpoint_file_sha256"],
        "no_replay_registry_file_sha256": ci[
            "no_replay_registry_file_sha256"
        ],
        "terminal_acceptance_sha256": provider[
            "terminal_acceptance_sha256"
        ],
        "raw_closure_sha256": provider["raw_closure_sha256"],
        "source_manifest": source_manifest,
        "restored_manifest": restored_manifest,
        "source_manifest_file_sha256": _sha(source_manifest_raw),
        "restored_manifest_file_sha256": _sha(restored_manifest_raw),
    }
