#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill preference generation slots with real model outputs and score artifacts.

This runner is intentionally offline: it reads the generated backlog JSONL,
calls the same model router / quality helpers used by the API, and writes one
auditable artifact per slot. It does not mutate the task pool directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = ROOT / "quality" / "preference_generation_queue.v01.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "quality" / "generated_variants" / "v01"
VERSION = "preference-slot-fill-v0.1"

DIRECT_ROUTES = {"analyze", "generate", "offline_candidate"}
DEPENDENT_ROUTES = {"chat", "second_pass"}
MANUAL_ROUTES = {"manual"}

LOCAL_TIME_DEFAULT = "2026062512"
LEGACY_REFERENCE_SCORE = 72.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not valid JSONL: {exc}") from exc
    return rows


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def artifact_path(output_dir: Path, row: dict[str, Any]) -> Path:
    return output_dir / str(row["task_id"]) / f"{row['slot_id']}.json"


def _split_csv_arg(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def generation_payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("generation_payload_json") or "{}"
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"generation_payload_json must be an object for queue_id={row.get('queue_id')}")
    return payload


def route_support_status(route: str, include_dependent: bool = False) -> tuple[bool, str]:
    if route in DIRECT_ROUTES:
        return True, "direct"
    if route in DEPENDENT_ROUTES:
        if include_dependent:
            return True, "dependent"
        return False, "dependent_route_requires_existing_base"
    if route in MANUAL_ROUTES:
        return False, "manual_slot_requires_human_rewrite"
    return False, f"unsupported_generation_route:{route}"


