#!/usr/bin/env python3
"""Fail-closed readiness accounting for the complete NoteAI first launch.

This tool validates a finite evidence ledger and computes three distinct
layers. It never contacts cloud services or providers and cannot turn a green
repository test suite into production evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "deploy" / "production" / "internal-deployment-readiness.json"
EXPECTED_LAYERS = ("repository_isolated", "internal_runtime", "public_launch")
VALID_STATUSES = {"verified", "unverified", "blocked"}
VALID_EVIDENCE_KINDS = {"git", "path"}
VALID_EXECUTION_CLASSES = {
    "repository_offline",
    "authenticated_production",
    "external_or_public",
    "professional_review",
}


class ManifestError(ValueError):
    """Raised when the readiness ledger is ambiguous or unverifiable."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _verify_git_ref(ref: str, *, root: Path) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _verify_path(ref: str, *, root: Path) -> bool:
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return False
    return resolved.is_file()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load readiness manifest: {exc}") from exc
    _require(isinstance(payload, dict), "manifest root must be an object")
    return payload


def validate_manifest(manifest: dict[str, Any], *, root: Path = ROOT) -> None:
    _require(manifest.get("schema_version") == 1, "unsupported schema_version")
    _require(
        manifest.get("task_id") == "PROD-COMPLETE-FIRST-LAUNCH-001",
        "unexpected umbrella task",
    )
    _require(
        set(manifest.get("status_values") or []) == VALID_STATUSES,
        "status_values must match the fail-closed status vocabulary",
    )
    layers = manifest.get("layers")
    _require(isinstance(layers, list), "layers must be a list")
    layer_ids = tuple(layer.get("id") for layer in layers if isinstance(layer, dict))
    _require(layer_ids == EXPECTED_LAYERS, "readiness layers are missing or out of order")

    controls_by_id: dict[str, dict[str, Any]] = {}
    for layer in layers:
        _require(
            layer.get("default_execution_class") in VALID_EXECUTION_CLASSES,
            f"{layer.get('id')}: invalid default_execution_class",
        )
        controls = layer.get("controls")
        _require(isinstance(controls, list) and controls, f"{layer.get('id')}: controls required")
        for control in controls:
            _require(isinstance(control, dict), "control must be an object")
            control_id = control.get("id")
            _require(
                isinstance(control_id, str) and control_id and control_id not in controls_by_id,
                f"duplicate or invalid control id: {control_id}",
            )
            _require(
                isinstance(control.get("title"), str) and control["title"].strip(),
                f"{control_id}: title required",
            )
            status = control.get("status")
            _require(status in VALID_STATUSES, f"{control_id}: invalid status {status}")
            _require(
                control.get("execution_class", layer["default_execution_class"])
                in VALID_EXECUTION_CLASSES,
                f"{control_id}: invalid execution_class",
            )
            dependencies = control.get("dependencies")
            _require(isinstance(dependencies, list), f"{control_id}: dependencies must be a list")
            _require(
                all(isinstance(item, str) and item for item in dependencies),
                f"{control_id}: invalid dependency",
            )
            evidence = control.get("evidence")
            _require(isinstance(evidence, list), f"{control_id}: evidence must be a list")
            if status == "verified":
                _require(evidence, f"{control_id}: verified without evidence")
                _require(not control.get("blocker"), f"{control_id}: verified with blocker")
            else:
                _require(
                    isinstance(control.get("blocker"), str) and control["blocker"].strip(),
                    f"{control_id}: non-verified control requires blocker",
                )
                _require(
                    isinstance(control.get("next_task"), str) and control["next_task"].strip(),
                    f"{control_id}: non-verified control requires next_task",
                )
            if status == "blocked":
                _require(
                    isinstance(control.get("resume_condition"), str)
                    and control["resume_condition"].strip(),
                    f"{control_id}: blocked control requires resume_condition",
                )
            for item in evidence:
                _require(isinstance(item, dict), f"{control_id}: invalid evidence entry")
                kind = item.get("kind")
                ref = item.get("ref")
                _require(kind in VALID_EVIDENCE_KINDS, f"{control_id}: invalid evidence kind")
                _require(isinstance(ref, str) and ref, f"{control_id}: evidence ref required")
                if kind == "git":
                    _require(_verify_git_ref(ref, root=root), f"{control_id}: missing git evidence {ref}")
                else:
                    _require(_verify_path(ref, root=root), f"{control_id}: missing path evidence {ref}")
            controls_by_id[control_id] = control

    for control_id, control in controls_by_id.items():
        for dependency in control["dependencies"]:
            _require(dependency in controls_by_id, f"{control_id}: unknown dependency {dependency}")
            _require(dependency != control_id, f"{control_id}: self dependency")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(control_id: str) -> None:
        if control_id in visiting:
            raise ManifestError(f"dependency cycle at {control_id}")
        if control_id in visited:
            return
        visiting.add(control_id)
        for dependency in controls_by_id[control_id]["dependencies"]:
            visit(dependency)
        visiting.remove(control_id)
        visited.add(control_id)

    for control_id in controls_by_id:
        visit(control_id)


