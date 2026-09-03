#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONOPTIMIZE PYTHONDONTWRITEBYTECODE

readonly ORIGINAL_ROOT='/run/noteai-item21-worker-secret-source-v1'
readonly REKEY_ROOT='/run/noteai-item21-worker-secret-source-rekey-c-v1'
readonly TOOL_ROOT='/run/noteai-item21-worker-secret-source-tools-v1'
readonly DOCKER_CONFIG_ROOT="$ORIGINAL_ROOT/docker-config"
readonly MODULE_PATH="$TOOL_ROOT/production_secret_envelope.py"
readonly SOURCE_DRIVER_PATH="$TOOL_ROOT/source-driver.py"
readonly REKEY_DRIVER_PATH="$REKEY_ROOT/source-reencrypt-c-driver.py"
readonly MODULE_SHA256='b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf'
readonly SOURCE_DRIVER_SHA256='ff9bdcfa6b8979848ff35e7d8c7c9c05450d9573d21eb220fbcc367d9ce1c3d2'
readonly REKEY_DRIVER_SHA256='ede68c0fdc3400d5811595b7493039566afac29a281e60f4400bb59366ebbd99'
readonly API_INSTANCE_ID='i-wz9j36od3nf2b1uw7bvg'
readonly API_ROLE='noteai-storage-api-20260729-c60cc608'

mutation_started=0
success=0

on_exit() {
  local rc=$?
  if [ "$success" -eq 1 ] && [ "$rc" -eq 0 ]; then
    return 0
  fi
  if [ "$mutation_started" -eq 1 ]; then
    printf '%s\n' '{"automatic_retry_allowed":false,"readback_required":true,"status":"SOURCE_RESIDUE_CLEANUP_UNKNOWN"}' >&2 || true
    exit 4
  fi
  printf '%s\n' '{"automatic_retry_allowed":false,"status":"SOURCE_RESIDUE_CLEANUP_PRECHECK_FAILED"}' >&2 || true
  exit 3
}
trap on_exit EXIT

[ "$(id -u)" = '0' ]

python3 -I -B - \
  "$ORIGINAL_ROOT" "$REKEY_ROOT" "$TOOL_ROOT" \
  "$MODULE_PATH" "$SOURCE_DRIVER_PATH" "$REKEY_DRIVER_PATH" \
  "$MODULE_SHA256" "$SOURCE_DRIVER_SHA256" "$REKEY_DRIVER_SHA256" \
  "$API_INSTANCE_ID" "$API_ROLE" <<'PY'
import hashlib
import os
import stat
import sys
import urllib.request

(
    original_root, rekey_root, tool_root,
    module_path, source_driver_path, rekey_driver_path,
    module_sha, source_driver_sha, rekey_driver_sha,
    expected_instance, expected_role,
) = sys.argv[1:]

def safe_dir(path, names):
    row = os.lstat(path)
    if not (
        stat.S_ISDIR(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o700
    ):
        raise SystemExit(2)
    if set(os.listdir(path)) != set(names):
        raise SystemExit(3)

def safe_file(path, minimum=0, maximum=16384):
    before = os.lstat(path)
    if not (
        stat.S_ISREG(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_uid == 0 and before.st_gid == 0
        and stat.S_IMODE(before.st_mode) == 0o600
        and before.st_nlink == 1
        and minimum <= before.st_size <= maximum
    ):
        raise SystemExit(4)
    return before

def read_fixed(path, maximum=16384):
    before = safe_file(path, 0, maximum)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        current = os.fstat(descriptor)
        if not (
            current.st_dev == before.st_dev and current.st_ino == before.st_ino
            and current.st_uid == 0 and current.st_gid == 0
            and stat.S_IMODE(current.st_mode) == 0o600
            and current.st_nlink == 1 and current.st_size == before.st_size
        ):
            raise SystemExit(5)
        payload = b""
        while len(payload) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(payload)))
            if not chunk:
                break
            payload += chunk
        if len(payload) != before.st_size:
            raise SystemExit(6)
        return payload
    finally:
        os.close(descriptor)

original_top = {"docker-config", "input", "output", "helper.stdout", "helper.stderr"}
safe_dir(original_root, original_top)
safe_dir(os.path.join(original_root, "docker-config"), set())
original_input = os.path.join(original_root, "input")
original_output = os.path.join(original_root, "output")
safe_dir(original_input, {
    "worker-c-public.pem", "worker-c-public.sha256",
    "worker-f-public.pem", "worker-f-public.sha256",
})
safe_dir(original_output, {
    "worker-c-database.envelope.json", "worker-c-private_storage.envelope.json",
    "worker-f-database.envelope.json", "worker-f-private_storage.envelope.json",
})
for name in os.listdir(original_input):
    safe_file(os.path.join(original_input, name), 1, 1024)
