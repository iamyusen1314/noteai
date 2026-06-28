"""
Optional web fact enrichment for NoteAI.

This module only extracts structured factual hints from search snippets. It does
not generate copy and it never invents missing fields. If no provider key is
configured, callers get a disabled result and the app falls back to local logic.
"""

from __future__ import annotations

import os
import re
import time
import logging
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx


logging.getLogger("httpx").setLevel(logging.WARNING)

_CACHE: dict[str, tuple[float, dict]] = {}
_TIMEOUT_SECONDS = float(os.environ.get("NOTEAI_FACT_SEARCH_TIMEOUT", "8") or "8")
_MEITUAN_TRAVEL_TIMEOUT_SECONDS = float(os.environ.get("NOTEAI_MEITUAN_TRAVEL_TIMEOUT", "45") or "45")


_PRICE_RE = re.compile(
    r"(?:人均|每人|客单|消费|预算|价格|套餐价|团购|双人套餐)\D{0,12}(?:¥|￥)?\d{2,5}\s*(?:元|块|rmb|RMB)?"
    r"|(?:cost|price)[:： ]*(?:¥|￥)?\d{2,5}\s*(?:元|块)?"
    r"|(?:¥|￥)\s*\d{2,5}"
)
_HOURS_RE = re.compile(
    r"(?:营业时间|营业|开放时间|周一至周五|周六|周日|每天|全年)\D{0,24}\d{1,2}[:：点]\d{0,2}(?:\s*[-~至到]\s*\d{1,2}[:：点]\d{0,2})?"
    r"|(?:opentime|shop_hours|opening_hours)[:： ]*[^。；\n]{0,60}\d{1,2}[:：点]\d{0,2}(?:\s*[-~至到]\s*\d{1,2}[:：点]\d{0,2})?"
)
_ADDRESS_RE = re.compile(
    r"(?:地址|位于|位置|店址)[:：]?\s*[\u4e00-\u9fa5A-Za-z0-9（）()·\-—,，、]{6,80}"
    r"|[\u4e00-\u9fa5]{2,12}(?:区|镇|街道|商圈|广场|中心|购物中心|路|街|号|楼)[\u4e00-\u9fa5A-Za-z0-9（）()·\-—,，、]{0,60}"
)
_BOOKING_RE = re.compile(r"(?:预订|预约|订位|订座|排队|等位|叫号|提前订)")
_DEAL_RE = re.compile(r"(?:团购|套餐|双人餐|双人套餐|代金券|券包|平台券)[^。；\n]{0,80}")
_MUST_ORDER_RE = re.compile(r"(?:必点|招牌|推荐菜|招牌菜|镇店|主推)[^。；\n]{0,80}")
_RATING_RE = re.compile(r"(?:评分|星级|口味|环境|服务|rating)[:： ]?\s*\d(?:\.\d)?")
_REVIEW_KEYWORDS_RE = re.compile(r"(?:评价|点评|评论|高频词|关键词|大家说|用户说)[^。；\n]{0,100}")
_NOISE_RE = re.compile(r"\s+")
_SECRET_QUERY_RE = re.compile(r"(?i)([?&](?:key|ak|api_key|api-key|appid|secret|token|access_token|cx)=)[^&\s]+")
_FACT_QUERY_STOP_WORDS = {
    "地址", "位置", "营业", "营业时间", "开放时间", "时间", "人均", "价格", "消费", "预算", "预订", "预约", "排队", "等位",
    "电话", "商圈", "必点", "招牌", "评分", "口碑", "评价", "点评", "团购", "套餐", "优惠", "查询",
}
_LOCATION_HINT_WORDS = {
    "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "南京", "苏州", "武汉", "长沙", "西安", "天津", "厦门",
    "青岛", "佛山", "东莞", "珠海", "番禺", "万博",
}
_LOCATION_HINT_RE = re.compile(
    r"(北京|上海|广州|深圳|杭州|成都|重庆|南京|苏州|武汉|长沙|西安|天津|厦门|青岛|佛山|东莞|珠海|番禺|万博)"
)
_ROAD_CONTEXT_PREFIXES = ("路", "街", "大道", "大街", "西路", "东路", "南路", "北路", "中路")
_TRAVEL_FACT_DOMAINS = {"旅行", "旅游", "酒店", "住宿", "酒旅", "民宿", "出行"}
_AMAP_STORE_NAME_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9·.]{2,30}(?:旗舰店|总店|分店|万博店|门店|餐厅|酒家|饭店|茶楼|酒楼|火锅店|烤肉店|咖啡店|茶餐厅|酒店|民宿|景区|乐园|店|楼))"
)
_AMAP_GENERIC_SUFFIX_RE = re.compile(
    r"(?:旗舰店|总店|分店|万博店|门店|餐厅|酒家|饭店|茶楼|酒楼|火锅店|烤肉店|咖啡店|茶餐厅|酒店|民宿|景区|乐园|店|楼)$"
)
_FACT_FIELD_LABELS = {
    "address": "位置/地址",
    "price": "价格/人均",
    "hours": "营业时间",
    "booking": "预订/排队",
    "deal": "团购/套餐",
    "must_order": "必点/招牌菜",
    "rating": "评分/口碑",
    "review_keywords": "评价高频词",
    "business_area": "商圈",
    "category": "门店类型",
    "phone": "商家电话",
    "photos": "门店图片",
}
_LOCAL_FACT_KEYS = tuple(_FACT_FIELD_LABELS.keys()) + ("source_note",)
_LOCAL_FACT_CACHE: tuple[float, str, list[dict]] | None = None


