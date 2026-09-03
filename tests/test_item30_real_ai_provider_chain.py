import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_SOURCE = ROOT / "deploy" / "production" / "real_ai_provider_chain.py"
FACT_SOURCE = ROOT / "model" / "fact_enrichment.py"
EXECUTOR_SPEC = importlib.util.spec_from_file_location(
    "real_ai_provider_chain", EXECUTOR_SOURCE
)
executor = importlib.util.module_from_spec(EXECUTOR_SPEC)
assert EXECUTOR_SPEC.loader is not None
sys.modules[EXECUTOR_SPEC.name] = executor
EXECUTOR_SPEC.loader.exec_module(executor)

sys.path.insert(0, str(ROOT / "tools"))
import verify_real_ai_provider_chain_evidence as verifier  # noqa: E402


PRE_TIME = "2026-08-24T12:55:00Z"
GATE_TIME = "2026-08-24T13:00:00Z"
START_TIME = "2026-08-24T13:02:00Z"
RESULT_TIME = "2026-08-24T13:03:00Z"
FINISH_TIME = "2026-08-24T13:06:00Z"
POST_TIME = "2026-08-24T13:07:00Z"
SETTLEMENT_TIME = "2026-08-24T13:08:00Z"
EVIDENCE_TIME = "2026-08-24T13:09:00Z"
EXPIRES_TIME = "2026-08-24T13:30:00Z"


def digest(value):
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def account_gate_document(revision=None):
    revision = revision or subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    counter_kinds = {
        "claude": ("request_count", "requests", "100.000000"),
        "kimi": ("total_tokens", "tokens", "1000.000000"),
        "amap": ("request_count", "requests", "200.000000"),
    }
    caps = {
        "claude": "0.100000",
        "kimi": "0.100000",
        "amap": "0.100000",
    }
    providers = {}
    for name in executor.PROVIDER_ORDER:
        if name == "meituan":
            disclosure_sha = digest("meituan-token-metadata-pre")
            providers[name] = {
                "account_identity_sha256": digest("meituan-account"),
                "credential_name_present": True,
                "balance_or_quota_confirmed": False,
                "current_price_confirmed": False,
                "pre_call_counter_readable": False,
                "pre_call_counter": {
                    "observed_at_utc": PRE_TIME,
                    "counter_kind": executor.NOT_EXPOSED_BY_PROVIDER,
                    "counter_unit": executor.NOT_EXPOSED_BY_PROVIDER,
                    "direction": executor.NOT_EXPOSED_BY_PROVIDER,
                    "counter_value": executor.NOT_EXPOSED_BY_PROVIDER,
                    "snapshot_sha256": disclosure_sha,
                    "source": "provider_account_console",
                },
                "price_snapshot_sha256": disclosure_sha,
                "unit_cost_upper_bound_rmb": executor.NOT_EXPOSED_BY_PROVIDER,
            }
            continue
        kind, unit, value = counter_kinds[name]
        providers[name] = {
            "account_identity_sha256": digest(f"{name}-account"),
            "credential_name_present": True,
            "balance_or_quota_confirmed": True,
            "current_price_confirmed": True,
            "pre_call_counter_readable": True,
            "pre_call_counter": {
                "observed_at_utc": PRE_TIME,
                "counter_kind": kind,
                "counter_unit": unit,
                "direction": "increasing",
                "counter_value": value,
                "snapshot_sha256": digest(f"{name}-pre"),
                "source": "provider_account_console",
            },
            "price_snapshot_sha256": digest(f"{name}-price"),
            "unit_cost_upper_bound_rmb": caps[name],
        }
    return {
        "schema": executor.ACCOUNT_GATE_SCHEMA,
        "generated_at_utc": GATE_TIME,
        "expires_at_utc": EXPIRES_TIME,
        "execution_nonce": digest("item30-execution-nonce"),
        "execution_source_revision": revision,
        "executor_sha256": digest(EXECUTOR_SOURCE.read_bytes()),
        "fact_enrichment_sha256": digest(FACT_SOURCE.read_bytes()),
        "providers": providers,
    }


class FakeBackend:
    def __init__(self):
        self.calls = []

    def preflight(self):
        self.calls.append("preflight")
        return {
            "claude_transport": "gateway",
            "claude_remote_ready": True,
            "kimi_credential_present": True,
            "amap_credential_present": True,
            "meituan_runtime_status": "MEITUAN_TRAVEL_READY",
        }

    def claude(self):
        self.calls.append("claude")
        return {
            "output_bytes": len(verifier.SENTINEL),
            "output_sha256": digest(verifier.SENTINEL),
            "input_tokens": 20,
            "output_tokens": 5,
            "model_calls": 1,
            "provider": "claude",
            "model": executor.CLAUDE_MODEL,
            "pricing_status": "exact",
            "usage_status": "complete",
            "cost_mode": "actual",
            "actual_cost_rmb": "0.001000",
            "transport": "production_gateway",
        }

    def kimi(self):
        self.calls.append("kimi")
        return {
            "output_bytes": len(verifier.SENTINEL),
            "output_sha256": digest(verifier.SENTINEL),
            "input_tokens": 18,
            "output_tokens": 5,
            "model_calls": 1,
            "provider": "kimi",
            "model": executor.KIMI_MODEL,
            "pricing_status": "exact",
            "usage_status": "complete",
            "cost_mode": "actual",
            "actual_cost_rmb": "0.001000",
            "transport": "model_router_kimi",
        }

    def amap(self):
        self.calls.append("amap")
        return {
            "output_bytes": 40,
            "output_sha256": digest("amap"),
            "structured_fact_count": 2,
            "source_count": 1,
            "confidence_milli": 630,
            "target_entity_matched": True,
            "target_region_matched": True,
            "http_request_count": 1,
            "detail_request_count": 0,
            "transport": "fact_enrichment_amap_text_only",
        }

    def meituan(self):
        self.calls.append("meituan")
        return {
            "output_bytes": 40,
            "output_sha256": digest("meituan"),
            "structured_fact_count": 2,
            "source_count": 1,
            "confidence_milli": 630,
            "target_entity_matched": True,
            "target_region_matched": True,
            "cli_invocation_count": 1,
            "transport": "fact_enrichment_meituan_travel",
        }

    def close(self):
        self.calls.append("close")


def raw_executor_result():
    gates = account_gate_document()
    backend = FakeBackend()
    result = executor.execute_probe(
        backend,
        gates,
        clock=lambda: RESULT_TIME,
    )
    result["cleanup"] = {
        "ephemeral_database_residue_count": 0,
        "credential_file_persisted_by_executor_count": 0,
    }
    result["attempt"] = {
        "schema": executor.JOURNAL_SCHEMA,
        "execution_nonce": gates["execution_nonce"],
        "execution_source_revision": gates["execution_source_revision"],
        "account_gate_sha256": digest(executor._canonical(gates)),
        "executor_sha256": gates["executor_sha256"],
        "fact_enrichment_sha256": gates["fact_enrichment_sha256"],
        "status": "PASS",
        "providers": {name: "SUCCESS" for name in executor.PROVIDER_ORDER},
    }
    return result


