#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe naturalness/AI-smell scores for generated notes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from naturalness import score_naturalness  # noqa: E402
from text_naturalness_features import extract_naturalness_features  # noqa: E402


KEY_FEATURES = [
    "paragraph_count",
    "body_len",
    "title_body_ratio",
    "avg_line_len",
    "plad_ttr",
    "plad_phrasal_repetition",
    "sentence_len_cv_naturalness",
    "personal_reader_ratio",
    "sensory_density",
    "generic_praise_count",
    "low_info_phrase_count",
    "ai_transition_count",
    "hashtag_density",
]


def _case_candidates(data: object) -> list[dict]:
    cases: list[dict] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                cases.extend(_case_candidates(item))
        return cases
    if not isinstance(data, dict):
        return cases

    for title_key, body_key in [
        ("title", "body"),
        ("note_title", "note_body"),
        ("output_title", "output_body"),
        ("new_title", "new_body"),
    ]:
        title = data.get(title_key)
        body = data.get(body_key)
        if title and body:
            cases.append(
                {
                    "id": data.get("id") or data.get("name") or title[:20],
                    "title": title,
                    "body": body,
                    "domain": data.get("domain") or "美食",
                }
            )

    if isinstance(data.get("note_update"), dict):
        cases.extend(_case_candidates(data["note_update"]))
    for plan in data.get("suggested_plans") or []:
        if isinstance(plan, dict):
            cases.extend(_case_candidates(plan))
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe generated-note naturalness")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.json_file.read_text(encoding="utf-8"))
    cases = _case_candidates(data)
    if not cases:
        raise SystemExit("No title/body candidates found")

    results = []
    for case in cases:
        title = case["title"]
        body = case["body"]
        domain = case.get("domain") or "美食"
        score = score_naturalness(title, body, domain)
        feats = extract_naturalness_features(title, body, domain)
        results.append(
            {
                **case,
                "naturalness_score": round(score["naturalness_score"], 1),
                "ai_probability": round(score["ai_probability"], 4),
                "features": {key: round(float(feats.get(key, 0.0) or 0.0), 4) for key in KEY_FEATURES},
            }
        )

    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(
                f"{item['id']} domain={item['domain']} "
                f"naturalness={item['naturalness_score']} ai_p={item['ai_probability']} "
                f"title={item['title'][:36]}"
            )
            f = item["features"]
            print(
                "  "
                f"para={f['paragraph_count']} len={f['body_len']} "
                f"line={f['avg_line_len']} sensory={f['sensory_density']} "
                f"generic={f['generic_praise_count']} ttr={f['plad_ttr']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
