#!/usr/bin/env python3
"""Run the bounded Item 30 production-provider probe inside an isolated container.

The caller must project only the provider credentials needed by this probe.  The
script refuses a production database connection, records model usage in tmpfs
SQLite, never persists response content, and never retries or falls back.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any


TASK_ID = "PROD-FIRST-LAUNCH-PROVIDER-CHAIN-001"
RESULT_SCHEMA = "noteai.item30.real-ai-provider-chain-result.v1"
ACCOUNT_GATE_SCHEMA = "noteai.item30.account-gates.v1"
JOURNAL_SCHEMA = "noteai.item30.execution-journal.v1"
PROVIDER_ORDER = ("claude", "kimi", "amap", "meituan")
DISPATCH_ORDER = ("meituan", "claude", "kimi", "amap")
PROVIDER_CAPS = {
    "claude": Decimal("0.100000"),
    "kimi": Decimal("0.100000"),
    "amap": Decimal("0.100000"),
}
PROVIDER_COUNTER_SEMANTICS = {
    "claude": {
        ("request_count", "requests", "increasing"),
        ("total_tokens", "tokens", "increasing"),
        ("billed_cost_rmb", "rmb", "increasing"),
        ("remaining_balance_rmb", "rmb", "decreasing"),
    },
    "kimi": {
        ("request_count", "requests", "increasing"),
        ("total_tokens", "tokens", "increasing"),
        ("billed_cost_rmb", "rmb", "increasing"),
        ("remaining_balance_rmb", "rmb", "decreasing"),
    },
    "amap": {("request_count", "requests", "increasing")},
}
KNOWN_PRICED_PROVIDER_COST_CAP = Decimal("0.300000")
NOT_EXPOSED_BY_PROVIDER = "NOT_EXPOSED_BY_PROVIDER"
NOT_DETERMINABLE = "NOT_DETERMINABLE"
MEITUAN_COST_OVERRIDE = "OWNER_AUTHORIZED_UNPRICED_SINGLE_CALL"
SYNTHETIC_SYSTEM = "Return only NOTEAI_OK."
SYNTHETIC_USER = "Bounded production transport check."
PUBLIC_FACT_QUERY = "深圳四季酒店 地址 营业时间 预订"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
KIMI_MODEL = "kimi-k2.6"
MAX_OUTPUT_TOKENS = 64
MAX_PROMPT_BYTES = 128
MAX_ACCOUNT_GATE_AGE = timedelta(minutes=30)
MIN_GATE_REMAINING = timedelta(minutes=7)
STATE_DIR = Path("/result")
ACCOUNT_GATES_PATH = STATE_DIR / "account-gates.json"
RESULT_PATH = STATE_DIR / "executor-result.json"
SQLITE_PATH = Path("/dev/shm/noteai-item30-usage.db")
HEX64 = set("0123456789abcdef")
HEX40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SAFE_COUNTER_NAME = re.compile(r"^[a-z0-9_.-]{1,64}$")
SAFE_PROVIDER_RESULT_KEYS = {
    "claude": {
        "output_bytes", "output_sha256", "input_tokens", "output_tokens",
        "model_calls", "provider", "model", "pricing_status", "usage_status",
        "cost_mode", "actual_cost_rmb", "transport",
    },
    "kimi": {
        "output_bytes", "output_sha256", "input_tokens", "output_tokens",
        "model_calls", "provider", "model", "pricing_status", "usage_status",
        "cost_mode", "actual_cost_rmb", "transport",
    },
    "amap": {
        "output_bytes", "output_sha256", "structured_fact_count",
        "source_count", "confidence_milli", "target_entity_matched",
        "target_region_matched", "http_request_count",
        "detail_request_count", "transport",
    },
    "meituan": {
        "output_bytes", "output_sha256", "structured_fact_count",
        "source_count", "confidence_milli", "target_entity_matched",
        "target_region_matched", "cli_invocation_count", "transport",
    },
}


class ProbeError(RuntimeError):
    """A fixed-code probe error that never includes provider response text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


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


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _terminal_summary(result: dict[str, Any]) -> bytes:
    return _canonical(
        {
            "executor_result_sha256": _sha256(_canonical(result)),
            "status": result.get("status"),
        }
    )


def _decimal_text(value: Decimal | str | float | int) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProbeError("COST_SHAPE_INVALID") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ProbeError("COST_SHAPE_INVALID")
    return f"{parsed.quantize(Decimal('0.000001')):.6f}"


