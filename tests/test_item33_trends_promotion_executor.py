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
                with mock.patch.object(executor, "RUNTIME_OVERLAY_ROOT", overlay), mock.patch.object(
                    executor, "RUNTIME_OVERLAY_SHA256", {
                        name: hashlib.sha256((overlay / name).read_bytes()).hexdigest()
                        for name in executor.RUNTIME_OVERLAY_SHA256
                    }
                ):
                    # This fixture tests filesystem metadata with current source
                    # bytes. The renderer above separately pins the old release.
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


class Item33V5PromotionTests(unittest.TestCase):
    now = datetime(2026, 9, 19, 0, 10, tzinfo=timezone.utc)
    activation = "a" * 64

    def dependencies(self):
        value = Item33TrendsPromotionExecutorTests().dependencies()
        value["real_xhs_trends"].update(
            evidence_sha256=executor.V5_ITEM32_TERMINAL_SHA256,
            terminal_bucket_date="2026-09-18", runtime_profile=executor.V5_PROFILE)
        return value

    def capture(self):
        return {
            "source_sha256": {name: str(index) * 64 for index, name in enumerate(executor.V5_CAPTURE_TOOLS, 1)},
            "launcher_sha256": hashlib.sha256(executor.V5_CAPTURE_LAUNCHER).hexdigest(),
            "configuration_sha256": "c" * 64,
            "activation_identity_sha256": self.activation,
        }

    def retime(self, value):
        return json.loads(json.dumps(value).replace("2026-09-08", "2026-09-19"))

    def cycle(self):
        value = self.retime(Item33TrendsPromotionExecutorTests().cycle())
        value["activation_identity_sha256"] = self.activation
        observations, attempts = [], []
        kinds = ["dsl", "session", *(["homefeed"] * 10),
                 *[kind for _ in range(12) for kind in ("search_recommend", "search_notes")]]
        for index, kind in enumerate(kinds, 1):
            metadata = {"request_kind": kind, "sequence": index, "at": self.now.isoformat()}
            observations.extend([
                {**metadata, "phase": "dispatch"},
                {**metadata, "phase": "response", "response_diagnostics": {
                    "http_status": 200, "payload_kind": "non_json" if kind == "dsl" else "object",
                    "success_state": "absent" if kind == "dsl" else "true",
                    "business_code_kind": "integer", "business_code": 0, "message_tags": []}},
            ])
            if index > 2:
                attempts.append({"attempt_identity_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
                    "ordinal": index - 2, "endpoint": kind, "status": "succeeded",
                    "admitted_at": self.now.isoformat(), "completed_at": self.now.isoformat()})
        value["attempts"] = attempts
        value["physical_http"] = {
            "initialization_count": 2, "collection_count": 34, "total_count": 36, "total_limit": 36,
            "automatic_retry_count": 0, "first_homefeed_is_gate": True,
            "worker_receipt_sha256": "b" * 64, "observations": observations}
        return value

    def state(self, phase):
        value = self.retime(Item33TrendsPromotionExecutorTests().state(phase))
        value.update(activation_identity_sha256=self.activation, run_identity_sha256=RUN_IDENTITY)
        if phase != "rollback":
            value["unit_sha256"] = executor.V5_PROMOTED_UNIT_SHA256
        return value

    def action(self, phase):
        value = Item33TrendsPromotionExecutorTests().action(phase)
        for key in ("before_unit_sha256", "after_unit_sha256"):
            if value[key] == executor.PROMOTED_UNIT_SHA256:
                value[key] = executor.V5_PROMOTED_UNIT_SHA256
        return value

    def invoke(self, *, cycle=None, now=None, actual_run_argument=None, capture=None, state_override=None):
        calls, authorizations = [], []
        def callback(name, result):
            def read(*args):
                calls.append(name)
                authorizations.extend(args)
                return result
            return read
        options = {"activation_identity_sha256": self.activation,
                   "capture_binding": capture or self.capture()}
        if actual_run_argument is not None:
            options["run_identity_sha256"] = actual_run_argument
        with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()):
            try:
                result = executor.execute_item33_promotion(
                    dependencies=self.dependencies(), **options,
                    read_preflight=callback("preflight", self.retime(Item33TrendsPromotionExecutorTests().preflight())),
                    read_single_cycle=callback("cycle", self.cycle() if cycle is None else cycle),
                    promote_unit=callback("promotion", self.action("promotion")),
                    read_promoted=callback("promoted", state_override or self.state("promoted")),
                    rollback_unit=callback("rollback", self.action("rollback")),
                    read_rollback=callback("rollback_readback", self.state("rollback")),
                    reapply_unit=callback("reapply", self.action("reapply")),
                    read_final=callback("final", self.state("final")), clock=lambda: now or self.now)
            except executor.Item33ExecutionError as exc:
                exc.calls = calls
                raise
        return result, calls, authorizations

    def test_renderer_pins_actual_image_eight_sources_capture_and_original_entrypoint(self):
        import shlex
        original = Item33HostActionPreparationTests().suspended()
        rendered = executor.render_managed_unit(original, runtime_profile=executor.V5_PROFILE)
        self.assertEqual(hashlib.sha256(rendered).hexdigest(), executor.V5_PROMOTED_UNIT_SHA256)
        self.assertEqual(rendered.count(b"--mount=type=bind,"), 13)
        self.assertEqual(rendered.count(b",readonly"), 13)
        self.assertNotIn(b"--entrypoint", rendered)
        self.assertEqual(rendered.count(executor.V5_IMAGE_CONFIG_SHA256.encode()), 2)
        line = next(line for line in rendered.decode().splitlines() if line.startswith("ExecStart="))
        arguments = shlex.split(line.removeprefix("ExecStart="))
        self.assertEqual(arguments[-1], "/app/scripts/render_run_market_timing.sh")
        budget = next(value.split("=", 2)[2] for value in arguments if value.startswith("--env=NOTEAI_XHS_V5_BUDGET_JSON="))
        self.assertEqual(json.loads(budget), {"initialization": 2, "collection": 34, "total": 36})
        for name in executor.V5_RUNTIME_OVERLAY_SHA256:
            self.assertEqual(sum(f"dst=/app/{name},readonly" in item for item in arguments), 1)
        self.assertEqual(hashlib.sha256(original).hexdigest(), executor.SUSPENDED_UNIT_SHA256)
        self.assertIn(b"Restart=no", rendered)
        self.assertIn(b"python market_timing_worker.py --healthcheck", rendered)

    def test_complete_cycle_observes_run_after_activation_and_keeps_one_rehearsal(self):
        result, calls, authorizations = self.invoke()
        self.assertEqual(result["run_identity_sha256"], RUN_IDENTITY)
        self.assertEqual(result["activation_identity_sha256"], self.activation)
        self.assertNotIn("run_identity_sha256", result["authorization"])
        self.assertEqual(result["authorization"]["physical_http_limit"], 36)
        self.assertEqual(calls, ["preflight", "promotion", "cycle", "promoted", "rollback", "rollback_readback", "reapply", "final"])
        self.assertEqual(result["action_counts"], {"cycle": 1, "promotion": 1, "rollback": 1, "reapply": 1, "automatic_retry": 0})
        self.assertTrue(all(item["activation_identity_sha256"] == self.activation for item in authorizations))

    def test_preselected_run_and_same_item32_bucket_stop_before_actions(self):
        for kwargs, code in (({"actual_run_argument": RUN_IDENTITY}, "run_identity_must_be_observed"),
                             ({"now": self.now - timedelta(days=1)}, "utc_budget_not_available")):
            with self.subTest(code=code), self.assertRaises(executor.Item33ExecutionError) as caught:
                self.invoke(**kwargs)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.calls, [])

    def test_different_activation_cannot_supply_actual_cycle(self):
        value = self.cycle()
        value["activation_identity_sha256"] = "d" * 64
        with self.assertRaises(executor.Item33ExecutionError) as caught:
            self.invoke(cycle=value)
        self.assertEqual(caught.exception.code, "cycle")
        self.assertEqual(caught.exception.calls[-2:], ["rollback", "rollback_readback"])
        self.assertNotIn("reapply", caught.exception.calls)

    def test_missing_initialization_unknown_response_and_duplicate_attempt_fail(self):
        for mutation in ("init", "unknown", "duplicate", "wrong_endpoint"):
            value = self.cycle()
            if mutation == "init": value["physical_http"]["initialization_count"] = 0
            if mutation == "unknown": value["physical_http"]["observations"][1]["phase"] = "unknown"
            if mutation == "duplicate": value["attempts"][1]["attempt_identity_sha256"] = value["attempts"][0]["attempt_identity_sha256"]
            if mutation == "wrong_endpoint": value["attempts"][0]["endpoint"] = "search_notes"
            with self.subTest(mutation=mutation), self.assertRaises(executor.Item33ExecutionError) as caught:
                self.invoke(cycle=value)
            self.assertEqual(caught.exception.code, "cycle_physical_http")
            self.assertEqual(caught.exception.calls.count("rollback"), 1)
            self.assertNotIn("reapply", caught.exception.calls)

    def test_old_promoted_image_readback_is_not_accepted_as_v5(self):
        state = self.state("promoted")
        state["unit_sha256"] = executor.PROMOTED_UNIT_SHA256
        with self.assertRaises(executor.Item33ExecutionError) as caught:
            self.invoke(state_override=state)
        self.assertEqual(caught.exception.code, "promoted_readback")
        self.assertNotIn("reapply", caught.exception.calls)

    def test_readback_run_cannot_change_after_durable_cycle(self):
        state = self.state("promoted")
        state["run_identity_sha256"] = "f" * 64
        with self.assertRaises(executor.Item33ExecutionError) as caught:
            self.invoke(state_override=state)
        self.assertEqual(caught.exception.code, "promoted_readback")

    def test_capture_launcher_hash_and_profile_shape_fail_before_preflight(self):
        value = self.capture()
        value["launcher_sha256"] = "d" * 64
        with self.assertRaises(executor.Item33ExecutionError) as caught:
            self.invoke(capture=value)
        self.assertEqual(caught.exception.code, "capture_binding")
        self.assertEqual(caught.exception.calls, [])
        with self.assertRaisesRegex(executor.Item33ExecutionError, "runtime_profile_binding"):
            executor.render_managed_unit(Item33HostActionPreparationTests().suspended(), runtime_profile="unbound")

    def normal_fixture(self):
        prior = self.invoke()[0]
        preserved = {"run_count": 1, "attempt_count": 34, "snapshot_count": 1,
                     "run_sha256": "1" * 64, "attempt_ledger_sha256": "2" * 64, "snapshot_sha256": "3" * 64}
        raw = b'{"synthetic_seal":true}'
        readback = {"schema": "noteai.item33.normal_readback.v1", "activation_identity_sha256": self.activation,
            "run_identity_sha256": RUN_IDENTITY, "bucket_key": self.now.date().isoformat(), "observed_at": self.now.isoformat(),
            "unit_sha256": executor.V5_NORMAL_UNIT_SHA256, "preserved": preserved,
            "final": {"active": "active", "sub": "running", "enabled": "enabled", "collection_suspended": False,
                      "formal_unit_count": 1, "formal_container_count": 1, "process_count": 1, "health": "ready"},
            "same_bucket": {"bucket_key": self.now.date().isoformat(), "new_run_delta": 0, "provider_call_delta": 0},
            "capture_receipt_sha256": hashlib.sha256(raw).hexdigest(), "teardown_sha256": hashlib.sha256(b"synthetic teardown").hexdigest(),
            "capture_close": {**{prefix+"_ref": "deploy/production/evidence/production-item33-trends-"+name+".json" for prefix,name in
                (("service_result","capture-service-result"),("close","capture-service-close"),("host","normal-host-readback"))},
                **{prefix+"_sha256":"a"*64 for prefix in ("service_result","close","host")}}, "secret_values_recorded": False}
        action = self.action("reapply")
        action.update(phase="normal_handoff", before_unit_sha256=executor.V5_PROMOTED_UNIT_SHA256,
                      after_unit_sha256=executor.V5_NORMAL_UNIT_SHA256, started_at=self.now.isoformat(), completed_at=self.now.isoformat())
        return prior, preserved, raw, readback, action

    def test_normal_records_action_times_separately_from_later_readback(self):
        prior,preserved,raw,readback,action=self.normal_fixture()
        action['started_at']=(self.now+timedelta(seconds=1)).isoformat()
        action['completed_at']=(self.now+timedelta(seconds=2)).isoformat()
        readback['observed_at']=(self.now+timedelta(seconds=3)).isoformat()
        ticks=iter((self.now,self.now,self.now+timedelta(seconds=3),self.now+timedelta(seconds=4)))
        with mock.patch.object(executor,'_load_verified_dependencies',return_value=self.dependencies()), mock.patch.object(
            executor,'_validate_capture_seal',return_value={}),mock.patch.object(executor,'_validate_teardown',return_value={}):
            value=executor.execute_item33_normal_handoff(dependencies=self.dependencies(),previous_result=prior,preserved=preserved,
                capture_seal_raw=raw,capture_journal=b'synthetic journal',teardown_raw=b'synthetic teardown',
                handoff_unit=lambda _:action,read_normal=lambda:readback,clock=lambda:next(ticks))
        self.assertEqual(value['started_at'],action['started_at']);self.assertEqual(value['completed_at'],action['completed_at'])
        self.assertEqual(value['observed_at'],readback['observed_at']);self.assertNotEqual(value['completed_at'],value['observed_at'])
        self.assertEqual(value['capture_close'],readback['capture_close'])

    def test_invalid_teardown_prevents_the_unit_callback(self):
        prior,preserved,raw,readback,action=self.normal_fixture();handoff=mock.Mock(return_value=action)
        with mock.patch.object(executor,'_load_verified_dependencies',return_value=self.dependencies()), mock.patch.object(
            executor,'_validate_capture_seal',return_value={}):
            with self.assertRaisesRegex(executor.Item33ExecutionError,'normal_teardown_unverified'):
                executor.execute_item33_normal_handoff(dependencies=self.dependencies(),previous_result=prior,preserved=preserved,
                    capture_seal_raw=raw,capture_journal=b'synthetic journal',teardown_raw=b'synthetic teardown',
                    handoff_unit=handoff,read_normal=lambda:readback,clock=lambda:self.now)
        handoff.assert_not_called()

    def test_normal_renderer_has_eight_sources_and_original_allowed_command(self):
        original = Item33HostActionPreparationTests().suspended()
        normal = executor.render_managed_unit(original, runtime_profile=executor.V5_PROFILE, normal=True)
        self.assertEqual(hashlib.sha256(normal).hexdigest(), executor.V5_NORMAL_UNIT_SHA256)
        self.assertEqual(normal.count(b"--mount=type=bind,"), 8)
        self.assertIn(b"python market_timing_worker.py --daemon --interval 360", normal)
        self.assertNotIn(b"capture", normal)
        self.assertNotIn(b"--entrypoint", normal)
        capture = executor.render_managed_unit(original, runtime_profile=executor.V5_PROFILE)
        self.assertEqual(hashlib.sha256(capture).hexdigest(), executor.V5_PROMOTED_UNIT_SHA256)

    def test_normal_handoff_requires_real_seal_verifier_before_one_action(self):
        prior, preserved, raw, readback, action = self.normal_fixture()
        handoff = mock.Mock(return_value=action)
        # This isolates orchestration only; production C verifier is independently
        # tested against the actual row-count journal and catalog contract.
        with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
            executor, "_validate_capture_seal", return_value={}) as verifier, mock.patch.object(executor, "_validate_teardown", return_value={}):
            value = executor.execute_item33_normal_handoff(dependencies=self.dependencies(), previous_result=prior,
                preserved=preserved, capture_seal_raw=raw, capture_journal=b"synthetic journal", teardown_raw=b"synthetic teardown",
                handoff_unit=handoff, read_normal=lambda: readback, clock=lambda: self.now)
        verifier.assert_called_once_with(prior["capture_binding"], RUN_IDENTITY, self.now.date().isoformat(), raw, b"synthetic journal")
        handoff.assert_called_once()
        self.assertEqual(value["normal_unit_sha256"], executor.V5_NORMAL_UNIT_SHA256)
        self.assertEqual(value["preserved"], preserved)
        self.assertEqual(value["readback_sha256"], hashlib.sha256(executor._normal_json_bytes(readback)).hexdigest())
        self.assertTrue(executor._normal_json_bytes(readback).endswith(b"\n"))
        self.assertEqual(prior["final_readback"]["unit_sha256"], executor.V5_PROMOTED_UNIT_SHA256)

    def test_unsealed_capture_never_restarts_and_unknown_handoff_is_not_replayed(self):
        prior, preserved, raw, readback, action = self.normal_fixture()
        handoff = mock.Mock(return_value=action)
        with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()):
            with self.assertRaisesRegex(executor.Item33ExecutionError, "normal_capture_unverified"):
                executor.execute_item33_normal_handoff(dependencies=self.dependencies(), previous_result=prior,
                    preserved=preserved, capture_seal_raw=raw, capture_journal=b"synthetic journal", teardown_raw=b"synthetic teardown",
                    handoff_unit=handoff, read_normal=lambda: readback, clock=lambda: self.now)
        handoff.assert_not_called()
        handoff.side_effect = RuntimeError("synthetic unknown")
        with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
            executor, "_validate_capture_seal", return_value={}), mock.patch.object(executor, "_validate_teardown", return_value={}):
            with self.assertRaisesRegex(executor.Item33ExecutionError, "normal_handoff_outcome_unknown"):
                executor.execute_item33_normal_handoff(dependencies=self.dependencies(), previous_result=prior,
                    preserved=preserved, capture_seal_raw=raw, capture_journal=b"synthetic journal", teardown_raw=b"synthetic teardown",
                    handoff_unit=handoff, read_normal=lambda: readback, clock=lambda: self.now)
        handoff.assert_called_once()

    def test_normal_readback_cannot_hide_extra_request_or_changed_snapshot(self):
        for mutation in ("request", "snapshot"):
            prior, preserved, raw, readback, action = self.normal_fixture()
            readback = copy.deepcopy(readback)
            if mutation == "request": readback["same_bucket"]["provider_call_delta"] = 1
            else: readback["preserved"]["snapshot_sha256"] = "f" * 64
            with self.subTest(mutation=mutation), mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
                executor, "_validate_capture_seal", return_value={}), mock.patch.object(executor, "_validate_teardown", return_value={}):
                with self.assertRaisesRegex(executor.Item33ExecutionError, "normal_readback"):
                    executor.execute_item33_normal_handoff(dependencies=self.dependencies(), previous_result=prior,
                        preserved=preserved, capture_seal_raw=raw, capture_journal=b"synthetic journal", teardown_raw=b"synthetic teardown",
                        handoff_unit=lambda _: action, read_normal=lambda: readback, clock=lambda: self.now)

    @unittest.skipUnless(os.geteuid() == 0, "isolated root metadata fixture")
    def test_normal_host_cas_restart_once_and_midnight_stops_before_restart(self):
        for cross_midnight in (False, True):
            with self.subTest(cross_midnight=cross_midnight), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                unit = root / executor.UNIT_NAME
                original = Item33HostActionPreparationTests().suspended()
                unit.write_bytes(executor.render_managed_unit(original, runtime_profile=executor.V5_PROFILE))
                unit.chmod(0o644)
                action_root = root / "actions"
                action_root.mkdir(mode=0o700)
                for name, value in {
                    "promotion.started.json": {"activation_identity_sha256": self.activation, "bucket_key": self.now.date().isoformat()},
                    "reapply.applied.json": {"activation_identity_sha256": self.activation, "status": "APPLIED_REQUIRES_STATE_READBACK"},
                }.items():
                    path = action_root / name
                    path.write_bytes(executor._normal_json_bytes(value)); path.chmod(0o600)
                (action_root / "suspended-unit.rollback").write_bytes(original)
                (action_root / "suspended-unit.rollback").chmod(0o600)
                commands, now = [], [self.now]
                def run(argv):
                    commands.append(argv)
                    if "FragmentPath" in argv: return str(unit).encode()
                    if cross_midnight and argv == ["systemctl", "daemon-reload"]: now[0] = self.now + timedelta(days=1)
                    return b""
                binding = self.capture()
                auth = {"unit_name": executor.UNIT_NAME, "activation_identity_sha256": self.activation,
                    "run_identity_sha256": RUN_IDENTITY, "bucket_key": self.now.date().isoformat(),
                    "capture_binding": binding, "capture_receipt_sha256": "f" * 64, "teardown_sha256": "e" * 64, "automatic_retry_limit": 0}
                with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
                    actions := host_actions, "UNIT_PATH", unit), mock.patch.object(actions, "ACTION_ROOT", action_root), mock.patch.object(
                    actions, "_run", side_effect=run), mock.patch.object(actions, "_assert_host_identity"):
                    host = actions.Item33HostUnitActions(dependencies=self.dependencies(), capture_binding=binding, clock=lambda: now[0])
                    with mock.patch.object(host, "_assert_overlays"), mock.patch.object(host, "_assert_normal_capture"):
                        if cross_midnight:
                            with self.assertRaisesRegex(executor.Item33ExecutionError, "start_bucket_expired"): host.normal_handoff_once(auth)
                        else:
                            host.normal_handoff_once(auth)
                            with self.assertRaises(executor.Item33ExecutionError): host.normal_handoff_once(auth)
                    self.assertTrue((action_root / "normal_handoff.started.json").exists())
                    self.assertEqual((action_root / "normal_handoff.applied.json").exists(), not cross_midnight)
                    self.assertEqual(commands.count(["systemctl", "restart", executor.UNIT_NAME]), 0 if cross_midnight else 1)
                    self.assertFalse(any("enable" in command for command in commands))
                    self.assertEqual(hashlib.sha256(unit.read_bytes()).hexdigest(), executor.V5_NORMAL_UNIT_SHA256)

    @unittest.skipUnless(os.geteuid() == 0, "isolated root metadata fixture")
    def test_v5_host_actions_keep_activation_and_exact_original_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unit = root / executor.UNIT_NAME
            original = Item33HostActionPreparationTests().suspended()
            unit.write_bytes(original)
            unit.chmod(0o644)
            commands = []
            def run(argv):
                commands.append(argv)
                if "FragmentPath" in argv: return str(unit).encode()
                return b""
            binding = self.capture()
            promotion = {"unit_name": executor.UNIT_NAME, "activation_identity_sha256": self.activation,
                "automatic_retry_limit": 0, "capture_binding": binding,
                "cycle_authorization": {"activation_identity_sha256": self.activation,
                    "bucket_key": self.now.date().isoformat(), "provider_request_limit": 34,
                    "automatic_retry_limit": 0, "runtime_profile": executor.V5_PROFILE,
                    "initialization_limit": 2, "physical_http_limit": 36, "capture_binding": binding}}
            recovery = {key: value for key, value in promotion.items() if key != "cycle_authorization"}
            with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
                host_actions, "UNIT_PATH", unit), mock.patch.object(host_actions, "ACTION_ROOT", root / "actions"), mock.patch.object(
                host_actions, "_run", side_effect=run), mock.patch.object(host_actions, "_assert_host_identity"):
                actions = host_actions.Item33HostUnitActions(dependencies=self.dependencies(), capture_binding=binding, clock=lambda: self.now)
                with mock.patch.object(actions, "_assert_overlays") as overlays, mock.patch.object(actions, "_assert_capture") as capture:
                    actions.promote_unit(promotion)
                    self.assertEqual(hashlib.sha256(unit.read_bytes()).hexdigest(), executor.V5_PROMOTED_UNIT_SHA256)
                    actions.rollback_unit(recovery)
                    self.assertEqual(unit.read_bytes(), original)
                    actions.reapply_unit(recovery)
                    self.assertEqual(hashlib.sha256(unit.read_bytes()).hexdigest(), executor.V5_PROMOTED_UNIT_SHA256)
                    self.assertEqual(overlays.call_count, 2)
                    self.assertEqual(capture.call_args_list, [mock.call(promotion), mock.call(recovery)])
                    with self.assertRaises(executor.Item33ExecutionError): actions.reapply_unit(recovery)
                marker = json.loads((root / "actions/promotion.started.json").read_text())
                self.assertEqual(marker["activation_identity_sha256"], self.activation)
                self.assertNotIn("run_identity_sha256", marker)
                self.assertEqual((root / "actions/suspended-unit.rollback").read_bytes(), original)
                self.assertEqual(commands.count(["systemctl", "enable", "--now", executor.UNIT_NAME]), 2)
                self.assertEqual(commands.count(["systemctl", "disable", "--now", executor.UNIT_NAME]), 1)

    @unittest.skipUnless(os.geteuid() == 0, "isolated root metadata fixture")
    def test_v5_nested_source_and_capture_metadata_reject_symlink_or_changed_files(self):
        import socket
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay = root / "runtime"
            overlay.mkdir(mode=0o700)
            capture_root = root / "capture"
            capture_root.mkdir(mode=0o700)
            binding = self.capture()
            config = {
                "schema": "noteai.item33.runtime_capture_config.v1", "bucket_key": self.now.date().isoformat(),
                "activation_identity_sha256": self.activation, "socket_path": "/run/noteai-item33/capture.sock",
                "accepted_source_sha256": executor.V5_RUNTIME_OVERLAY_SHA256,
                "instrumentation_sha256": {**binding["source_sha256"], executor.V5_CAPTURE_LAUNCHER_PATH: binding["launcher_sha256"]},
            }
            raw = json.dumps(config).encode()
            (capture_root / "runtime-config.json").write_bytes(raw)
            (capture_root / "runtime-config.json").chmod(0o444)
            binding["configuration_sha256"] = hashlib.sha256(raw).hexdigest()
            for name in [*executor.V5_RUNTIME_OVERLAY_SHA256, *executor.V5_CAPTURE_TOOLS, executor.V5_CAPTURE_LAUNCHER_PATH]:
                path = overlay / name
                path.parent.mkdir(parents=True, exist_ok=True)
                parent = path.parent
                while parent != overlay:
                    parent.chmod(0o700)
                    parent = parent.parent
                if name in executor.V5_RUNTIME_OVERLAY_SHA256:
                    content = (ROOT / name).read_bytes()
                elif name == executor.V5_CAPTURE_LAUNCHER_PATH:
                    content = executor.V5_CAPTURE_LAUNCHER
                else:
                    content = b"# isolated source fixture\n"
                    binding["source_sha256"][name] = hashlib.sha256(content).hexdigest()
                path.write_bytes(content)
                path.chmod(0o555 if name == executor.V5_CAPTURE_LAUNCHER_PATH else 0o444)
            config["instrumentation_sha256"] = {**binding["source_sha256"], executor.V5_CAPTURE_LAUNCHER_PATH: binding["launcher_sha256"]}
            raw = json.dumps(config).encode()
            (capture_root / "runtime-config.json").write_bytes(raw)
            binding["configuration_sha256"] = hashlib.sha256(raw).hexdigest()
            connection = socket.socket(socket.AF_UNIX)
            connection.bind(str(capture_root / "capture.sock"))
            os.chown(capture_root / "capture.sock", 999, 999)
            (capture_root / "capture.sock").chmod(0o600)
            try:
                with mock.patch.object(executor, "_load_verified_dependencies", return_value=self.dependencies()), mock.patch.object(
                    executor, "V5_RUNTIME_OVERLAY_ROOT", overlay), mock.patch.object(executor, "V5_CAPTURE_ROOT", capture_root):
                    actions = host_actions.Item33HostUnitActions(dependencies=self.dependencies(), capture_binding=binding, clock=lambda: self.now)
                    actions._assert_overlays()
                    actions._assert_capture({"capture_binding": binding})
                    bridge = overlay / "model/vendor/spider_xhs/v5/trends_bridge.js"
                    backup = bridge.read_bytes()
                    bridge.unlink()
                    bridge.symlink_to(ROOT / "model/vendor/spider_xhs/v5/trends_bridge.js")
                    with self.assertRaises(OSError): actions._assert_overlays()
                    bridge.unlink()
                    bridge.write_bytes(backup + b"\n")
                    bridge.chmod(0o444)
                    with self.assertRaisesRegex(executor.Item33ExecutionError, "runtime_overlay_binding"):
                        actions._assert_overlays()
                    (capture_root / "capture.sock").chmod(0o666)
                    with self.assertRaisesRegex(executor.Item33ExecutionError, "capture_socket"):
                        actions._assert_capture({"capture_binding": binding})
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.environ.get('NOTEAI_ITEM33_DEPENDENCY_RECEIPT'), 'explicit frozen local validation receipt fixture')
class Item33SourcePackageDependencyTests(unittest.TestCase):
    def test_actual_dependencies_validate_without_git_or_unrelated_manifest_evidence(self):
        import internal_deployment_readiness_gate as gate
        refs=set()
        original_bytes,original_text=Path.read_bytes,Path.read_text
        def track_bytes(path):
            if path.is_relative_to(ROOT): refs.add(path.relative_to(ROOT))
            return original_bytes(path)
        def track_text(path,*args,**kwargs):
            if path.is_relative_to(ROOT): refs.add(path.relative_to(ROOT))
            return original_text(path,*args,**kwargs)
        manifest=gate.load_manifest(ROOT/executor.CANONICAL_MANIFEST_REF)
        control=next(c for layer in manifest['layers'] for c in layer['controls'] if c['id']=='real_xhs_trends')
        with mock.patch.object(Path,'read_bytes',track_bytes),mock.patch.object(Path,'read_text',track_text):
            self.assertEqual(gate.validate_item32_trends_evidence(control,root=ROOT),[])
        receipt=Path(os.environ['NOTEAI_ITEM33_DEPENDENCY_RECEIPT']).read_bytes()
        self.assertEqual(hashlib.sha256(receipt).hexdigest(),executor.DEPENDENCY_VALIDATION_SHA256)
        validation=json.loads(receipt)
        refs.update(map(Path,(executor.CANONICAL_MANIFEST_REF,validation['evidence_ref'],validation['validator_ref'])))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for ref in refs:
                path=root/ref;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/ref).read_bytes())
            proof=root/executor.DEPENDENCY_VALIDATION_REF;proof.write_bytes(receipt)
            self.assertFalse((root/'.git').exists())
            with mock.patch.object(executor,'ROOT',root),mock.patch.object(gate,'validate_manifest',side_effect=AssertionError('full manifest forbidden')),mock.patch('subprocess.run',side_effect=AssertionError('git/commands forbidden')):
                valid=executor._load_verified_dependencies()
                self.assertEqual(valid['real_xhs_trends']['runtime_profile'],executor.V5_PROFILE)
                self.assertTrue(valid['internal_failure_rollback']['verified'])
                for ref in (executor.DEPENDENCY_VALIDATION_REF,validation['evidence_ref'],validation['validator_ref'],'deploy/production/evidence/production-item32-xhs-trends-attempt-audit.json'):
                    path=root/ref;original=path.read_bytes();path.write_bytes(original+b' ')
                    with self.subTest(ref=ref),self.assertRaisesRegex(executor.Item33ExecutionError,'dependency_unverified'):executor._load_verified_dependencies()
                    path.write_bytes(original)
