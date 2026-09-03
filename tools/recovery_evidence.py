#!/usr/bin/env python3
"""Capture or compare content-free restore evidence; never performs a restore."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "model"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))

import storage_recovery_evidence as recovery_evidence
import private_storage


def _release_commit(value: str | None) -> str:
    if value:
        return value
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def _read(path: str) -> dict:
    source = Path(path)
    if source.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("recovery manifest exceeds the safe read limit")
    return json.loads(source.read_text(encoding="utf-8"))


def _write_once(path: str, body: bytes) -> None:
    if len(body) > MAX_MANIFEST_BYTES:
        raise ValueError("recovery manifest exceeds the safe write limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _configure_object_inventory(*, database_only: bool) -> None:
    if database_only:
        return
    if not private_storage.configure_from_environment():
        raise RuntimeError("private OSS configuration is required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture = subcommands.add_parser("capture")
    capture.add_argument("--release-commit")
    capture.add_argument("--output", required=True)
    capture.add_argument("--database-only", action="store_true")
    capture.add_argument("--max-rows-per-table", type=int, default=1000000)
    capture.add_argument("--max-objects", type=int, default=100000)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--source", required=True)
    verify.add_argument("--restored", required=True)
    args = parser.parse_args(argv)

    if args.command == "capture":
        _configure_object_inventory(database_only=args.database_only)
        manifest = recovery_evidence.capture_manifest(
            release_commit=_release_commit(args.release_commit),
            require_objects=not args.database_only,
            max_rows_per_table=args.max_rows_per_table,
            max_objects=args.max_objects,
        )
        _write_once(
            args.output,
            (
                json.dumps(
                    manifest,
                    ensure_ascii=True,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8"),
        )
        print(
            json.dumps(
                {
                    "captured": True,
                    "manifest_sha256": manifest["manifest_sha256"],
                    "content_included": False,
                },
                sort_keys=True,
            )
        )
        return 0

    result = recovery_evidence.verify_restore(
        _read(args.source),
        _read(args.restored),
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
