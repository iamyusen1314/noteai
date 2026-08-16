import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import extract_item26_cost_containment_abort_raw_v1 as extractor  # noqa: E402
import verify_item26_cost_containment_abort_authority_v1 as authority  # noqa: E402


REVISION = "8" * 40
REGION = "cn-shenzhen"
CLONE = "rm-authority-clone-secret-id"
SOURCE = "rm-authority-source-secret-id"
PREBOUND_IDEMPOTENCY_MARKER = "prebound-client-token"
NONCE_SHA256 = hashlib.sha256(b"confirmation-nonce").hexdigest()


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


def inner(value):
    return base64.b64encode(canonical(value)).decode("ascii")


def record(sequence, slot, operation, request, response):
    return {
        "sequence": sequence,
        "slot": slot,
        "operation": operation,
        "region_id": REGION,
        "started_at_utc": f"2026-08-16T00:00:0{sequence}Z",
        "completed_at_utc": f"2026-08-16T00:00:0{sequence}Z",
        "transport_outcome": extractor.TRANSPORT_RESPONSE_RECEIVED,
        "http_status": 200,
        "request_json_base64": inner(request),
        "response_json_base64": inner(response),
    }


def rds_request(instance_id):
    return {
        "Action": "DescribeDBInstances",
        "Version": "2014-08-15",
        "RegionId": REGION,
        "DBInstanceId": instance_id,
        "PageNumber": 1,
        "PageSize": 100,
    }


def rds_instance(instance_id, pay_type, protected):
    return {
        "DBInstanceId": instance_id,
        "DBInstanceStatus": "Running",
        "PayType": pay_type,
        "Engine": "PostgreSQL",
        "EngineVersion": "16.0",
        "DeletionProtection": protected,
        "VpcId": "vpc-root-only",
        "VSwitchId": "vsw-root-only",
        "ZoneId": "cn-shenzhen-e",
    }


def rds_response(instance, request_id):
    values = [instance]
    return {
        "RequestId": request_id,
        "PageNumber": 1,
        "PageRecordCount": 1,
        "TotalRecordCount": 1,
        "Items": {"DBInstance": values},
    }


