from __future__ import annotations

import ast
import builtins
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import types
import unittest
from unittest import mock
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "tools" / "item26_aliyun_cli_oauth_bootstrap_v1.py"
MODULE_NAME = "item26_aliyun_cli_oauth_bootstrap_v1_test_target"

EXPECTED_SOURCE_SCHEMA = "noteai.item26.aliyun-cli-oauth-bootstrap-source.v1"
EXPECTED_PROJECTION_SCHEMA = (
    "noteai.item26.aliyun-cli-oauth-bootstrap-stock-projection.v1"
)
EXPECTED_DECISION = "NO_GO_STOCK_CLI_FD_ONLY_OAUTH"
EXPECTED_BOOTSTRAP_STATUS = "NOT_PROVISIONED"

EXPECTED_LOCAL_IDENTITY = {
    "bytes": 87_064_450,
    "distribution": "OFFICIAL_HOMEBREW_ALIYUN_CLI",
    "evidence_id": "ACCEPTED_LOCAL_IDENTITY_LEDGER",
    "live_inspection_performed": False,
    "mode": "0555",
    "owner": "openclaw:admin",
    "provenance": "ACCEPTED_TRACKED_LEDGER_STATIC_NOT_LIVE_INSPECTION",
    "resolved_path": "/opt/homebrew/Cellar/aliyun-cli/3.4.11/bin/aliyun",
    "root_owned": False,
    "sha256": "7a418ea428dcbfeaab2af8760938aeda8d2f16bd77b586cbe4c75b07034df8fb",
    "version": "3.4.11",
}

EXPECTED_RELEASE_IDENTITY = {
    "commit": "f54f5fe9caa99723a6324b20eaa60f3de3b049cb",
    "evidence_id": "UPSTREAM_RELEASE_V3_4_11",
    "tag": "v3.4.11",
}

EXPECTED_OBSERVED_STOCK = {
    "browser_loopback_pkce": True,
    "config_path_full_lifecycle_safe": False,
    "custom_config_flag": True,
    "device_code": False,
    "fd_secret_export": False,
    "headless": False,
    "oauth_configure_plugin_required": False,
    "profile_contains_secrets": True,
    "refresh_can_touch_default_config": True,
    "requested_sts_ttl_control": False,
    "stdout_profile_secret_export": True,
}

EXPECTED_REQUIREMENT_CLASSIFICATIONS = {
    "browserless_headless_oauth": "ABSENT",
    "device_code_oauth": "ABSENT",
    "fd_only_secret_export": "ABSENT",
    "isolated_config_full_lifecycle": "UNSAFE",
    "refresh_default_config_neutral": "UNSAFE",
    "requested_sts_ttl_control": "ABSENT",
    "secret_free_profile": "UNSAFE",
    "secret_free_stdout": "UNSAFE",
}

EXPECTED_GATES = {
    "browser_oauth": False,
    "capture_integration": False,
    "cli_oauth_configuration": False,
    "credential_bootstrap": False,
    "plugin_execution": False,
    "stock_cli_execution": False,
}

EXPECTED_SOURCE_ROUND_COUNTS = {
    "argv_read_count": 0,
    "automatic_retry_count": 0,
    "browser_launch_count": 0,
    "capture_count": 0,
    "cleanup_count": 0,
    "cli_configure_count": 0,
    "cli_execution_count": 0,
    "config_read_count": 0,
    "config_write_count": 0,
    "credential_read_count": 0,
    "credential_write_count": 0,
    "database_connection_count": 0,
    "environment_read_count": 0,
    "filesystem_read_count": 0,
    "filesystem_write_count": 0,
    "materialization_count": 0,
    "network_call_count": 0,
    "oauth_login_count": 0,
    "oauth_refresh_count": 0,
    "plugin_execution_count": 0,
    "provider_call_count": 0,
    "root_read_count": 0,
    "root_write_count": 0,
    "secret_input_count": 0,
    "secret_output_count": 0,
    "stderr_write_count": 0,
    "stdout_write_count": 0,
    "subprocess_count": 0,
    "sudo_dispatch_count": 0,
}

EXPECTED_PRIOR_RESEARCH_AUDIT = {
    "aliyun_provider_cloud_call_count": 0,
    "generic_historical_filesystem_write_zero_claimed": False,
    "generic_historical_network_zero_claimed": False,
    "homebrew_nonprovider_metadata_network_event_count": 1,
    "homebrew_possible_cache_write_event_count": 1,
    "official_evidence_web_request_count": None,
    "official_evidence_web_request_count_status": "NOT_EXACTLY_ENUMERATED",
    "official_evidence_web_research_performed": True,
}

