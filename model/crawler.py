"""
NoteAI Pro 爬虫系统 v2
- Playwright 无头浏览器 + 自动 Cookie 刷新
- 两阶段采集：发布当天 + 7 天后
- 处理 tracked_notes 表的 pending 记录
- 防反爬：随机延迟、行为拟人化

使用：
  python crawler.py run          # 运行一轮采集
  python crawler.py check-cookie # 验证 Cookie 有效性
"""
import asyncio
import json
import os
import random
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径配置 ────────────────────────────────────────────────────────────
_BASE_DIR    = Path(__file__).parent
_COOKIE_FILE = _BASE_DIR / "data" / "xhs_cookies.json"
_LOG_FILE    = _BASE_DIR / "data" / "crawler_log.json"

# ── 导入共享模块 ─────────────────────────────────────────────────────────
sys.path.insert(0, str(_BASE_DIR))
import db

# ── 常量 ─────────────────────────────────────────────────────────────────
XHS_BASE         = "https://www.xiaohongshu.com"
MIN_DELAY        = 2.0   # 最短请求间隔（秒）
MAX_DELAY        = 6.0   # 最长请求间隔（秒）
DAILY_LIMIT      = 300   # 单日最大采集量
HEADLESS         = True  # 生产环境用无头模式


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cookies() -> list:
    if not _COOKIE_FILE.exists():
        return []
    try:
        return json.loads(_COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_log(entry: dict) -> None:
    log = []
    if _LOG_FILE.exists():
        try:
            log = json.loads(_LOG_FILE.read_text())
        except Exception:
            log = []
    log.append({**entry, "ts": _now()})
    log = log[-500:]  # 只保留最近500条
    _LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


async def _random_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


async def _extract_note_data(page, url: str) -> dict | None:
    """从小红书笔记页面提取互动数据。"""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await _random_delay()

        # 等待笔记内容加载
        await page.wait_for_selector(".note-content, .note-container, #noteContainer",
                                     timeout=15_000)

        # 提取互动数据（多种选择器兼容不同版本）
        async def try_select(selectors: list[str]) -> str:
            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        txt = (await el.inner_text()).strip()
                        if txt:
                            return txt
                except Exception:
                    pass
            return "0"

        def _parse_count(txt: str) -> int:
            """解析「1.2万」「999+」等格式。"""
            txt = txt.replace(",", "").replace("+", "").strip()
            if "万" in txt:
                return int(float(txt.replace("万", "")) * 10000)
            try:
                return int(txt)
            except Exception:
                return 0

        likes_txt    = await try_select([".like-wrapper .count", ".like-count", "[class*='like'] span"])
        saves_txt    = await try_select([".collect-wrapper .count", ".collect-count", "[class*='collect'] span"])
        comments_txt = await try_select([".comment-count", "[class*='comment'] span.count"])
        title_txt    = await try_select(["#detail-title", ".note-title", "h1.title"])

        return {
            "likes":    _parse_count(likes_txt),
            "saves":    _parse_count(saves_txt),
            "comments": _parse_count(comments_txt),
            "title":    title_txt[:100],
        }
    except Exception as e:
        _save_log({"action": "extract_failed", "url": url, "error": str(e)[:200]})
        return None


async def check_cookie_validity() -> bool:
    """验证 Cookie 是否有效（能否访问需登录的页面）。"""
    cookies = _load_cookies()
    if not cookies:
        print("No cookies found")
        return False
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=HEADLESS)
            ctx     = await browser.new_context(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            )
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            await page.goto(f"{XHS_BASE}/user/profile/me", wait_until="domcontentloaded", timeout=20_000)
            valid = "sign-in" not in page.url and "login" not in page.url
            await browser.close()
            print("Cookie valid:", valid)
            return valid
    except ImportError:
        print("Playwright not installed: pip install playwright && playwright install chromium")
        return False
    except Exception as e:
        print(f"Cookie check error: {e}")
        return False


async def _refresh_cookie_if_needed(ctx) -> bool:
    """如果访问时发现 Cookie 失效，自动尝试刷新（当前仅提示，真实刷新需要账号密码）。"""
    # TODO: 接入自动登录（需账号密码，当前仅触发告警）
    _save_log({"action": "cookie_expired", "message": "Cookie 已失效，请在管理后台更新"})
    return False


