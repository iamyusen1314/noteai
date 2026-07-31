#!/usr/bin/env bash
set -uo pipefail

# Always remove the exact task-owned credential and Buildx roots.  A failed
# builder removal, Docker parity check, state validation or root removal still
# makes the step fail, but does not short-circuit credential cleanup.

failure_count=0
record_failure() {
  failure_count=$((failure_count + 1))
}

runner_temp="${RUNNER_TEMP:-}"
docker_config="${DOCKER_CONFIG:-}"
buildx_config="${BUILDX_CONFIG:-}"
producer_builder="${NOTEAI_PRODUCER_BUILDER:-}"
consumer_builder="${NOTEAI_CONSUMER_BUILDER:-}"
transient_verifier="${NOTEAI_TRANSIENT_STATE_VERIFIER_PATH:-}"
transient_verifier_sha256="${NOTEAI_TRANSIENT_STATE_VERIFIER_SHA256:-}"

# An unresolved or redirected RUNNER_TEMP is the sole early stop: without this
# lexical trust root, no recursive target can be proven task-owned.
if [[ "${runner_temp}" != /* ]] ||
  [[ ! -d "${runner_temp}" ]] ||
  [[ -L "${runner_temp}" ]] ||
  [[ "${docker_config}" != "${runner_temp}/noteai-empty-docker-config-v4" ]] ||
  [[ "${buildx_config}" != "${runner_temp}/noteai-buildx-state-v4" ]] ||
  [[ "${docker_config}" == "${buildx_config}" ]]
then
  echo "unsafe transient-state cleanup roots" >&2
  exit 2
fi

verifier_ready=1
if [[ -z "${transient_verifier}" ]] ||
  [[ -z "${transient_verifier_sha256}" ]] ||
  [[ ! -f "${transient_verifier}" ]] ||
  [[ -L "${transient_verifier}" ]]
then
  echo "transient-state verifier unavailable" >&2
  record_failure
  verifier_ready=0
elif [[ "$(sha256sum "${transient_verifier}" | awk '{print $1}')" != "${transient_verifier_sha256}" ]]
then
  echo "transient-state verifier drift" >&2
  record_failure
  verifier_ready=0
fi

validate_transient_state() {
  if [[ "${verifier_ready}" -eq 1 ]]; then
    python3 "${transient_verifier}" \
      --runner-temp "${runner_temp}" \
      --docker-config "${docker_config}" \
      --buildx-config "${buildx_config}" ||
      record_failure
  fi
}

remove_builder() {
  local builder_name="$1"
  if [[ -z "${builder_name}" ]]; then
    record_failure
    return
  fi
  docker buildx rm "${builder_name}" >/dev/null 2>&1 || record_failure
}

validate_transient_state
remove_builder "${producer_builder}"
remove_builder "${consumer_builder}"

docker image ls --all --no-trunc --quiet |
  LC_ALL=C sort -u > "${runner_temp}/noteai-images-after-builders" ||
  record_failure
if [[ -f "${runner_temp}/noteai-images-before" ]] &&
  [[ -f "${runner_temp}/noteai-images-after-builders" ]]
then
  comm -13 \
    "${runner_temp}/noteai-images-before" \
    "${runner_temp}/noteai-images-after-builders" \
    > "${runner_temp}/noteai-new-image-ids" ||
    record_failure
  if [[ -f "${runner_temp}/noteai-new-image-ids" ]]; then
    while IFS= read -r image_id; do
      if [[ -n "${image_id}" ]]; then
        docker image rm "${image_id}" >/dev/null || record_failure
      fi
    done < "${runner_temp}/noteai-new-image-ids"
  fi
else
  record_failure
fi

docker image ls --all --no-trunc --quiet |
  LC_ALL=C sort -u > "${runner_temp}/noteai-images-after" ||
  record_failure
docker container ls --all --no-trunc --quiet |
  LC_ALL=C sort -u > "${runner_temp}/noteai-containers-after" ||
  record_failure
docker volume ls --quiet |
  LC_ALL=C sort -u > "${runner_temp}/noteai-volumes-after" ||
  record_failure
docker network ls --no-trunc --quiet |
  LC_ALL=C sort -u > "${runner_temp}/noteai-networks-after" ||
  record_failure

for object_kind in images containers volumes networks; do
  if [[ ! -f "${runner_temp}/noteai-${object_kind}-before" ]] ||
    [[ ! -f "${runner_temp}/noteai-${object_kind}-after" ]] ||
    ! cmp \
      "${runner_temp}/noteai-${object_kind}-before" \
      "${runner_temp}/noteai-${object_kind}-after"
  then
    record_failure
  fi
done

validate_transient_state

# The roots are fixed literal children of RUNNER_TEMP and were resolved above.
# Remove both even after a validation failure so credentials cannot be retained.
rm -rf --one-file-system -- "${docker_config}" || record_failure
rm -rf --one-file-system -- "${buildx_config}" || record_failure
[[ ! -e "${docker_config}" ]] || record_failure
[[ ! -e "${buildx_config}" ]] || record_failure

if [[ "${failure_count}" -ne 0 ]]; then
  echo "Admin dependency-cache cleanup failed closed" >&2
  exit 1
fi
echo "admin_dependency_cache_cleanup=PASS"
