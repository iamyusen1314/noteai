import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_item27_internal_smoke_evidence_v1 as builder
import render_item27_internal_smoke_requests_v1 as renderer


# Mirrors the complete optional field sets in Alibaba Cloud's generated
# ECS 2014-05-26 response models.  The builder must project only the required
# fields while committing the bytes of every optional field below.
OFFICIAL_COMMAND_FIELDS = {
    "Category", "CommandContent", "CommandId", "CreationTime",
    "Description", "EnableParameter", "InvokeTimes", "Latest", "Launcher",
    "Name", "ParameterDefinitions", "ParameterNames", "Provider",
    "ResourceGroupId", "Tags", "Timeout", "Type", "Version", "WorkingDir",
}
OFFICIAL_INVOCATION_FIELDS = {
    "CommandContent", "CommandDescription", "CommandId", "CommandName",
    "CommandType", "ContainerId", "ContainerName", "CreationTime",
    "Frequency", "InvocationStatus", "InvokeId", "InvokeInstances",
    "InvokeStatus", "Launcher", "OssOutputDelivery", "Parameters",
    "RepeatMode", "Tags", "TerminationMode", "Timed", "Timeout", "Username",
    "WorkingDir",
}
OFFICIAL_INVOKE_INSTANCE_FIELDS = {
    "CreationTime", "Dropped", "ErrorCode", "ErrorInfo", "ExitCode",
    "FinishTime", "InstanceId", "InstanceInvokeStatus", "InvocationStatus",
    "OssOutputErrorCode", "OssOutputErrorInfo", "OssOutputStatus",
    "OssOutputUri", "Output", "Repeats", "StartTime", "StopTime", "Timed",
    "UpdateTime",
}
OFFICIAL_INVOCATION_RESULT_FIELDS = {
    "CommandId", "ContainerId", "ContainerName", "Dropped", "ErrorCode",
    "ErrorInfo", "ExitCode", "FinishedTime", "InstanceId",
    "InvocationStatus", "InvokeId", "InvokeRecordStatus", "Launcher",
    "OssOutputDelivery", "OssOutputErrorCode", "OssOutputErrorInfo",
    "OssOutputStatus", "OssOutputUri", "Output", "Repeats", "StartTime",
    "StopTime", "Tags", "TerminationMode", "Username",
}


def _raw(value):
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )


def _result(action):
    mode = renderer.ACTIONS[action].host_mode
    roles = {
        "api_c": ("dispatcher", "payment"),
        "api_f": ("trends", "tracking"),
        "worker_c": ("worker",),
        "worker_f": ("worker",),
    }[action]
    endpoints = []
    if mode in {"api-c", "api-f"}:
        endpoints = [
            {"path": "/health/live", "status": 200, "service": "noteai-api", "state": "ok"},
            {
                "path": "/health/ready", "status": 200, "service": "noteai-api",
                "state": "ready", "checks": ["database", "model"],
            },
            {"path": "/legal/contracts", "status": 200, "sha256": "a" * 64},
            {"path": "/billing/tiers", "status": 200, "sha256": "b" * 64},
            {
                "path": "/payments/capabilities", "status": 200,
                "ordering_available": False, "currency": "CNY", "auto_renewal": False,
            },
        ]
    if mode == "api-c":
        endpoints.extend([
            {"path": "/health/live", "status": 200, "service": "noteai-admin", "state": "ok"},
            {
                "path": "/health/ready", "status": 200, "service": "noteai-admin",
                "state": "ready", "checks": ["database", "model"],
            },
            {"path": "/admin/capabilities", "status": 403, "authorization": "REJECTED"},
        ])
    role_rows = []
    for role in roles:
        row = {
            "role": role, "health_passed": True,
            "suspended_one_shot_passed": role != "payment",
            "expected_negative_passed": role == "payment",
        }
        if role == "dispatcher":
            row.update({"pending_outbox": 1, "exhausted_outbox": 0})
        elif role == "worker":
            row.update({
                "needs_manual": 0, "expired_ready": 0,
                "stale_provider_outcome": 0, "recoverable_unstarted": 1,
            })
        elif role == "trends":
            row["provider_attempt_counts"] = {"active": 0, "unknown": 0, "unlinked": 0}
        elif role == "tracking":
            row["provider_attempt_counts"] = {"active": 0, "stale": 0, "unlinked": 0}
        role_rows.append(row)
    return {
        "schema": builder.RESULT_SCHEMA, "task_id": builder.TASK_ID,
        "status": "PASS", "mode": mode,
        "loopback_endpoint_count": len(endpoints),
        "endpoint_projections": endpoints, "roles": role_rows,
        "active_runtime_identity_unchanged": True, "public_listener_count": 0,
        "service_start_count": len(roles), "service_stop_count": len(roles),
        "original_state_restored": True, "provider_call_count": 0,
        "provider_attempt_count": 0, "oss_mutation_count": 0,
        "production_database_mutation_count": 0, "synthetic_record_count": 0,
        "public_request_count": 0, "cleanup": "RESTORED",
        "automatic_retry_allowed": False,
        "same_invocation_replay_allowed": False,
    }


