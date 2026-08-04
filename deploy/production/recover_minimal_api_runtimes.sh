#!/bin/bash
set +x
set -Eeuo pipefail
umask 077

export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export DOCKER_CONTEXT='default'
unset \
  ALIBABA_CLOUD_ACCESS_KEY_ID \
  ALIBABA_CLOUD_ACCESS_KEY_SECRET \
  ALIBABA_CLOUD_SECURITY_TOKEN \
  ALICLOUD_ACCESS_KEY \
  ALICLOUD_SECRET_KEY \
  ALICLOUD_SECURITY_TOKEN \
  BUILDKIT_HOST \
  BUILDX_BUILDER \
  DOCKER_CERT_PATH \
  DOCKER_CONFIG \
  DOCKER_HOST \
  DOCKER_TLS_VERIFY \
  HTTP_PROXY \
  HTTPS_PROXY \
  ALL_PROXY \
  http_proxy \
  https_proxy \
  all_proxy

readonly API_REVISION='b55f11882100e9ef919522540729e366a511f88f'
readonly API_MANIFEST='sha256:612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620'
readonly API_IMAGE_ID='sha256:dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53'
readonly API_IMAGE='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620'
readonly ADMIN_REVISION='a635692a899ee02c6905cd694611c14e0da4594a'
readonly ADMIN_MANIFEST='sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733'
readonly ADMIN_IMAGE_ID='sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f'
readonly ADMIN_IMAGE='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733'
readonly API_ENV='/etc/noteai/api.env'
readonly ADMIN_ENV='/etc/noteai/admin.env'
readonly DATA_DIR='/var/lib/noteai/data'
SYSTEMD_DIR='/etc/systemd/system'
TASK_ROOT='/run/noteai-minimal-api-runtime-recovery'
readonly RECOVERY_OWNER='noteai-minimal-api-runtime-v1'

phase='argument_validation'
host_role=''
storage_env=''
task_root_owned=0
mutation_started=0
success=0
cleanup_unknown=0
installed_units=()
installed_hashes=()
temporary_unit_paths=()
target_units=()
target_containers=()
target_ports=()
target_image_ids=()

fail() {
  printf 'NOTEAI_RUNTIME_RECOVERY=FAIL phase=%s code=%s\n' "$phase" "$1" >&2
  return 1
}

port_listener_count() {
  local port="$1"
  ss -H -ltn 2>/dev/null | awk -v suffix=":${port}" \
    '$4 ~ suffix "$" {count++} END {print count + 0}'
}

database_connection_count() {
  ss -H -tn state established 2>/dev/null | awk \
    '$4 ~ /:5432$/ || $5 ~ /:5432$/ {count++} END {print count + 0}'
}

unit_is_absent() {
  local unit="$1"
  [ ! -e "${SYSTEMD_DIR}/${unit}" ] && [ ! -L "${SYSTEMD_DIR}/${unit}" ] && \
    [ "$(systemctl show "$unit" --property=LoadState --value 2>/dev/null || true)" = 'not-found' ] && \
    [ -z "$(find "$SYSTEMD_DIR" -type l -name "$unit" -print -quit)" ] && \
    [ -z "$(find "$SYSTEMD_DIR" -maxdepth 1 -name ".${unit}.noteai-recovery.*" -print -quit)" ]
}

container_is_absent() {
  ! docker container inspect "$1" >/dev/null 2>&1
}

container_is_owned() {
  local container="$1"
  local image_id="$2"
  [ "$(docker container inspect "$container" --format '{{index .Config.Labels "com.noteai.recovery.owner"}}|{{.Image}}' 2>/dev/null)" = "${RECOVERY_OWNER}|${image_id}" ]
}

parse_env_keys() {
  local path="$1"
  awk '
    /^[[:space:]]*($|#)/ {next}
    {
      line = $0
      if (line !~ /^[A-Za-z_][A-Za-z0-9_]*=/) exit 2
      sub(/=.*/, "", line)
      print line
    }
  ' "$path"
}

regular_root_0600() {
  local path="$1"
  [ -f "$path" ] && [ ! -L "$path" ] && \
    [ "$(stat -c '%u:%g:%a' "$path")" = '0:0:600' ]
}

validate_env_file() {
  local path="$1"
  local kind="$2"
  local key_file="${TASK_ROOT}/${kind}.keys"
  regular_root_0600 "$path" || return 1
  parse_env_keys "$path" > "$key_file" || return 1
  [ -s "$key_file" ] || return 1
  [ -z "$(LC_ALL=C sort "$key_file" | uniq -d)" ] || return 1

  case "$kind" in
    api)
      [ "$(grep -c '^DATABASE_URL$' "$key_file")" = '1' ] || return 1
      ! grep -Eq '^(PGOPTIONS|NOTEAI_RUNTIME_ROLE|NOTEAI_DEPLOYMENT_STAGE|NOTEAI_CLOUD_RUNTIME|NOTEAI_API_STARTS_TREND_SCHEDULER|NOTEAI_MODEL_ARTIFACT_REQUIRED|NOTEAI_ENABLE_CLOUD_MODEL_MUTATION|NOTEAI_DURABLE_AI_ADMISSION_ENABLED|NOTEAI_TRUSTED_PROXY_IPS|PORT)$' "$key_file"
      ! grep -Eq '^(NOTEAI_PRIVATE_STORAGE_BACKEND|NOTEAI_OSS_PRIVATE_BUCKET|NOTEAI_OSS_REGION|NOTEAI_OSS_ENDPOINT|NOTEAI_OSS_RAM_ROLE|NOTEAI_PRIVATE_STORAGE_KEY_EPOCH|NOTEAI_OSS_KEY_PREFIX|ALIBABA_CLOUD_ACCESS_KEY_ID|ALIBABA_CLOUD_ACCESS_KEY_SECRET|OSS_ACCESS_KEY_ID|OSS_ACCESS_KEY_SECRET)$' "$key_file"
      ;;
    admin)
      [ "$(LC_ALL=C sort "$key_file")" = $'ADMIN_PASSWORD\nDATABASE_URL' ]
      ;;
    *) return 1 ;;
  esac
}

