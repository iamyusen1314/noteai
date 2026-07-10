#!/usr/bin/env python3
"""Safely copy NoteAI application records from SQLite to PostgreSQL.

Dry-run is the default. The source database is never modified. Applying an
import requires both --apply and an exact --expected-database guard.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "model" / "data" / "noteai.db"

TABLE_ORDER = (
    "users",
    "notes",
    "chat_sessions",
    "user_memories",
    "growth_records",
    "subscriptions",
    "usage_records",
    "credits",
    "credit_transactions",
    "saved_diagnoses",
    "tracked_notes",
)


def _source_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def source_counts(source: Path, include_user_sessions: bool = False) -> dict[str, int]:
    if not source.exists():
        raise FileNotFoundError(f"SQLite source not found: {source}")
    conn = sqlite3.connect(str(source))
    try:
        tables = _source_tables(conn)
        selected = list(TABLE_ORDER)
        if include_user_sessions:
            selected.insert(1, "user_sessions")
        return {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in selected
            if table in tables
        }
    finally:
        conn.close()


def _target_columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _source_rows(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    order = " ORDER BY version ASC, created_at ASC" if table == "notes" else ""
    cursor = conn.execute(f'SELECT * FROM "{table}"{order}')
    columns = [str(item[0]) for item in cursor.description or ()]
    return columns, [tuple(row) for row in cursor.fetchall()]


def _insert_rows(pg_conn, table: str, columns: list[str], rows: list[tuple]) -> int:
    if not rows or not columns:
        return 0
    quoted = ",".join(f'"{column}"' for column in columns)
    placeholders = ",".join(["%s"] * len(columns))
    sql = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
    cursor = pg_conn.cursor()
    inserted = 0
    for row in rows:
        cursor.execute(sql, row)
        inserted += max(0, int(cursor.rowcount or 0))
    return inserted


def apply_import(
    source: Path,
    database_url: str,
    expected_database: str,
    include_user_sessions: bool = False,
) -> dict[str, dict[str, int]]:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL import requires psycopg[binary]") from exc

    sqlite_conn = sqlite3.connect(str(source))
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg.connect(database_url)
    report: dict[str, dict[str, int]] = {}
    try:
        current_database = str(pg_conn.execute("SELECT current_database()").fetchone()[0])
        if current_database != expected_database:
            raise RuntimeError(
                f"Destination guard failed: expected {expected_database}, got {current_database}"
            )
        source_tables = _source_tables(sqlite_conn)
        tables = list(TABLE_ORDER)
        if include_user_sessions:
            tables.insert(1, "user_sessions")

        with pg_conn:
            for table in tables:
                if table not in source_tables:
                    continue
                source_columns, rows = _source_rows(sqlite_conn, table)
                target_columns = _target_columns(pg_conn, table)
                selected_indexes = [
                    index for index, column in enumerate(source_columns) if column in target_columns
                ]
                selected_columns = [source_columns[index] for index in selected_indexes]
                selected_rows = [tuple(row[index] for index in selected_indexes) for row in rows]

                parent_links: list[tuple[str, str]] = []
                if table == "notes" and "parent_id" in selected_columns and "id" in selected_columns:
                    parent_index = selected_columns.index("parent_id")
                    id_index = selected_columns.index("id")
                    normalized = []
                    for row in selected_rows:
                        mutable = list(row)
                        if mutable[parent_index]:
                            parent_links.append((str(mutable[parent_index]), str(mutable[id_index])))
                            mutable[parent_index] = None
                        normalized.append(tuple(mutable))
                    selected_rows = normalized

                inserted = _insert_rows(pg_conn, table, selected_columns, selected_rows)
                for parent_id, note_id in parent_links:
                    pg_conn.execute(
                        "UPDATE notes SET parent_id=%s WHERE id=%s AND parent_id IS NULL",
                        (parent_id, note_id),
                    )
                report[table] = {"source": len(rows), "inserted": inserted}
    finally:
        sqlite_conn.close()
        pg_conn.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate NoteAI SQLite application data to PostgreSQL")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL; omitted means dry-run")
    parser.add_argument("--expected-database", default="")
    parser.add_argument("--include-user-sessions", action="store_true")
    args = parser.parse_args()

    counts = source_counts(args.source, args.include_user_sessions)
    print("mode=apply" if args.apply else "mode=dry-run")
    for table, count in counts.items():
        print(f"source_table={table} rows={count}")
    if not args.apply:
        print("No destination writes performed. Use --apply with --expected-database after backup approval.")
        return 0

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is required for --apply", file=sys.stderr)
        return 2
    if not args.expected_database:
        print("--expected-database is required for --apply", file=sys.stderr)
        return 2
    report = apply_import(
        args.source,
        database_url,
        args.expected_database,
        args.include_user_sessions,
    )
    for table, result in report.items():
        print(f"import_table={table} source={result['source']} inserted={result['inserted']}")
    print("Import committed. Existing destination rows were not overwritten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
