#!/usr/bin/env python3
"""Apply the reviewed V3 BuildKit provenance contract to the V2 bundle format.

The V2 bundle format and its deep OCI/cache/tar validation remain frozen.  V3
loads that exact verifier by SHA-256, replaces only the build-evidence entry
point, and then delegates every other check to the frozen implementation.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any


BASE_VERIFIER_SHA256 = (
    "bf526c29b213dc15d257cb9aedc52790aa1dc9cf1f82bba0e6e85e41db3edf38"
)
EXPECTED_BUILDER_PLATFORM = "linux/amd64"
EXPECTED_TARGET_PLATFORM = {"Architecture": "amd64", "OS": "linux"}
EXPECTED_DOCKERFILE_FRONTEND_VERSION = "1.25.0"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_base_verifier():
    configured = os.environ.get("NOTEAI_BASE_BUNDLE_VERIFIER_PATH")
    base_path = (
        Path(configured).resolve()
        if configured
        else Path(__file__).resolve().with_name(
            "verify_admin_dependency_cache_bundle.py"
        )
    )
    if not base_path.is_file():
        raise RuntimeError("frozen V2 bundle verifier is missing")
    if _sha256_file(base_path) != BASE_VERIFIER_SHA256:
        raise RuntimeError("frozen V2 bundle verifier hash drift")
    spec = importlib.util.spec_from_file_location(
        "_noteai_admin_dependency_cache_bundle_v2",
        base_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen V2 bundle verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_base = _load_base_verifier()
_v2_validate_build_evidence = _base.validate_build_evidence


def _validate_v3_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    _base.require(isinstance(metadata, dict), "BuildKit metadata root changed")
    provenance = metadata.get("buildx.build.provenance")
    _base.require(isinstance(provenance, dict), "BuildKit provenance missing")
    invocation = provenance.get("invocation")
    _base.require(isinstance(invocation, dict), "BuildKit invocation missing")
    environment = invocation.get("environment")
    _base.require(
        environment
        == {
            "platform": EXPECTED_BUILDER_PLATFORM,
            "dockerfileVersion": EXPECTED_DOCKERFILE_FRONTEND_VERSION,
        },
        "BuildKit builder environment changed",
    )

    build_config = provenance.get("buildConfig")
    _base.require(isinstance(build_config, dict), "BuildKit max provenance missing")
    llb = build_config.get("llbDefinition")
    _base.require(isinstance(llb, list) and llb, "BuildKit LLB definition missing")
    target_platform_vertices = 0
    for item in llb:
        _base.require(isinstance(item, dict), "BuildKit LLB item changed")
        op = item.get("op")
        _base.require(isinstance(op, dict), "BuildKit LLB op changed")
        platform = op.get("platform")
        if platform is None:
            continue
        _base.require(
            platform == EXPECTED_TARGET_PLATFORM,
            "BuildKit target platform changed",
        )
        target_platform_vertices += 1
    _base.require(
        target_platform_vertices > 0,
        "BuildKit target platform evidence missing",
    )
    return {
        "builder_platform": environment["platform"],
        "dockerfile_frontend_version": environment["dockerfileVersion"],
        "target_platform": "linux/amd64",
        "target_platform_vertex_count": target_platform_vertices,
    }


def validate_build_evidence(
    metadata_path: Path,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    metadata_path = Path(metadata_path)
    metadata = _base.strict_json_file(metadata_path)
    v3_summary = _validate_v3_provenance(metadata)

    # The frozen V2 verifier incorrectly expected the complete environment
    # object to omit BuildKit v0.31.2's reviewed dockerfileVersion field.
    # Feed only that already-independently-validated legacy view into V2 while
    # preserving the original file bytes and hashes for every other check.
    legacy_metadata = copy.deepcopy(metadata)
    legacy_metadata["buildx.build.provenance"]["invocation"]["environment"] = {
        "platform": EXPECTED_BUILDER_PLATFORM
    }
    original_strict_json_file = _base.strict_json_file
    resolved_metadata_path = metadata_path.resolve()

    def strict_json_file_with_legacy_environment(path: Path):
        candidate = Path(path)
        if candidate.resolve() == resolved_metadata_path:
            return copy.deepcopy(legacy_metadata)
        return original_strict_json_file(candidate)

    _base.strict_json_file = strict_json_file_with_legacy_environment
    try:
        summary = _v2_validate_build_evidence(
            metadata_path,
            Path(progress_path),
            dockerfile_kind=dockerfile_kind,
            require_network_vertices_cached=require_network_vertices_cached,
        )
    finally:
        _base.strict_json_file = original_strict_json_file
    return summary | v3_summary


# Every frozen V2 call site resolves this module global at execution time.
_base.validate_build_evidence = validate_build_evidence


def __getattr__(name: str):
    return getattr(_base, name)


def main() -> int:
    return _base.main()


if __name__ == "__main__":
    raise SystemExit(main())
