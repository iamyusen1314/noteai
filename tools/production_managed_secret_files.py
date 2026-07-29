#!/usr/bin/env python3
"""Stage and atomically promote production role env files.

Protected values enter only through stdin.  Results contain counts and fixed
labels only; values, connection strings, lengths and content hashes are never
emitted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_production_env_files import (
    EnvFileValidationError,
    validate_role_env_file,
)


TASK_ID = "PROD-FIRST-LAUNCH-MANAGED-SECRETS-001"
TASK_ROOT = Path("/var/lib/noteai/managed-secrets-v1")
ENV_ROOT = Path("/etc/noteai")
ROLE_FILES = {
    "api": "api.env",
    "admin": "admin.env",
    "payment": "payment.env",
    "ai_worker": "ai-worker.env",
    "xhs_trends": "xhs-trends.env",
    "xhs_tracking": "xhs-tracking.env",
}
ROLE_DATABASE_USERS = {
    "api": "noteai_app",
    "admin": "noteai_admin_runtime",
    "payment": "noteai_payment",
    "ai_worker": "noteai_ai_worker",
    "xhs_trends": "noteai_xhs_trends",
    "xhs_tracking": "noteai_xhs_tracking",
}
HOST_ROLES = {
    "API-C": ("api", "admin", "payment", "ai_worker"),
    "API-F": ("api", "xhs_trends", "xhs_tracking"),
}
STAGED_ROLES = {
    "API-C": ("admin", "payment", "ai_worker"),
    "API-F": ("xhs_trends", "xhs_tracking"),
}
NEW_FILE_ROLES = {
    "API-C": ("payment", "ai_worker"),
    "API-F": ("xhs_trends", "xhs_tracking"),
}
REQUIRED_KEYS = {
    "api": frozenset({"DATABASE_URL"}),
    "admin": frozenset({"DATABASE_URL", "ADMIN_PASSWORD"}),
    "payment": frozenset({"DATABASE_URL"}),
    "ai_worker": frozenset({"DATABASE_URL"}),
    "xhs_trends": frozenset({"DATABASE_URL"}),
    "xhs_tracking": frozenset({"DATABASE_URL"}),
}
MINIMAL_KEYS = {
    "payment": REQUIRED_KEYS["payment"],
    "ai_worker": REQUIRED_KEYS["ai_worker"],
}
LEGACY_XHS_FILE = "xhs.env"
LEGACY_XHS_KEY = "NOTEAI_XHS_COOKIES_JSON"


class ManagedSecretFileError(RuntimeError):
    """A fixed, Secret-free managed-file failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _require_root() -> None:
    if os.geteuid() != 0:
        raise ManagedSecretFileError("root_required")


def _private_regular(path: Path, *, expected_uid: int = 0) -> None:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise ManagedSecretFileError("required_file_missing") from exc
    if not stat.S_ISREG(file_stat.st_mode) or stat.S_ISLNK(file_stat.st_mode):
        raise ManagedSecretFileError("file_not_regular")
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    if file_stat.st_uid != expected_uid or file_stat.st_gid != expected_gid:
        raise ManagedSecretFileError("file_owner")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ManagedSecretFileError("file_mode")


def _parse_env(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    names: set[str] = set()
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ManagedSecretFileError("env_read") from exc
    for raw_line in raw_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            raise ManagedSecretFileError("env_shape")
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not name or name in names:
            raise ManagedSecretFileError("env_keys")
        names.add(name)
        rows.append((name, value))
    return rows


def _database_user(database_url: str) -> str:
    if not isinstance(database_url, str) or any(
        character in database_url for character in ("\n", "\r", "\x00")
    ):
        raise ManagedSecretFileError("database_url_shape")
    try:
        parsed = urlsplit(database_url)
        username = unquote(parsed.username or "")
        password = parsed.password
        query_names = {
            item.split("=", 1)[0].lower()
            for item in parsed.query.split("&")
            if item
        }
    except (TypeError, ValueError) as exc:
        raise ManagedSecretFileError("database_url_shape") from exc
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not username
        or password in (None, "")
        or not parsed.hostname
        or parsed.path in {"", "/"}
        or parsed.fragment
        or {"user", "username", "password"} & query_names
    ):
        raise ManagedSecretFileError("database_url_shape")
    return username


def _validate_database_url(role: str, database_url: str) -> None:
    if _database_user(database_url) != ROLE_DATABASE_USERS[role]:
        raise ManagedSecretFileError("database_role_mismatch")


def _render(rows: list[tuple[str, str]]) -> str:
    return "".join(f"{name}={value}\n" for name, value in rows)


