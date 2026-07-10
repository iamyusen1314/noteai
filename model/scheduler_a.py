"""
NoteAI Pro — Scheduler A: XHS Hot Keywords Scraper
每60分钟抓取一次 XHS 热词，写入 hot_keywords.db。
无需账号即可运行（从 homefeed tag_list 提取）；有 session 时额外尝试热搜 API。

用法：
  python3 scheduler_a.py              # 单次测试运行
  python3 scheduler_a.py --daemon     # 持续后台运行（开发调试用）
  # 生产：由 api.py 启动时调用 start_scheduler()
"""
import argparse
import asyncio
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import runtime_settings

BASE_DIR = Path(__file__).parent
STATE_PATH  = BASE_DIR / "data/xhs_state.json"
COOKIES_PATH = BASE_DIR / "data/xhs_cookies.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler_a] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scheduler_a")

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SCROLL_ROUNDS = int(os.environ.get("NOTEAI_XHS_SCROLL_ROUNDS", "10") or 10)
SCROLL_WAIT_SECONDS = float(os.environ.get("NOTEAI_XHS_SCROLL_WAIT_SECONDS", "1.0") or 1.0)
CHANNEL_SETTLE_SECONDS = float(os.environ.get("NOTEAI_XHS_CHANNEL_SETTLE_SECONDS", "3.0") or 3.0)
SEARCH_DISCOVERY_ENABLED = os.environ.get("NOTEAI_XHS_SEARCH_DISCOVERY", "1").strip().lower() not in {"0", "false", "no"}
SEARCH_SEEDS_PER_CATEGORY = int(os.environ.get("NOTEAI_XHS_SEARCH_SEEDS_PER_CATEGORY", "2") or 2)
SEARCH_SCROLL_ROUNDS = int(os.environ.get("NOTEAI_XHS_SEARCH_SCROLL_ROUNDS", "3") or 3)
SEARCH_SETTLE_SECONDS = float(os.environ.get("NOTEAI_XHS_SEARCH_SETTLE_SECONDS", "2.0") or 2.0)

