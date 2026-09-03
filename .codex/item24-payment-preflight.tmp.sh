#!/bin/bash
set -Eeuo pipefail
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

cleanup() {
  local rc=$?
  trap - EXIT
  if [ -d "$DOCKER_CONFIG_ROOT" ] && [ ! -L "$DOCKER_CONFIG_ROOT" ]; then
    if find "$DOCKER_CONFIG_ROOT" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
      exit 4
    fi
    rmdir "$DOCKER_CONFIG_ROOT" || exit 4
  elif [ -e "$DOCKER_CONFIG_ROOT" ] || [ -L "$DOCKER_CONFIG_ROOT" ]; then
    exit 4
  fi
  exit "$rc"
}
trap cleanup EXIT

[ ! -e "$DOCKER_CONFIG_ROOT" ] && [ ! -L "$DOCKER_CONFIG_ROOT" ]
install -d -o root -g root -m 0700 "$DOCKER_CONFIG_ROOT"
[ "$(systemctl is-active docker)" = active ]
[ "$(systemctl is-enabled docker)" = enabled ]
[ "$(stat -c '%U|%G|%a|%h|%F' "$PAYMENT_ENV")" = 'root|root|600|1|regular file' ]
[ ! -e "$PAYMENT_UNIT" ] && [ ! -L "$PAYMENT_UNIT" ]
[ "$(systemctl show noteai-payment.service -p LoadState --value)" = not-found ]
[ "$(systemctl is-active noteai-payment.service 2>/dev/null || true)" = inactive ]
[ "$(systemctl is-enabled noteai-payment.service 2>/dev/null || true)" = disabled ]

readonly DOCKER=(/usr/bin/env "DOCKER_CONFIG=$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default)
"${DOCKER[@]}" version --format '{{.Server.Version}}' >/dev/null
"${DOCKER[@]}" info --format '{{.ServerVersion}}' >/dev/null
payment_container_ids="$("${DOCKER[@]}" container ls -aq --filter 'name=^/noteai-payment$')"
[ -z "$payment_container_ids" ]
containers_before="$("${DOCKER[@]}" container ls -aq --no-trunc | sort -u)"

image_present=false
image_config_match=false
image_role_match=false
image_entrypoint_match=false
image_cmd_match=false
if image_json="$("${DOCKER[@]}" image inspect "$PAYMENT_REF" 2>/dev/null)"; then
  image_present=true
  IMAGE_JSON="$image_json" PAYMENT_CONFIG="$PAYMENT_CONFIG" /usr/bin/python3 - <<'PY'
import json
import os

items = json.loads(os.environ["IMAGE_JSON"])
if len(items) != 1:
    raise SystemExit(11)
item = items[0]
if item.get("Id") != os.environ["PAYMENT_CONFIG"]:
    raise SystemExit(12)
config = item.get("Config") or {}
labels = config.get("Labels") or {}
environment = config.get("Env") or []
if labels.get("com.noteai.runtime.role") != "payment":
    raise SystemExit(13)
if config.get("Entrypoint") != ["/app/scripts/docker_entrypoint.sh"]:
    raise SystemExit(14)
if config.get("Cmd") != ["/app/scripts/render_start_payment.sh"]:
    raise SystemExit(15)
if "NOTEAI_RUNTIME_ROLE=payment" not in environment:
    raise SystemExit(16)
if "NOTEAI_PAYMENT_CALLBACK_ENABLED=0" not in environment:
    raise SystemExit(17)
PY
  image_config_match=true
  image_role_match=true
  image_entrypoint_match=true
  image_cmd_match=true
fi

for port in 8000 8001; do
  for round in 1 2 3; do
    PORT="$port" /usr/bin/python3 - <<'PY'
import http.client
import os

connection = http.client.HTTPConnection(
    "127.0.0.1", int(os.environ["PORT"]), timeout=3
)
connection.request("GET", "/health/live")
response = connection.getresponse()
body = response.read(2048)
connection.close()
if response.status != 200 or b'"status":"ok"' not in body.replace(b" ", b""):
    raise SystemExit(18)
PY
  done
done

containers_after="$("${DOCKER[@]}" container ls -aq --no-trunc | sort -u)"
[ "$containers_after" = "$containers_before" ]
[ "$(ss -Htan state established '( dport = :5432 or sport = :5432 )' | wc -l | tr -d ' ')" = 0 ]

printf '%s\n' "NOTEAI_ITEM24_PAYMENT_PREFLIGHT=OBSERVED schema=v1 payment_env_metadata_exact=true unit_absent=true payment_container_count=0 image_present=$image_present image_config_match=$image_config_match image_role_match=$image_role_match image_entrypoint_match=$image_entrypoint_match image_cmd_match=$image_cmd_match api_live_checks=6 database_connections=0 provider_calls=0 ledger_writes=0 persistent_host_mutation_count=0 task_root_residue=0 automatic_retry_allowed=false"
