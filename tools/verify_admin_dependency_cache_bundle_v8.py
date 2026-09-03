#!/usr/bin/env python3
"""Accept exact empty BuildKit source locations over the frozen V7 chain.

BuildKit v0.31.2 may serialize a vertex with no source ranges as an exact
empty location wrapper. V8 treats only ``{}`` as a nonbinding location and
delegates every populated-location, incremental-progress, role, decoded-log,
network, archive and legacy-view rule to the hash-pinned V7/V6/V3/V2 chain.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


V7_VERIFIER_SHA256 = (
    "76af4aa0c8dbe68b46cc71fb74f15820"
    "30c5f28a7218a2ee04bcbde5f4198cd7"
)


def _read_frozen_source(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{label} is missing") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 4_194_304
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
            if observed > 4_194_304:
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


def _load_v7_verifier():
    configured = os.environ.get("NOTEAI_V7_BUNDLE_VERIFIER_PATH")
    configured_path = (
        Path(configured)
        if configured
        else Path(__file__).with_name(
            "verify_admin_dependency_cache_bundle_v7.py"
        )
    )
    if configured_path.is_symlink():
        raise RuntimeError("frozen V7 bundle verifier file contract changed")
    v7_path = configured_path.resolve()
    v7_source = _read_frozen_source(
        v7_path,
        label="frozen V7 bundle verifier",
    )
    if hashlib.sha256(v7_source).hexdigest() != V7_VERIFIER_SHA256:
        raise RuntimeError("frozen V7 bundle verifier hash drift")

    module_name = "_noteai_admin_dependency_cache_bundle_v7_for_v8"
    module = types.ModuleType(module_name)
    module.__file__ = str(v7_path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(
            compile(v7_source, str(v7_path), "exec"),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_v7 = _load_v7_verifier()
_v6 = _v7._v6
_FROZEN_V6_RANGE_PROJECTION = _v6._range_projection
_FROZEN_V7_INITIAL_DIAGNOSTIC = _v7._initial_diagnostic
_FROZEN_V7_EMIT_DIAGNOSTIC = _v7._emit_diagnostic
_FROZEN_V7_INTERNAL_VALIDATE_BUILD_EVIDENCE = (
    _v7._validate_build_evidence
)
_FROZEN_V7_VALIDATE_BUILD_EVIDENCE = _v7.validate_build_evidence
_FROZEN_V7_VALIDATE_CORE = _v7.validate_core
_FROZEN_V7_VALIDATE_FINAL = _v7.validate_final
_FROZEN_V7_MAIN = _v7.main


class V8BundleError(_v7.V7BundleError):
    """A fixed-code V8 failure safe for a public workflow log."""


def _fail(failure_code: str, message: str) -> None:
    raise V8BundleError(failure_code, message)


def _require(
    condition: bool,
    failure_code: str,
    message: str,
) -> None:
    if not condition:
        _fail(failure_code, message)


def _range_projection(
    location: Any,
    step_id: str,
) -> dict[str, set[int]]:
    if location == {}:
        return {"lines": set(), "starts": set()}
    return _FROZEN_V6_RANGE_PROJECTION(location, step_id)


def _initial_diagnostic(
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    diagnostic = _FROZEN_V7_INITIAL_DIAGNOSTIC(
        progress_path,
        dockerfile_kind=dockerfile_kind,
        require_network_vertices_cached=require_network_vertices_cached,
    )
    diagnostic["schema_version"] = (
        "noteai.admin-dependency-cache-v8-diagnostic.v1"
    )
    return diagnostic


def _emit_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(diagnostic)
    bounded["diagnostic_sha256"] = _v6._canonical_sha256(bounded)
    print(
        "noteai_v8_progress_diagnostic="
        + json.dumps(
            bounded,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    return bounded


def _validate_build_evidence(*args: Any, **kwargs: Any):
    try:
        summary = _FROZEN_V7_INTERNAL_VALIDATE_BUILD_EVIDENCE(
            *args,
            **kwargs,
        )
    except _v7.V7BundleError as exc:
        raise V8BundleError(
            exc.failure_code,
            str(exc),
        ) from None
    diagnostic = summary.pop("v7_rawjson_diagnostic")
    summary["v8_rawjson_diagnostic"] = diagnostic
    return summary


@contextmanager
def _patched_v7_empty_location_contract() -> Iterator[None]:
    with _v6._PATCH_LOCK:
        frozen = (
            (_v6, "_range_projection", _FROZEN_V6_RANGE_PROJECTION),
            (_v7, "_initial_diagnostic", _FROZEN_V7_INITIAL_DIAGNOSTIC),
            (_v7, "_emit_diagnostic", _FROZEN_V7_EMIT_DIAGNOSTIC),
            (
                _v7,
                "_validate_build_evidence",
                _FROZEN_V7_INTERNAL_VALIDATE_BUILD_EVIDENCE,
            ),
        )
        for target, name, expected in frozen:
            _require(
                getattr(target, name) is expected,
                "FROZEN_V7_DISPATCH_CHANGED",
                "frozen V7 validator dispatch changed",
            )
        replacements = (
            (_v6, "_range_projection", _range_projection),
            (_v7, "_initial_diagnostic", _initial_diagnostic),
            (_v7, "_emit_diagnostic", _emit_diagnostic),
            (_v7, "_validate_build_evidence", _validate_build_evidence),
        )
        for target, name, replacement in replacements:
            setattr(target, name, replacement)
        try:
            yield
        finally:
            for target, name, expected in frozen:
                setattr(target, name, expected)
            for target, name, expected in frozen:
                _require(
                    getattr(target, name) is expected,
                    "FROZEN_V7_DISPATCH_RESTORE_FAILED",
                    "frozen V7 validator dispatch restore failed",
                )


def __getattr__(name: str):
    return getattr(_v7, name)


def validate_build_evidence(*args: Any, **kwargs: Any):
    with _patched_v7_empty_location_contract():
        return _FROZEN_V7_VALIDATE_BUILD_EVIDENCE(*args, **kwargs)


def validate_core(*args: Any, **kwargs: Any):
    with _patched_v7_empty_location_contract():
        return _FROZEN_V7_VALIDATE_CORE(*args, **kwargs)


def validate_final(*args: Any, **kwargs: Any):
    with _patched_v7_empty_location_contract():
        return _FROZEN_V7_VALIDATE_FINAL(*args, **kwargs)


def main() -> int:
    with _patched_v7_empty_location_contract():
        return _FROZEN_V7_MAIN()


if __name__ == "__main__":
    raise SystemExit(main())
