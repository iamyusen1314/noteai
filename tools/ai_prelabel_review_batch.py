#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create AI-assisted prelabel review packets without writing final labels.

The output is intentionally not ingest-ready: official human label fields stay
blank unless a later review promotion step explicitly accepts the suggestions.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(MODEL_DIR / ".env")
except Exception:
    pass

from v04_composite_features import build_composite_features, canonical_domain  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "quality" / "review_packets"
KIMI_API_URL = "https://api.moonshot.cn/v1/chat/completions"
KIMI_REVIEW_MODEL = os.environ.get("NOTEAI_KIMI_REVIEW_MODEL", "kimi-k2.6")
KIMI_REVIEW_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=20.0, pool=10.0)
CLAUDE_REVIEW_MODEL = os.environ.get("NOTEAI_CLAUDE_REVIEW_MODEL", "claude-sonnet-4-6")
CLAUDE_REVIEW_FALLBACK_MODEL = os.environ.get("NOTEAI_CLAUDE_REVIEW_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_REVIEW_TIMEOUT_SECONDS = float(os.environ.get("NOTEAI_CLAUDE_REVIEW_TIMEOUT_SECONDS", "90"))

BODY_TARGETS = {
    "美食": (220, 380),
    "旅行": (300, 560),
    "穿搭": (160, 320),
    "美妆": (180, 340),
    "家居": (240, 460),
    "健身": (220, 460),
    "母婴": (220, 420),
}

READY_THRESHOLD = 78
NEAR_READY_THRESHOLD = 68
SERIOUS_FAILURE_TAGS = {
    "title_unreadable",
    "too_short",
    "fact_overclaim",
    "wrong_industry",
    "body_template",
    "score_hacking",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value or "").strip()
        if text == "":
            return default
        return float(text)
    except Exception:
        return default


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _truncate(text: str, limit: int = 2200) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[已截断]"


def _as_bool(value: Any) -> bool | None:
    text = _clean(value).lower()
    if text in {"true", "1", "yes", "y", "是", "可交付", "ready"}:
        return True
    if text in {"false", "0", "no", "n", "否", "不可交付", "not_ready"}:
        return False
    if isinstance(value, bool):
        return value
    return None


def _pipe_list(value: Any) -> str:
    if isinstance(value, list):
        parts = [_clean(item) for item in value if _clean(item)]
        return "|".join(dict.fromkeys(parts))
    text = _clean(value)
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[|,，、\s]+", text) if part.strip()]
    return "|".join(dict.fromkeys(parts))


def _tag_set(value: Any) -> set[str]:
    return {part for part in _pipe_list(value).split("|") if part}


def _body_len_without_tags(body: str) -> int:
    return len("".join(part for part in body.split("#", 1)[:1]).strip())


def _golden_features(title: str, body: str, domain: str) -> dict[str, float]:
    try:
        return build_composite_features(title=title, body=body, domain=domain)
    except Exception:
        return {}


def _feature_value(features: dict[str, float], key: str) -> float:
    return float(features.get(key, 0.0) or 0.0)


def _golden_score_and_tags(title: str, body: str, domain: str) -> tuple[int, list[str], dict[str, float]]:
    features = _golden_features(title, body, domain)
    body_len = _body_len_without_tags(body)
    lo, hi = BODY_TARGETS.get(domain, (180, 420))
    score = 50.0
    tags: list[str] = []

    title_len = len(title)
    if 8 <= title_len <= 18:
        score += 8
    elif title_len < 6:
        score -= 10
        tags.append("title_weak_hook")
    else:
        score -= 6
        tags.append("title_unreadable")

    if _feature_value(features, "commercial_title_unreadable_risk") > 0:
        score -= 14
        tags.append("title_unreadable")
    if _feature_value(features, "commercial_title_has_recommendation") > 0:
        score += 4
    if _feature_value(features, "commercial_title_has_number") > 0:
        score += 3

    if lo <= body_len <= hi:
        score += 12
    elif body_len < lo:
        score -= 12
        tags.append("too_short")
    else:
        score -= 5
        tags.append("too_long")

    coverage = _feature_value(features, "commercial_domain_slot_coverage")
    score += min(18, coverage * 22)
    if coverage < 0.35:
        tags.append("low_info_density")
    if _feature_value(features, "commercial_actionability") < 0.25:
        tags.append("low_info_density")
    else:
        score += 5
    if _feature_value(features, "commercial_body_has_cta") > 0:
        score += 4
    else:
        tags.append("missing_cta")
    if _feature_value(features, "commercial_body_template_phrase_count") >= 2:
        score -= 8
        tags.append("body_template")
    if _feature_value(features, "commercial_body_low_quality_phrase_count") >= 2:
        score -= 5
        tags.append("score_hacking")

    nat = _feature_value(features, "commercial_naturalness_score")
    ai_prob = _feature_value(features, "commercial_ai_probability")
    if nat:
        score += max(-8, min(8, (nat - 50) / 6))
    if ai_prob >= 0.85:
        score -= 4
        tags.append("ai_smell")

    if len(set(tags)) == 0 and score >= READY_THRESHOLD:
        tags.append("delivery_ready")
    elif score >= NEAR_READY_THRESHOLD:
        tags.append("needs_minor_revision")

    return int(round(max(0, min(100, score)))), list(dict.fromkeys(tags)), features


def _ai_smell_level(features: dict[str, float], tags: list[str]) -> int:
    ai_prob = _feature_value(features, "commercial_ai_probability")
    template_count = _feature_value(features, "commercial_body_template_phrase_count")
    if "body_template" in tags or ai_prob >= 0.9 or template_count >= 3:
        return 4
    if ai_prob >= 0.7 or "score_hacking" in tags:
        return 3
    if ai_prob >= 0.45:
        return 2
    return 1


def _rating_1_to_5(value: float) -> int:
    if value >= 0.8:
        return 5
    if value >= 0.6:
        return 4
    if value >= 0.4:
        return 3
    if value >= 0.2:
        return 2
    return 1


def _confidence(score: int, tags: list[str], features: dict[str, float]) -> float:
    dist = abs(score - READY_THRESHOLD)
    conf = 0.55 + min(0.25, dist / 100)
    if _feature_value(features, "commercial_naturalness_available"):
        conf += 0.05
    if "fact_overclaim" in tags or "title_unreadable" in tags:
        conf += 0.05
    return round(max(0.5, min(0.92, conf)), 2)


def _json_from_text(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty Kimi review response")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Kimi review response is not a JSON object")
    return data


def _call_kimi_json(system: str, user: str, max_tokens: int = 900) -> dict[str, Any]:
    key = os.environ.get("MOONSHOT_API_KEY", "")
    if not key:
        raise RuntimeError("MOONSHOT_API_KEY not configured")
    def _post(messages: list[dict[str, str]], tokens: int) -> str:
        payload = {
        "model": KIMI_REVIEW_MODEL,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": tokens,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=KIMI_REVIEW_TIMEOUT) as client:
            response = client.post(KIMI_API_URL, json=payload, headers={"Authorization": f"Bearer {key}"})
            if response.status_code >= 400:
                detail = response.text[:500]
                # Some Moonshot-compatible models may not support JSON mode. Retry
                # once without response_format before treating it as an API error.
                if response.status_code == 400 and "response_format" in detail:
                    payload.pop("response_format", None)
                    response = client.post(KIMI_API_URL, json=payload, headers={"Authorization": f"Bearer {key}"})
                    if response.status_code >= 400:
                        detail = response.text[:500]
                        raise RuntimeError(f"Kimi review HTTP {response.status_code}: {detail}")
                else:
                    raise RuntimeError(f"Kimi review HTTP {response.status_code}: {detail}")
        return response.json()["choices"][0]["message"]["content"]

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = _post(messages, max_tokens)
    try:
        return _json_from_text(raw)
    except Exception as parse_exc:
        repair_system = "你是 JSON 修复器。只输出严格 JSON 对象，不要 Markdown，不要解释。"
        repair_user = (
            "下面内容本应是 JSON，但格式可能有中文引号、未转义引号或多余文字。"
            "请只保留并修复为严格 JSON 对象，字段名和值含义不变。\n\n"
            f"{raw[:3000]}"
        )
        repaired = _post(
            [
                {"role": "system", "content": repair_system},
                {"role": "user", "content": repair_user},
            ],
            min(max_tokens, 700),
        )
        try:
            return _json_from_text(repaired)
        except Exception:
            raise RuntimeError(f"Kimi review JSON parse failed: {parse_exc}; raw={raw[:300]}")


KimiJsonCall = Callable[[str, str, int], dict[str, Any]]


def _call_claude_json(system: str, user: str, max_tokens: int = 900) -> dict[str, Any]:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    try:
        import anthropic  # type: ignore
    except Exception as exc:
        raise RuntimeError("anthropic package is not installed in the active Python environment") from exc

    client = anthropic.Anthropic(api_key=key, timeout=CLAUDE_REVIEW_TIMEOUT_SECONDS)
    last_error: Exception | None = None
    for model in dict.fromkeys([CLAUDE_REVIEW_MODEL, CLAUDE_REVIEW_FALLBACK_MODEL]):
        if not model:
            continue
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=0.2,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
            try:
                data = _json_from_text(raw)
            except Exception as parse_exc:
                repair_response = client.messages.create(
                    model=model,
                    max_tokens=min(max_tokens, 700),
                    temperature=0.0,
                    system="你是 JSON 修复器。只输出严格 JSON 对象，不要 Markdown，不要解释。",
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "下面内容本应是 JSON，但可能有中文引号、未转义引号或多余文字。"
                                "请只保留并修复为严格 JSON 对象，字段名和值含义不变。\n\n"
                                f"{raw[:3000]}"
                            ),
                        }
                    ],
                )
                repaired = "".join(
                    block.text for block in repair_response.content if getattr(block, "type", "") == "text"
                )
                try:
                    data = _json_from_text(repaired)
                except Exception:
                    raise RuntimeError(f"Claude review JSON parse failed: {parse_exc}; raw={raw[:300]}") from parse_exc
            data["_claude_model"] = model
            return data
        except Exception as exc:
            last_error = exc
            msg = str(exc).lower()
            if "authentication" in msg or "api_key" in msg or "unauthorized" in msg:
                raise
            continue
    raise RuntimeError(f"Claude review failed: {last_error}")


