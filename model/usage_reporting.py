"""Read-only usage projections; observations and price calculations are not bills.

All totals use the cohort of business records started inside the explicit UTC
window. Child tokens/cost are counted once, never added to their parent rollup.
This module imports no application, database, provider or environment settings.
"""
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone


AUXILIARY_OPERATIONS = frozenset({"extra_image", "video_analyze"})
LOCAL_STEPS = frozenset({"local_score"})
LOCAL_OUTCOMES = frozenset({"succeeded", "failed"})
MODEL_STEPS = frozenset({
    "semantic_features", "video_audio_understanding", "ocr_text_merge",
    "chat_quality_repair", "chat_response", "delivery_body_shaping",
    "delivery_quality_revision", "diagnosis_arbitration", "diagnosis_content",
    "diagnosis_body_distinctness", "diagnosis_fact_repair", "diagnosis_growth",
    "diagnosis_plan_body", "diagnosis_title_compression", "diagnosis_user",
    "diagnosis_visual", "generation_arbitration", "generation_arbitration_format_repair",
    "generation_body_compression", "generation_body_rhythm", "generation_challenger",
    "generation_content", "generation_growth", "generation_quality_repair",
    "generation_user", "generation_visual", "legacy_diagnosis", "title_compression",
})
TOKEN_INPUT_FIELDS = (
    "input_tokens", "unclassified_input_tokens", "cache_read_input_tokens",
    "cache_write_input_tokens", "audio_input_tokens", "audio_cache_read_input_tokens",
)


def reporting_window(*, period="rolling_days", days=30, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("usage reporting requires an aware clock")
    now = now.astimezone(timezone.utc)
    if period == "calendar_month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif period == "rolling_days":
        if type(days) is not int or not 1 <= days <= 366:
            raise ValueError("usage reporting days must be 1..366")
        start, end = now - timedelta(days=days), now
    else:
        raise ValueError("unsupported usage reporting period")
    return {"kind": period, "timezone": "UTC", "start": start.isoformat(),
            "end": end.isoformat(), "as_of": now.isoformat(),
            "basis": "usage_record_started_at"}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _json(value, expected):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, expected) else None


def _status(row, requests):
    if row.get("source") == "refunded":
        return "refunded"
    matches = requests.get(row["id"], [])
    if len(matches) != 1 or matches[0].get("operation") != row.get("operation"):
        return "status_unknown"
    value = matches[0].get("status")
    return value if value in {"completed", "failed", "running", "waiting_for_input"} else "status_unknown"


def _usage_complete(row):
    return (row.get("usage_status") == "complete"
            and all(_count(row.get(key)) is not None for key in (*TOKEN_INPUT_FIELDS, "output_tokens")))


def _model_complete(row):
    return (row.get("pricing_status") == "exact" and _usage_complete(row)
            and _number(row.get("known_cost_rmb")) is not None)


