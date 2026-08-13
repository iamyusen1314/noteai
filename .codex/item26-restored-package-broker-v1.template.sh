#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset DATABASE_URL PGPASSWORD ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN

readonly MODE='@@MODE@@'
readonly BASE_ROOT='/var/lib/noteai/item26-restored-v1'
readonly BROKER_ROOT="$BASE_ROOT/broker-v1"
readonly ENVELOPE="$BROKER_ROOT/control-envelope.json"
readonly RECEIPT="$BROKER_ROOT/broker-receipt.json"
readonly TASK_ROOT="$BASE_ROOT/broker-task-v1"
readonly DRIVER="$TASK_ROOT/driver.py"
readonly HELPER_OUT="$TASK_ROOT/helper.stdout"
readonly HELPER_ERR="$TASK_ROOT/helper.stderr"
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly CIDFILE="$TASK_ROOT/container.cid"
readonly SOURCE_MANIFEST='/run/noteai-item26-source-manifest-v3/source-manifest.json'
readonly API_ENV='/etc/noteai/api.env'
readonly STORAGE_ENV='/etc/noteai/storage.env'
readonly RECIPIENT_PUBLIC="$TASK_ROOT/recipient-public.pem"
readonly REWRAP_RESULT="$TASK_ROOT/password-rewrap.json"
readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly RELEASE_COMMIT='cad5ce35664f617c6e19f90a6159285ddf975594'
readonly API_C_IDENTITY_SHA256='@@API_C_IDENTITY_SHA256@@'
readonly RESTORED_HOST='@@RESTORED_HOST@@'
readonly RECIPIENT_PUBLIC_KEY_SHA256='@@RECIPIENT_PUBLIC_KEY_SHA256@@'
readonly RAM_ROLE='noteai-item26-pitr-oss-reader-v1'
readonly CONTAINER_NAME='noteai-item26-restored-package-broker-v1'
readonly CONTAINER_LABEL='com.noteai.task=PROD-FIRST-LAUNCH-PITR-RESTORE-001-restored-package-broker-v1'

task_identity=''
container_attempted=0

metadata_identity() {
  python3 -I -B - "$API_C_IDENTITY_SHA256" <<'PY'
import hashlib,json,re,sys,urllib.request
expected=sys.argv[1]
if re.fullmatch(r"[0-9a-f]{64}",expected) is None: raise SystemExit(2)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl): raise RuntimeError("redirect")
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
req=urllib.request.Request("http://100.100.100.200/latest/api/token",method="PUT",headers={"X-aliyun-ecs-metadata-token-ttl-seconds":"60"})
with opener.open(req,timeout=3) as response: token=response.read(512).decode("ascii").strip()
if not token or len(token)>256: raise SystemExit(2)
headers={"X-aliyun-ecs-metadata-token":token}; values=[]
for suffix in ("instance-id","ram/security-credentials/"):
    req=urllib.request.Request("http://100.100.100.200/latest/meta-data/"+suffix,headers=headers,method="GET")
    with opener.open(req,timeout=3) as response: body=response.read(4096)
    if len(body)>=4096: raise SystemExit(2)
    values.append(body.decode("ascii").strip())
roles=[row for row in values[1].splitlines() if row]
if not re.fullmatch(r"i-[a-z0-9]+",values[0]) or len(roles)!=1: raise SystemExit(2)
body=json.dumps({"instance_id":values[0],"ram_role":roles[0]},ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("ascii")
if hashlib.sha256(body).hexdigest()!=expected: raise SystemExit(2)
print("API_C_IDENTITY_EXACT")
PY
}

read_full_cid() {
  python3 -I -B - "$CIDFILE" <<'PY'
import os,re,stat,sys
p=sys.argv[1]; row=os.lstat(p)
if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not 64<=row.st_size<=65: raise SystemExit(2)
fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
try: raw=os.read(fd,66); now=os.fstat(fd)
finally: os.close(fd)
if len(raw)!=row.st_size or (row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size)!=(now.st_dev,now.st_ino,now.st_mode,now.st_uid,now.st_gid,now.st_nlink,now.st_size): raise SystemExit(2)
body=raw.decode("ascii").strip()
if re.fullmatch(r"[0-9a-f]{64}",body) is None: raise SystemExit(2)
print(body)
PY
}

