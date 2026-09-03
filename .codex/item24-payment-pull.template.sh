#!/bin/bash
set +x
set -Eeuo pipefail
umask 077
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset \
  ALIBABA_CLOUD_ACCESS_KEY_ID \
  ALIBABA_CLOUD_ACCESS_KEY_SECRET \
  ALIBABA_CLOUD_SECURITY_TOKEN \
  ALICLOUD_ACCESS_KEY \
  ALICLOUD_SECRET_KEY \
  ALICLOUD_SECURITY_TOKEN \
  BUILDKIT_HOST \
  BUILDX_BUILDER \
  BUILDX_CONFIG \
  DOCKER_CERT_PATH \
  DOCKER_CONFIG \
  DOCKER_CONTEXT \
  DOCKER_HOST \
  DOCKER_TLS_VERIFY \
  HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
export DOCKER_CONTEXT='default'

readonly EXPECTED_HOST_LABEL='@@EXPECTED_HOST_LABEL@@'
readonly EXPECTED_PUBLIC_KEY_SHA256='@@EXPECTED_PUBLIC_KEY_SHA256@@'
readonly REGISTRY_USERNAME='@@REGISTRY_USERNAME@@'
readonly CREDENTIAL_EXPIRES_AT_EPOCH='@@CREDENTIAL_EXPIRES_AT_EPOCH@@'
readonly CIPHERTEXT_B64='@@CIPHERTEXT_B64@@'
readonly RELEASE='b55f11882100e9ef919522540729e366a511f88f'
readonly MANIFEST='sha256:ad5827450ad187bd3cfb47f00a903b78106b00a5ca8dbee5e9a77770f0c02e2b'
readonly CONFIG='sha256:36b465dca36d5751318033cd494ed7544588f9ead18b781801542642ed2b1bc4'
readonly REGISTRY_HOST='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com'
readonly REF="${REGISTRY_HOST}/noteai/app@${MANIFEST}"
readonly TASK_ROOT='/run/noteai-item24-payment-pull-v1'
readonly DOCKER_CONFIG_ROOT="${TASK_ROOT}/docker-config"
readonly PRIVATE_KEY="${TASK_ROOT}/transport-private.pem"
readonly PUBLIC_KEY="${TASK_ROOT}/transport-public.pem"
readonly CIPHERTEXT="${TASK_ROOT}/registry-password.cipher"
readonly PULL_LOG="${TASK_ROOT}/pull.log"
readonly IMAGE_INSPECT="${TASK_ROOT}/image-inspect.json"

phase='preflight'
host_label='UNKNOWN'
pull_started=0
pull_completed=0
login_completed=0
cleanup_complete=0
cleanup_required=0

database_connection_count() {
  ss -Htan state established 2>/dev/null |
    awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {count++} END {print count + 0}'
}

