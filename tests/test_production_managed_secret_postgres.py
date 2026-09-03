import os
import unittest

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from tools import production_managed_secret_lifecycle as lifecycle
from tools import production_managed_secret_login_audit as login_audit
from tools import production_managed_secret_roles as managed_roles


LOCAL_DSN_ENV = "NOTEAI_LOCAL_PG16_MANAGED_SECRET_DSN"
DATABASE_NAME = "noteai_managed_secret_test"
PASSWORDS = {
    role: f"{index:02d}" + ("A" * 48)
    for index, role in enumerate(managed_roles.TARGET_LOGIN_ROLES)
}


@unittest.skipUnless(os.environ.get(LOCAL_DSN_ENV), "local PostgreSQL 16 only")
class ProductionManagedSecretPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ[LOCAL_DSN_ENV]
        settings = psycopg.conninfo.conninfo_to_dict(cls.base_url)
        settings["dbname"] = DATABASE_NAME
        cls.database_url = psycopg.conninfo.make_conninfo(**settings)
        with psycopg.connect(cls.base_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(DATABASE_NAME)
                )
            )
            for role in (
                *managed_roles.NEW_RUNTIME_ROLES,
                "noteai_xhs",
                "noteai_app",
                managed_roles.MIGRATION_OWNER_ROLE,
            ):
                conn.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(role)
                    )
                )
            conn.execute(
                "CREATE ROLE noteai_admin NOLOGIN NOSUPERUSER NOCREATEDB "
                "CREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            conn.execute(
                "CREATE ROLE noteai_app LOGIN PASSWORD "
                "'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB' "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "INHERIT NOREPLICATION NOBYPASSRLS"
            )
            conn.execute(
                "CREATE ROLE noteai_xhs LOGIN PASSWORD "
                "'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC' "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            for role in managed_roles.NEW_RUNTIME_ROLES:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role))
                )
                conn.execute(
                    sql.SQL(
                        "GRANT {} TO noteai_admin "
                        "WITH ADMIN OPTION, INHERIT FALSE, SET FALSE"
                    ).format(sql.Identifier(role))
                )
            conn.execute(
                "GRANT noteai_xhs TO noteai_admin "
                "WITH ADMIN OPTION, INHERIT FALSE, SET FALSE"
            )
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER noteai_admin").format(
                    sql.Identifier(DATABASE_NAME)
                )
            )
        with psycopg.connect(cls.database_url) as conn:
            conn.execute("SET ROLE noteai_admin")
            conn.execute(
                "CREATE TABLE schema_migrations("
                "version TEXT PRIMARY KEY,"
                "sha256 TEXT NOT NULL)"
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO schema_migrations(version,sha256) "
                    "VALUES(%s,%s)",
                    managed_roles.EXPECTED_MIGRATIONS,
                )
            conn.execute(
                sql.SQL(
                    "REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC"
                ).format(sql.Identifier(DATABASE_NAME))
            )
            for role in managed_roles.ALL_RUNTIME_ROLES:
                conn.execute(
                    sql.SQL(
                        "REVOKE CREATE, TEMPORARY ON DATABASE {} FROM {}"
                    ).format(
                        sql.Identifier(DATABASE_NAME),
                        sql.Identifier(role),
                    )
                )
                conn.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(DATABASE_NAME),
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

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.base_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(DATABASE_NAME)
                )
            )
            for role in (
                managed_roles.MIGRATION_OWNER_ROLE,
                *managed_roles.NEW_RUNTIME_ROLES,
                "noteai_xhs",
                "noteai_app",
            ):
                conn.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(role)
                    )
                )

    def _role_dsn(self, role, password):
        settings = psycopg.conninfo.conninfo_to_dict(self.database_url)
        settings["user"] = role
        settings["password"] = password
        return psycopg.conninfo.make_conninfo(**settings)

    def test_one_apply_readonly_logins_rotation_and_revocation(self):
        with psycopg.connect(
            self.database_url,
            row_factory=dict_row,
        ) as conn:
            result = managed_roles.apply_contract(conn, PASSWORDS)

        self.assertTrue(result["transaction_committed"])
        self.assertEqual(result["role_attribute_writes"], 5)
        self.assertEqual(result["password_writes"], 5)
        self.assertEqual(result["membership_writes"], 0)
        self.assertEqual(result["acl_writes"], 0)
        self.assertEqual(result["schema_writes"], 0)
        self.assertEqual(result["business_row_writes"], 0)
        self.assertEqual(result["dispatcher_login_enabled"], 0)

        for role, password in PASSWORDS.items():
            with self.subTest(role=role):
                audit = login_audit._audit_connection(
                    {
                        "noteai_admin_runtime": "admin",
                        "noteai_ai_worker": "ai_worker",
                        "noteai_payment": "payment",
                        "noteai_xhs_tracking": "xhs_tracking",
                        "noteai_xhs_trends": "xhs_trends",
                    }[role],
                    self._role_dsn(role, password),
                )
                self.assertEqual(audit["connection_count"], 1)
                self.assertEqual(audit["read_only_transaction_count"], 1)
                self.assertEqual(audit["unexpected_elevation_count"], 0)

        old_password = PASSWORDS["noteai_payment"]
        new_password = "D" * 48
        old_dsn = self._role_dsn("noteai_payment", old_password)
        new_dsn = self._role_dsn("noteai_payment", new_password)
        lifecycle._alter_role(
            self.database_url,
            "noteai_payment",
            password=new_password,
        )
        lifecycle._verify_login(new_dsn, "noteai_payment")
        lifecycle._verify_rejected(old_dsn)
        lifecycle._alter_role(
            self.database_url,
            "noteai_payment",
            password=None,
        )
        lifecycle._verify_rejected(new_dsn)


if __name__ == "__main__":
    unittest.main()
