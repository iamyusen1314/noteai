#!/usr/bin/env python3
"""Verify the inert, append-only V10 Admin dependency-cache recovery plan."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import verify_admin_dependency_cache_export_plan_v9 as v9_plan
import verify_admin_dependency_cache_v9_failure_evidence as v9_failure


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v10.yml"
)
TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v10.json"
)
ACTIVE_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v10.json"
)
SOURCE_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "cache_observer_projection.json"
)
BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v10.py"
)
IMPORT_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "import_admin_dependency_cache_v10.sh"
)
V9_IMPORT_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "import_admin_dependency_cache.sh"
)
EXPORT_HELPER_PATH = (
    ROOT / "scripts" / "ci" / "export_admin_dependency_cache.sh"
)
V9_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v9.yml"
)
V9_TEMPLATE_PATH = (
    ROOT
    / "deploy"
    / "production"
    / "plans"
    / "admin-dependency-cache-export-request-v9.json"
)
V9_REQUEST_PATH = (
    ROOT
    / ".github"
    / "release-requests"
    / "admin-5335bda-dependency-cache-v9.json"
)
V9_PLAN_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_export_plan_v9.py"
)
V9_BUNDLE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_bundle_v9.py"
)
V9_FAILURE_EVIDENCE_PATH = v9_failure.EVIDENCE_PATH
V9_FAILURE_VERIFIER_PATH = (
    ROOT / "tools" / "verify_admin_dependency_cache_v9_failure_evidence.py"
)

WORKFLOW_SHA256 = (
    "fd9570833c35aa3fc0d8632d26d68cca9ef33e960c26c4f4410eaaa6f7572d96"
)
TEMPLATE_SHA256 = (
    "2ac7f6ed83be057ffc79ca349888e8691d9324f3474942fe65571055e59c8bcc"
)
SOURCE_FIXTURE_SHA256 = (
    "f743084bb704d0fd6858510d81ebe6479ac0c6baae982b353715c328bc6fcd27"
)
BUNDLE_VERIFIER_SHA256 = (
    "77c2410406448998c81d09b04d93d12db1cb3a4a032a0b78d9fc25626014758f"
)
V9_WORKFLOW_SHA256 = (
    "ece8eb8e9c9d8a8997faa838c87a3a06a407bc3382670bf8f294433982e62f34"
)
V9_TEMPLATE_SHA256 = (
    "ae5114d66eb2aedd4db875b857974b0631caa1a39ad75a16e22ccbaecc424a3b"
)
V9_REQUEST_SHA256 = (
    "57c1506bb6e483e2e9f74e510847e278dbe336869cdc113ecc0230aebabd07d6"
)
V9_PLAN_VERIFIER_SHA256 = (
    "d3d4b32d3a2f98b4311d1576e7c69446b9e95cbd1e92a85b7562fe9a4d7bb0d0"
)
V9_BUNDLE_VERIFIER_SHA256 = (
    "a69103e899dc74b4d34e4837e29f40284be9b252281fed262a2dd1afee3d6032"
)
V9_FAILURE_EVIDENCE_SHA256 = (
    "3769b30bd827adce9bb2e28b258991b5202e1fc8214a1b8428705e852d2b8fa5"
)
V9_FAILURE_EVIDENCE_SEMANTIC_SHA256 = (
    "144200468493e909301ad7d9edb88403f060d5092a445ab8692c6481b166db01"
)
V9_FAILURE_VERIFIER_SHA256 = (
    "0db0086f120ade148bafc30b6de143c28d8cd3e37ec216c055280b1196586743"
)
IMPORT_HELPER_SHA256 = (
    "d8388ff776290b05aa699f3a09363fc2087c3b8bd5ada23b556d6cb14953b85f"
)
V9_IMPORT_HELPER_SHA256 = (
    "c4986143d5897140f72ad6835b44f7fc989830a30341cb4e3f5718fced3ca777"
)
EXPORT_HELPER_SHA256 = (
    "fabcdc2245c537c2fd56e88b6e0aced77d5c26234fc74d7d934b11ecda8d860c"
)
PRODUCER_BUILD_PROJECTION_SHA256 = (
    "3bf91abec518226459e46cb936eee0950b404720ee21071362630b2c21fc95b0"
)
FULL_REPLAY_PROJECTION_SHA256 = (
    "2715041a8cb52c6c5d5cfa70fd80fb6656086e759bbd1d431851cb113b561c50"
)
V9_PLAN_PARENT = "c2aebc9bdae9cc26c6c29d994bf55b547349e231"
V9_CONTROL_COMMIT = "fbe629daad669191d4ea9903ffb488c98055f000"
V9_TERMINAL_CHECKPOINT = "0e35e7dca22064402f8a7b569c6b966e4c6ec1a3"
V9_TERMINAL_RECEIPT = "512638647c5851aa3258cd472da42894110465af"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_WORKFLOW_HEADER = """name: Admin dependency cache export V10

on:
  push:
    branches:
      - codex/quality-stabilization-real-chain
    paths:
      - .github/release-requests/admin-5335bda-dependency-cache-v10.json
