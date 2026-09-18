"""Project supplied daemon output into one run's safe physical HTTP evidence.

No Docker, provider, database or filesystem mutation occurs here. A daemon is
still running, so a completed cycle is never reported as a fabricated exit0.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

try:
    from . import internal_deployment_readiness_gate as gate
except ImportError:
    import internal_deployment_readiness_gate as gate


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA = "noteai.item33.worker_http_receipt.v1"
RECEIPT_REF = "deploy/production/evidence/production-item33-trends-worker-http-receipt.json"
MAX_OUTPUT = 4 * 1024 * 1024
RUN_EVENTS = {"trends_run_started", "trends_run_succeeded", "trends_run_failed", "trends_run_skipped"}
DIAGNOSTIC_EVENTS = {"xhs_trends_http_observation", "xhs_trends_provider_failure",
                     "xhs_trends_candidate_diagnostics"}


class Item33HttpReadbackError(RuntimeError):
    """Fixed reason only; raw output and exception text never escape."""


def require(condition, reason):
    if not condition:
        raise Item33HttpReadbackError(reason)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _projectors():
    source = ROOT / "model/security_redaction.py"
    raw = source.read_bytes()
    require(digest(raw) == gate.ITEM33_V5_RUNTIME_OVERLAY_SHA256["model/security_redaction.py"],
            "diagnostic_source_binding")
    scope = {"__name__": "item33_bound_security_redaction", "__file__": str(source)}
    exec(compile(raw, str(source), "exec"), scope)
    return tuple(scope[name] for name in ("sanitize_trends_http_event", "sanitize_trends_failure",
                                          "sanitize_trends_candidate_diagnostics"))


def verify_worker_receipt(receipt: dict, cycle: dict) -> bool:
    """Recheck a saved safe projection without access to its original output."""
    keys = {"schema", "run_identity_sha256", "bucket_key", "output_sha256", "output_size",
            "projector_source_sha256", "reader_source_sha256", "structured_events",
            "physical_http_observations", "physical_http_summary", "provider_failures",
            "candidate_diagnostics", "invalid_candidate_diagnostics", "reason_codes", "secret_values_recorded"}
    if (not gate._keys_exact(receipt, keys) or not isinstance(cycle, dict)
        or receipt["schema"] != RECEIPT_SCHEMA or receipt["secret_values_recorded"] is not False
        or receipt["run_identity_sha256"] != cycle.get("run_identity_sha256")
        or receipt["bucket_key"] != cycle.get("bucket_key")
        or not gate._sha256(receipt["output_sha256"])
        or not gate._exact_int(receipt["output_size"]) or not 0 < receipt["output_size"] <= MAX_OUTPUT
        or receipt["reader_source_sha256"] != digest(Path(__file__).read_bytes())
        or receipt["projector_source_sha256"] != gate.ITEM33_V5_RUNTIME_OVERLAY_SHA256["model/security_redaction.py"]
        or receipt["provider_failures"] != [] or receipt["reason_codes"] != []
        or not gate._exact_int(receipt["invalid_candidate_diagnostics"], 0)):
        return False
    expected_events = [{"event": "trends_run_" + suffix, "run_identity_sha256": cycle.get("run_identity_sha256"),
                        "status": status} for suffix, status in (("started", "running"), ("succeeded", "succeeded"))]
    expected_summary = {"initialization_dispatches_observed": 2,
        "initialization_request_counts": {"dsl": 1, "session": 1}, "collection_dispatches_observed": 34,
        "response_events_observed": 36, "unknown_events_observed": 0, "unresolved_dispatches_observed": 0,
        "invalid_observations": 0, "observation_complete": True}
    if (receipt["structured_events"] != expected_events
        or encoded(receipt["physical_http_summary"]) != encoded(expected_summary)):
        return False
    project_http, _, project_candidates = _projectors()
    observations, candidates = receipt["physical_http_observations"], receipt["candidate_diagnostics"]
    if (not isinstance(observations, list) or len(observations) != 72
        or any(project_http(row) != row for row in observations)
        or not isinstance(candidates, list) or len(candidates) not in (0, 2)
        or any(project_candidates(row) != row or row.get("stage") != stage
               for row, stage in zip(candidates, ("selection", "evidence_check")))):
        return False
    physical = cycle.get("physical_http")
    return (isinstance(physical, dict) and physical.get("observations") == observations
        and physical.get("worker_receipt_sha256") == digest(encoded(receipt))
        and gate._item32_v5_physical_valid(physical, {key: value for key, value in physical.items()
            if key != "observations"}, cycle.get("attempts"), gate._evidence_clock(cycle.get("started_at")),
            gate._evidence_clock(cycle.get("completed_at"))))


def read_http_facts(raw: bytes, *, cycle: dict, observed_at: datetime) -> dict:
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_OUTPUT, "output_size")
    require(isinstance(cycle, dict) and isinstance(observed_at, datetime)
            and observed_at.tzinfo is not None, "cycle_input")
    observed_at = observed_at.astimezone(timezone.utc)
    identity, bucket = cycle.get("run_identity_sha256"), cycle.get("bucket_key")
    start, finish = (gate._evidence_clock(cycle.get(key)) for key in ("started_at", "completed_at"))
    require(gate._sha256(identity) and start is not None and finish is not None
            and start <= finish <= observed_at and start.date().isoformat() == bucket
            and finish.date().isoformat() == bucket, "cycle_identity_or_clock")
    attempts = cycle.get("attempts")
    project_http, project_failure, project_candidates = _projectors()
    events, http, failures, candidates = [], [], [], []
    reasons = set()
    active = ended = returned = False
    starts = successes = 0
    invalid_http = invalid_candidates = 0

    def matches(value):
        run = value.get("run_id")
        return (isinstance(run, str) and 0 < len(run) <= 64
                and digest(run.encode()) == identity and value.get("bucket_key") == bucket)

    for line in raw.decode("utf-8", errors="replace").splitlines():
        first = line.find("{")
        if first < 0:
            continue
        try:
            value = json.loads(line[first:], object_pairs_hook=gate._json_object_without_duplicate_keys,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (TypeError, ValueError):
            if any(event in line for event in RUN_EVENTS | DIAGNOSTIC_EVENTS):
                reasons.add("malformed_structured_event")
            continue
        if not isinstance(value, dict):
            continue
        event = value.get("event")
        if not isinstance(event, str):
            event = None
        if event in RUN_EVENTS:
            if event == "trends_run_skipped":
                if active or value.get("status") != "skipped" or not gate._exact_int(value.get("provider_calls"), 0):
                    reasons.add("unexpected_run_boundary")
                continue
            if not matches(value):
                reasons.add("run_identity_mismatch")
                continue
            if event == "trends_run_started":
                starts += 1
                if active or ended or value.get("status") != "running":
                    reasons.add("unexpected_run_boundary")
                active = True
            elif event == "trends_run_succeeded":
                successes += 1
                if (not active or ended or value.get("status") != "succeeded"
                    or not gate._exact_int(value.get("provider_calls"), 34)):
                    reasons.add("unexpected_run_boundary")
                active, ended = False, True
            else:
                active = False
                reasons.add("run_failed")
            events.append({"event": event, "run_identity_sha256": identity,
                           "status": value.get("status") if value.get("status") in
                           ("running", "succeeded", "failed") else "unknown"})
            continue
        if event in DIAGNOSTIC_EVENTS:
            if not active:
                reasons.add("diagnostic_outside_run")
            if event == "xhs_trends_http_observation":
                safe = project_http(value)
                if safe and len(http) < 72:
                    http.append(safe)
                else:
                    invalid_http += 1
            elif event == "xhs_trends_provider_failure":
                reasons.add("provider_failure")
                if len(failures) < 36:
                    failures.append(project_failure(value))
            else:
                safe = project_candidates(value)
                expected = "selection" if not candidates else "evidence_check"
                if safe and len(candidates) < 2 and safe.get("stage") == expected:
                    candidates.append(safe)
                else:
                    invalid_candidates += 1
            continue
        if "ok" in value:
            # The normal successful daemon summary is after the run event, not
            # a process exit. Repeated skipped summaries contain no run_id.
            if matches(value):
                if not ended or returned or value.get("ok") is not True or not gate._exact_int(value.get("provider_calls"), 34):
                    reasons.add("run_return_mismatch")
                returned = True
            elif value.get("ok") is False or "run_id" in value:
                reasons.add("run_return_mismatch")
    if starts != 1 or successes != 1 or active or not ended or not returned:
        reasons.add("run_not_completed")
    if invalid_candidates:
        reasons.add("candidate_diagnostics_invalid")
    dispatched, terminal = {}, {}
    for event in http:
        sequence, kind = event["sequence"], event["request_kind"]
        if event["phase"] == "dispatch":
            if sequence in dispatched or sequence != len(dispatched) + 1:
                invalid_http += 1
            dispatched[sequence] = kind
        else:
            if sequence in terminal or dispatched.get(sequence) != kind:
                invalid_http += 1
            terminal[sequence] = event["phase"]
    kinds = Counter(dispatched.values())
    summary = {"initialization_dispatches_observed": kinds["dsl"] + kinds["session"],
        "initialization_request_counts": {key: kinds[key] for key in ("dsl", "session")},
        "collection_dispatches_observed": sum(kinds.values()) - kinds["dsl"] - kinds["session"],
        "response_events_observed": sum(value == "response" for value in terminal.values()),
        "unknown_events_observed": sum(value == "unknown" for value in terminal.values()),
        "unresolved_dispatches_observed": len(set(dispatched) - set(terminal)),
        "invalid_observations": invalid_http,
        "observation_complete": bool(dispatched) and not invalid_http and set(dispatched) == set(terminal)}
    physical = {"initialization_count": summary["initialization_dispatches_observed"],
        "collection_count": summary["collection_dispatches_observed"], "total_count": len(dispatched),
        "total_limit": 36, "automatic_retry_count": 0, "first_homefeed_is_gate": True,
        "worker_receipt_sha256": "0" * 64, "observations": http}
    physical_summary = {key: value for key, value in physical.items() if key != "observations"}
    if invalid_http or not gate._item32_v5_physical_valid(physical, physical_summary, attempts, start, finish):
        reasons.add("physical_http_contract")
    physical_valid = not reasons
    receipt = {"schema": RECEIPT_SCHEMA, "run_identity_sha256": identity, "bucket_key": bucket,
        "output_sha256": digest(raw), "output_size": len(raw), "structured_events": events,
        "projector_source_sha256": gate.ITEM33_V5_RUNTIME_OVERLAY_SHA256["model/security_redaction.py"],
        "reader_source_sha256": digest(Path(__file__).read_bytes()),
        "physical_http_observations": http, "physical_http_summary": summary,
        "provider_failures": failures, "candidate_diagnostics": candidates,
        "invalid_candidate_diagnostics": invalid_candidates, "reason_codes": sorted(reasons),
        "secret_values_recorded": False}
    receipt_bytes = encoded(receipt)
    physical["worker_receipt_sha256"] = digest(receipt_bytes)
    # Zero retries is asserted only by the accepted exact full physical proof.
    if not physical_valid:
        physical["automatic_retry_count"] = None
        physical["first_homefeed_is_gate"] = None
    return {"schema": "noteai.item33.http_readback.v1",
        "observed_at": observed_at.isoformat(), "state": "HTTP_PROOF_VERIFIED" if physical_valid else "HTTP_PROOF_INCOMPLETE",
        "physical_http_verified": physical_valid, "physical_http": physical,
        "worker_receipt": receipt, "worker_receipt_ref": RECEIPT_REF,
        "worker_receipt_sha256": digest(receipt_bytes), "worker_receipt_size": len(receipt_bytes),
        "daemon_exit_code": None, "database_operations": 0, "provider_calls": 0,
        "raw_output_saved": False, "secret_values_recorded": False}
