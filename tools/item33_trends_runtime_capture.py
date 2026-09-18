"""One Item33 activation's writer/listener handoff; never a standalone promotion.

Import opens no connection or service. The host supplies existing autocommit
listener/control connections after installing the separately bound capture SQL.
The worker entry only wraps the eight unchanged accepted sources in memory.
"""
from __future__ import annotations

from collections import Counter
from contextlib import suppress
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys
import threading
import time
import uuid

try:
    from tools import item33_trends_dml_capture as dml
except ModuleNotFoundError:
    import item33_trends_dml_capture as dml

CONFIG_SCHEMA = "noteai.item33.runtime_capture_config.v1"
SEAL_SCHEMA = "noteai.item33.runtime_capture_seal.v1"
SOCKET_PATH = "/run/noteai-item33/capture.sock"
CONFIG_PATH = "/run/noteai-item33/capture-config.json"
JOURNAL_REF = "deploy/production/evidence/production-item33-trends-dml-journal.jsonl"
ACCEPTED_REFS = frozenset({"model/spider_xhs_http.py", "model/spider_xhs_v5.py",
    "model/security_redaction.py", "model/hot_keywords.py", "model/scheduler_a.py",
    "model/vendor/spider_xhs/v5/trends_bridge.js", "model/trends_contract.py",
    "model/market_timing_worker.py"})
INSTRUMENTATION_REFS = frozenset({"tools/item33_trends_runtime_capture.py",
    "tools/item33_trends_dml_capture.py", "scripts/render_run_market_timing.sh"})
CONFIG_KEYS = {"schema", "activation_id", "activation_identity_sha256", "bucket_key",
    "socket_path", "accepted_source_sha256", "instrumentation_sha256", "coverage",
    "coverage_sha256", "catalog_before_sha256", "installed_definition_sha256"}
SEAL_KEYS = {"schema", "state", "activation_id", "activation_identity_sha256", "run_identity_sha256",
    "bucket_key", "config_sha256", "accepted_source_sha256", "instrumentation_sha256", "coverage_sha256",
    "catalog_before_sha256", "installed_definition_sha256", "coverage", "journal", "stream", "writers",
    "counted_commits", "single_bucket_only", "readiness_credit", "aggregate", "catalog_proof"}
BINDING_KEYS = {"nonce", "run_identity_sha256", "pid", "txid"}
CLAIM_SQL = ("INSERT INTO xhs_trends_runs( id,bucket_key,status,lease_token_hash,lease_fence, "
             "lease_expires_at,started_at,provider_attempt_count ) VALUES (?,?,?,?,?,?,?,0)")
MAX_RECORDS = 32768
MAX_MESSAGE = 8192


class CaptureError(RuntimeError):
    """Fixed diagnostic only; never include SQL, arguments or exception strings."""


def require(ok, code="item33_capture_contract"):
    if not ok:
        raise CaptureError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decoded(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(CaptureError("item33_capture_json")))


def utc_now():
    return datetime.now(timezone.utc)


def normalized(statement):
    require(isinstance(statement, str))
    return " ".join(statement.split()).casefold()


