#!/usr/bin/env python3
"""Decrypt one protected owner DSN and dispatch a fixed Durable AI action.

This is intentionally a thin transport adapter.  It creates no ledger,
receipt, topology record, retry loop, or task state.  The private key remains
host-local; ciphertext is accepted only on stdin; plaintext exists only in
this process and is never placed in argv, an environment variable, or a file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import production_ai_dispatcher_secret_activator as dispatcher
from tools import production_durable_ai_schema_0017 as schema_0017


TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-PROTECTED-CONTROL-001"
TASK_ACCOUNT_NAME = "noteai_schema_task_durable_ai_0017"
PRIVATE_KEY = Path("/run/noteai-durable-ai-control/control-private.pem")
API_ENV = Path("/etc/noteai/api.env")
MAX_ENVELOPE_BYTES = 131_072
MAX_PLAINTEXT_BYTES = 8_192
MUTATING_ACTIONS = frozenset(
    {
        "schema-apply",
        "dispatcher-apply",
        "dispatcher-reconcile",
    }
)
ACTIONS = (
    "schema-preflight",
    "schema-apply",
    "schema-verify",
    "dispatcher-preflight",
    "dispatcher-apply",
    "dispatcher-reconcile",
)
ALLOWED_QUERY_KEYS = dispatcher.ALLOWED_QUERY_KEYS
ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ProtectedControlError(RuntimeError):
    """A fixed, Secret-free control failure."""

    def __init__(
        self,
        code: str,
        *,
        incident_class: str = "PRE_CONNECT",
        database_outcome: str = "NOT_CONNECTED",
    ):
        super().__init__(code)
        self.code = code
        self.incident_class = incident_class
        self.database_outcome = database_outcome


def _require_private_file(
    path: Path,
    *,
    expected_uid: int,
) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProtectedControlError("private_key_missing") from exc
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise ProtectedControlError("private_key_metadata")


def _database_url_from_api_env(
    path: Path,
    *,
    expected_uid: int,
) -> str:
    _require_private_file(path, expected_uid=expected_uid)
    names: set[str] = set()
    database_url = ""
    try:
        handle = path.open("r", encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProtectedControlError("api_env_read") from exc
    try:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export ") or "=" not in stripped:
                raise ProtectedControlError("api_env_shape")
            name, value = stripped.split("=", 1)
            name = name.strip()
            if (
                not ENV_KEY.fullmatch(name)
                or name in names
                or any(marker in value for marker in ("\x00", "\r", "\n"))
            ):
                raise ProtectedControlError("api_env_shape")
            names.add(name)
            if name == "DATABASE_URL":
                database_url = value
    except UnicodeError as exc:
        raise ProtectedControlError("api_env_read") from exc
    finally:
        handle.close()
    if not database_url:
        raise ProtectedControlError("api_database_url_missing")
    return database_url


def _parsed_database_url(
    value: str,
    *,
    expected_user: str,
    code: str,
) -> Any:
    if not isinstance(value, str) or not value or len(value) > 4_096:
        raise ProtectedControlError(code)
    if any(marker in value for marker in ("\x00", "\r", "\n")):
        raise ProtectedControlError(code)
    try:
        parsed = urlsplit(value)
        pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
        port = parsed.port or 5432
        password = unquote(parsed.password or "")
    except (TypeError, ValueError) as exc:
        raise ProtectedControlError(code) from exc
    names: set[str] = set()
    for raw_name, query_value in pairs:
        name = raw_name.lower()
        if (
            name not in ALLOWED_QUERY_KEYS
            or name in names
            or any(
                marker in raw_name or marker in query_value
                for marker in ("\x00", "\r", "\n")
            )
        ):
            raise ProtectedControlError(code)
        names.add(name)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or unquote(parsed.username or "") != expected_user
        or parsed.password in (None, "")
        or any(marker in password for marker in ("\x00", "\r", "\n"))
        or not parsed.hostname
        or not 1 <= port <= 65_535
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        raise ProtectedControlError(code)
    return parsed


def _query_contract(parsed: Any) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (name.lower(), value)
            for name, value in parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
            )
        )
    )


def _protected_database_url(
    envelope_bytes: bytes,
    *,
    private_key: Path,
    api_env: Path,
    expected_uid: int,
) -> str:
    if not isinstance(envelope_bytes, bytes) or not envelope_bytes:
        raise ProtectedControlError("envelope_missing")
    if len(envelope_bytes) > MAX_ENVELOPE_BYTES:
        raise ProtectedControlError("envelope_too_large")
    try:
        from tools.production_secret_envelope import (
            SecretEnvelopeError,
            decrypt_payload,
        )
    except ModuleNotFoundError as exc:
        raise ProtectedControlError("envelope_runtime_unavailable") from exc
    try:
        plaintext = decrypt_payload(envelope_bytes, private_key)
    except SecretEnvelopeError as exc:
        raise ProtectedControlError("envelope_decrypt") from exc
    if not plaintext or len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise ProtectedControlError("payload_size")
    try:
        payload = json.loads(plaintext)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtectedControlError("payload_parse") from exc
    finally:
        del plaintext
    if not isinstance(payload, dict) or set(payload) != {"control_database_url"}:
        raise ProtectedControlError("payload_shape")
    database_url = payload["control_database_url"]
    control = _parsed_database_url(
        database_url,
        expected_user=TASK_ACCOUNT_NAME,
        code="control_database_url",
    )
    topology_url = _database_url_from_api_env(
        api_env,
        expected_uid=expected_uid,
    )
    topology = _parsed_database_url(
        topology_url,
        expected_user="noteai_app",
        code="api_database_url",
    )
    if (
        control.scheme != topology.scheme
        or str(control.hostname).lower() != str(topology.hostname).lower()
        or (control.port or 5432) != (topology.port or 5432)
        or control.path != topology.path
        or _query_contract(control) != _query_contract(topology)
    ):
        raise ProtectedControlError("database_topology_mismatch")
    return str(database_url)


def _schema_action(action: str, database_url: str) -> dict[str, Any]:
    try:
        contract = schema_0017.source_contract()
    except BaseException as exc:
        raise ProtectedControlError("schema_source") from exc
    try:
        conn = schema_0017.connect_database_url(database_url)
    except schema_0017.DurableAiSchemaError as exc:
        raise ProtectedControlError("schema_database_connect") from exc
    try:
        if action == "schema-preflight":
            result = schema_0017.preflight_schema(
                conn,
                contract,
                expected_session_role=TASK_ACCOUNT_NAME,
            )
        elif action == "schema-apply":
            result = schema_0017.apply_schema(
                conn,
                contract,
                expected_session_role=TASK_ACCOUNT_NAME,
            )
        else:
            result = schema_0017.verify_schema(
                conn,
                contract,
                expected_session_role=TASK_ACCOUNT_NAME,
            )
    except BaseException as exc:
        if action == "schema-apply":
            raise ProtectedControlError(
                "schema_apply_unknown",
                incident_class="CONNECTED_UNKNOWN",
                database_outcome="UNKNOWN",
            ) from exc
        raise ProtectedControlError(
            "schema_read_failed",
            incident_class="CONNECTED_KNOWN",
            database_outcome="READ_ONLY_FAILED",
        ) from exc
    finally:
        try:
            conn.close()
        except BaseException:
            pass
    return {
        **result,
        "task_id": schema_0017.TASK_ID,
        "protected_control_task_id": TASK_ID,
        "action": action,
        "incident_class": "CONNECTED_KNOWN",
        "database_outcome": (
            "COMMITTED" if action == "schema-apply" else "READ_ONLY_VERIFIED"
        ),
        "automatic_retry": 0,
        "secret_values_emitted": 0,
    }


def _dispatcher_error(action: str, exc: dispatcher.DispatcherSecretError) -> None:
    if exc.code in {
        "database_connect",
        "pre_connect_database",
    }:
        if action == "dispatcher-reconcile":
            raise ProtectedControlError(
                "dispatcher_reconcile_state_unknown",
                incident_class="CONNECTED_UNKNOWN",
                database_outcome="UNKNOWN",
            ) from exc
        raise ProtectedControlError("dispatcher_pre_connect") from exc
    if exc.code == "connected_known_apply_connect_failed":
        raise ProtectedControlError(
            "dispatcher_read_only_connect_failed",
            incident_class="CONNECTED_KNOWN",
            database_outcome="READ_ONLY_VERIFIED",
        ) from exc
    if exc.code in {
        "connected_unknown_role_apply",
        "connected_unknown_role_revoke",
    }:
        raise ProtectedControlError(
            "dispatcher_database_unknown",
            incident_class="CONNECTED_UNKNOWN",
            database_outcome="UNKNOWN",
        ) from exc
    if exc.code in {
        "connected_known_file_promotion",
        "connected_known_committed_login_audit",
        "connected_known_reconcile_required",
    }:
        raise ProtectedControlError(
            "dispatcher_committed_reconcile_required",
            incident_class="CONNECTED_KNOWN",
            database_outcome="COMMITTED",
        ) from exc
    if exc.code in {
        "connected_known_reconcile_rolled_back_cleanup",
    }:
        raise ProtectedControlError(
            "dispatcher_rolled_back_reconcile_required",
            incident_class="CONNECTED_KNOWN",
            database_outcome="ROLLED_BACK",
        ) from exc
    outcome = "READ_ONLY_FAILED" if action == "dispatcher-preflight" else "UNKNOWN"
    incident = "CONNECTED_KNOWN" if action == "dispatcher-preflight" else "CONNECTED_UNKNOWN"
    raise ProtectedControlError(
        "dispatcher_action_failed",
        incident_class=incident,
        database_outcome=outcome,
    ) from exc


def _dispatcher_action(action: str, database_url: str) -> dict[str, Any]:
    try:
        if action == "dispatcher-preflight":
            result = dispatcher.preflight_activation(database_url)
        elif action == "dispatcher-apply":
            result = dispatcher.apply_activation(database_url)
        elif action == "dispatcher-reconcile":
            result = dispatcher.reconcile_activation(database_url)
        else:
            raise ProtectedControlError("action")
    except dispatcher.DispatcherSecretError as exc:
        _dispatcher_error(action, exc)
        raise AssertionError("unreachable")
    except BaseException as exc:
        outcome = (
            "READ_ONLY_FAILED"
            if action == "dispatcher-preflight"
            else "UNKNOWN"
        )
        raise ProtectedControlError(
            "dispatcher_unexpected",
            incident_class="CONNECTED_UNKNOWN",
            database_outcome=outcome,
        ) from exc
    return {
        **result,
        "protected_control_task_id": TASK_ID,
        "action": action,
        "automatic_retry": 0,
        "secret_values_emitted": 0,
    }


def execute(
    action: str,
    envelope_bytes: bytes,
    *,
    private_key: Path = PRIVATE_KEY,
    api_env: Path = API_ENV,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if action not in ACTIONS:
        raise ProtectedControlError("action")
    if require_root and os.geteuid() != 0:
        raise ProtectedControlError("root_required")
    _require_private_file(private_key, expected_uid=expected_uid)
    database_url = _protected_database_url(
        envelope_bytes,
        private_key=private_key,
        api_env=api_env,
        expected_uid=expected_uid,
    )
    try:
        if action.startswith("schema-"):
            return _schema_action(action, database_url)
        return _dispatcher_action(action, database_url)
    finally:
        del database_url


def _read_envelope() -> bytes:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    try:
        payload = stream.read(MAX_ENVELOPE_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise ProtectedControlError("envelope_read") from exc
    if isinstance(payload, str):
        try:
            payload = payload.encode("ascii")
        except UnicodeError as exc:
            raise ProtectedControlError("envelope_read") from exc
    if len(payload) > MAX_ENVELOPE_BYTES:
        raise ProtectedControlError("envelope_too_large")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=ACTIONS, required=True)
    parser.add_argument("--private-key", type=Path, default=PRIVATE_KEY)
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    if args.action in MUTATING_ACTIONS and args.confirm != TASK_ID:
        print(
            "production_durable_ai_protected_control=FAIL "
            f"action={args.action} incident_class=PRE_CONNECT "
            "database_outcome=NOT_CONNECTED automatic_retry=0 "
            "secret_values_emitted=0 code=confirmation_missing",
            file=sys.stderr,
        )
        return 2
    try:
        _require_private_file(args.private_key, expected_uid=0)
        envelope_bytes = _read_envelope()
        result = execute(
            args.action,
            envelope_bytes,
            private_key=args.private_key,
        )
    except ProtectedControlError as exc:
        print(
            "production_durable_ai_protected_control=FAIL "
            f"action={args.action} incident_class={exc.incident_class} "
            f"database_outcome={exc.database_outcome} automatic_retry=0 "
            f"secret_values_emitted=0 code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_durable_ai_protected_control=FAIL "
            f"action={args.action} incident_class=UNKNOWN "
            "database_outcome=UNKNOWN automatic_retry=0 "
            "secret_values_emitted=0 code=unexpected",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
