import hashlib
import json
import re
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


class Item35ReviewPackageFreezeTests(unittest.TestCase):
    def test_review_package_hash_table_matches_current_frozen_scope(self):
        package = (ROOT / gate.ITEM35_REVIEW_PACKAGE).read_text(encoding="utf-8")
        rows = dict(
            re.findall(
                r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$",
                package,
                flags=re.MULTILINE,
            )
        )
        expected_paths = set().union(
            *gate.ITEM35_DOCUMENT_SCOPE_PATHS.values(),
            *gate.ITEM35_APPROVAL_SCOPE_PATHS.values(),
        ) - {gate.ITEM35_REVIEW_PACKAGE}
        self.assertEqual(set(rows), expected_paths)
        self.assertEqual(
            rows,
            {
                ref: hashlib.sha256((ROOT / ref).read_bytes()).hexdigest()
                for ref in expected_paths
            },
        )


class Item35Item36EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        self.freeze_at = "2026-09-05T11:09:01+08:00"
        package = self.root / gate.ITEM35_REVIEW_PACKAGE
        package.parent.mkdir(parents=True)
        package.write_text(
            f"reviewed package\n审核包冻结时间：{self.freeze_at}\n",
            encoding="utf-8",
        )
        scoped_paths = set().union(
            *gate.ITEM35_DOCUMENT_SCOPE_PATHS.values(),
            *gate.ITEM35_APPROVAL_SCOPE_PATHS.values(),
        )
        for ref in scoped_paths - {gate.ITEM35_REVIEW_PACKAGE}:
            path = self.root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"review scope: {ref}\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, ref, payload):
        path = self.root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return {"evidence": [{"kind": "path", "ref": ref}]}

    def artifact(self, ref, content):
        path = self.root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def ledger(self, refs):
        return [
            {
                "path": ref,
                "sha256": hashlib.sha256((self.root / ref).read_bytes()).hexdigest(),
            }
            for ref in sorted(refs)
        ]

    def item35_payload(self):
        package_sha = hashlib.sha256(
            (self.root / gate.ITEM35_REVIEW_PACKAGE).read_bytes()
        ).hexdigest()
        approvals = []
        for category in sorted(gate.ITEM35_REQUIRED_APPROVALS):
            signed_path = (
                "deploy/production/evidence/"
                f"item35-{category}-signed.txt"
            )
            signed_sha = self.artifact(signed_path, f"signed:{category}\n")
            scope = self.ledger(gate.ITEM35_APPROVAL_SCOPE_PATHS[category])
            scope_sha = gate._file_ledger_sha256(scope)
            binding_path = (
                "deploy/production/evidence/"
                f"item35-{category}-approval-binding.json"
            )
            binding = {
                "schema": gate.ITEM35_APPROVAL_BINDING_SCHEMA,
                "category": category,
                "status": "APPROVED",
                "signer_name": f"Authorized reviewer for {category}",
                "organization": f"Review organization for {category}",
                "professional_role": "authorized professional",
                "signed_at": "2026-09-07T12:00:00+08:00",
                "signed_artifact_sha256": signed_sha,
                "scope_sha256": scope_sha,
                "open_condition_count": 0,
                "secret_values_recorded": False,
            }
            binding_sha = self.artifact(
                binding_path,
                json.dumps(binding),
            )
            approvals.append(
                {
                    "category": category,
                    "status": "APPROVED",
                    "signer_name": f"Authorized reviewer for {category}",
                    "organization": f"Review organization for {category}",
                    "professional_role": "authorized professional",
                    "signed_at": "2026-09-07T12:00:00+08:00",
                    "signed_artifact_path": signed_path,
                    "signed_artifact_sha256": signed_sha,
                    "binding_artifact_path": binding_path,
                    "binding_artifact_sha256": binding_sha,
                    "scope_artifacts": scope,
                    "scope_sha256": scope_sha,
                    "open_condition_count": 0,
                }
            )
        payload = {
            "schema": gate.ITEM35_APPROVAL_EVIDENCE_SCHEMA,
            "item": 35,
            "status": "VERIFIED",
            "readiness_credit": True,
            "environment": "production",
            "public_launch_scope": True,
            "review_package_sha256": package_sha,
            "review_package_frozen_at": self.freeze_at,
            "approved_documents": [
                {
                    "category": category,
                    "status": "APPROVED",
                    "artifacts": self.ledger(
                        gate.ITEM35_DOCUMENT_SCOPE_PATHS[category]
                    ),
                }
                for category in sorted(gate.ITEM35_REQUIRED_DOCUMENTS)
            ],
            "approvals": approvals,
            "secret_values_recorded": False,
        }
        return payload

    def test_item35_requires_bound_documents_and_separate_signed_approvals(self):
        payload = self.item35_payload()
        control = self.write(gate.ITEM35_APPROVAL_EVIDENCE, payload)
        self.assertEqual(
            gate.validate_item35_approval_evidence(
                control, root=self.root, now=self.now
            ),
            [],
        )
        payload["approvals"][1]["signed_artifact_path"] = payload["approvals"][0][
            "signed_artifact_path"
        ]
        payload["approvals"][1]["signed_artifact_sha256"] = payload["approvals"][0][
            "signed_artifact_sha256"
        ]
        control = self.write(gate.ITEM35_APPROVAL_EVIDENCE, payload)
        self.assertIn(
            "Item35 professional approval invalid",
            gate.validate_item35_approval_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item35_rejects_missing_package_or_nonexistent_artifacts(self):
        payload = self.item35_payload()
        (self.root / gate.ITEM35_REVIEW_PACKAGE).unlink()
        payload["approvals"][0]["signed_artifact_path"] = (
            "deploy/production/evidence/missing.txt"
        )
        control = self.write(gate.ITEM35_APPROVAL_EVIDENCE, payload)
        errors = gate.validate_item35_approval_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item35 review package missing", errors)
        self.assertIn("Item35 professional approval invalid", errors)

    def test_item35_binds_signed_content_and_full_frozen_scope(self):
        payload = self.item35_payload()
        approval = payload["approvals"][0]
        signed_path = self.root / approval["signed_artifact_path"]
        signed_path.write_text("unrelated replacement\n", encoding="utf-8")
        approval["signed_artifact_sha256"] = hashlib.sha256(
            signed_path.read_bytes()
        ).hexdigest()
        private_scope = self.root / "docs/PRIVATE_STORAGE_AND_RECOVERY_CONTRACT.md"
        private_scope.write_text("changed after review\n", encoding="utf-8")
        control = self.write(gate.ITEM35_APPROVAL_EVIDENCE, payload)
        errors = gate.validate_item35_approval_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item35 approved document binding mismatch", errors)
        self.assertIn("Item35 professional approval invalid", errors)

    def test_item35_rejects_cross_type_signed_and_binding_artifact_reuse(self):
        payload = self.item35_payload()
        target, donor = payload["approvals"]
        target["signed_artifact_path"] = donor["binding_artifact_path"]
        target["signed_artifact_sha256"] = donor["binding_artifact_sha256"]
        target_binding_path = self.root / target["binding_artifact_path"]
        target_binding = json.loads(target_binding_path.read_text(encoding="utf-8"))
        target_binding["signed_artifact_sha256"] = target[
            "signed_artifact_sha256"
        ]
        target_binding_path.write_text(json.dumps(target_binding), encoding="utf-8")
        target["binding_artifact_sha256"] = hashlib.sha256(
            target_binding_path.read_bytes()
        ).hexdigest()
        control = self.write(gate.ITEM35_APPROVAL_EVIDENCE, payload)
        self.assertIn(
            "Item35 signed and binding artifacts must be distinct",
            gate.validate_item35_approval_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item35_rejects_sensitive_or_unknown_fields(self):
        payload = self.item35_payload()
        payload["private_key"] = "synthetic-test-only"
        payload["approvals"][0]["cookie"] = "synthetic-test-only"
        control = self.write(gate.ITEM35_APPROVAL_EVIDENCE, payload)
        errors = gate.validate_item35_approval_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item35 terminal evidence schema mismatch", errors)
        self.assertIn("Item35 sensitive field present", errors)

    def test_item35_rejects_float_item_number(self):
        payload = self.item35_payload()
        payload["item"] = 35.0
        control = self.write(gate.ITEM35_APPROVAL_EVIDENCE, payload)
        self.assertIn(
            "Item35 terminal status mismatch",
            gate.validate_item35_approval_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def item36_payload(self):
        def operation_digest(label):
            return hashlib.sha256(f"item36:{label}".encode()).hexdigest()

        health_identities = {
            role: {
                "unit": hashlib.sha256(f"{role}:unit".encode()).hexdigest(),
                "effective": hashlib.sha256(
                    f"{role}:effective".encode()
                ).hexdigest(),
                "container": hashlib.sha256(
                    f"{role}:container".encode()
                ).hexdigest(),
            }
            for role in ("API-C", "API-F")
        }
        quote_path = "deploy/production/evidence/item36-alb-quote.json"
        quote_payload = {
            "schema": gate.ITEM36_COST_QUOTE_SCHEMA,
            "provider": "aliyun",
            "region": "cn-shenzhen",
            "currency": "CNY",
            "observed_at": "2026-09-06T10:00:00+08:00",
            "valid_until": "2026-09-10T10:00:00+08:00",
            "pricing_basis_hours": 720,
            "components": [
                {
                    "service": "alb_instance",
                    "quantity": 1,
                    "unit": "instance_hour",
                    "unit_price_cny": 0.125,
                    "estimated_monthly_cny": 90.0,
                },
                {
                    "service": "alb_lcu",
                    "quantity": 1,
                    "unit": "lcu_hour",
                    "unit_price_cny": 0.042,
                    "estimated_monthly_cny": 30.24,
                },
                {
                    "service": "public_eip",
                    "quantity": 2,
                    "unit": "ip_hour",
                    "unit_price_cny": 0.02,
                    "estimated_monthly_cny": 28.8,
                },
            ],
            "variable_egress": {
                "service": "public_egress",
                "unit": "GB",
                "unit_price_cny": 0.8,
                "estimated_usage": 1.0,
                "estimated_cost_cny": 0.8,
            },
            "estimated_monthly_cny": 149.04,
            "secret_values_recorded": False,
        }
        quote_sha = self.artifact(quote_path, json.dumps(quote_payload))
        billing_path = "deploy/production/evidence/item36-billing-readback.json"
        billing_payload = {
            "schema": gate.ITEM36_BILLING_READBACK_SCHEMA,
            "provider": "aliyun",
            "region": "cn-shenzhen",
            "currency": "CNY",
            "observed_at": "2026-09-07T09:14:30+08:00",
            "resource_scope_identity_sha256": hashlib.sha256(
                b"item36:resource-scope"
            ).hexdigest(),
            "line_items": [
                {"service": "alb_instance", "actual_incurred_cny": 0.01},
                {"service": "alb_lcu", "actual_incurred_cny": 0.0},
                {"service": "public_eip", "actual_incurred_cny": 0.0},
                {"service": "public_egress", "actual_incurred_cny": 0.0},
            ],
            "actual_incurred_cny": 0.01,
            "secret_values_recorded": False,
        }
        billing_sha = self.artifact(billing_path, json.dumps(billing_payload))
        approval_path = (
            "deploy/production/evidence/item36-recurring-cost-approval.json"
        )
        approval = {
            "schema": gate.ITEM36_COST_APPROVAL_SCHEMA,
            "status": "APPROVED",
            "approved_at": "2026-09-06T12:00:00+08:00",
            "approved_monthly_ceiling_cny": 180.0,
            "approved_variable_egress_ceiling_cny": 20.0,
            "resource_scope": [
                "alb_instance",
                "alb_lcu",
                "public_eip",
                "public_egress",
            ],
            "quote_sha256": quote_sha,
            "quote_observed_at": "2026-09-06T10:00:00+08:00",
            "quote_valid_until": "2026-09-10T10:00:00+08:00",
            "secret_values_recorded": False,
        }
        approval_sha = self.artifact(approval_path, json.dumps(approval))
        payload = {
            "schema": gate.ITEM36_ALB_EVIDENCE_SCHEMA,
            "item": 36,
            "status": "VERIFIED",
            "readiness_credit": True,
            "environment": "production",
            "observed_at": "2026-09-07T09:15:00+08:00",
            "alb": {
                "alb_identity_sha256": "a" * 64,
                "vpc_identity_sha256": "b" * 64,
                "server_group_identity_sha256": "c" * 64,
                "listener_identity_sha256": "d" * 64,
                "certificate_identity_sha256": "e" * 64,
                "public_eip_identity_sha256s": ["f" * 64, "0" * 64],
                "region": "cn-shenzhen",
                "protocol": "HTTPS",
                "listener_port": 443,
                "dual_zone_count": 2,
                "tls_verification": "PASS",
                "hostname": gate.ITEM36_API_HOSTNAME,
                "certificate_status": "ISSUED",
                "certificate_dns_names": [gate.ITEM36_API_HOSTNAME],
                "certificate_sha256": "1" * 64,
                "certificate_not_before": "2026-09-01T00:00:00+08:00",
                "certificate_not_after": "2027-01-01T00:00:00+08:00",
                "resource_created_at": "2026-09-07T09:00:00+08:00",
                "configuration_readback": {
                    "provider": "aliyun",
                    "request_identity_sha256": operation_digest(
                        "configuration-request"
                    ),
                    "response_sha256": operation_digest(
                        "configuration-response"
                    ),
                    "observed_at": "2026-09-07T09:12:00+08:00",
                },
            },
            "health_routing": {
                "path": "/health/ready",
                "expected_status": 200,
                "provider_readback": {
                    "provider": "aliyun",
                    "request_identity_sha256": operation_digest(
                        "health-request"
                    ),
                    "response_sha256": operation_digest("health-response"),
                    "observed_at": "2026-09-07T09:13:00+08:00",
                },
                "backends": [
                    {
                        "role": role,
                        "instance_identity_sha256": hashlib.sha256(
                            f"{role}:instance".encode()
                        ).hexdigest(),
                        "target_identity_sha256": hashlib.sha256(
                            f"{role}:target".encode()
                        ).hexdigest(),
                        "target_port": 8000,
                        "target_health": "healthy",
                        "private_bind": True,
                        "security_group_alb_only": True,
                        "private_address_sha256": hashlib.sha256(
                            f"{role}:address".encode()
                        ).hexdigest(),
                        "unit_sha256": health_identities[role]["unit"],
                        "effective_unit_sha256": health_identities[role][
                            "effective"
                        ],
                        "container_identity_sha256": health_identities[role][
                            "container"
                        ],
                        "health_observed_at": "2026-09-07T09:13:00+08:00",
                    }
                    for role, value in (("API-C", "6"), ("API-F", "7"))
                ],
                "security_group_rule": {
                    "provider": "aliyun",
                    "api_security_group_identity_sha256": operation_digest(
                        "api-security-group"
                    ),
                    "alb_security_group_identity_sha256": operation_digest(
                        "alb-security-group"
                    ),
                    "rule_identity_sha256": operation_digest(
                        "alb-only-port-8000-rule"
                    ),
                    "source_type": "security_group",
                    "source_identity_sha256": operation_digest(
                        "alb-security-group"
                    ),
                    "protocol": "TCP",
                    "destination_port": 8000,
                    "target_instance_identity_sha256s": sorted(
                        hashlib.sha256(f"{role}:instance".encode()).hexdigest()
                        for role in ("API-C", "API-F")
                    ),
                    "wider_ingress_rule_count": 0,
                    "request_identity_sha256": operation_digest(
                        "security-group-request"
                    ),
                    "response_sha256": operation_digest(
                        "security-group-response"
                    ),
                    "observed_at": "2026-09-07T09:13:30+08:00",
                },
                "controlled_probe": {
                    "result": "PASS",
                    "executed_at": "2026-09-07T09:14:00+08:00",
                    "connection_mode": "pre_dns_ip_override",
                    "endpoint_identity_sha256": "f" * 64,
                    "hostname": gate.ITEM36_API_HOSTNAME,
                    "sni_hostname": gate.ITEM36_API_HOSTNAME,
                    "host_header": gate.ITEM36_API_HOSTNAME,
                    "path": "/health/ready",
                    "status_code": 200,
                    "tls_verified": True,
                    "certificate_sha256": "1" * 64,
                    "run_identity_sha256": operation_digest("probe-run"),
                    "response_sha256": operation_digest("probe-response"),
                },
            },
            "activation": {
                "mode": "BOUNDED_ROLLING",
                "result": "PASS",
                "started_at": "2026-09-07T09:05:00+08:00",
                "finished_at": "2026-09-07T09:10:00+08:00",
                "planned_restart_count": 2,
                "unplanned_restart_count": 0,
                "fresh_ndr": {
                    "instance_role": "API-F",
                    "mask": 0,
                    "observed_at": "2026-09-07T09:11:00+08:00",
                    "readback_sha256": operation_digest("ndr-readback"),
                    "units": [
                        {
                            "name": name,
                            "unit_file_sha256": (
                                health_identities["API-F"]["unit"]
                                if name == "noteai-api.service"
                                else value * 64
                            ),
                            "effective_unit_sha256": (
                                health_identities["API-F"]["effective"]
                                if name == "noteai-api.service"
                                else str(int(value) + 1) * 64
                            ),
                        }
                        for name, value in (
                            ("noteai-api.service", "1"),
                            ("noteai-xhs-trends.service", "2"),
                            ("noteai-xhs-tracking.service", "3"),
                        )
                    ],
                },
                "rollback_state_retained": True,
                "rollback_unit_sha256": "a" * 64,
                "backend_executions": [
                    {
                        "role": role,
                        "result": "PASS",
                        "planned_restart_count": 1,
                        "exit_code": 0,
                        "started_at": (
                            "2026-09-07T09:05:00+08:00"
                            if role == "API-C"
                            else "2026-09-07T09:08:00+08:00"
                        ),
                        "finished_at": (
                            "2026-09-07T09:07:00+08:00"
                            if role == "API-C"
                            else "2026-09-07T09:10:00+08:00"
                        ),
                        "command_identity_sha256": operation_digest(
                            f"{role}-command"
                        ),
                        "invoke_identity_sha256": operation_digest(
                            f"{role}-invoke"
                        ),
                        "output_sha256": operation_digest(f"{role}-output"),
                        "before_unit_sha256": str(int(value) + 3) * 64,
                        "after_unit_sha256": health_identities[role]["unit"],
                        "after_effective_unit_sha256": health_identities[role][
                            "effective"
                        ],
                        "before_container_identity_sha256": str(int(value) + 5) * 64,
                        "after_container_identity_sha256": health_identities[role][
                            "container"
                        ],
                    }
                    for role, value in (("API-C", "1"), ("API-F", "2"))
                ],
            },
            "actual_production_write_set": {
                "alb_instance_create_count": 1,
                "server_group_create_count": 1,
                "https_listener_create_count": 1,
                "certificate_binding_count": 1,
                "backend_registration_count": 2,
                "api_unit_update_count": 2,
                "security_group_rule_change_count": 1,
                "planned_service_restart_count": 2,
                "unplanned_service_restart_count": 0,
                "public_eip_change_count": 0,
                "new_vpc_count": 0,
                "waf_resource_count": 0,
                "extra_resource_count": 0,
                "production_database_write_count": 0,
                "payment_or_funds_action_count": 0,
                "dns_write_count": 0,
            },
            "launch_boundary": {
                "dns_write_count": 0,
                "real_user_request_count": 0,
                "synthetic_probe_only": True,
                "production_database_write_count": 0,
                "payment_or_funds_action_count": 0,
            },
            "costs": {
                "owner_recurring_cost_approved": True,
                "approval_artifact_path": approval_path,
                "approval_artifact_sha256": approval_sha,
                "approved_at": "2026-09-06T12:00:00+08:00",
                "approved_monthly_ceiling_cny": 180.0,
                "approved_variable_egress_ceiling_cny": 20.0,
                "quote_artifact_path": quote_path,
                "quote_sha256": quote_sha,
                "quote_observed_at": "2026-09-06T10:00:00+08:00",
                "quote_valid_until": "2026-09-10T10:00:00+08:00",
                "estimated_monthly_cny": 149.04,
                "estimated_variable_egress_cny": 0.8,
                "actual_incurred_cny_to_observed_at": 0.01,
                "actual_variable_egress_cny_to_observed_at": 0.0,
                "billing_readback_path": billing_path,
                "billing_readback_sha256": billing_sha,
                "components": [
                    {"service": "alb_instance", "estimated_monthly_cny": 90.0},
                    {"service": "alb_lcu", "estimated_monthly_cny": 30.24},
                    {"service": "public_eip", "estimated_monthly_cny": 28.8},
                ],
                "variable_egress": {
                    "service": "public_egress",
                    "unit": "GB",
                    "unit_price_cny": 0.8,
                    "estimated_usage": 1.0,
                    "estimated_cost_cny": 0.8,
                },
            },
            "secret_values_recorded": False,
        }
        payload["alb"]["configuration_readback"]["response_sha256"] = (
            gate._item36_configuration_response_sha256(payload["alb"])
        )
        security_group_rule = payload["health_routing"]["security_group_rule"]
        security_group_rule["response_sha256"] = (
            gate._item36_security_group_response_sha256(
                security_group_rule,
                payload["alb"],
                payload["health_routing"]["backends"],
            )
        )
        payload["health_routing"]["provider_readback"]["response_sha256"] = (
            gate._item36_health_response_sha256(
                payload["health_routing"], payload["alb"]
            )
        )
        probe = payload["health_routing"]["controlled_probe"]
        probe["response_sha256"] = gate._item36_probe_response_sha256(
            probe, payload["alb"]
        )
        fresh_ndr = payload["activation"]["fresh_ndr"]
        fresh_ndr["readback_sha256"] = gate._item36_ndr_readback_sha256(
            fresh_ndr
        )
        for execution in payload["activation"]["backend_executions"]:
            execution["output_sha256"] = gate._item36_activation_output_sha256(
                execution
            )
        payload["activation"]["rollback_unit_sha256"] = (
            gate._item36_rollback_unit_sha256(
                payload["activation"]["backend_executions"]
            )
        )
        billing_payload["resource_scope_identity_sha256"] = (
            gate._item36_resource_scope_sha256(payload["alb"])
        )
        billing_sha = self.artifact(billing_path, json.dumps(billing_payload))
        payload["costs"]["billing_readback_sha256"] = billing_sha
        return payload

    def item36_actual_usage_payload(self, *, hours=744, lcu=2):
        payload = self.item36_payload()
        alb = payload["alb"]
        alb["hostname"] = gate.ITEM36_CURRENT_API_HOSTNAME
        alb["certificate_dns_names"] = [gate.ITEM36_CURRENT_API_HOSTNAME]
        alb["configuration_readback"]["response_sha256"] = (
            gate._item36_configuration_response_sha256(alb)
        )
        probe = payload["health_routing"]["controlled_probe"]
        for key in ("hostname", "sni_hostname", "host_header"):
            probe[key] = gate.ITEM36_CURRENT_API_HOSTNAME
        probe["response_sha256"] = gate._item36_probe_response_sha256(probe, alb)
        configuration = {
            "vpc_identity_sha256": alb["vpc_identity_sha256"],
            "region": "cn-shenzhen",
            "zones": ["cn-shenzhen-c", "cn-shenzhen-f"],
            "alb_count": 1,
            "edition": "Standard",
            "ip_version": "IPv4",
            "network_type": "Internet",
            "eip_count": 2,
            "eip_isp": "BGP",
            "eip_charge_type": "PayByTraffic",
            "shared_bandwidth": False,
            "api_hostname": gate.ITEM36_CURRENT_API_HOSTNAME,
        }
        costs = payload["costs"]
        for field in (
            "approved_monthly_ceiling_cny",
            "approved_variable_egress_ceiling_cny",
            "quote_valid_until",
        ):
            costs.pop(field)
        costs["authorization_mode"] = gate.ITEM36_ACTUAL_USAGE_MODE
        quote_path = self.root / costs["quote_artifact_path"]
        quote = json.loads(quote_path.read_text(encoding="utf-8"))
        quote.pop("valid_until")
        quote.update({
            "schema": gate.ITEM36_CURRENT_QUOTE_SCHEMA,
            "pricing_validity": "CURRENT_DISPLAY_NO_LOCK",
            "pricing_basis_hours": hours,
            "vat_included": True,
            "resource_configuration": configuration,
            "public_egress_pricing": {
                "billing": "CDT",
                "usage_scope": "SUM_TWO_EIPS_OUTBOUND",
                "free_allowance_assumed_gb": 0,
                "tiers": [
                    {"upper_tb": 10, "unit_price_cny": 0.8},
                    {"upper_tb": 50, "unit_price_cny": 0.75},
                    {"upper_tb": 150, "unit_price_cny": 0.7},
                    {"upper_tb": None, "unit_price_cny": 0.65},
                ],
            },
            "source_artifact_path": "deploy/production/evidence/quote-source.txt",
        })
        quote["source_artifact_sha256"] = self.artifact(
            quote["source_artifact_path"], "synthetic current China-site quote only"
        )
        for item in quote["components"]:
            if item["service"] == "alb_lcu":
                item["quantity"] = lcu
            item["estimated_monthly_cny"] = (
                hours * item["quantity"] * item["unit_price_cny"]
            )
        quote["estimated_monthly_cny"] = sum(
            item["estimated_monthly_cny"] for item in quote["components"]
        )
        quote["variable_egress"]["estimated_usage"] = 100.0
        quote["variable_egress"]["estimated_cost_cny"] = 80.0
        costs["components"] = [
            {"service": item["service"], "estimated_monthly_cny": item["estimated_monthly_cny"]}
            for item in quote["components"]
        ]
        costs["estimated_monthly_cny"] = quote["estimated_monthly_cny"]
        costs["estimated_variable_egress_cny"] = 80.0
        costs["variable_egress"] = quote["variable_egress"].copy()
        approval_path = self.root / costs["approval_artifact_path"]
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        for field in (
            "approved_monthly_ceiling_cny",
            "approved_variable_egress_ceiling_cny",
            "quote_valid_until",
        ):
            approval.pop(field)
        approval.update({
            "schema": gate.ITEM36_ACTUAL_USAGE_APPROVAL_SCHEMA,
            "authorization_mode": gate.ITEM36_ACTUAL_USAGE_MODE,
            "cost_triggered_service_actions": "NONE",
            "resource_configuration": configuration.copy(),
            "source_artifact_path": "deploy/production/evidence/owner-source.txt",
        })
        approval["source_artifact_sha256"] = self.artifact(
            approval["source_artifact_path"],
            "synthetic owner instruction: original scope, actual continuing cost, no cost stop",
        )
        costs["purchase_readback"] = {
            "observed_at": "2026-09-07T08:59:00+08:00",
            "source_artifact_path": "deploy/production/evidence/purchase-source.txt",
        }
        costs["purchase_readback"]["source_artifact_sha256"] = self.artifact(
            costs["purchase_readback"]["source_artifact_path"],
            "synthetic pre-create readback: same approved prices and configuration",
        )
        self.save_item36_current_costs(payload, quote, approval, refresh_recheck=True)
        return payload

    def save_item36_current_costs(self, payload, quote, approval, *, refresh_recheck=False):
        costs = payload["costs"]
        quote_sha = self.artifact(costs["quote_artifact_path"], json.dumps(quote))
        costs["quote_sha256"] = quote_sha
        approval["quote_sha256"] = quote_sha
        costs["approval_artifact_sha256"] = self.artifact(
            costs["approval_artifact_path"], json.dumps(approval)
        )
        if refresh_recheck:
            costs["purchase_readback"]["pricing_sha256"] = gate._canonical_object_sha256({
                key: quote[key] for key in (
                    "components", "variable_egress", "public_egress_pricing",
                    "pricing_basis_hours", "vat_included",
                )
            })
            costs["purchase_readback"]["resource_configuration_sha256"] = (
                gate._canonical_object_sha256(quote["resource_configuration"])
            )

    def read_item36_current_costs(self, payload):
        return tuple(
            json.loads((self.root / payload["costs"][field]).read_text(encoding="utf-8"))
            for field in ("quote_artifact_path", "approval_artifact_path")
        )

    def test_item36_actual_usage_accepts_current_host_and_hourly_scenarios(self):
        for hours, lcu in ((720, 1), (744, 2), (744, 5), (720, 0.1), (744, 0)):
            with self.subTest(hours=hours, lcu=lcu):
                payload = self.item36_actual_usage_payload(hours=hours, lcu=lcu)
                self.assertNotIn("approved_monthly_ceiling_cny", payload["costs"])
                self.assertNotIn("quote_valid_until", payload["costs"])
                self.assertEqual(
                    gate.validate_item36_alb_evidence(
                        self.write(gate.ITEM36_ALB_EVIDENCE, payload),
                        root=self.root, now=self.now,
                    ),
                    [],
                )

    def test_item36_actual_usage_keeps_real_billing_above_old_scenario(self):
        payload = self.item36_actual_usage_payload()
        costs = payload["costs"]
        billing = json.loads((self.root / costs["billing_readback_path"]).read_text())
        for line in billing["line_items"]:
            line["actual_incurred_cny"] = 1000.0
        billing["actual_incurred_cny"] = 4000.0
        costs["actual_incurred_cny_to_observed_at"] = 4000.0
        costs["actual_variable_egress_cny_to_observed_at"] = 1000.0
        costs["billing_readback_sha256"] = self.artifact(
            costs["billing_readback_path"], json.dumps(billing)
        )
        self.assertEqual(
            gate.validate_item36_alb_evidence(
                self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
            ), [],
        )
        billing["resource_scope_identity_sha256"] = "f" * 64
        costs["billing_readback_sha256"] = self.artifact(
            costs["billing_readback_path"], json.dumps(billing)
        )
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
            ),
        )

    def test_item36_actual_usage_rejects_reintroduced_caps_or_expiry(self):
        for record, key, value in (
            ("costs", "approved_monthly_ceiling_cny", 300),
            ("costs", "approved_variable_egress_ceiling_cny", None),
            ("costs", "quote_valid_until", None),
            ("approval", "approved_monthly_ceiling_cny", 300),
            ("approval", "cost_triggered_service_actions", "STOP_AT_90_PERCENT"),
            ("quote", "valid_until", "2026-09-10T10:00:00+08:00"),
        ):
            with self.subTest(record=record, key=key):
                payload = self.item36_actual_usage_payload()
                quote, approval = self.read_item36_current_costs(payload)
                {"costs": payload["costs"], "quote": quote, "approval": approval}[record][key] = value
                self.save_item36_current_costs(payload, quote, approval)
                self.assertIn(
                    "Item36 recurring-cost approval missing",
                    gate.validate_item36_alb_evidence(
                        self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
                    ),
                )

    def test_item36_actual_usage_requires_untampered_owner_quote_and_purchase_sources(self):
        for source in ("approval", "quote", "purchase_readback"):
            with self.subTest(source=source):
                payload = self.item36_actual_usage_payload()
                quote, approval = self.read_item36_current_costs(payload)
                record = {"approval": approval, "quote": quote,
                          "purchase_readback": payload["costs"]["purchase_readback"]}[source]
                (self.root / record["source_artifact_path"]).write_text("changed synthetic source")
                self.assertIn(
                    "Item36 recurring-cost approval missing",
                    gate.validate_item36_alb_evidence(
                        self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
                    ),
                )

    def test_item36_actual_usage_rechecks_same_prices_before_creation(self):
        for field, value in (
            ("observed_at", "2026-09-07T09:01:00+08:00"),
            ("observed_at", "2026-09-05T08:00:00+08:00"),
            ("pricing_sha256", "f" * 64),
            ("resource_configuration_sha256", "f" * 64),
        ):
            with self.subTest(field=field, value=value):
                payload = self.item36_actual_usage_payload()
                payload["costs"]["purchase_readback"][field] = value
                self.assertIn(
                    "Item36 recurring-cost approval missing",
                    gate.validate_item36_alb_evidence(
                        self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
                    ),
                )

    def test_item36_actual_usage_binds_original_resource_scope_and_tariffs(self):
        for changed in ("vpc", "edition", "vat", "free_traffic", "tariff", "unit_price"):
            with self.subTest(changed=changed):
                payload = self.item36_actual_usage_payload()
                quote, approval = self.read_item36_current_costs(payload)
                if changed in ("vpc", "edition"):
                    key, value = (("vpc_identity_sha256", "9" * 64)
                                  if changed == "vpc" else ("edition", "WAF"))
                    quote["resource_configuration"][key] = value
                    approval["resource_configuration"][key] = value
                elif changed == "vat":
                    quote["vat_included"] = False
                elif changed == "free_traffic":
                    quote["public_egress_pricing"]["free_allowance_assumed_gb"] = 20
                elif changed == "unit_price":
                    quote["components"][0]["unit_price_cny"] = 0.147
                    for item in quote["components"]:
                        item["estimated_monthly_cny"] = (
                            quote["pricing_basis_hours"] * item["quantity"] * item["unit_price_cny"]
                        )
                    quote["estimated_monthly_cny"] = sum(
                        item["estimated_monthly_cny"] for item in quote["components"]
                    )
                    payload["costs"]["estimated_monthly_cny"] = quote["estimated_monthly_cny"]
                    payload["costs"]["components"] = [
                        {"service": item["service"], "estimated_monthly_cny": item["estimated_monthly_cny"]}
                        for item in quote["components"]
                    ]
                else:
                    quote["public_egress_pricing"]["tiers"][0]["unit_price_cny"] = 0
                self.save_item36_current_costs(payload, quote, approval, refresh_recheck=True)
                self.assertIn(
                    "Item36 recurring-cost approval missing",
                    gate.validate_item36_alb_evidence(
                        self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
                    ),
                )

    def test_item36_actual_usage_rejects_wrong_host_and_legacy_schema_downgrade(self):
        payload = self.item36_actual_usage_payload()
        payload["alb"]["certificate_dns_names"] = [gate.ITEM36_API_HOSTNAME]
        payload["alb"]["configuration_readback"]["response_sha256"] = (
            gate._item36_configuration_response_sha256(payload["alb"])
        )
        self.assertIn(
            "Item36 ALB/TLS configuration mismatch",
            gate.validate_item36_alb_evidence(
                self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
            ),
        )
        payload = self.item36_actual_usage_payload()
        quote, approval = self.read_item36_current_costs(payload)
        approval["schema"] = gate.ITEM36_COST_APPROVAL_SCHEMA
        self.save_item36_current_costs(payload, quote, approval)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                self.write(gate.ITEM36_ALB_EVIDENCE, payload), root=self.root, now=self.now
            ),
        )

    def test_item36_requires_tls_fresh_health_activation_and_cost_gate(self):
        payload = self.item36_payload()
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertEqual(
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
            [],
        )
        payload["launch_boundary"]["dns_write_count"] = 1
        payload["costs"]["owner_recurring_cost_approved"] = False
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 pre-DNS boundary mismatch", errors)
        self.assertIn("Item36 recurring-cost approval missing", errors)

    def test_item36_rejects_bool_infinity_stale_and_malformed_evidence(self):
        payload = self.item36_payload()
        payload["launch_boundary"]["dns_write_count"] = False
        payload["costs"]["estimated_monthly_cny"] = float("inf")
        payload["health_routing"]["backends"] = 42
        payload["actual_production_write_set"]["waf_resource_count"] = 1
        payload["health_routing"]["controlled_probe"][
            "executed_at"
        ] = "2026-09-07T09:01:00+08:00"
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 pre-DNS boundary mismatch", errors)
        self.assertIn("Item36 recurring-cost approval missing", errors)
        self.assertIn("Item36 controlled health route mismatch", errors)
        self.assertIn("Item36 post-activation freshness binding missing", errors)
        self.assertIn("Item36 actual production write set invalid", errors)

    def test_item36_binds_activation_ndr_and_health_identities(self):
        payload = self.item36_payload()
        payload["health_routing"]["backends"][0]["unit_sha256"] = "f" * 64
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 activation/health identity binding mismatch", errors)

    def test_item36_rejects_collapsed_operational_evidence_hashes(self):
        payload = self.item36_payload()
        digest = "f" * 64
        payload["alb"]["configuration_readback"].update(
            {
                "request_identity_sha256": digest,
                "response_sha256": digest,
            }
        )
        payload["health_routing"]["provider_readback"].update(
            {
                "request_identity_sha256": digest,
                "response_sha256": digest,
            }
        )
        payload["health_routing"]["controlled_probe"].update(
            {"run_identity_sha256": digest, "response_sha256": digest}
        )
        payload["activation"]["fresh_ndr"]["readback_sha256"] = digest
        for execution in payload["activation"]["backend_executions"]:
            execution.update(
                {
                    "command_identity_sha256": digest,
                    "invoke_identity_sha256": digest,
                    "output_sha256": digest,
                }
            )
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 operational evidence identities are not distinct",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_requires_distinct_resources_backends_and_invocations(self):
        payload = self.item36_payload()
        alb = payload["alb"]
        alb["vpc_identity_sha256"] = alb["alb_identity_sha256"]
        alb["configuration_readback"]["response_sha256"] = (
            gate._item36_configuration_response_sha256(alb)
        )
        billing_path = self.root / payload["costs"]["billing_readback_path"]
        billing = json.loads(billing_path.read_text(encoding="utf-8"))
        billing["resource_scope_identity_sha256"] = (
            gate._item36_resource_scope_sha256(alb)
        )
        billing_path.write_text(json.dumps(billing), encoding="utf-8")
        payload["costs"]["billing_readback_sha256"] = hashlib.sha256(
            billing_path.read_bytes()
        ).hexdigest()

        backends = payload["health_routing"]["backends"]
        for field in (
            "instance_identity_sha256",
            "target_identity_sha256",
            "private_address_sha256",
        ):
            backends[1][field] = backends[0][field]
        payload["health_routing"]["provider_readback"]["response_sha256"] = (
            gate._item36_health_response_sha256(
                payload["health_routing"], payload["alb"]
            )
        )
        executions = payload["activation"]["backend_executions"]
        executions[1]["invoke_identity_sha256"] = executions[0][
            "invoke_identity_sha256"
        ]

        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 resource identities are not distinct", errors)
        self.assertIn("Item36 backend identities are not distinct", errors)
        self.assertIn(
            "Item36 operational evidence identities are not distinct",
            errors,
        )

    def test_item36_binds_health_and_probe_to_exact_alb_route(self):
        payload = self.item36_payload()
        alb = payload["alb"]
        for field in (
            "alb_identity_sha256",
            "server_group_identity_sha256",
            "listener_identity_sha256",
        ):
            alb[field] = hashlib.sha256(f"replacement:{field}".encode()).hexdigest()
        alb["configuration_readback"]["response_sha256"] = (
            gate._item36_configuration_response_sha256(alb)
        )
        billing_path = self.root / payload["costs"]["billing_readback_path"]
        billing = json.loads(billing_path.read_text(encoding="utf-8"))
        billing["resource_scope_identity_sha256"] = (
            gate._item36_resource_scope_sha256(alb)
        )
        billing_path.write_text(json.dumps(billing), encoding="utf-8")
        payload["costs"]["billing_readback_sha256"] = hashlib.sha256(
            billing_path.read_bytes()
        ).hexdigest()

        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 controlled health route mismatch", errors)
        self.assertIn("Item36 controlled TLS probe mismatch", errors)

    def test_item36_binds_rolling_rollback_container_and_health_clock(self):
        payload = self.item36_payload()
        payload["activation"]["rollback_unit_sha256"] = "9" * 64
        payload["activation"]["backend_executions"].reverse()
        backends = payload["health_routing"]["backends"]
        backends[1]["container_identity_sha256"] = backends[0][
            "container_identity_sha256"
        ]
        for backend in backends:
            backend["health_observed_at"] = "2026-09-07T09:13:30+08:00"
        executions_by_role = {
            item["role"]: item
            for item in payload["activation"]["backend_executions"]
        }
        executions_by_role[backends[1]["role"]][
            "after_container_identity_sha256"
        ] = backends[1]["container_identity_sha256"]
        for execution in payload["activation"]["backend_executions"]:
            execution["output_sha256"] = gate._item36_activation_output_sha256(
                execution
            )
        payload["health_routing"]["provider_readback"]["response_sha256"] = (
            gate._item36_health_response_sha256(
                payload["health_routing"], payload["alb"]
            )
        )

        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 bounded rolling activation evidence invalid", errors)
        self.assertIn("Item36 rollback binding mismatch", errors)
        self.assertIn("Item36 backend identities are not distinct", errors)
        self.assertIn("Item36 post-activation freshness binding missing", errors)

    def test_item36_rejects_api_f_first_even_with_recomputed_hashes(self):
        payload = self.item36_payload()
        executions = payload["activation"]["backend_executions"]
        executions.reverse()
        executions[0]["started_at"] = "2026-09-07T09:05:00+08:00"
        executions[0]["finished_at"] = "2026-09-07T09:07:00+08:00"
        executions[1]["started_at"] = "2026-09-07T09:08:00+08:00"
        executions[1]["finished_at"] = "2026-09-07T09:10:00+08:00"
        for execution in executions:
            execution["output_sha256"] = gate._item36_activation_output_sha256(
                execution
            )
        payload["activation"]["rollback_unit_sha256"] = (
            gate._item36_rollback_unit_sha256(executions)
        )
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 bounded rolling activation evidence invalid",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_wider_or_unbound_security_group_rule(self):
        payload = self.item36_payload()
        rule = payload["health_routing"]["security_group_rule"]
        rule["wider_ingress_rule_count"] = 1
        rule["source_identity_sha256"] = "9" * 64
        rule["response_sha256"] = gate._item36_security_group_response_sha256(
            rule, payload["alb"], payload["health_routing"]["backends"]
        )
        payload["health_routing"]["provider_readback"]["response_sha256"] = (
            gate._item36_health_response_sha256(
                payload["health_routing"], payload["alb"]
            )
        )
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 ALB-only security-group rule mismatch",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_probe_not_bound_to_pre_dns_endpoint(self):
        payload = self.item36_payload()
        probe = payload["health_routing"]["controlled_probe"]
        probe["endpoint_identity_sha256"] = "9" * 64
        probe["response_sha256"] = gate._item36_probe_response_sha256(
            probe, payload["alb"]
        )
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 controlled TLS probe mismatch",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_stale_billing_readback_even_when_hashes_match(self):
        payload = self.item36_payload()
        payload["alb"]["resource_created_at"] = "2026-09-01T00:00:00+08:00"
        payload["alb"]["configuration_readback"]["response_sha256"] = (
            gate._item36_configuration_response_sha256(payload["alb"])
        )
        billing_path = self.root / payload["costs"]["billing_readback_path"]
        billing = json.loads(billing_path.read_text(encoding="utf-8"))
        billing["observed_at"] = "2026-09-01T00:30:00+08:00"
        billing_path.write_text(json.dumps(billing), encoding="utf-8")
        payload["costs"]["billing_readback_sha256"] = hashlib.sha256(
            billing_path.read_bytes()
        ).hexdigest()

        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_reused_before_container_identity(self):
        payload = self.item36_payload()
        executions = payload["activation"]["backend_executions"]
        executions[1]["before_container_identity_sha256"] = executions[0][
            "before_container_identity_sha256"
        ]
        executions[1]["output_sha256"] = gate._item36_activation_output_sha256(
            executions[1]
        )
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 container identities are not distinct",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_huge_integer_cost_without_crashing(self):
        payload = self.item36_payload()
        payload["costs"]["actual_incurred_cny_to_observed_at"] = 10**1000
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_billing_readback_taken_before_final_probe(self):
        payload = self.item36_payload()
        billing_path = self.root / payload["costs"]["billing_readback_path"]
        billing = json.loads(billing_path.read_text(encoding="utf-8"))
        billing["observed_at"] = "2026-09-07T09:00:30+08:00"
        billing_path.write_text(json.dumps(billing), encoding="utf-8")
        payload["costs"]["billing_readback_sha256"] = hashlib.sha256(
            billing_path.read_bytes()
        ).hexdigest()

        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_internally_ordered_but_stale_evidence(self):
        payload = self.item36_payload()
        payload["observed_at"] = "2026-01-02T09:15:00+08:00"
        payload["alb"]["certificate_not_before"] = "2026-01-01T00:00:00+08:00"
        payload["alb"]["resource_created_at"] = "2026-01-02T09:00:00+08:00"
        payload["alb"]["configuration_readback"][
            "observed_at"
        ] = "2026-01-02T09:12:00+08:00"
        payload["health_routing"]["provider_readback"][
            "observed_at"
        ] = "2026-01-02T09:13:00+08:00"
        for backend in payload["health_routing"]["backends"]:
            backend["health_observed_at"] = "2026-01-02T09:13:00+08:00"
        payload["health_routing"]["controlled_probe"][
            "executed_at"
        ] = "2026-01-02T09:14:00+08:00"
        payload["activation"]["started_at"] = "2026-01-02T09:05:00+08:00"
        payload["activation"]["finished_at"] = "2026-01-02T09:10:00+08:00"
        payload["activation"]["fresh_ndr"][
            "observed_at"
        ] = "2026-01-02T09:11:00+08:00"
        payload["costs"].update(
            {
                "quote_observed_at": "2025-12-31T10:00:00+08:00",
                "approved_at": "2026-01-01T12:00:00+08:00",
                "quote_valid_until": "2026-01-05T10:00:00+08:00",
            }
        )
        approval_path = self.root / payload["costs"]["approval_artifact_path"]
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval.update(
            {
                "quote_observed_at": payload["costs"]["quote_observed_at"],
                "approved_at": payload["costs"]["approved_at"],
                "quote_valid_until": payload["costs"]["quote_valid_until"],
            }
        )
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
        payload["costs"]["approval_artifact_sha256"] = hashlib.sha256(
            approval_path.read_bytes()
        ).hexdigest()
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 observation clock invalid", errors)
        self.assertIn("Item36 bounded rolling activation evidence invalid", errors)

    def test_item36_binds_cost_approval_and_enforces_ceiling(self):
        payload = self.item36_payload()
        payload["costs"]["actual_incurred_cny_to_observed_at"] = 999999.0
        payload["costs"]["approval_artifact_sha256"] = "f" * 64
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_enforces_separate_variable_egress_ceiling(self):
        payload = self.item36_payload()
        costs = payload["costs"]
        costs["actual_variable_egress_cny_to_observed_at"] = 21.0
        costs["actual_incurred_cny_to_observed_at"] = 21.01
        billing_path = self.root / costs["billing_readback_path"]
        billing = json.loads(billing_path.read_text(encoding="utf-8"))
        for line in billing["line_items"]:
            if line["service"] == "public_egress":
                line["actual_incurred_cny"] = 21.0
        billing["actual_incurred_cny"] = 21.01
        billing_path.write_text(json.dumps(billing), encoding="utf-8")
        costs["billing_readback_sha256"] = hashlib.sha256(
            billing_path.read_bytes()
        ).hexdigest()
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_egress_headroom_cannot_hide_fixed_cost_overrun(self):
        payload = self.item36_payload()
        costs = payload["costs"]
        costs["actual_incurred_cny_to_observed_at"] = 199.0
        billing_path = self.root / costs["billing_readback_path"]
        billing = json.loads(billing_path.read_text(encoding="utf-8"))
        for line in billing["line_items"]:
            line["actual_incurred_cny"] = (
                199.0 if line["service"] == "alb_instance" else 0.0
            )
        billing["actual_incurred_cny"] = 199.0
        billing_path.write_text(json.dumps(billing), encoding="utf-8")
        costs["billing_readback_sha256"] = hashlib.sha256(
            billing_path.read_bytes()
        ).hexdigest()
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_semantically_fabricated_quote_and_billing(self):
        payload = self.item36_payload()
        costs = payload["costs"]
        quote_path = self.root / costs["quote_artifact_path"]
        quote = json.loads(quote_path.read_text(encoding="utf-8"))
        quote["provider"] = "fabricated_provider"
        quote_path.write_text(json.dumps(quote), encoding="utf-8")
        quote_sha = hashlib.sha256(quote_path.read_bytes()).hexdigest()
        costs["quote_sha256"] = quote_sha
        approval_path = self.root / costs["approval_artifact_path"]
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval["quote_sha256"] = quote_sha
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
        costs["approval_artifact_sha256"] = hashlib.sha256(
            approval_path.read_bytes()
        ).hexdigest()

        billing_path = self.root / costs["billing_readback_path"]
        billing = json.loads(billing_path.read_text(encoding="utf-8"))
        billing["actual_incurred_cny"] = 0.02
        billing_path.write_text(json.dumps(billing), encoding="utf-8")
        costs["billing_readback_sha256"] = hashlib.sha256(
            billing_path.read_bytes()
        ).hexdigest()

        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 recurring-cost approval missing",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )

    def test_item36_rejects_sensitive_or_unknown_fields(self):
        payload = self.item36_payload()
        payload["private_key"] = "synthetic-test-only"
        payload["alb"]["cookie"] = "synthetic-test-only"
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        errors = gate.validate_item36_alb_evidence(
            control, root=self.root, now=self.now
        )
        self.assertIn("Item36 terminal evidence schema mismatch", errors)
        self.assertIn("Item36 sensitive field present", errors)

    def test_item36_rejects_float_item_number(self):
        payload = self.item36_payload()
        payload["item"] = 36.0
        control = self.write(gate.ITEM36_ALB_EVIDENCE, payload)
        self.assertIn(
            "Item36 terminal status mismatch",
            gate.validate_item36_alb_evidence(
                control, root=self.root, now=self.now
            ),
        )


if __name__ == "__main__":
    unittest.main()
