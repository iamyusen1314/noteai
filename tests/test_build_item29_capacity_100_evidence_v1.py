import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_item29_capacity_100_evidence_v1 as builder
import render_item29_capacity_100_request_v1 as renderer
from tests.test_capacity_100_jobs import FakeRuntime, ITEM28, PLAN_NONCE, capacity


def raw(value):
    return (json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ) + "\n").encode("ascii")


def page(request_id, container, item, rows):
    return {
        "RequestId": request_id,
        "PageNumber": 1,
        "PageSize": 50,
        "TotalCount": len(rows),
        container: {item: rows},
    }


class BuildItem29EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = capacity.run_rehearsal(
            FakeRuntime(), plan_nonce=PLAN_NONCE, item28_dependency=ITEM28
        )
        cls.renderer_input = {
            "action": renderer.ACTION,
            "plan_nonce": PLAN_NONCE,
            "api_c_instance_id": "i-item29fixture",
            "item28_dependency": ITEM28,
        }
        with mock.patch.object(
            renderer, "FROZEN_ITEM28_DEPENDENCY", ITEM28
        ), mock.patch.object(renderer, "PRODUCTION_RUNTIME_ADAPTER_BOUND", True):
            cls.request, _validation = renderer.render_request(cls.renderer_input)

    def capture(self):
        command_id = "c-item29fixture"
        invoke_id = "t-item29fixture"
        target = "i-item29fixture"
        command = {
            "CommandId": command_id,
            "Name": renderer.COMMAND_NAME,
            "Type": "RunShellScript",
            "CommandContent": self.request["CommandContent"],
            "Timeout": self.request["Timeout"],
            "WorkingDir": self.request["WorkingDir"],
            "EnableParameter": self.request["EnableParameter"],
        }
        instance = {
            "InstanceId": target,
            "InstanceInvokeStatus": "Finished",
            "InvocationStatus": "Success",
            "ExitCode": 0,
            "Dropped": 0,
            "Repeats": 1,
        }
        invocation = {
            "CommandId": command_id,
            "InvokeId": invoke_id,
            "CommandName": renderer.COMMAND_NAME,
            "InvokeStatus": "Finished",
            "InvocationStatus": "Success",
            "RepeatMode": "Once",
            "Username": "root",
            "TerminationMode": "ProcessTree",
            "InvokeInstances": {"InvokeInstance": [instance]},
        }
        provider_result = {
            "CommandId": command_id,
            "InvokeId": invoke_id,
            "InstanceId": target,
            "InvocationStatus": "Success",
            "ExitCode": 0,
            "Dropped": 0,
            "Repeats": 1,
            "StartTime": "2026-08-14T01:00:00Z",
            "FinishedTime": "2026-08-14T01:01:00Z",
            "Output": base64.b64encode(raw(self.result)).decode("ascii"),
        }
        values = {
            "renderer-input.json": raw(self.renderer_input),
            "run-command-request.json": raw(self.request),
            "run-command-response.json": raw({
                "RequestId": "req-run", "CommandId": command_id,
                "InvokeId": invoke_id,
            }),
            "pre-describe-commands-request.json": raw({
                "RegionId": renderer.REGION,
                "Name": renderer.COMMAND_NAME,
                "PageNumber": 1,
                "PageSize": 50,
            }),
            "pre-describe-commands.json": raw(
                page("req-pre-command", "Commands", "Command", [])
            ),
            "pre-describe-invocations-request.json": raw({
                "RegionId": renderer.REGION,
                "CommandName": renderer.COMMAND_NAME,
                "PageNumber": 1,
                "PageSize": 50,
            }),
            "pre-describe-invocations.json": raw(
                page("req-pre-invocation", "Invocations", "Invocation", [])
            ),
            "terminal-describe-commands-request.json": raw({
                "RegionId": renderer.REGION,
                "CommandId": command_id,
                "Name": renderer.COMMAND_NAME,
                "PageNumber": 1,
                "PageSize": 50,
            }),
            "terminal-describe-commands.json": raw(
                page("req-terminal-command", "Commands", "Command", [command])
            ),
            "terminal-describe-invocations-request.json": raw({
                "RegionId": renderer.REGION,
                "CommandId": command_id,
                "InvokeId": invoke_id,
                "InstanceId": target,
                "PageNumber": 1,
                "PageSize": 50,
            }),
            "terminal-describe-invocations.json": raw(
                page(
                    "req-terminal-invocation", "Invocations", "Invocation",
                    [invocation],
                )
            ),
            "terminal-describe-results-request.json": raw({
                "RegionId": renderer.REGION,
                "CommandId": command_id,
                "InvokeId": invoke_id,
                "InstanceId": target,
                "PageNumber": 1,
                "PageSize": 50,
            }),
            "terminal-describe-results.json": raw({
                "RequestId": "req-results",
                "Invocation": {
                    "PageNumber": 1, "PageSize": 50, "TotalCount": 1,
                    "InvocationResults": {"InvocationResult": [provider_result]},
                },
            }),
        }
        return {name: values[name] for name in builder.CAPTURE_FILES}

    def build(self, capture=None):
        with tempfile.TemporaryDirectory() as directory:
            capture_dir = Path(directory)
            capture_dir.chmod(0o700)
            for name, value in (capture or self.capture()).items():
                path = capture_dir / name
                path.write_bytes(value)
                path.chmod(0o600)
            with mock.patch.object(builder, "ROOT_UID", os.getuid()):
                closure = builder.load_root_only_capture(capture_dir)
            with mock.patch.object(
                renderer, "FROZEN_ITEM28_DEPENDENCY", ITEM28
            ), mock.patch.object(renderer, "PRODUCTION_RUNTIME_ADAPTER_BOUND", True):
                return builder.build_receipt(
                    closure,
                    source_revision="a" * 40,
                    observed_at_utc="2026-08-14T01:02:00Z",
                )

    def test_builds_secret_free_exact_receipt(self):
        receipt = self.build()
        self.assertEqual(receipt["status"], "PROVIDER_TERMINAL_VERIFIED")
        self.assertEqual(receipt["pre_dispatch"]["history_key"], "Name")
        self.assertFalse(
            receipt["pre_dispatch"]["provider_client_token_readback_supported"]
        )
        self.assertEqual(receipt["result_binding"]["admission_count"], 100)
        self.assertEqual(receipt["result_binding"]["takeover_count"], 2)
        self.assertTrue(
            receipt["raw_closure"][
                "raw_provider_bodies_retained_root_only"
            ]
        )
        self.assertGreater(
            receipt["raw_closure"]["capture_manifest_canonical_bytes"], 0
        )
        self.assertEqual(
            receipt["execution_boundary"]["wrapper_host_temp_residue_count"],
            0,
        )
        self.assertTrue(
            receipt["execution_boundary"][
                "wrapper_temp_residue_absence_audited_before_output"
            ]
        )
        serialized = json.dumps(receipt)
        self.assertNotIn("i-item29fixture", serialized)
        self.assertNotIn("c-item29fixture", serialized)
        self.assertNotIn("t-item29fixture", serialized)
        self.assertNotIn(self.request["ClientToken"], serialized)

    def test_rejects_nonzero_history_and_repeated_provider_attempt(self):
        capture = self.capture()
        history = json.loads(capture["pre-describe-commands.json"])
        history["Commands"]["Command"] = [{"Name": renderer.COMMAND_NAME}]
        history["TotalCount"] = 1
        capture["pre-describe-commands.json"] = raw(history)
        with self.assertRaisesRegex(
            builder.EvidenceError,
            "pre_commands_incomplete_page|name_history_nonzero",
        ):
            self.build(capture)

        capture = self.capture()
        body = json.loads(capture["terminal-describe-results.json"])
        body["Invocation"]["InvocationResults"]["InvocationResult"][0]["Repeats"] = 2
        capture["terminal-describe-results.json"] = raw(body)
        with self.assertRaisesRegex(builder.EvidenceError, "provider_result"):
            self.build(capture)

    def test_rejects_result_count_drift(self):
        capture = self.capture()
        body = json.loads(capture["terminal-describe-results.json"])
        result = copy.deepcopy(self.result)
        result["runtime_projection"]["succeeded_count"] = 99
        body["Invocation"]["InvocationResults"]["InvocationResult"][0][
            "Output"
        ] = base64.b64encode(raw(result)).decode("ascii")
        capture["terminal-describe-results.json"] = raw(body)
        with self.assertRaisesRegex(builder.EvidenceError, "result_semantics"):
            self.build(capture)

    def test_raw_numeric_bool_float_and_string_aliases_are_rejected(self):
        attacks = (
            ("bool", "terminal-describe-results.json", lambda body: body[
                "Invocation"
            ].__setitem__("PageNumber", True)),
            ("float", "terminal-describe-results.json", lambda body: body[
                "Invocation"
            ]["InvocationResults"]["InvocationResult"][0].__setitem__(
                "ExitCode", 0.0
            )),
            ("string", "terminal-describe-invocations.json", lambda body: body[
                "Invocations"
            ]["Invocation"][0]["InvokeInstances"]["InvokeInstance"][0].__setitem__(
                "Repeats", "1"
            )),
        )
        for label, filename, mutate in attacks:
            with self.subTest(alias=label):
                capture = self.capture()
                body = json.loads(capture[filename])
                mutate(body)
                capture[filename] = raw(body)
                with self.assertRaises(builder.EvidenceError):
                    self.build(capture)

    def test_builder_rejects_unverified_dictionary_capture(self):
        with self.assertRaisesRegex(
            builder.EvidenceError, "capture_loader_required"
        ):
            builder.build_receipt(
                self.capture(),
                source_revision="a" * 40,
                observed_at_utc="2026-08-14T01:02:00Z",
            )

    def _capture_directory(self, base):
        capture_dir = Path(base)
        capture_dir.chmod(0o700)
        for name, value in self.capture().items():
            path = capture_dir / name
            path.write_bytes(value)
            path.chmod(0o600)
        return capture_dir

    def test_loader_requires_exact_0700_0600_inventory_and_nlink_one(self):
        cases = ("directory_mode", "file_mode", "extra", "symlink", "hardlink")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                capture_dir = self._capture_directory(directory)
                target = capture_dir / builder.CAPTURE_FILES[-1]
                if case == "directory_mode":
                    capture_dir.chmod(0o755)
                elif case == "file_mode":
                    target.chmod(0o644)
                elif case == "extra":
                    extra = capture_dir / "extra.json"
                    extra.write_bytes(b"{}\n")
                    extra.chmod(0o600)
                elif case == "symlink":
                    target.unlink()
                    target.symlink_to(builder.CAPTURE_FILES[0])
                elif case == "hardlink":
                    target.unlink()
                    os.link(capture_dir / builder.CAPTURE_FILES[0], target)
                with mock.patch.object(builder, "ROOT_UID", os.getuid()):
                    with self.assertRaises(builder.EvidenceError):
                        builder.load_root_only_capture(capture_dir)

    def test_loader_manifest_is_exact_and_security_derived(self):
        with tempfile.TemporaryDirectory() as directory:
            capture_dir = self._capture_directory(directory)
            if os.getuid() != builder.ROOT_UID:
                with self.assertRaisesRegex(
                    builder.EvidenceError, "capture_directory_identity"
                ):
                    builder.load_root_only_capture(capture_dir)
            with mock.patch.object(builder, "ROOT_UID", os.getuid()):
                closure = builder.load_root_only_capture(capture_dir)
            manifest = json.loads(closure.capture_manifest)
            self.assertEqual(
                [row["name"] for row in manifest["files"]],
                list(builder.CAPTURE_FILES),
            )
            self.assertEqual(
                manifest["security"]["exact_inventory"],
                list(builder.CAPTURE_FILES),
            )
            self.assertTrue(closure.raw_provider_bodies_retained_root_only)
            self.assertEqual(closure.raw_provider_value_emitted_count, 0)

    def test_cli_consumes_only_strict_loader_closure_and_writes_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            capture_dir = base / "capture"
            capture_dir.mkdir()
            self._capture_directory(capture_dir)
            output = base / "receipt.json"
            with mock.patch.object(
                builder, "ROOT_UID", os.getuid()
            ), mock.patch.object(
                renderer, "FROZEN_ITEM28_DEPENDENCY", ITEM28
            ), mock.patch.object(renderer, "PRODUCTION_RUNTIME_ADAPTER_BOUND", True):
                status = builder.main([
                    str(capture_dir),
                    "--source-revision", "a" * 40,
                    "--observed-at-utc", "2026-08-14T01:02:00Z",
                    "--output", str(output),
                ])
            self.assertEqual(status, 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                json.loads(output.read_bytes())["raw_closure"][
                    "raw_provider_bodies_retained_root_only"
                ],
                True,
            )


if __name__ == "__main__":
    unittest.main()
