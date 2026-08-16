#!/usr/bin/env python3
"""Strict raw projection for the Item 26 manual post-action cost stop.

The two RDS mutations happened before this control source. This module never
authorizes or dispatches an action. It only projects two root-owned, canonical
captures: fresh read-only RDS/billing responses and a complete ActionTrail
``LookupEvents`` pagination chain.

ActionTrail events are consumed as direct management-event summaries. A
LookupEvents page RequestId is not a historical RDS mutation RequestId, and an
event summary is never used to invent a request body or ClientToken.
"""

from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any


TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":MANUAL-POST-ACTION-COST-STOP:v1"
M0_ANCHOR_REVISION = "85bf60f51f823c9e55e33dbf9bf6a84768a48f3e"
LEDGER_CONTEXT_REVISION = "41c489cf5ebfedfa2959bcee1f09183a9491f7f6"

PROVIDER_CAPTURE_SCHEMA = "noteai.item26.manual-cost-stop-provider-raw.v1"
ACTIONTRAIL_CAPTURE_SCHEMA = (
    "noteai.item26.manual-cost-stop-actiontrail-raw.v1"
)
PROVIDER_PROJECTION_SCHEMA = (
    "noteai.item26.manual-cost-stop-provider-projection.v1"
)
ACTIONTRAIL_PROJECTION_SCHEMA = (
    "noteai.item26.manual-cost-stop-actiontrail-projection.v1"
)
CAPTURE_SCHEMA = PROVIDER_CAPTURE_SCHEMA
PROJECTION_SCHEMA = PROVIDER_PROJECTION_SCHEMA

RAW_PROVIDER_EXTRACTION_IMPLEMENTED = True
RAW_ACTIONTRAIL_EXTRACTION_IMPLEMENTED = True
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_BYTES = 24 * 1024 * 1024
MAX_RECORDS = 64
MAX_EVENTS = 256
HEX40 = re.compile(r"^[0-9a-f]{40}$")
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)

EXPECTED_OLD_CLONE_SHA256 = (
    "820121638125fcebe3b7c03f3416ddae1fef1a0a9f1de731320fa75dd69a1525"
)
EXPECTED_OLD_CLONE_NAME_SHA256 = (
    "cdffd0d0a0dd6d6a57f19d8479125671d4484fabe502d5cf4073b016767e4ef1"
)
EXPECTED_SOURCE_SHA256 = (
    "d3712c09b28ee82257ab128fa1b5ba79b223f8b774e5fa20f761a2c4782eee8d"
)
EXPECTED_SOURCE_NAME_SHA256 = (
    "3911925626a615785629237e9dd27bb98e8b902f6eebaae6b185df6c0b84ebd7"
)
EXPECTED_BILLING_RESPONSE_SHA256 = (
    "ed2fda069a1902bda37abfb7e551929cc40f3c139cb4117179b1176b0127631a"
)
EXPECTED_PROTECTION_REQUEST_ID_SHA256 = (
    "c44eb336fc53b7850778bf61049f4df43ca562642084d3b3e6498be72d3cdc75"
)
EXPECTED_DELETE_REQUEST_ID_SHA256 = (
    "4ea974bc7aeba8cc49af916a68939d10e54107928fb0dfebcf0deca644c088ed"
)
EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256 = (
    "4a3216763ad561a7d6ddef25e4a387188fe91964fa9bb2ab86bf464050f25ec5"
)
EXPECTED_HISTORICAL_CONFIRMATION_AT = "2026-08-16T14:39:11.475Z"
EXPECTED_FINAL_ABSENCE_AT = "2026-08-16T14:44:50.237Z"
EXPECTED_REGION_SHA256 = (
    "c30c2414d1124664f36b6f1972809876bb4ca83039b24684eafe3186fe1f8bba"
)

PROVIDER_REQUIRED_SLOTS = (
    "fresh_clone_inventory",
    "fresh_source_inventory",
    "historical_billing_snapshot",
)
REQUIRED_SLOTS = PROVIDER_REQUIRED_SLOTS
PROVIDER_OPERATIONS = {
    "fresh_clone_inventory": ("DescribeDBInstances", "2014-08-15"),
    "fresh_source_inventory": ("DescribeDBInstances", "2014-08-15"),
    "historical_billing_snapshot": ("QueryInstanceBill", "2017-12-14"),
}
EXPECTED_ACTIONTRAIL_ACTIONS = (
    "ModifyDBInstanceDeletionProtection",
    "DeleteDBInstance",
)
TUPLE_DOMAIN = b"noteai-item26-manual-cost-stop-source-tuple-v1\0"
ACTIONTRAIL_SET_DOMAIN = (
    b"noteai-item26-manual-cost-stop-actiontrail-set-v1\0"
)
MUTATION_IDENTITY_DOMAIN = (
    b"noteai-item26-manual-cost-stop-consumed-mutations-v1\0"
)
MUTATION_IDENTITY_TOKEN_BOUND_DOMAIN = (
    b"noteai-item26-manual-cost-stop-consumed-mutations-token-bound-v1\0"
)


class ExtractionError(ValueError):
    """A fixed, non-sensitive extraction failure."""

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


def value_sha256(value: str) -> str:
    if type(value) is not str or not value:
        raise ExtractionError("identity_value")
    return sha256(value.encode("utf-8"))


def decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def logical_request_body_sha256(
    operation: str,
    parameters: dict[str, Any],
) -> str:
    if (
        type(operation) is not str
        or not operation
        or type(parameters) is not dict
        or "Action" in parameters
        or "Version" in parameters
    ):
        raise ExtractionError("logical_request_body")
    return sha256(canonical_bytes({
        "Action": operation,
        "Version": "2014-08-15",
        **parameters,
    }))


def consumed_mutation_identity_set_sha256(
    *,
    protection_request_id_sha256: str,
    protection_request_body_sha256: str,
    protection_client_token_sha256: str,
    delete_request_id_sha256: str,
    delete_request_body_sha256: str,
    delete_client_token_present: bool,
) -> str:
    base_projection = {
        "protection_disable_request_id_sha256": (
            protection_request_id_sha256
        ),
        "protection_disable_request_body_sha256": (
            protection_request_body_sha256
        ),
        "protection_disable_client_token_sha256": (
            protection_client_token_sha256
        ),
        "delete_request_id_sha256": delete_request_id_sha256,
        "delete_request_body_sha256": delete_request_body_sha256,
    }
    projection = {
        "delete_client_token_present": delete_client_token_present,
        "mutation_identity_v1_sha256": sha256(
            MUTATION_IDENTITY_DOMAIN
            + canonical_bytes(base_projection)[:-1]
        ),
    }
    return sha256(
        MUTATION_IDENTITY_TOKEN_BOUND_DOMAIN
        + canonical_bytes(projection)[:-1]
    )


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if not 1 <= len(raw) <= MAX_CAPTURE_BYTES or b"\0" in raw:
        raise ExtractionError(label + "_shape")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ExtractionError(label + "_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ExtractionError(label + "_number")
            ),
        )
    except ExtractionError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExtractionError(label + "_json") from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise ExtractionError(label + "_canonical")
    return value


def decode_canonical_json(encoded: Any, label: str) -> dict[str, Any]:
    raw, value = _decode_json_body(encoded, label)
    if canonical_bytes(value) != raw:
        raise ExtractionError(label + "_canonical")
    return value


def _decode_json_body(
    encoded: Any,
    label: str,
) -> tuple[bytes, dict[str, Any]]:
    if type(encoded) is not str or not encoded or len(encoded) > 4 * MAX_BODY_BYTES:
        raise ExtractionError(label + "_base64")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ExtractionError(label + "_base64") from exc
    if not 1 <= len(raw) <= MAX_BODY_BYTES or b"\0" in raw:
        raise ExtractionError(label + "_shape")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ExtractionError(label + "_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ExtractionError(label + "_number")
            ),
        )
    except ExtractionError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExtractionError(label + "_json") from exc
    if type(value) is not dict:
        raise ExtractionError(label + "_object")
    return raw, value


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


def _capture_header(
    value: Any,
    *,
    schema: str,
    expected_control_revision: str,
) -> tuple[datetime, list[dict[str, Any]]]:
    keys = {
        "schema", "task_id", "operation_id", "phase",
        "m0_anchor_revision", "control_revision", "observed_at_utc",
        "records",
    }
    if type(value) is not dict or set(value) != keys:
        raise ExtractionError("capture_schema")
    if (
        value["schema"] != schema
        or value["task_id"] != TASK_ID
        or value["operation_id"] != OPERATION_ID
        or value["phase"] != "POST_ACTION_READBACK_ONLY"
        or value["m0_anchor_revision"] != M0_ANCHOR_REVISION
        or value["control_revision"] != expected_control_revision
        or HEX40.fullmatch(expected_control_revision or "") is None
        or expected_control_revision in {M0_ANCHOR_REVISION, LEDGER_CONTEXT_REVISION}
        or type(value["records"]) is not list
        or not 1 <= len(value["records"]) <= MAX_RECORDS
    ):
        raise ExtractionError("capture_identity")
    observed_at = _utc(value["observed_at_utc"], "capture_observed_at")
    return observed_at, value["records"]


def _record(
    value: Any,
    *,
    observed_at: datetime,
    allowed_slots: set[str],
) -> tuple[bytes, dict[str, Any], bytes, dict[str, Any]]:
    keys = {
        "sequence", "slot", "operation", "api_version",
        "started_at_utc", "completed_at_utc", "transport_outcome",
        "read_only", "request_json_base64", "response_json_base64",
    }
    if type(value) is not dict or set(value) != keys:
        raise ExtractionError("record_schema")
    if (
        type(value["sequence"]) is not int
        or value["sequence"] < 1
        or type(value["slot"]) is not str
        or value["slot"] not in allowed_slots
        or type(value["operation"]) is not str
        or not value["operation"]
        or type(value["api_version"]) is not str
        or not value["api_version"]
        or value["transport_outcome"] != "RESPONSE_RECEIVED"
        or value["read_only"] is not True
    ):
        raise ExtractionError("record_identity")
    started_at = _utc(value["started_at_utc"], "record_started_at")
    completed_at = _utc(value["completed_at_utc"], "record_completed_at")
    if not started_at <= completed_at <= observed_at:
        raise ExtractionError("record_time_order")
    request_raw, request = _decode_json_body(
        value["request_json_base64"], "request"
    )
    response_raw, response = _decode_json_body(
        value["response_json_base64"], "response"
    )
    return request_raw, request, response_raw, response


