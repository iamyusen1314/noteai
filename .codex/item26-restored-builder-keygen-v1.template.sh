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
readonly CONTROL_ROOT="$BASE_ROOT/control"
readonly PRIVATE_KEY="$CONTROL_ROOT/control-private.pem"
readonly PUBLIC_KEY="$CONTROL_ROOT/control-public.pem"
readonly PUBLIC_METADATA="$BASE_ROOT/keygen-public-metadata.json"
readonly ENVELOPE="$CONTROL_ROOT/control-envelope.json"
readonly TRANSFER="$BASE_ROOT/restored-capture-transfer-v1.sh.gz"
readonly CAPTURE_TASK="$BASE_ROOT/capture-task-v1"
readonly FINAL_ROOT="$BASE_ROOT/restored-manifest-v1"
readonly ATTEMPT="$BASE_ROOT/capture-attempted-v1"
readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly RELEASE_COMMIT='cad5ce35664f617c6e19f90a6159285ddf975594'
readonly BUILDER_IDENTITY_SHA256='@@BUILDER_IDENTITY_SHA256@@'
readonly CONTAINER_NAME='noteai-item26-restored-capture-v1'

emit_fixed() {
  trap - ERR
  local state="$1" phase="$2" code="$3"
  printf '{"NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN":"%s","automatic_retry_allowed":false,"phase":"%s","private_key_value_read_count":0,"same_invocation_replay_allowed":false}\n' "$state" "$phase" >&2
  exit "$code"
}
trap 'emit_fixed UNKNOWN unexpected 4' ERR

