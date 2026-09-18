"""Pure proof mutations and actual, disposable PG16 catalog closure negatives."""
import copy
from datetime import datetime, timedelta, timezone
import unittest

from tools import item33_trends_capture_catalog as catalog
from tools import item33_trends_runtime_capture as runtime
from tools import item33_trends_dml_capture as dml
from tests import test_item33_trends_dml_capture as fixtures
from tests.test_item33_trends_runtime_capture import config_fixture


def catalog_fixture(config):
    """Synthetic catalog satisfying the real verifier; never production evidence."""
    targets=catalog.targets_from(config); tables=sorted(targets)
    body=runtime.sha(dml.function_body(config['activation_id'],targets,mutation_counts=True).encode())
    columns=[];triggers=[]
    for table in tables:
        for name in sorted(set(targets[table].key_columns)|catalog.UPDATE_COLUMNS.get(table,set())):
            columns.append(dict(table=table,name=name,type_schema='pg_catalog',generated='',identity='',update_allowed=name in catalog.UPDATE_COLUMNS.get(table,set())))
        for suffix,kind in (('',29),('_truncate',32)):
            triggers.append(dict(table=table,name=dml.TRIGGER+suffix,enabled='O',internal=False,type=kind,function_schema='public',function=dml.FUNCTION,
                function_builtin=False,security_definer=False,arguments_hex=('{' + ','.join(targets[table].key_columns) + '}\0' + targets[table].group + '\0').encode().hex(),
                constraint_type=None,definition_sha256='a'*64,when_expression=None,column_filter='',transition_old=None,transition_new=None,deferrable=False,initially_deferred=False))
    value=dict(role=dict(name=dml.WRITER_ROLE,super=False,inherit=False,create_role=False,create_db=False,replication=False,bypass_rls=False,login=True),
        privileges=[dict(table=t,select=t in dml.TABLE_KEYS,insert=t in dml.TABLE_KEYS and t!='xhs_trends_service_state',update=False,delete=False,truncate=False,references=False,trigger=False) for t in tables],
        tables=[dict(name=t,kind='r',rls=False,forced_rls=False,partition=False,inheritance=0,keys=list(targets[t].key_columns)) for t in tables],
        columns=columns,triggers=triggers,rules=[],foreign_keys=[],functions=[dict(schema='public',name=dml.FUNCTION,arguments='',language='plpgsql',security_definer=False,config=['search_path=pg_catalog'],body_sha256=body,kind='f',result='trigger')],
        expression_functions=[],outside_writes=0,schema_create=0,database_create=False,database_temp=True,owned_objects=0,memberships=0)
    config['catalog_before_sha256']=catalog.digest(value);config['installed_definition_sha256']=body
    now=datetime.now(timezone.utc)
    before=dict(schema=catalog.SCHEMA,observed_at=now.isoformat(),bucket_key=config['bucket_key'],database_role=dml.WRITER_ROLE,catalog=value,catalog_sha256=catalog.digest(value),server_enforced_read_only=True,
        xid_assigned=False,production_database_writes=0,provider_calls=0,transaction_rolled_back=True)
    after=copy.deepcopy(before);after['observed_at']=(now+timedelta(microseconds=1)).isoformat()
    return catalog.build_catalog_proof(before,after,config=config,source_sha256='c'*64)


