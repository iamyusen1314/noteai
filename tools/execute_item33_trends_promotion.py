#!/usr/bin/env python3
"""Fail-closed orchestration for the dependency-gated Item33 promotion.

This module does not open the production database, read Secrets, call XHS, or
invoke systemd/Docker itself.  A production wrapper supplies narrow callables
for the already implemented Trends cycle and the managed unit transitions.
The outer controller fixes ordering, request budget, no-replay behavior, and
the one rollback/reapply rehearsal required by Item33.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UNIT_NAME = "noteai-xhs-trends.service"
SUSPENDED_UNIT_SHA256 = (
    "3ed7e555d61c8286ab6d1116d99171d23d073b6a318dbd4890ce3106b976e3b6"
)
LEGACY_PROMOTED_UNIT_SHA256 = (
    "13d777c7705cc1dbc539c3dad3e034ba0ce5226b038e355d91bd3a440e565f8c"
)
PROMOTED_UNIT_SHA256 = (
    "0a1c100462e62e9043ef0b73d81a8b12b85bd684b90c9e1d3a24e0a705fb88ff"
)
RUNTIME_OVERLAY_ROOT = Path("/var/lib/noteai/xhs-trends-runtime/1be2fde")
RUNTIME_OVERLAY_SHA256 = {
    "model/spider_xhs_http.py": "360a43f781e55e2c529387e70ef7be3b5f47a716bf6ede56d3daaaefa9b6bea1",
    "model/security_redaction.py": "c5fc02966035a01012a1a35b7005f3a62a72602c042e98dbad707029ca56f451",
    "model/hot_keywords.py": "77ff2a7e6b279d35a65f1dc497d32c92cc3bf46c061f0e42229dc42e3b81fc6d",
}
V5_PROFILE = "pc_v5_source_retention"
V5_SOURCE_REVISION = "e7f33456465632448974b435d3e56ddd73865740"
V5_ITEM32_TERMINAL_SHA256 = "1456a938acba00a12a9b547dd13e4054ef89b4bca05597363808007be28eb584"
V5_IMAGE_CONFIG_SHA256 = "6d5dcf058c5a0990ba7df3103f63e414de69b62b0ec3481c08490d66ae30b703"
V5_REGISTRY_MANIFEST_SHA256 = "87b9bf70c7ded691659ca39d3ea2453f9a97dfbdb83c05c44e838c8b0cf417c9"
V5_RUNTIME_OVERLAY_ROOT = Path("/var/lib/noteai/xhs-trends-runtime/e7f3345")
V5_RUNTIME_OVERLAY_SHA256 = {
    "model/hot_keywords.py": "77ff2a7e6b279d35a65f1dc497d32c92cc3bf46c061f0e42229dc42e3b81fc6d",
    "model/market_timing_worker.py": "ad5eb9d65cbe7b1b4919d388770260af8b490bd1ab72d52e32ee6a927f831e1f",
    "model/scheduler_a.py": "2cd8bbd094e0013fb023675618a532715a194afcde684715d5692150524f1f5b",
    "model/security_redaction.py": "09e31604f6d52d7fb101b38c1856d9388b6ce5e1612cc2c67095344ce725f694",
    "model/spider_xhs_http.py": "04c94f75ea34cd1d136f0db6808abed35d0c0007081d225a15af20e05fc12d93",
    "model/spider_xhs_v5.py": "d76bdc50578c886cdf1451cc03a204bb628c036c6c3da767d8e5e50361885dae",
    "model/trends_contract.py": "5ee865bad89fa8a96b3f0c35f02e2412958f07bf87ba158bab5796ba7da12a3c",
    "model/vendor/spider_xhs/v5/trends_bridge.js": "37152cb6c704da670f95df066f0b4e665588610eb1836daaaf05754c5ec81cd7",
}
V5_CAPTURE_TOOLS = ("tools/item33_trends_runtime_capture.py", "tools/item33_trends_dml_capture.py")
V5_CAPTURE_ROOT = Path("/var/lib/noteai/item33-trends-promotion/capture")
V5_CAPTURE_LAUNCHER_PATH = "scripts/render_run_market_timing.sh"
V5_CAPTURE_LAUNCHER = (
    "#!/bin/sh\nset -eu\n"
    "exec python3 -E -B /app/tools/item33_trends_runtime_capture.py --worker "
    "--config /run/noteai-item33/capture-config.json -- --daemon --interval 360\n"
).encode("ascii")
V5_PROMOTED_UNIT_SHA256 = "0a613724bb4f30fd914a8463ecb1ae866661941468757e5dc03ffefbc1eaa87e"
V5_NORMAL_UNIT_SHA256 = "94da6db2f3746e6fb74d3447757bb80cec546512e2116b2713124ccbc8cda47f"
PROVIDER_REQUEST_LIMIT = 34
ENDPOINTS = ("homefeed", "search_recommend", "search_notes")
AUTHORIZATION_SCHEMA = "noteai.item33.execution_authorization.v1"
RESULT_SCHEMA = "noteai.item33.execution_result.v1"
ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST_REF = "deploy/production/internal-deployment-readiness.json"
DEPENDENCY_EVIDENCE_REFS = {
    "real_xhs_trends": (
        "deploy/production/evidence/"
        "production-item32-xhs-trends-readonly-verified.json"
    ),
    "internal_failure_rollback": (
        "deploy/production/evidence/"
        "production-internal-failure-rollback-verified-20260814.json"
    ),
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PREFLIGHT_FRESHNESS = timedelta(minutes=5)


class Item33ExecutionError(RuntimeError):
    """Stable failure code that never includes callback or Secret content."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def render_managed_unit(suspended: bytes, *, runtime_profile: str | None = None, normal: bool = False) -> bytes:
    """Prepare the exact legacy or accepted V5 singleton and capture entry.

    Pure byte transformation: no filesystem writes, host calls or new run. The
    unmodified suspended bytes remain the exact rollback, including the image.
    """
    if hashlib.sha256(suspended).hexdigest() != SUSPENDED_UNIT_SHA256:
        raise Item33ExecutionError("suspended_unit_binding")
    source = suspended.decode("utf-8")
    anchor = " --env-file=/etc/noteai/xhs-trends.env"
    suspended_flag = "NOTEAI_XHS_COLLECTION_SUSPENDED=1"
    if source.count(anchor) != 1 or source.count(suspended_flag) != 1:
        raise Item33ExecutionError("suspended_unit_shape")
    if runtime_profile not in {None, V5_PROFILE} or (normal and runtime_profile != V5_PROFILE):
        raise Item33ExecutionError("runtime_profile_binding")
    root = V5_RUNTIME_OVERLAY_ROOT if runtime_profile else RUNTIME_OVERLAY_ROOT
    sources = V5_RUNTIME_OVERLAY_SHA256 if runtime_profile else RUNTIME_OVERLAY_SHA256
    mounts = "".join(
        f" --mount=type=bind,src={root / name},dst=/app/{name},readonly"
        for name in sources
    )
    if runtime_profile:
        old_image = "sha256:a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec"
        old_command = "python market_timing_worker.py --daemon --interval 360"
        if source.count(old_image) != 2 or source.count(old_command) != 1:
            raise Item33ExecutionError("suspended_unit_shape")
        source = source.replace(old_image, "sha256:" + V5_IMAGE_CONFIG_SHA256)
        if not normal:
            source = source.replace(old_command, "/app/scripts/render_run_market_timing.sh")
            for name in (*V5_CAPTURE_TOOLS, V5_CAPTURE_LAUNCHER_PATH):
                mounts += f" --mount=type=bind,src={root / name},dst=/app/{name},readonly"
            mounts += (
                f" --mount=type=bind,src={V5_CAPTURE_ROOT / 'runtime-config.json'},dst=/run/noteai-item33/capture-config.json,readonly"
                f" --mount=type=bind,src={V5_CAPTURE_ROOT / 'capture.sock'},dst=/run/noteai-item33/capture.sock,readonly"
            )
        mounts += (
            " --env=NOTEAI_XHS_PROTOCOL=pc_v5"
            " '--env=NOTEAI_XHS_V5_BUDGET_JSON={\"initialization\":2,\"collection\":34,\"total\":36}'"
        )
    candidate = source.replace(anchor, mounts + anchor).replace(
        suspended_flag, "NOTEAI_XHS_COLLECTION_SUSPENDED=0"
    ).encode("utf-8")
    if hashlib.sha256(candidate).hexdigest() != promoted_unit_sha256(runtime_profile, normal=normal):
        raise Item33ExecutionError("promoted_unit_binding")
    return candidate



