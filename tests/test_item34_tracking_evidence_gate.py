import hashlib
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import internal_deployment_readiness_gate as gate


class Item34TrackingEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / gate.ITEM34_TRACKING_EVIDENCE
        self.path.parent.mkdir(parents=True)
        migration_path = self.root / gate.ITEM34_RUNTIME_CONFIG_MIGRATION
        migration_path.parent.mkdir(parents=True)
        migration_path.write_bytes(
            (ROOT / gate.ITEM34_RUNTIME_CONFIG_MIGRATION).read_bytes()
        )
        note_id = "6a7954010000000026034707"
        object_identity = hashlib.sha256(
            f"noteai-item34-xhs-note-v1:{note_id}".encode("ascii")
        ).hexdigest()
        track_identity = "c" * 64
        self.payload = {
            "schema": "noteai.item34.tracking_observation.v1",
            "item": 34,
            "status": "VERIFIED",
            "readiness_credit": True,
            "terminal_finalized_at": "2026-09-07T22:31:00+08:00",
            "production_preparation_20260907": {
                "runtime_config_migration": {
                    "path": gate.ITEM34_RUNTIME_CONFIG_MIGRATION,
                    "sha256": gate.ITEM34_RUNTIME_CONFIG_MIGRATION_SHA256,
                    "version": "0019_xhs_tracking_runtime_config.sql",
                    "ledger_source_sha256": (
                        gate.ITEM34_RUNTIME_CONFIG_MIGRATION_SHA256
                    ),
                    "ledger_exact_count": 1,
                    "search_path_binding": True,
                    "rls_contract_exact": True,
                    "policy_name": gate.ITEM34_RUNTIME_CONFIG_POLICY,
                    "production_policy_count": 1,
                    "policy_contract_count": 1,
                    "policy_qual_readback": gate.ITEM34_RUNTIME_CONFIG_POLICY_QUAL,
                    "policy_qual_readback_sha256": (
                        gate.ITEM34_RUNTIME_CONFIG_POLICY_QUAL_SHA256
                    ),
                    "production_status": "VERIFIED",
                    "schema_migrations_insert_count": 1,
                    "business_row_mutations": 0,
                    "ledger_readback": "VERIFIED",
                    "ledger_readback_sha256": None,
                }
            },
            "managed_tracking_row_started": True,
            "provider_calls": 2,
            "observation": {
                "note_id": note_id,
                "canonical_url": (
                    "https://www.xiaohongshu.com/explore/" + note_id
                ),
                "object_identity_sha256": object_identity,
                "observation_started_at": "2026-09-04T22:30:38+08:00",
                "managed_track": {
                    "identity_sha256": track_identity,
                    "object_identity_sha256": object_identity,
                    "submitted_at": "2026-09-04T22:30:38+08:00",
                    "ledger_readback": "VERIFIED",
                    "ledger_readback_sha256": "d" * 64,
                },
                "initial_snapshot": {
                    "observed_at": "2026-09-04T22:30:38+08:00",
                    "object_identity_sha256": object_identity,
                    "metrics": {"likes": 4, "saves": 2, "comments": 2},
                },
                "checkpoint_24h": {
                    "observed_at": "2026-09-05T22:30:38+08:00",
                    "object_identity_sha256": object_identity,
                    "managed_track_identity_sha256": track_identity,
                    "attempt_identity_sha256": "a" * 64,
                    "metrics": {"likes": 5, "saves": 2, "comments": 2},
                },
                "checkpoint_3d": {
                    "observed_at": "2026-09-07T22:30:38+08:00",
                    "object_identity_sha256": object_identity,
                    "managed_track_identity_sha256": track_identity,
                    "attempt_identity_sha256": "b" * 64,
                    "metrics": {"likes": 8, "saves": 3, "comments": 3},
                },
                "actual_provider_attempts": [
                    {
                        "canonical_stage": "24h",
                        "persisted_stage": "24h",
                        "status": "succeeded",
                        "ledger_readback": "VERIFIED",
                        "actual_supplier_call": True,
                        "call_count": 1,
                        "worker_mode": "once",
                        "round_limit": 1,
                        "run_provider_calls": 1,
                        "automatic_retry_count": 0,
                        "due_candidate_count_before": 1,
                        "due_target_match": True,
                        "force_used": False,
                        "other_row_mutations": 0,
                        "outcome_unknown_count_before": 0,
                        "outcome_unknown_count_after": 0,
                        "runtime_quiescent_before": True,
                        "runtime_quiescent_after": True,
                        "crawler_events_inserted": 1,
                        "configuration_transition_used": True,
                        "configuration_row_mutations": 2,
                        "configuration_restored": True,
                        "premature_7d_attempt_count": 0,
                        "post_next_check_at": "2026-09-07T22:30:38+08:00",
                        "identity_sha256": "a" * 64,
                        "run_identity_sha256": "e" * 64,
                        "object_identity_sha256": object_identity,
                        "managed_track_identity_sha256": track_identity,
                        "admitted_at": "2026-09-05T22:30:38+08:00",
                        "completed_at": "2026-09-05T22:30:38+08:00",
                    },
                    {
                        "canonical_stage": "3d",
                        "persisted_stage": "7d",
                        "status": "succeeded",
                        "ledger_readback": "VERIFIED",
                        "actual_supplier_call": True,
                        "call_count": 1,
                        "worker_mode": "once",
                        "round_limit": 1,
                        "run_provider_calls": 1,
                        "automatic_retry_count": 0,
                        "due_candidate_count_before": 1,
                        "due_target_match": True,
                        "force_used": False,
                        "other_row_mutations": 0,
                        "outcome_unknown_count_before": 0,
                        "outcome_unknown_count_after": 0,
                        "runtime_quiescent_before": True,
                        "runtime_quiescent_after": True,
                        "crawler_events_inserted": 1,
                        "configuration_transition_used": True,
                        "configuration_row_mutations": 2,
                        "configuration_restored": True,
                        "training_eligible": False,
                        "score_window": "3d",
                        "growth_action": "url_crawl_3d",
                        "memory_window": "3d",
                        "memory_content_sha256": "9" * 64,
                        "identity_sha256": "b" * 64,
                        "run_identity_sha256": "f" * 64,
                        "object_identity_sha256": object_identity,
                        "managed_track_identity_sha256": track_identity,
                        "admitted_at": "2026-09-07T22:30:38+08:00",
                        "completed_at": "2026-09-07T22:30:38+08:00",
                    },
                ],
                "manual_fill_used": False,
                "backfill_used": False,
                "early_credit": False,
                "continuity_break_count": 0,
                "interruptions": [],
            },
            "managed_promotion": {
                "status": "VERIFIED",
                "singleton_winner_count": 1,
                "rollback_rehearsal": "PASS",
                "resource_controls": "PASS",
                "restart_controls": "PASS",
                "log_controls": "PASS",
                "alert_controls": "PASS",
                "health_check": "PASS",
                "execution_identity_sha256": "1" * 64,
                "immutable_artifact_sha256": "2" * 64,
                "managed_service_identity_sha256": "3" * 64,
                "bounded_validation_attempt_identity_sha256": "a" * 64,
            },
            "actual_production_write_set": {
                "tables": [
                    "schema_migrations",
                    "tracked_notes",
                    "tracking_provider_attempts",
                    "growth_records",
                    "user_memories",
                    "crawler_events",
                    "system_settings",
                ],
                "rows_by_table": {
                    "schema_migrations": 1,
                    "tracked_notes": 1,
                    "tracking_provider_attempts": 2,
                    "growth_records": 1,
                    "user_memories": 1,
                    "crawler_events": 2,
                    "system_settings": 1,
                },
                "row_mutations": 9,
                "out_of_contract_row_mutations": 0,
                "ledger_readback": "VERIFIED",
                "ledger_readback_sha256": None,
            },
            "secret_values_recorded": False,
        }
        self.control = {
            "evidence": [
                {"kind": "path", "ref": gate.ITEM34_TRACKING_EVIDENCE}
            ]
        }
        self._refresh_migration_readback_sha256()
        self._refresh_write_readback_sha256()

    def _refresh_migration_readback_sha256(self):
        migration = self.payload["production_preparation_20260907"][
            "runtime_config_migration"
        ]
        projection = {
            key: migration.get(key)
            for key in (
                "version",
                "ledger_source_sha256",
                "ledger_exact_count",
                "search_path_binding",
                "rls_contract_exact",
                "policy_name",
                "production_policy_count",
                "policy_contract_count",
                "policy_qual_readback",
                "policy_qual_readback_sha256",
                "schema_migrations_insert_count",
                "business_row_mutations",
            )
        }
        migration["ledger_readback_sha256"] = hashlib.sha256(
            json.dumps(
                projection,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()

    def _refresh_write_readback_sha256(self):
        writes = self.payload["actual_production_write_set"]
        projection = {
            "tables": sorted(writes["tables"]),
            "rows_by_table": writes["rows_by_table"],
            "row_mutations": writes["row_mutations"],
            "out_of_contract_row_mutations": writes[
                "out_of_contract_row_mutations"
            ],
        }
        if "authorized_auxiliary_effects" in self.payload:
            projection["authorized_auxiliary_effects"] = self.payload[
                "authorized_auxiliary_effects"
            ]
        writes["ledger_readback_sha256"] = hashlib.sha256(
            json.dumps(
                projection,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        self.path.write_text(
            json.dumps(self.payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return gate.validate_item34_tracking_evidence(
            self.control,
            root=self.root,
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )

    def validate_raw(self, raw):
        self.path.write_text(raw, encoding="utf-8")
        return gate.validate_item34_tracking_evidence(
            self.control,
            root=self.root,
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )

    def test_accepts_exact_real_24h_and_3d_evidence(self):
        self.assertEqual(self.validate(), [])

    def prospective_evidence(self):
        from tests.test_item34_tracking_checkpoint_executor import prospective_binding
        import execute_item34_tracking_checkpoint as checkpoint
        bound=prospective_binding()
        bound['observation_started_at']='2026-09-11T14:30:38+00:00'
        track_hash=hashlib.sha256(f"noteai-item34-tracking-row-v1:{bound['track_id']}".encode('ascii')).hexdigest()
        legacy=copy.deepcopy(self.payload)
        legacy['observation']['managed_track']['identity_sha256']=track_hash
        legacy.update(status='FAILED_24H_OLD_WINDOW_EXPIRED',readiness_credit=False)
        legacy['observation']['actual_provider_attempts']=[{
            'identity_sha256':hashlib.sha256(f"noteai-item34-tracking-attempt-row-v1:{bound['previous_attempt_id']}".encode('ascii')).hexdigest(),'status':'failed','error_code':'xhsadaptererror'}]
        legacy['actual_production_write_set']['rows_by_table']={
            'schema_migrations':1,'tracked_notes':1,'tracking_provider_attempts':1,'crawler_events':2,'system_settings':1}
        digest=hashlib.sha256(json.dumps(legacy,ensure_ascii=True,separators=(',',':'),sort_keys=True).encode('ascii')).hexdigest()
        pinned=mock.patch.object(gate,'ITEM34_SEALED_OBSERVATION_SHA256',digest)
        pinned.start();self.addCleanup(pinned.stop)
        def shift(value):
            if isinstance(value,dict):return {k:shift(v) for k,v in value.items()}
            if isinstance(value,list):return [shift(v) for v in value]
            if isinstance(value,str) and value.startswith('2026-') and 'T' in value:
                return (datetime.fromisoformat(value)+timedelta(days=7)).isoformat()
            return value
        new=shift(self.payload)
        with checkpoint.observation_context(bound):
            binding_sha=checkpoint.observation_identity()['observation_binding_sha256']
        new.update(observation_generation=1,observation_binding=bound,
                   observation_binding_sha256=binding_sha,previous_observation_sha256=digest)
        new['observation']['managed_track']=copy.deepcopy(legacy['observation']['managed_track'])
        for stage in ('checkpoint_24h','checkpoint_3d'):
            new['observation'][stage]['observation_binding_sha256']=binding_sha
            new['observation'][stage]['managed_track_identity_sha256']=track_hash
        for attempt in new['observation']['actual_provider_attempts']:
            attempt.update(observation_generation=1,observation_binding_sha256=binding_sha,
                           managed_track_identity_sha256=track_hash)
        original=self.payload;self.payload=new
        new['production_preparation_20260907']['runtime_config_migration']['schema_migrations_insert_count']=0
        self._refresh_migration_readback_sha256()
        aux=self._add_owner_auxiliary_effects()
        self.control['observation_authorization']={'authorization_checkpoint':'1'*40,'authorization_plan_sha256':'2'*64}
        aux.update(self.control['observation_authorization'])
        aux['authentication']=[]
        aux['policy_ddl']={'operation':'APPLY_EXACT_0020_VERIFY_EXISTING_0019',
                           'readback':'USE_EXISTING_MIGRATION_RECORDS'}
        self._refresh_write_readback_sha256()
        self.payload=original
        migration_path='model/migrations/postgres/0020_tracking_observation_generation.sql'
        (self.root/migration_path).write_bytes((ROOT/migration_path).read_bytes())
        sha=hashlib.sha256((ROOT/migration_path).read_bytes()).hexdigest()
        new['generation_migration']={'path':migration_path,'version':Path(migration_path).name,'sha256':sha,
            'ledger_source_sha256':sha,'ledger_exact_count':1,'schema_migrations_insert_count':1,
            'production_status':'VERIFIED','ledger_readback':'VERIFIED'}
        new['combined_production_write_set']={'rows_by_table':{'schema_migrations':2,'tracked_notes':1,
            'tracking_provider_attempts':3,'crawler_events':4,'system_settings':1,'growth_records':1,'user_memories':1},
            'distinct_rows':13,'provider_admissions':3,'ledger_readback':'VERIFIED'}
        legacy['prospective_observation']=new
        return legacy,new

    def test_prospective_branch_preserves_failed_history_and_default_accounting(self):
        legacy,new=self.prospective_evidence()
        self.path.write_text(json.dumps(legacy))
        now=datetime(2026,9,16,tzinfo=timezone.utc)
        errors=gate.validate_item34_tracking_evidence(self.control,root=self.root,now=now)
        self.assertIn('tracking terminal status mismatch',errors)
        control={**self.control,'observation_generation':1}
        self.assertEqual(gate.validate_item34_tracking_evidence(control,root=self.root,now=now),[])
        new['combined_production_write_set']['provider_admissions']=2
        self.path.write_text(json.dumps(legacy))
        self.assertIn('combined observation history accounting invalid',
            gate.validate_item34_tracking_evidence(control,root=self.root,now=now))
        self.assertEqual(legacy['status'],'FAILED_24H_OLD_WINDOW_EXPIRED')

    def test_prospective_branch_cannot_hide_changed_history_or_reuse_old_attempt(self):
        legacy,new=self.prospective_evidence()
        legacy['observation']['actual_provider_attempts'][0]['error_code']='changed'
        new['observation']['actual_provider_attempts'][0]['identity_sha256']=legacy['observation']['actual_provider_attempts'][0]['identity_sha256']
        self.path.write_text(json.dumps(legacy))
        errors=gate.validate_item34_tracking_evidence({**self.control,'observation_generation':1},
            root=self.root,now=datetime(2026,9,16,tzinfo=timezone.utc))
        self.assertIn('sealed failed observation history mismatch',errors)
        self.assertIn('old provider attempt reused by prospective observation',errors)

    def test_prospective_rejects_rehashed_history_changed_track_and_closed_approval(self):
        legacy,new=self.prospective_evidence()
        control={**self.control,'observation_generation':1}
        def errors():
            self.path.write_text(json.dumps(legacy))
            return gate.validate_item34_tracking_evidence(control,root=self.root,
                now=datetime(2026,9,16,tzinfo=timezone.utc))
        self.assertEqual(errors(),[])
        legacy['observation']['actual_provider_attempts'][0]['error_code']='different'
        old={k:v for k,v in legacy.items() if k!='prospective_observation'}
        new['previous_observation_sha256']=hashlib.sha256(json.dumps(old,ensure_ascii=True,
            separators=(',',':'),sort_keys=True).encode('ascii')).hexdigest()
        self.assertIn('sealed failed observation history mismatch',errors())
        new['observation']['managed_track']['submitted_at']='2026-09-11T14:30:38+00:00'
        self.assertIn('prospective observation changed original track',errors())
        new['authorized_auxiliary_effects']['authorization_checkpoint']='9802111a27b131e510c1c686870121baead5c45d'
        self.assertIn('Item34 authorized auxiliary effects invalid',errors())
        new['production_preparation_20260907']['runtime_config_migration']['schema_migrations_insert_count']=1
        self.assertIn('runtime config migration verification invalid',errors())

    def test_sealed_root_digest_matches_saved_canonical(self):
        actual=json.loads((ROOT/gate.ITEM34_TRACKING_EVIDENCE).read_text())
        actual.pop('prospective_observation',None)
        digest=hashlib.sha256(json.dumps(actual,ensure_ascii=True,
            separators=(',',':'),sort_keys=True).encode('ascii')).hexdigest()
        self.assertEqual(digest,gate.ITEM34_SEALED_OBSERVATION_SHA256)

    def _add_owner_auxiliary_effects(self):
        self.payload["authorized_auxiliary_effects"] = {
            "authorization_checkpoint": "9802111a27b131e510c1c686870121baead5c45d",
            "authorization_plan_sha256":
                "ae5b7fa36456dd01a7c1b9be63889d0e9d86298e54d354082c90859b0116e47d",
            "execution_record_ref": ".codex/handoffs/current-task.md",
            "authentication": [{
                "action": "existing_user_password_login",
                "outcome": "SUCCEEDED",
                "actual_committed_row_mutations": None,
                "count_basis": "SOURCE_BOUNDED_NOT_OBSERVED",
                "direct_row_mutations_upper_bound": 6,
            }],
            "policy_ddl": {
                "operation": "APPLY_EXACT_0019",
                "readback": "USE_EXISTING_RUNTIME_CONFIG_MIGRATION",
            },
            "temporary_attempts_select": [{
                "stage": stage, "grant_added": True,
                "original_acl_restored": True,
                "original_acl_sha256": "a" * 64,
                "restored_acl_sha256": "a" * 64,
            } for stage in ("24h", "3d")],
            "safety_flag": {
                "key": "xhs_collection_safety", "outcome": "NOT_NEEDED",
                "actual_committed_row_mutations": 0,
            },
            "unexpected_effects": [],
        }
        self._refresh_write_readback_sha256()
        return self.payload["authorized_auxiliary_effects"]

    def test_auxiliary_source_bound_keeps_unknown_count_and_core_nine(self):
        auxiliary = self._add_owner_auxiliary_effects()
        self.assertEqual(self.validate(), [])
        self.assertIsNone(auxiliary["authentication"][0]["actual_committed_row_mutations"])
        self.assertEqual(self.payload["actual_production_write_set"]["row_mutations"], 9)

    def _add_test_account_setup(self):
        auxiliary = self._add_owner_auxiliary_effects()
        setup = {
            "authorization_record_ref": ".codex/handoffs/current-task.md",
            "username_sha256": "56e5c09dfca80f6c2f70b328fc42af3c125bdd97c8beb47b93747f2e16cf7387",
            "user_identity_sha256": "c" * 64,
            "registration": {
                "outcome": "SUCCEEDED", "readback": "VERIFIED", "phone_bound": False,
                "actual_committed_row_mutations": None,
                "count_basis": "SOURCE_BOUNDED_NOT_OBSERVED", "direct_row_mutations_upper_bound": 4,
            },
            "credit_gift": {
                "outcome": "SUCCEEDED", "readback": "VERIFIED", "amount": 900,
                "type": "gift", "paid_rmb": 0, "balance_after": 900,
                "total_purchased_after": 0, "ledger_match_count": 1,
                "transaction_identity_sha256": "d" * 64, "replayed": False,
                "actual_committed_row_mutations": None,
                "count_basis": "SOURCE_BOUNDED_NOT_OBSERVED", "direct_row_mutations_upper_bound": 3,
            },
        }
        auxiliary["test_account_setup"] = setup
        self._refresh_write_readback_sha256()
        return setup

    def test_later_owner_test_account_scope_preserves_core_nine(self):
        self._add_test_account_setup()
        self.assertEqual(self.validate(), [])
        self.assertEqual(self.payload["actual_production_write_set"]["row_mutations"], 9)

    def test_owner_setup_rejects_other_identity_fake_phone_or_observed_counts(self):
        for mutate in (
            lambda s: s.update(username_sha256="e" * 64),
            lambda s: s["registration"].update(phone_bound=True),
            lambda s: s["registration"].update(actual_committed_row_mutations=4),
            lambda s: s.update(extra_account={}),
        ):
            setup = self._add_test_account_setup()
            mutate(setup)
            self._refresh_write_readback_sha256()
            self.assertIn("Item34 owner test account setup invalid", self.validate())

    def test_owner_setup_rejects_paid_topup_overgrant_replay_or_unproven_gift(self):
        for field, value in (("type", "topup"), ("amount", 901), ("paid_rmb", 270),
                             ("replayed", True), ("ledger_match_count", 2),
                             ("readback", "UNKNOWN"), ("actual_committed_row_mutations", 0)):
            setup = self._add_test_account_setup()
            setup["credit_gift"][field] = value
            self._refresh_write_readback_sha256()
            self.assertIn("Item34 owner test account setup invalid", self.validate())

    def test_owner_setup_is_in_existing_write_digest(self):
        self._add_test_account_setup()
        self.payload["authorized_auxiliary_effects"].pop("test_account_setup")
        self.assertIn("production write ledger digest invalid", self.validate())

    def test_owner_setup_does_not_extend_old_window_or_allow_failed_sample(self):
        self._add_test_account_setup()
        self.payload["observation"]["checkpoint_24h"]["observed_at"] = "2026-09-07T22:30:38+08:00"
        self.assertTrue(self.validate())

    def test_auxiliary_cannot_hide_unapproved_writes_or_unknown_as_zero(self):
        for field, value in (
            ("action", "create_user"), ("columns", ["credits"]),
            ("actual_committed_row_mutations", 0), ("outcome", "UNAPPROVED"),
        ):
            auxiliary = self._add_owner_auxiliary_effects()
            auxiliary["authentication"][0][field] = value
            self._refresh_write_readback_sha256()
            with self.subTest(field=field):
                self.assertIn("Item34 authorized auxiliary effects invalid", self.validate())

    def test_auxiliary_cannot_relabel_unobserved_count_as_verified_zero(self):
        auxiliary = self._add_owner_auxiliary_effects()
        auxiliary["authentication"][0].update(
            count_basis="READBACK_VERIFIED", actual_committed_row_mutations=0)
        self._refresh_write_readback_sha256()
        self.assertIn("Item34 authorized auxiliary effects invalid", self.validate())

    def test_lost_auth_response_keeps_unknown_count_without_relaxing_provider(self):
        auxiliary = self._add_owner_auxiliary_effects()
        auxiliary["authentication"][0]["outcome"] = "UNKNOWN"
        self._refresh_write_readback_sha256()
        self.assertEqual(self.validate(), [])
        self.payload["observation"]["actual_provider_attempts"][0]["status"] = "unknown"
        self.assertTrue(self.validate())

    def test_auxiliary_rejects_other_policy_privilege_and_unrestored_acl(self):
        mutations = (
            lambda a: a["policy_ddl"].update(operation="CREATE_OTHER_POLICY"),
            lambda a: a["temporary_attempts_select"][0].update(privilege="UPDATE"),
            lambda a: a["temporary_attempts_select"][0].update(original_acl_restored=False),
            lambda a: a["temporary_attempts_select"][0].update(restored_acl_sha256="b" * 64),
            lambda a: a["unexpected_effects"].append("unapproved_table"),
            lambda a: a["safety_flag"].update(outcome="BLOCKED", actual_committed_row_mutations=1),
        )
        for mutate in mutations:
            auxiliary = self._add_owner_auxiliary_effects()
            mutate(auxiliary)
            self._refresh_write_readback_sha256()
            self.assertIn("Item34 authorized auxiliary effects invalid", self.validate())

    def test_auxiliary_is_bound_into_original_ledger_digest(self):
        auxiliary = self._add_owner_auxiliary_effects()
        auxiliary["authentication"] = []
        self.assertIn("production write ledger digest invalid", self.validate())

    def test_auxiliary_does_not_relax_core_counts_clock_or_attempt_success(self):
        self._add_owner_auxiliary_effects()
        self.payload["actual_production_write_set"]["rows_by_table"]["crawler_events"] = 1
        self._refresh_write_readback_sha256()
        self.assertIn("terminal Tracking row counts invalid", self.validate())
        self.payload["actual_production_write_set"]["rows_by_table"]["crawler_events"] = 2
        self._refresh_write_readback_sha256()
        checkpoint = self.payload["observation"]["checkpoint_24h"]
        original = checkpoint["observed_at"]
        checkpoint["observed_at"] = "2026-09-07T22:30:38+08:00"
        self.assertTrue(self.validate())
        checkpoint["observed_at"] = original
        self.payload["observation"]["actual_provider_attempts"][0]["status"] = "failed"
        self.assertTrue(self.validate())

    def test_later_managed_row_does_not_reset_real_observation_anchor(self):
        self.payload["observation"]["managed_track"]["submitted_at"] = (
            "2026-09-05T10:00:00+08:00"
        )
        self.assertEqual(self.validate(), [])

    def test_rejects_terminal_checkpoint_before_actual_72_hours(self):
        self.payload["observation"]["checkpoint_3d"]["observed_at"] = (
            "2026-09-07T22:29:59+08:00"
        )
        self.assertIn("3d checkpoint credited early", self.validate())

    def test_rejects_24h_checkpoint_at_closed_72_hour_boundary(self):
        self.payload["observation"]["checkpoint_24h"]["observed_at"] = (
            "2026-09-07T22:30:38+08:00"
        )
        self.payload["observation"]["checkpoint_3d"]["observed_at"] = (
            "2026-09-07T22:30:39+08:00"
        )
        attempt = next(
            item
            for item in self.payload["observation"]["actual_provider_attempts"]
            if item["canonical_stage"] == "3d"
        )
        attempt["admitted_at"] = "2026-09-07T22:30:39+08:00"
        attempt["completed_at"] = "2026-09-07T22:30:39+08:00"
        self.payload["terminal_finalized_at"] = (
            "2026-09-07T22:30:40+08:00"
        )
        self.assertIn("24h checkpoint window closed", self.validate())

    def test_rejects_manual_or_backfilled_evidence(self):
        self.payload["observation"]["manual_fill_used"] = True
        self.payload["observation"]["backfill_used"] = True
        errors = self.validate()
        self.assertIn("manual fill cannot prove real observation", errors)
        self.assertIn("backfill cannot prove real observation", errors)

    def test_rejects_mismatched_initial_anchor(self):
        self.payload["observation"]["initial_snapshot"]["observed_at"] = (
            "2026-09-04T22:31:00+08:00"
        )
        self.assertIn("initial snapshot/start mismatch", self.validate())

    def test_rejects_different_self_consistent_note_identity(self):
        note_id = "6a7954010000000026034708"
        object_identity = hashlib.sha256(
            f"noteai-item34-xhs-note-v1:{note_id}".encode("ascii")
        ).hexdigest()
        observation = self.payload["observation"]
        observation["note_id"] = note_id
        observation["canonical_url"] = (
            "https://www.xiaohongshu.com/explore/" + note_id
        )
        observation["object_identity_sha256"] = object_identity
        observation["managed_track"]["object_identity_sha256"] = (
            object_identity
        )
        for checkpoint in (
            "initial_snapshot",
            "checkpoint_24h",
            "checkpoint_3d",
        ):
            observation[checkpoint]["object_identity_sha256"] = (
                object_identity
            )
        for attempt in observation["actual_provider_attempts"]:
            attempt["object_identity_sha256"] = object_identity

        self.assertIn(
            "canonical XHS note identity mismatch",
            self.validate(),
        )

    def test_rejects_shifted_self_consistent_observation_anchor(self):
        observation = self.payload["observation"]
        observation["observation_started_at"] = (
            "2026-09-04T23:30:38+08:00"
        )
        observation["initial_snapshot"]["observed_at"] = (
            "2026-09-04T23:30:38+08:00"
        )
        observation["checkpoint_24h"]["observed_at"] = (
            "2026-09-05T23:30:38+08:00"
        )
        observation["checkpoint_3d"]["observed_at"] = (
            "2026-09-07T23:30:38+08:00"
        )
        observation["actual_provider_attempts"][0]["admitted_at"] = (
            "2026-09-05T23:30:38+08:00"
        )
        observation["actual_provider_attempts"][0]["completed_at"] = (
            "2026-09-05T23:30:38+08:00"
        )
        observation["actual_provider_attempts"][0]["post_next_check_at"] = (
            "2026-09-07T23:30:38+08:00"
        )
        observation["actual_provider_attempts"][1]["admitted_at"] = (
            "2026-09-07T23:30:38+08:00"
        )
        observation["actual_provider_attempts"][1]["completed_at"] = (
            "2026-09-07T23:30:38+08:00"
        )
        self.payload["terminal_finalized_at"] = (
            "2026-09-07T23:31:00+08:00"
        )

        self.assertIn(
            "canonical observation anchor mismatch",
            self.validate(),
        )

    def test_rejects_future_terminal_clock(self):
        self.payload["terminal_finalized_at"] = "2026-09-09T22:31:00+08:00"
        self.assertIn(
            "future terminal_finalized_at prohibited",
            self.validate(),
        )

    def test_rejects_cross_object_or_unbound_attempt(self):
        self.payload["observation"]["checkpoint_24h"][
            "object_identity_sha256"
        ] = "9" * 64
        self.payload["observation"]["actual_provider_attempts"][0][
            "persisted_stage"
        ] = "7d"
        errors = self.validate()
        self.assertIn("provider attempt evidence invalid", errors)
        self.assertIn("24h checkpoint identity binding mismatch", errors)

    def test_rejects_unbounded_or_retried_worker_attempt(self):
        attempt = self.payload["observation"]["actual_provider_attempts"][0]
        attempt["round_limit"] = 50
        attempt["automatic_retry_count"] = 1
        self.assertIn("provider attempt evidence invalid", self.validate())

    def test_rejects_unknown_or_nonquiescent_attempt(self):
        attempt = self.payload["observation"]["actual_provider_attempts"][0]
        attempt["outcome_unknown_count_after"] = 1
        attempt["runtime_quiescent_after"] = False
        self.assertIn("provider attempt evidence invalid", self.validate())

    def test_rejects_inexact_config_transition_or_missing_crawler_event(self):
        attempt = self.payload["observation"]["actual_provider_attempts"][0]
        attempt["configuration_row_mutations"] = 1
        attempt["crawler_events_inserted"] = 0
        self.assertIn("provider attempt evidence invalid", self.validate())

    def test_rejects_untruthful_three_day_terminal_semantics(self):
        attempt = next(
            item
            for item in self.payload["observation"]["actual_provider_attempts"]
            if item["canonical_stage"] == "3d"
        )
        for key, invalid in (
            ("training_eligible", True),
            ("score_window", "7d"),
            ("growth_action", "url_crawl_7d"),
            ("memory_window", "7d"),
            ("memory_content_sha256", "bad"),
        ):
            original = attempt[key]
            attempt[key] = invalid
            with self.subTest(key=key):
                self.assertIn("3d terminal semantics invalid", self.validate())
            attempt[key] = original

    def test_rejects_sensitive_credential_shaped_field(self):
        for field in (
            "cookie",
            "a1",
            "web_session",
            "private_key",
            "access_token",
            "password",
        ):
            with self.subTest(field=field):
                self.payload[field] = "synthetic-sensitive-placeholder"
                self.assertIn(
                    "tracking evidence contains sensitive credential-shaped "
                    "field",
                    self.validate(),
                )
                del self.payload[field]

    def test_rejects_premature_legacy_stage_attempt(self):
        attempt = self.payload["observation"]["actual_provider_attempts"][0]
        attempt["premature_7d_attempt_count"] = 1
        self.assertIn("premature 7d provider attempt detected", self.validate())

    def test_rejects_wrong_post_24h_schedule(self):
        attempt = self.payload["observation"]["actual_provider_attempts"][0]
        attempt["post_next_check_at"] = "2026-09-11T22:30:00+08:00"
        self.assertIn("24h next-check schedule mismatch", self.validate())

    def test_rejects_incomplete_promotion_or_write_ledger(self):
        self.payload["managed_promotion"]["health_check"] = "FAIL"
        self.payload["actual_production_write_set"]["rows_by_table"][
            "tracking_provider_attempts"
        ] = 1
        self.payload["actual_production_write_set"]["tables"].remove(
            "crawler_events"
        )
        errors = self.validate()
        self.assertIn("managed promotion health_check missing", errors)
        self.assertIn("terminal Tracking write set incomplete", errors)
        self.assertIn("terminal Tracking row counts invalid", errors)

    def test_rejects_missing_or_unverified_runtime_config_migration(self):
        migration = self.payload["production_preparation_20260907"][
            "runtime_config_migration"
        ]
        for key, invalid in (
            ("production_status", "ABSENT"),
            ("production_policy_count", 0),
            ("schema_migrations_insert_count", 0),
            ("ledger_exact_count", 0),
            ("search_path_binding", False),
            ("rls_contract_exact", False),
            ("policy_contract_count", 0),
            ("policy_qual_readback", "FALSE"),
            ("policy_qual_readback_sha256", "0" * 64),
            ("business_row_mutations", 1),
            ("ledger_readback", "NOT_RUN"),
            ("ledger_readback_sha256", None),
        ):
            original = migration[key]
            migration[key] = invalid
            with self.subTest(key=key):
                self.assertIn(
                    "runtime config migration verification invalid",
                    self.validate(),
                )
            migration[key] = original

    def test_rejects_self_consistent_runtime_config_readback_tamper(self):
        migration = self.payload["production_preparation_20260907"][
            "runtime_config_migration"
        ]
        migration["policy_contract_count"] = 2
        self._refresh_migration_readback_sha256()
        self.assertIn(
            "runtime config migration verification invalid",
            self.validate(),
        )

    def test_rejects_self_consistent_policy_qual_readback_tamper(self):
        migration = self.payload["production_preparation_20260907"][
            "runtime_config_migration"
        ]
        migration["policy_qual_readback"] += " "
        migration["policy_qual_readback_sha256"] = hashlib.sha256(
            migration["policy_qual_readback"].encode("utf-8")
        ).hexdigest()
        self._refresh_migration_readback_sha256()
        self.assertIn(
            "runtime config migration verification invalid",
            self.validate(),
        )

    def test_rejects_runtime_config_migration_source_drift(self):
        migration = self.payload["production_preparation_20260907"][
            "runtime_config_migration"
        ]
        migration["sha256"] = "0" * 64
        self.assertIn(
            "runtime config migration verification invalid",
            self.validate(),
        )

    def test_rejects_missing_schema_migration_write(self):
        writes = self.payload["actual_production_write_set"]
        writes["tables"].remove("schema_migrations")
        del writes["rows_by_table"]["schema_migrations"]
        writes["row_mutations"] = 8
        errors = self.validate()
        self.assertIn("terminal Tracking write set incomplete", errors)
        self.assertIn("terminal Tracking row counts invalid", errors)
        self.assertIn("terminal Tracking mutation count invalid", errors)

    def test_rejects_duplicate_or_hidden_tracking_writes(self):
        writes = self.payload["actual_production_write_set"]
        writes["tables"].append("tracked_notes")
        writes["rows_by_table"]["hidden_table"] = 1
        writes["row_mutations"] = 10
        errors = self.validate()
        self.assertIn("production write set exceeds Tracking contract", errors)
        self.assertIn("terminal Tracking row counts invalid", errors)
        self.assertIn("terminal Tracking mutation count invalid", errors)

    def test_rejects_extra_write_set_field(self):
        self.payload["actual_production_write_set"]["extra_rows"] = 0
        self.assertIn(
            "actual production write set fields invalid",
            self.validate(),
        )

    def test_rejects_self_consistent_write_count_tamper(self):
        writes = self.payload["actual_production_write_set"]
        writes["rows_by_table"]["tracked_notes"] = 2
        writes["row_mutations"] = 10
        self._refresh_write_readback_sha256()
        errors = self.validate()
        self.assertIn("terminal Tracking row counts invalid", errors)
        self.assertIn("terminal Tracking mutation count invalid", errors)

    def test_rejects_duplicate_raw_json_object_key(self):
        raw = json.dumps(self.payload, ensure_ascii=False)
        raw = raw.replace(
            '"tracked_notes": 1',
            '"tracked_notes": 2, "tracked_notes": 1',
            1,
        )
        self.assertEqual(
            self.validate_raw(raw),
            ["canonical tracking evidence is unreadable"],
        )

    def test_rejects_boolean_out_of_contract_write_count(self):
        self.payload["actual_production_write_set"][
            "out_of_contract_row_mutations"
        ] = False
        self.assertIn(
            "out-of-contract production writes detected",
            self.validate(),
        )


if __name__ == "__main__":
    unittest.main()
