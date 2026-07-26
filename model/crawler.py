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
import re
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径配置 ────────────────────────────────────────────────────────────
_BASE_DIR    = Path(__file__).parent
_LOG_FILE    = _BASE_DIR / "data" / "crawler_log.json"

# ── 导入共享模块 ─────────────────────────────────────────────────────────
sys.path.insert(0, str(_BASE_DIR))
import db
from chromium_security import launch_chromium_async
import performance_scoring as perf
import runtime_settings
import security_redaction

try:
    import memory
except Exception:
    memory = None

try:
    import xhs_acquisition
except Exception:
    xhs_acquisition = None

# ── 常量 ─────────────────────────────────────────────────────────────────
XHS_BASE         = "https://www.xiaohongshu.com"
MIN_DELAY        = 2.0   # 最短请求间隔（秒）
MAX_DELAY        = 6.0   # 最长请求间隔（秒）
DAILY_LIMIT      = 300   # 单日最大采集量
NOTE_CONTAINER_SELECTOR = ".note-content, .note-container, #noteContainer"
NOTE_LINK_RE = re.compile(r"/(?:explore|discovery/item)/[A-Za-z0-9]+")


def _assert_tracking_writable_with_storage(storage, note: dict) -> None:
    """Serialize Tracking writes with the API account-deletion checkpoint."""
    if getattr(storage, "postgres", db.using_postgres()):
        storage.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))",
            (f"noteai:user-write:{note['user_id']}",),
        )
    current = storage.fetchone(
        "SELECT status FROM tracked_notes WHERE id=? AND user_id=?",
        (note["id"], note["user_id"]),
    )
    if not current or current["status"] == "account_deletion_pending":
        raise ValueError("tracking write fenced")
