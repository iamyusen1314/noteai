#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Product-facing domain policy for v0.4-composite quality training."""

from __future__ import annotations

from collections.abc import Iterable


CORE_PRODUCT_DOMAINS = ("美食", "旅行", "穿搭", "美妆", "家居", "健身", "母婴")

PRODUCT_DOMAIN_ALIASES = {
    "": "其他",
    "unknown": "其他",
    "Unknown": "其他",
    "others": "其他",
    "Others": "其他",
    "Food": "美食",
    "food": "美食",
    "餐饮": "美食",
    "食品": "美食",
    "Travel": "旅行",
    "travel": "旅行",
    "旅游": "旅行",
    "Fashion": "穿搭",
    "fashion": "穿搭",
    "时尚": "穿搭",
    "Beauty": "美妆",
    "beauty": "美妆",
    "Home": "家居",
    "home": "家居",
    "家装": "家居",
    "家居家装": "家居",
    "Sports": "健身",
    "sports": "健身",
    "运动": "健身",
    "运动健身": "健身",
    "健身": "健身",
    "Baby": "母婴",
    "baby": "母婴",
    "亲子": "母婴",
    "育儿": "母婴",
    "母婴": "母婴",
    "Health": "健康",
    "health": "健康",
    "Career": "职场",
    "career": "职场",
    "Pets": "宠物",
    "pets": "宠物",
    "Education": "学习",
    "education": "学习",
    "Relation.": "情感",
    "Relationship": "情感",
    "relationships": "情感",
    "Wellness": "心理",
    "wellness": "心理",
}


def canonical_product_domain(value: object) -> str:
    text = str(value or "").strip()
    return PRODUCT_DOMAIN_ALIASES.get(text, text or "其他")


def canonical_product_domains(values: Iterable[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        domain = canonical_product_domain(value)
        if domain not in seen:
            out.append(domain)
            seen.add(domain)
    return out
