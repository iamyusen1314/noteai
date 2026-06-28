#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mine supplemental first-core-domain golden candidates from raw RedNote data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_domain_policy import CORE_PRODUCT_DOMAINS, canonical_product_domains  # noqa: E402


VERSION = "core-domain-supplement-queue-v0.1"

DEFAULT_RAW_DIR = ROOT / "model" / "data" / "rednote_vibe_raw" / "20260625T062120Z_a9bc6e296549"
DEFAULT_MAIN_QUEUE = ROOT / "quality" / "annotation_queue.v01.jsonl"
DEFAULT_OUTPUT_JSONL = ROOT / "quality" / "annotation_queue.v01.core_supplement.jsonl"
DEFAULT_OUTPUT_CSV = ROOT / "quality" / "annotation_queue.v01.core_supplement.csv"
DEFAULT_REPORT = ROOT / "quality" / "annotation_queue.v01.core_supplement.report.json"

RAW_FILES = ("training_set_human.jsonl", "exploring_set.jsonl")
DEFAULT_DOMAINS = CORE_PRODUCT_DOMAINS

DOMAIN_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "美食": {
        "core": (
            "美食", "餐厅", "饭店", "探店", "必点", "招牌", "菜品", "菜单", "火锅", "烤肉",
            "咖啡", "甜品", "面包", "早茶", "粤菜", "川菜", "日料", "西餐", "小吃", "宵夜",
            "人均", "套餐", "团购", "口味", "复购", "排队", "店名", "地址",
        ),
        "context": ("好吃", "味道", "服务", "环境", "营业", "地铁", "停车", "新店", "聚餐", "约会", "外卖"),
    },
    "旅行": {
        "core": (
            "旅行", "旅游", "攻略", "行程", "路线", "景点", "酒店", "民宿", "住宿", "度假",
            "周末游", "自驾", "高铁", "机票", "签证", "海岛", "城市", "亲子游", "打卡", "门票",
        ),
        "context": ("预算", "人均", "交通", "避坑", "季节", "机场", "预约", "推荐", "不推荐", "天", "夜"),
    },
    "穿搭": {
        "core": (
            "穿搭", "搭配", "上衣", "裤子", "裙子", "外套", "衬衫", "牛仔裤", "连衣裙", "半裙",
            "鞋子", "包包", "配色", "显瘦", "显高", "通勤", "小个子", "梨形", "苹果型", "OOTD", "ootd",
        ),
        "context": ("面料", "版型", "尺码", "身高", "体重", "胯宽", "肩宽", "质感", "平价", "百搭", "风格"),
    },
    "美妆": {
        "core": (
            "粉底", "口红", "腮红", "眼影", "遮瑕", "散粉", "底妆", "妆效", "持妆", "色号",
            "卸妆", "护肤", "面霜", "精华", "防晒", "睫毛", "眉笔", "化妆", "上脸", "干皮", "油皮", "敏感肌",
            "彩妆", "妆容", "眼妆", "唇釉", "唇泥", "唇膏", "唇彩", "高光", "修容", "定妆",
            "气垫", "隔离", "素颜霜", "面膜", "水乳", "爽肤水", "洁面", "洗面奶", "刷酸",
            "痘痘", "痘肌", "混油", "混干", "黄黑皮", "冷白皮", "瑕疵皮", "毛孔", "抗老",
            "美白", "去黑头", "黑眼圈", "香水", "美甲", "染发", "发色",
        ),
        "context": (
            "显白", "服帖", "不浮粉", "卡粉", "试色", "肤质", "肤色", "质地", "用量",
            "控油", "暗沉", "泛红", "修护", "保湿", "脱妆", "氧化", "成分", "清爽",
        ),
    },
    "家居": {
        "core": (
            "家居", "收纳", "客厅", "卧室", "厨房", "装修", "改造", "软装", "柜子", "沙发",
            "窗帘", "户型", "出租屋", "餐边柜", "书桌", "床头", "阳台", "玄关", "浴室", "清单",
            "租房", "房间", "房子", "小家", "布置", "家具", "家电", "冰箱", "洗衣机", "收纳盒",
            "清洁", "扫地机器人", "床垫", "四件套", "香薰", "餐具", "锅具", "厨房好物", "家务",
            "卫生间", "浴室柜", "书房", "衣柜", "橱柜", "硬装", "全屋", "家装", "餐厅", "地毯",
            "灯具", "台灯", "茶几", "餐桌", "床头柜", "置物架",
            "新家", "我家", "装修日记", "入住", "室内", "电视柜", "岛台", "卫浴", "马桶",
            "淋浴", "花洒", "瓷砖", "地板", "墙面", "乳胶漆", "榻榻米", "飘窗", "洗衣区",
            "洗碗机", "烤箱", "微波炉", "空气炸锅", "小户型", "大平层", "餐椅", "床品",
        ),
        "context": (
            "预算", "面积", "动线", "布局", "置物", "宜家", "全屋", "入住", "好物", "平替",
            "断舍离", "小户型", "显大", "甲醛", "施工", "物业", "水电", "尺寸", "材质",
            "设计", "空间", "动线", "安装", "避坑", "落地", "显乱", "省空间", "氛围感",
        ),
    },
    "母婴": {
        "core": (
            "宝宝", "月龄", "辅食", "婴儿", "幼儿", "孕期", "宝妈", "育儿", "纸尿裤", "奶粉",
            "亲子", "儿童", "新生儿", "哺乳", "早教", "绘本", "过敏", "发烧", "奶瓶", "推车",
            "孩子", "小朋友", "儿子", "女儿", "怀孕", "孕妈", "孕妇", "胎儿", "待产包",
            "产后", "坐月子", "月子", "母乳", "喂奶", "断奶", "尿不湿", "拉拉裤",
            "安抚", "婴儿车", "幼儿园", "入园", "带娃",
        ),
        "context": (
            "安全", "剂量", "观察", "身高", "体重", "喂养", "睡眠", "入园", "产检",
            "长高", "湿疹", "积食", "咳嗽", "腹泻", "亲子游", "儿童乐园", "分离焦虑",
        ),
    },
    "健身": {
        "core": (
            "健身", "训练", "动作", "腹肌", "臀腿", "背部", "肩部", "胸肌", "有氧", "力量",
            "瑜伽", "普拉提", "跑步", "减脂", "增肌", "体脂", "饮食", "蛋白质", "热量", "拉伸",
            "组", "次",
        ),
        "context": ("计划", "新手", "训练量", "重量", "频率", "打卡", "注意", "避免", "受伤", "姿势", "目标"),
    },
}

