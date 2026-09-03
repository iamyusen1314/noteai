#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE PYTHONWARNINGS PYTHONINSPECT

readonly TASK_ROOT='/run/noteai-item21-worker-secret-source-v1'
readonly TOOL_ROOT='/run/noteai-item21-worker-secret-source-tools-v1'
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly INPUT_ROOT="$TASK_ROOT/input"
readonly OUTPUT_ROOT="$TASK_ROOT/output"
readonly MODULE_PATH="$TOOL_ROOT/production_secret_envelope.py"
readonly DRIVER_PATH="$TOOL_ROOT/source-driver.py"
readonly MODULE_SHA256='b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf'
readonly DRIVER_SHA256='ff9bdcfa6b8979848ff35e7d8c7c9c05450d9573d21eb220fbcc367d9ce1c3d2'
readonly WORKER_C_PUBLIC_SHA256='bf55278e59bc9911ab77a51c59f117e3afc575fd2c941c32d4bf2186fa8f94e0'
readonly WORKER_F_PUBLIC_SHA256='53abc24853f96a2882d756632d2f6781c211bbc3966a652d1cff50d090858863'
readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly C17='cad5ce35664f617c6e19f90a6159285ddf975594'
readonly CONTAINER_NAME='noteai-item21-worker-secret-source'
readonly CONTAINER_LABEL='worker-secret-source-v1'
readonly FIXED_PRESTART_ERROR="timeout: failed to run command 'docker_task': No such file or directory"

recovery_started=0
success=0

docker_task() {
  env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default "$@"
}

container_absent() {
  local ids=''
  ids="$(docker_task container ls -a --filter "name=^/$CONTAINER_NAME$" --format '{{.ID}}')" || return 1
  [ -z "$ids" ]
}

cleanup_container() {
  local ids='' label='' image=''
  set +e
  ids="$(docker_task container ls -a --filter "name=^/$CONTAINER_NAME$" --format '{{.ID}}' 2>/dev/null)"
  local list_rc=$?
  set -e
  [ "$list_rc" -eq 0 ] || return 1
  if [ -n "$ids" ]; then
    [ "$(printf '%s\n' "$ids" | sed '/^$/d' | wc -l | tr -d ' ')" = '1' ] || return 1
    label="$(docker_task container inspect "$CONTAINER_NAME" --format '{{index .Config.Labels "com.noteai.item21"}}' 2>/dev/null || true)"
    image="$(docker_task container inspect "$CONTAINER_NAME" --format '{{.Image}}' 2>/dev/null || true)"
    [ "$label" = "$CONTAINER_LABEL" ] && [ "$image" = "$IMAGE_CONFIG" ] || return 1
    docker_task container rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || return 1
  fi
  container_absent
}

on_exit() {
  local rc=$?
  if [ "$success" -eq 1 ] && [ "$rc" -eq 0 ]; then
    return 0
  fi
  if [ "$recovery_started" -eq 1 ]; then
    cleanup_container || true
    printf '%s\n' '{"automatic_retry_allowed":false,"encrypted_recovery_root_retained":true,"phase":"source_encrypt_recovery","readback_required":true,"status":"RECOVERY_UNKNOWN","tool_root_retained":true,"worker_stage_allowed":false}' >&2 || true
    exit 4
  fi
  printf '%s\n' '{"automatic_retry_allowed":false,"phase":"source_encrypt_recovery_precheck","status":"RECOVERY_PRECHECK_FAILED","worker_stage_allowed":false}' >&2 || true
  exit 3
}
trap on_exit EXIT

[ "$(id -u)" = '0' ]
[ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ]
[ "$(stat -c '%F|%u|%g|%a' "$TASK_ROOT")" = 'directory|0|0|700' ]
[ "$(find "$TASK_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)" = $'docker-config\nhelper.stderr\nhelper.stdout\ninput\noutput' ]
for directory in "$DOCKER_CONFIG_ROOT" "$INPUT_ROOT" "$OUTPUT_ROOT"; do
  [ "$(stat -c '%F|%u|%g|%a' "$directory")" = 'directory|0|0|700' ]