def _score(controls: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(controls)
    verified = sum(item["status"] == "verified" for item in controls)
    blocked = sum(item["status"] == "blocked" for item in controls)
    percentage = (verified * 100 + total // 2) // total
    return {
        "passed": verified == total,
        "percentage": percentage,
        "verified": verified,
        "total": total,
        "blocked": blocked,
        "remaining": total - verified,
    }


def build_report(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest, root=root)
    layers: dict[str, dict[str, Any]] = {}
    controls_by_id: dict[str, dict[str, Any]] = {}
    for layer in manifest["layers"]:
        controls = layer["controls"]
        layers[layer["id"]] = _score(controls)
        controls_by_id.update({item["id"]: item for item in controls})

    internal_controls = [
        *manifest["layers"][0]["controls"],
        *manifest["layers"][1]["controls"],
    ]
    all_controls = [
        item
        for layer in manifest["layers"]
        for item in layer["controls"]
    ]
    actionable = []
    layer_by_control = {
        control["id"]: layer
        for layer in manifest["layers"]
        for control in layer["controls"]
    }
    for control in all_controls:
        if control["status"] == "verified":
            continue
        if all(
            controls_by_id[dependency]["status"] == "verified"
            for dependency in control["dependencies"]
        ):
            actionable.append(
                {
                    "id": control["id"],
                    "status": control["status"],
                    "next_task": control["next_task"],
                    "blocker": control["blocker"],
                    "execution_class": control.get(
                        "execution_class",
                        layer_by_control[control["id"]]["default_execution_class"],
                    ),
                }
            )
    safe_actionable = [
        item for item in actionable if item["execution_class"] == "repository_offline"
    ]
    return {
        "version": "noteai-internal-deployment-readiness-v1",
        "task_id": manifest["task_id"],
        "manifest_valid": True,
        "layers": layers,
        "internal_deployment": _score(internal_controls),
        "complete_public_launch": _score(all_controls),
        "actionable": actionable,
        "next_safe_task": safe_actionable[0] if safe_actionable else None,
        "blocked": [
            {
                "id": control["id"],
                "resume_condition": control["resume_condition"],
            }
            for control in all_controls
            if control["status"] == "blocked"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute fail-closed NoteAI deployment readiness."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require",
        choices=("manifest", "repository", "internal", "public"),
        default="manifest",
        help="Return non-zero unless the selected evidence layer is complete.",
    )
    args = parser.parse_args()
    try:
        report = build_report(args.manifest)
    except ManifestError as exc:
        print(f"internal_deployment_readiness=INVALID\nerror={exc}")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        internal = report["internal_deployment"]
        public = report["complete_public_launch"]
        print(
            "internal_deployment_readiness="
            f"{internal['percentage']}% ({internal['verified']}/{internal['total']})"
        )
        print(
            "complete_public_launch_readiness="
            f"{public['percentage']}% ({public['verified']}/{public['total']})"
        )
        for item in report["actionable"]:
            print(f"- {item['status']}: {item['next_task']} ({item['id']})")

    required = {
        "manifest": True,
        "repository": report["layers"]["repository_isolated"]["passed"],
        "internal": report["internal_deployment"]["passed"],
        "public": report["complete_public_launch"]["passed"],
    }[args.require]
    return 0 if required else 1


if __name__ == "__main__":
    raise SystemExit(main())