def evidence_fixture():
    raw = raw_executor_result()
    gate_providers = raw["account_gate"]["providers"]
    post_values = {
        "claude": "101.000000",
        "kimi": "1023.000000",
        "amap": "201.000000",
    }
    deltas = {
        "claude": "1.000000",
        "kimi": "23.000000",
        "amap": "1.000000",
    }
    costs = {
        "claude": "0.001000",
        "kimi": "0.001000",
        "amap": "0.003000",
    }
    native = {}
    for name in executor.PROVIDER_ORDER:
        gate = gate_providers[name]
        if name == "meituan":
            post_snapshot = digest("meituan-token-metadata-post")
            native[name] = {
                "account_identity_sha256": gate["account_identity_sha256"],
                "custody": "protected_off_repo",
                "pre": {
                    **copy.deepcopy(gate["pre_call_counter"]),
                    "quota_or_balance_sufficient": executor.NOT_EXPOSED_BY_PROVIDER,
                    "current_unit_cap_rmb": executor.NOT_EXPOSED_BY_PROVIDER,
                    "price_snapshot_sha256": gate["price_snapshot_sha256"],
                },
                "post": {
                    **copy.deepcopy(gate["pre_call_counter"]),
                    "observed_at_utc": POST_TIME,
                    "snapshot_sha256": post_snapshot,
                },
                "usage_delta": executor.NOT_EXPOSED_BY_PROVIDER,
                "native_event_id_sha256": None,
                "settlement": {
                    "observed_at_utc": SETTLEMENT_TIME,
                    "status": executor.NOT_EXPOSED_BY_PROVIDER,
                    "currency": executor.NOT_EXPOSED_BY_PROVIDER,
                    "incremental_cost_rmb": executor.NOT_EXPOSED_BY_PROVIDER,
                    "reconciliation_tolerance_rmb": executor.NOT_EXPOSED_BY_PROVIDER,
                    "snapshot_sha256": post_snapshot,
                },
            }
            continue
        pre = {
            **copy.deepcopy(gate["pre_call_counter"]),
            "quota_or_balance_sufficient": True,
            "current_unit_cap_rmb": gate["unit_cost_upper_bound_rmb"],
            "price_snapshot_sha256": gate["price_snapshot_sha256"],
        }
        post = {
            **copy.deepcopy(gate["pre_call_counter"]),
            "observed_at_utc": POST_TIME,
            "counter_value": post_values[name],
            "snapshot_sha256": digest(f"{name}-post"),
        }
        native[name] = {
            "account_identity_sha256": gate["account_identity_sha256"],
            "custody": "protected_off_repo",
            "pre": pre,
            "post": post,
            "usage_delta": deltas[name],
            "native_event_id_sha256": digest(f"{name}-event"),
            "settlement": {
                "observed_at_utc": SETTLEMENT_TIME,
                "status": "RECONCILED",
                "currency": "RMB",
                "incremental_cost_rmb": costs[name],
                "reconciliation_tolerance_rmb": "0.010000",
                "snapshot_sha256": digest(f"{name}-settlement"),
            },
        }
    raw_sha = digest(verifier._canonical(raw))
    value = {
        "schema": verifier.EVIDENCE_SCHEMA,
        "task_id": verifier.TASK_ID,
        "status": "PASS",
        "observed_at_utc": EVIDENCE_TIME,
        "source_binding": {
            "branch": verifier.SOURCE_BRANCH,
            "execution_source_revision": raw["account_gate"]["execution_source_revision"],
            "executor_ref": verifier.EXECUTOR_REF,
            "executor_sha256": raw["account_gate"]["executor_sha256"],
            "fact_enrichment_ref": verifier.FACT_ENRICHMENT_REF,
            "fact_enrichment_sha256": raw["account_gate"]["fact_enrichment_sha256"],
            "runtime_executor_sha256": raw["account_gate"]["executor_sha256"],
            "runtime_fact_enrichment_sha256": raw["account_gate"]["fact_enrichment_sha256"],
            "application_release_revision": verifier.APPLICATION_RELEASE_REVISION,
            "application_manifest_sha256": verifier.APPLICATION_MANIFEST_SHA256,
            "application_config_sha256": verifier.APPLICATION_CONFIG_SHA256,
            "application_executor_readonly_overlay": True,
            "application_fact_enrichment_readonly_overlay": True,
            "gateway_service": "noteai-prod-claude-gateway",
            "gateway_release_revision": verifier.GATEWAY_RELEASE_REVISION,
            "gateway_region": "Singapore (Southeast Asia)",
            "gateway_health_path": "/health/ready",
            "gateway_health_http_status": 200,
        },
        "execution": {
            "command_name": verifier.COMMAND_NAME,
            "command_identity_sha256": digest("cloud-command"),
            "invocation_identity_sha256": digest("cloud-invocation"),
            "terminal_status": "Success",
            "exit_code": 0,
            "repeat_count": 1,
            "dropped_count": 0,
            "started_at_utc": START_TIME,
            "finished_at_utc": FINISH_TIME,
            "stdout_sha256": digest(
                verifier._canonical(
                    {"executor_result_sha256": raw_sha, "status": "PASS"}
                )
            ),
            "executor_result_sha256": raw_sha,
            "executor_result": raw,
        },
        "provider_native_bindings": native,
        "cost_and_settlement": {
            "currency": "RMB",
            "incremental_provider_cost_rmb": executor.NOT_EXPOSED_BY_PROVIDER,
            "application_model_cost_rmb": "0.002000",
            "incremental_cloud_compute_cost_rmb": "0.000000",
            "gateway_control_plane_cost_mode": (
                "existing_fin_003_budget_no_per_call_settlement"
            ),
            "total_incremental_cost_rmb": executor.NOT_EXPOSED_BY_PROVIDER,
            "hard_cap_rmb": executor.MEITUAN_COST_OVERRIDE,
            "within_cap": executor.NOT_DETERMINABLE,
            "provider_settlement_complete_count": 3,
        },
        "production_boundary": {
            "synthetic_ai_prompt_only": True,
            "public_fact_query_only": True,
            "provider_dispatch_count": 4,
            "user_content_count": 0,
            "response_content_persisted_count": 0,
            "response_url_persisted_count": 0,
            "noteai_business_database_connection_count": 0,
            "noteai_business_database_write_count": 0,
            "gateway_control_plane_request_expected": True,
            "gateway_terminal_record_ttl_days": 30,
            "gateway_control_plane_new_resource_count": 0,
            "production_service_restart_count": 0,
            "production_payment_mutation_count": 0,
            "production_dns_mutation_count": 0,
            "render_deploy_count": 0,
            "postpaid_instance_start_count": 0,
        },
        "resources": {
            "api_c": {"status": "Running", "charge_type": "PrePaid"},
            "api_f": {"status": "Running", "charge_type": "PrePaid"},
            "builder": {
                "status": "Stopped",
                "billing_state": "StopCharging",
                "charge_type": "PostPaid",
            },
            "worker_c": {
                "status": "Stopped",
                "billing_state": "StopCharging",
                "charge_type": "PostPaid",
            },
            "worker_f": {
                "status": "Stopped",
                "billing_state": "StopCharging",
                "charge_type": "PostPaid",
            },
            "temporary_compute_count": 0,
            "temporary_listener_count": 0,
            "temporary_security_group_count": 0,
            "temporary_peering_count": 0,
            "temporary_route_count": 0,
            "result_mount_type": "bind",
            "readonly_source_bind_count": 3,
            "temporary_docker_volume_count": 0,
        },
        "cleanup": {
            "task_container_residue_count": 0,
            "task_file_residue_count": 0,
            "credential_residue_count": 0,
            "ephemeral_database_residue_count": 0,
            "operation_lock_count": 0,
            "task_volume_residue_count": 0,
            "api_container_identity_unchanged": True,
            "api_container_restart_count": 0,
            "api_live_http_status": 200,
            "api_ready_http_status": 200,
        },
        "readiness": copy.deepcopy(verifier.DEFAULT_READINESS),
        "terminal_acceptance_sha256": "",
    }
    value["terminal_acceptance_sha256"] = verifier.terminal_acceptance_sha256(value)
    return value


def rebind_raw(value):
    raw = value["execution"]["executor_result"]
    raw["attempt"]["account_gate_sha256"] = digest(
        executor._canonical(raw["account_gate"])
    )
    raw_sha = digest(verifier._canonical(raw))
    value["execution"]["executor_result_sha256"] = raw_sha
    value["execution"]["stdout_sha256"] = digest(
        verifier._canonical({"executor_result_sha256": raw_sha, "status": "PASS"})
    )
    value["terminal_acceptance_sha256"] = verifier.terminal_acceptance_sha256(value)


