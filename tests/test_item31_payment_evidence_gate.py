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

    def live_approval(self):
        item = self.payload["providers"][0]
        binding = item["merchant_approval"]
        path = self.root / binding["artifact_path"]
        approval = json.loads(path.read_text(encoding="utf-8"))
        approval.pop("official_readback_sha256")
        approval.update(
            status="VERIFIED",
            approved_at=None,
            verification_basis="AUTHENTICATED_LIVE_CAPABILITIES",
            verified_at="2026-09-07T11:00:00+08:00",
            configuration_readback_sha256=hashlib.sha256(b"synthetic-config-readback").hexdigest(),
            capability_proofs={
                "payment_create": item["payment"]["create_response_sha256"],
                "asynchronous_callback": item["payment"]["callback_payload_sha256"],
                "full_refund": item["refund"]["response_sha256"],
                "bill_reconciliation": item["reconciliation"]["readback_sha256"],
            },
        )
        binding.update(
            approved_at=None,
            verification_basis=approval["verification_basis"],
            verified_at=approval["verified_at"],
        )
        self.save_approval(approval)
        return item, approval

    def save_approval(self, approval):
        binding = self.payload["providers"][0]["merchant_approval"]
        path = self.root / binding["artifact_path"]
        path.write_text(json.dumps(approval), encoding="utf-8")
        binding["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_accepts_live_capabilities_without_inventing_approval_date(self):
        item, approval = self.live_approval()
        self.assertIsNone(approval["approved_at"])
        self.assertIsNone(item["merchant_approval"]["approved_at"])
        self.assertEqual(self.validate(), [])

    def test_live_capabilities_require_each_same_item_proof(self):
        _, approval = self.live_approval()
        original = dict(approval["capability_proofs"])
        for capability in original:
            for wrong in (None, "0" * 64):
                with self.subTest(capability=capability, wrong=wrong):
                    approval["capability_proofs"] = dict(original)
                    if wrong is None:
                        approval["capability_proofs"].pop(capability)
                    else:
                        approval["capability_proofs"][capability] = wrong
                    self.save_approval(approval)
                    self.assertIn("Item31 merchant/product approval binding missing", self.validate())

    def test_live_capabilities_require_completed_observation_not_forged_approval(self):
        item, approval = self.live_approval()
        binding = item["merchant_approval"]
        original = json.loads(json.dumps(approval))
        for at in ("2026-09-07T10:04:00+08:00", "2026-09-07T12:01:00+08:00", "2026-09-07T11:00:00"):
            with self.subTest(verified_at=at):
                approval = dict(original, verified_at=at)
                binding["verified_at"] = at
                self.save_approval(approval)
                self.assertIn("Item31 merchant/product approval binding missing", self.validate())
        binding["verified_at"] = original["verified_at"]
        for target in ("binding", "artifact"):
            with self.subTest(approved_at=target):
                approval = dict(original)
                binding["approved_at"] = None
                (binding if target == "binding" else approval)["approved_at"] = "2026-09-06T12:00:00+08:00"
                self.save_approval(approval)
                self.assertIn("Item31 merchant/product approval binding missing", self.validate())
        binding["approved_at"] = None
        approval = dict(original, verified_at="2026-09-07T11:01:00+08:00")
        self.save_approval(approval)
        self.assertIn("Item31 merchant/product approval binding missing", self.validate())

    def test_live_capabilities_require_config_identity_and_exact_provider_shape(self):
        _, approval = self.live_approval()
        original = json.loads(json.dumps(approval))
        for field, value in (
            ("merchant_identity_sha256", None),
            ("application_identity_sha256", ""),
            ("configuration_readback_sha256", None),
            ("provider", "alipay_direct"),
            ("verification_basis", "OWNER_CONFIRMED"),
            ("unreviewed_field", True),
        ):
            with self.subTest(field=field):
                approval = dict(original)
                if value is None:
                    approval.pop(field)
                else:
                    approval[field] = value
                self.save_approval(approval)
                self.assertIn("Item31 merchant/product approval binding missing", self.validate())

    def test_live_capabilities_do_not_accept_failed_or_unauthenticated_operations(self):
        item, _ = self.live_approval()
        for section, field, wrong in (
            ("payment", "create_result", "UNKNOWN"),
            ("payment", "callback_result", "FAILED"),
            ("payment", "signature_verification", "UNKNOWN"),
            ("payment", "signature_scheme", "RSA2"),
            ("refund", "provider_status", "pending"),
            ("refund", "full_refund", False),
            ("reconciliation", "status", "MISMATCH"),
            ("reconciliation", "discrepancy_count", 1),
        ):
            with self.subTest(section=section, field=field):
                original = item[section][field]
                item[section][field] = wrong
                self.assertIn("Item31 merchant/product approval binding missing", self.validate())
                item[section][field] = original

    def test_live_capabilities_keep_original_accounting_and_dml_requirements(self):
        item, _ = self.live_approval()
        item["provider_operation_count"] = 6
        self.payload["net_real_funds_fen"] = 1
        self.payload["actual_production_write_set"]["out_of_contract_row_mutations"] = 1
        errors = self.validate()
        self.assertIn("Item31 bounded provider canary mismatch", errors)
        self.assertIn("Item31 cumulative full-refund amount mismatch", errors)
        self.assertIn("Item31 production write-set evidence invalid", errors)

    def save_canary(self, canary):
        item = self.payload["providers"][0]
        path = self.root / item["canary_audit_ref"]
        path.write_text(json.dumps(canary), encoding="utf-8")
        item["canary_audit_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def capture_manifest(self):
        item, _ = self.live_approval()
        item["payment"]["internal_status"] = "succeeded"
        canary = json.loads((self.root / item["canary_audit_ref"]).read_bytes())
        canary["payment"] = dict(item["payment"])
        canary["write_ledger_readback_kind"] = "MULTI_CAPTURE_MANIFEST"
        canary["write_ledger_manifest_ref"] = "deploy/production/evidence/two-captures.json"
        trade = dict(canary["write_mutations_by_table"])
        bill = {"payment_reconciliation_runs": trade.pop("payment_reconciliation_runs")}
        manifest = {
            "schema": "noteai.item31.write_capture_manifest.v1",
            "provider": item["name"],
            "canary_identity_sha256": item["canary_identity_sha256"],
            "captures": [
                {"phase": phase, "original_capture_sha256": hashlib.sha256(phase.encode()).hexdigest(),
                 "row_mutations_by_table": counts}
                for phase, counts in (("trade", trade), ("bill", bill))
            ],
            "secret_values_recorded": False,
        }
        self.save_capture_manifest(canary, manifest)
        return canary, manifest

    def save_capture_manifest(self, canary, manifest, *, canonical=True):
        raw = json.dumps(manifest, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
        if not canonical:
            raw += b"\n"
        path = self.root / canary["write_ledger_manifest_ref"]
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        canary["write_ledger_readback_sha256"] = digest
        self.save_canary(canary)
        self.payload["actual_production_write_set"]["ledger_readback_sha256"] = hashlib.sha256(
            json.dumps([digest], ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()

    def test_accepts_succeeded_with_original_scalar_capture(self):
        item = self.payload["providers"][0]
        item["payment"]["internal_status"] = "succeeded"
        canary = json.loads((self.root / item["canary_audit_ref"]).read_bytes())
        canary["payment"] = dict(item["payment"])
        self.save_canary(canary)
        self.assertEqual(self.validate(), [])

    def test_accepts_two_original_captures_as_manifest_not_single_capture(self):
        canary, manifest = self.capture_manifest()
        self.assertNotIn(canary["write_ledger_readback_sha256"], {
            capture["original_capture_sha256"] for capture in manifest["captures"]
        })
        self.assertEqual(self.validate(), [])

    def test_capture_manifest_requires_both_distinct_originals_in_phase_order(self):
        canary, manifest = self.capture_manifest()
        original = json.loads(json.dumps(manifest))
        for change in ("missing", "extra", "reversed", "duplicate_hash", "missing_hash"):
            with self.subTest(change=change):
                manifest = json.loads(json.dumps(original))
                captures = manifest["captures"]
                if change == "missing":
                    captures.pop()
                elif change == "extra":
                    captures.append(dict(captures[0]))
                elif change == "reversed":
                    captures.reverse()
                elif change == "duplicate_hash":
                    captures[1]["original_capture_sha256"] = captures[0]["original_capture_sha256"]
                else:
                    captures[0].pop("original_capture_sha256")
                self.save_capture_manifest(canary, manifest)
                self.assertIn("Item31 provider canary audit binding mismatch", self.validate())

    def test_capture_manifest_requires_exact_source_scope_counts_and_sum(self):
        canary, manifest = self.capture_manifest()
        original = json.loads(json.dumps(manifest))
        for phase, table, count in (
            (0, "credits", 2), (0, "credits", True), (0, "credits", 0),
            (0, "unknown_table", 1), (0, "payment_reconciliation_runs", 1),
            (1, "payment_reconciliation_runs", 2), (1, "payment_events", 1),
        ):
            with self.subTest(phase=phase, table=table, count=count):
                manifest = json.loads(json.dumps(original))
                manifest["captures"][phase]["row_mutations_by_table"][table] = count
                self.save_capture_manifest(canary, manifest)
                self.assertIn("Item31 provider canary audit binding mismatch", self.validate())

    def test_capture_manifest_requires_same_provider_canary_and_exact_shape(self):
        canary, manifest = self.capture_manifest()
        original = json.loads(json.dumps(manifest))
        for field, value in (("provider", "alipay_direct"), ("canary_identity_sha256", "0" * 64),
                             ("unreviewed_field", True), ("secret_values_recorded", True)):
            with self.subTest(field=field):
                manifest = dict(original, **{field: value})
                self.save_capture_manifest(canary, manifest)
                self.assertIn("Item31 provider canary audit binding mismatch", self.validate())

    def test_capture_manifest_requires_exact_canonical_file_and_bound_reference(self):
        canary, manifest = self.capture_manifest()
        self.save_capture_manifest(canary, manifest, canonical=False)
        self.assertIn("Item31 provider canary audit binding mismatch", self.validate())
        self.save_capture_manifest(canary, manifest)
        original = dict(canary)
        for field, value in (
            ("write_ledger_readback_sha256", "0" * 64),
            ("write_ledger_readback_kind", "ORIGINAL_CAPTURE"),
            ("write_ledger_manifest_ref", "deploy/production/evidence/missing.json"),
            ("write_ledger_manifest_ref", "two-captures.json"),
        ):
            with self.subTest(field=field, value=value):
                self.save_canary(dict(original, **{field: value}))
                self.assertIn("Item31 provider canary audit binding mismatch", self.validate())

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
