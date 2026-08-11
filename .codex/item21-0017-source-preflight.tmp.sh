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
readonly ARCHIVE='/run/noteai-item21-0017-source-f1a5cc.tar.gz'
readonly ARCHIVE_BYTES='20625'
readonly ARCHIVE_SHA256='8abb1fca9f67e98daca292932eb10ec9b39d5c79f8cbbd6e405e680de23d5c37'
readonly TAR_BYTES='112640'
readonly TAR_SHA256='083120e433dc76a1c7b34474c4272ae55e89278ce5879cb7f8d482d7b1f4850d'
readonly SOURCE_ROOT='/run/noteai-item21-0017-control-source-v1'
readonly TASK_ROOT='/run/noteai-item21-0017-source-preflight-v1'
readonly CONTROL_ROOT='/run/noteai-durable-ai-control'
readonly DOCKER_CONFIG_ROOT="$TASK_ROOT/docker-config"
readonly CONTAINER_NAME='noteai-i21-0017-source-preflight-v1'
readonly CONTAINER_LABEL='com.noteai.task=PROD-FIRST-LAUNCH-DURABLE-AI-PROTECTED-CONTROL-001-source-preflight'

task_created=0
task_cleaned=0
archive_verified=0
source_created=0
source_committed=0
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
  if [ "$completed" -eq 1 ]; then
    return 0
  fi
  if [ -d "$DOCKER_CONFIG_ROOT" ]; then
    cleanup_container >/dev/null 2>&1 || cleanup_ok=0
  fi
  cleanup_task_root >/dev/null 2>&1 || cleanup_ok=0
  if [ "$known_failure" -eq 1 ] && [ "$archive_verified" -eq 1 ] && [ "$source_created" -eq 0 ] && [ "$cleanup_ok" -eq 1 ]; then
    printf '%s\n' "NOTEAI_ITEM21_0017_SOURCE_PREFLIGHT=FAIL incident_class=PRE_DATABASE phase=$failure_phase cleanup=VERIFIED_TASK_ZERO source_root_created=0 transfer_archive_retained=true database_connections=0 database_writes=0 source_secret_reads=0 provider_control_plane_mutations=0 registry_calls=0 automatic_retry_allowed=false" >&2
    trap - EXIT
    exit 3
  fi
  if [ "$known_failure" -eq 1 ] && [ "$archive_verified" -eq 1 ] && [ "$source_committed" -eq 1 ] && [ "$cleanup_ok" -eq 1 ]; then
    printf '%s\n' "NOTEAI_ITEM21_0017_SOURCE_PREFLIGHT=FAIL incident_class=PRE_DATABASE phase=$failure_phase cleanup=VERIFIED_TASK_ZERO source_root_retained=true transfer_archive_retained=true database_connections=0 database_writes=0 source_secret_reads=0 provider_control_plane_mutations=0 registry_calls=0 automatic_retry_allowed=false" >&2
    trap - EXIT
    exit 3
  fi
  printf '%s\n' "NOTEAI_ITEM21_0017_SOURCE_PREFLIGHT=UNKNOWN incident_class=PRE_DATABASE phase=$failure_phase cleanup=UNKNOWN source_root_created=$source_created source_committed=$source_committed readback_required=true database_connections=0 database_writes=0 source_secret_reads=0 provider_control_plane_mutations=0 registry_calls=0 automatic_retry_allowed=false" >&2
  trap - EXIT
  exit 4
}
trap on_exit EXIT

[ "$(id -u)" = '0' ] || fail root_required
for required in docker systemctl stat sha256sum sort awk ss python3 timeout wc tr rm; do
  command -v "$required" >/dev/null 2>&1 || fail required_tool