"""
EXPECTED_TEMPLATE: dict[str, Any] = json.loads(
    TEMPLATE_PATH.read_text(encoding="utf-8")
)
FROZEN_ACTIVATION_FILES = (
    (WORKFLOW_PATH.relative_to(ROOT), WORKFLOW_SHA256),
    (TEMPLATE_PATH.relative_to(ROOT), TEMPLATE_SHA256),
    (SOURCE_FIXTURE_PATH.relative_to(ROOT), SOURCE_FIXTURE_SHA256),
    (BUNDLE_VERIFIER_PATH.relative_to(ROOT), BUNDLE_VERIFIER_SHA256),
    (IMPORT_HELPER_PATH.relative_to(ROOT), IMPORT_HELPER_SHA256),
)
LEGACY_PLAN_MODULES = (
    v9_plan,
    v9_plan.v8_plan,
    v9_plan.v8_plan.v7_plan,
    v9_plan.v8_plan.v7_plan.v6_plan,
    v9_plan.v8_plan.v7_plan.v6_plan.v5_plan,
    v9_plan.v8_plan.v7_plan.v6_plan.v5_plan.v4_plan,
    v9_plan.v8_plan.v7_plan.v6_plan.v5_plan.v4_plan.v3_plan,
)


def _repo_relative_path(value: Path | str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.relative_to(ROOT)
    if ".." in path.parts:
        raise ValueError("legacy frozen path escapes repository")
    return path


def _legacy_frozen_paths() -> tuple[Path, ...]:
    paths = {
        _repo_relative_path(module.__file__) for module in LEGACY_PLAN_MODULES
    }
    for module in LEGACY_PLAN_MODULES:
        paths.update(
            _repo_relative_path(value)
            for name, value in vars(module).items()
            if name.endswith("_PATH") and isinstance(value, Path)
        )
    paths.update(_repo_relative_path(path) for path in v9_failure.FROZEN_PATHS)
    paths.update(
        {
            _repo_relative_path(v9_failure.EVIDENCE_PATH),
            _repo_relative_path(v9_failure.REQUEST_PATH),
            _repo_relative_path(V9_FAILURE_VERIFIER_PATH),
        }
    )
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


LEGACY_FROZEN_PATHS = _legacy_frozen_paths()


def _workflow_literal_path_array(workflow: str, name: str) -> tuple[Path, ...]:
    lines = workflow.splitlines()
    opener = f"          {name}=("
    if lines.count(opener) != 1:
        raise ValueError(f"V10 workflow {name} declaration changed")
    start = lines.index(opener) + 1
    try:
        end = lines.index("          )", start)
    except ValueError as exc:
        raise ValueError(f"V10 workflow {name} terminator changed") from exc
    paths: list[Path] = []
    for line in lines[start:end]:
        match = re.fullmatch(r'            "([^"$`\\]+)"', line)
        if match is None:
            raise ValueError(f"V10 workflow {name} entry is not literal")
        value = match.group(1)
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError(f"V10 workflow {name} entry is not repository-relative")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise ValueError(f"V10 workflow {name} contains duplicates")
    return tuple(paths)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _replace_once(value: bytes, old: bytes, new: bytes, label: str) -> bytes:
    if value.count(old) != 1:
        raise ValueError(f"frozen V9 import helper {label} changed")
    return value.replace(old, new, 1)


def expected_v10_import_helper(v9_bytes: bytes) -> bytes:
    """Apply the only reviewed V9-to-V10 helper byte changes."""
    result = _replace_once(
        v9_bytes,
        b"# Validate, import and replay the exact-5335 dependency-only BuildKit cache.\n",
        (
            b"# V10 validates an imported cache through a consumer-only "
            b"zero-network observer.\n"
            b"# The producer prefix and full replay remain byte-for-byte frozen.\n"
            b"# Validate, import and replay the exact-5335 dependency-only "
            b"BuildKit cache.\n"
        ),
        "header",
    )
    result = _replace_once(
        result,
        (
            b'expected_prefix="93fd024e5af678b7885bcab8e72d980a'
            b'9f92cfc70de4f2fd2870284e25b8ec1e"\n'
        ),
        (
            b'expected_prefix="93fd024e5af678b7885bcab8e72d980a'
            b'9f92cfc70de4f2fd2870284e25b8ec1e"\n'
            b'expected_observer_prefix="8a2692fb460557e0159bc9e000364b51'
            b'5ce80aaf08eeeb186bf4930ce6357068"\n'
        ),
        "observer hash",
    )
    result = _replace_once(
        result,
        (
            b'check_sha256 "${expected_prefix}" "${prefix_dockerfile}"\n'
            b'test "$(sed -n \'81p\' "${NOTEAI_SOURCE_DIR}/Dockerfile")" = ""\n'
        ),
        (
            b'check_sha256 "${expected_prefix}" "${prefix_dockerfile}"\n'
            b"printf '%s\\n' \\\n"
            b'  "" \\\n'
            b'  "FROM runtime-common AS noteai-cache-observer" \\\n'
            b'  "RUN --network=none printf \'%s\\\\n\' noteai-cache-observer-v10" \\\n'
            b'  >> "${prefix_dockerfile}"\n'
            b'check_sha256 "${expected_observer_prefix}" "${prefix_dockerfile}"\n'
            b'test "$(wc -c < "${prefix_dockerfile}" | tr -d \' \')" = "5062"\n'
            b'test "$(wc -l < "${prefix_dockerfile}" | tr -d \' \')" = "83"\n'
            b'test "$(sed -n \'81p\' "${NOTEAI_SOURCE_DIR}/Dockerfile")" = ""\n'
        ),
        "observer derivation",
    )
    import_block = (
        b'    --target runtime-common \\\n'
        b'    --build-arg "NOTEAI_OCI_REVISION=${expected_release}" \\\n'
        b'    --build-arg "NOTEAI_OCI_SOURCE=${expected_source}" \\\n'
        b'    --build-arg "NOTEAI_OCI_VERSION=${expected_version}" \\\n'
        b'    --build-arg "NOTEAI_OCI_CREATED=${expected_created}" \\\n'
        b'    --cache-from "type=local,src=${cache_dir}" \\\n'
    )
    result = _replace_once(
        result,
        import_block,
        import_block.replace(
            b"--target runtime-common",
            b"--target noteai-cache-observer",
            1,
        ),
        "observer target",
    )
    return result


def _producer_build_projection(export_bytes: bytes) -> bytes:
    start = export_bytes.index(b"if ! docker buildx --builder")
    end = export_bytes.index(b"\nthen", start)
    return export_bytes[start : end + 1]


def _full_replay_projection(import_bytes: bytes) -> bytes:
    start = import_bytes.index(b"replay_metadata=")
    end = import_bytes.index(b'\nmanifest="', start)
    return import_bytes[start:end]


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
    return v9_plan._strict_json(value)


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
        "--full-history",
        "-m",
        "--no-renames",
        "--diff-filter=A",
        "--format=%H",
        "--",
        str(relative),
    )
    additions: list[str] = []
    for line in output.splitlines():
        if line and line not in additions:
            additions.append(line)
    return additions


def _validate_legacy_frozen_history(
    *,
    root: Path = ROOT,
    anchor: str = V9_TERMINAL_RECEIPT,
    frozen_paths: tuple[Path, ...] = LEGACY_FROZEN_PATHS,
) -> list[str]:
    errors: list[str] = []
    try:
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", anchor, "HEAD"],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).returncode != 0:
            return ["V9 terminal receipt is not an ancestor"]
        history = _git_at(
            root,
            "log",
            "--full-history",
            "-m",
            "--no-renames",
            "--format=%H",
            f"{anchor}..HEAD",
            "--",
            *(path.as_posix() for path in frozen_paths),
        )
        if history:
            errors.append("V2-V9 frozen authority changed after terminal receipt")
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V2-V9 frozen history: {exc}")
    return errors


def _validate_v10_worktree_files(
    *,
    root: Path = ROOT,
    frozen_files: tuple[tuple[Path, str], ...] = FROZEN_ACTIVATION_FILES,
) -> list[str]:
    errors: list[str] = []
    for relative, expected_sha256 in frozen_files:
        local_path = root / relative
        try:
            if not stat.S_ISREG(local_path.lstat().st_mode):
                errors.append(f"V10 frozen worktree file is not regular: {relative}")
        except OSError as exc:
            errors.append(f"cannot stat V10 frozen worktree file {relative}: {exc}")
            continue
        try:
            entry = _git_at(root, "ls-tree", "HEAD", "--", str(relative)).split()
            if not entry:
                continue
            if len(entry) < 3 or entry[:2] != ["100644", "blob"]:
                errors.append(f"V10 frozen HEAD file mode changed: {relative}")
                continue
            head_bytes = subprocess.run(
                ["git", "show", f"HEAD:{relative}"],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            if sha256_bytes(head_bytes) != expected_sha256:
                errors.append(f"V10 frozen HEAD file hash drift: {relative}")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify V10 frozen HEAD file {relative}: {exc}")
    return errors


def _load_active_request(
    path: Path | None = None,
) -> tuple[bool, bytes | None, list[str]]:
    path = ACTIVE_REQUEST_PATH if path is None else path
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False, None, []
    except OSError as exc:
        return True, None, [f"cannot stat V10 active request: {exc}"]
    if not stat.S_ISREG(mode):
        return True, None, ["V10 active request worktree file is not regular"]
    try:
        return True, path.read_bytes(), []
    except OSError as exc:
        return True, None, [f"cannot load V10 active request: {exc}"]


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
        return [f"invalid V10 active request: {exc}"]
    parent = request.get("plan_checkpoint_commit")
    if not isinstance(parent, str) or COMMIT_RE.fullmatch(parent) is None:
        return ["V10 active request checkpoint is invalid"]
    if plan_parent is not None and parent != plan_parent:
        errors.append("V10 active request does not bind its direct parent")
    expected_bytes = template_bytes.replace(
        b"__DIRECT_PARENT_COMMIT__",
        parent.encode("ascii"),
    )
    if request_bytes != expected_bytes:
        errors.append("V10 active request differs from reviewed template")
    expected = dict(template)
    expected["plan_checkpoint_commit"] = parent
    if request != expected:
        errors.append("V10 active request semantics drift")

    if not verify_git_state:
        return errors

    relative = (
        ACTIVE_REQUEST_PATH.relative_to(ROOT)
        if request_path is None
        else request_path
    )
    try:
        if not stat.S_ISREG((root / relative).lstat().st_mode):
            errors.append("V10 active request worktree file is not regular")
        additions = _request_additions(root=root, request_path=relative)
        if len(additions) != 1:
            return errors + ["V10 active request addition history is not unique"]
        activation = additions[0]
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", activation, "HEAD"],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).returncode != 0:
            errors.append("V10 activation is not an ancestor of HEAD")
        parent_record = _git_at(
            root,
            "rev-list",
            "--parents",
            "-n",
            "1",
            activation,
        ).split()
        if len(parent_record) != 2:
            return errors + ["V10 controller is not single-parent"]
        activation_parent = parent_record[1]
        if activation_parent != parent:
            errors.append("V10 request checkpoint differs from controller parent")
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
            errors.append("V10 activation changes more than its request")
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
            errors.append("V10 request was not a unique addition")
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
            errors.append("V10 request activation mode is not 100644")
        activation_bytes = subprocess.run(
            ["git", "show", f"{activation}:{relative}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if activation_bytes != request_bytes:
            errors.append("V10 request activation bytes differ from reviewed request")

        request_history = _git_at(
            root,
            "log",
            "--full-history",
            "-m",
            "--format=%H",
            f"{activation}..HEAD",
            "--",
            str(relative),
        )
        if request_history:
            errors.append("V10 request changed after activation")

        frozen_anchors: list[str] = []
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
                    f"V10 activation frozen file mode changed: {frozen_relative}"
                )
                continue
            if parent_entry[2] != frozen_activation_entry[2]:
                errors.append(
                    f"V10 activation frozen file blob changed: {frozen_relative}"
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
                    f"V10 activation frozen file hash drift: {frozen_relative}"
                )

            frozen_additions = _request_additions(
                root=root,
                request_path=frozen_relative,
            )
            if len(frozen_additions) != 1:
                errors.append(
                    "V10 frozen activation file addition history is not unique: "
                    f"{frozen_relative}"
                )
                continue
            frozen_anchor = frozen_additions[0]
            frozen_anchors.append(frozen_anchor)
            if subprocess.run(
                [
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    frozen_anchor,
                    activation_parent,
                ],
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).returncode != 0:
                errors.append(
                    "V10 frozen activation file anchor is not an ancestor of "
                    f"the controller parent: {frozen_relative}"
                )
                continue
            frozen_history_from_anchor = _git_at(
                root,
                "log",
                "--full-history",
                "-m",
                "--no-renames",
                "--format=%H",
                f"{frozen_anchor}..HEAD",
                "--",
                str(frozen_relative),
            )
            if frozen_history_from_anchor:
                errors.append(
                    "V10 frozen activation file changed after its addition: "
                    f"{frozen_relative}"
                )

        if (
            len(frozen_anchors) == len(FROZEN_ACTIVATION_FILES)
            and len(set(frozen_anchors)) != 1
        ):
            errors.append("V10 frozen activation files have different add anchors")
        elif len(frozen_anchors) == len(FROZEN_ACTIVATION_FILES):
            frozen_anchor_record = _git_at(
                root,
                "rev-list",
                "--parents",
                "-n",
                "1",
                frozen_anchors[0],
            ).split()
            if len(frozen_anchor_record) != 2:
                errors.append("V10 frozen activation anchor is not single-parent")

        frozen_history = _git_at(
            root,
            "log",
            "--full-history",
            "-m",
            "--format=%H",
            f"{activation}..HEAD",
            "--",
            *(str(relative) for relative, _sha256 in FROZEN_ACTIVATION_FILES),
        )
        if frozen_history:
            errors.append("V10 frozen activation files changed after activation")

        mode = _git_at(root, "ls-tree", "HEAD", "--", str(relative)).split()
        if len(mode) < 3 or mode[:2] != ["100644", "blob"]:
            errors.append("V10 request is not retained as 100644")
        current = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        if current != request_bytes:
            errors.append("V10 request bytes changed after activation")
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"cannot verify V10 active request Git state: {exc}")
    return errors


def validate_plan(
    *,
    workflow_bytes: bytes | None = None,
    template_bytes: bytes | None = None,
    source_fixture_bytes: bytes | None = None,
    bundle_verifier_bytes: bytes | None = None,
    import_helper_bytes: bytes | None = None,
    v9_import_helper_bytes: bytes | None = None,
    export_helper_bytes: bytes | None = None,
    active_request_bytes: bytes | None = None,
    active_plan_parent: str | None = None,
    verify_git_state: bool = True,
) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    active_supplied = active_request_bytes is not None
    active_present = False
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
        import_helper_bytes = (
            IMPORT_HELPER_PATH.read_bytes()
            if import_helper_bytes is None
            else import_helper_bytes
        )
        v9_import_helper_bytes = (
            V9_IMPORT_HELPER_PATH.read_bytes()
            if v9_import_helper_bytes is None
            else v9_import_helper_bytes
        )
        export_helper_bytes = (
            EXPORT_HELPER_PATH.read_bytes()
            if export_helper_bytes is None
            else export_helper_bytes
        )
    except OSError as exc:
        return [f"cannot load V10 dependency-cache plan: {exc}"]
    if not active_supplied:
        active_present, loaded_request, load_errors = _load_active_request()
        errors.extend(load_errors)
        if loaded_request is not None:
            active_request_bytes = loaded_request

    fixed_paths = (
        (workflow_bytes, WORKFLOW_SHA256, "V10 workflow"),
        (template_bytes, TEMPLATE_SHA256, "V10 template"),
        (
            source_fixture_bytes,
            SOURCE_FIXTURE_SHA256,
            "V10 input-omission source fixture",
        ),
        (
            bundle_verifier_bytes,
            BUNDLE_VERIFIER_SHA256,
            "V10 bundle verifier",
        ),
        (
            import_helper_bytes,
            IMPORT_HELPER_SHA256,
            "V10 import helper",
        ),
        (
            v9_import_helper_bytes,
            V9_IMPORT_HELPER_SHA256,
            "frozen V9 import helper",
        ),
        (
            export_helper_bytes,
            EXPORT_HELPER_SHA256,
            "frozen producer export helper",
        ),
        (
            V9_WORKFLOW_PATH.read_bytes(),
            V9_WORKFLOW_SHA256,
            "frozen V9 workflow",
        ),
        (
            V9_TEMPLATE_PATH.read_bytes(),
            V9_TEMPLATE_SHA256,
            "frozen V9 template",
        ),
        (
            V9_REQUEST_PATH.read_bytes(),
            V9_REQUEST_SHA256,
            "frozen V9 request",
        ),
        (
            V9_PLAN_VERIFIER_PATH.read_bytes(),
            V9_PLAN_VERIFIER_SHA256,
            "frozen V9 plan verifier",
        ),
        (
            V9_BUNDLE_VERIFIER_PATH.read_bytes(),
            V9_BUNDLE_VERIFIER_SHA256,
            "frozen V9 bundle verifier",
        ),
        (
            V9_FAILURE_EVIDENCE_PATH.read_bytes(),
            V9_FAILURE_EVIDENCE_SHA256,
            "V9 terminal evidence",
        ),
        (
            V9_FAILURE_VERIFIER_PATH.read_bytes(),
            V9_FAILURE_VERIFIER_SHA256,
            "V9 terminal evidence verifier",
        ),
    )
    for actual, expected, label in fixed_paths:
        require(sha256_bytes(actual) == expected, f"{label} hash drift")
    try:
        require(
            expected_v10_import_helper(v9_import_helper_bytes)
            == import_helper_bytes,
            "V10 import helper differs from the allowlisted V9 delta",
        )
        require(
            sha256_bytes(_producer_build_projection(export_helper_bytes))
            == PRODUCER_BUILD_PROJECTION_SHA256,
            "frozen producer build command projection changed",
        )
        require(
            sha256_bytes(_full_replay_projection(import_helper_bytes))
            == FULL_REPLAY_PROJECTION_SHA256,
            "V10 full replay projection changed",
        )
        require(
            _full_replay_projection(import_helper_bytes)
            == _full_replay_projection(v9_import_helper_bytes),
            "V10 full replay differs from frozen V9",
        )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        template = _strict_json(template_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V10 request template: {exc}")
        template = {}
    require(template == EXPECTED_TEMPLATE, "V10 request template drift")
    require(
        template_bytes.count(b"__DIRECT_PARENT_COMMIT__") == 1,
        "V10 request parent placeholder count changed",
    )
    predecessor = template.get("predecessor", {})
    recovery = template.get("recovery_basis", {})
    verifier_chain = template.get("bundle_verifier_chain", {})
    evidence = template.get("build_evidence_recovery", {})
    require(
        template.get("schema_version") == 10
        and template.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and template.get("release_commit") == RELEASE_COMMIT
        and template.get("plan_checkpoint_commit")
        == "__DIRECT_PARENT_COMMIT__"
        and template.get("release_scope")
        == "admin_dependency_prefix_cache_recovery"
        and template.get("trigger_mode") == "one_shot_added_request_v10",
        "V10 request identity changed",
    )
    require(
        predecessor
        == {
            "control_commit": V9_CONTROL_COMMIT,
            "direct_parent_commit": V9_PLAN_PARENT,
            "terminal_checkpoint_commit": V9_TERMINAL_CHECKPOINT,
            "terminal_receipt_commit": V9_TERMINAL_RECEIPT,
            "workflow_id": 324655362,
            "run_id": 30651679657,
            "job_id": 91226182660,
            "run_attempt": 1,
            "conclusion": "failure",
            "artifact_count": 0,
            "rerun_count": 0,
            "rerun_authorized": False,
            "request_sha256": V9_REQUEST_SHA256,
            "failure_evidence_sha256": V9_FAILURE_EVIDENCE_SHA256,
            "failure_evidence_semantic_sha256": (
                V9_FAILURE_EVIDENCE_SEMANTIC_SHA256
            ),
            "failure_verifier_sha256": V9_FAILURE_VERIFIER_SHA256,
        },
        "V10 predecessor terminal semantics changed",
    )
    require(
        recovery.get("cache_observer_source_projection_sha256")
        == SOURCE_FIXTURE_SHA256
        and recovery.get("base_dependency_prefix_sha256")
        == "93fd024e5af678b7885bcab8e72d980a9f92cfc70de4f2fd2870284e25b8ec1e"
        and recovery.get("observer_suffix_sha256")
        == "7cdfa59482f73d3274bc6080468671aeb42f5e45f5b6c868d52f13e8ee7c5266"
        and recovery.get("observer_prefix_sha256")
        == "8a2692fb460557e0159bc9e000364b515ce80aaf08eeeb186bf4930ce6357068"
        and recovery.get("observer_target") == "noteai-cache-observer"
        and recovery.get("observer_run_start_line") == 83
        and recovery.get("observer_network_mode") == "NONE"
        and recovery.get("observer_network_enum") == 2
        and recovery.get("producer_build_command_projection_sha256")
        == PRODUCER_BUILD_PROJECTION_SHA256
        and recovery.get("v10_import_helper_sha256")
        == IMPORT_HELPER_SHA256
        and recovery.get("full_replay_block_projection_sha256")
        == FULL_REPLAY_PROJECTION_SHA256
        and recovery.get("producer_contains_observer") is False
        and recovery.get("full_replay_contains_observer") is False
        and recovery.get("no_cache_filter_authorized") is False
        and recovery.get("dependency_cache_predicate_relaxed") is False
        and recovery.get("github_actions_provenance_injection_authorized")
        is False
        and recovery.get("buildkit_auth_behavior")
        == "ordinary_credentials_only",
        "V10 observer recovery basis changed",
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
            "v8_sha256": (
                "b07f9dee54862969fe90ef438c357a3445a9fe9574b69a9f87440e3ed9920300"
            ),
            "v9_sha256": V9_BUNDLE_VERIFIER_SHA256,
            "v10_sha256": BUNDLE_VERIFIER_SHA256,
        },
        "V10 bundle verifier chain changed",
    )
    require(
        evidence.get("frozen_v9_delegate_required") is True
        and evidence.get("producer_prefix_bytes_unchanged") is True
        and evidence.get("producer_target_runtime_common_unchanged")
        is True
        and evidence.get("consumer_only_observer_required") is True
        and evidence.get("observer_direct_parent_runtime_pip_required")
        is True
        and evidence.get("observer_provenance_network_none_required")
        is True
        and evidence.get("observer_progress_parent_binding_required")
        is True
        and evidence.get("observer_completed_uncached_required") is True
        and evidence.get(
            "observer_decoded_stdout_marker_exact_once_required"
        )
        is True
        and evidence.get(
            "all_dependency_role_intervals_cached_required_on_replay"
        )
        is True
        and evidence.get(
            "all_dependency_role_intervals_noncached_required_on_producer"
        )
        is True
        and evidence.get(
            "latest_interval_only_cache_acceptance_allowed"
        )
        is False
        and evidence.get("runtime_pip_cached_false_accepted") is False
        and evidence.get(
            "full_replay_original_dockerfile_and_target_required"
        )
        is True
        and evidence.get(
            "full_replay_post_pip_witness_completed_uncached_required"
        )
        is True
        and evidence.get("original_metadata_and_progress_sha256_required")
        is True
        and evidence.get(
            "compatibility_evidence_persistence_authorized"
        )
        is False
        and evidence.get("v9_dynamic_metadata_retained") is False
        and evidence.get("v9_dynamic_progress_retained") is False
        and evidence.get("v9_root_cause_reconstructed") is False
        and evidence.get("historical_v9_root_cause_status")
        == "UNKNOWN_NOT_RETAINED",
        "V10 build-evidence recovery contract changed",
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
        "V10 bounded authorization contract changed",
    )

    try:
        fixture = _strict_json(source_fixture_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid V10 source fixture: {exc}")
        fixture = {}
    contract = fixture.get("v10_contract", {})
    observer = fixture.get("observer_dockerfile", {})
    replay = fixture.get("full_replay", {})
    sources = fixture.get("buildkit", {}).get("sources", [])
    require(
        fixture.get("classification")
        == (
            "SOURCE_PROVEN_CACHE_OBSERVER_CHILD_CONTRACT_"
            "NOT_V9_RUNTIME_EVIDENCE"
        )
        and fixture.get("actual_v9_runtime_metadata_retained") is False
        and fixture.get("actual_v9_runtime_progress_retained") is False
        and fixture.get("actual_v9_runtime_role_digest_retained") is False
        and fixture.get("runtime_v9_cache_miss_cause_reconstructed")
        is False
        and fixture.get("historical_v9_root_cause_status")
        == "UNKNOWN_NOT_RETAINED"
        and fixture.get("buildkit", {}).get("commit")
        == "e42e1bfd389af7203238cce77b1f7dad447285e9"
        and [item.get("path") for item in sources]
        == [
            "client/graph.go",
            "solver/progress.go",
            "solver/jobs.go",
            "solver/llbsolver/provenance/buildconfig.go",
            "solver/pb/ops.proto",
        ]
        and contract.get("producer_dependency_prefix_bytes_unchanged")
        is True
        and contract.get("producer_cache_contains_observer") is False
        and contract.get("consumer_only_observer_required") is True
        and contract.get("observer_direct_parent_runtime_pip_required")
        is True
        and contract.get("observer_network_none_enum_required") == 2
        and contract.get("observer_completed_uncached_required") is True
        and contract.get(
            "observer_decoded_log_marker_exact_once_required"
        )
        is True
        and contract.get("dependency_cache_predicate_relaxed") is False
        and contract.get("runtime_pip_cached_false_accepted") is False
        and contract.get("v9_dynamic_root_cause_reconstructed") is False
        and observer.get("base_prefix_sha256")
        == "93fd024e5af678b7885bcab8e72d980a9f92cfc70de4f2fd2870284e25b8ec1e"
        and observer.get("suffix_sha256")
        == "7cdfa59482f73d3274bc6080468671aeb42f5e45f5b6c868d52f13e8ee7c5266"
        and observer.get("derived_sha256")
        == "8a2692fb460557e0159bc9e000364b515ce80aaf08eeeb186bf4930ce6357068"
        and observer.get("target") == "noteai-cache-observer"
        and observer.get("run_start_line") == 83
        and replay.get("target") == "runtime-common"
        and replay.get("cache_from_local") is False
        and replay.get("post_runtime_pip_witness_start_line") == 93,
        "V10 cache-observer source projection changed",
    )

    workflow = workflow_bytes.decode("utf-8", errors="replace")
    bundle = bundle_verifier_bytes.decode("utf-8", errors="replace")
    try:
        require(
            _workflow_literal_path_array(workflow, "legacy_frozen_paths")
            == LEGACY_FROZEN_PATHS,
            "V10 workflow legacy frozen authority set changed",
        )
        require(
            _workflow_literal_path_array(workflow, "v10_frozen_paths")
            == tuple(path for path, _sha256 in FROZEN_ACTIVATION_FILES),
            "V10 workflow runtime frozen authority set changed",
        )
    except ValueError as exc:
        errors.append(str(exc))
    for forbidden in (
        "workflow_dispatch:",
        "pull_request:",
        "schedule:",
        "repository_dispatch:",
        "permissions: write",
        "actions: write",
        '--data-urlencode "branch=',
        '--data-urlencode "event=',
        '--data-urlencode "head_sha=',
        '--data-urlencode "exclude_pull_requests=',
        "docker login",
        "docker push",
        "kubectl ",
        "psql ",
        "NOTEAI_V10_PLAN_VERIFIER_PATH",
    ):
        require(forbidden not in workflow, f"V10 workflow forbidden token: {forbidden}")
    require(
        workflow.split("\npermissions:", 1)[0] == EXPECTED_WORKFLOW_HEADER,
        "V10 trigger block changed",
    )
    for required in (
        "permissions:\n  contents: read",
        "  actions: read",
        "group: admin-dependency-cache-export-v10\n",
        "timeout-minutes: 120",
        'test "${GITHUB_RUN_ATTEMPT}" = "1"',
        "NOTEAI_V9_TERMINAL_RECEIPT",
        "NOTEAI_WORKFLOW_PATH",
        "NOTEAI_V10_CACHE_OBSERVER_SOURCE_PROJECTION_SHA256",
        "NOTEAI_V9_BUNDLE_VERIFIER_PATH",
        "git log --all --full-history -m --no-renames --diff-filter=A",
        "awk '!seen[$0]++'",
        "legacy_frozen_paths=(",
        "v10_frozen_paths=(",
        "v10_frozen_anchor_record",
        "Prove this is the unique V10 workflow run for the branch lifecycle",
        "NOTEAI_ACTIONS_READ_TOKEN: ${{ github.token }}",
        "/actions/workflows/admin-dependency-cache-export-v10.yml/runs",
        '--data-urlencode "per_page=100"',
        "NOTEAI_RUN_LEDGER_BUDGET_SECONDS: \"60\"",
        "NOTEAI_RUN_LEDGER_MAX_OBSERVATIONS: \"6\"",
        "NOTEAI_RUN_LEDGER_RETRY_MAXIMUM: \"2\"",
        "--connect-timeout",
        '"${NOTEAI_RUN_LEDGER_CONNECT_TIMEOUT_SECONDS}"',
        '--max-time "${ledger_call_timeout}"',
        '--retry-max-time "${ledger_call_timeout}"',
        "(( ledger_total <= 1 ))",
        'test "${ledger_lines}" = "${ledger_total}"',
        'test "${ledger_run_id}" = "${GITHUB_RUN_ID}"',
        'test "${ledger_verified}" = "true"',
        "v9_verifier_copy",
        "tools/verify_admin_dependency_cache_bundle_v10.py",
        "scripts/ci/import_admin_dependency_cache_v10.sh",
        ".import.v10_rawjson_diagnostic.observer_binding_completed",
        ".cacheless_replay.v10_rawjson_diagnostic.full_post_pip_witness",
        "retention-days: 1",
        "compression-level: 0",
        "admin-dependency-prefix-cache-5335bda-v2",
        "Remove V10 builders and all transient Docker state",
        "Upload one-day V10 public-repository dependency cache artifact",
        "Remove runner-local V10 bundle",
    ):
        require(required in workflow, f"V10 workflow contract missing: {required}")
    require(
        workflow.count("docker buildx create \\") == 2
        and workflow.count("--driver-opt ") == 4
        and workflow.count('--driver-opt "provenance-add-gha=false"') == 2,
        "V10 isolated builder contract changed",
    )
    require(
        workflow.count('test "${GITHUB_RUN_ATTEMPT}" = "1"') == 3
        and workflow.count("uses: actions/upload-artifact@") == 1
        and workflow.count("retention-days: 1") == 1,
        "V10 attempt or artifact bounds changed",
    )
    cleanup_position = workflow.find(
        "Remove V10 builders and all transient Docker state"
    )
    upload_position = workflow.find(
        "Upload one-day V10 public-repository dependency cache artifact"
    )
    local_removal_position = workflow.find("Remove runner-local V10 bundle")
    require(
        0 <= cleanup_position < upload_position < local_removal_position,
        "V10 cleanup/upload ordering changed",
    )
    for required in (
        "V9_VERIFIER_SHA256",
        "OBSERVER_SUFFIX",
        "OBSERVER_DOCKERFILE_SHA256",
        "_observer_validation",
        "_role_interval_projection",
        "_full_witness_validation",
        "_patched_v9_observer_contract",
        "FROZEN_V9_DISPATCH_CHANGED",
        "noteai_v10_progress_diagnostic=",
        "noteai.admin-dependency-cache-v10-diagnostic.v1",
    ):
        require(required in bundle, f"V10 bundle verifier contract missing: {required}")
    require(
        b"--target noteai-cache-observer" in import_helper_bytes
        and import_helper_bytes.count(b"--target runtime-common") == 1
        and import_helper_bytes.count(b"--cache-from") == 1
        and b"--no-cache-filter" not in import_helper_bytes
        and b"noteai-cache-observer" not in export_helper_bytes,
        "V10 helper observer isolation changed",
    )

    errors.extend(
        f"frozen V9 plan: {item}"
        for item in v9_plan.validate_plan(
            verify_git_state=verify_git_state,
        )
    )
    try:
        evidence_payload = v9_failure.load_strict()
        require(
            v9_failure.semantic_sha256(evidence_payload)
            == V9_FAILURE_EVIDENCE_SEMANTIC_SHA256,
            "V9 terminal evidence semantic hash drift",
        )
        errors.extend(
            f"V9 terminal evidence: {item}"
            for item in v9_failure.verify(
                evidence_payload,
                verify_git_state=verify_git_state,
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot verify V9 terminal evidence: {exc}")

    if verify_git_state:
        errors.extend(_validate_v10_worktree_files())
        errors.extend(_validate_legacy_frozen_history())
        try:
            require(
                v9_plan._request_additions() == [V9_CONTROL_COMMIT],
                "V9 request addition history changed",
            )
            require(
                _git("rev-list", "--parents", "-n", "1", V9_CONTROL_COMMIT)
                == f"{V9_CONTROL_COMMIT} {V9_PLAN_PARENT}",
                "V9 control parent changed",
            )
            require(
                _git(
                    "rev-list",
                    "--parents",
                    "-n",
                    "1",
                    V9_TERMINAL_CHECKPOINT,
                )
                == f"{V9_TERMINAL_CHECKPOINT} {V9_CONTROL_COMMIT}",
                "V9 terminal checkpoint parent changed",
            )
            require(
                _git(
                    "rev-list",
                    "--parents",
                    "-n",
                    "1",
                    V9_TERMINAL_RECEIPT,
                )
                == f"{V9_TERMINAL_RECEIPT} {V9_TERMINAL_CHECKPOINT}",
                "V9 terminal receipt parent changed",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify V9 terminal history: {exc}")

    if active_request_bytes is not None:
        errors.extend(
            _validate_active_request(
                active_request_bytes,
                template_bytes,
                plan_parent=active_plan_parent,
                verify_git_state=verify_git_state and not active_supplied,
            )
        )
    elif verify_git_state and not active_present:
        try:
            if _request_additions():
                errors.append("inactive V10 request has prior addition history")
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"cannot verify inactive V10 request history: {exc}")
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
            "V10_ARMED_OR_TRIGGERED_EXACT"
            if len(additions) == 1 and not active_git_errors
            else "INVALID"
        )
    if additions:
        return "V10_CONSUMED_OR_INVALID"
    return "PREPARED_V10_NOT_TRIGGERED"


def plan_state() -> str:
    base_errors = validate_plan(verify_git_state=False)
    active_exists, active_request_bytes, load_errors = _load_active_request()
    try:
        additions = _request_additions()
    except (OSError, subprocess.CalledProcessError):
        return "INVALID"
    active_git_errors: list[str] = list(load_errors)
    if active_request_bytes is not None:
        try:
            active_git_errors.extend(
                _validate_active_request(
                    active_request_bytes,
                    TEMPLATE_PATH.read_bytes(),
                    plan_parent=None,
                    verify_git_state=True,
                )
            )
        except OSError as exc:
            active_git_errors.append(f"cannot load V10 active request: {exc}")
    return classify_plan_state(
        plan_errors=base_errors,
        active_exists=active_exists,
        additions=additions,
        active_git_errors=active_git_errors,
    )


def main() -> int:
    errors = validate_plan()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"admin_dependency_cache_export_plan_v10=PASS state={plan_state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
