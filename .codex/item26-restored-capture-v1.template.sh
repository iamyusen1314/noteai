#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset DATABASE_URL NOTEAI_SQLITE_PATH PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH

readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly RELEASE_COMMIT='cad5ce35664f617c6e19f90a6159285ddf975594'
readonly BASE_ROOT='/var/lib/noteai/item26-restored-v1'
readonly CONTROL_ROOT="$BASE_ROOT/control"
readonly ATTEMPT_SENTINEL="$BASE_ROOT/capture-successor-attempted-v1"
readonly PRIVATE_KEY="$CONTROL_ROOT/control-private.pem"
readonly PUBLIC_KEY="$CONTROL_ROOT/control-public.pem"
readonly ENVELOPE="$CONTROL_ROOT/control-envelope-successor-v1.json"
readonly TASK_ROOT="$BASE_ROOT/capture-successor-task-v1"
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly OUTPUT_ROOT="$TASK_ROOT/output"
readonly DRIVER_PATH="$TASK_ROOT/driver.py"
readonly HELPER_OUT="$TASK_ROOT/helper.stdout"
readonly HELPER_ERR="$TASK_ROOT/helper.stderr"
readonly CIDFILE="$TASK_ROOT/container.cid"
readonly FINAL_ROOT="$BASE_ROOT/restored-manifest-successor-v1"
readonly FINAL_MANIFEST="$FINAL_ROOT/restored-manifest.json"
readonly FINAL_RECEIPT="$FINAL_ROOT/reconciliation.json"
readonly CONTAINER_NAME='noteai-item26-restored-capture-successor-v1'
readonly CONTAINER_LABEL='com.noteai.task=PROD-FIRST-LAUNCH-PITR-RESTORE-001-restored-capture-successor-v1'

phase='preflight'
task_created=0
container_attempted=0
uncertain=0
completed=0
task_identity=''
invocation_label=''
attempt_consumed=0

fail() { phase="$1"; exit 3; }
unknown() { phase="$1"; uncertain=1; exit 4; }

verify_attempt_sentinel() {
  [ "$(stat -c '%F|%u|%g|%a|%h|%s' "$ATTEMPT_SENTINEL")" = 'regular file|0|0|600|1|37' ] || return 1
  [ "$(sha256sum "$ATTEMPT_SENTINEL" | awk '{print $1}')" = 'de7dd59a303a5333f60de5c07d5747904b61de41109ff539f6c50f537707c7cd' ] || return 1
}

cleanup_container() {
  local cid row ids
  [ "$container_attempted" -eq 1 ] || return 1
  [ -n "$task_identity" ] && [ -n "$invocation_label" ] || return 1
  [ "$(stat -c '%d:%i' "$TASK_ROOT")" = "$task_identity" ] || return 1
  if [ -e "$CIDFILE" ] || [ -L "$CIDFILE" ]; then
    cid="$(python3 -I -B - "$CIDFILE" <<'PY'
import os,re,stat,sys
path=sys.argv[1]; row=os.lstat(path)
if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid!=0 or row.st_gid!=0 or row.st_nlink!=1 or not 64<=row.st_size<=65: raise SystemExit(2)
fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
try: body=os.read(fd,66); current=os.fstat(fd)
finally: os.close(fd)
if len(body)!=row.st_size or (current.st_dev,current.st_ino,current.st_mode,current.st_uid,current.st_gid,current.st_nlink,current.st_size)!=(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size): raise SystemExit(2)
value=body.decode("ascii").strip()
if re.fullmatch(r"[0-9a-f]{64}",value) is None: raise SystemExit(2)
print(value)
PY
)" || return 1
    if row="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$cid" --format '{{.Id}}|{{.Name}}|{{.Image}}|{{index .Config.Labels "com.noteai.task"}}|{{index .Config.Labels "com.noteai.invocation"}}' 2>/dev/null)"; then
      [ "$row" = "$cid|/$CONTAINER_NAME|$IMAGE_CONFIG|${CONTAINER_LABEL#com.noteai.task=}|$invocation_label" ] || return 1
      /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default rm -f "$cid" >/dev/null 2>&1 || return 1
      /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$cid" >/dev/null 2>&1 && return 1
    fi
  fi
  ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || return 1
  [ -z "$ids" ] || return 1
}

verify_task_retained() {
  if [ "$task_created" -eq 1 ]; then
    [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$TASK_ROOT")" = '0|0|700' ] || return 1
  fi
}

on_exit() {
  local rc=$? cleanup_ok=1
  if [ "$completed" -eq 1 ] && [ "$rc" -eq 0 ]; then return 0; fi
  trap - EXIT
  if [ "$attempt_consumed" -eq 1 ]; then verify_attempt_sentinel >/dev/null 2>&1 || cleanup_ok=0; fi
  if [ "$container_attempted" -eq 1 ] && [ -d "$DOCKER_CONFIG_ROOT" ]; then cleanup_container >/dev/null 2>&1 || cleanup_ok=0; fi
  if [ "$task_created" -eq 1 ]; then verify_task_retained >/dev/null 2>&1 || cleanup_ok=0; fi
  if [ "$uncertain" -eq 0 ] && [ "$container_attempted" -eq 0 ] && [ "$cleanup_ok" -eq 1 ]; then
    printf '%s\n' '{"NOTEAI_ITEM26_RESTORED_CAPTURE":"FAIL","automatic_retry_allowed":false,"database_attempted_state":"NO","incident_class":"PRE_CONNECT","new_capture_allowed":false,"phase":"'"$phase"'","same_invocation_replay_allowed":false}' >&2
    exit 3
  fi
  printf '%s\n' '{"NOTEAI_ITEM26_RESTORED_CAPTURE":"UNKNOWN","automatic_retry_allowed":false,"database_attempted_state":"UNKNOWN","incident_class":"CONNECTED_UNKNOWN","new_capture_allowed":false,"phase":"'"$phase"'","readback_required":true,"same_invocation_replay_allowed":false}' >&2
  exit 4
}
trap on_exit EXIT

