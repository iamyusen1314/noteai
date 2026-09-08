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
import socket
import struct
import threading
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.rows import tuple_row


PROVIDERS = {"wechatpay_direct", "alipay_direct"}
ALLOWED_TABLES = {
    "credits", "credit_transactions", "payment_orders", "payment_events",
    "payment_cash_ledger", "payment_credit_positions", "payment_entitlement_ledger",
    "payment_refunds", "payment_reconciliation_runs", "payment_reconciliation_items",
    "payment_settlement_summaries", "subscriptions",
}
FUNCTION = "noteai_item31_canary_dml_notice"
TRIGGER = "noteai_item31_canary_dml_notice"
AUTHENTICATED_EVENT = "@authenticated-event"
ORDER_FROM_KEY = "@order/"
ORDER_TABLES = {
    "payment_cash_ledger", "payment_credit_positions", "payment_entitlement_ledger",
    "payment_refunds", "payment_credit_consumptions",
}



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
DECLARE item jsonb; nonce text; provider text; expected text; event_hash text;
BEGIN
  IF current_setting('noteai.item31_activation',true) IS DISTINCT FROM {activation}
  THEN RETURN NULL; END IF;
  nonce := current_setting('noteai.item31_transaction',true);
  provider := current_setting('noteai.item31_provider',true);
  IF coalesce(nonce,'')='' OR coalesce(provider,'') NOT IN ('wechatpay_direct','alipay_direct') THEN
    RAISE EXCEPTION 'item31 transaction binding missing';
  END IF;
  item := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  expected := TG_ARGV[1];
  event_hash := current_setting('noteai.item31_event_hash',true);
  IF expected='@authenticated-event' THEN
    IF TG_TABLE_NAME<>'payment_events' OR TG_ARGV[0]<>'provider_event_id_hash'
       OR coalesce(event_hash,'') !~ '^[0-9a-f]{{64}}$' THEN
      RAISE EXCEPTION 'item31 authenticated event binding missing';
    END IF;
    expected := event_hash;
  ELSIF left(expected,7)='@order/' THEN
    SELECT o.id INTO STRICT expected FROM public.payment_orders o
      WHERE o.idempotency_key_hash=substring(expected from 8)
        AND o.user_id=TG_ARGV[2]
        AND o.provider=current_setting('noteai.item31_provider',true);
  END IF;
  PERFORM pg_notify({channel}, (json_build_object(
    'kind','row','nonce',nonce,'provider',provider,
    'txid',pg_current_xact_id()::text,'pid',pg_backend_pid(),
    'event_id',gen_random_uuid()::text,'table',TG_TABLE_NAME,'op',TG_OP,
    'scope_violation',(item->>TG_ARGV[0]) IS DISTINCT FROM expected
      OR (TG_OP='UPDATE' AND (to_jsonb(OLD)->>TG_ARGV[0]) IS DISTINCT FROM expected)
      OR (TG_TABLE_NAME='payment_orders' AND TG_ARGV[0]='idempotency_key_hash'
          AND coalesce(TG_ARGV[2],'')<>'' AND
          ((item->>'user_id') IS DISTINCT FROM TG_ARGV[2]
           OR (item->>'provider') IS DISTINCT FROM provider
           OR (TG_OP='UPDATE' AND (to_jsonb(OLD)->>'user_id') IS DISTINCT FROM TG_ARGV[2])))
  )::jsonb || CASE WHEN coalesce(event_hash,'')='' THEN '{{}}'::jsonb
       ELSE jsonb_build_object('event_hash',event_hash) END)::text);
  RETURN NULL;
