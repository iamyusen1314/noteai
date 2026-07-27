#!/usr/bin/env python3
"""Fail-closed verifier for sanitized production Gate 0 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "model" / "migrations" / "postgres"
TASK_ID = "PROD-FIRST-LAUNCH-SEC-COMPLIANCE-PROD-PREFLIGHT-001"
APPLICATION_REVISION = "2fa3a5543876a6c8040ec17ca05a5461b101bbd7"
HISTORICAL_REVISION = "a635692a899ee02c6905cd694611c14e0da4594a"
EXPECTED_DIGESTS = {
    "api": "17706e1802afc136ac8f9a621d4199a7f9749da733290e923e42268eff42e0d1",
    "admin": "d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733",
    "xhs-http": "452c2faf7853ce58d93e43c05fb6217a9a6cc1e4c81345d8cef2f50acabd79af",
}
EXPECTED_HOST_ROLES = {
    "API-C": ("api", "admin"),
    "API-F": ("api",),
}
EXPECTED_ENV_ROLES = {
    "API-C": ("api", "admin"),
    "API-F": ("api", "xhs"),
}
EXPECTED_PORTS = {
    "API-C": {"api": "127.0.0.1:8000", "admin": "127.0.0.1:8001"},
    "API-F": {"api": "127.0.0.1:8000"},
}
EXPECTED_READY_CORE_CHECKS = {
    "api": ["database", "model"],
    "admin": ["admin_credentials", "database"],
}
EXPECTED_ROLE_STATE = {
    "noteai_app": "present",
    "noteai_admin": "present",
    "noteai_admin_runtime": "absent",
    "noteai_xhs": "present",
    "noteai_ai_dispatcher": "absent",
    "noteai_ai_worker": "absent",
    "noteai_payment": "absent",
    "noteai_xhs_tracking": "absent",
    "noteai_xhs_trends": "absent",
}
SOURCE_ZERO_AGGREGATES = {
    "noncanonical_phone_count",
    "duplicate_phone_count",
    "invalid_note_created_at_count",
    "invalid_diagnosis_created_at_count",
    "invalid_subscription_started_at_count",
    "invalid_subscription_expires_at_count",
    "tracking_noncanonical_identity_count",
    "tracking_duplicate_url_count",
    "tracking_duplicate_note_count",
    "tracking_invalid_status_or_metric_count",
    "tracking_invalid_or_unordered_clock_count",
    "tracking_incomplete_terminal_count",
    "tracking_active_legacy_work_count",
}
SOURCE_INFORMATIONAL_AGGREGATES = {
    "retention_backfill_candidate_count",
    "retention_immediate_deadline_count",
}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"\d+(?:\.\d+){1,3}")
_IPV4 = re.compile(r"(?<![0-9a-f])(?:\d{1,3}\.){3}\d{1,3}(?![0-9a-f])")
_INSTANCE_ID = re.compile(r"\bi-[a-z0-9]{8,}\b")
_CONNECTION_VALUE = re.compile(
    r"(?:postgres(?:ql)?|mysql|redis|mongodb)://|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.IGNORECASE,
)


class PreflightEvidenceError(ValueError):
    """Raised when production evidence is incomplete, unsafe or contradictory."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightEvidenceError(message)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label}: expected object")
    return value


def _sequence(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label}: expected array")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    _require(actual == expected, f"{label}: keys mismatch")


def _current_migration_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        version = path.name.split("_", 1)[0]
        _require(version.isdigit(), f"migration filename is invalid: {path.name}")
        hashes[version] = hashlib.sha256(path.read_bytes()).hexdigest()
    _require(tuple(hashes) == tuple(f"{number:04d}" for number in range(1, 17)),
             "repository migration set must be exactly 0001-0016")
    return hashes


def _parse_observed_at(value: Any) -> datetime:
    _require(isinstance(value, str), "observed_at_utc: expected string")
    _require(value.endswith("Z"), "observed_at_utc: must be UTC Z time")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PreflightEvidenceError("observed_at_utc: invalid timestamp") from exc
    _require(parsed.tzinfo == timezone.utc, "observed_at_utc: must be UTC")
    return parsed


