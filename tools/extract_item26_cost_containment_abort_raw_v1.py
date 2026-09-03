#!/usr/bin/env python3
"""Pure Alibaba Cloud raw extractor for the Item 26 abort contract.

The extractor performs no file, network, subprocess, database, or cloud write.
It accepts one canonical root-owned capture envelope whose individual request
and response JSON bodies are retained byte-for-byte as base64.  It emits only
Secret-free commitments and provider-state projections; raw resource IDs and
provider payloads never appear in its return values.

This module deliberately implements only facts that can be rederived from
provider-native fields.  In particular, QueryInstanceBill is a delayed billing
snapshot, not a terminal/non-accruing marker.  Release authority comes from an
accepted DeleteDBInstance response plus complete exact-ID inventory absence and
the separately frozen provider release contract.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from typing import Any, Iterable


TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":COST_CONTAINMENT_ABORT:v1"
CAPTURE_SCHEMA = "noteai.item26.cost-containment-abort-provider-raw.v1"
RDS_VERSION = "2014-08-15"
BSS_VERSION = "2017-12-14"
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 256
MAX_PAGE_SIZE = 300
HEX40 = re.compile(r"^[0-9a-f]{40}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DECIMAL_TEXT = re.compile(r"^(0|[1-9]\d*)(?:\.\d{1,6})?$")

COMMITMENT_DOMAIN = b"noteai-item26-abort-provider-commitment-v1\0"
REQUEST_SET_DOMAIN = b"noteai-item26-abort-native-request-set-v1\0"
RESPONSE_SET_DOMAIN = b"noteai-item26-abort-native-response-set-v1\0"
OBSERVATION_SET_DOMAIN = b"noteai-item26-abort-native-observation-set-v1\0"
PAGE_SET_DOMAIN = b"noteai-item26-abort-native-page-set-v1\0"
RELEASE_NATIVE_DOMAIN = b"noteai-item26-abort-native-release-evidence-v1\0"
MUTATION_PROJECTION_SCHEMA = "noteai.item26.rds-mutation-projection.v1"
INVENTORY_PROJECTION_SCHEMA = "noteai.item26.rds-inventory-projection.v1"
BILLING_PROJECTION_SCHEMA = "noteai.item26.rds-billing-projection.v1"

FORBIDDEN_KEY_NAMES = {
    "accesskeyid",
    "accesskeysecret",
    "authorization",
    "cookie",
    "password",
    "privatekey",
    "securitytoken",
    "signature",
    "xacssecuritytoken",
}

CAPTURE_KEYS = {
    "schema",
    "task_id",
    "operation_id",
    "phase",
    "source_revision",
    "observed_at_utc",
    "records",
}
RECORD_KEYS = {
    "sequence",
    "slot",
    "operation",
    "region_id",
    "started_at_utc",
    "completed_at_utc",
    "transport_outcome",
    "http_status",
    "request_json_base64",
    "response_json_base64",
}
TRANSPORT_RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
TRANSPORT_NO_RESPONSE_UNKNOWN = "NO_RESPONSE_UNKNOWN"
_CAPTURE_TOKEN = object()


class ExtractionError(ValueError):
    """A fixed non-sensitive extraction failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
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


def _domain(domain: bytes, value: Any) -> str:
    return _sha(domain + _canonical(value))


def _commit(label: str, value: str) -> str:
    if type(label) is not str or not label.isascii() or not label:
        raise ExtractionError("commitment_label")
    if type(value) is not str or not value:
        raise ExtractionError("commitment_value")
    return _sha(
        COMMITMENT_DOMAIN
        + label.encode("ascii")
        + b"\0"
        + value.encode("utf-8")
    )


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExtractionError("duplicate_json_key")
        result[key] = value
    return result


def _json(raw: bytes, label: str, *, canonical: bool) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_BODY_BYTES
        or b"\0" in raw
    ):
        raise ExtractionError(label + "_shape")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_float=Decimal,
        )
    except ExtractionError:
        raise
    except (UnicodeError, json.JSONDecodeError, InvalidOperation) as exc:
        raise ExtractionError(label + "_json") from exc
    if type(value) is not dict:
        raise ExtractionError(label + "_object")
    if canonical and _canonical(value) != raw:
        raise ExtractionError(label + "_canonical")
    return value


def _utc(value: Any, label: str) -> datetime:
    if type(value) is not str or UTC.fullmatch(value) is None:
        raise ExtractionError(label)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ExtractionError(label) from exc
    return parsed