validate_topology_env() {
  local path="$1"
  local label="$2"
  local key_file="${TASK_ROOT}/${label}.keys"
  regular_root_0600 "$path" || return 1
  parse_env_keys "$path" > "$key_file" || return 1
  [ -s "$key_file" ] && [ -z "$(LC_ALL=C sort "$key_file" | uniq -d)" ]
}

env_value() {
  local path="$1"
  local key="$2"
  awk -v target="$key" '
    $0 ~ ("^" target "=") {
      count++
      value = substr($0, length(target) + 2)
    }
    END {
      if (count != 1) exit 2
      print value
    }
  ' "$path"
}

validate_storage_values() {
  local path="$1"
  local backend bucket region endpoint role epoch prefix
  backend="$(env_value "$path" NOTEAI_PRIVATE_STORAGE_BACKEND)" || return 1
  bucket="$(env_value "$path" NOTEAI_OSS_PRIVATE_BUCKET)" || return 1
  region="$(env_value "$path" NOTEAI_OSS_REGION)" || return 1
  endpoint="$(env_value "$path" NOTEAI_OSS_ENDPOINT)" || return 1
  role="$(env_value "$path" NOTEAI_OSS_RAM_ROLE)" || return 1
  epoch="$(env_value "$path" NOTEAI_PRIVATE_STORAGE_KEY_EPOCH)" || return 1
  prefix="$(env_value "$path" NOTEAI_OSS_KEY_PREFIX)" || return 1
  [ "$backend" = 'aliyun_oss' ] || return 1
  [[ "$region" =~ ^cn-[a-z0-9-]{2,32}$ ]] || return 1
  [ "$endpoint" = "https://oss-${region}-internal.aliyuncs.com" ] || return 1
  [ -n "$bucket" ] && [ -n "$role" ] && [ -n "$epoch" ] || return 1
  prefix="${prefix#/}"
  prefix="${prefix%/}"
  [ "$prefix" = 'noteai-private' ]
}

validate_host_secret_topology() {
  local expected=()
  local absent=()
  local path
  local label
  if [ "$host_role" = 'API-C' ]; then
    expected=(api.env admin.env payment.env ai-worker.env)
    absent=(xhs-trends.env xhs-tracking.env xhs.env)
  else
    expected=(api.env xhs-trends.env xhs-tracking.env)
    absent=(admin.env payment.env ai-worker.env xhs.env)
  fi
  for label in "${expected[@]}"; do
    path="/etc/noteai/${label}"
    validate_topology_env "$path" "topology-${label%.env}" || return 1
  done
  for label in "${absent[@]}"; do
    path="/etc/noteai/${label}"
    [ ! -e "$path" ] && [ ! -L "$path" ] || return 1
  done
}

discover_storage_env() {
  local path
  local candidate_keys
  local expected_keys
  local candidate_count=0
  expected_keys="$({
    printf '%s\n' \
      NOTEAI_OSS_ENDPOINT \
      NOTEAI_OSS_KEY_PREFIX \
      NOTEAI_OSS_PRIVATE_BUCKET \
      NOTEAI_OSS_RAM_ROLE \
      NOTEAI_OSS_REGION \
      NOTEAI_PRIVATE_STORAGE_BACKEND \
      NOTEAI_PRIVATE_STORAGE_KEY_EPOCH
  } | LC_ALL=C sort)"

  while IFS= read -r -d '' path; do
    case "$path" in
      "$API_ENV"|"$ADMIN_ENV"|/etc/noteai/xhs.env) continue ;;
    esac
    regular_root_0600 "$path" || continue
    candidate_keys="$(parse_env_keys "$path" 2>/dev/null | LC_ALL=C sort)" || continue
    if [ "$candidate_keys" = "$expected_keys" ]; then
      if validate_storage_values "$path"; then
        storage_env="$path"
        candidate_count=$((candidate_count + 1))
      fi
    fi
  done < <(find /etc/noteai -mindepth 1 -maxdepth 1 -type f -print0)

  [ "$candidate_count" = '1' ]
}