def _valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and not (set(value) - HEX64)
    )


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProbeError("ACCOUNT_GATE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProbeError("ACCOUNT_GATE_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise ProbeError("ACCOUNT_GATE_TIME_INVALID")
    return parsed.astimezone(timezone.utc)


def _normalize_account_gates(
    value: Any,
    *,
    now_text: str,
) -> dict[str, Any]:
    expected_top = {
        "schema",
        "generated_at_utc",
        "expires_at_utc",
        "execution_nonce",
        "execution_source_revision",
        "executor_sha256",
        "fact_enrichment_sha256",
        "providers",
    }
    if not isinstance(value, dict) or set(value) != expected_top:
        raise ProbeError("ACCOUNT_GATES_SHAPE")
    if value.get("schema") != ACCOUNT_GATE_SCHEMA:
        raise ProbeError("ACCOUNT_GATES_SCHEMA")
    for name in ("execution_nonce", "executor_sha256", "fact_enrichment_sha256"):
        if not _valid_digest(value.get(name)) or value[name] == "0" * 64:
            raise ProbeError("ACCOUNT_GATES_SOURCE_BINDING")
    if HEX40_PATTERN.fullmatch(str(value.get("execution_source_revision") or "")) is None:
        raise ProbeError("ACCOUNT_GATES_SOURCE_BINDING")

    generated = _parse_utc(value.get("generated_at_utc"))
    expires = _parse_utc(value.get("expires_at_utc"))
    now = _parse_utc(now_text)
    if not (
        generated <= now <= expires
        and timedelta(0) < expires - generated <= MAX_ACCOUNT_GATE_AGE
        and expires - now >= MIN_GATE_REMAINING
    ):
        raise ProbeError("ACCOUNT_GATES_EXPIRED")

    providers = value.get("providers")
    if not isinstance(providers, dict) or tuple(providers) != PROVIDER_ORDER:
        raise ProbeError("ACCOUNT_GATES_PROVIDER_ORDER")

    normalized_providers: dict[str, dict[str, Any]] = {}
    expected_keys = {
        "account_identity_sha256",
        "credential_name_present",
        "balance_or_quota_confirmed",
        "current_price_confirmed",
        "pre_call_counter_readable",
        "pre_call_counter",
        "price_snapshot_sha256",
        "unit_cost_upper_bound_rmb",
    }
    counter_keys = {
        "observed_at_utc",
        "counter_kind",
        "counter_unit",
        "direction",
        "counter_value",
        "snapshot_sha256",
        "source",
    }
    total = Decimal("0")
    for provider in PROVIDER_ORDER:
        gate = providers.get(provider)
        if not isinstance(gate, dict) or set(gate) != expected_keys:
            raise ProbeError("ACCOUNT_GATE_SHAPE")
        if (
            not _valid_digest(gate.get("account_identity_sha256"))
            or gate["account_identity_sha256"] == "0" * 64
        ):
            raise ProbeError("ACCOUNT_GATE_ACCOUNT_BINDING")
        if (
            not _valid_digest(gate.get("price_snapshot_sha256"))
            or gate["price_snapshot_sha256"] == "0" * 64
        ):
            raise ProbeError("ACCOUNT_GATE_PRICE_BINDING")
        counter = gate.get("pre_call_counter")
        if not isinstance(counter, dict) or set(counter) != counter_keys:
            raise ProbeError("ACCOUNT_GATE_COUNTER_SHAPE")
        observed = _parse_utc(counter.get("observed_at_utc"))
        if not now - MAX_ACCOUNT_GATE_AGE <= observed <= generated:
            raise ProbeError("ACCOUNT_GATE_COUNTER_STALE")
        if provider == "meituan":
            if not (
                gate.get("credential_name_present") is True
                and gate.get("balance_or_quota_confirmed") is False
                and gate.get("current_price_confirmed") is False
                and gate.get("pre_call_counter_readable") is False
                and counter.get("counter_kind") == NOT_EXPOSED_BY_PROVIDER
                and counter.get("counter_unit") == NOT_EXPOSED_BY_PROVIDER
                and counter.get("direction") == NOT_EXPOSED_BY_PROVIDER
                and counter.get("counter_value") == NOT_EXPOSED_BY_PROVIDER
                and counter.get("source") == "provider_account_console"
                and _valid_digest(counter.get("snapshot_sha256"))
                and counter["snapshot_sha256"] != "0" * 64
                and counter["snapshot_sha256"]
                == gate["price_snapshot_sha256"]
                and gate.get("unit_cost_upper_bound_rmb")
                == NOT_EXPOSED_BY_PROVIDER
            ):
                raise ProbeError("MEITUAN_DISCLOSURE_GATE_INVALID")
            normalized_providers[provider] = gate
            continue
        for name in (
            "credential_name_present",
            "balance_or_quota_confirmed",
            "current_price_confirmed",
            "pre_call_counter_readable",
        ):
            if gate.get(name) is not True:
                raise ProbeError("ACCOUNT_GATE_NOT_CONFIRMED")
        if (
            SAFE_COUNTER_NAME.fullmatch(str(counter.get("counter_kind") or "")) is None
            or SAFE_COUNTER_NAME.fullmatch(str(counter.get("counter_unit") or "")) is None
            or counter.get("direction") not in {"increasing", "decreasing"}
            or counter.get("source") != "provider_account_console"
            or not _valid_digest(counter.get("snapshot_sha256"))
            or counter.get("snapshot_sha256") == "0" * 64
        ):
            raise ProbeError("ACCOUNT_GATE_COUNTER_SHAPE")
        counter_semantics = (
            counter["counter_kind"],
            counter["counter_unit"],
            counter["direction"],
        )
        if counter_semantics not in PROVIDER_COUNTER_SEMANTICS[provider]:
            raise ProbeError("ACCOUNT_GATE_COUNTER_SEMANTICS")
        normalized_counter = {
            **counter,
            "counter_value": _decimal_text(counter.get("counter_value")),
        }
        amount = _decimal_text(gate.get("unit_cost_upper_bound_rmb"))
        parsed = Decimal(amount)
        if parsed > PROVIDER_CAPS[provider]:
            raise ProbeError("PROVIDER_COST_CAP_EXCEEDED")
        total += parsed
        normalized_providers[provider] = {
            **gate,
            "pre_call_counter": normalized_counter,
            "unit_cost_upper_bound_rmb": amount,
        }
    if total > KNOWN_PRICED_PROVIDER_COST_CAP:
        raise ProbeError("TOTAL_COST_CAP_EXCEEDED")
    return {**value, "providers": normalized_providers}


def load_account_gates(path: Path, *, now_text: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeError("ACCOUNT_GATES_UNREADABLE") from exc
    return _normalize_account_gates(value, now_text=now_text or _utc_now())


def _runtime_source_binding(account_gates: dict[str, Any]) -> None:
    executor_sha = _sha256(Path(__file__).read_bytes())
    fact_sha = _sha256((_model_path() / "fact_enrichment.py").read_bytes())
    if (
        account_gates["executor_sha256"] != executor_sha
        or account_gates["fact_enrichment_sha256"] != fact_sha
    ):
        raise ProbeError("RUNTIME_SOURCE_BINDING_MISMATCH")


def _mount_filesystem(path: Path) -> str:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProbeError("TMPFS_UNVERIFIED") from exc
    resolved = str(path.resolve())
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        after = right.split()
        if len(fields) > 4 and len(after) > 0 and fields[4] == resolved:
            return after[0]
    raise ProbeError("TMPFS_UNVERIFIED")


def _validate_sqlite_path(path: Path) -> tuple[Path, ...]:
    if path != SQLITE_PATH:
        raise ProbeError("SQLITE_PATH_FORBIDDEN")
    parent = path.parent
    try:
        mode = parent.lstat().st_mode
    except OSError as exc:
        raise ProbeError("TMPFS_UNVERIFIED") from exc
    if not stat.S_ISDIR(mode) or parent.is_symlink() or _mount_filesystem(parent) != "tmpfs":
        raise ProbeError("TMPFS_UNVERIFIED")
    artifacts = tuple(Path(str(path) + suffix) for suffix in ("", "-wal", "-shm"))
    if any(item.exists() or item.is_symlink() for item in artifacts):
        raise ProbeError("SQLITE_PATH_COLLISION")
    return artifacts


class AttemptJournal:
    """Host-persistent, fail-closed dispatch journal for a single nonce."""

    def __init__(self, path: Path, value: dict[str, Any]):
        self.path = path
        self.value = value

    @classmethod
    def create(cls, path: Path, account_gates: dict[str, Any]) -> "AttemptJournal":
        value = {
            "schema": JOURNAL_SCHEMA,
            "execution_nonce": account_gates["execution_nonce"],
            "execution_source_revision": account_gates["execution_source_revision"],
            "account_gate_sha256": _sha256(_canonical(account_gates)),
            "executor_sha256": account_gates["executor_sha256"],
            "fact_enrichment_sha256": account_gates["fact_enrichment_sha256"],
            "status": "ARMED",
            "providers": {},
        }
        raw = _canonical(value)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ProbeError("EXECUTION_ALREADY_ATTEMPTED") from exc
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return cls(path, value)

    def transition(self, status: str, provider: str | None = None) -> None:
        if provider is None:
            self.value["status"] = status
        else:
            self.value["providers"][provider] = status
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_canonical(self.value))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def finalize(self, result: dict[str, Any]) -> None:
        if (
            self.value.get("execution_nonce")
            != (result.get("account_gate") or {}).get("execution_nonce")
        ):
            raise ProbeError("EXECUTION_NONCE_MISMATCH")
        temporary = self.path.with_name(f".{self.path.name}.final")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_canonical(result))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


