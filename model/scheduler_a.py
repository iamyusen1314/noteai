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
import contextvars
import json
import logging
import os
import re
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import runtime_settings
from chromium_security import launch_chromium_async

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
TOKEN_DISCOVERY_ENABLED = os.environ.get("NOTEAI_XHS_TOKEN_DISCOVERY", "1").strip().lower() not in {"0", "false", "no"}
BROWSER_TARGETS_PER_SESSION = max(0, int(os.environ.get("NOTEAI_XHS_BROWSER_TARGETS_PER_SESSION", "0") or 0))
STOP_ON_CHALLENGE = os.environ.get("NOTEAI_XHS_STOP_ON_CHALLENGE", "0").strip().lower() in {"1", "true", "yes", "on"}

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

DISCOVERY_DIAGNOSTIC_ERROR_CODES = frozenset({
    "navigation_failed",
    "all_navigation_failed",
    "homefeed_target_failed",
    "search_input_not_found",
    "search_input_not_visible",
    "search_input_type_failed",
    "search_target_failed",
    "search_targets_skipped_after_challenge",
    "challenge_cooldown_active",
    "search_response_not_seen",
    "search_response_non_json",
    "search_target_payload_not_seen",
    "search_challenge_before_target_payload",
    "search_response_business_error",
    "search_response_unknown_schema",
    "search_response_empty_result",
    "search_candidates_empty",
    "search_candidates_all_filtered",
    "search_candidates_all_deduped",
    "search_source_zero_unclassified",
    "recommend_response_not_seen",
    "recommend_response_non_json",
    "recommend_schema_empty",
    "recommend_candidates_all_filtered",
    "recommend_candidates_all_deduped",
    "recommend_source_zero_unclassified",
    "homefeed_source_zero",
    "hot_search_source_zero",
    "possible_access_challenge",
    "server_session_logged_out",
    "collection_suspended",
    "runtime_role_not_allowed",
    "adapter_not_selected",
    "scrape_once_failed",
})
_DIAGNOSTIC_FIELDS = {
    "targets": ("planned", "started", "completed", "skipped"),
    "navigation": ("ok", "failed"),
    "input": ("found", "visible", "typed", "failed"),
    "search": (
        "response_seen", "json_ok", "json_failed", "title_count",
        "phrase_raw", "cleaned", "filtered", "deduped", "final",
    ),
    "recommend": (
        "response_seen", "json_ok", "json_failed", "items_raw",
        "extracted", "filtered", "deduped", "final",
    ),
}
_RESPONSE_STATUS_CLASSES = ("2xx", "3xx", "4xx", "5xx", "unknown")
_FINAL_PAGE_CLASSES = ("search", "explore", "login", "challenge", "other")
_SEARCH_RESPONSE_CLASSES = (
    "generic_json",
    "note_result",
    "empty_result",
    "unknown_schema",
    "business_error",
    "non_json",
)
_SEARCH_TARGET_OUTCOMES = ("endpoint_not_seen", "challenge_before_target_payload")
_CIRCUIT_STATES = ("closed", "open", "cooldown")
_CIRCUIT_SKIPPED_REASONS = ("", "challenge_detected", "challenge_cooldown_active")
_SEARCH_CIRCUIT_CONTEXT: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "noteai_xhs_search_circuit",
    default=None,
)


@contextmanager
def search_circuit_context(value: dict | None):
    token = _SEARCH_CIRCUIT_CONTEXT.set(dict(value or {}))
    try:
        yield
    finally:
        _SEARCH_CIRCUIT_CONTEXT.reset(token)


class ScrapeResults(list):
    """List-compatible scrape output carrying secret-free diagnostics."""

    def __init__(self, rows: list[dict], diagnostics: dict):
        super().__init__(rows)
        self.diagnostics = diagnostics


def new_discovery_diagnostics() -> dict:
    return {
        "schema_version": "xhs.discovery.v1",
        **{
            section: {field: 0 for field in fields}
            for section, fields in _DIAGNOSTIC_FIELDS.items()
        },
        "response_status_class": {key: 0 for key in _RESPONSE_STATUS_CLASSES},
        "final_page_class": {key: 0 for key in _FINAL_PAGE_CLASSES},
        "search_response_class": {key: 0 for key in _SEARCH_RESPONSE_CLASSES},
        "search_target_outcome": {key: 0 for key in _SEARCH_TARGET_OUTCOMES},
        "circuit": {"state": "closed", "skipped_reason": ""},
        "diagnostic_error_codes": [],
    }


def _diagnostic_inc(diagnostics: dict, section: str, field: str, amount: int = 1) -> None:
    if section not in _DIAGNOSTIC_FIELDS or field not in _DIAGNOSTIC_FIELDS[section]:
        return
    diagnostics[section][field] = max(0, int(diagnostics[section].get(field, 0))) + max(0, int(amount or 0))


