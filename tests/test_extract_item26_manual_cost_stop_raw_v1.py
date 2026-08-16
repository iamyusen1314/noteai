import base64
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import extract_item26_manual_cost_stop_raw_v1 as extractor  # noqa: E402


CONTROL_REVISION = "2" * 40
CLONE_ID = "test-old-clone-id"
SOURCE_ID = "test-source-id"
SOURCE_NAME = "test-source-name"
CREATE_REQUEST_ID = "test-clone-create-request-id"
CREATE_IDEMPOTENCY_MARKER = "test-clone-create-client-token"


def encoded(value):
    return base64.b64encode(extractor.canonical_bytes(value)).decode("ascii")


def record(sequence, slot, operation, version, request, response):
    started_second = sequence * 2
    completed_second = started_second + 1
    return {
        "sequence": sequence,
        "slot": slot,
        "operation": operation,
        "api_version": version,
        "started_at_utc": (
            f"2026-08-17T00:00:{started_second:02d}.475Z"
        ),
        "completed_at_utc": (
            f"2026-08-17T00:00:{completed_second:02d}.475Z"
        ),
        "transport_outcome": "RESPONSE_RECEIVED",
        "read_only": True,
        "request_json_base64": encoded(request),
        "response_json_base64": encoded(response),
    }


def provider_capture():
    clone_response = {
        "Items": {"DBInstance": []},
        "NextToken": "",
        "PageNumber": 1,
        "PageRecordCount": 0,
        "RequestId": "lookup-clone-request-id",
        "TotalRecordCount": 0,
    }
    source_response = {
        "Items": {"DBInstance": [{
            "DBInstanceDescription": SOURCE_NAME,
            "DBInstanceId": SOURCE_ID,
            "DBInstanceStatus": "Running",
            "Engine": "PostgreSQL",
            "EngineVersion": "16",
            "PayType": "Prepaid",
        }]},
        "NextToken": "",
        "PageNumber": 1,
        "PageRecordCount": 1,
        "RequestId": "lookup-source-request-id",
        "TotalRecordCount": 1,
    }
    billing_response = {
        "Code": "Success",
        "Data": {
            "Items": {"Item": [{
                "Currency": "CNY",
                "InstanceID": CLONE_ID,
                "PretaxGrossAmount": "198.462",
                "ServicePeriod": 345600,
                "ServicePeriodUnit": "Seconds",
                "SubscriptionType": "PayAsYouGo",
                "ProductCode": "rds",
                "PipCode": "rds",
            }]},
            "BillingCycle": "2026-08",
            "PageNum": 1,
            "PageSize": 300,
            "TotalCount": 1,
        },
        "RequestId": "billing-query-request-id",
        "Success": True,
    }
    return {
        "schema": extractor.PROVIDER_CAPTURE_SCHEMA,
        "task_id": extractor.TASK_ID,
        "operation_id": extractor.OPERATION_ID,
        "phase": "POST_ACTION_READBACK_ONLY",
        "m0_anchor_revision": extractor.M0_ANCHOR_REVISION,
        "control_revision": CONTROL_REVISION,
        "observed_at_utc": "2026-08-17T00:00:10.475Z",
        "records": [
            record(
                1,
                "fresh_clone_inventory",
                "DescribeDBInstances",
                "2014-08-15",
                {
                    "Action": "DescribeDBInstances",
                    "Version": "2014-08-15",
                    "DBInstanceId": CLONE_ID,
                    "RegionId": "cn-shenzhen",
                    "PageNumber": 1,
                    "PageSize": 100,
                },
                clone_response,
            ),
            record(
                2,
                "fresh_source_inventory",
                "DescribeDBInstances",
                "2014-08-15",
                {
                    "Action": "DescribeDBInstances",
                    "Version": "2014-08-15",
                    "DBInstanceId": SOURCE_ID,
                    "RegionId": "cn-shenzhen",
                    "PageNumber": 1,
                    "PageSize": 100,
                },
                source_response,
            ),
            record(
                3,
                "historical_billing_snapshot",
                "QueryInstanceBill",
                "2017-12-14",
                {
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
                },
                billing_response,
            ),
        ],
    }


