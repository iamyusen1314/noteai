"""Shell-only, zero-Claude rehearsal client for the staging Gateway.

This module is copied into the Gateway image but is never imported by the
normal server process. Operation and rate modes drive the existing FastAPI
ASGI chain with a fixed fake provider and shared DynamoDB control plane. Load
mode performs bounded local CPU work and never enters HTTP or DynamoDB.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any

import httpx

import claude_gateway_protocol as protocol

try:
    from . import claude_gateway
except ImportError:  # pragma: no cover - container copies modules to /app
    import claude_gateway


SCHEMA = "noteai-gateway-rehearsal.v1"
STAGING_SERVICE = "noteai-staging-claude-gateway"
STAGING_HOST = "noteai-staging-claude-gateway.onrender.com"
REHEARSAL_ACK = "staging-zero-claude"
REHEARSAL_RETENTION_SECONDS = "86400"
LOAD_DUTY_CYCLE = 0.95
LOAD_PERIOD_SECONDS = 0.1
_NAMESPACE_PATTERN = re.compile(r"^rehearsal-[A-Za-z0-9_-]{8,55}$")
_SYNTHETIC_OPERATION_PATTERN = re.compile(
    r"^rehearsal[_-][A-Za-z0-9_-]{14,117}$"
)
_TABLE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")
_ROLE_PATTERN = re.compile(
    r"^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}$"
)
_PRINCIPAL_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9+=,.@_:/-]{2,127}$"
)
_INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
_SAFE_ERROR_CODES = frozenset({
    "OK",
    "INVALID_JSON",
    "RATE_LIMIT",
    "CONCURRENCY_LIMIT",
    "OPERATION_ALREADY_DISPATCHED",
    "CONTROL_PLANE_UNAVAILABLE",
    "CONTROL_PLANE_OUTCOME_UNKNOWN",
    "AUTH_REPLAY",
    "GATEWAY_NOT_CONFIGURED",
    "REHEARSAL_ARGUMENT_INVALID",
    "REHEARSAL_GUARD_REJECTED",
    "REHEARSAL_INTERNAL_ERROR",
    "REHEARSAL_RESPONSE_INVALID",
})
_UNSET = object()


class RehearsalSafetyError(RuntimeError):
    """Fixed internal failure used when a real provider path is attempted."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise RehearsalSafetyError("invalid rehearsal arguments")


