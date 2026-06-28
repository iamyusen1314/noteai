#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download/version RedNote-Vibe raw dataset snapshots.

The GitHub repository keeps metadata and README files; the actual JSONL files
are distributed through Google Drive. This script stores each sync into a dated
directory and writes a manifest with repo commit metadata and file hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


REPO_API = "https://api.github.com/repos/ydli-ai/RedNote-Vibe/commits?per_page=1"
GOOGLE_DRIVE_URL = "https://drive.google.com/drive/folders/1T8JV-DmIo7SI8pBOPeuiQvXzFwe8ns--?usp=sharing"
EXPECTED_FILES = ["training_set_human.jsonl", "training_set_aigc.jsonl", "exploring_set.jsonl"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def latest_commit() -> dict:
    with urlopen(REPO_API, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    item = data[0]
    return {
        "sha": item["sha"],
        "html_url": item["html_url"],
        "message": item["commit"]["message"],
        "date": item["commit"]["author"]["date"],
        "author": item["commit"]["author"]["name"],
    }


def find_expected_files(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in root.rglob("*.jsonl"):
        if path.name in EXPECTED_FILES:
            found[path.name] = path
    return found


def download_folder(target: Path) -> None:
    try:
        import gdown
    except Exception as exc:
        raise RuntimeError("gdown is required. Install it with `.venv/bin/python -m pip install gdown`.") from exc
    gdown.download_folder(GOOGLE_DRIVE_URL, output=str(target), quiet=False, use_cookies=False)


def build_manifest(snapshot_dir: Path, commit: dict) -> dict:
    found = find_expected_files(snapshot_dir)
    files = {}
    for filename, path in sorted(found.items()):
        files[filename] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        }
    missing = [name for name in EXPECTED_FILES if name not in found]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo": "ydli-ai/RedNote-Vibe",
        "repo_latest_commit": commit,
        "google_drive_url": GOOGLE_DRIVE_URL,
        "snapshot_dir": str(snapshot_dir),
        "files": files,
        "missing_files": missing,
    }


def copy_latest(snapshot_dir: Path, latest_dir: Path) -> None:
    found = find_expected_files(snapshot_dir)
    latest_dir.mkdir(parents=True, exist_ok=True)
    for filename in EXPECTED_FILES:
        if filename in found:
            shutil.copy2(found[filename], latest_dir / filename)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync RedNote-Vibe Google Drive dataset")
    parser.add_argument("--snapshots-dir", default="model/data/rednote_vibe_raw")
    parser.add_argument("--latest-dir", default="model/data/RedNote-Vibe-Dataset")
    parser.add_argument("--no-copy-latest", action="store_true")
    parser.add_argument("--manifest-only", action="store_true", help="Do not download; write manifest for existing snapshot dir")
    parser.add_argument("--snapshot-dir", default="", help="Existing snapshot dir for --manifest-only")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    commit = latest_commit()
    if args.manifest_only:
        if not args.snapshot_dir:
            raise SystemExit("--snapshot-dir is required with --manifest-only")
        snapshot_dir = Path(args.snapshot_dir)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_dir = Path(args.snapshots_dir) / f"{stamp}_{commit['sha'][:12]}"
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        download_folder(snapshot_dir)

    manifest = build_manifest(snapshot_dir, commit)
    manifest_path = snapshot_dir / "sync_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if manifest["missing_files"]:
        raise SystemExit(f"Missing expected files after sync: {manifest['missing_files']}")

    if not args.no_copy_latest:
        copy_latest(snapshot_dir, Path(args.latest_dir))

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
