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
    "stage": ROOT / ".codex/item26-restored-builder-stage-v1.template.sh",
})
IDENTITIES = MappingProxyType({
    "keygen": MappingProxyType({"bytes":10007,"sha256":"91f6c99049ab9eb5fe5ef13427d4adcd93af99a85d5ab90306c1e4360ddcb32d"}),
    "broker": MappingProxyType({"bytes":24197,"sha256":"d5c0176cc8c8a9700cc7c590b9fe40052db811d6d44e9742a13a3c333b34e15d"}),
    "stage": MappingProxyType({"bytes":10562,"sha256":"babdbe7d6daad55db04d1247ec26741cc77925c1c8ba8ca20398bac9de0069e5"}),
})
COUNTS = MappingProxyType({
    "keygen": Counter({b"@@MODE@@":1,b"@@BUILDER_IDENTITY_SHA256@@":1}),
    "broker": Counter({b"@@MODE@@":1,b"@@API_C_IDENTITY_SHA256@@":1,b"@@RESTORED_HOST@@":2,b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":2,b"@@RECIPIENT_PUBLIC_KEY_B64@@":1,b"@@PASSWORD_REWRAP_RESULT_B64@@":1}),
    "stage": Counter({b"@@MODE@@":1,b"@@BUILDER_IDENTITY_SHA256@@":1,b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":1,b"@@ENVELOPE_BYTES@@":1,b"@@ENVELOPE_SHA256@@":1,b"@@TRANSFER_BYTES@@":1,b"@@TRANSFER_SHA256@@":1}),
})
HEX64=re.compile(r"^[0-9a-f]{64}$")
HOST=re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.rds\.aliyuncs\.com$")
PLACEHOLDER=re.compile(br"@@[A-Z][A-Z0-9_]*@@")
SOURCE_BYTES=9794
SOURCE_FILE_SHA="dba5251aaf489358eab6b800dfa43ff108290abd851410da9a16f97b86d0b1f4"
SOURCE_SHA="99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a"
MAX_COMMAND=18000
MAX_SENDFILE=18000

LOADER=b"""#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
exec python3 -I -B - <<'PY'
import base64,gzip,hashlib,os,subprocess
N=@@N@@
H="@@H@@"
Z=b"@@Z@@"
try:
 raw=gzip.decompress(base64.b85decode(Z))
 if len(raw)!=N or hashlib.sha256(raw).hexdigest()!=H: raise ValueError("hash")
 process=subprocess.Popen(["/bin/bash","-s"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"})
 out,err=process.communicate(raw)
except BaseException:
 os.write(2,b'{"NOTEAI_ITEM26_RESTORED_OPS_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\\n')
 os._exit(4)
if out: os.write(1,out)
if err: os.write(2,err)
os._exit(process.returncode)
PY
"""

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
def read_template(name):
    path=PATHS[name]; expected=IDENTITIES[name]; before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_size!=expected["bytes"]: raise RenderError(name+"_template")
    body=path.read_bytes()
    if len(body)!=expected["bytes"] or sha(body)!=expected["sha256"] or Counter(PLACEHOLDER.findall(body))!=COUNTS[name]: raise RenderError(name+"_template")
    return body
def render(name,bindings):
    body=read_template(name)
    if set(bindings)!=set(COUNTS[name]): raise RenderError(name+"_bindings")
    for token,value in bindings.items():
        if type(value) is not bytes or not value or any(char in value for char in (b"\n",b"\r",b"\x00")): raise RenderError(name+"_binding")
        body=body.replace(token,value)
    if PLACEHOLDER.search(body): raise RenderError(name+"_residue")
    try:
        v3._validate_bash_python(name,body,{"keygen":3,"broker":7,"stage":1}[name])
    except v3.RenderError as exc: raise RenderError(name+"_syntax") from exc
    return body
def wrapper(raw,compressor):
    try: packed=v3._compress("ops",raw,compressor)
    except v3.RenderError as exc: raise RenderError("gzip") from exc
    result=LOADER.replace(b"@@N@@",str(len(raw)).encode()).replace(b"@@H@@",sha(raw).encode()).replace(b"@@Z@@",base64.b85encode(packed))
    if PLACEHOLDER.search(result): raise RenderError("loader")
    try: v3._validate_bash_python("ops_loader",result,1)
    except v3.RenderError as exc: raise RenderError("loader") from exc
    return command(result)
def command(raw):
    encoded=base64.b64encode(raw)
    if len(encoded)>MAX_COMMAND: raise RenderError("command_limit")
    return {"base64":encoded.decode("ascii"),"bytes":len(encoded),"sha256":sha(encoded)}
def keygen_commands(builder_instance_id,builder_ram_role,compressor):
    builder=identity(builder_instance_id,builder_ram_role); template=read_template("keygen")
    result={}
    for mode in ("GENERATE","READBACK"):
        raw=render("keygen",{b"@@MODE@@":mode.encode(),b"@@BUILDER_IDENTITY_SHA256@@":builder.encode()})
        result[mode.lower()]=wrapper(raw,compressor)
    return {"builder_identity_sha256":builder,"commands":result,"template":dict(IDENTITIES["keygen"])}
def public_key(raw):
    if len(raw)!=625 or not raw.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not raw.endswith(b"-----END PUBLIC KEY-----\n"): raise RenderError("public_key")
    process=subprocess.run(["/usr/bin/openssl","pkey","-pubin","-outform","DER"],input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=10)
    if process.returncode or process.stderr or not process.stdout: raise RenderError("public_key")
    return sha(process.stdout)
def validate_rewrap(raw,recipient):
    value=parse(raw,"rewrap",1200)
    expected={"account_exact","automatic_retry_allowed","database_connection_count","database_write_count","password_policy_exact","provider_control_plane_mutation_count","recipient_public_key_sha256","schema_version","secret_values_emitted","status","wrapped_password"}
    if set(value)!=expected or value["schema_version"]!=1 or value["status"]!="PASSWORD_REWRAPPED" or value["recipient_public_key_sha256"]!=recipient or value["account_exact"] is not True or value["password_policy_exact"] is not True or value["automatic_retry_allowed"] is not False or any(value[key]!=0 for key in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted")): raise RenderError("rewrap")
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
        bindings=dict(common); bindings[b"@@MODE@@"]=mode.encode(); commands[mode.lower()]=wrapper(render("broker",bindings),compressor)
    return {"api_c_identity_sha256":api_identity,"commands":commands,"recipient_public_key_sha256":recipient,"template":dict(IDENTITIES["broker"])}
def validate_keygen(value,builder):
    expected={"NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN","automatic_retry_allowed","builder_identity_sha256","private_key_created","private_key_pair_verified","private_key_value_read_count","public_der_sha256","public_key_pem_b64","same_invocation_replay_allowed","schema_version"}
    if set(value)!=expected or value["NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN"]!="PASS" or value["schema_version"]!=1 or value["builder_identity_sha256"]!=builder or value["private_key_created"] is not True or value["private_key_pair_verified"] is not True or value["private_key_value_read_count"]!=1 or value["automatic_retry_allowed"] is not False or value["same_invocation_replay_allowed"] is not False: raise RenderError("keygen_result")
    try: public=base64.b64decode(value["public_key_pem_b64"],validate=True)
    except BaseException as exc: raise RenderError("keygen_result") from exc
    if public_key(public)!=value["public_der_sha256"]: raise RenderError("keygen_result")
    return value["public_der_sha256"]
def validate_broker(create,receipt,recipient):
    create_keys={"control_envelope_b64","control_envelope_bytes","control_envelope_sha256","recipient_public_key_sha256","same_invocation_replay_allowed","schema_version","secret_values_emitted"}
    if set(create)!=create_keys or create["schema_version"]!=1 or create["recipient_public_key_sha256"]!=recipient or create["same_invocation_replay_allowed"] is not False or create["secret_values_emitted"]!=0: raise RenderError("broker_create")
    try: envelope=base64.b64decode(create["control_envelope_b64"],validate=True)
    except BaseException as exc: raise RenderError("broker_create") from exc
    capture._validate_control_envelope(envelope)
    if create["control_envelope_bytes"]!=len(envelope) or create["control_envelope_sha256"]!=sha(envelope): raise RenderError("broker_create")
    keys={"NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER","algorithm","automatic_retry_allowed","control_envelope_bytes","control_envelope_sha256","payload_schema_exact","recipient_public_key_sha256","restored_topology_sha256","same_invocation_replay_allowed","schema_version","secret_values_emitted","source_manifest_bytes","source_manifest_file_sha256","source_manifest_sha256","storage_config_sha256"}
    if set(receipt)!=keys or receipt["NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER"]!="PASS" or receipt["schema_version"]!=1 or receipt["control_envelope_bytes"]!=len(envelope) or receipt["control_envelope_sha256"]!=sha(envelope) or receipt["recipient_public_key_sha256"]!=recipient or receipt["source_manifest_bytes"]!=SOURCE_BYTES or receipt["source_manifest_file_sha256"]!=SOURCE_FILE_SHA or receipt["source_manifest_sha256"]!=SOURCE_SHA or receipt["payload_schema_exact"] is not True or receipt["automatic_retry_allowed"] is not False or receipt["same_invocation_replay_allowed"] is not False or receipt["secret_values_emitted"]!=0 or any(HEX64.fullmatch(receipt[key]) is None for key in ("restored_topology_sha256","storage_config_sha256")): raise RenderError("broker_readback")
    return envelope
def stage_bindings(mode,builder,recipient,envelope,transfer):
    return {b"@@MODE@@":mode.encode(),b"@@BUILDER_IDENTITY_SHA256@@":builder.encode(),b"@@RECIPIENT_PUBLIC_KEY_SHA256@@":recipient.encode(),b"@@ENVELOPE_BYTES@@":str(len(envelope)).encode(),b"@@ENVELOPE_SHA256@@":sha(envelope).encode(),b"@@TRANSFER_BYTES@@":str(len(transfer)).encode(),b"@@TRANSFER_SHA256@@":sha(transfer).encode()}
def sendfile(name,target_dir,body,builder_instance_id):
    encoded=base64.b64encode(body)
    if len(body)>24576 or len(encoded)>MAX_SENDFILE: raise RenderError("sendfile_limit")
    return {"Content":encoded.decode("ascii"),"ContentType":"Base64","Description":"noteai-item26-restored-v1-write-once","FileGroup":"root","FileMode":"0600","FileOwner":"root","InstanceId":[builder_instance_id],"Name":name,"Overwrite":False,"RegionId":"cn-shenzhen","Tag":[{"Key":"noteai-task","Value":"item26-restored-v1"}],"TargetDir":target_dir,"content_base64_bytes":len(encoded),"content_sha256":sha(body)}
def post_broker(builder_instance_id,builder_ram_role,keygen_raw,create_raw,readback_raw,compressor):
    builder=identity(builder_instance_id,builder_ram_role); keygen=parse(keygen_raw,"keygen_result",4096); recipient=validate_keygen(keygen,builder)
    create=parse(create_raw,"broker_create",18000); receipt=parse(readback_raw,"broker_readback",4096); envelope=validate_broker(create,receipt,recipient)
    rendered=capture._render_item26_restored_v1_transport_for_test(envelope,recipient,builder,SOURCE_BYTES,SOURCE_FILE_SHA,SOURCE_SHA,receipt["restored_topology_sha256"],receipt["storage_config_sha256"],gzip_compressor=compressor)
    transfer=rendered["artifacts"]["capture_gzip"]
    finalize=wrapper(render("stage",stage_bindings("FINALIZE",builder,recipient,envelope,transfer)),compressor)
    readback=wrapper(render("stage",stage_bindings("READBACK",builder,recipient,envelope,transfer)),compressor)
    files=[sendfile("control-envelope.json","/var/lib/noteai/item26-restored-v1/control",envelope,builder_instance_id),sendfile("restored-capture-transfer-v1.sh.gz","/var/lib/noteai/item26-restored-v1",transfer,builder_instance_id)]
    return {"builder_identity_sha256":builder,"capture_command_content":rendered["sizing"]["capture_command_content"],"control_envelope_bytes":len(envelope),"control_envelope_sha256":sha(envelope),"finalize_command":finalize,"readback_command":readback,"recipient_public_key_sha256":recipient,"send_files":files,"source_manifest_bytes":SOURCE_BYTES,"source_manifest_file_sha256":SOURCE_FILE_SHA,"source_manifest_sha256":SOURCE_SHA,"stage_template":dict(IDENTITIES["stage"]),"transfer_bytes":len(transfer),"transfer_sha256":sha(transfer)}
def production_compressor():
    try: return v3._production_gzip_compressor()
    except v3.RenderError as exc: raise RenderError(exc.code) from exc
def decode(value,label):
    try: return base64.b64decode(value,validate=True)
    except BaseException as exc: raise RenderError(label) from exc
def cli():
    try:
        raw=sys.stdin.buffer.read(131073); request=parse(raw,"request",131072); mode=request.pop("mode",None); compressor=production_compressor()
        if mode=="keygen" and set(request)=={"builder_instance_id","builder_ram_role"}: result=keygen_commands(request["builder_instance_id"],request["builder_ram_role"],compressor)
        elif mode=="broker" and set(request)=={"api_c_instance_id","api_c_ram_role","password_rewrap_result_base64","recipient_public_key_pem_base64","restored_host"}: result=broker_commands(request["api_c_instance_id"],request["api_c_ram_role"],request["restored_host"],decode(request["recipient_public_key_pem_base64"],"public_key"),decode(request["password_rewrap_result_base64"],"rewrap"),compressor)
        elif mode=="post_broker" and set(request)=={"broker_create_result_base64","broker_readback_result_base64","builder_instance_id","builder_ram_role","keygen_result_base64"}: result=post_broker(request["builder_instance_id"],request["builder_ram_role"],decode(request["keygen_result_base64"],"keygen_result"),decode(request["broker_create_result_base64"],"broker_create"),decode(request["broker_readback_result_base64"],"broker_readback"),compressor)
        else: raise RenderError("request_contract")
        output=canonical(result)
    except RenderError as exc:
        sys.stderr.write("ITEM26_RESTORED_OPS_RENDER_FAILED:"+exc.code+"\n"); return 2
    except BaseException:
        sys.stderr.write("ITEM26_RESTORED_OPS_RENDER_FAILED:internal\n"); return 2
    sys.stdout.buffer.write(output); return 0
if __name__=="__main__": raise SystemExit(cli())
