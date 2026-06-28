#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Feature builder for v0.4-composite delivery quality models.

The 62 v0.4 interaction features remain useful input signals, but the
composite model also needs features that describe commercial delivery value:
natural title readability, domain-specific factual coverage, actionability,
template risk and reader decision value.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from feature_extraction import extract_features
from naturalness import score_naturalness
from rednote_vibe_v04 import MODEL_FEATURE_COLS_V04, VISUAL_FEATURE_COLS
from v04_domain_policy import canonical_product_domain

PRICE_RE = re.compile(r"(?:人均|预算|总花费|价格|费用|¥|￥)?\s*\d+(?:\.\d+)?\s*(?:元|块|rmb|RMB|k|K)")
TIME_RE = re.compile(r"\d{1,2}[:：]\d{2}|\d{1,2}\s*(?:点|:)\s*(?:半)?|周[一二三四五六日末天]|营业时间")
NUMBER_RE = re.compile(r"\d+")
HASHTAG_RE = re.compile(r"#([^#\s]+)")
SENTENCE_RE = re.compile(r"[。！？!?；;\n]+")

LOW_QUALITY_PHRASES = (
    "绝了",
    "天花板",
    "闭眼冲",
    "值哭",
    "封神",
    "狠狠爱",
    "谁懂",
    "不允许还有人不知道",
    "直接冲",
    "爆哭",
    "太香了",
)

TEMPLATE_MARKERS = (
    "姐妹们",
    "家人们",
    "真的不是广告",
    "听我的",
    "冲就完事了",
    "不踩雷",
    "码住",
    "我宣布",
    "这谁顶得住",
)

POSITIVE_RECOMMENDATION_WORDS = ("推荐", "值得", "很稳", "适合", "必点", "必吃", "招牌", "亲测")
CTA_WORDS = ("点赞", "收藏", "评论", "私信", "关注", "留言", "码住")
FIRST_PERSON_WORDS = ("我", "我们", "这次", "这家", "这套", "用下来", "试下来", "去之前", "下单前")

DOMAIN_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "美食": {
        "price": ("人均", "价格", "套餐", "元", "¥", "￥"),
        "address": ("地址", "位于", "路", "街", "号", "楼", "商场", "地铁", "停车", "导航", "商圈"),
        "hours": ("营业", "营业时间", "周一", "周二", "周三", "周四", "周五", "周六", "周日", "午市", "晚市"),
        "must_order": ("必点", "必吃", "招牌", "推荐", "人气", "主推", "镇店", "点单"),
        "booking": ("预订", "预约", "排队", "等位", "订位", "叫号"),
        "taste": ("口感", "火候", "鲜", "嫩", "香", "脆", "弹", "甜", "咸", "分量"),
    },
    "旅行": {
        "budget": ("预算", "花费", "人均", "门票", "酒店", "住宿", "机票", "高铁"),
        "transport": (
            "交通", "高铁", "飞机", "自驾", "地铁", "公交", "打车", "步行", "骑行", "电动车", "包车",
            "开车", "车程", "车站", "机场", "码头", "返程", "出发", "往返", "接送", "班车", "距离",
            "靠近", "近", "沙滩", "公共沙滩", "私家沙滩",
        ),
        "route": ("路线", "行程", "第一天", "第二天", "Day", "day", "打卡", "景点"),
        "avoid": ("避坑", "注意", "不适合", "建议", "提前", "别"),
        "season": ("季节", "天气", "夏天", "冬天", "春天", "秋天", "最佳时间"),
    },
    "穿搭": {
        "fit": ("小个子", "梨形", "苹果型", "通勤", "约会", "显高", "显瘦", "身材", "场合"),
        "items": ("上衣", "裤", "裙", "外套", "鞋", "包", "衬衫", "牛仔", "半裙"),
        "logic": ("比例", "颜色", "同色系", "腰线", "叠穿", "材质", "版型"),
        "price": ("价格", "预算", "元", "平替", "链接", "淘宝", "优衣库"),
    },
    "美妆": {
        "skin": ("干皮", "油皮", "混皮", "敏感肌", "黄皮", "冷白皮", "肤质", "肤色"),
        "product": ("粉底", "腮红", "口红", "散粉", "眼影", "色号", "质地", "产品"),
        "effect": ("妆效", "持妆", "显白", "遮瑕", "服帖", "不浮粉", "上脸", "用量"),
        "price": ("价格", "元", "平替", "大牌", "性价比"),
    },
    "家居": {
        "space": ("㎡", "平", "户型", "出租屋", "卧室", "客厅", "厨房", "收纳", "动线"),
        "budget": ("预算", "花费", "元", "清单", "价格"),
        "items": ("柜", "架", "灯", "桌", "椅", "床", "窗帘", "地毯", "宜家", "淘宝"),
        "before_after": ("改造前", "改造后", "以前", "现在", "对比", "痛点"),
    },
    "健身": {
        "action": ("深蹲", "卷腹", "平板支撑", "开合跳", "俯卧撑", "臀桥", "拉伸", "动作"),
        "dosage": ("组", "次", "分钟", "秒", "频率", "每天", "每周", "坚持"),
        "target": ("减脂", "腰腹", "臀", "腿", "全身", "马甲线", "核心", "体态"),
        "safety": ("新手", "注意", "膝盖", "腰", "疼", "热身", "拉伸", "不要"),
    },
    "母婴": {
        "age": ("月龄", "个月", "岁", "宝宝", "婴儿", "幼儿"),
        "safety": ("安全", "过敏", "无添加", "注意", "医生", "辅食", "剂量", "看护", "成人", "哭闹", "不承诺"),
        "steps": ("步骤", "第一", "第二", "准备", "搅拌", "蒸", "煮", "观察", "流程", "顺序", "信号"),
        "materials": (
            "食材", "米粉", "南瓜", "鸡蛋", "奶", "餐具", "成分",
            "睡袋", "绘本", "夜灯", "白噪音", "抚触", "安抚", "牙胶", "玩具",
        ),
    },
}


