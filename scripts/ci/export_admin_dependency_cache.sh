#!/usr/bin/env bash
set -euo pipefail

# Export only the exact dependency-producing prefix of the 5335 Dockerfile as a
# portable BuildKit local cache. This script never builds an application image,
# starts a long-lived application container, logs in to a registry, pushes,
# deploys or contacts a production service/database.

: "${RELEASE_COMMIT:?RELEASE_COMMIT is required}"
: "${NOTEAI_OCI_SOURCE:?NOTEAI_OCI_SOURCE is required}"
: "${NOTEAI_OCI_VERSION:?NOTEAI_OCI_VERSION is required}"
: "${NOTEAI_OCI_CREATED:?NOTEAI_OCI_CREATED is required}"
: "${NOTEAI_CACHE_BUNDLE_DIR:?NOTEAI_CACHE_BUNDLE_DIR is required}"
: "${NOTEAI_PLAN_CHECKPOINT_COMMIT:?NOTEAI_PLAN_CHECKPOINT_COMMIT is required}"
: "${NOTEAI_CONTROL_COMMIT:?NOTEAI_CONTROL_COMMIT is required}"
: "${NOTEAI_REQUEST_SHA256:?NOTEAI_REQUEST_SHA256 is required}"
: "${NOTEAI_WORKFLOW_SHA256:?NOTEAI_WORKFLOW_SHA256 is required}"
: "${NOTEAI_EXPORT_HELPER_PATH:?NOTEAI_EXPORT_HELPER_PATH is required}"
: "${NOTEAI_EXPORT_HELPER_SHA256:?NOTEAI_EXPORT_HELPER_SHA256 is required}"
: "${NOTEAI_IMPORT_HELPER_PATH:?NOTEAI_IMPORT_HELPER_PATH is required}"
: "${NOTEAI_IMPORT_HELPER_SHA256:?NOTEAI_IMPORT_HELPER_SHA256 is required}"
: "${NOTEAI_BUNDLE_VERIFIER_PATH:?NOTEAI_BUNDLE_VERIFIER_PATH is required}"
: "${NOTEAI_BUNDLE_VERIFIER_SHA256:?NOTEAI_BUNDLE_VERIFIER_SHA256 is required}"
: "${NOTEAI_PRODUCER_BUILDER:?NOTEAI_PRODUCER_BUILDER is required}"
: "${DOCKER_CONFIG:?DOCKER_CONFIG is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"

expected_release="5335bdaed933b1f999b5f819c047ec50c11821ae"
expected_tree="38e574e56406ba3380acb78edbe784508cc537cd"
expected_dockerfile="ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447"
expected_prefix="93fd024e5af678b7885bcab8e72d980a9f92cfc70de4f2fd2870284e25b8ec1e"
expected_dockerignore="d327ca46e4800b2af3c073c7e40bac93e0a042fec016fe6b798a5bd6944d3149"
expected_requirements="1ef4150536e98b8057069981b1aadb469ca12f0f30f188a291af2f31e238724a"
expected_requirements_api="0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9"
python_index="sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
python_amd64="sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045"
node_index="sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"
node_amd64="sha256:3d0f05455dea2c82e2f76e7e2543964c30f6b7d673fc1a83286736d44fe4c41c"
chunk_bytes=268435456
maximum_gzip_bytes=3758096384
maximum_raw_tar_bytes=5368709120
maximum_blob_bytes=4294967296
maximum_extracted_cache_bytes=4311744512
maximum_artifact_input_bytes=4026531840
maximum_provider_artifact_bytes=4294967296
maximum_non_chunk_file_bytes=134217728
maximum_chunk_count=14

if [[ "${RELEASE_COMMIT}" != "${expected_release}" ]]; then
  echo "release commit drift" >&2
  exit 2
fi
if [[ "${GITHUB_RUN_ATTEMPT}" != "1" ]]; then
  echo "GitHub workflow rerun is not authorized" >&2
  exit 2
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "native x86_64 runner required" >&2
  exit 2
fi
if [[ "$(git rev-parse HEAD)" != "${expected_release}" ]]; then
  echo "exact release checkout required" >&2
  exit 2