docker_auth_entry_count() {
  local config_path="$1"
  local expected_registry="$2"
  python3 - "$config_path" "$expected_registry" <<'PY'
import json
import os
import stat
import sys

path, expected_registry = sys.argv[1:]
metadata = os.lstat(path)
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit(2)
with open(path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
if not isinstance(payload, dict):
    raise SystemExit(3)
auths = payload.get("auths", {})
helpers = payload.get("credHelpers", {})
store = payload.get("credsStore", "")
if not isinstance(auths, dict) or not isinstance(helpers, dict) or not isinstance(store, str):
    raise SystemExit(4)
if set(auths) != {expected_registry} or helpers != {} or store != "":
    raise SystemExit(5)
print(1)
PY
}

api_container_fingerprint() {
  local name
  for name in noteai-admin-c noteai-api-c; do
    env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker container inspect \
      --format '{{.Id}}|{{.Name}}|{{.State.Status}}|{{.RestartCount}}|{{.Image}}|{{json .HostConfig.PortBindings}}' \
      "$name"
  done | LC_ALL=C sort
}

verify_api_health() {
  python3 - <<'PY'
import http.client
import json

contracts = ((8000, "noteai-api"), (8001, "noteai-admin"))
for _ in range(3):
    for port, service in contracts:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/health/live")
            response = connection.getresponse()
            body = response.read(65536)
        finally:
            connection.close()
        if response.status != 200 or len(body) == 0 or len(body) >= 65536:
            raise SystemExit(2)
        payload = json.loads(body.decode("utf-8"))
        if payload.get("status") != "ok" or payload.get("service") != service:
            raise SystemExit(3)
PY
}
verify_image_contract() {
  env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker image inspect "$REF" > "$IMAGE_INSPECT"
  python3 - "$IMAGE_INSPECT" "$REF" "$CONFIG" "$RELEASE" <<'PY'
import json
import re
import sys

path, ref, config_digest, release = sys.argv[1:]
with open(path, "r", encoding="utf-8") as handle:
    rows = json.load(handle)
if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
    raise SystemExit(2)
row = rows[0]
config = row.get("Config")
rootfs = row.get("RootFS")
if not isinstance(config, dict) or not isinstance(rootfs, dict):
    raise SystemExit(3)
labels = config.get("Labels")
env = config.get("Env")
layers = rootfs.get("Layers")
expected = (
    row.get("Id") == config_digest,
    row.get("Os") == "linux",
    row.get("Architecture") == "amd64",
    row.get("RepoTags") == [],
    row.get("RepoDigests") == [ref],
    isinstance(row.get("Size"), int) and row["Size"] > 0,
    isinstance(labels, dict),
    isinstance(env, list),
    isinstance(layers, list) and len(layers) > 0,
    config.get("User") == "noteai",
    config.get("Entrypoint") == ["/app/scripts/docker_entrypoint.sh"],
    config.get("Cmd") == ["/app/scripts/render_start_payment.sh"],
    config.get("WorkingDir") == "/app/model",
)
if not all(expected):
    raise SystemExit(4)
if labels.get("org.opencontainers.image.revision") != release:
    raise SystemExit(5)
if labels.get("com.noteai.runtime.role") != "payment":
    raise SystemExit(6)
for required in (
    "NOTEAI_RUNTIME_ROLE=payment",
    "NOTEAI_PAYMENT_CALLBACK_ENABLED=0",
    "NOTEAI_SKIP_MODEL_ARTIFACT_CHECK=1",
    "PORT=8002",
):
    if env.count(required) != 1:
        raise SystemExit(7)
if not all(isinstance(layer, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", layer) for layer in layers):
    raise SystemExit(8)
PY
}
cleanup_sensitive_state() {
  local cleanup_error=0
  if [ "$cleanup_required" != '1' ]; then
    return
  fi
  if [ -d "$DOCKER_CONFIG_ROOT" ]; then
    env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker logout "$REGISTRY_HOST" \
      >/dev/null 2>&1 || true
  fi
  rm -f -- "$PRIVATE_KEY" "$PUBLIC_KEY" "$CIPHERTEXT" "$PULL_LOG" \
    "$IMAGE_INSPECT" "${TASK_ROOT}/inspect.err" || cleanup_error=1
  rm -rf -- "$DOCKER_CONFIG_ROOT" || cleanup_error=1
  rmdir -- "$TASK_ROOT" 2>/dev/null || cleanup_error=1
  if [ -e "$TASK_ROOT" ] || [ -L "$TASK_ROOT" ]; then
    cleanup_error=1
  fi
  [ "$cleanup_error" = '0' ] || return 1
  cleanup_complete=1
}

on_exit() {
  local exit_code=$? cleanup_exit=0 outcome='FAIL'
  trap - EXIT
  cleanup_sensitive_state || cleanup_exit=$?
  if [ "$pull_started" = '1' ] || [ "$cleanup_complete" != '1' ]; then
    outcome='UNKNOWN'
  fi
  if [ "$cleanup_exit" -ne 0 ]; then
    outcome='UNKNOWN'
  fi
  if [ "$exit_code" -ne 0 ] || [ "$cleanup_exit" -ne 0 ]; then
    printf 'NOTEAI_ITEM24_PAYMENT_PULL=%s phase=%s host=%s pull_started=%s pull_completed=%s login_completed=%s cleanup_complete=%s readback_required=true automatic_retry_allowed=false\n' \
      "$outcome" "$phase" "$host_label" "$pull_started" "$pull_completed" \
      "$login_completed" "$cleanup_complete" >&2
  fi
  if [ "$exit_code" -eq 0 ] && [ "$cleanup_exit" -ne 0 ]; then
    exit_code="$cleanup_exit"
  fi
  exit "$exit_code"
}
trap on_exit EXIT

for command_name in awk base64 date docker find grep openssl python3 sha256sum sort ss stat systemctl timeout tr wc; do
  command -v "$command_name" >/dev/null
done
[ "$(id -u)" = '0' ]
[ "$(uname -s)" = 'Linux' ]
[ "$(uname -m)" = 'x86_64' ]
[ "$EXPECTED_HOST_LABEL" = 'API-C' ]
[[ "$EXPECTED_PUBLIC_KEY_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$REGISTRY_USERNAME" =~ ^[[:alnum:]_.:@+-]{1,256}$ ]]
[[ "$CREDENTIAL_EXPIRES_AT_EPOCH" =~ ^([0-9]{10}|[0-9]{13})$ ]]
expiry_seconds="$CREDENTIAL_EXPIRES_AT_EPOCH"
if [ "${#expiry_seconds}" = '13' ]; then
  expiry_seconds="$(( expiry_seconds / 1000 ))"
fi
[ "$expiry_seconds" -gt "$(( $(date +%s) + 2790 ))" ]
[[ "$CIPHERTEXT_B64" =~ ^[A-Za-z0-9+/]{512}$ ]]
[ "$(systemctl is-active docker)" = 'active' ]
[ "$(systemctl is-enabled docker)" = 'enabled' ]
[ -S /var/run/docker.sock ]
[ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ]
[ "$(stat -c '%u:%g:%a' "$TASK_ROOT")" = '0:0:700' ]
[ -d "$DOCKER_CONFIG_ROOT" ] && [ ! -L "$DOCKER_CONFIG_ROOT" ]
[ "$(stat -c '%u:%g:%a' "$DOCKER_CONFIG_ROOT")" = '0:0:700' ]
[ -f "$PRIVATE_KEY" ] && [ ! -L "$PRIVATE_KEY" ]
[ -f "$PUBLIC_KEY" ] && [ ! -L "$PUBLIC_KEY" ]
[ "$(stat -c '%u:%g:%a:%h' "$PRIVATE_KEY")" = '0:0:600:1' ]
[ "$(stat -c '%u:%g:%a:%h' "$PUBLIC_KEY")" = '0:0:600:1' ]
[ ! -e "$CIPHERTEXT" ] && [ ! -L "$CIPHERTEXT" ]
[ ! -e "$PULL_LOG" ] && [ ! -L "$PULL_LOG" ]
[ ! -e "$IMAGE_INSPECT" ] && [ ! -L "$IMAGE_INSPECT" ]
if find "$DOCKER_CONFIG_ROOT" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  exit 73
fi
cleanup_required=1

phase='host_identity'
instance_id="$({
  python3 - <<'PY'
import sys
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("imds_redirect")

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
token_request = urllib.request.Request(
    "http://100.100.100.200/latest/api/token",
    method="PUT",
    headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "600"},
)
with opener.open(token_request, timeout=3) as response:
    if response.status != 200:
        raise RuntimeError("imds_token_status")
    token = response.read(4096).decode("ascii")
if not token or len(token) > 2048 or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
    raise RuntimeError("imds_token_shape")
instance_request = urllib.request.Request(
    "http://100.100.100.200/latest/meta-data/instance-id",
    headers={"X-aliyun-ecs-metadata-token": token},
)
with opener.open(instance_request, timeout=3) as response:
    if response.status != 200:
        raise RuntimeError("imds_instance_status")
    instance_id = response.read(256).decode("ascii")
if not instance_id.startswith("i-") or len(instance_id) > 64:
    raise RuntimeError("imds_instance_shape")
if any(not (ch.isalnum() or ch == "-") for ch in instance_id):
    raise RuntimeError("imds_instance_shape")
sys.stdout.write(instance_id)
PY
} 2>/dev/null)"
case "$instance_id" in
  i-wz9j36od3nf2b1uw7bvg) host_label='API-C' ;;
  i-wz98zwcdtcmxzmmoso3w) host_label='Worker-C' ;;
  i-wz93qgvlu1bllpjcfwfj) host_label='Worker-F' ;;
  *) exit 71 ;;