verify_image() {
  local image_ref="$1"
  local image_id="$2"
  local revision="$3"
  local role="$4"
  local command_json="$5"

  [ "$(docker image inspect "$image_ref" --format '{{.Id}}' 2>/dev/null)" = "$image_id" ] && \
    [ "$(docker image inspect "$image_ref" --format '{{.Os}}/{{.Architecture}}')" = 'linux/amd64' ] && \
    [ "$(docker image inspect "$image_ref" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$revision" ] && \
    [ "$(docker image inspect "$image_ref" --format '{{index .Config.Labels "com.noteai.runtime.role"}}')" = "$role" ] && \
    [ "$(docker image inspect "$image_ref" --format '{{json .Config.Entrypoint}}')" = '["/app/scripts/docker_entrypoint.sh"]' ] && \
    [ "$(docker image inspect "$image_ref" --format '{{json .Config.Cmd}}')" = "$command_json" ] && \
    [ "$(docker image inspect "$image_id" --format '{{.Id}}')" = "$image_id" ] && \
    [ "$(docker image inspect "$image_ref" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -Fxc "$image_ref")" = '1' ]
}

render_api_unit() {
  local destination="$1"
  local container="$2"
  local storage_path="$3"
  cat > "$destination" <<EOF
[Unit]
Description=NoteAI production API semantic recovery
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=no
TimeoutStartSec=120
TimeoutStopSec=45
KillMode=process
Environment=DOCKER_CONTEXT=default
ExecStart=/usr/bin/docker run --pull=never --rm --name=${container} --label=com.noteai.recovery.owner=${RECOVERY_OWNER} --user=999:999 --read-only --cap-drop=ALL --security-opt=no-new-privileges:true --network=bridge --ipc=private --memory=1536m --cpus=2 --pids-limit=512 --tmpfs=/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999 --env-file=${API_ENV} --env-file=${storage_path} --env=NOTEAI_RUNTIME_ROLE=api --env=NOTEAI_DEPLOYMENT_STAGE=production --env=NOTEAI_CLOUD_RUNTIME=1 --env=NOTEAI_API_STARTS_TREND_SCHEDULER=0 --env=NOTEAI_MODEL_ARTIFACT_REQUIRED=1 --env=NOTEAI_ENABLE_CLOUD_MODEL_MUTATION=0 --env=NOTEAI_DURABLE_AI_ADMISSION_ENABLED=0 --env=NOTEAI_TRUSTED_PROXY_IPS=127.0.0.1 --env="PGOPTIONS=-c default_transaction_read_only=on" --publish=127.0.0.1:8000:8000 --mount=type=bind,src=${DATA_DIR},dst=/app/model/data ${API_IMAGE}
ExecStop=/usr/bin/docker container stop --time=30 ${container}

[Install]
WantedBy=multi-user.target
EOF
}

render_admin_unit() {
  local destination="$1"
  cat > "$destination" <<EOF
[Unit]
Description=NoteAI production historical Admin semantic recovery
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=no
TimeoutStartSec=120
TimeoutStopSec=45
KillMode=process
Environment=DOCKER_CONTEXT=default
ExecStart=/usr/bin/docker run --pull=never --rm --name=noteai-admin-c --label=com.noteai.recovery.owner=${RECOVERY_OWNER} --user=999:999 --read-only --cap-drop=ALL --security-opt=no-new-privileges:true --network=bridge --ipc=private --memory=1024m --cpus=1 --pids-limit=512 --tmpfs=/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999 --env-file=${ADMIN_ENV} --env=NOTEAI_RUNTIME_ROLE=admin --env=NOTEAI_DEPLOYMENT_STAGE=production --env=NOTEAI_CLOUD_RUNTIME=1 --env=NOTEAI_SKIP_MODEL_ARTIFACT_CHECK=1 --env=NOTEAI_ENABLE_CLOUD_MODEL_MUTATION=0 --env=PORT=8001 --env="PGOPTIONS=-c default_transaction_read_only=on" --publish=127.0.0.1:8001:8001 --mount=type=bind,src=${DATA_DIR},dst=/app/model/data ${ADMIN_IMAGE}
ExecStop=/usr/bin/docker container stop --time=30 noteai-admin-c

[Install]
WantedBy=multi-user.target
EOF
}

offline_self_test() {
  local fixture
  fixture="$(mktemp -d)"
  trap 'rm -rf -- "$fixture"' RETURN
  render_api_unit "$fixture/api.service" noteai-api-f /etc/noteai/private-storage.env
  render_admin_unit "$fixture/admin.service"
  grep -Fq -- '--pull=never' "$fixture/api.service"
  grep -Fq -- '--publish=127.0.0.1:8000:8000' "$fixture/api.service"
  grep -Fq -- '--publish=127.0.0.1:8001:8001' "$fixture/admin.service"
  grep -Fq -- 'PGOPTIONS=-c default_transaction_read_only=on' "$fixture/api.service"
  grep -Fq -- 'PGOPTIONS=-c default_transaction_read_only=on' "$fixture/admin.service"
  [ "$(grep -Fhc -- 'Restart=no' "$fixture/api.service" "$fixture/admin.service" | awk '{sum += $1} END {print sum}')" = '2' ]
  ! grep -Fq -- '--privileged' "$fixture/api.service"
  ! grep -Fq -- '--privileged' "$fixture/admin.service"
  printf 'NOTEAI_RUNTIME_RECOVERY_OFFLINE_SELF_TEST=PASS\n'
}

