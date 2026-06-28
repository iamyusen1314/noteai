"""
NoteAI Pro — Hot Keywords: Storage + Market Timing Features
Scheduler A 写入此模块；/analyze 读取此模块。
"""
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import jieba

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data/hot_keywords.db"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS hot_keywords (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword      TEXT    NOT NULL,
    search_vol   INTEGER DEFAULT 50,
    trend_dir    INTEGER DEFAULT 0,
    source       TEXT    DEFAULT 'homefeed',
    category     TEXT    DEFAULT '',
    captured_at  TEXT    NOT NULL,
    captured_date TEXT   NOT NULL DEFAULT '',
    UNIQUE(keyword, captured_date)
);

CREATE TABLE IF NOT EXISTS keyword_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT    NOT NULL,
    count       INTEGER NOT NULL,
    captured_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kw_captured ON hot_keywords(captured_at);
CREATE INDEX IF NOT EXISTS idx_snap_kw     ON keyword_snapshots(keyword, captured_at);
"""


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript(_INIT_SQL)


# ── Write ─────────────────────────────────────────────────────────────────────

def upsert_keywords(keywords: list[dict]):
    """Save a scrape batch. keywords: [{keyword, search_vol, trend_dir, source, count}]"""
    now = datetime.now().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        for kw in keywords:
            c.execute(
                """
                INSERT INTO hot_keywords
                    (keyword, search_vol, trend_dir, source, category, captured_at, captured_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(keyword, captured_date) DO UPDATE SET
                    search_vol = MAX(search_vol, excluded.search_vol),
                    trend_dir  = excluded.trend_dir,
                    source     = CASE WHEN excluded.source='hot_search' THEN 'hot_search'
                                      ELSE hot_keywords.source END
                """,
                (kw["keyword"], kw.get("search_vol", 50), kw.get("trend_dir", 0),
                 kw.get("source", "homefeed"), kw.get("category", ""), now, today),
            )
            c.execute(
                "INSERT INTO keyword_snapshots (keyword, count, captured_at) VALUES (?,?,?)",
                (kw["keyword"], kw.get("count", 1), now),
            )


# ── Trend direction ───────────────────────────────────────────────────────────

def compute_trend_dir(keyword: str) -> int:
    """1=rising 0=stable -1=falling. Based on last 4 snapshots."""
    with _conn() as c:
        rows = c.execute(
            "SELECT count FROM keyword_snapshots WHERE keyword=? ORDER BY captured_at DESC LIMIT 4",
            (keyword,),
        ).fetchall()
    if len(rows) < 2:
        return 0
    recent, older = rows[0]["count"], rows[-1]["count"]
    if recent > older * 1.2:
        return 1
    if recent < older * 0.8:
        return -1
    return 0


def compute_trend_peak_distance(keyword: str) -> float:
    """Days from the keyword's peak snapshot to now. Negative = still rising (peak ahead).
    Returns 0.0 if fewer than 3 snapshots (insufficient history)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT count, captured_at FROM keyword_snapshots WHERE keyword=? ORDER BY captured_at ASC",
            (keyword,),
        ).fetchall()
    if len(rows) < 3:
        return 0.0
    counts = [r["count"] for r in rows]
    peak_idx = counts.index(max(counts))
    peak_date = datetime.fromisoformat(rows[peak_idx]["captured_at"][:10])
    return float((datetime.now() - peak_date).days)


# ── Domain stats (lazy-loaded from features.parquet) ─────────────────────────

_DOMAIN_STATS: dict = {}


def _load_domain_stats():
    global _DOMAIN_STATS
    if _DOMAIN_STATS:
        return
    feat_path = BASE_DIR / "data/features.parquet"
    if not feat_path.exists():
        return
    try:
        import pandas as pd
        df = pd.read_parquet(feat_path, columns=["domain", "ces_percentile"])
        total = max(len(df), 1)
        stats = df.groupby("domain")["ces_percentile"].agg(["mean", "count"])
        _DOMAIN_STATS = {
            d: {
                "avg_ces":    float(row["mean"]),
                "saturation": min(float(row["count"]) / total, 1.0),
            }
            for d, row in stats.iterrows()
        }
    except Exception:
        pass


def get_domain_stats(domain: str) -> dict:
    """Returns {avg_ces: float, saturation: float} for a domain. Falls back to defaults."""
    _load_domain_stats()
    return _DOMAIN_STATS.get(domain, {"avg_ces": 50.0, "saturation": 0.5})


# ── Read ──────────────────────────────────────────────────────────────────────

def get_top_keywords(limit: int = 300, hours: int = 24) -> list[dict]:
    """
    获取热词列表。优先取最近 hours 小时内的数据；
    若最近数据不足（采集延迟），自动回退到最新可用日期，
    确保始终返回有效热词，不因采集间隔导致数据为空。
    """
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT keyword, MAX(search_vol) vol, trend_dir, source, category
            FROM hot_keywords
            WHERE captured_at > ?
            GROUP BY keyword
            ORDER BY (trend_dir*10 + vol) DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()

        # 回退策略：若最近24小时无数据（采集延迟/离线），
        # 取最新一次采集的数据，确保时机分析始终有依据
        if not rows:
            latest_date = c.execute(
                "SELECT MAX(captured_date) FROM hot_keywords"
            ).fetchone()[0]
            if latest_date:
                rows = c.execute(
                    """
                    SELECT keyword, MAX(search_vol) vol, trend_dir, source, category
                    FROM hot_keywords
                    WHERE captured_date = ?
                    GROUP BY keyword
                    ORDER BY (trend_dir*10 + vol) DESC
                    LIMIT ?
                    """,
                    (latest_date, limit),
                ).fetchall()

    return [dict(r) for r in rows]


