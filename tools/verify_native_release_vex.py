#!/usr/bin/env python3
"""Build and verify the exact local-image VEX bundle for the native release.

The canonical Trivy reports stay outside the repository and remain
unsuppressed.  This module reduces their identities and exact package rows into
a secret-free manifest, emits a CycloneDX VEX bound to the five local image
IDs/SBOMs, and verifies the bundle offline.  It never treats a local image ID
as a registry digest or as deployment authorization.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE_COMMIT = "2fa3a5543876a6c8040ec17ca05a5461b101bbd7"
RELEASE_SHORT = RELEASE_COMMIT[:7]
TASK_ID = "PROD-FIRST-LAUNCH-IMAGE-VULN-DISPOSITION-001"
RUN_ID = 30216295810
JOB_ID = 89830982353
RUN_URL = f"https://github.com/iamyusen1314/noteai/actions/runs/{RUN_ID}"
ROLES = ("api", "admin", "payment", "ai-worker", "xhs-http")
EVIDENCE_PATH = ROOT / "security" / "vex" / f"{RELEASE_SHORT}-native-release-evidence.json"
VEX_PATH = ROOT / "security" / "vex" / f"{RELEASE_SHORT}-native-release.vex.cdx.json"
REVIEW_PATH = ROOT / "security" / "vex" / f"{RELEASE_SHORT}-native-release-review.json"
EXPECTED_ROLE_IDENTITIES = {
    "api": {
        "local_image_id": "sha256:d5b0066cca40c70b1fa9f84afb136bf1a933b89ca7d98a36b73382a1585118c1",
        "sbom_sha256": "58b485d920b103d2cf1cb8ecd951752dec3153cd6c183de9858d1bdadb17c04c",
        "vulnerability_sha256": "5a70699ceb5d3b8a519a8f65b710d6e48879dcf585b5e6ae5d21dc14343a062e",
    },
    "admin": {
        "local_image_id": "sha256:a87133a69cc460f17fd2ade6f36fe09401083c0b93ca087ea1c74aa757a80c60",
        "sbom_sha256": "2829bc88f5e4dabfae7c2bc0c953b5d3071b8bd04c6db8eb2a00b0cec06230ee",
        "vulnerability_sha256": "504aabc50a703685bf735e4e0b5c086c7d361cf562d9630441438bf06fe0b17b",
    },
    "payment": {
        "local_image_id": "sha256:b499cc6600a49a4ae4dc95302b20b99d8aa859f8d2c6eb44f51c7d63094a5ca5",
        "sbom_sha256": "3e66a120720bc8905d11602541779823e21e5b9cd6a4682ea8a87e790c27ccde",
        "vulnerability_sha256": "10becf8454e857726729b0eda6518802f2d4878359bdaf5c7deefa2a84553863",
    },
    "ai-worker": {
        "local_image_id": "sha256:19d7ac22d33e12584037bed9abefd2dc5d84264a6df598071e7ca48ed89f27c4",
        "sbom_sha256": "4656c6ad49f901dba3ca876eaf7aba39f90d2536cfa08955c586198b0e8bfff6",
        "vulnerability_sha256": "318a8fb6f805577f6853793996bc33eeb71b2e407037e76ab7550dfaab947569",
    },
    "xhs-http": {
        "local_image_id": "sha256:b5907d57feca619b6668f91ba278740799d4768f2816a7d48f0551f9b060c9ba",
        "sbom_sha256": "2cabdeb2608dc3802a7fd6bba31ca98e933be4610a40557c2593813a3ec7761a",
        "vulnerability_sha256": "4bab1def66febf338a80138a1cf161eb41a2e1b2553d80aafc66855923a5cc80",
    },
}

SOURCE_PATHS = (
    "Dockerfile",
    "model/requirements-api.txt",
    "scripts/docker_entrypoint.sh",
    "deploy/production/docker-compose.yml",
)

EXPECTED_PACKAGES = {
    "CVE-2025-69720": (
        "libncursesw6",
        "libtinfo6",
        "ncurses-base",
        "ncurses-bin",
    ),
    "CVE-2026-13221": ("perl-base",),
    "CVE-2026-41992": ("gzip",),
    "CVE-2026-42496": ("perl-base",),
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
    "CVE-2026-57433": ("perl-base",),
    "CVE-2026-8376": ("perl-base",),
    "CVE-2026-9538": ("perl-base",),
}

DISPOSITIONS = {
    "CVE-2025-69720": {
        "justification": "code_not_reachable",
        "detail": (
            "The affected infocmp command is not accepted by any exact role "
            "entrypoint or invoked by production Python code. Runtime roles "
            "are non-root, capability-free and read-only."
        ),
    },
    "CVE-2026-13221": {
        "justification": "code_not_reachable",
        "detail": (
            "perl-base is present, but the fail-closed role marker, command "
            "allowlist and exact source contain no production Perl invocation "
            "or attacker-controlled Perl regular-expression path."
        ),
    },
    "CVE-2026-41992": {
        "justification": "code_not_reachable",
        "detail": (
            "No accepted role command invokes gzip or accepts the crafted "
            "multi-file LZW/LZH sequence required by the affected path."
        ),
    },
    "CVE-2026-42496": {
        "justification": "code_not_present",
        "detail": (
            "Trivy maps the Debian source package finding to perl-base. The "
            "affected Archive::Tar module is absent from the exact pinned base "
            "and no Docker stage installs Perl modules."
        ),
    },
    "CVE-2026-42497": {
        "justification": "code_not_present",
        "detail": (
            "Trivy maps the Debian source package finding to perl-base. The "
            "affected Archive::Tar module is absent from the exact pinned base "
            "and no Docker stage installs Perl modules."
        ),
    },
    "CVE-2026-48962": {
        "justification": "code_not_present",
        "detail": (
            "Trivy maps the Debian source package finding to perl-base. The "
            "affected IO::Compress module is absent from the exact pinned base "
            "and no Docker stage installs Perl modules."
        ),
    },
    "CVE-2026-53615": {
        "justification": "code_not_reachable",
        "detail": (
            "No role invokes blkid, mount or another partition parser. The "
            "production contract exposes no devices or host namespace and "
            "enforces non-root, cap-drop ALL, no-new-privileges and read-only "
            "root filesystems."
        ),
    },
    "CVE-2026-54369": {
        "justification": "code_not_reachable",
        "detail": (
            "No role invokes ACL tools or pathname ACL APIs. The production "
            "contract runs UID/GID 999 with cap-drop ALL, "
            "no-new-privileges and a read-only root filesystem."
        ),
    },
    "CVE-2026-57432": {
        "justification": "code_not_reachable",
        "detail": (
            "No accepted role invokes Perl or accepts an attacker-controlled "
            "Perl pack/unpack template."
        ),
    },
    "CVE-2026-57433": {
        "justification": "code_not_present",
        "detail": (
            "Trivy maps the Debian source package finding to perl-base. The "
            "affected Storable module is absent from the exact pinned base and "
            "no Docker stage installs Perl modules."
        ),
    },
    "CVE-2026-8376": {
        "justification": "requires_environment",
        "detail": (
            "The vulnerable condition is limited to 32-bit Perl builds. Every "
            "exact candidate and its runner evidence is linux/amd64."
        ),
    },
    "CVE-2026-9538": {
        "justification": "code_not_present",
        "detail": (
            "Trivy maps the Debian source package finding to perl-base. The "
            "affected Archive::Tar module is absent from the exact pinned base "
            "and no Docker stage installs Perl modules."
        ),
    },
}

EXPECTED_PROCESS_CALLS = {
    "model/admin_server.py": ("asyncio.create_subprocess_exec",),
    "model/fact_enrichment.py": ("subprocess.run",),
    "model/spider_xhs_http.py": ("subprocess.run",),
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _git_blob(path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{RELEASE_COMMIT}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"cannot read release blob: {path}")
    return result.stdout


def _git_model_sources() -> dict[str, str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", RELEASE_COMMIT, "--", "model"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("cannot enumerate release model sources")
    return {
        path: _git_blob(path).decode("utf-8")
        for path in result.stdout.splitlines()
        if path.endswith(".py")
    }


def _source_constraints() -> dict[str, Any]:
    sources = _git_model_sources()
    process_calls: dict[str, list[str]] = {}
    forbidden = (
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system(",
        "os.popen(",
        "create_subprocess_shell",
        "shell=True",
    )
    for path, source in sources.items():
        found = [
            call
            for call in ("subprocess.run", "asyncio.create_subprocess_exec")
            if call in source
        ]
        if found:
            process_calls[path] = found
        if any(marker in source for marker in forbidden):
            raise ValueError(f"forbidden process primitive in {path}")
    expected = {key: list(value) for key, value in EXPECTED_PROCESS_CALLS.items()}
    if process_calls != expected:
        raise ValueError(f"production process call set changed: {process_calls}")

    entrypoint = _git_blob("scripts/docker_entrypoint.sh").decode("utf-8")
    for forbidden_command in ("perl", "gzip", "infocmp", "blkid", "setfacl", "getfacl"):
        if forbidden_command in entrypoint:
            raise ValueError(f"entrypoint accepts forbidden command: {forbidden_command}")

    compose = _git_blob("deploy/production/docker-compose.yml").decode("utf-8")
    service_names = (
        "api",
        "admin",
        "payment",
        "ai-worker",
        "xhs-trends",
        "xhs-tracking",
    )
    if compose.count('user: "999:999"') != len(service_names):
        raise ValueError("production UID/GID hardening count changed")
    if compose.count("read_only: true") != len(service_names):
        raise ValueError("production read-only hardening count changed")
    if compose.count("privileged: false") != len(service_names):
        raise ValueError("production privilege hardening count changed")
    if compose.count("- ALL") != len(service_names):
        raise ValueError("production capability hardening count changed")
    if compose.count("no-new-privileges:true") != len(service_names):
        raise ValueError("production no-new-privileges count changed")
    if "\n    devices:" in compose or "\n    pid:" in compose or "\n    network_mode: host" in compose:
        raise ValueError("production host/device exposure changed")

    return {
        "release_blob_sha256": {
            path: _sha256_bytes(_git_blob(path)) for path in SOURCE_PATHS
        },
        "process_call_allowlist": process_calls,
        "forbidden_runtime_programs": [
            "perl",
            "gzip",
            "infocmp",
            "blkid",
            "setfacl",
            "getfacl",
        ],
        "runtime_contract": {
            "uid_gid": "999:999",
            "read_only_root": True,
            "privileged": False,
            "cap_drop_all": True,
            "no_new_privileges": True,
            "devices": [],
            "host_namespaces": [],
        },
        "prior_exact_base_constraint_evidence": {
            "evidence": "security/vex/a635692-browserless-evidence.json",
            "review": "security/vex/a635692-browserless-review.json",
            "vex": "security/vex/a635692-browserless.vex.cdx.json",
        },
    }


def _find_evidence_root(path: Path) -> Path:
    if (path / "summary.json").is_file():
        return path
    matches = [candidate for candidate in path.iterdir() if (candidate / "summary.json").is_file()]
    if len(matches) != 1:
        raise ValueError("evidence directory must contain exactly one summary.json root")
    return matches[0]


def _component_refs(sbom: dict[str, Any], package_names: set[str]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for component in sbom.get("components", []):
        name = component.get("name")
        if name in package_names:
            if name in refs:
                raise ValueError(f"duplicate SBOM component: {name}")
            refs[name] = component["bom-ref"]
    if set(refs) != package_names:
        raise ValueError(f"SBOM package set mismatch: {set(refs) ^ package_names}")
    return refs


def build_evidence(source_dir: Path) -> dict[str, Any]:
    evidence_root = _find_evidence_root(source_dir)
    summary = _json(evidence_root / "summary.json")
    if summary.get("release_commit") != RELEASE_COMMIT:
        raise ValueError("native evidence release commit mismatch")
    if summary.get("runner_architecture") != "x86_64":
        raise ValueError("native evidence runner is not x86_64")
    if summary.get("passed") is not False:
        raise ValueError("raw zero-Critical/High gate must remain failed")
    summary_roles = {item["role"]: item for item in summary.get("roles", [])}
    if set(summary_roles) != set(ROLES):
        raise ValueError("native evidence role set mismatch")

    package_names = {name for names in EXPECTED_PACKAGES.values() for name in names}
    roles: dict[str, Any] = {}
    canonical_rows: list[dict[str, Any]] | None = None
    for role in ROLES:
        role_summary = summary_roles[role]
        sbom_path = evidence_root / f"{role}-sbom.cdx.json"
        vuln_path = evidence_root / f"{role}-vuln-high-critical.json"
        secret_path = evidence_root / f"{role}-secret.json"
        inspect_path = evidence_root / f"{role}-inspect.json"
        build_metadata_path = evidence_root / f"{role}-build-metadata.json"
        history_path = evidence_root / f"{role}-history.jsonl"
        os_packages_path = evidence_root / f"{role}-os-packages.txt"
        sbom = _json(sbom_path)
        vuln = _json(vuln_path)
        inspect = _json(inspect_path)
        rows = sorted(
            (
                {
                    "id": item["VulnerabilityID"],
                    "package": item["PkgName"],
                    "installed_version": item["InstalledVersion"],
                    "fixed_version": item.get("FixedVersion") or "",
                    "severity": item["Severity"],
                }
                for result in vuln.get("Results", [])
                for item in result.get("Vulnerabilities") or []
            ),
            key=lambda row: (row["id"], row["package"]),
        )
        if len(rows) != 23:
            raise ValueError(f"{role}: expected 23 unsuppressed rows")
        if canonical_rows is None:
            canonical_rows = rows
        elif rows != canonical_rows:
            raise ValueError(f"{role}: vulnerability rows differ across roles")
        critical = sum(row["severity"] == "CRITICAL" for row in rows)
        high = sum(row["severity"] == "HIGH" for row in rows)
        if (critical, high) != (4, 19):
            raise ValueError(f"{role}: expected 4 Critical / 19 High")
        if any(row["fixed_version"] for row in rows):
            raise ValueError(f"{role}: unexpected fixed Debian row")
        findings = role_summary.get("findings", {})
        if findings != {
            "critical": 4,
            "high": 19,
            "secrets": 0,
            "browser_components": 0,
            "cryptography_48_0_1_components": 1,
            "forbidden_os_packages": 0,
        }:
            raise ValueError(f"{role}: native summary finding contract changed")
        if role_summary.get("passed") is not False:
            raise ValueError(f"{role}: raw gate result must remain false")
        config = inspect[0]["Config"] if isinstance(inspect, list) else inspect["Config"]
        roles[role] = {
            "target": role_summary["target"],
            "local_image_id": role_summary["image_id"],
            "registry_digest": None,
            "platform": role_summary["platform"],
            "entrypoint": config["Entrypoint"],
            "cmd": config["Cmd"],
            "sbom": {
                "sha256": _sha256(sbom_path),
                "serial_number": sbom["serialNumber"],
                "version": sbom["version"],
                "component_count": len(sbom.get("components", [])),
                "component_refs": _component_refs(sbom, package_names),
            },
            "raw_reports": {
                "vulnerability_sha256": _sha256(vuln_path),
                "secret_sha256": _sha256(secret_path),
                "inspect_sha256": _sha256(inspect_path),
                "build_metadata_sha256": _sha256(build_metadata_path),
                "history_sha256": _sha256(history_path),
                "os_packages_sha256": _sha256(os_packages_path),
            },
            "findings": findings,
            "raw_gate_passed": False,
        }

    assert canonical_rows is not None
    actual_cves = {
        row["id"]: tuple(
            sorted(item["package"] for item in canonical_rows if item["id"] == row["id"])
        )
        for row in canonical_rows
    }
    actual_cves = {key: value for key, value in actual_cves.items()}
    if actual_cves != EXPECTED_PACKAGES:
        raise ValueError("exact CVE/package map changed")

    return {
        "manifest_version": 1,
        "task": TASK_ID,
        "application_revision": RELEASE_COMMIT,
        "platform": "linux/amd64",
        "native_workflow": {
            "run_id": RUN_ID,
            "job_id": JOB_ID,
            "url": RUN_URL,
            "runner_architecture": summary["runner_architecture"],
            "created": summary["created"],
            "version": summary["version"],
            "artifact_summary_sha256": _sha256(evidence_root / "summary.json"),
        },
        "base_images": summary["base_images"],
        "scanner": {
            "sbom": {"name": "Syft", "version": "1.49.0"},
            "vulnerability": {"name": "Trivy", "version": "0.72.0"},
            "ignore_file_used": False,
            "vex_applied_to_raw_report": False,
            "ignore_unfixed": False,
            "raw_reports_canonical_and_unsuppressed": True,
        },
        "roles": roles,
        "vulnerability_rows_per_role": canonical_rows,
        "dispositions": copy.deepcopy(DISPOSITIONS),
        "source_constraints": _source_constraints(),
        "decision": {
            "status": "not_affected_for_exact_product",
            "production_exception": False,
            "deployment_authorization": False,
            "registry_access_performed": False,
            "provider_calls": 0,
            "business_writes": 0,
            "invalidation_triggers": [
                "application revision or local image ID changes",
                "base image, SBOM or package version changes",
                "architecture changes",
                "entrypoint, command or subprocess graph changes",
                "runtime capabilities, devices, mounts or namespaces change",
                "official vulnerability scope changes",
            ],
        },
    }


def _bom_link(role: dict[str, Any], package: str) -> str:
    serial = role["sbom"]["serial_number"]
    if not serial.startswith("urn:uuid:"):
        raise ValueError("invalid SBOM serial number")
    ref = role["sbom"]["component_refs"][package]
    return f"urn:cdx:{serial.removeprefix('urn:uuid:')}/{role['sbom']['version']}#{ref}"


def build_vex(evidence: dict[str, Any]) -> dict[str, Any]:
    timestamp = evidence["native_workflow"]["created"]
    vulnerabilities: list[dict[str, Any]] = []
    for cve in sorted(EXPECTED_PACKAGES):
        disposition = evidence["dispositions"][cve]
        refs = sorted(
            _bom_link(evidence["roles"][role], package)
            for role in ROLES
            for package in EXPECTED_PACKAGES[cve]
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
    for role in ROLES:
        role_data = evidence["roles"][role]
        components.append(
            {
                "bom-ref": f"urn:noteai:container:{role}:{role_data['local_image_id']}",
                "type": "container",
                "group": "NoteAI",
                "name": role_data["target"],
                "version": RELEASE_COMMIT,
                "properties": [
                    {
                        "name": "noteai:local-image-id",
                        "value": role_data["local_image_id"],
                    },
                    {
                        "name": "noteai:sbom-sha256",
                        "value": role_data["sbom"]["sha256"],
                    },
                    {
                        "name": "noteai:raw-vulnerability-report-sha256",
                        "value": role_data["raw_reports"]["vulnerability_sha256"],
                    },
                    {
                        "name": "noteai:registry-digest",
                        "value": "none",
                    },
                ],
            }
        )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, RUN_URL)}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "authors": [{"name": "NoteAI Production Release Management"}],
            "component": {
                "bom-ref": f"urn:noteai:release:{RELEASE_SHORT}-native-five-role-local",
                "type": "application",
                "group": "NoteAI",
                "name": "native-five-role-local-release-candidate",
                "version": RELEASE_COMMIT,
                "properties": [
                    {"name": "noteai:task", "value": TASK_ID},
                    {"name": "noteai:platform", "value": "linux/amd64"},
                    {"name": "noteai:workflow-run", "value": str(RUN_ID)},
                    {"name": "noteai:production-exception", "value": "false"},
                    {"name": "noteai:deployment-authorization", "value": "false"},
                    {
                        "name": "noteai:registry-digest-binding",
                        "value": "none-local-images-only",
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


def build_review(evidence: dict[str, Any], vex: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_version": 1,
        "task": TASK_ID,
        "application_revision": RELEASE_COMMIT,
        "workflow_run_id": RUN_ID,
        "roles": list(ROLES),
        "status": "verified_exact_local_product_disposition",
        "checks": {
            "ordinary_ci_passed": True,
            "native_build_and_artifact_upload_passed": True,
            "raw_zero_critical_high_gate_passed": False,
            "raw_reports_canonical_and_unsuppressed": True,
            "cryptography_48_0_1_per_role": 1,
            "secret_findings_per_role": 0,
            "browser_components_per_role": 0,
            "cyclonedx_exact_bom_links": True,
            "source_command_graph_fail_closed": True,
            "runtime_constraints_fail_closed": True,
            "registry_digest_binding": False,
            "production_exception": False,
            "deployment_authorization": False,
        },
        "cyclonedx_schema_validation": {
            "specification_commit": "55343ba19dee1785acf1ce9191540d5fd7b590db",
            "schema": "schema/bom-1.6.schema.json",
            "schema_sha256": "3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93",
            "validation_errors": 0,
        },
        "evidence_semantic_sha256": _canonical_sha256(evidence),
        "vex_semantic_sha256": _canonical_sha256(vex),
        "re_review_required_on": evidence["decision"]["invalidation_triggers"],
    }


def validate_documents(
    evidence: dict[str, Any],
    vex: dict[str, Any],
    review: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    try:
        if evidence.get("task") != TASK_ID:
            errors.append("evidence task mismatch")
        if evidence.get("application_revision") != RELEASE_COMMIT:
            errors.append("evidence release commit mismatch")
        if set(evidence.get("roles", {})) != set(ROLES):
            errors.append("evidence role set mismatch")
        if evidence.get("source_constraints") != _source_constraints():
            errors.append("release source constraints changed")
        scanner = evidence.get("scanner", {})
        if scanner.get("raw_reports_canonical_and_unsuppressed") is not True:
            errors.append("raw reports must remain canonical and unsuppressed")
        if scanner.get("vex_applied_to_raw_report") is not False:
            errors.append("VEX must not be applied to canonical raw reports")
        decision = evidence.get("decision", {})
        for key in (
            "production_exception",
            "deployment_authorization",
            "registry_access_performed",
        ):
            if decision.get(key) is not False:
                errors.append(f"decision.{key} must remain false")
        for role in ROLES:
            role_data = evidence["roles"].get(role, {})
            identity = EXPECTED_ROLE_IDENTITIES[role]
            if role_data.get("local_image_id") != identity["local_image_id"]:
                errors.append(f"{role}: immutable local image ID mismatch")
            if role_data.get("sbom", {}).get("sha256") != identity["sbom_sha256"]:
                errors.append(f"{role}: immutable SBOM hash mismatch")
            if (
                role_data.get("raw_reports", {}).get("vulnerability_sha256")
                != identity["vulnerability_sha256"]
            ):
                errors.append(f"{role}: immutable vulnerability report hash mismatch")
            if role_data.get("registry_digest") is not None:
                errors.append(f"{role}: local evidence must not claim a registry digest")
            if role_data.get("platform") != "linux/amd64":
                errors.append(f"{role}: platform mismatch")
            if role_data.get("raw_gate_passed") is not False:
                errors.append(f"{role}: raw vulnerability gate result was rewritten")
            if role_data.get("findings") != {
                "critical": 4,
                "high": 19,
                "secrets": 0,
                "browser_components": 0,
                "cryptography_48_0_1_components": 1,
                "forbidden_os_packages": 0,
            }:
                errors.append(f"{role}: exact finding counts changed")

        expected_vex = build_vex(evidence)
        if vex != expected_vex:
            errors.append("CycloneDX VEX content differs from exact evidence")
        if len(vex.get("vulnerabilities", [])) != len(EXPECTED_PACKAGES):
            errors.append("VEX vulnerability count mismatch")
        for item in vex.get("vulnerabilities", []):
            analysis = item.get("analysis", {})
            if analysis.get("state") != "not_affected":
                errors.append(f"{item.get('id')}: VEX state changed")
            if "response" in analysis:
                errors.append(f"{item.get('id')}: VEX must not claim a waiver response")

        expected_review = build_review(evidence, vex)
        if review != expected_review:
            errors.append("review record differs from exact evidence/VEX")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"malformed native VEX bundle: {exc}")
    return errors


def validate_bundle() -> list[str]:
    try:
        return validate_documents(_json(EVIDENCE_PATH), _json(VEX_PATH), _json(REVIEW_PATH))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load native VEX bundle: {exc}"]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-from",
        type=Path,
        help="Build the reduced bundle from a downloaded native evidence directory.",
    )
    args = parser.parse_args()
    if args.build_from:
        evidence = build_evidence(args.build_from)
        vex = build_vex(evidence)
        review = build_review(evidence, vex)
        _write_json(EVIDENCE_PATH, evidence)
        _write_json(VEX_PATH, vex)
        _write_json(REVIEW_PATH, review)
    errors = validate_bundle()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS: exact native five-role VEX bundle; raw reports remain "
        "unsuppressed at 4 Critical / 19 High per role"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
