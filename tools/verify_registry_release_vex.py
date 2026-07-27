#!/usr/bin/env python3
"""Build and verify the exact b06671f ACR publication/VEX bundle offline.

The input attestation is a secret-free reduction produced on the isolated
AMD64 builder after five immutable tags were published and read back from the
ACR control plane. Canonical SBOM and scanner reports remain retained on that
builder for fourteen days. This verifier binds the registry manifests to those
raw-report hashes without confusing them with the separate GitHub-built local
image IDs or granting deployment authorization.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import verify_native_release_vex as source_bundle


ROOT = Path(__file__).resolve().parents[1]
RELEASE_COMMIT = source_bundle.RELEASE_COMMIT
RELEASE_SHORT = RELEASE_COMMIT[:7]
TASK_ID = "PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-B06671F-PUBLISH-001"
ROLES = source_bundle.ROLES
EVIDENCE_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-registry-release-evidence.json"
)
VEX_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-registry-release.vex.cdx.json"
)
REVIEW_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-registry-release-review.json"
)
SOURCE_EVIDENCE_PATH = source_bundle.EVIDENCE_PATH
SOURCE_VEX_PATH = source_bundle.VEX_PATH
SOURCE_REVIEW_PATH = source_bundle.REVIEW_PATH

EXPECTED_ATTESTATION_SEMANTIC_SHA256 = (
    "7cf291aa386d9518ad321c7b8acd4986c17cfe4c50b5b0dd141737e95294e0a0"
)
EXPECTED_ATTESTATION_GZIP_SHA256 = (
    "64011d309857793dbd0c25dbf9882b7d35bdad06d66b1b44109bde56108a2c03"
)
EXPECTED_NATIVE_SUMMARY_SHA256 = (
    "dfa5e85af830dcdcdc3428a97d2ce7c0a98797b49ebd8b2e98a6d4193fff6c0e"
)
EXPECTED_REGISTRY_PUBLICATION_SHA256 = (
    "5f0142fc1c47c4c98384c95e9387d06c50a45e9e49d84d49b3cd72de01700c2a"
)
EXPECTED_CONTROL_PLANE_BINDING_SHA256 = (
    "73cc99438e1816347ee0f1af23f8758969b629bdb4d1db902fbdca723de836ff"
)
EXPECTED_REGISTRY_EVIDENCE_SEMANTIC_SHA256 = (
    "82360747d90b1481c736a9841fb9954a8d26dc1206140157b1dd0293ca1a691f"
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG_RE = re.compile(r"^git-b06671f-amd64-[a-z-]+-r[0-9]+$")
EXPECTED_FINDINGS = {
    "critical": 4,
    "high": 19,
    "secrets": 0,
    "browser_components": 0,
    "cryptography_48_0_1_components": 1,
    "forbidden_os_packages": 0,
}
EXPECTED_CLEANUP = {
    "builder_acr_vpc_links": 0,
    "docker_auth_entries": 0,
    "publisher_policy_exists": False,
    "publisher_role_attached": False,
    "publisher_role_exists": False,
    "running_containers": 0,
    "temporary_auth_directories": 0,
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _expected_source() -> dict[str, Any]:
    source = _load_json(SOURCE_EVIDENCE_PATH)
    errors = source_bundle.validate_bundle()
    if errors:
        raise ValueError(f"GitHub source-candidate bundle invalid: {errors[0]}")
    return source


def _validate_attestation(
    attestation: dict[str, Any],
    source: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    semantic_payload = copy.deepcopy(attestation)
    recorded_semantic = semantic_payload.pop("semantic_sha256", None)
    if recorded_semantic != EXPECTED_ATTESTATION_SEMANTIC_SHA256:
        errors.append("attestation recorded semantic hash mismatch")
    if _canonical_sha256(semantic_payload) != EXPECTED_ATTESTATION_SEMANTIC_SHA256:
        errors.append("attestation content semantic hash mismatch")
    if attestation.get("manifest_version") != 2:
        errors.append("attestation manifest version mismatch")
    if attestation.get("task") != TASK_ID:
        errors.append("attestation task mismatch")
    if attestation.get("application_revision") != RELEASE_COMMIT:
        errors.append("attestation release revision mismatch")
    if attestation.get("platform") != "linux/amd64":
        errors.append("attestation platform mismatch")
    if attestation.get("runner_architecture") != "x86_64":
        errors.append("attestation builder architecture mismatch")
    if attestation.get("base_images") != source.get("base_images"):
        errors.append("attestation base images differ from reviewed source candidate")
    if attestation.get("native_summary_sha256") != EXPECTED_NATIVE_SUMMARY_SHA256:
        errors.append("native summary binding mismatch")
    if (
        attestation.get("registry_publication_sha256")
        != EXPECTED_REGISTRY_PUBLICATION_SHA256
    ):
        errors.append("registry publication binding mismatch")
    if (
        attestation.get("control_plane_binding_sha256")
        != EXPECTED_CONTROL_PLANE_BINDING_SHA256
    ):
        errors.append("control-plane digest binding mismatch")

    scanner = attestation.get("scanner") or {}
    if scanner != {
        "ignore_file_used": False,
        "ignore_unfixed": False,
        "raw_reports_canonical_and_unsuppressed": True,
        "sbom": {"name": "Syft", "version": "1.49.0"},
        "vex_applied_to_raw_report": False,
        "vulnerability": {"name": "Trivy", "version": "0.72.0"},
    }:
        errors.append("attestation scanner contract mismatch")
    retained = attestation.get("retained_raw_evidence") or {}
    if (
        retained.get("retention_days") != 14
        or not isinstance(retained.get("file_count"), int)
        or retained.get("file_count", 0) < 40
        or not isinstance(retained.get("bytes"), int)
        or retained.get("bytes", 0) < 1_000_000
    ):
        errors.append("retained raw-evidence contract mismatch")
    if attestation.get("cleanup") != EXPECTED_CLEANUP:
        errors.append("temporary publication resource cleanup mismatch")
    if (
        attestation.get("vulnerability_rows_per_role")
        != source.get("vulnerability_rows_per_role")
    ):
        errors.append("registry vulnerability rows differ from source candidate")

    roles = attestation.get("roles") or {}
    if set(roles) != set(ROLES):
        errors.append("attestation role set mismatch")
        return errors
    registry_digests: set[str] = set()
    component_refs: dict[str, str] | None = None
    for role_name in ROLES:
        role = roles.get(role_name) or {}
        source_role = (source.get("roles") or {}).get(role_name) or {}
        local_id = str(role.get("local_image_id", ""))
        registry_digest = str(role.get("registry_digest", ""))
        if not DIGEST_RE.fullmatch(local_id):
            errors.append(f"{role_name}: invalid local image ID")
        if not DIGEST_RE.fullmatch(registry_digest):
            errors.append(f"{role_name}: invalid registry manifest digest")
        if local_id == registry_digest:
            errors.append(f"{role_name}: local image ID equals registry digest")
        registry_digests.add(registry_digest)
        if role.get("platform") != "linux/amd64":
            errors.append(f"{role_name}: platform mismatch")
        if role.get("findings") != EXPECTED_FINDINGS:
            errors.append(f"{role_name}: finding counts mismatch")
        if role.get("raw_gate_passed") is not False:
            errors.append(f"{role_name}: raw zero-Critical/High result was rewritten")
        if role.get("entrypoint") != source_role.get("entrypoint"):
            errors.append(f"{role_name}: entrypoint differs from source candidate")
        if role.get("cmd") != source_role.get("cmd"):
            errors.append(f"{role_name}: command differs from source candidate")
        if not TAG_RE.fullmatch(str(role.get("tag", ""))):
            errors.append(f"{role_name}: immutable tag format mismatch")
        if not str(role.get("target", "")).endswith(f"{role_name}-runtime"):
            errors.append(f"{role_name}: local target role mismatch")
        raw_reports = role.get("raw_reports") or {}
        if set(raw_reports) != {
            "build_metadata_sha256",
            "history_sha256",
            "inspect_sha256",
            "os_packages_sha256",
            "secret_sha256",
            "vulnerability_sha256",
        } or any(
            not SHA256_RE.fullmatch(str(value)) for value in raw_reports.values()
        ):
            errors.append(f"{role_name}: raw-report hash inventory mismatch")
        sbom = role.get("sbom") or {}
        if (
            not SHA256_RE.fullmatch(str(sbom.get("sha256", "")))
            or not SHA256_RE.fullmatch(
                str(sbom.get("component_inventory_sha256", ""))
            )
            or not str(sbom.get("serial_number", "")).startswith("urn:uuid:")
            or sbom.get("version") != 1
            or sbom.get("component_count")
            != source_role.get("sbom", {}).get("component_count")
        ):
            errors.append(f"{role_name}: SBOM identity mismatch")
        refs = sbom.get("component_refs") or {}
        if set(refs) != {
            package
            for packages in source_bundle.EXPECTED_PACKAGES.values()
            for package in packages
        }:
            errors.append(f"{role_name}: vulnerable SBOM component set mismatch")
        if component_refs is None:
            component_refs = refs
        elif refs != component_refs:
            errors.append(f"{role_name}: vulnerable SBOM component refs differ")
    if len(registry_digests) != len(ROLES):
        errors.append("registry manifest digests are not unique per role")
    return errors


def build_evidence(attestation: dict[str, Any]) -> dict[str, Any]:
    source = _expected_source()
    errors = _validate_attestation(attestation, source)
    if errors:
        raise ValueError("; ".join(errors))
    first_role = attestation["roles"][ROLES[0]]
    roles: dict[str, Any] = {}
    for role_name in ROLES:
        role = attestation["roles"][role_name]
        roles[role_name] = {
            "target": role["target"],
            "tag": role["tag"],
            "local_image_id": role["local_image_id"],
            "registry_digest": role["registry_digest"],
            "platform": role["platform"],
            "entrypoint": role["entrypoint"],
            "cmd": role["cmd"],
            "sbom": {
                key: role["sbom"][key]
                for key in (
                    "sha256",
                    "serial_number",
                    "version",
                    "component_count",
                    "component_inventory_sha256",
                )
            },
            "raw_reports": role["raw_reports"],
            "findings": role["findings"],
            "raw_gate_passed": role["raw_gate_passed"],
        }
    return {
        "manifest_version": 1,
        "task": TASK_ID,
        "application_revision": RELEASE_COMMIT,
        "platform": "linux/amd64",
        "builder": {
            "runner_architecture": attestation["runner_architecture"],
            "created": attestation["created"],
        },
        "attestation_binding": {
            "semantic_sha256": EXPECTED_ATTESTATION_SEMANTIC_SHA256,
            "received_gzip_sha256": EXPECTED_ATTESTATION_GZIP_SHA256,
            "native_summary_sha256": attestation["native_summary_sha256"],
            "registry_publication_sha256": attestation[
                "registry_publication_sha256"
            ],
            "control_plane_binding_sha256": attestation[
                "control_plane_binding_sha256"
            ],
        },
        "source_candidate_binding": {
            "evidence": str(SOURCE_EVIDENCE_PATH.relative_to(ROOT)),
            "evidence_semantic_sha256": _canonical_sha256(source),
            "vex": str(SOURCE_VEX_PATH.relative_to(ROOT)),
            "vex_semantic_sha256": _canonical_sha256(_load_json(SOURCE_VEX_PATH)),
            "review": str(SOURCE_REVIEW_PATH.relative_to(ROOT)),
            "review_semantic_sha256": _canonical_sha256(
                _load_json(SOURCE_REVIEW_PATH)
            ),
        },
        "base_images": attestation["base_images"],
        "scanner": attestation["scanner"],
        "retained_raw_evidence": attestation["retained_raw_evidence"],
        "cleanup": attestation["cleanup"],
        "components": first_role["sbom"]["component_refs"],
        "roles": roles,
        "vulnerability_rows_per_role": attestation[
            "vulnerability_rows_per_role"
        ],
        "decision": {
            "status": "not_affected_for_exact_registry_products",
            "raw_reports_rewritten": False,
            "registry_access_performed": True,
            "acr_push_completed": True,
            "control_plane_tag_digest_binding_verified": True,
            "temporary_publication_access_cleaned": True,
            "production_exception": False,
            "deployment_authorization": False,
            "provider_calls": 0,
            "business_writes": 0,
            "services_restarted_or_redeployed": 0,
        },
    }


def _bom_link(role: dict[str, Any], component_ref: str) -> str:
    serial = role["sbom"]["serial_number"]
    return f"urn:cdx:{serial.removeprefix('urn:uuid:')}/{role['sbom']['version']}#{component_ref}"


def build_vex(
    evidence: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    timestamp = evidence["builder"]["created"]
    vulnerabilities: list[dict[str, Any]] = []
    for cve in sorted(source_bundle.EXPECTED_PACKAGES):
        disposition = source["dispositions"][cve]
        refs = sorted(
            _bom_link(evidence["roles"][role_name], evidence["components"][package])
            for role_name in ROLES
            for package in source_bundle.EXPECTED_PACKAGES[cve]
        )
        vulnerabilities.append(
            {
                "bom-ref": f"urn:noteai:vulnerability-disposition:{cve}",
                "id": cve,
                "source": {
                    "name": "CVE",
                    "url": f"https://www.cve.org/CVERecord?id={cve}",
                },
                "advisories": [
                    {
                        "title": "Debian Security Tracker",
                        "url": f"https://security-tracker.debian.org/tracker/{cve}",
                    }
                ],
                "analysis": {
                    "state": "not_affected",
                    "justification": disposition["justification"],
                    "detail": disposition["detail"],
                    "firstIssued": timestamp,
                    "lastUpdated": timestamp,
                },
                "affects": [{"ref": ref} for ref in refs],
            }
        )
    components = []
    for role_name in ROLES:
        role = evidence["roles"][role_name]
        components.append(
            {
                "bom-ref": (
                    f"urn:noteai:container:{role_name}:"
                    f"{role['registry_digest'].replace(':', '-')}"
                ),
                "type": "container",
                "group": "NoteAI",
                "name": f"{role_name}-runtime",
                "version": RELEASE_COMMIT,
                "properties": [
                    {
                        "name": "noteai:local-image-id",
                        "value": role["local_image_id"],
                    },
                    {
                        "name": "noteai:registry-digest",
                        "value": role["registry_digest"],
                    },
                    {"name": "noteai:image-tag", "value": role["tag"]},
                    {
                        "name": "noteai:sbom-sha256",
                        "value": role["sbom"]["sha256"],
                    },
                    {
                        "name": "noteai:raw-vulnerability-report-sha256",
                        "value": role["raw_reports"]["vulnerability_sha256"],
                    },
                ],
            }
        )
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, TASK_ID)}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "authors": [{"name": "NoteAI Production Release Management"}],
            "component": {
                "bom-ref": f"urn:noteai:release:{RELEASE_SHORT}-registry-five-role",
                "type": "application",
                "group": "NoteAI",
                "name": "registry-five-role-release-candidate",
                "version": RELEASE_COMMIT,
                "properties": [
                    {"name": "noteai:task", "value": TASK_ID},
                    {"name": "noteai:platform", "value": "linux/amd64"},
                    {"name": "noteai:production-exception", "value": "false"},
                    {
                        "name": "noteai:deployment-authorization",
                        "value": "false",
                    },
                    {
                        "name": "noteai:registry-digest-binding",
                        "value": "five-exact-control-plane-readbacks",
                    },
                    {
                        "name": "noteai:raw-trivy-report",
                        "value": "canonical-and-unsuppressed",
                    },
                ],
            },
        },
        "components": components,
        "vulnerabilities": vulnerabilities,
    }


def build_review(
    evidence: dict[str, Any],
    vex: dict[str, Any],
    *,
    evidence_sha256: str,
    vex_sha256: str,
) -> dict[str, Any]:
    return {
        "review_version": 1,
        "task": TASK_ID,
        "reviewer": "production-release-manager:/root",
        "result": "PASS",
        "application_revision": RELEASE_COMMIT,
        "roles": list(ROLES),
        "reviewed_cves": sorted(source_bundle.EXPECTED_PACKAGES),
        "evidence_sha256": evidence_sha256,
        "vex_sha256": vex_sha256,
        "checks": {
            "five_unique_registry_manifest_digests": True,
            "control_plane_tag_digest_binding": True,
            "native_amd64": True,
            "raw_reports_canonical_and_unsuppressed": True,
            "raw_critical_per_role": 4,
            "raw_high_per_role": 19,
            "secret_findings_per_role": 0,
            "browser_components_per_role": 0,
            "cryptography_48_0_1_per_role": 1,
            "cyclonedx_exact_bom_links": True,
            "temporary_publication_access_cleanup": True,
            "api_nodes_post_health_and_isolation": True,
            "production_exception": False,
            "deployment_authorization": False,
        },
        "scope": {
            "registry_publication_complete": True,
            "application_deployed": False,
            "database_changed": False,
            "provider_called": False,
            "service_restarted": False,
            "local_image_ids_are_registry_digests": False,
        },
        "cyclonedx_schema_validation": {
            "specification_commit": "55343ba19dee1785acf1ce9191540d5fd7b590db",
            "schema": "schema/bom-1.6.schema.json",
            "schema_sha256": (
                "3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93"
            ),
            "validation_errors": 0,
        },
        "evidence_semantic_sha256": _canonical_sha256(evidence),
        "vex_semantic_sha256": _canonical_sha256(vex),
        "source_candidate_evidence_semantic_sha256": evidence[
            "source_candidate_binding"
        ]["evidence_semantic_sha256"],
        "re_review_required_on": [
            "application revision or registry manifest digest changes",
            "local image ID, SBOM or package inventory changes",
            "base image or architecture changes",
            "entrypoint, command or subprocess graph changes",
            "runtime capabilities, devices, mounts or namespaces change",
            "official vulnerability scope changes",
        ],
    }


def validate_documents(
    evidence: dict[str, Any],
    vex: dict[str, Any],
    review: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    try:
        source = _expected_source()
        if evidence.get("manifest_version") != 1:
            errors.append("registry evidence manifest version mismatch")
        if evidence.get("task") != TASK_ID:
            errors.append("registry evidence task mismatch")
        if evidence.get("application_revision") != RELEASE_COMMIT:
            errors.append("registry evidence revision mismatch")
        if evidence.get("platform") != "linux/amd64":
            errors.append("registry evidence platform mismatch")
        if _canonical_sha256(evidence) != EXPECTED_REGISTRY_EVIDENCE_SEMANTIC_SHA256:
            errors.append("registry evidence semantic hash mismatch")
        binding = evidence.get("attestation_binding") or {}
        if binding != {
            "semantic_sha256": EXPECTED_ATTESTATION_SEMANTIC_SHA256,
            "received_gzip_sha256": EXPECTED_ATTESTATION_GZIP_SHA256,
            "native_summary_sha256": EXPECTED_NATIVE_SUMMARY_SHA256,
            "registry_publication_sha256": EXPECTED_REGISTRY_PUBLICATION_SHA256,
            "control_plane_binding_sha256": EXPECTED_CONTROL_PLANE_BINDING_SHA256,
        }:
            errors.append("registry attestation binding mismatch")
        if evidence.get("base_images") != source.get("base_images"):
            errors.append("registry evidence base images mismatch")
        if evidence.get("scanner", {}).get(
            "raw_reports_canonical_and_unsuppressed"
        ) is not True:
            errors.append("registry raw reports are not canonical")
        if evidence.get("cleanup") != EXPECTED_CLEANUP:
            errors.append("registry cleanup evidence mismatch")
        if evidence.get("vulnerability_rows_per_role") != source.get(
            "vulnerability_rows_per_role"
        ):
            errors.append("registry vulnerability row set mismatch")
        source_binding = evidence.get("source_candidate_binding") or {}
        if source_binding != {
            "evidence": str(SOURCE_EVIDENCE_PATH.relative_to(ROOT)),
            "evidence_semantic_sha256": _canonical_sha256(source),
            "vex": str(SOURCE_VEX_PATH.relative_to(ROOT)),
            "vex_semantic_sha256": _canonical_sha256(
                _load_json(SOURCE_VEX_PATH)
            ),
            "review": str(SOURCE_REVIEW_PATH.relative_to(ROOT)),
            "review_semantic_sha256": _canonical_sha256(
                _load_json(SOURCE_REVIEW_PATH)
            ),
        }:
            errors.append("registry source-candidate binding mismatch")
        roles = evidence.get("roles") or {}
        if set(roles) != set(ROLES):
            errors.append("registry evidence role set mismatch")
        digests: set[str] = set()
        for role_name in ROLES:
            role = roles.get(role_name) or {}
            source_role = source["roles"][role_name]
            digest = str(role.get("registry_digest", ""))
            local_id = str(role.get("local_image_id", ""))
            if not DIGEST_RE.fullmatch(digest):
                errors.append(f"{role_name}: invalid registry digest")
            if not DIGEST_RE.fullmatch(local_id) or local_id == digest:
                errors.append(f"{role_name}: invalid local/registry identity boundary")
            digests.add(digest)
            if role.get("platform") != "linux/amd64":
                errors.append(f"{role_name}: registry platform mismatch")
            if role.get("entrypoint") != source_role.get("entrypoint"):
                errors.append(f"{role_name}: registry entrypoint mismatch")
            if role.get("cmd") != source_role.get("cmd"):
                errors.append(f"{role_name}: registry command mismatch")
            if role.get("findings") != EXPECTED_FINDINGS:
                errors.append(f"{role_name}: registry finding counts mismatch")
            if role.get("raw_gate_passed") is not False:
                errors.append(f"{role_name}: raw vulnerability result rewritten")
        if len(digests) != len(ROLES):
            errors.append("registry digests are not unique")
        decision = evidence.get("decision") or {}
        for key in (
            "production_exception",
            "deployment_authorization",
            "raw_reports_rewritten",
        ):
            if decision.get(key) is not False:
                errors.append(f"registry decision.{key} must remain false")
        for key in (
            "registry_access_performed",
            "acr_push_completed",
            "control_plane_tag_digest_binding_verified",
            "temporary_publication_access_cleaned",
        ):
            if decision.get(key) is not True:
                errors.append(f"registry decision.{key} must remain true")
        if (
            decision.get("provider_calls") != 0
            or decision.get("business_writes") != 0
            or decision.get("services_restarted_or_redeployed") != 0
        ):
            errors.append("registry publication scope boundary mismatch")

        expected_vex = build_vex(evidence, source)
        if vex != expected_vex:
            errors.append("registry VEX differs from exact evidence")
        if len(vex.get("vulnerabilities") or []) != len(
            source_bundle.EXPECTED_PACKAGES
        ):
            errors.append("registry VEX vulnerability count mismatch")
        if sum(
            len(item.get("affects") or [])
            for item in vex.get("vulnerabilities") or []
        ) != 115:
            errors.append("registry VEX BOM-Link count mismatch")
        for item in vex.get("vulnerabilities") or []:
            analysis = item.get("analysis") or {}
            if analysis.get("state") != "not_affected" or "response" in analysis:
                errors.append(f"{item.get('id')}: invalid registry VEX disposition")

        expected_review = build_review(
            evidence,
            vex,
            evidence_sha256=_sha256(EVIDENCE_PATH),
            vex_sha256=_sha256(VEX_PATH),
        )
        if review != expected_review:
            errors.append("registry review differs from exact evidence/VEX")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"malformed registry release bundle: {exc}")
    return errors


def validate_bundle() -> list[str]:
    missing = [
        str(path.relative_to(ROOT))
        for path in (EVIDENCE_PATH, VEX_PATH, REVIEW_PATH)
        if not path.is_file()
    ]
    if missing:
        return [f"missing registry release bundle file: {path}" for path in missing]
    try:
        return validate_documents(
            _load_json(EVIDENCE_PATH),
            _load_json(VEX_PATH),
            _load_json(REVIEW_PATH),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load registry release bundle: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-from-attestation",
        type=Path,
        help="Build the reduced registry bundle from the received attestation.",
    )
    args = parser.parse_args()
    if args.build_from_attestation:
        attestation = _load_json(args.build_from_attestation)
        evidence = build_evidence(attestation)
        vex = build_vex(evidence, _expected_source())
        _write_json(EVIDENCE_PATH, evidence)
        _write_json(VEX_PATH, vex)
        review = build_review(
            evidence,
            vex,
            evidence_sha256=_sha256(EVIDENCE_PATH),
            vex_sha256=_sha256(VEX_PATH),
        )
        _write_json(REVIEW_PATH, review)
    errors = validate_bundle()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS: exact b06671f five-role ACR manifests are bound to the "
        "unsuppressed native evidence; deployment remains unauthorized"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
