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

readonly EXPECTED_INSTANCE='i-wz9j36od3nf2b1uw7bvg'
readonly EXPECTED_ROLE='noteai-storage-api-20260729-c60cc608'
readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly CONTROL_ROOT='/run/noteai-item26-source-account-v2'
readonly PRIVATE_KEY="$CONTROL_ROOT/control-private.pem"
readonly PUBLIC_KEY="$CONTROL_ROOT/control-public.pem"
readonly ENVELOPE="$CONTROL_ROOT/control-database-url.enc"
readonly API_ENV='/etc/noteai/api.env'
readonly STORAGE_ENV='/etc/noteai/private-storage.env'
readonly TASK_ROOT='/run/noteai-item26-source-manifest-capture-v3'
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly OUTPUT_ROOT="$TASK_ROOT/output"
readonly DRIVER_PATH="$TASK_ROOT/driver.py"
readonly HELPER_OUT="$TASK_ROOT/helper.stdout"
readonly HELPER_ERR="$TASK_ROOT/helper.stderr"
readonly FINAL_ROOT='/run/noteai-item26-source-manifest-v3'
readonly FINAL_MANIFEST="$FINAL_ROOT/source-manifest.json"
readonly CONTAINER_NAME='noteai-item26-source-manifest-capture-v3'
readonly CONTAINER_LABEL='com.noteai.task=PROD-FIRST-LAUNCH-PITR-RESTORE-001-source-manifest-v3'

phase='preflight'
known_failure=0
task_created=0
task_cleaned=0
container_attempted=0
database_attempted=0
manifest_committed=0
completed=0

fail() { known_failure=1; phase="$1"; exit 3; }

cleanup_container() {
  local ids label image
  ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || return 1
  if [ -n "$ids" ]; then
    [ "$container_attempted" -eq 1 ] || return 1
    [ "$(printf '%s\n' "$ids" | wc -l | tr -d ' ')" = '1' ] || return 1
    label="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$ids" --format '{{index .Config.Labels "com.noteai.task"}}')" || return 1
    image="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$ids" --format '{{.Image}}')" || return 1
    [ "com.noteai.task=$label" = "$CONTAINER_LABEL" ] && [ "$image" = "$IMAGE_CONFIG" ] || return 1
    /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default rm -f "$ids" >/dev/null 2>&1 || return 1
    ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || return 1
    [ -z "$ids" ] || return 1
  fi
}

cleanup_task() {
  if [ "$task_created" -eq 1 ] && [ "$task_cleaned" -eq 0 ]; then
    [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$TASK_ROOT")" = '0|0|700' ] || return 1
    rm -rf --one-file-system "$TASK_ROOT" || return 1
    [ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
    task_cleaned=1
  fi
}

on_exit() {
  local rc=$? cleanup_ok=1
  if [ "$completed" -eq 1 ] && [ "$rc" -eq 0 ]; then return 0; fi
  trap - EXIT
  if [ "$task_created" -eq 1 ] && [ -d "$DOCKER_CONFIG_ROOT" ]; then cleanup_container >/dev/null 2>&1 || cleanup_ok=0; fi
  if [ "$database_attempted" -eq 0 ] && [ "$manifest_committed" -eq 0 ]; then cleanup_task >/dev/null 2>&1 || cleanup_ok=0; fi
  if [ "$known_failure" -eq 1 ] && [ "$database_attempted" -eq 0 ] && [ "$manifest_committed" -eq 0 ] && [ "$cleanup_ok" -eq 1 ] && [ ! -e "$FINAL_ROOT" ] && [ ! -L "$FINAL_ROOT" ]; then
    printf '%s\n' "NOTEAI_ITEM26_SOURCE_MANIFEST=FAIL incident_class=PRE_CONNECT phase=$phase cleanup=VERIFIED_TASK_ZERO database_connections=0 database_writes=0 object_writes=0 row_values_emitted=0 object_keys_emitted=0 secret_values_emitted=0 automatic_retry_allowed=false" >&2
    exit 3
  fi
  printf '%s\n' "NOTEAI_ITEM26_SOURCE_MANIFEST=UNKNOWN incident_class=CONNECTED_UNKNOWN phase=$phase cleanup=UNKNOWN database_attempted=$database_attempted manifest_committed=$manifest_committed readback_required=true database_writes=0 object_writes=0 row_values_emitted=0 object_keys_emitted=0 secret_values_emitted=0 automatic_retry_allowed=false" >&2
  exit 4
}
trap on_exit EXIT

[ "$(id -u)" = '0' ] || fail root
for tool in docker systemctl stat sha256sum openssl awk grep ss python3 timeout wc tr sort rm mv find; do command -v "$tool" >/dev/null 2>&1 || fail tool; done
[ -x /usr/bin/docker ] && [ -x /usr/bin/env ] && [ -x /usr/bin/timeout ] && [ -x /usr/bin/openssl ] || fail absolute_tool
[ -d /run ] && [ ! -L /run ] || fail run_root
if [ -e "$TASK_ROOT" ] || [ -L "$TASK_ROOT" ] || [ -e "$FINAL_ROOT" ] || [ -L "$FINAL_ROOT" ]; then phase='preexisting_path'; exit 4; fi

identity="$({ python3 -I -B - <<'PY'
import re, urllib.request
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): raise RuntimeError("redirect")
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
if not re.fullmatch(r"i-[a-z0-9]+",values[0]) or values[0]!="i-wz9j36od3nf2b1uw7bvg" or [row for row in values[1].splitlines() if row]!=["noteai-storage-api-20260729-c60cc608"]: raise SystemExit(2)
print("HOST_IDENTITY_EXACT")
PY
} 2>/dev/null)" || fail identity
[ "$identity" = HOST_IDENTITY_EXACT ] || fail identity

