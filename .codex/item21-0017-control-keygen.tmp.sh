#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH

readonly EXPECTED_INSTANCE='i-wz9j36od3nf2b1uw7bvg'
readonly EXPECTED_ROLE='noteai-storage-api-20260729-c60cc608'
readonly SOURCE_ROOT='/run/noteai-item21-0017-control-source-v1'
readonly ARCHIVE='/run/noteai-item21-0017-source-f1a5cc.tar.gz'
readonly TASK_ROOT='/run/noteai-item21-0017-control-keygen-v1'
readonly STAGE_ROOT="$TASK_ROOT/output"
readonly CONTROL_ROOT='/run/noteai-durable-ai-control'
readonly STAGE_PRIVATE_KEY="$STAGE_ROOT/control-private.pem"
readonly STAGE_PUBLIC_KEY="$STAGE_ROOT/control-public.pem"
readonly PRIVATE_KEY="$CONTROL_ROOT/control-private.pem"
readonly PUBLIC_KEY="$CONTROL_ROOT/control-public.pem"
readonly FINAL_ENVELOPE="$CONTROL_ROOT/control-database-url.enc"
readonly API_ENV='/etc/noteai/api.env'

phase='preflight'
known_failure=0
task_created=0
task_cleaned=0
key_committed=0
key_ready=0
completed=0

fail() {
  known_failure=1
  phase="$1"
  exit 3
}

openssl_clean() {
  /usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl "$@"
}

cleanup_task_root() {
  if [ "$task_created" -eq 1 ] && [ "$task_cleaned" -eq 0 ]; then
    [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
    [ "$(stat -c '%u|%g|%a' "$TASK_ROOT")" = '0|0|700' ] || return 1
    rm -rf --one-file-system "$TASK_ROOT" || return 1
    [ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
    task_cleaned=1
  fi
  return 0
}

on_exit() {
  local rc=$?
  local cleanup_ok=1
  if [ "$completed" -eq 1 ] && [ "$rc" -eq 0 ]; then
    return 0
  fi
  trap - EXIT
  if [ "$key_ready" -eq 1 ] || [ "$key_committed" -eq 1 ]; then
    printf '%s\n' "NOTEAI_ITEM21_0017_CONTROL_KEYGEN=UNKNOWN incident_class=PRE_DATABASE phase=$phase cleanup=KEY_RETAINED key_state=RETAINED readback_required=true database_connections=0 database_writes=0 source_secret_reads=0 private_key_emitted=0 secret_values_emitted=0 provider_control_plane_mutations=0 automatic_retry_allowed=false" >&2
    exit 4
  fi
  if [ -e "$CONTROL_ROOT" ] || [ -L "$CONTROL_ROOT" ]; then
    printf '%s\n' "NOTEAI_ITEM21_0017_CONTROL_KEYGEN=UNKNOWN incident_class=PRE_DATABASE phase=$phase cleanup=UNKNOWN key_state=RETAINED_OR_UNKNOWN readback_required=true database_connections=0 database_writes=0 source_secret_reads=0 private_key_emitted=0 secret_values_emitted=0 provider_control_plane_mutations=0 automatic_retry_allowed=false" >&2
    exit 4
  fi
  if [ "$task_created" -eq 0 ] && { [ -e "$TASK_ROOT" ] || [ -L "$TASK_ROOT" ]; }; then
    printf '%s\n' "NOTEAI_ITEM21_0017_CONTROL_KEYGEN=UNKNOWN incident_class=PRE_DATABASE phase=$phase cleanup=UNKNOWN key_state=UNKNOWN readback_required=true database_connections=0 database_writes=0 source_secret_reads=0 private_key_emitted=0 secret_values_emitted=0 provider_control_plane_mutations=0 automatic_retry_allowed=false" >&2
    exit 4
  fi
  cleanup_task_root >/dev/null 2>&1 || cleanup_ok=0
  if [ "$known_failure" -eq 1 ] && [ "$cleanup_ok" -eq 1 ]; then
    if [ "$task_created" -eq 1 ]; then
      cleanup_state='VERIFIED_ZERO'
    else
      cleanup_state='NOT_NEEDED'
    fi
    printf '%s\n' "NOTEAI_ITEM21_0017_CONTROL_KEYGEN=FAIL incident_class=PRE_DATABASE phase=$phase cleanup=$cleanup_state key_state=NOT_READY database_connections=0 database_writes=0 source_secret_reads=0 private_key_emitted=0 secret_values_emitted=0 provider_control_plane_mutations=0 automatic_retry_allowed=false" >&2
    exit 3
  fi
  printf '%s\n' "NOTEAI_ITEM21_0017_CONTROL_KEYGEN=UNKNOWN incident_class=PRE_DATABASE phase=$phase cleanup=UNKNOWN key_state=UNKNOWN readback_required=true database_connections=0 database_writes=0 source_secret_reads=0 private_key_emitted=0 secret_values_emitted=0 provider_control_plane_mutations=0 automatic_retry_allowed=false" >&2
  exit 4
}
trap on_exit EXIT

[ "$(id -u)" = '0' ] || fail root_required
for required in python3 openssl timeout stat sha256sum base64 awk grep ss rm mv cmp wc tr chown chmod mkdir; do
  command -v "$required" >/dev/null 2>&1 || fail required_tool
done
[ -x /usr/bin/timeout ] && [ -x /usr/bin/env ] && [ -x /usr/bin/openssl ] || fail required_absolute_tool
[ -d /run ] && [ ! -L /run ] || fail run_root
if [ -e "$TASK_ROOT" ] || [ -L "$TASK_ROOT" ]; then
  phase='task_root_preexisting'
  exit 4
fi
if [ -e "$CONTROL_ROOT" ] || [ -L "$CONTROL_ROOT" ]; then
  phase='control_root_preexisting'
  exit 4
fi

identity="$({ python3 -I -B - <<'PY'
import re
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect")

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
token_request = urllib.request.Request(
    "http://100.100.100.200/latest/api/token",
    method="PUT",
    headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"},
)
with opener.open(token_request, timeout=3) as response:
    token = response.read(512).decode("ascii").strip()
if not token or len(token) > 256:
    raise SystemExit(2)
headers = {"X-aliyun-ecs-metadata-token": token}
values = []
for suffix in ("instance-id", "ram/security-credentials/"):
    request = urllib.request.Request(
        "http://100.100.100.200/latest/meta-data/" + suffix,
        headers=headers,
        method="GET",
    )
    with opener.open(request, timeout=3) as response:
        payload = response.read(4096)
    if len(payload) >= 4096:
        raise SystemExit(2)
    values.append(payload.decode("ascii").strip())
if not re.fullmatch(r"i-[a-z0-9]+", values[0]):
    raise SystemExit(2)
roles = [row for row in values[1].splitlines() if row]
if values[0] != "i-wz9j36od3nf2b1uw7bvg":
    raise SystemExit(2)
if roles != ["noteai-storage-api-20260729-c60cc608"]:
    raise SystemExit(2)
print("HOST_IDENTITY_EXACT")
PY
} 2>/dev/null)" || fail host_identity
[ "$identity" = 'HOST_IDENTITY_EXACT' ] || fail host_identity

