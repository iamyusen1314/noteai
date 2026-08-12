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
from tools import production_schema_roles as schema_roles


LOCAL_DSN_ENV = "NOTEAI_LOCAL_PG16_SCHEMA_ROLE_DSN"
TASK_EXECUTOR_ROLE = "noteai_schema_task_executor"
ITEM26_TEMPLATE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".codex"
    / "item26-source-manifest.template.sh"
)
ITEM26_EXECUTOR_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".codex"
    / "item26-source-manifest-executor-v3.template.sh"
)
ITEM26_CONTROLLER_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".codex"
    / "item26-source-manifest-executor-v3-controller.template.py"
)
ITEM26_WRAPPER_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".codex"
    / "item26-source-manifest-executor-v3-wrapper.template.sh"
)
ITEM26_READBACK_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".codex"
    / "item26-source-manifest-readback-v3.template.sh"
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

        source_bytes = ITEM26_TEMPLATE_PATH.read_bytes()
        source = source_bytes.decode("ascii")
        source_bindings = {
            "@@ENVELOPE_BYTES@@": "894",
            "@@ENVELOPE_SHA256@@": hashlib.sha256(b"envelope").hexdigest(),
            "@@PUBLIC_KEY_SHA256@@": hashlib.sha256(b"public-key").hexdigest(),
        }
        for token, value in source_bindings.items():
            self.assertEqual(source.count(token), 1)
            source = source.replace(token, value)
        self.assertNotIn("@@", source)
        source_bytes = source.encode("ascii")
        source_gzip = deterministic_gzip(source_bytes)

        executor = ITEM26_EXECUTOR_PATH.read_text(encoding="ascii")
        executor_bindings = {
            "@@TRANSFER_BYTES@@": str(len(source_gzip)),
            "@@TRANSFER_SHA256@@": hashlib.sha256(source_gzip).hexdigest(),
            "@@RAW_BYTES@@": str(len(source_bytes)),
            "@@RAW_SHA256@@": hashlib.sha256(source_bytes).hexdigest(),
        }
        for token, value in executor_bindings.items():
            self.assertEqual(executor.count(token), 1)
            executor = executor.replace(token, value)
        self.assertNotIn("@@", executor)
        executor_bytes = executor.encode("ascii")
        executor_gzip = deterministic_gzip(executor_bytes)

        controller = ITEM26_CONTROLLER_PATH.read_text(encoding="ascii")
        controller_bindings = {
            "@@EXECUTOR_GZIP_BYTES@@": str(len(executor_gzip)),
            "@@EXECUTOR_GZIP_SHA256@@": hashlib.sha256(executor_gzip).hexdigest(),
            "@@EXECUTOR_BYTES@@": str(len(executor_bytes)),
            "@@EXECUTOR_SHA256@@": hashlib.sha256(executor_bytes).hexdigest(),
            "@@EXECUTOR_GZIP_B85@@": base64.b85encode(executor_gzip).decode("ascii"),
        }
        for token, value in controller_bindings.items():
            self.assertEqual(controller.count(token), 1)
            controller = controller.replace(token, value)
        self.assertTrue(all(token not in controller for token in controller_bindings))
        controller_bytes = controller.encode("ascii")
        controller_gzip = deterministic_gzip(controller_bytes)

        wrapper = ITEM26_WRAPPER_PATH.read_text(encoding="ascii")
        wrapper_bindings = {
            "@@CONTROLLER_GZIP_BYTES@@": str(len(controller_gzip)),
            "@@CONTROLLER_GZIP_SHA256@@": hashlib.sha256(controller_gzip).hexdigest(),
            "@@CONTROLLER_BYTES@@": str(len(controller_bytes)),
            "@@CONTROLLER_SHA256@@": hashlib.sha256(controller_bytes).hexdigest(),
            "@@CONTROLLER_GZIP_B85@@": base64.b85encode(controller_gzip).decode("ascii"),
        }
        for token, value in wrapper_bindings.items():
            self.assertEqual(wrapper.count(token), 1)
            wrapper = wrapper.replace(token, value)
        self.assertTrue(all(token not in wrapper for token in wrapper_bindings))
        self.assertLessEqual(len(base64.b64encode(wrapper.encode("ascii"))), 18000)

        for path in (
            ITEM26_EXECUTOR_PATH,
            ITEM26_WRAPPER_PATH,
            ITEM26_READBACK_PATH,
        ):
            syntax = subprocess.run(
                ["/bin/bash", "-n", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr[:2000])

        readback = ITEM26_READBACK_PATH.read_text(encoding="ascii")
        self.assertIn(
            'TRANSFER = "/run/noteai-item26-source-manifest-transfer-v3.sh.gz"',
            readback,
        )
        self.assertEqual(readback.count("manifest_readback_allowed = True"), 2)
        self.assertNotIn("same_invocation_replay_allowed\": True", readback)


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
        legacy_migration_dir = pathlib.Path(legacy_migration_root.name)
        for path in sorted(canonical_migration_dir.glob("*.sql"))[:16]:
            (legacy_migration_dir / path.name).write_bytes(path.read_bytes())
        schema_roles.MIGRATION_DIR = legacy_migration_dir
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
