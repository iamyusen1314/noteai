#!/usr/bin/env python3
"""Append an operator-attested, current-month Amap observation; never query Amap.

This is a maintenance tool, not an automatic provider-balance refresh. It cannot
prove the truth of a console observation. The operator must retain and inspect
the official artifact and attest its account, Key identity and shared scope.
Default --plan is SELECT-only. --apply uses the existing maintenance role and
schema; it never initializes a database, changes grants or rewrites a baseline.
Secrets are accepted only from the process environment and are never emitted.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys

MODEL = Path(__file__).resolve().parents[1] / "model"
sys.path.insert(0, str(MODEL))
import amap_quota as quota

SHANGHAI = timezone(timedelta(hours=8))
EVIDENCE_MAX_AGE = timedelta(hours=24)
KEY_ALIAS = "noteai-rot-0902"
SOURCE = "amap_console_base_search_statistics"
FIELDS = {"version", "account_scope", "service_group", "period", "period_start", "period_end", "time_zone",
          "quota", "official_used", "observed_at", "source", "official_observation_sha256", "attestations"}
ATTESTATIONS = {"console_account_matches", "key_alias", "key_scope", "runtime_key_observed_at", "verified_at",
                "enterprise_certified", "license_purchased", "owner_risk_accepted", "exclusive_noteai_use"}
BASELINE_FIELDS = ("account_scope", "service_group", "period", "period_start", "period_end", "time_zone",
                   "quota", "official_used", "observed_at", "source", "snapshot_sha256", "owner_authorized_at",
                   "enterprise_certified", "license_purchased", "owner_risk_accepted", "exclusive_noteai_use")


class RefreshError(RuntimeError):
    """Only allowlisted error codes reach the CLI; no underlying exception text."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class CommitUnknown(RuntimeError):
    """COMMIT may have succeeded. No automatic retry or claim of no writes."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally repeats invalid argv. An accidentally supplied DSN
        # or Key must not be echoed even though secrets belong in env only.
        print(json.dumps({"status": "rejected", "code": "AMAP_REFRESH_ARGUMENTS_INVALID",
                          "changed": False, "automatic_retry": False}, sort_keys=True))
        raise SystemExit(2)


@dataclass(frozen=True)
class PreparedEvidence:
    baseline: dict
    verified_at: datetime
    runtime_key_observed_at: datetime


def prepare_evidence(evidence_path, official_path, *, configured_key, observed_key):
    """Validate bounded files and in-memory Key equality, without printing them.

    Both Key values must come from trusted runtime/console observations, not
    from the JSON. Equality alone does not prove the console account identity.
    The source file is an operator-attested official artifact, never a fixture
    that this tool upgrades into official verification.
    """
    try:
        path = Path(evidence_path)
        if path.stat().st_size > 16384:
            raise RefreshError("AMAP_REFRESH_EVIDENCE_INVALID")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict) or set(evidence) != FIELDS:
            raise RefreshError("AMAP_REFRESH_EVIDENCE_INVALID")
        attestation = evidence["attestations"]
        if (not isinstance(attestation, dict) or set(attestation) != ATTESTATIONS
            or type(evidence["version"]) is not int or evidence["version"] != 1
            or evidence["account_scope"] != quota.ACCOUNT_SCOPE or evidence["service_group"] != quota.SERVICE_GROUP
            or evidence["time_zone"] != "Asia/Shanghai" or evidence["source"] != SOURCE
            or attestation["key_alias"] != KEY_ALIAS or attestation["key_scope"] != "web_service"
            or any(attestation[name] is not expected for name, expected in (
                ("console_account_matches", True), ("enterprise_certified", True), ("license_purchased", False),
                ("owner_risk_accepted", True), ("exclusive_noteai_use", True)))):
            raise RefreshError("AMAP_REFRESH_ATTESTATION_INVALID")
        if (not isinstance(configured_key, str) or not configured_key.strip()
            or not isinstance(observed_key, str) or not observed_key.strip()):
            raise RefreshError("AMAP_REFRESH_KEY_OBSERVATION_REQUIRED")
        if not hmac.compare_digest(hashlib.sha256(configured_key.encode()).digest(),
                                   hashlib.sha256(observed_key.encode()).digest()):
            raise RefreshError("AMAP_REFRESH_KEY_MISMATCH")
        if (type(evidence["quota"]) is not int or not 0 <= evidence["quota"] <= 1000000000
            or type(evidence["official_used"]) is not int or not 0 <= evidence["official_used"] <= evidence["quota"]):
            raise RefreshError("AMAP_REFRESH_EVIDENCE_INVALID")
        sha = evidence["official_observation_sha256"]
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise RefreshError("AMAP_REFRESH_EVIDENCE_INVALID")
        artifact = Path(official_path)
        if not artifact.is_file() or artifact.stat().st_size > 20 * 1024 * 1024 or artifact.stat().st_size == 0:
            raise RefreshError("AMAP_REFRESH_OFFICIAL_ARTIFACT_REQUIRED")
        with artifact.open("rb") as stream:
            observed_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if not hmac.compare_digest(sha, observed_sha):
            raise RefreshError("AMAP_REFRESH_OFFICIAL_ARTIFACT_MISMATCH")
        for name in ("period_start", "period_end", "observed_at"):
            evidence[name] = quota._iso(evidence[name])
        for name in ("verified_at", "runtime_key_observed_at"):
            attestation[name] = quota._iso(attestation[name])
        # A canonical JSON digest binds all assertions and the retained artifact.
        # It contains no Key bytes or Key fingerprint.
        digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        row = {name: evidence[name] for name in BASELINE_FIELDS if name in evidence}
        row.update(snapshot_sha256=digest, enterprise_certified=1, license_purchased=0,
                   owner_risk_accepted=1, exclusive_noteai_use=1)
        return PreparedEvidence(row, quota._clock(attestation["verified_at"]),
                                quota._clock(attestation["runtime_key_observed_at"]))
    except RefreshError:
        raise
    except Exception:
        raise RefreshError("AMAP_REFRESH_EVIDENCE_UNREADABLE") from None


def _calendar(now):
    local = now.astimezone(SHANGHAI)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.strftime("%Y-%m"), start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _baseline(row):
    result = {name: row[name] for name in BASELINE_FIELDS}
    for name in ("period_start", "period_end", "observed_at", "owner_authorized_at"):
        result[name] = quota._iso(result[name])
    return result


def refresh_snapshot(storage, evidence, *, apply=False):
    """Plan or append one immutable month under the admission account lock.

    Tests supply an explicit disposable storage adapter. CLI storage is only
    PostgreSQL, via the maintenance DSN. Existing restrictions remain in their
    original records and continue to govern admission across month boundaries.
    """
    if not isinstance(evidence, PreparedEvidence):
        raise RefreshError("AMAP_REFRESH_EVIDENCE_INVALID")
    try:
        with storage.transaction(write=apply) as tx:
            if apply:
                quota._account_lock(tx)
            previous = quota._bucket(tx, lock=apply)
            if previous is None:
                raise RefreshError("AMAP_REFRESH_ORIGINAL_SNAPSHOT_REQUIRED")
            _, old_end, _, _ = quota._validate_bucket(previous)
            now = quota._database_now(tx)
            period, start, end = _calendar(now)
            row = dict(evidence.baseline)
            # Standing owner authorization is retained, not invented per month.
            row.update(owner_authorized_at=previous["owner_authorized_at"], admitted_count=0,
                       billing_observation_json=None, account_block_code=None, account_block_until=None,
                       text_block_code=None, text_block_until=None, detail_block_code=None, detail_block_until=None)
            observed = quota._clock(row["observed_at"])
            if (row["period"] != period or quota._clock(row["period_start"]) != start
                or quota._clock(row["period_end"]) != end):
                raise RefreshError("AMAP_REFRESH_PERIOD_NOT_CURRENT")
            if now + timedelta(seconds=10) >= end:
                raise RefreshError("AMAP_REFRESH_PERIOD_CLOSING")
            if (observed > now or evidence.verified_at > now or evidence.runtime_key_observed_at > now
                or evidence.verified_at < observed or not start <= observed < end
                or not start <= evidence.runtime_key_observed_at < end):
                raise RefreshError("AMAP_REFRESH_OBSERVATION_NOT_CURRENT")
            # Official zero quota cannot satisfy the original schema. Keep the
            # hold; never manufacture a positive quota or relax its guard.
            if row["quota"] == 0:
                raise RefreshError("AMAP_REFRESH_OFFICIAL_QUOTA_ZERO_HOLD")
            quota._validate_bucket(row)
            restrictions = quota._restrictions(tx, now)
            if previous["period"] == period:
                if _baseline(previous) != _baseline(row):
                    raise RefreshError("AMAP_REFRESH_CURRENT_BASELINE_CONFLICT")
                return {"status": "same_month_noop", "changed": False, "period": period,
                        "snapshot_sha256": row["snapshot_sha256"], "key_matches": True,
                        "admitted_count": previous["admitted_count"], "blocked_endpoints": restrictions,
                        "evidence_scope": "operator_attested_console_observation", "provider_requests": 0}
            if previous["period"] >= period or old_end > now:
                raise RefreshError("AMAP_REFRESH_PREVIOUS_PERIOD_NOT_EXPIRED")
            if any(now - clock > EVIDENCE_MAX_AGE for clock in
                   (observed, evidence.verified_at, evidence.runtime_key_observed_at)):
                raise RefreshError("AMAP_REFRESH_OBSERVATION_TOO_OLD")
            status = "applied" if apply else "plan_ready"
            if apply:
                names = tuple(row)
                tx.execute("INSERT INTO amap_quota_buckets(" + ",".join(names) + ") VALUES(" +
                           ",".join("?" for _ in names) + ")", tuple(row[name] for name in names))
                stored = quota._bucket(tx)
                if stored is None or _baseline(stored) != _baseline(row) or stored["admitted_count"] != 0:
                    raise RefreshError("AMAP_REFRESH_READBACK_MISMATCH")
            result = {"status": status, "changed": apply, "period": period,
                      "snapshot_sha256": row["snapshot_sha256"], "key_matches": True,
                      "remaining": row["quota"] - row["official_used"], "blocked_endpoints": restrictions,
                      "evidence_scope": "operator_attested_console_observation", "provider_requests": 0,
                      "billing_current_period": "unknown"}
        # Only a successfully acknowledged commit reaches this return.
        return result
    except (RefreshError, CommitUnknown):
        raise
    except Exception:
        raise RefreshError("AMAP_REFRESH_STATE_UNAVAILABLE") from None


class _PostgresTransaction:
    postgres = True

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(sql.replace("?", "%s"), params)

    def fetchone(self, sql, params=()):
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        return self.execute(sql, params).fetchall()


class MaintenancePostgresStorage:
    """No db import, dotenv, SQLite fallback, initialization or retry."""
    def __init__(self, dsn):
        if not isinstance(dsn, str) or not dsn.startswith(("postgresql://", "postgres://")):
            raise RefreshError("AMAP_REFRESH_MAINTENANCE_DSN_REQUIRED")
        self.dsn = dsn

    @contextmanager
    def transaction(self, *, write=False):
        try:
            import psycopg
            from psycopg.rows import dict_row
            connection = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row,
                                         connect_timeout=10, options="-c statement_timeout=15000 -c lock_timeout=5000")
        except Exception:
            raise RefreshError("AMAP_REFRESH_CONNECTION_UNAVAILABLE") from None
        try:
            connection.execute("BEGIN")
            if not write:
                connection.execute("SET TRANSACTION READ ONLY")
            # Scope only this transaction to the original public-schema tables;
            # a maintenance login's custom search_path must not select a shadow
            # quota bucket. No database-wide/runtime configuration is changed.
            connection.execute("SET LOCAL search_path = pg_catalog, public")
            tx = _PostgresTransaction(connection)
            identity = tx.fetchone("SELECT current_user AS role, "
                                   "has_table_privilege(current_user,'public.amap_quota_buckets','SELECT') AS can_read, "
                                   "has_table_privilege(current_user,'public.amap_quota_buckets','INSERT') AS can_insert")
            if (identity is None or identity["role"] in {"noteai_app", "noteai_admin_runtime"}
                or not identity["can_read"] or (write and not identity["can_insert"])):
                raise RefreshError("AMAP_REFRESH_MAINTENANCE_ROLE_REQUIRED")
            yield tx
        except BaseException:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            raise
        else:
            try:
                connection.execute("COMMIT")
            except Exception:
                raise CommitUnknown() from None
        finally:
            # Closing a disconnected client must never mask COMMIT_UNKNOWN or
            # turn an acknowledged commit into a false "unchanged" response.
            try:
                connection.close()
            except Exception:
                pass


def main(argv=None):
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, help="operator-attested JSON (no secrets)")
    parser.add_argument("--official-observation", required=True, help="retained official artifact; contents are never printed")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="SELECT-only default")
    mode.add_argument("--apply", action="store_true", help="append only after production change is authorized")
    args = parser.parse_args(argv)
    try:
        evidence = prepare_evidence(args.evidence, args.official_observation,
                                    configured_key=os.environ.get("AMAP_WEB_KEY"),
                                    observed_key=os.environ.get("NOTEAI_AMAP_OBSERVED_KEY"))
        storage = MaintenancePostgresStorage(os.environ.get("NOTEAI_AMAP_REFRESH_DSN"))
        result = refresh_snapshot(storage, evidence, apply=args.apply)
        exit_code = 0
    except CommitUnknown:
        result = {"status": "commit_unknown", "code": "AMAP_REFRESH_COMMIT_UNKNOWN", "changed": None,
                  "automatic_retry": False, "manual_readback_required": True}
        exit_code = 2
    except RefreshError as exc:
        result = {"status": "rejected", "code": exc.code, "changed": False, "automatic_retry": False}
        exit_code = 1
    except Exception:
        # Unrecognized failures cannot expose credentials, exception text or
        # assert that an uncertain transaction left the database unchanged.
        result = {"status": "unknown", "code": "AMAP_REFRESH_STATE_UNKNOWN", "changed": None,
                  "automatic_retry": False, "manual_readback_required": True}
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
