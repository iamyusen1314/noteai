import base64
import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import extract_item26_cost_containment_abort_raw_v1 as extractor  # noqa: E402


REVISION = "8" * 40
REGION = "cn-shenzhen"
CLONE = "rm-test-clone-secret-id"
SOURCE = "rm-test-source-secret-id"
CLIENT_TOKEN = "test-unique-protection-token"
CONTRACT_SHA256 = "9" * 64


def canonical(value):
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


def record(
    sequence,
    slot,
    operation,
    request,
    response,
    *,
    status=200,
    second=None,
):
    second = sequence if second is None else second
    return {
        "sequence": sequence,
        "slot": slot,
        "operation": operation,
        "region_id": REGION,
        "started_at_utc": f"2026-08-16T00:00:{second:02d}Z",
        "completed_at_utc": f"2026-08-16T00:00:{second:02d}Z",
        "transport_outcome": extractor.TRANSPORT_RESPONSE_RECEIVED,
        "http_status": status,
        "request_json_base64": base64.b64encode(canonical(request)).decode("ascii"),
        "response_json_base64": base64.b64encode(canonical(response)).decode("ascii"),
    }


def unknown_record(sequence, slot, operation, request, *, second=None):
    value = record(
        sequence,
        slot,
        operation,
        request,
        {},
        second=second,
    )
    value["transport_outcome"] = extractor.TRANSPORT_NO_RESPONSE_UNKNOWN
    value["http_status"] = None
    value["response_json_base64"] = None
    return value


def capture(records, phase="TERMINAL"):
    return canonical({
        "schema": extractor.CAPTURE_SCHEMA,
        "task_id": extractor.TASK_ID,
        "operation_id": extractor.OPERATION_ID,
        "phase": phase,
        "source_revision": REVISION,
        "observed_at_utc": "2026-08-16T00:00:59Z",
        "records": records,
    })


def rds_request(instance_id, page=1, page_size=100):
    return {
        "Action": "DescribeDBInstances",
        "Version": "2014-08-15",
        "RegionId": REGION,
        "DBInstanceId": instance_id,
        "PageNumber": page,
        "PageSize": page_size,
    }


def rds_instance(instance_id, *, pay_type, protected, status="Running"):
    return {
        "DBInstanceId": instance_id,
        "DBInstanceStatus": status,
        "PayType": pay_type,
        "Engine": "PostgreSQL",
        "EngineVersion": "16.0",
        "DeletionProtection": protected,
        "VpcId": "vpc-test-secret-id",
        "VSwitchId": "vsw-test-secret-id",
        "ZoneId": "cn-shenzhen-e",
        "ConnectionString": "root-only.example.invalid",
    }


def rds_response(items, *, page=1, total=None, request_id=None):
    total = len(items) if total is None else total
    return {
        "RequestId": request_id or f"request-{page}",
        "PageNumber": page,
        "PageRecordCount": len(items),
        "TotalRecordCount": total,
        "Items": {"DBInstance": items},
    }


def parsed(records, phase="TERMINAL"):
    return extractor.parse_capture(capture(records, phase), expected_phase=phase)


