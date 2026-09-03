#!/usr/bin/env bash
set -euo pipefail

# V17 carries the core-validated cache-record hash into the fresh consumer
# check. All solves use the same canonical full-commit Git main context; both
# frozen Dockerfiles are supplied via stdin. Validate, import and replay the
# exact-5335 dependency-only BuildKit cache.
# This helper has two explicit modes:
# - ci_portability: prove a fresh second builder can consume the producer bundle.
# - builder_prewarm: repeat that proof on the paid publication builder.
# Neither mode creates an image, logs in, pushes, deploys or contacts a
# production service/database.

: "${NOTEAI_IMPORT_MODE:?NOTEAI_IMPORT_MODE is required}"
: "${NOTEAI_CACHE_BUNDLE_DIR:?NOTEAI_CACHE_BUNDLE_DIR is required}"
: "${NOTEAI_SOURCE_DIR:?NOTEAI_SOURCE_DIR is required}"
: "${NOTEAI_BUILDX_BUILDER:?NOTEAI_BUILDX_BUILDER is required}"
: "${NOTEAI_IMPORT_EVIDENCE_DIR:?NOTEAI_IMPORT_EVIDENCE_DIR is required}"
: "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH:?NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH is required}"
: "${NOTEAI_BUNDLE_VERIFIER_SHA256:?NOTEAI_BUNDLE_VERIFIER_SHA256 is required}"
: "${NOTEAI_EXPECTED_IMPORT_HELPER_SHA256:?NOTEAI_EXPECTED_IMPORT_HELPER_SHA256 is required}"
: "${BUILDX_BUILDER:?BUILDX_BUILDER is required}"
: "${DOCKER_CONFIG:?DOCKER_CONFIG is required}"

expected_release="5335bdaed933b1f999b5f819c047ec50c11821ae"
expected_tree="38e574e56406ba3380acb78edbe784508cc537cd"
expected_dockerfile="ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447"
expected_prefix="93fd024e5af678b7885bcab8e72d980a9f92cfc70de4f2fd2870284e25b8ec1e"
expected_combined="c665ac4356bec6751d44878a416bbaa278a77df77754f5461ba0adb13f43c2a0"
expected_dockerignore="d327ca46e4800b2af3c073c7e40bac93e0a042fec016fe6b798a5bd6944d3149"
expected_requirements="1ef4150536e98b8057069981b1aadb469ca12f0f30f188a291af2f31e238724a"
expected_requirements_api="0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9"
expected_gitattributes="98faf6b3614dd8619b606b58c8052a2b5f699f3b37a3f1c23035c578a0e24eed"
expected_source="https://github.com/iamyusen1314/noteai"
expected_version="git-5335bda-amd64-r1"
expected_created="2026-07-30T13:29:02Z"
git_context_query="https://github.com/iamyusen1314/noteai.git?ref=${expected_release}&checksum=${expected_release}&submodules=false&mtime=commit&fetch-by-commit=true"
build_timeout_seconds=300

case "${NOTEAI_IMPORT_MODE}" in
  ci_portability)
    : "${NOTEAI_PRODUCER_BUILDER_NAME:?NOTEAI_PRODUCER_BUILDER_NAME is required}"
    ;;
  builder_prewarm)
    : "${NOTEAI_EXPECTED_FINAL_SUMS_SHA256:?NOTEAI_EXPECTED_FINAL_SUMS_SHA256 is required}"
    : "${NOTEAI_PROVIDER_ARTIFACT_TRANSPORT_DIR:?NOTEAI_PROVIDER_ARTIFACT_TRANSPORT_DIR is required}"
    : "${NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH:?NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH is required}"
    : "${NOTEAI_EXPECTED_DOWNLOAD_RECEIPT_SHA256:?NOTEAI_EXPECTED_DOWNLOAD_RECEIPT_SHA256 is required}"
    : "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH:?NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH is required}"
    : "${NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256:?NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256 is required}"
    ;;
  *)
    echo "unsupported import mode" >&2
    exit 2
    ;;
esac

for command_name in docker git jq python3 sha256sum timeout find sort sed cp cmp awk stat; do
  command -v "${command_name}" >/dev/null
done

