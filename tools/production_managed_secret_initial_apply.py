#!/usr/bin/env python3
"""Perform the one-time managed-secret apply without plaintext persistence."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

try:
    from tools import production_managed_secret_files as managed_files
    from tools import production_managed_secret_roles as managed_roles
    from tools.production_secret_envelope import (
        SecretEnvelopeError,
        decrypt_payload,
        encrypt_payload,
    )
except ModuleNotFoundError:
    import production_managed_secret_files as managed_files  # type: ignore[no-redef]
    import production_managed_secret_roles as managed_roles  # type: ignore[no-redef]
    from production_secret_envelope import (  # type: ignore[no-redef]
        SecretEnvelopeError,
        decrypt_payload,
        encrypt_payload,
    )


TASK_ID = managed_roles.TASK_ID
EXECUTION_ROOT = Path("/var/lib/noteai/managed-secrets-execution-v1")
API_C_PUBLIC_KEY = EXECUTION_ROOT / "api-c-public.pem"
API_F_PUBLIC_KEY = EXECUTION_ROOT / "api-f-public.pem"
API_F_PRIVATE_KEY = EXECUTION_ROOT / "api-f-private.pem"
API_F_BUNDLE = EXECUTION_ROOT / "api-f-bundle.enc"
RECOVERY_BUNDLE = EXECUTION_ROOT / "api-c-recovery.enc"


class InitialManagedSecretError(RuntimeError):
    """A fixed, Secret-free initial-apply failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _private_execution_root() -> None:
    try:
        root_stat = EXECUTION_ROOT.lstat()
    except OSError as exc:
        raise InitialManagedSecretError("execution_root_missing") from exc
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_ISLNK(root_stat.st_mode)
        or root_stat.st_uid != 0
        or root_stat.st_gid != 0
        or stat.S_IMODE(root_stat.st_mode) != 0o700
    ):
        raise InitialManagedSecretError("execution_root_metadata")


def _write_ciphertext(path: Path, body: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.fchown(descriptor, 0, 0)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError as exc:
        raise InitialManagedSecretError("ciphertext_write") from exc


def _database_url(base_database_url: str, role: str, password: str) -> str:
    try:
        parsed = urlsplit(base_database_url)
        base_user = unquote(parsed.username or "")
    except (TypeError, ValueError) as exc:
        raise InitialManagedSecretError("control_database_url_shape") from exc
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not base_user
        or parsed.password in (None, "")
        or not parsed.hostname
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        raise InitialManagedSecretError("control_database_url_shape")
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = (
        f"{quote(role, safe='')}:{quote(password, safe='')}@"
        f"{hostname}{port}"
    )
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, "")
    )


