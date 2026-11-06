"""Content-free, database-authoritative model rate admission.

These verified account ceilings are separate from local CPU, memory and socket
capacity. A caller reserves rate, money and its unique public_trial_calls row in
one write transaction, then dispatches once. This module never commits or calls a
supplier. Ordinary rate exhaustion is a deferral, not a failed Invocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
import re


_WINDOW_SECONDS = 60
_BUCKET_COUNT = _WINDOW_SECONDS + 1
_LOCK_KEY = (1312904273, 1296253264)
_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SCOPE = re.compile(r"^[a-zA-Z0-9_.:-]{1,100}$")
_SOURCE = "ark-console-model-limits-20261105"
_DEFAULTS = {
    "doubao-seed-2-0-lite-260428": ("doubao-seed-2.0-lite", 30000, 5000000, None),
    "doubao-seed-2-1-pro-260915": ("doubao-seed-2.1-pro", 500, 1000000, None),
    "doubao-seedream-5-0-pro-260628": ("doubao-seedream-5.0-pro", None, None, 500),
}
_KIMI = "kimi-k2.6"
_HAIKU_5_5 = "claude-haiku-5-5"
_CLAUDE = ("claude-haiku-4-5-20251001", "claude-sonnet-4-6", _HAIKU_5_5)
_CLAUDE_QUOTA_KEYS = {"claude-haiku-4-5-20251001": "claude-haiku-4.5",
                      "claude-sonnet-4-6": "claude-sonnet-4.6",
                      _HAIKU_5_5: "claude-haiku-5.5"}
_INTEGRATED = (*_DEFAULTS, _KIMI, *_CLAUDE)


class CapacityError(RuntimeError):
    pass


class CapacityConfigurationError(CapacityError):
    pass


class CapacityDemandError(CapacityError):
    pass


class CapacityStateError(CapacityError):
    pass


class QuotaDeferred(CapacityError):
    def __init__(self, retry_at, reason):
        self.retry_at, self.reason = float(retry_at), str(reason)
        super().__init__(self.reason)


@dataclass(frozen=True)
class Demand:
    model_id: str
    input_tokens: int
    output_tokens: int
    images: int = 0

    def __post_init__(self):
        if (not isinstance(self.model_id, str) or not _NAME.fullmatch(self.model_id)
                or any(type(value) is not int or not 0 <= value <= 1000000000
                       for value in (self.input_tokens, self.output_tokens, self.images))):
            raise CapacityDemandError("MODEL_CAPACITY_DEMAND_INVALID")


@dataclass(frozen=True)
class Policy:
    scope_key: str
    quota_key: str
    model_ids: tuple[str, ...]
    rpm: int | None
    tpm: int | None
    ipm: int | None
    verified_ref: str
    concurrency: int | None = None
    itpm: int | None = None
    otpm: int | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_at: float | None = None
    reason: str | None = None


def enabled():
    return os.environ.get("NOTEAI_MODEL_CAPACITY_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"}


def model_ids():
    """Integrated IDs only; policy_for decides whether each is active."""
    return tuple(_INTEGRATED)


def _overrides():
    raw = os.environ.get("NOTEAI_MODEL_CAPACITY_LIMITS_JSON", "")
    if not raw:
        return {}
    try:
        if len(raw.encode()) > 16384:
            raise ValueError()
        values = json.loads(raw)
        if (type(values) is not dict or set(values) - set(_INTEGRATED)
                or any(type(value) is not dict for value in values.values())):
            raise ValueError()
        for identity, value in values.items():
            allowed = ({"rpm", "itpm", "otpm", "concurrency"} if identity in _CLAUDE else
                       {"ipm", "concurrency"} if identity == "doubao-seedream-5-0-pro-260628"
                       else {"rpm", "tpm", "concurrency"})
            if (set(value) - allowed - {"evidence_ref"} or not set(value) & allowed
                    or type(value.get("evidence_ref")) is not str
                    or not 1 <= len(value["evidence_ref"].strip()) <= 500
                    or any(type(amount) is not int or not 1 <= amount <= 1000000000
                           for key, amount in value.items() if key != "evidence_ref")
                    or (identity in _CLAUDE and not {"rpm", "itpm", "otpm"} <= set(value))):
                raise ValueError()
        return values
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise CapacityConfigurationError("MODEL_CAPACITY_POLICY_INVALID") from None


def policy_for(model_id):
    """Verified ceilings; an API key never defines independent account quota.

    Ark retains its verified model defaults. Moonshot needs a separate explicit
    activation after the production key/account binding is verified. Claude has
    no fabricated defaults: its exact model needs complete evidenced RPM/ITPM/
    OTPM settings. Unknown routes retain their legacy provider protection.
    """
    if not enabled() or model_id not in _INTEGRATED:
        return None
    overrides = _overrides()
    values = overrides.get(model_id, {})
    if model_id in _CLAUDE:
        if not values:
            return None
        scope = os.environ.get("NOTEAI_MODEL_CAPACITY_CLAUDE_SCOPE", "claude-primary")
        key = _CLAUDE_QUOTA_KEYS[model_id]
        defaults = (values["rpm"], None, None)
        reference = values["evidence_ref"]
    elif model_id == _KIMI:
        if os.environ.get("NOTEAI_MODEL_CAPACITY_MOONSHOT_ENABLED", "0").strip().lower() not in {
                "1", "true", "yes", "on"}:
            return None
        scope = os.environ.get("NOTEAI_MODEL_CAPACITY_MOONSHOT_SCOPE", "moonshot-primary")
        key, defaults = "moonshot-account", (200, 3000000, None)
        reference = "moonshot-console-account-limits-20261105"
    else:
        scope = os.environ.get("NOTEAI_MODEL_CAPACITY_SCOPE", "ark-primary")
        key, *defaults = _DEFAULTS[model_id]
        reference = _SOURCE
    if not _SCOPE.fullmatch(scope):
        raise CapacityConfigurationError("MODEL_CAPACITY_SCOPE_INVALID")
    rpm, tpm, ipm = defaults
    return Policy(scope, key, (model_id,), values.get("rpm", rpm), values.get("tpm", tpm),
                  values.get("ipm", ipm), values.get("evidence_ref", reference),
                  values.get("concurrency", 50 if model_id == _KIMI else None),
                  values.get("itpm"), values.get("otpm"))


def require_verified_policy(model_id):
    """The new model must never borrow the old model's legacy admission limits."""
    policy = policy_for(model_id)
    if model_id == _HAIKU_5_5 and policy is None:
        raise CapacityConfigurationError("MODEL_CAPACITY_POLICY_UNVERIFIED")
    return policy


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_capacity_buckets (
 scope_key TEXT NOT NULL CHECK(length(scope_key) BETWEEN 1 AND 100),
 quota_key TEXT NOT NULL CHECK(length(quota_key) BETWEEN 1 AND 100),
 slot INTEGER NOT NULL CHECK(slot BETWEEN 0 AND 60),
 epoch_second INTEGER NOT NULL CHECK(epoch_second>=0 AND slot=epoch_second%61),
 request_count INTEGER NOT NULL CHECK(request_count>=0),
 token_bound INTEGER NOT NULL CHECK(token_bound>=0),
 image_count INTEGER NOT NULL CHECK(image_count>=0),
 input_bound INTEGER NOT NULL CHECK(input_bound>=0),
 output_bound INTEGER NOT NULL CHECK(output_bound>=0),
 CHECK(token_bound=input_bound+output_bound),
 PRIMARY KEY(scope_key,quota_key,slot)
)
"""


def init_sqlite_schema(connection):
    """Explicit SQLite initializer; one statement, with no implicit commit."""
    connection.execute(SQLITE_SCHEMA)


def acquire_transaction_lock(tx):
    """Take before budget row locks, consistently across every model/budget.

    SQLite write transactions already serialize. One short PostgreSQL lock also
    protects any retained cross-model physical guard against cross-budget races.
    No locks or transactions may be held while waiting for quota availability.
    """
    if tx.postgres:
        tx.fetchone("SELECT pg_advisory_xact_lock(?,?)", _LOCK_KEY)


def _database_now(tx, now):
    if now is None:
        row = tx.fetchone("SELECT clock_timestamp() AS now" if tx.postgres else
                          "SELECT strftime('%Y-%m-%dT%H:%M:%f+00:00','now') AS now")
        now = row["now"]
    if isinstance(now, str):
        try:
            now = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except ValueError:
            raise CapacityStateError("MODEL_CAPACITY_CLOCK_INVALID") from None
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise CapacityStateError("MODEL_CAPACITY_CLOCK_INVALID")
    timestamp = now.astimezone(timezone.utc).timestamp()
    if not math.isfinite(timestamp) or timestamp < 0:
        raise CapacityStateError("MODEL_CAPACITY_CLOCK_INVALID")
    return timestamp


def _demand_values(policy, demand):
    if not isinstance(demand, Demand):
        raise CapacityDemandError("MODEL_CAPACITY_DEMAND_INVALID")
    values = (1, demand.input_tokens + demand.output_tokens, demand.images,
              demand.input_tokens, demand.output_tokens)
    if ((policy.ipm is None and demand.images != 0)
            or (policy.tpm is None and policy.itpm is None and policy.otpm is None
                and (demand.input_tokens or demand.output_tokens))
            or (policy.ipm is not None and demand.images < 1)):
        raise CapacityDemandError("MODEL_CAPACITY_DEMAND_UNITS_INVALID")
    limits = (policy.rpm, policy.tpm, policy.ipm, policy.itpm, policy.otpm)
    if any(limit is not None and value > limit for value, limit in zip(values, limits)):
        raise CapacityDemandError("MODEL_CAPACITY_DEMAND_EXCEEDS_QUOTA")
    return values, limits


def _active_rows(tx, policy, second):
    rows = tx.fetchall("SELECT epoch_second,slot,request_count,token_bound,image_count,input_bound,output_bound "
        "FROM model_capacity_buckets WHERE scope_key=? AND quota_key=?",
        (policy.scope_key, policy.quota_key))
    if len(rows) > _BUCKET_COUNT:
        raise CapacityStateError("MODEL_CAPACITY_BUCKET_INVALID")
    active = []
    for row in rows:
        values = [row[key] for key in ("epoch_second", "slot", "request_count", "token_bound", "image_count", "input_bound", "output_bound")]
        if (any(type(value) is not int or value < 0 for value in values)
                or values[1] != values[0] % _BUCKET_COUNT
                or values[3] != values[5] + values[6]):
            raise CapacityStateError("MODEL_CAPACITY_BUCKET_INVALID")
        if values[0] > second:
            raise CapacityStateError("MODEL_CAPACITY_CLOCK_REVERSED")
        if values[0] >= second - _WINDOW_SECONDS:
            active.append((values[0], tuple(values[2:])))
    return active


def _decision(tx, demand, policy, timestamp):
    requested, limits = _demand_values(policy, demand)
    active = _active_rows(tx, policy, math.floor(timestamp))
    totals = [sum(values[index] for _second, values in active) for index in range(5)]

    def fits():
        return all(limit is None or used + extra <= limit
                   for used, extra, limit in zip(totals, requested, limits))

    if fits():
        return Decision(True), active
    exceeded = next(name for name, used, extra, limit in
        zip(("RPM", "TPM", "IPM", "ITPM", "OTPM"), totals, requested, limits)
        if limit is not None and used + extra > limit)
    for second, values in sorted(active):
        totals = [used - value for used, value in zip(totals, values)]
        if fits():
            return Decision(False, float(second + _BUCKET_COUNT),
                            "MODEL_CAPACITY_" + exceeded), active
    raise CapacityStateError("MODEL_CAPACITY_BUCKET_INVALID")


def read_available(tx, demand, *, now=None):
    """Read-only scheduling hint; reserve_in_transaction is authoritative."""
    if not isinstance(demand, Demand):
        raise CapacityDemandError("MODEL_CAPACITY_DEMAND_INVALID")
    policy = require_verified_policy(demand.model_id)
    if policy is None:
        return Decision(True)
    timestamp = _database_now(tx, now)
    return _decision(tx, demand, policy, timestamp)[0]


def reserve_in_transaction(tx, demand, *, call_id, now=None):
    """Reserve rate immediately before the caller's unique physical-row insert.

    Caller MUST hold one write transaction through this function, its existing
    financial reservation and public_trial_calls INSERT. A unique-row conflict
    rolls back the bucket too. A caller must never commit quota independently.
    Existing physical IDs reject all replay, including after rate buckets age.
    Cancellation and known results do not refund this conservative rate bound;
    it expires naturally. Existing UNKNOWN money and identity remain untouched.
    """
    if not isinstance(demand, Demand):
        raise CapacityDemandError("MODEL_CAPACITY_DEMAND_INVALID")
    policy = require_verified_policy(demand.model_id)
    if policy is None:
        return {}
    if not isinstance(call_id, str) or not _NAME.fullmatch(call_id):
        raise CapacityDemandError("MODEL_CAPACITY_CALL_ID_INVALID")
    acquire_transaction_lock(tx)
    if tx.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)) is not None:
        raise CapacityStateError("MODEL_CAPACITY_CALL_ALREADY_RESERVED")
    timestamp = _database_now(tx, now)
    decision, active = _decision(tx, demand, policy, timestamp)
    if not decision.allowed:
        raise QuotaDeferred(decision.retry_at, decision.reason)
    second = math.floor(timestamp)
    values, _limits = _demand_values(policy, demand)
    before = next((counts for when, counts in active if when == second), (0, 0, 0, 0, 0))
    totals = tuple(left + right for left, right in zip(before, values))
    tx.execute("INSERT INTO model_capacity_buckets(scope_key,quota_key,slot,epoch_second,"
        "request_count,token_bound,image_count,input_bound,output_bound) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(scope_key,quota_key,slot) DO UPDATE SET epoch_second=excluded.epoch_second,"
        "request_count=excluded.request_count,token_bound=excluded.token_bound,image_count=excluded.image_count,"
        "input_bound=excluded.input_bound,output_bound=excluded.output_bound",
        (policy.scope_key, policy.quota_key, second % _BUCKET_COUNT, second, *totals))
    return {"v": 1, "scope": policy.scope_key, "quota_key": policy.quota_key,
            "model": demand.model_id, "input_bound": demand.input_tokens,
            "output_bound": demand.output_tokens, "images": demand.images,
            "rpm": policy.rpm, "tpm": policy.tpm, "ipm": policy.ipm,
            "itpm": policy.itpm, "otpm": policy.otpm, "concurrency": policy.concurrency,
            "evidence_ref": policy.verified_ref, "admitted_epoch_second": second}
