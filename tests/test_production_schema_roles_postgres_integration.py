import os
import unittest

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from tools import collect_production_database_preflight as preflight
from tools import production_first_launch_role_risk_set_audit as set_audit
from tools import production_schema_owner_authority_preflight as owner_preflight
from tools import production_schema_outcome_audit as outcome_audit
from tools import production_schema_roles as schema_roles


LOCAL_DSN_ENV = "NOTEAI_LOCAL_PG16_SCHEMA_ROLE_DSN"
TASK_EXECUTOR_ROLE = "noteai_schema_task_executor"


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

    def test_fixed_read_audit_then_exact_apply_and_apply_twice(self):
        database_url = os.environ[LOCAL_DSN_ENV]
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
