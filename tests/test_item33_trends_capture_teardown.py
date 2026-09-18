"""Exact temporary-object removal: synthetic proof negatives and isolated PG16."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import item33_trends_capture_teardown as teardown
from tools import item33_trends_runtime_capture as runtime
from tools import item33_trends_capture_catalog as catalog
from tools import item33_trends_dml_capture as dml
from tests import test_item33_trends_runtime_capture as runtime_fx
from tests import test_item33_trends_capture_catalog as catalog_fx
from tests import test_item33_trends_dml_capture as db_fx


def sealed(config=None, proof=None):
    value, raw = runtime_fx.sealed_fixture()
    config = config or runtime_fx.config_fixture(value['activation_id'])
    proof = proof or catalog_fx.catalog_fixture(config)
    for key in runtime.CONFIG_KEYS - {'schema','socket_path'}:
        value[key] = copy.deepcopy(config[key])
    value['config_sha256'] = runtime.sha(runtime.encoded(config))
    value['catalog_proof'] = proof
    events = [json.loads(line)['event'] for line in raw.splitlines()]
    for event in events:
        if 'activation_id' in event: event['activation_id'] = config['activation_id']
    events[0]['configuration_sha256'] = value['config_sha256']
    with tempfile.TemporaryDirectory() as directory:
        journal = runtime.Journal(Path(directory)/'journal')
        for event in events: journal.append(event)
        value['journal'] = journal.metadata(); raw = journal.path.read_bytes(); journal.close()
    runtime.verify_capture_artifacts(value, raw)
    return value, raw


def proof_fixture():
    seal,journal = sealed(); raw = runtime.encoded(seal)+b'\n'
    after = copy.deepcopy(seal['catalog_proof']['after'])
    start = datetime.fromisoformat(after['observed_at']) + timedelta(seconds=1)
    after['observed_at'] = (start+timedelta(seconds=2)).isoformat()
    after['catalog'] = teardown._without_capture(after['catalog'])
    after['catalog_sha256'] = catalog.digest(after['catalog'])
    script = teardown.render_teardown_sql(seal=seal,journal=journal,operator_role='postgres')
    execution = dict(schema=teardown.EXECUTION_SCHEMA,status='COMMITTED',activation_identity_sha256=seal['activation_identity_sha256'],
        operator_role='postgres',sql_sha256=runtime.sha(script.encode()),started_at=start.isoformat(),committed_at=(start+timedelta(seconds=1)).isoformat(),
        control_plane_ddl_count=2*len(seal['coverage'])+1,outcome_unknown_count=0)
    proof=teardown.build_teardown_proof(seal_raw=raw,journal=journal,after=after,execution=execution,source_sha256='a'*64)
    return proof,raw,journal


class TeardownPureTests(unittest.TestCase):
    def test_only_exact_activation_objects_drop_inside_guarded_transaction(self):
        seal,journal=sealed()
        script=teardown.render_teardown_sql(seal=seal,journal=journal,operator_role='postgres')
        self.assertTrue(script.startswith('BEGIN;\n'));self.assertTrue(script.endswith('COMMIT;\n'))
        self.assertIn('IN ACCESS EXCLUSIVE MODE NOWAIT',script)
        self.assertIn('p.prosrc',script);self.assertIn('t.tgtype',script);self.assertIn('t.tgargs',script)
        self.assertIn(seal['activation_id'],script)
        self.assertEqual(script.count('DROP TRIGGER'),2*len(seal['coverage']))
        self.assertEqual(script.count('DROP FUNCTION'),1)
        for forbidden in ('CASCADE','DROP TRIGGER IF EXISTS','DROP FUNCTION IF EXISTS','GRANT ','ALTER TABLE','DROP TABLE','DELETE FROM'):
            self.assertNotIn(forbidden,script)

    def test_sql_literals_escape_quotes_backslashes_and_reject_non_identifier(self):
        self.assertEqual(teardown._literal("a'b\\c"), "E'a''b\\\\c'")
        for value in ('public;DROP','x"y','x.y'):
            with self.assertRaises(ValueError):teardown._identifier(value)
        with self.assertRaises(ValueError):teardown._literal('x\x00y')

    def test_full_proof_verifies_in_fresh_stdlib_only_interpreter(self):
        import subprocess,sys
        proof,raw,journal=proof_fixture()
        payload=json.dumps({'proof':proof,'seal':raw.decode(),'journal':journal.decode()}).encode()
        code="import sys,json;sys.path.insert(0,"+repr(str(db_fx.ROOT))+");from tools import item33_trends_capture_teardown as t;p=json.load(sys.stdin);t.verify_teardown_proof(p['proof'],seal_raw=p['seal'].encode(),journal=p['journal'].encode(),source_sha256='a'*64);assert 'psycopg' not in sys.modules;print('STDLIB_PROOF_PASS')"
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',code],input=payload,capture_output=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr.decode());self.assertEqual(result.stdout,b'STDLIB_PROOF_PASS\n')

    def test_real_verifier_requires_seal_journal_and_operator_identity(self):
        seal,journal=sealed()
        for kwargs in (dict(journal=journal[:-1],operator_role='postgres'),dict(journal=journal,operator_role=dml.WRITER_ROLE),
                       dict(journal=journal,operator_role='postgres;DROP')):
            with self.subTest(kwargs=tuple(kwargs)),self.assertRaises(ValueError):
                teardown.render_teardown_sql(seal=seal,**kwargs)

    def test_proof_retains_seal_and_exact_non_capture_catalog(self):
        proof,raw,journal=proof_fixture()
        before=copy.deepcopy(proof['before'])
        self.assertIsNone(teardown.verify_teardown_proof(proof,seal_raw=raw,journal=journal,source_sha256='a'*64))
        self.assertEqual(proof['before'],before)
        self.assertEqual(proof['capture_receipt_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(proof['control_plane_ddl_count'],2*len(json.loads(raw)['coverage'])+1)

    def test_residual_capture_acl_or_unrelated_catalog_change_is_rejected(self):
        proof,raw,journal=proof_fixture()
        for defect in ('trigger','function','acl','rls','other_function'):
            value=copy.deepcopy(proof); cat=value['after']['catalog']
            if defect=='trigger':cat['triggers'].append(copy.deepcopy(value['before']['catalog']['triggers'][0]))
            elif defect=='function':cat['functions'].append(copy.deepcopy(value['before']['catalog']['functions'][0]))
            elif defect=='acl':cat['privileges'][0]['delete']=True
            elif defect=='rls':cat['tables'][0]['rls']=True
            else:cat['functions'].append({'name':'unrelated'})
            value['after']['catalog_sha256']=catalog.digest(cat)
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                teardown.verify_teardown_proof(value,seal_raw=raw,journal=journal,source_sha256='a'*64)

    def test_unknown_execution_wrong_source_or_time_never_verifies(self):
        proof,raw,journal=proof_fixture()
        for defect in ('unknown','sql','identity','count_bool','unknown_bool','time','source','extra'):
            value=copy.deepcopy(proof)
            if defect=='unknown':value['execution']['status']='UNKNOWN'
            elif defect=='sql':value['execution']['sql_sha256']='f'*64
            elif defect=='identity':value['execution']['activation_identity_sha256']='f'*64
            elif defect=='count_bool':value['execution']['control_plane_ddl_count']=True
            elif defect=='unknown_bool':value['execution']['outcome_unknown_count']=False
            elif defect=='time':value['execution']['committed_at']=value['before']['observed_at']
            elif defect=='source':value['source_sha256']='f'*64
            else:value['unproved']=True
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                teardown.verify_teardown_proof(value,seal_raw=raw,journal=journal,source_sha256='a'*64)


@unittest.skipUnless(db_fx.ENABLED,'explicit isolated PG16 socket required')
class TeardownPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fx=catalog_fx.CatalogPostgresTests('test_real_catalog_exact_definitions_acl_foreign_keys_and_no_xid')
        self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        before=self.fx.read();self.fx.bind(before)
        proof=catalog.build_catalog_proof(before,self.fx.read(),config=self.fx.config,source_sha256='a'*64)
        self.seal,self.journal=sealed(self.fx.config,proof)
        self.script=teardown.render_teardown_sql(seal=self.seal,journal=self.journal,operator_role='postgres')

    def test_actual_pg_transaction_drops_only_capture_and_proof_verifies(self):
        start=datetime.now(timezone.utc)
        self.fx.fx.owner.execute(self.script)
        committed=datetime.now(timezone.utc)
        after=self.fx.read()
        execution=dict(schema=teardown.EXECUTION_SCHEMA,status='COMMITTED',activation_identity_sha256=self.seal['activation_identity_sha256'],
            operator_role='postgres',sql_sha256=runtime.sha(self.script.encode()),started_at=start.isoformat(),committed_at=committed.isoformat(),
            control_plane_ddl_count=2*len(self.seal['coverage'])+1,outcome_unknown_count=0)
        raw=runtime.encoded(self.seal)+b'\n'
        proof=teardown.build_teardown_proof(seal_raw=raw,journal=self.journal,after=after,execution=execution,source_sha256='a'*64)
        teardown.verify_teardown_proof(proof,seal_raw=raw,journal=self.journal,source_sha256='a'*64)
        self.assertEqual(after['catalog'],teardown._without_capture(self.seal['catalog_proof']['after']['catalog']))
        self.assertTrue(after['catalog']['triggers'])  # Original FK guard triggers are preserved.

    def test_changed_installed_body_rejects_without_any_partial_drop(self):
        import psycopg
        self.fx.fx.owner.execute('CREATE OR REPLACE FUNCTION public.'+dml.FUNCTION+"() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'changed'; END $$")
        with self.assertRaises(psycopg.Error): self.fx.fx.owner.execute(self.script)
        self.fx.fx.owner.rollback()
        self.assertEqual(len([x for x in self.fx.read()['catalog']['triggers'] if x['function']==dml.FUNCTION]),2*len(self.seal['coverage']))

    def test_pre_cycle_cleanup_has_actual_zero_bucket_sql_and_no_terminal_claim(self):
        script=teardown.render_pre_cycle_cleanup_sql(config=self.fx.config,
            installed_catalog=self.seal['catalog_proof']['after'],operator_role='postgres')
        self.assertIn('item33 pre-cycle zero activity required',script)
        self.fx.fx.owner.execute(script)
        self.assertEqual(self.fx.read()['catalog'],teardown._without_capture(self.seal['catalog_proof']['after']['catalog']))

    def test_pre_cycle_cleanup_rejects_real_existing_run_and_retains_capture(self):
        import psycopg
        owner=self.fx.fx.owner
        owner.execute('BEGIN')
        for query in dml.binding_sql(self.fx.config['activation_id'],str(__import__('uuid').uuid4()),'e'*64,mutation_counts=True):owner.execute(query)
        owner.execute(runtime.CLAIM_SQL.replace("?", "%s"),(self.fx.fx.run_id,self.fx.config['bucket_key'],'running','f'*64,1,
            datetime.now(timezone.utc)+timedelta(minutes=20),datetime.now(timezone.utc)))
        owner.execute('COMMIT')
        script=teardown.render_pre_cycle_cleanup_sql(config=self.fx.config,
            installed_catalog=self.seal['catalog_proof']['after'],operator_role='postgres')
        with self.assertRaises(psycopg.Error):owner.execute(script)
        owner.rollback()
        self.assertEqual(len([x for x in self.fx.read()['catalog']['triggers'] if x['function']==dml.FUNCTION]),2*len(self.seal['coverage']))
