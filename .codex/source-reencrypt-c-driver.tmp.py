#!/usr/bin/env python3
import base64
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

MODULE = Path("/task/production_secret_envelope.py")
MODULE_SHA256 = "b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf"
DATABASE_SOURCE = Path("/input/ai-worker.env")
STORAGE_SOURCE = Path("/input/private-storage.env")
PUBLIC_KEY = (
    Path("/input/worker-c-public.pem"),
    Path("/input/worker-c-public.sha256"),
)
TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-WORKER-SECRETS-001"
WORKER_ROLE = "noteai-storage-worker-20260808-item21"
API_ROLE = "noteai-storage-api-20260729-c60cc608"
DATABASE_QUERY_KEYS = frozenset({
    "sslmode", "connect_timeout", "target_session_attrs", "channel_binding",
    "keepalives", "keepalives_idle", "keepalives_interval",
    "keepalives_count", "tcp_user_timeout",
})
STORAGE_KEYS = frozenset({
    "NOTEAI_PRIVATE_STORAGE_BACKEND", "NOTEAI_OSS_PRIVATE_BUCKET",
    "NOTEAI_OSS_REGION", "NOTEAI_OSS_ENDPOINT", "NOTEAI_OSS_RAM_ROLE",
    "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH", "NOTEAI_OSS_KEY_PREFIX",
})

class FixedError(Exception):
    pass

def private_regular(path):
    row = path.lstat()
    return (
        stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0
        and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o600
        and row.st_nlink == 1
    )

def read_private(path):
    if not private_regular(path):
        raise FixedError("source_metadata")
    payload = path.read_bytes()
    if not payload or len(payload) > 16384 or b"\x00" in payload or b"\r" in payload:
        raise FixedError("source_shape")
    return payload

def canonical_rows(payload):
    if not payload.endswith(b"\n"):
        raise FixedError("env_shape")
    lines = payload.splitlines(keepends=True)
    if not lines or any(not line.endswith(b"\n") for line in lines):
        raise FixedError("env_shape")
    rows = []
    names = set()
    for line in lines:
        body = line[:-1]
        if not body or body.startswith(b"#") or body.startswith(b"export ") or b"=" not in body:
            raise FixedError("env_shape")
        raw_name, value = body.split(b"=", 1)
        try:
            name = raw_name.decode("ascii")
        except UnicodeError:
            raise FixedError("env_shape")
        if not name or name in names or raw_name.strip() != raw_name:
            raise FixedError("env_shape")
        names.add(name)
        rows.append((name, value, line))
    return rows

def validate_database(payload):
    rows = canonical_rows(payload)
    if len(rows) != 1 or rows[0][0] != "DATABASE_URL":
        raise FixedError("database_contract")
    try:
        value = rows[0][1].decode("utf-8")
        parsed = urlsplit(value)
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (UnicodeError, TypeError, ValueError):
        raise FixedError("database_contract")
    names = [name.lower() for name, _ in query]
    if not (
        parsed.scheme in {"postgres", "postgresql"}
        and unquote(parsed.username or "") == "noteai_ai_worker"
        and parsed.password not in (None, "")
        and parsed.hostname
        and parsed.path not in {"", "/"}
        and not parsed.fragment
        and len(names) == len(set(names))
        and set(names) <= DATABASE_QUERY_KEYS
    ):
        raise FixedError("database_contract")