ClaudeJsonCall = Callable[[str, str, int], dict[str, Any]]


def _domain_brief(domain: str) -> str:
    briefs = {
        "美食": "关注标题是否有真实决策钩子；正文是否写清菜品/口味/人均/位置/适合人群/避坑，但不要因用户未提供营业时间而重罚。",
        "旅行": "关注路线、预算、交通、住宿/景点、季节、避坑和情绪记忆；酒店/酒旅事实缺失可标 unknown，不要凭空判 overclaim。",
        "穿搭": "关注身材/场景/单品/版型/配色/尺码/价格/搭配逻辑；标题要自然，不要只靠夸张词。",
        "美妆": "关注肤质、色号/产品、妆效、持妆、使用量、适合/不适合；医疗功效或绝对化承诺才算事实风险。",
        "家居": "关注空间、面积/预算、动线、改造前后、清单和踩坑；真实生活感比硬塞参数更重要。",
        "健身": "关注动作、组次/频率、目标、饮食、安全边界；涉及伤病治疗或极端减脂需谨慎。",
        "母婴": "关注月龄/年龄、安全、步骤、材料、观察点和适用边界；医疗/剂量建议不清时要降分或标风险。",
    }
    return briefs.get(domain, "关注标题可读性、正文信息密度、行业适配、自然度、事实安全和用户可执行价值。")