EXPECTED_EVIDENCE_IDS = {
    "ACCEPTED_LOCAL_IDENTITY_LEDGER",
    "BROWSER_PROCESS_EXACT_SOURCE",
    "CONFIG_PATH_ENTRY_EXACT_SOURCE",
    "CONFIG_STORAGE_EXACT_SOURCE",
    "CREDENTIALS_OFFICIAL_DOC",
    "EXTERNAL_INGRESS_EXACT_README",
    "OAUTH_EXCHANGE_TTL_EXACT_SOURCE",
    "OAUTH_FLOW_EXACT_SOURCE",
    "OAUTH_OFFICIAL_DOC",
    "PROFILE_REFRESH_EXACT_SOURCE",
    "PROFILE_STDOUT_EXACT_SOURCE",
    "UPSTREAM_RELEASE_V3_4_11",
}

EXPECTED_CAPABILITY_EVIDENCE_IDS = {
    "browser_loopback_pkce": [
        "OAUTH_FLOW_EXACT_SOURCE",
        "BROWSER_PROCESS_EXACT_SOURCE",
        "OAUTH_OFFICIAL_DOC",
    ],
    "config_path_full_lifecycle_safe": [
        "CONFIG_PATH_ENTRY_EXACT_SOURCE",
        "PROFILE_REFRESH_EXACT_SOURCE",
        "CONFIG_STORAGE_EXACT_SOURCE",
    ],
    "custom_config_flag": ["CONFIG_PATH_ENTRY_EXACT_SOURCE"],
    "device_code": ["OAUTH_FLOW_EXACT_SOURCE", "OAUTH_OFFICIAL_DOC"],
    "fd_secret_export": [
        "PROFILE_STDOUT_EXACT_SOURCE",
        "EXTERNAL_INGRESS_EXACT_README",
        "CREDENTIALS_OFFICIAL_DOC",
    ],
    "headless": [
        "OAUTH_FLOW_EXACT_SOURCE",
        "BROWSER_PROCESS_EXACT_SOURCE",
        "OAUTH_OFFICIAL_DOC",
    ],
    "oauth_configure_plugin_required": ["OAUTH_FLOW_EXACT_SOURCE"],
    "profile_contains_secrets": [
        "PROFILE_REFRESH_EXACT_SOURCE",
        "CREDENTIALS_OFFICIAL_DOC",
    ],
    "refresh_can_touch_default_config": [
        "CONFIG_PATH_ENTRY_EXACT_SOURCE",
        "PROFILE_REFRESH_EXACT_SOURCE",
        "CONFIG_STORAGE_EXACT_SOURCE",
        "OAUTH_OFFICIAL_DOC",
    ],
    "requested_sts_ttl_control": ["OAUTH_EXCHANGE_TTL_EXACT_SOURCE"],
    "stdout_profile_secret_export": [
        "PROFILE_STDOUT_EXACT_SOURCE",
        "CREDENTIALS_OFFICIAL_DOC",
    ],
}


def load_module() -> tuple[types.ModuleType, bytes]:
    raw = SOURCE_PATH.read_bytes()
    module = types.ModuleType(MODULE_NAME)
    module.__file__ = str(SOURCE_PATH)
    module.__package__ = ""
    sys.modules[MODULE_NAME] = module
    exec(compile(raw, str(SOURCE_PATH), "exec"), module.__dict__)
    return module, raw


def strict_object(raw: bytes) -> dict[str, object]:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AssertionError(f"duplicate key: {key}")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("ascii"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            AssertionError(f"nonfinite: {value}")
        ),
    )
    if type(value) is not dict:
        raise AssertionError("top level is not an object")
    return value


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one function {name}, got {len(matches)}")
    return matches[0]


class Poison:
    def __getattribute__(self, _name):
        raise AssertionError("poison attribute inspected")

    def __iter__(self):
        raise AssertionError("poison iterated")

    def __str__(self):
        raise AssertionError("poison formatted")

    def __repr__(self):
        raise AssertionError("poison represented")

    def __bool__(self):
        raise AssertionError("poison truth-tested")


