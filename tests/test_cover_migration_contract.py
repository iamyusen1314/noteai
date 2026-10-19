"""Source-only PG migration checks; these do not replace real role/RLS tests."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / 'model/migrations/features/noteai_xhs_cover_20261019_0001.sql').read_text()
BASE = (ROOT / 'model/migrations/postgres/0024_admin_scoped_operations.sql').read_text()
KEYS = {'noteai_cover_config_v1', 'noteai_cover_config_v1_test'}


class CoverMigrationContractTests(unittest.TestCase):
    def test_ddl_is_atomic_and_replay_does_not_reset_budget_or_costs(self):
        self.assertEqual(len(re.findall(r'^BEGIN;', SQL, re.M)), 1)
        self.assertTrue(SQL.rstrip().endswith('COMMIT;'))
        self.assertEqual(len(re.findall(r'^CREATE TABLE IF NOT EXISTS ', SQL, re.M)), 3)
        self.assertNotRegex(SQL, r'(?i)DELETE FROM|TRUNCATE|UPDATE\s+(public\.)?public_trial_budget')
        self.assertEqual(SQL.count('ON CONFLICT(id) DO NOTHING'), 2)
        self.assertNotRegex(SQL, r'(?m)^ALTER TABLE .*DROP CONSTRAINT (?!IF EXISTS)')

    def test_app_exclusion_preserves_all_baseline_model_prompt_keys(self):
        pattern = r'ALTER POLICY noteai_system_settings_app_v1\b[\s\S]*?;'
        before = re.search(pattern, BASE)[0]
        after = re.search(pattern, SQL)[0]
        for part in ('USING', 'WITH CHECK'):
            old_set = set(re.findall(r"'([^']+)'", before.split(part, 1)[1].split(')', 1)[0]))
            new_set = set(re.findall(r"'([^']+)'", after.split(part, 1)[1].split(')', 1)[0]))
            self.assertEqual(new_set, old_set | KEYS)

    def test_only_nonsecret_exact_cover_keys_are_admin_writable_and_api_readable(self):
        policies = re.findall(r'CREATE POLICY (noteai_cover_config_\w+)\b([\s\S]*?);', SQL)
        self.assertEqual({name for name, _ in policies}, {
            'noteai_cover_config_admin_read', 'noteai_cover_config_admin_insert',
            'noteai_cover_config_admin_update', 'noteai_cover_config_api_read'})
        for name, body in policies:
            self.assertEqual(set(re.findall(r"'([^']+)'", body)) - {'noteai_admin_runtime', 'noteai_app'}, KEYS)
            self.assertIn('is_secret=0', body)
            self.assertNotIn('DELETE', body)
            if name.endswith('api_read'):
                self.assertIn('FOR SELECT TO noteai_app', body)
            else:
                self.assertIn('TO noteai_admin_runtime', body)
        self.assertNotRegex(SQL, r'(?i)GRANT\s+(ALL|DELETE).*system_settings')

    def test_admin_cover_tables_cannot_read_frozen_user_text_or_sources(self):
        job_grants = re.findall(r'GRANT ([^;]+) ON cover_jobs TO noteai_admin_runtime;', SQL)
        self.assertEqual(job_grants, ['SELECT(status)'])
        self.assertNotRegex(SQL, r'GRANT\s+SELECT\s+ON\s+cover_jobs\s+TO\s+noteai_admin_runtime')