def validate_config(value):
    require(isinstance(value, dict) and set(value) == CONFIG_KEYS and value["schema"] == CONFIG_SCHEMA)
    activation = dml._uuid(value["activation_id"])
    require(value["activation_identity_sha256"] == sha(activation.encode("ascii")))
    require(isinstance(value["bucket_key"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["bucket_key"]))
    require(datetime.fromisoformat(value["bucket_key"]).date().isoformat() == value["bucket_key"])
    require(value["socket_path"] == SOCKET_PATH)
    for field, refs in (("accepted_source_sha256", ACCEPTED_REFS), ("instrumentation_sha256", INSTRUMENTATION_REFS)):
        require(isinstance(value[field], dict) and set(value[field]) == refs)
        for digest in value[field].values(): dml._sha(digest)
    require(isinstance(value["coverage"], dict))
    targets = {}
    for table, item in value["coverage"].items():
        require(isinstance(item, dict) and set(item) == {"key_columns", "group"} and isinstance(item["key_columns"], list))
        targets[table] = dml.TableTarget(tuple(item["key_columns"]), item["group"])
    require(dml.coverage_sha256(targets) == value["coverage_sha256"])
    for field in ("catalog_before_sha256", "installed_definition_sha256"): dml._sha(value[field])
    return targets


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def exclusive(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(fd)
    finally: os.close(fd)
    sync_directory(path.parent)


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.fchmod(self.fd, 0o600); os.fsync(self.fd); sync_directory(self.path.parent)
        self.records = []; self.last = "0" * 64

    def append(self, event):
        require(len(self.records) < MAX_RECORDS, "item33_capture_record_limit")
        body = {"sequence": len(self.records) + 1, "previous_sha256": self.last, "event": event}
        row = {**body, "sha256": sha(encoded(body))}; raw = encoded(row) + b"\n"
        view = memoryview(raw)
        while view:
            written = os.write(self.fd, view); require(written > 0, "item33_capture_journal_write")
            view = view[written:]
        os.fsync(self.fd)
        self.records.append(row); self.last = row["sha256"]

    def metadata(self):
        expected = b"".join(encoded(row) + b"\n" for row in self.records)
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            with os.fdopen(fd, "rb", closefd=False) as stream: actual = stream.read(len(expected) + 1)
            require(actual == expected, "item33_capture_journal_changed")
        finally: os.close(fd)
        return {"ref": JOURNAL_REF, "bytes": len(actual), "sha256": sha(actual),
                "record_count": len(self.records), "last_chain_sha256": self.last}

    def close(self):
        if self.fd is not None:
            os.close(self.fd); self.fd = None


class CaptureSession:
    """Host-side session. All DB connections are supplied, never discovered here.

    `start`/`serve` use only the dedicated capture channel and Unix socket. Every
    ACK follows journal fsync. A gap or uncertain terminal permanently stops ACKs.
    The seal remains NOT_TERMINAL: actual coverage/ACL/DDL proofs belong to the
    host's separately bound preflight/control-plane readbacks and original gate.
    """
    def __init__(self, config, root, *, clock=utc_now):
        self.targets = validate_config(config); self.config = config; self.root = Path(root)
        self.clock = clock; self.condition = threading.Condition(threading.RLock())
        self.bindings = {}; self.closed = {}; self.event_ids = set(); self.mutations = Counter()
        self.run_identity = None; self.started = False; self.ended = False; self.admission_closed = False
        self.disconnected = 0; self.invalid = 0; self.failure = False; self.stopping = threading.Event()
        self.journal = None; self.listener_thread = None; self.rpc_thread = None; self.server = None
        self.start_token = str(uuid.uuid4()); self.end_token = str(uuid.uuid4()); self.barrier_pid = None

    def guard(self):
        require(not self.failure, "item33_capture_unknown")
        now = self.clock()
        require(now.tzinfo is not None and now.utcoffset().total_seconds() == 0)
        require(now.date().isoformat() == self.config["bucket_key"], "item33_capture_bucket_closed")

    def fail(self, *, disconnect=False):
        with self.condition:
            self.failure = True
            if disconnect: self.disconnected += 1
            else: self.invalid += 1
            self.condition.notify_all()

    def register(self, binding):
        with self.condition:
            self.guard(); require(self.started and not self.admission_closed)
            dml._validate_binding(binding)
            require(binding["nonce"] not in self.bindings and binding["txid"] not in {x["txid"] for x in self.bindings.values()})
            if self.run_identity is None: self.run_identity = binding["run_identity_sha256"]
            require(binding["run_identity_sha256"] == self.run_identity)
            self.journal.append({"kind": "registered", **binding})
            self.bindings[binding["nonce"]] = dict(binding)

    def notify(self, notification):
        with self.condition:
            require(not self.failure and not self.ended)
            require(notification.channel == dml.channel_for(self.config["activation_id"]))
            raw = notification.payload.encode(); require(len(raw) <= MAX_MESSAGE)
            event = decoded(raw); require(isinstance(event, dict) and "sender_pid" not in event)
            kind = event.get("kind")
            if kind == "barrier":
                require(set(event) == {"kind", "activation_id", "phase", "nonce"})
                require(event["activation_id"] == self.config["activation_id"] and notification.pid == self.barrier_pid)
                if event["phase"] == "start":
                    require(not self.started and event["nonce"] == self.start_token)
                    self.journal.append({**event, "sender_pid": notification.pid}); self.started = True
                else:
                    require(event["phase"] == "end" and event["nonce"] == self.end_token and self.admission_closed)
                    require(set(self.bindings) == set(self.closed))
                    self.journal.append({**event, "sender_pid": notification.pid}); self.ended = True
                self.condition.notify_all(); return
            nonce = event.get("nonce"); require(nonce in self.bindings and nonce not in self.closed)
            binding = self.bindings[nonce]
            require(notification.pid == binding["pid"] and all(event.get(k) == v for k, v in binding.items()))
            if kind == "mutation":
                require(set(event) == {"kind", *BINDING_KEYS, "activation", "coverage_sha256", "event_id", "table", "op",
                    "old_row_sha256", "new_row_sha256", "scope_violation", "run_succeeded"})
                require(event["activation"] == self.config["activation_id"] and event["coverage_sha256"] == self.config["coverage_sha256"])
                event_id = dml._uuid(event["event_id"]); require(event_id not in self.event_ids)
                require(event["table"] in self.targets and event["op"] in {"INSERT", "UPDATE", "DELETE", "TRUNCATE"})
                for key, present in (("old_row_sha256", event["op"] in {"UPDATE", "DELETE"}), ("new_row_sha256", event["op"] in {"INSERT", "UPDATE"})):
                    if present: dml._sha(event[key])
                    else: require(event[key] is None)
                require(type(event["scope_violation"]) is bool and type(event["run_succeeded"]) is bool)
                self.journal.append({**event, "sender_pid": notification.pid})
                self.event_ids.add(event_id); self.mutations[nonce] += 1
                if event["scope_violation"] or event["op"] in {"DELETE", "TRUNCATE"}:
                    self.fail(); return
            else:
                require(kind == "commit" and set(event) == {"kind", *BINDING_KEYS, "mutation_count"})
                require(type(event["mutation_count"]) is int and event["mutation_count"] == self.mutations[nonce])
                self.journal.append({**event, "sender_pid": notification.pid}); self.closed[nonce] = "commit"
            self.condition.notify_all()

    def rollback(self, binding):
        with self.condition:
            require(not self.failure and self.bindings.get(binding.get("nonce")) == binding)
            nonce = binding["nonce"]; require(nonce not in self.closed and self.mutations[nonce] == 0)
            self.journal.append({"kind": "rollback", **binding}); self.closed[nonce] = "rollback"
            self.condition.notify_all()

    def wait_terminal(self, binding, *, timeout=10):
        with self.condition:
            require(self.bindings.get(binding.get("nonce")) == binding)
            require(self.condition.wait_for(lambda: self.failure or binding["nonce"] in self.closed, timeout))
            require(not self.failure and self.closed[binding["nonce"]] == "commit")

    def _barrier(self, control, phase):
        from psycopg import sql
        require(control.autocommit is True)
        pid = control.execute("SELECT pg_backend_pid()").fetchone()[0]
        if self.barrier_pid is None: self.barrier_pid = pid
        require(self.barrier_pid == pid)
        event = {"kind": "barrier", "activation_id": self.config["activation_id"], "phase": phase,
                 "nonce": self.start_token if phase == "start" else self.end_token}
        control.execute("SELECT pg_notify(%s,%s)", (dml.channel_for(self.config["activation_id"]), encoded(event).decode()))

    def start(self, listener, control):
        from psycopg import sql
        self.guard(); require(self.journal is None and listener is not control and listener.autocommit is True)
        meta = self.root.lstat(); require(stat.S_ISDIR(meta.st_mode) and not self.root.is_symlink()
            and meta.st_uid == os.geteuid() and stat.S_IMODE(meta.st_mode) == 0o700)
        self.journal = Journal(self.root / "production-item33-trends-dml-journal.jsonl")
        self.journal.append({"kind": "capture_start", "activation_id": self.config["activation_id"],
            "configuration_sha256": sha(encoded(self.config)), "bucket_key": self.config["bucket_key"]})
        listener.execute(sql.SQL("LISTEN {}").format(sql.Identifier(dml.channel_for(self.config["activation_id"]))))
        def consume():
            try:
                while not self.stopping.is_set():
                    for notification in listener.notifies(timeout=0.25):
                        self.notify(notification)
                        if self.stopping.is_set(): return
            except Exception: self.fail(disconnect=True)
        self.listener_thread = threading.Thread(target=consume, name="item33-capture-listener", daemon=True)
        self.listener_thread.start(); self._barrier(control, "start")
        with self.condition:
            require(self.condition.wait_for(lambda: self.started or self.failure, 10) and self.started and not self.failure)

    def serve(self, path, *, expected_uid=999):
        require(self.started and not self.failure and self.server is None)
        path = Path(path); require(path.parent == self.root and path.name == "capture.sock" and not os.path.lexists(path))
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path)); os.chmod(path, 0o600)
        if os.geteuid() == 0: os.chown(path, expected_uid, expected_uid)
        require(path.stat().st_uid == expected_uid); sync_directory(path.parent)
        server.listen(4); server.settimeout(0.25); self.server = server
        def handle():
            while not self.stopping.is_set():
                try: conn, _ = server.accept()
                except socket.timeout: continue
                except OSError:
                    if not self.stopping.is_set(): self.fail()
                    return
                with conn:
                    try:
                        conn.settimeout(10)
                        require(hasattr(socket, "SO_PEERCRED"))
                        _, uid, _ = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        require(uid == expected_uid)
                        raw = receive_message(conn); request = decoded(raw)
                        require(set(request) == {"op", "activation_id", "binding"} and request["activation_id"] == self.config["activation_id"])
                        binding = request["binding"]; dml._validate_binding(binding)
                        if request["op"] == "register": self.register(binding)
                        elif request["op"] == "committed": self.wait_terminal(binding)
                        elif request["op"] == "rollback": self.rollback(binding)
                        else: raise CaptureError("item33_capture_operation")
                        conn.sendall(encoded({"state": "DURABLE_ACK", "nonce": binding["nonce"]}) + b"\n")
                    except Exception:
                        self.fail()
                        with suppress(Exception): conn.sendall(b'{"state":"UNKNOWN_READBACK_ONLY"}\n')
        self.rpc_thread = threading.Thread(target=handle, name="item33-capture-registration", daemon=True)
        self.rpc_thread.start()

    def seal(self, control, *, catalog_proof=None, catalog_proof_factory=None):
        with self.condition:
            require(not self.failure and self.started and not self.admission_closed)
            self.admission_closed = True
            self.journal.append({"kind": "admission_closed", "activation_id": self.config["activation_id"]})
            require(self.condition.wait_for(lambda: self.failure or set(self.bindings) == set(self.closed), 10))
            require(not self.failure and self.bindings and self.run_identity is not None)
        self._barrier(control, "end")
        with self.condition:
            require(self.condition.wait_for(lambda: self.ended or self.failure, 10) and self.ended and not self.failure)
            records = [row["event"] for row in self.journal.records if row["event"]["kind"] in {"registered", "mutation", "commit", "rollback"}]
            aggregate = dml.aggregate_records(records, activation=self.config["activation_id"], targets=self.targets,
                run_identity_sha256=self.run_identity, require_mutation_count=True)
            require(aggregate["status"] == "ROW_CAPTURE_AGGREGATED_NOT_TERMINAL")
            require(catalog_proof_factory is None or (callable(catalog_proof_factory) and catalog_proof is None))
            if catalog_proof_factory is not None: catalog_proof = catalog_proof_factory()
            counts = Counter(self.closed.values())
            result = {"schema": SEAL_SCHEMA, "state": "CAPTURE_SEALED_NOT_TERMINAL",
                "activation_id": self.config["activation_id"], "activation_identity_sha256": self.config["activation_identity_sha256"],
                "run_identity_sha256": self.run_identity, "bucket_key": self.config["bucket_key"],
                "config_sha256": sha(encoded(self.config)),
                **{k: self.config[k] for k in ("accepted_source_sha256", "instrumentation_sha256", "coverage_sha256", "catalog_before_sha256", "installed_definition_sha256")},
                "coverage": self.config["coverage"], "journal": self.journal.metadata(),
                "stream": {"start_barrier_received": True, "end_barrier_received": True,
                           "disconnect_count": self.disconnected, "invalid_count": self.invalid},
                "writers": {"registered": len(self.bindings), "committed": counts["commit"], "rolled_back": counts["rollback"],
                            "admission_closed": True, "all_closed": set(self.bindings) == set(self.closed)},
                "counted_commits": True, "single_bucket_only": True, "readiness_credit": False,
                "aggregate": aggregate, "catalog_proof": catalog_proof}
            exclusive(self.root / "capture-seal.json", encoded(result) + b"\n")
            return result

    def close(self):
        self.stopping.set()
        if self.server is not None: self.server.close()
        for thread in (self.rpc_thread, self.listener_thread):
            if thread is not None: thread.join(timeout=1)
        require(not any(thread is not None and thread.is_alive() for thread in (self.rpc_thread, self.listener_thread)),
                "item33_capture_close_unknown")
        if self.journal is not None: self.journal.close()
        require(not self.failure, "item33_capture_close_unknown")
        # Keep socket and partial records: existing paths forbid a second activation.


