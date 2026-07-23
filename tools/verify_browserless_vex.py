#!/usr/bin/env python3
"""Validate the exact-product browserless VEX evidence bundle.

This verifier is intentionally offline. It does not apply VEX to Trivy output,
contact vulnerability feeds, or inspect registries. It verifies the exact ACR
manifest digests recorded by the separately authorized PROD-IMG-002 read-back
without ever treating local image IDs as registry digests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VEX_PATH = ROOT / "security" / "vex" / "a635692-browserless.vex.cdx.json"
EVIDENCE_PATH = ROOT / "security" / "vex" / "a635692-browserless-evidence.json"
REVIEW_PATH = ROOT / "security" / "vex" / "a635692-browserless-review.json"
APPLICATION_REVISION = "a635692a899ee02c6905cd694611c14e0da4594a"
ROLE_NAMES = ("api", "admin", "xhs-http")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LOCAL_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REGISTRY_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REGISTRY_HOST = "noteai-prod-shenzhen-registry.cn-shenzhen.cr.aliyuncs.com"
REGISTRY_REPOSITORY = f"{REGISTRY_HOST}/noteai/app"
EXPECTED_REGISTRY = {
    "api": {
        "tag": "git-a635692-amd64-api-r1",
        "digest": "sha256:17706e1802afc136ac8f9a621d4199a719749da73329ee923e42268eff42e0d1",
    },
    "admin": {
        "tag": "git-a635692-amd64-admin-r1",
        "digest": "sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d676c733",
    },
    "xhs-http": {
        "tag": "git-a635692-amd64-xhs-http-r1",
        "digest": "sha256:452c2faf7853ce58d93e43c5bf6217a99a6cce14c81345d8cef2f5accabd79af",
    },
}

EXPECTED_PACKAGES = {
    "CVE-2026-13221": ("perl-base",),
    "CVE-2026-42496": ("perl-base",),
    "CVE-2026-57433": ("perl-base",),
    "CVE-2026-8376": ("perl-base",),
    "CVE-2025-69720": ("libncursesw6", "libtinfo6", "ncurses-base", "ncurses-bin"),
    "CVE-2026-41992": ("gzip",),
    "CVE-2026-42497": ("perl-base",),
    "CVE-2026-48962": ("perl-base",),
    "CVE-2026-53615": (
        "bsdutils",
        "libblkid1",
        "liblastlog2-2",
        "libmount1",
        "libsmartcols1",
        "libuuid1",
        "login",
        "mount",
        "util-linux",
    ),
    "CVE-2026-54369": ("libacl1",),
    "CVE-2026-57432": ("perl-base",),
    "CVE-2026-9538": ("perl-base",),
}
EXPECTED_JUSTIFICATIONS = {
    "CVE-2026-13221": "code_not_reachable",
    "CVE-2026-42496": "code_not_present",
    "CVE-2026-57433": "code_not_present",
    "CVE-2026-8376": "requires_environment",
    "CVE-2025-69720": "code_not_reachable",
    "CVE-2026-41992": "code_not_reachable",
    "CVE-2026-42497": "code_not_present",
    "CVE-2026-48962": "code_not_present",
    "CVE-2026-53615": "code_not_reachable",
    "CVE-2026-54369": "code_not_reachable",
    "CVE-2026-57432": "code_not_reachable",
    "CVE-2026-9538": "code_not_present",
}
EXPECTED_COMPONENTS = {
    "bsdutils": "pkg:deb/debian/bsdutils@2.41-5?arch=amd64&distro=debian-13.6&epoch=1",
    "gzip": "pkg:deb/debian/gzip@1.13-1?arch=amd64&distro=debian-13.6",
    "libacl1": "pkg:deb/debian/libacl1@2.3.2-2%2Bb1?arch=amd64&distro=debian-13.6",
    "libblkid1": "pkg:deb/debian/libblkid1@2.41-5?arch=amd64&distro=debian-13.6",
    "liblastlog2-2": "pkg:deb/debian/liblastlog2-2@2.41-5?arch=amd64&distro=debian-13.6",
    "libmount1": "pkg:deb/debian/libmount1@2.41-5?arch=amd64&distro=debian-13.6",
    "libncursesw6": "pkg:deb/debian/libncursesw6@6.5%2B20250216-2?arch=amd64&distro=debian-13.6",
    "libsmartcols1": "pkg:deb/debian/libsmartcols1@2.41-5?arch=amd64&distro=debian-13.6",
    "libtinfo6": "pkg:deb/debian/libtinfo6@6.5%2B20250216-2?arch=amd64&distro=debian-13.6",
    "libuuid1": "pkg:deb/debian/libuuid1@2.41-5?arch=amd64&distro=debian-13.6",
    "login": "pkg:deb/debian/login@4.16.0-2%2Breally2.41-5?arch=amd64&distro=debian-13.6&epoch=1",
    "mount": "pkg:deb/debian/mount@2.41-5?arch=amd64&distro=debian-13.6",
    "ncurses-base": "pkg:deb/debian/ncurses-base@6.5%2B20250216-2?arch=all&distro=debian-13.6",
    "ncurses-bin": "pkg:deb/debian/ncurses-bin@6.5%2B20250216-2?arch=amd64&distro=debian-13.6",
    "perl-base": "pkg:deb/debian/perl-base@5.40.1-6?arch=amd64&distro=debian-13.6",
    "util-linux": "pkg:deb/debian/util-linux@2.41-5?arch=amd64&distro=debian-13.6",
}
EXPECTED_EVIDENCE = {
    "manifest_version": 2,
    "task": "PROD-IMG-002",
    "application_revision": APPLICATION_REVISION,
    "platform": "linux/amd64",
    "base_image": {
        "name": "python:3.11.15-slim-trixie",
        "index_digest": "sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93",
        "amd64_child_digest": "sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045",
    },
    "scanner": {
        "name": "Trivy",
        "version": "0.70.0",
        "database_date": "2026-07-23",
        "database_metadata_path": "/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/trivy-db-metadata.json",
        "database_metadata_sha256": "d633ce44665171118fcfb016dea65891878f1638e3dd5c987fc1ac2d1018e71a",
        "ignore_file_used": False,
        "vex_applied": False,
        "ignore_unfixed": False,
        "raw_report_is_canonical": True,
    },
    "registry": {
        "provider": "Alibaba Cloud ACR Enterprise",
        "region": "cn-shenzhen",
        "instance_id": "cri-xpuhaclqkxlwy47t",
        "repository": "noteai/app",
        "public_host": REGISTRY_HOST,
        "tags_immutable": True,
        "readback_method": "authenticated tag pull plus local OCI inspect",
        "temporary_access_cleanup": {
            "docker_logout": True,
            "builder_cidr_removed": True,
            "public_endpoint_disabled": True,
            "session_manager_disabled": True,
            "security_group_ingress_modified": False,
        },
    },
    "roles": {
        "api": {
            "image": f"{REGISTRY_REPOSITORY}:git-a635692-amd64-api-r1",
            "local_image": "noteai-local:git-a635692-amd64-api-r1",
            "local_image_id": "sha256:b1983bab928ef93495d8be020030917d4ae54364234390047c3163af5414fedb",
            "registry_digest": EXPECTED_REGISTRY["api"]["digest"],
            "registry_reference": f"{REGISTRY_REPOSITORY}@{EXPECTED_REGISTRY['api']['digest']}",
            "registry_platform": "linux/amd64",
            "sbom_path": "/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/api-sbom.cdx.json",
            "sbom_sha256": "59a4cabaa7debfb81684ac3a77c7467454d1c98ef04d64aeade4850b07d918be",
            "sbom_serial_number": "urn:uuid:9b5dc0cf-276b-42a8-8cde-aae5d0676dc5",
            "sbom_version": 1,
            "trivy_path": "/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/api-vuln-high-critical.json",
            "trivy_sha256": "92d8bab2f8b58f4ed2a9469aaca8a73ee9985d8a97999ab7ff81efba68c20eda",
            "constraint_proof_path": "/opt/noteai-build/evidence-a635692-constraint-proof-r1/api-elf-reachability.json",
            "constraint_proof_sha256": "9eb515761c9c1f52465a1460e426cb6d1995e6384daeaa88c1f3574b5c74b7bb",
            "runtime_constraints_path": "/opt/noteai-build/evidence-a635692-constraint-proof-r1/api-runtime-constraints.txt",
            "runtime_constraints_sha256": "f0a1925f1b0711d145bc2899443c1a56002e78becbbe24b57175ce62d182d386",
        },
        "admin": {
            "image": f"{REGISTRY_REPOSITORY}:git-a635692-amd64-admin-r1",
            "local_image": "noteai-local:git-a635692-amd64-admin-r1",
            "local_image_id": "sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f",
            "registry_digest": EXPECTED_REGISTRY["admin"]["digest"],
            "registry_reference": f"{REGISTRY_REPOSITORY}@{EXPECTED_REGISTRY['admin']['digest']}",
            "registry_platform": "linux/amd64",
            "sbom_path": "/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/admin-sbom.cdx.json",
            "sbom_sha256": "136ace76eaaaed1d7ded40d54bb5162cbd28bb79069a310694913e847d1f6cd7",
            "sbom_serial_number": "urn:uuid:ae2ab874-1774-4af7-ad42-ce7cad5c876b",
            "sbom_version": 1,
            "trivy_path": "/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/admin-vuln-high-critical.json",
            "trivy_sha256": "e38d2a754a74133b93538545473cc3a1758403a1389fc34a028a3d81bc1e44b8",
            "constraint_proof_path": "/opt/noteai-build/evidence-a635692-constraint-proof-r1/admin-elf-reachability.json",
            "constraint_proof_sha256": "d2f33801b80f66352f1922f8be81a9fab95d9ec7f8d6d553d05f442ebcb4d6eb",
            "runtime_constraints_path": "/opt/noteai-build/evidence-a635692-constraint-proof-r1/admin-runtime-constraints.txt",
            "runtime_constraints_sha256": "dfba225a01155562e3c3e776c9dbdacaa06791fc82269edaa77da21346930ff1",
        },
        "xhs-http": {
            "image": f"{REGISTRY_REPOSITORY}:git-a635692-amd64-xhs-http-r1",
            "local_image": "noteai-local:git-a635692-amd64-xhs-http-r1",
            "local_image_id": "sha256:5b44114d4bd9c28a8e93c39140466c542e8babeead038fb0d1cfe45c3cd75966",
            "registry_digest": EXPECTED_REGISTRY["xhs-http"]["digest"],
            "registry_reference": f"{REGISTRY_REPOSITORY}@{EXPECTED_REGISTRY['xhs-http']['digest']}",
            "registry_platform": "linux/amd64",
            "sbom_path": "/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/xhs-http-sbom.cdx.json",
            "sbom_sha256": "a27663349c7af6ebdfdfbd16bf6ef2c189b420115405304ac26565249aa6a92e",
            "sbom_serial_number": "urn:uuid:4073a9eb-1d9b-49b3-8dc1-7bfbfec21514",
            "sbom_version": 1,
            "trivy_path": "/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/xhs-http-vuln-high-critical.json",
            "trivy_sha256": "f91e706a8e058fa60952b74246fb9a156b68cb698e6379ccc9a6aed79f744932",
            "constraint_proof_path": "/opt/noteai-build/evidence-a635692-constraint-proof-r1/xhs-http-elf-reachability.json",
            "constraint_proof_sha256": "d4c707612914dd989044ae65bdc45d06021072737a4511ec9207445a2d1f554e",
            "runtime_constraints_path": "/opt/noteai-build/evidence-a635692-constraint-proof-r1/xhs-runtime-constraints.txt",
            "runtime_constraints_sha256": "cfaa10444c2553af478e0ca9b54b900d140b8c6f3aa5b2e03d713c8517132031",
        },
    },
    "constraint_proof": {
        "manifest_path": "/opt/noteai-build/evidence-a635692-constraint-proof-r1/SHA256SUMS",
        "manifest_sha256": "6bcdb87db13e95cdf04eebcca332abc8138c61b62b0759b3c49994d9f9f6bd1f",
        "evidence_script_sha256": "75b7d8393de4e259fcc6303ecffa51a063b59266fc10dfe357fedaf7524221e6",
        "elf_records_per_role": 1203,
        "accepted_roots_per_role": 354,
        "reachable_objects_per_role": 377,
        "libblkid_reachable": False,
        "libacl_reachable": False,
        "runtime_contract": {
            "uid_gid": "999:999",
            "cap_drop_all": True,
            "no_new_privileges": True,
            "read_only_root": True,
            "privileged": False,
            "devices": [],
            "host_namespaces": [],
        },
    },
    "components": EXPECTED_COMPONENTS,
    "cloud_assistant_audit": {
        "instance_id": "i-wz99180s9ig5ecq10uaj",
        "initial_evidence_execution_id": "t-sz06rsblbtnwphc",
        "initial_evidence_exit_code": 0,
        "failed_read_only_query_execution_id": "t-sz06rsbrezx6g3k",
        "failed_read_only_query_exit_code": 5,
        "final_bom_ref_execution_id": "t-sz06rsbupffva4g",
        "final_bom_ref_exit_code": 0,
        "production_instances_targeted": 0,
        "files_modified": 0,
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bom_link(role: dict[str, Any], component_ref: str) -> str:
    serial = role["sbom_serial_number"]
    if not serial.startswith("urn:uuid:"):
        return ""
    return f"urn:cdx:{serial.removeprefix('urn:uuid:')}/{role['sbom_version']}#{component_ref}"


def _check_expected_subset(
    actual: Any,
    expected: Any,
    path: str,
    errors: list[str],
) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            errors.append(f"{path}: expected object")
            return
        for key, value in expected.items():
            if key not in actual:
                errors.append(f"{path}.{key}: missing immutable evidence field")
                continue
            _check_expected_subset(actual[key], value, f"{path}.{key}", errors)
        return
    if actual != expected:
        errors.append(f"{path}: immutable evidence mismatch")


def validate_documents(
    vex: dict[str, Any],
    evidence: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []

    _check_expected_subset(evidence, EXPECTED_EVIDENCE, "evidence", errors)
    if evidence.get("task") != "PROD-IMG-002":
        errors.append("evidence task mismatch")
    if evidence.get("application_revision") != APPLICATION_REVISION:
        errors.append("evidence application revision mismatch")
    if evidence.get("platform") != "linux/amd64":
        errors.append("evidence platform is not linux/amd64")

    roles = evidence.get("roles") or {}
    if tuple(sorted(roles)) != tuple(sorted(ROLE_NAMES)):
        errors.append("evidence roles are not exactly api/admin/xhs-http")
    for role_name in ROLE_NAMES:
        role = roles.get(role_name) or {}
        if not LOCAL_IMAGE_ID_RE.fullmatch(str(role.get("local_image_id", ""))):
            errors.append(f"{role_name}: invalid local image ID")
        registry_digest = str(role.get("registry_digest", ""))
        if not REGISTRY_DIGEST_RE.fullmatch(registry_digest):
            errors.append(f"{role_name}: invalid registry manifest digest")
        if registry_digest == role.get("local_image_id"):
            errors.append(f"{role_name}: registry digest must not equal local image ID")
        expected_registry = EXPECTED_REGISTRY[role_name]
        if registry_digest != expected_registry["digest"]:
            errors.append(f"{role_name}: unexpected registry manifest digest")
        expected_tag = f"{REGISTRY_REPOSITORY}:{expected_registry['tag']}"
        expected_reference = f"{REGISTRY_REPOSITORY}@{expected_registry['digest']}"
        if role.get("image") != expected_tag:
            errors.append(f"{role_name}: registry tag mismatch")
        if role.get("registry_reference") != expected_reference:
            errors.append(f"{role_name}: immutable registry reference mismatch")
        if role.get("registry_platform") != "linux/amd64":
            errors.append(f"{role_name}: registry platform is not linux/amd64")
        if not str(role.get("sbom_serial_number", "")).startswith("urn:uuid:"):
            errors.append(f"{role_name}: invalid SBOM serial number")
        if role.get("sbom_version") != 1:
            errors.append(f"{role_name}: unexpected SBOM version")
        for field in (
            "sbom_sha256",
            "trivy_sha256",
            "constraint_proof_sha256",
            "runtime_constraints_sha256",
        ):
            if not SHA256_RE.fullmatch(str(role.get(field, ""))):
                errors.append(f"{role_name}: invalid {field}")

    raw = evidence.get("raw_report_expectation") or {}
    expected_counts = {
        "rows_per_role": 23,
        "critical_per_role": 4,
        "high_per_role": 19,
        "unique_cves_per_role": 12,
        "fixed_version_rows_per_role": 0,
        "pillow_rows_per_role": 0,
    }
    for key, value in expected_counts.items():
        if raw.get(key) != value:
            errors.append(f"raw report expectation drift: {key}")

    scope = evidence.get("scope_limit") or {}
    for key in (
        "local_image_ids_are_registry_digests",
        "valid_after_image_change",
        "valid_after_sbom_change",
        "valid_after_registry_push_without_reissue",
        "production_exception",
        "deployment_authorization",
    ):
        if scope.get(key) is not False:
            errors.append(f"scope limit must remain false: {key}")
    if scope.get("registry_digest_reissue_complete") is not True:
        errors.append("registry digest VEX reissue is not complete")

    components = evidence.get("components") or {}
    if components != EXPECTED_COMPONENTS:
        errors.append("evidence component set does not match scanner package rows")
    for package, purl in components.items():
        if not str(purl).startswith(f"pkg:deb/debian/{package}@"):
            errors.append(f"{package}: invalid Debian package BOM reference")

    if vex.get("$schema") != "http://cyclonedx.org/schema/bom-1.6.schema.json":
        errors.append("VEX must use the CycloneDX 1.6 JSON schema")
    if vex.get("bomFormat") != "CycloneDX" or vex.get("specVersion") != "1.6":
        errors.append("VEX is not CycloneDX 1.6")
    if not str(vex.get("serialNumber", "")).startswith("urn:uuid:"):
        errors.append("VEX serialNumber is invalid")
    if vex.get("version") != 2:
        errors.append("VEX registry reissue document version must be 2")

    metadata_component = (vex.get("metadata") or {}).get("component") or {}
    if metadata_component.get("version") != APPLICATION_REVISION:
        errors.append("VEX metadata component is not bound to a635692")
    metadata_properties = {
        prop.get("name"): prop.get("value")
        for prop in metadata_component.get("properties") or []
    }
    if metadata_properties.get("noteai:task") != "PROD-IMG-002":
        errors.append("VEX metadata task is not PROD-IMG-002")

    vex_components = vex.get("components") or []
    components_by_name = {item.get("name"): item for item in vex_components}
    if set(components_by_name) != {f"{name}-runtime" for name in ROLE_NAMES}:
        errors.append("VEX role components do not match the three candidates")
    for role_name in ROLE_NAMES:
        item = components_by_name.get(f"{role_name}-runtime") or {}
        role = roles.get(role_name) or {}
        properties = {
            prop.get("name"): prop.get("value")
            for prop in item.get("properties") or []
        }
        if properties.get("noteai:local-image-id") != role.get("local_image_id"):
            errors.append(f"{role_name}: VEX local image ID mismatch")
        if properties.get("noteai:application-revision") != APPLICATION_REVISION:
            errors.append(f"{role_name}: VEX application revision mismatch")
        if properties.get("noteai:image-tag") != role.get("image"):
            errors.append(f"{role_name}: VEX registry tag mismatch")
        if properties.get("noteai:local-image-tag") != role.get("local_image"):
            errors.append(f"{role_name}: VEX local image tag mismatch")
        if properties.get("noteai:registry-digest") != role.get("registry_digest"):
            errors.append(f"{role_name}: VEX registry digest mismatch")
        if properties.get("noteai:registry-reference") != role.get("registry_reference"):
            errors.append(f"{role_name}: VEX immutable registry reference mismatch")
        expected_bom_ref = (
            f"urn:noteai:container:{role_name}:"
            f"{role.get('registry_digest', '').replace(':', '-')}"
        )
        if item.get("bom-ref") != expected_bom_ref:
            errors.append(f"{role_name}: VEX component BOM reference is not digest-bound")
        bom_refs = [
            ref
            for ref in item.get("externalReferences") or []
            if ref.get("type") == "bom"
        ]
        if len(bom_refs) != 1:
            errors.append(f"{role_name}: expected one SBOM external reference")
        elif (
            bom_refs[0].get("url") != f"file://{role.get('sbom_path', '')}"
            or (bom_refs[0].get("hashes") or [{}])[0].get("content") != role.get("sbom_sha256")
        ):
            errors.append(f"{role_name}: SBOM external reference mismatch")

    vulnerabilities = vex.get("vulnerabilities") or []
    by_id = {item.get("id"): item for item in vulnerabilities}
    if len(vulnerabilities) != len(by_id):
        errors.append("VEX contains duplicate vulnerability IDs")
    if set(by_id) != set(EXPECTED_PACKAGES):
        errors.append("VEX does not contain exactly the twelve reviewed CVEs")

    for cve, packages in EXPECTED_PACKAGES.items():
        item = by_id.get(cve) or {}
        analysis = item.get("analysis") or {}
        if analysis.get("state") != "not_affected":
            errors.append(f"{cve}: state must be not_affected")
        if analysis.get("justification") != EXPECTED_JUSTIFICATIONS[cve]:
            errors.append(f"{cve}: justification mismatch")
        if not str(analysis.get("detail", "")).strip():
            errors.append(f"{cve}: missing analysis detail")
        if "response" in analysis:
            errors.append(f"{cve}: not_affected disposition must not claim a response/waiver")
        advisories = item.get("advisories") or []
        expected_advisory = f"https://security-tracker.debian.org/tracker/{cve}"
        if expected_advisory not in {advisory.get("url") for advisory in advisories}:
            errors.append(f"{cve}: missing Debian tracker advisory")

        expected_refs = {
            _bom_link(roles[role_name], components[package])
            for role_name in ROLE_NAMES
            for package in packages
        }
        actual_refs = {
            affected.get("ref")
            for affected in item.get("affects") or []
        }
        if actual_refs != expected_refs:
            errors.append(f"{cve}: exact SBOM BOM-Link set mismatch")

    if review is not None:
        if review.get("review_version") != 2:
            errors.append("registry reissue review version mismatch")
        if review.get("task") != "PROD-IMG-002":
            errors.append("registry reissue review task mismatch")
        if review.get("reviewer") != "production-release-manager:/root":
            errors.append("registry reissue reviewer identity mismatch")
        if review.get("result") != "PASS":
            errors.append("registry reissue review has not passed")
        if review.get("application_revision") != APPLICATION_REVISION:
            errors.append("registry reissue review revision mismatch")
        if set(review.get("reviewed_cves") or []) != set(EXPECTED_PACKAGES):
            errors.append("registry reissue review CVE set mismatch")
        prior_review = review.get("prior_independent_review") or {}
        if (
            prior_review.get("task") != "PROD-BROWSERLESS-VEX-REVIEW-001"
            or prior_review.get("reviewer")
            != "independent-verification-agent:/root/vex_final_verify"
            or prior_review.get("git_commit")
            != "5b3249995522a22dc600ee7501f9328121f4497c"
            or prior_review.get("result") != "PASS"
            or prior_review.get("vex_sha256")
            != "cf30b880f95c5b0b889bce79478b2b26aa71b66aee884c7380c9dbf9adde2746"
            or prior_review.get("evidence_sha256")
            != "7deb56837f833075e4579d4aaa0dd26c6ea5d4cbfcf9505ce109324f8af6d1db"
        ):
            errors.append("prior independent disposition review binding mismatch")
        if review.get("production_exception") is not False:
            errors.append("registry reissue must not grant a production exception")
        if review.get("acr_authorization") is not False:
            errors.append("registry reissue must not grant future ACR authorization")
        if review.get("deployment_authorization") is not False:
            errors.append("registry reissue must not authorize deployment")
        if review.get("acr_push_completed") is not True:
            errors.append("registry reissue does not record the completed ACR push")
        expected_bindings = {
            role_name: (
                f"{REGISTRY_REPOSITORY}@"
                f"{EXPECTED_REGISTRY[role_name]['digest']}"
            )
            for role_name in ROLE_NAMES
        }
        if review.get("registry_bindings") != expected_bindings:
            errors.append("registry reissue review digest bindings mismatch")
        official_schema = review.get("official_schema") or {}
        if (
            official_schema.get("url")
            != "https://cyclonedx.org/schema/bom-1.6.schema.json"
            or official_schema.get("sha256")
            != "1ebcb88a2c845ecb6ff7bee7aeabdff9422cb0347f3d6875b241bd444b7e098f"
            or official_schema.get("validation_errors") != 0
        ):
            errors.append("registry reissue official schema evidence mismatch")
        conclusions = review.get("conclusions") or {}
        if (
            conclusions.get("schema") != "PASS"
            or conclusions.get("twelve_dispositions") != "PASS"
            or conclusions.get("bom_links") != "PASS"
            or conclusions.get("bom_link_count") != 69
            or conclusions.get("bom_links_per_role")
            != {"api": 23, "admin": 23, "xhs-http": 23}
            or conclusions.get("immutable_evidence") != "PASS"
            or conclusions.get("raw_trivy_reports_unchanged") is not True
            or conclusions.get("local_image_ids_not_registry_digests") is not True
            or conclusions.get("registry_manifest_digests_bound") is not True
            or conclusions.get("registry_tags_read_back") is not True
            or conclusions.get("temporary_access_cleanup") is not True
            or conclusions.get("dispositions_unchanged_from_independent_review") is not True
        ):
            errors.append("registry reissue review conclusions are incomplete")

    return errors


def validate_bundle(root: Path = ROOT, *, require_review: bool = True) -> list[str]:
    vex_path = root / VEX_PATH.relative_to(ROOT)
    evidence_path = root / EVIDENCE_PATH.relative_to(ROOT)
    review_path = root / REVIEW_PATH.relative_to(ROOT)
    missing = [
        str(path.relative_to(root))
        for path in (vex_path, evidence_path)
        if not path.is_file()
    ]
    if require_review and not review_path.is_file():
        missing.append(str(review_path.relative_to(root)))
    if missing:
        return [f"missing VEX bundle file: {path}" for path in missing]
    vex = _load_json(vex_path)
    evidence = _load_json(evidence_path)
    review = _load_json(review_path) if review_path.is_file() else None
    errors = validate_documents(
        vex,
        evidence,
        review,
    )
    if review is not None:
        if review.get("vex_sha256") != _sha256(vex_path):
            errors.append("registry reissue review VEX SHA256 mismatch")
        if review.get("evidence_sha256") != _sha256(evidence_path):
            errors.append("registry reissue review evidence SHA256 mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--without-review",
        action="store_true",
        help="validate authoring inputs before the registry reissue review record exists",
    )
    args = parser.parse_args()
    errors = validate_bundle(require_review=not args.without_review)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: exact a635692 browserless VEX bundle is internally consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