def _model_path() -> Path:
    image_path = Path("/app/model")
    if image_path.is_dir():
        return image_path
    return Path(__file__).resolve().parents[2] / "model"


def _validate_environment_boundary() -> None:
    allowed_application_names = {
        "NOTEAI_CLAUDE_GATEWAY_URL",
        "NOTEAI_CLAUDE_GATEWAY_AUTHORITY",
        "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET",
        "NOTEAI_CLAUDE_TRANSPORT",
        "NOTEAI_FACT_SEARCH",
        "NOTEAI_MEITUAN_TRAVEL_ENABLED",
        "NOTEAI_MEITUAN_TRAVEL_TIMEOUT",
        "NOTEAI_CLOUD_RUNTIME",
        "NOTEAI_RUNTIME_ROLE",
        "MOONSHOT_API_KEY",
        "AMAP_WEB_KEY",
        "MEITUAN_AI_HUB_TOKEN",
        "MEITUAN_OPEN_TOKEN",
        "MEITUAN_TRAVEL_CLI",
    }
    known_secret_names = {
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",
        "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET",
        "BAIDU_MAP_AK",
        "TENCENT_MAP_KEY",
        "SERPAPI_API_KEY",
        "BING_SEARCH_API_KEY",
        "GOOGLE_API_KEY",
        "MEITUAN_SIGN_KEY",
        "MEITUAN_APP_AUTH_TOKEN",
        "MEITUAN_OPEN_APP_KEY",
        "MEITUAN_OPEN_APP_SECRET",
        "MEITUAN_OPEN_SIGN",
        "MEITUAN_OPEN_AES_KEY",
        "NOTEAI_MARKET_TIMING_REFRESH_TOKEN",
        "NOTEAI_AUTHORIZED_TREND_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "NOTEAI_AI_API_STORE_ACCESS_KEY_ID",
        "NOTEAI_AI_API_STORE_SECRET_ACCESS_KEY",
        "NOTEAI_AI_API_STORE_SESSION_TOKEN",
        "NOTEAI_AI_WORKER_STORE_ACCESS_KEY_ID",
        "NOTEAI_AI_WORKER_STORE_SECRET_ACCESS_KEY",
        "NOTEAI_AI_WORKER_STORE_SESSION_TOKEN",
        "NOTEAI_ADAPAY_API_KEY",
        "NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY",
        "NOTEAI_ADAPAY_PUBLIC_KEY",
        "ADMIN_PASSWORD",
        "SECRET_KEY",
    }
    application_prefixes = (
        "NOTEAI_", "MEITUAN_", "MOONSHOT_", "AMAP_", "ANTHROPIC_",
        "BAIDU_", "TENCENT_", "SERPAPI_", "BING_", "GOOGLE_",
        "AWS_", "ALIYUN_", "OSS_", "S3_", "XHS_", "ADMIN_",
    )
    proxy_names = {
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    }
    populated = {name for name, value in os.environ.items() if str(value)}
    forbidden_known = known_secret_names - allowed_application_names
    unexpected_application = {
        name
        for name in populated
        if name.startswith(application_prefixes)
        and name not in allowed_application_names
    }
    if populated & (forbidden_known | proxy_names) or unexpected_application:
        raise ProbeError("ENVIRONMENT_SCOPE_FORBIDDEN")
    required = {
        "NOTEAI_CLAUDE_GATEWAY_URL",
        "NOTEAI_CLAUDE_GATEWAY_AUTHORITY",
        "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET",
        "MOONSHOT_API_KEY",
        "AMAP_WEB_KEY",
    }
    if not required <= populated:
        raise ProbeError("ENVIRONMENT_SCOPE_INCOMPLETE")
    meituan_names = {
        name
        for name in ("MEITUAN_AI_HUB_TOKEN", "MEITUAN_OPEN_TOKEN")
        if name in populated
    }
    if len(meituan_names) != 1:
        raise ProbeError("MEITUAN_CREDENTIAL_SCOPE_INVALID")
    if not (
        os.environ.get("NOTEAI_CLAUDE_TRANSPORT") == "gateway"
        and os.environ.get("NOTEAI_FACT_SEARCH") == "1"
        and os.environ.get("NOTEAI_MEITUAN_TRAVEL_ENABLED") == "1"
        and os.environ.get("NOTEAI_CLOUD_RUNTIME") == "1"
        and os.environ.get("NOTEAI_RUNTIME_ROLE") == "api"
        and os.environ.get("TMPDIR") == "/dev/shm"
        and os.environ.get("MEITUAN_TRAVEL_CLI") == "/usr/local/bin/mttravel"
        and os.environ.get("NOTEAI_MEITUAN_TRAVEL_TIMEOUT", "45") == "45"
    ):
        raise ProbeError("FACT_RUNTIME_SCOPE_INVALID")


