"""Compose existing Item33 callbacks from independently collected real facts.

No connection, provider call, service action or artifact write. Missing facts are
errors, never guessed zeros. This module does not itself make a terminal release.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

try:
    from . import execute_item33_trends_promotion as controller
    from . import item33_trends_runtime_capture as capture
    from . import item33_trends_dml_capture as dml
    from . import item33_trends_http_readback as http_reader
    from . import execute_item32_readonly_trends_successor as accepted
except ImportError:
    import execute_item33_trends_promotion as controller
    import item33_trends_runtime_capture as capture
    import item33_trends_dml_capture as dml
    import item33_trends_http_readback as http_reader
    import execute_item32_readonly_trends_successor as accepted


class Item33AssemblyError(RuntimeError):
    """Fixed projection/contract error; no raw database or provider contents."""


def require(condition, code):
    if not condition:
        raise Item33AssemblyError(code)


def encoded(value, *, ensure_ascii=False):
    return json.dumps(value, ensure_ascii=ensure_ascii, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def checked_fact(value, schema, *, ensure_ascii=False):
    require(isinstance(value, dict) and value.get("schema") == schema
            and value.get("secret_values_recorded") is False, "fact_shape")
    body = {key: item for key, item in value.items() if key != "canonical_sha256"}
    require(value.get("canonical_sha256") == hashlib.sha256(encoded(body, ensure_ascii=ensure_ascii)).hexdigest(),
            "fact_digest")


def timestamp(value):
    try:
        require(isinstance(value, str), "fact_clock")
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Original frozen acquisition code stores naive UTC in TEXT columns;
        # runtime role/image/session binding establishes that clock convention.
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise Item33AssemblyError("fact_clock") from None


def _readonly(database):
    require(database.get("database_role") == "noteai_xhs_trends"
            and database.get("server_enforced_read_only") is True
            and database.get("transaction_rolled_back") is True
            and database.get("xid_assigned") is False
            and type(database.get("provider_calls")) is int and database["provider_calls"] == 0
            and type(database.get("production_database_writes")) is int
            and database["production_database_writes"] == 0, "database_readonly")


def compose_preflight(host: dict, database: dict) -> dict:
    checked_fact(host, "noteai.item33.host_facts.v1", ensure_ascii=True)
    checked_fact(database, "noteai.item33.database_preflight.v1", ensure_ascii=True)
    _readonly(database)
    require(host["phase"] == "preflight", "host_phase")
    ledger = database["ledger"]
    result = {"observed_at": min(timestamp(host["observed_at"]), timestamp(database["observed_at"])).isoformat(),
        "database_role": database["database_role"], "role_exact": database["role_exact"],
        "acl_exact": database["acl_exact"],
        **{key: host[key] for key in ("unit_sha256", "unit_active", "unit_sub", "unit_enabled",
            "collection_suspended", "formal_container_count")},
        **{key: ledger[key] for key in ("active_run_count", "same_bucket_run_count", "outcome_unknown_count",
            "unlinked_attempt_count", "utc_provider_budget_used_before")},
        "utc_provider_budget_remaining_before": database["utc_provider_budget_remaining_before"],
        "provider_calls": database["provider_calls"], "production_database_writes": database["production_database_writes"]}
    result["canonical_sha256"] = digest({"host": host["canonical_sha256"], "database": database["canonical_sha256"],
                                          "projection": result})
    return result


def checked_database_cycle(database):
    checked_fact(database, "noteai.item33.database_cycle_readback.v1")
    _readonly(database)
    ledger = database["ledger"]
    require(ledger == {"active_run_count": 0, "same_bucket_run_count": 1, "active_attempt_count": 0,
        "outcome_unknown_count": 0, "orphan_attempt_count": 0, "unlinked_attempt_count": 0, "idle_service_count": 1}
        and all(type(value) is int for value in ledger.values()), "cycle_ledger")
    started, finished, observed = (timestamp(database[key]) for key in ("started_at", "completed_at", "observed_at"))
    health, freshness = database["health_rows"], database["freshness_rows"]
    require(len(health) == len(freshness) == 6 and {row["domain"] for row in health} == accepted.DOMAINS
            and {row["domain"] for row in freshness} == accepted.DOMAINS, "cycle_domain_health")
    for row in health:
        require(row["status"] == "ok" and type(row["risk_login_detected"]) is int and row["risk_login_detected"] == 0
                and type(row["evidence_count"]) is int and row["evidence_count"] >= 12
                and started <= timestamp(row["checked_at"]) <= finished, "cycle_domain_health")
    for row in freshness:
        require(row["status"] == "fresh" and type(row["evidence_count"]) is int and row["evidence_count"] >= 12
                and row["evidence_date"] == database["bucket_key"]
                and started <= timestamp(row["acquired_at"]) <= finished
                and finished <= observed <= timestamp(row["fresh_until"]), "cycle_freshness")
    snapshot = database["snapshot"]
    raw = encoded(snapshot["payload"])
    require(snapshot["sha256"] == hashlib.sha256(raw).hexdigest() and snapshot["size"] == len(raw), "snapshot_binding")
    try:
        real, search, recommend, count = accepted._snapshot_quality(raw,
            execution_started_at=database["started_at"], execution_finished_at=database["completed_at"])
    except accepted.Item32Error:
        raise Item33AssemblyError("snapshot_quality") from None
    require(database["quality"] == {"domain_real_keyword_counts": real, "search_result_domains": search,
            "search_recommend_domains": recommend, "keyword_count": count}, "snapshot_quality")
    return count


def compose_cycle(database: dict, http: dict, seal: dict, journal: bytes) -> dict:
    count = checked_database_cycle(database)
    require(http.get("state") == "HTTP_PROOF_VERIFIED" and http.get("physical_http_verified") is True, "http_unproven")
    try:
        require(http_reader.verify_worker_receipt(http["worker_receipt"],
            {**database, "physical_http": http["physical_http"]}) is True, "http_unproven")
        require(http["worker_receipt_sha256"] == http["physical_http"]["worker_receipt_sha256"], "http_binding")
        aggregate = capture.verify_capture_artifacts(seal, journal)
    except (TypeError, ValueError):
        raise Item33AssemblyError("http_or_capture_unproven") from None
    require(seal["run_identity_sha256"] == database["run_identity_sha256"]
            and seal["bucket_key"] == database["bucket_key"]
            and not dml.cycle_contract_errors(aggregate, request_count=34, keyword_count=count), "capture_cycle_binding")
    result = {"run_identity_sha256": database["run_identity_sha256"],
        "activation_identity_sha256": seal["activation_identity_sha256"], "bucket_key": database["bucket_key"],
        **{key: database[key] for key in ("started_at", "completed_at", "lease_expires_at", "endpoint_counts", "attempts")},
        "cycle_count": database["ledger"]["same_bucket_run_count"], "same_bucket_completed_run_count": 1,
        "provider_request_count": database["provider_request_count"], "provider_request_succeeded": len(database["attempts"]),
        "provider_request_failed": sum(row["status"] == "failed" for row in database["attempts"]),
        "outcome_unknown_count": database["ledger"]["outcome_unknown_count"],
        "automatic_retry_count": http["physical_http"]["automatic_retry_count"],
        "active_admitted_count": database["ledger"]["active_attempt_count"], "challenge_detected": False,
        "published_keyword_count": count, "minimum_real_keyword_count_per_domain": min(database["quality"]["domain_real_keyword_counts"].values()),
        "search_result_domain_count": len(database["quality"]["search_result_domains"]),
        "search_recommend_domain_count": len(database["quality"]["search_recommend_domains"]),
        "quality_snapshot_verified": True, "production_write_set_verified": True,
        "post_cycle_health": "ready", "physical_http": http["physical_http"]}
    result["canonical_result_sha256"] = digest({"database": database["canonical_sha256"],
        "http_receipt": http["worker_receipt_sha256"], "seal": digest(seal), "projection": result})
    return result


def preserved_signature(database):
    return digest({key: database[key] for key in ("bucket_key", "run_identity_sha256", "started_at", "completed_at",
        "lease_expires_at", "provider_request_count", "endpoint_counts", "attempts", "snapshot", "quality")})


def compose_state(*, phase: str, host: dict, database: dict, baseline: dict, cycle: dict, aggregate: dict) -> dict:
    require(phase in {"promoted", "rollback", "final"}, "phase")
    checked_fact(host, "noteai.item33.host_facts.v1", ensure_ascii=True)
    checked_database_cycle(database)
    checked_database_cycle(baseline)
    require(host["phase"] == phase and host.get("capture_container_count") == 0
            and type(host.get("capture_container_count")) is int
            and host.get("capture_service_failure_present") is False
            and host["activation_identity_sha256"] == cycle["activation_identity_sha256"]
            and database["run_identity_sha256"] == cycle["run_identity_sha256"]
            and preserved_signature(database) == preserved_signature(baseline), "state_binding")
    require(not dml.cycle_contract_errors(aggregate, request_count=34,
            keyword_count=database["quality"]["keyword_count"]), "capture_unproven")
    result = {"phase": phase, "observed_at": min(timestamp(host["observed_at"]), timestamp(database["observed_at"])).isoformat(),
        "activation_identity_sha256": cycle["activation_identity_sha256"], "run_identity_sha256": cycle["run_identity_sha256"],
        **{key: host[key] for key in ("unit_sha256", "unit_active", "unit_sub", "unit_enabled", "collection_suspended",
            "formal_unit_count", "formal_container_count", "process_count", "task_container_count",
            "inspection_container_count", "stage_directory_count", "runtime_directory_count",
            "temporary_unit_count", "temporary_dropin_count")},
        **{key: database["ledger"][key] for key in ("active_run_count", "active_attempt_count", "outcome_unknown_count", "unlinked_attempt_count")},
        "health": "stopped" if phase == "rollback" else "ready", "provider_calls": database["provider_calls"],
        "production_database_writes": database["production_database_writes"]}
    if phase in {"rollback", "final"}:
        result.update(preserved_run_count=database["ledger"]["same_bucket_run_count"],
            preserved_attempt_count=len(database["attempts"]), preserved_snapshot_count=1,
            database_audit_deletes=aggregate["delete_rows"],
            same_bucket_new_run_delta=database["ledger"]["same_bucket_run_count"] - baseline["ledger"]["same_bucket_run_count"],
            same_bucket_provider_call_delta=database["provider_request_count"] - baseline["provider_request_count"])
    result["canonical_sha256"] = digest({"host": host["canonical_sha256"], "database": database["canonical_sha256"],
        "baseline": baseline["canonical_sha256"], "aggregate": digest(aggregate), "projection": result})
    return result


def preserved_rows(database: dict) -> dict:
    """Stable row projections across restarts; observation time is excluded."""
    checked_database_cycle(database)
    return {"run_count": database["ledger"]["same_bucket_run_count"],
        "attempt_count": len(database["attempts"]), "snapshot_count": 1,
        "run_sha256": digest({key: database[key] for key in ("bucket_key", "run_identity_sha256",
            "started_at", "completed_at", "lease_expires_at", "provider_request_count", "endpoint_counts")}),
        "attempt_ledger_sha256": digest(database["attempts"]), "snapshot_sha256": database["snapshot"]["sha256"]}


def compose_normal(*, host: dict, database: dict, baseline: dict, cycle: dict,
                   seal_raw: bytes, teardown_raw: bytes, capture_close: dict) -> dict:
    """Normal-runtime readback, after independent capture teardown validation.

    The controller separately verifies the original seal, journal and teardown;
    this projection binds their exact bytes and proves rows survived the restart.
    """
    checked_fact(host, "noteai.item33.host_facts.v1", ensure_ascii=True)
    checked_database_cycle(database)
    checked_database_cycle(baseline)
    require(host["phase"] == "normal" and host.get("capture_container_count") == 0
            and type(host.get("capture_container_count")) is int
            and host.get("capture_service_failure_present") is False
            and host["activation_identity_sha256"] == cycle["activation_identity_sha256"]
            and host["unit_sha256"] == controller.V5_NORMAL_UNIT_SHA256
            and database["run_identity_sha256"] == cycle["run_identity_sha256"]
            and preserved_signature(database) == preserved_signature(baseline), "normal_binding")
    require(all(type(host[key]) is int and host[key] == 0 for key in (
        "task_container_count", "inspection_container_count", "stage_directory_count", "runtime_directory_count",
        "temporary_unit_count", "temporary_dropin_count")), "normal_cleanup")
    require(isinstance(seal_raw, bytes) and seal_raw and isinstance(teardown_raw, bytes) and teardown_raw,
            "normal_artifacts")
    return {"schema": "noteai.item33.normal_readback.v1",
        "activation_identity_sha256": cycle["activation_identity_sha256"],
        "run_identity_sha256": cycle["run_identity_sha256"], "bucket_key": database["bucket_key"],
        "observed_at": min(timestamp(host["observed_at"]), timestamp(database["observed_at"])).isoformat(),
        "unit_sha256": host["unit_sha256"], "preserved": preserved_rows(database),
        "final": {"active": host["unit_active"], "sub": host["unit_sub"], "enabled": host["unit_enabled"],
            "collection_suspended": host["collection_suspended"], "formal_unit_count": host["formal_unit_count"],
            "formal_container_count": host["formal_container_count"], "process_count": host["process_count"], "health": "ready"},
        "same_bucket": {"bucket_key": database["bucket_key"],
            "new_run_delta": database["ledger"]["same_bucket_run_count"] - baseline["ledger"]["same_bucket_run_count"],
            "provider_call_delta": database["provider_request_count"] - baseline["provider_request_count"]},
        "capture_receipt_sha256": hashlib.sha256(seal_raw).hexdigest(),
        "teardown_sha256": hashlib.sha256(teardown_raw).hexdigest(), "capture_close": dict(capture_close),
        "secret_values_recorded": False}