done
[ -x /usr/bin/docker ] && [ -x /usr/bin/env ] && [ -x /usr/bin/timeout ] || fail required_absolute_tool
[ -d /run ] && [ ! -L /run ] || fail run_root
[ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || fail task_root_present
[ ! -e "$SOURCE_ROOT" ] && [ ! -L "$SOURCE_ROOT" ] || fail source_root_present
[ ! -e "$CONTROL_ROOT" ] && [ ! -L "$CONTROL_ROOT" ] || fail control_root_present

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

archive_contract="$({ python3 -I -B - "$ARCHIVE" <<'PY'
import gzip
import hashlib
import io
import os
import stat
import sys
import tarfile

path = sys.argv[1]
st = os.lstat(path)
if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_gid != 0:
    raise SystemExit(2)
if stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1 or st.st_size != 20625:
    raise SystemExit(2)
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    fst = os.fstat(fd)
    if (fst.st_dev, fst.st_ino, fst.st_mode, fst.st_uid, fst.st_gid, fst.st_nlink, fst.st_size) != (
        st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid, st.st_nlink, st.st_size
    ):
        raise SystemExit(2)
    chunks = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(fd)
compressed = b"".join(chunks)
if len(compressed) != 20625 or hashlib.sha256(compressed).hexdigest() != "8abb1fca9f67e98daca292932eb10ec9b39d5c79f8cbbd6e405e680de23d5c37":
    raise SystemExit(2)
raw = gzip.decompress(compressed)
if len(raw) != 112640 or hashlib.sha256(raw).hexdigest() != "083120e433dc76a1c7b34474c4272ae55e89278ce5879cb7f8d482d7b1f4850d":
    raise SystemExit(2)
expected = [
    ("scripts", "dir", 0o755, 0),
    ("scripts/validate_production_env_files.py", "file", 0o644, 7290),
    ("tools", "dir", 0o755, 0),
    ("tools/production_ai_dispatcher_secret_activator.py", "file", 0o644, 36894),
    ("tools/production_durable_ai_protected_control.py", "file", 0o644, 16107),
    ("tools/production_durable_ai_schema_0017.py", "file", 0o644, 15991),
    ("tools/production_managed_secret_roles.py", "file", 0o644, 15177),
    ("tools/production_secret_envelope.py", "file", 0o644, 3637),
]
comment = "f1a5cc014578e10243174a80d643a67a57921c17"
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
    if archive.pax_headers != {"comment": comment}:
        raise SystemExit(2)
    members = archive.getmembers()
    if len(members) != len(expected):
        raise SystemExit(2)
    for member, contract in zip(members, expected):
        name, kind, mode, size = contract
        if member.name != name or member.uid != 0 or member.gid != 0:
            raise SystemExit(2)
        if member.mode != mode or member.size != size or member.linkname:
            raise SystemExit(2)
        if member.pax_headers != {"comment": comment}:
            raise SystemExit(2)
        if kind == "dir" and not member.isdir():
            raise SystemExit(2)
        if kind == "file" and not member.isfile():
            raise SystemExit(2)
print("ARCHIVE_EXACT")
PY
} 2>/dev/null)" || fail archive_contract
[ "$archive_contract" = 'ARCHIVE_EXACT' ] || fail archive_contract
archive_verified=1

mkdir -m 0700 "$TASK_ROOT"
task_created=1
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
    labels.get("org.opencontainers.image.revision") == "cad5ce35664f617c6e19f90a6159285ddf975594",
    image.get("RepoDigests", []).count("noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b") == 1,
)
if not all(checks):
    raise SystemExit(2)
PY
rm -f "$TASK_ROOT/image.json"

db_before="$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" || fail db_socket_query
[ "$db_before" = '0' ] || fail database_connection_present

mkdir -m 0700 "$SOURCE_ROOT"
source_created=1
extract_result="$({ python3 -I -B - "$ARCHIVE" "$SOURCE_ROOT" <<'PY'
import gzip
import hashlib
import io
import os
import stat
import sys
import tarfile

