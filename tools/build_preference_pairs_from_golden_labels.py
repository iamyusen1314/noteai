#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distill A/B preference pairs from reviewed golden quality labels.

This is not a replacement for same-task generated A/B labels. It converts
high-confidence absolute quality differences into pairwise ranking examples and
keeps a distinct label_source so downstream audits can separate the two.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_composite_dataset import resolve_golden_content  # noqa: E402
from v04_domain_policy import canonical_product_domain  # noqa: E402


DEFAULT_GOLDEN = ROOT / "quality" / "golden_labels.v01.merged.json"
DEFAULT_OUTPUT_JSONL = ROOT / "quality" / "preference_queue.v01.golden_distilled.jsonl"
DEFAULT_OUTPUT_REPORT = ROOT / "quality" / "preference_queue.v01.golden_distilled.report.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(*parts: Any, length: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    sep = "|" if "|" in text else ","
    return [part.strip() for part in text.split(sep) if part.strip()]


def _bool_label(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是", "ready", "可交付"}


def _golden_rows(golden_doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in golden_doc.get("items", []):
        labels = item.get("labels") or {}
        if "human_quality_score" not in labels:
            continue
        try:
            content = resolve_golden_content(item)
            score = float(labels.get("human_quality_score"))
        except Exception:
            continue
        title = str(content.get("title") or "").strip()
        body = str(content.get("body") or "").strip()
        domain = canonical_product_domain(content.get("domain"))
        if not title or not body or not domain:
            continue
        rows.append(
            {
                "id": str(item.get("id") or content.get("content_id") or ""),
                "domain": domain,
                "title": title,
                "body": body,
                "score": score,
                "delivery_ready": _bool_label(labels.get("delivery_ready")),
                "naturalness": float(labels.get("naturalness_label", 50.0) or 50.0),
                "fact_status": str(labels.get("fact_status") or "unknown"),
                "ai_smell_level": int(float(labels.get("ai_smell_level", 3) or 3)),
                "failure_tags": _split_tags(labels.get("failure_tags")),
                "label_source": str(labels.get("label_source") or ""),
            }
        )
    return rows


def _pair_margin(score_gap: float) -> int:
    if score_gap >= 30:
        return 3
    if score_gap >= 20:
        return 2
    return 1


def _reason_tags(winner: dict[str, Any], loser: dict[str, Any]) -> list[str]:
    tags = ["golden_score_gap"]
    if winner.get("delivery_ready") and not loser.get("delivery_ready"):
        tags.append("delivery_ready")
    if float(winner.get("naturalness") or 0) - float(loser.get("naturalness") or 0) >= 10:
        tags.append("naturalness")
    if winner.get("fact_status") in {"verified", "safe"} and loser.get("fact_status") in {"overclaim", "unknown"}:
        tags.append("fact_safety")
    if int(winner.get("ai_smell_level") or 3) < int(loser.get("ai_smell_level") or 3):
        tags.append("less_ai_smell")
    tags.append("better_user_value")
    return list(dict.fromkeys(tags))


def _should_pair(high: dict[str, Any], low: dict[str, Any], *, min_score_gap: float, ready_gap_min: float) -> bool:
    gap = float(high["score"]) - float(low["score"])
    if gap >= min_score_gap:
        return True
    if high.get("delivery_ready") and not low.get("delivery_ready") and gap >= ready_gap_min:
        return True
    return False


def _row_for_pair(high: dict[str, Any], low: dict[str, Any], seq: int) -> dict[str, Any]:
    # Deterministic side flipping keeps A/B winner distribution balanced.
    flip = int(_stable_hash(high["id"], low["id"], length=2), 16) % 2 == 0
    a, b = (low, high) if flip else (high, low)
    winner = "B" if flip else "A"
    score_gap = abs(float(high["score"]) - float(low["score"]))
    pair_hash = _stable_hash(high["id"], low["id"], high["score"], low["score"], length=10)
    return {
        "pair_id": f"gdist_{canonical_product_domain(high['domain'])}_{seq:05d}_{pair_hash}",
        "version": "golden-pairwise-distillation-v0.1",
        "label_status": "completed",
        "priority": "normal",
        "task_id": f"golden_distilled_{canonical_product_domain(high['domain'])}",
        "domain": canonical_product_domain(high["domain"]),
        "task_context": (
            "Golden 绝对质量标签蒸馏的 A/B 偏好；同一行业内高分/低分真实笔记对比，"
            "用于训练质量排序，不等同于同任务生成 A/B。"
        ),
        "comparison_focus": "标题自然度|正文价值|行业适配|事实安全|AI味|是否值得交付",
        "variant_a_id": a["id"],
        "variant_a_origin": "golden_label",
        "variant_a_title": a["title"],
        "variant_a_body": a["body"],
        "variant_a_body_char_len": len(a["body"]),
        "variant_a_score": round(float(a["score"]), 3),
        "variant_a_source_file": "quality/golden_labels.v01.merged.json",
        "variant_b_id": b["id"],
        "variant_b_origin": "golden_label",
        "variant_b_title": b["title"],
        "variant_b_body": b["body"],
        "variant_b_body_char_len": len(b["body"]),
        "variant_b_score": round(float(b["score"]), 3),
        "variant_b_source_file": "quality/golden_labels.v01.merged.json",
        "winner": winner,
        "preference_margin": _pair_margin(score_gap),
        "delivery_ready_winner": "true" if high.get("delivery_ready") else "false",
        "reason_tags": "|".join(_reason_tags(high, low)),
        "loser_failure_tags": "|".join(low.get("failure_tags") or ["lower_golden_quality"]),
        "rationale": (
            f"Golden 标签蒸馏：高分样本 {high['score']:.1f} vs 低分样本 {low['score']:.1f}，"
            f"分差 {score_gap:.1f}，高分样本更适合交付。"
        ),
        "reviewer": "golden_pairwise_distiller_v0.1",
        "reviewed_at": _now_iso(),
        "label_source": "golden_pairwise_distillation",
        "pair_text_hash": pair_hash,
    }


def build_pairs(
    *,
    golden_path: Path,
    max_pairs_per_domain: int,
    min_score_gap: float,
    ready_gap_min: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _golden_rows(_load_json(golden_path))
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[row["domain"]].append(row)

    out: list[dict[str, Any]] = []
    domain_reports: dict[str, Any] = {}
    seq = 1
    for domain in sorted(by_domain):
        items = sorted(by_domain[domain], key=lambda item: (-float(item["score"]), item["id"]))
        candidates: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
        for i, high in enumerate(items):
            for low in items[i + 1 :]:
                if float(high["score"]) < float(low["score"]):
                    high, low = low, high
                if not _should_pair(high, low, min_score_gap=min_score_gap, ready_gap_min=ready_gap_min):
                    continue
                gap = float(high["score"]) - float(low["score"])
                candidates.append((gap, _stable_hash(high["id"], low["id"], length=16), high, low))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[:max_pairs_per_domain]
        for _gap, _hash, high, low in selected:
            out.append(_row_for_pair(high, low, seq))
            seq += 1
        scores = [float(item["score"]) for item in items]
        domain_reports[domain] = {
            "golden_rows": len(items),
            "score_min": min(scores) if scores else None,
            "score_max": max(scores) if scores else None,
            "candidate_pairs": len(candidates),
            "selected_pairs": len(selected),
        }

    report = {
        "version": "golden-pairwise-distillation-report-v0.1",
        "created_at": _now_iso(),
        "inputs": {"golden_labels": str(golden_path)},
        "policy": {
            "label_source": "golden_pairwise_distillation",
            "min_score_gap": min_score_gap,
            "ready_gap_min": ready_gap_min,
            "max_pairs_per_domain": max_pairs_per_domain,
            "note": "These rows come from reviewed golden labels and are supplemental pairwise ranking labels, not same-task generated A/B labels.",
        },
        "totals": {
            "golden_rows": len(rows),
            "pairs": len(out),
            "by_domain": dict(Counter(row["domain"] for row in out)),
            "winner_counts": dict(Counter(row["winner"] for row in out)),
        },
        "domains": domain_reports,
    }
    return out, report


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build preference rows from reviewed golden labels")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--report", type=Path, default=DEFAULT_OUTPUT_REPORT)
    parser.add_argument("--max-pairs-per-domain", type=int, default=1000)
    parser.add_argument("--min-score-gap", type=float, default=20.0)
    parser.add_argument("--ready-gap-min", type=float, default=12.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    golden = args.golden if args.golden.is_absolute() else ROOT / args.golden
    output = args.output_jsonl if args.output_jsonl.is_absolute() else ROOT / args.output_jsonl
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    rows, report = build_pairs(
        golden_path=golden,
        max_pairs_per_domain=args.max_pairs_per_domain,
        min_score_gap=args.min_score_gap,
        ready_gap_min=args.ready_gap_min,
    )
    _write_jsonl(output, rows)
    report["outputs"] = {"jsonl": str(output), "report": str(report_path)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"pairs={report['totals']['pairs']} by_domain={report['totals']['by_domain']}")
        print(f"jsonl={output}")
        print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