if [[ "${NOTEAI_IMPORT_MODE}" == "ci_portability" ]]; then
  if [[ ! -d "${NOTEAI_CACHE_BUNDLE_DIR}" ]]; then
    echo "cache bundle directory missing" >&2
    exit 2
  fi
else
  test ! -e "${NOTEAI_CACHE_BUNDLE_DIR}"
  test -d "${NOTEAI_PROVIDER_ARTIFACT_TRANSPORT_DIR}"
  test -f "${NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH}"
  test -f "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}"
  [[ "${NOTEAI_EXPECTED_DOWNLOAD_RECEIPT_SHA256}" =~ ^[0-9a-f]{64}$ ]]
  [[ "${NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256}" =~ ^[0-9a-f]{64}$ ]]
fi
if [[ ! -d "${NOTEAI_SOURCE_DIR}/.git" ]]; then
  echo "exact release source checkout missing" >&2
  exit 2
fi
if [[ -e "${NOTEAI_IMPORT_EVIDENCE_DIR}" ]]; then
  echo "import evidence directory already exists" >&2
  exit 2
fi
if [[ "${BUILDX_BUILDER}" != "${NOTEAI_BUILDX_BUILDER}" ]]; then
  echo "canonical Buildx builder environment differs from prewarm builder" >&2
  exit 2
fi
test -f "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}"
test -f "${DOCKER_CONFIG}/config.json"
jq -e '
  type == "object"
  and (keys == ["auths"])
  and .auths == {}
' "${DOCKER_CONFIG}/config.json" >/dev/null
test "$(stat -c '%a' "${DOCKER_CONFIG}")" = "700"
test "$(stat -c '%a' "${DOCKER_CONFIG}/config.json")" = "600"

check_sha256() {
  local expected="$1"
  local path="$2"
  test "$(sha256sum "${path}" | awk '{print $1}')" = "${expected}"
}

timestamp_ns() {
  python3 - <<'PY'
from datetime import datetime, timezone
import time

value = time.time_ns()
seconds, nanoseconds = divmod(value, 1_000_000_000)
print(
    datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    + f".{nanoseconds:09d}Z"
)
PY
}

write_command_envelope() {
  local output_path="$1"
  local phase="$2"
  local started="$3"
  local completed="$4"
  python3 - "${output_path}" "${phase}" "${started}" "${completed}" <<'PY'
import json
import os
from pathlib import Path
import sys

output = Path(sys.argv[1])
payload = (
    json.dumps(
        {
            "schema_version": "noteai.admin-dependency-cache-command-envelope.v17",
            "phase": sys.argv[2],
            "started": sys.argv[3],
            "completed": sys.argv[4],
        },
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
    )
    + "\n"
).encode("utf-8")
descriptor = os.open(
    output,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
with os.fdopen(descriptor, "wb") as handle:
    handle.write(payload)
    handle.flush()
    os.fsync(handle.fileno())
PY
}
[[ "${NOTEAI_BUNDLE_VERIFIER_SHA256}" =~ ^[0-9a-f]{64}$ ]]
[[ "${NOTEAI_EXPECTED_IMPORT_HELPER_SHA256}" =~ ^[0-9a-f]{64}$ ]]
check_sha256 "${NOTEAI_EXPECTED_IMPORT_HELPER_SHA256}" "$0"
check_sha256 \
  "${NOTEAI_BUNDLE_VERIFIER_SHA256}" \
  "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}"
if [[ "${NOTEAI_IMPORT_MODE}" == "builder_prewarm" ]]; then
  check_sha256 \
    "${NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256}" \
    "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}"
fi

(
  cd "${NOTEAI_SOURCE_DIR}"
  test "$(git rev-parse HEAD)" = "${expected_release}"
  test "$(git rev-parse HEAD^{tree})" = "${expected_tree}"
  test -z "$(git status --short)"
)
check_sha256 "${expected_dockerfile}" "${NOTEAI_SOURCE_DIR}/Dockerfile"
check_sha256 "${expected_dockerignore}" "${NOTEAI_SOURCE_DIR}/.dockerignore"
check_sha256 "${expected_gitattributes}" "${NOTEAI_SOURCE_DIR}/.gitattributes"
check_sha256 "${expected_requirements}" "${NOTEAI_SOURCE_DIR}/model/requirements.txt"
check_sha256 \
  "${expected_requirements_api}" \
  "${NOTEAI_SOURCE_DIR}/model/requirements-api.txt"
test -z "$(
  cd "${NOTEAI_SOURCE_DIR}"
  git ls-tree -r --name-only "${expected_release}" |
    grep -E '^\.gitmodules$' ||
    true
)"

