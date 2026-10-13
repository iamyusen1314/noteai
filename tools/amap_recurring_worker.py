#!/usr/bin/env python3
"""Finite-rights continuing worker core; no installation, login or model calls.

One public, unauthenticated HTTPS document read per tick. Approval uses a stable
quota/validity semantic digest; the separately recorded fetch digest is audit
provenance. A page/parser/network failure has no cached-success fallback.
"""
from datetime import timedelta
import hashlib
from html.parser import HTMLParser
import json
import re
import ssl
import time
import urllib.error
import urllib.request

import derive_amap_monthly_budget as producer
quota = producer.quota


class RulesUnknown(RuntimeError):
    pass


class _PublicText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.text, self.rows, self.tables = [], [], []
        self.table, self.row, self.cell = None, None, None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if not self.hidden:
            if tag == "table":
                self.table = []
            elif tag == "tr":
                self.row = []
            elif tag in {"td", "th"} and self.row is not None:
                self.cell = []

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden-1)
        if not self.hidden:
            if tag in {"td", "th"} and self.cell is not None:
                self.row.append("".join(self.cell))
                self.cell = None
            elif tag == "tr" and self.row is not None:
                self.rows.append(self.row)
                if self.table is not None:
                    self.table.append(self.row)
                self.row = None
            elif tag == "table" and self.table is not None:
                self.tables.append(self.table)
                self.table = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.cell is not None:
                self.cell.append(data)


def rules_projection(raw):
    """Reject incomplete/ambiguous public HTML, never infer account eligibility."""
    page = _PublicText()
    page.feed(raw.decode("utf-8", errors="strict"))
    text = re.sub(r"\s+", "", "".join(page.text))
    matches = []
    for table in page.tables:
        for index, row in enumerate(table):
            if row and "基础搜索服务" in row[0]:
                numbers = []
                for cell in row[1:]:
                    value = re.sub(r"\s+|,", "", cell)
                    if re.fullmatch(r"[0-9]+", value):
                        numbers.append(int(value))
                if (len(numbers) == 3 and numbers[0] == 5000 and numbers[2] == 500000
                    and all(term in row[0] for term in
                        ("配额共享平台", "API", "JS", "Android", "iOS", "微信小程序"))):
                    headers = [header for header in table[:index] if any(
                        term in "".join(header) for term in ("月配额", "企业认证开发者"))]
                    if (len(headers) != 2 or len(headers[0]) != 2 or len(headers[1]) != 3
                        or "企业认证开发者" not in headers[1][1]):
                        raise RulesUnknown("PUBLIC_RULES_HEADER_UNCONFIRMED")
                    matches.append((numbers[1], headers, row))
    # The official upgrade table and its free-one-year/invitation clauses are
    # the approved contract being observed; no policy values are guessed when
    # structure changes. Navigation, advertisements and dates are excluded.
    plan = re.search(r"高德开放平台乘风计划(.{0,400}?)购买流程", text)
    if (len(matches) != 1 or "月配额" not in text or plan is None
        or "免费提供为期一年" not in plan[1] or "定向邀请" not in plan[1]
        or "符合平台认定标准" not in plan[1]):
        raise RulesUnknown("PUBLIC_RULES_UNCONFIRMED")
    normalize = lambda value: re.sub(r"\s+", "", value)
    # Bind the complete relevant contract, not only positive keywords. Newly
    # added qualifications/denials in its headers, service or plan must change
    # the approved digest. Dynamic navigation remains outside this projection.
    return {"schema": "noteai.amap_public_monthly_rules.v1", "source_url": quota.PUBLIC_RULES_URL,
        "service_group": quota.SERVICE_GROUP, "monthly_quota": matches[0][0],
        "free_entitlement_term": "one_year", "plan": "enterprise_chengfeng_invitation",
        "sharing_scope": ["API", "JS", "Android", "iOS", "WeChat_mini_program"],
        "rules_text": {"headers": [[normalize(cell) for cell in header] for header in matches[0][1]],
            "service_cells": [normalize(cell).replace(",", "") if re.fullmatch(
                r"[0-9,]+", normalize(cell)) else normalize(cell) for cell in matches[0][2]],
            "chengfeng_clause": plan[1]}}


def projection_bytes(projection):
    return (json.dumps(projection, sort_keys=True, separators=(",", ":"))+"\n").encode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        raise RulesUnknown("PUBLIC_RULES_REDIRECT_HOLD")


