"""Canary-only PostgreSQL committed-row capture; no automatic installation.

The caller owns the existing canary action journal and must register each API
and Payment writer before admitting work. This module never chooses a user,
opens a DSN, enables a provider, grants a role, or claims terminal acceptance.
Installation is explicit DDL. A disconnected LISTEN stream cannot be resumed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections import Counter
from pathlib import Path

from psycopg import sql
from psycopg.pq import TransactionStatus


PROVIDERS = {"wechatpay_direct", "alipay_direct"}
ALLOWED_TABLES = {
    "credits", "credit_transactions", "payment_orders", "payment_events",
    "payment_cash_ledger", "payment_credit_positions", "payment_entitlement_ledger",
    "payment_refunds", "payment_reconciliation_runs", "payment_reconciliation_items",
    "payment_settlement_summaries", "subscriptions",
}
FUNCTION = "noteai_item31_canary_dml_notice"
TRIGGER = "noteai_item31_canary_dml_notice"


def _uuid(value: str) -> str:
    if str(uuid.UUID(value)) != value:
        raise ValueError("canonical UUID required")
    return value


def channel_for(activation: str) -> str:
    return "noteai_item31_" + _uuid(activation).replace("-", "")


def coverage_sha256(targets: dict) -> str:
    return hashlib.sha256(json.dumps(targets, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def installation_sql(activation: str, targets: dict[str, tuple[str, str]]) -> list:
    """Render explicit, bounded DDL for reviewed table/row predicates.

    Include every reachable table, including forbidden-table sentinels. A
    registered canary transaction writing a different target emits a scope
    violation. Trigger/rule/FK/ACL coverage must be reviewed before live use.
    """
    channel = channel_for(activation)
    if not targets or len(targets) > 20:
        raise ValueError("bounded reviewed coverage required")
    statements = [sql.SQL("""
CREATE FUNCTION public.noteai_item31_canary_dml_notice() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $notice$
DECLARE item jsonb; nonce text; provider text;
BEGIN
  IF current_setting('noteai.item31_activation',true) IS DISTINCT FROM {activation}
  THEN RETURN NULL; END IF;
  nonce := current_setting('noteai.item31_transaction',true);
  provider := current_setting('noteai.item31_provider',true);
  IF coalesce(nonce,'')='' OR coalesce(provider,'') NOT IN ('wechatpay_direct','alipay_direct') THEN
    RAISE EXCEPTION 'item31 transaction binding missing';
  END IF;
  item := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  PERFORM pg_notify({channel}, json_build_object(
    'kind','row','nonce',nonce,'provider',provider,
    'txid',pg_current_xact_id()::text,'pid',pg_backend_pid(),
    'event_id',gen_random_uuid()::text,'table',TG_TABLE_NAME,'op',TG_OP,
    'scope_violation',(item->>TG_ARGV[0]) IS DISTINCT FROM TG_ARGV[1]
      OR (TG_OP='UPDATE' AND (to_jsonb(OLD)->>TG_ARGV[0]) IS DISTINCT FROM TG_ARGV[1])
  )::text);
  RETURN NULL;
