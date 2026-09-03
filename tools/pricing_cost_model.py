#!/usr/bin/env python3
"""NoteAI pricing cost model.

The numbers are engineering budgets, not live metering. Production billing
should use usage_records.tokens_in/tokens_out and actual_model_cost_rmb.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass


USD_CNY = float(os.environ.get("NOTEAI_PRICING_USD_CNY", "6.8"))
RESERVE_MULTIPLIER = float(os.environ.get("NOTEAI_PRICING_RESERVE_MULTIPLIER", "1.3"))


@dataclass(frozen=True)
class ModelPrice:
    currency: str
    input_per_1m: float
    output_per_1m: float


PRICES = {
    "claude_haiku": ModelPrice("USD", 1.0, 5.0),
    "claude_sonnet": ModelPrice("USD", 3.0, 15.0),
    "kimi_k25": ModelPrice("RMB", 4.0, 21.0),
    "kimi_vision_32k": ModelPrice("RMB", 5.0, 20.0),
}


@dataclass(frozen=True)
class Part:
    model: str
    input_k: float
    output_k: float


SCENARIOS: dict[str, list[Part]] = {
    "score_light": [Part("claude_haiku", 0.7, 0.1)],
    "screenshot_ocr_single": [Part("kimi_vision_32k", 3.5, 0.4)],
    "screenshot_ocr_with_validate": [
        Part("kimi_vision_32k", 3.5, 0.4),
        Part("claude_haiku", 3.0, 0.3),
    ],
    "cover_extract": [Part("kimi_k25", 3.0, 0.2)],
    "extra_image_quick": [Part("kimi_vision_32k", 2.2, 0.08)],
    "video_understand_15s": [Part("kimi_vision_32k", 10.8, 0.8)],
    "video_understand_60s": [Part("kimi_vision_32k", 20.8, 1.2)],
    "video_understand_90s": [Part("kimi_vision_32k", 26.8, 1.4)],
    "ai_diagnosis_manual_base": [Part("claude_haiku", 38.0, 3.7)],
    "ai_diagnosis_with_cover_base": [
        Part("claude_haiku", 40.0, 3.95),
        Part("kimi_k25", 3.0, 0.2),
    ],
    "ai_diagnosis_p95_one_repair": [
        Part("claude_haiku", 43.0, 4.35),
        Part("kimi_k25", 3.0, 0.2),
        Part("claude_sonnet", 8.0, 1.5),
    ],
    "ai_diagnosis_video_60s_p95": [
        Part("claude_haiku", 43.0, 4.35),
        Part("kimi_k25", 3.0, 0.2),
        Part("kimi_vision_32k", 20.8, 1.2),
        Part("claude_sonnet", 8.0, 1.5),
    ],
    "viral_generation_no_image_base": [
        Part("claude_haiku", 19.0, 2.6),
        Part("claude_sonnet", 10.0, 5.0),
    ],
    "viral_generation_one_image_base": [
        Part("claude_haiku", 21.0, 2.9),
        Part("claude_sonnet", 10.0, 5.0),
        Part("kimi_vision_32k", 3.8, 0.35),
    ],
    "viral_generation_p95_repair": [
        Part("claude_haiku", 29.0, 3.9),
        Part("claude_sonnet", 22.0, 11.0),
        Part("kimi_vision_32k", 3.8, 0.35),
    ],
    "chat_fast_answer": [Part("claude_sonnet", 3.0, 0.7)],
    "chat_rewrite_base": [
        Part("claude_sonnet", 6.0, 3.5),
        Part("claude_haiku", 0.8, 0.1),
    ],
    "chat_rewrite_p95_repair": [
        Part("claude_sonnet", 14.0, 7.0),
        Part("claude_haiku", 6.0, 0.7),
    ],
}


def scenario_cost(parts: list[Part]) -> dict:
    input_tokens = 0
    output_tokens = 0
    claude_cost_usd = 0.0
    kimi_cost_rmb = 0.0
    for part in parts:
        price = PRICES[part.model]
        input_tokens += int(part.input_k * 1000)
        output_tokens += int(part.output_k * 1000)
        cost = (
            part.input_k * 1000 / 1_000_000 * price.input_per_1m
            + part.output_k * 1000 / 1_000_000 * price.output_per_1m
        )
        if price.currency == "USD":
            claude_cost_usd += cost
        else:
            kimi_cost_rmb += cost
    claude_cost_rmb_est = claude_cost_usd * USD_CNY
    total_cost_rmb_est = claude_cost_rmb_est + kimi_cost_rmb
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "claude_cost_usd": round(claude_cost_usd, 6),
        "kimi_cost_rmb": round(kimi_cost_rmb, 4),
        "claude_cost_rmb_est": round(claude_cost_rmb_est, 4),
        "total_cost_rmb_est": round(total_cost_rmb_est, 4),
        "reserved_total_cost_rmb_est": round(total_cost_rmb_est * RESERVE_MULTIPLIER, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a markdown table")
    args = parser.parse_args()

    rows = {name: scenario_cost(parts) for name, parts in SCENARIOS.items()}
    if args.json:
        print(json.dumps({
            "currency_note": "Claude is billed in USD; Kimi/Moonshot China is billed in RMB. RMB totals are estimates using usd_cny.",
            "usd_cny": USD_CNY,
            "reserve_multiplier": RESERVE_MULTIPLIER,
            "scenarios": rows,
        }, indent=2))
        return 0

    print(f"USD/CNY={USD_CNY} reserve={RESERVE_MULTIPLIER}x")
    print("| scenario | input | output | total | Claude USD | Kimi RMB | total RMB est | reserved RMB est |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, row in rows.items():
        print(
            f"| {name} | {row['input_tokens']:,} | {row['output_tokens']:,} | "
            f"{row['total_tokens']:,} | ${row['claude_cost_usd']:.6f} | "
            f"¥{row['kimi_cost_rmb']:.4f} | ¥{row['total_cost_rmb_est']:.4f} | "
            f"¥{row['reserved_total_cost_rmb_est']:.4f} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
