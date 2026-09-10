import copy
import hashlib
import json
import sys
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import execute_item34_tracking_checkpoint as executor


TRACK_ID = "8cc8b6de-f826-4c4a-965e-67dbb7e1fcf8"
RUN_ID = "95066174-2d7f-4be3-b8fb-a2e094a3a2bf"
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone(timedelta(hours=8)))
ACTIVE_CONFIG_SHA256 = "1" * 64
INACTIVE_CONFIG_SHA256 = "2" * 64
ATTEMPT_24H_ID = "f0f2c118-f03b-4e73-937d-88455fd0301a"
ATTEMPT_3D_ID = "ae40f92a-ab88-4551-9333-46bbbe1834b5"


def attempt_sha256(attempt_id):
    return hashlib.sha256(
        f"noteai-item34-tracking-attempt-row-v1:{attempt_id}".encode("ascii")
    ).hexdigest()


class Item34TrackingCheckpointExecutorTests(unittest.TestCase):
    def test_tracking_role_reads_only_nonsecret_config_and_session_stop(self):
        migration = (
            ROOT
            / "model"
            / "migrations"
            / "postgres"
            / "0019_xhs_tracking_runtime_config.sql"
        ).read_text(encoding="utf-8")
        normalized = " ".join(migration.split())
        self.assertIn(
            "CREATE POLICY noteai_xhs_tracking_config_read_v1 "
            "ON system_settings FOR SELECT TO PUBLIC",
            normalized,
        )
        self.assertIn(
            "current_user = 'noteai_xhs_tracking' "
            "AND is_secret = 0 AND key IN "
            "('crawler_config', 'xhs_collection_safety')",
            normalized,
        )
        self.assertNotRegex(
            normalized,
            r"(?i)\b(?:INSERT|UPDATE|DELETE)\b.*\b(?:GRANT|POLICY)\b",
        )

    def preflight(self, *, enabled=True, suspended=False, present=True):
        config_sha256 = None
        if present:
            config_sha256 = (
                ACTIVE_CONFIG_SHA256
                if enabled and not suspended
                else INACTIVE_CONFIG_SHA256
            )
        return {
            "schema": executor.SNAPSHOT_SCHEMA,
            "observed_at": NOW.isoformat(),
            "observation_started_at": executor.OBSERVATION_STARTED_AT,
            "production_config": {
                "crawler_enabled": enabled,
                "collection_suspended": suspended,
                "crawler_config_present": present,
                "crawler_config_sha256": config_sha256,
                "runtime_role": "xhs-http",
                "adapter": "spider_xhs_http",
            },
            "runtime_state": {
                "unit_active_state": "inactive",
                "unit_sub_state": "dead",
                "unit_file_state": "disabled",
                "task_container_count": 0,
            },
            "global_due": {
                "count": 1,
                "rows": [
                    {
                        "track_id": TRACK_ID,
                        "note_id": executor.CANONICAL_NOTE_ID,
                        "stage": "24h",
                    }
                ],
            },
            "target": {
                "track_id": TRACK_ID,
                "note_id": executor.CANONICAL_NOTE_ID,
                "canonical_url": executor.CANONICAL_URL,
                "object_identity_sha256": executor.OBJECT_IDENTITY_SHA256,
                "status": "pending",
                "next_check_at": executor.CHECKPOINT_24H_DUE_AT,
                "check_24h_at": None,
                "check_7d_at": None,
                "claim_present": False,
                "active_attempt_present": False,
                "training_eligible": False,
                "score_window": None,
                "metrics": {"likes": None, "saves": None, "comments": None},
            },
            "attempts": {
                "target_count_24h": 0,
                "target_count_7d": 0,
                "global_started_count": 0,
                "target_unknown_count": 0,
                "global_unknown_count": 0,
                "rows": [],
            },
            "non_target_tracked_notes_sha256": "a" * 64,
        }

    def postflight(self, *, system_settings_row_mutations=0):
        observed = NOW + timedelta(minutes=1)
        return {
            "schema": executor.SNAPSHOT_SCHEMA,
            "observed_at": observed.isoformat(),
            "observation_started_at": executor.OBSERVATION_STARTED_AT,
            "production_config": {
                "crawler_enabled": True,
                "collection_suspended": False,
                "crawler_config_present": True,
                "crawler_config_sha256": ACTIVE_CONFIG_SHA256,
                "runtime_role": "xhs-http",
                "adapter": "spider_xhs_http",
            },
            "runtime_state": {
                "unit_active_state": "inactive",
                "unit_sub_state": "dead",
                "unit_file_state": "disabled",
                "task_container_count": 0,
            },
            "global_due": {"count": 0, "rows": []},
            "target": {
                "track_id": TRACK_ID,
                "note_id": executor.CANONICAL_NOTE_ID,
                "canonical_url": executor.CANONICAL_URL,
                "object_identity_sha256": executor.OBJECT_IDENTITY_SHA256,
                "status": "checking_7d",
                "next_check_at": executor.CHECKPOINT_3D_DUE_AT,
                "check_24h_at": observed.isoformat(),
                "check_7d_at": None,
                "claim_present": False,
                "active_attempt_present": False,
                "training_eligible": False,
                "score_window": None,
                "metrics": {"likes": 5, "saves": 2, "comments": 2},
            },
            "attempts": {
                "target_count_24h": 1,
                "target_count_7d": 0,
                "global_started_count": 0,
                "target_unknown_count": 0,
                "global_unknown_count": 0,
                "rows": [
                    {
                        "track_id": TRACK_ID,
                        "note_id": executor.CANONICAL_NOTE_ID,
                        "stage": "24h",
                        "status": "succeeded",
                        "run_id": RUN_ID,
                        "attempt_id": ATTEMPT_24H_ID,
                        "admitted_at": NOW.isoformat(),
                        "completed_at": observed.isoformat(),
                    }
                ],
            },
            "non_target_tracked_notes_sha256": "a" * 64,
            "run": {
                "run_id": RUN_ID,
                "worker_argv": list(executor.WORKER_ARGV),
                "worker_invocation_count": 1,
                "automatic_retry_count": 0,
                "attempted": 1,
                "collected": 1,
                "failed": 0,
            },
            "write_audit": {
                "target_tracked_notes_distinct_rows": 1,
                "other_tracked_notes_row_mutations": 0,
                "tracking_provider_attempts_inserted": 1,
                "crawler_events_inserted": 1,
                "system_settings_row_mutations": system_settings_row_mutations,
                "other_system_settings_row_mutations": 0,
                "out_of_contract_row_mutations": 0,
            },
        }

    @staticmethod
    def transition_authorization(initial, transition_id="b" * 64):
        config = initial["production_config"]
        return {
            "schema": executor.TRANSITION_SCHEMA,
            "transition_id": transition_id,
            "action": "item34_single_24h_checkpoint",
            "restore_required": True,
            "worker_argv": list(executor.WORKER_ARGV),
            "expected_original_config_present": config[
                "crawler_config_present"
            ],
            "expected_original_config_sha256": config[
                "crawler_config_sha256"
            ],
            "expected_active_config_sha256": ACTIVE_CONFIG_SHA256,
        }

    @staticmethod
    def transition_receipt(
        phase,
        initial,
        *,
        transition_id="b" * 64,
        configuration_mutations=1,
    ):
        original = initial["production_config"]
        if phase == "activate":
            before_present = original["crawler_config_present"]
            before_sha256 = original["crawler_config_sha256"]
            after_present = True
            after_sha256 = ACTIVE_CONFIG_SHA256
            enabled, suspended = True, False
        else:
            before_present = True
            before_sha256 = ACTIVE_CONFIG_SHA256
            after_present = original["crawler_config_present"]
            after_sha256 = original["crawler_config_sha256"]
            enabled = original["crawler_enabled"]
            suspended = original["collection_suspended"]
        return {
            "transition_id": transition_id,
            "phase": phase,
            "crawler_enabled": enabled,
            "collection_suspended": suspended,
            "before_config_present": before_present,
            "before_config_sha256": before_sha256,
            "after_config_present": after_present,
            "after_config_sha256": after_sha256,
            "configuration_mutations": configuration_mutations,
            "other_configuration_mutations": 0,
        }

    @staticmethod
    def worker_receipt():
        return {
            "exit_code": 0,
            "invocation_count": 1,
            "automatic_retry_count": 0,
            "result": {
                "claimed": 1,
                "attempted": 1,
                "collected": 1,
                "failed": 0,
                "released": 0,
                "total": 1,
            },
        }

    @staticmethod
    def schedule_receipt():
        return {
            "track_id": TRACK_ID,
            "next_check_at": executor.CHECKPOINT_3D_DUE_AT,
            "target_rows_mutated": 1,
            "other_tracked_notes_row_mutations": 0,
        }

    def run_happy(self, **overrides):
        pre = overrides.pop("pre", self.preflight())
        post = overrides.pop("post", self.postflight())
        worker = overrides.pop("worker", self.worker_receipt())
        schedule = overrides.pop("schedule", self.schedule_receipt())
        calls = []

        def run_worker(argv):
            calls.append(tuple(argv))
            return worker

        result = executor.execute_24h_checkpoint(
            expected_track_id=TRACK_ID,
            read_preflight=lambda: pre,
            run_worker=run_worker,
            schedule_3d=lambda track_id, due: schedule,
            read_postflight=lambda: post,
            clock=lambda: NOW,
            **overrides,
        )
        return result, calls

    def assert_code(self, expected, callback):
        with self.assertRaises(executor.Item34CheckpointError) as raised:
            callback()
        self.assertEqual(raised.exception.code, expected)

    def test_happy_path_invokes_exact_one_bounded_worker_and_schedules_72h(self):
        schedule_calls = []
        worker_calls = []

        result = executor.execute_24h_checkpoint(
            expected_track_id=TRACK_ID,
            read_preflight=self.preflight,
            run_worker=lambda argv: (
                worker_calls.append(tuple(argv)) or self.worker_receipt()
            ),
            schedule_3d=lambda track_id, due: (
                schedule_calls.append((track_id, due)) or self.schedule_receipt()
            ),
            read_postflight=self.postflight,
            clock=lambda: NOW,
        )

        self.assertEqual(worker_calls, [executor.WORKER_ARGV])
        self.assertEqual(
            schedule_calls,
            [(TRACK_ID, executor.CHECKPOINT_3D_DUE_AT)],
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["worker_invocation_count"], 1)
        self.assertEqual(result["automatic_retry_count"], 0)
        self.assertEqual(result["attempt_count_24h"], 1)
        self.assertEqual(result["attempt_count_7d"], 0)
        self.assertEqual(
            result["attempt_identity_sha256"], attempt_sha256(ATTEMPT_24H_ID)
        )
        self.assertEqual(result["canonical_stage"], "24h")
        self.assertEqual(result["persisted_stage"], "24h")
        self.assertFalse(result["readiness_credit"])
        self.assertFalse(result["secret_values_recorded"])

    def test_worker_argv_is_exact_and_has_no_unmanaged_bypass(self):
        self.assertEqual(
            executor.WORKER_ARGV,
            ("python", "crawler_worker.py", "--once", "--limit", "1"),
        )
        self.assertEqual(len(executor.WORKER_ARGV), 5)

    def test_rejects_disabled_or_suspended_config_without_transition(self):
        for pre in (
            self.preflight(enabled=False),
            self.preflight(suspended=True),
        ):
            calls = []
            with self.subTest(config=pre["production_config"]):
                self.assert_code(
                    "managed_transition_required",
                    lambda: executor.execute_24h_checkpoint(
                        expected_track_id=TRACK_ID,
                        read_preflight=lambda: pre,
                        run_worker=lambda argv: calls.append(argv),
                        schedule_3d=lambda *_: calls.append("schedule"),
                        read_postflight=self.postflight,
                        clock=lambda: NOW,
                    ),
                )
                self.assertEqual(calls, [])

    def test_explicit_managed_transition_is_scoped_and_restored(self):
        initial = self.preflight(enabled=False, present=False)
        active = self.preflight()
        preflights = iter((initial, active))
        transition_id = "b" * 64
        authorization = self.transition_authorization(initial, transition_id)
        phases = []

        def transition(phase, supplied):
            phases.append((phase, supplied["transition_id"]))
            return self.transition_receipt(
                phase,
                initial,
                transition_id=transition_id,
            )

        result = executor.execute_24h_checkpoint(
            expected_track_id=TRACK_ID,
            read_preflight=lambda: next(preflights),
            run_worker=lambda argv: self.worker_receipt(),
            schedule_3d=lambda *_: self.schedule_receipt(),
            read_postflight=lambda: self.postflight(
                system_settings_row_mutations=1
            ),
            clock=lambda: NOW,
            transition_authorization=authorization,
            transition_config=transition,
            read_transition_state=lambda: initial["production_config"],
        )

        self.assertEqual(phases, [("activate", transition_id), ("restore", transition_id)])
        self.assertEqual(
            result["managed_transition"],
            {
                "used": True,
                "restored": True,
                "configuration_row_mutations": 2,
            },
        )

    def test_transition_cannot_change_due_target_or_attempt_state(self):
        initial = self.preflight(enabled=False, present=False)
        active = self.preflight()
        active["target"]["track_id"] = (
            "55f76e15-89ea-4e52-932f-431e58315fb2"
        )
        preflights = iter((initial, active))
        authorization = self.transition_authorization(initial)

        def transition(phase, _authorization):
            return self.transition_receipt(phase, initial)

        self.assert_code(
            "target_binding",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=lambda: next(preflights),
                run_worker=lambda argv: self.worker_receipt(),
                schedule_3d=lambda *_: self.schedule_receipt(),
                read_postflight=lambda: self.postflight(
                    system_settings_row_mutations=1
                ),
                clock=lambda: NOW,
                transition_authorization=authorization,
                transition_config=transition,
                read_transition_state=lambda: initial["production_config"],
            ),
        )

    def test_invalid_activation_receipt_still_restores_original_gates(self):
        initial = self.preflight(enabled=False, present=False)
        transition_id = "b" * 64
        authorization = self.transition_authorization(initial, transition_id)
        phases = []

        def transition(phase, _authorization):
            phases.append(phase)
            return self.transition_receipt(
                phase,
                initial,
                transition_id=transition_id,
                configuration_mutations=0 if phase == "activate" else 1,
            )

        self.assert_code(
            "managed_transition",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=lambda: initial,
                run_worker=lambda argv: self.worker_receipt(),
                schedule_3d=lambda *_: self.schedule_receipt(),
                read_postflight=lambda: self.postflight(
                    system_settings_row_mutations=1
                ),
                clock=lambda: NOW,
                transition_authorization=authorization,
                transition_config=transition,
                read_transition_state=lambda: initial["production_config"],
            ),
        )
        self.assertEqual(phases, ["activate", "restore"])

    def test_restore_receipt_requires_independent_original_state_readback(self):
        initial = self.preflight(enabled=False, present=False)
        active = self.preflight()
        preflights = iter((initial, active))
        transition_id = "b" * 64
        authorization = self.transition_authorization(initial, transition_id)

        def lying_transition(phase, _authorization):
            return self.transition_receipt(
                phase,
                initial,
                transition_id=transition_id,
            )

        self.assert_code(
            "managed_transition_restore",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=lambda: next(preflights),
                run_worker=lambda argv: self.worker_receipt(),
                schedule_3d=lambda *_: self.schedule_receipt(),
                read_postflight=lambda: self.postflight(
                    system_settings_row_mutations=1
                ),
                clock=lambda: NOW,
                transition_authorization=authorization,
                transition_config=lying_transition,
                read_transition_state=lambda: active["production_config"],
            ),
        )

    def test_restore_failure_preserves_the_primary_stage_error_code(self):
        initial = self.preflight(enabled=False, present=False)
        active = self.preflight()
        preflights = iter((initial, active))
        authorization = self.transition_authorization(initial)
        bad_worker = self.worker_receipt()
        bad_worker["result"]["failed"] = 1
        bad_worker["result"]["collected"] = 0

        def transition(phase, _authorization):
            return self.transition_receipt(phase, initial)

        self.assert_code(
            "worker_result_restore_failed",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=lambda: next(preflights),
                run_worker=lambda argv: bad_worker,
                schedule_3d=lambda *_: self.schedule_receipt(),
                read_postflight=lambda: self.postflight(
                    system_settings_row_mutations=1
                ),
                clock=lambda: NOW,
                transition_authorization=authorization,
                transition_config=transition,
                read_transition_state=lambda: active["production_config"],
            ),
        )

    def test_rejects_non_singleton_or_cross_object_due_work_before_worker(self):
        cases = []
        two = self.preflight()
        two["global_due"]["count"] = 2
        two["global_due"]["rows"].append(copy.deepcopy(two["global_due"]["rows"][0]))
        cases.append((two, "global_due"))
        wrong_note = self.preflight()
        wrong_note["global_due"]["rows"][0]["note_id"] = "0" * 24
        cases.append((wrong_note, "global_due_binding"))
        wrong_track = self.preflight()
        wrong_track["global_due"]["rows"][0]["track_id"] = RUN_ID
        cases.append((wrong_track, "global_due_binding"))

        for pre, code in cases:
            with self.subTest(code=code):
                self.assert_code(
                    code,
                    lambda pre=pre: self.run_happy(pre=pre),
                )

    def test_rejects_prior_24h_or_7d_attempt_before_worker(self):
        for key in (
            "target_count_24h",
            "target_count_7d",
            "global_started_count",
            "target_unknown_count",
            "global_unknown_count",
        ):
            pre = self.preflight()
            pre["attempts"][key] = 1
            with self.subTest(key=key):
                self.assert_code(
                    "prior_provider_attempt",
                    lambda pre=pre: self.run_happy(pre=pre),
                )

    def test_requires_quiescent_unit_and_zero_task_containers(self):
        cases = []
        active = self.preflight()
        active["runtime_state"]["unit_active_state"] = "active"
        cases.append(active)
        container = self.preflight()
        container["runtime_state"]["task_container_count"] = 1
        cases.append(container)
        for pre in cases:
            with self.subTest(state=pre["runtime_state"]):
                self.assert_code(
                    "runtime_not_quiescent",
                    lambda pre=pre: self.run_happy(pre=pre),
                )

    def test_rejects_outcome_unknown_before_or_after_dispatch(self):
        pre = self.preflight()
        pre["attempts"]["global_unknown_count"] = 1
        self.assert_code(
            "prior_provider_attempt",
            lambda: self.run_happy(pre=pre),
        )

        post = self.postflight()
        post["attempts"]["target_unknown_count"] = 1
        self.assert_code(
            "post_provider_attempt",
            lambda: self.run_happy(post=post),
        )

    def test_transition_authorization_binds_entire_original_config_digest(self):
        initial = self.preflight(enabled=False, present=False)
        authorization = self.transition_authorization(initial)
        authorization["expected_original_config_sha256"] = "9" * 64
        self.assert_code(
            "managed_transition_authorization",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=lambda: initial,
                run_worker=lambda argv: self.worker_receipt(),
                schedule_3d=lambda *_: self.schedule_receipt(),
                read_postflight=lambda: self.postflight(
                    system_settings_row_mutations=1
                ),
                clock=lambda: NOW,
                transition_authorization=authorization,
                transition_config=lambda phase, _: self.transition_receipt(
                    phase, initial
                ),
                read_transition_state=lambda: initial["production_config"],
            ),
        )

    def test_transition_requires_exactly_one_config_row_mutation_per_phase(self):
        initial = self.preflight(enabled=False, present=False)
        phases = []

        def transition(phase, _authorization):
            phases.append(phase)
            return self.transition_receipt(
                phase,
                initial,
                configuration_mutations=2 if phase == "activate" else 1,
            )

        self.assert_code(
            "managed_transition",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=lambda: initial,
                run_worker=lambda argv: self.worker_receipt(),
                schedule_3d=lambda *_: self.schedule_receipt(),
                read_postflight=lambda: self.postflight(
                    system_settings_row_mutations=1
                ),
                clock=lambda: NOW,
                transition_authorization=self.transition_authorization(initial),
                transition_config=transition,
                read_transition_state=lambda: initial["production_config"],
            ),
        )
        self.assertEqual(phases, ["activate", "restore"])

    def test_postflight_audits_crawler_event_and_config_write_counts(self):
        missing_event = self.postflight()
        missing_event["write_audit"]["crawler_events_inserted"] = 0
        self.assert_code(
            "write_audit",
            lambda: self.run_happy(post=missing_event),
        )

        unexpected_config = self.postflight()
        unexpected_config["write_audit"]["system_settings_row_mutations"] = 1
        self.assert_code(
            "write_audit",
            lambda: self.run_happy(post=unexpected_config),
        )

    def test_preflight_allows_small_positive_readback_clock_skew(self):
        pre = self.preflight()
        pre["observed_at"] = (NOW + timedelta(microseconds=1)).isoformat()
        post = self.postflight()
        post["attempts"]["rows"][0]["admitted_at"] = (
            NOW + timedelta(seconds=1)
        ).isoformat()
        result, _calls = self.run_happy(pre=pre, post=post)
        self.assertEqual(result["status"], "VERIFIED")

    def test_preflight_schedule_is_bound_to_anchor_plus_24h(self):
        pre = self.preflight()
        pre["target"]["next_check_at"] = (
            datetime.fromisoformat(executor.CHECKPOINT_24H_DUE_AT)
            - timedelta(seconds=1)
        ).isoformat()
        self.assert_code(
            "target_pre_schedule",
            lambda: self.run_happy(pre=pre),
        )

    def test_worker_failure_is_not_retried_or_scheduled(self):
        worker = self.worker_receipt()
        worker["result"]["failed"] = 1
        worker["result"]["collected"] = 0
        calls = []
        self.assert_code(
            "worker_result",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=self.preflight,
                run_worker=lambda argv: calls.append("worker") or worker,
                schedule_3d=lambda *_: calls.append("schedule"),
                read_postflight=lambda: calls.append("post"),
                clock=lambda: NOW,
            ),
        )
        self.assertEqual(calls, ["worker"])

    def test_boolean_counters_are_not_accepted_as_integer_evidence(self):
        worker = self.worker_receipt()
        worker["invocation_count"] = True
        self.assert_code(
            "worker_result",
            lambda: self.run_happy(worker=worker),
        )

    def test_unknown_worker_outcome_uses_stable_error_and_no_retry(self):
        calls = []
        sensitive_detail = "synthetic-cookie-value-must-not-escape"

        def fail(_argv):
            calls.append("worker")
            raise RuntimeError(sensitive_detail)

        try:
            executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=self.preflight,
                run_worker=fail,
                schedule_3d=lambda *_: calls.append("schedule"),
                read_postflight=lambda: calls.append("post"),
                clock=lambda: NOW,
            )
        except executor.Item34CheckpointError as raised:
            rendered = "".join(traceback.format_exception(raised))
            self.assertEqual(raised.code, "worker_outcome_unknown")
            self.assertIsNone(raised.__cause__)
            self.assertNotIn(sensitive_detail, rendered)
        else:
            self.fail("worker failure must be fail-closed")
        self.assertEqual(calls, ["worker"])

    def test_every_post_activation_failure_restores_and_reads_original_gates(self):
        bad_worker = self.worker_receipt()
        bad_worker["result"]["failed"] = 1
        bad_schedule = self.schedule_receipt()
        bad_schedule["other_tracked_notes_row_mutations"] = 1
        bad_post = self.postflight(system_settings_row_mutations=1)
        bad_post["run"]["failed"] = 1
        cases = (
            (
                "worker_result",
                bad_worker,
                self.schedule_receipt(),
                self.postflight(system_settings_row_mutations=1),
            ),
            (
                "schedule_write",
                self.worker_receipt(),
                bad_schedule,
                self.postflight(system_settings_row_mutations=1),
            ),
            ("post_run", self.worker_receipt(), self.schedule_receipt(), bad_post),
        )

        for code, worker, schedule, post in cases:
            with self.subTest(code=code):
                initial = self.preflight(enabled=False, present=False)
                active = self.preflight()
                preflights = iter((initial, active))
                state = dict(active["production_config"])
                phases = []
                readbacks = []
                authorization = self.transition_authorization(initial)

                def transition(phase, _authorization):
                    phases.append(phase)
                    receipt = self.transition_receipt(phase, initial)
                    if phase == "activate":
                        state.update(active["production_config"])
                    else:
                        state.update(initial["production_config"])
                    return receipt

                def read_state():
                    readbacks.append(dict(state))
                    return dict(state)

                self.assert_code(
                    code,
                    lambda: executor.execute_24h_checkpoint(
                        expected_track_id=TRACK_ID,
                        read_preflight=lambda: next(preflights),
                        run_worker=lambda argv: worker,
                        schedule_3d=lambda *_: schedule,
                        read_postflight=lambda: post,
                        clock=lambda: NOW,
                        transition_authorization=authorization,
                        transition_config=transition,
                        read_transition_state=read_state,
                    ),
                )
                self.assertEqual(phases, ["activate", "restore"])
                self.assertEqual(
                    readbacks,
                    [initial["production_config"]],
                )

    def test_schedule_must_update_only_the_bound_target(self):
        schedule = self.schedule_receipt()
        schedule["other_tracked_notes_row_mutations"] = 1
        self.assert_code(
            "schedule_write",
            lambda: self.run_happy(schedule=schedule),
        )

    def test_postflight_requires_exact_run_and_zero_7d_attempt(self):
        cases = []
        retried = self.postflight()
        retried["run"]["automatic_retry_count"] = 1
        cases.append((retried, "post_run"))
        seven_day = self.postflight()
        seven_day["attempts"]["target_count_7d"] = 1
        cases.append((seven_day, "post_provider_attempt"))
        failed = self.postflight()
        failed["run"]["failed"] = 1
        cases.append((failed, "post_run"))

        for post, code in cases:
            with self.subTest(code=code):
                self.assert_code(code, lambda post=post: self.run_happy(post=post))

    def test_postflight_requires_exact_72h_schedule_and_other_rows_unchanged(self):
        wrong_due = self.postflight()
        wrong_due["target"]["next_check_at"] = (
            datetime.fromisoformat(executor.CHECKPOINT_3D_DUE_AT)
            + timedelta(seconds=1)
        ).isoformat()
        self.assert_code(
            "target_post_state",
            lambda: self.run_happy(post=wrong_due),
        )

        changed = self.postflight()
        changed["non_target_tracked_notes_sha256"] = "c" * 64
        self.assert_code(
            "other_tracking_rows_changed",
            lambda: self.run_happy(post=changed),
        )

        audited = self.postflight()
        audited["write_audit"]["other_tracked_notes_row_mutations"] = 1
        self.assert_code("write_audit", lambda: self.run_happy(post=audited))

    def test_24h_persist_clock_must_equal_attempt_completion_clock(self):
        post = self.postflight()
        post["target"]["check_24h_at"] = (
            datetime.fromisoformat(post["attempts"]["rows"][0]["admitted_at"])
            + timedelta(seconds=1)
        ).isoformat()
        self.assert_code(
            "post_snapshot_clock",
            lambda: self.run_happy(post=post),
        )

    def test_rejects_early_or_closed_24h_execution_window(self):
        early = datetime.fromisoformat(executor.CHECKPOINT_24H_DUE_AT) - timedelta(seconds=1)
        closed = datetime.fromisoformat(executor.CHECKPOINT_3D_DUE_AT)
        for when, code in (
            (early, "checkpoint_24h_not_due"),
            (closed, "checkpoint_24h_window_closed"),
        ):
            with self.subTest(code=code):
                self.assert_code(
                    code,
                    lambda when=when: executor.execute_24h_checkpoint(
                        expected_track_id=TRACK_ID,
                        read_preflight=self.preflight,
                        run_worker=lambda argv: self.worker_receipt(),
                        schedule_3d=lambda *_: self.schedule_receipt(),
                        read_postflight=self.postflight,
                        clock=lambda: when,
                    ),
                )

    def test_rechecks_72h_boundary_immediately_before_dispatch(self):
        clocks = iter(
            (
                NOW,
                datetime.fromisoformat(executor.CHECKPOINT_3D_DUE_AT),
            )
        )
        worker_calls = []
        self.assert_code(
            "checkpoint_24h_window_closed",
            lambda: executor.execute_24h_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=self.preflight,
                run_worker=lambda argv: worker_calls.append(tuple(argv)),
                schedule_3d=lambda *_: self.schedule_receipt(),
                read_postflight=self.postflight,
                clock=lambda: next(clocks),
            ),
        )
        self.assertEqual(worker_calls, [])

    def test_module_has_no_direct_production_or_secret_access(self):
        source = Path(executor.__file__).read_text(encoding="utf-8")
        for prohibited in (
            "os.environ",
            "psycopg",
            "sqlite3",
            "requests.",
            "urllib.request",
            "subprocess",
            "/etc/noteai",
            "NOTEAI_XHS_COOKIES_JSON",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, source)