archive_path, root = sys.argv[1:]
expected_hashes = {
    "scripts/validate_production_env_files.py": "1b1c2d1aef0bd52e07ebdbd3e671417bf00b5b8754efe7133e198eff17b41b21",
    "tools/production_ai_dispatcher_secret_activator.py": "258a7831de36d158c5b346f220f38073f97dfd0d70109cb46a65fcbd52a13f3f",
    "tools/production_durable_ai_protected_control.py": "c6e3c370495365c07dcbf8e4bf7cd8e250091dde563610741b7c7868841a2bb6",
    "tools/production_durable_ai_schema_0017.py": "c64cb74799cecb908902895f7151a13464980ec3ba2e0dccc7525c3536c4a8be",
    "tools/production_managed_secret_roles.py": "8d42df5a6ac5b466cd9040757448602f6fedcf0b87ae33fce7a9c3b3fc24973f",
    "tools/production_secret_envelope.py": "b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf",
}
expected_sizes = {
    "scripts/validate_production_env_files.py": 7290,
    "tools/production_ai_dispatcher_secret_activator.py": 36894,
    "tools/production_durable_ai_protected_control.py": 16107,
    "tools/production_durable_ai_schema_0017.py": 15991,
    "tools/production_managed_secret_roles.py": 15177,
    "tools/production_secret_envelope.py": 3637,
}
fd = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    compressed = b""
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        compressed += chunk
finally:
    os.close(fd)
if len(compressed) != 20625 or hashlib.sha256(compressed).hexdigest() != "8abb1fca9f67e98daca292932eb10ec9b39d5c79f8cbbd6e405e680de23d5c37":
    raise SystemExit(2)
raw = gzip.decompress(compressed)
if len(raw) != 112640 or hashlib.sha256(raw).hexdigest() != "083120e433dc76a1c7b34474c4272ae55e89278ce5879cb7f8d482d7b1f4850d":
    raise SystemExit(2)
payloads = {}
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
    members = {member.name: member for member in archive.getmembers()}
    if set(members) != {"scripts", "tools", *expected_hashes} or len(members) != 8:
        raise SystemExit(2)
    for name in expected_hashes:
        member = members[name]
        if not member.isfile() or member.linkname:
            raise SystemExit(2)
        stream = archive.extractfile(member)
        if stream is None:
            raise SystemExit(2)
        payload = stream.read()
        if len(payload) != expected_sizes[name] or hashlib.sha256(payload).hexdigest() != expected_hashes[name]:
            raise SystemExit(2)
        payloads[name] = payload

root_st = os.lstat(root)
if not stat.S_ISDIR(root_st.st_mode) or stat.S_IMODE(root_st.st_mode) != 0o700:
    raise SystemExit(2)
if root_st.st_uid != 0 or root_st.st_gid != 0:
    raise SystemExit(2)
root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    for directory in ("scripts", "tools"):
        os.mkdir(directory, 0o700, dir_fd=root_fd)
    for name in sorted(payloads):
        parent, base = name.split("/", 1)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            out_fd = os.open(
                base,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            try:
                payload = payloads[name]
                offset = 0
                while offset < len(payload):
                    written = os.write(out_fd, payload[offset:])
                    if written <= 0:
                        raise SystemExit(2)
                    offset += written
                os.fchown(out_fd, 0, 0)
                os.fchmod(out_fd, 0o600)
                os.fsync(out_fd)
            finally:
                os.close(out_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    os.fsync(root_fd)
finally:
    os.close(root_fd)

if sorted(os.listdir(root)) != ["scripts", "tools"]:
    raise SystemExit(2)
for directory in ("scripts", "tools"):
    path = os.path.join(root, directory)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o700 or st.st_uid != 0 or st.st_gid != 0:
        raise SystemExit(2)
for name in sorted(expected_hashes):
    path = os.path.join(root, name)
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o600:
        raise SystemExit(2)
    if st.st_uid != 0 or st.st_gid != 0 or st.st_nlink != 1 or st.st_size != expected_sizes[name]:
        raise SystemExit(2)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            raise SystemExit(2)
        payload = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            payload += chunk
    finally:
        os.close(fd)
    if hashlib.sha256(payload).hexdigest() != expected_hashes[name]:
        raise SystemExit(2)
print("SOURCE_EXACT")
PY
} 2>/dev/null)" || fail source_extract
[ "$extract_result" = 'SOURCE_EXACT' ] || fail source_extract
source_committed=1

