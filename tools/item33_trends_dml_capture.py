"""Item33 row/transaction capture preparation, with no connection or CLI.

SQL is rendered only. The production runner must bind/install it within the
existing authorization and satisfied execution prerequisites, register every
actual writer transaction before DML, continuously consume NOTIFY, and durably
seal the journal. This module cannot prove coverage, stream continuity or zero
DDL, and therefore never produces terminal readiness evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping
import uuid

FUNCTION = "noteai_item33_trends_dml_notice"
TRIGGER = "noteai_item33_trends_dml_notice"
WRITER_ROLE = "noteai_xhs_trends"
TABLE_KEYS = {
    "xhs_trends_runs": ("id",),
    "xhs_trends_service_state": ("service_key",),
    "xhs_trends_provider_attempts": ("id",),
    "hot_keywords": ("id",),
    "keyword_snapshots": ("id",),
    "xhs_crawler_health": ("id",),
    "xhs_freshness_ledger": ("id",),
    "xhs_trends_snapshot_evidence": ("run_id",),
}
FORBIDDEN_GROUPS = frozenset({
    "system_settings", "crawler_events", "tracking", "authentication", "billing", "payment",
})
PACK_TABLES = frozenset({
    "hot_keywords", "keyword_snapshots", "xhs_crawler_health",
    "xhs_freshness_ledger", "xhs_trends_snapshot_evidence",
})
UNPROVEN = (
    "fresh_schema_acl_trigger_rule_fk_coverage",
    "all_writer_registration_and_stream_continuity",
    "durable_journal_start_end_seal",
    "business_ddl_count",
)


@dataclass(frozen=True)
class TableTarget:
    key_columns: tuple[str, ...]
    group: str = "allowed"


def _uuid(value: str) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("canonical capture UUID required")
    return value


def _sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("sha256 required")
    return value


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise ValueError("literal identifier required")
    return value


def _coverage(targets: Mapping[str, TableTarget]) -> dict:
    if not isinstance(targets, Mapping) or not 8 <= len(targets) <= 64:
        raise ValueError("bounded reviewed table coverage required")
    result = {}
    for table, target in sorted(targets.items()):
        _identifier(table)
        if not isinstance(target, TableTarget) or not isinstance(target.key_columns, tuple):
            raise ValueError("table target required")
        if not 1 <= len(target.key_columns) <= 4 or len(set(target.key_columns)) != len(target.key_columns):
            raise ValueError("stable primary key required")
        for column in target.key_columns:
            _identifier(column)
        if target.group not in FORBIDDEN_GROUPS | {"allowed", "out_of_contract"}:
            raise ValueError("table group required")
        if (table in TABLE_KEYS and (target.key_columns != TABLE_KEYS[table] or target.group != "allowed")):
            raise ValueError("Item33 table key contract")
        if table not in TABLE_KEYS and target.group == "allowed":
            raise ValueError("out-of-contract table cannot be allowed")
        result[table] = {"key_columns": list(target.key_columns), "group": target.group}
    if not set(TABLE_KEYS) <= set(result):
        raise ValueError("all eight Item33 tables required")
    if not FORBIDDEN_GROUPS <= {target["group"] for target in result.values()}:
        raise ValueError("all six forbidden groups need reviewed table coverage")
    return result


def coverage_sha256(targets: Mapping[str, TableTarget]) -> str:
    return hashlib.sha256(json.dumps(_coverage(targets), sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def channel_for(activation: str) -> str:
    return "noteai_item33_" + _uuid(activation).replace("-", "")


def schema_guard_sql(targets: Mapping[str, TableTarget]):
    """Reject absent/partitioned tables or a changed primary key before DDL.

    This is a key-shape guard only; it does not certify actual ACL/reachability.
    """
    from psycopg import sql

    coverage = _coverage(targets)
    checks = []
    for table, target in coverage.items():
        checks.append(sql.SQL("""
  SELECT c.oid INTO relation FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relname={table} AND c.relkind='r';
  IF relation IS NULL THEN RAISE EXCEPTION 'item33 table shape'; END IF;
  SELECT array_agg(a.attname::text ORDER BY k.ordinality) INTO actual_keys
    FROM pg_catalog.pg_index i
    CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,ordinality)
    JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
    WHERE i.indrelid=relation AND i.indisprimary AND i.indisvalid AND a.attnotnull;
  IF actual_keys IS DISTINCT FROM {keys}::text[] THEN
    RAISE EXCEPTION 'item33 primary key shape';
  END IF;
