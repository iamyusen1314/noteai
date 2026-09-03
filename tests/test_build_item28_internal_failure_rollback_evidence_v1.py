import base64
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_item28_internal_failure_rollback_evidence_v1 as builder  # noqa: E402
import render_item28_internal_failure_rollback_request_v1 as renderer  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "item28_executor_for_builder_test",
    ROOT / "deploy" / "production" / "internal_failure_rollback.py",
)
executor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(executor)


def canonical_response(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def renderer_input():
    return {
        "action": renderer.ACTION,
        "plan_nonce": "1" * 32,
        "api_f_instance_id": "i-abc123",
        "item25_terminal_acceptance_sha256": "a" * 64,
        "item26_terminal_acceptance_sha256": "b" * 64,
        "item27_terminal_acceptance_sha256": "c" * 64,
    }


def result_payload():
    health = [
        {"path": "/health/live", "status": 200, "state": "ok"},
        {"path": "/health/ready", "status": 200, "state": "ready"},
    ]
    baseline = {
        "release_identity_sha256": "e" * 64,
        "health": copy.deepcopy(health),
    }
    final = copy.deepcopy(baseline)
    guardian = {
        "schema": "noteai.item28.guardian-result.v1",
        "status": "RESTORED",
        "dropin_removed": True,
        "daemon_reload_count": 1,
        "runtime_start_count": 1,
        "volatile_residue_count": 0,
    }
    return executor.result_payload(baseline, final, guardian, 1)


def empty_page(request_id, container, item):
    return {
        "RequestId": request_id,
        "PageNumber": 1,
        "PageSize": builder.PAGE_SIZE,
        "TotalCount": 0,
        container: {item: []},
    }


def capture_fixture():
    value = renderer_input()
    request, _validation = renderer.render_request(value)
    target = value["api_f_instance_id"]
    command_id = "c-command"
    invoke_id = "t-invoke"
    page = {"PageNumber": 1, "PageSize": builder.PAGE_SIZE}
    result = result_payload()
    command_row = {
        "CommandId": command_id,
        "Name": request["Name"],
        "Type": request["Type"],
        "CommandContent": request["CommandContent"],
        "Timeout": request["Timeout"],
        "WorkingDir": request["WorkingDir"],
        "EnableParameter": request["EnableParameter"],
        "Description": "documented extra field",
    }
    invocation_row = {
        "CommandId": command_id,
        "InvokeId": invoke_id,
        "CommandName": request["Name"],
        "InvocationStatus": "Success",
        "InvokeStatus": "Finished",
        "RepeatMode": "Once",
        "Username": "root",
        "TerminationMode": "ProcessTree",
        "InvokeInstances": {"InvokeInstance": [{
            "InstanceId": target,
            "InvocationStatus": "Success",
            "InstanceInvokeStatus": "Finished",
            "ExitCode": 0,
            "Dropped": 0,
            "Repeats": 1,
            "DocumentedExtra": True,
        }]},
        "DocumentedExtra": "allowed",
    }
    provider_result = {
        "CommandId": command_id,
        "InvokeId": invoke_id,
        "InstanceId": target,
        "InvocationStatus": "Success",
        "ExitCode": 0,
        "Dropped": 0,
        "Repeats": 1,
        "Output": base64.b64encode(renderer.canonical(result)).decode(),
        "StartTime": "2026-08-14T00:00:00Z",
        "FinishedTime": "2026-08-14T00:01:00Z",
        "ErrorCode": "",
        "ErrorInfo": "",
        "DocumentedExtra": 1,
    }
    values = {
        "renderer-input.json": renderer.canonical(value),
        "run-command-request.json": renderer.canonical(request),
        "run-command-response.json": canonical_response({
            "RequestId": "request-run", "CommandId": command_id,
            "InvokeId": invoke_id,
        }),
        "pre-describe-commands-request.json": renderer.canonical({
            "RegionId": renderer.REGION, "Name": request["Name"], **page,
        }),
        "pre-describe-commands.json": canonical_response(
            empty_page("request-pre-commands", "Commands", "Command")
        ),
        "pre-describe-invocations-request.json": renderer.canonical({
            "RegionId": renderer.REGION, "CommandName": request["Name"], **page,
        }),
        "pre-describe-invocations.json": canonical_response(
            empty_page("request-pre-invocations", "Invocations", "Invocation")
        ),
        "terminal-describe-commands-request.json": renderer.canonical({
            "RegionId": renderer.REGION, "CommandId": command_id,
            "Name": request["Name"], **page,
        }),
        "terminal-describe-commands.json": canonical_response({
            "RequestId": "request-terminal-commands", **page,
            "TotalCount": 1, "Commands": {"Command": [command_row]},
        }),
        "terminal-describe-invocations-request.json": renderer.canonical({
            "RegionId": renderer.REGION, "CommandId": command_id,
            "InvokeId": invoke_id, "InstanceId": target, **page,
        }),
        "terminal-describe-invocations.json": canonical_response({
            "RequestId": "request-terminal-invocations", **page,
            "TotalCount": 1, "Invocations": {"Invocation": [invocation_row]},
        }),
        "terminal-describe-results-request.json": renderer.canonical({
            "RegionId": renderer.REGION, "CommandId": command_id,
            "InvokeId": invoke_id, "InstanceId": target, **page,
        }),
        "terminal-describe-results.json": canonical_response({
            "RequestId": "request-terminal-results",
            "Invocation": {
                **page, "TotalCount": 1,
                "InvocationResults": {"InvocationResult": [provider_result]},
            },
        }),
    }
    return {name: values[name] for name in builder.CAPTURE_FILES}


def build(capture=None):
    return builder.build_receipt(
        capture or capture_fixture(), source_revision="d" * 40,
        observed_at_utc="2026-08-14T00:02:00Z",
    )


class Item28EvidenceBuilderTests(unittest.TestCase):
    def test_official_raw_projection_builds_secret_free_receipt(self):
        receipt = build()

        self.assertEqual(receipt["status"], "PROVIDER_TERMINAL_VERIFIED")
        self.assertEqual(receipt["pre_dispatch"]["exact_command_name_history_count"], 0)
        self.assertEqual(receipt["pre_dispatch"]["exact_invocation_name_history_count"], 0)
        self.assertFalse(receipt["pre_dispatch"]["provider_client_token_readback_supported"])
        self.assertEqual(receipt["terminal_readback"]["provider_status"], "Finished")
        self.assertEqual(receipt["terminal_readback"]["repeat_count"], 1)
        self.assertEqual(receipt["execution_boundary"]["dispatch_count"], 1)
        self.assertEqual(receipt["execution_boundary"]["automatic_retry_count"], 0)
        self.assertNotIn("i-abc123", json.dumps(receipt))
        self.assertNotIn("c-command", json.dumps(receipt))
        self.assertNotIn("t-invoke", json.dumps(receipt))
        self.assertNotIn(request_token(capture_fixture()), json.dumps(receipt))


    def test_root_only_capture_loader_rejects_extra_and_linked_files(self):
        capture = capture_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "capture"
            directory.mkdir(mode=0o700)
            for name, raw in capture.items():
                path = directory / name
                path.write_bytes(raw)
                path.chmod(0o600)
            loaded = builder.load_root_only_capture(directory)
            self.assertEqual(loaded, capture)

            extra = directory / "extra.json"
            extra.write_text("{}")
            extra.chmod(0o600)
            with self.assertRaisesRegex(builder.ClosureError, "capture_root_identity"):
                builder.load_root_only_capture(directory)
            extra.unlink()

            linked = Path(temp_dir) / "linked-copy"
            os.link(directory / builder.CAPTURE_FILES[0], linked)
            with self.assertRaisesRegex(builder.ClosureError, "capture_file_identity"):
                builder.load_root_only_capture(directory)

    def test_nonzero_history_and_incomplete_page_fail_closed(self):
        capture = capture_fixture()
        body = json.loads(capture["pre-describe-commands.json"])
        body["TotalCount"] = 1
        body["Commands"]["Command"] = [{"Name": renderer.COMMAND_NAME}]
        capture["pre-describe-commands.json"] = canonical_response(body)
        with self.assertRaisesRegex(builder.ClosureError, "pre_commands_incomplete_page"):
            build(capture)

        capture = capture_fixture()
        body = json.loads(capture["terminal-describe-commands.json"])
        body["TotalCount"] = 2
        capture["terminal-describe-commands.json"] = canonical_response(body)
        with self.assertRaisesRegex(builder.ClosureError, "incomplete_page"):
            build(capture)

    def test_legacy_or_wrong_provider_status_shapes_fail(self):
        capture = capture_fixture()
        body = json.loads(capture["terminal-describe-invocations.json"])
        row = body["Invocations"]["Invocation"][0]
        row.pop("InvokeInstances")
        row["TotalCount"] = 1
        capture["terminal-describe-invocations.json"] = canonical_response(body)
        with self.assertRaises(builder.ClosureError):
            build(capture)

        capture = capture_fixture()
        body = json.loads(capture["terminal-describe-invocations.json"])
        body["Invocations"]["Invocation"][0]["InvokeStatus"] = "Running"
        capture["terminal-describe-invocations.json"] = canonical_response(body)
        with self.assertRaisesRegex(builder.ClosureError, "terminal_invocation_result"):
            build(capture)

    def test_result_counter_drift_and_boolean_alias_fail(self):
        for key, replacement in (
            ("provider_call_count", 1),
            ("restart_attempt_count", True),
            ("original_release_restored", 1),
        ):
            capture = capture_fixture()
            body = json.loads(capture["terminal-describe-results.json"])
            row = body["Invocation"]["InvocationResults"]["InvocationResult"][0]
            value = json.loads(base64.b64decode(row["Output"]))
            value[key] = replacement
            row["Output"] = base64.b64encode(renderer.canonical(value)).decode()
            capture["terminal-describe-results.json"] = canonical_response(body)
            with self.assertRaisesRegex(builder.ClosureError, "result_semantics", msg=key):
                build(capture)

    def test_raw_body_tamper_changes_receipt_commitment(self):
        first = build()
        capture = capture_fixture()
        body = json.loads(capture["terminal-describe-results.json"])
        body["DocumentedExtra"] = "changed but supported"
        capture["terminal-describe-results.json"] = canonical_response(body)
        second = build(capture)

        self.assertNotEqual(
            first["terminal_readback"]["results_response_raw_sha256"],
            second["terminal_readback"]["results_response_raw_sha256"],
        )
        self.assertEqual(first["result"], second["result"])

def request_token(capture):
    return json.loads(capture["run-command-request.json"])["ClientToken"]


if __name__ == "__main__":
    unittest.main()