artifact_contract="$({ python3 -I -B - "$SOURCE_ROOT" "$ARCHIVE" "$API_ENV" <<'PY'
import hashlib
import os
import stat
import sys

source_root, archive_path, api_env = sys.argv[1:]
expected = {
    "scripts/validate_production_env_files.py": (7290, "1b1c2d1aef0bd52e07ebdbd3e671417bf00b5b8754efe7133e198eff17b41b21"),
    "tools/production_ai_dispatcher_secret_activator.py": (36894, "258a7831de36d158c5b346f220f38073f97dfd0d70109cb46a65fcbd52a13f3f"),
    "tools/production_durable_ai_protected_control.py": (16107, "c6e3c370495365c07dcbf8e4bf7cd8e250091dde563610741b7c7868841a2bb6"),
    "tools/production_durable_ai_schema_0017.py": (15991, "c64cb74799cecb908902895f7151a13464980ec3ba2e0dccc7525c3536c4a8be"),
    "tools/production_managed_secret_roles.py": (15177, "8d42df5a6ac5b466cd9040757448602f6fedcf0b87ae33fce7a9c3b3fc24973f"),
    "tools/production_secret_envelope.py": (3637, "b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf"),
}

def safe_dir(path, mode):
    st = os.lstat(path)
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode) and st.st_uid == 0 and st.st_gid == 0 and stat.S_IMODE(st.st_mode) == mode

def read_exact(path, size, digest):
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise SystemExit(2)
    if st.st_uid != 0 or st.st_gid != 0 or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1 or st.st_size != size:
        raise SystemExit(2)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino, fst.st_mode, fst.st_uid, fst.st_gid, fst.st_nlink, fst.st_size) != (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid, st.st_nlink, st.st_size):
            raise SystemExit(2)
        data = b""
        while len(data) <= size:
            chunk = os.read(fd, min(65536, size + 1 - len(data)))
            if not chunk:
                break
            data += chunk
    finally:
        os.close(fd)
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit(2)

