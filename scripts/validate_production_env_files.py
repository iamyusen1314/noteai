#!/usr/bin/env python3
"""Validate production role env files without exposing Secret values."""

from __future__ import annotations

import argparse
import re
import stat
from pathlib import Path
from typing import Iterable


ROLE_ALLOWED_SECRET_KEYS = {
    "api": frozenset(
        {
            "DATABASE_URL",
            "ANTHROPIC_API_KEY",
            "MOONSHOT_API_KEY",
            "AMAP_WEB_KEY",
            "BAIDU_MAP_AK",
            "TENCENT_MAP_KEY",
            "SERPAPI_API_KEY",
            "BING_SEARCH_API_KEY",
            "GOOGLE_API_KEY",
            "MEITUAN_AI_HUB_TOKEN",
            "MEITUAN_OPEN_TOKEN",
            "MEITUAN_SIGN_KEY",
            "MEITUAN_APP_AUTH_TOKEN",
            "MEITUAN_OPEN_APP_KEY",
            "MEITUAN_OPEN_APP_SECRET",
            "MEITUAN_OPEN_SIGN",
            "MEITUAN_OPEN_AES_KEY",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET",
            "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET",
            "NOTEAI_MARKET_TIMING_REFRESH_TOKEN",
            "NOTEAI_AUTHORIZED_TREND_TOKEN",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        }
    ),
    "admin": frozenset({"DATABASE_URL", "ADMIN_PASSWORD"}),
    "xhs": frozenset(
        {
            "DATABASE_URL",
            "NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_TOKEN",
            "NOTEAI_AUTHORIZED_TREND_TOKEN",
        }
    ),
}

_KNOWN_SECRET_KEYS = frozenset().union(*ROLE_ALLOWED_SECRET_KEYS.values())
_SECRET_NAME_PATTERN = re.compile(
    r"(?:PASSWORD|SECRET|TOKEN|COOKIE|CREDENTIALS?|PRIVATE_KEY|API_KEY|WEB_KEY|"
    r"ACCESS_KEY_ID|SECRET_ACCESS_KEY|SIGN_KEY|AES_KEY|AK)$"
)
_ENV_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class EnvFileValidationError(ValueError):
    """Raised when an env file violates the role boundary."""


def is_secret_key_name(name: str) -> bool:
    return (
        name == "DATABASE_URL"
        or name in _KNOWN_SECRET_KEYS
        or bool(_SECRET_NAME_PATTERN.search(name))
    )


def read_env_key_names(path: Path) -> tuple[str, ...]:
    if path.is_symlink() or not path.is_file():
        raise EnvFileValidationError(f"{path}: env file is missing or not regular")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise EnvFileValidationError(
            f"{path}: env file must not be group/world accessible"
        )

    names: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[7:].lstrip()
            if "=" not in stripped:
                raise EnvFileValidationError(
                    f"{path}:{line_number}: expected KEY=VALUE"
                )
            name = stripped.split("=", 1)[0].strip()
            if not _ENV_KEY_PATTERN.fullmatch(name):
                raise EnvFileValidationError(
                    f"{path}:{line_number}: invalid environment key name"
                )
            if name in seen:
                raise EnvFileValidationError(
                    f"{path}:{line_number}: duplicate key {name}"
                )
            seen.add(name)
            names.append(name)
    return tuple(names)


def validate_role_env_file(role: str, path: Path) -> dict[str, int | str]:
    if role not in ROLE_ALLOWED_SECRET_KEYS:
        raise EnvFileValidationError(f"unknown production role: {role}")

    names = read_env_key_names(path)
    secret_names = tuple(name for name in names if is_secret_key_name(name))
    rejected = sorted(set(secret_names) - ROLE_ALLOWED_SECRET_KEYS[role])
    if rejected:
        raise EnvFileValidationError(
            f"{path}: role {role} rejects Secret key name(s): {', '.join(rejected)}"
        )
    return {
        "role": role,
        "key_count": len(names),
        "secret_key_count": len(secret_names),
    }


def validate_all_role_env_files(
    role_paths: Iterable[tuple[str, Path]],
) -> list[dict[str, int | str]]:
    results: list[dict[str, int | str]] = []
    file_identities: dict[tuple[int, int], str] = {}
    for role, path in role_paths:
        result = validate_role_env_file(role, path)
        file_stat = path.stat()
        identity = (file_stat.st_dev, file_stat.st_ino)
        prior_role = file_identities.get(identity)
        if prior_role is not None:
            raise EnvFileValidationError(
                f"roles {prior_role} and {role} must use distinct env files"
            )
        file_identities[identity] = role
        results.append(result)
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate production env-file key names by role. Values are never "
            "printed."
        )
    )
    parser.add_argument("--api", type=Path, required=True)
    parser.add_argument("--admin", type=Path, required=True)
    parser.add_argument("--xhs", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        results = validate_all_role_env_files(
            (("api", args.api), ("admin", args.admin), ("xhs", args.xhs))
        )
    except EnvFileValidationError as exc:
        print(f"FAIL: {exc}")
        return 1
    for result in results:
        print(
            f"PASS role={result['role']} keys={result['key_count']} "
            f"secret_keys={result['secret_key_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
