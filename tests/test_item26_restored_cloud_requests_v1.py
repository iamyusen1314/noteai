import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

from tools import render_item26_restored_cloud_requests_v1 as cloud


class Item26RestoredCloudRequestsV1Tests(unittest.TestCase):
    API_C = "i-api123"
    BUILDER = "i-builder123"
    PLAN_NONCE = "0123456789abcdef0123456789abcdef"
    COMMAND_RAW = b"#!/bin/bash\nprintf '%s\\n' fixture\n"

    def command(self, raw=None):
        raw = self.COMMAND_RAW if raw is None else raw
        encoded = base64.b64encode(raw)
        return {
            "base64": encoded.decode("ascii"),
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }

    def input_value(self, action="preflight_api_c", command=None):
        return {
            "action": action,
            "api_c_instance_id": self.API_C,
            "builder_instance_id": self.BUILDER,
            "command": self.command() if command is None else command,
            "plan_nonce": self.PLAN_NONCE,
        }

    def send_file_row(self, name, raw=b"fixture-bytes"):
        target_dir = cloud.SEND_FILE_TARGETS[name]
        encoded = base64.b64encode(raw)
        return {
            "evidence": {
                "content_base64_bytes": len(encoded),
                "content_sha256": hashlib.sha256(raw).hexdigest(),
            },
            "request": {
                "Content": encoded.decode("ascii"),
                "ContentType": "Base64",
                "Description": "noteai-item26-restored-v1-write-once",
                "FileGroup": "root",
                "FileMode": "0600",
                "FileOwner": "root",
                "InstanceId": [self.BUILDER],
                "Name": name,
                "Overwrite": False,
                "RegionId": "cn-shenzhen",
                "Tag": [{"Key": "noteai-task", "Value": "item26-restored-v1"}],
                "TargetDir": target_dir,
            },
        }

    def test_fixed_eleven_action_matrix(self):
        expected = {
            "preflight_api_c": (
                "noteai-item26-restored-preflight-api-c-20260822-v1",
                "api_c",
                120,
            ),
            "preflight_builder": (
                "noteai-item26-restored-preflight-builder-20260821-v1",
                "builder",
                120,
            ),
            "keygen_generate": (
                "noteai-item26-restored-keygen-generate-20260821-v1",
                "builder",
                120,
            ),
            "keygen_readback": (
                "noteai-item26-restored-keygen-readback-20260821-v1",
                "builder",
                120,
            ),
            "password_rewrap_create": (
                "noteai-item26-restored-password-rewrap-create-20260821-v1",
                "api_c",
                120,
            ),
            "password_rewrap_readback": (
                "noteai-item26-restored-password-rewrap-readback-20260821-v1",
                "api_c",
                120,
            ),
            "package_broker_create": (
                "noteai-item26-restored-package-broker-create-20260821-v1",
                "api_c",
                120,
            ),
            "package_broker_readback": (
                "noteai-item26-restored-package-broker-readback-20260821-v1",
                "api_c",
                120,
            ),
            "builder_stage_finalize": (
                "noteai-item26-restored-builder-stage-finalize-20260821-v1",
                "builder",
                120,
            ),
            "builder_stage_readback": (
                "noteai-item26-restored-builder-stage-readback-20260821-v1",
                "builder",
                120,
            ),
            "restored_capture": (
                "noteai-item26-restored-capture-20260821-v1",
                "builder",
                1500,
            ),
        }
        self.assertEqual(set(cloud.ACTIONS), set(expected))
        self.assertEqual(cloud.ACTION_ORDER, tuple(expected))
        for action, (name, target, timeout) in expected.items():
            row = cloud.ACTIONS[action]
            self.assertEqual((row.name, row.target, row.timeout), (name, target, timeout))

    def test_every_action_renders_one_exact_official_request(self):
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
        for action, spec in cloud.ACTIONS.items():
            with self.subTest(action=action):
                result = cloud.render_request(self.input_value(action))
                request = result["request"]
                target = self.API_C if spec.target == "api_c" else self.BUILDER
                self.assertEqual(set(request), exact_keys)
                self.assertEqual(request, {
                    "ClientToken": cloud.derive_client_tokens(self.PLAN_NONCE)[action],
                    "CommandContent": self.command()["base64"],
                    "ContentEncoding": "Base64",
                    "EnableParameter": False,
                    "InstanceId": [target],
                    "KeepCommand": True,
                    "Name": spec.name,
                    "RegionId": "cn-shenzhen",
                    "RepeatMode": "Once",
                    "Tag": [{"Key": "noteai-task", "Value": "item26-restored-v1"}],
                    "TerminationMode": "ProcessTree",
                    "Timeout": spec.timeout,
                    "Type": "RunShellScript",
                    "Username": "root",
                    "WorkingDir": "/root",
                })
                for forbidden in (
                    "Frequency",
                    "Parameters",
                    "ResourceTag",
                    "ContainerId",
                    "ContainerName",
                    "OssDelivery",
                ):
                    self.assertNotIn(forbidden, request)
                self.assertIs(type(request["EnableParameter"]), bool)
                self.assertIs(type(request["KeepCommand"]), bool)
                self.assertIs(type(request["Timeout"]), int)
                evidence = result["evidence"]
                request_raw = cloud.canonical(request)
                self.assertEqual(
                    evidence["request_canonical_sha256"],
                    hashlib.sha256(request_raw).hexdigest(),
                )
                self.assertEqual(evidence["request_canonical_bytes"], len(request_raw))

    def test_plan_nonce_derives_one_ordered_unique_token_per_action(self):
        tokens = cloud.derive_client_tokens(self.PLAN_NONCE)
        self.assertEqual(tuple(tokens), cloud.ACTION_ORDER)
        self.assertEqual(len(tokens), 11)
        self.assertEqual(len(set(tokens.values())), 11)
        for action, token in tokens.items():
            expected = hashlib.sha256(
                b"item26-restored-v1\x00"
                + self.PLAN_NONCE.encode("ascii")
                + b"\x00"
                + action.encode("ascii")
            ).hexdigest()
            self.assertEqual(token, expected)
            self.assertRegex(token, r"^[0-9a-f]{64}$")
        rendered = cloud.render_request(self.input_value())
        self.assertEqual(rendered["evidence"]["client_token_plan_count"], 11)
        self.assertNotIn(
            self.PLAN_NONCE,
            cloud.canonical(rendered).decode("ascii"),
        )

    def test_state_machine_and_prerequisite_contract_is_fail_closed(self):
        for action, spec in cloud.ACTIONS.items():
            with self.subTest(action=action):
                result = cloud.render_request(self.input_value(action))
                state = result["state"]
                self.assertEqual(state["initial"], "HISTORY_ZERO_REQUIRED")
                self.assertEqual(state["post_submit"], "PROVIDER_READBACK_ONLY")
                self.assertEqual(state["dispatch_count_limit"], 1)
                self.assertIs(state["automatic_retry_allowed"], False)
                self.assertIs(state["same_request_resubmit_allowed"], False)
                self.assertEqual(
                    state["provider_unknown_recovery"],
                    "READBACK_EXACT_CLIENT_TOKEN_NAME_TARGET_NEVER_RESUBMIT",
                )
                self.assertEqual(
                    state["terminal_command_recovery"], spec.terminal_recovery,
                )
                prerequisites = result["prerequisites"]
                self.assertEqual(
                    prerequisites["fresh_client_token_history_count_must_equal"], 0,
                )
                self.assertEqual(
                    prerequisites["fresh_exact_name_target_history_count_must_equal"], 0,
                )
                self.assertEqual(prerequisites["provider_reads_performed_by_renderer"], 0)
                self.assertIs(prerequisites["plan_nonce_emitted_by_renderer"], False)
                self.assertIs(
                    prerequisites["plan_nonce_must_be_retained_root_only"], True,
                )
                self.assertEqual(prerequisites["action_prerequisites"], list(spec.prerequisites))
                self.assertEqual(
                    state["terminal_exit_code"],
                    dict(cloud.TERMINAL_TRANSITIONS[action]),
                )
        self.assertEqual(
            cloud.ACTIONS["keygen_generate"].terminal_recovery,
            "DISPATCH_keygen_readback_ONLY_AFTER_TERMINAL_UNKNOWN",
        )
        self.assertEqual(
            cloud.ACTIONS["package_broker_create"].terminal_recovery,
            "DISPATCH_package_broker_readback_EXACTLY_ONCE_AFTER_EXIT_0_OR_4",
        )

    def test_command_binding_rejects_bad_base64_size_sha_and_bool_integer_aliases(self):
        mutations = []
        for key, value in (
            ("base64", "%%%="),
            ("bytes", True),
            ("bytes", self.command()["bytes"] + 1),
            ("sha256", "A" * 64),
            ("sha256", "a" * 63),
            ("sha256", "b" * 64),
        ):
            command = self.command()
            command[key] = value
            mutations.append(command)
        command = self.command()
        command["extra"] = 0
        mutations.append(command)
        command = self.command()
        del command["bytes"]
        mutations.append(command)
        oversized = base64.b64encode(b"x" * 13501)
        self.assertGreater(len(oversized), cloud.MAX_COMMAND_CONTENT_BYTES)
        mutations.append({
            "base64": oversized.decode("ascii"),
            "bytes": len(oversized),
            "sha256": hashlib.sha256(oversized).hexdigest(),
        })
        for index, command in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(cloud.RequestError):
                cloud.render_request(self.input_value(command=command))

    def test_ids_tokens_actions_and_top_level_schema_are_strict(self):
        changes = (
            ("action", "other"),
            ("action", 1),
            ("api_c_instance_id", "api123"),
            ("builder_instance_id", "i-BUILDER"),
            ("plan_nonce", ""),
            ("plan_nonce", "with space"),
            ("plan_nonce", "A" * 32),
            ("plan_nonce", "a" * 31),
            ("plan_nonce", True),
        )
        for key, value in changes:
            request = self.input_value()
            request[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(cloud.RequestError):
                cloud.render_request(request)
        same = self.input_value()
        same["builder_instance_id"] = same["api_c_instance_id"]
        with self.assertRaisesRegex(cloud.RequestError, "instance_distinct"):
            cloud.render_request(same)
        extra = self.input_value()
        extra["extra"] = False
        with self.assertRaisesRegex(cloud.RequestError, "input_contract"):
            cloud.render_request(extra)

    def test_run_command_validator_rejects_forbidden_fields_and_type_aliases(self):
        input_value = self.input_value("restored_capture")
        result = cloud.render_request(input_value)
        request = result["request"]
        mutations = []
        for key, value in (
            ("KeepCommand", 1),
            ("EnableParameter", 0),
            ("Timeout", True),
            ("Timeout", 120),
            ("Name", "other"),
            ("ClientToken", "f" * 64),
            ("TerminationMode", "Process"),
            ("Tag", [{"Key": "noteai-task", "Value": "other"}]),
            ("InstanceId", [self.BUILDER, self.API_C]),
        ):
            changed = copy.deepcopy(request)
            changed[key] = value
            mutations.append(changed)
        changed = copy.deepcopy(request)
        changed["Frequency"] = "0 0 * * *"
        mutations.append(changed)
        for index, changed in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(cloud.RequestError):
                cloud.validate_run_command(changed, input_value)

    def test_canonical_parser_rejects_noncanonical_and_duplicate_keys(self):
        value = self.input_value()
        canonical = cloud.canonical(value)
        self.assertEqual(cloud.parse_canonical(canonical), value)
        noncanonical = json.dumps(value, ensure_ascii=True).encode("ascii") + b"\n"
        self.assertNotEqual(noncanonical, canonical)
        with self.assertRaisesRegex(cloud.RequestError, "input_canonical"):
            cloud.parse_canonical(noncanonical)
        duplicate = (
            b'{"action":"preflight_api_c","action":"preflight_builder",'
            b'"api_c_instance_id":"i-api123","builder_instance_id":"i-builder123",'
            b'"command":{"base64":"YQ==","bytes":4,'
            b'"plan_nonce":"0123456789abcdef0123456789abcdef",'
            b'"sha256":"' + hashlib.sha256(b"YQ==").hexdigest().encode("ascii") + b'"}}\n'
        )
        with self.assertRaisesRegex(cloud.RequestError, "duplicate_json_key"):
            cloud.parse_canonical(duplicate)
        nested_duplicate = (
            b'{"action":"preflight_api_c","api_c_instance_id":"i-api123",'
            b'"builder_instance_id":"i-builder123",'
            b'"command":{"base64":"YQ==","base64":"Yg==","bytes":4,'
            b'"sha256":"' + hashlib.sha256(b"YQ==").hexdigest().encode("ascii") +
            b'"},"plan_nonce":"0123456789abcdef0123456789abcdef"}\n'
        )
        with self.assertRaisesRegex(cloud.RequestError, "duplicate_json_key"):
            cloud.parse_canonical(nested_duplicate)

    def test_both_send_file_rows_validate_with_raw_sha_and_no_client_token(self):
        self.assertEqual(
            cloud.SEND_FILE_ORDER,
            ("control-envelope.json", "restored-capture-transfer-v1.sh.gz"),
        )
        for name in cloud.SEND_FILE_TARGETS:
            with self.subTest(name=name):
                row = self.send_file_row(name)
                result = cloud.validate_send_file(
                    row["request"], row["evidence"], self.BUILDER,
                )
                self.assertEqual(result["name"], name)
                self.assertEqual(result["content_sha256_scope"], "decoded_raw_bytes")
                request_raw = cloud.canonical(row["request"])
                self.assertEqual(result["request_canonical_bytes"], len(request_raw))
                self.assertEqual(
                    result["request_canonical_sha256"],
                    hashlib.sha256(request_raw).hexdigest(),
                )
                self.assertNotIn("ClientToken", row["request"])
                self.assertIs(result["no_replay"]["send_file_has_client_token"], False)
                self.assertIs(result["no_replay"]["history_zero_required"], True)
                self.assertIs(result["no_replay"]["overwrite_must_be_false"], True)
                self.assertIs(result["no_replay"]["exact_name_required"], True)
                self.assertIs(
                    result["no_replay"]["describe_all_pages_required"], True,
                )
                self.assertEqual(
                    result["no_replay"]["provider_ack_unknown_allowed_action"],
                    "DESCRIBE_EXACT_NAME_INSTANCE_ALL_PAGES",
                )
                self.assertEqual(
                    result["no_replay"]["unknown_recovery"],
                    "DESCRIBE_EXACT_NAME_INSTANCE_ALL_PAGES_NEVER_RESEND",
                )

    def test_send_file_plan_requires_both_rows_once_in_fixed_order(self):
        rows = [
            self.send_file_row("control-envelope.json", b"envelope"),
            self.send_file_row("restored-capture-transfer-v1.sh.gz", b"transfer"),
        ]
        result = cloud.validate_send_file_plan(rows, self.BUILDER)
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(result["order"], list(cloud.SEND_FILE_ORDER))
        self.assertEqual(
            [row["name"] for row in result["files"]],
            list(cloud.SEND_FILE_ORDER),
        )
        self.assertRegex(result["plan_binding_sha256"], r"^[0-9a-f]{64}$")
        mutations = (
            list(reversed(rows)),
            [rows[0], rows[0]],
            rows[:1],
            rows + [rows[1]],
            tuple(rows),
        )
        for index, changed in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(cloud.RequestError):
                cloud.validate_send_file_plan(changed, self.BUILDER)
        changed = copy.deepcopy(rows)
        changed[0]["extra"] = 0
        with self.assertRaisesRegex(cloud.RequestError, "send_file_plan_row"):
            cloud.validate_send_file_plan(changed, self.BUILDER)

    def test_send_file_validator_rejects_wrong_shape_target_types_and_evidence(self):
        original = self.send_file_row("control-envelope.json")
        cases = []
        for key, value in (
            ("Name", "other"),
            ("TargetDir", "/tmp"),
            ("FileMode", 600),
            ("Overwrite", 0),
            ("Overwrite", True),
            ("InstanceId", [self.BUILDER, self.API_C]),
            ("Tag", [{"Key": "noteai-task", "Value": "other"}]),
            ("Content", "%%%="),
        ):
            row = copy.deepcopy(original)
            row["request"][key] = value
            cases.append(row)
        row = copy.deepcopy(original)
        row["request"]["ClientToken"] = "f" * 64
        cases.append(row)
        row = copy.deepcopy(original)
        row["evidence"]["content_base64_bytes"] = True
        cases.append(row)
        row = copy.deepcopy(original)
        row["evidence"]["content_sha256"] = "f" * 64
        cases.append(row)
        row = copy.deepcopy(original)
        row["evidence"]["extra"] = 0
        cases.append(row)
        for index, row in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(cloud.RequestError):
                cloud.validate_send_file(
                    row["request"], row["evidence"], self.BUILDER,
                )

    def test_send_file_base64_limit_is_enforced(self):
        encoded = base64.b64encode(b"x" * 13501)
        self.assertGreater(len(encoded), cloud.MAX_SEND_FILE_CONTENT_BYTES)
        row = self.send_file_row("restored-capture-transfer-v1.sh.gz")
        row["request"]["Content"] = encoded.decode("ascii")
        row["evidence"] = {
            "content_base64_bytes": len(encoded),
            "content_sha256": hashlib.sha256(b"x" * 13501).hexdigest(),
        }
        with self.assertRaisesRegex(cloud.RequestError, "send_file_content"):
            cloud.validate_send_file(row["request"], row["evidence"], self.BUILDER)

    def test_cli_stdin_to_canonical_stdout_and_known_failure_to_stderr_rc2(self):
        request = cloud.canonical(self.input_value("keygen_generate"))
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(request)
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

        bad = self.input_value()
        bad["command"]["bytes"] = False
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
            r"^ITEM26_RESTORED_CLOUD_REQUEST_FAILED:[a-z0-9_]+\n$",
        )


if __name__ == "__main__":
    unittest.main()
