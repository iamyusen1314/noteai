import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import internal_deployment_readiness_gate as gate


class Item32TrendsEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        # Synthetic fixtures bind the checked-out source, never rewrite the
        # sealed v2 plan or the production gate's historical digest constants.
        overlays = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in gate.ITEM32_RUNTIME_OVERLAY_SHA256}
        for name, value in (("ITEM32_RUNTIME_OVERLAY_SHA256", overlays),
                            ("ITEM32_EFFECTIVE_SOURCE_SHA256", {**gate.ITEM32_IMAGE_SOURCE_SHA256, **overlays})):
            patcher = mock.patch.object(gate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ref = (
            "deploy/production/evidence/"
            "production-item32-xhs-trends-readonly-verified.json"
        )
        self.path = self.root / self.ref
        self.path.parent.mkdir(parents=True)
        plan_source = ROOT / gate.ITEM32_EXECUTION_PLAN
        plan = json.loads(plan_source.read_text(encoding="utf-8"))
        # Synthetic source binding only: leave the sealed dated plan untouched.
        plan["outer_executor_sha256"] = hashlib.sha256(
            (ROOT / plan["outer_executor"]).read_bytes()
        ).hexdigest()
        plan["adapter_overlay_sha256"] = gate.ITEM32_RUNTIME_OVERLAY_SHA256[
            "model/spider_xhs_http.py"
        ]
        plan["image_source_sha256"] = dict(gate.ITEM32_IMAGE_SOURCE_SHA256)
        plan["source_sha256"] = dict(gate.ITEM32_EFFECTIVE_SOURCE_SHA256)
        # Authorized only inside this isolated synthetic fixture.
        plan["admission"].update(
            not_before_utc="2026-09-07T03:00:00+00:00",
            bucket_date_utc="2026-09-07",
            dispatch_deadline_utc="2026-09-07T04:40:00+00:00",
            must_finish_before_utc="2026-09-07T05:00:00+00:00",
        )
        plan["authorization"] = {
            "status": "AUTHORIZED", "confirmed_at_utc": "2026-09-06T12:00:00+00:00",
            "approved_scope_sha256": self.approval_digest(plan),
        }
        plan_target = self.root / gate.ITEM32_EXECUTION_PLAN
        plan_target.parent.mkdir(parents=True, exist_ok=True)
        plan_target.write_text(json.dumps(plan), encoding="utf-8")
        self.plan_target = plan_target
        self.plan = plan
        hold_source = ROOT / gate.ITEM32_HOLD_EVIDENCE
        hold_target = self.root / gate.ITEM32_HOLD_EVIDENCE
        hold_target.parent.mkdir(parents=True, exist_ok=True)
        hold_target.write_bytes(hold_source.read_bytes())
        for source_ref in plan["source_sha256"]:
            target = self.root / source_ref
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / source_ref).read_bytes())
        outer_executor = self.root / plan["outer_executor"]
        outer_executor.parent.mkdir(parents=True, exist_ok=True)
        outer_executor.write_bytes((ROOT / plan["outer_executor"]).read_bytes())
        counts = {domain: 12 for domain in gate.ITEM32_TRENDS_DOMAINS}
        generated_at = "2026-09-07T11:58:00+08:00"
        snapshot_ref = (
            "deploy/production/evidence/"
            "production-item32-xhs-trends-snapshot.json"
        )
        snapshot = self.root / snapshot_ref
        snapshot_payload = {
            "schema_version": 1,
            "generated_at": generated_at,
            "freshness_max_hours": 30,
            "domains": {
                domain: {
                    "captured_at": generated_at,
                    "keywords": [
                        {
                            "keyword": f"{domain}-real-{index}",
                            "search_vol": 10 + index,
                            "trend_dir": 1,
                            "source": (
                                "search_recommend"
                                if index == 0
                                else "search_phrase"
                            ),
                            "category": domain,
                            "sample_count": 1,
                            "quality_score": 80,
                            "evidence_level": "strong",
                            "quality_reason": "bounded real source",
                            "captured_at": generated_at,
                        }
                        for index in range(12)
                    ],
                }
                for domain in gate.ITEM32_TRENDS_DOMAINS
            },
        }
        snapshot.write_text(
            json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        snapshot_bytes = snapshot.read_bytes()
        self.snapshot_ref = snapshot_ref

        endpoint_sequence = (
            ["homefeed"] * 10
            + [
                endpoint
                for _ in range(12)
                for endpoint in ("search_recommend", "search_notes")
            ]
        )
        attempt_ref = (
            "deploy/production/evidence/"
            "production-item32-xhs-trends-attempt-audit.json"
        )
        self.attempt_payload = {
            "schema": gate.ITEM32_ATTEMPT_AUDIT_SCHEMA,
            "run_identity_sha256": "1" * 64,
            "task_store_identity_sha256": "2" * 64,
            "started_at": "2026-09-07T11:55:00+08:00",
            "finished_at": "2026-09-07T11:59:00+08:00",
            "provider_request_limit": 34,
            "attempts": [
                {
                    "ordinal": ordinal,
                    "endpoint": endpoint,
                    "status": "succeeded",
                    "admitted_at": "2026-09-07T11:56:00+08:00",
                    "completed_at": "2026-09-07T11:57:00+08:00",
                    "identity_sha256": hashlib.sha256(
                        f"attempt:{ordinal}:{endpoint}".encode()
                    ).hexdigest(),
                }
                for ordinal, endpoint in enumerate(endpoint_sequence, start=1)
            ],
            "secret_values_recorded": False,
        }
        self.attempt_ref = attempt_ref
        attempt_path = self.root / attempt_ref
        attempt_path.write_text(json.dumps(self.attempt_payload), encoding="utf-8")

        proof_ref = (
            "deploy/production/evidence/"
            "production-item32-database-zero-write-proof.json"
        )
        self.proof_payload = {
            "schema": gate.ITEM32_DATABASE_PROOF_SCHEMA,
            "run_identity_sha256": "1" * 64,
            "session_identity_sha256": "4" * 64,
            "server_enforced_read_only": True,
            "write_count": 0,
            "tuple_write_count": 0,
            "write_tables": [],
            "xid_assigned": False,
            "transaction_rolled_back": True,
            "before_observed_at": "2026-09-07T11:54:00+08:00",
            "after_observed_at": "2026-09-07T11:59:30+08:00",
            "readback_query_sha256": plan["database_readonly_probe_sha256"],
            "secret_values_recorded": False,
        }
        self.proof_ref = proof_ref
        proof_path = self.root / proof_ref
        proof_path.write_text(json.dumps(self.proof_payload), encoding="utf-8")
        self.payload = {
            "schema": gate.ITEM32_TRENDS_EVIDENCE_SCHEMA,
            "item": 32,
            "status": "VERIFIED",
            "readiness_credit": True,
            "observed_at": "2026-09-07T12:00:00+08:00",
            "successor": {
                "fresh_identity": True,
                "no_replay": True,
                "work_root_identity_sha256": "7" * 64,
                "predecessor_closure_sha256": (
                    gate.ITEM32_HOLD_EVIDENCE_SHA256
                ),
                "original_admission_sha256": (
                    gate.ITEM32_ORIGINAL_ADMISSION_SHA256
                ),
                "original_store_sha256": gate.ITEM32_ORIGINAL_STORE_SHA256,
                "diagnostic_admission_sha256": (
                    gate.ITEM32_DIAGNOSTIC_ADMISSION_SHA256
                ),
                "diagnostic_result_sha256": (
                    gate.ITEM32_DIAGNOSTIC_RESULT_SHA256
                ),
                "predecessor_provider_call_count": 2,
                "predecessors_unchanged": True,
                "budget": {
                    "bucket_date": "2026-09-07",
                    "used_before": 0,
                    "remaining_before": 34,
                    "planned": 34,
                    "limit": 34,
                },
                "runtime_readback": {
                    "observed_at": "2026-09-07T11:54:30+08:00",
                    "image_config_sha256": gate.ITEM32_EXPECTED_CONFIG_SHA256,
                    "registry_manifest_sha256": (
                        gate.ITEM32_EXPECTED_MANIFEST_SHA256
                    ),
                    "registry_manifest_provenance": (
                        "SEALED_RELEASE_ATTESTATION_PLUS_"
                        "FRESH_LOCAL_CONFIG_READBACK"
                    ),
                    "adapter_overlay_sha256": gate.ITEM32_RUNTIME_OVERLAY_SHA256[
                        "model/spider_xhs_http.py"
                    ],
                    "runtime_overlay_sha256": dict(gate.ITEM32_RUNTIME_OVERLAY_SHA256),
                    "user_agent_sha256": gate.ITEM32_USER_AGENT_SHA256,
                    "signer_asset_sha256": gate.ITEM32_SIGNER_ASSET_SHA256,
                    "user_agent_exact_match": True,
                },
            },
            "execution": {
                "cycle_count": 1,
                "provider_request_count": 34,
                "provider_request_limit": 34,
                "attempt_count": 34,
                "succeeded_attempt_count": 34,
                "automatic_retry_count": 0,
                "all_admitted_attempts_succeeded": True,
                "outcome_unknown_count": 0,
                "challenge_detected": False,
                "authenticated_session": True,
                "source": "real_xhs",
                "started_at": "2026-09-07T11:55:00+08:00",
                "finished_at": "2026-09-07T11:59:00+08:00",
                "run_identity_sha256": "1" * 64,
                "task_store_identity_sha256": "2" * 64,
                "container_identity_sha256": "3" * 64,
                "outer_executor_sha256": plan["outer_executor_sha256"],
                "execution_plan_sha256": hashlib.sha256(
                    plan_target.read_bytes()
                ).hexdigest(),
                "image_config_sha256": plan["existing_image_config_sha256"],
                "registry_manifest_sha256": plan[
                    "existing_registry_manifest_sha256"
                ],
                "source_sha256": plan["source_sha256"],
                "endpoint_counts": {
                    "homefeed": 10,
                    "search_recommend": 12,
                    "search_notes": 12,
                },
                "attempt_audit_ref": attempt_ref,
                "attempt_audit_sha256": hashlib.sha256(
                    attempt_path.read_bytes()
                ).hexdigest(),
            },
            "quality": {
                "real_keyword_counts_by_domain": counts,
                "keyword_count": sum(counts.values()),
                "search_result_domains": sorted(gate.ITEM32_TRENDS_DOMAINS),
                "search_recommend_domains": sorted(gate.ITEM32_TRENDS_DOMAINS),
                "snapshot_ref": snapshot_ref,
                "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                "snapshot_size": len(snapshot_bytes),
            },
            "production_database": {
                "server_enforced_read_only": True,
                "write_count": 0,
                "tuple_write_count": 0,
                "write_tables": [],
                "xid_assigned": False,
                "transaction_rolled_back": True,
                "session_identity_sha256": "4" * 64,
                "proof_ref": proof_ref,
                "proof_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                "before_observed_at": "2026-09-07T11:54:00+08:00",
                "after_observed_at": "2026-09-07T11:59:30+08:00",
            },
            "task_store": {
                "isolated": True,
                "production_database_url_present": False,
                "production_data_mount_present": False,
                "docker_socket_mount_present": False,
                "path_identity_sha256": "6" * 64,
            },
            "cleanup": {
                "task_container_count": 0,
                "postpaid_resources_started": 0,
            },
            "secret_values_recorded": False,
        }
        self.control = {
            "evidence": [{"kind": "path", "ref": self.ref}]
        }

    def rewrite_bound_artifact(self, ref, payload, evidence_field):
        path = self.root / ref
        path.write_text(json.dumps(payload), encoding="utf-8")
        evidence_field["proof_sha256" if "proof_ref" in evidence_field else "attempt_audit_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        return gate.validate_item32_trends_evidence(
            self.control,
            root=self.root,
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )

    @staticmethod
    def approval_digest(plan):
        scope = {key: value for key, value in plan.items() if key != "authorization"}
        return hashlib.sha256(json.dumps(
            scope, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()

    def test_accepts_one_bounded_real_cycle_with_zero_production_writes(self):
        self.assertEqual(self.validate(), [])

    def test_pending_or_changed_approval_scope_cannot_supply_terminal_credit(self):
        for pending in (True, False):
            with self.subTest(pending=pending):
                plan = json.loads(json.dumps(self.plan))
                if pending:
                    plan["authorization"] = {"status": "PENDING", "confirmed_at_utc": None,
                                             "approved_scope_sha256": None}
                else:
                    plan["admission"]["not_before_utc"] = "2026-09-07T02:00:00+00:00"
                self.plan_target.write_text(json.dumps(plan))
                self.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(
                    self.plan_target.read_bytes()).hexdigest()
                self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_same_day_finish_at_or_after_approved_end_is_rejected(self):
        for finish in ("2026-09-07T05:00:00+00:00", "2026-09-07T05:01:00+00:00"):
            with self.subTest(finish=finish):
                self.payload["execution"]["finished_at"] = finish
                self.payload["observed_at"] = "2026-09-07T05:02:00+00:00"
                self.assertIn("Item32 approved execution window mismatch", self.validate())

    def test_same_day_start_at_dispatch_deadline_is_rejected(self):
        self.payload["execution"]["started_at"] = "2026-09-07T04:40:00+00:00"
        self.payload["execution"]["finished_at"] = "2026-09-07T04:50:00+00:00"
        self.payload["observed_at"] = "2026-09-07T04:51:00+00:00"
        self.assertIn("Item32 approved execution window mismatch", self.validate())

    def test_approval_recorded_after_execution_started_is_rejected(self):
        self.plan["authorization"]["confirmed_at_utc"] = "2026-09-07T03:56:00+00:00"
        self.plan_target.write_text(json.dumps(self.plan))
        self.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(
            self.plan_target.read_bytes()).hexdigest()
        self.assertIn("Item32 approved execution window mismatch", self.validate())

    def test_accepts_labelled_baseline_without_counting_it_as_real(self):
        snapshot = self.root / self.snapshot_ref
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        for domain, bucket in payload["domains"].items():
            bucket["keywords"].extend(
                {
                    "keyword": f"{domain}-baseline-{index}",
                    "search_vol": 45,
                    "trend_dir": 0,
                    "source": "industry_baseline",
                    "category": domain,
                    "sample_count": 3,
                    "quality_score": 80,
                    "evidence_level": "strong",
                    "quality_reason": "labelled industry baseline",
                    "captured_at": payload["generated_at"],
                }
                for index in range(3)
            )
        snapshot.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        raw = snapshot.read_bytes()
        self.payload["quality"]["keyword_count"] = 90
        self.payload["quality"]["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
        self.payload["quality"]["snapshot_size"] = len(raw)
        self.assertEqual(self.validate(), [])

    def test_labelled_baseline_cannot_impersonate_real_coverage(self):
        snapshot = self.root / self.snapshot_ref
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        payload["domains"]["美食"]["keywords"][1]["source"] = (
            "industry_baseline"
        )
        snapshot.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        raw = snapshot.read_bytes()
        self.payload["quality"]["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
        self.payload["quality"]["snapshot_size"] = len(raw)
        self.assertIn("Item32 snapshot identity invalid", self.validate())

    def test_rejects_unbound_predecessor_budget_or_browser_runtime(self):
        self.payload["successor"]["diagnostic_result_sha256"] = "0" * 64
        self.payload["successor"]["budget"]["used_before"] = 1
        self.payload["successor"]["runtime_readback"][
            "user_agent_exact_match"
        ] = False
        errors = self.validate()
        self.assertIn("Item32 successor predecessor binding mismatch", errors)
        self.assertIn("Item32 successor UTC budget mismatch", errors)
        self.assertIn("Item32 successor runtime binding mismatch", errors)

    def test_runtime_requires_all_and_only_the_three_reviewed_overlays(self):
        runtime = self.payload["successor"]["runtime_readback"]
        correct = dict(gate.ITEM32_RUNTIME_OVERLAY_SHA256)
        mutations = [
            None,
            {key: value for key, value in correct.items()
             if key != "model/security_redaction.py"},
            {**correct, "model/hot_keywords.py": "0" * 64},
            {**correct, "model/unreviewed.py": "0" * 64},
        ]
        for overlay in mutations:
            with self.subTest(overlay=overlay):
                if overlay is None:
                    runtime.pop("runtime_overlay_sha256", None)
                else:
                    runtime["runtime_overlay_sha256"] = overlay
                expected_error = (
                    "Item32 successor runtime readback schema mismatch"
                    if overlay is None else "Item32 successor runtime binding mismatch"
                )
                self.assertIn(expected_error, self.validate())
        runtime["runtime_overlay_sha256"] = correct
        self.assertEqual(self.validate(), [])

    def test_effective_source_cannot_impersonate_frozen_image_or_omit_overlay(self):
        mutations = [
            ("image_source_sha256", {**self.plan["image_source_sha256"],
             "model/hot_keywords.py": gate.ITEM32_RUNTIME_OVERLAY_SHA256["model/hot_keywords.py"]}),
            ("source_sha256", {key: value for key, value in self.plan["source_sha256"].items()
             if key != "model/security_redaction.py"}),
        ]
        for field, sources in mutations:
            with self.subTest(field=field):
                plan = json.loads(json.dumps(self.plan))
                plan[field] = sources
                self.plan_target.write_text(json.dumps(plan), encoding="utf-8")
                self.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(
                    self.plan_target.read_bytes()
                ).hexdigest()
                self.assertIn("Item32 canonical execution plan binding mismatch", self.validate())

    def test_execution_and_actual_overlay_bytes_must_match_the_plan(self):
        execution = self.payload["execution"]
        execution["source_sha256"] = {**self.plan["source_sha256"],
                                      "model/hot_keywords.py": "0" * 64}
        self.assertIn("Item32 canonical executor/release binding mismatch", self.validate())
        execution["source_sha256"] = dict(self.plan["source_sha256"])
        target = self.root / "model/security_redaction.py"
        target.write_bytes(target.read_bytes() + b"\n# synthetic tamper\n")
        self.assertIn("Item32 canonical executor/release binding mismatch", self.validate())

    def test_rejects_terminal_before_successor_not_before_boundary(self):
        self.payload["successor"]["budget"]["bucket_date"] = "2026-09-06"
        self.payload["successor"]["runtime_readback"][
            "observed_at"
        ] = "2026-09-06T11:54:30+08:00"
        self.payload["execution"]["started_at"] = "2026-09-06T11:55:00+08:00"
        self.payload["execution"]["finished_at"] = "2026-09-06T11:59:00+08:00"
        errors = self.validate()
        self.assertIn("Item32 successor admission clock mismatch", errors)

    def test_rejects_stale_runtime_or_cross_bucket_attempt(self):
        self.payload["successor"]["runtime_readback"][
            "observed_at"
        ] = "2026-09-07T11:00:00+08:00"
        self.attempt_payload["attempts"][-1][
            "completed_at"
        ] = "2026-09-08T00:00:00+00:00"
        self.rewrite_bound_artifact(
            self.attempt_ref,
            self.attempt_payload,
            self.payload["execution"],
        )
        errors = self.validate()
        self.assertIn("Item32 successor admission clock mismatch", errors)
        self.assertIn("Item32 provider attempt audit binding mismatch", errors)

    def test_rejects_snapshot_generated_after_run_finished(self):
        snapshot = self.root / self.snapshot_ref
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        generated_at = "2026-09-07T11:59:30+08:00"
        payload["generated_at"] = generated_at
        for bucket in payload["domains"].values():
            bucket["captured_at"] = generated_at
            for row in bucket["keywords"]:
                row["captured_at"] = generated_at
        snapshot.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        raw = snapshot.read_bytes()
        self.payload["quality"]["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
        self.payload["quality"]["snapshot_size"] = len(raw)
        self.assertIn("Item32 snapshot identity invalid", self.validate())

    def test_rejects_production_write_or_weak_real_source_quality(self):
        self.payload["production_database"]["write_count"] = 1
        self.payload["quality"]["real_keyword_counts_by_domain"]["美食"] = 11
        errors = self.validate()
        self.assertIn(
            "Item32 production database zero-write proof missing",
            errors,
        )
        self.assertIn(
            "Item32 six-domain real-source quality mismatch",
            errors,
        )

    def test_rejects_bool_counts_and_malformed_domains_without_crashing(self):
        self.payload["execution"]["cycle_count"] = True
        self.payload["production_database"]["write_count"] = False
        self.payload["cleanup"]["task_container_count"] = False
        self.payload["quality"]["search_result_domains"] = [[]]
        errors = self.validate()
        self.assertIn("Item32 bounded real-XHS execution mismatch", errors)
        self.assertIn(
            "Item32 production database zero-write proof missing",
            errors,
        )
        self.assertIn("Item32 task-exact cleanup missing", errors)
        self.assertIn(
            "Item32 six-domain real-source quality mismatch",
            errors,
        )

    def test_rejects_noncanonical_request_shape_and_unbound_snapshot(self):
        self.payload["execution"]["endpoint_counts"]["homefeed"] = 10.0
        self.payload["execution"]["provider_request_count"] = 25
        snapshot = self.root / self.snapshot_ref
        snapshot.write_text("{}", encoding="utf-8")
        self.payload["quality"]["snapshot_sha256"] = hashlib.sha256(
            snapshot.read_bytes()
        ).hexdigest()
        self.payload["quality"]["snapshot_size"] = len(snapshot.read_bytes())
        errors = self.validate()
        self.assertIn("Item32 bounded real-XHS execution mismatch", errors)
        self.assertIn("Item32 endpoint request ledger mismatch", errors)
        self.assertIn("Item32 snapshot identity invalid", errors)

    def test_rejects_unbound_attempt_audit_and_nonbracketing_db_proof(self):
        self.attempt_payload["attempts"][0]["ordinal"] = 2
        self.rewrite_bound_artifact(
            self.attempt_ref,
            self.attempt_payload,
            self.payload["execution"],
        )
        for target in (self.proof_payload, self.payload["production_database"]):
            target["before_observed_at"] = "2026-09-05T11:54:00+08:00"
            target["after_observed_at"] = "2026-09-05T11:59:30+08:00"
        self.rewrite_bound_artifact(
            self.proof_ref,
            self.proof_payload,
            self.payload["production_database"],
        )
        errors = self.validate()
        self.assertIn("Item32 provider attempt audit binding mismatch", errors)
        self.assertIn(
            "Item32 production database zero-write proof missing",
            errors,
        )

    def test_rejects_sensitive_or_unknown_terminal_fields(self):
        self.payload["private_key"] = "synthetic-test-only"
        errors = self.validate()
        self.assertIn("Item32 terminal evidence schema mismatch", errors)
        self.assertIn("Item32 sensitive field present", errors)

    def test_rejects_fabricated_source_or_missing_recommend_source(self):
        snapshot = self.root / self.snapshot_ref
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        for bucket in payload["domains"].values():
            for row in bucket["keywords"]:
                row["source"] = "fabricated_source"
        snapshot.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        raw = snapshot.read_bytes()
        self.payload["quality"]["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
        self.payload["quality"]["snapshot_size"] = len(raw)
        self.assertIn("Item32 snapshot identity invalid", self.validate())

    def test_rejects_whitespace_keyword_duplicate(self):
        snapshot = self.root / self.snapshot_ref
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        rows = payload["domains"]["美食"]["keywords"]
        rows[1]["keyword"] = f" {rows[0]['keyword']} "
        snapshot.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        raw = snapshot.read_bytes()
        self.payload["quality"]["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
        self.payload["quality"]["snapshot_size"] = len(raw)
        self.assertIn("Item32 snapshot identity invalid", self.validate())

    def test_rejects_noncanonical_attempt_sequence(self):
        attempts = self.attempt_payload["attempts"]
        attempts[10]["endpoint"], attempts[11]["endpoint"] = (
            attempts[11]["endpoint"],
            attempts[10]["endpoint"],
        )
        self.rewrite_bound_artifact(
            self.attempt_ref,
            self.attempt_payload,
            self.payload["execution"],
        )
        self.assertIn(
            "Item32 provider attempt audit binding mismatch",
            self.validate(),
        )

    def test_rejects_collapsed_semantic_identity_domains(self):
        digest = "7" * 64
        execution = self.payload["execution"]
        execution["run_identity_sha256"] = digest
        execution["task_store_identity_sha256"] = digest
        execution["container_identity_sha256"] = digest
        self.attempt_payload["run_identity_sha256"] = digest
        self.attempt_payload["task_store_identity_sha256"] = digest
        self.rewrite_bound_artifact(
            self.attempt_ref,
            self.attempt_payload,
            execution,
        )
        database = self.payload["production_database"]
        database["session_identity_sha256"] = digest
        self.proof_payload["run_identity_sha256"] = digest
        self.proof_payload["session_identity_sha256"] = digest
        self.proof_payload["readback_query_sha256"] = digest
        self.rewrite_bound_artifact(
            self.proof_ref,
            self.proof_payload,
            database,
        )
        self.payload["task_store"]["path_identity_sha256"] = digest
        self.assertIn(
            "Item32 semantic identity domains are not distinct",
            self.validate(),
        )

    def test_rejects_float_item_number(self):
        self.payload["item"] = 32.0
        self.assertIn("Item32 terminal status mismatch", self.validate())

    def test_rejects_self_rebound_or_empty_canonical_plan(self):
        alternate = self.root / "tools" / "alternate.py"
        alternate.write_text("pass\n", encoding="utf-8")
        plan = dict(self.plan)
        plan["outer_executor"] = "tools/alternate.py"
        plan["outer_executor_sha256"] = hashlib.sha256(
            alternate.read_bytes()
        ).hexdigest()
        plan["source_sha256"] = {}
        self.plan_target.write_text(json.dumps(plan), encoding="utf-8")
        self.payload["execution"]["outer_executor_sha256"] = plan[
            "outer_executor_sha256"
        ]
        self.payload["execution"]["source_sha256"] = {}
        self.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(
            self.plan_target.read_bytes()
        ).hexdigest()
        errors = self.validate()
        self.assertIn("Item32 canonical execution plan binding mismatch", errors)
        self.assertIn("Item32 canonical executor/release binding mismatch", errors)

    def test_rejects_arbitrary_database_probe_digest(self):
        self.proof_payload["readback_query_sha256"] = "5" * 64
        self.rewrite_bound_artifact(
            self.proof_ref,
            self.proof_payload,
            self.payload["production_database"],
        )
        self.assertIn(
            "Item32 production database zero-write proof missing",
            self.validate(),
        )

    def test_rejects_each_critical_plan_binding_tamper(self):
        mutations = {
            "item": lambda plan: plan.__setitem__("item", 33),
            "status": lambda plan: plan.__setitem__("status", "VERIFIED"),
            "readiness": lambda plan: plan.__setitem__("readiness_credit", True),
            "unit": lambda plan: plan.__setitem__("existing_unit_sha256", "0" * 64),
            "config": lambda plan: plan.__setitem__(
                "existing_image_config_sha256", "0" * 64
            ),
            "manifest": lambda plan: plan.__setitem__(
                "existing_registry_manifest_sha256", "0" * 64
            ),
            "probe": lambda plan: plan.__setitem__(
                "database_readonly_probe_sha256", "0" * 64
            ),
            "bounds": lambda plan: plan["bounds"].__setitem__("cycles", 2),
            "prior_calls": lambda plan: plan.__setitem__(
                "provider_calls_dispatched", 1
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                plan = json.loads(json.dumps(self.plan))
                mutate(plan)
                self.plan_target.write_text(json.dumps(plan), encoding="utf-8")
                self.payload["execution"]["execution_plan_sha256"] = hashlib.sha256(
                    self.plan_target.read_bytes()
                ).hexdigest()
                self.assertIn(
                    "Item32 canonical execution plan binding mismatch",
                    self.validate(),
                )


if __name__ == "__main__":
    unittest.main()