for name in os.listdir(original_output):
    safe_file(os.path.join(original_output, name), 1, 12288)
if read_fixed(os.path.join(original_root, "helper.stdout"), 1) != b"":
    raise SystemExit(7)
if read_fixed(os.path.join(original_root, "helper.stderr"), 128) != b"timeout: failed to run command 'docker_task': No such file or directory\n":
    raise SystemExit(8)

rekey_top = {"docker-config", "input", "output", "helper.stdout", "helper.stderr", "source-reencrypt-c-driver.py"}
safe_dir(rekey_root, rekey_top)
safe_dir(os.path.join(rekey_root, "docker-config"), set())
rekey_input = os.path.join(rekey_root, "input")
rekey_output = os.path.join(rekey_root, "output")
safe_dir(rekey_input, {"worker-c-public.pem", "worker-c-public.sha256"})
safe_dir(rekey_output, {"worker-c-database.envelope.json", "worker-c-private_storage.envelope.json"})
for name in os.listdir(rekey_input):
    safe_file(os.path.join(rekey_input, name), 1, 1024)
for name in os.listdir(rekey_output):
    safe_file(os.path.join(rekey_output, name), 1, 12288)
expected_rekey_summary = (
    b'{"database_payload_unchanged":true,"derived_role_replacement_count":1,'
    b'"envelope_count":2,"plaintext_output_count":0,"source_file_count":2,'
    b'"status":"REENCRYPTED_C","unchanged_storage_key_count":6,'
    b'"worker_c_payload_count":2}\n'
)
if read_fixed(os.path.join(rekey_root, "helper.stdout"), 512) != expected_rekey_summary:
    raise SystemExit(9)
if read_fixed(os.path.join(rekey_root, "helper.stderr"), 1) != b"":
    raise SystemExit(10)

safe_dir(tool_root, {"production_secret_envelope.py", "source-driver.py"})
for path, expected_sha in (
    (module_path, module_sha),
    (source_driver_path, source_driver_sha),
    (rekey_driver_path, rekey_driver_sha),
):
    payload = read_fixed(path, 16384)
    if hashlib.sha256(payload).hexdigest() != expected_sha:
        raise SystemExit(11)

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
    raise SystemExit(12)

def metadata(path):
    request = urllib.request.Request(
        "http://100.100.100.200/latest/meta-data/" + path,
        headers={"X-aliyun-ecs-metadata-token": token},
    )
    with opener.open(request, timeout=3) as response:
        payload = response.read(4096)
    if len(payload) >= 4096:
        raise SystemExit(13)
    return payload.decode("ascii").strip()

if metadata("instance-id") != expected_instance:
    raise SystemExit(14)
roles = [value for value in metadata("ram/security-credentials/").splitlines() if value]
if roles != [expected_role]:
    raise SystemExit(15)
PY

[ "$(/usr/bin/systemctl is-active docker)" = 'active' ]
[ "$(/usr/bin/systemctl is-enabled docker)" = 'enabled' ]
[ "$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default context inspect default --format '{{(index .Endpoints "docker").Host}}')" = 'unix:///var/run/docker.sock' ]
for container_name in noteai-item21-worker-secret-source noteai-item21-worker-secret-source-rekey-c; do
  container_ids="$(env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -a --filter "name=^/$container_name$" --format '{{.ID}}')"
  [ -z "$container_ids" ]
done

mutation_started=1
rm -rf -- "$ORIGINAL_ROOT"
[ ! -e "$ORIGINAL_ROOT" ] && [ ! -L "$ORIGINAL_ROOT" ]
rm -rf -- "$REKEY_ROOT"
[ ! -e "$REKEY_ROOT" ] && [ ! -L "$REKEY_ROOT" ]
rm -rf -- "$TOOL_ROOT"
[ ! -e "$TOOL_ROOT" ] && [ ! -L "$TOOL_ROOT" ]

success=1
printf '%s\n' '{"automatic_retry_allowed":false,"ciphertext_value_read_count":0,"encrypted_envelope_residue_count":0,"source_secret_value_read_count":0,"source_task_root_count":0,"source_tool_root_count":0,"status":"SOURCE_RESIDUE_CLEANUP_COMPLETE"}'
trap - EXIT
