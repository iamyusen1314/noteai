import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import render_item29_capacity_100_request_v1 as renderer


FROZEN = {
    "schema": renderer.DEPENDENCY_SCHEMA,
    "authority_root": "1" * 64,
    "verifier_path": "tools/verify_internal_failure_rollback_evidence.py",
    "verifier_sha256": "2" * 64,
    "evidence_path": (
        "deploy/production/evidence/"
        "production-internal-failure-rollback-verified-20260814.json"
    ),
    "evidence_sha256": "3" * 64,
    "receipt_path": (
        "deploy/production/evidence/"
        "internal-failure-rollback-api-f-provider-receipt-20260814.json"
    ),
    "receipt_sha256": "4" * 64,
    "checkpoint_path": (
        "deploy/production/evidence/"
        "internal-failure-rollback-terminal-checkpoint-20260814.json"
    ),
    "checkpoint_sha256": "5" * 64,
    "terminal_acceptance_sha256": "6" * 64,
}


def input_value():
    return {
        "action": renderer.ACTION,
        "plan_nonce": "5c22acf5-1f6a-49e2-9787-036c1cbb43ea",
        "api_c_instance_id": "i-item29fixture",
        "item28_dependency": copy.deepcopy(FROZEN),
    }


class RenderItem29CapacityRequestTests(unittest.TestCase):
    @staticmethod
    def _sha_tool(base):
        sha_tool = base / "sha256sum"
        sha_tool.write_text(
            "#!/usr/bin/python3\n"
            "import hashlib, pathlib, sys\n"
            "for name in sys.argv[1:]:\n"
            " print(hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest(), name)\n",
            encoding="ascii",
        )
        sha_tool.chmod(0o755)
        return sha_tool

    @classmethod
    def _shell_wrapper(cls, base, child_rc=0, child_out=b"", child_err=b""):
        executor = (
            "import sys\n"
            f"sys.stdout.buffer.write({child_out!r})\n"
            f"sys.stderr.buffer.write({child_err!r})\n"
            f"raise SystemExit({child_rc})\n"
        ).encode("ascii")
        wrapper = renderer.render_wrapper(executor, input_value())
        return wrapper.replace(
            b"/run/.noteai-item29-capacity.",
            (str(base) + "/.noteai-item29-capacity.").encode("ascii"),
        ).replace(
            b"/usr/bin/sha256sum", str(cls._sha_tool(base)).encode("ascii")
        )

    def _assert_file_collision_preserves_sentinel(self, suffix):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            mkdir_tool = base / "mkdir-collision"
            mkdir_tool.write_text(
                "#!/bin/sh\n"
                "/bin/mkdir \"$@\" || exit $?\n"
                "for candidate do collision_dir=$candidate; done\n"
                f"/usr/bin/printf '%s' sentinel > \"$collision_dir/{suffix}\"\n",
                encoding="ascii",
            )
            mkdir_tool.chmod(0o755)
            wrapper = self._shell_wrapper(base).replace(
                b"/bin/mkdir", str(mkdir_tool).encode("ascii")
            )
            result = subprocess.run(
                ["/bin/sh"], input=wrapper,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                timeout=10, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            private_dirs = list(base.glob(".noteai-item29-capacity.*"))
            self.assertEqual(len(private_dirs), 1)
            self.assertEqual(
                {path.name for path in private_dirs[0].iterdir()}, {suffix}
            )
            self.assertEqual(
                (private_dirs[0] / suffix).read_bytes(), b"sentinel"
            )

    def test_default_item28_authority_is_empty_and_blocks(self):
        self.assertEqual(renderer.FROZEN_ITEM28_DEPENDENCY["authority_root"], "")
        self.assertEqual(renderer.FROZEN_ITEM28_DEPENDENCY["verifier_path"], "")
        self.assertEqual(renderer.FROZEN_ITEM28_DEPENDENCY["evidence_path"], "")
        self.assertEqual(renderer.FROZEN_ITEM28_DEPENDENCY["receipt_path"], "")
        self.assertEqual(renderer.FROZEN_ITEM28_DEPENDENCY["checkpoint_path"], "")
        self.assertEqual(renderer.FROZEN_ITEM28_DEPENDENCY["evidence_sha256"], "")
        with self.assertRaisesRegex(
            renderer.RequestError,
            "item28_dependency_authority_not_frozen",
        ):
            renderer.render_request(input_value())

    def test_frozen_dependency_renders_exact_no_replay_request(self):
        value = input_value()
        with mock.patch.object(
            renderer, "FROZEN_ITEM28_DEPENDENCY", FROZEN
        ), mock.patch.object(renderer, "PRODUCTION_RUNTIME_ADAPTER_BOUND", True):
            request, validation = renderer.render_request(value)
        self.assertEqual(set(request), renderer.RUN_COMMAND_KEYS)
        self.assertEqual(request["Name"], renderer.COMMAND_NAME)
        self.assertEqual(request["InstanceId"], ["i-item29fixture"])
        self.assertEqual(request["RepeatMode"], "Once")
        self.assertEqual(request["KeepCommand"], True)
        self.assertEqual(request["TerminationMode"], "ProcessTree")
        self.assertEqual(validation["provider_history_key"], "Name")
        self.assertFalse(validation["provider_client_token_readback_supported"])
        self.assertFalse(validation["wrapper_child_exec_used"])
        self.assertTrue(
            validation["wrapper_cleanup_requires_owned_private_directory"]
        )
        self.assertEqual(validation["wrapper_host_temp_file_count"], 4)
        self.assertTrue(validation["wrapper_private_directory_atomic_mkdir"])
        self.assertEqual(validation["wrapper_temp_file_created_flag_count"], 4)
        self.assertTrue(
            validation["wrapper_temp_residue_absence_audited_before_output"]
        )
        wrapper = base64.b64decode(request["CommandContent"], validate=True)
        self.assertIn(b"--runtime-factory __main__:create_runtime", wrapper)
        self.assertNotIn(b"exec /usr/bin/python3", wrapper)
        self.assertIn(b"rc=$?", wrapper)
        self.assertIn(b"run_dir_owned=0", wrapper)
        self.assertIn(b"run_dir_owned=1", wrapper)
        self.assertIn(b"if [ \"$run_dir_owned\" -ne 1 ]", wrapper)
        self.assertIn(b"src_created=1", wrapper)
        self.assertIn(b"gz_created=1", wrapper)
        self.assertIn(b"out_created=1", wrapper)
        self.assertIn(b"err_created=1", wrapper)
        self.assertIn(b"cleanup\n[ ! -e \"$src\" ]", wrapper)
        self.assertIn(b"[ ! -e \"$gz\" ]", wrapper)
        self.assertIn(b"[ ! -e \"$out\" ]", wrapper)
        self.assertIn(b"[ ! -e \"$err\" ]", wrapper)
        self.assertIn(b"[ ! -e \"$run_dir\" ]", wrapper)
        self.assertLess(
            wrapper.index(b"[ ! -e \"$err\" ]"),
            wrapper.index(b"/usr/bin/printf '%s' \"$out_b64\""),
        )
        self.assertNotIn(b"ANTHROPIC_" + b"API_" + b"KEY=", wrapper)
        self.assertNotIn(b"MOONSHOT_" + b"API_" + b"KEY=", wrapper)

    def test_dependency_drift_and_extra_fields_fail_closed(self):
        with mock.patch.object(
            renderer, "FROZEN_ITEM28_DEPENDENCY", FROZEN
        ), mock.patch.object(renderer, "PRODUCTION_RUNTIME_ADAPTER_BOUND", True):
            changed = input_value()
            changed["item28_dependency"]["evidence_sha256"] = "4" * 64
            with self.assertRaisesRegex(
                renderer.RequestError, "item28_dependency_binding"
            ):
                renderer.render_request(changed)
            extra = input_value()
            extra["unexpected"] = 1
            with self.assertRaisesRegex(renderer.RequestError, "input_contract"):
                renderer.render_request(extra)

    def test_wrapper_preserves_child_rc_and_emits_only_after_temp_absence(self):
        cases = (
            (0, b"child-out\n", b"child-err\n"),
            (7, b"failed-out\n", b"failed-err\n"),
        )
        for child_rc, child_out, child_err in cases:
            with self.subTest(child_rc=child_rc), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                wrapper = self._shell_wrapper(
                    base, child_rc, child_out, child_err
                )
                result = subprocess.run(
                    ["/bin/sh"], input=wrapper,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                    timeout=10, check=False,
                )
                self.assertEqual(result.returncode, child_rc)
                self.assertEqual(result.stdout, child_out)
                self.assertEqual(result.stderr, child_err)
                self.assertEqual(
                    list(base.glob(".noteai-item29-capacity.*")), []
                )

    def test_preexisting_private_directory_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            private_dir = base / ".noteai-item29-capacity.preexisting"
            private_dir.mkdir(mode=0o700)
            sentinel = private_dir / "sentinel"
            sentinel.write_bytes(b"do-not-delete")
            wrapper = self._shell_wrapper(base).replace(
                (
                    "run_dir=" + str(base)
                    + "/.noteai-item29-capacity.$$"
                ).encode("ascii"),
                ("run_dir=" + str(private_dir)).encode("ascii"),
            )
            result = subprocess.run(
                ["/bin/sh"], input=wrapper,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                timeout=10, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_bytes(), b"do-not-delete")
            self.assertEqual({path.name for path in private_dir.iterdir()}, {"sentinel"})

    def test_payload_py_collision_is_not_deleted(self):
        self._assert_file_collision_preserves_sentinel("payload.py")

    def test_payload_gzip_collision_is_not_deleted(self):
        self._assert_file_collision_preserves_sentinel("payload.py.gz")

    def test_stdout_collision_is_not_deleted(self):
        self._assert_file_collision_preserves_sentinel("payload.stdout")

    def test_stderr_collision_is_not_deleted(self):
        self._assert_file_collision_preserves_sentinel("payload.stderr")

    def test_frozen_item28_still_blocks_without_production_runtime_adapter(self):
        with mock.patch.object(renderer, "FROZEN_ITEM28_DEPENDENCY", FROZEN):
            with self.assertRaisesRegex(
                renderer.RequestError,
                "production_runtime_adapter_not_frozen",
            ):
                renderer.render_request(input_value())

    def test_main_stays_blocked_with_canonical_input(self):
        raw = renderer.canonical(input_value())
        with mock.patch.object(sys, "stdin") as stdin:
            stdin.buffer.read.return_value = raw
            with mock.patch.object(sys, "stderr") as stderr:
                self.assertEqual(renderer.main([]), 3)
                stderr.write.assert_called_with(
                    "item28_dependency_authority_not_frozen\n"
                )


if __name__ == "__main__":
    unittest.main()
