"""Pure managed-Prompt composition shared by the user API and Admin preview."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


SUPPORTED_DOMAINS = ("美食", "旅行", "穿搭", "美妆", "家居", "健身", "母婴")
_DOMAIN_ALIASES = {
    "餐饮": "美食",
    "食品": "美食",
    "运动健身": "健身",
    "亲子": "母婴",
}

LEGACY_PROMPT_PATTERN = re.compile(
    r"(?i)(?:v\s*0\.3(?:\s*模型)?|(?<![A-Za-z0-9_])CES(?:\s*[≥<]=?\s*\d+(?:\.\d+)?)?(?![A-Za-z0-9_])|\d+(?:\.\d+)?%\s*权重)"
)

_LEGACY_REPLACEMENTS = (
    (re.compile(r"(?i)v\s*0\.3(?:\s*模型)?(?:各品类高分笔记真实基准)?"), "历史辅助评分器"),
    (re.compile(r"(?i)(?<![A-Za-z0-9_])CES\s*≥\s*70(?![A-Za-z0-9_])"), "高质量可交付"),
    (re.compile(r"(?i)(?<![A-Za-z0-9_])CES\s*<\s*40(?![A-Za-z0-9_])"), "低质量不可交付"),
    (re.compile(r"(?i)(?<![A-Za-z0-9_])CES(?:分位)?(?![A-Za-z0-9_])"), "历史互动分位遥测"),
    (re.compile(r"\d+(?:\.\d+)?%\s*权重"), "辅助信号"),
    (re.compile(r"最重要单一特征"), "重要辅助特征"),
    (re.compile(r"缺一必补"), "有事实来源时优先补充"),
)

_DYNAMIC_LAYER_LABELS = (
    "统一质量契约",
    "62维特征治理",
    "行业知识与生成规划",
    "当前请求事实与素材",
    "市场时机与关键词证据",
    "用户约束与授权记忆",
)


@dataclass(frozen=True)
class PromptLayer:
    name: str
    content: str
    source: str = "runtime"
    dynamic: bool = False


@dataclass(frozen=True)
class ComposedPrompt:
    text: str
    domain: str
    layers: tuple[PromptLayer, ...]
    preview_complete: bool


def canonicalize_domain(domain: str | None, *, allow_other: bool = False) -> str:
    value = (domain or "").strip()
    value = _DOMAIN_ALIASES.get(value, value)
    if value in SUPPORTED_DOMAINS:
        return value
    if allow_other and re.fullmatch(r"[\w\u3400-\u9fff-]{1,24}", value):
        return value
    raise ValueError("unsupported prompt preview domain")


def neutralize_legacy_prompt_conflicts(prompt: str) -> str:
    text = prompt or ""
    for pattern, replacement in _LEGACY_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    text = re.sub(
        r"(?ms)^数据来源说明：.*?(?=\n\n|\Z)",
        "数据来源说明：历史统计仅作辅助参考；当前策略以交付价值、事实可信、自然表达和人工偏好为主。",
        text,
    )
    return text


def v04_runtime_prefix(key: str, domain: str) -> str:
    return (
        f"【V0.4运行时最高优先级覆盖｜{key}｜{domain}】\n"
        "- 当前链路服务 NoteAI V0.4 复合交付目标；历史评分信号只作辅助遥测。\n"
        "- 第一目标是用户愿意发布、读者愿意收藏、事实可信、行业适配且自然好读，不是机械追分。\n"
        "- 先规划读者价值、事实边界、行业结构、标题吸引力、正文信息密度和自然表达，再参考辅助特征修缺口。\n"
        "- 不得编造价格、地址、营业时间、体验经历、医学或功效承诺；已核验事实优先。\n"
        "- 三个标题或方案必须代表不同叙事角度，正文必须服务对应标题。\n"
        "- 若基础 Prompt 与统一质量契约或请求时动态材料冲突，以后两者为准。"
    )


def compose_effective_prompt(
    key: str,
    domain: str | None,
    base_content: str,
    layers: Iterable[PromptLayer] = (),
    *,
    preview_complete: bool = False,
    allow_other_domain: bool = False,
) -> ComposedPrompt:
    canonical = canonicalize_domain(domain or "美食", allow_other=allow_other_domain)
    prefix = PromptLayer("V0.4运行时策略", v04_runtime_prefix(key, canonical), "prompt_composer")
    base = PromptLayer("可编辑基础Prompt", neutralize_legacy_prompt_conflicts(base_content), "managed_prompts")
    materialized = tuple(layer for layer in layers if (layer.content or "").strip())
    all_layers = (prefix, base, *materialized)
    return ComposedPrompt(
        text="\n\n".join(layer.content.strip() for layer in all_layers if layer.content.strip()),
        domain=canonical,
        layers=all_layers,
        preview_complete=bool(preview_complete),
    )


def dynamic_layer_labels(key: str | None = None) -> list[str]:
    if key == "semantic_features":
        return ["当前标题与正文（请求时填充，不在预览中展示）"]
    return list(_DYNAMIC_LAYER_LABELS)