class Item26AbortRawExtractorTests(unittest.TestCase):
    def test_exact_present_rds_inventory_is_secret_free(self):
        raw = parsed([
            record(
                1,
                "source_final",
                "DescribeDBInstances",
                rds_request(SOURCE),
                rds_response([
                    rds_instance(SOURCE, pay_type="Prepaid", protected=True)
                ]),
            )
        ])
        projection = extractor.project_rds_inventory(
            raw,
            slot="source_final",
            region_id=REGION,
            instance_id=SOURCE,
            expected_count=1,
        )
        self.assertEqual(projection["exact_count"], 1)
        self.assertEqual(projection["instances"][0]["status"], "Running")
        self.assertEqual(projection["instances"][0]["pay_type"], "Prepaid")
        self.assertFalse(
            extractor.emitted_contains_raw_identifier(
                projection,
                [SOURCE, "vpc-test-secret-id", "vsw-test-secret-id"],
            )
        )

    def test_exact_absence_requires_complete_page(self):
        raw = parsed([
            record(
                1,
                "clone_absence",
                "DescribeDBInstances",
                rds_request(CLONE),
                rds_response([]),
            )
        ])
        projection = extractor.project_rds_inventory(
            raw,
            slot="clone_absence",
            region_id=REGION,
            instance_id=CLONE,
            expected_count=0,
        )
        self.assertEqual(projection["exact_count"], 0)
        self.assertTrue(projection["full_page_complete"])

    def test_incomplete_rds_pagination_fails(self):
        raw = parsed([
            record(
                1,
                "inventory",
                "DescribeDBInstances",
                rds_request(CLONE, page_size=1),
                rds_response(
                    [rds_instance(CLONE, pay_type="Postpaid", protected=True)],
                    total=2,
                ),
            )
        ])
        with self.assertRaisesRegex(extractor.ExtractionError, "incomplete_pages"):
            extractor.project_rds_inventory(
                raw,
                slot="inventory",
                region_id=REGION,
                instance_id=CLONE,
                expected_count=1,
            )

    def test_wrong_rds_identity_fails(self):
        raw = parsed([
            record(
                1,
                "inventory",
                "DescribeDBInstances",
                rds_request(CLONE),
                rds_response([
                    rds_instance(SOURCE, pay_type="Prepaid", protected=True)
                ]),
            )
        ])
        with self.assertRaisesRegex(extractor.ExtractionError, "instance_identity"):
            extractor.project_rds_inventory(
                raw,
                slot="inventory",
                region_id=REGION,
                instance_id=CLONE,
                expected_count=1,
            )

    def test_accepted_protection_disable_is_exact(self):
        request = {
            "Action": "ModifyDBInstanceDeletionProtection",
            "Version": "2014-08-15",
            "RegionId": REGION,
            "DBInstanceId": CLONE,
            "DeletionProtection": False,
            "ClientToken": CLIENT_TOKEN,
        }
        raw = parsed([
            record(
                1,
                "disable",
                "ModifyDBInstanceDeletionProtection",
                request,
                {"RequestId": "disable-request-id"},
            )
        ])
        projection = extractor.project_accepted_rds_mutation(
            raw,
            slot="disable",
            operation="ModifyDBInstanceDeletionProtection",
            region_id=REGION,
            instance_id=CLONE,
            client_token=CLIENT_TOKEN,
        )
        self.assertEqual(projection["submission_outcome"], "ACCEPTED")
        self.assertFalse(
            extractor.emitted_contains_raw_identifier(
                projection, [CLONE, CLIENT_TOKEN, "disable-request-id"]
            )
        )

    def test_delete_response_must_be_unambiguously_accepted(self):
        request = {
            "Action": "DeleteDBInstance",
            "Version": "2014-08-15",
            "RegionId": REGION,
            "DBInstanceId": CLONE,
        }
        raw = parsed([
            record(
                1,
                "delete",
                "DeleteDBInstance",
                request,
                {"Code": "InternalError"},
                status=500,
            )
        ])
        with self.assertRaisesRegex(extractor.ExtractionError, "transport"):
            extractor.project_accepted_rds_mutation(
                raw,
                slot="delete",
                operation="DeleteDBInstance",
                region_id=REGION,
                instance_id=CLONE,
            )

    def test_http_200_provider_error_is_not_accepted(self):
        request = {
            "Action": "DeleteDBInstance",
            "Version": "2014-08-15",
            "RegionId": REGION,
            "DBInstanceId": CLONE,
        }
        raw = parsed([
            record(
                1,
                "delete",
                "DeleteDBInstance",
                request,
                {
                    "RequestId": "failed-request-id",
                    "Code": "InternalError",
                    "Success": False,
                },
            )
        ])
        with self.assertRaisesRegex(extractor.ExtractionError, "response_schema"):
            extractor.project_accepted_rds_mutation(
                raw,
                slot="delete",
                operation="DeleteDBInstance",
                region_id=REGION,
                instance_id=CLONE,
            )

    def test_delete_response_region_must_match_target_region(self):
        request = {
            "Action": "DeleteDBInstance",
            "Version": "2014-08-15",
            "RegionId": REGION,
            "DBInstanceId": CLONE,
        }
        raw = parsed([
            record(
                1,
                "delete",
                "DeleteDBInstance",
                request,
                {
                    "RequestId": "delete-request-id",
                    "RegionId": "cn-hangzhou",
                },
            )
        ])
        with self.assertRaisesRegex(extractor.ExtractionError, "response_region"):
            extractor.project_accepted_rds_mutation(
                raw,
                slot="delete",
                operation="DeleteDBInstance",
                region_id=REGION,
                instance_id=CLONE,
            )

    def test_mutation_without_response_remains_unknown(self):
        request = {
            "Action": "DeleteDBInstance",
            "Version": "2014-08-15",
            "RegionId": REGION,
            "DBInstanceId": CLONE,
        }
        raw = parsed([
            unknown_record(1, "delete", "DeleteDBInstance", request)
        ])
        with self.assertRaisesRegex(extractor.ExtractionError, "mutation_transport"):
            extractor.project_accepted_rds_mutation(
                raw,
                slot="delete",
                operation="DeleteDBInstance",
                region_id=REGION,
                instance_id=CLONE,
            )

    def test_exact_capture_slot_ledger_rejects_unconsumed_attempt(self):
        raw = parsed([
            record(
                1,
                "source",
                "DescribeDBInstances",
                rds_request(SOURCE),
                rds_response([
                    rds_instance(SOURCE, pay_type="Prepaid", protected=True)
                ]),
            ),
            unknown_record(
                2,
                "unexpected_delete",
                "DeleteDBInstance",
                {
                    "Action": "DeleteDBInstance",
                    "Version": "2014-08-15",
                    "RegionId": REGION,
                    "DBInstanceId": CLONE,
                },
            ),
        ])
        with self.assertRaisesRegex(extractor.ExtractionError, "slot_ledger"):
            extractor.require_exact_capture_slots(
                raw,
                {"source": "DescribeDBInstances"},
            )

    def test_query_instance_bill_is_historical_snapshot_only(self):
        request = {
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
        bill_item = {
            "InstanceID": CLONE,
            "Currency": "CNY",
            "SubscriptionType": "PayAsYouGo",
            "ProductCode": "rds",
            "PipCode": "rds",
            "ServicePeriod": "331200",
            "ServicePeriodUnit": "Seconds",
            "PretaxGrossAmount": "185.658",
        }
        response = {
            "Code": "Success",
            "Success": True,
            "RequestId": "billing-request-id",
            "Data": {
                "PageNum": 1,
                "BillingCycle": "2026-08",
                "PageSize": 300,
                "TotalCount": 1,
                "Items": {"Item": [bill_item]},
            },
        }
        raw = parsed([
            record(1, "billing", "QueryInstanceBill", request, response)
        ])
        projection = extractor.project_instance_bill(
            raw,
            slot="billing",
            instance_id=CLONE,
            billing_cycle="2026-08",
        )
        self.assertEqual(projection["pretax_gross_cny"], "185.658")
        self.assertEqual(projection["service_seconds"], 331200)
        self.assertTrue(projection["historical_snapshot_only"])
        self.assertFalse(projection["terminal_non_accruing_marker_present"])
        self.assertFalse(
            extractor.emitted_contains_raw_identifier(
                projection, [CLONE, "billing-request-id"]
            )
        )

    def test_release_native_projection_binds_delete_absence_and_source(self):
        delete_request = {
            "Action": "DeleteDBInstance",
            "Version": "2014-08-15",
            "RegionId": REGION,
            "DBInstanceId": CLONE,
        }
        delete = extractor.project_accepted_rds_mutation(
            parsed([
                record(
                    1,
                    "delete",
                    "DeleteDBInstance",
                    delete_request,
                    {"RequestId": "delete-request-id", "RegionId": REGION},
                )
            ]),
            slot="delete",
            operation="DeleteDBInstance",
            region_id=REGION,
            instance_id=CLONE,
        )
        absence = extractor.project_rds_inventory(
            parsed([
                record(
                    1,
                    "absence",
                    "DescribeDBInstances",
                    rds_request(CLONE),
                    rds_response([]),
                )
            ]),
            slot="absence",
            region_id=REGION,
            instance_id=CLONE,
            expected_count=0,
        )
        source = extractor.project_rds_inventory(
            parsed([
                record(
                    1,
                    "source",
                    "DescribeDBInstances",
                    rds_request(SOURCE),
                    rds_response([
                        rds_instance(SOURCE, pay_type="Prepaid", protected=True)
                    ]),
                )
            ]),
            slot="source",
            region_id=REGION,
            instance_id=SOURCE,
            expected_count=1,
        )
        digest = extractor.release_native_projection_sha256(
            release_contract_sha256=CONTRACT_SHA256,
            delete_projection=delete,
            absence_projection=absence,
            source_projection=source,
            preflight_source_instance=copy.deepcopy(source["instances"][0]),
            new_paid_resource_count=0,
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        drifted = copy.deepcopy(absence)
        drifted["observation_set_sha256"] = "a" * 64
        self.assertNotEqual(
            digest,
            extractor.release_native_projection_sha256(
                release_contract_sha256=CONTRACT_SHA256,
                delete_projection=delete,
                absence_projection=drifted,
                source_projection=source,
                preflight_source_instance=copy.deepcopy(source["instances"][0]),
                new_paid_resource_count=0,
            ),
        )
        source_drift = copy.deepcopy(source)
        source_drift["instances"][0]["vpc_sha256"] = "a" * 64
        with self.assertRaisesRegex(extractor.ExtractionError, "release_source"):
            extractor.release_native_projection_sha256(
                release_contract_sha256=CONTRACT_SHA256,
                delete_projection=delete,
                absence_projection=absence,
                source_projection=source_drift,
                preflight_source_instance=copy.deepcopy(source["instances"][0]),
                new_paid_resource_count=0,
            )

    def test_release_projection_rejects_forged_shallow_leaves(self):
        with self.assertRaisesRegex(extractor.ExtractionError, "release_native"):
            extractor.release_native_projection_sha256(
                release_contract_sha256=CONTRACT_SHA256,
                delete_projection={
                    "operation": "DeleteDBInstance",
                    "submission_outcome": "ACCEPTED",
                },
                absence_projection={
                    "exact_count": 0,
                    "full_page_complete": True,
                },
                source_projection={
                    "exact_count": 1,
                    "full_page_complete": True,
                    "instances": [{"status": "Running", "pay_type": "Prepaid"}],
                },
                preflight_source_instance={},
                new_paid_resource_count=0,
            )

    def test_raw_derived_commitment_key_is_rejected(self):
        request = rds_request(CLONE)
        request["candidate_sha256"] = "a" * 64
        with self.assertRaisesRegex(extractor.ExtractionError, "derived_key"):
            parsed([
                record(
                    1,
                    "inventory",
                    "DescribeDBInstances",
                    request,
                    rds_response([]),
                )
            ])

    def test_secret_request_key_is_rejected(self):
        request = rds_request(CLONE)
        request["AccessKeySecret"] = "must-not-enter-capture"
        with self.assertRaisesRegex(extractor.ExtractionError, "secret_key"):
            parsed([
                record(
                    1,
                    "inventory",
                    "DescribeDBInstances",
                    request,
                    rds_response([]),
                )
            ])

    def test_outer_capture_must_be_canonical(self):
        value = json.loads(capture([
            record(
                1,
                "inventory",
                "DescribeDBInstances",
                rds_request(CLONE),
                rds_response([]),
            )
        ]))
        noncanonical = json.dumps(value, indent=2).encode("ascii")
        with self.assertRaisesRegex(extractor.ExtractionError, "canonical"):
            extractor.parse_capture(noncanonical, expected_phase="TERMINAL")

    def test_duplicate_inner_json_key_is_rejected(self):
        row = record(
            1,
            "inventory",
            "DescribeDBInstances",
            rds_request(CLONE),
            rds_response([]),
        )
        row["response_json_base64"] = base64.b64encode(
            b'{"RequestId":"a","RequestId":"b"}\n'
        ).decode("ascii")
        with self.assertRaisesRegex(extractor.ExtractionError, "duplicate_json_key"):
            parsed([row])


if __name__ == "__main__":
    unittest.main()