BUSINESS_FEATURE_COLS = [
    "commercial_title_char_len",
    "commercial_title_in_delivery_range",
    "commercial_title_has_number",
    "commercial_title_has_recommendation",
    "commercial_title_has_domain_anchor",
    "commercial_title_unreadable_risk",
    "commercial_title_price_recommendation_join",
    "commercial_title_template_phrase_count",
    "commercial_body_char_len",
    "commercial_body_main_char_len",
    "commercial_body_paragraph_count",
    "commercial_body_sentence_count",
    "commercial_body_avg_sentence_len",
    "commercial_body_sentence_burstiness",
    "commercial_body_tag_count",
    "commercial_body_has_cta",
    "commercial_body_cta_count",
    "commercial_body_has_first_person",
    "commercial_body_template_phrase_count",
    "commercial_body_low_quality_phrase_count",
    "commercial_body_specific_number_count",
    "commercial_body_price_mentions",
    "commercial_fact_density",
    "commercial_actionability",
    "commercial_specificity",
    "commercial_naturalness_available",
    "commercial_naturalness_score",
    "commercial_ai_probability",
    "commercial_domain_slot_coverage",
    "commercial_domain_slot_count",
    "commercial_domain_missing_slot_count",
    "domain_food_price",
    "domain_food_address",
    "domain_food_hours",
    "domain_food_must_order",
    "domain_food_booking",
    "domain_food_taste_evidence",
    "domain_travel_budget",
    "domain_travel_transport",
    "domain_travel_route",
    "domain_travel_avoid",
    "domain_travel_season",
    "domain_fashion_fit",
    "domain_fashion_items",
    "domain_fashion_logic",
    "domain_fashion_price",
    "domain_beauty_skin",
    "domain_beauty_product",
    "domain_beauty_effect",
    "domain_beauty_price",
    "domain_home_space",
    "domain_home_budget",
    "domain_home_items",
    "domain_home_before_after",
    "domain_fitness_action",
    "domain_fitness_dosage",
    "domain_fitness_target",
    "domain_fitness_safety",
    "domain_baby_age",
    "domain_baby_safety",
    "domain_baby_steps",
    "domain_baby_materials",
]

COMPOSITE_FEATURE_COLS = list(MODEL_FEATURE_COLS_V04) + BUSINESS_FEATURE_COLS


def canonical_domain(domain: str | None) -> str:
    return canonical_product_domain(domain)


def strip_tags(body: str) -> str:
    return re.sub(r"#([^#\s]+)(?:\[话题\])?#?", "", body or "").strip()


def _has_any(text: str, words: tuple[str, ...]) -> int:
    return int(any(word in text for word in words))


def _count_any(text: str, words: tuple[str, ...]) -> int:
    return sum(text.count(word) for word in words if word)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.split(text or "") if s.strip()]