[ -d "$CONTROL_ROOT" ] && [ ! -L "$CONTROL_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$CONTROL_ROOT")" = '0|0|700' ] || { phase=control_root; exit 4; }
[ "$(find "$CONTROL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'control-database-url.enc\ncontrol-private.pem\ncontrol-public.pem' ] || { phase=control_inventory; exit 4; }
[ "$(stat -c '%F|%u|%g|%a|%h' "$PRIVATE_KEY")" = 'regular file|0|0|600|1' ] || { phase=private_key; exit 4; }
[ "$(stat -c '%F|%u|%g|%a|%h|%s' "$PUBLIC_KEY")" = 'regular file|0|0|600|1|625' ] || { phase=public_key; exit 4; }
[ "$(stat -c '%F|%u|%g|%a|%h|%s' "$ENVELOPE")" = 'regular file|0|0|600|1|@@ENVELOPE_BYTES@@' ] || { phase=envelope; exit 4; }
[ "$(sha256sum "$ENVELOPE" | awk '{print $1}')" = '@@ENVELOPE_SHA256@@' ] || { phase=envelope_hash; exit 4; }
for env_file in "$API_ENV" "$STORAGE_ENV"; do
  [ "$(stat -c '%F|%u|%g|%a|%h' "$env_file")" = 'regular file|0|0|600|1' ] || fail env_metadata
  [ "$(stat -c '%s' "$env_file")" -ge 1 ] && [ "$(stat -c '%s' "$env_file")" -le 16384 ] || fail env_size
done
public_sha="$(/usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl pkey -pubin -in "$PUBLIC_KEY" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || fail public_hash
private_sha="$(/usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || fail private_hash
[ "$public_sha" = '@@PUBLIC_KEY_SHA256@@' ] && [ "$private_sha" = "$public_sha" ] || fail key_pair