def _instance_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        "Items", "PageNumber", "PageRecordCount", "RequestId",
        "TotalRecordCount",
    }
    if not required.issubset(response):
        raise ExtractionError("rds_response_schema")
    items = response.get("Items")
    if type(items) is not dict or set(items) != {"DBInstance"}:
        raise ExtractionError("rds_response_items")
    rows = items.get("DBInstance")
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise ExtractionError("rds_response_items")
    total = response.get("TotalRecordCount")
    if (
        type(total) is not int
        or total != len(rows)
        or type(response.get("PageNumber")) is not int
        or response["PageNumber"] != 1
        or type(response.get("PageRecordCount")) is not int
        or response["PageRecordCount"] != len(rows)
        or type(response.get("RequestId")) is not str
        or not response["RequestId"]
        or response.get("NextToken") not in {None, ""}
    ):
        raise ExtractionError("rds_response_count")
    return rows


def _require_describe_request(
    request: dict[str, Any],
    *,
    expected_identity_sha256: str,
) -> None:
    expected_keys = {
        "Action", "Version", "RegionId", "DBInstanceId",
        "PageNumber", "PageSize",
    }
    if (
        set(request) != expected_keys
        or request.get("Action") != "DescribeDBInstances"
        or request.get("Version") != "2014-08-15"
        or type(request.get("RegionId")) is not str
        or not request["RegionId"]
        or value_sha256(request["RegionId"]) != EXPECTED_REGION_SHA256
        or type(request.get("DBInstanceId")) is not str
        or value_sha256(request["DBInstanceId"]) != expected_identity_sha256
        or type(request.get("PageNumber")) is not int
        or request["PageNumber"] != 1
        or type(request.get("PageSize")) is not int
        or request["PageSize"] != 100
    ):
        raise ExtractionError("describe_request_identity")


def _source_row(row: dict[str, Any]) -> dict[str, Any]:
    identity = row.get("DBInstanceId")
    name = row.get("DBInstanceDescription")
    status = row.get("DBInstanceStatus")
    pay_type = row.get("PayType")
    engine = row.get("Engine")
    engine_version = row.get("EngineVersion")
    if (
        type(identity) is not str
        or value_sha256(identity) != EXPECTED_SOURCE_SHA256
        or type(name) is not str
        or value_sha256(name) != EXPECTED_SOURCE_NAME_SHA256
        or status != "Running"
        or pay_type != "Prepaid"
        or engine != "PostgreSQL"
        or str(engine_version) != "16"
    ):
        raise ExtractionError("source_tuple")
    tuple_projection = {
        "identity_sha256": EXPECTED_SOURCE_SHA256,
        "name_sha256": EXPECTED_SOURCE_NAME_SHA256,
        "status": "Running",
        "pay_type": "Prepaid",
        "engine": "PostgreSQL",
        "engine_version": "16",
    }
    return {
        **tuple_projection,
        "tuple_sha256": sha256(TUPLE_DOMAIN + canonical_bytes(tuple_projection)[:-1]),
    }


