"""Shared, persistent Amap basic-search admissions. No automatic initialization.

One account bucket covers both existing Keys and both supported endpoints. Every
physical HTTP attempt is charged conservatively before dispatch and never released,
including uncertain transport/commit outcomes. Snapshots are operator-controlled
observations, not a live provider balance or permission assertion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import uuid


ACCOUNT_SCOPE = "noteai-primary-amap-account"
SERVICE_GROUP = "basic_search"
ENDPOINT_QPS = {"text": 30, "detail": 30}
ENDPOINT_URLS = {
    "https://restapi.amap.com/v3/place/text": "text",
    "https://restapi.amap.com/v5/place/detail": "detail",
}
ERROR_SOURCE = "https://lbs.amap.com/api/webservice/guide/tools/info"
AUTH_CODES = frozenset({"10001", "10002", "10005", "10006", "10007", "10008", "10009", "10010", "10011", "10012", "10013", "10041", "40002"})
ACCOUNT_CODES = frozenset({"10003", "10026", "10044", "40000"})
QPS_CODES = frozenset({"10004", "10014", "10015", "10019", "10020", "10021", "10029"})

# SQLite has no role ACL; this schema is for the existing local initializer only.
# Production uses 0031 and explicit column grants, never this initializer.
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS amap_quota_buckets (
 account_scope TEXT NOT NULL CHECK(account_scope='noteai-primary-amap-account'),
 service_group TEXT NOT NULL CHECK(service_group='basic_search'),
 period TEXT NOT NULL CHECK(length(period)=7),
 period_start TEXT NOT NULL, period_end TEXT NOT NULL,
 time_zone TEXT NOT NULL CHECK(time_zone='Asia/Shanghai'),
 quota INTEGER NOT NULL CHECK(quota BETWEEN 1 AND 1000000000),
 official_used INTEGER NOT NULL CHECK(official_used BETWEEN 0 AND quota),
 observed_at TEXT NOT NULL, source TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 500),
 snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256)=64),
 owner_authorized_at TEXT NOT NULL,
 enterprise_certified INTEGER NOT NULL CHECK(enterprise_certified=1),
 license_purchased INTEGER NOT NULL CHECK(license_purchased=0),
 owner_risk_accepted INTEGER NOT NULL CHECK(owner_risk_accepted=1),
 exclusive_noteai_use INTEGER NOT NULL CHECK(exclusive_noteai_use=1),
 billing_observation_json TEXT,
 admitted_count INTEGER NOT NULL DEFAULT 0 CHECK(admitted_count>=0 AND official_used+admitted_count<=quota),
 account_block_code TEXT, account_block_until TEXT,
 text_block_code TEXT, text_block_until TEXT, detail_block_code TEXT, detail_block_until TEXT,
 PRIMARY KEY(account_scope,service_group,period)
);
CREATE TABLE IF NOT EXISTS amap_quota_attempts (
 id TEXT PRIMARY KEY, account_scope TEXT NOT NULL, service_group TEXT NOT NULL, period TEXT NOT NULL,
 endpoint TEXT NOT NULL CHECK(endpoint IN('text','detail')), admitted_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN('reserved','succeeded','failed','unknown')),
 http_status INTEGER, business_code TEXT, completed_at TEXT,
 FOREIGN KEY(account_scope,service_group,period) REFERENCES amap_quota_buckets(account_scope,service_group,period)
);
CREATE INDEX IF NOT EXISTS idx_amap_quota_qps ON amap_quota_attempts(account_scope,service_group,period,endpoint,admitted_at);
CREATE TRIGGER IF NOT EXISTS amap_quota_bucket_guard BEFORE UPDATE ON amap_quota_buckets
WHEN NEW.account_scope<>OLD.account_scope OR NEW.service_group<>OLD.service_group OR NEW.period<>OLD.period
 OR NEW.period_start<>OLD.period_start OR NEW.period_end<>OLD.period_end OR NEW.time_zone<>OLD.time_zone
 OR NEW.quota<>OLD.quota OR NEW.official_used<>OLD.official_used OR NEW.observed_at<>OLD.observed_at
 OR NEW.source<>OLD.source OR NEW.snapshot_sha256<>OLD.snapshot_sha256
 OR NEW.owner_authorized_at<>OLD.owner_authorized_at OR NEW.enterprise_certified<>OLD.enterprise_certified
 OR NEW.license_purchased<>OLD.license_purchased OR NEW.owner_risk_accepted<>OLD.owner_risk_accepted
 OR NEW.exclusive_noteai_use<>OLD.exclusive_noteai_use OR NEW.admitted_count<OLD.admitted_count
BEGIN SELECT RAISE(ABORT,'amap baseline and cumulative admissions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS amap_quota_attempt_guard BEFORE UPDATE ON amap_quota_attempts
WHEN NEW.id<>OLD.id OR NEW.account_scope<>OLD.account_scope OR NEW.service_group<>OLD.service_group
 OR NEW.period<>OLD.period OR NEW.endpoint<>OLD.endpoint OR NEW.admitted_at<>OLD.admitted_at
 OR OLD.status<>'reserved' OR NEW.status='reserved'
BEGIN SELECT RAISE(ABORT,'amap attempt cannot be replayed or rewritten'); END;
"""


