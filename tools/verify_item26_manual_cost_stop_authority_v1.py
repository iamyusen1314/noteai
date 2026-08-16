#!/usr/bin/env python3
"""Detached authority scaffold for Item 26 manual post-action cost stop.

This authority can only attest read-only reconciliation of two already
consumed browser mutations.  It cannot retroactively authorize them and can
never authorize a future paid action.  The expected root hash remains empty
in the source-only M0 checkpoint; validation therefore fails before any
root-owned file is read.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":MANUAL-POST-ACTION-COST-STOP:v1"
VERIFIER_REF = "tools/verify_item26_manual_cost_stop_authority_v1.py"
AUTHORITY_ROOT_PATH = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v1/authority-root-v1.json"
)
AUTHORITY_BUNDLE_PATH = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v1/authority-bundle-v1.json"
)
PROVIDER_RAW_PATH = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v1/provider-raw-v1.json"
)
ACTIONTRAIL_RAW_PATH = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v1/actiontrail-raw-v1.json"
)
CONFIRMATION_ENVELOPE_PATH = Path(
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v1/confirmation-envelope-v1.json"
)
ROOT_SCHEMA = "noteai.item26.manual-cost-stop-authority-root.v1"
BUNDLE_SCHEMA = "noteai.item26.manual-cost-stop-authority-bundle.v1"
EXPECTED_AUTHORITY_ROOT_FILE_SHA256 = ""
AUTHORITY_IMPLEMENTED = False
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def validate_authority_bundle(
    *,
    expected_authority_root_file_sha256: str,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    del root
    if (
        not AUTHORITY_IMPLEMENTED
        or HEX64.fullmatch(expected_authority_root_file_sha256 or "") is None
        or expected_authority_root_file_sha256
        != EXPECTED_AUTHORITY_ROOT_FILE_SHA256
    ):
        return ["manual cost-stop authority is not finalized"], None
    return ["manual cost-stop authority implementation is not installed"], None


__all__ = [
    "ACTIONTRAIL_RAW_PATH",
    "AUTHORITY_BUNDLE_PATH",
    "AUTHORITY_IMPLEMENTED",
    "AUTHORITY_ROOT_PATH",
    "BUNDLE_SCHEMA",
    "CONFIRMATION_ENVELOPE_PATH",
    "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
    "OPERATION_ID",
    "PROVIDER_RAW_PATH",
    "ROOT_SCHEMA",
    "TASK_ID",
    "VERIFIER_REF",
    "validate_authority_bundle",
]
