"""
NoteAI Pro — Feature Extraction Pipeline (v0.2)
Target: 37 content features from RedNote-Vibe exploring_set.jsonl
Features derived from: note_title, desc, local_time, domain, liked_count, collected_count, comments_count
PLAD features expanded from 4 to 13 based on RedNote-Vibe paper (2509.22055v2) Table 2.
"""

import json
import re
import math
import warnings
from collections import Counter
from datetime import datetime
from pathlib import Path

import jieba
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Keyword dictionaries ──────────────────────────────────────────

POS_EMOTION = [
    "好吃", "推荐", "喜欢", "爱", "必去", "超棒", "绝了", "惊喜", "好玩",
    "美味", "开心", "幸福", "治愈", "满足", "温柔", "可爱", "贴心", "用心",
    "值得", "值得试", "值得冲", "安心", "舒适", "温暖", "快乐", "感动", "赞", "棒", "nice",
    "必点", "必吃", "招牌", "很稳", "省心", "适合",
]
NEG_EMOTION = [
    "避雷", "踩雷", "差评", "失望", "后悔", "难吃", "难用", "贵", "坑",
    "骗", "假", "黑心", "差劲", "糟糕", "恶心", "呕", "垃圾",
]
PRICE_WORDS = ["元", "¥", "￥", "块", "价格", "人均", "费用", "优惠", "折扣", "券"]
NEW_SIGNAL = ["新开", "刚开", "首店", "试营业", "新品", "上新", "新款", "首发"]
CTA_WORDS = ["关注", "点赞", "收藏", "转发", "评论", "私信", "记得", "别忘了", "快来", "冲"]
ADDRESS_WORDS = [
    "地址", "位于", "路", "街", "号", "楼", "座", "区", "镇", "市",
    "商圈", "广场", "附近", "地铁", "万博",
]
HOURS_WORDS = ["营业", "开放", "几点", "时间", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
TRANSPORT_WORDS = [
    "地铁", "公交", "步行", "打车", "骑行", "导航", "出口", "站", "高铁", "飞机", "自驾", "电动车",
    "包车", "开车", "车程", "车站", "机场", "码头", "返程", "出发", "往返", "接送", "班车", "距离",
    "靠近", "沙滩",
]
BOOKING_WORDS = ["预约", "预订", "订位", "排队", "等位", "叫号"]
MUST_ORDER = ["必点", "必吃", "招牌", "推荐", "人气", "爆款", "神仙", "yyds"]

# Emoji detection pattern — explicit block list to avoid capturing CJK characters.
# Ranges \U000024C2-\U0001F251 and \U00010000-\U0010FFFF are intentionally excluded
# because they overlap with Chinese character planes (U+3400-U+9FFF).
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # Emoticons
    "\U0001F300-\U0001F5FF"   # Misc Symbols & Pictographs
    "\U0001F680-\U0001F6FF"   # Transport & Map
    "\U0001F900-\U0001F9FF"   # Supplemental Symbols & Pictographs
    "\U0001FA00-\U0001FAFF"   # Symbols & Pictographs Extended-A
    "\U0001F1E0-\U0001F1FF"   # Regional Indicator (flags)
    "\U00002600-\U000026FF"   # Miscellaneous Symbols (☀⛅☁)
    "\U00002700-\U000027BF"   # Dingbats (✅❌)
    "\U0001F004-\U0001F0CF"   # Mahjong/Playing card tiles
    "]+",
    flags=re.UNICODE,
)

CHINESE_CITIES = [
    "北京", "上海", "广州", "深圳", "成都", "杭州", "武汉", "重庆", "西安",
    "南京", "苏州", "天津", "青岛", "厦门", "长沙", "郑州", "宁波", "无锡",
]
TITLE_LOCATION_WORDS = CHINESE_CITIES + [
    "番禺", "万博", "北京路", "西关", "南京西路", "春熙路", "建设路", "湖滨",
    "西湖", "国贸", "亚龙湾", "长隆", "太古里", "珠江新城",
]