def promoted_unit_sha256(runtime_profile: str | None = None, *, normal: bool = False) -> str:
    if runtime_profile not in {None, V5_PROFILE} or (normal and runtime_profile != V5_PROFILE):
        raise Item33ExecutionError("runtime_profile_binding")
    return V5_NORMAL_UNIT_SHA256 if normal else V5_PROMOTED_UNIT_SHA256 if runtime_profile else PROMOTED_UNIT_SHA256


def _runtime_profile(dependencies: Mapping[str, Any]) -> str | None:
    profile = dependencies["real_xhs_trends"].get("runtime_profile")
    promoted_unit_sha256(profile)
    return profile


def _validate_capture_binding(value: Any, activation: str) -> Mapping[str, Any]:
    binding = _mapping(value, "capture_binding")
    _exact_keys(binding, {"source_sha256", "launcher_sha256", "configuration_sha256", "activation_identity_sha256"}, "capture_binding")
    if binding["activation_identity_sha256"] != activation:
        raise Item33ExecutionError("capture_binding")
    sources = _mapping(binding["source_sha256"], "capture_binding")
    _exact_keys(sources, set(V5_CAPTURE_TOOLS), "capture_binding")
    for digest in sources.values():
        _sha256(digest, "capture_binding")
    if binding["launcher_sha256"] != hashlib.sha256(V5_CAPTURE_LAUNCHER).hexdigest():
        raise Item33ExecutionError("capture_binding")
    _sha256(binding["configuration_sha256"], "capture_binding")
    return binding


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Item33ExecutionError(code)
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], code: str) -> None:
    if set(value) != keys:
        raise Item33ExecutionError(code)