def select_rows(
    rows: list[dict[str, Any]],
    *,
    domains: set[str] | None = None,
    routes: set[str] | None = None,
    origins: set[str] | None = None,
    task_ids: set[str] | None = None,
    slot_ids: set[str] | None = None,
    include_dependent: bool = False,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    overwrite: bool = False,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        route = str(row.get("generation_route", ""))
        keep = True
        reasons: list[str] = []
        if domains and row.get("domain") not in domains:
            keep = False
            reasons.append("domain_filter")
        if routes and route not in routes:
            keep = False
            reasons.append("route_filter")
        if origins and row.get("origin") not in origins:
            keep = False
            reasons.append("origin_filter")
        if task_ids and row.get("task_id") not in task_ids:
            keep = False
            reasons.append("task_filter")
        if slot_ids and row.get("slot_id") not in slot_ids:
            keep = False
            reasons.append("slot_filter")

        supported, reason = route_support_status(route, include_dependent=include_dependent)
        if not supported:
            keep = False
            reasons.append(reason)

        if artifact_path(output_dir, row).exists() and not overwrite:
            keep = False
            reasons.append("artifact_exists")

        if keep and (limit is None or len(selected) < limit):
            selected.append(row)
        elif keep:
            skipped.append(_skip_record(row, "limit"))
        else:
            skipped.append(_skip_record(row, ";".join(reasons) or "filtered"))
    return selected, skipped


def _skip_record(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "queue_id": row.get("queue_id", ""),
        "task_id": row.get("task_id", ""),
        "slot_id": row.get("slot_id", ""),
        "domain": row.get("domain", ""),
        "generation_route": row.get("generation_route", ""),
        "status": "skipped",
        "reason": reason,
    }


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


_INTERNAL_FACT_CONSTRAINT_RE = re.compile(
    r"(?:用户|创作者|原始信息)?未提供[^。\n]*(?:不能|不可|不得)?编造"
    r"|(?:用户|创作者|原始信息)?未提供"
    r"|(?:不能|不可|不得)编造具体数字"
    r"|缺失字段必须用安全表达"
)


def _is_internal_fact_constraint(text: str) -> bool:
    return bool(_INTERNAL_FACT_CONSTRAINT_RE.search(text or ""))


def source_context_from_payload(payload: dict[str, Any]) -> str:
    domain = str(payload.get("domain", ""))
    facts = [str(item).strip() for item in payload.get("known_facts", []) if str(item).strip()]
    lines = [
        f"- 用户意图：{payload.get('user_intent', '')}",
        f"- 目标读者：{payload.get('target_reader', '')}",
        f"- 事实状态：{payload.get('fact_status', '')}",
    ]
    lines.extend(f"- 已核验事实：{fact}" for fact in facts)
    if domain == "美食":
        lines.extend(_food_labeled_fact_lines(facts))
    elif domain in {"旅行", "旅游", "酒店", "住宿", "酒旅", "民宿", "出行"}:
        lines.extend(_travel_labeled_fact_lines(facts))
    return "\n".join(line for line in lines if line.strip() not in {"-", "- ："})


def _food_labeled_fact_lines(facts: list[str]) -> list[str]:
    out: list[str] = []
    label_patterns: list[tuple[str, re.Pattern[str]]] = [
        ("价格/人均", re.compile(r"(人均|价格|套餐|消费|预算|¥|￥|\d{2,5}\s*元)")),
        ("位置/地址", re.compile(r"(地点|地址|附近|商圈|广场|中心|地铁|万博|南京西路)")),
        ("营业时间", re.compile(r"(营业|开门|闭店|打烊|\d{1,2}[:：]\d{2})")),
        ("预订/排队", re.compile(r"(预订|预约|排队|等位|饭点|周末)")),
        ("必点/招牌菜", re.compile(r"(必点|招牌|推荐菜|推荐点|推荐)")),
        ("评分/口碑", re.compile(r"(评分|口碑|点评|评价|星)")),
    ]
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        if _is_internal_fact_constraint(fact):
            continue
        for label, pattern in label_patterns:
            if pattern.search(fact):
                item = (label, fact)
                if item not in seen:
                    out.append(f"- {label}：{fact}")
                    seen.add(item)
    return out


def _travel_labeled_fact_lines(facts: list[str]) -> list[str]:
    out: list[str] = []
    label_patterns: list[tuple[str, re.Pattern[str]]] = [
        ("路线/景点", re.compile(r"(DAY\s*\d|建议游玩时间|核心景点|路线|景点|断桥|白堤|孤山|三潭印月|花港观鱼|苏堤|灵隐|河坊街|小河直街)")),
        ("酒店/住宿", re.compile(r"(酒店|饭店|民宿|住宿|客房|房型|亲子房|套房|公寓|别墅|元起/晚)")),
        ("交通/距离", re.compile(r"(地铁|步行|公里|米|班车|穿梭|接送|停车|机场|车站|靠近|距离|近)")),
        ("预算/价格", re.compile(r"(预算|价格|花费|费用|门票|元起/晚|元/晚|¥|￥|\\d{2,5}\\s*元)")),
        ("评分/口碑", re.compile(r"(美团真实评分|评分|星级|豪华型|高档型|舒适型|四星级|五星级)")),
        ("设施/体验", re.compile(r"(早餐|儿童|亲子|乐园|泳池|沙滩|隔音|健身房|影院|落地窗|夜景|客控|商务|会议|祈福|文创|小吃|手工艺)")),
        ("季节/避坑", re.compile(r"(最佳|季节|台风|避开|避坑|不适合|人多|体力|注意)")),
    ]
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        if _is_internal_fact_constraint(fact):
            continue
        for label, pattern in label_patterns:
            if pattern.search(fact):
                item = (label, fact)
                if item not in seen:
                    out.append(f"- {label}：{fact}")
                    seen.add(item)
    return out


def _focus_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key, [])
    if isinstance(value, list):
        return "、".join(str(item) for item in value if str(item).strip())
    return str(value or "")


def _route_task(route: str) -> str:
    if route == "analyze":
        return "diagnosis"
    if route == "chat":
        return "chat"
    return "content_gen"


