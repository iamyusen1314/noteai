import base64
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

from tools import render_item27_internal_smoke_requests_v1 as cloud

SMOKE_SOURCE = ROOT / "deploy" / "production" / "internal_zero_provider_smoke.py"
SMOKE_SPEC = importlib.util.spec_from_file_location(
    "item27_internal_zero_provider_smoke_for_renderer_test",
    SMOKE_SOURCE,
)
smoke = importlib.util.module_from_spec(SMOKE_SPEC)
assert SMOKE_SPEC.loader is not None
SMOKE_SPEC.loader.exec_module(smoke)


class Item27InternalSmokeRequestsV1Tests(unittest.TestCase):
    PLAN_NONCE = "0123456789abcdef0123456789abcdef"
    PREDECESSOR_ACCEPTANCE = "c" * 64
    INSTANCES = {
        "api_c_instance_id": "i-apic123",
        "api_f_instance_id": "i-apif123",
        "worker_c_instance_id": "i-workerc123",
        "worker_f_instance_id": "i-workerf123",
    }

    def input_value(self, action="api_c"):
        return {
            "action": action,
            **self.INSTANCES,
            "plan_nonce": self.PLAN_NONCE,
            "predecessor_acceptance_sha256": self.PREDECESSOR_ACCEPTANCE,
        }

    def decoded_wrapper(self, action="api_c"):
        rendered = cloud.render_request(self.input_value(action))
        return base64.b64decode(
            rendered["request"]["CommandContent"].encode("ascii"),
            validate=True,
        )

    def embedded_executor(self, wrapper):
        marker = b"<<'ITEM27_EXECUTOR_GZIP'\n"
        payload = wrapper.split(marker, 1)[1].split(b"\nITEM27_EXECUTOR_GZIP\n", 1)[0]
        compressed = base64.b64decode(b"".join(payload.splitlines()), validate=True)
        return compressed, gzip.decompress(compressed)

    def test_fixed_four_action_matrix_and_serial_order(self):
        expected = {
            "api_c": (
                "noteai-item27-internal-smoke-api-c-20260823-closure-fix1",
                "api_c_instance_id",
                "api-c",
            ),
            "api_f": (
                "noteai-item27-internal-smoke-api-f-20260823-json-output-fix1",
                "api_f_instance_id",
                "api-f",
            ),
            "worker_c": (
                "noteai-item27-internal-smoke-worker-c-20260813-v1",
                "worker_c_instance_id",
                "worker-c",
            ),
            "worker_f": (
                "noteai-item27-internal-smoke-worker-f-20260813-v1",
                "worker_f_instance_id",
                "worker-f",
            ),
        }
        self.assertEqual(cloud.ACTION_ORDER, tuple(expected))
        self.assertEqual(set(cloud.ACTIONS), set(expected))
        for action, row in expected.items():
            with self.subTest(action=action):
                spec = cloud.ACTIONS[action]
                self.assertEqual((spec.name, spec.target, spec.host_mode), row)
                self.assertEqual(
                    spec.timeout,
                    smoke.REQUIRED_PROVIDER_TIMEOUT_SECONDS[spec.host_mode],
                )
                rendered = cloud.render_request(self.input_value(action))
                index = cloud.ACTION_ORDER.index(action)
                next_action = (
                    cloud.ACTION_ORDER[index + 1]
                    if index + 1 < len(cloud.ACTION_ORDER)
                    else None
                )
                self.assertEqual(rendered["state"]["serial_next_action"], next_action)

    def test_each_action_renders_one_exact_official_single_target_request(self):
        exact_keys = {
            "ClientToken",
            "CommandContent",
            "ContentEncoding",
            "EnableParameter",
            "InstanceId",
            "KeepCommand",
            "Name",
            "RegionId",
            "RepeatMode",
            "Tag",
            "TerminationMode",
            "Timeout",
            "Type",
            "Username",
            "WorkingDir",
        }
        tokens = cloud.derive_client_tokens(
            self.PLAN_NONCE, self.PREDECESSOR_ACCEPTANCE
        )
        for action, spec in cloud.ACTIONS.items():
            with self.subTest(action=action):
                result = cloud.render_request(self.input_value(action))
                request = result["request"]
                self.assertEqual(set(request), exact_keys)
                self.assertEqual(request["ClientToken"], tokens[action])
                self.assertEqual(request["ContentEncoding"], "Base64")
                self.assertIs(request["EnableParameter"], False)
                self.assertEqual(request["InstanceId"], [self.INSTANCES[spec.target]])
                self.assertIs(request["KeepCommand"], True)
                self.assertEqual(request["Name"], spec.name)
                self.assertEqual(request["RegionId"], "cn-shenzhen")
                self.assertEqual(request["RepeatMode"], "Once")
                self.assertEqual(
                    request["Tag"],
                    [{"Key": "noteai-task", "Value": "item27-internal-smoke-v1"}],
                )
                self.assertEqual(request["TerminationMode"], "ProcessTree")
                self.assertEqual(
                    request["Timeout"],
                    smoke.REQUIRED_PROVIDER_TIMEOUT_SECONDS[spec.host_mode],
                )
                self.assertEqual(request["Type"], "RunShellScript")
                self.assertEqual(request["Username"], "root")
                self.assertEqual(request["WorkingDir"], "/root")
                self.assertLessEqual(
                    len(request["CommandContent"].encode("ascii")),
                    cloud.MAX_COMMAND_CONTENT_BYTES,
                )
                for forbidden in (
                    "Frequency",
                    "Parameters",
                    "ResourceTag",
                    "ContainerId",
                    "ContainerName",
                    "OssDelivery",
                    "RetryCount",
                ):
                    self.assertNotIn(forbidden, request)

    def test_frozen_executor_identity_is_exact_and_embedded_roundtrip(self):
        path = ROOT / cloud.EXECUTOR_PATH
        payload = path.read_bytes()
        self.assertEqual(cloud.EXECUTOR_IDENTITY["bytes"], len(payload))
        self.assertEqual(cloud.EXECUTOR_IDENTITY["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(cloud.EXECUTOR_IDENTITY["mode"], 0o644)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        self.assertEqual(cloud._read_executor(), payload)
        for action, spec in cloud.ACTIONS.items():
            with self.subTest(action=action):
                wrapper = self.decoded_wrapper(action)
                compressed, restored = self.embedded_executor(wrapper)
                self.assertEqual(restored, payload)
                rendered = cloud.render_request(self.input_value(action))
                evidence = rendered["evidence"]
                self.assertEqual(evidence["executor_path"], cloud.EXECUTOR_PATH)
                self.assertEqual(evidence["executor_bytes"], len(payload))
                self.assertEqual(evidence["executor_sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(evidence["compressed_executor_bytes"], len(compressed))
                self.assertEqual(
                    evidence["compressed_executor_sha256"],
                    hashlib.sha256(compressed).hexdigest(),
                )
                self.assertIn(("--mode '" + spec.host_mode + "'").encode("ascii"), wrapper)

    def test_wrapper_is_syntax_valid_root_only_cleanup_bounded_and_host_bound(self):
        wrappers = {}
        for action, spec in cloud.ACTIONS.items():
            with self.subTest(action=action):
                wrapper = self.decoded_wrapper(action)
                wrappers[action] = wrapper
                syntax = subprocess.run(
                    ["/bin/bash", "-n"],
                    input=wrapper,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=10,
                )
                self.assertEqual((syntax.returncode, syntax.stdout, syntax.stderr), (0, b"", b""))
                self.assertTrue(wrapper.startswith(b"#!/bin/bash\nset -euo pipefail\numask 077\n"))
                self.assertIn(b"/usr/bin/mkdir -m 0700", wrapper)
                self.assertIn(b"test \"$created\" = 1 || return 0", wrapper)
                self.assertIn(b"'%u:%g:%a'", wrapper)
                self.assertIn(b"/usr/bin/chown root:root", wrapper)
                self.assertIn(b"/usr/bin/chmod 0600", wrapper)
                self.assertIn(b"cleanup >/dev/null 2>&1 || exit 4", wrapper)
                self.assertIn(b"case \"$result\" in 0|3|4)", wrapper)
                self.assertNotIn(b"rm -rf", wrapper)
                self.assertLess(
                    wrapper.index(b"if test -e \"$task_root\""),
                    wrapper.index(b"/usr/bin/mkdir -m 0700"),
                )
                self.assertLess(
                    wrapper.index(b"/usr/bin/mkdir -m 0700"),
                    wrapper.index(b"created=1"),
                )
                self.assertIn(
                    ("/run/noteai-item27-internal-smoke-v1-" + spec.host_mode).encode("ascii"),
                    wrapper,
                )
                self.assertNotIn(self.PLAN_NONCE.encode("ascii"), wrapper)
                for instance_id in self.INSTANCES.values():
                    self.assertNotIn(instance_id.encode("ascii"), wrapper)
        self.assertEqual(len(set(wrappers.values())), 4)

    def test_render_is_deterministic_and_emits_only_the_selected_instance(self):
        requests = {}
        for action, spec in cloud.ACTIONS.items():
            with self.subTest(action=action):
                first = cloud.canonical(cloud.render_request(self.input_value(action)))
                second = cloud.canonical(cloud.render_request(self.input_value(action)))
                self.assertEqual(first, second)
                selected = self.INSTANCES[spec.target].encode("ascii")
                self.assertIn(selected, first)
                for key, instance_id in self.INSTANCES.items():
                    if key != spec.target:
                        self.assertNotIn(instance_id.encode("ascii"), first)
                requests[action] = first
        self.assertEqual(len(set(requests.values())), 4)

    def test_plan_nonce_derives_four_ordered_unique_tokens_without_emission(self):
        tokens = cloud.derive_client_tokens(
            self.PLAN_NONCE, self.PREDECESSOR_ACCEPTANCE
        )
        self.assertEqual(tuple(tokens), cloud.ACTION_ORDER)
        self.assertEqual(len(set(tokens.values())), 4)
        for action, token in tokens.items():
            expected = hashlib.sha256(
                b"item27-internal-smoke-v1\x00"
                + self.PLAN_NONCE.encode("ascii")
                + b"\x00"
                + self.PREDECESSOR_ACCEPTANCE.encode("ascii")
                + b"\x00"
                + action.encode("ascii")
            ).hexdigest()
            self.assertEqual(token, expected)
            self.assertRegex(token, r"^[0-9a-f]{64}$")
        output = cloud.canonical(cloud.render_request(self.input_value()))
        self.assertNotIn(self.PLAN_NONCE.encode("ascii"), output)

    def test_each_dispatch_token_machine_binds_the_supplied_predecessor_acceptance(self):
        for action in cloud.ACTION_ORDER:
            with self.subTest(action=action):
                original_input = self.input_value(action)
                changed_input = copy.deepcopy(original_input)
                changed_input["predecessor_acceptance_sha256"] = "d" * 64
                original = cloud.render_request(original_input)
                changed = cloud.render_request(changed_input)
                self.assertNotEqual(
                    original["request"]["ClientToken"],
                    changed["request"]["ClientToken"],
                )
                self.assertEqual(
                    original["evidence"]["predecessor_acceptance_sha256"],
                    self.PREDECESSOR_ACCEPTANCE,
                )
                self.assertEqual(
                    original["evidence"]["predecessor_acceptance_source"],
                    cloud.PREDECESSOR_ACCEPTANCE_SOURCES[action],
                )

    def test_history_zero_retry_zero_and_unknown_never_resubmit_are_fixed(self):
        for action, spec in cloud.ACTIONS.items():
            with self.subTest(action=action):
                rendered = cloud.render_request(self.input_value(action))
                prerequisites = rendered["prerequisites"]
                self.assertEqual(prerequisites["action_prerequisites"], list(spec.prerequisites))
                self.assertEqual(
                    prerequisites["fresh_describe_commands_exact_identity_count_must_equal"], 0,
                )
                self.assertEqual(
                    prerequisites["fresh_describe_invocations_exact_identity_count_must_equal"], 0,
                )
                self.assertEqual(prerequisites["fresh_exact_name_history_count_must_equal"], 0)
                self.assertIs(prerequisites["history_all_pages_required"], True)
                self.assertIs(prerequisites["local_o_excl_plan_nonce_required"], True)
                self.assertEqual(prerequisites["provider_reads_performed_by_renderer"], 0)
                self.assertIs(
                    prerequisites["provider_client_token_readback_supported"],
                    False,
                )
                self.assertNotIn(
                    "fresh_client_token_history_count_must_equal",
                    prerequisites,
                )
                self.assertIs(prerequisites["plan_nonce_emitted_by_renderer"], False)
                self.assertIs(
                    prerequisites[
                        "predecessor_acceptance_digest_must_be_machine_verified"
                    ],
                    True,
                )
                state = rendered["state"]
                self.assertEqual(state["initial"], "HISTORY_ZERO_REQUIRED")
                self.assertEqual(state["post_submit"], "PROVIDER_READBACK_ONLY")
                self.assertEqual(state["automatic_retry_count"], 0)
                self.assertIs(state["automatic_retry_allowed"], False)
                self.assertEqual(state["dispatch_count_limit"], 1)
                self.assertIs(state["same_request_resubmit_allowed"], False)
                self.assertEqual(
                    state["provider_unknown_recovery"],
                    "READBACK_EXACT_NAME_COMMAND_INVOCATION_TARGET_NEVER_RESUBMIT",
                )
                self.assertNotIn(
                    "CLIENT_TOKEN", state["provider_unknown_recovery"]
                )
                self.assertEqual(
                    state["provider_unknown_allowed_reads"],
                    [
                        "DescribeCommands",
                        "DescribeInvocations",
                        "DescribeInvocationResults",
                    ],
                )
                self.assertIs(state["provider_unknown_readback_all_pages_required"], True)
                self.assertIs(state["provider_unknown_resubmit_allowed"], False)
                self.assertEqual(
                    state["terminal_exit_code"],
                    dict(cloud.TERMINAL_TRANSITIONS[action]),
                )
                self.assertEqual(state["terminal_exit_code"]["3"], "STOP_KNOWN_FAIL_NEVER_REPLAY")
                self.assertEqual(state["terminal_exit_code"]["4"], "STOP_UNKNOWN_RETAIN_NEVER_REPLAY")

    def test_request_and_evidence_hashes_bind_exact_bytes(self):
        result = cloud.render_request(self.input_value("worker_f"))
        request = result["request"]
        evidence = result["evidence"]
        request_raw = cloud.canonical(request)
        command_ascii = request["CommandContent"].encode("ascii")
        wrapper = base64.b64decode(command_ascii, validate=True)
        self.assertEqual(evidence["request_canonical_bytes"], len(request_raw))
        self.assertEqual(evidence["request_canonical_sha256"], hashlib.sha256(request_raw).hexdigest())
        self.assertEqual(evidence["command_content_base64_bytes"], len(command_ascii))
        self.assertEqual(evidence["command_content_sha256"], hashlib.sha256(command_ascii).hexdigest())
        self.assertEqual(evidence["wrapper_bytes"], len(wrapper))
        self.assertEqual(evidence["wrapper_sha256"], hashlib.sha256(wrapper).hexdigest())
        validation = cloud.validate_run_command(request, self.input_value("worker_f"))
        self.assertEqual(validation["command_content_sha256"], evidence["command_content_sha256"])
        self.assertEqual(validation["executor_sha256"], evidence["executor_sha256"])
        self.assertEqual(validation["wrapper_sha256"], evidence["wrapper_sha256"])

    def test_input_schema_ids_action_nonce_and_distinctness_are_strict(self):
        changes = (
            ("action", "other"),
            ("action", True),
            ("api_c_instance_id", "api-c"),
            ("api_f_instance_id", "i-UPPER"),
            ("worker_c_instance_id", True),
            ("worker_f_instance_id", "i-worker_f"),
            ("plan_nonce", True),
            ("plan_nonce", "A" * 32),
            ("plan_nonce", "a" * 31),
            ("plan_nonce", "a" * 33),
            ("predecessor_acceptance_sha256", True),
            ("predecessor_acceptance_sha256", "a" * 63),
            ("predecessor_acceptance_sha256", "A" * 64),
        )
        for key, value in changes:
            changed = self.input_value()
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(cloud.RequestError):
                cloud.render_request(changed)
        duplicate = self.input_value()
        duplicate["api_f_instance_id"] = duplicate["api_c_instance_id"]
        with self.assertRaisesRegex(cloud.RequestError, "instances_distinct"):
            cloud.render_request(duplicate)
        extra = self.input_value()
        extra["extra"] = False
        with self.assertRaisesRegex(cloud.RequestError, "input_contract"):
            cloud.render_request(extra)
        missing = self.input_value()
        del missing["worker_f_instance_id"]
        with self.assertRaisesRegex(cloud.RequestError, "input_contract"):
            cloud.render_request(missing)

    def test_validator_rejects_extras_alias_types_multiple_targets_and_drift(self):
        input_value = self.input_value("api_f")
        request = cloud.render_request(input_value)["request"]
        cases = []
        for key, value in (
            ("KeepCommand", 1),
            ("EnableParameter", 0),
            ("Timeout", True),
            ("Timeout", cloud.ACTIONS["api_f"].timeout + 1),
            ("Name", "other"),
            ("ClientToken", "f" * 64),
            ("CommandContent", base64.b64encode(b"other").decode("ascii")),
            ("RepeatMode", "Period"),
            ("TerminationMode", "Process"),
            ("Tag", [{"Key": "noteai-task", "Value": "other"}]),
            ("InstanceId", [self.INSTANCES["api_f_instance_id"], self.INSTANCES["api_c_instance_id"]]),
        ):
            changed = copy.deepcopy(request)
            changed[key] = value
            cases.append(changed)
        changed = copy.deepcopy(request)
        changed["Frequency"] = "0 0 * * *"
        cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(cloud.RequestError):
                cloud.validate_run_command(changed, input_value)

    def test_canonical_parser_rejects_duplicates_noncanonical_json_and_bad_shape(self):
        value = self.input_value()
        raw = cloud.canonical(value)
        self.assertEqual(cloud.parse_canonical(raw), value)
        noncanonical = json.dumps(value, ensure_ascii=True).encode("ascii") + b"\n"
        self.assertNotEqual(noncanonical, raw)
        with self.assertRaisesRegex(cloud.RequestError, "input_canonical"):
            cloud.parse_canonical(noncanonical)
        duplicate = raw.replace(
            b'"action":"api_c",',
            b'"action":"api_c","action":"api_f",',
            1,
        )
        with self.assertRaisesRegex(cloud.RequestError, "duplicate_json_key"):
            cloud.parse_canonical(duplicate)
        for bad in (b"", raw[:-1], raw + b"\x00", raw.replace(b"\n", b"\r\n")):
            with self.subTest(bad=bad[-10:]), self.assertRaises(cloud.RequestError):
                cloud.parse_canonical(bad)

    def test_executor_loader_rejects_unfrozen_wrong_hash_mode_and_symlink(self):
        with mock.patch.object(
            cloud,
            "EXECUTOR_IDENTITY",
            {"bytes": 0, "sha256": "", "mode": 0o644},
        ):
            with self.assertRaisesRegex(cloud.RequestError, "executor_identity_unfrozen"):
                cloud._read_executor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"#!/usr/bin/env python3\nprint('ok')\n"
            source = root / "executor.py"
            source.write_bytes(payload)
            source.chmod(0o644)
            identity = {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mode": 0o644,
            }
            with mock.patch.object(cloud, "REPOSITORY_ROOT", root), mock.patch.object(
                cloud, "EXECUTOR_PATH", "executor.py",
            ), mock.patch.object(cloud, "EXECUTOR_IDENTITY", identity):
                self.assertEqual(cloud._read_executor(), payload)
                source.chmod(0o600)
                with self.assertRaisesRegex(cloud.RequestError, "executor_identity"):
                    cloud._read_executor()
                source.chmod(0o644)
                wrong = dict(identity)
                wrong["sha256"] = "f" * 64
                with mock.patch.object(cloud, "EXECUTOR_IDENTITY", wrong):
                    with self.assertRaisesRegex(cloud.RequestError, "executor_identity"):
                        cloud._read_executor()
            source.unlink()
            target = root / "target.py"
            target.write_bytes(payload)
            target.chmod(0o644)
            source.symlink_to(target)
            with mock.patch.object(cloud, "REPOSITORY_ROOT", root), mock.patch.object(
                cloud, "EXECUTOR_PATH", "executor.py",
            ), mock.patch.object(cloud, "EXECUTOR_IDENTITY", identity):
                with self.assertRaises(cloud.RequestError):
                    cloud._read_executor()

    def test_command_content_limit_is_strict(self):
        encoded_at_limit = base64.b64encode(b"x" * 13500)
        self.assertEqual(len(encoded_at_limit), cloud.MAX_COMMAND_CONTENT_BYTES)
        content, digest = cloud._command_content(b"x" * 13500)
        self.assertEqual(content.encode("ascii"), encoded_at_limit)
        self.assertEqual(digest, hashlib.sha256(encoded_at_limit).hexdigest())
        with self.assertRaisesRegex(cloud.RequestError, "command_limit"):
            cloud._command_content(b"x" * 13501)

    def test_cli_canonical_success_and_failure_are_secret_free_and_rc2(self):
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(cloud.canonical(self.input_value("worker_c")))
        stdout = mock.Mock()
        stdout.buffer = io.BytesIO()
        stderr = io.StringIO()
        with mock.patch.object(cloud.sys, "stdin", stdin), mock.patch.object(
            cloud.sys, "stdout", stdout,
        ), mock.patch.object(cloud.sys, "stderr", stderr):
            self.assertEqual(cloud.cli(), 0)
        output = stdout.buffer.getvalue()
        self.assertEqual(output, cloud.canonical(json.loads(output)))
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(self.PLAN_NONCE.encode("ascii"), output)

        bad = self.input_value()
        bad["plan_nonce"] = False
        stdin.buffer = io.BytesIO(cloud.canonical(bad))
        stdout.buffer = io.BytesIO()
        stderr = io.StringIO()
        with mock.patch.object(cloud.sys, "stdin", stdin), mock.patch.object(
            cloud.sys, "stdout", stdout,
        ), mock.patch.object(cloud.sys, "stderr", stderr):
            self.assertEqual(cloud.cli(), 2)
        self.assertEqual(stdout.buffer.getvalue(), b"")
        self.assertRegex(
            stderr.getvalue(),
            r"^ITEM27_INTERNAL_SMOKE_REQUEST_FAILED:[a-z0-9_]+\n$",
        )


if __name__ == "__main__":
    unittest.main()