offline_rollback_self_test() {
  local fixture
  local fault
  local unit
  local unit_path
  local hash
  fixture="$(mktemp -d)"
  trap 'rm -rf -- "$fixture"' RETURN
  SYSTEMD_DIR="${fixture}/systemd"
  TASK_ROOT="${fixture}/task"
  mkdir -p "$SYSTEMD_DIR/multi-user.target.wants" "$TASK_ROOT" \
    "$fixture/containers" "$fixture/listeners" "$fixture/active"
  target_units=(noteai-api.service noteai-admin.service)
  target_containers=(noteai-api-c noteai-admin-c)
  target_ports=(8000 8001)
  target_image_ids=("$API_IMAGE_ID" "$ADMIN_IMAGE_ID")

  unit_is_absent() {
    local checked_unit="$1"
    [ ! -e "${SYSTEMD_DIR}/${checked_unit}" ] && \
      [ ! -L "${SYSTEMD_DIR}/${checked_unit}" ] && \
      [ ! -e "${fixture}/active/${checked_unit}" ] && \
      [ -z "$(find "$SYSTEMD_DIR" -type l -name "$checked_unit" -print -quit)" ] && \
      [ -z "$(find "$SYSTEMD_DIR" -maxdepth 1 -name ".${checked_unit}.noteai-recovery.*" -print -quit)" ]
  }
  container_is_absent() {
    [ ! -e "${fixture}/containers/$1" ]
  }
  container_is_owned() {
    [ "$(cat "${fixture}/containers/$1" 2>/dev/null || true)" = "${RECOVERY_OWNER}|$2" ]
  }
  port_listener_count() {
    if [ -e "${fixture}/listeners/$1" ]; then printf '1\n'; else printf '0\n'; fi
  }
  systemctl() {
    local action="$1"
    shift
    case "$action" in
      is-active)
        [ -e "${fixture}/active/${2}" ]
        ;;
      stop)
        [ "${OFFLINE_STOP_FAIL:-0}" != '1' ] || return 1
        rm -f -- "${fixture}/active/${1}"
        ;;
      is-enabled)
        [ -L "${SYSTEMD_DIR}/multi-user.target.wants/${2}" ]
        ;;
      disable)
        rm -f -- "${SYSTEMD_DIR}/multi-user.target.wants/${1}"
        ;;
      daemon-reload) return 0 ;;
      show) printf 'not-found\n' ;;
      *) return 1 ;;
    esac
  }
  docker() {
    local container
    if [ "$1 $2 $3" = 'container rm --force' ]; then
      container="$4"
      rm -f -- "${fixture}/containers/${container}"
      case "$container" in
        noteai-api-c) rm -f -- "${fixture}/listeners/8000" ;;
        noteai-admin-c) rm -f -- "${fixture}/listeners/8001" ;;
      esac
      return 0
    fi
    return 1
  }

  for fault in install reload enable start health postcheck; do
    rm -rf -- "$SYSTEMD_DIR" "$fixture/containers" "$fixture/listeners" "$fixture/active"
    mkdir -p "$SYSTEMD_DIR/multi-user.target.wants" \
      "$fixture/containers" "$fixture/listeners" "$fixture/active"
    installed_units=()
    installed_hashes=()
    temporary_unit_paths=()
    cleanup_unknown=0
    if [ "$fault" = 'install' ]; then
      unit_path="${SYSTEMD_DIR}/.noteai-api.service.noteai-recovery.999"
      printf 'partial\n' > "$unit_path"
      temporary_unit_paths+=("$unit_path")
    else
      for unit in "${target_units[@]}"; do
        unit_path="${SYSTEMD_DIR}/${unit}"
        printf '%s\n' "$fault-$unit" > "$unit_path"
        hash="$(sha256sum "$unit_path" | awk '{print $1}')"
        installed_units+=("$unit")
        installed_hashes+=("$hash")
        if [ "$fault" = 'enable' ] || [ "$fault" = 'start' ] || \
          [ "$fault" = 'health' ] || [ "$fault" = 'postcheck' ]; then
          ln -s "../${unit}" "${SYSTEMD_DIR}/multi-user.target.wants/${unit}"
        fi
      done
      if [ "$fault" = 'start' ] || [ "$fault" = 'health' ] || [ "$fault" = 'postcheck' ]; then
        touch "${fixture}/active/noteai-api.service" "${fixture}/active/noteai-admin.service"
        printf '%s|%s\n' "$RECOVERY_OWNER" "$API_IMAGE_ID" > "${fixture}/containers/noteai-api-c"
        printf '%s|%s\n' "$RECOVERY_OWNER" "$ADMIN_IMAGE_ID" > "${fixture}/containers/noteai-admin-c"
        touch "${fixture}/listeners/8000" "${fixture}/listeners/8001"
      fi
    fi
    rollback_mutation
    [ -z "$(find "$SYSTEMD_DIR" -mindepth 1 ! -type d -print -quit)" ]
    [ -z "$(find "$fixture/containers" "$fixture/listeners" "$fixture/active" -type f -print -quit)" ]
  done

  unit_path="${SYSTEMD_DIR}/noteai-api.service"
  printf 'stop-failure\n' > "$unit_path"
  installed_units=(noteai-api.service)
  installed_hashes=("$(sha256sum "$unit_path" | awk '{print $1}')")
  temporary_unit_paths=()
  target_units=(noteai-api.service)
  target_containers=(noteai-api-c)
  target_ports=(8000)
  target_image_ids=("$API_IMAGE_ID")
  touch "${fixture}/active/noteai-api.service"
  printf '%s|%s\n' "$RECOVERY_OWNER" "$API_IMAGE_ID" > "${fixture}/containers/noteai-api-c"
  cleanup_unknown=0
  OFFLINE_STOP_FAIL=1
  if rollback_mutation; then
    return 1
  fi
  [ "$cleanup_unknown" = '1' ]
  unset OFFLINE_STOP_FAIL
  printf 'NOTEAI_RUNTIME_RECOVERY_ROLLBACK_SELF_TEST=PASS faults=7 cleanup_failure=fail_closed\n'
}

