#!/usr/bin/env bash
set -euo pipefail

# Native GitHub runner only. This script builds local images, gathers
# secret-free evidence and never logs in, pushes or starts a container.

: "${RELEASE_COMMIT:?RELEASE_COMMIT is required}"
: "${NOTEAI_OCI_SOURCE:?NOTEAI_OCI_SOURCE is required}"
: "${NOTEAI_OCI_VERSION:?NOTEAI_OCI_VERSION is required}"
: "${NOTEAI_OCI_CREATED:?NOTEAI_OCI_CREATED is required}"
: "${NOTEAI_EVIDENCE_DIR:?NOTEAI_EVIDENCE_DIR is required}"

if [[ ! "${RELEASE_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "invalid RELEASE_COMMIT" >&2
  exit 2
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "native x86_64 runner required" >&2
  exit 2
fi
if [[ -e "${NOTEAI_EVIDENCE_DIR}" ]]; then
  echo "evidence directory already exists" >&2
  exit 2
fi

for command_name in docker jq syft trivy sha256sum; do
  command -v "${command_name}" >/dev/null
done
docker buildx version

mkdir -p "${NOTEAI_EVIDENCE_DIR}"
task_tmp="$(mktemp -d)"
container_names=()

cleanup() {
  local container_name
  for container_name in "${container_names[@]:-}"; do
    docker rm "${container_name}" >/dev/null 2>&1 || true
  done
  rm -rf "${task_tmp}"
}
trap cleanup EXIT

python_index="sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
python_amd64="sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045"
node_index="sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"
node_amd64="sha256:3d0f05455dea2c82e2f76e7e2543964c30f6b7d673fc1a83286736d44fe4c41c"

docker buildx imagetools inspect \
  "python:3.11.15-slim-trixie@${python_index}" --raw \
  > "${NOTEAI_EVIDENCE_DIR}/python-base-index.json"
docker buildx imagetools inspect \
  "node:20-bookworm-slim@${node_index}" --raw \
  > "${NOTEAI_EVIDENCE_DIR}/node-base-index.json"
jq -e --arg digest "${python_amd64}" \
  '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") | .digest == $digest' \
  "${NOTEAI_EVIDENCE_DIR}/python-base-index.json" >/dev/null
jq -e --arg digest "${node_amd64}" \
  '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") | .digest == $digest' \
  "${NOTEAI_EVIDENCE_DIR}/node-base-index.json" >/dev/null

roles=(api admin payment ai-worker xhs-http)
declare -A targets=(
  [api]="api-runtime"
  [admin]="admin-runtime"
  [payment]="payment-runtime"
  [ai-worker]="ai-worker-runtime"
  [xhs-http]="xhs-http-runtime"
)
declare -A expected_commands=(
  [api]='["/app/scripts/render_start_api.sh"]'
  [admin]='["/app/scripts/render_start_admin.sh"]'
  [payment]='["/app/scripts/render_start_payment.sh"]'
  [ai-worker]='["python","durable_ai_worker.py","--once"]'
  [xhs-http]='["/bin/false"]'
)

release_short="${RELEASE_COMMIT:0:7}"

for role in "${roles[@]}"; do
  target="${targets[${role}]}"
  image="noteai-native-evidence:${release_short}-${role}"
  metadata="${NOTEAI_EVIDENCE_DIR}/${role}-build-metadata.json"

  docker buildx build \
    --pull \
    --platform linux/amd64 \
    --target "${target}" \
    --build-arg "NOTEAI_OCI_REVISION=${RELEASE_COMMIT}" \
    --build-arg "NOTEAI_OCI_SOURCE=${NOTEAI_OCI_SOURCE}" \
    --build-arg "NOTEAI_OCI_VERSION=${NOTEAI_OCI_VERSION}" \
    --build-arg "NOTEAI_OCI_CREATED=${NOTEAI_OCI_CREATED}" \
    --metadata-file "${metadata}" \
    --load \
    --tag "${image}" \
    .

  inspect="${NOTEAI_EVIDENCE_DIR}/${role}-inspect.json"
  history="${NOTEAI_EVIDENCE_DIR}/${role}-history.jsonl"
  sbom="${NOTEAI_EVIDENCE_DIR}/${role}-sbom.cdx.json"
  vulnerability_report="${NOTEAI_EVIDENCE_DIR}/${role}-vuln-high-critical.json"
  secret_report="${NOTEAI_EVIDENCE_DIR}/${role}-secret.json"
  os_packages="${NOTEAI_EVIDENCE_DIR}/${role}-os-packages.txt"
  docker image inspect "${image}" > "${inspect}"
  docker history --no-trunc --format '{{json .}}' "${image}" > "${history}"

  valid=true
  jq -e '.[0].Architecture == "amd64" and .[0].Os == "linux"' "${inspect}" >/dev/null || valid=false
  jq -e '.[0].Config.User == "noteai"' "${inspect}" >/dev/null || valid=false
  jq -e '.[0].Config.Entrypoint == ["/app/scripts/docker_entrypoint.sh"]' "${inspect}" >/dev/null || valid=false
  jq -e --argjson expected "${expected_commands[${role}]}" \
    '.[0].Config.Cmd == $expected' "${inspect}" >/dev/null || valid=false
  jq -e --arg value "${RELEASE_COMMIT}" \
    '.[0].Config.Labels["org.opencontainers.image.revision"] == $value' "${inspect}" >/dev/null || valid=false
  jq -e --arg value "${NOTEAI_OCI_SOURCE}" \
    '.[0].Config.Labels["org.opencontainers.image.source"] == $value' "${inspect}" >/dev/null || valid=false
  jq -e --arg value "${NOTEAI_OCI_VERSION}" \
    '.[0].Config.Labels["org.opencontainers.image.version"] == $value' "${inspect}" >/dev/null || valid=false
  jq -e --arg value "${NOTEAI_OCI_CREATED}" \
    '.[0].Config.Labels["org.opencontainers.image.created"] == $value' "${inspect}" >/dev/null || valid=false
  jq -e --arg value "${role}" \
    '.[0].Config.Labels["com.noteai.runtime.role"] == $value' "${inspect}" >/dev/null || valid=false
  jq -e --arg value "NOTEAI_RUNTIME_ROLE=${role}" \
    '.[0].Config.Env | index($value) != null' "${inspect}" >/dev/null || valid=false

  container_name="noteai-native-evidence-${GITHUB_RUN_ID:-local}-${role}"
  container_names+=("${container_name}")
  docker create --name "${container_name}" "${image}" >/dev/null
  role_tmp="${task_tmp}/${role}"
  mkdir -p "${role_tmp}"
  docker cp "${container_name}:/etc/noteai-runtime-role" "${role_tmp}/runtime-role"
  docker cp "${container_name}:/etc/passwd" "${role_tmp}/passwd"
  docker cp "${container_name}:/var/lib/dpkg/status" "${role_tmp}/dpkg-status"
  test "$(tr -d '\r\n' < "${role_tmp}/runtime-role")" = "${role}" || valid=false
  grep -Eq '^noteai:x:999:999:' "${role_tmp}/passwd" || valid=false
  awk '/^Package: / {print $2}' "${role_tmp}/dpkg-status" | LC_ALL=C sort > "${os_packages}"

  syft "${image}" --output "cyclonedx-json=${sbom}"
  trivy image --quiet --scanners vuln --severity HIGH,CRITICAL \
    --format json --output "${vulnerability_report}" "${image}"
  trivy image --quiet --scanners secret \
    --format json --output "${secret_report}" "${image}"

  critical_count="$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' "${vulnerability_report}")"
  high_count="$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "HIGH")] | length' "${vulnerability_report}")"
  secret_count="$(jq '[.Results[]?.Secrets[]?] | length' "${secret_report}")"
  browser_component_count="$(jq '[.components[]? | select(.name | ascii_downcase | test("playwright|chromium|google-chrome"))] | length' "${sbom}")"
  cryptography_component_count="$(jq '[.components[]? | select(.name == "cryptography" and .version == "48.0.1")] | length' "${sbom}")"
  forbidden_os_count="$(grep -Ec '^(libgl1|libglib2\.0-0|libsm6|libxext6|libxrender1|chromium|google-chrome.*)$' "${os_packages}" || true)"
  forbidden_os_count="${forbidden_os_count:-0}"

  if [[ "${critical_count}" != "0" || "${high_count}" != "0" || "${secret_count}" != "0" \
    || "${browser_component_count}" != "0" || "${cryptography_component_count}" != "1" \
    || "${forbidden_os_count}" != "0" ]]; then
    valid=false
  fi

  if [[ "${role}" == "payment" ]]; then
    jq -e '.[0].Config.Env | index("NOTEAI_PAYMENT_CALLBACK_ENABLED=0") != null' "${inspect}" >/dev/null || valid=false
  elif [[ "${role}" == "ai-worker" ]]; then
    jq -e '.[0].Config.Env | index("NOTEAI_DURABLE_AI_SUSPENDED=1") != null' "${inspect}" >/dev/null || valid=false
    jq -e '.[0].Config.Healthcheck.Test == ["NONE"]' "${inspect}" >/dev/null || valid=false
  elif [[ "${role}" == "xhs-http" ]]; then
    jq -e '.[0].Config.Env | index("NOTEAI_XHS_COLLECTION_SUSPENDED=1") != null' "${inspect}" >/dev/null || valid=false
    jq -e '.[0].Config.Env | index("NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http") != null' "${inspect}" >/dev/null || valid=false
    jq -e '.[0].Config.Healthcheck.Test == ["NONE"]' "${inspect}" >/dev/null || valid=false
    docker cp "${container_name}:/app/model/vendor/spider_xhs/xhs_main_260411.js" "${role_tmp}/xhs-main.js"
    docker cp "${container_name}:/app/model/vendor/spider_xhs/xhs_rap.js" "${role_tmp}/xhs-rap.js"
    docker cp "${container_name}:/opt/noteai/xhs-node/node_modules/crypto-js/package.json" "${role_tmp}/crypto-js-package.json"
    test "$(sha256sum "${role_tmp}/xhs-main.js" | awk '{print $1}')" = "723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d" || valid=false
    test "$(sha256sum "${role_tmp}/xhs-rap.js" | awk '{print $1}')" = "e79fe1c79c97a73fbf5fdb6420af114ff591902aa60b436ac4b803a99b806d2e" || valid=false
    test "$(jq -r '.version' "${role_tmp}/crypto-js-package.json")" = "4.2.0" || valid=false
  fi

  image_id="$(jq -r '.[0].Id' "${inspect}")"
  sbom_sha256="$(sha256sum "${sbom}" | awk '{print $1}')"
  vulnerability_sha256="$(sha256sum "${vulnerability_report}" | awk '{print $1}')"
  secret_sha256="$(sha256sum "${secret_report}" | awk '{print $1}')"
  jq -n \
    --arg role "${role}" \
    --arg target "${target}" \
    --arg image_id "${image_id}" \
    --arg sbom_sha256 "${sbom_sha256}" \
    --arg vulnerability_sha256 "${vulnerability_sha256}" \
    --arg secret_sha256 "${secret_sha256}" \
    --argjson critical "${critical_count}" \
    --argjson high "${high_count}" \
    --argjson secrets "${secret_count}" \
    --argjson browser_components "${browser_component_count}" \
    --argjson cryptography_48_0_1_components "${cryptography_component_count}" \
    --argjson forbidden_os_packages "${forbidden_os_count}" \
    --argjson passed "${valid}" \
    '{
      role: $role,
      target: $target,
      image_id: $image_id,
      platform: "linux/amd64",
      sbom_sha256: $sbom_sha256,
      vulnerability_report_sha256: $vulnerability_sha256,
      secret_report_sha256: $secret_sha256,
      findings: {
        critical: $critical,
        high: $high,
        secrets: $secrets,
        browser_components: $browser_components,
        cryptography_48_0_1_components: $cryptography_48_0_1_components,
        forbidden_os_packages: $forbidden_os_packages
      },
      passed: $passed
    }' > "${NOTEAI_EVIDENCE_DIR}/${role}-summary.json"

  docker rm "${container_name}" >/dev/null
done

role_summaries="$(jq -s '.' "${NOTEAI_EVIDENCE_DIR}"/*-summary.json)"
jq -n \
  --arg schema_version "noteai.native-release-evidence.v1" \
  --arg release_commit "${RELEASE_COMMIT}" \
  --arg source "${NOTEAI_OCI_SOURCE}" \
  --arg version "${NOTEAI_OCI_VERSION}" \
  --arg created "${NOTEAI_OCI_CREATED}" \
  --arg runner_architecture "$(uname -m)" \
  --arg python_index "${python_index}" \
  --arg python_amd64 "${python_amd64}" \
  --arg node_index "${node_index}" \
  --arg node_amd64 "${node_amd64}" \
  --argjson roles "${role_summaries}" \
  '{
    schema_version: $schema_version,
    release_commit: $release_commit,
    source: $source,
    version: $version,
    created: $created,
    runner_architecture: $runner_architecture,
    base_images: {
      python: {index: $python_index, linux_amd64: $python_amd64},
      node: {index: $node_index, linux_amd64: $node_amd64}
    },
    roles: $roles,
    passed: all($roles[]; .passed == true)
  }' > "${NOTEAI_EVIDENCE_DIR}/summary.json"