def make_capture(action="api_c", predecessor_acceptance=None):
    instances = {
        "api_c_instance_id": "i-apic123",
        "api_f_instance_id": "i-apif123",
        "worker_c_instance_id": "i-workerc123",
        "worker_f_instance_id": "i-workerf123",
    }
    input_value = {
        "action": action,
        "plan_nonce": "0123456789abcdef0123456789abcdef",
        "predecessor_acceptance_sha256": (
            predecessor_acceptance or "0" * 64
        ),
        **instances,
    }
    rendered = renderer.render_request(input_value)
    request = rendered["request"]
    spec = renderer.ACTIONS[action]
    target = request["InstanceId"][0]
    command_id = "cmd-" + action
    invoke_id = "invoke-" + action
    result = _result(action)
    ordinal = renderer.ACTION_ORDER.index(action) + 1
    start_time = f"2026-08-13T01:00:0{ordinal * 2 - 1}Z"
    finished_time = f"2026-08-13T01:00:0{ordinal * 2}Z"
    page = {"PageNumber": 1, "PageSize": builder.DESCRIBE_PAGE_SIZE}
    pre_commands_request = {
        "RegionId": renderer.REGION, "Name": request["Name"], **page,
    }
    pre_invocations_request = {
        "RegionId": renderer.REGION, "CommandName": request["Name"],
        **page,
    }
    terminal_commands_request = {
        "RegionId": renderer.REGION, "CommandId": command_id,
        "Name": request["Name"], **page,
    }
    terminal_invocations_request = {
        "RegionId": renderer.REGION, "CommandId": command_id,
        "InvokeId": invoke_id, "InstanceId": target, **page,
    }
    terminal_results_request = copy.deepcopy(terminal_invocations_request)
    capture = {
        "renderer-input.json": renderer.canonical(input_value),
        "run-command-request.json": renderer.canonical(request),
        "run-command-response.json": _raw({
            "RequestId": "request-run-" + action,
            "CommandId": command_id,
            "InvokeId": invoke_id,
        }),
        "pre-describe-commands-request.json": renderer.canonical(
            pre_commands_request
        ),
        "pre-describe-commands.json": _raw({
            "RequestId": "request-pre-commands-" + action,
            "PageNumber": 1,
            "PageSize": 50,
            "TotalCount": 0,
            "NextToken": "",
            "Commands": {"Command": []},
        }),
        "pre-describe-invocations-request.json": renderer.canonical(
            pre_invocations_request
        ),
        "pre-describe-invocations.json": _raw({
            "RequestId": "request-pre-invocations-" + action,
            "PageNumber": 1,
            "PageSize": 50,
            "TotalCount": 0,
            "NextToken": "",
            "Invocations": {"Invocation": []},
        }),
        "terminal-describe-commands-request.json": renderer.canonical(
            terminal_commands_request
        ),
        "terminal-describe-commands.json": _raw({
            "RequestId": "request-terminal-commands-" + action,
            "PageNumber": 1,
            "PageSize": 50,
            "TotalCount": 1,
            "NextToken": "",
            "Commands": {"Command": [{
                "Category": "",
                "CommandId": command_id,
                "Description": "official provider field retained in raw body",
                "CreationTime": start_time,
                "InvokeTimes": 1,
                "Latest": False,
                "Launcher": "",
                "ParameterDefinitions": {"ParameterDefinition": []},
                "ParameterNames": {"ParameterName": []},
                "Provider": "",
                "ResourceGroupId": "",
                "Tags": {"Tag": [{
                    "TagKey": "noteai-task",
                    "TagValue": "item27-internal-smoke-v1",
                }]},
                "Version": 1,
                **{
                    key: request[key]
                    for key in (
                        "Name", "Type", "CommandContent", "Timeout",
                        "WorkingDir", "EnableParameter",
                    )
                },
            }]},
        }),
        "terminal-describe-invocations-request.json": renderer.canonical(
            terminal_invocations_request
        ),
        "terminal-describe-invocations.json": _raw({
            "RequestId": "request-terminal-invocations-" + action,
            "PageNumber": 1,
            "PageSize": 50,
            "TotalCount": 1,
            "NextToken": "",
            "Invocations": {"Invocation": [{
                "CommandContent": request["CommandContent"],
                "CommandDescription": "official provider field retained in raw body",
                "CommandId": command_id,
                "InvokeId": invoke_id,
                "CommandName": request["Name"],
                "CommandType": request["Type"],
                "ContainerId": "",
                "ContainerName": "",
                "CreationTime": start_time,
                "Frequency": "",
                "InvocationStatus": "Success",
                "InvokeStatus": "Finished",
                "Launcher": "",
                "OssOutputDelivery": "",
                "Parameters": "{}",
                "Username": request["Username"],
                "RepeatMode": request["RepeatMode"],
                "TerminationMode": request["TerminationMode"],
                "Tags": {"Tag": [{
                    "TagKey": "noteai-task",
                    "TagValue": "item27-internal-smoke-v1",
                }]},
                "Timed": False,
                "Timeout": request["Timeout"],
                "WorkingDir": request["WorkingDir"],
                "InvokeInstances": {"InvokeInstance": [{
                    "CreationTime": start_time,
                    "InstanceId": target,
                    "InvocationStatus": "Success",
                    "InstanceInvokeStatus": "Finished",
                    "ExitCode": 0,
                    "Dropped": 0,
                    "ErrorCode": "",
                    "ErrorInfo": "",
                    "OssOutputErrorCode": "",
                    "OssOutputErrorInfo": "",
                    "OssOutputStatus": "",
                    "OssOutputUri": "",
                    "Output": "",
                    "Repeats": 1,
                    "StartTime": start_time,
                    "FinishTime": finished_time,
                    "StopTime": "",
                    "Timed": False,
                    "UpdateTime": finished_time,
                }]},
            }]},
        }),
        "terminal-describe-results-request.json": renderer.canonical(
            terminal_results_request
        ),
        "terminal-describe-results.json": _raw({
            "RequestId": "request-terminal-results-" + action,
            "Invocation": {
                **page,
                "TotalCount": 1,
                "NextToken": "",
                "InvocationResults": {"InvocationResult": [{
                "CommandId": command_id,
                "InvokeId": invoke_id,
                "InstanceId": target,
                "InvocationStatus": "Success",
                "ExitCode": 0,
                "Dropped": 0,
                "Repeats": 1,
                "StartTime": start_time,
                "FinishedTime": finished_time,
                "Output": base64.b64encode(renderer.canonical(result)).decode("ascii"),
                "ErrorCode": "",
                "ErrorInfo": "",
                "InvokeRecordStatus": "Finished",
                "ContainerId": "",
                "ContainerName": "",
                "Launcher": "",
                "OssOutputDelivery": "",
                "OssOutputErrorCode": "",
                "OssOutputErrorInfo": "",
                "OssOutputStatus": "",
                "OssOutputUri": "",
                "StopTime": "",
                "Username": "root",
                "TerminationMode": "ProcessTree",
                "Tags": {"Tag": [{"TagKey": "noteai-task", "TagValue": "item27-internal-smoke-v1"}]},
            }]},
            },
        }),
    }
    return input_value, request, result, capture


