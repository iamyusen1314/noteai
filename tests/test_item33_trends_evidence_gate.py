import hashlib
import json
import shutil
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


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Item33TrendsEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        item32_path = self.root / gate.ITEM32_TRENDS_EVIDENCE
        item32_path.parent.mkdir(parents=True)
        self.item32_terminal = {
            "schema": gate.ITEM32_TRENDS_EVIDENCE_SCHEMA,
            "successor": {"budget": {"bucket_date": "2026-09-07"}},
        }
        item32_path.write_text(
            json.dumps(self.item32_terminal), encoding="utf-8"
        )
        executor = self.root / gate.ITEM33_TRENDS_PROMOTION_EXECUTOR
        executor.parent.mkdir(parents=True)
        executor.write_text("synthetic item33 executor\n", encoding="utf-8")
        executor_sha = hashlib.sha256(executor.read_bytes()).hexdigest()

        generated_at = "2026-09-08T00:05:00+00:00"
        snapshot = {
            "schema_version": 1,
            "generated_at": generated_at,
            "freshness_max_hours": 24,
            "domains": {},
        }
        for domain in sorted(gate.ITEM32_TRENDS_DOMAINS):
            rows = []
            for index in range(15):
                if index < 12 and index % 2 == 0:
                    source = "search_phrase"
                elif index < 12:
                    source = "search_recommend"
                else:
                    source = "industry_baseline"
                rows.append(
                    {
                        "keyword": f"{domain}-{index}",
                        "search_vol": 100 + index,
                        "trend_dir": 1,
                        "source": source,
                        "category": domain,
                        "sample_count": 1,
                        "quality_score": 70,
                        "evidence_level": "medium",
                        "quality_reason": "bounded publication row",
                        "captured_at": generated_at,
                    }
                )
            snapshot["domains"][domain] = {
                "captured_at": generated_at,
                "keywords": rows,
            }
        self.snapshot_ref = (
            "deploy/production/evidence/item33-trends-snapshot.json"
        )
        snapshot_path = self.root / self.snapshot_ref
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        snapshot_raw = snapshot_path.read_bytes()
        snapshot_sha = hashlib.sha256(snapshot_raw).hexdigest()
        snapshot_size = len(snapshot_raw)

        request_count = 34
        endpoints = (
            ["homefeed"] * 10
            + ["search_recommend"] * 12
            + ["search_notes"] * 12
        )
        attempts = []
        for ordinal, endpoint in enumerate(endpoints, start=1):
            attempts.append(
                {
                    "attempt_identity_sha256": digest(f"attempt:{ordinal}"),
                    "ordinal": ordinal,
                    "endpoint": endpoint,
                    "status": "succeeded",
                    "admitted_at": "2026-09-08T00:05:00+00:00",
                    "completed_at": "2026-09-08T00:05:30+00:00",
                }
            )
        published_counts = {
            domain: 15 for domain in gate.ITEM32_TRENDS_DOMAINS
        }
        real_counts = {domain: 12 for domain in gate.ITEM32_TRENDS_DOMAINS}
        self.payload = {
            "schema": gate.ITEM33_TRENDS_PROMOTION_EVIDENCE_SCHEMA,
            "item": 33,
            "status": "VERIFIED",
            "readiness_credit": True,
            "observed_at": "2026-09-08T01:00:00+00:00",
            "release_binding": {
                "outer_executor_ref": gate.ITEM33_TRENDS_PROMOTION_EXECUTOR,
                "outer_executor_sha256": executor_sha,
                "source_sha256": gate.ITEM32_EXPECTED_SOURCE_SHA256,
                "image_config_sha256": gate.ITEM32_EXPECTED_CONFIG_SHA256,
                "registry_manifest_sha256": (
                    gate.ITEM32_EXPECTED_MANIFEST_SHA256
                ),
                "suspended_unit_sha256": gate.ITEM33_SUSPENDED_UNIT_SHA256,
                "promoted_unit_sha256": gate.ITEM33_PROMOTED_UNIT_SHA256,
            },
            "cycle": {
                "run_identity_sha256": digest("run"),
                "bucket_key": "2026-09-08",
                "started_at": "2026-09-08T00:01:00+00:00",
                "completed_at": "2026-09-08T00:10:00+00:00",
                "lease_expires_at": "2026-09-08T00:31:00+00:00",
                "cycle_count": 1,
                "same_bucket_completed_run_count": 1,
                "source": "real_xhs",
                "authenticated_session": True,
                "challenge_detected": False,
                "provider_request_limit": 34,
                "provider_request_count": request_count,
                "provider_request_succeeded": request_count,
                "provider_request_failed": 0,
                "active_admitted_count": 0,
                "outcome_unknown_count": 0,
                "automatic_retry_count": 0,
                "endpoint_counts": {
                    "homefeed": 10,
                    "search_recommend": 12,
                    "search_notes": 12,
                },
                "attempts": attempts,
            },
            "quality_snapshot": {
                "snapshot_ref": self.snapshot_ref,
                "snapshot_sha256": snapshot_sha,
                "snapshot_size_bytes": snapshot_size,
                "snapshot_schema_version": 1,
                "snapshot_row_count": 1,
                "run_snapshot_sha256": snapshot_sha,
                "run_snapshot_size_bytes": snapshot_size,
                "real_keyword_counts_by_domain": real_counts,
                "search_result_domains": sorted(gate.ITEM32_TRENDS_DOMAINS),
                "search_recommend_domains": sorted(
                    gate.ITEM32_TRENDS_DOMAINS
                ),
                "published_keyword_counts_by_domain": published_counts,
                "published_keyword_count": 90,
            },
            "promotion": {
                "unit_name": "noteai-xhs-trends.service",
                "container_name": "noteai-xhs-trends",
                "database_role": "noteai_xhs_trends",
                "argv": [
                    "python",
                    "market_timing_worker.py",
                    "--daemon",
                    "--interval",
                    "360",
                ],
                "before": {
                    "active": "inactive",
                    "sub": "dead",
                    "enabled": "disabled",
                    "collection_suspended": True,
                    "formal_container_count": 0,
                },
                "after": {
                    "active": "active",
                    "sub": "running",
                    "enabled": "enabled",
                    "collection_suspended": False,
                    "formal_unit_count": 1,
                    "formal_container_count": 1,
                    "process_count": 1,
                    "service_state_row_count": 1,
                    "database_service_status": "idle",
                    "active_run_count": 0,
                    "active_attempt_count": 0,
                    "outcome_unknown_count": 0,
                    "unlinked_attempt_count": 0,
                    "health": "ready",
                },
                "runtime": {
                    "memory_bytes": 536870912,
                    "cpus_millis": 500,
                    "pids_limit": 64,
                    "user": "999:999",
                    "read_only": True,
                    "cap_drop": ["ALL"],
                    "no_new_privileges": True,
                    "log_driver": "local",
                    "log_max_size": "10m",
                    "log_max_file": 2,
                },
                "singleton_winner_count": 1,
                "restart_policy": "no",
                "automatic_restart_count": 0,
            },
            "recovery": {
                "status": "VERIFIED",
                "scope": "trends_only",
                "rollback_count": 1,
                "rollback_started_at": "2026-09-08T00:20:00+00:00",
                "rollback_completed_at": "2026-09-08T00:25:00+00:00",
                "rollback_final": {
                    "active": "inactive",
                    "sub": "dead",
                    "enabled": "disabled",
                    "collection_suspended": True,
                    "formal_container_count": 0,
                },
                "other_unit_actions": 0,
                "provider_call_delta": 0,
                "database_audit_deletes": 0,
                "preserved": {
                    "run_count": 1,
                    "attempt_count": request_count,
                    "snapshot_count": 1,
                    "run_sha256": digest("run-row"),
                    "attempt_ledger_sha256": digest("attempt-ledger"),
                    "snapshot_sha256": snapshot_sha,
                },
                "reapplied_promoted_unit_sha256": (
                    gate.ITEM33_PROMOTED_UNIT_SHA256
                ),
                "reapplied_at": "2026-09-08T00:30:00+00:00",
                "manual_start_count": 1,
                "restart_policy": "no",
                "same_bucket": {
                    "bucket_key": "2026-09-08",
                    "new_run_delta": 0,
                    "provider_call_delta": 0,
                },
                "final": {
                    "active": "active",
                    "sub": "running",
                    "enabled": "enabled",
                    "collection_suspended": False,
                    "formal_unit_count": 1,
                    "formal_container_count": 1,
                    "process_count": 1,
                    "health": "ready",
                },
            },
            "production_write_set": {
                "tables": sorted(gate.ITEM33_ALLOWED_WRITE_TABLES),
                "distinct_rows_touched_by_table": {
                    "xhs_trends_runs": 1,
                    "xhs_trends_service_state": 1,
                    "xhs_trends_provider_attempts": request_count,
                    "hot_keywords": 90,
                    "keyword_snapshots": 90,
                    "xhs_crawler_health": 6,
                    "xhs_freshness_ledger": 6,
                    "xhs_trends_snapshot_evidence": 1,
                },
                "out_of_contract_row_mutations": 0,
                "delete_rows": 0,
                "truncate_count": 0,
                "ddl_count": 0,
                "forbidden_table_mutations": {
                    key: 0 for key in gate.ITEM33_FORBIDDEN_WRITE_GROUPS
                },
                "atomic_publish": {
                    "business_pack_snapshot_run_success_one_transaction": True,
                    "attempt_audit_outside_transaction": True,
                },
            },
            "readbacks": {
                "preflight": {
                    "observed_at": "2026-09-08T00:00:00+00:00",
                    "canonical_sha256": digest("preflight"),
                    "database_role": "noteai_xhs_trends",
                    "role_exact": True,
                    "acl_exact": True,
                    "unit_active": "inactive",
                    "unit_sub": "dead",
                    "unit_enabled": "disabled",
                    "formal_container_count": 0,
                    "active_run_count": 0,
                    "same_bucket_run_count": 0,
                    "outcome_unknown_count": 0,
                    "unlinked_attempt_count": 0,
                    "utc_provider_budget_used_before": 0,
                    "utc_provider_budget_remaining_before": 34,
                    "provider_calls": 0,
                    "production_database_writes": 0,
                },
                "post_cycle": {
                    "observed_at": "2026-09-08T00:15:00+00:00",
                    "canonical_sha256": digest("post-cycle"),
                    "health": "ready",
                    "provider_calls": 0,
                    "production_database_writes": 0,
                },
                "rollback": {
                    "observed_at": "2026-09-08T00:25:00+00:00",
                    "canonical_sha256": digest("rollback"),
                    "provider_calls": 0,
                    "database_audit_deletes": 0,
                },
                "final": {
                    "observed_at": "2026-09-08T00:35:00+00:00",
                    "canonical_sha256": digest("final"),
                    "health": "ready",
                    "provider_calls": 0,
                    "production_database_writes": 0,
                },
            },
            "cleanup": {
                "task_container_count": 0,
                "inspection_container_count": 0,
                "stage_directory_count": 0,
                "runtime_directory_count": 0,
                "temporary_unit_count": 0,
                "temporary_dropin_count": 0,
                "local_snapshot_count": 0,
                "local_export_count": 0,
                "formal_managed_container_count": 1,
                "rollback_artifact_retained": True,
                "rollback_artifact_sha256": digest("rollback-artifact"),
            },
            "cost": {
                "currency": "CNY",
                "xhs_provider_requests": request_count,
                "provider_fee_fen": 0,
                "incremental_cloud_cost_fen": 0,
                "postpaid_resources_started": 0,
                "postpaid_resources_running": 0,
                "new_recurring_resource_count": 0,
                "new_recurring_monthly_fen": 0,
                "real_funds_fen": 0,
                "payment_actions": 0,
            },
            "secret_values_recorded": False,
        }
        self.path = self.root / gate.ITEM33_TRENDS_PROMOTION_EVIDENCE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.control = {
            "evidence": [
                {
                    "kind": "path",
                    "ref": gate.ITEM33_TRENDS_PROMOTION_EVIDENCE,
                }
            ]
        }

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        self.path.write_text(
            json.dumps(self.payload, ensure_ascii=False), encoding="utf-8"
        )
        return gate.validate_item33_trends_promotion_evidence(
            self.control,
            root=self.root,
            now=datetime(2026, 9, 9, tzinfo=timezone.utc),
        )

    def rewrite_snapshot(self, mutate):
        path = self.root / self.snapshot_ref
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        mutate(snapshot)
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        raw = path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        quality = self.payload["quality_snapshot"]
        quality["snapshot_sha256"] = sha256
        quality["run_snapshot_sha256"] = sha256
        quality["snapshot_size_bytes"] = len(raw)
        quality["run_snapshot_size_bytes"] = len(raw)
        self.payload["recovery"]["preserved"]["snapshot_sha256"] = sha256

    def use_effective_item32_release(self):
        # Reuse the complete Item32 fixture, including its real-source ledger
        # and approved synthetic plan; a source-only stub is not acceptance.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_item32_evidence_fixture", ROOT / "tests/test_item32_trends_evidence_gate.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = module.Item32TrendsEvidenceGateTests()
        fixture.setUp()
        try:
            self.assertEqual(fixture.validate(), [])
            shutil.copytree(fixture.root, self.root, dirs_exist_ok=True)
        finally:
            fixture.tearDown()
        item32_path = self.root / gate.ITEM32_TRENDS_EVIDENCE
        self.item32_terminal = json.loads(item32_path.read_text())
        self.payload["release_binding"].update(
            source_sha256=dict(gate.ITEM32_EFFECTIVE_SOURCE_SHA256),
            image_source_sha256=dict(gate.ITEM32_IMAGE_SOURCE_SHA256),
            runtime_overlay_sha256=dict(gate.ITEM32_RUNTIME_OVERLAY_SHA256),
            item32_terminal_sha256=hashlib.sha256(item32_path.read_bytes()).hexdigest(),
            promoted_unit_sha256=gate.ITEM33_EFFECTIVE_PROMOTED_UNIT_SHA256,
        )
        self.payload["recovery"]["reapplied_promoted_unit_sha256"] = (
            gate.ITEM33_EFFECTIVE_PROMOTED_UNIT_SHA256
        )

    def test_accepts_real_cycle_baseline_fill_and_singleton_recovery(self):
        self.assertEqual(self.validate(), [])

    def test_accepts_effective_item32_sources_and_exact_overlay_managed_unit(self):
        self.use_effective_item32_release()
        self.assertEqual(self.validate(), [])

    def test_effective_release_requires_fully_accepted_item32(self):
        self.use_effective_item32_release()
        self.item32_terminal["execution"]["automatic_retry_count"] = 1
        path = self.root / gate.ITEM32_TRENDS_EVIDENCE
        path.write_text(json.dumps(self.item32_terminal))
        self.payload["release_binding"]["item32_terminal_sha256"] = hashlib.sha256(
            path.read_bytes()).hexdigest()
        self.assertIn("Item33 release binding mismatch", self.validate())

    def test_effective_release_rejects_inherited_source_hash_or_unit_drift(self):
        self.use_effective_item32_release()
        original = json.loads(json.dumps(self.payload["release_binding"]))
        for key, value in (
            ("item32_terminal_sha256", "0" * 64),
            ("image_source_sha256", gate.ITEM32_EFFECTIVE_SOURCE_SHA256),
            ("runtime_overlay_sha256", {}),
            ("source_sha256", gate.ITEM32_EXPECTED_SOURCE_SHA256),
            ("promoted_unit_sha256", gate.ITEM33_PROMOTED_UNIT_SHA256),
        ):
            with self.subTest(key=key):
                self.payload["release_binding"] = {**original, key: value}
                self.assertIn("Item33 release binding mismatch", self.validate())

    def test_effective_release_cannot_omit_binding_or_reapply_legacy_unit(self):
        self.use_effective_item32_release()
        release = self.payload["release_binding"]
        for key in ("image_source_sha256", "runtime_overlay_sha256", "item32_terminal_sha256"):
            release.pop(key)
        release["source_sha256"] = gate.ITEM32_EXPECTED_SOURCE_SHA256
        release["promoted_unit_sha256"] = gate.ITEM33_PROMOTED_UNIT_SHA256
        self.assertIn("Item33 release binding mismatch", self.validate())
        self.use_effective_item32_release()
        self.payload["recovery"]["reapplied_promoted_unit_sha256"] = gate.ITEM33_PROMOTED_UNIT_SHA256
        self.assertIn("Item33 Trends-only rollback/no-replay mismatch", self.validate())

    def test_cost_accepts_actual_nonzero_or_explicit_unknown_without_new_resources(self):
        for provider, cloud in (("UNKNOWN", "UNKNOWN"), (125, 23), (0, "UNKNOWN")):
            with self.subTest(provider=provider, cloud=cloud):
                self.payload["cost"].update(provider_fee_fen=provider, incremental_cloud_cost_fen=cloud)
                self.assertEqual(self.validate(), [])

    def test_cost_rejects_ambiguous_unknown_invalid_amount_or_new_resource(self):
        for key, value in (
            ("provider_fee_fen", None), ("provider_fee_fen", "unknown"),
            ("provider_fee_fen", True), ("incremental_cloud_cost_fen", -1),
            ("incremental_cloud_cost_fen", 0.5), ("new_recurring_resource_count", 1),
            ("postpaid_resources_running", "UNKNOWN"), ("payment_actions", 1),
        ):
            with self.subTest(key=key, value=value):
                previous = self.payload["cost"][key]
                self.payload["cost"][key] = value
                self.assertIn("Item33 cost/resource boundary mismatch", self.validate())
                self.payload["cost"][key] = previous

    def test_rejects_cycle_in_item32_terminal_utc_bucket(self):
        item32_path = self.root / gate.ITEM32_TRENDS_EVIDENCE
        self.item32_terminal["successor"]["budget"]["bucket_date"] = (
            "2026-09-08"
        )
        item32_path.write_text(
            json.dumps(self.item32_terminal), encoding="utf-8"
        )
        self.assertIn(
            "Item33 UTC budget overlaps Item32 terminal cycle",
            self.validate(),
        )

    def test_requires_canonical_terminal_path(self):
        self.control["evidence"] = [{"kind": "path", "ref": "AGENTS.md"}]
        self.assertIn("exactly one", self.validate()[0])

    def test_rejects_unknown_or_sensitive_terminal_fields(self):
        self.payload["private_key"] = "synthetic"
        errors = self.validate()
        self.assertIn("Item33 terminal evidence schema mismatch", errors)
        self.assertIn("Item33 sensitive field present", errors)

    def test_rejects_release_or_promoted_unit_drift(self):
        self.payload["release_binding"]["promoted_unit_sha256"] = "0" * 64
        self.assertIn("Item33 release binding mismatch", self.validate())

    def test_rejects_cycle_limit_clock_or_endpoint_drift(self):
        cycle = self.payload["cycle"]
        cycle["provider_request_limit"] = 35
        cycle["lease_expires_at"] = "2026-09-08T00:09:00+00:00"
        cycle["endpoint_counts"]["homefeed"] = 3
        errors = self.validate()
        self.assertIn("Item33 real single-cycle proof mismatch", errors)
        self.assertIn("Item33 provider-attempt ledger mismatch", errors)

    def test_rejects_duplicate_or_nonterminal_attempt(self):
        attempts = self.payload["cycle"]["attempts"]
        attempts[1]["attempt_identity_sha256"] = attempts[0][
            "attempt_identity_sha256"
        ]
        attempts[2]["status"] = "admitted"
        self.assertIn("Item33 provider-attempt ledger mismatch", self.validate())

    def test_rejects_snapshot_or_six_domain_quality_drift(self):
        self.payload["quality_snapshot"]["real_keyword_counts_by_domain"][
            "美食"
        ] = 11
        self.assertIn("Item33 six-domain quality snapshot mismatch", self.validate())

    def test_rejects_snapshot_real_source_overclaim(self):
        self.rewrite_snapshot(
            lambda snapshot: snapshot["domains"]["美食"]["keywords"][0].__setitem__(
                "source", "industry_baseline"
            )
        )
        self.assertIn("Item33 six-domain quality snapshot mismatch", self.validate())

    def test_rejects_snapshot_without_recommend_coverage(self):
        def remove_published_recommend(snapshot):
            for domain in snapshot["domains"].values():
                for row in domain["keywords"]:
                    if row["source"] == "search_recommend":
                        row["source"] = "search_phrase"

        self.rewrite_snapshot(remove_published_recommend)
        self.assertIn("Item33 six-domain quality snapshot mismatch", self.validate())

    def test_rejects_partial_or_searchless_endpoint_sequence(self):
        cycle = self.payload["cycle"]
        cycle["provider_request_count"] = 10
        cycle["provider_request_succeeded"] = 10
        cycle["attempts"] = cycle["attempts"][:10]
        cycle["endpoint_counts"] = {
            "homefeed": 10,
            "search_recommend": 0,
            "search_notes": 0,
        }
        self.payload["cost"]["xhs_provider_requests"] = 10
        self.payload["recovery"]["preserved"]["attempt_count"] = 10
        self.payload["production_write_set"][
            "distinct_rows_touched_by_table"
        ]["xhs_trends_provider_attempts"] = 10
        self.assertIn("Item33 real single-cycle proof mismatch", self.validate())

    def test_accepts_weak_bounded_published_row(self):
        def weaken(snapshot):
            row = snapshot["domains"]["美食"]["keywords"][12]
            row["quality_score"] = 5
            row["evidence_level"] = "weak"

        self.rewrite_snapshot(weaken)
        self.assertEqual(self.validate(), [])

    def test_rejects_weak_real_source_overclaim(self):
        def weaken(snapshot):
            row = snapshot["domains"]["美食"]["keywords"][0]
            row["quality_score"] = 5
            row["evidence_level"] = "weak"

        self.rewrite_snapshot(weaken)
        self.assertIn("Item33 six-domain quality snapshot mismatch", self.validate())

    def test_rejects_cycle_completion_after_lease_expiry(self):
        self.payload["cycle"]["completed_at"] = (
            "2026-09-08T00:32:00+00:00"
        )
        self.assertIn("Item33 real single-cycle proof mismatch", self.validate())

    def test_rejects_cross_bucket_preflight_or_nonstandard_lease(self):
        self.payload["readbacks"]["preflight"]["observed_at"] = (
            "2026-09-06T23:59:00+00:00"
        )
        self.payload["cycle"]["lease_expires_at"] = (
            "2026-09-08T00:32:00+00:00"
        )
        errors = self.validate()
        self.assertIn("Item33 real single-cycle proof mismatch", errors)
        self.assertIn("Item33 provider-free readback/budget mismatch", errors)

    def test_rejects_readbacks_before_their_recovery_actions(self):
        self.payload["readbacks"]["rollback"]["observed_at"] = (
            "2026-09-08T00:16:00+00:00"
        )
        self.payload["readbacks"]["final"]["observed_at"] = (
            "2026-09-08T00:17:00+00:00"
        )
        self.assertIn(
            "Item33 provider-free readback/budget mismatch", self.validate()
        )

    def test_rejects_whitespace_duplicate_and_malformed_collections(self):
        def duplicate(snapshot):
            rows = snapshot["domains"]["美食"]["keywords"]
            rows[1]["keyword"] = f" {rows[0]['keyword']} "
            rows[2]["source"] = []

        self.rewrite_snapshot(duplicate)
        self.payload["cycle"]["attempts"][0]["endpoint"] = []
        self.payload["quality_snapshot"]["search_result_domains"][0] = {}
        self.payload["production_write_set"]["tables"][0] = {}
        errors = self.validate()
        self.assertIn("Item33 provider-attempt ledger mismatch", errors)
        self.assertIn("Item33 six-domain quality snapshot mismatch", errors)
        self.assertIn("Item33 production write-set mismatch", errors)

    def test_rejects_preflight_unknown_or_exhausted_daily_budget(self):
        preflight = self.payload["readbacks"]["preflight"]
        preflight["outcome_unknown_count"] = 1
        preflight["utc_provider_budget_used_before"] = 32
        preflight["utc_provider_budget_remaining_before"] = 2
        self.assertIn(
            "Item33 provider-free readback/budget mismatch", self.validate()
        )

    def test_rejects_preused_or_existing_same_bucket_run(self):
        preflight = self.payload["readbacks"]["preflight"]
        preflight["utc_provider_budget_used_before"] = 1
        preflight["utc_provider_budget_remaining_before"] = 33
        preflight["same_bucket_run_count"] = 1
        self.assertIn(
            "Item33 provider-free readback/budget mismatch", self.validate()
        )

    def test_rejects_non_singleton_or_restart_drift(self):
        promotion = self.payload["promotion"]
        promotion["singleton_winner_count"] = 2
        promotion["restart_policy"] = "on-failure"
        self.assertIn("Item33 managed singleton promotion mismatch", self.validate())

    def test_rejects_rollback_replay_or_audit_loss(self):
        recovery = self.payload["recovery"]
        recovery["same_bucket"]["provider_call_delta"] = 1
        recovery["database_audit_deletes"] = 1
        self.assertIn(
            "Item33 Trends-only rollback/no-replay mismatch", self.validate()
        )

    def test_rejects_write_scope_or_nonatomic_publish(self):
        writes = self.payload["production_write_set"]
        writes["tables"].append("system_settings")
        writes["atomic_publish"][
            "business_pack_snapshot_run_success_one_transaction"
        ] = False
        self.assertIn("Item33 production write-set mismatch", self.validate())

    def test_rejects_residue_or_resource_cost_type_drift(self):
        self.payload["cleanup"]["task_container_count"] = 1
        self.payload["cost"]["postpaid_resources_running"] = True
        errors = self.validate()
        self.assertIn("Item33 task-exact cleanup mismatch", errors)
        self.assertIn("Item33 cost/resource boundary mismatch", errors)


if __name__ == "__main__":
    unittest.main()