def event(event_id, name, time):
    return {
        "eventId": event_id,
        "eventName": name,
        "eventRW": "Write",
        "eventSource": "rds.aliyuncs.com",
        "eventTime": time,
        "resourceName": CLONE_ID,
        "resourceType": "ALIYUN::RDS::DBInstance",
        "serviceName": "Rds",
        "userIdentity": {"type": "root-account", "userName": "test-user"},
    }


def lookup_request(next_token=None, *, stream="cost_stop"):
    if stream == "cost_stop":
        start = "2026-08-16T14:38:00Z"
        end = "2026-08-16T14:46:00Z"
        attributes = [
            {"Key": "ServiceName", "Value": "Rds"},
            {"Key": "EventRW", "Value": "Write"},
        ]
    else:
        start = "2026-08-12T00:00:00Z"
        end = "2026-08-13T00:00:00Z"
        attributes = [
            {"Key": "EventName", "Value": "CloneDBInstance"},
            {"Key": "ResourceName", "Value": CLONE_ID},
        ]
    value = {
        "Action": "LookupEvents",
        "Version": "2020-07-06",
        "Direction": "FORWARD",
        "EndTime": end,
        "LookupAttribute": attributes,
        "MaxResults": "50",
        "StartTime": start,
    }
    if next_token is not None:
        value["NextToken"] = next_token
    return value


def actiontrail_capture():
    create = event(
        "event-create",
        "CloneDBInstance",
        "2026-08-12T12:00:00Z",
    )
    create["requestId"] = CREATE_REQUEST_ID
    create["requestParameters"] = {
        "ClientToken": CREATE_IDEMPOTENCY_MARKER,
        "DBInstanceDescription": SOURCE_NAME.replace("source", "old-clone"),
        "DBInstanceId": SOURCE_ID,
    }
    return {
        "schema": extractor.ACTIONTRAIL_CAPTURE_SCHEMA,
        "task_id": extractor.TASK_ID,
        "operation_id": extractor.OPERATION_ID,
        "phase": "POST_ACTION_READBACK_ONLY",
        "m0_anchor_revision": extractor.M0_ANCHOR_REVISION,
        "control_revision": CONTROL_REVISION,
        "observed_at_utc": "2026-08-17T00:00:10.475Z",
        "records": [
            record(
                1,
                "cost_stop_rds_write_lookup_page",
                "LookupEvents",
                "2020-07-06",
                lookup_request(),
                {
                    "EndTime": "2026-08-16T14:46:00Z",
                    "Events": [event(
                        "event-1",
                        "ModifyDBInstanceDeletionProtection",
                        "2026-08-16T14:40:00Z",
                    )],
                    "NextToken": "page-2-token",
                    "RequestId": "lookup-page-1-request-id",
                    "StartTime": "2026-08-16T14:38:00Z",
                },
            ),
            record(
                2,
                "cost_stop_rds_write_lookup_page",
                "LookupEvents",
                "2020-07-06",
                lookup_request("page-2-token"),
                {
                    "EndTime": "2026-08-16T14:46:00Z",
                    "Events": [event(
                        "event-2",
                        "DeleteDBInstance",
                        "2026-08-16T14:42:00Z",
                    )],
                    "NextToken": "",
                    "RequestId": "lookup-page-2-request-id",
                    "StartTime": "2026-08-16T14:38:00Z",
                },
            ),
            record(
                3,
                "clone_create_lookup_page",
                "LookupEvents",
                "2020-07-06",
                lookup_request(stream="clone_create"),
                {
                    "EndTime": "2026-08-13T00:00:00Z",
                    "Events": [create],
                    "NextToken": "",
                    "RequestId": "lookup-create-page-request-id",
                    "StartTime": "2026-08-12T00:00:00Z",
                },
            ),
        ],
    }


