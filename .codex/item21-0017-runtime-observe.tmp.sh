#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH

readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly TASK_ROOT='/run/noteai-item21-0017-runtime-observe-v1'
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly CONTAINER_NAME='noteai-i21-0017-runtime-observe-v1'
readonly CONTAINER_LABEL='com.noteai.task=PROD-FIRST-LAUNCH-DURABLE-AI-PROTECTED-CONTROL-001-runtime-observe'

created=0
attempted=0
completed=0

cleanup() {
  local ids label image
  if [ -d "$DOCKER_CONFIG_ROOT" ]; then
    ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || return 1
    if [ -n "$ids" ]; then
      [ "$attempted" -eq 1 ] || return 1
      [ "$(printf '%s\n' "$ids" | wc -l | tr -d ' ')" = '1' ] || return 1
      label="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$ids" --format '{{index .Config.Labels "com.noteai.task"}}')" || return 1
      image="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect "$ids" --format '{{.Image}}')" || return 1
      [ "com.noteai.task=$label" = "$CONTAINER_LABEL" ] || return 1
      [ "$image" = "$IMAGE_CONFIG" ] || return 1
      /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default rm -f "$ids" >/dev/null 2>&1 || return 1
      ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || return 1
      [ -z "$ids" ] || return 1
    fi
  fi
  if [ "$created" -eq 1 ]; then
    [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
    [ "$(stat -c '%u|%g|%a' "$TASK_ROOT")" = '0|0|700' ] || return 1
    rm -rf --one-file-system "$TASK_ROOT" || return 1
    [ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
  fi
}

on_exit() {
  local cleanup_ok=1
  if [ "$completed" -eq 1 ]; then return 0; fi
  cleanup >/dev/null 2>&1 || cleanup_ok=0
  trap - EXIT
  if [ "$cleanup_ok" -eq 1 ]; then
    printf '%s\n' 'NOTEAI_ITEM21_0017_RUNTIME_OBSERVE=FAIL incident_class=PRE_DATABASE cleanup=VERIFIED_ZERO database_connections=0 database_writes=0 secret_values_emitted=0 automatic_retry_allowed=false' >&2
    exit 3
  fi
  printf '%s\n' 'NOTEAI_ITEM21_0017_RUNTIME_OBSERVE=UNKNOWN incident_class=PRE_DATABASE cleanup=UNKNOWN database_connections=0 database_writes=0 secret_values_emitted=0 readback_required=true automatic_retry_allowed=false' >&2
  exit 4
}
trap on_exit EXIT

[ "$(id -u)" = '0' ]
for required in awk chmod docker env grep id mkdir python3 rm sha256sum stat timeout tr wc; do
  command -v "$required" >/dev/null 2>&1
done
[ -x /usr/bin/docker ] && [ -x /usr/bin/env ] && [ -x /usr/bin/timeout ]
[ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ]
mkdir -m 0700 "$TASK_ROOT"
created=1
mkdir -m 0700 "$DOCKER_CONFIG_ROOT"
printf '%s' '{}' >"$DOCKER_CONFIG_ROOT/config.json"
chmod 0600 "$DOCKER_CONFIG_ROOT/config.json"
/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default version >/dev/null 2>&1
/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default info >/dev/null 2>&1
/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default image inspect "$IMAGE_REF" --format '{{.Id}}' | grep -Fx "$IMAGE_CONFIG" >/dev/null
ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")"
[ -z "$ids" ]

attempted=1
set +e
observed="$({ /usr/bin/timeout --foreground --signal=TERM --kill-after=10s 120s \
  /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" \
  /usr/bin/docker --context=default run --rm -i \
    --name "$CONTAINER_NAME" --label "$CONTAINER_LABEL" \
    --pull never --network none --read-only --user 0:0 \
    --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 64 --memory 128m --cpus 0.25 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --entrypoint /usr/local/bin/python3.11 \
    "$IMAGE_REF" -I -B - <<'PY'
import hashlib
import json
import pathlib
import platform

result = {
    "status": "OBSERVED",
    "python": platform.python_version(),
    "python_error": "",
    "psycopg": "",
    "psycopg_error": "",
    "cryptography": "",
    "cryptography_error": "",
    "migration_count": -1,
    "migration_names_error": "",
    "migration_0017_sha256": "",
    "migration_0017_error": "",
    "network": "none",
    "database_connections": 0,
    "database_writes": 0,
    "secret_values_emitted": 0,
}
try:
    import importlib.metadata
    import psycopg
    from psycopg.rows import dict_row
    if not psycopg or not dict_row:
        raise RuntimeError("psycopg_import_contract")
    result["psycopg"] = importlib.metadata.version("psycopg")
except BaseException as exc:
    result["psycopg_error"] = type(exc).__name__
try:
    import importlib.metadata
    import cryptography
    from cryptography.hazmat.primitives.asymmetric import rsa
    if not cryptography or not rsa:
        raise RuntimeError("cryptography_import_contract")
    result["cryptography"] = importlib.metadata.version("cryptography")
except BaseException as exc:
    result["cryptography_error"] = type(exc).__name__
root = pathlib.Path("/app/model/migrations/postgres")
try:
    names = sorted(path.name for path in root.glob("*.sql"))
    result["migration_count"] = len(names)
except BaseException as exc:
    result["migration_names_error"] = type(exc).__name__
try:
    payload = (root / "0017_durable_ai_postgres_wakeup.sql").read_bytes()
    result["migration_0017_sha256"] = hashlib.sha256(payload).hexdigest()
except BaseException as exc:
    result["migration_0017_error"] = type(exc).__name__
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
PY
} 2>"$TASK_ROOT/container.stderr")"
rc=$?
set -e