def db_status() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM hot_keywords").fetchone()[0]
        latest = c.execute(
            "SELECT captured_at FROM hot_keywords ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
    return {"total_keywords": total, "latest_capture": latest[0] if latest else None}


# ── Match ─────────────────────────────────────────────────────────────────────

def match_keywords(text: str) -> list[dict]:
    """Find hot keywords present in the input text."""
    if not text:
        return []
    top = get_top_keywords(limit=500)
    index = {k["keyword"]: k for k in top}
    matched: dict[str, dict] = {}

    # Direct substring match
    for kw, data in index.items():
        if kw in text:
            matched[kw] = data

    # Jieba token match (catches compound words not in raw text)
    try:
        for token in jieba.cut(text):
            if len(token) >= 2 and token in index and token not in matched:
                matched[token] = index[token]
    except Exception:
        pass

    return sorted(matched.values(), key=lambda x: x.get("vol", 0), reverse=True)


# ── Market timing features ────────────────────────────────────────────────────

def compute_market_timing(title: str, desc: str, domain: str) -> dict:
    """
    Compute market timing features + timing_coefficient + keyword suggestions.
    Used by /analyze to inject trend context into Claude prompt.
    """
    full_text = f"{title} {desc}"
    matched = match_keywords(full_text)
    all_top = get_top_keywords(limit=30)
    matched_set = {k["keyword"] for k in matched}

    domain_stats = get_domain_stats(domain)

    if not matched:
        suggested = [k["keyword"] for k in all_top[:6]]
        return {
            "keyword_search_vol":  0.0,
            "trend_momentum":      0.0,
            "is_trending_topic":   0.0,
            "content_freshness":   0.5,
            "category_saturation": round(domain_stats["saturation"], 3),
            "category_avg_ces":    round(domain_stats["avg_ces"], 1),
            "keyword_competition": 0.5,
            "trend_peak_distance": 0.0,
            "timing_coefficient":  0.85,
            "matched_keywords":    [],
            "suggested_keywords":  suggested,
            "timing_note":         "未命中近期热词，建议在标题或话题标签中加入以下热词",
            "timing_action":       "suggest",
        }

    max_vol        = max(k.get("vol", 50) for k in matched) / 100.0
    rising         = sum(1 for k in matched if k.get("trend_dir", 0) == 1)
    trend_momentum = rising / len(matched)
    is_trending    = float(any(k.get("source") == "hot_search" for k in matched))
    content_freshness   = min(0.5 + trend_momentum * 0.5, 1.0)
    keyword_competition = max_vol * 0.8

    # trend_peak_distance: average across matched keywords (0.0 if insufficient snapshots)
    peak_distances = [compute_trend_peak_distance(k["keyword"]) for k in matched[:5]]
    trend_peak_distance = round(sum(peak_distances) / len(peak_distances), 1) if peak_distances else 0.0

    timing_coefficient = (
        0.85
        + max_vol             * 0.25
        + trend_momentum      * 0.20
        + is_trending         * 0.10
        - keyword_competition * 0.10
    )
    timing_coefficient = round(min(max(timing_coefficient, 0.6), 1.4), 3)

    matched_names = [k["keyword"] for k in matched[:8]]

    # Suggest complementary hot keywords not yet in the content
    suggested = [k["keyword"] for k in all_top if k["keyword"] not in matched_set][:5]

    # Human-readable note
    rising_kws = [k["keyword"] for k in matched if k.get("trend_dir") == 1][:3]
    hot_kws    = [k["keyword"] for k in matched if k.get("source") == "hot_search"][:3]
    parts = []
    if hot_kws:
        parts.append(f"命中热搜词：{'、'.join(hot_kws)}")
    if rising_kws:
        parts.append(f"上升趋势词：{'、'.join(rising_kws)}")
    if not parts:
        parts.append(f"命中热词：{'、'.join(matched_names[:3])}")
    if suggested:
        parts.append(f"建议补充：{'、'.join(suggested[:3])}")

    return {
        "keyword_search_vol":  round(max_vol, 3),
        "trend_momentum":      round(trend_momentum, 3),
        "is_trending_topic":   is_trending,
        "content_freshness":   round(content_freshness, 3),
        "category_saturation": round(domain_stats["saturation"], 3),
        "category_avg_ces":    round(domain_stats["avg_ces"], 1),
        "keyword_competition": round(keyword_competition, 3),
        "trend_peak_distance": trend_peak_distance,
        "timing_coefficient":  timing_coefficient,
        "matched_keywords":    matched_names,
        "suggested_keywords":  suggested,
        "timing_note":         "；".join(parts),
        "timing_action":       "reinforce",
    }