def _truthy_env(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on", "auto"}


def _domain_uses_meituan_travel(domain: str | None) -> bool:
    return (domain or "").strip() in _TRAVEL_FACT_DOMAINS


def _meituan_travel_cli_path() -> str:
    configured = os.environ.get("MEITUAN_TRAVEL_CLI") or os.environ.get("MTTRAVEL_CLI")
    if configured:
        return configured
    return shutil.which("mttravel") or "/opt/homebrew/bin/mttravel"


def _meituan_travel_ready() -> bool:
    if not _truthy_env("NOTEAI_MEITUAN_TRAVEL_ENABLED", "1"):
        return False
    has_token = bool(os.environ.get("MEITUAN_AI_HUB_TOKEN") or os.environ.get("MEITUAN_OPEN_TOKEN"))
    has_config = (Path.home() / ".config" / "meituan-travel" / "config.json").exists()
    cli_path = _meituan_travel_cli_path()
    return (has_token or has_config) and bool(cli_path) and Path(cli_path).exists()


def fact_search_enabled(domain: str | None = None) -> bool:
    if not _truthy_env("NOTEAI_FACT_SEARCH", "1"):
        return False
    return bool(
        _has_authorized_fact_records()
        or (_domain_uses_meituan_travel(domain) and _meituan_travel_ready())
        or os.environ.get("AMAP_WEB_KEY")
        or os.environ.get("BAIDU_MAP_AK")
        or os.environ.get("TENCENT_MAP_KEY")
        or os.environ.get("SERPAPI_API_KEY")
        or os.environ.get("BING_SEARCH_API_KEY")
        or (os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"))
    )


def meituan_credentials_status() -> dict:
    """Report readiness without exposing secret values."""
    token = bool(os.environ.get("MEITUAN_AI_HUB_TOKEN") or os.environ.get("MEITUAN_OPEN_TOKEN"))
    developer_id = bool(os.environ.get("MEITUAN_DEVELOPER_ID"))
    sign_key = bool(os.environ.get("MEITUAN_SIGN_KEY") or os.environ.get("MEITUAN_OPEN_SIGN"))
    app_auth_token = bool(os.environ.get("MEITUAN_APP_AUTH_TOKEN"))
    oauth_fields = {
        "MEITUAN_OPEN_TOKEN": token,
        "MEITUAN_OPEN_APP_KEY": bool(os.environ.get("MEITUAN_OPEN_APP_KEY")),
        "MEITUAN_OPEN_APP_SECRET": bool(os.environ.get("MEITUAN_OPEN_APP_SECRET")),
    }
    mt_tech_fields = {
        "MEITUAN_DEVELOPER_ID": developer_id,
        "MEITUAN_SIGN_KEY": sign_key,
        "MEITUAN_APP_AUTH_TOKEN": app_auth_token,
    }
    enterprise_fields = {
        "MEITUAN_OPEN_TOKEN": token,
        "MEITUAN_OPEN_SIGN": bool(os.environ.get("MEITUAN_OPEN_SIGN")),
        "MEITUAN_OPEN_AES_KEY": bool(os.environ.get("MEITUAN_OPEN_AES_KEY")),
    }
    oauth_ready = all(oauth_fields.values())
    enterprise_ready = all(enterprise_fields.values())
    ai_hub_ready = token
    service_retail_basic_ready = developer_id and sign_key
    service_retail_authorized_ready = all(mt_tech_fields.values())
    return {
        "token_present": token,
        "ai_hub_ready": ai_hub_ready,
        "travel_skill_ready": ai_hub_ready,
        "service_retail_basic_ready": service_retail_basic_ready,
        "service_retail_api_ready": service_retail_authorized_ready or enterprise_ready,
        "oauth_ready": oauth_ready,
        "enterprise_ready": enterprise_ready,
        "ready": ai_hub_ready or oauth_ready or enterprise_ready,
        "missing_for_oauth": [k for k, ok in oauth_fields.items() if not ok],
        "missing_for_mt_tech": [k for k, ok in mt_tech_fields.items() if not ok],
        "missing_for_enterprise": [k for k, ok in enterprise_fields.items() if not ok],
    }


def _clean_text(text: str | None, limit: int = 180) -> str:
    txt = _NOISE_RE.sub(" ", text or "").strip()
    return txt[:limit]


def _redact_secret_values(text: str | None) -> str:
    return _SECRET_QUERY_RE.sub(r"\1<redacted>", text or "")


def _authorized_fact_path() -> Path:
    configured = (
        os.environ.get("NOTEAI_LOCAL_VERIFIED_FACTS_PATH", "").strip()
        or os.environ.get("NOTEAI_AUTHORIZED_FACTS_PATH", "").strip()
    )
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).parent / "data" / "authorized_facts.json"


def _load_authorized_fact_records() -> list[dict]:
    global _LOCAL_FACT_CACHE
    path = _authorized_fact_path()
    if not path.exists():
        return []
    try:
        mtime = path.stat().st_mtime
        cache_key = str(path)
        if _LOCAL_FACT_CACHE and _LOCAL_FACT_CACHE[0] == mtime and _LOCAL_FACT_CACHE[1] == cache_key:
            return _LOCAL_FACT_CACHE[2]
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = raw.get("records", raw) if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            return []
        normalized = [record for record in records if isinstance(record, dict)]
        _LOCAL_FACT_CACHE = (mtime, cache_key, normalized)
        return normalized
    except Exception:
        return []


def _has_authorized_fact_records() -> bool:
    return bool(_load_authorized_fact_records())


def _provider_name(domain: str | None = None) -> str:
    configured = os.environ.get("NOTEAI_FACT_SEARCH_PROVIDER", "").strip().lower()
    if configured and configured not in {"auto", "default"}:
        return configured
    if _domain_uses_meituan_travel(domain) and _meituan_travel_ready():
        return "meituan_travel"
    if os.environ.get("AMAP_WEB_KEY"):
        return "amap"
    if os.environ.get("BAIDU_MAP_AK"):
        return "baidu_map"
    if os.environ.get("TENCENT_MAP_KEY"):
        return "tencent_map"
    if os.environ.get("SERPAPI_API_KEY"):
        return "serpapi"
    if os.environ.get("BING_SEARCH_API_KEY"):
        return "bing"
    if os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"):
        return "google_cse"
    return "none"


def build_fact_query(domain: str | None, title: str | None, text: str | None) -> str:
    src = f"{title or ''} {text or ''}"
    src = re.sub(r"目前没有提供[^。；\n]*", " ", src)
    src = re.sub(r"请只基于[^。；\n]*", " ", src)

    explicit = re.search(r"(?:店名|门店|餐厅|品牌)[:：]\s*([^\n。；;，,]{2,30})", src)
    name = explicit.group(1).strip() if explicit else ""
    if not name:
        m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9·]{2,24}(?:万博店|门店|餐厅|酒家|饭店|茶楼|酒楼|火锅店|烤肉店|咖啡店|茶餐厅|店|楼))", src)
        name = m.group(1).strip() if m else ""
    if not name and "珑厨" in src:
        name = "珑厨万博店" if "万博" in src else "珑厨"

    common_places = _location_hint_values(src)
    places = " ".join(dict.fromkeys(common_places[:4]))
    base = " ".join(part for part in [places, name] if part).strip()
    if not base:
        base = _clean_text(src, 60)
    suffix = "地址 营业时间 人均 预订" if (domain or "") in {"美食", "餐饮", "食品"} else "价格 地址 时间"
    return f"{base} {suffix}".strip()