if [ "$rc" -ne 0 ]; then
  stderr_bytes="$(stat -c '%s' "$TASK_ROOT/container.stderr")"
  stderr_sha="$(sha256sum "$TASK_ROOT/container.stderr" | awk '{print $1}')"
  stderr_observation="$(python3 -I -B - "$TASK_ROOT/container.stderr" "$rc" <<'PY'
import base64
import sys

with open(sys.argv[1], "rb") as handle:
    payload = handle.read(4097)
rc = int(sys.argv[2])
lowered = payload.lower()
if rc in (124, 137, 143):
    stderr_class = "TIMEOUT_OR_TERMINATION"
elif b"no such file or directory" in lowered:
    stderr_class = "EXEC_NOT_FOUND"
elif b"syntaxerror" in lowered:
    stderr_class = "PYTHON_SYNTAX"
elif b"traceback" in lowered:
    stderr_class = "PYTHON_EXCEPTION"
elif b"out of memory" in lowered or b"cannot allocate memory" in lowered:
    stderr_class = "OUT_OF_MEMORY"
elif b"error response from daemon" in lowered:
    stderr_class = "DOCKER_ENGINE"
elif not payload:
    stderr_class = "EMPTY"
else:
    stderr_class = "OTHER"
safe_ascii = len(payload) <= 4096 and all(
    byte in (9, 10, 13) or 32 <= byte <= 126 for byte in payload
)
sensitive_markers = (
    b"password", b"authorization:", b"bearer ", b"accesskey",
    b"securitytoken", b"postgresql://", b"postgres://",
)
safe = safe_ascii and not any(marker in lowered for marker in sensitive_markers)
encoded = base64.b64encode(payload).decode("ascii") if safe else "REDACTED"
print(stderr_class + "|" + encoded)
PY
)"
  IFS='|' read -r stderr_class stderr_safe_b64 <<<"$stderr_observation"
  cleanup
  printf '%s\n' "NOTEAI_ITEM21_0017_RUNTIME_OBSERVE=ENGINE_FAILURE incident_class=PRE_DATABASE diagnostic_container_attempted=1 diagnostic_container_residue=0 rc=$rc stderr_class=$stderr_class stderr_bytes=$stderr_bytes stderr_sha256=$stderr_sha stderr_safe_b64=$stderr_safe_b64 cleanup=VERIFIED_ZERO database_connections=0 database_writes=0 secret_values_emitted=0 automatic_retry_allowed=false"
  completed=1
  trap - EXIT
  exit 0
fi
[ ! -s "$TASK_ROOT/container.stderr" ]
python3 -I -B - "$observed" <<'PY'
import json
import sys
value = json.loads(sys.argv[1])
expected = {
    "status", "python", "python_error", "psycopg", "psycopg_error",
    "cryptography", "cryptography_error", "migration_count",
    "migration_names_error", "migration_0017_sha256",
    "migration_0017_error", "network", "database_connections",
    "database_writes", "secret_values_emitted",
}
if set(value) != expected or value["status"] != "OBSERVED":
    raise SystemExit(2)
print(json.dumps(value, sort_keys=True, separators=(",", ":")))
PY
ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")"
[ -z "$ids" ]
cleanup
printf '%s\n' 'NOTEAI_ITEM21_0017_RUNTIME_OBSERVE=COMPLETE cleanup=VERIFIED_ZERO database_connections=0 database_writes=0 secret_values_emitted=0 automatic_retry_allowed=false'
completed=1
trap - EXIT
