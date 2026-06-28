#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Text naturalness / AI-smell feature extraction."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

import jieba

from feature_extraction import FEATURE_COLS, extract_features


BASE_NATURALNESS_FEATURES = [
    c
    for c in FEATURE_COLS
    if c
    not in {
        "time_hour",
        "time_weekday",
        "time_is_weekend",
        "time_days_to_holiday",
        "domain_encoded",
    }
]

AI_TRANSITIONS = [
    "首先",
    "其次",
    "最后",
    "总之",
    "综上",
    "此外",
    "另外",
    "需要注意",
    "值得注意",
    "以下是",
    "总结一下",
    "核心是",
    "关键在于",
]

PERSONAL_WORDS = ["我", "我们", "自己", "朋友", "家里", "这次", "上次", "第一次", "最近"]
READER_WORDS = ["你", "你们", "大家", "姐妹", "宝子", "新手", "打工人", "学生党", "妈妈", "情侣"]
SENSORY_WORDS = [
    "香",
    "脆",
    "软",
    "嫩",
    "烫",
    "甜",
    "酸",
    "辣",
    "鲜",
    "滑",
    "糯",
    "清爽",
    "厚实",
    "细腻",
    "蓬松",
    "舒服",
    "扎实",
]
GENERIC_PRAISE = ["很好", "不错", "推荐", "值得", "喜欢", "好看", "好吃", "舒服", "方便", "实用"]
LOW_INFO_PHRASES = ["真的", "非常", "特别", "超级", "很适合", "强烈推荐", "闭眼入", "绝了", "宝藏"]
AI_DISCLAIMERS = ["作为AI", "无法", "不能保证", "仅供参考", "根据你的需求", "希望这些建议"]

LIST_MARKER_RE = re.compile(r"(^|\n)\s*(?:\d+[.、)]|[一二三四五六七八九十]+[、.]|[✅✔️•\-])")
SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]+",
    flags=re.UNICODE,
)


def _count_any(text: str, words: list[str]) -> int:
    return sum(text.count(w) for w in words)


def _ratio(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _cv(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    return float((sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5 / mean)


def _entropy(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    return float(-sum((count / total) * math.log2(count / total) for count in counts.values()))


EXTRA_NATURALNESS_FEATURES = [
    "text_char_len",
    "title_body_ratio",
    "line_count",
    "paragraph_count",
    "avg_line_len",
    "line_len_cv",
    "sentence_count_naturalness",
    "sentence_len_cv_naturalness",
    "duplicate_sentence_ratio",
    "list_marker_count",
    "list_marker_ratio",
    "colon_line_ratio",
    "ai_transition_count",
    "ai_transition_density",
    "ai_disclaimer_count",
    "personal_word_count",
    "reader_word_count",
    "personal_reader_ratio",
    "sensory_word_count",
    "sensory_density",
    "generic_praise_count",
    "low_info_phrase_count",
    "question_count",
    "exclamation_count",
    "hashtag_density",
    "emoji_count_naturalness",
    "emoji_density_naturalness",
    "token_entropy_naturalness",
    "token_ttr_naturalness",
]

NATURALNESS_FEATURE_COLS = BASE_NATURALNESS_FEATURES + EXTRA_NATURALNESS_FEATURES


def extract_naturalness_features(title: str, body: str, domain: str = "") -> dict[str, float]:
    title = str(title or "").strip()
    body = str(body or "").strip()
    text = f"{title}\n{body}".strip()

    base = extract_features(
        {
            "note_title": title,
            "desc": body,
            "local_time": "2024010112",
            "domain": domain,
        }
    )
    out: dict[str, float] = {col: float(base.get(col, 0.0) or 0.0) for col in BASE_NATURALNESS_FEATURES}

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    paragraphs = [seg.strip() for seg in re.split(r"\n{2,}", body) if seg.strip()]
    sentences = [seg.strip() for seg in SENTENCE_SPLIT_RE.split(body) if seg.strip()]
    line_lens = [len(line) for line in lines]
    sentence_lens = [len(sentence) for sentence in sentences]
    sentence_counts = Counter(sentences)
    duplicate_sentences = sum(count - 1 for count in sentence_counts.values() if count > 1)
    tokens = [tok.strip() for tok in jieba.cut(text) if len(tok.strip()) > 1]
    char_len = len(text)
    hashtag_count = len(re.findall(r"#([^#\[\]]+?)(?:\[话题\])?#", body))
    emoji_count = len("".join(EMOJI_RE.findall(text)))
    list_markers = len(LIST_MARKER_RE.findall(body))
    colon_lines = sum(1 for line in lines if "：" in line or ":" in line)
    personal = _count_any(text, PERSONAL_WORDS)
    reader = _count_any(text, READER_WORDS)
    sensory = _count_any(text, SENSORY_WORDS)

    extras = {
        "text_char_len": char_len,
        "title_body_ratio": _ratio(len(title), max(len(body), 1)),
        "line_count": len(lines),
        "paragraph_count": len(paragraphs),
        "avg_line_len": sum(line_lens) / len(line_lens) if line_lens else 0.0,
        "line_len_cv": _cv(line_lens),
        "sentence_count_naturalness": len(sentences),
        "sentence_len_cv_naturalness": _cv(sentence_lens),
        "duplicate_sentence_ratio": _ratio(duplicate_sentences, len(sentences)),
        "list_marker_count": list_markers,
        "list_marker_ratio": _ratio(list_markers, len(lines)),
        "colon_line_ratio": _ratio(colon_lines, len(lines)),
        "ai_transition_count": _count_any(text, AI_TRANSITIONS),
        "ai_transition_density": _ratio(_count_any(text, AI_TRANSITIONS), char_len),
        "ai_disclaimer_count": _count_any(text, AI_DISCLAIMERS),
        "personal_word_count": personal,
        "reader_word_count": reader,
        "personal_reader_ratio": _ratio(personal + reader, char_len),
        "sensory_word_count": sensory,
        "sensory_density": _ratio(sensory, char_len),
        "generic_praise_count": _count_any(text, GENERIC_PRAISE),
        "low_info_phrase_count": _count_any(text, LOW_INFO_PHRASES),
        "question_count": text.count("?") + text.count("？"),
        "exclamation_count": text.count("!") + text.count("！"),
        "hashtag_density": _ratio(hashtag_count, char_len),
        "emoji_count_naturalness": emoji_count,
        "emoji_density_naturalness": _ratio(emoji_count, char_len),
        "token_entropy_naturalness": _entropy(tokens),
        "token_ttr_naturalness": _ratio(len(set(tokens)), len(tokens)),
    }
    out.update({col: float(extras.get(col, 0.0) or 0.0) for col in EXTRA_NATURALNESS_FEATURES})
    return out