class AmapQuotaError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Admission:
    id: str
    period: str
    endpoint: str


def _storage(storage):
    if storage is None:
        import db
        return db
    return storage


def _clock(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("clock")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("zoned clock")
    return parsed.astimezone(timezone.utc)


def _iso(value):
    return _clock(value).isoformat(timespec="microseconds")


def _database_now(storage):
    # PostgreSQL CURRENT_TIMESTAMP is transaction-start time; admission uses the
    # clock after acquiring the bucket lock, including time spent waiting for it.
    if getattr(storage, "postgres", False) or (hasattr(storage, "using_postgres") and storage.using_postgres()):
        row = storage.fetchone("SELECT clock_timestamp() AS now")
        return _clock(row["now"])
    row = storage.fetchone("SELECT strftime('%Y-%m-%dT%H:%M:%f+00:00','now') AS now")
    return _clock(row["now"])


def _bucket(storage, *, lock=False):
    suffix = " FOR UPDATE" if lock and storage.postgres else ""
    row = storage.fetchone("SELECT * FROM amap_quota_buckets WHERE account_scope=? AND service_group=? "
                           "ORDER BY period DESC LIMIT 1" + suffix, (ACCOUNT_SCOPE, SERVICE_GROUP))
    return dict(row) if row is not None else None


def _account_lock(tx):
    # Serializes old-period outcomes with new-period admissions as well as the
    # current bucket. SQLite's BEGIN IMMEDIATE already serializes writers.
    if tx.postgres:
        tx.fetchone("SELECT pg_advisory_xact_lock(?,?)", (1095582032, 1112752979))


def _restrictions(storage, now):
    # A fresh monthly quota observation cannot clear an earlier auth/account
    # denial. Only a recorded operator recovery may clear the original fields.
    rows = storage.fetchall("SELECT * FROM amap_quota_buckets WHERE account_scope=? AND service_group=? ORDER BY period",
                            (ACCOUNT_SCOPE, SERVICE_GROUP))
    blocked = dict.fromkeys(ENDPOINT_QPS)
    for raw in rows:
        row = dict(raw)
        _validate_bucket(row)
        account = _active_block(row, "account", now)
        for endpoint in ENDPOINT_QPS:
            blocked[endpoint] = blocked[endpoint] or account or _active_block(row, endpoint, now)
    return blocked


def _validate_bucket(row):
    if (row["account_scope"] != ACCOUNT_SCOPE or row["service_group"] != SERVICE_GROUP
        or not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", row["period"])
        or row["time_zone"] != "Asia/Shanghai" or type(row["quota"]) is not int or not 1 <= row["quota"] <= 1000000000
        or any(type(row[name]) is not int or row[name] < 0 for name in ("official_used", "admitted_count"))
        or row["official_used"] + row["admitted_count"] > row["quota"]
        or not re.fullmatch(r"[0-9a-f]{64}", row["snapshot_sha256"])
        or not isinstance(row["source"], str) or not 1 <= len(row["source"]) <= 500
        or any(row[name] != expected for name, expected in (
            ("enterprise_certified", 1), ("license_purchased", 0),
            ("owner_risk_accepted", 1), ("exclusive_noteai_use", 1)))):
        raise ValueError("snapshot shape")
    start, end, observed, authorized = (_clock(row[key]) for key in
        ("period_start", "period_end", "observed_at", "owner_authorized_at"))
    # Explicit stored boundaries are required. No calendar rollover is guessed.
    if not start <= observed < end or authorized > observed or not 27 <= (end-start).total_seconds()/86400 <= 32:
        raise ValueError("snapshot clocks")
    if start.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m") != row["period"]:
        raise ValueError("snapshot period")
    for prefix in ("account", "text", "detail"):
        code, until = row[prefix + "_block_code"], row[prefix + "_block_until"]
        if code is not None and (not isinstance(code, str) or not re.fullmatch(r"(?:[0-9]{5}|HTTP_[0-9]{3})", code)):
            raise ValueError("restriction code")
        if until is not None:
            if code is None:
                raise ValueError("restriction clock")
            _clock(until)
    return start, end, observed, authorized


def _active_block(row, prefix, now):
    code, until = row[prefix + "_block_code"], row[prefix + "_block_until"]
    return code if code and (until is None or _clock(until) > now) else None


def _billing(value):
    if value is None:
        return None
    row = json.loads(value)
    if (not isinstance(row, dict) or set(row) != {"period_start", "period_end", "usage", "cost_cny", "observed_at", "source", "scope"}
        or type(row["usage"]) is not int or row["usage"] < 0
        or type(row["cost_cny"]) not in {int, float} or not 0 <= row["cost_cny"] < 1_000_000
        or row["source"] != "amap_console_bill" or row["scope"] != "observed_period_only"):
        raise ValueError("billing observation")
    for field in ("period_start", "period_end"):
        datetime.strptime(row[field], "%Y-%m-%d")
    _clock(row["observed_at"])
    if row["period_start"] > row["period_end"]:
        raise ValueError("billing period")
    return row


def read_status(*, storage=None):
    """Admin-safe SELECT-only snapshot and conservative local allocation status."""
    result = {"account_scope": ACCOUNT_SCOPE, "service_group": SERVICE_GROUP,
              "snapshot_is_realtime": False, "runtime_activation_inferred": False,
              "remaining": None, "snapshot": None}
    try:
        storage = _storage(storage)
        row = _bucket(storage)
        if row is None:
            return {**result, "status": "snapshot_missing", "reason": "AMAP_QUOTA_SNAPSHOT_REQUIRED"}
        start, end, observed, authorized = _validate_bucket(row)
        now = _database_now(storage)
        snapshot = {key: row[key] for key in ("period", "period_start", "period_end", "time_zone", "quota",
            "official_used", "observed_at", "source", "snapshot_sha256", "owner_authorized_at")}
        for key in ("period_start", "period_end", "observed_at", "owner_authorized_at"):
            snapshot[key] = _iso(snapshot[key])
        snapshot.update(enterprise_certified=True, license_purchased=False, owner_risk_accepted=True,
            exclusive_noteai_use=True, admitted_since_snapshot=row["admitted_count"],
            remaining=row["quota"]-row["official_used"]-row["admitted_count"], endpoint_qps=dict(ENDPOINT_QPS),
            blocked_endpoints=_restrictions(storage, now), billing_observation=_billing(row["billing_observation_json"]))
        result["snapshot"] = snapshot
        if now >= end:
            return {**result, "status": "snapshot_expired", "reason": "AMAP_QUOTA_SNAPSHOT_EXPIRED"}
        if now < max(start, observed, authorized):
            return {**result, "status": "snapshot_not_current", "reason": "AMAP_QUOTA_SNAPSHOT_NOT_CURRENT"}
        if not snapshot["remaining"]:
            return {**result, "status": "quota_exhausted", "reason": "AMAP_MONTHLY_QUOTA_EXHAUSTED", "remaining": 0}
        return {**result, "status": "access_restricted" if any(snapshot["blocked_endpoints"].values()) else "ready",
                "reason": "AMAP_PROVIDER_ACCESS_RESTRICTED" if any(snapshot["blocked_endpoints"].values()) else None,
                "remaining": snapshot["remaining"]}
    except Exception:
        return {**result, "status": "unavailable", "reason": "AMAP_QUOTA_STATE_UNAVAILABLE", "snapshot": None}


def admit(endpoint, *, storage=None, attempt_id=None):
    """Commit one irreversible quota admission before the only HTTP dispatch."""
    if endpoint not in ENDPOINT_QPS:
        raise AmapQuotaError("AMAP_ENDPOINT_NOT_ALLOWED")
    identity = attempt_id or str(uuid.uuid4())
    try:
        valid_identity = str(uuid.UUID(identity)) == identity
    except (ValueError, TypeError, AttributeError):
        valid_identity = False
    if not valid_identity:
        raise AmapQuotaError("AMAP_ADMISSION_ID_INVALID")
    try:
        with _storage(storage).transaction(write=True) as tx:
            _account_lock(tx)
            row = _bucket(tx, lock=True)
            if row is None:
                raise AmapQuotaError("AMAP_QUOTA_SNAPSHOT_REQUIRED")
            start, end, observed, authorized = _validate_bucket(row)
            now = _database_now(tx)
            if now < max(start, observed, authorized):
                raise AmapQuotaError("AMAP_QUOTA_SNAPSHOT_NOT_CURRENT")
            if now + timedelta(seconds=10) >= end:
                raise AmapQuotaError("AMAP_QUOTA_SNAPSHOT_EXPIRED")
            if _restrictions(tx, now)[endpoint]:
                raise AmapQuotaError("AMAP_PROVIDER_ACCESS_RESTRICTED")
            if tx.fetchone("SELECT id FROM amap_quota_attempts WHERE id=?", (identity,)) is not None:
                raise AmapQuotaError("AMAP_ADMISSION_ALREADY_USED")
            if row["official_used"] + row["admitted_count"] >= row["quota"]:
                raise AmapQuotaError("AMAP_MONTHLY_QUOTA_EXHAUSTED")
            qps = tx.fetchone("SELECT count(*) AS count FROM amap_quota_attempts WHERE account_scope=? AND service_group=? "
                "AND period=? AND endpoint=? AND admitted_at>?", (ACCOUNT_SCOPE, SERVICE_GROUP, row["period"], endpoint, _iso(now-timedelta(seconds=1))))
            if qps["count"] >= ENDPOINT_QPS[endpoint]:
                raise AmapQuotaError("AMAP_QPS_LIMIT_REACHED")
            tx.execute("UPDATE amap_quota_buckets SET admitted_count=admitted_count+1 WHERE account_scope=? AND service_group=? AND period=?",
                       (ACCOUNT_SCOPE, SERVICE_GROUP, row["period"]))
            tx.execute("INSERT INTO amap_quota_attempts(id,account_scope,service_group,period,endpoint,admitted_at,status) "
                       "VALUES(?,?,?,?,?,?,'reserved')", (identity, ACCOUNT_SCOPE, SERVICE_GROUP, row["period"], endpoint, _iso(now)))
        return Admission(identity, row["period"], endpoint)
    except AmapQuotaError:
        raise
    except Exception:
        # A failed commit response may already have consumed this admission.
        # No caller may dispatch, release, or retry it from this exception.
        raise AmapQuotaError("AMAP_QUOTA_STATE_UNKNOWN") from None


def finish(admission, *, status, http_status=None, business_code=None, storage=None):
    """Record known/unknown outcome; never reduce admissions or auto-retry."""
    if (not isinstance(admission, Admission) or status not in {"succeeded", "failed", "unknown"}
        or (http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599))
        or (business_code is not None and not re.fullmatch(r"[0-9]{5}", business_code))):
        raise AmapQuotaError("AMAP_OUTCOME_INVALID")
    try:
        with _storage(storage).transaction(write=True) as tx:
            _account_lock(tx)
            # Same lock order as admission; no lost quota/block updates.
            bucket = tx.fetchone("SELECT * FROM amap_quota_buckets WHERE account_scope=? AND service_group=? AND period=?" +
                (" FOR UPDATE" if tx.postgres else ""), (ACCOUNT_SCOPE, SERVICE_GROUP, admission.period))
            row = tx.fetchone("SELECT * FROM amap_quota_attempts WHERE id=?", (admission.id,))
            if (bucket is None or row is None or row["account_scope"] != ACCOUNT_SCOPE
                or row["service_group"] != SERVICE_GROUP or row["period"] != admission.period or row["endpoint"] != admission.endpoint):
                raise AmapQuotaError("AMAP_ADMISSION_BINDING_INVALID")
            if row["status"] != "reserved":
                if (row["status"], row["http_status"], row["business_code"]) == (status, http_status, business_code):
                    return
                raise AmapQuotaError("AMAP_OUTCOME_ALREADY_RECORDED")
            now = _database_now(tx)
            tx.execute("UPDATE amap_quota_attempts SET status=?,http_status=?,business_code=?,completed_at=? WHERE id=?",
                       (status, http_status, business_code, _iso(now), admission.id))
            scope = code = until = None
            if business_code in ACCOUNT_CODES:
                scope, code = "account", business_code
            elif business_code in AUTH_CODES or http_status in {401, 403}:
                scope, code = admission.endpoint, business_code or "HTTP_" + str(http_status)
            elif business_code in QPS_CODES or http_status == 429:
                scope = "account" if business_code == "10019" else admission.endpoint
                code = business_code or "HTTP_429"
                until = _iso(now + timedelta(seconds=60 if business_code == "10004" else 1))
            if scope is not None:
                bucket = dict(bucket)
                existing = _active_block(bucket, scope, now)
                # A late temporary failure cannot overwrite an existing durable restriction.
                if existing and bucket[scope + "_block_until"] is None:
                    return
                if existing and until and _clock(bucket[scope + "_block_until"]) > _clock(until):
                    return
                tx.execute(f"UPDATE amap_quota_buckets SET {scope}_block_code=?,{scope}_block_until=? "
                    "WHERE account_scope=? AND service_group=? AND period=?", (code, until, ACCOUNT_SCOPE, SERVICE_GROUP, admission.period))
    except AmapQuotaError:
        raise
    except Exception:
        raise AmapQuotaError("AMAP_OUTCOME_STATE_UNKNOWN") from None
