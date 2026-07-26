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
import hashlib
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
import tracking_contract

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
NOTE_CONTAINER_SELECTOR = ".note-content, .note-container, #noteContainer"
NOTE_LINK_RE = re.compile(r"/(?:explore|discovery/item)/[A-Za-z0-9]+")


def _assert_tracking_writable_with_storage(
    storage,
    note: dict,
    *,
    require_active_attempt: bool,
) -> dict:
    """Lock and verify one exact Tracking claim against account deletion."""
    if getattr(storage, "postgres", db.using_postgres()):
        storage.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))",
            (f"noteai:user-write:{note['user_id']}",),
        )
    lock = " FOR UPDATE" if getattr(storage, "postgres", False) else ""
    current = storage.fetchone(
        "SELECT status,claim_token,claim_expires_at,active_attempt_id "
        f"FROM tracked_notes WHERE id=? AND user_id=?{lock}",
        (note["id"], note["user_id"]),
    )
    expected_status = note.get("claimed_status") or note.get("status")
    if (
        not current
        or current["status"] == "account_deletion_pending"
        or current["status"] != expected_status
        or not note.get("claim_token")
        or current["claim_token"] != note.get("claim_token")
    ):
        raise ValueError("tracking write fenced")
    if not require_active_attempt:
        expires_at = _parse_iso(current["claim_expires_at"])
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            raise ValueError("tracking claim expired")
    if require_active_attempt:
        if (
            not note.get("active_attempt_id")
            or current["active_attempt_id"] != note.get("active_attempt_id")
        ):
            raise ValueError("tracking provider attempt fenced")
    elif current["active_attempt_id"] is not None:
        raise ValueError("tracking provider attempt already active")
    return dict(current)
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


def _claim_due_tracking_notes(
    limit: int,
    *,
    now: datetime | None = None,
    run_id: str | None = None,
) -> list[dict]:
    """Atomically claim due rows in deterministic order.

    Rows with an active provider attempt are deliberately never reclaimed:
    after a crash their external-call outcome is ambiguous and an operator
    must resolve them instead of allowing an automatic duplicate call.
    """
    limit = tracking_contract.validate_round_limit(limit)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = now.isoformat()
    h24 = (now - timedelta(hours=24)).isoformat()
    d7 = (now - timedelta(days=7)).isoformat()
    expires_at = (now + tracking_contract.CLAIM_LEASE).isoformat()
    claimed: list[dict] = []
    with db.transaction(write=True) as tx:
        lock = " FOR UPDATE SKIP LOCKED" if tx.postgres else ""
        if tx.postgres:
            claim_due = "claim_expires_at::timestamptz<=?::timestamptz"
            next_due = "next_check_at::timestamptz<=?::timestamptz"
            submitted_due = "submitted_at::timestamptz<=?::timestamptz"
            check_24h_due = "check_24h_at::timestamptz<=?::timestamptz"
            order_next = "next_check_at::timestamptz"
            order_submitted = "submitted_at::timestamptz"
        else:
            claim_due = "noteai_tracking_clock_lte(claim_expires_at,?)=1"
            next_due = "noteai_tracking_clock_lte(next_check_at,?)=1"
            submitted_due = "noteai_tracking_clock_lte(submitted_at,?)=1"
            check_24h_due = "noteai_tracking_clock_lte(check_24h_at,?)=1"
            order_next = "next_check_at"
            order_submitted = "submitted_at"
        rows = tx.fetchall(
            "SELECT * FROM tracked_notes WHERE "
            "active_attempt_id IS NULL "
            "AND (claim_token IS NULL OR claim_expires_at IS NULL OR "
            f"{claim_due}) "
            "AND ("
            "(status='pending' AND ("
            f"(next_check_at IS NOT NULL AND {next_due}) "
            f"OR (next_check_at IS NULL AND {submitted_due}))) "
            "OR (status IN ('checking_7d','checking_24h') AND ("
            f"(next_check_at IS NOT NULL AND {next_due}) "
            f"OR (next_check_at IS NULL AND {check_24h_due})))"
            f") ORDER BY COALESCE({order_next},{order_submitted}),"
            f"{order_submitted},id "
            f"LIMIT ?{lock}",
            (now_iso, now_iso, h24, now_iso, d7, limit),
        )
        for row in rows:
            snapshot = dict(row)
            claim_token = str(uuid.uuid4())
            expiry_guard = (
                "claim_expires_at::timestamptz<=?::timestamptz"
                if tx.postgres
                else "noteai_tracking_clock_lte(claim_expires_at,?)=1"
            )
            cursor = tx.execute(
                "UPDATE tracked_notes SET claim_token=?,claim_expires_at=? "
                "WHERE id=? AND user_id=? AND status=? AND active_attempt_id IS NULL "
                "AND (claim_token IS NULL OR claim_expires_at IS NULL OR "
                f"{expiry_guard})",
                (
                    claim_token,
                    expires_at,
                    snapshot["id"],
                    snapshot["user_id"],
                    snapshot["status"],
                    now_iso,
                ),
            )
            if cursor.rowcount != 1:
                continue
            snapshot["claim_token"] = claim_token
            snapshot["claim_expires_at"] = expires_at
            snapshot["claimed_status"] = snapshot["status"]
            snapshot["active_attempt_id"] = None
            snapshot["run_id"] = run_id or str(uuid.uuid4())
            claimed.append(snapshot)
    return claimed


