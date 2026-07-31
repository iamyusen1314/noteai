#!/usr/bin/env python3
"""Verify phase-aware task-owned Docker/Buildx client state for V5."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
from pathlib import Path


BASE_VERIFIER_SHA256 = (
    "a6578845bc220f38ffc819ced26d8d0c3530b37e53ebc4c74cceeb4b523ea432"
)
CLIENT_TOKEN_CONTROL = "BUILDKIT_NO_CLIENT_TOKEN"
BUILDER_NAME_RE = re.compile(
    r"^noteai-admin-cache-v5-(?:producer|consumer)-[0-9]+$"
)
BUILD_NODE_ID_RE = re.compile(rb"^[0-9a-f]{16}$")
PHASES = ("pre-build", "post-build", "cleanup-active")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_base(path: Path):
    path = path.absolute()
    item = path.lstat()
    if path.is_symlink() or not path.is_file() or item.st_nlink != 1:
        raise RuntimeError("base verifier shape changed")
    if _sha256(path) != BASE_VERIFIER_SHA256:
        raise RuntimeError("base verifier hash changed")
    spec = importlib.util.spec_from_file_location(
        "noteai_admin_cache_transient_v4_frozen",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("base verifier loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_base(base, phase: str) -> None:
    base.BUILDER_NAME_RE = BUILDER_NAME_RE

    def require_exact_task_roots(
        runner_temp: Path,
        docker_config: Path,
        buildx_config: Path,
    ) -> None:
        base.require(runner_temp.is_absolute(), "RUNNER_TEMP must be absolute")
        base.require(
            docker_config == runner_temp / "noteai-empty-docker-config-v5",
            "Docker config root changed",
        )
        base.require(
            buildx_config == runner_temp / "noteai-buildx-state-v5",
            "Buildx config root changed",
        )
        base.require(
            docker_config != buildx_config,
            "Docker and Buildx roots overlap",
        )
        base.require(
            not runner_temp.is_symlink(),
            "RUNNER_TEMP is a symlink",
        )

    original_node_group = base._validate_node_group

    def validate_node_group(payload: bytes, label: str) -> None:
        group = base._strict_json_bytes(payload, label)
        base.require(isinstance(group, dict), f"{label} is not an object")
        nodes = group.get("Nodes")
        base.require(
            isinstance(nodes, list) and len(nodes) == 1,
            f"{label}.Nodes changed",
        )
        node = nodes[0]
        base.require(
            isinstance(node, dict),
            f"{label}.Nodes[0] changed",
        )
        base.require(
            node.get("DriverOpts")
            == {
                "image": base.BUILDKIT_IMAGE,
                "provenance-add-gha": "false",
            },
            f"{label}.driver options changed",
        )
        normalized = copy.deepcopy(group)
        normalized["Nodes"][0]["DriverOpts"] = {
            "image": base.BUILDKIT_IMAGE,
        }
        original_node_group(
            json.dumps(
                normalized,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            label,
        )

    original_buildx_path = base._validate_buildx_path

    def validate_buildx_path(relative: Path, payload: bytes | None) -> None:
        if relative.parts == (".buildNodeID",):
            base.require(payload is not None, "Build node ID is not regular")
            base.require(
                BUILD_NODE_ID_RE.fullmatch(payload) is not None,
                "Build node ID shape changed",
            )
            return
        original_buildx_path(relative, payload)

    base._require_exact_task_roots = require_exact_task_roots
    base._validate_node_group = validate_node_group
    base._validate_buildx_path = validate_buildx_path
    base._noteai_v5_phase = phase


def validate(
    *,
    base_verifier: Path,
    runner_temp: Path,
    docker_config: Path,
    buildx_config: Path,
    phase: str,
) -> dict[str, int | str | bool]:
    if phase not in PHASES:
        raise RuntimeError("phase changed")
    if os.environ.get(CLIENT_TOKEN_CONTROL) != "1":
        raise RuntimeError("client token control changed")
    base = _load_base(base_verifier)
    _patch_base(base, phase)
    summary = base.validate_active_state(
        runner_temp,
        docker_config,
        buildx_config,
    )
    node_id = buildx_config.absolute() / ".buildNodeID"
    node_id_present = os.path.lexists(node_id)
    if node_id_present:
        node_stat = node_id.lstat()
        base.require(
            stat.S_ISREG(node_stat.st_mode),
            "Build node ID is not regular",
        )
        base.require(node_stat.st_nlink == 1, "Build node ID hardlink found")
        base.require(
            stat.S_IMODE(node_stat.st_mode) == 0o600,
            "Build node ID mode changed",
        )
        base.require(node_stat.st_size == 16, "Build node ID size changed")
    if phase == "pre-build":
        base.require(not node_id_present, "Build node ID appeared before build")
    elif phase == "post-build":
        base.require(node_id_present, "Build node ID missing after build")
    summary.update(
        {
            "phase": phase,
            "client_token_disabled": True,
            "build_node_id_present": node_id_present,
            "build_node_id_shape": "pass" if node_id_present else "not_present",
        }
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-verifier", type=Path, required=True)
    parser.add_argument("--runner-temp", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--buildx-config", type=Path, required=True)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = validate(
            base_verifier=args.base_verifier,
            runner_temp=args.runner_temp,
            docker_config=args.docker_config,
            buildx_config=args.buildx_config,
            phase=args.phase,
        )
        if args.output:
            args.output.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except Exception:
        print("FAIL: transient_state_contract_changed", file=os.sys.stderr)
        return 1
    print(
        "admin_dependency_cache_transient_state_v5=PASS "
        f"phase={args.phase}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