def _exact_int(value: Any, code: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise Item33ExecutionError(code)
    return value


def _sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Item33ExecutionError(code)
    return value


def _clock(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise Item33ExecutionError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Item33ExecutionError(code) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Item33ExecutionError(code)
    return parsed.astimezone(timezone.utc)


def _trusted_now(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        raise Item33ExecutionError("execution_clock") from None
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Item33ExecutionError("execution_clock")
    return value.astimezone(timezone.utc)


def _invoke(
    callback: Callable[..., Mapping[str, Any]],
    code: str,
    *args: Any,
) -> Mapping[str, Any]:
    try:
        value = callback(*args)
    except Exception:
        raise Item33ExecutionError(f"{code}_outcome_unknown") from None
    return _mapping(value, code)


DEPENDENCY_VALIDATION_REF = "deploy/production/evidence/item33-dependency-validation.json"
DEPENDENCY_VALIDATION_SHA256 = "1dd9cc4a673653608263f836d3e103532918851987287be93af0b1285018d039"


def _validate_retained_rollback(control: Mapping[str, Any], payload: Mapping[str, Any], raw: bytes) -> None:
    """Reuse the original locally verified Git proof through its pinned bytes.

    F's source-only package cannot re-run historical Git ancestry. This receipt
    is the immutable output of the real original single-item validator, not a
    caller-supplied substitute for its result.
    """
    receipt_raw = (ROOT / DEPENDENCY_VALIDATION_REF).read_bytes()
    if hashlib.sha256(receipt_raw).hexdigest() != DEPENDENCY_VALIDATION_SHA256:
        raise ValueError("dependency receipt binding")
    receipt = json.loads(receipt_raw)
    if (receipt["status"] != "VERIFIED" or receipt["validation_errors"] != []
        or receipt["control_id"] != "internal_failure_rollback"
        or receipt["manifest_evidence"] != control["evidence"]
        or receipt["evidence_ref"] != DEPENDENCY_EVIDENCE_REFS["internal_failure_rollback"]
        or receipt["evidence_sha256"] != hashlib.sha256(raw).hexdigest()
        or receipt["validator_sha256"] != hashlib.sha256((ROOT / receipt["validator_ref"]).read_bytes()).hexdigest()
        or payload.get("status") != "VERIFIED_RECONCILED"
        or payload.get("source_binding") != receipt["source_binding"]
        or payload.get("terminal_acceptance_sha256") != receipt["terminal_acceptance_sha256"]):
        raise ValueError("dependency original evidence changed")


def _load_verified_dependencies() -> dict[str, dict[str, Any]]:
    """Bind admission to the validated canonical readiness ledger on disk."""

    try:
        import internal_deployment_readiness_gate as readiness_gate

        manifest_path = ROOT / CANONICAL_MANIFEST_REF
        manifest = readiness_gate.load_manifest(manifest_path)
        rows = [control for layer in manifest["layers"] for control in layer["controls"]]
        if any(sum(row.get("id") == name for row in rows) != 1 for name in DEPENDENCY_EVIDENCE_REFS):
            raise ValueError("dependency control identity")
        controls = {control["id"]: control for control in rows}
        verified: dict[str, dict[str, Any]] = {}
        for control_id, evidence_ref in DEPENDENCY_EVIDENCE_REFS.items():
            control = controls[control_id]
            evidence = control["evidence"]
            if (
                control["status"] != "verified"
                or not isinstance(evidence, list)
                or {"kind": "path", "ref": evidence_ref} not in evidence
            ):
                raise ValueError("unverified dependency")
            evidence_path = ROOT / evidence_ref
            raw = evidence_path.read_bytes()
            payload = json.loads(raw)
            if control_id == "real_xhs_trends":
                if readiness_gate.validate_item32_trends_evidence(control, root=ROOT):
                    raise ValueError("Item32 semantic evidence")
            else:
                _validate_retained_rollback(control, payload, raw)
            verified[control_id] = {
                "verified": True,
                "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            }
            if control_id == "real_xhs_trends":
                bucket = payload["successor"]["budget"]["bucket_date"]
                if date.fromisoformat(bucket).isoformat() != bucket:
                    raise ValueError("invalid Item32 bucket")
                verified[control_id]["terminal_bucket_date"] = bucket
                if payload.get("successor", {}).get("runtime_readback", {}).get("protocol") == "pc_v5":
                    execution = payload.get("execution", {})
                    if (verified[control_id]["evidence_sha256"] != V5_ITEM32_TERMINAL_SHA256
                        or execution.get("source_sha256") != V5_RUNTIME_OVERLAY_SHA256
                        or execution.get("image_config_sha256") != V5_IMAGE_CONFIG_SHA256
                        or execution.get("registry_manifest_sha256") != V5_REGISTRY_MANIFEST_SHA256
                        or payload["successor"]["runtime_readback"].get("runtime_overlay_sha256") != V5_RUNTIME_OVERLAY_SHA256):
                        raise ValueError("Item32 V5 runtime binding")
                    verified[control_id]["runtime_profile"] = V5_PROFILE
        return verified
    except Exception:
        raise Item33ExecutionError("dependency_unverified") from None


def _validate_dependencies(
    value: Any,
    trusted: Mapping[str, Any],
) -> date:
    dependencies = _mapping(value, "dependencies")
    _exact_keys(
        dependencies,
        {"real_xhs_trends", "internal_failure_rollback"},
        "dependencies",
    )
    for control_id, dependency in dependencies.items():
        item = _mapping(dependency, "dependencies")
        expected_keys = {"verified", "evidence_sha256"}
        if control_id == "real_xhs_trends":
            expected_keys.add("terminal_bucket_date")
            if trusted.get(control_id, {}).get("runtime_profile") == V5_PROFILE:
                expected_keys.add("runtime_profile")
        _exact_keys(item, expected_keys, "dependencies")
        if item["verified"] is not True:
            raise Item33ExecutionError("dependency_unverified")
        _sha256(item["evidence_sha256"], "dependencies")
        if item != trusted.get(control_id):
            raise Item33ExecutionError("dependency_unverified")
    try:
        bucket = date.fromisoformat(
            dependencies["real_xhs_trends"]["terminal_bucket_date"]
        )
    except (KeyError, TypeError, ValueError):
        raise Item33ExecutionError("dependency_unverified") from None
    if bucket.isoformat() != dependencies["real_xhs_trends"][
        "terminal_bucket_date"
    ]:
        raise Item33ExecutionError("dependency_unverified")
    return bucket


def _validate_preflight(
    value: Any,
    *,
    now: datetime,
) -> tuple[Mapping[str, Any], int, str, datetime]:
    preflight = _mapping(value, "preflight")
    _exact_keys(
        preflight,
        {
            "observed_at",
            "canonical_sha256",
            "database_role",
            "role_exact",
            "acl_exact",
            "unit_sha256",
            "unit_active",
            "unit_sub",
            "unit_enabled",
            "collection_suspended",
            "formal_container_count",
            "active_run_count",
            "same_bucket_run_count",
            "outcome_unknown_count",
            "unlinked_attempt_count",
            "utc_provider_budget_used_before",
            "utc_provider_budget_remaining_before",
            "provider_calls",
            "production_database_writes",
        },
        "preflight",
    )
    observed_at = _clock(preflight["observed_at"], "preflight_clock")
    used = _exact_int(
        preflight["utc_provider_budget_used_before"], "preflight_budget"
    )
    remaining = _exact_int(
        preflight["utc_provider_budget_remaining_before"],
        "preflight_budget",
    )
    if (
        not observed_at <= now <= observed_at + _PREFLIGHT_FRESHNESS
        or observed_at.date() != now.date()
        or preflight["database_role"] != "noteai_xhs_trends"
        or preflight["role_exact"] is not True
        or preflight["acl_exact"] is not True
        or preflight["unit_sha256"] != SUSPENDED_UNIT_SHA256
        or preflight["unit_active"] != "inactive"
        or preflight["unit_sub"] != "dead"
        or preflight["unit_enabled"] != "disabled"
        or preflight["collection_suspended"] is not True
        or any(
            _exact_int(preflight[field], "preflight") != 0
            for field in (
                "formal_container_count",
                "active_run_count",
                "same_bucket_run_count",
                "outcome_unknown_count",
                "unlinked_attempt_count",
                "provider_calls",
                "production_database_writes",
            )
        )
        or used != 0
        or remaining != PROVIDER_REQUEST_LIMIT
    ):
        raise Item33ExecutionError("preflight")
    return (
        preflight,
        remaining,
        _sha256(preflight["canonical_sha256"], "preflight"),
        observed_at,
    )


def _validate_cycle(
    value: Any,
    *,
    run_identity: str | None,
    bucket_key: str,
    remaining: int,
    not_before: datetime,
    activation_identity: str | None = None,
) -> tuple[Mapping[str, Any], datetime]:
    receipt = _mapping(value, "cycle")
    _exact_keys(
        receipt,
        {
            "run_identity_sha256",
            "bucket_key",
            "started_at",
            "completed_at",
            "lease_expires_at",
            "cycle_count",
            "same_bucket_completed_run_count",
            "provider_request_count",
            "provider_request_succeeded",
            "provider_request_failed",
            "outcome_unknown_count",
            "automatic_retry_count",
            "active_admitted_count",
            "challenge_detected",
            "endpoint_counts",
            "published_keyword_count",
            "minimum_real_keyword_count_per_domain",
            "search_result_domain_count",
            "search_recommend_domain_count",
            "quality_snapshot_verified",
            "production_write_set_verified",
            "post_cycle_health",
            "canonical_result_sha256",
        } | ({"activation_identity_sha256", "physical_http", "attempts"} if activation_identity else set()),
        "cycle",
    )
    actual_run = _sha256(receipt["run_identity_sha256"], "cycle")
    if activation_identity and (receipt["activation_identity_sha256"] != activation_identity
        or actual_run == activation_identity):
        raise Item33ExecutionError("cycle")
    request_count = _exact_int(
        receipt["provider_request_count"], "cycle", minimum=1
    )
    started_at = _clock(receipt["started_at"], "cycle")
    completed_at = _clock(receipt["completed_at"], "cycle")
    lease_expires_at = _clock(receipt["lease_expires_at"], "cycle")
    endpoint_counts = receipt["endpoint_counts"]
    endpoints_valid = (
        isinstance(endpoint_counts, Mapping)
        and set(endpoint_counts) == set(ENDPOINTS)
        and all(
            _exact_int(value, "cycle") >= 0
            for value in endpoint_counts.values()
        )
        and sum(endpoint_counts.values()) == request_count
        and endpoint_counts["search_recommend"] > 0
        and endpoint_counts["search_notes"] > 0
    )
    if (
        (run_identity is not None and actual_run != run_identity)
        or receipt["bucket_key"] != bucket_key
        or not_before > started_at
        or started_at > completed_at
        or lease_expires_at != started_at + timedelta(minutes=30)
        or completed_at > lease_expires_at
        or completed_at.date().isoformat() != bucket_key
        or _exact_int(receipt["cycle_count"], "cycle") != 1
        or _exact_int(receipt["same_bucket_completed_run_count"], "cycle")
        != 1
        or request_count > remaining
        or _exact_int(receipt["provider_request_succeeded"], "cycle")
        != request_count
        or _exact_int(receipt["provider_request_failed"], "cycle") != 0
        or _exact_int(receipt["outcome_unknown_count"], "cycle") != 0
        or _exact_int(receipt["automatic_retry_count"], "cycle") != 0
        or _exact_int(receipt["active_admitted_count"], "cycle") != 0
        or receipt["challenge_detected"] is not False
        or not endpoints_valid
        or not 72
        <= _exact_int(receipt["published_keyword_count"], "cycle")
        <= 90
        or not 12
        <= _exact_int(
            receipt["minimum_real_keyword_count_per_domain"], "cycle"
        )
        <= 15
        or _exact_int(receipt["search_result_domain_count"], "cycle") != 6
        or _exact_int(receipt["search_recommend_domain_count"], "cycle")
        != 6
        or receipt["quality_snapshot_verified"] is not True
        or receipt["production_write_set_verified"] is not True
        or receipt["post_cycle_health"] != "ready"
    ):
        raise Item33ExecutionError("cycle")
    if activation_identity:
        import internal_deployment_readiness_gate as readiness_gate
        physical = _mapping(receipt["physical_http"], "cycle_physical_http")
        summary = {key: value for key, value in physical.items() if key != "observations"}
        attempts = receipt["attempts"]
        if (request_count != 34 or endpoint_counts != {"homefeed": 10, "search_recommend": 12, "search_notes": 12}
            or not isinstance(attempts, list) or len(attempts) != 34
            or any(not isinstance(item, Mapping) or set(item) != {
                       "attempt_identity_sha256", "ordinal", "endpoint", "status", "admitted_at", "completed_at"}
                   or item.get("ordinal") != index or type(item.get("ordinal")) is not int
                   or not isinstance(item.get("attempt_identity_sha256"), str)
                   or not _SHA256.fullmatch(item["attempt_identity_sha256"])
                   or not started_at <= _clock(item["admitted_at"], "cycle_physical_http")
                      <= _clock(item["completed_at"], "cycle_physical_http") <= completed_at
                   for index, item in enumerate(attempts, 1))
            or len({item["attempt_identity_sha256"] for item in attempts}) != 34
            or not readiness_gate._item32_v5_physical_valid(
                physical, summary, attempts, started_at, completed_at)):
            raise Item33ExecutionError("cycle_physical_http")
    _sha256(receipt["canonical_result_sha256"], "cycle")
    return receipt, completed_at


def _validate_action(
    value: Any,
    *,
    phase: str,
    expected_before: str,
    expected_after: str,
) -> Mapping[str, Any]:
    receipt = _mapping(value, phase)
    _exact_keys(
        receipt,
        {
            "phase",
            "status",
            "unit_name",
            "before_unit_sha256",
            "after_unit_sha256",
            "mutation_count",
            "other_unit_actions",
            "provider_calls",
            "production_database_writes",
            "canonical_result_sha256",
        } | ({"started_at", "completed_at"} if phase == "normal_handoff" else set()),
        phase,
    )
    if (
        receipt["phase"] != phase
        or receipt["status"] != "applied"
        or receipt["unit_name"] != UNIT_NAME
        or receipt["before_unit_sha256"] != expected_before
        or receipt["after_unit_sha256"] != expected_after
        or any(
            _exact_int(receipt[field], phase) != expected
            for field, expected in (
                ("mutation_count", 1),
                ("other_unit_actions", 0),
                ("provider_calls", 0),
                ("production_database_writes", 0),
            )
        )
    ):
        raise Item33ExecutionError(phase)
    _sha256(receipt["canonical_result_sha256"], phase)
    if phase == "normal_handoff" and _clock(receipt["started_at"], phase) > _clock(receipt["completed_at"], phase):
        raise Item33ExecutionError(phase)
    return receipt


def _validate_state(
    value: Any,
    *,
    phase: str,
    active: bool,
    not_before: datetime,
    expected_attempt_count: int | None,
    allow_unresolved: bool = False,
    runtime_profile: str | None = None,
    activation_identity: str | None = None,
    run_identity: str | None = None,
) -> tuple[Mapping[str, Any], datetime]:
    state = _mapping(value, f"{phase}_readback")
    exact_keys = {
        "phase",
        "observed_at",
        "canonical_sha256",
        "unit_sha256",
        "unit_active",
        "unit_sub",
        "unit_enabled",
        "collection_suspended",
        "formal_unit_count",
        "formal_container_count",
        "process_count",
        "active_run_count",
        "active_attempt_count",
        "outcome_unknown_count",
        "unlinked_attempt_count",
        "health",
        "provider_calls",
        "production_database_writes",
        "task_container_count",
        "inspection_container_count",
        "stage_directory_count",
        "runtime_directory_count",
        "temporary_unit_count",
        "temporary_dropin_count",
    }
    if runtime_profile:
        exact_keys |= {"activation_identity_sha256", "run_identity_sha256"}
    if phase in {"rollback", "final"}:
        exact_keys |= {
            "preserved_run_count",
            "preserved_attempt_count",
            "preserved_snapshot_count",
            "database_audit_deletes",
            "same_bucket_new_run_delta",
            "same_bucket_provider_call_delta",
        }
    _exact_keys(
        state,
        exact_keys,
        f"{phase}_readback",
    )
    expected = {
        "unit_sha256": promoted_unit_sha256(runtime_profile) if active else SUSPENDED_UNIT_SHA256,
        "unit_active": "active" if active else "inactive",
        "unit_sub": "running" if active else "dead",
        "unit_enabled": "enabled" if active else "disabled",
        "collection_suspended": not active,
        "formal_unit_count": 1,
        "formal_container_count": 1 if active else 0,
        "process_count": 1 if active else 0,
        "health": "ready" if active else "stopped",
    }
    if runtime_profile:
        expected["activation_identity_sha256"] = activation_identity
        if run_identity is not None:
            expected["run_identity_sha256"] = run_identity
        elif state["run_identity_sha256"] is not None:
            _sha256(state["run_identity_sha256"], f"{phase}_readback")
    for field in (
        "formal_unit_count",
        "formal_container_count",
        "process_count",
    ):
        _exact_int(state[field], f"{phase}_readback")
    zero_counts = {
        "active_run_count",
        "active_attempt_count",
        "outcome_unknown_count",
        "unlinked_attempt_count",
        "provider_calls",
        "production_database_writes",
        "task_container_count",
        "inspection_container_count",
        "stage_directory_count",
        "runtime_directory_count",
        "temporary_unit_count",
        "temporary_dropin_count",
    }
    for field in zero_counts:
        value = _exact_int(state[field], f"{phase}_readback")
        if not allow_unresolved or field not in {
            "active_run_count",
            "active_attempt_count",
            "outcome_unknown_count",
            "unlinked_attempt_count",
        }:
            expected[field] = 0
        elif value > PROVIDER_REQUEST_LIMIT:
            raise Item33ExecutionError(f"{phase}_readback")
    if phase in {"rollback", "final"} and expected_attempt_count is not None:
        for field in (
            "preserved_run_count",
            "preserved_attempt_count",
            "preserved_snapshot_count",
            "database_audit_deletes",
            "same_bucket_new_run_delta",
            "same_bucket_provider_call_delta",
        ):
            _exact_int(state[field], f"{phase}_readback")
        expected.update(
            {
                "preserved_run_count": 1,
                "preserved_attempt_count": expected_attempt_count,
                "preserved_snapshot_count": 1,
                "database_audit_deletes": 0,
                "same_bucket_new_run_delta": 0,
                "same_bucket_provider_call_delta": 0,
            }
        )
    elif phase in {"rollback", "final"}:
        for field in (
            "preserved_run_count",
            "preserved_attempt_count",
            "preserved_snapshot_count",
            "database_audit_deletes",
            "same_bucket_new_run_delta",
            "same_bucket_provider_call_delta",
        ):
            _exact_int(state[field], f"{phase}_readback")
        expected.update(
            {
                "database_audit_deletes": 0,
                "same_bucket_new_run_delta": 0,
                "same_bucket_provider_call_delta": 0,
            }
        )
    if state["phase"] != phase or any(
        state.get(key) != expected_value for key, expected_value in expected.items()
    ) or state["collection_suspended"] is not (not active):
        raise Item33ExecutionError(f"{phase}_readback")
    observed_at = _clock(state["observed_at"], f"{phase}_readback")
    if observed_at < not_before:
        raise Item33ExecutionError(f"{phase}_readback")
    _sha256(state["canonical_sha256"], f"{phase}_readback")
    return state, observed_at


def execute_item33_promotion(
    *,
    dependencies: Mapping[str, Any],
    run_identity_sha256: str | None = None,
    activation_identity_sha256: str | None = None,
    capture_binding: Mapping[str, Any] | None = None,
    read_preflight: Callable[[], Mapping[str, Any]],
    read_single_cycle: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    promote_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    read_promoted: Callable[[], Mapping[str, Any]],
    rollback_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    read_rollback: Callable[[], Mapping[str, Any]],
    reapply_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    read_final: Callable[[], Mapping[str, Any]],
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    """Run one cycle and one managed promote/rollback/reapply sequence.

    An exception from any callback means the action outcome is UNKNOWN.  The
    controller never retries it or guesses whether another mutation is safe.
    A known post-promotion validation failure receives one rollback attempt;
    rollback or reapply failures remain sealed for read-only reconciliation.
    """

    trusted_dependencies = _load_verified_dependencies()
    item32_bucket = _validate_dependencies(dependencies, trusted_dependencies)
    runtime_profile = _runtime_profile(trusted_dependencies)
    promoted_sha = promoted_unit_sha256(runtime_profile)
    identity_field = "activation_identity_sha256" if runtime_profile else "run_identity_sha256"
    if runtime_profile:
        if run_identity_sha256 is not None:
            raise Item33ExecutionError("run_identity_must_be_observed")
        action_identity = _sha256(activation_identity_sha256, "activation_identity")
        capture_binding = _validate_capture_binding(capture_binding, action_identity)
    else:
        if activation_identity_sha256 is not None or capture_binding is not None:
            raise Item33ExecutionError("runtime_profile_binding")
        action_identity = _sha256(run_identity_sha256, "run_identity")
    run_identity = None if runtime_profile else action_identity
    admission_now = _trusted_now(clock)
    if admission_now.date() <= item32_bucket:
        raise Item33ExecutionError("utc_budget_not_available")
    preflight_value = _invoke(read_preflight, "preflight")
    now = _trusted_now(clock)
    preflight, remaining, preflight_sha, preflight_at = _validate_preflight(
        preflight_value, now=now
    )
    bucket_key = now.date().isoformat()
    authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        identity_field: action_identity,
        "bucket_key": bucket_key,
        "previous_item32_bucket_key": item32_bucket.isoformat(),
        "provider_request_limit": PROVIDER_REQUEST_LIMIT,
        "provider_request_budget_remaining": remaining,
        "permitted_endpoints": list(ENDPOINTS),
        "cycle_count": 1,
        "automatic_retry_limit": 0,
        "expected_unit_sha256": SUSPENDED_UNIT_SHA256,
        "preflight_sha256": preflight_sha,
    }
    if runtime_profile:
        authorization.update(runtime_profile=runtime_profile, initialization_limit=2, physical_http_limit=36,
                             capture_binding=dict(capture_binding))
    promotion_authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        "unit_name": UNIT_NAME,
        identity_field: action_identity,
        "cycle_authorization": authorization,
        "controller_provider_calls_permitted": 0,
        "controller_database_writes_permitted": 0,
        "other_unit_actions_permitted": 0,
        "automatic_retry_limit": 0,
    }
    recovery_authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        "unit_name": UNIT_NAME,
        identity_field: action_identity,
        "provider_calls_permitted": 0,
        "production_database_writes_permitted": 0,
        "other_unit_actions_permitted": 0,
        "automatic_retry_limit": 0,
    }

    if runtime_profile:
        promotion_authorization["capture_binding"] = dict(capture_binding)
        recovery_authorization["capture_binding"] = dict(capture_binding)
    promotion_known = False
    rollback_started = False
    try:
        promotion = _validate_action(
            _invoke(promote_unit, "promotion", promotion_authorization),
            phase="promotion",
            expected_before=SUSPENDED_UNIT_SHA256,
            expected_after=promoted_sha,
        )
        promotion_known = True
        cycle, cycle_completed_at = _validate_cycle(
            _invoke(read_single_cycle, "cycle", authorization),
            run_identity=run_identity,
            bucket_key=bucket_key,
            remaining=remaining,
            not_before=now,
            activation_identity=action_identity if runtime_profile else None,
        )
        run_identity = cycle["run_identity_sha256"]
        request_count = int(cycle["provider_request_count"])
        promoted, promoted_at = _validate_state(
            _invoke(read_promoted, "promoted_readback"),
            runtime_profile=runtime_profile, activation_identity=action_identity if runtime_profile else None,
            run_identity=run_identity,
            phase="promoted",
            active=True,
            not_before=cycle_completed_at,
            expected_attempt_count=request_count,
        )
    except Item33ExecutionError:
        if not promotion_known:
            raise
        rollback_started = True
        try:
            _validate_action(
                _invoke(rollback_unit, "rollback", recovery_authorization),
                phase="rollback",
                expected_before=promoted_sha,
                expected_after=SUSPENDED_UNIT_SHA256,
            )
            _validate_state(
                _invoke(read_rollback, "rollback_readback"),
                runtime_profile=runtime_profile, activation_identity=action_identity if runtime_profile else None,
                run_identity=run_identity,
                phase="rollback",
                active=False,
                not_before=preflight_at,
                expected_attempt_count=(
                    int(cycle["provider_request_count"])
                    if "cycle" in locals()
                    else None
                ),
                allow_unresolved="cycle" not in locals(),
            )
        except Item33ExecutionError:
            raise Item33ExecutionError("recovery_failed") from None
        raise

    rollback_started = True
    rollback = _validate_action(
        _invoke(rollback_unit, "rollback", recovery_authorization),
        phase="rollback",
        expected_before=promoted_sha,
        expected_after=SUSPENDED_UNIT_SHA256,
    )
    rollback_state, rollback_at = _validate_state(
        _invoke(read_rollback, "rollback_readback"),
        runtime_profile=runtime_profile, activation_identity=action_identity if runtime_profile else None,
        run_identity=run_identity,
        phase="rollback",
        active=False,
        not_before=promoted_at,
        expected_attempt_count=request_count,
    )
    reapply = _validate_action(
        _invoke(reapply_unit, "reapply", recovery_authorization),
        phase="reapply",
        expected_before=SUSPENDED_UNIT_SHA256,
        expected_after=promoted_sha,
    )
    final, final_at = _validate_state(
        _invoke(read_final, "final_readback"),
        runtime_profile=runtime_profile, activation_identity=action_identity if runtime_profile else None,
        run_identity=run_identity,
        phase="final",
        active=True,
        not_before=rollback_at,
        expected_attempt_count=request_count,
    )
    observed_at = _trusted_now(clock)
    if observed_at < now or observed_at < final_at:
        raise Item33ExecutionError("execution_clock")
    return {
        "schema": RESULT_SCHEMA,
        "status": "VERIFIED",
        "readiness_credit": False,
        "observed_at": observed_at.isoformat(),
        "run_identity_sha256": run_identity,
        **({"activation_identity_sha256": action_identity, "capture_binding": dict(capture_binding)} if runtime_profile else {}),
        "bucket_key": bucket_key,
        "authorization": authorization,
        "preflight": dict(preflight),
        "cycle": dict(cycle),
        "promotion": dict(promotion),
        "promoted_readback": dict(promoted),
        "rollback": dict(rollback),
        "rollback_readback": dict(rollback_state),
        "reapply": dict(reapply),
        "final_readback": dict(final),
        "action_counts": {
            "cycle": 1,
            "promotion": 1,
            "rollback": 1 if rollback_started else 0,
            "reapply": 1,
            "automatic_retry": 0,
        },
        "secret_values_recorded": False,
    }


NORMAL_ACTION_REF = "deploy/production/evidence/production-item33-trends-normal-handoff-action.json"
NORMAL_READBACK_REF = "deploy/production/evidence/production-item33-trends-normal-handoff-readback.json"


def _normal_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _validate_capture_seal(binding: Mapping[str, Any], run_identity: str, bucket: str,
                           seal_raw: bytes, journal: bytes) -> Mapping[str, Any]:
    try:
        import item33_trends_runtime_capture as capture
        if not isinstance(seal_raw, bytes) or not 0 < len(seal_raw) < 2 * 1024 * 1024:
            raise ValueError("capture size")
        seal = json.loads(seal_raw)
        if (seal.get("activation_identity_sha256") != binding["activation_identity_sha256"]
            or seal.get("run_identity_sha256") != run_identity or seal.get("bucket_key") != bucket
            or seal.get("config_sha256") != binding["configuration_sha256"]
            or seal.get("accepted_source_sha256") != V5_RUNTIME_OVERLAY_SHA256
            or seal.get("instrumentation_sha256") != {**binding["source_sha256"], V5_CAPTURE_LAUNCHER_PATH: binding["launcher_sha256"]}):
            raise ValueError("capture binding")
        capture.verify_capture_artifacts(seal, journal, require_terminal_proofs=True)
        return seal
    except Exception:
        raise Item33ExecutionError("normal_capture_unverified") from None


def _validate_teardown(teardown_raw: bytes, seal_raw: bytes, journal: bytes, *, not_after: datetime) -> Mapping[str, Any]:
    try:
        import item33_trends_capture_teardown as teardown
        if not isinstance(teardown_raw, bytes) or not 0 < len(teardown_raw) < 4 * 1024 * 1024:
            raise ValueError("teardown size")
        proof = json.loads(teardown_raw)
        source_sha = hashlib.sha256((ROOT / teardown.SOURCE_REF).read_bytes()).hexdigest()
        teardown.verify_teardown_proof(proof, seal_raw=seal_raw, journal=journal, source_sha256=source_sha)
        if _clock(proof["after"]["observed_at"], "normal_teardown_unverified") > not_after:
            raise ValueError("teardown time")
        return proof
    except Exception:
        raise Item33ExecutionError("normal_teardown_unverified") from None


def execute_item33_normal_handoff(*, dependencies: Mapping[str, Any], previous_result: Mapping[str, Any],
                                  preserved: Mapping[str, Any], capture_seal_raw: bytes, capture_journal: bytes, teardown_raw: bytes,
                                  handoff_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
                                  read_normal: Callable[[], Mapping[str, Any]], clock: Callable[[], datetime]) -> dict[str, Any]:
    """One same-bucket handoff after the instrumented rehearsal and real seal.

    A callback exception remains UNKNOWN and is never retried here. No new
    collection is requested. The original rehearsal result remains separate.
    """
    trusted = _load_verified_dependencies()
    prior_bucket = _validate_dependencies(dependencies, trusted)
    if _runtime_profile(trusted) != V5_PROFILE:
        raise Item33ExecutionError("normal_profile")
    prior = _mapping(previous_result, "normal_previous_result")
    activation = _sha256(prior.get("activation_identity_sha256"), "normal_activation")
    run_identity = _sha256(prior.get("run_identity_sha256"), "normal_run")
    binding = _validate_capture_binding(prior.get("capture_binding"), activation)
    now = _trusted_now(clock)
    bucket = prior.get("bucket_key")
    if (prior.get("schema") != RESULT_SCHEMA or prior.get("status") != "VERIFIED"
        or prior.get("readiness_credit") is not False or run_identity == activation
        or bucket != now.date().isoformat() or now.date() <= prior_bucket
        or prior.get("action_counts") != {"cycle": 1, "promotion": 1, "rollback": 1, "reapply": 1, "automatic_retry": 0}):
        raise Item33ExecutionError("normal_previous_result")
    cycle, completed = _validate_cycle(prior.get("cycle"), run_identity=run_identity, bucket_key=bucket,
        remaining=34, not_before=_clock(prior.get("cycle", {}).get("started_at"), "cycle"), activation_identity=activation)
    _, prior_final_at = _validate_state(prior.get("final_readback"), phase="final", active=True,
        not_before=completed, expected_attempt_count=34, runtime_profile=V5_PROFILE,
        activation_identity=activation, run_identity=run_identity)
    if now < prior_final_at:
        raise Item33ExecutionError("normal_previous_result")
    preserved = dict(_mapping(preserved, "normal_preserved"))
    _exact_keys(preserved, {"run_count", "attempt_count", "snapshot_count", "run_sha256", "attempt_ledger_sha256", "snapshot_sha256"}, "normal_preserved")
    for key, value in (("run_count", 1), ("attempt_count", 34), ("snapshot_count", 1)):
        if _exact_int(preserved[key], "normal_preserved") != value:
            raise Item33ExecutionError("normal_preserved")
    for key in ("run_sha256", "attempt_ledger_sha256", "snapshot_sha256"):
        _sha256(preserved[key], "normal_preserved")
    _validate_capture_seal(binding, run_identity, bucket, capture_seal_raw, capture_journal)
    _validate_teardown(teardown_raw, capture_seal_raw, capture_journal, not_after=now)
    teardown_sha = hashlib.sha256(teardown_raw).hexdigest()
    receipt_sha = hashlib.sha256(capture_seal_raw).hexdigest()
    authorization = {"schema": AUTHORIZATION_SCHEMA, "unit_name": UNIT_NAME,
        "activation_identity_sha256": activation, "run_identity_sha256": run_identity,
        "bucket_key": bucket, "capture_binding": dict(binding), "capture_receipt_sha256": receipt_sha,
        "teardown_sha256": teardown_sha,
        "provider_calls_permitted": 0, "production_database_writes_permitted": 0,
        "other_unit_actions_permitted": 0, "automatic_retry_limit": 0}
    if _trusted_now(clock).date().isoformat() != bucket:
        raise Item33ExecutionError("normal_bucket_expired")
    action = _validate_action(_invoke(handoff_unit, "normal_handoff", authorization), phase="normal_handoff",
        expected_before=V5_PROMOTED_UNIT_SHA256, expected_after=V5_NORMAL_UNIT_SHA256)
    action_started = _clock(action["started_at"], "normal_handoff")
    action_completed = _clock(action["completed_at"], "normal_handoff")
    if not now <= action_started <= action_completed <= _trusted_now(clock) or action_completed.date().isoformat() != bucket:
        raise Item33ExecutionError("normal_handoff")
    readback = _invoke(read_normal, "normal_readback")
    _exact_keys(readback, {"schema", "activation_identity_sha256", "run_identity_sha256", "bucket_key", "observed_at",
        "unit_sha256", "preserved", "final", "same_bucket", "capture_receipt_sha256", "teardown_sha256", "capture_close", "secret_values_recorded"}, "normal_readback")
    observed_at = _clock(readback["observed_at"], "normal_readback")
    expected_final = {"active": "active", "sub": "running", "enabled": "enabled", "collection_suspended": False,
        "formal_unit_count": 1, "formal_container_count": 1, "process_count": 1, "health": "ready"}
    if (readback["schema"] != "noteai.item33.normal_readback.v1"
        or readback["activation_identity_sha256"] != activation or readback["run_identity_sha256"] != run_identity
        or readback["bucket_key"] != bucket or readback["unit_sha256"] != V5_NORMAL_UNIT_SHA256
        or readback["capture_receipt_sha256"] != receipt_sha or readback["teardown_sha256"] != teardown_sha
        or readback["secret_values_recorded"] is not False
        or readback["preserved"] != preserved or readback["final"] != expected_final
        or readback["final"].get("collection_suspended") is not False
        or readback["same_bucket"] != {"bucket_key": bucket, "new_run_delta": 0, "provider_call_delta": 0}
        or not action_completed <= observed_at <= _trusted_now(clock) or observed_at.date().isoformat() != bucket):
        raise Item33ExecutionError("normal_readback")
    close = _mapping(readback["capture_close"], "normal_capture_close")
    _exact_keys(close, {"service_result_ref", "service_result_sha256", "close_ref", "close_sha256", "host_ref", "host_sha256"}, "normal_capture_close")
    for prefix, filename in (("service_result", "capture-service-result"), ("close", "capture-service-close"), ("host", "normal-host-readback")):
        if close[prefix + "_ref"] != f"deploy/production/evidence/production-item33-trends-{filename}.json":
            raise Item33ExecutionError("normal_capture_close")
        _sha256(close[prefix + "_sha256"], "normal_capture_close")
    for key in ("run_count", "attempt_count", "snapshot_count"):
        _exact_int(readback["preserved"][key], "normal_readback")
    for key in ("formal_unit_count", "formal_container_count", "process_count"):
        _exact_int(readback["final"][key], "normal_readback")
    for key in ("new_run_delta", "provider_call_delta"):
        _exact_int(readback["same_bucket"][key], "normal_readback")
    return {"status": "VERIFIED", "started_at": action_started.isoformat(), "completed_at": action_completed.isoformat(),
        "observed_at": observed_at.isoformat(), "activation_identity_sha256": activation, "run_identity_sha256": run_identity,
        "capture_receipt_sha256": receipt_sha,
        "teardown_ref": "deploy/production/evidence/production-item33-trends-capture-teardown.json",
        "teardown_sha256": teardown_sha, "before_unit_sha256": V5_PROMOTED_UNIT_SHA256,
        "normal_unit_sha256": V5_NORMAL_UNIT_SHA256, "image_config_sha256": V5_IMAGE_CONFIG_SHA256,
        "runtime_overlay_sha256": dict(V5_RUNTIME_OVERLAY_SHA256), "mutation_count": 1, "other_unit_actions": 0,
        "restart_policy": "no", "same_bucket": dict(readback["same_bucket"]), "preserved": preserved,
        "final": dict(readback["final"]), "capture_close": dict(close), "action_ref": NORMAL_ACTION_REF,
        "action_sha256": action["canonical_result_sha256"], "readback_ref": NORMAL_READBACK_REF,
        "readback_sha256": hashlib.sha256(_normal_json_bytes(readback)).hexdigest()}


__all__ = [
    "AUTHORIZATION_SCHEMA",
    "ENDPOINTS",
    "Item33ExecutionError",
    "LEGACY_PROMOTED_UNIT_SHA256",
    "PROMOTED_UNIT_SHA256",
    "PROVIDER_REQUEST_LIMIT",
    "RESULT_SCHEMA",
    "SUSPENDED_UNIT_SHA256",
    "UNIT_NAME",
    "execute_item33_promotion",
    "render_managed_unit",
    "execute_item33_normal_handoff",
    "V5_PROFILE",
    "V5_PROMOTED_UNIT_SHA256",
    "V5_NORMAL_UNIT_SHA256",
]
