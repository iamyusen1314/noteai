#!/usr/bin/env python3
"""Verify the inert, append-only V9 Admin dependency-cache recovery plan."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import verify_admin_dependency_cache_export_plan_v8 as v8_plan
import verify_admin_dependency_cache_v8_failure_evidence as v8_failure


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v9.yml"
)
TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v9.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v9.json"
)
SOURCE_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "vertex_input_omission_projection.json"
)
BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v9.py"
)
V8_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v8.yml"
)
V8_TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v8.json"
)
V8_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v8.json"
)
V8_PLAN_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_export_plan_v8.py"
)
V8_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v8.py"
)
V8_FAILURE_EVIDENCE_PATH = v8_failure.EVIDENCE_PATH
V8_FAILURE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_v8_failure_evidence.py"
)

WORKFLOW_SHA256 = (
    "ece8eb8e9c9d8a8997faa838c87a3a06a407bc3382670bf8f294433982e62f34"
)
TEMPLATE_SHA256 = (
    "ae5114d66eb2aedd4db875b857974b0631caa1a39ad75a16e22ccbaecc424a3b"
)
SOURCE_FIXTURE_SHA256 = (
    "3738f1b5bea4490c063cee7749fe39134b0f63005201496ac74aa1d125efb9fd"
)
BUNDLE_VERIFIER_SHA256 = (
    "a69103e899dc74b4d34e4837e29f40284be9b252281fed262a2dd1afee3d6032"
)
V8_WORKFLOW_SHA256 = (
    "370e17b59ce457efda8b5a6cd23d40937379d23d1a2aeb3f36ac7b88f72333b3"
)
V8_TEMPLATE_SHA256 = (
    "ba2f705eff90285e377e8d683a059f7f23aef088dc7df2498d167909fff48e7c"
)
V8_REQUEST_SHA256 = (
    "5283d1044e3fb783e4951019f2c137a23530fb6c09fc290718c305ee3e449cd5"
)
V8_PLAN_VERIFIER_SHA256 = (
    "69fde0852832a2b6cdfc4e3542b835a74c3c939377220deb3009430292ef5915"
)
V8_BUNDLE_VERIFIER_SHA256 = (
    "b07f9dee54862969fe90ef438c357a3445a9fe9574b69a9f87440e3ed9920300"
)
V8_FAILURE_EVIDENCE_SHA256 = (
    "e4b69bab7c607ec71f44ec390be9acb693de53d05c33a62cb21b6691255e206b"
)
V8_FAILURE_EVIDENCE_SEMANTIC_SHA256 = (
    "78bdb3bc843cec7c9eb192dde896cf79296edab2d46561a17ac4065324489645"
)
V8_FAILURE_VERIFIER_SHA256 = (
    "4ddeca8a7b60e0c8c60b7c60eeb8cec2a56366cfab8b39e9c71e3b37535c7027"
)
V8_PLAN_PARENT = "cf253f9b42b096f45405ac55fe546c281a2a748d"
V8_CONTROL_COMMIT = "354bec3b2d36bfaabc5c3307d49f5dc66255cbbf"
V8_TERMINAL_CHECKPOINT = "6961876b35aba5e52fc7e44a59a4881469d0064f"
V8_TERMINAL_RECEIPT = "72f36354471e2d56ea77760d50417bf09b5cd9e1"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_WORKFLOW_HEADER = """name: Admin dependency cache export V9