# 覆盖全部主流品类，确保热词多样性
CHANNELS = [
    ("https://www.xiaohongshu.com/explore", "综合"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.food_v3",       "美食"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.travel_v3",     "旅行"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.fashion_v3",    "穿搭"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3",  "美妆"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.household_product_v3", "家居"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.fitness_v3",    "健身"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.career_v3",     "职场"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.love_v3",       "情感"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.movie_and_tv_v3","影视"),
]

SEARCH_SEEDS = {
    "美食": ("美食探店", "餐厅推荐", "粤菜探店", "小吃宵夜"),
    "旅行": ("旅行攻略", "酒店推荐", "周末旅行", "亲子酒店"),
    "穿搭": ("夏季穿搭", "通勤穿搭", "小个子穿搭", "显瘦穿搭"),
    "美妆": ("夏季底妆", "美甲款式", "防晒推荐", "妆容教程"),
    "家居": ("装修避坑", "家居收纳", "厨房装修", "客厅改造"),
    "健身": ("减肥训练", "普拉提塑形", "燃脂训练", "居家健身"),
}

# 尝试拦截的热搜/建议 API 关键词（路径片段匹配）
HOT_API_PATTERNS = [
    "hot_list", "hot_search", "trending", "search/keyword",
    "suggest", "hot_words", "search_recommend", "search/recommend",
]


def _source_weight(source: str) -> float:
    if source in {"homefeed_phrase", "search_phrase"}:
        return 2.5
    if source == "search_token":
        return 1.35
    return 1.0


def _get_session_state():
    if STATE_PATH.exists():
        return str(STATE_PATH)
    stored = runtime_settings.get_json("xhs_cookies", [])
    if isinstance(stored, list) and stored:
        cookies = [dict(cookie) for cookie in stored]
        for cookie in cookies:
            if "domain" not in cookie:
                cookie["domain"] = ".xiaohongshu.com"
        return {"cookies": cookies, "origins": []}
    if COOKIES_PATH.exists():
        with open(COOKIES_PATH) as f:
            cookies = json.load(f)
        for c in cookies:
            if "domain" not in c:
                c["domain"] = ".xiaohongshu.com"
        return {"cookies": cookies, "origins": []}
    return None


def _extract_keyword_from_item(item: dict) -> str | None:
    for key in ("keyword", "word", "name", "text", "title"):
        v = item.get(key)
        if v and isinstance(v, str) and len(v) >= 2:
            return v.strip()
    return None


def _extract_note_titles(payload) -> list[str]:
    titles: list[str] = []

    def walk(value):
        if isinstance(value, dict):
            for key in ("display_title", "title"):
                title = value.get(key)
                if isinstance(title, str) and title.strip():
                    titles.append(title.strip())
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(payload)
    return titles


def _title_phrase_candidates(title: str) -> list[str]:
    title = re.sub(r"#([^#\s]+)", r" \1 ", title or "")
    title = re.sub(r"[\u200b-\u200f\ufeff]", "", title)
    parts = re.split(r"[\s｜|/\\，。！？、；：,.!?;:「」『』【】\[\]()（）<>《》]+", title)
    phrases: list[str] = []
    for part in parts:
        part = part.strip()
        if 5 <= len(part) <= 24:
            phrases.append(part)
        elif len(part) > 24:
            phrases.append(part[:24])
    return phrases[:4]


def _keep_best_candidate(best: dict[tuple[str, str], dict], row: dict) -> None:
    key = (row.get("category", ""), row.get("keyword", ""))
    current = best.get(key)
    if not current:
        best[key] = row
        return
    current_rank = (current.get("source_priority", 0), current.get("search_vol", 0), current.get("count", 0))
    row_rank = (row.get("source_priority", 0), row.get("search_vol", 0), row.get("count", 0))
    if row_rank > current_rank:
        best[key] = row


def _search_url(seed: str) -> str:
    return f"https://www.xiaohongshu.com/search_result?keyword={quote(seed)}&source=web_explore_feed"


def _search_discovery_targets() -> list[tuple[str, str]]:
    if not SEARCH_DISCOVERY_ENABLED:
        return []
    targets: list[tuple[str, str]] = []
    limit = max(0, SEARCH_SEEDS_PER_CATEGORY)
    for category, seeds in SEARCH_SEEDS.items():
        for seed in seeds[:limit]:
            targets.append((_search_url(seed), category))
    return targets


async def scrape_once() -> list[dict]:
    """
    单次抓取：
    1. 遍历8个品类 channel，拦截 homefeed tag_list 统计词频
    2. 同时拦截热搜/建议 API（有 session 时命中概率更高）
    返回 keywords list，每项包含 keyword/search_vol/trend_dir/source/count
    """
    from playwright.async_api import async_playwright
    from hot_keywords import clean_scraped_keyword_row, compute_trend_dir

    state = _get_session_state()
    tag_counters: dict[str, Counter] = {name: Counter() for _, name in CHANNELS}
    hot_search_kws: dict[str, list[str]] = {name: [] for _, name in CHANNELS}
    search_recommend_kws: dict[str, list[str]] = {name: [] for name in SEARCH_SEEDS}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx_kwargs = dict(
            user_agent=BROWSER_UA,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        if state:
            ctx_kwargs["storage_state"] = state

        ctx = await browser.new_context(**ctx_kwargs)
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        def make_on_response(channel_name: str, discovery_source: str):
            async def on_response(resp):
                url = resp.url

                # 尝试拦截热搜 API
                if any(p in url for p in HOT_API_PATTERNS):
                    try:
                        data = await resp.json()
                        if "search/recommend" in url:
                            for item in data.get("data", {}).get("sug_items", []) or []:
                                kw = _extract_keyword_from_item(item) if isinstance(item, dict) else None
                                if kw:
                                    search_recommend_kws.setdefault(channel_name, []).append(kw)
                            return
                        # 尝试常见结构
                        candidates = (
                            data.get("data", {}).get("items", [])
                            or data.get("data", {}).get("keywords", [])
                            or (data.get("data") if isinstance(data.get("data"), list) else [])
                            or data.get("items", [])
                        )
                        for item in candidates:
                            kw = _extract_keyword_from_item(item) if isinstance(item, dict) else (
                                item if isinstance(item, str) else None
                            )
                            if kw:
                                hot_search_kws.setdefault(channel_name, []).append(kw)
                    except Exception:
                        pass

                should_extract_titles = (
                    ("homefeed" in url and discovery_source == "homefeed")
                    or (discovery_source == "search_discovery" and ("search" in url or "api" in url))
                )
                if should_extract_titles:
                    try:
                        import jieba
                        data = await resp.json()
                        counter = tag_counters.setdefault(channel_name, Counter())
                        for title in _extract_note_titles(data):
                            if not title:
                                continue
                            # 标题短语优先：比单词更能反映真实内容趋势。
                            for phrase in _title_phrase_candidates(title):
                                source = "search_phrase" if discovery_source == "search_discovery" else "homefeed_phrase"
                                counter[(phrase, source)] += 1
                            # jieba 分词作为补充，后续会按行业相关度清洗。
                            for token in jieba.cut(title):
                                token = token.strip()
                                if 2 <= len(token) <= 8:
                                    source = "search_token" if discovery_source == "search_discovery" else "homefeed_token"
                                    counter[(token, source)] += 1
                    except Exception:
                        pass
            return on_response

        # 遍历所有 channel
        for channel_url, channel_name in CHANNELS:
            page = await ctx.new_page()
            page.on("response", make_on_response(channel_name, "homefeed"))
            try:
                await page.goto(channel_url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(CHANNEL_SETTLE_SECONDS)
                for _ in range(max(1, SCROLL_ROUNDS)):
                    await page.evaluate("window.scrollBy(0, 700)")
                    await asyncio.sleep(max(0.2, SCROLL_WAIT_SECONDS))
            except Exception as e:
                log.warning(f"Channel {channel_name} error: {e}")
            finally:
                await page.close()

        for search_url, channel_name in _search_discovery_targets():
            page = await ctx.new_page()
            page.on("response", make_on_response(channel_name, "search_discovery"))
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(SEARCH_SETTLE_SECONDS)
                for _ in range(max(1, SEARCH_SCROLL_ROUNDS)):
                    await page.evaluate("window.scrollBy(0, 700)")
                    await asyncio.sleep(max(0.2, SCROLL_WAIT_SECONDS))
            except Exception as e:
                log.warning(f"Search discovery {channel_name} error: {e}")
            finally:
                await page.close()

        await ctx.close()
        await browser.close()

    # ── 构建结果 ──────────────────────────────────────────────────────────────
    best_results: dict[tuple[str, str], dict] = {}

    # 来自热搜 API 的词（最高权重）
    seen: set[tuple[str, str]] = set()
    for category, kws in hot_search_kws.items():
        for kw in kws:
            key = (category, kw)
            if key not in seen:
                seen.add(key)
                row = clean_scraped_keyword_row({
                    "keyword":    kw,
                    "search_vol": 90,
                    "trend_dir":  1,
                    "source":     "hot_search",
                    "category":   category,
                    "count":      99,
                })
                if row:
                    _keep_best_candidate(best_results, row)

    # 来自搜索推荐词：不等同热搜，但比普通 homefeed 更接近用户主动搜索意图。
    for category, kws in search_recommend_kws.items():
        for kw in kws:
            key = (category, kw)
            if key in seen:
                continue
            seen.add(key)
            row = clean_scraped_keyword_row({
                "keyword":    kw,
                "search_vol": 86,
                "trend_dir":  1,
                "source":     "search_recommend",
                "category":   category,
                "count":      6,
            })
            if row:
                _keep_best_candidate(best_results, row)

    # 来自 homefeed 标题短语/分词（按词频和质量权重计算相对热度）
    for category, tag_counter in tag_counters.items():
        total = sum(
            count * _source_weight(source)
            for (_, source), count in tag_counter.items()
        ) or 1
        for (kw, source), count in tag_counter.most_common(300):
            key = (category, kw)
            if len(kw) < 2 or key in seen:
                continue
            weighted_count = count * _source_weight(source)
            vol = max(min(int(weighted_count / total * 12000), 95), 5)
            row = clean_scraped_keyword_row({
                "keyword":    kw,
                "search_vol": vol,
                "trend_dir":  compute_trend_dir(kw),
                "source":     source,
                "category":   category,
                "count":      count,
            })
            if not row:
                continue
            _keep_best_candidate(best_results, row)

    results = sorted(
        best_results.values(),
        key=lambda r: (r.get("category", ""), -int(r.get("search_vol", 0)), -int(r.get("source_priority", 0))),
    )
    unique_homefeed_count = sum(1 for row in results if row.get("source") not in {"hot_search", "search_recommend"})
    unique_hot_count = sum(1 for row in results if row.get("source") == "hot_search")
    unique_recommend_count = sum(1 for row in results if row.get("source") == "search_recommend")
    log.info(
        f"Scraped {len(results)} keywords "
        f"({unique_homefeed_count} homefeed, {unique_recommend_count} search_recommend, {unique_hot_count} hot_search)"
    )
    return results


# ── Scheduler ─────────────────────────────────────────────────────────────────

_scheduler = None


def run_scrape_job():
    """APScheduler 调用的同步入口。"""
    try:
        log.info(f"Scrape job started at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        t0 = time.time()
        from hot_keywords import upsert_keywords
        kws = asyncio.run(scrape_once())
        if kws:
            upsert_keywords(kws)
            log.info(f"Saved {len(kws)} keywords in {time.time()-t0:.1f}s")
        else:
            log.warning("No keywords scraped this run")
    except Exception as e:
        log.error(f"Scrape job failed: {e}", exc_info=True)


def start_scheduler(interval_minutes: int = 60):
    """
    启动后台调度器。在 api.py startup 时调用一次。
    立即执行一次 + 之后每 interval_minutes 分钟执行。
    """
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from hot_keywords import init_db

    init_db()
    log.info("Running initial scrape on startup...")
    run_scrape_job()

    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        run_scrape_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="scheduler_a",
        name="XHS Hot Keywords",
        replace_existing=True,
    )
    _scheduler.start()
    log.info(f"Scheduler A started — interval: {interval_minutes} min")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="持续运行（每60分钟）")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()

    from hot_keywords import init_db, db_status, DB_PATH
    init_db()

    if args.daemon:
        start_scheduler(args.interval)
        print(f"Scheduler A running every {args.interval} min. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            stop_scheduler()
    else:
        # 单次测试
        kws = asyncio.run(scrape_once())
        print(f"\n{'='*50}")
        print(f"Total: {len(kws)} keywords")
        print("\nTop 30 by search_vol:")
        for k in sorted(kws, key=lambda x: x["search_vol"], reverse=True)[:30]:
            trend = {1: "↑", 0: "→", -1: "↓"}.get(k["trend_dir"], "?")
            print(f"  {trend} [{k['search_vol']:3d}] {k['keyword']}  ({k['source']})")
        from hot_keywords import upsert_keywords
        upsert_keywords(kws)
        print(f"\nSaved to {DB_PATH}")
        print(f"DB status: {db_status()}")