def project_usage(*, usage_rows, model_rows, physical_rows, request_rows, window):
    """Project already user-scoped rows. Missing observations remain unknown.

    public_trial_calls records reservations too: a row alone is not proof of an
    HTTP request, and a model usage row alone is not a physical HTTP count.
    """
    usages = {row["id"]: dict(row) for row in usage_rows}
    models, physical, requests = defaultdict(list), defaultdict(list), defaultdict(list)
    for rows, target, parent in ((model_rows, models, "usage_record_id"),
                                 (physical_rows, physical, "usage_record_id"),
                                 (request_rows, requests, "usage_id")):
        for row in rows:
            row = dict(row)
            if row.get(parent) in usages:
                target[row[parent]].append(row)
    business, auxiliary, statuses, by_operation = [], [], Counter(), {}
    local_counts, trace_counts = defaultdict(Counter), Counter()
    local_parents, local_seen, metadata_invalid, traces_missing = set(), set(), 0, 0
    physical_counts = Counter()
    model_count = incomplete_models = incomplete_usage = pricing_gaps = unbound_models = unknown_parents = 0
    known_cost = manual_cost = estimates = 0.0
    tokens_in = tokens_out = 0
    cache_read = cache_write = 0
    for usage_id, row in usages.items():
        op = row.get("operation", "unknown")
        is_aux = op in AUXILIARY_OPERATIONS
        (auxiliary if is_aux else business).append(row)
        status = _status(row, requests)
        if not is_aux:
            statuses[status] += 1
        details, calls = models[usage_id], physical[usage_id]
        detail_ids = {item["id"] for item in details}
        linked_ids = {item.get("model_usage_record_id") for item in calls}
        unbound_models += len(detail_ids - linked_ids)
        complete = bool(details) and all(_model_complete(item) for item in details)
        # Missing physical binding or an unsettled/unknown reservation prevents
        # a strict cost-completeness claim even if one earlier call was priced.
        physical_complete = bool(calls) and all(
            item.get("state") == "responded" and item.get("http_status") == 200
            and item.get("model_usage_record_id") in detail_ids for item in calls)
        physical_complete = physical_complete and not (detail_ids - linked_ids)
        included = row.get("cost_mode") == "included_in_parent" and is_aux and not details and not calls
        cost_complete = complete and physical_complete
        if not included and not cost_complete:
            unknown_parents += 1
        op_value = by_operation.setdefault(op, {
            "kind": "auxiliary_event" if is_aux else "business_operation",
            "count_basis": "usage_records", "status_counts": {},
            "cost_basis": "legacy_mixed_estimate_and_usage_calculation",
            "known_calculated_rmb": 0.0, "manual_cost_rmb": 0.0,
            "estimated_only_rmb": 0.0, "cost_complete": True,
            "included_in_parent_records": 0, "physical_records": 0,
            "model_usage_records": 0,
        })
        op_value["status_counts"][status] = op_value["status_counts"].get(status, 0) + 1
        op_value["cost_complete"] = op_value["cost_complete"] and (cost_complete or included)
        op_value["included_in_parent_records"] += int(included)
        op_value["physical_records"] += len(calls)
        op_value["model_usage_records"] += len(details)
        for item in details:
            model_count += 1
            incomplete_models += int(not _model_complete(item))
            incomplete_usage += int(not _usage_complete(item))
            pricing_gaps += int(item.get("pricing_status") != "exact" or _number(item.get("known_cost_rmb")) is None)
            value = _number(item.get("known_cost_rmb"))
            if value is not None:
                key = "manual_cost_rmb" if item.get("pricing_status") == "manual" else "known_calculated_rmb"
                op_value[key] += value
                if key == "manual_cost_rmb": manual_cost += value
                else: known_cost += value
            tokens_in += sum(_count(item.get(key)) or 0 for key in TOKEN_INPUT_FIELDS)
            tokens_out += _count(item.get("output_tokens")) or 0
            cache_read += (_count(item.get("cache_read_input_tokens")) or 0) + (_count(item.get("audio_cache_read_input_tokens")) or 0)
            cache_write += _count(item.get("cache_write_input_tokens")) or 0
        # Legacy parents retain an explicit fallback estimate when returned
        # usage cannot be priced at all. It is separate from known child cost.
        if not included and not complete and not any((_number(item.get("known_cost_rmb")) or 0) > 0 for item in details):
            value = _number(row.get("estimated_cost_rmb"))
            if value is not None:
                estimates += value
                op_value["estimated_only_rmb"] += value
        for call in calls:
            physical_counts["recorded"] += 1
            state, http_status = call.get("state"), call.get("http_status")
            if state == "unknown": physical_counts["unknown"] += 1
            elif state == "dispatched": physical_counts["in_flight"] += 1
            elif state == "responded": physical_counts["responded"] += 1
            else: physical_counts["state_unrecognized"] += 1
            if type(http_status) is int and 100 <= http_status <= 599:
                physical_counts["http_responses_observed"] += 1
            else:
                physical_counts["not_dispatched_or_unconfirmed"] += 1
            if call.get("model_usage_record_id") not in detail_ids:
                physical_counts["usage_missing"] += 1
            trace = _json(call.get("provenance_json"), dict)
            step = trace.get("step") if trace else None
            if isinstance(step, str) and step in MODEL_STEPS: trace_counts[step] += 1
            elif step: trace_counts["other_recorded_step"] += 1
            else: traces_missing += 1
        events = _json(row.get("fact_observations_json", "[]"), list)
        if events is None:
            metadata_invalid += 1
            continue
        for event in events:
            if not isinstance(event, dict) or event.get("kind") != "local_step":
                continue
            if (event.get("schema") != "noteai.local_step.v1"
                    or not isinstance(event.get("step"), str) or event["step"] not in LOCAL_STEPS
                    or not isinstance(event.get("outcome"), str) or event["outcome"] not in LOCAL_OUTCOMES
                    or not isinstance(event.get("observation_id"), str) or not event["observation_id"]):
                metadata_invalid += 1
                continue
            identity = (usage_id, event["observation_id"])
            if identity in local_seen:
                continue
            local_seen.add(identity)
            local_parents.add(usage_id)
            local_counts[event["step"]][event["outcome"]] += 1
    for op_value in by_operation.values():
        for key in ("known_calculated_rmb", "manual_cost_rmb", "estimated_only_rmb"):
            op_value[key] = round(op_value[key], 9)
    return {"window": dict(window), "operation_accounting": by_operation, "accounting": {
        "business": {"recorded": len(business), **{key: statuses[key] for key in (
            "completed", "failed", "refunded", "running", "waiting_for_input", "status_unknown")}},
        "auxiliary": {"recorded": len(auxiliary), "count_basis": "recorded_media_events_not_provider_calls",
                      "included_in_parent": sum(row.get("cost_mode") == "included_in_parent" for row in auxiliary),
                      "parent_link_status": "not_recorded_in_legacy_schema"},
        "models": {"usage_records": model_count, "pricing_or_usage_incomplete": incomplete_models,
                   "usage_incomplete": incomplete_usage, "pricing_gaps": pricing_gaps,
                   "without_physical_binding": unbound_models, "tokens_in": tokens_in, "tokens_out": tokens_out,
                   "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
                   "token_coverage": "not_recorded" if not model_count else "partial" if incomplete_usage else "recorded",
                   "count_basis": "model_usage_records_not_http_requests"},
        "physical": {**{key: physical_counts[key] for key in ("recorded", "responded", "in_flight",
            "unknown", "state_unrecognized", "http_responses_observed", "usage_missing", "not_dispatched_or_unconfirmed")},
            "count_basis": "public_trial_call_reservations", "actual_http_requests": None,
            "historical_coverage": "recorded_only"},
        "internal_model_steps": {"by_step": dict(sorted(trace_counts.items())),
                                 "without_step_metadata": traces_missing, "count_basis": "physical_reservation_trace"},
        "local_steps": {"status": "partially_recorded" if local_parents else "not_recorded",
            "by_step": {key: {"succeeded": value["succeeded"], "failed": value["failed"]}
                        for key, value in sorted(local_counts.items())},
            "parents_with_observations": len(local_parents), "metadata_invalid_records": metadata_invalid,
            "coverage": "observed_only_no_historical_backfill", "provider_http_requests": 0},
        "cost": {"known_calculated_rmb": round(known_cost, 9), "manual_cost_rmb": round(manual_cost, 9),
            "estimated_only_rmb": round(estimates, 9), "unknown_records": unknown_parents,
            "complete": bool(business) and not unknown_parents,
            "scope": "model_usage_only", "basis": "provider_usage_times_recorded_price",
            "supplier_bill_paid_rmb": None, "platform_total_rmb": None,
            "external_data_cost_status": "not_reconciled", "parent_child_sum": "model_children_once"},
    }}