def build_generation_prompt(api: Any, row: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str, str]:
    domain = str(payload.get("domain") or row.get("domain") or "通用")
    route = str(payload.get("generation_route") or row.get("generation_route") or "")
    source_context = source_context_from_payload(payload)
    focus = _focus_text(payload, "prompt_focus") or row.get("prompt_focus", "")
    quality_focus = _focus_text(payload, "quality_focus") or row.get("quality_focus", "")
    reference = payload.get("reference") or {}
    style_name = focus or str(row.get("origin", ""))

    if route == "analyze":
        route_goal = (
            "这是 AI诊断 的一个候选改写方向。必须让标题和正文都服务同一方向，"
            "不要写成三个方案通用模板。"
        )
    elif route == "offline_candidate":
        route_goal = (
            "这是降低AI味的自然候选稿。保留信息密度，但句子要像真实创作者写的，"
            "少用整齐排比和营销腔。"
        )
    else:
        route_goal = "这是爆文生成候选稿。目标是可直接交付，同时保留用于偏好比较的风格差异。"

    system = (
        f"你是 NoteAI 多行业小红书候选稿生成器，当前品类：{domain}。\n"
        "你生成的内容会进入人工偏好标注和模型训练，所以必须真实、可追溯、不可编造结构化事实。\n"
        "只输出XML，不要解释，不要Markdown标题，不要方案编号。\n\n"
        f"{api._get_quality_contract(domain)}\n\n"
        f"{api._get_feature_governance_brief(domain)}\n\n"
        f"{api._build_generation_planning_brief(domain, reference.get('title', ''), source_context, style_name)}\n"
        f"{api._safe_fact_delivery_brief(domain, source_context)}\n\n"
        f"{api._quality_expression_brief(domain)}\n\n"
        f"输出格式：<note><title>{api._TITLE_DELIVERY_MAX}字以内标题</title><body>完整正文，含话题标签</body></note>"
    )
    user = (
        f"任务ID：{payload.get('task_id')}\n"
        f"槽位：{payload.get('slot_id')}｜来源：{payload.get('origin')}｜路线：{route}\n"
        f"槽位目标：{route_goal}\n"
        f"方向聚焦：{focus or '按任务自然生成'}\n"
        f"质量重点：{quality_focus or '标题自然、正文信息密度、事实安全、CTA自然'}\n"
        f"用户意图：{payload.get('user_intent', '')}\n"
        f"目标读者：{payload.get('target_reader', '')}\n\n"
        f"已核验事实/用户原始信息：\n{source_context}\n\n"
        "参考样本只用于理解自然度和任务，不得照抄：\n"
        f"- 参考标题：{reference.get('title', '')}\n"
        f"- 参考正文片段：{reference.get('body_excerpt', '')}\n\n"
        "写作要求：\n"
        "- 标题读起来必须像人写的，不要为了分数堆关键词。\n"
        "- 正文要给读者真实决策帮助，有具体对象、步骤、价格/预算/地址等已提供事实。\n"
        "- 缺失事实可以用安全表达，但不要输出【待补】、XX、占位符。\n"
        "- 标签放在正文末尾，按品类目标数量，不要泛标签堆满。\n"
    )
    return system, user, source_context


def parse_note(raw: str) -> tuple[str, str] | None:
    text = (raw or "").strip()
    if not text:
        return None
    m = re.search(r"<note>(.*?)</note>", text, re.DOTALL)
    if m:
        inner = m.group(1)
        title = re.search(r"<title>(.*?)</title>", inner, re.DOTALL)
        body = re.search(r"<body>(.*?)</body>", inner, re.DOTALL)
        if title and body:
            return title.group(1).strip(), body.group(1).strip()
    title = re.search(r"(?:^|\n)\s*(?:标题|Title)\s*[:：]\s*(.+)", text)
    body = re.search(r"(?:^|\n)\s*(?:正文|Body)\s*[:：]\s*(.+)", text, re.DOTALL)
    if title and body:
        return title.group(1).strip(), body.group(1).strip()
    return None


def load_api_module() -> Any:
    sys.path.insert(0, str(ROOT / "model"))
    import api  # type: ignore

    return api


