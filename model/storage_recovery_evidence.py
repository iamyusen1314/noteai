"""Content-free backup/PITR restore evidence.

This module reads a database and private object inventory, hashes row values
in-process, and emits only schema names, bounded counts, clocks and aggregate
digests. It never performs a restore, database write or object write.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

import db
import durable_ai
import private_storage


CONTRACT_VERSION = "noteai-recovery-evidence-v1"
MAX_TABLES = 256
MAX_ROWS_PER_TABLE = 1_000_000
MAX_OBJECTS = 100_000
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RecoveryEvidenceError(RuntimeError):
    pass


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("recovery evidence clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: bytes | str) -> str:
    body = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if normalized != value or not minimum <= normalized <= maximum:
        raise ValueError(f"{label} is outside the allowed range")
    return normalized


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(str(value or "")):
        raise RecoveryEvidenceError("unsafe database identifier")
    return f'"{value}"'


def _encoded_cell(value: Any) -> bytes:
    if value is None:
        return b"N"
    if isinstance(value, bytes):
        return b"B" + str(len(value)).encode() + b":" + hashlib.sha256(value).digest()
    if isinstance(value, bool):
        return b"T1" if value else b"T0"
    if isinstance(value, int):
        return b"I" + str(value).encode()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RecoveryEvidenceError("non-finite database value")
        return b"F" + value.hex().encode()
    encoded = str(value).encode("utf-8")
    return b"S" + str(len(encoded)).encode() + b":" + encoded


def _table_names(storage: Any) -> list[str]:
    if bool(getattr(storage, "postgres", db.using_postgres())):
        rows = storage.fetchall(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        )
    else:
        rows = storage.fetchall(
            "SELECT name AS table_name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    names = [str(row["table_name"]) for row in rows]
    if len(names) > MAX_TABLES:
        raise RecoveryEvidenceError("database table count exceeds evidence limit")
    for name in names:
        _quote_identifier(name)
    return names


def _table_columns(storage: Any, table: str) -> list[dict[str, Any]]:
    _quote_identifier(table)
    if bool(getattr(storage, "postgres", db.using_postgres())):
        rows = storage.fetchall(
            "SELECT c.column_name,c.data_type,c.is_nullable,c.ordinal_position,"
            "COALESCE(k.primary_key_ordinal,0) AS primary_key_ordinal "
            "FROM information_schema.columns c "
            "LEFT JOIN ("
            "SELECT kcu.table_schema,kcu.table_name,kcu.column_name,"
            "kcu.ordinal_position AS primary_key_ordinal "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON kcu.constraint_name=tc.constraint_name "
            "AND kcu.constraint_schema=tc.constraint_schema "
            "WHERE tc.constraint_type='PRIMARY KEY'"
            ") k ON k.table_schema=c.table_schema "
            "AND k.table_name=c.table_name AND k.column_name=c.column_name "
            "WHERE c.table_schema='public' AND c.table_name=? "
            "ORDER BY c.ordinal_position",
            (table,),
        )
        return [
            {
                "name": str(row["column_name"]),
                "type": str(row["data_type"]),
                "nullable": str(row["is_nullable"]),
                "ordinal": int(row["ordinal_position"]),
                "primary_key_ordinal": int(row["primary_key_ordinal"] or 0),
            }
            for row in rows
        ]
    rows = storage.fetchall(f"PRAGMA table_info({_quote_identifier(table)})")
    return [
        {
            "name": str(row["name"]),
            "type": str(row["type"] or ""),
            "nullable": "NO" if int(row["notnull"] or 0) else "YES",
            "ordinal": int(row["cid"]) + 1,
            "primary_key_ordinal": int(row["pk"] or 0),
        }
        for row in rows
    ]


def _row_digest(
    storage: Any,
    table: str,
    columns: list[dict[str, Any]],
    *,
    max_rows: int,
) -> tuple[int, str]:
    names = [str(column["name"]) for column in columns]
    if not names:
        raise RecoveryEvidenceError("table has no columns")
    quoted_columns = ",".join(_quote_identifier(name) for name in names)
    order_columns = sorted(
        columns,
        key=lambda value: int(value.get("primary_key_ordinal") or 0),
    )
    primary = [
        str(value["name"])
        for value in order_columns
        if int(value.get("primary_key_ordinal") or 0) > 0
    ]
    order = primary or names
    order_sql = ",".join(_quote_identifier(name) for name in order)
    rows = storage.fetchall(
        f"SELECT {quoted_columns} FROM {_quote_identifier(table)} "
        f"ORDER BY {order_sql} LIMIT ?",
        (max_rows + 1,),
    )
    if len(rows) > max_rows:
        raise RecoveryEvidenceError(
            f"table {table} exceeds the bounded row evidence limit"
        )
    digest = hashlib.sha256()
    for row in rows:
        digest.update(b"R")
        for name in names:
            cell = _encoded_cell(row[name])
            digest.update(str(len(cell)).encode())
            digest.update(b":")
            digest.update(cell)
    return len(rows), digest.hexdigest()


def _migration_inventory(storage: Any, table_names: set[str]) -> list[dict[str, Any]]:
    if "schema_migrations" not in table_names:
        return []
    columns = {
        value["name"]
        for value in _table_columns(storage, "schema_migrations")
    }
    selected = ["version"]
    if "sha256" in columns:
        selected.append("sha256")
    rows = storage.fetchall(
        "SELECT " + ",".join(selected) + " FROM schema_migrations ORDER BY version"
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        entry = {"version": str(row["version"])}
        if "sha256" in selected:
            digest = str(row["sha256"] or "")
            if not _DIGEST_RE.fullmatch(digest):
                raise RecoveryEvidenceError("invalid migration ledger digest")
            entry["sha256"] = digest
        result.append(entry)
    return result


def _reference_inventory(storage: Any, table_names: set[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for table in ("ai_payload_refs", "private_media_refs"):
        if table not in table_names:
            values[table] = {"present": False, "total_count": 0, "states": {}}
            continue
        rows = storage.fetchall(
            f"SELECT state,COUNT(*) AS count,MIN(created_at) AS oldest_created_at,"
            f"MAX(created_at) AS newest_created_at FROM {_quote_identifier(table)} "
            "GROUP BY state ORDER BY state"
        )
        states = {
            str(row["state"]): {
                "count": int(row["count"]),
                "oldest_created_at": row["oldest_created_at"],
                "newest_created_at": row["newest_created_at"],
            }
            for row in rows
        }
        values[table] = {
            "present": True,
            "total_count": sum(value["count"] for value in states.values()),
            "states": states,
        }
    return values


def object_inventory(
    backend: private_storage.ObjectBackend,
    *,
    max_objects: int = MAX_OBJECTS,
) -> dict[str, Any]:
    maximum = _bounded_int(max_objects, "max_objects", 1, MAX_OBJECTS)
    aggregate = hashlib.sha256()
    count = 0
    size_bytes = 0
    cursor: str | None = None
    while True:
        remaining = maximum - count
        if remaining <= 0:
            raise RecoveryEvidenceError("private object inventory exceeds limit")
        objects, cursor = backend.list(
            "v1",
            limit=min(private_storage.MAX_OBJECT_LIST_LIMIT, remaining),
            cursor=cursor,
        )
        for item in objects:
            private_storage.validate_stored_object_descriptor(item)
            count += 1
            size_bytes += int(item.size_bytes)
            safe_record = {
                "key_hash": _sha(item.key),
                "size_bytes": int(item.size_bytes),
                "content_sha256": str(item.content_sha256),
                "reference_id_hash": _sha(
                    str(item.metadata.get("reference_id") or "")
                ),
                "purpose": str(item.metadata.get("purpose") or ""),
                "created_at": str(item.created_at),
                "expires_at": str(item.metadata.get("expires_at") or ""),
            }
            aggregate.update(_canonical_json(safe_record))
        if cursor is None:
            break
    return {
        "object_count": count,
        "size_bytes": size_bytes,
        "aggregate_sha256": aggregate.hexdigest(),
        "content_included": False,
        "object_keys_included": False,
    }


def _capture_manifest(
    *,
    release_commit: str,
    storage: Any,
    backend: private_storage.ObjectBackend | None = None,
    require_objects: bool = True,
    max_rows_per_table: int = MAX_ROWS_PER_TABLE,
    max_objects: int = MAX_OBJECTS,
    now: datetime | None = None,
) -> dict[str, Any]:
    commit = str(release_commit or "").strip().lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise ValueError("release commit must be a full lowercase Git SHA")
    row_limit = _bounded_int(
        max_rows_per_table,
        "max_rows_per_table",
        1,
        MAX_ROWS_PER_TABLE,
    )
    names = _table_names(storage)
    table_set = set(names)
    table_inventory: dict[str, Any] = {}
    schema_records: list[dict[str, Any]] = []
    for table in names:
        columns = _table_columns(storage, table)
        count, digest = _row_digest(
            storage,
            table,
            columns,
            max_rows=row_limit,
        )
        schema_records.append({"table": table, "columns": columns})
        table_inventory[table] = {
            "row_count": count,
            "rowset_sha256": digest,
        }
    selected_backend = backend
    if selected_backend is None and private_storage.object_backend_configured():
        selected_backend = private_storage.get_object_backend()
    if require_objects and selected_backend is None:
        raise RecoveryEvidenceError("private object inventory is required")
    objects = (
        object_inventory(selected_backend, max_objects=max_objects)
        if selected_backend is not None
        else {
            "object_count": 0,
            "size_bytes": 0,
            "aggregate_sha256": _sha(b""),
            "content_included": False,
            "object_keys_included": False,
            "not_captured": True,
        }
    )
    manifest = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": _utc(now).isoformat(),
        "release_commit": commit,
        "database": {
            "engine": "postgresql"
            if bool(getattr(storage, "postgres", db.using_postgres()))
            else "sqlite",
            "schema_sha256": _sha(_canonical_json(schema_records)),
            "table_count": len(names),
            "tables": table_inventory,
            "migrations": _migration_inventory(storage, table_set),
            "references": _reference_inventory(storage, table_set),
        },
        "objects": objects,
        "privacy": {
            "row_values_included": False,
            "object_content_included": False,
            "object_keys_included": False,
            "user_identifiers_included": False,
        },
    }
    manifest["manifest_sha256"] = _sha(_canonical_json(manifest))
    return manifest


def capture_manifest(
    *,
    release_commit: str,
    storage: Any = db,
    backend: private_storage.ObjectBackend | None = None,
    require_objects: bool = True,
    max_rows_per_table: int = MAX_ROWS_PER_TABLE,
    max_objects: int = MAX_OBJECTS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Capture one database snapshot plus its corresponding object inventory."""
    if storage is db:
        with db.transaction(write=False) as snapshot:
            if snapshot.postgres:
                snapshot.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            return _capture_manifest(
                release_commit=release_commit,
                storage=snapshot,
                backend=backend,
                require_objects=require_objects,
                max_rows_per_table=max_rows_per_table,
                max_objects=max_objects,
                now=now,
            )
    return _capture_manifest(
        release_commit=release_commit,
        storage=storage,
        backend=backend,
        require_objects=require_objects,
        max_rows_per_table=max_rows_per_table,
        max_objects=max_objects,
        now=now,
    )


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise RecoveryEvidenceError(f"invalid {label}")
    return value