def _passwords() -> dict[str, str]:
    values = {
        role: secrets.token_urlsafe(48)
        for role in managed_roles.TARGET_LOGIN_ROLES
    }
    return managed_roles.validate_passwords(values)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def apply_api_c(control_database_url: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise InitialManagedSecretError("root_required")
    _private_execution_root()
    for path in (API_C_PUBLIC_KEY, API_F_PUBLIC_KEY):
        if path.is_symlink() or not path.is_file():
            raise InitialManagedSecretError("public_key_missing")
    if API_F_BUNDLE.exists() or RECOVERY_BUNDLE.exists():
        raise InitialManagedSecretError("ciphertext_residue")
    passwords = _passwords()
    database_urls = {
        role: _database_url(control_database_url, role, passwords[role])
        for role in managed_roles.TARGET_LOGIN_ROLES
    }
    api_c_payload = {
        "database_urls": {
            "admin": database_urls["noteai_admin_runtime"],
            "payment": database_urls["noteai_payment"],
            "ai_worker": database_urls["noteai_ai_worker"],
        }
    }
    api_f_payload = {
        "database_urls": {
            "xhs_trends": database_urls["noteai_xhs_trends"],
            "xhs_tracking": database_urls["noteai_xhs_tracking"],
        }
    }
    try:
        managed_files.stage_distribution("API-C", api_c_payload)
        _write_ciphertext(
            API_F_BUNDLE,
            encrypt_payload(_json_bytes(api_f_payload), API_F_PUBLIC_KEY),
        )
        _write_ciphertext(
            RECOVERY_BUNDLE,
            encrypt_payload(
                _json_bytes({"passwords": passwords}),
                API_C_PUBLIC_KEY,
            ),
        )
    except BaseException as exc:
        if managed_files.TASK_ROOT.exists():
            try:
                managed_files.rollback_distribution("API-C")
            except BaseException:
                pass
        API_F_BUNDLE.unlink(missing_ok=True)
        RECOVERY_BUNDLE.unlink(missing_ok=True)
        raise InitialManagedSecretError("pre_connect_prepare") from exc

    connected = False
    try:
        conn = managed_roles._connect(control_database_url)
        connected = True
        try:
            role_result = managed_roles.apply_contract(conn, passwords)
        finally:
            conn.close()
    except BaseException as exc:
        if not connected:
            managed_files.rollback_distribution("API-C")
            API_F_BUNDLE.unlink(missing_ok=True)
            RECOVERY_BUNDLE.unlink(missing_ok=True)
            raise InitialManagedSecretError("pre_connect_database") from exc
        raise InitialManagedSecretError("connected_unknown_role_apply") from exc

    try:
        file_result = managed_files.promote_distribution("API-C")
    except BaseException as exc:
        raise InitialManagedSecretError(
            "connected_known_committed_file_promotion"
        ) from exc
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "api_c_committed",
        "incident_class": "CONNECTED_KNOWN",
        "database_outcome": "COMMITTED",
        "database_transactions": 1,
        "role_attribute_writes": role_result["role_attribute_writes"],
        "password_writes": role_result["password_writes"],
        "membership_writes": 0,
        "acl_writes": 0,
        "schema_writes": 0,
        "business_row_writes": 0,
        "dispatcher_login_enabled": 0,
        "api_c_promoted_files": file_result["promoted_file_count"],
        "api_f_encrypted_bundle_count": 1,
        "recovery_encrypted_bundle_count": 1,
        "plaintext_task_file_count": 0,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
    }


def apply_api_f() -> dict[str, Any]:
    if os.geteuid() != 0:
        raise InitialManagedSecretError("root_required")
    _private_execution_root()
    for path in (API_F_PRIVATE_KEY, API_F_BUNDLE):
        if path.is_symlink() or not path.is_file():
            raise InitialManagedSecretError("protected_input_missing")
    try:
        payload = json.loads(
            decrypt_payload(
                API_F_BUNDLE.read_bytes(),
                API_F_PRIVATE_KEY,
            )
        )
        if not isinstance(payload, dict):
            raise InitialManagedSecretError("protected_payload_shape")
        staged = managed_files.stage_distribution("API-F", payload)
        promoted = managed_files.promote_distribution("API-F")
    except (
        json.JSONDecodeError,
        UnicodeError,
        SecretEnvelopeError,
        managed_files.ManagedSecretFileError,
    ) as exc:
        if managed_files.TASK_ROOT.exists():
            try:
                managed_files.rollback_distribution("API-F")
            except BaseException:
                pass
        raise InitialManagedSecretError("pre_connect_api_f_apply") from exc
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "api_f_promoted",
        "incident_class": "PRE_CONNECT",
        "database_connections": 0,
        "database_transactions": 0,
        "database_writes": 0,
        "staged_files": staged["staged_file_count"],
        "promoted_files": promoted["promoted_file_count"],
        "plaintext_task_file_count": 0,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--api-c", action="store_true")
    mode.add_argument("--api-f", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    if args.confirm != TASK_ID:
        print(
            "production_managed_secret_initial_apply=FAIL "
            "code=confirmation_missing",
            file=sys.stderr,
        )
        return 2
    try:
        if args.api_c:
            control_database_url = sys.stdin.read()
            if not control_database_url:
                raise InitialManagedSecretError(
                    "control_database_url_missing"
                )
            result = apply_api_c(control_database_url)
            del control_database_url
        else:
            result = apply_api_f()
    except InitialManagedSecretError as exc:
        print(
            "production_managed_secret_initial_apply=FAIL "
            f"code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_managed_secret_initial_apply=FAIL "
            "code=execution_failed",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
