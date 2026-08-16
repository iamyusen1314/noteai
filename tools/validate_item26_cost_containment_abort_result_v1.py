#!/usr/bin/env python3
"""Pure semantic validator for the Item 26 cost-containment abort.

This module performs no provider calls and accepts no production identifiers.
It validates only Secret-free commitments derived from a separately retained,
root-owned raw closure.  A successful abort closes the old clone's metering;
it never verifies the PITR restore and never grants readiness credit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any


VALIDATOR_REF = "tools/validate_item26_cost_containment_abort_result_v1.py"
RELEASE_BILLING_CONTRACT_REF = (
    "deploy/production/plans/item26-rds-release-billing-contract-v1.json"
)
EXPECTED_RELEASE_BILLING_CONTRACT_SHA256 = (
    "985d08f9fb5350b3c48e11b1193a683991e60ad4b8dd4ca087c00ae4ebb908e2"
)
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":COST_CONTAINMENT_ABORT:v1"
TERMINAL_STATUS = "COST_CONTAINMENT_ABORT_TERMINAL_CLEAN"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DECIMAL_CNY = re.compile(r"^(0|[1-9]\d*)(?:\.\d{1,6})?$")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
MAX_CONFIRMATION_TTL = timedelta(minutes=10)
MAX_PREFLIGHT_AGE = timedelta(minutes=2)
KNOWN_BILLING_CYCLE = "2026-08"
KNOWN_24H_CEILING_CNY = "76.824"
KNOWN_PRE_ABORT_GROSS_CNY = "185.658"
KNOWN_PRE_ABORT_SERVICE_SECONDS = 331200
EXPECTED_HISTORICAL_REGISTRY_SHA256 = (
    "763ae967af95f55347e427f9df8e6c7014b16e645957417915e3ccd44d20e5d9"
)

SEMANTIC_DOMAIN = b"noteai-item26-cost-containment-abort-semantic-v1\0"
PREFLIGHT_DOMAIN = b"noteai-item26-cost-containment-abort-preflight-v1\0"
PLAN_DOMAIN = b"noteai-item26-cost-containment-abort-plan-v1\0"
REQUEST_SET_DOMAIN = b"noteai-item26-cost-containment-abort-request-set-v1\0"
RESPONSE_SET_DOMAIN = b"noteai-item26-cost-containment-abort-response-set-v1\0"
RESPONSE_PROJECTION_DOMAIN = (
    b"noteai-item26-cost-containment-abort-response-projection-v1\0"
)
PAGE_INVENTORY_DOMAIN = b"noteai-item26-cost-containment-abort-page-inventory-v1\0"
BILLING_SET_DOMAIN = b"noteai-item26-cost-containment-abort-billing-set-v1\0"
DISPOSITION_SET_DOMAIN = b"noteai-item26-cost-containment-abort-disposition-set-v1\0"
FINAL_STATE_DOMAIN = b"noteai-item26-cost-containment-abort-final-state-v1\0"
RELEASE_EVIDENCE_DOMAIN = (
    b"noteai-item26-cost-containment-abort-release-evidence-v1\0"
)
MUTATION_SET_DOMAIN = b"noteai-item26-cost-containment-abort-mutation-set-v1\0"
INVENTORY_SCOPE_DOMAIN = b"noteai-item26-cost-containment-abort-inventory-scope-v1\0"
BUILDER_DISK_TUPLE_DOMAIN = b"noteai-item26-cost-containment-abort-builder-disk-v1\0"
RAM_ATTACHMENT_DOMAIN = b"noteai-item26-cost-containment-abort-ram-attachment-v1\0"

IDENTITY_KEYS = (
    "account_sha256",
    "region_sha256",
    "vpc_sha256",
    "inventory_scope_sha256",
    "builder_disk_tuple_sha256",
    "old_clone_sha256",
    "source_rds_sha256",
    "builder_sha256",
    "shared_disk_sha256",
    "vswitch_a_sha256",
    "vswitch_b_sha256",
    "ram_role_sha256",
    "ram_policy_sha256",
    "ram_attachment_sha256",
    "temporary_account_sha256",
    "control_material_set_sha256",
)

RESOURCE_SLOTS = (
    ("temporary_account", "RDS_TEMPORARY_ACCOUNT", "temporary_account_sha256"),
    ("ram_attachment", "RAM_ROLE_POLICY_ATTACHMENT", "ram_attachment_sha256"),
    ("ram_policy", "RAM_CUSTOM_POLICY", "ram_policy_sha256"),
    ("ram_role", "RAM_ROLE", "ram_role_sha256"),
    ("vswitch_a", "VSWITCH", "vswitch_a_sha256"),
    ("vswitch_b", "VSWITCH", "vswitch_b_sha256"),
    ("control_material", "ROOT_OWNED_CONTROL_MATERIAL", "control_material_set_sha256"),
)

EXPECTED_ACTIONS = (
    (
        "abort_preflight_readback",
        "READ_ONLY",
        "inventory_scope_sha256",
        "DescribeAbortPreflightProjection",
    ),
    (
        "clone_deletion_protection_disable",
        "EXACT_ONCE_MUTATION",
        "old_clone_sha256",
        "ModifyDBInstanceDeletionProtection",
    ),
    (
        "clone_protection_same_identity_readback",
        "READ_ONLY",
        "old_clone_sha256",
        "DescribeDBInstancesProtectionReadback",
    ),
    (
        "clone_delete",
        "EXACT_ONCE_MUTATION",
        "old_clone_sha256",
        "DeleteDBInstance",
    ),
    (
        "clone_absence_same_identity_readback",
        "READ_ONLY",
        "old_clone_sha256",
        "DescribeDBInstancesAbsenceReadback",
    ),
    (
        "clone_billing_terminal_readback",
        "READ_ONLY",
        "old_clone_sha256",
        "QueryInstanceBillTerminalReadback",
    ),
    (
        "temporary_account_disposition",
        "RESOURCE_DISPOSITION",
        "temporary_account_sha256",
        "DeleteAccount",
    ),
    (
        "ram_attachment_disposition",
        "RESOURCE_DISPOSITION",
        "ram_attachment_sha256",
        "DetachPolicyFromRole",
    ),
    (
        "ram_policy_disposition",
        "RESOURCE_DISPOSITION",
        "ram_policy_sha256",
        "DeletePolicy",
    ),
    (
        "ram_role_disposition",
        "RESOURCE_DISPOSITION",
        "ram_role_sha256",
        "DeleteRole",
    ),
    (
        "vswitch_a_disposition",
        "RESOURCE_DISPOSITION",
        "vswitch_a_sha256",
        "DeleteVSwitch",
    ),
    (
        "vswitch_b_disposition",
        "RESOURCE_DISPOSITION",
        "vswitch_b_sha256",
        "DeleteVSwitch",
    ),
    (
        "control_material_disposition",
        "RESOURCE_DISPOSITION",
        "control_material_set_sha256",
        "DeleteTaskControlMaterial",
    ),
    (
        "task_cleanup_readback",
        "READ_ONLY",
        "inventory_scope_sha256",
        "DescribeTaskCleanupProjection",
    ),
    (
        "shared_builder_disk_retention_readback",
        "READ_ONLY",
        "builder_disk_tuple_sha256",
        "DescribeSharedBuilderDiskRetention",
    ),
    (
        "final_baseline_readback",
        "READ_ONLY",
        "inventory_scope_sha256",
        "DescribeAbortFinalBaseline",
    ),
)

READ_ONLY_DISPOSITION_OPERATIONS = {
    "temporary_account": "DescribeAccountDisposition",
    "ram_attachment": "ListPolicyAttachmentsDisposition",
    "ram_policy": "GetPolicyDisposition",
    "ram_role": "GetRoleDisposition",
    "vswitch_a": "DescribeVSwitchDisposition",
    "vswitch_b": "DescribeVSwitchDisposition",
    "control_material": "InspectTaskControlMaterialDisposition",
}

ACTION_STATE_BOUNDARIES = {
    "abort_preflight_readback": ("UNOBSERVED", "BASELINE_ACCEPTED"),
    "clone_deletion_protection_disable": (
        "PROTECTED",
        "PROTECTION_DISABLE_SUBMITTED",
    ),
    "clone_protection_same_identity_readback": (
        "PROTECTION_DISABLE_SUBMITTED",
        "UNPROTECTED",
    ),
    "clone_delete": ("PRESENT_UNPROTECTED", "DELETE_SUBMITTED"),
    "clone_absence_same_identity_readback": (
        "DELETE_SUBMITTED",
        "ABSENT_FULL_PAGE",
    ),
    "clone_billing_terminal_readback": (
        "ABSENT_FULL_PAGE",
        "POST_RELEASE_BILLING_SNAPSHOT_RECORDED",
    ),
    "task_cleanup_readback": ("DISPOSITIONS_COMPLETE", "TASK_CLEANUP_TERMINAL"),
    "shared_builder_disk_retention_readback": (
        "BASELINE_RETAINED",
        "STOPPED_ATTACHED_UNCHANGED",
    ),
    "final_baseline_readback": (
        "TASK_CLEANUP_TERMINAL",
        "FINAL_BASELINE_ACCEPTED",
    ),
}

ALLOWED_MUTATIONS = [
    "ModifyDBInstanceDeletionProtection",
    "DeleteDBInstance",
    "DeleteAccount",
    "DetachPolicyFromRole",
    "DeletePolicy",
    "DeleteRole",
    "DeleteVSwitch",
    "DeleteTaskControlMaterial",
]

READINESS_25_TO_25 = {
    "internal_verified_before": 25,
    "internal_verified_after": 25,
    "internal_total": 29,
    "internal_percentage_after": 86,
    "complete_public_verified_before": 25,
    "complete_public_verified_after": 25,
    "complete_public_total": 38,
    "complete_public_percentage_after": 66,
    "item26_status_before": "unverified",
    "item26_status_after": "unverified",
    "manifest_status_unchanged": True,
    "readiness_credit_added": False,
    "future_successor_requires_new_fee_authorization": True,
}

ACTION_KEYS = {
    "sequence",
    "name",
    "mode",
    "operation",
    "target_sha256",
    "request_body_sha256",
    "request_set_sha256",
    "response_set_sha256",
    "provider_request_id_set_sha256",
    "observation_set_sha256",
    "client_token_used",
    "client_token_sha256",
    "started_at_utc",
    "completed_at_utc",
    "read_request_count",
    "mutation_submit_count",
    "same_identity_readback_count",
    "automatic_retry_count",
    "manual_resend_count",
    "parameter_change_count",
    "replacement_target_count",
    "submission_outcome",
    "provider_state_before",
    "provider_state_after",
    "terminal_outcome",
}

DISPOSITION_KEYS = {
    "slot",
    "resource_kind",
    "identity_sha256",
    "ownership_outcome",
    "ownership_evidence",
    "dependency_count_before",
    "dependency_count_after",
    "attachment_count_before",
    "attachment_count_after",
    "mutation_count",
    "final_state",
    "final_readback_sha256",
}

OWNERSHIP_EVIDENCE_KEYS = {
    "schema",
    "resource_kind",
    "identity_sha256",
    "parent_identity_sha256",
    "related_identity_sha256",
    "lineage_method",
    "create_receipt_sha256",
    "before_inventory_sha256",
    "task_marker_sha256",
    "topology_tuple_sha256",
    "all_pages_complete",
    "task_owned_proven",
    "shared_proven",
    "absent_proven",
}

BILLING_OBSERVATION_KEYS = {
    "observed_at_utc",
    "resource_sha256",
    "gross_cny",
    "service_seconds",
    "billed_through_at_utc",
    "settlement_watermark_at_utc",
    "open_meter_row_count",
    "full_page_complete",
    "raw_observation_sha256",
}


def _hex64(value: Any) -> bool:
    return type(value) is str and HEX64.fullmatch(value) is not None


def _nonnegative(value: Any) -> bool:
    return type(value) is int and value >= 0


def _strict(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _strict(left, right) for left, right in zip(value, expected)
        )
    return value == expected


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


def _domain_sha256(domain: bytes, value: Any) -> str:
    return hashlib.sha256(domain + _canonical(value)).hexdigest()


def _utc(value: Any) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        return None
    return parsed


def _decimal(value: Any) -> Decimal | None:
    if type(value) is not str or DECIMAL_CNY.fullmatch(value) is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def inventory_scope_sha256(identities: dict[str, Any]) -> str:
    return _domain_sha256(
        INVENTORY_SCOPE_DOMAIN,
        {
            "account_sha256": identities.get("account_sha256"),
            "region_sha256": identities.get("region_sha256"),
            "vpc_sha256": identities.get("vpc_sha256"),
        },
    )


def builder_disk_tuple_sha256(identities: dict[str, Any]) -> str:
    return _domain_sha256(
        BUILDER_DISK_TUPLE_DOMAIN,
        {
            "builder_sha256": identities.get("builder_sha256"),
            "shared_disk_sha256": identities.get("shared_disk_sha256"),
            "disk_size_gib": 120,
            "disk_charge_type": "PostPaid",
            "builder_status": "Stopped",
            "builder_stop_charging_mode": "StopCharging",
            "disk_attached_to_builder": True,
        },
    )


def ram_attachment_sha256(identities: dict[str, Any]) -> str:
    return _domain_sha256(
        RAM_ATTACHMENT_DOMAIN,
        {
            "ram_role_sha256": identities.get("ram_role_sha256"),
            "ram_policy_sha256": identities.get("ram_policy_sha256"),
        },
    )


def preflight_projection_sha256(preflight: dict[str, Any]) -> str:
    projection = dict(preflight)
    projection.pop("raw_projection_sha256", None)
    return _domain_sha256(PREFLIGHT_DOMAIN, projection)


def _planned_action_projection(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "sequence",
        "name",
        "mode",
        "operation",
        "target_sha256",
        "request_body_sha256",
        "client_token_used",
        "client_token_sha256",
        "mutation_submit_count",
    )
    return [{key: row.get(key) for key in keys} for row in actions]


def _planned_disposition_projection(
    dispositions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    keys = (
        "slot",
        "resource_kind",
        "identity_sha256",
        "ownership_outcome",
        "ownership_evidence",
        "dependency_count_before",
        "attachment_count_before",
        "mutation_count",
    )
    return [{key: row.get(key) for key in keys} for row in dispositions]


def abort_plan_sha256(
    identities: dict[str, Any],
    preflight: dict[str, Any],
    actions: list[dict[str, Any]],
    dispositions: list[dict[str, Any]],
    authorization: dict[str, Any],
) -> str:
    return _domain_sha256(
        PLAN_DOMAIN,
        {
            "schema": "noteai.item26.cost-containment-abort-plan.v1",
            "task_id": TASK_ID,
            "operation_id": OPERATION_ID,
            "identity_ledger": identities,
            "preflight_sha256": preflight_projection_sha256(preflight),
            "allowed_mutations": authorization.get("allowed_mutations"),
            "destructive_clone_target_count": authorization.get(
                "destructive_clone_target_count"
            ),
            "new_paid_resource_allowed": authorization.get(
                "new_paid_resource_allowed"
            ),
            "release_billing_contract": {
                "ref": RELEASE_BILLING_CONTRACT_REF,
                "sha256": EXPECTED_RELEASE_BILLING_CONTRACT_SHA256,
            },
            "confirmation_nonce_sha256": authorization.get(
                "confirmation_nonce_sha256"
            ),
            "protection_disable_client_token_sha256": authorization.get(
                "protection_disable_client_token_sha256"
            ),
            "ordered_actions": _planned_action_projection(actions),
            "resource_dispositions": _planned_disposition_projection(
                dispositions
            ),
        },
    )


def provider_request_set_sha256(actions: list[dict[str, Any]]) -> str:
    keys = (
        "sequence",
        "name",
        "operation",
        "target_sha256",
        "request_body_sha256",
        "request_set_sha256",
        "provider_request_id_set_sha256",
        "client_token_sha256",
        "mutation_submit_count",
        "read_request_count",
    )
    return _domain_sha256(
        REQUEST_SET_DOMAIN,
        [{key: row.get(key) for key in keys} for row in actions],
    )


def provider_response_set_sha256(actions: list[dict[str, Any]]) -> str:
    keys = (
        "sequence",
        "name",
        "response_set_sha256",
        "observation_set_sha256",
        "submission_outcome",
        "provider_state_before",
        "provider_state_after",
        "terminal_outcome",
    )
    return _domain_sha256(
        RESPONSE_SET_DOMAIN,
        [{key: row.get(key) for key in keys} for row in actions],
    )


def response_projection_sha256(actions: list[dict[str, Any]]) -> str:
    keys = (
        "sequence",
        "name",
        "target_sha256",
        "same_identity_readback_count",
        "submission_outcome",
        "provider_state_before",
        "provider_state_after",
        "terminal_outcome",
    )
    return _domain_sha256(
        RESPONSE_PROJECTION_DOMAIN,
        [{key: row.get(key) for key in keys} for row in actions],
    )


def page_inventory_sha256(actions: list[dict[str, Any]]) -> str:
    rows = [
        {
            "sequence": row.get("sequence"),
            "name": row.get("name"),
            "target_sha256": row.get("target_sha256"),
            "observation_set_sha256": row.get("observation_set_sha256"),
            "read_request_count": row.get("read_request_count"),
            "same_identity_readback_count": row.get(
                "same_identity_readback_count"
            ),
        }
        for row in actions
        if row.get("read_request_count", 0) > 0
    ]
    return _domain_sha256(PAGE_INVENTORY_DOMAIN, rows)


def billing_observation_set_sha256(billing: dict[str, Any]) -> str:
    return _domain_sha256(BILLING_SET_DOMAIN, billing.get("observations"))


def release_evidence_projection_sha256(
    billing: dict[str, Any],
    actions: list[dict[str, Any]],
    final_state: dict[str, Any],
    execution_boundary: dict[str, Any],
) -> str:
    delete = actions[3] if len(actions) > 3 else {}
    absence = actions[4] if len(actions) > 4 else {}
    return _domain_sha256(
        RELEASE_EVIDENCE_DOMAIN,
        {
            "schema": "noteai.item26.rds-release-evidence-projection.v1",
            "release_billing_contract_ref": billing.get(
                "release_billing_contract_ref"
            ),
            "release_billing_contract_sha256": billing.get(
                "release_billing_contract_sha256"
            ),
            "delete": {
                key: delete.get(key)
                for key in (
                    "sequence",
                    "name",
                    "operation",
                    "target_sha256",
                    "request_body_sha256",
                    "request_set_sha256",
                    "response_set_sha256",
                    "provider_request_id_set_sha256",
                    "mutation_submit_count",
                    "submission_outcome",
                    "completed_at_utc",
                )
            },
            "absence": {
                key: absence.get(key)
                for key in (
                    "sequence",
                    "name",
                    "operation",
                    "target_sha256",
                    "request_set_sha256",
                    "response_set_sha256",
                    "observation_set_sha256",
                    "provider_request_id_set_sha256",
                    "read_request_count",
                    "same_identity_readback_count",
                    "provider_state_after",
                    "terminal_outcome",
                    "completed_at_utc",
                )
            },
            "source": {
                "source_rds_sha256": final_state.get("source_rds_sha256"),
                "source_running_prepaid_unchanged": final_state.get(
                    "source_running_prepaid_unchanged"
                ),
                "source_readback_sha256": final_state.get(
                    "source_readback_sha256"
                ),
            },
            "new_paid_resource_count": execution_boundary.get(
                "new_paid_resource_count"
            ),
        },
    )


def resource_disposition_set_sha256(dispositions: list[dict[str, Any]]) -> str:
    return _domain_sha256(DISPOSITION_SET_DOMAIN, dispositions)


def final_state_sha256(final_state: dict[str, Any]) -> str:
    return _domain_sha256(FINAL_STATE_DOMAIN, final_state)


def abort_mutation_identity_set_sha256(actions: list[dict[str, Any]]) -> str:
    keys = (
        "sequence",
        "name",
        "operation",
        "target_sha256",
        "request_body_sha256",
        "request_set_sha256",
        "provider_request_id_set_sha256",
        "client_token_sha256",
        "submission_outcome",
    )
    rows = [
        {key: row.get(key) for key in keys}
        for row in actions
        if row.get("mutation_submit_count") == 1
    ]
    return _domain_sha256(MUTATION_SET_DOMAIN, rows)


def _validate_authorization(value: Any, preflight: Any) -> list[str]:
    errors: list[str] = []
    keys = {
        "action",
        "approval_kind",
        "approval_statement_sha256",
        "confirmation_envelope_sha256",
        "plan_sha256",
        "preflight_sha256",
        "confirmation_nonce_sha256",
        "protection_disable_client_token_sha256",
        "approved_at_utc",
        "expires_at_utc",
        "allowed_mutations",
        "destructive_clone_target_count",
        "new_paid_resource_allowed",
    }
    if type(value) is not dict or set(value) != keys:
        return ["abort authorization schema mismatch"]
    if (
        value["action"] != "COST_CONTAINMENT_ABORT"
        or value["approval_kind"] != "USER_ACTION_TIME_CONFIRMATION"
        or any(
            not _hex64(value[key])
            for key in (
                "approval_statement_sha256",
                "confirmation_envelope_sha256",
                "plan_sha256",
                "preflight_sha256",
                "confirmation_nonce_sha256",
                "protection_disable_client_token_sha256",
            )
        )
        or type(value["allowed_mutations"]) is not list
        or not value["allowed_mutations"]
        or len(value["allowed_mutations"]) != len(set(value["allowed_mutations"]))
        or any(operation not in ALLOWED_MUTATIONS for operation in value["allowed_mutations"])
        or type(preflight) is not dict
        or value["preflight_sha256"] != preflight_projection_sha256(preflight)
        or type(value["destructive_clone_target_count"]) is not int
        or value["destructive_clone_target_count"] != 1
        or value["new_paid_resource_allowed"] is not False
    ):
        errors.append("abort authorization boundary mismatch")
    approved = _utc(value["approved_at_utc"])
    expires = _utc(value["expires_at_utc"])
    observed = _utc(preflight.get("observed_at_utc")) if type(preflight) is dict else None
    if (
        approved is None
        or expires is None
        or observed is None
        or not observed <= approved < expires
        or approved - observed > MAX_PREFLIGHT_AGE
        or expires - approved > MAX_CONFIRMATION_TTL
    ):
        errors.append("abort authorization time boundary mismatch")
    return errors


def _validate_preflight(value: Any, identities: Any) -> list[str]:
    keys = {
        "observed_at_utc",
        "raw_projection_sha256",
        "all_pages_complete",
        "exact_clone_count",
        "clone_identity_sha256",
        "clone_status",
        "clone_charge_type",
        "clone_postgresql_major_version",
        "clone_deletion_protection",
        "clone_capture_status",
        "clone_reconciliation_status",
        "clone_terminal_acceptance",
        "source_identity_sha256",
        "source_status",
        "source_charge_type",
        "builder_identity_sha256",
        "builder_status",
        "builder_stop_charging_mode",
        "shared_disk_identity_sha256",
        "shared_disk_size_gib",
        "shared_disk_charge_type",
        "shared_disk_attached_to_builder",
        "cost_ceiling_breached",
        "billing_observed_at_utc",
        "billing_cycle",
        "billing_resource_sha256",
        "billing_pretax_gross_cny",
        "billing_service_seconds",
        "billing_readback_sha256",
        "recorded_baseline_pretax_gross_cny",
        "recorded_baseline_service_seconds",
    }
    if type(value) is not dict or set(value) != keys:
        return ["abort preflight schema mismatch"]
    if (
        _utc(value["observed_at_utc"]) is None
        or value["raw_projection_sha256"] != preflight_projection_sha256(value)
        or value["all_pages_complete"] is not True
        or type(value["exact_clone_count"]) is not int
        or value["exact_clone_count"] != 1
        or value["clone_identity_sha256"] != identities.get("old_clone_sha256")
        or value["clone_status"] != "Running"
        or value["clone_charge_type"] != "Postpaid"
        or type(value["clone_postgresql_major_version"]) is not int
        or value["clone_postgresql_major_version"] != 16
        or value["clone_deletion_protection"] is not True
        or value["clone_capture_status"] != "NOT_STARTED"
        or value["clone_reconciliation_status"] != "PENDING"
        or value["clone_terminal_acceptance"] is not False
        or value["source_identity_sha256"] != identities.get("source_rds_sha256")
        or value["source_status"] != "Running"
        or value["source_charge_type"] != "Prepaid"
        or value["builder_identity_sha256"] != identities.get("builder_sha256")
        or value["builder_status"] != "Stopped"
        or value["builder_stop_charging_mode"] != "StopCharging"
        or value["shared_disk_identity_sha256"] != identities.get("shared_disk_sha256")
        or type(value["shared_disk_size_gib"]) is not int
        or value["shared_disk_size_gib"] != 120
        or value["shared_disk_charge_type"] != "PostPaid"
        or value["shared_disk_attached_to_builder"] is not True
        or value["cost_ceiling_breached"] is not True
        or value["billing_observed_at_utc"] != value["observed_at_utc"]
        or value["billing_cycle"] != KNOWN_BILLING_CYCLE
        or value["billing_resource_sha256"]
        != identities.get("old_clone_sha256")
        or _decimal(value["billing_pretax_gross_cny"]) is None
        or _decimal(value["billing_pretax_gross_cny"])
        < Decimal(KNOWN_PRE_ABORT_GROSS_CNY)
        or type(value["billing_service_seconds"]) is not int
        or value["billing_service_seconds"]
        < KNOWN_PRE_ABORT_SERVICE_SECONDS
        or not _hex64(value["billing_readback_sha256"])
        or value["recorded_baseline_pretax_gross_cny"]
        != KNOWN_PRE_ABORT_GROSS_CNY
        or type(value["recorded_baseline_service_seconds"]) is not int
        or value["recorded_baseline_service_seconds"]
        != KNOWN_PRE_ABORT_SERVICE_SECONDS
    ):
        return ["abort preflight state mismatch"]
    return []


def _validate_dispositions(value: Any, identities: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    errors: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    if type(value) is not list or len(value) != len(RESOURCE_SLOTS):
        return ["abort resource disposition count mismatch"], rows
    for candidate, (slot, kind, identity_key) in zip(value, RESOURCE_SLOTS):
        if type(candidate) is not dict or set(candidate) != DISPOSITION_KEYS:
            errors.append("abort resource disposition schema mismatch")
            continue
        row = candidate
        rows[slot] = row
        counts = (
            row["dependency_count_before"],
            row["dependency_count_after"],
            row["attachment_count_before"],
            row["attachment_count_after"],
            row["mutation_count"],
        )
        ownership = row["ownership_evidence"]
        related = {
            "temporary_account": (
                identities["source_rds_sha256"],
                identities["inventory_scope_sha256"],
            ),
            "ram_attachment": (
                identities["ram_role_sha256"],
                identities["ram_policy_sha256"],
            ),
            "ram_policy": (
                identities["account_sha256"],
                identities["ram_role_sha256"],
            ),
            "ram_role": (
                identities["account_sha256"],
                identities["ram_policy_sha256"],
            ),
            "vswitch_a": (
                identities["vpc_sha256"],
                identities["region_sha256"],
            ),
            "vswitch_b": (
                identities["vpc_sha256"],
                identities["region_sha256"],
            ),
            "control_material": (
                identities["inventory_scope_sha256"],
                identities["builder_sha256"],
            ),
        }[slot]
        if (
            row["slot"] != slot
            or row["resource_kind"] != kind
            or row["identity_sha256"] != identities[identity_key]
            or not _hex64(row["final_readback_sha256"])
            or any(not _nonnegative(item) for item in counts)
            or type(ownership) is not dict
            or set(ownership) != OWNERSHIP_EVIDENCE_KEYS
            or ownership["schema"]
            != "noteai.item26.cost-containment-abort-ownership.v1"
            or ownership["resource_kind"] != kind
            or ownership["identity_sha256"] != identities[identity_key]
            or ownership["parent_identity_sha256"] != related[0]
            or ownership["related_identity_sha256"] != related[1]
            or ownership["lineage_method"]
            not in {
                "CREATE_RECEIPT_AND_FULL_INVENTORY",
                "BEFORE_AFTER_FULL_INVENTORY",
                "ROOT_OWNED_HASH_INVENTORY",
            }
            or any(
                not _hex64(ownership[key])
                for key in (
                    "create_receipt_sha256",
                    "before_inventory_sha256",
                    "task_marker_sha256",
                    "topology_tuple_sha256",
                )
            )
            or ownership["all_pages_complete"] is not True
        ):
            errors.append("abort resource disposition identity/count mismatch")
            continue
        outcome = row["ownership_outcome"]
        if outcome == "TASK_OWNED":
            if (
                ownership["task_owned_proven"] is not True
                or ownership["shared_proven"] is not False
                or ownership["absent_proven"] is not False
                or row["mutation_count"] != 1
                or row["final_state"] != "ABSENT"
                or row["dependency_count_after"] != 0
                or row["attachment_count_after"] != 0
            ):
                errors.append("abort task-owned resource cleanup mismatch")
        elif outcome == "PROVEN_SHARED":
            if (
                ownership["task_owned_proven"] is not False
                or ownership["shared_proven"] is not True
                or ownership["absent_proven"] is not False
                or row["mutation_count"] != 0
                or row["final_state"] != "RETAINED_SHARED"
                or row["dependency_count_after"]
                != row["dependency_count_before"]
                or row["attachment_count_after"]
                != row["attachment_count_before"]
            ):
                errors.append("abort shared resource retention mismatch")
        elif outcome == "PROVEN_ABSENT":
            if (
                ownership["task_owned_proven"] is not False
                or ownership["shared_proven"] is not False
                or ownership["absent_proven"] is not True
                or row["mutation_count"] != 0
                or row["final_state"] != "ABSENT"
                or any(counts[index] != 0 for index in range(4))
            ):
                errors.append("abort absent resource disposition mismatch")
        else:
            errors.append("abort resource ownership is not terminal")
        if (
            slot in {"vswitch_a", "vswitch_b"}
            and outcome == "TASK_OWNED"
            and row["dependency_count_before"] != 0
        ):
            errors.append("abort vSwitch dependency boundary mismatch")
        if slot == "ram_attachment" and outcome == "TASK_OWNED" and (
            row["attachment_count_before"] != 1
        ):
            errors.append("abort RAM attachment lineage mismatch")
        if slot == "temporary_account" and outcome == "TASK_OWNED" and (
            row["dependency_count_before"] != 1
        ):
            errors.append("abort temporary account parent lineage mismatch")
        if slot in {"ram_policy", "ram_role"} and outcome == "TASK_OWNED" and (
            row["attachment_count_before"] != 0
        ):
            errors.append("abort RAM delete attachment boundary mismatch")
    ownership_hashes = [
        _domain_sha256(SEMANTIC_DOMAIN, row["ownership_evidence"])
        for row in rows.values()
        if type(row.get("ownership_evidence")) is dict
    ]
    if len(ownership_hashes) != len(set(ownership_hashes)):
        errors.append("abort ownership authorities are not resource-distinct")
    for key in (
        "create_receipt_sha256",
        "before_inventory_sha256",
        "task_marker_sha256",
        "topology_tuple_sha256",
    ):
        commitments = [
            row["ownership_evidence"][key]
            for row in rows.values()
            if type(row.get("ownership_evidence")) is dict
            and key in row["ownership_evidence"]
        ]
        if len(commitments) != len(set(commitments)):
            errors.append("abort ownership " + key + " commitments are not distinct")
    return errors, rows


def _validate_actions(
    value: Any,
    identities: dict[str, Any],
    authorization: dict[str, Any],
    preflight: dict[str, Any],
    dispositions: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if type(value) is not list or len(value) != len(EXPECTED_ACTIONS):
        return ["abort ordered action count mismatch"]
    previous_end = _utc(preflight["observed_at_utc"])
    approved = _utc(authorization["approved_at_utc"])
    expires = _utc(authorization["expires_at_utc"])
    disposition_by_action = {
        slot + "_disposition": dispositions.get(slot)
        for slot, _kind, _identity_key in RESOURCE_SLOTS
    }
    request_body_digests: list[str] = []
    request_set_digests: list[str] = []
    response_set_digests: list[str] = []
    observation_set_digests: list[str] = []
    provider_request_id_set_digests: list[str] = []
    for sequence, (candidate, spec) in enumerate(zip(value, EXPECTED_ACTIONS), start=1):
        name, mode, identity_key, operation = spec
        if type(candidate) is not dict or set(candidate) != ACTION_KEYS:
            errors.append("abort ordered action schema mismatch")
            continue
        row = candidate
        started = _utc(row["started_at_utc"])
        completed = _utc(row["completed_at_utc"])
        if (
            type(row["sequence"]) is not int
            or row["sequence"] != sequence
            or row["name"] != name
            or row["target_sha256"] != identities[identity_key]
            or any(
                not _hex64(row[key])
                for key in (
                    "request_body_sha256",
                    "request_set_sha256",
                    "response_set_sha256",
                    "provider_request_id_set_sha256",
                    "observation_set_sha256",
                    "client_token_sha256",
                )
            )
            or started is None
            or completed is None
            or previous_end is None
            or not previous_end <= started <= completed
            or any(
                not _nonnegative(row[key])
                for key in (
                    "read_request_count",
                    "mutation_submit_count",
                    "same_identity_readback_count",
                    "automatic_retry_count",
                    "manual_resend_count",
                    "parameter_change_count",
                    "replacement_target_count",
                )
            )
            or row["automatic_retry_count"] != 0
            or row["manual_resend_count"] != 0
            or row["parameter_change_count"] != 0
            or row["replacement_target_count"] != 0
        ):
            errors.append("abort ordered action identity/order mismatch")
            if completed is not None:
                previous_end = completed
            continue
        previous_end = completed
        request_body_digests.append(row["request_body_sha256"])
        request_set_digests.append(row["request_set_sha256"])
        response_set_digests.append(row["response_set_sha256"])
        observation_set_digests.append(row["observation_set_sha256"])
        provider_request_id_set_digests.append(
            row["provider_request_id_set_sha256"]
        )
        expected_states = ACTION_STATE_BOUNDARIES.get(name)
        if expected_states is not None and (
            row["provider_state_before"] != expected_states[0]
            or row["provider_state_after"] != expected_states[1]
        ):
            errors.append("abort provider state transition mismatch")
        if mode == "EXACT_ONCE_MUTATION":
            expected_client_token_used = (
                name == "clone_deletion_protection_disable"
            )
            if (
                row["mode"] != mode
                or row["operation"] != operation
                or row["mutation_submit_count"] != 1
                or row["read_request_count"] != 0
                or row["same_identity_readback_count"] != 0
                or row["terminal_outcome"] != "SUBMITTED_ONCE_NO_REPLAY"
                or row["submission_outcome"] != "ACCEPTED"
                or row["client_token_used"] is not expected_client_token_used
                or row["operation"] not in authorization["allowed_mutations"]
                or (
                    expected_client_token_used
                    and row["client_token_sha256"]
                    != authorization["protection_disable_client_token_sha256"]
                )
                or (
                    not expected_client_token_used
                    and row["client_token_sha256"] != EMPTY_SHA256
                )
                or approved is None
                or expires is None
                or not approved <= started < expires
            ):
                errors.append("abort exact-once mutation boundary mismatch")
        elif mode == "READ_ONLY":
            if (
                row["mode"] != mode
                or row["operation"] != operation
                or row["mutation_submit_count"] != 0
                or row["read_request_count"] < 1
                or row["client_token_used"] is not False
                or row["client_token_sha256"] != EMPTY_SHA256
                or row["submission_outcome"] != "NOT_APPLICABLE"
                or row["terminal_outcome"] != "PASS"
            ):
                errors.append("abort read-only action boundary mismatch")
            if name in {
                "clone_protection_same_identity_readback",
                "clone_absence_same_identity_readback",
                "clone_billing_terminal_readback",
            } and row["same_identity_readback_count"] < 1:
                errors.append("abort same-identity readback missing")
        else:
            disposition = disposition_by_action.get(name)
            if disposition is None:
                errors.append("abort disposition action missing authority")
                continue
            outcome = disposition["ownership_outcome"]
            expected_mode = {
                "TASK_OWNED": "DELETE_TASK_OWNED",
                "PROVEN_SHARED": "RETAIN_PROVEN_SHARED",
                "PROVEN_ABSENT": "RETAIN_PROVEN_ABSENT",
            }.get(outcome)
            expected_terminal = {
                "TASK_OWNED": "ABSENT",
                "PROVEN_SHARED": "RETAINED_SHARED",
                "PROVEN_ABSENT": "ABSENT",
            }.get(outcome)
            expected_operation = (
                operation
                if outcome == "TASK_OWNED"
                else READ_ONLY_DISPOSITION_OPERATIONS[name.removesuffix("_disposition")]
            )
            expected_submission = (
                {"ACCEPTED"}
                if outcome == "TASK_OWNED"
                else {"NOT_APPLICABLE"}
            )
            expected_state_before = {
                "TASK_OWNED": "TASK_OWNED_PRESENT",
                "PROVEN_SHARED": "PROVEN_SHARED_PRESENT",
                "PROVEN_ABSENT": "PROVEN_ABSENT",
            }.get(outcome)
            expected_state_after = {
                "TASK_OWNED": "ABSENT_SAME_IDENTITY",
                "PROVEN_SHARED": "RETAINED_SHARED_UNCHANGED",
                "PROVEN_ABSENT": "ABSENT_UNCHANGED",
            }.get(outcome)
            if (
                row["mode"] != expected_mode
                or row["operation"] != expected_operation
                or row["mutation_submit_count"] != disposition["mutation_count"]
                or row["read_request_count"] < 1
                or row["same_identity_readback_count"] < 1
                or row["terminal_outcome"] != expected_terminal
                or row["submission_outcome"] not in expected_submission
                or row["provider_state_before"] != expected_state_before
                or row["provider_state_after"] != expected_state_after
                or row["client_token_used"] is not False
                or row["client_token_sha256"] != EMPTY_SHA256
                or (
                    disposition["mutation_count"] == 1
                    and (
                        approved is None
                        or expires is None
                        or not approved <= started < expires
                    )
                )
            ):
                errors.append("abort disposition action mismatch")
    for label, digests in (
        ("request body", request_body_digests),
        ("request set", request_set_digests),
        ("response set", response_set_digests),
        ("observation set", observation_set_digests),
        ("provider request ID set", provider_request_id_set_digests),
    ):
        if len(digests) != len(set(digests)):
            errors.append("abort action " + label + " commitments are not distinct")
    return errors


def _validate_billing(
    value: Any,
    identities: dict[str, Any],
    actions: list[dict[str, Any]],
    preflight: dict[str, Any],
) -> list[str]:
    keys = {
        "resource_sha256",
        "release_billing_contract_ref",
        "release_billing_contract_sha256",
        "currency",
        "billing_cycle",
        "approved_24h_ceiling_cny",
        "pre_abort_gross_cny",
        "pre_abort_service_seconds",
        "final_gross_cny",
        "final_service_seconds",
        "incremental_after_preflight_cny",
        "deletion_accepted_at_utc",
        "first_absent_at_utc",
        "final_observed_at_utc",
        "billed_through_at_utc",
        "closure_method",
        "release_contract_outcome",
        "stable_readback_count",
        "open_meter_row_count",
        "metering_closed",
        "historical_charge_retained",
        "observations",
    }
    if type(value) is not dict or set(value) != keys:
        return ["abort billing closure schema mismatch"]
    ceiling = _decimal(value["approved_24h_ceiling_cny"])
    before = _decimal(value["pre_abort_gross_cny"])
    final = _decimal(value["final_gross_cny"])
    incremental = _decimal(value["incremental_after_preflight_cny"])
    deleted = _utc(value["deletion_accepted_at_utc"])
    absent = _utc(value["first_absent_at_utc"])
    observed = _utc(value["final_observed_at_utc"])
    billed = _utc(value["billed_through_at_utc"])
    method = value["closure_method"]
    errors: list[str] = []
    if (
        value["resource_sha256"] != identities["old_clone_sha256"]
        or value["release_billing_contract_ref"]
        != RELEASE_BILLING_CONTRACT_REF
        or value["release_billing_contract_sha256"]
        != EXPECTED_RELEASE_BILLING_CONTRACT_SHA256
        or value["currency"] != "CNY"
        or value["billing_cycle"] != KNOWN_BILLING_CYCLE
        or value["approved_24h_ceiling_cny"] != KNOWN_24H_CEILING_CNY
        or value["billing_cycle"] != preflight.get("billing_cycle")
        or value["resource_sha256"]
        != preflight.get("billing_resource_sha256")
        or value["pre_abort_gross_cny"]
        != preflight.get("billing_pretax_gross_cny")
        or value["pre_abort_service_seconds"]
        != preflight.get("billing_service_seconds")
        or ceiling != Decimal(KNOWN_24H_CEILING_CNY)
        or before is None
        or before < Decimal(KNOWN_PRE_ABORT_GROSS_CNY)
        or final is None
        or incremental is None
        or not before > ceiling
        or final < before
        or incremental != final - before
        or not _nonnegative(value["pre_abort_service_seconds"])
        or value["pre_abort_service_seconds"]
        < KNOWN_PRE_ABORT_SERVICE_SECONDS
        or not _nonnegative(value["final_service_seconds"])
        or value["final_service_seconds"] < value["pre_abort_service_seconds"]
        or deleted is None
        or absent is None
        or observed is None
        or billed is None
        or not deleted <= absent <= observed
        or billed > observed
        or not _nonnegative(value["stable_readback_count"])
        or not _nonnegative(value["open_meter_row_count"])
        or value["open_meter_row_count"] != 0
        or value["metering_closed"] is not True
        or value["historical_charge_retained"] is not True
    ):
        errors.append("abort billing closure mismatch")
    observations = value["observations"]
    if type(observations) is not list or not observations:
        return [*errors, "abort billing observation vector missing"]
    parsed_observations: list[
        tuple[datetime, Decimal, int, datetime, datetime, str]
    ] = []
    for row in observations:
        if type(row) is not dict or set(row) != BILLING_OBSERVATION_KEYS:
            errors.append("abort billing observation schema mismatch")
            continue
        row_observed = _utc(row["observed_at_utc"])
        row_gross = _decimal(row["gross_cny"])
        row_billed = _utc(row["billed_through_at_utc"])
        row_watermark = _utc(row["settlement_watermark_at_utc"])
        if (
            row["resource_sha256"] != identities["old_clone_sha256"]
            or row_observed is None
            or row_gross is None
            or not _nonnegative(row["service_seconds"])
            or row_billed is None
            or row_watermark is None
            or not row_billed <= row_watermark <= row_observed
            or not _nonnegative(row["open_meter_row_count"])
            or row["full_page_complete"] is not True
            or not _hex64(row["raw_observation_sha256"])
        ):
            errors.append("abort billing observation mismatch")
            continue
        parsed_observations.append(
            (
                row_observed,
                row_gross,
                row["service_seconds"],
                row_billed,
                row_watermark,
                row["raw_observation_sha256"],
            )
        )
    if len(parsed_observations) != len(observations):
        return errors
    if any(
        parsed_observations[index - 1][0] >= parsed_observations[index][0]
        for index in range(1, len(parsed_observations))
    ) or len({row[5] for row in parsed_observations}) != len(parsed_observations):
        errors.append("abort billing observations are not distinct and ordered")
    last = parsed_observations[-1]
    if (
        observed != last[0]
        or final != last[1]
        or value["final_service_seconds"] != last[2]
        or billed != last[3]
        or value["open_meter_row_count"]
        != observations[-1]["open_meter_row_count"]
    ):
        errors.append("abort billing final projection mismatch")
    if (
        type(actions) is not list
        or len(actions) != len(EXPECTED_ACTIONS)
        or any(type(row) is not dict for row in actions)
    ):
        errors.append("abort billing action timeline missing")
    else:
        delete_completed = _utc(actions[3].get("completed_at_utc"))
        absence_completed = _utc(actions[4].get("completed_at_utc"))
        billing_started = _utc(actions[5].get("started_at_utc"))
        billing_completed = _utc(actions[5].get("completed_at_utc"))
        if (
            deleted != delete_completed
            or absent != absence_completed
            or billing_started is None
            or billing_completed is None
            or not billing_started <= parsed_observations[0][0]
            or parsed_observations[-1][0] != billing_completed
            or absent is None
            or parsed_observations[0][0] < absent
        ):
            errors.append("abort billing/action timeline mismatch")
    if method == "OFFICIAL_RELEASE_CONTRACT_PLUS_EXACT_ABSENCE":
        if (
            len(parsed_observations) != 1
            or value["stable_readback_count"] != 1
            or value["release_contract_outcome"]
            != "DELETE_ACCEPTED_EXACT_ID_ABSENT_CONTRACT_APPLIED"
        ):
            errors.append("abort official release billing proof missing")
    elif method == "SETTLEMENT_WATERMARK_STABLE_TWO_READS":
        stable_projection = [row[1:4] for row in parsed_observations]
        if (
            len(parsed_observations) != 2
            or value["stable_readback_count"] != 2
            or value["release_contract_outcome"] != "NOT_APPLICABLE"
            or stable_projection[0] != stable_projection[1]
            or any(row["open_meter_row_count"] != 0 for row in observations)
        ):
            errors.append("abort settlement billing proof mismatch")
        errors.append("abort settlement-only closure is not finalized in v1")
    else:
        errors.append("abort billing closure method is not terminal")
    return errors


def _validate_final_state(value: Any, identities: dict[str, Any]) -> list[str]:
    expected = {
        "old_clone_sha256": identities["old_clone_sha256"],
        "old_clone_absent": True,
        "source_rds_sha256": identities["source_rds_sha256"],
        "source_running_prepaid_unchanged": True,
        "source_readback_sha256": value.get("source_readback_sha256")
        if type(value) is dict
        else None,
        "builder_sha256": identities["builder_sha256"],
        "builder_stopped_stop_charging": True,
        "builder_deleted": False,
        "builder_readback_sha256": value.get("builder_readback_sha256")
        if type(value) is dict
        else None,
        "shared_disk_sha256": identities["shared_disk_sha256"],
        "shared_disk_retained_attached_120gib_postpaid": True,
        "shared_disk_readback_sha256": value.get("shared_disk_readback_sha256")
        if type(value) is dict
        else None,
        "builder_disk_tuple_sha256": identities["builder_disk_tuple_sha256"],
        "item26_builder_cost_attribution_proven": False,
        "task_owned_cleanup_terminal": True,
        "unresolved_ownership_count": 0,
    }
    if not _strict(value, expected):
        return ["abort final runtime state mismatch"]
    if any(
        not _hex64(value[key])
        for key in (
            "source_readback_sha256",
            "builder_readback_sha256",
            "shared_disk_readback_sha256",
        )
    ) or len(
        {
            value["source_readback_sha256"],
            value["builder_readback_sha256"],
            value["shared_disk_readback_sha256"],
        }
    ) != 3:
        return ["abort final runtime readback binding mismatch"]
    return []


def _validate_raw_closure(
    value: Any,
    authorization: dict[str, Any],
    preflight: dict[str, Any],
    actions: list[dict[str, Any]],
    billing: dict[str, Any],
    dispositions: list[dict[str, Any]],
    final_state: dict[str, Any],
    execution_boundary: dict[str, Any],
) -> list[str]:
    keys = {
        "schema",
        "root_owned_raw_file_sha256",
        "root_owned_raw_semantic_sha256",
        "plan_sha256",
        "preflight_sha256",
        "confirmation_envelope_sha256",
        "provider_request_set_sha256",
        "provider_response_set_sha256",
        "response_projection_sha256",
        "page_inventory_sha256",
        "billing_observation_set_sha256",
        "release_evidence_projection_sha256",
        "resource_disposition_set_sha256",
        "final_state_sha256",
        "raw_record_count",
        "full_page_readback_count",
        "raw_provider_payload_retained_in_repository",
        "secret_value_emitted_count",
    }
    if type(value) is not dict or set(value) != keys:
        return ["abort raw closure schema mismatch"]
    if (
        value["schema"] != "noteai.item26.cost-containment-abort-raw-closure.v1"
        or any(
            not _hex64(value[key])
            for key in keys
            if key.endswith("_sha256")
        )
        or value["plan_sha256"] != authorization["plan_sha256"]
        or value["preflight_sha256"] != authorization["preflight_sha256"]
        or value["preflight_sha256"] != preflight["raw_projection_sha256"]
        or value["confirmation_envelope_sha256"]
        != authorization["confirmation_envelope_sha256"]
        or value["provider_request_set_sha256"]
        != provider_request_set_sha256(actions)
        or value["provider_response_set_sha256"]
        != provider_response_set_sha256(actions)
        or value["response_projection_sha256"]
        != response_projection_sha256(actions)
        or value["page_inventory_sha256"] != page_inventory_sha256(actions)
        or value["billing_observation_set_sha256"]
        != billing_observation_set_sha256(billing)
        or value["release_evidence_projection_sha256"]
        != release_evidence_projection_sha256(
            billing, actions, final_state, execution_boundary
        )
        or value["resource_disposition_set_sha256"]
        != resource_disposition_set_sha256(dispositions)
        or value["final_state_sha256"] != final_state_sha256(final_state)
        or type(value["raw_record_count"]) is not int
        or value["raw_record_count"] < len(EXPECTED_ACTIONS)
        or type(value["full_page_readback_count"]) is not int
        or value["full_page_readback_count"] < 1
        or value["raw_provider_payload_retained_in_repository"] is not False
        or value["secret_value_emitted_count"] != 0
    ):
        return ["abort raw closure mismatch"]
    return []


def _validate_no_replay(
    value: Any,
    actions: list[dict[str, Any]],
    authorization: dict[str, Any],
) -> list[str]:
    mutation_rows = [
        row for row in actions if row.get("mutation_submit_count") == 1
    ] if type(actions) is list else []
    expected = {
        "registry_ref": "deploy/production/plans/item26-no-replay-registry-v1.json",
        "registry_sha256": EXPECTED_HISTORICAL_REGISTRY_SHA256,
        "historical_entry_count": 25,
        "historical_replay_count": 0,
        "historical_replacement_count": 0,
        "historical_automatic_retry_count": 0,
        "untracked_script_execution_count": 0,
        "mutation_automatic_retry_count": 0,
        "mutation_manual_resend_count": 0,
        "mutation_parameter_change_count": 0,
        "replacement_target_count": 0,
        "terminal_unknown_count": 0,
        "unknown_same_identity_readback_only": True,
        "automatic_retry_allowed": False,
        "confirmation_nonce_sha256": authorization.get(
            "confirmation_nonce_sha256"
        ),
        "protection_disable_client_token_sha256": authorization.get(
            "protection_disable_client_token_sha256"
        ),
        "abort_mutation_identity_set_sha256": abort_mutation_identity_set_sha256(
            actions
        ),
        "abort_mutation_submit_count": len(mutation_rows),
        "abort_mutation_unknown_resolution_count": 0,
    }
    if not _strict(value, expected):
        return ["abort no-replay boundary mismatch"]
    return []


def _validate_execution_boundary(
    value: Any,
    dispositions: dict[str, dict[str, Any]],
    actions: list[dict[str, Any]],
) -> list[str]:
    mutation_operations = [
        row.get("operation")
        for row in actions
        if row.get("mutation_submit_count") == 1
    ] if type(actions) is list else []
    cleanup_mutations = sum(row["mutation_count"] for row in dispositions.values())
    expected = {
        "rds_instance_control_plane_write_count": sum(
            operation
            in {"ModifyDBInstanceDeletionProtection", "DeleteDBInstance"}
            for operation in mutation_operations
        ),
        "rds_account_control_plane_write_count": mutation_operations.count(
            "DeleteAccount"
        ),
        "ram_control_plane_write_count": sum(
            operation in {"DetachPolicyFromRole", "DeletePolicy", "DeleteRole"}
            for operation in mutation_operations
        ),
        "vpc_control_plane_write_count": mutation_operations.count(
            "DeleteVSwitch"
        ),
        "root_control_material_write_count": mutation_operations.count(
            "DeleteTaskControlMaterial"
        ),
        "deletion_protection_disable_count": 1,
        "clone_delete_count": 1,
        "task_cleanup_mutation_count": cleanup_mutations,
        "cloud_control_plane_write_count": len(mutation_operations)
        - mutation_operations.count("DeleteTaskControlMaterial"),
        "total_mutation_count": len(mutation_operations),
        "new_clone_count": 0,
        "restore_time_change_count": 0,
        "new_paid_resource_count": 0,
        "database_connection_count": 0,
        "database_transaction_count": 0,
        "database_write_count": 0,
        "object_write_count": 0,
        "source_permission_mutation_count": 0,
        "builder_start_count": 0,
        "builder_stop_count": 0,
        "builder_reboot_count": 0,
        "builder_delete_count": 0,
        "disk_detach_count": 0,
        "disk_resize_count": 0,
        "disk_delete_count": 0,
        "cloud_assistant_dispatch_count": 0,
        "sendfile_dispatch_count": 0,
        "historical_command_replay_count": 0,
        "public_request_count": 0,
        "workload_provider_call_count": 0,
        "service_restart_count": 0,
    }
    return [] if _strict(value, expected) else ["abort execution boundary mismatch"]


def validate_abort_result(receipt: Any) -> list[str]:
    """Return semantic errors for a terminal abort receipt projection."""

    if type(receipt) is not dict:
        return ["abort receipt must be an object"]
    errors: list[str] = []
    identities = receipt.get("identity_ledger")
    if type(identities) is not dict or set(identities) != set(IDENTITY_KEYS):
        return ["abort identity ledger schema mismatch"]
    if any(not _hex64(identities[key]) for key in IDENTITY_KEYS):
        errors.append("abort identity ledger digest mismatch")
    if (
        identities["inventory_scope_sha256"]
        != inventory_scope_sha256(identities)
        or identities["builder_disk_tuple_sha256"]
        != builder_disk_tuple_sha256(identities)
        or identities["ram_attachment_sha256"]
        != ram_attachment_sha256(identities)
    ):
        errors.append("abort composite identity ledger mismatch")
    critical = [
        identities[key]
        for key in (
            "old_clone_sha256",
            "source_rds_sha256",
            "builder_sha256",
            "shared_disk_sha256",
            "vswitch_a_sha256",
            "vswitch_b_sha256",
            "ram_role_sha256",
            "ram_policy_sha256",
            "ram_attachment_sha256",
            "temporary_account_sha256",
        )
    ]
    if len(set(critical)) != len(critical):
        errors.append("abort critical identities are not distinct")

    preflight = receipt.get("preflight")
    authorization = receipt.get("authorization")
    errors.extend(_validate_preflight(preflight, identities))
    errors.extend(_validate_authorization(authorization, preflight))
    if (
        type(authorization) is not dict
        or type(preflight) is not dict
        or not {
            "plan_sha256",
            "preflight_sha256",
            "confirmation_nonce_sha256",
            "protection_disable_client_token_sha256",
            "approved_at_utc",
            "expires_at_utc",
            "allowed_mutations",
            "destructive_clone_target_count",
            "new_paid_resource_allowed",
        }.issubset(authorization)
    ):
        return errors

    disposition_errors, dispositions = _validate_dispositions(
        receipt.get("resource_dispositions"), identities
    )
    errors.extend(disposition_errors)
    if len(dispositions) == len(RESOURCE_SLOTS):
        actions = receipt.get("ordered_actions")
        errors.extend(
            _validate_actions(
                actions,
                identities,
                authorization,
                preflight,
                dispositions,
            )
        )
        if type(actions) is list and all(type(row) is dict for row in actions):
            exact_planned_mutations = list(
                dict.fromkeys(
                    row["operation"]
                    for row in actions
                    if row.get("mutation_submit_count") == 1
                )
            )
            if authorization["allowed_mutations"] != exact_planned_mutations:
                errors.append("abort allowed mutation set exceeds exact plan")
            errors.extend(
                _validate_execution_boundary(
                    receipt.get("execution_boundary"), dispositions, actions
                )
            )
            expected_plan = abort_plan_sha256(
                identities,
                preflight,
                actions,
                receipt["resource_dispositions"],
                authorization,
            )
            if authorization["plan_sha256"] != expected_plan:
                errors.append("abort exact action plan binding mismatch")
    else:
        actions = receipt.get("ordered_actions")
    errors.extend(
        _validate_billing(
            receipt.get("billing_closure"), identities, actions, preflight
        )
    )
    errors.extend(_validate_final_state(receipt.get("final_state"), identities))
    resource_rows = receipt.get("resource_dispositions")
    final_state = receipt.get("final_state")
    if (
        type(actions) is list
        and all(type(row) is dict for row in actions)
        and type(receipt.get("billing_closure")) is dict
        and type(resource_rows) is list
        and all(type(row) is dict for row in resource_rows)
        and type(final_state) is dict
        and type(receipt.get("execution_boundary")) is dict
    ):
        errors.extend(
            _validate_raw_closure(
                receipt.get("raw_closure"),
                authorization,
                preflight,
                actions,
                receipt["billing_closure"],
                receipt.get("resource_dispositions"),
                receipt.get("final_state"),
                receipt.get("execution_boundary"),
            )
        )
        errors.extend(
            _validate_no_replay(receipt.get("no_replay"), actions, authorization)
        )
        action_times = [
            _utc(row.get("completed_at_utc"))
            for row in actions
            if type(row) is dict
        ]
        billing_observed = _utc(
            receipt["billing_closure"].get("final_observed_at_utc")
        )
        receipt_observed = _utc(receipt.get("observed_at_utc"))
        if (
            len(action_times) != len(actions)
            or any(item is None for item in action_times)
            or billing_observed is None
            or receipt_observed is None
            or receipt_observed
            != max([item for item in action_times if item is not None] + [billing_observed])
        ):
            errors.append("abort terminal observation timeline mismatch")
    else:
        errors.append("abort raw/no-replay projection unavailable")
    if not _strict(receipt.get("readiness"), READINESS_25_TO_25):
        errors.append("abort readiness must remain 25/29 with no credit")
    return errors


__all__ = [
    "ALLOWED_MUTATIONS",
    "EXPECTED_ACTIONS",
    "IDENTITY_KEYS",
    "OPERATION_ID",
    "READINESS_25_TO_25",
    "RESOURCE_SLOTS",
    "RELEASE_BILLING_CONTRACT_REF",
    "EXPECTED_RELEASE_BILLING_CONTRACT_SHA256",
    "TASK_ID",
    "TERMINAL_STATUS",
    "VALIDATOR_REF",
    "release_evidence_projection_sha256",
    "validate_abort_result",
]
