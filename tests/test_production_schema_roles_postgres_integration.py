import ast
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from tools import collect_production_database_preflight as preflight
from tools import production_first_launch_role_risk_set_audit as set_audit
from tools import production_schema_owner_authority_preflight as owner_preflight
from tools import production_schema_outcome_audit as outcome_audit
from tools import (
    production_schema_privileged_owner_preflight as privileged_owner,
)
from tools import render_item26_v3_transport as item26_transport_renderer
from tools import production_schema_roles as schema_roles


LOCAL_DSN_ENV = "NOTEAI_LOCAL_PG16_SCHEMA_ROLE_DSN"
TASK_EXECUTOR_ROLE = "noteai_schema_task_executor"
ITEM26_TEMPLATE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".codex"
    / "item26-source-manifest.template.sh"
)
def _load_item26_owner_gate():
    source = ITEM26_TEMPLATE_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'cat >"\$DRIVER_PATH" <<\'PY\'\n(.*?)\nPY\n',
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("Item26 driver heredoc is missing")
    tree = ast.parse(match.group(1))
    required_assignments = {
        "ACCOUNT", "OWNER", "MANAGED", "TABLES", "RLS",
    }
    required_definitions = {"Fixed", "one", "owner_gate"}
    selected = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id in required_assignments
                for target in node.targets
            )
        ):
            selected.append(node)
        elif (
            isinstance(node, (ast.ClassDef, ast.FunctionDef))
            and node.name in required_definitions
        ):
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {}
    exec(compile(module, str(ITEM26_TEMPLATE_PATH), "exec"), namespace)
    missing = (required_assignments | required_definitions) - set(namespace)
    if missing:
        raise AssertionError(f"Item26 owner gate definitions missing: {missing}")
    return namespace


def _expected_rls_tables_from_migrations():
    enabled = set()
    forced = set()
    enable_pattern = re.compile(
        r"\bALTER\s+TABLE\s+([a-z_][a-z0-9_]*)\s+"
        r"ENABLE\s+ROW\s+LEVEL\s+SECURITY\s*;",
        re.IGNORECASE,
    )
    force_pattern = re.compile(
        r"\bALTER\s+TABLE\s+([a-z_][a-z0-9_]*)\s+"
        r"FORCE\s+ROW\s+LEVEL\s+SECURITY\s*;",
        re.IGNORECASE,
    )
    for path in sorted(schema_roles.MIGRATION_DIR.glob("*.sql")):
        source = path.read_text(encoding="utf-8")
        enabled.update(match.lower() for match in enable_pattern.findall(source))
        forced.update(match.lower() for match in force_pattern.findall(source))
    return tuple(sorted(enabled)), tuple(sorted(forced))