esac
[ "$host_label" = "$EXPECTED_HOST_LABEL" ]

phase='key_and_docker_baseline'
openssl pkey -in "$PRIVATE_KEY" -check -noout >/dev/null 2>&1
openssl pkey -in "$PRIVATE_KEY" -text -noout 2>/dev/null | grep -Fq 'Private-Key: (3072 bit'
openssl pkey -pubin -in "$PUBLIC_KEY" -text -noout 2>/dev/null | grep -Fq 'Public-Key: (3072 bit)'
observed_public_key_sha256="$(openssl pkey -pubin -in "$PUBLIC_KEY" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
[ "$observed_public_key_sha256" = "$EXPECTED_PUBLIC_KEY_SHA256" ]
private_derived_public_key_sha256="$(openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
[ "$private_derived_public_key_sha256" = "$EXPECTED_PUBLIC_KEY_SHA256" ]
[ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker context show)" = 'default' ]
[ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker context inspect default --format '{{.Endpoints.docker.Host}}')" = 'unix:///var/run/docker.sock' ]
env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker version >/dev/null
env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker info >/dev/null
if env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker image inspect "$REF" >/dev/null 2>"${TASK_ROOT}/inspect.err"; then
  phase='payment_image_already_present'
  exit 72
fi
grep -Fq 'No such image:' "${TASK_ROOT}/inspect.err"
rm -f -- "${TASK_ROOT}/inspect.err"
[ "$(database_connection_count)" = '0' ]