def derive_storage(payload):
    rows = canonical_rows(payload)
    values = {name: value for name, value, _ in rows}
    if len(rows) != 7 or set(values) != STORAGE_KEYS:
        raise FixedError("storage_contract")
    try:
        decoded = {name: value.decode("utf-8") for name, value in values.items()}
    except UnicodeError:
        raise FixedError("storage_contract")
    region = decoded["NOTEAI_OSS_REGION"]
    source_role = decoded["NOTEAI_OSS_RAM_ROLE"]
    if not (
        decoded["NOTEAI_PRIVATE_STORAGE_BACKEND"] == "aliyun_oss"
        and region.startswith("cn-")
        and decoded["NOTEAI_OSS_ENDPOINT"] == "https://oss-{}-internal.aliyuncs.com".format(region)
        and decoded["NOTEAI_OSS_PRIVATE_BUCKET"]
        and source_role == API_ROLE
        and decoded["NOTEAI_PRIVATE_STORAGE_KEY_EPOCH"]
        and decoded["NOTEAI_OSS_KEY_PREFIX"].strip("/") == "noteai-private"
    ):
        raise FixedError("storage_contract")
    derived_lines = []
    replaced = 0
    original_role_line = None
    for name, _value, line in rows:
        if name == "NOTEAI_OSS_RAM_ROLE":
            original_role_line = line
            derived_lines.append(b"NOTEAI_OSS_RAM_ROLE=" + WORKER_ROLE.encode("ascii") + b"\n")
            replaced += 1
        else:
            derived_lines.append(line)
    if replaced != 1 or original_role_line is None:
        raise FixedError("storage_derivation")
    derived = b"".join(derived_lines)
    derived_rows = canonical_rows(derived)
    derived_values = {name: value for name, value, _ in derived_rows}
    if derived_values.get("NOTEAI_OSS_RAM_ROLE") != WORKER_ROLE.encode("ascii"):
        raise FixedError("storage_derivation")
    for name in STORAGE_KEYS - {"NOTEAI_OSS_RAM_ROLE"}:
        if derived_values.get(name) != values.get(name):
            raise FixedError("storage_derivation")
    reversed_lines = [original_role_line if name == "NOTEAI_OSS_RAM_ROLE" else line for name, _value, line in derived_rows]
    if b"".join(reversed_lines) != payload:
        raise FixedError("storage_derivation")
    return derived

def write_private(path, payload):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, 0, 0)
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise FixedError("envelope_write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def validated_public(module, host, public_path, hash_path):
    if not private_regular(public_path) or not private_regular(hash_path):
        raise FixedError("public_key_metadata")
    expected_hash = hash_path.read_text(encoding="ascii").strip()
    if len(expected_hash) != 64 or any(value not in "0123456789abcdef" for value in expected_hash):
        raise FixedError("public_key_hash")
    public = module.serialization.load_pem_public_key(public_path.read_bytes())
    if not isinstance(public, module.rsa.RSAPublicKey):
        raise FixedError("public_key_type")
    numbers = public.public_numbers()
    der = public.public_bytes(
        module.serialization.Encoding.DER,
        module.serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if public.key_size != 3072 or numbers.e != 65537 or len(der) != 422 or hashlib.sha256(der).hexdigest() != expected_hash:
        raise FixedError("public_key_contract")
    return expected_hash

def protected_payload(host, public_hash, kind, raw):
    return json.dumps({
        "schema_version": 1,
        "task_id": TASK_ID,
        "host": host,
        "public_key_sha256": public_hash,
        "payload_kind": kind,
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "payload_b64": base64.b64encode(raw).decode("ascii"),
    }, sort_keys=True, separators=(",", ":")).encode("ascii")

try:
    if hashlib.sha256(MODULE.read_bytes()).hexdigest() != MODULE_SHA256:
        raise FixedError("module_hash")
    spec = importlib.util.spec_from_file_location("noteai_secret_envelope", str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = read_private(DATABASE_SOURCE)
    storage = read_private(STORAGE_SOURCE)
    validate_database(database)
    derived_storage = derive_storage(storage)
    output_count = 0
    public_path, hash_path = PUBLIC_KEY
    expected_hash = validated_public(module, "Worker-C", public_path, hash_path)
    for kind, raw in (("database", database), ("private_storage", derived_storage)):
        protected = protected_payload("Worker-C", expected_hash, kind, raw)
        envelope = module.encrypt_payload(protected, public_path)
        if not (0 < len(envelope) <= 12288):
            raise FixedError("envelope_size")
        output = Path("/output/worker-c-{}.envelope.json".format(kind))
        write_private(output, envelope)
        output_count += 1
    print(json.dumps({
        "status": "REENCRYPTED_C",
        "source_file_count": 2,
        "derived_role_replacement_count": 1,
        "unchanged_storage_key_count": 6,
        "envelope_count": output_count,
        "database_payload_unchanged": True,
        "worker_c_payload_count": 2,
        "plaintext_output_count": 0,
    }, sort_keys=True, separators=(",", ":")))
except BaseException:
    print('{"status":"HELPER_FAILED"}')
    sys.exit(3)