class Item30ExecutorTests(unittest.TestCase):
    def test_runtime_source_binding_includes_exact_model_router(self):
        gates = account_gate_document()
        router_source = (ROOT / "model" / "model_router.py").read_bytes()
        self.assertEqual(digest(router_source), executor.MODEL_ROUTER_SHA256)
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir)
            (model_path / "fact_enrichment.py").write_bytes(FACT_SOURCE.read_bytes())
            router = model_path / "model_router.py"
            router.write_bytes(router_source)
            with mock.patch.object(executor, "_model_path", return_value=model_path):
                executor._runtime_source_binding(gates)
                router.write_bytes(router_source + b"\n")
                with self.assertRaisesRegex(
                    executor.ProbeError, "RUNTIME_SOURCE_BINDING_MISMATCH"
                ):
                    executor._runtime_source_binding(gates)

    def test_success_calls_each_provider_once_without_retry_or_fallback(self):
        backend = FakeBackend()
        result = executor.execute_probe(
            backend,
            account_gate_document(),
            clock=lambda: RESULT_TIME,
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            backend.calls,
            ["preflight", "meituan", "claude", "kimi", "amap", "close"],
        )
        self.assertEqual(result["totals"]["dispatch_count"], 4)
        self.assertEqual(result["totals"]["automatic_retry_count"], 0)
        self.assertEqual(result["totals"]["fallback_count"], 0)
        self.assertEqual(result["totals"]["unknown_count"], 0)
        self.assertEqual(result["data_boundary"]["noteai_business_database_write_count"], 0)
        self.assertNotIn("failure_code", result)

    def test_provider_failures_preserve_only_allowlisted_fixed_codes(self):
        for code in (
            "CLAUDE_OUTPUT_INVALID", "MODEL_USAGE_MISSING", "MODEL_USAGE_NOT_ACTUAL"
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp_dir:
                gates = account_gate_document()
                journal_path = Path(temp_dir) / "executor-result.json"
                journal = executor.AttemptJournal.create(journal_path, gates)
                backend = FakeBackend()
                backend.claude = mock.Mock(side_effect=executor.ProbeError(code))
                result = executor.execute_probe(
                    backend, gates, clock=lambda: RESULT_TIME, journal=journal
                )

                self.assertEqual(result["failure_code"], code)
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertEqual(tuple(result["providers"]), ("meituan", "claude"))
                self.assertEqual(result["providers"]["claude"]["dispatch_count"], 1)
                self.assertEqual(result["totals"]["automatic_retry_count"], 0)
                self.assertEqual(result["totals"]["fallback_count"], 0)
                self.assertEqual(journal.value["status"], "UNKNOWN")
                self.assertEqual(
                    journal.value["providers"],
                    {"meituan": "SUCCESS", "claude": "UNKNOWN"},
                )
                with self.assertRaisesRegex(
                    executor.ProbeError, "EXECUTION_ALREADY_ATTEMPTED"
                ):
                    executor.AttemptJournal.create(journal_path, gates)

    def test_provider_failure_details_and_arbitrary_codes_never_escape(self):
        misleading = RuntimeError("PRIVATE_PROVIDER_BODY")
        misleading.code = "CLAUDE_OUTPUT_INVALID"
        for error in (
            executor.ProbeError("PRIVATE_PROVIDER_BODY"),
            RuntimeError("PRIVATE_PROVIDER_BODY"),
            misleading,
        ):
            with self.subTest(error_type=type(error).__name__):
                backend = FakeBackend()
                backend.claude = mock.Mock(side_effect=error)
                result = executor.execute_probe(
                    backend, account_gate_document(), clock=lambda: RESULT_TIME
                )
                self.assertEqual(result["failure_code"], "RUNTIME_INTERNAL_ERROR")
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertNotIn("PRIVATE_PROVIDER_BODY", json.dumps(result))
                self.assertNotIn("kimi", result["providers"])
                self.assertNotIn("amap", result["providers"])

    def test_model_usage_keeps_all_six_predicates_and_failure_values(self):
        backend = object.__new__(executor.ProductionProbeBackend)
        row = {
            "tokens_in": 26, "tokens_out": 6, "model_calls": 1,
            "provider": "kimi", "model": executor.KIMI_MODEL,
            "pricing_status": "exact", "usage_status": "complete",
            "cost_mode": "actual", "actual_model_cost_rmb": "0.000331",
            "known_cost_rmb": "0.000331",
        }
        backend.db = mock.Mock()
        backend.db.fetchone.return_value = row
        expected = {
            "input_tokens": 26, "output_tokens": 6, "model_calls": 1,
            "pricing_status": "exact", "usage_status": "complete",
            "cost_mode": "actual",
        }
        self.assertEqual(
            backend._model_usage("synthetic-user", "kimi"),
            {
                **expected, "provider": "kimi", "model": executor.KIMI_MODEL,
                "actual_cost_rmb": "0.000331",
            },
        )
        cases = (
            ("tokens_in", "input_tokens", 0),
            ("tokens_out", "output_tokens", 0),
            ("model_calls", "model_calls", 0),
            ("model_calls", "model_calls", 2),
            ("pricing_status", "pricing_status", "unpriced"),
            ("usage_status", "usage_status", "cache_usage_missing"),
            ("cost_mode", "cost_mode", "usage_incomplete"),
        )
        for source_key, summary_key, value in cases:
            with self.subTest(field=source_key, value=value):
                backend.db.fetchone.return_value = {**row, source_key: value}
                with self.assertRaises(executor.ProbeError) as caught:
                    backend._model_usage("synthetic-user", "kimi")
                error = caught.exception
                self.assertEqual(error.code, "MODEL_USAGE_NOT_ACTUAL")
                self.assertEqual(error.args, ("MODEL_USAGE_NOT_ACTUAL",))
                self.assertEqual(error.usage_summary, {**expected, summary_key: value})

        for missing_row in (None, {**row, "provider": "claude"}):
            with self.subTest(missing_row=missing_row):
                backend.db.fetchone.return_value = missing_row
                with self.assertRaises(executor.ProbeError) as caught:
                    backend._model_usage("synthetic-user", "kimi")
                self.assertEqual(caught.exception.code, "MODEL_USAGE_MISSING")
                self.assertEqual(caught.exception.usage_summary, {})

    def test_usage_failure_summary_preserves_unknown_cost_and_no_replay(self):
        summary = {
            "input_tokens": 26, "output_tokens": 6, "model_calls": 1,
            "pricing_status": "exact", "usage_status": "cache_usage_missing",
            "cost_mode": "usage_incomplete",
        }
        for provider in ("claude", "kimi"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp_dir:
                native = object.__new__(executor.ProductionProbeBackend)
                native._create_usage = mock.Mock(return_value="synthetic-user")
                native.model_router = types.SimpleNamespace(
                    call_claude_sync=mock.Mock(return_value="NOTEAI_OK"),
                    _call_kimi=mock.AsyncMock(return_value="NOTEAI_OK"),
                )
                native.db = mock.Mock()
                native.db.fetchone.return_value = {
                    "tokens_in": 26, "tokens_out": 6, "model_calls": 1,
                    "provider": provider,
                    "model": executor.CLAUDE_MODEL if provider == "claude" else executor.KIMI_MODEL,
                    "pricing_status": "exact", "usage_status": "cache_usage_missing",
                    "cost_mode": "usage_incomplete",
                    "actual_model_cost_rmb": "0.000162", "known_cost_rmb": "0.000162",
                }
                backend = FakeBackend()
                setattr(backend, provider, getattr(native, provider))
                gates = account_gate_document()
                journal_path = Path(temp_dir) / "executor-result.json"
                journal = executor.AttemptJournal.create(journal_path, gates)
                result = executor.execute_probe(
                    backend, gates, clock=lambda: RESULT_TIME, journal=journal
                )
                failed = result["providers"][provider]
                self.assertEqual({key: failed[key] for key in summary}, summary)
                self.assertEqual(
                    set(failed), set(summary) | {
                        "status", "dispatch_count", "automatic_retry_count",
                        "fallback_count", "unknown_count", "elapsed_millis",
                    },
                )
                self.assertTrue(set(summary) <= executor.SAFE_PROVIDER_RESULT_KEYS[provider])
                self.assertTrue(set(summary) <= verifier.RAW_MODEL_KEYS)
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertEqual(result["failure_code"], "MODEL_USAGE_NOT_ACTUAL")
                self.assertEqual(failed["status"], "UNKNOWN")
                self.assertEqual(failed["dispatch_count"], 1)
                self.assertEqual(result["totals"]["unknown_count"], 1)
                self.assertEqual(result["totals"]["automatic_retry_count"], 0)
                self.assertEqual(result["totals"]["fallback_count"], 0)
                previous_successes = 1 if provider == "claude" else 2
                self.assertEqual(result["totals"]["successful_provider_count"], previous_successes)
                self.assertEqual(result["totals"]["dispatch_count"], previous_successes + 1)
                self.assertEqual(
                    result["totals"]["actual_model_cost_rmb"],
                    "0.000000" if provider == "claude" else "0.001000",
                )
                self.assertNotIn("amap", result["providers"])
                if provider == "claude":
                    native.model_router.call_claude_sync.assert_called_once()
                    native.model_router._call_kimi.assert_not_called()
                    self.assertNotIn("kimi", result["providers"])
                else:
                    native.model_router._call_kimi.assert_awaited_once()
                    native.model_router.call_claude_sync.assert_not_called()
                self.assertEqual(journal.value["status"], "UNKNOWN")
                self.assertEqual(journal.value["providers"][provider], "UNKNOWN")
                with self.assertRaisesRegex(executor.ProbeError, "EXECUTION_ALREADY_ATTEMPTED"):
                    executor.AttemptJournal.create(journal_path, gates)

                value = evidence_fixture()
                raw = value["execution"]["executor_result"]
                raw["status"] = "UNKNOWN"
                raw["providers"][provider].update(failed)
                rebind_raw(value)
                errors = verifier.validate_document(value, verify_git=False)
                self.assertIn("executor result terminal mismatch", errors)
                self.assertIn(f"{provider}: raw dispatch terminal mismatch", errors)

    def test_usage_failure_summary_rejects_malformed_values_and_private_fields(self):
        summary = {
            "input_tokens": 26, "output_tokens": 6, "model_calls": 1,
            "pricing_status": "exact", "usage_status": "cache_usage_missing",
            "cost_mode": "usage_incomplete",
        }
        error = executor.ProbeError(
            "MODEL_USAGE_NOT_ACTUAL",
            usage_summary={
                **summary, "raw_output": "PRIVATE_PROVIDER_BODY",
                "status": "SUCCESS", "actual_cost_rmb": "999.000000",
            },
        )
        self.assertEqual(error.usage_summary, summary)
        self.assertEqual(str(error), "MODEL_USAGE_NOT_ACTUAL")
        malformed = [None, [], "PRIVATE_PROVIDER_BODY", {}]
        for key in summary:
            malformed.append({name: value for name, value in summary.items() if name != key})
            for invalid in (None, [], {}, True, "PRIVATE_PROVIDER_BODY"):
                malformed.append({**summary, key: invalid})
        for value in malformed:
            with self.subTest(summary=value):
                error = executor.ProbeError("MODEL_USAGE_NOT_ACTUAL", usage_summary=value)
                self.assertEqual(error.usage_summary, {})
                backend = FakeBackend()
                backend.kimi = mock.Mock(side_effect=error)
                result = executor.execute_probe(
                    backend, account_gate_document(), clock=lambda: RESULT_TIME
                )
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertFalse(set(summary) & set(result["providers"]["kimi"]))
                self.assertNotIn("PRIVATE_PROVIDER_BODY", json.dumps(result))
                self.assertNotIn("amap", result["providers"])

    def test_usage_failure_summary_is_not_attached_to_other_errors_or_providers(self):
        summary = {
            "input_tokens": 26, "output_tokens": 6, "model_calls": 1,
            "pricing_status": "exact", "usage_status": "cache_usage_missing",
            "cost_mode": "usage_incomplete",
        }
        for provider, code in (
            ("kimi", "MODEL_USAGE_MISSING"),
            ("claude", "CLAUDE_OUTPUT_INVALID"),
            ("kimi", "PRIVATE_PROVIDER_BODY"),
            ("meituan", "MODEL_USAGE_NOT_ACTUAL"),
            ("amap", "MODEL_USAGE_NOT_ACTUAL"),
        ):
            with self.subTest(provider=provider, code=code):
                error = executor.ProbeError(code, usage_summary=summary)
                backend = FakeBackend()
                setattr(backend, provider, mock.Mock(side_effect=error))
                result = executor.execute_probe(
                    backend, account_gate_document(), clock=lambda: RESULT_TIME
                )
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertFalse(set(summary) & set(result["providers"][provider]))
                self.assertNotIn("PRIVATE_PROVIDER_BODY", json.dumps(result))

    def test_cleanup_failure_retains_priority_over_provider_failure_code(self):
        gates = account_gate_document()
        backend = FakeBackend()
        backend.claude = mock.Mock(
            side_effect=executor.ProbeError("CLAUDE_OUTPUT_INVALID")
        )
        artifact = mock.Mock()
        artifact.unlink.side_effect = OSError("PRIVATE_CLEANUP_DETAIL")
        artifact.exists.return_value = True
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "executor-result.json"
            output = io.StringIO()
            with mock.patch.object(executor, "_validate_state_dir"), mock.patch.object(
                executor, "_validate_sqlite_path", return_value=(artifact,)
            ), mock.patch.object(
                executor, "_validate_environment_boundary"
            ), mock.patch.object(
                executor, "load_account_gates", return_value=gates
            ), mock.patch.object(
                executor, "_runtime_source_binding"
            ), mock.patch.object(
                executor, "_utc_now", return_value=RESULT_TIME
            ), mock.patch.object(
                executor, "ProductionProbeBackend", return_value=backend
            ), mock.patch.object(
                executor, "RESULT_PATH", result_path
            ), mock.patch.object(sys, "stdout", output):
                self.assertEqual(executor.main([]), 2)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertEqual(result["failure_code"], "EPHEMERAL_DATABASE_CLEANUP_FAILED")
            self.assertEqual(result["attempt"]["status"], "UNKNOWN")
            self.assertEqual(result["cleanup"]["ephemeral_database_residue_count"], 1)
            self.assertNotIn("PRIVATE_CLEANUP_DETAIL", json.dumps(result))
            self.assertNotIn("PRIVATE_CLEANUP_DETAIL", output.getvalue())

    def test_unknown_stops_chain_and_never_replays_across_attempts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "executor-result.json"
            gates = account_gate_document()
            journal = executor.AttemptJournal.create(journal_path, gates)
            backend = FakeBackend()
            backend.kimi = mock.Mock(side_effect=RuntimeError("private provider body"))
            result = executor.execute_probe(
                backend,
                gates,
                clock=lambda: RESULT_TIME,
                journal=journal,
            )

            self.assertEqual(result["status"], "UNKNOWN")
            self.assertEqual(result["providers"]["kimi"]["unknown_count"], 1)
            self.assertNotIn("amap", result["providers"])
            self.assertNotIn("private provider body", json.dumps(result))
            second_backend = FakeBackend()
            with self.assertRaisesRegex(
                executor.ProbeError, "EXECUTION_ALREADY_ATTEMPTED"
            ):
                executor.AttemptJournal.create(journal_path, gates)
            self.assertEqual(second_backend.calls, [])

    def test_unexpected_provider_content_is_not_persisted(self):
        backend = FakeBackend()
        original = backend.claude

        def unsafe_claude():
            return {**original(), "raw_output": "SENSITIVE_PROVIDER_CONTENT"}

        backend.claude = unsafe_claude
        result = executor.execute_probe(
            backend, account_gate_document(), clock=lambda: RESULT_TIME
        )
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertNotIn("SENSITIVE_PROVIDER_CONTENT", json.dumps(result))
        self.assertNotIn("raw_output", json.dumps(result))
        self.assertNotIn("kimi", result["providers"])

    def test_account_gate_freshness_source_and_cost_caps(self):
        payload = account_gate_document()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = executor.load_account_gates(path, now_text=RESULT_TIME)
            self.assertEqual(loaded, payload)

            with self.assertRaisesRegex(executor.ProbeError, "ACCOUNT_GATES_EXPIRED"):
                executor.load_account_gates(
                    path, now_text="2026-08-24T14:00:00Z"
                )
            payload["providers"]["claude"]["unit_cost_upper_bound_rmb"] = "0.100001"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                executor.ProbeError, "PROVIDER_COST_CAP_EXCEEDED"
            ):
                executor.load_account_gates(path, now_text=RESULT_TIME)

    def test_meituan_not_exposed_gate_is_exact_and_not_reusable(self):
        canonical = account_gate_document()
        variants = []

        numeric = copy.deepcopy(canonical)
        numeric_gate = numeric["providers"]["meituan"]
        numeric_gate.update(
            {
                "balance_or_quota_confirmed": True,
                "current_price_confirmed": True,
                "pre_call_counter_readable": True,
                "unit_cost_upper_bound_rmb": "0.500000",
            }
        )
        numeric_gate["pre_call_counter"].update(
            {
                "counter_kind": "request_count",
                "counter_unit": "requests",
                "direction": "increasing",
                "counter_value": "0.000000",
            }
        )
        variants.append(numeric)

        mixed = copy.deepcopy(canonical)
        mixed["providers"]["meituan"]["unit_cost_upper_bound_rmb"] = "0.000000"
        variants.append(mixed)

        mismatched_snapshot = copy.deepcopy(canonical)
        mismatched_snapshot["providers"]["meituan"][
            "price_snapshot_sha256"
        ] = digest("different-disclosure")
        variants.append(mismatched_snapshot)

        for name in ("claude", "kimi", "amap"):
            wrong_provider = copy.deepcopy(canonical)
            wrong_provider["providers"][name] = copy.deepcopy(
                wrong_provider["providers"]["meituan"]
            )
            variants.append(wrong_provider)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gates.json"
            for payload in variants:
                with self.subTest(payload=digest(executor._canonical(payload))):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(executor.ProbeError):
                        executor.load_account_gates(path, now_text=RESULT_TIME)

    def test_meituan_numeric_gate_blocks_before_backend_and_journal(self):
        payload = account_gate_document()
        gate = payload["providers"]["meituan"]
        gate.update(
            {
                "balance_or_quota_confirmed": True,
                "current_price_confirmed": True,
                "pre_call_counter_readable": True,
                "unit_cost_upper_bound_rmb": "0.500000",
            }
        )
        gate["pre_call_counter"].update(
            {
                "counter_kind": "request_count",
                "counter_unit": "requests",
                "direction": "increasing",
                "counter_value": "0.000000",
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            backend_factory = mock.Mock()
            output = io.StringIO()
            with mock.patch.object(executor, "_validate_state_dir"), mock.patch.object(
                executor, "_validate_sqlite_path", return_value=()
            ), mock.patch.object(
                executor, "_validate_environment_boundary"
            ), mock.patch.object(
                executor, "ACCOUNT_GATES_PATH", path
            ), mock.patch.object(
                executor, "_utc_now", return_value=RESULT_TIME
            ), mock.patch.object(
                executor, "ProductionProbeBackend", backend_factory
            ), mock.patch.object(
                executor.AttemptJournal, "create"
            ) as create_journal, mock.patch.object(sys, "stdout", output):
                self.assertEqual(executor.main([]), 2)
            backend_factory.assert_not_called()
            create_journal.assert_not_called()
            self.assertIn("MEITUAN_DISCLOSURE_GATE_INVALID", output.getvalue())

    def test_meituan_unknown_stops_before_any_other_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            gates = account_gate_document()
            journal_path = Path(temp_dir) / "executor-result.json"
            journal = executor.AttemptJournal.create(journal_path, gates)
            backend = FakeBackend()

            def fail_meituan():
                backend.calls.append("meituan")
                raise RuntimeError("private provider body")

            backend.meituan = fail_meituan
            result = executor.execute_probe(
                backend, gates, clock=lambda: RESULT_TIME, journal=journal
            )

            self.assertEqual(result["status"], "UNKNOWN")
            self.assertEqual(backend.calls, ["preflight", "meituan", "close"])
            self.assertEqual(tuple(result["providers"]), ("meituan",))
            self.assertEqual(journal.value["status"], "UNKNOWN")
            self.assertEqual(journal.value["providers"], {"meituan": "UNKNOWN"})
            self.assertNotIn("private provider body", json.dumps(result))
            with self.assertRaisesRegex(
                executor.ProbeError, "EXECUTION_ALREADY_ATTEMPTED"
            ):
                executor.AttemptJournal.create(journal_path, gates)

    def test_invalid_provider_counter_blocks_before_journal_or_provider(self):
        payload = account_gate_document()
        payload["providers"]["amap"]["pre_call_counter"].update(
            {"counter_kind": "total_tokens", "counter_unit": "tokens"}
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            backend_factory = mock.Mock()
            output = io.StringIO()
            with mock.patch.object(executor, "_validate_state_dir"), mock.patch.object(
                executor, "_validate_sqlite_path", return_value=()
            ), mock.patch.object(
                executor, "_validate_environment_boundary"
            ), mock.patch.object(
                executor, "ACCOUNT_GATES_PATH", path
            ), mock.patch.object(
                executor, "_utc_now", return_value=RESULT_TIME
            ), mock.patch.object(
                executor, "ProductionProbeBackend", backend_factory
            ), mock.patch.object(
                executor.AttemptJournal, "create"
            ) as create_journal, mock.patch.object(sys, "stdout", output):
                self.assertEqual(executor.main([]), 2)
            backend_factory.assert_not_called()
            create_journal.assert_not_called()
            self.assertIn("ACCOUNT_GATE_COUNTER_SEMANTICS", output.getvalue())

    def test_success_stdout_is_only_the_bound_secret_free_summary(self):
        gates = account_gate_document()
        backend = FakeBackend()
        original_claude = backend.claude

        def noisy_claude():
            print("PROVIDER_STDOUT_MUST_NOT_ESCAPE")
            return original_claude()

        backend.claude = noisy_claude
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "executor-result.json"
            output = io.StringIO()
            with mock.patch.object(executor, "_validate_state_dir"), mock.patch.object(
                executor, "_validate_sqlite_path", return_value=()
            ), mock.patch.object(
                executor, "_validate_environment_boundary"
            ), mock.patch.object(
                executor, "load_account_gates", return_value=gates
            ), mock.patch.object(
                executor, "_runtime_source_binding"
            ), mock.patch.object(
                executor, "_utc_now", return_value=RESULT_TIME
            ), mock.patch.object(
                executor, "ProductionProbeBackend", return_value=backend
            ), mock.patch.object(
                executor, "RESULT_PATH", result_path
            ), mock.patch.object(sys, "stdout", output):
                self.assertEqual(executor.main([]), 0)
            persisted = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(
                output.getvalue(),
                executor._terminal_summary(persisted).decode("ascii"),
            )
            self.assertNotIn("PROVIDER_STDOUT_MUST_NOT_ESCAPE", output.getvalue())

    def test_explicit_synthetic_prompt_preserves_bounds_and_model_parameters(self):
        self.assertEqual(executor.SYNTHETIC_USER, "Reply only NOTEAI_OK. Nothing else.")
        self.assertEqual(len(executor.SYNTHETIC_USER.encode("utf-8")), 35)
        self.assertEqual(
            len((executor.SYNTHETIC_SYSTEM + executor.SYNTHETIC_USER).encode("utf-8")),
            57,
        )
        self.assertEqual(executor.MAX_PROMPT_BYTES, 128)
        backend = object.__new__(executor.ProductionProbeBackend)
        backend.model_router = types.SimpleNamespace(
            call_claude_sync=mock.Mock(return_value="NOTEAI_OK"),
            _call_kimi=mock.AsyncMock(return_value="NOTEAI_OK"),
        )
        backend._create_usage = mock.Mock(side_effect=lambda provider: f"item30-{provider}")
        backend._model_usage = mock.Mock(return_value={"model_calls": 1})
        for provider in ("claude", "kimi"):
            result = getattr(backend, provider)()
            self.assertEqual(result["output_bytes"], len(verifier.SENTINEL))
            self.assertEqual(result["output_sha256"], digest(verifier.SENTINEL))
            self.assertEqual(result["model_calls"], 1)
        backend.model_router.call_claude_sync.assert_called_once_with(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            system="Return only NOTEAI_OK.",
            messages=[{"role": "user", "content": "Reply only NOTEAI_OK. Nothing else."}],
            temperature=0,
        )
        backend.model_router._call_kimi.assert_awaited_once_with(
            "kimi-k2.6", "Return only NOTEAI_OK.",
            "Reply only NOTEAI_OK. Nothing else.", False, 64,
        )
        self.assertEqual(
            backend._model_usage.call_args_list,
            [mock.call("item30-claude", "claude"), mock.call("item30-kimi", "kimi")],
        )

    def test_native_models_require_exact_sentinel(self):
        diagnostic_output = (
            "# Bounded Production Transport Check\n\nNOTEAI_OK\n\n---\n\n"
            "**Status**: Ready to process bounded production transport verification.\n\n"
            "**Capabilities**:\n- Validate transport constraints within production limits\n"
            "- Check capacity boundaries and thresholds\n"
            "- Verify resource allocation compliance\n- Assess logistics feasibility"
        )
        for provider in ("claude", "kimi"):
            for output in (
                "provider error", diagnostic_output, "NOTEAI_OK\nextra", "`NOTEAI_OK`"
            ):
                with self.subTest(provider=provider, output=output):
                    backend = object.__new__(executor.ProductionProbeBackend)
                    backend.model_router = types.SimpleNamespace(
                        call_claude_sync=mock.Mock(return_value=output),
                        _call_kimi=mock.AsyncMock(return_value=output),
                    )
                    backend._create_usage = mock.Mock(return_value=f"item30-{provider}")
                    backend._model_usage = mock.Mock()
                    with self.assertRaisesRegex(
                        executor.ProbeError, f"{provider.upper()}_OUTPUT_INVALID"
                    ):
                        getattr(backend, provider)()
                    backend._model_usage.assert_not_called()
                    if provider == "claude":
                        backend.model_router.call_claude_sync.assert_called_once()
                        backend.model_router._call_kimi.assert_not_called()
                    else:
                        backend.model_router._call_kimi.assert_awaited_once()
                        backend.model_router.call_claude_sync.assert_not_called()

    def test_fact_target_must_match_within_one_structured_item(self):
        split_items = [
            {"title": "深圳酒店", "source": "provider", "facts": {"address": "深圳"}},
            {"title": "四季酒店", "source": "provider", "facts": {"rating": "4.8"}},
        ]
        with self.assertRaisesRegex(executor.ProbeError, "FACT_OUTPUT_TARGET_MISMATCH"):
            executor.ProductionProbeBackend._fact_result(split_items, "test")
        matched = [{
            "title": "深圳四季酒店",
            "source": "provider",
            "facts": {"address": "深圳市福田区"},
        }]
        self.assertTrue(
            executor.ProductionProbeBackend._fact_result(matched, "test")[
                "target_entity_matched"
            ]
        )

    def test_meituan_disabled_is_not_ready(self):
        backend = object.__new__(executor.ProductionProbeBackend)
        backend.model_router = types.SimpleNamespace(
            claude_transport_readiness=mock.Mock(
                return_value={
                    "mode": "gateway",
                    "configured": True,
                    "remote_checked": True,
                    "remote_ready": True,
                }
            )
        )
        backend.fact_enrichment = types.SimpleNamespace(
            meituan_travel_runtime_status=mock.Mock(
                return_value={
                    "ok": True,
                    "required": False,
                    "status_code": "MEITUAN_TRAVEL_DISABLED",
                }
            )
        )
        with mock.patch.dict(
            os.environ,
            {"MOONSHOT_API_KEY": "present", "AMAP_WEB_KEY": "present"},
            clear=False,
        ):
            with self.assertRaisesRegex(
                executor.ProbeError, "MEITUAN_RUNTIME_NOT_READY"
            ):
                backend.preflight()

    def test_environment_projection_is_exact_for_application_secrets(self):
        allowed = {
            "NOTEAI_CLAUDE_GATEWAY_URL": "https://gateway.example.invalid",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": "item30",
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "1",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "1",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "current",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "secret",
            "NOTEAI_CLAUDE_TRANSPORT": "gateway",
            "NOTEAI_FACT_SEARCH": "1",
            "NOTEAI_MEITUAN_TRAVEL_ENABLED": "1",
            "NOTEAI_CLOUD_RUNTIME": "1",
            "NOTEAI_RUNTIME_ROLE": "api",
            "MOONSHOT_API_KEY": "secret",
            "AMAP_WEB_KEY": "secret",
            "MEITUAN_AI_HUB_TOKEN": "secret",
            "MEITUAN_TRAVEL_CLI": "/usr/local/bin/mttravel",
            "TMPDIR": "/dev/shm",
        }
        with mock.patch.dict(os.environ, allowed, clear=True):
            executor._validate_environment_boundary()
            os.environ["AWS_SESSION_TOKEN"] = "forbidden"
            with self.assertRaisesRegex(
                executor.ProbeError, "ENVIRONMENT_SCOPE_FORBIDDEN"
            ):
                executor._validate_environment_boundary()
        with mock.patch.dict(
            os.environ,
            {**allowed, "NOTEAI_MEITUAN_TRAVEL_TIMEOUT": "46"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                executor.ProbeError, "FACT_RUNTIME_SCOPE_INVALID"
            ):
                executor._validate_environment_boundary()

    def test_sqlite_path_is_fixed_tmpfs(self):
        with self.assertRaisesRegex(executor.ProbeError, "SQLITE_PATH_FORBIDDEN"):
            executor._validate_sqlite_path(Path("/tmp/other.db"))
        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "noteai-item30-usage.db"
            with mock.patch.object(executor, "SQLITE_PATH", test_path), mock.patch.object(
                executor, "_mount_filesystem", return_value="tmpfs"
            ):
                artifacts = executor._validate_sqlite_path(test_path)
        self.assertEqual(artifacts[0], test_path)

    def test_amap_text_only_path_sends_one_http_request(self):
        model_path = ROOT / "model"
        if str(model_path) not in sys.path:
            sys.path.insert(0, str(model_path))
        import fact_enrichment

        calls = []

        class Response:
            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {
                    "pois": [{
                        "id": "public-poi",
                        "name": "深圳四季酒店",
                        "address": "深圳市福田区",
                        "type": "住宿服务",
                        "biz_ext": {"rating": "4.8"},
                    }]
                }

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def get(self, url, **_kwargs):
                calls.append(url)
                return Response()

        with mock.patch.object(fact_enrichment.httpx, "Client", Client), mock.patch.object(
            fact_enrichment,
            "_amap_fetch_v5_detail",
            side_effect=AssertionError("detail request forbidden"),
        ):
            items = fact_enrichment._search_amap(
                executor.PUBLIC_FACT_QUERY, max_detail_requests=0
            )
        self.assertEqual(calls, ["https://restapi.amap.com/v3/place/text"])
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["facts"])


class Item30EvidenceVerifierTests(unittest.TestCase):
    def test_bound_terminal_evidence_passes(self):
        self.assertEqual(
            verifier.validate_document(evidence_fixture(), verify_git=False), []
        )

    def test_command_name_matches_actual_official_execution(self):
        actual = "noteai-item30-provider-8719308abacc687d"
        self.assertEqual(verifier.COMMAND_NAME, actual)
        for name in (actual, "noteai-item30-real-provider-chain-20260824"):
            with self.subTest(name=name):
                value = evidence_fixture()
                value["execution"]["command_name"] = name
                value["terminal_acceptance_sha256"] = (
                    verifier.terminal_acceptance_sha256(value)
                )
                self.assertEqual(
                    verifier.validate_document(value, verify_git=False),
                    [] if name == actual else ["execution terminal binding mismatch"],
                )

    def test_readonly_source_bind_count_is_exactly_three(self):
        for count in (3, 2, 4):
            with self.subTest(count=count):
                value = evidence_fixture()
                value["resources"]["readonly_source_bind_count"] = count
                value["terminal_acceptance_sha256"] = (
                    verifier.terminal_acceptance_sha256(value)
                )
                self.assertEqual(
                    verifier.validate_document(value, verify_git=False),
                    [] if count == 3 else ["resource state mismatch"],
                )

    def test_application_image_binding_rejects_cad5_and_mixed_identities(self):
        self.assertEqual(
            verifier.APPLICATION_RELEASE_REVISION,
            "b55f11882100e9ef919522540729e366a511f88f",
        )
        self.assertEqual(
            verifier.APPLICATION_MANIFEST_SHA256,
            "612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620",
        )
        self.assertEqual(
            verifier.APPLICATION_CONFIG_SHA256,
            "dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53",
        )
        cad5 = {
            "application_release_revision": (
                "cad5ce35664f617c6e19f90a6159285ddf975594"
            ),
            "application_manifest_sha256": (
                "407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b"
            ),
            "application_config_sha256": (
                "1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95"
            ),
        }
        cases = (
            (cad5, "application release revision mismatch"),
            (
                {
                    "application_manifest_sha256": cad5[
                        "application_manifest_sha256"
                    ]
                },
                "application manifest mismatch",
            ),
            (
                {
                    "application_config_sha256": cad5[
                        "application_config_sha256"
                    ]
                },
                "application config mismatch",
            ),
            (
                {
                    "application_release_revision": cad5[
                        "application_release_revision"
                    ]
                },
                "application release revision mismatch",
            ),
        )
        for replacements, expected in cases:
            with self.subTest(replacements=replacements):
                value = evidence_fixture()
                value["source_binding"].update(replacements)
                value["terminal_acceptance_sha256"] = (
                    verifier.terminal_acceptance_sha256(value)
                )
                errors = verifier.validate_document(value, verify_git=False)
                self.assertIn(expected, errors)

    def test_legacy_self_asserted_shape_cannot_receive_credit(self):
        value = evidence_fixture()
        value.pop("execution")
        value.pop("provider_native_bindings")
        self.assertIn("evidence shape mismatch", verifier.validate_document(value))

    def test_raw_and_native_mutations_refuse_credit_even_when_rehashed(self):
        cases = [
            (
                ("execution", "executor_result", "providers", "claude", "output_sha256"),
                digest("not-sentinel"),
                "sentinel output",
                True,
            ),
            (
                ("provider_native_bindings", "claude", "account_identity_sha256"),
                digest("different-account"),
                "native account binding",
                False,
            ),
            (
                ("provider_native_bindings", "amap", "post", "counter_value"),
                "202.000000",
                "counter arithmetic",
                False,
            ),
            (
                ("provider_native_bindings", "kimi", "post", "observed_at_utc"),
                FINISH_TIME,
                "observation order",
                False,
            ),
            (
                ("execution", "repeat_count"),
                2,
                "execution terminal binding",
                False,
            ),
            (
                ("readiness", "next_task"),
                "PROD-FIRST-LAUNCH-REAL-PAYMENT-001",
                "readiness mismatch",
                False,
            ),
            (
                ("source_binding", "application_executor_readonly_overlay"),
                False,
                "executor overlay boundary",
                False,
            ),
            (
                ("resources", "temporary_docker_volume_count"),
                1,
                "resource state mismatch",
                False,
            ),
            (
                ("cleanup", "task_volume_residue_count"),
                1,
                "cleanup mismatch",
                False,
            ),
            (
                ("execution", "exit_code"),
                False,
                "execution terminal binding",
                False,
            ),
            (
                ("execution", "repeat_count"),
                True,
                "execution terminal binding",
                False,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "claude",
                    "dispatch_count",
                ),
                True,
                "raw dispatch terminal",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "meituan",
                    "cli_invocation_count",
                ),
                0,
                "meituan: invocation boundary",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "meituan",
                    "cli_invocation_count",
                ),
                2,
                "meituan: invocation boundary",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "meituan",
                    "dispatch_count",
                ),
                0,
                "raw dispatch terminal",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "claude",
                    "model_calls",
                ),
                True,
                "application usage/cost",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "meituan",
                    "cli_invocation_count",
                ),
                True,
                "meituan: invocation boundary",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "meituan",
                    "dispatch_count",
                ),
                2,
                "raw dispatch terminal",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "meituan",
                    "automatic_retry_count",
                ),
                1,
                "raw dispatch terminal",
                True,
            ),
            (
                (
                    "execution",
                    "executor_result",
                    "providers",
                    "meituan",
                    "fallback_count",
                ),
                1,
                "raw dispatch terminal",
                True,
            ),
            (
                (
                    "provider_native_bindings",
                    "meituan",
                    "usage_delta",
                ),
                "0.000000",
                "exact-one disclosure binding",
                False,
            ),
            (
                (
                    "provider_native_bindings",
                    "meituan",
                    "native_event_id_sha256",
                ),
                digest("invented-provider-event"),
                "exact-one disclosure binding",
                False,
            ),
            (
                (
                    "provider_native_bindings",
                    "meituan",
                    "post",
                    "counter_value",
                ),
                "0.000000",
                "native post disclosure",
                False,
            ),
        ]
        for path, replacement, expected, raw_changed in cases:
            with self.subTest(path=path):
                value = evidence_fixture()
                target = value
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                if raw_changed:
                    rebind_raw(value)
                else:
                    value["terminal_acceptance_sha256"] = (
                        verifier.terminal_acceptance_sha256(value)
                    )
                errors = verifier.validate_document(value, verify_git=False)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_arm_time_price_and_meituan_disclosure_are_bound(self):
        price_changed = evidence_fixture()
        price_changed["provider_native_bindings"]["claude"]["pre"][
            "price_snapshot_sha256"
        ] = digest("different-price-snapshot")
        price_changed["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(price_changed)
        )
        self.assertTrue(
            any(
                "native pre/gate projection" in error
                for error in verifier.validate_document(
                    price_changed, verify_git=False
                )
            )
        )

        meituan_mixed = evidence_fixture()
        raw_gate = meituan_mixed["execution"]["executor_result"]["account_gate"][
            "providers"
        ]["meituan"]
        raw_gate["pre_call_counter"].update(
            {
                "counter_kind": "request_count",
                "counter_unit": "requests",
                "direction": "increasing",
                "counter_value": "0.000000",
            }
        )
        rebind_raw(meituan_mixed)
        self.assertTrue(
            any(
                "meituan: disclosure gate" in error
                for error in verifier.validate_document(
                    meituan_mixed, verify_git=False
                )
            )
        )

    def test_future_settlement_and_malformed_nested_counters_fail_closed(self):
        future = evidence_fixture()
        future["provider_native_bindings"]["claude"]["settlement"][
            "observed_at_utc"
        ] = "2027-08-24T13:08:00Z"
        future["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(future)
        )
        self.assertTrue(
            any(
                "native observation order" in error
                for error in verifier.validate_document(future, verify_git=False)
            )
        )

        for malformed in ([1], "invalid", None, {"unexpected": "shape"}):
            with self.subTest(native_post=malformed):
                value = evidence_fixture()
                value["provider_native_bindings"]["amap"]["post"] = malformed
                value["terminal_acceptance_sha256"] = (
                    verifier.terminal_acceptance_sha256(value)
                )
                errors = verifier.validate_document(value, verify_git=False)
                self.assertTrue(errors)
                self.assertTrue(
                    any("native post" in error for error in errors), errors
                )

        for malformed in ([1], "invalid", None, {"unexpected": "shape"}):
            with self.subTest(account_pre=malformed):
                value = evidence_fixture()
                value["execution"]["executor_result"]["account_gate"][
                    "providers"
                ]["amap"]["pre_call_counter"] = malformed
                rebind_raw(value)
                errors = verifier.validate_document(value, verify_git=False)
                self.assertTrue(errors)
                self.assertTrue(any("amap: pre" in error for error in errors), errors)

        cap_changed = evidence_fixture()
        cap_changed["execution"]["executor_result"]["account_gate"]["providers"][
            "meituan"
        ]["unit_cost_upper_bound_rmb"] = "0.100000"
        cap_changed["provider_native_bindings"]["meituan"]["pre"][
            "current_unit_cap_rmb"
        ] = "0.100000"
        rebind_raw(cap_changed)
        self.assertTrue(
            any(
                "meituan: disclosure gate" in error
                for error in verifier.validate_document(cap_changed, verify_git=False)
            )
        )

        counter_changed = evidence_fixture()
        raw_pre = counter_changed["execution"]["executor_result"]["account_gate"][
            "providers"
        ]["meituan"]["pre_call_counter"]
        native = counter_changed["provider_native_bindings"]["meituan"]
        for counter in (raw_pre, native["pre"], native["post"]):
            counter["counter_kind"] = "request_count"
            counter["counter_unit"] = "requests"
            counter["direction"] = "increasing"
            counter["counter_value"] = "0.000000"
        rebind_raw(counter_changed)
        self.assertTrue(
            any(
                "meituan: disclosure" in error
                for error in verifier.validate_document(
                    counter_changed, verify_git=False
                )
            )
        )

    def test_meituan_unknown_cost_cannot_be_forged_as_zero_or_reconciled(self):
        cases = [
            (("cost_and_settlement", "incremental_provider_cost_rmb"), "0.005000"),
            (("cost_and_settlement", "total_incremental_cost_rmb"), "0.005000"),
            (("cost_and_settlement", "hard_cap_rmb"), "1.000000"),
            (("cost_and_settlement", "within_cap"), True),
            (("cost_and_settlement", "provider_settlement_complete_count"), 4),
            (
                (
                    "provider_native_bindings",
                    "meituan",
                    "settlement",
                    "status",
                ),
                "RECONCILED",
            ),
            (
                (
                    "provider_native_bindings",
                    "meituan",
                    "settlement",
                    "incremental_cost_rmb",
                ),
                "0.000000",
            ),
        ]
        for path, replacement in cases:
            with self.subTest(path=path):
                value = evidence_fixture()
                target = value
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                value["terminal_acceptance_sha256"] = (
                    verifier.terminal_acceptance_sha256(value)
                )
                errors = verifier.validate_document(value, verify_git=False)
                self.assertTrue(
                    any(
                        "cost settlement mismatch" in error
                        or "meituan: settlement disclosure" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_fully_rebound_legacy_numeric_meituan_still_fails(self):
        value = evidence_fixture()
        raw = value["execution"]["executor_result"]
        gate = raw["account_gate"]["providers"]["meituan"]
        gate.update(
            {
                "balance_or_quota_confirmed": True,
                "current_price_confirmed": True,
                "pre_call_counter_readable": True,
                "unit_cost_upper_bound_rmb": "0.500000",
            }
        )
        gate["pre_call_counter"].update(
            {
                "counter_kind": "request_count",
                "counter_unit": "requests",
                "direction": "increasing",
                "counter_value": "0.000000",
            }
        )
        raw["bounds"]["total_cost_cap_rmb"] = "1.000000"
        raw["totals"]["worst_case_provider_cost_rmb"] = "0.800000"
        native = value["provider_native_bindings"]["meituan"]
        native["pre"].update(
            {
                **copy.deepcopy(gate["pre_call_counter"]),
                "quota_or_balance_sufficient": True,
                "current_unit_cap_rmb": "0.500000",
            }
        )
        native["post"].update(
            {
                **copy.deepcopy(gate["pre_call_counter"]),
                "observed_at_utc": POST_TIME,
                "counter_value": "1.000000",
                "snapshot_sha256": digest("legacy-meituan-post"),
            }
        )
        native["usage_delta"] = "1.000000"
        native["native_event_id_sha256"] = digest("legacy-meituan-event")
        native["settlement"].update(
            {
                "status": "RECONCILED",
                "currency": "RMB",
                "incremental_cost_rmb": "0.200000",
                "reconciliation_tolerance_rmb": "0.010000",
                "snapshot_sha256": digest("legacy-meituan-settlement"),
            }
        )
        value["cost_and_settlement"].update(
            {
                "incremental_provider_cost_rmb": "0.205000",
                "total_incremental_cost_rmb": "0.205000",
                "hard_cap_rmb": "1.000000",
                "within_cap": True,
                "provider_settlement_complete_count": 4,
            }
        )
        rebind_raw(value)
        errors = verifier.validate_document(value, verify_git=False)
        self.assertTrue(errors)
        self.assertTrue(
            any(
                "meituan: disclosure gate" in error
                or "executor bounds mismatch" in error
                or "cost settlement mismatch" in error
                for error in errors
            ),
            errors,
        )

    def test_malformed_raw_provider_and_kimi_tokens_return_errors(self):
        for malformed in ([1], "invalid", None, {"unexpected": "shape"}):
            with self.subTest(meituan=malformed):
                value = evidence_fixture()
                value["execution"]["executor_result"]["providers"][
                    "meituan"
                ] = malformed
                rebind_raw(value)
                errors = verifier.validate_document(value, verify_git=False)
                self.assertTrue(errors)
                self.assertTrue(
                    any("meituan: raw provider shape" in error for error in errors),
                    errors,
                )

        for malformed in ("invalid", None, True):
            with self.subTest(kimi_input_tokens=malformed):
                value = evidence_fixture()
                value["execution"]["executor_result"]["providers"]["kimi"][
                    "input_tokens"
                ] = malformed
                rebind_raw(value)
                errors = verifier.validate_document(value, verify_git=False)
                self.assertTrue(errors)
                self.assertTrue(
                    any(
                        "kimi: application usage/cost" in error
                        or "kimi: native token delta" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_source_revision_must_contain_exact_executor_and_fact_blobs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "deploy" / "production").mkdir(parents=True)
            (root / "model").mkdir()
            shutil.copyfile(EXECUTOR_SOURCE, root / verifier.EXECUTOR_REF)
            shutil.copyfile(FACT_SOURCE, root / verifier.FACT_ENRICHMENT_REF)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Item30 Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "bundle"], cwd=root, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()

            value = evidence_fixture()
            source = value["source_binding"]
            source["execution_source_revision"] = revision
            raw = value["execution"]["executor_result"]
            raw["account_gate"]["execution_source_revision"] = revision
            raw["attempt"]["execution_source_revision"] = revision
            rebind_raw(value)
            self.assertEqual(
                verifier.validate_document(value, root=root, verify_git=True), []
            )

            subprocess.run(["git", "rm", "-q", verifier.FACT_ENRICHMENT_REF], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "remove fact"], cwd=root, check=True)
            missing_revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            source["execution_source_revision"] = missing_revision
            raw["account_gate"]["execution_source_revision"] = missing_revision
            raw["attempt"]["execution_source_revision"] = missing_revision
            rebind_raw(value)
            errors = verifier.validate_document(value, root=root, verify_git=True)
            self.assertIn("fact enrichment Git blob mismatch", errors)


if __name__ == "__main__":
    unittest.main()