cleanup_container() {
  [ "$container_attempted" -eq 1 ] && [ -n "$task_identity" ] || return 1
  [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] && [ "$(stat -c '%d:%i|%u|%g|%a' "$TASK_ROOT")" = "$task_identity|0|0|700" ] || return 1
  local ids='' all_ids='' cid='' row='' cid_present=0 value=''
  ids="$(/usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default container ls -aq --no-trunc --filter "name=^/${CONTAINER_NAME}$" 2>/dev/null)" || return 1
  all_ids="$(/usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default container ls -aq --no-trunc 2>/dev/null)" || return 1
  [ -z "$ids" ] || { [ "$(printf '%s\n' "$ids" | wc -l | tr -d ' ')" = '1' ] || return 1; }
  if [ -e "$CIDFILE" ] || [ -L "$CIDFILE" ]; then
    cid="$(read_full_cid 2>/dev/null)" || return 1
    if [ -n "$ids" ] && [ "$ids" != "$cid" ]; then return 1; fi
    while IFS= read -r value; do
      [ -z "$value" ] && continue
      [ "$value" = "$cid" ] && cid_present=$((cid_present+1))
    done <<<"$all_ids"
    [ "$cid_present" -le 1 ] || return 1
    if [ "$cid_present" -eq 1 ]; then
      [ "$container_attempted" -eq 1 ] || return 1
      row="$(/usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default inspect "$cid" --format '{{.Id}}|{{.Name}}|{{.Image}}|{{index .Config.Labels "com.noteai.task"}}' 2>/dev/null)" || return 1
      [ "$row" = "$cid|/$CONTAINER_NAME|$IMAGE_CONFIG|${CONTAINER_LABEL#com.noteai.task=}" ] || return 1
      /usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default rm -f "$cid" >/dev/null 2>&1 || return 1
    elif [ -n "$ids" ]; then
      return 1
    fi
  elif [ -n "$ids" ]; then
    return 1
  fi
  ids="$(/usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default container ls -aq --no-trunc --filter "name=^/${CONTAINER_NAME}$" 2>/dev/null)" || return 1
  [ -z "$ids" ] || return 1
  all_ids="$(/usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default container ls -aq --no-trunc 2>/dev/null)" || return 1
  if [ -n "$cid" ]; then
    while IFS= read -r value; do [ "$value" != "$cid" ] || return 1; done <<<"$all_ids"
  fi
}

fixed() {
  trap - ERR
  printf '{"NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER":"%s","automatic_retry_allowed":false,"phase":"%s","same_invocation_replay_allowed":false,"secret_values_emitted":0}\n' "$1" "$2" >&2
  exit "$3"
}
unexpected() {
  trap - ERR
  if [ "$container_attempted" -eq 1 ]; then cleanup_container >/dev/null 2>&1 || true; fi
  fixed UNKNOWN unexpected 4
}
trap unexpected ERR