def _extract_region(text: str | None) -> str:
    src = text or ""
    matches = _location_hint_matches(src)
    if not matches:
        return "全国"
    value = matches[0][0]
    if value in {"番禺", "万博"}:
        return "广州"
    return value


def _location_hint_matches(src: str) -> list[tuple[str, bool]]:
    matches: list[tuple[str, bool]] = []
    for m in _LOCATION_HINT_RE.finditer(src or ""):
        value = m.group(1)
        tail = (src or "")[m.end():m.end() + 2]
        is_road_name = any(tail.startswith(prefix) for prefix in _ROAD_CONTEXT_PREFIXES)
        matches.append((value, is_road_name))
    non_road = [item for item in matches if not item[1]]
    return non_road or matches


def _location_hint_values(src: str, limit: int = 4) -> list[str]:
    values: list[str] = []
    for value, _is_road in _location_hint_matches(src):
        if value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _amap_keyword_from_query(query: str) -> str:
    cleaned = query or ""
    for word in _FACT_QUERY_STOP_WORDS:
        cleaned = re.sub(rf"(?<![\u4e00-\u9fa5A-Za-z0-9]){re.escape(word)}(?![\u4e00-\u9fa5A-Za-z0-9])", " ", cleaned)
    cleaned = _NOISE_RE.sub(" ", cleaned).strip()
    parenthesized = re.search(r"([\u4e00-\u9fa5A-Za-z0-9·.]{2,40})[（(][^\n（）()]{2,40}[)）]", cleaned)
    if parenthesized:
        outside = _clean_text(parenthesized.group(1), 80)
        if len(_amap_norm(outside)) >= 2:
            return outside
    match = _AMAP_STORE_NAME_RE.search(cleaned)
    if match:
        return _clean_text(match.group(1), 80)

    parts = [
        part.strip()
        for part in re.split(r"[\s,，、;；|]+", cleaned)
        if part.strip()
    ]
    candidates = [
        part for part in parts
        if part not in _LOCATION_HINT_WORDS and part not in _FACT_QUERY_STOP_WORDS and len(part) >= 2
    ]
    if candidates:
        return _clean_text(" ".join(candidates[:3]), 80)
    return _clean_text(cleaned, 80)