def _manifest_clock(value: Any, label: str) -> datetime:
    normalized = str(value or "")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryEvidenceError(f"invalid {label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecoveryEvidenceError(f"invalid {label}")
    utc = parsed.astimezone(timezone.utc)
    if normalized not in {
        utc.isoformat(),
        utc.isoformat().replace("+00:00", "Z"),
    }:
        raise RecoveryEvidenceError(f"noncanonical {label}")
    return utc


def validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise RecoveryEvidenceError("invalid recovery manifest")
    value = dict(manifest)
    supplied = str(value.pop("manifest_sha256", "") or "")
    if not _DIGEST_RE.fullmatch(supplied):
        raise RecoveryEvidenceError("invalid recovery manifest digest")
    if _sha(_canonical_json(value)) != supplied:
        raise RecoveryEvidenceError("recovery manifest integrity mismatch")
    if value.get("contract_version") != CONTRACT_VERSION:
        raise RecoveryEvidenceError("unsupported recovery manifest")
    _exact_keys(
        value,
        {
            "contract_version",
            "generated_at",
            "release_commit",
            "database",
            "objects",
            "privacy",
        },
        "recovery manifest shape",
    )
    _manifest_clock(value.get("generated_at"), "manifest clock")
    if not _COMMIT_RE.fullmatch(str(value.get("release_commit") or "")):
        raise RecoveryEvidenceError("invalid release commit")

    privacy = _exact_keys(
        value.get("privacy"),
        {
            "row_values_included",
            "object_content_included",
            "object_keys_included",
            "user_identifiers_included",
        },
        "recovery manifest privacy contract",
    )
    if any(item is not False for item in privacy.values()):
        raise RecoveryEvidenceError("recovery manifest privacy contract violated")

    database = _exact_keys(
        value.get("database"),
        {
            "engine",
            "schema_sha256",
            "table_count",
            "tables",
            "migrations",
            "references",
        },
        "database evidence",
    )
    if database["engine"] not in {"sqlite", "postgresql"}:
        raise RecoveryEvidenceError("invalid database engine")
    if not _DIGEST_RE.fullmatch(str(database["schema_sha256"] or "")):
        raise RecoveryEvidenceError("invalid database schema digest")
    tables = database["tables"]
    if not isinstance(tables, dict):
        raise RecoveryEvidenceError("invalid database table evidence")
    table_count = _bounded_int(
        database["table_count"],
        "table_count",
        0,
        MAX_TABLES,
    )
    if table_count != len(tables):
        raise RecoveryEvidenceError("database table count mismatch")
    for table, inventory in tables.items():
        _quote_identifier(str(table))
        inventory = _exact_keys(
            inventory,
            {"row_count", "rowset_sha256"},
            "database table inventory",
        )
        _bounded_int(
            inventory["row_count"],
            "row_count",
            0,
            MAX_ROWS_PER_TABLE,
        )
        if not _DIGEST_RE.fullmatch(str(inventory["rowset_sha256"] or "")):
            raise RecoveryEvidenceError("invalid database row-set digest")

    migrations = database["migrations"]
    if not isinstance(migrations, list) or len(migrations) > MAX_TABLES:
        raise RecoveryEvidenceError("invalid migration evidence")
    migration_versions: set[str] = set()
    for migration in migrations:
        if not isinstance(migration, dict) or set(migration) not in (
            {"version"},
            {"version", "sha256"},
        ):
            raise RecoveryEvidenceError("invalid migration evidence")
        version = str(migration.get("version") or "")
        if (
            not re.fullmatch(r"[0-9]{4}_[a-z0-9_]+[.]sql", version)
            or version in migration_versions
        ):
            raise RecoveryEvidenceError("invalid migration version")
        migration_versions.add(version)
        if "sha256" in migration and not _DIGEST_RE.fullmatch(
            str(migration["sha256"] or "")
        ):
            raise RecoveryEvidenceError("invalid migration digest")

    references = _exact_keys(
        database["references"],
        {"ai_payload_refs", "private_media_refs"},
        "reference evidence",
    )
    for inventory in references.values():
        inventory = _exact_keys(
            inventory,
            {"present", "total_count", "states"},
            "reference inventory",
        )
        if not isinstance(inventory["present"], bool):
            raise RecoveryEvidenceError("invalid reference presence")
        states = inventory["states"]
        if not isinstance(states, dict) or set(states) - {
            "ready",
            "expired",
            "deleted",
        }:
            raise RecoveryEvidenceError("invalid reference states")
        total = _bounded_int(
            inventory["total_count"],
            "reference total_count",
            0,
            MAX_ROWS_PER_TABLE,
        )
        counted = 0
        for state_inventory in states.values():
            state_inventory = _exact_keys(
                state_inventory,
                {"count", "oldest_created_at", "newest_created_at"},
                "reference state inventory",
            )
            count = _bounded_int(
                state_inventory["count"],
                "reference state count",
                1,
                MAX_ROWS_PER_TABLE,
            )
            counted += count
            oldest = _manifest_clock(
                state_inventory["oldest_created_at"],
                "reference oldest clock",
            )
            newest = _manifest_clock(
                state_inventory["newest_created_at"],
                "reference newest clock",
            )
            if oldest > newest:
                raise RecoveryEvidenceError("invalid reference clock order")
        if counted != total or (not inventory["present"] and total != 0):
            raise RecoveryEvidenceError("reference count mismatch")

    objects = value.get("objects")
    expected_object_keys = {
        "object_count",
        "size_bytes",
        "aggregate_sha256",
        "content_included",
        "object_keys_included",
    }
    if isinstance(objects, dict) and objects.get("not_captured") is True:
        expected_object_keys.add("not_captured")
    objects = _exact_keys(objects, expected_object_keys, "object evidence")
    object_count = _bounded_int(
        objects["object_count"],
        "object_count",
        0,
        MAX_OBJECTS,
    )
    _bounded_int(
        objects["size_bytes"],
        "object size_bytes",
        0,
        MAX_OBJECTS * durable_ai.MAX_OBJECT_BYTES,
    )
    if not _DIGEST_RE.fullmatch(str(objects["aggregate_sha256"] or "")):
        raise RecoveryEvidenceError("invalid object inventory digest")
    if (
        objects["content_included"] is not False
        or objects["object_keys_included"] is not False
    ):
        raise RecoveryEvidenceError("object evidence privacy contract violated")
    if (
        (object_count == 0) != (objects["size_bytes"] == 0)
        or (
            objects.get("not_captured") is True
            and (
                object_count != 0
                or objects["aggregate_sha256"] != _sha(b"")
            )
        )
    ):
        raise RecoveryEvidenceError("uncaptured object inventory is not empty")
    return manifest


def verify_restore(
    source_manifest: Any,
    restored_manifest: Any,
) -> dict[str, Any]:
    source = validate_manifest(source_manifest)
    restored = validate_manifest(restored_manifest)
    mismatches: list[str] = []
    comparisons = (
        ("release_commit", source.get("release_commit"), restored.get("release_commit")),
        (
            "database_engine",
            source.get("database", {}).get("engine"),
            restored.get("database", {}).get("engine"),
        ),
        (
            "database_schema",
            source.get("database", {}).get("schema_sha256"),
            restored.get("database", {}).get("schema_sha256"),
        ),
        (
            "database_migrations",
            source.get("database", {}).get("migrations"),
            restored.get("database", {}).get("migrations"),
        ),
        (
            "database_tables",
            source.get("database", {}).get("tables"),
            restored.get("database", {}).get("tables"),
        ),
        (
            "database_references",
            source.get("database", {}).get("references"),
            restored.get("database", {}).get("references"),
        ),
        ("private_objects", source.get("objects"), restored.get("objects")),
    )
    for code, expected, actual in comparisons:
        if expected != actual:
            mismatches.append(code)
    return {
        "verified": not mismatches,
        "mismatch_codes": mismatches,
        "source_manifest_sha256": source["manifest_sha256"],
        "restored_manifest_sha256": restored["manifest_sha256"],
        "content_included": False,
    }
