"""Execute the saved 0019 SQL on an isolated PG16 fixture, not production."""

import asyncio
import base64
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid

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


@unittest.skipUnless(os.environ.get("NOTEAI_LOCAL_PG16_CANARY_TEST") == "1",
                     "explicit isolated PG16 container required")
class ObservationGenerationPostgresTests(unittest.TestCase):
    """Prospective design with real crawler SQL, never a live observation."""

    @classmethod
    def setUpClass(cls):
        with psycopg.connect(host="/var/run/postgresql",dbname="postgres",user="postgres",autocommit=True) as c:
            version, addr = c.execute("SELECT current_setting('server_version_num')::int,inet_server_addr()").fetchone()
            assert 160000 <= version < 170000 and addr is None
            cls.created_roles=[]
            for role in ('noteai_xhs_tracking','noteai_app'):
                if not c.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                    c.execute(psycopg.sql.SQL('CREATE ROLE {} NOLOGIN').format(psycopg.sql.Identifier(role)))
                    cls.created_roles.append(role)

    @classmethod
    def tearDownClass(cls):
        if cls.created_roles:
            with psycopg.connect(host="/var/run/postgresql",dbname="postgres",user="postgres",autocommit=True) as c:
                for role in cls.created_roles:
                    c.execute(psycopg.sql.SQL('DROP ROLE {}').format(psycopg.sql.Identifier(role)))

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.admin = psycopg.connect(host="/var/run/postgresql", dbname="postgres",
                                     user="postgres", autocommit=True)
        version, addr = self.admin.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr()"
        ).fetchone()
        self.assertTrue(160000 <= version < 170000 and addr is None)
        self.database = "noteai_item34_test_" + uuid.uuid4().hex
        self.admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(self.database)))
        self.addCleanup(self.drop_database)
        self.args = dict(host="/var/run/postgresql", dbname=self.database, user="postgres")
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://postgres@/" + self.database + "?host=/var/run/postgresql",
            "PYTHON_DOTENV_DISABLED": "1", "NOTEAI_FACT_SEARCH": "0",
        }, clear=True))
        sys.path.insert(0, str(ROOT / "model")) if str(ROOT / "model") not in sys.path else None
        self.db = importlib.import_module("db")
        self.crawler = importlib.import_module("crawler")
        self.contract = importlib.import_module("tracking_contract")
        # Reproduce the real pre-0020 state, then apply the exact prospective
        # owner SQL below. This temporary migration view never reaches production.
        migrations = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for source in self.db._POSTGRES_MIGRATIONS_DIR.glob('*.sql'):
            if source.name < '0020':
                (migrations/source.name).write_bytes(source.read_bytes())
        with mock.patch.object(self.db,'_POSTGRES_MIGRATIONS_DIR',migrations):
            self.db.apply_postgres_migrations()
        self.owner = psycopg.connect(**self.args, autocommit=True)
        self.addCleanup(self.owner.close)
        self.phase = "history"
        self.role = None
        self.stack.enter_context(mock.patch.object(self.db, "get_conn", self.connect))
        self.track, self.uid, self.failed = (str(uuid.uuid4()) for _ in range(3))
        self.anchor = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
        self.time = self.anchor
        test = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return test.time.astimezone(tz) if tz else test.time.replace(tzinfo=None)

        self.stack.enter_context(mock.patch.object(self.crawler, "datetime", Clock))
        self.owner.execute("CREATE TABLE item34_test_dml(table_name text,row_id text,phase text,operation text)")
        self.owner.execute("""CREATE FUNCTION item34_test_notice() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN INSERT INTO item34_test_dml VALUES(TG_TABLE_NAME,to_jsonb(NEW)->>TG_ARGV[0],
                current_setting('noteai.test_phase',true),TG_OP); RETURN NEW; END $$""")
        self.keys = {"schema_migrations": "version", "tracked_notes": "id",
            "tracking_provider_attempts": "id", "growth_records": "id",
            "user_memories": "id", "crawler_events": "id", "system_settings": "key"}
        for table, key in self.keys.items():
            self.owner.execute(psycopg.sql.SQL("CREATE TRIGGER item34_local_test AFTER INSERT OR UPDATE ON {} "
                "FOR EACH ROW EXECUTE FUNCTION item34_test_notice({})").format(
                    psycopg.sql.Identifier(table), psycopg.sql.Literal(key)))
        self.set_phase("history")
        self.owner.execute("INSERT INTO users(id,username,password_hash,password_salt,created_at) "
                           "VALUES(%s,%s,'synthetic','synthetic','2026-01-01T00:00:00Z')", (self.uid,self.uid))
        self.owner.execute("INSERT INTO tracked_notes(id,user_id,xhs_note_id,xhs_url,submitted_at,status,attempt_count) "
                           "VALUES(%s,%s,'6a7954010000000026034707',"
                           "'https://www.xiaohongshu.com/explore/6a7954010000000026034707',"
                           "'2026-01-01T00:00:00Z','needs_manual',1)", (self.track,self.uid))
        self.owner.execute("INSERT INTO tracking_provider_attempts(id,track_id,user_id,run_id,stage,status,"
                           "admitted_at,completed_at,error_code) VALUES(%s,%s,%s,'synthetic-old','24h','failed',"
                           "'2026-01-02T00:00:00Z','2026-01-02T00:01:00Z','xhsadaptererror')",
                           (self.failed,self.track,self.uid))
        self.owner.execute("INSERT INTO crawler_events(event_json,created_at) VALUES('{}','2026-01-02T00:01:00Z')")
        self.owner.execute("INSERT INTO crawler_events(event_json,created_at) VALUES('{}','2026-01-02T00:01:01Z')")
        self.owner.execute("INSERT INTO system_settings(key,value_json,updated_at) VALUES('crawler_config','{}',%s)",
                           (self.anchor.isoformat(),))
        self.old_attempt = self.row("tracking_provider_attempts",self.failed)
        self.old_track = self.row("tracked_notes",self.track)
        self.history = self.objects("history") | {("schema_migrations","0019_xhs_tracking_runtime_config.sql")}
        self.assertEqual(len(self.history),6)
        self.assertEqual(self.object_counts(self.history), {'schema_migrations':1,'tracked_notes':1,
            'tracking_provider_attempts':1,'crawler_events':2,'system_settings':1})
        # Existing safety config is fixture infrastructure, not a historical
        # Item34 mutation. Match the canonical failed job's per-table objects.
        self.set_phase("fixture")
        self.owner.execute("INSERT INTO system_settings(key,value_json,updated_at) "
                           "VALUES('xhs_collection_safety','{}',%s)",(self.anchor.isoformat(),))
        self.set_phase("proposal")
        self.owner.execute((ROOT / "tests/fixtures/item34-observation-generation.sql").read_text())
        self.owner.execute("SELECT set_config('noteai.item34.expected_database',%s,false)",(self.database,))
        self.owner.execute("SELECT set_config('noteai.item34.expected_owner','postgres',false)")
        candidate = (ROOT / "scripts/postgres/item34-observation-generation-apply.sql").read_text()
        self.owner.execute(candidate, prepare=False)
        payload=candidate.split('-- DDL_PAYLOAD_BEGIN\n',1)[1].split('-- DDL_PAYLOAD_END\n',1)[0]
        self.assertEqual(self.owner.execute("SELECT sha256 FROM schema_migrations WHERE "
            "version='0020_tracking_observation_generation.sql'").fetchone()[0],hashlib.sha256(payload.encode()).hexdigest())
        self.assertEqual(self.owner.execute("SELECT n.nspname,count(*) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid=p.pronamespace WHERE p.proname IN ('noteai_item34_open_observation',"
            "'noteai_item34_observation_owner_guard') GROUP BY n.nspname").fetchall(),[('public',2)])
        self.assertEqual(self.owner.execute("SELECT n.nspname,p.proname,t.tgenabled FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE t.tgrelid='tracked_notes'::regclass AND t.tgname='item34_observation_owner_guard'").fetchall(),
            [('public','noteai_item34_observation_owner_guard','O')])
        acl = (ROOT / "scripts/postgres/noteai_production_runtime_roles.sql").read_text()
        tracking_acl = acl.split("-- NOTEAI-RUNTIME-ACL-STAGE: tracking\n",1)[1].split(
            "-- NOTEAI-RUNTIME-ACL-STAGE: trends",1)[0]
        self.owner.execute(tracking_acl, prepare=False)
        # Test-only measurement must not grant application schema/control rights.
        self.owner.execute('GRANT INSERT ON item34_test_dml TO noteai_xhs_tracking')
        self.set_phase("window")
        self.install_binding()

    def install_binding(self, generation=1, history=None):
        history=history or [self.failed]
        self.binding={'track_id':self.track,'owner_id':self.uid,'generation':generation,
            'observation_started_at':self.anchor.isoformat(),'initial_snapshot':{'likes':4,'saves':2,'comments':2},
            'previous_attempt_id':history[-1],
            'previous_attempt_sha256':self.contract.observation_history_digest(self.row('tracking_provider_attempts',history[-1]))}
        if generation==2:
            self.binding['sealed_attempts']=[{'generation':g,'attempt_id':ident,
                'sha256':self.contract.observation_history_digest(self.row('tracking_provider_attempts',ident))}
                for g,ident in enumerate(history)]
        os.environ.update({'NOTEAI_ITEM34_ACCEPTANCE':'1','NOTEAI_ITEM34_TRACK_ID':self.track,
            'NOTEAI_ITEM34_CHECKPOINT_STAGE':'24h','NOTEAI_ITEM34_OBSERVATION_GENERATION':str(generation),
            'NOTEAI_ITEM34_OBSERVATION_BINDING_B64':base64.b64encode(json.dumps(self.binding).encode()).decode()})

    def drop_database(self):
        self.admin.execute(psycopg.sql.SQL("DROP DATABASE {}").format(psycopg.sql.Identifier(self.database)))
        self.admin.close()

    def connect(self):
        c = psycopg.connect(**self.args, autocommit=True, row_factory=self.db._compat_row_factory)
        c.execute("SELECT set_config('noteai.test_phase',%s,false)", (self.phase,))
        if self.role:c.execute('SET ROLE noteai_xhs_tracking')
        return c

    def set_phase(self, phase):
        self.phase = phase
        self.owner.execute("SELECT set_config('noteai.test_phase',%s,false)", (phase,))

    def row(self, table, key):
        return self.owner.execute(psycopg.sql.SQL("SELECT to_jsonb(t) FROM {} t WHERE id=%s").format(
            psycopg.sql.Identifier(table)), (key,)).fetchone()[0]

    def objects(self, phase):
        return set(self.owner.execute("SELECT DISTINCT table_name,row_id FROM item34_test_dml WHERE phase=%s",
                                      (phase,)).fetchall())

    def object_counts(self, objects):
        return {table:sum(t == table for t,_ in objects) for table,_ in objects}

    def open(self, *, connection=None, failed=None, anchor=None, previous_generation=0):
        return (connection or self.owner).execute(
            "SELECT noteai_item34_open_observation(%s,%s,%s,%s,%s,%s::jsonb)",
            (self.track,self.uid,previous_generation,failed or self.failed,anchor or self.anchor,
             json.dumps({"likes":4,"saves":2,"comments":2}))).fetchone()[0]

    def claim(self, stage="24h", generation=1):
        return self.crawler._claim_due_tracking_notes(1,now=self.time,run_id="synthetic-new",
            target_id=self.track,target_stage=stage,target_generation=generation)

    def assert_history_unchanged(self):
        current = self.row("tracking_provider_attempts",self.failed)
        self.assertEqual({k:current[k] for k in self.old_attempt}, self.old_attempt)
        self.assertEqual(current["observation_generation"],0)
        current_track = self.row("tracked_notes",self.track)
        for key in ("id","user_id","xhs_note_id","xhs_url","submitted_at","published_at"):
            self.assertEqual(current_track[key],self.old_track[key])

    def run_stage(self, stage, *, generation=1, fail=False):
        spider = importlib.import_module("spider_xhs_http")
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"NOTEAI_ITEM34_ACCEPTANCE":"1",
                "NOTEAI_ITEM34_TRACK_ID":self.track,"NOTEAI_ITEM34_CHECKPOINT_STAGE":stage,
                "NOTEAI_ITEM34_OBSERVATION_GENERATION":str(generation)}))
            stack.enter_context(mock.patch.object(spider,"collection_route",return_value="direct"))
            stack.enter_context(mock.patch.object(spider,"collection_route_suspended",return_value=False))
            stack.enter_context(mock.patch.object(self.crawler.xhs_acquisition,"collection_safety_status",
                                                   return_value={"session_blocked":False}))
            fetch = stack.enter_context(mock.patch.object(self.crawler,"_extract_note_data_with_spider_http",
                new=mock.AsyncMock(side_effect=spider.XHSAdapterError('remote_business_error') if fail else None,
                    return_value={"likes":20,"saves":10,"comments":3,"title":"Synthetic note"})))
            stack.enter_context(mock.patch.object(self.crawler,"_random_delay",new=mock.AsyncMock()))
            result = asyncio.run(self.crawler.run_collection_round(limit=1))
            self.assertEqual((result["collected"],result["attempted"],result["failed"]),(0,1,1) if fail else (1,1,0))
            fetch.assert_awaited_once()

    def prepare_generation2(self):
        self.open()
        self.time=self.anchor+timedelta(hours=24)
        self.owner.execute("UPDATE system_settings SET value_json='{}' WHERE key='crawler_config'")
        self.run_stage('24h',fail=True)
        failed=self.owner.execute('SELECT id FROM tracking_provider_attempts WHERE observation_generation=1').fetchone()[0]
        self.sealed={ident:self.row('tracking_provider_attempts',ident) for ident in (self.failed,failed)}
        self.ledger=self.owner.execute('SELECT * FROM schema_migrations ORDER BY version').fetchall()
        self.g1_objects=self.history|self.objects('proposal')|self.objects('window')
        self.assertEqual(len(self.g1_objects),10)
        self.anchor+=timedelta(days=2);self.time=self.anchor
        self.set_phase('generation2')
        self.install_binding(2,[self.failed,failed])
        self.assertEqual(self.open(failed=failed,previous_generation=1),2)

    def test_generation2_preserves_both_failed_generations_and_has_eight_new_objects(self):
        self.prepare_generation2()
        self.role='noteai_xhs_tracking'
        self.owner.execute("UPDATE system_settings SET value_json='{}' WHERE key='crawler_config'")
        self.time=self.anchor+timedelta(hours=24);self.run_stage('24h',generation=2)
        self.time=self.anchor+timedelta(hours=72);self.run_stage('3d',generation=2)
        self.assertEqual(self.row('tracked_notes',self.track)['status'],'complete')
        self.assertEqual(self.claim('3d',generation=2),[])
        self.assertEqual(self.claim('24h',generation=1),[])
        current=self.objects('generation2')
        self.assertEqual(self.object_counts(current),{'tracked_notes':1,'tracking_provider_attempts':2,
            'crawler_events':2,'system_settings':1,'growth_records':1,'user_memories':1})
        self.assertEqual(len(current),8)
        self.assertEqual(len(self.g1_objects|current),16)
        self.assertEqual(self.owner.execute('SELECT * FROM schema_migrations ORDER BY version').fetchall(),self.ledger)
        for ident,row in self.sealed.items():self.assertEqual(self.row('tracking_provider_attempts',ident),row)

    def test_generation2_checks_each_history_before_claim_and_again_before_admission(self):
        self.prepare_generation2();self.time=self.anchor+timedelta(hours=24)
        for ident,row in self.sealed.items():
            self.owner.execute("UPDATE tracking_provider_attempts SET error_code='changed' WHERE id=%s",(ident,))
            with self.assertRaisesRegex(ValueError,'history'):self.claim(generation=2)
            self.assertIsNone(self.row('tracked_notes',self.track)['claim_token'])
            self.owner.execute('UPDATE tracking_provider_attempts SET error_code=%s WHERE id=%s',(row['error_code'],ident))
            claimed=self.claim(generation=2)[0]
            self.owner.execute("UPDATE tracking_provider_attempts SET error_code='changed' WHERE id=%s",(ident,))
            with self.assertRaisesRegex(ValueError,'history'):self.crawler._admit_provider_attempt(claimed)
            self.assertIsNone(self.row('tracked_notes',self.track)['active_attempt_id'])
            self.owner.execute('UPDATE tracking_provider_attempts SET error_code=%s WHERE id=%s',(row['error_code'],ident))
            self.crawler._release_unstarted_claim(claimed)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM tracking_provider_attempts').fetchone()[0],2)

    def test_generation2_locks_both_sealed_attempts_through_claim_and_admission(self):
        self.prepare_generation2();self.time=self.anchor+timedelta(hours=24)
        original=self.contract.assert_observation_history
        checks=[]
        def verify_locked(rows,binding):
            result=original(rows,binding)
            with psycopg.connect(**self.args,autocommit=True) as other:
                for ident in self.sealed:
                    with self.assertRaises(psycopg.errors.LockNotAvailable),other.transaction():
                        other.execute("SET LOCAL lock_timeout='60ms'")
                        other.execute("UPDATE tracking_provider_attempts SET error_code='must_block' WHERE id=%s",(ident,))
            checks.append(True)
            return result
        with mock.patch.object(self.contract,'assert_observation_history',side_effect=verify_locked):
            claimed=self.claim(generation=2)[0]
            admitted=self.crawler._admit_provider_attempt(claimed)
        self.assertEqual(checks,[True,True])
        self.crawler._record_tracking_failure(admitted,'synthetic','synthetic')
        for ident,row in self.sealed.items():self.assertEqual(self.row('tracking_provider_attempts',ident),row)

    def test_cas_preserves_failed_history_and_refuses_replay_wrong_identity_or_future_t0(self):
        for kwargs in ({"failed":str(uuid.uuid4())},{"anchor":datetime.now(timezone.utc)+timedelta(days=1)}):
            with self.assertRaises(psycopg.Error): self.open(**kwargs)
        self.assertEqual(self.open(),1)
        with self.assertRaises(psycopg.Error): self.open()
        self.assert_history_unchanged()
        self.assertEqual(self.row("tracked_notes",self.track)["observation_initial_snapshot"],
                         {"likes":4,"saves":2,"comments":2})

    def test_manual_apply_is_native_migration_compatible_and_no_replay(self):
        self.assertEqual(self.db.apply_postgres_migrations(),[])
        candidate=(ROOT/'scripts/postgres/item34-observation-generation-apply.sql').read_text()
        with self.assertRaisesRegex(psycopg.errors.RaiseException,'migration history'):
            self.owner.execute(candidate,prepare=False)
        self.owner.execute('ROLLBACK')
        self.assertEqual(self.row('tracked_notes',self.track)['observation_generation'],0)
        for name in ('preflight','verify'):
            result_sets=[]
            with self.owner.cursor() as cursor:
                cursor.execute((ROOT/f'scripts/postgres/item34-observation-generation-{name}.sql').read_text(),prepare=False)
                while True:
                    if cursor.description:result_sets.append(cursor.fetchall())
                    if not cursor.nextset():break
            if name == 'verify':
                self.assertEqual(result_sets[0][0][2:],(1,2,1))
                self.assertEqual(result_sets[1],[
                    ('tracked_notes','observation_generation','integer',True,'0'),
                    ('tracked_notes','observation_initial_snapshot','jsonb',False,None),
                    ('tracked_notes','observation_started_at','text',False,None),
                    ('tracking_provider_attempts','observation_generation','integer',True,'0')])
                self.assertEqual(result_sets[2][0][2:],('public','noteai_item34_observation_owner_guard','O'))
                self.assertEqual(len(result_sets[3]),4)
                self.assertEqual(len(result_sets[4]),2)
                self.assertTrue(all(row[2] is False and row[-1] is False for row in result_sets[4]))
        with tempfile.TemporaryDirectory() as directory:
            missing=Path(directory)
            for source in self.db._POSTGRES_MIGRATIONS_DIR.glob('*.sql'):
                if source.name < '0020':(missing/source.name).write_bytes(source.read_bytes())
            with mock.patch.object(self.db,'_POSTGRES_MIGRATIONS_DIR',missing):
                with self.assertRaisesRegex(RuntimeError,'migration missing locally'):
                    self.db.apply_postgres_migrations()
            (missing/'0020_tracking_observation_generation.sql').write_text('-- wrong local bytes\n')
            with mock.patch.object(self.db,'_POSTGRES_MIGRATIONS_DIR',missing):
                with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):
                    self.db.apply_postgres_migrations()

    def test_candidate_wrong_binding_and_mid_ddl_failure_leave_schema_and_ledger_unchanged(self):
        database='noteai_item34_test_'+uuid.uuid4().hex
        role='noteai_item34_owner_'+uuid.uuid4().hex[:16]
        self.admin.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(database)))
        self.admin.execute(psycopg.sql.SQL('CREATE ROLE {} NOLOGIN').format(psycopg.sql.Identifier(role)))
        try:
            with tempfile.TemporaryDirectory() as directory:
                prior=Path(directory)
                for source in self.db._POSTGRES_MIGRATIONS_DIR.glob('*.sql'):
                    if source.name < '0020':(prior/source.name).write_bytes(source.read_bytes())
                with mock.patch.dict(os.environ,{'DATABASE_URL':f'postgresql://postgres@/{database}?host=/var/run/postgresql'}), \
                     mock.patch.object(self.db,'_POSTGRES_MIGRATIONS_DIR',prior):
                    self.db.apply_postgres_migrations()
            candidate=(ROOT/'scripts/postgres/item34-observation-generation-apply.sql').read_text()
            with psycopg.connect(**{**self.args,'dbname':database},autocommit=True) as c:
                c.execute("SELECT set_config('noteai.item34.expected_database',%s,false)",(database,))
                c.execute("SELECT set_config('noteai.item34.expected_owner','wrong-owner',false)")
                with self.assertRaisesRegex(psycopg.errors.RaiseException,'database or owner binding'):
                    c.execute(candidate,prepare=False)
                c.execute('ROLLBACK')
                c.execute("SELECT set_config('noteai.item34.expected_owner','postgres',false)")
                broken=candidate.replace('-- DDL_PAYLOAD_END\n','SELECT 1/0;\n-- DDL_PAYLOAD_END\n')
                with self.assertRaises(psycopg.errors.DivisionByZero):c.execute(broken,prepare=False)
                c.execute('ROLLBACK')
                self.assertEqual(c.execute("SELECT count(*) FROM pg_attribute WHERE attrelid='tracked_notes'::regclass "
                    "AND attname='observation_generation' AND NOT attisdropped").fetchone()[0],0)
                self.assertEqual(c.execute("SELECT count(*) FROM schema_migrations WHERE version>='0020'").fetchone()[0],0)
                c.execute(psycopg.sql.SQL('GRANT USAGE,CREATE ON SCHEMA public TO {}').format(psycopg.sql.Identifier(role)))
                for table in ('tracked_notes','tracking_provider_attempts','schema_migrations'):
                    c.execute(psycopg.sql.SQL('ALTER TABLE {} OWNER TO {}').format(
                        psycopg.sql.Identifier(table),psycopg.sql.Identifier(role)))
                c.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
                c.execute("SELECT set_config('noteai.item34.expected_owner',%s,false)",(role,))
                self.assertFalse(c.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()[0])
                c.execute(candidate,prepare=False)
                self.assertEqual(c.execute("SELECT n.nspname,count(*) FROM pg_proc p JOIN pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE p.proname IN ('noteai_item34_open_observation',"
                    "'noteai_item34_observation_owner_guard') AND pg_get_userbyid(p.proowner)=current_user "
                    "GROUP BY n.nspname").fetchall(),[('public',2)])
        finally:
            self.admin.execute(psycopg.sql.SQL('DROP DATABASE {}').format(psycopg.sql.Identifier(database)))
            self.admin.execute(psycopg.sql.SQL('DROP ROLE {}').format(psycopg.sql.Identifier(role)))

    def test_concurrent_open_has_one_winner(self):
        barrier = threading.Barrier(2)
        results = []
        def run():
            with psycopg.connect(**self.args,autocommit=True) as c:
                barrier.wait(timeout=5)
                try: results.append(self.open(connection=c))
                except psycopg.Error: results.append("rejected")
        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertCountEqual(results,[1,"rejected"])
        self.assert_history_unchanged()

    def test_legacy_worker_cannot_activate_default_generation_attempt(self):
        self.open(); self.time=self.anchor+timedelta(hours=24)
        self.assertEqual(self.crawler._claim_due_tracking_notes(1),[])
        self.assertEqual(self.claim(generation=None),[])
        self.assertEqual(self.claim(generation=2),[])
        note=self.claim()[0]
        attempted=str(uuid.uuid4())
        with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.owner.transaction():
            self.owner.execute("INSERT INTO tracking_provider_attempts(id,track_id,user_id,run_id,stage,status,admitted_at) "
                "VALUES(%s,%s,%s,'legacy-other-run','7d','started',%s)",
                (attempted,self.track,self.uid,self.time.isoformat()))
            self.owner.execute("UPDATE tracked_notes SET active_attempt_id=%s WHERE id=%s",(attempted,self.track))
        self.assertIsNone(self.row("tracked_notes",self.track)["active_attempt_id"])
        self.assertEqual(self.owner.execute("SELECT count(*) FROM tracking_provider_attempts").fetchone()[0],1)
        self.crawler._release_unstarted_claim(note)

    def test_ordinary_queue_skips_prospective_generation_without_starving_old_work(self):
        self.open(); self.time=self.anchor+timedelta(hours=25)
        other=str(uuid.uuid4())
        self.owner.execute("INSERT INTO tracked_notes(id,user_id,xhs_note_id,xhs_url,submitted_at,next_check_at) "
            "VALUES(%s,%s,'1123456789abcdef01234567','https://www.xiaohongshu.com/explore/1123456789abcdef01234567',"
            "%s,%s)",(other,self.uid,self.anchor.isoformat(),(self.time-timedelta(minutes=1)).isoformat()))
        claimed=self.crawler._claim_due_tracking_notes(1,now=self.time)
        self.assertEqual([r['id'] for r in claimed],[other])
        self.crawler._release_unstarted_claim(claimed[0])
        self.assertIsNone(self.row('tracked_notes',self.track)['claim_token'])

    def test_global_orphan_started_and_unknown_block_open_and_new_admission(self):
        other,attempt=str(uuid.uuid4()),str(uuid.uuid4())
        self.owner.execute("INSERT INTO tracked_notes(id,user_id,xhs_note_id,xhs_url,submitted_at) "
            "VALUES(%s,%s,'1123456789abcdef01234567','https://www.xiaohongshu.com/explore/1123456789abcdef01234567',%s)",
            (other,self.uid,'2026-01-01T00:00:00Z'))
        self.owner.execute("INSERT INTO tracking_provider_attempts(id,track_id,user_id,run_id,stage,status,admitted_at) "
            "VALUES(%s,%s,%s,'synthetic-orphan','24h','started','2026-01-02T00:00:00Z')",(attempt,other,self.uid))
        with self.assertRaises(psycopg.Error):self.open()
        self.owner.execute("UPDATE tracking_provider_attempts SET status='failed',completed_at='2026-01-02T00:01:00Z',"
            "error_code='provider_outcome_unknown' WHERE id=%s",(attempt,))
        with self.assertRaises(psycopg.Error):self.open()
        self.owner.execute("UPDATE tracking_provider_attempts SET error_code='synthetic_reconciled' WHERE id=%s",(attempt,))
        self.open(); self.time=self.anchor+timedelta(hours=24)
        self.owner.execute("INSERT INTO tracking_provider_attempts(id,track_id,user_id,run_id,stage,status,admitted_at) "
            "VALUES(%s,%s,%s,'synthetic-new-orphan','7d','started',%s)",
            (str(uuid.uuid4()),other,self.uid,self.time.isoformat()))
        with self.assertRaisesRegex(ValueError,'global outcome unresolved'):
            self.crawler._admit_provider_attempt(self.claim()[0])
        self.assertEqual(self.owner.execute("SELECT count(*) FROM tracking_provider_attempts WHERE track_id=%s",
            (self.track,)).fetchone()[0],1)

    def test_actual_two_stage_writers_have_nine_new_and_thirteen_combined_distinct_objects(self):
        self.open()
        self.role = "noteai_xhs_tracking"
        self.owner.execute("UPDATE system_settings SET value_json=%s WHERE key='crawler_config'",('{"local":true}',))
        self.time=self.anchor+timedelta(hours=24); self.run_stage("24h")
        expected_due=self.anchor+timedelta(hours=72)
        self.assertEqual(self.crawler._parse_iso(self.row("tracked_notes",self.track)["next_check_at"]),expected_due)
        self.time=expected_due-timedelta(microseconds=1); self.assertEqual(self.claim("3d"),[])
        self.time=expected_due; self.run_stage("3d")
        self.owner.execute("UPDATE system_settings SET value_json='{}' WHERE key='crawler_config'")
        current=self.row("tracked_notes",self.track); self.assertEqual(current["status"],"complete")
        for effect,table in (("growth","growth_records"),("memory","user_memories")):
            ident=self.contract.deterministic_effect_id(self.track,effect,generation=1)
            self.assertNotEqual(ident,self.contract.deterministic_effect_id(self.track,effect))
            self.assertEqual(self.row(table,ident)["user_id"],self.uid)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.owner.execute("INSERT INTO tracking_provider_attempts(id,track_id,user_id,run_id,stage,status,"
                "admitted_at,observation_generation) VALUES(%s,%s,%s,'different-run','24h','started',%s,1)",
                (str(uuid.uuid4()),self.track,self.uid,self.time.isoformat()))
        window=self.objects("window"); proposal=self.objects("proposal"); new=window|proposal
        self.assertEqual(len(window),8); self.assertEqual(len({t for t,_ in window}),6)
        self.assertEqual(len(new),9); self.assertEqual(len({t for t,_ in new}),7)
        self.assertEqual(len(self.history|new),13)
        self.assertEqual(self.object_counts(new), {'schema_migrations':1,'tracked_notes':1,
            'tracking_provider_attempts':2,'growth_records':1,'user_memories':1,
            'crawler_events':2,'system_settings':1})
        self.assertEqual(self.object_counts(self.history|new), {'schema_migrations':2,'tracked_notes':1,
            'tracking_provider_attempts':3,'growth_records':1,'user_memories':1,
            'crawler_events':4,'system_settings':1})
        self.assertEqual(self.owner.execute("SELECT count(*) FROM tracking_provider_attempts").fetchone()[0],3)
        self.assert_history_unchanged()
        mutations=self.owner.execute("SELECT table_name,count(*) FROM item34_test_dml WHERE phase='window' "
                                     "GROUP BY table_name ORDER BY table_name").fetchall()
        print(json.dumps({"local_generation_budget":{"sampling_distinct":8,"including_one_migration":9,
              "combined_with_old_history":13,"attempts_total":3,"window_dml_mutations":dict(mutations)}}))

    def test_normal_tracking_role_cannot_open_window_or_change_anchor(self):
        self.owner.execute('SET ROLE noteai_xhs_tracking')
        try:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):self.open()
            for column in ('observation_generation','observation_started_at','observation_initial_snapshot'):
                self.assertFalse(self.owner.execute('SELECT has_column_privilege(current_user,\'tracked_notes\',%s,\'UPDATE\')',
                                                     (column,)).fetchone()[0])
        finally:self.owner.execute('RESET ROLE')
        self.assertEqual(self.row('tracked_notes',self.track)['observation_generation'],0)

    def test_existing_table_wide_privilege_does_not_confer_observation_control(self):
        self.open()
        # Deliberately model an existing broader API-style table grant. This is
        # only a disposable fixture; no production privilege is changed.
        self.owner.execute('GRANT INSERT, UPDATE ON tracked_notes TO noteai_xhs_tracking')
        self.owner.execute('SET ROLE noteai_xhs_tracking')
        try:
            self.owner.execute("UPDATE tracked_notes SET status='pending' WHERE id=%s",(self.track,))
            with self.assertRaisesRegex(psycopg.errors.RaiseException,'metadata requires table owner'):
                self.owner.execute("UPDATE tracked_notes SET observation_started_at='2026-01-09T00:00:00Z' WHERE id=%s",(self.track,))
            with self.assertRaisesRegex(psycopg.errors.RaiseException,'metadata requires table owner'):
                self.owner.execute("INSERT INTO tracked_notes(id,user_id,xhs_note_id,xhs_url,submitted_at,observation_generation,"
                    "observation_started_at,observation_initial_snapshot) VALUES(%s,%s,'1123456789abcdef01234567',"
                    "'https://www.xiaohongshu.com/explore/1123456789abcdef01234567',%s,1,%s,%s::jsonb)",
                    (str(uuid.uuid4()),self.uid,self.anchor.isoformat(),self.anchor.isoformat(),'{"likes":1}'))
        finally:self.owner.execute('RESET ROLE')
        self.assertEqual(self.crawler._parse_iso(self.row('tracked_notes',self.track)['observation_started_at']),self.anchor)

    def test_stale_generation_finalize_release_and_unknown_reconcile(self):
        self.open(); self.time=self.anchor+timedelta(hours=24)
        note=self.claim()[0]; stale={**note,"observation_generation":0}
        with self.assertRaises(ValueError):self.crawler._release_unstarted_claim(stale)
        admitted=self.crawler._admit_provider_attempt(note); stale={**admitted,"observation_generation":0}
        before=self.row("tracked_notes",self.track)
        with self.assertRaises(ValueError):self.crawler._record_tracking_success(stale,{"likes":1,"saves":1,"comments":1})
        with self.assertRaises(ValueError):self.crawler._record_tracking_failure(stale,"synthetic","synthetic")
        self.assertEqual(self.row("tracked_notes",self.track),before)
        self.time+=timedelta(minutes=16)
        self.assertEqual(self.crawler._reconcile_stale_provider_attempts(now=self.time),1)
        attempt=self.row("tracking_provider_attempts",admitted["active_attempt_id"])
        self.assertEqual(attempt["error_code"],"provider_outcome_unknown")
        with self.assertRaises(psycopg.Error):self.open()
        self.assert_history_unchanged()

    def test_strict_24h_result_deadline_and_global_unknown_block(self):
        self.owner.execute("UPDATE tracking_provider_attempts SET error_code='provider_outcome_unknown' WHERE id=%s",(self.failed,))
        with self.assertRaises(psycopg.Error):self.open()
        self.owner.execute("UPDATE tracking_provider_attempts SET error_code='xhsadaptererror' WHERE id=%s",(self.failed,))
        self.open(); self.time=self.anchor+timedelta(hours=24)-timedelta(microseconds=1)
        self.assertEqual(self.claim(),[])
        self.time+=timedelta(microseconds=1); admitted=self.crawler._admit_provider_attempt(self.claim()[0])
        self.time=self.anchor+timedelta(hours=72)
        with self.assertRaises(ValueError):self.crawler._record_tracking_success(admitted,{"likes":1,"saves":1,"comments":1})
        self.assertIsNone(self.row("tracked_notes",self.track)["check_24h_at"])
        # Safety failure closure remains possible after the successful-result deadline.
        self.crawler._record_tracking_failure(admitted,"synthetic_deadline","synthetic_deadline")
        self.assertEqual(self.claim(),[])

    def admit_after_clock_advance(self, note, predicate, delta):
        execute = self.db.Transaction.execute
        advanced = []
        def execute_with_wait(tx, sql, params=()):
            result = execute(tx, sql, params)
            if not advanced and predicate(sql, params):
                self.time += delta
                advanced.append(True)
            return result
        try:
            with mock.patch.object(self.db.Transaction, 'execute', execute_with_wait):
                return self.crawler._admit_provider_attempt(note)
        finally:
            self.assertEqual(advanced, [True], 'the real SQL wait boundary must be exercised')

    def test_global_lock_wait_uses_actual_new_utc_day_and_admission_time(self):
        self.open(); self.time=self.anchor+timedelta(hours=36)-timedelta(seconds=1)
        self.role='noteai_xhs_tracking'
        admitted=self.admit_after_clock_advance(self.claim()[0],
            lambda sql,p: p == ('noteai:tracking:observation-open',), timedelta(seconds=2))
        attempt=self.row('tracking_provider_attempts',admitted['active_attempt_id'])
        self.assertEqual(self.crawler._parse_iso(attempt['admitted_at']),self.time)
        self.assertEqual(self.time.date().isoformat(),'2026-01-12')

    def test_complete_binding_is_required_at_claim_and_locked_admission(self):
        self.open(); self.time=self.anchor+timedelta(hours=24)
        with mock.patch.dict(os.environ,{'NOTEAI_ITEM34_OBSERVATION_BINDING_B64':''}):
            with self.assertRaisesRegex(ValueError,'binding missing'):self.claim()
        self.assertIsNone(self.row('tracked_notes',self.track)['claim_token'])
        note=self.claim()[0]
        self.owner.execute("UPDATE tracked_notes SET observation_initial_snapshot=%s::jsonb WHERE id=%s",
                           ('{"likes":5,"saves":2,"comments":2}',self.track))
        with self.assertRaisesRegex(ValueError,'binding_changed'):self.crawler._admit_provider_attempt(note)
        self.owner.execute("UPDATE tracked_notes SET observation_initial_snapshot=%s::jsonb WHERE id=%s",
                           (json.dumps(self.binding['initial_snapshot']),self.track))
        self.owner.execute("UPDATE tracking_provider_attempts SET error_code='changed_history' WHERE id=%s",(self.failed,))
        with self.assertRaisesRegex(ValueError,'history_changed'):self.crawler._admit_provider_attempt(note)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM tracking_provider_attempts WHERE track_id=%s',
                                            (self.track,)).fetchone()[0],1)
        self.assertIsNone(self.row('tracked_notes',self.track)['active_attempt_id'])

    def test_prospective_wrapper_reads_actual_generation_and_old_helper_cannot_reschedule_it(self):
        from deploy.production import execute_item34_tracking as wrapper
        # A synthetic T0 after the sealed legacy boundary, still in the past.
        self.anchor=datetime(2026,9,7,15,tzinfo=timezone.utc);self.time=self.anchor
        self.install_binding();self.open()
        self.owner.execute('GRANT SELECT ON tracked_notes,tracking_provider_attempts,growth_records,'
                           'user_memories,crawler_events,system_settings TO noteai_app')
        self.owner.execute('GRANT UPDATE(next_check_at) ON tracked_notes TO noteai_app')
        def app_connection(*,write):
            c=psycopg.connect(**self.args,autocommit=True,row_factory=psycopg.rows.dict_row)
            c.execute('SET ROLE noteai_app');c.autocommit=False
            return c
        with mock.patch.object(wrapper,'_connect',app_connection):
            with wrapper.checkpoint.observation_context(self.binding):
                before=self.row('tracked_notes',self.track)
                bound=wrapper._inner_bind(self.track)
                self.assertEqual((bound['status'],bound['target_rows_mutated']),('ALREADY_BOUND',0))
                self.assertEqual(self.row('tracked_notes',self.track),before)
                snap=wrapper._inner_snapshot('24h',self.track)['snapshot']
                self.assertEqual(snap['attempts']['rows'],[])
                self.assertEqual(snap['observation_binding_sha256'],wrapper.checkpoint.observation_identity()['observation_binding_sha256'])
                self.time=self.anchor+timedelta(hours=24);self.role='noteai_xhs_tracking';self.run_stage('24h')
                self.assertEqual(wrapper._inner_schedule(self.track)['target_rows_mutated'],0)
                snap=wrapper._inner_snapshot('24h',self.track)['snapshot']
                self.assertEqual(snap['attempts']['target_count_24h'],1)
                self.assertNotEqual(snap['attempts']['rows'][0]['attempt_id'],self.failed)
                self.assertTrue(wrapper._inner_config_snapshot()['config']['present'])
            due=self.row('tracked_notes',self.track)['next_check_at']
            with self.assertRaisesRegex(wrapper.ProductionAdapterError,'schedule_binding'):
                wrapper._inner_schedule(self.track)
            self.assertEqual(self.row('tracked_notes',self.track)['next_check_at'],due)
        self.assert_history_unchanged()

    def test_day_lock_wait_crossing_midnight_rejects_without_admission(self):
        self.open(); self.time=self.anchor+timedelta(hours=36)-timedelta(seconds=1)
        self.role='noteai_xhs_tracking'
        with self.assertRaisesRegex(ValueError,'UTC day changed'):
            self.admit_after_clock_advance(self.claim()[0],
                lambda sql,p: bool(p) and str(p[0]).startswith('noteai:tracking:daily-cap:'),
                timedelta(seconds=2))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM tracking_provider_attempts WHERE track_id=%s',
                                            (self.track,)).fetchone()[0],1)
        self.assertIsNone(self.row('tracked_notes',self.track)['active_attempt_id'])

    def test_quota_query_wait_expiring_lease_rejects_without_admission(self):
        self.open(); self.time=self.anchor+timedelta(hours=24)
        self.role='noteai_xhs_tracking'
        with self.assertRaisesRegex(ValueError,'claim expired'):
            self.admit_after_clock_advance(self.claim()[0],
                lambda sql,p: 'WHERE admitted_at::timestamptz' in sql, timedelta(minutes=16))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM tracking_provider_attempts WHERE track_id=%s',
                                            (self.track,)).fetchone()[0],1)
        self.assertIsNone(self.row('tracked_notes',self.track)['active_attempt_id'])

    def test_quota_query_wait_crossing_stage_deadline_rejects_without_admission(self):
        self.open(); self.time=self.anchor+timedelta(hours=72)-timedelta(seconds=1)
        self.role='noteai_xhs_tracking'
        with self.assertRaisesRegex(ValueError,'admission outside window'):
            self.admit_after_clock_advance(self.claim()[0],
                lambda sql,p: 'WHERE admitted_at::timestamptz' in sql, timedelta(seconds=2))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM tracking_provider_attempts WHERE track_id=%s',
                                            (self.track,)).fetchone()[0],1)
        self.assertIsNone(self.row('tracked_notes',self.track)['active_attempt_id'])

    def test_result_lock_or_final_sql_crossing_deadline_rolls_back_success(self):
        self.open(); self.time=self.anchor+timedelta(hours=72)-timedelta(seconds=1)
        self.role='noteai_xhs_tracking'
        admitted=self.crawler._admit_provider_attempt(self.claim()[0])
        before=self.row('tracked_notes',self.track)
        execute=self.db.Transaction.execute
        for boundary in ('FOR UPDATE', "UPDATE tracking_provider_attempts SET status='succeeded'"):
            with self.subTest(boundary=boundary):
                self.time=self.anchor+timedelta(hours=72)-timedelta(seconds=1)
                advanced=[]
                def execute_with_wait(tx, sql, params=()):
                    result=execute(tx,sql,params)
                    if boundary in sql and not advanced:
                        self.time+=timedelta(seconds=2)
                        advanced.append(True)
                    return result
                with mock.patch.object(self.db.Transaction,'execute',execute_with_wait):
                    with self.assertRaisesRegex(ValueError,'result outside window'):
                        self.crawler._record_tracking_success(admitted,{'likes':1,'saves':1,'comments':1,'title':'Local'})
                self.assertEqual(advanced,[True])
                self.assertEqual(self.row('tracked_notes',self.track),before)
                self.assertEqual(self.row('tracking_provider_attempts',admitted['active_attempt_id'])['status'],'started')
        self.assert_history_unchanged()

    def test_utc_daily_cap_includes_prior_generations_and_timezone_offsets(self):
        self.open(); self.time=self.anchor+timedelta(hours=24)
        other=str(uuid.uuid4())
        self.owner.execute("INSERT INTO tracked_notes(id,user_id,xhs_note_id,xhs_url,submitted_at) VALUES(%s,%s,"
            "'1123456789abcdef01234567','https://www.xiaohongshu.com/explore/1123456789abcdef01234567',%s)",
            (other,self.uid,self.anchor.isoformat()))
        for generation in range(300):
            self.owner.execute("INSERT INTO tracking_provider_attempts(id,track_id,user_id,run_id,stage,status,"
                "admitted_at,completed_at,error_code,observation_generation) VALUES(%s,%s,%s,'local-quota',"
                "'24h','failed','2026-01-10T20:30:00-04:00','2026-01-11T00:31:00Z','synthetic',%s)",
                (str(uuid.uuid4()),other,self.uid,generation))
        with self.assertRaises(self.contract.TrackingDailyLimitReached):
            self.crawler._admit_provider_attempt(self.claim()[0])
        self.assertEqual(self.owner.execute("SELECT count(*) FROM tracking_provider_attempts WHERE track_id=%s",
                                            (self.track,)).fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