def _billing_rows(
    request: dict[str, Any],
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_request = {
        "Action": "QueryInstanceBill",
        "Version": "2017-12-14",
        "BillingCycle": "2026-08",
        "ProductCode": "rds",
        "SubscriptionType": "PayAsYouGo",
        "IsBillingItem": False,
        "IsHideZeroCharge": False,
        "Granularity": "MONTHLY",
        "PageNum": 1,
        "PageSize": 300,
    }
    if type(request) is not dict or set(request) != set(expected_request) or any(
        type(request.get(key)) is not type(expected)
        or request.get(key) != expected
        for key, expected in expected_request.items()
    ):
        raise ExtractionError("billing_request")
    if response.get("Success") is not True or response.get("Code") != "Success":
        raise ExtractionError("billing_response_status")
    if type(response.get("RequestId")) is not str or not response["RequestId"]:
        raise ExtractionError("billing_response_status")
    data = response.get("Data")
    if type(data) is not dict:
        raise ExtractionError("billing_response_data")
    items = data.get("Items")
    if type(items) is not dict or set(items) != {"Item"}:
        raise ExtractionError("billing_response_items")
    rows = items.get("Item")
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise ExtractionError("billing_response_items")
    total = data.get("TotalCount")
    if (
        type(total) is not int
        or total != len(rows)
        or type(data.get("PageNum")) is not int
        or data["PageNum"] != 1
        or type(data.get("PageSize")) is not int
        or data["PageSize"] != 300
        or data.get("BillingCycle") != "2026-08"
    ):
        raise ExtractionError("billing_response_count")
    return rows


def project_provider_readback(
    raw: bytes,
    *,
    expected_control_revision: str,
) -> dict[str, Any]:
    if not RAW_PROVIDER_EXTRACTION_IMPLEMENTED:
        raise ExtractionError("provider_extractor_not_finalized")
    capture = _strict_json(raw, "provider_capture")
    observed_at, records = _capture_header(
        capture,
        schema=PROVIDER_CAPTURE_SCHEMA,
        expected_control_revision=expected_control_revision,
    )
    if [record.get("sequence") for record in records] != [1, 2, 3]:
        raise ExtractionError("provider_record_sequence")
    if [record.get("slot") for record in records] != list(PROVIDER_REQUIRED_SLOTS):
        raise ExtractionError("provider_capture_slots")

    parsed: dict[
        str,
        tuple[bytes, dict[str, Any], bytes, dict[str, Any]],
    ] = {}
    response_hashes: dict[str, str] = {}
    prior_completed: datetime | None = None
    first_started_text: str | None = None
    last_completed_text: str | None = None
    for record in records:
        slot = record["slot"]
        expected_operation, expected_version = PROVIDER_OPERATIONS[slot]
        if record.get("operation") != expected_operation or record.get("api_version") != expected_version:
            raise ExtractionError("provider_operation")
        started_at = _utc(record.get("started_at_utc"), "record_started_at")
        completed_at = _utc(
            record.get("completed_at_utc"), "record_completed_at"
        )
        if prior_completed is not None and started_at < prior_completed:
            raise ExtractionError("provider_record_time_order")
        prior_completed = completed_at
        if first_started_text is None:
            first_started_text = record["started_at_utc"]
        last_completed_text = record["completed_at_utc"]
        request_raw, request, response_raw, response = _record(
            record,
            observed_at=observed_at,
            allowed_slots=set(PROVIDER_REQUIRED_SLOTS),
        )
        parsed[slot] = (request_raw, request, response_raw, response)
        response_hashes[slot] = sha256(response_raw)

    _clone_request_raw, clone_request, _clone_response_raw, clone_response = (
        parsed["fresh_clone_inventory"]
    )
    _require_describe_request(clone_request, expected_identity_sha256=EXPECTED_OLD_CLONE_SHA256)
    if _instance_rows(clone_response):
        raise ExtractionError("old_clone_still_present")

    _source_request_raw, source_request, _source_response_raw, source_response = (
        parsed["fresh_source_inventory"]
    )
    _require_describe_request(source_request, expected_identity_sha256=EXPECTED_SOURCE_SHA256)
    source_rows = _instance_rows(source_response)
    if len(source_rows) != 1:
        raise ExtractionError("source_match_count")
    source = _source_row(source_rows[0])

    (
        _billing_request_raw,
        billing_request,
        _billing_response_raw,
        billing_response,
    ) = parsed["historical_billing_snapshot"]
    billing_rows = _billing_rows(billing_request, billing_response)
    matches = [
        row for row in billing_rows
        if type(row.get("InstanceID")) is str
        and value_sha256(row["InstanceID"]) == EXPECTED_OLD_CLONE_SHA256
    ]
    if len(matches) != 1:
        raise ExtractionError("billing_identity")
    billing = matches[0]
    service_seconds = billing.get("ServicePeriod")
    if type(service_seconds) is str and service_seconds.isdecimal():
        service_seconds = int(service_seconds)
    if (
        billing.get("Currency") != "CNY"
        or type(billing.get("SubscriptionType")) is not str
        or billing["SubscriptionType"] != "PayAsYouGo"
        or str(billing.get("ProductCode", "")).lower() != "rds"
        or str(billing.get("PipCode", "")).lower() != "rds"
        or billing.get("ServicePeriodUnit") not in {"Second", "Seconds", "秒"}
        or type(billing.get("PretaxGrossAmount")) not in {int, float, str}
        or service_seconds is None
    ):
        raise ExtractionError("billing_snapshot")
    try:
        gross = Decimal(str(billing["PretaxGrossAmount"]))
    except (InvalidOperation, ValueError) as exc:
        raise ExtractionError("billing_snapshot") from exc
    if (
        not gross.is_finite()
        or gross < Decimal("198.462")
        or type(service_seconds) is not int
        or service_seconds < 345600
    ):
        raise ExtractionError("billing_snapshot")

    return {
        "schema": PROVIDER_PROJECTION_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "control_revision": expected_control_revision,
        "observed_at_utc": capture["observed_at_utc"],
        "first_started_at_utc": first_started_text,
        "last_completed_at_utc": last_completed_text,
        "provider_raw_file_sha256": sha256(raw),
        "region_sha256": EXPECTED_REGION_SHA256,
        "old_clone": {
            "identity_sha256": EXPECTED_OLD_CLONE_SHA256,
            "match_count": 0,
            "absent": True,
        },
        "source": source,
        "billing": {
            "resource_identity_sha256": EXPECTED_OLD_CLONE_SHA256,
            "currency": "CNY",
            "pretax_gross_cny": decimal_text(gross),
            "service_seconds": service_seconds,
            "response_sha256": response_hashes["historical_billing_snapshot"],
            "recorded_baseline_pretax_gross_cny": "198.462",
            "recorded_baseline_service_seconds": 345600,
            "recorded_baseline_response_sha256": (
                EXPECTED_BILLING_RESPONSE_SHA256
            ),
            "historical_snapshot_only": True,
            "native_non_accruing_marker_proven": False,
            "settlement_terminal_proven": False,
        },
        "response_commitments": response_hashes,
        "ledger_commitments_rederived_from_fresh_raw": False,
        "complete_resource_identifier_value_count": 0,
        "raw_provider_value_emitted_count": 0,
    }


def _lookup_attributes(request: dict[str, Any], stream: str) -> None:
    attributes = request.get("LookupAttribute")
    if (
        type(attributes) is not list
        or len(attributes) != 2
        or any(
            type(item) is not dict
            or set(item) != {"Key", "Value"}
            for item in attributes
        )
    ):
        raise ExtractionError("actiontrail_lookup_attributes")
    values = {item["Key"]: item["Value"] for item in attributes}
    if len(values) != 2:
        raise ExtractionError("actiontrail_lookup_attributes")
    if stream == "cost_stop":
        if values != {"ServiceName": "Rds", "EventRW": "Write"}:
            raise ExtractionError("actiontrail_lookup_attributes")
    elif stream == "clone_create":
        if (
            set(values) != {"EventName", "ResourceName"}
            or values["EventName"] != "CloneDBInstance"
            or type(values["ResourceName"]) is not str
            or value_sha256(values["ResourceName"])
            != EXPECTED_OLD_CLONE_SHA256
        ):
            raise ExtractionError("actiontrail_lookup_attributes")
    else:
        raise ExtractionError("actiontrail_lookup_stream")


def _event_request_parameters(event: dict[str, Any]) -> dict[str, Any] | None:
    direct = event.get("requestParameters")
    encoded = event.get("requestParameterJson")
    parsed: dict[str, Any] | None = None
    if direct is not None:
        if type(direct) is not dict:
            raise ExtractionError("actiontrail_request_parameters")
        parsed = direct
    if encoded is not None:
        if type(encoded) is not str or not encoded:
            raise ExtractionError("actiontrail_request_parameter_json")
        def reject_duplicates(
            pairs: list[tuple[str, Any]],
        ) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    raise ExtractionError(
                        "actiontrail_request_parameter_duplicate"
                    )
                result[key] = item
            return result

        try:
            decoded = json.loads(
                encoded,
                object_pairs_hook=reject_duplicates,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ExtractionError("actiontrail_request_parameter_number")
                ),
            )
        except ExtractionError:
            raise
        except json.JSONDecodeError as exc:
            raise ExtractionError("actiontrail_request_parameter_json") from exc
        if type(decoded) is not dict or (parsed is not None and decoded != parsed):
            raise ExtractionError("actiontrail_request_parameter_json")
        parsed = decoded
    if parsed is not None and any(
        key in parsed for key in ("Action", "Version")
    ):
        raise ExtractionError("actiontrail_request_parameters_reserved")
    return parsed


