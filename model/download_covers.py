"""
NoteAI Pro — XHS Cover Image Collector

Confirmed working approach:
  1. Authenticate via Playwright with saved cookies
  2. Browse XHS explore page + scroll to trigger homefeed API calls
  3. Intercept homefeed JSON responses → extract (note_id, cover_url, liked_count)
  4. Download cover images directly from XHS CDN (no per-note page visit)

Output:
  data/covers/{note_id}.jpg        cover images (~40-100 KB each)
  data/cover_metadata.jsonl        note_id, liked_count per line

Usage:
  python3 download_covers.py --login              # save session (run once)
  python3 download_covers.py --collect 10000      # collect 10k covers
  python3 download_covers.py --collect 100        # small test run
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Optional
import aiohttp

from chromium_security import launch_chromium_async
import runtime_settings

BASE_DIR = Path(__file__).parent

# Defaults (overridden by --run-id)
COVER_DIR = BASE_DIR / "data/covers"
METADATA_PATH = BASE_DIR / "data/cover_metadata.jsonl"
CHECKPOINT_PATH = BASE_DIR / "data/cover_checkpoint.json"


def set_run_paths(run_id: str):
    global COVER_DIR, METADATA_PATH, CHECKPOINT_PATH
    suffix = f"_{run_id}" if run_id != "v1" else ""
    COVER_DIR = BASE_DIR / f"data/covers{suffix}"
    METADATA_PATH = BASE_DIR / f"data/cover_metadata{suffix}.jsonl"
    CHECKPOINT_PATH = BASE_DIR / f"data/cover_checkpoint{suffix}.json"
    COVER_DIR.mkdir(parents=True, exist_ok=True)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# XHS explore channel URLs for category diversity
CHANNELS = [
    ("https://www.xiaohongshu.com/explore", "综合"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.fashion_v3", "穿搭"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.food_v3", "美食"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.travel_v3", "旅行"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.fitness_v3", "运动健康"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.movie_and_tv_v3", "影视"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.career_v3", "职场"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.love_v3", "情感"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.household_product_v3", "家居"),
    ("https://www.xiaohongshu.com/explore?channel_id=homefeed.gaming_v3", "游戏"),
]


# ── Login ──────────────────────────────────────────────────────────────────────

def do_login():
    raise RuntimeError(
        "明文登录态文件已禁用；请通过受管 Secret 注入 NOTEAI_XHS_COOKIES_JSON"
    )


def get_session_state():
    cookies = runtime_settings.get_json("xhs_cookies", [])
    if isinstance(cookies, list) and cookies:
        cookies = [dict(cookie) for cookie in cookies]
        for c in cookies:
            if "domain" not in c:
                c["domain"] = ".xiaohongshu.com"
        return {"cookies": cookies, "origins": []}
    return None


# ── Checkpoint ─────────────────────────────────────────────────────────────────

def load_done() -> set:
    done = set()
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            done.update(json.load(f))
    done.update(p.stem for p in COVER_DIR.glob("*.jpg"))
    return done



def save_done(done: set):
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(list(done), f)


# ── Extract covers from homefeed API response ─────────────────────────────────

def _to_int(v) -> int:
    try:
        return int(v) if v else 0
    except (ValueError, TypeError):
        return 0


def parse_homefeed(data: dict) -> list[dict]:
    from datetime import datetime
    notes = []
    items = data.get("data", {}).get("items", [])
    for item in items:
        note_id = item.get("id", "")
        if not note_id or len(note_id) != 24:
            continue
        nc = item.get("note_card", {})
        info_list = nc.get("cover", {}).get("info_list", [])
        # Prefer WB_DFT (web default = full quality), fallback to last entry
        cover_url = next(
            (x["url"] for x in info_list if x.get("image_scene") == "WB_DFT"),
            info_list[-1]["url"] if info_list else "",
        )
        if not cover_url or not cover_url.startswith("http"):
            continue

        # Engagement
        interact = nc.get("interact_info", {})
        liked = _to_int(interact.get("liked_count", 0))
        collected = _to_int(interact.get("collected_count", 0))
        comments = _to_int(interact.get("comment_count", 0))

        # Text fields
        title = nc.get("display_title", "") or nc.get("title", "") or ""
        desc = nc.get("desc", "") or ""
        tag_list = nc.get("tag_list", []) or []
        tags_str = "".join(
            f"#{t.get('name', '')}[话题]#" for t in tag_list if t.get("name")
        )
        if tags_str:
            desc = desc + " " + tags_str

        # Timestamp (milliseconds → YYYYMMDDhh)
        ts_ms = nc.get("time", 0)
        try:
            local_time = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y%m%d%H")
        except Exception:
            local_time = "2024010112"

        notes.append({
            "note_id": note_id,
            "cover_url": cover_url,
            "liked_count": liked,
            "collected_count": collected,
            "comments_count": comments,
            "note_title": title,
            "desc": desc,
            "local_time": local_time,
        })
    return notes


# ── Download one cover ─────────────────────────────────────────────────────────

async def download_cover(
    session: aiohttp.ClientSession, note_id: str, url: str
) -> bool:
    dest = COVER_DIR / f"{note_id}.jpg"
    if dest.exists():
        return True
    try:
        async with session.get(
            url,
            headers={"User-Agent": BROWSER_UA, "Referer": "https://www.xiaohongshu.com/"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                return False
            data = await resp.read()
            if len(data) < 4096:
                return False
            dest.write_bytes(data)
            return True
    except Exception:
        return False


# ── Main collection loop ───────────────────────────────────────────────────────

async def run_collect(total: int):
    from playwright.async_api import async_playwright

    state = get_session_state()
    if state is None:
        print("No session found. Run: python3 download_covers.py --login")
        return

    done = load_done()
    print(f"Already have: {len(done):,}  |  Target: {total:,}  |  Need: {max(0, total-len(done)):,}\n")

    if len(done) >= total:
        print("Target already reached.")
        return

    stats = {"downloaded": 0, "skipped": 0, "failed": 0}
    t0 = time.time()

    # Open metadata file for appending
    meta_f = open(METADATA_PATH, "a")

    async with async_playwright() as pw:
        browser = await launch_chromium_async(
            pw.chromium,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            storage_state=state,
            user_agent=BROWSER_UA,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        connector = aiohttp.TCPConnector(limit=10)
        async with aiohttp.ClientSession(connector=connector) as http:

            # Cycle through channels to get domain diversity
            channel_idx = 0
            while len(done) < total:
                channel_url, channel_name = CHANNELS[channel_idx % len(CHANNELS)]
                channel_idx += 1

                page_covers: list[dict] = []

                async def on_response(resp):
                    if "homefeed" in resp.url:
                        try:
                            data = await resp.json()
                            page_covers.extend(parse_homefeed(data))
                        except Exception:
                            pass

                page = await ctx.new_page()
                page.on("response", on_response)

                try:
                    await page.goto(channel_url, wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2.5)

                    # Scroll to load more notes from this channel
                    scrolls_needed = max(15, (total - len(done)) // 8)
                    scrolls_needed = min(scrolls_needed, 40)

                    for _ in range(scrolls_needed):
                        if len(done) >= total:
                            break
                        await page.evaluate("window.scrollBy(0, 700)")
                        await asyncio.sleep(1.0)

                        # Download any newly captured covers
                        while page_covers and len(done) < total:
                            note = page_covers.pop(0)
                            nid = note["note_id"]
                            if nid in done:
                                stats["skipped"] += 1
                                continue
                            ok = await download_cover(http, nid, note["cover_url"])
                            if ok:
                                done.add(nid)
                                stats["downloaded"] += 1
                                meta_f.write(json.dumps({
                                    "note_id": nid,
                                    "liked_count": note["liked_count"],
                                    "collected_count": note.get("collected_count", 0),
                                    "comments_count": note.get("comments_count", 0),
                                    "note_title": note.get("note_title", ""),
                                    "desc": note.get("desc", ""),
                                    "local_time": note.get("local_time", "2024010112"),
                                    "domain": channel_name,
                                    "channel": channel_name,
                                }, ensure_ascii=False) + "\n")
                                meta_f.flush()
                            else:
                                stats["failed"] += 1

                except Exception as e:
                    print(
                        f"  [error] channel_failed error_code="
                        f"{type(e).__name__.lower()}"
                    )
                finally:
                    await page.close()

                # Progress report per channel
                elapsed = time.time() - t0
                rate = stats["downloaded"] / elapsed if elapsed > 0 else 0.001
                remaining = max(0, total - len(done))
                eta = remaining / rate / 60 if rate > 0 else 999
                mb = stats["downloaded"] * 55 // 1024  # ~55KB avg
                save_done(done)
                print(
                    f"[{channel_name}] total={len(done):,}/{total}  "
                    f"new={stats['downloaded']}  "
                    f"~{mb}MB  "
                    f"rate={rate:.1f}/s  ETA={eta:.0f}m"
                )

        await ctx.close()
        await browser.close()

    meta_f.close()
    save_done(done)
    elapsed = time.time() - t0
    mb = stats["downloaded"] * 55 // 1024
    print(
        f"\n{'='*60}\n"
        f"Done in {elapsed/60:.1f} min\n"
        f"  Downloaded : {stats['downloaded']:,} (~{mb} MB)\n"
        f"  Skipped    : {stats['skipped']:,}\n"
        f"  Failed     : {stats['failed']:,}\n"
        f"  Output dir : {COVER_DIR}\n"
        f"  Metadata   : {METADATA_PATH}\n"
        f"{'='*60}"
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true", help="Log in to XHS (run once)")
    parser.add_argument("--collect", type=int, metavar="N",
                        help="Collect N cover images")
    parser.add_argument("--run-id", default="v1", metavar="ID",
                        help="Run identifier, controls output paths (default: v1, use v2 for fresh run)")
    args = parser.parse_args()

    set_run_paths(args.run_id)

    if args.login:
        do_login()
    elif args.collect:
        asyncio.run(run_collect(args.collect))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