async def _postprocess_and_score(
    api: Any,
    title: str,
    body: str,
    *,
    domain: str,
    local_time: str,
    source_context: str,
    style_hint: str,
) -> tuple[str, str, float, dict[str, float], str, list[str], bool]:
    title = await api._fit_title_limit(title, body, domain)
    title = api._sanitize_title_for_delivery(title, source_context, domain)
    body = await api._shape_body_for_delivery(title, body, domain, source_context, style_hint)
    score, features, grade = await api._score_generated_note(
        title,
        body,
        domain,
        local_time,
        timing=None,
        cover_feats=None,
    )
    issues = api._generated_quality_issues(title, body, domain, score, features)
    issues.extend(api._delivery_integrity_issues(f"{title}\n{body}", source_context, domain))
    issues.extend(api._body_format_issues(body))
    # Keep order stable while de-duplicating issue text.
    deduped_issues = list(dict.fromkeys(issue for issue in issues if issue))
    blocking = bool(api._has_blocking_quality_issues(score, deduped_issues, domain))
    should_try_second_pass = (
        (not blocking or any("遗漏已提供动作" in issue for issue in deduped_issues))
        and (
            float(score or 0.0) < float(getattr(api, "_GENERATION_DELIVERY_TARGET", 72.0))
            or api._score_gap_issue_count(deduped_issues) > 0
        )
    )
    if should_try_second_pass:
        (
            cand_title,
            cand_body,
            cand_score,
            cand_features,
            cand_grade,
            cand_issues,
            repaired,
            _reason,
        ) = await api._score_directed_second_pass(
            title,
            body,
            domain,
            local_time,
            source_context=source_context,
            style_hint=style_hint,
            current_score=score,
            current_features=features,
            current_grade=grade,
            current_issues=deduped_issues,
            route=_route_task("second_pass"),
        )
        cand_issues = list(dict.fromkeys(issue for issue in cand_issues if issue))
        cand_blocking = bool(api._has_blocking_quality_issues(float(cand_score or 0.0), cand_issues, domain))
        issue_gain = api._score_gap_issue_count(deduped_issues) - api._score_gap_issue_count(cand_issues)
        score_preserved = float(cand_score or 0.0) >= float(score or 0.0) - 0.3
        if repaired and not cand_blocking and (score_preserved or issue_gain > 0):
            title, body, score, features, grade, deduped_issues, blocking = (
                cand_title,
                cand_body,
                cand_score,
                cand_features,
                cand_grade,
                cand_issues,
                cand_blocking,
            )
    if any("遗漏已提供动作" in issue for issue in deduped_issues) and hasattr(api, "_append_missing_fitness_source_actions"):
        patched_body = api._append_missing_fitness_source_actions(body, source_context)
        if patched_body and patched_body != body:
            body = patched_body
            score, features, grade = await api._score_generated_note(
                title,
                body,
                domain,
                local_time,
                timing=None,
                cover_feats=None,
            )
            issues = api._generated_quality_issues(title, body, domain, score, features)
            issues.extend(api._delivery_integrity_issues(f"{title}\n{body}", source_context, domain))
            issues.extend(api._body_format_issues(body))
            deduped_issues = list(dict.fromkeys(issue for issue in issues if issue))
            blocking = bool(api._has_blocking_quality_issues(float(score or 0.0), deduped_issues, domain))
    final_title = api._sanitize_title_for_delivery(title, source_context, domain)
    final_body = api._insert_safe_fact_line(body, domain, source_context)
    if final_title != title or final_body != body:
        title, body = final_title, final_body
        score, features, grade = await api._score_generated_note(
            title,
            body,
            domain,
            local_time,
            timing=None,
            cover_feats=None,
        )
        issues = api._generated_quality_issues(title, body, domain, score, features)
        issues.extend(api._delivery_integrity_issues(f"{title}\n{body}", source_context, domain))
        issues.extend(api._body_format_issues(body))
        deduped_issues = list(dict.fromkeys(issue for issue in issues if issue))
        blocking = bool(api._has_blocking_quality_issues(float(score or 0.0), deduped_issues, domain))
    return title, body, score, features, grade, deduped_issues, blocking