def read_reporting_rows(tx, window, *, user_id=None):
    """Select safe accounting columns only, inside the caller's read transaction.

    user_id=None is for an already authenticated Admin caller. All user joins
    bind both parent identity and owner; no response/prompt/balance is read.
    """
    where = "u.recorded_at>=? AND u.recorded_at<?"
    params = (window["start"], window["as_of"])
    if user_id is not None:
        where += " AND u.user_id=?"
        params += (user_id,)
    usage = tx.fetchall("SELECT u.id,u.operation,u.source,u.cost_mode,u.estimated_cost_rmb,"
        "u.fact_observations_json FROM usage_records u WHERE " + where, params)
    models = tx.fetchall("SELECT m.id,m.usage_record_id,m.pricing_status,m.usage_status,m.known_cost_rmb,"
        + ",".join("m." + key for key in (*TOKEN_INPUT_FIELDS, "output_tokens"))
        + " FROM model_usage_records m JOIN usage_records u ON u.id=m.usage_record_id WHERE " + where, params)
    physical = tx.fetchall("SELECT c.usage_record_id,c.model_usage_record_id,c.state,c.http_status,c.provenance_json "
        "FROM public_trial_calls c JOIN usage_records u ON u.id=c.usage_record_id AND u.user_id=c.user_id WHERE " + where, params)
    requests = tx.fetchall("SELECT i.usage_id,i.operation,i.status FROM idempotency_requests i "
        "JOIN usage_records u ON u.id=i.usage_id AND u.user_id=i.user_id WHERE " + where, params)
    return {"usage_rows": usage, "model_rows": models, "physical_rows": physical, "request_rows": requests}


def subscription_period(row):
    if not row:
        return {"kind": "not_recorded", "start": None, "end": None, "timezone": "UTC"}
    row = dict(row)
    end = row.get("expires_at")
    if row.get("tier") == "free":
        try:
            start = datetime.fromisoformat(str(row.get("period_start"))).astimezone(timezone.utc)
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        except (ValueError, TypeError):
            end = None
    return {"kind": "free_calendar_month" if row.get("tier") == "free" else "stored_subscription_period",
            "start": row.get("period_start"), "end": end, "timezone": "UTC",
            "account_expires_at": row.get("expires_at"),
            "basis": "stored_subscription_no_refresh"}