container_attempted=1
set +e
/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 180s \
  /usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" \
  /usr/bin/docker --context=default run --rm -i \
    --name "$CONTAINER_NAME" \
    --label "$CONTAINER_LABEL" \
    --pull never --network none --read-only --user 0:0 \
    --cap-drop ALL --cap-add DAC_READ_SEARCH \
    --security-opt no-new-privileges \
    --pids-limit 64 --memory 256m --cpus 0.50 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --mount "type=bind,src=$SOURCE_ROOT/tools,dst=/app/tools,readonly,bind-propagation=rprivate" \
    --mount "type=bind,src=$SOURCE_ROOT/scripts,dst=/app/scripts,readonly,bind-propagation=rprivate" \
    --entrypoint /usr/local/bin/python3.11 \
    "$IMAGE_REF" -I -B - >"$TASK_ROOT/container.stdout" 2>"$TASK_ROOT/container.stderr" <<'PY'
import hashlib
import importlib
import os
import pathlib
import sys

if os.geteuid() != 0 or os.getegid() != 0:
    raise SystemExit(11)
status = {}
for line in pathlib.Path("/proc/self/status").read_text(encoding="ascii").splitlines():
    if ":" in line:
        key, value = line.split(":", 1)
        status[key] = value.strip()
if status.get("CapEff") != "0000000000000004":
    raise SystemExit(12)
if status.get("CapPrm") != "0000000000000004":
    raise SystemExit(12)
if status.get("CapBnd") != "0000000000000004":
    raise SystemExit(12)
if status.get("CapInh") != "0000000000000000" or status.get("CapAmb") != "0000000000000000":
    raise SystemExit(12)
if status.get("NoNewPrivs") != "1":
    raise SystemExit(12)

mount_options = {}
for line in pathlib.Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
    fields = line.split()
    if len(fields) > 6 and fields[4] in ("/app/tools", "/app/scripts"):
        mount_options[fields[4]] = set(fields[5].split(","))
if set(mount_options) != {"/app/tools", "/app/scripts"}:
    raise SystemExit(13)
if any("ro" not in options for options in mount_options.values()):
    raise SystemExit(13)

sys.path.insert(0, "/app")
contracts = (
    ("tools.production_durable_ai_protected_control", "/app/tools/production_durable_ai_protected_control.py", "c6e3c370495365c07dcbf8e4bf7cd8e250091dde563610741b7c7868841a2bb6"),
    ("tools.production_durable_ai_schema_0017", "/app/tools/production_durable_ai_schema_0017.py", "c64cb74799cecb908902895f7151a13464980ec3ba2e0dccc7525c3536c4a8be"),
    ("tools.production_ai_dispatcher_secret_activator", "/app/tools/production_ai_dispatcher_secret_activator.py", "258a7831de36d158c5b346f220f38073f97dfd0d70109cb46a65fcbd52a13f3f"),
    ("tools.production_managed_secret_roles", "/app/tools/production_managed_secret_roles.py", "8d42df5a6ac5b466cd9040757448602f6fedcf0b87ae33fce7a9c3b3fc24973f"),
    ("tools.production_secret_envelope", "/app/tools/production_secret_envelope.py", "b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf"),
    ("scripts.validate_production_env_files", "/app/scripts/validate_production_env_files.py", "1b1c2d1aef0bd52e07ebdbd3e671417bf00b5b8754efe7133e198eff17b41b21"),
)
modules = {}
for module_name, expected_path, expected_hash in contracts:
    module = importlib.import_module(module_name)
    actual_path = str(pathlib.Path(module.__file__).resolve())
    if actual_path != expected_path:
        raise SystemExit(14)
    if hashlib.sha256(pathlib.Path(expected_path).read_bytes()).hexdigest() != expected_hash:
        raise SystemExit(14)
    modules[module_name] = module

protected = modules["tools.production_durable_ai_protected_control"]
schema = modules["tools.production_durable_ai_schema_0017"]
dispatcher = modules["tools.production_ai_dispatcher_secret_activator"]
managed = modules["tools.production_managed_secret_roles"]
if pathlib.Path(protected.ROOT) != pathlib.Path("/app"):
    raise SystemExit(15)
if pathlib.Path(schema.MIGRATION_DIR) != pathlib.Path("/app/model/migrations/postgres"):
    raise SystemExit(15)
