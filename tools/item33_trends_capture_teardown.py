"""Guarded, activation-specific capture teardown SQL and readback verification.

This module never connects or executes SQL. A once-only operator wrapper must
retain the real successful transaction receipt; UNKNOWN is read back, not replayed.
Business data/schema/ACL are not changed by the generated temporary-object DROP.
"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json

try:
    from tools import item33_trends_capture_catalog as catalog
    from tools import item33_trends_dml_capture as dml
    from tools import item33_trends_runtime_capture as runtime
except ModuleNotFoundError:
    import item33_trends_capture_catalog as catalog
    import item33_trends_dml_capture as dml
    import item33_trends_runtime_capture as runtime

SOURCE_REF = 'tools/item33_trends_capture_teardown.py'
PROOF_REF = 'deploy/production/evidence/production-item33-trends-capture-teardown.json'
SCHEMA = 'noteai.item33.capture_teardown.v1'
EXECUTION_SCHEMA = 'noteai.item33.capture_teardown_execution.v1'
FACT_KEYS = {'schema','observed_at','bucket_key','database_role','catalog','catalog_sha256',
             'server_enforced_read_only','xid_assigned','production_database_writes','provider_calls','transaction_rolled_back'}


def require(value):
    if not value:
        raise ValueError('item33_capture_teardown_unproven')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


SCHEMA_CHECK = "\n  SELECT c.oid INTO relation FROM pg_catalog.pg_class c\n    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace\n    WHERE n.nspname='public' AND c.relname={table} AND c.relkind='r';\n  IF relation IS NULL THEN RAISE EXCEPTION 'item33 table shape'; END IF;\n  SELECT array_agg(a.attname::text ORDER BY k.ordinality) INTO actual_keys\n    FROM pg_catalog.pg_index i\n    CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,ordinality)\n    JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum\n    WHERE i.indrelid=relation AND i.indisprimary AND i.indisvalid AND a.attnotnull;\n  IF actual_keys IS DISTINCT FROM {keys}::text[] THEN\n    RAISE EXCEPTION 'item33 primary key shape';\n  END IF;\n"
SCHEMA_GUARD = 'DO $guard$ DECLARE relation oid; actual_keys text[]; BEGIN {} END $guard$'


def _identifier(*parts):
    return '.'.join('"' + dml._identifier(part) + '"' for part in parts)


def _literal(value):
    if isinstance(value, (list, tuple)):
        return 'ARRAY[' + ','.join(_literal(item) for item in value) + ']'
    require(isinstance(value, str) and '\x00' not in value)
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _schema_guard(targets):
    coverage = dml._coverage(targets)
    checks = [SCHEMA_CHECK.format(table=_literal(table), keys=_literal(target['key_columns']))
              for table, target in coverage.items()]
    return SCHEMA_GUARD.format('\n'.join(checks))


def _removal_statements(targets):
    return ['DROP TRIGGER ' + _identifier(dml.TRIGGER + suffix) + ' ON ' + _identifier('public', table)
            for table in dml._coverage(targets) for suffix in ('', '_truncate')] + [
                'DROP FUNCTION ' + _identifier('public', dml.FUNCTION) + '()']


def _config(seal):
    value = {key: seal[key] for key in runtime.CONFIG_KEYS - {'schema', 'socket_path'}}
    value.update(schema=runtime.CONFIG_SCHEMA, socket_path=runtime.SOCKET_PATH)
    runtime.validate_config(value)
    return value


def _targets(seal):
    return catalog.targets_from(_config(seal))


def _without_capture(value):
    result = copy.deepcopy(value)
    result['triggers'] = [item for item in result['triggers']
                          if not (item['function_schema'] == 'public' and item['function'] == dml.FUNCTION)]
    result['functions'] = [item for item in result['functions']
                           if not (item['schema'] == 'public' and item['name'] == dml.FUNCTION)]
    return result


def _clock(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0)
    return parsed


def _facts(value, bucket):
    require(isinstance(value, dict) and set(value) == FACT_KEYS and value['schema'] == catalog.SCHEMA)
    require(value['bucket_key'] == bucket and _clock(value['observed_at']).date().isoformat() == bucket)
    require(value['database_role'] == dml.WRITER_ROLE and value['server_enforced_read_only'] is True
            and value['transaction_rolled_back'] is True and value['xid_assigned'] is False)
    require(all(type(value[key]) is int and value[key] == 0 for key in ('production_database_writes','provider_calls')))
    require(value['catalog_sha256'] == catalog.digest(value['catalog']))


def render_teardown_sql(*, seal, journal: bytes, operator_role: str) -> str:
    """Generate only after original seal/journal/catalog verification succeeds."""
    runtime.verify_capture_artifacts(seal, journal, require_terminal_proofs=True)
    return _render_removal_sql(_config(seal), seal['catalog_proof']['after']['catalog'], operator_role)


def render_pre_cycle_cleanup_sql(*, config: dict, installed_catalog: dict, operator_role: str) -> str:
    """Recovery-only SQL; caller separately proves stopped worker/collector.

    This does not produce a terminal/cycle proof. The original installation and
    failure records remain retained. SQL checks zero actual bucket admissions
    while all covered tables are locked, before dropping exact capture objects.
    """
    runtime.validate_config(config)
    _facts(installed_catalog, config['bucket_key'])
    require(installed_catalog['catalog_sha256'] == config['catalog_before_sha256'])
    return _render_removal_sql(config, installed_catalog['catalog'], operator_role, pre_cycle=True)


def _render_removal_sql(config, before, operator_role, *, pre_cycle=False):
    operator_role = dml._identifier(operator_role)
    require(operator_role != dml.WRITER_ROLE)
    targets = catalog.targets_from(config)
    catalog.validate_catalog(before, config=config)
    body = dml.function_body(config['activation_id'], targets, mutation_counts=True)
    function = next(item for item in before['functions'] if item['schema'] == 'public' and item['name'] == dml.FUNCTION)
    triggers = [item for item in before['triggers'] if item['function_schema'] == 'public' and item['function'] == dml.FUNCTION]
    expected_rows = sorted([{key: item[key] for key in ('table','name','enabled','internal','type','arguments_hex','definition_sha256')}
                            for item in triggers], key=lambda item: (item['table'], item['name']))
    guard = str('''DO $item33_teardown$ DECLARE actual jsonb; BEGIN
 IF session_user <> {role} OR current_user <> {role} THEN RAISE EXCEPTION 'item33 operator identity'; END IF;
 SELECT jsonb_build_object('schema',n.nspname,'name',p.proname,'arguments',pg_get_function_identity_arguments(p.oid),
   'language',l.lanname,'security_definer',p.prosecdef,'config',p.proconfig,'kind',p.prokind::text,
   'result',pg_get_function_result(p.oid),'body_sha256',encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')) INTO actual
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
 WHERE n.nspname='public' AND p.proname={function};
 IF actual IS DISTINCT FROM {expected_function}::jsonb OR
    (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
     WHERE n.nspname='public' AND p.proname={function}) <> 1 OR
    (SELECT p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
     WHERE n.nspname='public' AND p.proname={function}) IS DISTINCT FROM {body}
 THEN RAISE EXCEPTION 'item33 installed function changed'; END IF;
 SELECT jsonb_agg(jsonb_build_object('table',c.relname,'name',t.tgname,'enabled',t.tgenabled::text,
   'internal',t.tgisinternal,'type',t.tgtype::int,'arguments_hex',encode(t.tgargs,'hex'),
   'definition_sha256',encode(sha256(convert_to(pg_get_triggerdef(t.oid),'UTF8')),'hex')) ORDER BY c.relname,t.tgname)
 INTO actual FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace r ON r.oid=c.relnamespace
 JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.proname={function};
 IF actual IS DISTINCT FROM {expected_triggers}::jsonb OR EXISTS(
   SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace r ON r.oid=c.relnamespace
   JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='public' AND p.proname={function} AND r.nspname<>'public')
 THEN RAISE EXCEPTION 'item33 installed triggers changed'; END IF;
 END $item33_teardown$''').format(role=_literal(operator_role), function=_literal(dml.FUNCTION),
    expected_function=_literal(encoded(function).decode()), body=_literal(body),
    expected_triggers=_literal(encoded(expected_rows).decode()))
    residual = str('''DO $item33_removed$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='public' AND p.proname={function}) OR EXISTS(
    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relname=ANY({tables}) AND t.tgname IN ({row_trigger},{truncate_trigger}))
 THEN RAISE EXCEPTION 'item33 capture residual'; END IF;
 END $item33_removed$''').format(function=_literal(dml.FUNCTION), tables=_literal(sorted(targets)),
     row_trigger=_literal(dml.TRIGGER), truncate_trigger=_literal(dml.TRIGGER + '_truncate'))
    lock = str('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE NOWAIT').format(
        str(',').join(_identifier('public', name) for name in sorted(targets)))
    zero_guard = str("""DO $item33_pre_cycle$ BEGIN
 IF EXISTS(SELECT 1 FROM public.xhs_trends_runs WHERE bucket_key={bucket}) OR
    EXISTS(SELECT 1 FROM public.xhs_trends_provider_attempts
      WHERE admitted_at >= {bucket}::date AND admitted_at < {bucket}::date + 1) OR
    EXISTS(SELECT 1 FROM public.xhs_trends_runs WHERE status IN ('running','needs_manual')) OR
    EXISTS(SELECT 1 FROM public.xhs_trends_provider_attempts WHERE status IN ('admitted','outcome_unknown'))
 THEN RAISE EXCEPTION 'item33 pre-cycle zero activity required'; END IF;
 END $item33_pre_cycle$""").format(bucket=_literal(config['bucket_key']))
    statements = [str('BEGIN'), str("SET LOCAL lock_timeout='5000ms'"),
        str("SET LOCAL statement_timeout='15000ms'"), str("SET LOCAL TIME ZONE 'UTC'"),
        lock, _schema_guard(targets), guard,
        *([zero_guard] if pre_cycle else []), *_removal_statements(targets), residual, str('COMMIT')]
    return '\n'.join(item.rstrip(';') + ';' for item in statements) + '\n'


def build_teardown_proof(*, seal_raw: bytes, journal: bytes, after: dict, execution: dict, source_sha256: str) -> dict:
    seal = json.loads(seal_raw)
    require(isinstance(execution, dict) and set(execution) == {'schema','status','activation_identity_sha256',
        'operator_role','sql_sha256','started_at','committed_at','control_plane_ddl_count','outcome_unknown_count'})
    script = render_teardown_sql(seal=seal, journal=journal, operator_role=execution['operator_role'])
    before = seal['catalog_proof']['after']
    require(execution['schema'] == EXECUTION_SCHEMA and execution['status'] == 'COMMITTED')
    require(execution['activation_identity_sha256'] == seal['activation_identity_sha256'])
    require(execution['sql_sha256'] == hashlib.sha256(script.encode()).hexdigest())
    count = 2 * len(_targets(seal)) + 1
    require(type(execution['control_plane_ddl_count']) is int and execution['control_plane_ddl_count'] == count)
    require(type(execution['outcome_unknown_count']) is int and execution['outcome_unknown_count'] == 0)
    _facts(before, seal['bucket_key']); _facts(after, seal['bucket_key'])
    require(_clock(before['observed_at']) <= _clock(execution['started_at']) <= _clock(execution['committed_at']) <= _clock(after['observed_at']))
    require(_clock(execution['started_at']).date().isoformat() == _clock(execution['committed_at']).date().isoformat() == seal['bucket_key'])
    require(after['catalog'] == _without_capture(before['catalog']))
    dml._sha(source_sha256)
    return dict(schema=SCHEMA,status='VERIFIED',activation_identity_sha256=seal['activation_identity_sha256'],
        run_identity_sha256=seal['run_identity_sha256'],bucket_key=seal['bucket_key'],config_sha256=seal['config_sha256'],
        capture_receipt_sha256=hashlib.sha256(seal_raw).hexdigest(),source_ref=SOURCE_REF,source_sha256=source_sha256,
        operator_role=execution['operator_role'],sql_sha256=execution['sql_sha256'],control_plane_ddl_count=count,
        execution=copy.deepcopy(execution),before=copy.deepcopy(before),after=copy.deepcopy(after))


def verify_teardown_proof(proof, *, seal_raw: bytes, journal: bytes, source_sha256: str) -> None:
    require(isinstance(proof, dict))
    expected = build_teardown_proof(seal_raw=seal_raw,journal=journal,after=proof.get('after'),
                                   execution=proof.get('execution'),source_sha256=source_sha256)
    require(proof == expected)
