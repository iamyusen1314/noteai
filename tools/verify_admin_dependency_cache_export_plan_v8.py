#!/usr/bin/env python3
"""Verify the inert, append-only V8 Admin dependency-cache recovery plan."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import verify_admin_dependency_cache_export_plan_v7 as v7_plan
import verify_admin_dependency_cache_v7_failure_evidence as v7_failure


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v8.yml"
)
TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v8.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v8.json"
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
INCREMENTAL_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_incremental_vertex_projection.json"
)
EMPTY_LOCATION_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "empty_source_location_projection.json"
)
V7_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v7.yml"
)
V7_TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v7.json"
)
V7_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v7.json"
)
V7_PLAN_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_export_plan_v7.py"
)
V4_TRANSIENT_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v4.py"
)
V7_FAILURE_EVIDENCE_PATH = v7_failure.EVIDENCE_PATH
V7_FAILURE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_v7_failure_evidence.py"
)
EXPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "export_admin_dependency_cache.sh"
IMPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "import_admin_dependency_cache.sh"
BASE_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle.py"
)
V3_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v3.py"
)
V6_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v6.py"
)
V7_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v7.py"
)
BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v8.py"
)
DOWNLOAD_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "download_admin_dependency_cache_artifact.sh"
)
PROVIDER_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_provider_download.py"
)

WORKFLOW_SHA256 = (
    "370e17b59ce457efda8b5a6cd23d40937379d23d1a2aeb3f36ac7b88f72333b3"
)
TEMPLATE_SHA256 = (
    "ba2f705eff90285e377e8d683a059f7f23aef088dc7df2498d167909fff48e7c"
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
INCREMENTAL_FIXTURE_SHA256 = (
    "fb5c944a0006cb8e04f32e3ac98e949e27036b10077e4ce10bc0a6c8b4fb5de1"
)
EMPTY_LOCATION_FIXTURE_SHA256 = (
    "b5f5e806b7e822b536a850eca8861bb7b6f8934832d7bdb4e898e698d7f20eeb"
)
V7_WORKFLOW_SHA256 = (
    "3b4ec5ed8841253afe62ff54b7de7dfdd523d48d9dd3ce5837394fb4c5e9c427"
)
V7_TEMPLATE_SHA256 = (
    "e690b968c935ffa721535a0282b3d108fe6ce651431622f262894225cd0a29e7"
)
V7_REQUEST_SHA256 = (
    "161dc1cfbc8683cbc18816baffd01edfa50c5d4fca8edb2e85054fb79eeb37dd"
)
V7_PLAN_VERIFIER_SHA256 = (
    "bed5ee29dd367caa4faafb7c711fd4d97d740319622aa459fcc5000a866ebc6b"
)
V4_TRANSIENT_VERIFIER_SHA256 = (
    "a6578845bc220f38ffc819ced26d8d0c3530b37e53ebc4c74cceeb4b523ea432"
)
V7_FAILURE_EVIDENCE_SHA256 = (
    "91950799263f19b8422534b685cd1e46856e9d03137976ccec08ce1d644e3ed4"
)
V7_FAILURE_EVIDENCE_SEMANTIC_SHA256 = (
    "6ea653978234820dad155784d22887dfd61352e28f97571e3a18423b3893ad9a"
)
V7_FAILURE_VERIFIER_SHA256 = (
    "c1ae9caa594c48ff1a6d46f78d4aef84cb3a33e410ea9c2ae6bb2c17bf6ae476"
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
V6_BUNDLE_VERIFIER_SHA256 = (
    "86d93114e804bf6a51fdb160651d6a20c555f107b88020e0f8d811d0f0d358e5"
)
V7_BUNDLE_VERIFIER_SHA256 = (
    "76af4aa0c8dbe68b46cc71fb74f1582030c5f28a7218a2ee04bcbde5f4198cd7"
)
BUNDLE_VERIFIER_SHA256 = (
    "b07f9dee54862969fe90ef438c357a3445a9fe9574b69a9f87440e3ed9920300"
)
DOWNLOAD_HELPER_SHA256 = (
    "66abfd513be7aa81946072493e1472030a8acccbf7a3e2d4dc461c94712e2a92"
)
PROVIDER_VERIFIER_SHA256 = (
    "ca05697d12b8c02b183b1c611c33781d63641c5369bc54b2508a538591a0986b"
)

V7_PLAN_PARENT = "71692d5f25f6a2d3f248cc62a568f4a2bd5af2cd"
V7_CONTROL_COMMIT = "4494f50bf9a18422cef6252792bb9c6bbeaf1135"
V7_TERMINAL_CHECKPOINT = "6102ac231b68e3bc6b69db817fd834da0e37e1b9"
V7_TERMINAL_RECEIPT = "3714cc2feec65d3059325d0d869ad007083b0276"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_WORKFLOW_HEADER = """name: Admin dependency cache export V8