DOMAIN_MAP = {
    "情感": "relationships", "穿搭": "fashion", "心理": "wellness",
    "健康": "health", "职场": "career", "旅行": "travel",
    "美食": "food", "餐饮": "food", "食品": "food",
    "宠物": "pets", "运动": "sports", "健身": "sports", "学习": "education",
    "母婴": "relationships", "亲子": "relationships",
    "家居": "career", "美妆": "fashion",
}
DOMAIN_LABELS = list(DOMAIN_MAP.values()) + ["others"]

# Chinese public holidays (month, day)
HOLIDAYS = [
    (1, 1), (2, 1), (2, 4), (4, 4), (4, 5), (5, 1),
    (6, 7), (9, 29), (10, 1), (10, 2), (10, 3),
]


# ── Helper functions ──────────────────────────────────────────────

def has_any(text: str, words: list) -> int:
    return int(any(w in text for w in words))


def count_matches(text: str, words: list) -> int:
    return sum(1 for w in words if w in text)


def extract_hashtags(desc: str) -> list:
    return re.findall(r"#([^#\[\]]+?)(?:\[话题\])?#", desc)


def word_freq_entropy(tokens: list) -> float:
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def phrasal_repetition(text: str, n: int = 4) -> float:
    """Ratio of repeated n-grams to total n-grams."""
    if len(text) < n * 2:
        return 0.0
    grams = [text[i : i + n] for i in range(len(text) - n + 1)]
    if not grams:
        return 0.0
    return 1 - len(set(grams)) / len(grams)


def ttr(tokens: list) -> float:
    """Type-Token Ratio: unique tokens / total tokens (lexical diversity)."""
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def _sentence_lengths(text: str) -> list:
    segs = re.split(r"[。！？.!?\n]+", text)
    return [len(s.strip()) for s in segs if s.strip()]