class PublicRulesObserver:
    """Fixed official URL, system TLS, no auth/cookies, no retry or 304 cache."""
    def __init__(self):
        self.http_reads = 0
        self.fetch_sha256 = None

    def observe(self):
        if self.http_reads:
            raise RulesUnknown("PUBLIC_RULES_READ_LIMIT")
        self.http_reads = 1
        opener = urllib.request.build_opener(_NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request = urllib.request.Request(quota.PUBLIC_RULES_URL,
            headers={"User-Agent": "NoteAI-allowance-policy-monitor/1", "Cache-Control": "no-cache"})
        try:
            deadline = time.monotonic()+15
            with opener.open(request, timeout=10) as response:
                if response.status != 200 or response.geturl() != quota.PUBLIC_RULES_URL:
                    raise RulesUnknown("PUBLIC_RULES_HTTP_HOLD")
                parts, total = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise RulesUnknown("PUBLIC_RULES_DEADLINE_HOLD")
                    chunk = response.read(16384)
                    if not chunk:
                        break
                    parts.append(chunk)
                    total += len(chunk)
                    if total > 2*1024*1024:
                        raise RulesUnknown("PUBLIC_RULES_SIZE_HOLD")
                raw = b"".join(parts)
                if not 0 < len(raw) <= 2*1024*1024:
                    raise RulesUnknown("PUBLIC_RULES_SIZE_HOLD")
            self.fetch_sha256 = hashlib.sha256(raw).hexdigest()
            return projection_bytes(rules_projection(raw))
        except RulesUnknown:
            raise
        except Exception:
            raise RulesUnknown("PUBLIC_RULES_FETCH_HOLD") from None


def report(state, *, period=None, **extra):
    return {"schema": "noteai.amap_recurring_worker_status.v1", "state": state, "period": period,
        "provider_calls": 0, "automatic_apply_retry": False, **extra}


def _reconcile(storage, marker):
    with storage.transaction(write=False) as tx:
        row = tx.fetchone("SELECT * FROM amap_quota_buckets WHERE account_scope=? AND service_group=? AND period=?",
            (quota.ACCOUNT_SCOPE, quota.SERVICE_GROUP, marker["period"]))
        now = quota._database_now(tx)
        match = bool(row and quota._recurring_budget(row) is not None
            and producer._binding(row["source"], row["period"]) == marker["budget_binding_sha256"])
    return {"period": marker["period"], "present": row is not None, "binding_matches": match,
        "observed_at": quota._iso(now), "admitted_count": row["admitted_count"] if row else None}


def run_once(storage, *, entitlement_loader, observer, state_store, current_binding_verified):
    """One tick: immutable rights -> fresh public rules -> RO plan -> one apply.

    Missing rights, policy/connection/pre-plan failures consume no apply attempt;
    a later scheduled check may recover. Once claimed, failures are read-only.
    Even a known insert rejection is not automatically retried because the old
    storage adapter does not provide a separately attested rollback receipt.
    """
    period = None
    prepared = None
    now = None
    apply_started = False
    try:
        with storage.transaction(write=False) as tx:
            now = quota._database_now(tx)
        period, _, _ = producer._calendar(now)
        if current_binding_verified is not True or not entitlement_loader.present():
            raise RulesUnknown("FINITE_RIGHTS_OR_SHARED_METERING_UNCONFIRMED")
        current_rules = observer.observe()
        rules_path = state_store.rules_artifact(current_rules)
        prepared = entitlement_loader.prepare(rules_path)
        with storage.transaction(write=False) as tx:
            now = quota._database_now(tx)
        period, _, _ = producer._calendar(now)
        if quota._clock(prepared.metadata["verified_at"]) > now:
            raise RulesUnknown("FINITE_RIGHTS_VERIFICATION_FUTURE")
        verified_policy = _policy(prepared, now, observer, verified=True)
        prepared.runtime["NOTEAI_AMAP_RECURRING_RULES_STATUS_FILE"] = state_store.private_policy(verified_policy)
        state_store.policy(_policy(prepared, now, observer, verified=False, code="MAINTENANCE_CHECK_PENDING"))
        for marker in state_store.markers():
            outcome = state_store.outcome(marker["period"])
            if outcome is None or outcome.get("status") == "commit_unknown":
                readback = _reconcile(storage, marker)
                if not readback["binding_matches"]:
                    return report("HOLD_UNKNOWN_READONLY", period=period, changed=None,
                        public_http_reads=observer.http_reads, apply_invocations=0, readback=readback)
                state_store.confirm(marker, readback)  # new receipt; original unknown is retained
        plan = producer.produce_month_budget(storage, prepared)
        if plan["period"] != period:
            raise RulesUnknown("DATABASE_MONTH_CHANGED_DURING_CHECK")
        if plan["status"] == "same_month_noop":
            state_store.policy(verified_policy)
            return report("CURRENT_MONTH_NOOP", period=period, changed=False,
                public_http_reads=observer.http_reads, apply_invocations=0, remaining=plan["remaining"],
                blocked_endpoints=plan["blocked_endpoints"])
        if state_store.marker(period) is not None:
            return report("HOLD_RECORDED_ATTEMPT", period=period, changed=None,
                public_http_reads=observer.http_reads, apply_invocations=0,
                readback=_reconcile(storage, state_store.marker(period)))
        if any(plan["blocked_endpoints"].values()):
            raise RulesUnknown("EXISTING_PROVIDER_DENIAL")
        marker = {"schema": "noteai.amap_recurring_attempt.v1", "period": period,
            "budget_binding_sha256": plan["budget_binding_sha256"], "started_at": quota._iso(now),
            "entitlement_sha256": prepared.metadata["entitlement_sha256"], "maximum_apply_invocations": 1}
        state_store.begin(marker)
        apply_started = True
        try:
            outcome = producer.produce_month_budget(storage, prepared, apply=True,
                expected_binding=plan["budget_binding_sha256"])
        except producer.CommitUnknown:
            outcome = {"status": "commit_unknown", "changed": None, "automatic_retry": False}
        except producer.RefreshError as exc:
            outcome = {"status": "rejected", "code": exc.code, "changed": False, "automatic_retry": False}
        except BaseException:
            outcome = {"status": "commit_unknown", "changed": None, "automatic_retry": False}
        state_store.finish(period, outcome)
        if outcome["status"] in {"applied", "same_month_noop"}:
            state_store.policy(verified_policy)
        elif outcome["status"] == "commit_unknown":
            readback = _reconcile(storage, marker)
            if readback["binding_matches"]:
                state_store.confirm(marker, readback)
                state_store.policy(verified_policy)
                return report("APPLY_CONFIRMED_READONLY", period=period, changed=True,
                    public_http_reads=observer.http_reads, apply_invocations=1, original_result=outcome,
                    readback=readback)
        return report("APPLY_ACKNOWLEDGED" if outcome["status"] in {"applied", "same_month_noop"}
            else "HOLD_APPLY_RESULT", period=period, changed=outcome["changed"],
            public_http_reads=observer.http_reads, apply_invocations=1, result=outcome)
    except (RulesUnknown, producer.RefreshError) as exc:
        code = str(exc) if isinstance(exc, RulesUnknown) else exc.code
        try:
            state_store.policy(_policy(prepared, now, observer, verified=False, code=code))
        except BaseException:
            pass
        return report("HOLD", period=period, code=code, changed=None if apply_started else False,
            public_http_reads=observer.http_reads, apply_invocations=int(apply_started))
    except BaseException:
        try:
            state_store.policy(_policy(prepared, now, observer, verified=False, code="WORKER_STATE_UNKNOWN"))
        except BaseException:
            pass
        return report("HOLD_STATE_UNKNOWN", period=period, changed=None,
            public_http_reads=observer.http_reads, apply_invocations=None)


def _policy(prepared, now, observer, *, verified, code=None):
    value = prepared.metadata if prepared is not None else {}
    # Shared API-readable projection deliberately excludes source.k and all
    # Key material/digests, raw source JSON, DSN and exception text.
    return {"schema": "noteai.amap_recurring_rules_status.v1", "state": "VERIFIED" if verified else "HOLD",
        "entitlement_sha256": value.get("entitlement_sha256"),
        "official_entitlement_artifact_sha256": value.get("official_entitlement_sha256"),
        "rules_sha256": value.get("official_rules_sha256"), "valid_from": value.get("valid_from"),
        "valid_until": value.get("valid_until"), "source_url": quota.PUBLIC_RULES_URL,
        "observed_at": quota._iso(now) if now is not None else None,
        "official_fetch_artifact_sha256": observer.fetch_sha256, "public_http_reads": observer.http_reads,
        "code": code}