def _claude_golden_review(row: dict[str, Any], call_claude_json: ClaudeJsonCall = _call_claude_json) -> dict[str, Any]:
    title = _clean(row.get("title") or row.get("note_title"))
    body = _clean(row.get("body") or row.get("desc") or row.get("note_content"))
    domain = canonical_domain(row.get("domain"))
    heuristic_score, heuristic_tags, features = _golden_score_and_tags(title, body, domain)
    feature_hint = {
        "heuristic_score": heuristic_score,
        "heuristic_failure_tags": heuristic_tags,
        "body_len": _body_len_without_tags(body),
        "slot_coverage": round(_feature_value(features, "commercial_domain_slot_coverage"), 3),
        "actionability": round(_feature_value(features, "commercial_actionability"), 3),
        "naturalness_score": round(_feature_value(features, "commercial_naturalness_score"), 1),
        "ai_probability": round(_feature_value(features, "commercial_ai_probability"), 3),
    }
    system = """你是 NoteAI V0.4 训练标注的 Claude 主审，目标是为商业化小红书 SaaS 建立高质量评分标签。
你不是内容生成者，不能为了讨好训练而放水；也不能机械按槽位扣分。
请判断这篇笔记对真实用户是否有付费价值：标题是否自然有点击理由、正文是否具体可信、有行业信息密度、表达是否像真人、有无模板感或事实风险。
事实规则：缺少价格/地址/营业时间不等于造假；本地生活/酒旅后续会用事实源补齐。只有明显虚构、绝对化功效、错误行业或高风险建议才标 overclaim/wrong_industry。
评分锚点：85-100 高质量可商用；72-84 可交付但可优化；60-71 可作为对话优化基础；低于60 不应直接交付。
只输出严格 JSON 对象，不要 Markdown。
字段：
quality_score: 0-100 整数；
delivery_ready: boolean；
naturalness_label: 0-100 整数；
hook_quality/body_value/industry_fit: 1-5 整数；
fact_status: safe/unknown/overclaim/wrong_industry；
ai_smell_level: 1-5 整数；
failure_tags: 字符串数组，可用 title_unreadable, title_weak_hook, too_short, too_long, low_info_density, missing_cta, body_template, ai_smell, fact_overclaim, wrong_industry, score_hacking, needs_minor_revision；
confidence: 0-1；
rationale: 80字以内中文理由。"""
    user = (
        f"品类：{domain}\n"
        f"行业审稿重点：{_domain_brief(domain)}\n"
        f"标题：{title}\n"
        f"正文：{_truncate(body)}\n\n"
        f"本地特征仅作参考，不能机械照搬：{json.dumps(feature_hint, ensure_ascii=False)}"
    )
    data = call_claude_json(system, user, 1000)
    score = int(round(max(0, min(100, _to_float(data.get("quality_score"), heuristic_score)))))
    fact_status = _clean(data.get("fact_status")) or "safe"
    if fact_status == "uncertain":
        fact_status = "unknown"
    if fact_status not in {"safe", "unknown", "overclaim", "wrong_industry"}:
        fact_status = "safe"
    tags = _pipe_list(data.get("failure_tags"))
    model = _clean(data.get("_claude_model")) or CLAUDE_REVIEW_MODEL
    return {
        "review_decision": "",
        "review_note": "",
        "ai_review_status": "ok",
        "ai_human_quality_score": score,
        "ai_delivery_ready": "true" if _as_bool(data.get("delivery_ready")) else "false",
        "ai_naturalness_label": int(round(max(0, min(100, _to_float(data.get("naturalness_label"), 70))))),
        "ai_hook_quality": int(round(max(1, min(5, _to_float(data.get("hook_quality"), 3))))),
        "ai_body_value": int(round(max(1, min(5, _to_float(data.get("body_value"), 3))))),
        "ai_industry_fit": int(round(max(1, min(5, _to_float(data.get("industry_fit"), 3))))),
        "ai_fact_status": fact_status,
        "ai_smell_level": int(round(max(1, min(5, _to_float(data.get("ai_smell_level"), 3))))),
        "ai_failure_tags": tags,
        "ai_confidence": round(max(0.0, min(1.0, _to_float(data.get("confidence"), 0.65))), 2),
        "ai_needs_human_review": "false" if score >= 72 and _to_float(data.get("confidence"), 0.0) >= 0.78 else "true",
        "ai_rationale": _clean(data.get("rationale"))[:220],
        "ai_reviewer": f"claude_primary_reviewer_v0.4:{model}",
        "ai_reviewed_at": _now_iso(),
        "ai_heuristic_score": heuristic_score,
        "ai_heuristic_failure_tags": "|".join(heuristic_tags),
    }