""").format(table=sql.Literal(table), keys=sql.Literal(target["key_columns"])))
    return sql.SQL("DO $guard$ DECLARE relation oid; actual_keys text[]; BEGIN {} END $guard$").format(
        sql.SQL("\n").join(checks))


FUNCTION_SQL_TEMPLATE = """CREATE FUNCTION public.{function}() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $notice$
DECLARE old_item jsonb; new_item jsonb; old_key jsonb; new_key jsonb;
        nonce text; run_hash text; old_hash text; new_hash text;
        violation boolean; succeeded boolean; run_column text;
BEGIN
  IF session_user <> {role} THEN RETURN NULL; END IF;
  nonce := current_setting('noteai.item33_transaction',true);
  run_hash := current_setting('noteai.item33_run_sha256',true);
  IF current_setting('noteai.item33_activation',true) IS DISTINCT FROM {activation}
     OR coalesce(nonce,'') !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
     OR coalesce(run_hash,'') !~ '^[0-9a-f]{{64}}$' THEN
    RAISE EXCEPTION 'item33 transaction binding missing';
  END IF;
  violation := TG_ARGV[1] <> 'allowed';
  succeeded := false;
  IF TG_OP <> 'TRUNCATE' THEN
    IF TG_OP <> 'INSERT' THEN old_item := to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN new_item := to_jsonb(NEW); END IF;
    SELECT jsonb_agg(old_item->key ORDER BY ord), jsonb_agg(new_item->key ORDER BY ord)
      INTO old_key,new_key FROM unnest(TG_ARGV[0]::text[]) WITH ORDINALITY k(key,ord);
    IF (old_item IS NOT NULL AND EXISTS(SELECT 1 FROM jsonb_array_elements(old_key) v WHERE v='null'::jsonb))
       OR (new_item IS NOT NULL AND EXISTS(SELECT 1 FROM jsonb_array_elements(new_key) v WHERE v='null'::jsonb)) THEN
      RAISE EXCEPTION 'item33 row identity missing';
    END IF;
    IF old_item IS NOT NULL THEN
      old_hash := encode(sha256(convert_to(jsonb_build_array({activation},TG_TABLE_NAME,old_key)::text,'UTF8')),'hex');
    END IF;
    IF new_item IS NOT NULL THEN
      new_hash := encode(sha256(convert_to(jsonb_build_array({activation},TG_TABLE_NAME,new_key)::text,'UTF8')),'hex');
    END IF;
    IF TG_OP='UPDATE' AND old_key IS DISTINCT FROM new_key THEN violation := true; END IF;
    run_column := CASE WHEN TG_TABLE_NAME='xhs_trends_runs' THEN 'id'
      WHEN TG_TABLE_NAME IN ('xhs_trends_provider_attempts','xhs_trends_snapshot_evidence') THEN 'run_id' ELSE NULL END;
    IF run_column IS NOT NULL THEN
      violation := violation OR
        (old_item IS NOT NULL AND encode(sha256(convert_to(old_item->>run_column,'UTF8')),'hex') IS DISTINCT FROM run_hash)
        OR (new_item IS NOT NULL AND encode(sha256(convert_to(new_item->>run_column,'UTF8')),'hex') IS DISTINCT FROM run_hash);
    END IF;
    IF TG_TABLE_NAME='xhs_trends_service_state' THEN
      violation := violation OR coalesce(new_item,old_item)->>'service_key' IS DISTINCT FROM 'market_timing';
    END IF;
    succeeded := TG_TABLE_NAME='xhs_trends_runs' AND TG_OP='UPDATE'
      AND new_item->>'status'='succeeded' AND old_item->>'status' IS DISTINCT FROM 'succeeded';
  END IF;
  {counter}
  PERFORM pg_notify({channel}, json_build_object(
    'kind','mutation','activation',{activation},'coverage_sha256',{coverage},
    'nonce',nonce,'run_identity_sha256',run_hash,'pid',pg_backend_pid(),
    'txid',pg_current_xact_id()::text,'event_id',gen_random_uuid()::text,
    'table',TG_TABLE_NAME,'op',TG_OP,'old_row_sha256',old_hash,'new_row_sha256',new_hash,
    'scope_violation',violation,'run_succeeded',coalesce(succeeded,false))::text);
  RETURN NULL;
