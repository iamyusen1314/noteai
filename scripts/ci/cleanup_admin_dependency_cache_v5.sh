#!/usr/bin/env bash
set -uo pipefail
umask 077

# Aggregate every cleanup control, emit only bounded status enums, and remove
# both exact task-owned roots even when an earlier control fails closed.

runner_temp="${RUNNER_TEMP:-}"
docker_config="${DOCKER_CONFIG:-}"
buildx_config="${BUILDX_CONFIG:-}"
producer_builder="${NOTEAI_PRODUCER_BUILDER:-}"
consumer_builder="${NOTEAI_CONSUMER_BUILDER:-}"
transient_verifier="${NOTEAI_TRANSIENT_STATE_VERIFIER_PATH:-}"
transient_verifier_sha256="${NOTEAI_TRANSIENT_STATE_VERIFIER_SHA256:-}"
base_verifier="${NOTEAI_V4_TRANSIENT_VERIFIER_PATH:-}"
base_verifier_sha256="${NOTEAI_V4_TRANSIENT_VERIFIER_SHA256:-}"
receipt_path="${NOTEAI_CLEANUP_RECEIPT_PATH:-}"
pre_cleanup_deadline_epoch="${NOTEAI_PRE_CLEANUP_DEADLINE_EPOCH:-}"
cleanup_deadline_epoch="${NOTEAI_CLEANUP_DEADLINE_EPOCH:-}"
cleanup_command_timeout_seconds="${NOTEAI_CLEANUP_COMMAND_TIMEOUT_SECONDS:-}"

