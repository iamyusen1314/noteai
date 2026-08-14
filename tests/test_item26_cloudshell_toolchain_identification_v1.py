import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import struct
import unittest
from pathlib import Path
from unittest import mock

from tools import validate_item26_cloudshell_toolchain_identification_v1 as validator


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".codex" / "item26-cloudshell-toolchain-identify-v1.template.py"
SPEC = importlib.util.spec_from_file_location("item26_toolchain_atom", TEMPLATE)
atom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(atom)


class Item26CloudShellToolchainIdentificationTests(unittest.TestCase):
    def shell(self, body, interpreter="/usr/bin/bash"):
        return ("#!" + interpreter + "\n" + body + "\n").encode("utf-8")

    def test_accepts_only_literal_shell_exec_with_exact_argv_forwarding(self):
        raw = self.shell("set -euo pipefail\nexec /usr/local/libexec/aliyun-real \"$@\"")
        interpreter, final_path, language = atom.parse_wrapper(
            raw, inherited_environment=set()
        )
        self.assertEqual(interpreter, "/usr/bin/bash")
        self.assertEqual(final_path, "/usr/local/libexec/aliyun-real")
        self.assertEqual(language, "shell")

    def test_accepts_readonly_literal_but_not_reassigned_or_unbound_target(self):
        raw = self.shell(
            "readonly FINAL=/usr/local/libexec/aliyun-real\nexec \"$FINAL\" \"$@\""
        )
        self.assertEqual(
            atom.parse_wrapper(raw, inherited_environment=set())[1],
            "/usr/local/libexec/aliyun-real",
        )
        for body in (
            "FINAL=/usr/local/libexec/aliyun-real\nexec \"$FINAL\" \"$@\"",
            "readonly FINAL=/one\nreadonly FINAL=/two\nexec \"$FINAL\" \"$@\"",
            "readonly FINAL=/one\nexec \"$OTHER\" \"$@\"",
            "readonly FINAL=/one\nreadonly PATH=/two\nexec \"$FINAL\" \"$@\"",
            "readonly UNUSED=/one\nexec /two \"$@\"",
        ):
            with self.assertRaises(atom.Blocked):
                atom.parse_wrapper(self.shell(body), inherited_environment=set())

    def test_rejects_path_and_every_inherited_environment_dispatch_name(self):
        for name in ("PATH", "FINAL", "HOME", "CUSTOM_INHERITED"):
            raw = self.shell(
                "readonly %s=/usr/local/libexec/aliyun-real\nexec \"$%s\" \"$@\""
                % (name, name)
            )
            inherited = set([name]) if name not in atom.FORBIDDEN_SHELL_NAMES else set()
            with self.subTest(name=name), self.assertRaises(atom.Blocked):
                atom.parse_wrapper(raw, inherited_environment=inherited)
        safe = self.shell(
            "readonly ITEM26_FINAL=/usr/local/libexec/aliyun-real\n"
            "exec \"$ITEM26_FINAL\" \"$@\""
        )
        self.assertEqual(
            atom.parse_wrapper(safe, inherited_environment=set())[1],
            "/usr/local/libexec/aliyun-real",
        )
        with self.assertRaises(atom.Blocked):
            atom.parse_wrapper(safe, inherited_environment=set(["ITEM26_FINAL"]))

    def test_rejects_path_lookup_download_dynamic_dispatch_and_shell_control_flow(self):
        bodies = (
            "PATH=/usr/local/bin:/usr/bin\nexec aliyun-real \"$@\"",
            "readonly FINAL=$(command -v aliyun-real)\nexec \"$FINAL\" \"$@\"",
            "curl -o /tmp/aliyun https://example.invalid/aliyun\nexec /tmp/aliyun \"$@\"",
            "if test -x /one; then exec /one \"$@\"; else exec /two \"$@\"; fi",
            "exec ${FINAL:-/usr/local/bin/aliyun} \"$@\"",
            "readonly FINAL=/usr/local/bin/aliyun\nexec \"$FINAL}\" \"$@\"",
            "exec /usr/local/bin/aliyun --profile default \"$@\"",
            "set -a\nreadonly FINAL=/usr/local/bin/aliyun\nexec \"$FINAL\" \"$@\"",
        )
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(atom.Blocked):
                atom.parse_wrapper(self.shell(body), inherited_environment=set())

    def test_rejects_env_shebang_relative_paths_and_multiple_execs(self):
        samples = (
            self.shell("exec /usr/local/bin/aliyun \"$@\"", "/usr/bin/env"),
            self.shell("exec aliyun \"$@\""),
            self.shell("exec /one \"$@\"\nexec /two \"$@\""),
        )
        for raw in samples:
            with self.assertRaises(atom.Blocked):
                atom.parse_wrapper(raw, inherited_environment=set())

    def test_accepts_narrow_python_execv_and_rejects_system_or_computed_target(self):
        accepted = b"#!/usr/bin/python3\nimport os, sys\nFINAL = '/usr/local/bin/aliyun-real'\nos.execv(FINAL, [FINAL] + sys.argv[1:])\n"
        self.assertEqual(atom.parse_wrapper(accepted), (
            "/usr/bin/python3", "/usr/local/bin/aliyun-real", "python",
        ))
        rejected = (
            b"#!/usr/bin/python3\nimport os, sys\nos.system('/usr/local/bin/aliyun-real')\n",
            b"#!/usr/bin/python3\nimport os, sys\nFINAL = os.environ['FINAL']\nos.execv(FINAL, [FINAL] + sys.argv[1:])\n",
            b"#!/usr/bin/python3\nimport subprocess, sys\nsubprocess.call(['/usr/local/bin/aliyun-real'] + sys.argv[1:])\n",
            b"#!/usr/bin/python3\nimport os, sys\nFINAL = '/usr/local/bin/aliyun-real'\nUNUSED = '/tmp/other'\nos.execv(FINAL, [FINAL] + sys.argv[1:])\n",
            b"#!/usr/bin/python3\nimport os as sys, sys as os\nFINAL = '/usr/local/bin/aliyun-real'\nos.execv(FINAL, [FINAL] + sys.argv[1:])\n",
        )
        for raw in rejected:
            with self.assertRaises(atom.Blocked):
                atom.parse_wrapper(raw)

    def test_static_elf_identity_rejects_dynamic_or_wrong_machine(self):
        header = bytearray(120)
        header[:16] = b"\x7fELF\x02\x01\x01\x00" + (b"\x00" * 8)
        struct.pack_into("<H", header, 16, 2)
        struct.pack_into("<H", header, 18, 62)
        struct.pack_into("<I", header, 20, 1)
        struct.pack_into("<Q", header, 24, 0x400040)
        struct.pack_into("<Q", header, 32, 64)
        struct.pack_into("<I", header, 48, 0)
        struct.pack_into("<H", header, 52, 64)
        struct.pack_into("<H", header, 54, 56)
        struct.pack_into("<H", header, 56, 1)
        struct.pack_into(
            "<IIQQQQQQ",
            header,
            64,
            1,
            5,
            0,
            0x400000,
            0x400000,
            len(header),
            len(header),
            0x1000,
        )
        atom.verify_static_linux_amd64_elf(bytes(header), len(header))
        for program_type, machine in ((2, 62), (3, 62), (1, 183)):
            mutated = bytearray(header)
            struct.pack_into("<I", mutated, 64, program_type)
            struct.pack_into("<H", mutated, 18, machine)
            with self.assertRaises(atom.Blocked):
                atom.verify_static_linux_amd64_elf(bytes(mutated), len(mutated))

    def test_static_elf_rejects_header_table_load_and_entry_mutations(self):
        header = bytearray(120)
        header[:16] = b"\x7fELF\x02\x01\x01\x00" + (b"\x00" * 8)
        struct.pack_into("<HHIQQQIHHHHHH", header, 16,
                         2, 62, 1, 0x400040, 64, 0, 0, 64, 56, 1, 0, 0, 0)
        struct.pack_into("<IIQQQQQQ", header, 64,
                         1, 5, 0, 0x400000, 0x400000, 120, 120, 0x1000)
        mutations = []
        for offset, fmt, value in (
            (6, "<B", 0),
            (20, "<I", 0),
            (52, "<H", 63),
            (32, "<Q", 0),
            (54, "<H", 55),
            (56, "<H", 0),
            (24, "<Q", 0x500000),
            (64, "<I", 4),
            (96, "<Q", 121),
        ):
            mutated = bytearray(header)
            struct.pack_into(fmt, mutated, offset, value)
            mutations.append(mutated)
        for mutated in mutations:
            with self.assertRaises(atom.Blocked):
                atom.verify_static_linux_amd64_elf(bytes(mutated), len(mutated))
        with self.assertRaises(atom.Blocked):
            atom.verify_static_linux_amd64_elf(bytes(header), 119)

    def record(self, role, path, size=100, digest=None):
        return {
            "role": role,
            "invoked_path": path,
            "canonical_path": path,
            "uid": 0,
            "gid": 0,
            "mode": "0755",
            "nlink": 1,
            "size": size,
            "sha256": digest or ("a" * 64),
            "symlinks": [],
        }

    def valid_commitment(self):
        before = [
            self.record("wrapper", validator.WRAPPER_PATH, validator.WRAPPER_BYTES, validator.WRAPPER_SHA256),
            self.record("wrapper_interpreter", "/usr/bin/bash", 1000, "b" * 64),
            self.record("final_cli", "/usr/local/libexec/aliyun-real", 2000, "c" * 64),
        ]
        value = {
            "schema": validator.SCHEMA,
            "status": "PASS",
            "parser": validator.PARSER,
            "wrapper_language": "shell",
            "wrapper_policy": {
                "absolute_shebang": True,
                "literal_final_exec": True,
                "exact_argv_forwarding": True,
                "path_lookup": False,
                "variable_dispatch": False,
                "inherited_environment_dispatch": False,
                "dynamic_download": False,
                "cli_invocations": 0,
            },
            "final_cli_format": "elf64-static-linux-amd64",
            "before": before,
            "after": copy.deepcopy(before),
            "before_after_equal": True,
        }
        value["commitment_sha256"] = hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return value

    def test_validator_accepts_exact_commitment(self):
        value = self.valid_commitment()
        self.assertEqual(validator.validate(value), value["commitment_sha256"])

    def test_validator_rejects_mutated_chain_policy_and_commitment(self):
        mutations = []
        value = self.valid_commitment()
        value["after"][2]["sha256"] = "d" * 64
        mutations.append(value)
        value = self.valid_commitment()
        value["wrapper_policy"]["path_lookup"] = True
        mutations.append(value)
        value = self.valid_commitment()
        value["before"][1]["uid"] = 1000
        value["after"][1]["uid"] = 1000
        mutations.append(value)
        value = self.valid_commitment()
        value["commitment_sha256"] = "0" * 64
        mutations.append(value)
        value = self.valid_commitment()
        link = {
            "path": "/unrelated/link",
            "uid": 0,
            "gid": 0,
            "mode": "0777",
            "nlink": 1,
            "target_sha256": "e" * 64,
        }
        value["before"][2]["symlinks"] = [link]
        value["after"][2]["symlinks"] = [copy.deepcopy(link)]
        value["commitment_sha256"] = hashlib.sha256(
            json.dumps({k: v for k, v in value.items() if k != "commitment_sha256"},
                       sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        mutations.append(value)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(validator.Invalid):
                validator.validate(mutation)

    def recommit(self, value):
        payload = {key: item for key, item in value.items() if key != "commitment_sha256"}
        value["commitment_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return value

    def test_validator_is_recursive_type_exact_for_before_and_after(self):
        mutations = []
        value = self.valid_commitment()
        value["before"][1]["uid"] = False
        value["after"][1]["uid"] = False
        mutations.append(self.recommit(value))
        value = self.valid_commitment()
        value["before_after_equal"] = 1
        mutations.append(self.recommit(value))
        value = self.valid_commitment()
        value["wrapper_policy"]["cli_invocations"] = False
        mutations.append(self.recommit(value))
        value = self.valid_commitment()
        value["before"][2]["symlinks"] = [False]
        value["after"][2]["symlinks"] = [False]
        mutations.append(self.recommit(value))
        value = self.valid_commitment()
        value["after"][2]["size"] = 1.0
        mutations.append(self.recommit(value))
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(validator.Invalid):
                validator.validate(mutation)
        for root in ([], "PASS", True, 1, None):
            with self.subTest(root=root), self.assertRaises(validator.Invalid):
                validator.validate(root)

    def test_validator_main_uses_one_fixed_invalid_marker(self):
        for raw in ("[{}]", '{"schema":"one","schema":"two"}', "null"):
            output = io.StringIO()
            with mock.patch.object(validator.Path, "read_text", return_value=raw), \
                    contextlib.redirect_stdout(output):
                status = validator.main(["validator", "/unused"])
            self.assertEqual(status, 1)
            self.assertEqual(output.getvalue(), "ITEM26_TOOLCHAIN_IDENTIFICATION_INVALID\n")

    def test_template_has_no_cli_execution_or_network_process_imports(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import socket", "import urllib", "os.system(", "os.exec"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
