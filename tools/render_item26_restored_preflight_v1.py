#!/usr/bin/env python3
"""Render the two fixed, Secret-free Item 26 restored host preflights."""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import render_item26_v3_transport as v3


PATHS = MappingProxyType({
    "api_c": ROOT / ".codex/item26-restored-api-c-preflight-v1.template.sh",
    "builder": ROOT / ".codex/item26-restored-builder-preflight-v1.template.sh",
})
IDENTITIES = MappingProxyType({
    "api_c": MappingProxyType({
        "bytes": 22269,
        "sha256": "e031f433b6e24346d3c34f57d83f937d6a0b0bf62b653b6908ecb7defe42800b",
    }),
    "builder": MappingProxyType({
        "bytes": 16286,
        "sha256": "690b01e8abb2822d7141130761177d321357771e075b501f08b3ee4025967137",
    }),
})
COUNTS = MappingProxyType({
    "api_c": Counter({b"@@API_C_IDENTITY_SHA256@@": 1}),
    "builder": Counter({b"@@BUILDER_IDENTITY_SHA256@@": 1}),
})
BUILDER_RAM_ROLE = "noteai-item26-pitr-oss-reader-v1"
MAX_COMMAND = 18000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER = re.compile(br"@@[A-Z][A-Z0-9_]*@@")


class RenderError(ValueError):
    def __init__(self, code):
        ValueError.__init__(self, code)
        self.code = code


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return (json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("ascii")


def no_duplicates(pairs):
    value = {}
    for key, row in pairs:
        if key in value:
            raise RenderError("duplicate")
        value[key] = row
    return value


def parse(raw, label, limit=65536):
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= limit
        or not raw.endswith(b"\n")
        or b"\r" in raw
        or b"\x00" in raw
    ):
        raise RenderError(label)
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=no_duplicates)
    except RenderError:
        raise
    except BaseException as exc:
        raise RenderError(label) from exc
    if type(value) is not dict or canonical(value) != raw:
        raise RenderError(label)
    return value


