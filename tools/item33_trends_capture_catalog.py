"""Read-only catalog closure for the one bound Item33 capture, not an installer.

No SQL or connection runs at import. TEMP capability is reported, not rewritten:
zero business DDL additionally relies on the bound writer's fixed SQL boundary.
Unknown executable application functions, rules and side-effect triggers reject.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

try:
    from tools import item33_trends_dml_capture as dml
except ModuleNotFoundError:
    import item33_trends_dml_capture as dml

SOURCE_REF = 'tools/item33_trends_capture_catalog.py'
SCHEMA = 'noteai.item33.capture_catalog_facts.v1'
PROOF_SCHEMA = 'noteai.item33.capture_catalog_proof.v1'
ROLE = dml.WRITER_ROLE
UPDATE_COLUMNS = {
    'hot_keywords': {'search_vol','trend_dir','source','sample_count','quality_score','evidence_level','quality_reason','captured_at'},
    'xhs_freshness_ledger': {'source','evidence_count','status','acquired_at','fresh_until','last_run_id','details_json'},
    'xhs_trends_runs': {'status','completed_at','provider_attempt_count','last_error_code','snapshot_sha256','snapshot_size'},
    'xhs_trends_provider_attempts': {'status','completed_at','error_code'},
    'xhs_trends_service_state': {'active_run_id','status','lease_token_hash','lease_fence','lease_expires_at','session_blocked','session_block_reason','session_blocked_at','updated_at'},
}
KNOWN_GUARDS = {
    'noteai_guard_ark_media_v1': ('fed9e570817da74d21a51c41a1fe7480f139f742886b3a979ed008477ec82afe','private_media_refs',23,'model/migrations/postgres/0026_multimodal_usage.sql'),
    'noteai_guard_response_reference_v1': ('ff0a29026abcf4e066f93f677ecde3fac8ed7d2bb5dff27ec1ee0a604d5c3b9c','idempotency_requests',31,'model/migrations/postgres/0028_media_response_recovery.sql'),
}
SAFE_DEPENDENCY_FUNCTIONS = {'nextval','to_char','to_date','length','jsonb_typeof','jsonb_array_length'}
RI_FUNCTIONS = {'RI_FKey_check_ins','RI_FKey_check_upd','RI_FKey_noaction_del','RI_FKey_noaction_upd',
    'RI_FKey_restrict_del','RI_FKey_restrict_upd','RI_FKey_cascade_del'}
CATALOG_KEYS = {'role','privileges','tables','columns','triggers','rules','foreign_keys','functions','expression_functions','outside_writes','schema_create','database_create','database_temp','owned_objects','memberships'}


def require(condition):
    if not condition: raise ValueError('item33_catalog_unproven')


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def targets_from(config):
    targets={k:dml.TableTarget(tuple(v['key_columns']),v['group']) for k,v in config['coverage'].items()}
    require(dml.coverage_sha256(targets)==config['coverage_sha256'])
    return targets


def validate_catalog(catalog, *, config):
    """Pure whitelist check of actual projected catalog rows, never caller booleans."""
    require(isinstance(catalog,dict) and set(catalog)==CATALOG_KEYS)
    targets=targets_from(config); tables=set(targets)
    role=catalog['role']
    require(role==dict(name=ROLE,super=False,inherit=False,create_role=False,create_db=False,replication=False,bypass_rls=False,login=True))
    require(all(type(role[x]) is bool for x in role if x!='name'))
    for key in ('outside_writes','schema_create','owned_objects','memberships'):
        require(type(catalog[key]) is int and catalog[key]==0)
    require(catalog['database_create'] is False and type(catalog['database_temp']) is bool)
    actual_tables=catalog['tables'];require(isinstance(actual_tables,list) and len(actual_tables)==len(tables))
    require({row['name'] for row in actual_tables}==tables)
    for row in actual_tables:
        require(set(row)=={'name','kind','rls','forced_rls','partition','inheritance','keys'} and row['kind']=='r'
            and type(row['rls']) is bool and type(row['forced_rls']) is bool
            and (row['name'] not in dml.TABLE_KEYS or (row['rls'] is False and row['forced_rls'] is False)) and row['partition'] is False
            and type(row['inheritance']) is int and row['inheritance']==0
            and row['keys']==list(targets[row['name']].key_columns))
    columns=catalog['columns'];require(isinstance(columns,list) and len(columns)<=2048)
    require(len({(x['table'],x['name']) for x in columns})==len(columns) and {x['table'] for x in columns}==tables)
    for table in tables:
        names={x['name'] for x in columns if x['table']==table}
        require(set(targets[table].key_columns)|UPDATE_COLUMNS.get(table,set()) <= names)
    for row in columns:
        require(set(row)=={'table','name','type_schema','generated','identity','update_allowed'} and row['table'] in tables
            and row['type_schema']=='pg_catalog' and row['generated']=='' and row['identity']==''
            and type(row['update_allowed']) is bool
            and row['update_allowed']==(row['name'] in UPDATE_COLUMNS.get(row['table'],set())))
    expected_privileges=[]
    for table in sorted(tables):
        expected_privileges.append(dict(table=table,select=table in dml.TABLE_KEYS,
            insert=table in dml.TABLE_KEYS and table!='xhs_trends_service_state',
            update=False,delete=False,truncate=False,references=False,trigger=False))
    require(catalog['privileges']==expected_privileges)
    require(all(type(value) is bool for row in catalog['privileges'] for key,value in row.items() if key!='table'))
    expected_body=hashlib.sha256(dml.function_body(config['activation_id'],targets,mutation_counts=True).encode()).hexdigest()
    functions=catalog['functions']
    expected_capture=dict(schema='public',name=dml.FUNCTION,arguments='',language='plpgsql',security_definer=False,
        config=['search_path=pg_catalog'],body_sha256=expected_body,kind='f',result='trigger')
    require(isinstance(functions,list) and functions.count(expected_capture)==1 and len(functions)<=1+len(KNOWN_GUARDS))
    seen_functions=set()
    for function in functions:
        require(function['name'] not in seen_functions);seen_functions.add(function['name'])
        if function==expected_capture: continue
        require(function['name'] in KNOWN_GUARDS)
        require(function==dict(schema='public',name=function['name'],arguments='',language='plpgsql',security_definer=False,
            config=['search_path=pg_catalog, public'],body_sha256=KNOWN_GUARDS[function['name']][0],kind='f',result='trigger'))
    require(catalog['rules']==[])
    fk=catalog['foreign_keys'];require(isinstance(fk,list) and len(fk)<=32)
    for row in fk:
        require(set(row)=={'source_schema','source','target_schema','target','update_action','delete_action','validated','source_columns','target_columns'}
            and row['source_schema']==row['target_schema']=='public' and row['source'] in tables and row['target'] in tables
            and row['update_action'] in ('a','r') and row['delete_action'] in ('a','r','c') and row['validated'] is True)
        require(isinstance(row['source_columns'],list) and isinstance(row['target_columns'],list)
            and 1<=len(row['source_columns'])==len(row['target_columns'])<=4)
        # No DELETE is permitted by either ACL or the bound writer. UPDATE cannot cascade.
    triggers=catalog['triggers']; require(isinstance(triggers,list) and len(triggers)<=256)
    seen=set(); capture_count=0
    for row in triggers:
        require(set(row)=={'table','name','enabled','internal','type','function_schema','function','function_builtin',
            'security_definer','arguments_hex','constraint_type','definition_sha256','when_expression','column_filter','transition_old','transition_new','deferrable','initially_deferred'})
        require(row['table'] in tables and (row['table'],row['name']) not in seen and row['enabled']=='O')
        seen.add((row['table'],row['name']));dml._sha(row['definition_sha256'])
        if row['internal'] is True:
            require(row['function_schema']=='pg_catalog' and row['function_builtin'] is True
                and row['function'] in RI_FUNCTIONS and row['constraint_type']=='f' and row['security_definer'] is False)
        elif (row['table'] not in dml.TABLE_KEYS and row['function'] != dml.FUNCTION
              and not any(fn['schema']==row['function_schema'] and fn['name']==row['function'] for fn in functions)):
            # Existing guards on inaccessible forbidden tables are not reachable
            # from this writer. Exact table/column ACLs above deny every write;
            # allowed triggers/functions/FK paths remain closed. Preserve these
            # definitions in the before/after catalog instead of modifying them.
            require(row['internal'] is False and targets[row['table']].group != 'allowed')
        elif row['function'] in KNOWN_GUARDS:
            guard=KNOWN_GUARDS[row['function']]
            require(row['internal'] is False and row['table']==guard[1] and row['name']==row['function']
                and row['type']==guard[2] and row['function'] in seen_functions and row['function_schema']=='public'
                and row['function_builtin'] is False and row['security_definer'] is False
                and row['constraint_type'] is None and row['arguments_hex']=='')
        else:
            require(row['internal'] is False and row['function_schema']=='public' and row['function']==dml.FUNCTION
                and row['function_builtin'] is False and row['security_definer'] is False and row['constraint_type'] is None)
            require(row['when_expression'] is None and row['column_filter']=='' and row['transition_old'] is None
                and row['transition_new'] is None and row['deferrable'] is False and row['initially_deferred'] is False)
            suffix='_truncate' if row['type']==32 else ''
            require(type(row['type']) is int and row['type'] in (29,32) and row['name']==dml.TRIGGER+suffix)
            target=targets[row['table']]
            expected=('{' + ','.join(target.key_columns) + '}\0' + target.group + '\0').encode().hex()
            require(row['arguments_hex']==expected);capture_count+=1
    require(capture_count==2*len(tables))
    for table in tables: require((table,dml.TRIGGER) in seen and (table,dml.TRIGGER+'_truncate') in seen)
    dependencies=catalog['expression_functions'];require(isinstance(dependencies,list) and len(dependencies)<=128)
    for row in dependencies:
        require(set(row)=={'schema','name','builtin','security_definer'} and row['schema']=='pg_catalog'
            and row['name'] in SAFE_DEPENDENCY_FUNCTIONS and row['builtin'] is True and row['security_definer'] is False)
    return expected_body


def read_catalog_facts(connection, *, config, now):
    """Actual single READ ONLY transaction; caller supplies idle original role."""
    from psycopg.rows import dict_row
    require(isinstance(now,datetime) and now.tzinfo is not None)
    require(connection.autocommit is True and connection.info.transaction_status==0)
    tables=sorted(targets_from(config));begun=False
    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute('BEGIN READ ONLY');begun=True;cur.execute("SET LOCAL statement_timeout='5000ms'");cur.execute("SET LOCAL TIME ZONE 'UTC'")
            identity=cur.execute("SELECT session_user::text AS session,current_user::text AS current,current_timestamp AS observed,current_setting('transaction_read_only') AS readonly,pg_current_xact_id_if_assigned()::text AS xid").fetchone()
            require(identity['session']==identity['current']==ROLE and identity['readonly']=='on' and identity['xid'] is None
                and abs((identity['observed']-now).total_seconds())<=60)
            role=dict(cur.execute('''SELECT rolname AS name,rolsuper AS super,rolinherit AS inherit,rolcreaterole AS create_role,
                rolcreatedb AS create_db,rolreplication AS replication,rolbypassrls AS bypass_rls,rolcanlogin AS login FROM pg_roles WHERE rolname=%s''',(ROLE,)).fetchone())
            rawtables=cur.execute('''SELECT c.oid,c.relname AS name,c.relkind::text AS kind,c.relrowsecurity AS rls,c.relforcerowsecurity AS forced_rls,
                c.relispartition AS partition,(SELECT count(*)::int FROM pg_inherits i WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS inheritance,
                (SELECT array_agg(a.attname::text ORDER BY k.ordinality) FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,ordinality)
                  JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum WHERE i.indrelid=c.oid AND i.indisprimary AND i.indisvalid AND a.attnotnull) AS keys
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname''',(tables,)).fetchall()
            oids=[x['oid'] for x in rawtables];allowed_oids=[x['oid'] for x in rawtables if x['name'] in dml.TABLE_KEYS];actualtables=[{k:v for k,v in x.items() if k!='oid'} for x in rawtables]
            privileges=cur.execute('''SELECT c.relname AS table,has_table_privilege(%s,c.oid,'SELECT') AS select,
                has_table_privilege(%s,c.oid,'INSERT') AS insert,has_table_privilege(%s,c.oid,'UPDATE') AS update,
                has_table_privilege(%s,c.oid,'DELETE') AS delete,has_table_privilege(%s,c.oid,'TRUNCATE') AS truncate,
                has_table_privilege(%s,c.oid,'REFERENCES') AS references,has_table_privilege(%s,c.oid,'TRIGGER') AS trigger
                FROM pg_class c WHERE c.oid=ANY(%s) ORDER BY c.relname''',(*(ROLE,)*7,oids)).fetchall()
            columns=cur.execute('''SELECT c.relname AS table,a.attname AS name,n.nspname AS type_schema,a.attgenerated::text AS generated,
                a.attidentity::text AS identity,has_column_privilege(%s,c.oid,a.attname,'UPDATE') AS update_allowed
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace n ON n.oid=t.typnamespace
                WHERE a.attrelid=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum''',(ROLE,oids)).fetchall()
            triggers=cur.execute('''SELECT c.relname AS table,t.tgname AS name,t.tgenabled::text AS enabled,t.tgisinternal AS internal,t.tgtype::int AS type,
                n.nspname AS function_schema,p.proname AS function,(p.oid<16384) AS function_builtin,p.prosecdef AS security_definer,
                encode(t.tgargs,'hex') AS arguments_hex,k.contype::text AS constraint_type,
                CASE WHEN t.tgqual IS NULL THEN NULL ELSE encode(sha256(convert_to(pg_get_expr(t.tgqual,t.tgrelid),'UTF8')),'hex') END AS when_expression,t.tgattr::text AS column_filter,
                t.tgoldtable AS transition_old,t.tgnewtable AS transition_new,t.tgdeferrable AS deferrable,t.tginitdeferred AS initially_deferred,
                encode(sha256(convert_to(pg_get_triggerdef(t.oid),'UTF8')),'hex') AS definition_sha256
                FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
                LEFT JOIN pg_constraint k ON k.oid=t.tgconstraint WHERE c.oid=ANY(%s) ORDER BY c.relname,t.tgname''',(oids,)).fetchall()
            rules=cur.execute('SELECT r.rulename AS name FROM pg_rewrite r WHERE r.ev_class=ANY(%s) ORDER BY r.rulename',(oids,)).fetchall()
            foreign=cur.execute('''SELECT ns.nspname AS source_schema,cs.relname AS source,nt.nspname AS target_schema,ct.relname AS target,
                k.confupdtype::text AS update_action,k.confdeltype::text AS delete_action,k.convalidated AS validated,
                ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY x(num,ord) JOIN pg_attribute a ON a.attrelid=cs.oid AND a.attnum=x.num ORDER BY x.ord) AS source_columns,
                ARRAY(SELECT a.attname::text FROM unnest(k.confkey) WITH ORDINALITY x(num,ord) JOIN pg_attribute a ON a.attrelid=ct.oid AND a.attnum=x.num ORDER BY x.ord) AS target_columns
                FROM pg_constraint k JOIN pg_class cs ON cs.oid=k.conrelid JOIN pg_class ct ON ct.oid=k.confrelid JOIN pg_namespace ns ON ns.oid=cs.relnamespace JOIN pg_namespace nt ON nt.oid=ct.relnamespace
                WHERE k.contype='f' AND (k.conrelid=ANY(%s) OR k.confrelid=ANY(%s)) ORDER BY cs.relname,ct.relname,k.conname''',(allowed_oids,allowed_oids)).fetchall()
            functions=cur.execute('''SELECT n.nspname AS schema,p.proname AS name,pg_get_function_identity_arguments(p.oid) AS arguments,
                l.lanname AS language,p.prosecdef AS security_definer,p.proconfig AS config,p.prokind::text AS kind,
                pg_get_function_result(p.oid) AS result,encode(sha256(convert_to(p.prosrc,'UTF8')),'hex') AS body_sha256
                FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
                WHERE p.oid>=16384 AND has_function_privilege(%s,p.oid,'EXECUTE') AND has_schema_privilege(%s,n.oid,'USAGE')
                ORDER BY n.nspname,p.proname,p.oid LIMIT 257''',(ROLE,ROLE)).fetchall()
            require(len(functions)<=256)
            deps=cur.execute('''WITH expression_objects AS (
                SELECT 'pg_attrdef'::regclass AS classid,oid FROM pg_attrdef WHERE adrelid=ANY(%s)
                UNION ALL SELECT 'pg_constraint'::regclass,oid FROM pg_constraint WHERE conrelid=ANY(%s)
                UNION ALL SELECT 'pg_class'::regclass,indexrelid FROM pg_index WHERE indrelid=ANY(%s))
                , expression_dependencies AS (
                    SELECT d.refclassid,d.refobjid FROM expression_objects e JOIN pg_depend d ON d.classid=e.classid AND d.objid=e.oid),
                  reachable_functions AS (
                    SELECT refobjid AS oid FROM expression_dependencies WHERE refclassid='pg_proc'::regclass
                    UNION SELECT o.oprcode FROM expression_dependencies d JOIN pg_operator o ON d.refclassid='pg_operator'::regclass AND d.refobjid=o.oid)
                SELECT DISTINCT n.nspname AS schema,p.proname AS name,(p.oid<16384) AS builtin,p.prosecdef AS security_definer
                FROM reachable_functions f JOIN pg_proc p ON p.oid=f.oid JOIN pg_namespace n ON n.oid=p.pronamespace ORDER BY n.nspname,p.proname''',(allowed_oids,allowed_oids,allowed_oids)).fetchall()
            caps=cur.execute('''SELECT
                (SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid<>ALL(%s)
                 AND n.nspname NOT IN ('pg_catalog','information_schema') AND c.relkind IN ('r','p','v','m','f') AND
                   (has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER') OR has_any_column_privilege(%s,c.oid,'INSERT,UPDATE'))) AS outside_writes,
                (SELECT count(*)::int FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname<>'information_schema' AND has_schema_privilege(%s,n.oid,'CREATE')) AS schema_create,
                has_database_privilege(%s,current_database(),'CREATE') AS database_create,
                has_database_privilege(%s,current_database(),'TEMP') AS database_temp,
                ((SELECT count(*) FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s))+
                 (SELECT count(*) FROM pg_namespace WHERE nspowner=(SELECT oid FROM pg_roles WHERE rolname=%s))+
                 (SELECT count(*) FROM pg_proc WHERE proowner=(SELECT oid FROM pg_roles WHERE rolname=%s)))::int AS owned_objects,
                (SELECT count(*)::int FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)) AS memberships''',(allowed_oids,*(ROLE,)*9)).fetchone()
            end=cur.execute("SELECT current_setting('transaction_read_only') AS readonly,pg_current_xact_id_if_assigned()::text AS xid").fetchone()
            require(end==dict(readonly='on',xid=None))
            catalog=dict(role=role,privileges=list(privileges),tables=actualtables,columns=list(columns),triggers=list(triggers),rules=list(rules),
                foreign_keys=list(foreign),functions=list(functions),expression_functions=list(deps),**caps)
            result=dict(schema=SCHEMA,observed_at=identity['observed'].isoformat(),bucket_key=identity['observed'].astimezone(timezone.utc).date().isoformat(),
                database_role=ROLE,catalog=catalog,catalog_sha256=digest(catalog),server_enforced_read_only=True,xid_assigned=False,
                production_database_writes=0,provider_calls=0,transaction_rolled_back=True)
        connection.rollback();begun=False
        return result
    except Exception:
        raise ValueError('item33_catalog_read_failed') from None
    finally:
        if begun: connection.rollback()


def build_catalog_proof(before,after,*,config,source_sha256):
    proof=dict(schema=PROOF_SCHEMA,source_ref=SOURCE_REF,source_sha256=source_sha256,before=before,after=after,
        business_ddl_count=0,closure='bound_writer_and_exact_catalog',temporary_ddl_capability=before['catalog']['database_temp'])
    verify_catalog_proof(proof,config=config)
    return proof


def verify_catalog_proof(proof,*,config):
    require(isinstance(proof,dict) and set(proof)=={'schema','source_ref','source_sha256','before','after','business_ddl_count','closure','temporary_ddl_capability'})
    require(proof['schema']==PROOF_SCHEMA and proof['source_ref']==SOURCE_REF);dml._sha(proof['source_sha256'])
    require(type(proof['business_ddl_count']) is int and proof['business_ddl_count']==0 and proof['closure']=='bound_writer_and_exact_catalog')
    times=[]
    for facts in (proof['before'],proof['after']):
        require(set(facts)=={'schema','observed_at','bucket_key','database_role','catalog','catalog_sha256','server_enforced_read_only','xid_assigned','production_database_writes','provider_calls','transaction_rolled_back'})
        require(facts['schema']==SCHEMA and facts['bucket_key']==config['bucket_key'] and facts['database_role']==ROLE)
        at=datetime.fromisoformat(facts['observed_at']);require(at.tzinfo is not None and at.utcoffset().total_seconds()==0 and at.date().isoformat()==config['bucket_key']);times.append(at)
        require(facts['server_enforced_read_only'] is True and facts['transaction_rolled_back'] is True and facts['xid_assigned'] is False)
        require(all(type(facts[k]) is int and facts[k]==0 for k in ('production_database_writes','provider_calls')))
        require(facts['catalog_sha256']==digest(facts['catalog'])==config['catalog_before_sha256'])
        require(validate_catalog(facts['catalog'],config=config)==config['installed_definition_sha256'])
    require(times[1]>=times[0] and proof['before']['catalog']==proof['after']['catalog'])
    require(type(proof['temporary_ddl_capability']) is bool and proof['temporary_ddl_capability']==proof['before']['catalog']['database_temp'])