def _result_summary(value: Any) -> dict[str, Any]:
    raw = value.encode("utf-8") if isinstance(value, str) else _canonical(value)
    return {
        "output_bytes": len(raw),
        "output_sha256": _sha256(raw),
    }


class ProductionProbeBackend:
    """Call the current application transports with an ephemeral usage ledger."""

    def __init__(self, sqlite_path: Path):
        if os.environ.get("DATABASE_URL"):
            raise ProbeError("PRODUCTION_DATABASE_FORBIDDEN")
        os.environ["NOTEAI_SQLITE_PATH"] = str(sqlite_path)
        os.environ["NOTEAI_MODEL_RETRY_ATTEMPTS"] = "1"
        os.environ["NOTEAI_MODEL_RETRY_BASE_DELAY"] = "0"
        model_path = _model_path()
        if str(model_path) not in sys.path:
            sys.path.insert(0, str(model_path))
        self.db = importlib.import_module("db")
        self.billing = importlib.import_module("billing")
        self.model_router = importlib.import_module("model_router")
        self.fact_enrichment = importlib.import_module("fact_enrichment")
        self.model_router.MODEL_RETRY_ATTEMPTS = 1
        self.model_router.MODEL_RETRY_BASE_DELAY = 0
        self.db.init_db()

    def preflight(self) -> dict[str, Any]:
        readiness = self.model_router.claude_transport_readiness(
            require_remote=True
        )
        if not (
            readiness.get("mode") == "gateway"
            and readiness.get("configured") is True
            and readiness.get("remote_checked") is True
            and readiness.get("remote_ready") is True
        ):
            raise ProbeError("CLAUDE_GATEWAY_NOT_READY")
        if not os.environ.get("MOONSHOT_API_KEY"):
            raise ProbeError("KIMI_CREDENTIAL_MISSING")
        if not os.environ.get("AMAP_WEB_KEY"):
            raise ProbeError("AMAP_CREDENTIAL_MISSING")
        meituan = self.fact_enrichment.meituan_travel_runtime_status()
        if not (
            meituan.get("ok") is True
            and meituan.get("required") is True
            and meituan.get("status_code") == "MEITUAN_TRAVEL_READY"
        ):
            raise ProbeError("MEITUAN_RUNTIME_NOT_READY")
        return {
            "claude_transport": "gateway",
            "claude_remote_ready": True,
            "kimi_credential_present": True,
            "amap_credential_present": True,
            "meituan_runtime_status": "MEITUAN_TRAVEL_READY",
        }

    def _create_usage(self, provider: str) -> str:
        user_id = f"item30-{provider}"
        now = "2026-08-24T00:00:00+00:00"
        self.db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                user_id,
                user_id,
                f"{user_id}@example.invalid",
                "synthetic",
                "synthetic",
                now,
            ),
        )
        self.billing.record_free_usage(user_id, f"item30_{provider}")
        return user_id

    def _model_usage(self, user_id: str, provider: str) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT u.tokens_in,u.tokens_out,u.actual_model_cost_rmb,u.model_calls,"
            "u.cost_mode,m.provider,m.model,m.pricing_status,m.usage_status,"
            "m.known_cost_rmb FROM usage_records u "
            "JOIN model_usage_records m ON m.usage_record_id=u.id "
            "WHERE u.user_id=? ORDER BY m.recorded_at DESC LIMIT 1",
            (user_id,),
        )
        if not row or row["provider"] != provider:
            raise ProbeError("MODEL_USAGE_MISSING")
        result = {
            "input_tokens": int(row["tokens_in"] or 0),
            "output_tokens": int(row["tokens_out"] or 0),
            "model_calls": int(row["model_calls"] or 0),
            "provider": str(row["provider"]),
            "model": str(row["model"]),
            "pricing_status": str(row["pricing_status"]),
            "usage_status": str(row["usage_status"]),
            "cost_mode": str(row["cost_mode"]),
            "actual_cost_rmb": _decimal_text(
                row["actual_model_cost_rmb"] or row["known_cost_rmb"] or 0
            ),
        }
        if not (
            result["input_tokens"] > 0
            and result["output_tokens"] > 0
            and result["model_calls"] == 1
            and result["pricing_status"] == "exact"
            and result["usage_status"] == "complete"
            and result["cost_mode"] == "actual"
        ):
            raise ProbeError("MODEL_USAGE_NOT_ACTUAL")
        return result

    def claude(self) -> dict[str, Any]:
        user_id = self._create_usage("claude")
        output = self.model_router.call_claude_sync(
            model=CLAUDE_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYNTHETIC_SYSTEM,
            messages=[{"role": "user", "content": SYNTHETIC_USER}],
            temperature=0,
        )
        if not isinstance(output, str) or output.strip() != "NOTEAI_OK":
            raise ProbeError("CLAUDE_OUTPUT_INVALID")
        result = {
            **_result_summary("NOTEAI_OK"),
            **self._model_usage(user_id, "claude"),
        }
        result["transport"] = "production_gateway"
        return result

    def kimi(self) -> dict[str, Any]:
        user_id = self._create_usage("kimi")
        output = asyncio.run(
            self.model_router._call_kimi(
                KIMI_MODEL,
                SYNTHETIC_SYSTEM,
                SYNTHETIC_USER,
                False,
                MAX_OUTPUT_TOKENS,
            )
        )
        if not isinstance(output, str) or output.strip() != "NOTEAI_OK":
            raise ProbeError("KIMI_OUTPUT_INVALID")
        result = {
            **_result_summary("NOTEAI_OK"),
            **self._model_usage(user_id, "kimi"),
        }
        result["transport"] = "model_router_kimi"
        return result

    @staticmethod
    def _fact_result(items: Any, transport: str) -> dict[str, Any]:
        if not isinstance(items, list) or not items:
            raise ProbeError("FACT_OUTPUT_EMPTY")
        fact_count = sum(
            len(item.get("facts") or {})
            for item in items
            if isinstance(item, dict)
        )
        source_count = sum(
            bool((item or {}).get("source"))
            for item in items
            if isinstance(item, dict)
        )
        if fact_count <= 0 or source_count <= 0:
            raise ProbeError("FACT_OUTPUT_INCOMPLETE")
        target_item_matched = False
        for item in items:
            if not (
                isinstance(item, dict)
                and item.get("source")
                and isinstance(item.get("facts"), dict)
                and item["facts"]
            ):
                continue
            semantic_surface = " ".join(
                str(value)
                for value in (
                    item.get("title"),
                    item.get("snippet"),
                    *item["facts"].values(),
                )
                if value
            )
            if "四季酒店" in semantic_surface and "深圳" in semantic_surface:
                target_item_matched = True
                break
        if not target_item_matched:
            raise ProbeError("FACT_OUTPUT_TARGET_MISMATCH")
        confidence = min(0.9, 0.35 + 0.12 * fact_count + 0.04 * source_count)
        return {
            **_result_summary(items),
            "structured_fact_count": fact_count,
            "source_count": source_count,
            "confidence_milli": int(round(confidence * 1000)),
            "target_entity_matched": True,
            "target_region_matched": True,
            "transport": transport,
        }

    def amap(self) -> dict[str, Any]:
        items = self.fact_enrichment._search_amap(
            PUBLIC_FACT_QUERY,
            max_detail_requests=0,
        )
        return {
            **self._fact_result(items, "fact_enrichment_amap_text_only"),
            "http_request_count": 1,
            "detail_request_count": 0,
        }

    def meituan(self) -> dict[str, Any]:
        items = self.fact_enrichment._search_meituan_travel(PUBLIC_FACT_QUERY)
        return {
            **self._fact_result(items, "fact_enrichment_meituan_travel"),
            "cli_invocation_count": 1,
        }

    def close(self) -> None:
        self.billing.clear_active_usage()


