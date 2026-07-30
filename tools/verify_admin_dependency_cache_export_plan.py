#!/usr/bin/env python3
"""Verify the fail-closed exact-5335 dependency-cache export plan."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "admin-dependency-cache-export.yml"
EXPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "export_admin_dependency_cache.sh"
IMPORT_HELPER_PATH = ROOT / "scripts" / "ci" / "import_admin_dependency_cache.sh"
BUNDLE_VERIFIER_PATH = ROOT / "tools" / "verify_admin_dependency_cache_bundle.py"
DOWNLOAD_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "download_admin_dependency_cache_artifact.sh"
)
PROVIDER_DOWNLOAD_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_provider_download.py"
)
REQUEST_TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v2.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v2.json"
)

# Updated only after the complete inert plan receives review.
WORKFLOW_SHA256 = (
    "a98b72cb6f2bc167deb789954aa87fa0b62cf78560610dbe09ddb2849598903e"
)
EXPORT_HELPER_SHA256 = (
    "fabcdc2245c537c2fd56e88b6e0aced77d5c26234fc74d7d934b11ecda8d860c"
)
IMPORT_HELPER_SHA256 = (
    "c4986143d5897140f72ad6835b44f7fc989830a30341cb4e3f5718fced3ca777"
)
BUNDLE_VERIFIER_SHA256 = (
    "bf526c29b213dc15d257cb9aedc52790aa1dc9cf1f82bba0e6e85e41db3edf38"
)
REQUEST_TEMPLATE_SHA256 = (
    "331bd7a6dd93d3f714859ebfc2b537c60d911f6e1f1ba05adb0a05e30c254f57"
)
DOWNLOAD_HELPER_SHA256 = (
    "66abfd513be7aa81946072493e1472030a8acccbf7a3e2d4dc461c94712e2a92"
)
PROVIDER_DOWNLOAD_VERIFIER_SHA256 = (
    "943c294d92d2dea13d4cd3dc6396ea2522841634541562d2f22ef4d319c52b36"
)

RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
RELEASE_TREE = "38e574e56406ba3380acb78edbe784508cc537cd"
DOCKERFILE_SHA256 = (
    "ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447"
)
PREFIX_SHA256 = (
    "93fd024e5af678b7885bcab8e72d980a9f92cfc70de4f2fd2870284e25b8ec1e"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_TEMPLATE = {
    "schema_version": 2,
    "task": "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
    "release_commit": RELEASE_COMMIT,
    "plan_checkpoint_commit": "__DIRECT_PARENT_COMMIT__",
    "release_scope": "admin_dependency_prefix_cache",
    "trigger_mode": "one_shot_added_request_v2",
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


def reject_duplicate_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def strict_json_loads(value: bytes) -> dict[str, Any]:
    payload = json.loads(
        value.decode("utf-8"),
        object_pairs_hook=reject_duplicate_object_pairs,
        parse_constant=reject_non_finite_json_constant,
        parse_float=parse_finite_json_float,
    )
    if not isinstance(payload, dict):
        raise ValueError("request root must be an object")
    return payload


def _run_git_at(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _run_git(*args: str) -> str:
    return _run_git_at(ROOT, *args)


def _request_additions(
    *,
    git_root: Path = ROOT,
    request_path: Path | None = None,
) -> list[str]:
    request_path = (
        ACTIVE_REQUEST_PATH.relative_to(ROOT)
        if request_path is None
        else request_path
    )
    head = _run_git_at(git_root, "rev-parse", "HEAD")
    output = _run_git_at(
        git_root,
        "log",
        "--diff-filter=A",
        "--format=%H",
        head,
        "--",
        request_path.as_posix(),
    )
    return output.splitlines() if output else []


def _validate_active_request(
    request_bytes: bytes,
    template_bytes: bytes,
    *,
    plan_parent: str | None,
    verify_git_state: bool,
    git_root: Path = ROOT,
    request_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        request = strict_json_loads(request_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid active dependency-cache request: {exc}"]
    parent = request.get("plan_checkpoint_commit")
    if not isinstance(parent, str) or not COMMIT_RE.fullmatch(parent):
        errors.append("active request plan checkpoint is invalid")
        return errors
    if plan_parent is not None and parent != plan_parent:
        errors.append("active request does not bind its direct parent")
    expected_bytes = template_bytes.replace(
        b"__DIRECT_PARENT_COMMIT__",
        parent.encode("ascii"),
    )
    if request_bytes != expected_bytes:
        errors.append("active request differs from reviewed parent-bound template")
    expected = dict(EXPECTED_TEMPLATE)
    expected["plan_checkpoint_commit"] = parent
    if request != expected:
        errors.append("active dependency-cache request semantics drift")

    if verify_git_state:
        try:
            head = _run_git_at(git_root, "rev-parse", "HEAD")
            request_path = (
                ACTIVE_REQUEST_PATH.relative_to(ROOT)
                if request_path is None
                else request_path
            )
            request_path_text = request_path.as_posix()
            additions = _request_additions(
                git_root=git_root,
                request_path=request_path,
            )
            if len(additions) != 1:
                errors.append("active request addition history is not unique")
                return errors
            activation_commit = additions[0]
            parents = _run_git_at(
                git_root,
                "rev-list",
                "--parents",
                "-n",
                "1",
                activation_commit,
            ).split()
            if len(parents) != 2:
                errors.append("active request controller is not single-parent")
                return errors
            direct_parent = parents[1]
            if parent != direct_parent:
                errors.append("active request parent differs from controller parent")
            changed = _run_git_at(
                git_root,
                "diff-tree",
                "--no-commit-id",
                "--no-renames",
                "--name-only",
                "-r",
                direct_parent,
                activation_commit,
            ).splitlines()
            if changed != [request_path_text]:
                errors.append("active request commit changes more than its request")
            added = _run_git_at(
                git_root,
                "diff-tree",
                "--no-commit-id",
                "--no-renames",
                "--diff-filter=A",
                "--name-status",
                "-r",
                direct_parent,
                activation_commit,
                "--",
                request_path_text,
            )
            if added != f"A\t{request_path_text}":
                errors.append("active request was not added exactly once")
            mode = _run_git_at(
                git_root,
                "ls-tree",
                activation_commit,
                "--",
                request_path_text,
            ).split()
            if mode[:2] != ["100644", "blob"]:
                errors.append("active request is not a regular 100644 blob")
            committed_request = subprocess.run(
                ["git", "show", f"{activation_commit}:{request_path_text}"],
                cwd=git_root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            if committed_request != request_bytes:
                errors.append("active request changed after activation")
            current_mode = _run_git_at(
                git_root,
                "ls-tree",
                head,
                "--",
                request_path_text,
            ).split()
            if current_mode[:2] != ["100644", "blob"]:
                errors.append("active request is not retained in current HEAD")
            else:
                current_request = subprocess.run(
                    ["git", "show", f"{head}:{request_path_text}"],
                    cwd=git_root,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ).stdout
                if current_request != request_bytes:
                    errors.append("active request differs from current HEAD")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify active request Git state: {exc}")
    return errors


def _validate_exact_prefix() -> list[str]:
    errors: list[str] = []
    try:
        dockerfile = subprocess.run(
            ["git", "show", f"{RELEASE_COMMIT}:Dockerfile"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"cannot load exact release Dockerfile: {exc}"]
    if sha256_bytes(dockerfile) != DOCKERFILE_SHA256:
        errors.append("exact release Dockerfile hash changed")
    lines = dockerfile.splitlines(keepends=True)
    if len(lines) < 83:
        return errors + ["exact release Dockerfile is too short"]
    prefix = b"".join(lines[:80])
    if sha256_bytes(prefix) != PREFIX_SHA256:
        errors.append("dependency prefix hash changed")
    if lines[80] not in (b"\n", b"\r\n"):
        errors.append("dependency prefix boundary line 81 changed")
    if lines[82].rstrip(b"\r\n") != b"COPY model/ ./model/":
        errors.append("first application COPY line changed")
    local_copy_lines = [
        line.decode("utf-8").strip()
        for line in lines[:80]
        if line.startswith(b"COPY ") and not line.startswith(b"COPY --from=")
    ]
    if local_copy_lines != [
        "COPY model/requirements.txt model/requirements-api.txt ./"
    ]:
        errors.append("dependency prefix local COPY scope changed")
    return errors


def validate_plan(
    *,
    workflow_bytes: bytes | None = None,
    export_helper_bytes: bytes | None = None,
    import_helper_bytes: bytes | None = None,
    bundle_verifier_bytes: bytes | None = None,
    download_helper_bytes: bytes | None = None,
    provider_download_verifier_bytes: bytes | None = None,
    template_bytes: bytes | None = None,
    active_request_bytes: bytes | None = None,
    active_plan_parent: str | None = None,
    verify_active_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []
    filesystem_request_mode = active_request_bytes is None

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        workflow_bytes = (
            WORKFLOW_PATH.read_bytes() if workflow_bytes is None else workflow_bytes
        )
        export_helper_bytes = (
            EXPORT_HELPER_PATH.read_bytes()
            if export_helper_bytes is None
            else export_helper_bytes
        )
        import_helper_bytes = (
            IMPORT_HELPER_PATH.read_bytes()
            if import_helper_bytes is None
            else import_helper_bytes
        )
        bundle_verifier_bytes = (
            BUNDLE_VERIFIER_PATH.read_bytes()
            if bundle_verifier_bytes is None
            else bundle_verifier_bytes
        )
        download_helper_bytes = (
            DOWNLOAD_HELPER_PATH.read_bytes()
            if download_helper_bytes is None
            else download_helper_bytes
        )
        provider_download_verifier_bytes = (
            PROVIDER_DOWNLOAD_VERIFIER_PATH.read_bytes()
            if provider_download_verifier_bytes is None
            else provider_download_verifier_bytes
        )
        template_bytes = (
            REQUEST_TEMPLATE_PATH.read_bytes()
            if template_bytes is None
            else template_bytes
        )
        active_from_filesystem = False
        if active_request_bytes is None and ACTIVE_REQUEST_PATH.exists():
            active_request_bytes = ACTIVE_REQUEST_PATH.read_bytes()
            active_from_filesystem = True
    except OSError as exc:
        return [f"cannot load dependency-cache export plan: {exc}"]

    for actual, expected, label in (
        (workflow_bytes, WORKFLOW_SHA256, "workflow"),
        (export_helper_bytes, EXPORT_HELPER_SHA256, "export helper"),
        (import_helper_bytes, IMPORT_HELPER_SHA256, "import helper"),
        (bundle_verifier_bytes, BUNDLE_VERIFIER_SHA256, "bundle verifier"),
        (download_helper_bytes, DOWNLOAD_HELPER_SHA256, "download helper"),
        (
            provider_download_verifier_bytes,
            PROVIDER_DOWNLOAD_VERIFIER_SHA256,
            "provider download verifier",
        ),
        (template_bytes, REQUEST_TEMPLATE_SHA256, "request template"),
    ):
        require(
            expected != "PENDING" and sha256_bytes(actual) == expected,
            f"dependency-cache {label} hash drift",
        )

    try:
        template = strict_json_loads(template_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid dependency-cache request template: {exc}")
        template = {}
    require(template == EXPECTED_TEMPLATE, "dependency-cache request template drift")
    require(
        template_bytes.count(b"__DIRECT_PARENT_COMMIT__") == 1,
        "request template parent placeholder count changed",
    )

    if active_request_bytes is not None:
        errors.extend(
            _validate_active_request(
                active_request_bytes,
                template_bytes,
                plan_parent=active_plan_parent,
                verify_git_state=active_from_filesystem and verify_active_git_state,
            )
        )
    elif filesystem_request_mode and verify_active_git_state:
        try:
            if _request_additions():
                errors.append(
                    "inactive dependency-cache request has prior addition history"
                )
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify inactive request Git state: {exc}")

    workflow = workflow_bytes.decode("utf-8", errors="replace")
    export_helper = export_helper_bytes.decode("utf-8", errors="replace")
    import_helper = import_helper_bytes.decode("utf-8", errors="replace")
    bundle_verifier = bundle_verifier_bytes.decode("utf-8", errors="replace")
    download_helper = download_helper_bytes.decode("utf-8", errors="replace")
    provider_download_verifier = provider_download_verifier_bytes.decode(
        "utf-8",
        errors="replace",
    )

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
    ):
        require(forbidden not in workflow, f"workflow contains forbidden token: {forbidden}")
    require(
        "permissions:\n  contents: read" in workflow,
        "workflow permissions are not read-only",
    )
    job_environment = workflow.split("    env:\n", 1)[1].split(
        "\n    steps:",
        1,
    )[0]
    require(
        "${{ runner." not in job_environment,
        "workflow job environment uses unavailable runner context",
    )
    require(
        workflow.count(
            "DOCKER_CONFIG: ${{ runner.temp }}/noteai-empty-docker-config"
        )
        == 4,
        "step-scoped empty Docker config count changed",
    )
    require(
        "      - .github/release-requests/"
        "admin-5335bda-dependency-cache-v2.json" in workflow,
        "workflow trigger request path drift",
    )
    require(
        ".github/workflows/admin-dependency-cache-export.yml"
        not in workflow.split("permissions:", 1)[0],
        "workflow would trigger when merely installed",
    )
    require("timeout-minutes: 120" in workflow, "workflow runtime cap drift")
    require("retention-days: 1" in workflow, "artifact retention drift")
    require("compression-level: 0" in workflow, "artifact compression drift")
    require(
        workflow.count('test "${GITHUB_RUN_ATTEMPT}" = "1"') == 2,
        "workflow rerun gates changed",
    )
    require(
        workflow.count("--driver docker-container") == 2,
        "isolated builder creation count changed",
    )
    require(
        "fresh consumer builders" in workflow
        and "cacheless full-context replay" in workflow,
        "fresh-consumer portability stage missing",
    )
    require(
        "Remove isolated builders and all transient Docker state" in workflow,
        "pre-upload cleanup stage missing",
    )
    require(
        workflow.index("Remove isolated builders and all transient Docker state")
        < workflow.index("Upload one-day public-repository dependency cache artifact"),
        "artifact upload occurs before cleanup",
    )
    require(
        workflow.count(
            "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        )
        == 2,
        "checkout action pin/count drift",
    )
    require(
        workflow.count(
            "uses: actions/upload-artifact@"
            "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        )
        == 1,
        "upload action pin/count drift",
    )
    for required in (
        'test "${#changed_files[@]}" -eq 1',
        'test "${changed_files[0]}" = "${NOTEAI_REQUEST_PATH}"',
        "--no-renames --diff-filter=A",
        'test "${#request_add_commits[@]}" -eq 1',
        'test "${request_add_commits[0]}" = "${GITHUB_SHA}"',
        "controller_parent",
        "__DIRECT_PARENT_COMMIT__",
        'cmp "${request_file}" "${expected_request}"',
        "public_repository_artifact_authorized == true",
        "cross_provider_transfer_authorized == true",
        "artifact_input_maximum_bytes == 4026531840",
        "artifact_provider_maximum_bytes == 4294967296",
        "artifact_visibility_assumption == \"public_repository_readers\"",
        "git merge-base --is-ancestor",
        "ref: ${{ env.RELEASE_COMMIT }}",
        "lfs: false",
        "persist-credentials: false",
        "verify-final",
        "final_sums_sha256",
        "noteai-empty-docker-config",
        "bash \"${{ steps.control.outputs.import_helper_copy }}\"",
        "NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH",
        "BUILDX_BUILDER: ${{ env.NOTEAI_CONSUMER_BUILDER }}",
        "cleanup_passed == 'true'",
    ):
        require(required in workflow, f"workflow contract missing: {required}")

    for script_name, script in (
        ("export helper", export_helper),
        ("import helper", import_helper),
        ("download helper", download_helper),
    ):
        for forbidden in (
            "docker login",
            "docker push",
            "docker run",
            "docker save",
            "docker export",
            "--secret",
            "--ssh",
            "trivy",
            "syft",
        ):
            require(
                forbidden not in script,
                f"{script_name} contains forbidden token: {forbidden}",
            )
    require(
        export_helper.count("docker buildx --builder") == 1,
        "export build invocation count changed",
    )
    for required in (
        "sed -n '1,80p' Dockerfile",
        "--target runtime-common",
        "--platform linux/amd64",
        "--cache-to",
        "type=local,dest=",
        "mode=max",
        "--output type=cacheonly",
        "--progress rawjson",
        "docker buildx imagetools inspect --raw",
        "maximum_raw_tar_bytes=5368709120",
        "maximum_blob_bytes=4294967296",
        "maximum_gzip_bytes=3758096384",
        "maximum_extracted_cache_bytes=4311744512",
        "maximum_artifact_input_bytes=4026531840",
        "maximum_provider_artifact_bytes=4294967296",
        "maximum_non_chunk_file_bytes=134217728",
        "chunk_bytes=268435456",
        "maximum_chunk_count=14",
        "-type f -links +1",
        "application_or_model_source_inputs_supplied_to_export: false",
        "buildkit_credential_or_secret_inputs_supplied: false",
        "buildkit_daemon_image_reference",
        "buildkit_daemon_image_id",
        "transient_buildkit_sandboxes_expected: true",
        "provider_artifact_digest_acceptance_required: true",
    ):
        require(required in export_helper, f"export contract missing: {required}")
    require(
        "credentials_included" not in export_helper,
        "export helper makes an unprovable credential-byte claim",
    )
    require(
        import_helper.count('docker buildx --builder "${NOTEAI_BUILDX_BUILDER}" build')
        == 2,
        "import/replay build invocation count changed",
    )
    require(
        import_helper.count("--cache-from") == 1,
        "local cache import count changed",
    )
    for required in (
        "ci_portability",
        "builder_prewarm",
        "build_timeout_seconds=300",
        "NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH",
        "NOTEAI_EXPECTED_IMPORT_HELPER_SHA256",
        'check_sha256 "${NOTEAI_EXPECTED_IMPORT_HELPER_SHA256}" "$0"',
        'if [[ "${BUILDX_BUILDER}" != "${NOTEAI_BUILDX_BUILDER}" ]]',
        "--require-network-cached",
        'rm -rf "${cache_dir}"',
        "--file \"${NOTEAI_SOURCE_DIR}/Dockerfile\"",
        '"${NOTEAI_SOURCE_DIR}"',
        "external_cache_removed_before_replay: true",
        "full_release_context_used: true",
        "full_replay_release_context_used: true",
        "canonical_admin_build_must_inherit_BUILDX_BUILDER",
        "buildkit_daemon_image_reference",
        "NOTEAI_EXPECTED_FINAL_SUMS_SHA256",
        "NOTEAI_PROVIDER_ARTIFACT_TRANSPORT_DIR",
        "NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH",
        "NOTEAI_EXPECTED_DOWNLOAD_RECEIPT_SHA256",
        "verify-transfer",
        "canonical_admin_build_still_required: true",
    ):
        require(required in import_helper, f"import contract missing: {required}")
    for required in (
        "reject_duplicate_object_pairs",
        "parse_constant=reject_non_finite_json_constant",
        "parse_float=parse_finite_json_float",
        "MAXIMUM_RAW_TAR_BYTES",
        "MAXIMUM_BLOB_BYTES",
        "MAXIMUM_EXTRACTED_CACHE_BYTES",
        "MAXIMUM_ARTIFACT_INPUT_BYTES",
        "MAXIMUM_NON_CHUNK_FILE_BYTES",
        "member.sparse",
        "GNU.sparse".lower(),
        "member.isreg()",
        "duplicate tar member",
        "OCI cache blob closure changed",
        "BuildKit cache layer closure changed",
        "OCI cache root layer descriptors repeat",
        "BuildKit cache record reachability changed",
        "BuildKit cache layer reachability changed",
        "BuildKit cache record link cycle",
        "application/vnd.buildkit.cacheconfig.v0",
        "image.resolvemode",
        "context followpaths",
        "BuildKit target or OCI arguments changed",
        "network vertex was not cached",
        "FULL_CONTEXT_FOLLOWPATHS",
        "chunk names are not contiguous",
        "final sums trust root changed",
    ):
        require(required in bundle_verifier, f"bundle verifier missing: {required}")
    for required in (
        "gh auth status --hostname github.com",
        "actions/artifacts/${NOTEAI_EXPECTED_ARTIFACT_ID}",
        "actions/artifacts/${NOTEAI_EXPECTED_ARTIFACT_ID}/zip",
        "NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH",
        "NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256",
        "NOTEAI_EXPECTED_DOWNLOAD_HELPER_SHA256",
        'sha256sum "$0"',
        "preflight-metadata",
        "receive-zip",
        "verify-download",
        '--transport-dir "${transport}"',
    ):
        require(required in download_helper, f"download helper missing: {required}")
    download_order_tokens = (
        "preflight-metadata",
        "actions/artifacts/${NOTEAI_EXPECTED_ARTIFACT_ID}/zip",
        "receive-zip",
        "verify-download",
    )
    if all(token in download_helper for token in download_order_tokens):
        require(
            all(
                download_helper.index(left) < download_helper.index(right)
                for left, right in zip(
                    download_order_tokens,
                    download_order_tokens[1:],
                )
            ),
            "provider metadata preflight/download order changed",
        )
    for required in (
        "def verify_download",
        "def verify_transfer",
        "safe_extract_provider_zip",
        "parse_constant=reject_non_finite_json_constant",
        "parse_float=parse_finite_json_float",
        "validate_provider_metadata_preflight",
        "validate_downloaded_provider_zip",
        "receive_provider_zip",
        "provider receive exceeds declared size",
        "provider artifact digest changed",
        "provider artifact ZIP size changed",
        "authenticated_provider_api",
        "verify-transfer",
        "expected-receipt-sha256",
        "split_provider_zip",
        "reassemble_provider_zip",
        "TRANSPORT_PART_BYTES",
        "MAXIMUM_TRANSPORT_PARTS",
        "MAXIMUM_ARTIFACT_INPUT_BYTES",
        "MAXIMUM_PROVIDER_ARTIFACT_BYTES",
    ):
        require(
            required in provider_download_verifier,
            f"provider download verifier missing: {required}",
        )
    if (
        "def verify_download" in provider_download_verifier
        and "def verify_transfer" in provider_download_verifier
    ):
        verify_download_block = provider_download_verifier.split(
            "def verify_download",
            1,
        )[1].split("def verify_transfer", 1)[0]
        verification_order_tokens = (
            "validate_provider_metadata_preflight",
            "validate_downloaded_provider_zip",
            "safe_extract_provider_zip",
        )
        if all(
            token in verify_download_block
            for token in verification_order_tokens
        ):
            require(
                all(
                    verify_download_block.index(left)
                    < verify_download_block.index(right)
                    for left, right in zip(
                        verification_order_tokens,
                        verification_order_tokens[1:],
                    )
                ),
                "provider validation/extraction order changed",
            )

    for label, script_bytes in (
        ("export helper", export_helper_bytes),
        ("import helper", import_helper_bytes),
        ("download helper", download_helper_bytes),
    ):
        syntax = subprocess.run(
            ["bash", "-n"],
            input=script_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        require(syntax.returncode == 0, f"{label} shell syntax invalid")
    errors.extend(_validate_exact_prefix())
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
            "ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "CONSUMED_OR_INVALID"
    return "PREPARED_NOT_TRIGGERED"


def plan_state() -> str:
    base_errors = validate_plan(verify_active_git_state=False)
    try:
        additions = _request_additions()
    except (OSError, subprocess.CalledProcessError):
        return "INVALID"
    active_git_errors: list[str] = []
    if ACTIVE_REQUEST_PATH.exists():
        try:
            active_git_errors = _validate_active_request(
                ACTIVE_REQUEST_PATH.read_bytes(),
                REQUEST_TEMPLATE_PATH.read_bytes(),
                plan_parent=None,
                verify_git_state=True,
            )
        except OSError as exc:
            active_git_errors = [f"cannot load active request: {exc}"]
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
    print(
        "PASS: exact 5335 dependency-only BuildKit cache plan is fail-closed; "
        f"state={plan_state()}; registry_publication_authorized=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
