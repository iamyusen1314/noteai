#!/usr/bin/env python3
"""CLI wrapper for model artifact verification/download."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from artifact_loader import main


if __name__ == "__main__":
    raise SystemExit(main())