def _amap_norm(text: str | None) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fa5]+", "", (text or "").lower())


def _amap_core_terms(keyword: str) -> list[str]:
    raw_parts = [
        part
        for part in re.split(r"[\s,，、;；|]+", keyword or "")
        if part.strip()
    ]
    parts = [
        _amap_norm(part)
        for part in raw_parts
    ]
    terms = [part for part in parts if len(part) >= 2 and part not in _LOCATION_HINT_WORDS]
    if len(raw_parts) > 1 and terms:
        return terms[:4]

    compact = _amap_norm(keyword)
    if not compact:
        return []
    core = _AMAP_GENERIC_SUFFIX_RE.sub("", compact)
    for word in sorted(_LOCATION_HINT_WORDS, key=len, reverse=True):
        normalized_word = _amap_norm(word)
        if normalized_word and normalized_word in core and len(core.replace(normalized_word, "")) >= 2:
            core = core.replace(normalized_word, "")
    if len(core) >= 2:
        return [core]
    return [compact] if len(compact) >= 2 else []


def _amap_poi_matches_keyword(poi: dict, keyword: str) -> bool:
    haystack = _amap_norm(
        " ".join(
            _amap_scalar(poi.get(field))
            for field in ("name", "address", "type", "tag", "business_area")
        )
    )
    compact_keyword = _amap_norm(keyword)
    if not compact_keyword:
        return True
    if compact_keyword in haystack:
        return True
    terms = _amap_core_terms(keyword)
    if not terms:
        return True
    return all(term in haystack for term in terms)


def _amap_rank_terms(query: str, keyword: str) -> list[str]:
    terms: list[str] = []
    keyword_terms = set(_amap_core_terms(keyword))
    for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·.]{2,16}", query or ""):
        token_norm = _amap_norm(token)
        if not token_norm or token_norm in _FACT_QUERY_STOP_WORDS:
            continue
        if token_norm in keyword_terms:
            continue
        if token in _FACT_QUERY_STOP_WORDS:
            continue
        if token in _LOCATION_HINT_WORDS or any(place in token for place in _LOCATION_HINT_WORDS) or len(token_norm) <= 6:
            terms.append(token_norm)
    deduped = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped[:8]


def _amap_poi_rank(poi: dict, keyword: str, query: str) -> int:
    title = _amap_norm(_amap_scalar(poi.get("name")))
    category = _amap_scalar(poi.get("type"))
    haystack = _amap_norm(
        " ".join(
            _amap_scalar(poi.get(field))
            for field in ("name", "address", "type", "tag", "business_area")
        )
    )
    compact_keyword = _amap_norm(keyword)
    keyword_terms = _amap_core_terms(keyword)
    score = 0
    if compact_keyword and compact_keyword in title:
        score += 30
    if keyword_terms and all(term in title for term in keyword_terms):
        score += 20
    elif keyword_terms and all(term in haystack for term in keyword_terms):
        score += 10
    if "餐饮服务" in category or "中餐厅" in category or "美食" in category:
        score += 8
    for term in _amap_rank_terms(query, keyword):
        if term in title:
            score += 5
        elif term in haystack:
            score += 3
    return score


def _cache_key(provider: str, query: str) -> str:
    return f"{provider}:{query}"


def _cache_ttl_seconds() -> int:
    try:
        return max(0, int(os.environ.get("NOTEAI_FACT_SEARCH_CACHE_TTL", "0") or "0"))
    except ValueError:
        return 0


def _normalize_fact_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return _clean_text("、".join(str(v) for v in value if str(v).strip()), 220)
    if isinstance(value, dict):
        return _clean_text("；".join(f"{k}:{v}" for k, v in value.items() if str(v).strip()), 220)
    return _clean_text(str(value), 220)


