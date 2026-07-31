#!/usr/bin/env python3
"""Verify the inert, append-only V6 Admin dependency-cache recovery plan."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import verify_admin_dependency_cache_export_plan_v5 as v5_plan
import verify_admin_dependency_cache_v5_failure_evidence as v5_failure


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v6.yml"
)
TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v6.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v6.json"
)
TRANSIENT_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v5.py"
)
CLEANUP_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "cleanup_admin_dependency_cache_v5.sh"
)
PROVENANCE_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildx_v0.35.0_provenance_gha_disabled_projection.json"
)
RAWJSON_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildx_v0.35.0_rawjson_schema_projection.json"
)
STRUCTURAL_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_solvestatus_structural_projection.json"
)
V5_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v5.yml"
)
V5_TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v5.json"
)
V5_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v5.json"
)
V5_PLAN_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_export_plan_v5.py"
)
V4_TRANSIENT_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v4.py"
)
V5_FAILURE_EVIDENCE_PATH = v5_failure.EVIDENCE_PATH
V5_FAILURE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_v5_failure_evidence.py"
)
EXPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "export_admin_dependency_cache.sh"
IMPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "import_admin_dependency_cache.sh"
BASE_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle.py"
)
V3_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v3.py"
)
BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v6.py"
)
DOWNLOAD_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "download_admin_dependency_cache_artifact.sh"
)
PROVIDER_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_provider_download.py"
)

WORKFLOW_SHA256 = (
    "65afd81d42dbe16d3b4054aecc10e2c5861c9454cc8ec061c7227056292bb26b"
)
TEMPLATE_SHA256 = (
    "fe34f3b07102478aa6e99e98b0deb399aeb95c0955ebd2ad8ce9ecc1afefd196"
)
TRANSIENT_VERIFIER_SHA256 = (
    "4b81fb25c259a5a5c8a3f115b6d4539698280c744535c5ff002b658dbec9cb5f"
)
CLEANUP_HELPER_SHA256 = (
    "a291c7242a0ac343faca19a921b2ad056d212aa2ef175a6b58b33ef028bbf239"
)
PROVENANCE_FIXTURE_SHA256 = (
    "33de770d1f2d31ab794d914c28e0f148cb614629fece4dc50ad9a68fe665999d"
)
RAWJSON_FIXTURE_SHA256 = (
    "44429de50d1d823a06cd4b17a10b3a9d19e674418dd7ff065929ed02237245ce"
)
STRUCTURAL_FIXTURE_SHA256 = (
    "4b7a087c813b82085dd8ccb1255b8e873e834510ee652d12ff9443b72a29dac5"
)
V5_WORKFLOW_SHA256 = (
    "a784ed678e642d0c958ee89d1937dbd1ac73b88352a56f9ef14b1615a2b3546a"
)
V5_TEMPLATE_SHA256 = (
    "766a87aec122860e325730eeebc24a705ec777dc157ae603b3e154ffd6d6dfad"
)
V5_REQUEST_SHA256 = (
    "417ecf201b61bab280af1f6db59eec98d4fa8ff672c609765b82bdb4b52b5b93"
)
V5_PLAN_VERIFIER_SHA256 = (
    "78d58b5bbfa5971a968fa2b52a9ddb27e791393979ca558efcfae5b902be86ef"
)
V4_TRANSIENT_VERIFIER_SHA256 = (
    "a6578845bc220f38ffc819ced26d8d0c3530b37e53ebc4c74cceeb4b523ea432"
)
V5_FAILURE_EVIDENCE_SHA256 = (
    "0deb75a5e2c1081db3599f30139fabc21c2931f0bc05420d7713796329729a06"
)
V5_FAILURE_VERIFIER_SHA256 = (
    "07c4991852b49dddd8577e60bb3360aa5b3eac2879daad88adaab2fd8ad09fdb"
)
EXPORT_HELPER_SHA256 = (
    "fabcdc2245c537c2fd56e88b6e0aced77d5c26234fc74d7d934b11ecda8d860c"
)
IMPORT_HELPER_SHA256 = (
    "c4986143d5897140f72ad6835b44f7fc989830a30341cb4e3f5718fced3ca777"
)
BASE_BUNDLE_VERIFIER_SHA256 = (
    "bf526c29b213dc15d257cb9aedc52790aa1dc9cf1f82bba0e6e85e41db3edf38"
)
V3_BUNDLE_VERIFIER_SHA256 = (
    "c2e318d5d9cbe196d8b9294277c85e1ee986ccb3e1970b3d25a31d28c8da0fef"
)
BUNDLE_VERIFIER_SHA256 = (
    "86d93114e804bf6a51fdb160651d6a20c555f107b88020e0f8d811d0f0d358e5"
)
DOWNLOAD_HELPER_SHA256 = (
    "66abfd513be7aa81946072493e1472030a8acccbf7a3e2d4dc461c94712e2a92"
)
PROVIDER_VERIFIER_SHA256 = (
    "ca05697d12b8c02b183b1c611c33781d63641c5369bc54b2508a538591a0986b"
)

V5_PLAN_PARENT = "ec4b806ea7ffe24de6f8005d077bb6d81a0ec1c9"
V5_CONTROL_COMMIT = "58871b0be3427ed643f44bc198c9fe3c87a01600"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_WORKFLOW_HEADER = """name: Admin dependency cache export V6

