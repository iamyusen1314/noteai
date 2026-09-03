#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH

readonly EXPECTED_INSTANCE='i-wz9j36od3nf2b1uw7bvg'
readonly EXPECTED_ROLE='noteai-storage-api-20260729-c60cc608'
readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly C17='cad5ce35664f617c6e19f90a6159285ddf975594'
readonly TASK_ROOT='/run/noteai-item21-0017-runtime-preflight-noteai-v1'
readonly SOURCE_ROOT='/run/noteai-item21-protected-control-source-v1'
readonly CONTROL_ROOT='/run/noteai-durable-ai-control'
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly CONTAINER_NAME='noteai-i21-0017-runtime-preflight-noteai-v1'
readonly CONTAINER_LABEL='com.noteai.task=PROD-FIRST-LAUNCH-DURABLE-AI-PROTECTED-CONTROL-001-runtime-preflight-noteai'

created=0
completed=0
known_failure=0
failure_phase='unexpected'
container_attempted=0

fail() {
  known_failure=1
  failure_phase="$1"
  exit 3
}

cleanup_container() {
  local ids label image
  ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || return 1
  if [ -n "$ids" ]; then
    [ "$container_attempted" -eq 1 ] || return 1
    [ "$(printf '%s\n' "$ids" | wc -l | tr -d ' ')" = '1' ] || return 1
    label="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$ids" --format '{{index .Config.Labels "com.noteai.task"}}')" || return 1
    image="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$ids" --format '{{.Image}}')" || return 1
    [ "com.noteai.task=$label" = "$CONTAINER_LABEL" ] || return 1
    [ "$image" = "$IMAGE_CONFIG" ] || return 1
    /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default rm -f "$ids" >/dev/null 2>&1 || return 1
    ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || return 1
    [ -z "$ids" ] || return 1
  fi
  return 0
}

