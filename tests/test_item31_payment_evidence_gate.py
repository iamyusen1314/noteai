import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import internal_deployment_readiness_gate as gate


class Item31PaymentEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ref = gate.ITEM31_PAYMENT_EVIDENCE
        sides = [
            "internal_order",
            "provider_payment",
            "callback",
            "payment_ledger",
            "entitlement",
            "provider_refund",
            "refunded_state",
            "duplicate_no_replay",
        ]
        def digest(value):
            return hashlib.sha256(value.encode("utf-8")).hexdigest()

        providers = []
        provider_write_readbacks = []
        for name in sorted(gate.ITEM31_DIRECT_PROVIDERS):
            approval_path = (
                f"deploy/production/evidence/{name}-merchant-approval.json"
            )
            artifact = self.root / approval_path
            artifact.parent.mkdir(parents=True, exist_ok=True)
            approval_payload = {
                "schema": gate.ITEM31_MERCHANT_APPROVAL_SCHEMA,
                "provider": name,
                "status": "APPROVED",
                "approved_at": "2026-09-06T12:00:00+08:00",
                "merchant_identity_sha256": digest(f"{name}:merchant"),
                "application_identity_sha256": digest(f"{name}:application"),
                "product_capabilities": [
                    "payment_create",
                    "asynchronous_callback",
                    "full_refund",
                    "bill_reconciliation",
                ],
                "official_readback_sha256": digest(f"{name}:approval-readback"),
                "secret_values_recorded": False,
            }
            artifact.write_text(json.dumps(approval_payload), encoding="utf-8")
            payment = {
                "create_result": "SUCCEEDED",
                "callback_result": "SUCCEEDED",
                "signature_verification": "VERIFIED",
                "signature_scheme": (
                    "WECHATPAY2-SHA256-RSA2048"
                    if name == "wechatpay_direct"
                    else "RSA2"
                ),
                "internal_status": "paid",
                "entitlement_mutation_count": 1,
                "duplicate_callback_count": 1,
                "duplicate_entitlement_mutation_count": 0,
                **{
                    field: digest(f"{name}:{field}")
                    for field in (
                        "provider_payment_identity_sha256",
                        "callback_identity_sha256",
                        "create_request_sha256",
                        "create_response_sha256",
                        "signature_input_sha256",
                        "callback_payload_sha256",
                        "ledger_readback_sha256",
                    )
                },
            }
            refund = {
                "create_result": "SUCCEEDED",
                "provider_status": "refunded",
                "internal_status": "refunded",
                "amount_fen": gate.ITEM31_CANARY_AMOUNT_FEN,
                "full_refund": True,
                "provider_refund_identity_sha256": digest(f"{name}:refund"),
                "request_sha256": digest(f"{name}:refund-request"),
                "response_sha256": digest(f"{name}:refund-response"),
            }
            reconciliation = {
                "status": "MATCHED",
                "matched_sides": sides,
                "discrepancy_count": 0,
                "readback_sha256": digest(f"{name}:reconciliation"),
            }
            write_mutations = {
                table: 1 for table in sorted(gate.ITEM31_REQUIRED_WRITE_TABLES)
            }
            write_readback = digest(f"{name}:write-readback")
            provider_write_readbacks.append(write_readback)
            canary_path = (
                f"deploy/production/evidence/{name}-canary-audit.json"
            )
            canary_payload = {
                "schema": gate.ITEM31_CANARY_AUDIT_SCHEMA,
                "provider": name,
                "environment": "LIVE",
                "canary_identity_sha256": digest(f"{name}:canary"),
                "started_at": "2026-09-07T10:00:00+08:00",
                "finished_at": "2026-09-07T10:05:00+08:00",
                "payment_amount_fen": gate.ITEM31_CANARY_AMOUNT_FEN,
                "payment": payment,
                "refund": refund,
                "reconciliation": reconciliation,
                "write_mutations_by_table": write_mutations,
                "write_ledger_readback_sha256": write_readback,
                "secret_values_recorded": False,
                "raw_provider_identifiers_recorded": False,
            }
            canary_artifact = self.root / canary_path
            canary_artifact.write_text(
                json.dumps(canary_payload), encoding="utf-8"
            )
            providers.append(
                {
                    "name": name,
                    "environment": "LIVE",
                    "synthetic_user": False,
                    "synthetic_order": False,
                    "real_user_order": True,
                    "payment_amount_fen": gate.ITEM31_CANARY_AMOUNT_FEN,
                    "started_at": "2026-09-07T10:00:00+08:00",
                    "finished_at": "2026-09-07T10:05:00+08:00",
                    "provider_operation_count": gate.ITEM31_PROVIDER_OPERATION_COUNT,
                    "automatic_retry_count": 0,
                    "outcome_unknown_count": 0,
                    "canary_identity_sha256": digest(f"{name}:canary"),
                    "merchant_approval": {
                        "status": "VERIFIED",
                        "approved_at": "2026-09-06T12:00:00+08:00",
                        "artifact_path": approval_path,
                        "artifact_sha256": hashlib.sha256(
                            artifact.read_bytes()
                        ).hexdigest(),
                    },
                    "payment": payment,
                    "refund": refund,
                    "reconciliation": reconciliation,
                    "canary_audit_ref": canary_path,
                    "canary_audit_sha256": hashlib.sha256(
                        canary_artifact.read_bytes()
                    ).hexdigest(),
                }
            )

        self.payload = {
            "schema": gate.ITEM31_PAYMENT_EVIDENCE_SCHEMA,
            "item": 31,
            "status": "VERIFIED",
            "readiness_credit": True,
            "environment": "LIVE",
            "observed_at": "2026-09-07T12:00:00+08:00",
            "pingxx_readiness_credit": 0,
            "providers": providers,
            "cumulative_payment_fen": (
                gate.ITEM31_CANARY_AMOUNT_FEN * len(gate.ITEM31_DIRECT_PROVIDERS)
            ),
            "cumulative_refund_fen": (
                gate.ITEM31_CANARY_AMOUNT_FEN * len(gate.ITEM31_DIRECT_PROVIDERS)
            ),
            "net_real_funds_fen": 0,
            "owner_over_20_cny_approval": False,
            "actual_production_write_set": {
                "tables": sorted(gate.ITEM31_REQUIRED_WRITE_TABLES),
                "row_mutations_by_table": {
                    table: len(gate.ITEM31_DIRECT_PROVIDERS) for table in sorted(gate.ITEM31_REQUIRED_WRITE_TABLES)
                },
                "ledger_readback_sha256": hashlib.sha256(
                    json.dumps(
                        sorted(provider_write_readbacks),
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "out_of_contract_row_mutations": 0,
            },
            "secret_values_recorded": False,
            "raw_provider_identifiers_recorded": False,
        }
        path = self.root / self.ref
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.control = {
            "evidence": [{"kind": "path", "ref": self.ref}]
        }

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        return gate.validate_item31_payment_evidence(
            self.control,
            root=self.root,
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )

    def test_accepts_approved_wechat_owner_live_full_refund_chain(self):
        self.assertEqual(self.validate(), [])

    def test_requires_each_starter_credit_write_table(self):
        base_payload = json.loads(json.dumps(self.payload))
        base_audits = {}
        for provider in base_payload["providers"]:
            path = self.root / provider["canary_audit_ref"]
            base_audits[provider["name"]] = json.loads(
                path.read_text(encoding="utf-8")
            )
        for table in (
            "credits",
            "credit_transactions",
            "payment_credit_positions",
        ):
            with self.subTest(table=table):
                self.payload = json.loads(json.dumps(base_payload))
                for provider in self.payload["providers"]:
                    audit_path = self.root / provider["canary_audit_ref"]
                    audit = json.loads(
                        json.dumps(base_audits[provider["name"]])
                    )
                    audit["write_mutations_by_table"].pop(table)
                    audit_path.write_text(json.dumps(audit), encoding="utf-8")
                    provider["canary_audit_sha256"] = hashlib.sha256(
                        audit_path.read_bytes()
                    ).hexdigest()
                writes = self.payload["actual_production_write_set"]
                writes["tables"].remove(table)
                writes["row_mutations_by_table"].pop(table)
                errors = self.validate()
                self.assertIn(
                    "Item31 provider canary audit binding mismatch",
                    errors,
                )
                self.assertIn(
                    "Item31 production write-set evidence invalid",
                    errors,
                )

    def test_rejects_nonpositive_or_noninteger_write_counts(self):
        provider = self.payload["providers"][0]
        audit_path = self.root / provider["canary_audit_ref"]
        base_audit = json.loads(audit_path.read_text(encoding="utf-8"))
        invalid_counts = (0, -1, True, 1.5)
        for count in invalid_counts:
            with self.subTest(count=count):
                audit = json.loads(json.dumps(base_audit))
                audit["write_mutations_by_table"]["credit_transactions"] = count
                audit_path.write_text(json.dumps(audit), encoding="utf-8")
                provider["canary_audit_sha256"] = hashlib.sha256(
                    audit_path.read_bytes()
                ).hexdigest()
                self.assertIn(
                    "Item31 provider canary audit binding mismatch",
                    self.validate(),
                )

    def test_rejects_provider_and_terminal_write_count_mismatch(self):
        self.payload["actual_production_write_set"][
            "row_mutations_by_table"
        ]["credit_transactions"] = 3
        self.assertIn(
            "Item31 production write-set evidence invalid",
            self.validate(),
        )

    def test_rejects_unknown_write_table(self):
        provider = self.payload["providers"][0]
        audit_path = self.root / provider["canary_audit_ref"]
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["write_mutations_by_table"]["unknown_payment_table"] = 1
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        provider["canary_audit_sha256"] = hashlib.sha256(
            audit_path.read_bytes()
        ).hexdigest()
        self.assertIn(
            "Item31 provider canary audit binding mismatch",
            self.validate(),
        )

    def test_rejects_test_or_missing_approved_provider_credit(self):
        self.payload["environment"] = "TEST"
        self.payload["providers"].pop()
        self.payload["cumulative_payment_fen"] = gate.ITEM31_CANARY_AMOUNT_FEN
        errors = self.validate()
        self.assertIn("Item31 direct Live terminal status mismatch", errors)
        self.assertIn(
            "Item31 requires the approved WeChat Native provider exactly once",
            errors,
        )

    def test_rejects_noncanonical_amount_without_requesting_unneeded_over_20_approval(self):
        provider = self.payload["providers"][0]
        provider["payment_amount_fen"] = 1
        self.payload["owner_over_20_cny_approval"] = False
        errors = self.validate()
        self.assertIn("Item31 bounded provider canary mismatch", errors)
        self.assertNotIn("Item31 over-CNY20 authorization missing", errors)

    def test_requires_exact_provider_operation_count(self):
        for count in (1, 4, 6, 10):
            with self.subTest(count=count):
                self.payload["providers"][0]["provider_operation_count"] = count
                self.assertIn(
                    "Item31 bounded provider canary mismatch",
                    self.validate(),
                )

    def test_rejects_bool_counts_and_malformed_collections_without_crashing(self):
        self.payload["providers"][0]["payment"]["duplicate_callback_count"] = True
        self.payload["providers"][0]["reconciliation"]["matched_sides"] = [
            []
        ]
        self.payload["actual_production_write_set"]["tables"] = [[]]
        errors = self.validate()
        self.assertIn(
            "Item31 payment/callback exactly-once proof mismatch",
            errors,
        )
        self.assertIn("Item31 direct-provider reconciliation mismatch", errors)
        self.assertIn("Item31 production write-set evidence invalid", errors)

    def test_rejects_unbound_merchant_and_provider_receipt_hashes(self):
        self.payload["providers"][0]["merchant_approval"][
            "artifact_sha256"
        ] = "0" * 64
        self.payload["providers"][0]["payment"][
            "provider_payment_identity_sha256"
        ] = self.payload["providers"][0]["payment"][
            "callback_identity_sha256"
        ]
        errors = self.validate()
        self.assertIn("Item31 merchant/product approval binding missing", errors)
        self.assertIn(
            "Item31 payment/callback exactly-once proof mismatch",
            errors,
        )

    def test_rejects_provider_swapped_approval_and_canary_artifact(self):
        first = self.payload["providers"][0]
        approval_path = self.root / first["merchant_approval"]["artifact_path"]
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval["provider"] = "alipay_direct"
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
        first["merchant_approval"]["artifact_sha256"] = hashlib.sha256(approval_path.read_bytes()).hexdigest()
        canary_path = self.root / first["canary_audit_ref"]
        canary = json.loads(canary_path.read_text(encoding="utf-8"))
        canary["provider"] = "alipay_direct"
        canary_path.write_text(json.dumps(canary), encoding="utf-8")
        first["canary_audit_sha256"] = hashlib.sha256(
            canary_path.read_bytes()
        ).hexdigest()
        errors = self.validate()
        self.assertIn("Item31 merchant/product approval binding missing", errors)
        self.assertIn("Item31 provider canary audit binding mismatch", errors)

    def test_rejects_collapsed_semantic_hashes_and_write_ledger_mismatch(self):
        provider = self.payload["providers"][0]
        repeated = "f" * 64
        for key in (
            "provider_payment_identity_sha256",
            "callback_identity_sha256",
            "create_request_sha256",
            "create_response_sha256",
            "signature_input_sha256",
            "callback_payload_sha256",
            "ledger_readback_sha256",
        ):
            provider["payment"][key] = repeated
        self.payload["actual_production_write_set"]["row_mutations_by_table"][
            "payment_orders"
        ] = 99
        errors = self.validate()
        self.assertIn(
            "Item31 payment/callback exactly-once proof mismatch",
            errors,
        )
        self.assertIn("Item31 semantic proof identities must be distinct", errors)
        self.assertIn("Item31 production write-set evidence invalid", errors)

    def test_rejects_sensitive_or_unknown_terminal_fields(self):
        self.payload["private_key"] = "synthetic-test-only"
        errors = self.validate()
        self.assertIn("Item31 terminal evidence schema mismatch", errors)
        self.assertIn("Item31 sensitive field present", errors)

    def test_rejects_float_control_numbers(self):
        self.payload["item"] = 31.0
        self.payload["pingxx_readiness_credit"] = 0.0
        self.assertIn("Item31 direct Live terminal status mismatch", self.validate())


if __name__ == "__main__":
    unittest.main()