END $notice$;
""").format(activation=sql.Literal(activation), channel=sql.Literal(channel))]
    for table, (column, value) in sorted(targets.items()):
        if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", x) for x in (table, column)):
            raise ValueError("literal identifier required")
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError("bounded target required")
        if value.startswith("@") and not (
            (table == "payment_events" and column == "provider_event_id_hash" and value == AUTHENTICATED_EVENT)
            or (table in ORDER_TABLES and column == "order_id" and value.startswith(ORDER_FROM_KEY)
                and re.fullmatch(r"[0-9a-f]{64}", value[len(ORDER_FROM_KEY):]))
        ):
            raise ValueError("unsupported dynamic canary predicate")
        subject = targets.get("credits", ("", ""))
        if value.startswith(ORDER_FROM_KEY) and (subject[0] != "user_id" or not subject[1]):
            raise ValueError("dynamic order requires reviewed canary subject")
        statements.append(sql.SQL(
            "CREATE TRIGGER {trigger} AFTER INSERT OR UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.{function}({column},{value},{subject})"
        ).format(trigger=sql.Identifier(TRIGGER), table=sql.Identifier(table),
                 function=sql.Identifier(FUNCTION), column=sql.Literal(column),
                 value=sql.Literal(value), subject=sql.Literal(subject[1])))
    return statements


def removal_sql(tables: list[str]) -> list:
    return [sql.SQL("DROP TRIGGER {trigger} ON public.{table}").format(
        trigger=sql.Identifier(TRIGGER), table=sql.Identifier(table),
    ) for table in sorted(tables)] + [sql.SQL(
        "DROP FUNCTION public.noteai_item31_canary_dml_notice()"
    )]


def bind_transaction(cursor, activation: str, provider: str, *, event_hash=None) -> dict:
    """Call inside an explicit writer transaction, before any business DML."""
    if provider not in PROVIDERS:
        raise ValueError("provider")
    if cursor.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("explicit writer transaction required")
    if event_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", event_hash):
        raise ValueError("authenticated event hash")
    nonce = str(uuid.uuid4())
    # Business connections use CompatRow mappings. Keep metadata positional
    # without changing their row factory or consuming a business cursor result.
    with cursor.connection.cursor(row_factory=tuple_row) as metadata:
        metadata.execute("SELECT set_config('noteai.item31_activation',%s,true),"
                         "set_config('noteai.item31_transaction',%s,true),"
                         "set_config('noteai.item31_provider',%s,true)",
                         (_uuid(activation), nonce, provider))
        metadata.execute("SELECT set_config('noteai.item31_event_hash',%s,true)", (event_hash or "",))
        metadata.execute("SELECT pg_backend_pid(),pg_current_xact_id()::text")
        pid, txid = metadata.fetchone()
    return {"nonce": nonce, "provider": provider, "pid": pid, "txid": txid, **({"event_hash": event_hash} if event_hash else {})}


def transaction_complete(cursor, activation: str, binding: dict) -> None:
    """Queue before COMMIT; rolled-back transactions deliver no completion."""
    _validate_binding(binding)
    if cursor.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("explicit writer transaction required")
    with cursor.connection.cursor(row_factory=tuple_row) as metadata:
        metadata.execute("SELECT pg_backend_pid(),pg_current_xact_id()::text,"
                         "current_setting('noteai.item31_activation',true),"
                         "current_setting('noteai.item31_transaction',true),"
                         "current_setting('noteai.item31_provider',true)")
        if metadata.fetchone() != (binding["pid"], binding["txid"], _uuid(activation),
                                   binding["nonce"], binding["provider"]):
            raise ValueError("writer transaction changed")
        metadata.execute("SELECT current_setting('noteai.item31_event_hash',true)")
        if (metadata.fetchone()[0] or "") != binding.get("event_hash", ""):
            raise ValueError("writer event binding changed")
        metadata.execute("SELECT pg_notify(%s,%s)", (channel_for(activation), json.dumps(
            {"kind": "commit", **binding}, sort_keys=True, separators=(",", ":"),
        )))


class CanaryWriter:
    """Explicit payment transaction factory; no global hook or DSN selection.

    The caller supplies a dedicated connection factory and the existing
    db.Transaction type, and serializes access to its CanaryCapture. Every
    invocation binds/registers before yielding any business SQL. A failed
    COMMIT response poisons the capture even if a later rollback succeeds.
    """

    def __init__(self, capture, connect, transaction_type, *, event_hash=None):
        self.capture = capture
        self.connect = connect
        self.transaction_type = transaction_type
        self.event_hash = event_hash
        self.event_resolver = None

    def action(self):
        return self.capture.action()

    def for_event(self, event):
        if self.event_resolver is None:
            return self
        return self.event_resolver(event)

    @contextmanager
    def __call__(self, *, write=False):
        # This only serializes this process; remote writers still require the
        # existing orchestrator's registration/admission protocol.
        with self.capture.lock:
            with self._transaction(write=write) as transaction:
                yield transaction

    @contextmanager
    def _transaction(self, *, write):
        capture = self.capture
        if write is not True or capture.broken or capture.sealing:
            raise ValueError("canary writer unavailable")
        connection = self.connect()
        # A factory returning somebody else's active connection is invalid.
        # Ownership starts only after this check: rejection must not rollback
        # or close that caller's transaction.
        if (not connection.autocommit
                or connection.info.transaction_status != TransactionStatus.IDLE):
            raise ValueError("fresh autocommit writer required")
        registered = False
        commit_started = False
        try:
            connection.execute("BEGIN")
            with connection.cursor() as cursor:
                binding = bind_transaction(cursor, capture.context["activation"],
                                           capture.context["provider"], event_hash=self.event_hash)
            capture.register(binding)
            registered = True
            yield self.transaction_type(connection, postgres=True)
            with connection.cursor() as cursor:
                transaction_complete(cursor, capture.context["activation"], binding)
            commit_started = True
            connection.commit()
        except BaseException:
            if commit_started:
                # No inferred rollback after COMMIT has been sent. The retained
                # journal is incomplete and the next action must not proceed.
                capture.broken = True
            else:
                try:
                    connection.rollback()
                    if connection.info.transaction_status != TransactionStatus.IDLE:
                        raise ValueError("rollback not confirmed")
                    if registered:
                        capture.rolled_back(binding)
                except BaseException:
                    capture.broken = True
            raise
        finally:
            try:
                connection.close()
            except BaseException:
                capture.broken = True
                raise


class CanaryScope:
    """One approved canary subject/key; invoked only after normal authentication.

    The caller injects the existing database's read-only lookup and the same
    capture-backed writer. No environment activation, account selection, DDL,
    provider call or global transaction hook is performed here.
    """

    def __init__(self, writer, fetchone, *, user_id, idempotency_key_hash,
                 app_id, prod_mode, create_context):
        if (not re.fullmatch(r"[0-9a-f]{64}", idempotency_key_hash)
                or type(prod_mode) is not bool or not user_id or not app_id):
            raise ValueError("canary scope")
        self.writer, self.fetchone = writer, fetchone
        self.user_id, self.key_hash = user_id, idempotency_key_hash
        self.app_id, self.prod_mode = app_id, prod_mode
        self.create_context = dict(create_context)
        writer.event_resolver = self.callback

    def __call__(self, event):
        return self.callback(event)

    def action(self):
        return self.writer.capture.action()

    def create(self, context):
        if context != self.create_context:
            raise ValueError("canary create binding")
        return self.writer

    def callback(self, event):
        # Gateway authentication must precede this call. Recheck the trusted
        # event's business identity before its first event INSERT (order_id NULL).
        import payment_contract
        provider = self.writer.capture.context["provider"]
        if (event.provider_name != provider or event.app_id != self.app_id
                or event.prod_mode is not self.prod_mode):
            raise ValueError("canary callback identity")
        if event.event_type in {"payment.succeeded", "payment.failed"}:
            order = self.fetchone("SELECT * FROM payment_orders WHERE merchant_order_no=?",
                                  (event.data.get("order_no"),))
        elif event.event_type in {"refund.succeeded", "refund.failed"}:
            order = self.fetchone(
                "SELECT o.* FROM payment_orders o JOIN payment_refunds r ON r.order_id=o.id "
                "WHERE r.merchant_refund_no=?", (event.data.get("refund_order_no"),),
            )
        else:
            raise ValueError("canary callback event")
        if (not order or order["user_id"] != self.user_id
                or order["idempotency_key_hash"] != self.key_hash
                or order["provider"] != provider
                or order["app_id_hash"] != payment_contract._app_id_hash(self.app_id, provider)
                or order["provider_mode"] != ("live" if self.prod_mode else "mock")
                or order["amount_fen"] != 1200 or order["currency"] != "CNY"):
            raise ValueError("canary callback order")
        digest = hashlib.sha256(("noteai-" + provider + "-event-id-v1").encode()
                                + b"\0" + event.provider_event_id.encode()).hexdigest()
        return CanaryWriter(self.writer.capture, self.writer.connect,
                            self.writer.transaction_type, event_hash=digest)


class CaptureBroker:
    """Explicit, canary-local registration bridge to ONE listener/journal.

    The same UID's API and Payment processes use a private Unix socket. It has
    no remote finish, DDL, SQL, reconnect or provider operation. EOF with a live
    action poisons the existing capture; it never infers successful completion.
    """

    def __init__(self, capture, path: Path):
        self.capture, self.path = capture, path
        self.uid = os.geteuid()
        self.closed = threading.Event()
        self.clients, self.threads = [], []
        self.guard = threading.Lock()
        self.server = None

    def __enter__(self):
        parent = os.lstat(self.path.parent)
        if (self.path.parent != self.capture.path.parent or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != self.uid or stat.S_IMODE(parent.st_mode) != 0o700
                or os.path.lexists(self.path) or not hasattr(socket, "SO_PEERCRED")):
            raise ValueError("private canary socket directory required")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.server.bind(str(self.path))
            os.chmod(self.path, 0o600)
            self.identity = os.lstat(self.path)
            self.server.listen(8)
            self.server.settimeout(0.2)
            self.acceptor = threading.Thread(target=self._accept, daemon=True)
            self.acceptor.start()
            return self
        except BaseException:
            self.server.close()
            raise

    def _accept(self):
        while not self.closed.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != self.uid:
                connection.close()
                continue
            connection.settimeout(3600)  # Existing canary action window maximum.
            thread = threading.Thread(target=self._serve, args=(connection,), daemon=True)
            with self.guard:
                self.clients.append(connection)
                self.threads.append(thread)
            thread.start()

    def _serve(self, connection):
        actions = {}
        stream = connection.makefile("rwb", buffering=0)
        try:
            while not self.closed.is_set():
                raw = stream.readline(4097)
                if not raw:
                    break
                if len(raw) > 4096 or not raw.endswith(b"\n"):
                    raise ValueError("canary message size")
                request = json.loads(raw)
                operation = request.get("operation")
                with self.capture.lock:
                    if operation == "status" and set(request) == {"operation"}:
                        result = {"context": self.capture.context, "broken": self.capture.broken,
                                  "sealing": self.capture.sealing}
                    elif operation == "action_begin" and set(request) == {"operation"}:
                        action = self.capture.action()
                        action.__enter__()
                        token = str(uuid.uuid4())
                        actions[token] = action
                        result = token
                    elif operation == "action_end" and set(request) == {"operation", "token"}:
                        actions.pop(request["token"]).__exit__(None, None, None)
                        result = True
                    elif operation in {"register", "rolled_back"} and set(request) == {"operation", "binding"} and actions:
                        getattr(self.capture, operation)(request["binding"])
                        result = True  # register has fsynced before this ACK.
                    elif operation == "mark_unknown" and set(request) == {"operation"}:
                        self.capture.broken = True
                        result = True
                    else:
                        raise ValueError("canary operation")
                response = json.dumps({"ok": True, "result": result}, separators=(",", ":")).encode() + b"\n"
                connection.sendall(response)
        except BaseException:
            with self.capture.lock:
                self.capture.broken = True
            try:
                connection.sendall(b'{"ok":false}\n')
            except OSError:
                pass
        finally:
            with self.capture.lock:
                if actions:
                    self.capture.broken = True
                for action in actions.values():
                    action.__exit__(None, None, None)
            stream.close()
            connection.close()

    def __exit__(self, *exc):
        self.closed.set()
        self.server.close()
        self.acceptor.join(2)
        with self.guard:
            for connection in self.clients:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            threads = list(self.threads)
        for thread in threads:
            thread.join(2)
            if thread.is_alive():
                self.capture.broken = True
        current = os.lstat(self.path)
        if (current.st_dev, current.st_ino) == (self.identity.st_dev, self.identity.st_ino):
            self.path.unlink()


class CaptureProxy:
    """One unreconnectable process connection; no credentials or SQL on the wire."""

    def __init__(self, path: Path, *, context: dict):
        self.lock = threading.RLock()
        self._broken = False
        self.context = dict(context)
        metadata, parent = os.lstat(path), os.lstat(path.parent)
        if (not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or stat.S_IMODE(parent.st_mode) != 0o700):
            raise ValueError("private canary socket required")
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.settimeout(5)
        self.connection.connect(str(path))
        self.stream = self.connection.makefile("rwb", buffering=0)
        try:
            state = self._call("status")
            if state["context"] != self.context or state["broken"] or state["sealing"]:
                raise ValueError("canary broker binding")
        except BaseException:
            self.close()
            raise

    def _call(self, operation, **fields):
        with self.lock:
            if self._broken:
                raise ValueError("canary broker unavailable")
            try:
                raw = json.dumps({"operation": operation, **fields}, separators=(",", ":")).encode() + b"\n"
                if len(raw) > 4096:
                    raise ValueError("canary request size")
                self.connection.sendall(raw)
                response = self.stream.readline(4097)
                if len(response) > 4096 or not response.endswith(b"\n"):
                    raise ValueError("canary response size")
                value = json.loads(response)
                if set(value) != {"ok", "result"} or value["ok"] is not True:
                    raise ValueError("canary response")
                return value["result"]
            except BaseException:
                self._broken = True
                # Disconnect makes the broker retain an unfinished action as
                # UNKNOWN. No lost ACK is retried and no new connection opens.
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                raise

    @property
    def broken(self):
        return self._broken or self._call("status")["broken"]

    @broken.setter
    def broken(self, value):
        if value is True and not self._broken:
            try:
                self._call("mark_unknown")
            finally:
                self._broken = True

    @property
    def sealing(self):
        return self._call("status")["sealing"]

    def register(self, binding):
        self._call("register", binding=binding)

    def rolled_back(self, binding):
        self._call("rolled_back", binding=binding)

    @contextmanager
    def action(self):
        token = self._call("action_begin")
        try:
            yield
        finally:
            if not self._broken:
                self._call("action_end", token=token)

    def close(self):
        self.stream.close()
        self.connection.close()


class CanaryCapture:
    """One uninterrupted LISTEN connection and one durable local JSONL file.

    No reconnect, replay or inferred rollback. Sender
    PID plus registered transaction/nonce is required; payload/GUC alone is
    not treated as authenticated evidence. All participating DB roles/code
    must be trusted, and live coverage review remains an external prerequisite.
    """

    def __init__(self, listener, control, *, activation: str, targets: dict,
                 provider: str, journal: Path):
        if not listener.autocommit or not control.autocommit:
            raise ValueError("dedicated autocommit connections required")
        self.listener, self.control = listener, control
        self.lock = threading.RLock()
        self.channel = channel_for(activation)
        if provider not in PROVIDERS:
            raise ValueError("provider")
        self.context = {"activation": activation, "coverage_sha256": coverage_sha256(targets),
                        "provider": provider}
        self.bindings, self.terminal = {}, {}
        self.events = set()
        self.broken = False
        self.sealing = False
        self.active_actions = 0
        self.path = journal
        if journal.name.endswith(".incomplete") or os.path.lexists(journal):
            raise ValueError("new final journal path required")
        self.incomplete_path = journal.with_name(journal.name + ".incomplete")
        self.handle = None
        fd = os.open(self.incomplete_path,
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
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

    @contextmanager
    def action(self):
        # Count the whole action, including awaits/provider time; never retain
        # an RLock across an await or a worker-thread handoff.
        with self.lock:
            if self.broken or self.sealing:
                raise ValueError("canary action unavailable")
            self.active_actions += 1
        try:
            yield
        finally:
            with self.lock:
                self.active_actions -= 1

    def _append(self, record: dict) -> None:
        try:
            self.handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except BaseException:
            self.broken = True
            # Keep failed bytes for diagnosis, but never publish this path.
            raise

    def register(self, binding: dict) -> None:
        with self.lock:
            _validate_binding(binding)
            nonce = _uuid(binding["nonce"])
            if (self.broken or self.sealing or nonce in self.bindings
                    or binding["provider"] != self.context["provider"]):
                raise ValueError("writer registration")
            self.bindings[nonce] = dict(binding)
            self._append({"kind": "registered", **binding})

    def rolled_back(self, binding: dict) -> None:
        """Only call after the writer's explicit ROLLBACK has succeeded."""
        with self.lock:
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
            value.get(k) != binding.get(k) for k in ("pid", "txid", "provider", "event_hash")
        ):
            raise ValueError("unregistered notification sender/transaction")
        if value["nonce"] in self.terminal:
            raise ValueError("notification after writer terminal")
        if value.get("kind") == "row":
            if set(value) != {"kind", "nonce", "provider", "pid", "txid", "event_id",
                              "table", "op", "scope_violation"} | ({"event_hash"} if "event_hash" in binding else set()):
                raise ValueError("row fields")
            event_id = _uuid(value["event_id"])
            if event_id in self.events or value["op"] not in {"INSERT", "UPDATE", "DELETE"}:
                raise ValueError("duplicate/invalid row event")
            self.events.add(event_id)
            if value["scope_violation"] is not False or value["table"] not in ALLOWED_TABLES:
                self._append(value)
                raise ValueError("out-of-contract DML")
        elif value.get("kind") == "commit" and {k: v for k, v in value.items() if k != "kind"} == binding:
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
        with self.lock:
            if self.active_actions:
                # This is an early caller error, not loss of the LISTEN stream.
                # Keep the journal open so admitted workers can save results.
                raise ValueError("canary action still in flight")
            try:
                if self.broken or not admission_closed or not self.bindings:
                    raise ValueError("capture incomplete")
                self.sealing = True
                self._barrier("end")
                self.handle.close()
                # Same-directory hard link is an atomic, no-overwrite publication.
                # File data (including end) is already fsynced. A failed fsync can
                # never expose a final path, even if truncation would also fail.
                os.link(self.incomplete_path, self.path, follow_symlinks=False)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                self.incomplete_path.unlink()
                return read_journal(self.path, **self.context)
            except BaseException:
                self.broken = True
                self.handle.close()
                raise


def _validate_binding(binding: dict) -> None:
    if set(binding) not in ({"nonce", "provider", "pid", "txid"}, {"nonce", "provider", "pid", "txid", "event_hash"}):
        raise ValueError("binding fields")
    _uuid(binding["nonce"])
    if "event_hash" in binding and not re.fullmatch(r"[0-9a-f]{64}", binding["event_hash"]):
        raise ValueError("binding event hash")
    if (binding["provider"] not in PROVIDERS or type(binding["pid"]) is not int
            or binding["pid"] <= 0 or not re.fullmatch(r"[1-9][0-9]*", binding["txid"])):
        raise ValueError("binding identity")


def read_journal(path: Path, *, activation: str, coverage_sha256: str, provider: str) -> dict:
    """Read retained bytes; a missing tail stays UNKNOWN, never resumes LISTEN."""
    try:
        if path.name.endswith(".incomplete"):
            raise OSError("unpublished journal")
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
                                 "table", "op", "scope_violation"} | ({"event_hash"} if "event_hash" in pending[nonce] else set())
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