def _string(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise ExtractionError(label)
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ExtractionError(label)
    return value


def _decimal(value: Any, label: str) -> Decimal:
    if type(value) is int:
        parsed = Decimal(value)
    elif type(value) is Decimal:
        parsed = value
    elif type(value) is str and DECIMAL_TEXT.fullmatch(value):
        parsed = Decimal(value)
    else:
        raise ExtractionError(label)
    if not parsed.is_finite() or parsed < 0:
        raise ExtractionError(label)
    return parsed


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _strict(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ExtractionError(label + "_schema")
    return value


def _provider_object(
    value: Any,
    required_keys: set[str],
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict or not required_keys.issubset(value):
        raise ExtractionError(label + "_schema")
    return value


def _reject_derived_or_secret_keys(value: Any, label: str) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ExtractionError(label + "_key")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in FORBIDDEN_KEY_NAMES:
                raise ExtractionError(label + "_secret_key")
            if key.lower().endswith("_sha256"):
                raise ExtractionError(label + "_derived_key")
            _reject_derived_or_secret_keys(item, label)
    elif type(value) is list:
        for item in value:
            _reject_derived_or_secret_keys(item, label)


def _decode_body(encoded: Any, label: str) -> tuple[bytes, dict[str, Any]]:
    if type(encoded) is not str or not encoded or len(encoded) > MAX_BODY_BYTES * 2:
        raise ExtractionError(label + "_base64")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ExtractionError(label + "_base64") from exc
    value = _json(raw, label, canonical=False)
    _reject_derived_or_secret_keys(value, label)
    return raw, value


@dataclass(frozen=True)
class RawRecord:
    sequence: int
    slot: str
    operation: str
    region_id: str
    started_at_utc: str
    completed_at_utc: str
    transport_outcome: str
    http_status: int | None
    request_raw: bytes
    request: dict[str, Any]
    response_raw: bytes | None
    response: dict[str, Any] | None
    _token: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class RawCapture:
    phase: str
    source_revision: str
    observed_at_utc: str
    raw_sha256: str
    records: tuple[RawRecord, ...]
    raw: bytes = field(repr=False)
    _token: object = field(repr=False, compare=False)


def parse_capture(raw: bytes, *, expected_phase: str) -> RawCapture:
    """Parse one canonical capture and retain exact inner request/response bytes."""

    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_CAPTURE_BYTES
        or b"\0" in raw
    ):
        raise ExtractionError("capture_shape")
    value = _json(raw, "capture", canonical=True)
    _strict(value, CAPTURE_KEYS, "capture")
    if (
        value["schema"] != CAPTURE_SCHEMA
        or value["task_id"] != TASK_ID
        or value["operation_id"] != OPERATION_ID
        or value["phase"] != expected_phase
        or expected_phase not in {"PREFLIGHT", "TERMINAL"}
        or type(value["source_revision"]) is not str
        or HEX40.fullmatch(value["source_revision"]) is None
    ):
        raise ExtractionError("capture_identity")
    capture_observed = _utc(value["observed_at_utc"], "capture_observed_at")
    rows = value["records"]
    if (
        type(rows) is not list
        or not rows
        or len(rows) > MAX_RECORDS
        or any(type(row) is not dict for row in rows)
    ):
        raise ExtractionError("capture_records")
    records: list[RawRecord] = []
    previous_completed: datetime | None = None
    for expected_sequence, row in enumerate(rows, start=1):
        _strict(row, RECORD_KEYS, "capture_record")
        started = _utc(row["started_at_utc"], "record_started_at")
        completed = _utc(row["completed_at_utc"], "record_completed_at")
        if (
            type(row["sequence"]) is not int
            or row["sequence"] != expected_sequence
            or type(row["slot"]) is not str
            or not row["slot"].isascii()
            or not row["slot"]
            or type(row["operation"]) is not str
            or not row["operation"].isascii()
            or not row["operation"]
            or type(row["region_id"]) is not str
            or not row["region_id"].isascii()
            or not row["region_id"]
            or started > completed
            or completed > capture_observed
            or (previous_completed is not None and started < previous_completed)
        ):
            raise ExtractionError("capture_record_identity")
        request_raw, request = _decode_body(
            row["request_json_base64"], "request"
        )
        transport_outcome = row["transport_outcome"]
        if transport_outcome == TRANSPORT_RESPONSE_RECEIVED:
            if (
                type(row["http_status"]) is not int
                or not 100 <= row["http_status"] <= 599
                or type(row["response_json_base64"]) is not str
            ):
                raise ExtractionError("capture_record_transport")
            response_raw, response = _decode_body(
                row["response_json_base64"], "response"
            )
        elif transport_outcome == TRANSPORT_NO_RESPONSE_UNKNOWN:
            if row["http_status"] is not None or row["response_json_base64"] is not None:
                raise ExtractionError("capture_record_transport")
            response_raw = None
            response = None
        else:
            raise ExtractionError("capture_record_transport")
        records.append(
            RawRecord(
                sequence=row["sequence"],
                slot=row["slot"],
                operation=row["operation"],
                region_id=row["region_id"],
                started_at_utc=row["started_at_utc"],
                completed_at_utc=row["completed_at_utc"],
                transport_outcome=transport_outcome,
                http_status=row["http_status"],
                request_raw=request_raw,
                request=request,
                response_raw=response_raw,
                response=response,
                _token=_CAPTURE_TOKEN,
            )
        )
        previous_completed = completed
    return RawCapture(
        phase=value["phase"],
        source_revision=value["source_revision"],
        observed_at_utc=value["observed_at_utc"],
        raw_sha256=_sha(raw),
        records=tuple(records),
        raw=raw,
        _token=_CAPTURE_TOKEN,
    )


def _assert_capture(capture: RawCapture) -> None:
    if type(capture) is not RawCapture or capture._token is not _CAPTURE_TOKEN:
        raise ExtractionError("capture_provenance")
    reparsed = parse_capture(capture.raw, expected_phase=capture.phase)
    if (
        capture.source_revision != reparsed.source_revision
        or capture.observed_at_utc != reparsed.observed_at_utc
        or capture.raw_sha256 != reparsed.raw_sha256
        or capture.records != reparsed.records
    ):
        raise ExtractionError("capture_provenance")


def _records(capture: RawCapture, slot: str, operation: str) -> list[RawRecord]:
    _assert_capture(capture)
    rows = [row for row in capture.records if row.slot == slot]
    if not rows or any(row.operation != operation for row in rows):
        raise ExtractionError(slot + "_records")
    return rows


def require_exact_capture_slots(
    capture: RawCapture,
    expected: dict[str, str],
) -> None:
    """Reject unconsumed or mislabeled provider attempts in a signed capture."""

    _assert_capture(capture)
    if (
        type(expected) is not dict
        or not expected
        or any(
            type(slot) is not str
            or not slot
            or type(operation) is not str
            or not operation
            for slot, operation in expected.items()
        )
    ):
        raise ExtractionError("capture_expected_slots")
    observed_slots = {row.slot for row in capture.records}
    if observed_slots != set(expected):
        raise ExtractionError("capture_slot_ledger")
    if any(row.operation != expected[row.slot] for row in capture.records):
        raise ExtractionError("capture_operation_ledger")


def _rpc_request(
    row: RawRecord,
    *,
    version: str,
    allowed_keys: set[str],
    required: dict[str, Any],
) -> dict[str, Any]:
    request = row.request
    if set(request) - allowed_keys or not set(required).issubset(request):
        raise ExtractionError(row.slot + "_request_schema")
    expected = {"Action": row.operation, "Version": version, **required}
    for key, value in expected.items():
        if type(request.get(key)) is not type(value) or request.get(key) != value:
            raise ExtractionError(row.slot + "_request_binding")
    if request.get("RegionId", row.region_id) != row.region_id:
        raise ExtractionError(row.slot + "_request_region")
    return request


def _request_projection(row: RawRecord) -> dict[str, Any]:
    return {
        "sequence": row.sequence,
        "slot": row.slot,
        "operation": row.operation,
        "region_sha256": _commit("region_id", row.region_id),
        "request_body_sha256": _sha(row.request_raw),
    }


def _response_projection(row: RawRecord, request_id: str) -> dict[str, Any]:
    if (
        row.transport_outcome != TRANSPORT_RESPONSE_RECEIVED
        or type(row.http_status) is not int
        or type(row.response_raw) is not bytes
        or type(row.response) is not dict
    ):
        raise ExtractionError(row.slot + "_response_unavailable")
    return {
        "sequence": row.sequence,
        "slot": row.slot,
        "operation": row.operation,
        "http_status": row.http_status,
        "provider_request_id_sha256": _commit("provider_request_id", request_id),
        "response_body_sha256": _sha(row.response_raw),
    }


def project_accepted_rds_mutation(
    capture: RawCapture,
    *,
    slot: str,
    operation: str,
    region_id: str,
    instance_id: str,
    client_token: str | None = None,
) -> dict[str, Any]:
    """Project one exact accepted RDS mutation; ambiguous responses never pass."""

    rows = _records(capture, slot, operation)
    if len(rows) != 1 or operation not in {
        "ModifyDBInstanceDeletionProtection",
        "DeleteDBInstance",
    }:
        raise ExtractionError(slot + "_mutation_count")
    row = rows[0]
    if (
        row.transport_outcome != TRANSPORT_RESPONSE_RECEIVED
        or row.region_id != region_id
        or row.http_status != 200
    ):
        raise ExtractionError(slot + "_mutation_transport")
    if operation == "ModifyDBInstanceDeletionProtection":
        if type(client_token) is not str or not client_token:
            raise ExtractionError(slot + "_client_token")
        required = {
            "RegionId": region_id,
            "DBInstanceId": instance_id,
            "DeletionProtection": False,
            "ClientToken": client_token,
        }
        allowed = {"Action", "Version", *required}
    else:
        if client_token is not None:
            raise ExtractionError(slot + "_delete_client_token")
        required = {"RegionId": region_id, "DBInstanceId": instance_id}
        allowed = {"Action", "Version", *required}
    _rpc_request(
        row,
        version=RDS_VERSION,
        allowed_keys=allowed,
        required=required,
    )
    response = _provider_object(row.response, {"RequestId"}, slot + "_response")
    expected_response_keys = (
        {"RequestId"}
        if operation == "ModifyDBInstanceDeletionProtection"
        else {"RequestId", "RegionId"}
    )
    if set(response) != expected_response_keys:
        raise ExtractionError(slot + "_response_schema")
    if operation == "DeleteDBInstance" and response["RegionId"] != region_id:
        raise ExtractionError(slot + "_response_region")
    request_id = _string(response["RequestId"], slot + "_request_id")
    request_projection = _request_projection(row)
    response_projection = _response_projection(row, request_id)
    return {
        "schema": MUTATION_PROJECTION_SCHEMA,
        "slot": slot,
        "operation": operation,
        "target_sha256": _commit("rds_instance_id", instance_id),
        "region_sha256": _commit("region_id", region_id),
        "request_body_sha256": request_projection["request_body_sha256"],
        "request_set_sha256": _domain(REQUEST_SET_DOMAIN, [request_projection]),
        "response_set_sha256": _domain(RESPONSE_SET_DOMAIN, [response_projection]),
        "provider_request_id_set_sha256": _domain(
            OBSERVATION_SET_DOMAIN,
            [response_projection["provider_request_id_sha256"]],
        ),
        "started_at_utc": row.started_at_utc,
        "completed_at_utc": row.completed_at_utc,
        "submission_outcome": "ACCEPTED",
        "raw_record_count": 1,
        "raw_capture_sha256": capture.raw_sha256,
    }


def project_rds_inventory(
    capture: RawCapture,
    *,
    slot: str,
    region_id: str,
    instance_id: str,
    expected_count: int,
) -> dict[str, Any]:
    """Project a complete PageNumber/PageSize exact-ID RDS inventory."""

    if type(expected_count) is not int or expected_count not in {0, 1}:
        raise ExtractionError(slot + "_expected_count")
    rows = _records(capture, slot, "DescribeDBInstances")
    page_rows: list[dict[str, Any]] = []
    request_projections: list[dict[str, Any]] = []
    response_projections: list[dict[str, Any]] = []
    request_ids: set[str] = set()
    total: int | None = None
    page_size: int | None = None
    instances: list[dict[str, Any]] = []
    for expected_page, row in enumerate(rows, start=1):
        if (
            row.transport_outcome != TRANSPORT_RESPONSE_RECEIVED
            or row.region_id != region_id
            or row.http_status != 200
        ):
            raise ExtractionError(slot + "_transport")
        request = _rpc_request(
            row,
            version=RDS_VERSION,
            allowed_keys={
                "Action", "Version", "RegionId", "DBInstanceId",
                "PageNumber", "PageSize",
            },
            required={
                "RegionId": region_id,
                "DBInstanceId": instance_id,
                "PageNumber": expected_page,
            },
        )
        current_page_size = _integer(request.get("PageSize"), slot + "_page_size")
        if not 1 <= current_page_size <= 100:
            raise ExtractionError(slot + "_page_size")
        if page_size is None:
            page_size = current_page_size
        elif page_size != current_page_size:
            raise ExtractionError(slot + "_page_size_drift")
        response = _provider_object(
            row.response,
            {
                "RequestId", "PageNumber", "PageRecordCount",
                "TotalRecordCount", "Items",
            },
            slot + "_response",
        )
        request_id = _string(response["RequestId"], slot + "_request_id")
        if request_id in request_ids:
            raise ExtractionError(slot + "_request_id_reuse")
        request_ids.add(request_id)
        response_page = _integer(response["PageNumber"], slot + "_response_page")
        response_count = _integer(
            response["PageRecordCount"], slot + "_response_count"
        )
        response_total = _integer(
            response["TotalRecordCount"], slot + "_response_total"
        )
        if response_page != expected_page:
            raise ExtractionError(slot + "_page_sequence")
        if total is None:
            total = response_total
        elif total != response_total:
            raise ExtractionError(slot + "_total_drift")
        items = _provider_object(response["Items"], {"DBInstance"}, slot + "_items")
        current_instances = items["DBInstance"]
        if (
            type(current_instances) is not list
            or any(type(item) is not dict for item in current_instances)
            or response_count != len(current_instances)
        ):
            raise ExtractionError(slot + "_page_rows")
        instances.extend(current_instances)
        request_projection = _request_projection(row)
        response_projection = _response_projection(row, request_id)
        request_projections.append(request_projection)
        response_projections.append(response_projection)
        page_rows.append(
            {
                "page_number": expected_page,
                "page_size": current_page_size,
                "page_record_count": response_count,
                "total_record_count": response_total,
                "request_body_sha256": request_projection["request_body_sha256"],
                "response_body_sha256": response_projection["response_body_sha256"],
                "provider_request_id_sha256": response_projection[
                    "provider_request_id_sha256"
                ],
            }
        )
    if total is None or page_size is None:
        raise ExtractionError(slot + "_pagination_state")
    required_pages = max(1, math.ceil(total / page_size))
    if len(rows) != required_pages or len(instances) != total:
        raise ExtractionError(slot + "_incomplete_pages")
    seen: set[str] = set()
    projected_instances: list[dict[str, Any]] = []
    for item in instances:
        native_id = _string(item.get("DBInstanceId"), slot + "_instance_id")
        if native_id != instance_id or native_id in seen:
            raise ExtractionError(slot + "_instance_identity")
        seen.add(native_id)
        required = {
            "DBInstanceId", "DBInstanceStatus", "PayType", "Engine",
            "EngineVersion", "DeletionProtection", "VpcId", "VSwitchId",
            "ZoneId",
        }
        _provider_object(item, required, slot + "_instance")
        if type(item["DeletionProtection"]) is not bool:
            raise ExtractionError(slot + "_deletion_protection")
        projected_instances.append(
            {
                "instance_sha256": _commit("rds_instance_id", native_id),
                "status": _string(item["DBInstanceStatus"], slot + "_status"),
                "pay_type": _string(item["PayType"], slot + "_pay_type"),
                "engine": _string(item["Engine"], slot + "_engine"),
                "engine_version": _string(
                    item["EngineVersion"], slot + "_engine_version"
                ),
                "deletion_protection": item["DeletionProtection"],
                "vpc_sha256": _commit("vpc_id", _string(item["VpcId"], slot + "_vpc")),
                "vswitch_sha256": _commit(
                    "vswitch_id", _string(item["VSwitchId"], slot + "_vswitch")
                ),
                "zone_sha256": _commit(
                    "zone_id", _string(item["ZoneId"], slot + "_zone")
                ),
            }
        )
    if total != expected_count:
        raise ExtractionError(slot + "_exact_count")
    observation = {
        "slot": slot,
        "target_sha256": _commit("rds_instance_id", instance_id),
        "exact_count": total,
        "instances": projected_instances,
        "pages": page_rows,
    }
    return {
        "schema": INVENTORY_PROJECTION_SCHEMA,
        **observation,
        "region_sha256": _commit("region_id", region_id),
        "request_set_sha256": _domain(REQUEST_SET_DOMAIN, request_projections),
        "response_set_sha256": _domain(RESPONSE_SET_DOMAIN, response_projections),
        "provider_request_id_set_sha256": _domain(
            OBSERVATION_SET_DOMAIN,
            [row["provider_request_id_sha256"] for row in response_projections],
        ),
        "observation_set_sha256": _domain(OBSERVATION_SET_DOMAIN, observation),
        "page_inventory_sha256": _domain(PAGE_SET_DOMAIN, page_rows),
        "full_page_complete": True,
        "raw_record_count": len(rows),
        "raw_capture_sha256": capture.raw_sha256,
        "observed_at_utc": capture.observed_at_utc,
    }


def project_instance_bill(
    capture: RawCapture,
    *,
    slot: str,
    instance_id: str,
    billing_cycle: str,
) -> dict[str, Any]:
    """Project the complete delayed QueryInstanceBill snapshot for one RDS ID."""

    rows = _records(capture, slot, "QueryInstanceBill")
    request_projections: list[dict[str, Any]] = []
    response_projections: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    request_ids: set[str] = set()
    all_items: list[tuple[dict[str, Any], str, int]] = []
    total: int | None = None
    page_size: int | None = None
    for expected_page, row in enumerate(rows, start=1):
        if (
            row.transport_outcome != TRANSPORT_RESPONSE_RECEIVED
            or row.http_status != 200
        ):
            raise ExtractionError(slot + "_transport")
        request = _rpc_request(
            row,
            version=BSS_VERSION,
            allowed_keys={
                "Action", "Version", "BillingCycle", "ProductCode",
                "SubscriptionType", "IsBillingItem", "IsHideZeroCharge",
                "Granularity", "PageNum", "PageSize",
            },
            required={
                "BillingCycle": billing_cycle,
                "ProductCode": "rds",
                "SubscriptionType": "PayAsYouGo",
                "IsBillingItem": False,
                "IsHideZeroCharge": False,
                "Granularity": "MONTHLY",
                "PageNum": expected_page,
            },
        )
        current_page_size = _integer(request.get("PageSize"), slot + "_page_size")
        if not 1 <= current_page_size <= MAX_PAGE_SIZE:
            raise ExtractionError(slot + "_page_size")
        if page_size is None:
            page_size = current_page_size
        elif page_size != current_page_size:
            raise ExtractionError(slot + "_page_size_drift")
        response = _provider_object(
            row.response,
            {"Code", "Success", "RequestId", "Data"},
            slot + "_response",
        )
        if response["Code"] != "Success" or response["Success"] is not True:
            raise ExtractionError(slot + "_provider_failure")
        request_id = _string(response["RequestId"], slot + "_request_id")
        if request_id in request_ids:
            raise ExtractionError(slot + "_request_id_reuse")
        request_ids.add(request_id)
        data = _provider_object(
            response["Data"],
            {"PageNum", "BillingCycle", "PageSize", "TotalCount", "Items"},
            slot + "_data",
        )
        response_page = _integer(data["PageNum"], slot + "_response_page")
        response_page_size = _integer(data["PageSize"], slot + "_response_size")
        response_total = _integer(data["TotalCount"], slot + "_response_total")
        if (
            response_page != expected_page
            or response_page_size != current_page_size
            or data["BillingCycle"] != billing_cycle
        ):
            raise ExtractionError(slot + "_page_binding")
        if total is None:
            total = response_total
        elif total != response_total:
            raise ExtractionError(slot + "_total_drift")
        items = _provider_object(data["Items"], {"Item"}, slot + "_items")["Item"]
        if type(items) is not list or any(type(item) is not dict for item in items):
            raise ExtractionError(slot + "_item_rows")
        request_projection = _request_projection(row)
        response_projection = _response_projection(row, request_id)
        for item in items:
            all_items.append(
                (item, response_projection["response_body_sha256"], len(all_items))
            )
        request_projections.append(request_projection)
        response_projections.append(response_projection)
        page_rows.append(
            {
                "page_number": expected_page,
                "page_size": current_page_size,
                "item_count": len(items),
                "total_count": response_total,
                "request_body_sha256": request_projection["request_body_sha256"],
                "response_body_sha256": response_projection["response_body_sha256"],
                "provider_request_id_sha256": response_projection[
                    "provider_request_id_sha256"
                ],
            }
        )
    if total is None or page_size is None:
        raise ExtractionError(slot + "_pagination_state")
    required_pages = max(1, math.ceil(total / page_size))
    if len(rows) != required_pages or len(all_items) != total:
        raise ExtractionError(slot + "_incomplete_pages")
    matched: list[dict[str, Any]] = []
    gross = Decimal(0)
    service_seconds = 0
    for item, page_response_sha256, ordinal in all_items:
        native_id = item.get("InstanceID")
        if native_id != instance_id:
            continue
        required = {
            "InstanceID", "Currency", "SubscriptionType", "ProductCode",
            "PipCode", "ServicePeriod", "ServicePeriodUnit",
            "PretaxGrossAmount",
        }
        _provider_object(item, required, slot + "_bill_item")
        if (
            item["Currency"] != "CNY"
            or item["SubscriptionType"] != "PayAsYouGo"
            or item["ProductCode"] != "rds"
            or item["PipCode"] != "rds"
            or item["ServicePeriodUnit"] not in {"秒", "Second", "Seconds"}
        ):
            raise ExtractionError(slot + "_bill_item_binding")
        row_gross = _decimal(item["PretaxGrossAmount"], slot + "_gross")
        try:
            row_seconds = int(_string(item["ServicePeriod"], slot + "_seconds"))
        except ValueError as exc:
            raise ExtractionError(slot + "_seconds") from exc
        if row_seconds < 0:
            raise ExtractionError(slot + "_seconds")
        gross += row_gross
        service_seconds += row_seconds
        matched.append(
            {
                "instance_sha256": _commit("rds_instance_id", instance_id),
                "gross_cny": _decimal_text(row_gross),
                "service_seconds": row_seconds,
                "raw_item_sha256": _domain(
                    OBSERVATION_SET_DOMAIN,
                    {
                        "page_sha256": page_response_sha256,
                        "ordinal": ordinal,
                    },
                ),
            }
        )
    if not matched:
        raise ExtractionError(slot + "_instance_bill_missing")
    observation = {
        "slot": slot,
        "resource_sha256": _commit("rds_instance_id", instance_id),
        "billing_cycle": billing_cycle,
        "currency": "CNY",
        "pretax_gross_cny": _decimal_text(gross),
        "service_seconds": service_seconds,
        "matched_row_count": len(matched),
        "items": matched,
        "pages": page_rows,
        "historical_snapshot_only": True,
        "terminal_non_accruing_marker_present": False,
    }
    return {
        "schema": BILLING_PROJECTION_SCHEMA,
        **observation,
        "request_set_sha256": _domain(REQUEST_SET_DOMAIN, request_projections),
        "response_set_sha256": _domain(RESPONSE_SET_DOMAIN, response_projections),
        "provider_request_id_set_sha256": _domain(
            OBSERVATION_SET_DOMAIN,
            [row["provider_request_id_sha256"] for row in response_projections],
        ),
        "observation_set_sha256": _domain(OBSERVATION_SET_DOMAIN, observation),
        "page_inventory_sha256": _domain(PAGE_SET_DOMAIN, page_rows),
        "full_page_complete": True,
        "raw_record_count": len(rows),
        "raw_capture_sha256": capture.raw_sha256,
        "observed_at_utc": capture.observed_at_utc,
    }


def release_native_projection_sha256(
    *,
    release_contract_sha256: str,
    delete_projection: dict[str, Any],
    absence_projection: dict[str, Any],
    source_projection: dict[str, Any],
    preflight_source_instance: dict[str, Any],
    new_paid_resource_count: int,
) -> str:
    """Bind only provider-native release leaves; billing rows are not authority."""

    mutation_keys = {
        "schema", "slot", "operation", "target_sha256", "region_sha256",
        "request_body_sha256", "request_set_sha256", "response_set_sha256",
        "provider_request_id_set_sha256", "started_at_utc", "completed_at_utc",
        "submission_outcome", "raw_record_count", "raw_capture_sha256",
    }
    inventory_keys = {
        "schema", "slot", "target_sha256", "exact_count", "instances", "pages",
        "region_sha256", "request_set_sha256", "response_set_sha256",
        "provider_request_id_set_sha256", "observation_set_sha256",
        "page_inventory_sha256", "full_page_complete", "raw_record_count",
        "raw_capture_sha256", "observed_at_utc",
    }
    instance_keys = {
        "instance_sha256", "status", "pay_type", "engine", "engine_version",
        "deletion_protection", "vpc_sha256", "vswitch_sha256", "zone_sha256",
    }
    digest_keys = {
        "target_sha256", "region_sha256", "request_body_sha256",
        "request_set_sha256", "response_set_sha256",
        "provider_request_id_set_sha256", "raw_capture_sha256",
        "observation_set_sha256", "page_inventory_sha256",
    }
    if (
        type(release_contract_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", release_contract_sha256) is None
        or type(delete_projection) is not dict
        or set(delete_projection) != mutation_keys
        or type(absence_projection) is not dict
        or set(absence_projection) != inventory_keys
        or type(source_projection) is not dict
        or set(source_projection) != inventory_keys
        or delete_projection.get("schema") != MUTATION_PROJECTION_SCHEMA
        or absence_projection.get("schema") != INVENTORY_PROJECTION_SCHEMA
        or source_projection.get("schema") != INVENTORY_PROJECTION_SCHEMA
        or delete_projection.get("operation") != "DeleteDBInstance"
        or delete_projection.get("submission_outcome") != "ACCEPTED"
        or delete_projection.get("raw_record_count") != 1
        or absence_projection.get("exact_count") != 0
        or absence_projection.get("instances") != []
        or absence_projection.get("full_page_complete") is not True
        or source_projection.get("exact_count") != 1
        or source_projection.get("full_page_complete") is not True
        or delete_projection.get("target_sha256")
        != absence_projection.get("target_sha256")
        or delete_projection.get("region_sha256")
        != absence_projection.get("region_sha256")
        or source_projection.get("target_sha256")
        == delete_projection.get("target_sha256")
        or source_projection.get("region_sha256")
        != delete_projection.get("region_sha256")
        or any(
            type(value.get(key)) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value[key]) is None
            for value in (delete_projection, absence_projection, source_projection)
            for key in digest_keys.intersection(value)
        )
        or _utc(delete_projection.get("completed_at_utc"), "release_delete_time")
        > _utc(absence_projection.get("observed_at_utc"), "release_absence_time")
        or type(new_paid_resource_count) is not int
        or new_paid_resource_count != 0
    ):
        raise ExtractionError("release_native_projection")
    source_instances = source_projection.get("instances")
    if (
        type(source_instances) is not list
        or len(source_instances) != 1
        or type(source_instances[0]) is not dict
        or set(source_instances[0]) != instance_keys
        or type(preflight_source_instance) is not dict
        or set(preflight_source_instance) != instance_keys
        or source_instances[0] != preflight_source_instance
        or source_instances[0].get("instance_sha256")
        != source_projection.get("target_sha256")
        or source_instances[0].get("status") != "Running"
        or source_instances[0].get("pay_type") != "Prepaid"
        or source_instances[0].get("engine") != "PostgreSQL"
        or type(source_instances[0].get("engine_version")) is not str
        or not source_instances[0].get("engine_version", "").startswith("16")
        or source_instances[0].get("deletion_protection") is not True
        or any(
            type(source_instances[0].get(key)) is not str
            or re.fullmatch(r"[0-9a-f]{64}", source_instances[0][key]) is None
            for key in (
                "instance_sha256", "vpc_sha256", "vswitch_sha256", "zone_sha256"
            )
        )
    ):
        raise ExtractionError("release_source_projection")
    return _domain(
        RELEASE_NATIVE_DOMAIN,
        {
            "schema": "noteai.item26.rds-release-native-evidence.v1",
            "release_contract_sha256": release_contract_sha256,
            "delete": {
                key: delete_projection.get(key)
                for key in (
                    "target_sha256",
                    "request_body_sha256",
                    "request_set_sha256",
                    "response_set_sha256",
                    "provider_request_id_set_sha256",
                    "completed_at_utc",
                    "submission_outcome",
                )
            },
            "absence": {
                key: absence_projection.get(key)
                for key in (
                    "target_sha256",
                    "exact_count",
                    "request_set_sha256",
                    "response_set_sha256",
                    "provider_request_id_set_sha256",
                    "observation_set_sha256",
                    "page_inventory_sha256",
                    "full_page_complete",
                )
            },
            "source": {
                "target_sha256": source_projection.get("target_sha256"),
                "exact_count": source_projection.get("exact_count"),
                "instances": source_instances,
                "observation_set_sha256": source_projection.get(
                    "observation_set_sha256"
                ),
                "page_inventory_sha256": source_projection.get(
                    "page_inventory_sha256"
                ),
                "full_page_complete": source_projection.get(
                    "full_page_complete"
                ),
                "preflight_instance_sha256": _domain(
                    OBSERVATION_SET_DOMAIN,
                    preflight_source_instance,
                ),
            },
            "new_paid_resource_count": new_paid_resource_count,
        },
    )


def emitted_contains_raw_identifier(value: Any, raw_identifiers: Iterable[str]) -> bool:
    """Test/helper guard: confirm a Secret-free projection emitted no raw ID."""

    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return any(identifier and identifier in rendered for identifier in raw_identifiers)


__all__ = [
    "CAPTURE_SCHEMA",
    "ExtractionError",
    "OPERATION_ID",
    "RawCapture",
    "TASK_ID",
    "emitted_contains_raw_identifier",
    "parse_capture",
    "project_accepted_rds_mutation",
    "project_instance_bill",
    "project_rds_inventory",
    "require_exact_capture_slots",
    "release_native_projection_sha256",
]