[ "$(id -u)" = '0' ] && [ "$(id -g)" = '0' ] || fail root
for tool in docker systemctl stat sha256sum openssl awk python3 timeout wc tr sort rm mv find mkdir chmod; do command -v "$tool" >/dev/null 2>&1 || fail tool; done
[ -x /usr/sbin/ss ] || fail tool
[ -x /usr/bin/docker ] && [ -x /usr/bin/env ] && [ -x /usr/bin/timeout ] && [ -x /usr/bin/openssl ] || fail absolute_tool
[ -d /var/lib/noteai ] && [ ! -L /var/lib/noteai ] && [ "$(stat -c '%F|%u|%g|%a' /var/lib/noteai)" = 'directory|0|0|700' ] || fail persistent_parent
[ -d "$BASE_ROOT" ] && [ ! -L "$BASE_ROOT" ] && [ "$(stat -c '%F|%u|%g|%a' "$BASE_ROOT")" = 'directory|0|0|700' ] || fail persistent_root
[ ! -e "$ATTEMPT_SENTINEL" ] && [ ! -L "$ATTEMPT_SENTINEL" ] || unknown replay_barrier
python3 -I -B - "$ATTEMPT_SENTINEL" <<'PY' || unknown replay_barrier
import os,stat,sys
path=sys.argv[1]; parent,name=os.path.split(path)
dirfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dirfd)
    try:
        body=b"ITEM26_RESTORED_SUCCESSOR_V1_ATTEMPT\n"
        if os.write(fd,body)!=len(body): raise OSError("short write")
        os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
    finally: os.close(fd)
    os.fsync(dirfd)
finally: os.close(dirfd)
row=os.lstat(path)
if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid!=0 or row.st_gid!=0 or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or row.st_size!=37: raise SystemExit(2)
PY
attempt_consumed=1
verify_attempt_sentinel || unknown replay_barrier
if [ -e "$TASK_ROOT" ] || [ -L "$TASK_ROOT" ] || [ -e "$FINAL_ROOT" ] || [ -L "$FINAL_ROOT" ]; then unknown preexisting_capture_state; fi

identity="$({ python3 -I -B - '@@BUILDER_IDENTITY_SHA256@@' <<'PY'
import hashlib,json,re,sys,urllib.request
expected=sys.argv[1]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl): raise RuntimeError("redirect")
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
request=urllib.request.Request("http://100.100.100.200/latest/api/token",method="PUT",headers={"X-aliyun-ecs-metadata-token-ttl-seconds":"60"})
with opener.open(request,timeout=3) as response: token=response.read(512).decode("ascii").strip()
if not token or len(token)>256: raise SystemExit(2)
headers={"X-aliyun-ecs-metadata-token":token}; values=[]
for suffix in ("instance-id","ram/security-credentials/"):
    request=urllib.request.Request("http://100.100.100.200/latest/meta-data/"+suffix,headers=headers,method="GET")
    with opener.open(request,timeout=3) as response: body=response.read(4096)
    if len(body)>=4096: raise SystemExit(2)
    values.append(body.decode("ascii").strip())
roles=[row for row in values[1].splitlines() if row]
if not re.fullmatch(r"i-[a-z0-9]+",values[0]) or len(roles)!=1 or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}",roles[0]): raise SystemExit(2)
canonical=json.dumps({"instance_id":values[0],"ram_role":roles[0]},ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("ascii")
if hashlib.sha256(canonical).hexdigest()!=expected: raise SystemExit(2)
print("BUILDER_IDENTITY_EXACT")
PY
} 2>/dev/null)" || fail identity
[ "$identity" = BUILDER_IDENTITY_EXACT ] || fail identity

[ -d "$CONTROL_ROOT" ] && [ ! -L "$CONTROL_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$CONTROL_ROOT")" = '0|0|700' ] || fail control_root
[ "$(find "$CONTROL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'control-envelope-successor-v1.json\ncontrol-private.pem\ncontrol-public.pem' ] || fail control_inventory
[ "$(stat -c '%F|%u|%g|%a|%h' "$PRIVATE_KEY")" = 'regular file|0|0|600|1' ] || fail private_key
[ "$(stat -c '%F|%u|%g|%a|%h|%s' "$PUBLIC_KEY")" = 'regular file|0|0|600|1|625' ] || fail public_key
[ "$(stat -c '%F|%u|%g|%a|%h|%s' "$ENVELOPE")" = 'regular file|0|0|600|1|@@CONTROL_ENVELOPE_BYTES@@' ] || fail envelope
[ "$(sha256sum "$ENVELOPE" | awk '{print $1}')" = '@@CONTROL_ENVELOPE_SHA256@@' ] || fail envelope_hash
public_sha="$(/usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl pkey -pubin -in "$PUBLIC_KEY" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || fail public_hash
private_sha="$(/usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || fail private_hash
[ "$public_sha" = '@@RECIPIENT_PUBLIC_KEY_SHA256@@' ] && [ "$private_sha" = "$public_sha" ] || fail key_pair