metadata_identity() {
  python3 -I -B - "$BUILDER_IDENTITY_SHA256" <<'PY'
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
canonical=json.dumps({"instance_id":values[0],"ram_role":roles[0]},ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("ascii")
if hashlib.sha256(canonical).hexdigest()!=expected: raise SystemExit(2)
print("BUILDER_IDENTITY_EXACT")
PY
}

current_machine_preflight() {
  [ "$(metadata_identity 2>/dev/null)" = BUILDER_IDENTITY_EXACT ] || return 1
  [ "$(systemctl is-active docker)" = active ] || return 1
  [ -z "${DOCKER_CONFIG:-}" ] && [ "$(/usr/bin/docker context show)" = default ] || return 1
  if [ -e /root/.docker/config.json ] || [ -L /root/.docker/config.json ]; then
    [ "$(stat -c '%F|%u|%g|%a|%h|%s' /root/.docker/config.json)" = 'regular file|0|0|600|1|2' ] || return 1
    [ "$(cat /root/.docker/config.json)" = '{}' ] || return 1
  fi
  /usr/bin/docker --context=default version >/dev/null 2>&1 || return 1
  local image_row
  image_row="$(/usr/bin/docker --context=default image inspect "$IMAGE_REF" --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{index .Config.Labels "org.opencontainers.image.revision"}}')" || return 1
  [ "$image_row" = "$IMAGE_CONFIG|linux|amd64|$RELEASE_COMMIT" ] || return 1
  [ -z "$(/usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" ] || return 1
  [ "$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" = 0 ] || return 1
}

readback() {
  current_machine_preflight || emit_fixed FAIL current_preflight 3
  [ -d "$BASE_ROOT" ] && [ ! -L "$BASE_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$BASE_ROOT")" = '0|0|700' ] || emit_fixed UNKNOWN base_root 4
  [ -d "$CONTROL_ROOT" ] && [ ! -L "$CONTROL_ROOT" ] && [ "$(stat -c '%u|%g|%a' "$CONTROL_ROOT")" = '0|0|700' ] || emit_fixed UNKNOWN control_root 4
  [ "$(find "$CONTROL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'control-private.pem\ncontrol-public.pem' ] || emit_fixed UNKNOWN control_inventory 4
  [ "$(stat -c '%F|%u|%g|%a|%h' "$PRIVATE_KEY")" = 'regular file|0|0|600|1' ] || emit_fixed UNKNOWN private_metadata 4
  for path in "$ENVELOPE" "$TRANSFER" "$CAPTURE_TASK" "$FINAL_ROOT" "$ATTEMPT"; do
    [ ! -e "$path" ] && [ ! -L "$path" ] || emit_fixed UNKNOWN later_state_present 4
  done
  python3 -I -B - "$PRIVATE_KEY" "$PUBLIC_KEY" "$PUBLIC_METADATA" "$BUILDER_IDENTITY_SHA256" <<'PY' 2>/dev/null || emit_fixed UNKNOWN readback 4
import base64,hashlib,json,os,re,stat,subprocess,sys
private_path,public_path,metadata_path,identity=sys.argv[1:]
def read(path,low,high):
    row=os.lstat(path)
    if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=0o600 or row.st_nlink!=1 or not low<=row.st_size<=high: raise SystemExit(2)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: body=os.read(fd,high+1); now=os.fstat(fd)
    finally: os.close(fd)
    if len(body)!=row.st_size or (row.st_dev,row.st_ino,row.st_mode,row.st_size)!=(now.st_dev,now.st_ino,now.st_mode,now.st_size): raise SystemExit(2)
    return body
public=read(public_path,625,625); body=read(metadata_path,1,4096)
if not public.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not public.endswith(b"-----END PUBLIC KEY-----\n") or not body.endswith(b"\n"): raise SystemExit(2)
der=subprocess.check_output(["/usr/bin/openssl","pkey","-pubin","-outform","DER"],input=public,stderr=subprocess.DEVNULL)
private_der=subprocess.check_output(["/usr/bin/openssl","pkey","-in",private_path,"-pubout","-outform","DER"],stderr=subprocess.DEVNULL)
if private_der!=der: raise SystemExit(2)
row=json.loads(body.decode("ascii"))
expected={"NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN":"PASS","automatic_retry_allowed":False,"builder_identity_sha256":identity,"private_key_created":True,"private_key_pair_verified":True,"private_key_value_read_count":1,"public_der_sha256":hashlib.sha256(der).hexdigest(),"public_key_pem_b64":base64.b64encode(public).decode("ascii"),"same_invocation_replay_allowed":False,"schema_version":1}
canonical=(json.dumps(expected,ensure_ascii=True,sort_keys=True,separators=(",",":"))+"\n").encode("ascii")
if canonical!=body: raise SystemExit(2)
os.write(1,canonical)
PY
}

generate() {
  [ "$(id -u)" = 0 ] && [ "$(id -g)" = 0 ] || emit_fixed FAIL root 3
  for tool in python3 openssl docker systemctl stat find sort ss awk mkdir; do command -v "$tool" >/dev/null 2>&1 || emit_fixed FAIL tool 3; done
  [ -d /var/lib/noteai ] && [ ! -L /var/lib/noteai ] && [ "$(stat -c '%u|%g|%a' /var/lib/noteai)" = '0|0|700' ] || emit_fixed FAIL parent 3
  [ ! -e "$BASE_ROOT" ] && [ ! -L "$BASE_ROOT" ] || emit_fixed UNKNOWN preexisting_base 4
  current_machine_preflight || emit_fixed FAIL machine_preflight 3
  mkdir -m 0700 "$BASE_ROOT" || emit_fixed UNKNOWN base_create 4
  mkdir -m 0700 "$CONTROL_ROOT" || emit_fixed UNKNOWN control_create 4
  python3 -I -B - "$PRIVATE_KEY" "$PUBLIC_KEY" "$PUBLIC_METADATA" "$BUILDER_IDENTITY_SHA256" <<'PY' 2>/dev/null || emit_fixed UNKNOWN generate 4
import base64,hashlib,json,os,subprocess,sys
private_path,public_path,metadata_path,identity=sys.argv[1:]
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
private=subprocess.check_output(["/usr/bin/openssl","genpkey","-algorithm","RSA","-pkeyopt","rsa_keygen_bits:3072","-pkeyopt","rsa_keygen_pubexp:65537"],stderr=subprocess.DEVNULL)
public=subprocess.check_output(["/usr/bin/openssl","pkey","-pubout"],input=private,stderr=subprocess.DEVNULL)
der=subprocess.check_output(["/usr/bin/openssl","pkey","-pubout","-outform","DER"],input=private,stderr=subprocess.DEVNULL)
if len(public)!=625 or not public.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not public.endswith(b"-----END PUBLIC KEY-----\n"): raise SystemExit(2)
write_once(private_path,private); write_once(public_path,public)
row={"NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN":"PASS","automatic_retry_allowed":False,"builder_identity_sha256":identity,"private_key_created":True,"private_key_pair_verified":True,"private_key_value_read_count":1,"public_der_sha256":hashlib.sha256(der).hexdigest(),"public_key_pem_b64":base64.b64encode(public).decode("ascii"),"same_invocation_replay_allowed":False,"schema_version":1}
body=(json.dumps(row,ensure_ascii=True,sort_keys=True,separators=(",",":"))+"\n").encode("ascii")
write_once(metadata_path,body)
for path in (os.path.dirname(private_path),os.path.dirname(metadata_path),os.path.dirname(os.path.dirname(metadata_path))):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)
os.write(1,body)
PY
}

case "$MODE" in
  GENERATE) generate ;;
  READBACK) readback ;;
  *) emit_fixed FAIL mode 3 ;;
esac
