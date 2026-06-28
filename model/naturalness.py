#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime helper for the naturalness candidate model."""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np

from text_naturalness_features import NATURALNESS_FEATURE_COLS, extract_naturalness_features


MODEL_PATH = Path(__file__).parent / "artifacts" / "model_naturalness_v0.1.lgb"
_MODEL: lgb.Booster | None = None
_SIGNATURE: tuple[str, float] | None = None


def get_model() -> lgb.Booster | None:
    global _MODEL, _SIGNATURE
    if not MODEL_PATH.exists():
        return None
    resolved = MODEL_PATH.resolve()
    signature = (str(resolved), resolved.stat().st_mtime)
    if _MODEL is None or _SIGNATURE != signature:
        _MODEL = lgb.Booster(model_file=str(MODEL_PATH))
        _SIGNATURE = signature
    return _MODEL


def score_naturalness(title: str, body: str, domain: str = "") -> dict[str, float]:
    model = get_model()
    if model is None:
        return {"available": 0.0, "ai_probability": 0.0, "naturalness_score": 50.0}
    feats = extract_naturalness_features(title, body, domain)
    vector = np.array([[float(feats.get(col, 0.0) or 0.0) for col in NATURALNESS_FEATURE_COLS]], dtype=float)
    ai_probability = float(model.predict(vector)[0])
    ai_probability = max(0.0, min(1.0, ai_probability))
    return {
        "available": 1.0,
        "ai_probability": ai_probability,
        "naturalness_score": (1.0 - ai_probability) * 100.0,
    }