class CatalogPureTests(unittest.TestCase):
    def test_inaccessible_forbidden_guard_is_preserved_but_allowed_path_stays_closed(self):
        config=config_fixture();proof=catalog_fixture(config)
        value=copy.deepcopy(proof['before']['catalog'])
        guard=copy.deepcopy(value['triggers'][0]);guard.update(table='item33_test_payment',name='original_payment_guard',
            function='original_payment_guard_function',type=11,arguments_hex='')
        value['triggers'].append(guard)
        self.assertEqual(catalog.validate_catalog(value,config=config),config['installed_definition_sha256'])
        guard['table']='hot_keywords'
        with self.assertRaises(ValueError):catalog.validate_catalog(value,config=config)
        guard['table']='item33_test_payment'
        next(row for row in value['privileges'] if row['table']==guard['table'])['insert']=True
        with self.assertRaises(ValueError):catalog.validate_catalog(value,config=config)

    def test_actual_structure_not_boolean_proof_and_temp_is_disclosed(self):
        config=config_fixture();proof=catalog_fixture(config)
        self.assertIsNone(catalog.verify_catalog_proof(proof,config=config));self.assertTrue(proof['temporary_ddl_capability'])
        with self.assertRaises(ValueError): catalog.verify_catalog_proof({'verified':True},config=config)

    def test_unknown_function_rule_fk_trigger_or_acl_is_not_closure(self):
        config=config_fixture();proof=catalog_fixture(config)
        for defect in ('function','rule','fk','trigger','body','column','metadata_bool','ddl_bool','after'):
            item=copy.deepcopy(proof);value=item['after']['catalog']
            if defect=='function':value['functions'][0]['security_definer']=True
            elif defect=='rule':value['rules']=[{'name':'hidden'}]
            elif defect=='fk':value['foreign_keys']=[{}]
            elif defect=='trigger':value['triggers'][0]['enabled']='D'
            elif defect=='body':value['functions'][0]['body_sha256']='f'*64
            elif defect=='column':value['columns']=[]
            elif defect=='metadata_bool':value['outside_writes']=False
            elif defect=='ddl_bool':item['business_ddl_count']=False
            else:item['after']['observed_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
            item['after']['catalog_sha256']=catalog.digest(value)
            with self.subTest(defect=defect),self.assertRaises(ValueError):catalog.verify_catalog_proof(item,config=config)


@unittest.skipUnless(fixtures.ENABLED,'explicit disposable PG16 socket required')
class CatalogPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.fx=fixtures.Item33DmlPostgresTests('test_real_schema_counts_distinct_rows_and_atomic_transaction');self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.enable_counted();self.config=config_fixture(self.fx.activation)
        owner=self.fx.owner
        owner.execute('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM noteai_xhs_trends')
        for table in dml.TABLE_KEYS:
            rights='SELECT' if table=='xhs_trends_service_state' else 'SELECT,INSERT'
            owner.execute(sql.SQL('GRANT '+rights+' ON {} TO noteai_xhs_trends').format(sql.Identifier(table)))
        for table,columns in catalog.UPDATE_COLUMNS.items():
            owner.execute(sql.SQL('GRANT UPDATE ({}) ON {} TO noteai_xhs_trends').format(sql.SQL(',').join(map(sql.Identifier,sorted(columns))),sql.Identifier(table)))
        self.reader=psycopg.connect(**(fixtures.CONNECT|{'user':dml.WRITER_ROLE}),autocommit=True);self.addCleanup(self.reader.close)

    def read(self): return catalog.read_catalog_facts(self.reader,config=self.config,now=datetime.now(timezone.utc))

    def bind(self,before):
        self.config['catalog_before_sha256']=before['catalog_sha256']
        self.config['installed_definition_sha256']=catalog.validate_catalog(before['catalog'],config=self.config)

    def test_real_catalog_exact_definitions_acl_foreign_keys_and_no_xid(self):
        before=self.read();self.bind(before);after=self.read()
        proof=catalog.build_catalog_proof(before,after,config=self.config,source_sha256='a'*64)
        self.assertEqual(proof['business_ddl_count'],0);self.assertTrue(proof['temporary_ddl_capability'])
        self.assertEqual(self.reader.info.transaction_status,0)
        self.assertTrue(before['catalog']['foreign_keys']);self.assertEqual(before['catalog']['rules'],[])

    def test_real_reader_uses_utc_and_rolls_back_original_timezone(self):
        self.reader.execute("SET TIME ZONE 'Asia/Shanghai'")
        before=self.read();self.bind(before)
        self.assertEqual(datetime.fromisoformat(before['observed_at']).utcoffset().total_seconds(),0)
        self.assertEqual(self.reader.execute("SHOW TIME ZONE").fetchone()[0],'Asia/Shanghai')

    def test_forbidden_column_only_insert_is_part_of_outside_write_proof(self):
        self.fx.owner.execute('GRANT INSERT(id) ON item33_test_payment TO noteai_xhs_trends')
        before=self.read()
        self.assertEqual(before['catalog']['outside_writes'],1)
        with self.assertRaises(ValueError):self.bind(before)

    def test_real_runtime_factory_seals_only_after_end_barrier_and_closure(self):
        import ast,os,tempfile,psycopg
        from pathlib import Path
        before=self.read();self.bind(before)
        tree=ast.parse((fixtures.ROOT/'model/hot_keywords.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='_PostgresCompatConnection')
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'compat','exec'),namespace)
        def connect():return namespace[node.name](psycopg.connect(**(fixtures.CONNECT|{'user':dml.WRITER_ROLE}),autocommit=False))
        with tempfile.TemporaryDirectory() as directory:
            capture=runtime.CaptureSession(self.config,Path(directory))
            listener=psycopg.connect(**fixtures.CONNECT,autocommit=True)
            try:
                capture.start(listener,self.fx.owner);sock=Path(directory)/'capture.sock';capture.serve(sock,expected_uid=os.geteuid())
                def rpc(config,op,binding):return runtime.writer_rpc(dict(config,socket_path=str(sock)),op,binding)
                context=runtime.WriterContext(self.config,rpc=rpc)
                with context.connection(connect) as conn:
                    conn.execute(runtime.CLAIM_SQL,(self.fx.run_id,self.config['bucket_key'],'running','f'*64,1,
                        datetime.now(timezone.utc)+timedelta(minutes=30),datetime.now(timezone.utc)))
                def proof():
                    self.assertTrue(capture.ended);self.assertTrue(capture.admission_closed)
                    self.assertEqual(set(capture.bindings),set(capture.closed))
                    return catalog.build_catalog_proof(before,self.read(),config=self.config,source_sha256='a'*64)
                seal=capture.seal(self.fx.owner,catalog_proof_factory=proof)
                aggregate=runtime.verify_capture_artifacts(seal,capture.journal.path.read_bytes())
                self.assertEqual(aggregate['write_mutations_by_table'],{'xhs_trends_runs':1})
                self.assertFalse(seal['readiness_credit'])
            finally:capture.close();listener.close()

    def test_real_known_original_trigger_guard_functions_are_allowed_without_new_privileges(self):
        import re
        for filename in ('0026_multimodal_usage.sql','0028_media_response_recovery.sql'):
            source=(fixtures.ROOT/'model/migrations/postgres'/filename).read_text()
            definition=re.search(r'CREATE FUNCTION public\.noteai_guard_.*?\$\$;',source,re.S).group(0)
            self.fx.owner.execute(definition)
        before=self.read();self.bind(before)
        self.assertEqual(len(before['catalog']['functions']),3)
        self.assertIsNone(catalog.verify_catalog_proof(catalog.build_catalog_proof(before,self.read(),config=self.config,source_sha256='a'*64),config=self.config))

    def test_real_cascading_update_fk_is_rejected(self):
        self.fx.owner.execute('ALTER TABLE xhs_trends_service_state DROP CONSTRAINT xhs_trends_state_active_fk')
        self.fx.owner.execute('ALTER TABLE xhs_trends_service_state ADD CONSTRAINT xhs_trends_state_active_fk FOREIGN KEY(active_run_id,lease_token_hash,lease_fence) REFERENCES xhs_trends_runs(id,lease_token_hash,lease_fence) ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED')
        with self.assertRaises(ValueError):catalog.validate_catalog(self.read()['catalog'],config=self.config)

    def test_real_rls_on_unreachable_forbidden_target_is_preserved(self):
        self.fx.owner.execute('ALTER TABLE item33_test_authentication ENABLE ROW LEVEL SECURITY')
        self.fx.owner.execute('ALTER TABLE item33_test_authentication FORCE ROW LEVEL SECURITY')
        before=self.read();self.bind(before)
        self.assertTrue(next(x for x in before['catalog']['tables'] if x['name']=='item33_test_authentication')['rls'])

    def test_real_unknown_security_definer_and_dynamic_sql_function_rejected(self):
        before=self.read();self.bind(before)
        self.fx.owner.execute("CREATE FUNCTION public.item33_unreviewed() RETURNS int LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN EXECUTE 'SELECT 1'; RETURN 1; END $$")
        after=self.read()
        with self.assertRaises(ValueError):catalog.validate_catalog(after['catalog'],config=self.config)

    def test_real_extra_rule_or_disabled_capture_rejected(self):
        before=self.read();self.bind(before)
        self.fx.owner.execute('ALTER TABLE hot_keywords DISABLE TRIGGER noteai_item33_trends_dml_notice')
        with self.assertRaises(ValueError):catalog.validate_catalog(self.read()['catalog'],config=self.config)
        self.fx.owner.execute('ALTER TABLE hot_keywords ENABLE TRIGGER noteai_item33_trends_dml_notice')
        self.fx.owner.execute('CREATE RULE item33_noop AS ON INSERT TO hot_keywords DO ALSO NOTHING')
        with self.assertRaises(ValueError):catalog.validate_catalog(self.read()['catalog'],config=self.config)

    def test_real_conditional_capture_and_custom_operator_are_rejected(self):
        from psycopg import sql
        self.fx.owner.execute('DROP TRIGGER noteai_item33_trends_dml_notice ON hot_keywords')
        self.fx.owner.execute(sql.SQL("CREATE TRIGGER noteai_item33_trends_dml_notice AFTER INSERT OR UPDATE OR DELETE ON hot_keywords FOR EACH ROW WHEN(false) EXECUTE FUNCTION noteai_item33_trends_dml_notice('{id}','allowed')"))
        with self.assertRaises(ValueError):catalog.validate_catalog(self.read()['catalog'],config=self.config)
        self.fx.owner.execute('DROP TRIGGER noteai_item33_trends_dml_notice ON hot_keywords')
        self.fx.owner.execute(sql.SQL("CREATE TRIGGER noteai_item33_trends_dml_notice AFTER INSERT OR UPDATE OR DELETE ON hot_keywords FOR EACH ROW EXECUTE FUNCTION noteai_item33_trends_dml_notice('{id}','allowed')"))
        self.fx.owner.execute("CREATE FUNCTION item33_operator(int,int) RETURNS bool LANGUAGE SQL AS 'SELECT true'; REVOKE ALL ON FUNCTION item33_operator(int,int) FROM PUBLIC")
        self.fx.owner.execute('CREATE OPERATOR === (FUNCTION=item33_operator,LEFTARG=int,RIGHTARG=int)')
        self.fx.owner.execute('ALTER TABLE hot_keywords ADD CONSTRAINT hidden_operator CHECK (search_vol === 0)')
        with self.assertRaises(ValueError):catalog.validate_catalog(self.read()['catalog'],config=self.config)

    def test_real_extra_write_acl_rejected(self):
        before=self.read();self.bind(before)
        self.fx.owner.execute('GRANT UPDATE ON hot_keywords TO noteai_xhs_trends')
        with self.assertRaises(ValueError):catalog.validate_catalog(self.read()['catalog'],config=self.config)
