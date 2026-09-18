"""Bounded synthetic protocol and opt-in real, network-none PG16 capture checks."""
import ast
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from tools import item33_trends_runtime_capture as runtime
from tools import item33_trends_dml_capture as dml
from tests import test_item33_trends_dml_capture as fixtures
coverage, CONNECT, ENABLED, ROOT = fixtures.coverage, fixtures.CONNECT, fixtures.ENABLED, fixtures.ROOT


def config_fixture(activation=None):
    activation = activation or str(uuid.uuid4())
    return dict(schema=runtime.CONFIG_SCHEMA, activation_id=activation,
        activation_identity_sha256=runtime.sha(activation.encode()), bucket_key=datetime.now(timezone.utc).date().isoformat(),
        socket_path=runtime.SOCKET_PATH, accepted_source_sha256=dict.fromkeys(runtime.ACCEPTED_REFS, 'a'*64),
        instrumentation_sha256=dict.fromkeys(runtime.INSTRUMENTATION_REFS, 'b'*64),
        coverage=dml._coverage(coverage()), coverage_sha256=dml.coverage_sha256(coverage()),
        catalog_before_sha256='c'*64, installed_definition_sha256='d'*64)


def sealed_fixture():
    config = config_fixture(); binding = dict(nonce=str(uuid.uuid4()),run_identity_sha256='e'*64,pid=123,txid='12345')
    events = [dict(kind='capture_start',activation_id=config['activation_id'],configuration_sha256=runtime.sha(runtime.encoded(config)),bucket_key=config['bucket_key']),
        dict(kind='barrier',activation_id=config['activation_id'],phase='start',nonce=str(uuid.uuid4()),sender_pid=122),
        dict(kind='registered',**binding), dict(kind='commit',**binding,sender_pid=123,mutation_count=0),
        dict(kind='admission_closed',activation_id=config['activation_id']),
        dict(kind='barrier',activation_id=config['activation_id'],phase='end',nonce=str(uuid.uuid4()),sender_pid=122)]
    aggregate = dml.aggregate_records(events[2:4],activation=config['activation_id'],targets=coverage(),run_identity_sha256='e'*64,require_mutation_count=True)
    with tempfile.TemporaryDirectory() as directory:
        journal=runtime.Journal(Path(directory)/'journal');
        for event in events: journal.append(event)
        metadata=journal.metadata(); raw=journal.path.read_bytes(); journal.close()
    seal = dict(schema=runtime.SEAL_SCHEMA,state='CAPTURE_SEALED_NOT_TERMINAL',activation_id=config['activation_id'],
        activation_identity_sha256=config['activation_identity_sha256'],run_identity_sha256='e'*64,bucket_key=config['bucket_key'],
        config_sha256=runtime.sha(runtime.encoded(config)),
        **{k:config[k] for k in ('accepted_source_sha256','instrumentation_sha256','coverage_sha256','catalog_before_sha256','installed_definition_sha256','coverage')},
        journal=metadata,stream=dict(start_barrier_received=True,end_barrier_received=True,disconnect_count=0,invalid_count=0),
        writers=dict(registered=1,committed=1,rolled_back=0,admission_closed=True,all_closed=True),
        counted_commits=True,single_bucket_only=True,readiness_credit=False,aggregate=aggregate,catalog_proof=None)
    return seal,raw


class RuntimePureTests(unittest.TestCase):
    def test_chained_counted_journal_not_automatically_terminal(self):
        seal,raw=sealed_fixture()
        self.assertEqual(runtime.verify_capture_artifacts(seal,raw,require_terminal_proofs=False),seal['aggregate'])
        with self.assertRaises(ValueError): runtime.verify_capture_artifacts(seal,raw)

    def test_changed_omitted_or_boolean_metadata_rejected(self):
        original,raw=sealed_fixture()
        for defect in ('bytes','chain','bool','closed','source','config','aggregate'):
            seal=copy.deepcopy(original); candidate=raw
            if defect=='bytes': candidate=raw[:-1]
            elif defect=='chain': candidate=raw.replace(b'12345',b'12346',1)
            elif defect=='bool': seal['writers']['registered']=True
            elif defect=='closed': seal['writers']['all_closed']=False
            elif defect=='source': seal['accepted_source_sha256'].pop('model/hot_keywords.py')
            elif defect=='config': seal['config_sha256']='f'*64
            else: seal['aggregate']['write_mutations_by_table']={'hot_keywords':1}
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                runtime.verify_capture_artifacts(seal,candidate,require_terminal_proofs=False)

    def test_writer_stops_before_opening_connection_in_next_bucket(self):
        config=config_fixture(); calls=[]
        context=runtime.WriterContext(config,clock=lambda:datetime.now(timezone.utc)+timedelta(days=1))
        with self.assertRaises(runtime.CaptureError): context.connection(lambda:calls.append('opened'))
        self.assertEqual(calls,[])

    def test_close_does_not_claim_closed_while_a_protocol_thread_is_alive(self):
        class PendingThread:
            def join(self,timeout): self.timeout=timeout
            def is_alive(self): return True
        with tempfile.TemporaryDirectory() as directory:
            capture=runtime.CaptureSession(config_fixture(),Path(directory))
            capture.rpc_thread=PendingThread()
            with self.assertRaisesRegex(runtime.CaptureError,'close_unknown'):capture.close()
            self.assertEqual(capture.rpc_thread.timeout,1)

    def test_known_late_capture_failure_cannot_be_reported_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            capture=runtime.CaptureSession(config_fixture(),Path(directory))
            capture.ended=True
            capture.fail(disconnect=True)
            with self.assertRaisesRegex(runtime.CaptureError,'close_unknown'):capture.close()

    def test_cold_initialization_transport_stops_at_bucket_boundary(self):
        calls=[]
        class Client:
            def request(self,*args,**kwargs):calls.append((args,kwargs));return 'same-result'
        current=[datetime.now(timezone.utc)]
        context=runtime.WriterContext(config_fixture(),clock=lambda:current[0])
        runtime.guard_transport(Client,context)
        self.assertEqual(Client().request('GET','synthetic'), 'same-result')
        current[0]+=timedelta(days=1)
        with self.assertRaises(runtime.CaptureError):Client().request('GET','synthetic')
        self.assertEqual(len(calls),1)

    def test_journal_exclusive_and_preserves_original_on_second_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'journal'; journal=runtime.Journal(path); journal.append({'kind':'safe'})
            original=path.read_bytes()
            with self.assertRaises(FileExistsError): runtime.Journal(path)
            self.assertEqual(path.read_bytes(),original); self.assertEqual(path.stat().st_mode & 0o777,0o600); journal.close()


