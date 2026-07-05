"""
NoteAI Pro — Hot Keywords: Storage + Market Timing Features
Scheduler A 写入此模块；/analyze 读取此模块。
"""
import sqlite3
import re
import os
import json
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import jieba

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data/hot_keywords.db"
FRESHNESS_MAX_HOURS = int(os.environ.get("NOTEAI_HOT_KEYWORD_FRESH_HOURS", "30") or 30)
CLOUD_SNAPSHOT_URL = os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_URL", "").strip()
CLOUD_REFRESH_URL = os.environ.get("NOTEAI_MARKET_TIMING_REFRESH_URL", "").strip()
CLOUD_REFRESH_TOKEN = os.environ.get("NOTEAI_MARKET_TIMING_REFRESH_TOKEN", "").strip()
CLOUD_FETCH_TIMEOUT = float(os.environ.get("NOTEAI_MARKET_TIMING_FETCH_TIMEOUT", "8") or 8)
DEFAULT_MIN_DOMAIN_KEYWORDS = int(os.environ.get("NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS", "12") or 12)
AUTHORIZED_TREND_SOURCE = "authorized_trend"
AUTHORIZED_TREND_SOURCES = {"authorized_trend", "official_trend", "licensed_trend", "partner_trend"}
BASELINE_EVIDENCE_SOURCE = "industry_baseline"
CORE_EVIDENCE_DOMAINS = ("美食", "旅行", "穿搭", "美妆", "家居", "健身")

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS hot_keywords (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword      TEXT    NOT NULL,
    search_vol   INTEGER DEFAULT 50,
    trend_dir    INTEGER DEFAULT 0,
    source       TEXT    DEFAULT 'homefeed',
    category     TEXT    DEFAULT '',
    sample_count INTEGER DEFAULT 1,
    quality_score INTEGER DEFAULT 50,
    evidence_level TEXT DEFAULT 'weak',
    quality_reason TEXT DEFAULT '',
    captured_at  TEXT    NOT NULL,
    captured_date TEXT   NOT NULL DEFAULT '',
    UNIQUE(keyword, category, captured_date)
);

CREATE TABLE IF NOT EXISTS keyword_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT    NOT NULL,
    count       INTEGER NOT NULL,
    captured_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kw_captured ON hot_keywords(captured_at);