remove_task_root() {
  if [ "$task_root_owned" = '1' ]; then
    [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || return 1
    rm -rf -- "$TASK_ROOT" || return 1
    task_root_owned=0
  fi
}

rollback_mutation() {
  local index
  local unit
  local expected_hash
  local actual_hash

  for ((index=${#installed_units[@]} - 1; index >= 0; index--)); do
    unit="${installed_units[$index]}"
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
      systemctl stop "$unit" >/dev/null 2>&1 || cleanup_unknown=1
    fi
    if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
      systemctl disable "$unit" >/dev/null 2>&1 || cleanup_unknown=1
    fi
  done
  for index in "${!target_containers[@]}"; do
    if ! container_is_absent "${target_containers[$index]}"; then
      if container_is_owned "${target_containers[$index]}" "${target_image_ids[$index]}"; then
        docker container rm --force "${target_containers[$index]}" >/dev/null 2>&1 || cleanup_unknown=1
      else
        cleanup_unknown=1
      fi
    fi
  done
  if [ "${#temporary_unit_paths[@]}" -gt '0' ]; then
    for unit in "${temporary_unit_paths[@]}"; do
      if [ -e "$unit" ] || [ -L "$unit" ]; then
        if [ -f "$unit" ] && [ ! -L "$unit" ]; then
          rm -f -- "$unit" || cleanup_unknown=1
        else
          cleanup_unknown=1
        fi
      fi
    done
  fi
  for ((index=${#installed_units[@]} - 1; index >= 0; index--)); do
    unit="${installed_units[$index]}"
    expected_hash="${installed_hashes[$index]}"
    if [ -f "${SYSTEMD_DIR}/${unit}" ] && [ ! -L "${SYSTEMD_DIR}/${unit}" ]; then
      actual_hash="$(sha256sum "${SYSTEMD_DIR}/${unit}" | awk '{print $1}')"
      if [ "$actual_hash" = "$expected_hash" ]; then
        rm -f -- "${SYSTEMD_DIR}/${unit}" || cleanup_unknown=1
      else
        cleanup_unknown=1
      fi
    fi
  done
  systemctl daemon-reload >/dev/null 2>&1 || cleanup_unknown=1
  for index in "${!target_units[@]}"; do
    unit_is_absent "${target_units[$index]}" || cleanup_unknown=1
    container_is_absent "${target_containers[$index]}" || cleanup_unknown=1
    [ "$(port_listener_count "${target_ports[$index]}")" = '0' ] || cleanup_unknown=1
  done
  [ "$cleanup_unknown" = '0' ]
}

on_exit() {
  local exit_code=$?
  local cleanup_exit=0
  trap - EXIT
  if [ "$success" != '1' ] && [ "$mutation_started" = '1' ]; then
    phase='rollback'
    rollback_mutation || cleanup_exit=1
  fi
  remove_task_root || cleanup_exit=1
  if [ "$cleanup_exit" != '0' ]; then
    printf 'NOTEAI_RUNTIME_RECOVERY=CLEANUP_UNKNOWN phase=%s\n' "$phase" >&2
    exit 1
  fi
  exit "$exit_code"
}

install_unit() {
  local unit="$1"
  local source_path="${TASK_ROOT}/${unit}"
  local target_path="${SYSTEMD_DIR}/${unit}"
  local temporary_path="${SYSTEMD_DIR}/.${unit}.noteai-recovery.$$"
  local expected_hash

  expected_hash="$(sha256sum "$source_path" | awk '{print $1}')"
  [ ! -e "$temporary_path" ] && [ ! -L "$temporary_path" ]
  [ ! -e "$target_path" ] && [ ! -L "$target_path" ]
  temporary_unit_paths+=("$temporary_path")
  installed_units+=("$unit")
  installed_hashes+=("$expected_hash")
  mutation_started=1
  install -o root -g root -m 0644 "$source_path" "$temporary_path"
  [ "$(sha256sum "$temporary_path" | awk '{print $1}')" = "$expected_hash" ]
  ln "$temporary_path" "$target_path"
  rm -f -- "$temporary_path"
}

wait_for_ready() {
  local role="$1"
  local port="$2"
  local container="$3"
  local attempt
  local status
  local body="${TASK_ROOT}/${role}.wait.json"
  for attempt in $(seq 1 90); do
    status="$(curl --noproxy '*' --silent --show-error --output "$body" \
      --write-out '%{http_code}' --connect-timeout 2 --max-time 8 \
      "http://127.0.0.1:${port}/health/ready" 2>/dev/null || true)"
    if [ "$status" = '200' ] && validate_health_body "$role" ready "$body" && \
      [ "$(docker container inspect "$container" --format '{{.State.Running}}' 2>/dev/null)" = 'true' ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

validate_health_body() {
  local role="$1"
  local endpoint="$2"
  local body="$3"
  if [ "$endpoint" = 'live' ]; then
    jq -e --arg service "noteai-${role}" \
      '.status == "ok" and .service == $service' "$body" >/dev/null
  elif [ "$role" = 'api' ]; then
    jq -e '
      .status == "ready" and .service == "noteai-api" and
      (.checks | keys) == ["database", "model"] and
      .checks.database.ok == true and .checks.model.ok == true
    ' "$body" >/dev/null
  else
    jq -e '
      .status == "ready" and .service == "noteai-admin" and
      (.checks | keys) == ["admin_credentials", "database"] and
      .checks.admin_credentials.ok == true and .checks.database.ok == true
    ' "$body" >/dev/null
  fi
}

health_request() {
  local role="$1"
  local port="$2"
  local endpoint="$3"
  local round="$4"
  local body="${TASK_ROOT}/${role}.${endpoint}.${round}.json"
  local status
  status="$(curl --noproxy '*' --silent --show-error --output "$body" \
    --write-out '%{http_code}' --connect-timeout 2 --max-time 10 \
    "http://127.0.0.1:${port}/health/${endpoint}")"
  [ "$status" = '200' ] && validate_health_body "$role" "$endpoint" "$body"
}

verify_runtime_env() {
  local role="$1"
  local container="$2"
  if [ "$role" = 'api' ]; then
    docker exec "$container" /bin/sh -c '
      test "$NOTEAI_RUNTIME_ROLE" = api &&
      test "$NOTEAI_DEPLOYMENT_STAGE" = production &&
      test "$NOTEAI_CLOUD_RUNTIME" = 1 &&
      test "$NOTEAI_API_STARTS_TREND_SCHEDULER" = 0 &&
      test "$NOTEAI_MODEL_ARTIFACT_REQUIRED" = 1 &&
      test "$NOTEAI_ENABLE_CLOUD_MODEL_MUTATION" = 0 &&
      test "$NOTEAI_DURABLE_AI_ADMISSION_ENABLED" = 0 &&
      test "$NOTEAI_TRUSTED_PROXY_IPS" = 127.0.0.1 &&
      test "$PGOPTIONS" = "-c default_transaction_read_only=on" &&
      test -n "$DATABASE_URL" &&
      test -n "$NOTEAI_PRIVATE_STORAGE_BACKEND" &&
      test -n "$NOTEAI_OSS_PRIVATE_BUCKET" &&
      test -n "$NOTEAI_OSS_REGION" &&
      test -n "$NOTEAI_OSS_ENDPOINT" &&
      test -n "$NOTEAI_OSS_RAM_ROLE" &&
      test -n "$NOTEAI_PRIVATE_STORAGE_KEY_EPOCH" &&
      test -n "$NOTEAI_OSS_KEY_PREFIX"
    ' >/dev/null
  else
    docker exec "$container" /bin/sh -c '
      test "$NOTEAI_RUNTIME_ROLE" = admin &&
      test "$NOTEAI_DEPLOYMENT_STAGE" = production &&
      test "$NOTEAI_CLOUD_RUNTIME" = 1 &&
      test "$NOTEAI_SKIP_MODEL_ARTIFACT_CHECK" = 1 &&
      test "$NOTEAI_ENABLE_CLOUD_MODEL_MUTATION" = 0 &&
      test "$PORT" = 8001 &&
      test "$PGOPTIONS" = "-c default_transaction_read_only=on" &&
      test -n "$DATABASE_URL" &&
      test -n "$ADMIN_PASSWORD"
    ' >/dev/null
  fi
}

verify_container_shape() {
  local role="$1"
  local container="$2"
  local image_ref="$3"
  local image_id="$4"
  local port="$5"
  local memory="$6"
  local cpus="$7"
  local tmpfs_value
  local expected_bindings

  expected_bindings="{\"${port}/tcp\":[{\"HostIp\":\"127.0.0.1\",\"HostPort\":\"${port}\"}]}"
  [ "$(docker container inspect "$container" --format '{{.Image}}')" = "$image_id" ]
  [ "$(docker container inspect "$container" --format '{{.Config.Image}}')" = "$image_ref" ]
  [ "$(docker container inspect "$container" --format '{{.Config.User}}')" = '999:999' ]
  [ "$(docker container inspect "$container" --format '{{.State.Running}}')" = 'true' ]
  [ "$(docker container inspect "$container" --format '{{.RestartCount}}')" = '0' ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.ReadonlyRootfs}}')" = 'true' ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.Privileged}}')" = 'false' ]
  [ "$(docker container inspect "$container" --format '{{json .HostConfig.CapDrop}}')" = '["ALL"]' ]
  case "$(docker container inspect "$container" --format '{{json .HostConfig.CapAdd}}')" in null|'[]') ;; *) return 1 ;; esac
  [ "$(docker container inspect "$container" --format '{{json .HostConfig.SecurityOpt}}')" = '["no-new-privileges:true"]' ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.RestartPolicy.Name}}')" = 'no' ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.AutoRemove}}')" = 'true' ]
  [ "$(docker container inspect "$container" --format '{{index .Config.Labels "com.noteai.recovery.owner"}}')" = "$RECOVERY_OWNER" ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.Memory}}')" = "$memory" ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.NanoCpus}}')" = "$cpus" ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.PidsLimit}}')" = '512' ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.NetworkMode}}')" = 'bridge' ]
  [ "$(docker container inspect "$container" --format '{{.HostConfig.IpcMode}}')" = 'private' ]
  [ -z "$(docker container inspect "$container" --format '{{.HostConfig.PidMode}}')" ]
  [ "$(docker container inspect "$container" --format '{{json .HostConfig.PortBindings}}')" = "$expected_bindings" ]
  [ "$(docker container inspect "$container" --format '{{len .Mounts}}')" = '1' ]
  [ "$(docker container inspect "$container" --format '{{(index .Mounts 0).Type}}|{{(index .Mounts 0).Source}}|{{(index .Mounts 0).Destination}}|{{(index .Mounts 0).RW}}')" = "bind|${DATA_DIR}|/app/model/data|true" ]
  [ "$(docker container inspect "$container" --format '{{len .HostConfig.Tmpfs}}')" = '1' ]
  tmpfs_value="$(docker container inspect "$container" --format '{{index .HostConfig.Tmpfs "/tmp"}}')"
  case ",${tmpfs_value}," in *,noexec,*nosuid,*nodev,*) ;; *) return 1 ;; esac
  verify_runtime_env "$role" "$container"
}