on:
  push:
    branches:
      - codex/quality-stabilization-real-chain
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v9.json
"""
EXPECTED_TEMPLATE: dict[str, Any] = json.loads(
    TEMPLATE_PATH.read_text(encoding="utf-8")
)
FROZEN_ACTIVATION_FILES = (
    (WORKFLOW_PATH.relative_to(ROOT), WORKFLOW_SHA256),
    (TEMPLATE_PATH.relative_to(ROOT), TEMPLATE_SHA256),
    (SOURCE_FIXTURE_PATH.relative_to(ROOT), SOURCE_FIXTURE_SHA256),
    (BUNDLE_VERIFIER_PATH.relative_to(ROOT), BUNDLE_VERIFIER_SHA256),
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


def _strict_json(value: bytes) -> Any:
    return v8_plan.v7_plan.v6_plan.v5_plan.v4_plan.strict_json(value)


def _request_additions(
    *,
    root: Path = ROOT,
    request_path: Path | None = None,
) -> list[str]:
    relative = (
        ACTIVE_REQUEST_PATH.relative_to(ROOT)
        if request_path is None
        else request_path
    )
    output = _git_at(
        root,
        "log",
        "--all",
        "--diff-filter=A",
        "--format=%H",
        "--",
        str(relative),
    )
    return [line for line in output.splitlines() if line]


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
        request = _strict_json(request_bytes)
        template = _strict_json(template_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid V9 active request: {exc}"]
    parent = request.get("plan_checkpoint_commit")
    if not isinstance(parent, str) or COMMIT_RE.fullmatch(parent) is None:
        return ["V9 active request checkpoint is invalid"]
    if plan_parent is not None and parent != plan_parent:
        errors.append("V9 active request does not bind its direct parent")
    expected_bytes = template_bytes.replace(
        b"__DIRECT_PARENT_COMMIT__",
        parent.encode("ascii"),
    )
    if request_bytes != expected_bytes:
        errors.append("V9 active request differs from reviewed template")
    expected = dict(template)
    expected["plan_checkpoint_commit"] = parent
    if request != expected:
        errors.append("V9 active request semantics drift")

    if not verify_git_state:
        return errors

    relative = (
        ACTIVE_REQUEST_PATH.relative_to(ROOT)
        if request_path is None
        else request_path
    )
    try:
        additions = _request_additions(root=root, request_path=relative)
        if len(additions) != 1:
            return errors + ["V9 active request addition history is not unique"]
        activation = additions[0]
        parent_record = _git_at(
            root,
            "rev-list",
            "--parents",
            "-n",
            "1",
            activation,
        ).split()
        if len(parent_record) != 2:
            return errors + ["V9 controller is not single-parent"]
        activation_parent = parent_record[1]
        if activation_parent != parent:
            errors.append("V9 request checkpoint differs from controller parent")
        changed = _git_at(
            root,
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            activation_parent,
            activation,
        ).splitlines()
        if changed != [str(relative)]:
            errors.append("V9 activation changes more than its request")
        addition = _git_at(
            root,
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--diff-filter=A",
            "--name-status",
            "-r",
            activation_parent,
            activation,
            "--",
            str(relative),
        )
        if addition != f"A\t{relative}":
            errors.append("V9 request was not a unique addition")
        activation_entry = _git_at(
            root,
            "ls-tree",
            activation,
            "--",
            str(relative),
        ).split()
        if (
            len(activation_entry) < 3
            or activation_entry[:2] != ["100644", "blob"]
        ):
            errors.append("V9 request activation mode is not 100644")
        activation_bytes = subprocess.run(
            ["git", "show", f"{activation}:{relative}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if activation_bytes != request_bytes:
            errors.append("V9 request activation bytes differ from reviewed request")

        for frozen_relative, expected_sha256 in FROZEN_ACTIVATION_FILES:
            parent_entry = _git_at(
                root,
                "ls-tree",
                activation_parent,
                "--",
                str(frozen_relative),
            ).split()
            frozen_activation_entry = _git_at(
                root,
                "ls-tree",
                activation,
                "--",
                str(frozen_relative),
            ).split()
            if (
                len(parent_entry) < 3
                or parent_entry[:2] != ["100644", "blob"]
                or len(frozen_activation_entry) < 3
                or frozen_activation_entry[:2] != ["100644", "blob"]
            ):
                errors.append(
                    f"V9 activation frozen file mode changed: {frozen_relative}"
                )
                continue
            if parent_entry[2] != frozen_activation_entry[2]:
                errors.append(
                    f"V9 activation frozen file blob changed: {frozen_relative}"
                )
            parent_bytes = subprocess.run(
                ["git", "show", f"{activation_parent}:{frozen_relative}"],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            activation_file_bytes = subprocess.run(
                ["git", "show", f"{activation}:{frozen_relative}"],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            if (
                sha256_bytes(parent_bytes) != expected_sha256
                or sha256_bytes(activation_file_bytes) != expected_sha256
            ):
                errors.append(
                    f"V9 activation frozen file hash drift: {frozen_relative}"
                )

        mode = _git_at(root, "ls-tree", "HEAD", "--", str(relative)).split()
        if len(mode) < 3 or mode[:2] != ["100644", "blob"]:
            errors.append("V9 request is not retained as 100644")
        current = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if current != request_bytes:
            errors.append("V9 request bytes changed after activation")
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V9 active request Git state: {exc}")
    return errors


def validate_plan(
    *,
    workflow_bytes: bytes | None = None,
    template_bytes: bytes | None = None,
    source_fixture_bytes: bytes | None = None,
    bundle_verifier_bytes: bytes | None = None,
    active_request_bytes: bytes | None = None,
    active_plan_parent: str | None = None,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    active_supplied = active_request_bytes is not None
    try:
        workflow_bytes = (
            WORKFLOW_PATH.read_bytes()
            if workflow_bytes is None
            else workflow_bytes
        )
        template_bytes = (
            TEMPLATE_PATH.read_bytes()
            if template_bytes is None
            else template_bytes
        )
        source_fixture_bytes = (
            SOURCE_FIXTURE_PATH.read_bytes()
            if source_fixture_bytes is None
            else source_fixture_bytes
        )
        bundle_verifier_bytes = (
            BUNDLE_VERIFIER_PATH.read_bytes()
            if bundle_verifier_bytes is None
            else bundle_verifier_bytes
        )
        if active_request_bytes is None and ACTIVE_REQUEST_PATH.exists():
            active_request_bytes = ACTIVE_REQUEST_PATH.read_bytes()
    except OSError as exc:
        return [f"cannot load V9 dependency-cache plan: {exc}"]

    fixed_paths = (
        (workflow_bytes, WORKFLOW_SHA256, "V9 workflow"),
        (template_bytes, TEMPLATE_SHA256, "V9 template"),
        (
            source_fixture_bytes,
            SOURCE_FIXTURE_SHA256,
            "V9 input-omission source fixture",
        ),
        (
            bundle_verifier_bytes,
            BUNDLE_VERIFIER_SHA256,
            "V9 bundle verifier",
        ),
        (
            V8_WORKFLOW_PATH.read_bytes(),
            V8_WORKFLOW_SHA256,
            "frozen V8 workflow",
        ),
        (
            V8_TEMPLATE_PATH.read_bytes(),
            V8_TEMPLATE_SHA256,
            "frozen V8 template",
        ),
        (
            V8_REQUEST_PATH.read_bytes(),
            V8_REQUEST_SHA256,
            "frozen V8 request",
        ),
        (
            V8_PLAN_VERIFIER_PATH.read_bytes(),
            V8_PLAN_VERIFIER_SHA256,
            "frozen V8 plan verifier",
        ),
        (
            V8_BUNDLE_VERIFIER_PATH.read_bytes(),
            V8_BUNDLE_VERIFIER_SHA256,
            "frozen V8 bundle verifier",
        ),
        (
            V8_FAILURE_EVIDENCE_PATH.read_bytes(),
            V8_FAILURE_EVIDENCE_SHA256,
            "V8 terminal evidence",
        ),
        (
            V8_FAILURE_VERIFIER_PATH.read_bytes(),
            V8_FAILURE_VERIFIER_SHA256,
            "V8 terminal evidence verifier",
        ),
    )
    for actual, expected, label in fixed_paths:
        require(sha256_bytes(actual) == expected, f"{label} hash drift")

    try:
        template = _strict_json(template_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V9 request template: {exc}")
        template = {}
    require(template == EXPECTED_TEMPLATE, "V9 request template drift")
    require(
        template_bytes.count(b"__DIRECT_PARENT_COMMIT__") == 1,
        "V9 request parent placeholder count changed",
    )
    predecessor = template.get("predecessor", {})
    recovery = template.get("recovery_basis", {})
    verifier_chain = template.get("bundle_verifier_chain", {})
    evidence = template.get("build_evidence_recovery", {})
    require(
        template.get("schema_version") == 9
        and template.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and template.get("release_commit") == RELEASE_COMMIT
        and template.get("plan_checkpoint_commit")
        == "__DIRECT_PARENT_COMMIT__"
        and template.get("release_scope")
        == "admin_dependency_prefix_cache_recovery"
        and template.get("trigger_mode") == "one_shot_added_request_v9",
        "V9 request identity changed",
    )
    require(
        predecessor
        == {
            "control_commit": V8_CONTROL_COMMIT,
            "direct_parent_commit": V8_PLAN_PARENT,
            "terminal_checkpoint_commit": V8_TERMINAL_CHECKPOINT,
            "terminal_receipt_commit": V8_TERMINAL_RECEIPT,
            "workflow_id": 324467538,
            "run_id": 30632611051,
            "job_id": 91162335850,
            "run_attempt": 1,
            "conclusion": "failure",
            "artifact_count": 0,
            "rerun_count": 0,
            "rerun_authorized": False,
            "request_sha256": V8_REQUEST_SHA256,
            "failure_evidence_sha256": V8_FAILURE_EVIDENCE_SHA256,
            "failure_evidence_semantic_sha256": (
                V8_FAILURE_EVIDENCE_SEMANTIC_SHA256
            ),
            "failure_verifier_sha256": V8_FAILURE_VERIFIER_SHA256,
        },
        "V9 predecessor terminal semantics changed",
    )
    require(
        recovery.get("vertex_input_omission_projection_sha256")
        == SOURCE_FIXTURE_SHA256
        and recovery.get("missing_inputs_member_allowed_as_nonbinding")
        is True
        and recovery.get("explicit_empty_inputs_member_allowed") is False
        and recovery.get("first_nonempty_ordered_vector_binds") is True
        and recovery.get("bound_vector_requires_exact_ordered_match") is True
        and recovery.get("omission_only_proves_zero_inputs_or_leaf") is False
        and recovery.get(
            "union_append_last_write_or_ignore_recovery_allowed"
        )
        is False
        and recovery.get("v8_runtime_input_transition_reconstructed")
        is False
        and recovery.get("import_mixed_presence_diagnostic_required")
        is True
        and recovery.get(
            "populated_source_location_delegated_to_frozen_v8"
        )
        is True
        and recovery.get("github_actions_provenance_injection_authorized")
        is False
        and recovery.get("buildkit_auth_behavior")
        == "ordinary_credentials_only",
        "V9 omitted-input recovery basis changed",
    )
    require(
        verifier_chain
        == {
            "v2_sha256": (
                "bf526c29b213dc15d257cb9aedc52790aa1dc9cf1f82bba0e6e85e41db3edf38"
            ),
            "v3_sha256": (
                "c2e318d5d9cbe196d8b9294277c85e1ee986ccb3e1970b3d25a31d28c8da0fef"
            ),
            "v6_sha256": (
                "86d93114e804bf6a51fdb160651d6a20c555f107b88020e0f8d811d0f0d358e5"
            ),
            "v7_sha256": (
                "76af4aa0c8dbe68b46cc71fb74f1582030c5f28a7218a2ee04bcbde5f4198cd7"
            ),
            "v8_sha256": V8_BUNDLE_VERIFIER_SHA256,
            "v9_sha256": BUNDLE_VERIFIER_SHA256,
        },
        "V9 bundle verifier chain changed",
    )
    require(
        evidence.get("v8_dynamic_metadata_retained") is False
        and evidence.get("v8_dynamic_progress_retained") is False
        and evidence.get("source_projection_only_not_v8_runtime_evidence")
        is True
        and evidence.get(
            "v8_conflicting_digest_or_vectors_reconstructed"
        )
        is False
        and evidence.get("missing_inputs_member_nonbinding") is True
        and evidence.get(
            "explicit_empty_null_non_array_inputs_rejected"
        )
        is True
        and evidence.get(
            "first_nonempty_ordered_input_vector_binds"
        )
        is True
        and evidence.get("bound_input_vector_exact_order_required") is True
        and evidence.get("omission_only_input_state_remains_unknown")
        is True
        and evidence.get("non_input_vertex_fields_exact_required") is True
        and evidence.get(
            "input_union_append_last_write_or_ignore_allowed"
        )
        is False
        and evidence.get(
            "mixed_presence_diagnostic_required_on_successful_import"
        )
        is True
        and evidence.get("frozen_v8_delegate_required") is True
        and evidence.get("original_progress_sha256_required") is True
        and evidence.get("compatibility_progress_persistence_authorized")
        is False,
        "V9 build-evidence recovery contract changed",
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
        "V9 bounded authorization contract changed",
    )

    try:
        fixture = _strict_json(source_fixture_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V9 source fixture: {exc}")
        fixture = {}
    contract = fixture.get("v9_contract", {})
    findings = fixture.get("source_findings", {})
    require(
        fixture.get("classification")
        == (
            "SOURCE_PROVEN_OMITTED_VERTEX_INPUTS_COMPATIBILITY_"
            "CONTRACT_NOT_V8_RUNTIME_EVIDENCE"
        )
        and fixture.get("actual_v8_runtime_progress_retained") is False
        and fixture.get("actual_v8_conflicting_digest_retained") is False
        and fixture.get("actual_v8_previous_input_vector_retained") is False
        and fixture.get("actual_v8_current_input_vector_retained") is False
        and fixture.get("runtime_input_transition_reconstructed") is False
        and fixture.get("buildkit", {}).get("commit")
        == "e42e1bfd389af7203238cce77b1f7dad447285e9"
        and fixture.get("buildx", {}).get("commit")
        == "a319e5b15052cf6557ceb666eb8ff6e32380b782"
        and findings.get(
            "structural_vertex_preserves_ordered_nonempty_inputs"
        )
        is True
        and findings.get("controller_lifecycle_vertex_omits_inputs")
        is True
        and findings.get("field_level_vertex_merge_before_rawjson") is False
        and findings.get("v8_observed_transition_reconstructed") is False
        and contract.get("missing_inputs_member_allowed_as_nonbinding")
        is True
        and contract.get("explicit_empty_inputs_member_allowed") is False
        and contract.get("omission_only_proves_zero_inputs_or_leaf") is False
        and contract.get(
            "union_append_last_write_or_ignore_recovery_allowed"
        )
        is False
        and contract.get("v8_runtime_input_transition_reconstructed")
        is False,
        "V9 input-omission source projection changed",
    )

    workflow = workflow_bytes.decode("utf-8", errors="replace")
    bundle = bundle_verifier_bytes.decode("utf-8", errors="replace")
    for forbidden in (
        "workflow_dispatch:",
        "pull_request:",
        "schedule:",
        "repository_dispatch:",
        "permissions: write",
        "docker login",
        "docker push",
        "kubectl ",
        "psql ",
        "NOTEAI_V9_PLAN_VERIFIER_PATH",
    ):
        require(forbidden not in workflow, f"V9 workflow forbidden token: {forbidden}")
    require(
        workflow.split("\npermissions:", 1)[0] == EXPECTED_WORKFLOW_HEADER,
        "V9 trigger block changed",
    )
    for required in (
        "permissions:\n  contents: read",
        "timeout-minutes: 120",
        'test "${GITHUB_RUN_ATTEMPT}" = "1"',
        "NOTEAI_V8_TERMINAL_RECEIPT",
        "NOTEAI_V9_VERTEX_INPUT_OMISSION_SOURCE_PROJECTION_SHA256",
        "NOTEAI_V8_BUNDLE_VERIFIER_PATH",
        "v8_verifier_copy",
        "tools/verify_admin_dependency_cache_bundle_v9.py",
        ".import.v9_rawjson_diagnostic.input_mixed_presence_vertex_digest_count > 0",
        "retention-days: 1",
        "compression-level: 0",
        "admin-dependency-prefix-cache-5335bda-v2",
        "Remove V9 builders and all transient Docker state",
        "Upload one-day V9 public-repository dependency cache artifact",
        "Remove runner-local V9 bundle",
    ):
        require(required in workflow, f"V9 workflow contract missing: {required}")
    require(
        workflow.count("docker buildx create \\") == 2
        and workflow.count("--driver-opt ") == 4
        and workflow.count('--driver-opt "provenance-add-gha=false"') == 2,
        "V9 isolated builder contract changed",
    )
    require(
        workflow.count('test "${GITHUB_RUN_ATTEMPT}" = "1"') == 2
        and workflow.count("uses: actions/upload-artifact@") == 1
        and workflow.count("retention-days: 1") == 1,
        "V9 attempt or artifact bounds changed",
    )
    cleanup_position = workflow.find(
        "Remove V9 builders and all transient Docker state"
    )
    upload_position = workflow.find(
        "Upload one-day V9 public-repository dependency cache artifact"
    )
    local_removal_position = workflow.find("Remove runner-local V9 bundle")
    require(
        0 <= cleanup_position < upload_position < local_removal_position,
        "V9 cleanup/upload ordering changed",
    )
    for required in (
        "V8_VERIFIER_SHA256",
        '"inputs" not in vertex',
        "and bool(inputs)",
        "input_mixed_presence_vertex_digest_count",
        "_patched_v8_input_omission_contract",
        "FROZEN_V8_DISPATCH_CHANGED",
        "noteai_v9_progress_diagnostic=",
        "noteai.admin-dependency-cache-v9-diagnostic.v1",
    ):
        require(required in bundle, f"V9 bundle verifier contract missing: {required}")
    require(
        'vertex.get("inputs", [])' not in bundle
        and "union(" not in bundle
        and "sorted(input" not in bundle,
        "V9 bundle input recovery broadened",
    )

    errors.extend(
        f"frozen V8 plan: {item}"
        for item in v8_plan.validate_plan(
            verify_git_state=verify_git_state,
        )
    )
    try:
        evidence_payload = v8_failure.load_strict()
        require(
            v8_failure.semantic_sha256(evidence_payload)
            == V8_FAILURE_EVIDENCE_SEMANTIC_SHA256,
            "V8 terminal evidence semantic hash drift",
        )
        errors.extend(
            f"V8 terminal evidence: {item}"
            for item in v8_failure.verify(
                evidence_payload,
                verify_git_state=verify_git_state,
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot verify V8 terminal evidence: {exc}")

    if verify_git_state:
        try:
            require(
                v8_plan._request_additions() == [V8_CONTROL_COMMIT],
                "V8 request addition history changed",
            )
            require(
                _git("rev-list", "--parents", "-n", "1", V8_CONTROL_COMMIT)
                == f"{V8_CONTROL_COMMIT} {V8_PLAN_PARENT}",
                "V8 control parent changed",
            )
            require(
                _git(
                    "rev-list",
                    "--parents",
                    "-n",
                    "1",
                    V8_TERMINAL_CHECKPOINT,
                )
                == f"{V8_TERMINAL_CHECKPOINT} {V8_CONTROL_COMMIT}",
                "V8 terminal checkpoint parent changed",
            )
            require(
                _git(
                    "rev-list",
                    "--parents",
                    "-n",
                    "1",
                    V8_TERMINAL_RECEIPT,
                )
                == f"{V8_TERMINAL_RECEIPT} {V8_TERMINAL_CHECKPOINT}",
                "V8 terminal receipt parent changed",
            )
            require(
                subprocess.run(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        V8_TERMINAL_RECEIPT,
                        "HEAD",
                    ],
                    cwd=ROOT,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ).returncode
                == 0,
                "V8 terminal receipt is not an ancestor",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify V8 terminal history: {exc}")

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
                errors.append("inactive V9 request has prior addition history")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify inactive V9 request history: {exc}")
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
            "V9_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V9_CONSUMED_OR_INVALID"
    return "PREPARED_V9_NOT_TRIGGERED"


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
            active_git_errors = [f"cannot load V9 active request: {exc}"]
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
    print(f"admin_dependency_cache_export_plan_v9=PASS state={plan_state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