def _write_private(path: Path, body: str, *, owner_uid: int = 0) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            if os.geteuid() == 0:
                os.fchown(descriptor, owner_uid, owner_uid)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError as exc:
        raise ManagedSecretFileError("private_write") from exc


def _copy_private(source: Path, target: Path, *, owner_uid: int) -> None:
    _private_regular(source, expected_uid=owner_uid)
    try:
        shutil.copyfile(source, target, follow_symlinks=False)
        target.chmod(0o600)
        if os.geteuid() == 0:
            os.chown(target, owner_uid, owner_uid)
    except OSError as exc:
        raise ManagedSecretFileError("backup_write") from exc


def _validate_role_file(
    role: str,
    path: Path,
    *,
    expected_uid: int,
) -> None:
    _private_regular(path, expected_uid=expected_uid)
    try:
        validate_role_env_file(role, path)
    except EnvFileValidationError as exc:
        raise ManagedSecretFileError("role_file_contract") from exc
    rows = _parse_env(path)
    values = dict(rows)
    if not REQUIRED_KEYS[role].issubset(values):
        raise ManagedSecretFileError("required_keys")
    if role in MINIMAL_KEYS and set(values) != MINIMAL_KEYS[role]:
        raise ManagedSecretFileError("minimal_keys")
    if role in {"xhs_trends", "xhs_tracking"} and set(values) not in {
        frozenset({"DATABASE_URL"}),
        frozenset({"DATABASE_URL", LEGACY_XHS_KEY}),
    }:
        raise ManagedSecretFileError("minimal_keys")
    _validate_database_url(role, values["DATABASE_URL"])


def _validate_transition_admin(
    path: Path,
    *,
    expected_uid: int,
) -> None:
    _private_regular(path, expected_uid=expected_uid)
    try:
        validate_role_env_file("admin", path)
    except EnvFileValidationError as exc:
        raise ManagedSecretFileError("role_file_contract") from exc
    values = dict(_parse_env(path))
    if not REQUIRED_KEYS["admin"].issubset(values):
        raise ManagedSecretFileError("required_keys")
    if _database_user(values["DATABASE_URL"]) != "noteai_app":
        raise ManagedSecretFileError("admin_transition_prestate")


def _legacy_xhs_state(
    path: Path,
    *,
    expected_uid: int,
) -> dict[str, str]:
    _private_regular(path, expected_uid=expected_uid)
    values = dict(_parse_env(path))
    if not values or set(values) - {"DATABASE_URL", LEGACY_XHS_KEY}:
        raise ManagedSecretFileError("legacy_xhs_contract")
    database_url = values.get("DATABASE_URL")
    if (
        database_url is not None
        and _database_user(database_url) != "noteai_xhs"
    ):
        raise ManagedSecretFileError("legacy_xhs_database_role")
    cookie = values.get(LEGACY_XHS_KEY)
    if cookie is not None and not cookie:
        raise ManagedSecretFileError("legacy_xhs_contract")
    return values


def preflight_distribution(
    host_label: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path = TASK_ROOT,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    if host_label not in HOST_ROLES:
        raise ManagedSecretFileError("host_label")
    if task_root.exists() or task_root.is_symlink():
        raise ManagedSecretFileError("task_residue")
    _validate_role_file(
        "api",
        env_root / ROLE_FILES["api"],
        expected_uid=expected_uid,
    )
    legacy_cookie_present = 0
    legacy_database_url_present = 0
    if host_label == "API-C":
        _validate_transition_admin(
            env_root / ROLE_FILES["admin"],
            expected_uid=expected_uid,
        )
    else:
        legacy = _legacy_xhs_state(
            env_root / LEGACY_XHS_FILE,
            expected_uid=expected_uid,
        )
        legacy_cookie_present = int(LEGACY_XHS_KEY in legacy)
        legacy_database_url_present = int("DATABASE_URL" in legacy)
    if any(
        (env_root / ROLE_FILES[role]).exists()
        or (env_root / ROLE_FILES[role]).is_symlink()
        for role in NEW_FILE_ROLES[host_label]
    ):
        raise ManagedSecretFileError("final_file_preexists")
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "preflight_verified",
        "host_label": host_label,
        "existing_file_count": 2,
        "new_file_count": 0,
        "legacy_cookie_present": legacy_cookie_present,
        "legacy_database_url_present": legacy_database_url_present,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "database_connections": 0,
    }


def _manifest_path(task_root: Path) -> Path:
    return task_root / "manifest.json"