cleanup_root() {
  if [ "$created" -eq 1 ]; then
    [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
    [ "$(stat -c '%u|%g|%a' "$TASK_ROOT")" = '0|0|700' ] || return 1
    rm -rf --one-file-system "$TASK_ROOT" || return 1
    [ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
  fi
  return 0
}

on_exit() {
  local rc=$?
  local cleanup_ok=1
  if [ "$completed" -eq 1 ]; then
    return 0
  fi
  if [ -d "$DOCKER_CONFIG_ROOT" ]; then
    cleanup_container >/dev/null 2>&1 || cleanup_ok=0
  fi
  cleanup_root >/dev/null 2>&1 || cleanup_ok=0
  if [ "$known_failure" -eq 1 ] && [ "$cleanup_ok" -eq 1 ]; then
    printf '%s\n' "NOTEAI_ITEM21_0017_RUNTIME_PREFLIGHT=FAIL incident_class=PRE_DATABASE phase=$failure_phase cleanup=VERIFIED_ZERO database_connections=0 database_writes=0 source_secret_reads=0 provider_control_plane_mutations=0 registry_calls=0 automatic_retry_allowed=false" >&2
    trap - EXIT
    exit 3
  fi
  printf '%s\n' "NOTEAI_ITEM21_0017_RUNTIME_PREFLIGHT=UNKNOWN incident_class=PRE_DATABASE phase=$failure_phase cleanup=UNKNOWN readback_required=true database_connections=0 database_writes=0 source_secret_reads=0 provider_control_plane_mutations=0 registry_calls=0 automatic_retry_allowed=false" >&2
  trap - EXIT
  exit 4
}
trap on_exit EXIT

[ "$(id -u)" = '0' ] || fail root_required
for required in docker systemctl stat sha256sum sort awk ss python3 timeout; do
  command -v "$required" >/dev/null 2>&1 || fail required_tool
done
[ -x /usr/bin/docker ] && [ -x /usr/bin/env ] && [ -x /usr/bin/timeout ] || fail required_absolute_tool
[ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || fail task_root_present
[ ! -e "$SOURCE_ROOT" ] && [ ! -L "$SOURCE_ROOT" ] || fail source_root_present
[ ! -e "$CONTROL_ROOT" ] && [ ! -L "$CONTROL_ROOT" ] || fail control_root_present

api_env_meta="$(stat -c '%F|%u|%g|%a|%h' /etc/noteai/api.env 2>/dev/null)" || fail api_env_metadata
[ "$api_env_meta" = 'regular file|0|0|600|1' ] || fail api_env_metadata

identity="$({ python3 -I -B - <<'PY'
import json
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
if roles != ["noteai-storage-api-20260729-c60cc608"]:
    raise SystemExit(2)
if values[0] != "i-wz9j36od3nf2b1uw7bvg":
    raise SystemExit(2)
print("HOST_IDENTITY_EXACT")
PY
} 2>/dev/null)" || fail host_identity
[ "$identity" = 'HOST_IDENTITY_EXACT' ] || fail host_identity

mkdir -m 0700 "$TASK_ROOT"
created=1
mkdir -m 0700 "$DOCKER_CONFIG_ROOT"
printf '%s' '{}' >"$DOCKER_CONFIG_ROOT/config.json"
chmod 0600 "$DOCKER_CONFIG_ROOT/config.json"

[ "$(systemctl is-active docker)" = 'active' ] || fail docker_active
[ "$(systemctl is-enabled docker)" = 'enabled' ] || fail docker_enabled
/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default version >/dev/null 2>&1 || fail isolated_docker_version
/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default info >/dev/null 2>&1 || fail isolated_docker_info
container_rows="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default ps -a --format '{{.Names}}|{{.State}}' | sort)" || fail container_query
[ "$container_rows" = $'noteai-admin-c|running\nnoteai-api-c|running' ] || fail api_container_set
existing_task_ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || fail task_container_query
[ -z "$existing_task_ids" ] || fail task_container_present

before_containers="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect noteai-api-c noteai-admin-c --format '{{.Id}}|{{.State.Status}}|{{.RestartCount}}|{{.Image}}|{{json .HostConfig.PortBindings}}' | sort | sha256sum | awk '{print $1}')" || fail api_fingerprint
before_images="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default image ls -aq --no-trunc | sort -u | sha256sum | awk '{print $1}')" || fail image_set

/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default image inspect "$IMAGE_REF" >"$TASK_ROOT/image.json" 2>/dev/null || fail c17_missing
python3 -I -B - "$TASK_ROOT/image.json" <<'PY' || fail c17_contract
import json
import sys
image = json.load(open(sys.argv[1], "r"))[0]
config = image.get("Config") or {}
labels = config.get("Labels") or {}
checks = (
    image.get("Id") == "sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95",
    image.get("Os") == "linux",
    image.get("Architecture") == "amd64",
    config.get("User") == "noteai",
    config.get("Entrypoint") == ["/app/scripts/docker_entrypoint.sh"],
    config.get("Cmd") == ["python", "durable_ai_worker.py", "--once"],
    config.get("WorkingDir") == "/app/model",
    (config.get("Healthcheck") or {}).get("Test") == ["NONE"],
    labels.get("org.opencontainers.image.revision") == "cad5ce35664f617c6e19f90a6159285ddf975594",
    labels.get("com.noteai.runtime.role") == "ai-worker",
    image.get("RepoDigests", []).count("noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b") == 1,
    config.get("Env", []).count("NOTEAI_DURABLE_AI_SUSPENDED=1") == 1,
    config.get("Env", []).count("NOTEAI_RUNTIME_ROLE=ai-worker") == 1,
    int(image.get("Size") or 0) > 0,
    len((image.get("RootFS") or {}).get("Layers") or []) > 0,
)
if not all(checks):
    raise SystemExit(2)
PY
rm -f "$TASK_ROOT/image.json"

db_before="$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" || fail db_socket_query
[ "$db_before" = '0' ] || fail database_connection_present

for port in 8000 8001; do
  python3 -I -B - "$port" <<'PY' || fail api_live
import http.client
import sys
port = int(sys.argv[1])
for _ in range(3):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", "/health/live", headers={"Connection": "close"})
    response = conn.getresponse()
    response.read(4097)
    conn.close()
    if response.status != 200:
        raise SystemExit(2)
PY
done

container_attempted=1
set +e
runtime_result="$({ /usr/bin/timeout --foreground --signal=TERM --kill-after=10s 120s \
  /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" \
  /usr/bin/docker --context=default run --rm -i \
    --name "$CONTAINER_NAME" \
    --label "$CONTAINER_LABEL" \
    --pull never --network none --read-only --user noteai:noteai \
    --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 64 --memory 128m --cpus 0.25 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --entrypoint /usr/local/bin/python3.11 \
    "$IMAGE_REF" -I -B - <<'PY'
import importlib.metadata
import json
import pathlib
import platform
import cryptography
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg.rows import dict_row

# The full accepted migration set is verified again by source_contract after
# the overlay is assembled.  This preflight binds the runtime and exact 0017.
migration_root = pathlib.Path("/app/model/migrations/postgres")
names = sorted(path.name for path in migration_root.glob("*.sql"))
expected_names = [
    "0001_initial.sql", "0002_shared_runtime_state.sql", "0003_market_timing.sql",
    "0004_xhs_freshness.sql", "0005_idempotency_requests.sql",
    "0006_model_usage_records.sql", "0007_ai_operations.sql",
    "0008_ai_operation_admissions.sql", "0009_account_security_compliance.sql",
    "0010_tracking_execution_contract.sql", "0011_trends_execution_contract.sql",
    "0012_durable_ai_execution_contract.sql", "0013_private_storage_recovery_contract.sql",
    "0014_payment_execution_contract.sql", "0015_admin_runtime_contract.sql",
    "0016_admin_runtime_role_collision.sql", "0017_durable_ai_postgres_wakeup.sql",
]
payload = (migration_root / "0017_durable_ai_postgres_wakeup.sql").read_bytes()
checks = {
    "python": platform.python_version() == "3.11.15",
    "psycopg": bool(psycopg) and bool(dict_row) and importlib.metadata.version("psycopg") == "3.3.4",
    "cryptography": bool(cryptography) and bool(rsa) and importlib.metadata.version("cryptography") == "50.0.0",
    "migration_names": names == expected_names,
    "migration_0017": __import__("hashlib").sha256(payload).hexdigest() == "a73cbefd853cefe7b56c42bed2c5a7f0ba1626e57755c6f9464629b49c42cbbe",
}
for code, name in enumerate((
    "python", "psycopg", "cryptography", "migration_names", "migration_0017",
), start=11):
    if not checks[name]:
        raise SystemExit(code)
print(json.dumps({
    "status": "RUNTIME_EXACT",
    "python": "3.11.15",
    "psycopg": "3.3.4",
    "cryptography": "50.0.0",
    "migration_count": 17,
    "migration_0017_exact": True,
    "network": "none",
    "database_connections": 0,
    "database_writes": 0,
    "source_secret_reads": 0,
}, sort_keys=True, separators=(",", ":")))
PY
} 2>"$TASK_ROOT/runtime.stderr")"
runtime_rc=$?
set -e
case "$runtime_rc" in
  0) ;;
  11) fail runtime_python ;;
  12) fail runtime_psycopg ;;
  13) fail runtime_cryptography ;;
  14) fail runtime_migration_names ;;
  15) fail runtime_migration_0017 ;;
  124|137|143) fail runtime_timeout_or_termination ;;
  125|126|127) fail runtime_engine ;;
  *) fail runtime_container ;;