END $notice$;"""

COUNTER_SQL = """
  IF coalesce(current_setting('noteai.item33_mutation_count',true),'') !~ '^[0-9]{1,5}$'
     OR current_setting('noteai.item33_mutation_count',true)::integer >= 32768 THEN
    RAISE EXCEPTION 'item33 mutation count binding missing';
  END IF;
  PERFORM set_config('noteai.item33_mutation_count',
    (current_setting('noteai.item33_mutation_count',true)::integer + 1)::text,true);
"""

def function_sql_text(activation, targets, *, mutation_counts=False):
    if type(mutation_counts) is not bool: raise ValueError("mutation count mode")
    values = dict(function='"' + FUNCTION + '"', role="'" + WRITER_ROLE + "'",
        activation="'" + _uuid(activation) + "'", channel="'" + channel_for(activation) + "'",
        coverage="'" + coverage_sha256(targets) + "'", counter=COUNTER_SQL if mutation_counts else "")
    return FUNCTION_SQL_TEMPLATE.format(**values)

def function_body(activation, targets, *, mutation_counts=False):
    return function_sql_text(activation, targets, mutation_counts=mutation_counts).split("$notice$")[1]


def installation_sql(activation: str, targets: Mapping[str, TableTarget], *,
                     mutation_counts: bool = False) -> list:
    """Render independent Item33 triggers; never execute or replace an object.

    Missing writer transaction binding raises, including writes caused by nested
    triggers. Only the exact session role is observed; that role/ACL and all
    reachable relations must be independently verified before installation.
    """
    from psycopg import sql

    if type(mutation_counts) is not bool:
        raise ValueError("mutation count mode")
    channel = channel_for(activation)
    coverage = _coverage(targets)
    digest = coverage_sha256(targets)
    statements = [schema_guard_sql(targets), sql.SQL(function_sql_text(activation, targets, mutation_counts=mutation_counts))]
    for table, target in coverage.items():
        for level, operations, suffix in (("ROW", "INSERT OR UPDATE OR DELETE", ""),
                                          ("STATEMENT", "TRUNCATE", "_truncate")):
            statements.append(sql.SQL(
                "CREATE TRIGGER {trigger} AFTER {operations} ON public.{table} "
                "FOR EACH {level} EXECUTE FUNCTION public.{function}({keys},{group})"
            ).format(trigger=sql.Identifier(TRIGGER + suffix), operations=sql.SQL(operations),
                     table=sql.Identifier(table), level=sql.SQL(level), function=sql.Identifier(FUNCTION),
                     keys=sql.Literal("{" + ",".join(target["key_columns"]) + "}"), group=sql.Literal(target["group"])))
    return statements


def removal_sql(targets: Mapping[str, TableTarget]) -> list:
    """Render only; the runner must first bind installed definitions/activation."""
    from psycopg import sql

    coverage = _coverage(targets)
    return [sql.SQL("DROP TRIGGER {trigger} ON public.{table}").format(
        trigger=sql.Identifier(TRIGGER + suffix), table=sql.Identifier(table))
        for table in coverage for suffix in ("", "_truncate")] + [
        sql.SQL("DROP FUNCTION public.{}()").format(sql.Identifier(FUNCTION))]


def binding_sql(activation: str, nonce: str, run_identity_sha256: str, *,
                mutation_counts: bool = False) -> list:
    """SET LOCAL only: execute in an explicit writer BEGIN, then register metadata.

    The caller must register returned actual pid/txid before yielding business
    SQL. Calling in autocommit loses the local binding and later DML fails.
    """
    from psycopg import sql

    if type(mutation_counts) is not bool:
        raise ValueError("mutation count mode")
    values = (_uuid(activation), _uuid(nonce), _sha(run_identity_sha256))
    statements = [sql.SQL("SELECT set_config('noteai.item33_activation',{},true),"
                    "set_config('noteai.item33_transaction',{},true),"
                    "set_config('noteai.item33_run_sha256',{},true)").format(
                        *(sql.Literal(value) for value in values))]
    if mutation_counts:
        statements.append(sql.SQL("SELECT set_config('noteai.item33_mutation_count','0',true)"))
    statements.append(sql.SQL("SELECT pg_backend_pid(),pg_current_xact_id()::text"))
    return statements


def completion_sql(activation: str, binding: dict, *, mutation_counts: bool = False):
    """A bound commit notice queued before COMMIT; rollback delivers no notice."""
    from psycopg import sql

    if type(mutation_counts) is not bool:
        raise ValueError("mutation count mode")
    _validate_binding(binding)
    payload = json.dumps({"kind": "commit", **binding}, sort_keys=True, separators=(",", ":"))
    return sql.SQL("""DO $complete$ BEGIN
  IF session_user <> {role} OR pg_backend_pid() <> {pid}
    OR pg_current_xact_id()::text <> {txid}
    OR current_setting('noteai.item33_activation',true) IS DISTINCT FROM {activation}
    OR current_setting('noteai.item33_transaction',true) IS DISTINCT FROM {nonce}
    OR current_setting('noteai.item33_run_sha256',true) IS DISTINCT FROM {run_hash}
  THEN RAISE EXCEPTION 'item33 writer transaction changed'; END IF;
  {counter_guard}
  PERFORM pg_notify({channel},{payload}); END $complete$;""").format(
        role=sql.Literal(WRITER_ROLE), pid=sql.Literal(binding["pid"]), txid=sql.Literal(binding["txid"]),
        activation=sql.Literal(_uuid(activation)), nonce=sql.Literal(binding["nonce"]),
        run_hash=sql.Literal(binding["run_identity_sha256"]),
        channel=sql.Literal(channel_for(activation)),
        counter_guard=sql.SQL("""
  IF coalesce(current_setting('noteai.item33_mutation_count',true),'') !~ '^[0-9]{1,5}$'
     OR current_setting('noteai.item33_mutation_count',true)::integer > 32768 THEN
    RAISE EXCEPTION 'item33 mutation count binding missing';
  END IF;
