"""Execute the saved 0019 SQL on an isolated PG16 fixture, not production."""

import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
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
            cls.created_role = not c.execute("SELECT 1 FROM pg_roles WHERE rolname='noteai_xhs_tracking'").fetchone()
            if cls.created_role:c.execute('CREATE ROLE noteai_xhs_tracking NOLOGIN')

    @classmethod
    def tearDownClass(cls):
        if cls.created_role:
            with psycopg.connect(host="/var/run/postgresql",dbname="postgres",user="postgres",autocommit=True) as c:
                c.execute('DROP ROLE noteai_xhs_tracking')

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
                           "VALUES(%s,%s,'0123456789abcdef01234567',"
                           "'https://www.xiaohongshu.com/explore/0123456789abcdef01234567',"
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
        candidate = (ROOT / "tests/fixtures/item34-observation-generation.sql").read_text()
        with self.owner.transaction():
            self.owner.execute(candidate, prepare=False)
            # Conditional budget for ONE prospective forward migration, not an
            # approved migration identity or a production ledger assertion.
            self.owner.execute("INSERT INTO schema_migrations(version,sha256) VALUES(%s,%s)",
                ("LOCAL_ITEM34_GENERATION_CANDIDATE_ONLY",hashlib.sha256(candidate.encode()).hexdigest()))
        acl = (ROOT / "scripts/postgres/noteai_production_runtime_roles.sql").read_text()
        tracking_acl = acl.split("-- NOTEAI-RUNTIME-ACL-STAGE: tracking\n",1)[1].split(
            "-- NOTEAI-RUNTIME-ACL-STAGE: trends",1)[0]
        self.owner.execute(tracking_acl, prepare=False)
        # Test-only measurement must not grant application schema/control rights.
        self.owner.execute('GRANT INSERT ON item34_test_dml TO noteai_xhs_tracking')
        self.set_phase("window")

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

    def open(self, *, connection=None, failed=None, anchor=None):
        return (connection or self.owner).execute(
            "SELECT noteai_item34_open_observation(%s,%s,0,%s,%s,%s::jsonb)",
            (self.track,self.uid,failed or self.failed,anchor or self.anchor,
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

    def run_stage(self, stage):
        spider = importlib.import_module("spider_xhs_http")
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"NOTEAI_ITEM34_ACCEPTANCE":"1",
                "NOTEAI_ITEM34_TRACK_ID":self.track,"NOTEAI_ITEM34_CHECKPOINT_STAGE":stage,
                "NOTEAI_ITEM34_OBSERVATION_GENERATION":"1"}))
            stack.enter_context(mock.patch.object(spider,"collection_route",return_value="direct"))
            stack.enter_context(mock.patch.object(spider,"collection_route_suspended",return_value=False))
            stack.enter_context(mock.patch.object(self.crawler.xhs_acquisition,"collection_safety_status",
                                                   return_value={"session_blocked":False}))
            fetch = stack.enter_context(mock.patch.object(self.crawler,"_extract_note_data_with_spider_http",
                new=mock.AsyncMock(return_value={"likes":20,"saves":10,"comments":3,"title":"Synthetic note"})))
            stack.enter_context(mock.patch.object(self.crawler,"_random_delay",new=mock.AsyncMock()))
            result = asyncio.run(self.crawler.run_collection_round(limit=1))
            self.assertEqual((result["collected"],result["attempted"],result["failed"]),(1,1,0))
            fetch.assert_awaited_once()

    def test_cas_preserves_failed_history_and_refuses_replay_wrong_identity_or_future_t0(self):
        for kwargs in ({"failed":str(uuid.uuid4())},{"anchor":datetime.now(timezone.utc)+timedelta(days=1)}):
            with self.assertRaises(psycopg.Error): self.open(**kwargs)
        self.assertEqual(self.open(),1)
        with self.assertRaises(psycopg.Error): self.open()
        self.assert_history_unchanged()
        self.assertEqual(self.row("tracked_notes",self.track)["observation_initial_snapshot"],
                         {"likes":4,"saves":2,"comments":2})

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
