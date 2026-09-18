"""Projection tests. Real capture proof is independently covered by PG tests."""
import copy
from datetime import timedelta
import hashlib
import unittest
from unittest import mock

from tools import item33_trends_readback_assembly as assembly
from tests import test_item33_trends_http_readback as http_fixtures


class ReadbackAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.http_fixture = http_fixtures.Item33HttpReadbackTests()
        self.http_fixture.setUp()
        self.http = self.http_fixture.read()
        self.database = copy.deepcopy(self.http_fixture.cycle)
        captured = (self.http_fixture.base + timedelta(seconds=25)).isoformat()
        payload = {"schema_version": 1, "generated_at": captured, "freshness_max_hours": 48,
            "domains": {domain: {"captured_at": captured, "keywords": [
                {"keyword": domain + "合成测试词" + str(i), "search_vol": 70, "trend_dir": 0,
                 "source": "search_phrase" if i == 0 else "search_recommend", "category": domain,
                 "sample_count": 3, "quality_score": 70, "evidence_level": "medium",
                 "quality_reason": "synthetic", "captured_at": captured} for i in range(12)]}
                for domain in sorted(assembly.accepted.DOMAINS)}}
        raw = assembly.encoded(payload)
        self.database.update(schema="noteai.item33.database_cycle_readback.v1",
            observed_at=(self.http_fixture.base + timedelta(minutes=1)).isoformat(),
            database_role="noteai_xhs_trends", server_enforced_read_only=True, transaction_rolled_back=True,
            xid_assigned=False, provider_calls=0, production_database_writes=0, secret_values_recorded=False,
            lease_expires_at=(self.http_fixture.base + timedelta(minutes=30)).isoformat(),
            provider_request_count=34, endpoint_counts={"homefeed": 10, "search_recommend": 12, "search_notes": 12},
            snapshot={"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "payload": payload},
            quality={"domain_real_keyword_counts": dict.fromkeys(sorted(assembly.accepted.DOMAINS), 12),
                "search_result_domains": sorted(assembly.accepted.DOMAINS), "search_recommend_domains": sorted(assembly.accepted.DOMAINS),
                "keyword_count": 72},
            health_rows=[{"domain": d, "status": "ok", "risk_login_detected": 0, "evidence_count": 12, "checked_at": captured}
                for d in sorted(assembly.accepted.DOMAINS)],
            freshness_rows=[{"domain": d, "status": "fresh", "evidence_count": 12, "evidence_date": "2026-09-19",
                "acquired_at": captured, "fresh_until": (self.http_fixture.base + timedelta(hours=48)).isoformat()}
                for d in sorted(assembly.accepted.DOMAINS)],
            ledger={"active_run_count": 0, "same_bucket_run_count": 1, "active_attempt_count": 0,
                "outcome_unknown_count": 0, "orphan_attempt_count": 0, "unlinked_attempt_count": 0, "idle_service_count": 1})
        self.rehash()
        self.aggregate = {"status": "ROW_CAPTURE_AGGREGATED_NOT_TERMINAL",
            "distinct_rows_touched_by_table": dict.fromkeys(assembly.dml.TABLE_KEYS, 1),
            "out_of_contract_row_mutations": 0, "delete_rows": 0, "truncate_count": 0,
            "forbidden_table_mutations": dict.fromkeys(sorted(assembly.dml.FORBIDDEN_GROUPS), 0),
            "atomic_publish": {"business_pack_snapshot_run_success_one_transaction": True,
                               "attempt_audit_outside_transaction": True}}
        self.aggregate["distinct_rows_touched_by_table"].update(xhs_trends_provider_attempts=34,
            hot_keywords=72, keyword_snapshots=72, xhs_crawler_health=6, xhs_freshness_ledger=6)
        self.seal = {"activation_identity_sha256": "a" * 64,
            "run_identity_sha256": self.database["run_identity_sha256"], "bucket_key": "2026-09-19"}

    def rehash(self):
        self.database.pop("canonical_sha256", None)
        self.database["canonical_sha256"] = assembly.digest(self.database)

    def compose(self):
        with mock.patch.object(assembly.capture, "verify_capture_artifacts", return_value=self.aggregate):
            return assembly.compose_cycle(self.database, self.http, self.seal, b"synthetic journal boundary")

    def host(self, phase="final"):
        active = phase != "rollback"
        result = {"schema": "noteai.item33.host_facts.v1", "secret_values_recorded": False,
            "phase": phase, "observed_at": self.database["observed_at"], "activation_identity_sha256": "a" * 64,
            "unit_sha256": assembly.controller.V5_NORMAL_UNIT_SHA256 if phase == "normal" else
                assembly.controller.V5_PROMOTED_UNIT_SHA256 if active else assembly.controller.SUSPENDED_UNIT_SHA256,
            "unit_active": "active" if active else "inactive", "unit_sub": "running" if active else "dead",
            "unit_enabled": "enabled" if active else "disabled", "collection_suspended": not active,
            "formal_unit_count": 1, "formal_container_count": int(active), "process_count": int(active),
            "capture_service_failure_present": False,
            **dict.fromkeys(("capture_container_count", "task_container_count", "inspection_container_count",
                "stage_directory_count", "runtime_directory_count", "temporary_unit_count", "temporary_dropin_count"), 0)}
        result["canonical_sha256"] = assembly.digest(result)
        return result

    def state(self, **changes):
        arguments = dict(phase="final", host=self.host(), database=self.database,
            baseline=copy.deepcopy(self.database), cycle=self.compose(), aggregate=self.aggregate)
        arguments.update(changes)
        return assembly.compose_state(**arguments)

    def test_actual_http_reader_and_snapshot_quality_project_to_existing_controller_contract(self):
        result = self.compose()
        receipt, _ = assembly.controller._validate_cycle(result, run_identity=None,
            bucket_key="2026-09-19", remaining=34, not_before=self.http_fixture.base,
            activation_identity="a" * 64)
        self.assertEqual(receipt["published_keyword_count"], 72)
        self.assertEqual(receipt["physical_http"]["total_count"], 36)

    def test_configuration_or_http_success_does_not_replace_six_domain_health(self):
        self.database["health_rows"].pop()
        self.rehash()
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "cycle_domain_health"):
            self.compose()

    def test_unknown_ledger_is_not_erased_by_completed_run(self):
        self.database["ledger"]["outcome_unknown_count"] = 1
        self.rehash()
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "cycle_ledger"):
            self.compose()

    def test_stale_freshness_rejects(self):
        self.database["freshness_rows"][0]["fresh_until"] = self.database["completed_at"]
        self.rehash()
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "cycle_freshness"):
            self.compose()

    def test_different_capture_run_rejects(self):
        self.seal["run_identity_sha256"] = "f" * 64
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "capture_cycle_binding"):
            self.compose()

    def test_real_receipt_recheck_rejects_changed_http_event(self):
        self.http["worker_receipt"]["physical_http_observations"][1]["response_diagnostics"]["http_status"] = 503
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "http_unproven"):
            self.compose()

    def test_forbidden_write_cannot_be_projected_as_success(self):
        self.aggregate["forbidden_table_mutations"]["payment"] = 1
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "capture_cycle_binding"):
            self.compose()

    def test_missing_catalog_or_stream_proof_cannot_be_projected_as_success(self):
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "http_or_capture_unproven"):
            assembly.compose_cycle(self.database, self.http, self.seal, b"not a sealed journal")

    def test_state_projects_preserved_rows_to_original_controller(self):
        result = self.state()
        assembly.controller._validate_state(result, phase="final", active=True,
            not_before=assembly.timestamp(self.database["completed_at"]), expected_attempt_count=34,
            runtime_profile=assembly.controller.V5_PROFILE, activation_identity="a" * 64,
            run_identity=self.database["run_identity_sha256"])

    def test_new_host_timestamp_does_not_hide_old_database_readback(self):
        host = self.host()
        host["observed_at"] = (assembly.timestamp(host["observed_at"]) + timedelta(minutes=5)).isoformat()
        host.pop("canonical_sha256")
        host["canonical_sha256"] = assembly.digest(host)
        self.assertEqual(self.state(host=host)["observed_at"], self.database["observed_at"])

    def test_incomplete_collector_close_rejects_even_with_complete_cycle(self):
        for field, value in (("capture_container_count", 1), ("capture_service_failure_present", True)):
            with self.subTest(field=field):
                host = self.host()
                host[field] = value
                host.pop("canonical_sha256")
                host["canonical_sha256"] = assembly.digest(host)
                with self.assertRaisesRegex(assembly.Item33AssemblyError, "state_binding"):
                    self.state(host=host)

    def test_preserved_run_identity_must_match_actual_cycle(self):
        baseline = copy.deepcopy(self.database)
        baseline["lease_expires_at"] = (assembly.timestamp(baseline["lease_expires_at"]) + timedelta(seconds=1)).isoformat()
        baseline.pop("canonical_sha256")
        baseline["canonical_sha256"] = assembly.digest(baseline)
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "state_binding"):
            self.state(baseline=baseline)

    def test_normal_handoff_projects_real_host_and_unchanged_rows(self):
        result = assembly.compose_normal(host=self.host("normal"), database=self.database,
            baseline=copy.deepcopy(self.database), cycle=self.compose(), seal_raw=b"seal", teardown_raw=b"teardown", capture_close={})
        self.assertEqual(result["preserved"], assembly.preserved_rows(self.database))
        self.assertEqual(result["same_bucket"], {"bucket_key": "2026-09-19", "new_run_delta": 0, "provider_call_delta": 0})
        self.assertEqual(result["teardown_sha256"], hashlib.sha256(b"teardown").hexdigest())

    def test_normal_handoff_refuses_instrumented_runtime(self):
        with self.assertRaisesRegex(assembly.Item33AssemblyError, "normal_binding"):
            assembly.compose_normal(host=self.host(), database=self.database,
                baseline=self.database, cycle=self.compose(), seal_raw=b"seal", teardown_raw=b"teardown", capture_close={})


if __name__ == "__main__":
    unittest.main()