def _due_tracking_notes(limit: int) -> list[dict]:
    """Compatibility alias; selecting due work now always acquires a claim."""
    return _claim_due_tracking_notes(limit)


def _reconcile_stale_provider_attempts(
    *,
    limit: int = 50,
    now: datetime | None = None,
) -> int:
    """Fail stale admitted calls to a visible, manual-only terminal state.

    A stale admission is never retried: its external outcome is unknowable.
    The durable attempt remains as evidence while the user-facing row becomes
    actionable and future worker rounds fail loudly.
    """
    limit = tracking_contract.validate_round_limit(limit)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current_iso = current.isoformat()
    postgres = db.using_postgres()
    stale_predicate = (
        "t.claim_expires_at::timestamptz<=?::timestamptz"
        if postgres
        else "noteai_tracking_clock_lte(t.claim_expires_at,?)=1"
    )
    candidates = db.fetchall(
        "SELECT t.id,t.user_id,t.status,t.claim_token,t.claim_expires_at,"
        "t.active_attempt_id "
        "FROM tracked_notes t JOIN tracking_provider_attempts a "
        "ON a.id=t.active_attempt_id AND a.track_id=t.id AND a.user_id=t.user_id "
        "WHERE a.status='started' AND t.claim_expires_at IS NOT NULL "
        f"AND {stale_predicate} ORDER BY t.id LIMIT ?",
        (current_iso, limit),
    )
    reconciled = 0
    for candidate in candidates:
        note = dict(candidate)
        note["claimed_status"] = note["status"]
        with db.transaction(write=True) as tx:
            try:
                _assert_tracking_writable_with_storage(
                    tx,
                    note,
                    require_active_attempt=True,
                )
            except ValueError:
                continue
            expiry = _parse_iso(note.get("claim_expires_at"))
            if expiry is None or expiry > current:
                continue
            attempt = tx.execute(
                "UPDATE tracking_provider_attempts SET status='failed',"
                "completed_at=?,error_code='provider_outcome_unknown' "
                "WHERE id=? AND track_id=? AND user_id=? AND status='started'",
                (
                    current_iso,
                    note["active_attempt_id"],
                    note["id"],
                    note["user_id"],
                ),
            )
            if attempt.rowcount != 1:
                continue
            tracked = tx.execute(
                "UPDATE tracked_notes SET status='needs_manual',"
                "attempt_count=CASE WHEN attempt_count<2 THEN attempt_count+1 "
                "ELSE attempt_count END,last_checked_at=?,next_check_at=NULL,"
                "last_error_code='provider_outcome_unknown',"
                "last_error='provider_outcome_unknown',claim_token=NULL,"
                "claim_expires_at=NULL,active_attempt_id=NULL "
                "WHERE id=? AND user_id=? AND active_attempt_id=?",
                (
                    current_iso,
                    note["id"],
                    note["user_id"],
                    note["active_attempt_id"],
                ),
            )
            if tracked.rowcount != 1:
                raise ValueError("tracking stale reconciliation fenced")
            reconciled += 1
    return reconciled