def _diagnostic_add_error(diagnostics: dict, code: str) -> None:
    if code not in DISCOVERY_DIAGNOSTIC_ERROR_CODES:
        return
    codes = diagnostics.setdefault("diagnostic_error_codes", [])
    if code not in codes:
        codes.append(code)


def sanitize_discovery_diagnostics(value: dict | None) -> dict:
    safe = new_discovery_diagnostics()
    raw = value if isinstance(value, dict) else {}
    for section, fields in _DIAGNOSTIC_FIELDS.items():
        source = raw.get(section) if isinstance(raw.get(section), dict) else {}
        for field in fields:
            try:
                safe[section][field] = max(0, int(source.get(field) or 0))
            except (TypeError, ValueError):
                safe[section][field] = 0
    for section, allowed in (
        ("response_status_class", _RESPONSE_STATUS_CLASSES),
        ("final_page_class", _FINAL_PAGE_CLASSES),
        ("search_response_class", _SEARCH_RESPONSE_CLASSES),
        ("search_target_outcome", _SEARCH_TARGET_OUTCOMES),
    ):
        source = raw.get(section) if isinstance(raw.get(section), dict) else {}
        for field in allowed:
            try:
                safe[section][field] = max(0, int(source.get(field) or 0))
            except (TypeError, ValueError):
                safe[section][field] = 0
    for code in raw.get("diagnostic_error_codes") or []:
        _diagnostic_add_error(safe, str(code))
    raw_circuit = raw.get("circuit") if isinstance(raw.get("circuit"), dict) else {}
    state = str(raw_circuit.get("state") or "closed")
    reason = str(raw_circuit.get("skipped_reason") or "")
    safe["circuit"]["state"] = state if state in _CIRCUIT_STATES else "closed"
    safe["circuit"]["skipped_reason"] = reason if reason in _CIRCUIT_SKIPPED_REASONS else ""
    return safe


def _response_status_class(status: object) -> str:
    try:
        value = int(status)
    except (TypeError, ValueError):
        return "unknown"
    if 200 <= value < 300:
        return "2xx"
    if 300 <= value < 400:
        return "3xx"
    if 400 <= value < 500:
        return "4xx"
    if 500 <= value < 600:
        return "5xx"
    return "unknown"


def _classify_final_page(raw_url: str) -> str:
    path = (urlparse(str(raw_url or "")).path or "").lower()
    if any(marker in path for marker in ("/captcha", "/challenge", "/risk-control")):
        return "challenge"
    if any(marker in path for marker in ("/login", "/signin", "/sign-in")):
        return "login"
    if "search_result" in path or "/search/" in path:
        return "search"
    if "/explore" in path:
        return "explore"
    return "other"


def _classify_discovery_response(raw_url: str) -> str:
    path = (urlparse(str(raw_url or "")).path or "").lower()
    segments = tuple(segment for segment in path.split("/") if segment)
    if (
        segments[-2:] in {("search", "recommend"), ("search", "suggest")}
        or segments[-1:] in {("search_recommend",), ("suggest",)}
    ):
        return "recommend"
    if "search/trending/query" in path:
        return "trending"
    return "other"


def _classify_search_payload(payload) -> str:
    if not isinstance(payload, dict):
        return "generic_json"

    success = payload.get("success")
    code = payload.get("code")
    if success is False:
        return "business_error"
    if isinstance(code, (int, float)) and not isinstance(code, bool) and code != 0:
        return "business_error"
    if isinstance(code, str) and code.strip().lower() not in {"", "0", "ok", "success"}:
        return "business_error"

    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return "generic_json"
    items = data["items"]
    if not items:
        return "empty_result"
    if any(
        isinstance(item, dict)
        and isinstance(item.get("note_card"), dict)
        and any(
            isinstance(item["note_card"].get(key), str)
            and item["note_card"][key].strip()
            for key in ("display_title", "title")
        )
        for item in items
    ):
        return "note_result"
    return "unknown_schema"


