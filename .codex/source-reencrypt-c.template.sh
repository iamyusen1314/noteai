#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH

readonly TASK_ROOT='/run/noteai-item21-worker-secret-source-rekey-c-v1'
readonly TOOL_ROOT='/run/noteai-item21-worker-secret-source-tools-v1'
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly INPUT_ROOT="$TASK_ROOT/input"
readonly OUTPUT_ROOT="$TASK_ROOT/output"
readonly MODULE_PATH="$TOOL_ROOT/production_secret_envelope.py"
readonly SOURCE_DRIVER_PATH="$TOOL_ROOT/source-driver.py"
readonly DRIVER_PATH="$TASK_ROOT/source-reencrypt-c-driver.py"
readonly MODULE_SHA256='b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf'
readonly SOURCE_DRIVER_SHA256='ff9bdcfa6b8979848ff35e7d8c7c9c05450d9573d21eb220fbcc367d9ce1c3d2'
readonly DRIVER_SHA256='ede68c0fdc3400d5811595b7493039566afac29a281e60f4400bb59366ebbd99'
readonly IMAGE_REF='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b'
readonly IMAGE_CONFIG='sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95'
readonly C17='cad5ce35664f617c6e19f90a6159285ddf975594'
readonly API_ROLE='noteai-storage-api-20260729-c60cc608'
readonly CONTAINER_NAME='noteai-item21-worker-secret-source-rekey-c'
readonly CONTAINER_LABEL='worker-secret-source-rekey-c-v1'
readonly API_INSTANCE_ID='i-wz9j36od3nf2b1uw7bvg'
readonly WORKER_C_PUBLIC_SHA256='@@WORKER_C_PUBLIC_SHA256@@'
readonly WORKER_C_PUBLIC_B64='@@WORKER_C_PUBLIC_B64@@'

created=0
container_started=0
encrypt_started=0
success=0
cleanup_ok=0
recovery_ready=0

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
  if [ "$container_started" -eq 1 ]; then
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
  fi
  container_absent
}