class ManualCostStopRawExtractorTests(unittest.TestCase):
    def patches(self, billing_response):
        patchers = [
            mock.patch.object(
                extractor,
                "EXPECTED_OLD_CLONE_SHA256",
                extractor.value_sha256(CLONE_ID),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_SOURCE_SHA256",
                extractor.value_sha256(SOURCE_ID),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_SOURCE_NAME_SHA256",
                extractor.value_sha256(SOURCE_NAME),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_OLD_CLONE_NAME_SHA256",
                extractor.value_sha256(
                    SOURCE_NAME.replace("source", "old-clone")
                ),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_BILLING_RESPONSE_SHA256",
                extractor.sha256(extractor.canonical_bytes(billing_response)),
            ),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def valid_projection(self):
        provider = provider_capture()
        actiontrail = actiontrail_capture()
        billing_response = extractor.decode_canonical_json(
            provider["records"][2]["response_json_base64"],
            "fixture",
        )
        self.patches(billing_response)
        return extractor.extract_verified_projection(
            extractor.canonical_bytes(provider),
            extractor.canonical_bytes(actiontrail),
            expected_control_revision=CONTROL_REVISION,
        )

    def add_cost_stop_request_authority(self, value):
        protection_response = extractor.decode_canonical_json(
            value["records"][0]["response_json_base64"], "fixture"
        )
        deletion_response = extractor.decode_canonical_json(
            value["records"][1]["response_json_base64"], "fixture"
        )
        protection = protection_response["Events"][0]
        deletion = deletion_response["Events"][0]
        protection["requestId"] = "test-protection-request-id"
        protection["requestParameters"] = {
            "ClientToken": "test-protection-token",
            "DBInstanceId": CLONE_ID,
            "DeletionProtection": False,
        }
        deletion["requestId"] = "test-delete-request-id"
        deletion["requestParameters"] = {"DBInstanceId": CLONE_ID}
        value["records"][0]["response_json_base64"] = encoded(
            protection_response
        )
        value["records"][1]["response_json_base64"] = encoded(
            deletion_response
        )
        patchers = [
            mock.patch.object(
                extractor,
                "EXPECTED_PROTECTION_REQUEST_ID_SHA256",
                extractor.value_sha256("test-protection-request-id"),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_DELETE_REQUEST_ID_SHA256",
                extractor.value_sha256("test-delete-request-id"),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256",
                extractor.value_sha256("test-protection-token"),
            ),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_provider_and_actiontrail_domains_project_separately(self):
        projection = self.valid_projection()
        self.assertTrue(projection.provider["old_clone"]["absent"])
        self.assertEqual(projection.provider["source"]["status"], "Running")
        self.assertEqual(projection.actiontrail["event_count"], 3)
        self.assertTrue(
            projection.actiontrail["old_clone_create_identity_rederived"]
        )
        self.assertTrue(projection.actiontrail["complete_pagination_proven"])

    def test_mixed_legacy_capture_is_retired(self):
        with self.assertRaisesRegex(
            extractor.ExtractionError, "mixed_capture_schema_retired"
        ):
            extractor.validate_capture_envelope({})

    def test_event_detail_is_ignored_and_never_projected(self):
        value = actiontrail_capture()
        response = extractor.decode_canonical_json(
            value["records"][0]["response_json_base64"], "fixture"
        )
        response["Events"][0]["EventDetail"] = "{}"
        value["records"][0]["response_json_base64"] = encoded(response)
        with mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_SHA256",
            extractor.value_sha256(CLONE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_SOURCE_SHA256",
            extractor.value_sha256(SOURCE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_NAME_SHA256",
            extractor.value_sha256(
                SOURCE_NAME.replace("source", "old-clone")
            ),
        ):
            projection = extractor.project_actiontrail_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )
        emitted = extractor.canonical_bytes(projection)
        self.assertNotIn(b"EventDetail", emitted)
        self.assertFalse(
            projection["historical_request_bodies_rederived"]
        )

    def test_lookup_request_id_does_not_become_mutation_request_id(self):
        projection = self.valid_projection().actiontrail
        self.assertFalse(projection["historical_mutation_request_ids_rederived"])
        emitted = extractor.canonical_bytes(projection)
        self.assertNotIn(b"lookup-page-1-request-id", emitted)
        self.assertNotIn(b"page-2-token", emitted)

    def test_direct_request_parameters_can_rederive_consumed_identities(self):
        value = actiontrail_capture()
        self.add_cost_stop_request_authority(value)
        with mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_SHA256",
            extractor.value_sha256(CLONE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_SOURCE_SHA256",
            extractor.value_sha256(SOURCE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_NAME_SHA256",
            extractor.value_sha256(
                SOURCE_NAME.replace("source", "old-clone")
            ),
        ):
            projection = extractor.project_actiontrail_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )
        self.assertTrue(projection["historical_mutation_request_ids_rederived"])
        self.assertTrue(projection["historical_request_bodies_rederived"])
        self.assertTrue(projection["historical_client_tokens_rederived"])

    def test_numeric_false_alias_is_rejected(self):
        value = actiontrail_capture()
        self.add_cost_stop_request_authority(value)
        response = extractor.decode_canonical_json(
            value["records"][0]["response_json_base64"], "fixture"
        )
        response["Events"][0]["requestParameters"][
            "DeletionProtection"
        ] = 0
        value["records"][0]["response_json_base64"] = encoded(response)
        with mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_SHA256",
            extractor.value_sha256(CLONE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_SOURCE_SHA256",
            extractor.value_sha256(SOURCE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_NAME_SHA256",
            extractor.value_sha256(
                SOURCE_NAME.replace("source", "old-clone")
            ),
        ), self.assertRaisesRegex(
            extractor.ExtractionError, "actiontrail_protection_parameters"
        ):
            extractor.project_actiontrail_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_next_token_gap_is_rejected(self):
        value = actiontrail_capture()
        request = extractor.decode_canonical_json(
            value["records"][1]["request_json_base64"], "fixture"
        )
        request["NextToken"] = "wrong-token"
        value["records"][1]["request_json_base64"] = encoded(request)
        with mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_SHA256",
            extractor.value_sha256(CLONE_ID),
        ), self.assertRaisesRegex(
            extractor.ExtractionError, "actiontrail_token_chain"
        ):
            extractor.project_actiontrail_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_next_token_cycle_is_rejected(self):
        value = actiontrail_capture()
        response = extractor.decode_canonical_json(
            value["records"][1]["response_json_base64"], "fixture"
        )
        response["NextToken"] = "page-2-token"
        value["records"][1]["response_json_base64"] = encoded(response)
        with mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_SHA256",
            extractor.value_sha256(CLONE_ID),
        ), self.assertRaisesRegex(
            extractor.ExtractionError, "actiontrail_response_token_reuse"
        ):
            extractor.project_actiontrail_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_extra_write_event_is_rejected(self):
        value = actiontrail_capture()
        response = extractor.decode_canonical_json(
            value["records"][1]["response_json_base64"], "fixture"
        )
        response["Events"].append(event(
            "event-3", "DeleteDBInstance", "2026-08-16T14:43:00Z"
        ))
        value["records"][1]["response_json_base64"] = encoded(response)
        with mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_SHA256",
            extractor.value_sha256(CLONE_ID),
        ), self.assertRaisesRegex(
            extractor.ExtractionError, "actiontrail_event_count"
        ):
            extractor.project_actiontrail_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_present_clone_is_rejected(self):
        value = provider_capture()
        response = extractor.decode_canonical_json(
            value["records"][0]["response_json_base64"], "fixture"
        )
        response["Items"]["DBInstance"].append({"DBInstanceId": CLONE_ID})
        response["PageRecordCount"] = 1
        response["TotalRecordCount"] = 1
        value["records"][0]["response_json_base64"] = encoded(response)
        billing = extractor.decode_canonical_json(
            value["records"][2]["response_json_base64"], "fixture"
        )
        self.patches(billing)
        with self.assertRaisesRegex(
            extractor.ExtractionError, "old_clone_still_present"
        ):
            extractor.project_provider_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_describe_extra_filter_cannot_forge_absence(self):
        value = provider_capture()
        request = extractor.decode_canonical_json(
            value["records"][0]["request_json_base64"], "fixture"
        )
        request["DBInstanceStatus"] = "Creating"
        value["records"][0]["request_json_base64"] = encoded(request)
        billing = extractor.decode_canonical_json(
            value["records"][2]["response_json_base64"], "fixture"
        )
        self.patches(billing)
        with self.assertRaisesRegex(
            extractor.ExtractionError, "describe_request_identity"
        ):
            extractor.project_provider_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_wrong_region_cannot_forge_clone_absence(self):
        value = provider_capture()
        request = extractor.decode_canonical_json(
            value["records"][0]["request_json_base64"], "fixture"
        )
        request["RegionId"] = "cn-hangzhou"
        value["records"][0]["request_json_base64"] = encoded(request)
        billing = extractor.decode_canonical_json(
            value["records"][2]["response_json_base64"], "fixture"
        )
        self.patches(billing)
        with self.assertRaisesRegex(
            extractor.ExtractionError, "describe_request_identity"
        ):
            extractor.project_provider_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_cost_stop_events_must_follow_confirmation_and_precede_absence(self):
        value = actiontrail_capture()
        first = extractor.decode_canonical_json(
            value["records"][0]["response_json_base64"], "fixture"
        )
        second = extractor.decode_canonical_json(
            value["records"][1]["response_json_base64"], "fixture"
        )
        first["Events"][0]["eventTime"] = "2026-08-16T14:38:30Z"
        second["Events"][0]["eventTime"] = "2026-08-16T14:45:30Z"
        value["records"][0]["response_json_base64"] = encoded(first)
        value["records"][1]["response_json_base64"] = encoded(second)
        with mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_SHA256",
            extractor.value_sha256(CLONE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_SOURCE_SHA256",
            extractor.value_sha256(SOURCE_ID),
        ), mock.patch.object(
            extractor,
            "EXPECTED_OLD_CLONE_NAME_SHA256",
            extractor.value_sha256(
                SOURCE_NAME.replace("source", "old-clone")
            ),
        ), self.assertRaisesRegex(
            extractor.ExtractionError, "actiontrail_mutation_time_order"
        ):
            extractor.project_actiontrail_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_source_drift_is_rejected(self):
        value = provider_capture()
        response = extractor.decode_canonical_json(
            value["records"][1]["response_json_base64"], "fixture"
        )
        response["Items"]["DBInstance"][0]["PayType"] = "Postpaid"
        value["records"][1]["response_json_base64"] = encoded(response)
        billing = extractor.decode_canonical_json(
            value["records"][2]["response_json_base64"], "fixture"
        )
        self.patches(billing)
        with self.assertRaisesRegex(extractor.ExtractionError, "source_tuple"):
            extractor.project_provider_readback(
                extractor.canonical_bytes(value),
                expected_control_revision=CONTROL_REVISION,
            )

    def test_fresh_billing_may_advance_above_recorded_baseline(self):
        value = provider_capture()
        response = extractor.decode_canonical_json(
            value["records"][2]["response_json_base64"], "fixture"
        )
        response["Data"]["Items"]["Item"][0][
            "PretaxGrossAmount"
        ] = "211.266"
        response["Data"]["Items"]["Item"][0]["ServicePeriod"] = 360000
        value["records"][2]["response_json_base64"] = encoded(response)
        self.patches(response)
        projection = extractor.project_provider_readback(
            extractor.canonical_bytes(value),
            expected_control_revision=CONTROL_REVISION,
        )
        self.assertEqual(projection["billing"]["pretax_gross_cny"], "211.266")
        self.assertEqual(projection["billing"]["service_seconds"], 360000)
        self.assertTrue(projection["billing"]["historical_snapshot_only"])

    def test_fresh_billing_decimal_text_is_canonical(self):
        value = provider_capture()
        response = extractor.decode_canonical_json(
            value["records"][2]["response_json_base64"], "fixture"
        )
        response["Data"]["Items"]["Item"][0][
            "PretaxGrossAmount"
        ] = "211.20"
        value["records"][2]["response_json_base64"] = encoded(response)
        self.patches(response)
        projection = extractor.project_provider_readback(
            extractor.canonical_bytes(value),
            expected_control_revision=CONTROL_REVISION,
        )
        self.assertEqual(projection["billing"]["pretax_gross_cny"], "211.2")

    def test_plain_dict_cannot_construct_verified_projection(self):
        with self.assertRaisesRegex(
            extractor.ExtractionError, "verified_projection_loader_required"
        ):
            extractor.VerifiedManualProjection({}, {}, token=object())

    def test_projection_does_not_emit_complete_resource_values(self):
        projection = self.valid_projection()
        raw = extractor.canonical_bytes({
            "provider": projection.provider,
            "actiontrail": projection.actiontrail,
        })
        for value in (CLONE_ID, SOURCE_ID, SOURCE_NAME):
            self.assertNotIn(value.encode("ascii"), raw)


if __name__ == "__main__":
    unittest.main()