mkdir -m 0700 "$TASK_ROOT"; task_created=1
mkdir -m 0700 "$DOCKER_CONFIG_ROOT" "$OUTPUT_ROOT"
printf '%s' '{}' >"$DOCKER_CONFIG_ROOT/config.json"; chmod 0600 "$DOCKER_CONFIG_ROOT/config.json"
cat >"$DRIVER_PATH" <<'PY'
import base64, hashlib, json, os, re, stat, sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ACCOUNT="noteai_item26_source_read_20260811_v2"; ROLE="noteai-storage-api-20260729-c60cc608"; RELEASE="cad5ce35664f617c6e19f90a6159285ddf975594"
OWNER="noteai_admin"; MANAGED="pg_rds_superuser"
IMPORT_GUARD_DATABASE_URL="postgresql:///noteai_item26_import_guard"
QUERY=frozenset({"sslmode","connect_timeout","target_session_attrs","channel_binding","keepalives","keepalives_idle","keepalives_interval","keepalives_count","tcp_user_timeout"})
STORAGE=frozenset({"NOTEAI_PRIVATE_STORAGE_BACKEND","NOTEAI_OSS_PRIVATE_BUCKET","NOTEAI_OSS_REGION","NOTEAI_OSS_ENDPOINT","NOTEAI_OSS_RAM_ROLE","NOTEAI_PRIVATE_STORAGE_KEY_EPOCH","NOTEAI_OSS_KEY_PREFIX"})
TABLES=("account_deletion_requests","admin_sessions","ai_dispatch_state","ai_operation_admissions","ai_operation_events","ai_operation_media_refs","ai_operation_outbox","ai_operation_settlements","ai_operations","ai_payload_refs","ai_provider_attempts","analysis_log","auth_login_limits","auth_verification_challenges","chat_sessions","content_retention","crawler_events","credit_transactions","credits","growth_records","hot_keywords","idempotency_requests","keyword_snapshots","managed_prompts","model_usage_records","notes","payment_cash_ledger","payment_credit_consumptions","payment_credit_positions","payment_entitlement_ledger","payment_events","payment_orders","payment_reconciliation_items","payment_reconciliation_runs","payment_refunds","payment_settlement_summaries","private_media_refs","prompt_history","saved_diagnoses","schema_migrations","subscriptions","system_settings","tracked_notes","tracking_provider_attempts","usage_records","user_contract_acceptances","user_learn","user_memories","user_sessions","users","xhs_crawler_health","xhs_freshness_ledger","xhs_trends_provider_attempts","xhs_trends_runs","xhs_trends_service_state","xhs_trends_snapshot_evidence")
RLS=("admin_sessions","ai_dispatch_state","ai_operation_media_refs","ai_operation_outbox","ai_operation_settlements","ai_payload_refs","content_retention","payment_cash_ledger","payment_credit_consumptions","payment_credit_positions","payment_entitlement_ledger","payment_events","payment_orders","payment_reconciliation_items","payment_reconciliation_runs","payment_refunds","payment_settlement_summaries","private_media_refs","system_settings")
FIXED_CODES=frozenset({"metadata","race","read","env","dsn","identity","capability","envelope","key","write","output","payload","api_env","topology","storage","backend","session","owner","tables","rls","migrations","database","references","privacy","size","rollback"})
AAD=b"noteai-managed-secrets-v1"
class Fixed(Exception): pass

def read_private(path,low=1,high=131072):
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

def env_file(path):
    body=read_private(path,1,16384)
    if not body.endswith(b"\n") or b"\x00" in body or b"\r" in body: raise Fixed("env")
    values={}
    for raw_line in body.splitlines():
        line=raw_line.strip()
        if not line or line.startswith(b"#"): continue
        if line.startswith(b"export "): line=line[7:].lstrip()
        if b"=" not in line: raise Fixed("env")
        name,value=line.split(b"=",1); name=name.strip()
        try: name=name.decode("ascii"); value=value.decode("utf-8")
        except UnicodeError: raise Fixed("env")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",name) or name in values: raise Fixed("env")
        values[name]=value
    return values

def parsed(value,user):
    try: result=urlsplit(value); pairs=parse_qsl(result.query,keep_blank_values=True,strict_parsing=True); port=result.port or 5432
    except (TypeError,ValueError): raise Fixed("dsn")
    names=[name.lower() for name,_ in pairs]
    if not (result.scheme in {"postgres","postgresql"} and unquote(result.username or "")==user and result.password not in (None,"") and result.hostname and 1<=port<=65535 and result.path not in {"","/"} and not result.fragment and len(names)==len(set(names)) and set(names)<=QUERY): raise Fixed("dsn")
    return result,tuple(sorted((name.lower(),value) for name,value in pairs))

def capabilities():
    values={}
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if ":" in line:
            key,value=line.split(":",1); values[key]=value.strip()
    if os.geteuid()!=0 or os.getegid()!=0 or values.get("NoNewPrivs")!="1": raise Fixed("identity")
    if any(int(values.get(key,"-1"),16)!=4 for key in ("CapEff","CapPrm","CapBnd")) or any(int(values.get(key,"-1"),16)!=0 for key in ("CapInh","CapAmb")): raise Fixed("capability")