def _admit_provider_attempt(note: dict) -> dict:
    """Durably admit the sole provider call for this track/window."""
    canonical_url = tracking_contract.safe_public_xhs_note_url(
        note.get("xhs_url"),
        note.get("xhs_note_id"),
    )
    if canonical_url is None:
        raise tracking_contract.TrackingContractError(
            "invalid_stored_tracking_identity"
        )
    stage = tracking_contract.stage_for_status(
        note.get("claimed_status") or note.get("status", "")
    )
    attempt_id = str(uuid.uuid4())
    admitted_at = _now()
    day_start = datetime.now(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat()
    run_id = str(note.get("run_id") or uuid.uuid4())
    with db.transaction(write=True) as tx:
        _assert_tracking_writable_with_storage(
            tx,
            note,
            require_active_attempt=False,
        )
        if tx.postgres:
            tx.execute(
                "SELECT pg_advisory_xact_lock(hashtext(?))",
                (f"noteai:tracking:daily-cap:{day_start[:10]}",),
            )
        admitted_count = tx.fetchone(
            "SELECT COUNT(*) AS c FROM tracking_provider_attempts "
            "WHERE admitted_at>=?",
            (day_start,),
        )
        if int(admitted_count["c"]) >= tracking_contract.DAILY_PROVIDER_LIMIT:
            raise tracking_contract.TrackingDailyLimitReached(
                "tracking_daily_provider_limit"
            )
        tx.execute(
            "INSERT INTO tracking_provider_attempts("
            "id,track_id,user_id,run_id,stage,status,admitted_at"
            ") VALUES(?,?,?,?,?,?,?)",
            (
                attempt_id,
                note["id"],
                note["user_id"],
                run_id,
                stage,
                "started",
                admitted_at,
            ),
        )
        cursor = tx.execute(
            "UPDATE tracked_notes SET active_attempt_id=? "
            "WHERE id=? AND user_id=? AND claim_token=? AND active_attempt_id IS NULL",
            (
                attempt_id,
                note["id"],
                note["user_id"],
                note["claim_token"],
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("tracking provider attempt fenced")
    admitted = dict(note)
    admitted["xhs_url"] = canonical_url
    admitted["active_attempt_id"] = attempt_id
    admitted["provider_stage"] = stage
    admitted["run_id"] = run_id
    return admitted


def _release_unstarted_claim(note: dict) -> None:
    """Release only a claim that has not admitted an external call."""
    with db.transaction(write=True) as tx:
        _assert_tracking_writable_with_storage(
            tx,
            note,
            require_active_attempt=False,
        )
        tx.execute(
            "UPDATE tracked_notes SET claim_token=NULL,claim_expires_at=NULL "
            "WHERE id=? AND user_id=? AND claim_token=?",
            (note["id"], note["user_id"], note["claim_token"]),
        )


def _record_tracking_success(note: dict, data: dict) -> None:
    data = tracking_contract.validate_provider_metrics(data)
    is_7d = note["status"] in ("checking_7d", "checking_24h")
    now_iso = _now()
    with db.transaction(write=True) as tx:
        _assert_tracking_writable_with_storage(
            tx,
            note,
            require_active_attempt=True,
        )
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
                "last_error=NULL,claim_token=NULL,claim_expires_at=NULL,"
                "active_attempt_id=NULL WHERE id=?",
                (
                    data["likes"], data["saves"], data["comments"], now_iso,
                    now_iso, next_7d, note["id"],
                ),
            )
            attempt_cursor = tx.execute(
                "UPDATE tracking_provider_attempts SET status='succeeded',"
                "completed_at=? WHERE id=? AND status='started'",
                (now_iso, note["active_attempt_id"]),
            )
            if attempt_cursor.rowcount != 1:
                raise ValueError("tracking provider attempt finalize fenced")
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
            "last_error_code=NULL,last_error=NULL,claim_token=NULL,"
            "claim_expires_at=NULL,active_attempt_id=NULL WHERE id=?",
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
                tracking_contract.deterministic_effect_id(note["id"], "growth"),
                note["user_id"], note.get("source_note_id"),
                note.get("domain", "美食"), score.actual_ces, score.grade,
                "url_crawl_7d", now_iso,
            ),
        )
        if memory is None:
            raise RuntimeError("tracking memory module unavailable")
        title = note.get("note_title") or data.get("title") or "已发布笔记"
        memory._add_memory_with_storage(
            tx,
            note["user_id"],
            "context",
            f"真实表现追踪：{title[:24]}，7天实际{score.actual_ces:.1f}分，"
            f"{score.confidence_label}置信度，强项{score.insights.get('strongest_signal')}，"
            f"短板{score.insights.get('weakest_signal')}",
            importance=0.5,
            source_note_id=note.get("source_note_id"),
            memory_id=tracking_contract.deterministic_effect_id(
                note["id"],
                "memory",
            ),
        )
        attempt_cursor = tx.execute(
            "UPDATE tracking_provider_attempts SET status='succeeded',"
            "completed_at=? WHERE id=? AND status='started'",
            (now_iso, note["active_attempt_id"]),
        )
        if attempt_cursor.rowcount != 1:
            raise ValueError("tracking provider attempt finalize fenced")