def prelabel_golden_row_with_claude(
    row: dict[str, Any],
    call_claude_json: ClaudeJsonCall = _call_claude_json,
) -> dict[str, Any]:
    out = dict(row)
    try:
        out.update(_claude_golden_review(row, call_claude_json))
    except Exception as exc:
        fallback = prelabel_golden_row(row)
        fallback["ai_review_status"] = "failed"
        fallback["ai_error"] = str(exc)[:240]
        fallback["ai_reviewer"] = "claude_primary_failed_heuristic_fallback_v0.1"
        fallback["ai_needs_human_review"] = "true"
        out.update(fallback)
    return out


def prelabel_golden_row(row: dict[str, Any]) -> dict[str, Any]:
    title = _clean(row.get("title") or row.get("note_title"))
    body = _clean(row.get("body") or row.get("desc") or row.get("note_content"))
    domain = canonical_domain(row.get("domain"))
    score, tags, features = _golden_score_and_tags(title, body, domain)
    delivery_ready = score >= READY_THRESHOLD and not any(
        tag in tags for tag in {"title_unreadable", "too_short", "fact_overclaim", "wrong_industry"}
    )
    coverage = _feature_value(features, "commercial_domain_slot_coverage")
    naturalness = int(round(max(0, min(100, _feature_value(features, "commercial_naturalness_score") or (70 if "ai_smell" not in tags else 45)))))
    conf = _confidence(score, tags, features)
    needs_review = score < 45 or 62 <= score <= 82 or conf < 0.78 or "title_unreadable" in tags
    rationale = (
        f"AI预标注：{domain}；分数{score}；行业事实槽覆盖{coverage:.2f}；"
        f"正文长度{_body_len_without_tags(body)}；主要问题：{','.join(tags) or '无明显硬伤'}。"
    )
    out = dict(row)
    out.update(
        {
            "review_decision": "",
            "review_note": "",
            "ai_human_quality_score": score,
            "ai_delivery_ready": "true" if delivery_ready else "false",
            "ai_naturalness_label": naturalness,
            "ai_hook_quality": _rating_1_to_5(1.0 - _feature_value(features, "commercial_title_unreadable_risk")),
            "ai_body_value": _rating_1_to_5(min(1.0, coverage + _feature_value(features, "commercial_actionability") / 2)),
            "ai_industry_fit": _rating_1_to_5(coverage),
            "ai_fact_status": "safe",
            "ai_smell_level": _ai_smell_level(features, tags),
            "ai_failure_tags": "|".join(tags),
            "ai_confidence": conf,
            "ai_needs_human_review": "true" if needs_review else "false",
            "ai_rationale": rationale,
            "ai_reviewer": "noteai_ai_prelabeller_v0.1",
            "ai_reviewed_at": _now_iso(),
        }
    )
    return out


