"""Assemble an Item33 candidate from retained facts; no connections or writes.

The caller saves the listed original bytes and runs the original Item33 gate
before crediting readiness. Missing facts are errors, never synthetic defaults.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

try:
    from . import internal_deployment_readiness_gate as gate
    from . import execute_item33_trends_promotion as controller
    from . import item33_trends_readback_assembly as facts
    from . import item33_trends_runtime_capture as capture
    from . import item33_trends_dml_capture as dml
    from . import item33_trends_http_readback as http
    from . import item33_trends_capture_teardown as teardown
except ImportError:
    import internal_deployment_readiness_gate as gate
    import execute_item33_trends_promotion as controller
    import item33_trends_readback_assembly as facts
    import item33_trends_runtime_capture as capture
    import item33_trends_dml_capture as dml
    import item33_trends_http_readback as http
    import item33_trends_capture_teardown as teardown


ACTION_REFS = {phase: f"deploy/production/evidence/production-item33-trends-{phase}-action.json"
               for phase in ("promotion", "rollback", "reapply")}
SNAPSHOT_REF = "deploy/production/evidence/production-item33-trends-snapshot.json"


class EvidenceAssemblyError(ValueError):
    """Fixed diagnostic, never original logs, statements or connection details."""


def require(value, code="item33_assembly_unproven"):
    if not value:
        raise EvidenceAssemblyError(code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pick(value, names):
    require(isinstance(value, dict) and set(names) <= set(value), "item33_assembly_missing_fact")
    return {name: copy.deepcopy(value[name]) for name in names}


def utc(value):
    require(isinstance(value, str), "item33_assembly_clock")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0, "item33_assembly_clock")
    return parsed


def assemble_terminal(*, promotion_result: dict, normal_handoff: dict, database_cycle: dict,
                      release_binding: dict, artifacts: dict[str, bytes], control_facts: dict,
                      observed_at: datetime, source_root: Path = gate.ROOT) -> dict:
    """Return ``terminal`` and exact ``required_artifacts`` metadata.

    control_facts has exactly cycle_authentication, managed_runtime, cleanup,
    cost. It contains original observations, not permission to assume zero.
    Artifacts maps fixed evidence references to original bytes; no caller path
    is opened. source_root is used only for non-secret reviewed source hashes.
    """
    try:
        require(isinstance(observed_at, datetime) and observed_at.tzinfo is not None
                and observed_at.utcoffset().total_seconds() == 0, "item33_assembly_clock")
        require(isinstance(artifacts, dict) and isinstance(control_facts, dict)
                and set(control_facts) == {"cycle_authentication", "managed_runtime", "cleanup", "cost"})
        used = {}

        def raw(ref, expected=None):
            value = artifacts.get(ref)
            require(isinstance(value, bytes) and 0 < len(value) <= 16 * 1024 * 1024,
                    "item33_assembly_missing_artifact")
            sha = digest(value)
            require(expected is None or sha == expected, "item33_assembly_artifact_binding")
            used[ref] = {"ref": ref, "bytes": len(value), "sha256": sha}
            return value

        def document(ref, expected=None):
            value = json.loads(raw(ref, expected), object_pairs_hook=gate._json_object_without_duplicate_keys)
            require(isinstance(value, dict) and not gate._has_sensitive_evidence_key(value))
            return value

        result = promotion_result
        require(result.get("schema") == controller.RESULT_SCHEMA and result.get("status") == "VERIFIED"
                and result.get("readiness_credit") is False and result.get("secret_values_recorded") is False)
        require(result.get("action_counts") == {"cycle": 1, "promotion": 1, "rollback": 1, "reapply": 1, "automatic_retry": 0}
                and all(type(value) is int for value in result["action_counts"].values()))
        cycle = result["cycle"]
        controller._validate_cycle(cycle, run_identity=result["run_identity_sha256"],
            activation_identity=result["activation_identity_sha256"], bucket_key=result["bucket_key"],
            remaining=34, not_before=utc(result["preflight"]["observed_at"]))
        require(utc(result["observed_at"]) <= observed_at)
        facts.checked_database_cycle(database_cycle)
        require(all(database_cycle[key] == cycle[key] for key in (
            "run_identity_sha256", "bucket_key", "started_at", "completed_at", "attempts", "endpoint_counts")))

        release = copy.deepcopy(release_binding)
        binding = release["capture_binding"]
        require({key: binding[key] for key in result["capture_binding"]} == result["capture_binding"])
        require(binding["receipt_ref"] == gate.ITEM33_V5_CAPTURE_EVIDENCE)
        seal_raw = raw(binding["receipt_ref"], binding["receipt_sha256"])
        seal = document(binding["receipt_ref"], binding["receipt_sha256"])
        journal = raw(gate.ITEM33_V5_CAPTURE_JOURNAL, seal["journal"]["sha256"])
        aggregate = capture.verify_capture_artifacts(seal, journal)
        require(not dml.cycle_contract_errors(aggregate, request_count=34,
            keyword_count=database_cycle["quality"]["keyword_count"]))
        require(seal["run_identity_sha256"] == cycle["run_identity_sha256"]
                and seal["activation_identity_sha256"] == cycle["activation_identity_sha256"]
                and seal["config_sha256"] == binding["configuration_sha256"]
                and seal["accepted_source_sha256"] == release["runtime_overlay_sha256"])
        for ref, sha in {**binding["source_sha256"],
                         seal["catalog_proof"]["source_ref"]: seal["catalog_proof"]["source_sha256"]}.items():
            require(ref in gate.ITEM33_V5_CAPTURE_TOOLS | {"tools/item33_trends_capture_catalog.py"}
                    and digest((source_root / ref).read_bytes()) == sha, "item33_assembly_source_binding")
        receipt = document(gate.ITEM33_V5_HTTP_RECEIPT, cycle["physical_http"]["worker_receipt_sha256"])
        require(http.verify_worker_receipt(receipt, cycle), "item33_assembly_http_unproven")

        normal = copy.deepcopy(normal_handoff)
        require(normal["status"] == "VERIFIED" and normal["capture_receipt_sha256"] == digest(seal_raw)
                and normal["run_identity_sha256"] == cycle["run_identity_sha256"]
                and normal["activation_identity_sha256"] == cycle["activation_identity_sha256"]
                and utc(normal["observed_at"]) <= observed_at)
        require(normal["teardown_ref"] == gate.ITEM33_V5_CAPTURE_TEARDOWN)
        proof = document(normal["teardown_ref"], normal["teardown_sha256"])
        teardown.verify_teardown_proof(proof, seal_raw=seal_raw, journal=journal,
            source_sha256=digest((source_root / teardown.SOURCE_REF).read_bytes()))
        close = normal["capture_close"]
        require(set(close) == {key + suffix for key in gate.ITEM33_V5_CAPTURE_CLOSE_REFS for suffix in ("_ref", "_sha256")})
        close_facts = {}
        for key, ref in gate.ITEM33_V5_CAPTURE_CLOSE_REFS.items():
            require(close[key + "_ref"] == ref)
            close_facts[key] = document(ref, close[key + "_sha256"])
        service, closed, host = (close_facts[key] for key in ("service_result", "close", "host"))
        require(service["state"] == "SEALED" and service["capture_seal_sha256"] == digest(seal_raw)
                and service["run_identity_sha256"] == cycle["run_identity_sha256"]
                and closed["state"] == "CONNECTIONS_CLOSED" and type(closed["connection_count"]) is int
                and closed["connection_count"] == 3 and host["capture_service_failure_present"] is False
                and type(host["capture_container_count"]) is int and host["capture_container_count"] == 0,
                "item33_assembly_close_unproven")
        require(all(value["activation_identity_sha256"] == cycle["activation_identity_sha256"]
                    for value in (service, closed, host)))
        require(all(value["configuration_sha256"] == seal["config_sha256"] for value in (service, closed)))
        facts.checked_fact(host, "noteai.item33.host_facts.v1", ensure_ascii=True)
        timeline = [utc(value) for value in (cycle["completed_at"], seal["catalog_proof"]["after"]["observed_at"],
            service["observed_at"], closed["observed_at"], proof["execution"]["started_at"], proof["after"]["observed_at"],
            normal["started_at"], normal["completed_at"], normal["observed_at"])]
        require(timeline == sorted(timeline) and timeline[-1] <= observed_at)
        require(normal["action_ref"] == gate.ITEM33_V5_NORMAL_ACTION and normal["readback_ref"] == gate.ITEM33_V5_NORMAL_READBACK)
        normal_action = document(normal["action_ref"], normal["action_sha256"])
        normal_readback = document(normal["readback_ref"], normal["readback_sha256"])
        require(normal_action["observed_at"] == normal["started_at"] and normal_action["completed_at"] == normal["completed_at"])
        require(all(normal_readback[key] == normal[key] for key in (
            "activation_identity_sha256", "run_identity_sha256", "observed_at", "preserved", "final",
            "same_bucket", "capture_receipt_sha256", "teardown_sha256", "capture_close")))

        actions = {}
        for phase, ref in ACTION_REFS.items():
            actions[phase] = document(ref, result[phase]["canonical_result_sha256"])
            action = actions[phase]
            require(action["status"] == "APPLIED_REQUIRES_STATE_READBACK" and action["phase"] == phase
                    and action["activation_identity_sha256"] == cycle["activation_identity_sha256"]
                    and action["bucket_key"] == cycle["bucket_key"])
            require(all(action[key] == result[phase][key] for key in ("before_unit_sha256", "after_unit_sha256")))
            require(utc(action["observed_at"]) <= utc(action["completed_at"]) <= observed_at)

        pre, promoted, rollback, final = (result[key] for key in (
            "preflight", "promoted_readback", "rollback_readback", "final_readback"))
        snapshot_raw = raw(SNAPSHOT_REF, database_cycle["snapshot"]["sha256"])
        require(len(snapshot_raw) == database_cycle["snapshot"]["size"]
                and json.loads(snapshot_raw) == database_cycle["snapshot"]["payload"])
        snapshot = database_cycle["snapshot"]["payload"]
        published = {domain: len(value["keywords"]) for domain, value in snapshot["domains"].items()}
        preserved = facts.preserved_rows(database_cycle)
        require(preserved == normal["preserved"])
        auth = control_facts["cycle_authentication"]
        require(auth == {"source": "real_xhs", "authenticated_session": True}
                and auth["authenticated_session"] is True)
        runtime = control_facts["managed_runtime"]
        require(set(runtime) == {"unit_name", "container_name", "database_role", "argv", "runtime",
            "singleton_winner_count", "restart_policy", "automatic_restart_count"})
        require(runtime["unit_name"] == "noteai-xhs-trends.service" and runtime["container_name"] == "noteai-xhs-trends"
                and runtime["database_role"] == "noteai_xhs_trends" and runtime["argv"] == ["/app/scripts/render_run_market_timing.sh"]
                and runtime["restart_policy"] == "no" and type(runtime["singleton_winner_count"]) is int
                and runtime["singleton_winner_count"] == 1 and type(runtime["automatic_restart_count"]) is int
                and runtime["automatic_restart_count"] == 0)
        expected_runtime = {"memory_bytes": 536870912, "cpus_millis": 500, "pids_limit": 64, "user": "999:999",
            "read_only": True, "cap_drop": ["ALL"], "no_new_privileges": True, "log_driver": "local",
            "log_max_size": "10m", "log_max_file": 2}
        require(json.dumps(runtime["runtime"], sort_keys=True, allow_nan=False)
                == json.dumps(expected_runtime, sort_keys=True), "item33_assembly_runtime_fact")
        cleanup = control_facts["cleanup"]
        zero_cleanup = {"task_container_count", "inspection_container_count", "stage_directory_count", "runtime_directory_count",
            "temporary_unit_count", "temporary_dropin_count", "local_snapshot_count", "local_export_count"}
        require(set(cleanup) == zero_cleanup | {"formal_managed_container_count", "rollback_artifact_retained", "rollback_artifact_sha256"}
                and all(type(cleanup[key]) is int and cleanup[key] == 0 for key in zero_cleanup)
                and type(cleanup["formal_managed_container_count"]) is int and cleanup["formal_managed_container_count"] == 1
                and cleanup["rollback_artifact_retained"] is True and gate._sha256(cleanup["rollback_artifact_sha256"]),
                "item33_assembly_cleanup_fact")
        cost = control_facts["cost"]
        zero_cost = {"postpaid_resources_started", "postpaid_resources_running", "new_recurring_resource_count",
            "new_recurring_monthly_fen", "real_funds_fen", "payment_actions"}
        fee_fields = {"provider_fee_fen", "incremental_cloud_cost_fen"}
        require(set(cost) == zero_cost | fee_fields | {"currency", "xhs_provider_requests"}
                and cost["currency"] == "CNY" and type(cost["xhs_provider_requests"]) is int
                and cost["xhs_provider_requests"] == cycle["physical_http"]["total_count"]
                and all(type(cost[key]) is int and cost[key] == 0 for key in zero_cost)
                and all(cost[key] == "UNKNOWN" or (type(cost[key]) is int and cost[key] >= 0) for key in fee_fields),
                "item33_assembly_cost_fact")
        before = {key: pre["unit_" + key] for key in ("active", "sub", "enabled")}
        before.update(pick(pre, ("collection_suspended", "formal_container_count")))
        after = {key: promoted["unit_" + key] for key in ("active", "sub", "enabled")}
        after.update(pick(promoted, ("collection_suspended", "formal_unit_count", "formal_container_count",
            "process_count", "active_run_count", "active_attempt_count", "outcome_unknown_count", "unlinked_attempt_count", "health")))
        after.update(service_state_row_count=database_cycle["ledger"]["idle_service_count"], database_service_status="idle")
        stopped = {key: rollback["unit_" + key] for key in ("active", "sub", "enabled")}
        stopped.update(pick(rollback, ("collection_suspended", "formal_container_count")))
        final_state = {key: final["unit_" + key] for key in ("active", "sub", "enabled")}
        final_state.update(pick(final, ("collection_suspended", "formal_unit_count", "formal_container_count", "process_count", "health")))
        terminal_cycle = pick(cycle, ("run_identity_sha256", "activation_identity_sha256", "bucket_key",
            "started_at", "completed_at", "lease_expires_at", "cycle_count", "same_bucket_completed_run_count",
            "challenge_detected", "provider_request_count", "provider_request_succeeded", "provider_request_failed",
            "active_admitted_count", "outcome_unknown_count", "automatic_retry_count", "endpoint_counts", "attempts", "physical_http"))
        terminal_cycle.update(copy.deepcopy(auth), provider_request_limit=result["authorization"]["provider_request_limit"])
        terminal = {"schema": gate.ITEM33_TRENDS_PROMOTION_EVIDENCE_SCHEMA, "item": 33,
            "status": "VERIFIED", "readiness_credit": True, "observed_at": observed_at.isoformat(),
            "release_binding": release, "cycle": terminal_cycle,
            "quality_snapshot": {"snapshot_ref": SNAPSHOT_REF, "snapshot_sha256": digest(snapshot_raw),
                "snapshot_size_bytes": len(snapshot_raw), "snapshot_schema_version": snapshot["schema_version"],
                "snapshot_row_count": preserved["snapshot_count"], "run_snapshot_sha256": database_cycle["snapshot"]["sha256"],
                "run_snapshot_size_bytes": database_cycle["snapshot"]["size"],
                "real_keyword_counts_by_domain": copy.deepcopy(database_cycle["quality"]["domain_real_keyword_counts"]),
                "search_result_domains": copy.deepcopy(database_cycle["quality"]["search_result_domains"]),
                "search_recommend_domains": copy.deepcopy(database_cycle["quality"]["search_recommend_domains"]),
                "published_keyword_counts_by_domain": published, "published_keyword_count": sum(published.values())},
            "promotion": {**copy.deepcopy(runtime), "before": before, "after": after},
            "recovery": {"status": "VERIFIED", "scope": "trends_only", "rollback_count": result["action_counts"]["rollback"],
                "rollback_started_at": actions["rollback"]["observed_at"], "rollback_completed_at": actions["rollback"]["completed_at"],
                "rollback_final": stopped, "other_unit_actions": result["rollback"]["other_unit_actions"],
                "provider_call_delta": final["same_bucket_provider_call_delta"], "database_audit_deletes": rollback["database_audit_deletes"],
                "preserved": preserved, "reapplied_promoted_unit_sha256": actions["reapply"]["after_unit_sha256"],
                "reapplied_at": actions["reapply"]["observed_at"], "manual_start_count": result["action_counts"]["reapply"],
                "restart_policy": runtime["restart_policy"], "same_bucket": {"bucket_key": cycle["bucket_key"],
                    "new_run_delta": final["same_bucket_new_run_delta"], "provider_call_delta": final["same_bucket_provider_call_delta"]},
                "final": final_state},
            "production_write_set": {"tables": sorted(dml.TABLE_KEYS),
                "distinct_rows_touched_by_table": {table: aggregate["distinct_rows_touched_by_table"][table] for table in dml.TABLE_KEYS},
                **pick(aggregate, ("out_of_contract_row_mutations", "delete_rows", "truncate_count", "forbidden_table_mutations", "atomic_publish")),
                "ddl_count": seal["catalog_proof"]["business_ddl_count"]},
            "readbacks": {"preflight": pick(pre, ("observed_at", "canonical_sha256", "database_role", "role_exact", "acl_exact",
                "unit_active", "unit_sub", "unit_enabled", "formal_container_count", "active_run_count", "same_bucket_run_count",
                "outcome_unknown_count", "unlinked_attempt_count", "utc_provider_budget_used_before", "utc_provider_budget_remaining_before",
                "provider_calls", "production_database_writes")),
                "post_cycle": pick(promoted, ("observed_at", "canonical_sha256", "health", "provider_calls", "production_database_writes")),
                "rollback": pick(rollback, ("observed_at", "canonical_sha256", "provider_calls", "database_audit_deletes")),
                "final": pick(final, ("observed_at", "canonical_sha256", "health", "provider_calls", "production_database_writes"))},
            "cleanup": copy.deepcopy(control_facts["cleanup"]), "cost": copy.deepcopy(control_facts["cost"]),
            "normal_handoff": normal, "secret_values_recorded": False}
        return {"terminal": terminal, "required_artifacts": [used[key] for key in sorted(used)]}
    except (KeyError, TypeError, ValueError, OSError, controller.Item33ExecutionError, facts.Item33AssemblyError) as exc:
        if isinstance(exc, EvidenceAssemblyError):
            raise
        raise EvidenceAssemblyError("item33_assembly_unproven") from None
