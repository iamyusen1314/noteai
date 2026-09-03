#!/usr/bin/env python3
"""Render the read-only Item 26 API-C persistent-parent diagnostic atom."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import render_item26_v3_transport as v3


TEMPLATE_PATH = ROOT / ".codex/item26-restored-parent-probe-api-c-v1.template.sh"
TEMPLATE_IDENTITY = {
    "bytes": 8107,
    "sha256": "38f455663d300ea16170c9c845def60d0686c6dd4186e2fd117065d070fae4d4",
}
ACTION = "parent_probe_api_c"
COMMAND_NAME = "noteai-item26-restored-parent-probe-api-c-20260813-v1"
REGION = "cn-shenzhen"
TASK_TAG = {"Key": "noteai-task", "Value": "item26-restored-v1"}
MAX_INPUT_BYTES = 4096
MAX_COMMAND_CONTENT_BYTES = 18000
INSTANCE_ID = re.compile(r"^i-[a-z0-9]+$")
PLAN_NONCE = re.compile(r"^[0-9a-f]{32}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER = re.compile(br"@@[A-Z][A-Z0-9_]*@@")
RUN_COMMAND_KEYS = frozenset({
    "ClientToken",
    "CommandContent",
    "ContentEncoding",
    "EnableParameter",
    "InstanceId",
    "KeepCommand",
    "Name",
    "RegionId",
    "RepeatMode",
    "Tag",
    "TerminationMode",
    "Timeout",
    "Type",
    "Username",
    "WorkingDir",
})


class RenderError(ValueError):
    def __init__(self, code):
        ValueError.__init__(self, code)
        self.code = code


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    try:
        return (json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RenderError("json") from exc


def no_duplicates(pairs):
    value = {}
    for key, row in pairs:
        if key in value:
            raise RenderError("duplicate_json_key")
        value[key] = row
    return value


def parse_canonical(raw):
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_INPUT_BYTES
        or not raw.endswith(b"\n")
        or b"\r" in raw
        or b"\x00" in raw
    ):
        raise RenderError("input_shape")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=no_duplicates)
    except RenderError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RenderError("input_json") from exc
    if type(value) is not dict or canonical(value) != raw:
        raise RenderError("input_canonical")
    return value


def read_template():
    try:
        before = TEMPLATE_PATH.lstat()
        body = TEMPLATE_PATH.read_bytes()
        after = TEMPLATE_PATH.lstat()
    except OSError as exc:
        raise RenderError("template") from exc
    metadata = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or metadata(before) != metadata(after)
        or len(body) != TEMPLATE_IDENTITY["bytes"]
        or sha256(body) != TEMPLATE_IDENTITY["sha256"]
        or PLACEHOLDER.search(body)
    ):
        raise RenderError("template")
    try:
        v3._validate_bash_python("parent_probe_template", body, 1)
    except v3.RenderError as exc:
        raise RenderError("template_syntax") from exc
    return body


VALIDATOR = b"""import json,os,re,signal,subprocess
def nd(p):
 v={}
 for k,x in p:
  if k in v:raise ValueError
  v[k]=x
 return v