on:
  push:
    branches:
      - codex/quality-stabilization-real-chain
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v8.json
"""
EXPECTED_TEMPLATE: dict[str, Any] = json.loads(
    TEMPLATE_PATH.read_text(encoding="utf-8")
)


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
        request = v7_plan.v6_plan.v5_plan.v4_plan.strict_json(request_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid V8 active request: {exc}"]
    parent = request.get("plan_checkpoint_commit")
    if not isinstance(parent, str) or not COMMIT_RE.fullmatch(parent):
        return ["V8 active request checkpoint is invalid"]
    if plan_parent is not None and parent != plan_parent:
        errors.append("V8 active request does not bind its direct parent")
    expected_bytes = template_bytes.replace(
        b"__DIRECT_PARENT_COMMIT__",
        parent.encode("ascii"),
    )
    if request_bytes != expected_bytes:
        errors.append("V8 active request differs from reviewed template")
    expected = dict(EXPECTED_TEMPLATE)
    expected["plan_checkpoint_commit"] = parent
    if request != expected:
        errors.append("V8 active request semantics drift")
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
            return errors + ["V8 active request addition history is not unique"]
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
            return errors + ["V8 controller is not single-parent"]
        if parent != parents[1]:
            errors.append("V8 request checkpoint differs from controller parent")
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
            errors.append("V8 activation changes more than its request")
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
            errors.append("V8 request was not a unique addition")
        mode = _git_at(root, "ls-tree", "HEAD", "--", relative.as_posix()).split()
        if mode[:2] != ["100644", "blob"]:
            errors.append("V8 request is not retained as 100644")
        current = subprocess.run(
            ["git", "show", f"HEAD:{relative.as_posix()}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if current != request_bytes:
            errors.append("V8 request bytes changed after activation")
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V8 active request Git state: {exc}")
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
    incremental_fixture_bytes: bytes | None = None,
    empty_location_fixture_bytes: bytes | None = None,
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
        incremental_fixture_bytes = (
            INCREMENTAL_FIXTURE_PATH.read_bytes()
            if incremental_fixture_bytes is None
            else incremental_fixture_bytes
        )
        empty_location_fixture_bytes = (
            EMPTY_LOCATION_FIXTURE_PATH.read_bytes()
            if empty_location_fixture_bytes is None
            else empty_location_fixture_bytes
        )
        if active_request_bytes is None and ACTIVE_REQUEST_PATH.exists():
            active_request_bytes = ACTIVE_REQUEST_PATH.read_bytes()
    except OSError as exc:
        return [f"cannot load V8 dependency-cache plan: {exc}"]

    fixed_paths = (
        (workflow_bytes, WORKFLOW_SHA256, "V8 workflow"),
        (template_bytes, TEMPLATE_SHA256, "V8 template"),
        (
            transient_verifier_bytes,
            TRANSIENT_VERIFIER_SHA256,
            "V8 transient verifier",
        ),
        (cleanup_helper_bytes, CLEANUP_HELPER_SHA256, "V8 cleanup helper"),
        (
            provenance_fixture_bytes,
            PROVENANCE_FIXTURE_SHA256,
            "V8 provenance source fixture",
        ),
        (
            rawjson_fixture_bytes,
            RAWJSON_FIXTURE_SHA256,
            "V8 rawjson source fixture",
        ),
        (
            structural_fixture_bytes,
            STRUCTURAL_FIXTURE_SHA256,
            "V8 structural source fixture",
        ),
        (
            incremental_fixture_bytes,
            INCREMENTAL_FIXTURE_SHA256,
            "frozen V7 incremental source fixture",
        ),
        (
            empty_location_fixture_bytes,
            EMPTY_LOCATION_FIXTURE_SHA256,
            "V8 empty-location source fixture",
        ),
        (
            V7_WORKFLOW_PATH.read_bytes(),
            V7_WORKFLOW_SHA256,
            "frozen V7 workflow",
        ),
        (
            V7_TEMPLATE_PATH.read_bytes(),
            V7_TEMPLATE_SHA256,
            "frozen V7 template",
        ),
        (
            V7_REQUEST_PATH.read_bytes(),
            V7_REQUEST_SHA256,
            "frozen V7 request",
        ),
        (
            V7_PLAN_VERIFIER_PATH.read_bytes(),
            V7_PLAN_VERIFIER_SHA256,
            "frozen V7 plan verifier",
        ),
        (
            V4_TRANSIENT_VERIFIER_PATH.read_bytes(),
            V4_TRANSIENT_VERIFIER_SHA256,
            "frozen V4 transient base verifier",
        ),
        (
            V7_FAILURE_EVIDENCE_PATH.read_bytes(),
            V7_FAILURE_EVIDENCE_SHA256,
            "V7 terminal evidence",
        ),
        (
            V7_FAILURE_VERIFIER_PATH.read_bytes(),
            V7_FAILURE_VERIFIER_SHA256,
            "V7 terminal evidence verifier",
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
            V6_BUNDLE_VERIFIER_PATH.read_bytes(),
            V6_BUNDLE_VERIFIER_SHA256,
            "frozen V6 bundle verifier",
        ),
        (
            V7_BUNDLE_VERIFIER_PATH.read_bytes(),
            V7_BUNDLE_VERIFIER_SHA256,
            "frozen V7 bundle verifier",
        ),
        (
            BUNDLE_VERIFIER_PATH.read_bytes(),
            BUNDLE_VERIFIER_SHA256,
            "V8 bundle verifier",
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
        template = v7_plan.v6_plan.v5_plan.v4_plan.strict_json(template_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V8 request template: {exc}")
        template = {}
    require(template == EXPECTED_TEMPLATE, "V8 request template drift")
    require(
        template_bytes.count(b"__DIRECT_PARENT_COMMIT__") == 1,
        "V8 request parent placeholder count changed",
    )
    predecessor = template.get("predecessor", {})
    recovery_basis = template.get("recovery_basis", {})
    verifier_chain = template.get("bundle_verifier_chain", {})
    evidence_recovery = template.get("build_evidence_recovery", {})
    provider_protocol = template.get("provider_artifact_protocol", {})
    require(
        template.get("schema_version") == 8
        and template.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and template.get("release_commit") == RELEASE_COMMIT
        and template.get("plan_checkpoint_commit")
        == "__DIRECT_PARENT_COMMIT__"
        and template.get("release_scope")
        == "admin_dependency_prefix_cache_recovery"
        and template.get("trigger_mode") == "one_shot_added_request_v8",
        "V8 request identity changed",
    )
    require(
        predecessor
        == {
            "control_commit": V7_CONTROL_COMMIT,
            "direct_parent_commit": V7_PLAN_PARENT,
            "terminal_checkpoint_commit": V7_TERMINAL_CHECKPOINT,
            "terminal_receipt_commit": V7_TERMINAL_RECEIPT,
            "workflow_id": 324378036,
            "run_id": 30622876575,
            "job_id": 91131267190,
            "run_attempt": 1,
            "conclusion": "failure",
            "artifact_count": 0,
            "rerun_count": 0,
            "rerun_authorized": False,
            "request_sha256": V7_REQUEST_SHA256,
            "failure_evidence_sha256": V7_FAILURE_EVIDENCE_SHA256,
            "failure_evidence_semantic_sha256": (
                V7_FAILURE_EVIDENCE_SEMANTIC_SHA256
            ),
            "failure_verifier_sha256": V7_FAILURE_VERIFIER_SHA256,
        },
        "V8 predecessor terminal semantics changed",
    )
    require(
        recovery_basis.get("empty_source_location_projection_sha256")
        == EMPTY_LOCATION_FIXTURE_SHA256
        and recovery_basis.get(
            "exact_empty_source_location_allowed_as_nonbinding"
        )
        is True
        and recovery_basis.get(
            "empty_source_location_cannot_satisfy_dependency_role"
        )
        is True
        and recovery_basis.get(
            "populated_source_location_delegated_to_frozen_v7"
        )
        is True
        and recovery_basis.get("v7_runtime_step9_payload_reconstructed")
        is False
        and recovery_basis.get("github_actions_provenance_injection_authorized")
        is False
        and recovery_basis.get("buildkit_auth_behavior")
        == "ordinary_credentials_only",
        "V8 exact-empty recovery basis changed",
    )
    require(
        verifier_chain
        == {
            "v2_sha256": BASE_BUNDLE_VERIFIER_SHA256,
            "v3_sha256": V3_BUNDLE_VERIFIER_SHA256,
            "v6_sha256": V6_BUNDLE_VERIFIER_SHA256,
            "v7_sha256": V7_BUNDLE_VERIFIER_SHA256,
            "v8_sha256": BUNDLE_VERIFIER_SHA256,
        },
        "V8 bundle verifier chain changed",
    )
    require(
        evidence_recovery.get("v7_dynamic_metadata_retained") is False
        and evidence_recovery.get("v7_dynamic_progress_retained") is False
        and evidence_recovery.get(
            "source_projection_only_not_v7_runtime_evidence"
        )
        is True
        and evidence_recovery.get("v7_step9_payload_reconstructed") is False
        and evidence_recovery.get(
            "exact_empty_wrapper_allowed_as_nonbinding"
        )
        is True
        and evidence_recovery.get(
            "empty_wrapper_cannot_satisfy_dependency_role"
        )
        is True
        and evidence_recovery.get("null_empty_array_unknown_keys_rejected")
        is True
        and evidence_recovery.get("source_index_contract_broadened") is False
        and evidence_recovery.get("frozen_v7_delegate_required") is True,
        "V8 build-evidence recovery contract changed",
    )
    require(
        provider_protocol
        == {
            "artifact_name": "admin-dependency-prefix-cache-5335bda-v2",
            "legacy_name_required_by_frozen_download_chain": True,
            "identity_bound_by_artifact_id_run_control_request_and_digest": True,
        },
        "V8 provider artifact protocol changed",
    )
    require(
        template.get("recovery_run_authorized_after_predecessor_failure")
        is True
        and template.get("github_actions_maximum_run_count") == 1
        and template.get("github_actions_maximum_runtime_minutes") == 120
        and template.get("artifact_retention_days") == 1
        and template.get("artifact_compressed_maximum_bytes") == 3758096384
        and template.get("artifact_input_maximum_bytes") == 4026531840
        and template.get("artifact_provider_maximum_bytes") == 4294967296
        and template.get("authenticated_artifact_download_maximum_count")
        == 1
        and template.get("cross_provider_transfer_maximum_count") == 1
        and template.get("dependency_cache_export_authorized") is True
        and template.get("public_repository_artifact_authorized") is True
        and template.get("cross_provider_transfer_authorized") is True
        and template.get("registry_publication_authorized") is False
        and template.get("deployment_authorized") is False
        and template.get("database_authorized") is False
        and template.get("service_mutation_authorized") is False
        and template.get("public_traffic_authorized") is False,
        "V8 bounded authorization contract changed",
    )
    try:
        fixture = v7_plan.v6_plan.v5_plan.v4_plan.strict_json(
            provenance_fixture_bytes
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V8 provenance fixture: {exc}")
        fixture = {}
    require(
        fixture.get("classification")
        == "SOURCE_PROVEN_CONFIGURATION_CONTRACT_NOT_V5_RUNTIME_EVIDENCE",
        "V8 provenance fixture classification changed",
    )
    require(
        fixture.get("actual_v5_runtime_metadata_retained") is False,
        "V8 provenance fixture overclaims runtime evidence",
    )
    require(
        fixture.get("v5_expected_configuration", {}).get(
            "pre_build_direct_json_file_count"
        )
        == 0,
        "V8 provenance pre-build projection changed",
    )
    try:
        rawjson_fixture = v7_plan.v6_plan.v5_plan.v4_plan.strict_json(
            rawjson_fixture_bytes
        )
        structural_fixture = v7_plan.v6_plan.v5_plan.v4_plan.strict_json(
            structural_fixture_bytes
        )
        incremental_fixture = v7_plan.v6_plan.v5_plan.v4_plan.strict_json(
            incremental_fixture_bytes
        )
        empty_location_fixture = (
            v7_plan.v6_plan.v5_plan.v4_plan.strict_json(
                empty_location_fixture_bytes
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V8 source fixture: {exc}")
        rawjson_fixture = {}
        structural_fixture = {}
        incremental_fixture = {}
        empty_location_fixture = {}
    require(
        rawjson_fixture.get("classification")
        == "SOURCE_PROVEN_RAWJSON_SCHEMA_NOT_V5_RUNTIME_EVIDENCE"
        and rawjson_fixture.get("actual_v5_runtime_progress_retained")
        is False
        and rawjson_fixture.get("frozen_v5_verifier_projection", {}).get(
            "iterates_nested_vertexes"
        )
        is False,
        "V8 rawjson source projection changed",
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
        "V8 structural source projection changed",
    )
    incremental_contract = incremental_fixture.get("v7_contract", {})
    require(
        incremental_fixture.get("classification")
        == "SOURCE_PROVEN_INCREMENTAL_VERTEX_CONTRACT_NOT_V6_RUNTIME_EVIDENCE"
        and incremental_fixture.get("actual_v6_runtime_metadata_retained")
        is False
        and incremental_fixture.get("actual_v6_runtime_progress_retained")
        is False
        and incremental_fixture.get(
            "runtime_conflicting_digest_reconstructed"
        )
        is False
        and incremental_fixture.get(
            "runtime_conflicting_field_reconstructed"
        )
        is False
        and incremental_fixture.get("buildkit", {}).get("commit")
        == "e42e1bfd389af7203238cce77b1f7dad447285e9"
        and incremental_fixture.get("buildx", {}).get("commit")
        == "a319e5b15052cf6557ceb666eb8ff6e32380b782"
        and incremental_contract.get(
            "each_vertex_update_is_full_value_copy"
        )
        is True
        and incremental_contract.get(
            "inputs_exact_across_same_digest_updates"
        )
        is True
        and incremental_contract.get(
            "progress_group_exact_across_same_digest_updates"
        )
        is True
        and incremental_contract.get(
            "same_digest_multiple_lifecycle_intervals_valid"
        )
        is True
        and incremental_contract.get(
            "latest_started_interval_controls_cached_result"
        )
        is True
        and incremental_contract.get(
            "all_structurally_bound_role_intervals_must_complete_inside_build_window"
        )
        is True,
        "V8 incremental source projection changed",
    )
    empty_contract = empty_location_fixture.get("v8_contract", {})
    require(
        empty_location_fixture.get("classification")
        == (
            "SOURCE_PROVEN_EMPTY_SOURCE_LOCATION_CONTRACT_"
            "NOT_V7_RUNTIME_EVIDENCE"
        )
        and empty_location_fixture.get(
            "actual_v7_runtime_metadata_retained"
        )
        is False
        and empty_location_fixture.get(
            "actual_v7_step9_payload_retained"
        )
        is False
        and empty_location_fixture.get(
            "runtime_step9_shape_reconstructed"
        )
        is False
        and empty_location_fixture.get("buildkit", {}).get("commit")
        == "e42e1bfd389af7203238cce77b1f7dad447285e9"
        and empty_contract.get(
            "exact_empty_wrapper_allowed_as_nonbinding"
        )
        is True
        and empty_contract.get(
            "empty_wrapper_cannot_satisfy_dependency_role"
        )
        is True
        and empty_contract.get(
            "populated_location_delegated_to_frozen_v7"
        )
        is True
        and empty_contract.get("null_empty_array_unknown_keys_rejected")
        is True
        and empty_contract.get("source_index_contract_not_broadened")
        is True
        and empty_contract.get("v7_runtime_payload_claimed") is False,
        "V8 empty-location source projection changed",
    )

    errors.extend(f"frozen V7 plan: {item}" for item in v7_plan.validate_plan())
    try:
        evidence_payload = v7_failure.load_strict()
        errors.extend(
            f"V7 terminal evidence: {item}"
            for item in v7_failure.verify(evidence_payload)
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot verify V7 terminal evidence: {exc}")
    if verify_git_state:
        try:
            require(
                v7_plan._request_additions() == [V7_CONTROL_COMMIT],
                "V7 request addition history changed",
            )
            require(
                _git("rev-list", "--parents", "-n", "1", V7_CONTROL_COMMIT)
                == f"{V7_CONTROL_COMMIT} {V7_PLAN_PARENT}",
                "V7 control parent changed",
            )
            require(
                _git(
                    "rev-list",
                    "--parents",
                    "-n",
                    "1",
                    V7_TERMINAL_CHECKPOINT,
                )
                == f"{V7_TERMINAL_CHECKPOINT} {V7_CONTROL_COMMIT}",
                "V7 terminal checkpoint parent changed",
            )
            require(
                _git(
                    "rev-list",
                    "--parents",
                    "-n",
                    "1",
                    V7_TERMINAL_RECEIPT,
                )
                == f"{V7_TERMINAL_RECEIPT} {V7_TERMINAL_CHECKPOINT}",
                "V7 terminal receipt parent changed",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify V7 terminal history: {exc}")

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
                errors.append("inactive V8 request has prior addition history")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify inactive V8 request history: {exc}")

    workflow = workflow_bytes.decode("utf-8", errors="replace")
    transient = transient_verifier_bytes.decode("utf-8", errors="replace")
    cleanup = cleanup_helper_bytes.decode("utf-8", errors="replace")
    export_helper = EXPORT_HELPER_PATH.read_text(encoding="utf-8")
    import_helper = IMPORT_HELPER_PATH.read_text(encoding="utf-8")
    download_helper = DOWNLOAD_HELPER_PATH.read_text(encoding="utf-8")
    provider_verifier = PROVIDER_VERIFIER_PATH.read_text(encoding="utf-8")
    v3_bundle_verifier = V3_BUNDLE_VERIFIER_PATH.read_text(
        encoding="utf-8"
    )
    v6_bundle_verifier = V6_BUNDLE_VERIFIER_PATH.read_text(
        encoding="utf-8"
    )
    v7_bundle_verifier = V7_BUNDLE_VERIFIER_PATH.read_text(
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
        require(forbidden not in workflow, f"V8 workflow forbidden token: {forbidden}")
    require(
        workflow.split("\npermissions:", 1)[0] == EXPECTED_WORKFLOW_HEADER,
        "V8 trigger block changed",
    )
    require(
        "permissions:\n  contents: read" in workflow,
        "V8 workflow permissions changed",
    )
    require(
        workflow.count(
            "DOCKER_CONFIG: ${{ runner.temp }}/noteai-empty-docker-config-v5"
        )
        == 4,
        "V8 Docker config step count changed",
    )
    require(
        workflow.count(
            "BUILDX_CONFIG: ${{ runner.temp }}/noteai-buildx-state-v5"
        )
        == 4,
        "V8 Buildx config step count changed",
    )
    require(
        workflow.count('BUILDKIT_NO_CLIENT_TOKEN: "1"') == 1,
        "V8 client-token control changed",
    )
    require(
        workflow.count("BUILDX_METADATA_PROVENANCE: max") == 1,
        "V8 max provenance setting changed",
    )
    require(
        "admin-5335bda-dependency-cache-v8.json" in workflow,
        "V8 trigger path changed",
    )
    require(
        ".github/workflows/admin-dependency-cache-export-v8.yml"
        not in workflow.split("permissions:", 1)[0],
        "V8 workflow triggers on installation",
    )
    require("timeout-minutes: 120" in workflow, "V8 runtime cap changed")
    for required, message in (
        (
            'NOTEAI_PRE_CLEANUP_BUDGET_SECONDS: "5700"',
            "V8 pre-cleanup budget changed",
        ),
        (
            'NOTEAI_CLEANUP_BUDGET_SECONDS: "6300"',
            "V8 cleanup budget changed",
        ),
        (
            'NOTEAI_SETUP_CALL_MAX_SECONDS: "300"',
            "V8 setup call timeout changed",
        ),
        (
            'NOTEAI_EXPORT_CALL_MAX_SECONDS: "3600"',
            "V8 export call timeout changed",
        ),
        (
            'NOTEAI_IMPORT_CALL_MAX_SECONDS: "900"',
            "V8 import call timeout changed",
        ),
        (
            'NOTEAI_CLEANUP_COMMAND_TIMEOUT_SECONDS: "15"',
            "V8 cleanup call timeout changed",
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
        "V8 cleanup headroom control changed",
    )
    deadline_initializer = workflow.find(
        "    steps:\n"
        "      - name: Initialize V8 bounded job deadlines"
    )
    first_checkout = workflow.find(
        "      - name: Checkout V8 one-shot controller"
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
        "V8 deadline is not initialized before checkout",
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
        "V8 helper timeout envelope changed",
    )
    require("retention-days: 1" in workflow, "V8 retention changed")
    require("compression-level: 0" in workflow, "V8 compression changed")
    require(
        workflow.count('test "${GITHUB_RUN_ATTEMPT}" = "1"') == 2,
        "V8 rerun guards changed",
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
        "V8 isolated builder options changed",
    )
    require(
        workflow.count('--driver-opt "provenance-add-gha=false"') == 2,
        "V8 provenance driver option changed",
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
        "V8 exact BuildKit daemon flags changed",
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
        "V8 Buildx/BuildKit identity changed",
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
        "V8 action pins changed",
    )
    for required in (
        'test "${#changed_files[@]}" -eq 1',
        'test "${changed_files[0]}" = "${NOTEAI_REQUEST_PATH}"',
        "--no-renames --diff-filter=A",
        'test "${#request_add_commits[@]}" -eq 1',
        'test "${request_add_commits[0]}" = "${GITHUB_SHA}"',
        "git log --all --diff-filter=A",
        "NOTEAI_V7_CONTROL_COMMIT",
        "NOTEAI_V7_REQUEST_SHA256",
        "NOTEAI_V7_WORKFLOW_SHA256",
        "NOTEAI_V7_PLAN_VERIFIER_SHA256",
        "NOTEAI_V7_PLAN_PARENT",
        "NOTEAI_V7_TERMINAL_CHECKPOINT",
        "NOTEAI_V7_TERMINAL_RECEIPT",
        "NOTEAI_V4_TRANSIENT_VERIFIER_SHA256",
        "NOTEAI_FAILURE_EVIDENCE_SHA256",
        "NOTEAI_FAILURE_EVIDENCE_SEMANTIC_SHA256",
        "NOTEAI_FAILURE_EVIDENCE_VERIFIER_SHA256",
        "NOTEAI_V5_RAWJSON_SOURCE_PROJECTION_SHA256",
        "NOTEAI_V6_STRUCTURAL_SOURCE_PROJECTION_SHA256",
        "NOTEAI_V7_INCREMENTAL_SOURCE_PROJECTION_SHA256",
        "NOTEAI_V8_EMPTY_SOURCE_PROJECTION_SHA256",
        'python3 "${NOTEAI_V7_PLAN_VERIFIER_PATH}"',
        'python3 "${NOTEAI_FAILURE_EVIDENCE_VERIFIER_PATH}"',
        "__DIRECT_PARENT_COMMIT__",
        'cmp "${request_file}" "${expected_request}"',
        "recovery_run_authorized_after_predecessor_failure == true",
        ".predecessor.rerun_authorized == false",
        ".predecessor.artifact_count == 0",
        ".recovery_basis.exact_empty_source_location_allowed_as_nonbinding ==",
        ".recovery_basis.empty_source_location_cannot_satisfy_dependency_role ==",
        ".recovery_basis.populated_source_location_delegated_to_frozen_v7 ==",
        ".recovery_basis.v7_runtime_step9_payload_reconstructed == false",
        "registry_publication_authorized == false",
        "git merge-base --is-ancestor",
        "persist-credentials: false",
        "NOTEAI_BASE_BUNDLE_VERIFIER_PATH",
        "NOTEAI_V3_BUNDLE_VERIFIER_PATH",
        "NOTEAI_V6_BUNDLE_VERIFIER_PATH",
        "NOTEAI_V7_BUNDLE_VERIFIER_PATH",
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
        require(required in workflow, f"V8 workflow contract missing: {required}")

    require(
        "name: Admin dependency cache export V8" in workflow
        and (
            "group: admin-dependency-cache-export-v8-${{ github.sha }}"
            in workflow
        )
        and (
            'NOTEAI_ARTIFACT_NAME: '
            '"admin-dependency-prefix-cache-5335bda-v2"'
            in workflow
        )
        and workflow.count(
            "noteai-admin-dependency-cache-bundle-v8"
        )
        >= 6
        and "unused-v8-import-evidence" in workflow
        and "noteai-final-cache-v8-validation" in workflow
        and "noteai-final-bundle-v8-validation.json" in workflow,
        "V8 outer workflow identity changed",
    )
    require(
        "noteai-admin-dependency-cache-bundle-v5" not in workflow
        and "unused-v5-import-evidence" not in workflow
        and "noteai-final-cache-v5-validation" not in workflow
        and "noteai-final-bundle-v5-validation.json" not in workflow
        and "admin_dependency_cache_v5_artifact" not in workflow,
        "V8 outer workflow retains V5 identity",
    )
    require(
        "noteai-empty-docker-config-v8" not in workflow
        and "noteai-buildx-state-v8" not in workflow
        and "noteai-admin-cache-v8-producer" not in workflow
        and "noteai-admin-cache-v8-consumer" not in workflow
        and "noteai-docker-baseline-v8" not in workflow
        and "dependency-cache-cleanup-v8.json" not in workflow
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
        "V8 frozen V5 runtime namespace changed",
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
            "NOTEAI_V6_BUNDLE_VERIFIER_PATH: "
            "tools/verify_admin_dependency_cache_bundle_v6.py"
            in workflow
        )
        and (
            "NOTEAI_V6_BUNDLE_VERIFIER_SHA256: "
            f"{V6_BUNDLE_VERIFIER_SHA256}"
            in workflow
        )
        and (
            "NOTEAI_V7_BUNDLE_VERIFIER_PATH: "
            "tools/verify_admin_dependency_cache_bundle_v7.py"
            in workflow
        )
        and (
            "NOTEAI_V7_BUNDLE_VERIFIER_SHA256: "
            f"{V7_BUNDLE_VERIFIER_SHA256}"
            in workflow
        )
        and (
            "NOTEAI_BUNDLE_VERIFIER_PATH: "
            "tools/verify_admin_dependency_cache_bundle_v8.py"
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
            "NOTEAI_V6_BUNDLE_VERIFIER_PATH: "
            "${{ steps.control.outputs.v6_verifier_copy }}"
        )
        == 3
        and workflow.count(
            "NOTEAI_V7_BUNDLE_VERIFIER_PATH: "
            "${{ steps.control.outputs.v7_verifier_copy }}"
        )
        == 3
        and workflow.count(
            'v3_verifier_copy="${RUNNER_TEMP}/'
            'noteai-cache-v8-bundle-v3.py"'
        )
        == 1
        and 'cp "${NOTEAI_V3_BUNDLE_VERIFIER_PATH}" '
        '"${v3_verifier_copy}"' in workflow
        and 'cp "${NOTEAI_V6_BUNDLE_VERIFIER_PATH}" '
        '"${v6_verifier_copy}"' in workflow
        and 'cp "${NOTEAI_V7_BUNDLE_VERIFIER_PATH}" '
        '"${v7_verifier_copy}"' in workflow
        and 'cp "${NOTEAI_BASE_BUNDLE_VERIFIER_PATH}" '
        '"${base_verifier_copy}"' in workflow
        and 'cp "${NOTEAI_BUNDLE_VERIFIER_PATH}" '
        '"${bundle_verifier_copy}"' in workflow
        and 'printf \'v3_verifier_copy=%s\\n\' '
        '"${v3_verifier_copy}"' in workflow
        and 'printf \'v6_verifier_copy=%s\\n\' '
        '"${v6_verifier_copy}"' in workflow
        and 'printf \'v7_verifier_copy=%s\\n\' '
        '"${v7_verifier_copy}"' in workflow
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
        "V8 five-layer bundle trust matrix changed",
    )
    require(
        "github_actions_maximum_run_count == 1" in workflow
        and "artifact_compressed_maximum_bytes == 3758096384"
        in workflow
        and "authenticated_artifact_download_maximum_count == 1"
        in workflow
        and "cross_provider_transfer_maximum_count == 1" in workflow
        and ".archive.maximum_gzip_bytes == 3758096384" in workflow,
        "V8 authorized artifact bounds changed",
    )
    require(
        workflow.count(
            'NOTEAI_ARTIFACT_NAME: "'
            'admin-dependency-prefix-cache-5335bda-v2"'
        )
        == 1
        and download_helper.count(
            'artifact_name="admin-dependency-prefix-cache-5335bda-v2"'
        )
        == 1
        and provider_verifier.count(
            'ARTIFACT_NAME = "admin-dependency-prefix-cache-5335bda-v2"'
        )
        == 1,
        "V8 frozen provider artifact identity changed",
    )
    require(
        f"NOTEAI_V7_PLAN_PARENT: {V7_PLAN_PARENT}" in workflow
        and f"NOTEAI_V7_CONTROL_COMMIT: {V7_CONTROL_COMMIT}"
        in workflow
        and f"NOTEAI_V7_TERMINAL_CHECKPOINT: {V7_TERMINAL_CHECKPOINT}"
        in workflow
        and f"NOTEAI_V7_TERMINAL_RECEIPT: {V7_TERMINAL_RECEIPT}"
        in workflow
        and f"NOTEAI_V7_REQUEST_SHA256: {V7_REQUEST_SHA256}"
        in workflow
        and f"NOTEAI_V7_WORKFLOW_SHA256: {V7_WORKFLOW_SHA256}"
        in workflow
        and f"NOTEAI_V7_TEMPLATE_SHA256: {V7_TEMPLATE_SHA256}"
        in workflow
        and (
            f"NOTEAI_V7_PLAN_VERIFIER_SHA256: "
            f"{V7_PLAN_VERIFIER_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_FAILURE_EVIDENCE_SHA256: "
            f"{V7_FAILURE_EVIDENCE_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_FAILURE_EVIDENCE_SEMANTIC_SHA256: "
            f"{V7_FAILURE_EVIDENCE_SEMANTIC_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_FAILURE_EVIDENCE_VERIFIER_SHA256: "
            f"{V7_FAILURE_VERIFIER_SHA256}"
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
        and (
            f"NOTEAI_V7_INCREMENTAL_SOURCE_PROJECTION_SHA256: "
            f"{INCREMENTAL_FIXTURE_SHA256}"
            in workflow
        )
        and (
            f"NOTEAI_V8_EMPTY_SOURCE_PROJECTION_SHA256: "
            f"{EMPTY_LOCATION_FIXTURE_SHA256}"
            in workflow
        )
        and ".predecessor.workflow_id == 324378036" in workflow
        and ".predecessor.run_id == 30622876575" in workflow
        and ".predecessor.job_id == 91131267190" in workflow
        and ".predecessor.artifact_count == 0" in workflow
        and ".predecessor.rerun_count == 0" in workflow
        and ".predecessor.rerun_authorized == false" in workflow,
        "V8 predecessor terminal chain changed",
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
        "V8 Docker baseline atomic sequence changed",
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
        "V8 baseline/provenance gate ordering changed",
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
        require(required in workflow, f"V8 provenance gate missing: {required}")
    require(
        workflow.count("docker exec \"${container_name}\" sh -eu -c") == 1
        and (
            'for builder_name in \\\n'
            '            "${NOTEAI_PRODUCER_BUILDER}" \\\n'
            '            "${NOTEAI_CONSUMER_BUILDER}"'
        )
        in workflow,
        "V8 provenance gate builder coverage changed",
    )

    require(
        export_helper.count("--platform linux/amd64") == 1
        and import_helper.count("--platform linux/amd64") == 2,
        "V8 target platform contract changed",
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
        require(required in export_helper, f"V8 artifact limit missing: {required}")
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
            required in v6_bundle_verifier,
            f"frozen V6 bundle verifier contract missing: {required}",
        )
    for required in (
        "V6_VERIFIER_SHA256",
        'os.environ.get("NOTEAI_V6_BUNDLE_VERIFIER_PATH")',
        "_exact_optional_time",
        "_patched_v6_incremental_contract",
        "_FROZEN_PROVENANCE_BUILD_WINDOW",
        "NETWORK_VERTEX_INTERVAL_PROJECTION_INVALID",
    ):
        require(
            required in v7_bundle_verifier,
            f"frozen V7 bundle verifier contract missing: {required}",
        )
    for required in (
        "V7_VERIFIER_SHA256",
        'os.environ.get("NOTEAI_V7_BUNDLE_VERIFIER_PATH")',
        "_FROZEN_V6_RANGE_PROJECTION",
        "if location == {}:",
        '"lines": set(), "starts": set()',
        "_patched_v7_empty_location_contract",
        "_v6._PATCH_LOCK",
        '(_v6, "_range_projection", _range_projection)',
        '(_v7, "_initial_diagnostic", _initial_diagnostic)',
        '(_v7, "_emit_diagnostic", _emit_diagnostic)',
        '(_v7, "_validate_build_evidence", _validate_build_evidence)',
        "FROZEN_V7_DISPATCH_CHANGED",
        "FROZEN_V7_DISPATCH_RESTORE_FAILED",
        "noteai.admin-dependency-cache-v8-diagnostic.v1",
        "noteai_v8_progress_diagnostic=",
        "v7_rawjson_diagnostic",
        "v8_rawjson_diagnostic",
    ):
        require(
            required in bundle_verifier,
            f"V8 bundle verifier contract missing: {required}",
        )
    require(
        'os.environ.get("NOTEAI_BASE_BUNDLE_VERIFIER_PATH")'
        in v3_bundle_verifier
        and "BASE_VERIFIER_SHA256" in v3_bundle_verifier
        and "V3_VERIFIER_SHA256" in v6_bundle_verifier
        and "V2_VERIFIER_SHA256" in v6_bundle_verifier
        and "V6_VERIFIER_SHA256" in v7_bundle_verifier
        and "V7_VERIFIER_SHA256" in bundle_verifier,
        "V8 frozen bundle verifier chain changed",
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
        require(required in transient, f"V8 transient contract missing: {required}")
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
        require(required in cleanup, f"V8 cleanup contract missing: {required}")
    cleanup_position = workflow.find(
        "Remove V8 builders and all transient Docker state"
    )
    upload_position = workflow.find(
        "Upload one-day V8 public-repository dependency cache artifact"
    )
    local_removal_position = workflow.find("Remove runner-local V8 bundle")
    require(
        0
        <= cleanup_position
        < upload_position
        < local_removal_position,
        "V8 cleanup/upload ordering changed",
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
            "V8_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V8_CONSUMED_OR_INVALID"
    return "PREPARED_V8_NOT_TRIGGERED"


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
            active_git_errors = [f"cannot load V8 active request: {exc}"]
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
    print(f"admin_dependency_cache_export_plan_v8=PASS state={plan_state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