def _lookup_stream(
    records: list[dict[str, Any]],
    *,
    slot: str,
    stream: str,
    observed_at: datetime,
) -> tuple[
    list[dict[str, Any]],
    list[str],
    datetime,
    datetime,
    str,
    str,
    list[str],
]:
    if not records:
        raise ExtractionError("actiontrail_stream_missing")
    prior_next_token: str | None = None
    seen_nonterminal_tokens: set[str] = set()
    terminal_seen = False
    page_request_ids: list[str] = []
    events: list[dict[str, Any]] = []
    query_start: datetime | None = None
    query_end: datetime | None = None
    first_started_text: str | None = None
    last_completed_text: str | None = None
    prior_completed: datetime | None = None
    response_body_hashes: list[str] = []
    for index, record in enumerate(records):
        if (
            record.get("slot") != slot
            or record.get("operation") != "LookupEvents"
            or record.get("api_version") != "2020-07-06"
        ):
            raise ExtractionError("actiontrail_operation")
        started = _utc(record.get("started_at_utc"), "record_started_at")
        completed = _utc(
            record.get("completed_at_utc"), "record_completed_at"
        )
        if prior_completed is not None and started < prior_completed:
            raise ExtractionError("actiontrail_record_time_order")
        prior_completed = completed
        if first_started_text is None:
            first_started_text = record["started_at_utc"]
        last_completed_text = record["completed_at_utc"]
        _request_raw, request, response_raw, response = _record(
            record,
            observed_at=observed_at,
            allowed_slots={slot},
        )
        if terminal_seen:
            raise ExtractionError("actiontrail_page_after_terminal")
        expected_request_keys = {
            "Action", "Version", "Direction", "EndTime",
            "LookupAttribute", "MaxResults", "StartTime",
        }
        if index > 0:
            expected_request_keys.add("NextToken")
        if (
            set(request) != expected_request_keys
            or request.get("Action") != "LookupEvents"
            or request.get("Version") != "2020-07-06"
            or request.get("Direction") != "FORWARD"
            or type(request.get("MaxResults")) is not str
            or not request["MaxResults"].isdecimal()
            or not 1 <= int(request["MaxResults"]) <= 50
        ):
            raise ExtractionError("actiontrail_request")
        _lookup_attributes(request, stream)
        start = _utc(request.get("StartTime"), "actiontrail_start")
        end = _utc(request.get("EndTime"), "actiontrail_end")
        if not start < end <= observed_at:
            raise ExtractionError("actiontrail_window")
        if index == 0:
            if request.get("NextToken") not in {None, ""}:
                raise ExtractionError("actiontrail_first_token")
            query_start, query_end = start, end
        elif (
            start != query_start
            or end != query_end
            or request.get("NextToken") != prior_next_token
        ):
            raise ExtractionError("actiontrail_token_chain")
        request_id = response.get("RequestId")
        page_events = response.get("Events")
        if (
            type(request_id) is not str
            or not request_id
            or type(page_events) is not list
            or len(page_events) > MAX_EVENTS
            or any(type(event) is not dict for event in page_events)
            or _utc(response.get("StartTime"), "actiontrail_response_start")
            != start
            or _utc(response.get("EndTime"), "actiontrail_response_end")
            != end
        ):
            raise ExtractionError("actiontrail_response")
        page_request_ids.append(request_id)
        response_body_hashes.append(sha256(response_raw))
        events.extend(page_events)
        token = response.get("NextToken")
        if token in {None, ""}:
            terminal_seen = True
            prior_next_token = None
        elif type(token) is str:
            if token in seen_nonterminal_tokens:
                raise ExtractionError("actiontrail_response_token_reuse")
            seen_nonterminal_tokens.add(token)
            prior_next_token = token
        else:
            raise ExtractionError("actiontrail_response_token")
    if (
        not terminal_seen
        or query_start is None
        or query_end is None
        or first_started_text is None
        or last_completed_text is None
    ):
        raise ExtractionError("actiontrail_incomplete_pagination")
    if len(set(page_request_ids)) != len(page_request_ids):
        raise ExtractionError("actiontrail_page_request_id_reuse")
    return (
        events,
        page_request_ids,
        query_start,
        query_end,
        first_started_text,
        last_completed_text,
        response_body_hashes,
    )