mkdir -m 0700 "$TASK_ROOT"; task_created=1
task_identity="$(stat -c '%d:%i' "$TASK_ROOT")" || fail task_identity
invocation_label="item26-restored-v1-$(printf '%s' "$task_identity" | sha256sum | awk '{print $1}')" || fail task_identity
mkdir -m 0700 "$DOCKER_CONFIG_ROOT" "$OUTPUT_ROOT"
printf '%s' '{}' >"$DOCKER_CONFIG_ROOT/config.json"; chmod 0600 "$DOCKER_CONFIG_ROOT/config.json"
cat >"$DRIVER_PATH" <<'PY'
import base64,gzip,hashlib,json,os,re,stat,sys,urllib.request,zlib
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ACCOUNT="noteai_item26_source_read_20260811_v2"; OWNER="noteai_admin"; MANAGED="pg_rds_superuser"
RELEASE="cad5ce35664f617c6e19f90a6159285ddf975594"; IMPORT_GUARD_DATABASE_URL="postgresql:///noteai_item26_restored_import_guard"
CONTROL_AAD=b"noteai-item26-restored-control-v1"; PASSWORD_LABEL=b"noteai-item26-password-rewrap-v1"
EXPECTED_PUBLIC_SHA="@@RECIPIENT_PUBLIC_KEY_SHA256@@"; EXPECTED_ENVELOPE_BYTES=@@CONTROL_ENVELOPE_BYTES@@; EXPECTED_ENVELOPE_SHA="@@CONTROL_ENVELOPE_SHA256@@"
SOURCE_BYTES=@@SOURCE_MANIFEST_BYTES@@; SOURCE_FILE_SHA="@@SOURCE_MANIFEST_FILE_SHA256@@"; SOURCE_MANIFEST_SHA="@@SOURCE_MANIFEST_SHA256@@"
TOPOLOGY_SHA="@@RESTORED_TOPOLOGY_SHA256@@"; STORAGE_SHA="@@STORAGE_CONFIG_SHA256@@"; BUILDER_IDENTITY_SHA="@@BUILDER_IDENTITY_SHA256@@"
QUERY=frozenset({"sslmode","connect_timeout","target_session_attrs","channel_binding","keepalives","keepalives_idle","keepalives_interval","keepalives_count","tcp_user_timeout"})
STORAGE=frozenset({"NOTEAI_PRIVATE_STORAGE_BACKEND","NOTEAI_OSS_PRIVATE_BUCKET","NOTEAI_OSS_REGION","NOTEAI_OSS_ENDPOINT","NOTEAI_OSS_RAM_ROLE","NOTEAI_PRIVATE_STORAGE_KEY_EPOCH","NOTEAI_OSS_KEY_PREFIX"})
TABLES=("account_deletion_requests","admin_sessions","ai_dispatch_state","ai_operation_admissions","ai_operation_events","ai_operation_media_refs","ai_operation_outbox","ai_operation_settlements","ai_operations","ai_payload_refs","ai_provider_attempts","analysis_log","auth_login_limits","auth_verification_challenges","chat_sessions","content_retention","crawler_events","credit_transactions","credits","growth_records","hot_keywords","idempotency_requests","keyword_snapshots","managed_prompts","model_usage_records","notes","payment_cash_ledger","payment_credit_consumptions","payment_credit_positions","payment_entitlement_ledger","payment_events","payment_orders","payment_reconciliation_items","payment_reconciliation_runs","payment_refunds","payment_settlement_summaries","private_media_refs","prompt_history","saved_diagnoses","schema_migrations","subscriptions","system_settings","tracked_notes","tracking_provider_attempts","usage_records","user_contract_acceptances","user_learn","user_memories","user_sessions","users","xhs_crawler_health","xhs_freshness_ledger","xhs_trends_provider_attempts","xhs_trends_runs","xhs_trends_service_state","xhs_trends_snapshot_evidence")
RLS=("admin_sessions","ai_dispatch_state","ai_operation_media_refs","ai_operation_outbox","ai_operation_settlements","ai_payload_refs","content_retention","payment_cash_ledger","payment_credit_consumptions","payment_credit_positions","payment_entitlement_ledger","payment_events","payment_orders","payment_reconciliation_items","payment_reconciliation_runs","payment_refunds","payment_settlement_summaries","private_media_refs","system_settings")
PRE_CODES=frozenset({"metadata","race","read","identity","capability","envelope","key","payload","source","topology","storage","password","import","backend"})
MISMATCH_CODES=frozenset({"release_commit","database_engine","database_schema","database_migrations","database_tables","database_references","private_objects"})
class Fixed(Exception): pass

def canonical(value,newline=False):
    body=json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("ascii")
    return body+(b"\n" if newline else b"")

def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise Fixed("payload")
        result[key]=value
    return result

def emit(value,code,descriptor):
    body=canonical(value,True)
    if len(body)>4096: os._exit(4)
    try:
        if os.write(descriptor,body)!=len(body): os._exit(4)
    except BaseException: os._exit(4)
    os._exit(code)

def read_private(path,low,high):
    row=os.lstat(path)
    if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid!=0 or row.st_gid!=0 or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not low<=row.st_size<=high: raise Fixed("metadata")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        current=os.fstat(fd)
        if (current.st_dev,current.st_ino,current.st_mode,current.st_uid,current.st_gid,current.st_nlink,current.st_size)!=(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size): raise Fixed("race")
        body=b""
        while len(body)<=high:
            chunk=os.read(fd,min(65536,high+1-len(body)))
            if not chunk: break
            body+=chunk
    finally: os.close(fd)
    if len(body)!=row.st_size: raise Fixed("read")
    return body

def capabilities():
    values={}
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if ":" in line:
            key,value=line.split(":",1); values[key]=value.strip()
    if os.geteuid()!=0 or os.getegid()!=0 or values.get("NoNewPrivs")!="1": raise Fixed("identity")
    if any(int(values.get(key,"-1"),16)!=4 for key in ("CapEff","CapPrm","CapBnd")) or any(int(values.get(key,"-1"),16)!=0 for key in ("CapInh","CapAmb")): raise Fixed("capability")

def metadata_identity():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl): raise RuntimeError("redirect")
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    request=urllib.request.Request("http://100.100.100.200/latest/api/token",method="PUT",headers={"X-aliyun-ecs-metadata-token-ttl-seconds":"60"})
    with opener.open(request,timeout=3) as response: token=response.read(512).decode("ascii").strip()
    if not token or len(token)>256: raise Fixed("identity")
    headers={"X-aliyun-ecs-metadata-token":token}; values=[]
    for suffix in ("instance-id","ram/security-credentials/"):
        request=urllib.request.Request("http://100.100.100.200/latest/meta-data/"+suffix,headers=headers,method="GET")
        with opener.open(request,timeout=3) as response: body=response.read(4096)
        if len(body)>=4096: raise Fixed("identity")
        values.append(body.decode("ascii").strip())
    roles=[row for row in values[1].splitlines() if row]
    if not re.fullmatch(r"i-[a-z0-9]+",values[0]) or len(roles)!=1 or hashlib.sha256(canonical({"instance_id":values[0],"ram_role":roles[0]})).hexdigest()!=BUILDER_IDENTITY_SHA: raise Fixed("identity")
    return roles[0]

def bounded_gunzip(body,expected):
    stream=zlib.decompressobj(16+zlib.MAX_WBITS)
    result=stream.decompress(body,expected+1)
    if len(result)>expected or stream.unconsumed_tail: raise Fixed("source")
    result+=stream.flush(expected+1-len(result))
    if not stream.eof or stream.unused_data or len(result)!=expected: raise Fixed("source")
    return result