verify_listener() {
  local port="$1"
  local listeners
  listeners="$(ss -H -ltn 2>/dev/null | awk -v suffix=":${port}" '$4 ~ suffix "$" {print $4}')"
  [ "$listeners" = "127.0.0.1:${port}" ]
}

verify_service() {
  local unit="$1"
  local expected_hash="$2"
  [ "$(systemctl is-active "$unit")" = 'active' ]
  [ "$(systemctl is-enabled "$unit")" = 'enabled' ]
  [ "$(systemctl show "$unit" --property=Result --value)" = 'success' ]
  [ "$(sha256sum "${SYSTEMD_DIR}/${unit}" | awk '{print $1}')" = "$expected_hash" ]
}

verify_no_container_connections() {
  local container="$1"
  [ "$(docker exec "$container" /bin/sh -c \
    "awk 'NR > 1 && \$4 == \"01\" {count++} END {print count + 0}' /proc/net/tcp /proc/net/tcp6")" = '0' ]
}

if [ "${1:-}" = '--offline-self-test' ]; then
  [ "$#" = '1' ]
  offline_self_test
  exit 0
fi
if [ "${1:-}" = '--offline-rollback-self-test' ]; then
  [ "$#" = '1' ]
  offline_rollback_self_test
  exit 0
fi

