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

readonly MODE='@@MODE@@'
readonly API_C_IDENTITY_SHA256='@@API_C_IDENTITY_SHA256@@'
readonly RECIPIENT_PUBLIC_KEY_SHA256='@@RECIPIENT_PUBLIC_KEY_SHA256@@'
readonly RECIPIENT_PUBLIC_KEY_B64='@@RECIPIENT_PUBLIC_KEY_B64@@'
readonly SOURCE_CONTROL_ROOT='/run/noteai-item26-source-account-v2'
readonly SOURCE_PRIVATE_KEY="$SOURCE_CONTROL_ROOT/control-private.pem"
readonly SOURCE_PUBLIC_KEY="$SOURCE_CONTROL_ROOT/control-public.pem"
readonly SOURCE_ENVELOPE="$SOURCE_CONTROL_ROOT/control-database-url.enc"
readonly SOURCE_PUBLIC_KEY_SHA256='dc8f8283248dd232030bb63d19f669ccdaad89faa87dbdffb7b5eb5aae83969a'
readonly SOURCE_ENVELOPE_BYTES=894
readonly SOURCE_ENVELOPE_SHA256='2c522a13b236301c5276088dd6ae83cabb5ac9c6a45923385831ec582d81e90a'
readonly PERSISTENT_PARENT='/var/lib/noteai'
readonly PERSISTENT_ROOT="$PERSISTENT_PARENT/item26-restored-password-rewrap-v1"
readonly ATTEMPT_FILE="$PERSISTENT_ROOT/attempted-v1.json"
readonly RESULT_FILE="$PERSISTENT_ROOT/password-rewrap-result-v1.json"
readonly TASK_ROOT="$PERSISTENT_ROOT/task-v1"
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly RECIPIENT_PUBLIC_KEY="$TASK_ROOT/recipient-public.pem"
readonly DRIVER_PATH="$TASK_ROOT/driver.py"
readonly HELPER_OUT="$TASK_ROOT/helper.stdout"
readonly HELPER_ERR="$TASK_ROOT/helper.stderr"
readonly CIDFILE="$TASK_ROOT/container.cid"
readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly RELEASE_COMMIT='cad5ce35664f617c6e19f90a6159285ddf975594'
readonly CONTAINER_NAME='noteai-item26-password-rewrap-v1'
readonly CONTAINER_LABEL='com.noteai.task=PROD-FIRST-LAUNCH-PITR-RESTORE-001-password-rewrap-v1'

phase='preflight'
persistent_created=0
attempt_committed=0
result_committed=0
task_created=0
container_attempted=0
force_unknown=0
completed=0
task_identity=''

emit_fixed() {
  trap - EXIT
  local state="$1" current_phase="$2" incident readback code
  if [ "$state" = 'FAIL' ]; then
    incident='PRE_ATTEMPT'
    readback='false'
    code=3
  else
    incident='ATTEMPTED_UNKNOWN'
    readback='true'
    code=4
  fi
  printf '{"NOTEAI_ITEM26_PASSWORD_REWRAP":"%s","automatic_retry_allowed":false,"database_connection_count":0,"database_write_count":0,"incident_class":"%s","new_rewrap_allowed":false,"phase":"%s","provider_control_plane_mutation_count":0,"readback_required":%s,"same_invocation_replay_allowed":false,"secret_values_emitted":0}\n' \
    "$state" "$incident" "$current_phase" "$readback" >&2
  exit "$code"
}