def _variant_quality(title: str, body: str, domain: str, explicit_score: Any) -> tuple[float, list[str], dict[str, float]]:
    local_score, tags, features = _golden_score_and_tags(title, body, domain)
    model_score = _to_float(explicit_score, default=local_score)
    # Blend explicit generated score with heuristic value. The explicit score is
    # still only a signal, not a training label.
    blended = model_score * 0.55 + local_score * 0.45
    if _feature_value(features, "commercial_title_unreadable_risk") > 0:
        blended -= 8
    if "body_template" in tags:
        blended -= 5
    return max(0, min(100, blended)), tags, features


def prelabel_preference_row(row: dict[str, Any]) -> dict[str, Any]:
    domain = canonical_domain(row.get("domain"))
    a_score, a_tags, a_features = _variant_quality(
        _clean(row.get("variant_a_title")),
        _clean(row.get("variant_a_body")),
        domain,
        row.get("variant_a_score"),
    )
    b_score, b_tags, b_features = _variant_quality(
        _clean(row.get("variant_b_title")),
        _clean(row.get("variant_b_body")),
        domain,
        row.get("variant_b_score"),
    )
    diff = a_score - b_score
    if abs(diff) < 3:
        winner = "tie"
        margin = 0
    elif diff > 0:
        winner = "A"
        margin = 3 if diff >= 18 else 2 if diff >= 8 else 1
    else:
        winner = "B"
        margin = 3 if diff <= -18 else 2 if diff <= -8 else 1

    winner_score = max(a_score, b_score)
    delivery_ready = winner_score >= READY_THRESHOLD
    reason_tags: list[str] = []
    loser_tags = b_tags if winner == "A" else a_tags if winner == "B" else list(set(a_tags + b_tags))
    if winner != "tie":
        win_features = a_features if winner == "A" else b_features
        lose_features = b_features if winner == "A" else a_features
        if _feature_value(win_features, "commercial_title_unreadable_risk") < _feature_value(lose_features, "commercial_title_unreadable_risk"):
            reason_tags.append("title_readability")
        if _feature_value(win_features, "commercial_domain_slot_coverage") > _feature_value(lose_features, "commercial_domain_slot_coverage"):
            reason_tags.append("info_density")
            reason_tags.append("industry_fit")
        if _feature_value(win_features, "commercial_naturalness_score") > _feature_value(lose_features, "commercial_naturalness_score"):
            reason_tags.append("naturalness")
        if not reason_tags:
            reason_tags.append("better_user_value")
    else:
        reason_tags.append("similar_quality")

    conf = round(max(0.52, min(0.92, 0.55 + abs(diff) / 55)), 2)
    out = dict(row)
    out.update(
        {
            "review_decision": "",
            "review_note": "",
            "ai_winner": winner,
            "ai_preference_margin": margin,
            "ai_delivery_ready_winner": "true" if delivery_ready else "false",
            "ai_reason_tags": "|".join(dict.fromkeys(reason_tags)),
            "ai_loser_failure_tags": "|".join(dict.fromkeys(loser_tags)),
            "ai_confidence": conf,
            "ai_needs_human_review": "true" if winner == "tie" or margin <= 1 or conf < 0.75 else "false",
            "ai_variant_a_quality": round(a_score, 2),
            "ai_variant_b_quality": round(b_score, 2),
            "ai_rationale": (
                f"AI预标注：A={a_score:.1f}，B={b_score:.1f}，差值={diff:.1f}；"
                f"建议 winner={winner}，margin={margin}。"
            ),
            "ai_reviewer": "noteai_ai_prelabeller_v0.1",
            "ai_reviewed_at": _now_iso(),
        }
    )
    return out


