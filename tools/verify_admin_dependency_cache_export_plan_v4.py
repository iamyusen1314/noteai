#!/usr/bin/env python3
"""Verify the inert, append-only V4 Admin dependency-cache recovery plan."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

import verify_admin_dependency_cache_v3_failure_evidence as failure_evidence
import verify_admin_dependency_cache_export_plan_v3 as v3_plan


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v4.yml"
)
TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v4.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v4.json"
)
V3_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v3.yml"
)
V3_TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v3.json"
)
V3_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v3.json"
)
V3_PLAN_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_export_plan_v3.py"
)
V3_TRANSIENT_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v3.py"
)
V3_CLEANUP_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "cleanup_admin_dependency_cache_v3.sh"
)
EXPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "export_admin_dependency_cache.sh"
IMPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "import_admin_dependency_cache.sh"
BASE_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle.py"
)
BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v3.py"
)
TRANSIENT_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v4.py"
)
CLEANUP_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "cleanup_admin_dependency_cache_v4.sh"
)
DOWNLOAD_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "download_admin_dependency_cache_artifact.sh"
)
PROVIDER_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_provider_download.py"
)
FAILURE_EVIDENCE_PATH = failure_evidence.EVIDENCE_PATH
FAILURE_EVIDENCE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_v3_failure_evidence.py"
)


# Filled only after the complete inert V4 plan receives local review.
WORKFLOW_SHA256 = (
    "5331e03bd2080651c5374b6f051e34da569eb16d50ed3f8b3b9856edc94304cc"
)
TEMPLATE_SHA256 = "6e2a7ba6f6f242ef1bcaa84cc47cbab4d51763d2425b4999b6f506e769a614da"
V3_WORKFLOW_SHA256 = (
    "60b48606e98ce9ea8b81b6afcc910701798cd3dff307661e11ff383dbb2eed39"
)
V3_TEMPLATE_SHA256 = (
    "2ddca5c392f21cfa3b623197d07c2f8a983715a95ec58042aa0eece8930cd2f3"
)
V3_REQUEST_SHA256 = (
    "7c7eff9d0cf7c20009f57237bc50f2b06b3c6f3f28ec1401eefeeff1c91583b9"
)
V3_PLAN_VERIFIER_SHA256 = (
    "f1de65d37f7bac35fcf1df7ac490a69df0057bef4d0800fbbdaa0ce0b4c85924"
)
V3_TRANSIENT_VERIFIER_SHA256 = (
    "da19c4908fc73ee7bdd74342cf0c626a2db79299672ba5aa0511a7c9d92baae0"
)
V3_CLEANUP_HELPER_SHA256 = (
    "b6115cc641c563f90236bcbdea432e0ca18ff9908834f663c6eeadd27ffa3101"
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
BUNDLE_VERIFIER_SHA256 = (
    "c2e318d5d9cbe196d8b9294277c85e1ee986ccb3e1970b3d25a31d28c8da0fef"
)
TRANSIENT_VERIFIER_SHA256 = (
    "a6578845bc220f38ffc819ced26d8d0c3530b37e53ebc4c74cceeb4b523ea432"
)
CLEANUP_HELPER_SHA256 = (
    "6cc130389abcd60a6f1e901160957ab2f2c33e0986e4b8c2a6c6fa89caa23ab2"
)
DOWNLOAD_HELPER_SHA256 = (
    "66abfd513be7aa81946072493e1472030a8acccbf7a3e2d4dc461c94712e2a92"
)
PROVIDER_VERIFIER_SHA256 = (
    "ca05697d12b8c02b183b1c611c33781d63641c5369bc54b2508a538591a0986b"
)
FAILURE_EVIDENCE_SHA256 = (
    "6ea71731d57e55dee16c162838a68e6c22ea48baad53185f3c5f5c1a8f76425c"
)
FAILURE_EVIDENCE_VERIFIER_SHA256 = (
    "74c2b3e2e644d70680be6b035299c7a00edc5a2e3be4e2fe647bb2314087a012"
)

V3_CONTROL_COMMIT = "443bb1e534f98232541f44b744d753bfa7c09168"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
BUILDX_VERSION = "v0.35.0"
BUILDX_SOURCE_COMMIT = "a319e5b15052cf6557ceb666eb8ff6e32380b782"
EXPECTED_BUILDKITD_FLAGS = ["--allow-insecure-entitlement=network.host"]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_TEMPLATE = {
    "schema_version": 4,
    "task": "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
    "release_commit": RELEASE_COMMIT,
    "plan_checkpoint_commit": "__DIRECT_PARENT_COMMIT__",
    "release_scope": "admin_dependency_prefix_cache_recovery",
    "trigger_mode": "one_shot_added_request_v4",
    "predecessor": {
        "control_commit": V3_CONTROL_COMMIT,
        "run_id": 30596283342,
        "run_attempt": 1,
        "conclusion": "failure",
        "artifact_count": 0,
        "rerun_authorized": False,
        "failure_evidence_sha256": FAILURE_EVIDENCE_SHA256,
    },
    "recovery_basis": {
        "runner_image": "ubuntu-24.04",
        "runner_image_version": "20260720.247.2",
        "buildx_version": BUILDX_VERSION,
        "buildx_source_commit": BUILDX_SOURCE_COMMIT,
        "exact_buildkitd_flags": EXPECTED_BUILDKITD_FLAGS,
        "additional_buildkitd_flags_authorized": False,
        "build_network_host_authorized": False,
    },
    "recovery_run_authorized_after_predecessor_failure": True,
    "github_actions_maximum_runtime_minutes": 120,
    "artifact_retention_days": 1,
    "artifact_input_maximum_bytes": 4_026_531_840,
    "artifact_provider_maximum_bytes": 4_294_967_296,
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


def reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str):
    raise ValueError(f"non-finite JSON number: {value}")


def parse_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def strict_json(value: bytes) -> dict[str, Any]:
    payload = json.loads(
        value.decode("utf-8"),
        object_pairs_hook=reject_duplicate_pairs,
        parse_constant=reject_constant,
        parse_float=parse_float,
    )
    if not isinstance(payload, dict):
        raise ValueError("request root must be an object")
    return payload


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


def _validate_v3_frozen_git() -> list[str]:
    errors: list[str] = []
    try:
        additions = _request_additions(
            request_path=V3_REQUEST_PATH.relative_to(ROOT),
        )
        if additions != [V3_CONTROL_COMMIT]:
            errors.append("V3 request addition history changed")
            return errors
        parent_fields = _git(
            "rev-list",
            "--parents",
            "-n",
            "1",
            V3_CONTROL_COMMIT,
        ).split()
        if len(parent_fields) != 2:
            errors.append("V3 controller is no longer single-parent")
            return errors
        changed = _git(
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            parent_fields[1],
            V3_CONTROL_COMMIT,
        ).splitlines()
        if changed != [V3_REQUEST_PATH.relative_to(ROOT).as_posix()]:
            errors.append("V3 controller change set drifted")
        current = subprocess.run(
            [
                "git",
                "show",
                f"HEAD:{V3_REQUEST_PATH.relative_to(ROOT).as_posix()}",
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if sha256_bytes(current) != V3_REQUEST_SHA256:
            errors.append("V3 request is not retained byte-exact")
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify frozen V3 Git state: {exc}")
    return errors


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
        request = strict_json(request_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid V4 active request: {exc}"]
    parent = request.get("plan_checkpoint_commit")
    if not isinstance(parent, str) or not COMMIT_RE.fullmatch(parent):
        return ["V4 active request checkpoint is invalid"]
    if plan_parent is not None and parent != plan_parent:
        errors.append("V4 active request does not bind its direct parent")
    expected_bytes = template_bytes.replace(
        b"__DIRECT_PARENT_COMMIT__",
        parent.encode("ascii"),
    )
    if request_bytes != expected_bytes:
        errors.append("V4 active request differs from reviewed template")
    expected = dict(EXPECTED_TEMPLATE)
    expected["plan_checkpoint_commit"] = parent
    if request != expected:
        errors.append("V4 active request semantics drift")

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
            return errors + ["V4 active request addition history is not unique"]
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
            return errors + ["V4 controller is not single-parent"]
        if parent != parents[1]:
            errors.append("V4 request checkpoint differs from controller parent")
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
            errors.append("V4 activation changes more than its request")
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
            errors.append("V4 request was not a unique addition")
        mode = _git_at(root, "ls-tree", "HEAD", "--", relative.as_posix()).split()
        if mode[:2] != ["100644", "blob"]:
            errors.append("V4 request is not retained as 100644")
        current = subprocess.run(
            ["git", "show", f"HEAD:{relative.as_posix()}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if current != request_bytes:
            errors.append("V4 request bytes changed after activation")
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V4 active request Git state: {exc}")
    return errors


def validate_plan(
    *,
    workflow_bytes: bytes | None = None,
    template_bytes: bytes | None = None,
    bundle_verifier_bytes: bytes | None = None,
    transient_verifier_bytes: bytes | None = None,
    cleanup_helper_bytes: bytes | None = None,
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
        bundle_verifier_bytes = (
            BUNDLE_VERIFIER_PATH.read_bytes()
            if bundle_verifier_bytes is None
            else bundle_verifier_bytes
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
        if active_request_bytes is None and ACTIVE_REQUEST_PATH.exists():
            active_request_bytes = ACTIVE_REQUEST_PATH.read_bytes()
    except OSError as exc:
        return [f"cannot load V4 dependency-cache plan: {exc}"]

    fixed_paths = (
        (workflow_bytes, WORKFLOW_SHA256, "V4 workflow"),
        (template_bytes, TEMPLATE_SHA256, "V4 template"),
        (V3_WORKFLOW_PATH.read_bytes(), V3_WORKFLOW_SHA256, "frozen V3 workflow"),
        (V3_TEMPLATE_PATH.read_bytes(), V3_TEMPLATE_SHA256, "frozen V3 template"),
        (V3_REQUEST_PATH.read_bytes(), V3_REQUEST_SHA256, "frozen V3 request"),
        (
            V3_PLAN_VERIFIER_PATH.read_bytes(),
            V3_PLAN_VERIFIER_SHA256,
            "frozen V3 plan verifier",
        ),
        (
            V3_TRANSIENT_VERIFIER_PATH.read_bytes(),
            V3_TRANSIENT_VERIFIER_SHA256,
            "frozen V3 transient verifier",
        ),
        (
            V3_CLEANUP_HELPER_PATH.read_bytes(),
            V3_CLEANUP_HELPER_SHA256,
            "frozen V3 cleanup helper",
        ),
        (EXPORT_HELPER_PATH.read_bytes(), EXPORT_HELPER_SHA256, "export helper"),
        (IMPORT_HELPER_PATH.read_bytes(), IMPORT_HELPER_SHA256, "import helper"),
        (
            BASE_BUNDLE_VERIFIER_PATH.read_bytes(),
            BASE_BUNDLE_VERIFIER_SHA256,
            "base bundle verifier",
        ),
        (bundle_verifier_bytes, BUNDLE_VERIFIER_SHA256, "V4 bundle verifier"),
        (
            transient_verifier_bytes,
            TRANSIENT_VERIFIER_SHA256,
            "V4 transient verifier",
        ),
        (cleanup_helper_bytes, CLEANUP_HELPER_SHA256, "V4 cleanup helper"),
        (DOWNLOAD_HELPER_PATH.read_bytes(), DOWNLOAD_HELPER_SHA256, "download helper"),
        (
            PROVIDER_VERIFIER_PATH.read_bytes(),
            PROVIDER_VERIFIER_SHA256,
            "provider verifier",
        ),
        (
            FAILURE_EVIDENCE_PATH.read_bytes(),
            FAILURE_EVIDENCE_SHA256,
            "V3 failure evidence",
        ),
        (
            FAILURE_EVIDENCE_VERIFIER_PATH.read_bytes(),
            FAILURE_EVIDENCE_VERIFIER_SHA256,
            "V3 failure verifier",
        ),
    )
    for actual, expected, label in fixed_paths:
        require(
            expected != "PENDING" and sha256_bytes(actual) == expected,
            f"{label} hash drift",
        )

    try:
        template = strict_json(template_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V4 request template: {exc}")
        template = {}
    require(template == EXPECTED_TEMPLATE, "V4 request template drift")
    require(
        template_bytes.count(b"__DIRECT_PARENT_COMMIT__") == 1,
        "V4 request parent placeholder count changed",
    )
    try:
        evidence_payload = failure_evidence.load_strict()
        errors.extend(
            f"V3 failure evidence: {item}"
            for item in failure_evidence.verify(evidence_payload)
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot verify V3 failure evidence: {exc}")
    errors.extend(f"frozen V3 plan: {item}" for item in v3_plan.validate_plan())

    if verify_git_state:
        errors.extend(_validate_v3_frozen_git())
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
                errors.append("inactive V4 request has prior addition history")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify inactive V4 request history: {exc}")

    workflow = workflow_bytes.decode("utf-8", errors="replace")
    bundle_verifier = bundle_verifier_bytes.decode("utf-8", errors="replace")
    transient_verifier = transient_verifier_bytes.decode(
        "utf-8",
        errors="replace",
    )
    cleanup_helper = cleanup_helper_bytes.decode("utf-8", errors="replace")
    export_helper = EXPORT_HELPER_PATH.read_text(encoding="utf-8")
    import_helper = IMPORT_HELPER_PATH.read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

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
    ):
        require(forbidden not in workflow, f"V4 workflow forbidden token: {forbidden}")
    require(
        "permissions:\n  contents: read" in workflow,
        "V4 workflow permissions changed",
    )
    job_environment = workflow.split("    env:\n", 1)[1].split(
        "\n    steps:",
        1,
    )[0]
    require(
        "${{ runner." not in job_environment,
        "V4 job environment uses runner context",
    )
    require(
        workflow.count(
            "DOCKER_CONFIG: ${{ runner.temp }}/noteai-empty-docker-config-v4"
        )
        == 4,
        "V4 Docker config step count changed",
    )
    require(
        workflow.count(
            "BUILDX_CONFIG: ${{ runner.temp }}/noteai-buildx-state-v4"
        )
        == 4,
        "V4 Buildx config step count changed",
    )
    require(
        "admin-5335bda-dependency-cache-v4.json" in workflow,
        "V4 trigger path changed",
    )
    require(
        ".github/workflows/admin-dependency-cache-export-v4.yml"
        not in workflow.split("permissions:", 1)[0],
        "V4 workflow triggers on installation",
    )
    require("timeout-minutes: 120" in workflow, "V4 runtime cap changed")
    require("retention-days: 1" in workflow, "V4 retention changed")
    require("compression-level: 0" in workflow, "V4 compression changed")
    require(
        workflow.count('test "${GITHUB_RUN_ATTEMPT}" = "1"') == 2,
        "V4 rerun guards changed",
    )
    require(
        workflow.count("--driver docker-container") == 2
        and workflow.count(
            "--driver-opt \"image=${NOTEAI_BUILDKIT_IMAGE}\""
        )
        == 2,
        "V4 isolated builder creation changed",
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
        "V4 exact BuildKit daemon flags changed",
    )
    require(
        "NOTEAI_BUILDX_VERSION: v0.35.0" in workflow
        and (
            "NOTEAI_BUILDX_SOURCE_COMMIT: "
            "a319e5b15052cf6557ceb666eb8ff6e32380b782"
        )
        in workflow
        and 'buildx_identity="$(docker buildx version)"' in workflow
        and 'test "${#buildx_commit}" -ge 7' in workflow
        and 'test "${#buildx_commit}" -le 40' in workflow
        and (
            'test "${NOTEAI_BUILDX_SOURCE_COMMIT:0:${#buildx_commit}}" = \\'
        )
        in workflow,
        "V4 Buildx source identity gate changed",
    )
    require(
        (
            "moby/buildkit@sha256:"
            "2f5adac4ecd194d9f8c10b7b5d7bceb"
            "5186853db1b26e5abd3a657af0b7e26ec"
        )
        in workflow
        and ')" = "v0.31.2"' in workflow,
        "V4 BuildKit pin/version changed",
    )
    require(
        workflow.count(
            "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        )
        == 2,
        "V4 checkout pin/count changed",
    )
    require(
        workflow.count(
            "uses: actions/upload-artifact@"
            "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        )
        == 1,
        "V4 upload pin/count changed",
    )
    require(
        workflow.index("Remove V4 builders and all transient Docker state")
        < workflow.index(
            "Upload one-day V4 public-repository dependency cache artifact"
        )
        < workflow.index("Remove runner-local V4 bundle"),
        "V4 cleanup/upload ordering changed",
    )
    for required in (
        'test "${#changed_files[@]}" -eq 1',
        'test "${changed_files[0]}" = "${NOTEAI_REQUEST_PATH}"',
        "--no-renames --diff-filter=A",
        'test "${#request_add_commits[@]}" -eq 1',
        'test "${request_add_commits[0]}" = "${GITHUB_SHA}"',
        "NOTEAI_V3_CONTROL_COMMIT",
        "NOTEAI_V3_REQUEST_SHA256",
        "NOTEAI_V3_WORKFLOW_SHA256",
        "NOTEAI_V3_TRANSIENT_VERIFIER_SHA256",
        "NOTEAI_V3_CLEANUP_HELPER_SHA256",
        "NOTEAI_FAILURE_EVIDENCE_SHA256",
        "python3 \"${NOTEAI_V3_PLAN_VERIFIER_PATH}\"",
        "python3 \"${NOTEAI_FAILURE_EVIDENCE_VERIFIER_PATH}\"",
        "__DIRECT_PARENT_COMMIT__",
        'cmp "${request_file}" "${expected_request}"',
        "recovery_run_authorized_after_predecessor_failure == true",
        "rerun_authorized: false",
        "artifact_count: 0",
        "runner_image_version: \"20260720.247.2\"",
        "buildx_version: \"v0.35.0\"",
        "additional_buildkitd_flags_authorized: false",
        "build_network_host_authorized: false",
        "public_repository_artifact_authorized == true",
        "cross_provider_transfer_authorized == true",
        "registry_publication_authorized == false",
        "git merge-base --is-ancestor",
        "ref: ${{ env.RELEASE_COMMIT }}",
        "persist-credentials: false",
        "NOTEAI_BASE_BUNDLE_VERIFIER_PATH",
        "NOTEAI_TRANSIENT_STATE_VERIFIER_PATH",
        "NOTEAI_CLEANUP_HELPER_PATH",
        "cleanup_passed == 'true'",
        "rm -rf --one-file-system -- \"${NOTEAI_CACHE_BUNDLE_DIR}\"",
    ):
        require(required in workflow, f"V4 workflow contract missing: {required}")

    require(
        export_helper.count("--platform linux/amd64") == 1,
        "export target-platform count changed",
    )
    require(
        import_helper.count("--platform linux/amd64") == 2,
        "import target-platform count changed",
    )
    for source_name, source in (
        ("Dockerfile", dockerfile),
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
        'EXPECTED_BUILDER_PLATFORM = "linux/amd64"',
        'EXPECTED_DOCKERFILE_FRONTEND_VERSION = "1.25.0"',
        'EXPECTED_TARGET_PLATFORM = {"Architecture": "amd64", "OS": "linux"}',
        "BuildKit builder environment changed",
        "BuildKit target platform changed",
        "target_platform_vertex_count",
        "BASE_VERIFIER_SHA256",
    ):
        require(
            required in bundle_verifier,
            f"V4 bundle verifier contract missing: {required}",
        )
    for required in (
        "noteai-empty-docker-config-v4",
        "noteai-buildx-state-v4",
        "_reject_duplicate_pairs",
        "_validate_node_group",
        'BUILDX_VERSION = "v0.35.0"',
        (
            'BUILDX_SOURCE_COMMIT = '
            '"a319e5b15052cf6557ceb666eb8ff6e32380b782"'
        ),
        "EXPECTED_BUILDKITD_FLAGS = [",
        '"--allow-insecure-entitlement=network.host",',
        'node["Flags"] == EXPECTED_BUILDKITD_FLAGS',
        'node["Files"] in (None, {})',
        "Buildx state file path changed",
        'config == {"auths": {}}',
        "Buildx state symlink found",
        "Buildx state hardlink found",
        "Buildx special file found",
        "SENSITIVE_BUILD_STATE_RE",
        "MAXIMUM_DOCKER_CONFIG_BYTES",
        "MAXIMUM_BUILDX_STATE_BYTES",
    ):
        require(
            required in transient_verifier,
            f"V4 transient-state contract missing: {required}",
        )
    for required in (
        "failure_count",
        "validate_transient_state",
        "remove_builder",
        'docker buildx rm "${builder_name}"',
        "transient-state verifier unavailable",
        'rm -rf --one-file-system -- "${docker_config}"',
        'rm -rf --one-file-system -- "${buildx_config}"',
        '[[ ! -e "${docker_config}" ]]',
        '[[ ! -e "${buildx_config}" ]]',
        "Admin dependency-cache cleanup failed closed",
    ):
        require(
            required in cleanup_helper,
            f"V4 cleanup contract missing: {required}",
        )
    require("rmdir " not in cleanup_helper, "V4 cleanup retains V3 rmdir defect")
    require(
        'docker buildx rm "${builder_name}" >/dev/null 2>&1 || true'
        not in cleanup_helper,
        "V4 cleanup ignores builder removal",
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
            "V4_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V4_CONSUMED_OR_INVALID"
    return "PREPARED_V4_NOT_TRIGGERED"


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
            active_git_errors = [f"cannot load V4 active request: {exc}"]
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
    print(f"admin_dependency_cache_export_plan_v4=PASS state={plan_state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