class Item27RawClosureBuilderTests(unittest.TestCase):
    def setUp(self):
        self.revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            stdout=subprocess.PIPE, text=True,
        ).stdout.strip()

    def build(self, action="api_c", capture=None):
        if capture is None:
            _input, _request, _result, capture = make_capture(action)
        return builder.build_receipt(
            action=action,
            source_revision=self.revision,
            observed_at_utc="2026-08-13T01:01:59Z",
            capture=capture,
        )

    def test_builds_from_exact_raw_bytes_and_emits_no_provider_values(self):
        input_value, request, result, capture = make_capture()
        receipt = self.build(capture=capture)
        self.assertEqual(receipt["result"], result)
        self.assertEqual(
            receipt["request"]["canonical_sha256"],
            hashlib.sha256(capture["run-command-request.json"]).hexdigest(),
        )
        self.assertEqual(
            receipt["request"]["run_command_response_raw_sha256"],
            hashlib.sha256(capture["run-command-response.json"]).hexdigest(),
        )
        self.assertEqual(
            receipt["raw_closure"]["builder"]["sha256"],
            hashlib.sha256((ROOT / builder.BUILDER_REF).read_bytes()).hexdigest(),
        )
        self.assertTrue(receipt["raw_closure"]["provider_raw_bodies_retained_complete"])
        self.assertTrue(receipt["raw_closure"]["provider_response_projection_only"])
        self.assertRegex(
            receipt["request"]["client_token_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertRegex(
            receipt["request"]["client_token_plan_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertIs(
            receipt["pre_dispatch"][
                "provider_client_token_readback_supported"
            ],
            False,
        )
        self.assertNotIn(
            "exact_client_token_history_count", receipt["pre_dispatch"]
        )
        self.assertNotIn("client_token_sha256", receipt["terminal_readback"])
        self.assertIs(
            receipt["execution_boundary"][
                "local_o_excl_plan_nonce_required"
            ],
            True,
        )
        self.assertIs(
            receipt["execution_boundary"][
                "provider_client_token_readback_supported"
            ],
            False,
        )
        self.assertEqual(
            receipt["execution_boundary"][
                "derived_client_token_commitment_count"
            ],
            1,
        )
        self.assertEqual(
            receipt["terminal_acceptance_sha256"],
            builder.terminal_acceptance_sha256(receipt),
        )
        output = renderer.canonical(receipt)
        for forbidden in (
            request["ClientToken"], request["InstanceId"][0],
            "cmd-api_c", "invoke-api_c", "request-run-api_c",
            input_value["plan_nonce"],
        ):
            self.assertNotIn(forbidden.encode("ascii"), output)

    def test_raw_response_identity_status_and_stdout_are_recomputed(self):
        cases = []
        _input, _request, _result, capture = make_capture()
        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-commands.json"])
        body["Commands"]["Command"][0]["CommandId"] = "invented"
        changed["terminal-describe-commands.json"] = _raw(body)
        cases.append((changed, "terminal_command_match"))

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-invocations.json"])
        body["Invocations"]["Invocation"][0]["InvokeInstances"][
            "InvokeInstance"
        ][0]["ExitCode"] = 1
        changed["terminal-describe-invocations.json"] = _raw(body)
        cases.append((changed, "terminal_invocation_result"))

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-results.json"])
        body["Invocation"]["InvocationResults"]["InvocationResult"][0][
            "Output"
        ] = base64.b64encode(b'{"status":"PASS"}\n').decode("ascii")
        changed["terminal-describe-results.json"] = _raw(body)
        cases.append((changed, "result_identity"))

        changed = copy.deepcopy(capture)
        body = json.loads(changed["pre-describe-commands.json"])
        body["TotalCount"] = 1
        body["Commands"]["Command"] = [{"CommandId": "old"}]
        changed["pre-describe-commands.json"] = _raw(body)
        cases.append((changed, "pre_commands_incomplete_page"))

        for changed, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(
                builder.ClosureError, error
            ):
                self.build(capture=changed)

    def test_terminal_lists_totals_repeats_and_dropped_are_provider_derived(self):
        _input, _request, _result_value, capture = make_capture()
        cases = []
        for filename, mutate, expected in (
            (
                "terminal-describe-commands.json",
                lambda body: (
                    body.update({"TotalCount": 2}),
                    body["Commands"]["Command"].append(
                        copy.deepcopy(body["Commands"]["Command"][0])
                    ),
                ),
                "terminal_commands_incomplete_page",
            ),
            (
                "terminal-describe-invocations.json",
                lambda body: body["Invocations"]["Invocation"][0][
                    "InvokeInstances"
                ]["InvokeInstance"].append(copy.deepcopy(
                    body["Invocations"]["Invocation"][0]["InvokeInstances"]
                    ["InvokeInstance"][0]
                )),
                "terminal_invoke_instances",
            ),
            (
                "terminal-describe-results.json",
                lambda body: body["Invocation"].update({"TotalCount": 2}),
                "terminal_results_rows",
            ),
            (
                "terminal-describe-invocations.json",
                lambda body: body["Invocations"]["Invocation"][0][
                    "InvokeInstances"
                ]["InvokeInstance"][0].update({"Repeats": 2}),
                "terminal_invocation_result",
            ),
            (
                "terminal-describe-results.json",
                lambda body: body["Invocation"]["InvocationResults"][
                    "InvocationResult"
                ][0].update({"Dropped": 1}),
                "terminal_provider_result",
            ),
        ):
            changed = copy.deepcopy(capture)
            body = json.loads(changed[filename])
            mutate(body)
            changed[filename] = _raw(body)
            cases.append((changed, expected))
        for changed, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(
                builder.ClosureError, expected
            ):
                self.build(capture=changed)

    def test_describe_requests_are_exact_but_complete_official_raw_allows_extras(self):
        _input, _request, _result_value, capture = make_capture()
        cases = []
        changed = copy.deepcopy(capture)
        request = json.loads(changed["pre-describe-commands-request.json"])
        request["PageSize"] = builder.DESCRIBE_PAGE_SIZE + 1
        changed["pre-describe-commands-request.json"] = renderer.canonical(request)
        cases.append((changed, "pre_commands_request_binding"))

        changed = copy.deepcopy(capture)
        response = json.loads(changed["terminal-describe-commands.json"])
        del response["Commands"]["Command"][0]["CommandId"]
        changed["terminal-describe-commands.json"] = _raw(response)
        cases.append((changed, "terminal_command_row_schema"))

        for changed, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(
                builder.ClosureError, expected
            ):
                self.build(capture=changed)

        changed = copy.deepcopy(capture)
        response = json.loads(changed["run-command-response.json"])
        response["OfficialFutureField"] = {"opaque": True}
        changed["run-command-response.json"] = _raw(response)
        response = json.loads(changed["terminal-describe-commands.json"])
        response["Commands"]["OfficialFutureField"] = []
        response["Commands"]["Command"][0]["OfficialFutureField"] = "retained"
        changed["terminal-describe-commands.json"] = _raw(response)
        receipt = self.build(capture=changed)
        self.assertEqual(
            receipt["request"]["run_command_response_raw_sha256"],
            hashlib.sha256(changed["run-command-response.json"]).hexdigest(),
        )
        self.assertEqual(
            receipt["terminal_readback"]["describe_commands_raw_sha256"],
            hashlib.sha256(
                changed["terminal-describe-commands.json"]
            ).hexdigest(),
        )

    def test_pre_invocation_history_is_global_to_fresh_name_not_instance(self):
        _input, request, _result_value, capture = make_capture()
        pre_request = json.loads(
            capture["pre-describe-invocations-request.json"]
        )
        self.assertEqual(pre_request["CommandName"], request["Name"])
        self.assertNotIn("InstanceId", pre_request)

        pre_request["InstanceId"] = request["InstanceId"][0]
        capture["pre-describe-invocations-request.json"] = renderer.canonical(
            pre_request
        )
        with self.assertRaisesRegex(
            builder.ClosureError, "pre_invocations_request_binding"
        ):
            self.build(capture=capture)

        _input, _request, _result_value, capture = make_capture()
        body = json.loads(capture["pre-describe-invocations.json"])
        body["TotalCount"] = 1
        body["Invocations"]["Invocation"] = [{
            "CommandName": request["Name"],
        }]
        capture["pre-describe-invocations.json"] = _raw(body)
        with self.assertRaisesRegex(
            builder.ClosureError, "pre_invocations_incomplete_page"
        ):
            self.build(capture=capture)

    def test_describe_invocation_results_uses_official_nested_pagination(self):
        _input, _request, _result_value, capture = make_capture()
        receipt = self.build(capture=capture)
        terminal = receipt["terminal_readback"]
        self.assertEqual(terminal["provider_result_status"], "Success")
        self.assertLess(
            terminal["provider_start_time_utc"],
            terminal["provider_finished_time_utc"],
        )
        body = json.loads(capture["terminal-describe-results.json"])
        self.assertNotIn("PageNumber", body)
        self.assertEqual(body["Invocation"]["PageNumber"], 1)
        self.assertNotIn("TotalCount", body["Invocation"]["InvocationResults"])

    def test_describe_commands_and_invocations_use_official_field_sources(self):
        _input, _request, _result_value, capture = make_capture()
        receipt = self.build(capture=capture)
        command = json.loads(capture["terminal-describe-commands.json"])[
            "Commands"
        ]["Command"][0]
        self.assertEqual(set(command), OFFICIAL_COMMAND_FIELDS)
        for request_or_invocation_field in (
            "ContentEncoding", "Username", "RepeatMode", "TerminationMode",
            "KeepCommand",
        ):
            self.assertNotIn(request_or_invocation_field, command)
        invocation = json.loads(capture["terminal-describe-invocations.json"])[
            "Invocations"
        ]["Invocation"][0]
        self.assertEqual(set(invocation), OFFICIAL_INVOCATION_FIELDS)
        self.assertEqual(invocation["InvocationStatus"], "Success")
        self.assertEqual(invocation["InvokeStatus"], "Finished")
        self.assertEqual(invocation["RepeatMode"], "Once")
        self.assertNotIn("TotalCount", invocation["InvokeInstances"])
        instance = invocation["InvokeInstances"]["InvokeInstance"][0]
        self.assertEqual(set(instance), OFFICIAL_INVOKE_INSTANCE_FIELDS)
        self.assertEqual(instance["InvocationStatus"], "Success")
        self.assertEqual(instance["InstanceInvokeStatus"], "Finished")
        self.assertEqual(
            receipt["terminal_readback"][
                "provider_readable_run_command_field_count"
            ],
            7,
        )

        for field, value in (
            ("Username", "nobody"),
            ("RepeatMode", "Period"),
            ("TerminationMode", "Process"),
            ("InvocationStatus", "Finished"),
            ("InvokeStatus", "Success"),
        ):
            changed = copy.deepcopy(capture)
            body = json.loads(changed["terminal-describe-invocations.json"])
            body["Invocations"]["Invocation"][0][field] = value
            changed["terminal-describe-invocations.json"] = _raw(body)
            with self.subTest(field=field), self.assertRaisesRegex(
                builder.ClosureError, "terminal_invocation_result"
            ):
                self.build(capture=changed)

        result_row = json.loads(capture["terminal-describe-results.json"])[
            "Invocation"
        ]["InvocationResults"]["InvocationResult"][0]
        self.assertEqual(set(result_row), OFFICIAL_INVOCATION_RESULT_FIELDS)

    def test_rejects_legacy_cropped_wrong_layer_and_flat_pagination_shapes(self):
        _input, _request, _result_value, capture = make_capture()
        cases = []

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-commands.json"])
        command = body["Commands"]["Command"][0]
        body["Commands"]["Command"] = [{
            key: command[key]
            for key in (
                "CommandId", "ContentEncoding", "Username", "RepeatMode",
                "TerminationMode", "KeepCommand",
            )
            if key in command
        }]
        changed["terminal-describe-commands.json"] = _raw(body)
        cases.append((changed, "terminal_command_row_schema"))

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-invocations.json"])
        invocation = body["Invocations"]["Invocation"][0]
        repeat_mode = invocation.pop("RepeatMode")
        invocation["InvokeInstances"]["InvokeInstance"][0][
            "RepeatMode"
        ] = repeat_mode
        changed["terminal-describe-invocations.json"] = _raw(body)
        cases.append((changed, "terminal_invocation_row_schema"))

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-results.json"])
        invocation = body["Invocation"]
        for field in ("PageNumber", "PageSize", "TotalCount"):
            body[field] = invocation.pop(field)
        changed["terminal-describe-results.json"] = _raw(body)
        cases.append((changed, "terminal_results_invocation_wrapper_schema"))

        for changed, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(
                builder.ClosureError, expected
            ):
                self.build(capture=changed)

        for field, value in (
            ("InvocationStatus", "Finished"),
            ("InstanceInvokeStatus", "Success"),
        ):
            changed = copy.deepcopy(capture)
            body = json.loads(changed["terminal-describe-invocations.json"])
            body["Invocations"]["Invocation"][0]["InvokeInstances"][
                "InvokeInstance"
            ][0][field] = value
            changed["terminal-describe-invocations.json"] = _raw(body)
            with self.subTest(instance_field=field), self.assertRaisesRegex(
                builder.ClosureError, "terminal_invocation_result"
            ):
                self.build(capture=changed)

        for field, value in (
            ("ContentEncoding", "PlainText"),
            ("KeepCommand", False),
        ):
            changed = copy.deepcopy(capture)
            request = json.loads(changed["run-command-request.json"])
            request[field] = value
            changed["run-command-request.json"] = renderer.canonical(request)
            with self.subTest(request_field=field), self.assertRaisesRegex(
                builder.ClosureError, "request_binding"
            ):
                self.build(capture=changed)

    def test_provider_result_times_are_strict_and_bound_into_terminal_acceptance(self):
        _input, _request, _result_value, capture = make_capture()
        original = self.build(capture=capture)
        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-results.json"])
        row = body["Invocation"]["InvocationResults"]["InvocationResult"][0]
        row["FinishedTime"] = row["StartTime"]
        changed["terminal-describe-results.json"] = _raw(body)
        with self.assertRaisesRegex(builder.ClosureError, "terminal_provider_result"):
            self.build(capture=changed)

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-results.json"])
        body["Invocation"]["InvocationResults"]["InvocationResult"][0][
            "OfficialFutureField"
        ] = "retained-and-committed"
        changed["terminal-describe-results.json"] = _raw(body)
        future = self.build(capture=changed)
        self.assertNotEqual(
            original["terminal_acceptance_sha256"],
            future["terminal_acceptance_sha256"],
        )

    def test_success_result_may_omit_optional_error_fields(self):
        _input, _request, result, capture = make_capture()
        body = json.loads(capture["terminal-describe-results.json"])
        row = body["Invocation"]["InvocationResults"]["InvocationResult"][0]
        del row["ErrorCode"]
        del row["ErrorInfo"]
        capture["terminal-describe-results.json"] = _raw(body)

        receipt = self.build(capture=capture)
        self.assertEqual(receipt["result"], result)
        self.assertEqual(
            receipt["terminal_readback"]["describe_results_raw_sha256"],
            hashlib.sha256(
                capture["terminal-describe-results.json"]
            ).hexdigest(),
        )

        for field in ("ErrorCode", "ErrorInfo"):
            _input, _request, _result, changed = make_capture()
            body = json.loads(changed["terminal-describe-results.json"])
            body["Invocation"]["InvocationResults"]["InvocationResult"][0][
                field
            ] = "unexpected-provider-error"
            changed["terminal-describe-results.json"] = _raw(body)
            with self.subTest(field=field), self.assertRaisesRegex(
                builder.ClosureError, "terminal_provider_result"
            ):
                self.build(capture=changed)

    def test_recursive_integer_boolean_aliases_are_rejected(self):
        _input, _request, _result_value, capture = make_capture()
        cases = []

        changed = copy.deepcopy(capture)
        body = json.loads(changed["pre-describe-commands.json"])
        body["PageNumber"] = True
        changed["pre-describe-commands.json"] = _raw(body)
        cases.append(changed)

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-invocations.json"])
        body["Invocations"]["Invocation"][0]["InvokeInstances"][
            "InvokeInstance"
        ][0]["Dropped"] = False
        changed["terminal-describe-invocations.json"] = _raw(body)
        cases.append(changed)

        changed = copy.deepcopy(capture)
        body = json.loads(changed["terminal-describe-commands.json"])
        request = json.loads(changed["run-command-request.json"])
        request["KeepCommand"] = 1
        changed["run-command-request.json"] = renderer.canonical(request)
        cases.append(changed)

        changed = copy.deepcopy(capture)
        request = json.loads(changed["pre-describe-commands-request.json"])
        request["PageNumber"] = True
        changed["pre-describe-commands-request.json"] = renderer.canonical(request)
        cases.append(changed)

        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(
                builder.ClosureError
            ):
                self.build(capture=changed)

    def test_builder_calls_shared_complete_executor_result_validator(self):
        _input, _request, _result_value, capture = make_capture()
        body = json.loads(capture["terminal-describe-results.json"])
        result = _result("api_c")
        result["provider_call_count"] = 1
        body["Invocation"]["InvocationResults"]["InvocationResult"][0][
            "Output"
        ] = base64.b64encode(renderer.canonical(result)).decode("ascii")
        capture["terminal-describe-results.json"] = _raw(body)
        with self.assertRaisesRegex(
            builder.ClosureError, "executor_result_semantics"
        ):
            self.build(capture=capture)

    def test_receipt_separates_raw_values_from_commitments(self):
        receipt = self.build()
        boundary = receipt["execution_boundary"]
        self.assertEqual(boundary["raw_provider_body_value_emitted_count"], 0)
        self.assertEqual(
            boundary["raw_provider_body_commitment_count"],
            len(builder.PROVIDER_RAW_RESPONSE_FILES),
        )
        self.assertEqual(boundary["provider_request_value_emitted_count"], 0)
        self.assertEqual(
            boundary["provider_request_commitment_count"],
            len(builder.PROVIDER_REQUEST_FILES),
        )
        self.assertNotIn("provider_raw_body_committed_count", boundary)

    def test_rejects_missing_extra_or_nonbytes_capture(self):
        _input, _request, _result, capture = make_capture()
        for changed in (
            {key: value for key, value in capture.items() if key != builder.CAPTURE_FILES[-1]},
            {**capture, "extra.json": b"{}\n"},
            {**capture, builder.CAPTURE_FILES[-1]: "not-bytes"},
        ):
            with self.assertRaises(builder.ClosureError):
                self.build(capture=changed)

    def test_root_only_loader_rejects_permissions_symlink_and_extras(self):
        _input, _request, _result, capture = make_capture()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "capture"
            directory.mkdir(mode=0o700)
            for name, raw in capture.items():
                path = directory / name
                path.write_bytes(raw)
                path.chmod(0o600)
            self.assertEqual(builder.load_root_only_capture(directory), capture)

            target = directory / builder.CAPTURE_FILES[0]
            target.chmod(0o644)
            with self.assertRaisesRegex(builder.ClosureError, "capture_file"):
                builder.load_root_only_capture(directory)
            target.chmod(0o600)

            extra = directory / "extra.json"
            extra.write_text("{}\n", encoding="ascii")
            extra.chmod(0o600)
            with self.assertRaisesRegex(builder.ClosureError, "capture_directory"):
                builder.load_root_only_capture(directory)
            extra.unlink()

            raw = target.read_bytes()
            target.unlink()
            link_target = directory / "outside"
            link_target.write_bytes(raw)
            link_target.chmod(0o600)
            target.symlink_to(link_target)
            with self.assertRaises(builder.ClosureError):
                builder.load_root_only_capture(directory)


if __name__ == "__main__":
    unittest.main()
