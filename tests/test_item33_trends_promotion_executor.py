import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import execute_item33_trends_promotion as executor
import item33_trends_host_actions as host_actions


NOW = datetime(2026, 9, 8, 0, 10, tzinfo=timezone.utc)
RUN_IDENTITY = "1" * 64


class Item33TrendsPromotionExecutorTests(unittest.TestCase):
    def dependencies(self):
        return {
            "real_xhs_trends": {
                "verified": True,
                "evidence_sha256": "2" * 64,
                "terminal_bucket_date": "2026-09-07",
            },
            "internal_failure_rollback": {
                "verified": True,
                "evidence_sha256": "3" * 64,
            },
        }

    def preflight(self):
        return {
            "observed_at": NOW.isoformat(),
            "canonical_sha256": "4" * 64,
            "database_role": "noteai_xhs_trends",
            "role_exact": True,
            "acl_exact": True,
            "unit_sha256": executor.SUSPENDED_UNIT_SHA256,
            "unit_active": "inactive",
            "unit_sub": "dead",
            "unit_enabled": "disabled",
            "collection_suspended": True,
            "formal_container_count": 0,
            "active_run_count": 0,
            "same_bucket_run_count": 0,
            "outcome_unknown_count": 0,
            "unlinked_attempt_count": 0,
            "utc_provider_budget_used_before": 0,
            "utc_provider_budget_remaining_before": 34,
            "provider_calls": 0,
            "production_database_writes": 0,
        }

    def cycle(self):
        return {
            "run_identity_sha256": RUN_IDENTITY,
            "bucket_key": NOW.date().isoformat(),
            "started_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "lease_expires_at": (NOW + timedelta(minutes=30)).isoformat(),
            "cycle_count": 1,
            "same_bucket_completed_run_count": 1,
            "provider_request_count": 34,
            "provider_request_succeeded": 34,
            "provider_request_failed": 0,
            "outcome_unknown_count": 0,
            "automatic_retry_count": 0,
            "active_admitted_count": 0,
            "challenge_detected": False,
            "endpoint_counts": {
                "homefeed": 10,
                "search_recommend": 12,
                "search_notes": 12,
            },
            "published_keyword_count": 90,
            "minimum_real_keyword_count_per_domain": 12,
            "search_result_domain_count": 6,
            "search_recommend_domain_count": 6,
            "quality_snapshot_verified": True,
            "production_write_set_verified": True,
            "post_cycle_health": "ready",
            "canonical_result_sha256": "5" * 64,
        }

    def action(self, phase):
        before, after = {
            "promotion": (
                executor.SUSPENDED_UNIT_SHA256,
                executor.PROMOTED_UNIT_SHA256,
            ),
            "rollback": (
                executor.PROMOTED_UNIT_SHA256,
                executor.SUSPENDED_UNIT_SHA256,
            ),
            "reapply": (
                executor.SUSPENDED_UNIT_SHA256,
                executor.PROMOTED_UNIT_SHA256,
            ),
        }[phase]
        return {
            "phase": phase,
            "status": "applied",
            "unit_name": executor.UNIT_NAME,
            "before_unit_sha256": before,
            "after_unit_sha256": after,
            "mutation_count": 1,
            "other_unit_actions": 0,
            "provider_calls": 0,
            "production_database_writes": 0,
            "canonical_result_sha256": {
                "promotion": "6",
                "rollback": "7",
                "reapply": "8",
            }[phase]
            * 64,
        }

    def state(self, phase):
        active = phase in {"promoted", "final"}
        state = {
            "phase": phase,
            "observed_at": NOW.isoformat(),
            "canonical_sha256": {
                "promoted": "9",
                "rollback": "a",
                "final": "b",
            }[phase]
            * 64,
            "unit_sha256": (
                executor.PROMOTED_UNIT_SHA256
                if active
                else executor.SUSPENDED_UNIT_SHA256
            ),
            "unit_active": "active" if active else "inactive",
            "unit_sub": "running" if active else "dead",
            "unit_enabled": "enabled" if active else "disabled",
            "collection_suspended": not active,
            "formal_unit_count": 1,
            "formal_container_count": 1 if active else 0,
            "process_count": 1 if active else 0,
            "active_run_count": 0,
            "active_attempt_count": 0,
            "outcome_unknown_count": 0,
            "unlinked_attempt_count": 0,
            "health": "ready" if active else "stopped",
            "provider_calls": 0,
            "production_database_writes": 0,
            "task_container_count": 0,
            "inspection_container_count": 0,
            "stage_directory_count": 0,
            "runtime_directory_count": 0,
            "temporary_unit_count": 0,
            "temporary_dropin_count": 0,
        }
        if phase in {"rollback", "final"}:
            state.update(
                {
                    "preserved_run_count": 1,
                    "preserved_attempt_count": 34,
                    "preserved_snapshot_count": 1,
                    "database_audit_deletes": 0,
                    "same_bucket_new_run_delta": 0,
                    "same_bucket_provider_call_delta": 0,
                }
            )
        return state

    def invoke(self, **overrides):
        calls = []
        authorizations = []

        def wrap(name, value):
            def callback(*args):
                calls.append(name)
                if args:
                    authorizations.append((name, copy.deepcopy(args[0])))
                if isinstance(value, BaseException):
                    raise value
                return copy.deepcopy(value)

            return callback

        values = {
            "read_preflight": self.preflight(),
            "read_single_cycle": self.cycle(),
            "promote_unit": self.action("promotion"),
            "read_promoted": self.state("promoted"),
            "rollback_unit": self.action("rollback"),
            "read_rollback": self.state("rollback"),
            "reapply_unit": self.action("reapply"),
            "read_final": self.state("final"),
        }
        values.update(overrides)
        supplied_dependencies = values.pop("dependencies", self.dependencies())
        trusted_dependencies = values.pop(
            "trusted_dependencies", self.dependencies()
        )
        try:
            with mock.patch.object(
                executor,
                "_load_verified_dependencies",
                return_value=trusted_dependencies,
            ):
                result = executor.execute_item33_promotion(
                    dependencies=supplied_dependencies,
                    run_identity_sha256=values.pop(
                        "run_identity_sha256", RUN_IDENTITY
                    ),
                    read_preflight=wrap("preflight", values["read_preflight"]),
                    read_single_cycle=wrap("cycle", values["read_single_cycle"]),
                    promote_unit=wrap("promotion", values["promote_unit"]),
                    read_promoted=wrap(
                        "promoted_readback", values["read_promoted"]
                    ),
                    rollback_unit=wrap("rollback", values["rollback_unit"]),
                    read_rollback=wrap(
                        "rollback_readback", values["read_rollback"]
                    ),
                    reapply_unit=wrap("reapply", values["reapply_unit"]),
                    read_final=wrap("final_readback", values["read_final"]),
                    clock=lambda: NOW,
                )
        except executor.Item33ExecutionError as exc:
            exc.calls = list(calls)
            exc.authorizations = list(authorizations)
            raise
        return result, calls, authorizations

    def assert_code(self, expected, callback):
        with self.assertRaises(executor.Item33ExecutionError) as raised:
            callback()
        self.assertEqual(raised.exception.code, expected)
        return raised.exception

    def test_happy_path_has_one_cycle_and_one_transition_per_phase(self):
        result, calls, authorizations = self.invoke()

        self.assertEqual(
            calls,
            [
                "preflight",
                "promotion",
                "cycle",
                "promoted_readback",
                "rollback",
                "rollback_readback",
                "reapply",
                "final_readback",
            ],
        )
        self.assertEqual(
            result["action_counts"],
            {
                "cycle": 1,
                "promotion": 1,
                "rollback": 1,
                "reapply": 1,
                "automatic_retry": 0,
            },
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertFalse(result["readiness_credit"])
        self.assertFalse(result["secret_values_recorded"])
        cycle_auth = dict(authorizations)["cycle"]
        self.assertEqual(cycle_auth["provider_request_budget_remaining"], 34)
        self.assertEqual(
            cycle_auth["previous_item32_bucket_key"], "2026-09-07"
        )
        self.assertEqual(cycle_auth["permitted_endpoints"], list(executor.ENDPOINTS))
        self.assertEqual(cycle_auth["automatic_retry_limit"], 0)

    def test_unverified_dependency_blocks_every_callback(self):
        dependencies = self.dependencies()
        dependencies["real_xhs_trends"]["verified"] = False
        raised = self.assert_code(
            "dependency_unverified",
            lambda: self.invoke(dependencies=dependencies),
        )
        self.assertEqual(raised.calls, [])

    def test_forged_dependency_digest_blocks_every_callback(self):
        dependencies = self.dependencies()
        dependencies["real_xhs_trends"]["evidence_sha256"] = "f" * 64
        raised = self.assert_code(
            "dependency_unverified",
            lambda: self.invoke(dependencies=dependencies),
        )
        self.assertEqual(raised.calls, [])

    def test_item32_same_utc_bucket_blocks_every_callback(self):
        dependencies = self.dependencies()
        dependencies["real_xhs_trends"]["terminal_bucket_date"] = (
            NOW.date().isoformat()
        )
        raised = self.assert_code(
            "dependency_unverified",
            lambda: self.invoke(dependencies=dependencies),
        )
        self.assertEqual(raised.calls, [])

        same_bucket = self.dependencies()
        trusted = self.dependencies()
        same_bucket["real_xhs_trends"]["terminal_bucket_date"] = (
            NOW.date().isoformat()
        )
        trusted["real_xhs_trends"]["terminal_bucket_date"] = (
            NOW.date().isoformat()
        )
        raised = self.assert_code(
            "utc_budget_not_available",
            lambda: self.invoke(
                dependencies=same_bucket,
                trusted_dependencies=trusted,
            ),
        )
        self.assertEqual(raised.calls, [])

    def test_preflight_unknown_or_exhausted_budget_blocks_cycle(self):
        for field, value in (
            ("outcome_unknown_count", 1),
            ("utc_provider_budget_used_before", 34),
        ):
            preflight = self.preflight()
            preflight[field] = value
            if field == "utc_provider_budget_used_before":
                preflight["utc_provider_budget_remaining_before"] = 0
            with self.subTest(field=field):
                raised = self.assert_code(
                    "preflight",
                    lambda preflight=preflight: self.invoke(
                        read_preflight=preflight
                    ),
                )
                self.assertEqual(raised.calls, ["preflight"])

    def test_future_or_preused_bucket_preflight_blocks_promotion(self):
        cases = []
        future = self.preflight()
        future["observed_at"] = (NOW + timedelta(minutes=4)).isoformat()
        cases.append(future)
        preused = self.preflight()
        preused["utc_provider_budget_used_before"] = 1
        preused["utc_provider_budget_remaining_before"] = 33
        cases.append(preused)
        existing_run = self.preflight()
        existing_run["same_bucket_run_count"] = 1
        cases.append(existing_run)
        for preflight in cases:
            with self.subTest(preflight=preflight):
                raised = self.assert_code(
                    "preflight",
                    lambda preflight=preflight: self.invoke(
                        read_preflight=preflight
                    ),
                )
                self.assertEqual(raised.calls, ["preflight"])

    def test_preflight_that_ages_during_readback_blocks_promotion(self):
        calls = []
        clocks = iter((NOW, NOW + timedelta(minutes=10)))
        with mock.patch.object(
            executor,
            "_load_verified_dependencies",
            return_value=self.dependencies(),
        ):
            with self.assertRaises(executor.Item33ExecutionError) as raised:
                executor.execute_item33_promotion(
                    dependencies=self.dependencies(),
                    run_identity_sha256=RUN_IDENTITY,
                    read_preflight=lambda: calls.append("preflight")
                    or self.preflight(),
                    read_single_cycle=lambda _authorization: calls.append("cycle"),
                    promote_unit=lambda _authorization: calls.append("promotion"),
                    read_promoted=lambda: calls.append("promoted"),
                    rollback_unit=lambda _authorization: calls.append("rollback"),
                    read_rollback=lambda: calls.append("rollback_readback"),
                    reapply_unit=lambda _authorization: calls.append("reapply"),
                    read_final=lambda: calls.append("final"),
                    clock=lambda: next(clocks),
                )
        self.assertEqual(raised.exception.code, "preflight")
        self.assertEqual(calls, ["preflight"])

    def test_cycle_callback_unknown_is_sealed_without_retry(self):
        calls = []
        sensitive = "synthetic-cookie-must-not-escape"

        def execute():
            with mock.patch.object(
                executor,
                "_load_verified_dependencies",
                return_value=self.dependencies(),
            ):
                return executor.execute_item33_promotion(
                    dependencies=self.dependencies(),
                    run_identity_sha256=RUN_IDENTITY,
                    read_preflight=lambda: calls.append("preflight")
                    or self.preflight(),
                    read_single_cycle=lambda _authorization: (
                        calls.append("cycle")
                        or (_ for _ in ()).throw(RuntimeError(sensitive))
                    ),
                    promote_unit=lambda _authorization: (
                        calls.append("promotion") or self.action("promotion")
                    ),
                    read_promoted=lambda: calls.append("promoted"),
                    rollback_unit=lambda _authorization: (
                        calls.append("rollback") or self.action("rollback")
                    ),
                    read_rollback=lambda: (
                        calls.append("rollback_readback")
                        or self.state("rollback")
                    ),
                    reapply_unit=lambda _authorization: calls.append("reapply"),
                    read_final=lambda: calls.append("final"),
                    clock=lambda: NOW,
                )

        try:
            execute()
        except executor.Item33ExecutionError as raised:
            rendered = "".join(traceback.format_exception(raised))
            self.assertEqual(raised.code, "cycle_outcome_unknown")
            self.assertIsNone(raised.__cause__)
            self.assertNotIn(sensitive, rendered)
        else:
            self.fail("unknown cycle must fail closed")
        self.assertEqual(
            calls,
            ["preflight", "promotion", "cycle", "rollback", "rollback_readback"],
        )

    def test_callback_item33_error_is_sealed_without_sensitive_text(self):
        sensitive = "synthetic-sensitive-marker"
        try:
            self.invoke(
                promote_unit=executor.Item33ExecutionError(sensitive)
            )
        except executor.Item33ExecutionError as raised:
            rendered = "".join(traceback.format_exception(raised))
            self.assertEqual(raised.code, "promotion_outcome_unknown")
            self.assertIsNone(raised.__cause__)
            self.assertNotIn(sensitive, rendered)
            self.assertEqual(raised.calls, ["preflight", "promotion"])
        else:
            self.fail("callback exception must fail closed")

    def test_cycle_cannot_complete_after_lease(self):
        cycle = self.cycle()
        cycle["completed_at"] = (NOW + timedelta(minutes=31)).isoformat()
        raised = self.assert_code(
            "cycle", lambda: self.invoke(read_single_cycle=cycle)
        )
        self.assertEqual(
            raised.calls[-3:], ["cycle", "rollback", "rollback_readback"]
        )

    def test_bounded_partial_cycle_with_both_search_endpoints_is_allowed(self):
        cycle = self.cycle()
        cycle["provider_request_count"] = 3
        cycle["provider_request_succeeded"] = 3
        cycle["endpoint_counts"] = {
            "homefeed": 1,
            "search_recommend": 1,
            "search_notes": 1,
        }
        rollback = self.state("rollback")
        rollback["preserved_attempt_count"] = 3
        final = self.state("final")
        final["preserved_attempt_count"] = 3

        result, _calls, _authorizations = self.invoke(
            read_single_cycle=cycle,
            read_rollback=rollback,
            read_final=final,
        )

        self.assertEqual(result["cycle"]["provider_request_count"], 3)
        self.assertEqual(result["status"], "VERIFIED")

    def test_invalid_cycle_is_stopped_by_one_rollback_and_never_reapplied(self):
        for field, value in (
            ("outcome_unknown_count", 1),
            ("automatic_retry_count", 1),
        ):
            cycle = self.cycle()
            cycle[field] = value
            with self.subTest(field=field):
                raised = self.assert_code(
                    "cycle",
                    lambda cycle=cycle: self.invoke(read_single_cycle=cycle),
                )
                self.assertEqual(
                    raised.calls[-3:],
                    ["cycle", "rollback", "rollback_readback"],
                )
                self.assertNotIn("reapply", raised.calls)

        searchless = self.cycle()
        searchless["endpoint_counts"] = {
            "homefeed": 34,
            "search_recommend": 0,
            "search_notes": 0,
        }
        raised = self.assert_code(
            "cycle",
            lambda: self.invoke(read_single_cycle=searchless),
        )
        self.assertEqual(
            raised.calls[-3:],
            ["cycle", "rollback", "rollback_readback"],
        )

    def test_unknown_or_invalid_promotion_is_not_blindly_rolled_back(self):
        unknown = self.assert_code(
            "promotion_outcome_unknown",
            lambda: self.invoke(promote_unit=RuntimeError("opaque")),
        )
        self.assertEqual(unknown.calls[-1], "promotion")
        self.assertNotIn("rollback", unknown.calls)
        invalid = self.action("promotion")
        invalid["mutation_count"] = 0
        malformed = self.assert_code(
            "promotion", lambda: self.invoke(promote_unit=invalid)
        )
        self.assertNotIn("rollback", malformed.calls)

    def test_known_promotion_with_bad_readback_rolls_back_once(self):
        promoted = self.state("promoted")
        promoted["formal_container_count"] = 0
        with self.assertRaises(executor.Item33ExecutionError) as raised:
            self.invoke(read_promoted=promoted)
        self.assertEqual(raised.exception.code, "promoted_readback")
        self.assertEqual(
            raised.exception.calls[-3:],
            ["promoted_readback", "rollback", "rollback_readback"],
        )
        self.assertNotIn("reapply", raised.exception.calls)

    def test_bad_promoted_readback_then_unknown_rollback_is_recovery_failed(self):
        promoted = self.state("promoted")
        promoted["health"] = "unready"
        raised = self.assert_code(
            "recovery_failed",
            lambda: self.invoke(
                read_promoted=promoted,
                rollback_unit=RuntimeError("opaque"),
            ),
        )
        self.assertEqual(raised.calls[-2:], ["promoted_readback", "rollback"])

    def test_unknown_rollback_never_reapplies(self):
        raised = self.assert_code(
            "rollback_outcome_unknown",
            lambda: self.invoke(rollback_unit=RuntimeError("opaque")),
        )
        self.assertEqual(raised.calls[-1], "rollback")
        self.assertNotIn("reapply", raised.calls)

    def test_bad_rollback_readback_never_reapplies(self):
        rollback = self.state("rollback")
        rollback["unit_active"] = "active"
        raised = self.assert_code(
            "rollback_readback",
            lambda: self.invoke(read_rollback=rollback),
        )
        self.assertEqual(raised.calls[-1], "rollback_readback")
        self.assertNotIn("reapply", raised.calls)

    def test_unknown_reapply_never_retries_or_reads_final(self):
        raised = self.assert_code(
            "reapply_outcome_unknown",
            lambda: self.invoke(reapply_unit=RuntimeError("opaque")),
        )
        self.assertEqual(raised.calls[-1], "reapply")
        self.assertNotIn("final_readback", raised.calls)

    def test_final_readback_must_prove_exact_singleton(self):
        final = self.state("final")
        final["process_count"] = 2
        self.assert_code(
            "final_readback", lambda: self.invoke(read_final=final)
        )

    def test_boolean_counts_and_noncanonical_identity_fail_closed(self):
        preflight = self.preflight()
        preflight["formal_container_count"] = False
        self.assert_code(
            "preflight", lambda: self.invoke(read_preflight=preflight)
        )
        self.assert_code(
            "run_identity", lambda: self.invoke(run_identity_sha256="ABC")
        )


class Item33HostActionPreparationTests(unittest.TestCase):
    def suspended(self):
        return (ROOT / "deploy/production/systemd/noteai-xhs-trends.service.template").read_bytes().replace(
            b"@@NOTEAI_XHS_IMAGE@@",
            b"sha256:a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec",
        )

    def dependencies(self):
        return Item33TrendsPromotionExecutorTests().dependencies()

    def test_renderer_preserves_exact_rollback_and_adds_only_three_readonly_mounts(self):
        original = self.suspended()
        self.assertEqual(hashlib.sha256(original).hexdigest(), executor.SUSPENDED_UNIT_SHA256)
        candidate = executor.render_managed_unit(original)
        self.assertEqual(hashlib.sha256(candidate).hexdigest(), executor.PROMOTED_UNIT_SHA256)
        self.assertEqual(candidate.count(b"--mount=type=bind,"), 3)
        self.assertEqual(candidate.count(b",readonly"), 3)
        self.assertIn(b"Restart=no\n", candidate)
        self.assertIn(b"python market_timing_worker.py --daemon --interval 360", candidate)
        self.assertEqual(self.suspended(), original)
        with self.assertRaisesRegex(executor.Item33ExecutionError, "suspended_unit_binding"):
            executor.render_managed_unit(original + b"\n")

    def test_missing_dependency_or_same_bucket_stops_before_host_or_state(self):
        with mock.patch.object(executor, "_load_verified_dependencies", side_effect=executor.Item33ExecutionError("dependency_unverified")), mock.patch.object(
            host_actions, "_run", side_effect=AssertionError("host forbidden")
        ):
            with self.assertRaisesRegex(executor.Item33ExecutionError, "dependency_unverified"):
                host_actions.Item33HostUnitActions(dependencies=self.dependencies())
        with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
            host_actions, "_run", side_effect=AssertionError("host forbidden")
        ):
            with self.assertRaisesRegex(executor.Item33ExecutionError, "utc_budget_not_available"):
                host_actions.Item33HostUnitActions(dependencies=self.dependencies(),
                    clock=lambda: datetime(2026, 9, 7, 23, 59, tzinfo=timezone.utc))

    def test_host_identity_accepts_only_exact_api_f_instance(self):
        with mock.patch.object(host_actions, "_imds", side_effect=["test-token", host_actions.EXPECTED_INSTANCE_ID]) as imds:
            host_actions._assert_host_identity()
            self.assertEqual(imds.call_args_list, [
                mock.call("/latest/api/token", method="PUT",
                    headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"}),
                mock.call("/latest/meta-data/instance-id",
                    headers={"X-aliyun-ecs-metadata-token": "test-token"}),
            ])
        with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
            host_actions.os, "geteuid", return_value=0
        ), mock.patch.object(host_actions, "_imds", side_effect=["test-token", "i-wz9j36od3nf2b1uw7bvg"]), mock.patch.object(
            host_actions, "_regular", side_effect=AssertionError("file forbidden")
        ), mock.patch.object(host_actions, "_run", side_effect=AssertionError("unit forbidden")):
            actions = host_actions.Item33HostUnitActions(dependencies=self.dependencies(), clock=lambda: NOW)
            with self.assertRaisesRegex(executor.Item33ExecutionError, "host_identity"):
                actions.promote_unit({"unit_name": executor.UNIT_NAME,
                    "run_identity_sha256": RUN_IDENTITY, "automatic_retry_limit": 0})

    def test_exclusive_marker_syncs_file_then_parent_and_cannot_overwrite(self):
        sync = os.fsync
        events = []

        def observed_sync(descriptor):
            events.append("directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file")
            sync(descriptor)

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(host_actions.os, "fsync", side_effect=observed_sync):
            path = Path(directory) / "started.json"
            host_actions._exclusive(path, b"original")
            self.assertEqual(events, ["file", "directory"])
            with self.assertRaises(FileExistsError):
                host_actions._exclusive(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(events, ["file", "directory"])

    @unittest.skipUnless(os.geteuid() == 0, "host metadata checks run in the isolated root test container")
    def test_real_unit_callbacks_keep_action_markers_and_never_replay(self):
        self.exercise_actions()

    @unittest.skipUnless(os.geteuid() == 0, "host metadata checks run in the isolated root test container")
    def test_unknown_reload_keeps_changed_unit_and_refuses_second_promotion(self):
        self.exercise_actions(fail_reload=True)

    @unittest.skipUnless(os.geteuid() == 0, "host metadata checks run in the isolated root test container")
    def test_reapply_in_next_bucket_is_rejected_before_start(self):
        self.exercise_actions(reapply_next_day=True)

    @unittest.skipUnless(os.geteuid() == 0, "host metadata checks run in the isolated root test container")
    def test_promotion_crossing_midnight_during_reload_keeps_unknown_and_does_not_start(self):
        self.exercise_actions(cross_during_reload="promotion")

    @unittest.skipUnless(os.geteuid() == 0, "host metadata checks run in the isolated root test container")
    def test_reapply_crossing_midnight_during_reload_keeps_unknown_and_does_not_start(self):
        self.exercise_actions(cross_during_reload="reapply")

    def exercise_actions(self, *, fail_reload=False, reapply_next_day=False, cross_during_reload=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unit = root / executor.UNIT_NAME
            original = self.suspended()
            unit.write_bytes(original)
            unit.chmod(0o644)
            overlay = root / "runtime"
            overlay.mkdir(mode=0o700)
            (overlay / "model").mkdir(mode=0o700)
            for name in executor.RUNTIME_OVERLAY_SHA256:
                path = overlay / name
                path.write_bytes((ROOT / name).read_bytes())
                path.chmod(0o444)
            action_root = root / "actions"
            now = [NOW]
            commands = []

            def run(argv):
                commands.append(argv)
                if "FragmentPath" in argv:
                    return str(unit).encode()
                if "DropInPaths" in argv:
                    return b""
                if fail_reload and argv == ["systemctl", "daemon-reload"]:
                    raise executor.Item33ExecutionError("host_action_outcome_unknown")
                if argv == ["systemctl", "daemon-reload"] and (
                    (cross_during_reload == "promotion" and commands.count(argv) == 1)
                    or (cross_during_reload == "reapply" and commands.count(argv) == 3)
                ):
                    now[0] = NOW + timedelta(days=1)
                return b""

            # Only filesystem metadata and action sequencing use temporary real
            # files. Every host command/dependency is isolated and synthetic.
            with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
                host_actions, "UNIT_PATH", unit
            ), mock.patch.object(host_actions, "ACTION_ROOT", action_root), mock.patch.object(
                host_actions, "_run", side_effect=run
            ), mock.patch.object(host_actions, "_assert_host_identity"):
                actions = host_actions.Item33HostUnitActions(dependencies=self.dependencies(), clock=lambda: now[0])
                with mock.patch.object(executor, "RUNTIME_OVERLAY_ROOT", overlay):
                    actions._assert_overlays()
                # Renderer stays bound to the canonical production mount paths.
                with mock.patch.object(actions, "_assert_overlays"):
                    promotion = {"unit_name": executor.UNIT_NAME, "run_identity_sha256": RUN_IDENTITY,
                        "automatic_retry_limit": 0, "cycle_authorization": {
                            "run_identity_sha256": RUN_IDENTITY, "bucket_key": NOW.date().isoformat(),
                            "provider_request_limit": 34, "automatic_retry_limit": 0}}
                    recovery = {key: value for key, value in promotion.items() if key != "cycle_authorization"}
                    if fail_reload:
                        with self.assertRaisesRegex(executor.Item33ExecutionError, "host_action_outcome_unknown"):
                            actions.promote_unit(promotion)
                        self.assertTrue((action_root / "promotion.started.json").exists())
                        self.assertFalse((action_root / "promotion.applied.json").exists())
                        with self.assertRaises(executor.Item33ExecutionError):
                            actions.promote_unit(promotion)
                        self.assertEqual(commands.count(["systemctl", "daemon-reload"]), 1)
                        return
                    if cross_during_reload == "promotion":
                        with self.assertRaisesRegex(executor.Item33ExecutionError, "start_bucket_expired"):
                            actions.promote_unit(promotion)
                        self.assertTrue((action_root / "promotion.started.json").exists())
                        self.assertFalse((action_root / "promotion.applied.json").exists())
                        self.assertEqual(unit.read_bytes(), executor.render_managed_unit(original))
                        self.assertEqual(commands.count(["systemctl", "enable", "--now", executor.UNIT_NAME]), 0)
                        return
                    self.assertEqual(actions.promote_unit(promotion)["status"], "applied")
                    self.assertEqual(unit.read_bytes(), executor.render_managed_unit(original))
                    self.assertEqual(actions.rollback_unit(recovery)["status"], "applied")
                    self.assertEqual(unit.read_bytes(), original)
                    if reapply_next_day:
                        now[0] = NOW + timedelta(days=1)
                        with self.assertRaisesRegex(executor.Item33ExecutionError, "reapply_bucket_or_rollback_binding"):
                            actions.reapply_unit(recovery)
                        self.assertEqual(commands.count(["systemctl", "enable", "--now", executor.UNIT_NAME]), 1)
                        return
                    if cross_during_reload == "reapply":
                        with self.assertRaisesRegex(executor.Item33ExecutionError, "start_bucket_expired"):
                            actions.reapply_unit(recovery)
                        self.assertTrue((action_root / "reapply.started.json").exists())
                        self.assertFalse((action_root / "reapply.applied.json").exists())
                        self.assertEqual(unit.read_bytes(), executor.render_managed_unit(original))
                        self.assertEqual(commands.count(["systemctl", "enable", "--now", executor.UNIT_NAME]), 1)
                        return
                    self.assertEqual(actions.reapply_unit(recovery)["status"], "applied")
                    self.assertEqual(unit.read_bytes(), executor.render_managed_unit(original))
                    with self.assertRaises(executor.Item33ExecutionError):
                        actions.reapply_unit(recovery)
                    self.assertEqual(commands.count(["systemctl", "enable", "--now", executor.UNIT_NAME]), 2)
                    self.assertEqual((action_root / "suspended-unit.rollback").read_bytes(), original)
                    self.assertEqual(json.loads((action_root / "promotion.started.json").read_text())["status"], "STARTED_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