class FixedFakeProvider:
    """Provider replacement with deterministic zero-token usage."""

    def __init__(self, hold_seconds: float = 0.0):
        self.hold_seconds = max(0.0, float(hold_seconds))
        self.calls = 0

    async def create(self, _payload: dict[str, Any]):
        self.calls += 1
        if self.hold_seconds:
            await asyncio.sleep(self.hold_seconds)
        return ["rehearsal-result"], {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

    async def stream(self, _payload: dict[str, Any]):
        self.calls += 1
        if self.hold_seconds:
            await asyncio.sleep(self.hold_seconds)
        yield {"type": "content", "text": "rehearsal-result"}
        yield {"type": "usage", "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }}


def guard_environment(environ: dict[str, str] | None = None) -> bool:
    """Allow only the exact Render staging Gateway and fixed safety contract."""
    env = os.environ if environ is None else environ
    exact = {
        "RENDER": "true",
        "RENDER_SERVICE_NAME": STAGING_SERVICE,
        "RENDER_EXTERNAL_HOSTNAME": STAGING_HOST,
        "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": STAGING_HOST,
        "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "dynamodb",
        "NOTEAI_GATEWAY_REHEARSAL_ACK": REHEARSAL_ACK,
        "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "2",
        "NOTEAI_CLAUDE_GATEWAY_CONCURRENCY": "2",
        "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "30",
        "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "ap-southeast-1",
        "WEB_CONCURRENCY": "1",
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    if any(str(env.get(key, "")) != value for key, value in exact.items()):
        return False
    required = (
        "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET",
        "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE",
        "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID",
    )
    if not all(str(env.get(key, "")).strip() for key in required):
        return False
    if not _identity_environment_valid(env):
        return False
    return bool(
        _TABLE_PATTERN.fullmatch(
            str(env.get("NOTEAI_CLAUDE_GATEWAY_DDB_TABLE", ""))
        )
        and _PRINCIPAL_PATTERN.fullmatch(
            str(env.get("NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID", ""))
        )
        and _INSTANCE_PATTERN.fullmatch(str(env.get("RENDER_INSTANCE_ID", "")))
        and _COMMIT_PATTERN.fullmatch(str(env.get("RENDER_GIT_COMMIT", "")))
    )


def _identity_environment_valid(env: Mapping[str, str]) -> bool:
    """Mirror the Gateway's OIDC-only identity gate without opening AWS."""
    static_names = (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    )
    role = str(env.get("AWS_ROLE_ARN", "")).strip()
    token_file = str(env.get("AWS_WEB_IDENTITY_TOKEN_FILE", "")).strip()
    return bool(
        not any(str(env.get(name, "")).strip() for name in static_names)
        and _ROLE_PATTERN.fullmatch(role)
        and token_file.startswith("/")
        and str(env.get("AWS_EC2_METADATA_DISABLED", "")).strip().lower() == "true"
    )


def _valid_namespace(value: str) -> bool:
    return bool(_NAMESPACE_PATTERN.fullmatch(value or ""))


def _valid_operation_id(value: str) -> bool:
    return bool(
        _SYNTHETIC_OPERATION_PATTERN.fullmatch(value or "")
        and protocol.valid_operation_id(value)
    )


def _principal_for_namespace(namespace: str) -> str:
    digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:32]
    return f"staging-rehearsal-{digest}"


def _instance_marker(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = str(env.get("RENDER_INSTANCE_ID") or "")
    if not _INSTANCE_PATTERN.fullmatch(raw):
        return "unknown"
    return hashlib.sha256(f"rehearsal:{raw}".encode("utf-8")).hexdigest()[:12]


def _commit_prefix(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = str(env.get("RENDER_GIT_COMMIT") or "")
    return raw.lower()[:12] if _COMMIT_PATTERN.fullmatch(raw) else "unknown"


def _control_config_marker(environ: dict[str, str] | None = None) -> str:
    """One-way consistency marker; never emit raw control-plane identifiers."""
    env = os.environ if environ is None else environ
    names = (
        "NOTEAI_CLAUDE_GATEWAY_AUTHORITY",
        "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE",
        "NOTEAI_CLAUDE_GATEWAY_DDB_REGION",
        "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID",
        "AWS_ROLE_ARN",
    )
    values = [str(env.get(name, "")).strip() for name in names]
    if not all(values):
        return "unknown"
    material = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _fixed_output(
    mode: str,
    status_codes: list[int],
    error_codes: list[str],
    fake_provider_calls: int,
) -> dict[str, Any]:
    safe_mode = mode if mode in {"operation", "rate", "load"} else "guard"
    safe_errors = [
        code if code in _SAFE_ERROR_CODES else "REHEARSAL_RESPONSE_INVALID"
        for code in error_codes
    ]
    return {
        "schema": SCHEMA,
        "mode": safe_mode,
        "status_codes": [int(code) for code in status_codes],
        "error_codes": safe_errors,
        "fake_provider_calls": max(0, int(fake_provider_calls)),
        "instance_marker": _instance_marker(),
        "commit_prefix": _commit_prefix(),
        "control_config_marker": _control_config_marker(),
    }


def _response_code(response: httpx.Response) -> str:
    if response.status_code == 200:
        return "OK"
    try:
        payload = response.json()
        code = payload.get("error", {}).get("code")
    except Exception:
        code = None
    return code if code in _SAFE_ERROR_CODES else "REHEARSAL_RESPONSE_INVALID"


def _blocked_anthropic_client(_self):
    raise RehearsalSafetyError("real provider disabled")


def _blocked_anthropic_constructor(*_args, **_kwargs):
    raise RehearsalSafetyError("real provider disabled")


@contextmanager
def _fake_provider_runtime(fake_provider: FixedFakeProvider):
    original_provider = claude_gateway._PROVIDER
    original_get_client = claude_gateway.AnthropicProvider._get_client
    original_constructor = claude_gateway.anthropic.AsyncAnthropic
    claude_gateway._PROVIDER = fake_provider
    claude_gateway.AnthropicProvider._get_client = _blocked_anthropic_client
    claude_gateway.anthropic.AsyncAnthropic = _blocked_anthropic_constructor
    try:
        yield
    finally:
        claude_gateway._PROVIDER = original_provider
        claude_gateway.AnthropicProvider._get_client = original_get_client
        claude_gateway.anthropic.AsyncAnthropic = original_constructor


@contextmanager
def _rehearsal_control_environment(
    namespace: str,
    *,
    control_store: Any = _UNSET,
):
    original_principal = os.environ.get("NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID")
    original_retention = os.environ.get(
        "NOTEAI_CLAUDE_GATEWAY_TERMINAL_RETENTION_SECONDS"
    )
    original_store = claude_gateway._CONTROL_STORE
    os.environ["NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID"] = _principal_for_namespace(namespace)
    os.environ[
        "NOTEAI_CLAUDE_GATEWAY_TERMINAL_RETENTION_SECONDS"
    ] = REHEARSAL_RETENTION_SECONDS
    claude_gateway._CONTROL_STORE = None if control_store is _UNSET else control_store
    try:
        yield
    finally:
        claude_gateway._CONTROL_STORE = original_store
        if original_principal is None:
            os.environ.pop("NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID", None)
        else:
            os.environ["NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID"] = original_principal
        if original_retention is None:
            os.environ.pop("NOTEAI_CLAUDE_GATEWAY_TERMINAL_RETENTION_SECONDS", None)
        else:
            os.environ[
                "NOTEAI_CLAUDE_GATEWAY_TERMINAL_RETENTION_SECONDS"
            ] = original_retention


async def _signed_asgi_post(body: bytes) -> httpx.Response:
    authority = claude_gateway._gateway_authority()
    headers = protocol.auth_headers(
        key_id=os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID", ""),
        secret=os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET", ""),
        method="POST",
        path=protocol.MESSAGES_PATH,
        authority=authority,
        config_epoch=os.environ.get("NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH", ""),
        key_epoch=os.environ.get("NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", ""),
        body=body,
    )
    transport = httpx.ASGITransport(
        app=claude_gateway.app,
        raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=f"https://{authority}",
        trust_env=False,
        follow_redirects=False,
    ) as client:
        return await client.post(protocol.MESSAGES_PATH, content=body, headers=headers)


def _operation_body(operation_id: str) -> bytes:
    return json.dumps({
        "operation_id": operation_id,
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1,
        "system": "staging zero-provider rehearsal",
        "messages": [{"role": "user", "content": "synthetic rehearsal"}],
        "temperature": 0.0,
        "thinking_budget": None,
    }, separators=(",", ":")).encode("utf-8")


async def execute_operation(
    operation_id: str,
    namespace: str,
    hold_seconds: float,
    *,
    request_count: int = 1,
    control_store: Any = _UNSET,
) -> dict[str, Any]:
    fake = FixedFakeProvider(hold_seconds)
    body = _operation_body(operation_id)
    with _rehearsal_control_environment(namespace, control_store=control_store), \
         _fake_provider_runtime(fake):
        responses = await asyncio.gather(*(
            _signed_asgi_post(body) for _ in range(request_count)
        ))
    return _fixed_output(
        "operation",
        [response.status_code for response in responses],
        [_response_code(response) for response in responses],
        fake.calls,
    )


async def execute_rate(
    namespace: str,
    request_count: int,
    *,
    control_store: Any = _UNSET,
) -> dict[str, Any]:
    fake = FixedFakeProvider()
    invalid_json = b"{"
    responses: list[httpx.Response] = []
    with _rehearsal_control_environment(namespace, control_store=control_store), \
         _fake_provider_runtime(fake):
        for _ in range(request_count):
            responses.append(await _signed_asgi_post(invalid_json))
    return _fixed_output(
        "rate",
        [response.status_code for response in responses],
        [_response_code(response) for response in responses],
        fake.calls,
    )


async def execute_load(
    duration_seconds: int,
    *,
    clock=None,
    sleeper=None,
) -> dict[str, Any]:
    """Run bounded local CPU work without HTTP, control-store, or provider I/O."""
    duration = _bounded_int(str(duration_seconds), 60, 600)
    monotonic = time.perf_counter if clock is None else clock
    async_sleep = asyncio.sleep if sleeper is None else sleeper
    deadline = monotonic() + duration
    busy_seconds = LOAD_PERIOD_SECONDS * LOAD_DUTY_CYCLE
    while True:
        cycle_started = monotonic()
        busy_until = min(deadline, cycle_started + busy_seconds)
        while monotonic() < busy_until:
            pass
        now = monotonic()
        if now >= deadline:
            break
        sleep_until = min(deadline, cycle_started + LOAD_PERIOD_SECONDS)
        # Always yield once per cycle, even if scheduler delay consumed the
        # nominal 5% idle slice.
        await async_sleep(max(0.0, sleep_until - now))
    return _fixed_output("load", [200], ["OK"], 0)


def _bounded_float(value: str | None, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value or "0")
    except (TypeError, ValueError) as exc:
        raise RehearsalSafetyError("invalid rehearsal arguments") from exc
    if not minimum <= parsed <= maximum:
        raise RehearsalSafetyError("invalid rehearsal arguments")
    return parsed


def _bounded_int(value: str | None, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or "0")
    except (TypeError, ValueError) as exc:
        raise RehearsalSafetyError("invalid rehearsal arguments") from exc
    if not minimum <= parsed <= maximum:
        raise RehearsalSafetyError("invalid rehearsal arguments")
    return parsed


async def _wait_for_start(value: str | None) -> None:
    if value is None:
        return
    start_at = _bounded_float(value, 1.0, 4_102_444_800.0)
    now = time.time()
    if start_at < now - 5.0 or start_at > now + 600.0:
        raise RehearsalSafetyError("invalid rehearsal arguments")
    delay = max(0.0, start_at - now)
    if delay:
        await asyncio.sleep(delay)


def _parser() -> argparse.ArgumentParser:
    # Keep every invocation on the fixed JSON output contract, including
    # malformed arguments such as --help.
    parser = _ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    operation = subparsers.add_parser("operation", add_help=False)
    operation.add_argument("--operation-id", required=True)
    operation.add_argument("--namespace", required=True)
    operation.add_argument("--start-at")
    operation.add_argument("--hold-seconds", default="0")

    rate = subparsers.add_parser("rate", add_help=False)
    rate.add_argument("--namespace", required=True)
    rate.add_argument("--start-at")
    rate.add_argument("--request-count", required=True)

    load = subparsers.add_parser("load", add_help=False)
    load.add_argument("--start-at", required=True)
    load.add_argument("--duration-seconds", required=True)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if not guard_environment():
        return _fixed_output(
            "guard", [403], ["REHEARSAL_GUARD_REJECTED"], 0,
        )
    if args.mode == "load":
        duration_seconds = _bounded_int(args.duration_seconds, 60, 600)
        await _wait_for_start(args.start_at)
        return await execute_load(duration_seconds)
    namespace = str(args.namespace or "")
    if not _valid_namespace(namespace):
        raise RehearsalSafetyError("invalid rehearsal arguments")
    await _wait_for_start(args.start_at)
    if args.mode == "operation":
        operation_id = str(args.operation_id or "")
        if not _valid_operation_id(operation_id):
            raise RehearsalSafetyError("invalid rehearsal arguments")
        hold_seconds = _bounded_float(args.hold_seconds, 0.0, 170.0)
        return await execute_operation(operation_id, namespace, hold_seconds)
    request_count = _bounded_int(args.request_count, 1, 100)
    return await execute_rate(namespace, request_count)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    mode = (
        raw_args[0]
        if raw_args and raw_args[0] in {"operation", "rate", "load"}
        else "guard"
    )
    try:
        args = _parser().parse_args(raw_args)
        output = asyncio.run(_run(args))
        exit_code = 0 if all(code in {200, 400, 409, 429} for code in output["status_codes"]) else 2
    except RehearsalSafetyError:
        output = _fixed_output(
            mode, [400], ["REHEARSAL_ARGUMENT_INVALID"], 0,
        )
        exit_code = 2
    except BaseException:
        output = _fixed_output(
            mode, [500], ["REHEARSAL_INTERNAL_ERROR"], 0,
        )
        exit_code = 3
    print(json.dumps(output, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