class Item26AliyunCliOauthBootstrapV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module, cls.raw = load_module()
        cls.tree = ast.parse(cls.raw, filename=str(SOURCE_PATH))

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop(MODULE_NAME, None)

    def projection(self) -> dict[str, object]:
        return strict_object(self.module.stock_cli_projection())

    def status(self) -> dict[str, object]:
        return strict_object(self.module.source_status())

    def test_01_fixed_public_schemas_and_decision(self) -> None:
        self.assertEqual(self.module.SOURCE_SCHEMA, EXPECTED_SOURCE_SCHEMA)
        self.assertEqual(
            self.module.STOCK_CLI_PROJECTION_SCHEMA,
            EXPECTED_PROJECTION_SCHEMA,
        )
        self.assertEqual(self.module.STOCK_CLI_ASSESSMENT, EXPECTED_DECISION)
        self.assertEqual(self.module.BOOTSTRAP_STATUS, EXPECTED_BOOTSTRAP_STATUS)
        self.assertEqual(self.module.assess_stock_cli(), EXPECTED_DECISION)

    def test_02_local_resolved_target_identity_is_exact(self) -> None:
        projection = self.projection()
        self.assertEqual(projection["local_cli_identity"], EXPECTED_LOCAL_IDENTITY)
        identity = projection["local_cli_identity"]
        self.assertIs(type(identity["bytes"]), int)
        self.assertIs(identity["root_owned"], False)
        self.assertEqual(len(identity["sha256"]), 64)
        self.assertEqual(identity["sha256"], identity["sha256"].lower())

    def test_03_official_release_identity_is_exact_and_matches_version(self) -> None:
        projection = self.projection()
        release = projection["official_release_identity"]
        self.assertEqual(release, EXPECTED_RELEASE_IDENTITY)
        self.assertEqual(release["tag"].removeprefix("v"), LOCAL_VERSION := "3.4.11")
        self.assertEqual(LOCAL_VERSION, projection["local_cli_identity"]["version"])
        self.assertEqual(len(release["commit"]), 40)
        self.assertTrue(all(character in "0123456789abcdef" for character in release["commit"]))

    def test_04_observed_stock_matrix_has_exact_eleven_boolean_facts(self) -> None:
        observed = self.projection()["observed_stock_capabilities"]
        self.assertEqual(observed, EXPECTED_OBSERVED_STOCK)
        self.assertEqual(len(observed), 11)
        self.assertTrue(all(type(value) is bool for value in observed.values()))

    def test_05_positive_pkce_and_custom_config_facts_are_not_erased(self) -> None:
        observed = self.projection()["observed_stock_capabilities"]
        self.assertIs(observed["browser_loopback_pkce"], True)
        self.assertIs(observed["custom_config_flag"], True)
        self.assertIs(observed["headless"], False)
        self.assertIs(observed["device_code"], False)

    def test_06_secret_and_refresh_risk_facts_are_exact(self) -> None:
        observed = self.projection()["observed_stock_capabilities"]
        self.assertIs(observed["fd_secret_export"], False)
        self.assertIs(observed["stdout_profile_secret_export"], True)
        self.assertIs(observed["profile_contains_secrets"], True)
        self.assertIs(observed["refresh_can_touch_default_config"], True)
        self.assertIs(observed["config_path_full_lifecycle_safe"], False)

    def test_07_plugin_and_sts_control_observations_are_exact(self) -> None:
        observed = self.projection()["observed_stock_capabilities"]
        self.assertIs(observed["oauth_configure_plugin_required"], False)
        self.assertIs(observed["requested_sts_ttl_control"], False)

    def test_08_accepted_requirement_matrix_is_exact_and_separate(self) -> None:
        projection = self.projection()
        requirements = projection["accepted_requirements"]
        self.assertEqual(set(requirements), set(EXPECTED_REQUIREMENT_CLASSIFICATIONS))
        self.assertIsNot(requirements, projection["observed_stock_capabilities"])
        for name, classification in EXPECTED_REQUIREMENT_CLASSIFICATIONS.items():
            self.assertEqual(
                requirements[name],
                {"classification": classification, "stock_support": False},
            )
            self.assertIs(requirements[name]["stock_support"], False)

    def test_09_absent_and_unsafe_requirement_classes_are_both_frozen(self) -> None:
        requirements = self.projection()["accepted_requirements"]
        classes = {row["classification"] for row in requirements.values()}
        self.assertEqual(classes, {"ABSENT", "UNSAFE"})
        self.assertEqual(
            {name for name, row in requirements.items() if row["classification"] == "ABSENT"},
            {
                "browserless_headless_oauth",
                "device_code_oauth",
                "fd_only_secret_export",
                "requested_sts_ttl_control",
            },
        )

    def test_10_assessment_is_fixed_no_go_when_fact_maps_are_rebound(self) -> None:
        projection_before = self.module.stock_cli_projection()
        status_before = self.module.source_status()
        with mock.patch.object(self.module, "OBSERVED_STOCK_CAPABILITIES", {}), \
             mock.patch.object(self.module, "EXECUTION_GATES", {"unsafe": True}):
            self.assertEqual(self.module.assess_stock_cli(), EXPECTED_DECISION)
            self.assertEqual(self.module.stock_cli_projection(), projection_before)
            self.assertEqual(self.module.source_status(), status_before)

    def test_11_assessment_ast_has_only_the_fixed_constant_return(self) -> None:
        node = function_node(self.tree, "assess_stock_cli")
        returns = [item for item in ast.walk(node) if isinstance(item, ast.Return)]
        self.assertEqual(len(returns), 1)
        self.assertIsInstance(returns[0].value, ast.Name)
        self.assertEqual(returns[0].value.id, "STOCK_CLI_ASSESSMENT")
        branches = [
            item
            for item in ast.walk(node)
            if isinstance(item, (ast.If, ast.IfExp, ast.Match, ast.Try, ast.While))
        ]
        self.assertEqual(branches, [])
        self.assertNotIn(
            "GO",
            {
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and type(item.value) is str
            },
        )

    def test_12_projection_is_exact_canonical_ascii_with_one_lf(self) -> None:
        raw = self.module.stock_cli_projection()
        self.assertIs(type(raw), bytes)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))
        self.assertNotIn(b"\x00", raw)
        value = strict_object(raw)
        self.assertEqual(raw, canonical(value))
        self.assertEqual(
            set(value),
            {
                "accepted_requirements",
                "assessment",
                "capability_evidence_classifications",
                "capability_evidence_ids",
                "evidence_index",
                "local_cli_identity",
                "observed_stock_capabilities",
                "official_release_identity",
                "schema",
            },
        )
        self.assertEqual(value["schema"], EXPECTED_PROJECTION_SCHEMA)
        self.assertEqual(value["assessment"], EXPECTED_DECISION)

    def test_13_projection_output_is_immutable_and_local_mutation_isolated(self) -> None:
        raw = self.module.stock_cli_projection()
        self.assertIs(copy.copy(raw), raw)
        self.assertIs(copy.deepcopy(raw), raw)
        with self.assertRaises(TypeError):
            raw[0] = 0
        parsed = strict_object(raw)
        parsed["assessment"] = "GO"
        parsed["local_cli_identity"]["bytes"] = 1
        parsed["observed_stock_capabilities"]["headless"] = True
        parsed["accepted_requirements"]["fd_only_secret_export"]["stock_support"] = True
        self.assertEqual(self.module.stock_cli_projection(), raw)
        self.assertEqual(self.module.assess_stock_cli(), EXPECTED_DECISION)

    def test_14_internal_fact_maps_reject_direct_mutation(self) -> None:
        with self.assertRaises(TypeError):
            self.module.OBSERVED_STOCK_CAPABILITIES["headless"] = True
        with self.assertRaises(TypeError):
            self.module._ACCEPTED_REQUIREMENT_CLASSIFICATIONS[
                "fd_only_secret_export"
            ] = "SAFE"
        with self.assertRaises(TypeError):
            self.module.EXECUTION_GATES["stock_cli_execution"] = True
        with self.assertRaises(TypeError):
            self.module.SOURCE_ROUND_OPERATION_COUNTS["network_call_count"] = 1

    def test_15_status_is_exact_canonical_ascii_and_embeds_projection(self) -> None:
        raw = self.module.source_status()
        self.assertIs(type(raw), bytes)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))
        self.assertNotIn(b"\x00", raw)
        status = strict_object(raw)
        self.assertEqual(raw, canonical(status))
        self.assertEqual(
            set(status),
            {
                "authorizes_execution",
                "authorized_cny",
                "bootstrap_status",
                "execution_gates",
                "implementation_complete",
                "incurred_cny",
                "operational_ready",
                "prior_research_audit",
                "schema",
                "source_round_operation_counts",
                "source_round_operation_count_scope",
                "status",
                "stock_cli_assessment",
                "stock_cli_projection",
            },
        )
        self.assertEqual(status["schema"], EXPECTED_SOURCE_SCHEMA)
        self.assertEqual(
            status["status"],
            "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED",
        )
        self.assertIs(status["implementation_complete"], True)
        self.assertIs(status["authorizes_execution"], False)
        self.assertIs(status["operational_ready"], False)
        self.assertEqual(status["bootstrap_status"], EXPECTED_BOOTSTRAP_STATUS)
        self.assertEqual(status["stock_cli_assessment"], EXPECTED_DECISION)
        self.assertEqual(status["stock_cli_projection"], self.projection())

    def test_16_all_execution_gates_are_exact_bool_false(self) -> None:
        gates = self.status()["execution_gates"]
        self.assertEqual(gates, EXPECTED_GATES)
        self.assertEqual(len(gates), 6)
        self.assertTrue(all(value is False for value in gates.values()))

    def test_17_source_round_operation_counts_are_exact_integer_zero(self) -> None:
        counts = self.status()["source_round_operation_counts"]
        self.assertEqual(
            self.status()["source_round_operation_count_scope"],
            "MODULE_RUNTIME_ONLY",
        )
        self.assertEqual(counts, EXPECTED_SOURCE_ROUND_COUNTS)
        for key, value in counts.items():
            self.assertTrue(key.endswith("_count"), key)
            self.assertIs(type(value), int, key)
            self.assertEqual(value, 0, key)

    def test_18_prior_research_history_is_not_erased_or_misattributed(self) -> None:
        status = self.status()
        audit = status["prior_research_audit"]
        self.assertEqual(audit, EXPECTED_PRIOR_RESEARCH_AUDIT)
        self.assertEqual(audit["homebrew_nonprovider_metadata_network_event_count"], 1)
        self.assertEqual(audit["homebrew_possible_cache_write_event_count"], 1)
        self.assertIs(audit["generic_historical_network_zero_claimed"], False)
        self.assertIs(
            audit["generic_historical_filesystem_write_zero_claimed"],
            False,
        )
        self.assertEqual(audit["aliyun_provider_cloud_call_count"], 0)
        self.assertIs(audit["official_evidence_web_research_performed"], True)
        self.assertIsNone(audit["official_evidence_web_request_count"])
        self.assertEqual(
            audit["official_evidence_web_request_count_status"],
            "NOT_EXACTLY_ENUMERATED",
        )
        self.assertEqual(status["source_round_operation_counts"]["network_call_count"], 0)
        self.assertEqual(status["source_round_operation_counts"]["filesystem_write_count"], 0)

    def test_19_status_has_zero_cost_and_no_private_material(self) -> None:
        raw = self.module.source_status()
        status = strict_object(raw)
        self.assertEqual(status["authorized_cny"], "0.00")
        self.assertEqual(status["incurred_cny"], "0.00")
        lowered = raw.lower()
        for marker in (
            b"access_key_id",
            b"access_key_secret",
            b"security_token",
            b"refresh_token",
            b"authorization:",
            b"cookie:",
            b"begin private key",
            b".aliyun/config",
            b"ltai",
        ):
            self.assertNotIn(marker, lowered, marker)

    def test_20_canonical_encoder_rejects_nonfinite_nul_oversize_and_bad_types(self) -> None:
        for value, code in (
            ({"x": float("nan")}, "canonical_type"),
            ({"x": float("inf")}, "canonical_type"),
            ({"x": "has\x00nul"}, "canonical_text"),
            ({"x": object()}, "canonical_type"),
            ({1: "bad"}, "canonical_key"),
            ({"x": 2**63}, "canonical_integer"),
            ({"x": "a" * (self.module.MAX_PUBLIC_TEXT_BYTES + 1)}, "canonical_text"),
        ):
            with self.subTest(code=code):
                with self.assertRaisesRegex(ValueError, f"^{code}$"):
                    self.module._canonical_bytes(value)

    def test_21_canonical_encoder_rejects_depth_and_item_limits(self) -> None:
        deep = {"end": True}
        for _ in range(self.module.MAX_JSON_DEPTH + 1):
            deep = {"next": deep}
        with self.assertRaisesRegex(ValueError, "^canonical_depth$"):
            self.module._canonical_bytes(deep)
        oversized = {
            f"k{index}": index
            for index in range(self.module.MAX_JSON_ITEMS + 1)
        }
        with self.assertRaisesRegex(ValueError, "^canonical_items$"):
            self.module._canonical_bytes(oversized)

    def test_22_bootstrap_error_has_fixed_secret_free_surface(self) -> None:
        error = self.module.BootstrapError("caller supplied private value")
        self.assertEqual(error.code, EXPECTED_BOOTSTRAP_STATUS)
        self.assertEqual(str(error), EXPECTED_BOOTSTRAP_STATUS)
        self.assertEqual(repr(error), "BootstrapError('NOT_PROVISIONED')")
        self.assertNotIn("caller supplied", str(error))
        self.assertNotIn("caller supplied", repr(error))

    def test_23_request_bootstrap_refuses_without_inspecting_arguments(self) -> None:
        with self.assertRaises(self.module.BootstrapError) as caught:
            self.module.request_bootstrap(Poison(), keyword=Poison())
        self.assertEqual(caught.exception.code, EXPECTED_BOOTSTRAP_STATUS)

    def test_24_request_bootstrap_first_executable_statement_is_fixed_raise(self) -> None:
        node = function_node(self.tree, "request_bootstrap")
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and type(body[0].value.value) is str
        ):
            body = body[1:]
        self.assertEqual(len(body), 1)
        self.assertIsInstance(body[0], ast.Raise)
        raise_node = body[0]
        self.assertIsInstance(raise_node.exc, ast.Call)
        self.assertIsInstance(raise_node.exc.func, ast.Name)
        self.assertEqual(raise_node.exc.func.id, "BootstrapError")
        self.assertEqual(len(raise_node.exc.args), 1)
        self.assertEqual(raise_node.exc.args[0].value, EXPECTED_BOOTSTRAP_STATUS)

    def test_25_bootstrap_refusal_precedes_filesystem_process_and_network(self) -> None:
        calls = []

        def touched(name):
            def fail(*_args, **_kwargs):
                calls.append(name)
                raise AssertionError(name)
            return fail

        with mock.patch.object(builtins, "open", side_effect=touched("open")), \
             mock.patch.object(os, "open", side_effect=touched("os.open")), \
             mock.patch.object(os, "stat", side_effect=touched("os.stat")), \
             mock.patch.object(os, "lstat", side_effect=touched("os.lstat")), \
             mock.patch.object(os, "read", side_effect=touched("os.read")), \
             mock.patch.object(os, "write", side_effect=touched("os.write")), \
             mock.patch.object(subprocess, "Popen", side_effect=touched("Popen")), \
             mock.patch.object(subprocess, "run", side_effect=touched("run")), \
             mock.patch.object(socket, "socket", side_effect=touched("socket")), \
             mock.patch.object(socket, "socketpair", side_effect=touched("socketpair")), \
             mock.patch.object(urllib.request, "urlopen", side_effect=touched("urlopen")):
            with self.assertRaisesRegex(
                self.module.BootstrapError,
                "^NOT_PROVISIONED$",
            ):
                self.module.request_bootstrap(Poison())
        self.assertEqual(calls, [])

    def test_26_main_refuses_before_argv_and_emits_nothing(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(self.module.main(Poison()), 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_27_main_calls_only_fixed_bootstrap_before_return(self) -> None:
        calls = []

        def refuse():
            calls.append("bootstrap")
            raise self.module.BootstrapError(EXPECTED_BOOTSTRAP_STATUS)

        with mock.patch.object(self.module, "request_bootstrap", side_effect=refuse):
            self.assertEqual(self.module.main(Poison()), 2)
        self.assertEqual(calls, ["bootstrap"])

        node = function_node(self.tree, "main")
        calls_in_main = [item for item in ast.walk(node) if isinstance(item, ast.Call)]
        called_names = {
            item.func.id
            for item in calls_in_main
            if isinstance(item.func, ast.Name)
        }
        self.assertEqual(called_names, {"request_bootstrap"})

    def test_28_source_imports_only_inert_standard_library_modules(self) -> None:
        imports = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertEqual(imports, {"__future__", "json", "types", "typing"})
        forbidden_names = {
            "input",
            "open",
            "print",
            "exec",
            "eval",
            "compile",
            "Popen",
            "run",
            "socket",
            "urlopen",
            "getenv",
        }
        called = {
            node.func.id
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_names.isdisjoint(called))

    def test_29_source_has_no_user_config_environment_or_terminal_path(self) -> None:
        text = self.raw.decode("utf-8")
        for forbidden in (
            "import os",
            "import sys",
            "import socket",
            "import subprocess",
            "http.client",
            "urllib.request",
            "pathlib",
            ".aliyun/config",
            "expanduser(",
            "getenv(",
            "environ[",
            "sys.argv",
            "sys.stdin",
            "sys.stdout",
            "sys.stderr",
            "os.system",
            "subprocess.",
        ):
            self.assertNotIn(forbidden, text)

    def test_30_security_boundaries_do_not_depend_on_assert_or_debug_mode(self) -> None:
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(self.tree)))
        self.assertNotIn("__debug__", self.raw.decode("utf-8"))
        compile(self.raw, str(SOURCE_PATH), "exec", optimize=0)
        compile(self.raw, str(SOURCE_PATH), "exec", optimize=2)

    def test_31_public_surface_is_minimal_and_action_free(self) -> None:
        self.assertEqual(
            self.module.__all__,
            (
                "BootstrapError",
                "assess_stock_cli",
                "main",
                "request_bootstrap",
                "source_status",
                "stock_cli_projection",
            ),
        )
        self.assertFalse(hasattr(self.module, "run_cli"))
        self.assertFalse(hasattr(self.module, "configure_oauth"))
        self.assertFalse(hasattr(self.module, "refresh_oauth"))
        self.assertFalse(hasattr(self.module, "provision_credentials"))

    def test_32_evidence_index_has_exact_public_sources(self) -> None:
        evidence = self.projection()["evidence_index"]
        self.assertEqual(set(evidence), EXPECTED_EVIDENCE_IDS)
        self.assertEqual(
            evidence["UPSTREAM_RELEASE_V3_4_11"],
            {
                "commit": "f54f5fe9caa99723a6324b20eaa60f3de3b049cb",
                "commit_url": (
                    "https://github.com/aliyun/aliyun-cli/commit/"
                    "f54f5fe9caa99723a6324b20eaa60f3de3b049cb"
                ),
                "kind": "OFFICIAL_RELEASE_AND_EXACT_COMMIT",
                "release_url": (
                    "https://github.com/aliyun/aliyun-cli/releases/tag/v3.4.11"
                ),
                "tag": "v3.4.11",
            },
        )
        self.assertEqual(
            evidence["OAUTH_OFFICIAL_DOC"],
            {
                "kind": "SECONDARY_MUTABLE_OFFICIAL_DOCUMENTATION",
                "mutable": True,
                "url": "https://help.aliyun.com/zh/cli/oauth-credentials",
            },
        )
        self.assertEqual(
            evidence["CREDENTIALS_OFFICIAL_DOC"],
            {
                "kind": "SECONDARY_MUTABLE_OFFICIAL_DOCUMENTATION",
                "mutable": True,
                "url": "https://help.aliyun.com/en/cli/configure-credentials/",
            },
        )

    def test_33_commit_pinned_paths_symbols_and_urls_are_exact(self) -> None:
        evidence = self.projection()["evidence_index"]
        commit = "f54f5fe9caa99723a6324b20eaa60f3de3b049cb"
        expected = {
            "BROWSER_PROCESS_EXACT_SOURCE": (
                "util/util.go",
                ["OpenBrowser"],
            ),
            "CONFIG_PATH_ENTRY_EXACT_SOURCE": (
                "config/configure.go",
                ["NewConfigureCommand", "doConfigure", "loadOrCreateConfiguration"],
            ),
            "CONFIG_STORAGE_EXACT_SOURCE": (
                "config/configuration.go",
                [
                    "getConfigurePath",
                    "LoadProfileWithContext",
                    "LoadOrCreateConfiguration",
                    "SaveConfiguration",
                    "SaveConfigurationWithContext",
                    "atomicWriteFileWithRename",
                    "GetConfigPath",
                ],
            ),
            "OAUTH_EXCHANGE_TTL_EXACT_SOURCE": (
                "config/configure.go",
                ["OAuth case", "exchangeFromOAuth", "tryRefreshOauthToken"],
            ),
            "OAUTH_FLOW_EXACT_SOURCE": (
                "config/configure.go",
                [
                    "oauthClientMap",
                    "oauthBaseUrlMap",
                    "signInMap",
                    "configureOAuth",
                    "startOauthFlow",
                ],
            ),
            "PROFILE_REFRESH_EXACT_SOURCE": (
                "config/profile.go",
                [
                    "type Profile",
                    "mergeProfileAfterCredentialRefresh",
                    "(*Profile).GetCredential OAuth case",
                    "(*Profile).GetRuntimeEnv",
                ],
            ),
            "PROFILE_STDOUT_EXACT_SOURCE": (
                "config/configure_get.go",
                ["doConfigureGet"],
            ),
        }
        for evidence_id, (path, symbols) in expected.items():
            with self.subTest(evidence_id=evidence_id):
                row = evidence[evidence_id]
                self.assertEqual(row["kind"], "COMMIT_PINNED_OFFICIAL_SOURCE")
                self.assertEqual(row["commit"], commit)
                self.assertEqual(row["path"], path)
                self.assertEqual(row["symbols"], symbols)
                self.assertEqual(
                    row["url"],
                    f"https://github.com/aliyun/aliyun-cli/blob/{commit}/{path}",
                )
        readme = evidence["EXTERNAL_INGRESS_EXACT_README"]
        self.assertEqual(readme["commit"], commit)
        self.assertEqual(readme["path"], "README.md")
        self.assertEqual(
            readme["section"],
            "Use an external program to get credentials",
        )
        self.assertEqual(
            readme["url"],
            f"https://github.com/aliyun/aliyun-cli/blob/{commit}/README.md",
        )

    def test_34_each_capability_resolves_to_known_evidence(self) -> None:
        projection = self.projection()
        identifiers = projection["capability_evidence_ids"]
        classifications = projection["capability_evidence_classifications"]
        self.assertEqual(identifiers, EXPECTED_CAPABILITY_EVIDENCE_IDS)
        self.assertEqual(set(identifiers), set(EXPECTED_OBSERVED_STOCK))
        self.assertEqual(set(classifications), set(EXPECTED_OBSERVED_STOCK))
        known = set(projection["evidence_index"])
        for capability, evidence_ids in identifiers.items():
            self.assertTrue(evidence_ids, capability)
            self.assertEqual(len(evidence_ids), len(set(evidence_ids)), capability)
            self.assertTrue(set(evidence_ids).issubset(known), capability)
        self.assertEqual(
            classifications["oauth_configure_plugin_required"],
            "INFERENCE_FROM_EXACT_SOURCE",
        )
        self.assertEqual(
            classifications["fd_secret_export"],
            "EXACT_SURFACE_AND_DIRECTION_INFERENCE",
        )

    def test_35_local_identity_is_accepted_ledger_static_not_live(self) -> None:
        projection = self.projection()
        identity = projection["local_cli_identity"]
        evidence = projection["evidence_index"][identity["evidence_id"]]
        self.assertEqual(
            identity["provenance"],
            "ACCEPTED_TRACKED_LEDGER_STATIC_NOT_LIVE_INSPECTION",
        )
        self.assertIs(identity["live_inspection_performed"], False)
        self.assertEqual(
            evidence,
            {
                "kind": "ACCEPTED_TRACKED_LEDGER_STATIC_IDENTITY",
                "live_inspection_performed": False,
                "path": "deploy/production/internal-deployment-readiness.json",
                "record": (
                    "manual_cost_stop_a3_g_terminal_acceptance_aliyun_fd_adapter_"
                    "l_candidate_20260819"
                ),
            },
        )

    def test_36_evidence_maps_are_recursively_immutable(self) -> None:
        with self.assertRaises(TypeError):
            self.module.EVIDENCE_INDEX["OAUTH_FLOW_EXACT_SOURCE"] = {}
        with self.assertRaises(TypeError):
            self.module.EVIDENCE_INDEX["OAUTH_FLOW_EXACT_SOURCE"]["url"] = "x"
        symbols = self.module.EVIDENCE_INDEX["OAUTH_FLOW_EXACT_SOURCE"]["symbols"]
        self.assertIs(type(symbols), tuple)
        with self.assertRaises(TypeError):
            symbols[0] = "x"
        evidence_ids = self.module.CAPABILITY_EVIDENCE_IDS["headless"]
        self.assertIs(type(evidence_ids), tuple)
        with self.assertRaises(TypeError):
            evidence_ids[0] = "x"

    def test_37_candidate_files_are_utf8_secret_free_and_compile(self) -> None:
        test_raw = Path(__file__).read_bytes()
        self.raw.decode("utf-8", "strict")
        test_raw.decode("utf-8", "strict")
        compile(self.raw, str(SOURCE_PATH), "exec")
        compile(test_raw, str(Path(__file__)), "exec")
        patterns = (
            re.compile(b"LTAI" + b"[A-Za-z0-9]{12,}"),
            re.compile(b"BEGIN[ ]PRIVATE[ ]KEY"),
            re.compile(b"security_token[\"']?[ ]*[:=][ ]*[\"'][^\"']+"),
            re.compile(b"access_key_secret[\"']?[ ]*[:=][ ]*[\"'][^\"']+"),
            re.compile(b"refresh_token[\"']?[ ]*[:=][ ]*[\"'][^\"']+"),
        )
        for candidate in (self.raw, test_raw):
            for pattern in patterns:
                self.assertIsNone(pattern.search(candidate), pattern.pattern)


if __name__ == "__main__":
    unittest.main()