on:
  push:
    branches:
      - codex/quality-stabilization-real-chain
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v6.json
"""
EXPECTED_TEMPLATE: dict[str, Any] = {
    "schema_version": 6,
    "task": "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
    "release_commit": RELEASE_COMMIT,
    "plan_checkpoint_commit": "__DIRECT_PARENT_COMMIT__",
    "release_scope": "admin_dependency_prefix_cache_recovery",
    "trigger_mode": "one_shot_added_request_v6",
    "predecessor": {
        "control_commit": V5_CONTROL_COMMIT,
        "run_id": 30606218502,
        "run_attempt": 1,
        "conclusion": "failure",
        "artifact_count": 0,
        "rerun_authorized": False,
        "failure_evidence_sha256": V5_FAILURE_EVIDENCE_SHA256,
    },
    "recovery_basis": {
        "runner_image": "ubuntu-24.04",
        "predecessor_runner_image_observed_version": "20260720.247.2",
        "runner_image_version_pinned": False,
        "buildx_version": "v0.35.0",
        "buildx_source_commit": "a319e5b15052cf6557ceb666eb8ff6e32380b782",
        "buildkit_daemon_observed_version": "v0.31.2",
        "buildx_vendored_buildkit_client_version": "v0.31.0",
        "exact_buildkitd_flags": [
            "--allow-insecure-entitlement=network.host",
        ],
        "additional_buildkitd_flags_authorized": False,
        "build_network_host_authorized": False,
        "github_actions_provenance_injection_authorized": False,
        "buildkit_auth_behavior": "ordinary_credentials_only",
        "phase_aware_client_state_required": True,
        "structured_cleanup_receipt_required": True,
        "frozen_v5_transient_cleanup_namespace_required": True,
        "pre_cleanup_deadline_seconds_from_control": 5700,
        "cleanup_deadline_seconds_from_control": 6300,
        "setup_call_maximum_seconds": 300,
        "export_call_maximum_seconds": 3600,
        "import_call_maximum_seconds": 900,
        "cleanup_external_call_maximum_seconds": 15,
        "atomic_docker_baseline_required": True,
    },
    "bundle_verifier_chain": {
        "v2_sha256": BASE_BUNDLE_VERIFIER_SHA256,
        "v3_sha256": V3_BUNDLE_VERIFIER_SHA256,
        "v6_sha256": BUNDLE_VERIFIER_SHA256,
    },
    "build_evidence_recovery": {
        "v5_dynamic_progress_retained": False,
        "source_projection_only_not_v5_runtime_evidence": True,
        "nested_solve_status_parser_required": True,
        "digest_mapping_source_location_binding_required": True,
        "decoded_original_log_scan_required": True,
        "original_progress_sha256_required": True,
        "frozen_v3_delegate_required": True,
        "compatibility_progress_persistence_authorized": False,
    },
    "recovery_run_authorized_after_predecessor_failure": True,
    "github_actions_maximum_run_count": 1,
    "github_actions_maximum_runtime_minutes": 120,
    "artifact_retention_days": 1,
    "artifact_compressed_maximum_bytes": 3_758_096_384,
    "artifact_input_maximum_bytes": 4_026_531_840,
    "artifact_provider_maximum_bytes": 4_294_967_296,
    "authenticated_artifact_download_maximum_count": 1,
    "cross_provider_transfer_maximum_count": 1,
    "artifact_visibility_assumption": "public_repository_readers",
    "dependency_cache_export_authorized": True,
    "public_repository_artifact_authorized": True,
    "cross_provider_transfer_authorized": True,
    "registry_publication_authorized": False,
    "deployment_authorized": False,
    "database_authorized": False,
    "service_mutation_authorized": False,
    "public_traffic_authorized": False,
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_at(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _git(*args: str) -> str:
    return _git_at(ROOT, *args)


def _request_additions(
    *,
    root: Path = ROOT,
    request_path: Path | None = None,
    all_refs: bool = True,
) -> list[str]:
    relative = (
        ACTIVE_REQUEST_PATH.relative_to(ROOT)
        if request_path is None
        else request_path
    )
    args = ["log"]
    if all_refs:
        args.append("--all")
    else:
        args.append(_git_at(root, "rev-parse", "HEAD"))
    args.extend(
        [
            "--diff-filter=A",
            "--format=%H",
            "--",
            relative.as_posix(),
        ]
    )
    output = _git_at(root, *args)
    return output.splitlines() if output else []


def _validate_active_request(
    request_bytes: bytes,
    template_bytes: bytes,
    *,
    plan_parent: str | None,
    verify_git_state: bool,
    root: Path = ROOT,
    request_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        request = v5_plan.v4_plan.strict_json(request_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid V6 active request: {exc}"]
    parent = request.get("plan_checkpoint_commit")
    if not isinstance(parent, str) or not COMMIT_RE.fullmatch(parent):
        return ["V6 active request checkpoint is invalid"]
    if plan_parent is not None and parent != plan_parent:
        errors.append("V6 active request does not bind its direct parent")
    expected_bytes = template_bytes.replace(
        b"__DIRECT_PARENT_COMMIT__",
        parent.encode("ascii"),
    )
    if request_bytes != expected_bytes:
        errors.append("V6 active request differs from reviewed template")
    expected = dict(EXPECTED_TEMPLATE)
    expected["plan_checkpoint_commit"] = parent
    if request != expected:
        errors.append("V6 active request semantics drift")
    if not verify_git_state:
        return errors
    try:
        relative = (
            ACTIVE_REQUEST_PATH.relative_to(ROOT)
            if request_path is None
            else request_path
        )
        additions = _request_additions(
            root=root,
            request_path=relative,
            all_refs=True,
        )
        if len(additions) != 1:
            return errors + ["V6 active request addition history is not unique"]
        activation = additions[0]
        parents = _git_at(
            root,
            "rev-list",
            "--parents",
            "-n",
            "1",
            activation,
        ).split()
        if len(parents) != 2:
            return errors + ["V6 controller is not single-parent"]
        if parent != parents[1]:
            errors.append("V6 request checkpoint differs from controller parent")
        changed = _git_at(
            root,
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            parents[1],
            activation,
        ).splitlines()
        if changed != [relative.as_posix()]:
            errors.append("V6 activation changes more than its request")
        added = _git_at(
            root,
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--diff-filter=A",
            "--name-status",
            "-r",
            parents[1],
            activation,
            "--",
            relative.as_posix(),
        )
        if added != f"A\t{relative.as_posix()}":
            errors.append("V6 request was not a unique addition")
        mode = _git_at(root, "ls-tree", "HEAD", "--", relative.as_posix()).split()
        if mode[:2] != ["100644", "blob"]:
            errors.append("V6 request is not retained as 100644")
        current = subprocess.run(
            ["git", "show", f"HEAD:{relative.as_posix()}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if current != request_bytes:
            errors.append("V6 request bytes changed after activation")
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V6 active request Git state: {exc}")
    return errors


def validate_plan(
    *,
    workflow_bytes: bytes | None = None,
    template_bytes: bytes | None = None,
    transient_verifier_bytes: bytes | None = None,
    cleanup_helper_bytes: bytes | None = None,
    provenance_fixture_bytes: bytes | None = None,
    rawjson_fixture_bytes: bytes | None = None,
    structural_fixture_bytes: bytes | None = None,
    active_request_bytes: bytes | None = None,
    active_plan_parent: str | None = None,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []
    active_supplied = active_request_bytes is not None

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        workflow_bytes = (
            WORKFLOW_PATH.read_bytes() if workflow_bytes is None else workflow_bytes
        )
        template_bytes = (
            TEMPLATE_PATH.read_bytes() if template_bytes is None else template_bytes
        )
        transient_verifier_bytes = (
            TRANSIENT_VERIFIER_PATH.read_bytes()
            if transient_verifier_bytes is None
            else transient_verifier_bytes
        )
        cleanup_helper_bytes = (
            CLEANUP_HELPER_PATH.read_bytes()
            if cleanup_helper_bytes is None
            else cleanup_helper_bytes
        )
        provenance_fixture_bytes = (
            PROVENANCE_FIXTURE_PATH.read_bytes()
            if provenance_fixture_bytes is None
            else provenance_fixture_bytes
        )
        rawjson_fixture_bytes = (
            RAWJSON_FIXTURE_PATH.read_bytes()
            if rawjson_fixture_bytes is None
            else rawjson_fixture_bytes
        )
        structural_fixture_bytes = (
            STRUCTURAL_FIXTURE_PATH.read_bytes()
            if structural_fixture_bytes is None
            else structural_fixture_bytes
        )
        if active_request_bytes is None and ACTIVE_REQUEST_PATH.exists():
            active_request_bytes = ACTIVE_REQUEST_PATH.read_bytes()
    except OSError as exc:
        return [f"cannot load V6 dependency-cache plan: {exc}"]

    fixed_paths = (
        (workflow_bytes, WORKFLOW_SHA256, "V6 workflow"),
        (template_bytes, TEMPLATE_SHA256, "V6 template"),
        (
            transient_verifier_bytes,
            TRANSIENT_VERIFIER_SHA256,
            "V6 transient verifier",
        ),
        (cleanup_helper_bytes, CLEANUP_HELPER_SHA256, "V6 cleanup helper"),
        (
            provenance_fixture_bytes,
            PROVENANCE_FIXTURE_SHA256,
            "V6 provenance source fixture",
        ),
        (
            rawjson_fixture_bytes,
            RAWJSON_FIXTURE_SHA256,
            "V6 rawjson source fixture",
        ),
        (
            structural_fixture_bytes,
            STRUCTURAL_FIXTURE_SHA256,
            "V6 structural source fixture",
        ),
        (V5_WORKFLOW_PATH.read_bytes(), V5_WORKFLOW_SHA256, "frozen V5 workflow"),
        (V5_TEMPLATE_PATH.read_bytes(), V5_TEMPLATE_SHA256, "frozen V5 template"),
        (V5_REQUEST_PATH.read_bytes(), V5_REQUEST_SHA256, "frozen V5 request"),
        (
            V5_PLAN_VERIFIER_PATH.read_bytes(),
            V5_PLAN_VERIFIER_SHA256,
            "frozen V5 plan verifier",
        ),
        (
            V4_TRANSIENT_VERIFIER_PATH.read_bytes(),
            V4_TRANSIENT_VERIFIER_SHA256,
            "frozen V4 transient base verifier",
        ),
        (
            V5_FAILURE_EVIDENCE_PATH.read_bytes(),
            V5_FAILURE_EVIDENCE_SHA256,
            "V5 terminal evidence",
        ),
        (
            V5_FAILURE_VERIFIER_PATH.read_bytes(),
            V5_FAILURE_VERIFIER_SHA256,
            "V5 terminal evidence verifier",
        ),
        (EXPORT_HELPER_PATH.read_bytes(), EXPORT_HELPER_SHA256, "export helper"),
        (IMPORT_HELPER_PATH.read_bytes(), IMPORT_HELPER_SHA256, "import helper"),
        (
            BASE_BUNDLE_VERIFIER_PATH.read_bytes(),
            BASE_BUNDLE_VERIFIER_SHA256,
            "base bundle verifier",
        ),
        (
            V3_BUNDLE_VERIFIER_PATH.read_bytes(),
            V3_BUNDLE_VERIFIER_SHA256,
            "V3 bundle verifier",
        ),
        (
            BUNDLE_VERIFIER_PATH.read_bytes(),
            BUNDLE_VERIFIER_SHA256,
            "V6 bundle verifier",
        ),
        (
            DOWNLOAD_HELPER_PATH.read_bytes(),
            DOWNLOAD_HELPER_SHA256,
            "download helper",
        ),
        (
            PROVIDER_VERIFIER_PATH.read_bytes(),
            PROVIDER_VERIFIER_SHA256,
            "provider verifier",
        ),
    )
    for actual, expected, label in fixed_paths:
        require(
            sha256_bytes(actual) == expected,
            f"{label} hash drift",
        )

    try:
        template = v5_plan.v4_plan.strict_json(template_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V6 request template: {exc}")
        template = {}
    require(template == EXPECTED_TEMPLATE, "V6 request template drift")
    require(
        template_bytes.count(b"__DIRECT_PARENT_COMMIT__") == 1,
        "V6 request parent placeholder count changed",
    )
    try:
        fixture = v5_plan.v4_plan.strict_json(provenance_fixture_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V6 provenance fixture: {exc}")
        fixture = {}
    require(
        fixture.get("classification")
        == "SOURCE_PROVEN_CONFIGURATION_CONTRACT_NOT_V5_RUNTIME_EVIDENCE",
        "V6 provenance fixture classification changed",
    )
    require(
        fixture.get("actual_v5_runtime_metadata_retained") is False,
        "V6 provenance fixture overclaims runtime evidence",
    )
    require(
        fixture.get("v5_expected_configuration", {}).get(
            "pre_build_direct_json_file_count"
        )
        == 0,
        "V6 provenance pre-build projection changed",
    )
    try:
        rawjson_fixture = v5_plan.v4_plan.strict_json(rawjson_fixture_bytes)
        structural_fixture = v5_plan.v4_plan.strict_json(
            structural_fixture_bytes
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V6 source fixture: {exc}")
        rawjson_fixture = {}
        structural_fixture = {}
    require(
        rawjson_fixture.get("classification")
        == "SOURCE_PROVEN_RAWJSON_SCHEMA_NOT_V5_RUNTIME_EVIDENCE"
        and rawjson_fixture.get("actual_v5_runtime_progress_retained")
        is False
        and rawjson_fixture.get("frozen_v5_verifier_projection", {}).get(
            "iterates_nested_vertexes"
        )
        is False,
        "V6 rawjson source projection changed",
    )
    require(
        structural_fixture.get("classification")
        == "SOURCE_PROVEN_SCHEMA_CONTRACT_NOT_V5_RUNTIME_EVIDENCE"
        and structural_fixture.get("actual_v5_runtime_metadata_retained")
        is False
        and structural_fixture.get("actual_v5_runtime_progress_retained")
        is False
        and structural_fixture.get("v6_binding_contract", {}).get(
            "ordered_chain"
        )
        == [
            "SolveStatus.vertexes[].digest",
            "buildConfig.digestMapping[digest]",
            "llbDefinition[].id",
            "llbDefinition[].op.Op.exec",
            "metadata.source.locations[step-id]",
        ],
        "V6 structural source projection changed",
    )

    errors.extend(f"frozen V5 plan: {item}" for item in v5_plan.validate_plan())
    try:
        evidence_payload = v5_failure.load_strict()
        errors.extend(
            f"V5 terminal evidence: {item}"
            for item in v5_failure.verify(evidence_payload)
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot verify V5 terminal evidence: {exc}")
    if verify_git_state:
        try:
            require(
                v5_plan._request_additions() == [V5_CONTROL_COMMIT],
                "V5 request addition history changed",
            )
            require(
                _git("rev-list", "--parents", "-n", "1", V5_CONTROL_COMMIT)
                == f"{V5_CONTROL_COMMIT} {V5_PLAN_PARENT}",
                "V5 control parent changed",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify V5 control history: {exc}")

    if active_request_bytes is not None:
        errors.extend(
            _validate_active_request(
                active_request_bytes,
                template_bytes,
                plan_parent=active_plan_parent,
                verify_git_state=verify_git_state and not active_supplied,
            )
        )
    elif verify_git_state:
        try:
            if _request_additions():
                errors.append("inactive V6 request has prior addition history")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify inactive V6 request history: {exc}")

    workflow = workflow_bytes.decode("utf-8", errors="replace")
    transient = transient_verifier_bytes.decode("utf-8", errors="replace")
    cleanup = cleanup_helper_bytes.decode("utf-8", errors="replace")
    export_helper = EXPORT_HELPER_PATH.read_text(encoding="utf-8")
    import_helper = IMPORT_HELPER_PATH.read_text(encoding="utf-8")
    v3_bundle_verifier = V3_BUNDLE_VERIFIER_PATH.read_text(
        encoding="utf-8"
    )
    bundle_verifier = BUNDLE_VERIFIER_PATH.read_text(encoding="utf-8")

    for forbidden in (
        "workflow_dispatch:",
        "pull_request:",
        "schedule:",
        "repository_dispatch:",
        "secrets.",
        "id-token: write",
        "packages: write",
        "docker/login-action",
        "docker push",
        "--push",
        "security.insecure",
        "--provenance=",
        "--buildkitd-config",
        "BUILDX_NO_DEFAULT_ATTESTATIONS",
        "GITHUB_ACTIONS:",
        "GITHUB_EVENT_NAME:",
        "GITHUB_EVENT_PATH:",
        "set -x",
    ):
        require(forbidden not in workflow, f"V6 workflow forbidden token: {forbidden}")
    require(
        workflow.split("\npermissions:", 1)[0] == EXPECTED_WORKFLOW_HEADER,
        "V6 trigger block changed",
    )
    require(
        "permissions:\n  contents: read" in workflow,
        "V6 workflow permissions changed",
    )
    require(
        workflow.count(
            "DOCKER_CONFIG: ${{ runner.temp }}/noteai-empty-docker-config-v5"
        )
        == 4,
        "V6 Docker config step count changed",
    )
    require(
        workflow.count(
            "BUILDX_CONFIG: ${{ runner.temp }}/noteai-buildx-state-v5"
        )
        == 4,
        "V6 Buildx config step count changed",
    )
    require(
        workflow.count('BUILDKIT_NO_CLIENT_TOKEN: "1"') == 1,
        "V6 client-token control changed",
    )
    require(
        workflow.count("BUILDX_METADATA_PROVENANCE: max") == 1,
        "V6 max provenance setting changed",
    )
    require(
        "admin-5335bda-dependency-cache-v6.json" in workflow,
        "V6 trigger path changed",
    )
    require(
        ".github/workflows/admin-dependency-cache-export-v6.yml"
        not in workflow.split("permissions:", 1)[0],
        "V6 workflow triggers on installation",
    )
    require("timeout-minutes: 120" in workflow, "V6 runtime cap changed")
    for required, message in (
        (
            'NOTEAI_PRE_CLEANUP_BUDGET_SECONDS: "5700"',
            "V6 pre-cleanup budget changed",
        ),
        (
            'NOTEAI_CLEANUP_BUDGET_SECONDS: "6300"',
            "V6 cleanup budget changed",
        ),
        (
            'NOTEAI_SETUP_CALL_MAX_SECONDS: "300"',
            "V6 setup call timeout changed",
        ),
        (
            'NOTEAI_EXPORT_CALL_MAX_SECONDS: "3600"',
            "V6 export call timeout changed",
        ),
        (
            'NOTEAI_IMPORT_CALL_MAX_SECONDS: "900"',
            "V6 import call timeout changed",
        ),
        (
            'NOTEAI_CLEANUP_COMMAND_TIMEOUT_SECONDS: "15"',
            "V6 cleanup call timeout changed",
        ),
    ):
        require(
            workflow.count(required) == 1,
            message,
        )
    require(
        workflow.count("run_before_cleanup_deadline()") == 3
        and workflow.count("--kill-after=15s") == 3
        and workflow.count(
            "NOTEAI_PRE_CLEANUP_DEADLINE_EPOCH - now_epoch"
        )
        == 3
        and "NOTEAI_PRE_CLEANUP_DEADLINE_EPOCH=%s" in workflow
        and "NOTEAI_CLEANUP_DEADLINE_EPOCH=%s" in workflow,
        "V6 cleanup headroom control changed",
    )
    deadline_initializer = workflow.find(
        "    steps:\n"
        "      - name: Initialize V6 bounded job deadlines"
    )
    first_checkout = workflow.find(
        "      - name: Checkout V6 one-shot controller"
    )
    require(
        deadline_initializer >= 0
        and first_checkout > deadline_initializer
        and workflow.count('job_control_epoch="$(date +%s)"') == 1
        and workflow.count(
            "job_control_epoch + NOTEAI_PRE_CLEANUP_BUDGET_SECONDS"
        )
        == 1
        and workflow.count(
            "job_control_epoch + NOTEAI_CLEANUP_BUDGET_SECONDS"
        )
        == 1,
        "V6 deadline is not initialized before checkout",
    )
    require(
        (
            'run_before_cleanup_deadline \\\n'
            '            "${NOTEAI_EXPORT_CALL_MAX_SECONDS}" \\\n'
            '            "${NOTEAI_EXPORT_HELPER_PATH}"'
        )
        in workflow
        and (
            'run_before_cleanup_deadline \\\n'
            '            "${NOTEAI_IMPORT_CALL_MAX_SECONDS}" \\\n'
            '            bash "${{ steps.control.outputs.import_helper_copy }}"'
        )
        in workflow,
        "V6 helper timeout envelope changed",
    )
    require("retention-days: 1" in workflow, "V6 retention changed")
    require("compression-level: 0" in workflow, "V6 compression changed")
    require(
        workflow.count('test "${GITHUB_RUN_ATTEMPT}" = "1"') == 2,
        "V6 rerun guards changed",
    )
    expected_create = (
        'docker buildx create \\\n'
        '            --name "${NOTEAI_PRODUCER_BUILDER}" \\\n'
        "            --driver docker-container \\\n"
        '            --driver-opt "image=${NOTEAI_BUILDKIT_IMAGE}" \\\n'
        '            --driver-opt "provenance-add-gha=false" \\\n'
        '            --buildkitd-flags "${NOTEAI_BUILDKITD_FLAGS}"'
    )
    expected_consumer_create = expected_create.replace(
        "NOTEAI_PRODUCER_BUILDER",
        "NOTEAI_CONSUMER_BUILDER",
    )
    require(
        workflow.count(expected_create) == 1
        and workflow.count(expected_consumer_create) == 1
        and workflow.count("docker buildx create \\") == 2
        and workflow.count("--driver-opt ") == 4,
        "V6 isolated builder options changed",
    )
    require(
        workflow.count('--driver-opt "provenance-add-gha=false"') == 2,
        "V6 provenance driver option changed",
    )
    require(
        workflow.count(
            '--buildkitd-flags "${NOTEAI_BUILDKITD_FLAGS}"'
        )
        == 2
        and (
            'NOTEAI_BUILDKITD_FLAGS: '
            '"--allow-insecure-entitlement=network.host"'
        )
        in workflow,
        "V6 exact BuildKit daemon flags changed",
    )
    require(
        "NOTEAI_BUILDX_VERSION: v0.35.0" in workflow
        and (
            "NOTEAI_BUILDX_SOURCE_COMMIT: "
            "a319e5b15052cf6557ceb666eb8ff6e32380b782"
        )
        in workflow
        and (
            "moby/buildkit@sha256:"
            "2f5adac4ecd194d9f8c10b7b5d7bceb"
            "5186853db1b26e5abd3a657af0b7e26ec"
        )
        in workflow
        and ')" = "v0.31.2"' in workflow,
        "V6 Buildx/BuildKit identity changed",
    )
    require(
        workflow.count(
            "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        )
        == 2
        and workflow.count(
            "uses: actions/upload-artifact@"
            "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        )
        == 1,
        "V6 action pins changed",
    )
    for required in (
        'test "${#changed_files[@]}" -eq 1',
        'test "${changed_files[0]}" = "${NOTEAI_REQUEST_PATH}"',
        "--no-renames --diff-filter=A",
        'test "${#request_add_commits[@]}" -eq 1',
        'test "${request_add_commits[0]}" = "${GITHUB_SHA}"',
        "git log --all --diff-filter=A",
        "NOTEAI_V5_CONTROL_COMMIT",
        "NOTEAI_V5_REQUEST_SHA256",
        "NOTEAI_V5_WORKFLOW_SHA256",
        "NOTEAI_V5_PLAN_VERIFIER_SHA256",
        "NOTEAI_V5_PLAN_PARENT",
        "NOTEAI_V4_TRANSIENT_VERIFIER_SHA256",
        "NOTEAI_FAILURE_EVIDENCE_SHA256",
        "NOTEAI_FAILURE_EVIDENCE_VERIFIER_SHA256",
        "NOTEAI_V5_RAWJSON_SOURCE_PROJECTION_SHA256",
        "NOTEAI_V6_STRUCTURAL_SOURCE_PROJECTION_SHA256",
        'python3 "${NOTEAI_V5_PLAN_VERIFIER_PATH}"',
        'python3 "${NOTEAI_FAILURE_EVIDENCE_VERIFIER_PATH}"',
        "__DIRECT_PARENT_COMMIT__",
        'cmp "${request_file}" "${expected_request}"',
        "recovery_run_authorized_after_predecessor_failure == true",
        "rerun_authorized: false",
        "artifact_count: 0",
        "github_actions_provenance_injection_authorized: false",
        'buildkit_auth_behavior: "ordinary_credentials_only"',
        "registry_publication_authorized == false",
        "git merge-base --is-ancestor",
        "persist-credentials: false",
        "NOTEAI_BASE_BUNDLE_VERIFIER_PATH",
        "NOTEAI_V3_BUNDLE_VERIFIER_PATH",
        "NOTEAI_BUNDLE_VERIFIER_PATH",
        "NOTEAI_TRANSIENT_STATE_VERIFIER_PATH",
        "NOTEAI_CLEANUP_HELPER_PATH",
        "noteai-docker-baseline-v5=complete",
        '"${images_before}.tmp"',
        'LC_ALL=C sort -u > "${images_before}.tmp"',
        'mv -- "${images_before}.tmp" "${images_before}"',
        'mv -- "${baseline_marker}.tmp" "${baseline_marker}"',
        "cleanup_passed == 'true'",
        'rm -rf --one-file-system -- "${NOTEAI_CACHE_BUNDLE_DIR}"',
    ):
        require(required in workflow, f"V6 workflow contract missing: {required}")

    require(
        "name: Admin dependency cache export V6" in workflow
        and (
            "group: admin-dependency-cache-export-v6-${{ github.sha }}"
            in workflow
        )
        and (
            'NOTEAI_ARTIFACT_NAME: '
            '"admin-dependency-prefix-cache-5335bda-v6"'
            in workflow
        )
        and workflow.count(
            "noteai-admin-dependency-cache-bundle-v6"
        )
        >= 6
        and "unused-v6-import-evidence" in workflow
        and "noteai-final-cache-v6-validation" in workflow
        and "noteai-final-bundle-v6-validation.json" in workflow,
        "V6 outer workflow identity changed",
    )
    require(
        "noteai-admin-dependency-cache-bundle-v5" not in workflow
        and "unused-v5-import-evidence" not in workflow
        and "noteai-final-cache-v5-validation" not in workflow
        and "noteai-final-bundle-v5-validation.json" not in workflow
        and "admin_dependency_cache_v5_artifact" not in workflow,
        "V6 outer workflow retains V5 identity",
    )
    require(
        "noteai-empty-docker-config-v6" not in workflow
        and "noteai-buildx-state-v6" not in workflow
        and "noteai-admin-cache-v6-producer" not in workflow
        and "noteai-admin-cache-v6-consumer" not in workflow
        and "noteai-docker-baseline-v6" not in workflow
        and "dependency-cache-cleanup-v6.json" not in workflow
        and (
            "NOTEAI_TRANSIENT_STATE_VERIFIER_PATH: "
            "tools/verify_admin_dependency_cache_transient_state_v5.py"
            in workflow
        )
        and (
            "NOTEAI_CLEANUP_HELPER_PATH: "
            "scripts/ci/cleanup_admin_dependency_cache_v5.sh"
            in workflow
        )
        and "noteai-docker-baseline-v5.complete" in workflow
        and "noteai-admin-dependency-cache-cleanup-v5.json" in workflow
        and "noteai-images-before" in workflow
        and "noteai-containers-before" in workflow
        and "noteai-volumes-before" in workflow
        and "noteai-networks-before" in workflow
        and workflow.count(
            "NOTEAI_PRODUCER_BUILDER: "
            "noteai-admin-cache-v5-producer-${{ github.run_id }}"
        )
        == 1
        and workflow.count(
            "NOTEAI_CONSUMER_BUILDER: "
            "noteai-admin-cache-v5-consumer-${{ github.run_id }}"
        )
        == 1,
        "V6 frozen V5 runtime namespace changed",
    )
    require(
        (
            "NOTEAI_BASE_BUNDLE_VERIFIER_PATH: "
            "tools/verify_admin_dependency_cache_bundle.py"
            in workflow
        )
        and (
            "NOTEAI_BASE_BUNDLE_VERIFIER_SHA256: "
            f"{BASE_BUNDLE_VERIFIER_SHA256}"
            in workflow
        )
        and (
            "NOTEAI_V3_BUNDLE_VERIFIER_PATH: "
            "tools/verify_admin_dependency_cache_bundle_v3.py"
            in workflow
        )
        and (
            "NOTEAI_V3_BUNDLE_VERIFIER_SHA256: "
            f"{V3_BUNDLE_VERIFIER_SHA256}"
            in workflow
        )
        and (
            "NOTEAI_BUNDLE_VERIFIER_PATH: "
            "tools/verify_admin_dependency_cache_bundle_v6.py"
            in workflow
        )
        and (
            "NOTEAI_BUNDLE_VERIFIER_SHA256: "
            f"{BUNDLE_VERIFIER_SHA256}"
            in workflow
        )
        and workflow.count(
            "NOTEAI_BASE_BUNDLE_VERIFIER_PATH: "
            "${{ steps.control.outputs.base_verifier_copy }}"
        )
        == 3
        and workflow.count(
            "NOTEAI_V3_BUNDLE_VERIFIER_PATH: "
            "${{ steps.control.outputs.v3_verifier_copy }}"
        )
        == 3
        and workflow.count(
            'v3_verifier_copy="${RUNNER_TEMP}/'
            'noteai-cache-v6-bundle-v3.py"'
        )
        == 1
        and 'cp "${NOTEAI_V3_BUNDLE_VERIFIER_PATH}" '
        '"${v3_verifier_copy}"' in workflow
        and 'cp "${NOTEAI_BASE_BUNDLE_VERIFIER_PATH}" '
        '"${base_verifier_copy}"' in workflow
        and 'cp "${NOTEAI_BUNDLE_VERIFIER_PATH}" '
        '"${bundle_verifier_copy}"' in workflow
        and 'printf \'v3_verifier_copy=%s\\n\' '
        '"${v3_verifier_copy}"' in workflow
        and (
            'NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH: '
            '${{ steps.control.outputs.bundle_verifier_copy }}'
            in workflow
        )
        and (
            '"${{ steps.control.outputs.bundle_verifier_copy }}" \\\n'
            "            verify-final"
            in workflow
        ),
        "V6 three-layer bundle trust matrix changed",
    )
    require(
        "github_actions_maximum_run_count == 1" in workflow
        and "artifact_compressed_maximum_bytes == 3758096384"
        in workflow
        and "authenticated_artifact_download_maximum_count == 1"
        in workflow
        and "cross_provider_transfer_maximum_count == 1" in workflow
        and ".archive.maximum_gzip_bytes == 3758096384" in workflow,
        "V6 authorized artifact bounds changed",
    )
    require(
        f"NOTEAI_V5_PLAN_PARENT: {V5_PLAN_PARENT}" in workflow
        and f"NOTEAI_V5_CONTROL_COMMIT: {V5_CONTROL_COMMIT}"
        in workflow
        and f"NOTEAI_V5_REQUEST_SHA256: {V5_REQUEST_SHA256}"
        in workflow
        and f"NOTEAI_V5_WORKFLOW_SHA256: {V5_WORKFLOW_SHA256}"
        in workflow
        and f"NOTEAI_V5_TEMPLATE_SHA256: {V5_TEMPLATE_SHA256}"
        in workflow
        and (
            f"NOTEAI_V5_PLAN_VERIFIER_SHA256: "
            f"{V5_PLAN_VERIFIER_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_FAILURE_EVIDENCE_SHA256: "
            f"{V5_FAILURE_EVIDENCE_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_FAILURE_EVIDENCE_VERIFIER_SHA256: "
            f"{V5_FAILURE_VERIFIER_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_V5_RAWJSON_SOURCE_PROJECTION_SHA256: "
            f"{RAWJSON_FIXTURE_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_V6_STRUCTURAL_SOURCE_PROJECTION_SHA256: "
            f"{STRUCTURAL_FIXTURE_SHA256}"
            in workflow
        )
        and "run_id: 30606218502" in workflow
        and "artifact_count: 0" in workflow
        and "rerun_authorized: false" in workflow,
        "V6 predecessor terminal chain changed",
    )

    baseline_atomic_sequence = (
        'LC_ALL=C sort -u > "${images_before}.tmp"',
        'chmod 0600 "${images_before}.tmp"',
        'LC_ALL=C sort -u > "${containers_before}.tmp"',
        'chmod 0600 "${containers_before}.tmp"',
        'LC_ALL=C sort -u > "${volumes_before}.tmp"',
        'chmod 0600 "${volumes_before}.tmp"',
        'LC_ALL=C sort -u > "${networks_before}.tmp"',
        'chmod 0600 "${networks_before}.tmp"',
        'mv -- "${images_before}.tmp" "${images_before}"',
        'mv -- "${containers_before}.tmp" "${containers_before}"',
        'mv -- "${volumes_before}.tmp" "${volumes_before}"',
        'mv -- "${networks_before}.tmp" "${networks_before}"',
        "printf 'noteai-docker-baseline-v5=complete\\n'",
        'chmod 0600 "${baseline_marker}.tmp"',
        'mv -- "${baseline_marker}.tmp" "${baseline_marker}"',
    )
    baseline_positions = [
        workflow.find(token) for token in baseline_atomic_sequence
    ]
    require(
        all(position >= 0 for position in baseline_positions)
        and baseline_positions == sorted(baseline_positions)
        and len(set(baseline_positions)) == len(baseline_positions),
        "V6 Docker baseline atomic sequence changed",
    )

    probe_start = workflow.find('container_name="buildx_buildkit_${builder_name}0"')
    export_start = workflow.find(
        '\n            "${NOTEAI_EXPORT_HELPER_PATH}"',
        probe_start,
    )
    marker_start = workflow.find(
        'mv -- "${baseline_marker}.tmp" "${baseline_marker}"'
    )
    builder_create_start = workflow.find("docker buildx create \\")
    require(
        marker_start > 0
        and marker_start < builder_create_start
        and probe_start > builder_create_start
        and export_start > probe_start,
        "V6 baseline/provenance gate ordering changed",
    )
    for required in (
        "root=/etc/buildkit/provenance.d",
        '[ ! -L "${root}" ] || exit 41',
        '"${root}"/*.json',
        '"${root}"/.json',
        '"${root}"/.[!.]*.json',
        '"${root}"/..*.json',
        '"${root}"/..?*.json',
        "docker exec \"${container_name}\" sh -eu -c",
        "</dev/null >/dev/null 2>&1",
        "admin_dependency_cache_buildkit_provenance_dropins=ABSENT builders=2",
    ):
        require(required in workflow, f"V6 provenance gate missing: {required}")
    require(
        workflow.count("docker exec \"${container_name}\" sh -eu -c") == 1
        and (
            'for builder_name in \\\n'
            '            "${NOTEAI_PRODUCER_BUILDER}" \\\n'
            '            "${NOTEAI_CONSUMER_BUILDER}"'
        )
        in workflow,
        "V6 provenance gate builder coverage changed",
    )

    require(
        export_helper.count("--platform linux/amd64") == 1
        and import_helper.count("--platform linux/amd64") == 2,
        "V6 target platform contract changed",
    )
    for source_name, source in (
        ("export helper", export_helper),
        ("import helper", import_helper),
    ):
        require(
            "--allow network.host" not in source
            and "--allow=network.host" not in source
            and "--network=host" not in source,
            f"{source_name} requests build-level host networking",
        )
    for required in (
        "maximum_gzip_bytes=3758096384",
        "maximum_artifact_input_bytes=4026531840",
        "maximum_provider_artifact_bytes=4294967296",
    ):
        require(required in export_helper, f"V6 artifact limit missing: {required}")
    for required in (
        'EXPECTED_BUILDER_PLATFORM = "linux/amd64"',
        'EXPECTED_DOCKERFILE_FRONTEND_VERSION = "1.25.0"',
        "BuildKit builder environment changed",
        '"platform": EXPECTED_BUILDER_PLATFORM',
        '"dockerfileVersion": EXPECTED_DOCKERFILE_FRONTEND_VERSION',
    ):
        require(
            required in v3_bundle_verifier,
            f"V3 bundle verifier contract missing: {required}",
        )
    for required in (
        "V2_VERIFIER_SHA256",
        "V3_VERIFIER_SHA256",
        'os.environ.get("NOTEAI_V3_BUNDLE_VERIFIER_PATH")',
        '"vertexes", "statuses", "logs", "warnings"',
        "base64.b64decode",
        'build_config.get("digestMapping")',
        'source.get("locations")',
        "_legacy_evidence_view",
        "_patched_base_validator",
        "ORIGINAL_EVIDENCE_CHANGED",
        "PACKAGE_NETWORK_OUTPUT_OBSERVED",
        "RFC3339_RE",
    ):
        require(
            required in bundle_verifier,
            f"V6 bundle verifier contract missing: {required}",
        )
    require(
        'os.environ.get("NOTEAI_BASE_BUNDLE_VERIFIER_PATH")'
        in v3_bundle_verifier
        and "BASE_VERIFIER_SHA256" in v3_bundle_verifier
        and "V3_VERIFIER_SHA256" in bundle_verifier
        and "V2_VERIFIER_SHA256" in bundle_verifier,
        "V6 frozen bundle verifier chain changed",
    )
    for required in (
        "noteai-empty-docker-config-v5",
        "noteai-buildx-state-v5",
        "CLIENT_TOKEN_CONTROL",
        "provenance-add-gha",
        '"pre-build", "post-build", "cleanup-active"',
        "BUILD_NODE_ID_RE",
        "build_node_id_present",
        "FAIL: transient_state_contract_changed",
        "BASE_VERIFIER_SHA256",
    ):
        require(required in transient, f"V6 transient contract missing: {required}")
    for required in (
        "producer_builder_remove",
        "producer_builder_absent",
        "consumer_builder_remove",
        "consumer_builder_absent",
        "images_parity",
        "containers_parity",
        "volumes_parity",
        "networks_parity",
        "cleanup_effective",
        "overall_pass",
        "deadline_control_valid",
        "docker_baseline_state",
        "diagnostic_files_absent",
        "noteai-docker-baseline-v5=complete",
        "validate_baseline_marker",
        "validate_snapshot_file",
        "rm_nonzero_absent_after",
        "run_cleanup_command",
        "--kill-after=5s",
        "chmod u+rwx",
        "docker buildx ls --format '{{.Name}}'",
        '[[ ! -e "${target}" ]] && [[ ! -L "${target}" ]]',
        "Admin dependency-cache cleanup failed closed",
    ):
        require(required in cleanup, f"V6 cleanup contract missing: {required}")
    cleanup_position = workflow.find(
        "Remove V6 builders and all transient Docker state"
    )
    upload_position = workflow.find(
        "Upload one-day V6 public-repository dependency cache artifact"
    )
    local_removal_position = workflow.find("Remove runner-local V6 bundle")
    require(
        0
        <= cleanup_position
        < upload_position
        < local_removal_position,
        "V6 cleanup/upload ordering changed",
    )
    return errors


def classify_plan_state(
    *,
    plan_errors: list[str],
    active_exists: bool,
    additions: list[str],
    active_git_errors: list[str],
) -> str:
    if plan_errors:
        return "INVALID"
    if active_exists:
        return (
            "V6_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V6_CONSUMED_OR_INVALID"
    return "PREPARED_V6_NOT_TRIGGERED"


def plan_state() -> str:
    base_errors = validate_plan(verify_git_state=False)
    try:
        additions = _request_additions()
    except (OSError, subprocess.CalledProcessError):
        return "INVALID"
    active_git_errors: list[str] = []
    if ACTIVE_REQUEST_PATH.exists():
        try:
            active_git_errors = _validate_active_request(
                ACTIVE_REQUEST_PATH.read_bytes(),
                TEMPLATE_PATH.read_bytes(),
                plan_parent=None,
                verify_git_state=True,
            )
        except OSError as exc:
            active_git_errors = [f"cannot load V6 active request: {exc}"]
    return classify_plan_state(
        plan_errors=base_errors,
        active_exists=ACTIVE_REQUEST_PATH.exists(),
        additions=additions,
        active_git_errors=active_git_errors,
    )


def main() -> int:
    errors = validate_plan()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"admin_dependency_cache_export_plan_v6=PASS state={plan_state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