@unittest.skipUnless(ENABLED,'explicit disposable PG16 socket required')
class RuntimePostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.fixture=fixtures.Item33DmlPostgresTests('test_real_schema_counts_distinct_rows_and_atomic_transaction'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups); self.fixture.enable_counted()
        self.temporary=tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.config=config_fixture(self.fixture.activation)
        self.listener=psycopg.connect(**CONNECT,autocommit=True);self.addCleanup(self.listener.close)
        self.capture=runtime.CaptureSession(self.config,Path(self.temporary.name)); self.expected_close_unknown=False
        def close_capture():
            if self.expected_close_unknown:
                with self.assertRaisesRegex(runtime.CaptureError,'close_unknown'):self.capture.close()
            else:self.capture.close()
        self.addCleanup(close_capture)
        self.capture.start(self.listener,self.fixture.owner)
        self.socket=Path(self.temporary.name)/'capture.sock'; self.capture.serve(self.socket,expected_uid=os.geteuid())
        # Exact existing production compatibility class, without importing app/db.
        tree=ast.parse((ROOT/'model/hot_keywords.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='_PostgresCompatConnection')
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'hot_keywords.py','exec'),namespace)
        compat=namespace[node.name]
        def connect(): return compat(psycopg.connect(**(CONNECT|{'user':dml.WRITER_ROLE}),autocommit=False))
        self.connect=connect
        def rpc(config,operation,binding):
            # Only the local socket path differs from the fixed container mount.
            return runtime.writer_rpc(dict(config,socket_path=str(self.socket)),operation,binding)
        self.context=runtime.WriterContext(self.config,rpc=rpc)

    def claim(self):
        conn=self.context.connection(self.connect)
        with conn:
            conn.execute(runtime.CLAIM_SQL,(self.fixture.run_id,self.config['bucket_key'],'running','f'*64,1,
                datetime.now(timezone.utc)+timedelta(minutes=30),datetime.now(timezone.utc)))
        return self.context.run_identity

    def test_actual_writer_notify_commit_rollback_and_durable_seal(self):
        self.assertEqual(self.claim(),self.fixture.run_hash)
        with self.context.connection(self.connect) as conn:
            conn.execute("INSERT INTO hot_keywords(keyword,captured_at) VALUES (?,?)",('private-text','safe-time'))
        with self.assertRaisesRegex(ValueError,'synthetic'):
            with self.context.connection(self.connect) as conn:
                conn.execute("UPDATE hot_keywords SET search_vol=?",(9,));raise ValueError('synthetic')
        seal=self.capture.seal(self.fixture.owner);raw=self.capture.journal.path.read_bytes()
        self.assertEqual(seal['writers'],dict(registered=3,committed=2,rolled_back=1,admission_closed=True,all_closed=True))
        self.assertEqual(runtime.verify_capture_artifacts(seal,raw,require_terminal_proofs=False)['write_mutations_by_table'],
            {'hot_keywords':1,'xhs_trends_runs':1})
        self.assertNotIn(b'private-text',raw);self.assertNotIn(self.fixture.run_id.encode(),raw)
        self.assertEqual(self.fixture.owner.execute('SELECT search_vol FROM hot_keywords').fetchone()[0],50)

    def test_ddl_second_run_and_closed_writer_fail_before_business_write(self):
        self.claim()
        for statement,params in [('CREATE TABLE must_not_exist(id int)',()),(runtime.CLAIM_SQL,
                (str(uuid.uuid4()),self.config['bucket_key'],'running','f'*64,1,datetime.now(timezone.utc),datetime.now(timezone.utc)))]:
            with self.assertRaises(runtime.CaptureError):
                with self.context.connection(self.connect) as conn: conn.execute(statement,params)
        self.capture.seal(self.fixture.owner)
        with self.assertRaises(runtime.CaptureError):
            with self.context.connection(self.connect) as conn: conn.execute('UPDATE hot_keywords SET search_vol=9')
        self.assertEqual(self.fixture.owner.execute("SELECT to_regclass('public.must_not_exist')").fetchone()[0],None)
        self.expected_close_unknown=True

    def test_same_bucket_readonly_skip_needs_no_new_registration(self):
        self.claim(); self.capture.seal(self.fixture.owner)
        restarted=runtime.WriterContext(self.config,rpc=lambda *args:self.fail('readonly must not register'))
        with restarted.connection(self.connect) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM xhs_trends_runs').fetchone()[0],1)
        self.assertEqual(len(self.capture.bindings),1)
