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
  DOCKER_CERT_PATH \
  DOCKER_CONFIG \
  DOCKER_CONTEXT \
  DOCKER_HOST \
  DOCKER_TLS_VERIFY \
  HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
export DOCKER_CONTEXT='default'

readonly REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:ad5827450ad187bd3cfb47f00a903b78106b00a5ca8dbee5e9a77770f0c02e2b'
readonly TASK_ROOT='/run/noteai-item24-payment-pull-v1'
readonly DOCKER_CONFIG_ROOT="${TASK_ROOT}/docker-config"
readonly PRIVATE_KEY="${TASK_ROOT}/transport-private.pem"
readonly PUBLIC_KEY="${TASK_ROOT}/transport-public.pem"

phase='preflight'
task_root_owned=0
key_ready=0
host_label='UNKNOWN'

cleanup_failure() {
  if [ "$key_ready" != '1' ] && [ "$task_root_owned" = '1' ]; then
    rm -rf -- "$TASK_ROOT" || true
  fi
}

on_exit() {
  local exit_code=$?
  trap - EXIT
  cleanup_failure
  if [ "$exit_code" -ne 0 ]; then
    if [ "$key_ready" = '1' ]; then
      printf 'NOTEAI_ITEM24_PAYMENT_KEYGEN=UNKNOWN phase=%s host=%s readback_required=true automatic_retry_allowed=false\n' \
        "$phase" "$host_label" >&2
    else
      printf 'NOTEAI_ITEM24_PAYMENT_KEYGEN=FAIL phase=%s host=%s automatic_retry_allowed=false\n' \
        "$phase" "$host_label" >&2
    fi
  fi
  exit "$exit_code"
}
trap on_exit EXIT

for command_name in docker openssl python3 systemctl stat sha256sum base64 sort ss awk wc grep; do
  command -v "$command_name" >/dev/null
done
[ "$(id -u)" = '0' ]
[ "$(uname -s)" = 'Linux' ]
[ "$(uname -m)" = 'x86_64' ]
[ "$(systemctl is-active docker)" = 'active' ]
[ "$(systemctl is-enabled docker)" = 'enabled' ]
[ -S /var/run/docker.sock ]
[ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ]

instance_id="$({
  python3 - <<'PY'
import sys
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("imds_redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    NoRedirect(),
)
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
if not instance_id or len(instance_id) > 64 or not instance_id.startswith("i-"):
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
  *) phase='host_identity'; exit 71 ;;
esac
[ "$host_label" = 'API-C' ]

mkdir -m 0700 -- "$TASK_ROOT"
task_root_owned=1
install -d -o root -g root -m 0700 -- "$DOCKER_CONFIG_ROOT"

phase='docker_baseline'
[ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker context show)" = 'default' ]
[ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker context inspect default \
  --format '{{.Endpoints.docker.Host}}')" = 'unix:///var/run/docker.sock' ]
env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker version >/dev/null
env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker info >/dev/null
if env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" docker image inspect "$REF" \
    >/dev/null 2>"${TASK_ROOT}/inspect.err"; then
  phase='payment_image_already_present'
  exit 72
fi
grep -Fq 'No such image:' "${TASK_ROOT}/inspect.err"
rm -f -- "${TASK_ROOT}/inspect.err"

container_rows="$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" \
  docker ps -a --format '{{.Names}}|{{.State}}' | LC_ALL=C sort)"
case "$host_label" in
  API-C)
    [ "$container_rows" = $'noteai-admin-c|running\nnoteai-api-c|running' ]
    ;;
  Worker-C|Worker-F)
    [ -z "$container_rows" ]
    ;;
esac
[ "$(ss -Htan state established 2>/dev/null | \
  awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {count++} END {print count + 0}')" = '0' ]

phase='key_generation'
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$PRIVATE_KEY" >/dev/null 2>&1
openssl pkey -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY" >/dev/null 2>&1
chown root:root "$PRIVATE_KEY" "$PUBLIC_KEY"
chmod 0600 "$PRIVATE_KEY" "$PUBLIC_KEY"
[ "$(stat -c '%u:%g:%a:%h' "$PRIVATE_KEY")" = '0:0:600:1' ]
[ "$(stat -c '%u:%g:%a:%h' "$PUBLIC_KEY")" = '0:0:600:1' ]
openssl pkey -in "$PRIVATE_KEY" -check -noout >/dev/null 2>&1
openssl pkey -pubin -in "$PUBLIC_KEY" -text -noout 2>/dev/null | \
  grep -Fq 'Public-Key: (3072 bit)'
public_key_sha256="$(openssl pkey -pubin -in "$PUBLIC_KEY" -outform DER 2>/dev/null | \
  sha256sum | awk '{print $1}')"
[[ "$public_key_sha256" =~ ^[0-9a-f]{64}$ ]]
public_key_b64="$(base64 -w 0 "$PUBLIC_KEY")"
[ -n "$public_key_b64" ]
key_ready=1

phase='key_ready'
printf 'NOTEAI_ITEM24_PAYMENT_KEYGEN=KEY_READY host=%s public_key_sha256=%s public_key_b64=%s automatic_retry_allowed=false\n' \
  "$host_label" "$public_key_sha256" "$public_key_b64"
trap - EXIT