def verify_capture_artifacts(seal, journal, *, require_terminal_proofs=True):
    """Pure recheck of original bytes; a chained journal alone is not terminal."""
    try:
        require(type(require_terminal_proofs) is bool and isinstance(seal, dict) and set(seal) == SEAL_KEYS)
        require(seal["schema"] == SEAL_SCHEMA and seal["state"] == "CAPTURE_SEALED_NOT_TERMINAL")
        require(seal["readiness_credit"] is False and seal["counted_commits"] is True and seal["single_bucket_only"] is True)
        config = {key: seal[key] for key in CONFIG_KEYS - {"schema", "socket_path"}}
        config.update(schema=CONFIG_SCHEMA, socket_path=SOCKET_PATH)
        targets = validate_config(config)
        require(seal["config_sha256"] == sha(encoded(config)))
        dml._sha(seal["run_identity_sha256"])
        require(seal["run_identity_sha256"] != seal["activation_identity_sha256"])
        require(isinstance(journal, bytes) and 0 < len(journal) <= MAX_RECORDS * MAX_MESSAGE)
        metadata = seal["journal"]
        require(set(metadata) == {"ref", "bytes", "sha256", "record_count", "last_chain_sha256"})
        require(metadata["ref"] == JOURNAL_REF and type(metadata["bytes"]) is int and metadata["bytes"] == len(journal)
                and metadata["sha256"] == sha(journal))
        lines = journal.splitlines(keepends=True)
        require(type(metadata["record_count"]) is int and metadata["record_count"] == len(lines) and 5 <= len(lines) <= MAX_RECORDS)
        previous = "0" * 64; events = []
        for index, line in enumerate(lines, 1):
            require(len(line) <= MAX_MESSAGE and line.endswith(b"\n"))
            row = decoded(line)
            require(set(row) == {"sequence", "previous_sha256", "event", "sha256"} and type(row["sequence"]) is int
                    and row["sequence"] == index and row["previous_sha256"] == previous)
            body = {key: row[key] for key in ("sequence", "previous_sha256", "event")}
            require(row["sha256"] == sha(encoded(body)) and encoded(row) + b"\n" == line)
            previous = row["sha256"]; events.append(row["event"])
        require(metadata["last_chain_sha256"] == previous)
        require(events[0] == {"kind": "capture_start", "activation_id": seal["activation_id"],
            "configuration_sha256": seal["config_sha256"], "bucket_key": seal["bucket_key"]})
        barriers = [event for event in events if event.get("kind") == "barrier"]
        require(len(barriers) == 2 and events[1] == barriers[0] and events[-1] == barriers[1])
        for event, phase in zip(barriers, ("start", "end")):
            require(set(event) == {"kind", "activation_id", "phase", "nonce", "sender_pid"}
                and event["activation_id"] == seal["activation_id"] and event["phase"] == phase
                and type(event["sender_pid"]) is int and event["sender_pid"] > 0)
            dml._uuid(event["nonce"])
        require(barriers[0]["sender_pid"] == barriers[1]["sender_pid"] and barriers[0]["nonce"] != barriers[1]["nonce"])
        closed_event = {"kind": "admission_closed", "activation_id": seal["activation_id"]}
        require(events.count(closed_event) == 1)
        closed_index = events.index(closed_event)
        require(2 < closed_index < len(events) - 1 and not any(x.get("kind") == "registered" for x in events[closed_index + 1:]))
        require(all(x.get("kind") in {"registered", "mutation", "commit", "rollback"} for x in events[2:closed_index])
                and all(x.get("kind") in {"mutation", "commit", "rollback"} for x in events[closed_index + 1:-1]))
        records = events[2:closed_index] + events[closed_index + 1:-1]
        aggregate = dml.aggregate_records(records, activation=seal["activation_id"], targets=targets,
            run_identity_sha256=seal["run_identity_sha256"], require_mutation_count=True)
        require(aggregate["status"] == "ROW_CAPTURE_AGGREGATED_NOT_TERMINAL" and aggregate == seal["aggregate"])
        counts = Counter(row["kind"] for row in records)
        require(seal["stream"] == {"start_barrier_received": True, "end_barrier_received": True,
            "disconnect_count": 0, "invalid_count": 0})
        require(seal["stream"]["start_barrier_received"] is True and seal["stream"]["end_barrier_received"] is True)
        require(all(type(seal["stream"][key]) is int for key in ("disconnect_count", "invalid_count")))
        require(seal["writers"] == {"registered": counts["registered"], "committed": counts["commit"],
            "rolled_back": counts["rollback"], "admission_closed": True, "all_closed": True})
        require(seal["writers"]["admission_closed"] is True and seal["writers"]["all_closed"] is True)
        require(all(type(seal["writers"][key]) is int for key in ("registered", "committed", "rolled_back")))
        if require_terminal_proofs:
            try:
                from tools import item33_trends_capture_catalog as catalog
            except ModuleNotFoundError:
                import item33_trends_capture_catalog as catalog
            catalog.verify_catalog_proof(seal["catalog_proof"], config=config)
        return aggregate
    except (CaptureError, KeyError, TypeError, AttributeError, ImportError, ValueError):
        raise ValueError("item33_capture_artifacts_unproven") from None


