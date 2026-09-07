import copy
import sys
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


if __name__ == "__main__":
    unittest.main()