if protected.TASK_ID != "PROD-FIRST-LAUNCH-DURABLE-AI-PROTECTED-CONTROL-001":
    raise SystemExit(15)
if protected.TASK_ACCOUNT_NAME != "noteai_schema_task_durable_ai_0017":
    raise SystemExit(15)
if schema.TASK_ID != "PROD-FIRST-LAUNCH-DURABLE-AI-SCHEMA-0017":
    raise SystemExit(15)
if dispatcher.TASK_ID != "PROD-FIRST-LAUNCH-DURABLE-AI-DISPATCHER-SECRET-001":
    raise SystemExit(15)

source = schema.source_contract()
expected_hashes = dict(managed.EXPECTED_MIGRATIONS)
expected_hashes[schema.MIGRATION_NAME] = schema.MIGRATION_SHA256
if source.get("migration_hashes") != expected_hashes:
    raise SystemExit(16)
if len(expected_hashes) != 17 or expected_hashes.get(schema.MIGRATION_NAME) != "a73cbefd853cefe7b56c42bed2c5a7f0ba1626e57755c6f9464629b49c42cbbe":
    raise SystemExit(16)

print("NOTEAI_ITEM21_0017_SOURCE_CONTAINER=PASS euid=0 cap_effective=0x4 cap_permitted=0x4 cap_bounding=0x4 no_new_privs=true source_file_count=6 source_bytes=95096 source_contract_migration_count=17 migration_0017_exact=true source_mount_count=2 database_connections=0 database_writes=0 source_secret_reads=0 provider_control_plane_mutations=0 registry_calls=0")
PY
container_rc=$?
set -e
[ "$container_rc" -eq 0 ] || fail source_container
[ ! -s "$TASK_ROOT/container.stderr" ] || fail source_container_stderr
container_output="$(<"$TASK_ROOT/container.stdout")"
[ "$container_output" = 'NOTEAI_ITEM21_0017_SOURCE_CONTAINER=PASS euid=0 cap_effective=0x4 cap_permitted=0x4 cap_bounding=0x4 no_new_privs=true source_file_count=6 source_bytes=95096 source_contract_migration_count=17 migration_0017_exact=true source_mount_count=2 database_connections=0 database_writes=0 source_secret_reads=0 provider_control_plane_mutations=0 registry_calls=0' ] || fail source_container_output

post_task_ids="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default container ls -aq --filter "name=^/${CONTAINER_NAME}$")" || fail task_container_postquery
[ -z "$post_task_ids" ] || fail task_container_residue
after_containers="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default inspect noteai-api-c noteai-admin-c --format '{{.Id}}|{{.State.Status}}|{{.RestartCount}}|{{.Image}}|{{json .HostConfig.PortBindings}}' | sort | sha256sum | awk '{print $1}')" || fail api_fingerprint_post
[ "$after_containers" = "$before_containers" ] || fail api_container_drift
after_images="$(/usr/bin/env DOCKER_CONFIG="$DOCKER_CONFIG_ROOT" /usr/bin/docker --context=default image ls -aq --no-trunc | sort -u | sha256sum | awk '{print $1}')" || fail image_set_post
[ "$after_images" = "$before_images" ] || fail image_set_drift
db_after="$(ss -Htan state established | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END {print n+0}')" || fail db_socket_postquery
[ "$db_after" = '0' ] || fail database_connection_post

cleanup_container || fail container_cleanup
cleanup_task_root || fail task_cleanup

printf '%s\n' 'NOTEAI_ITEM21_0017_SOURCE_PREFLIGHT=PASS host=API-C source_file_count=6 source_bytes=95096 source_contract_migration_count=17 migration_0017_exact=true euid=0 cap_effective=0x4 cap_permitted=0x4 cap_bounding=0x4 no_new_privs=true network_none=true source_mount_count=2 diagnostic_container_starts=1 diagnostic_container_residue=0 api_container_drift=0 image_set_drift=0 database_connections=0 database_writes=0 source_secret_reads=0 metadata_http_requests=3 provider_control_plane_mutations=0 registry_calls=0 source_root_retained=true transfer_archive_retained=true task_root_residue=0 automatic_retry_allowed=false'
completed=1
trap - EXIT