def receive_message(conn):
    result = bytearray()
    while b"\n" not in result:
        chunk = conn.recv(min(1024, MAX_MESSAGE + 1 - len(result)))
        require(chunk and len(result) + len(chunk) <= MAX_MESSAGE)
        result.extend(chunk)
    require(result.endswith(b"\n") and result.count(b"\n") == 1)
    return bytes(result[:-1])


def writer_rpc(config, operation, binding):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10); client.connect(config["socket_path"])
        client.sendall(encoded({"op": operation, "activation_id": config["activation_id"], "binding": binding}) + b"\n")
        response = decoded(receive_message(client))
    require(response == {"state": "DURABLE_ACK", "nonce": binding["nonce"]}, "item33_capture_ack_unknown")


class WriterContext:
    def __init__(self, config, *, rpc=writer_rpc, clock=utc_now):
        validate_config(config); self.config = config; self.rpc = rpc; self.clock = clock; self.run_identity = None

    def guard(self):
        now = self.clock()
        require(now.tzinfo is not None and now.utcoffset().total_seconds() == 0)
        require(now.date().isoformat() == self.config["bucket_key"], "item33_capture_bucket_closed")

    def connection(self, original):
        self.guard()
        return WriterConnection(original(), self)


class WriterConnection:
    def __init__(self, connection, context):
        self.original = connection; self.context = context; self.binding = None; self.entered = False
        self.raw = connection._connection
        require(self.raw.autocommit is False, "item33_capture_explicit_transaction_required")

    def __enter__(self):
        self.context.guard(); self.original.__enter__(); self.entered = True; return self

    def execute(self, statement, params=()):
        self.context.guard()
        text = normalized(statement)
        if not text.startswith("select "):
            require(self.entered)
            require(text.startswith(("insert ", "update ")), "item33_capture_business_sql")
            if self.binding is None:
                if self.context.run_identity is None:
                    require(text == normalized(CLAIM_SQL) and isinstance(params, (tuple, list)) and len(params) == 7,
                            "item33_capture_unbound_run")
                    run = dml._uuid(params[0]); self.context.run_identity = sha(run.encode("ascii"))
                else:
                    require(text != normalized(CLAIM_SQL), "item33_capture_second_run")
                identity = self.raw.execute("SELECT session_user,current_user").fetchone()
                require(identity[0] == identity[1] == dml.WRITER_ROLE, "item33_capture_writer_role")
                nonce = str(uuid.uuid4())
                for query in dml.binding_sql(self.context.config["activation_id"], nonce, self.context.run_identity, mutation_counts=True):
                    cursor = self.raw.execute(query)
                identity_row = cursor.fetchone()
                pid, txid = identity_row[0], identity_row[1]
                self.binding = {"nonce": nonce, "run_identity_sha256": self.context.run_identity, "pid": pid, "txid": txid}
                self.context.rpc(self.context.config, "register", self.binding)
        return self.original.execute(statement, params)

    def __exit__(self, exc_type, exc, tb):
        completion_failed = False
        if self.binding is not None and exc_type is None:
            try:
                self.context.guard()
                self.raw.execute(dml.completion_sql(self.context.config["activation_id"], self.binding, mutation_counts=True))
            except Exception:
                exc = CaptureError("item33_capture_completion_unknown"); exc_type = type(exc); tb = None; completion_failed = True
        try:
            result = self.original.__exit__(exc_type, exc, tb)
        except Exception:
            raise CaptureError("item33_capture_transaction_unknown") from None
        if self.binding is not None:
            try: self.context.rpc(self.context.config, "committed" if exc_type is None else "rollback", self.binding)
            except Exception: raise CaptureError("item33_capture_terminal_ack_unknown") from None
        if completion_failed: raise exc from None
        return result

    def close(self):
        self.original.close()