esac
[ ! -s "$TASK_ROOT/runtime.stderr" ] || fail runtime_stderr
[ "$runtime_result" = '{"cryptography":"50.0.0","database_connections":0,"database_writes":0,"migration_0017_exact":true,"migration_count":17,"network":"none","psycopg":"3.3.4","python":"3.11.15","source_secret_reads":0,"status":"RUNTIME_EXACT"}' ] || fail runtime_result

task_ids_after="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || fail task_container_readback
[ -z "$task_ids_after" ] || fail task_container_residue

for port in 8000 8001; do
  python3 -I -B - "$port" <<'PY' || fail api_live_readback
import http.client
import sys
port = int(sys.argv[1])
for _ in range(3):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", "/health/live", headers={"Connection": "close"})
    response = conn.getresponse()
    response.read(4097)
    conn.close()
    if response.status != 200:
        raise SystemExit(2)
PY
done

after_containers="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect noteai-api-c noteai-admin-c --format '{{.Id}}|{{.State.Status}}|{{.RestartCount}}|{{.Image}}|{{json .HostConfig.PortBindings}}' | sort | sha256sum | awk '{print $1}')" || fail api_fingerprint_readback
[ "$after_containers" = "$before_containers" ] || fail api_fingerprint_drift
after_images="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default image ls -aq --no-trunc | sort -u | sha256sum | awk '{print $1}')" || fail image_set_readback
[ "$after_images" = "$before_images" ] || fail image_set_drift
db_after="$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" || fail db_socket_readback
[ "$db_after" = '0' ] || fail database_connection_after

cleanup_root || fail cleanup
printf '%s\n' 'NOTEAI_ITEM21_0017_RUNTIME_PREFLIGHT=PASS host=API-C runtime_exact=true python=3.11.15 psycopg=3.3.4 cryptography=50.0.0 migration_count=17 migration_0017_exact=true diagnostic_container_starts=1 diagnostic_container_residue=0 api_live_checks=12 api_container_drift=0 image_set_drift=0 database_connections=0 database_writes=0 source_secret_reads=0 metadata_http_requests=3 provider_control_plane_mutations=0 registry_calls=0 automatic_retry_allowed=false'
completed=1
trap - EXIT