def _record_tracking_failure(note: dict, code: str, summary: str) -> None:
    attempts = int(note.get("attempt_count") or 0) + 1
    now_iso = _now()
    with db.transaction(write=True) as tx:
        _assert_tracking_writable_with_storage(
            tx,
            note,
            require_active_attempt=True,
        )
        tx.execute(
            "UPDATE tracked_notes SET status=?,attempt_count=?,last_checked_at=?,"
            "next_check_at=NULL,last_error_code=?,last_error=?,claim_token=NULL,"
            "claim_expires_at=NULL,active_attempt_id=NULL WHERE id=?",
            (
                "needs_manual", attempts, now_iso,
                code, summary[:200], note["id"],
            ),
        )
        attempt_cursor = tx.execute(
            "UPDATE tracking_provider_attempts SET status='failed',"
            "completed_at=?,error_code=? WHERE id=? AND status='started'",
            (now_iso, code, note["active_attempt_id"]),
        )
        if attempt_cursor.rowcount != 1:
            raise ValueError("tracking provider attempt finalize fenced")


async def _process_tracking_notes(notes: list[dict], fetch_detail) -> dict:
    stats = {
        "claimed": len(notes),
        "attempted": 0,
        "collected": 0,
        "failed": 0,
        "released": 0,
        "total": len(notes),
    }
    for index, claimed_note in enumerate(notes):
        note = None
        try:
            note = _admit_provider_attempt(claimed_note)
            stats["attempted"] += 1
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
            if note is None:
                try:
                    _release_unstarted_claim(claimed_note)
                    stats["released"] += 1
                except Exception:
                    pass
                stats["failed"] += 1
                _save_log({
                    "action": "provider_admission_failed",
                    "error_code": error_code,
                    "run_id": claimed_note.get("run_id"),
                })
                break
            _record_tracking_failure(note, error_code, error_summary)
            stats["failed"] += 1
            _save_log({
                "action": "note_error",
                "error_code": error_code,
                "run_id": note.get("run_id"),
                "stage": note.get("provider_stage"),
                "track_ref": hashlib.sha256(
                    str(note["id"]).encode("utf-8")
                ).hexdigest()[:16],
            })
            if error_code in allowed_codes:
                for remaining in notes[index + 1:]:
                    try:
                        _release_unstarted_claim(remaining)
                        stats["released"] += 1
                    except Exception as release_exc:
                        _save_log({
                            "action": "claim_release_failed",
                            "error_code": security_redaction.stable_error_code(
                                release_exc
                            ),
                        })
                break
    return stats


async def _process_due_tracking_notes(
    limit: int,
    fetch_detail,
    *,
    run_id: str,
) -> dict:
    """Claim immediately before each call so every row gets a fresh lease."""
    limit = tracking_contract.validate_round_limit(limit)
    aggregate = {
        "claimed": 0,
        "attempted": 0,
        "collected": 0,
        "failed": 0,
        "released": 0,
        "total": 0,
    }
    for _ in range(limit):
        notes = _claim_due_tracking_notes(1, run_id=run_id)
        if not notes:
            break
        result = await _process_tracking_notes(notes, fetch_detail)
        for key in aggregate:
            aggregate[key] += int(result.get(key) or 0)
        if int(result.get("failed") or 0) > 0:
            break
    return aggregate