class Item26SourceManifestImportGuardTests(unittest.TestCase):
    def test_runtime_import_guard_prevents_sqlite_initialization(self):
        repository_root = pathlib.Path(__file__).resolve().parents[1]
        probe = r'''
import ast
import os
import pathlib
import re
import sqlite3
import sys

template_path = pathlib.Path(sys.argv[1])
repository_root = pathlib.Path(sys.argv[2])
sqlite_path = pathlib.Path(sys.argv[3])
source = template_path.read_text(encoding="utf-8")
match = re.search(
    r'cat >"\$DRIVER_PATH" <<\'PY\'\n(.*?)\nPY\n',
    source,
    re.DOTALL,
)
if match is None:
    raise SystemExit(11)
tree = ast.parse(match.group(1))
selected = []
for node in tree.body:
    if (
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "IMPORT_GUARD_DATABASE_URL"
            for target in node.targets
        )
    ) or (
        isinstance(node, ast.FunctionDef)
        and node.name == "runtime_modules"
    ):
        selected.append(node)
module = ast.Module(body=selected, type_ignores=[])
namespace = {"os": os, "sys": sys}
exec(compile(module, str(template_path), "exec"), namespace)
if namespace.get("IMPORT_GUARD_DATABASE_URL") != (
    "postgresql:///noteai_item26_import_guard"
):
    raise SystemExit(12)
os.environ.pop("DATABASE_URL", None)
os.environ["NOTEAI_SQLITE_PATH"] = str(sqlite_path)
sys.path.insert(0, str(repository_root / "model"))
modules = namespace["runtime_modules"]()
if len(modules) != 5:
    raise SystemExit(13)
if "DATABASE_URL" in os.environ:
    raise SystemExit(14)
if sqlite_path.exists():
    raise SystemExit(15)
database_module = sys.modules.get("db")
if database_module is None or database_module.using_postgres():
    raise SystemExit(16)
if pathlib.Path(database_module._DB_PATH) != sqlite_path:
    raise SystemExit(17)
private_storage, recovery, psycopg, _dict_row, _transaction_status = modules
blocked_calls = []
def blocked(name):
    def fail(*_args, **_kwargs):
        blocked_calls.append(name)
        raise AssertionError(name)
    return fail
sqlite3.connect = blocked("sqlite3.connect")
psycopg.connect = blocked("psycopg.connect")
for name in (
    "transaction",
    "get_conn",
    "_get_sqlite_conn",
    "_get_postgres_conn",
):
    setattr(database_module, name, blocked("db." + name))

class EmptyCursor:
    def fetchall(self):
        return []

class EmptyConnection:
    def __init__(self):
        self.execute_count = 0
    def execute(self, _statement, _parameters=()):
        self.execute_count += 1
        return EmptyCursor()

class EmptyBackend:
    def list(self, _prefix, *, limit, cursor=None):
        if not 1 <= limit <= private_storage.MAX_OBJECT_LIST_LIMIT:
            raise AssertionError("limit")
        if cursor is not None:
            raise AssertionError("cursor")
        return [], None

connection = EmptyConnection()
adapter = type(
    "Adapter",
    (),
    {
        "postgres": True,
        "fetchall": lambda self, statement, parameters=(): (
            self.connection.execute(
                statement.replace("?", "%s"),
                tuple(parameters),
            ).fetchall()
        ),
    },
)()
adapter.connection = connection
manifest = recovery.capture_manifest(
    release_commit="0" * 40,
    storage=adapter,
    backend=EmptyBackend(),
    require_objects=True,
    max_rows_per_table=1,
    max_objects=1,
)
if manifest["database"]["engine"] != "postgresql":
    raise SystemExit(18)
if manifest["database"]["table_count"] != 0:
    raise SystemExit(19)
if manifest["objects"]["object_count"] != 0:
    raise SystemExit(20)
if connection.execute_count != 1:
    raise SystemExit(21)
if blocked_calls:
    raise SystemExit(22)
if sqlite_path.exists():
    raise SystemExit(23)
'''
        clean_environment = {
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            sqlite_path = pathlib.Path(temporary_directory) / "noteai.db"
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    probe,
                    str(ITEM26_TEMPLATE_PATH),
                    str(repository_root),
                    str(sqlite_path),
                ],
                cwd=str(repository_root),
                env=clean_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                result.stderr.decode("utf-8", errors="replace")[:2000],
            )
            self.assertFalse(sqlite_path.exists())

    def test_v3_transport_and_readback_templates_are_bound_and_bounded(self):
        import base64
        import gzip
        import inspect
        import json
        from unittest import mock

        def deterministic_gzip(payload):
            result = subprocess.run(
                ["/usr/bin/gzip", "-9", "-n"],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr[:2000])
            return result.stdout

        envelope_sha256 = (
            "2c522a13b236301c5276088dd6ae83cabb5ac9c6a45923385831ec582d81e90a"
        )
        public_key_sha256 = (
            "dc8f8283248dd232030bb63d19f669ccdaad89faa87dbdffb7b5eb5aae83969a"
        )
        rendered = item26_transport_renderer._render_item26_v3_transport_for_test(
            894,
            envelope_sha256,
            public_key_sha256,
            gzip_compressor=deterministic_gzip,
        )
        artifacts = rendered["artifacts"]
        summary = rendered["sizing"]
        self.assertEqual(rendered["mode"], "TEST_SIZING_ONLY")
        self.assertNotIn("summary", rendered)
        self.assertEqual(
            tuple(
                inspect.signature(
                    item26_transport_renderer.render_item26_v3_transport
                ).parameters
            ),
            ("envelope_bytes", "envelope_sha256", "public_key_sha256"),
        )
        with self.assertRaises(TypeError):
            item26_transport_renderer.render_item26_v3_transport(
                894,
                envelope_sha256,
                public_key_sha256,
                gzip_compressor=deterministic_gzip,
            )
        with mock.patch.object(
            item26_transport_renderer,
            "_sha256",
            return_value="0" * 64,
        ):
            with self.assertRaises(item26_transport_renderer.RenderError):
                item26_transport_renderer._read_template("source")
        partial_writes = []

        def short_write(_file_descriptor, payload):
            chunk = bytes(payload[:3])
            partial_writes.append(chunk)
            return len(chunk)

        with mock.patch.object(
            item26_transport_renderer.os,
            "write",
            side_effect=short_write,
        ):
            self.assertTrue(item26_transport_renderer._write_all(1, b"abcdefgh"))
        self.assertEqual(b"".join(partial_writes), b"abcdefgh")
        self.assertEqual(
            set(artifacts),
            set(item26_transport_renderer.SUMMARY_LAYER_NAMES),
        )
        self.assertEqual(
            set(summary),
            set(item26_transport_renderer.SUMMARY_LAYER_NAMES)
            | set(item26_transport_renderer.SUMMARY_COMMAND_NAMES),
        )
        for name in item26_transport_renderer.SUMMARY_LAYER_NAMES:
            self.assertEqual(set(summary[name]), {"bytes", "sha256"})
            self.assertEqual(summary[name]["bytes"], len(artifacts[name]))
            self.assertEqual(
                summary[name]["sha256"],
                hashlib.sha256(artifacts[name]).hexdigest(),
            )

        self.assertEqual(len(artifacts["driver"]), 18084)
        self.assertEqual(
            hashlib.sha256(artifacts["driver"]).hexdigest(),
            "282c789b8918cdbe9e1512a0a54e248ab7d9e2814aea1629f8353487d962d67e",
        )
        self.assertTrue(artifacts["driver"].endswith(b"\n"))
        for name in ("source", "executor", "controller", "wrapper", "readback"):
            self.assertIsNone(
                item26_transport_renderer.PLACEHOLDER.search(artifacts[name])
            )

        command = summary["command_content"]
        self.assertEqual(set(command), {"base64", "bytes", "sha256"})
        command_bytes = command["base64"].encode("ascii")
        self.assertEqual(command["bytes"], len(command_bytes))
        self.assertLessEqual(command["bytes"], 18000)
        self.assertEqual(
            command["sha256"],
            hashlib.sha256(command_bytes).hexdigest(),
        )
        self.assertEqual(
            base64.b64decode(command_bytes, validate=True),
            artifacts["wrapper"],
        )
        readback_command = summary["readback_command_content"]
        self.assertEqual(
            set(readback_command),
            {"base64", "bytes", "sha256"},
        )
        readback_command_bytes = readback_command["base64"].encode("ascii")
        self.assertEqual(readback_command["bytes"], len(readback_command_bytes))
        self.assertLessEqual(readback_command["bytes"], 18000)
        self.assertEqual(
            readback_command["sha256"],
            hashlib.sha256(readback_command_bytes).hexdigest(),
        )
        self.assertEqual(
            base64.b64decode(readback_command_bytes, validate=True),
            artifacts["readback_wrapper"],
        )
        with self.assertRaises(item26_transport_renderer.RenderError):
            item26_transport_renderer.canonical_summary(summary)

        expected_apple_sizing = {
            "source": {
                "bytes": 35425,
                "sha256": "c3d86745eb12a1155100a55106f6cead2e0b9577dffe5950cddcb0668ab87d2a",
            },
            "driver": {
                "bytes": 18084,
                "sha256": "282c789b8918cdbe9e1512a0a54e248ab7d9e2814aea1629f8353487d962d67e",
            },
            "transfer_gzip": {
                "bytes": 10594,
                "sha256": "d9b66022e78b1f659252e79bd1952b79ad35ba18b88fa28f484d5cc2f6c55023",
            },
            "executor": {
                "bytes": 17035,
                "sha256": "456fa3c25c69f96d573c8167d6c65fbbdb30f22c258b0b33d0cef1009acdcd37",
            },
            "executor_gzip": {
                "bytes": 4476,
                "sha256": "d07378c61de3dc4d5d109f865c729ac74771492a390f257c499c25b5cbcb7942",
            },
            "controller": {
                "bytes": 15666,
                "sha256": "e1450626559bd8656f81c8413065e93d9cf481b7baf1ba6a282e3231c85a9d0e",
            },
            "controller_gzip": {
                "bytes": 7609,
                "sha256": "54d273d11c9c2da7e4b9c6fa2859ff7e1a7f430d4c3df8fe57abf92552d78bc1",
            },
            "wrapper": {
                "bytes": 12810,
                "sha256": "42edd3534f5293455178cb457f251783c68ed3cf1a28be90c5c333ad8e27f268",
            },
            "readback": {
                "bytes": 25895,
                "sha256": "a79fb6312605599e232d70833f05b07d9b078b4a33d8f528eb2d082c852660d8",
            },
            "readback_validator": {
                "bytes": 11528,
                "sha256": "f22cd609d2935d24f85c98057b603edc48ff938cb6d661419a8abb89104b4562",
            },
            "readback_payload": {
                "bytes": 37431,
                "sha256": "af8c385a25b63fc94f5a75e40d8ff9cb8464b65adfbd12ed2a979695059ae330",
            },
            "readback_payload_gzip": {
                "bytes": 8227,
                "sha256": "183aa39f6a79ccd8e38d406db4983b1023382d77235cca87f4e2fe6057dff960",
            },
            "readback_wrapper": {
                "bytes": 13451,
                "sha256": "0aeaf413dbd9d5fc8415d1f46d0eea038e821d36aa5e46f265c34b6a41a87339",
            },
            "command_content": {
                "bytes": 17080,
                "sha256": "a6ace3aef127817396ff75e794379c18003732384ee6191b3459cc1f61b82ec7",
            },
            "readback_command_content": {
                "bytes": 17936,
                "sha256": "e1982e0759fb4390f818e30a0c190e60efb5d809d4c31828e492d333476b643d",
            },
        }
        expected_gnu_sizing = {
            "source": {
                "bytes": 35425,
                "sha256": "c3d86745eb12a1155100a55106f6cead2e0b9577dffe5950cddcb0668ab87d2a",
            },
            "driver": {
                "bytes": 18084,
                "sha256": "282c789b8918cdbe9e1512a0a54e248ab7d9e2814aea1629f8353487d962d67e",
            },
            "transfer_gzip": {
                "bytes": 10534,
                "sha256": "0c2ad55242e9d8cb5b410f5e8ad782d60b59772ba722daeb9418e10e94dc053a",
            },
            "executor": {
                "bytes": 17035,
                "sha256": "b19920ce377e4f9b1d4272ff6c27a89e33de0311a7c98be96dbea088ff09c673",
            },
            "executor_gzip": {
                "bytes": 4473,
                "sha256": "72354a463675d576cd1ee1c4b9ff4fe0c7fee9832ede3d60d6e4c2a81d9282c5",
            },
            "controller": {
                "bytes": 15663,
                "sha256": "79c693b64b64bc9ba7cda3f4c4abde3bb980e7a229843c79447cdb5104b87c9c",
            },
            "controller_gzip": {
                "bytes": 7603,
                "sha256": "507bcc92bbb1bfb8e94d2de7bbc5a287cc9b975df064ec1b3240666aafe28560",
            },
            "wrapper": {
                "bytes": 12802,
                "sha256": "e5e56b8cffb8c363c56c12800de01563de451a111924c8a03ffd2245fd1a6d55",
            },
            "readback": {
                "bytes": 25895,
                "sha256": "b8d7c78b987d00360e298b2ccbbb6d7b822b79ad040157bb23003daab32a342f",
            },
            "readback_validator": {
                "bytes": 11528,
                "sha256": "f22cd609d2935d24f85c98057b603edc48ff938cb6d661419a8abb89104b4562",
            },
            "readback_payload": {
                "bytes": 37431,
                "sha256": "543388587968bb51435fe0211ee55a24c87990e045347d4384b0948c27ee257f",
            },
            "readback_payload_gzip": {
                "bytes": 8173,
                "sha256": "df68c86a17f5019bcd24554ce6c8f7cff9b3228a3c91cb1a90cadd53ae501089",
            },
            "readback_wrapper": {
                "bytes": 13384,
                "sha256": "7abe1416179a455c92f807b6fd24880f797df5ad72555abd9f46c69713c38911",
            },
            "command_content": {
                "bytes": 17072,
                "sha256": "fb3c0ee5768341fcb54cb62c94c33a3a3592cb6770307de918cfefcda84d8a0d",
            },
            "readback_command_content": {
                "bytes": 17848,
                "sha256": "9f903382e097dd2d00b606f058c42e6392e6723cec331dc360a5515d38e4208e",
            },
        }
        expected_sizing = (
            expected_gnu_sizing
            if sys.platform.startswith("linux")
            else expected_apple_sizing
        )
        actual_sizing = {
            name: {
                "bytes": summary[name]["bytes"],
                "sha256": summary[name]["sha256"],
            }
            for name in expected_sizing
        }
        self.assertEqual(actual_sizing, expected_sizing)

        readback = artifacts["readback"].decode("ascii")
        self.assertIn("DRIVER_BYTES = 18084", readback)
        self.assertIn(
            'DRIVER_SHA256 = "282c789b8918cdbe9e1512a0a54e248ab7d9e2814aea1629f8353487d962d67e"',
            readback,
        )
        self.assertIn(
            'TRANSFER = "/run/noteai-item26-source-manifest-transfer-v3.sh.gz"',
            readback,
        )
        self.assertEqual(readback.count("manifest_readback_allowed = True"), 2)
        self.assertNotIn("same_invocation_replay_allowed\": True", readback)

        fixed_readback = {
            "NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK": "READBACK_UNKNOWN",
            "automatic_retry_allowed": False,
            "cleanup_allowed": False,
            "manifest_readback_allowed": False,
            "new_capture_allowed": False,
            "pitr_stage_allowed": False,
            "same_invocation_replay_allowed": False,
            "temporary_account_delete_allowed": False,
            "worker_stage_allowed": False,
        }

        def canonical(value):
            return (
                json.dumps(
                    value,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("ascii")

        def raw_fixture(value, returncode):
            body_b64 = base64.b64encode(canonical(value))
            return (
                b"#!/bin/bash\nexec python3 -I -B - <<'PY'\n"
                b"import base64,os\n"
                b"body=base64.b64decode(b'"
                + body_b64
                + b"')\n"
                b"written=os.write(1,body)\n"
                b"raise SystemExit("
                + str(returncode).encode("ascii")
                + b" if written==len(body) else 4)\nPY\n"
            )

        def sleeping_raw_fixture():
            return (
                b"#!/bin/bash\nexec python3 -I -B - <<'PY'\n"
                b"import os,time\n"
                b"if os.fork()==0: time.sleep(120)\n"
                b"time.sleep(120)\nPY\n"
            )

        def rendered_readback_wrapper(value, returncode):
            raw = raw_fixture(value, returncode)
            chain = item26_transport_renderer._render_readback_transport(
                raw,
                deterministic_gzip,
            )
            self.assertEqual(len(chain), 5)
            validator_bytes = len(chain[0])
            payload = chain[1]
            self.assertEqual(
                payload[:8],
                ("{:08d}".format(validator_bytes)).encode("ascii"),
            )
            self.assertEqual(
                gzip.decompress(chain[2]),
                payload,
            )
            self.assertEqual(payload[8:8 + validator_bytes], chain[0])
            self.assertEqual(payload[8 + validator_bytes:], raw)
            self.assertLessEqual(chain[4]["bytes"], 18000)
            return raw, chain[2], chain[3]

        def run_readback_wrapper(wrapper):
            return subprocess.run(
                ["/bin/bash", "-s"],
                input=wrapper,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                timeout=30,
                check=False,
            )

        full_readback = {
            "NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK": (
                "NO_TASK_NO_FINAL_EXECUTION_UNPROVEN"
            ),
            "host": "API-C",
            "host_identity_exact": True,
            "control_metadata_exact": True,
            "control_value_read_count": 0,
            "transfer_exact": True,
            "task_root_present": False,
            "task_root_exact": False,
            "task_inventory_state": "ABSENT",
            "driver_exact": False,
            "task_docker_config_exact": False,
            "final_root_present": False,
            "final_root_exact": False,
            "output_state": "ABSENT",
            "helper_stdout_bytes": None,
            "helper_stdout_value_read_count": 0,
            "helper_error_code": None,
            "task_container_query_ok": True,
            "task_container_count": 0,
            "task_container_exact": True,
            "established_5432_count": 0,
            "original_database_state": "EXECUTION_UNPROVEN",
            "manifest_readback_allowed": False,
            "same_invocation_replay_allowed": False,
            "new_capture_allowed": False,
            "cleanup_allowed": False,
            "temporary_account_delete_allowed": False,
            "pitr_stage_allowed": False,
            "worker_stage_allowed": False,
            "automatic_retry_allowed": False,
            "api_environment_value_read_count": 0,
            "storage_environment_value_read_count": 0,
            "source_secret_value_read_count": 0,
            "ciphertext_value_read_count": 0,
            "manifest_value_read_count": 0,
            "database_connection_count": 0,
            "database_write_count": 0,
            "object_read_count": 0,
            "object_write_count": 0,
            "provider_control_plane_mutation_count": 0,
            "runtime_container_start_count": 0,
        }
        self.assertEqual(len(full_readback), 41)
        _raw, _gzip, valid_wrapper = rendered_readback_wrapper(full_readback, 0)
        valid_result = run_readback_wrapper(valid_wrapper)
        self.assertEqual(valid_result.returncode, 0)
        self.assertEqual(valid_result.stdout, canonical(full_readback))
        self.assertEqual(valid_result.stderr, b"")

        for status in (
            "MANIFEST_COMMITTED_READBACK_REQUIRED",
            "STAGED_UNCOMMITTED_READBACK_REQUIRED",
        ):
            manifest_row = dict(full_readback)
            manifest_row.update(
                {
                    "NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK": status,
                    "original_database_state": "CONNECTED_READ_ONLY_ROLLBACK",
                    "manifest_readback_allowed": True,
                }
            )
            if status == "MANIFEST_COMMITTED_READBACK_REQUIRED":
                manifest_row.update(
                    {
                        "final_root_present": True,
                        "final_root_exact": True,
                        "task_root_present": True,
                        "task_root_exact": True,
                        "task_inventory_state": "POST_MOVE_EXACT",
                        "driver_exact": True,
                        "task_docker_config_exact": True,
                        "helper_stdout_bytes": 512,
                    }
                )
            else:
                manifest_row.update(
                    {
                        "task_root_present": True,
                        "task_root_exact": True,
                        "task_inventory_state": "HELPER_EXACT",
                        "driver_exact": True,
                        "task_docker_config_exact": True,
                        "output_state": "MANIFEST_PRESENT",
                        "helper_stdout_bytes": 512,
                    }
                )
            _raw, _gzip, manifest_wrapper = rendered_readback_wrapper(
                manifest_row,
                0,
            )
            manifest_result = run_readback_wrapper(manifest_wrapper)
            self.assertEqual(manifest_result.returncode, 0)
            self.assertEqual(manifest_result.stdout, canonical(manifest_row))
            self.assertEqual(manifest_result.stderr, b"")

        container_row = dict(full_readback)
        container_row.update(
            {
                "NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK": (
                    "CONTAINER_PRESENT_UNKNOWN"
                ),
                "task_container_count": 1,
                "task_container_exact": True,
                "original_database_state": (
                    "TASK_EXECUTION_OR_RESIDUE_UNKNOWN"
                ),
            }
        )
        _raw, _gzip, container_wrapper = rendered_readback_wrapper(
            container_row,
            0,
        )
        container_result = run_readback_wrapper(container_wrapper)
        self.assertEqual(container_result.returncode, 0)
        container_terminal = json.loads(container_result.stdout.decode("ascii"))
        for key in (
            "same_invocation_replay_allowed",
            "new_capture_allowed",
            "cleanup_allowed",
            "temporary_account_delete_allowed",
            "pitr_stage_allowed",
            "worker_stage_allowed",
            "automatic_retry_allowed",
        ):
            self.assertIs(container_terminal[key], False)

        docker_race_row = dict(container_row)
        docker_race_row.update(
            {
                "task_container_query_ok": False,
                "task_container_exact": False,
                "NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK": (
                    "CONTAINER_STATE_UNKNOWN"
                ),
                "original_database_state": "UNKNOWN",
            }
        )
        _raw, _gzip, docker_race_wrapper = rendered_readback_wrapper(
            docker_race_row,
            0,
        )
        docker_race_result = run_readback_wrapper(docker_race_wrapper)
        self.assertEqual(docker_race_result.returncode, 0)
        self.assertEqual(docker_race_result.stdout, canonical(docker_race_row))
        self.assertEqual(docker_race_result.stderr, b"")

        _raw, _gzip, fixed_wrapper = rendered_readback_wrapper(fixed_readback, 4)
        fixed_result = run_readback_wrapper(fixed_wrapper)
        self.assertEqual(fixed_result.returncode, 4)
        self.assertEqual(fixed_result.stdout, canonical(fixed_readback))
        self.assertEqual(fixed_result.stderr, b"")

        for invalid in (
            dict(full_readback, unexpected_field=0),
            dict(full_readback, host_identity_exact=1),
            dict(
                full_readback,
                NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK=(
                    "MANIFEST_COMMITTED_READBACK_REQUIRED"
                ),
                original_database_state="CONNECTED_READ_ONLY_ROLLBACK",
                manifest_readback_allowed=False,
            ),
            dict(
                full_readback,
                NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK=(
                    "MANIFEST_COMMITTED_READBACK_REQUIRED"
                ),
                original_database_state="CONNECTED_READ_ONLY_ROLLBACK",
                manifest_readback_allowed=True,
            ),
            dict(
                full_readback,
                NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK=(
                    "CONTAINER_PRESENT_UNKNOWN"
                ),
                original_database_state=(
                    "TASK_EXECUTION_OR_RESIDUE_UNKNOWN"
                ),
            ),
            dict(
                full_readback,
                NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK=(
                    "STAGED_UNCOMMITTED_READBACK_REQUIRED"
                ),
                original_database_state="CONNECTED_READ_ONLY_ROLLBACK",
                manifest_readback_allowed=True,
            ),
        ):
            _raw, _gzip, invalid_wrapper = rendered_readback_wrapper(invalid, 0)
            invalid_result = run_readback_wrapper(invalid_wrapper)
            self.assertEqual(invalid_result.returncode, 4)
            self.assertEqual(invalid_result.stdout, canonical(fixed_readback))
            self.assertEqual(invalid_result.stderr, b"")

        tamper_raw, tamper_gzip, tamper_wrapper = rendered_readback_wrapper(
            full_readback,
            0,
        )
        for supplied in (
            hashlib.sha256(tamper_gzip).hexdigest().encode("ascii"),
            hashlib.sha256(tamper_raw).hexdigest().encode("ascii"),
        ):
            self.assertEqual(tamper_wrapper.count(supplied), 1)
            replacement = b"0" * 64 if supplied != b"0" * 64 else b"f" * 64
            tampered_result = run_readback_wrapper(
                tamper_wrapper.replace(supplied, replacement, 1)
            )
            self.assertEqual(tampered_result.returncode, 4)
            self.assertEqual(tampered_result.stdout, canonical(fixed_readback))
            self.assertEqual(tampered_result.stderr, b"")

        validator = item26_transport_renderer.READBACK_VALIDATOR_SOURCE.decode(
            "ascii"
        )
        self.assertIn("start_new_session=True", validator)
        self.assertIn("os.killpg(process.pid, signal.SIGKILL)", validator)
        self.assertIn("process.communicate(timeout=5)", validator)
        timeout_source = validator.replace(
            "process.communicate(READBACK_RAW, timeout=90)",
            "process.communicate(READBACK_RAW, timeout=1)",
        ).encode("ascii")
        timeout_result = item26_transport_renderer._render_readback_transport(
            sleeping_raw_fixture(),
            deterministic_gzip,
        )
        self.assertEqual(timeout_result[0], item26_transport_renderer.READBACK_VALIDATOR_SOURCE)
        timeout_payload = (
            "{:08d}".format(len(timeout_source)).encode("ascii")
            + timeout_source
            + sleeping_raw_fixture()
        )
        timeout_gzip = deterministic_gzip(timeout_payload)
        timeout_wrapper = item26_transport_renderer._render(
            "timeout_readback_wrapper",
            item26_transport_renderer.READBACK_WRAPPER_TEMPLATE,
            {
                b"@@READBACK_PAYLOAD_GZIP_BYTES@@": str(
                    len(timeout_gzip)
                ).encode("ascii"),
                b"@@READBACK_PAYLOAD_GZIP_SHA256@@": hashlib.sha256(
                    timeout_gzip
                ).hexdigest().encode("ascii"),
                b"@@READBACK_PAYLOAD_BYTES@@": str(
                    len(timeout_payload)
                ).encode("ascii"),
                b"@@READBACK_PAYLOAD_SHA256@@": hashlib.sha256(
                    timeout_payload
                ).hexdigest().encode("ascii"),
                b"@@READBACK_PAYLOAD_GZIP_B85@@": base64.b85encode(
                    timeout_gzip
                ),
                b"@@READBACK_VALIDATOR_BYTES@@": str(
                    len(timeout_source)
                ).encode("ascii"),
                b"@@READBACK_VALIDATOR_SHA256@@": hashlib.sha256(
                    timeout_source
                ).hexdigest().encode("ascii"),
                b"@@READBACK_BYTES@@": str(
                    len(sleeping_raw_fixture())
                ).encode("ascii"),
                b"@@READBACK_SHA256@@": hashlib.sha256(
                    sleeping_raw_fixture()
                ).hexdigest().encode("ascii"),
            },
        )
        timeout_terminal = run_readback_wrapper(timeout_wrapper)
        self.assertEqual(timeout_terminal.returncode, 4)
        self.assertEqual(timeout_terminal.stdout, canonical(fixed_readback))
        self.assertEqual(timeout_terminal.stderr, b"")

        if sys.platform.startswith("linux"):
            production_render = item26_transport_renderer.render_item26_v3_transport(
                894,
                envelope_sha256,
                public_key_sha256,
            )
            self.assertEqual(production_render["artifacts"], artifacts)
            production_summary = production_render["summary"]
            self.assertEqual(
                set(production_summary),
                item26_transport_renderer.SUMMARY_KEYS,
            )
            production_sizing = {
                name: {
                    "bytes": production_summary[name]["bytes"],
                    "sha256": production_summary[name]["sha256"],
                }
                for name in expected_sizing
            }
            self.assertEqual(production_sizing, expected_sizing)
            self.assertEqual(
                production_summary["public_bindings"],
                {
                    "envelope_bytes": 894,
                    "envelope_sha256": envelope_sha256,
                    "public_key_sha256": public_key_sha256,
                },
            )
            self.assertEqual(
                production_summary["production_provenance"],
                item26_transport_renderer._production_provenance_summary(),
            )
            canonical = item26_transport_renderer.canonical_summary(
                production_summary
            )
            self.assertEqual(
                json.loads(canonical.decode("ascii")),
                production_summary,
            )
            invalid_summary = json.loads(canonical.decode("ascii"))
            invalid_summary["wrapper"]["sha256"] = "0" * 64
            with self.assertRaises(item26_transport_renderer.RenderError):
                item26_transport_renderer.canonical_summary(invalid_summary)


@unittest.skipUnless(os.environ.get(LOCAL_DSN_ENV), "local PostgreSQL 16 only")
class ProductionSchemaRolesPostgresIntegrationTests(unittest.TestCase):
    def _grant_table_matrix(self, conn, role, matrix):
        for table, privileges in matrix.items():
            conn.execute(
                sql.SQL("GRANT {} ON TABLE {}.{} TO {}").format(
                    sql.SQL(", ").join(
                        sql.SQL(privilege) for privilege in privileges
                    ),
                    sql.Identifier("public"),
                    sql.Identifier(table),
                    sql.Identifier(role),
                )
            )

    def _prepare_legacy_state(self, database_url):
        migration_paths = sorted(schema_roles.MIGRATION_DIR.glob("*.sql"))[:8]
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            conn.execute(
                "CREATE ROLE noteai_admin NOLOGIN "
                "NOSUPERUSER NOCREATEDB CREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            conn.execute(
                "CREATE ROLE noteai_app LOGIN "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "INHERIT NOREPLICATION NOBYPASSRLS"
            )
            conn.execute(
                "CREATE ROLE noteai_xhs LOGIN "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                    "CREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(TASK_EXECUTOR_ROLE))
            )
            conn.execute(
                sql.SQL(
                    "GRANT noteai_admin TO {} "
                    "WITH INHERIT FALSE, SET TRUE"
                ).format(sql.Identifier(TASK_EXECUTOR_ROLE))
            )
            conn.execute(
                "GRANT noteai_xhs TO noteai_admin "
                "WITH ADMIN OPTION, INHERIT FALSE, SET FALSE"
            )
            database_name = conn.execute(
                "SELECT current_database() AS name"
            ).fetchone()["name"]
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO noteai_admin").format(
                    sql.Identifier(database_name)
                )
            )
            conn.execute("SET ROLE noteai_admin")
            conn.execute(
                "CREATE TABLE schema_migrations("
                "version TEXT PRIMARY KEY,"
                "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            for path in migration_paths:
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES(%s)",
                    (path.name,),
                )
            for role in ("noteai_app", "noteai_xhs"):
                conn.execute(
                    sql.SQL(
                        "REVOKE CREATE, TEMPORARY ON DATABASE {} FROM {}"
                    ).format(
                        sql.Identifier(database_name),
                        sql.Identifier(role),
                    )
                )
                conn.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database_name),
                        sql.Identifier(role),
                    )
                )
                conn.execute(
                    sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(
                        sql.Identifier(role)
                    )
                )
                conn.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.Identifier(role)
                    )
                )
            conn.execute(
                sql.SQL(
                    "REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC"
                ).format(sql.Identifier(database_name))
            )
            self._grant_table_matrix(
                conn,
                "noteai_app",
                preflight.APP_TABLE_PRIVILEGES,
            )
            self._grant_table_matrix(
                conn,
                "noteai_xhs",
                preflight.XHS_TABLE_PRIVILEGES,
            )
            for role, sequences in (
                ("noteai_app", preflight.EXPECTED_PUBLIC_SEQUENCES),
                (
                    "noteai_xhs",
                    (
                        "crawler_events_id_seq",
                        "hot_keywords_id_seq",
                        "keyword_snapshots_id_seq",
                    ),
                ),
            ):
                for sequence in sequences:
                    conn.execute(
                        sql.SQL(
                            "GRANT USAGE ON SEQUENCE {}.{} TO {}"
                        ).format(
                            sql.Identifier("public"),
                            sql.Identifier(sequence),
                            sql.Identifier(role),
                        )
                    )
            conn.execute("RESET ROLE")

    def _connect_as_task_executor(self, database_url):
        conn = psycopg.connect(
            database_url,
            row_factory=dict_row,
            autocommit=True,
        )
        conn.execute(
            sql.SQL("SET SESSION AUTHORIZATION {}").format(
                sql.Identifier(TASK_EXECUTOR_ROLE)
            )
        )
        conn.autocommit = False
        return conn

    def _drop_task_executor(self, database_url):
        with psycopg.connect(
            database_url,
            row_factory=dict_row,
        ) as conn:
            owned = conn.execute(
                "SELECT ("
                "(SELECT COUNT(*) FROM pg_class object "
                "JOIN pg_namespace namespace "
                "ON namespace.oid=object.relnamespace "
                "WHERE namespace.nspname='public' "
                "AND object.relowner=%s::regrole) + "
                "(SELECT COUNT(*) FROM pg_proc object "
                "JOIN pg_namespace namespace "
                "ON namespace.oid=object.pronamespace "
                "WHERE namespace.nspname='public' "
                "AND object.proowner=%s::regrole)) AS count",
                (TASK_EXECUTOR_ROLE, TASK_EXECUTOR_ROLE),
            ).fetchone()["count"]
            self.assertEqual(int(owned), 0)
            conn.execute(
                sql.SQL("DROP ROLE {}").format(
                    sql.Identifier(TASK_EXECUTOR_ROLE)
                )
            )
            self.assertFalse(conn.execute(
                "SELECT EXISTS("
                "SELECT 1 FROM pg_roles WHERE rolname=%s)",
                (TASK_EXECUTOR_ROLE,),
            ).fetchone()["exists"])

    def _assert_mutation_rejected(
        self,
        database_url,
        *,
        apply_sql,
        cleanup_sql,
        outcome_check=False,
    ):
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            conn.execute(apply_sql)
        try:
            with psycopg.connect(
                database_url,
                row_factory=dict_row,
                options="-c default_transaction_read_only=on",
            ) as audit_conn:
                if outcome_check:
                    outcome = outcome_audit.collect_outcome(audit_conn)
                    self.assertEqual(
                        outcome["database_outcome"],
                        "CONFLICT",
                    )
                    self.assertFalse(
                        outcome["observation"][
                            "full_contract_matrix_verified"
                        ]
                    )
                else:
                    with self.assertRaises(schema_roles.SchemaRoleError):
                        schema_roles.verify_contract(audit_conn)
        finally:
            with psycopg.connect(
                database_url,
                row_factory=dict_row,
            ) as conn:
                conn.execute(cleanup_sql)

    def test_000_privileged_owner_equivalent_chain_is_read_only(self):
        base_url = os.environ[LOCAL_DSN_ENV]
        database_name = "noteai_privileged_owner_preflight_005_test"
        managed_role = "noteai_local_rds_privileged"
        original_executor = globals()["TASK_EXECUTOR_ROLE"]
        original_managed_role = privileged_owner.MANAGED_PRIVILEGED_ROLE
        settings = psycopg.conninfo.conninfo_to_dict(base_url)
        settings["dbname"] = database_name
        database_url = psycopg.conninfo.make_conninfo(**settings)
        try:
            with psycopg.connect(base_url, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(database_name)
                    )
                )
            globals()["TASK_EXECUTOR_ROLE"] = (
                privileged_owner.TASK_ACCOUNT_NAME
            )
            privileged_owner.MANAGED_PRIVILEGED_ROLE = managed_role
            self._prepare_legacy_state(database_url)
            with psycopg.connect(database_url) as conn:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(managed_role))
                )
                conn.execute(
                    sql.SQL(
                        "GRANT noteai_admin TO {} "
                        "WITH INHERIT FALSE, SET TRUE"
                    ).format(sql.Identifier(managed_role))
                )
                conn.execute(
                    sql.SQL(
                        "GRANT {} TO {} WITH INHERIT FALSE, SET TRUE"
                    ).format(
                        sql.Identifier(managed_role),
                        sql.Identifier(
                            privileged_owner.TASK_ACCOUNT_NAME
                        ),
                    )
                )
                conn.execute(
                    sql.SQL("REVOKE noteai_admin FROM {}").format(
                        sql.Identifier(
                            privileged_owner.TASK_ACCOUNT_NAME
                        )
                    )
                )

            audit_conn = privileged_owner._connect(database_url)
            try:
                audit_conn.execute(
                    sql.SQL("SET SESSION AUTHORIZATION {}").format(
                        sql.Identifier(
                            privileged_owner.TASK_ACCOUNT_NAME
                        )
                    )
                )
                result = (
                    privileged_owner.collect_privileged_owner_authority(
                        audit_conn
                    )
                )
            finally:
                audit_conn.close()

            self.assertEqual(
                result["status"],
                "privileged_owner_authority_verified",
            )
            self.assertEqual(result["database_write_count"], 0)
            self.assertTrue(result["transaction_rolled_back"])
            self.assertEqual(result["acceptance"], {
                "session": True,
                "owner_contract": True,
                "production_state": True,
            })
            self.assertEqual(
                result["session"][
                    "direct_managed_privileged_membership_count"
                ],
                1,
            )
            self.assertEqual(
                result["session"]["unexpected_direct_membership_count"],
                0,
            )
            self.assertEqual(
                result["session"]["direct_owner_membership_count"],
                0,
            )
            self.assertEqual(
                result["session"]["unexpected_runtime_membership_count"],
                0,
            )
            self.assertEqual(
                result["session"]["executor_shared_dependency_count"],
                0,
            )
        finally:
            privileged_owner.MANAGED_PRIVILEGED_ROLE = original_managed_role
            globals()["TASK_EXECUTOR_ROLE"] = original_executor
            with psycopg.connect(base_url, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
                for role in (
                    privileged_owner.TASK_ACCOUNT_NAME,
                    managed_role,
                    "noteai_xhs",
                    "noteai_app",
                    "noteai_admin",
                ):
                    conn.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(role)
                        )
                    )

    def test_001_item26_owner_gate_is_exact_on_postgresql16(self):
        base_url = os.environ[LOCAL_DSN_ENV]
        contract = _load_item26_owner_gate()
        account = contract["ACCOUNT"]
        owner = contract["OWNER"]
        tables = tuple(contract["TABLES"])
        rls_tables = tuple(contract["RLS"])
        self.assertEqual(tables, tuple(sorted(schema_roles.EXPECTED_TABLES)))
        migration_rls_tables, migration_force_rls_tables = (
            _expected_rls_tables_from_migrations()
        )
        self.assertEqual(rls_tables, migration_rls_tables)
        self.assertEqual(migration_force_rls_tables, ())
        fixed_error = contract["Fixed"]
        owner_gate = contract["owner_gate"]
        self.assertEqual(contract["MANAGED"], "pg_rds_superuser")
        managed = "noteai_item26_managed_equivalent"
        owner_gate.__globals__["MANAGED"] = managed
        database_name = "noteai_item26_owner_gate_pg16_test"
        settings = psycopg.conninfo.conninfo_to_dict(base_url)
        settings["dbname"] = database_name
        database_url = psycopg.conninfo.make_conninfo(**settings)
        migrations = [
            {
                "version": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(schema_roles.MIGRATION_DIR.glob("*.sql"))
        ]
        database_created = False
        created_roles = []

        class RecordingConnection:
            def __init__(self, connection):
                self.connection = connection
                self.statements = []

            def execute(self, statement, params=()):
                self.statements.append(" ".join(statement.split()))
                return self.connection.execute(statement, params)

        def connect_as_task():
            connection = psycopg.connect(
                database_url,
                row_factory=dict_row,
                autocommit=True,
                options="-c default_transaction_read_only=on",
            )
            connection.execute(
                sql.SQL("SET SESSION AUTHORIZATION {}").format(
                    sql.Identifier(account)
                )
            )
            return connection

        def run_positive():
            connection = connect_as_task()
            try:
                connection.execute(
                    "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                self.assertEqual(
                    connection.info.transaction_status.name,
                    "INTRANS",
                )
                owner_gate(connection, migrations)
                row = connection.execute(
                    "SELECT COUNT(*)::integer AS count "
                    "FROM admin_sessions"
                ).fetchone()
                self.assertEqual(row["count"], 1)
                connection.rollback()
                self.assertEqual(
                    connection.info.transaction_status.name,
                    "IDLE",
                )
                identity = connection.execute(
                    "SELECT session_user=current_user AS restored,"
                    "current_setting('row_security')='on' AS rls_restored"
                ).fetchone()
                self.assertEqual(identity, {
                    "restored": True,
                    "rls_restored": True,
                })
            finally:
                connection.close()

        def run_negative():
            connection = connect_as_task()
            recorder = RecordingConnection(connection)
            try:
                connection.execute(
                    "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                with self.assertRaises(fixed_error):
                    owner_gate(recorder, migrations)
                connection.rollback()
                self.assertEqual(
                    connection.info.transaction_status.name,
                    "IDLE",
                )
                identity = connection.execute(
                    "SELECT session_user=current_user AS restored,"
                    "current_setting('row_security')='on' AS rls_restored"
                ).fetchone()
                self.assertEqual(identity, {
                    "restored": True,
                    "rls_restored": True,
                })
                business_reads = [
                    statement
                    for statement in recorder.statements
                    if 'FROM "' in statement
                ]
                self.assertEqual(business_reads, [])
            finally:
                connection.close()

        try:
            with psycopg.connect(base_url, autocommit=True) as connection:
                existing = connection.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)",
                    ([account, managed, owner],),
                ).fetchall()
                self.assertEqual(existing, [])
                database_exists = connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)",
                    (database_name,),
                ).fetchone()[0]
                self.assertFalse(database_exists)
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(owner))
                )
                created_roles.append(owner)
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(managed))
                )
                created_roles.append(managed)
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(account))
                )
                created_roles.append(account)
                connection.execute(
                    sql.SQL(
                        "GRANT {} TO {} WITH INHERIT FALSE, SET TRUE"
                    ).format(sql.Identifier(owner), sql.Identifier(managed))
                )
                connection.execute(
                    sql.SQL(
                        "GRANT {} TO {} WITH INHERIT FALSE, SET TRUE"
                    ).format(sql.Identifier(managed), sql.Identifier(account))
                )
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(database_name)
                    )
                )
                database_created = True
            with psycopg.connect(database_url) as connection:
                for table in tables:
                    if table == "schema_migrations":
                        connection.execute(
                            "CREATE TABLE schema_migrations("
                            "version text PRIMARY KEY,sha256 text NOT NULL)"
                        )
                    else:
                        connection.execute(
                            sql.SQL(
                                "CREATE TABLE {}(id bigint PRIMARY KEY)"
                            ).format(sql.Identifier(table))
                        )
                    connection.execute(
                        sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                            sql.Identifier(table),
                            sql.Identifier(owner),
                        )
                    )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO schema_migrations(version,sha256) "
                        "VALUES(%s,%s)",
                        [
                            (row["version"], row["sha256"])
                            for row in migrations
                        ],
                    )
                connection.execute("INSERT INTO admin_sessions(id) VALUES(1)")
                for table in rls_tables:
                    connection.execute(
                        sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                            sql.Identifier(table)
                        )
                    )

            run_positive()

            mutations = (
                (
                    ("CREATE TABLE item26_extra_table(id bigint)",
                     f"ALTER TABLE item26_extra_table OWNER TO {owner}"),
                    ("DROP TABLE item26_extra_table",),
                ),
                (
                    ("ALTER TABLE users RENAME TO item26_users_missing",),
                    ("ALTER TABLE item26_users_missing RENAME TO users",),
                ),
                (
                    ("ALTER TABLE account_deletion_requests OWNER TO postgres",),
                    (f"ALTER TABLE account_deletion_requests OWNER TO {owner}",),
                ),
                (
                    ("ALTER TABLE admin_sessions DISABLE ROW LEVEL SECURITY",),
                    ("ALTER TABLE admin_sessions ENABLE ROW LEVEL SECURITY",),
                ),
                (
                    ("ALTER TABLE account_deletion_requests ENABLE ROW LEVEL SECURITY",),
                    ("ALTER TABLE account_deletion_requests DISABLE ROW LEVEL SECURITY",),
                ),
                (
                    ("ALTER TABLE admin_sessions FORCE ROW LEVEL SECURITY",),
                    ("ALTER TABLE admin_sessions NO FORCE ROW LEVEL SECURITY",),
                ),
                (
                    (f"REVOKE {managed} FROM {account}",),
                    (f"GRANT {managed} TO {account} WITH INHERIT FALSE, SET TRUE",),
                ),
                (
                    (f"REVOKE {owner} FROM {managed}",),
                    (f"GRANT {owner} TO {managed} WITH INHERIT FALSE, SET TRUE",),
                ),
                (
                    ("UPDATE schema_migrations SET sha256=repeat('0',64) "
                     "WHERE version=(SELECT MIN(version) FROM schema_migrations)",),
                    (
                        "UPDATE schema_migrations SET sha256='{}' "
                        "WHERE version='{}'".format(
                            migrations[0]["sha256"],
                            migrations[0]["version"],
                        ),
                    ),
                ),
            )
            for apply_statements, restore_statements in mutations:
                with self.subTest(mutation=apply_statements[0]):
                    with psycopg.connect(database_url) as connection:
                        for statement in apply_statements:
                            connection.execute(statement)
                    try:
                        run_negative()
                    finally:
                        with psycopg.connect(database_url) as connection:
                            for statement in restore_statements:
                                connection.execute(statement)
                    run_positive()
        finally:
            with psycopg.connect(base_url, autocommit=True) as connection:
                if database_created:
                    connection.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(database_name)
                        )
                    )
                for role in reversed(created_roles):
                    connection.execute(
                        sql.SQL("DROP ROLE {}").format(
                            sql.Identifier(role)
                        )
                    )

    def test_fixed_read_audit_then_exact_apply_and_apply_twice(self):
        database_url = os.environ[LOCAL_DSN_ENV]
        canonical_migration_dir = schema_roles.MIGRATION_DIR
        canonical_outcome_migration_dir = outcome_audit.MIGRATION_DIR
        legacy_migration_root = tempfile.TemporaryDirectory(
            prefix="noteai-schema-roles-0016-"
        )
        self.addCleanup(legacy_migration_root.cleanup)
        self.addCleanup(
            setattr,
            schema_roles,
            "MIGRATION_DIR",
            canonical_migration_dir,
        )
        self.addCleanup(
            setattr,
            outcome_audit,
            "MIGRATION_DIR",
            canonical_outcome_migration_dir,
        )
        legacy_migration_dir = pathlib.Path(legacy_migration_root.name)
        for path in sorted(canonical_migration_dir.glob("*.sql"))[:16]:
            (legacy_migration_dir / path.name).write_bytes(path.read_bytes())
        schema_roles.MIGRATION_DIR = legacy_migration_dir
        outcome_audit.MIGRATION_DIR = legacy_migration_dir
        self._prepare_legacy_state(database_url)

        authority_conn = owner_preflight._connect(database_url)
        try:
            authority_conn.execute(
                sql.SQL("SET SESSION AUTHORIZATION {}").format(
                    sql.Identifier(TASK_EXECUTOR_ROLE)
                )
            )
            authority = owner_preflight.collect_owner_authority(
                authority_conn
            )
        finally:
            authority_conn.close()
        self.assertEqual(
            authority["status"],
            "owner_authority_verified",
        )
        self.assertFalse(authority["session"]["executor_is_owner"])
        self.assertTrue(
            authority["session"]["owner_activation_capable"]
        )
        self.assertEqual(
            authority["session"]["direct_owner_set_membership_count"],
            1,
        )
        self.assertEqual(
            authority["session"]["transient_executor_dependency_count"],
            0,
        )
        self.assertEqual(
            authority["owner_contract"]["owner_mismatch_count"],
            0,
        )
        self.assertEqual(
            authority["production_state"]["task_role_residue_count"],
            0,
        )

        audit_conn = set_audit._connect(database_url)
        try:
            prewrite = set_audit.collect_role_risk_set(audit_conn)
        finally:
            audit_conn.close()
        self.assertEqual(prewrite["status"], "accepted_risk_observed")
        self.assertEqual(prewrite["stage_order"], list(set_audit.STAGE_ORDER))
        self.assertEqual(
            prewrite["ledger_inventory"]["retention_backfill_source_count"],
            0,
        )

        with self._connect_as_task_executor(database_url) as apply_conn:
            first = schema_roles.apply_contract(apply_conn)
        self.assertEqual(first["status"], "verified")
        self.assertEqual(first["applied_versions"], list(
            schema_roles.NEW_VERSIONS
        ))
        self.assertEqual(first["database_writes"], {
            "migration_ledger_rows": 8,
            "migration_ledger_hash_backfills": 8,
            "schema_seed_rows": 2,
            "retention_backfill_rows": 0,
            "existing_business_row_updates": 0,
        })
        self.assertEqual(first["verification"]["table_grant_option_count"], 0)
        self.assertEqual(first["verification"]["column_grant_option_count"], 0)
        self.assertEqual(
            first["verification"]["sequence_grant_option_count"],
            0,
        )
        self.assertEqual(first["verification"]["default_acl_entry_count"], 0)
        self.assertEqual(first["roles"]["membership_count"], 7)
        self.assertEqual(
            first["roles"]["management_membership_count"],
            6,
        )
        self.assertEqual(
            first["roles"]["migration_owner_mismatch_count"],
            0,
        )
        self.assertEqual(first["roles"]["executor_owned_object_count"], 0)

        with self._connect_as_task_executor(database_url) as apply_conn:
            second = schema_roles.apply_contract(apply_conn)
        self.assertEqual(second["applied_versions"], [])
        self.assertEqual(second["database_writes"], {
            "migration_ledger_rows": 0,
            "migration_ledger_hash_backfills": 0,
            "schema_seed_rows": 0,
            "retention_backfill_rows": 0,
            "existing_business_row_updates": 0,
        })
        self.assertEqual(second["roles"]["executor_owned_object_count"], 0)
        self._drop_task_executor(database_url)

        with psycopg.connect(
            database_url,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        ) as audit_conn:
            outcome = outcome_audit.collect_outcome(audit_conn)
        self.assertEqual(outcome["database_outcome"], "COMMITTED")
        self.assertEqual(outcome["observation"]["ledger_count"], 16)
        self.assertEqual(
            outcome["observation"]["matching_migration_hash_count"],
            16,
        )
        self.assertEqual(outcome["observation"]["retention_row_count"], 0)

        mutations = (
            (
                "GRANT SELECT ON schema_migrations "
                "TO noteai_xhs WITH GRANT OPTION",
                "REVOKE SELECT ON schema_migrations FROM noteai_xhs",
                True,
            ),
            (
                "GRANT SELECT(id) ON users TO noteai_xhs",
                "REVOKE SELECT(id) ON users FROM noteai_xhs",
                False,
            ),
            (
                "GRANT UPDATE ON SEQUENCE analysis_log_id_seq "
                "TO noteai_xhs",
                "REVOKE UPDATE ON SEQUENCE analysis_log_id_seq "
                "FROM noteai_xhs",
                False,
            ),
            (
                "GRANT EXECUTE ON FUNCTION "
                "noteai_retained_primary_insert_guard_h20() "
                "TO noteai_xhs",
                "REVOKE EXECUTE ON FUNCTION "
                "noteai_retained_primary_insert_guard_h20() "
                "FROM noteai_xhs",
                False,
            ),
            (
                "ALTER DEFAULT PRIVILEGES "
                "GRANT SELECT ON TABLES TO noteai_xhs",
                "ALTER DEFAULT PRIVILEGES "
                "REVOKE SELECT ON TABLES FROM noteai_xhs",
                False,
            ),
            (
                "GRANT noteai_app TO noteai_xhs WITH SET FALSE",
                "REVOKE noteai_app FROM noteai_xhs",
                False,
            ),
        )
        for apply_sql, cleanup_sql, outcome_check in mutations:
            with self.subTest(apply_sql=apply_sql):
                self._assert_mutation_rejected(
                    database_url,
                    apply_sql=apply_sql,
                    cleanup_sql=cleanup_sql,
                    outcome_check=outcome_check,
                )

        with psycopg.connect(
            database_url,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        ) as audit_conn:
            final = outcome_audit.collect_outcome(audit_conn)
        self.assertEqual(final["database_outcome"], "COMMITTED")
        self.assertTrue(
            final["observation"]["full_contract_matrix_verified"]
        )

    def test_pg16_non_super_creator_gets_implicit_admin_membership(self):
        database_url = os.environ[LOCAL_DSN_ENV]
        creator = "noteai_acl_probe_creator"
        runtime = "noteai_acl_probe_runtime"
        with psycopg.connect(
            database_url,
            row_factory=dict_row,
        ) as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                    "CREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(creator))
            )
            conn.execute(
                sql.SQL("SET SESSION AUTHORIZATION {}").format(
                    sql.Identifier(creator)
                )
            )
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(runtime))
            )
            conn.execute("RESET SESSION AUTHORIZATION")
            edge = conn.execute(
                "SELECT membership.admin_option,"
                "(to_jsonb(membership)->>'inherit_option')::boolean "
                "AS inherit_option,"
                "(to_jsonb(membership)->>'set_option')::boolean "
                "AS set_option,grantor.rolname AS grantor_name "
                "FROM pg_auth_members membership "
                "JOIN pg_roles granted ON granted.oid=membership.roleid "
                "JOIN pg_roles member ON member.oid=membership.member "
                "JOIN pg_roles grantor ON grantor.oid=membership.grantor "
                "WHERE granted.rolname=%s AND member.rolname=%s",
                (runtime, creator),
            ).fetchone()
            self.assertIsNotNone(edge)
            self.assertTrue(edge["admin_option"])
            self.assertFalse(edge["inherit_option"])
            self.assertFalse(edge["set_option"])
            self.assertEqual(edge["grantor_name"], "postgres")

            conn.execute(
                sql.SQL("SET SESSION AUTHORIZATION {}").format(
                    sql.Identifier(creator)
                )
            )
            conn.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(runtime),
                    sql.Identifier(creator),
                )
            )
            conn.execute("RESET SESSION AUTHORIZATION")
            self.assertEqual(int(conn.execute(
                "SELECT COUNT(*) FROM pg_auth_members membership "
                "JOIN pg_roles granted ON granted.oid=membership.roleid "
                "JOIN pg_roles member ON member.oid=membership.member "
                "WHERE granted.rolname=%s AND member.rolname=%s",
                (runtime, creator),
            ).fetchone()["count"]), 1)

            conn.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(creator))
            )
            conn.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(runtime))
            )


if __name__ == "__main__":
    unittest.main()
