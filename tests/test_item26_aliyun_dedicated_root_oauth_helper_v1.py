from __future__ import annotations

import ast
import builtins
import contextlib
import copy
import hashlib
import hmac
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
SOURCE_PATH = ROOT / "tools" / "item26_aliyun_dedicated_root_oauth_helper_v1.py"
MODULE_NAME = "item26_aliyun_dedicated_root_oauth_helper_v1_test_target"

EXPECTED_SOURCE_SCHEMA = (
    "noteai.item26.aliyun-dedicated-root-oauth-helper-source.v1"
)
EXPECTED_CONTRACT_SCHEMA = (
    "noteai.item26.aliyun-dedicated-root-oauth-helper-contract.v1"
)
EXPECTED_PURE_CORE_SCHEMA = (
    "noteai.item26.aliyun-dedicated-root-oauth-pure-core.v1"
)
EXPECTED_SOURCE_STATUS = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
EXPECTED_BOOTSTRAP_STATUS = "NOT_PROVISIONED"
EXPECTED_ASSESSMENT = (
    "NO_GO_PENDING_DEDICATED_OAUTH_CLIENT_AND_ACTION_AUTHORIZATION"
)

EXPECTED_GATES = {
    "action_authority_acceptance": False,
    "c1_capsule_handoff": False,
    "c2_capture_integration": False,
    "caller_identity_verification": False,
    "dedicated_oauth_client_registration": False,
    "loopback_callback_listener": False,
    "oauth_token_exchange": False,
    "root_custody_creation": False,
    "unprivileged_broker_execution": False,
}

EXPECTED_BLOCKERS = {
    "c1_source_label_successor": {
        "blocking": True,
        "state": "PENDING",
        "required_artifact": "C1_SOURCE_LABEL_SUCCESSOR",
    },
    "c2_fixed_binding_successor": {
        "blocking": True,
        "state": "PENDING",
        "required_artifact": "C2_FIXED_BINDING_SUCCESSOR",
    },
    "dedicated_oauth_client_registration": {
        "blocking": True,
        "state": "ABSENT",
        "required_artifact": "DEDICATED_OAUTH_CLIENT_REGISTRATION_RECEIPT",
    },
    "unprivileged_broker": {
        "blocking": True,
        "state": "PENDING",
        "required_artifact": "UNPRIVILEGED_BROKER_SOURCE_AND_ACCEPTANCE",
    },
}

EXPECTED_ACTION_AUTHORIZATION = {
    "required_receipt": "SEPARATE_ACTION_AUTHORITY_RECEIPT",
    "required_before_any_action": True,
    "receipt_present": False,
    "state": "ABSENT",
}

EXPECTED_OPERATION_KEYS = {
    "argv_read_count",
    "automatic_retry_count",
    "browser_launch_count",
    "c1_capsule_handoff_count",
    "c2_handshake_count",
    "caller_identity_verification_count",
    "callback_accept_count",
    "callback_listener_open_count",
    "capture_count",
    "cleanup_count",
    "client_registration_count",
    "config_read_count",
    "config_write_count",
    "credential_read_count",
    "credential_write_count",
    "database_connection_count",
    "environment_read_count",
    "filesystem_read_count",
    "filesystem_write_count",
    "helper_install_count",
    "helper_process_count",
    "materialization_count",
    "network_call_count",
    "oauth_authorization_count",
    "oauth_token_exchange_count",
    "provider_call_count",
    "root_custody_creation_count",
    "root_read_count",
    "root_write_count",
    "secret_input_count",
    "secret_output_count",
    "stderr_write_count",
    "stdout_write_count",
    "subprocess_count",
    "sudo_dispatch_count",
    "temporary_sts_projection_count",
    "unprivileged_broker_dispatch_count",
}