def decrypt_payload():
    envelope_bytes=read_private("/input/control/control-envelope-successor-v1.json",EXPECTED_ENVELOPE_BYTES,EXPECTED_ENVELOPE_BYTES)
    if hashlib.sha256(envelope_bytes).hexdigest()!=EXPECTED_ENVELOPE_SHA: raise Fixed("envelope")
    try: envelope=json.loads(envelope_bytes.decode("ascii"),object_pairs_hook=no_duplicates)
    except BaseException: raise Fixed("envelope")
    if canonical(envelope)!=envelope_bytes or not isinstance(envelope,dict) or set(envelope)!={"schema_version","algorithm","wrapped_key","nonce","ciphertext"} or envelope["schema_version"]!=1 or envelope["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM": raise Fixed("envelope")
    private=serialization.load_pem_private_key(read_private("/input/control/control-private.pem",2000,5000),password=None)
    if not isinstance(private,rsa.RSAPrivateKey) or private.key_size!=3072 or private.public_key().public_numbers().e!=65537: raise Fixed("key")
    public_der=private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(public_der).hexdigest()!=EXPECTED_PUBLIC_SHA: raise Fixed("key")
    try:
        wrapped=base64.b64decode(envelope["wrapped_key"],validate=True); nonce=base64.b64decode(envelope["nonce"],validate=True); ciphertext=base64.b64decode(envelope["ciphertext"],validate=True)
    except BaseException: raise Fixed("envelope")
    if len(wrapped)!=384 or len(nonce)!=12 or len(ciphertext)<16: raise Fixed("envelope")
    data_key=private.decrypt(wrapped,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=CONTROL_AAD))
    if len(data_key)!=32: raise Fixed("key")
    plaintext=AESGCM(data_key).decrypt(nonce,ciphertext,CONTROL_AAD); del data_key
    try: payload=json.loads(plaintext.decode("ascii"),object_pairs_hook=no_duplicates)
    except BaseException: raise Fixed("payload")
    if canonical(payload)!=plaintext or not isinstance(payload,dict) or set(payload)!={"schema_version","source_manifest_gzip","restored_database","wrapped_password","storage"} or payload["schema_version"]!=1: raise Fixed("payload")
    del plaintext
    return payload,private

def source_manifest(payload,recovery):
    try: compressed=base64.b64decode(payload.pop("source_manifest_gzip").encode("ascii"),validate=True)
    except BaseException: raise Fixed("source")
    body=bounded_gunzip(compressed,SOURCE_BYTES); del compressed
    if not body.endswith(b"\n") or hashlib.sha256(body).hexdigest()!=SOURCE_FILE_SHA: raise Fixed("source")
    try: manifest=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
    except BaseException: raise Fixed("source")
    if canonical(manifest,True)!=body: raise Fixed("source")
    recovery.validate_manifest(manifest)
    if manifest.get("manifest_sha256")!=SOURCE_MANIFEST_SHA or manifest.get("release_commit")!=RELEASE or manifest.get("database",{}).get("engine")!="postgresql": raise Fixed("source")
    del body
    return manifest

def topology_and_password(payload,private,psycopg):
    topology=payload.pop("restored_database")
    if not isinstance(topology,dict) or set(topology)!={"scheme","host","port","database","query"} or hashlib.sha256(canonical(topology)).hexdigest()!=TOPOLOGY_SHA: raise Fixed("topology")
    scheme=topology["scheme"]; host=topology["host"]; port=topology["port"]; database=topology["database"]; query=topology["query"]
    if scheme!="postgresql" or type(host) is not str or not 1<=len(host)<=253 or type(port) is not int or port!=5432 or type(database) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}",database) is None or not isinstance(query,dict) or set(query)-QUERY or query.get("sslmode") not in {"require","verify-ca","verify-full"} or any(type(key) is not str or type(value) is not str or len(value)>256 for key,value in query.items()): raise Fixed("topology")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}[A-Za-z0-9]",host) is None or not host.lower().endswith(".rds.aliyuncs.com"): raise Fixed("topology")
    try: wrapped=base64.b64decode(payload.pop("wrapped_password").encode("ascii"),validate=True)
    except BaseException: raise Fixed("password")
    if len(wrapped)!=384: raise Fixed("password")
    password=private.decrypt(wrapped,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=PASSWORD_LABEL)).decode("ascii")
    if len(password)!=32 or not password.isalnum() or not any(ch.isupper() for ch in password) or not any(ch.islower() for ch in password) or not any(ch.isdigit() for ch in password): raise Fixed("password")
    values={"host":host,"port":port,"dbname":database,"user":ACCOUNT,"password":password}; values.update(query)
    dsn=psycopg.conninfo.make_conninfo(**values)
    del password,wrapped,values,topology,query
    return dsn

def storage_contract(payload,ram_role):
    storage=payload.pop("storage")
    if not isinstance(storage,dict) or set(storage)!=STORAGE or hashlib.sha256(canonical(storage)).hexdigest()!=STORAGE_SHA: raise Fixed("storage")
    region=storage.get("NOTEAI_OSS_REGION","")
    if storage.get("NOTEAI_PRIVATE_STORAGE_BACKEND")!="aliyun_oss" or storage.get("NOTEAI_OSS_RAM_ROLE")!=ram_role or not re.fullmatch(r"cn-[a-z0-9-]{2,32}",region) or storage.get("NOTEAI_OSS_ENDPOINT")!="https://oss-{}-internal.aliyuncs.com".format(region) or not storage.get("NOTEAI_OSS_PRIVATE_BUCKET") or not storage.get("NOTEAI_PRIVATE_STORAGE_KEY_EPOCH") or storage.get("NOTEAI_OSS_KEY_PREFIX","").strip("/")!="noteai-private": raise Fixed("storage")
    return storage

def runtime_modules():
    os.environ["DATABASE_URL"]=IMPORT_GUARD_DATABASE_URL
    try:
        sys.path.insert(0,"/app/model")
        import private_storage,storage_recovery_evidence as recovery,psycopg
        from psycopg.rows import dict_row
        from psycopg.pq import TransactionStatus
    except BaseException: raise Fixed("import")
    finally: os.environ.pop("DATABASE_URL",None)
    return private_storage,recovery,psycopg,dict_row,TransactionStatus

class Adapter:
    postgres=True
    def __init__(self,connection): self.connection=connection
    def fetchall(self,statement,parameters=()): return self.connection.execute(statement.replace("?","%s"),tuple(parameters)).fetchall()

class MetadataOnlyClient:
    def __init__(self,client): self._client=client; self.list_count=0; self.head_count=0
    def list_objects_v2(self,request): self.list_count+=1; return self._client.list_objects_v2(request)
    def head_object(self,request): self.head_count+=1; return self._client.head_object(request)
    def __getattr__(self,name): raise Fixed("object_operation")