def _amap_scalar(value) -> str:
    """Amap returns missing scalar fields as [] in some responses."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return ""
    return _clean_text(str(value), 220)


def _format_amap_cost(value) -> str:
    cost = _amap_scalar(value)
    if not cost:
        return ""
    normalized = cost.rstrip("0").rstrip(".") if "." in cost else cost
    if not re.search(r"\d", normalized):
        return ""
    if "元" in normalized or "人均" in normalized:
        return normalized
    return f"人均{normalized}元"


def _format_amap_rating(value) -> str:
    rating = _amap_scalar(value)
    if not rating or not re.search(r"\d", rating):
        return ""
    return rating if "评分" in rating else f"高德评分{rating}"


def _format_amap_photos(value) -> str:
    if not isinstance(value, list) or not value:
        return ""
    titles = []
    for photo in value[:3]:
        if isinstance(photo, dict):
            title = _amap_scalar(photo.get("title"))
            if title:
                titles.append(title)
    if titles:
        return f"{len(value)}张高德门店图片（{_clean_text('、'.join(titles), 80)}）"
    return f"{len(value)}张高德门店图片"


def _amap_poi_facts(poi: dict) -> dict:
    biz = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
    business = poi.get("business") if isinstance(poi.get("business"), dict) else {}
    facts: dict[str, str] = {}
    field_pairs = [
        ("address", _amap_scalar(poi.get("address"))),
        ("business_area", _amap_scalar(poi.get("business_area") or business.get("business_area"))),
        ("category", _amap_scalar(poi.get("type"))),
        ("phone", _amap_scalar(poi.get("tel") or business.get("tel"))),
        ("hours", _amap_scalar(
            biz.get("opentime")
            or biz.get("opentime_week")
            or biz.get("opentime_today")
            or business.get("opentime_today")
            or business.get("opentime_week")
        )),
        ("price", _format_amap_cost(biz.get("cost") or business.get("cost"))),
        ("rating", _format_amap_rating(biz.get("rating") or business.get("rating"))),
        ("must_order", _amap_scalar(poi.get("tag") or business.get("tag"))),
        ("photos", _format_amap_photos(poi.get("photos"))),
    ]
    for key, value in field_pairs:
        if value:
            facts[key] = value

    if _amap_scalar(biz.get("meal_ordering")) == "1":
        facts["booking"] = "高德显示支持订餐/预订"
    if facts.get("must_order") and not facts.get("review_keywords"):
        facts["review_keywords"] = facts["must_order"]
    return facts


def _merge_amap_detail(base: dict, detail: dict) -> dict:
    merged = dict(base)
    for key, value in detail.items():
        if key == "business" and isinstance(value, dict):
            current = merged.get("business") if isinstance(merged.get("business"), dict) else {}
            merged["business"] = {**current, **{k: v for k, v in value.items() if v not in (None, "", [])}}
        elif key == "photos" and isinstance(value, list) and value:
            merged["photos"] = value
        elif value not in (None, "", []) and not merged.get(key):
            merged[key] = value
    return merged


def _amap_fetch_v5_detail(client: httpx.Client, key: str, poi_id: str) -> dict:
    if not poi_id:
        return {}
    try:
        resp = client.get(
            "https://restapi.amap.com/v5/place/detail",
            params={
                "key": key,
                "id": poi_id,
                "show_fields": "business,photos",
                "output": "json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        pois = data.get("pois") if isinstance(data, dict) else None
        if isinstance(pois, list) and pois and isinstance(pois[0], dict):
            return pois[0]
    except Exception:
        return {}
    return {}


def _amap_poi_to_item(poi: dict) -> dict:
    facts = _amap_poi_facts(poi)
    snippet_parts = [
        _amap_scalar(poi.get("name")),
        *[
            f"{_FACT_FIELD_LABELS.get(key, key)}：{value}"
            for key, value in facts.items()
            if key in _FACT_FIELD_LABELS and key != "photos"
        ],
    ]
    return {
        "title": _amap_scalar(poi.get("name")),
        "url": f"amap://poi/{poi.get('id', '')}" if poi.get("id") else "",
        "snippet": _clean_text(" ".join(part for part in snippet_parts if part), 500),
        "source": "高德地图",
        "facts": facts,
    }


def _record_match_score(record: dict, haystack: str, domain: str | None) -> int:
    score = 0
    rec_domain = str(record.get("domain", "")).strip()
    if rec_domain and domain and rec_domain not in {domain, "通用"}:
        score -= 2

    names = [record.get("name", ""), record.get("brand", ""), record.get("shop_name", "")]
    aliases = record.get("aliases") or record.get("keywords") or []
    if isinstance(aliases, str):
        aliases = [aliases]

    identity_tokens = [
        str(token or "").strip()
        for token in [*names, *aliases]
        if str(token or "").strip()
    ]
    haystack_norm = _amap_norm(haystack)
    identity_matched = False
    for token in identity_tokens:
        token_norm = _amap_norm(token)
        if len(token_norm) >= 2 and token_norm in haystack_norm:
            identity_matched = True
            break

    # A local verified record is stronger than map search, but only when the
    # submitted material identifies the same shop/brand. City or business-area
    # overlap alone is too broad and can leak another merchant's facts.
    if identity_tokens and not identity_matched:
        return 0

    for token in [*names, *aliases, record.get("city", ""), record.get("business_area", "")]:
        token = str(token or "").strip()
        if token and token in haystack:
            score += 3 if token in names else 1

    facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
    for key in ("address", "deal", "must_order", "review_keywords"):
        value = _normalize_fact_value(facts.get(key) or record.get(key))
        parts = [part for part in re.split(r"[、,，；; ]+", value) if len(part) >= 2]
        if any(part in haystack for part in parts[:8]):
            score += 1
    return score


def _authorized_fact_items(domain: str | None, title: str | None, text: str | None, query: str) -> list[dict]:
    haystack = _clean_text(f"{title or ''} {text or ''} {query}", 1200)
    matched: list[tuple[int, dict]] = []
    for record in _load_authorized_fact_records():
        score = _record_match_score(record, haystack, domain)
        if score <= 0:
            continue
        facts_src = record.get("facts") if isinstance(record.get("facts"), dict) else {}
        facts = {}
        for key in _LOCAL_FACT_KEYS:
            normalized = _normalize_fact_value(facts_src.get(key, record.get(key)))
            if normalized:
                facts[key] = normalized
        title_text = _clean_text(record.get("name") or record.get("shop_name") or record.get("brand") or "核验事实", 80)
        source_label = _clean_text(record.get("source") or record.get("platform") or "本地核验事实库", 40)
        captured_at = _clean_text(record.get("captured_at") or record.get("updated_at") or "", 30)
        snippet = " ".join(f"{_FACT_FIELD_LABELS.get(k, k)}：{v}" for k, v in facts.items() if k in _FACT_FIELD_LABELS)
        if captured_at:
            snippet += f" 核验时间：{captured_at}"
        matched.append((score, {
            "title": title_text,
            "url": record.get("url", ""),
            "snippet": _clean_text(snippet, 500),
            "source": source_label,
            "facts": facts,
        }))
    matched.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in matched[:3]]


def _search_serpapi(query: str) -> list[dict]:
    key = os.environ.get("SERPAPI_API_KEY", "")
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        resp = client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "hl": "zh-cn", "gl": "cn", "num": 6, "api_key": key},
        )
        resp.raise_for_status()
        data = resp.json()
    items: list[dict] = []
    for item in data.get("organic_results", [])[:6]:
        items.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    local = data.get("local_results") or data.get("place_results") or {}
    if isinstance(local, dict) and local:
        items.insert(0, {
            "title": local.get("title", ""),
            "url": local.get("website") or local.get("link") or "",
            "snippet": " ".join(str(local.get(k, "")) for k in ("address", "phone", "hours", "description")),
        })
    return items


def _search_amap(query: str) -> list[dict]:
    key = os.environ.get("AMAP_WEB_KEY", "")
    region = _extract_region(query)
    keyword = _amap_keyword_from_query(query)
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        resp = client.get(
            "https://restapi.amap.com/v3/place/text",
            params={
                "key": key,
                "keywords": keyword or query,
                "city": "" if region == "全国" else region,
                "citylimit": "false" if region == "全国" else "true",
                "extensions": "all",
                "offset": 6,
                "page": 1,
                "output": "json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    ranked_pois: list[dict] = []
    for poi in data.get("pois", [])[:6]:
        if isinstance(poi, dict) and _amap_poi_matches_keyword(poi, keyword):
            ranked_pois.append(poi)
    ranked_pois.sort(key=lambda item: _amap_poi_rank(item, keyword, query), reverse=True)

    enriched_pois: list[dict] = []
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        for poi in ranked_pois[:3]:
            detail = _amap_fetch_v5_detail(client, key, _amap_scalar(poi.get("id")))
            enriched_pois.append(_merge_amap_detail(poi, detail) if detail else poi)
    return [_amap_poi_to_item(poi) for poi in enriched_pois]


def _search_meituan_travel(query: str) -> list[dict]:
    cli_path = _meituan_travel_cli_path()
    region = _extract_region(query)
    if not Path(cli_path).exists():
        return []
    completed = subprocess.run(
        [cli_path, region if region != "全国" else "中国", query],
        capture_output=True,
        text=True,
        timeout=max(30, int(_MEITUAN_TRAVEL_TIMEOUT_SECONDS)),
        check=False,
    )
    output = _redact_secret_values("\n".join(part for part in [completed.stdout, completed.stderr] if part))
    if completed.returncode != 0:
        raise RuntimeError(_clean_text(output or f"meituan-travel exited {completed.returncode}", 160))
    snippet = _clean_text(output, 1200)
    if not snippet:
        return []
    urls = re.findall(r"https?://[^\s)）]+", snippet)
    first_line = next((line.strip() for line in snippet.splitlines() if line.strip()), "")
    return [{
        "title": _clean_text(first_line or "美团酒旅事实", 80),
        "url": urls[0] if urls else "",
        "snippet": snippet,
        "source": "美团酒旅",
    }]


def _search_baidu_map(query: str) -> list[dict]:
    ak = os.environ.get("BAIDU_MAP_AK", "")
    region = _extract_region(query)
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        resp = client.get(
            "https://api.map.baidu.com/place/v2/search",
            params={
                "ak": ak,
                "query": query,
                "region": region,
                "city_limit": "false" if region == "全国" else "true",
                "output": "json",
                "scope": 2,
                "page_size": 6,
                "page_num": 0,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    items: list[dict] = []
    for poi in data.get("results", [])[:6]:
        detail = poi.get("detail_info") if isinstance(poi.get("detail_info"), dict) else {}
        snippet_parts = [
            poi.get("name", ""),
            poi.get("address", ""),
            poi.get("telephone", ""),
            detail.get("tag", ""),
            detail.get("price", ""),
            detail.get("overall_rating", ""),
            detail.get("shop_hours", "") or detail.get("opening_hours", ""),
        ]
        items.append({
            "title": poi.get("name", ""),
            "url": detail.get("detail_url", "") or (f"baidumap://poi/{poi.get('uid', '')}" if poi.get("uid") else ""),
            "snippet": " ".join(str(part) for part in snippet_parts if part),
            "source": "百度地图",
        })
    return items


def _search_tencent_map(query: str) -> list[dict]:
    key = os.environ.get("TENCENT_MAP_KEY", "")
    region = _extract_region(query)
    boundary = "region(全国,0)" if region == "全国" else f"region({region},0)"
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        resp = client.get(
            "https://apis.map.qq.com/ws/place/v1/search",
            params={
                "key": key,
                "keyword": query,
                "boundary": boundary,
                "page_size": 6,
                "page_index": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    items: list[dict] = []
    for poi in data.get("data", [])[:6]:
        snippet_parts = [
            poi.get("title", ""),
            poi.get("address", ""),
            poi.get("tel", ""),
            poi.get("category", ""),
        ]
        items.append({
            "title": poi.get("title", ""),
            "url": f"qqmap://poi/{poi.get('id', '')}" if poi.get("id") else "",
            "snippet": " ".join(str(part) for part in snippet_parts if part),
            "source": "腾讯地图",
        })
    return items


def _search_bing(query: str) -> list[dict]:
    key = os.environ.get("BING_SEARCH_API_KEY", "")
    endpoint = os.environ.get("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search")
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        resp = client.get(
            endpoint,
            headers={"Ocp-Apim-Subscription-Key": key},
            params={"q": query, "mkt": "zh-CN", "count": 6, "responseFilter": "Webpages"},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"title": item.get("name", ""), "url": item.get("url", ""), "snippet": item.get("snippet", "")}
        for item in data.get("webPages", {}).get("value", [])[:6]
    ]


def _search_google_cse(query: str) -> list[dict]:
    key = os.environ.get("GOOGLE_API_KEY", "")
    cx = os.environ.get("GOOGLE_CSE_ID", "")
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        resp = client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": key, "cx": cx, "q": query, "num": 6, "hl": "zh-CN"},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")}
        for item in data.get("items", [])[:6]
    ]


def _search(query: str, provider: str | None = None) -> tuple[str, list[dict]]:
    provider = provider or _provider_name()
    if provider == "meituan_travel":
        return provider, _search_meituan_travel(query)
    if provider == "amap":
        return provider, _search_amap(query)
    if provider == "baidu_map":
        return provider, _search_baidu_map(query)
    if provider == "tencent_map":
        return provider, _search_tencent_map(query)
    if provider == "serpapi":
        return provider, _search_serpapi(query)
    if provider == "bing":
        return provider, _search_bing(query)
    if provider == "google_cse":
        return provider, _search_google_cse(query)
    return provider, []


def _pick_first(pattern: re.Pattern, texts: list[str]) -> str:
    for text in texts:
        m = pattern.search(text)
        if m:
            return _clean_text(m.group(0), 120)
    return ""


def extract_facts_from_search_items(items: list[dict]) -> dict:
    texts = [
        _clean_text(f"{item.get('title', '')}。{item.get('snippet', '')}", 500)
        for item in items
    ]
    facts: dict[str, str] = {}
    for item in items:
        item_facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
        for key in _LOCAL_FACT_KEYS:
            normalized = _normalize_fact_value(item_facts.get(key))
            if normalized and not facts.get(key):
                facts[key] = normalized
    regex_facts = {
        "address": _pick_first(_ADDRESS_RE, texts),
        "price": _pick_first(_PRICE_RE, texts),
        "hours": _pick_first(_HOURS_RE, texts),
        "booking": _pick_first(_BOOKING_RE, texts),
        "deal": _pick_first(_DEAL_RE, texts),
        "must_order": _pick_first(_MUST_ORDER_RE, texts),
        "rating": _pick_first(_RATING_RE, texts),
        "review_keywords": _pick_first(_REVIEW_KEYWORDS_RE, texts),
    }
    for key, value in regex_facts.items():
        if value and not facts.get(key):
            facts[key] = value
    return {k: v for k, v in facts.items() if v}


def _provider_label(search_provider: str, local_items: list[dict]) -> str:
    labels = []
    if local_items:
        labels.append("local_verified")
    if search_provider and search_provider != "none":
        labels.append(search_provider)
    return "+".join(labels) or search_provider or "none"


def _search_enabled_for_provider(provider: str) -> bool:
    return provider in {"meituan_travel", "amap", "baidu_map", "tencent_map", "serpapi", "bing", "google_cse"}


def _merge_sources(items: list[dict]) -> list[dict]:
    sources = []
    seen = set()
    for item in items[:8]:
        url = item.get("url", "")
        title = _clean_text(item.get("title", ""), 80)
        key = (title, url)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "title": title,
            "url": url,
            "domain": urlparse(url).netloc,
            "source": _clean_text(item.get("source", ""), 40),
            "snippet": _clean_text(item.get("snippet", ""), 180),
        })
        if len(sources) >= 5:
            break
    return sources


def enrich_content_facts(domain: str | None, title: str | None, text: str | None) -> dict:
    query = build_fact_query(domain, title, text)
    provider = _provider_name(domain)
    if not fact_search_enabled(domain):
        return {"enabled": False, "provider": provider, "query": query, "facts": {}, "sources": [], "confidence": 0.0}

    ttl = _cache_ttl_seconds()
    key = _cache_key(provider, query)
    now = time.time()
    cached = _CACHE.get(key) if ttl > 0 else None
    if cached and now - cached[0] < ttl:
        result = dict(cached[1])
        result["cached"] = True
        return result

    local_items = _authorized_fact_items(domain, title, text, query)
    items = list(local_items)
    search_provider = provider
    try:
        if _search_enabled_for_provider(provider):
            search_provider, provider_items = _search(query, provider)
            items.extend(provider_items)
    except Exception as exc:
        if not local_items:
            return {
                "enabled": True,
                "provider": _provider_label(search_provider, local_items),
                "query": query,
                "facts": {},
                "sources": [],
                "confidence": 0.0,
                "error": _redact_secret_values(str(exc))[:160],
            }

    sources = _merge_sources(items)
    facts = extract_facts_from_search_items(items)
    confidence = min(0.9, 0.35 + 0.12 * len(facts) + 0.04 * min(len(sources), 5))
    result = {
        "enabled": True,
        "provider": _provider_label(search_provider, local_items),
        "query": query,
        "facts": facts,
        "sources": sources,
        "confidence": round(confidence if facts else 0.2 if sources else 0.0, 2),
        "cached": False,
    }
    if ttl > 0:
        _CACHE[key] = (now, result)
    return result


def format_fact_context(enrichment: dict | None) -> str:
    if not enrichment or not enrichment.get("facts"):
        return ""
    facts = enrichment.get("facts") or {}
    lines = [
        "【联网事实补全】",
        f"查询：{enrichment.get('query', '')}",
        f"事实源：{enrichment.get('provider', '')}",
        f"置信度：{enrichment.get('confidence', 0)}；来源数量：{len(enrichment.get('sources') or [])}",
        "已提取字段（只能引用这里列出的事实；未列出的字段不得编造）：",
    ]
    for key, label in _FACT_FIELD_LABELS.items():
        if facts.get(key):
            lines.append(f"- {label}：{facts[key]}")
    if enrichment.get("sources"):
        lines.append("来源：")
        for idx, src in enumerate(enrichment["sources"][:3], 1):
            source = src.get("source") or src.get("domain") or "事实源"
            lines.append(f"{idx}. {source} - {src.get('title') or src.get('domain')}: {src.get('url')}")
    return "\n".join(lines)
