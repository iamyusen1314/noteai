#!/bin/bash
set +x
set -Eeuo pipefail
umask 077
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export HOME='/root'
unset \
  ALIBABA_CLOUD_ACCESS_KEY_ID \
  ALIBABA_CLOUD_ACCESS_KEY_SECRET \
  ALIBABA_CLOUD_SECURITY_TOKEN \
  ALICLOUD_ACCESS_KEY \
  ALICLOUD_SECRET_KEY \
  ALICLOUD_SECURITY_TOKEN \
  BUILDKIT_HOST \
  BUILDX_BUILDER \
  BUILDX_CONFIG \
  DOCKER_CERT_PATH \
  DOCKER_CONFIG \
  DOCKER_CONTEXT \
  DOCKER_HOST \
  DOCKER_TLS_VERIFY
export DOCKER_CONTEXT='default'

release='5335bdaed933b1f999b5f819c047ec50c11821ae'
release_created='2026-07-30T13:29:02Z'
release_version='git-5335bda-amd64-r1'
oci_source='https://github.com/iamyusen1314/noteai'
canonical_image='noteai-native-evidence:5335bda-admin'
local_image='noteai-local:git-5335bda-amd64-admin-r1'
registry_host='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com'
repository='noteai/app'
tag='git-5335bda-amd64-admin-r1'
remote_image="${registry_host}/${repository}:${tag}"
stage_a_root='/var/lib/noteai/admin-5335-current-public-ecr'
evidence_root="${stage_a_root}/evidence"
task_root='/var/lib/noteai/admin-5335-stage-b-private-acr'
docker_config="${task_root}/docker-config"
push_log="${task_root}/push.log"
descriptor_log="${task_root}/descriptor.txt"
raw_manifest="${task_root}/manifest.json"
phase='preflight'
published=0
push_started=0
local_image_id=''
push_digest=''
manifest_digest=''
task_root_owned=0
remote_alias_created=0