CREATE INDEX IF NOT EXISTS idx_kw_category_captured ON hot_keywords(category, captured_at);
CREATE INDEX IF NOT EXISTS idx_snap_kw     ON keyword_snapshots(keyword, captured_at);
"""

_DOMAIN_CATEGORY_ALIASES = {
    "美食": ("美食", "餐饮", "本地生活"),
    "餐饮": ("美食", "餐饮", "本地生活"),
    "本地生活": ("本地生活", "美食"),
    "旅行": ("旅行", "酒旅"),
    "酒旅": ("旅行", "酒旅"),
    "穿搭": ("穿搭", "时尚"),
    "时尚": ("穿搭", "时尚"),
    "美妆": ("美妆", "护肤", "彩妆"),
    "护肤": ("美妆", "护肤", "彩妆"),
    "家居": ("家居", "装修", "收纳"),
    "健身": ("健身", "运动"),
    "运动": ("健身", "运动"),
}

_DAILY_BASELINE_SEEDS = {
    "美食": (
        "本地美食探店", "粤菜餐厅推荐", "小吃宵夜攻略", "茶餐厅点单", "早茶点心",
        "海鲜砂锅", "牛肉火锅", "咖啡甜品", "周末聚餐", "人均友好餐厅", "亲子餐厅",
        "约会餐厅", "排队少美食", "地铁沿线美食", "招牌菜推荐", "清单式点单",
    ),
    "旅行": (
        "周末旅行攻略", "亲子酒店推荐", "城市漫游路线", "高铁短途游", "海边度假",
        "小众景点", "酒店避坑", "自由行路线", "自驾游攻略", "景区交通", "民宿体验",
        "亲子旅行", "两天一夜", "旅行清单", "当地美食路线", "拍照机位",
    ),
    "穿搭": (
        "通勤穿搭", "小个子显高", "夏季显瘦穿搭", "基础款搭配", "半裙搭配",
        "衬衫穿法", "牛仔裤搭配", "大码显瘦", "约会穿搭", "通勤鞋包", "配色公式",
        "短袖搭配", "法式穿搭", "平价穿搭", "外套叠穿", "胶囊衣橱",
    ),
    "美妆": (
        "夏季底妆", "防晒推荐", "油皮粉底", "干皮粉底", "通勤妆容",
        "美甲款式", "口红色号", "遮瑕教程", "定妆粉饼", "面膜修护", "护肤精华",
        "眼影配色", "香水推荐", "卸妆清洁", "新手化妆", "短甲美甲",
    ),
    "家居": (
        "装修避坑", "小户型收纳", "厨房改造", "客厅软装", "卧室收纳",
        "全屋清洁", "家电选购", "阳台改造", "卫生间收纳", "衣柜设计", "灯光设计",
        "预算控制", "瓷砖选择", "断舍离收纳", "租房改造", "餐桌布置",
    ),
    "健身": (
        "减肥训练计划", "居家燃脂", "普拉提塑形", "臀腿训练", "核心训练",
        "肩颈拉伸", "跑步入门", "跳绳燃脂", "饮食蛋白", "瘦小腿训练", "新手健身",
        "膝盖友好动作", "瑜伽拉伸", "增肌训练", "体重管理", "居家无器械",
    ),
}


def _domain_categories(domain: str | None) -> tuple[str, ...]:
    domain = (domain or "").strip()
    if not domain:
        return ()
    return _DOMAIN_CATEGORY_ALIASES.get(domain, (domain,))


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


@contextmanager
def _db_conn():
    conn = _conn()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _hot_keywords_unique_columns(c: sqlite3.Connection) -> list[str]:
    try:
        for idx in c.execute("PRAGMA index_list(hot_keywords)").fetchall():
            if not int(idx["unique"]):
                continue
            cols = [
                row["name"]
                for row in c.execute(f"PRAGMA index_info({idx['name']})").fetchall()
            ]
            if "keyword" in cols and "captured_date" in cols:
                return cols
    except Exception:
        return []
    return []


def _ensure_category_unique_schema(c: sqlite3.Connection) -> None:
    cols = _hot_keywords_unique_columns(c)
    if not cols or cols == ["keyword", "category", "captured_date"]:
        return
    if cols != ["keyword", "captured_date"]:
        return
    c.execute("ALTER TABLE hot_keywords RENAME TO hot_keywords_old_unique")
    c.executescript(_INIT_SQL)
    c.execute(
        """
        INSERT OR IGNORE INTO hot_keywords
            (id, keyword, search_vol, trend_dir, source, category, captured_at, captured_date)
        SELECT
            id, keyword, search_vol, trend_dir, source, COALESCE(category, ''),
            captured_at, captured_date
        FROM hot_keywords_old_unique
        """
    )
    c.execute("DROP TABLE hot_keywords_old_unique")


def _ensure_hot_keyword_quality_columns(c: sqlite3.Connection) -> None:
    cols = {row["name"] for row in c.execute("PRAGMA table_info(hot_keywords)").fetchall()}
    additions = {
        "sample_count": "ALTER TABLE hot_keywords ADD COLUMN sample_count INTEGER DEFAULT 1",
        "quality_score": "ALTER TABLE hot_keywords ADD COLUMN quality_score INTEGER DEFAULT 50",
        "evidence_level": "ALTER TABLE hot_keywords ADD COLUMN evidence_level TEXT DEFAULT 'weak'",
        "quality_reason": "ALTER TABLE hot_keywords ADD COLUMN quality_reason TEXT DEFAULT ''",
    }
    for col, sql in additions.items():
        if col not in cols:
            c.execute(sql)


def init_db():
    with _db_conn() as c:
        c.executescript(_INIT_SQL)
        _ensure_category_unique_schema(c)
        _ensure_hot_keyword_quality_columns(c)


# ── Write ─────────────────────────────────────────────────────────────────────

def upsert_keywords(keywords: list[dict]):
    """Save a scrape batch. keywords: [{keyword, search_vol, trend_dir, source, count}]"""
    now = datetime.now().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    with _db_conn() as c:
        for raw_kw in keywords:
            kw = clean_scraped_keyword_row(raw_kw)
            if not kw:
                continue
            c.execute(
                """
                INSERT INTO hot_keywords
                    (keyword, search_vol, trend_dir, source, category,
                     sample_count, quality_score, evidence_level, quality_reason,
                     captured_at, captured_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(keyword, category, captured_date) DO UPDATE SET
                    search_vol = MAX(search_vol, excluded.search_vol),
                    trend_dir  = excluded.trend_dir,
                    source     = CASE
                                      WHEN excluded.source IN ('hot_search', 'authorized_trend', 'official_trend', 'licensed_trend', 'partner_trend')
                                           THEN excluded.source
                                      WHEN hot_keywords.source NOT IN ('hot_search', 'authorized_trend', 'official_trend', 'licensed_trend', 'partner_trend')
                                           AND excluded.source IN ('cloud_snapshot', 'search_recommend', 'search_phrase')
                                           THEN excluded.source
                                      ELSE hot_keywords.source
                                  END,
                    category   = CASE WHEN excluded.category!='' THEN excluded.category
                                      ELSE hot_keywords.category END,
                    sample_count = MAX(sample_count, excluded.sample_count),
                    quality_score = MAX(quality_score, excluded.quality_score),
                    evidence_level = excluded.evidence_level,
                    quality_reason = excluded.quality_reason,
                    captured_at = excluded.captured_at
                """,
                (kw["keyword"], kw.get("search_vol", 50), kw.get("trend_dir", 0),
                 kw.get("source", "homefeed"), kw.get("category", ""),
                 int(kw.get("sample_count", kw.get("count", 1)) or 1),
                 int(kw.get("quality_score", 50) or 50),
                 kw.get("evidence_level", "weak"),
                 kw.get("quality_reason", ""),
                 now, today),
            )
            c.execute(
                "INSERT INTO keyword_snapshots (keyword, count, captured_at) VALUES (?,?,?)",
                (kw["keyword"], kw.get("count", 1), now),
            )


# ── Cloud snapshot import/export ──────────────────────────────────────────────

def _parse_snapshot_time(value: str | None) -> str:
    if not value:
        return datetime.now().isoformat()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None).isoformat()
    except Exception:
        return datetime.now().isoformat()


def _snapshot_keyword_rows(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        payload = {"keywords": payload}
    if not isinstance(payload, dict):
        return []

    for envelope_key in ("data", "result"):
        envelope = payload.get(envelope_key)
        if isinstance(envelope, dict) and any(k in envelope for k in ("keywords", "domains", "items", "trends", "hot_search", "hot_keywords")):
            nested = dict(envelope)
            nested.setdefault("captured_at", payload.get("captured_at") or payload.get("generated_at"))
            payload = nested
            break
        if isinstance(envelope, list) and not any(k in payload for k in ("keywords", "domains")):
            payload = {
                "keywords": envelope,
                "captured_at": payload.get("captured_at") or payload.get("generated_at"),
            }
            break

    rows: list[dict] = []
    captured_default = _parse_snapshot_time(payload.get("captured_at") or payload.get("generated_at"))

    top_level_keyword_rows: list = []
    for key in ("keywords", "items", "trends", "hot_search", "hot_keywords"):
        value = payload.get(key)
        if isinstance(value, list):
            top_level_keyword_rows.extend(value)

    if top_level_keyword_rows:
        for item in top_level_keyword_rows:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["captured_at"] = _parse_snapshot_time(row.get("captured_at") or captured_default)
            rows.append(row)
    domains = payload.get("domains")
    if isinstance(domains, dict):
        for domain, value in domains.items():
            if isinstance(value, dict):
                captured = _parse_snapshot_time(value.get("captured_at") or captured_default)
                keywords = value.get("keywords") or []
            else:
                captured = captured_default
                keywords = value if isinstance(value, list) else []
            for item in keywords:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                row.setdefault("category", domain)
                row["captured_at"] = _parse_snapshot_time(row.get("captured_at") or captured)
                rows.append(row)
    return rows


def import_keyword_snapshot(payload: dict | list, default_source: str = "cloud_snapshot") -> dict:
    rows = _snapshot_keyword_rows(payload or {})
    if not rows:
        return {"imported": 0, "domains": []}
    imported = 0
    domains: set[str] = set()
    with _db_conn() as c:
        for raw_row in rows:
            raw_row = dict(raw_row)
            if default_source:
                raw_row.setdefault("source", default_source)
            row = clean_scraped_keyword_row(raw_row)
            if not row:
                continue
            keyword = str(row.get("keyword") or "").strip()
            if not keyword:
                continue
            captured_at = _parse_snapshot_time(row.get("captured_at"))
            captured_date = captured_at[:10]
            category = str(row.get("category") or row.get("domain") or "")
            c.execute(
                """
                INSERT INTO hot_keywords
                    (keyword, search_vol, trend_dir, source, category,
                     sample_count, quality_score, evidence_level, quality_reason,
                     captured_at, captured_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(keyword, category, captured_date) DO UPDATE SET
                    search_vol = MAX(search_vol, excluded.search_vol),
                    trend_dir  = excluded.trend_dir,
                    source     = excluded.source,
                    sample_count = MAX(sample_count, excluded.sample_count),
                    quality_score = MAX(quality_score, excluded.quality_score),
                    evidence_level = excluded.evidence_level,
                    quality_reason = excluded.quality_reason,
                    captured_at = excluded.captured_at
                """,
                (
                    keyword,
                    int(row.get("search_vol", row.get("vol", 50)) or 50),
                    int(row.get("trend_dir", 0) or 0),
                    str(row.get("source") or default_source or "cloud_snapshot"),
                    category,
                    int(row.get("sample_count", row.get("count", 1)) or 1),
                    int(row.get("quality_score", 50) or 50),
                    str(row.get("evidence_level") or "weak"),
                    str(row.get("quality_reason") or ""),
                    captured_at,
                    captured_date,
                ),
            )
            c.execute(
                "INSERT INTO keyword_snapshots (keyword, count, captured_at) VALUES (?,?,?)",
                (keyword, int(row.get("count", 1) or 1), captured_at),
            )
            imported += 1
            if category:
                domains.add(category)
    return {
        "imported": imported,
        "domains": sorted(domains),
    }


def export_keyword_snapshot(hours: int = FRESHNESS_MAX_HOURS) -> dict:
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    with _db_conn() as c:
        rows = c.execute(
            """
            SELECT keyword, search_vol, trend_dir, source, category,
                   sample_count, quality_score, evidence_level, quality_reason,
                   captured_at, captured_date
            FROM hot_keywords
            WHERE captured_at > ?
            ORDER BY category, (quality_score*0.65 + search_vol*0.35 + trend_dir*5) DESC
            """,
            (since,),
        ).fetchall()
    domains: dict[str, dict] = {}
    for row in rows:
        category = row["category"] or "综合"
        bucket = domains.setdefault(category, {"captured_at": row["captured_at"], "keywords": []})
        if row["captured_at"] > bucket["captured_at"]:
            bucket["captured_at"] = row["captured_at"]
        bucket["keywords"].append({
            "keyword": row["keyword"],
            "search_vol": int(row["search_vol"] or 0),
            "trend_dir": int(row["trend_dir"] or 0),
            "source": row["source"] or "unknown",
            "category": category,
            "sample_count": int(row["sample_count"] or 1),
            "quality_score": int(row["quality_score"] or 0),
            "evidence_level": row["evidence_level"] or "weak",
            "quality_reason": row["quality_reason"] or "",
            "captured_at": row["captured_at"],
        })
    return {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "freshness_max_hours": hours,
        "domains": domains,
    }


def write_keyword_snapshot(path: str | Path, hours: int = FRESHNESS_MAX_HOURS) -> dict:
    payload = export_keyword_snapshot(hours=hours)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _load_snapshot_from_url(url: str, headers: dict | None = None, timeout: float | None = None) -> dict:
    if url.startswith("file://"):
        return json.loads(Path(url[7:]).read_text(encoding="utf-8"))
    if "://" not in url:
        return json.loads(Path(url).read_text(encoding="utf-8"))
    effective_timeout = timeout
    if effective_timeout is None:
        effective_timeout = float(os.environ.get("NOTEAI_MARKET_TIMING_FETCH_TIMEOUT", str(CLOUD_FETCH_TIMEOUT)) or CLOUD_FETCH_TIMEOUT)
    with httpx.Client(timeout=effective_timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


def _trigger_cloud_refresh(domain: str | None = None) -> None:
    refresh_url = os.environ.get("NOTEAI_MARKET_TIMING_REFRESH_URL", CLOUD_REFRESH_URL).strip()
    refresh_token = os.environ.get("NOTEAI_MARKET_TIMING_REFRESH_TOKEN", CLOUD_REFRESH_TOKEN).strip()
    if not refresh_url:
        return
    headers = {}
    if refresh_token:
        headers["Authorization"] = f"Bearer {refresh_token}"
    try:
        timeout = float(os.environ.get("NOTEAI_MARKET_TIMING_FETCH_TIMEOUT", str(CLOUD_FETCH_TIMEOUT)) or CLOUD_FETCH_TIMEOUT)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            client.post(refresh_url, json={"domain": domain or ""}, headers=headers)
    except Exception:
        pass


def sync_cloud_keyword_snapshot(domain: str | None = None, trigger_refresh: bool = False) -> dict:
    if trigger_refresh:
        _trigger_cloud_refresh(domain)
    snapshot_url = os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_URL", CLOUD_SNAPSHOT_URL).strip()
    if not snapshot_url:
        return {"enabled": False, "imported": 0, "reason": "NOTEAI_MARKET_TIMING_SNAPSHOT_URL not set"}
    payload = _load_snapshot_from_url(snapshot_url)
    result = import_keyword_snapshot(payload, default_source="cloud_snapshot")
    result["enabled"] = True
    result["source"] = "cloud_snapshot"
    result["source_url"] = snapshot_url
    return result


def _authorized_trend_url_for_domain(url: str, domain: str | None = None) -> str:
    if domain and "{domain}" in url:
        return url.replace("{domain}", quote(domain))
    return url


def _authorized_trend_headers() -> dict:
    headers = {"Accept": "application/json"}
    token = os.environ.get("NOTEAI_AUTHORIZED_TREND_TOKEN", "").strip()
    if not token:
        return headers
    header_name = os.environ.get("NOTEAI_AUTHORIZED_TREND_AUTH_HEADER", "Authorization").strip() or "Authorization"
    scheme = os.environ.get("NOTEAI_AUTHORIZED_TREND_AUTH_SCHEME", "Bearer").strip()
    if header_name.lower() == "authorization" and scheme:
        headers[header_name] = f"{scheme} {token}"
    else:
        headers[header_name] = token
    return headers


def sync_authorized_trend_source(domain: str | None = None) -> dict:
    """Import a licensed/official trend JSON feed when configured.

    This is intentionally optional. If no provider URL is configured, the market
    timing pipeline keeps using the existing cloud snapshot / scraper path.
    """
    source_url = os.environ.get("NOTEAI_AUTHORIZED_TREND_URL", "").strip()
    if not source_url:
        return {"enabled": False, "imported": 0, "reason": "NOTEAI_AUTHORIZED_TREND_URL not set"}
    timeout = float(os.environ.get("NOTEAI_AUTHORIZED_TREND_TIMEOUT", str(CLOUD_FETCH_TIMEOUT)) or CLOUD_FETCH_TIMEOUT)
    request_url = _authorized_trend_url_for_domain(source_url, domain)
    try:
        payload = _load_snapshot_from_url(request_url, headers=_authorized_trend_headers(), timeout=timeout)
        result = import_keyword_snapshot(payload, default_source=AUTHORIZED_TREND_SOURCE)
        result["enabled"] = True
        result["source"] = AUTHORIZED_TREND_SOURCE
        result["source_url"] = source_url
        return result
    except Exception as exc:
        return {
            "enabled": True,
            "imported": 0,
            "source": AUTHORIZED_TREND_SOURCE,
            "source_url": source_url,
            "error": str(exc),
        }


def ensure_fresh_domain_keywords(domain: str, trigger_refresh: bool = True) -> dict:
    init_db()
    status = db_status(domain)
    if status.get("has_fresh_domain_data"):
        return {"ok": True, "status": status, "synced": False}

    sync_result = sync_authorized_trend_source(domain=domain)
    status = db_status(domain)
    if status.get("has_fresh_domain_data"):
        return {"ok": True, "status": status, "synced": True, "sync_result": sync_result}

    sync_result = sync_cloud_keyword_snapshot(domain=domain, trigger_refresh=False)
    status = db_status(domain)
    if status.get("has_fresh_domain_data"):
        return {"ok": True, "status": status, "synced": True, "sync_result": sync_result}
    if trigger_refresh:
        sync_result = sync_cloud_keyword_snapshot(domain=domain, trigger_refresh=True)
        status = db_status(domain)
        if status.get("has_fresh_domain_data"):
            return {"ok": True, "status": status, "synced": True, "sync_result": sync_result}
    return {"ok": False, "status": status, "synced": bool(sync_result.get("enabled")), "sync_result": sync_result}


# ── Trend direction ───────────────────────────────────────────────────────────

def compute_trend_dir(keyword: str) -> int:
    """1=rising 0=stable -1=falling. Based on last 4 snapshots."""
    with _db_conn() as c:
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
    with _db_conn() as c:
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

_GENERIC_KEYWORDS = {
    "一个", "这个", "那个", "什么", "真的", "这样", "这么", "怎么", "可以", "不是", "没有",
    "还是", "就是", "自己", "现在", "今天", "昨天", "明天", "时候", "感觉", "喜欢", "因为",
    "分享", "笔记", "小红书", "有用", "回家", "这家", "那家", "人均", "价格", "地址",
    "一下", "一些", "大家", "姐妹", "朋友", "推荐", "收藏", "点赞", "看看", "知道",
    "到底", "终于", "开始", "不会", "一定", "需要", "那么", "如果", "一起", "好看",
    "快乐", "日常", "生活", "女生", "男生", "你们", "我们", "他们", "它们", "哈哈",
    "哈哈哈", "啊啊啊", "真的很", "太适合", "谁懂啊", "救命", "绝了", "爱了",
    "vlog", "Vlog", "tips", "Tips", "合集", "全网", "浅浅", "干干净净",
}

_DOMAIN_KEYWORD_HINTS = {
    "美食": (
        "吃饭", "美食", "菜品", "餐厅", "饭店", "门店", "私厨", "厨师", "厨神", "厨艺", "奶茶", "咖啡", "甜品", "面馆",
        "粉店", "火锅", "烧烤", "小吃", "粤菜", "探店", "宵夜", "早茶", "brunch", "蛋糕",
        "面包", "巧克力", "奶油", "饮食", "好吃", "好喝", "茶餐厅", "小龙虾", "小青龙", "芝士",
        "牛排", "烤肉",
        "自助", "酸菜鱼", "鱼生", "寿司", "烧鸟", "点心", "乳鸽", "海鲜", "牛肉", "猪脚", "砂锅",
        "酒楼", "餐吧", "料理", "烘焙", "茶饮",
    ),
    "餐饮": (
        "吃饭", "美食", "菜品", "餐厅", "饭店", "门店", "私厨", "厨师", "厨神", "厨艺", "奶茶", "咖啡", "甜品", "面馆",
        "粉店", "火锅", "烧烤", "小吃", "探店", "蛋糕", "面包", "好吃", "好喝", "烤肉",
    ),
    "本地生活": (
        "店", "探店", "商圈", "周末", "路线", "体验", "排队", "预约", "地铁", "停车", "到店",
        "团购", "套餐", "人均", "营业", "服务", "门店",
    ),
    "旅行": (
        "酒店", "景区", "路线", "攻略", "交通", "机票", "民宿", "出行", "城市", "周末", "旅行",
        "旅游", "海边", "度假", "亲子", "自由行", "自驾", "高铁", "机场", "签证", "门票", "北京",
        "上海", "广州", "深圳", "成都", "杭州", "重庆", "新疆", "云南", "三亚", "香港", "澳门",
    ),
    "酒旅": (
        "酒店", "景区", "路线", "攻略", "交通", "机票", "民宿", "出行", "城市", "周末", "旅行",
        "旅游", "海边", "度假", "亲子", "自由行", "自驾", "高铁", "机场", "签证", "门票",
    ),
    "穿搭": (
        "穿", "搭", "裤", "裙", "外套", "鞋", "包", "通勤", "显瘦", "配色", "小个子", "大码",
        "旗袍", "项链", "衬衫", "牛仔", "短袖", "半裙", "吊带", "风衣", "西装", "内搭", "穿法",
    ),
    "时尚": (
        "穿", "搭", "裤", "裙", "外套", "鞋", "包", "通勤", "显瘦", "配色", "小个子", "大码",
        "旗袍", "项链", "衬衫", "牛仔", "短袖", "半裙", "吊带", "风衣", "西装", "内搭", "穿法",
    ),
    "美妆": (
        "妆", "makeup", "口红", "粉底", "护肤", "面霜", "精华", "防晒", "色号", "肤质", "彩妆", "底妆",
        "眼影", "腮红", "眉笔", "睫毛", "香水", "唇釉", "遮瑕", "卸妆", "水乳", "面膜", "指甲油",
        "美甲", "短甲", "甲", "鼻影", "修容", "高光", "粉饼", "定妆",
    ),
    "彩妆": (
        "妆", "makeup", "口红", "粉底", "护肤", "面霜", "精华", "防晒", "色号", "肤质", "彩妆", "底妆",
        "眼影", "腮红", "眉笔", "睫毛", "香水", "唇釉", "遮瑕", "卸妆", "面膜", "指甲油",
        "美甲", "短甲", "甲", "鼻影", "修容", "高光", "粉饼", "定妆",
    ),
    "家居": (
        "家居", "全屋", "家电", "家务", "自建房", "收纳", "装修", "阳台", "厨房", "客厅", "卧室", "柜", "预算", "网红设计", "翻车",
        "软装", "硬装", "瓷砖", "灯", "沙发", "餐桌", "卫生间", "洗手台", "衣柜", "断舍离",
        "清洁", "冰箱", "洗衣机", "户型",
    ),
    "健身": (
        "健身", "训练", "动作", "燃脂", "增肌", "拉伸", "跑步", "核心", "膝盖", "减肥", "跳绳",
        "体重", "小腿", "倒立", "练习", "瑜伽", "普拉提", "臀腿", "肩颈", "饮食", "蛋白", "瘦",
    ),
    "运动": (
        "健身", "训练", "动作", "燃脂", "增肌", "拉伸", "跑步", "核心", "膝盖", "减肥", "跳绳",
        "体重", "小腿", "倒立", "练习", "瑜伽", "普拉提", "臀腿", "肩颈", "饮食", "蛋白", "瘦",
    ),
    "职场": (
        "面试", "工作", "职场", "简历", "offer", "招聘", "跳槽", "副业", "考编", "教资", "教师",
        "联考", "公务员", "考研", "实习", "证书", "工资", "绩效",
    ),
    "情感": (
        "恋爱", "男朋友", "女朋友", "男友", "女友", "老公", "老婆", "crush", "分手", "复合",
        "婚姻", "相亲", "沟通", "关系", "情侣",
    ),
    "影视": (
        "电影", "电视剧", "好剧", "看剧", "综艺", "短剧", "纪录片", "演员", "导演", "票房",
        "爱情", "悬疑", "喜剧", "院线",
    ),
}

_SOURCE_PRIORITY = {
    "hot_search": 4,
    "authorized_trend": 4,
    "official_trend": 4,
    "licensed_trend": 4,
    "partner_trend": 4,
    "cloud_snapshot": 3,
    "search_recommend": 3,
    "search_phrase": 3,
    "search_token": 2,
    "homefeed_phrase": 2,
    "homefeed": 1,
    "homefeed_token": 1,
    BASELINE_EVIDENCE_SOURCE: 1,
}

_WEAK_BUT_USEFUL_BY_DOMAIN = {
    "旅行": {"攻略", "周末", "酒店", "旅游", "旅行"},
    "酒旅": {"攻略", "周末", "酒店", "旅游", "旅行"},
    "美食": {"好吃", "好喝", "探店", "蛋糕", "咖啡"},
    "餐饮": {"好吃", "好喝", "探店", "蛋糕", "咖啡"},
    "本地生活": {"探店", "周末", "到店", "停车", "地铁"},
    "健身": {"减肥", "训练", "健身", "饮食"},
    "运动": {"减肥", "训练", "健身", "饮食"},
    "穿搭": {"好看", "显瘦", "平价", "通勤"},
    "美妆": {"好看", "防晒", "底妆", "色号"},
    "彩妆": {"好看", "防晒", "底妆", "色号"},
    "家居": {"装修", "收纳", "翻车", "清洁"},
}

_SEARCH_RECOMMEND_NOISE = (
    "博主", "招募", "互关", "拍摄技巧", "bgm", "视频", "图文", "怎么做",
    "文案", "标题", "模板", "素材", "头像", "壁纸", "表情包", "vlog",
    "app", "excel", "ppt", "pdf", "手抄报", "制作", "下载",
)


def normalize_keyword_text(keyword: str) -> str:
    kw = unicodedata.normalize("NFKC", str(keyword or "")).strip()
    kw = re.sub(r"#([^#\s]+)", r"\1", kw)
    kw = re.sub(r"[\u200b-\u200f\ufeff]", "", kw)
    kw = re.sub(r"\s+", "", kw)
    kw = re.sub(r"[，。！？、；：,.!?;:「」『』【】\[\]()（）<>《》|/\\\"'“”‘’]+", "", kw)
    kw = re.sub(r"^[·~～\-_=+]+|[·~～\-_=+]+$", "", kw)
    kw = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9￥元%折]+", "", kw)
    return kw[:24]


def _chinese_char_count(keyword: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", keyword or ""))


def _is_phrase_keyword(keyword: str, source: str | None = None) -> bool:
    source = source or ""
    return source == "homefeed_phrase" or _chinese_char_count(keyword) >= 5 or len(keyword) >= 8


def _domain_hint_hit(category: str | None, keyword: str) -> bool:
    kw = (keyword or "").strip()
    if not kw:
        return False
    hints = _DOMAIN_KEYWORD_HINTS.get(category or "")
    if not hints:
        return True
    return any(h.lower() in kw.lower() for h in hints)


def keyword_quality_profile(keyword: str, category: str | None = None, source: str | None = None, count: int | float = 1) -> dict:
    kw = normalize_keyword_text(keyword)
    category = (category or "").strip()
    source = (source or "homefeed").strip() or "homefeed"
    count_value = float(count or 1)
    phrase = _is_phrase_keyword(kw, source)
    hint_hit = _domain_hint_hit(category, kw)
    weak_useful = kw in _WEAK_BUT_USEFUL_BY_DOMAIN.get(category, set())

    if len(kw) < 2:
        return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "too_short"}
    if kw in _GENERIC_KEYWORDS and not weak_useful:
        return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "generic_stopword"}
    if re.fullmatch(r"\d+(?:\.\d+)?", kw):
        return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "pure_number"}
    if re.fullmatch(r"[a-zA-Z]+", kw) and len(kw) < 4:
        return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "short_ascii"}
    if re.fullmatch(r"[a-zA-Z]+", kw) and category and category not in ("综合", "推荐") and not hint_hit:
        return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "ascii_domain_mismatch"}
    if source == "search_recommend" and any(noise in kw.lower() for noise in _SEARCH_RECOMMEND_NOISE):
        return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "search_recommend_meta_noise"}
    if len(set(kw.lower())) <= 2 and len(kw) >= 4:
        return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "repeated_noise"}

    if category and category not in ("综合", "推荐") and not hint_hit:
        if source == "hot_search" or source in AUTHORIZED_TREND_SOURCES:
            pass
        elif not phrase:
            return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "domain_mismatch_token"}
        elif count_value < 2:
            return {"keyword": kw, "keep": False, "multiplier": 0.0, "reason": "domain_mismatch_singleton_phrase"}

    multiplier = 1.0
    reasons = []
    if source == "hot_search":
        multiplier += 0.35
        reasons.append("hot_search")
    elif source in AUTHORIZED_TREND_SOURCES:
        multiplier += 0.32
        reasons.append("authorized_trend")
    elif source == "search_recommend":
        multiplier += 0.22
        reasons.append("search_recommend")
    elif source == "search_phrase":
        multiplier += 0.24
        reasons.append("search_discovery")
    elif source == "search_token":
        multiplier += 0.12
        reasons.append("search_discovery")
    elif source == "homefeed_phrase":
        multiplier += 0.28
        reasons.append("phrase")
    elif source == "cloud_snapshot":
        multiplier += 0.10
        reasons.append("cloud_snapshot")
    elif source == BASELINE_EVIDENCE_SOURCE:
        multiplier += 0.02
        reasons.append("industry_baseline")
    if hint_hit:
        multiplier += 0.22
        reasons.append("domain_hint")
    if phrase:
        multiplier += 0.15
        reasons.append("phrase_len")
    if count_value >= 2:
        multiplier += 0.08
        reasons.append("repeated")
    if kw in _GENERIC_KEYWORDS:
        multiplier *= 0.55
        reasons.append("generic_downrank")

    score = 25
    if source == "hot_search":
        score += 40
    elif source in AUTHORIZED_TREND_SOURCES:
        score += 38
    elif source == "cloud_snapshot":
        score += 25
    elif source == "search_recommend":
        score += 24
    elif source == "search_phrase":
        score += 22
    elif source == "search_token":
        score += 14
    elif source == "homefeed_phrase":
        score += 14
    elif source == BASELINE_EVIDENCE_SOURCE:
        score += 6
    else:
        score += 6
    if hint_hit:
        score += 24
    if phrase:
        score += 8
    if count_value >= 2:
        score += 8
    if count_value >= 4:
        score += 8
    if count_value >= 8:
        score += 4
    if source == "homefeed_phrase" and count_value < 2 and source != "hot_search":
        score -= 14
    if kw in _GENERIC_KEYWORDS:
        score -= 18
    if weak_useful and count_value < 4:
        score -= 8
    quality_score = int(min(max(score, 5), 100))
    evidence_level = "strong" if quality_score >= 74 else "medium" if quality_score >= 55 else "weak"

    return {
        "keyword": kw,
        "keep": True,
        "multiplier": round(min(max(multiplier, 0.3), 1.8), 3),
        "reason": "+".join(reasons) or "accepted",
        "source_priority": _SOURCE_PRIORITY.get(source, 0),
        "is_phrase": phrase,
        "domain_hint": hint_hit,
        "quality_score": quality_score,
        "evidence_level": evidence_level,
    }


def clean_scraped_keyword_row(row: dict) -> dict | None:
    profile = keyword_quality_profile(
        row.get("keyword", ""),
        category=row.get("category") or row.get("domain") or "",
        source=row.get("source") or "homefeed",
        count=row.get("count", 1),
    )
    if not profile["keep"]:
        return None
    cleaned = dict(row)
    cleaned["keyword"] = profile["keyword"]
    cleaned["quality_reason"] = profile["reason"]
    cleaned["quality_multiplier"] = profile["multiplier"]
    cleaned["source_priority"] = profile["source_priority"]
    cleaned["quality_score"] = profile["quality_score"]
    cleaned["evidence_level"] = profile["evidence_level"]
    cleaned["sample_count"] = int(float(cleaned.get("count", 1) or 1))
    if "search_vol" in cleaned:
        cleaned["search_vol"] = max(5, min(95, int(float(cleaned.get("search_vol") or 50) * profile["multiplier"])))
    return cleaned


def baseline_evidence_rows(
    domains: list[str] | tuple[str, ...] | None = None,
    min_per_domain: int | None = None,
) -> list[dict]:
    """Return deterministic daily baseline rows for industry evidence packs.

    These rows are intentionally labelled `industry_baseline`: they keep the
    cloud pipeline fresh and industry-specific when public scraping is weak, but
    they must not be presented as platform hot search or official trend data.
    """
    target_domains = tuple(domains or CORE_EVIDENCE_DOMAINS)
    per_domain = max(1, int(min_per_domain or _min_domain_keywords()))
    rows: list[dict] = []
    for domain in target_domains:
        seeds = _DAILY_BASELINE_SEEDS.get(domain, ())
        seed_limit = min(len(seeds), per_domain + 4)
        for idx, keyword in enumerate(seeds[:seed_limit]):
            rows.append({
                "keyword": keyword,
                "search_vol": max(45, 64 - idx),
                "trend_dir": 0,
                "source": BASELINE_EVIDENCE_SOURCE,
                "category": domain,
                "count": 3,
            })
    return rows


def ensure_daily_evidence_pack(
    domains: list[str] | tuple[str, ...] | None = None,
    min_per_domain: int | None = None,
) -> dict:
    """Ensure every core industry has a fresh, labelled baseline evidence pack."""
    init_db()
    target_domains = tuple(domains or CORE_EVIDENCE_DOMAINS)
    generated_rows: list[dict] = []
    refreshed_domains: list[str] = []
    for domain in target_domains:
        status = db_status(domain)
        if status.get("has_fresh_domain_data"):
            continue
        rows = baseline_evidence_rows((domain,), min_per_domain=min_per_domain)
        if rows:
            generated_rows.extend(rows)
            refreshed_domains.append(domain)
    if generated_rows:
        upsert_keywords(generated_rows)
    return {
        "enabled": True,
        "source": BASELINE_EVIDENCE_SOURCE,
        "generated": len(generated_rows),
        "domains": refreshed_domains,
        "reason": "public_scrape_or_snapshot_insufficient; generated labelled industry baseline evidence",
    }


def _is_actionable_keyword(keyword: str) -> bool:
    return keyword_quality_profile(keyword).get("keep", False)


def _is_domain_relevant_keyword(domain: str, keyword: str) -> bool:
    return _domain_hint_hit(domain, keyword)


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

def _freshness_hours(latest_capture: str | None) -> float | None:
    if not latest_capture:
        return None
    try:
        captured = datetime.fromisoformat(str(latest_capture))
        return round((datetime.now() - captured).total_seconds() / 3600, 1)
    except Exception:
        return None


def _is_fresh(latest_capture: str | None, hours: int = FRESHNESS_MAX_HOURS) -> bool:
    freshness = _freshness_hours(latest_capture)
    return freshness is not None and freshness <= hours


def _min_domain_keywords() -> int:
    try:
        return max(1, int(os.environ.get("NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS", str(DEFAULT_MIN_DOMAIN_KEYWORDS)) or DEFAULT_MIN_DOMAIN_KEYWORDS))
    except Exception:
        return DEFAULT_MIN_DOMAIN_KEYWORDS


def _category_where(domain: str | None) -> tuple[str, list[str]]:
    categories = _domain_categories(domain)
    if not categories:
        return "", []
    return f" AND category IN ({','.join('?' for _ in categories)})", list(categories)


def get_top_keywords(
    limit: int = 300,
    hours: int = 24,
    domain: str | None = None,
    allow_stale_fallback: bool = False,
) -> list[dict]:
    """
    获取热词列表。优先取最近 hours 小时内的数据；
    生产报告默认不回退旧数据，避免把多天前样本当作今日市场时机证据。
    仅在离线审计/历史分析显式 allow_stale_fallback=True 时回退到最新可用日期。
    """
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    category_where, category_params = _category_where(domain)
    with _db_conn() as c:
        rows = c.execute(
            f"""
            SELECT keyword,
                   MAX(search_vol) vol,
                   MAX(trend_dir) trend_dir,
                   MAX(source) source,
                   MAX(category) category,
                   MAX(sample_count) sample_count,
                   MAX(quality_score) quality_score,
                   MAX(evidence_level) evidence_level,
                   MAX(quality_reason) quality_reason
            FROM hot_keywords
            WHERE captured_at > ?{category_where}
            GROUP BY keyword
            ORDER BY (quality_score*0.65 + vol*0.35 + trend_dir*5) DESC
            LIMIT ?
            """,
            (since, *category_params, limit),
        ).fetchall()

        if not rows and allow_stale_fallback:
            latest_date = c.execute(
                f"SELECT MAX(captured_date) FROM hot_keywords WHERE 1=1{category_where}",
                category_params,
            ).fetchone()[0]
            if latest_date:
                rows = c.execute(
                    f"""
                    SELECT keyword,
                           MAX(search_vol) vol,
                           MAX(trend_dir) trend_dir,
                           MAX(source) source,
                           MAX(category) category,
                           MAX(sample_count) sample_count,
                           MAX(quality_score) quality_score,
                           MAX(evidence_level) evidence_level,
                           MAX(quality_reason) quality_reason
                    FROM hot_keywords
                    WHERE captured_date = ?{category_where}
                    GROUP BY keyword
                    ORDER BY (quality_score*0.65 + vol*0.35 + trend_dir*5) DESC
                    LIMIT ?
                    """,
                    (latest_date, *category_params, limit),
                ).fetchall()

    return [dict(r) for r in rows]


def db_status(domain: str | None = None) -> dict:
    category_where, category_params = _category_where(domain)
    with _db_conn() as c:
        total = c.execute("SELECT COUNT(*) FROM hot_keywords").fetchone()[0]
        latest = c.execute(
            "SELECT captured_at FROM hot_keywords ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        sources = c.execute(
            "SELECT COALESCE(source, '') source, COUNT(*) n FROM hot_keywords GROUP BY source"
        ).fetchall()
        categories = c.execute(
            "SELECT COALESCE(category, '') category, COUNT(*) n, MAX(captured_at) latest_at "
            "FROM hot_keywords GROUP BY category ORDER BY n DESC"
        ).fetchall()
        domain_total = 0
        domain_qualified_total = 0
        domain_strong_total = 0
        domain_latest = None
        domain_sources = []
        if domain:
            domain_total = c.execute(
                f"SELECT COUNT(*) FROM hot_keywords WHERE 1=1{category_where}",
                category_params,
            ).fetchone()[0]
            domain_qualified_total = c.execute(
                f"SELECT COUNT(*) FROM hot_keywords WHERE quality_score >= 55{category_where}",
                category_params,
            ).fetchone()[0]
            domain_strong_total = c.execute(
                f"SELECT COUNT(*) FROM hot_keywords WHERE quality_score >= 74{category_where}",
                category_params,
            ).fetchone()[0]
            domain_latest = c.execute(
                f"SELECT captured_at FROM hot_keywords WHERE 1=1{category_where} ORDER BY captured_at DESC LIMIT 1",
                category_params,
            ).fetchone()
            domain_sources = c.execute(
                f"SELECT COALESCE(source, '') source, COUNT(*) n FROM hot_keywords WHERE 1=1{category_where} GROUP BY source",
                category_params,
            ).fetchall()
    latest_capture = latest[0] if latest else None
    domain_latest_capture = domain_latest[0] if domain_latest else None
    domain_freshness = _freshness_hours(domain_latest_capture)
    min_domain_keywords = _min_domain_keywords()
    return {
        "total_keywords": total,
        "latest_capture": latest_capture,
        "freshness_hours": _freshness_hours(latest_capture),
        "source_breakdown": {r["source"] or "unknown": int(r["n"]) for r in sources},
        "category_breakdown": {
            r["category"] or "unknown": {"count": int(r["n"]), "latest_capture": r["latest_at"]}
            for r in categories
        },
        "domain": domain or "",
        "domain_categories": list(_domain_categories(domain)),
        "domain_keyword_count": int(domain_total or 0),
        "domain_qualified_keyword_count": int(domain_qualified_total or 0),
        "domain_strong_keyword_count": int(domain_strong_total or 0),
        "market_timing_min_domain_keywords": min_domain_keywords,
        "domain_latest_capture": domain_latest_capture,
        "domain_freshness_hours": domain_freshness,
        "domain_source_breakdown": {r["source"] or "unknown": int(r["n"]) for r in domain_sources},
        "has_fresh_domain_data": bool(
            domain
            and _is_fresh(domain_latest_capture)
            and int(domain_qualified_total or 0) >= min_domain_keywords
        ),
    }


# ── Match ─────────────────────────────────────────────────────────────────────

def match_keywords(text: str, domain: str | None = None) -> list[dict]:
    """Find hot keywords present in the input text."""
    if not text:
        return []
    top = get_top_keywords(limit=500, domain=domain, hours=FRESHNESS_MAX_HOURS)
    index = {k["keyword"]: k for k in top if _is_actionable_keyword(k.get("keyword", ""))}
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

    return sorted(
        matched.values(),
        key=lambda x: (int(x.get("quality_score", 0) or 0), int(x.get("vol", 0) or 0)),
        reverse=True,
    )


# ── Market timing features ────────────────────────────────────────────────────

def _baseline_source_note(source_breakdown: dict | None) -> str:
    sources = {str(k) for k, v in (source_breakdown or {}).items() if int(v or 0) > 0}
    if sources and sources <= {BASELINE_EVIDENCE_SOURCE}:
        return "当前证据来自每日行业基线包，用于保证行业覆盖，不代表平台官方热搜。"
    if BASELINE_EVIDENCE_SOURCE in sources:
        return "含每日行业基线证据；公开抓取样本不足时仅作选题参考，不代表平台官方热搜。"
    return ""


def compute_market_timing(title: str, desc: str, domain: str) -> dict:
    """
    Compute market timing features + timing_coefficient + keyword suggestions.
    Used by /analyze to inject trend context into Claude prompt.
    """
    full_text = f"{title} {desc}"
    refresh_info = ensure_fresh_domain_keywords(domain, trigger_refresh=True) if domain else {"ok": False, "status": db_status(domain)}
    status = refresh_info.get("status") or db_status(domain)
    latest_capture = status.get("domain_latest_capture") or status.get("latest_capture")
    freshness_hours = status.get("domain_freshness_hours")
    source_note = _baseline_source_note(status.get("domain_source_breakdown", {}))
    if domain and not status.get("has_fresh_domain_data"):
        domain_stats = get_domain_stats(domain)
        qualified_count = int(status.get("domain_qualified_keyword_count", 0) or 0)
        min_required = int(status.get("market_timing_min_domain_keywords", _min_domain_keywords()) or _min_domain_keywords())
        if freshness_hours is None:
            stale_note = f"今日「{domain}」热词尚未采集成功，市场时机证据已停用。"
        elif qualified_count < min_required:
            stale_note = (
                f"今日「{domain}」中等以上热词证据仅 {qualified_count}/{min_required} 条，"
                "未达到可交付样本量，市场时机证据已停用。"
            )
        else:
            stale_note = (
                f"「{domain}」热词距最近采集约 {float(freshness_hours):.1f} 小时，"
                "超过每日更新标准，市场时机证据已停用。"
            )
        return {
            "keyword_search_vol":  0.0,
            "trend_momentum":      0.0,
            "is_trending_topic":   0.0,
            "content_freshness":   0.0,
            "category_saturation": round(domain_stats["saturation"], 3),
            "category_avg_ces":    round(domain_stats["avg_ces"], 1),
            "keyword_competition": 0.0,
            "trend_peak_distance": 0.0,
            "timing_coefficient":  1.0,
            "domain":              domain or "",
            "matched_keywords":    [],
            "suggested_keywords":  [],
            "matched_keyword_evidence": [],
            "suggested_keyword_evidence": [],
            "keyword_count":        int(status.get("domain_keyword_count", 0) or 0),
            "latest_capture":       latest_capture,
            "source_breakdown":     status.get("domain_source_breakdown", {}),
            "freshness_hours":      freshness_hours,
            "data_source_label":    f"{domain}每日热词样本库",
            "data_stale":           True,
            "evidence_required":     True,
            "evidence_unavailable":  True,
            "cloud_sync":            refresh_info.get("sync_result", {}),
            "freshness_policy":     f"要求 {FRESHNESS_MAX_HOURS} 小时内有行业采集样本",
            "domain_latest_capture": latest_capture,
            "domain_keyword_count": int(status.get("domain_keyword_count", 0) or 0),
            "domain_qualified_keyword_count": qualified_count,
            "domain_strong_keyword_count": int(status.get("domain_strong_keyword_count", 0) or 0),
            "market_timing_min_domain_keywords": min_required,
            "evidence_quality_note": stale_note,
            "confidence_note":      stale_note,
            "timing_note":          stale_note,
            "timing_action":        "stale",
        }

    matched = match_keywords(full_text, domain)
    all_top = [
        k for k in get_top_keywords(limit=120, domain=domain, hours=FRESHNESS_MAX_HOURS)
        if _is_actionable_keyword(k.get("keyword", "")) and int(k.get("quality_score", 0) or 0) >= 55
    ][:30]
    domain_top = [k for k in all_top if _is_domain_relevant_keyword(domain, k.get("keyword", ""))]
    matched_set = {k["keyword"] for k in matched}

    def evidence_rows(rows: list[dict], limit: int = 8) -> list[dict]:
        out = []
        for row in rows[:limit]:
            out.append({
                "keyword": row.get("keyword", ""),
                "search_vol": int(row.get("vol", row.get("search_vol", 0)) or 0),
                "trend_dir": int(row.get("trend_dir", 0) or 0),
                "source": row.get("source", "") or "unknown",
                "category": row.get("category", "") or "",
                "sample_count": int(row.get("sample_count", 1) or 1),
                "quality_score": int(row.get("quality_score", 0) or 0),
                "evidence_level": row.get("evidence_level", "") or "weak",
                "quality_reason": row.get("quality_reason", "") or "",
            })
        return out

    domain_stats = get_domain_stats(domain)

    if not matched:
        suggested = [k["keyword"] for k in domain_top[:6]]
        return {
            "keyword_search_vol":  0.0,
            "trend_momentum":      0.0,
            "is_trending_topic":   0.0,
            "content_freshness":   0.5,
            "category_saturation": round(domain_stats["saturation"], 3),
            "category_avg_ces":    round(domain_stats["avg_ces"], 1),
            "keyword_competition": 0.5,
            "trend_peak_distance": 0.0,
            "timing_coefficient":  1.0,
            "domain":              domain or "",
            "matched_keywords":    [],
            "suggested_keywords":  suggested,
            "matched_keyword_evidence": [],
            "suggested_keyword_evidence": evidence_rows(domain_top[:6], 6),
            "keyword_count":        int(status.get("domain_keyword_count", 0) or 0),
            "latest_capture":       latest_capture,
            "source_breakdown":     status.get("domain_source_breakdown", {}),
            "freshness_hours":      freshness_hours,
            "data_source_label":    f"{domain}每日热词样本库" if domain else "本地热词样本库",
            "data_stale":           False,
            "evidence_required":     True,
            "evidence_unavailable":  False,
            "cloud_sync":            refresh_info.get("sync_result", {}),
            "freshness_policy":     f"要求 {FRESHNESS_MAX_HOURS} 小时内有行业采集样本",
            "domain_latest_capture": latest_capture,
            "domain_keyword_count": int(status.get("domain_keyword_count", 0) or 0),
            "domain_qualified_keyword_count": int(status.get("domain_qualified_keyword_count", 0) or 0),
            "domain_strong_keyword_count": int(status.get("domain_strong_keyword_count", 0) or 0),
            "market_timing_min_domain_keywords": int(status.get("market_timing_min_domain_keywords", _min_domain_keywords()) or _min_domain_keywords()),
            "evidence_quality_note": "有新鲜行业样本，但当前内容未命中强相关词；建议只把趋势词作为选题参考。" + (f" {source_note}" if source_note else ""),
            "confidence_note":      "有新鲜行业样本，但当前内容未命中强相关词；建议只把趋势词作为选题参考。" + (f" {source_note}" if source_note else ""),
            "timing_note":         "未命中与当前品类高度相关的热词证据" if not suggested else "未命中近期热词，可参考下方品类相关词",
            "timing_action":       "suggest",
        }

    max_vol        = max(k.get("vol", 50) for k in matched) / 100.0
    rising         = sum(1 for k in matched if k.get("trend_dir", 0) == 1)
    trend_momentum = rising / len(matched)
    is_trending    = float(any(k.get("source") == "hot_search" or k.get("source") in AUTHORIZED_TREND_SOURCES for k in matched))
    quality_values = [int(k.get("quality_score", 50) or 50) / 100.0 for k in matched]
    avg_quality    = sum(quality_values) / len(quality_values) if quality_values else 0.5
    strong_count   = sum(1 for k in matched if int(k.get("quality_score", 0) or 0) >= 74)
    content_freshness   = min(0.5 + trend_momentum * 0.5, 1.0)
    keyword_competition = max_vol * 0.8

    # trend_peak_distance: average across matched keywords (0.0 if insufficient snapshots)
    peak_distances = [compute_trend_peak_distance(k["keyword"]) for k in matched[:5]]
    trend_peak_distance = round(sum(peak_distances) / len(peak_distances), 1) if peak_distances else 0.0

    timing_coefficient = (
        0.95
        + max_vol             * 0.12
        + trend_momentum      * 0.10
        + is_trending         * 0.12
        + avg_quality         * 0.08
        - keyword_competition * 0.06
    )
    timing_coefficient = round(min(max(timing_coefficient, 0.6), 1.4), 3)
    if not is_trending and strong_count == 0:
        timing_coefficient = min(timing_coefficient, 1.05)
    elif not is_trending:
        timing_coefficient = min(timing_coefficient, 1.15)
    timing_coefficient = round(timing_coefficient, 3)

    matched_names = [k["keyword"] for k in matched[:8]]

    # Suggest complementary hot keywords not yet in the content
    suggested = [k["keyword"] for k in domain_top if k["keyword"] not in matched_set][:5]

    # Human-readable note
    rising_kws = [k["keyword"] for k in matched if k.get("trend_dir") == 1][:3]
    hot_kws    = [k["keyword"] for k in matched if k.get("source") == "hot_search" or k.get("source") in AUTHORIZED_TREND_SOURCES][:3]
    parts = []
    if hot_kws:
        parts.append(f"命中高置信趋势词：{'、'.join(hot_kws)}")
    if rising_kws:
        parts.append(f"上升趋势词：{'、'.join(rising_kws)}")
    if not parts:
        parts.append(f"命中热词：{'、'.join(matched_names[:3])}")
    if suggested:
        parts.append(f"建议补充：{'、'.join(suggested[:3])}")
    evidence_quality_note = (
        f"命中 {len(matched)} 个当前行业热词，其中强证据 {strong_count} 个；"
        f"平均证据质量 {round(avg_quality * 100)} 分。"
    )
    if source_note:
        evidence_quality_note = f"{evidence_quality_note} {source_note}"

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
        "domain":              domain or "",
        "matched_keywords":    matched_names,
        "suggested_keywords":  suggested,
        "matched_keyword_evidence": evidence_rows(matched, 8),
        "suggested_keyword_evidence": evidence_rows([k for k in domain_top if k["keyword"] not in matched_set], 5),
        "keyword_count":        int(status.get("domain_keyword_count", 0) or 0),
        "latest_capture":       latest_capture,
        "source_breakdown":     status.get("domain_source_breakdown", {}),
        "freshness_hours":      freshness_hours,
        "data_source_label":    f"{domain}每日热词样本库" if domain else "本地热词样本库",
        "data_stale":           False,
        "evidence_required":     True,
        "evidence_unavailable":  False,
        "cloud_sync":            refresh_info.get("sync_result", {}),
        "freshness_policy":     f"要求 {FRESHNESS_MAX_HOURS} 小时内有行业采集样本",
        "domain_latest_capture": latest_capture,
        "domain_keyword_count": int(status.get("domain_keyword_count", 0) or 0),
        "domain_qualified_keyword_count": int(status.get("domain_qualified_keyword_count", 0) or 0),
        "domain_strong_keyword_count": int(status.get("domain_strong_keyword_count", 0) or 0),
        "market_timing_min_domain_keywords": int(status.get("market_timing_min_domain_keywords", _min_domain_keywords()) or _min_domain_keywords()),
        "evidence_quality_note": evidence_quality_note,
        "confidence_note": evidence_quality_note,
        "timing_note":         "；".join(parts),
        "timing_action":       "reinforce",
    }