""" if mutation_counts else ""),
        payload=(sql.SQL("({}::jsonb || jsonb_build_object('mutation_count',"
                         "current_setting('noteai.item33_mutation_count',true)::integer))::text").format(
                             sql.Literal(payload)) if mutation_counts else sql.Literal(payload)))


def _validate_binding(binding: dict) -> None:
    if set(binding) != {"nonce", "run_identity_sha256", "pid", "txid"}:
        raise ValueError("writer binding fields")
    _uuid(binding["nonce"])
    _sha(binding["run_identity_sha256"])
    if type(binding["pid"]) is not int or binding["pid"] <= 0:
        raise ValueError("writer pid")
    if not isinstance(binding["txid"], str) or not re.fullmatch(r"[1-9][0-9]*", binding["txid"]):
        raise ValueError("writer txid")


def aggregate_records(records: list[dict], *, activation: str,
                      targets: Mapping[str, TableTarget], run_identity_sha256: str,
                      require_mutation_count: bool = False) -> dict:
    """Aggregate trusted transport records, never certify a production capture.

    `registered`/`rollback` come from the separate durable writer protocol.
    Notifications add `sender_pid` from PostgreSQL's actual notification object,
    never from its payload. Missing registrations/terminals and duplicate or
    unbound events remain UNKNOWN. Legacy mode cannot detect a missing individual mutation. Counted mode
    compares the transaction-local trigger counter with delivered mutations. A forged
    notice from the already-bound backend still requires source/transport trust;
    actual writer-source binding and continuous capture remain prerequisites.
    """
    if type(require_mutation_count) is not bool:
        raise ValueError("mutation count mode")
    context = (_uuid(activation), coverage_sha256(targets), _sha(run_identity_sha256))
    coverage = _coverage(targets)
    unknown = {"status": "UNKNOWN", "unproven": list(UNPROVEN), "readiness_credit": False}
    try:
        if not isinstance(records, list) or not 1 <= len(records) <= 32768:
            raise ValueError("bounded records required")
        bindings, closed, events, rows = {}, set(), set(), []
        seen_transactions = set()
        for record in records:
            kind, nonce = record["kind"], record["nonce"]
            if kind == "registered":
                binding = {key: value for key, value in record.items() if key != "kind"}
                _validate_binding(binding)
                if nonce in bindings or binding["txid"] in seen_transactions or binding["run_identity_sha256"] != context[2]:
                    raise ValueError("duplicate or wrong writer")
                bindings[nonce] = binding
                seen_transactions.add(binding["txid"])
                continue
            if nonce not in bindings or nonce in closed:
                raise ValueError("unregistered or closed writer")
            binding = bindings[nonce]
            if any(record.get(key) != value for key, value in binding.items()):
                raise ValueError("writer mismatch")
            if kind in {"commit", "rollback"}:
                expected = {"kind", *binding} | ({"sender_pid"} if kind == "commit" else set())
                if kind == "commit" and require_mutation_count:
                    expected.add("mutation_count")
                if set(record) != expected or (kind == "commit" and record["sender_pid"] != binding["pid"]):
                    raise ValueError("terminal binding")
                if kind == "commit" and require_mutation_count:
                    count = record.get("mutation_count")
                    if (type(count) is not int or not 0 <= count <= 32768
                            or count != sum(row["nonce"] == nonce for row in rows)):
                        raise ValueError("committed mutation count mismatch")
                if kind == "rollback" and any(row["nonce"] == nonce for row in rows):
                    raise ValueError("rolled back notification")
                closed.add(nonce)
                continue
            if kind != "mutation" or set(record) != {
                "kind", *binding, "sender_pid", "activation", "coverage_sha256", "event_id", "table", "op",
                "old_row_sha256", "new_row_sha256", "scope_violation", "run_succeeded",
            }:
                raise ValueError("mutation fields")
            if record["sender_pid"] != binding["pid"] or (record["activation"], record["coverage_sha256"]) != context[:2]:
                raise ValueError("mutation context")
            event = _uuid(record["event_id"])
            if event in events or record["table"] not in coverage:
                raise ValueError("duplicate or uncovered event")
            events.add(event)
            operation = record["op"]
            if operation not in {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}:
                raise ValueError("mutation operation")
            for key, present in (("old_row_sha256", operation in {"UPDATE", "DELETE"}),
                                 ("new_row_sha256", operation in {"INSERT", "UPDATE"})):
                if present:
                    _sha(record[key])
                elif record[key] is not None:
                    raise ValueError("row identity shape")
            if any(type(record[key]) is not bool for key in ("scope_violation", "run_succeeded")):
                raise ValueError("mutation flag")
            if record["run_succeeded"] and (record["table"] != "xhs_trends_runs" or operation != "UPDATE"):
                raise ValueError("run success shape")
            rows.append(record)
        if not bindings or closed != set(bindings):
            raise ValueError("writer missing terminal")
    except (ValueError, KeyError, TypeError, AttributeError):
        return unknown

    distinct, mutations, transaction_tables = defaultdict(set), Counter(), defaultdict(Counter)
    forbidden = dict.fromkeys(sorted(FORBIDDEN_GROUPS), 0)
    out_of_contract = delete_rows = truncate_count = 0
    success_transactions, attempt_transactions, pack_transactions = [], set(), set()
    for row in rows:
        table, txid, operation = row["table"], row["txid"], row["op"]
        mutations[table] += 1
        transaction_tables[txid][table] += 1
        for key in ("old_row_sha256", "new_row_sha256"):
            if row[key] is not None:
                distinct[table].add(row[key])
        group = coverage[table]["group"]
        if group in forbidden:
            forbidden[group] += 1
        out_of_contract += int(group != "allowed" or row["scope_violation"] or (
            operation == "UPDATE" and row["old_row_sha256"] != row["new_row_sha256"]))
        delete_rows += int(operation == "DELETE")
        truncate_count += int(operation == "TRUNCATE")
        if row["run_succeeded"]:
            success_transactions.append(txid)
        if table == "xhs_trends_provider_attempts":
            attempt_transactions.add(txid)
        if table in PACK_TABLES:
            pack_transactions.add(txid)
    single_publish = (len(success_transactions) == 1 and pack_transactions == set(success_transactions)
                      and PACK_TABLES <= set(transaction_tables[success_transactions[0]]))
    atomic = {
        "business_pack_snapshot_run_success_one_transaction": single_publish,
        "attempt_audit_outside_transaction": bool(attempt_transactions) and single_publish
            and not attempt_transactions.intersection(pack_transactions),
    }
    return {
        "status": "ROW_CAPTURE_AGGREGATED_NOT_TERMINAL", "readiness_credit": False,
        "unproven": list(UNPROVEN), "coverage_sha256": context[1],
        "distinct_rows_touched_by_table": {table: len(distinct[table]) for table in sorted(coverage)},
        "write_mutations_by_table": dict(sorted(mutations.items())),
        "transactions": {txid: dict(sorted(counts.items())) for txid, counts in sorted(transaction_tables.items())},
        "out_of_contract_row_mutations": out_of_contract,
        "delete_rows": delete_rows, "truncate_count": truncate_count,
        "forbidden_table_mutations": forbidden, "atomic_publish": atomic,
    }


def cycle_contract_errors(result: dict, *, request_count: int, keyword_count: int) -> list[str]:
    """Check the existing row/atomic subset; absent DDL/stream proof stays absent."""
    if type(request_count) is not int or not 1 <= request_count <= 34 or type(keyword_count) is not int or not 72 <= keyword_count <= 90:
        raise ValueError("bounded real cycle counts required")
    if result.get("status") != "ROW_CAPTURE_AGGREGATED_NOT_TERMINAL":
        return ["capture_unknown"]
    expected = dict.fromkeys(TABLE_KEYS, 1)
    expected.update(xhs_trends_provider_attempts=request_count, hot_keywords=keyword_count,
                    keyword_snapshots=keyword_count, xhs_crawler_health=6, xhs_freshness_ledger=6)
    rows = result.get("distinct_rows_touched_by_table", {})
    errors = []
    if any(type(rows.get(table)) is not int or rows[table] != count for table, count in expected.items()):
        errors.append("distinct_row_counts")
    for key in ("out_of_contract_row_mutations", "delete_rows", "truncate_count"):
        if type(result.get(key)) is not int or result[key] != 0:
            errors.append(key)
    if result.get("forbidden_table_mutations") != dict.fromkeys(sorted(FORBIDDEN_GROUPS), 0):
        errors.append("forbidden_table_mutations")
    if result.get("atomic_publish") != {
        "business_pack_snapshot_run_success_one_transaction": True,
        "attempt_audit_outside_transaction": True,
    }:
        errors.append("atomic_publish")
    return errors