def discovery_diagnostics_for_results(
    rows: list[dict],
    diagnostics: dict | None = None,
    *,
    extra_error_code: str = "",
) -> dict:
    safe = sanitize_discovery_diagnostics(diagnostics)
    if extra_error_code:
        _diagnostic_add_error(safe, extra_error_code)
    sources = _source_breakdown(rows)
    safe["search"]["final"] = sources["search_result"]
    safe["recommend"]["final"] = sources["search_recommend"]
    if {
        "server_session_logged_out",
        "collection_suspended",
    } & set(safe["diagnostic_error_codes"]):
        return safe
    if safe["navigation"]["failed"]:
        _diagnostic_add_error(safe, "navigation_failed")
        if safe["navigation"]["ok"] == 0:
            _diagnostic_add_error(safe, "all_navigation_failed")
    if safe["input"]["failed"]:
        if safe["input"]["found"] == 0:
            _diagnostic_add_error(safe, "search_input_not_found")
        elif safe["input"]["visible"] == 0:
            _diagnostic_add_error(safe, "search_input_not_visible")
        elif safe["input"]["typed"] == 0:
            _diagnostic_add_error(safe, "search_input_type_failed")

    search = safe["search"]
    search_classes = safe["search_response_class"]
    search_outcomes = safe["search_target_outcome"]
    if search["final"] == 0:
        if search["response_seen"] == 0:
            _diagnostic_add_error(safe, "search_response_not_seen")
        if search["json_failed"]:
            _diagnostic_add_error(safe, "search_response_non_json")
        if search_outcomes["endpoint_not_seen"]:
            _diagnostic_add_error(safe, "search_target_payload_not_seen")
        if search_outcomes["challenge_before_target_payload"]:
            _diagnostic_add_error(safe, "search_challenge_before_target_payload")
        if search_classes["business_error"]:
            _diagnostic_add_error(safe, "search_response_business_error")
        if search_classes["unknown_schema"]:
            _diagnostic_add_error(safe, "search_response_unknown_schema")
        if search_classes["empty_result"]:
            _diagnostic_add_error(safe, "search_response_empty_result")
        if search_classes["note_result"] and search["phrase_raw"] == 0:
            _diagnostic_add_error(safe, "search_candidates_empty")
        if search["phrase_raw"] and search["cleaned"] == 0 and search["filtered"]:
            _diagnostic_add_error(safe, "search_candidates_all_filtered")
        if search["deduped"] and search["cleaned"] == 0:
            _diagnostic_add_error(safe, "search_candidates_all_deduped")
        if not any(str(code).startswith("search_") for code in safe["diagnostic_error_codes"]):
            _diagnostic_add_error(safe, "search_source_zero_unclassified")

    recommend = safe["recommend"]
    if recommend["final"] == 0:
        if recommend["response_seen"] == 0:
            _diagnostic_add_error(safe, "recommend_response_not_seen")
        if recommend["json_failed"]:
            _diagnostic_add_error(safe, "recommend_response_non_json")
        if recommend["json_ok"] and recommend["items_raw"] == 0:
            _diagnostic_add_error(safe, "recommend_schema_empty")
        if recommend["extracted"] and recommend["filtered"] >= recommend["extracted"]:
            _diagnostic_add_error(safe, "recommend_candidates_all_filtered")
        if recommend["extracted"] and recommend["deduped"] >= recommend["extracted"]:
            _diagnostic_add_error(safe, "recommend_candidates_all_deduped")
        if not any(str(code).startswith("recommend_") for code in safe["diagnostic_error_codes"]):
            _diagnostic_add_error(safe, "recommend_source_zero_unclassified")
    if sources["homefeed"] == 0:
        _diagnostic_add_error(safe, "homefeed_source_zero")
    if sources["hot_search"] == 0:
        _diagnostic_add_error(safe, "hot_search_source_zero")
    return safe


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


def session_state_summary() -> dict:
    """Return secret-free XHS session metadata for health checks and alerts."""
    if os.environ.get("NOTEAI_XHS_ACQUISITION_ADAPTER", "").strip() == "spider_xhs_http":
        from spider_xhs_http import session_health

        health = session_health()
        return {
            "configured": health["configured"],
            "cookie_count": health["cookie_count"],
            "auth_cookie_present": health["auth_cookie_present"],
            "auth_cookie_expired": health["auth_cookie_expired"],
            "auth_expires_at": None,
            "adapter": health["adapter"],
            "status": health["status"],
        }
    state = _get_session_state()
    payload = None
    if isinstance(state, str):
        try:
            payload = json.loads(Path(state).read_text(encoding="utf-8"))
        except Exception:
            payload = None
    elif isinstance(state, dict):
        payload = state

    cookies = payload.get("cookies", []) if isinstance(payload, dict) else []
    cookies = cookies if isinstance(cookies, list) else []
    auth_cookies = [
        cookie for cookie in cookies
        if isinstance(cookie, dict) and cookie.get("name") in {"web_session", "id_token"}
    ]
    expiries = []
    for cookie in auth_cookies:
        try:
            expires = float(cookie.get("expires") or 0)
        except (TypeError, ValueError):
            expires = 0
        if expires > 0:
            expiries.append(expires)
    now_ts = time.time()
    auth_expired = bool(auth_cookies and expiries and max(expiries) <= now_ts)
    return {
        "configured": bool(cookies),
        "cookie_count": len(cookies),
        "auth_cookie_present": bool(auth_cookies),
        "auth_cookie_expired": auth_expired,
        "auth_expires_at": (
            datetime.fromtimestamp(max(expiries)).isoformat()
            if expiries else None
        ),
    }