END $notice$;
""").format(activation=sql.Literal(activation), channel=sql.Literal(channel))]
    for table, (column, value) in sorted(targets.items()):
        if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", x) for x in (table, column)):
            raise ValueError("literal identifier required")
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError("bounded target required")
        statements.append(sql.SQL(
            "CREATE TRIGGER {trigger} AFTER INSERT OR UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.{function}({column},{value})"
        ).format(trigger=sql.Identifier(TRIGGER), table=sql.Identifier(table),
                 function=sql.Identifier(FUNCTION), column=sql.Literal(column),
                 value=sql.Literal(value)))
    return statements


def removal_sql(tables: list[str]) -> list:
    return [sql.SQL("DROP TRIGGER {trigger} ON public.{table}").format(
        trigger=sql.Identifier(TRIGGER), table=sql.Identifier(table),
    ) for table in sorted(tables)] + [sql.SQL(
        "DROP FUNCTION public.noteai_item31_canary_dml_notice()"
    )]


def bind_transaction(cursor, activation: str, provider: str) -> dict:
    """Call inside an explicit writer transaction, before any business DML."""
    if provider not in PROVIDERS:
        raise ValueError("provider")
    if cursor.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("explicit writer transaction required")
    nonce = str(uuid.uuid4())
    cursor.execute("SELECT set_config('noteai.item31_activation',%s,true),"
                   "set_config('noteai.item31_transaction',%s,true),"
                   "set_config('noteai.item31_provider',%s,true)",
                   (_uuid(activation), nonce, provider))
    cursor.execute("SELECT pg_backend_pid(),pg_current_xact_id()::text")
    pid, txid = cursor.fetchone()
    return {"nonce": nonce, "provider": provider, "pid": pid, "txid": txid}


def transaction_complete(cursor, activation: str, binding: dict) -> None:
    """Queue before COMMIT; rolled-back transactions deliver no completion."""
    _validate_binding(binding)
    if cursor.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("explicit writer transaction required")
    cursor.execute("SELECT pg_backend_pid(),pg_current_xact_id()::text,"
                   "current_setting('noteai.item31_activation',true),"
                   "current_setting('noteai.item31_transaction',true),"
                   "current_setting('noteai.item31_provider',true)")
    if cursor.fetchone() != (binding["pid"], binding["txid"], _uuid(activation),
                             binding["nonce"], binding["provider"]):
        raise ValueError("writer transaction changed")
    cursor.execute("SELECT pg_notify(%s,%s)", (channel_for(activation), json.dumps(
        {"kind": "commit", **binding}, sort_keys=True, separators=(",", ":"),
    )))


class CanaryCapture:
    """One uninterrupted LISTEN connection and one durable local JSONL file.

    No reconnect, replay, inferred rollback or automatic publication. Sender
    PID plus registered transaction/nonce is required; payload/GUC alone is
    not treated as authenticated evidence. All participating DB roles/code
    must be trusted, and live coverage review remains an external prerequisite.
    """

    def __init__(self, listener, control, *, activation: str, targets: dict,
                 provider: str, journal: Path):
        if not listener.autocommit or not control.autocommit:
            raise ValueError("dedicated autocommit connections required")
        self.listener, self.control = listener, control
        self.channel = channel_for(activation)
        if provider not in PROVIDERS:
            raise ValueError("provider")
        self.context = {"activation": activation, "coverage_sha256": coverage_sha256(targets),
                        "provider": provider}
        self.bindings, self.terminal = {}, {}
        self.events = set()
        self.broken = False
        self.sealing = False
        self.path = journal
        self.handle = None
        fd = os.open(journal, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        self.handle = os.fdopen(fd, "w", encoding="utf-8")
        try:
            listener.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self.channel)))
            self.control_pid = control.execute("SELECT pg_backend_pid()").fetchone()[0]
            self._barrier("start")
            directory = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            self.broken = True
            self.handle.close()
            raise

    def _append(self, record: dict) -> None:
        offset = self.handle.tell()
        try:
            self.handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except BaseException:
            self.broken = True
            # Do not leave a failed tail write looking complete on readback.
            try:
                self.handle.seek(offset)
                self.handle.truncate()
                self.handle.flush()
            except OSError:
                pass
            raise

    def register(self, binding: dict) -> None:
        _validate_binding(binding)
        nonce = _uuid(binding["nonce"])
        if (self.broken or self.sealing or nonce in self.bindings
                or binding["provider"] != self.context["provider"]):
            raise ValueError("writer registration")
        self.bindings[nonce] = dict(binding)
        self._append({"kind": "registered", **binding})

    def rolled_back(self, binding: dict) -> None:
        """Only call after the writer's explicit ROLLBACK has succeeded."""
        if (self.broken or self.sealing or self.bindings.get(binding["nonce"]) != binding
                or binding["nonce"] in self.terminal):
            raise ValueError("rollback binding")
        self.terminal[binding["nonce"]] = "rollback"
        self._append({"kind": "rollback", **binding})

    def _consume(self, notification) -> dict:
        if notification.channel != self.channel:
            raise ValueError("notification channel")
        value = json.loads(notification.payload)
        if value.get("kind") in {"start", "end"}:
            if notification.pid != self.control_pid:
                raise ValueError("barrier sender")
            return value
        binding = self.bindings.get(value.get("nonce"))
        if binding is None or notification.pid != binding["pid"] or any(
            value.get(k) != binding[k] for k in ("pid", "txid", "provider")
        ):
            raise ValueError("unregistered notification sender/transaction")
        if value["nonce"] in self.terminal:
            raise ValueError("notification after writer terminal")
        if value.get("kind") == "row":
            if set(value) != {"kind", "nonce", "provider", "pid", "txid", "event_id",
                              "table", "op", "scope_violation"}:
                raise ValueError("row fields")
            event_id = _uuid(value["event_id"])
            if event_id in self.events or value["op"] not in {"INSERT", "UPDATE", "DELETE"}:
                raise ValueError("duplicate/invalid row event")
            self.events.add(event_id)
            if value["scope_violation"] is not False or value["table"] not in ALLOWED_TABLES:
                self._append(value)
                raise ValueError("out-of-contract DML")
        elif value.get("kind") == "commit" and set(value) == {"kind", "nonce", "provider", "pid", "txid"}:
            self.terminal[value["nonce"]] = "commit"
        else:
            raise ValueError("notification kind")
        self._append(value)
        return value

    def _barrier(self, kind: str) -> None:
        marker = {"kind": kind, "token": str(uuid.uuid4()), **self.context}
        self.control.execute("SELECT pg_notify(%s,%s)", (self.channel, json.dumps(marker)))
        try:
            for notification in self.listener.notifies(timeout=5):
                value = self._consume(notification)
                if value == marker:
                    # The tail may not seal before every registered writer is
                    # terminal; admission closure is also required by finish().
                    if kind == "end" and set(self.terminal) != set(self.bindings):
                        raise ValueError("writer still in flight")
                    self._append(marker)
                    return
            raise TimeoutError("notification barrier")
        except BaseException:
            self.broken = True
            raise

    def finish(self, *, admission_closed: bool) -> dict:
        try:
            if self.broken or not admission_closed or not self.bindings:
                raise ValueError("capture incomplete")
            self.sealing = True
            self._barrier("end")
            self.handle.close()
            return read_journal(self.path, **self.context)
        except BaseException:
            self.broken = True
            self.handle.close()
            raise


