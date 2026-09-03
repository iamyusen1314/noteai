"""Versioned managed-Prompt baselines and exact legacy seed fingerprints."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASELINE_ID = "v04-commercial-20260712"
PROMPTS_FILE = Path(__file__).with_name("prompts.json")
PROMPT_KEYS = (
    "agent_arbitrate_system",
    "agent_content_system",
    "agent_growth_system",
    "agent_user_system",
    "agent_visual_system",
    "chat_system",
    "gent_arbitrate_system",
    "gent_content_system",
    "gent_growth_system",
    "gent_user_system",
    "gent_visual_system",
    "semantic_features",
)


def content_sha256(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def load_current_baseline() -> dict[str, dict]:
    data = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    prompts = data.get("prompts") or {}
    if set(prompts) != set(PROMPT_KEYS):
        raise RuntimeError("managed prompt baseline key set is invalid")
    return prompts


# Exact UTF-8 SHA256 values of model/prompts.json before the V0.4 baseline
# migration. Version and digest must both match; no fuzzy text matching is used.
_LEGACY = {
    "agent_arbitrate_system": (4, "687193c651348a96a34f6884c80dcb22b00d0e70ee573f6810372786672103b8", "诊断-仲裁专家（全品类数据驱动版）"),
    "agent_content_system": (4, "ee69f971a2c1a2cd7f5bd0a2a0aff16c9f117214309b9273af91c96f39679433", "诊断-内容分析师（全品类数据驱动版）"),
    "agent_growth_system": (4, "213aaf74624165a4f17b747d55c51ad17d7372c6a241e588007f40087f2c952f", "诊断-增长策略师（全品类数据驱动版）"),
    "agent_user_system": (4, "427c96ae5cf3ce09600fa636c237f0a7c5e36e084faa2df587707460e855ba76", "诊断-用户心理师（全品类数据驱动版）"),
    "agent_visual_system": (4, "9b5b7d4dd146888754c89472c7ba84e085ebb54490d09a50992a28d4637b3f20", "诊断-视觉诊断师（全品类数据驱动版）"),
    "chat_system": (5, "8db593cf6a4fdeefac357d37499ca89abe189aacf604d2f0c46c24bde575caa4", "对话优化（全品类数据驱动版）"),
    "gent_arbitrate_system": (4, "93327548d69c802feb2fb5d67468e853a5dee47bba909d6b8ecbe4b123f36dee", "生成-P3仲裁专家（全品类多图数据驱动版，thinking模式）"),
    "gent_content_system": (4, "7311192d214991773c0d77090c591f322267708c3a680305eb265db951113513", "生成-内容创作师（全品类数据驱动版）"),
    "gent_growth_system": (4, "785af4d58fc80c550c1c87b01b8ff1d1cc53053d591b90bd81becc9caad81622", "生成-增长策略师（全品类数据驱动版）"),
    "gent_user_system": (4, "b6891e1bdb16d6d8c07b3ea014bcf243a34a32b935efb6768e29245ba718f8a7", "生成-用户心理师（全品类数据驱动版）"),
    "gent_visual_system": (4, "06b4ddd51c0ee118da63d8f7e85de5b3a296354256150d15abef9cf46cd5c29f", "生成-视觉分析师（全品类多图数据驱动版）"),
    "semantic_features": (7, "a6dfa03d921e3280316954130ee81db044ef430edaa19806c6b9bbe8e15dd5e5", "语义特征评估（v0.3数据校准+全品类版）"),
}

ACCEPTED_LEGACY = {
    key: ({"version": version, "sha256": digest, "label": label},)
    for key, (version, digest, label) in _LEGACY.items()
}


def is_accepted_legacy(key: str, version: int, content: str) -> bool:
    digest = content_sha256(content)
    return any(
        int(item["version"]) == int(version) and item["sha256"] == digest
        for item in ACCEPTED_LEGACY.get(key, ())
    )