def _extract_keyword_from_item(item: dict) -> str | None:
    for key in ("keyword", "word", "search_word", "name", "text", "title"):
        v = item.get(key)
        if v and isinstance(v, str) and len(v) >= 2:
            return v.strip()
    return None


def _source_breakdown(rows: list[dict]) -> dict[str, int]:
    breakdown = {
        "homefeed": 0,
        "search_result": 0,
        "search_recommend": 0,
        "hot_search": 0,
        "other": 0,
    }
    for row in rows:
        source = str(row.get("source") or "")
        if source in {"homefeed", "homefeed_phrase", "homefeed_token"}:
            breakdown["homefeed"] += 1
        elif source in {"search_phrase", "search_token"}:
            breakdown["search_result"] += 1
        elif source in {"search_recommend", "hot_search"}:
            breakdown[source] += 1
        else:
            breakdown["other"] += 1
    return breakdown


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


def _extract_recommend_keywords(payload: object) -> list[str]:
    found: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            keyword = _extract_keyword_from_item(value)
            if keyword:
                found.append(keyword)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(payload)
    return list(dict.fromkeys(found))


def _direct_http_failure_code(code: str) -> str:
    if code in {"login_required", "login_or_challenge_required", "server_session_logged_out"}:
        return "server_session_logged_out"
    if code == "cooldown":
        return "challenge_cooldown_active"
    if code == "collection_suspended":
        return "collection_suspended"
    if code == "runtime_role_not_allowed":
        return "runtime_role_not_allowed"
    if code == "challenge":
        return "possible_access_challenge"
    return "scrape_once_failed"


async def scrape_once_http() -> list[dict]:
    """Collect the bounded production evidence set through direct HTTP only."""
    from hot_keywords import clean_scraped_keyword_row, compute_trend_dirs
    from spider_xhs_http import SpiderXHSHTTPAdapter, XHSAdapterError

    def collect() -> ScrapeResults:
        adapter = SpiderXHSHTTPAdapter()
        diagnostics = new_discovery_diagnostics()
        best: dict[tuple[str, str], dict] = {}
        phrase_rows: list[tuple[str, str, str]] = []
        recommend_rows: list[tuple[str, str]] = []

        homefeed_targets = []
        for url, category in CHANNELS:
            channel_id = (parse_qs(urlparse(url).query).get("channel_id") or ["homefeed_recommend"])[-1]
            homefeed_targets.append((channel_id, category))
        search_targets = [
            (seed, category)
            for category, seeds in SEARCH_SEEDS.items()
            for seed in seeds[:max(0, SEARCH_SEEDS_PER_CATEGORY)]
        ]
        diagnostics["targets"]["planned"] = len(search_targets)

        try:
            for channel_id, category in homefeed_targets:
                response = adapter.homefeed(category=channel_id, max_pages=1, max_items=20)
                for title in _extract_note_titles(response.get("items") or []):
                    phrase_rows.extend((phrase, category, "homefeed_phrase") for phrase in _title_phrase_candidates(title))

            for seed, category in search_targets:
                _diagnostic_inc(diagnostics, "targets", "started")
                recommend = adapter.search_recommend(seed)
                _diagnostic_inc(diagnostics, "recommend", "response_seen")
                _diagnostic_inc(diagnostics, "recommend", "json_ok")
                recommended = _extract_recommend_keywords(recommend)
                _diagnostic_inc(diagnostics, "recommend", "items_raw", len(recommended))
                _diagnostic_inc(diagnostics, "recommend", "extracted", len(recommended))
                recommend_rows.extend((keyword, category) for keyword in recommended)

                search = adapter.search_notes(seed, max_pages=1, max_items=20)
                _diagnostic_inc(diagnostics, "search", "response_seen")
                _diagnostic_inc(diagnostics, "search", "json_ok")
                titles = _extract_note_titles(search.get("items") or [])
                _diagnostic_inc(diagnostics, "search", "title_count", len(titles))
                for title in titles:
                    phrases = _title_phrase_candidates(title)
                    _diagnostic_inc(diagnostics, "search", "phrase_raw", len(phrases))
                    phrase_rows.extend((phrase, category, "search_phrase") for phrase in phrases)
                _diagnostic_inc(diagnostics, "targets", "completed")
        except XHSAdapterError as exc:
            failure = _direct_http_failure_code(exc.code)
            _diagnostic_add_error(diagnostics, failure)
            diagnostics["circuit"].update({
                "state": "cooldown" if failure == "challenge_cooldown_active" else "open",
                "skipped_reason": (
                    "challenge_cooldown_active"
                    if failure == "challenge_cooldown_active"
                    else "challenge_detected"
                    if failure == "possible_access_challenge"
                    else ""
                ),
            })
            return ScrapeResults([], diagnostics)

        phrase_counts = Counter(phrase_rows)
        trend_directions = compute_trend_dirs([phrase for phrase, _category, _source in phrase_counts])
        for (phrase, category, source), count in phrase_counts.most_common(600):
            row = clean_scraped_keyword_row({
                "keyword": phrase,
                "search_vol": max(5, min(95, 12 + count * 8)),
                "trend_dir": trend_directions.get(phrase, 0),
                "source": source,
                "category": category,
                "count": count,
            })
            if row:
                _keep_best_candidate(best, row)
                if source == "search_phrase":
                    _diagnostic_inc(diagnostics, "search", "cleaned")
            elif source == "search_phrase":
                _diagnostic_inc(diagnostics, "search", "filtered")

        for keyword, category in recommend_rows:
            row = clean_scraped_keyword_row({
                "keyword": keyword,
                "search_vol": 86,
                "trend_dir": 1,
                "source": "search_recommend",
                "category": category,
                "count": 1,
            })
            if row:
                _keep_best_candidate(best, row)
            else:
                _diagnostic_inc(diagnostics, "recommend", "filtered")

        results = sorted(
            best.values(),
            key=lambda row: (row.get("category", ""), -int(row.get("search_vol", 0))),
        )
        return ScrapeResults(results, discovery_diagnostics_for_results(results, diagnostics))

    return await asyncio.to_thread(collect)


