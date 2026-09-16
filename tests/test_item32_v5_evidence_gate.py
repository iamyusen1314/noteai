"""Synthetic v3 acceptance and negative evidence, no production or provider IO."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests import test_item32_trends_evidence_gate as legacy

gate, ROOT = legacy.gate, legacy.ROOT


class Item32V5EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.f = legacy.Item32TrendsEvidenceGateTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.addCleanup(self.f.tearDown)
        f = self.f
        def date(value):
            if isinstance(value, dict):
                return {k: date(v) for k, v in value.items()}
            if isinstance(value, list):
                return [date(v) for v in value]
            if isinstance(value, str) and value.startswith("2026-09-07"):
                return value.replace("2026-09-07", "2026-09-16", 1)
            return value
        f.payload, f.attempt_payload, f.proof_payload = map(date, (f.payload, f.attempt_payload, f.proof_payload))
        snapshot = f.root / f.snapshot_ref
        snapshot.write_text(json.dumps(date(json.loads(snapshot.read_text())), ensure_ascii=False))
        f.payload["quality"].update(snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                                    snapshot_size=len(snapshot.read_bytes()))
        f.rewrite_bound_artifact(f.payload["production_database"]["proof_ref"], f.proof_payload, f.payload["production_database"])
        plan = date(copy.deepcopy(f.plan))
        plan.update(schema="noteai.item32.readonly_successor_plan.v3",
                    existing_image_config_sha256=gate.ITEM32_V5_CONFIG_SHA256,
                    existing_registry_manifest_sha256=gate.ITEM32_V5_MANIFEST_SHA256,
                    physical_http_budget={"initialization": 2, "collection": 34, "total": 36})
        plan["runtime_overlay_sha256"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in gate.ITEM32_V5_OVERLAYS}
        plan["source_sha256"] = {**plan["image_source_sha256"], **plan["runtime_overlay_sha256"]}
        for name in [*plan["source_sha256"], "model/vendor/spider_xhs/v5/upstream.json"]:
            target = f.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        plan["browser_binding"] = {
            "protocol": "pc_v5", "curl_cffi_version": "0.15.0", "node_major": 20,
            "upstream_manifest_ref": "model/vendor/spider_xhs/v5/upstream.json",
            "upstream_manifest_sha256": gate.ITEM32_V5_UPSTREAM_SHA256,
            "cold_initialization": True, "first_homefeed_is_gate": True}
        plan["admission"]["work_root"] = "/var/lib/noteai/item32-v5-successor-20260916"
        base = "/var/lib/noteai/item32-readonly-successor"
        paths = [base + "/item32-admission.json", base + "/run-synthetic/worker-receipt.json",
                 base + "/run-synthetic/task-store/hot_keywords.db"]
        for stage in ("item32-successor-package-20260915-79e1e35", "item32-repair-package-20260915-fac5dd0"):
            paths.extend(f"/var/lib/noteai/{stage}/{name}" for name in
                         ("dispatch-started.json", "dispatch-child.json", "dispatch-done.json", "dispatch.log"))
        plan["previous_successor"] = {"work_root": base, "provider_call_count": 1, "no_replay": True,
            "files": {name: {"bytes": 1, "sha256": hashlib.sha256(name.encode()).hexdigest()} for name in paths}}
        f.plan = plan
        f.plan_target = f.root / gate.ITEM32_V5_EXECUTION_PLAN
        f.payload["schema"] = gate.ITEM32_V5_EVIDENCE_SCHEMA
        f.payload["successor"].update(predecessor_provider_call_count=3,
            work_root_identity_sha256=hashlib.sha256(b"noteai-item32:successor-work-root:/var/lib/noteai/item32-v5-successor-20260916").hexdigest(),
            previous_successor={"files_sha256": hashlib.sha256((json.dumps(plan["previous_successor"]["files"],
                ensure_ascii=False, sort_keys=True, indent=2)+"\n").encode()).hexdigest(),
                "provider_call_count": 1, "call_date_utc": "2026-09-15", "no_replay": True})
        f.payload["successor"]["runtime_readback"] = {
            "observed_at": "2026-09-16T03:54:00+00:00",
            "image_config_sha256": gate.ITEM32_V5_CONFIG_SHA256,
            "registry_manifest_sha256": gate.ITEM32_V5_MANIFEST_SHA256,
            "registry_manifest_provenance": plan["registry_manifest_provenance"],
            "adapter_overlay_sha256": plan["adapter_overlay_sha256"],
            "runtime_overlay_sha256": plan["runtime_overlay_sha256"],
            "protocol": "pc_v5", "curl_cffi_version": "0.15.0", "node_major": 20,
            "upstream_manifest_sha256": gate.ITEM32_V5_UPSTREAM_SHA256}
        f.payload["execution"].update(image_config_sha256=gate.ITEM32_V5_CONFIG_SHA256,
            registry_manifest_sha256=gate.ITEM32_V5_MANIFEST_SHA256, source_sha256=plan["source_sha256"])
        summary = {"initialization_count": 2, "collection_count": 34, "total_count": 36, "total_limit": 36,
                   "automatic_retry_count": 0, "first_homefeed_is_gate": True, "worker_receipt_sha256": "e"*64}
        f.payload["execution"]["physical_http"] = dict(summary)
        observations = []
        for index, kind in enumerate(["dsl", "session"] + [a["endpoint"] for a in f.attempt_payload["attempts"]]):
            first = datetime(2026, 9, 16, 3, 56, tzinfo=timezone.utc) + timedelta(seconds=index-2)
            observations.append({"phase": "dispatch", "request_kind": kind, "sequence": index+1, "at": first.isoformat()})
            diag = {"http_status": 200, "payload_kind": "non_json"} if kind == "dsl" else {
                "http_status": 200, "payload_kind": "object", "success_state": "true",
                "business_code_kind": "integer", "business_code": 0, "message_tags": []}
            observations.append({"phase": "response", "request_kind": kind, "sequence": index+1,
                                 "at": (first + timedelta(milliseconds=500)).isoformat(), "response_diagnostics": diag})
        f.attempt_payload["physical_http"] = {**summary, "observations": observations}
        self.rebind_plan()

    def rebind_plan(self):
        f = self.f
        f.plan["authorization"] = {"status": "AUTHORIZED", "confirmed_at_utc": "2026-09-15T12:00:00+00:00",
                                   "approved_scope_sha256": f.approval_digest(f.plan)}
        f.plan_target.write_text(json.dumps(f.plan))
        f.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(f.plan_target.read_bytes()).hexdigest()

    def validate(self):
        f = self.f
        f.rewrite_bound_artifact(f.attempt_ref, f.attempt_payload, f.payload["execution"])
        f.path.write_text(json.dumps(f.payload))
        return gate.validate_item32_trends_evidence(f.control, root=f.root, now=datetime(2026,9,17,tzinfo=timezone.utc))

    def test_accepts_complete_v3_without_weakening_original_quality(self):
        self.assertEqual(self.validate(), [])

    def test_missing_initialization_or_extra_requests_rejected(self):
        self.f.attempt_payload["physical_http"]["observations"] = self.f.attempt_payload["physical_http"]["observations"][4:]
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_business_failure_despite_http200_rejected(self):
        self.f.attempt_payload["physical_http"]["observations"][5]["response_diagnostics"]["business_code"] = -100
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_bool_business_zero_or_retry_count_cannot_pass(self):
        self.f.attempt_payload["physical_http"]["observations"][5]["response_diagnostics"]["business_code"] = False
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_physical_call_outside_ledger_admission_rejected(self):
        self.f.attempt_payload["physical_http"]["observations"][4]["at"] = "2026-09-16T03:55:59+00:00"
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_secret_extra_response_fields_rejected(self):
        self.f.attempt_payload["physical_http"]["observations"][5]["response_diagnostics"]["message"] = "unapproved text"
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_unknown_or_duplicate_terminal_rejected(self):
        self.f.attempt_payload["physical_http"]["observations"][5]["phase"] = "unknown"
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_physical_summary_must_match_original_observation_receipt(self):
        self.f.payload["execution"]["physical_http"]["worker_receipt_sha256"] = "d"*64
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_pending_or_changed_scope_has_no_credit(self):
        self.f.plan["authorization"]["status"] = "PENDING"
        self.f.plan_target.write_text(json.dumps(self.f.plan))
        self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_v3_cannot_drop_original_failure_closure(self):
        self.f.payload["successor"]["previous_successor"]["files_sha256"] = "f"*64
        self.assertIn("Item32 previous successor closure mismatch", self.validate())

    def test_boolean_counters_cannot_impersonate_no_retry_or_preserved_call(self):
        self.f.attempt_payload["physical_http"]["automatic_retry_count"] = False
        self.f.payload["successor"]["previous_successor"]["provider_call_count"] = True
        errors = self.validate()
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", errors)
        self.assertIn("Item32 previous successor closure mismatch", errors)

    def test_source_drift_and_old_base_image_rejected(self):
        self.f.payload["execution"]["image_config_sha256"] = gate.ITEM32_EXPECTED_CONFIG_SHA256
        self.assertIn("Item32 canonical executor/release binding mismatch", self.validate())

    def test_baseline_and_database_zero_write_still_required(self):
        self.f.payload["production_database"]["write_count"] = 1
        self.assertIn("Item32 production database zero-write proof missing", self.validate())

    def test_malformed_raw_diagnostics_and_changed_sequence_fail_closed(self):
        original = copy.deepcopy(self.f.attempt_payload)
        for field, value in (("payload_kind", []), ("business_code", "RAW_PRIVATE"),
                             ("business_code_kind", {}), ("http_status", True),
                             ("message_tags", ["login"])):
            with self.subTest(field=field):
                self.f.attempt_payload = copy.deepcopy(original)
                self.f.attempt_payload["physical_http"]["observations"][1]["response_diagnostics"][field] = value
                self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())
        self.f.attempt_payload = copy.deepcopy(original)
        self.f.attempt_payload["physical_http"]["observations"][4]["sequence"] = 2
        self.assertIn("Item32 physical HTTP/init/collection evidence mismatch", self.validate())

    def test_v3_cannot_credit_item33_using_the_old_promoted_unit(self):
        from tests import test_item33_trends_evidence_gate as item33
        import shutil
        self.assertEqual(self.validate(), [])
        f33 = item33.Item33TrendsEvidenceGateTests()
        f33.setUp()
        self.addCleanup(f33.tearDown)
        self.addCleanup(f33.doCleanups)
        shutil.copytree(self.f.root, f33.root, dirs_exist_ok=True)
        self.assertIn("Item33 v5 promoted runtime binding missing", f33.validate())


if __name__ == "__main__":
    unittest.main()