def execute_probe(
    backend: Any,
    account_gates: dict[str, Any],
    *,
    clock=_utc_now,
    journal: AttemptJournal | None = None,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt_bytes = len((SYNTHETIC_SYSTEM + SYNTHETIC_USER).encode("utf-8"))
    if prompt_bytes > MAX_PROMPT_BYTES:
        raise ProbeError("PROMPT_CAP_EXCEEDED")
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "task_id": TASK_ID,
        "status": "RUNNING",
        "observed_at_utc": clock(),
        "account_gate": account_gates,
        "bounds": {
            "provider_order": list(DISPATCH_ORDER),
            "maximum_dispatches_per_provider": 1,
            "maximum_output_tokens": MAX_OUTPUT_TOKENS,
            "maximum_prompt_bytes": MAX_PROMPT_BYTES,
            "actual_prompt_bytes": prompt_bytes,
            "automatic_retry_count": 0,
            "fallback_count": 0,
            "total_cost_cap_rmb": MEITUAN_COST_OVERRIDE,
        },
        "preflight": {},
        "providers": {},
        "totals": {},
        "data_boundary": {
            "synthetic_ai_prompt_only": True,
            "public_fact_query_only": True,
            "user_content_count": 0,
            "response_content_persisted_count": 0,
            "response_url_persisted_count": 0,
            "noteai_business_database_connection_count": 0,
            "noteai_business_database_write_count": 0,
            "gateway_control_plane_request_expected": True,
            "gateway_terminal_record_ttl_days": 30,
        },
    }
    try:
        if preflight is None:
            try:
                result["preflight"] = backend.preflight()
            except Exception:
                raise ProbeError("PREFLIGHT_FAILED") from None
        else:
            result["preflight"] = preflight
        for provider in DISPATCH_ORDER:
            try:
                _normalize_account_gates(account_gates, now_text=clock())
            except ProbeError:
                if result["providers"]:
                    result["status"] = "UNKNOWN"
                    if journal is not None:
                        journal.transition("UNKNOWN")
                    break
                raise
            if journal is not None:
                journal.transition("DISPATCHING", provider)
            started = time.monotonic()
            try:
                provider_result = getattr(backend, provider)()
            except Exception as exc:
                result["failure_code"] = (
                    exc.code
                    if isinstance(exc, ProbeError) and exc.code in {
                        "CLAUDE_OUTPUT_INVALID",
                        "MODEL_USAGE_MISSING",
                        "MODEL_USAGE_NOT_ACTUAL",
                    }
                    else "RUNTIME_INTERNAL_ERROR"
                )
                result["providers"][provider] = {
                    "status": "UNKNOWN",
                    "dispatch_count": 1,
                    "automatic_retry_count": 0,
                    "fallback_count": 0,
                    "unknown_count": 1,
                    "elapsed_millis": int((time.monotonic() - started) * 1000),
                }
                result["status"] = "UNKNOWN"
                if journal is not None:
                    journal.transition("UNKNOWN", provider)
                    journal.transition("UNKNOWN")
                break
            if not (
                isinstance(provider_result, dict)
                and set(provider_result) == SAFE_PROVIDER_RESULT_KEYS[provider]
                and provider_result.get("output_bytes", 0) > 0
                and _valid_digest(provider_result.get("output_sha256"))
            ):
                result["providers"][provider] = {
                    "status": "UNKNOWN",
                    "dispatch_count": 1,
                    "automatic_retry_count": 0,
                    "fallback_count": 0,
                    "unknown_count": 1,
                    "elapsed_millis": int(
                        (time.monotonic() - started) * 1000
                    ),
                }
                result["status"] = "UNKNOWN"
                if journal is not None:
                    journal.transition("UNKNOWN", provider)
                    journal.transition("UNKNOWN")
                break
            result["providers"][provider] = {
                "status": "SUCCESS",
                "dispatch_count": 1,
                "automatic_retry_count": 0,
                "fallback_count": 0,
                "unknown_count": 0,
                "elapsed_millis": int((time.monotonic() - started) * 1000),
                **provider_result,
            }
            if journal is not None:
                journal.transition("SUCCESS", provider)
        if result["status"] == "RUNNING":
            result["status"] = "PASS"
            if journal is not None:
                journal.transition("PASS")
    finally:
        try:
            backend.close()
        except Exception:
            result["status"] = "UNKNOWN"
            if journal is not None:
                journal.transition("UNKNOWN")

    providers = result["providers"]
    actual_model_cost = sum(
        Decimal(row.get("actual_cost_rmb", "0"))
        for row in providers.values()
        if isinstance(row, dict)
    )
    result["totals"] = {
        "successful_provider_count": sum(
            row.get("status") == "SUCCESS" for row in providers.values()
        ),
        "dispatch_count": sum(
            int(row.get("dispatch_count", 0)) for row in providers.values()
        ),
        "unknown_count": sum(
            int(row.get("unknown_count", 0)) for row in providers.values()
        ),
        "automatic_retry_count": 0,
        "fallback_count": 0,
        "actual_model_cost_rmb": _decimal_text(actual_model_cost),
        "worst_case_provider_cost_rmb": NOT_EXPOSED_BY_PROVIDER,
    }
    return result