metadata_identity() {
  python3 -I -B - "$API_C_IDENTITY_SHA256" <<'PY'
import hashlib,json,re,sys,urllib.request
expected=sys.argv[1]
if re.fullmatch(r"[0-9a-f]{64}",expected) is None: raise SystemExit(2)
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
if not re.fullmatch(r"i-[a-z0-9]+",values[0]) or len(roles)!=1 or re.fullmatch(r"[A-Za-z0-9._-]{1,64}",roles[0]) is None: raise SystemExit(2)
canonical=json.dumps({"instance_id":values[0],"ram_role":roles[0]},ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("ascii")
if hashlib.sha256(canonical).hexdigest()!=expected: raise SystemExit(2)
print("API_C_IDENTITY_EXACT")
PY
}

fsync_directory() {
  python3 -I -B - "$1" <<'PY'
import os,sys
fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: os.fsync(fd)
finally: os.close(fd)
PY
}

read_full_cid() {
  python3 -I -B - "$CIDFILE" <<'PY'
import os,re,stat,sys
path=sys.argv[1]; row=os.lstat(path)
if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or row.st_size not in (64,65): raise SystemExit(2)
fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
try: body=os.read(fd,66); opened=os.fstat(fd)
finally: os.close(fd)
if (opened.st_dev,opened.st_ino,opened.st_mode,opened.st_uid,opened.st_gid,opened.st_nlink,opened.st_size)!=(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size): raise SystemExit(2)
value=body.decode("ascii").strip()
if len(value)!=64 or re.fullmatch(r"[0-9a-f]{64}",value) is None: raise SystemExit(2)
print(value)
PY
}

cleanup_container() {
  [ "$task_created" -eq 1 ] && [ -n "$task_identity" ] || return 0
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

cleanup_task() {
  [ "$task_created" -eq 1 ] || return 0
  python3 -I -B - "$PERSISTENT_ROOT" "$TASK_ROOT" "$task_identity" <<'PY' || return 1
import os,re,stat,sys
base,task,identity=sys.argv[1:]
basefd=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
    name=os.path.basename(task); row=os.stat(name,dir_fd=basefd,follow_symlinks=False)
    if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o700 or "{}:{}".format(row.st_dev,row.st_ino)!=identity: raise SystemExit(2)
    taskfd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=basefd)
    try:
        names=set(os.listdir(taskfd)); allowed={"docker-config","recipient-public.pem","driver.py","helper.stdout","helper.stderr","container.cid"}
        if names-allowed: raise SystemExit(2)
        regular=names-{"docker-config"}
        for child in regular:
            item=os.stat(child,dir_fd=taskfd,follow_symlinks=False)
            if not stat.S_ISREG(item.st_mode) or stat.S_ISLNK(item.st_mode) or item.st_uid or item.st_gid or stat.S_IMODE(item.st_mode)!=0o600 or item.st_nlink!=1: raise SystemExit(2)
            if child=="recipient-public.pem" and item.st_size!=625: raise SystemExit(2)
            if child=="container.cid":
                fd=os.open(child,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=taskfd)
                try: value=os.read(fd,66).decode("ascii").strip()
                finally: os.close(fd)
                if len(value)!=64 or re.fullmatch(r"[0-9a-f]{64}",value) is None: raise SystemExit(2)
        if "docker-config" in names:
            config=os.stat("docker-config",dir_fd=taskfd,follow_symlinks=False)
            if not stat.S_ISDIR(config.st_mode) or stat.S_ISLNK(config.st_mode) or config.st_uid or config.st_gid or stat.S_IMODE(config.st_mode)!=0o700: raise SystemExit(2)
            configfd=os.open("docker-config",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=taskfd)
            try:
                if set(os.listdir(configfd))!={"config.json"}: raise SystemExit(2)
                item=os.stat("config.json",dir_fd=configfd,follow_symlinks=False)
                if not stat.S_ISREG(item.st_mode) or stat.S_ISLNK(item.st_mode) or item.st_uid or item.st_gid or stat.S_IMODE(item.st_mode)!=0o600 or item.st_nlink!=1 or item.st_size!=2: raise SystemExit(2)
                fd=os.open("config.json",os.O_RDONLY|os.O_NOFOLLOW,dir_fd=configfd)
                try: body=os.read(fd,3)
                finally: os.close(fd)
                if body!=b"{}": raise SystemExit(2)
            finally: os.close(configfd)
        for child in regular: os.unlink(child,dir_fd=taskfd)
        if "docker-config" in names:
            configfd=os.open("docker-config",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=taskfd)
            try: os.unlink("config.json",dir_fd=configfd)
            finally: os.close(configfd)
            os.rmdir("docker-config",dir_fd=taskfd)
        os.fsync(taskfd)
    finally: os.close(taskfd)
    os.rmdir(name,dir_fd=basefd); os.fsync(basefd)
finally: os.close(basefd)
PY
  task_created=0
}

on_exit() {
  local rc=$? cleanup_ok=1 state='FAIL'
  trap - EXIT
  if [ "$completed" -eq 1 ] && [ "$rc" -eq 0 ]; then return 0; fi
  if [ "$task_created" -eq 1 ]; then
    cleanup_container >/dev/null 2>&1 || cleanup_ok=0
    [ "$cleanup_ok" -eq 1 ] && cleanup_task >/dev/null 2>&1 || cleanup_ok=0
  fi
  if [ "$force_unknown" -eq 1 ] || [ "$persistent_created" -eq 1 ] || [ "$attempt_committed" -eq 1 ] || [ "$result_committed" -eq 1 ] || [ "$cleanup_ok" -eq 0 ]; then state='UNKNOWN'; fi
  emit_fixed "$state" "$phase"
}
trap on_exit EXIT

common_preflight() {
  phase='root'
  [ "$(id -u)" = '0' ] && [ "$(id -g)" = '0' ] || return 1
  phase='binding'
  [ "$MODE" = 'CREATE' ] || [ "$MODE" = 'READBACK' ] || return 1
  [[ "$API_C_IDENTITY_SHA256" =~ ^[0-9a-f]{64}$ ]] && [[ "$RECIPIENT_PUBLIC_KEY_SHA256" =~ ^[0-9a-f]{64}$ ]] && [ "$RECIPIENT_PUBLIC_KEY_SHA256" != "$SOURCE_PUBLIC_KEY_SHA256" ] || return 1
  phase='tool'
  for tool in python3 stat find sort openssl sha256sum awk ss docker systemctl timeout mkdir chmod wc tr cat env; do command -v "$tool" >/dev/null 2>&1 || return 1; done
  [ -x /usr/bin/docker ] && [ -x /usr/bin/timeout ] && [ -x /usr/bin/openssl ] && [ -x /usr/bin/env ] || return 1
  phase='persistent_parent'
  [ -d "$PERSISTENT_PARENT" ] && [ ! -L "$PERSISTENT_PARENT" ] && [ "$(stat -c '%F|%u|%g|%a' "$PERSISTENT_PARENT")" = 'directory|0|0|700' ] || return 1
  phase='identity'
  [ "$(metadata_identity 2>/dev/null)" = 'API_C_IDENTITY_EXACT' ] || return 1
}

source_control_preflight() {
  phase='source_control_root'
  [ -d "$SOURCE_CONTROL_ROOT" ] && [ ! -L "$SOURCE_CONTROL_ROOT" ] && [ "$(stat -c '%F|%u|%g|%a' "$SOURCE_CONTROL_ROOT")" = 'directory|0|0|700' ] || return 1
  [ "$(find "$SOURCE_CONTROL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'control-database-url.enc\ncontrol-private.pem\ncontrol-public.pem' ] || return 1
  phase='source_control_metadata'
  [ "$(stat -c '%F|%u|%g|%a|%h|%s' "$SOURCE_ENVELOPE")" = "regular file|0|0|600|1|$SOURCE_ENVELOPE_BYTES" ] || return 1
  [ "$(stat -c '%F|%u|%g|%a|%h|%s' "$SOURCE_PUBLIC_KEY")" = 'regular file|0|0|600|1|625' ] || return 1
  [ "$(stat -c '%F|%u|%g|%a|%h' "$SOURCE_PRIVATE_KEY")" = 'regular file|0|0|600|1' ] || return 1
  [ "$(sha256sum "$SOURCE_ENVELOPE" | awk '{print $1}')" = "$SOURCE_ENVELOPE_SHA256" ] || return 1
  phase='source_control_key_pair'
  local public_sha private_sha
  public_sha="$(/usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl pkey -pubin -in "$SOURCE_PUBLIC_KEY" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || return 1
  private_sha="$(/usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl pkey -in "$SOURCE_PRIVATE_KEY" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || return 1
  [ "$public_sha" = "$SOURCE_PUBLIC_KEY_SHA256" ] && [ "$private_sha" = "$public_sha" ] || return 1
  phase='source_envelope_contract'
  python3 -I -B - "$SOURCE_ENVELOPE" "$SOURCE_ENVELOPE_BYTES" "$SOURCE_ENVELOPE_SHA256" <<'PY' 2>/dev/null
import base64,hashlib,json,os,stat,sys
path,size_raw,digest=sys.argv[1:]; size=int(size_raw)
def no_duplicates(pairs):
    value={}
    for key,row in pairs:
        if key in value: raise SystemExit(2)
        value[key]=row
    return value
before=os.lstat(path)
fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
try: body=os.read(fd,size+1); opened=os.fstat(fd)
finally: os.close(fd)
after=os.lstat(path)
stable=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size,row.st_mtime_ns)
if len(body)!=size or hashlib.sha256(body).hexdigest()!=digest or stable(before)!=stable(opened) or stable(before)!=stable(after): raise SystemExit(2)
row=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
canonical=json.dumps(row,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("ascii")
if canonical!=body or set(row)!={"schema_version","algorithm","wrapped_key","nonce","ciphertext"} or type(row["schema_version"]) is not int or row["schema_version"]!=1 or row["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM": raise SystemExit(2)
wrapped=base64.b64decode(row["wrapped_key"],validate=True); nonce=base64.b64decode(row["nonce"],validate=True); ciphertext=base64.b64decode(row["ciphertext"],validate=True)
if len(wrapped)!=384 or len(nonce)!=12 or len(ciphertext)<16: raise SystemExit(2)
PY
}

emit_readback() {
  python3 -I -B - "$PERSISTENT_PARENT" "$PERSISTENT_ROOT" "$ATTEMPT_FILE" "$RESULT_FILE" "$API_C_IDENTITY_SHA256" "$RECIPIENT_PUBLIC_KEY_SHA256" "$SOURCE_ENVELOPE_SHA256" <<'PY'
import base64,json,os,re,stat,sys
parent,root,attempt_path,result_path,identity,recipient,source_sha=sys.argv[1:]
def no_duplicates(pairs):
    value={}
    for key,row in pairs:
        if key in value: raise SystemExit(2)
        value[key]=row
    return value
def canonical(value): return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")
def read(path,low,high):
    before=os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_uid or before.st_gid or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not low<=before.st_size<=high: raise SystemExit(2)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: body=os.read(fd,high+1); opened=os.fstat(fd)
    finally: os.close(fd)
    after=os.lstat(path)
    stable=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size)
    if len(body)!=before.st_size or stable(before)!=stable(opened) or stable(before)!=stable(after): raise SystemExit(2)
    return body
for path in (parent,root):
    row=os.lstat(path)
    if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o700: raise SystemExit(2)
if set(os.listdir(root))!={"attempted-v1.json","password-rewrap-result-v1.json"}: raise SystemExit(2)
attempt_body=read(attempt_path,1,4096)
attempt=json.loads(attempt_body.decode("ascii"),object_pairs_hook=no_duplicates)
expected_attempt={"NOTEAI_ITEM26_PASSWORD_REWRAP_ATTEMPT":"COMMITTED","api_c_identity_sha256":identity,"automatic_retry_allowed":False,"recipient_public_key_sha256":recipient,"same_invocation_replay_allowed":False,"schema_version":1,"source_envelope_sha256":source_sha}
if canonical(attempt)!=attempt_body or set(attempt)!=set(expected_attempt) or attempt["NOTEAI_ITEM26_PASSWORD_REWRAP_ATTEMPT"]!="COMMITTED" or attempt["api_c_identity_sha256"]!=identity or attempt["recipient_public_key_sha256"]!=recipient or attempt["source_envelope_sha256"]!=source_sha: raise SystemExit(2)
if type(attempt["schema_version"]) is not int or attempt["schema_version"]!=1 or type(attempt["automatic_retry_allowed"]) is not bool or attempt["automatic_retry_allowed"] is not False or type(attempt["same_invocation_replay_allowed"]) is not bool or attempt["same_invocation_replay_allowed"] is not False: raise SystemExit(2)
body=read(result_path,700,1200); result=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
keys={"account_exact","automatic_retry_allowed","database_connection_count","database_write_count","password_policy_exact","provider_control_plane_mutation_count","recipient_public_key_sha256","schema_version","secret_values_emitted","status","wrapped_password"}
if canonical(result)!=body or set(result)!=keys or type(result["schema_version"]) is not int or result["schema_version"]!=1 or result["status"]!="PASSWORD_REWRAPPED" or result["recipient_public_key_sha256"]!=recipient: raise SystemExit(2)
for key in ("account_exact","password_policy_exact"):
    if type(result[key]) is not bool or result[key] is not True: raise SystemExit(2)
if type(result["automatic_retry_allowed"]) is not bool or result["automatic_retry_allowed"] is not False: raise SystemExit(2)
for key in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted"):
    if type(result[key]) is not int or result[key]!=0: raise SystemExit(2)
try: wrapped=base64.b64decode(result["wrapped_password"].encode("ascii"),validate=True)
except BaseException: raise SystemExit(2)
if len(wrapped)!=384: raise SystemExit(2)
if os.write(1,body)!=len(body): raise SystemExit(2)
PY
}

readback() {
  phase='readback_absent'
  if [ ! -e "$PERSISTENT_ROOT" ] && [ ! -L "$PERSISTENT_ROOT" ]; then return 1; fi
  force_unknown=1
  phase='readback_contract'
  emit_readback || return 1
  completed=1
  trap - EXIT
}

create() {
  phase='preexisting_persistent_root'
  if [ -e "$PERSISTENT_ROOT" ] || [ -L "$PERSISTENT_ROOT" ]; then force_unknown=1; return 1; fi
  source_control_preflight || return 1
  phase='docker_service'
  [ "$(systemctl is-active docker)" = 'active' ] && [ "$(systemctl is-enabled docker)" = 'enabled' ] || return 1
  /usr/bin/docker --context=default version >/dev/null 2>&1 || return 1
  [ -z "$(/usr/bin/docker --context=default container ls -aq --no-trunc --filter "name=^/${CONTAINER_NAME}$")" ] || { force_unknown=1; phase='preexisting_container'; return 1; }
  phase='image'
  local image_row
  image_row="$(/usr/bin/docker --context=default image inspect "$IMAGE_REF" --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{index .Config.Labels "org.opencontainers.image.revision"}}')" || return 1
  [ "$image_row" = "$IMAGE_CONFIG|linux|amd64|$RELEASE_COMMIT" ] || return 1
  phase='db_socket_before'
  [ "$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = '0' ] || return 1

  phase='persistent_root_create'
  force_unknown=1
  mkdir -m 0700 "$PERSISTENT_ROOT" || return 1
  persistent_created=1
  fsync_directory "$PERSISTENT_PARENT" || return 1
  [ "$(stat -c '%F|%u|%g|%a' "$PERSISTENT_ROOT")" = 'directory|0|0|700' ] || return 1
  phase='attempt_commit'
  python3 -I -B - "$ATTEMPT_FILE" "$PERSISTENT_ROOT" "$API_C_IDENTITY_SHA256" "$RECIPIENT_PUBLIC_KEY_SHA256" "$SOURCE_ENVELOPE_SHA256" <<'PY' 2>/dev/null || return 1
import json,os,sys
path,root,identity,recipient,source_sha=sys.argv[1:]
value={"NOTEAI_ITEM26_PASSWORD_REWRAP_ATTEMPT":"COMMITTED","api_c_identity_sha256":identity,"automatic_retry_allowed":False,"recipient_public_key_sha256":recipient,"same_invocation_replay_allowed":False,"schema_version":1,"source_envelope_sha256":source_sha}
body=(json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
try:
    offset=0
    while offset<len(body):
        count=os.write(fd,body[offset:])
        if count<=0: raise OSError("write")
        offset+=count
    os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
finally: os.close(fd)
dirfd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: os.fsync(dirfd)
finally: os.close(dirfd)
PY
  attempt_committed=1

  phase='task_create'
  mkdir -m 0700 "$TASK_ROOT" "$DOCKER_CONFIG_ROOT" || return 1
  task_created=1
  task_identity="$(stat -c '%d:%i' "$TASK_ROOT")" || return 1
  printf '%s' '{}' >"$DOCKER_CONFIG_ROOT/config.json" || return 1
  chmod 0600 "$DOCKER_CONFIG_ROOT/config.json" || return 1
  python3 -I -B - "$RECIPIENT_PUBLIC_KEY" "$RECIPIENT_PUBLIC_KEY_B64" "$RECIPIENT_PUBLIC_KEY_SHA256" <<'PY' 2>/dev/null || return 1
import base64,hashlib,os,subprocess,sys
path,encoded,expected=sys.argv[1:]
body=base64.b64decode(encoded.encode("ascii"),validate=True)
if len(body)!=625 or not body.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not body.endswith(b"-----END PUBLIC KEY-----\n"): raise SystemExit(2)
der=subprocess.check_output(["/usr/bin/openssl","pkey","-pubin","-outform","DER"],input=body,stderr=subprocess.DEVNULL)
if hashlib.sha256(der).hexdigest()!=expected: raise SystemExit(2)
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

  cat >"$DRIVER_PATH" <<'PY' || return 1
import base64,hashlib,json,os,re,stat,sys
from urllib.parse import parse_qsl,unquote,urlsplit
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ACCOUNT="noteai_item26_source_read_20260811_v2"
SOURCE_PUBLIC_SHA256="dc8f8283248dd232030bb63d19f669ccdaad89faa87dbdffb7b5eb5aae83969a"
SOURCE_ENVELOPE_SHA256="2c522a13b236301c5276088dd6ae83cabb5ac9c6a45923385831ec582d81e90a"
RECIPIENT_PUBLIC_SHA256="@@RECIPIENT_PUBLIC_KEY_SHA256@@"
SOURCE_AAD=b"noteai-managed-secrets-v1"
REWRAP_LABEL=b"noteai-item26-password-rewrap-v1"
QUERY=frozenset({"sslmode","connect_timeout","target_session_attrs","channel_binding","keepalives","keepalives_idle","keepalives_interval","keepalives_count","tcp_user_timeout"})

class Fixed(Exception): pass
def no_duplicates(pairs):
    value={}
    for key,row in pairs:
        if key in value: raise Fixed("duplicate")
        value[key]=row
    return value
def canonical(value): return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")
def read(path,low,high):
    before=os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_uid or before.st_gid or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not low<=before.st_size<=high: raise Fixed("metadata")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: body=os.read(fd,high+1); opened=os.fstat(fd)
    finally: os.close(fd)
    after=os.lstat(path)
    stable=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size,row.st_mtime_ns)
    if len(body)!=before.st_size or stable(before)!=stable(opened) or stable(before)!=stable(after): raise Fixed("race")
    return body
def main():
    envelope_body=read("/input/control/control-database-url.enc",894,894)
    if hashlib.sha256(envelope_body).hexdigest()!=SOURCE_ENVELOPE_SHA256: raise Fixed("envelope_hash")
    envelope=json.loads(envelope_body.decode("ascii"),object_pairs_hook=no_duplicates)
    if json.dumps(envelope,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("ascii")!=envelope_body or set(envelope)!={"schema_version","algorithm","wrapped_key","nonce","ciphertext"} or type(envelope["schema_version"]) is not int or envelope["schema_version"]!=1 or envelope["algorithm"]!="RSA-OAEP-SHA256+AES-256-GCM": raise Fixed("envelope")
    source_private=serialization.load_pem_private_key(read("/input/control/control-private.pem",2000,5000),password=None)
    if not isinstance(source_private,rsa.RSAPrivateKey) or source_private.key_size!=3072 or source_private.public_key().public_numbers().e!=65537: raise Fixed("source_key")
    source_der=source_private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(source_der).hexdigest()!=SOURCE_PUBLIC_SHA256: raise Fixed("source_key_hash")
    wrapped_key=base64.b64decode(envelope["wrapped_key"],validate=True); nonce=base64.b64decode(envelope["nonce"],validate=True); ciphertext=base64.b64decode(envelope["ciphertext"],validate=True)
    if len(wrapped_key)!=384 or len(nonce)!=12 or len(ciphertext)<16: raise Fixed("envelope_shape")
    data_key=source_private.decrypt(wrapped_key,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=SOURCE_AAD))
    plaintext=AESGCM(data_key).decrypt(nonce,ciphertext,SOURCE_AAD)
    try: payload=json.loads(plaintext.decode("utf-8"),object_pairs_hook=no_duplicates)
    finally: del plaintext,data_key,wrapped_key,nonce,ciphertext,envelope,source_private
    if type(payload) is not dict or set(payload)!={"control_database_url"}: raise Fixed("payload")
    control_url=payload.pop("control_database_url"); payload.clear()
    try:
        parsed=urlsplit(control_url); pairs=parse_qsl(parsed.query,keep_blank_values=True,strict_parsing=True); password=unquote(parsed.password or "")
    except (TypeError,ValueError): raise Fixed("dsn")
    names=[name.lower() for name,_ in pairs]
    if parsed.scheme not in {"postgres","postgresql"} or unquote(parsed.username or "")!=ACCOUNT or not parsed.hostname or not 1<=(parsed.port or 5432)<=65535 or parsed.path in {"","/"} or parsed.fragment or len(names)!=len(set(names)) or set(names)-QUERY: raise Fixed("dsn")
    if len(password)!=32 or not password.isascii() or not password.isalnum() or not any(char.isupper() for char in password) or not any(char.islower() for char in password) or not any(char.isdigit() for char in password): raise Fixed("password_policy")
    recipient=serialization.load_pem_public_key(read("/input/task/recipient-public.pem",625,625))
    if not isinstance(recipient,rsa.RSAPublicKey) or recipient.key_size!=3072 or recipient.public_numbers().e!=65537: raise Fixed("recipient")
    recipient_der=recipient.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if RECIPIENT_PUBLIC_SHA256==SOURCE_PUBLIC_SHA256 or hashlib.sha256(recipient_der).hexdigest()!=RECIPIENT_PUBLIC_SHA256: raise Fixed("recipient_hash")
    wrapped_password=recipient.encrypt(password.encode("ascii"),padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=REWRAP_LABEL))
    del password,control_url,parsed,pairs,names,recipient,recipient_der
    if len(wrapped_password)!=384: raise Fixed("wrapped_password")
    result={"account_exact":True,"automatic_retry_allowed":False,"database_connection_count":0,"database_write_count":0,"password_policy_exact":True,"provider_control_plane_mutation_count":0,"recipient_public_key_sha256":RECIPIENT_PUBLIC_SHA256,"schema_version":1,"secret_values_emitted":0,"status":"PASSWORD_REWRAPPED","wrapped_password":base64.b64encode(wrapped_password).decode("ascii")}
    body=canonical(result); del wrapped_password,result
    if os.write(1,body)!=len(body): raise Fixed("output")
try:
    main()
except BaseException as exc:
    code=str(exc) if isinstance(exc,Fixed) else "unexpected"
    allowed={"duplicate","metadata","race","envelope_hash","envelope","source_key","source_key_hash","envelope_shape","payload","dsn","password_policy","recipient","recipient_hash","wrapped_password","output"}
    if code not in allowed: code="unexpected"
    body=canonical({"NOTEAI_ITEM26_PASSWORD_REWRAP_DRIVER":"FAIL","automatic_retry_allowed":False,"code":code,"same_invocation_replay_allowed":False,"secret_values_emitted":0})
    try: os.write(2,body)
    except BaseException: pass
    raise SystemExit(3)
PY
  chmod 0600 "$DRIVER_PATH" || return 1

  phase='container_execute'
  container_attempted=1
  set +e
  /usr/bin/timeout --foreground --signal=TERM --kill-after=10s 120s /usr/bin/docker --config "$DOCKER_CONFIG_ROOT" --context=default run --rm --cidfile "$CIDFILE" \
    --name "$CONTAINER_NAME" --label "$CONTAINER_LABEL" --pull never --network none --workdir /tmp --user 0:0 --read-only \
    --cap-drop ALL --security-opt no-new-privileges:true --memory 256m --cpus 0.25 --pids-limit 64 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16777216,mode=1777 \
    --mount type=bind,src="$SOURCE_CONTROL_ROOT",dst=/input/control,readonly \
    --mount type=bind,src="$TASK_ROOT",dst=/input/task,readonly \
    --mount type=bind,src="$DRIVER_PATH",dst=/task/driver.py,readonly \
    --entrypoint /usr/local/bin/python3.11 "$IMAGE_REF" -I -B /task/driver.py >"$HELPER_OUT" 2>"$HELPER_ERR"
  local helper_rc=$?
  set -e
  cleanup_container || { phase='container_cleanup'; return 1; }
  container_attempted=0
  [ "$helper_rc" -eq 0 ] || return 1
  [ "$(stat -c '%F|%u|%g|%a|%h|%s' "$HELPER_ERR")" = 'regular file|0|0|600|1|0' ] || { phase='helper_stderr'; return 1; }

  phase='result_commit'
  python3 -I -B - "$HELPER_OUT" "$RESULT_FILE" "$PERSISTENT_ROOT" "$RECIPIENT_PUBLIC_KEY_SHA256" <<'PY' 2>/dev/null || return 1
import base64,json,os,stat,sys
source,target,root,recipient=sys.argv[1:]
def no_duplicates(pairs):
    value={}
    for key,row in pairs:
        if key in value: raise SystemExit(2)
        value[key]=row
    return value
def canonical(value): return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")
before=os.lstat(source)
if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_uid or before.st_gid or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not 700<=before.st_size<=1200: raise SystemExit(2)
fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
try: body=os.read(fd,1201); opened=os.fstat(fd)
finally: os.close(fd)
after=os.lstat(source)
stable=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,row.st_nlink,row.st_size,row.st_mtime_ns)
if len(body)!=before.st_size or stable(before)!=stable(opened) or stable(before)!=stable(after): raise SystemExit(2)
result=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
keys={"account_exact","automatic_retry_allowed","database_connection_count","database_write_count","password_policy_exact","provider_control_plane_mutation_count","recipient_public_key_sha256","schema_version","secret_values_emitted","status","wrapped_password"}
if canonical(result)!=body or set(result)!=keys or type(result["schema_version"]) is not int or result["schema_version"]!=1 or result["status"]!="PASSWORD_REWRAPPED" or result["recipient_public_key_sha256"]!=recipient: raise SystemExit(2)
if type(result["account_exact"]) is not bool or result["account_exact"] is not True or type(result["password_policy_exact"]) is not bool or result["password_policy_exact"] is not True or type(result["automatic_retry_allowed"]) is not bool or result["automatic_retry_allowed"] is not False: raise SystemExit(2)
for key in ("database_connection_count","database_write_count","provider_control_plane_mutation_count","secret_values_emitted"):
    if type(result[key]) is not int or result[key]!=0: raise SystemExit(2)
if len(base64.b64decode(result["wrapped_password"].encode("ascii"),validate=True))!=384: raise SystemExit(2)
fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
try:
    offset=0
    while offset<len(body):
        count=os.write(fd,body[offset:])
        if count<=0: raise OSError("write")
        offset+=count
    os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
finally: os.close(fd)
dirfd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: os.fsync(dirfd)
finally: os.close(dirfd)
PY
  result_committed=1
  phase='task_cleanup'
  cleanup_task || return 1
  phase='db_socket_after'
  [ "$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = '0' ] || return 1
  phase='terminal_readback'
  emit_readback || return 1
  completed=1
  trap - EXIT
}

if [ "$MODE" = 'READBACK' ] || [ -e "$PERSISTENT_ROOT" ] || [ -L "$PERSISTENT_ROOT" ]; then
  force_unknown=1
fi
common_preflight || exit 1
case "$MODE" in
  CREATE) create || exit 1 ;;
  READBACK) readback || exit 1 ;;
  *) phase='mode'; exit 1 ;;
esac