done
[ -z "$(find "$DOCKER_CONFIG_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]
[ "$(find "$INPUT_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)" = $'worker-c-public.pem\nworker-c-public.sha256\nworker-f-public.pem\nworker-f-public.sha256' ]
[ -z "$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]
for path in "$INPUT_ROOT"/* "$TASK_ROOT/helper.stdout" "$TASK_ROOT/helper.stderr"; do
  [ -f "$path" ] && [ ! -L "$path" ]
  [ "$(stat -c '%u|%g|%a|%h' "$path")" = '0|0|600|1' ]
done
[ ! -s "$TASK_ROOT/helper.stdout" ]
[ "$(cat "$TASK_ROOT/helper.stderr")" = "$FIXED_PRESTART_ERROR" ]
[ "$(stat -c '%s' "$TASK_ROOT/helper.stderr")" = '72' ]

[ -d "$TOOL_ROOT" ] && [ ! -L "$TOOL_ROOT" ]
[ "$(stat -c '%F|%u|%g|%a' "$TOOL_ROOT")" = 'directory|0|0|700' ]
[ "$(find "$TOOL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)" = $'production_secret_envelope.py\nsource-driver.py' ]
for path in "$MODULE_PATH" "$DRIVER_PATH"; do
  [ "$(stat -c '%F|%u|%g|%a|%h' "$path")" = 'regular file|0|0|600|1' ]
done
[ "$(sha256sum "$MODULE_PATH" | awk '{print $1}')" = "$MODULE_SHA256" ]
[ "$(sha256sum "$DRIVER_PATH" | awk '{print $1}')" = "$DRIVER_SHA256" ]

[ "$(cat "$INPUT_ROOT/worker-c-public.sha256")" = "$WORKER_C_PUBLIC_SHA256" ]
[ "$(cat "$INPUT_ROOT/worker-f-public.sha256")" = "$WORKER_F_PUBLIC_SHA256" ]
openssl_path="$(command -v openssl)"
[ -n "$openssl_path" ]
for host in worker-c worker-f; do
  pem="$INPUT_ROOT/$host-public.pem"
  expected="$WORKER_C_PUBLIC_SHA256"
  [ "$host" = 'worker-f' ] && expected="$WORKER_F_PUBLIC_SHA256"
  [ "$(timeout --foreground --signal=TERM --kill-after=5s 20s "$openssl_path" pkey -pubin -in "$pem" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" = "$expected" ]
done

for path in /etc/noteai/ai-worker.env /etc/noteai/private-storage.env; do
  [ "$(stat -c '%F|%u|%g|%a|%h' "$path")" = 'regular file|0|0|600|1' ]
  [ "$(stat -c '%s' "$path")" -gt 0 ]
  [ "$(stat -c '%s' "$path")" -le 16384 ]
done

[ "$(/usr/bin/systemctl is-active docker)" = 'active' ]
[ "$(/usr/bin/systemctl is-enabled docker)" = 'enabled' ]
[ "$(docker_task context inspect default --format '{{(index .Endpoints "docker").Host}}')" = 'unix:///var/run/docker.sock' ]
container_absent

python3 - "$DOCKER_CONFIG_ROOT" "$IMAGE_REF" "$IMAGE_CONFIG" "$C17" <<'PY'
import json
import subprocess
import sys

config_root, ref, image_config, commit = sys.argv[1:]
env = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LC_ALL": "C",
    "DOCKER_CONFIG": config_root,
}
completed = subprocess.run(
    ["/usr/bin/docker", "--context=default", "image", "inspect", ref],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    timeout=20,
)
if completed.returncode != 0:
    raise SystemExit(2)
rows = json.loads(completed.stdout.decode("utf-8"))
if not isinstance(rows, list) or len(rows) != 1:
    raise SystemExit(3)
row = rows[0]
cfg = row.get("Config") or {}
labels = cfg.get("Labels") or {}
rootfs = row.get("RootFS") or {}
if not (
    row.get("Id") == image_config
    and row.get("Os") == "linux"
    and row.get("Architecture") == "amd64"
    and (row.get("RepoDigests") or []).count(ref) == 1
    and isinstance(row.get("Size"), int) and row.get("Size") > 0
    and isinstance(rootfs.get("Layers"), list) and len(rootfs["Layers"]) > 0
    and cfg.get("User") == "noteai"
    and cfg.get("Entrypoint") == ["/app/scripts/docker_entrypoint.sh"]
    and cfg.get("Cmd") == ["python", "durable_ai_worker.py", "--once"]
    and cfg.get("WorkingDir") == "/app/model"
    and (cfg.get("Healthcheck") or {}).get("Test") == ["NONE"]
    and labels.get("org.opencontainers.image.revision") == commit
    and labels.get("com.noteai.runtime.role") == "ai-worker"
    and (cfg.get("Env") or []).count("NOTEAI_DURABLE_AI_SUSPENDED=1") == 1
    and (cfg.get("Env") or []).count("NOTEAI_RUNTIME_ROLE=ai-worker") == 1
):
    raise SystemExit(4)
PY

recovery_started=1
set +e
helper_combined="$(/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 180s \
  /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default run \
  --rm --pull never --name "$CONTAINER_NAME" \
  --label "com.noteai.item21=$CONTAINER_LABEL" \
  --network none --read-only --user 0:0 --cap-drop ALL \
  --security-opt no-new-privileges:true --memory 256m --memory-swap 256m \
  --cpus 1 --pids-limit 64 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1048576 \
  --mount type=bind,src=/etc/noteai/ai-worker.env,dst=/input/ai-worker.env,readonly \
  --mount type=bind,src=/etc/noteai/private-storage.env,dst=/input/private-storage.env,readonly \
  --mount type=bind,src="$INPUT_ROOT/worker-c-public.pem",dst=/input/worker-c-public.pem,readonly \
  --mount type=bind,src="$INPUT_ROOT/worker-c-public.sha256",dst=/input/worker-c-public.sha256,readonly \
  --mount type=bind,src="$INPUT_ROOT/worker-f-public.pem",dst=/input/worker-f-public.pem,readonly \
  --mount type=bind,src="$INPUT_ROOT/worker-f-public.sha256",dst=/input/worker-f-public.sha256,readonly \
  --mount type=bind,src="$MODULE_PATH",dst=/task/production_secret_envelope.py,readonly \
  --mount type=bind,src="$DRIVER_PATH",dst=/task/source-driver.py,readonly \
  --mount type=bind,src="$OUTPUT_ROOT",dst=/output \
  --entrypoint python "$IMAGE_REF" -I /task/source-driver.py \
  2>&1)"
helper_rc=$?
set -e
[ "$helper_rc" -eq 0 ]
container_absent
[ "$helper_combined" = '{"database_payload_unchanged":true,"derived_role_replacement_count":1,"envelope_count":4,"plaintext_output_count":0,"source_file_count":2,"status":"ENCRYPTED","unchanged_storage_key_count":6,"worker_database_payloads_equal":true,"worker_storage_payloads_equal":true}' ]

python3 - "$OUTPUT_ROOT" <<'PY'
import base64
import json
import os
import stat
import sys

root = sys.argv[1]
expected = {
    "worker-c-database.envelope.json",
    "worker-c-private_storage.envelope.json",
    "worker-f-database.envelope.json",
    "worker-f-private_storage.envelope.json",
}
if set(os.listdir(root)) != expected:
    raise SystemExit(2)
seen = set()
for name in sorted(expected):
    path = os.path.join(root, name)
    row = os.lstat(path)
    if not (
        stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o600
        and row.st_nlink == 1
        and 0 < row.st_size <= 12288
    ):
        raise SystemExit(3)
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw in seen:
        raise SystemExit(4)
    seen.add(raw)
    envelope = json.loads(raw.decode("ascii"))
    if set(envelope) != {"schema_version", "algorithm", "wrapped_key", "nonce", "ciphertext"}:
        raise SystemExit(5)
    if envelope.get("schema_version") != 1 or envelope.get("algorithm") != "RSA-OAEP-SHA256+AES-256-GCM":
        raise SystemExit(6)
    if len(base64.b64decode(envelope["wrapped_key"], validate=True)) != 384:
        raise SystemExit(7)
    if len(base64.b64decode(envelope["nonce"], validate=True)) != 12:
        raise SystemExit(8)
    if len(base64.b64decode(envelope["ciphertext"], validate=True)) < 16:
        raise SystemExit(9)
PY

wc_db="$(base64 -w0 "$OUTPUT_ROOT/worker-c-database.envelope.json")"
wc_storage="$(base64 -w0 "$OUTPUT_ROOT/worker-c-private_storage.envelope.json")"
wf_db="$(base64 -w0 "$OUTPUT_ROOT/worker-f-database.envelope.json")"
wf_storage="$(base64 -w0 "$OUTPUT_ROOT/worker-f-private_storage.envelope.json")"

result="$(printf '{"ai_provider_call_count":0,"application_container_start_count":0,"automatic_retry_allowed":false,"database_connection_count":0,"database_envelope_count":2,"derived_role_replacement_count":1,"encrypted_recovery_root_retained":true,"encryption_task_container_start_count":1,"object_store_call_count":0,"plaintext_output_count":0,"provider_control_plane_mutation_count":0,"recovered_from_prestart_failure":true,"registry_call_count":0,"source_file_count":2,"status":"RECOVERED_ENCRYPTED","storage_envelope_count":2,"terminal_cleanup_pending":true,"tool_root_retained":true,"unchanged_storage_key_count":6,"worker_c_database_envelope_b64":"%s","worker_c_storage_envelope_b64":"%s","worker_f_database_envelope_b64":"%s","worker_f_storage_envelope_b64":"%s","worker_payloads_equal":true}\n' "$wc_db" "$wc_storage" "$wf_db" "$wf_storage")"
[ "${#result}" -le 12000 ]
printf '%s' "$result"
success=1
trap - EXIT