fi
if [[ "$(git rev-parse HEAD^{tree})" != "${expected_tree}" ]]; then
  echo "release tree drift" >&2
  exit 2
fi
if [[ -n "$(git status --short)" ]]; then
  echo "release checkout is not clean" >&2
  exit 2
fi
if [[ -e "${NOTEAI_CACHE_BUNDLE_DIR}" ]]; then
  echo "cache bundle directory already exists" >&2
  exit 2
fi
test -f "${DOCKER_CONFIG}/config.json"
jq -e '
  type == "object"
  and (keys == ["auths"])
  and .auths == {}
' "${DOCKER_CONFIG}/config.json" >/dev/null
test "$(stat -c '%a' "${DOCKER_CONFIG}")" = "700"
test "$(stat -c '%a' "${DOCKER_CONFIG}/config.json")" = "600"

for command_name in docker git jq python3 sha256sum stat find sort tar gzip split awk sed cp; do
  command -v "${command_name}" >/dev/null
done

check_sha256() {
  local expected="$1"
  local path="$2"
  test "$(sha256sum "${path}" | awk '{print $1}')" = "${expected}"
}

for hash_value in \
  "${NOTEAI_REQUEST_SHA256}" \
  "${NOTEAI_WORKFLOW_SHA256}" \
  "${NOTEAI_EXPORT_HELPER_SHA256}" \
  "${NOTEAI_IMPORT_HELPER_SHA256}" \
  "${NOTEAI_BUNDLE_VERIFIER_SHA256}"
do
  [[ "${hash_value}" =~ ^[0-9a-f]{64}$ ]]
done
[[ "${NOTEAI_PLAN_CHECKPOINT_COMMIT}" =~ ^[0-9a-f]{40}$ ]]
[[ "${NOTEAI_CONTROL_COMMIT}" =~ ^[0-9a-f]{40}$ ]]
check_sha256 "${NOTEAI_EXPORT_HELPER_SHA256}" "${NOTEAI_EXPORT_HELPER_PATH}"
check_sha256 "${NOTEAI_IMPORT_HELPER_SHA256}" "${NOTEAI_IMPORT_HELPER_PATH}"
check_sha256 \
  "${NOTEAI_BUNDLE_VERIFIER_SHA256}" \
  "${NOTEAI_BUNDLE_VERIFIER_PATH}"
check_sha256 "${expected_dockerfile}" Dockerfile
check_sha256 "${expected_dockerignore}" .dockerignore
check_sha256 "${expected_requirements}" model/requirements.txt
check_sha256 "${expected_requirements_api}" model/requirements-api.txt
test "$(
  grep -Ec '^[A-Za-z0-9_.-]+(\[[A-Za-z0-9_.-]+\])?==' \
    model/requirements-api.txt
)" = "24"
test -z "$(
  grep -E -- '--require-hashes|--index-url|--extra-index-url' \
    model/requirements-api.txt ||
    true
)"

umask 077
task_tmp="$(mktemp -d)"
cache_dir="${task_tmp}/cache"
context_dir="${task_tmp}/context"
prefix_dockerfile="${context_dir}/Dockerfile"
metadata_file="${task_tmp}/cache-build-metadata.json"
progress_file="${task_tmp}/producer-build.rawjson"
producer_summary="${task_tmp}/producer-build-summary.json"
builder_inspect="${task_tmp}/producer-builder-inspect.txt"

