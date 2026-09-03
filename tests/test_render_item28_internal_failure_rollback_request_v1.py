import base64
import copy
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import render_item28_internal_failure_rollback_request_v1 as renderer  # noqa: E402


def input_value():
    return {
        "action": renderer.ACTION,
        "plan_nonce": "1" * 32,
        "api_f_instance_id": "i-abc123",
        "item25_terminal_acceptance_sha256": "a" * 64,
        "item26_terminal_acceptance_sha256": "b" * 64,
        "item27_terminal_acceptance_sha256": "c" * 64,
    }


class Item28RendererTests(unittest.TestCase):
    def test_exact_request_and_bounded_shell(self):
        value = input_value()
        request, validation = renderer.render_request(value)

        self.assertEqual(set(request), renderer.RUN_COMMAND_KEYS)
        self.assertEqual(request["Name"], renderer.COMMAND_NAME)
        self.assertEqual(request["InstanceId"], [value["api_f_instance_id"]])
        self.assertEqual(request["RepeatMode"], "Once")
        self.assertEqual(request["TerminationMode"], "ProcessTree")
        self.assertEqual(request["Username"], "root")
        self.assertTrue(request["KeepCommand"])
        self.assertFalse(request["EnableParameter"])
        wrapper = base64.b64decode(request["CommandContent"], validate=True)
        self.assertEqual(len(wrapper), validation["command_content_bytes"])
        self.assertLessEqual(len(wrapper), renderer.MAX_COMMAND_CONTENT_BYTES)
        syntax = subprocess.run(
            ["/bin/sh", "-n"], input=wrapper, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr.decode())
        self.assertEqual(validation["target_count"], 1)
        self.assertFalse(validation["automatic_retry_allowed"])
        self.assertFalse(validation["same_request_resubmit_allowed"])
        self.assertFalse(validation["provider_client_token_readback_supported"])

    def test_wrapper_collision_never_removes_preexisting_run_directory(self):
        wrapper, _compressed = renderer.render_wrapper(renderer.read_executor())
        with tempfile.TemporaryDirectory() as temp_dir:
            collision = Path(temp_dir) / "preexisting"
            collision.mkdir(mode=0o700)
            sentinel = collision / "sentinel"
            sentinel.write_text("keep\n")
            replacement = "task_dir=" + shlex.quote(str(collision))
            wrapper = wrapper.replace(
                b"task_dir=/run/.noteai-item28-wrapper.$$",
                replacement.encode("ascii"),
            )
            run = subprocess.run(
                ["/bin/sh"], input=wrapper, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(run.returncode, 4)
            self.assertTrue(collision.is_dir())
            self.assertEqual(sentinel.read_text(), "keep\n")

    def test_wrapper_cleanup_is_guarded_by_owned_directory_flag(self):
        wrapper, _compressed = renderer.render_wrapper(renderer.read_executor())
        self.assertIn(b"owned=0", wrapper)
        self.assertIn(b'if [ "$owned" -eq 1 ]; then', wrapper)
        self.assertIn(b'/bin/mkdir -m 0700 -- "$task_dir"', wrapper)
        self.assertNotIn(b"/run/.noteai-item28-executor.$$.py", wrapper)

    def test_client_token_binds_every_predecessor_and_nonce(self):
        original = input_value()
        baseline = renderer.derive_client_token(original)
        for key in (
            "plan_nonce", "item25_terminal_acceptance_sha256",
            "item26_terminal_acceptance_sha256",
            "item27_terminal_acceptance_sha256",
        ):
            changed = copy.deepcopy(original)
            changed[key] = ("2" if key == "plan_nonce" else "d") * len(changed[key])
            self.assertNotEqual(renderer.derive_client_token(changed), baseline)

    def test_wrong_types_duplicates_and_noncanonical_input_fail(self):
        value = input_value()
        value["api_f_instance_id"] = ["i-abc123"]
        with self.assertRaisesRegex(renderer.RequestError, "api_f_instance_id"):
            renderer.render_request(value)

        value = input_value()
        value["item25_terminal_acceptance_sha256"] = True
        with self.assertRaisesRegex(
            renderer.RequestError, "item25_terminal_acceptance_sha256"
        ):
            renderer.render_request(value)

        with self.assertRaisesRegex(renderer.RequestError, "duplicate_json_key"):
            renderer.parse_canonical(b'{"a":1,"a":2}\n')
        with self.assertRaisesRegex(renderer.RequestError, "input_canonical"):
            renderer.parse_canonical(b'{"b":2, "a":1}\n')

    def test_request_tamper_fails_closed(self):
        value = input_value()
        request, _validation = renderer.render_request(value)
        mutations = (
            ("Timeout", request["Timeout"] + 1),
            ("RepeatMode", "Period"),
            ("KeepCommand", 1),
            ("Name", request["Name"] + "-replay"),
            ("InstanceId", ["i-other"]),
        )
        for key, replacement in mutations:
            broken = copy.deepcopy(request)
            broken[key] = replacement
            with self.assertRaises(renderer.RequestError, msg=key):
                renderer.validate_run_command(broken, value)

    def test_executor_identity_is_exact(self):
        raw = renderer.read_executor()
        self.assertEqual(len(raw), renderer.EXECUTOR_IDENTITY["bytes"])
        self.assertEqual(
            renderer._sha256(raw), renderer.EXECUTOR_IDENTITY["sha256"]
        )

    def test_module_has_no_provider_submit_or_retry_helper(self):
        source = Path(renderer.__file__).read_text()
        self.assertNotIn("RunCommand(", source)
        self.assertNotIn("aliyun ecs", source)
        self.assertNotIn("--retry-count", source)
        self.assertNotIn("ClientToken readback", source)

    def test_cli_emits_one_canonical_request(self):
        run = subprocess.run(
            [sys.executable, str(Path(renderer.__file__))],
            input=renderer.canonical(input_value()), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        self.assertEqual(renderer.canonical(json.loads(run.stdout)), run.stdout)


if __name__ == "__main__":
    unittest.main()
