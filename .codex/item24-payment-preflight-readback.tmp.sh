#!/bin/bash
set -u
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 077
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH DOCKER_CONTEXT

readonly DOCKER_CONFIG_ROOT=/run/noteai-item24-payment-preflight-v1
readonly PAYMENT_UNIT=/etc/systemd/system/noteai-payment.service
readonly PAYMENT_ENV=/etc/noteai/payment.env
readonly PAYMENT_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:ad5827450ad187bd3cfb47f00a903b78106b00a5ca8dbee5e9a77770f0c02e2b'
readonly PAYMENT_CONFIG='sha256:36b465dca36d5751318033cd494ed7544588f9ead18b781801542642ed2b1bc4'
readonly DOCKER=(/usr/bin/env "DOCKER_CONFIG=/run/noteai-item24-diagnostic-does-not-exist" /usr/bin/docker --context=default)

bool() {
  if "$@"; then
    printf true
  else
    printf false
  fi
}

env_metadata_exact=false
if [ -f "$PAYMENT_ENV" ] && [ ! -L "$PAYMENT_ENV" ]; then
  [ "$(stat -c '%U|%G|%a|%h' "$PAYMENT_ENV" 2>/dev/null)" = 'root|root|600|1' ] \
    && env_metadata_exact=true
fi
unit_path_absent="$(bool test ! -e "$PAYMENT_UNIT")"
unit_load_state="$(systemctl show noteai-payment.service -p LoadState --value 2>/dev/null || printf query_failed)"
unit_active_state="$(systemctl is-active noteai-payment.service 2>/dev/null || true)"
unit_enabled_state="$(systemctl is-enabled noteai-payment.service 2>/dev/null || true)"
docker_version_ok="$(bool "${DOCKER[@]}" version --format '{{.Server.Version}}')"
docker_info_ok="$(bool "${DOCKER[@]}" info --format '{{.ServerVersion}}')"
payment_container_count="$(( $("${DOCKER[@]}" container ls -aq --filter 'name=^/noteai-payment$' 2>/dev/null | sed '/^$/d' | wc -l) ))"
image_present=false
image_config_match=false
image_role_match=false
if image_line="$("${DOCKER[@]}" image inspect "$PAYMENT_REF" --format '{{.Id}}|{{index .Config.Labels "com.noteai.runtime.role"}}' 2>/dev/null)"; then
  image_present=true
  [ "$image_line" = "$PAYMENT_CONFIG|payment" ] && image_config_match=true && image_role_match=true
fi
api_live_8000="$(PORT=8000 /usr/bin/python3 - <<'PY'
import http.client
import os

try:
    connection = http.client.HTTPConnection(
        "127.0.0.1", int(os.environ["PORT"]), timeout=3
    )
    connection.request("GET", "/health/live")
    response = connection.getresponse()
    body = response.read(2048)
    connection.close()
    print("true" if response.status == 200 and b'"status":"ok"' in body.replace(b" ", b"") else "false")
except Exception:
    print("false")
PY
)"
api_live_8001="$(PORT=8001 /usr/bin/python3 - <<'PY'
import http.client
import os

try:
    connection = http.client.HTTPConnection(
        "127.0.0.1", int(os.environ["PORT"]), timeout=3
    )
    connection.request("GET", "/health/live")
    response = connection.getresponse()
    body = response.read(2048)
    connection.close()
    print("true" if response.status == 200 and b'"status":"ok"' in body.replace(b" ", b"") else "false")
except Exception:
    print("false")
PY
)"
database_connections="$(ss -Htan state established '( dport = :5432 or sport = :5432 )' 2>/dev/null | wc -l | tr -d ' ')"
task_root_absent="$(bool test ! -e "$DOCKER_CONFIG_ROOT")"

printf '%s\n' "NOTEAI_ITEM24_PAYMENT_PREFLIGHT_READBACK=OBSERVED schema=v1 env_metadata_exact=$env_metadata_exact unit_path_absent=$unit_path_absent unit_load_state=$unit_load_state unit_active_state=$unit_active_state unit_enabled_state=$unit_enabled_state docker_version_ok=$docker_version_ok docker_info_ok=$docker_info_ok payment_container_count=$payment_container_count image_present=$image_present image_config_match=$image_config_match image_role_match=$image_role_match api_live_8000=$api_live_8000 api_live_8001=$api_live_8001 database_connections=$database_connections task_root_absent=$task_root_absent source_secret_reads=0 provider_calls=0 ledger_writes=0 host_mutations=0 automatic_retry_allowed=false"