cleanup() {
  if [[ "${task_tmp}" == /tmp/* || "${task_tmp}" == "${RUNNER_TEMP:-/nonexistent}/"* ]]; then
    rm -rf "${task_tmp}"
  fi
}
trap cleanup EXIT

mkdir -p "${context_dir}/model"
sed -n '1,80p' Dockerfile > "${prefix_dockerfile}"
cp --preserve=mode,timestamps .dockerignore "${context_dir}/.dockerignore"
cp --preserve=mode,timestamps \
  model/requirements.txt \
  model/requirements-api.txt \
  "${context_dir}/model/"
check_sha256 "${expected_prefix}" "${prefix_dockerfile}"
test "$(sed -n '81p' Dockerfile)" = ""
test "$(sed -n '83p' Dockerfile)" = "COPY model/ ./model/"
test "$(find "${context_dir}" -type f | wc -l | tr -d ' ')" = "4"
test "$(
  cd "${context_dir}"
  find . -type f -print |
    sed 's#^\./##' |
    LC_ALL=C sort
)" = $'.dockerignore\nDockerfile\nmodel/requirements-api.txt\nmodel/requirements.txt'
test -z "$(
  find "${context_dir}" \
    \( -type l -o -type b -o -type c -o -type p -o -type s \) \
    -print -quit
)"

docker buildx inspect "${NOTEAI_PRODUCER_BUILDER}" --bootstrap > "${builder_inspect}"
buildkit_driver="$(
  awk -F: '
    $1 ~ /^[[:space:]]*Driver[[:space:]]*$/ {
      value = $2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      print value
    }
  ' "${builder_inspect}" |
    sort -u
)"
test "${buildkit_driver}" = "docker-container"
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
buildx_version="$(docker buildx version | tr -d '\r\n')"
buildkit_container="buildx_buildkit_${NOTEAI_PRODUCER_BUILDER}0"
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

mkdir -p "${NOTEAI_CACHE_BUNDLE_DIR}/chunks"
mkdir -p "${NOTEAI_CACHE_BUNDLE_DIR}/builder"
mkdir -p "${NOTEAI_CACHE_BUNDLE_DIR}/producer"
docker buildx imagetools inspect --raw \
  "python:3.11.15-slim-trixie@${python_index}" \
  > "${NOTEAI_CACHE_BUNDLE_DIR}/python-base-index.json"
docker buildx imagetools inspect --raw \
  "node:20-bookworm-slim@${node_index}" \
  > "${NOTEAI_CACHE_BUNDLE_DIR}/node-base-index.json"
check_sha256 \
  "${python_index#sha256:}" \
  "${NOTEAI_CACHE_BUNDLE_DIR}/python-base-index.json"
check_sha256 \
  "${node_index#sha256:}" \
  "${NOTEAI_CACHE_BUNDLE_DIR}/node-base-index.json"
jq -e --arg child "${python_amd64}" '
  [
    .manifests[]
    | select(
        .platform.os == "linux"
        and .platform.architecture == "amd64"
        and (.platform.variant // "") == ""
      )
    | .digest
  ] == [$child]
' "${NOTEAI_CACHE_BUNDLE_DIR}/python-base-index.json" >/dev/null
jq -e --arg child "${node_amd64}" '
  [
    .manifests[]
    | select(
        .platform.os == "linux"
        and .platform.architecture == "amd64"
        and (.platform.variant // "") == ""
      )
    | .digest
  ] == [$child]
' "${NOTEAI_CACHE_BUNDLE_DIR}/node-base-index.json" >/dev/null

if ! docker buildx --builder "${NOTEAI_PRODUCER_BUILDER}" build \
  --pull \
  --platform linux/amd64 \
  --target runtime-common \
  --build-arg "NOTEAI_OCI_REVISION=${RELEASE_COMMIT}" \
  --build-arg "NOTEAI_OCI_SOURCE=${NOTEAI_OCI_SOURCE}" \
  --build-arg "NOTEAI_OCI_VERSION=${NOTEAI_OCI_VERSION}" \
  --build-arg "NOTEAI_OCI_CREATED=${NOTEAI_OCI_CREATED}" \
  --cache-to "type=local,dest=${cache_dir},mode=max,oci-mediatypes=true,image-manifest=true,compression=gzip,compression-level=1" \
  --output type=cacheonly \
  --metadata-file "${metadata_file}" \
  --progress rawjson \
  --file "${prefix_dockerfile}" \
  "${context_dir}" \
  > "${progress_file}" 2>&1
then
  echo "dependency-prefix cache export failed" >&2
  exit 3
fi
python3 "${NOTEAI_BUNDLE_VERIFIER_PATH}" verify-build \
  --metadata "${metadata_file}" \
  --progress "${progress_file}" \
  --dockerfile prefix \
  --output "${producer_summary}"

test -f "${cache_dir}/oci-layout"
test -f "${cache_dir}/index.json"
test -z "$(
  find "${cache_dir}" \
    \( -type l -o -type b -o -type c -o -type p -o -type s \) \
    -print -quit
)"
test -z "$(find "${cache_dir}" -type f -links +1 -print -quit)"
find "${cache_dir}" -type d -exec chmod 0700 {} +
find "${cache_dir}" -type f -exec chmod 0600 {} +
cache_regular_bytes=0
while IFS= read -r -d '' cache_path; do
  cache_size="$(stat -c '%s' "${cache_path}")"
  cache_regular_bytes=$((cache_regular_bytes + cache_size))
  test "${cache_regular_bytes}" -le "${maximum_extracted_cache_bytes}"
done < <(find "${cache_dir}" -type f -print0 | LC_ALL=C sort -z)

blob_inventory_jsonl="${task_tmp}/blob-inventory.jsonl"
blob_count=0
blob_bytes=0
while IFS= read -r -d '' blob_path; do
  blob_name="$(basename "${blob_path}")"
  blob_sha256="$(sha256sum "${blob_path}" | awk '{print $1}')"
  blob_size="$(stat -c '%s' "${blob_path}")"
  test "${blob_name}" = "${blob_sha256}"
  jq -n \
    --arg name "${blob_name}" \
    --arg sha256 "${blob_sha256}" \
    --argjson bytes "${blob_size}" \
    '{name: $name, sha256: $sha256, bytes: $bytes}' \
    >> "${blob_inventory_jsonl}"
  blob_count=$((blob_count + 1))
  blob_bytes=$((blob_bytes + blob_size))
done < <(find "${cache_dir}/blobs/sha256" -type f -print0 | LC_ALL=C sort -z)
test "${blob_count}" -gt 0
test "${blob_bytes}" -gt 0
test "${blob_bytes}" -le "${maximum_blob_bytes}"
jq -s '.' "${blob_inventory_jsonl}" > "${task_tmp}/blob-inventory.json"

cp "${metadata_file}" "${NOTEAI_CACHE_BUNDLE_DIR}/cache-build-metadata.json"
cp "${progress_file}" "${NOTEAI_CACHE_BUNDLE_DIR}/producer-build.rawjson"
cp "${cache_dir}/index.json" "${NOTEAI_CACHE_BUNDLE_DIR}/cache-index.json"
cp "${cache_dir}/oci-layout" "${NOTEAI_CACHE_BUNDLE_DIR}/oci-layout"
cp \
  "${NOTEAI_EXPORT_HELPER_PATH}" \
  "${NOTEAI_CACHE_BUNDLE_DIR}/producer/export_admin_dependency_cache.sh"
cp \
  "${NOTEAI_IMPORT_HELPER_PATH}" \
  "${NOTEAI_CACHE_BUNDLE_DIR}/builder/import_admin_dependency_cache.sh"
cp \
  "${NOTEAI_BUNDLE_VERIFIER_PATH}" \
  "${NOTEAI_CACHE_BUNDLE_DIR}/builder/verify_admin_dependency_cache_bundle.py"

raw_archive="${task_tmp}/admin-dependency-cache.tar"
gzip_archive="${task_tmp}/admin-dependency-cache.tar.gz"
tar \
  --sort=name \
  --mtime='UTC 1970-01-01' \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  -C "${cache_dir}" \
  -cf "${raw_archive}" \
  .
raw_archive_sha256="$(sha256sum "${raw_archive}" | awk '{print $1}')"
raw_archive_bytes="$(stat -c '%s' "${raw_archive}")"
test "${raw_archive_bytes}" -gt 0
test "${raw_archive_bytes}" -le "${maximum_raw_tar_bytes}"
gzip -1 -n -c "${raw_archive}" > "${gzip_archive}"
gzip -t "${gzip_archive}"
gzip_archive_sha256="$(sha256sum "${gzip_archive}" | awk '{print $1}')"
gzip_archive_bytes="$(stat -c '%s' "${gzip_archive}")"
test "${gzip_archive_bytes}" -gt 0
test "${gzip_archive_bytes}" -le "${maximum_gzip_bytes}"
test "${raw_archive_bytes}" -le "$((gzip_archive_bytes * 8))"

split \
  --bytes="${chunk_bytes}" \
  --numeric-suffixes=0 \
  --suffix-length=4 \
  "${gzip_archive}" \
  "${NOTEAI_CACHE_BUNDLE_DIR}/chunks/admin-dependency-cache.tar.gz.part-"

chunk_inventory_jsonl="${task_tmp}/chunk-inventory.jsonl"
chunk_count=0
while IFS= read -r -d '' chunk_path; do
  chunk_name="chunks/$(basename "${chunk_path}")"
  expected_chunk_name="$(
    printf 'chunks/admin-dependency-cache.tar.gz.part-%04d' "${chunk_count}"
  )"
  test "${chunk_name}" = "${expected_chunk_name}"
  chunk_sha256="$(sha256sum "${chunk_path}" | awk '{print $1}')"
  chunk_size="$(stat -c '%s' "${chunk_path}")"
  test "${chunk_size}" -gt 0
  test "${chunk_size}" -le "${chunk_bytes}"
  jq -n \
    --arg name "${chunk_name}" \
    --arg sha256 "${chunk_sha256}" \
    --argjson bytes "${chunk_size}" \
    '{name: $name, sha256: $sha256, bytes: $bytes}' \
    >> "${chunk_inventory_jsonl}"
  chunk_count=$((chunk_count + 1))
done < <(
  find "${NOTEAI_CACHE_BUNDLE_DIR}/chunks" -type f -print0 |
    LC_ALL=C sort -z
)
test "${chunk_count}" -gt 0
test "${chunk_count}" -le "${maximum_chunk_count}"
jq -s '.' "${chunk_inventory_jsonl}" > "${task_tmp}/chunk-inventory.json"
if [[ "${chunk_count}" -gt 1 ]]; then
  for chunk_index in $(seq 0 "$((chunk_count - 2))"); do
    test "$(
      stat -c '%s' "$(
        printf '%s/chunks/admin-dependency-cache.tar.gz.part-%04d' \
          "${NOTEAI_CACHE_BUNDLE_DIR}" \
          "${chunk_index}"
      )"
    )" = "${chunk_bytes}"
  done
fi
test "$(
  cat "${NOTEAI_CACHE_BUNDLE_DIR}"/chunks/admin-dependency-cache.tar.gz.part-* |
    sha256sum |
    awk '{print $1}'
)" = "${gzip_archive_sha256}"

metadata_sha256="$(sha256sum "${metadata_file}" | awk '{print $1}')"
progress_sha256="$(sha256sum "${progress_file}" | awk '{print $1}')"
duration_seconds="$(jq -r '.duration_seconds' "${producer_summary}")"
cache_index_sha256="$(sha256sum "${cache_dir}/index.json" | awk '{print $1}')"
oci_layout_sha256="$(sha256sum "${cache_dir}/oci-layout" | awk '{print $1}')"
cache_manifest_digest="$(
  jq -r '
    select(.schemaVersion == 2)
    | select(.manifests | type == "array" and length == 1)
    | .manifests[0].digest
  ' "${cache_dir}/index.json"
)"
[[ "${cache_manifest_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
test -f "${cache_dir}/blobs/sha256/${cache_manifest_digest#sha256:}"

jq -n \
  --arg schema_version "noteai.admin-dependency-cache-export.v2" \
  --arg release_commit "${RELEASE_COMMIT}" \
  --arg release_tree "${expected_tree}" \
  --arg dockerfile_sha256 "${expected_dockerfile}" \
  --arg dependency_prefix_sha256 "${expected_prefix}" \
  --arg dockerignore_sha256 "${expected_dockerignore}" \
  --arg requirements_sha256 "${expected_requirements}" \
  --arg requirements_api_sha256 "${expected_requirements_api}" \
  --arg buildx_version "${buildx_version}" \
  --arg buildkit_driver "${buildkit_driver}" \
  --arg buildkit_version "${buildkit_version}" \
  --arg buildkit_image_reference "${buildkit_image_reference}" \
  --arg buildkit_image_id "${buildkit_image_id}" \
  --arg plan_checkpoint_commit "${NOTEAI_PLAN_CHECKPOINT_COMMIT}" \
  --arg control_commit "${NOTEAI_CONTROL_COMMIT}" \
  --arg request_sha256 "${NOTEAI_REQUEST_SHA256}" \
  --arg workflow_sha256 "${NOTEAI_WORKFLOW_SHA256}" \
  --arg export_helper_sha256 "${NOTEAI_EXPORT_HELPER_SHA256}" \
  --arg import_helper_sha256 "${NOTEAI_IMPORT_HELPER_SHA256}" \
  --arg bundle_verifier_sha256 "${NOTEAI_BUNDLE_VERIFIER_SHA256}" \
  --arg github_run_id "${GITHUB_RUN_ID}" \
  --arg metadata_sha256 "${metadata_sha256}" \
  --arg progress_sha256 "${progress_sha256}" \
  --arg cache_index_sha256 "${cache_index_sha256}" \
  --arg oci_layout_sha256 "${oci_layout_sha256}" \
  --arg cache_manifest_digest "${cache_manifest_digest}" \
  --arg python_index "${python_index}" \
  --arg python_amd64 "${python_amd64}" \
  --arg node_index "${node_index}" \
  --arg node_amd64 "${node_amd64}" \
  --arg raw_archive_sha256 "${raw_archive_sha256}" \
  --arg gzip_archive_sha256 "${gzip_archive_sha256}" \
  --argjson duration_seconds "${duration_seconds}" \
  --argjson blob_count "${blob_count}" \
  --argjson blob_bytes "${blob_bytes}" \
  --argjson raw_archive_bytes "${raw_archive_bytes}" \
  --argjson gzip_archive_bytes "${gzip_archive_bytes}" \
  --argjson chunk_bytes "${chunk_bytes}" \
  --argjson chunk_count "${chunk_count}" \
  --argjson maximum_gzip_bytes "${maximum_gzip_bytes}" \
  --argjson maximum_extracted_cache_bytes "${maximum_extracted_cache_bytes}" \
  --argjson maximum_artifact_input_bytes "${maximum_artifact_input_bytes}" \
  --argjson maximum_provider_artifact_bytes "${maximum_provider_artifact_bytes}" \
  --argjson maximum_non_chunk_file_bytes "${maximum_non_chunk_file_bytes}" \
  --slurpfile blobs "${task_tmp}/blob-inventory.json" \
  --slurpfile chunks "${task_tmp}/chunk-inventory.json" \
  '{
    schema_version: $schema_version,
    task: "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
    release: {
      commit: $release_commit,
      tree: $release_tree,
      dockerfile_sha256: $dockerfile_sha256,
      dependency_prefix_lines: [1, 80],
      first_application_copy_line: 83,
      dependency_prefix_sha256: $dependency_prefix_sha256,
      minimal_context_files: [
        {path: ".dockerignore", sha256: $dockerignore_sha256},
        {path: "Dockerfile", sha256: $dependency_prefix_sha256},
        {
          path: "model/requirements-api.txt",
          sha256: $requirements_api_sha256
        },
        {path: "model/requirements.txt", sha256: $requirements_sha256}
      ]
    },
    build: {
      runner_architecture: "x86_64",
      platform: "linux/amd64",
      target: "runtime-common",
      pull: true,
      output: "cacheonly",
      cache_export: "type=local,mode=max,oci-mediatypes=true",
      docker_engine_image_export_requested: false,
      registry_export_requested: false,
      transient_buildkit_sandboxes_expected: true,
      buildx_client_version: $buildx_version,
      buildkit_driver: $buildkit_driver,
      buildkit_version: $buildkit_version,
      buildkit_daemon_image_reference: $buildkit_image_reference,
      buildkit_daemon_image_id: $buildkit_image_id,
      metadata_sha256: $metadata_sha256,
      progress_sha256: $progress_sha256,
      duration_seconds: $duration_seconds,
      base_images: {
        python: {index: $python_index, linux_amd64: $python_amd64},
        node: {index: $node_index, linux_amd64: $node_amd64}
      }
    },
    cache: {
      type: "buildkit-local-oci-layout",
      mode: "max",
      compression: "gzip",
      compression_level: 1,
      cache_index_sha256: $cache_index_sha256,
      oci_layout_sha256: $oci_layout_sha256,
      manifest_digest: $cache_manifest_digest,
      blob_count: $blob_count,
      blob_bytes: $blob_bytes,
      blobs: $blobs[0]
    },
    archive: {
      format: "deterministic-tar-gzip",
      raw_tar_sha256: $raw_archive_sha256,
      raw_tar_bytes: $raw_archive_bytes,
      gzip_sha256: $gzip_archive_sha256,
      gzip_bytes: $gzip_archive_bytes,
      chunk_bytes_limit: $chunk_bytes,
      chunk_count: $chunk_count,
      chunks: $chunks[0],
      maximum_gzip_bytes: $maximum_gzip_bytes,
      maximum_extracted_cache_bytes: $maximum_extracted_cache_bytes,
      artifact_input_maximum_bytes: $maximum_artifact_input_bytes,
      artifact_provider_maximum_bytes: $maximum_provider_artifact_bytes,
      non_chunk_file_maximum_bytes: $maximum_non_chunk_file_bytes
    },
    control: {
      plan_checkpoint_commit: $plan_checkpoint_commit,
      control_commit: $control_commit,
      request_sha256: $request_sha256,
      workflow_sha256: $workflow_sha256,
      export_helper_sha256: $export_helper_sha256,
      import_helper_sha256: $import_helper_sha256,
      bundle_verifier_sha256: $bundle_verifier_sha256,
      github_run_id: $github_run_id,
      github_run_attempt: 1,
      artifact_retention_days: 1,
      application_or_model_source_inputs_supplied_to_export: false,
      buildkit_credential_or_secret_inputs_supplied: false,
      registry_digest: null,
      registry_publication_authorized: false,
      deployment_authorized: false,
      database_authorized: false,
      service_mutation_authorized: false,
      public_traffic_authorized: false
    },
    next_gate: {
      provider_artifact_digest_acceptance_required: true,
      authenticated_download_verification_required: true,
      target_builder_import_required: true,
      target_builder_cacheless_full_context_prefix_replay_required: true,
      canonical_admin_build_same_builder_environment_required: true,
      exact_buildkit_daemon_image_required: true,
      canonical_admin_build_required: true,
      fresh_scan_and_sbom_required: true,
      private_publication_authorized: false
    }
  }' > "${NOTEAI_CACHE_BUNDLE_DIR}/manifest.json"

(
  cd "${NOTEAI_CACHE_BUNDLE_DIR}"
  find . -type f ! -name CORE_SHA256SUMS -print0 |
    LC_ALL=C sort -z |
    xargs -0 sha256sum
) > "${NOTEAI_CACHE_BUNDLE_DIR}/CORE_SHA256SUMS"

find "${NOTEAI_CACHE_BUNDLE_DIR}" -type d -exec chmod 0700 {} +
find "${NOTEAI_CACHE_BUNDLE_DIR}" -type f -exec chmod 0600 {} +
test -z "$(
  find "${NOTEAI_CACHE_BUNDLE_DIR}" \
    \( -type l -o -type b -o -type c -o -type p -o -type s \) \
    -print -quit
)"
test -z "$(
  find "${NOTEAI_CACHE_BUNDLE_DIR}" -type f -links +1 -print -quit
)"
bundle_input_bytes=0
while IFS= read -r -d '' bundle_path; do
  bundle_relative="${bundle_path#"${NOTEAI_CACHE_BUNDLE_DIR}/"}"
  bundle_size="$(stat -c '%s' "${bundle_path}")"
  if [[ "${bundle_relative}" != chunks/* ]]; then
    test "${bundle_size}" -le "${maximum_non_chunk_file_bytes}"
  fi
  bundle_input_bytes=$((bundle_input_bytes + bundle_size))
  test "${bundle_input_bytes}" -le "${maximum_artifact_input_bytes}"
done < <(
  find "${NOTEAI_CACHE_BUNDLE_DIR}" -type f -print0 |
    LC_ALL=C sort -z
)

bundle_file_count="$(
  find "${NOTEAI_CACHE_BUNDLE_DIR}" -type f | wc -l | tr -d ' '
)"
echo "admin_dependency_cache_export=PASS files=${bundle_file_count} chunks=${chunk_count}"
