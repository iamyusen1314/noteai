#!/usr/bin/env python3
"""Verify task-owned Docker/Buildx client state before V4 cache cleanup."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
from pathlib import Path


MAXIMUM_BUILDX_STATE_FILES = 512
MAXIMUM_BUILDX_STATE_BYTES = 16 * 1024 * 1024
MAXIMUM_DOCKER_CONFIG_BYTES = 128
BUILDKIT_IMAGE = (
    "moby/buildkit@sha256:"
    "2f5adac4ecd194d9f8c10b7b5d7bceb5186853db1b26e5abd3a657af0b7e26ec"
)
BUILDX_VERSION = "v0.35.0"
BUILDX_SOURCE_COMMIT = "a319e5b15052cf6557ceb666eb8ff6e32380b782"
EXPECTED_BUILDKITD_FLAGS = [
    "--allow-insecure-entitlement=network.host",
]
BUILDER_NAME_RE = re.compile(
    r"^noteai-admin-cache-v4-(?:producer|consumer)-[0-9]+$"
)
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DEFAULT_KEY_RE = re.compile(r"^[0-9a-f]{20}$")
RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
SENSITIVE_BUILD_STATE_RE = re.compile(
    rb"(?i)(password|authorization|identity[_-]?token|access[_-]?token|"
    rb"refresh[_-]?token|private[_-]?key|client[_-]?secret|credential|"
    rb"credsStore|credHelpers|-----BEGIN)"
)


class StateError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StateError(message)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON number: {value}")


def _parse_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _strict_json_bytes(payload: bytes, label: str):
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StateError(f"{label} JSON invalid") from exc


def _require_exact_keys(value, expected: set[str], label: str) -> dict:
    require(isinstance(value, dict), f"{label} is not an object")
    require(set(value) == expected, f"{label} keys changed")
    return value


def _require_safe_text(
    value,
    label: str,
    *,
    maximum: int = 4096,
    allow_empty: bool = True,
) -> str:
    require(isinstance(value, str), f"{label} is not text")
    require(allow_empty or bool(value), f"{label} is empty")
    require(len(value) <= maximum, f"{label} is too long")
    require(
        all(character.isprintable() and character not in "\r\n" for character in value),
        f"{label} contains control text",
    )
    require("\x00" not in value, f"{label} contains NUL")
    require(
        SENSITIVE_BUILD_STATE_RE.search(value.encode("utf-8")) is None,
        f"{label} contains credential-like text",
    )
    return value


def _require_builder_name(value, label: str) -> str:
    value = _require_safe_text(value, label, maximum=128, allow_empty=False)
    require(BUILDER_NAME_RE.fullmatch(value) is not None, f"{label} changed")
    return value


def _validate_platform(value, label: str) -> None:
    platform = _require_exact_keys(value, {"architecture", "os"}, label)
    require(
        platform == {"architecture": "amd64", "os": "linux"},
        f"{label} changed",
    )


def _validate_node_group(payload: bytes, label: str) -> None:
    group = _require_exact_keys(
        _strict_json_bytes(payload, label),
        {"Name", "Driver", "Nodes", "Dynamic"},
        label,
    )
    group_name = _require_builder_name(group["Name"], f"{label}.Name")
    require(group["Driver"] == "docker-container", f"{label}.Driver changed")
    require(group["Dynamic"] is False, f"{label}.Dynamic changed")
    require(
        isinstance(group["Nodes"], list) and len(group["Nodes"]) == 1,
        f"{label}.Nodes changed",
    )
    node = _require_exact_keys(
        group["Nodes"][0],
        {"Name", "Endpoint", "Platforms", "DriverOpts", "Flags", "Files"},
        f"{label}.Nodes[0]",
    )
    require(node["Name"] == f"{group_name}0", f"{label}.node name changed")
    require(
        node["Endpoint"] in ("default", "unix:///var/run/docker.sock"),
        f"{label}.endpoint changed",
    )
    platforms = node["Platforms"]
    require(
        platforms is None or isinstance(platforms, list),
        f"{label}.platforms changed",
    )
    if isinstance(platforms, list):
        require(len(platforms) <= 1, f"{label}.platform count changed")
        for index, platform in enumerate(platforms):
            _validate_platform(platform, f"{label}.Platforms[{index}]")
    require(
        node["DriverOpts"] == {"image": BUILDKIT_IMAGE},
        f"{label}.driver options changed",
    )
    require(
        node["Flags"] == EXPECTED_BUILDKITD_FLAGS,
        f"{label}.flags changed",
    )
    require(node["Files"] in (None, {}), f"{label}.embedded files changed")


def _validate_current(payload: bytes, label: str) -> None:
    current = _require_exact_keys(
        _strict_json_bytes(payload, label),
        {"Key", "Name", "Global"},
        label,
    )
    current_key = _require_safe_text(
        current["Key"],
        f"{label}.Key",
        maximum=512,
    )
    require(
        current_key in ("default", "unix:///var/run/docker.sock"),
        f"{label}.Key changed",
    )
    if current["Name"]:
        _require_builder_name(current["Name"], f"{label}.Name")
    require(isinstance(current["Global"], bool), f"{label}.Global changed")


def _validate_local_ref(payload: bytes, label: str) -> None:
    state = _strict_json_bytes(payload, label)
    require(isinstance(state, dict), f"{label} is not an object")
    require(
        set(state) in (
            {"Target", "LocalPath", "DockerfilePath"},
            {"Target", "LocalPath", "DockerfilePath", "GroupRef"},
        ),
        f"{label} keys changed",
    )
    _require_safe_text(state["Target"], f"{label}.Target", maximum=256)
    local_path = _require_safe_text(
        state["LocalPath"],
        f"{label}.LocalPath",
        allow_empty=False,
    )
    require(Path(local_path).is_absolute(), f"{label}.LocalPath is not absolute")
    require(".." not in Path(local_path).parts, f"{label}.LocalPath traverses")
    dockerfile_path = _require_safe_text(
        state["DockerfilePath"],
        f"{label}.DockerfilePath",
        allow_empty=False,
    )
    require(
        ".." not in Path(dockerfile_path).parts,
        f"{label}.DockerfilePath traverses",
    )
    if "GroupRef" in state:
        group_ref = _require_safe_text(
            state["GroupRef"],
            f"{label}.GroupRef",
            maximum=128,
            allow_empty=False,
        )
        require(
            SAFE_COMPONENT_RE.fullmatch(group_ref) is not None,
            f"{label}.GroupRef changed",
        )


def _validate_local_group(payload: bytes, label: str) -> None:
    group = _strict_json_bytes(payload, label)
    require(isinstance(group, dict), f"{label} is not an object")
    require(
        set(group) in ({"Refs"}, {"Targets", "Refs"}),
        f"{label} keys changed",
    )
    targets = group.get("Targets", [])
    require(
        isinstance(targets, list)
        and len(targets) <= 64
        and isinstance(group["Refs"], list)
        and 1 <= len(group["Refs"]) <= 64,
        f"{label} lists changed",
    )
    for key, values in (("Targets", targets), ("Refs", group["Refs"])):
        for index, value in enumerate(values):
            text = _require_safe_text(
                value,
                f"{label}.{key}[{index}]",
                maximum=512,
                allow_empty=False,
            )
            require(
                all(
                    SAFE_COMPONENT_RE.fullmatch(component) is not None
                    for component in text.split("/")
                ),
                f"{label}.{key}[{index}] changed",
            )


def _validate_buildx_path(relative: Path, payload: bytes | None) -> None:
    parts = relative.parts
    require(parts, "Buildx state path empty")
    if payload is None:
        if len(parts) == 1:
            require(
                parts[0] in {"instances", "defaults", "activity", "refs"},
                "Buildx state directory path changed",
            )
            return
        require(
            parts[0] == "refs" and 2 <= len(parts) <= 3,
            "Buildx state directory path changed",
        )
        if parts[1] == "__group__":
            require(
                len(parts) == 2,
                "Buildx state group directory path changed",
            )
            return
        builder_name = _require_builder_name(
            parts[1],
            "Buildx refs builder directory",
        )
        if len(parts) == 3:
            require(
                parts[2] == f"{builder_name}0",
                "Buildx refs node directory changed",
            )
        return

    label = f"Buildx state {relative.as_posix()}"
    require(
        SENSITIVE_BUILD_STATE_RE.search(payload) is None,
        "credential-like Buildx state found",
    )
    if parts == (".lock",):
        require(payload == b"", "Buildx lock content changed")
    elif parts == ("current",):
        _validate_current(payload, label)
    elif len(parts) == 2 and parts[0] == "instances":
        _require_builder_name(parts[1], f"{label} filename")
        _validate_node_group(payload, label)
    elif len(parts) == 2 and parts[0] == "defaults":
        require(
            DEFAULT_KEY_RE.fullmatch(parts[1]) is not None,
            "Buildx default key changed",
        )
        _require_builder_name(
            payload.decode("utf-8"),
            f"{label} builder",
        )
    elif len(parts) == 2 and parts[0] == "activity":
        _require_builder_name(parts[1], f"{label} filename")
        try:
            activity = payload.decode("ascii")
        except UnicodeDecodeError as exc:
            raise StateError("Buildx activity encoding changed") from exc
        require(
            RFC3339_RE.fullmatch(activity) is not None,
            "Buildx activity timestamp changed",
        )
    elif parts == ("refs", "version"):
        require(payload == b"2", "Buildx local-state version changed")
    elif len(parts) == 3 and parts[:2] == ("refs", "__group__"):
        require(
            SAFE_COMPONENT_RE.fullmatch(parts[2]) is not None,
            "Buildx group filename changed",
        )
        _validate_local_group(payload, label)
    elif len(parts) == 4 and parts[0] == "refs":
        builder_name = _require_builder_name(
            parts[1],
            "Buildx ref builder",
        )
        require(
            parts[2] == f"{builder_name}0",
            "Buildx ref node changed",
        )
        require(
            SAFE_COMPONENT_RE.fullmatch(parts[3]) is not None,
            "Buildx ref identifier changed",
        )
        _validate_local_ref(payload, label)
    else:
        raise StateError("Buildx state file path changed")


def _require_exact_task_roots(
    runner_temp: Path,
    docker_config: Path,
    buildx_config: Path,
) -> None:
    require(runner_temp.is_absolute(), "RUNNER_TEMP must be absolute")
    require(
        docker_config == runner_temp / "noteai-empty-docker-config-v4",
        "Docker config root changed",
    )
    require(
        buildx_config == runner_temp / "noteai-buildx-state-v4",
        "Buildx config root changed",
    )
    require(docker_config != buildx_config, "Docker and Buildx roots overlap")
    require(not runner_temp.is_symlink(), "RUNNER_TEMP is a symlink")


def validate_active_state(
    runner_temp: Path,
    docker_config: Path,
    buildx_config: Path,
) -> dict[str, int | str]:
    runner_temp = runner_temp.absolute()
    docker_config = docker_config.absolute()
    buildx_config = buildx_config.absolute()
    _require_exact_task_roots(runner_temp, docker_config, buildx_config)
    runner_temp = runner_temp.resolve(strict=True)
    docker_config = docker_config.resolve(strict=True)
    buildx_config = buildx_config.resolve(strict=True)
    _require_exact_task_roots(runner_temp, docker_config, buildx_config)

    for root, label in (
        (docker_config, "Docker config"),
        (buildx_config, "Buildx config"),
    ):
        require(root.exists(), f"{label} root missing")
        require(not root.is_symlink(), f"{label} root is a symlink")
        require(root.is_dir(), f"{label} root is not a directory")
        require(_mode(root) == 0o700, f"{label} root mode changed")
        require(root.resolve() == root, f"{label} root escaped RUNNER_TEMP")

    docker_entries = list(docker_config.iterdir())
    require(
        [entry.name for entry in docker_entries] == ["config.json"],
        "Docker config contains Buildx or unexpected state",
    )
    config_path = docker_config / "config.json"
    config_stat = config_path.lstat()
    require(stat.S_ISREG(config_stat.st_mode), "Docker config is not regular")
    require(config_stat.st_nlink == 1, "Docker config hardlink count changed")
    require(_mode(config_path) == 0o600, "Docker config mode changed")
    require(
        config_stat.st_size <= MAXIMUM_DOCKER_CONFIG_BYTES,
        "Docker config size exceeded",
    )
    try:
        config_payload = config_path.read_bytes()
    except OSError as exc:
        raise StateError("cannot read Docker config") from exc
    config = _strict_json_bytes(config_payload, "Docker config")
    require(config == {"auths": {}}, "Docker auth config changed")

    buildx_files = 0
    buildx_bytes = 0
    for path in buildx_config.rglob("*"):
        item_stat = path.lstat()
        require(not stat.S_ISLNK(item_stat.st_mode), "Buildx state symlink found")
        if stat.S_ISDIR(item_stat.st_mode):
            require(
                _mode(path) == 0o700,
                "Buildx state directory mode changed",
            )
            _validate_buildx_path(
                path.relative_to(buildx_config),
                None,
            )
            continue
        require(stat.S_ISREG(item_stat.st_mode), "Buildx special file found")
        require(item_stat.st_nlink == 1, "Buildx state hardlink found")
        require(
            _mode(path) in (0o600, 0o644),
            "Buildx state file mode changed",
        )
        buildx_files += 1
        buildx_bytes += item_stat.st_size
        require(
            buildx_files <= MAXIMUM_BUILDX_STATE_FILES,
            "Buildx state file count exceeded",
        )
        require(
            buildx_bytes <= MAXIMUM_BUILDX_STATE_BYTES,
            "Buildx state bytes exceeded",
        )
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise StateError("cannot read Buildx state") from exc
        _validate_buildx_path(
            path.relative_to(buildx_config),
            payload,
        )

    return {
        "docker_config_files": 1,
        "buildx_state_files": buildx_files,
        "buildx_state_bytes": buildx_bytes,
        "docker_auth_entries": 0,
        "roots_distinct": "true",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-temp", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--buildx-config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = validate_active_state(
            args.runner_temp,
            args.docker_config,
            args.buildx_config,
        )
    except StateError as exc:
        print(f"FAIL: {exc}", file=os.sys.stderr)
        return 1
    if args.output:
        args.output.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print("admin_dependency_cache_transient_state=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
