#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NoteAI Pro — Semantic Feature Enrichment via Kimi (moonshot-v1-8k)
Computes 3 semantic PLAD features for each unique note in exploring_set.jsonl:
  - semantic_emotional_intensity   : 情感强度 (0-1)
  - semantic_empathetic_engagement : 共情度   (0-1)
  - semantic_rhetorical_score      : 修辞水平 (0-1)

Usage:
  python enrich_semantic_features.py [--dry-run] [--batch-size 20] [--workers 5]
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
JSONL_PATH = BASE_DIR / "data" / "RedNote-Vibe-Dataset" / "exploring_set.jsonl"
OUTPUT_PATH = BASE_DIR / "data" / "semantic_features.parquet"
CHECKPOINT_PATH = BASE_DIR / "data" / "semantic_features_checkpoint.jsonl"

SEMANTIC_FEATURE_COLS = [
    "semantic_emotional_intensity",
    "semantic_empathetic_engagement",
    "semantic_rhetorical_score",
]

KIMI_URL = "https://api.moonshot.cn/v1/chat/completions"
KIMI_MODEL = "moonshot-v1-8k"

_SYSTEM_PROMPT = """你是一位专业的内容分析师，擅长分析中文社交媒体笔记的情感与修辞特征。
请严格按照要求返回JSON格式，不要输出任何其他内容。"""

_BATCH_PROMPT_TEMPLATE = """请对以下{n}篇小红书笔记分别评估3个维度，每个维度评分范围0.0到1.0：

评分标准：
- semantic_emotional_intensity（情感强度）：
  0.0=纯信息罗列无情绪, 0.3=轻微情绪色彩, 0.5=明显情绪表达, 0.8=强烈情绪感染, 1.0=极致情绪爆发
- semantic_empathetic_engagement（共情度）：
  0.0=无共情设计, 0.3=有轻微代入感, 0.5=能引发读者共鸣, 0.8=强烈情感连接, 1.0=精准击中读者痛点
- semantic_rhetorical_score（修辞水平）：
  0.0=直白口语无修辞, 0.3=偶有比喻或排比, 0.5=修辞手法较丰富, 0.8=语言精炼生动, 1.0=修辞极为精妙

笔记列表：
{notes_block}

只返回JSON数组，格式如下，不要包含任何解释：
[{{"note_id":"...","semantic_emotional_intensity":0.0,"semantic_empathetic_engagement":0.0,"semantic_rhetorical_score":0.0}},...]"""


def _call_kimi(api_key: str, batch: list[dict], retries: int = 3) -> list[dict]:
    """Call Kimi API for a batch of notes. Returns list of scored dicts."""
    notes_block = ""
    for i, note in enumerate(batch, 1):
        title = (note.get("note_title") or "").strip()
        desc = (note.get("desc") or "").strip()[:300]
        notes_block += f"[笔记{i}] note_id={note['note_id']}\n标题：{title}\n正文：{desc}\n\n"

    prompt = _BATCH_PROMPT_TEMPLATE.format(n=len(batch), notes_block=notes_block)

    payload = json.dumps({
        "model": KIMI_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1600,
        "temperature": 0.1,
    }).encode()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                KIMI_URL,
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
                raw = resp["choices"][0]["message"]["content"].strip()
                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                results = json.loads(raw.strip())
                if isinstance(results, list):
                    return results
                return []
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt * 3
                print(f"  [rate limit] sleeping {wait}s ...", flush=True)
                time.sleep(wait)
            else:
                print(f"  [HTTP {e.code}] attempt {attempt+1}/{retries}", flush=True)
                time.sleep(1)
        except Exception as exc:
            print(f"  [error] {type(exc).__name__}: {exc} — attempt {attempt+1}/{retries}", flush=True)
            time.sleep(1)

    return []