trap on_exit EXIT

[ "$#" = '1' ] || fail usage
host_role="$1"
case "$host_role" in
  API-C)
    target_units=(noteai-api.service noteai-admin.service)
    target_containers=(noteai-api-c noteai-admin-c)
    target_ports=(8000 8001)
    target_image_ids=("$API_IMAGE_ID" "$ADMIN_IMAGE_ID")
    ;;
  API-F)
    target_units=(noteai-api.service)
    target_containers=(noteai-api-f)
    target_ports=(8000)
    target_image_ids=("$API_IMAGE_ID")
    ;;
  *) fail host_role ;;
esac

phase='host_preflight'
[ "$(id -u)" = '0' ] || fail root_required
[ "$(uname -s)" = 'Linux' ] || fail linux_required
[ "$(uname -m)" = 'x86_64' ] || fail amd64_required
for command_name in awk cat curl docker find grep install jq ln readlink rm seq sha256sum sleep sort ss stat systemctl systemd-analyze uniq; do
  command -v "$command_name" >/dev/null || fail missing_command
done
[ "$(docker context show)" = 'default' ] || fail docker_context
[ "$(docker context inspect default --format '{{.Endpoints.docker.Host}}')" = 'unix:///var/run/docker.sock' ] || fail docker_socket
[ -S /var/run/docker.sock ] || fail docker_socket
[ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] || fail task_root_exists
[ -d "$DATA_DIR" ] && [ ! -L "$DATA_DIR" ] || fail data_directory
[ "$(readlink -f "$DATA_DIR")" = "$DATA_DIR" ] || fail data_directory
[ "$(stat -c '%u:%g' "$DATA_DIR")" = '999:999' ] || fail data_owner
data_permissions="$(stat -c '%A' "$DATA_DIR")"
[ "${data_permissions:2:1}" = 'w' ] || fail data_not_writable
[ "$(database_connection_count)" = '0' ] || fail database_connection_baseline
[ -z "$(docker ps -a --format '{{.Names}}' | awk '/^noteai-/ {print}')" ] || fail unexpected_runtime
for index in "${!target_units[@]}"; do
  unit_is_absent "${target_units[$index]}" || fail unit_not_absent
  container_is_absent "${target_containers[$index]}" || fail container_not_absent
  [ "$(port_listener_count "${target_ports[$index]}")" = '0' ] || fail listener_not_absent
