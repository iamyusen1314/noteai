"""0031 table/column permissions on an explicitly isolated local PG16 socket."""

import os
from pathlib import Path
import unittest

import psycopg
from psycopg import sql


ENABLED = os.environ.get("NOTEAI_LOCAL_PG16_AMAP_ACL_TEST") == "1"
DATABASE = "noteai_amap_acl_local"
ROOT = Path(__file__).resolve().parents[1]
ROLES = ("noteai_app", "noteai_admin_runtime", "noteai_ai_dispatcher", "noteai_ai_worker",
         "noteai_payment", "noteai_xhs", "noteai_xhs_tracking", "noteai_xhs_trends")
EXTRA_ROLE = "noteai_amap_acl_default_grantee"
TABLES = ("amap_quota_buckets", "amap_quota_attempts")
UPDATES = {
    "amap_quota_buckets": {"admitted_count", "account_block_code", "account_block_until",
                           "text_block_code", "text_block_until", "detail_block_code", "detail_block_until"},
    "amap_quota_attempts": {"status", "http_status", "business_code", "completed_at"},
}
INSERTS = {"amap_quota_buckets": set(), "amap_quota_attempts":
           {"id", "account_scope", "service_group", "period", "endpoint", "admitted_at", "status"}}


@unittest.skipUnless(ENABLED, "explicit disposable network-none PG16 socket required")
class AmapQuotaAclTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = psycopg.connect(host="/var/run/postgresql", dbname=DATABASE, user="postgres", autocommit=True)
        version, address, database = cls.owner.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr(),current_database()"
        ).fetchone()
        if not (160000 <= version < 170000 and address is None and database == DATABASE):
            cls.owner.close()
            raise AssertionError("explicit local PG16 ACL fixture required")
        for role in (*ROLES, EXTRA_ROLE):
            cls.owner.execute(sql.SQL("DO $roles$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname={name}) "
                "THEN CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; END IF; END $roles$").format(
                    name=sql.Literal(role), role=sql.Identifier(role)))

    @classmethod
    def tearDownClass(cls):
        cls.owner.close()

    def setUp(self):
        self.owner.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        self.owner.execute("CREATE TABLE public.amap_acl_existing_table(id integer)")
        self.owner.execute("GRANT SELECT ON public.amap_acl_existing_table TO noteai_xhs")

    def install(self):
        with self.owner.transaction():
            self.owner.execute((ROOT / "model/migrations/postgres/0031_amap_shared_quota.sql").read_text())

    def assert_exact_matrix(self):
        for table in TABLES:
            columns = [row[0] for row in self.owner.execute(
                "SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped",
                ("public." + table,))]
            for role in (*ROLES, EXTRA_ROLE):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    with self.subTest(table=table, role=role, privilege=privilege):
                        expected = privilege == "SELECT" and role in {"noteai_app", "noteai_admin_runtime"}
                        self.assertEqual(self.owner.execute("SELECT has_table_privilege(%s,%s,%s)",
                            (role, "public." + table, privilege)).fetchone()[0], expected)
                        self.assertFalse(self.owner.execute("SELECT has_table_privilege(%s,%s,%s)",
                            (role, "public." + table, privilege + " WITH GRANT OPTION")).fetchone()[0])
                for column in columns:
                    for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                        expected = (privilege == "SELECT" and role in {"noteai_app", "noteai_admin_runtime"}) or (
                            role == "noteai_app" and ((privilege == "UPDATE" and column in UPDATES[table])
                                                     or (privilege == "INSERT" and column in INSERTS[table])))
                        with self.subTest(table=table, role=role, column=column, privilege=privilege):
                            self.assertEqual(self.owner.execute("SELECT has_column_privilege(%s,%s,%s,%s)",
                                (role, "public." + table, column, privilege)).fetchone()[0], expected)
            public_count = self.owner.execute("SELECT count(*) FROM pg_class c CROSS JOIN LATERAL "
                "aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a "
                "WHERE c.oid=%s::regclass AND a.grantee=0", ("public." + table,)).fetchone()[0]
            self.assertEqual(public_count, 0)
            self.assertEqual(self.owner.execute(sql.SQL("SELECT count(*) FROM public.{}").format(
                sql.Identifier(table))).fetchone()[0], 0)

    def test_clean_default_acl_has_exact_api_columns_and_admin_read_only(self):
        self.install()
        self.assert_exact_matrix()

    def test_default_grants_do_not_escape_or_change_existing_objects(self):
        self.owner.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO PUBLIC,{}").format(
            sql.SQL(",").join(sql.Identifier(role) for role in (*ROLES, EXTRA_ROLE))))
        old_acl = self.owner.execute("SELECT relacl::text FROM pg_class WHERE oid='public.amap_acl_existing_table'::regclass").fetchone()[0]
        defaults = self.owner.execute("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid").fetchall()
        self.install()
        self.assert_exact_matrix()
        self.assertEqual(self.owner.execute("SELECT relacl::text FROM pg_class WHERE oid='public.amap_acl_existing_table'::regclass").fetchone()[0], old_acl)
        self.assertEqual(self.owner.execute("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid").fetchall(), defaults)


if __name__ == "__main__":
    unittest.main()