umask 077
task_tmp="$(mktemp -d)"
cache_dir="${task_tmp}/cache"
prefix_dockerfile="${task_tmp}/Dockerfile"
validation_summary="${task_tmp}/bundle-validation.json"
import_summary="${task_tmp}/import-summary.json"
replay_summary="${task_tmp}/replay-summary.json"
if [[ "${NOTEAI_IMPORT_MODE}" == "builder_prewarm" ]]; then
  python3 "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}" \
    verify-transfer \
    --receipt "${NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH}" \
    --expected-receipt-sha256 "${NOTEAI_EXPECTED_DOWNLOAD_RECEIPT_SHA256}" \
    --transport-dir "${NOTEAI_PROVIDER_ARTIFACT_TRANSPORT_DIR}" \
    --bundle "${NOTEAI_CACHE_BUNDLE_DIR}" \
    --bundle-verifier "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" \
    --bundle-verifier-sha256 "${NOTEAI_BUNDLE_VERIFIER_SHA256}" \
    --output "${task_tmp}/provider-transfer-validation.json"
  test -d "${NOTEAI_CACHE_BUNDLE_DIR}"
fi

cleanup() {
  if [[ "${task_tmp}" == /tmp/* || "${task_tmp}" == "${RUNNER_TEMP:-/nonexistent}/"* ]]; then
    rm -rf "${task_tmp}"
  fi
}
trap cleanup EXIT

sed -n '1,80p' "${NOTEAI_SOURCE_DIR}/Dockerfile" > "${prefix_dockerfile}"
check_sha256 "${expected_prefix}" "${prefix_dockerfile}"
printf '%s\n' \
  "" \
  "FROM runtime-common AS noteai-cache-export-anchor" \
  "RUN --network=none printf '%s\\n' noteai-cache-export-anchor-v11" \
  "" \
  "FROM runtime-common AS noteai-cache-import-observer" \
  "RUN --network=none printf '%s\\n' noteai-cache-import-observer-v11" \
  >> "${prefix_dockerfile}"
check_sha256 "${expected_combined}" "${prefix_dockerfile}"
test "$(wc -c < "${prefix_dockerfile}" | tr -d ' ')" = "5191"
test "$(wc -l < "${prefix_dockerfile}" | tr -d ' ')" = "86"
test "$(sed -n '81p' "${NOTEAI_SOURCE_DIR}/Dockerfile")" = ""
test "$(
  sed -n '83p' "${NOTEAI_SOURCE_DIR}/Dockerfile"
)" = "COPY model/ ./model/"

builder_inspect="${task_tmp}/builder-inspect.txt"
docker buildx inspect "${NOTEAI_BUILDX_BUILDER}" --bootstrap > "${builder_inspect}"
test "$(
  awk -F: '
    $1 ~ /^[[:space:]]*Driver[[:space:]]*$/ {
      value = $2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      print value
    }
  ' "${builder_inspect}" |
    sort -u
)" = "docker-container"
buildkit_version="$(
  awk -F: '
    $1 ~ /^[[:space:]]*BuildKit version[[:space:]]*$/ {
      value = $2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      print value
    }
  ' "${builder_inspect}" |
    sort -u
)"
test -n "${buildkit_version}"
test "$(
  awk -F: '
    $1 ~ /^[[:space:]]*BuildKit version[[:space:]]*$/ {
      value = $2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      print value
    }
  ' "${builder_inspect}" |
    sort -u |
    wc -l |
    tr -d ' '
)" = "1"
buildkit_container="buildx_buildkit_${NOTEAI_BUILDX_BUILDER}0"
test "$(
  docker container inspect \
    --format '{{.Name}}' \
    "${buildkit_container}"
)" = "/${buildkit_container}"
buildkit_image_id="$(
  docker container inspect \
    --format '{{.Image}}' \
    "${buildkit_container}"
)"
[[ "${buildkit_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
mapfile -t buildkit_repo_digests < <(
  docker image inspect \
    --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    "${buildkit_image_id}" |
    sed '/^$/d' |
    LC_ALL=C sort -u
)
test "${#buildkit_repo_digests[@]}" -eq 1
buildkit_image_reference="${buildkit_repo_digests[0]}"
[[ "${buildkit_image_reference}" =~ ^(docker.io/)?moby/buildkit@sha256:[0-9a-f]{64}$ ]]

if [[ "${NOTEAI_IMPORT_MODE}" == "ci_portability" ]]; then
  python3 "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" verify-core \
    --bundle "${NOTEAI_CACHE_BUNDLE_DIR}" \
    --extract-to "${cache_dir}" \
    --output "${validation_summary}"
  evidence_dir="${NOTEAI_CACHE_BUNDLE_DIR}/portability"
else
  python3 "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" verify-final \
    --bundle "${NOTEAI_CACHE_BUNDLE_DIR}" \
    --extract-to "${cache_dir}" \
    --expected-sums-sha256 "${NOTEAI_EXPECTED_FINAL_SUMS_SHA256}" \
    --output "${validation_summary}"
  evidence_dir="${NOTEAI_IMPORT_EVIDENCE_DIR}"
fi

trusted_cache_record="${NOTEAI_CACHE_BUNDLE_DIR}/producer/cache-record.json"
test -f "${trusted_cache_record}"
trusted_cache_record_sha256="$(
  jq -er '.validated_cache_record_sha256' "${validation_summary}"
)"
[[ "${trusted_cache_record_sha256}" =~ ^[0-9a-f]{64}$ ]]
test "$(sha256sum "${trusted_cache_record}" | awk '{print $1}')" = \
  "${trusted_cache_record_sha256}"

test ! -e "${evidence_dir}"
mkdir -p "${evidence_dir}"

import_metadata="${evidence_dir}/import-build-metadata.json"
import_progress="${evidence_dir}/import-build.rawjson"
import_command_envelope="${evidence_dir}/import-command-envelope.json"
import_git_lifecycle_diagnostic="${evidence_dir}/import-git-source-lifecycle.json"
import_identity="${evidence_dir}/import-build-identity.json"
pre_predicate_diagnostic="${evidence_dir}/import-pre-predicate-diagnostic.json"
import_diagnostic="${evidence_dir}/import-diagnostic.json"
pair_summary="${evidence_dir}/pair.json"
import_command_started="$(timestamp_ns)"
import_build_rc=0
BUILDX_SEND_GIT_QUERY_AS_INPUT=0 \
  timeout "${build_timeout_seconds}" \
  docker buildx --builder "${NOTEAI_BUILDX_BUILDER}" build \
    --pull \
    --platform linux/amd64 \
    --target noteai-cache-import-observer \
    --build-arg "NOTEAI_OCI_REVISION=${expected_release}" \
    --build-arg "NOTEAI_OCI_SOURCE=${expected_source}" \
    --build-arg "NOTEAI_OCI_VERSION=${expected_version}" \
    --build-arg "NOTEAI_OCI_CREATED=${expected_created}" \
    --cache-from "type=local,src=${cache_dir}" \
    --output type=cacheonly \
    --metadata-file "${import_metadata}" \
    --progress rawjson \
    --file - \
    "${git_context_query}" \
    < "${prefix_dockerfile}" \
    > "${import_progress}" 2>&1 || import_build_rc=$?
import_command_completed="$(timestamp_ns)"
write_command_envelope \
  "${import_command_envelope}" \
  import \
  "${import_command_started}" \
  "${import_command_completed}"
if ((import_build_rc != 0)); then
  echo "dependency-cache import build failed or timed out" >&2
  exit 3
fi
if ! python3 "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" verify-build \
  --metadata "${import_metadata}" \
  --progress "${import_progress}" \
  --command-envelope "${import_command_envelope}" \
  --dockerfile prefix \
  --git-lifecycle-diagnostic-output "${import_git_lifecycle_diagnostic}" \
  --require-network-cached \
  --producer-summary \
  "${NOTEAI_CACHE_BUNDLE_DIR}/producer/cache-build-summary.json" \
  --cache-record \
  "${NOTEAI_CACHE_BUNDLE_DIR}/producer/cache-record.json" \
  --expected-cache-record-sha256 "${trusted_cache_record_sha256}" \
  --pre-predicate-diagnostic-output "${pre_predicate_diagnostic}" \
  --diagnostic-output "${import_diagnostic}" \
  --pair-output "${pair_summary}" \
  --identity-output "${import_identity}" \
  --output "${import_summary}"
then
  if [[ -s "${import_git_lifecycle_diagnostic}" ]]; then
    test "$(stat -c '%a' "${import_git_lifecycle_diagnostic}")" = "600"
    test "$(stat -c '%h' "${import_git_lifecycle_diagnostic}")" = "1"
    test "$(stat -c '%s' "${import_git_lifecycle_diagnostic}")" -le 16384
    jq -e '
      .schema_version == "noteai.admin-dependency-cache-git-source-lifecycle.v17"
      and .phase == "import"
      and (.verdict == "pass" or .verdict == "fail")
    ' "${import_git_lifecycle_diagnostic}" >/dev/null
    printf 'noteai_v17_git_source_lifecycle='
    jq -cS . "${import_git_lifecycle_diagnostic}"
  fi
  test -s "${import_identity}"
  printf 'noteai_v17_retained_import_identity='
  jq -cS . "${import_identity}"
  if [[ -f "${import_diagnostic}" ]]; then
    jq -e '
      .schema_version == "noteai.admin-dependency-cache-v11-diagnostic.v1"
      and .verdict == "fail"
      and (.failure_code | type == "string")
      and (.diagnostic_sha256 | test("^[0-9a-f]{64}$"))
    ' "${import_diagnostic}" >/dev/null
    printf 'noteai_v13_compatibility_import_diagnostic='
    jq -cS . "${import_diagnostic}"
  fi
  if [[ -f "${pre_predicate_diagnostic}" ]]; then
    jq -e '
      .schema_version == "noteai.admin-dependency-cache-v11-diagnostic.v1"
      and .v11_boundary_status == "PENDING_CACHE_PREDICATE"
      and .cached_predicates_enforced == false
      and (.diagnostic_sha256 | test("^[0-9a-f]{64}$"))
    ' "${pre_predicate_diagnostic}" >/dev/null
    printf 'noteai_v13_compatibility_pre_predicate_diagnostic='
    jq -cS . "${pre_predicate_diagnostic}"
  fi
  if [[ -f "${pair_summary}" ]]; then
    jq -e '
      .schema_version == "noteai.admin-dependency-cache-pair.v17"
      and (.classification | IN(
        "SOURCE_DIGEST_DRIFT",
        "REQUIREMENTS_COPY_DIGEST_DRIFT",
        "RUNTIME_PIP_DIGEST_DRIFT",
        "SAME_SOURCE_COPY_PIP_DIGESTS_NONCACHED",
        "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED"
      ))
    ' "${pair_summary}" >/dev/null
    printf 'noteai_v17_retained_pair='
    jq -cS . "${pair_summary}"
  fi
  exit 3
fi
cp "${import_summary}" "${evidence_dir}/import-summary.json"
verified_pair="${task_tmp}/verified-pair.json"
python3 "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" verify-pair \
  --producer-summary \
  "${NOTEAI_CACHE_BUNDLE_DIR}/producer/cache-build-summary.json" \
  --consumer-summary "${import_summary}" \
  --output "${verified_pair}"
cmp "${pair_summary}" "${verified_pair}"

if [[ "${cache_dir}" != "${task_tmp}/cache" || ! -d "${cache_dir}" ]]; then
  echo "unsafe external cache cleanup target" >&2
  exit 2
fi
rm -rf "${cache_dir}"
test ! -e "${cache_dir}"

replay_metadata="${evidence_dir}/replay-build-metadata.json"
replay_progress="${evidence_dir}/replay-build.rawjson"
replay_command_envelope="${evidence_dir}/replay-command-envelope.json"
replay_git_lifecycle_diagnostic="${evidence_dir}/replay-git-source-lifecycle.json"
replay_identity="${evidence_dir}/replay-build-identity.json"
replay_pre_predicate_diagnostic="${evidence_dir}/replay-pre-predicate-diagnostic.json"
replay_diagnostic="${evidence_dir}/replay-diagnostic.json"
replay_command_started="$(timestamp_ns)"
replay_build_rc=0
BUILDX_SEND_GIT_QUERY_AS_INPUT=0 \
  timeout "${build_timeout_seconds}" \
  docker buildx --builder "${NOTEAI_BUILDX_BUILDER}" build \
    --pull \
    --platform linux/amd64 \
    --target runtime-common \
    --build-arg "NOTEAI_OCI_REVISION=${expected_release}" \
    --build-arg "NOTEAI_OCI_SOURCE=${expected_source}" \
    --build-arg "NOTEAI_OCI_VERSION=${expected_version}" \
    --build-arg "NOTEAI_OCI_CREATED=${expected_created}" \
    --output type=cacheonly \
    --metadata-file "${replay_metadata}" \
    --progress rawjson \
    --file - \
    "${git_context_query}" \
    < "${NOTEAI_SOURCE_DIR}/Dockerfile" \
    > "${replay_progress}" 2>&1 || replay_build_rc=$?
replay_command_completed="$(timestamp_ns)"
write_command_envelope \
  "${replay_command_envelope}" \
  replay \
  "${replay_command_started}" \
  "${replay_command_completed}"
if ((replay_build_rc != 0)); then
  echo "external-cache-removed same-consumer-builder replay failed or timed out" >&2
  exit 3
fi
if ! python3 "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" verify-build \
  --metadata "${replay_metadata}" \
  --progress "${replay_progress}" \
  --command-envelope "${replay_command_envelope}" \
  --dockerfile full \
  --git-lifecycle-diagnostic-output "${replay_git_lifecycle_diagnostic}" \
  --require-network-cached \
  --pre-predicate-diagnostic-output "${replay_pre_predicate_diagnostic}" \
  --diagnostic-output "${replay_diagnostic}" \
  --identity-output "${replay_identity}" \
  --output "${replay_summary}"
then
  if [[ -s "${replay_git_lifecycle_diagnostic}" ]]; then
    test "$(stat -c '%a' "${replay_git_lifecycle_diagnostic}")" = "600"
    test "$(stat -c '%h' "${replay_git_lifecycle_diagnostic}")" = "1"
    test "$(stat -c '%s' "${replay_git_lifecycle_diagnostic}")" -le 16384
    jq -e '
      .schema_version == "noteai.admin-dependency-cache-git-source-lifecycle.v17"
      and .phase == "replay"
      and (.verdict == "pass" or .verdict == "fail")
    ' "${replay_git_lifecycle_diagnostic}" >/dev/null
    printf 'noteai_v17_git_source_lifecycle='
    jq -cS . "${replay_git_lifecycle_diagnostic}"
  fi
  if [[ -s "${replay_identity}" ]]; then
    test "$(stat -c '%s' "${replay_identity}")" -le 65536
    jq -e '
      .schema_version == "noteai.admin-dependency-cache-identity.v17"
      and .target == "runtime-common"
    ' "${replay_identity}" >/dev/null
    printf 'noteai_v17_retained_replay_identity='
    jq -cS . "${replay_identity}"
  fi
  for diagnostic in \
    "${replay_pre_predicate_diagnostic}" \
    "${replay_diagnostic}"
  do
    if [[ -s "${diagnostic}" ]]; then
      test "$(stat -c '%s' "${diagnostic}")" -le 16384
      printf 'noteai_v13_compatibility_replay_diagnostic='
      jq -cS . "${diagnostic}"
    fi
  done
  exit 3
fi
cp "${replay_summary}" "${evidence_dir}/replay-summary.json"

manifest="${NOTEAI_CACHE_BUNDLE_DIR}/manifest.json"
producer_buildkit_version="$(jq -r '.build.buildkit_version' "${manifest}")"
test "${producer_buildkit_version}" = "${buildkit_version}"
producer_buildkit_image_reference="$(
  jq -r '.build.buildkit_daemon_image_reference' "${manifest}"
)"
producer_buildkit_image_id="$(
  jq -r '.build.buildkit_daemon_image_id' "${manifest}"
)"
test "${producer_buildkit_image_reference}" = "${buildkit_image_reference}"
test "${producer_buildkit_image_id}" = "${buildkit_image_id}"
manifest_sha256="$(sha256sum "${manifest}" | awk '{print $1}')"
core_sums_sha256="$(
  sha256sum "${NOTEAI_CACHE_BUNDLE_DIR}/CORE_SHA256SUMS" |
    awk '{print $1}'
)"

if [[ "${NOTEAI_IMPORT_MODE}" == "ci_portability" ]]; then
  proof="${evidence_dir}/proof.json"
  jq -n \
    --arg schema_version "noteai.admin-dependency-cache-portability.v17" \
    --arg task "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001" \
    --arg release_commit "${expected_release}" \
    --arg manifest_sha256 "${manifest_sha256}" \
    --arg core_sums_sha256 "${core_sums_sha256}" \
    --arg producer_builder_name "${NOTEAI_PRODUCER_BUILDER_NAME}" \
    --arg consumer_builder_name "${NOTEAI_BUILDX_BUILDER}" \
    --arg buildkit_version "${buildkit_version}" \
    --arg buildkit_image_reference "${buildkit_image_reference}" \
    --arg buildkit_image_id "${buildkit_image_id}" \
    --slurpfile import_summary "${import_summary}" \
    --slurpfile producer_identity \
    "${NOTEAI_CACHE_BUNDLE_DIR}/producer/cache-build-identity.json" \
    --slurpfile import_identity "${import_identity}" \
    --slurpfile replay_identity "${replay_identity}" \
    --slurpfile replay_summary "${replay_summary}" \
    --slurpfile pair "${evidence_dir}/pair.json" \
    --slurpfile cache_record \
    "${NOTEAI_CACHE_BUNDLE_DIR}/producer/cache-record.json" \
    '{
      schema_version: $schema_version,
      task: $task,
      release_commit: $release_commit,
      manifest_sha256: $manifest_sha256,
      core_sums_sha256: $core_sums_sha256,
      producer: {
        builder_name: $producer_builder_name,
        driver: "docker-container",
        buildkit_version: $buildkit_version,
        buildkit_daemon_image_reference: $buildkit_image_reference,
        buildkit_daemon_image_id: $buildkit_image_id
      },
      consumer: {
        builder_name: $consumer_builder_name,
        driver: "docker-container",
        buildkit_version: $buildkit_version,
        buildkit_daemon_image_reference: $buildkit_image_reference,
        buildkit_daemon_image_id: $buildkit_image_id
      },
      pair: $pair[0],
      cache_record: $cache_record[0],
      import: ($import_summary[0] + {cache_from_local: true}),
      external_cache_removed_same_consumer_builder_replay: (
        $replay_summary[0] + {
          cache_from_local: false,
          external_cache_removed_before_replay: true,
          same_consumer_builder_used: true,
          full_committed_git_context_used: true,
          true_empty_cache_replay_claimed: false
        }
      ),
      identity_chain_digests: {
        producer: {
          source: $producer_identity[0].source.vertex_digest,
          requirements_copy: $producer_identity[0].requirements_copy.vertex_digest,
          runtime_pip: $producer_identity[0].runtime_pip.vertex_digest
        },
        consumer: {
          source: $import_identity[0].source.vertex_digest,
          requirements_copy: $import_identity[0].requirements_copy.vertex_digest,
          runtime_pip: $import_identity[0].runtime_pip.vertex_digest
        },
        replay: {
          source: $replay_identity[0].source.vertex_digest,
          requirements_copy: $replay_identity[0].requirements_copy.vertex_digest,
          runtime_pip: $replay_identity[0].runtime_pip.vertex_digest
        }
      },
      controls: {
        github_run_attempt: 1,
        image_or_registry_output_requested: false,
        full_committed_git_context_supplied: true,
        local_workspace_main_context_supplied: false,
        local_dockerfile_supplied_via_stdin: true,
        credential_or_secret_values_supplied: false,
        default_git_auth_secret_ids_present: true,
        external_cache_removed_before_replay: true,
        same_consumer_builder_used_for_replay: true,
        true_empty_cache_replay_claimed: false,
        upload_allowed_only_after_cleanup: true
      }
    }' > "${proof}"

  (
    cd "${NOTEAI_CACHE_BUNDLE_DIR}"
    find . -type f ! -name SHA256SUMS -print0 |
      LC_ALL=C sort -z |
      xargs -0 sha256sum
  ) > "${NOTEAI_CACHE_BUNDLE_DIR}/SHA256SUMS"
  echo "$(
    sha256sum "${NOTEAI_CACHE_BUNDLE_DIR}/SHA256SUMS" |
      awk '{print $1}'
  )" > "${RUNNER_TEMP:?RUNNER_TEMP is required}/noteai-final-sums-sha256"
else
  proof="${evidence_dir}/builder-prewarm-proof.json"
  provider_artifact_digest="$(
    jq -r \
      '.artifact.artifact_digest | sub("^sha256:"; "")' \
      "${NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH}"
  )"
  provider_artifact_id="$(
    jq -r \
      '.artifact.artifact_id' \
      "${NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH}"
  )"
  provider_run_id="$(
    jq -r \
      '.artifact.run_id' \
      "${NOTEAI_AUTHENTICATED_DOWNLOAD_RECEIPT_PATH}"
  )"
  [[ "${provider_artifact_digest}" =~ ^[0-9a-f]{64}$ ]]
  [[ "${provider_artifact_id}" =~ ^[1-9][0-9]*$ ]]
  [[ "${provider_run_id}" =~ ^[1-9][0-9]*$ ]]
  jq -n \
    --arg schema_version "noteai.admin-dependency-cache-builder-prewarm.v1" \
    --arg task "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001" \
    --arg release_commit "${expected_release}" \
    --arg manifest_sha256 "${manifest_sha256}" \
    --arg final_sums_sha256 "${NOTEAI_EXPECTED_FINAL_SUMS_SHA256}" \
    --arg provider_artifact_digest "${provider_artifact_digest}" \
    --arg provider_artifact_id "${provider_artifact_id}" \
    --arg provider_run_id "${provider_run_id}" \
    --arg download_receipt_sha256 "${NOTEAI_EXPECTED_DOWNLOAD_RECEIPT_SHA256}" \
    --arg builder_name "${NOTEAI_BUILDX_BUILDER}" \
    --arg buildkit_version "${buildkit_version}" \
    --arg buildkit_image_reference "${buildkit_image_reference}" \
    --arg buildkit_image_id "${buildkit_image_id}" \
    --slurpfile bundle_validation "${validation_summary}" \
    --slurpfile import_summary "${import_summary}" \
    --slurpfile replay_summary "${replay_summary}" \
    '{
      schema_version: $schema_version,
      task: $task,
      release_commit: $release_commit,
      manifest_sha256: $manifest_sha256,
      final_sums_sha256: $final_sums_sha256,
      provider_artifact_digest: $provider_artifact_digest,
      provider_artifact_id: $provider_artifact_id,
      provider_run_id: $provider_run_id,
      authenticated_download_receipt_sha256: $download_receipt_sha256,
      bundle_validation: $bundle_validation[0],
      builder: {
        name: $builder_name,
        driver: "docker-container",
        buildkit_version: $buildkit_version,
        buildkit_daemon_image_reference: $buildkit_image_reference,
        buildkit_daemon_image_id: $buildkit_image_id
      },
      import: ($import_summary[0] + {cache_from_local: true}),
      external_cache_removed_same_consumer_builder_replay: (
        $replay_summary[0] + {
          cache_from_local: false,
          external_cache_removed_before_replay: true,
          same_consumer_builder_used: true,
          full_committed_git_context_used: true,
          true_empty_cache_replay_claimed: false
        }
      ),
      controls: {
        image_or_registry_output_requested: false,
        registry_login_or_push_performed: false,
        deployment_or_database_action_performed: false,
        canonical_admin_build_still_required: true,
        canonical_admin_build_must_inherit_BUILDX_BUILDER: $builder_name
      }
    }' > "${proof}"
fi

find "${evidence_dir}" -type d -exec chmod 0700 {} +
find "${evidence_dir}" -type f -exec chmod 0600 {} +
test -z "$(
  find "${evidence_dir}" \
    \( -type l -o -type b -o -type c -o -type p -o -type s \) \
    -print -quit
)"
echo "admin_dependency_cache_import=PASS mode=${NOTEAI_IMPORT_MODE}"