done

install -d -o root -g root -m 0700 "$TASK_ROOT"
task_root_owned=1

phase='secret_metadata_preflight'
validate_host_secret_topology || fail host_secret_topology
validate_env_file "$API_ENV" api || fail api_env_contract
discover_storage_env || fail storage_env_contract
if [ "$host_role" = 'API-C' ]; then
  validate_env_file "$ADMIN_ENV" admin || fail admin_env_contract
fi

phase='cached_image_preflight'
verify_image "$API_IMAGE" "$API_IMAGE_ID" "$API_REVISION" api '["/app/scripts/render_start_api.sh"]' || fail api_image_contract
if [ "$host_role" = 'API-C' ]; then
  verify_image "$ADMIN_IMAGE" "$ADMIN_IMAGE_ID" "$ADMIN_REVISION" admin '["/app/scripts/render_start_admin.sh"]' || fail admin_image_contract
fi

phase='unit_render_and_verify'
if [ "$host_role" = 'API-C' ]; then
  render_api_unit "${TASK_ROOT}/noteai-api.service" noteai-api-c "$storage_env"
  render_admin_unit "${TASK_ROOT}/noteai-admin.service"
  systemd-analyze verify "${TASK_ROOT}/noteai-api.service" "${TASK_ROOT}/noteai-admin.service" >/dev/null
else
  render_api_unit "${TASK_ROOT}/noteai-api.service" noteai-api-f "$storage_env"
  systemd-analyze verify "${TASK_ROOT}/noteai-api.service" >/dev/null
fi

phase='unit_install'
for unit in "${target_units[@]}"; do
  install_unit "$unit"
done
systemctl daemon-reload >/dev/null

phase='unit_enable'
for unit in "${target_units[@]}"; do
  systemctl enable "$unit" >/dev/null
done

phase='unit_start'
for unit in "${target_units[@]}"; do
  systemctl start "$unit" >/dev/null
done

phase='bounded_startup_wait'
wait_for_ready api 8000 "${target_containers[0]}" || fail api_startup_timeout
if [ "$host_role" = 'API-C' ]; then
  wait_for_ready admin 8001 noteai-admin-c || fail admin_startup_timeout
fi

phase='runtime_shape_validation'
verify_container_shape api "${target_containers[0]}" "$API_IMAGE" "$API_IMAGE_ID" 8000 1610612736 2000000000 || fail api_runtime_shape
verify_listener 8000 || fail api_listener
verify_service noteai-api.service "${installed_hashes[0]}" || fail api_service
if [ "$host_role" = 'API-C' ]; then
  verify_container_shape admin noteai-admin-c "$ADMIN_IMAGE" "$ADMIN_IMAGE_ID" 8001 1073741824 1000000000 || fail admin_runtime_shape
  verify_listener 8001 || fail admin_listener
  verify_service noteai-admin.service "${installed_hashes[1]}" || fail admin_service
fi

phase='three_round_health_acceptance'
for round in 1 2 3; do
  health_request api 8000 live "$round" || fail api_live
  health_request api 8000 ready "$round" || fail api_ready
  if [ "$host_role" = 'API-C' ]; then
    health_request admin 8001 live "$round" || fail admin_live
    health_request admin 8001 ready "$round" || fail admin_ready
  fi
done

phase='final_zero_residue_check'
[ "$(database_connection_count)" = '0' ] || fail database_connection_residue
verify_no_container_connections "${target_containers[0]}" || fail api_network_residue
if [ "$host_role" = 'API-C' ]; then
  verify_no_container_connections noteai-admin-c || fail admin_network_residue
fi
[ "$(docker ps -a --format '{{.Names}}' | awk '/^noteai-/ {count++} END {print count + 0}')" = "${#target_containers[@]}" ] || fail unexpected_runtime_final

phase='success_cleanup'
remove_task_root || fail task_root_cleanup
success=1
phase='success'
printf 'NOTEAI_RUNTIME_RECOVERY=PASS host_role=%s units=%s health_rounds=3 loopback_only=1 cached_images_only=1 database_write_commands=0 public_network_commands=0\n' \
  "$host_role" "${#target_units[@]}"