class Item34Tracking3dCheckpointExecutorTests(unittest.TestCase):
    now = datetime.fromisoformat(executor.CHECKPOINT_3D_DUE_AT) + timedelta(
        minutes=5
    )
    completed_24h = NOW + timedelta(minutes=1)

    def snapshot(self, *, phase="pre", enabled=True, suspended=False, present=True):
        post = phase == "post"
        observed = self.now + (timedelta(minutes=1) if post else timedelta())
        config_sha256 = None
        if present:
            config_sha256 = (
                ACTIVE_CONFIG_SHA256
                if enabled and not suspended
                else INACTIVE_CONFIG_SHA256
            )
        attempts = [
            {
                "track_id": TRACK_ID,
                "note_id": executor.CANONICAL_NOTE_ID,
                "stage": "24h",
                "status": "succeeded",
                "run_id": RUN_ID,
                "attempt_id": ATTEMPT_24H_ID,
                "admitted_at": NOW.isoformat(),
                "completed_at": self.completed_24h.isoformat(),
            }
        ]
        run_3d = "41d130b3-36b8-43d9-8168-a5ed7c45fa9d"
        if post:
            attempts.append(
                {
                    "track_id": TRACK_ID,
                    "note_id": executor.CANONICAL_NOTE_ID,
                    "stage": "7d",
                    "status": "succeeded",
                    "run_id": run_3d,
                    "attempt_id": ATTEMPT_3D_ID,
                    "admitted_at": self.now.isoformat(),
                    "completed_at": observed.isoformat(),
                }
            )
        result = {
            "schema": executor.SNAPSHOT_SCHEMA,
            "observed_at": observed.isoformat(),
            "observation_started_at": executor.OBSERVATION_STARTED_AT,
            "production_config": {
                "crawler_enabled": enabled,
                "collection_suspended": suspended,
                "crawler_config_present": present,
                "crawler_config_sha256": config_sha256,
                "runtime_role": "xhs-http",
                "adapter": "spider_xhs_http",
            },
            "runtime_state": {
                "unit_active_state": "inactive",
                "unit_sub_state": "dead",
                "unit_file_state": "disabled",
                "task_container_count": 0,
            },
            "global_due": (
                {"count": 0, "rows": []}
                if post
                else {
                    "count": 1,
                    "rows": [
                        {
                            "track_id": TRACK_ID,
                            "note_id": executor.CANONICAL_NOTE_ID,
                            "stage": "7d",
                        }
                    ],
                }
            ),
            "target": {
                "track_id": TRACK_ID,
                "note_id": executor.CANONICAL_NOTE_ID,
                "canonical_url": executor.CANONICAL_URL,
                "object_identity_sha256": executor.OBJECT_IDENTITY_SHA256,
                "status": "complete" if post else "checking_7d",
                "next_check_at": executor.CHECKPOINT_3D_DUE_AT,
                "check_24h_at": self.completed_24h.isoformat(),
                "check_7d_at": observed.isoformat() if post else None,
                "claim_present": False,
                "active_attempt_present": False,
                "training_eligible": False,
                "score_window": "3d" if post else None,
                "metrics": (
                    {"likes": 8, "saves": 3, "comments": 3}
                    if post
                    else {"likes": 5, "saves": 2, "comments": 2}
                ),
            },
            "attempts": {
                "target_count_24h": 1,
                "target_count_7d": 1 if post else 0,
                "global_started_count": 0,
                "target_unknown_count": 0,
                "global_unknown_count": 0,
                "rows": attempts,
            },
            "non_target_tracked_notes_sha256": "a" * 64,
        }
        if post:
            result.update(
                {
                    "run": {
                        "run_id": run_3d,
                        "worker_argv": list(executor.WORKER_ARGV),
                        "worker_invocation_count": 1,
                        "automatic_retry_count": 0,
                        "attempted": 1,
                        "collected": 1,
                        "failed": 0,
                    },
                    "write_audit": {
                        "target_tracked_notes_distinct_rows": 1,
                        "other_tracked_notes_row_mutations": 0,
                        "tracking_provider_attempts_inserted": 1,
                        "crawler_events_inserted": 1,
                        "growth_records_inserted": 1,
                        "user_memories_inserted": 1,
                        "system_settings_row_mutations": 0,
                        "other_system_settings_row_mutations": 0,
                        "out_of_contract_row_mutations": 0,
                    },
                    "terminal_effects": {
                        "growth_record_count": 1,
                        "user_memory_count": 1,
                        "training_eligible": False,
                        "score_window": "3d",
                        "growth_action": "url_crawl_3d",
                        "memory_window": "3d",
                        "memory_content_sha256": "d" * 64,
                        "ledger_sha256": "e" * 64,
                    },
                }
            )
        return result

    def run_happy(self, **overrides):
        return executor.execute_3d_checkpoint(
            expected_track_id=TRACK_ID,
            read_preflight=lambda: overrides.get("pre", self.snapshot()),
            run_worker=lambda argv: overrides.get(
                "worker",
                Item34TrackingCheckpointExecutorTests.worker_receipt(),
            ),
            read_postflight=lambda: overrides.get(
                "post", self.snapshot(phase="post")
            ),
            clock=lambda: overrides.get("now", self.now),
        )

    def assert_code(self, code, callback):
        with self.assertRaises(executor.Item34CheckpointError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_exact_3d_attempt_and_terminal_effects_are_verified(self):
        result = self.run_happy()
        self.assertEqual(result["checkpoint"], "3d")
        self.assertEqual(result["provider_calls"], 1)
        self.assertEqual(result["attempt_count_7d"], 1)
        self.assertEqual(
            result["attempt_identity_sha256"], attempt_sha256(ATTEMPT_3D_ID)
        )
        self.assertEqual(result["canonical_stage"], "3d")
        self.assertEqual(result["persisted_stage"], "7d")
        self.assertEqual(result["admitted_at"], self.now.isoformat())
        self.assertEqual(
            result["completed_at"],
            (self.now + timedelta(minutes=1)).isoformat(),
        )
        self.assertEqual(result["other_tracked_notes_row_mutations"], 0)
        self.assertEqual(result["metrics"], {"likes": 8, "saves": 3, "comments": 3})
        self.assertFalse(result["training_eligible"])
        self.assertEqual(result["score_window"], "3d")
        self.assertEqual(result["growth_action"], "url_crawl_3d")
        self.assertEqual(result["memory_window"], "3d")
        self.assertEqual(result["memory_content_sha256"], "d" * 64)
        self.assertFalse(result["readiness_credit"])

    def test_attempt_identity_must_be_a_canonical_database_row_id(self):
        for phase in ("pre", "post"):
            snapshot = self.snapshot(phase=phase)
            snapshot["attempts"]["rows"][-1]["attempt_id"] = "not-a-uuid"
            with self.subTest(phase=phase):
                self.assert_code(
                    "provider_attempt_identity",
                    lambda snapshot=snapshot: self.run_happy(
                        **({"post": snapshot} if phase == "post" else {"pre": snapshot})
                    ),
                )

    def test_3d_attempt_cannot_run_before_real_72h_boundary(self):
        calls = []
        self.assert_code(
            "checkpoint_3d_not_due",
            lambda: executor.execute_3d_checkpoint(
                expected_track_id=TRACK_ID,
                read_preflight=lambda: calls.append("pre"),
                run_worker=lambda argv: calls.append("worker"),
                read_postflight=lambda: calls.append("post"),
                clock=lambda: datetime.fromisoformat(executor.CHECKPOINT_3D_DUE_AT)
                - timedelta(microseconds=1),
            ),
        )
        self.assertEqual(calls, [])

    def test_3d_rejects_missing_24h_ledger_or_terminal_effect(self):
        missing_prior = self.snapshot()
        missing_prior["attempts"]["target_count_24h"] = 0
        self.assert_code(
            "provider_attempt_ledger",
            lambda: self.run_happy(pre=missing_prior),
        )
        missing_effect = self.snapshot(phase="post")
        missing_effect["terminal_effects"]["growth_record_count"] = 0
        self.assert_code(
            "terminal_effects",
            lambda: self.run_happy(post=missing_effect),
        )
        for key, invalid in (
            ("training_eligible", True),
            ("score_window", "7d"),
            ("growth_action", "url_crawl_7d"),
            ("memory_window", "7d"),
            ("memory_content_sha256", "bad"),
        ):
            post = self.snapshot(phase="post")
            post["terminal_effects"][key] = invalid
            with self.subTest(key=key):
                self.assert_code(
                    "terminal_effects",
                    lambda post=post: self.run_happy(post=post),
                )

    def test_3d_transition_requires_stage_bound_authorization_and_restores(self):
        initial = self.snapshot(enabled=False, present=False)
        active = self.snapshot()
        preflights = iter((initial, active))
        transition_id = "b" * 64
        authorization = Item34TrackingCheckpointExecutorTests.transition_authorization(
            initial, transition_id
        )
        authorization["action"] = "item34_single_3d_checkpoint"
        phases = []

        def transition(phase, supplied):
            phases.append(phase)
            return Item34TrackingCheckpointExecutorTests.transition_receipt(
                phase,
                initial,
                transition_id=transition_id,
            )

        post = self.snapshot(phase="post")
        post["write_audit"]["system_settings_row_mutations"] = 1
        result = executor.execute_3d_checkpoint(
            expected_track_id=TRACK_ID,
            read_preflight=lambda: next(preflights),
            run_worker=lambda argv: Item34TrackingCheckpointExecutorTests.worker_receipt(),
            read_postflight=lambda: post,
            clock=lambda: self.now,
            transition_authorization=authorization,
            transition_config=transition,
            read_transition_state=lambda: initial["production_config"],
        )
        self.assertEqual(phases, ["activate", "restore"])
        self.assertEqual(result["managed_transition"]["configuration_row_mutations"], 2)


def prospective_binding(generation=1):
    value={'track_id':TRACK_ID,'owner_id':'00000000-0000-4000-8000-000000000001',
            'generation':generation,'observation_started_at':'2026-09-10T12:00:00+00:00',
            'initial_snapshot':{'likes':4,'saves':2,'comments':2},
            'previous_attempt_id':'00000000-0000-4000-8000-000000000002',
            'previous_attempt_sha256':'c'*64}
    if generation==2:
        value['sealed_attempts']=[{'generation':0,'attempt_id':'00000000-0000-4000-8000-000000000003','sha256':'d'*64},
            {'generation':1,'attempt_id':value['previous_attempt_id'],'sha256':value['previous_attempt_sha256']}]
    return value


class ProspectiveObservationCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.binding=prospective_binding()
        self.delta=datetime.fromisoformat(self.binding['observation_started_at'])-datetime.fromisoformat(executor.OBSERVATION_STARTED_AT)

    def shifted(self,value):
        if isinstance(value,dict):return {k:self.shifted(v) for k,v in value.items()}
        if isinstance(value,list):return [self.shifted(v) for v in value]
        if isinstance(value,str) and value.startswith('2026-') and 'T' in value:
            return (datetime.fromisoformat(value)+self.delta).astimezone(timezone.utc).isoformat()
        return value

    def snapshot(self,value):
        return {**self.shifted(value),**executor.observation_identity()}

    def test_two_stages_use_explicit_new_t0_and_leave_legacy_constants_unchanged(self):
        original=(executor.OBSERVATION_STARTED_AT,executor.CHECKPOINT_24H_DUE_AT,executor.CHECKPOINT_3D_DUE_AT)
        fixture=Item34TrackingCheckpointExecutorTests()
        terminal=Item34Tracking3dCheckpointExecutorTests()
        calls=[]
        with executor.observation_context(self.binding):
            result=executor.execute_24h_checkpoint(expected_track_id=TRACK_ID,
                read_preflight=lambda:self.snapshot(fixture.preflight()),
                run_worker=lambda argv:calls.append(argv) or fixture.worker_receipt(),
                schedule_3d=lambda *_:{**self.shifted(fixture.schedule_receipt()),'target_rows_mutated':0},
                read_postflight=lambda:self.snapshot(fixture.postflight()),clock=lambda:NOW+self.delta)
            self.assertEqual(result['observation_started_at'],self.binding['observation_started_at'])
            self.assertEqual(result['observation_binding_sha256'],executor.observation_identity()['observation_binding_sha256'])
            result=executor.execute_3d_checkpoint(expected_track_id=TRACK_ID,
                read_preflight=lambda:self.snapshot(terminal.snapshot()),
                run_worker=lambda argv:calls.append(argv) or fixture.worker_receipt(),
                read_postflight=lambda:self.snapshot(terminal.snapshot(phase='post')),
                clock=lambda:terminal.now+self.delta)
            self.assertEqual(result['score_window'],'3d')
            self.assertFalse(result['readiness_credit'])
        self.assertEqual(calls,[executor.WORKER_ARGV,executor.WORKER_ARGV])
        self.assertEqual(original,(executor.OBSERVATION_STARTED_AT,executor.CHECKPOINT_24H_DUE_AT,executor.CHECKPOINT_3D_DUE_AT))
        self.assertIsNone(executor.current_observation())

    def test_old_window_and_cross_binding_never_dispatch(self):
        with self.assertRaisesRegex(executor.Item34CheckpointError,'old_observation_sealed'):
            with executor.observation_context({**self.binding,'observation_started_at':executor.OBSERVATION_STARTED_AT}):pass
        fixture=Item34TrackingCheckpointExecutorTests(); calls=[]
        with executor.observation_context(self.binding):
            pre=self.snapshot(fixture.preflight()); pre['observation_binding_sha256']='d'*64
            with self.assertRaises(executor.Item34CheckpointError):
                executor.execute_24h_checkpoint(expected_track_id=TRACK_ID,read_preflight=lambda:pre,
                    run_worker=lambda argv:calls.append(argv),schedule_3d=lambda *_:None,
                    read_postflight=lambda:None,clock=lambda:NOW+self.delta)
        self.assertEqual(calls,[])
        self.assertIsNone(executor.current_observation())

    def test_generation2_two_stages_and_complete_sealed_binding(self):
        self.binding=prospective_binding(2)
        self.test_two_stages_use_explicit_new_t0_and_leave_legacy_constants_unchanged()
        for change in ('missing','duplicate','out_of_order','alias'):
            binding=json.loads(json.dumps(self.binding))
            if change=='missing':binding['sealed_attempts'].pop(0)
            if change=='duplicate':binding['sealed_attempts'][0]['attempt_id']=binding['previous_attempt_id']
            if change=='out_of_order':binding['sealed_attempts'].reverse()
            if change=='alias':binding['previous_attempt_sha256']='e'*64
            with self.assertRaises(executor.Item34CheckpointError):
                with executor.observation_context(binding):pass


if __name__ == "__main__":
    unittest.main()