async def run_collection_round(limit: int = 50) -> dict:
    """
    执行一轮采集：
    1. 处理 status='pending' 且 submitted_at > 24h 的记录（24h 首次采集）
    2. 处理 status='checking_7d' 或 check_24h_at > 7d 的记录（7天终态）
    返回统计信息。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"error": "Playwright 未安装", "collected": 0}

    cookies = _load_cookies()
    if not cookies:
        return {"error": "无有效 Cookie，请在管理后台上传", "collected": 0}

    now   = datetime.now(timezone.utc)
    h24   = (now - timedelta(hours=24)).isoformat()
    d7    = (now - timedelta(days=7)).isoformat()

    # 24h 首次采集
    pending_24h = db.fetchall(
        "SELECT * FROM tracked_notes WHERE status='pending' AND submitted_at<=? LIMIT ?",
        (h24, limit // 2)
    )

    # 7天终态采集
    pending_7d = db.fetchall(
        "SELECT * FROM tracked_notes WHERE status='checking_24h' AND check_24h_at<=? LIMIT ?",
        (d7, limit // 2)
    )

    to_process = [dict(r) for r in pending_24h] + [dict(r) for r in pending_7d]
    if not to_process:
        return {"message": "暂无待采集记录", "collected": 0}

    stats = {"collected": 0, "failed": 0, "total": len(to_process)}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        for note in to_process:
            try:
                data = await _extract_note_data(page, note["xhs_url"])
                is_7d = note["status"] == "checking_24h"

                if data:
                    # 更新 title（如果为空）
                    if not note.get("note_title") and data.get("title"):
                        db.execute("UPDATE tracked_notes SET note_title=? WHERE id=?",
                                   (data["title"], note["id"]))

                    now_iso = _now()
                    if is_7d:
                        # 计算真实 CES
                        views_est = max(int(data["saves"] / 0.11), data["likes"] * 5, 100)
                        save_r = data["saves"] / max(views_est, 1)
                        like_r = data["likes"] / max(views_est, 1)
                        comm_r = data["comments"] / max(views_est, 1)
                        BENCH = {"s": 0.08, "l": 0.15, "c": 0.02}
                        def p(v, b): return min(100, round(v / max(b, 0.001) * 50, 1))
                        ces = round(p(save_r,BENCH["s"])*0.40 + p(like_r,BENCH["l"])*0.30
                                    + p(comm_r,BENCH["c"])*0.20 + 50*0.10, 1)
                        db.execute(
                            "UPDATE tracked_notes SET likes_7d=?,saves_7d=?,comments_7d=?,"
                            "views_est=?,actual_ces=?,check_7d_at=?,status='complete' WHERE id=?",
                            (data["likes"], data["saves"], data["comments"],
                             views_est, ces, now_iso, note["id"])
                        )
                        # 写成长记录
                        db.execute(
                            "INSERT INTO growth_records(id,user_id,note_id,domain,score,grade,action,recorded_at) VALUES(?,?,NULL,?,?,?,?,?)",
                            (str(uuid.uuid4()), note["user_id"],
                             note.get("domain","美食"), ces,
                             "优秀" if ces>=75 else "良好" if ces>=55 else "待改进",
                             "url_crawl_7d", now_iso)
                        )
                    else:
                        db.execute(
                            "UPDATE tracked_notes SET likes_24h=?,saves_24h=?,comments_24h=?,"
                            "check_24h_at=?,status='checking_24h' WHERE id=?",
                            (data["likes"], data["saves"], data["comments"], now_iso, note["id"])
                        )
                    stats["collected"] += 1
                else:
                    # 采集失败，标记为需要手动回填
                    db.execute(
                        "UPDATE tracked_notes SET status='needs_manual' WHERE id=?",
                        (note["id"],))
                    stats["failed"] += 1

                await _random_delay()  # 防反爬

            except Exception as e:
                stats["failed"] += 1
                _save_log({"action": "note_error", "id": note["id"], "error": str(e)[:200]})

        await browser.close()

    _save_log({"action": "round_complete", **stats})
    return stats


def get_crawler_logs(limit: int = 50) -> list:
    if not _LOG_FILE.exists():
        return []
    try:
        log = json.loads(_LOG_FILE.read_text())
        return log[-limit:]
    except Exception:
        return []


# ── CLI 入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        result = asyncio.run(run_collection_round())
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "check-cookie":
        valid = asyncio.run(check_cookie_validity())
        sys.exit(0 if valid else 1)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
