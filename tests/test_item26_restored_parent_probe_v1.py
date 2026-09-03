import ast
import base64
import copy
import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import render_item26_restored_parent_probe_v1 as probe


class Item26RestoredParentProbeV1Tests(unittest.TestCase):
    API_C = "i-api123"
    NONCE = "0123456789abcdef0123456789abcdef"

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

    def pass_value(self, state="PRESENT", kind="DIRECTORY"):
        absent = state == "ABSENT"
        return {
            **self.common(),
            "NOTEAI_ITEM26_RESTORED_PARENT_PROBE": "PASS",
            "persistent_parent_gid": None if absent else 0,
            "persistent_parent_is_symlink": kind == "SYMLINK",
            "persistent_parent_mode": None if absent else "0700",
            "persistent_parent_nlink": None if absent else 2,
            "persistent_parent_state": state,
            "persistent_parent_type": kind,
            "persistent_parent_uid": None if absent else 0,
            "schema_version": 1,
            "trusted_parent_gid": 123,
            "trusted_parent_mode": "0750",
            "trusted_parent_nlink": 1,
            "trusted_parent_safe": True,
        }

    def metadata(
        self,
        mode=0o755,
        uid=0,
        gid=123,
        nlink=1,
        device=1,
        inode=2,
    ):
        return SimpleNamespace(
            st_mode=stat.S_IFDIR | mode,
            st_uid=uid,
            st_gid=gid,
            st_nlink=nlink,
            st_dev=device,
            st_ino=inode,
            st_mtime=0,
            st_mtime_ns=0,
            st_ctime=0,
            st_ctime_ns=0,
        )

    def terminal(self, state, phase):
        value = {
            **self.common(),
            "NOTEAI_ITEM26_RESTORED_PARENT_PROBE": state,
            "phase": phase,
        }
        if state == "UNKNOWN":
            value["readback_required"] = True
        return value

    def child(self, body, returncode):
        descriptor = 1 if returncode == 0 else 2
        return (
            b"#!/bin/bash\nexec /usr/bin/python3 -I -B - <<'PY'\n"
            b"import os\n"
            + ("body={!r}\n".format(probe.canonical(body))).encode("ascii")
            + ("os.write({},body)\n".format(descriptor)).encode("ascii")
            + ("os._exit({})\n".format(returncode)).encode("ascii")
            + b"PY\n"
        )

    def run_wrapped(self, value, returncode=0):
        rendered = probe._command_from_raw(
            self.child(value, returncode), self.compressor,
        )
        loader = base64.b64decode(rendered["base64"], validate=True)
        return subprocess.run(
            ["/bin/bash", "-s"],
            input=loader,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )

    def host_namespace(self):
        source = probe.TEMPLATE_PATH.read_bytes()
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
        exec(compile(module, str(probe.TEMPLATE_PATH), "exec"), namespace)
        return namespace

    def test_template_is_sha_bound_read_only_and_command_is_bounded(self):
        body = probe.TEMPLATE_PATH.read_bytes()
        self.assertEqual(len(body), probe.TEMPLATE_IDENTITY["bytes"])
        self.assertEqual(hashlib.sha256(body).hexdigest(), probe.TEMPLATE_IDENTITY["sha256"])
        subprocess.run(["/bin/bash", "-n", str(probe.TEMPLATE_PATH)], check=True)
        rendered = probe.command(self.compressor)
        self.assertLessEqual(rendered["bytes"], 18000)
        self.assertEqual(
            hashlib.sha256(rendered["base64"].encode("ascii")).hexdigest(),
            rendered["sha256"],
        )
        source = body.decode("ascii")
        self.assertEqual(source.count("os.lstat("), 3)
        self.assertEqual(source.count("os.fstat("), 2)
        self.assertEqual(source.count("os.stat("), 3)
        self.assertEqual(source.count("dir_fd=parent_descriptor"), 3)
        self.assertEqual(source.count("follow_symlinks=False"), 3)
        self.assertEqual(source.count("os.open("), 1)
        self.assertIn(
            "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC",
            source,
        )
        self.assertIn("os.open(TRUSTED_PARENT, flags)", source)
        self.assertNotIn("os.listdir", source)
        self.assertNotIn("os.scandir", source)
        self.assertNotIn("os.open(PERSISTENT_NAME", source)
        self.assertNotIn("os.read", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("urllib", source)
        for forbidden in (
            "mkdir", "makedirs", "chmod", "chown", "unlink", "remove(",
            "rmdir", "rename", "replace(", "psycopg", "sqlite3",
            "100.100.100.200", "os.environ", "os.getenv", "readlink",
        ):
            self.assertNotIn(forbidden, source.lower())
        self.assertNotIn('"/usr/bin/docker"', source)
        self.assertNotIn("docker run", source.lower())
        self.assertIn('TRUSTED_PARENT = "/var/lib"', source)
        self.assertIn('PERSISTENT_NAME = "noteai"', source)
        self.assertNotIn("0o755", source)
        self.assertNotIn("trusted.st_gid != 0", source)
        self.assertNotIn("trusted.st_nlink <", source)
        self.assertIn("(mode & 0o700) == 0o700", source)
        self.assertIn("(mode & 0o7000) == 0", source)
        self.assertIn("(mode & 0o022) == 0", source)

    def test_loader_accepts_exact_present_absent_and_terminal_schemas(self):
        alternate_safe_modes = []
        for mode in ("0700", "0711", "0750", "0755"):
            value = self.pass_value()
            value["trusted_parent_mode"] = mode
            value["trusted_parent_gid"] = 987
            value["trusted_parent_nlink"] = 1
            alternate_safe_modes.append((value, 0))
        cases = (
            (self.pass_value(), 0),
            (self.pass_value("ABSENT", "ABSENT"), 0),
            (self.pass_value("PRESENT", "SYMLINK"), 0),
            (self.terminal("FAIL", "trusted_parent"), 3),
            (self.terminal("FAIL", "tool"), 3),
            (self.terminal("UNKNOWN", "persistent_parent_runtime"), 4),
            (self.terminal("UNKNOWN", "persistent_parent_race"), 4),
        ) + tuple(alternate_safe_modes)
        for value, returncode in cases:
            with self.subTest(state=value["NOTEAI_ITEM26_RESTORED_PARENT_PROBE"]):
                result = self.run_wrapped(value, returncode)
                expected = probe.canonical(value)
                self.assertEqual(result.returncode, returncode)
                self.assertEqual(result.stdout, expected if returncode == 0 else b"")
                self.assertEqual(result.stderr, b"" if returncode == 0 else expected)

    def test_loader_rejects_aliases_duplicates_and_noncanonical_output(self):
        fixed = b'{"NOTEAI_ITEM26_RESTORED_PARENT_PROBE_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\n'
        invalid = []
        value = self.pass_value()
        invalid.append({**value, "schema_version": True})
        invalid.append({**value, "persistent_parent_uid": False})
        invalid.append({**value, "persistent_parent_mode": "700"})
        invalid.append({**value, "persistent_parent_nlink": 0})
        invalid.append({**value, "persistent_parent_type": "PATH"})
        invalid.append({**value, "persistent_parent_is_symlink": True})
        invalid.append({**value, "unexpected": "must-not-leak"})
        invalid.append({**value, "trusted_parent_gid": False})
        invalid.append({**value, "trusted_parent_nlink": False})
        invalid.append({**value, "trusted_parent_nlink": -1})
        invalid.append({**value, "trusted_parent_safe": 1})
        for unsafe_mode in ("755", "0655", "0775", "0777", "1755", "2755", "4755"):
            invalid.append({**value, "trusted_parent_mode": unsafe_mode})
        absent = self.pass_value("ABSENT", "ABSENT")
        invalid.append({**absent, "persistent_parent_uid": 0})
        for value in invalid:
            with self.subTest(invalid=value):
                result = self.run_wrapped(value)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (4, b"", fixed))
                self.assertNotIn(b"must-not-leak", result.stderr)

        duplicate = probe.canonical(self.pass_value()).replace(
            b'{"NOTEAI_', b'{"schema_version":1,"NOTEAI_', 1,
        )
        raw_child = (
            b"#!/bin/bash\nexec /usr/bin/python3 -I -B - <<'PY'\n"
            b"import os\nbody=" + repr(duplicate).encode("ascii") + b"\n"
            b"os.write(1,body)\nos._exit(0)\nPY\n"
        )
        rendered = probe._command_from_raw(raw_child, self.compressor)
        result = subprocess.run(
            ["/bin/bash", "-s"],
            input=base64.b64decode(rendered["base64"], validate=True),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (4, b"", fixed))

    def test_pinned_parent_and_child_lstat_are_race_safe(self):
        namespace = self.host_namespace()
        failure = namespace["Failure"]
        stat_call = mock.Mock(side_effect=[FileNotFoundError(), FileNotFoundError()])
        with mock.patch.object(namespace["os"], "stat", stat_call):
            self.assertIsNone(namespace["stable_child_lstat"](123))
        self.assertEqual(stat_call.call_count, 2)
        for row in stat_call.call_args_list:
            self.assertEqual(row.args, ("noteai",))
            self.assertEqual(
                row.kwargs,
                {"dir_fd": 123, "follow_symlinks": False},
            )

        for error in (PermissionError("denied"), OSError(5, "io")):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                namespace["os"], "stat", side_effect=error,
            ), self.assertRaises(failure) as caught:
                namespace["stable_child_lstat"](123)
            self.assertTrue(caught.exception.unknown)
            self.assertEqual(caught.exception.phase, "persistent_parent_runtime")

        fixture = self.metadata()
        drift = self.metadata(inode=3)
        with mock.patch.object(
            namespace["os"], "stat", side_effect=[fixture, drift],
        ), self.assertRaises(failure) as caught:
            namespace["stable_child_lstat"](123)
        self.assertTrue(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "persistent_parent_race")

        trusted = self.metadata(mode=0o750, gid=987, nlink=1)
        flags = (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        open_call = mock.Mock(return_value=42)
        close_call = mock.Mock()
        with mock.patch.object(
            namespace["os"], "lstat", side_effect=[trusted, trusted],
        ), mock.patch.object(
            namespace["os"], "open", open_call,
        ), mock.patch.object(
            namespace["os"], "fstat", return_value=trusted,
        ), mock.patch.object(
            namespace["os"], "close", close_call,
        ):
            self.assertEqual(namespace["pin_trusted_parent"](), (42, trusted))
        open_call.assert_called_once_with("/var/lib", flags)
        close_call.assert_not_called()

        unsafe_rows = (
            self.metadata(mode=0o655),
            self.metadata(mode=0o775),
            self.metadata(mode=0o4755),
            self.metadata(mode=0o755, uid=1),
            SimpleNamespace(**{
                **vars(self.metadata()),
                "st_mode": stat.S_IFLNK | 0o777,
            }),
        )
        for row in unsafe_rows:
            with self.subTest(unsafe_mode=oct(row.st_mode)), mock.patch.object(
                namespace["os"], "lstat", return_value=row,
            ), self.assertRaises(failure) as caught:
                namespace["pin_trusted_parent"]()
            self.assertFalse(caught.exception.unknown)
            self.assertEqual(caught.exception.phase, "trusted_parent")

        changed = self.metadata(mode=0o750, gid=987, nlink=1, inode=3)
        with mock.patch.object(
            namespace["os"], "lstat", side_effect=[trusted, trusted],
        ), mock.patch.object(
            namespace["os"], "open", return_value=42,
        ), mock.patch.object(
            namespace["os"], "fstat", return_value=changed,
        ), mock.patch.object(
            namespace["os"], "close",
        ), self.assertRaises(failure) as caught:
            namespace["pin_trusted_parent"]()
        self.assertTrue(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "trusted_parent_race")

        with mock.patch.object(
            namespace["os"], "fstat", return_value=trusted,
        ), mock.patch.object(
            namespace["os"], "lstat", return_value=changed,
        ), self.assertRaises(failure) as caught:
            namespace["verify_trusted_parent"](42, trusted)
        self.assertTrue(caught.exception.unknown)
        self.assertEqual(caught.exception.phase, "trusted_parent_race")

        with mock.patch.object(
            namespace["os"], "geteuid", return_value=0,
        ), mock.patch.dict(namespace, {
            "pin_trusted_parent": mock.Mock(return_value=(42, trusted)),
            "stable_child_lstat": mock.Mock(return_value=None),
            "verify_trusted_parent": mock.Mock(return_value=None),
        }), mock.patch.object(
            namespace["os"], "close",
        ):
            value = namespace["observe"]()
        self.assertEqual(value["trusted_parent_gid"], 987)
        self.assertEqual(value["trusted_parent_mode"], "0750")
        self.assertEqual(value["trusted_parent_nlink"], 1)
        self.assertIs(value["trusted_parent_safe"], True)
        self.assertEqual(value["persistent_parent_state"], "ABSENT")

    def test_exact_request_binding_no_replay_and_fresh_history_contract(self):
        plan = probe.render_plan(self.API_C, self.NONCE, self.compressor)
        self.assertEqual(
            plan,
            probe.render_plan(self.API_C, self.NONCE, self.compressor),
        )
        request = plan["request"]
        self.assertEqual(set(request), probe.RUN_COMMAND_KEYS)
        self.assertEqual(request["Name"], probe.COMMAND_NAME)
        self.assertEqual(request["InstanceId"], [self.API_C])
        self.assertEqual(request["ContentEncoding"], "Base64")
        self.assertEqual(request["RepeatMode"], "Once")
        self.assertEqual(request["Username"], "root")
        self.assertEqual(request["WorkingDir"], "/root")
        self.assertEqual(request["TerminationMode"], "ProcessTree")
        self.assertIs(request["KeepCommand"], True)
        self.assertIs(request["EnableParameter"], False)
        self.assertEqual(request["Timeout"], 120)
        self.assertEqual(plan["prerequisites"]["fresh_client_token_history_count_must_equal"], 0)
        self.assertEqual(plan["prerequisites"]["fresh_exact_name_target_history_count_must_equal"], 0)
        self.assertIs(plan["state"]["automatic_retry_allowed"], False)
        self.assertIs(plan["state"]["result_unlocks_initializer"], False)
        self.assertIs(plan["state"]["result_unlocks_v3"], False)
        self.assertIs(plan["state"]["same_invocation_replay_allowed"], False)
        self.assertIs(plan["state"]["same_request_resubmit_allowed"], False)
        self.assertEqual(plan["state"]["dispatch_count_limit"], 1)
        self.assertEqual(
            plan["state"]["provider_unknown_recovery"],
            "READBACK_EXACT_CLIENT_TOKEN_NAME_TARGET_NEVER_RESUBMIT",
        )
        self.assertEqual(
            probe.derive_client_token(self.NONCE),
            probe.derive_client_token(self.NONCE),
        )
        self.assertNotEqual(
            probe.derive_client_token(self.NONCE),
            probe.derive_client_token("f" * 32),
        )
        self.assertNotIn(self.NONCE, json.dumps(plan, sort_keys=True))

        for key, value in (
            ("Timeout", 120.0),
            ("KeepCommand", 1),
            ("EnableParameter", 0),
            ("InstanceId", [self.API_C, "i-other"]),
            ("Name", probe.COMMAND_NAME + "-other"),
            ("CommandContent", base64.b64encode(b"other").decode("ascii")),
            ("RepeatMode", "Period"),
            ("Username", "ecs-user"),
        ):
            mutated = copy.deepcopy(request)
            mutated[key] = value
            with self.subTest(key=key), self.assertRaises(probe.RenderError):
                probe.validate_request(mutated, self.API_C, self.NONCE, plan["command"])

        for key, value in (
            ("base64", "not base64"),
            ("bytes", True),
            ("bytes", plan["command"]["bytes"] + 1),
            ("sha256", "f" * 64),
        ):
            malformed = dict(plan["command"])
            malformed[key] = value
            with self.subTest(command_key=key, command_value=value), self.assertRaises(
                probe.RenderError,
            ):
                probe.validate_request(request, self.API_C, self.NONCE, malformed)

    def test_cli_is_canonical_strict_and_secret_free(self):
        request = probe.canonical({
            "api_c_instance_id": self.API_C,
            "mode": "parent_probe",
            "plan_nonce": self.NONCE,
        })
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(request)
        stdout = mock.Mock()
        stdout.buffer = io.BytesIO()
        with mock.patch.object(probe.sys, "stdin", stdin), mock.patch.object(
            probe.sys, "stdout", stdout,
        ), mock.patch.object(
            probe, "production_compressor", return_value=self.compressor,
        ):
            self.assertEqual(probe.cli(), 0)
        output = stdout.buffer.getvalue()
        self.assertEqual(probe.canonical(json.loads(output)), output)
        self.assertNotIn(self.NONCE.encode("ascii"), output)

        duplicate = request.replace(b'{"api_c_instance_id"', b'{"mode":"parent_probe","api_c_instance_id"', 1)
        with self.assertRaisesRegex(probe.RenderError, "duplicate_json_key"):
            probe.parse_canonical(duplicate)
        with self.assertRaisesRegex(probe.RenderError, "input_canonical"):
            probe.parse_canonical(json.dumps(json.loads(request)).encode("ascii") + b"\n")


if __name__ == "__main__":
    unittest.main()