def decrypt():
    envelope=json.loads(read_private("/input/control/control-database-url.enc"))
    if not isinstance(envelope,dict) or set(envelope)!={"schema_version","algorithm","wrapped_key","nonce","ciphertext"} or envelope["schema_version"]!=1 or envelope["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM": raise Fixed("envelope")
    key=serialization.load_pem_private_key(read_private("/input/control/control-private.pem",2000,5000),password=None)
    if not isinstance(key,rsa.RSAPrivateKey) or key.key_size!=3072 or key.public_key().public_numbers().e!=65537: raise Fixed("key")
    wrapped=base64.b64decode(envelope["wrapped_key"],validate=True); nonce=base64.b64decode(envelope["nonce"],validate=True); ciphertext=base64.b64decode(envelope["ciphertext"],validate=True)
    if len(wrapped)!=384 or len(nonce)!=12 or len(ciphertext)<16: raise Fixed("envelope")
    data_key=key.decrypt(wrapped,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=AAD))
    if len(data_key)!=32: raise Fixed("key")
    return AESGCM(data_key).decrypt(nonce,ciphertext,AAD)

class Adapter:
    postgres=True
    def __init__(self,connection): self.connection=connection
    def fetchall(self,statement,parameters=()): return self.connection.execute(statement.replace("?","%s"),tuple(parameters)).fetchall()

def one(connection,statement,parameters,code):
    rows=connection.execute(statement,parameters).fetchall()
    if len(rows)!=1: raise Fixed(code)
    return dict(rows[0])

def owner_gate(connection,migrations):
    session=one(connection,"""
WITH executor AS (SELECT oid,rolsuper,rolcanlogin FROM pg_roles WHERE rolname=session_user),
managed AS (SELECT oid FROM pg_roles WHERE rolname=%s)
SELECT
  session_user=%s AS account_exact,
  session_user=current_user AND current_user=current_role AS identity_unchanged,
  current_setting('default_transaction_read_only')='on' AS default_read_only,
  current_setting('transaction_read_only')='on' AS transaction_read_only,
  current_setting('transaction_isolation')='repeatable read' AS isolation_exact,
  current_setting('server_version_num')::integer>=160000 AND current_setting('server_version_num')::integer<170000 AS server_version_exact,
  COALESCE((SELECT NOT rolsuper FROM executor),FALSE) AS executor_non_superuser,
  COALESCE((SELECT rolcanlogin FROM executor),FALSE) AS executor_can_login,
  COALESCE((SELECT pg_has_role(session_user,oid,'MEMBER') FROM managed),FALSE) AS managed_membership,
  pg_has_role(session_user,%s,'SET') AS owner_set_capable,
  COALESCE((SELECT pg_has_role(oid,%s,'SET') FROM managed),FALSE) AS managed_owner_set_capable,
  (SELECT COUNT(*)::integer FROM pg_auth_members m WHERE m.member=(SELECT oid FROM executor) AND m.roleid=(SELECT oid FROM managed)) AS direct_managed_membership_count,
  (SELECT COUNT(*)::integer FROM pg_auth_members m WHERE m.member=(SELECT oid FROM executor)) AS direct_membership_count
FROM executor
""",(MANAGED,ACCOUNT,OWNER,OWNER),"session")
    expected_session={"account_exact":True,"identity_unchanged":True,"default_read_only":True,"transaction_read_only":True,"isolation_exact":True,"server_version_exact":True,"executor_non_superuser":True,"executor_can_login":True,"managed_membership":True,"owner_set_capable":True,"managed_owner_set_capable":True,"direct_managed_membership_count":1,"direct_membership_count":1}
    if session!=expected_session: raise Fixed("session")
    connection.execute("SET LOCAL ROLE noteai_admin")
    owner=one(connection,"""
WITH owner_role AS (SELECT oid,rolsuper FROM pg_roles WHERE rolname=%s),
base_tables AS (
  SELECT c.relname::text AS name,c.relowner,c.relrowsecurity,c.relforcerowsecurity
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='public' AND c.relkind IN ('r','p')
)
SELECT
  session_user=%s AS account_exact,
  current_user=%s AND current_role=%s AS owner_activated,
  current_setting('default_transaction_read_only')='on' AS default_read_only,
  current_setting('transaction_read_only')='on' AS transaction_read_only,
  current_setting('transaction_isolation')='repeatable read' AS isolation_exact,
  (SELECT COUNT(*) FROM owner_role)=1 AS owner_exists,
  COALESCE((SELECT NOT rolsuper FROM owner_role),FALSE) AS owner_non_superuser,
  has_schema_privilege(current_user,'public','USAGE') AS schema_usage,
  COALESCE(array_agg(name ORDER BY name),ARRAY[]::text[]) AS table_names,
  COUNT(*)::integer AS table_count,
  COUNT(*) FILTER (WHERE relowner<>(SELECT oid FROM owner_role))::integer AS owner_mismatch_count,
  COALESCE(array_agg(name ORDER BY name) FILTER (WHERE relrowsecurity),ARRAY[]::text[]) AS rls_names,
  COUNT(*) FILTER (WHERE relrowsecurity)::integer AS rls_count,
  COUNT(*) FILTER (WHERE relforcerowsecurity)::integer AS force_rls_count
FROM base_tables
""",(OWNER,ACCOUNT,OWNER,OWNER),"owner")
    fixed={key:owner[key] for key in ("account_exact","owner_activated","default_read_only","transaction_read_only","isolation_exact","owner_exists","owner_non_superuser","schema_usage")}
    if fixed!={key:True for key in fixed}: raise Fixed("owner")
    if tuple(owner["table_names"])!=TABLES or owner["table_count"]!=len(TABLES) or owner["owner_mismatch_count"]!=0: raise Fixed("tables")
    if tuple(owner["rls_names"])!=RLS or owner["rls_count"]!=len(RLS) or owner["force_rls_count"]!=0: raise Fixed("rls")
    connection.execute("SET LOCAL row_security=off")
    guard=one(connection,"SELECT current_user=%s AND current_role=%s AS owner_activated,current_setting('default_transaction_read_only')='on' AS default_read_only,current_setting('transaction_read_only')='on' AS transaction_read_only,current_setting('transaction_isolation')='repeatable read' AS isolation_exact,current_setting('row_security')='off' AS row_security_off",(OWNER,OWNER),"rls")
    if guard!={"owner_activated":True,"default_read_only":True,"transaction_read_only":True,"isolation_exact":True,"row_security_off":True}: raise Fixed("rls")
    ledger=[dict(row) for row in connection.execute("SELECT version,sha256 FROM schema_migrations ORDER BY version").fetchall()]
    if ledger!=migrations: raise Fixed("migrations")