def feature_snapshot(features: dict[str, float]) -> dict[str, float]:
    keys = [
        "title_len",
        "body_len",
        "tag_count",
        "body_cta_count",
        "title_has_pos_emotion",
        "title_has_number",
        "title_has_city",
        "body_has_price",
        "body_has_address",
        "body_has_hours",
        "body_has_must_order",
        "body_has_transport",
        "plad_number_ratio",
        "plad_phrasal_repetition",
        "plad_sentence_burstiness",
        "semantic_emotional_intensity",
        "semantic_empathetic_engagement",
        "semantic_rhetorical_score",
    ]
    return {key: round(float(features[key]), 4) for key in keys if key in features}


def _existing_ready_artifacts(output_dir: Path, task_id: str) -> list[dict[str, Any]]:
    task_dir = output_dir / task_id
    if not task_dir.exists():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(task_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "ready" and data.get("score") is not None and not data.get("blocking"):
            artifacts.append(data)
    artifacts.sort(key=lambda item: float(item.get("score") or -1), reverse=True)
    return artifacts


async def generate_direct_slot(
    api: Any,
    row: dict[str, Any],
    payload: dict[str, Any],
    *,
    local_time: str,
) -> dict[str, Any]:
    domain = str(payload.get("domain") or row.get("domain") or "")
    route = str(payload.get("generation_route") or row.get("generation_route") or "")
    focus = _focus_text(payload, "prompt_focus") or str(row.get("prompt_focus", ""))
    system, user, source_context = build_generation_prompt(api, row, payload)
    raw = await api._mr.call(_route_task(route), system, user, thinking=False, max_tokens=3200)
    parsed = parse_note(raw) or api._extract_note_from_response(raw)
    if not parsed:
        raise ValueError("model_response_missing_note_xml")
    title, body = parsed
    title, body, score, features, grade, issues, blocking = await _postprocess_and_score(
        api,
        title,
        body,
        domain=domain,
        local_time=local_time,
        source_context=source_context,
        style_hint=focus,
    )
    return _ready_artifact(
        row,
        payload,
        raw_response=raw,
        title=title,
        body=body,
        score=score,
        features=features,
        grade=grade,
        issues=issues,
        blocking=blocking,
        source_context=source_context,
        generation_notes=[],
    )


async def generate_dependent_slot(
    api: Any,
    row: dict[str, Any],
    payload: dict[str, Any],
    *,
    output_dir: Path,
    local_time: str,
) -> dict[str, Any]:
    route = str(payload.get("generation_route") or row.get("generation_route") or "")
    task_id = str(payload.get("task_id") or row.get("task_id") or "")
    base = next((item for item in _existing_ready_artifacts(output_dir, task_id) if item.get("slot_id") != row.get("slot_id")), None)
    if not base:
        return _skip_artifact(row, payload, "dependent_route_needs_ready_base_artifact")

    domain = str(payload.get("domain") or row.get("domain") or "")
    focus = _focus_text(payload, "prompt_focus") or str(row.get("prompt_focus", ""))
    source_context = source_context_from_payload(payload)
    if route == "second_pass":
        (
            title,
            body,
            score,
            features,
            grade,
            issues,
            repaired,
            reason,
        ) = await api._score_directed_second_pass(
            str(base.get("title", "")),
            str(base.get("body", "")),
            domain,
            local_time,
            source_context=source_context,
            style_hint=focus or "交付质量二修",
            current_score=float(base.get("score")),
            current_features=base.get("features") or {},
            current_grade=str(base.get("grade", "")),
            current_issues=list(base.get("quality_issues") or []),
        )
        title, body, score, features, grade, issues, blocking = await _postprocess_and_score(
            api,
            title,
            body,
            domain=domain,
            local_time=local_time,
            source_context=source_context,
            style_hint=focus or "交付质量二修",
        )
        return _ready_artifact(
            row,
            payload,
            raw_response="",
            title=title,
            body=body,
            score=float(score or 0.0),
            features=features,
            grade=grade,
            issues=issues,
            blocking=blocking,
            source_context=source_context,
            generation_notes=[reason, f"base_slot={base.get('slot_id')}", f"repaired={repaired}"],
        )

    if route == "chat":
        system = (
            f"你是小红书{domain}内容对话优化助手。用户觉得当前稿有AI味，要求更自然但不丢失信息密度。"
            "只输出XML，不要解释。不得新增未提供的结构化事实。\n\n"
            f"{api._get_quality_contract(domain)}\n\n"
            f"{api._quality_expression_brief(domain)}\n\n"
            f"输出格式：<note><title>{api._TITLE_DELIVERY_MAX}字以内标题</title><body>完整正文，含话题标签</body></note>"
        )
        user = (
            f"用户要求：{focus or '更自然，更像真实用户写的'}\n"
            f"已核验事实：\n{source_context}\n\n"
            f"当前标题：{base.get('title', '')}\n"
            f"当前正文：\n{base.get('body', '')}\n\n"
            "请优化为更自然的一版，保留有用事实和标签。"
        )
        raw = await api._mr.call("chat", system, user, thinking=False, max_tokens=3000)
        parsed = parse_note(raw) or api._extract_note_from_response(raw)
        if not parsed:
            raise ValueError("chat_response_missing_note_xml")
        title, body = parsed
        title, body, score, features, grade, issues, blocking = await _postprocess_and_score(
            api,
            title,
            body,
            domain=domain,
            local_time=local_time,
            source_context=source_context,
            style_hint=focus or "对话优化",
        )
        base_score = float(base.get("score") or 0.0)
        if blocking or float(score or 0.0) < base_score - float(getattr(api, "_CHAT_MAX_ACCEPTABLE_SCORE_DROP", 2.0)):
            title, body, score, features, grade, issues, blocking = await _postprocess_and_score(
                api,
                str(base.get("title", "")),
                str(base.get("body", "")),
                domain=domain,
                local_time=local_time,
                source_context=source_context,
                style_hint=focus or "对话优化回退版本复核",
            )
            fallback_note = "chat_rewrite_rejected_score_drop_or_blocking"
        else:
            fallback_note = ""
        return _ready_artifact(
            row,
            payload,
            raw_response=raw,
            title=title,
            body=body,
            score=score,
            features=features,
            grade=grade,
            issues=issues,
            blocking=blocking,
            source_context=source_context,
            generation_notes=[item for item in [f"base_slot={base.get('slot_id')}", fallback_note] if item],
        )

    return _skip_artifact(row, payload, f"unsupported_dependent_route:{route}")


def _ready_artifact(
    row: dict[str, Any],
    payload: dict[str, Any],
    *,
    raw_response: str,
    title: str,
    body: str,
    score: float,
    features: dict[str, float],
    grade: str,
    issues: list[str],
    blocking: bool,
    source_context: str,
    generation_notes: list[str],
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "created_at": _now_iso(),
        "status": "blocked" if blocking else "ready",
        "queue_id": row.get("queue_id", ""),
        "task_id": payload.get("task_id") or row.get("task_id", ""),
        "slot_id": payload.get("slot_id") or row.get("slot_id", ""),
        "domain": payload.get("domain") or row.get("domain", ""),
        "origin": payload.get("origin") or row.get("origin", ""),
        "generation_route": payload.get("generation_route") or row.get("generation_route", ""),
        "prompt_focus": payload.get("prompt_focus", []),
        "quality_focus": payload.get("quality_focus", []),
        "user_intent": payload.get("user_intent", ""),
        "known_facts": payload.get("known_facts", []),
        "source_context": source_context,
        "title": title,
        "body": body,
        "score": round(float(score), 3),
        "legacy_reference_score": LEGACY_REFERENCE_SCORE,
        "grade": grade,
        "blocking": blocking,
        "quality_issues": issues,
        "feature_snapshot": feature_snapshot(features),
        "features": {key: float(value) for key, value in features.items()},
        "raw_response": raw_response,
        "generation_notes": generation_notes,
    }


def _skip_artifact(row: dict[str, Any], payload: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "version": VERSION,
        "created_at": _now_iso(),
        "status": "skipped",
        "queue_id": row.get("queue_id", ""),
        "task_id": payload.get("task_id") or row.get("task_id", ""),
        "slot_id": payload.get("slot_id") or row.get("slot_id", ""),
        "domain": payload.get("domain") or row.get("domain", ""),
        "origin": payload.get("origin") or row.get("origin", ""),
        "generation_route": payload.get("generation_route") or row.get("generation_route", ""),
        "reason": reason,
    }


def _failure_artifact(row: dict[str, Any], payload: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "version": VERSION,
        "created_at": _now_iso(),
        "status": "failed",
        "queue_id": row.get("queue_id", ""),
        "task_id": payload.get("task_id") or row.get("task_id", ""),
        "slot_id": payload.get("slot_id") or row.get("slot_id", ""),
        "domain": payload.get("domain") or row.get("domain", ""),
        "origin": payload.get("origin") or row.get("origin", ""),
        "generation_route": payload.get("generation_route") or row.get("generation_route", ""),
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
    }


async def fill_rows(
    rows: list[dict[str, Any]],
    *,
    output_dir: Path,
    overwrite: bool = False,
    local_time: str = LOCAL_TIME_DEFAULT,
) -> list[dict[str, Any]]:
    api = load_api_module()
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        payload = generation_payload(row)
        path = artifact_path(output_dir, row)
        if path.exists() and not overwrite:
            existing = json.loads(path.read_text(encoding="utf-8"))
            results.append({"status": "existing", "path": str(path), "artifact": existing})
            continue
        try:
            route = str(payload.get("generation_route") or row.get("generation_route") or "")
            if route in DIRECT_ROUTES:
                artifact = await generate_direct_slot(api, row, payload, local_time=local_time)
            elif route in DEPENDENT_ROUTES:
                artifact = await generate_dependent_slot(api, row, payload, output_dir=output_dir, local_time=local_time)
            else:
                artifact = _skip_artifact(row, payload, f"unsupported_or_manual_route:{route}")
            _write_json(path, artifact)
            results.append({"status": artifact.get("status", ""), "path": str(path), "artifact": artifact})
            print(
                f"[{index}/{len(rows)}] {artifact.get('status')} {artifact.get('domain')} "
                f"{artifact.get('slot_id')} score={artifact.get('score', '-')}",
                flush=True,
            )
        except Exception as exc:
            artifact = _failure_artifact(row, payload, exc)
            _write_json(path, artifact)
            results.append({"status": "failed", "path": str(path), "artifact": artifact})
            print(f"[{index}/{len(rows)}] failed {row.get('queue_id')}: {exc}", file=sys.stderr, flush=True)
    return results


def build_run_report(
    *,
    queue_path: Path,
    output_dir: Path,
    selected: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    results: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    ready_artifacts = [
        item["artifact"]
        for item in results
        if item.get("artifact", {}).get("status") == "ready"
        and not item.get("artifact", {}).get("blocking")
        and item.get("artifact", {}).get("score") is not None
    ]
    blocked_artifacts = [
        item["artifact"]
        for item in results
        if item.get("artifact", {}).get("status") == "blocked" or item.get("artifact", {}).get("blocking")
    ]
    scores = [float(item["score"]) for item in ready_artifacts]
    by_status: dict[str, int] = {}
    for item in results:
        status = str(item.get("status") or item.get("artifact", {}).get("status", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
    for item in skipped:
        status = str(item.get("status", "skipped"))
        by_status[status] = by_status.get(status, 0) + 1

    by_domain: dict[str, dict[str, int]] = {}
    for artifact in [item.get("artifact", item) for item in results] + skipped:
        domain = str(artifact.get("domain", ""))
        status = str(artifact.get("status", "unknown"))
        by_domain.setdefault(domain, {})
        by_domain[domain][status] = by_domain[domain].get(status, 0) + 1

    return {
        "version": VERSION,
        "created_at": _now_iso(),
        "dry_run": dry_run,
        "queue_path": str(queue_path),
        "output_dir": str(output_dir),
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "result_count": len(results),
        "by_status": dict(sorted(by_status.items())),
        "by_domain_status": {domain: dict(sorted(counts.items())) for domain, counts in sorted(by_domain.items())},
        "score_summary": {
            "count": len(scores),
            "min": round(min(scores), 3) if scores else None,
            "max": round(max(scores), 3) if scores else None,
            "mean": round(statistics.mean(scores), 3) if scores else None,
            "median": round(statistics.median(scores), 3) if scores else None,
            "ready_ge_60": sum(1 for score in scores if score >= 60),
            "legacy_score_ge_reference": sum(1 for score in scores if score >= LEGACY_REFERENCE_SCORE),
            "blocked_count": len(blocked_artifacts),
        },
        "ready_outputs": [
            {
                "path": item["path"],
                "task_id": item["artifact"].get("task_id", ""),
                "slot_id": item["artifact"].get("slot_id", ""),
                "domain": item["artifact"].get("domain", ""),
                "title": item["artifact"].get("title", ""),
                "score": item["artifact"].get("score"),
                "blocking": item["artifact"].get("blocking"),
            }
            for item in results
            if item.get("artifact", {}).get("status") == "ready"
            and not item.get("artifact", {}).get("blocking")
        ],
        "blocked_outputs": [
            {
                "path": item["path"],
                "task_id": item["artifact"].get("task_id", ""),
                "slot_id": item["artifact"].get("slot_id", ""),
                "domain": item["artifact"].get("domain", ""),
                "title": item["artifact"].get("title", ""),
                "score": item["artifact"].get("score"),
                "issues": (item["artifact"].get("quality_issues") or [])[:8],
            }
            for item in results
            if item.get("artifact", {}).get("status") == "blocked" or item.get("artifact", {}).get("blocking")
        ],
        "failures": [
            {
                "path": item["path"],
                "task_id": item["artifact"].get("task_id", ""),
                "slot_id": item["artifact"].get("slot_id", ""),
                "error": item["artifact"].get("error", ""),
            }
            for item in results
            if item.get("artifact", {}).get("status") == "failed"
        ],
        "skipped": skipped[:200],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--domains", default="", help="Comma-separated domain filter, e.g. 美食,旅行")
    parser.add_argument("--routes", default="", help="Comma-separated generation_route filter")
    parser.add_argument("--origins", default="", help="Comma-separated origin filter")
    parser.add_argument("--task-ids", default="", help="Comma-separated task_id filter")
    parser.add_argument("--slot-ids", default="", help="Comma-separated slot_id filter")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to execute after filters; 0 means no limit")
    parser.add_argument("--include-dependent", action="store_true", help="Enable chat/second_pass slots when base artifacts exist")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--local-time", default=LOCAL_TIME_DEFAULT)
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    queue_path = args.queue if args.queue.is_absolute() else ROOT / args.queue
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    rows = _load_jsonl(queue_path)
    selected, skipped = select_rows(
        rows,
        domains=_split_csv_arg(args.domains),
        routes=_split_csv_arg(args.routes),
        origins=_split_csv_arg(args.origins),
        task_ids=_split_csv_arg(args.task_ids),
        slot_ids=_split_csv_arg(args.slot_ids),
        include_dependent=bool(args.include_dependent),
        output_dir=output_dir,
        overwrite=bool(args.overwrite),
        limit=args.limit or None,
    )

    if args.dry_run:
        results: list[dict[str, Any]] = []
    else:
        results = await fill_rows(
            selected,
            output_dir=output_dir,
            overwrite=bool(args.overwrite),
            local_time=args.local_time,
        )

    report = build_run_report(
        queue_path=queue_path,
        output_dir=output_dir,
        selected=selected,
        skipped=skipped,
        results=results,
        dry_run=bool(args.dry_run),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_name = f"run_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json(output_dir / report_name, report)
    _write_json(output_dir / "latest_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
