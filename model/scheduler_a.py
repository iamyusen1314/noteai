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
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

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

# 覆盖全部主流品类，确保热词多样性
CHANNELS = [
    ("https://www.xiaohongshu.com/explore", "综合"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.food_v3",       "美食"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.travel_v3",     "旅行"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.fashion_v3",    "穿搭"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.fitness_v3",    "运动"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.career_v3",     "职场"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.love_v3",       "情感"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.movie_and_tv_v3","影视"),
]

# 尝试拦截的热搜/建议 API 关键词（路径片段匹配）
HOT_API_PATTERNS = [
    "hot_list", "hot_search", "trending", "search/keyword",
    "suggest", "hot_words", "search_recommend",
]


def _get_session_state():
    if STATE_PATH.exists():
        return str(STATE_PATH)
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


async def scrape_once() -> list[dict]:
    """
    单次抓取：
    1. 遍历8个品类 channel，拦截 homefeed tag_list 统计词频
    2. 同时拦截热搜/建议 API（有 session 时命中概率更高）
    返回 keywords list，每项包含 keyword/search_vol/trend_dir/source/count
    """
    from playwright.async_api import async_playwright
    from hot_keywords import compute_trend_dir

    state = _get_session_state()
    tag_counter: Counter = Counter()
    hot_search_kws: list[str] = []

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

        async def on_response(resp):
            url = resp.url

            # 尝试拦截热搜 API
            if any(p in url for p in HOT_API_PATTERNS):
                try:
                    data = await resp.json()
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
                            hot_search_kws.append(kw)
                except Exception:
                    pass

            # 拦截 homefeed：从 display_title 用 jieba 提词
            # 注：XHS homefeed 已不返回 tag_list，改用标题关键词提取
            if "homefeed" in url:
                try:
                    import jieba
                    data = await resp.json()
                    for item in data.get("data", {}).get("items", []):
                        nc = item.get("note_card", {})
                        title = nc.get("display_title", "").strip()
                        if not title:
                            continue
                        # 整个标题作为一个整体词（捕捉短语热词）
                        if len(title) >= 2:
                            tag_counter[title[:20]] += 1
                        # jieba 分词，保留 2-8 字的词
                        for token in jieba.cut(title):
                            token = token.strip()
                            if 2 <= len(token) <= 8:
                                tag_counter[token] += 1
                except Exception:
                    pass

        # 遍历所有 channel
        for channel_url, channel_name in CHANNELS:
            page = await ctx.new_page()
            page.on("response", on_response)
            try:
                await page.goto(channel_url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(3.0)
                for _ in range(8):
                    await page.evaluate("window.scrollBy(0, 700)")
                    await asyncio.sleep(1.0)
            except Exception as e:
                log.warning(f"Channel {channel_name} error: {e}")
            finally:
                await page.close()

        await ctx.close()
        await browser.close()

    # ── 构建结果 ──────────────────────────────────────────────────────────────
    results: list[dict] = []

    # 来自热搜 API 的词（最高权重）
    seen = set()
    for kw in hot_search_kws:
        if kw not in seen:
            seen.add(kw)
            results.append({
                "keyword":    kw,
                "search_vol": 90,
                "trend_dir":  1,
                "source":     "hot_search",
                "count":      99,
            })

    # 来自 homefeed tag_list（按词频计算相对热度）
    total = sum(tag_counter.values()) or 1
    for kw, count in tag_counter.most_common(200):
        if len(kw) < 2 or kw in seen:
            continue
        seen.add(kw)
        vol = max(min(int(count / total * 10000), 95), 5)
        results.append({
            "keyword":    kw,
            "search_vol": vol,
            "trend_dir":  compute_trend_dir(kw),
            "source":     "homefeed",
            "count":      count,
        })

    log.info(
        f"Scraped {len(results)} keywords "
        f"({len(seen - {r['keyword'] for r in results if r['source']!='hot_search'})} homefeed, "
        f"{len(hot_search_kws)} hot_search)"
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