if [[ "${runner_temp}" != /* ]] ||
  [[ ! -d "${runner_temp}" ]] ||
  [[ -L "${runner_temp}" ]] ||
  [[ "${docker_config}" != "${runner_temp}/noteai-empty-docker-config-v5" ]] ||
  [[ "${buildx_config}" != "${runner_temp}/noteai-buildx-state-v5" ]] ||
  [[ "${docker_config}" == "${buildx_config}" ]] ||
  [[ "${receipt_path}" != "${runner_temp}/noteai-admin-dependency-cache-cleanup-v5.json" ]]
then
  echo "unsafe transient-state cleanup roots" >&2
  exit 2
fi

current_epoch="$(date +%s 2>/dev/null || printf '0')"
deadline_control_valid=true
if [[ ! "${current_epoch}" =~ ^[0-9]+$ ]] ||
  [[ ! "${pre_cleanup_deadline_epoch}" =~ ^[0-9]+$ ]] ||
  [[ ! "${cleanup_deadline_epoch}" =~ ^[0-9]+$ ]] ||
  [[ "${cleanup_command_timeout_seconds}" != "15" ]] ||
  (( cleanup_deadline_epoch - pre_cleanup_deadline_epoch != 600 )) ||
  (( cleanup_deadline_epoch <= current_epoch )) ||
  (( cleanup_deadline_epoch - current_epoch > 6300 )) ||
  ! command -v timeout >/dev/null 2>&1
then
  deadline_control_valid=false
  pre_cleanup_deadline_epoch="${current_epoch}"
  cleanup_deadline_epoch="$((current_epoch + 240))"
  cleanup_command_timeout_seconds="15"
fi

# Docker calls stop first, exact-root removal stops next, and the last thirty
# seconds remain reserved for a bounded, atomic receipt.
docker_deadline_epoch="$((cleanup_deadline_epoch - 90))"
root_deadline_epoch="$((cleanup_deadline_epoch - 30))"

run_bounded_until() {
  local deadline_epoch="$1"
  local maximum_seconds="$2"
  shift 2
  local now_epoch
  local remaining_seconds
  local timeout_seconds

  now_epoch="$(date +%s 2>/dev/null || printf '0')"
  if [[ ! "${now_epoch}" =~ ^[0-9]+$ ]]; then
    return 124
  fi
  remaining_seconds="$((deadline_epoch - now_epoch))"
  if (( remaining_seconds <= 0 )); then
    return 124
  fi
  timeout_seconds="${maximum_seconds}"
  if (( timeout_seconds > remaining_seconds )); then
    timeout_seconds="${remaining_seconds}"
  fi
  timeout \
    --signal=TERM \
    --kill-after=5s \
    "${timeout_seconds}s" \
    "$@"
}

run_cleanup_command() {
  run_bounded_until \
    "${docker_deadline_epoch}" \
    "${cleanup_command_timeout_seconds}" \
    "$@"
}

run_root_command() {
  run_bounded_until \
    "${root_deadline_epoch}" \
    "${cleanup_command_timeout_seconds}" \
    "$@"
}

client_token_disabled=false
if [[ "${BUILDKIT_NO_CLIENT_TOKEN:-}" == "1" ]]; then
  client_token_disabled=true
fi

verifier_ready=true
if [[ -z "${transient_verifier}" ]] ||
  [[ -z "${transient_verifier_sha256}" ]] ||
  [[ ! -f "${transient_verifier}" ]] ||
  [[ -L "${transient_verifier}" ]] ||
  [[ "$(sha256sum "${transient_verifier}" 2>/dev/null | awk '{print $1}')" != "${transient_verifier_sha256}" ]] ||
  [[ -z "${base_verifier}" ]] ||
  [[ -z "${base_verifier_sha256}" ]] ||
  [[ ! -f "${base_verifier}" ]] ||
  [[ -L "${base_verifier}" ]] ||
  [[ "$(sha256sum "${base_verifier}" 2>/dev/null | awk '{print $1}')" != "${base_verifier_sha256}" ]]
then
  verifier_ready=false
fi

validate_state() {
  run_cleanup_command \
    python3 "${transient_verifier}" \
    --base-verifier "${base_verifier}" \
    --runner-temp "${runner_temp}" \
    --docker-config "${docker_config}" \
    --buildx-config "${buildx_config}" \
    --phase cleanup-active \
    >/dev/null 2>&1
}

pre_state="unknown"
if [[ ! -e "${docker_config}" ]] &&
  [[ ! -L "${docker_config}" ]] &&
  [[ ! -e "${buildx_config}" ]] &&
  [[ ! -L "${buildx_config}" ]]
then
  pre_state="not_created"
elif [[ "${verifier_ready}" != "true" ]]; then
  pre_state="verifier_unavailable"
elif validate_state; then
  pre_state="pass"
else
  pre_state="drift"
fi

producer_builder_remove="fail"
producer_builder_absent="unknown"
consumer_builder_remove="fail"
consumer_builder_absent="unknown"

remove_and_prove_absent() {
  local builder_name="$1"
  local builder_label="$2"
  local remove_status_var="$3"
  local absent_status_var="$4"
  local before_file="${runner_temp}/noteai-${builder_label}-builder-before"
  local after_file="${runner_temp}/noteai-${builder_label}-builder-after"
  local before_known=false
  local before_present=false
  local remove_rc=0

  if [[ ! "${builder_name}" =~ ^noteai-admin-cache-v5-(producer|consumer)-[0-9]+$ ]]; then
    printf -v "${remove_status_var}" '%s' "fail"
    printf -v "${absent_status_var}" '%s' "unknown"
    return
  fi
  if run_cleanup_command \
    docker buildx ls --format '{{.Name}}' >"${before_file}" 2>/dev/null
  then
    before_known=true
    if grep -Fxq -- "${builder_name}" "${before_file}"; then
      before_present=true
    fi
  fi

  run_cleanup_command \
    docker buildx rm "${builder_name}" >/dev/null 2>&1 || remove_rc=$?

  if run_cleanup_command \
    docker buildx ls --format '{{.Name}}' >"${after_file}" 2>/dev/null
  then
    if grep -Fxq -- "${builder_name}" "${after_file}"; then
      printf -v "${absent_status_var}" '%s' "fail"
      printf -v "${remove_status_var}" '%s' "fail"
    else
      printf -v "${absent_status_var}" '%s' "pass"
      if [[ "${before_known}" == "true" ]] &&
        [[ "${before_present}" != "true" ]]
      then
        printf -v "${remove_status_var}" '%s' "already_absent"
      elif [[ "${remove_rc}" -eq 0 ]]; then
        printf -v "${remove_status_var}" '%s' "removed"
      else
        printf -v "${remove_status_var}" '%s' \
          "rm_nonzero_absent_after"
      fi
    fi
  else
    printf -v "${absent_status_var}" '%s' "unknown"
    printf -v "${remove_status_var}" '%s' "fail"
  fi
}

remove_and_prove_absent \
  "${producer_builder}" \
  producer \
  producer_builder_remove \
  producer_builder_absent
remove_and_prove_absent \
  "${consumer_builder}" \
  consumer \
  consumer_builder_remove \
  consumer_builder_absent

validate_snapshot_file() {
  local path="$1"
  local kind="$2"
  python3 - "${path}" "${kind}" <<'PY' >/dev/null 2>&1
import os
import re
import stat
import sys

path, kind = sys.argv[1:]
patterns = {
    "images": re.compile(r"sha256:[0-9a-f]{64}"),
    "containers": re.compile(r"[0-9a-f]{64}"),
    "volumes": re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}"),
    "networks": re.compile(r"[0-9a-f]{64}"),
}
try:
    metadata = os.lstat(path)
    payload = open(path, "rb").read()
except OSError:
    raise SystemExit(1)
if not stat.S_ISREG(metadata.st_mode):
    raise SystemExit(1)
if metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit(1)
if len(payload) > 1_048_576 or b"\0" in payload:
    raise SystemExit(1)
if payload and not payload.endswith(b"\n"):
    raise SystemExit(1)
try:
    values = payload.decode("ascii").splitlines()
except UnicodeDecodeError:
    raise SystemExit(1)
if values != sorted(set(values)):
    raise SystemExit(1)
pattern = patterns.get(kind)
if pattern is None or any(pattern.fullmatch(value) is None for value in values):
    raise SystemExit(1)
PY
}

validate_baseline_marker() {
  local marker_path="$1"
  python3 - "${marker_path}" <<'PY' >/dev/null 2>&1
import os
import stat
import sys

try:
    metadata = os.lstat(sys.argv[1])
    payload = open(sys.argv[1], "rb").read()
except OSError:
    raise SystemExit(1)
if not stat.S_ISREG(metadata.st_mode):
    raise SystemExit(1)
if metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit(1)
if payload != b"noteai-docker-baseline-v5=complete\n":
    raise SystemExit(1)
PY
}

baseline_marker="${runner_temp}/noteai-docker-baseline-v5.complete"
images_before="${runner_temp}/noteai-images-before"
containers_before="${runner_temp}/noteai-containers-before"
volumes_before="${runner_temp}/noteai-volumes-before"
networks_before="${runner_temp}/noteai-networks-before"
docker_baseline_state="invalid"
if validate_baseline_marker "${baseline_marker}" &&
  validate_snapshot_file "${images_before}" images &&
  validate_snapshot_file "${containers_before}" containers &&
  validate_snapshot_file "${volumes_before}" volumes &&
  validate_snapshot_file "${networks_before}" networks
then
  docker_baseline_state="pass"
fi

capture_snapshot() {
  local kind="$1"
  local output_path="$2"
  shift 2
  local temporary_path="${output_path}.tmp"

  if [[ -e "${output_path}" ]] ||
    [[ -L "${output_path}" ]] ||
    [[ -e "${temporary_path}" ]] ||
    [[ -L "${temporary_path}" ]]
  then
    return 1
  fi
  if ! run_cleanup_command "$@" |
    LC_ALL=C sort -u >"${temporary_path}"
  then
    rm -f -- "${temporary_path}" >/dev/null 2>&1 || true
    return 1
  fi
  if ! chmod 0600 "${temporary_path}" ||
    ! validate_snapshot_file "${temporary_path}" "${kind}" ||
    ! mv -- "${temporary_path}" "${output_path}"
  then
    rm -f -- "${temporary_path}" >/dev/null 2>&1 || true
    return 1
  fi
}

new_images_remove="unknown"
images_parity="unknown"
containers_parity="unknown"
volumes_parity="unknown"
networks_parity="unknown"
images_after_builders="${runner_temp}/noteai-images-after-builders"
new_image_ids="${runner_temp}/noteai-new-image-ids"

if [[ "${docker_baseline_state}" == "pass" ]] &&
  capture_snapshot \
    images \
    "${images_after_builders}" \
    docker image ls --all --no-trunc --quiet
then
  if comm -13 \
    "${images_before}" \
    "${images_after_builders}" \
    >"${new_image_ids}"
  then
    chmod 0600 "${new_image_ids}" >/dev/null 2>&1 || true
    new_images_remove="not_needed"
    image_removal_attempted=false
    image_removal_failed=false
    while IFS= read -r image_id; do
      if [[ -n "${image_id}" ]]; then
        image_removal_attempted=true
        if ! run_cleanup_command \
          docker image rm -- "${image_id}" >/dev/null 2>&1
        then
          image_removal_failed=true
        fi
      fi
    done <"${new_image_ids}"
    if [[ "${image_removal_failed}" == "true" ]]; then
      new_images_remove="fail"
    elif [[ "${image_removal_attempted}" == "true" ]]; then
      new_images_remove="removed"
    fi
  else
    new_images_remove="fail"
  fi

  if capture_snapshot \
    images \
    "${runner_temp}/noteai-images-after" \
    docker image ls --all --no-trunc --quiet
  then
    if cmp -s "${images_before}" "${runner_temp}/noteai-images-after"; then
      images_parity="pass"
    else
      images_parity="fail"
    fi
  fi
  if capture_snapshot \
    containers \
    "${runner_temp}/noteai-containers-after" \
    docker container ls --all --no-trunc --quiet
  then
    if cmp -s \
      "${containers_before}" \
      "${runner_temp}/noteai-containers-after"
    then
      containers_parity="pass"
    else
      containers_parity="fail"
    fi
  fi
  if capture_snapshot \
    volumes \
    "${runner_temp}/noteai-volumes-after" \
    docker volume ls --quiet
  then
    if cmp -s "${volumes_before}" "${runner_temp}/noteai-volumes-after"; then
      volumes_parity="pass"
    else
      volumes_parity="fail"
    fi
  fi
  if capture_snapshot \
    networks \
    "${runner_temp}/noteai-networks-after" \
    docker network ls --no-trunc --quiet
  then
    if cmp -s \
      "${networks_before}" \
      "${runner_temp}/noteai-networks-after"
    then
      networks_parity="pass"
    else
      networks_parity="fail"
    fi
  fi
fi

post_builder_state="unknown"
if [[ ! -e "${docker_config}" ]] &&
  [[ ! -L "${docker_config}" ]] &&
  [[ ! -e "${buildx_config}" ]] &&
  [[ ! -L "${buildx_config}" ]]
then
  post_builder_state="not_created"
elif [[ "${verifier_ready}" != "true" ]]; then
  post_builder_state="verifier_unavailable"
elif validate_state; then
  post_builder_state="pass"
else
  post_builder_state="drift"
fi

remove_exact_root() {
  local target="$1"
  if [[ -L "${target}" ]]; then
    run_root_command rm -f -- "${target}" >/dev/null 2>&1 || return 1
  elif [[ -d "${target}" ]]; then
    run_root_command chmod u+rwx "${target}" >/dev/null 2>&1 ||
      return 1
    run_root_command \
      rm -rf --one-file-system -- "${target}" >/dev/null 2>&1 ||
      return 1
  elif [[ -e "${target}" ]]; then
    run_root_command rm -f -- "${target}" >/dev/null 2>&1 || return 1
  fi
  [[ ! -e "${target}" ]] && [[ ! -L "${target}" ]]
}

docker_root_absent="fail"
buildx_root_absent="fail"
if remove_exact_root "${docker_config}"; then
  docker_root_absent="pass"
fi
if remove_exact_root "${buildx_config}"; then
  buildx_root_absent="pass"
fi

diagnostic_files_absent="pass"
for cleanup_file in \
  "${images_before}" \
  "${containers_before}" \
  "${volumes_before}" \
  "${networks_before}" \
  "${images_before}.tmp" \
  "${containers_before}.tmp" \
  "${volumes_before}.tmp" \
  "${networks_before}.tmp" \
  "${baseline_marker}" \
  "${baseline_marker}.tmp" \
  "${runner_temp}/noteai-producer-builder-before" \
  "${runner_temp}/noteai-producer-builder-after" \
  "${runner_temp}/noteai-consumer-builder-before" \
  "${runner_temp}/noteai-consumer-builder-after" \
  "${images_after_builders}" \
  "${images_after_builders}.tmp" \
  "${new_image_ids}" \
  "${runner_temp}/noteai-images-after" \
  "${runner_temp}/noteai-images-after.tmp" \
  "${runner_temp}/noteai-containers-after" \
  "${runner_temp}/noteai-containers-after.tmp" \
  "${runner_temp}/noteai-volumes-after" \
  "${runner_temp}/noteai-volumes-after.tmp" \
  "${runner_temp}/noteai-networks-after" \
  "${runner_temp}/noteai-networks-after.tmp"
do
  rm -f -- "${cleanup_file}" >/dev/null 2>&1 || true
  if [[ -e "${cleanup_file}" ]] || [[ -L "${cleanup_file}" ]]; then
    diagnostic_files_absent="fail"
  fi
done

cleanup_effective=false
if [[ "${producer_builder_absent}" == "pass" ]] &&
  [[ "${consumer_builder_absent}" == "pass" ]] &&
  [[ "${docker_baseline_state}" == "pass" ]] &&
  [[ "${new_images_remove}" =~ ^(removed|not_needed)$ ]] &&
  [[ "${images_parity}" == "pass" ]] &&
  [[ "${containers_parity}" == "pass" ]] &&
  [[ "${volumes_parity}" == "pass" ]] &&
  [[ "${networks_parity}" == "pass" ]] &&
  [[ "${docker_root_absent}" == "pass" ]] &&
  [[ "${buildx_root_absent}" == "pass" ]] &&
  [[ "${diagnostic_files_absent}" == "pass" ]]
then
  cleanup_effective=true
fi

overall_pass=false
if [[ "${deadline_control_valid}" == "true" ]] &&
  [[ "${client_token_disabled}" == "true" ]] &&
  [[ "${verifier_ready}" == "true" ]] &&
  [[ "${pre_state}" =~ ^(pass|not_created)$ ]] &&
  [[ "${post_builder_state}" =~ ^(pass|not_created)$ ]] &&
  [[ "${producer_builder_remove}" =~ ^(removed|already_absent)$ ]] &&
  [[ "${consumer_builder_remove}" =~ ^(removed|already_absent)$ ]] &&
  [[ "${cleanup_effective}" == "true" ]]
then
  overall_pass=true
fi

if [[ -e "${receipt_path}" ]] || [[ -L "${receipt_path}" ]]; then
  echo "Admin dependency-cache cleanup receipt failed" >&2
  exit 1
fi
receipt_tmp="$(
  mktemp "${runner_temp}/noteai-admin-dependency-cache-cleanup-v5.tmp.XXXXXX"
)" || {
  echo "Admin dependency-cache cleanup receipt failed" >&2
  exit 1
}

if ! jq -n \
  --argjson deadline_control_valid "${deadline_control_valid}" \
  --argjson client_token_disabled "${client_token_disabled}" \
  --arg pre_state "${pre_state}" \
  --arg producer_builder_remove "${producer_builder_remove}" \
  --arg producer_builder_absent "${producer_builder_absent}" \
  --arg consumer_builder_remove "${consumer_builder_remove}" \
  --arg consumer_builder_absent "${consumer_builder_absent}" \
  --arg post_builder_state "${post_builder_state}" \
  --arg docker_baseline_state "${docker_baseline_state}" \
  --arg new_images_remove "${new_images_remove}" \
  --arg images_parity "${images_parity}" \
  --arg containers_parity "${containers_parity}" \
  --arg volumes_parity "${volumes_parity}" \
  --arg networks_parity "${networks_parity}" \
  --arg docker_root_absent "${docker_root_absent}" \
  --arg buildx_root_absent "${buildx_root_absent}" \
  --arg diagnostic_files_absent "${diagnostic_files_absent}" \
  --argjson cleanup_effective "${cleanup_effective}" \
  --argjson overall_pass "${overall_pass}" \
  '{
    schema_version: 2,
    deadline_control_valid: $deadline_control_valid,
    client_token_disabled: $client_token_disabled,
    pre_state: $pre_state,
    producer_builder_remove: $producer_builder_remove,
    producer_builder_absent: $producer_builder_absent,
    consumer_builder_remove: $consumer_builder_remove,
    consumer_builder_absent: $consumer_builder_absent,
    post_builder_state: $post_builder_state,
    docker_baseline_state: $docker_baseline_state,
    new_images_remove: $new_images_remove,
    images_parity: $images_parity,
    containers_parity: $containers_parity,
    volumes_parity: $volumes_parity,
    networks_parity: $networks_parity,
    docker_root_absent: $docker_root_absent,
    buildx_root_absent: $buildx_root_absent,
    diagnostic_files_absent: $diagnostic_files_absent,
    cleanup_effective: $cleanup_effective,
    overall_pass: $overall_pass
  }' >"${receipt_tmp}" ||
  ! chmod 0600 "${receipt_tmp}"
then
  rm -f -- "${receipt_tmp}" >/dev/null 2>&1 || true
  echo "Admin dependency-cache cleanup receipt failed" >&2
  exit 1
fi

receipt_filter='
  type == "object"
  and keys == [
    "buildx_root_absent",
    "cleanup_effective",
    "client_token_disabled",
    "consumer_builder_absent",
    "consumer_builder_remove",
    "containers_parity",
    "deadline_control_valid",
    "diagnostic_files_absent",
    "docker_baseline_state",
    "docker_root_absent",
    "images_parity",
    "networks_parity",
    "new_images_remove",
    "overall_pass",
    "post_builder_state",
    "pre_state",
    "producer_builder_absent",
    "producer_builder_remove",
    "schema_version",
    "volumes_parity"
  ]
  and .schema_version == 2
  and (.deadline_control_valid | type) == "boolean"
  and (.client_token_disabled | type) == "boolean"
  and (.cleanup_effective | type) == "boolean"
  and (.overall_pass | type) == "boolean"
  and (
    .pre_state
    | IN("unknown", "not_created", "verifier_unavailable", "pass", "drift")
  )
  and (
    .post_builder_state
    | IN("unknown", "not_created", "verifier_unavailable", "pass", "drift")
  )
  and (
    .producer_builder_remove
    | IN("fail", "removed", "already_absent", "rm_nonzero_absent_after")
  )
  and (
    .consumer_builder_remove
    | IN("fail", "removed", "already_absent", "rm_nonzero_absent_after")
  )
  and (.producer_builder_absent | IN("unknown", "pass", "fail"))
  and (.consumer_builder_absent | IN("unknown", "pass", "fail"))
  and (.docker_baseline_state | IN("invalid", "pass"))
  and (.new_images_remove | IN("unknown", "fail", "removed", "not_needed"))
  and (.images_parity | IN("unknown", "pass", "fail"))
  and (.containers_parity | IN("unknown", "pass", "fail"))
  and (.volumes_parity | IN("unknown", "pass", "fail"))
  and (.networks_parity | IN("unknown", "pass", "fail"))
  and (.docker_root_absent | IN("pass", "fail"))
  and (.buildx_root_absent | IN("pass", "fail"))
  and (.diagnostic_files_absent | IN("pass", "fail"))
'
if ! jq -e "${receipt_filter}" "${receipt_tmp}" >/dev/null 2>&1 ||
  ! mv -- "${receipt_tmp}" "${receipt_path}"
then
  rm -f -- "${receipt_tmp}" >/dev/null 2>&1 || true
  echo "Admin dependency-cache cleanup receipt failed" >&2
  exit 1
fi

compact_receipt="$(
  jq -c . "${receipt_path}" 2>/dev/null
)" || {
  echo "Admin dependency-cache cleanup receipt failed" >&2
  exit 1
}
printf '%s\n' "${compact_receipt}"
if [[ "${overall_pass}" != "true" ]]; then
  echo "Admin dependency-cache cleanup failed closed" >&2
  exit 1
fi
echo "admin_dependency_cache_cleanup_v5=PASS"