def _event_base(
    event: dict[str, Any],
    *,
    allowed_names: set[str],
    start: datetime,
    end: datetime,
) -> tuple[str, str, dict[str, Any], datetime, dict[str, Any]]:
    required = {
        "eventId", "eventName", "eventRW", "eventSource", "eventTime",
        "resourceName", "resourceType", "serviceName", "userIdentity",
    }
    if not required.issubset(event):
        raise ExtractionError("actiontrail_event_schema")
    event_id = event["eventId"]
    event_name = event["eventName"]
    resource_name = event["resourceName"]
    user_identity = event["userIdentity"]
    if type(user_identity) is str:
        def reject_identity_duplicates(
            pairs: list[tuple[str, Any]],
        ) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    raise ExtractionError(
                        "actiontrail_user_identity_duplicate"
                    )
                result[key] = item
            return result

        try:
            user_identity = json.loads(
                user_identity,
                object_pairs_hook=reject_identity_duplicates,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ExtractionError("actiontrail_user_identity_number")
                ),
            )
        except ExtractionError:
            raise
        except (TypeError, json.JSONDecodeError) as exc:
            raise ExtractionError("actiontrail_user_identity") from exc
    event_time = _utc(event["eventTime"], "actiontrail_event_time")
    if (
        type(event_id) is not str
        or not event_id
        or event_name not in allowed_names
        or event["eventRW"] != "Write"
        or str(event["serviceName"]).lower() != "rds"
        or event["eventSource"] != "rds.aliyuncs.com"
        or type(resource_name) is not str
        or value_sha256(resource_name) != EXPECTED_OLD_CLONE_SHA256
        or type(event["resourceType"]) is not str
        or not event["resourceType"]
        or type(user_identity) is not dict
        or not start <= event_time <= end
        or event.get("errorCode") not in {None, ""}
    ):
        raise ExtractionError("actiontrail_event_identity")
    base = {
        "event_id_sha256": value_sha256(event_id),
        "event_name": event_name,
        "event_time": event["eventTime"],
        "event_rw": "Write",
        "event_source": "rds.aliyuncs.com",
        "service_name": "Rds",
        "resource_name_sha256": EXPECTED_OLD_CLONE_SHA256,
        "resource_type_sha256": value_sha256(event["resourceType"]),
        "user_identity_sha256": sha256(canonical_bytes(user_identity)),
    }
    return event_id, event_name, user_identity, event_time, base


