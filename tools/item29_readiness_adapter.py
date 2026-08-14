#!/usr/bin/env python3
"""Narrow Item 29 semantic adapter for the production readiness gate.

This file is deliberately standalone while Item 28 is still editing the shared
gate.  After Item 28 freezes, the gate integration is a mechanical import plus
one call to ``validate_capacity_control``; no Item 29 predicate needs to be
reimplemented in the shared file.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from verify_capacity_100_jobs_evidence import (  # noqa: E402
    DEFAULT_READINESS,
    validate_item28_dependency,
    validate_manifest_evidence,
)


ADAPTER_REF = "tools/item29_readiness_adapter.py"


def validate_capacity_control(
    manifest: Any,
    controls_by_id: Any,
    *,
    root: Path = ROOT,
) -> list[str]:
    if type(manifest) is not dict or type(controls_by_id) is not dict:
        return ["capacity_100_jobs: readiness adapter input invalid"]
    capacity = controls_by_id.get("capacity_100_jobs")
    if type(capacity) is not dict:
        return ["capacity_100_jobs: control missing"]
    if capacity.get("status") != "verified":
        return []
    dependency_errors, dependency = validate_item28_dependency(
        controls_by_id, root=root
    )
    if dependency_errors or dependency is None:
        return [
            "capacity_100_jobs: Item28 dependency invalid: "
            + (dependency_errors[0] if dependency_errors else "missing")
        ]
    layers = manifest.get("layers")
    if type(layers) is not list or len(layers) != 3:
        return ["capacity_100_jobs: manifest layer contract invalid"]
    try:
        internal_controls = [*layers[0]["controls"], *layers[1]["controls"]]
        all_controls = [control for layer in layers for control in layer["controls"]]
    except (KeyError, TypeError):
        return ["capacity_100_jobs: manifest layer contract invalid"]
    internal_before = sum(
        type(control) is dict
        and control.get("id") != "capacity_100_jobs"
        and control.get("status") == "verified"
        for control in internal_controls
    )
    public_before = sum(
        type(control) is dict
        and control.get("id") != "capacity_100_jobs"
        and control.get("status") == "verified"
        for control in all_controls
    )
    if (
        len(internal_controls) != 29
        or len(all_controls) != 38
        or internal_before != 28
        or public_before != 28
    ):
        return ["capacity_100_jobs: exact 28/29 predecessor state required"]
    errors = validate_manifest_evidence(
        capacity.get("evidence"),
        root=root,
        expected_item28_dependency=dependency,
        expected_readiness=DEFAULT_READINESS,
    )
    return ["capacity_100_jobs: " + error for error in errors]