ANNOTATION_COLUMNS = [
    "annotation_id",
    "version",
    "human_label_status",
    "priority",
    "domain",
    "sample_bucket",
    "sample_source",
    "source_type",
    "source_file",
    "source_row",
    "note_id",
    "title",
    "body",
    "body_char_len",
    "liked_count",
    "collected_count",
    "comments_count",
    "ces_raw",
    "ces_percentile",
    "domain_match_score",
    "domain_match_terms",
    "human_quality_score",
    "delivery_ready",
    "naturalness_label",
    "hook_quality",
    "body_value",
    "industry_fit",
    "fact_status",
    "ai_smell_level",
    "failure_tags",
    "rationale",
    "reviewer",
    "reviewed_at",
    "text_hash",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(*parts: Any, length: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(float(str(value or "0").replace(",", "").strip())))
    except Exception:
        return 0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _text_hash(title: str, body: str) -> str:
    return _stable_hash(title.strip(), body.strip(), length=16)


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row["_source_row"] = idx
            rows.append(row)
    return rows


def _load_existing_text_hashes(path: Path) -> set[str]:
    hashes: set[str] = set()
    for row in _iter_jsonl(path):
        if row.get("text_hash"):
            hashes.add(str(row["text_hash"]))
            continue
        title = _clean_text(row.get("title") or row.get("note_title"))
        body = _clean_text(row.get("body") or row.get("desc") or row.get("note_content"))
        hashes.add(_text_hash(title, body))
    return hashes


def _domain_match(title: str, body: str, domain: str) -> tuple[int, list[str], int]:
    rules = DOMAIN_RULES[domain]
    title_hits: list[str] = []
    body_hits: list[str] = []
    context_hits: list[str] = []
    for word in rules["core"]:
        if word in title:
            title_hits.append(word)
        if word in body:
            body_hits.append(word)
    for word in rules["context"]:
        if word in title or word in body:
            context_hits.append(word)
    score = len(set(title_hits)) * 5 + len(set(body_hits)) * 2 + len(set(context_hits))
    core_hit_count = len(set(title_hits + body_hits))
    return score, sorted(set(title_hits + body_hits + context_hits)), core_hit_count


def _engagement(row: dict[str, Any]) -> float:
    liked = _safe_int(row.get("liked_count") or row.get("likes"))
    collected = _safe_int(row.get("collected_count") or row.get("collects"))
    comments = _safe_int(row.get("comments_count") or row.get("comments"))
    return math.log1p(liked + collected * 1.5 + comments * 2.0)


def _priority(match_score: int, engagement: float) -> str:
    if match_score >= 12 or engagement >= 5:
        return "high"
    if match_score >= 8 or engagement >= 3:
        return "medium"
    return "normal"


def _candidate_row(
    *,
    domain: str,
    source_file: str,
    source_type: str,
    row: dict[str, Any],
    sequence: int,
    match_score: int,
    match_terms: list[str],
) -> dict[str, Any]:
    title = _clean_text(row.get("note_title") or row.get("title"))
    body = _clean_text(row.get("desc") or row.get("body") or row.get("note_content"))
    note_id = _clean_text(row.get("note_id")) or f"{source_file}:{row.get('_source_row', sequence)}"
    text_hash = _text_hash(title, body)
    liked = _safe_int(row.get("liked_count") or row.get("likes"))
    collected = _safe_int(row.get("collected_count") or row.get("collects"))
    comments = _safe_int(row.get("comments_count") or row.get("comments"))
    engagement = _engagement(row)
    annotation_id = f"gq01s_{_stable_hash(domain, note_id, text_hash, length=16)}"
    return {
        "annotation_id": annotation_id,
        "version": VERSION,
        "human_label_status": "needs_label",
        "priority": _priority(match_score, engagement),
        "domain": domain,
        "sample_bucket": "core_domain_supplement",
        "sample_source": "rednote_raw_keyword_mining",
        "source_type": source_type,
        "source_file": source_file,
        "source_row": int(row.get("_source_row") or 0),
        "note_id": note_id,
        "title": title,
        "body": body,
        "body_char_len": len(body),
        "liked_count": liked,
        "collected_count": collected,
        "comments_count": comments,
        "ces_raw": float(liked + collected + comments),
        "ces_percentile": 0.0,
        "domain_match_score": match_score,
        "domain_match_terms": "|".join(match_terms),
        "human_quality_score": "",
        "delivery_ready": "",
        "naturalness_label": "",
        "hook_quality": "",
        "body_value": "",
        "industry_fit": "",
        "fact_status": "",
        "ai_smell_level": "",
        "failure_tags": "",
        "rationale": "",
        "reviewer": "",
        "reviewed_at": "",
        "text_hash": text_hash,
    }


def build_supplement_queue(
    *,
    raw_dir: Path,
    domains: list[str],
    existing_queue: Path,
    per_domain: int,
    min_score: int,
    min_body_chars: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    existing_hashes = _load_existing_text_hashes(existing_queue)
    candidates_by_domain: dict[str, list[dict[str, Any]]] = {domain: [] for domain in domains}
    seen_text = set(existing_hashes)
    scanned_rows = 0
    short_or_duplicate = 0
    weak_match = 0

    for raw_name in RAW_FILES:
        raw_path = raw_dir / raw_name
        source_type = "human" if raw_name == "training_set_human.jsonl" else "exploration"
        for row in _iter_jsonl(raw_path):
            scanned_rows += 1
            title = _clean_text(row.get("note_title") or row.get("title"))
            body = _clean_text(row.get("desc") or row.get("body") or row.get("note_content"))
            if len(body) < min_body_chars:
                short_or_duplicate += 1
                continue
            text_hash = _text_hash(title, body)
            if text_hash in seen_text:
                short_or_duplicate += 1
                continue
            best_match: tuple[int, str, list[str]] | None = None
            for domain in domains:
                score, terms, core_hits = _domain_match(title, body, domain)
                if score < min_score or core_hits < 2:
                    continue
                if best_match is None or score > best_match[0]:
                    best_match = (score, domain, terms)
            if best_match:
                score, domain, terms = best_match
                candidates_by_domain[domain].append(
                    _candidate_row(
                        domain=domain,
                        source_file=raw_name,
                        source_type=source_type,
                        row=row,
                        sequence=len(candidates_by_domain[domain]) + 1,
                        match_score=score,
                        match_terms=terms,
                    )
                )
                seen_text.add(text_hash)
            else:
                weak_match += 1

    rows: list[dict[str, Any]] = []
    shortfalls: list[dict[str, Any]] = []
    for domain in domains:
        candidates = candidates_by_domain[domain]
        candidates.sort(
            key=lambda row: (
                {"high": 0, "medium": 1, "normal": 2}.get(str(row["priority"]), 9),
                -int(row["domain_match_score"]),
                -int(row["liked_count"]) - int(row["collected_count"]) - int(row["comments_count"]),
                str(row["annotation_id"]),
            )
        )
        selected = candidates[:per_domain]
        rows.extend(selected)
        if len(selected) < per_domain:
            shortfalls.append(
                {
                    "domain": domain,
                    "target": per_domain,
                    "available": len(candidates),
                    "selected": len(selected),
                }
            )

    report = {
        "version": VERSION,
        "created_at": _now_iso(),
        "status": "supplement_queue_needs_human_labels",
        "inputs": {
            "raw_dir": str(raw_dir),
            "existing_queue": str(existing_queue),
            "raw_files": list(RAW_FILES),
        },
        "params": {
            "domains": domains,
            "per_domain": per_domain,
            "min_score": min_score,
            "min_body_chars": min_body_chars,
        },
        "totals": {
            "scanned_rows": scanned_rows,
            "selected_rows": len(rows),
            "short_or_duplicate_rows": short_or_duplicate,
            "weak_match_rows": weak_match,
        },
        "by_domain_selected": {
            domain: len([row for row in rows if row["domain"] == domain])
            for domain in domains
        },
        "by_domain_available": {
            domain: len(candidates_by_domain[domain])
            for domain in domains
        },
        "shortfalls": shortfalls,
        "policy": "Supplement rows are candidates only; they require human labels before training.",
    }
    return rows, report


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            line = line.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            fh.write(line + "\n")


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ANNOTATION_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine supplemental core-domain labeling candidates")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--existing-queue", type=Path, default=DEFAULT_MAIN_QUEUE)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--domains", default=",".join(DEFAULT_DOMAINS))
    parser.add_argument("--per-domain", type=int, default=120)
    parser.add_argument("--min-score", type=int, default=7)
    parser.add_argument("--min-body-chars", type=int, default=80)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_dir = args.raw_dir if args.raw_dir.is_absolute() else ROOT / args.raw_dir
    existing_queue = args.existing_queue if args.existing_queue.is_absolute() else ROOT / args.existing_queue
    output_jsonl = args.output_jsonl if args.output_jsonl.is_absolute() else ROOT / args.output_jsonl
    output_csv = args.output_csv if args.output_csv.is_absolute() else ROOT / args.output_csv
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    domains = canonical_product_domains(part.strip() for part in args.domains.split(",") if part.strip())
    rows, report = build_supplement_queue(
        raw_dir=raw_dir,
        domains=domains,
        existing_queue=existing_queue,
        per_domain=args.per_domain,
        min_score=args.min_score,
        min_body_chars=args.min_body_chars,
    )
    report["outputs"] = {
        "jsonl": str(output_jsonl),
        "csv": str(output_csv),
        "report": str(report_path),
    }
    write_jsonl(rows, output_jsonl)
    write_csv(rows, output_csv)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"rows={report['totals']['selected_rows']}")
        print(f"by_domain={report['by_domain_selected']}")
        print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
