#!/usr/bin/env python3
"""Fail-closed readiness accounting for the complete NoteAI first launch.

This tool validates a finite evidence ledger and computes three distinct
layers. It never contacts cloud services or providers and cannot turn a green
repository test suite into production evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from verify_api_c_current_release_evidence import (
    EXPECTED_MANIFEST_EVIDENCE as API_C_EXPECTED_MANIFEST_EVIDENCE,
)
from verify_api_c_current_release_evidence import (
    validate_bundle as validate_api_c_current_release_evidence,
)
from verify_api_f_current_release_evidence import (
    EXPECTED_MANIFEST_EVIDENCE as API_F_EXPECTED_MANIFEST_EVIDENCE,
)
from verify_api_f_current_release_evidence import (
    validate_bundle as validate_api_f_current_release_evidence,
)
from verify_admin_current_release_evidence import (
    validate_bundle as validate_admin_current_release_evidence,
)
from verify_internal_zero_provider_smoke_evidence import (
    validate_manifest_evidence as validate_internal_zero_provider_smoke_evidence,
)
from verify_internal_failure_rollback_evidence import (
    validate_manifest_evidence as validate_internal_failure_rollback_evidence,
)
from verify_capacity_100_jobs_evidence import (
    validate_manifest_evidence as validate_capacity_100_jobs_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "deploy" / "production" / "internal-deployment-readiness.json"
EXPECTED_LAYERS = ("repository_isolated", "internal_runtime", "public_launch")
VALID_STATUSES = {"verified", "unverified", "blocked"}
VALID_EVIDENCE_KINDS = {"git", "path"}
VALID_EXECUTION_CLASSES = {
    "repository_offline",
    "authenticated_production",
    "external_or_public",
    "professional_review",
}
ACCEPTED_RISK_CONTROL_ID = "production_schema_roles"
EXPECTED_ACCEPTED_RISK_FINDINGS = {
    "FIRST-LAUNCH-LEGACY-XHS-ADMIN-MEMBERSHIP-20260728": {
        "granted_role": "noteai_xhs",
        "member_role": "noteai_admin",
        "admin_option": True,
        "inherit_option": False,
        "set_option": False,
    },
    "FIRST-LAUNCH-LEGACY-APP-INHERIT-20260728": {
        "role": "noteai_app",
        "rolinherit": True,
        "incoming_membership_count": 0,
        "high_privilege_inheritance_count": 0,
    },
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ITEM26_TERMINAL_EVIDENCE = [
    {"kind": "path", "ref": ".codex/handoffs/current-task.md"}
]
ITEM26_TERMINAL_ACCEPTANCE_SHA256 = (
    "4285231c59a111056426c643aac0764a1d7c32904caf46eacf555188d082a7b8"
)
ITEM26_HANDOFF_TERMINAL_BINDINGS = (
    "c-sz06us1t8hwu4u8",
    "t-sz06us1t8ijb7y8",
    "01A02A52-80FB-5218-AB42-9C2A98555BA6",
    "99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a",
    "476a9d2b6daf79f4d190bf3e08dfefe07e372fd6387f858bbe584b40c2a7910b",
    "438e9d19f5e4ea2284165e3a927e146ad1a22af62b010c7140f2bb999242e29b",
    "01A02A58-801E-59B8-868E-3E583F0FEFBD",
    "01A02A58-B2EA-598A-BCDF-3D96BF3CCD50",
    "01A02A5D-53B9-513F-8500-2944A1A79E4D",
    "01A02A63-23A2-592B-A670-75A568B96008",
    "01A02A72-9985-5D33-8ADB-D507E6A482FE",
    "t-sz06us4hlzxn7r4",
    "01A02A73-B23A-56A6-B9BE-FA7F30D5CF71",
    "01A02A6F-02C0-501E-8B83-59FE19AC358F",
    "01A02A6F-479B-5842-9BB6-1D9C43BD7328",
    "01A02A71-EE82-5D2F-8698-AA5C7BD0B81E",
    "01A02A76-B492-59AA-A15F-A541D7234041",
)


class ManifestError(ValueError):
    """Raised when the readiness ledger is ambiguous or unverifiable."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _verify_git_ref(ref: str, *, root: Path) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _verify_path(ref: str, *, root: Path) -> bool:
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return False
    return resolved.is_file()