HEADLESS         = os.environ.get("NOTEAI_CRAWLER_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}
XHS_USER_AGENT   = os.environ.get(
    "NOTEAI_XHS_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36",
)
XHS_PROFILE_USER_AGENT = os.environ.get(
    "NOTEAI_XHS_PROFILE_USER_AGENT",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1",
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


XHS_VIEWPORT = {
    "width": _env_int("NOTEAI_CRAWLER_VIEWPORT_WIDTH", 1365),
    "height": _env_int("NOTEAI_CRAWLER_VIEWPORT_HEIGHT", 900),
}
XHS_PROFILE_VIEWPORT = {
    "width": _env_int("NOTEAI_CRAWLER_PROFILE_VIEWPORT_WIDTH", 390),
    "height": _env_int("NOTEAI_CRAWLER_PROFILE_VIEWPORT_HEIGHT", 844),
}


def _browser_context_kwargs() -> dict:
    return {
        "user_agent": XHS_USER_AGENT,
        "viewport": dict(XHS_VIEWPORT),
    }


def _profile_context_kwargs() -> dict:
    return {
        "user_agent": XHS_PROFILE_USER_AGENT,
        "viewport": dict(XHS_PROFILE_VIEWPORT),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _next_due_from_note(note: dict, days: int) -> str:
    now = datetime.now(timezone.utc)
    base = (
        _parse_iso(note.get("published_at"))
        or _parse_iso(note.get("submitted_at"))
        or now
    )
    due = base + timedelta(days=days)
    return (due if due > now else now).isoformat()


def _classify_error(error: str) -> str:
    lower = (error or "").lower()
    if "timeout" in lower:
        return "timeout"
    if "login" in lower or "sign-in" in lower or "cookie" in lower:
        return "auth_required"
    if "captcha" in lower or "verify" in lower:
        return "verification_required"
    if "selector" in lower:
        return "selector_changed"
    return "extract_failed"


def _load_cookies() -> list:
    stored = runtime_settings.get_json("xhs_cookies", [])
    if isinstance(stored, list) and stored:
        return stored
    return []


def _save_log(entry: dict) -> None:
    event = security_redaction.sanitize_crawler_event({**entry, "ts": _now()})
    print(json.dumps({"crawler_event": event}, ensure_ascii=False), flush=True)
    if db.using_postgres():
        db.execute(
            "INSERT INTO crawler_events(event_json,created_at) VALUES(?,?)",
            (json.dumps(event, ensure_ascii=False), event["ts"]),
        )
        return
    log = []
    if _LOG_FILE.exists():
        try:
            log = json.loads(_LOG_FILE.read_text())
        except Exception:
            log = []
    log.append(event)
    log = log[-500:]  # 只保留最近500条
    _LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


async def _random_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


async def _wait_for_note_container(page, timeout_ms: int) -> bool:
    try:
        await page.wait_for_selector(NOTE_CONTAINER_SELECTOR, timeout=timeout_ms)
        return True
    except Exception:
        return False


async def _note_link_from_page(page) -> str:
    try:
        hrefs = await page.eval_on_selector_all(
            "a[href]",
            "(links) => links.map((a) => a.href).filter(Boolean)",
        )
    except Exception:
        hrefs = []
    for href in hrefs:
        if isinstance(href, str) and NOTE_LINK_RE.search(href):
            return href
    return ""


async def _extract_note_data(page, url: str) -> dict | None:
    """从小红书笔记页面提取互动数据。"""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await _random_delay()

        # 等待笔记内容加载；短链有时先落到中间页，再暴露真实笔记链接。
        if not await _wait_for_note_container(page, timeout_ms=12_000):
            note_href = await _note_link_from_page(page)
            if note_href:
                await page.goto(note_href, wait_until="domcontentloaded", timeout=30_000)
                await _random_delay()
            await page.wait_for_selector(NOTE_CONTAINER_SELECTOR, timeout=15_000)

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
        _save_log({
            "action": "extract_failed",
            "error_code": security_redaction.stable_error_code(e),
        })
        return None


async def _extract_note_data_with_sidecar(url: str, domain: str = "") -> dict | None:
    """Fallback to the XHS-Downloader API sidecar when browser selectors fail."""
    if not xhs_acquisition or not os.environ.get("NOTEAI_XHS_DOWNLOADER_URL", "").strip():
        return None
    try:
        result = await asyncio.to_thread(
            xhs_acquisition.fetch_detail_with_sidecar,
            url,
            domain=domain or "",
        )
        normalized = result.get("normalized") if isinstance(result.get("normalized"), dict) else {}
        if not (normalized.get("has_content") or normalized.get("has_metrics")):
            return None
        return {
            "likes": int(normalized.get("likes") or 0),
            "saves": int(normalized.get("saves") or 0),
            "comments": int(normalized.get("comments") or 0),
            "title": str(normalized.get("title") or "")[:100],
        }
    except Exception as e:
        _save_log({
            "action": "sidecar_extract_failed",
            "error_code": security_redaction.stable_error_code(e),
        })
        return None


async def _extract_note_data_with_spider_http(url: str) -> dict | None:
    """Read one note through the bounded direct adapter; never use a browser fallback."""
    from spider_xhs_http import SpiderXHSHTTPAdapter

    payload = await asyncio.to_thread(SpiderXHSHTTPAdapter().note_detail, url)
    normalized = (
        xhs_acquisition.normalize_sidecar_detail(payload)
        if xhs_acquisition else {}
    )
    if not (normalized.get("has_content") or normalized.get("has_metrics")):
        return None
    return {
        "likes": int(normalized.get("likes") or 0),
        "saves": int(normalized.get("saves") or 0),
        "comments": int(normalized.get("comments") or 0),
        "title": str(normalized.get("title") or "")[:100],
    }


async def check_cookie_validity() -> bool:
    """验证 Cookie 是否有效（能否访问需登录的页面）。"""
    cookies = _load_cookies()
    if not cookies:
        print("No cookies found")
        return False
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await launch_chromium_async(pw.chromium, headless=HEADLESS)
            ctx     = await browser.new_context(**_profile_context_kwargs())
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
        print(json.dumps(
            security_redaction.safe_failure_event("crawler_cookie_check", e),
            ensure_ascii=False,
        ))
        return False


async def _refresh_cookie_if_needed(ctx) -> bool:
    """如果访问时发现 Cookie 失效，自动尝试刷新（当前仅提示，真实刷新需要账号密码）。"""
    # TODO: 接入自动登录（需账号密码，当前仅触发告警）
    _save_log({"action": "cookie_expired", "message": "Cookie 已失效，请在管理后台更新"})
    return False


def _due_tracking_notes(limit: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    h24 = (now - timedelta(hours=24)).isoformat()
    d7 = (now - timedelta(days=7)).isoformat()

    # 24h 首次采集
    pending_24h = db.fetchall(
        "SELECT * FROM tracked_notes WHERE status='pending' "
        "AND ((next_check_at IS NOT NULL AND next_check_at<=?) "
        "OR (next_check_at IS NULL AND submitted_at<=?)) LIMIT ?",
        (now_iso, h24, limit // 2)
    )

    # 7天终态采集；checking_24h 兼容旧数据，成功后会统一进入 complete。
    pending_7d = db.fetchall(
        "SELECT * FROM tracked_notes WHERE status IN ('checking_7d','checking_24h') "
        "AND ((next_check_at IS NOT NULL AND next_check_at<=?) "
        "OR (next_check_at IS NULL AND check_24h_at<=?)) LIMIT ?",
        (now_iso, d7, limit // 2)
    )

    return [dict(r) for r in pending_24h] + [dict(r) for r in pending_7d]


def _record_tracking_success(note: dict, data: dict) -> None:
    is_7d = note["status"] in ("checking_7d", "checking_24h")
    now_iso = _now()
    with db.transaction(write=True) as tx:
        _assert_tracking_writable_with_storage(tx, note)
        if not note.get("note_title") and data.get("title"):
            tx.execute(
                "UPDATE tracked_notes SET note_title=? WHERE id=?",
                (data["title"], note["id"]),
            )
        if not is_7d:
            next_7d = _next_due_from_note(note, days=7)
            tx.execute(
                "UPDATE tracked_notes SET likes_24h=?,saves_24h=?,comments_24h=?,"
                "check_24h_at=?,last_checked_at=?,next_check_at=?,"
                "status='checking_7d',attempt_count=0,last_error_code=NULL,"
                "last_error=NULL WHERE id=?",
                (
                    data["likes"], data["saves"], data["comments"], now_iso,
                    now_iso, next_7d, note["id"],
                ),
            )
            return

        score = perf.score_performance(
            domain=note.get("domain", "美食"),
            likes=data["likes"],
            saves=data["saves"],
            comments=data["comments"],
            views=None,
            predicted_ces=note.get("predicted_ces"),
            evidence_source="crawler",
            window="7d",
            likes_24h=note.get("likes_24h"),
            saves_24h=note.get("saves_24h"),
            comments_24h=note.get("comments_24h"),
        )
        tx.execute(
            "UPDATE tracked_notes SET likes_7d=?,saves_7d=?,comments_7d=?,"
            "views_est=?,actual_ces=?,check_7d_at=?,last_checked_at=?,"
            "status='complete',confidence=?,confidence_label=?,evidence_source=?,"
            "training_eligible=?,insights_json=?,completed_at=?,"
            "last_error_code=NULL,last_error=NULL WHERE id=?",
            (
                data["likes"], data["saves"], data["comments"], score.views_est,
                score.actual_ces, now_iso, now_iso, score.confidence,
                score.confidence_label, score.evidence_source,
                1 if score.training_eligible else 0, score.insights_json(),
                now_iso, note["id"],
            ),
        )
        tx.execute(
            "INSERT INTO growth_records("
            "id,user_id,note_id,domain,score,grade,action,recorded_at"
            ") VALUES(?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()), note["user_id"], note.get("source_note_id"),
                note.get("domain", "美食"), score.actual_ces, score.grade,
                "url_crawl_7d", now_iso,
            ),
        )
    if memory:
        try:
            title = note.get("note_title") or data.get("title") or "已发布笔记"
            memory.add_context(
                note["user_id"],
                f"真实表现追踪：{title[:24]}，7天实际{score.actual_ces:.1f}分，"
                f"{score.confidence_label}置信度，强项{score.insights.get('strongest_signal')}，"
                f"短板{score.insights.get('weakest_signal')}",
                source_note_id=note.get("source_note_id"),
            )
        except Exception:
            pass


def _record_tracking_failure(note: dict, code: str, summary: str) -> None:
    attempts = int(note.get("attempt_count") or 0) + 1
    max_attempts = int(note.get("max_attempts") or 2)
    next_status = "needs_manual" if attempts >= max_attempts else note["status"]
    with db.transaction(write=True) as tx:
        _assert_tracking_writable_with_storage(tx, note)
        tx.execute(
            "UPDATE tracked_notes SET status=?,attempt_count=?,last_checked_at=?,"
            "next_check_at=?,last_error_code=?,last_error=? WHERE id=?",
            (
                next_status, attempts, _now(),
                (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                code, summary[:200], note["id"],
            ),
        )


async def _process_tracking_notes(notes: list[dict], fetch_detail) -> dict:
    stats = {"collected": 0, "failed": 0, "total": len(notes)}
    for note in notes:
        try:
            data = await fetch_detail(note)
            if data:
                _record_tracking_success(note, data)
                stats["collected"] += 1
            else:
                _record_tracking_failure(note, "extract_failed", "自动采集未能读取公开互动数据")
                stats["failed"] += 1
            await _random_delay()
        except Exception as exc:
            # Adapter exceptions expose only a fixed code; no Cookie/a1/xsec token
            # is included in the persisted summary.
            direct_code = str(getattr(exc, "code", "") or "")
            allowed_codes = {
                "challenge",
                "cooldown",
                "login_required",
                "login_or_challenge_required",
                "server_session_logged_out",
                "collection_suspended",
                "collection_safety_unavailable",
            }
            error_code = (
                direct_code
                if direct_code in allowed_codes
                else security_redaction.stable_error_code(exc)
            )
            error_summary = error_code
            _record_tracking_failure(note, error_code, error_summary)
            stats["failed"] += 1
            _save_log({"action": "note_error", "error_code": error_code})
            if error_code in allowed_codes:
                if (
                    xhs_acquisition
                    and error_code in {"login_required", "server_session_logged_out"}
                ):
                    xhs_acquisition.mark_server_session_logged_out()
                break
    return stats


async def run_collection_round(limit: int = 50) -> dict:
    """Process due 24-hour/7-day tracking rows through the selected adapter."""
    adapter_name = os.environ.get("NOTEAI_XHS_ACQUISITION_ADAPTER", "").strip()
    from spider_xhs_http import XHSAdapterError, collection_route, collection_route_suspended

    try:
        route = collection_route(adapter_name)
    except XHSAdapterError as exc:
        return {"skipped": True, "reason": exc.code, "collected": 0}
    if collection_route_suspended(route):
        return {"skipped": True, "reason": "collection_suspended", "collected": 0}
    if route == "direct":
        if xhs_acquisition and xhs_acquisition.collection_safety_status().get("session_blocked"):
            return {"skipped": True, "reason": "server_session_logged_out", "collected": 0}

    notes = _due_tracking_notes(limit)
    if not notes:
        return {"message": "暂无待采集记录", "collected": 0}

    if route == "direct":
        async def fetch_http(note: dict) -> dict | None:
            return await _extract_note_data_with_spider_http(note["xhs_url"])

        stats = await _process_tracking_notes(notes, fetch_http)
    else:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"error": "Playwright 未安装", "collected": 0}
        cookies = _load_cookies()
        if not cookies:
            return {"error": "无有效 Cookie，请在管理后台上传", "collected": 0}
        async with async_playwright() as pw:
            browser = await launch_chromium_async(pw.chromium, headless=HEADLESS)
            ctx = await browser.new_context(**_browser_context_kwargs())
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()

            async def fetch_browser(note: dict) -> dict | None:
                data = await _extract_note_data(page, note["xhs_url"])
                if data:
                    return data
                return await _extract_note_data_with_sidecar(
                    note["xhs_url"], domain=note.get("domain", "")
                )

            stats = await _process_tracking_notes(notes, fetch_browser)
            await browser.close()

    _save_log({"action": "round_complete", **stats})
    return stats


def get_crawler_logs(limit: int = 50) -> list:
    if db.using_postgres():
        rows = db.fetchall(
            "SELECT event_json FROM crawler_events ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        events = []
        for row in reversed(rows):
            try:
                events.append(json.loads(row["event_json"]))
            except Exception:
                continue
        return events
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
