#!/usr/bin/env python3
"""Fail-closed raw extractor scaffold for Item 26 manual cost stop.

The two browser mutations predate this control source.  This module therefore
does not authorize or dispatch any action.  A later activation revision may
set ``RAW_PROVIDER_EXTRACTION_IMPLEMENTED`` only after tests cover complete
ActionTrail pagination and the retained provider responses.  Until then every
attempt to derive a terminal projection fails before consuming input.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any


TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":MANUAL-POST-ACTION-COST-STOP:v1"
CAPTURE_SCHEMA = "noteai.item26.manual-cost-stop-provider-raw.v1"
PROJECTION_SCHEMA = "noteai.item26.manual-cost-stop-provider-projection.v1"
RAW_PROVIDER_EXTRACTION_IMPLEMENTED = False
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 256
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)
COMMITMENT_DOMAIN = b"noteai-item26-manual-cost-stop-provider-v1\0"

REQUIRED_SLOTS = (
    "pre_action_rds_inventory",
    "protection_disable_response",
    "protection_disabled_readback",
    "delete_response",
    "final_rds_inventory",
    "historical_billing_snapshot",
    "actiontrail_lookup_pages",
)


class ExtractionError(ValueError):
    """A fixed non-sensitive extraction failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def commitment(label: str, value: str) -> str:
    if type(label) is not str or not label.isascii() or not label:
        raise ExtractionError("commitment_label")
    if type(value) is not str or not value:
        raise ExtractionError("commitment_value")
    return sha256(
        COMMITMENT_DOMAIN
        + label.encode("ascii")
        + b"\0"
        + value.encode("utf-8")
    )


def decode_canonical_json(encoded: Any, label: str) -> dict[str, Any]:
    if type(encoded) is not str or not encoded or len(encoded) > 4 * MAX_BODY_BYTES:
        raise ExtractionError(label + "_base64")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ExtractionError(label + "_base64") from exc
    if not 1 <= len(raw) <= MAX_BODY_BYTES or b"\0" in raw:
        raise ExtractionError(label + "_shape")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExtractionError(label + "_json") from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise ExtractionError(label + "_canonical")
    return value


def _utc(value: Any, label: str) -> datetime:
    if type(value) is not str or RFC3339.fullmatch(value) is None:
        raise ExtractionError(label)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ExtractionError(label) from exc
    if parsed.tzinfo != timezone.utc:
        raise ExtractionError(label)
    return parsed


def validate_capture_envelope(value: Any) -> None:
    keys = {
        "schema",
        "task_id",
        "operation_id",
        "phase",
        "ledger_context_revision",
        "observed_at_utc",
        "records",
    }
    if type(value) is not dict or set(value) != keys:
        raise ExtractionError("capture_schema")
    if (
        value["schema"] != CAPTURE_SCHEMA
        or value["task_id"] != TASK_ID
        or value["operation_id"] != OPERATION_ID
        or value["phase"] != "POST_ACTION_READBACK_ONLY"
        or type(value["ledger_context_revision"]) is not str
        or len(value["ledger_context_revision"]) != 40
        or type(value["records"]) is not list
        or not 1 <= len(value["records"]) <= MAX_RECORDS
    ):
        raise ExtractionError("capture_identity")
    observed_at = _utc(value["observed_at_utc"], "capture_observed_at")
    slots: list[str] = []
    for record in value["records"]:
        if type(record) is not dict or set(record) != {
            "sequence",
            "slot",
            "operation",
            "started_at_utc",
            "completed_at_utc",
            "transport_outcome",
            "request_json_base64",
            "response_json_base64",
        }:
            raise ExtractionError("record_schema")
        if (
            type(record["sequence"]) is not int
            or record["sequence"] < 1
            or type(record["slot"]) is not str
            or record["slot"] not in REQUIRED_SLOTS
            or type(record["operation"]) is not str
            or not record["operation"]
            or record["transport_outcome"] != "RESPONSE_RECEIVED"
        ):
            raise ExtractionError("record_identity")
        started_at = _utc(record["started_at_utc"], "record_started_at")
        completed_at = _utc(record["completed_at_utc"], "record_completed_at")
        if not started_at <= completed_at <= observed_at:
            raise ExtractionError("record_time_order")
        decode_canonical_json(record["request_json_base64"], "request")
        decode_canonical_json(record["response_json_base64"], "response")
        slots.append(record["slot"])
    if sorted(set(slots)) != sorted(REQUIRED_SLOTS):
        raise ExtractionError("capture_slots")
    if any(
        slots.count(slot) != 1
        for slot in REQUIRED_SLOTS
        if slot != "actiontrail_lookup_pages"
    ) or slots.count("actiontrail_lookup_pages") < 1:
        raise ExtractionError("capture_slot_count")
    if [record["sequence"] for record in value["records"]] != list(
        range(1, len(value["records"]) + 1)
    ):
        raise ExtractionError("record_sequence")


def extract_projection(_capture: Any) -> dict[str, Any]:
    """Fail closed until native provider projection semantics are finalized."""

    if not RAW_PROVIDER_EXTRACTION_IMPLEMENTED:
        raise ExtractionError("provider_extractor_not_finalized")
    raise ExtractionError("provider_extractor_not_installed")


__all__ = [
    "CAPTURE_SCHEMA",
    "ExtractionError",
    "OPERATION_ID",
    "PROJECTION_SCHEMA",
    "RAW_PROVIDER_EXTRACTION_IMPLEMENTED",
    "REQUIRED_SLOTS",
    "TASK_ID",
    "canonical_bytes",
    "commitment",
    "decode_canonical_json",
    "extract_projection",
    "sha256",
    "validate_capture_envelope",
]