cleanup() {
  cleanup_container || return 1
  if [ "$created" -eq 1 ]; then
    [ "$TASK_ROOT" = '/run/noteai-item21-worker-secret-source-rekey-c-v1' ] || return 1
    rm -rf -- "$TASK_ROOT" || return 1
  fi
  [ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
  cleanup_ok=1
}

on_exit() {
  local rc=$?
  if [ "$success" -eq 1 ] && [ "$rc" -eq 0 ]; then
    return 0
  fi
  if [ "$encrypt_started" -eq 1 ]; then
    cleanup_container || true
    printf '{"automatic_retry_allowed":false,"encrypted_recovery_root_retained":%s,"phase":"source_reencrypt_c","readback_required":true,"status":"UNKNOWN","tool_root_retained":true}\n' "$([ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] && printf true || printf false)" >&2 || true
    exit 4
  fi
  cleanup || true
  if [ "$cleanup_ok" -ne 1 ]; then
    printf '%s\n' '{"automatic_retry_allowed":false,"phase":"pre_reencrypt_c","readback_required":true,"status":"UNKNOWN","tool_root_retained":true}' >&2 || true
    exit 4
  fi
  printf '%s\n' '{"automatic_retry_allowed":false,"cleanup":"VERIFIED_ZERO","phase":"pre_reencrypt_c","status":"FAIL","tool_root_retained":true}' >&2 || true
  exit 3
}
trap on_exit EXIT

[ "$(id -u)" = '0' ]
[ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ]
[ -d "$TOOL_ROOT" ] && [ ! -L "$TOOL_ROOT" ]
[ "$(stat -c '%F|%u|%g|%a' "$TOOL_ROOT")" = 'directory|0|0|700' ]
[ "$(find "$TOOL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)" = $'production_secret_envelope.py\nsource-driver.py' ]
for path in "$MODULE_PATH" "$SOURCE_DRIVER_PATH"; do
  [ "$(stat -c '%F|%u|%g|%a|%h' "$path")" = 'regular file|0|0|600|1' ]
done
[ "$(sha256sum "$MODULE_PATH" | awk '{print $1}')" = "$MODULE_SHA256" ]
[ "$(sha256sum "$SOURCE_DRIVER_PATH" | awk '{print $1}')" = "$SOURCE_DRIVER_SHA256" ]

python3 - "$API_INSTANCE_ID" "$API_ROLE" <<'PY'
import base64
import json
import os
import stat
import sys
import urllib.request

expected, expected_role = sys.argv[1:]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
token_request = urllib.request.Request(
    "http://100.100.100.200/latest/api/token",
    headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"},
    method="PUT",
)
with opener.open(token_request, timeout=3) as response:
    token = response.read(512).decode("ascii").strip()
if not token or len(token) > 256:
    raise SystemExit(2)
def read(path):
    request = urllib.request.Request(
        "http://100.100.100.200/latest/meta-data/" + path,
        headers={"X-aliyun-ecs-metadata-token": token},
    )
    with opener.open(request, timeout=3) as response:
        payload = response.read(4096)
    if len(payload) >= 4096:
        raise SystemExit(3)
    return payload.decode("ascii").strip()
if read("instance-id") != expected:
    raise SystemExit(4)
root = os.lstat("/etc/noteai")
if not (
    stat.S_ISDIR(root.st_mode)
    and not stat.S_ISLNK(root.st_mode)
    and root.st_uid == 0 and root.st_gid == 0
    and stat.S_IMODE(root.st_mode) & 0o022 == 0
):
    raise SystemExit(5)
paths = ("/etc/noteai/ai-worker.env", "/etc/noteai/private-storage.env")
sizes = []
for path in paths:
    row = os.lstat(path)
    if not (
        stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o600
        and row.st_nlink == 1
        and 0 < row.st_size <= 16384
    ):
        raise SystemExit(6)
    sizes.append(row.st_size)
def b64_size(size):
    return 4 * ((size + 2) // 3)
def envelope_outer_size(host, kind, raw_size):
    protected = json.dumps({
        "schema_version": 1,
        "task_id": "PROD-FIRST-LAUNCH-DURABLE-AI-WORKER-SECRETS-001",
        "host": host,
        "public_key_sha256": "0" * 64,
        "payload_kind": kind,
        "payload_sha256": "0" * 64,
        "payload_b64": "A" * b64_size(raw_size),
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    envelope = json.dumps({
        "schema_version": 1,
        "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
        "wrapped_key": "A" * 512,
        "nonce": "A" * 16,
        "ciphertext": "A" * b64_size(len(protected) + 16),
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    return b64_size(len(envelope))
database_outer = envelope_outer_size("Worker-C", "database", sizes[0])
storage_outer = envelope_outer_size("Worker-C", "private_storage", sizes[1] + 1)
projected = json.dumps({
    "ai_provider_call_count": 0,
    "application_container_start_count": 0,
    "automatic_retry_allowed": False,
    "database_connection_count": 0,
    "database_envelope_count": 1,
    "derived_role_replacement_count": 1,
    "encryption_task_container_start_count": 1,
    "encrypted_recovery_root_retained": True,
    "metadata_identity_check_count": 1,
    "object_store_call_count": 0,
    "plaintext_output_count": 0,
    "provider_control_plane_mutation_count": 0,
    "registry_call_count": 0,
    "source_file_count": 2,
    "status": "REENCRYPTED_C",
    "storage_envelope_count": 1,
    "terminal_cleanup_pending": True,
    "tool_root_retained": True,
    "unchanged_storage_key_count": 6,
    "worker_c_database_envelope_b64": "A" * database_outer,
    "worker_c_storage_envelope_b64": "A" * storage_outer,
    "worker_f_artifact_read_count": 0,
    "worker_f_artifact_write_count": 0,
}, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
if len(projected) > 12000:
    raise SystemExit(10)
raw = open(paths[1], "rb").read()
rows = {}
for line in raw.splitlines():
    if not line or line.startswith(b"#") or line.startswith(b"export ") or b"=" not in line:
        raise SystemExit(7)
    key, value = line.split(b"=", 1)
    if key in rows:
        raise SystemExit(8)
    rows[key] = value
role = rows.get(b"NOTEAI_OSS_RAM_ROLE", b"")
roles = [value for value in read("ram/security-credentials/").splitlines() if value]
if roles != [expected_role] or role.decode("utf-8") != expected_role:
    raise SystemExit(9)
PY

mkdir -m 0700 "$TASK_ROOT"
created=1
mkdir -m 0700 "$DOCKER_CONFIG_ROOT" "$INPUT_ROOT" "$OUTPUT_ROOT"
chown 0:0 "$TASK_ROOT" "$DOCKER_CONFIG_ROOT" "$INPUT_ROOT" "$OUTPUT_ROOT"

printf '%s' "$WORKER_C_PUBLIC_B64" | base64 -d > "$INPUT_ROOT/worker-c-public.pem"
printf '%s\n' "$WORKER_C_PUBLIC_SHA256" > "$INPUT_ROOT/worker-c-public.sha256"
chmod 0600 "$INPUT_ROOT"/*
chown 0:0 "$INPUT_ROOT"/*

python3 -B - "$SOURCE_DRIVER_PATH" "$DRIVER_PATH" "$SOURCE_DRIVER_SHA256" "$DRIVER_SHA256" <<'PY'
import hashlib
import os
import stat
import sys

source_path, target_path, source_sha, target_sha = sys.argv[1:]
row = os.lstat(source_path)
if not (
    stat.S_ISREG(row.st_mode)
    and not stat.S_ISLNK(row.st_mode)
    and row.st_uid == 0 and row.st_gid == 0
    and stat.S_IMODE(row.st_mode) == 0o600
    and row.st_nlink == 1
):
    raise SystemExit(2)
with open(source_path, "rb") as handle:
    source = handle.read()
if hashlib.sha256(source).hexdigest() != source_sha:
    raise SystemExit(3)

old_public = b'''PUBLIC_KEYS = {
    "Worker-C": (
        Path("/input/worker-c-public.pem"),
        Path("/input/worker-c-public.sha256"),
    ),
    "Worker-F": (
        Path("/input/worker-f-public.pem"),
        Path("/input/worker-f-public.sha256"),
    ),
}
'''
new_public = b'''PUBLIC_KEY = (
    Path("/input/worker-c-public.pem"),
    Path("/input/worker-c-public.sha256"),
)
'''
old_action = b'''    observed_hashes = set()
    for host in ("Worker-C", "Worker-F"):
        public_path, hash_path = PUBLIC_KEYS[host]
        expected_hash = validated_public(module, host, public_path, hash_path)
        if expected_hash in observed_hashes:
            raise FixedError("public_key_reuse")
        observed_hashes.add(expected_hash)
        for kind, raw in (("database", database), ("private_storage", derived_storage)):
            protected = protected_payload(host, expected_hash, kind, raw)
            envelope = module.encrypt_payload(protected, public_path)
            if not (0 < len(envelope) <= 12288):
                raise FixedError("envelope_size")
            output = Path("/output/{}-{}.envelope.json".format(host.lower().replace("-", "-"), kind))
            write_private(output, envelope)
            output_count += 1
    print(json.dumps({
        "status": "ENCRYPTED",
        "source_file_count": 2,
        "derived_role_replacement_count": 1,
        "unchanged_storage_key_count": 6,
        "envelope_count": output_count,
        "database_payload_unchanged": True,
        "worker_database_payloads_equal": True,
        "worker_storage_payloads_equal": True,
        "plaintext_output_count": 0,
    }, sort_keys=True, separators=(",", ":")))
'''
new_action = b'''    public_path, hash_path = PUBLIC_KEY
    expected_hash = validated_public(module, "Worker-C", public_path, hash_path)
    for kind, raw in (("database", database), ("private_storage", derived_storage)):
        protected = protected_payload("Worker-C", expected_hash, kind, raw)
        envelope = module.encrypt_payload(protected, public_path)
        if not (0 < len(envelope) <= 12288):
            raise FixedError("envelope_size")
        output = Path("/output/worker-c-{}.envelope.json".format(kind))
        write_private(output, envelope)
        output_count += 1
    print(json.dumps({
        "status": "REENCRYPTED_C",
        "source_file_count": 2,
        "derived_role_replacement_count": 1,
        "unchanged_storage_key_count": 6,
        "envelope_count": output_count,
        "database_payload_unchanged": True,
        "worker_c_payload_count": 2,
        "plaintext_output_count": 0,
    }, sort_keys=True, separators=(",", ":")))
'''
if source.count(old_public) != 1 or source.count(old_action) != 1:
    raise SystemExit(4)
if source.count(new_public) != 0 or source.count(new_action) != 0:
    raise SystemExit(5)
derived = source.replace(old_public, new_public, 1).replace(old_action, new_action, 1)
if hashlib.sha256(derived).hexdigest() != target_sha:
    raise SystemExit(6)
if derived.replace(new_action, old_action, 1).replace(new_public, old_public, 1) != source:
    raise SystemExit(7)
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
descriptor = os.open(target_path, flags, 0o600)
try:
    os.fchmod(descriptor, 0o600)
    os.fchown(descriptor, 0, 0)
    offset = 0
    while offset < len(derived):
        written = os.write(descriptor, derived[offset:])
        if written <= 0:
            raise SystemExit(8)
        offset += written
    os.fsync(descriptor)
    final = os.fstat(descriptor)
    if not (
        stat.S_ISREG(final.st_mode)
        and final.st_uid == 0 and final.st_gid == 0
        and stat.S_IMODE(final.st_mode) == 0o600
        and final.st_nlink == 1
        and final.st_size == len(derived)
    ):
        raise SystemExit(9)
finally:
    os.close(descriptor)
PY
[ "$(sha256sum "$DRIVER_PATH" | awk '{print $1}')" = "$DRIVER_SHA256" ]

[ "$(/usr/bin/systemctl is-active docker)" = 'active' ]
[ "$(/usr/bin/systemctl is-enabled docker)" = 'enabled' ]
[ -z "$(find "$DOCKER_CONFIG_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]
context_host="$(docker_task context inspect default --format '{{(index .Endpoints "docker").Host}}')"
[ "$context_host" = 'unix:///var/run/docker.sock' ]
container_absent

python3 - "$DOCKER_CONFIG_ROOT" "$IMAGE_REF" "$IMAGE_CONFIG" "$C17" <<'PY'
import json
import os
import subprocess
import sys
config_root, ref, image_config, commit = sys.argv[1:]
env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "DOCKER_CONFIG": config_root}
completed = subprocess.run(
    ["/usr/bin/docker", "--context=default", "image", "inspect", ref],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
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

helper_output="$TASK_ROOT/helper.stdout"
helper_error="$TASK_ROOT/helper.stderr"
encrypt_started=1
container_started=1
set +e
/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 180s \
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
  --mount type=bind,src="$MODULE_PATH",dst=/task/production_secret_envelope.py,readonly \
  --mount type=bind,src="$DRIVER_PATH",dst=/task/source-driver.py,readonly \
  --mount type=bind,src="$OUTPUT_ROOT",dst=/output \
  --entrypoint python "$IMAGE_REF" -I /task/source-driver.py \
  >"$helper_output" 2>"$helper_error"
helper_rc=$?
set -e
[ "$helper_rc" -eq 0 ]
container_absent
container_started=0
[ "$(cat "$helper_output")" = '{"database_payload_unchanged":true,"derived_role_replacement_count":1,"envelope_count":2,"plaintext_output_count":0,"source_file_count":2,"status":"REENCRYPTED_C","unchanged_storage_key_count":6,"worker_c_payload_count":2}' ]
[ "$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')" = '2' ]

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
}
if set(os.listdir(root)) != expected:
    raise SystemExit(2)
seen = set()
for name in sorted(expected):
    path = os.path.join(root, name)
    row = os.lstat(path)
    if not (
        stat.S_ISREG(row.st_mode) and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o600 and row.st_nlink == 1
        and 0 < row.st_size <= 12288
    ):
        raise SystemExit(3)
    raw = open(path, "rb").read()
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

cleanup_container
result="$(printf '{"ai_provider_call_count":0,"application_container_start_count":0,"automatic_retry_allowed":false,"database_connection_count":0,"database_envelope_count":1,"derived_role_replacement_count":1,"encrypted_recovery_root_retained":true,"encryption_task_container_start_count":1,"metadata_identity_check_count":1,"object_store_call_count":0,"plaintext_output_count":0,"provider_control_plane_mutation_count":0,"registry_call_count":0,"source_file_count":2,"status":"REENCRYPTED_C","storage_envelope_count":1,"terminal_cleanup_pending":true,"tool_root_retained":true,"unchanged_storage_key_count":6,"worker_c_database_envelope_b64":"%s","worker_c_storage_envelope_b64":"%s","worker_f_artifact_read_count":0,"worker_f_artifact_write_count":0}\n' "$wc_db" "$wc_storage")"
[ "${#result}" -le 12000 ]
recovery_ready=1
printf '%s' "$result"
success=1
trap - EXIT