def project_actiontrail_readback(
    raw: bytes,
    *,
    expected_control_revision: str,
) -> dict[str, Any]:
    if not RAW_ACTIONTRAIL_EXTRACTION_IMPLEMENTED:
        raise ExtractionError("actiontrail_extractor_not_finalized")
    capture = _strict_json(raw, "actiontrail_capture")
    observed_at, records = _capture_header(
        capture,
        schema=ACTIONTRAIL_CAPTURE_SCHEMA,
        expected_control_revision=expected_control_revision,
    )
    if [record.get("sequence") for record in records] != list(range(1, len(records) + 1)):
        raise ExtractionError("actiontrail_record_sequence")

    cost_records = [
        record
        for record in records
        if record.get("slot") == "cost_stop_rds_write_lookup_page"
    ]
    create_records = [
        record
        for record in records
        if record.get("slot") == "clone_create_lookup_page"
    ]
    if len(cost_records) + len(create_records) != len(records):
        raise ExtractionError("actiontrail_operation")
    slots = [record.get("slot") for record in records]
    if slots != [
        *(["cost_stop_rds_write_lookup_page"] * len(cost_records)),
        *(["clone_create_lookup_page"] * len(create_records)),
    ]:
        raise ExtractionError("actiontrail_stream_order")
    (
        events,
        cost_page_ids,
        query_start,
        query_end,
        cost_first_started,
        cost_last_completed,
        cost_response_hashes,
    ) = _lookup_stream(
        cost_records,
        slot="cost_stop_rds_write_lookup_page",
        stream="cost_stop",
        observed_at=observed_at,
    )
    (
        create_events,
        create_page_ids,
        create_start,
        create_end,
        create_first_started,
        create_last_completed,
        create_response_hashes,
    ) = _lookup_stream(
        create_records,
        slot="clone_create_lookup_page",
        stream="clone_create",
        observed_at=observed_at,
    )
    if len(set(cost_page_ids + create_page_ids)) != len(
        cost_page_ids + create_page_ids
    ):
        raise ExtractionError("actiontrail_page_request_id_reuse")
    confirmation_time = _utc(
        EXPECTED_HISTORICAL_CONFIRMATION_AT,
        "confirmation_time",
    )
    if not (
        query_start
        <= confirmation_time
        <= _utc(EXPECTED_FINAL_ABSENCE_AT, "absence_time")
        <= query_end
        and create_end < confirmation_time
    ):
        raise ExtractionError("actiontrail_window_scope")
    if len(events) != 2 or len(create_events) != 1:
        raise ExtractionError("actiontrail_event_count")

    event_projection: list[dict[str, Any]] = []
    event_ids: list[str] = []
    user_identity_hashes: set[str] = set()
    mutation_request_ids_rederived = True
    mutation_request_parameters_rederived = True
    mutation_client_tokens_rederived = True
    for event in events:
        event_id, event_name, user_identity, _event_time, base = _event_base(
            event,
            allowed_names=set(EXPECTED_ACTIONTRAIL_ACTIONS),
            start=query_start,
            end=query_end,
        )
        event_ids.append(event_id)
        user_identity_sha256 = sha256(canonical_bytes(user_identity))
        user_identity_hashes.add(user_identity_sha256)
        provider_request_id = event.get("requestId")
        expected_request_id = (
            EXPECTED_PROTECTION_REQUEST_ID_SHA256
            if event_name == "ModifyDBInstanceDeletionProtection"
            else EXPECTED_DELETE_REQUEST_ID_SHA256
        )
        if type(provider_request_id) is not str or not provider_request_id:
            provider_request_id_sha256 = None
            mutation_request_ids_rederived = False
        else:
            provider_request_id_sha256 = value_sha256(provider_request_id)
            if provider_request_id_sha256 != expected_request_id:
                raise ExtractionError("actiontrail_provider_request_id")
        parameters = _event_request_parameters(event)
        request_body_sha256 = None
        client_token_present = None
        client_token_sha256 = None
        if parameters is None:
            mutation_request_parameters_rederived = False
            mutation_client_tokens_rederived = False
        else:
            target = parameters.get("DBInstanceId")
            if (
                type(target) is not str
                or value_sha256(target) != EXPECTED_OLD_CLONE_SHA256
            ):
                raise ExtractionError("actiontrail_request_target")
            request_body_sha256 = logical_request_body_sha256(
                event_name, parameters
            )
            client_token_present = "ClientToken" in parameters
            if event_name == "ModifyDBInstanceDeletionProtection":
                deletion_protection = parameters.get("DeletionProtection")
                if (
                    not (
                        deletion_protection is False
                        or (
                            type(deletion_protection) is str
                            and deletion_protection == "false"
                        )
                    )
                    or type(parameters.get("ClientToken")) is not str
                    or value_sha256(parameters["ClientToken"])
                    != EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256
                ):
                    raise ExtractionError("actiontrail_protection_parameters")
                client_token_sha256 = EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256
            elif client_token_present:
                raise ExtractionError("actiontrail_delete_client_token")
        event_projection.append({
            **base,
            "provider_request_id_sha256": provider_request_id_sha256,
            "request_body_sha256": request_body_sha256,
            "client_token_present": client_token_present,
            "client_token_sha256": client_token_sha256,
        })
    if (
        len(set(event_ids)) != 2
        or {row["event_name"] for row in event_projection} != set(EXPECTED_ACTIONTRAIL_ACTIONS)
        or len(user_identity_hashes) != 1
    ):
        raise ExtractionError("actiontrail_event_set")
    event_projection.sort(key=lambda row: (row["event_time"], row["event_name"]))
    if [row["event_name"] for row in event_projection] != list(EXPECTED_ACTIONTRAIL_ACTIONS):
        raise ExtractionError("actiontrail_event_order")
    protection_time = _utc(
        event_projection[0]["event_time"], "protection_event_time"
    )
    deletion_time = _utc(
        event_projection[1]["event_time"], "delete_event_time"
    )
    final_absence_time = _utc(
        EXPECTED_FINAL_ABSENCE_AT, "absence_time"
    )
    if not (
        confirmation_time <= protection_time < deletion_time
        <= final_absence_time
    ):
        raise ExtractionError("actiontrail_mutation_time_order")

    create_event = create_events[0]
    create_event_id, _create_name, _create_user, create_time, create_base = (
        _event_base(
            create_event,
            allowed_names={"CloneDBInstance"},
            start=create_start,
            end=create_end,
        )
    )
    create_request_id = create_event.get("requestId")
    create_parameters = _event_request_parameters(create_event)
    create_proven = bool(
        type(create_request_id) is str
        and create_request_id
        and create_parameters is not None
    )
    create_request_id_sha256 = None
    create_body_sha256 = None
    create_client_token_sha256 = None
    if create_proven:
        source_candidates = [
            create_parameters.get("DBInstanceId"),
            create_parameters.get("SourceDBInstanceId"),
        ]
        source_candidates = [
            value
            for value in source_candidates
            if type(value) is str and value
        ]
        description = create_parameters.get("DBInstanceDescription")
        client_token = create_parameters.get("ClientToken")
        if (
            len(source_candidates) != 1
            or value_sha256(source_candidates[0]) != EXPECTED_SOURCE_SHA256
            or type(description) is not str
            or value_sha256(description) != EXPECTED_OLD_CLONE_NAME_SHA256
            or type(client_token) is not str
            or not client_token
        ):
            raise ExtractionError("actiontrail_clone_create_parameters")
        create_request_id_sha256 = value_sha256(create_request_id)
        create_body_sha256 = logical_request_body_sha256(
            "CloneDBInstance", create_parameters
        )
        create_client_token_sha256 = value_sha256(client_token)
    if create_time >= confirmation_time:
        raise ExtractionError("actiontrail_clone_create_time")
    if create_event_id in event_ids:
        raise ExtractionError("actiontrail_event_id_reuse")
    clone_create_projection = {
        **create_base,
        "provider_request_id_sha256": create_request_id_sha256,
        "request_body_sha256": create_body_sha256,
        "client_token_present": (
            True if create_proven else None
        ),
        "client_token_sha256": create_client_token_sha256,
        "identity_rederived": create_proven,
    }
    first_started_candidates = (
        cost_first_started,
        create_first_started,
    )
    last_completed_candidates = (
        cost_last_completed,
        create_last_completed,
    )
    first_started_text = min(
        first_started_candidates,
        key=lambda value: _utc(value, "actiontrail_first_started"),
    )
    last_completed_text = max(
        last_completed_candidates,
        key=lambda value: _utc(value, "actiontrail_last_completed"),
    )
    return {
        "schema": ACTIONTRAIL_PROJECTION_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "control_revision": expected_control_revision,
        "observed_at_utc": capture["observed_at_utc"],
        "first_started_at_utc": first_started_text,
        "last_completed_at_utc": last_completed_text,
        "actiontrail_raw_file_sha256": sha256(raw),
        "cost_stop_lookup_page_count": len(cost_records),
        "clone_create_lookup_page_count": len(create_records),
        "complete_pagination_proven": True,
        "event_count": 3,
        "events": event_projection,
        "clone_create": clone_create_projection,
        "event_set_sha256": sha256(ACTIONTRAIL_SET_DOMAIN + canonical_bytes(event_projection)[:-1]),
        "page_response_body_sha256": sha256(
            ACTIONTRAIL_SET_DOMAIN
            + canonical_bytes(cost_response_hashes + create_response_hashes)[:-1]
        ),
        "historical_mutation_request_ids_rederived": (
            mutation_request_ids_rederived
        ),
        "historical_request_bodies_rederived": (
            mutation_request_parameters_rederived
        ),
        "historical_client_tokens_rederived": (
            mutation_client_tokens_rederived
        ),
        "old_clone_create_identity_rederived": create_proven,
        "complete_resource_identifier_value_count": 0,
        "raw_actiontrail_value_emitted_count": 0,
    }


