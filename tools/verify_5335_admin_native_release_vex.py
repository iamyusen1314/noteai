#!/usr/bin/env python3
"""Build and verify the exact 5335bda Admin-only native release VEX.

The raw GitHub artifact remains canonical and unsuppressed. This verifier
reduces its exact eleven-file Admin-only evidence into a repository-safe VEX
bundle, proves the single image-context change from b55f118, and binds the
controller request that explicitly forbids Registry, deployment, database,
service and public-traffic mutations.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import verify_native_release_vex as native


ROOT = Path(__file__).resolve().parents[1]
PRIOR_RELEASE_COMMIT = "b55f11882100e9ef919522540729e366a511f88f"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
RELEASE_SHORT = RELEASE_COMMIT[:7]
CONTROL_COMMIT = "e7039a3fe73b539325593cf1ba78dcd4a9949910"
CONTROL_PARENT = "e7766ab903a2f2721521552c62a18573bc9990de"
TASK_ID = "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
RUN_ID = 30550548144
JOB_ID = 90897767171
RUN_URL = f"https://github.com/iamyusen1314/noteai/actions/runs/{RUN_ID}"
ARTIFACT_NAME = (
    "native-amd64-release-evidence-"
    "5335bdaed933b1f999b5f819c047ec50c11821ae-admin"
)
REQUEST_PATH = ".github/release-requests/admin-5335bda-v2.json"
REQUEST_SHA256 = "c5bd56148af0d780d3955ebb9ed5dafe0c7507ba6974da86b5830323c77009ef"
WORKFLOW_SHA256 = "6b8bacf383f1ee9b984b571d28a8a69437b8f69c949cc68a17691351180e430f"
SUMMARY_SHA256 = "19cbf14415e05d614e7e70caed67ecfefac2c12ae726edaae7a3525cb88d38f7"
ROLES = ("admin",)
EVIDENCE_PATH = (
    ROOT
    / "security"
    / "vex"
    / f"{RELEASE_SHORT}-admin-github-native-release-evidence.json"
)
VEX_PATH = (
    ROOT
    / "security"
    / "vex"
    / f"{RELEASE_SHORT}-admin-github-native-release.vex.cdx.json"
)
REVIEW_PATH = (
    ROOT
    / "security"
    / "vex"
    / f"{RELEASE_SHORT}-admin-github-native-release-review.json"
)
PRIOR_EVIDENCE_PATH = (
    ROOT / "security" / "vex" / "b55f118-github-native-release-evidence.json"
)
GITHUB_RECEIPT_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "evidence"
    / "production-admin-native-source-candidate-verified-20260730.json"
)
GITHUB_RECEIPT_SHA256 = (
    "3ee041fd375b23a0973dc9e5b6949a156374eb2e6a88e6a036e82b965d11bb74"
)

EXPECTED_ROLE_IDENTITIES = {
    "admin": {
        "local_image_id": (
            "sha256:9ab915287427e58b1be80faa3a4252eb98463519967aad0e18329ad74d6d8cf7"
        ),
        "sbom_sha256": (
            "31b468943fd99864f1b541f4e90a7cc5985123633ab3336402ad6a16a9ecae1d"
        ),
        "vulnerability_sha256": (
            "e43c01d2258187ceb690ee3a8c866821451d42e1703259aa83df44bd9fa87af3"
        ),
    }
}
HISTORICAL_ADMIN_IDENTITIES = {
    "b55_github_local_image_id": (
        "sha256:50a21bea7e496a6f09e3e71fd0e1d4a9fb06fb23815d2bea702808bc24d98a71"
    ),
    "b55_builder_local_config_id": (
        "sha256:fac78f71d7b123621962738d2a93532ff98f2302232562dc75b6a8e0016b7626"
    ),
    "b55_registry_manifest_digest": (
        "sha256:271a089e4e5ae7da3635b14d2ce8d5195955e7d74225723a4308d0c99cb79e56"
    ),
}
EXPECTED_ARTIFACT_SHA256 = {
    "admin-build-metadata.json": (
        "305f8e2ef58fd00841d9f39349920f2f6885abc00c58a86e053a603d823a08b1"
    ),
    "admin-history.jsonl": (
        "cd7e0330c69358e2d8929c4438365c542c788aba23df842d029d92117effcba9"
    ),
    "admin-inspect.json": (
        "92ee11e7232acee37d9ba029dec80d7c8752d432cb62a66d4ba1ddfe065811a0"
    ),
    "admin-os-packages.txt": (
        "1cf41e20e68ddfd8ed52bf5c95f1c6c20dc146e506815c679731962010a85a54"
    ),
    "admin-sbom.cdx.json": (
        "31b468943fd99864f1b541f4e90a7cc5985123633ab3336402ad6a16a9ecae1d"
    ),
    "admin-secret.json": (
        "70a187a5f71375d7ec758c8ecebe53bb04df5822a47ef5f42db6c722b3306ce5"
    ),
    "admin-summary.json": (
        "1ee6488ff3ccd1f39e203542a5f38e8136efea072ab42818abffa8529f2d74d3"
    ),
    "admin-vuln-high-critical.json": (
        "e43c01d2258187ceb690ee3a8c866821451d42e1703259aa83df44bd9fa87af3"
    ),
    "node-base-index.json": (
        "2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"
    ),
    "python-base-index.json": (
        "db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
    ),
    "summary.json": SUMMARY_SHA256,
}
EXPECTED_IMAGE_CONTEXT_DELTA = ("model/crawler_config.json",)
IMAGE_CONTEXT_PATHS = (
    "Dockerfile",
    "model",
    "scripts/docker_entrypoint.sh",
    "scripts/render_start_api.sh",
    "scripts/render_start_admin.sh",
    "scripts/render_start_payment.sh",
    "scripts/render_predeploy.py",
    "scripts/render_run_market_timing.sh",
    "scripts/render_run_crawler.sh",
    "scripts/migrate_sqlite_to_postgres.py",
    "scripts/migrate_managed_prompts_v04.py",
    "NoteAI_Pro_Demo_Framer.html",
    "deploy/production/docker-compose.yml",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git(args: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _git_blob(revision: str, path: str) -> bytes:
    result = _git(["show", f"{revision}:{path}"], text=False)
    if result.returncode:
        raise ValueError(f"cannot read exact Git blob: {revision}:{path}")
    return result.stdout


def _request_contract() -> dict[str, Any]:
    expected = {
        "schema_version": 2,
        "task": TASK_ID,
        "release_commit": RELEASE_COMMIT,
        "release_scope": "admin",
        "trigger_mode": "one_shot_controller_diff_v2",
        "registry_publication_authorized": False,
        "deployment_authorized": False,
        "database_authorized": False,
        "service_mutation_authorized": False,
        "public_traffic_authorized": False,
    }
    request_blob = _git_blob(CONTROL_COMMIT, REQUEST_PATH)
    if _sha256_bytes(request_blob) != REQUEST_SHA256:
        raise ValueError("controller request hash changed")
    if json.loads(request_blob) != expected:
        raise ValueError("controller request contract changed")

    parents = _git(["rev-list", "--parents", "-n", "1", CONTROL_COMMIT])
    if parents.returncode or parents.stdout.split() != [CONTROL_COMMIT, CONTROL_PARENT]:
        raise ValueError("controller parent contract changed")
    ancestor = _git(["merge-base", "--is-ancestor", RELEASE_COMMIT, CONTROL_COMMIT])
    if ancestor.returncode:
        raise ValueError("release is not an ancestor of controller")
    additions = _git(
        ["log", "--diff-filter=A", "--format=%H", CONTROL_COMMIT, "--", REQUEST_PATH]
    )
    if additions.returncode or additions.stdout.splitlines() != [CONTROL_COMMIT]:
        raise ValueError("controller request addition history changed")

    canonical_script = _git_blob(RELEASE_COMMIT, "scripts/ci/native_release_evidence.sh")
    workflow = _git_blob(
        CONTROL_COMMIT,
        ".github/workflows/native-release-evidence.yml",
    )
    if _sha256_bytes(workflow) != WORKFLOW_SHA256:
        raise ValueError("controller workflow hash changed")
    role_line = b"roles=(api admin payment ai-worker xhs-http)"
    if canonical_script.count(role_line) != 1:
        raise ValueError("canonical release role list changed")
    executed_script = canonical_script.replace(role_line, b"roles=(admin)")
    return {
        "controller_commit": CONTROL_COMMIT,
        "controller_parent": CONTROL_PARENT,
        "request_path": REQUEST_PATH,
        "request_sha256": REQUEST_SHA256,
        "request": expected,
        "release_is_controller_ancestor": True,
        "request_addition_commit": CONTROL_COMMIT,
        "workflow_sha256": WORKFLOW_SHA256,
        "resolution": "controller-checkout-single-parent-git-diff-tree-v2",
        "transformation": "exact canonical five-role list to admin only",
        "original_script_sha256": _sha256_bytes(canonical_script),
        "executed_script_sha256": _sha256_bytes(executed_script),
    }


def _release_delta() -> dict[str, Any]:
    result = _git(
        [
            "diff",
            "--name-only",
            PRIOR_RELEASE_COMMIT,
            RELEASE_COMMIT,
            "--",
            *IMAGE_CONTEXT_PATHS,
        ]
    )
    if result.returncode:
        raise ValueError("cannot enumerate Admin image-context delta")
    changed = tuple(sorted(result.stdout.splitlines()))
    if changed != EXPECTED_IMAGE_CONTEXT_DELTA:
        raise ValueError(f"Admin image-context delta changed: {changed}")
    crawler = json.loads(_git_blob(RELEASE_COMMIT, changed[0]))
    if crawler != {
        "enabled": False,
        "cookie_valid": False,
        "last_run": None,
        "total_collected": 0,
        "daily_limit": 300,
        "schedule_hour": 3,
    }:
        raise ValueError("Admin crawler fallback is not default-suspended")
    return {
        "prior_application_revision": PRIOR_RELEASE_COMMIT,
        "image_context_changed_paths": list(changed),
        "release_blob_sha256": {
            path: _sha256_bytes(_git_blob(RELEASE_COMMIT, path)) for path in changed
        },
        "prior_blob_sha256": {
            path: _sha256_bytes(_git_blob(PRIOR_RELEASE_COMMIT, path))
            for path in changed
        },
        "unchanged_build_contract_sha256": {
            path: _sha256_bytes(_git_blob(RELEASE_COMMIT, path))
            for path in (
                "Dockerfile",
                "model/requirements-api.txt",
                "scripts/docker_entrypoint.sh",
                "scripts/render_start_admin.sh",
                "deploy/production/docker-compose.yml",
            )
        },
        "purpose": (
            "Make the no-row Admin crawler fallback truthfully default to "
            "suspended without changing the reviewed image or command graph."
        ),
    }


def _expected_artifact_contract() -> dict[str, Any]:
    return {
        "artifact_name": ARTIFACT_NAME,
        "file_count": 11,
        "file_sha256": copy.deepcopy(EXPECTED_ARTIFACT_SHA256),
        "runtime": {
            "role": "admin",
            "target": "admin-runtime",
            "platform": "linux/amd64",
            "image_user": "noteai",
            "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
            "cmd": ["/app/scripts/render_start_admin.sh"],
            "oci_revision": RELEASE_COMMIT,
            "oci_created": "2026-07-30T13:29:02Z",
            "oci_version": "git-5335bda-amd64-r1",
            "runtime_role_environment": "NOTEAI_RUNTIME_ROLE=admin",
            "build_config_digest": (
                "sha256:9ab915287427e58b1be80faa3a4252eb98463519967aad0e18329ad74d6d8cf7"
            ),
            "rootfs_diff_id_count": 18,
            "sbom_component_count": 3076,
            "canonical_vulnerability_row_count": 23,
        },
    }


def _github_receipt() -> dict[str, Any]:
    if _sha256(GITHUB_RECEIPT_PATH) != GITHUB_RECEIPT_SHA256:
        raise ValueError("GitHub read-only receipt hash changed")
    receipt = _json(GITHUB_RECEIPT_PATH)
    if receipt.get("task") != TASK_ID or receipt.get("status") != "VERIFIED":
        raise ValueError("GitHub receipt task/status changed")
    if receipt.get("release", {}).get("commit") != RELEASE_COMMIT:
        raise ValueError("GitHub receipt release changed")
    controller = receipt.get("controller", {})
    if controller.get("commit") != CONTROL_COMMIT:
        raise ValueError("GitHub receipt controller changed")
    if controller.get("workflow_sha256") != WORKFLOW_SHA256:
        raise ValueError("GitHub receipt workflow hash changed")
    if controller.get("request_sha256") != REQUEST_SHA256:
        raise ValueError("GitHub receipt request hash changed")
    run = receipt.get("github_run", {})
    if (
        run.get("run_id"),
        run.get("job_id"),
        run.get("event"),
        run.get("head_sha"),
        run.get("conclusion"),
        run.get("expected_terminal_failure_only"),
    ) != (RUN_ID, JOB_ID, "push", CONTROL_COMMIT, "failure", True):
        raise ValueError("GitHub receipt run identity changed")
    expected_steps = [
        ("Checkout controller commit with full history", "success"),
        ("Resolve and validate release control", "success"),
        ("Checkout exact source with full evidence history", "success"),
        ("Verify native runner and immutable source", "success"),
        ("Install checksum-pinned scanners", "success"),
        ("Build, inspect, inventory and scan", "success"),
        ("Upload evidence only", "success"),
        ("Enforce zero Critical or High findings", "failure"),
    ]
    actual_steps = [
        (item.get("name"), item.get("conclusion")) for item in run.get("steps", [])
    ]
    if actual_steps != expected_steps:
        raise ValueError("GitHub receipt step outcomes changed")
    artifact = receipt.get("artifact", {})
    if (
        artifact.get("name"),
        artifact.get("file_count"),
        artifact.get("summary_sha256"),
        artifact.get("local_image_id"),
        artifact.get("raw_gate_passed"),
    ) != (
        ARTIFACT_NAME,
        11,
        SUMMARY_SHA256,
        EXPECTED_ROLE_IDENTITIES["admin"]["local_image_id"],
        False,
    ):
        raise ValueError("GitHub receipt artifact identity changed")
    if any(receipt.get("authorization", {}).values()):
        raise ValueError("GitHub receipt grants an unauthorized mutation")
    observed = receipt.get("observed_mutations", {})
    for key in (
        "registry_login",
        "registry_push",
        "cloud_resource",
        "database_connection",
        "database_write",
        "service_mutation",
        "provider_call",
        "public_traffic",
    ):
        if observed.get(key) != 0:
            raise ValueError(f"GitHub receipt observed unexpected mutation: {key}")
    return {
        "path": str(GITHUB_RECEIPT_PATH.relative_to(ROOT)),
        "sha256": GITHUB_RECEIPT_SHA256,
        "run_id": RUN_ID,
        "job_id": JOB_ID,
        "artifact_id": artifact["artifact_id"],
        "artifact_name": ARTIFACT_NAME,
        "build_scan_upload_passed": True,
        "terminal_raw_gate_expected_failure": True,
    }


def _validate_raw_artifact(evidence_root: Path) -> dict[str, Any]:
    entries = list(evidence_root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("native artifact contains non-regular entries")
    actual_names = {path.name for path in entries}
    if actual_names != set(EXPECTED_ARTIFACT_SHA256):
        raise ValueError(f"native artifact file set changed: {actual_names}")
    actual_hashes = {name: _sha256(evidence_root / name) for name in sorted(actual_names)}
    if actual_hashes != EXPECTED_ARTIFACT_SHA256:
        raise ValueError("native artifact file hashes changed")

    summary = _json(evidence_root / "summary.json")
    control = _request_contract()
    expected_summary_control = {
        "release_scope": "admin",
        "source_tree_clean_after_execution": True,
        "resolution": control["resolution"],
        "transformation": control["transformation"],
        "original_script_sha256": control["original_script_sha256"],
        "executed_script_sha256": control["executed_script_sha256"],
        "trigger_event": "push",
        "control_commit": CONTROL_COMMIT,
        "request_path": REQUEST_PATH,
        "request_sha256": REQUEST_SHA256,
    }
    if summary.get("control") != expected_summary_control:
        raise ValueError("native artifact control block changed")
    if summary.get("created") != "2026-07-30T13:29:02Z":
        raise ValueError("native artifact created label changed")
    if summary.get("version") != "git-5335bda-amd64-r1":
        raise ValueError("native artifact version changed")

    inspect = _json(evidence_root / "admin-inspect.json")
    if not isinstance(inspect, list) or len(inspect) != 1:
        raise ValueError("Admin inspect shape changed")
    image = inspect[0]
    config = image.get("Config") or {}
    labels = config.get("Labels") or {}
    if image.get("Id") != EXPECTED_ROLE_IDENTITIES["admin"]["local_image_id"]:
        raise ValueError("Admin local image ID changed")
    if (image.get("Os"), image.get("Architecture")) != ("linux", "amd64"):
        raise ValueError("Admin inspect platform changed")
    if config.get("User") != "noteai":
        raise ValueError("Admin image user changed")
    if config.get("Entrypoint") != ["/app/scripts/docker_entrypoint.sh"]:
        raise ValueError("Admin entrypoint changed")
    if config.get("Cmd") != ["/app/scripts/render_start_admin.sh"]:
        raise ValueError("Admin command changed")
    if labels != {
        "com.noteai.runtime.role": "admin",
        "org.opencontainers.image.created": "2026-07-30T13:29:02Z",
        "org.opencontainers.image.revision": RELEASE_COMMIT,
        "org.opencontainers.image.source": "https://github.com/iamyusen1314/noteai",
        "org.opencontainers.image.version": "git-5335bda-amd64-r1",
    }:
        raise ValueError("Admin OCI labels changed")
    if (config.get("Env") or []).count("NOTEAI_RUNTIME_ROLE=admin") != 1:
        raise ValueError("Admin runtime-role environment changed")

    metadata = _json(evidence_root / "admin-build-metadata.json")
    provenance = metadata.get("buildx.build.provenance") or {}
    invocation = provenance.get("invocation") or {}
    parameters = invocation.get("parameters") or {}
    build_args = parameters.get("args") or {}
    if invocation.get("environment") != {"platform": "linux/amd64"}:
        raise ValueError("Admin build platform changed")
    if build_args.get("target") != "admin-runtime":
        raise ValueError("Admin build target changed")
    for key, expected in (
        ("build-arg:NOTEAI_OCI_REVISION", RELEASE_COMMIT),
        ("build-arg:NOTEAI_OCI_SOURCE", "https://github.com/iamyusen1314/noteai"),
        ("build-arg:NOTEAI_OCI_VERSION", "git-5335bda-amd64-r1"),
        ("build-arg:NOTEAI_OCI_CREATED", "2026-07-30T13:29:02Z"),
    ):
        if build_args.get(key) != expected:
            raise ValueError(f"Admin build argument changed: {key}")
    image_id = EXPECTED_ROLE_IDENTITIES["admin"]["local_image_id"]
    if metadata.get("containerimage.digest") != image_id:
        raise ValueError("Admin build image digest changed")
    if metadata.get("containerimage.config.digest") != image_id:
        raise ValueError("Admin build config digest changed")
    material_digests = {
        item.get("digest", {}).get("sha256")
        for item in provenance.get("materials", [])
    }
    if material_digests != {
        EXPECTED_ARTIFACT_SHA256["python-base-index.json"],
        EXPECTED_ARTIFACT_SHA256["node-base-index.json"],
    }:
        raise ValueError("Admin base material set changed")

    sbom = _json(evidence_root / "admin-sbom.cdx.json")
    if len(sbom.get("components", [])) != 3076:
        raise ValueError("Admin SBOM component count changed")
    cryptography = [
        component
        for component in sbom.get("components", [])
        if component.get("name") == "cryptography"
        and component.get("version") == "48.0.1"
    ]
    if len(cryptography) != 1:
        raise ValueError("cryptography 48.0.1 component count changed")
    browser_components = [
        component
        for component in sbom.get("components", [])
        if any(
            marker in str(component.get("name", "")).lower()
            for marker in ("playwright", "chromium", "google-chrome")
        )
    ]
    if browser_components:
        raise ValueError("browser component entered Admin SBOM")
    secret_report = _json(evidence_root / "admin-secret.json")
    secret_count = sum(
        len(result.get("Secrets") or []) for result in secret_report.get("Results", [])
    )
    if secret_count:
        raise ValueError("Admin secret scanner findings changed")
    vulnerability_report = _json(
        evidence_root / "admin-vuln-high-critical.json"
    )
    inspect_diff_ids = image.get("RootFS", {}).get("Layers")
    if not isinstance(inspect_diff_ids, list) or len(inspect_diff_ids) != 18:
        raise ValueError("Admin inspect RootFS identity changed")
    for report_name, report in (
        ("vulnerability", vulnerability_report),
        ("secret", secret_report),
    ):
        report_metadata = report.get("Metadata", {})
        if report_metadata.get("ImageID") != image_id:
            raise ValueError(f"Admin {report_name} report image ID changed")
        if report_metadata.get("DiffIDs") != inspect_diff_ids:
            raise ValueError(f"Admin {report_name} RootFS identity changed")

    forbidden_os = {
        "libgl1",
        "libglib2.0-0",
        "libsm6",
        "libxext6",
        "libxrender1",
        "chromium",
    }
    os_packages = set(
        (evidence_root / "admin-os-packages.txt").read_text(encoding="utf-8").splitlines()
    )
    if forbidden_os & os_packages or any(
        package.startswith("google-chrome") for package in os_packages
    ):
        raise ValueError("forbidden Admin OS package set changed")
    return _expected_artifact_contract()


@contextmanager
def _native_profile():
    values = {
        "RELEASE_COMMIT": RELEASE_COMMIT,
        "RELEASE_SHORT": RELEASE_SHORT,
        "TASK_ID": TASK_ID,
        "RUN_ID": RUN_ID,
        "JOB_ID": JOB_ID,
        "RUN_URL": RUN_URL,
        "ROLES": ROLES,
        "EVIDENCE_PATH": EVIDENCE_PATH,
        "VEX_PATH": VEX_PATH,
        "REVIEW_PATH": REVIEW_PATH,
        "EXPECTED_ROLE_IDENTITIES": EXPECTED_ROLE_IDENTITIES,
    }
    previous = {name: getattr(native, name) for name in values}
    for name, value in values.items():
        setattr(native, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(native, name, value)


def _identity_separation() -> dict[str, Any]:
    current = EXPECTED_ROLE_IDENTITIES["admin"]["local_image_id"]
    if current in HISTORICAL_ADMIN_IDENTITIES.values():
        raise ValueError("fresh Admin identity reuses a historical b55 identity")
    return {
        "fresh_local_image_id": current,
        "historical_b55_identities": copy.deepcopy(HISTORICAL_ADMIN_IDENTITIES),
        "all_distinct_from_fresh": True,
        "historical_registry_authorization_reused": False,
    }


def build_evidence(source_dir: Path) -> dict[str, Any]:
    evidence_root = native._find_evidence_root(source_dir)
    artifact_contract = _validate_raw_artifact(evidence_root)
    with _native_profile():
        evidence = native.build_evidence(source_dir)
    prior = _json(PRIOR_EVIDENCE_PATH)
    if evidence["base_images"] != prior["base_images"]:
        raise ValueError("base image identity changed from b55 predecessor")
    if evidence["vulnerability_rows_per_role"] != prior["vulnerability_rows_per_role"]:
        raise ValueError("Admin vulnerability rows changed from b55 predecessor")
    evidence["admin_control"] = _request_contract()
    evidence["github_readonly_receipt"] = _github_receipt()
    evidence["artifact_contract"] = artifact_contract
    evidence["release_delta"] = _release_delta()
    evidence["historical_identity_separation"] = _identity_separation()
    evidence["native_workflow"].update(
        {
            "artifact_name": ARTIFACT_NAME,
            "artifact_file_count": 11,
            "control_commit": CONTROL_COMMIT,
            "request_sha256": REQUEST_SHA256,
            "build_scan_upload_passed": True,
            "terminal_raw_gate_expected_failure": True,
        }
    )
    evidence["decision"].update(
        {
            "registry_publication_authorization": False,
            "database_authorization": False,
            "service_mutation_authorization": False,
            "public_traffic_authorization": False,
        }
    )
    return evidence


def build_vex(evidence: dict[str, Any]) -> dict[str, Any]:
    with _native_profile():
        vex = native.build_vex(evidence)
    component = vex["metadata"]["component"]
    component["bom-ref"] = f"urn:noteai:release:{RELEASE_SHORT}-native-admin-only-local"
    component["name"] = "native-admin-only-local-release-candidate"
    component["properties"].extend(
        [
            {"name": "noteai:release-scope", "value": "admin-only"},
            {"name": "noteai:control-commit", "value": CONTROL_COMMIT},
            {"name": "noteai:request-sha256", "value": REQUEST_SHA256},
            {
                "name": "noteai:github-receipt-sha256",
                "value": GITHUB_RECEIPT_SHA256,
            },
            {"name": "noteai:registry-publication-authorization", "value": "false"},
            {"name": "noteai:database-authorization", "value": "false"},
            {"name": "noteai:service-mutation-authorization", "value": "false"},
            {"name": "noteai:public-traffic-authorization", "value": "false"},
        ]
    )
    return vex


def build_review(evidence: dict[str, Any], vex: dict[str, Any]) -> dict[str, Any]:
    with _native_profile():
        review = native.build_review(evidence, vex)
    review["status"] = "verified_exact_admin_only_local_product_disposition"
    review["checks"].update(
        {
            "admin_only_scope": True,
            "artifact_file_count": 11,
            "controller_request_validated": True,
            "controller_commit": CONTROL_COMMIT,
            "request_sha256": REQUEST_SHA256,
            "github_receipt_sha256": GITHUB_RECEIPT_SHA256,
            "image_context_delta": ["model/crawler_config.json"],
            "fresh_image_identity": True,
            "registry_publication_authorization": False,
            "database_authorization": False,
            "service_mutation_authorization": False,
            "public_traffic_authorization": False,
        }
    )
    return review


def validate_documents(
    evidence: dict[str, Any],
    vex: dict[str, Any],
    review: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    try:
        with _native_profile():
            native_vex = native.build_vex(evidence)
            native_review = native.build_review(evidence, native_vex)
            errors.extend(native.validate_documents(evidence, native_vex, native_review))
        prior = _json(PRIOR_EVIDENCE_PATH)
        if evidence.get("admin_control") != _request_contract():
            errors.append("Admin controller contract changed")
        if evidence.get("github_readonly_receipt") != _github_receipt():
            errors.append("Admin GitHub read-only receipt changed")
        if evidence.get("artifact_contract") != _expected_artifact_contract():
            errors.append("Admin eleven-file artifact contract changed")
        if evidence.get("release_delta") != _release_delta():
            errors.append("Admin image-context delta changed")
        if evidence.get("historical_identity_separation") != _identity_separation():
            errors.append("Admin historical identity separation changed")
        if evidence.get("base_images") != prior.get("base_images"):
            errors.append("Admin base images differ from b55 predecessor")
        if (
            evidence.get("vulnerability_rows_per_role")
            != prior.get("vulnerability_rows_per_role")
        ):
            errors.append("Admin vulnerability rows differ from b55 predecessor")
        workflow = evidence.get("native_workflow", {})
        if workflow.get("artifact_summary_sha256") != SUMMARY_SHA256:
            errors.append("Admin artifact summary hash changed")
        if workflow.get("control_commit") != CONTROL_COMMIT:
            errors.append("Admin controller commit changed")
        if workflow.get("request_sha256") != REQUEST_SHA256:
            errors.append("Admin request hash changed")
        decision = evidence.get("decision", {})
        for key in (
            "registry_publication_authorization",
            "deployment_authorization",
            "database_authorization",
            "service_mutation_authorization",
            "public_traffic_authorization",
        ):
            if decision.get(key) is not False:
                errors.append(f"decision.{key} must remain false")
        if vex != build_vex(evidence):
            errors.append("Admin-only CycloneDX VEX differs from exact evidence")
        if review != build_review(evidence, vex):
            errors.append("Admin-only review differs from exact evidence/VEX")
    except (KeyError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        errors.append(f"malformed 5335 Admin native VEX bundle: {exc}")
    return errors


def validate_bundle() -> list[str]:
    try:
        return validate_documents(
            _json(EVIDENCE_PATH),
            _json(VEX_PATH),
            _json(REVIEW_PATH),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load 5335 Admin native VEX bundle: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-from",
        type=Path,
        help="Build from the downloaded exact eleven-file Admin artifact.",
    )
    args = parser.parse_args()
    if args.build_from:
        evidence = build_evidence(args.build_from)
        vex = build_vex(evidence)
        review = build_review(evidence, vex)
        native._write_json(EVIDENCE_PATH, evidence)
        native._write_json(VEX_PATH, vex)
        native._write_json(REVIEW_PATH, review)
    errors = validate_bundle()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS: exact 5335bda Admin-only native VEX; raw reports remain "
        "unsuppressed at 4 Critical / 19 High; publication and deployment "
        "remain unauthorized"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