async def _trigger_search_input(
    page,
    seed: str,
    timeout_seconds: float = 7.0,
    diagnostics: dict | None = None,
) -> tuple[bool, str]:
    """Type a seed after XHS finishes any client-side search-page redirects."""
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    last_error = "search input not available"
    found = False
    visible = False
    while time.monotonic() < deadline:
        try:
            search_input = page.locator('input[placeholder="搜索小红书"]').first
            current_found = bool(await search_input.count())
            if current_found:
                found = True
            if current_found and await search_input.is_visible():
                visible = True
                await search_input.fill("")
                await search_input.type(seed, delay=35)
                if diagnostics is not None:
                    _diagnostic_inc(diagnostics, "input", "found")
                    _diagnostic_inc(diagnostics, "input", "visible")
                    _diagnostic_inc(diagnostics, "input", "typed")
                return True, ""
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        await asyncio.sleep(0.35)
    if diagnostics is not None:
        if found:
            _diagnostic_inc(diagnostics, "input", "found")
        if visible:
            _diagnostic_inc(diagnostics, "input", "visible")
        _diagnostic_inc(diagnostics, "input", "failed")
    return False, last_error


async def scrape_once() -> list[dict]:
    """
    单次抓取：
    1. 遍历8个品类 channel，拦截 homefeed tag_list 统计词频
    2. 同时拦截热搜/建议 API（有 session 时命中概率更高）
    返回 keywords list，每项包含 keyword/search_vol/trend_dir/source/count
    """
    from playwright.async_api import async_playwright
    from hot_keywords import clean_scraped_keyword_row, compute_trend_dirs

    state = _get_session_state()
    tag_counters: dict[str, Counter] = {name: Counter() for _, name in CHANNELS}
    hot_search_kws: dict[str, list[str]] = {name: [] for _, name in CHANNELS}
    search_recommend_kws: dict[str, list[str]] = {name: [] for name in SEARCH_SEEDS}
    discovery_metrics: Counter = Counter()
    discovery_diagnostics = new_discovery_diagnostics()
    requested_circuit = _SEARCH_CIRCUIT_CONTEXT.get() or {}
    requested_state = str(requested_circuit.get("state") or "closed")
    circuit_state = requested_state if STOP_ON_CHALLENGE and requested_state in _CIRCUIT_STATES else "closed"
    discovery_diagnostics["circuit"]["state"] = circuit_state
    if circuit_state == "cooldown":
        discovery_diagnostics["circuit"]["skipped_reason"] = "challenge_cooldown_active"
        _diagnostic_add_error(discovery_diagnostics, "challenge_cooldown_active")

    async with async_playwright() as pw:
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-gpu",
            "--disable-sync",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-first-run",
            "--renderer-process-limit=1",
        ]
        ctx_kwargs = dict(
            user_agent=BROWSER_UA,
            viewport={"width": 1024, "height": 640},
            locale="zh-CN",
            service_workers="block",
        )
        if state:
            ctx_kwargs["storage_state"] = state

        async def block_heavy_assets(route):
            if route.request.resource_type in {"image", "media", "font", "stylesheet"}:
                await route.abort()
            else:
                await route.continue_()

        def make_on_response(
            channel_name: str,
            discovery_source: str,
            search_target_state: dict | None = None,
        ):
            async def on_response(resp):
                url = resp.url
                if discovery_source == "search_discovery":
                    status_class = _response_status_class(getattr(resp, "status", None))
                    discovery_diagnostics["response_status_class"][status_class] += 1
                response_kind = _classify_discovery_response(url)

                # 尝试拦截热搜 API
                if any(p in url for p in HOT_API_PATTERNS):
                    if response_kind == "recommend" and discovery_source == "search_discovery":
                        _diagnostic_inc(discovery_diagnostics, "recommend", "response_seen")
                    try:
                        data = await resp.json()
                        if response_kind == "recommend" and discovery_source == "search_discovery":
                            _diagnostic_inc(discovery_diagnostics, "recommend", "json_ok")
                        if response_kind == "recommend":
                            items = data.get("data", {}).get("sug_items", []) or []
                            if discovery_source == "search_discovery":
                                _diagnostic_inc(discovery_diagnostics, "recommend", "items_raw", len(items))
                            discovery_metrics["recommend_responses"] += 1
                            discovery_metrics["recommend_items"] += len(items)
                            for item in items:
                                kw = _extract_keyword_from_item(item) if isinstance(item, dict) else None
                                if kw:
                                    if discovery_source == "search_discovery":
                                        _diagnostic_inc(discovery_diagnostics, "recommend", "extracted")
                                    search_recommend_kws.setdefault(channel_name, []).append(kw)
                            return
                        if "search/trending/query" in url:
                            payload = data.get("data", {}) if isinstance(data, dict) else {}
                            candidates = list(payload.get("queries") or [])
                            candidates.extend(payload.get("ai_words") or [])
                            hint_word = payload.get("hint_word")
                            if isinstance(hint_word, dict):
                                candidates.append(hint_word)
                            discovery_metrics["trending_responses"] += 1
                            discovery_metrics["trending_items"] += len(candidates)
                            for item in candidates:
                                kw = _extract_keyword_from_item(item) if isinstance(item, dict) else None
                                if kw:
                                    hot_search_kws.setdefault(channel_name, []).append(kw)
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
                        if response_kind == "recommend" and discovery_source == "search_discovery":
                            _diagnostic_inc(discovery_diagnostics, "recommend", "json_failed")

                should_extract_titles = (
                    ("homefeed" in url and discovery_source == "homefeed")
                    or (discovery_source == "search_discovery" and ("search" in url or "api" in url))
                )
                if should_extract_titles:
                    if discovery_source == "search_discovery":
                        _diagnostic_inc(discovery_diagnostics, "search", "response_seen")
                    try:
                        data = await resp.json()
                    except Exception:
                        if discovery_source == "search_discovery":
                            _diagnostic_inc(discovery_diagnostics, "search", "json_failed")
                            discovery_diagnostics["search_response_class"]["non_json"] += 1
                        return
                    if discovery_source == "search_discovery":
                        response_class = _classify_search_payload(data)
                        discovery_diagnostics["search_response_class"][response_class] += 1
                        # Only a supported result-family shape proves that a target payload arrived.
                        if (
                            search_target_state is not None
                            and response_class in {"note_result", "empty_result", "unknown_schema"}
                        ):
                            search_target_state["target_payload_seen"] = True
                    try:
                        counter = tag_counters.setdefault(channel_name, Counter())
                        titles = (
                            _extract_note_titles(data)
                            if discovery_source != "search_discovery" or response_class == "note_result"
                            else []
                        )
                        if discovery_source == "search_discovery":
                            _diagnostic_inc(discovery_diagnostics, "search", "json_ok")
                            _diagnostic_inc(discovery_diagnostics, "search", "title_count", len(titles))
                        for title in titles:
                            if not title:
                                continue
                            # 标题短语优先：比单词更能反映真实内容趋势。
                            phrases = _title_phrase_candidates(title)
                            if discovery_source == "search_discovery":
                                _diagnostic_inc(discovery_diagnostics, "search", "phrase_raw", len(phrases))
                            for phrase in phrases:
                                source = "search_phrase" if discovery_source == "search_discovery" else "homefeed_phrase"
                                counter[(phrase, source)] += 1
                            # jieba 分词作为补充，后续会按行业相关度清洗。
                            if TOKEN_DISCOVERY_ENABLED:
                                import jieba

                                for token in jieba.cut(title):
                                    token = token.strip()
                                    if 2 <= len(token) <= 8:
                                        source = "search_token" if discovery_source == "search_discovery" else "homefeed_token"
                                        counter[(token, source)] += 1
                    except Exception:
                        if discovery_source == "search_discovery":
                            _diagnostic_inc(discovery_diagnostics, "search", "json_failed")
            return on_response

        async def scrape_target(
            page,
            target_url: str,
            channel_name: str,
            discovery_source: str,
            settle_seconds: float,
            scroll_rounds: int,
        ) -> str:
            search_target_state = {"target_payload_seen": False}
            handler = make_on_response(
                channel_name,
                discovery_source,
                search_target_state,
            )
            page.on("response", handler)
            page_class = "other"
            if discovery_source == "search_discovery":
                _diagnostic_inc(discovery_diagnostics, "targets", "started")
            try:
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                    if discovery_source == "search_discovery":
                        _diagnostic_inc(discovery_diagnostics, "navigation", "ok")
                    page_class = _classify_final_page(getattr(page, "url", ""))
                    if page_class == "login":
                        _diagnostic_add_error(
                            discovery_diagnostics,
                            "server_session_logged_out",
                        )
                        return page_class
                    if (
                        discovery_source == "search_discovery"
                        and STOP_ON_CHALLENGE
                        and page_class == "challenge"
                    ):
                        return page_class
                except Exception:
                    if discovery_source == "search_discovery":
                        _diagnostic_inc(discovery_diagnostics, "navigation", "failed")
                    raise
                if discovery_source == "search_discovery":
                    seed = (parse_qs(urlparse(target_url).query).get("keyword") or [""])[0]
                    typed, _input_error = await _trigger_search_input(
                        page, seed, diagnostics=discovery_diagnostics
                    )
                    if typed:
                        discovery_metrics["search_inputs_typed"] += 1
                    else:
                        discovery_metrics["search_input_failures"] += 1
                await asyncio.sleep(settle_seconds)
                for _ in range(max(1, scroll_rounds)):
                    await page.mouse.wheel(0, 700)
                    await asyncio.sleep(max(0.2, SCROLL_WAIT_SECONDS))
            finally:
                page_class = _classify_final_page(getattr(page, "url", ""))
                discovery_diagnostics["final_page_class"][page_class] += 1
                if page_class == "login":
                    _diagnostic_add_error(
                        discovery_diagnostics,
                        "server_session_logged_out",
                    )
                if discovery_source == "search_discovery":
                    _diagnostic_inc(discovery_diagnostics, "targets", "completed")
                    if page_class == "challenge":
                        _diagnostic_add_error(discovery_diagnostics, "possible_access_challenge")
                    if not search_target_state["target_payload_seen"]:
                        outcome = (
                            "challenge_before_target_payload"
                            if page_class == "challenge"
                            else "endpoint_not_seen"
                        )
                        discovery_diagnostics["search_target_outcome"][outcome] += 1
                page.remove_listener("response", handler)
                if page_class != "login":
                    try:
                        await page.goto("about:blank", wait_until="commit", timeout=5000)
                    except Exception:
                        pass
            return page_class

        targets = [
            (url, channel, "homefeed", CHANNEL_SETTLE_SECONDS, SCROLL_ROUNDS, "Channel")
            for url, channel in CHANNELS
        ]
        targets.extend(
            (url, channel, "search_discovery", SEARCH_SETTLE_SECONDS, SEARCH_SCROLL_ROUNDS, "Search discovery")
            for url, channel in _search_discovery_targets()
        )
        discovery_diagnostics["targets"]["planned"] = sum(
            1 for _url, _channel, source, _settle, _scrolls, _label in targets
            if source == "search_discovery"
        )
        targets_per_session = BROWSER_TARGETS_PER_SESSION or max(1, len(targets))
        session_logged_out = False

        for start in range(0, len(targets), targets_per_session):
            target_batch = targets[start:start + targets_per_session]
            if session_logged_out:
                _diagnostic_inc(
                    discovery_diagnostics,
                    "targets",
                    "skipped",
                    sum(1 for item in target_batch if item[2] == "search_discovery"),
                )
                continue
            if target_batch and all(item[2] == "search_discovery" for item in target_batch) and circuit_state in {"open", "cooldown"}:
                _diagnostic_inc(discovery_diagnostics, "targets", "skipped", len(target_batch))
                continue
            browser = await launch_chromium_async(
                pw.chromium,
                headless=True,
                args=browser_args,
            )
            ctx = await browser.new_context(**ctx_kwargs)
            await ctx.route("**/*", block_heavy_assets)
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await ctx.new_page()
            try:
                for target_url, channel_name, source, settle, scrolls, label in target_batch:
                    if session_logged_out:
                        if source == "search_discovery":
                            _diagnostic_inc(discovery_diagnostics, "targets", "skipped")
                        continue
                    if source == "search_discovery" and circuit_state in {"open", "cooldown"}:
                        _diagnostic_inc(discovery_diagnostics, "targets", "skipped")
                        continue
                    try:
                        page_class = await scrape_target(
                            page, target_url, channel_name, source, settle, scrolls
                        )
                        if page_class == "login":
                            session_logged_out = True
                            continue
                        if (
                            STOP_ON_CHALLENGE
                            and source == "search_discovery"
                            and page_class == "challenge"
                        ):
                            circuit_state = "open"
                            discovery_diagnostics["circuit"].update({
                                "state": "open",
                                "skipped_reason": "challenge_detected",
                            })
                            _diagnostic_add_error(
                                discovery_diagnostics,
                                "search_targets_skipped_after_challenge",
                            )
                    except Exception as exc:
                        error_code = (
                            "search_target_failed"
                            if source == "search_discovery"
                            else "homefeed_target_failed"
                        )
                        _diagnostic_add_error(discovery_diagnostics, error_code)
                        log.warning(
                            "%s target failed exception_type=%s diagnostic_error_code=%s",
                            label,
                            type(exc).__name__,
                            error_code,
                        )
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
                _diagnostic_inc(discovery_diagnostics, "recommend", "deduped")
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
            if not row:
                _diagnostic_inc(discovery_diagnostics, "recommend", "filtered")
                continue
            if key in best_results:
                _diagnostic_inc(discovery_diagnostics, "recommend", "deduped")
            _keep_best_candidate(best_results, row)

    trend_candidates = list(dict.fromkeys(
        kw
        for tag_counter in tag_counters.values()
        for (kw, _source), _count in tag_counter.most_common(300)
        if len(kw) >= 2
    ))
    trend_directions = compute_trend_dirs(trend_candidates)

    # 来自 homefeed 标题短语/分词（按词频和质量权重计算相对热度）
    for category, tag_counter in tag_counters.items():
        total = sum(
            count * _source_weight(source)
            for (_, source), count in tag_counter.items()
        ) or 1
        for (kw, source), count in tag_counter.most_common(300):
            key = (category, kw)
            is_search_candidate = source in {"search_phrase", "search_token"}
            if len(kw) < 2:
                if is_search_candidate:
                    _diagnostic_inc(discovery_diagnostics, "search", "filtered")
                continue
            if key in seen:
                if is_search_candidate:
                    _diagnostic_inc(discovery_diagnostics, "search", "deduped")
                continue
            weighted_count = count * _source_weight(source)
            vol = max(min(int(weighted_count / total * 12000), 95), 5)
            row = clean_scraped_keyword_row({
                "keyword":    kw,
                "search_vol": vol,
                "trend_dir":  trend_directions.get(kw, 0),
                "source":     source,
                "category":   category,
                "count":      count,
            })
            if not row:
                if is_search_candidate:
                    _diagnostic_inc(discovery_diagnostics, "search", "filtered")
                continue
            if is_search_candidate:
                _diagnostic_inc(discovery_diagnostics, "search", "cleaned")
                if key in best_results:
                    _diagnostic_inc(discovery_diagnostics, "search", "deduped")
            _keep_best_candidate(best_results, row)

    results = sorted(
        best_results.values(),
        key=lambda r: (r.get("category", ""), -int(r.get("search_vol", 0)), -int(r.get("source_priority", 0))),
    )
    sources = _source_breakdown(results)
    discovery_diagnostics = discovery_diagnostics_for_results(results, discovery_diagnostics)
    log.info(
        f"Scraped {len(results)} keywords "
        f"({sources['homefeed']} homefeed, {sources['search_result']} search_result, "
        f"{sources['search_recommend']} search_recommend, {sources['hot_search']} hot_search, "
        f"{sources['other']} other)"
    )
    log.info(
        "Discovery API metrics "
        f"recommend_responses={discovery_metrics['recommend_responses']} "
        f"recommend_items={discovery_metrics['recommend_items']} "
        f"trending_responses={discovery_metrics['trending_responses']} "
        f"trending_items={discovery_metrics['trending_items']} "
        f"search_inputs_typed={discovery_metrics['search_inputs_typed']} "
        f"search_input_failures={discovery_metrics['search_input_failures']}"
    )
    return ScrapeResults(results, discovery_diagnostics)


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
    except Exception as exc:
        log.error(
            "Scrape job failed exception_type=%s diagnostic_error_code=scrape_once_failed",
            type(exc).__name__,
        )


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