def one(connection,statement,parameters,code):
    rows=connection.execute(statement,parameters).fetchall()
    if len(rows)!=1: raise Fixed(code)
    return dict(rows[0])

def owner_gate(connection,migrations):
    session=one(connection,"""
WITH executor AS (SELECT oid,rolsuper,rolcanlogin FROM pg_roles WHERE rolname=session_user),
managed AS (SELECT oid FROM pg_roles WHERE rolname=%s)
SELECT session_user=%s AS account_exact,session_user=current_user AND current_user=current_role AS identity_unchanged,
current_setting('default_transaction_read_only')='on' AS default_read_only,current_setting('transaction_read_only')='on' AS transaction_read_only,
current_setting('transaction_isolation')='repeatable read' AS isolation_exact,current_setting('server_version_num')::integer>=160000 AND current_setting('server_version_num')::integer<170000 AS server_version_exact,
COALESCE((SELECT NOT rolsuper FROM executor),FALSE) AS executor_non_superuser,COALESCE((SELECT rolcanlogin FROM executor),FALSE) AS executor_can_login,
COALESCE((SELECT pg_has_role(session_user,oid,'MEMBER') FROM managed),FALSE) AS managed_membership,pg_has_role(session_user,%s,'SET') AS owner_set_capable,
COALESCE((SELECT pg_has_role(oid,%s,'SET') FROM managed),FALSE) AS managed_owner_set_capable,
(SELECT COUNT(*)::integer FROM pg_auth_members m WHERE m.member=(SELECT oid FROM executor) AND m.roleid=(SELECT oid FROM managed)) AS direct_managed_membership_count,
(SELECT COUNT(*)::integer FROM pg_auth_members m WHERE m.member=(SELECT oid FROM executor)) AS direct_membership_count FROM executor
""",(MANAGED,ACCOUNT,OWNER,OWNER),"session")
    expected={"account_exact":True,"identity_unchanged":True,"default_read_only":True,"transaction_read_only":True,"isolation_exact":True,"server_version_exact":True,"executor_non_superuser":True,"executor_can_login":True,"managed_membership":True,"owner_set_capable":True,"managed_owner_set_capable":True,"direct_managed_membership_count":1,"direct_membership_count":1}
    if session!=expected: raise Fixed("session")
    connection.execute("SET LOCAL ROLE noteai_admin")
    owner=one(connection,"""
WITH owner_role AS (SELECT oid,rolsuper FROM pg_roles WHERE rolname=%s),base_tables AS (
SELECT c.relname::text AS name,c.relowner,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p'))
SELECT session_user=%s AS account_exact,current_user=%s AND current_role=%s AS owner_activated,
current_setting('default_transaction_read_only')='on' AS default_read_only,current_setting('transaction_read_only')='on' AS transaction_read_only,
current_setting('transaction_isolation')='repeatable read' AS isolation_exact,(SELECT COUNT(*) FROM owner_role)=1 AS owner_exists,
COALESCE((SELECT NOT rolsuper FROM owner_role),FALSE) AS owner_non_superuser,has_schema_privilege(current_user,'public','USAGE') AS schema_usage,
COALESCE(array_agg(name ORDER BY name),ARRAY[]::text[]) AS table_names,COUNT(*)::integer AS table_count,
COUNT(*) FILTER (WHERE relowner<>(SELECT oid FROM owner_role))::integer AS owner_mismatch_count,
COALESCE(array_agg(name ORDER BY name) FILTER (WHERE relrowsecurity),ARRAY[]::text[]) AS rls_names,
COUNT(*) FILTER (WHERE relrowsecurity)::integer AS rls_count,COUNT(*) FILTER (WHERE relforcerowsecurity)::integer AS force_rls_count FROM base_tables
""",(OWNER,ACCOUNT,OWNER,OWNER),"owner")
    fixed={key:owner[key] for key in ("account_exact","owner_activated","default_read_only","transaction_read_only","isolation_exact","owner_exists","owner_non_superuser","schema_usage")}
    if fixed!={key:True for key in fixed}: raise Fixed("owner")
    if tuple(owner["table_names"])!=TABLES or owner["table_count"]!=56 or owner["owner_mismatch_count"]!=0: raise Fixed("tables")
    if tuple(owner["rls_names"])!=RLS or owner["rls_count"]!=19 or owner["force_rls_count"]!=0: raise Fixed("rls")
    connection.execute("SET LOCAL search_path=pg_catalog,public")
    connection.execute("SET LOCAL row_security=off")
    guard=one(connection,"SELECT current_user=%s AND current_role=%s AS owner_activated,current_setting('default_transaction_read_only')='on' AS default_read_only,current_setting('transaction_read_only')='on' AS transaction_read_only,current_setting('transaction_isolation')='repeatable read' AS isolation_exact,current_setting('search_path')='pg_catalog, public' AS search_path_exact,current_setting('row_security')='off' AS row_security_off",(OWNER,OWNER),"rls")
    if guard!={"owner_activated":True,"default_read_only":True,"transaction_read_only":True,"isolation_exact":True,"search_path_exact":True,"row_security_off":True}: raise Fixed("rls")
    ledger=[dict(row) for row in connection.execute("SELECT version,sha256 FROM schema_migrations ORDER BY version").fetchall()]
    if ledger!=migrations: raise Fixed("migrations")