def _validate_state_dir(path: Path) -> None:
    if path != STATE_DIR:
        raise ProbeError("STATE_DIR_FORBIDDEN")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ProbeError("STATE_DIR_UNAVAILABLE") from exc
    if (
        not stat.S_ISDIR(mode)
        or path.is_symlink()
        or not os.path.ismount(path)
        or _mount_filesystem(path) in {"tmpfs", "overlay"}
    ):
        raise ProbeError("STATE_DIR_UNAVAILABLE")
    try:
        gate_stat = ACCOUNT_GATES_PATH.lstat()
    except OSError as exc:
        raise ProbeError("ACCOUNT_GATES_UNREADABLE") from exc
    if (
        ACCOUNT_GATES_PATH.is_symlink()
        or not stat.S_ISREG(gate_stat.st_mode)
        or stat.S_IMODE(gate_stat.st_mode) not in {0o400, 0o600}
    ):
        raise ProbeError("ACCOUNT_GATES_UNREADABLE")
    if RESULT_PATH.exists() or RESULT_PATH.is_symlink():
        raise ProbeError("EXECUTION_ALREADY_ATTEMPTED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    artifacts: tuple[Path, ...] = ()
    backend: ProductionProbeBackend | None = None
    journal: AttemptJournal | None = None
    gates: dict[str, Any] | None = None
    cleanup_failed = False
    try:
        _validate_state_dir(STATE_DIR)
        artifacts = _validate_sqlite_path(SQLITE_PATH)
        _validate_environment_boundary()
        gates = load_account_gates(ACCOUNT_GATES_PATH)
        _runtime_source_binding(gates)
        with open(os.devnull, "w", encoding="utf-8") as stdout_sink:
            with contextlib.redirect_stdout(stdout_sink):
                backend = ProductionProbeBackend(SQLITE_PATH)
                try:
                    preflight = backend.preflight()
                except Exception:
                    raise ProbeError("PREFLIGHT_FAILED") from None
                journal = AttemptJournal.create(RESULT_PATH, gates)
                result = execute_probe(
                    backend,
                    gates,
                    journal=journal,
                    preflight=preflight,
                    clock=_utc_now,
                )
                backend = None
    except Exception as exc:
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass
        failure_code = (
            exc.code if isinstance(exc, ProbeError) else "RUNTIME_INTERNAL_ERROR"
        )
        result = {
            "schema": RESULT_SCHEMA,
            "task_id": TASK_ID,
            "status": "UNKNOWN" if journal is not None else "BLOCKED",
            "observed_at_utc": _utc_now(),
            "failure_code": failure_code,
        }
        if gates is not None:
            result["account_gate"] = gates
        if journal is None:
            print(json.dumps({"status": "BLOCKED", "failure_code": failure_code}))
            return 2
        try:
            journal.transition("UNKNOWN")
        except Exception:
            pass
    finally:
        for artifact in artifacts:
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
        if cleanup_failed and journal is not None:
            try:
                journal.transition("UNKNOWN")
            except Exception:
                pass
    if cleanup_failed:
        result["status"] = "UNKNOWN"
        result["failure_code"] = "EPHEMERAL_DATABASE_CLEANUP_FAILED"
    result["cleanup"] = {
        "ephemeral_database_residue_count": sum(
            artifact.exists() for artifact in artifacts
        ),
        "credential_file_persisted_by_executor_count": 0,
    }
    if journal is None:
        print(json.dumps({"status": "BLOCKED", "failure_code": "JOURNAL_MISSING"}))
        return 2
    result["attempt"] = journal.value
    try:
        journal.finalize(result)
    except Exception:
        try:
            journal.transition("UNKNOWN")
        except Exception:
            pass
        print(json.dumps({"status": "UNKNOWN", "failure_code": "FINALIZE_FAILED"}))
        return 2
    sys.stdout.write(_terminal_summary(result).decode("ascii"))
    sys.stdout.flush()
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