def _kimi_golden_review(row: dict[str, Any], call_kimi_json: KimiJsonCall = _call_kimi_json) -> dict[str, Any]:
    system = """你是 NoteAI V0.4 商业质量第二评审，由 Kimi 独立复核首审建议。
你不是生成者，也不能迎合首审。请按用户是否愿意付费获得这篇笔记来判断。
只输出 JSON，不要 Markdown，不要解释 JSON 以外的内容。
字段：
quality_score: 0-100 整数；
delivery_ready: boolean；
naturalness_label: 0-100 整数；
hook_quality/body_value/industry_fit: 1-5 整数；
fact_status: safe/unknown/overclaim/wrong_industry；
ai_smell_level: 1-5 整数；
failure_tags: 字符串数组，可用 title_unreadable, too_short, too_long, low_info_density, missing_cta, body_template, ai_smell, fact_overclaim, wrong_industry, score_hacking, needs_minor_revision；
confidence: 0-1；
rationale: 60字以内中文理由。"""
    user = (
        f"品类：{canonical_domain(row.get('domain'))}\n"
        f"标题：{_clean(row.get('title') or row.get('note_title'))}\n"
        f"正文：{_truncate(_clean(row.get('body') or row.get('desc') or row.get('note_content')))}\n\n"
        "首审建议，仅供参考，不可盲从：\n"
        f"score={row.get('ai_human_quality_score')} delivery_ready={row.get('ai_delivery_ready')} "
        f"failure_tags={row.get('ai_failure_tags')} confidence={row.get('ai_confidence')}\n"
    )
    data = call_kimi_json(system, user, 900)
    fact_status = _clean(data.get("fact_status")) or "safe"
    if fact_status == "uncertain":
        fact_status = "unknown"
    if fact_status not in {"safe", "unknown", "overclaim", "wrong_industry"}:
        fact_status = "safe"
    return {
        "kimi_review_status": "ok",
        "kimi_human_quality_score": int(round(max(0, min(100, _to_float(data.get("quality_score")))))),
        "kimi_delivery_ready": "true" if _as_bool(data.get("delivery_ready")) else "false",
        "kimi_naturalness_label": int(round(max(0, min(100, _to_float(data.get("naturalness_label")))))),
        "kimi_hook_quality": int(round(max(1, min(5, _to_float(data.get("hook_quality"), 3))))),
        "kimi_body_value": int(round(max(1, min(5, _to_float(data.get("body_value"), 3))))),
        "kimi_industry_fit": int(round(max(1, min(5, _to_float(data.get("industry_fit"), 3))))),
        "kimi_fact_status": fact_status,
        "kimi_ai_smell_level": int(round(max(1, min(5, _to_float(data.get("ai_smell_level"), 3))))),
        "kimi_failure_tags": _pipe_list(data.get("failure_tags")),
        "kimi_confidence": round(max(0.0, min(1.0, _to_float(data.get("confidence"), 0.5))), 2),
        "kimi_rationale": _clean(data.get("rationale"))[:180],
        "kimi_reviewer": "kimi_second_reviewer_v0.1",
        "kimi_reviewed_at": _now_iso(),
    }


def _kimi_preference_review(row: dict[str, Any], call_kimi_json: KimiJsonCall = _call_kimi_json) -> dict[str, Any]:
    system = """你是 NoteAI V0.4 商业质量第二评审，由 Kimi 独立复核 A/B 哪篇更值得交付。
请优先判断：标题是否自然有吸引力、正文是否具体有价值、是否适配行业、是否像模板、是否有事实风险。
只输出 JSON，不要 Markdown，不要解释 JSON 以外的内容。
字段：
winner: A/B/tie；
preference_margin: 0-3 整数，0表示相近，3表示明显胜出；
delivery_ready_winner: boolean；
reason_tags: 字符串数组，可用 title_readability, info_density, naturalness, industry_fit, fact_safety, better_user_value；
loser_failure_tags: 字符串数组；
confidence: 0-1；
rationale: 80字以内中文理由。"""
    user = (
        f"品类：{canonical_domain(row.get('domain'))}\n"
        f"任务背景：{_truncate(_clean(row.get('task_context')), 700)}\n\n"
        f"A标题：{_clean(row.get('variant_a_title'))}\n"
        f"A正文：{_truncate(_clean(row.get('variant_a_body')), 1600)}\n\n"
        f"B标题：{_clean(row.get('variant_b_title'))}\n"
        f"B正文：{_truncate(_clean(row.get('variant_b_body')), 1600)}\n\n"
        "首审建议，仅供参考，不可盲从：\n"
        f"winner={row.get('ai_winner')} margin={row.get('ai_preference_margin')} "
        f"A_quality={row.get('ai_variant_a_quality')} B_quality={row.get('ai_variant_b_quality')} "
        f"reason_tags={row.get('ai_reason_tags')} confidence={row.get('ai_confidence')}\n"
    )
    data = call_kimi_json(system, user, 900)
    winner = _clean(data.get("winner")).upper()
    if winner not in {"A", "B", "TIE"}:
        winner = "tie"
    if winner == "TIE":
        winner = "tie"
    return {
        "kimi_review_status": "ok",
        "kimi_winner": winner,
        "kimi_preference_margin": int(round(max(0, min(3, _to_float(data.get("preference_margin"), 0))))),
        "kimi_delivery_ready_winner": "true" if _as_bool(data.get("delivery_ready_winner")) else "false",
        "kimi_reason_tags": _pipe_list(data.get("reason_tags")),
        "kimi_loser_failure_tags": _pipe_list(data.get("loser_failure_tags")),
        "kimi_confidence": round(max(0.0, min(1.0, _to_float(data.get("confidence"), 0.5))), 2),
        "kimi_rationale": _clean(data.get("rationale"))[:220],
        "kimi_reviewer": "kimi_second_reviewer_v0.1",
        "kimi_reviewed_at": _now_iso(),
    }