api_fingerprint_before=''
image_ids_before=''
case "$host_label" in
  API-C)
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker ps -a --format '{{.Names}}|{{.State}}' | LC_ALL=C sort)" = $'noteai-admin-c|running\nnoteai-api-c|running' ]
    api_fingerprint_before="$(api_container_fingerprint)"
    image_ids_before="$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker image ls -aq --no-trunc | LC_ALL=C sort -u)"
    [ -n "$image_ids_before" ]
    if printf '%s\n' "$image_ids_before" | grep -Fqx "$CONFIG"; then
      phase='payment_config_already_present'
      exit 72
    fi
    ;;
  Worker-C|Worker-F)
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker ps -aq | wc -l | tr -d ' ')" = '0' ]
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker image ls -aq | LC_ALL=C sort -u | wc -l | tr -d ' ')" = '0' ]
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker volume ls -q | wc -l | tr -d ' ')" = '0' ]
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker system df --format '{{.Type}}={{.TotalCount}}' | awk -F= '$1=="Build Cache" {print $2}')" = '0' ]
    ;;
esac

phase='ciphertext_materialization'
printf '%s' "$CIPHERTEXT_B64" | base64 -d > "$CIPHERTEXT"
chown root:root "$CIPHERTEXT"
chmod 0600 "$CIPHERTEXT"
[ "$(stat -c '%u:%g:%a:%s:%h' "$CIPHERTEXT")" = '0:0:600:384:1' ]

phase='registry_login'
openssl pkeyutl -decrypt \
  -inkey "$PRIVATE_KEY" \
  -pkeyopt rsa_padding_mode:oaep \
  -pkeyopt rsa_oaep_md:sha256 \
  -pkeyopt rsa_mgf1_md:sha256 \
  -in "$CIPHERTEXT" 2>/dev/null | \
  timeout --foreground --signal=TERM --kill-after=10s 60s \
  env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker login \
    --username "$REGISTRY_USERNAME" --password-stdin "$REGISTRY_HOST" \
    >/dev/null 2>&1
login_completed=1
rm -f -- "$PRIVATE_KEY" "$PUBLIC_KEY" "$CIPHERTEXT"
[ ! -e "$PRIVATE_KEY" ] && [ ! -L "$PRIVATE_KEY" ]
[ ! -e "$PUBLIC_KEY" ] && [ ! -L "$PUBLIC_KEY" ]
[ ! -e "$CIPHERTEXT" ] && [ ! -L "$CIPHERTEXT" ]
[ -f "$DOCKER_CONFIG_ROOT/config.json" ] && [ ! -L "$DOCKER_CONFIG_ROOT/config.json" ]
chmod 0600 "$DOCKER_CONFIG_ROOT/config.json"
[ "$(stat -c '%u:%g:%a' "$DOCKER_CONFIG_ROOT/config.json")" = '0:0:600' ]
[ "$(docker_auth_entry_count "$DOCKER_CONFIG_ROOT/config.json" "$REGISTRY_HOST")" = '1' ]
[ "$expiry_seconds" -gt "$(( $(date +%s) + 2790 ))" ]

phase='single_exact_digest_pull'
pull_started=1
timeout --foreground --signal=TERM --kill-after=30s 2700s \
  env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker pull --platform linux/amd64 "$REF" \
  >"$PULL_LOG" 2>&1
pull_completed=1
grep -Fqx "Digest: ${MANIFEST}" "$PULL_LOG"

phase='image_and_host_acceptance'
verify_image_contract
case "$host_label" in
  API-C)
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker ps -a --format '{{.Names}}|{{.State}}' | LC_ALL=C sort)" = $'noteai-admin-c|running\nnoteai-api-c|running' ]
    [ "$(api_container_fingerprint)" = "$api_fingerprint_before" ]
    observed_image_ids_after="$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker image ls -aq --no-trunc | LC_ALL=C sort -u)"
    expected_image_ids_after="$(printf '%s\n%s\n' "$image_ids_before" "$CONFIG" | LC_ALL=C sort -u)"
    [ "$observed_image_ids_after" = "$expected_image_ids_after" ]
    verify_api_health
    ;;
  Worker-C|Worker-F)
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker ps -aq | wc -l | tr -d ' ')" = '0' ]
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker image ls -aq | LC_ALL=C sort -u | wc -l | tr -d ' ')" = '1' ]
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker volume ls -q | wc -l | tr -d ' ')" = '0' ]
    [ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker system df --format '{{.Type}}={{.TotalCount}}' | awk -F= '$1=="Build Cache" {print $2}')" = '0' ]
    ;;
esac
[ "$(database_connection_count)" = '0' ]

phase='credential_cleanup'
cleanup_sensitive_state
[ "$cleanup_complete" = '1' ]
phase='accepted'
printf 'NOTEAI_ITEM24_PAYMENT_PULL=PASS host=%s release=%s manifest=%s config=%s pulls=1 executor_retries=0 containers_started=0 cleanup_complete=true automatic_retry_allowed=false\n' \
  "$host_label" "$RELEASE" "$MANIFEST" "$CONFIG"
trap - EXIT
