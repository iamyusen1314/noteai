#!/usr/bin/env bash
set -euo pipefail

# Run only after explicit authorization and an authenticated `gh` login. This
# performs exactly one provider metadata read and one artifact ZIP download. It
# never logs in to a container registry, pushes, deploys or contacts production.

: "${NOTEAI_EXPECTED_ARTIFACT_ID:?NOTEAI_EXPECTED_ARTIFACT_ID is required}"
: "${NOTEAI_CONTROL_COMMIT:?NOTEAI_CONTROL_COMMIT is required}"
: "${NOTEAI_REQUEST_SHA256:?NOTEAI_REQUEST_SHA256 is required}"
: "${NOTEAI_PROVIDER_DOWNLOAD_DIR:?NOTEAI_PROVIDER_DOWNLOAD_DIR is required}"
: "${NOTEAI_EXPECTED_DOWNLOAD_HELPER_SHA256:?NOTEAI_EXPECTED_DOWNLOAD_HELPER_SHA256 is required}"
: "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH:?NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH is required}"
: "${NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256:?NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256 is required}"
: "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH:?NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH is required}"
: "${NOTEAI_BUNDLE_VERIFIER_SHA256:?NOTEAI_BUNDLE_VERIFIER_SHA256 is required}"

repository="iamyusen1314/noteai"
artifact_name="admin-dependency-prefix-cache-5335bda-v2"

for command_name in gh python3 sha256sum stat find sort mv awk dirname; do
  command -v "${command_name}" >/dev/null
done
[[ "${NOTEAI_EXPECTED_ARTIFACT_ID}" =~ ^[1-9][0-9]*$ ]]
[[ "${NOTEAI_CONTROL_COMMIT}" =~ ^[0-9a-f]{40}$ ]]
[[ "${NOTEAI_REQUEST_SHA256}" =~ ^[0-9a-f]{64}$ ]]
[[ "${NOTEAI_EXPECTED_DOWNLOAD_HELPER_SHA256}" =~ ^[0-9a-f]{64}$ ]]
[[ "${NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256}" =~ ^[0-9a-f]{64}$ ]]
[[ "${NOTEAI_BUNDLE_VERIFIER_SHA256}" =~ ^[0-9a-f]{64}$ ]]
test -f "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}"
test -f "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}"
test "$(
  sha256sum "$0" |
    awk '{print $1}'
)" = "${NOTEAI_EXPECTED_DOWNLOAD_HELPER_SHA256}"
test "$(
  sha256sum "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}" |
    awk '{print $1}'
)" = "${NOTEAI_PROVIDER_DOWNLOAD_VERIFIER_SHA256}"
test "$(
  sha256sum "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" |
    awk '{print $1}'
)" = "${NOTEAI_BUNDLE_VERIFIER_SHA256}"
test ! -e "${NOTEAI_PROVIDER_DOWNLOAD_DIR}"

umask 077
task_tmp="$(mktemp -d)"
metadata="${task_tmp}/provider-metadata.json"
artifact_zip="${task_tmp}/artifact.zip"
preflight="${task_tmp}/provider-preflight.json"
bundle="${task_tmp}/bundle"
transport="${task_tmp}/transport"
receipt="${task_tmp}/provider-receipt.json"

cleanup() {
  task_tmp_parent="$(dirname "${task_tmp}")"
  configured_tmp_parent="${TMPDIR:-/nonexistent}"
  configured_tmp_parent="${configured_tmp_parent%/}"
  if [[ "${task_tmp_parent}" == "/tmp" || \
        "${task_tmp_parent}" == "${configured_tmp_parent}" ]]; then
    rm -rf "${task_tmp}"
  fi
}
trap cleanup EXIT

gh auth status --hostname github.com >/dev/null 2>&1
GH_REPO="${repository}" gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "repos/${repository}/actions/artifacts/${NOTEAI_EXPECTED_ARTIFACT_ID}" \
  > "${metadata}"

python3 "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}" \
  preflight-metadata \
  --metadata "${metadata}" \
  --control-commit "${NOTEAI_CONTROL_COMMIT}" \
  --artifact-id "${NOTEAI_EXPECTED_ARTIFACT_ID}" \
  --output "${preflight}"

GH_REPO="${repository}" gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "repos/${repository}/actions/artifacts/${NOTEAI_EXPECTED_ARTIFACT_ID}/zip" |
  python3 "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}" \
    receive-zip \
    --preflight "${preflight}" \
    --control-commit "${NOTEAI_CONTROL_COMMIT}" \
    --artifact-id "${NOTEAI_EXPECTED_ARTIFACT_ID}" \
    --output "${artifact_zip}"

python3 "${NOTEAI_TRUSTED_PROVIDER_DOWNLOAD_VERIFIER_PATH}" \
  verify-download \
  --metadata "${metadata}" \
  --zip "${artifact_zip}" \
  --transport-dir "${transport}" \
  --bundle "${bundle}" \
  --bundle-verifier "${NOTEAI_TRUSTED_BUNDLE_VERIFIER_PATH}" \
  --bundle-verifier-sha256 "${NOTEAI_BUNDLE_VERIFIER_SHA256}" \
  --control-commit "${NOTEAI_CONTROL_COMMIT}" \
  --request-sha256 "${NOTEAI_REQUEST_SHA256}" \
  --artifact-id "${NOTEAI_EXPECTED_ARTIFACT_ID}" \
  --receipt "${receipt}"

mkdir -m 0700 "${NOTEAI_PROVIDER_DOWNLOAD_DIR}"
mv "${transport}" "${NOTEAI_PROVIDER_DOWNLOAD_DIR}/transport"
mv "${receipt}" "${NOTEAI_PROVIDER_DOWNLOAD_DIR}/provider-receipt.json"
find "${NOTEAI_PROVIDER_DOWNLOAD_DIR}" -type d -exec chmod 0700 {} +
find "${NOTEAI_PROVIDER_DOWNLOAD_DIR}" -type f -exec chmod 0600 {} +
test "$(
  python3 -c '
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["artifact"]["artifact_name"])
' "${NOTEAI_PROVIDER_DOWNLOAD_DIR}/provider-receipt.json"
)" = "${artifact_name}"
receipt_sha256="$(
  sha256sum "${NOTEAI_PROVIDER_DOWNLOAD_DIR}/provider-receipt.json" |
    awk '{print $1}'
)"
echo "admin_dependency_cache_download=PASS receipt_sha256=${receipt_sha256}"