def _apply_golden_consensus(row: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    if _clean(row.get("ai_review_status")).lower() == "failed":
        flags.append("primary_review_failed")
    ai_score = _to_float(row.get("ai_human_quality_score"))
    kimi_score = _to_float(row.get("kimi_human_quality_score"), default=ai_score)
    if abs(ai_score - kimi_score) >= 12:
        flags.append("score_gap")
    if _as_bool(row.get("ai_delivery_ready")) != _as_bool(row.get("kimi_delivery_ready")):
        flags.append("delivery_ready_mismatch")
    ai_fact = _clean(row.get("ai_fact_status")).lower()
    kimi_fact = _clean(row.get("kimi_fact_status")).lower()
    if ai_fact in {"uncertain", "overclaim", "wrong_industry"} or kimi_fact in {"uncertain", "overclaim", "wrong_industry"}:
        flags.append("fact_or_industry_risk")
    ai_serious = _tag_set(row.get("ai_failure_tags")) & SERIOUS_FAILURE_TAGS
    kimi_serious = _tag_set(row.get("kimi_failure_tags")) & SERIOUS_FAILURE_TAGS
    if ai_serious != kimi_serious:
        flags.append("serious_failure_tag_mismatch")
    if _to_float(row.get("kimi_confidence")) < 0.7:
        flags.append("low_kimi_confidence")
    row["judge_consensus"] = "agree" if not flags else "disagree"
    row["judge_disagreement_flags"] = "|".join(flags)
    row["consensus_label_source"] = "ai_rubric_consensus" if not flags else "holdout_due_to_judge_disagreement"
    if flags:
        row["ai_needs_human_review"] = "true"
        row["review_decision_recommendation"] = "needs_manual"
    else:
        row["review_decision_recommendation"] = "accept_ai_candidate"
    return row


def _apply_preference_consensus(row: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    ai_winner = _clean(row.get("ai_winner"))
    kimi_winner = _clean(row.get("kimi_winner"))
    if ai_winner != kimi_winner:
        flags.append("winner_mismatch")
    if abs(_to_float(row.get("ai_preference_margin")) - _to_float(row.get("kimi_preference_margin"))) >= 2:
        flags.append("margin_gap")
    if _as_bool(row.get("ai_delivery_ready_winner")) != _as_bool(row.get("kimi_delivery_ready_winner")):
        flags.append("delivery_ready_mismatch")
    if _to_float(row.get("kimi_confidence")) < 0.7:
        flags.append("low_kimi_confidence")
    row["judge_consensus"] = "agree" if not flags else "disagree"
    row["judge_disagreement_flags"] = "|".join(flags)
    row["consensus_label_source"] = "ai_rubric_consensus" if not flags else "holdout_due_to_judge_disagreement"
    if flags:
        row["ai_needs_human_review"] = "true"
        row["review_decision_recommendation"] = "needs_manual"
    else:
        row["review_decision_recommendation"] = "accept_ai_candidate"
    return row


def apply_kimi_second_review(
    row: dict[str, Any],
    kind: str,
    call_kimi_json: KimiJsonCall = _call_kimi_json,
) -> dict[str, Any]:
    out = dict(row)
    try:
        review = _kimi_golden_review(out, call_kimi_json) if kind == "golden" else _kimi_preference_review(out, call_kimi_json)
        out.update(review)
        return _apply_golden_consensus(out) if kind == "golden" else _apply_preference_consensus(out)
    except Exception as exc:
        out.update(
            {
                "kimi_review_status": "failed",
                "kimi_error": str(exc)[:240],
                "kimi_reviewer": "kimi_second_reviewer_v0.1",
                "kimi_reviewed_at": _now_iso(),
                "judge_consensus": "second_review_failed",
                "judge_disagreement_flags": "second_review_failed",
                "consensus_label_source": "holdout_due_to_second_review_failure",
                "ai_needs_human_review": "true",
                "review_decision_recommendation": "needs_manual",
            }
        )
        return out


def prelabel_rows(
    rows: list[dict[str, Any]],
    kind: str,
    *,
    primary_review: str = "heuristic",
    second_review: str = "none",
    call_claude_json: ClaudeJsonCall = _call_claude_json,
    call_kimi_json: KimiJsonCall = _call_kimi_json,
) -> list[dict[str, Any]]:
    if kind == "golden":
        prelabels = []
        for idx, row in enumerate(rows, 1):
            prelabels.append(
                prelabel_golden_row_with_claude(row, call_claude_json)
                if primary_review == "claude"
                else prelabel_golden_row(row)
            )
            if primary_review == "claude" and idx % 10 == 0:
                print(f"[ai-prelabel] Claude primary review {idx}/{len(rows)}", file=sys.stderr, flush=True)
    else:
        prelabels = [prelabel_preference_row(row) for row in rows]
    if second_review == "kimi":
        reviewed: list[dict[str, Any]] = []
        for idx, row in enumerate(prelabels, 1):
            reviewed.append(apply_kimi_second_review(row, kind, call_kimi_json))
            if idx % 10 == 0:
                print(f"[ai-prelabel] Kimi second review {idx}/{len(prelabels)}", file=sys.stderr, flush=True)
        return reviewed
    return prelabels


def build_report(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    input_path: Path,
    outputs: dict[str, str],
    primary_review: str,
    second_review: str,
) -> dict[str, Any]:
    review_needed = [row for row in rows if str(row.get("ai_needs_human_review")) == "true"]
    by_domain: dict[str, int] = {}
    consensus_counts: dict[str, int] = {}
    second_review_status: dict[str, int] = {}
    for row in rows:
        domain = canonical_domain(row.get("domain"))
        by_domain[domain] = by_domain.get(domain, 0) + 1
        consensus = _clean(row.get("judge_consensus")) or "not_run"
        consensus_counts[consensus] = consensus_counts.get(consensus, 0) + 1
        status = _clean(row.get("kimi_review_status")) or "not_run"
        second_review_status[status] = second_review_status.get(status, 0) + 1
    return {
        "version": "ai-prelabel-review-batch-v0.2",
        "created_at": _now_iso(),
        "kind": kind,
        "input": str(input_path),
        "outputs": outputs,
        "review_chain": {
            "primary_review": primary_review,
            "second_review": second_review,
            "claude_review_model": CLAUDE_REVIEW_MODEL if primary_review == "claude" else "",
            "kimi_review_model": KIMI_REVIEW_MODEL if second_review == "kimi" else "",
        },
        "totals": {
            "rows": len(rows),
            "ai_needs_human_review": len(review_needed),
            "ai_can_fast_review": len(rows) - len(review_needed),
        },
        "by_domain": dict(sorted(by_domain.items())),
        "judge_consensus": dict(sorted(consensus_counts.items())),
        "second_review_status": dict(sorted(second_review_status.items())),
        "policy": (
            "AI prelabels are suggestions only. Official label fields remain blank; "
            "Kimi second review can mark disagreement/holdout; "
            "use promote_reviewed_prelabels.py after review approval."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AI-assisted review packets")
    parser.add_argument("--kind", choices=["golden", "preference"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--primary-review", choices=["heuristic", "claude"], default=os.environ.get("NOTEAI_PRIMARY_REVIEW", "heuristic").lower())
    parser.add_argument("--second-review", choices=["none", "kimi"], default=os.environ.get("NOTEAI_SECOND_REVIEW", "none").lower())
    parser.add_argument("--limit", type=int, default=0, help="Optional smoke-test row limit")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    rows = _load_rows(input_path)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    prelabels = prelabel_rows(rows, args.kind, primary_review=args.primary_review, second_review=args.second_review)
    batch_id = args.batch_id or input_path.stem.replace(".", "_")
    stem = f"{batch_id}_{args.kind}_ai_review"
    csv_path = output_dir / f"{stem}.csv"
    jsonl_path = output_dir / f"{stem}.jsonl"
    report_path = output_dir / f"{stem}.report.json"
    _write_csv(csv_path, prelabels)
    _write_jsonl(jsonl_path, prelabels)
    report = build_report(
        prelabels,
        kind=args.kind,
        input_path=input_path,
        outputs={"csv": str(csv_path), "jsonl": str(jsonl_path), "report": str(report_path)},
        primary_review=args.primary_review,
        second_review=args.second_review,
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"rows={report['totals']['rows']} review_needed={report['totals']['ai_needs_human_review']}")
        print(f"csv={csv_path}")
        print(f"jsonl={jsonl_path}")
        print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