def runtime_modules():
    os.environ["DATABASE_URL"]=IMPORT_GUARD_DATABASE_URL
    try:
        sys.path.insert(0,"/app/model")
        import private_storage, storage_recovery_evidence as recovery, psycopg
        from psycopg.rows import dict_row
        from psycopg.pq import TransactionStatus
    finally:
        os.environ.pop("DATABASE_URL",None)
    return private_storage,recovery,psycopg,dict_row,TransactionStatus

def write_once(body):
    fd=os.open("/output/source-manifest.json",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        offset=0
        while offset<len(body):
            written=os.write(fd,body[offset:])
            if written<=0: raise Fixed("write")
            offset+=written
        os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
    finally: os.close(fd)

def main():
    capabilities()
    if os.listdir("/output"): raise Fixed("output")
    plaintext=decrypt()
    try: payload=json.loads(plaintext)
    finally: del plaintext
    if not isinstance(payload,dict) or set(payload)!={"control_database_url"}: raise Fixed("payload")
    control_url=payload["control_database_url"]
    control,cquery=parsed(control_url,ACCOUNT)
    api=env_file("/input/api.env")
    if "DATABASE_URL" not in api: raise Fixed("api_env")
    api_url=api.pop("DATABASE_URL"); api.clear()
    topology,tquery=parsed(api_url,"noteai_app"); del api_url
    if (control.scheme,str(control.hostname).lower(),control.port or 5432,control.path,cquery)!=(topology.scheme,str(topology.hostname).lower(),topology.port or 5432,topology.path,tquery): raise Fixed("topology")
    storage=env_file("/input/private-storage.env"); region=storage.get("NOTEAI_OSS_REGION","")
    if set(storage)!=STORAGE or storage.get("NOTEAI_PRIVATE_STORAGE_BACKEND")!="aliyun_oss" or not re.fullmatch(r"cn-[a-z0-9-]{2,32}",region) or storage.get("NOTEAI_OSS_ENDPOINT")!="https://oss-{}-internal.aliyuncs.com".format(region) or storage.get("NOTEAI_OSS_RAM_ROLE")!=ROLE or not storage.get("NOTEAI_OSS_PRIVATE_BUCKET") or not storage.get("NOTEAI_PRIVATE_STORAGE_KEY_EPOCH") or storage.get("NOTEAI_OSS_KEY_PREFIX","").strip("/")!="noteai-private": raise Fixed("storage")
    for name in list(os.environ):
        if name.startswith(("ALIBABA_CLOUD_","ALICLOUD_","OSS_","PG")) or name=="DATABASE_URL": os.environ.pop(name,None)
    os.environ.update(storage)
    private_storage,recovery,psycopg,dict_row,TransactionStatus=runtime_modules()
    if not private_storage.configure_from_environment(): raise Fixed("backend")
    migrations=[]
    for path in sorted(Path("/app/model/migrations/postgres").glob("*.sql")):
        migrations.append({"version":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    if len(migrations)!=17 or migrations[-1]["version"]!="0017_durable_ai_postgres_wakeup.sql": raise Fixed("migrations")
    connection=None; active=False; manifest=None
    try:
        connection=psycopg.connect(control_url,row_factory=dict_row,connect_timeout=10,options="-c timezone=UTC -c default_transaction_read_only=on",autocommit=True)
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"); active=True
        if connection.info.transaction_status != TransactionStatus.INTRANS: raise Fixed("session")
        connection.execute("SET LOCAL statement_timeout='600s'"); connection.execute("SET LOCAL lock_timeout='5s'"); connection.execute("SET LOCAL idle_in_transaction_session_timeout='900s'")
        owner_gate(connection,migrations)
        manifest=recovery.capture_manifest(release_commit=RELEASE,storage=Adapter(connection),backend=private_storage.get_object_backend(),require_objects=True,max_rows_per_table=1000000,max_objects=100000)
        recovery.validate_manifest(manifest); connection.rollback()
        if connection.info.transaction_status != TransactionStatus.IDLE: raise Fixed("rollback")
        active=False
    finally:
        if connection is not None:
            if active:
                try: connection.rollback()
                except BaseException: pass
            try: connection.close()
            except BaseException: pass
        del control_url
    if manifest["database"]["migrations"]!=migrations: raise Fixed("migrations")
    if manifest["database"]["engine"]!="postgresql" or manifest["database"]["table_count"]!=len(manifest["database"]["tables"]): raise Fixed("database")
    if not all(manifest["database"]["references"][name]["present"] is True for name in ("ai_payload_refs","private_media_refs")): raise Fixed("references")
    if any(manifest["privacy"].values()) or manifest["objects"].get("not_captured") is True or manifest["objects"]["content_included"] is not False or manifest["objects"]["object_keys_included"] is not False: raise Fixed("privacy")
    body=(json.dumps(manifest,ensure_ascii=True,sort_keys=True,separators=(",",":"))+"\n").encode("ascii")
    if not 1<=len(body)<=1048576: raise Fixed("size")
    write_once(body)
    result={"status":"SOURCE_MANIFEST_CAPTURED","manifest_bytes":len(body),"manifest_file_sha256":hashlib.sha256(body).hexdigest(),"manifest_sha256":manifest["manifest_sha256"],"table_count":manifest["database"]["table_count"],"migration_count":17,"object_count":manifest["objects"]["object_count"],"object_size_bytes":manifest["objects"]["size_bytes"],"database_connection_count":1,"database_transaction_count":1,"database_write_count":0,"transaction_terminal":"ROLLBACK","object_write_count":0,"row_values_emitted":0,"object_keys_emitted":0,"object_contents_read":0,"secret_values_emitted":0,"postgresql_major_version":16,"account_exact":True,"topology_exact":True,"account_delete_required":True,"executor_native_superuser":False,"managed_owner_activation_count":1,"owner_table_contract_exact":True,"rls_contract_exact":True,"rls_table_count":len(RLS),"force_rls_table_count":0,"row_security_off":True,"persistent_permission_mutation_count":0,"automatic_retry_allowed":False}
    print(json.dumps(result,sort_keys=True,separators=(",",":")),flush=True)

try: main()
except BaseException as exc:
    code=str(exc) if isinstance(exc,Fixed) and str(exc) in FIXED_CODES else type(exc).__name__
    print(json.dumps({"status":"SOURCE_MANIFEST_FAILED","code":code,"automatic_retry_allowed":False},sort_keys=True,separators=(",",":")),file=sys.stderr,flush=True)
    raise SystemExit(2)
PY
chmod 0600 "$DRIVER_PATH"

[ "$(systemctl is-active docker)" = active ] && [ "$(systemctl is-enabled docker)" = enabled ] || fail docker_service
/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default version >/dev/null 2>&1 || fail docker_version
containers="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default ps -a --format '{{.Names}}|{{.State}}' | sort)" || fail containers
[ "$containers" = $'noteai-admin-c|running\nnoteai-api-c|running' ] || fail containers
[ -z "$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" ] || fail task_container
image_row="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default image inspect "$IMAGE_REF" --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{index .Config.Labels "org.opencontainers.image.revision"}}')" || fail image
[ "$image_row" = 'sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95|linux|amd64|cad5ce35664f617c6e19f90a6159285ddf975594' ] || fail image
fingerprint="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect noteai-api-c noteai-admin-c --format '{{.Id}}|{{.State.Status}}|{{.State.StartedAt}}|{{.RestartCount}}|{{.Image}}' | sort | sha256sum | awk '{print $1}')" || fail fingerprint
[ "$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = 0 ] || fail db_socket

phase='database_read_only_capture'; container_attempted=1; database_attempted=1
set +e
/usr/bin/timeout --foreground --signal=TERM --kill-after=20s 1200s /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default run --rm \
  --name "$CONTAINER_NAME" --label "$CONTAINER_LABEL" --pull never --network host --workdir /tmp --user 0:0 --read-only \
  --cap-drop ALL --cap-add DAC_READ_SEARCH --security-opt no-new-privileges:true --memory 768m --cpus 0.75 --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777 \
  --mount type=bind,src="$CONTROL_ROOT",dst=/input/control,readonly --mount type=bind,src="$API_ENV",dst=/input/api.env,readonly \
  --mount type=bind,src="$STORAGE_ENV",dst=/input/private-storage.env,readonly --mount type=bind,src="$DRIVER_PATH",dst=/task/driver.py,readonly \
  --mount type=bind,src="$OUTPUT_ROOT",dst=/output --entrypoint /usr/local/bin/python3.11 "$IMAGE_REF" -I -B /task/driver.py >"$HELPER_OUT" 2>"$HELPER_ERR"
helper_rc=$?; set -e
[ "$helper_rc" -eq 0 ] || exit 4
[ -z "$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" ] || exit 4
container_attempted=0
[ "$(stat -c '%u|%g|%a|%h|%s' "$HELPER_ERR")" = '0|0|600|1|0' ] || exit 4
[ "$(stat -c '%u|%g|%a|%h' "$HELPER_OUT")" = '0|0|600|1' ] && [ "$(stat -c '%s' "$HELPER_OUT")" -le 4096 ] || exit 4

validated="$(python3 -I -B - "$HELPER_OUT" "$OUTPUT_ROOT/source-manifest.json" <<'PY'
import hashlib,json,os,stat,sys
def read(path,maximum):
    row=os.lstat(path)
    if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid!=0 or row.st_gid!=0 or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not 1<=row.st_size<=maximum: raise SystemExit(2)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: body=os.read(fd,maximum+1); current=os.fstat(fd)
    finally: os.close(fd)
    if len(body)!=row.st_size or (current.st_dev,current.st_ino)!=(row.st_dev,row.st_ino): raise SystemExit(2)
    return body
summary=json.loads(read(sys.argv[1],4096)); body=read(sys.argv[2],1048576); manifest=json.loads(body)
keys={"account_delete_required","account_exact","automatic_retry_allowed","database_connection_count","database_transaction_count","database_write_count","executor_native_superuser","force_rls_table_count","managed_owner_activation_count","manifest_bytes","manifest_file_sha256","manifest_sha256","migration_count","object_contents_read","object_count","object_keys_emitted","object_size_bytes","object_write_count","owner_table_contract_exact","persistent_permission_mutation_count","postgresql_major_version","rls_contract_exact","rls_table_count","row_security_off","row_values_emitted","secret_values_emitted","status","table_count","topology_exact","transaction_terminal"}
if set(summary)!=keys or summary["status"]!="SOURCE_MANIFEST_CAPTURED" or not summary["account_exact"] or not summary["topology_exact"] or not summary["account_delete_required"] or summary["automatic_retry_allowed"] is not False: raise SystemExit(2)
if (summary["database_connection_count"],summary["database_transaction_count"],summary["database_write_count"],summary["transaction_terminal"],summary["object_write_count"],summary["row_values_emitted"],summary["object_keys_emitted"],summary["object_contents_read"],summary["secret_values_emitted"],summary["postgresql_major_version"],summary["migration_count"],summary["table_count"],summary["executor_native_superuser"],summary["managed_owner_activation_count"],summary["owner_table_contract_exact"],summary["rls_contract_exact"],summary["rls_table_count"],summary["force_rls_table_count"],summary["row_security_off"],summary["persistent_permission_mutation_count"])!=(1,1,0,"ROLLBACK",0,0,0,0,0,16,17,56,False,1,True,True,19,0,True,0): raise SystemExit(2)
file_sha=hashlib.sha256(body).hexdigest(); unsigned=dict(manifest); supplied=unsigned.pop("manifest_sha256",None); internal=hashlib.sha256(json.dumps(unsigned,ensure_ascii=True,sort_keys=True,separators=(",",":")).encode()).hexdigest()
if summary["manifest_bytes"]!=len(body) or summary["manifest_file_sha256"]!=file_sha or supplied!=internal or summary["manifest_sha256"]!=supplied: raise SystemExit(2)
privacy=manifest.get("privacy",{}); database=manifest.get("database",{}); objects=manifest.get("objects",{})
if manifest.get("contract_version")!="noteai-recovery-evidence-v1" or manifest.get("release_commit")!="cad5ce35664f617c6e19f90a6159285ddf975594" or any(privacy.values()): raise SystemExit(2)
if database.get("engine")!="postgresql" or database.get("table_count")!=56 or database.get("table_count")!=len(database.get("tables",{})) or len(database.get("migrations",[]))!=17: raise SystemExit(2)
if objects.get("not_captured") is True or objects.get("content_included") is not False or objects.get("object_keys_included") is not False: raise SystemExit(2)
print("OK|{}|{}|{}|{}|{}|{}".format(len(body),file_sha,supplied,database["table_count"],objects["object_count"],objects["size_bytes"]))
PY
)" || exit 4
IFS='|' read -r tag manifest_bytes manifest_file_sha manifest_sha table_count object_count object_size <<<"$validated"; [ "$tag" = OK ] || exit 4

phase='manifest_promotion'
[ "$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n')" = 'source-manifest.json' ] || exit 4
[ ! -e "$FINAL_ROOT" ] && [ ! -L "$FINAL_ROOT" ] || exit 4
mv "$OUTPUT_ROOT" "$FINAL_ROOT" || exit 4; manifest_committed=1
[ "$(stat -c '%F|%u|%g|%a' "$FINAL_ROOT")" = 'directory|0|0|700' ] || exit 4
[ "$(stat -c '%F|%u|%g|%a|%h|%s' "$FINAL_MANIFEST")" = "regular file|0|0|600|1|$manifest_bytes" ] || exit 4
[ "$(sha256sum "$FINAL_MANIFEST" | awk '{print $1}')" = "$manifest_file_sha" ] || exit 4
[ "$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect noteai-api-c noteai-admin-c --format '{{.Id}}|{{.State.Status}}|{{.State.StartedAt}}|{{.RestartCount}}|{{.Image}}' | sort | sha256sum | awk '{print $1}')" = "$fingerprint" ] || exit 4
[ "$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = 0 ] || exit 4
cleanup_task || exit 4

phase='complete'
printf '{"NOTEAI_ITEM26_SOURCE_MANIFEST":"PASS","incident_class":"CONNECTED_KNOWN_READ_ONLY","transaction":"REPEATABLE_READ_READ_ONLY_ROLLBACK","manifest_bytes":%s,"manifest_file_sha256":"%s","manifest_sha256":"%s","postgresql_major_version":16,"table_count":%s,"migration_count":17,"object_count":%s,"object_size_bytes":%s,"database_connection_count":1,"database_transaction_count":1,"database_write_count":0,"object_write_count":0,"row_values_emitted":0,"object_keys_emitted":0,"object_contents_read":0,"secret_values_emitted":0,"executor_native_superuser":false,"managed_owner_activation_count":1,"owner_table_contract_exact":true,"owner_mismatch_count":0,"rls_contract_exact":true,"rls_table_count":19,"force_rls_table_count":0,"row_security_off":true,"persistent_permission_mutation_count":0,"runtime_container_start_count":1,"container_residue_count":0,"task_root_residue_count":0,"source_manifest_retained":true,"temporary_account_delete_required":true,"provider_control_plane_mutation_count":0,"registry_call_count":0,"automatic_retry_allowed":false}\n' "$manifest_bytes" "$manifest_file_sha" "$manifest_sha" "$table_count" "$object_count" "$object_size"
completed=1; trap - EXIT
