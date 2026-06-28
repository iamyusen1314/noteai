#!/usr/bin/env python3
"""Offline/optional-semantic quality gate for generated NoteAI outputs.

Input JSON shape:
[
  {
    "id": "food_good",
    "domain": "美食",
    "title": "...",
    "body": "... #标签",
    "local_time": "2026062412",
    "min_score": 68,
    "expected_pass": true
  }
]

By default this uses neutral semantic features to avoid external API cost.
Pass --semantic to call the configured Claude semantic route.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import api  # noqa: E402


async def evaluate_case(case: dict, use_semantic: bool) -> dict:
    title = (case.get("title") or "").strip()
    body = (case.get("body") or "").strip()
    domain = case.get("domain") or "美食"
    local_time = case.get("local_time") or "2026062412"
    min_score = float(case.get("min_score", 68))

    if use_semantic:
        score, features, grade = await api._score_generated_note(
            title, body, domain, local_time, timing=None, cover_feats=None
        )
    else:
        note = api.NoteInput(
            note_title=title,
            desc=api._normalize_tags_for_scoring(body),
            local_time=local_time,
            domain=domain,
        )
        semantic_defaults = {col: 0.5 for col in api.SEMANTIC_FEATURE_COLS}
        score, features = api._predict(note, semantic_feats=semantic_defaults)
        grade = api._grade(score)

    issues = api._generated_quality_issues(title, body, domain, score, features)
    blocking = api._has_blocking_quality_issues(score, issues, domain)
    passed = (score >= min_score) and not blocking

    expected = case.get("expected_pass")
    expectation_ok = True if expected is None else (bool(expected) == passed)

    return {
        "id": case.get("id") or title[:20] or "untitled",
        "domain": domain,
        "score": round(float(score), 1),
        "grade": grade,
        "passed": passed,
        "expected_pass": expected,
        "expectation_ok": expectation_ok,
        "blocking": blocking,
        "issues": issues,
        "features": {
            "body_len": features.get("body_len"),
            "tag_count": features.get("tag_count"),
            "body_cta_count": features.get("body_cta_count"),
            "body_has_price": features.get("body_has_price"),
            "body_has_address": features.get("body_has_address"),
            "body_has_hours": features.get("body_has_hours"),
            "body_has_must_order": features.get("body_has_must_order"),
        },
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run NoteAI generated-content quality gate.")
    parser.add_argument("cases", type=Path, help="JSON file containing generated note cases")
    parser.add_argument("--semantic", action="store_true", help="Call Claude semantic feature route")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise SystemExit("cases file must contain a JSON array")

    results = [await evaluate_case(case, args.semantic) for case in cases]
    failed = [
        r for r in results
        if (not r["expectation_ok"]) or (r["expected_pass"] is None and not r["passed"])
    ]

    if args.json:
        print(json.dumps({"ok": not failed, "results": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if r["expected_pass"] is False and not r["passed"] and r["expectation_ok"]:
                mark = "EXPECTED_FAIL"
            elif r["passed"] and r["expectation_ok"]:
                mark = "PASS"
            else:
                mark = "FAIL"
            print(f"{mark} {r['id']} domain={r['domain']} score={r['score']} issues={len(r['issues'])}")
            for issue in r["issues"][:4]:
                print(f"  - {issue}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
