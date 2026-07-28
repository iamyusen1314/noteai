import os
import unittest

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from tools import collect_production_database_preflight as preflight
from tools import production_first_launch_role_risk_set_audit as set_audit
from tools import production_schema_outcome_audit as outcome_audit
from tools import production_schema_roles as schema_roles


LOCAL_DSN_ENV = "NOTEAI_LOCAL_PG16_SCHEMA_ROLE_DSN"


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
            conn.execute(
                "CREATE ROLE noteai_admin NOLOGIN "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE "
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
                "GRANT noteai_xhs TO noteai_admin WITH ADMIN OPTION"
            )
            conn.execute(
                "GRANT noteai_xhs TO noteai_admin WITH INHERIT FALSE"
            )
            conn.execute(
                "GRANT noteai_xhs TO noteai_admin WITH SET FALSE"
            )
            database_name = conn.execute(
                "SELECT current_database() AS name"
            ).fetchone()["name"]
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

        with psycopg.connect(
            database_url,
            row_factory=dict_row,
        ) as apply_conn:
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

        with psycopg.connect(
            database_url,
            row_factory=dict_row,
        ) as apply_conn:
            second = schema_roles.apply_contract(apply_conn)
        self.assertEqual(second["applied_versions"], [])
        self.assertEqual(second["database_writes"], {
            "migration_ledger_rows": 0,
            "migration_ledger_hash_backfills": 0,
            "schema_seed_rows": 0,
            "retention_backfill_rows": 0,
            "existing_business_row_updates": 0,
        })

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


if __name__ == "__main__":
    unittest.main()