def _load_manifest(task_root: Path, host_label: str) -> dict[str, Any]:
    try:
        manifest = json.loads(
            _manifest_path(task_root).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManagedSecretFileError("manifest") from exc
    if (
        manifest.get("schema_version") != 1
        or manifest.get("task_id") != TASK_ID
        or manifest.get("host_label") != host_label
        or tuple(manifest.get("roles", ())) != STAGED_ROLES[host_label]
    ):
        raise ManagedSecretFileError("manifest")
    return manifest


def stage_distribution(
    host_label: str,
    protected_payload: dict[str, Any],
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path = TASK_ROOT,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    if host_label not in HOST_ROLES:
        raise ManagedSecretFileError("host_label")
    if task_root.exists() or task_root.is_symlink():
        raise ManagedSecretFileError("task_residue")
    database_urls = protected_payload.get("database_urls")
    if (
        set(protected_payload) != {"database_urls"}
        or not isinstance(database_urls, dict)
        or set(database_urls) != set(STAGED_ROLES[host_label])
    ):
        raise ManagedSecretFileError("protected_payload_shape")
    for role in STAGED_ROLES[host_label]:
        _validate_database_url(role, database_urls[role])

    preflight_distribution(
        host_label,
        env_root=env_root,
        task_root=task_root,
        expected_uid=expected_uid,
        require_root=False,
    )
    legacy_values: dict[str, str] = {}
    if host_label == "API-F":
        legacy_values = _legacy_xhs_state(
            env_root / LEGACY_XHS_FILE,
            expected_uid=expected_uid,
        )

    try:
        (task_root / "stage").mkdir(parents=True, mode=0o700)
        (task_root / "backup").mkdir(mode=0o700)
        task_root.chmod(0o700)
        if os.geteuid() == 0:
            os.chown(task_root, expected_uid, expected_uid)
            os.chown(task_root / "stage", expected_uid, expected_uid)
            os.chown(task_root / "backup", expected_uid, expected_uid)
    except OSError as exc:
        raise ManagedSecretFileError("task_root_create") from exc

    existed: dict[str, bool] = {}
    try:
        for role in STAGED_ROLES[host_label]:
            final_path = env_root / ROLE_FILES[role]
            existed[role] = final_path.exists()
            if existed[role]:
                _copy_private(
                    final_path,
                    task_root / "backup" / ROLE_FILES[role],
                    owner_uid=expected_uid,
                )

            if role == "admin":
                rows = _parse_env(final_path)
                replaced = False
                staged_rows: list[tuple[str, str]] = []
                for name, value in rows:
                    if name == "DATABASE_URL":
                        value = database_urls[role]
                        replaced = True
                    staged_rows.append((name, value))
                if not replaced:
                    staged_rows.insert(0, ("DATABASE_URL", database_urls[role]))
            elif role in {"xhs_trends", "xhs_tracking"}:
                staged_rows = [
                    ("DATABASE_URL", database_urls[role]),
                ]
                if LEGACY_XHS_KEY in legacy_values:
                    staged_rows.append(
                        (LEGACY_XHS_KEY, legacy_values[LEGACY_XHS_KEY])
                    )
            else:
                staged_rows = [("DATABASE_URL", database_urls[role])]
            staged_path = task_root / "stage" / ROLE_FILES[role]
            _write_private(
                staged_path,
                _render(staged_rows),
                owner_uid=expected_uid,
            )
            _validate_role_file(
                role,
                staged_path,
                expected_uid=expected_uid,
            )

        manifest = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "host_label": host_label,
            "roles": list(STAGED_ROLES[host_label]),
            "existed": existed,
            "promoted": False,
        }
        _write_private(
            _manifest_path(task_root),
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            owner_uid=expected_uid,
        )
    except BaseException:
        shutil.rmtree(task_root, ignore_errors=True)
        raise
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "staged",
        "host_label": host_label,
        "staged_file_count": len(STAGED_ROLES[host_label]),
        "secret_values_emitted": 0,
        "service_changes": 0,
        "database_connections": 0,
    }


def _restore(
    host_label: str,
    manifest: dict[str, Any],
    *,
    env_root: Path,
    task_root: Path,
) -> None:
    for role in reversed(STAGED_ROLES[host_label]):
        final_path = env_root / ROLE_FILES[role]
        backup_path = task_root / "backup" / ROLE_FILES[role]
        if bool(manifest["existed"][role]):
            if backup_path.exists():
                os.replace(backup_path, final_path)
        else:
            final_path.unlink(missing_ok=True)


