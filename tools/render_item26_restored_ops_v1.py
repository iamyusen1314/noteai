#!/usr/bin/env python3
"""Render the fixed, Secret-free Item 26 restored operational commands."""

from __future__ import annotations

import ast
import base64
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import render_item26_restored_v1_transport as capture
from tools import render_item26_v3_transport as v3

PATHS = MappingProxyType({
    "keygen": ROOT / ".codex/item26-restored-builder-keygen-v1.template.sh",
    "broker": ROOT / ".codex/item26-restored-package-broker-v1.template.sh",
    "rewrap": ROOT / ".codex/item26-password-rewrap.template.sh",
    "stage": ROOT / ".codex/item26-restored-builder-stage-v1.template.sh",
})
IDENTITIES = MappingProxyType({
    "keygen": MappingProxyType({"bytes":10909,"sha256":"ab9c6324365ff4fad4f8c9a6757d41835575f3aa258ac6be2fd42bfc72129b83"}),
    "broker": MappingProxyType({"bytes":26487,"sha256":"7cda962fd965bac66f265ba117b2054fe253351d60bda6d1b3d6b808e9854541"}),
    "rewrap": MappingProxyType({"bytes":34625,"sha256":"d73661b9dc4f2dddc3c6354655361377a0a2323a4adc2c40cd37da0e9ca96082"}),
    "stage": MappingProxyType({"bytes":10562,"sha256":"babdbe7d6daad55db04d1247ec26741cc77925c1c8ba8ca20398bac9de0069e5"}),
})
COUNTS = MappingProxyType({
    "keygen": Counter({b"@@MODE@@":1,b"@@BUILDER_IDENTITY_SHA256@@":1}),
    "broker": Counter({b"@@MODE@@":1,b"@@API_C_IDENTITY_SHA256@@":1,b"@@RESTORED_HOST@@":2,b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":2,b"@@RECIPIENT_PUBLIC_KEY_B64@@":1,b"@@PASSWORD_REWRAP_RESULT_B64@@":1}),
    "rewrap": Counter({b"@@MODE@@":1,b"@@API_C_IDENTITY_SHA256@@":1,b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":2,b"@@RECIPIENT_PUBLIC_KEY_B64@@":1}),
    "stage": Counter({b"@@MODE@@":1,b"@@BUILDER_IDENTITY_SHA256@@":1,b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":1,b"@@ENVELOPE_BYTES@@":1,b"@@ENVELOPE_SHA256@@":1,b"@@TRANSFER_BYTES@@":1,b"@@TRANSFER_SHA256@@":1}),
})
HEX64=re.compile(r"^[0-9a-f]{64}$")
HOST=re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.rds\.aliyuncs\.com$")
PLACEHOLDER=re.compile(br"@@[A-Z][A-Z0-9_]*@@")
SOURCE_BYTES=9794
SOURCE_FILE_SHA="dba5251aaf489358eab6b800dfa43ff108290abd851410da9a16f97b86d0b1f4"
SOURCE_SHA="99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a"
SOURCE_CONTROL_PUBLIC_SHA="dc8f8283248dd232030bb63d19f669ccdaad89faa87dbdffb7b5eb5aae83969a"
BUILDER_RAM_ROLE="noteai-item26-pitr-oss-reader-v1"
MAX_COMMAND=18000
MAX_SENDFILE=18000
LOADER_CONTRACTS=frozenset({"keygen","broker_create","broker_readback","rewrap_create","rewrap_readback","stage_finalize","stage_readback"})
LOADER_TIMEOUTS=MappingProxyType({"keygen":90,"broker_create":240,"broker_readback":90,"rewrap_create":180,"rewrap_readback":90,"stage_finalize":90,"stage_readback":90})

LOADER=b"""#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
exec /usr/bin/python3 -I -B - <<'PY'
import base64 as b,gzip as g,hashlib as h,os
N=@@N@@;H=b"@@H@@";Z=b"@@Z@@";T=@@T@@
FIX=b'{"NOTEAI_ITEM26_RESTORED_OPS_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\\n'
def f():
 try:
  if os.write(2,FIX)!=len(FIX):1/0
 except: pass
 os._exit(4)
try:
 p=g.decompress(b.b85decode(Z))
 if h.sha256(p).digest()!=b.b85decode(H) or not 1<=N<len(p):1/0
 raw=p[:N];exec(p[N:])
except:f()
PY
"""

STRICT_VALIDATOR_PREFIX=b"""import base64,hashlib,json,os,re,signal,subprocess
X=re.compile(r"^[0-9a-f]{64}$")
def nd(p):
 v={}
 for k,x in p:
  if k in v: raise ValueError
  v[k]=x
 return v
def ca(v): return (json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\\n").encode("ascii")
def ex(v,k): return type(v) is dict and set(v)==set(k.split())
def h(v): return type(v) is str and X.fullmatch(v) is not None
def i(v,a,b): return type(v) is int and a<=v<=b
def q(v,x): return type(v) is bool and v is x
def cm(v): return q(v["automatic_retry_allowed"],False) and q(v["same_invocation_replay_allowed"],False)
"""
STRICT_VALIDATOR_CASES=MappingProxyType({
"keygen":b"""F=set("current_preflight machine_preflight mode parent root tool".split());U=set("base_create base_root control_create control_inventory control_root generate later_state_present preexisting_base private_metadata readback unexpected".split())
def ok(v,r):
 if r:
  k="NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN automatic_retry_allowed phase private_key_value_read_count same_invocation_replay_allowed"
  return ex(v,k) and v["NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN"]==("FAIL" if r==3 else "UNKNOWN") and cm(v) and i(v["private_key_value_read_count"],0,0) and type(v["phase"]) is str and v["phase"] in (F if r==3 else U)
 k="NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN automatic_retry_allowed builder_identity_sha256 private_key_created private_key_pair_verified private_key_value_read_count public_der_sha256 public_key_pem_b64 same_invocation_replay_allowed schema_version"
 if not ex(v,k) or v["NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN"]!="PASS" or not cm(v) or not h(v["builder_identity_sha256"]) or not h(v["public_der_sha256"]) or not q(v["private_key_created"],True) or not q(v["private_key_pair_verified"],True) or not i(v["private_key_value_read_count"],1,1) or not i(v["schema_version"],1,1) or type(v["public_key_pem_b64"]) is not str: return False
 try: x=base64.b64decode(v["public_key_pem_b64"],validate=True)
 except: return False
 return len(x)==625 and x.startswith(b"-----BEGIN PUBLIC KEY-----\\n") and x.endswith(b"-----END PUBLIC KEY-----\\n")
""",
"broker_create":b"""F=set("db_socket docker docker_config identity image input_metadata mode parent root tool".split());U=set("base_root broker_root container container_cleanup container_execute docker_config_runtime helper_stderr helper_stdout inventory output preexisting_base promote promote_fsync readback stage_input task_create task_identity unexpected".split())
def ok(v,r):
 if r:
  k="NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER automatic_retry_allowed phase same_invocation_replay_allowed secret_values_emitted"
  return ex(v,k) and v["NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER"]==("FAIL" if r==3 else "UNKNOWN") and cm(v) and i(v["secret_values_emitted"],0,0) and v["phase"] in (F if r==3 else U)
 k="control_envelope_b64 control_envelope_bytes control_envelope_sha256 recipient_public_key_sha256 same_invocation_replay_allowed schema_version secret_values_emitted"
 if not ex(v,k) or not q(v["same_invocation_replay_allowed"],False) or not i(v["schema_version"],1,1) or not i(v["secret_values_emitted"],0,0) or not i(v["control_envelope_bytes"],1,12288) or not h(v["control_envelope_sha256"]) or not h(v["recipient_public_key_sha256"]) or type(v["control_envelope_b64"]) is not str: return False
 try: x=base64.b64decode(v["control_envelope_b64"],validate=True)
 except: return False
 return len(x)==v["control_envelope_bytes"] and hashlib.sha256(x).hexdigest()==v["control_envelope_sha256"]
""",
"broker_readback":b"""R="@@RECIPIENT@@";F={"identity","parent"};U=set("base_root broker_root docker_config_runtime inventory readback unexpected".split())
def ok(v,r):
 if r:
  k="NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER automatic_retry_allowed phase same_invocation_replay_allowed secret_values_emitted"
  return ex(v,k) and v["NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER"]==("FAIL" if r==3 else "UNKNOWN") and cm(v) and i(v["secret_values_emitted"],0,0) and v["phase"] in (F if r==3 else U)
 if not ex(v,"receipt transport"):return False
 p=v["receipt"];t=v["transport"];pk="NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER algorithm automatic_retry_allowed control_envelope_bytes control_envelope_sha256 payload_schema_exact recipient_public_key_sha256 restored_topology_sha256 same_invocation_replay_allowed schema_version secret_values_emitted source_manifest_bytes source_manifest_file_sha256 source_manifest_sha256 storage_config_sha256";tk="control_envelope_b64 control_envelope_bytes control_envelope_sha256 recipient_public_key_sha256 same_invocation_replay_allowed schema_version secret_values_emitted"
 if not ex(p,pk) or not ex(t,tk) or p["NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER"]!="PASS" or p["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM" or not cm(p) or not q(p["payload_schema_exact"],True) or not i(p["schema_version"],1,1) or not i(p["secret_values_emitted"],0,0) or not i(p["control_envelope_bytes"],1,12288) or not i(p["source_manifest_bytes"],9794,9794) or p["source_manifest_file_sha256"]!="dba5251aaf489358eab6b800dfa43ff108290abd851410da9a16f97b86d0b1f4" or p["source_manifest_sha256"]!="99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a" or not all(h(p[x]) for x in ("control_envelope_sha256","recipient_public_key_sha256","restored_topology_sha256","storage_config_sha256")):return False
 if not q(t["same_invocation_replay_allowed"],False) or not i(t["schema_version"],1,1) or not i(t["secret_values_emitted"],0,0) or not i(t["control_envelope_bytes"],1,12288) or not h(t["control_envelope_sha256"]) or t["recipient_public_key_sha256"]!=R or p["recipient_public_key_sha256"]!=R or p["control_envelope_bytes"]!=t["control_envelope_bytes"] or p["control_envelope_sha256"]!=t["control_envelope_sha256"] or type(t["control_envelope_b64"]) is not str:return False
 try:x=base64.b64decode(t["control_envelope_b64"],validate=True)
 except:return False
 return len(x)==t["control_envelope_bytes"] and hashlib.sha256(x).hexdigest()==t["control_envelope_sha256"]
""",
"rewrap_create":b"""R="@@RECIPIENT@@";F=set("preflight root binding tool persistent_parent identity source_control_root source_control_metadata source_control_key_pair source_envelope_contract docker_config docker_service image db_socket_before".split());U=set("preflight root binding tool persistent_parent identity preexisting_persistent_root preexisting_container docker_config_runtime persistent_root_create attempt_commit task_create container_execute container_cleanup helper_stderr result_commit task_cleanup db_socket_after terminal_readback".split())
def ok(v,r):
 if r:
  k="NOTEAI_ITEM26_PASSWORD_REWRAP automatic_retry_allowed database_connection_count database_write_count incident_class new_rewrap_allowed phase provider_control_plane_mutation_count readback_required same_invocation_replay_allowed secret_values_emitted"
  return ex(v,k) and v["NOTEAI_ITEM26_PASSWORD_REWRAP"]==("FAIL" if r==3 else "UNKNOWN") and v["incident_class"]==("PRE_ATTEMPT" if r==3 else "ATTEMPTED_UNKNOWN") and cm(v) and q(v["new_rewrap_allowed"],False) and q(v["readback_required"],r==4) and all(i(v[x],0,0) for x in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted")) and type(v["phase"]) is str and v["phase"] in (F if r==3 else U)
 k="account_exact automatic_retry_allowed database_connection_count database_write_count password_policy_exact provider_control_plane_mutation_count recipient_public_key_sha256 schema_version secret_values_emitted status wrapped_password"
 if not ex(v,k) or v["status"]!="PASSWORD_REWRAPPED" or v["recipient_public_key_sha256"]!=R or not q(v["account_exact"],True) or not q(v["password_policy_exact"],True) or not q(v["automatic_retry_allowed"],False) or not i(v["schema_version"],1,1) or not all(i(v[x],0,0) for x in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted")) or type(v["wrapped_password"]) is not str:return False
 try:x=base64.b64decode(v["wrapped_password"],validate=True)
 except:return False
 return len(x)==384
""",
"rewrap_readback":b"""R="@@RECIPIENT@@";U=set("preflight root binding tool persistent_parent identity docker_config_runtime readback_absent readback_contract".split())
def ok(v,r):
 if r:
  k="NOTEAI_ITEM26_PASSWORD_REWRAP automatic_retry_allowed database_connection_count database_write_count incident_class new_rewrap_allowed phase provider_control_plane_mutation_count readback_required same_invocation_replay_allowed secret_values_emitted"
  return r==4 and ex(v,k) and v["NOTEAI_ITEM26_PASSWORD_REWRAP"]=="UNKNOWN" and v["incident_class"]=="ATTEMPTED_UNKNOWN" and cm(v) and q(v["new_rewrap_allowed"],False) and q(v["readback_required"],True) and all(i(v[x],0,0) for x in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted")) and type(v["phase"]) is str and v["phase"] in U
 k="account_exact automatic_retry_allowed database_connection_count database_write_count password_policy_exact provider_control_plane_mutation_count recipient_public_key_sha256 schema_version secret_values_emitted status wrapped_password"
 if not ex(v,k) or v["status"]!="PASSWORD_REWRAPPED" or v["recipient_public_key_sha256"]!=R or not q(v["account_exact"],True) or not q(v["password_policy_exact"],True) or not q(v["automatic_retry_allowed"],False) or not i(v["schema_version"],1,1) or not all(i(v[x],0,0) for x in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted")) or type(v["wrapped_password"]) is not str:return False
 try:x=base64.b64decode(v["wrapped_password"],validate=True)
 except:return False
 return len(x)==384
""",
"stage_finalize":b"""F={"identity","preflight"};U=set("artifact_absent artifact_hash base_inventory control_inventory duplicate key_pair keygen metadata partial_inventory race receipt receipt_write replay_barrier terminal_inventory unexpected".split())
def er(v,r):
 k="NOTEAI_ITEM26_RESTORED_BUILDER_STAGE automatic_retry_allowed materials_retained new_sendfile_allowed phase same_invocation_replay_allowed secret_values_emitted"+(" readback_required" if r==4 else "")
 return ex(v,k) and v["NOTEAI_ITEM26_RESTORED_BUILDER_STAGE"]==("FAIL" if r==3 else "UNKNOWN") and cm(v) and q(v["materials_retained"],True) and q(v["new_sendfile_allowed"],False) and i(v["secret_values_emitted"],0,0) and type(v["phase"]) is str and v["phase"] in (F if r==3 else U) and (r==3 or q(v["readback_required"],True))
def receipt(v):
 k="NOTEAI_ITEM26_RESTORED_BUILDER_STAGE automatic_retry_allowed builder_identity_sha256 control_inventory_exact envelope_bytes envelope_sha256 materials_retained new_sendfile_allowed recipient_public_key_sha256 same_invocation_replay_allowed schema_version secret_values_emitted transfer_bytes transfer_sha256"
 return ex(v,k) and v["NOTEAI_ITEM26_RESTORED_BUILDER_STAGE"]=="PASS" and cm(v) and q(v["control_inventory_exact"],True) and q(v["materials_retained"],True) and q(v["new_sendfile_allowed"],False) and i(v["schema_version"],1,1) and i(v["secret_values_emitted"],0,0) and i(v["envelope_bytes"],1,12288) and i(v["transfer_bytes"],1,24576) and all(h(v[x]) for x in ("builder_identity_sha256","envelope_sha256","recipient_public_key_sha256","transfer_sha256"))
def ok(v,r): return er(v,r) if r else receipt(v)
""",
"stage_readback":b"""F={"identity","preflight"};U=set("artifact_absent artifact_hash base_inventory control_inventory duplicate key_pair keygen metadata partial_inventory race receipt receipt_write replay_barrier terminal_inventory unexpected".split())
def er(v,r):
 k="NOTEAI_ITEM26_RESTORED_BUILDER_STAGE automatic_retry_allowed materials_retained new_sendfile_allowed phase same_invocation_replay_allowed secret_values_emitted"+(" readback_required" if r==4 else "")
 return ex(v,k) and v["NOTEAI_ITEM26_RESTORED_BUILDER_STAGE"]==("FAIL" if r==3 else "UNKNOWN") and cm(v) and q(v["materials_retained"],True) and q(v["new_sendfile_allowed"],False) and i(v["secret_values_emitted"],0,0) and type(v["phase"]) is str and v["phase"] in (F if r==3 else U) and (r==3 or q(v["readback_required"],True))
def receipt(v):
 k="NOTEAI_ITEM26_RESTORED_BUILDER_STAGE automatic_retry_allowed builder_identity_sha256 control_inventory_exact envelope_bytes envelope_sha256 materials_retained new_sendfile_allowed recipient_public_key_sha256 same_invocation_replay_allowed schema_version secret_values_emitted transfer_bytes transfer_sha256"
 return ex(v,k) and v["NOTEAI_ITEM26_RESTORED_BUILDER_STAGE"]=="PASS" and cm(v) and q(v["control_inventory_exact"],True) and q(v["materials_retained"],True) and q(v["new_sendfile_allowed"],False) and i(v["schema_version"],1,1) and i(v["secret_values_emitted"],0,0) and i(v["envelope_bytes"],1,12288) and i(v["transfer_bytes"],1,24576) and all(h(v[x]) for x in ("builder_identity_sha256","envelope_sha256","recipient_public_key_sha256","transfer_sha256"))
def ok(v,r):
 if r:return er(v,r)
 if receipt(v):return True
 k="NOTEAI_ITEM26_RESTORED_BUILDER_STAGE automatic_retry_allowed finalize_allowed materials_retained new_sendfile_allowed same_invocation_replay_allowed secret_values_emitted";s=v.get("NOTEAI_ITEM26_RESTORED_BUILDER_STAGE") if type(v) is dict else None
 return ex(v,k) and s in {"KEYGEN_ONLY","ENVELOPE_EXACT","READY_TO_FINALIZE"} and cm(v) and q(v["finalize_allowed"],s=="READY_TO_FINALIZE") and q(v["materials_retained"],True) and q(v["new_sendfile_allowed"],False) and i(v["secret_values_emitted"],0,0)
""",
})
STRICT_VALIDATOR_SUFFIX=b"""p=subprocess.Popen(["/bin/bash","-s"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},close_fds=True,start_new_session=True)
try:o,e=p.communicate(raw,timeout=T)
except:
 try:os.killpg(p.pid,signal.SIGKILL)
 except:pass
 try:p.communicate(timeout=10)
 except:pass
 raise
r=p.returncode
if r not in (0,3,4) or len(o)+len(e)>18000 or (r==0 and (e or not o)) or (r in (3,4) and (o or not e)):raise ValueError
x=o if r==0 else e
if not x.endswith(b"\\n") or x.count(b"\\n")!=1 or b"\\r" in x or b"\\x00" in x:raise ValueError
v=json.loads(x.decode("ascii"),object_pairs_hook=nd)
if ca(v)!=x or not ok(v,r):raise ValueError
d=1 if r==0 else 2
if os.write(d,x)!=len(x):raise ValueError
os._exit(r)
"""
def strict_validator(contract,expected_recipient=None):
    try: result=STRICT_VALIDATOR_PREFIX+STRICT_VALIDATOR_CASES[contract]+STRICT_VALIDATOR_SUFFIX
    except KeyError as exc: raise RenderError("loader_contract") from exc
    if contract.startswith("rewrap_") or contract=="broker_readback":
        if type(expected_recipient) is not str or HEX64.fullmatch(expected_recipient) is None or result.count(b"@@RECIPIENT@@")!=1: raise RenderError("loader_recipient")
        result=result.replace(b"@@RECIPIENT@@",expected_recipient.encode("ascii"))
    elif expected_recipient is not None: raise RenderError("loader_recipient")
    if PLACEHOLDER.search(result): raise RenderError("loader_validator")
    return result

class RenderError(ValueError):
    def __init__(self,code):
        ValueError.__init__(self,code); self.code=code

def sha(body): return hashlib.sha256(body).hexdigest()
def canonical(value): return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")
def nodup(pairs):
    value={}
    for key,row in pairs:
        if key in value: raise RenderError("duplicate")
        value[key]=row
    return value
def parse(raw,label,limit=65536):
    if type(raw) is not bytes or not 1<=len(raw)<=limit or not raw.endswith(b"\n") or b"\r" in raw or b"\x00" in raw: raise RenderError(label)
    try: value=json.loads(raw.decode("ascii"),object_pairs_hook=nodup)
    except RenderError: raise
    except BaseException as exc: raise RenderError(label) from exc
    if canonical(value)!=raw or type(value) is not dict: raise RenderError(label)
    return value
def identity(instance,role):
    if type(instance) is not str or re.fullmatch(r"i-[a-z0-9]+",instance) is None or type(role) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,64}",role) is None: raise RenderError("identity")
    return sha(json.dumps({"instance_id":instance,"ram_role":role},ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("ascii"))
def builder_identity(instance,role):
    if role!=BUILDER_RAM_ROLE: raise RenderError("builder_ram_role")
    return identity(instance,role)
def read_template(name):
    path=PATHS[name]; expected=IDENTITIES[name]; before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_size!=expected["bytes"]: raise RenderError(name+"_template")
    body=path.read_bytes()
    if len(body)!=expected["bytes"] or sha(body)!=expected["sha256"] or Counter(PLACEHOLDER.findall(body))!=COUNTS[name]: raise RenderError(name+"_template")
    return body
def _cut(body,start,end):
    if body.count(start)!=1 or body.count(end)!=1: raise RenderError("specialize")
    left=body.index(start); right=body.index(end,left)
    return body[:left]+body[right:]
def _specialize(name,body,mode):
    if name=="rewrap":
        if mode==b"CREATE": return _cut(body,b"\nreadback() {\n",b"\ncreate() {\n")
        if mode==b"READBACK": return _cut(body,b"\ncreate() {\n",b"\nif [ \"$MODE\" = 'READBACK' ]")
    if name=="broker":
        if mode==b"CREATE": return _cut(body,b"\nreadback() {\n",b"\ncreate() {\n")
        if mode==b"READBACK": return _cut(body,b"\ncreate() {\n",b"\ncase \"$MODE\" in\n")
    return body
def render(name,bindings):
    body=read_template(name)
    if set(bindings)!=set(COUNTS[name]): raise RenderError(name+"_bindings")
    for token,value in bindings.items():
        if type(value) is not bytes or not value or any(char in value for char in (b"\n",b"\r",b"\x00")): raise RenderError(name+"_binding")
        body=body.replace(token,value)
    if PLACEHOLDER.search(body): raise RenderError(name+"_residue")
    try:
        v3._validate_bash_python(name,body,{"keygen":3,"broker":7,"rewrap":10,"stage":1}[name])
        mode=bindings.get(b"@@MODE@@")
        body=_specialize(name,body,mode)
        counts={"broker":{b"CREATE":6,b"READBACK":3},"rewrap":{b"CREATE":10,b"READBACK":6}}
        v3._validate_bash_python(name+"_specialized",body,counts.get(name,{}).get(mode,{"keygen":3,"stage":1}.get(name)))
    except v3.RenderError as exc: raise RenderError(name+"_syntax") from exc
    return body
def _wrapper(raw,compressor,contract,timeout,expected_recipient=None):
    if contract not in LOADER_CONTRACTS or type(timeout) is not int or not 1<=timeout<=300: raise RenderError("loader_contract")
    payload=raw+strict_validator(contract,expected_recipient)
    try: packed=v3._compress("ops",payload,compressor)
    except v3.RenderError as exc: raise RenderError("gzip") from exc
    result=LOADER.replace(b"@@N@@",str(len(raw)).encode()).replace(b"@@H@@",base64.b85encode(hashlib.sha256(payload).digest())).replace(b"@@Z@@",base64.b85encode(packed)).replace(b"@@T@@",str(timeout).encode())
    if PLACEHOLDER.search(result): raise RenderError("loader")
    try: v3._validate_bash_python("ops_loader",result,1)
    except v3.RenderError as exc: raise RenderError("loader") from exc
    return command(result)
def wrapper(raw,compressor,contract,expected_recipient=None): return _wrapper(raw,compressor,contract,LOADER_TIMEOUTS[contract] if contract in LOADER_CONTRACTS else 0,expected_recipient)
def _wrapper_for_test(raw,compressor,contract,timeout=1,expected_recipient=None): return _wrapper(raw,compressor,contract,timeout,expected_recipient)
def command(raw):
    encoded=base64.b64encode(raw)
    if len(encoded)>MAX_COMMAND: raise RenderError("command_limit")
    return {"base64":encoded.decode("ascii"),"bytes":len(encoded),"sha256":sha(encoded)}
def keygen_commands(builder_instance_id,builder_ram_role,compressor):
    builder=builder_identity(builder_instance_id,builder_ram_role); template=read_template("keygen")
    result={}
    for mode in ("GENERATE","READBACK"):
        raw=render("keygen",{b"@@MODE@@":mode.encode(),b"@@BUILDER_IDENTITY_SHA256@@":builder.encode()})
        result[mode.lower()]=wrapper(raw,compressor,"keygen")
    return {"builder_identity_sha256":builder,"commands":result,"template":dict(IDENTITIES["keygen"])}
def public_key(raw):
    if len(raw)!=625 or not raw.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not raw.endswith(b"-----END PUBLIC KEY-----\n"): raise RenderError("public_key")
    process=subprocess.run(["/usr/bin/openssl","pkey","-pubin","-outform","DER"],input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=10)
    if process.returncode or process.stderr or not process.stdout: raise RenderError("public_key")
    return sha(process.stdout)
def rewrap_commands(api_c_instance_id,api_c_ram_role,public,compressor):
    api_identity=identity(api_c_instance_id,api_c_ram_role); recipient=public_key(public)
    if recipient==SOURCE_CONTROL_PUBLIC_SHA: raise RenderError("recipient_reuse")
    common={b"@@API_C_IDENTITY_SHA256@@":api_identity.encode(),b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":recipient.encode(),b"@@RECIPIENT_PUBLIC_KEY_B64@@":base64.b64encode(public)}
    commands={}
    for mode in ("CREATE","READBACK"):
        bindings=dict(common); bindings[b"@@MODE@@"]=mode.encode(); contract="rewrap_"+mode.lower(); commands[mode.lower()]=wrapper(render("rewrap",bindings),compressor,contract,recipient)
    return {"api_c_identity_sha256":api_identity,"commands":commands,"recipient_public_key_sha256":recipient,"template":dict(IDENTITIES["rewrap"])}
def validate_rewrap(raw,recipient):
    value=parse(raw,"rewrap",1200)
    expected={"account_exact","automatic_retry_allowed","database_connection_count","database_write_count","password_policy_exact","provider_control_plane_mutation_count","recipient_public_key_sha256","schema_version","secret_values_emitted","status","wrapped_password"}
    if set(value)!=expected or type(value["schema_version"]) is not int or value["schema_version"]!=1 or value["status"]!="PASSWORD_REWRAPPED" or value["recipient_public_key_sha256"]!=recipient or value["account_exact"] is not True or value["password_policy_exact"] is not True or value["automatic_retry_allowed"] is not False or type(value["wrapped_password"]) is not str or any(type(value[key]) is not int or value[key]!=0 for key in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted")): raise RenderError("rewrap")
    try: wrapped=base64.b64decode(value["wrapped_password"],validate=True)
    except BaseException as exc: raise RenderError("rewrap") from exc
    if len(wrapped)!=384: raise RenderError("rewrap")
def broker_commands(api_c_instance_id,api_c_ram_role,restored_host,public,rewrap,compressor):
    api_identity=identity(api_c_instance_id,api_c_ram_role)
    if type(restored_host) is not str or not restored_host.isascii() or HOST.fullmatch(restored_host) is None or any(char in restored_host for char in "'\"`$\\"): raise RenderError("restored_host")
    recipient=public_key(public); validate_rewrap(rewrap,recipient)
    common={b"@@API_C_IDENTITY_SHA256@@":api_identity.encode(),b"@@RESTORED_HOST@@":restored_host.encode(),b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":recipient.encode(),b"@@RECIPIENT_PUBLIC_KEY_B64@@":base64.b64encode(public),b"@@PASSWORD_REWRAP_RESULT_B64@@":base64.b64encode(rewrap)}
    commands={}
    for mode in ("CREATE","READBACK"):
        bindings=dict(common); bindings[b"@@MODE@@"]=mode.encode(); contract="broker_"+mode.lower(); commands[mode.lower()]=wrapper(render("broker",bindings),compressor,contract,recipient if mode=="READBACK" else None)
    state_machine={"create":{"0":"READBACK_REQUIRED","3":"STOP","4":"READBACK_REQUIRED"},"post_broker_requires_composite":True,"readback":{"0":"POST_BROKER_ALLOWED","3":"STOP","4":"STOP"},"readback_dispatch_count":1}
    return {"api_c_identity_sha256":api_identity,"commands":commands,"recipient_public_key_sha256":recipient,"state_machine":state_machine,"template":dict(IDENTITIES["broker"])}
def validate_keygen(value,builder):
    expected={"NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN","automatic_retry_allowed","builder_identity_sha256","private_key_created","private_key_pair_verified","private_key_value_read_count","public_der_sha256","public_key_pem_b64","same_invocation_replay_allowed","schema_version"}
    if set(value)!=expected or value["NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN"]!="PASS" or type(value["schema_version"]) is not int or value["schema_version"]!=1 or value["builder_identity_sha256"]!=builder or value["private_key_created"] is not True or value["private_key_pair_verified"] is not True or type(value["private_key_value_read_count"]) is not int or value["private_key_value_read_count"]!=1 or value["automatic_retry_allowed"] is not False or value["same_invocation_replay_allowed"] is not False or type(value["public_key_pem_b64"]) is not str: raise RenderError("keygen_result")
    try: public=base64.b64decode(value["public_key_pem_b64"],validate=True)
    except BaseException as exc: raise RenderError("keygen_result") from exc
    if public_key(public)!=value["public_der_sha256"]: raise RenderError("keygen_result")
    return value["public_der_sha256"]
def validate_broker_transport(create,recipient):
    create_keys={"control_envelope_b64","control_envelope_bytes","control_envelope_sha256","recipient_public_key_sha256","same_invocation_replay_allowed","schema_version","secret_values_emitted"}
    if set(create)!=create_keys or type(create["schema_version"]) is not int or create["schema_version"]!=1 or create["recipient_public_key_sha256"]!=recipient or create["same_invocation_replay_allowed"] is not False or type(create["secret_values_emitted"]) is not int or create["secret_values_emitted"]!=0 or type(create["control_envelope_bytes"]) is not int or type(create["control_envelope_b64"]) is not str: raise RenderError("broker_create")
    try: envelope=base64.b64decode(create["control_envelope_b64"],validate=True)
    except BaseException as exc: raise RenderError("broker_create") from exc
    capture._validate_control_envelope(envelope)
    if create["control_envelope_bytes"]!=len(envelope) or create["control_envelope_sha256"]!=sha(envelope): raise RenderError("broker_create")
    return envelope
def validate_broker(composite,recipient,create=None):
    if type(composite) is not dict or set(composite)!={"receipt","transport"} or type(composite["receipt"]) is not dict or type(composite["transport"]) is not dict: raise RenderError("broker_readback")
    receipt=composite["receipt"]; transport=composite["transport"]; envelope=validate_broker_transport(transport,recipient)
    keys={"NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER","algorithm","automatic_retry_allowed","control_envelope_bytes","control_envelope_sha256","payload_schema_exact","recipient_public_key_sha256","restored_topology_sha256","same_invocation_replay_allowed","schema_version","secret_values_emitted","source_manifest_bytes","source_manifest_file_sha256","source_manifest_sha256","storage_config_sha256"}
    if set(receipt)!=keys or receipt["NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER"]!="PASS" or receipt["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM" or type(receipt["schema_version"]) is not int or receipt["schema_version"]!=1 or type(receipt["control_envelope_bytes"]) is not int or receipt["control_envelope_bytes"]!=len(envelope) or receipt["control_envelope_sha256"]!=sha(envelope) or receipt["recipient_public_key_sha256"]!=recipient or type(receipt["source_manifest_bytes"]) is not int or receipt["source_manifest_bytes"]!=SOURCE_BYTES or receipt["source_manifest_file_sha256"]!=SOURCE_FILE_SHA or receipt["source_manifest_sha256"]!=SOURCE_SHA or receipt["payload_schema_exact"] is not True or receipt["automatic_retry_allowed"] is not False or receipt["same_invocation_replay_allowed"] is not False or type(receipt["secret_values_emitted"]) is not int or receipt["secret_values_emitted"]!=0 or any(type(receipt[key]) is not str or HEX64.fullmatch(receipt[key]) is None for key in ("restored_topology_sha256","storage_config_sha256")): raise RenderError("broker_readback")
    if create is not None:
        validate_broker_transport(create,recipient)
        if create!=transport: raise RenderError("broker_create_mismatch")
    return envelope,receipt
def stage_bindings(mode,builder,recipient,envelope,transfer):
    return {b"@@MODE@@":mode.encode(),b"@@BUILDER_IDENTITY_SHA256@@":builder.encode(),b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":recipient.encode(),b"@@ENVELOPE_BYTES@@":str(len(envelope)).encode(),b"@@ENVELOPE_SHA256@@":sha(envelope).encode(),b"@@TRANSFER_BYTES@@":str(len(transfer)).encode(),b"@@TRANSFER_SHA256@@":sha(transfer).encode()}
def sendfile(name,target_dir,body,builder_instance_id):
    encoded=base64.b64encode(body)
    if len(body)>24576 or len(encoded)>MAX_SENDFILE: raise RenderError("sendfile_limit")
    request={"Content":encoded.decode("ascii"),"ContentType":"Base64","Description":"noteai-item26-restored-v1-write-once","FileGroup":"root","FileMode":"0600","FileOwner":"root","InstanceId":[builder_instance_id],"Name":name,"Overwrite":False,"RegionId":"cn-shenzhen","Tag":[{"Key":"noteai-task","Value":"item26-restored-v1"}],"TargetDir":target_dir}
    return {"evidence":{"content_base64_bytes":len(encoded),"content_sha256":sha(body)},"request":request}
def _post_broker_context(builder_instance_id,builder_ram_role,keygen_raw,readback_raw,create_raw=None):
    builder=builder_identity(builder_instance_id,builder_ram_role); keygen=parse(keygen_raw,"keygen_result",4096); recipient=validate_keygen(keygen,builder)
    composite=parse(readback_raw,"broker_readback",18000); create=parse(create_raw,"broker_create",18000) if create_raw is not None else None; envelope,receipt=validate_broker(composite,recipient,create)
    return builder,recipient,envelope,receipt
def _assemble_post_broker(builder_instance_id,builder,recipient,envelope,receipt,artifacts,capture_command,compressor,capture_summary=None,capture_sizing=None):
    transfer=artifacts["capture_gzip"]
    finalize=wrapper(render("stage",stage_bindings("FINALIZE",builder,recipient,envelope,transfer)),compressor,"stage_finalize")
    readback=wrapper(render("stage",stage_bindings("READBACK",builder,recipient,envelope,transfer)),compressor,"stage_readback")
    files=[sendfile("control-envelope.json","/var/lib/noteai/item26-restored-v1/control",envelope,builder_instance_id),sendfile("restored-capture-transfer-v1.sh.gz","/var/lib/noteai/item26-restored-v1",transfer,builder_instance_id)]
    result={"builder_identity_sha256":builder,"capture_command_content":capture_command,"control_envelope_bytes":len(envelope),"control_envelope_sha256":sha(envelope),"finalize_command":finalize,"readback_command":readback,"recipient_public_key_sha256":recipient,"send_files":files,"source_manifest_bytes":SOURCE_BYTES,"source_manifest_file_sha256":SOURCE_FILE_SHA,"source_manifest_sha256":SOURCE_SHA,"stage_template":dict(IDENTITIES["stage"]),"transfer_bytes":len(transfer),"transfer_sha256":sha(transfer)}
    if capture_summary is not None: result["capture_summary"]=capture_summary
    if capture_sizing is not None: result["capture_sizing"]=capture_sizing
    return result
def _validated_production_render(rendered,envelope):
    if type(rendered) is not dict or set(rendered)!={"artifacts","summary"} or type(rendered["artifacts"]) is not dict or set(rendered["artifacts"])!=set(capture.SUMMARY_LAYER_NAMES): raise RenderError("capture_render")
    try: summary=json.loads(capture.canonical_summary(rendered["summary"]).decode("ascii"),object_pairs_hook=nodup)
    except (capture.RenderError,RenderError,UnicodeError,json.JSONDecodeError) as exc: raise RenderError("capture_summary") from exc
    for name in capture.SUMMARY_LAYER_NAMES:
        body=rendered["artifacts"].get(name)
        if type(body) is not bytes or len(body)!=summary[name]["bytes"] or sha(body)!=summary[name]["sha256"]: raise RenderError("capture_artifact")
    if rendered["artifacts"]["control_envelope"]!=envelope: raise RenderError("capture_envelope")
    return rendered["artifacts"],summary
def post_broker(builder_instance_id,builder_ram_role,keygen_raw,readback_raw,create_raw=None):
    builder,recipient,envelope,receipt=_post_broker_context(builder_instance_id,builder_ram_role,keygen_raw,readback_raw,create_raw)
    rendered=capture.render_item26_restored_v1_transport(envelope,recipient,builder,SOURCE_BYTES,SOURCE_FILE_SHA,SOURCE_SHA,receipt["restored_topology_sha256"],receipt["storage_config_sha256"])
    artifacts,summary=_validated_production_render(rendered,envelope)
    return _assemble_post_broker(builder_instance_id,builder,recipient,envelope,receipt,artifacts,summary["capture_command_content"],production_compressor(),capture_summary=summary)
def _post_broker_for_test(builder_instance_id,builder_ram_role,keygen_raw,readback_raw,create_raw,compressor):
    builder,recipient,envelope,receipt=_post_broker_context(builder_instance_id,builder_ram_role,keygen_raw,readback_raw,create_raw)
    rendered=capture._render_item26_restored_v1_transport_for_test(envelope,recipient,builder,SOURCE_BYTES,SOURCE_FILE_SHA,SOURCE_SHA,receipt["restored_topology_sha256"],receipt["storage_config_sha256"],gzip_compressor=compressor)
    return _assemble_post_broker(builder_instance_id,builder,recipient,envelope,receipt,rendered["artifacts"],rendered["sizing"]["capture_command_content"],compressor,capture_sizing=rendered["sizing"])
def production_compressor():
    try: return v3._production_gzip_compressor()
    except v3.RenderError as exc: raise RenderError(exc.code) from exc
def decode(value,label):
    try: return base64.b64decode(value,validate=True)
    except BaseException as exc: raise RenderError(label) from exc
def cli():
    try:
        raw=sys.stdin.buffer.read(131073); request=parse(raw,"request",131072); mode=request.pop("mode",None)
        if mode=="keygen" and set(request)=={"builder_instance_id","builder_ram_role"}: result=keygen_commands(request["builder_instance_id"],request["builder_ram_role"],production_compressor())
        elif mode=="rewrap" and set(request)=={"api_c_instance_id","api_c_ram_role","recipient_public_key_pem_base64"}: result=rewrap_commands(request["api_c_instance_id"],request["api_c_ram_role"],decode(request["recipient_public_key_pem_base64"],"public_key"),production_compressor())
        elif mode=="broker" and set(request)=={"api_c_instance_id","api_c_ram_role","password_rewrap_result_base64","recipient_public_key_pem_base64","restored_host"}: result=broker_commands(request["api_c_instance_id"],request["api_c_ram_role"],request["restored_host"],decode(request["recipient_public_key_pem_base64"],"public_key"),decode(request["password_rewrap_result_base64"],"rewrap"),production_compressor())
        elif mode=="post_broker" and set(request) in ({"broker_readback_result_base64","builder_instance_id","builder_ram_role","keygen_result_base64"},{"broker_create_result_base64","broker_readback_result_base64","builder_instance_id","builder_ram_role","keygen_result_base64"}): result=post_broker(request["builder_instance_id"],request["builder_ram_role"],decode(request["keygen_result_base64"],"keygen_result"),decode(request["broker_readback_result_base64"],"broker_readback"),decode(request["broker_create_result_base64"],"broker_create") if "broker_create_result_base64" in request else None)
        else: raise RenderError("request_contract")
        output=canonical(result)
    except RenderError as exc:
        sys.stderr.write("ITEM26_RESTORED_OPS_RENDER_FAILED:"+exc.code+"\n"); return 2
    except BaseException:
        sys.stderr.write("ITEM26_RESTORED_OPS_RENDER_FAILED:internal\n"); return 2
    sys.stdout.buffer.write(output); return 0
if __name__=="__main__": raise SystemExit(cli())
