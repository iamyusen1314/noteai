"""
Real performance scoring for published notes.

The score is evidence-based rather than platform-authoritative: crawled,
screenshot/OCR, and manual data can all feed the same calculation, with a
confidence value that prevents low-quality evidence from being treated as
high-certainty training data.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


DEFAULT_BENCHMARK = {
    "like_rate": 0.12,
    "save_rate": 0.075,
    "comment_rate": 0.012,
    "interaction_rate": 0.20,
}

DOMAIN_BENCHMARKS: dict[str, dict[str, float]] = {
    "美食": {"like_rate": 0.13, "save_rate": 0.08, "comment_rate": 0.012, "interaction_rate": 0.22},
    "旅行": {"like_rate": 0.11, "save_rate": 0.085, "comment_rate": 0.011, "interaction_rate": 0.21},
    "美妆": {"like_rate": 0.12, "save_rate": 0.07, "comment_rate": 0.013, "interaction_rate": 0.20},
    "穿搭": {"like_rate": 0.13, "save_rate": 0.065, "comment_rate": 0.012, "interaction_rate": 0.20},
    "家居": {"like_rate": 0.10, "save_rate": 0.09, "comment_rate": 0.010, "interaction_rate": 0.20},
    "母婴": {"like_rate": 0.10, "save_rate": 0.08, "comment_rate": 0.018, "interaction_rate": 0.20},
    "教育": {"like_rate": 0.09, "save_rate": 0.10, "comment_rate": 0.014, "interaction_rate": 0.21},
    "健身": {"like_rate": 0.12, "save_rate": 0.07, "comment_rate": 0.013, "interaction_rate": 0.20},
    "数码": {"like_rate": 0.10, "save_rate": 0.065, "comment_rate": 0.018, "interaction_rate": 0.19},
}

SOURCE_CONFIDENCE = {
    "crawler": 0.82,
    "screenshot": 0.76,
    "manual": 0.64,
    "mixed": 0.72,
    "": 0.58,
}


@dataclass(frozen=True)
class PerformanceScore:
    actual_ces: float
    grade: str
    confidence: float
    confidence_label: str
    evidence_source: str
    views_est: int
    views_estimated: bool
    training_eligible: bool
    insights: dict[str, Any]

    def insights_json(self) -> str:
        return json.dumps(self.insights, ensure_ascii=False, sort_keys=True)


def grade_from_score(score: float) -> str:
    if score >= 75:
        return "优秀"
    if score >= 50:
        return "良好"
    if score >= 25:
        return "待改进"
    return "需优化"


def _benchmarks(domain: str | None) -> dict[str, float]:
    domain_key = (domain or "").strip()
    return {**DEFAULT_BENCHMARK, **DOMAIN_BENCHMARKS.get(domain_key, {})}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _rate_score(rate: float, benchmark: float) -> float:
    if benchmark <= 0:
        return 50.0
    ratio = max(rate, 0.00001) / benchmark
    return _clamp(50.0 + 28.0 * math.log2(ratio))


def _volume_score(total_interactions: int, views: int) -> float:
    if total_interactions <= 0:
        return 8.0
    density = total_interactions / max(views, 1)
    base = _clamp(50.0 + 24.0 * math.log2(max(density, 0.00001) / 0.20))
    volume_bonus = min(12.0, math.log10(total_interactions + 1) * 4.0)
    return _clamp(base + volume_bonus)


def estimate_views(
    *,
    domain: str | None,
    likes: int,
    saves: int,
    comments: int,
    explicit_views: int | None = None,
) -> tuple[int, bool]:
    if explicit_views and explicit_views > 0:
        return max(int(explicit_views), likes + saves + comments, 1), False
    bench = _benchmarks(domain)
    candidates = [
        int(likes / max(bench["like_rate"], 0.001)) if likes else 0,
        int(saves / max(bench["save_rate"], 0.001)) if saves else 0,
        int(comments / max(bench["comment_rate"], 0.001)) if comments else 0,
        100,
    ]
    return max(candidates), True


def score_performance(
    *,
    domain: str | None,
    likes: int = 0,
    saves: int = 0,
    comments: int = 0,
    views: int | None = None,
    predicted_ces: float | None = None,
    evidence_source: str = "manual",
    window: str = "7d",
    likes_24h: int | None = None,
    saves_24h: int | None = None,
    comments_24h: int | None = None,
) -> PerformanceScore:
    likes = max(int(likes or 0), 0)
    saves = max(int(saves or 0), 0)
    comments = max(int(comments or 0), 0)
    views_est, views_estimated = estimate_views(
        domain=domain,
        likes=likes,
        saves=saves,
        comments=comments,
        explicit_views=views,
    )
    bench = _benchmarks(domain)
    like_rate = likes / max(views_est, 1)
    save_rate = saves / max(views_est, 1)
    comment_rate = comments / max(views_est, 1)
    interaction_rate = (likes + saves + comments) / max(views_est, 1)

    save_component = _rate_score(save_rate, bench["save_rate"])
    like_component = _rate_score(like_rate, bench["like_rate"])
    comment_component = _rate_score(comment_rate, bench["comment_rate"])
    interaction_component = _rate_score(interaction_rate, bench["interaction_rate"])
    volume_component = _volume_score(likes + saves + comments, views_est)

    momentum_component = 50.0
    if any(v is not None for v in (likes_24h, saves_24h, comments_24h)):
        early_total = max(int(likes_24h or 0) + int(saves_24h or 0) + int(comments_24h or 0), 1)
        final_total = max(likes + saves + comments, early_total)
        growth_ratio = final_total / early_total
        momentum_component = _clamp(42.0 + 18.0 * math.log2(max(growth_ratio, 1.0)))

    actual = round(
        save_component * 0.34
        + like_component * 0.24
        + comment_component * 0.18
        + interaction_component * 0.12
        + volume_component * 0.07
        + momentum_component * 0.05,
        1,
    )
    actual = round(_clamp(actual), 1)

    source_key = evidence_source if evidence_source in SOURCE_CONFIDENCE else ""
    confidence = SOURCE_CONFIDENCE[source_key]
    if views_estimated:
        confidence -= 0.10
    if likes + saves + comments < 20:
        confidence -= 0.10
    if window == "24h":
        confidence -= 0.05
    confidence = round(max(0.20, min(0.95, confidence)), 2)
    confidence_label = "高" if confidence >= 0.75 else "中" if confidence >= 0.55 else "低"
    training_eligible = confidence >= 0.65 and window == "7d"

    predicted_delta = None
    if predicted_ces is not None:
        try:
            predicted_delta = round(actual - float(predicted_ces), 1)
        except Exception:
            predicted_delta = None

    strongest_signal = max(
        [
            ("收藏率", save_component),
            ("点赞率", like_component),
            ("评论率", comment_component),
            ("综合互动率", interaction_component),
        ],
        key=lambda item: item[1],
    )[0]
    weakest_signal = min(
        [
            ("收藏率", save_component),
            ("点赞率", like_component),
            ("评论率", comment_component),
            ("综合互动率", interaction_component),
        ],
        key=lambda item: item[1],
    )[0]

    insights = {
        "schema_version": "performance_score_v1",
        "window": window,
        "domain": domain or "",
        "metrics": {
            "likes": likes,
            "saves": saves,
            "comments": comments,
            "views_est": views_est,
            "views_estimated": views_estimated,
            "like_rate": round(like_rate, 4),
            "save_rate": round(save_rate, 4),
            "comment_rate": round(comment_rate, 4),
            "interaction_rate": round(interaction_rate, 4),
        },
        "benchmarks": bench,
        "components": {
            "save": round(save_component, 1),
            "like": round(like_component, 1),
            "comment": round(comment_component, 1),
            "interaction": round(interaction_component, 1),
            "volume": round(volume_component, 1),
            "momentum": round(momentum_component, 1),
        },
        "prediction_delta": predicted_delta,
        "strongest_signal": strongest_signal,
        "weakest_signal": weakest_signal,
        "recommendation": _recommendation(strongest_signal, weakest_signal, predicted_delta),
        "evidence": {
            "source": evidence_source,
            "confidence": confidence,
            "confidence_label": confidence_label,
            "training_eligible": training_eligible,
        },
    }
    return PerformanceScore(
        actual_ces=actual,
        grade=grade_from_score(actual),
        confidence=confidence,
        confidence_label=confidence_label,
        evidence_source=evidence_source,
        views_est=views_est,
        views_estimated=views_estimated,
        training_eligible=training_eligible,
        insights=insights,
    )


def _recommendation(strongest: str, weakest: str, predicted_delta: float | None) -> str:
    if predicted_delta is not None and predicted_delta >= 8:
        return f"真实表现明显超出预测，建议复用这次的{strongest}优势，并把该结构沉淀为账号模板。"
    if predicted_delta is not None and predicted_delta <= -8:
        return f"真实表现低于预测，下一版优先补强{weakest}，同时降低对单一卖点的依赖。"
    return f"本次表现与预测接近，下一版建议保留{strongest}优势，并针对{weakest}做小幅迭代。"