def write_once(body):
    fd=os.open("/output/restored-manifest.json",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        offset=0
        while offset<len(body):
            written=os.write(fd,body[offset:])
            if written<=0: raise Fixed("write")
            offset+=written
        os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
    finally: os.close(fd)

state={"database_attempted":False,"rollback":False,"manifest_written":False}
try:
    capabilities(); ram_role=metadata_identity(); payload,private=decrypt_payload()
    private_storage,recovery,psycopg,dict_row,TransactionStatus=runtime_modules()
    source=source_manifest(payload,recovery); storage=storage_contract(payload,ram_role); dsn=topology_and_password(payload,private,psycopg)
    if payload!={"schema_version":1}: raise Fixed("payload")
    del private,payload
    for name in list(os.environ):
        if name.startswith(("ALIBABA_CLOUD_","ALICLOUD_","OSS_","PG")) or name=="DATABASE_URL": os.environ.pop(name,None)
    os.environ.update(storage)
    if not private_storage.configure_from_environment(): raise Fixed("backend")
    backend=private_storage.get_object_backend()
    if not isinstance(backend,private_storage.AliyunOssObjectBackend): raise Fixed("backend")
    metadata_client=MetadataOnlyClient(backend.client); backend.client=metadata_client
    migrations=[{"version":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(Path("/app/model/migrations/postgres").glob("*.sql"))]
    if len(migrations)!=17 or migrations[-1]["version"]!="0017_durable_ai_postgres_wakeup.sql": raise Fixed("migrations")
    connection=None; active=False; restored=None
    state["database_attempted"]=True
    try:
        connection=psycopg.connect(dsn,row_factory=dict_row,connect_timeout=10,options="-c timezone=UTC -c default_transaction_read_only=on",autocommit=True)
        del dsn
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"); active=True
        if connection.info.transaction_status!=TransactionStatus.INTRANS: raise Fixed("session")
        connection.execute("SET LOCAL statement_timeout='600s'"); connection.execute("SET LOCAL lock_timeout='5s'"); connection.execute("SET LOCAL idle_in_transaction_session_timeout='900s'")
        owner_gate(connection,migrations)
        restored=recovery.capture_manifest(release_commit=RELEASE,storage=Adapter(connection),backend=backend,require_objects=True,max_rows_per_table=1000000,max_objects=100000)
        recovery.validate_manifest(restored); connection.rollback()
        if connection.info.transaction_status!=TransactionStatus.IDLE: raise Fixed("rollback")
        active=False; state["rollback"]=True
    finally:
        if connection is not None:
            if active:
                try: connection.rollback()
                except BaseException: pass
            try: connection.close()
            except BaseException: pass
        try: del dsn
        except NameError: pass
    if restored["database"]["migrations"]!=migrations or restored["database"]["engine"]!="postgresql" or restored["database"]["table_count"]!=56 or len(restored["database"]["tables"])!=56: raise Fixed("database")
    if metadata_client.list_count<1 or metadata_client.head_count!=restored["objects"]["object_count"]: raise Fixed("object_operation")
    if any(restored["privacy"].values()) or restored["objects"].get("not_captured") is True or restored["objects"]["content_included"] is not False or restored["objects"]["object_keys_included"] is not False: raise Fixed("privacy")
    body=canonical(restored,True)
    if not 1<=len(body)<=1048576: raise Fixed("size")
    write_once(body); state["manifest_written"]=True
    comparison=recovery.verify_restore(source,restored)
    if set(comparison)!={"verified","mismatch_codes","source_manifest_sha256","restored_manifest_sha256","content_included"} or comparison["source_manifest_sha256"]!=SOURCE_MANIFEST_SHA or comparison["restored_manifest_sha256"]!=restored["manifest_sha256"] or comparison["content_included"] is not False or not isinstance(comparison["mismatch_codes"],list) or len(comparison["mismatch_codes"])!=len(set(comparison["mismatch_codes"])) or set(comparison["mismatch_codes"])-MISMATCH_CODES: raise Fixed("comparison")
    verified=comparison["verified"] is True and comparison["mismatch_codes"]==[]
    known_mismatch=comparison["verified"] is False and bool(comparison["mismatch_codes"])
    if not (verified or known_mismatch): raise Fixed("comparison")
    receipt={"NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER":"PASS" if verified else "FAIL","comparison_exact":verified,"database_connection_count":1,"database_transaction_count":1,"database_write_count":0,"force_rls_table_count":0,"incident_class":"CONNECTED_KNOWN_READ_ONLY" if verified else "CONNECTED_KNOWN_READ_ONLY_MISMATCH","managed_owner_activation_count":1,"manifest_bytes":len(body),"mismatch_codes":comparison["mismatch_codes"],"object_contents_read":0,"object_keys_emitted":0,"object_write_count":0,"oss_get_request_count":0,"oss_head_request_count":metadata_client.head_count,"oss_list_request_count":metadata_client.list_count,"oss_operation_mode":"LIST_HEAD_ONLY","owner_mismatch_count":0,"owner_table_contract_exact":True,"persistent_permission_mutation_count":0,"postgresql_major_version":16,"restored_manifest_file_sha256":hashlib.sha256(body).hexdigest(),"restored_manifest_sha256":restored["manifest_sha256"],"rls_contract_exact":True,"rls_table_count":19,"row_security_off":True,"row_values_emitted":0,"search_path_exact":True,"secret_values_emitted":0,"source_manifest_sha256":SOURCE_MANIFEST_SHA,"table_count":56,"transaction_terminal":"ROLLBACK","verified":verified}
    emit(receipt,0 if verified else 5,1)
except BaseException as exc:
    code=str(exc) if isinstance(exc,Fixed) else type(exc).__name__
    safe=frozenset({"session","owner","tables","rls","migrations","rollback","database","object_operation","privacy","size","write","comparison","OperationalError","DatabaseError","ProgrammingError","InsufficientPrivilege","TimeoutError"})
    if code not in safe and code not in PRE_CODES: code="unexpected"
    if not state["database_attempted"] and code in PRE_CODES:
        emit({"NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER":"FAIL","automatic_retry_allowed":False,"code":code,"database_attempted_state":"NO","same_invocation_replay_allowed":False},3,2)
    emit({"NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER":"UNKNOWN","automatic_retry_allowed":False,"code":code,"database_attempted_state":"UNKNOWN","manifest_write_state":"COMMITTED" if state["manifest_written"] else "UNKNOWN","readback_required":True,"rollback_state":"CONFIRMED" if state["rollback"] else "UNKNOWN","same_invocation_replay_allowed":False},4,2)
PY
chmod 0600 "$DRIVER_PATH"

[ "$(systemctl is-active docker)" = active ] || fail docker_service
/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default version >/dev/null 2>&1 || fail docker_version
[ -z "$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" ] || unknown task_container
image_row="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default image inspect "$IMAGE_REF" --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{index .Config.Labels "org.opencontainers.image.revision"}}')" || fail image
[ "$image_row" = 'sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95|linux|amd64|cad5ce35664f617c6e19f90a6159285ddf975594' ] || fail image
[ "$(/usr/sbin/ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = 0 ] || fail db_socket_before

phase='restored_read_only_capture'; container_attempted=1
set +e
/usr/bin/timeout --foreground --signal=TERM --kill-after=20s 1260s /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default run --rm \
  --name "$CONTAINER_NAME" --label "$CONTAINER_LABEL" --label "com.noteai.invocation=$invocation_label" --cidfile "$CIDFILE" --pull never --network host --workdir /tmp --user 0:0 --read-only \
  --cap-drop ALL --cap-add DAC_READ_SEARCH --security-opt no-new-privileges:true --memory 768m --cpus 0.75 --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777 \
  --mount type=bind,src="$CONTROL_ROOT",dst=/input/control,readonly \
  --mount type=bind,src="$DRIVER_PATH",dst=/task/driver.py,readonly \
  --mount type=bind,src="$OUTPUT_ROOT",dst=/output \
  --entrypoint /usr/local/bin/python3.11 "$IMAGE_REF" -I -B /task/driver.py >"$HELPER_OUT" 2>"$HELPER_ERR"
helper_rc=$?
set -e
cleanup_container || unknown container_cleanup
container_attempted=0

if [ "$helper_rc" -eq 3 ]; then
  phase='driver_preconnect_failure'
  [ "$(stat -c '%u|%g|%a|%h|%s' "$HELPER_OUT")" = '0|0|600|1|0' ] || unknown preconnect_stdout
  [ "$(stat -c '%u|%g|%a|%h' "$HELPER_ERR")" = '0|0|600|1' ] && [ "$(stat -c '%s' "$HELPER_ERR")" -le 1024 ] || unknown preconnect_stderr
  preconnect_phase="$(python3 -I -B - "$HELPER_ERR" <<'PY'
import json,re,sys
row=json.load(open(sys.argv[1],encoding="ascii"))
if set(row)!={"NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER","automatic_retry_allowed","code","database_attempted_state","same_invocation_replay_allowed"} or row["NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER"]!="FAIL" or row["database_attempted_state"]!="NO" or row["automatic_retry_allowed"] is not False or row["same_invocation_replay_allowed"] is not False or type(row["code"]) is not str or re.fullmatch(r"[A-Za-z_]{1,32}",row["code"]) is None: raise SystemExit(2)
print("driver_"+row["code"])
PY
)" || unknown preconnect_contract
  verify_task_retained || unknown preconnect_retention
  completed=1; trap - EXIT
  printf '{"NOTEAI_ITEM26_RESTORED_CAPTURE":"FAIL","automatic_retry_allowed":false,"database_attempted_state":"NO","incident_class":"PRE_CONNECT","new_capture_allowed":false,"phase":"%s","same_invocation_replay_allowed":false}\n' "$preconnect_phase" >&2
  exit 3
fi

if [ "$helper_rc" -eq 4 ]; then
  phase='driver_unknown_contract'
  [ "$(stat -c '%u|%g|%a|%h|%s' "$HELPER_OUT")" = '0|0|600|1|0' ] || unknown driver_unknown_stdout
  [ "$(stat -c '%u|%g|%a|%h' "$HELPER_ERR")" = '0|0|600|1' ] && [ "$(stat -c '%s' "$HELPER_ERR")" -le 1024 ] || unknown driver_unknown_stderr
  driver_phase="$(python3 -I -B - "$HELPER_ERR" <<'PY'
import json,re,sys
row=json.load(open(sys.argv[1],encoding="ascii"))
expected={"NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER","automatic_retry_allowed","code","database_attempted_state","manifest_write_state","readback_required","rollback_state","same_invocation_replay_allowed"}
if set(row)!=expected or row["NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER"]!="UNKNOWN" or row["automatic_retry_allowed"] is not False or row["database_attempted_state"]!="UNKNOWN" or row["manifest_write_state"] not in {"COMMITTED","UNKNOWN"} or row["readback_required"] is not True or row["rollback_state"] not in {"CONFIRMED","UNKNOWN"} or row["same_invocation_replay_allowed"] is not False or type(row["code"]) is not str or re.fullmatch(r"[A-Za-z_]{1,32}",row["code"]) is None: raise SystemExit(2)
print("driver_"+row["code"])
PY
)" || unknown driver_unknown_contract
  verify_task_retained || unknown driver_unknown_retention
  unknown "$driver_phase"
fi
if [ "$helper_rc" -ne 0 ] && [ "$helper_rc" -ne 5 ]; then unknown driver_terminal; fi
[ "$(stat -c '%u|%g|%a|%h|%s' "$HELPER_ERR")" = '0|0|600|1|0' ] || unknown driver_stderr
[ "$(stat -c '%u|%g|%a|%h' "$HELPER_OUT")" = '0|0|600|1' ] && [ "$(stat -c '%s' "$HELPER_OUT")" -le 4096 ] || unknown driver_stdout

validated="$(python3 -I -B - "$HELPER_OUT" "$OUTPUT_ROOT/restored-manifest.json" "$OUTPUT_ROOT/reconciliation.json" "$helper_rc" <<'PY'
import hashlib,json,os,re,stat,sys
summary_path,manifest_path,receipt_path,returncode=sys.argv[1],sys.argv[2],sys.argv[3],int(sys.argv[4])
HEX64=re.compile(r"^[0-9a-f]{64}$")
MISMATCH=frozenset({"release_commit","database_engine","database_schema","database_migrations","database_tables","database_references","private_objects"})
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("duplicate")
        result[key]=value
    return result
def canonical(value): return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")
def read(path,maximum):
    row=os.lstat(path)
    if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid!=0 or row.st_gid!=0 or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not 1<=row.st_size<=maximum: raise SystemExit(2)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: body=os.read(fd,maximum+1); current=os.fstat(fd)
    finally: os.close(fd)
    if len(body)!=row.st_size or (current.st_dev,current.st_ino)!=(row.st_dev,row.st_ino): raise SystemExit(2)
    return body
def write_once(path,body):
    parent,name=os.path.split(path); dirfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dirfd)
        try:
            offset=0
            while offset<len(body):
                written=os.write(fd,body[offset:])
                if written<=0: raise OSError("short write")
                offset+=written
            os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
        finally: os.close(fd)
        os.fsync(dirfd)
    finally: os.close(dirfd)