def _default_row(note_id: str) -> dict:
    return {
        "note_id": note_id,
        "semantic_emotional_intensity": 0.5,
        "semantic_empathetic_engagement": 0.5,
        "semantic_rhetorical_score": 0.5,
    }


def _load_checkpoint() -> set[str]:
    """Return set of already-processed note_ids from checkpoint file."""
    done: set[str] = set()
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["note_id"])
                except Exception:
                    pass
    return done


def _append_checkpoint(rows: list[dict]):
    with open(CHECKPOINT_PATH, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Enrich notes with semantic features via Kimi")
    parser.add_argument("--dry-run", action="store_true", help="Process only first 40 notes")
    parser.add_argument("--batch-size", type=int, default=20, help="Notes per API call (default 20)")
    parser.add_argument("--workers", type=int, default=5, help="Parallel API workers (default 5)")
    args = parser.parse_args()

    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        print("ERROR: MOONSHOT_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Load unique notes
    print(f"Loading {JSONL_PATH} ...")
    seen_ids: set[str] = set()
    notes: list[dict] = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                nid = row.get("note_id", "")
                if nid and nid not in seen_ids:
                    seen_ids.add(nid)
                    notes.append({"note_id": nid,
                                  "note_title": row.get("note_title", ""),
                                  "desc": row.get("desc", "")})
            except Exception:
                pass

    print(f"Unique notes: {len(notes):,}")

    if args.dry_run:
        notes = notes[:40]
        print(f"[dry-run] Truncated to {len(notes)} notes.")

    # Resume from checkpoint
    done_ids = _load_checkpoint()
    notes = [n for n in notes if n["note_id"] not in done_ids]
    print(f"Already done: {len(done_ids):,} | Remaining: {len(notes):,}")

    if not notes:
        print("All notes already processed. Building final parquet ...")
    else:
        # Split into batches
        bs = args.batch_size
        batches = [notes[i:i+bs] for i in range(0, len(notes), bs)]
        total_batches = len(batches)
        print(f"Batches: {total_batches:,} (size={bs}) | Workers: {args.workers}")

        completed = 0

        def process_batch(batch: list[dict]) -> list[dict]:
            results = _call_kimi(api_key, batch)
            # Index returned results by note_id
            result_map = {r.get("note_id", ""): r for r in results if isinstance(r, dict)}
            rows = []
            for note in batch:
                nid = note["note_id"]
                r = result_map.get(nid)
                if r:
                    row = {
                        "note_id": nid,
                        "semantic_emotional_intensity": float(r.get("semantic_emotional_intensity", 0.5)),
                        "semantic_empathetic_engagement": float(r.get("semantic_empathetic_engagement", 0.5)),
                        "semantic_rhetorical_score": float(r.get("semantic_rhetorical_score", 0.5)),
                    }
                else:
                    row = _default_row(nid)
                rows.append(row)
            return rows

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process_batch, b): b for b in batches}
            for future in as_completed(futures):
                rows = future.result()
                _append_checkpoint(rows)
                completed += 1
                if completed % 50 == 0 or completed == total_batches:
                    pct = completed / total_batches * 100
                    print(f"  Progress: {completed:,}/{total_batches:,} batches ({pct:.1f}%)", flush=True)

    # Build final parquet from checkpoint
    all_rows = []
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    all_rows.append(json.loads(line))
                except Exception:
                    pass

    df = pd.DataFrame(all_rows, columns=["note_id"] + SEMANTIC_FEATURE_COLS)
    df = df.drop_duplicates(subset="note_id", keep="last")

    print(f"\nSaving {len(df):,} rows → {OUTPUT_PATH}")
    df.to_parquet(OUTPUT_PATH, index=False)

    print(f"\n{'='*55}")
    print(f"semantic_features.parquet written")
    print(f"  Rows: {len(df):,}")
    print(f"\nFeature statistics:")
    print(df[SEMANTIC_FEATURE_COLS].describe().round(3).to_string())
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