def _coeff_of_variation(values: list) -> float:
    """Coefficient of variation (std/mean). Returns 0 if < 2 samples or mean == 0."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return (variance ** 0.5) / mean


def _emoji_stats(text: str) -> tuple:
    """Returns (total_emoji_chars, unique_emoji_chars)."""
    matches = _EMOJI_RE.findall(text)
    all_chars = list("".join(matches))
    return len(all_chars), len(set(all_chars))


def immediate_repetition_density(tokens: list) -> float:
    """Fraction of consecutive identical token pairs."""
    if len(tokens) < 2:
        return 0.0
    repeats = sum(1 for i in range(len(tokens) - 1) if tokens[i] == tokens[i + 1])
    return repeats / (len(tokens) - 1)


def days_to_nearest_holiday(dt: datetime) -> int:
    min_days = 365
    for month, day in HOLIDAYS:
        try:
            h = datetime(dt.year, month, day)
        except ValueError:
            continue
        diff = abs((h - dt).days)
        min_days = min(min_days, diff)
    return min_days


# ── Main feature extractor ────────────────────────────────────────

def extract_features(row: dict) -> dict:
    title = row.get("note_title", "") or ""
    desc = row.get("desc", "") or ""
    body = title + " " + desc
    local_time_str = str(row.get("local_time", "2024010112"))

    # Parse timestamp
    try:
        dt = datetime.strptime(local_time_str[:10], "%Y%m%d%H")
    except Exception:
        dt = datetime(2024, 1, 1, 12)

    # Tokenize for entropy
    tokens = list(jieba.cut(body, cut_all=False))
    tokens = [t for t in tokens if len(t.strip()) > 1]

    # Hashtags from desc
    hashtags = extract_hashtags(desc)

    # ── Title features (7) ──────────────────────────────────────
    f = {}
    f["title_len"] = len(title)
    f["title_has_pos_emotion"] = has_any(title, POS_EMOTION)
    f["title_has_neg_emotion"] = has_any(title, NEG_EMOTION)
    f["title_has_price"] = has_any(title, PRICE_WORDS)
    f["title_has_question"] = int("?" in title or "？" in title)
    f["title_has_number"] = int(bool(re.search(r"\d", title)))
    f["title_has_new_signal"] = has_any(title, NEW_SIGNAL)
    f["title_has_city"] = has_any(title, TITLE_LOCATION_WORDS)

    # ── Content features (7) ────────────────────────────────────
    f["body_len"] = len(desc)
    f["body_has_address"] = has_any(desc, ADDRESS_WORDS)
    f["body_has_hours"] = has_any(desc, HOURS_WORDS)
    f["body_has_price"] = has_any(desc, PRICE_WORDS)
    f["body_has_transport"] = has_any(desc, TRANSPORT_WORDS)
    f["body_has_booking"] = has_any(desc, BOOKING_WORDS)
    f["body_has_must_order"] = has_any(desc, MUST_ORDER)
    f["body_cta_count"] = count_matches(desc, CTA_WORDS)

    # ── PLAD features (4 original + 9 extended from RedNote-Vibe paper) ──
    f["plad_word_freq_entropy"] = word_freq_entropy(tokens)
    f["plad_phrasal_repetition"] = phrasal_repetition(desc)
    all_chars = len(body)
    punct_chars = sum(1 for c in body if c in "，。！？、；：,.!?;:")
    f["plad_punctuation_ratio"] = punct_chars / all_chars if all_chars > 0 else 0.0
    question_sentences = len(re.findall(r"[？?]", desc))
    total_sentences = max(len(re.split(r"[。！？.!?]", desc)), 1)
    f["plad_interactive_stance"] = (question_sentences + f["body_cta_count"]) / total_sentences

    f["plad_ttr"] = ttr(tokens)
    sent_lens = _sentence_lengths(body)
    f["plad_sentence_count"] = len(sent_lens)
    f["plad_avg_sentence_len"] = sum(sent_lens) / len(sent_lens) if sent_lens else 0.0
    f["plad_sentence_burstiness"] = _coeff_of_variation(sent_lens)
    emoji_total, emoji_unique = _emoji_stats(body)
    f["plad_emoji_density"] = emoji_total / all_chars if all_chars > 0 else 0.0
    f["plad_unique_emoji_ratio"] = emoji_unique / emoji_total if emoji_total > 0 else 0.0
    digit_chars = sum(1 for c in body if c.isdigit())
    f["plad_number_ratio"] = digit_chars / all_chars if all_chars > 0 else 0.0
    word_counts = list(Counter(tokens).values())
    f["plad_word_burstiness"] = _coeff_of_variation(word_counts)
    f["plad_immediate_repetition"] = immediate_repetition_density(tokens)

    # ── Tag features (3) ────────────────────────────────────────
    f["tag_count"] = len(hashtags)
    f["tag_has_city"] = int(any(city in " ".join(hashtags) for city in CHINESE_CITIES))
    f["tag_has_food_travel"] = int(
        any(kw in " ".join(hashtags) for kw in ["美食", "探店", "旅行", "旅游", "餐厅", "打卡"])
    )

    # ── Time features (4) ───────────────────────────────────────
    f["time_hour"] = dt.hour
    f["time_weekday"] = dt.weekday()          # 0=Mon, 6=Sun
    f["time_is_weekend"] = int(dt.weekday() >= 4)
    f["time_days_to_holiday"] = days_to_nearest_holiday(dt)

    # ── Domain (label encoded) ──────────────────────────────────
    domain_cn = row.get("domain", "")
    domain_en = DOMAIN_MAP.get(domain_cn, "others")
    f["domain_encoded"] = DOMAIN_LABELS.index(domain_en)

    return f


# ── CES label computation ─────────────────────────────────────────

def compute_ces_percentile(df: pd.DataFrame) -> pd.Series:
    """Percentile rank within domain (0-100). Missing domain treated as 'others'."""
    df = df.copy()
    df["ces_raw"] = (
        df["liked_count"].fillna(0)
        + df["collected_count"].fillna(0)
        + df["comments_count"].fillna(0) * 4
    )
    df["domain_label"] = df["domain"].fillna("").map(DOMAIN_MAP).fillna("others")
    df["ces_percentile"] = df.groupby("domain_label")["ces_raw"].rank(pct=True) * 100
    return df["ces_percentile"]


# ── Pipeline ──────────────────────────────────────────────────────

def load_and_extract(jsonl_path: str, max_rows: int = None) -> pd.DataFrame:
    print(f"Loading {jsonl_path} ...")
    rows = []
    with open(jsonl_path) as f:
        for i, line in enumerate(f):
            if max_rows and i >= max_rows:
                break
            try:
                rows.append(json.loads(line))
            except Exception:
                continue

    print(f"  Loaded {len(rows):,} rows. Extracting features...")
    jieba.setLogLevel("WARNING")

    records = []
    for i, row in enumerate(rows):
        feat = extract_features(row)
        feat["liked_count"] = row.get("liked_count", 0)
        feat["collected_count"] = row.get("collected_count", 0)
        feat["comments_count"] = row.get("comments_count", 0)
        feat["domain"] = row.get("domain", "")
        feat["note_id"] = row.get("note_id", "")
        records.append(feat)
        if (i + 1) % 10000 == 0:
            print(f"  {i+1:,} / {len(rows):,} ...")

    df = pd.DataFrame(records)
    df["ces_percentile"] = compute_ces_percentile(df)

    print(f"  Done. Shape: {df.shape}")
    print(f"  CES percentile — mean: {df['ces_percentile'].mean():.1f}  median: {df['ces_percentile'].median():.1f}")
    return df


FEATURE_COLS = [
    "title_len", "title_has_pos_emotion", "title_has_neg_emotion",
    "title_has_price", "title_has_question", "title_has_number",
    "title_has_new_signal", "title_has_city",
    "body_len", "body_has_address", "body_has_hours", "body_has_price",
    "body_has_transport", "body_has_booking", "body_has_must_order", "body_cta_count",
    "plad_word_freq_entropy", "plad_phrasal_repetition",
    "plad_punctuation_ratio", "plad_interactive_stance",
    "plad_ttr", "plad_sentence_count", "plad_avg_sentence_len",
    "plad_sentence_burstiness", "plad_emoji_density", "plad_unique_emoji_ratio",
    "plad_number_ratio", "plad_word_burstiness", "plad_immediate_repetition",
    "tag_count", "tag_has_city", "tag_has_food_travel",
    "time_hour", "time_weekday", "time_is_weekend", "time_days_to_holiday",
    "domain_encoded",
]
TARGET_COL = "ces_percentile"

TIMING_FEATURE_COLS = [
    "keyword_search_vol",   # 主标签当前搜索量指数（0-1）
    "trend_momentum",       # 命中热词中上升趋势词占比（0-1）
    "is_trending_topic",    # 是否命中热搜（0/1）
    "content_freshness",    # 话题新鲜度（0-1）
    "category_saturation",  # 同品类竞争密度（0-1）
    "category_avg_ces",     # 同品类平均CES分位（0-100）
    "keyword_competition",  # 同标签存量竞争度（0-1）
    "trend_peak_distance",  # 距热词峰值天数（负=未到峰，正=已过峰）
]

# Semantic features computed by Kimi (moonshot-v1-8k) batch annotation
# Used in model v0.4+; default 0.5 when unavailable (batch not yet run or inference fallback)
SEMANTIC_FEATURE_COLS = [
    "semantic_emotional_intensity",   # 情感强度 (0-1)
    "semantic_empathetic_engagement", # 共情度   (0-1)
    "semantic_rhetorical_score",      # 修辞水平 (0-1)
]

ALL_FEATURE_COLS = FEATURE_COLS + TIMING_FEATURE_COLS  # 45 features for v0.3+


if __name__ == "__main__":
    DATA_PATH = Path(__file__).parent / "data/RedNote-Vibe-Dataset/exploring_set.jsonl"
    OUT_PATH = Path(__file__).parent / "data/features.parquet"

    df = load_and_extract(str(DATA_PATH))
    df.to_parquet(OUT_PATH, index=False)
    print(f"\nSaved to {OUT_PATH}")
    print(df[FEATURE_COLS].describe().round(3))