if not safe_dir(source_root, 0o700):
    raise SystemExit(2)
if sorted(os.listdir(source_root)) != ["scripts", "tools"]:
    raise SystemExit(2)
for directory in ("scripts", "tools"):
    if not safe_dir(os.path.join(source_root, directory), 0o700):
        raise SystemExit(2)
if sorted(os.listdir(os.path.join(source_root, "scripts"))) != [
    "validate_production_env_files.py"
]:
    raise SystemExit(2)
if sorted(os.listdir(os.path.join(source_root, "tools"))) != [
    "production_ai_dispatcher_secret_activator.py",
    "production_durable_ai_protected_control.py",
    "production_durable_ai_schema_0017.py",
    "production_managed_secret_roles.py",
    "production_secret_envelope.py",
]:
    raise SystemExit(2)
for name, (size, digest) in expected.items():
    read_exact(os.path.join(source_root, name), size, digest)
read_exact(archive_path, 20625, "8abb1fca9f67e98daca292932eb10ec9b39d5c79f8cbbd6e405e680de23d5c37")
env_st = os.lstat(api_env)
if not stat.S_ISREG(env_st.st_mode) or stat.S_ISLNK(env_st.st_mode):
    raise SystemExit(2)
if env_st.st_uid != 0 or env_st.st_gid != 0 or stat.S_IMODE(env_st.st_mode) != 0o600 or env_st.st_nlink != 1 or not 1 <= env_st.st_size <= 16384:
    raise SystemExit(2)
print("ARTIFACTS_AND_API_ENV_METADATA_EXACT")
PY
} 2>/dev/null)" || fail retained_artifact_contract
[ "$artifact_contract" = 'ARTIFACTS_AND_API_ENV_METADATA_EXACT' ] || fail retained_artifact_contract

db_connections="$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" || fail database_socket_query
[ "$db_connections" = '0' ] || fail database_connection_present

phase='task_root_create'
mkdir -m 0700 "$TASK_ROOT" || fail task_root_create
task_created=1
mkdir -m 0700 "$STAGE_ROOT" || fail stage_root_create
[ "$(stat -c '%u|%g|%a' "$TASK_ROOT")" = '0|0|700' ] || fail task_root_metadata
[ "$(stat -c '%u|%g|%a' "$STAGE_ROOT")" = '0|0|700' ] || fail stage_root_metadata

phase='key_generation'
/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 60s \
  /usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl \
  genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$STAGE_PRIVATE_KEY" >/dev/null 2>&1 || fail private_key_generation
/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 20s \
  /usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl \
  pkey -in "$STAGE_PRIVATE_KEY" -pubout -out "$STAGE_PUBLIC_KEY" \
  >/dev/null 2>&1 || fail public_key_generation
chown root:root "$STAGE_PRIVATE_KEY" "$STAGE_PUBLIC_KEY" || fail key_owner
chmod 0600 "$STAGE_PRIVATE_KEY" "$STAGE_PUBLIC_KEY" || fail key_mode
[ "$(stat -c '%u|%g|%a|%h' "$STAGE_PRIVATE_KEY")" = '0|0|600|1' ] || fail private_key_metadata
[ "$(stat -c '%u|%g|%a|%h' "$STAGE_PUBLIC_KEY")" = '0|0|600|1' ] || fail public_key_metadata
[ "$(stat -c '%s' "$STAGE_PUBLIC_KEY")" = '625' ] || fail public_key_size
/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 20s \
  /usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl \
  pkey -in "$STAGE_PRIVATE_KEY" -check -noout >/dev/null 2>&1 || fail private_key_check
private_public_sha256="$(openssl_clean pkey -in "$STAGE_PRIVATE_KEY" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || fail private_public_hash
public_key_sha256="$(openssl_clean pkey -pubin -in "$STAGE_PUBLIC_KEY" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || fail public_key_hash
[[ "$public_key_sha256" =~ ^[0-9a-f]{64}$ ]] || fail public_key_hash_shape
[ "$private_public_sha256" = "$public_key_sha256" ] || fail key_pair_mismatch
[ "$(openssl_clean pkey -pubin -in "$STAGE_PUBLIC_KEY" -outform DER 2>/dev/null | wc -c | tr -d ' ')" = '422' ] || fail public_key_der_size
openssl_clean pkey -pubin -in "$STAGE_PUBLIC_KEY" -text -noout 2>/dev/null | grep -Fq 'Public-Key: (3072 bit)' || fail public_key_bits
openssl_clean pkey -pubin -in "$STAGE_PUBLIC_KEY" -text -noout 2>/dev/null | grep -Fq 'Exponent: 65537 (0x10001)' || fail public_key_exponent