docker_auth_entry_count() {
  local config_path="${1:-/root/.docker/config.json}"
  if [ ! -e "$config_path" ]; then
    printf '0\n'
    return
  fi
  [ -f "$config_path" ] && [ ! -L "$config_path" ] || return 1
  jq -er '
    if type != "object" then
      error("docker config must be an object")
    else
      ((.auths // {}) |
        if type == "object" then length else error("auths must be an object") end) +
      ((.credHelpers // {}) |
        if type == "object" then length else error("credHelpers must be an object") end) +
      (if ((.credsStore // "") | type) != "string" then
         error("credsStore must be a string")
       elif (.credsStore // "") == "" then 0 else 1 end)
    end
  ' "$config_path"
}

extract_push_digest() {
  local path="$1"
  local match
  match="$(
    awk '
      {
        for (field = 1; field <= NF; field++) {
          if ($field == "digest:" &&
              $(field + 1) ~ /^sha256:[0-9a-f]{64}$/) {
            print $(field + 1)
          }
        }
      }
    ' "$path"
  )"
  [[ "$match" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$match"
}

extract_descriptor_digest() {
  local path="$1"
  local match
  match="$(
    awk '$1 == "Digest:" && $2 ~ /^sha256:[0-9a-f]{64}$/ {print $2}' \
      "$path"
  )"
  [[ "$match" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$match"
}

build_or_push_process_count() {
  ps -eo args= | awk '
    /docker.* (build|push)( |$)/ ||
    /buildx.* (build|create)( |$)/ ||
    /buildkitd( |$)/ {count++}
    END {print count + 0}
  '
}

database_connection_count() {
  ss -Htan state established 2>/dev/null |
    awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {count++} END {print count + 0}'
}

cleanup_sensitive_state() {
  unset registry_password
  if [ "$task_root_owned" = '1' ] && [ -d "$docker_config" ]; then
    env DOCKER_CONFIG="$docker_config" \
      docker logout "$registry_host" >/dev/null 2>&1 || true
  fi
  if [ "$remote_alias_created" = '1' ]; then
    docker image rm "$remote_image" >/dev/null 2>&1 || true
  fi
  if [ "$task_root_owned" = '1' ]; then
    rm -rf -- "$task_root" || return 1
  fi
}

on_exit() {
  local exit_code=$?
  local cleanup_exit=0
  trap - EXIT
  cleanup_sensitive_state || cleanup_exit=$?
  if [ "$exit_code" -eq 0 ] && [ "$cleanup_exit" -ne 0 ]; then
    exit_code="$cleanup_exit"
  fi
  if [ "$exit_code" -ne 0 ]; then
    printf 'NOTEAI_ADMIN_STAGE_B=FAIL phase=%s push_started=%s published=%s cleanup_exit=%s manual_retries=0\n' \
      "$phase" "$push_started" "$published" "$cleanup_exit" >&2
  fi
  exit "$exit_code"
}

offline_self_test() {
  local fixture
  fixture="$(mktemp -d)"
  trap 'rm -rf -- "$fixture"' RETURN

  printf 'layer complete\n%s: digest: sha256:%064d size: 1234\n' \
    "$tag" 0 > "$fixture/push-ok.log"
  [ "$(extract_push_digest "$fixture/push-ok.log")" = \
    "sha256:$(printf '%064d' 0)" ]
  cp "$fixture/push-ok.log" "$fixture/push-duplicate.log"
  printf '%s: digest: sha256:%064d size: 1234\n' "$tag" 1 \
    >> "$fixture/push-duplicate.log"
  if extract_push_digest "$fixture/push-duplicate.log" >/dev/null 2>&1; then
    return 1
  fi

  printf 'Name: test\nMediaType: application/vnd.oci.image.manifest.v1+json\nDigest: sha256:%064d\n' \
    2 > "$fixture/descriptor-ok.txt"
  [ "$(extract_descriptor_digest "$fixture/descriptor-ok.txt")" = \
    "sha256:$(printf '%064d' 2)" ]
  printf 'Digest: sha256:%064d\n' 3 >> "$fixture/descriptor-ok.txt"
  if extract_descriptor_digest "$fixture/descriptor-ok.txt" >/dev/null 2>&1; then
    return 1
  fi

  printf 'NOTEAI_ADMIN_STAGE_B_OFFLINE_SELF_TEST=PASS\n'
}

if [ "${1:-}" = '--offline-self-test' ]; then
  [ "$#" = '1' ]
  offline_self_test
  exit 0
fi

trap on_exit EXIT

[ "$#" = '1' ] || {
  echo 'usage: admin_item20_stage_b_private_acr.sh REGISTRY_USERNAME' >&2
  exit 64
}
registry_username="$1"
[[ "$registry_username" =~ ^[[:alnum:]_.:@+-]{1,256}$ ]]

[ "$(id -u)" = '0' ]
[ "$(uname -s)" = 'Linux' ]
[ "$(uname -m)" = 'x86_64' ]
for command_name in docker jq sha256sum awk find stat ps ss cmp sort wc; do
  command -v "$command_name" >/dev/null
done
docker buildx version >/dev/null
[ "$(docker context show)" = 'default' ]
[ "$(docker context inspect default --format '{{.Endpoints.docker.Host}}')" = \
  'unix:///var/run/docker.sock' ]
[ -S /var/run/docker.sock ]

[ ! -e "$task_root" ] && [ ! -L "$task_root" ]
[ -d "$evidence_root" ] && [ ! -L "$evidence_root" ]
[ "$(readlink -f "$evidence_root")" = "$evidence_root" ]
[ "$(stat -c '%u:%g:%a' "$evidence_root")" = '0:0:700' ]
[ "$(docker_auth_entry_count)" = '0' ]
[ "$(docker ps -q | wc -l | tr -d ' ')" = '0' ]
[ "$(build_or_push_process_count)" = '0' ]
[ "$(database_connection_count)" = '0' ]
! docker image inspect "$remote_image" >/dev/null 2>&1

local_image_id="$(docker image inspect "$local_image" --format '{{.Id}}')"
[ -n "$local_image_id" ]
[ "$(docker image inspect "$canonical_image" --format '{{.Id}}')" = \
  "$local_image_id" ]
[ "$(docker image inspect "$local_image" --format '{{.Architecture}}/{{.Os}}')" = \
  'amd64/linux' ]
[ "$(docker image inspect "$local_image" --format '{{.Config.User}}')" = 'noteai' ]
[ "$(docker image inspect "$local_image" --format '{{json .Config.Entrypoint}}')" = \
  '["/app/scripts/docker_entrypoint.sh"]' ]
[ "$(docker image inspect "$local_image" --format '{{json .Config.Cmd}}')" = \
  '["/app/scripts/render_start_admin.sh"]' ]
[ "$(docker image inspect "$local_image" --format \
  '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$release" ]
[ "$(docker image inspect "$local_image" --format \
  '{{index .Config.Labels "org.opencontainers.image.created"}}')" = \
  "$release_created" ]
[ "$(docker image inspect "$local_image" --format \
  '{{index .Config.Labels "org.opencontainers.image.version"}}')" = \
  "$release_version" ]
[ "$(docker image inspect "$local_image" --format \
  '{{index .Config.Labels "org.opencontainers.image.source"}}')" = \
  "$oci_source" ]
[ "$(docker image inspect "$local_image" --format \
  '{{index .Config.Labels "com.noteai.runtime.role"}}')" = 'admin' ]

expected_evidence_files=(
  admin-build-metadata.json
  admin-history.jsonl
  admin-inspect.json
  admin-os-packages.txt
  admin-sbom.cdx.json
  admin-secret.json
  admin-summary.json
  admin-vuln-high-critical.json
  node-base-index.json
  python-base-index.json
  summary.json
)
[ "$(find "$evidence_root" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')" = \
  '11' ]
[ -z "$(find "$evidence_root" -mindepth 1 -maxdepth 1 \
  \( ! -type f -o -type l \) -print -quit)" ]
for evidence_name in "${expected_evidence_files[@]}"; do
  evidence_path="${evidence_root}/${evidence_name}"
  [ -f "$evidence_path" ] && [ ! -L "$evidence_path" ]
  [ "$(stat -c '%u:%g:%a' "$evidence_path")" = '0:0:600' ]
done
[ "$({ find "$evidence_root" -mindepth 1 -maxdepth 1 -type f -printf '%f\n'; } | \
  LC_ALL=C sort)" = "$(printf '%s\n' "${expected_evidence_files[@]}" | \
  LC_ALL=C sort)" ]

jq -e \
  --arg release "$release" \
  --arg created "$release_created" \
  --arg version "$release_version" '
    .schema_version == "noteai.native-release-evidence.v1" and
    .release_commit == $release and .created == $created and
    .version == $version and .runner_architecture == "x86_64" and
    (.roles | type == "array" and length == 1) and
    .roles[0].role == "admin" and .roles[0].target == "admin-runtime" and
    .roles[0].image_id == $image_id and .roles[0].platform == "linux/amd64"
  ' --arg image_id "$local_image_id" "$evidence_root/summary.json" >/dev/null

jq -e --arg image_id "$local_image_id" '
  .role == "admin" and .target == "admin-runtime" and
  .image_id == $image_id and .platform == "linux/amd64"
' "$evidence_root/admin-summary.json" >/dev/null

jq -e --arg image_id "$local_image_id" '
  type == "array" and length == 1 and .[0].Id == $image_id
' "$evidence_root/admin-inspect.json" >/dev/null

jq -e --arg image_id "$local_image_id" '
    .["containerimage.digest"] == $image_id and
    .["containerimage.config.digest"] == $image_id
  ' "$evidence_root/admin-build-metadata.json" >/dev/null

build_metadata_sha="$(sha256sum "$evidence_root/admin-build-metadata.json" | awk '{print $1}')"
inspect_sha="$(sha256sum "$evidence_root/admin-inspect.json" | awk '{print $1}')"
sbom_sha="$(sha256sum "$evidence_root/admin-sbom.cdx.json" | awk '{print $1}')"
vuln_sha="$(sha256sum "$evidence_root/admin-vuln-high-critical.json" | awk '{print $1}')"
secret_sha="$(sha256sum "$evidence_root/admin-secret.json" | awk '{print $1}')"
summary_sha="$(sha256sum "$evidence_root/summary.json" | awk '{print $1}')"

phase='credential_input'
registry_password=''
IFS= read -r registry_password || [ -n "$registry_password" ]
[ -n "$registry_password" ] && [ "${#registry_password}" -le 8192 ]
extra_input=''
if IFS= read -r extra_input || [ -n "$extra_input" ]; then
  echo 'registry password input must contain exactly one line' >&2
  exit 65
fi
unset extra_input

mkdir -m 0700 -- "$task_root"
task_root_owned=1
install -d -o root -g root -m 0700 "$docker_config"

phase='registry_login'
if ! printf '%s\n' "$registry_password" |
  env DOCKER_CONFIG="$docker_config" \
    docker login --username "$registry_username" --password-stdin \
      "$registry_host" >/dev/null 2>&1; then
  exit 1
fi
unset registry_password
[ -f "$docker_config/config.json" ] && [ ! -L "$docker_config/config.json" ]
chmod 0600 "$docker_config/config.json"
[ "$(docker_auth_entry_count "$docker_config/config.json")" = '1' ]

phase='single_push'
docker tag "$local_image" "$remote_image"
remote_alias_created=1
[ "$(docker image inspect "$remote_image" --format '{{.Id}}')" = \
  "$local_image_id" ]
push_started=1
if ! env DOCKER_CONFIG="$docker_config" \
  docker push "$remote_image" 2>&1 | tee "$push_log"; then
  exit 1
fi
published=1
push_digest="$(extract_push_digest "$push_log")"

phase='manifest_readback'
env DOCKER_CONFIG="$docker_config" \
  docker buildx imagetools inspect "$remote_image" > "$descriptor_log"
manifest_digest="$(extract_descriptor_digest "$descriptor_log")"
env DOCKER_CONFIG="$docker_config" \
  docker buildx imagetools inspect "$remote_image" --raw > "$raw_manifest"
manifest_config_digest="$(jq -er '.config.digest' "$raw_manifest")"
jq -e --arg local_id "$local_image_id" '
  .schemaVersion == 2 and
  (.mediaType == "application/vnd.docker.distribution.manifest.v2+json" or
   .mediaType == "application/vnd.oci.image.manifest.v1+json") and
  (.manifests | not) and
  .config.digest == $local_id and .config.size > 0 and
  (.config.mediaType == "application/vnd.docker.container.image.v1+json" or
   .config.mediaType == "application/vnd.oci.image.config.v1+json") and
  (.layers | type == "array" and length > 0) and
  all(.layers[];
    (.digest | test("^sha256:[0-9a-f]{64}$")) and
    (.size | type == "number" and . > 0))
' "$raw_manifest" >/dev/null
[ "$push_digest" = "$manifest_digest" ]
[ "$manifest_config_digest" = "$local_image_id" ]
[ "$manifest_digest" != "$local_image_id" ]
raw_manifest_sha="$(sha256sum "$raw_manifest" | awk '{print $1}')"

phase='cleanup'
cleanup_sensitive_state
[ ! -e "$task_root" ] && [ ! -L "$task_root" ]
! docker image inspect "$remote_image" >/dev/null 2>&1
[ "$(docker image inspect "$canonical_image" --format '{{.Id}}')" = \
  "$local_image_id" ]
[ "$(docker image inspect "$local_image" --format '{{.Id}}')" = \
  "$local_image_id" ]
[ "$(docker_auth_entry_count)" = '0' ]
[ "$(docker ps -q | wc -l | tr -d ' ')" = '0' ]
[ "$(build_or_push_process_count)" = '0' ]
[ "$(database_connection_count)" = '0' ]

trap - EXIT
printf 'NOTEAI_ADMIN_STAGE_B=PUSH_MANIFEST_PASS release=%s tag=%s evidence_files=11 pushes=1 manual_retries=0\n' \
  "$release" "$tag"
printf 'NOTEAI_ADMIN_STAGE_B_DIGESTS local_config=%s push=%s manifest=%s raw_manifest_sha256=%s manifest_config=%s\n' \
  "$local_image_id" "$push_digest" "$manifest_digest" \
  "$raw_manifest_sha" "$manifest_config_digest"
printf 'NOTEAI_ADMIN_STAGE_B_HASHES build_metadata=%s inspect=%s sbom=%s vuln=%s secret=%s summary=%s\n' \
  "$build_metadata_sha" "$inspect_sha" "$sbom_sha" "$vuln_sha" \
  "$secret_sha" "$summary_sha"
printf 'NOTEAI_ADMIN_STAGE_B_CLEANUP docker_auth_entries=0 task_root=absent remote_alias=absent canonical_and_local_images=retained containers=0 push_processes=0 database_connections=0\n'