def identity(instance_id, ram_role):
    if (
        type(instance_id) is not str
        or re.fullmatch(r"i-[a-z0-9]+", instance_id) is None
        or type(ram_role) is not str
        or re.fullmatch(r"[A-Za-z0-9._-]{1,64}", ram_role) is None
    ):
        raise RenderError("identity")
    return sha(json.dumps(
        {"instance_id": instance_id, "ram_role": ram_role},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii"))


def builder_identity(instance_id, ram_role):
    if ram_role != BUILDER_RAM_ROLE:
        raise RenderError("builder_ram_role")
    return identity(instance_id, ram_role)


def read_template(name):
    if name not in PATHS:
        raise RenderError("template_name")
    path = PATHS[name]
    expected = IDENTITIES[name]
    try:
        before = path.lstat()
        body = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise RenderError(name + "_template") from exc
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
        or metadata(before) != metadata(after)
        or len(body) != expected["bytes"]
        or sha(body) != expected["sha256"]
        or Counter(PLACEHOLDER.findall(body)) != COUNTS[name]
    ):
        raise RenderError(name + "_template")
    return body


def render(name, bindings):
    body = read_template(name)
    if set(bindings) != set(COUNTS[name]):
        raise RenderError(name + "_bindings")
    for token, value in bindings.items():
        if (
            type(value) is not bytes
            or not value
            or any(char in value for char in (b"\n", b"\r", b"\x00"))
        ):
            raise RenderError(name + "_binding")
        body = body.replace(token, value)
    if PLACEHOLDER.search(body):
        raise RenderError(name + "_residue")
    try:
        v3._validate_bash_python(name, body, 1)
    except v3.RenderError as exc:
        raise RenderError(name + "_syntax") from exc
    return body


VALIDATOR_PREFIX = b"""import json,os,re,signal,subprocess
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
def cm(v):return q(v["automatic_retry_allowed"],False) and q(v["same_invocation_replay_allowed"],False)
C="application_secret_value_read_count automatic_retry_allowed container_start_count database_connection_count database_write_count environment_value_read_count host_task_write_count private_key_value_read_count resource_id_values_emitted same_invocation_replay_allowed secret_values_emitted"
def common(v):return cm(v) and all(i(v[x],0,0) for x in "application_secret_value_read_count container_start_count database_connection_count database_write_count environment_value_read_count host_task_write_count private_key_value_read_count resource_id_values_emitted secret_values_emitted".split())
"""

VALIDATOR_CASES = MappingProxyType({
    "api_c": b"""M="NOTEAI_ITEM26_RESTORED_API_C_PREFLIGHT";F=set("binding db_socket docker_config docker_service environment_metadata identity image persistent_parent python root source_control source_manifest tool".split());U=set("broker_root_present broker_root_present_runtime container_present docker_config_race docker_config_runtime docker_runtime environment_metadata_race environment_metadata_runtime identity_runtime image_runtime persistent_parent_race persistent_parent_runtime rewrap_root_present rewrap_root_present_runtime socket_runtime source_control_race source_control_runtime source_manifest_race source_manifest_runtime tool_runtime unexpected".split())
def ok(v,r):
 if r:
  k=M+" "+C+" phase"+(" readback_required" if r==4 else "")
  return ex(v,k) and v[M]==("FAIL" if r==3 else "UNKNOWN") and common(v) and type(v["phase"]) is str and v["phase"] in (F if r==3 else U) and (r==3 or q(v["readback_required"],True))
 k=M+" "+C+" broker_root_absent docker_config_exact docker_service_exact environment_metadata_exact established_tcp_5432_count identity_exact image_exact persistent_parent_exact rewrap_root_absent schema_version source_control_exact source_manifest_exact task_container_count"
 return ex(v,k) and v[M]=="PASS" and common(v) and all(q(v[x],True) for x in "broker_root_absent docker_config_exact docker_service_exact environment_metadata_exact identity_exact image_exact persistent_parent_exact rewrap_root_absent source_control_exact source_manifest_exact".split()) and all(i(v[x],0,0) for x in ("established_tcp_5432_count","task_container_count")) and i(v["schema_version"],1,1)
""",
    "builder": b"""M="NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT";F=set("binding capacity db_socket docker_config docker_service identity image persistent_parent python root tool".split());U=set("capacity_runtime container_present docker_config_race docker_config_runtime docker_runtime identity_runtime image_runtime persistent_parent_race persistent_parent_runtime restored_base_present restored_base_present_runtime socket_runtime tool_runtime unexpected".split())
def ok(v,r):
 if r:
  k=M+" "+C+" phase"+(" readback_required" if r==4 else "")
  return ex(v,k) and v[M]==("FAIL" if r==3 else "UNKNOWN") and common(v) and type(v["phase"]) is str and v["phase"] in (F if r==3 else U) and (r==3 or q(v["readback_required"],True))
 k=M+" "+C+" builder_capacity_exact docker_config_exact docker_service_exact established_tcp_5432_count fixed_ram_role_exact identity_exact image_exact persistent_parent_exact restored_base_absent schema_version task_container_count"
 return ex(v,k) and v[M]=="PASS" and common(v) and all(q(v[x],True) for x in "builder_capacity_exact docker_config_exact docker_service_exact fixed_ram_role_exact identity_exact image_exact persistent_parent_exact restored_base_absent".split()) and all(i(v[x],0,0) for x in ("established_tcp_5432_count","task_container_count")) and i(v["schema_version"],1,1)
""",
})

VALIDATOR_SUFFIX = b"""p=subprocess.Popen(["/bin/bash","-s"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},close_fds=True,start_new_session=True)
try:o,e=p.communicate(raw,timeout=90)
except:
 try:os.killpg(p.pid,signal.SIGKILL)
 except:pass
 try:p.communicate(timeout=10)
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
FIX=b'{"NOTEAI_ITEM26_RESTORED_PREFLIGHT_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\\n'
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


def validator(name):
    try:
        result = VALIDATOR_PREFIX + VALIDATOR_CASES[name] + VALIDATOR_SUFFIX
    except KeyError as exc:
        raise RenderError("contract") from exc
    if PLACEHOLDER.search(result):
        raise RenderError("validator")
    return result


def command(raw, name, compressor):
    payload = raw + validator(name)
    try:
        packed = v3._compress("preflight", payload, compressor)
    except v3.RenderError as exc:
        raise RenderError("gzip") from exc
    loader = (
        LOADER
        .replace(b"@@N@@", str(len(raw)).encode("ascii"))
        .replace(b"@@H@@", sha(payload).encode("ascii"))
        .replace(b"@@Z@@", base64.b85encode(packed))
    )
    if PLACEHOLDER.search(loader):
        raise RenderError("loader")
    try:
        v3._validate_bash_python("preflight_loader", loader, 1)
    except v3.RenderError as exc:
        raise RenderError("loader") from exc
    encoded = base64.b64encode(loader)
    if len(encoded) > MAX_COMMAND:
        raise RenderError("command_limit")
    return {
        "base64": encoded.decode("ascii"),
        "bytes": len(encoded),
        "sha256": sha(encoded),
    }


def preflight_commands(
    api_c_instance_id,
    api_c_ram_role,
    builder_instance_id,
    builder_ram_role,
    compressor,
):
    api_c = identity(api_c_instance_id, api_c_ram_role)
    builder = builder_identity(builder_instance_id, builder_ram_role)
    api_raw = render(
        "api_c",
        {b"@@API_C_IDENTITY_SHA256@@": api_c.encode("ascii")},
    )
    builder_raw = render(
        "builder",
        {b"@@BUILDER_IDENTITY_SHA256@@": builder.encode("ascii")},
    )
    return {
        "api_c": {
            "command": command(api_raw, "api_c", compressor),
            "identity_sha256": api_c,
            "template": dict(IDENTITIES["api_c"]),
        },
        "builder": {
            "command": command(builder_raw, "builder", compressor),
            "identity_sha256": builder,
            "template": dict(IDENTITIES["builder"]),
        },
    }


def production_compressor():
    try:
        return v3._production_gzip_compressor()
    except v3.RenderError as exc:
        raise RenderError(exc.code) from exc


def cli():
    try:
        raw = sys.stdin.buffer.read(131073)
        request = parse(raw, "request", 131072)
        if set(request) != {
            "api_c_instance_id",
            "api_c_ram_role",
            "builder_instance_id",
            "builder_ram_role",
            "mode",
        } or request.pop("mode") != "preflight":
            raise RenderError("request_contract")
        result = preflight_commands(
            request["api_c_instance_id"],
            request["api_c_ram_role"],
            request["builder_instance_id"],
            request["builder_ram_role"],
            production_compressor(),
        )
        output = canonical(result)
    except RenderError as exc:
        sys.stderr.write("ITEM26_RESTORED_PREFLIGHT_RENDER_FAILED:" + exc.code + "\n")
        return 2
    except BaseException:
        sys.stderr.write("ITEM26_RESTORED_PREFLIGHT_RENDER_FAILED:internal\n")
        return 2
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