printf '%s' 'noteai-0017-control-key-selftest-v1' >"$TASK_ROOT/selftest.plain" || fail selftest_input
/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 20s \
  /usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl \
  pkeyutl -encrypt -pubin -inkey "$STAGE_PUBLIC_KEY" \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 \
  -pkeyopt rsa_mgf1_md:sha256 \
  -pkeyopt rsa_oaep_label:6e6f746561692d6d616e616765642d736563726574732d7631 \
  -in "$TASK_ROOT/selftest.plain" \
  -out "$TASK_ROOT/selftest.cipher" >/dev/null 2>&1 || fail selftest_encrypt
/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 20s \
  /usr/bin/env -i PATH="$PATH" LC_ALL=C /usr/bin/openssl \
  pkeyutl -decrypt -inkey "$STAGE_PRIVATE_KEY" \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 \
  -pkeyopt rsa_mgf1_md:sha256 \
  -pkeyopt rsa_oaep_label:6e6f746561692d6d616e616765642d736563726574732d7631 \
  -in "$TASK_ROOT/selftest.cipher" \
  -out "$TASK_ROOT/selftest.out" >/dev/null 2>&1 || fail selftest_decrypt
cmp -s "$TASK_ROOT/selftest.plain" "$TASK_ROOT/selftest.out" || fail selftest_mismatch
rm -f "$TASK_ROOT/selftest.plain" "$TASK_ROOT/selftest.cipher" "$TASK_ROOT/selftest.out" || fail selftest_cleanup

stage_inventory="$(python3 -I -B - "$STAGE_ROOT" <<'PY'
import os
import sys
root = sys.argv[1]
names = sorted(os.listdir(root))
if names != ["control-private.pem", "control-public.pem"]:
    raise SystemExit(2)
print("CONTROL_KEY_INVENTORY_EXACT")
PY
)" || fail control_root_inventory
[ "$stage_inventory" = 'CONTROL_KEY_INVENTORY_EXACT' ] || fail control_root_inventory

phase='key_promotion'
[ ! -e "$CONTROL_ROOT" ] && [ ! -L "$CONTROL_ROOT" ] || exit 4
mv "$STAGE_ROOT" "$CONTROL_ROOT" || exit 4
key_committed=1
[ "$(stat -c '%u|%g|%a' "$CONTROL_ROOT")" = '0|0|700' ] || exit 4
[ "$(stat -c '%u|%g|%a|%h' "$PRIVATE_KEY")" = '0|0|600|1' ] || exit 4
[ "$(stat -c '%u|%g|%a|%h' "$PUBLIC_KEY")" = '0|0|600|1' ] || exit 4
[ ! -e "$FINAL_ENVELOPE" ] && [ ! -L "$FINAL_ENVELOPE" ] || exit 4
final_public_sha256="$(openssl_clean pkey -pubin -in "$PUBLIC_KEY" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" || exit 4
[ "$final_public_sha256" = "$public_key_sha256" ] || exit 4
final_inventory="$(python3 -I -B - "$CONTROL_ROOT" <<'PY'
import os
import sys
if sorted(os.listdir(sys.argv[1])) != ["control-private.pem", "control-public.pem"]:
    raise SystemExit(2)
print("FINAL_KEY_INVENTORY_EXACT")
PY
)" || exit 4
[ "$final_inventory" = 'FINAL_KEY_INVENTORY_EXACT' ] || exit 4
cleanup_task_root || exit 4
public_key_b64="$(base64 -w 0 "$PUBLIC_KEY")" || exit 4
[ "${#public_key_b64}" = '836' ] || fail public_key_b64_size
key_ready=1

phase='key_ready'
printf '%s\n' "NOTEAI_ITEM21_0017_CONTROL_KEYGEN=KEY_READY schema=v1 host=API-C role_exact=true api_env_metadata_exact=true source_closure_exact=true transfer_archive_exact=true rsa_bits=3072 rsa_exponent=65537 public_key_sha256=$public_key_sha256 public_key_b64=$public_key_b64 control_root_retained=true database_connections=0 database_writes=0 source_secret_reads=0 private_key_emitted=0 secret_values_emitted=0 metadata_http_requests=3 provider_control_plane_mutations=0 automatic_retry_allowed=false"
completed=1
trap - EXIT