EXPECTED_PRIOR_RESEARCH = {
    "aliyun_provider_cloud_call_count": 0,
    "generic_historical_filesystem_write_zero_claimed": False,
    "generic_historical_network_zero_claimed": False,
    "homebrew_nonprovider_metadata_network_event_count": 1,
    "homebrew_possible_cache_write_event_count": 1,
    "official_evidence_web_request_count": None,
    "official_evidence_web_request_count_status": "NOT_EXACTLY_ENUMERATED",
    "official_evidence_web_research_performed": True,
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


def fixed_commitment(key: bytes, domain: bytes, value: bytes) -> str:
    message = domain + len(value).to_bytes(8, "big") + value
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def fake_key() -> bytearray:
    return bytearray(range(32))


def assert_scrubbed(test: unittest.TestCase, *values: bytearray) -> None:
    for value in values:
        test.assertTrue(value)
        test.assertEqual(set(value), {0})


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


class Item26AliyunDedicatedRootOauthHelperV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module, cls.raw = load_module()
        cls.tree = ast.parse(cls.raw, filename=str(SOURCE_PATH))

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop(MODULE_NAME, None)

    def contract(self) -> dict[str, object]:
        return strict_object(self.module.helper_contract())

    def status(self) -> dict[str, object]:
        return strict_object(self.module.source_status())

    def test_01_fixed_schemas_statuses_and_assessment(self) -> None:
        self.assertEqual(self.module.SOURCE_SCHEMA, EXPECTED_SOURCE_SCHEMA)
        self.assertEqual(self.module.CONTRACT_SCHEMA, EXPECTED_CONTRACT_SCHEMA)
        self.assertEqual(self.module.PURE_CORE_SCHEMA, EXPECTED_PURE_CORE_SCHEMA)
        self.assertEqual(self.module.SOURCE_ONLY_STATUS, EXPECTED_SOURCE_STATUS)
        self.assertEqual(self.module.BOOTSTRAP_STATUS, EXPECTED_BOOTSTRAP_STATUS)
        self.assertEqual(self.module.ASSESSMENT, EXPECTED_ASSESSMENT)

    def test_02_exact_four_operational_blockers_are_frozen(self) -> None:
        blockers = self.contract()["operational_blockers"]
        self.assertEqual(blockers, EXPECTED_BLOCKERS)
        self.assertEqual(len(blockers), 4)
        self.assertTrue(all(row["blocking"] is True for row in blockers.values()))

    def test_03_separate_action_authority_receipt_is_absent(self) -> None:
        self.assertEqual(
            self.contract()["action_authorization"],
            EXPECTED_ACTION_AUTHORIZATION,
        )
        self.assertEqual(
            self.status()["action_authorization"],
            EXPECTED_ACTION_AUTHORIZATION,
        )

    def test_04_exact_nine_execution_gates_are_bool_false(self) -> None:
        gates = self.status()["execution_gates"]
        self.assertEqual(gates, EXPECTED_GATES)
        self.assertEqual(len(gates), 9)
        self.assertTrue(all(value is False for value in gates.values()))

    def test_05_contract_is_cached_canonical_ascii_with_one_lf(self) -> None:
        raw = self.module.helper_contract()
        self.assertIs(raw, self.module.helper_contract())
        self.assertIs(type(raw), bytes)
        self.assertEqual(raw, canonical(strict_object(raw)))
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))
        self.assertNotIn(b"\x00", raw)
        self.assertEqual(self.contract()["schema"], EXPECTED_CONTRACT_SCHEMA)

    def test_06_status_is_cached_canonical_ascii_with_one_lf(self) -> None:
        raw = self.module.source_status()
        self.assertIs(raw, self.module.source_status())
        self.assertIs(type(raw), bytes)
        self.assertEqual(raw, canonical(strict_object(raw)))
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))
        self.assertNotIn(b"\x00", raw)

    def test_07_c1_exact_seven_is_reference_only_and_not_runnable(self) -> None:
        reference = self.contract()["c1_interface_reference"]
        self.assertEqual(
            reference["interface_schema"],
            "noteai.item26.m1-root-custody-temporary-sts-interface.v1",
        )
        self.assertEqual(
            reference["exact_keys"],
            [
                "account_binding_sha256",
                "credential_payload_exposed",
                "minimum_remaining_validity_seconds",
                "oauth_configure_count",
                "oauth_refresh_count",
                "schema",
                "status",
            ],
        )
        self.assertIs(reference["reference_only"], True)
        self.assertIs(reference["runnable"], False)
        self.assertIs(reference["successor_required"], True)
        self.assertIs(reference["dedicated_helper_source_label_accepted"], False)
        self.assertEqual(
            reference["current_inner_envelope_source"],
            "BRIDGE_PROJECTED_CLI_OAUTH_TEMPORARY_STS",
        )

    def test_08_c2_ready_ack_exact_seven_and_fixed_binding_are_reference_only(self) -> None:
        reference = self.contract()["c2_ready_ack_reference"]
        self.assertEqual(
            tuple(reference),
            (
                "ack_count",
                "ack_status",
                "current_fixed_c1_binding",
                "dedicated_helper_fixed_binding_present",
                "exact_keys",
                "handshake_schema",
                "ready_binding_schema",
                "ready_count",
                "ready_status",
                "reference_only",
                "runnable",
                "successor_required",
            ),
        )
        self.assertEqual(
            reference["handshake_schema"],
            "noteai.item26.m1-c1-capture-handshake.v1",
        )
        self.assertEqual(
            reference["ready_binding_schema"],
            "noteai.item26.m1-c1-ready-binding.v1",
        )
        self.assertEqual(
            reference["exact_keys"],
            [
                "ack_count",
                "capsule_acceptance_revision",
                "capsule_source_revision",
                "projection",
                "ready_sha256",
                "schema",
                "status",
            ],
        )
        self.assertEqual(reference["ready_count"], 0)
        self.assertEqual(reference["ack_count"], 1)
        self.assertEqual(
            reference["ready_status"],
            "ROOT_CUSTODY_TEMPORARY_STS_READY_FOR_CAPTURE_ACK",
        )
        self.assertEqual(
            reference["ack_status"],
            "ROOT_CUSTODY_TEMPORARY_STS_CAPTURE_ACKNOWLEDGED",
        )
        self.assertIs(reference["reference_only"], True)
        self.assertIs(reference["runnable"], False)
        self.assertIs(reference["successor_required"], True)
        self.assertIs(reference["dedicated_helper_fixed_binding_present"], False)
        self.assertEqual(
            reference["current_fixed_c1_binding"],
            {
                "acceptance_revision": "314a6b885bc7bda9790074a201ac176e498326b5",
                "bytes": 49_494,
                "file_sha256": (
                    "7ed50fd5acdbb5733a174367e8bcb339b3a6bc07b49fed3a31243fddf763e4e3"
                ),
                "git_blob_oid": "99110863d055929fbc76950ec2bc9aa8fd0f7bc6",
                "source_ref": "tools/item26_aliyun_temporary_sts_capsule_v1.py",
                "source_revision": "86206f816fb092a7fca7a577b1391e251dfca5ca",
            },
        )

    def test_09_pure_core_contract_separates_oauth_and_sts_ttl(self) -> None:
        pure = self.contract()["pure_core"]
        self.assertEqual(pure["schema"], EXPECTED_PURE_CORE_SCHEMA)
        self.assertEqual(pure["token_contract"]["minimum_validity_seconds"], 60)
        self.assertEqual(pure["token_contract"]["maximum_validity_seconds"], 86_400)
        self.assertEqual(
            pure["token_contract"]["token_type_input"],
            "CALLER_OWNED_BYTEARRAY_EXACT_BEARER",
        )
        self.assertEqual(
            pure["callback_contract"]["authorization_code_binding"],
            "DOMAIN_SEPARATED_HMAC_SHA256",
        )
        sts = pure["temporary_sts_contract"]
        self.assertEqual(sts["initial_minimum_remaining_seconds"], 1_860)
        self.assertEqual(sts["per_begin_minimum_remaining_seconds"], 960)
        self.assertEqual(sts["maximum_remaining_seconds"], 86_400)
        self.assertEqual(
            sts["per_begin_validation"],
            {
                "implemented_by_c4_s": False,
                "required_component": (
                    "C1_SOURCE_LABEL_AND_C2_FIXED_BINDING_SUCCESSORS"
                ),
                "status": "FUTURE_C1_CAPSULE_REQUIRED",
            },
        )
        self.assertEqual(
            sts["caller_identity_completion_requirement"],
            "FUTURE_ACTION_ORCHESTRATOR_REQUIRED",
        )
        self.assertEqual(
            sts["credential_envelope_sha256_stability_requirement"],
            "REQUIRED_NOT_VERIFIED_BY_C4_S",
        )
        self.assertEqual(
            sts["account_binding_input_validation"],
            "LOWER_HEX_64_SHAPE_ONLY",
        )
        self.assertIs(sts["successor_envelope_source_required"], True)

    def test_10_future_runtime_broker_and_portability_requirements_are_inert(self) -> None:
        future = self.contract()["future_action_requirements"]
        self.assertIsNone(future["browser_managed_provider_request_count"])
        self.assertEqual(
            future["browser_managed_provider_request_count_status"],
            "NOT_OBSERVABLE",
        )
        self.assertEqual(
            future["browser_url_transport"],
            "ONE_SHOT_ANONYMOUS_BLOCKING_FD",
        )
        self.assertIs(future["browser_url_in_argv"], False)
        self.assertIs(future["browser_url_in_environment"], False)
        self.assertEqual(
            future["dedicated_runtime_inventory_relationship"],
            "INDEPENDENT_SIBLING_NOT_C1_INVENTORY",
        )
        self.assertEqual(
            future["darwin_anonymous_unix_socket_device_normalization"],
            "FUTURE_ACTION_ADAPTER_REQUIRED",
        )
        self.assertEqual(
            future["replay_protection"],
            "FUTURE_ROOT_TRANSACTION_STATE_REQUIRED",
        )

    def test_11_status_exact_shape_is_source_only_and_embeds_contract(self) -> None:
        status = self.status()
        self.assertEqual(
            set(status),
            {
                "action_authorization",
                "assessment",
                "authorizes_execution",
                "authorized_cny",
                "bootstrap_status",
                "execution_gates",
                "helper_contract",
                "implementation_complete",
                "implementation_completion_scope",
                "incurred_cny",
                "operational_blockers",
                "operational_ready",
                "prior_research_audit",
                "pure_validation_invocation_accounting",
                "schema",
                "source_round_operation_count_scope",
                "source_round_operation_count_scope_detail",
                "source_round_operation_counts",
                "status",
            },
        )
        self.assertEqual(status["schema"], EXPECTED_SOURCE_SCHEMA)
        self.assertEqual(status["status"], EXPECTED_SOURCE_STATUS)
        self.assertEqual(status["assessment"], EXPECTED_ASSESSMENT)
        self.assertEqual(status["bootstrap_status"], EXPECTED_BOOTSTRAP_STATUS)
        self.assertIs(status["implementation_complete"], True)
        self.assertEqual(
            status["implementation_completion_scope"],
            "C4_S_PURE_VALIDATION_AND_INERT_CONTRACT_ONLY",
        )
        self.assertIs(status["authorizes_execution"], False)
        self.assertIs(status["operational_ready"], False)
        self.assertEqual(status["helper_contract"], self.contract())

    def test_12_action_counts_have_narrow_scope_and_exact_integer_zero(self) -> None:
        status = self.status()
        self.assertEqual(
            status["source_round_operation_count_scope"],
            "IMPORT_AND_INERT_REQUEST_MAIN_ONLY",
        )
        self.assertEqual(
            status["source_round_operation_count_scope_detail"],
            "PURE_VALIDATOR_INVOCATIONS_EXCLUDED_AND_NOT_RECORDED",
        )
        self.assertEqual(
            status["pure_validation_invocation_accounting"],
            "STATELESS_NOT_RECORDED",
        )
        counts = status["source_round_operation_counts"]
        self.assertEqual(set(counts), EXPECTED_OPERATION_KEYS)
        for key, value in counts.items():
            self.assertTrue(key.endswith("_count"), key)
            self.assertIs(type(value), int, key)
            self.assertEqual(value, 0, key)

    def test_13_prior_research_and_homebrew_history_are_honest(self) -> None:
        audit = self.status()["prior_research_audit"]
        self.assertEqual(audit, EXPECTED_PRIOR_RESEARCH)
        self.assertIs(audit["generic_historical_network_zero_claimed"], False)
        self.assertIs(
            audit["generic_historical_filesystem_write_zero_claimed"],
            False,
        )
        self.assertIs(audit["official_evidence_web_research_performed"], True)
        self.assertIsNone(audit["official_evidence_web_request_count"])
        self.assertEqual(audit["homebrew_nonprovider_metadata_network_event_count"], 1)
        self.assertEqual(audit["homebrew_possible_cache_write_event_count"], 1)
        self.assertEqual(audit["aliyun_provider_cloud_call_count"], 0)

    def test_14_zero_cost_status_and_contract_are_secret_free(self) -> None:
        status = self.status()
        self.assertEqual(status["authorized_cny"], "0.00")
        self.assertEqual(status["incurred_cny"], "0.00")
        combined = self.module.helper_contract() + self.module.source_status()
        lowered = combined.lower()
        for marker in (
            b"authorization: bearer ",
            b"cookie:",
            b"begin private key",
            b".aliyun/config",
            b"ltai",
        ):
            self.assertNotIn(marker, lowered, marker)

    def test_15_public_maps_are_immutable_and_cached_bytes_ignore_rebind(self) -> None:
        contract_before = self.module.helper_contract()
        status_before = self.module.source_status()
        with self.assertRaises(TypeError):
            self.module.EXECUTION_GATES["root_custody_creation"] = True
        with self.assertRaises(TypeError):
            self.module.OPERATIONAL_BLOCKERS["unprivileged_broker"]["state"] = "READY"
        with mock.patch.object(self.module, "EXECUTION_GATES", {"unsafe": True}), \
             mock.patch.object(self.module, "OPERATIONAL_BLOCKERS", {}):
            self.assertIs(self.module.helper_contract(), contract_before)
            self.assertIs(self.module.source_status(), status_before)
        self.assertIs(copy.copy(contract_before), contract_before)
        self.assertIs(copy.deepcopy(status_before), status_before)

    def test_16_canonical_encoder_rejects_bad_public_values(self) -> None:
        cases = (
            ({"x": float("nan")}, "canonical_type"),
            ({"x": float("inf")}, "canonical_type"),
            ({"x": "nul\x00text"}, "canonical_text"),
            ({"x": object()}, "canonical_type"),
            ({1: "bad"}, "canonical_key"),
            ({"x": 2**63}, "canonical_integer"),
            ({"x": "a" * (self.module.MAX_PUBLIC_TEXT_BYTES + 1)}, "canonical_text"),
        )
        for value, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(
                    self.module.DedicatedRootOauthHelperError,
                    f"^{code}$",
                ):
                    self.module._canonical_bytes(value)

    def test_17_canonical_encoder_rejects_depth_items_and_size(self) -> None:
        deep = {"end": True}
        for _ in range(self.module.MAX_JSON_DEPTH + 1):
            deep = {"next": deep}
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^canonical_depth$",
        ):
            self.module._canonical_bytes(deep)
        oversized_items = {
            f"k{index}": index
            for index in range(self.module.MAX_JSON_ITEMS + 1)
        }
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^canonical_items$",
        ):
            self.module._canonical_bytes(oversized_items)
        with mock.patch.object(self.module, "MAX_CANONICAL_BYTES", 2):
            with self.assertRaisesRegex(
                self.module.DedicatedRootOauthHelperError,
                "^canonical_size$",
            ):
                self.module._canonical_bytes({"x": 1})

    def test_18_fixed_error_surface_never_includes_caller_text(self) -> None:
        error = self.module.DedicatedRootOauthHelperError("private caller marker")
        self.assertEqual(error.code, "helper_internal")
        self.assertEqual(str(error), "helper_internal")
        self.assertEqual(
            repr(error),
            "DedicatedRootOauthHelperError(<fixed-code>)",
        )
        self.assertNotIn("private caller marker", str(error))
        self.assertNotIn("private caller marker", repr(error))

    def test_19_request_refuses_without_inspecting_arguments(self) -> None:
        with self.assertRaises(self.module.DedicatedRootOauthHelperError) as caught:
            self.module.request_bootstrap(Poison(), keyword=Poison())
        self.assertEqual(caught.exception.code, EXPECTED_BOOTSTRAP_STATUS)

    def test_20_request_first_and_only_executable_statement_is_fixed_raise(self) -> None:
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
        raised = body[0].exc
        self.assertIsInstance(raised, ast.Call)
        self.assertIsInstance(raised.func, ast.Name)
        self.assertEqual(raised.func.id, "DedicatedRootOauthHelperError")
        self.assertEqual(len(raised.args), 1)
        self.assertEqual(raised.args[0].value, EXPECTED_BOOTSTRAP_STATUS)

    def test_21_request_refusal_precedes_filesystem_process_and_network(self) -> None:
        calls = []

        def touched(name):
            def fail(*_args, **_kwargs):
                calls.append(name)
                raise AssertionError(name)
            return fail

        with mock.patch.object(builtins, "open", side_effect=touched("open")), \
             mock.patch.object(os, "open", side_effect=touched("os.open")), \
             mock.patch.object(os, "stat", side_effect=touched("os.stat")), \
             mock.patch.object(subprocess, "Popen", side_effect=touched("Popen")), \
             mock.patch.object(subprocess, "run", side_effect=touched("run")), \
             mock.patch.object(socket, "socket", side_effect=touched("socket")), \
             mock.patch.object(urllib.request, "urlopen", side_effect=touched("urlopen")):
            with self.assertRaisesRegex(
                self.module.DedicatedRootOauthHelperError,
                "^NOT_PROVISIONED$",
            ):
                self.module.request_bootstrap(Poison())
        self.assertEqual(calls, [])

    def test_22_main_refuses_before_argv_and_emits_nothing(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(self.module.main(Poison()), 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_23_main_calls_only_request_once(self) -> None:
        calls = []

        def refuse():
            calls.append("request")
            raise self.module.DedicatedRootOauthHelperError("NOT_PROVISIONED")

        with mock.patch.object(self.module, "request_bootstrap", side_effect=refuse):
            self.assertEqual(self.module.main(Poison()), 2)
        self.assertEqual(calls, ["request"])
        node = function_node(self.tree, "main")
        called_names = {
            item.func.id
            for item in ast.walk(node)
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
        }
        self.assertEqual(called_names, {"request_bootstrap"})

    def test_24_public_surface_is_minimal_and_has_no_action_leaf(self) -> None:
        self.assertEqual(
            self.module.__all__,
            (
                "DedicatedRootOauthHelperError",
                "helper_contract",
                "main",
                "request_bootstrap",
                "scrub_bytearray",
                "source_status",
            ),
        )
        for name in (
            "install_root_helper",
            "launch_browser",
            "listen_callback",
            "register_oauth_client",
            "request_caller_identity",
            "run_oauth",
            "stage_root_custody",
            "exchange_token",
        ):
            self.assertFalse(hasattr(self.module, name), name)

    def test_25_source_imports_only_action_free_standard_library_modules(self) -> None:
        imports = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertEqual(
            imports,
            {"__future__", "dataclasses", "hashlib", "hmac", "json", "types", "typing"},
        )
        top_level_functions = {
            node.name
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertEqual(
            top_level_functions,
            {
                "_account_binding",
                "_base64url_no_padding",
                "_canonical_bytes",
                "_deep_freeze",
                "_domain_commitment",
                "_helper_contract_object",
                "_hex_nibble",
                "_is_exact_int",
                "_is_lower_hex",
                "_is_nonnegative_canonical_int",
                "_percent_decode_callback_range",
                "_plain_public",
                "_reject_private_aliases",
                "_require_owned_buffer",
                "_source_status_object",
                "_validate_callback_query",
                "_validate_identity_binding",
                "_validate_json_value",
                "_validate_pkce_pair",
                "_validate_temporary_sts_material",
                "_validate_token_material",
                "helper_contract",
                "main",
                "request_bootstrap",
                "scrub_bytearray",
                "source_status",
            },
        )
        top_level_classes = {
            node.name
            for node in self.tree.body
            if isinstance(node, ast.ClassDef)
        }
        self.assertEqual(
            top_level_classes,
            {
                "DedicatedRootOauthHelperError",
                "_CallbackSummary",
                "_IdentityBindingSummary",
                "_TemporaryStsSummary",
                "_TokenSummary",
            },
        )
        forbidden_normalized_leaves = {
            "accept",
            "bind",
            "builtins",
            "compile",
            "connect",
            "delattr",
            "dump",
            "environ",
            "eval",
            "exec",
            "getattr",
            "getattribute",
            "getenv",
            "globals",
            "input",
            "listen",
            "load",
            "load_module",
            "locals",
            "lstat",
            "mkdir",
            "open",
            "popen",
            "print",
            "read",
            "recv",
            "remove",
            "rmdir",
            "run",
            "send",
            "setattr",
            "socket",
            "socketpair",
            "stat",
            "subclasses",
            "system",
            "unlink",
            "urlopen",
            "vars",
            "write",
        }
        normalized_names = {
            node.id.strip("_").lower()
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Name)
        }
        normalized_attributes = {
            node.attr.strip("_").lower()
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Attribute)
        }
        normalized_function_names = {
            node.name.strip("_").lower()
            for node in ast.walk(self.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        exact_names_and_attributes = {
            node.id
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Name)
        } | {
            node.attr
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertTrue(forbidden_normalized_leaves.isdisjoint(normalized_names))
        self.assertTrue(
            forbidden_normalized_leaves.isdisjoint(normalized_attributes)
        )
        self.assertTrue(
            forbidden_normalized_leaves.isdisjoint(normalized_function_names)
        )
        self.assertNotIn("__import__", exact_names_and_attributes)
        direct_calls = {
            node.func.id
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertEqual(
            direct_calls,
            {
                "DedicatedRootOauthHelperError",
                "MappingProxyType",
                "SystemExit",
                "TypeError",
                "_CallbackSummary",
                "_IdentityBindingSummary",
                "_TemporaryStsSummary",
                "_TokenSummary",
                "_account_binding",
                "_base64url_no_padding",
                "_canonical_bytes",
                "_deep_freeze",
                "_domain_commitment",
                "_helper_contract_object",
                "_hex_nibble",
                "_is_exact_int",
                "_is_lower_hex",
                "_is_nonnegative_canonical_int",
                "_percent_decode_callback_range",
                "_plain_public",
                "_reject_private_aliases",
                "_require_owned_buffer",
                "_source_status_object",
                "_validate_json_value",
                "all",
                "any",
                "bool",
                "bytearray",
                "dataclass",
                "enumerate",
                "frozenset",
                "isinstance",
                "len",
                "main",
                "range",
                "request_bootstrap",
                "scrub_bytearray",
                "super",
                "tuple",
                "type",
            },
        )
        attribute_calls = {
            node.func.attr
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertEqual(
            attribute_calls,
            {
                "__init__",
                "append",
                "compare_digest",
                "decode",
                "digest",
                "dumps",
                "encode",
                "extend",
                "find",
                "hexdigest",
                "isalnum",
                "isascii",
                "items",
                "new",
                "sha256",
                "startswith",
                "to_bytes",
            },
        )
        module_assignment_names = []
        module_assignment_values = []
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                self.assertEqual(len(node.targets), 1)
                self.assertIsInstance(node.targets[0], ast.Name)
                module_assignment_names.append(node.targets[0].id)
                module_assignment_values.append(node.value)
            else:
                self.assertNotIsInstance(node, ast.AnnAssign)
        self.assertEqual(
            tuple(module_assignment_names),
            (
                "SOURCE_SCHEMA",
                "CONTRACT_SCHEMA",
                "PURE_CORE_SCHEMA",
                "SOURCE_ONLY_STATUS",
                "BOOTSTRAP_STATUS",
                "ASSESSMENT",
                "C1_INTERFACE_SCHEMA",
                "C1_READY_STATUS",
                "C1_CURRENT_INNER_ENVELOPE_SOURCE",
                "C1_ACCOUNT_BINDING_SCHEMA",
                "C2_HANDSHAKE_SCHEMA",
                "C2_READY_BINDING_SCHEMA",
                "C2_READY_STATUS",
                "C2_ACK_STATUS",
                "C2_CURRENT_C1_SOURCE_REF",
                "C2_CURRENT_C1_SOURCE_REVISION",
                "C2_CURRENT_C1_ACCEPTANCE_REVISION",
                "C2_CURRENT_C1_GIT_BLOB_OID",
                "C2_CURRENT_C1_FILE_SHA256",
                "C2_CURRENT_C1_BYTES",
                "MAX_CANONICAL_BYTES",
                "MAX_JSON_DEPTH",
                "MAX_JSON_ITEMS",
                "MAX_PUBLIC_TEXT_BYTES",
                "MIN_PKCE_VERIFIER_BYTES",
                "MAX_PKCE_VERIFIER_BYTES",
                "PKCE_S256_CHALLENGE_BYTES",
                "MAX_CALLBACK_QUERY_BYTES",
                "MIN_AUTHORIZATION_CODE_BYTES",
                "MAX_AUTHORIZATION_CODE_BYTES",
                "MIN_STATE_BYTES",
                "MAX_STATE_BYTES",
                "MIN_TOKEN_BYTES",
                "MAX_TOKEN_BYTES",
                "MIN_COMMITMENT_KEY_BYTES",
                "MAX_COMMITMENT_KEY_BYTES",
                "MAX_IDENTITY_BYTES",
                "MIN_TOKEN_VALIDITY_SECONDS",
                "MAX_TOKEN_VALIDITY_SECONDS",
                "INITIAL_MINIMUM_STS_SECONDS",
                "PER_BEGIN_MINIMUM_STS_SECONDS",
                "MAXIMUM_STS_SECONDS",
                "MAX_SECURITY_TOKEN_BYTES",
                "DEDICATED_RUNTIME_ROOT",
                "SOURCE_ROUND_OPERATION_COUNT_SCOPE",
                "_STATE_DOMAIN",
                "_AUTHORIZATION_CODE_DOMAIN",
                "_ACCESS_TOKEN_DOMAIN",
                "_REFRESH_TOKEN_DOMAIN",
                "_ACCOUNT_DOMAIN",
                "_PRINCIPAL_DOMAIN",
                "_STS_ACCESS_KEY_ID_DOMAIN",
                "_STS_ACCESS_KEY_SECRET_DOMAIN",
                "_STS_SECURITY_TOKEN_DOMAIN",
                "_STS_MATERIAL_BINDING_SCHEMA",
                "_BASE64URL_ALPHABET",
                "OPERATIONAL_BLOCKERS",
                "ACTION_AUTHORIZATION",
                "EXECUTION_GATES",
                "SOURCE_ROUND_OPERATION_COUNTS",
                "PRIOR_RESEARCH_AUDIT",
                "__all__",
                "_ERROR_CODES",
                "_HELPER_CONTRACT_BYTES",
                "_SOURCE_STATUS_BYTES",
            ),
        )
        self.assertFalse(any(isinstance(node, ast.Lambda) for node in ast.walk(self.tree)))
        self.assertFalse(any(isinstance(node, ast.NamedExpr) for node in ast.walk(self.tree)))
        self.assertFalse(
            any(
                isinstance(item, ast.Attribute)
                for value in module_assignment_values
                for item in ast.walk(value)
            )
        )
        self.assertEqual(
            {
                name
                for name, value in self.module.__dict__.items()
                if callable(value)
            },
            {
                "Any",
                "DedicatedRootOauthHelperError",
                "Mapping",
                "MappingProxyType",
                "NoReturn",
                "_CallbackSummary",
                "_IdentityBindingSummary",
                "_TemporaryStsSummary",
                "_TokenSummary",
                "_account_binding",
                "_base64url_no_padding",
                "_canonical_bytes",
                "_deep_freeze",
                "_domain_commitment",
                "_helper_contract_object",
                "_hex_nibble",
                "_is_exact_int",
                "_is_lower_hex",
                "_is_nonnegative_canonical_int",
                "_percent_decode_callback_range",
                "_plain_public",
                "_reject_private_aliases",
                "_require_owned_buffer",
                "_source_status_object",
                "_validate_callback_query",
                "_validate_identity_binding",
                "_validate_json_value",
                "_validate_pkce_pair",
                "_validate_temporary_sts_material",
                "_validate_token_material",
                "dataclass",
                "helper_contract",
                "main",
                "request_bootstrap",
                "scrub_bytearray",
                "source_status",
            },
        )
        alias_contracts = {
            "_validate_callback_query": (
                "callback_contract",
                ("query", "state_commitment_key"),
            ),
            "_validate_identity_binding": (
                "identity_contract",
                (
                    "account_identity",
                    "principal_identity",
                    "identity_commitment_key",
                ),
            ),
            "_validate_temporary_sts_material": (
                "sts_contract",
                (
                    "access_key_id",
                    "access_key_secret",
                    "security_token",
                    "material_commitment_key",
                ),
            ),
            "_validate_token_material": (
                "token_contract",
                (
                    "access_token",
                    "refresh_token",
                    "token_type",
                    "token_commitment_key",
                ),
            ),
        }
        for function_name, (error_code, expected_arguments) in alias_contracts.items():
            function = function_node(self.tree, function_name)
            calls = [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_reject_private_aliases"
            ]
            self.assertEqual(len(calls), 1, function_name)
            self.assertIsInstance(calls[0].args[0], ast.Constant)
            self.assertEqual(calls[0].args[0].value, error_code)
            self.assertEqual(
                tuple(
                    argument.id
                    for argument in calls[0].args[1:]
                    if isinstance(argument, ast.Name)
                ),
                expected_arguments,
            )
            self.assertEqual(len(calls[0].args), len(expected_arguments) + 1)

    def test_26_source_has_no_action_capable_names_or_paths(self) -> None:
        text = self.raw.decode("utf-8")
        for forbidden in (
            "import os",
            "import sys",
            "import socket",
            "import subprocess",
            "import secrets",
            "import urllib",
            "import webbrowser",
            "http.client",
            "pathlib",
            "tempfile",
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
            "json.loads(",
            "base64.urlsafe_b64encode",
        ):
            self.assertNotIn(forbidden, text)

    def test_27_security_boundaries_ignore_assert_and_optimization(self) -> None:
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(self.tree)))
        self.assertNotIn("__debug__", self.raw.decode("utf-8"))
        compile(self.raw, str(SOURCE_PATH), "exec", optimize=0)
        compile(self.raw, str(SOURCE_PATH), "exec", optimize=2)

    def test_28_pkce_rfc7636_s256_vector_matches_and_scrubs(self) -> None:
        verifier = bytearray(
            b"dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        )
        challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        self.assertEqual(
            self.module._validate_pkce_pair(verifier, challenge),
            challenge,
        )
        assert_scrubbed(self, verifier)

    def test_29_pkce_minimum_and_maximum_lengths_are_exact(self) -> None:
        for length in (43, 128):
            with self.subTest(length=length):
                raw = b"a" * length
                verifier = bytearray(raw)
                digest = hashlib.sha256(raw).digest()
                import base64
                challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
                self.assertEqual(
                    self.module._validate_pkce_pair(verifier, challenge),
                    challenge,
                )
                self.assertNotIn("=", challenge)
                self.assertEqual(len(challenge), 43)
                assert_scrubbed(self, verifier)

    def test_30_pkce_bad_shape_mismatch_and_padding_scrub_every_path(self) -> None:
        cases = (
            (bytearray(b"a" * 42), "a" * 43, "pkce_shape"),
            (bytearray(b"a" * 129), "a" * 43, "pkce_shape"),
            (bytearray(b"a" * 42 + b"!"), "a" * 43, "pkce_shape"),
            (bytearray(b"a" * 43), "a" * 42 + "=", "pkce_shape"),
            (bytearray(b"a" * 43), "a" * 43, "pkce_mismatch"),
        )
        for verifier, expected, code in cases:
            with self.subTest(code=code, length=len(verifier)):
                with self.assertRaisesRegex(
                    self.module.DedicatedRootOauthHelperError,
                    f"^{code}$",
                ):
                    self.module._validate_pkce_pair(verifier, expected)
                assert_scrubbed(self, verifier)

    def test_31_pkce_rejects_non_bytearray_without_formatting_it(self) -> None:
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^pkce_shape$",
        ):
            self.module._validate_pkce_pair(Poison(), "a" * 43)

    def test_32_callback_query_success_is_secret_free_and_scrubs(self) -> None:
        code = b"FAKE-CODE-FOR-UNIT-TEST-001"
        state = b"fake-state-for-unit-test-001"
        key_raw = bytes(range(32))
        expected = fixed_commitment(
            key_raw,
            b"noteai.item26.dedicated-root-oauth-state.v1\x00",
            state,
        )
        query = bytearray(b"code=" + code + b"&state=" + state)
        key = bytearray(key_raw)
        summary = self.module._validate_callback_query(
            query,
            state_commitment_key=key,
            expected_state_commitment_hmac_sha256=expected,
        )
        self.assertIs(summary.authorization_code_present, True)
        self.assertEqual(summary.parameter_count, 2)
        self.assertEqual(summary.state_commitment_hmac_sha256, expected)
        self.assertEqual(
            summary.authorization_code_commitment_hmac_sha256,
            fixed_commitment(
                key_raw,
                b"noteai.item26.dedicated-root-oauth-authorization-code.v1\x00",
                code,
            ),
        )
        self.assertNotIn(code.decode("ascii"), repr(summary))
        self.assertNotIn(state.decode("ascii"), repr(summary))
        assert_scrubbed(self, query, key)

    def test_33_callback_percent_decoding_and_parameter_order_are_strict_safe(self) -> None:
        code = b"FAKE-CODE-FOR-UNIT-TEST-002"
        state = b"fake-state_for~unit-test-002"
        key_raw = bytes(reversed(range(32)))
        expected = fixed_commitment(
            key_raw,
            b"noteai.item26.dedicated-root-oauth-state.v1\x00",
            state,
        )
        query = bytearray(
            b"state=fake-state_for%7Eunit-test-002&code=" + code
        )
        key = bytearray(key_raw)
        summary = self.module._validate_callback_query(
            query,
            state_commitment_key=key,
            expected_state_commitment_hmac_sha256=expected,
        )
        self.assertEqual(summary.state_commitment_hmac_sha256, expected)
        assert_scrubbed(self, query, key)

    def test_34_callback_state_mismatch_is_fixed_and_scrubs(self) -> None:
        query = bytearray(
            b"code=FAKE-CODE-FOR-UNIT-TEST-003&state=fake-state-for-test-003"
        )
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^callback_state_mismatch$",
        ):
            self.module._validate_callback_query(
                query,
                state_commitment_key=key,
                expected_state_commitment_hmac_sha256="0" * 64,
            )
        assert_scrubbed(self, query, key)

    def test_35_callback_rejects_duplicate_extra_error_plus_and_bad_percent(self) -> None:
        cases = (
            b"code=FAKE-CODE-FOR-TEST-0001&code=FAKE-CODE-FOR-TEST-0002",
            b"code=FAKE-CODE-FOR-TEST-0003&state=fake-state-for-test-0003&x=y",
            b"error=denied&state=fake-state-for-test-0004",
            b"code=FAKE+CODE+FOR+TEST+0005&state=fake-state-for-test-0005",
            b"code=FAKE-CODE-FOR-TEST-0006&state=bad%2",
            b"code=FAKE-CODE-FOR-TEST-0007&state=bad%XX",
            b"code=FAKE-CODE-FOR-TEST-0008&state=bad%+A",
            b"code=FAKE-CODE-FOR-TEST-0009&state=bad%-1",
            b"code=FAKE-CODE-FOR-TEST-0010&state=fake-state-for-test-0010&",
        )
        for raw in cases:
            with self.subTest(shape=raw.count(b"&")):
                query = bytearray(raw)
                key = fake_key()
                with self.assertRaisesRegex(
                    self.module.DedicatedRootOauthHelperError,
                    "^callback_contract$",
                ):
                    self.module._validate_callback_query(
                        query,
                        state_commitment_key=key,
                        expected_state_commitment_hmac_sha256="0" * 64,
                )
                assert_scrubbed(self, query, key)

        encoded = bytearray(b"decoded-prefix%41")
        output = bytearray()
        with mock.patch.object(
            self.module,
            "_hex_nibble",
            side_effect=KeyboardInterrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.module._percent_decode_callback_range(
                    encoded,
                    0,
                    len(encoded),
                    output,
                )
        self.assertEqual(len(output), len(b"decoded-prefix"))
        self.assertEqual(set(output), {0})

        query = bytearray(
            b"code=FAKE-CODE-ALLOCATION-INTERRUPT&"
            b"state=fake-state-allocation-interrupt"
        )
        key = fake_key()
        locally_allocated = bytearray(b"fake-local-decoded-copy")
        real_bytearray = bytearray
        allocation_calls = 0

        def interrupt_second_secret_allocation():
            nonlocal allocation_calls
            allocation_calls += 1
            if allocation_calls == 1:
                return locally_allocated
            raise KeyboardInterrupt

        def exact_scrub(value):
            if type(value) is real_bytearray:
                value[:] = b"\x00" * len(value)

        with mock.patch.object(
            self.module,
            "bytearray",
            side_effect=interrupt_second_secret_allocation,
            create=True,
        ), mock.patch.object(
            self.module,
            "scrub_bytearray",
            side_effect=exact_scrub,
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.module._validate_callback_query(
                    query,
                    state_commitment_key=key,
                    expected_state_commitment_hmac_sha256="0" * 64,
                )
        self.assertEqual(allocation_calls, 2)
        assert_scrubbed(self, query, key, locally_allocated)

    def test_36_callback_rejects_alias_bad_digest_and_oversize_with_scrub(self) -> None:
        alias = bytearray(b"x" * 32)
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^callback_contract$",
        ):
            self.module._validate_callback_query(
                alias,
                state_commitment_key=alias,
                expected_state_commitment_hmac_sha256="0" * 64,
            )
        assert_scrubbed(self, alias)

        query = bytearray(b"code=" + b"c" * 20 + b"&state=" + b"s" * 20)
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^callback_contract$",
        ):
            self.module._validate_callback_query(
                query,
                state_commitment_key=key,
                expected_state_commitment_hmac_sha256="A" * 64,
            )
        assert_scrubbed(self, query, key)

        node = function_node(self.tree, "_validate_callback_query")
        self.assertFalse(
            any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr in {"split", "decode"}
                for item in ast.walk(node)
            )
        )
        self.assertFalse(
            any(
                isinstance(item, ast.Subscript)
                and isinstance(item.value, ast.Name)
                and item.value.id in {"query", "owned_query"}
                and isinstance(item.slice, ast.Slice)
                for item in ast.walk(node)
            )
        )

        query = bytearray(b"q" * (self.module.MAX_CALLBACK_QUERY_BYTES + 1))
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^callback_contract$",
        ):
            self.module._validate_callback_query(
                query,
                state_commitment_key=key,
                expected_state_commitment_hmac_sha256="0" * 64,
            )
        assert_scrubbed(self, query, key)

    def test_37_token_material_success_has_domain_separated_commitments(self) -> None:
        access_raw = b"fake-access-token-for-unit-test-001"
        refresh_raw = b"fake-refresh-token-for-unit-test-001"
        key_raw = bytes(range(32))
        access = bytearray(access_raw)
        refresh = bytearray(refresh_raw)
        token_type = bytearray(b"Bearer")
        key = bytearray(key_raw)
        summary = self.module._validate_token_material(
            access_token=access,
            refresh_token=refresh,
            token_type=token_type,
            token_commitment_key=key,
            issued_at_unix=1_000,
            expires_in_seconds=3_600,
            now_unix=1_001,
        )
        self.assertEqual(summary.token_type, "Bearer")
        self.assertEqual(summary.expiration_unix, 4_600)
        self.assertEqual(summary.remaining_seconds, 3_599)
        self.assertEqual(
            summary.access_token_commitment_hmac_sha256,
            fixed_commitment(
                key_raw,
                b"noteai.item26.dedicated-root-oauth-access-token.v1\x00",
                access_raw,
            ),
        )
        self.assertEqual(
            summary.refresh_token_commitment_hmac_sha256,
            fixed_commitment(
                key_raw,
                b"noteai.item26.dedicated-root-oauth-refresh-token.v1\x00",
                refresh_raw,
            ),
        )
        self.assertNotEqual(
            summary.access_token_commitment_hmac_sha256,
            summary.refresh_token_commitment_hmac_sha256,
        )
        self.assertNotIn(access_raw.decode("ascii"), repr(summary))
        self.assertNotIn(refresh_raw.decode("ascii"), repr(summary))
        assert_scrubbed(self, access, refresh, token_type, key)

    def test_38_token_validity_exact_bounds_accept_int_not_bool(self) -> None:
        for expires in (60, 86_400):
            with self.subTest(expires=expires):
                access = bytearray(b"fake-access-token-boundary")
                refresh = bytearray(b"fake-refresh-token-boundary")
                token_type = bytearray(b"Bearer")
                key = fake_key()
                summary = self.module._validate_token_material(
                    access_token=access,
                    refresh_token=refresh,
                    token_type=token_type,
                    token_commitment_key=key,
                    issued_at_unix=2_000,
                    expires_in_seconds=expires,
                    now_unix=2_000,
                )
                self.assertEqual(summary.remaining_seconds, expires)
                assert_scrubbed(self, access, refresh, token_type, key)
        for issued, expires, now in (
            (True, 60, 2_000),
            (2_000, True, 2_000),
            (2_000, 60, True),
            (2_000, 59, 2_000),
            (2_000, 86_401, 2_000),
            (2_000, 60, 2_001),
            (2**63, 60, 2**63),
            (2**63 - 30, 60, 2**63 - 30),
            (2_000, 60, 2**63),
        ):
            access = bytearray(b"fake-access-token-invalid-ttl")
            refresh = bytearray(b"fake-refresh-token-invalid-ttl")
            token_type = bytearray(b"Bearer")
            key = fake_key()
            with self.assertRaisesRegex(
                self.module.DedicatedRootOauthHelperError,
                "^token_validity$",
            ):
                self.module._validate_token_material(
                    access_token=access,
                    refresh_token=refresh,
                    token_type=token_type,
                    token_commitment_key=key,
                    issued_at_unix=issued,
                    expires_in_seconds=expires,
                    now_unix=now,
                )
            assert_scrubbed(self, access, refresh, token_type, key)

        access = bytearray(b"fake-access-token-int64-boundary")
        refresh = bytearray(b"fake-refresh-token-int64-boundary")
        token_type = bytearray(b"Bearer")
        key = fake_key()
        summary = self.module._validate_token_material(
            access_token=access,
            refresh_token=refresh,
            token_type=token_type,
            token_commitment_key=key,
            issued_at_unix=2**63 - 61,
            expires_in_seconds=60,
            now_unix=2**63 - 61,
        )
        self.assertEqual(summary.expiration_unix, 2**63 - 1)
        assert_scrubbed(self, access, refresh, token_type, key)

    def test_39_token_rejects_alias_shape_and_nul_but_scrubs_all_buffers(self) -> None:
        alias = bytearray(b"fake-token-alias-material-value")
        token_type = bytearray(b"Bearer")
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^token_contract$",
        ):
            self.module._validate_token_material(
                access_token=alias,
                refresh_token=alias,
                token_type=token_type,
                token_commitment_key=key,
                issued_at_unix=1,
                expires_in_seconds=60,
                now_unix=1,
            )
        assert_scrubbed(self, alias, token_type, key)

        access = bytearray(b"short")
        refresh = bytearray(b"fake-refresh-token-shape-value")
        token_type = bytearray(b"Bearer")
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^token_contract$",
        ):
            self.module._validate_token_material(
                access_token=access,
                refresh_token=refresh,
                token_type=token_type,
                token_commitment_key=key,
                issued_at_unix=1,
                expires_in_seconds=60,
                now_unix=1,
            )
        assert_scrubbed(self, access, refresh, token_type, key)

        access = bytearray(b"fake-access-token-wrong-type")
        refresh = bytearray(b"fake-refresh-token-wrong-type")
        token_type = bytearray(b"bearer")
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^token_contract$",
        ):
            self.module._validate_token_material(
                access_token=access,
                refresh_token=refresh,
                token_type=token_type,
                token_commitment_key=key,
                issued_at_unix=1,
                expires_in_seconds=60,
                now_unix=1,
            )
        assert_scrubbed(self, access, refresh, token_type, key)

    def test_40_identity_binding_exactly_matches_c1_domains_and_aggregate(self) -> None:
        account_raw = b"fake-account-identity-001"
        principal_raw = b"fake-principal-identity-001"
        key_raw = bytes(range(32))
        expected_account = fixed_commitment(
            key_raw,
            b"noteai.item26.account-id-commitment.v1\x00",
            account_raw,
        )
        expected_principal = fixed_commitment(
            key_raw,
            b"noteai.item26.principal-id-commitment.v1\x00",
            principal_raw,
        )
        account = bytearray(account_raw)
        principal = bytearray(principal_raw)
        key = bytearray(key_raw)
        summary = self.module._validate_identity_binding(
            account_identity=account,
            principal_identity=principal,
            identity_commitment_key=key,
            expected_account_commitment_hmac_sha256=expected_account,
            expected_principal_commitment_hmac_sha256=expected_principal,
        )
        aggregate = {
            "account_commitment_hmac_sha256": expected_account,
            "principal_commitment_hmac_sha256": expected_principal,
            "schema": "noteai.item26.aliyun-account-binding.v1",
        }
        expected_binding = hashlib.sha256(canonical(aggregate)).hexdigest()
        self.assertEqual(summary.account_binding_sha256, expected_binding)
        self.assertEqual(summary.account_commitment_hmac_sha256, expected_account)
        self.assertEqual(summary.principal_commitment_hmac_sha256, expected_principal)
        assert_scrubbed(self, account, principal, key)

    def test_41_identity_mismatch_runs_both_compares_and_uses_one_error(self) -> None:
        account_raw = b"fake-account-identity-002"
        principal_raw = b"fake-principal-identity-002"
        key_raw = bytes(range(32))
        expected_principal = fixed_commitment(
            key_raw,
            b"noteai.item26.principal-id-commitment.v1\x00",
            principal_raw,
        )
        account = bytearray(account_raw)
        principal = bytearray(principal_raw)
        key = bytearray(key_raw)
        original_compare = hmac.compare_digest
        comparisons = []

        def compare(left, right):
            comparisons.append((left, right))
            return original_compare(left, right)

        with mock.patch.object(self.module.hmac, "compare_digest", side_effect=compare):
            with self.assertRaisesRegex(
                self.module.DedicatedRootOauthHelperError,
                "^identity_commitment_mismatch$",
            ):
                self.module._validate_identity_binding(
                    account_identity=account,
                    principal_identity=principal,
                    identity_commitment_key=key,
                    expected_account_commitment_hmac_sha256="0" * 64,
                    expected_principal_commitment_hmac_sha256=expected_principal,
                )
        self.assertEqual(len(comparisons), 2)
        assert_scrubbed(self, account, principal, key)
        domain_node = function_node(self.tree, "_domain_commitment")
        body = list(domain_node.body)
        self.assertEqual(len(body), 2)
        self.assertIsInstance(body[0], ast.Assign)
        self.assertIsInstance(body[1], ast.Try)
        secret_extends = [
            item
            for item in ast.walk(body[1])
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "extend"
        ]
        self.assertEqual(len(secret_extends), 3)

    def test_42_identity_rejects_alias_and_malformed_expected_with_scrub(self) -> None:
        alias = bytearray(b"fake-identity-alias-value")
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^identity_contract$",
        ):
            self.module._validate_identity_binding(
                account_identity=alias,
                principal_identity=alias,
                identity_commitment_key=key,
                expected_account_commitment_hmac_sha256="0" * 64,
                expected_principal_commitment_hmac_sha256="0" * 64,
            )
        assert_scrubbed(self, alias, key)

        account = bytearray(b"fake-account-identity-003")
        principal = bytearray(b"fake-principal-identity-003")
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^identity_contract$",
        ):
            self.module._validate_identity_binding(
                account_identity=account,
                principal_identity=principal,
                identity_commitment_key=key,
                expected_account_commitment_hmac_sha256="A" * 64,
                expected_principal_commitment_hmac_sha256="0" * 64,
            )
        assert_scrubbed(self, account, principal, key)

    def test_43_temporary_sts_initial_validation_uses_post_identity_clock(self) -> None:
        key_id_raw = b"STS.FAKEACCESSKEY0001"
        key_secret_raw = b"fake-sts-secret-for-unit-test"
        security_token_raw = b"fake-sts-security-token-for-unit-test"
        key_raw = bytes(range(32))
        account_binding = "a" * 64
        key_id = bytearray(key_id_raw)
        key_secret = bytearray(key_secret_raw)
        security_token = bytearray(security_token_raw)
        key = bytearray(key_raw)
        summary = self.module._validate_temporary_sts_material(
            access_key_id=key_id,
            access_key_secret=key_secret,
            security_token=security_token,
            material_commitment_key=key,
            claimed_account_binding_sha256=account_binding,
            expiration_unix=11_860,
            now_after_caller_identity_unix=10_000,
        )
        self.assertEqual(summary.remaining_seconds, 1_860)
        self.assertEqual(summary.expiration_unix, 11_860)
        self.assertEqual(summary.account_binding_sha256, account_binding)
        commitments = {
            "access_key_id_commitment_hmac_sha256": fixed_commitment(
                key_raw,
                b"noteai.item26.dedicated-root-oauth-sts-access-key-id.v1\x00",
                key_id_raw,
            ),
            "access_key_secret_commitment_hmac_sha256": fixed_commitment(
                key_raw,
                b"noteai.item26.dedicated-root-oauth-sts-access-key-secret.v1\x00",
                key_secret_raw,
            ),
            "account_binding_sha256": account_binding,
            "expiration_unix": 11_860,
            "schema": (
                "noteai.item26.dedicated-root-oauth-temporary-sts-material-binding.v1"
            ),
            "security_token_commitment_hmac_sha256": fixed_commitment(
                key_raw,
                b"noteai.item26.dedicated-root-oauth-sts-security-token.v1\x00",
                security_token_raw,
            ),
        }
        self.assertEqual(
            summary.credential_material_binding_sha256,
            hashlib.sha256(canonical(commitments)).hexdigest(),
        )
        assert_scrubbed(self, key_id, key_secret, security_token, key)

    def test_44_temporary_sts_exact_ttl_bounds_and_stability(self) -> None:
        outputs = []
        for remaining in (1_860, 86_400):
            key_id = bytearray(b"STS.FAKEACCESSKEY0002")
            key_secret = bytearray(b"fake-sts-secret-boundary")
            security_token = bytearray(b"fake-sts-token-boundary")
            key = fake_key()
            summary = self.module._validate_temporary_sts_material(
                access_key_id=key_id,
                access_key_secret=key_secret,
                security_token=security_token,
                material_commitment_key=key,
                claimed_account_binding_sha256="b" * 64,
                expiration_unix=20_000 + remaining,
                now_after_caller_identity_unix=20_000,
            )
            outputs.append(summary.credential_material_binding_sha256)
            self.assertEqual(summary.remaining_seconds, remaining)
            assert_scrubbed(self, key_id, key_secret, security_token, key)
        self.assertNotEqual(outputs[0], outputs[1])

        key_id = bytearray(b"STS.FAKEACCESSKEYINT64")
        key_secret = bytearray(b"fake-sts-secret-int64")
        security_token = bytearray(b"fake-sts-token-int64")
        key = fake_key()
        boundary = self.module._validate_temporary_sts_material(
            access_key_id=key_id,
            access_key_secret=key_secret,
            security_token=security_token,
            material_commitment_key=key,
            claimed_account_binding_sha256="b" * 64,
            expiration_unix=2**63 - 1,
            now_after_caller_identity_unix=2**63 - 1 - 1_860,
        )
        self.assertEqual(boundary.remaining_seconds, 1_860)
        assert_scrubbed(self, key_id, key_secret, security_token, key)

        stable = []
        for _ in range(2):
            key_id = bytearray(b"STS.FAKEACCESSKEY0003")
            key_secret = bytearray(b"fake-sts-secret-stable")
            security_token = bytearray(b"fake-sts-token-stable")
            key = fake_key()
            stable.append(
                self.module._validate_temporary_sts_material(
                    access_key_id=key_id,
                    access_key_secret=key_secret,
                    security_token=security_token,
                    material_commitment_key=key,
                    claimed_account_binding_sha256="c" * 64,
                    expiration_unix=31_860,
                    now_after_caller_identity_unix=30_000,
                ).credential_material_binding_sha256
            )
        self.assertEqual(stable[0], stable[1])

    def test_45_temporary_sts_rejects_ttl_shape_alias_and_bad_binding_with_scrub(self) -> None:
        for expiration, now, code in (
            (11_859, 10_000, "sts_validity"),
            (96_401, 10_000, "sts_validity"),
            (True, 10_000, "sts_validity"),
            (11_860, True, "sts_validity"),
            (2**63, 2**63 - 1_860, "sts_validity"),
            (2**63 - 1, 2**63, "sts_validity"),
        ):
            key_id = bytearray(b"STS.FAKEACCESSKEY0004")
            key_secret = bytearray(b"fake-sts-secret-invalid")
            security_token = bytearray(b"fake-sts-token-invalid")
            key = fake_key()
            with self.assertRaisesRegex(
                self.module.DedicatedRootOauthHelperError,
                f"^{code}$",
            ):
                self.module._validate_temporary_sts_material(
                    access_key_id=key_id,
                    access_key_secret=key_secret,
                    security_token=security_token,
                    material_commitment_key=key,
                    claimed_account_binding_sha256="d" * 64,
                    expiration_unix=expiration,
                    now_after_caller_identity_unix=now,
                )
            assert_scrubbed(self, key_id, key_secret, security_token, key)

        alias = bytearray(b"STS.FAKEACCESSKEY0005")
        security_token = bytearray(b"fake-sts-token-alias")
        key = fake_key()
        with self.assertRaisesRegex(
            self.module.DedicatedRootOauthHelperError,
            "^sts_contract$",
        ):
            self.module._validate_temporary_sts_material(
                access_key_id=alias,
                access_key_secret=alias,
                security_token=security_token,
                material_commitment_key=key,
                claimed_account_binding_sha256="d" * 64,
                expiration_unix=11_860,
                now_after_caller_identity_unix=10_000,
            )
        assert_scrubbed(self, alias, security_token, key)
        node = function_node(self.tree, "_validate_temporary_sts_material")
        self.assertFalse(
            any(
                isinstance(item, ast.Subscript)
                and isinstance(item.value, ast.Name)
                and item.value.id == "key_id"
                and isinstance(item.slice, ast.Slice)
                for item in ast.walk(node)
            )
        )

    def test_46_public_summaries_are_frozen_and_never_hold_raw_buffers(self) -> None:
        classes = {
            self.module._CallbackSummary: (
                "authorization_code_commitment_hmac_sha256",
                "authorization_code_present",
                "parameter_count",
                "state_commitment_hmac_sha256",
            ),
            self.module._TokenSummary: (
                "access_token_commitment_hmac_sha256",
                "expiration_unix",
                "refresh_token_commitment_hmac_sha256",
                "remaining_seconds",
                "token_type",
            ),
            self.module._IdentityBindingSummary: (
                "account_binding_sha256",
                "account_commitment_hmac_sha256",
                "principal_commitment_hmac_sha256",
            ),
            self.module._TemporaryStsSummary: (
                "account_binding_sha256",
                "credential_material_binding_sha256",
                "expiration_unix",
                "remaining_seconds",
            ),
        }
        for summary_class, expected_fields in classes.items():
            mapping = summary_class.__dataclass_fields__
            self.assertEqual(tuple(mapping), expected_fields)
            self.assertNotIn("__dict__", summary_class.__dict__)
            self.assertIn("__slots__", summary_class.__dict__)
            self.assertTrue(summary_class.__dataclass_params__.frozen)

    def test_47_scrub_bytearray_only_overwrites_exact_mutable_buffers(self) -> None:
        value = bytearray(b"fake-private-buffer")
        self.assertIsNone(self.module.scrub_bytearray(value))
        assert_scrubbed(self, value)
        immutable = b"fake-private-buffer"
        self.assertIsNone(self.module.scrub_bytearray(immutable))
        self.assertEqual(immutable, b"fake-private-buffer")
        self.assertIsNone(self.module.scrub_bytearray(Poison()))

    def test_48_private_validation_is_stateless_and_not_memoized(self) -> None:
        before = dict(self.module.__dict__)
        verifier = bytearray(b"a" * 43)
        import base64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(b"a" * 43).digest()).rstrip(b"=").decode("ascii")
        self.module._validate_pkce_pair(verifier, challenge)
        after = dict(self.module.__dict__)
        new_names = set(after) - set(before)
        self.assertEqual(new_names, set())
        self.assertFalse(any("cache" in name.lower() and "bytes" not in name.lower() for name in new_names))

    def test_49_candidate_files_are_utf8_secret_free_and_compile(self) -> None:
        test_raw = Path(__file__).read_bytes()
        self.raw.decode("utf-8", "strict")
        test_raw.decode("utf-8", "strict")
        compile(self.raw, str(SOURCE_PATH), "exec", optimize=0)
        compile(self.raw, str(SOURCE_PATH), "exec", optimize=2)
        compile(test_raw, str(Path(__file__)), "exec", optimize=0)
        compile(test_raw, str(Path(__file__)), "exec", optimize=2)
        patterns = (
            re.compile(b"LTAI" + b"[A-Za-z0-9]{12,}"),
            re.compile(b"BEGIN[ ]PRIVATE[ ]KEY"),
            re.compile(b"access_key_secret[\"']?[ ]*[:=][ ]*[\"'][^\"']+"),
            re.compile(b"security_token[\"']?[ ]*[:=][ ]*[\"'][^\"']+"),
            re.compile(b"refresh_token[\"']?[ ]*[:=][ ]*[\"'][^\"']+"),
        )
        for candidate in (self.raw, test_raw):
            for pattern in patterns:
                self.assertIsNone(pattern.search(candidate), pattern.pattern)

    def test_50_authorized_candidate_path_names_are_exact(self) -> None:
        self.assertEqual(SOURCE_PATH.name, "item26_aliyun_dedicated_root_oauth_helper_v1.py")
        self.assertEqual(
            Path(__file__).name,
            "test_item26_aliyun_dedicated_root_oauth_helper_v1.py",
        )


if __name__ == "__main__":
    unittest.main()
