#!/usr/bin/env python3
"""Validate the single canonical Item 30 production-provider evidence file."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-PROVIDER-CHAIN-001"
EVIDENCE_SCHEMA = "noteai.item30.real-ai-provider-chain-evidence.v1"
RESULT_SCHEMA = "noteai.item30.real-ai-provider-chain-result.v1"
ACCOUNT_GATE_SCHEMA = "noteai.item30.account-gates.v1"
JOURNAL_SCHEMA = "noteai.item30.execution-journal.v1"
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-real-ai-provider-chain-verified-20260824.json"
)
EVIDENCE_PATH = ROOT / EVIDENCE_REF
EXECUTOR_REF = "deploy/production/real_ai_provider_chain.py"
FACT_ENRICHMENT_REF = "model/fact_enrichment.py"
VERIFIER_REF = "tools/verify_real_ai_provider_chain_evidence.py"
REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF,
    EXECUTOR_REF,
    FACT_ENRICHMENT_REF,
    VERIFIER_REF,
}
SOURCE_BRANCH = "codex/quality-stabilization-real-chain"
APPLICATION_RELEASE_REVISION = "b55f11882100e9ef919522540729e366a511f88f"
APPLICATION_MANIFEST_SHA256 = (
    "612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620"
)
APPLICATION_CONFIG_SHA256 = (
    "dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53"
)
GATEWAY_RELEASE_REVISION = "84f8a2f1436627e0f05588ee0276b1950b230ae3"
COMMAND_NAME = "noteai-item30-real-provider-chain-20260824"
PROVIDERS = ("claude", "kimi", "amap", "meituan")
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
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
KIMI_MODEL = "kimi-k2.6"
SENTINEL = b"NOTEAI_OK"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DECIMAL = re.compile(r"^(0|[1-9]\d*)\.\d{6}$")
SAFE_COUNTER_NAME = re.compile(r"^[a-z0-9_.-]{1,64}$")
MAX_EVIDENCE_BYTES = 256 * 1024
ACCOUNT_GATE_MAX_AGE = timedelta(minutes=30)
MIN_GATE_REMAINING = timedelta(minutes=7)
AI_RECONCILIATION_TOLERANCE = Decimal("0.010000")
DEFAULT_READINESS = {
    "internal_verified_before": 29,
    "internal_verified_after": 29,
    "internal_total": 29,
    "internal_percentage_after": 100,
    "complete_public_verified_before": 29,
    "complete_public_verified_after": 30,
    "complete_public_total": 38,
    "complete_public_percentage_after": 79,
    "next_task": "PROD-FIRST-LAUNCH-PAYMENT-REAL-001",
    "public_launch_authorized": False,
    "real_provider_chain_verified": True,
}


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


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not 1 <= len(raw) <= MAX_EVIDENCE_BYTES or b"\x00" in raw:
        raise ValueError("evidence size/encoding invalid")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    if type(value) is not dict:
        raise ValueError("evidence root must be an object")
    return value


def terminal_acceptance_sha256(value: dict[str, Any]) -> str:
    return _sha256(
        _canonical(
            {
                key: item
                for key, item in value.items()
                if key != "terminal_acceptance_sha256"
            }
        )
    )


def _append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


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


def _decimal(value: Any) -> Decimal | None:
    if not isinstance(value, str) or DECIMAL.fullmatch(value) is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or UTC.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if not parsed.microsecond else None


def _digest(value: Any, *, nonzero: bool = True) -> bool:
    return (
        isinstance(value, str)
        and HEX64.fullmatch(value) is not None
        and (not nonzero or value != "0" * 64)
    )


def _git_exists(root: Path, revision: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _git_blob(root: Path, revision: str, ref: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{ref}"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def _validate_source(source: Any, *, root: Path, verify_git: bool) -> list[str]:
    errors: list[str] = []
    expected_keys = {
        "branch",
        "execution_source_revision",
        "executor_ref",
        "executor_sha256",
        "fact_enrichment_ref",
        "fact_enrichment_sha256",
        "runtime_executor_sha256",
        "runtime_fact_enrichment_sha256",
        "application_release_revision",
        "application_manifest_sha256",
        "application_config_sha256",
        "application_executor_readonly_overlay",
        "application_fact_enrichment_readonly_overlay",
        "gateway_service",
        "gateway_release_revision",
        "gateway_region",
        "gateway_health_path",
        "gateway_health_http_status",
    }
    if type(source) is not dict or set(source) != expected_keys:
        return ["source binding shape mismatch"]
    revision = source["execution_source_revision"]
    _append(errors, source["branch"] == SOURCE_BRANCH, "source branch mismatch")
    _append(
        errors,
        isinstance(revision, str) and HEX40.fullmatch(revision) is not None,
        "execution source revision invalid",
    )
    _append(errors, source["executor_ref"] == EXECUTOR_REF, "executor ref mismatch")
    _append(
        errors,
        source["fact_enrichment_ref"] == FACT_ENRICHMENT_REF,
        "fact enrichment ref mismatch",
    )
    for name in (
        "executor_sha256",
        "fact_enrichment_sha256",
        "runtime_executor_sha256",
        "runtime_fact_enrichment_sha256",
    ):
        _append(errors, _digest(source[name]), f"{name} invalid")
    _append(
        errors,
        source["runtime_executor_sha256"] == source["executor_sha256"],
        "runtime executor SHA mismatch",
    )
    _append(
        errors,
        source["runtime_fact_enrichment_sha256"]
        == source["fact_enrichment_sha256"],
        "runtime fact enrichment SHA mismatch",
    )
    if verify_git and isinstance(revision, str) and HEX40.fullmatch(revision):
        _append(errors, _git_exists(root, revision), "execution source missing")
        executor_blob = _git_blob(root, revision, EXECUTOR_REF)
        fact_blob = _git_blob(root, revision, FACT_ENRICHMENT_REF)
        _append(
            errors,
            executor_blob is not None
            and _sha256(executor_blob) == source["executor_sha256"],
            "executor Git blob mismatch",
        )
        _append(
            errors,
            fact_blob is not None
            and _sha256(fact_blob) == source["fact_enrichment_sha256"],
            "fact enrichment Git blob mismatch",
        )
    _append(
        errors,
        source["application_release_revision"] == APPLICATION_RELEASE_REVISION,
        "application release revision mismatch",
    )
    _append(
        errors,
        source["application_manifest_sha256"] == APPLICATION_MANIFEST_SHA256,
        "application manifest mismatch",
    )
    _append(
        errors,
        source["application_config_sha256"] == APPLICATION_CONFIG_SHA256,
        "application config mismatch",
    )
    _append(
        errors,
        source["application_executor_readonly_overlay"] is True,
        "executor overlay boundary mismatch",
    )
    _append(
        errors,
        source["application_fact_enrichment_readonly_overlay"] is True,
        "fact enrichment overlay boundary mismatch",
    )
    _append(
        errors,
        source["gateway_service"] == "noteai-prod-claude-gateway"
        and source["gateway_release_revision"] == GATEWAY_RELEASE_REVISION
        and source["gateway_region"] == "Singapore (Southeast Asia)"
        and source["gateway_health_path"] == "/health/ready"
        and source["gateway_health_http_status"] == 200,
        "gateway source/health mismatch",
    )
    return errors


ACCOUNT_GATE_KEYS = {
    "schema",
    "generated_at_utc",
    "expires_at_utc",
    "execution_nonce",
    "execution_source_revision",
    "executor_sha256",
    "fact_enrichment_sha256",
    "providers",
}
ACCOUNT_PROVIDER_KEYS = {
    "account_identity_sha256",
    "credential_name_present",
    "balance_or_quota_confirmed",
    "current_price_confirmed",
    "pre_call_counter_readable",
    "pre_call_counter",
    "price_snapshot_sha256",
    "unit_cost_upper_bound_rmb",
}
COUNTER_KEYS = {
    "observed_at_utc",
    "counter_kind",
    "counter_unit",
    "direction",
    "counter_value",
    "snapshot_sha256",
    "source",
}


def _validate_counter(counter: Any, prefix: str) -> tuple[list[str], Decimal | None]:
    errors: list[str] = []
    if type(counter) is not dict or set(counter) != COUNTER_KEYS:
        return [f"{prefix}: counter shape mismatch"], None
    _append(errors, _time(counter["observed_at_utc"]) is not None, f"{prefix}: counter time invalid")
    _append(
        errors,
        isinstance(counter["counter_kind"], str)
        and SAFE_COUNTER_NAME.fullmatch(counter["counter_kind"]) is not None
        and isinstance(counter["counter_unit"], str)
        and SAFE_COUNTER_NAME.fullmatch(counter["counter_unit"]) is not None,
        f"{prefix}: counter name invalid",
    )
    _append(
        errors,
        counter["direction"] in {"increasing", "decreasing"},
        f"{prefix}: counter direction invalid",
    )
    _append(
        errors,
        counter["source"] == "provider_account_console",
        f"{prefix}: counter source mismatch",
    )
    value = _decimal(counter["counter_value"])
    _append(errors, value is not None, f"{prefix}: counter value invalid")
    _append(errors, _digest(counter["snapshot_sha256"]), f"{prefix}: counter snapshot invalid")
    return errors, value


def _validate_account_gate(
    gate: Any,
    *,
    source: dict[str, Any],
    execution_start: datetime,
    execution_finish: datetime,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if type(gate) is not dict or set(gate) != ACCOUNT_GATE_KEYS:
        return ["account gate shape mismatch"], {}
    _append(errors, gate["schema"] == ACCOUNT_GATE_SCHEMA, "account gate schema mismatch")
    _append(errors, _digest(gate["execution_nonce"]), "execution nonce invalid")
    _append(
        errors,
        gate["execution_source_revision"] == source["execution_source_revision"]
        and gate["executor_sha256"] == source["executor_sha256"]
        and gate["fact_enrichment_sha256"] == source["fact_enrichment_sha256"],
        "account gate source binding mismatch",
    )
    generated = _time(gate["generated_at_utc"])
    expires = _time(gate["expires_at_utc"])
    _append(
        errors,
        generated is not None
        and expires is not None
        and generated <= execution_start <= execution_finish <= expires
        and expires - generated <= ACCOUNT_GATE_MAX_AGE
        and expires - execution_start >= MIN_GATE_REMAINING,
        "account gate freshness mismatch",
    )
    providers = gate["providers"]
    if type(providers) is not dict or tuple(providers) != PROVIDERS:
        errors.append("account gate provider set/order mismatch")
        return errors, {}
    for name in PROVIDERS:
        row = providers[name]
        if type(row) is not dict or set(row) != ACCOUNT_PROVIDER_KEYS:
            errors.append(f"{name}: account gate provider shape mismatch")
            continue
        _append(errors, _digest(row["account_identity_sha256"]), f"{name}: account identity invalid")
        _append(errors, _digest(row["price_snapshot_sha256"]), f"{name}: price snapshot invalid")
        counter = row["pre_call_counter"]
        counter_value = counter if type(counter) is dict else {}
        observed = _time(counter_value.get("observed_at_utc"))
        if name == "meituan":
            _append(
                errors,
                type(counter) is dict
                and set(counter) == COUNTER_KEYS
                and row["credential_name_present"] is True
                and row["balance_or_quota_confirmed"] is False
                and row["current_price_confirmed"] is False
                and row["pre_call_counter_readable"] is False
                and counter_value.get("counter_kind")
                == NOT_EXPOSED_BY_PROVIDER
                and counter_value.get("counter_unit")
                == NOT_EXPOSED_BY_PROVIDER
                and counter_value.get("direction")
                == NOT_EXPOSED_BY_PROVIDER
                and counter_value.get("counter_value")
                == NOT_EXPOSED_BY_PROVIDER
                and counter_value.get("source") == "provider_account_console"
                and _digest(counter_value.get("snapshot_sha256"))
                and counter_value.get("snapshot_sha256")
                == row["price_snapshot_sha256"]
                and row["unit_cost_upper_bound_rmb"]
                == NOT_EXPOSED_BY_PROVIDER,
                "meituan: disclosure gate mismatch",
            )
            _append(
                errors,
                observed is not None
                and generated is not None
                and execution_start - ACCOUNT_GATE_MAX_AGE
                <= observed
                <= generated,
                "meituan: disclosure snapshot stale",
            )
            continue
        _append(
            errors,
            row["credential_name_present"] is True
            and row["balance_or_quota_confirmed"] is True
            and row["current_price_confirmed"] is True
            and row["pre_call_counter_readable"] is True,
            f"{name}: account gate not confirmed",
        )
        counter_errors, _ = _validate_counter(counter, f"{name}: pre")
        errors.extend(counter_errors)
        _append(
            errors,
            observed is not None
            and generated is not None
            and execution_start - ACCOUNT_GATE_MAX_AGE <= observed <= generated,
            f"{name}: pre counter stale",
        )
        _append(
            errors,
            (
                counter_value.get("counter_kind"),
                counter_value.get("counter_unit"),
                counter_value.get("direction"),
            )
            in PROVIDER_COUNTER_SEMANTICS[name],
            f"{name}: pre counter semantics mismatch",
        )
        cap = _decimal(row["unit_cost_upper_bound_rmb"])
        _append(
            errors,
            cap is not None and cap <= PROVIDER_CAPS[name],
            f"{name}: account gate cap exceeded",
        )
    return errors, providers


RAW_COMMON_PROVIDER_KEYS = {
    "status", "dispatch_count", "automatic_retry_count", "fallback_count",
    "unknown_count", "elapsed_millis", "output_bytes", "output_sha256",
    "transport",
}
RAW_MODEL_KEYS = {
    "input_tokens", "output_tokens", "model_calls", "provider", "model",
    "pricing_status", "usage_status", "cost_mode", "actual_cost_rmb",
}
RAW_FACT_KEYS = {
    "structured_fact_count", "source_count", "confidence_milli",
    "target_entity_matched", "target_region_matched",
}


def _validate_raw_provider(name: str, row: Any) -> tuple[list[str], Decimal]:
    errors: list[str] = []
    expected = RAW_COMMON_PROVIDER_KEYS | (
        RAW_MODEL_KEYS if name in {"claude", "kimi"} else RAW_FACT_KEYS
    )
    if name == "amap":
        expected |= {"http_request_count", "detail_request_count"}
    if name == "meituan":
        expected |= {"cli_invocation_count"}
    if type(row) is not dict or set(row) != expected:
        return [f"{name}: raw provider shape mismatch"], Decimal("0")
    _append(
        errors,
        row["status"] == "SUCCESS"
        and type(row["dispatch_count"]) is int
        and row["dispatch_count"] == 1
        and type(row["automatic_retry_count"]) is int
        and row["automatic_retry_count"] == 0
        and type(row["fallback_count"]) is int
        and row["fallback_count"] == 0
        and type(row["unknown_count"]) is int
        and row["unknown_count"] == 0
        and type(row["elapsed_millis"]) is int
        and row["elapsed_millis"] >= 0,
        f"{name}: raw dispatch terminal mismatch",
    )
    _append(
        errors,
        type(row["output_bytes"]) is int
        and row["output_bytes"] > 0
        and _digest(row["output_sha256"], nonzero=False),
        f"{name}: raw output summary invalid",
    )
    app_cost = Decimal("0")
    if name in {"claude", "kimi"}:
        expected_model = CLAUDE_MODEL if name == "claude" else KIMI_MODEL
        expected_transport = "production_gateway" if name == "claude" else "model_router_kimi"
        app_cost_value = _decimal(row["actual_cost_rmb"])
        _append(
            errors,
            row["output_bytes"] == len(SENTINEL)
            and row["output_sha256"] == _sha256(SENTINEL),
            f"{name}: sentinel output mismatch",
        )
        _append(
            errors,
            row["provider"] == name
            and row["model"] == expected_model
            and row["transport"] == expected_transport
            and type(row["model_calls"]) is int
            and row["model_calls"] == 1
            and type(row["input_tokens"]) is int
            and row["input_tokens"] > 0
            and type(row["output_tokens"]) is int
            and row["output_tokens"] > 0
            and row["pricing_status"] == "exact"
            and row["usage_status"] == "complete"
            and row["cost_mode"] == "actual"
            and app_cost_value is not None
            and app_cost_value > 0
            and app_cost_value <= PROVIDER_CAPS[name],
            f"{name}: application usage/cost mismatch",
        )
        app_cost = app_cost_value or Decimal("0")
    else:
        _append(
            errors,
            type(row["structured_fact_count"]) is int
            and row["structured_fact_count"] > 0
            and type(row["source_count"]) is int
            and row["source_count"] > 0
            and type(row["confidence_milli"]) is int
            and 1 <= row["confidence_milli"] <= 900
            and row["target_entity_matched"] is True
            and row["target_region_matched"] is True,
            f"{name}: target fact output mismatch",
        )
    if name == "amap":
        _append(
            errors,
            row["transport"] == "fact_enrichment_amap_text_only"
            and type(row["http_request_count"]) is int
            and row["http_request_count"] == 1
            and type(row["detail_request_count"]) is int
            and row["detail_request_count"] == 0,
            "amap: request boundary mismatch",
        )
    if name == "meituan":
        _append(
            errors,
            row["transport"] == "fact_enrichment_meituan_travel"
            and type(row["cli_invocation_count"]) is int
            and row["cli_invocation_count"] == 1,
            "meituan: invocation boundary mismatch",
        )
    return errors, app_cost


def _validate_executor_result(
    raw: Any,
    *,
    source: dict[str, Any],
    execution_start: datetime,
    execution_finish: datetime,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    expected_top = {
        "schema", "task_id", "status", "observed_at_utc", "account_gate",
        "bounds", "preflight", "providers", "totals", "data_boundary",
        "cleanup", "attempt",
    }
    if type(raw) is not dict or set(raw) != expected_top:
        return ["executor result shape mismatch"], {}
    observed = _time(raw["observed_at_utc"])
    _append(
        errors,
        raw["schema"] == RESULT_SCHEMA
        and raw["task_id"] == TASK_ID
        and raw["status"] == "PASS"
        and observed is not None
        and execution_start <= observed <= execution_finish,
        "executor result terminal mismatch",
    )
    gate_errors, gate_providers = _validate_account_gate(
        raw["account_gate"],
        source=source,
        execution_start=execution_start,
        execution_finish=execution_finish,
    )
    errors.extend(gate_errors)
    actual_prompt_bytes = len(
        ("Return only NOTEAI_OK." + "Bounded production transport check.").encode("utf-8")
    )
    _append(
        errors,
        _strict(
            raw["bounds"],
            {
                "provider_order": list(DISPATCH_ORDER),
                "maximum_dispatches_per_provider": 1,
                "maximum_output_tokens": 64,
                "maximum_prompt_bytes": 128,
                "actual_prompt_bytes": actual_prompt_bytes,
                "automatic_retry_count": 0,
                "fallback_count": 0,
                "total_cost_cap_rmb": MEITUAN_COST_OVERRIDE,
            },
        ),
        "executor bounds mismatch",
    )
    _append(
        errors,
        _strict(
            raw["preflight"],
            {
                "claude_transport": "gateway",
                "claude_remote_ready": True,
                "kimi_credential_present": True,
                "amap_credential_present": True,
                "meituan_runtime_status": "MEITUAN_TRAVEL_READY",
            },
        ),
        "executor preflight mismatch",
    )
    providers = raw["providers"]
    if type(providers) is not dict or tuple(providers) != DISPATCH_ORDER:
        errors.append("executor provider set/order mismatch")
        providers = {}
    application_total = Decimal("0")
    for name in PROVIDERS:
        provider_errors, app_cost = _validate_raw_provider(name, providers.get(name))
        errors.extend(provider_errors)
        application_total += app_cost
    _append(
        errors,
        _strict(
            raw["totals"],
            {
                "successful_provider_count": 4,
                "dispatch_count": 4,
                "unknown_count": 0,
                "automatic_retry_count": 0,
                "fallback_count": 0,
                "actual_model_cost_rmb": f"{application_total:.6f}",
                "worst_case_provider_cost_rmb": NOT_EXPOSED_BY_PROVIDER,
            },
        ),
        "executor totals mismatch",
    )
    _append(
        errors,
        _strict(
            raw["data_boundary"],
            {
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
        ),
        "executor data boundary mismatch",
    )
    _append(
        errors,
        _strict(
            raw["cleanup"],
            {
                "ephemeral_database_residue_count": 0,
                "credential_file_persisted_by_executor_count": 0,
            },
        ),
        "executor cleanup mismatch",
    )
    attempt = raw["attempt"]
    expected_attempt_keys = {
        "schema", "execution_nonce", "execution_source_revision",
        "account_gate_sha256", "executor_sha256", "fact_enrichment_sha256",
        "status", "providers",
    }
    _append(
        errors,
        type(attempt) is dict
        and set(attempt) == expected_attempt_keys
        and attempt["schema"] == JOURNAL_SCHEMA
        and attempt["execution_nonce"]
        == (
            raw["account_gate"].get("execution_nonce")
            if isinstance(raw["account_gate"], dict)
            else None
        )
        and attempt["execution_source_revision"] == source["execution_source_revision"]
        and attempt["account_gate_sha256"] == _sha256(_canonical(raw["account_gate"]))
        and attempt["executor_sha256"] == source["executor_sha256"]
        and attempt["fact_enrichment_sha256"] == source["fact_enrichment_sha256"]
        and attempt["status"] == "PASS"
        and _strict(attempt["providers"], {name: "SUCCESS" for name in PROVIDERS}),
        "executor journal binding mismatch",
    )
    return errors, {
        "gate_providers": gate_providers,
        "raw_providers": providers,
        "application_total": application_total,
    }


NATIVE_PRE_KEYS = COUNTER_KEYS | {
    "quota_or_balance_sufficient", "current_unit_cap_rmb",
    "price_snapshot_sha256",
}
SETTLEMENT_KEYS = {
    "observed_at_utc", "status", "currency", "incremental_cost_rmb",
    "reconciliation_tolerance_rmb", "snapshot_sha256",
}


def _validate_native_bindings(
    bindings: Any,
    *,
    context: dict[str, Any],
    execution_start: datetime,
    execution_finish: datetime,
    evidence_observed: datetime | None,
) -> tuple[list[str], Decimal]:
    errors: list[str] = []
    if type(bindings) is not dict or tuple(bindings) != PROVIDERS:
        return ["provider native binding set/order mismatch"], Decimal("0")
    provider_total = Decimal("0")
    gate_providers = context.get("gate_providers") or {}
    raw_providers = context.get("raw_providers") or {}
    for name in PROVIDERS:
        row = bindings[name]
        expected = {
            "account_identity_sha256", "custody", "pre", "post",
            "usage_delta", "native_event_id_sha256", "settlement",
        }
        if type(row) is not dict or set(row) != expected:
            errors.append(f"{name}: native binding shape mismatch")
            continue
        gate = gate_providers.get(name)
        if type(gate) is not dict:
            gate = {}
        raw_provider = raw_providers.get(name)
        if type(raw_provider) is not dict:
            raw_provider = {}
        _append(
            errors,
            _digest(row["account_identity_sha256"])
            and row["account_identity_sha256"] == gate.get("account_identity_sha256")
            and row["custody"] == "protected_off_repo",
            f"{name}: native account binding mismatch",
        )
        pre = row["pre"]
        if name == "meituan":
            post = row["post"]
            settlement = row["settlement"]
            projected_pre = (
                {key: pre[key] for key in COUNTER_KEYS}
                if type(pre) is dict and set(pre) == NATIVE_PRE_KEYS
                else {}
            )
            pre_time = _time(projected_pre.get("observed_at_utc"))
            post_time = (
                _time(post.get("observed_at_utc"))
                if type(post) is dict
                else None
            )
            settlement_time = (
                _time(settlement.get("observed_at_utc"))
                if type(settlement) is dict
                else None
            )
            _append(
                errors,
                type(pre) is dict
                and set(pre) == NATIVE_PRE_KEYS
                and _strict(projected_pre, gate.get("pre_call_counter"))
                and pre.get("quota_or_balance_sufficient")
                == NOT_EXPOSED_BY_PROVIDER
                and pre.get("current_unit_cap_rmb")
                == NOT_EXPOSED_BY_PROVIDER
                and pre.get("price_snapshot_sha256")
                == gate.get("price_snapshot_sha256")
                and _digest(pre.get("price_snapshot_sha256")),
                "meituan: native pre/disclosure projection mismatch",
            )
            _append(
                errors,
                type(post) is dict
                and set(post) == COUNTER_KEYS
                and post.get("counter_kind") == NOT_EXPOSED_BY_PROVIDER
                and post.get("counter_unit") == NOT_EXPOSED_BY_PROVIDER
                and post.get("direction") == NOT_EXPOSED_BY_PROVIDER
                and post.get("counter_value") == NOT_EXPOSED_BY_PROVIDER
                and post.get("source") == "provider_account_console"
                and _digest(post.get("snapshot_sha256")),
                "meituan: native post disclosure mismatch",
            )
            _append(
                errors,
                type(settlement) is dict
                and set(settlement) == SETTLEMENT_KEYS
                and settlement.get("status") == NOT_EXPOSED_BY_PROVIDER
                and settlement.get("currency") == NOT_EXPOSED_BY_PROVIDER
                and settlement.get("incremental_cost_rmb")
                == NOT_EXPOSED_BY_PROVIDER
                and settlement.get("reconciliation_tolerance_rmb")
                == NOT_EXPOSED_BY_PROVIDER
                and settlement.get("snapshot_sha256")
                == (post.get("snapshot_sha256") if type(post) is dict else None)
                and _digest(settlement.get("snapshot_sha256")),
                "meituan: settlement disclosure mismatch",
            )
            _append(
                errors,
                pre_time is not None
                and post_time is not None
                and settlement_time is not None
                and evidence_observed is not None
                and pre_time <= execution_start <= execution_finish
                < post_time <= settlement_time <= evidence_observed,
                "meituan: disclosure observation order mismatch",
            )
            _append(
                errors,
                row["usage_delta"] == NOT_EXPOSED_BY_PROVIDER
                and row["native_event_id_sha256"] is None
                and type(raw_provider.get("cli_invocation_count")) is int
                and raw_provider.get("cli_invocation_count") == 1,
                "meituan: exact-one disclosure binding mismatch",
            )
            continue
        if type(pre) is not dict or set(pre) != NATIVE_PRE_KEYS:
            errors.append(f"{name}: native pre shape mismatch")
            continue
        projected_pre = {key: pre[key] for key in COUNTER_KEYS}
        pre_errors, pre_value = _validate_counter(projected_pre, f"{name}: native pre")
        errors.extend(pre_errors)
        _append(
            errors,
            _strict(projected_pre, gate.get("pre_call_counter"))
            and pre["quota_or_balance_sufficient"] is True
            and pre["current_unit_cap_rmb"] == gate.get("unit_cost_upper_bound_rmb")
            and pre["price_snapshot_sha256"] == gate.get("price_snapshot_sha256")
            and _digest(pre["price_snapshot_sha256"]),
            f"{name}: native pre/gate projection mismatch",
        )
        post_raw = row["post"]
        post_errors, post_value = _validate_counter(post_raw, f"{name}: native post")
        errors.extend(post_errors)
        post = post_raw if type(post_raw) is dict else {}
        pre_time = _time(pre["observed_at_utc"])
        post_time = _time(post.get("observed_at_utc"))
        settlement = row["settlement"]
        if type(settlement) is not dict or set(settlement) != SETTLEMENT_KEYS:
            errors.append(f"{name}: settlement shape mismatch")
            continue
        settlement_time = _time(settlement["observed_at_utc"])
        cost = _decimal(settlement["incremental_cost_rmb"])
        tolerance = _decimal(settlement["reconciliation_tolerance_rmb"])
        gate_cap = _decimal(gate.get("unit_cost_upper_bound_rmb"))
        _append(
            errors,
            pre_time is not None
            and post_time is not None
            and settlement_time is not None
            and evidence_observed is not None
            and pre_time <= execution_start <= execution_finish
            < post_time <= settlement_time <= evidence_observed,
            f"{name}: native observation order mismatch",
        )
        _append(
            errors,
            type(post_raw) is dict
            and post.get("counter_kind") == pre["counter_kind"]
            and post.get("counter_unit") == pre["counter_unit"]
            and post.get("direction") == pre["direction"],
            f"{name}: native counter identity mismatch",
        )
        delta = _decimal(row["usage_delta"])
        calculated_delta = None
        if pre_value is not None and post_value is not None:
            calculated_delta = (
                post_value - pre_value
                if pre["direction"] == "increasing"
                else pre_value - post_value
            )
        _append(
            errors,
            delta is not None and delta > 0 and calculated_delta == delta,
            f"{name}: native counter arithmetic mismatch",
        )
        event = row["native_event_id_sha256"]
        _append(errors, event is None or _digest(event), f"{name}: native event identity invalid")
        _append(
            errors,
            settlement["status"] == "RECONCILED"
            and settlement["currency"] == "RMB"
            and cost is not None
            and gate_cap is not None
            and cost <= gate_cap
            and tolerance == AI_RECONCILIATION_TOLERANCE
            and _digest(settlement["snapshot_sha256"]),
            f"{name}: settlement mismatch",
        )
        kind = pre["counter_kind"]
        unit = pre["counter_unit"]
        if name in {"claude", "kimi"}:
            _append(
                errors,
                (kind, unit, pre["direction"])
                in PROVIDER_COUNTER_SEMANTICS[name],
                f"{name}: native AI counter kind mismatch",
            )
            if kind == "request_count":
                _append(errors, delta == Decimal("1"), f"{name}: native request delta mismatch")
            elif kind == "total_tokens":
                input_tokens = raw_provider.get("input_tokens")
                output_tokens = raw_provider.get("output_tokens")
                _append(
                    errors,
                    type(input_tokens) is int
                    and type(output_tokens) is int
                    and delta == Decimal(input_tokens + output_tokens),
                    f"{name}: native token delta mismatch",
                )
            elif kind in {"billed_cost_rmb", "remaining_balance_rmb"}:
                _append(errors, delta == cost, f"{name}: native cost counter mismatch")
            app_cost = _decimal(raw_provider.get("actual_cost_rmb"))
            _append(
                errors,
                app_cost is not None
                and cost is not None
                and abs(cost - app_cost) <= AI_RECONCILIATION_TOLERANCE,
                f"{name}: native/application cost reconciliation mismatch",
            )
        elif name == "amap":
            _append(
                errors,
                kind == "request_count"
                and unit == "requests"
                and pre["direction"] == "increasing"
                and delta == Decimal("1")
                and type(raw_provider.get("http_request_count")) is int
                and raw_provider.get("http_request_count") == 1
                and type(raw_provider.get("detail_request_count")) is int
                and raw_provider.get("detail_request_count") == 0,
                "amap: native request delta mismatch",
            )
        provider_total += cost or Decimal("0")
    return errors, provider_total


def validate_document(
    value: Any,
    *,
    root: Path = ROOT,
    expected_readiness: dict[str, Any] | None = None,
    verify_git: bool = True,
) -> list[str]:
    errors: list[str] = []
    expected_top = {
        "schema", "task_id", "status", "observed_at_utc", "source_binding",
        "execution", "provider_native_bindings", "cost_and_settlement",
        "production_boundary", "resources", "cleanup", "readiness",
        "terminal_acceptance_sha256",
    }
    if type(value) is not dict or set(value) != expected_top:
        return ["evidence shape mismatch"]
    _append(errors, value["schema"] == EVIDENCE_SCHEMA, "schema mismatch")
    _append(errors, value["task_id"] == TASK_ID, "task mismatch")
    observed = _time(value["observed_at_utc"])
    _append(errors, value["status"] == "PASS" and observed is not None, "terminal status/time mismatch")
    source = value["source_binding"]
    errors.extend(_validate_source(source, root=root, verify_git=verify_git))
    if not isinstance(source, dict) or not {
        "execution_source_revision",
        "executor_sha256",
        "fact_enrichment_sha256",
    } <= set(source):
        return errors
    execution = value["execution"]
    execution_keys = {
        "command_name", "command_identity_sha256", "invocation_identity_sha256",
        "terminal_status", "exit_code", "repeat_count", "dropped_count",
        "started_at_utc", "finished_at_utc", "stdout_sha256",
        "executor_result_sha256", "executor_result",
    }
    if type(execution) is not dict or set(execution) != execution_keys:
        return errors + ["execution binding shape mismatch"]
    started = _time(execution["started_at_utc"])
    finished = _time(execution["finished_at_utc"])
    _append(
        errors,
        execution["command_name"] == COMMAND_NAME
        and _digest(execution["command_identity_sha256"])
        and _digest(execution["invocation_identity_sha256"])
        and execution["terminal_status"] == "Success"
        and type(execution["exit_code"]) is int
        and execution["exit_code"] == 0
        and type(execution["repeat_count"]) is int
        and execution["repeat_count"] == 1
        and type(execution["dropped_count"]) is int
        and execution["dropped_count"] == 0
        and started is not None
        and finished is not None
        and started < finished
        and observed is not None
        and finished <= observed,
        "execution terminal binding mismatch",
    )
    raw = execution["executor_result"]
    raw_sha = _sha256(_canonical(raw)) if type(raw) is dict else ""
    expected_stdout = _canonical({"executor_result_sha256": raw_sha, "status": "PASS"})
    _append(
        errors,
        execution["executor_result_sha256"] == raw_sha
        and _digest(raw_sha, nonzero=False)
        and execution["stdout_sha256"] == _sha256(expected_stdout),
        "execution raw/stdout SHA binding mismatch",
    )
    if started is None or finished is None:
        return errors
    raw_errors, context = _validate_executor_result(
        raw, source=source, execution_start=started, execution_finish=finished,
    )
    errors.extend(raw_errors)
    native_errors, provider_total = _validate_native_bindings(
        value["provider_native_bindings"],
        context=context,
        execution_start=started,
        execution_finish=finished,
        evidence_observed=observed,
    )
    errors.extend(native_errors)
    cost = value["cost_and_settlement"]
    expected_cost_keys = {
        "currency", "incremental_provider_cost_rmb",
        "application_model_cost_rmb", "incremental_cloud_compute_cost_rmb",
        "gateway_control_plane_cost_mode", "total_incremental_cost_rmb",
        "hard_cap_rmb", "within_cap", "provider_settlement_complete_count",
    }
    if type(cost) is not dict or set(cost) != expected_cost_keys:
        errors.append("cost settlement shape mismatch")
    else:
        app_cost = _decimal(cost["application_model_cost_rmb"])
        cloud_cost = _decimal(cost["incremental_cloud_compute_cost_rmb"])
        _append(
            errors,
            cost["currency"] == "RMB"
            and cost["incremental_provider_cost_rmb"]
            == NOT_EXPOSED_BY_PROVIDER
            and provider_total > Decimal("0")
            and provider_total <= KNOWN_PRICED_PROVIDER_COST_CAP
            and app_cost == context.get("application_total")
            and cloud_cost == Decimal("0")
            and cost["gateway_control_plane_cost_mode"]
            == "existing_fin_003_budget_no_per_call_settlement"
            and cost["total_incremental_cost_rmb"]
            == NOT_EXPOSED_BY_PROVIDER
            and cost["hard_cap_rmb"] == MEITUAN_COST_OVERRIDE
            and cost["within_cap"] == NOT_DETERMINABLE
            and type(cost["provider_settlement_complete_count"]) is int
            and cost["provider_settlement_complete_count"] == 3,
            "cost settlement mismatch",
        )
    _append(
        errors,
        _strict(
            value["production_boundary"],
            {
                "synthetic_ai_prompt_only": True,
                "public_fact_query_only": True,
                "provider_dispatch_count": 4,
                "user_content_count": 0,
                "response_content_persisted_count": 0,
                "response_url_persisted_count": 0,
                "noteai_business_database_connection_count": 0,
                "noteai_business_database_write_count": 0,
                "gateway_control_plane_request_expected": True,
                "gateway_terminal_record_ttl_days": 30,
                "gateway_control_plane_new_resource_count": 0,
                "production_service_restart_count": 0,
                "production_payment_mutation_count": 0,
                "production_dns_mutation_count": 0,
                "render_deploy_count": 0,
                "postpaid_instance_start_count": 0,
            },
        ),
        "production boundary mismatch",
    )
    _append(
        errors,
        _strict(
            value["resources"],
            {
                "api_c": {"status": "Running", "charge_type": "PrePaid"},
                "api_f": {"status": "Running", "charge_type": "PrePaid"},
                "builder": {"status": "Stopped", "billing_state": "StopCharging", "charge_type": "PostPaid"},
                "worker_c": {"status": "Stopped", "billing_state": "StopCharging", "charge_type": "PostPaid"},
                "worker_f": {"status": "Stopped", "billing_state": "StopCharging", "charge_type": "PostPaid"},
                "temporary_compute_count": 0,
                "temporary_listener_count": 0,
                "temporary_security_group_count": 0,
                "temporary_peering_count": 0,
                "temporary_route_count": 0,
                "result_mount_type": "bind",
                "readonly_source_bind_count": 2,
                "temporary_docker_volume_count": 0,
            },
        ),
        "resource state mismatch",
    )
    _append(
        errors,
        _strict(
            value["cleanup"],
            {
                "task_container_residue_count": 0,
                "task_file_residue_count": 0,
                "credential_residue_count": 0,
                "ephemeral_database_residue_count": 0,
                "operation_lock_count": 0,
                "task_volume_residue_count": 0,
                "api_container_identity_unchanged": True,
                "api_container_restart_count": 0,
                "api_live_http_status": 200,
                "api_ready_http_status": 200,
            },
        ),
        "cleanup mismatch",
    )
    _append(
        errors,
        _strict(value["readiness"], expected_readiness or DEFAULT_READINESS),
        "readiness mismatch",
    )
    acceptance = value["terminal_acceptance_sha256"]
    _append(
        errors,
        _digest(acceptance, nonzero=False)
        and acceptance == terminal_acceptance_sha256(value),
        "terminal acceptance mismatch",
    )
    return errors


def validate_manifest_evidence(
    entries: Any,
    *,
    root: Path = ROOT,
    expected_readiness: dict[str, Any] | None = None,
) -> list[str]:
    if type(entries) is not list or any(type(row) is not dict for row in entries):
        return ["manifest evidence fields mismatch"]
    paths = {row.get("ref") for row in entries if row.get("kind") == "path"}
    git_refs = [row.get("ref") for row in entries if row.get("kind") == "git"]
    if paths != REQUIRED_MANIFEST_PATH_REFS or len(git_refs) != 1:
        return ["manifest evidence refs mismatch"]
    try:
        value = load_evidence(root / EVIDENCE_REF)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return ["evidence read failed: " + type(exc).__name__]
    source = value.get("source_binding") if isinstance(value, dict) else None
    if (
        not isinstance(source, dict)
        or source.get("execution_source_revision") != git_refs[0]
    ):
        return ["manifest source revision mismatch"]
    return validate_document(
        value,
        root=root,
        expected_readiness=expected_readiness,
        verify_git=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", nargs="?", type=Path, default=EVIDENCE_PATH)
    args = parser.parse_args(argv)
    try:
        value = load_evidence(args.evidence)
        errors = validate_document(value)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        errors = ["evidence read failed: " + type(exc).__name__]
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=True))
        return 1
    print(json.dumps({"valid": True, "task_id": TASK_ID}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