summary_body=read(summary_path,4096); manifest_body=read(manifest_path,1048576)
summary=json.loads(summary_body.decode("ascii"),object_pairs_hook=no_duplicates); manifest=json.loads(manifest_body.decode("ascii"),object_pairs_hook=no_duplicates)
if canonical(summary)!=summary_body or canonical(manifest)!=manifest_body: raise SystemExit(2)
expected={"NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER","comparison_exact","database_connection_count","database_transaction_count","database_write_count","force_rls_table_count","incident_class","managed_owner_activation_count","manifest_bytes","mismatch_codes","object_contents_read","object_keys_emitted","object_write_count","oss_get_request_count","oss_head_request_count","oss_list_request_count","oss_operation_mode","owner_mismatch_count","owner_table_contract_exact","persistent_permission_mutation_count","postgresql_major_version","restored_manifest_file_sha256","restored_manifest_sha256","rls_contract_exact","rls_table_count","row_security_off","row_values_emitted","search_path_exact","secret_values_emitted","source_manifest_sha256","table_count","transaction_terminal","verified"}
if set(summary)!=expected or summary["NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER"]!=("PASS" if returncode==0 else "FAIL") or summary["incident_class"]!=("CONNECTED_KNOWN_READ_ONLY" if returncode==0 else "CONNECTED_KNOWN_READ_ONLY_MISMATCH") or summary["verified"] is not (returncode==0) or summary["comparison_exact"] is not (returncode==0) or bool(summary["mismatch_codes"]) is not (returncode==5): raise SystemExit(2)
fixed=(summary["database_connection_count"],summary["database_transaction_count"],summary["database_write_count"],summary["transaction_terminal"],summary["postgresql_major_version"],summary["table_count"],summary["managed_owner_activation_count"],summary["owner_mismatch_count"],summary["rls_table_count"],summary["force_rls_table_count"],summary["persistent_permission_mutation_count"],summary["object_write_count"],summary["object_contents_read"],summary["object_keys_emitted"],summary["oss_get_request_count"],summary["row_values_emitted"],summary["secret_values_emitted"])
if fixed!=(1,1,0,"ROLLBACK",16,56,1,0,19,0,0,0,0,0,0,0,0) or summary["oss_operation_mode"]!="LIST_HEAD_ONLY" or type(summary["oss_list_request_count"]) is not int or summary["oss_list_request_count"]<1 or type(summary["oss_head_request_count"]) is not int or summary["oss_head_request_count"]<0 or summary["owner_table_contract_exact"] is not True or summary["rls_contract_exact"] is not True or summary["row_security_off"] is not True or summary["search_path_exact"] is not True: raise SystemExit(2)
if type(summary["manifest_bytes"]) is not int or summary["manifest_bytes"]!=len(manifest_body) or any(type(summary[key]) is not str or HEX64.fullmatch(summary[key]) is None for key in ("restored_manifest_file_sha256","restored_manifest_sha256","source_manifest_sha256")) or summary["restored_manifest_file_sha256"]!=hashlib.sha256(manifest_body).hexdigest() or summary["restored_manifest_sha256"]!=manifest.get("manifest_sha256"): raise SystemExit(2)
if type(summary["mismatch_codes"]) is not list or any(type(code) is not str for code in summary["mismatch_codes"]) or len(summary["mismatch_codes"])!=len(set(summary["mismatch_codes"])) or set(summary["mismatch_codes"])-MISMATCH: raise SystemExit(2)
summary["NOTEAI_ITEM26_RESTORED_CAPTURE"]=summary.pop("NOTEAI_ITEM26_RESTORED_CAPTURE_DRIVER")
summary.update({"attempt_sentinel_retained":True,"automatic_retry_allowed":False,"container_residue_count":0,"control_material_retained":True,"new_capture_allowed":False,"readback_required":False,"reconciliation_retained":True,"reconciliation_schema_version":"noteai.item26.restored-reconciliation.v1","restored_manifest_retained":True,"runtime_container_start_count":1,"same_invocation_replay_allowed":False,"task_root_retained":True,"transfer_retained":True})
receipt_body=canonical(summary); write_once(receipt_path,receipt_body)
if read(receipt_path,8192)!=receipt_body: raise SystemExit(2)
print("OK|{}|{}|{}|{}|{}".format(len(manifest_body),summary["restored_manifest_file_sha256"],len(receipt_body),hashlib.sha256(receipt_body).hexdigest(),returncode))
PY
)" || unknown driver_contract
IFS='|' read -r tag manifest_bytes manifest_file_sha receipt_bytes receipt_file_sha terminal_rc <<<"$validated"; [ "$tag" = OK ] || unknown driver_contract