_VERIFIED_PROJECTION_TOKEN = object()


class VerifiedManualProjection:
    """Opaque projection constructible only after both strict projections."""

    __slots__ = ("_provider", "_actiontrail")

    def __init__(
        self,
        provider: dict[str, Any],
        actiontrail: dict[str, Any],
        *,
        token: object,
    ) -> None:
        if token is not _VERIFIED_PROJECTION_TOKEN:
            raise ExtractionError("verified_projection_loader_required")
        if provider["control_revision"] != actiontrail["control_revision"]:
            raise ExtractionError("projection_revision_mismatch")
        self._provider = copy.deepcopy(provider)
        self._actiontrail = copy.deepcopy(actiontrail)

    @property
    def control_revision(self) -> str:
        return self._provider["control_revision"]

    @property
    def provider(self) -> dict[str, Any]:
        return copy.deepcopy(self._provider)

    @property
    def actiontrail(self) -> dict[str, Any]:
        return copy.deepcopy(self._actiontrail)


def extract_verified_projection(
    provider_raw: bytes,
    actiontrail_raw: bytes,
    *,
    expected_control_revision: str,
) -> VerifiedManualProjection:
    provider = project_provider_readback(provider_raw, expected_control_revision=expected_control_revision)
    actiontrail = project_actiontrail_readback(actiontrail_raw, expected_control_revision=expected_control_revision)
    return VerifiedManualProjection(provider, actiontrail, token=_VERIFIED_PROJECTION_TOKEN)


def validate_capture_envelope(_value: Any) -> None:
    raise ExtractionError("mixed_capture_schema_retired")


def extract_projection(_capture: Any) -> dict[str, Any]:
    raise ExtractionError("mixed_capture_schema_retired")


__all__ = [
    "ACTIONTRAIL_CAPTURE_SCHEMA", "ACTIONTRAIL_PROJECTION_SCHEMA",
    "CAPTURE_SCHEMA", "EXPECTED_ACTIONTRAIL_ACTIONS", "ExtractionError",
    "M0_ANCHOR_REVISION", "OPERATION_ID", "PROJECTION_SCHEMA",
    "PROVIDER_CAPTURE_SCHEMA", "PROVIDER_PROJECTION_SCHEMA",
    "PROVIDER_REQUIRED_SLOTS", "RAW_ACTIONTRAIL_EXTRACTION_IMPLEMENTED",
    "RAW_PROVIDER_EXTRACTION_IMPLEMENTED", "REQUIRED_SLOTS", "TASK_ID",
    "VerifiedManualProjection", "canonical_bytes", "decode_canonical_json",
    "extract_projection", "extract_verified_projection",
    "project_actiontrail_readback", "project_provider_readback", "sha256",
    "validate_capture_envelope", "value_sha256",
]
