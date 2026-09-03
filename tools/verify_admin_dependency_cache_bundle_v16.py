#!/usr/bin/env python3
"""Validate the source-backed V16 BuildKit cache export successor.

V16 changes the operational main context from a per-solve local source to one
canonical, full-commit Git source.  It retains the frozen V13 cache and
rawjson predicates, then adds a fail-closed SourceOp -> requirements FileOp ->
runtime_pip ExecOp identity chain across producer, fresh consumer and the
same-consumer-builder replay after the external cache has been removed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


V13_VERIFIER_SHA256 = (
    "c9a0f130879f8381ea94584a600b3ee3"
    "88b91d380c079ec0b5efa145bff8b2d9"
)
SOURCE_IDENTITY_FIXTURE_SHA256 = (
    "2010890934f05c8ada09328c433962d5"
    "ae648346351accdeec62e1aafdb1f701"
)
MAXIMUM_SOURCE_BYTES = 4_194_304
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
RELEASE_TREE = "38e574e56406ba3380acb78edbe784508cc537cd"
GIT_CONTEXT_QUERY = (
    "https://github.com/iamyusen1314/noteai.git"
    f"?ref={RELEASE_COMMIT}&checksum={RELEASE_COMMIT}"
    "&submodules=false&mtime=commit&fetch-by-commit=true"
)
GIT_SOURCE_IDENTIFIER = (
    "git://github.com/iamyusen1314/noteai.git#" + RELEASE_COMMIT
)
GIT_SOURCE_ATTRS = {
    "git.authheadersecret": "GIT_AUTH_HEADER",
    "git.authtokensecret": "GIT_AUTH_TOKEN",
    "git.checksum": RELEASE_COMMIT,
    "git.fetchbycommit": "true",
    "git.fullurl": "https://github.com/iamyusen1314/noteai.git",
    "git.mtime": "commit",
    "git.skipsubmodules": "true",
}
GITATTRIBUTES_SHA256 = (
    "98faf6b3614dd8619b606b58c8052a2b"
    "5f699f3b37a3f1c23035c578a0e24eed"
)
REQUIREMENTS_COPY_LINE = 75
RUNTIME_PIP_LINE = 76
EXPECTED_COPY_ACTIONS = [
    {
        "input": 0,
        "secondaryInput": 1,
        "output": -1,
        "Action": {
            "copy": {
                "src": "/model/requirements.txt",
                "dest": "/app/",
                "mode": -1,
                "followSymlink": True,
                "dirCopyContents": True,
                "createDestPath": True,
                "allowWildcard": True,
                "allowEmptyWildcard": True,
                "timestamp": -1,
            }
        },
    },
    {
        "input": 2,
        "secondaryInput": 1,
        "output": 0,
        "Action": {
            "copy": {
                "src": "/model/requirements-api.txt",
                "dest": "/app/",
                "mode": -1,
                "followSymlink": True,
                "dirCopyContents": True,
                "createDestPath": True,
                "allowWildcard": True,
                "allowEmptyWildcard": True,
                "timestamp": -1,
            }
        },
    },
]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _read_frozen_source(path: Path, *, label: str) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{label} is missing") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAXIMUM_SOURCE_BYTES
        ):
            raise RuntimeError(f"{label} file contract changed")
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > MAXIMUM_SOURCE_BYTES:
                raise RuntimeError(f"{label} file contract changed")
        after = os.fstat(descriptor)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            or observed != before.st_size
        ):
            raise RuntimeError(f"{label} changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _load_v13_verifier():
    configured = os.environ.get("NOTEAI_V13_BUNDLE_VERIFIER_PATH")
    configured_path = (
        Path(configured)
        if configured
        else Path(__file__).with_name(
            "verify_admin_dependency_cache_bundle_v13.py"
        )
    )
    if configured_path.is_symlink():
        raise RuntimeError("frozen V13 bundle verifier file contract changed")
    path = configured_path.resolve()
    source = _read_frozen_source(path, label="frozen V13 bundle verifier")
    if hashlib.sha256(source).hexdigest() != V13_VERIFIER_SHA256:
        raise RuntimeError("frozen V13 bundle verifier hash drift")
    name = "_noteai_admin_dependency_cache_bundle_v13_for_v16"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


_v13 = _load_v13_verifier()
_base = _v13._base


class V16BundleError(_v13.V11BundleError):
    """A fixed-code V16 rejection safe for a public workflow log."""


def _fail(code: str, message: str) -> None:
    raise V16BundleError(code, message)


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        _fail(code, message)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path | None, payload: dict[str, Any]) -> None:
    try:
        _base.write_json(Path(path).resolve() if path else None, payload)
    except _v13._v10._v6._v3.BundleError as exc:
        _fail(
            getattr(exc, "failure_code", "V16_OUTPUT_INVALID"),
            "V16 output write failed",
        )


def _require_exact_dict(
    value: Any,
    keys: set[str],
    label: str,
    *,
    code: str = "V16_MANIFEST_INVALID",
) -> dict[str, Any]:
    _require(
        isinstance(value, dict) and set(value) == keys,
        code,
        f"{label} keys changed",
    )
    return value


def _require_sha256(value: Any, label: str) -> None:
    _require(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        "V16_MANIFEST_INVALID",
        f"{label} is invalid",
    )


def _require_positive_int(value: Any, label: str) -> None:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value > 0,
        "V16_MANIFEST_INVALID",
        f"{label} is invalid",
    )


def _read_summary_with_sha256(
    path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], str]:
    return _v13._read_summary_with_sha256(Path(path), label=label)


def _read_summary(path: Path, *, label: str) -> dict[str, Any]:
    return _v13._read_summary(Path(path), label=label)


def _all_intervals_cached(item: dict[str, Any]) -> bool:
    count = item.get("interval_count")
    return (
        isinstance(count, int)
        and not isinstance(count, bool)
        and count > 0
        and item.get("completed_interval_count") == count
        and item.get("cached_interval_count") == count
        and item.get("noncached_interval_count") == 0
    )


def _all_intervals_noncached(item: dict[str, Any]) -> bool:
    count = item.get("interval_count")
    return (
        isinstance(count, int)
        and not isinstance(count, bool)
        and count > 0
        and item.get("completed_interval_count") == count
        and item.get("cached_interval_count") == 0
        and item.get("noncached_interval_count") == count
    )


def _one_step_digest(
    step_to_digests: dict[str, list[str]],
    step_id: str,
    *,
    code: str,
    label: str,
) -> str:
    digests = step_to_digests.get(step_id, [])
    _require(
        len(digests) == 1
        and isinstance(digests[0], str)
        and DIGEST_RE.fullmatch(digests[0]) is not None,
        code,
        f"{label} digest binding changed",
    )
    return digests[0]


def _progress_input_projection(
    progress_bytes: bytes,
    *,
    child_digest: str,
    expected_parent_digests: list[str],
    label: str,
) -> dict[str, Any]:
    explicit = 0
    omitted = 0
    for line_number, raw_line in enumerate(progress_bytes.splitlines(), start=1):
        if not raw_line.strip():
            continue
        event = _v13._strict_json_bytes(
            raw_line,
            f"BuildKit rawjson line {line_number}",
        )
        vertexes = event.get("vertexes", []) if isinstance(event, dict) else []
        for vertex in vertexes:
            if not isinstance(vertex, dict) or vertex.get("digest") != child_digest:
                continue
            if "inputs" not in vertex:
                omitted += 1
                continue
            _require(
                vertex["inputs"] == expected_parent_digests,
                "V16_PROGRESS_INPUT_INVALID",
                f"{label} ordered progress inputs changed",
            )
            explicit += 1
    return {
        "explicit_input_update_count": explicit,
        "omitted_input_update_count": omitted,
        "explicit_ordered_inputs_observed": explicit > 0,
        "omission_only_is_nonbinding": explicit == 0,
    }


def _identity_projection(
    metadata_path: Path,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_cached: bool,
    enforce_cache_predicates: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata_bytes = _v13._regular_bytes(
        Path(metadata_path),
        maximum_bytes=_v13._v10._v6.MAXIMUM_METADATA_BYTES,
        failure_code="METADATA_FILE_INVALID",
        label="BuildKit metadata",
    )
    progress_bytes = _v13._regular_bytes(
        Path(progress_path),
        maximum_bytes=_v13._v10._v6.MAXIMUM_PROGRESS_BYTES,
        failure_code="RAWJSON_FILE_INVALID",
        label="BuildKit rawjson",
    )
    metadata = _v13._strict_json_bytes(metadata_bytes, "BuildKit metadata")
    _require(
        isinstance(metadata, dict),
        "PROVENANCE_ROOT_INVALID",
        "BuildKit metadata root changed",
    )
    _provenance, args, build_config, source = _v13._v10._metadata_parts(
        metadata
    )
    if dockerfile_kind == "prefix":
        _v13._combined_dockerfile(source)
        expected_target = (
            _v13.IMPORT_TARGET if require_cached else _v13.EXPORT_TARGET
        )
    elif dockerfile_kind == "full":
        decoded = _v13._v10._decoded_dockerfile(source)
        _require(
            hashlib.sha256(decoded).hexdigest() == _v13.FULL_DOCKERFILE_SHA256,
            "FULL_DOCKERFILE_CHANGED",
            "full replay Dockerfile changed",
        )
        expected_target = _v13.FULL_TARGET
    else:
        _fail("DOCKERFILE_KIND_INVALID", "Dockerfile kind changed")
    target = args.get("target")
    _require(
        target == expected_target,
        "V16_TARGET_INVALID",
        "V16 Dockerfile target changed",
    )
    try:
        ((vertices, _names, log_streams, _refs, _plain), _diagnostic) = (
            _v13._v10._strict_progress_view(
                progress_bytes,
                Path(progress_path),
                dockerfile_kind=dockerfile_kind,
                require_network_vertices_cached=require_cached,
            )
        )
        steps, step_to_digests = _v13._v10._step_graph(build_config)
    except _v13._v10.V10BundleError as exc:
        raise V16BundleError(exc.failure_code, str(exc)) from None
    try:
        roles, _role_logs = _v13._collect_roles(
            metadata,
            source,
            steps,
            step_to_digests,
            vertices,
            log_streams,
        )
    except _v13.V11BundleError as exc:
        raise V16BundleError(exc.failure_code, str(exc)) from None

    git_steps: list[str] = []
    local_steps: list[str] = []
    for step_id, step in steps.items():
        union = step["union"]
        if set(union) != {"source"} or not isinstance(union["source"], dict):
            continue
        identifier = union["source"].get("identifier")
        if isinstance(identifier, str) and identifier.startswith("local://"):
            local_steps.append(step_id)
        if isinstance(identifier, str) and identifier.startswith("git://"):
            git_steps.append(step_id)
    _require(
        not local_steps,
        "V16_LOCAL_MAIN_CONTEXT_PRESENT",
        "top-level operational local source is forbidden",
    )
    _require(
        len(git_steps) == 1,
        "V16_GIT_SOURCE_AMBIGUOUS",
        "canonical Git source binding changed",
    )
    git_step_id = git_steps[0]
    git_step = steps[git_step_id]
    git_source = git_step["union"]["source"]
    _require(
        set(git_source) == {"identifier", "attrs"}
        and git_source["identifier"] == GIT_SOURCE_IDENTIFIER
        and git_source["attrs"] == GIT_SOURCE_ATTRS
        and git_step["inputs"] == [],
        "V16_GIT_SOURCE_INVALID",
        "canonical Git SourceOp changed",
    )
    git_digest = _one_step_digest(
        step_to_digests,
        git_step_id,
        code="V16_GIT_SOURCE_DIGEST_AMBIGUOUS",
        label="Git main context",
    )
    _require(
        git_digest in vertices,
        "V16_GIT_SOURCE_VERTEX_MISSING",
        "Git source progress vertex missing",
    )
    git_interval = _v13._collect_interval(
        role="git_main_context",
        line=0,
        step_id=git_step_id,
        digest=git_digest,
        vertex=vertices[git_digest],
        build_window=_v13._v10._v7._provenance_build_window(metadata),
    )

    copy_step_id = _v13._v10._step_for_line(
        source,
        steps,
        REQUIREMENTS_COPY_LINE,
    )
    copy_step = steps[copy_step_id]
    _require(
        set(copy_step["union"]) == {"file"}
        and copy_step["union"]["file"]
        == {"actions": EXPECTED_COPY_ACTIONS}
        and copy_step["platform"] is None
        and len(copy_step["inputs"]) == 2
        and copy_step["inputs"][1] == (git_step_id, 0)
        and copy_step["inputs"][0][1] == 0
        and copy_step["inputs"][0][0] != git_step_id,
        "V16_REQUIREMENTS_COPY_INVALID",
        "requirements FileOp identity changed",
    )
    copy_digest = _one_step_digest(
        step_to_digests,
        copy_step_id,
        code="V16_REQUIREMENTS_COPY_DIGEST_AMBIGUOUS",
        label="requirements copy",
    )
    _require(
        copy_digest in vertices,
        "V16_REQUIREMENTS_COPY_VERTEX_MISSING",
        "requirements copy progress vertex missing",
    )
    copy_interval = _v13._collect_interval(
        role="requirements_copy",
        line=REQUIREMENTS_COPY_LINE,
        step_id=copy_step_id,
        digest=copy_digest,
        vertex=vertices[copy_digest],
        build_window=_v13._v10._v7._provenance_build_window(metadata),
    )
    runtime_parent_step_id = copy_step["inputs"][0][0]
    runtime_parent_digest = _one_step_digest(
        step_to_digests,
        runtime_parent_step_id,
        code="V16_REQUIREMENTS_COPY_PARENT_DIGEST_AMBIGUOUS",
        label="requirements copy runtime parent",
    )
    copy_progress_inputs = _progress_input_projection(
        progress_bytes,
        child_digest=copy_digest,
        expected_parent_digests=[runtime_parent_digest, git_digest],
        label="requirements copy",
    )
    copy_predicate = (
        _all_intervals_cached(copy_interval)
        if require_cached
        else _all_intervals_noncached(copy_interval)
    )

    pip_step_id = _v13._v10._step_for_line(
        source,
        steps,
        RUNTIME_PIP_LINE,
    )
    pip_step = steps[pip_step_id]
    _require(
        isinstance(pip_step["exec"], dict)
        and pip_step["platform"]
        == {"Architecture": "amd64", "OS": "linux"}
        and pip_step["inputs"] == [(copy_step_id, 0)],
        "V16_RUNTIME_PIP_PARENT_INVALID",
        "runtime_pip direct requirements-copy parent changed",
    )
    pip_digest = _one_step_digest(
        step_to_digests,
        pip_step_id,
        code="V16_RUNTIME_PIP_DIGEST_AMBIGUOUS",
        label="runtime_pip",
    )
    pip_roles = [item for item in roles if item.get("role") == "runtime_pip"]
    _require(
        len(pip_roles) == 1
        and pip_roles[0].get("step_id") == pip_step_id
        and pip_roles[0].get("vertex_digest") == pip_digest,
        "V16_RUNTIME_PIP_IDENTITY_INVALID",
        "runtime_pip identity binding changed",
    )
    pip_progress_inputs = _progress_input_projection(
        progress_bytes,
        child_digest=pip_digest,
        expected_parent_digests=[copy_digest],
        label="runtime_pip",
    )
    role_predicate = all(
        (_all_intervals_cached(item) if require_cached else _all_intervals_noncached(item))
        for item in roles
    )

    nested_llb = None
    infos = source.get("infos")
    if isinstance(infos, list) and len(infos) == 1 and isinstance(infos[0], dict):
        nested_llb = infos[0].get("llbDefinition")
    identity = {
        "schema_version": "noteai.admin-dependency-cache-identity.v16",
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "progress_sha256": hashlib.sha256(progress_bytes).hexdigest(),
        "dockerfile_kind": dockerfile_kind,
        "target": target,
        "cache_predicate": (
            "ALL_COMPLETED_CACHED"
            if require_cached
            else "ALL_COMPLETED_NONCACHED"
        ),
        "source": {
            "step_id": git_step_id,
            "vertex_digest": git_digest,
            "identifier": GIT_SOURCE_IDENTIFIER,
            "attrs": dict(GIT_SOURCE_ATTRS),
            "top_level_operational_local_source_count": 0,
            "interval": git_interval,
        },
        "requirements_copy": {
            "step_id": copy_step_id,
            "vertex_digest": copy_digest,
            "direct_input_step_ids": [
                runtime_parent_step_id,
                git_step_id,
            ],
            "direct_input_vertex_digests": [
                runtime_parent_digest,
                git_digest,
            ],
            "git_source_input_index": 1,
            "actions_sha256": _canonical_sha256(EXPECTED_COPY_ACTIONS),
            "interval": copy_interval,
            **copy_progress_inputs,
        },
        "runtime_pip": {
            "step_id": pip_step_id,
            "vertex_digest": pip_digest,
            "direct_parent_step_id": copy_step_id,
            "interval": pip_roles[0],
            **pip_progress_inputs,
        },
        "nested_dockerfile_llb_diagnostic_sha256": (
            _canonical_sha256(nested_llb) if nested_llb is not None else None
        ),
        "nested_dockerfile_llb_is_operational_identity": False,
        "requirements_copy_cache_predicate_satisfied": copy_predicate,
        "network_cache_predicate_satisfied": role_predicate,
    }
    identity["identity_chain_sha256"] = _canonical_sha256(
        {
            "source": git_digest,
            "requirements_copy": copy_digest,
            "runtime_pip": pip_digest,
        }
    )
    if enforce_cache_predicates:
        _require(
            copy_predicate,
            "V16_REQUIREMENTS_COPY_CACHE_PREDICATE_FAILED",
            "requirements copy cache predicate changed",
        )
        _require(
            role_predicate,
            "V16_NETWORK_CACHE_PREDICATE_FAILED",
            "dependency role cache predicate changed",
        )
    return identity, roles


def _v16_summary(
    legacy: dict[str, Any],
    identity: dict[str, Any],
    *,
    legacy_v13_verdict_sha256: str,
) -> dict[str, Any]:
    summary = copy.deepcopy(legacy)
    summary["schema_version"] = "noteai.admin-dependency-cache-build.v16"
    summary["legacy_v13_verdict_sha256"] = legacy_v13_verdict_sha256
    summary["legacy_v13_compatibility_projection_sha256"] = (
        _canonical_sha256(legacy)
    )
    summary["legacy_v13_execution_boundary"] = {
        "mode": "PRIVATE_GIT_TO_LOCAL_COMPATIBILITY_PROJECTION",
        "original_v16_git_identity_validated_first": True,
        "high_level_delegate_executed_on_original_metadata": False,
        "legacy_verdict_transformed_for_v16_summary": True,
        "runtime_portability_accepted_from_legacy_projection_only": False,
    }
    summary["identity_chain"] = identity
    return summary


@contextmanager
def _legacy_git_context_projection(
    metadata_path: Path,
    *,
    dockerfile_kind: str,
) -> Iterator[tuple[Path, str, str]]:
    """Project only the already-validated Git source into frozen V2's view.

    Frozen V13 ultimately delegates to V2, whose historical contract requires
    one local://context SourceOp and only the two base-image materials.  V16
    validates the original Git graph before entering this function.  The
    projection is a private deep copy, never an authority for V16 identity.
    """

    metadata_bytes = _v13._regular_bytes(
        Path(metadata_path),
        maximum_bytes=_v13._v10._v6.MAXIMUM_METADATA_BYTES,
        failure_code="METADATA_FILE_INVALID",
        label="BuildKit metadata",
    )
    metadata = _v13._strict_json_bytes(metadata_bytes, "BuildKit metadata")
    _require(
        isinstance(metadata, dict),
        "PROVENANCE_ROOT_INVALID",
        "BuildKit metadata root changed",
    )
    legacy = copy.deepcopy(metadata)
    provenance = legacy["buildx.build.provenance"]
    build_config = provenance["buildConfig"]
    followpaths = (
        _base.PREFIX_CONTEXT_FOLLOWPATHS
        if dockerfile_kind == "prefix"
        else _base.FULL_CONTEXT_FOLLOWPATHS
    )
    replacements = 0
    for item in build_config["llbDefinition"]:
        op = item.get("op") if isinstance(item, dict) else None
        union = op.get("Op") if isinstance(op, dict) else None
        source = union.get("source") if isinstance(union, dict) else None
        if (
            isinstance(source, dict)
            and source.get("identifier") == GIT_SOURCE_IDENTIFIER
            and source.get("attrs") == GIT_SOURCE_ATTRS
        ):
            union["source"] = {
                "identifier": "local://context",
                "attrs": {
                    "local.followpaths": json.dumps(
                        followpaths,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                },
            }
            replacements += 1
    _require(
        replacements == 1,
        "V16_LEGACY_PROJECTION_INVALID",
        "V16 legacy Git-source projection changed",
    )
    materials = provenance.get("materials")
    _require(
        isinstance(materials, list),
        "V16_LEGACY_PROJECTION_INVALID",
        "BuildKit materials changed",
    )
    retained_materials = [
        item
        for item in materials
        if isinstance(item, dict)
        and isinstance(item.get("digest"), dict)
        and item["digest"].get("sha256")
        in {_base.NODE_INDEX, _base.PYTHON_INDEX}
    ]
    _require(
        {
            item["digest"]["sha256"]
            for item in retained_materials
        }
        == {_base.NODE_INDEX, _base.PYTHON_INDEX},
        "V16_LEGACY_PROJECTION_INVALID",
        "pinned base-image materials changed",
    )
    provenance["materials"] = retained_materials
    payload = json.dumps(
        legacy,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    temporary_root = Path(tempfile.mkdtemp(prefix="noteai-v16-legacy-"))
    legacy_path = temporary_root / "metadata.json"
    try:
        _v13._v10._v6._write_exclusive_regular(legacy_path, payload)
        _require(
            stat.S_IMODE(legacy_path.stat().st_mode) == 0o600,
            "V16_LEGACY_PROJECTION_INVALID",
            "V16 legacy projection mode changed",
        )
        yield (
            legacy_path,
            hashlib.sha256(payload).hexdigest(),
            hashlib.sha256(metadata_bytes).hexdigest(),
        )
    finally:
        import shutil

        shutil.rmtree(temporary_root, ignore_errors=True)
        _require(
            not temporary_root.exists() and not temporary_root.is_symlink(),
            "V16_LEGACY_PROJECTION_CLEANUP_FAILED",
            "V16 legacy projection cleanup incomplete",
        )


def _legacy_producer_summary(summary: dict[str, Any]) -> dict[str, Any]:
    legacy = copy.deepcopy(summary)
    identity = legacy.get("identity_chain")
    _require(
        legacy.get("schema_version")
        == "noteai.admin-dependency-cache-build.v16",
        "V16_PRODUCER_SUMMARY_INVALID",
        "V16 producer summary schema changed",
    )
    _require(
        legacy.get("target") == _v13.EXPORT_TARGET
        and legacy.get("anchor") is not None
        and legacy.get("observer") is None
        and isinstance(identity, dict)
        and identity.get("target") == _v13.EXPORT_TARGET
        and identity.get("source", {}).get("identifier")
        == GIT_SOURCE_IDENTIFIER
        and identity.get("source", {}).get("attrs") == GIT_SOURCE_ATTRS
        and identity.get("requirements_copy_cache_predicate_satisfied") is True
        and identity.get("network_cache_predicate_satisfied") is True,
        "V16_PRODUCER_SUMMARY_INVALID",
        "V16 producer identity or target changed",
    )
    verdict_sha256 = legacy.pop("legacy_v13_verdict_sha256", None)
    projection_sha256 = legacy.pop(
        "legacy_v13_compatibility_projection_sha256",
        None,
    )
    boundary = legacy.pop("legacy_v13_execution_boundary", None)
    legacy.pop("identity_chain", None)
    legacy["schema_version"] = "noteai.admin-dependency-cache-build.v11"
    _require(
        isinstance(verdict_sha256, str)
        and SHA256_RE.fullmatch(verdict_sha256) is not None
        and projection_sha256 == _canonical_sha256(legacy)
        and boundary
        == {
            "mode": "PRIVATE_GIT_TO_LOCAL_COMPATIBILITY_PROJECTION",
            "original_v16_git_identity_validated_first": True,
            "high_level_delegate_executed_on_original_metadata": False,
            "legacy_verdict_transformed_for_v16_summary": True,
            "runtime_portability_accepted_from_legacy_projection_only": False,
        },
        "V16_PRODUCER_SUMMARY_INVALID",
        "frozen V13 verdict or compatibility projection binding changed",
    )
    return legacy


def classify_pair(
    producer_summary: dict[str, Any],
    consumer_summary: dict[str, Any],
) -> dict[str, Any]:
    _require(
        producer_summary.get("schema_version")
        == "noteai.admin-dependency-cache-build.v16"
        and consumer_summary.get("schema_version")
        == "noteai.admin-dependency-cache-build.v16"
        and producer_summary.get("target") == _v13.EXPORT_TARGET
        and consumer_summary.get("target") == _v13.IMPORT_TARGET,
        "V16_PAIR_TARGET_INVALID",
        "V16 producer or consumer summary changed",
    )
    producer = producer_summary.get("identity_chain")
    consumer = consumer_summary.get("identity_chain")
    _require(
        isinstance(producer, dict) and isinstance(consumer, dict),
        "V16_PAIR_IDENTITY_MISSING",
        "V16 identity chain missing",
    )
    labels = ("source", "requirements_copy", "runtime_pip")
    producer_digests = {
        label: producer.get(label, {}).get("vertex_digest")
        if isinstance(producer.get(label), dict)
        else None
        for label in labels
    }
    consumer_digests = {
        label: consumer.get(label, {}).get("vertex_digest")
        if isinstance(consumer.get(label), dict)
        else None
        for label in labels
    }
    _require(
        all(
            isinstance(value, str) and DIGEST_RE.fullmatch(value) is not None
            for value in (*producer_digests.values(), *consumer_digests.values())
        ),
        "V16_PAIR_IDENTITY_INVALID",
        "V16 identity digest changed",
    )
    producer_noncached = (
        _all_intervals_noncached(producer["requirements_copy"]["interval"])
        and all(
            _all_intervals_noncached(item)
            for item in producer_summary.get("network_vertices", [])
        )
    )
    consumer_cached = (
        _all_intervals_cached(consumer["requirements_copy"]["interval"])
        and all(
            _all_intervals_cached(item)
            for item in consumer_summary.get("network_vertices", [])
        )
    )
    if producer_digests["source"] != consumer_digests["source"]:
        classification = "SOURCE_DIGEST_DRIFT"
    elif producer_digests["requirements_copy"] != consumer_digests["requirements_copy"]:
        classification = "REQUIREMENTS_COPY_DIGEST_DRIFT"
    elif producer_digests["runtime_pip"] != consumer_digests["runtime_pip"]:
        classification = "RUNTIME_PIP_DIGEST_DRIFT"
    elif producer_noncached and consumer_cached:
        classification = "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED"
    else:
        classification = "SAME_SOURCE_COPY_PIP_DIGESTS_NONCACHED"
    return {
        "schema_version": "noteai.admin-dependency-cache-pair.v16",
        "producer_digests": producer_digests,
        "consumer_digests": consumer_digests,
        "producer_copy_and_network_all_noncached": producer_noncached,
        "consumer_copy_and_network_all_cached": consumer_cached,
        "classification": classification,
        "v15_terminal_classification": "DIGEST_DRIFT",
        "v16_boundary_status": "DETERMINED_BY_V16",
    }


def validate_pair(
    producer_summary_path: Path,
    consumer_summary_path: Path,
) -> dict[str, Any]:
    producer, producer_sha256 = _read_summary_with_sha256(
        producer_summary_path,
        label="V16 producer summary",
    )
    consumer, consumer_sha256 = _read_summary_with_sha256(
        consumer_summary_path,
        label="V16 consumer summary",
    )
    pair = classify_pair(producer, consumer)
    print(
        "noteai_v16_pair_diagnostic="
        + json.dumps(
            pair
            | {
                "producer_summary_sha256": producer_sha256,
                "consumer_summary_sha256": consumer_sha256,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    _require(
        pair["classification"]
        == "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED",
        "V16_PAIR_CACHE_PREDICATE_FAILED",
        "V16 producer/consumer identity chain did not prove a cache hit",
    )
    return pair


def validate_build_evidence(
    metadata_path: Path,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
    producer_summary_path: Path | None = None,
    cache_record_path: Path | None = None,
    expected_cache_record_sha256: str | None = None,
    pre_predicate_diagnostic_output_path: Path | None = None,
    diagnostic_output_path: Path | None = None,
    pair_output_path: Path | None = None,
    identity_output_path: Path | None = None,
) -> dict[str, Any]:
    identity, roles = _identity_projection(
        Path(metadata_path),
        Path(progress_path),
        dockerfile_kind=dockerfile_kind,
        require_cached=require_network_vertices_cached,
        enforce_cache_predicates=False,
    )
    if identity_output_path is not None:
        _write_json(Path(identity_output_path), identity)

    preliminary_pair = None
    if dockerfile_kind == "prefix" and require_network_vertices_cached:
        _require(
            producer_summary_path is not None,
            "V16_PAIR_EVIDENCE_MISSING",
            "V16 producer summary is missing",
        )
        producer = _read_summary(
            Path(producer_summary_path),
            label="V16 producer summary",
        )
        candidate = {
            "schema_version": "noteai.admin-dependency-cache-build.v16",
            "target": _v13.IMPORT_TARGET,
            "network_vertices": roles,
            "identity_chain": identity,
        }
        preliminary_pair = classify_pair(producer, candidate)
        if pair_output_path is not None:
            _write_json(Path(pair_output_path), preliminary_pair)
        _require(
            preliminary_pair["classification"]
            == "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED",
            "V16_PAIR_CACHE_PREDICATE_FAILED",
            "V16 fresh consumer identity chain did not prove a cache hit",
        )

    _require(
        identity["requirements_copy_cache_predicate_satisfied"] is True,
        "V16_REQUIREMENTS_COPY_CACHE_PREDICATE_FAILED",
        "requirements copy cache predicate changed",
    )
    _require(
        identity["network_cache_predicate_satisfied"] is True,
        "V16_NETWORK_CACHE_PREDICATE_FAILED",
        "dependency role cache predicate changed",
    )

    original_metadata_sha256 = identity["metadata_sha256"]
    with _legacy_git_context_projection(
        Path(metadata_path),
        dockerfile_kind=dockerfile_kind,
    ) as (
        legacy_metadata_path,
        legacy_metadata_sha256,
        reread_original_metadata_sha256,
    ):
        _require(
            reread_original_metadata_sha256 == original_metadata_sha256,
            "V16_METADATA_CHANGED_DURING_VALIDATION",
            "BuildKit metadata changed between identity and compatibility validation",
        )
        legacy = _v13.validate_build_evidence(
            legacy_metadata_path,
            Path(progress_path),
            dockerfile_kind=dockerfile_kind,
            require_network_vertices_cached=require_network_vertices_cached,
            producer_summary_path=producer_summary_path,
            cache_record_path=cache_record_path,
            expected_cache_record_sha256=expected_cache_record_sha256,
            pre_predicate_diagnostic_output_path=(
                pre_predicate_diagnostic_output_path
            ),
            diagnostic_output_path=diagnostic_output_path,
            pair_output_path=None,
        )
    legacy_v13_verdict_sha256 = _canonical_sha256(legacy)
    legacy["metadata_sha256"] = original_metadata_sha256
    legacy["legacy_compatibility_metadata_sha256"] = legacy_metadata_sha256
    summary = _v16_summary(
        legacy,
        identity,
        legacy_v13_verdict_sha256=legacy_v13_verdict_sha256,
    )
    if preliminary_pair is not None:
        summary["identity_pair"] = preliminary_pair
    return summary


def validate_cache_record(
    cache_root: Path,
    producer_summary_path: Path,
) -> dict[str, Any]:
    producer, producer_sha256 = _read_summary_with_sha256(
        Path(producer_summary_path),
        label="V16 producer summary",
    )
    legacy = _legacy_producer_summary(producer)
    with tempfile.TemporaryDirectory(prefix="noteai-v16-record-") as temporary:
        legacy_path = Path(temporary) / "producer-summary.json"
        _write_json(legacy_path, legacy)
        record = _v13.validate_cache_record(Path(cache_root), legacy_path)
    record["producer_summary_sha256"] = producer_sha256
    return _v13._validate_cache_record_summary(
        record,
        expected_producer_summary_sha256=producer_sha256,
    )


def _validate_inventory(manifest: dict[str, Any]) -> None:
    cache = _require_exact_dict(
        manifest["cache"],
        {
            "type",
            "mode",
            "compression",
            "compression_level",
            "cache_index_sha256",
            "oci_layout_sha256",
            "manifest_digest",
            "blob_count",
            "blob_bytes",
            "blobs",
            "record_path",
            "record_provenance",
        },
        "manifest.cache",
    )
    _require(
        cache["type"] == "buildkit-local-oci-layout"
        and cache["mode"] == "max"
        and cache["compression"] == "gzip"
        and cache["compression_level"] == 1
        and cache["record_path"] == "producer/cache-record.json"
        and isinstance(cache["record_provenance"], dict)
        and isinstance(cache["manifest_digest"], str)
        and DIGEST_RE.fullmatch(cache["manifest_digest"]) is not None,
        "V16_MANIFEST_INVALID",
        "V16 cache contract changed",
    )
    for key in ("cache_index_sha256", "oci_layout_sha256"):
        _require_sha256(cache[key], f"manifest.cache.{key}")
    _require_positive_int(cache["blob_count"], "manifest.cache.blob_count")
    _require_positive_int(cache["blob_bytes"], "manifest.cache.blob_bytes")
    _require(
        cache["blob_bytes"] <= _base.MAXIMUM_BLOB_BYTES
        and isinstance(cache["blobs"], list)
        and len(cache["blobs"]) == cache["blob_count"]
        and len({item.get("name") for item in cache["blobs"]})
        == cache["blob_count"]
        and all(
            isinstance(item, dict)
            and set(item) == {"name", "sha256", "bytes"}
            and isinstance(item["name"], str)
            and SHA256_RE.fullmatch(item["name"]) is not None
            and item["sha256"] == item["name"]
            and isinstance(item["bytes"], int)
            and not isinstance(item["bytes"], bool)
            and item["bytes"] > 0
            for item in cache["blobs"]
        ),
        "V16_MANIFEST_INVALID",
        "V16 cache inventory changed",
    )

    archive = _require_exact_dict(
        manifest["archive"],
        {
            "format",
            "raw_tar_sha256",
            "raw_tar_bytes",
            "gzip_sha256",
            "gzip_bytes",
            "chunk_bytes_limit",
            "chunk_count",
            "chunks",
            "maximum_gzip_bytes",
            "maximum_extracted_cache_bytes",
            "artifact_input_maximum_bytes",
            "artifact_provider_maximum_bytes",
            "non_chunk_file_maximum_bytes",
        },
        "manifest.archive",
    )
    for key in ("raw_tar_sha256", "gzip_sha256"):
        _require_sha256(archive[key], f"manifest.archive.{key}")
    for key in ("raw_tar_bytes", "gzip_bytes", "chunk_count"):
        _require_positive_int(archive[key], f"manifest.archive.{key}")
    _require(
        archive["format"] == "deterministic-tar-gzip"
        and archive["raw_tar_bytes"] <= _base.MAXIMUM_RAW_TAR_BYTES
        and archive["gzip_bytes"] <= _base.MAXIMUM_GZIP_BYTES
        and archive["raw_tar_bytes"] <= archive["gzip_bytes"] * 8
        and archive["chunk_bytes_limit"] == _base.CHUNK_BYTES
        and archive["chunk_count"] <= _base.MAXIMUM_CHUNK_COUNT
        and archive["maximum_gzip_bytes"] == _base.MAXIMUM_GZIP_BYTES
        and archive["maximum_extracted_cache_bytes"]
        == _base.MAXIMUM_EXTRACTED_CACHE_BYTES
        and archive["artifact_input_maximum_bytes"]
        == _base.MAXIMUM_ARTIFACT_INPUT_BYTES
        and archive["artifact_provider_maximum_bytes"]
        == _base.MAXIMUM_PROVIDER_ARTIFACT_BYTES
        and archive["non_chunk_file_maximum_bytes"]
        == _base.MAXIMUM_NON_CHUNK_FILE_BYTES,
        "V16_MANIFEST_INVALID",
        "V16 archive contract changed",
    )
    expected_chunks = [
        f"chunks/admin-dependency-cache.tar.gz.part-{index:04d}"
        for index in range(archive["chunk_count"])
    ]
    _require(
        isinstance(archive["chunks"], list)
        and len(archive["chunks"]) == archive["chunk_count"]
        and [item.get("name") for item in archive["chunks"]]
        == expected_chunks
        and all(
            isinstance(item, dict)
            and set(item) == {"name", "sha256", "bytes"}
            and SHA256_RE.fullmatch(item.get("sha256", "")) is not None
            and isinstance(item.get("bytes"), int)
            and not isinstance(item.get("bytes"), bool)
            and 0 < item["bytes"] <= _base.CHUNK_BYTES
            and (
                index == archive["chunk_count"] - 1
                or item["bytes"] == _base.CHUNK_BYTES
            )
            for index, item in enumerate(archive["chunks"])
        ),
        "V16_MANIFEST_INVALID",
        "V16 chunk inventory changed",
    )


def validate_manifest(bundle: Path) -> dict[str, Any]:
    bundle = Path(bundle)
    manifest = _base.strict_json_file(bundle / "manifest.json")
    _require_exact_dict(
        manifest,
        {
            "schema_version",
            "task",
            "release",
            "build",
            "cache",
            "archive",
            "control",
            "next_gate",
        },
        "V16 manifest",
    )
    _require(
        manifest["schema_version"]
        == "noteai.admin-dependency-cache-export.v16"
        and manifest["task"] == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "V16_MANIFEST_INVALID",
        "V16 manifest identity changed",
    )
    release = _require_exact_dict(
        manifest["release"],
        {
            "commit",
            "tree",
            "dockerfile_sha256",
            "dependency_prefix_lines",
            "first_application_copy_line",
            "dependency_prefix_sha256",
            "combined_dockerfile_sha256",
            "combined_dockerfile_lines",
            "main_context",
        },
        "manifest.release",
    )
    _require(
        release["commit"] == RELEASE_COMMIT
        and release["tree"] == RELEASE_TREE
        and release["dockerfile_sha256"] == _v13.FULL_DOCKERFILE_SHA256
        and release["dependency_prefix_lines"] == [1, 80]
        and release["first_application_copy_line"] == 83
        and release["dependency_prefix_sha256"] == _v13.BASE_PREFIX_SHA256
        and release["combined_dockerfile_sha256"]
        == _v13.COMBINED_DOCKERFILE_SHA256
        and release["combined_dockerfile_lines"]
        == _v13.COMBINED_DOCKERFILE_LINES,
        "V16_MANIFEST_INVALID",
        "V16 release binding changed",
    )
    main_context = _require_exact_dict(
        release["main_context"],
        {
            "query_url",
            "source_identifier",
            "source_attrs",
            "buildx_send_git_query_as_input",
            "dockerfile_transport",
            "full_committed_context_supplied",
            "local_workspace_main_context_supplied",
            "dockerignore_sha256",
            "gitattributes_sha256",
            "gitmodules_present",
            "reachable_export_copy_files",
        },
        "manifest.release.main_context",
    )
    _require(
        main_context
        == {
            "query_url": GIT_CONTEXT_QUERY,
            "source_identifier": GIT_SOURCE_IDENTIFIER,
            "source_attrs": GIT_SOURCE_ATTRS,
            "buildx_send_git_query_as_input": False,
            "dockerfile_transport": "stdin",
            "full_committed_context_supplied": True,
            "local_workspace_main_context_supplied": False,
            "dockerignore_sha256": _base.DOCKERIGNORE_SHA256,
            "gitattributes_sha256": GITATTRIBUTES_SHA256,
            "gitmodules_present": False,
            "reachable_export_copy_files": [
                {
                    "path": "model/requirements-api.txt",
                    "sha256": _base.REQUIREMENTS_API_SHA256,
                },
                {
                    "path": "model/requirements.txt",
                    "sha256": _base.REQUIREMENTS_SHA256,
                },
            ],
        },
        "V16_MANIFEST_INVALID",
        "V16 Git main-context contract changed",
    )
    build = _require_exact_dict(
        manifest["build"],
        {
            "runner_architecture",
            "platform",
            "target",
            "pull",
            "output",
            "cache_export",
            "docker_engine_image_export_requested",
            "registry_export_requested",
            "transient_buildkit_sandboxes_expected",
            "buildx_client_version",
            "buildkit_driver",
            "buildkit_version",
            "buildkit_daemon_image_reference",
            "buildkit_daemon_image_id",
            "metadata_sha256",
            "progress_sha256",
            "duration_seconds",
            "base_images",
            "source_identity_fixture_sha256",
            "producer_identity_projection_sha256",
        },
        "manifest.build",
    )
    _require(
        build["runner_architecture"] == "x86_64"
        and build["platform"] == "linux/amd64"
        and build["target"] == _v13.EXPORT_TARGET
        and build["pull"] is True
        and build["output"] == "cacheonly"
        and build["cache_export"]
        == "type=local,mode=max,oci-mediatypes=true"
        and build["docker_engine_image_export_requested"] is False
        and build["registry_export_requested"] is False
        and build["transient_buildkit_sandboxes_expected"] is True
        and build["buildkit_driver"] == "docker-container"
        and isinstance(build["buildx_client_version"], str)
        and bool(build["buildx_client_version"])
        and isinstance(build["buildkit_version"], str)
        and bool(build["buildkit_version"])
        and isinstance(build["buildkit_daemon_image_reference"], str)
        and re.fullmatch(
            r"(?:docker\.io/)?moby/buildkit@sha256:[0-9a-f]{64}",
            build["buildkit_daemon_image_reference"],
        )
        is not None
        and isinstance(build["buildkit_daemon_image_id"], str)
        and DIGEST_RE.fullmatch(build["buildkit_daemon_image_id"]) is not None
        and isinstance(build["duration_seconds"], (int, float))
        and not isinstance(build["duration_seconds"], bool)
        and 0 <= build["duration_seconds"] <= 7_200
        and build["base_images"]
        == {
            "python": {
                "index": f"sha256:{_base.PYTHON_INDEX}",
                "linux_amd64": f"sha256:{_base.PYTHON_AMD64}",
            },
            "node": {
                "index": f"sha256:{_base.NODE_INDEX}",
                "linux_amd64": f"sha256:{_base.NODE_AMD64}",
            },
        }
        and build["source_identity_fixture_sha256"]
        == SOURCE_IDENTITY_FIXTURE_SHA256,
        "V16_MANIFEST_INVALID",
        "V16 BuildKit identity changed",
    )
    for key in (
        "metadata_sha256",
        "progress_sha256",
        "producer_identity_projection_sha256",
    ):
        _require_sha256(build[key], f"manifest.build.{key}")
    producer_summary = validate_build_evidence(
        bundle / "cache-build-metadata.json",
        bundle / "producer-build.rawjson",
        dockerfile_kind="prefix",
        require_network_vertices_cached=False,
    )
    retained_producer = _read_summary(
        bundle / "producer" / "cache-build-summary.json",
        label="V16 producer summary",
    )
    retained_identity = _read_summary(
        bundle / "producer" / "cache-build-identity.json",
        label="V16 producer identity",
    )
    _require(
        producer_summary == retained_producer
        and retained_identity == producer_summary["identity_chain"]
        and producer_summary["metadata_sha256"] == build["metadata_sha256"]
        and producer_summary["progress_sha256"] == build["progress_sha256"]
        and producer_summary["duration_seconds"] == build["duration_seconds"]
        and _base.sha256_file(
            bundle / "producer" / "cache-build-identity.json"
        )
        == build["producer_identity_projection_sha256"],
        "V16_MANIFEST_INVALID",
        "V16 producer evidence binding changed",
    )
    _validate_inventory(manifest)
    control = _require_exact_dict(
        manifest["control"],
        {
            "plan_checkpoint_commit",
            "control_commit",
            "request_sha256",
            "workflow_sha256",
            "export_helper_sha256",
            "import_helper_sha256",
            "bundle_verifier_sha256",
            "v13_bundle_verifier_sha256",
            "source_identity_fixture_sha256",
            "github_run_id",
            "github_run_attempt",
            "artifact_retention_days",
            "full_committed_git_context_supplied",
            "local_workspace_main_context_supplied",
            "local_dockerfile_supplied_via_stdin",
            "credential_or_secret_values_supplied",
            "default_git_auth_secret_ids_present",
            "registry_digest",
            "registry_publication_authorized",
            "deployment_authorized",
            "database_authorized",
            "service_mutation_authorized",
            "public_traffic_authorized",
        },
        "manifest.control",
    )
    _require(
        all(
            isinstance(control[key], str)
            and re.fullmatch(r"[0-9a-f]{40}", control[key]) is not None
            for key in ("plan_checkpoint_commit", "control_commit")
        )
        and isinstance(control["github_run_id"], str)
        and control["github_run_id"].isdigit()
        and int(control["github_run_id"]) > 0
        and control["github_run_attempt"] == 1
        and control["artifact_retention_days"] == 1
        and control["full_committed_git_context_supplied"] is True
        and control["local_workspace_main_context_supplied"] is False
        and control["local_dockerfile_supplied_via_stdin"] is True
        and control["credential_or_secret_values_supplied"] is False
        and control["default_git_auth_secret_ids_present"] is True
        and control["registry_digest"] is None
        and all(
            control[field] is False
            for field in (
                "registry_publication_authorized",
                "deployment_authorized",
                "database_authorized",
                "service_mutation_authorized",
                "public_traffic_authorized",
            )
        )
        and control["source_identity_fixture_sha256"]
        == SOURCE_IDENTITY_FIXTURE_SHA256,
        "V16_MANIFEST_INVALID",
        "V16 bounded authorization changed",
    )
    for key in (
        "request_sha256",
        "workflow_sha256",
        "export_helper_sha256",
        "import_helper_sha256",
        "bundle_verifier_sha256",
        "v13_bundle_verifier_sha256",
        "source_identity_fixture_sha256",
    ):
        _require_sha256(control[key], f"manifest.control.{key}")
    _require(
        _base.sha256_file(
            bundle / "producer" / "export_admin_dependency_cache.sh"
        )
        == control["export_helper_sha256"]
        and _base.sha256_file(
            bundle / "builder" / "import_admin_dependency_cache.sh"
        )
        == control["import_helper_sha256"]
        and _base.sha256_file(
            bundle / "builder" / "verify_admin_dependency_cache_bundle.py"
        )
        == control["bundle_verifier_sha256"]
        and _base.sha256_file(
            bundle / "builder" / "verify_admin_dependency_cache_bundle_v13.py"
        )
        == control["v13_bundle_verifier_sha256"]
        and control["v13_bundle_verifier_sha256"] == V13_VERIFIER_SHA256
        and _base.sha256_file(
            bundle / "builder" / "git-main-context-identity-source-projection.json"
        )
        == control["source_identity_fixture_sha256"],
        "V16_MANIFEST_INVALID",
        "V16 bundled execution authority changed",
    )
    _require(
        manifest["next_gate"]
        == {
            "provider_artifact_digest_acceptance_required": True,
            "authenticated_download_verification_required": True,
            "target_builder_import_required": True,
            "target_builder_external_cache_removed_same_consumer_builder_replay_required": True,
            "true_empty_cache_replay_claimed": False,
            "canonical_admin_build_same_builder_environment_required": True,
            "exact_buildkit_daemon_image_required": True,
            "canonical_admin_build_required": True,
            "fresh_scan_and_sbom_required": True,
            "private_publication_authorized": False,
        },
        "V16_MANIFEST_INVALID",
        "V16 next gate changed",
    )
    _base.validate_base_index(
        bundle / "python-base-index.json",
        _base.PYTHON_INDEX,
        _base.PYTHON_AMD64,
    )
    _base.validate_base_index(
        bundle / "node-base-index.json",
        _base.NODE_INDEX,
        _base.NODE_AMD64,
    )
    return manifest


FINAL_ADDITIONS = {
    "portability/import-build-metadata.json",
    "portability/import-build.rawjson",
    "portability/import-build-identity.json",
    "portability/import-pre-predicate-diagnostic.json",
    "portability/import-diagnostic.json",
    "portability/import-summary.json",
    "portability/pair.json",
    "portability/replay-build-metadata.json",
    "portability/replay-build.rawjson",
    "portability/replay-build-identity.json",
    "portability/replay-summary.json",
    "portability/proof.json",
    "SHA256SUMS",
}


def validate_core(
    bundle: Path,
    extract_to: Path,
    *,
    validation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = Path(bundle)
    extract_to = Path(extract_to)
    _require(bundle.is_dir(), "V16_BUNDLE_INVALID", "bundle directory missing")
    files = _base.relative_regular_files(bundle)
    _base.validate_bundle_size(bundle, files)
    present_final = files & FINAL_ADDITIONS
    _require(
        not present_final or present_final == FINAL_ADDITIONS,
        "V16_BUNDLE_INVALID",
        "partial V16 portability evidence present",
    )
    core_scope = files - FINAL_ADDITIONS
    core_files = core_scope - {"CORE_SHA256SUMS"}
    manifest = validate_manifest(bundle)
    expected_core = {
        "manifest.json",
        "cache-build-metadata.json",
        "producer-build.rawjson",
        "python-base-index.json",
        "node-base-index.json",
        "cache-index.json",
        "oci-layout",
        "producer/export_admin_dependency_cache.sh",
        "producer/cache-build-summary.json",
        "producer/cache-build-identity.json",
        "producer/cache-record.json",
        "builder/import_admin_dependency_cache.sh",
        "builder/verify_admin_dependency_cache_bundle.py",
        "builder/verify_admin_dependency_cache_bundle_v13.py",
        "builder/git-main-context-identity-source-projection.json",
        *{item["name"] for item in manifest["archive"]["chunks"]},
    }
    _require(
        core_files == expected_core,
        "V16_BUNDLE_INVALID",
        "V16 core bundle file set changed",
    )
    _base.validate_checksum_file(bundle, "CORE_SHA256SUMS", core_files)
    work = extract_to.parent / f".{extract_to.name}-archive-work"
    _require(
        not work.exists(),
        "V16_BUNDLE_INVALID",
        "archive work directory already exists",
    )
    work.mkdir(mode=0o700)
    gzip_path = work / "cache.tar.gz"
    raw_tar = work / "cache.tar"
    try:
        _base.validate_chunks(bundle, manifest, gzip_path)
        _base.bounded_decompress(
            gzip_path,
            raw_tar,
            manifest["archive"]["raw_tar_bytes"],
        )
        _require(
            _base.sha256_file(raw_tar)
            == manifest["archive"]["raw_tar_sha256"],
            "V16_ARCHIVE_INVALID",
            "raw archive hash changed",
        )
        _base.safe_extract_tar(
            raw_tar,
            extract_to,
            manifest["archive"]["raw_tar_bytes"],
        )
        _base.validate_oci_cache(extract_to, manifest)
        observed_record = validate_cache_record(
            extract_to,
            bundle / "producer" / "cache-build-summary.json",
        )
        retained_record_path = bundle / manifest["cache"]["record_path"]
        retained_record_bytes = _v13._regular_bytes(
            retained_record_path,
            maximum_bytes=2_097_152,
            failure_code="V16_SUMMARY_FILE_INVALID",
            label="V16 cache record",
        )
        retained_record = _v13._strict_json_bytes(
            retained_record_bytes,
            "V16 cache record",
        )
        _require(
            isinstance(retained_record, dict)
            and observed_record == retained_record
            and retained_record == manifest["cache"]["record_provenance"],
            "CACHE_RECORD_BINDING_INVALID",
            "V16 cache record provenance changed",
        )
        if validation_context is not None:
            _require(
                validation_context == {},
                "V16_CACHE_RECORD_TRUST_INVALID",
                "V16 core validation context was not empty",
            )
            validation_context["validated_cache_record_sha256"] = (
                hashlib.sha256(retained_record_bytes).hexdigest()
            )
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
    return manifest


def _identity_digests(identity: dict[str, Any]) -> dict[str, str]:
    return {
        label: identity[label]["vertex_digest"]
        for label in ("source", "requirements_copy", "runtime_pip")
    }


def validate_portability(
    bundle: Path,
    manifest: dict[str, Any],
    *,
    expected_cache_record_sha256: str,
) -> dict[str, Any]:
    portability = bundle / "portability"
    producer = _read_summary(
        bundle / "producer" / "cache-build-summary.json",
        label="V16 producer summary",
    )
    import_summary = validate_build_evidence(
        portability / "import-build-metadata.json",
        portability / "import-build.rawjson",
        dockerfile_kind="prefix",
        require_network_vertices_cached=True,
        producer_summary_path=(
            bundle / "producer" / "cache-build-summary.json"
        ),
        cache_record_path=bundle / "producer" / "cache-record.json",
        expected_cache_record_sha256=expected_cache_record_sha256,
    )
    replay_summary = validate_build_evidence(
        portability / "replay-build-metadata.json",
        portability / "replay-build.rawjson",
        dockerfile_kind="full",
        require_network_vertices_cached=True,
    )
    retained_import = _read_summary(
        portability / "import-summary.json",
        label="V16 retained import summary",
    )
    retained_replay = _read_summary(
        portability / "replay-summary.json",
        label="V16 retained replay summary",
    )
    retained_import_identity = _read_summary(
        portability / "import-build-identity.json",
        label="V16 retained import identity",
    )
    retained_replay_identity = _read_summary(
        portability / "replay-build-identity.json",
        label="V16 retained replay identity",
    )
    retained_diagnostic = _read_summary(
        portability / "import-diagnostic.json",
        label="V16 retained V13 compatibility diagnostic",
    )
    retained_pre_predicate = _read_summary(
        portability / "import-pre-predicate-diagnostic.json",
        label="V16 retained V13 compatibility pre-predicate diagnostic",
    )
    pair = validate_pair(
        bundle / "producer" / "cache-build-summary.json",
        portability / "import-summary.json",
    )
    retained_pair = _read_summary(
        portability / "pair.json",
        label="V16 retained pair",
    )
    _require(
        retained_import == import_summary
        and retained_replay == replay_summary
        and retained_import_identity == import_summary["identity_chain"]
        and retained_replay_identity == replay_summary["identity_chain"]
        and retained_pair == pair,
        "V16_PORTABILITY_BINDING_INVALID",
        "V16 retained portability evidence changed",
    )
    _require(
        retained_diagnostic == import_summary["v11_rawjson_diagnostic"],
        "V16_PORTABILITY_BINDING_INVALID",
        "V16 retained compatibility diagnostic changed",
    )
    _v13._validate_pre_predicate_diagnostic(
        retained_pre_predicate,
        retained_diagnostic,
    )
    producer_digests = _identity_digests(producer["identity_chain"])
    import_digests = _identity_digests(import_summary["identity_chain"])
    replay_digests = _identity_digests(replay_summary["identity_chain"])
    _require(
        producer_digests == import_digests == replay_digests,
        "V16_REPLAY_IDENTITY_DRIFT",
        "V16 replay identity chain changed",
    )
    proof = _read_summary(
        portability / "proof.json",
        label="V16 portability proof",
    )
    _require_exact_dict(
        proof,
        {
            "schema_version",
            "task",
            "release_commit",
            "manifest_sha256",
            "core_sums_sha256",
            "producer",
            "consumer",
            "pair",
            "cache_record",
            "import",
            "external_cache_removed_same_consumer_builder_replay",
            "identity_chain_digests",
            "controls",
        },
        "V16 portability proof",
        code="V16_PORTABILITY_INVALID",
    )
    _require(
        proof["schema_version"]
        == "noteai.admin-dependency-cache-portability.v16"
        and proof["task"] == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and proof["release_commit"] == RELEASE_COMMIT
        and proof["manifest_sha256"]
        == _base.sha256_file(bundle / "manifest.json")
        and proof["core_sums_sha256"]
        == _base.sha256_file(bundle / "CORE_SHA256SUMS")
        and proof["pair"] == pair
        and proof["cache_record"] == manifest["cache"]["record_provenance"]
        and proof["identity_chain_digests"]
        == {
            "producer": producer_digests,
            "consumer": import_digests,
            "replay": replay_digests,
        }
        and proof["import"] == import_summary | {"cache_from_local": True}
        and proof["external_cache_removed_same_consumer_builder_replay"]
        == replay_summary
        | {
            "cache_from_local": False,
            "external_cache_removed_before_replay": True,
            "same_consumer_builder_used": True,
            "full_committed_git_context_used": True,
            "true_empty_cache_replay_claimed": False,
        },
        "V16_PORTABILITY_INVALID",
        "V16 portability proof changed",
    )
    producer_builder = _require_exact_dict(
        proof["producer"],
        {
            "builder_name",
            "driver",
            "buildkit_version",
            "buildkit_daemon_image_reference",
            "buildkit_daemon_image_id",
        },
        "portability producer",
        code="V16_PORTABILITY_INVALID",
    )
    consumer_builder = _require_exact_dict(
        proof["consumer"],
        set(producer_builder),
        "portability consumer",
        code="V16_PORTABILITY_INVALID",
    )
    _require(
        isinstance(producer_builder["builder_name"], str)
        and bool(producer_builder["builder_name"])
        and isinstance(consumer_builder["builder_name"], str)
        and bool(consumer_builder["builder_name"])
        and producer_builder["builder_name"] != consumer_builder["builder_name"]
        and producer_builder["driver"]
        == consumer_builder["driver"]
        == "docker-container"
        and producer_builder["buildkit_version"]
        == consumer_builder["buildkit_version"]
        == manifest["build"]["buildkit_version"]
        and producer_builder["buildkit_daemon_image_reference"]
        == consumer_builder["buildkit_daemon_image_reference"]
        == manifest["build"]["buildkit_daemon_image_reference"]
        and producer_builder["buildkit_daemon_image_id"]
        == consumer_builder["buildkit_daemon_image_id"]
        == manifest["build"]["buildkit_daemon_image_id"],
        "V16_PORTABILITY_INVALID",
        "V16 producer/consumer BuildKit identity changed",
    )
    _require(
        proof["controls"]
        == {
            "github_run_attempt": 1,
            "image_or_registry_output_requested": False,
            "full_committed_git_context_supplied": True,
            "local_workspace_main_context_supplied": False,
            "local_dockerfile_supplied_via_stdin": True,
            "credential_or_secret_values_supplied": False,
            "default_git_auth_secret_ids_present": True,
            "external_cache_removed_before_replay": True,
            "same_consumer_builder_used_for_replay": True,
            "true_empty_cache_replay_claimed": False,
            "upload_allowed_only_after_cleanup": True,
        },
        "V16_PORTABILITY_INVALID",
        "V16 portability controls changed",
    )
    return proof


def validate_final(
    bundle: Path,
    extract_to: Path,
    expected_sums_sha256: str | None,
) -> dict[str, Any]:
    bundle = Path(bundle)
    files = _base.relative_regular_files(bundle)
    artifact_input_bytes = _base.validate_bundle_size(bundle, files)
    _require(
        FINAL_ADDITIONS <= files,
        "V16_BUNDLE_INVALID",
        "V16 portability evidence missing",
    )
    sums_sha256 = _base.validate_checksum_file(
        bundle,
        "SHA256SUMS",
        files - {"SHA256SUMS"},
    )
    if expected_sums_sha256 is not None:
        _require_sha256(expected_sums_sha256, "expected final sums hash")
        _require(
            sums_sha256 == expected_sums_sha256,
            "V16_FINAL_SUMS_INVALID",
            "final sums trust root changed",
        )
    validation_context: dict[str, Any] = {}
    manifest = validate_core(
        bundle,
        Path(extract_to),
        validation_context=validation_context,
    )
    record_sha256 = validation_context.get("validated_cache_record_sha256")
    _require(
        isinstance(record_sha256, str)
        and SHA256_RE.fullmatch(record_sha256) is not None,
        "V16_CACHE_RECORD_TRUST_INVALID",
        "V16 core validation did not capture the cache record",
    )
    proof = validate_portability(
        bundle,
        manifest,
        expected_cache_record_sha256=record_sha256,
    )
    return {
        "manifest_sha256": _base.sha256_file(bundle / "manifest.json"),
        "core_sums_sha256": _base.sha256_file(bundle / "CORE_SHA256SUMS"),
        "final_sums_sha256": sums_sha256,
        "portability_proof_sha256": _base.sha256_file(
            bundle / "portability" / "proof.json"
        ),
        "validated_cache_record_sha256": record_sha256,
        "control_commit": manifest["control"]["control_commit"],
        "request_sha256": manifest["control"]["request_sha256"],
        "github_run_id": manifest["control"]["github_run_id"],
        "github_run_attempt": manifest["control"]["github_run_attempt"],
        "producer_buildkit_version": manifest["build"]["buildkit_version"],
        "consumer_buildkit_version": proof["consumer"]["buildkit_version"],
        "pair_classification": proof["pair"]["classification"],
        "replay_kind": "external-cache-removed-same-consumer-builder",
        "true_empty_cache_replay_claimed": False,
        "artifact_input_bytes": artifact_input_bytes,
        "artifact_input_maximum_bytes": _base.MAXIMUM_ARTIFACT_INPUT_BYTES,
        "artifact_provider_maximum_bytes": _base.MAXIMUM_PROVIDER_ARTIFACT_BYTES,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("verify-build")
    build.add_argument("--metadata", type=Path, required=True)
    build.add_argument("--progress", type=Path, required=True)
    build.add_argument("--dockerfile", choices=("prefix", "full"), required=True)
    build.add_argument("--require-network-cached", action="store_true")
    build.add_argument("--producer-summary", type=Path)
    build.add_argument("--cache-record", type=Path)
    build.add_argument("--expected-cache-record-sha256")
    build.add_argument("--pre-predicate-diagnostic-output", type=Path)
    build.add_argument("--diagnostic-output", type=Path)
    build.add_argument("--pair-output", type=Path)
    build.add_argument("--identity-output", type=Path)
    build.add_argument("--output", type=Path)
    record = subparsers.add_parser("verify-cache-record")
    record.add_argument("--cache-dir", type=Path, required=True)
    record.add_argument("--producer-summary", type=Path, required=True)
    record.add_argument("--output", type=Path)
    pair = subparsers.add_parser("verify-pair")
    pair.add_argument("--producer-summary", type=Path, required=True)
    pair.add_argument("--consumer-summary", type=Path, required=True)
    pair.add_argument("--output", type=Path)
    core = subparsers.add_parser("verify-core")
    core.add_argument("--bundle", type=Path, required=True)
    core.add_argument("--extract-to", type=Path, required=True)
    core.add_argument("--output", type=Path)
    final = subparsers.add_parser("verify-final")
    final.add_argument("--bundle", type=Path, required=True)
    final.add_argument("--extract-to", type=Path, required=True)
    final.add_argument("--expected-sums-sha256")
    final.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "verify-build":
            payload = validate_build_evidence(
                args.metadata.resolve(),
                args.progress.resolve(),
                dockerfile_kind=args.dockerfile,
                require_network_vertices_cached=args.require_network_cached,
                producer_summary_path=(
                    args.producer_summary.resolve()
                    if args.producer_summary
                    else None
                ),
                cache_record_path=(
                    args.cache_record.resolve() if args.cache_record else None
                ),
                expected_cache_record_sha256=(
                    args.expected_cache_record_sha256
                    if args.expected_cache_record_sha256
                    else None
                ),
                pre_predicate_diagnostic_output_path=(
                    args.pre_predicate_diagnostic_output.resolve()
                    if args.pre_predicate_diagnostic_output
                    else None
                ),
                diagnostic_output_path=(
                    args.diagnostic_output.resolve()
                    if args.diagnostic_output
                    else None
                ),
                pair_output_path=(
                    args.pair_output.resolve() if args.pair_output else None
                ),
                identity_output_path=(
                    args.identity_output.resolve()
                    if args.identity_output
                    else None
                ),
            )
        elif args.command == "verify-cache-record":
            payload = validate_cache_record(
                args.cache_dir.resolve(),
                args.producer_summary.resolve(),
            )
        elif args.command == "verify-pair":
            payload = validate_pair(
                args.producer_summary.resolve(),
                args.consumer_summary.resolve(),
            )
        elif args.command == "verify-core":
            context: dict[str, Any] = {}
            manifest = validate_core(
                args.bundle.resolve(),
                args.extract_to.resolve(),
                validation_context=context,
            )
            payload = {
                "manifest_sha256": _base.sha256_file(
                    args.bundle / "manifest.json"
                ),
                "core_sums_sha256": _base.sha256_file(
                    args.bundle / "CORE_SHA256SUMS"
                ),
                "control_commit": manifest["control"]["control_commit"],
                "validated_cache_record_sha256": context[
                    "validated_cache_record_sha256"
                ],
            }
        else:
            payload = validate_final(
                args.bundle.resolve(),
                args.extract_to.resolve(),
                args.expected_sums_sha256,
            )
        _write_json(args.output, payload)
    except (
        V16BundleError,
        _v13.V11BundleError,
        _v13._v10.V10BundleError,
        _v13._v10._v6._v3.BundleError,
        OSError,
    ) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
