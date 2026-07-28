#!/usr/bin/env python3
"""Collect Secret-free production managed-secret distribution evidence.

The collector reads only environment key names and filesystem/unit metadata.
It never emits environment values and never connects to a database, provider,
or network service.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_production_env_files import (
    ROLE_ALLOWED_SECRET_KEYS,
    is_secret_key_name,
)


TASK_ID = "PROD-FIRST-LAUNCH-MANAGED-SECRETS-001"
ROLE_FILES = {
    "api": "api.env",
    "admin": "admin.env",
    "payment": "payment.env",
    "ai_worker": "ai-worker.env",
    "xhs_trends": "xhs-trends.env",
    "xhs_tracking": "xhs-tracking.env",
}
HOST_ROLES = {
    "API-C": ("api", "admin", "payment", "ai_worker"),
    "API-F": ("api", "xhs_trends", "xhs_tracking"),
}
HOST_UNITS = {
    "API-C": ("noteai-api.service", "noteai-admin.service"),
    "API-F": ("noteai-api.service",),
}
ROTATION_TOOL = "noteai-rotate-production-secrets"
REVOCATION_TOOL = "noteai-revoke-production-secrets"
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _parse_key_names(
    path: Path,
    *,
    role: str,
) -> dict[str, int]:
    names: set[str] = set()
    key_count = 0
    secret_key_count = 0
    duplicate_key_count = 0
    rejected_key_count = 0
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[7:].lstrip()
            if "=" not in stripped:
                rejected_key_count += 1
                continue
            name = stripped.split("=", 1)[0].strip()
            if not _ENV_KEY.fullmatch(name):
                rejected_key_count += 1
                continue
            key_count += 1
            if name in names:
                duplicate_key_count += 1
            names.add(name)
            if is_secret_key_name(name):
                secret_key_count += 1
                if name not in ROLE_ALLOWED_SECRET_KEYS[role]:
                    rejected_key_count += 1
    return {
        "key_count": key_count,
        "secret_key_count": secret_key_count,
        "duplicate_key_count": duplicate_key_count,
        "rejected_key_count": rejected_key_count,
    }


def _file_evidence(path: Path, *, role: str) -> dict[str, Any]:
    try:
        file_stat = path.lstat()
    except OSError:
        return {
            "role": role,
            "file_label": ROLE_FILES[role],
            "present": False,
            "regular": False,
            "symlink": False,
            "root_owned": False,
            "mode": "0000",
            "root_only": False,
            "key_count": 0,
            "secret_key_count": 0,
            "duplicate_key_count": 0,
            "rejected_key_count": 0,
        }

    regular = stat.S_ISREG(file_stat.st_mode)
    symlink = stat.S_ISLNK(file_stat.st_mode)
    mode = stat.S_IMODE(file_stat.st_mode)
    root_owned = file_stat.st_uid == 0 and file_stat.st_gid == 0
    evidence: dict[str, Any] = {
        "role": role,
        "file_label": ROLE_FILES[role],
        "present": True,
        "regular": regular,
        "symlink": symlink,
        "root_owned": root_owned,
        "mode": f"{mode:04o}",
        "root_only": regular and not symlink and root_owned and mode == 0o600,
        "key_count": 0,
        "secret_key_count": 0,
        "duplicate_key_count": 0,
        "rejected_key_count": 0,
    }
    if not regular or symlink:
        evidence["rejected_key_count"] = 1
        return evidence
    try:
        evidence.update(_parse_key_names(path, role=role))
    except (OSError, UnicodeError):
        evidence["rejected_key_count"] = 1
    return evidence


def _unit_reference_counts(
    *,
    host_label: str,
    systemd_root: Path,
) -> dict[str, int]:
    contents: list[str] = []
    for unit in HOST_UNITS[host_label]:
        path = systemd_root / unit
        try:
            contents.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            contents.append("")
    combined = "\n".join(contents)
    return {
        ROLE_FILES[role]: combined.count(f"/etc/noteai/{ROLE_FILES[role]}")
        for role in HOST_ROLES[host_label]
    }


def _tool_evidence(path: Path) -> dict[str, Any]:
    try:
        file_stat = path.lstat()
    except OSError:
        return {
            "present": False,
            "regular": False,
            "symlink": False,
            "root_owned": False,
            "mode": "0000",
        }
    return {
        "present": True,
        "regular": stat.S_ISREG(file_stat.st_mode),
        "symlink": stat.S_ISLNK(file_stat.st_mode),
        "root_owned": file_stat.st_uid == 0 and file_stat.st_gid == 0,
        "mode": f"{stat.S_IMODE(file_stat.st_mode):04o}",
    }


def collect(
    host_label: str,
    *,
    env_root: Path = Path("/etc/noteai"),
    systemd_root: Path = Path("/etc/systemd/system"),
    sbin_root: Path = Path("/usr/local/sbin"),
) -> dict[str, Any]:
    if host_label not in HOST_ROLES:
        raise ValueError("host label is not supported")

    files = [
        _file_evidence(env_root / ROLE_FILES[role], role=role)
        for role in HOST_ROLES[host_label]
    ]
    present = [row for row in files if row["present"]]
    identities = {
        (path_stat.st_dev, path_stat.st_ino)
        for role in HOST_ROLES[host_label]
        if (path := env_root / ROLE_FILES[role]).exists()
        for path_stat in (path.stat(),)
    }
    backup_artifact_count = sum(
        1
        for pattern in ("*.bak", "*.backup", "*.prev", "*.old", "*~")
        for path in env_root.glob(pattern)
        if path.is_file() or path.is_symlink()
    )
    legacy_file: dict[str, Any] | None = None
    if host_label == "API-F":
        legacy_file = _file_evidence(
            env_root / "xhs.env",
            role="xhs_trends",
        )
        legacy_file["role"] = "legacy_xhs"
        legacy_file["file_label"] = "xhs.env"
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "observed",
        "host_label": host_label,
        "database_connection_count": 0,
        "provider_call_count": 0,
        "service_change_count": 0,
        "secret_values_emitted": 0,
        "expected_file_count": len(files),
        "present_file_count": len(present),
        "missing_file_count": len(files) - len(present),
        "root_only_file_count": sum(bool(row["root_only"]) for row in files),
        "rejected_key_count": sum(
            int(row["rejected_key_count"]) for row in files
        ),
        "duplicate_key_count": sum(
            int(row["duplicate_key_count"]) for row in files
        ),
        "distinct_present_file_count": len(identities),
        "backup_artifact_count": backup_artifact_count,
        "files": files,
        "legacy_file": legacy_file,
        "unit_reference_counts": _unit_reference_counts(
            host_label=host_label,
            systemd_root=systemd_root,
        ),
        "rotation_tool": _tool_evidence(sbin_root / ROTATION_TOOL),
        "revocation_tool": _tool_evidence(sbin_root / REVOCATION_TOOL),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Secret-free managed-secret file metadata."
    )
    parser.add_argument("--host-label", choices=tuple(HOST_ROLES), required=True)
    parser.add_argument("--env-root", type=Path, default=Path("/etc/noteai"))
    parser.add_argument(
        "--systemd-root",
        type=Path,
        default=Path("/etc/systemd/system"),
    )
    parser.add_argument(
        "--sbin-root",
        type=Path,
        default=Path("/usr/local/sbin"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(
        json.dumps(
            collect(
                args.host_label,
                env_root=args.env_root,
                systemd_root=args.systemd_root,
                sbin_root=args.sbin_root,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
