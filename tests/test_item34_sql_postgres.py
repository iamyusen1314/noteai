"""Execute the saved 0019 SQL on an isolated PG16 fixture, not production."""

import os
from pathlib import Path
import unittest

import psycopg


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("NOTEAI_LOCAL_PG16_CANARY_TEST") == "1",
                     "explicit isolated PG16 container required")
class Item34SqlPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg.connect(host="/var/run/postgresql", dbname="noteai_local",
                                  user="postgres", autocommit=True)
        version, addr = cls.conn.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr()"
        ).fetchone()
        assert 160000 <= version < 170000 and addr is None
        for role in ("noteai_admin", "noteai_app", "noteai_xhs_tracking"):
            if not cls.conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                cls.conn.execute('CREATE ROLE '+role+' NOLOGIN')

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.conn.execute("RESET ROLE")
        self.conn.execute("DROP TABLE IF EXISTS system_settings,schema_migrations,tracking_provider_attempts")
        self.conn.execute("CREATE TABLE system_settings(key text primary key,value text,is_secret int DEFAULT 0)")
        self.conn.execute("CREATE TABLE schema_migrations(version text primary key,sha256 text,"
                          "applied_at timestamptz DEFAULT now())")
        self.conn.execute("CREATE TABLE tracking_provider_attempts(id text primary key)")
        for table in ("system_settings", "schema_migrations", "tracking_provider_attempts"):
            self.conn.execute('ALTER TABLE '+table+' OWNER TO noteai_admin')
        self.conn.execute("ALTER TABLE system_settings ENABLE ROW LEVEL SECURITY")
        self.conn.execute("GRANT USAGE ON SCHEMA public TO noteai_admin,noteai_app,noteai_xhs_tracking")
        self.conn.execute("GRANT SELECT ON system_settings TO noteai_xhs_tracking")
        # This is the exact attempts grant from the existing runtime ACL.
        acl = (ROOT / "scripts/postgres/noteai_production_runtime_roles.sql").read_text()
        grant = "GRANT SELECT, INSERT\n    ON tracking_provider_attempts TO noteai_xhs_tracking;"
        self.assertIn(grant, acl)
        self.conn.execute(grant)
        self.conn.execute("INSERT INTO system_settings (key,value) VALUES('crawler_config','{}'),('unrelated','{}')")

    def script(self, name):
        rows = []
        with self.conn.cursor() as cur:
            cur.execute((ROOT / ('scripts/postgres/item34-0019-'+name+'.sql')).read_text(), prepare=False)
            while True:
                if cur.description:
                    rows.extend(cur.fetchall())
                if not cur.nextset():
                    break
        return rows

    def test_exact_preflight_apply_verify_and_replay_rejection(self):
        before = self.script('preflight')
        self.assertTrue(all(before[0][1:]))
        self.assertTrue(all(before[1]))
        self.script('apply')
        after = self.script('verify')
        self.assertEqual(after[0][1:], ('noteai_admin', True, True, 1, 1))
        with self.assertRaises(psycopg.Error):
            self.script('apply')
        self.conn.execute('ROLLBACK')
        self.assertEqual(self.script('verify'), after)
        self.conn.execute('SET ROLE noteai_xhs_tracking')
        self.assertEqual(self.conn.execute('SELECT key FROM system_settings').fetchall(),
                         [('crawler_config',)])
        self.conn.execute('RESET ROLE')

    def test_owner_mismatch_fails_without_policy_or_ledger(self):
        self.conn.execute('ALTER TABLE system_settings OWNER TO postgres')
        with self.assertRaises(psycopg.Error):
            self.script('apply')
        self.conn.execute('ROLLBACK')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM schema_migrations').fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM pg_policies WHERE "
                                          "tablename='system_settings'").fetchone()[0], 0)

    def test_0019_does_not_fix_attempts_read_and_temporary_grant_reverts(self):
        self.script('apply')
        self.conn.execute('SET ROLE noteai_app')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.conn.execute('SELECT count(*) FROM tracking_provider_attempts')
        self.conn.execute('RESET ROLE')
        self.conn.execute('SET ROLE noteai_admin')
        self.conn.execute('GRANT SELECT ON public.tracking_provider_attempts TO noteai_app')
        self.conn.execute('RESET ROLE')
        self.conn.execute('SET ROLE noteai_app')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM tracking_provider_attempts').fetchone(), (0,))
        self.conn.execute('RESET ROLE')
        self.conn.execute('SET ROLE noteai_admin')
        self.conn.execute('REVOKE SELECT ON public.tracking_provider_attempts FROM noteai_app')
        self.conn.execute('RESET ROLE')
        self.assertFalse(self.conn.execute("SELECT has_table_privilege('noteai_app',"
                                          "'public.tracking_provider_attempts','SELECT')").fetchone()[0])


if __name__ == '__main__':
    unittest.main()
