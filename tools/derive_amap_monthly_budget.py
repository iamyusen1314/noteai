#!/usr/bin/env python3
"""Prototype finite recurring Amap allowance; no provider calls or installation.

A retained, operator-verified official entitlement and current official rules
must prove the allowance and exact validity dates. Key validity is insufficient.
Only the existing maintenance channel may append local budgets. The existing
console importer is unchanged. This tool neither fetches rights/usage nor claims
an automatic rules observer or monthly scheduler has been installed.

Secret values arrive only via env. The approved Key must be supplied through the
existing secret channel during preparation, never in entitlement JSON or output.
The derived source has an internal Key binding digest; public status sanitizes it.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import amap_quota as quota
from refresh_amap_quota_snapshot import (CommitUnknown,
    MaintenancePostgresStorage, RefreshError, _baseline, _calendar)

FIELDS = {"version", "account_scope", "service_group", "time_zone", "monthly_quota",
          "valid_from", "valid_until", "verified_at", "official_entitlement_sha256",
          "official_rules_sha256", "attestations"}
ATTESTATIONS = {"console_account_matches", "key_alias", "key_scope", "enterprise_certified",
    "license_purchased", "owner_risk_accepted", "exclusive_noteai_use", "all_shared_search_metered",
    "metering_continuous_since"}


@dataclass(frozen=True)
class PreparedEntitlement:
    metadata: dict = field(repr=False)
    runtime: dict = field(repr=False)


def _file_digest(path, limit):
    p = Path(path)
    if not p.is_file() or not 0 < p.stat().st_size <= limit:
        raise RefreshError("AMAP_RECURRING_OFFICIAL_ARTIFACT_REQUIRED")
    with p.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_entitlement(path, official_entitlement, current_official_rules, *,
                        configured_key, approved_key, observed_key):
    """Validate an attestation, not establish supplier truth from a test file."""
    try:
        p = Path(path)
        if not 0 < p.stat().st_size <= 16384:
            raise ValueError()
        value = json.loads(p.read_text())
        attested = value.get("attestations") if isinstance(value, dict) else None
        if (not isinstance(value, dict) or set(value) != FIELDS or value["version"] != 1
            or type(value["version"]) is not int or value["account_scope"] != quota.ACCOUNT_SCOPE
            or value["service_group"] != quota.SERVICE_GROUP or value["time_zone"] != "Asia/Shanghai"
            or type(value["monthly_quota"]) is not int or value["monthly_quota"] != 50000
            or not isinstance(attested, dict) or set(attested) != ATTESTATIONS
            or attested["key_alias"] != "noteai-rot-0902" or attested["key_scope"] != "web_service"
            or any(attested[name] is not expected for name, expected in (
                ("console_account_matches", True), ("enterprise_certified", True),
                ("license_purchased", False), ("owner_risk_accepted", True),
                ("exclusive_noteai_use", True), ("all_shared_search_metered", True)))):
            raise ValueError()
        if not all(isinstance(key, str) and key.strip() for key in (configured_key, approved_key, observed_key)):
            raise RefreshError("AMAP_RECURRING_KEY_CONFIRMATION_REQUIRED")
        if not (hmac.compare_digest(configured_key.encode(), approved_key.encode())
                and hmac.compare_digest(configured_key.encode(), observed_key.encode())):
            raise RefreshError("AMAP_RECURRING_KEY_MISMATCH")
        for key, artifact in (("official_entitlement_sha256", official_entitlement),
                              ("official_rules_sha256", current_official_rules)):
            digest = value[key]
            if not isinstance(digest, str) or len(digest) != 64 or not hmac.compare_digest(
                    digest, _file_digest(artifact, 20 * 1024 * 1024)):
                raise RefreshError("AMAP_RECURRING_OFFICIAL_ARTIFACT_MISMATCH")
        try:
            start, expiry, verified, metered = (quota._clock(clock) for clock in
                (value["valid_from"], value["valid_until"], value["verified_at"], attested["metering_continuous_since"]))
        except Exception:
            raise RefreshError("AMAP_RECURRING_RIGHTS_DATES_REQUIRED") from None
        if not timedelta(0) < expiry-start <= timedelta(days=366) or not start <= verified < expiry:
            raise RefreshError("AMAP_RECURRING_RIGHTS_DATES_REQUIRED")
        value["valid_from"], value["valid_until"], value["verified_at"] = map(quota._iso, (start, expiry, verified))
        attested["metering_continuous_since"] = quota._iso(metered)
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        value["entitlement_sha256"] = digest
        value["key_binding_sha256"] = hashlib.sha256(configured_key.encode()).hexdigest()
        runtime = {"AMAP_WEB_KEY": configured_key,
            "NOTEAI_AMAP_RECURRING_ENTITLEMENT_SHA256": os.environ.get("NOTEAI_AMAP_RECURRING_ENTITLEMENT_SHA256"),
            "NOTEAI_AMAP_RECURRING_RULES_SHA256": os.environ.get("NOTEAI_AMAP_RECURRING_RULES_SHA256"),
            "NOTEAI_AMAP_RECURRING_RULES_STATUS_FILE": os.environ.get("NOTEAI_AMAP_RECURRING_RULES_STATUS_FILE")}
        return PreparedEntitlement(value, runtime)
    except RefreshError:
        raise
    except Exception:
        raise RefreshError("AMAP_RECURRING_EVIDENCE_INVALID") from None


def _risk_reserve(tx, period, start):
    # Each old reserved/unknown physical request can hit at most once later.
    # Retain that upper bound in subsequent months, never release old admissions.
    rows = tx.fetchall("SELECT status,completed_at FROM amap_quota_attempts WHERE account_scope=? "
        "AND service_group=? AND period<?", (quota.ACCOUNT_SCOPE, quota.SERVICE_GROUP, period))
    return sum(row["status"] in {"reserved", "unknown"} or
               (row["completed_at"] is not None and quota._clock(row["completed_at"]) >= start) for row in rows)


def _binding(source, period):
    return hashlib.sha256(json.dumps({"source": source, "period": period},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def produce_month_budget(storage, entitlement, *, apply=False, expected_binding=None):
    """One locked append; absence/expiry/conflict fails shut, no automatic retry."""
    if not isinstance(entitlement, PreparedEntitlement):
        raise RefreshError("AMAP_RECURRING_EVIDENCE_REQUIRED")
    value = entitlement.metadata
    try:
        with storage.transaction(write=apply) as tx:
            if apply:
                quota._account_lock(tx)
            previous = quota._bucket(tx, lock=apply)
            if previous is None:
                raise RefreshError("AMAP_RECURRING_ORIGINAL_BASELINE_REQUIRED")
            _, old_end, _, _ = quota._validate_bucket(previous)
            now = quota._database_now(tx)
            period, start, end = _calendar(now)
            if (quota._clock(value["valid_from"]) > start or quota._clock(value["valid_until"]) <= now+timedelta(seconds=10)
                or quota._clock(value["verified_at"]) > now):
                raise RefreshError("AMAP_RECURRING_MONTH_NOT_COVERED")
            if quota._clock(value["attestations"]["metering_continuous_since"]) > start:
                raise RefreshError("AMAP_RECURRING_SHARED_METERING_GAP")
            if now + timedelta(seconds=10) >= end:
                raise RefreshError("AMAP_RECURRING_PERIOD_CLOSING")
            if previous["period"] > period or (previous["period"] < period and old_end > now):
                raise RefreshError("AMAP_RECURRING_PREVIOUS_PERIOD_NOT_EXPIRED")
            restrictions = quota._restrictions(tx, now)
            existing = quota._recurring_budget(previous)
            if (existing is not None and existing["e"] == value["entitlement_sha256"]
                and existing["k"] != value["key_binding_sha256"]):
                raise RefreshError("AMAP_QUOTA_RECURRING_BINDING_CHANGED")
            if previous["period"] == period:
                if existing is not None and (existing["e"] != value["entitlement_sha256"]
                    or existing["r"] != value["official_rules_sha256"]):
                    raise RefreshError("AMAP_RECURRING_CURRENT_BASELINE_CONFLICT")
                quota._recurring_check(previous, now, environment=entitlement.runtime)
                return {"status": "same_month_noop", "changed": False, "period": period,
                    "snapshot_sha256": previous["snapshot_sha256"], "admitted_count": previous["admitted_count"],
                    "remaining": previous["quota"]-previous["official_used"]-previous["admitted_count"],
                    "blocked_endpoints": restrictions, "provider_requests": 0,
                    "evidence_scope": "existing_local_budget" if existing else "existing_console_observation"}
            reserve = _risk_reserve(tx, period, start)
            if reserve >= value["monthly_quota"]:
                raise RefreshError("AMAP_RECURRING_UNCERTAIN_USAGE_EXHAUSTS_BUDGET")
            metadata = {"e": value["entitlement_sha256"], "a": value["official_entitlement_sha256"],
                "r": value["official_rules_sha256"], "k": value["key_binding_sha256"],
                "f": value["valid_from"], "u": value["valid_until"],
                "m": value["attestations"]["metering_continuous_since"], "v": value["monthly_quota"], "b": reserve}
            source = quota.RECURRING_SOURCE + json.dumps(metadata, sort_keys=True, separators=(",", ":"))
            binding = _binding(source, period)
            if expected_binding is not None and expected_binding != binding:
                raise RefreshError("AMAP_RECURRING_PLAN_CHANGED")
            row = {"account_scope": quota.ACCOUNT_SCOPE, "service_group": quota.SERVICE_GROUP,
                "period": period, "period_start": quota._iso(start), "period_end": quota._iso(end),
                "time_zone": "Asia/Shanghai", "quota": value["monthly_quota"],
                "official_used": reserve, "observed_at": quota._iso(now), "source": source,
                "owner_authorized_at": previous["owner_authorized_at"], "enterprise_certified": 1,
                "license_purchased": 0, "owner_risk_accepted": 1, "exclusive_noteai_use": 1,
                "admitted_count": 0, "billing_observation_json": None,
                "account_block_code": None, "account_block_until": None,
                "text_block_code": None, "text_block_until": None,
                "detail_block_code": None, "detail_block_until": None}
            row["snapshot_sha256"] = hashlib.sha256(json.dumps(row, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            quota._validate_bucket(row)
            quota._recurring_check(row, now, environment=entitlement.runtime)
            if apply:
                names = tuple(row)
                tx.execute("INSERT INTO amap_quota_buckets(" + ",".join(names) + ") VALUES(" +
                    ",".join("?" for _ in names) + ")", tuple(row[name] for name in names))
                if _baseline(quota._bucket(tx)) != _baseline(row):
                    raise RefreshError("AMAP_RECURRING_READBACK_MISMATCH")
            result = {"status": "applied" if apply else "plan_ready", "changed": apply, "period": period,
                "snapshot_sha256": row["snapshot_sha256"], "budget_binding_sha256": binding,
                "entitlement_sha256": value["entitlement_sha256"], "official_used": None,
                "unmetered_usage_upper_bound": reserve, "budget_derived_at": row["observed_at"],
                "remaining": row["quota"]-reserve, "blocked_endpoints": restrictions,
                "evidence_scope": "entitlement_derived_local_budget", "provider_requests": 0,
                "billing_current_period": "unknown"}
        return result
    except (RefreshError, CommitUnknown):
        raise
    except quota.AmapQuotaError as exc:
        raise RefreshError(exc.code) from None
    except Exception:
        raise RefreshError("AMAP_RECURRING_STATE_UNAVAILABLE") from None


def _claim_attempt(path, plan):
    # A scheduler must use a stable per-month state path. A pre-existing attempt
    # means read-only reconciliation, not another apply, even after a failure.
    p = Path(path)
    parent = p.parent.lstat()
    if (not p.parent.is_dir() or p.parent.is_symlink() or parent.st_uid != os.geteuid()
        or parent.st_mode & 0o077):
        raise RefreshError("AMAP_RECURRING_ATTEMPT_STATE_REQUIRED")
    try:
        descriptor = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise RefreshError("AMAP_RECURRING_READONLY_RECONCILIATION_REQUIRED") from None
    except Exception:
        raise RefreshError("AMAP_RECURRING_ATTEMPT_STATE_UNAVAILABLE") from None
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"period": plan["period"], "budget_binding_sha256": plan["budget_binding_sha256"],
            "state": "APPLY_ATTEMPT_CLAIMED", "automatic_retry": False}, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"status": "hold", "code": "AMAP_RECURRING_ARGUMENTS_INVALID"}))
        raise SystemExit(2)


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--entitlement", required=True)
    parser.add_argument("--official-entitlement", required=True)
    parser.add_argument("--current-official-rules", required=True)
    parser.add_argument("--attempt-state")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        prepared = prepare_entitlement(args.entitlement, args.official_entitlement, args.current_official_rules,
            configured_key=os.environ.get("AMAP_WEB_KEY"), approved_key=os.environ.get("NOTEAI_AMAP_RECURRING_APPROVED_KEY"),
            observed_key=os.environ.get("NOTEAI_AMAP_OBSERVED_KEY"))
        storage = MaintenancePostgresStorage(os.environ.get("NOTEAI_AMAP_REFRESH_DSN"))
        result = produce_month_budget(storage, prepared)
        if args.apply and result["status"] != "same_month_noop":
            if not args.attempt_state:
                raise RefreshError("AMAP_RECURRING_ATTEMPT_STATE_REQUIRED")
            _claim_attempt(args.attempt_state, result)
            result = produce_month_budget(storage, prepared, apply=True, expected_binding=result["budget_binding_sha256"])
        code = 0
    except CommitUnknown:
        result = {"status": "commit_unknown", "code": "AMAP_RECURRING_COMMIT_UNKNOWN", "changed": None,
            "automatic_retry": False, "readonly_reconciliation_required": True}
        code = 2
    except RefreshError as exc:
        result = {"status": "hold", "code": exc.code, "changed": False, "automatic_retry": False}
        code = 1
    except Exception:
        result = {"status": "unknown", "code": "AMAP_RECURRING_STATE_UNKNOWN", "changed": None,
            "automatic_retry": False, "readonly_reconciliation_required": True}
        code = 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