def _validate_binding(binding: dict) -> None:
    if set(binding) != {"nonce", "provider", "pid", "txid"}:
        raise ValueError("binding fields")
    _uuid(binding["nonce"])
    if (binding["provider"] not in PROVIDERS or type(binding["pid"]) is not int
            or binding["pid"] <= 0 or not re.fullmatch(r"[1-9][0-9]*", binding["txid"])):
        raise ValueError("binding identity")


def read_journal(path: Path, *, activation: str, coverage_sha256: str, provider: str) -> dict:
    """Read retained bytes; a missing tail stays UNKNOWN, never resumes LISTEN."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
                raise OSError("journal size/type")
            raw = handle.read(8 * 1024 * 1024 + 1)
    except OSError:
        return {"status": "UNKNOWN", "write_mutations_by_table": {},
                "write_ledger_readback_sha256": None}
    result = {"status": "UNKNOWN", "write_mutations_by_table": {},
              "write_ledger_readback_sha256": hashlib.sha256(raw).hexdigest()}
    if len(raw) > 8 * 1024 * 1024 or not raw.endswith(b"\n"):
        return result
    try:
        records = [json.loads(line) for line in raw.splitlines()]
        if not records or records[0].get("kind") != "start" or records[-1].get("kind") != "end":
            return result
        for marker in (records[0], records[-1]):
            if (set(marker) != {"kind", "token", "activation", "coverage_sha256", "provider"}
                    or marker["activation"] != activation
                    or marker["coverage_sha256"] != coverage_sha256 or marker["provider"] != provider):
                return result
            _uuid(marker["token"])
        pending, closed, counts, seen, transaction_rows = {}, set(), Counter(), set(), {}
        for row in records[1:-1]:
            nonce = row["nonce"]
            if row["kind"] == "registered":
                binding = {k: v for k, v in row.items() if k != "kind"}
                _validate_binding(binding)
                if binding["provider"] != provider:
                    return result
                if nonce in pending:
                    return result
                pending[nonce] = binding
                transaction_rows[nonce] = Counter()
            elif row["kind"] in {"commit", "rollback"}:
                if nonce not in pending or nonce in closed:
                    return result
                if {k: v for k, v in row.items() if k != "kind"} != pending[nonce]:
                    return result
                if row["kind"] == "rollback" and transaction_rows[nonce]:
                    return result
                counts.update(transaction_rows[nonce])
                closed.add(nonce)
            elif row["kind"] == "row":
                if nonce not in pending or nonce in closed or row["event_id"] in seen:
                    return result
                if row["scope_violation"] is not False or row["table"] not in ALLOWED_TABLES:
                    return result
                if (set(row) != {"kind", "nonce", "provider", "pid", "txid", "event_id",
                                 "table", "op", "scope_violation"}
                        or row["op"] not in {"INSERT", "UPDATE", "DELETE"}
                        or any(row[k] != v for k, v in pending[nonce].items())):
                    return result
                _uuid(row["event_id"])
                seen.add(row["event_id"])
                transaction_rows[nonce][row["table"]] += 1
            else:
                return result
        if not pending or closed != set(pending):
            return result
        result.update(status="CAPTURE_COMPLETE_NOT_TERMINAL", write_mutations_by_table=dict(counts))
    except (ValueError, KeyError, TypeError):
        pass
    return result