def tracking_readiness_status() -> dict:
    """Provider-free, read-only Tracking schema and role readiness."""
    if os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() != "xhs-http":
        return {"status": "not_ready", "reason": "runtime_role_not_allowed"}
    try:
        now_iso = _now()
        with db.transaction(write=False) as tx:
            tx.fetchone(
                "SELECT id,user_id,xhs_url,xhs_note_id,status,claim_token,"
                "claim_expires_at,active_attempt_id FROM tracked_notes LIMIT 0"
            )
            tx.fetchone(
                "SELECT id,track_id,user_id,run_id,stage,status,admitted_at,"
                "completed_at,error_code FROM tracking_provider_attempts LIMIT 0"
            )
            attempts = tx.fetchone(
                "SELECT "
                "COUNT(*) FILTER (WHERE a.status='started') AS started,"
                "COUNT(*) FILTER (WHERE a.status='started' "
                "AND t.active_attempt_id=a.id) AS linked "
                "FROM tracking_provider_attempts a "
                "LEFT JOIN tracked_notes t ON t.id=a.track_id "
                "AND t.user_id=a.user_id"
            )
            stale_predicate = (
                "t.claim_expires_at::timestamptz<=?::timestamptz"
                if tx.postgres
                else "noteai_tracking_clock_lte(t.claim_expires_at,?)=1"
            )
            stale = tx.fetchone(
                "SELECT COUNT(*) AS c FROM tracked_notes t "
                "JOIN tracking_provider_attempts a "
                "ON a.id=t.active_attempt_id AND a.track_id=t.id "
                "AND a.user_id=t.user_id "
                "WHERE a.status='started' AND t.claim_expires_at IS NOT NULL "
                f"AND {stale_predicate}",
                (now_iso,),
            )
        stale_count = int(stale["c"] or 0)
        started_count = int(attempts["started"] or 0)
        unlinked_count = started_count - int(attempts["linked"] or 0)
        result = {
            "status": (
                "not_ready"
                if stale_count or unlinked_count
                else "ready"
            ),
            "active_provider_attempts": started_count - unlinked_count,
            "stale_provider_attempts": stale_count,
            "unlinked_started_attempts": unlinked_count,
            "provider_called": False,
        }
        if unlinked_count:
            result["reason"] = "provider_attempt_integrity_error"
        elif stale_count:
            result["reason"] = "provider_outcome_unknown"
        return result
    except Exception as exc:
        return {
            "status": "not_ready",
            "reason": security_redaction.stable_error_code(exc),
            "provider_called": False,
        }


async def run_collection_round(limit: int = 50) -> dict:
    """Process due 24-hour/7-day tracking rows through the selected adapter."""
    try:
        limit = tracking_contract.validate_round_limit(limit)
    except ValueError:
        return {"error": "invalid_tracking_round_limit", "collected": 0}
    adapter_name = os.environ.get("NOTEAI_XHS_ACQUISITION_ADAPTER", "").strip()
    run_id = str(uuid.uuid4())
    from spider_xhs_http import XHSAdapterError, collection_route, collection_route_suspended

    try:
        route = collection_route(adapter_name)
    except XHSAdapterError as exc:
        return {"skipped": True, "reason": exc.code, "collected": 0}
    if collection_route_suspended(route):
        return {"skipped": True, "reason": "collection_suspended", "collected": 0}
    reconciled = _reconcile_stale_provider_attempts(limit=limit)
    if reconciled:
        _save_log({
            "action": "provider_outcome_unknown",
            "run_id": run_id,
            "count": reconciled,
        })
        return {
            "error": "tracking_provider_outcome_unknown",
            "failed": reconciled,
            "collected": 0,
            "attempted": 0,
        }
    if route == "direct":
        if xhs_acquisition and xhs_acquisition.collection_safety_status().get("session_blocked"):
            return {"skipped": True, "reason": "server_session_logged_out", "collected": 0}

    if route == "direct":
        async def fetch_http(note: dict) -> dict | None:
            return await _extract_note_data_with_spider_http(note["xhs_url"])

        stats = await _process_due_tracking_notes(
            limit,
            fetch_http,
            run_id=run_id,
        )
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

            stats = await _process_due_tracking_notes(
                limit,
                fetch_browser,
                run_id=run_id,
            )
            await browser.close()

    if int(stats.get("total") or 0) == 0:
        return {"message": "暂无待采集记录", "collected": 0}
    _save_log({
        "action": "round_complete",
        "run_id": run_id,
        "limit": limit,
        "provider_calls": stats.get("attempted", 0),
        **stats,
    })
    return stats


def _result_exit_code(result: dict) -> int:
    """Keep the legacy direct CLI aligned with the managed worker."""
    if result.get("error") or int(result.get("failed") or 0) > 0:
        return 1
    if result.get("skipped"):
        return 0 if result.get("reason") == "collection_suspended" else 1
    return 0


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
        sys.exit(_result_exit_code(result))
    elif cmd == "check-cookie":
        valid = asyncio.run(check_cookie_validity())
        sys.exit(0 if valid else 1)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