def promote_distribution(
    host_label: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path = TASK_ROOT,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    manifest = _load_manifest(task_root, host_label)
    if manifest.get("promoted") is not False:
        raise ManagedSecretFileError("promotion_state")
    try:
        for role in STAGED_ROLES[host_label]:
            os.replace(
                task_root / "stage" / ROLE_FILES[role],
                env_root / ROLE_FILES[role],
            )
        for role in STAGED_ROLES[host_label]:
            _validate_role_file(
                role,
                env_root / ROLE_FILES[role],
                expected_uid=expected_uid,
            )
        manifest["promoted"] = True
        replacement = task_root / "manifest.next"
        _write_private(
            replacement,
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            owner_uid=expected_uid,
        )
        os.replace(replacement, _manifest_path(task_root))
    except BaseException as exc:
        try:
            _restore(
                host_label,
                manifest,
                env_root=env_root,
                task_root=task_root,
            )
        finally:
            shutil.rmtree(task_root, ignore_errors=True)
        if isinstance(exc, ManagedSecretFileError):
            raise
        raise ManagedSecretFileError("promotion_failed_rolled_back") from exc
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "promoted",
        "host_label": host_label,
        "promoted_file_count": len(STAGED_ROLES[host_label]),
        "rollback_available": True,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "database_connections": 0,
    }


def verify_distribution(
    host_label: str,
    *,
    env_root: Path = ENV_ROOT,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    if host_label not in HOST_ROLES:
        raise ManagedSecretFileError("host_label")
    identities: set[tuple[int, int]] = set()
    for role in HOST_ROLES[host_label]:
        path = env_root / ROLE_FILES[role]
        _validate_role_file(role, path, expected_uid=expected_uid)
        file_stat = path.stat()
        identities.add((file_stat.st_dev, file_stat.st_ino))
    if len(identities) != len(HOST_ROLES[host_label]):
        raise ManagedSecretFileError("file_identity_reuse")
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "host_label": host_label,
        "verified_file_count": len(HOST_ROLES[host_label]),
        "distinct_file_count": len(identities),
        "secret_values_emitted": 0,
        "service_changes": 0,
        "database_connections": 0,
    }


def rollback_distribution(
    host_label: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path = TASK_ROOT,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    manifest = _load_manifest(task_root, host_label)
    _restore(
        host_label,
        manifest,
        env_root=env_root,
        task_root=task_root,
    )
    shutil.rmtree(task_root)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "rolled_back",
        "host_label": host_label,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "database_connections": 0,
    }


def finalize_distribution(
    host_label: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path = TASK_ROOT,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    manifest = _load_manifest(task_root, host_label)
    if manifest.get("promoted") is not True:
        raise ManagedSecretFileError("finalize_before_promotion")
    verify_distribution(
        host_label,
        env_root=env_root,
        expected_uid=expected_uid,
        require_root=require_root,
    )
    legacy_removed = 0
    if host_label == "API-F":
        legacy_path = env_root / LEGACY_XHS_FILE
        if legacy_path.exists():
            legacy_path.unlink()
            legacy_removed = 1
    shutil.rmtree(task_root)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "finalized",
        "host_label": host_label,
        "legacy_file_removed": legacy_removed,
        "rollback_artifact_count": 0,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "database_connections": 0,
    }


def _protected_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManagedSecretFileError("protected_payload_parse") from exc
    if not isinstance(payload, dict):
        raise ManagedSecretFileError("protected_payload_shape")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "preflight",
            "stage",
            "promote",
            "verify",
            "rollback",
            "finalize",
        ),
    )
    parser.add_argument("--host-label", choices=tuple(HOST_ROLES), required=True)
    parser.add_argument("--env-root", type=Path, default=ENV_ROOT)
    parser.add_argument("--task-root", type=Path, default=TASK_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            result = preflight_distribution(
                args.host_label,
                env_root=args.env_root,
                task_root=args.task_root,
            )
        elif args.action == "stage":
            result = stage_distribution(
                args.host_label,
                _protected_payload(),
                env_root=args.env_root,
                task_root=args.task_root,
            )
        elif args.action == "promote":
            result = promote_distribution(
                args.host_label,
                env_root=args.env_root,
                task_root=args.task_root,
            )
        elif args.action == "verify":
            result = verify_distribution(
                args.host_label,
                env_root=args.env_root,
            )
        elif args.action == "rollback":
            result = rollback_distribution(
                args.host_label,
                env_root=args.env_root,
                task_root=args.task_root,
            )
        else:
            result = finalize_distribution(
                args.host_label,
                env_root=args.env_root,
                task_root=args.task_root,
            )
    except ManagedSecretFileError as exc:
        print(
            f"production_managed_secret_files=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