def guard_transport(client_class, context):
    """RAM-only Trends hook includes the two cold-initialization HTTP starts."""
    original = client_class.request
    def bounded_request(client, *args, **kwargs):
        context.guard()
        return original(client, *args, **kwargs)
    client_class.request = bounded_request


def worker_main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--config", required=True)
    args, remainder = parser.parse_known_args(argv)
    require(args.config == CONFIG_PATH and remainder == ["--", "--daemon", "--interval", "360"])
    require(os.geteuid() == 999)
    path = Path(args.config)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd); require(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and stat.S_IMODE(meta.st_mode) == 0o444 and meta.st_size <= 65536)
        with os.fdopen(fd, "rb", closefd=False) as stream: raw = stream.read(65537)
    finally: os.close(fd)
    config = decoded(raw); validate_config(config)
    require(raw == encoded(config), "item33_capture_config_canonical")
    for ref, digest in {**config["accepted_source_sha256"], **config["instrumentation_sha256"]}.items():
        source = Path("/app") / ref
        require(not source.is_symlink() and sha(source.read_bytes()) == digest, "item33_capture_source_binding")
    sys.path.insert(0, "/app/model")
    import hot_keywords
    import market_timing_worker
    import spider_xhs_v5
    require(hot_keywords.primary_db.using_postgres(), "item33_capture_postgres_required")
    context = WriterContext(config); context.guard()
    guard_transport(spider_xhs_v5.TrendsCurlClient, context)
    original = hot_keywords._conn
    hot_keywords._conn = lambda: context.connection(original)
    sys.argv = ["market_timing_worker.py", *remainder[1:]]
    return market_timing_worker.main()


if __name__ == "__main__":
    try: raise SystemExit(worker_main(sys.argv[1:]))
    except CaptureError:
        print('{"event":"item33_capture_failed","error_code":"item33_capture_unknown"}', file=sys.stderr)
        raise SystemExit(2)
