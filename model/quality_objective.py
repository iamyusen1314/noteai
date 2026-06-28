"""
Composite delivery objective for NoteAI generation quality.

This module is the generation target layer. Model scores, 62-dim features and
naturalness signals are useful observations, but they must not become the
writer's primary goal. The user-facing goal is a publishable note that feels
natural, useful, factual and worth saving.
"""

from __future__ import annotations

QUALITY_OBJECTIVE_VERSION = "composite-v0.1"

# Legacy score lines. v0.3 may still be present in telemetry until the new
# composite model is trained, but it must not drive generation or hard blocking.
REFERENCE_SCORE_TARGET = 72.0
MIN_ACCEPTABLE_SCORE = 60.0

RUBRIC_WEIGHTS: dict[str, tuple[str, int]] = {
    "title_attraction": ("标题吸引力：短、清楚、有具体对象和自然点击理由", 18),
    "body_decision_value": ("正文决策价值：读者看完知道是否适合自己、怎么行动", 22),
    "information_density": ("信息密度：事实、步骤、清单、对比或体验证据足够", 18),
    "industry_fit": ("行业适配：结构、事实槽位和表达方式符合当前品类", 16),
    "natural_voice": ("自然表达：像真实创作者，不像关键词拼接或模板稿", 16),
    "fact_integrity": ("事实可信：结构化事实可追溯，缺失时不编造", 10),
}

DOMAIN_PRIORITIES: dict[str, tuple[str, ...]] = {
    "美食": (
        "到店决策：位置/人均/营业/预订/适合场景要清楚",
        "点单价值：招牌、必点、推荐菜要绑定具体菜品",
        "口感证据：火候、分量、口味层次用具体细节表达",
    ),
    "旅行": (
        "路线决策：天数、交通、预算、体力要求和适合人群要清楚",
        "体验画面：核心景点/酒店/玩法要有可感知画面",
        "避坑价值：至少给出一个真实限制或取舍建议",
    ),
    "穿搭": (
        "身材/场景适配：谁适合、什么场合穿要明确",
        "搭配逻辑：颜色、比例、单品关系要讲清楚",
        "购买决策：品牌/渠道/价格有则引用，缺失不编造",
    ),
    "美妆": (
        "肤质/肤色适配：适合谁、不适合谁要明确",
        "使用证据：质地、上脸、用量、妆效变化要具体",
        "安全边界：不写无依据医学功效或夸大承诺",
    ),
    "家居": (
        "空间问题：原始痛点和改造目标要清楚",
        "复刻价值：清单、尺寸、预算、动线或收纳逻辑要可执行",
        "效果证据：改造前后变化要具体，不空喊氛围感",
    ),
    "健身": (
        "训练可执行：动作、组数、频率、注意事项要清楚",
        "人群安全：适合基础和禁忌提醒要明确",
        "结果真实：不承诺快速瘦身或医学效果",
    ),
    "母婴": (
        "安全优先：月龄、剂量、成分、注意事项要清楚",
        "实操可复用：步骤、材料、观察点要具体",
        "信任表达：不编造医生背书、宝宝反应或疗效",
    ),
}


def delivery_objective_brief(domain: str | None = None) -> str:
    """Reader-facing composite objective for all generation and revision prompts."""
    canonical = domain or "通用"
    priorities = DOMAIN_PRIORITIES.get(canonical, (
        "清楚回答读者为什么要看、能获得什么、下一步怎么做",
        "用具体事实、步骤、对比或场景支撑观点",
        "保持自然表达，不做关键词堆砌和夸张承诺",
    ))
    rubric = "\n".join(
        f"- {label}（{weight}%）"
        for label, weight in (item for item in RUBRIC_WEIGHTS.values())
    )
    priority_text = "\n".join(f"- {item}" for item in priorities)
    return (
        f"【复合交付目标｜{QUALITY_OBJECTIVE_VERSION}｜优先级最高】\n"
        "目标不是追某个模型分，而是交付用户愿意发布、读者愿意收藏、事实可信的内容。\n"
        f"{rubric}\n"
        f"【{canonical}品类优先级】\n{priority_text}\n"
        "人工偏好、事实可信、自然表达和行业可执行价值是训练与交付主目标；旧评分器只允许做历史对照和遥测，不得指挥生成。"
    )


def auxiliary_signal_brief() -> str:
    return (
        "【训练信号使用原则】\n"
        "- 当前生成不得以旧评分器过线为目标；旧分数只保留在后台遥测和训练对照里。\n"
        "- 62维特征用于发现可解释缺口：标题长度、正文长度、标签、事实槽位、CTA、语义/节奏等；只修对读者有帮助的缺口。\n"
        "- 自然度/AI味信号用于发现模板化风险，不可单独否定行业好稿。\n"
        "- v0.4-composite 的训练目标必须来自人工 golden、A/B 偏好、事实可信和线上反馈，而不是继承 v0.3 分数。"
    )


def revision_objective_brief(domain: str | None = None, style_hint: str | None = "") -> str:
    style_line = f"本轮方向：{style_hint}" if style_hint else "本轮方向：提升交付价值"
    return (
        f"{delivery_objective_brief(domain)}\n\n"
        f"{auxiliary_signal_brief()}\n\n"
        "【二修策略】\n"
        f"- {style_line}。\n"
        "- 先保留原稿中真实、有用、有人味的部分，再补信息密度、行业适配和标题吸引力。\n"
        "- 只接受让内容更像真实好笔记的修改；分数上升但标题难读、正文模板化、事实不可追溯，一律不采纳。"
    )


def auxiliary_score_issue(score: float) -> str:
    return f"旧评分器低于历史参考线（当前{score:.1f}分，参考≥{REFERENCE_SCORE_TARGET:.0f}分，仅作遥测）"


def is_auxiliary_score_issue(issue: str) -> bool:
    return (
        "旧评分器低于历史参考线" in (issue or "")
        or "辅助评分低于爆文参考线" in (issue or "")
        or "v0.3评分未达爆文目标" in (issue or "")
    )