readback() {
  [ "$(metadata_identity 2>/dev/null)" = API_C_IDENTITY_EXACT ] || fixed FAIL identity 3
  [ -d "$BASE_ROOT" ] && [ ! -L "$BASE_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$BASE_ROOT")" = '0|0|700' ] || fixed UNKNOWN base_root 4
  [ -d "$BROKER_ROOT" ] && [ ! -L "$BROKER_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$BROKER_ROOT")" = '0|0|700' ] || fixed UNKNOWN broker_root 4
  [ "$(find "$BROKER_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'broker-receipt.json\ncontrol-envelope.json' ] || fixed UNKNOWN inventory 4
  python3 -I -B - "$ENVELOPE" "$RECEIPT" "$RECIPIENT_PUBLIC_KEY_SHA256" <<'PY' 2>/dev/null || fixed UNKNOWN readback 4
import base64,hashlib,json,os,re,stat,sys
envelope_path,receipt_path,recipient_sha=sys.argv[1:]
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise SystemExit(2)
        result[key]=value
    return result
def canonical(value,newline=False):
    body=json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("ascii")
    return body+(b"\n" if newline else b"")
def read(path,limit):
    row=os.lstat(path)
    if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not 1<=row.st_size<=limit: raise SystemExit(2)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: body=os.read(fd,limit+1); now=os.fstat(fd)
    finally: os.close(fd)
    if len(body)!=row.st_size or (row.st_dev,row.st_ino,row.st_mode,row.st_size)!=(now.st_dev,now.st_ino,now.st_mode,now.st_size): raise SystemExit(2)
    return body
envelope=read(envelope_path,12288); receipt=read(receipt_path,4096)
try:
    envelope_row=json.loads(envelope.decode("ascii"),object_pairs_hook=no_duplicates)
    row=json.loads(receipt.decode("ascii"),object_pairs_hook=no_duplicates)
except BaseException: raise SystemExit(2)
if canonical(envelope_row)!=envelope or canonical(row,True)!=receipt: raise SystemExit(2)
if set(envelope_row)!={"schema_version","algorithm","wrapped_key","nonce","ciphertext"} or envelope_row["schema_version"]!=1 or envelope_row["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM": raise SystemExit(2)
try:
    wrapped=base64.b64decode(envelope_row["wrapped_key"],validate=True); nonce=base64.b64decode(envelope_row["nonce"],validate=True); ciphertext=base64.b64decode(envelope_row["ciphertext"],validate=True)
except BaseException: raise SystemExit(2)
if len(wrapped)!=384 or len(nonce)!=12 or len(ciphertext)<16: raise SystemExit(2)
expected={"NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER","algorithm","automatic_retry_allowed","control_envelope_bytes","control_envelope_sha256","payload_schema_exact","recipient_public_key_sha256","restored_topology_sha256","same_invocation_replay_allowed","schema_version","secret_values_emitted","source_manifest_bytes","source_manifest_file_sha256","source_manifest_sha256","storage_config_sha256"}
hash_keys={"control_envelope_sha256","recipient_public_key_sha256","restored_topology_sha256","source_manifest_file_sha256","source_manifest_sha256","storage_config_sha256"}
if set(row)!=expected or row["NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER"]!="PASS" or type(row["schema_version"]) is not int or row["schema_version"]!=1 or row["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM" or type(row["control_envelope_bytes"]) is not int or row["control_envelope_bytes"]!=len(envelope) or row["control_envelope_sha256"]!=hashlib.sha256(envelope).hexdigest() or row["recipient_public_key_sha256"]!=recipient_sha or row["payload_schema_exact"] is not True or row["automatic_retry_allowed"] is not False or row["same_invocation_replay_allowed"] is not False or type(row["secret_values_emitted"]) is not int or row["secret_values_emitted"]!=0 or type(row["source_manifest_bytes"]) is not int or row["source_manifest_bytes"]!=9794 or row["source_manifest_file_sha256"]!="dba5251aaf489358eab6b800dfa43ff108290abd851410da9a16f97b86d0b1f4" or row["source_manifest_sha256"]!="99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a" or any(type(row[key]) is not str or re.fullmatch(r"[0-9a-f]{64}",row[key]) is None for key in hash_keys): raise SystemExit(2)
transport={"control_envelope_b64":base64.b64encode(envelope).decode("ascii"),"control_envelope_bytes":len(envelope),"control_envelope_sha256":row["control_envelope_sha256"],"recipient_public_key_sha256":row["recipient_public_key_sha256"],"same_invocation_replay_allowed":False,"schema_version":1,"secret_values_emitted":0}
body=canonical({"receipt":row,"transport":transport},True)
if len(body)>18000: raise SystemExit(2)
if os.write(1,body)!=len(body): raise SystemExit(2)
PY
}

create() {
  [ "$(id -u)" = 0 ] && [ "$(id -g)" = 0 ] || fixed FAIL root 3
  for tool in docker systemctl stat find sort python3 mkdir mv chmod ss awk timeout cat; do command -v "$tool" >/dev/null 2>&1 || fixed FAIL tool 3; done
  [ -d /var/lib/noteai ] && [ ! -L /var/lib/noteai ] && [ "$(stat -c '%u|%g|%a' /var/lib/noteai)" = '0|0|700' ] || fixed FAIL parent 3
  [ "$(metadata_identity 2>/dev/null)" = API_C_IDENTITY_EXACT ] || fixed FAIL identity 3
  [ ! -e "$BASE_ROOT" ] && [ ! -L "$BASE_ROOT" ] || fixed UNKNOWN preexisting_base 4
  [ "$(systemctl is-active docker)" = active ] || fixed FAIL docker 3
  for path in "$SOURCE_MANIFEST" "$API_ENV" "$STORAGE_ENV"; do
    [ "$(stat -c '%F|%u|%g|%a|%h' "$path")" = 'regular file|0|0|600|1' ] || fixed FAIL input_metadata 3
  done
  [ -z "$(/usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" ] || fixed UNKNOWN container 4
  [ "$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = 0 ] || fixed FAIL db_socket 3
  image_row="$(/usr/bin/docker --context=default image inspect "$IMAGE_REF" --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{index .Config.Labels "org.opencontainers.image.revision"}}')" || fixed FAIL image 3
  [ "$image_row" = "$IMAGE_CONFIG|linux|amd64|$RELEASE_COMMIT" ] || fixed FAIL image 3
  mkdir -m 0700 "$BASE_ROOT" "$TASK_ROOT" "$DOCKER_CONFIG_ROOT" || fixed UNKNOWN task_create 4
  task_identity="$(stat -c '%d:%i' "$TASK_ROOT")" || fixed UNKNOWN task_identity 4
  printf '%s' '{}' >"$DOCKER_CONFIG_ROOT/config.json"; chmod 0600 "$DOCKER_CONFIG_ROOT/config.json"
  python3 -I -B - "$RECIPIENT_PUBLIC" "$REWRAP_RESULT" <<'PY' 2>/dev/null || fixed UNKNOWN stage_input 4
import base64,os
public=base64.b64decode("@@RECIPIENT_PUBLIC_KEY_B64@@".encode("ascii"),validate=True)
rewrap=base64.b64decode("@@PASSWORD_REWRAP_RESULT_B64@@".encode("ascii"),validate=True)
if len(public)!=625 or not public.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not public.endswith(b"-----END PUBLIC KEY-----\n") or not 700<=len(rewrap)<=1200 or not rewrap.endswith(b"\n"): raise SystemExit(2)
for path,body in zip(__import__("sys").argv[1:],(public,rewrap)):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        offset=0
        while offset<len(body):
            count=os.write(fd,body[offset:])
            if count<=0: raise OSError("write")
            offset+=count
        os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
    finally: os.close(fd)
PY
  cat >"$DRIVER" <<'PY'
import base64,gzip,hashlib,json,os,re,stat,sys
from urllib.parse import parse_qsl,unquote,urlsplit
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SOURCE_BYTES=9794
SOURCE_FILE_SHA="dba5251aaf489358eab6b800dfa43ff108290abd851410da9a16f97b86d0b1f4"
SOURCE_MANIFEST_SHA="99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a"
RELEASE="cad5ce35664f617c6e19f90a6159285ddf975594"
RESTORED_HOST="@@RESTORED_HOST@@"
RECIPIENT_SHA="@@RECIPIENT_PUBLIC_KEY_SHA256@@"
RAM_ROLE="noteai-item26-pitr-oss-reader-v1"
AAD=b"noteai-item26-restored-control-v1"
QUERY=frozenset({"sslmode","connect_timeout","target_session_attrs","channel_binding","keepalives","keepalives_idle","keepalives_interval","keepalives_count","tcp_user_timeout"})
STORAGE=frozenset({"NOTEAI_PRIVATE_STORAGE_BACKEND","NOTEAI_OSS_PRIVATE_BUCKET","NOTEAI_OSS_REGION","NOTEAI_OSS_ENDPOINT","NOTEAI_OSS_RAM_ROLE","NOTEAI_PRIVATE_STORAGE_KEY_EPOCH","NOTEAI_OSS_KEY_PREFIX"})
def canonical(value,newline=False):
    body=json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("ascii")
    return body+(b"\n" if newline else b"")
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("duplicate")
        result[key]=value
    return result
def read(path,low,high):
    row=os.lstat(path)
    if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not low<=row.st_size<=high: raise ValueError("metadata")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: body=os.read(fd,high+1); now=os.fstat(fd)
    finally: os.close(fd)
    if len(body)!=row.st_size or (row.st_dev,row.st_ino,row.st_mode,row.st_size)!=(now.st_dev,now.st_ino,now.st_mode,now.st_size): raise ValueError("race")
    return body
def env(path):
    body=read(path,1,16384)
    if not body.endswith(b"\n") or b"\r" in body or b"\x00" in body: raise ValueError("env")
    values={}
    for raw in body.splitlines():
        line=raw.strip()
        if not line or line.startswith(b"#"): continue
        if line.startswith(b"export "): line=line[7:].lstrip()
        if b"=" not in line: raise ValueError("env")
        key,value=line.split(b"=",1); key=key.strip().decode("ascii"); value=value.decode("utf-8")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key) is None or key in values: raise ValueError("env")
        values[key]=value
    return values
def write_once(path,body):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        offset=0
        while offset<len(body):
            count=os.write(fd,body[offset:])
            if count<=0: raise OSError("write")
            offset+=count
        os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
    finally: os.close(fd)
source=read("/input/source-manifest.json",SOURCE_BYTES,SOURCE_BYTES)
if not source.endswith(b"\n") or hashlib.sha256(source).hexdigest()!=SOURCE_FILE_SHA: raise SystemExit(2)
manifest=json.loads(source.decode("ascii"))
if canonical(manifest,True)!=source or manifest.get("manifest_sha256")!=SOURCE_MANIFEST_SHA or manifest.get("release_commit")!=RELEASE or manifest.get("database",{}).get("engine")!="postgresql": raise SystemExit(2)
api=env("/input/api.env")
if "DATABASE_URL" not in api: raise SystemExit(2)
dsn=api.pop("DATABASE_URL"); api.clear(); parsed=urlsplit(dsn); pairs=parse_qsl(parsed.query,keep_blank_values=True,strict_parsing=True)
names=[name.lower() for name,_ in pairs]
if parsed.scheme not in {"postgres","postgresql"} or unquote(parsed.username or "")!="noteai_app" or not parsed.hostname or parsed.path in {"","/"} or parsed.fragment or len(names)!=len(set(names)) or set(names)-QUERY: raise SystemExit(2)
query={name.lower():value for name,value in pairs}; query["sslmode"]="require"
if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}[A-Za-z0-9]",RESTORED_HOST) is None or not RESTORED_HOST.lower().endswith(".rds.aliyuncs.com"): raise SystemExit(2)
topology={"scheme":"postgresql","host":RESTORED_HOST,"port":5432,"database":parsed.path[1:],"query":query}
del dsn,parsed,pairs,names
storage=env("/input/storage.env")
if set(storage)!=STORAGE: raise SystemExit(2)
storage["NOTEAI_OSS_RAM_ROLE"]=RAM_ROLE; region=storage.get("NOTEAI_OSS_REGION","")
if storage.get("NOTEAI_PRIVATE_STORAGE_BACKEND")!="aliyun_oss" or re.fullmatch(r"cn-[a-z0-9-]{2,32}",region) is None or storage.get("NOTEAI_OSS_ENDPOINT")!="https://oss-{}-internal.aliyuncs.com".format(region) or not storage.get("NOTEAI_OSS_PRIVATE_BUCKET") or not storage.get("NOTEAI_PRIVATE_STORAGE_KEY_EPOCH") or storage.get("NOTEAI_OSS_KEY_PREFIX","").strip("/")!="noteai-private": raise SystemExit(2)
public=read("/input/recipient-public.pem",625,625); key=serialization.load_pem_public_key(public)
if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=3072 or key.public_numbers().e!=65537: raise SystemExit(2)
der=key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
if hashlib.sha256(der).hexdigest()!=RECIPIENT_SHA: raise SystemExit(2)
rewrap_raw=read("/input/password-rewrap.json",700,1200)
if not rewrap_raw.endswith(b"\n"): raise SystemExit(2)
rewrap=json.loads(rewrap_raw.decode("ascii"),object_pairs_hook=no_duplicates)
if canonical(rewrap,True)!=rewrap_raw: raise SystemExit(2)
expected={"account_exact","automatic_retry_allowed","database_connection_count","database_write_count","password_policy_exact","provider_control_plane_mutation_count","recipient_public_key_sha256","schema_version","secret_values_emitted","status","wrapped_password"}
if set(rewrap)!=expected or rewrap["status"]!="PASSWORD_REWRAPPED" or rewrap["schema_version"]!=1 or rewrap["recipient_public_key_sha256"]!=RECIPIENT_SHA or rewrap["account_exact"] is not True or rewrap["password_policy_exact"] is not True or rewrap["automatic_retry_allowed"] is not False or any(rewrap[k]!=0 for k in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted")): raise SystemExit(2)
wrapped_password=base64.b64decode(rewrap["wrapped_password"],validate=True)
if len(wrapped_password)!=384: raise SystemExit(2)
payload={"schema_version":1,"source_manifest_gzip":base64.b64encode(gzip.compress(source,compresslevel=9,mtime=0)).decode("ascii"),"restored_database":topology,"wrapped_password":base64.b64encode(wrapped_password).decode("ascii"),"storage":storage}
plaintext=canonical(payload); data_key=AESGCM.generate_key(bit_length=256); nonce=os.urandom(12)
wrapped_key=key.encrypt(data_key,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=AAD))
ciphertext=AESGCM(data_key).encrypt(nonce,plaintext,AAD); del data_key,plaintext,payload,wrapped_password,rewrap,rewrap_raw,source,manifest
envelope={"schema_version":1,"algorithm":"RSA-OAEP-SHA256+AES-256-GCM","wrapped_key":base64.b64encode(wrapped_key).decode("ascii"),"nonce":base64.b64encode(nonce).decode("ascii"),"ciphertext":base64.b64encode(ciphertext).decode("ascii")}
envelope_body=canonical(envelope)
receipt={"NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER":"PASS","algorithm":"RSA-OAEP-SHA256+AES-256-GCM","automatic_retry_allowed":False,"control_envelope_bytes":len(envelope_body),"control_envelope_sha256":hashlib.sha256(envelope_body).hexdigest(),"payload_schema_exact":True,"recipient_public_key_sha256":RECIPIENT_SHA,"restored_topology_sha256":hashlib.sha256(canonical(topology)).hexdigest(),"same_invocation_replay_allowed":False,"schema_version":1,"secret_values_emitted":0,"source_manifest_bytes":SOURCE_BYTES,"source_manifest_file_sha256":SOURCE_FILE_SHA,"source_manifest_sha256":SOURCE_MANIFEST_SHA,"storage_config_sha256":hashlib.sha256(canonical(storage)).hexdigest()}
write_once("/output/control-envelope.json",envelope_body); write_once("/output/broker-receipt.json",canonical(receipt,True))
fd=os.open("/output",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: os.fsync(fd)
finally: os.close(fd)
transport={"control_envelope_b64":base64.b64encode(envelope_body).decode("ascii"),"control_envelope_bytes":len(envelope_body),"control_envelope_sha256":receipt["control_envelope_sha256"],"recipient_public_key_sha256":RECIPIENT_SHA,"same_invocation_replay_allowed":False,"schema_version":1,"secret_values_emitted":0}
transport_body=canonical(transport,True)
if len(envelope_body)>12288 or len(transport_body)>18000: raise SystemExit(2)
os.write(1,transport_body)
PY
  chmod 0600 "$DRIVER"
  mkdir -m 0700 "$TASK_ROOT/output"
  set +e
  container_attempted=1
  /usr/bin/timeout --foreground --signal=TERM --kill-after=10s 180s /usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default run --rm --cidfile "$CIDFILE" \
    --name "$CONTAINER_NAME" --label "$CONTAINER_LABEL" --pull never --network none --workdir /tmp --user 0:0 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    --memory 256m --cpus 0.25 --pids-limit 64 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16777216,mode=1777 \
    --mount type=bind,src="$SOURCE_MANIFEST",dst=/input/source-manifest.json,readonly --mount type=bind,src="$API_ENV",dst=/input/api.env,readonly \
    --mount type=bind,src="$STORAGE_ENV",dst=/input/storage.env,readonly --mount type=bind,src="$RECIPIENT_PUBLIC",dst=/input/recipient-public.pem,readonly \
    --mount type=bind,src="$REWRAP_RESULT",dst=/input/password-rewrap.json,readonly --mount type=bind,src="$DRIVER",dst=/task/driver.py,readonly \
    --mount type=bind,src="$TASK_ROOT/output",dst=/output --entrypoint /usr/local/bin/python3.11 "$IMAGE_REF" -I -B /task/driver.py >"$HELPER_OUT" 2>"$HELPER_ERR"
  rc=$?; set -e
  cleanup_container || fixed UNKNOWN container_cleanup 4
  container_attempted=0
  [ "$rc" -eq 0 ] || fixed UNKNOWN container_execute 4
  [ ! -s "$HELPER_ERR" ] || fixed UNKNOWN helper_stderr 4
  python3 -I -B - "$HELPER_OUT" <<'PY' 2>/dev/null || fixed UNKNOWN helper_stdout 4
import base64,hashlib,json,os,re,stat,sys
p=sys.argv[1]; row=os.lstat(p)
if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not 1<=row.st_size<=18000: raise SystemExit(2)
body=open(p,"rb").read()
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise SystemExit(2)
        result[key]=value
    return result
value=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
if (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")!=body: raise SystemExit(2)
if set(value)!={"control_envelope_b64","control_envelope_bytes","control_envelope_sha256","recipient_public_key_sha256","same_invocation_replay_allowed","schema_version","secret_values_emitted"} or value["schema_version"]!=1 or value["same_invocation_replay_allowed"] is not False or value["secret_values_emitted"]!=0: raise SystemExit(2)
decoded=base64.b64decode(value["control_envelope_b64"],validate=True)
if type(value["control_envelope_bytes"]) is not int or len(decoded)!=value["control_envelope_bytes"] or value["control_envelope_bytes"]>12288 or type(value["control_envelope_sha256"]) is not str or hashlib.sha256(decoded).hexdigest()!=value["control_envelope_sha256"] or type(value["recipient_public_key_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}",value["recipient_public_key_sha256"]) is None: raise SystemExit(2)
PY
  [ "$(find "$TASK_ROOT/output" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'broker-receipt.json\ncontrol-envelope.json' ] || fixed UNKNOWN output 4
  mv "$TASK_ROOT/output" "$BROKER_ROOT" || fixed UNKNOWN promote 4
  python3 -I -B - "$BASE_ROOT" <<'PY' 2>/dev/null || fixed UNKNOWN promote_fsync 4
import os,sys
fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: os.fsync(fd)
finally: os.close(fd)
PY
  cat "$HELPER_OUT"
}

case "$MODE" in
  CREATE) create ;;
  READBACK) readback ;;
  *) fixed FAIL mode 3 ;;
esac
