#!/usr/bin/env bash
set -euo pipefail

# Validate, import and replay the exact-5335 dependency-only BuildKit cache.
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
expected_dockerignore="d327ca46e4800b2af3c073c7e40bac93e0a042fec016fe6b798a5bd6944d3149"
expected_requirements="1ef4150536e98b8057069981b1aadb469ca12f0f30f188a291af2f31e238724a"
expected_requirements_api="0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9"
expected_source="https://github.com/iamyusen1314/noteai"
expected_version="git-5335bda-amd64-r1"
expected_created="2026-07-30T13:29:02Z"
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

for command_name in docker git jq python3 sha256sum timeout find sort sed cp awk stat; do
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
check_sha256 "${expected_requirements}" "${NOTEAI_SOURCE_DIR}/model/requirements.txt"
check_sha256 \
  "${expected_requirements_api}" \
  "${NOTEAI_SOURCE_DIR}/model/requirements-api.txt"

umask 077
task_tmp="$(mktemp -d)"
cache_dir="${task_tmp}/cache"
context_dir="${task_tmp}/context"
prefix_dockerfile="${context_dir}/Dockerfile"
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

mkdir -p "${context_dir}/model"
sed -n '1,80p' "${NOTEAI_SOURCE_DIR}/Dockerfile" > "${prefix_dockerfile}"
cp --preserve=mode,timestamps \
  "${NOTEAI_SOURCE_DIR}/.dockerignore" \
  "${context_dir}/.dockerignore"
cp --preserve=mode,timestamps \
  "${NOTEAI_SOURCE_DIR}/model/requirements.txt" \
  "${NOTEAI_SOURCE_DIR}/model/requirements-api.txt" \
  "${context_dir}/model/"
check_sha256 "${expected_prefix}" "${prefix_dockerfile}"
test "$(sed -n '81p' "${NOTEAI_SOURCE_DIR}/Dockerfile")" = ""
test "$(
  sed -n '83p' "${NOTEAI_SOURCE_DIR}/Dockerfile"
)" = "COPY model/ ./model/"
test "$(find "${context_dir}" -type f | wc -l | tr -d ' ')" = "4"
test -z "$(
  find "${context_dir}" \
    \( -type l -o -type b -o -type c -o -type p -o -type s \) \
    -print -quit
)"

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

test ! -e "${evidence_dir}"
mkdir -p "${evidence_dir}"

import_metadata="${evidence_dir}/import-build-metadata.json"
import_progress="${evidence_dir}/import-build.rawjson"
if ! timeout "${build_timeout_seconds}" \
  docker buildx --builder "${NOTEAI_BUILDX_BUILDER}" build \
    --pull \
    --platform linux/amd64 \
    --target runtime-common \
    --build-arg "NOTEAI_OCI_REVISION=${expected_release}" \
    --build-arg "NOTEAI_OCI_SOURCE=${expected_source}" \
    --build-arg "NOTEAI_OCI_VERSION=${expected_version}" \
    --build-arg "NOTEAI_OCI_CREATED=${expected_created}" \
    --cache-from "type=local,src=${cache_dir}" \
    --output type=cacheonly \
    --metadata-file "${import_metadata}" \
    --progress rawjson \
    --file "${prefix_dockerfile}" \
    "${context_dir}" \
    > "${import_progress}" 2>&1
then
  echo "dependency-cache import build failed or timed out" >&2
  exit 3
fi
python3 "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" verify-build \
  --metadata "${import_metadata}" \
  --progress "${import_progress}" \
  --dockerfile prefix \
  --require-network-cached \
  --output "${import_summary}"

if [[ "${cache_dir}" != "${task_tmp}/cache" || ! -d "${cache_dir}" ]]; then
  echo "unsafe external cache cleanup target" >&2
  exit 2
fi
rm -rf "${cache_dir}"
test ! -e "${cache_dir}"

replay_metadata="${evidence_dir}/replay-build-metadata.json"
replay_progress="${evidence_dir}/replay-build.rawjson"
if ! timeout "${build_timeout_seconds}" \
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
    --file "${NOTEAI_SOURCE_DIR}/Dockerfile" \
    "${NOTEAI_SOURCE_DIR}" \
    > "${replay_progress}" 2>&1
then
  echo "cacheless full-context dependency replay failed or timed out" >&2
  exit 3
fi
python3 "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" verify-build \
  --metadata "${replay_metadata}" \
  --progress "${replay_progress}" \
  --dockerfile full \
  --require-network-cached \
  --output "${replay_summary}"

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
    --arg schema_version "noteai.admin-dependency-cache-portability.v1" \
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
    --slurpfile replay_summary "${replay_summary}" \
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
      import: ($import_summary[0] + {cache_from_local: true}),
      cacheless_replay: (
        $replay_summary[0] + {
          cache_from_local: false,
          external_cache_removed_before_replay: true,
          full_release_context_used: true
        }
      ),
      controls: {
        github_run_attempt: 1,
        image_or_registry_output_requested: false,
        dependency_prefix_application_or_model_source_inputs_supplied: false,
        full_replay_release_context_used: true,
        buildkit_credential_or_secret_inputs_supplied: false,
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
      cacheless_replay: (
        $replay_summary[0] + {
          cache_from_local: false,
          external_cache_removed_before_replay: true,
          full_release_context_used: true
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