def ca(v):return (json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\\n").encode("ascii")
def ex(v,k):return type(v) is dict and set(v)==set(k.split())
def i(v,a,b):return type(v) is int and a<=v<=b
def q(v,x):return type(v) is bool and v is x
C="application_secret_value_read_count automatic_retry_allowed container_start_count database_connection_count database_write_count environment_value_read_count host_task_write_count private_key_value_read_count resource_id_values_emitted same_invocation_replay_allowed secret_values_emitted"
Z="application_secret_value_read_count container_start_count database_connection_count database_write_count environment_value_read_count host_task_write_count private_key_value_read_count resource_id_values_emitted secret_values_emitted"
M="NOTEAI_ITEM26_RESTORED_PARENT_PROBE"
F=set("python root tool trusted_parent".split())
U=set("trusted_parent_runtime trusted_parent_race persistent_parent_runtime persistent_parent_race unexpected".split())
T=set("ABSENT DIRECTORY REGULAR_FILE SYMLINK BLOCK_DEVICE CHARACTER_DEVICE FIFO SOCKET OTHER".split())
def cm(v):return q(v["automatic_retry_allowed"],False) and q(v["same_invocation_replay_allowed"],False) and all(i(v[x],0,0) for x in Z.split())
def sm(v):
 if type(v) is not str or re.fullmatch(r"[0-7]{4}",v) is None:return False
 m=int(v,8);return (m&0o700)==0o700 and (m&0o7000)==0 and (m&0o022)==0
def ok(v,r):
 if r:
  k=M+" "+C+" phase"+(" readback_required" if r==4 else "")
  return ex(v,k) and v[M]==("FAIL" if r==3 else "UNKNOWN") and cm(v) and type(v["phase"]) is str and v["phase"] in (F if r==3 else U) and (r==3 or q(v["readback_required"],True))
 k=M+" "+C+" persistent_parent_gid persistent_parent_is_symlink persistent_parent_mode persistent_parent_nlink persistent_parent_state persistent_parent_type persistent_parent_uid schema_version trusted_parent_gid trusted_parent_mode trusted_parent_nlink trusted_parent_safe"
 if not ex(v,k) or v[M]!="PASS" or not cm(v) or not i(v["schema_version"],1,1) or not i(v["trusted_parent_gid"],0,4294967295) or not sm(v["trusted_parent_mode"]) or not i(v["trusted_parent_nlink"],0,2147483647) or not q(v["trusted_parent_safe"],True):return False
 s=v["persistent_parent_state"];t=v["persistent_parent_type"]
 if s=="ABSENT":return t=="ABSENT" and q(v["persistent_parent_is_symlink"],False) and all(v[x] is None for x in ("persistent_parent_uid","persistent_parent_gid","persistent_parent_mode","persistent_parent_nlink"))
 if s!="PRESENT" or t not in T or t=="ABSENT" or not q(v["persistent_parent_is_symlink"],t=="SYMLINK"):return False
 return i(v["persistent_parent_uid"],0,4294967295) and i(v["persistent_parent_gid"],0,4294967295) and type(v["persistent_parent_mode"]) is str and re.fullmatch(r"[0-7]{4}",v["persistent_parent_mode"]) is not None and i(v["persistent_parent_nlink"],1,2147483647)
p=subprocess.Popen(["/bin/bash","-s"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},close_fds=True,start_new_session=True)
try:o,e=p.communicate(raw,timeout=30)
except:
 try:os.killpg(p.pid,signal.SIGKILL)
 except:pass
 try:p.communicate(timeout=5)
 except:pass
 raise
r=p.returncode
if r not in (0,3,4) or len(o)+len(e)>4096 or (r==0 and (e or not o)) or (r in (3,4) and (o or not e)):raise ValueError
x=o if r==0 else e
if not x.endswith(b"\\n") or x.count(b"\\n")!=1 or b"\\r" in x or b"\\x00" in x:raise ValueError
v=json.loads(x.decode("ascii"),object_pairs_hook=nd)
if ca(v)!=x or not ok(v,r):raise ValueError
d=1 if r==0 else 2
if os.write(d,x)!=len(x):raise ValueError
os._exit(r)
"""

LOADER = b"""#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
exec /usr/bin/python3 -I -B - <<'PY'
import base64,gzip,hashlib,os
N=@@N@@;H="@@H@@";Z=b"@@Z@@"
FIX=b'{"NOTEAI_ITEM26_RESTORED_PARENT_PROBE_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\\n'
def fixed():
 try:
  if os.write(2,FIX)!=len(FIX):raise OSError
 except:pass
 os._exit(4)
try:
 p=gzip.decompress(base64.b85decode(Z))
 if hashlib.sha256(p).hexdigest()!=H or not 1<=N<len(p):raise ValueError
 raw=p[:N];exec(p[N:],globals())
except:fixed()
PY
"""


def _command_from_raw(raw, compressor):
    if (
        type(raw) is not bytes
        or not raw
        or len(raw) > 65536
        or PLACEHOLDER.search(raw)
    ):
        raise RenderError("command_source")
    try:
        v3._validate_bash_python("parent_probe_source", raw, 1)
    except v3.RenderError as exc:
        raise RenderError("command_source_syntax") from exc
    payload = raw + VALIDATOR
    try:
        packed = v3._compress("parent_probe", payload, compressor)
    except v3.RenderError as exc:
        raise RenderError("gzip") from exc
    loader = (
        LOADER
        .replace(b"@@N@@", str(len(raw)).encode("ascii"))
        .replace(b"@@H@@", sha256(payload).encode("ascii"))
        .replace(b"@@Z@@", base64.b85encode(packed))
    )
    if PLACEHOLDER.search(loader):
        raise RenderError("loader")
    try:
        v3._validate_bash_python("parent_probe_loader", loader, 1)
    except v3.RenderError as exc:
        raise RenderError("loader_syntax") from exc
    encoded = base64.b64encode(loader)
    if not 1 <= len(encoded) <= MAX_COMMAND_CONTENT_BYTES:
        raise RenderError("command_limit")
    if base64.b64decode(encoded, validate=True) != loader:
        raise RenderError("command_roundtrip")
    return {
        "base64": encoded.decode("ascii"),
        "bytes": len(encoded),
        "sha256": sha256(encoded),
    }


def command(compressor):
    return _command_from_raw(read_template(), compressor)


def derive_client_token(plan_nonce):
    if type(plan_nonce) is not str or PLAN_NONCE.fullmatch(plan_nonce) is None:
        raise RenderError("plan_nonce")
    token = sha256(
        b"item26-restored-parent-probe-v1\x00"
        + plan_nonce.encode("ascii")
        + b"\x00"
        + ACTION.encode("ascii")
    )
    if HEX64.fullmatch(token) is None:
        raise RenderError("client_token")
    return token


def validate_command(rendered_command):
    if (
        type(rendered_command) is not dict
        or set(rendered_command) != {"base64", "bytes", "sha256"}
        or type(rendered_command.get("base64")) is not str
        or not rendered_command["base64"]
        or not rendered_command["base64"].isascii()
    ):
        raise RenderError("command_contract")
    try:
        encoded = rendered_command["base64"].encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeError, ValueError) as exc:
        raise RenderError("command_base64") from exc
    if (
        not decoded
        or base64.b64encode(decoded) != encoded
        or not 1 <= len(encoded) <= MAX_COMMAND_CONTENT_BYTES
        or type(rendered_command.get("bytes")) is not int
        or rendered_command["bytes"] != len(encoded)
        or type(rendered_command.get("sha256")) is not str
        or HEX64.fullmatch(rendered_command["sha256"]) is None
        or rendered_command["sha256"] != sha256(encoded)
    ):
        raise RenderError("command_binding")
    return rendered_command


def validate_request(request, api_c_instance_id, plan_nonce, rendered_command):
    if (
        type(api_c_instance_id) is not str
        or INSTANCE_ID.fullmatch(api_c_instance_id) is None
    ):
        raise RenderError("api_c_instance_id")
    rendered_command = validate_command(rendered_command)
    token = derive_client_token(plan_nonce)
    expected = {
        "ClientToken": token,
        "CommandContent": rendered_command["base64"],
        "ContentEncoding": "Base64",
        "EnableParameter": False,
        "InstanceId": [api_c_instance_id],
        "KeepCommand": True,
        "Name": COMMAND_NAME,
        "RegionId": REGION,
        "RepeatMode": "Once",
        "Tag": [dict(TASK_TAG)],
        "TerminationMode": "ProcessTree",
        "Timeout": 120,
        "Type": "RunShellScript",
        "Username": "root",
        "WorkingDir": "/root",
    }
    if type(request) is not dict or set(request) != RUN_COMMAND_KEYS:
        raise RenderError("request_contract")
    if request != expected:
        raise RenderError("request_binding")
    if (
        type(request["EnableParameter"]) is not bool
        or request["EnableParameter"] is not False
        or type(request["KeepCommand"]) is not bool
        or request["KeepCommand"] is not True
        or type(request["Timeout"]) is not int
        or request["Timeout"] != 120
        or type(request["InstanceId"]) is not list
        or len(request["InstanceId"]) != 1
    ):
        raise RenderError("request_types")
    return expected


def render_plan(api_c_instance_id, plan_nonce, compressor):
    if (
        type(api_c_instance_id) is not str
        or INSTANCE_ID.fullmatch(api_c_instance_id) is None
    ):
        raise RenderError("api_c_instance_id")
    rendered_command = command(compressor)
    request = {
        "ClientToken": derive_client_token(plan_nonce),
        "CommandContent": rendered_command["base64"],
        "ContentEncoding": "Base64",
        "EnableParameter": False,
        "InstanceId": [api_c_instance_id],
        "KeepCommand": True,
        "Name": COMMAND_NAME,
        "RegionId": REGION,
        "RepeatMode": "Once",
        "Tag": [dict(TASK_TAG)],
        "TerminationMode": "ProcessTree",
        "Timeout": 120,
        "Type": "RunShellScript",
        "Username": "root",
        "WorkingDir": "/root",
    }
    validate_request(request, api_c_instance_id, plan_nonce, rendered_command)
    request_raw = canonical(request)
    return {
        "action": ACTION,
        "command": rendered_command,
        "evidence": {
            "command_content_base64_bytes": rendered_command["bytes"],
            "command_content_sha256": rendered_command["sha256"],
            "request_canonical_bytes": len(request_raw),
            "request_canonical_sha256": sha256(request_raw),
            "template": dict(TEMPLATE_IDENTITY),
        },
        "prerequisites": {
            "fresh_client_token_history_count_must_equal": 0,
            "fresh_exact_name_target_history_count_must_equal": 0,
            "plan_nonce_emitted_by_renderer": False,
            "plan_nonce_must_be_retained_root_only": True,
            "provider_reads_performed_by_renderer": 0,
        },
        "request": request,
        "state": {
            "automatic_retry_allowed": False,
            "dispatch_count_limit": 1,
            "initial": "HISTORY_ZERO_REQUIRED",
            "post_submit": "PROVIDER_READBACK_ONLY",
            "provider_unknown_recovery": (
                "READBACK_EXACT_CLIENT_TOKEN_NAME_TARGET_NEVER_RESUBMIT"
            ),
            "result_unlocks_initializer": False,
            "result_unlocks_v3": False,
            "same_invocation_replay_allowed": False,
            "same_request_resubmit_allowed": False,
            "terminal_exit_code": {
                "0": "RECONCILE_PARENT_METADATA_RESULT",
                "3": "STOP_KNOWN_FAIL",
                "4": "STOP_UNKNOWN_READBACK_NEVER_REPLAY",
            },
        },
    }


def production_compressor():
    try:
        return v3._production_gzip_compressor()
    except v3.RenderError as exc:
        raise RenderError(exc.code) from exc


def cli():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        value = parse_canonical(raw)
        if type(value) is not dict or set(value) != {
            "api_c_instance_id",
            "mode",
            "plan_nonce",
        } or value["mode"] != "parent_probe":
            raise RenderError("input_contract")
        result = render_plan(
            value["api_c_instance_id"],
            value["plan_nonce"],
            production_compressor(),
        )
        output = canonical(result)
    except RenderError as exc:
        sys.stderr.write("ITEM26_RESTORED_PARENT_PROBE_RENDER_FAILED:" + exc.code + "\n")
        return 2
    except BaseException:
        sys.stderr.write("ITEM26_RESTORED_PARENT_PROBE_RENDER_FAILED:internal\n")
        return 2
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
