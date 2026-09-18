"""Synthetic original artifacts exercise the real assemblers and final gate."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from tests import test_item33_v5_evidence_gate as fixtures
from tools import item33_trends_evidence_assembly as assembly
from tools import item33_trends_readback_assembly as facts


class Item33EvidenceAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.Item33V5EvidenceGateTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root, payload = self.fx.root, self.fx.payload
        gate = fixtures.gate
        cycle = payload["cycle"]
        snapshot = json.loads((self.root / payload["quality_snapshot"]["snapshot_ref"]).read_bytes())
        snapshot_raw = facts.encoded(snapshot)
        snapshot_sha = hashlib.sha256(snapshot_raw).hexdigest()
        (self.root / assembly.SNAPSHOT_REF).write_bytes(snapshot_raw)
        generated = snapshot["generated_at"]
        self.database = {**copy.deepcopy(cycle), "schema": "noteai.item33.database_cycle_readback.v1",
            "observed_at": "2026-09-19T00:15:00+00:00", "database_role": "noteai_xhs_trends",
            "server_enforced_read_only": True, "transaction_rolled_back": True, "xid_assigned": False,
            "provider_calls": 0, "production_database_writes": 0, "secret_values_recorded": False,
            "snapshot": {"sha256": snapshot_sha, "size": len(snapshot_raw), "payload": snapshot},
            "quality": {"domain_real_keyword_counts": payload["quality_snapshot"]["real_keyword_counts_by_domain"],
                "search_result_domains": payload["quality_snapshot"]["search_result_domains"],
                "search_recommend_domains": payload["quality_snapshot"]["search_recommend_domains"], "keyword_count": 90},
            "health_rows": [{"domain": domain, "status": "ok", "risk_login_detected": 0,
                "evidence_count": 15, "checked_at": generated} for domain in sorted(gate.ITEM32_TRENDS_DOMAINS)],
            "freshness_rows": [{"domain": domain, "status": "fresh", "evidence_count": 15,
                "evidence_date": cycle["bucket_key"], "acquired_at": generated,
                "fresh_until": "2026-09-21T00:09:00+00:00"} for domain in sorted(gate.ITEM32_TRENDS_DOMAINS)],
            "ledger": {"active_run_count": 0, "same_bucket_run_count": 1, "active_attempt_count": 0,
                "outcome_unknown_count": 0, "orphan_attempt_count": 0, "unlinked_attempt_count": 0, "idle_service_count": 1}}
        self.rehash_database(self.database)
        facts.checked_database_cycle(self.database)
        payload["recovery"]["preserved"] = facts.preserved_rows(self.database)
        self.fx.bind_normal_handoff()
        self.normal = copy.deepcopy(payload["normal_handoff"])
        self.artifacts = {str(path.relative_to(self.root)): path.read_bytes()
                          for path in (self.root / "deploy/production/evidence").iterdir() if path.is_file()}
        self.seal = json.loads(self.artifacts[gate.ITEM33_V5_CAPTURE_EVIDENCE])
        aggregate = assembly.capture.verify_capture_artifacts(self.seal, self.artifacts[gate.ITEM33_V5_CAPTURE_JOURNAL])
        receipt = json.loads(self.artifacts[gate.ITEM33_V5_HTTP_RECEIPT])
        http = {"state": "HTTP_PROOF_VERIFIED", "physical_http_verified": True, "worker_receipt": receipt,
            "physical_http": cycle["physical_http"], "worker_receipt_sha256": cycle["physical_http"]["worker_receipt_sha256"]}
        projected_cycle = facts.compose_cycle(self.database, http, self.seal, self.artifacts[gate.ITEM33_V5_CAPTURE_JOURNAL])
        preflight = copy.deepcopy(payload["readbacks"]["preflight"])
        preflight.update(unit_sha256=gate.ITEM33_SUSPENDED_UNIT_SHA256, collection_suspended=True)
        self.result = {"schema": assembly.controller.RESULT_SCHEMA, "status": "VERIFIED", "readiness_credit": False,
            "secret_values_recorded": False, "observed_at": "2026-09-19T00:35:00+00:00",
            "run_identity_sha256": cycle["run_identity_sha256"], "activation_identity_sha256": cycle["activation_identity_sha256"],
            "bucket_key": cycle["bucket_key"], "preflight": preflight, "cycle": projected_cycle,
            "capture_binding": {key: value for key, value in payload["release_binding"]["capture_binding"].items()
                                if key not in {"receipt_ref", "receipt_sha256"}},
            "authorization": {"provider_request_limit": 34},
            "action_counts": {"cycle": 1, "promotion": 1, "rollback": 1, "reapply": 1, "automatic_retry": 0}}
        for phase, state_key, minute in (("promoted", "promoted_readback", 15), ("rollback", "rollback_readback", 25), ("final", "final_readback", 35)):
            db = copy.deepcopy(self.database)
            db["observed_at"] = f"2026-09-19T00:{minute}:00+00:00"
            self.rehash_database(db)
            active = phase != "rollback"
            host = {"schema": "noteai.item33.host_facts.v1", "secret_values_recorded": False, "phase": phase,
                "observed_at": db["observed_at"], "activation_identity_sha256": cycle["activation_identity_sha256"],
                "unit_sha256": gate.ITEM33_V5_PROMOTED_UNIT_SHA256 if active else gate.ITEM33_SUSPENDED_UNIT_SHA256,
                "unit_active": "active" if active else "inactive", "unit_sub": "running" if active else "dead",
                "unit_enabled": "enabled" if active else "disabled", "collection_suspended": not active,
                "formal_unit_count": 1, "formal_container_count": int(active), "process_count": int(active),
                "capture_service_failure_present": False,
                **dict.fromkeys(("capture_container_count", "task_container_count", "inspection_container_count", "stage_directory_count",
                    "runtime_directory_count", "temporary_unit_count", "temporary_dropin_count"), 0)}
            host["canonical_sha256"] = facts.digest(host)
            self.result[state_key] = facts.compose_state(phase=phase, host=host, database=db,
                baseline=self.database, cycle=projected_cycle, aggregate=aggregate)
        for phase, before, after, minute in (("promotion", gate.ITEM33_SUSPENDED_UNIT_SHA256, gate.ITEM33_V5_PROMOTED_UNIT_SHA256, 0),
            ("rollback", gate.ITEM33_V5_PROMOTED_UNIT_SHA256, gate.ITEM33_SUSPENDED_UNIT_SHA256, 20),
            ("reapply", gate.ITEM33_SUSPENDED_UNIT_SHA256, gate.ITEM33_V5_PROMOTED_UNIT_SHA256, 30)):
            at = datetime(2026, 9, 19, 0, minute, tzinfo=timezone.utc)
            action = {"phase": phase, "activation_identity_sha256": cycle["activation_identity_sha256"],
                "bucket_key": cycle["bucket_key"], "before_unit_sha256": before, "after_unit_sha256": after,
                "observed_at": at.isoformat(), "completed_at": (at + timedelta(seconds=10)).isoformat(),
                "status": "APPLIED_REQUIRES_STATE_READBACK"}
            raw = assembly.encoded(action)
            self.artifacts[assembly.ACTION_REFS[phase]] = raw
            self.result[phase] = {"phase": phase, "status": "applied", "unit_name": "noteai-xhs-trends.service",
                "before_unit_sha256": before, "after_unit_sha256": after, "mutation_count": 1,
                "other_unit_actions": 0, "provider_calls": 0, "production_database_writes": 0,
                "canonical_result_sha256": hashlib.sha256(raw).hexdigest()}
        self.release = copy.deepcopy(payload["release_binding"])
        self.controls = {"cycle_authentication": {"source": "real_xhs", "authenticated_session": True},
            "managed_runtime": {key: copy.deepcopy(value) for key, value in payload["promotion"].items() if key not in {"before", "after"}},
            "cleanup": copy.deepcopy(payload["cleanup"]), "cost": copy.deepcopy(payload["cost"])}

    @staticmethod
    def rehash_database(database):
        database.pop("canonical_sha256", None)
        database["canonical_sha256"] = facts.digest(database)

    def assemble(self):
        return assembly.assemble_terminal(promotion_result=self.result, normal_handoff=self.normal,
            database_cycle=self.database, release_binding=self.release, artifacts=self.artifacts,
            control_facts=self.controls, observed_at=datetime(2026, 9, 19, 1, tzinfo=timezone.utc), source_root=self.root)

    def test_actual_shape_assembly_passes_original_gate_without_mocking_proofs(self):
        result = self.assemble()
        for meta in result["required_artifacts"]:
            self.assertEqual(meta["sha256"], hashlib.sha256(self.artifacts[meta["ref"]]).hexdigest())
            (self.root / meta["ref"]).write_bytes(self.artifacts[meta["ref"]])
        (self.root / fixtures.gate.ITEM33_TRENDS_PROMOTION_EVIDENCE).write_bytes(assembly.encoded(result["terminal"]))
        self.assertEqual(fixtures.gate.validate_item33_trends_promotion_evidence(self.fx.f.control,
            root=self.root, now=datetime(2026, 9, 20, tzinfo=timezone.utc)), [])
        self.assertEqual(result["terminal"]["cost"]["provider_fee_fen"], "UNKNOWN")

    def test_missing_original_close_teardown_or_http_is_not_substituted(self):
        for ref in (fixtures.gate.ITEM33_V5_CAPTURE_CLOSE_REFS["close"], fixtures.gate.ITEM33_V5_CAPTURE_TEARDOWN,
                    fixtures.gate.ITEM33_V5_HTTP_RECEIPT):
            raw = self.artifacts.pop(ref)
            with self.subTest(ref=ref), self.assertRaises(assembly.EvidenceAssemblyError): self.assemble()
            self.artifacts[ref] = raw

    def test_unknown_close_is_rejected_even_after_rebinding_its_hash(self):
        binding = self.normal["capture_close"]
        ref = binding["close_ref"]
        value = json.loads(self.artifacts[ref]); value["state"] = "CLOSE_UNKNOWN"
        self.artifacts[ref] = assembly.encoded(value)
        binding["close_sha256"] = hashlib.sha256(self.artifacts[ref]).hexdigest()
        with self.assertRaises(assembly.EvidenceAssemblyError): self.assemble()

    def test_action_times_and_hashes_are_original_not_assembly_clock(self):
        result = self.assemble()["terminal"]
        self.assertEqual(result["recovery"]["rollback_started_at"], "2026-09-19T00:20:00+00:00")
        self.artifacts[assembly.ACTION_REFS["rollback"]] += b" "
        with self.assertRaises(assembly.EvidenceAssemblyError): self.assemble()

    def test_missing_actual_runtime_or_authentication_does_not_default_to_success(self):
        del self.controls["cycle_authentication"]
        with self.assertRaises(assembly.EvidenceAssemblyError): self.assemble()

    def test_unknown_business_write_proof_is_not_terminal(self):
        ref = fixtures.gate.ITEM33_V5_CAPTURE_EVIDENCE
        value = json.loads(self.artifacts[ref]); value["catalog_proof"] = None
        self.artifacts[ref] = assembly.encoded(value)
        self.release["capture_binding"]["receipt_sha256"] = hashlib.sha256(self.artifacts[ref]).hexdigest()
        with self.assertRaises(assembly.EvidenceAssemblyError): self.assemble()

    def test_missing_counts_are_not_filled_and_boolean_zero_is_not_money(self):
        original = copy.deepcopy(self.controls)
        for defect in ("cleanup_missing", "cost_missing", "bool_money", "runtime_missing"):
            self.controls = copy.deepcopy(original)
            if defect == "cleanup_missing": del self.controls["cleanup"]["local_export_count"]
            elif defect == "cost_missing": del self.controls["cost"]["provider_fee_fen"]
            elif defect == "bool_money": self.controls["cost"]["provider_fee_fen"] = False
            else: del self.controls["managed_runtime"]["runtime"]["pids_limit"]
            with self.subTest(defect=defect), self.assertRaises(assembly.EvidenceAssemblyError): self.assemble()


if __name__ == "__main__":
    unittest.main()
