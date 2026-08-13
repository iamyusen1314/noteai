import ast
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import render_item26_restored_preflight_v1 as ops


class Item26RestoredPreflightV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compressor = staticmethod(lambda body: gzip.compress(body, 9, mtime=0))

    def common(self):
        return {
            "application_secret_value_read_count": 0,
            "automatic_retry_allowed": False,
            "container_start_count": 0,
            "database_connection_count": 0,
            "database_write_count": 0,
            "environment_value_read_count": 0,
            "host_task_write_count": 0,
            "private_key_value_read_count": 0,
            "resource_id_values_emitted": 0,
            "same_invocation_replay_allowed": False,
            "secret_values_emitted": 0,
        }

    def host_namespace(self, name):
        source = ops.PATHS[name].read_bytes()
        chunks = re.findall(br"<<'PY'\n(.*?)\nPY(?:\n|$)", source, re.S)
        self.assertEqual(len(chunks), 1)
        tree = ast.parse(chunks[0].decode("ascii"))
        allowed = (
            ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
            ast.ClassDef, ast.FunctionDef,
        )
        module = ast.Module(
            body=[node for node in tree.body if isinstance(node, allowed)],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        namespace = {}
        exec(compile(module, str(ops.PATHS[name]), "exec"), namespace)
        return namespace

    def api_pass(self):
        return ops.canonical({
            **self.common(),
            "NOTEAI_ITEM26_RESTORED_API_C_PREFLIGHT": "PASS",
            "broker_root_absent": True,
            "docker_config_exact": True,
            "docker_service_exact": True,
            "environment_metadata_exact": True,
            "established_tcp_5432_count": 0,
            "identity_exact": True,
            "image_exact": True,
            "persistent_parent_exact": True,
            "rewrap_root_absent": True,
            "schema_version": 1,
            "source_control_exact": True,
            "source_manifest_exact": True,
            "task_container_count": 0,
        })

    def builder_pass(self):
        return ops.canonical({
            **self.common(),
            "NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT": "PASS",
            "builder_capacity_exact": True,
            "docker_config_exact": True,
            "docker_service_exact": True,
            "established_tcp_5432_count": 0,
            "fixed_ram_role_exact": True,
            "identity_exact": True,
            "image_exact": True,
            "persistent_parent_exact": True,
            "restored_base_absent": True,
            "schema_version": 1,
            "task_container_count": 0,
        })

    def terminal(self, marker, state, phase, readback=False):
        value = {
            **self.common(),
            marker: state,
            "phase": phase,
        }
        if readback:
            value["readback_required"] = True
        return ops.canonical(value)

    def child(self, body, returncode):
        descriptor = 1 if returncode == 0 else 2
        return (
            b"exec python3 -I -B - <<'PY'\n"
            b"import os\n"
            + ("body={!r}\n".format(body)).encode("ascii")
            + ("os.write({},body)\n".format(descriptor)).encode("ascii")
            + ("os._exit({})\n".format(returncode)).encode("ascii")
            + b"PY\n"
        )

    def run_loader(self, contract, body, returncode=0):
        command = ops.command(self.child(body, returncode), contract, self.compressor)
        loader = base64.b64decode(command["base64"], validate=True)
        return subprocess.run(
            ["bash", "-s"],
            input=loader,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )

    def test_preflight_templates_are_sha_bound_syntax_valid_and_bounded(self):
        rendered = ops.preflight_commands(
            "i-api123", "api-role", "i-builder123", ops.BUILDER_RAM_ROLE,
            self.compressor,
        )
        self.assertEqual(set(rendered), {"api_c", "builder"})
        for host, name in (("api_c", "api_c"), ("builder", "builder")):
            expected = ops.IDENTITIES[name]
            body = ops.PATHS[name].read_bytes()
            self.assertEqual(len(body), expected["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), expected["sha256"])
            self.assertEqual(rendered[host]["template"], dict(expected))
            self.assertLessEqual(rendered[host]["command"]["bytes"], 18000)
            subprocess.run(["bash", "-n", str(ops.PATHS[name])], check=True)

        api_raw = ops.render(
            "api_c",
            {b"@@API_C_IDENTITY_SHA256@@": b"a" * 64},
        )
        builder_raw = ops.render(
            "builder",
            {b"@@BUILDER_IDENTITY_SHA256@@": b"b" * 64},
        )
        for raw in (api_raw, builder_raw):
            subprocess.run(["bash", "-n", "-s"], input=raw, check=True)
            self.assertNotIn(b"i-api123", raw)
            self.assertNotIn(b"i-builder123", raw)
            self.assertNotIn(b"api-role", raw)
            self.assertNotIn(b"CommandName", raw)
            self.assertNotIn(b"20260813", raw)

    def test_loader_accepts_only_exact_pass_fail_and_unknown_schemas(self):
        cases = (
            ("api_c", self.api_pass(), 0),
            ("builder", self.builder_pass(), 0),
            (
                "api_c",
                self.terminal(
                    "NOTEAI_ITEM26_RESTORED_API_C_PREFLIGHT",
                    "FAIL", "source_manifest",
                ),
                3,
            ),
            (
                "api_c",
                self.terminal(
                    "NOTEAI_ITEM26_RESTORED_API_C_PREFLIGHT",
                    "UNKNOWN", "source_manifest_race", True,
                ),
                4,
            ),
            (
                "api_c",
                self.terminal(
                    "NOTEAI_ITEM26_RESTORED_API_C_PREFLIGHT",
                    "UNKNOWN", "broker_root_present_runtime", True,
                ),
                4,
            ),
            (
                "builder",
                self.terminal(
                    "NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT",
                    "FAIL", "capacity",
                ),
                3,
            ),
            (
                "builder",
                self.terminal(
                    "NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT",
                    "UNKNOWN", "capacity_runtime", True,
                ),
                4,
            ),
            (
                "builder",
                self.terminal(
                    "NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT",
                    "UNKNOWN", "image_runtime", True,
                ),
                4,
            ),
        )
        for contract, body, returncode in cases:
            with self.subTest(contract=contract, returncode=returncode):
                result = self.run_loader(contract, body, returncode)
                expected = (
                    (returncode, body, b"")
                    if returncode == 0
                    else (returncode, b"", body)
                )
                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr), expected,
                )

        fixed = b'{"NOTEAI_ITEM26_RESTORED_PREFLIGHT_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\n'
        invalid = []
        value = json.loads(self.api_pass())
        invalid.append(("api_c", ops.canonical({**value, "schema_version": True}), 0))
        invalid.append(("api_c", ops.canonical({**value, "secret_values_emitted": False}), 0))
        invalid.append(("api_c", ops.canonical({**value, "unexpected": "must-not-leak"}), 0))
        value = json.loads(self.builder_pass())
        invalid.append(("builder", ops.canonical({**value, "builder_capacity_exact": 1}), 0))
        invalid.append(("builder", ops.canonical({**value, "task_container_count": False}), 0))
        invalid.append((
            "builder",
            self.terminal(
                "NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT",
                "UNKNOWN", "must-not-leak", True,
            ),
            4,
        ))
        for contract, body, returncode in invalid:
            with self.subTest(contract=contract, invalid=body[:60]):
                result = self.run_loader(contract, body, returncode)
                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr),
                    (4, b"", fixed),
                )
                self.assertNotIn(b"must-not-leak", result.stderr)

    def test_api_c_preflight_never_opens_env_or_private_key_values(self):
        source = ops.PATHS["api_c"].read_text()
        for marker in (
            'stat_only_at(pinned, "control-private.pem"',
            'stat_only_at(pinned, "api.env"',
            'stat_only_at(pinned, "storage.env"',
            "verify_pinned_directory(source_control",
            "verify_pinned_directory(source_manifest",
            "verify_pinned_directory(environment",
            "verify_pinned_directory(persistent",
            '"application_secret_value_read_count": 0',
            '"environment_value_read_count": 0',
            '"private_key_value_read_count": 0',
            '"resource_id_values_emitted": 0',
        ):
            self.assertIn(marker, source)
        for forbidden in (
            'stable_read_at(pinned, "control-private.pem"',
            'stable_read_at(pinned, "api.env"',
            'stable_read_at(pinned, "storage.env"',
            "os.path.lexists",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("SOURCE_MANIFEST_BYTES = 9794", source)
        self.assertIn("SOURCE_ENVELOPE_BYTES = 894", source)
        builder_source = ops.PATHS["builder"].read_text()
        self.assertIn("roles != [BUILDER_RAM_ROLE]", builder_source)
        self.assertIn("verify_pinned_directory(persistent", builder_source)
        self.assertNotIn("os.path.lexists", builder_source)
        for value in (source, builder_source):
            self.assertIn("dir_fd=pinned[\"fd\"]", value)
            self.assertIn("os.O_NOFOLLOW", value)

    def test_pinned_directory_detects_absolute_root_replacement_race(self):
        namespace = self.host_namespace("builder")
        failure = namespace["Failure"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "persistent"
            moved = Path(temp) / "moved"
            root.mkdir(mode=0o700)
            pinned = namespace["pin_directory"](
                str(root), "persistent_parent", exact_mode=0o700,
                expected_uid=os.getuid(), expected_gid=os.getgid(),
            )
            root.rename(moved)
            root.mkdir(mode=0o700)
            try:
                with self.assertRaises(failure) as caught:
                    namespace["verify_pinned_directory"](
                        pinned, "persistent_parent",
                    )
                self.assertTrue(caught.exception.unknown)
                self.assertEqual(caught.exception.phase, "persistent_parent_race")
            finally:
                os.close(pinned["fd"])

    def test_absence_accepts_only_filenotfound_and_errors_are_unknown(self):
        for name in ("api_c", "builder"):
            namespace = self.host_namespace(name)
            failure = namespace["Failure"]
            pinned = {"fd": 123}
            with self.subTest(name=name, outcome="absent"), mock.patch.object(
                namespace["os"], "stat", side_effect=FileNotFoundError(),
            ):
                namespace["child_absent"](pinned, "child", "root_present")
            with self.subTest(name=name, optional="absent"), mock.patch.object(
                namespace["os"], "lstat", side_effect=FileNotFoundError(),
            ):
                self.assertIsNone(namespace["optional_directory"](
                    "/root/.docker", "docker_config",
                ))
            for error in (PermissionError("denied"), OSError(5, "io")):
                with self.subTest(name=name, error=type(error).__name__), mock.patch.object(
                    namespace["os"], "stat", side_effect=error,
                ), self.assertRaises(failure) as caught:
                    namespace["child_absent"](
                        pinned, "child", "root_present",
                    )
                self.assertTrue(caught.exception.unknown)
                self.assertEqual(caught.exception.phase, "root_present_runtime")
                with self.subTest(name=name, optional=type(error).__name__), mock.patch.object(
                    namespace["os"], "lstat", side_effect=error,
                ), self.assertRaises(failure) as caught:
                    namespace["optional_directory"](
                        "/root/.docker", "docker_config",
                    )
                self.assertTrue(caught.exception.unknown)
                self.assertEqual(caught.exception.phase, "docker_config_runtime")

    def test_docker_runtime_errors_are_unknown_and_identity_drift_is_fail(self):
        namespace = self.host_namespace("builder")
        failure = namespace["Failure"]
        prefix = [
            (0, b"active\n", b""),
            (0, b"enabled\n", b""),
            (0, b"version\n", b""),
        ]
        runtime = mock.Mock(side_effect=prefix + [(1, b"", b"daemon unavailable")])
        with mock.patch.dict(namespace, {
            "command": runtime,
            "docker_config_exact": mock.Mock(return_value=None),
        }), self.assertRaises(failure) as caught:
            namespace["docker_exact"]()
        self.assertTrue(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "image_runtime")

        mismatch = mock.Mock(side_effect=prefix + [(0, b"wrong-identity\n", b"")])
        with mock.patch.dict(namespace, {
            "command": mismatch,
            "docker_config_exact": mock.Mock(return_value=None),
        }), self.assertRaises(failure) as caught:
            namespace["docker_exact"]()
        self.assertFalse(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "image")

        with mock.patch.dict(namespace, {
            "command": mock.Mock(return_value=(1, b"", b"bus unavailable")),
        }), self.assertRaises(failure) as caught:
            namespace["service_state"](
                ["/usr/bin/systemctl", "is-active", "docker"], b"active",
            )
        self.assertTrue(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "docker_runtime")

        with mock.patch.dict(namespace, {
            "command": mock.Mock(return_value=(3, b"inactive\n", b"")),
        }), self.assertRaises(failure) as caught:
            namespace["service_state"](
                ["/usr/bin/systemctl", "is-active", "docker"], b"active",
            )
        self.assertFalse(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "docker_service")

        with mock.patch.dict(namespace, {
            "optional_directory": mock.Mock(return_value=None),
            "command": mock.Mock(return_value=(1, b"", b"daemon unavailable")),
        }), self.assertRaises(failure) as caught:
            namespace["docker_config_exact"]()
        self.assertTrue(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "docker_runtime")

    def test_cli_renders_both_preflights_and_rejects_wrong_builder_role(self):
        request = ops.canonical({
            "api_c_instance_id": "i-api123",
            "api_c_ram_role": "api-role",
            "builder_instance_id": "i-builder123",
            "builder_ram_role": ops.BUILDER_RAM_ROLE,
            "mode": "preflight",
        })
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(request)
        stdout = mock.Mock()
        stdout.buffer = io.BytesIO()
        with mock.patch.object(ops.sys, "stdin", stdin), mock.patch.object(
            ops.sys, "stdout", stdout,
        ), mock.patch.object(
            ops, "production_compressor", return_value=self.compressor,
        ):
            self.assertEqual(ops.cli(), 0)
        value = json.loads(stdout.buffer.getvalue())
        self.assertEqual(set(value), {"api_c", "builder"})
        self.assertLessEqual(value["api_c"]["command"]["bytes"], 18000)
        self.assertLessEqual(value["builder"]["command"]["bytes"], 18000)

        with self.assertRaisesRegex(ops.RenderError, "builder_ram_role"):
            ops.preflight_commands(
                "i-api123", "api-role", "i-builder123", "other-role",
                self.compressor,
            )


if __name__ == "__main__":
    unittest.main()