phase='terminal_promotion'
[ "$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'reconciliation.json\nrestored-manifest.json' ] || unknown output_inventory
[ ! -e "$FINAL_ROOT" ] && [ ! -L "$FINAL_ROOT" ] || unknown final_preexisting
mv "$OUTPUT_ROOT" "$FINAL_ROOT" || unknown final_move
python3 -I -B - "$BASE_ROOT" <<'PY' || unknown final_fsync
import os,sys
fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: os.fsync(fd)
finally: os.close(fd)
PY
[ "$(stat -c '%F|%u|%g|%a' "$FINAL_ROOT")" = 'directory|0|0|700' ] || unknown final_root
[ "$(find "$FINAL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'reconciliation.json\nrestored-manifest.json' ] || unknown final_inventory
[ "$(stat -c '%F|%u|%g|%a|%h|%s' "$FINAL_MANIFEST")" = "regular file|0|0|600|1|$manifest_bytes" ] || unknown final_manifest
[ "$(sha256sum "$FINAL_MANIFEST" | awk '{print $1}')" = "$manifest_file_sha" ] || unknown final_hash
[ "$(stat -c '%F|%u|%g|%a|%h|%s' "$FINAL_RECEIPT")" = "regular file|0|0|600|1|$receipt_bytes" ] || unknown final_receipt
[ "$(sha256sum "$FINAL_RECEIPT" | awk '{print $1}')" = "$receipt_file_sha" ] || unknown final_receipt_hash
[ "$(/usr/sbin/ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = 0 ] || unknown db_socket_after

receipt="$(<"$FINAL_RECEIPT")" || unknown receipt
verify_task_retained || unknown task_retention
verify_attempt_sentinel || unknown replay_barrier

phase='complete'; completed=1; trap - EXIT
if [ "$terminal_rc" = '0' ]; then printf '%s\n' "$receipt"; exit 0; fi
printf '%s\n' "$receipt" >&2
exit 3