def billing_request():
    return {
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


def billing_response(gross="185.658", seconds="331200"):
    return {
        "Code": "Success",
        "Success": True,
        "RequestId": "billing-request-id",
        "Data": {
            "PageNum": 1,
            "BillingCycle": "2026-08",
            "PageSize": 300,
            "TotalCount": 1,
            "Items": {
                "Item": [
                    {
                        "InstanceID": CLONE,
                        "Currency": "CNY",
                        "SubscriptionType": "PayAsYouGo",
                        "ProductCode": "rds",
                        "PipCode": "rds",
                        "ServicePeriod": seconds,
                        "ServicePeriodUnit": "Seconds",
                        "PretaxGrossAmount": gross,
                    }
                ]
            },
        },
    }


def preflight_raw(*, source_pay_type="Prepaid", gross="185.658"):
    records = [
        record(
            1,
            "clone_preflight",
            "DescribeDBInstances",
            rds_request(CLONE),
            rds_response(
                rds_instance(CLONE, "Postpaid", True), "clone-request-id"
            ),
        ),
        record(
            2,
            "source_preflight",
            "DescribeDBInstances",
            rds_request(SOURCE),
            rds_response(
                rds_instance(SOURCE, source_pay_type, True), "source-request-id"
            ),
        ),
        record(
            3,
            "billing_preflight",
            "QueryInstanceBill",
            billing_request(),
            billing_response(gross=gross),
        ),
    ]
    return canonical(
        {
            "schema": extractor.CAPTURE_SCHEMA,
            "task_id": extractor.TASK_ID,
            "operation_id": extractor.OPERATION_ID,
            "phase": "PREFLIGHT",
            "source_revision": REVISION,
            "observed_at_utc": "2026-08-16T00:00:03Z",
            "records": records,
        }
    )


def key_row(label):
    key = (
        "-----BEGIN PUBLIC KEY-----\n"
        + base64.b64encode(label.encode("ascii")).decode("ascii")
        + "\n-----END PUBLIC KEY-----\n"
    ).encode("ascii")
    spki = hashlib.sha256((label + "-spki").encode("ascii")).hexdigest()
    return {
        "issuer": label + "-issuer",
        "audience": label + "-audience",
        "public_key_pem_base64": base64.b64encode(key).decode("ascii"),
        "public_key_sha256": hashlib.sha256(key).hexdigest(),
        "public_key_spki_sha256": spki,
    }


def envelope(authority_name, key, payload):
    return {
        "schema": authority.ENVELOPE_SCHEMA,
        "authority": authority_name,
        "issuer": key["issuer"],
        "audience": key["audience"],
        "payload": payload,
        "signature_base64": base64.b64encode(b"test-signature").decode("ascii"),
    }


def fixture(*, source_pay_type="Prepaid", gross="185.658"):
    plan = {
        "schema": authority.PLAN_SCHEMA,
        "task_id": authority.TASK_ID,
        "operation_id": authority.OPERATION_ID,
        "execution_revision": REVISION,
        "region_id": REGION,
        "clone_instance_id": CLONE,
        "source_instance_id": SOURCE,
        "preflight_slots": {
            "clone": "clone_preflight",
            "source": "source_preflight",
            "billing": "billing_preflight",
        },
        "billing_cycle": "2026-08",
        "release_billing_contract_ref": authority.RELEASE_CONTRACT_REF,
        "release_billing_contract_sha256": authority.RELEASE_CONTRACT_SHA256,
        "recorded_minimum_pretax_gross_cny": "185.658",
        "recorded_minimum_service_seconds": 331200,
        "approved_24h_ceiling_cny": "76.824",
        "protection_disable_client_token": PREBOUND_IDEMPOTENCY_MARKER,
        "planned_mutations": [
            {
                "sequence": 1,
                "operation": "ModifyDBInstanceDeletionProtection",
                "request": {
                    "Action": "ModifyDBInstanceDeletionProtection",
                    "Version": "2014-08-15",
                    "RegionId": REGION,
                    "DBInstanceId": CLONE,
                    "DeletionProtection": False,
                    "ClientToken": PREBOUND_IDEMPOTENCY_MARKER,
                },
            },
            {
                "sequence": 2,
                "operation": "DeleteDBInstance",
                "request": {
                    "Action": "DeleteDBInstance",
                    "Version": "2014-08-15",
                    "RegionId": REGION,
                    "DBInstanceId": CLONE,
                },
            },
        ],
        "new_paid_resource_allowed": False,
        "database_connection_allowed": False,
        "readiness_credit_allowed": False,
        "partial_state_policy": "STOP_NO_RESUME_V1",
        "plan_sha256": "",
    }
    plan["plan_sha256"] = authority.plan_sha256(plan)
    plan_raw = canonical(plan)
    capture_raw = preflight_raw(source_pay_type=source_pay_type, gross=gross)
    capture = extractor.parse_capture(capture_raw, expected_phase="PREFLIGHT")
    clone = extractor.project_rds_inventory(
        capture,
        slot="clone_preflight",
        region_id=REGION,
        instance_id=CLONE,
        expected_count=1,
    )
    source = extractor.project_rds_inventory(
        capture,
        slot="source_preflight",
        region_id=REGION,
        instance_id=SOURCE,
        expected_count=1,
    )
    billing = extractor.project_instance_bill(
        capture,
        slot="billing_preflight",
        instance_id=CLONE,
        billing_cycle="2026-08",
    )
    state = {
        "schema": authority.STATE_SCHEMA,
        "task_id": authority.TASK_ID,
        "operation_id": authority.OPERATION_ID,
        "execution_revision": REVISION,
        "confirmation_nonce_sha256": NONCE_SHA256,
        "state": "FRESH_NO_INTENT",
        "consumed_nonce_count": 0,
        "mutation_intent_count": 0,
        "mutation_result_count": 0,
        "partial_state_count": 0,
        "automatic_retry_allowed": False,
    }
    state_raw = canonical(state)
    provider_key = key_row("provider")
    confirmation_key = key_row("confirmation")
    ci_key = key_row("ci")
    controls = [
        {"path": ref, "sha256": hashlib.sha256(ref.encode("ascii")).hexdigest()}
        for ref in authority.CONTROL_SOURCE_REFS
    ]
    root_value = {
        "schema": authority.ROOT_SCHEMA,
        "task_id": authority.TASK_ID,
        "operation_id": authority.OPERATION_ID,
        "status": "FROZEN_BEFORE_ABORT_EXECUTION",
        "repository": authority.REPOSITORY,
        "source_ref": authority.SOURCE_REF,
        "frozen_before_revision": authority.ANCHOR_REVISION,
        "release_billing_contract_ref": authority.RELEASE_CONTRACT_REF,
        "release_billing_contract_sha256": authority.RELEASE_CONTRACT_SHA256,
        "no_replay_registry_ref": authority.NO_REPLAY_REGISTRY_REF,
        "no_replay_registry_sha256": authority.NO_REPLAY_REGISTRY_SHA256,
        "control_sources": controls,
        "provider": provider_key,
        "confirmation": confirmation_key,
        "ci": ci_key,
        "partial_state_policy": "STOP_NO_RESUME_V1",
    }
    root_raw = canonical(root_value)
    root_sha = hashlib.sha256(root_raw).hexdigest()
    def ci_run(event, label):
        return {
            "event": event,
            "head_sha": REVISION,
            "attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "job_count": 1,
            "failed_step_count": 0,
            "run_id_sha256": hashlib.sha256((label + "-run").encode("ascii")).hexdigest(),
            "job_id_sha256": hashlib.sha256((label + "-job").encode("ascii")).hexdigest(),
            "unit_test_count": 2250,
            "postgres_test_count": 6,
            "readiness_check_count": 138,
            "error_annotation_count": 0,
        }
    ci_payload = {
        "schema": authority.EXECUTION_CI_SCHEMA,
        "task_id": authority.TASK_ID,
        "operation_id": authority.OPERATION_ID,
        "execution_revision": REVISION,
        "authority_root_file_sha256": root_sha,
        "repository": authority.REPOSITORY,
        "ref": authority.SOURCE_REF,
        "control_sources": controls,
        "execution_push": ci_run("push", "push"),
        "execution_pull_request": ci_run("pull_request", "pull-request"),
    }
    ci_envelope = envelope("ci", ci_key, ci_payload)
    provider_payload = {
        "schema": authority.PROVIDER_PREFLIGHT_SCHEMA,
        "task_id": authority.TASK_ID,
        "operation_id": authority.OPERATION_ID,
        "execution_revision": REVISION,
        "authority_root_file_sha256": root_sha,
        "preflight_raw_file_sha256": hashlib.sha256(capture_raw).hexdigest(),
        "plan_file_sha256": hashlib.sha256(plan_raw).hexdigest(),
        "plan_sha256": plan["plan_sha256"],
        "state_manifest_file_sha256": hashlib.sha256(state_raw).hexdigest(),
        "execution_ci_semantic_sha256": authority._semantic(ci_payload),
        "observed_at_utc": capture.observed_at_utc,
        "clone_projection_sha256": authority._semantic(clone),
        "source_projection_sha256": authority._semantic(source),
        "billing_projection_sha256": authority._semantic(billing),
        "release_billing_contract_sha256": authority.RELEASE_CONTRACT_SHA256,
        "no_replay_registry_sha256": authority.NO_REPLAY_REGISTRY_SHA256,
    }
    provider_envelope = envelope("provider", provider_key, provider_payload)
    confirmation_payload = {
        "schema": authority.CONFIRMATION_SCHEMA,
        "task_id": authority.TASK_ID,
        "operation_id": authority.OPERATION_ID,
        "execution_revision": REVISION,
        "authority_root_file_sha256": root_sha,
        "provider_preflight_semantic_sha256": authority._semantic(provider_payload),
        "preflight_raw_file_sha256": hashlib.sha256(capture_raw).hexdigest(),
        "plan_file_sha256": hashlib.sha256(plan_raw).hexdigest(),
        "plan_sha256": plan["plan_sha256"],
        "state_manifest_file_sha256": hashlib.sha256(state_raw).hexdigest(),
        "execution_ci_semantic_sha256": authority._semantic(ci_payload),
        "confirmation_nonce_sha256": NONCE_SHA256,
        "approved_at_utc": "2026-08-16T00:00:04Z",
        "expires_at_utc": "2026-08-16T00:10:04Z",
        "allowed_mutations": [
            "ModifyDBInstanceDeletionProtection",
            "DeleteDBInstance",
        ],
        "new_paid_resource_allowed": False,
        "database_connection_allowed": False,
        "readiness_credit_allowed": False,
        "partial_state_policy": "STOP_NO_RESUME_V1",
    }
    confirmation_envelope = envelope(
        "confirmation", confirmation_key, confirmation_payload
    )
    files = {
        "authority-root-v1.json": root_raw,
        "preflight-raw-v1.json": capture_raw,
        "exact-plan-v1.json": plan_raw,
        "state-manifest-v1.json": state_raw,
        "provider-preflight-envelope-v1.json": canonical(provider_envelope),
        "execution-ci-envelope-v1.json": canonical(ci_envelope),
        "confirmation-envelope-v1.json": canonical(confirmation_envelope),
    }
    return files, root_sha, controls


class Item26AbortAuthorityTests(unittest.TestCase):
    def validate(self, files, root_sha, controls):
        spki = {
            "provider": key_row("provider")["public_key_spki_sha256"],
            "confirmation": key_row("confirmation")["public_key_spki_sha256"],
            "ci": key_row("ci")["public_key_spki_sha256"],
        }

        def fake_spki(key):
            for label in spki:
                if base64.b64encode(label.encode("ascii")) in key:
                    return (label + "-spki").encode("ascii")
            return b"unknown-spki"

        with (
            mock.patch.object(authority, "load_root_owned_preaction", return_value=files),
            mock.patch.object(authority, "_strict_ancestor", return_value=True),
            mock.patch.object(
                authority,
                "_git_blob_sha256",
                side_effect=lambda _revision, ref, root: next(
                    row["sha256"] for row in controls if row["path"] == ref
                ),
            ),
            mock.patch.object(
                authority,
                "_current_control_source_sha256",
                side_effect=lambda ref, root: next(
                    row["sha256"] for row in controls if row["path"] == ref
                ),
            ),
            mock.patch.object(
                authority,
                "_now_utc",
                return_value=datetime(
                    2026, 8, 16, 0, 0, 5, tzinfo=timezone.utc
                ),
            ),
            mock.patch.object(authority, "_canonical_spki_der", side_effect=fake_spki),
            mock.patch.object(authority, "_verify_signature", return_value=True),
        ):
            return authority.validate_preaction_authority(
                expected_authority_root_file_sha256=root_sha,
                expected_execution_revision=REVISION,
                root=ROOT,
            )

    def test_valid_preaction_is_secret_free_and_exact(self):
        files, root_sha, controls = fixture()
        errors, binding = self.validate(files, root_sha, controls)
        self.assertEqual(errors, [])
        self.assertTrue(binding["fresh_no_intent"])
        self.assertEqual(
            binding["dispatch_scope"],
            "EXACT_CLONE_PROTECTION_DISABLE_AND_DELETE_ONLY",
        )
        rendered = json.dumps(binding)
        self.assertNotIn(CLONE, rendered)
        self.assertNotIn(SOURCE, rendered)
        self.assertNotIn(PREBOUND_IDEMPOTENCY_MARKER, rendered)

    def test_source_must_remain_prepaid(self):
        files, root_sha, controls = fixture(source_pay_type="Postpaid")
        errors, binding = self.validate(files, root_sha, controls)
        self.assertIsNone(binding)
        self.assertTrue(any("preflight_state" in error for error in errors))

    def test_billing_must_not_drop_below_recorded_baseline(self):
        files, root_sha, controls = fixture(gross="80")
        errors, binding = self.validate(files, root_sha, controls)
        self.assertIsNone(binding)
        self.assertTrue(any("preflight_state" in error for error in errors))

    def test_confirmation_cannot_expand_mutations(self):
        files, root_sha, controls = fixture()
        envelope_value = json.loads(files["confirmation-envelope-v1.json"])
        envelope_value["payload"]["allowed_mutations"].append("DeleteVSwitch")
        files["confirmation-envelope-v1.json"] = canonical(envelope_value)
        errors, binding = self.validate(files, root_sha, controls)
        self.assertIsNone(binding)
        self.assertTrue(any("confirmation_payload" in error for error in errors))

    def test_execution_ci_must_be_attempt_one_green(self):
        files, root_sha, controls = fixture()
        ci = json.loads(files["execution-ci-envelope-v1.json"])
        ci["payload"]["execution_push"]["attempt"] = 2
        files["execution-ci-envelope-v1.json"] = canonical(ci)
        errors, binding = self.validate(files, root_sha, controls)
        self.assertIsNone(binding)
        self.assertTrue(
            any(
                token in error
                for error in errors
                for token in ("provider_preflight_payload", "execution_ci_run")
            )
        )

    def test_consumed_nonce_fails(self):
        files, root_sha, controls = fixture()
        state = json.loads(files["state-manifest-v1.json"])
        state["state"] = "NONCE_CONSUMED"
        state["consumed_nonce_count"] = 1
        state_raw = canonical(state)
        files["state-manifest-v1.json"] = state_raw
        errors, binding = self.validate(files, root_sha, controls)
        self.assertIsNone(binding)
        self.assertTrue(
            any(
                token in error
                for error in errors
                for token in ("provider_preflight_payload", "state_identity")
            )
        )

    def test_wrong_root_hash_fails(self):
        files, _root_sha, controls = fixture()
        errors, binding = self.validate(files, "f" * 64, controls)
        self.assertIsNone(binding)
        self.assertTrue(any("root_identity" in error for error in errors))

    def test_exact_plan_target_drift_fails(self):
        files, root_sha, controls = fixture()
        plan = json.loads(files["exact-plan-v1.json"])
        plan["planned_mutations"][1]["request"]["DBInstanceId"] = SOURCE
        plan["plan_sha256"] = authority.plan_sha256(plan)
        files["exact-plan-v1.json"] = canonical(plan)
        errors, binding = self.validate(files, root_sha, controls)
        self.assertIsNone(binding)
        self.assertTrue(any("plan_identity" in error for error in errors))

    def test_default_incomplete_inputs_fail_without_reading(self):
        with mock.patch.object(
            authority,
            "load_root_owned_preaction",
            side_effect=AssertionError("must not read"),
        ):
            errors, binding = authority.validate_preaction_authority(
                expected_authority_root_file_sha256="",
                expected_execution_revision=REVISION,
            )
        self.assertIsNone(binding)
        self.assertIn("not finalized", errors[0])

    def test_loader_rejects_extra_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            os.chmod(base, 0o700)
            with mock.patch.object(authority, "ROOT_UID", os.getuid()):
                for name in authority.PREACTION_FILES:
                    path = base / name
                    path.write_bytes(b"{}\n")
                    os.chmod(path, 0o600)
                loaded = authority.load_root_owned_preaction(base)
                self.assertEqual(set(loaded), set(authority.PREACTION_FILES))
                extra = base / "extra"
                extra.write_bytes(b"x")
                os.chmod(extra, 0o600)
                with self.assertRaisesRegex(authority.AuthorityError, "inventory"):
                    authority.load_root_owned_preaction(base)
                extra.unlink()
                target = base / authority.PREACTION_FILES[0]
                target.unlink()
                target.symlink_to(base / authority.PREACTION_FILES[1])
                with self.assertRaises(authority.AuthorityError):
                    authority.load_root_owned_preaction(base)

    def test_loader_rejects_hardlink(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            os.chmod(base, 0o700)
            with mock.patch.object(authority, "ROOT_UID", os.getuid()):
                for name in authority.PREACTION_FILES:
                    path = base / name
                    path.write_bytes(b"{}\n")
                    os.chmod(path, 0o600)
                alias = base.parent / (base.name + "-alias")
                os.link(base / authority.PREACTION_FILES[0], alias)
                try:
                    with self.assertRaisesRegex(authority.AuthorityError, "file_identity"):
                        authority.load_root_owned_preaction(base)
                finally:
                    alias.unlink()


if __name__ == "__main__":
    unittest.main()