def _burstiness(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean <= 0:
        return 0.0
    return float(math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / mean)


def _keyword_density(text: str, keywords: tuple[str, ...]) -> float:
    if not text:
        return 0.0
    return min(1.0, _count_any(text, keywords) / max(1.0, len(text) / 120.0))


def _title_unreadable_risk(title: str) -> int:
    title = (title or "").strip()
    if not title:
        return 1
    if len(title) > 18:
        return 1
    if re.search(r"\d+\s*(?:元|块).{0,4}(?:值得点|值得|推荐|必点)$", title):
        return 1
    if re.search(r"[｜|/、]\s*(?:这家|这个|这些|值得|必点|推荐)$", title):
        return 1
    if re.search(r"(?:软颗粒安|计$|的$|了$|这家$|这个$)", title):
        return 1
    return 0


def _domain_anchor(title: str, body: str, domain: str) -> int:
    text = f"{title}\n{body}"
    slots = DOMAIN_KEYWORDS.get(domain, {})
    if not slots:
        return int(bool(title.strip()))
    return int(any(_has_any(text, words) for words in slots.values()))


def _fact_density_parts(
    *,
    main_body: str,
    domain: str,
    number_count: int,
    price_count: int,
    domain_slot_coverage: float,
) -> list[float]:
    """Domain-aware factual density signals.

    Price is a real delivery fact for restaurant, travel, fashion, beauty and
    home content. It is not a required fact for parenting routines or workout
    plans, where safety boundaries and executable steps carry the value.
    """
    if domain == "母婴":
        return [
            float(bool(number_count)),
            float(domain_slot_coverage),
            float(_has_any(main_body, ("流程", "顺序", "步骤", "观察", "困信号", "准备", "材料", "用品"))),
            float(_has_any(main_body, ("安全", "注意", "不适合", "不要", "不承诺", "哭闹", "安抚", "看护"))),
        ]
    if domain == "健身":
        return [
            float(bool(number_count)),
            float(domain_slot_coverage),
            float(_has_any(main_body, ("动作", "组", "次", "分钟", "秒", "轮", "热身", "拉伸"))),
            float(_has_any(main_body, ("注意", "不适", "疼", "替代", "减少", "低冲击", "膝盖", "休息"))),
        ]
    return [
        float(bool(number_count)),
        float(bool(price_count)),
        float(domain_slot_coverage),
        float(_has_any(main_body, ("地址", "路线", "步骤", "清单", "注意", "适合", "不适合"))),
    ]


def _specificity_parts(
    *,
    main_body: str,
    domain: str,
    number_count: int,
    price_count: int,
    tag_count: int,
) -> list[float]:
    if domain == "母婴":
        return [
            min(1.0, number_count / 4.0),
            min(1.0, tag_count / 6.0),
            float(_has_any(main_body, ("月龄", "个月", "流程", "顺序", "睡袋", "绘本", "白噪音", "牙胶", "餐具"))),
            float(_has_any(main_body, ("观察", "困信号", "哭闹", "安抚", "安全", "注意", "不承诺", "看护"))),
        ]
    if domain == "健身":
        return [
            min(1.0, number_count / 4.0),
            min(1.0, tag_count / 6.0),
            float(_has_any(main_body, ("动作", "组", "次", "秒", "分钟", "轮", "热身", "拉伸"))),
            float(_has_any(main_body, ("低冲击", "膝盖", "替代", "休息", "不适", "疼", "不要", "注意"))),
        ]
    return [
        min(1.0, number_count / 4.0),
        min(1.0, price_count / 2.0),
        min(1.0, tag_count / 6.0),
        float(_has_any(main_body, FIRST_PERSON_WORDS)),
    ]


def _domain_slot_features(text: str, domain: str) -> dict[str, float]:
    out = {col: 0.0 for col in BUSINESS_FEATURE_COLS if col.startswith("domain_")}
    prefixes = {
        "美食": "domain_food",
        "旅行": "domain_travel",
        "穿搭": "domain_fashion",
        "美妆": "domain_beauty",
        "家居": "domain_home",
        "健身": "domain_fitness",
        "母婴": "domain_baby",
    }
    slot_map = DOMAIN_KEYWORDS.get(domain, {})
    prefix = prefixes.get(domain)
    hit_count = 0
    if prefix:
        for slot, words in slot_map.items():
            col = f"{prefix}_{slot}"
            hit = float(_has_any(text, words))
            if col in out:
                out[col] = hit
            hit_count += int(hit)
    total = len(slot_map)
    out["commercial_domain_slot_count"] = float(hit_count)
    out["commercial_domain_missing_slot_count"] = float(max(0, total - hit_count))
    out["commercial_domain_slot_coverage"] = float(hit_count / total) if total else 0.0
    return out


def build_composite_features(
    *,
    title: str,
    body: str,
    domain: str | None = "",
    local_time: str | None = "2026062412",
    include_naturalness: bool = True,
) -> dict[str, float]:
    """Return a stable feature vector for a generated or human note."""
    title = title or ""
    body = body or ""
    domain = canonical_domain(domain)
    main_body = strip_tags(body)
    full_text = f"{title}\n{main_body}"

    base = extract_features(
        {
            "note_title": title,
            "desc": body,
            "domain": domain,
            "local_time": local_time or "2026062412",
        }
    )
    feats: dict[str, float] = {
        col: float(base.get(col, 0.0) or 0.0)
        for col in MODEL_FEATURE_COLS_V04
        if col not in VISUAL_FEATURE_COLS
    }
    for col in VISUAL_FEATURE_COLS:
        feats[col] = 0.0
    for col in MODEL_FEATURE_COLS_V04:
        feats.setdefault(col, 0.0)

    sentences = _sentences(main_body)
    sentence_lens = [len(s) for s in sentences]
    tag_count = len(HASHTAG_RE.findall(body))
    number_count = len(NUMBER_RE.findall(main_body))
    price_count = len(PRICE_RE.findall(main_body))
    cta_count = _count_any(main_body, CTA_WORDS)
    low_quality_count = _count_any(full_text, LOW_QUALITY_PHRASES)
    template_count = _count_any(full_text, TEMPLATE_MARKERS)

    nat = {"available": 0.0, "ai_probability": 0.0, "naturalness_score": 50.0}
    if include_naturalness:
        try:
            nat = score_naturalness(title, body, domain)
        except Exception:
            nat = {"available": 0.0, "ai_probability": 0.0, "naturalness_score": 50.0}

    domain_feats = _domain_slot_features(full_text, domain)
    fact_density_parts = _fact_density_parts(
        main_body=main_body,
        domain=domain,
        number_count=number_count,
        price_count=price_count,
        domain_slot_coverage=domain_feats.get("commercial_domain_slot_coverage", 0.0),
    )
    action_parts = [
        float(cta_count > 0),
        float(_has_any(main_body, CTA_WORDS)),
        float(_has_any(main_body, ("建议", "提前", "下单前", "出门前", "收藏", "可以", "适合"))),
        domain_feats.get("commercial_domain_slot_coverage", 0.0),
    ]
    specificity_parts = _specificity_parts(
        main_body=main_body,
        domain=domain,
        number_count=number_count,
        price_count=price_count,
        tag_count=tag_count,
    )

    commercial = {
        "commercial_title_char_len": float(len(title)),
        "commercial_title_in_delivery_range": float(8 <= len(title) <= 18),
        "commercial_title_has_number": float(bool(NUMBER_RE.search(title))),
        "commercial_title_has_recommendation": float(_has_any(title, POSITIVE_RECOMMENDATION_WORDS)),
        "commercial_title_has_domain_anchor": float(_domain_anchor(title, body, domain)),
        "commercial_title_unreadable_risk": float(_title_unreadable_risk(title)),
        "commercial_title_price_recommendation_join": float(bool(re.search(r"\d+\s*(?:元|块).{0,4}(?:值得|推荐|必点|冲|点)$", title))),
        "commercial_title_template_phrase_count": float(_count_any(title, LOW_QUALITY_PHRASES + TEMPLATE_MARKERS)),
        "commercial_body_char_len": float(len(body)),
        "commercial_body_main_char_len": float(len(main_body)),
        "commercial_body_paragraph_count": float(len([p for p in re.split(r"\n+", main_body) if p.strip()])),
        "commercial_body_sentence_count": float(len(sentences)),
        "commercial_body_avg_sentence_len": float(sum(sentence_lens) / len(sentence_lens)) if sentence_lens else 0.0,
        "commercial_body_sentence_burstiness": _burstiness(sentence_lens),
        "commercial_body_tag_count": float(tag_count),
        "commercial_body_has_cta": float(cta_count > 0),
        "commercial_body_cta_count": float(cta_count),
        "commercial_body_has_first_person": float(_has_any(main_body, FIRST_PERSON_WORDS)),
        "commercial_body_template_phrase_count": float(template_count),
        "commercial_body_low_quality_phrase_count": float(low_quality_count),
        "commercial_body_specific_number_count": float(number_count),
        "commercial_body_price_mentions": float(price_count),
        "commercial_fact_density": float(sum(fact_density_parts) / len(fact_density_parts)),
        "commercial_actionability": float(sum(action_parts) / len(action_parts)),
        "commercial_specificity": float(sum(specificity_parts) / len(specificity_parts)),
        "commercial_naturalness_available": float(nat.get("available", 0.0) or 0.0),
        "commercial_naturalness_score": float(nat.get("naturalness_score", 50.0) or 0.0),
        "commercial_ai_probability": float(nat.get("ai_probability", 0.0) or 0.0),
    }
    feats.update(commercial)
    feats.update(domain_feats)

    # Keep the contract stable even when a future feature branch changes logic.
    for col in COMPOSITE_FEATURE_COLS:
        feats[col] = float(feats.get(col, 0.0) or 0.0)
    return {col: feats[col] for col in COMPOSITE_FEATURE_COLS}


def feature_summary(features: dict[str, float], top_n: int = 12) -> dict[str, float]:
    """Small debug helper for reports/tests."""
    interesting = {
        k: v
        for k, v in features.items()
        if k.startswith("commercial_") or k.startswith("domain_")
    }
    return dict(Counter(interesting).most_common(top_n))
