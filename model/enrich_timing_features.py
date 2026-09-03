#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NoteAI Pro — Enrich Timing Features
Reads cover_metadata_v2.jsonl, calls compute_market_timing for each note,
and saves the 8 timing features to data/timing_features.parquet.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Ensure the model directory is importable regardless of cwd
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from hot_keywords import compute_market_timing  # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────────

# Default: full training set (91k notes with titles + desc)
METADATA_PATH     = BASE_DIR / "data" / "RedNote-Vibe-Dataset" / "exploring_set.jsonl"
COVER_METADATA    = BASE_DIR / "data" / "cover_metadata_v2.jsonl"   # 10k cover notes
HUMAN_METADATA    = BASE_DIR / "data" / "RedNote-Vibe-Dataset" / "training_set_human.jsonl"
OUTPUT_PATH       = BASE_DIR / "data" / "timing_features.parquet"

TIMING_FEATURE_COLS = [
    "keyword_search_vol",
    "trend_momentum",
    "is_trending_topic",
    "content_freshness",
    "category_saturation",
    "category_avg_ces",
    "keyword_competition",
    "trend_peak_distance",
]

# category_avg_ces and trend_peak_distance are not yet in compute_market_timing;
# use these defaults when the key is absent from the returned dict.
TIMING_DEFAULTS = {
    "category_avg_ces":    50.0,
    "trend_peak_distance": 0.0,
}

# Channel → Chinese domain label
# cover_metadata_v2.jsonl already uses Chinese domain names in the "channel" field.
# Normalize minor variants to match features.parquet domain values.
_DOMAIN_NORM = {
    "运动健康": "运动",
    "家居家装": "家居",
    "亲子": "情感",
}
DOMAIN_FALLBACK = "综合"


def channel_to_domain(channel: str) -> str:
    return _DOMAIN_NORM.get(channel, channel) if channel else DOMAIN_FALLBACK


def extract_timing_row(result: dict) -> dict:
    """Pull the 8 timing feature values out of a compute_market_timing result."""
    row = {}
    for col in TIMING_FEATURE_COLS:
        default = TIMING_DEFAULTS.get(col, 0.0)
        row[col] = float(result.get(col, default))
    return row


def _read_note(note: dict) -> tuple[str, str, str, str]:
    """Return (note_id, title, desc, domain) handling both data formats."""
    note_id = note.get("note_id", "")
    title   = note.get("note_title", "") or ""
    desc    = note.get("desc", "") or ""
    # exploring_set.jsonl uses "domain" directly; cover_metadata uses "channel"
    domain  = note.get("domain", "") or channel_to_domain(note.get("channel", ""))
    return note_id, title, desc, domain


def main():
    parser = argparse.ArgumentParser(
        description="Build timing_features.parquet — defaults to exploring_set.jsonl (91k)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Process only the first 500 notes for testing")
    parser.add_argument("--source", choices=["full", "cover", "human"], default="full",
                        help="'full'=exploring_set.jsonl (91k), 'cover'=cover_metadata_v2.jsonl (10k), 'human'=training_set_human.jsonl (51k)")
    parser.add_argument("--output", type=str, default=None,
                        help="Override output parquet path")
    args = parser.parse_args()

    src_map = {"full": METADATA_PATH, "cover": COVER_METADATA, "human": HUMAN_METADATA}
    src = src_map[args.source]
    out = Path(args.output) if args.output else (
        BASE_DIR / "data" / "timing_features_human.parquet" if args.source == "human"
        else OUTPUT_PATH
    )
    print(f"Reading {src} ...")
    notes = []
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if args.dry_run:
        notes = notes[:500]
        print(f"[dry-run] Truncated to {len(notes)} notes.")

    total = len(notes)
    print(f"Total notes to process: {total:,}")

    # ── Compute timing features ───────────────────────────────────────────────
    records = []
    zero_row = {col: 0.0 for col in TIMING_FEATURE_COLS}
    zero_row.update(TIMING_DEFAULTS)

    for i, note in enumerate(notes):
        note_id, note_title, desc, domain = _read_note(note)

        try:
            result   = compute_market_timing(note_title, desc, domain)
            feat_row = extract_timing_row(result)
        except Exception as exc:
            # Graceful degradation: log once per error type, fill zeros
            print(
                f"  [WARN] timing failed code={type(exc).__name__.lower()}; "
                "using zeros."
            )
            feat_row = dict(zero_row)

        feat_row["note_id"] = note_id
        records.append(feat_row)

        if (i + 1) % 1000 == 0:
            print(f"  Progress: {i + 1:,} / {total:,}")

    # ── Build DataFrame and save ──────────────────────────────────────────────
    df = pd.DataFrame(records, columns=["note_id"] + TIMING_FEATURE_COLS)

    print(f"\nSaving to {out} ...")
    out.parent.mkdir(exist_ok=True)
    df.to_parquet(out, index=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 55}")
    print(f"timing_features.parquet written")
    print(f"  Rows    : {len(df):,}")
    print(f"  Columns : {list(df.columns)}")
    print(f"\nFeature statistics:")
    print(df[TIMING_FEATURE_COLS].describe().round(4).to_string())
    nonzero_kw = (df["keyword_search_vol"] > 0).sum()
    print(f"\n  Notes with keyword_search_vol > 0 : {nonzero_kw:,} ({nonzero_kw/len(df)*100:.1f}%)")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