def _scan_safe_values(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _require(isinstance(key, str), f"{path}: non-string key")
            _scan_safe_values(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _scan_safe_values(child, f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    _require(not _CONNECTION_VALUE.search(value), f"{path}: credential material")
    _require(not _INSTANCE_ID.search(value), f"{path}: cloud instance identity")
    if value not in EXPECTED_PORTS["API-C"].values() and value not in EXPECTED_PORTS[
        "API-F"
    ].values():
        _require(not _IPV4.search(value), f"{path}: network address")
    if len(value) > 128:
        _require(bool(_HEX64.fullmatch(value)), f"{path}: long opaque value")


def _verify_zero_mutation(evidence: dict[str, Any]) -> None:
    expected = {
        "cloud_changes",
        "database_writes",
        "business_row_values_read",
        "registry_requests",
        "service_changes",
        "provider_calls",
        "public_traffic_requests",
        "secret_values_exposed",
    }
    _exact_keys(evidence, expected, "zero_mutation")
    for key in expected:
        _require(evidence[key] == 0, f"zero_mutation.{key}: must be zero")


def _verify_env_files(host: str, rows: Any) -> None:
    env_files = _sequence(rows, f"{host}.env_files")
    expected_roles = set(EXPECTED_ENV_ROLES[host])
    actual_roles: set[str] = set()
    for index, raw in enumerate(env_files):
        row = _mapping(raw, f"{host}.env_files[{index}]")
        _exact_keys(
            row,
            {
                "role",
                "file_label",
                "regular",
                "owner",
                "mode",
                "key_count",
                "duplicate_key_count",
                "rejected_key_count",
            },
            f"{host}.env_files[{index}]",
        )
        role = row["role"]
        _require(role in expected_roles, f"{host}: unexpected env role")
        _require(role not in actual_roles, f"{host}: duplicate env role")
        actual_roles.add(role)
        _require(row["file_label"] == f"{role}.env", f"{host}.{role}: file label")
        _require(row["regular"] is True, f"{host}.{role}: env is not regular")
        _require(row["owner"] == "root", f"{host}.{role}: env owner")
        _require(row["mode"] == "0600", f"{host}.{role}: env mode")
        _require(
            isinstance(row["key_count"], int) and row["key_count"] > 0,
            f"{host}.{role}: empty env",
        )
        _require(row["duplicate_key_count"] == 0, f"{host}.{role}: duplicate keys")
        _require(row["rejected_key_count"] == 0, f"{host}.{role}: rejected keys")
    _require(actual_roles == expected_roles, f"{host}: env role set mismatch")


def _verify_runtime(host: str, raw: Any) -> None:
    evidence = _mapping(raw, host)
    _exact_keys(
        evidence,
        {
            "label",
            "instance_state",
            "system_status",
            "private_only",
            "architecture",
            "docker_version",
            "compose_version",
            "docker_free_gib",
            "memory_available_mib",
            "private_acr_dns",
            "private_acr_route",
            "containers",
            "env_files",
            "unexpected_container_count",
            "unexpected_listener_count",
            "mutable_image_ref_count",
            "temporary_auth_entry_count",
            "temporary_process_count",
        },
        host,
    )
    _require(evidence["label"] == host, f"{host}: label mismatch")
    _require(evidence["instance_state"] == "Running", f"{host}: not running")
    _require(evidence["system_status"] == "OK", f"{host}: health is not OK")
    _require(evidence["private_only"] is True, f"{host}: public address/exposure")
    _require(evidence["architecture"] in {"x86_64", "amd64"}, f"{host}: architecture")
    _require(
        isinstance(evidence["docker_version"], str)
        and bool(_VERSION.fullmatch(evidence["docker_version"])),
        f"{host}: Docker version",
    )
    _require(
        evidence["compose_version"] == "absent"
        or (
            isinstance(evidence["compose_version"], str)
            and bool(_VERSION.fullmatch(evidence["compose_version"]))
        ),
        f"{host}: Compose version",
    )
    _require(
        isinstance(evidence["docker_free_gib"], (int, float))
        and not isinstance(evidence["docker_free_gib"], bool)
        and evidence["docker_free_gib"] >= 12,
        f"{host}: less than 12 GiB Docker storage",
    )
    _require(
        isinstance(evidence["memory_available_mib"], int)
        and evidence["memory_available_mib"] >= 1024,
        f"{host}: less than 1024 MiB available memory",
    )
    _require(evidence["private_acr_dns"] is True, f"{host}: private ACR DNS")
    _require(evidence["private_acr_route"] is True, f"{host}: private ACR route")
    for key in (
        "unexpected_container_count",
        "unexpected_listener_count",
        "mutable_image_ref_count",
        "temporary_auth_entry_count",
        "temporary_process_count",
    ):
        _require(evidence[key] == 0, f"{host}.{key}: must be zero")

    containers = _sequence(evidence["containers"], f"{host}.containers")
    actual_roles: set[str] = set()
    for index, raw_container in enumerate(containers):
        container = _mapping(raw_container, f"{host}.containers[{index}]")
        _exact_keys(
            container,
            {
                "role",
                "running",
                "managed",
                "image_digest_hex",
                "local_image_id_hex",
                "oci_revision",
                "unit_sha256",
                "unit_active",
                "unit_enabled",
                "unit_result",
                "user",
                "read_only_root",
                "privileged",
                "cap_drop_all",
                "no_new_privileges",
                "restart_policy",
                "mount_destinations",
                "loopback_listener",
                "public_listener_count",
                "live_http_status",
                "ready_http_status",
                "ready_core_checks",
                "log_migration_hit_count",
                "log_provider_hit_count",
                "log_secret_pattern_hit_count",
            },
            f"{host}.containers[{index}]",
        )
        role = container["role"]
        _require(role in EXPECTED_HOST_ROLES[host], f"{host}: unexpected role")
        _require(role not in actual_roles, f"{host}: duplicate role")
        actual_roles.add(role)
        _require(container["running"] is True, f"{host}.{role}: not running")
        _require(container["managed"] is True, f"{host}.{role}: not managed")
        digest_role = "xhs-http" if role.startswith("xhs") else role
        _require(
            container["image_digest_hex"] == EXPECTED_DIGESTS[digest_role],
            f"{host}.{role}: historical digest mismatch",
        )
        _require(
            isinstance(container["local_image_id_hex"], str)
            and bool(_HEX64.fullmatch(container["local_image_id_hex"])),
            f"{host}.{role}: local image ID",
        )
        _require(
            container["oci_revision"] == HISTORICAL_REVISION,
            f"{host}.{role}: historical OCI revision mismatch",
        )
        _require(
            isinstance(container["unit_sha256"], str)
            and bool(_HEX64.fullmatch(container["unit_sha256"])),
            f"{host}.{role}: unit SHA-256",
        )
        _require(container["unit_active"] is True, f"{host}.{role}: unit inactive")
        _require(container["unit_enabled"] is True, f"{host}.{role}: unit disabled")
        _require(
            container["unit_result"] == "success",
            f"{host}.{role}: unit result",
        )
        _require(container["user"] == "999:999", f"{host}.{role}: runtime user")
        _require(
            container["read_only_root"] is True,
            f"{host}.{role}: writable root",
        )
        _require(
            container["privileged"] is False,
            f"{host}.{role}: privileged runtime",
        )
        _require(
            container["cap_drop_all"] is True,
            f"{host}.{role}: capability boundary",
        )
        _require(
            container["no_new_privileges"] is True,
            f"{host}.{role}: no-new-privileges",
        )
        _require(
            container["restart_policy"] == "no",
            f"{host}.{role}: Docker restart policy",
        )
        _require(
            container["mount_destinations"] == ["/app/model/data"],
            f"{host}.{role}: mount destinations",
        )
        _require(
            container["loopback_listener"] == EXPECTED_PORTS[host][role],
            f"{host}.{role}: listener mismatch",
        )
        _require(
            container["public_listener_count"] == 0,
            f"{host}.{role}: public listener",
        )
        _require(
            container["live_http_status"] == 200,
            f"{host}.{role}: liveness status",
        )
        _require(
            container["ready_http_status"] == 200,
            f"{host}.{role}: readiness status",
        )
        _require(
            container["ready_core_checks"] == EXPECTED_READY_CORE_CHECKS[role],
            f"{host}.{role}: readiness core checks",
        )
        for key in (
            "log_migration_hit_count",
            "log_provider_hit_count",
            "log_secret_pattern_hit_count",
        ):
            _require(container[key] == 0, f"{host}.{role}.{key}: must be zero")
    _require(
        actual_roles == set(EXPECTED_HOST_ROLES[host]),
        f"{host}: running role set mismatch",
    )
    _verify_env_files(host, evidence["env_files"])


def _verify_cloud(evidence: dict[str, Any]) -> None:
    _exact_keys(evidence, {"acr", "rds", "edge"}, "cloud")
    acr = _mapping(evidence["acr"], "cloud.acr")
    _exact_keys(
        acr,
        {
            "historical_digests",
            "historical_images_normal",
            "historical_tags_immutable",
            "current_release_published",
            "registry_requests",
        },
        "cloud.acr",
    )
    _require(acr["historical_digests"] == EXPECTED_DIGESTS, "ACR digest set")
    _require(acr["historical_images_normal"] is True, "ACR image status")
    _require(acr["historical_tags_immutable"] is True, "ACR mutable tags")
    _require(acr["current_release_published"] is False, "unexpected current publish")
    _require(acr["registry_requests"] == 0, "ACR request occurred")

    rds = _mapping(evidence["rds"], "cloud.rds")
    _exact_keys(
        rds,
        {
            "state",
            "engine",
            "major_version",
            "high_availability",
            "encrypted",
            "ssl_enabled",
            "public_endpoint",
            "backup_enabled",
            "pitr_enabled",
            "backup_retention_days",
            "max_connections",
        },
        "cloud.rds",
    )
    _require(rds["state"] == "Running", "RDS is not Running")
    _require(rds["engine"] == "PostgreSQL", "RDS engine")
    _require(rds["major_version"] == 16, "RDS major version")
    for key in (
        "high_availability",
        "encrypted",
        "ssl_enabled",
        "backup_enabled",
        "pitr_enabled",
    ):
        _require(rds[key] is True, f"cloud.rds.{key}: must be true")
    _require(rds["public_endpoint"] is False, "RDS public endpoint")
    _require(
        isinstance(rds["backup_retention_days"], int)
        and rds["backup_retention_days"] >= 14,
        "RDS backup retention below 14 days",
    )
    _require(
        isinstance(rds["max_connections"], int) and rds["max_connections"] >= 100,
        "RDS max_connections below 100",
    )

    edge = _mapping(evidence["edge"], "cloud.edge")
    _exact_keys(
        edge,
        {"alb_target_count", "tls_listener_count", "business_dns_record_count", "traffic_request_count"},
        "cloud.edge",
    )
    for key, value in edge.items():
        _require(value == 0, f"cloud.edge.{key}: must be zero")


def _verify_database(evidence: dict[str, Any]) -> None:
    _exact_keys(
        evidence,
        {
            "metadata_session_read_only",
            "business_row_values_read",
            "aggregate_query_count",
            "migration_ledger_source",
            "applied_migration_hashes",
            "pending_versions",
            "stored_migration_drift_count",
            "source_preflight_complete",
            "source_preflight_blocker_count",
            "effective_role_audit_complete",
            "unexpected_grant_count",
            "runtime_owner_count",
            "runtime_superuser_count",
            "runtime_bypassrls_count",
            "role_state",
            "source_aggregates",
        },
        "database",
    )
    _require(
        evidence["metadata_session_read_only"] is True,
        "database metadata session is not read-only",
    )
    _require(evidence["business_row_values_read"] == 0, "business row value read")
    _require(
        isinstance(evidence["aggregate_query_count"], int)
        and evidence["aggregate_query_count"] >= 1,
        "database aggregate evidence absent",
    )
    _require(
        evidence["migration_ledger_source"]
        in {"stored_sha256", "pinned_legacy_versions"},
        "database migration ledger source",
    )
    hashes = _current_migration_hashes()
    _require(
        evidence["applied_migration_hashes"]
        == {version: hashes[version] for version in tuple(hashes)[:8]},
        "applied migration hashes do not match repository 0001-0008",
    )
    _require(
        evidence["pending_versions"] == list(tuple(hashes)[8:]),
        "pending migration set must be 0009-0016",
    )
    for key in (
        "stored_migration_drift_count",
        "source_preflight_blocker_count",
        "unexpected_grant_count",
        "runtime_owner_count",
        "runtime_superuser_count",
        "runtime_bypassrls_count",
    ):
        _require(evidence[key] == 0, f"database.{key}: must be zero")
    _require(
        evidence["source_preflight_complete"] is True,
        "database source preflight is incomplete",
    )
    _require(
        evidence["effective_role_audit_complete"] is True,
        "database role audit is incomplete",
    )
    _require(evidence["role_state"] == EXPECTED_ROLE_STATE, "database role state")
    aggregates = _mapping(evidence["source_aggregates"], "database.source_aggregates")
    _exact_keys(
        aggregates,
        SOURCE_ZERO_AGGREGATES | SOURCE_INFORMATIONAL_AGGREGATES,
        "database.source_aggregates",
    )
    for key in SOURCE_ZERO_AGGREGATES:
        _require(
            aggregates[key] == 0,
            f"database.source_aggregates.{key}: must be zero",
        )
    for key in SOURCE_INFORMATIONAL_AGGREGATES:
        _require(
            isinstance(aggregates[key], int)
            and not isinstance(aggregates[key], bool)
            and aggregates[key] >= 0,
            f"database.source_aggregates.{key}: invalid count",
        )
    _require(
        evidence["aggregate_query_count"] >= len(aggregates),
        "database aggregate query coverage is incomplete",
    )


def _verify_cleanup(evidence: dict[str, Any]) -> None:
    _exact_keys(
        evidence,
        {
            "temporary_file_count",
            "temporary_credential_count",
            "temporary_process_count",
            "session_manager_enabled",
            "host_services_unchanged",
            "database_unchanged",
        },
        "cleanup",
    )
    for key in (
        "temporary_file_count",
        "temporary_credential_count",
        "temporary_process_count",
    ):
        _require(evidence[key] == 0, f"cleanup.{key}: must be zero")
    _require(
        evidence["session_manager_enabled"] is False,
        "Session Manager remains enabled",
    )
    _require(evidence["host_services_unchanged"] is True, "host service changed")
    _require(evidence["database_unchanged"] is True, "database changed")


def validate_evidence(raw: Any) -> dict[str, Any]:
    evidence = _mapping(raw, "evidence")
    _exact_keys(
        evidence,
        {
            "schema_version",
            "task_id",
            "status",
            "observed_at_utc",
            "application_revision",
            "zero_mutation",
            "cloud",
            "hosts",
            "database",
            "cleanup",
        },
        "evidence",
    )
    _require(evidence["schema_version"] == 1, "schema_version must be 1")
    _require(evidence["task_id"] == TASK_ID, "task_id mismatch")
    _require(evidence["status"] == "verified", "status must be verified")
    _parse_observed_at(evidence["observed_at_utc"])
    _require(
        evidence["application_revision"] == APPLICATION_REVISION,
        "application revision mismatch",
    )
    _scan_safe_values(evidence)
    _verify_zero_mutation(_mapping(evidence["zero_mutation"], "zero_mutation"))
    _verify_cloud(_mapping(evidence["cloud"], "cloud"))

    hosts = _sequence(evidence["hosts"], "hosts")
    _require(len(hosts) == 2, "hosts: expected API-C and API-F")
    by_label: dict[str, Any] = {}
    for host in hosts:
        host_row = _mapping(host, "hosts[]")
        label = host_row.get("label")
        _require(label in EXPECTED_HOST_ROLES, "hosts: unknown label")
        _require(label not in by_label, "hosts: duplicate label")
        by_label[label] = host_row
    _require(set(by_label) == set(EXPECTED_HOST_ROLES), "host set mismatch")
    for label in EXPECTED_HOST_ROLES:
        _verify_runtime(label, by_label[label])

    _verify_database(_mapping(evidence["database"], "database"))
    _verify_cleanup(_mapping(evidence["cleanup"], "cleanup"))
    return evidence


def load_evidence(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightEvidenceError(f"cannot load evidence: {exc}") from exc
    return validate_evidence(raw)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify sanitized zero-write production Gate 0 evidence."
    )
    parser.add_argument("evidence", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        evidence = load_evidence(args.evidence)
    except PreflightEvidenceError as exc:
        print(f"production_readonly_preflight=INVALID error={exc}")
        return 1
    print(
        "production_readonly_preflight=PASS "
        f"task={evidence['task_id']} observed_at={evidence['observed_at_utc']} "
        "hosts=2 mutations=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