def validate_item26_terminal_evidence(
    control: dict[str, Any], *, root: Path = ROOT
) -> tuple[list[str], str | None]:
    """Validate the original Item 26 DoD without later proof structures."""

    errors: list[str] = []
    if control.get("evidence") != ITEM26_TERMINAL_EVIDENCE:
        errors.append("original DoD evidence ref mismatch")
    elif not _verify_path(ITEM26_TERMINAL_EVIDENCE[0]["ref"], root=root):
        errors.append("original DoD evidence path missing")

    reconciliation = control.get("latest_reconciliation")
    if not isinstance(reconciliation, dict):
        return [*errors, "latest reconciliation missing"], None
    if reconciliation.get("status") != (
        "ORIGINAL_ITEM26_DOD_VERIFIED_ZERO_RESIDUE"
    ):
        errors.append("latest reconciliation status mismatch")
    if reconciliation.get("readiness_credit_added") is not True:
        errors.append("latest reconciliation readiness credit mismatch")

    acceptance = reconciliation.get(
        "original_dod_terminal_acceptance_20260823"
    )
    if not isinstance(acceptance, dict):
        return [*errors, "original DoD terminal acceptance missing"], None
    semantic = json.dumps(
        acceptance, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    acceptance_sha256 = hashlib.sha256(semantic).hexdigest()
    if acceptance_sha256 != ITEM26_TERMINAL_ACCEPTANCE_SHA256:
        errors.append("original DoD terminal acceptance mismatch")

    if not errors:
        handoff = (root / ITEM26_TERMINAL_EVIDENCE[0]["ref"]).read_text(
            encoding="utf-8"
        )
        if any(value not in handoff for value in ITEM26_HANDOFF_TERMINAL_BINDINGS):
            errors.append("handoff terminal binding missing")

    return (errors, None) if errors else ([], acceptance_sha256)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load readiness manifest: {exc}") from exc
    _require(isinstance(payload, dict), "manifest root must be an object")
    return payload


def validate_manifest(manifest: dict[str, Any], *, root: Path = ROOT) -> None:
    _require(manifest.get("schema_version") == 1, "unsupported schema_version")
    _require(
        manifest.get("task_id") == "PROD-COMPLETE-FIRST-LAUNCH-001",
        "unexpected umbrella task",
    )
    _require(
        set(manifest.get("status_values") or []) == VALID_STATUSES,
        "status_values must match the fail-closed status vocabulary",
    )
    layers = manifest.get("layers")
    _require(isinstance(layers, list), "layers must be a list")
    layer_ids = tuple(layer.get("id") for layer in layers if isinstance(layer, dict))
    _require(layer_ids == EXPECTED_LAYERS, "readiness layers are missing or out of order")

    controls_by_id: dict[str, dict[str, Any]] = {}
    for layer in layers:
        _require(
            layer.get("default_execution_class") in VALID_EXECUTION_CLASSES,
            f"{layer.get('id')}: invalid default_execution_class",
        )
        controls = layer.get("controls")
        _require(isinstance(controls, list) and controls, f"{layer.get('id')}: controls required")
        for control in controls:
            _require(isinstance(control, dict), "control must be an object")
            control_id = control.get("id")
            _require(
                isinstance(control_id, str) and control_id and control_id not in controls_by_id,
                f"duplicate or invalid control id: {control_id}",
            )
            _require(
                isinstance(control.get("title"), str) and control["title"].strip(),
                f"{control_id}: title required",
            )
            status = control.get("status")
            _require(status in VALID_STATUSES, f"{control_id}: invalid status {status}")
            _require(
                control.get("execution_class", layer["default_execution_class"])
                in VALID_EXECUTION_CLASSES,
                f"{control_id}: invalid execution_class",
            )
            dependencies = control.get("dependencies")
            _require(isinstance(dependencies, list), f"{control_id}: dependencies must be a list")
            _require(
                all(isinstance(item, str) and item for item in dependencies),
                f"{control_id}: invalid dependency",
            )
            evidence = control.get("evidence")
            _require(isinstance(evidence, list), f"{control_id}: evidence must be a list")
            if status == "verified":
                _require(evidence, f"{control_id}: verified without evidence")
                _require(not control.get("blocker"), f"{control_id}: verified with blocker")
            else:
                _require(
                    isinstance(control.get("blocker"), str) and control["blocker"].strip(),
                    f"{control_id}: non-verified control requires blocker",
                )
                _require(
                    isinstance(control.get("next_task"), str) and control["next_task"].strip(),
                    f"{control_id}: non-verified control requires next_task",
                )
            if status == "blocked":
                _require(
                    isinstance(control.get("resume_condition"), str)
                    and control["resume_condition"].strip(),
                    f"{control_id}: blocked control requires resume_condition",
                )
            for item in evidence:
                _require(isinstance(item, dict), f"{control_id}: invalid evidence entry")
                kind = item.get("kind")
                ref = item.get("ref")
                _require(kind in VALID_EVIDENCE_KINDS, f"{control_id}: invalid evidence kind")
                _require(isinstance(ref, str) and ref, f"{control_id}: evidence ref required")
                if kind == "git":
                    _require(_verify_git_ref(ref, root=root), f"{control_id}: missing git evidence {ref}")
                else:
                    _require(_verify_path(ref, root=root), f"{control_id}: missing path evidence {ref}")
            if control_id == "api_c_current_release" and status == "verified":
                _require(
                    evidence == API_C_EXPECTED_MANIFEST_EVIDENCE,
                    f"{control_id}: exact runtime evidence refs required",
                )
                runtime_errors = validate_api_c_current_release_evidence(
                    root=root
                )
                _require(
                    not runtime_errors,
                    f"{control_id}: invalid runtime evidence: "
                    f"{runtime_errors[0] if runtime_errors else ''}",
                )
            if control_id == "api_f_current_release" and status == "verified":
                _require(
                    evidence == API_F_EXPECTED_MANIFEST_EVIDENCE,
                    f"{control_id}: exact runtime evidence refs required",
                )
                runtime_errors = validate_api_f_current_release_evidence(
                    root=root
                )
                _require(
                    not runtime_errors,
                    f"{control_id}: invalid runtime evidence: "
                    f"{runtime_errors[0] if runtime_errors else ''}",
                )
            if control_id == "admin_current_release" and status == "verified":
                required_refs = {
                    (
                        "git",
                        "5335bdaed933b1f999b5f819c047ec50c11821ae",
                    ),
                    (
                        "path",
                        "deploy/production/evidence/"
                        "production-admin-current-release-verified-20260805.json",
                    ),
                    (
                        "path",
                        "tools/verify_admin_current_release_evidence.py",
                    ),
                }
                actual_refs = {
                    (item.get("kind"), item.get("ref")) for item in evidence
                }
                _require(
                    required_refs.issubset(actual_refs),
                    f"{control_id}: final runtime evidence refs required",
                )
                runtime_errors = validate_admin_current_release_evidence(
                    root=root
                )
                _require(
                    not runtime_errors,
                    f"{control_id}: invalid runtime evidence: "
                    f"{runtime_errors[0] if runtime_errors else ''}",
                )
            accepted_risks = control.get("accepted_risks", [])
            _require(
                isinstance(accepted_risks, list),
                f"{control_id}: accepted_risks must be a list",
            )
            if accepted_risks:
                _require(
                    control_id == ACCEPTED_RISK_CONTROL_ID,
                    f"{control_id}: accepted_risks are not allowed",
                )
                _require(
                    len(accepted_risks) == len(
                        EXPECTED_ACCEPTED_RISK_FINDINGS
                    ),
                    f"{control_id}: exact accepted_risks required",
                )
                observed_ids = {
                    item.get("id")
                    for item in accepted_risks
                    if isinstance(item, dict)
                }
                _require(
                    observed_ids == set(EXPECTED_ACCEPTED_RISK_FINDINGS),
                    f"{control_id}: accepted_risk ids changed",
                )
                for risk in accepted_risks:
                    risk_id = risk["id"]
                    _require(
                        risk.get("status") == "accepted_risk",
                        f"{risk_id}: status must be accepted_risk",
                    )
                    _require(
                        risk.get("accepted_by") == "product_owner",
                        f"{risk_id}: product-owner acceptance required",
                    )
                    _require(
                        risk.get("environment") == "production",
                        f"{risk_id}: production environment required",
                    )
                    _require(
                        risk.get("finding")
                        == EXPECTED_ACCEPTED_RISK_FINDINGS[risk_id],
                        f"{risk_id}: finding changed",
                    )
                    _require(
                        isinstance(risk.get("decision_at_utc"), str)
                        and risk["decision_at_utc"].endswith("Z"),
                        f"{risk_id}: UTC decision timestamp required",
                    )
                    _require(
                        risk.get("owner") == "CTO",
                        f"{risk_id}: CTO owner required",
                    )
                    _require(
                        risk.get("review_due")
                        == "first_public_launch_plus_30_days",
                        f"{risk_id}: review trigger changed",
                    )
                    for field in (
                        "scope",
                        "remediation",
                        "actual_effective_privileges",
                    ):
                        _require(
                            isinstance(risk.get(field), str)
                            and risk[field].strip(),
                            f"{risk_id}: {field} required",
                        )
                    for field in (
                        "prohibited_expansion",
                        "compensating_controls",
                        "invalidates_on",
                    ):
                        _require(
                            isinstance(risk.get(field), list)
                            and risk[field]
                            and all(
                                isinstance(value, str) and value.strip()
                                for value in risk[field]
                            ),
                            f"{risk_id}: {field} required",
                        )
                    _require(
                        risk.get("readiness_credit") == 0,
                        f"{risk_id}: readiness credit must be zero",
                    )
                    _require(
                        risk.get("migration_verified") is False,
                        f"{risk_id}: migration cannot be accepted by risk",
                    )
                    _require(
                        risk.get("database_action_authorized") is False,
                        f"{risk_id}: risk cannot authorize database action",
                    )
                    _require(
                        risk.get("not_verified_fixed") is True,
                        f"{risk_id}: risk must not claim verified fixed",
                    )
                    digest = risk.get("source_evidence_sha256")
                    _require(
                        isinstance(digest, str)
                        and SHA256.fullmatch(digest) is not None,
                        f"{risk_id}: source evidence SHA-256 required",
                    )
                    risk_evidence = risk.get("evidence")
                    _require(
                        isinstance(risk_evidence, list)
                        and risk_evidence,
                        f"{risk_id}: evidence required",
                    )
                    for item in risk_evidence:
                        _require(
                            isinstance(item, dict)
                            and item.get("kind") == "path",
                            f"{risk_id}: path evidence required",
                        )
                        ref = item.get("ref")
                        _require(
                            isinstance(ref, str)
                            and _verify_path(ref, root=root),
                            f"{risk_id}: missing risk evidence {ref}",
                        )
            controls_by_id[control_id] = control

    item26 = controls_by_id.get("backup_pitr_restore") or {}
    if item26.get("status") == "verified":
        item26_errors, item26_acceptance_sha256 = (
            validate_item26_terminal_evidence(item26, root=root)
        )
        _require(
            not item26_errors
            and isinstance(item26_acceptance_sha256, str)
            and SHA256.fullmatch(item26_acceptance_sha256) is not None,
            "backup_pitr_restore: invalid semantic evidence: "
            f"{item26_errors[0] if item26_errors else ''}",
        )
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        deferred = {
            "backup_pitr_restore",
            "internal_zero_provider_smoke",
            "internal_failure_rollback",
            "capacity_100_jobs",
        }
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in deferred
        )
        public_before = sum(
            control["status"] == "verified"
            for control in all_controls
            if control["id"] not in deferred
        )
        _require(
            internal_before == 25
            and public_before == 25
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "backup_pitr_restore: exact 25/29 predecessor state required",
        )

    smoke = controls_by_id.get("internal_zero_provider_smoke") or {}
    if smoke.get("status") == "verified":
        item26 = controls_by_id.get("backup_pitr_restore") or {}
        _require(
            item26.get("status") == "verified",
            "internal_zero_provider_smoke: Item26 terminal verification required",
        )
        item26_errors, item26_acceptance_sha256 = (
            validate_item26_terminal_evidence(item26, root=root)
        )
        _require(
            not item26_errors
            and isinstance(item26_acceptance_sha256, str)
            and SHA256.fullmatch(item26_acceptance_sha256) is not None,
            "internal_zero_provider_smoke: Item26 semantic evidence invalid: "
            f"{item26_errors[0] if item26_errors else ''}",
        )
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in {
                "internal_zero_provider_smoke",
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        public_before = sum(
            control["status"] == "verified"
            for control in all_controls
            if control["id"] not in {
                "internal_zero_provider_smoke",
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        _require(
            internal_before == 26
            and public_before == 26
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "internal_zero_provider_smoke: exact 26/29 predecessor state required",
        )
        internal_after = internal_before + 1
        public_after = public_before + 1
        expected_readiness = {
            "internal_verified_before": internal_before,
            "internal_verified_after": internal_after,
            "internal_total": len(internal_controls),
            "internal_percentage_after": (
                internal_after * 100 + len(internal_controls) // 2
            ) // len(internal_controls),
            "complete_public_verified_before": public_before,
            "complete_public_verified_after": public_after,
            "complete_public_total": len(all_controls),
            "complete_public_percentage_after": (
                public_after * 100 + len(all_controls) // 2
            ) // len(all_controls),
            "next_task": "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001",
            "public_launch_authorized": False,
            "real_provider_chain_verified": False,
            "full_system_failure_rollback_verified": False,
            "capacity_100_jobs_verified": False,
        }
        runtime_errors = validate_internal_zero_provider_smoke_evidence(
            smoke["evidence"],
            root=root,
            expected_item26_terminal_acceptance_sha256=(
                item26_acceptance_sha256
            ),
            expected_readiness=expected_readiness,
        )
        _require(
            not runtime_errors,
            "internal_zero_provider_smoke: invalid semantic evidence: "
            f"{runtime_errors[0] if runtime_errors else ''}",
        )

    rollback = controls_by_id.get("internal_failure_rollback") or {}
    if rollback.get("status") == "verified":
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in {
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        public_before = sum(
            control["status"] == "verified"
            for control in all_controls
            if control["id"] not in {
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        _require(
            internal_before == 27
            and public_before == 27
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "internal_failure_rollback: exact 27/29 predecessor state required",
        )
        expected_readiness = {
            "internal_verified_before": 27,
            "internal_verified_after": 28,
            "internal_total": 29,
            "internal_percentage_after": 97,
            "complete_public_verified_before": 27,
            "complete_public_verified_after": 28,
            "complete_public_total": 38,
            "complete_public_percentage_after": 74,
            "next_task": "PROD-FIRST-LAUNCH-CAPACITY-100-001",
            "public_launch_authorized": False,
            "real_provider_chain_verified": False,
            "capacity_100_jobs_verified": False,
        }
        runtime_errors = validate_internal_failure_rollback_evidence(
            rollback["evidence"],
            root=root,
            expected_readiness=expected_readiness,
        )
        _require(
            not runtime_errors,
            "internal_failure_rollback: invalid semantic evidence: "
            f"{runtime_errors[0] if runtime_errors else ''}",
        )

    capacity = controls_by_id.get("capacity_100_jobs") or {}
    if capacity.get("status") == "verified":
        _require(
            all(
                (controls_by_id.get(dependency) or {}).get("status") == "verified"
                for dependency in capacity.get("dependencies", [])
            ),
            "capacity_100_jobs: verified dependency required",
        )
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] != "capacity_100_jobs"
        )
        public_before = sum(
            control["status"] == "verified"
            for control in all_controls
            if control["id"] != "capacity_100_jobs"
        )
        _require(
            internal_before == 28
            and public_before == 28
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "capacity_100_jobs: exact 28/29 predecessor state required",
        )
        expected_readiness = {
            "internal_verified_before": 28,
            "internal_verified_after": 29,
            "internal_total": 29,
            "internal_percentage_after": 100,
            "complete_public_verified_before": 28,
            "complete_public_verified_after": 29,
            "complete_public_total": 38,
            "complete_public_percentage_after": 76,
            "next_task": "PROD-FIRST-LAUNCH-PROVIDER-CHAIN-001",
            "public_launch_authorized": False,
            "real_provider_chain_verified": False,
            "capacity_100_jobs_verified": True,
        }
        capacity_errors = validate_capacity_100_jobs_evidence(
            capacity.get("evidence"),
            root=root,
            expected_readiness=expected_readiness,
        )
        _require(
            not capacity_errors,
            "capacity_100_jobs: invalid semantic evidence: "
            + (capacity_errors[0] if capacity_errors else ""),
        )

    for control_id, control in controls_by_id.items():
        for dependency in control["dependencies"]:
            _require(dependency in controls_by_id, f"{control_id}: unknown dependency {dependency}")
            _require(dependency != control_id, f"{control_id}: self dependency")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(control_id: str) -> None:
        if control_id in visiting:
            raise ManifestError(f"dependency cycle at {control_id}")
        if control_id in visited:
            return
        visiting.add(control_id)
        for dependency in controls_by_id[control_id]["dependencies"]:
            visit(dependency)
        visiting.remove(control_id)
        visited.add(control_id)

    for control_id in controls_by_id:
        visit(control_id)


def _score(controls: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(controls)
    verified = sum(item["status"] == "verified" for item in controls)
    blocked = sum(item["status"] == "blocked" for item in controls)
    percentage = (verified * 100 + total // 2) // total
    return {
        "passed": verified == total,
        "percentage": percentage,
        "verified": verified,
        "total": total,
        "blocked": blocked,
        "remaining": total - verified,
    }


def build_report(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest, root=root)
    layers: dict[str, dict[str, Any]] = {}
    controls_by_id: dict[str, dict[str, Any]] = {}
    for layer in manifest["layers"]:
        controls = layer["controls"]
        layers[layer["id"]] = _score(controls)
        controls_by_id.update({item["id"]: item for item in controls})

    internal_controls = [
        *manifest["layers"][0]["controls"],
        *manifest["layers"][1]["controls"],
    ]
    all_controls = [
        item
        for layer in manifest["layers"]
        for item in layer["controls"]
    ]
    actionable = []
    layer_by_control = {
        control["id"]: layer
        for layer in manifest["layers"]
        for control in layer["controls"]
    }
    for control in all_controls:
        if control["status"] == "verified":
            continue
        if all(
            controls_by_id[dependency]["status"] == "verified"
            for dependency in control["dependencies"]
        ):
            actionable.append(
                {
                    "id": control["id"],
                    "status": control["status"],
                    "next_task": control["next_task"],
                    "blocker": control["blocker"],
                    "execution_class": control.get(
                        "execution_class",
                        layer_by_control[control["id"]]["default_execution_class"],
                    ),
                }
            )
    safe_actionable = [
        item for item in actionable if item["execution_class"] == "repository_offline"
    ]
    return {
        "version": "noteai-internal-deployment-readiness-v1",
        "task_id": manifest["task_id"],
        "manifest_valid": True,
        "layers": layers,
        "internal_deployment": _score(internal_controls),
        "complete_public_launch": _score(all_controls),
        "actionable": actionable,
        "next_safe_task": safe_actionable[0] if safe_actionable else None,
        "accepted_risks": [
            {
                "control_id": control["id"],
                "risk_id": risk["id"],
                "readiness_credit": risk["readiness_credit"],
                "not_verified_fixed": risk["not_verified_fixed"],
            }
            for control in all_controls
            for risk in control.get("accepted_risks", [])
        ],
        "blocked": [
            {
                "id": control["id"],
                "resume_condition": control["resume_condition"],
            }
            for control in all_controls
            if control["status"] == "blocked"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute fail-closed NoteAI deployment readiness."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require",
        choices=("manifest", "repository", "internal", "public"),
        default="manifest",
        help="Return non-zero unless the selected evidence layer is complete.",
    )
    args = parser.parse_args()
    try:
        report = build_report(args.manifest)
    except ManifestError as exc:
        print(f"internal_deployment_readiness=INVALID\nerror={exc}")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        internal = report["internal_deployment"]
        public = report["complete_public_launch"]
        print(
            "internal_deployment_readiness="
            f"{internal['percentage']}% ({internal['verified']}/{internal['total']})"
        )
        print(
            "complete_public_launch_readiness="
            f"{public['percentage']}% ({public['verified']}/{public['total']})"
        )
        for item in report["actionable"]:
            print(f"- {item['status']}: {item['next_task']} ({item['id']})")

    required = {
        "manifest": True,
        "repository": report["layers"]["repository_isolated"]["passed"],
        "internal": report["internal_deployment"]["passed"],
        "public": report["complete_public_launch"]["passed"],
    }[args.require]
    return 0 if required else 1


if __name__ == "__main__":
    raise SystemExit(main())
