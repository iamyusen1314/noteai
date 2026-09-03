#!/bin/bash
set +x
set -Eeuo pipefail
umask 077
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
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
export DOCKER_CONTEXT=default

release='cad5ce35664f617c6e19f90a6159285ddf975594'
release_created='2026-08-05T14:30:09Z'
release_version='git-cad5ce3-amd64-r1'
oci_source='https://github.com/iamyusen1314/noteai'
registry_host='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com'
repository='noteai/app'
tag='git-cad5ce3-amd64-ai-worker-r1'
repository_ref="${registry_host}/${repository}"
task_root='/var/lib/noteai/durable-ai-cad5-fresh-import'
docker_config="${task_root}/docker-config"
pull_log="${task_root}/pull.log"

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

database_connection_count() {
  ss -Htan state established 2>/dev/null |
    awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {count++} END {print count + 0}'
}

extract_pull_digest() {
  local log_path="$1" match
  match="$(awk '$1=="Digest:" && $2 ~ /^sha256:[0-9a-f]{64}$/ {print $2}' "$log_path")"
  [[ "$match" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$match"
}

verify_digest() {
  [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]]
}

offline_self_test() (
  set -euo pipefail
  local fixture
  fixture="$(mktemp -d "${TMPDIR:-/tmp}/noteai-durable-ai-import.XXXXXX")"
  trap 'rm -rf -- "$fixture"' EXIT
  verify_digest "sha256:$(printf '%064d' 1)"
  if verify_digest 'sha256:not-a-digest' >/dev/null 2>&1; then exit 1; fi
  printf 'Status: image is up to date\nDigest: sha256:%064d\n' 2 > "$fixture/pull.log"
  [ "$(extract_pull_digest "$fixture/pull.log")" = "sha256:$(printf '%064d' 2)" ]
  printf 'Digest: sha256:%064d\n' 3 >> "$fixture/pull.log"
  if extract_pull_digest "$fixture/pull.log" >/dev/null 2>&1; then exit 1; fi
  printf '{"auths":{},"credHelpers":{},"credsStore":""}\n' > "$fixture/config.json"
  [ "$(docker_auth_entry_count "$fixture/config.json")" = '0' ]
  printf 'NOTEAI_DURABLE_AI_CAD5_FRESH_IMPORTER_OFFLINE_SELF_TEST=PASS\n'
)

if [ "${1:-}" = '--offline-self-test' ]; then
  [ "$#" = '1' ]
  offline_self_test
  exit
fi

[ "$#" = '3' ] || {
  echo 'usage: durable_ai_cad5_fresh_importer.sh REGISTRY_USERNAME MANIFEST_DIGEST CONFIG_DIGEST' >&2
  exit 64
}
registry_username="$1"
manifest_digest="$2"
expected_config_digest="$3"
[[ "$registry_username" =~ ^[[:alnum:]_.:@+-]{1,256}$ ]]
verify_digest "$manifest_digest"
verify_digest "$expected_config_digest"
[ "$manifest_digest" != "$expected_config_digest" ]
digest_ref="${repository_ref}@${manifest_digest}"
case "$task_root" in
  /var/lib/noteai/durable-ai-cad5-fresh-import) ;;
  *) exit 90 ;;
esac

phase='preflight'
task_root_owned=0
registry_password=''
extra_input=''
pull_started=0
pull_completed=0

cleanup_sensitive_state() {
  unset registry_password
  if [ "$task_root_owned" = '1' ] && [ -d "$docker_config" ]; then
    env DOCKER_CONFIG="$docker_config" docker logout "$registry_host" >/dev/null 2>&1 || true
  fi
  if [ "$task_root_owned" = '1' ] && [ -e "$task_root" ]; then
    rm -rf -- "$task_root"
  fi
}

on_exit() {
  local exit_code=$? cleanup_exit=0
  trap - EXIT
  cleanup_sensitive_state || cleanup_exit=$?
  if [ "$exit_code" -eq 0 ] && [ "$cleanup_exit" -ne 0 ]; then exit_code="$cleanup_exit"; fi
  if [ "$exit_code" -ne 0 ]; then
    image_cleanup='not_observed'
    if docker image inspect "$digest_ref" >/dev/null 2>&1; then
      if docker image rm "$digest_ref" >/dev/null 2>&1; then
        image_cleanup='removed'
      else
        image_cleanup='failed'
      fi
    elif docker image ls -aq >/dev/null 2>&1; then
      image_cleanup='no_exact_image_observed'
    else
      image_cleanup='inspect_unavailable'
    fi
    printf 'NOTEAI_DURABLE_AI_CAD5_FRESH_IMPORTER=FAIL phase=%s pull_started=%s pull_completed=%s image_cleanup=%s retries=0 host_reuse=forbidden\n' \
      "$phase" "$pull_started" "$pull_completed" "$image_cleanup" >&2
  fi
  exit "$exit_code"
}
trap on_exit EXIT

[ "$(id -u)" = '0' ]
[ "$(uname -s)" = 'Linux' ] && [ "$(uname -m)" = 'x86_64' ]
for command_name in docker jq awk find stat ss sort wc timeout; do
  command -v "$command_name" >/dev/null
done
[ "$(systemctl is-active docker)" = 'active' ]
[ "$(docker context show)" = 'default' ]
[ "$(docker context inspect default --format '{{.Endpoints.docker.Host}}')" = \
  'unix:///var/run/docker.sock' ]
[ -S /var/run/docker.sock ]
[ ! -e "$task_root" ] && [ ! -L "$task_root" ]
[ "$(docker_auth_entry_count)" = '0' ]
[ "$(docker image ls -aq | LC_ALL=C sort -u | wc -l | tr -d ' ')" = '0' ]
[ "$(docker ps -aq | wc -l | tr -d ' ')" = '0' ]
[ "$(docker volume ls -q | wc -l | tr -d ' ')" = '0' ]
[ "$(docker system df --format '{{.Type}}={{.TotalCount}}' | awk -F= '$1=="Build Cache" {print $2}')" = '0' ]
[ "$(database_connection_count)" = '0' ]
! docker image inspect "$digest_ref" >/dev/null 2>&1

phase='credential_input'
IFS= read -r registry_password || [ -n "$registry_password" ]
[ -n "$registry_password" ] && [ "${#registry_password}" -le 8192 ]
if IFS= read -r extra_input || [ -n "$extra_input" ]; then
  echo 'registry password input must contain exactly one line' >&2
  exit 65
fi
unset extra_input
mkdir -m 0700 -- "$task_root"
task_root_owned=1
install -d -o root -g root -m 0700 "$docker_config"

phase='registry_login'
printf '%s\n' "$registry_password" | env DOCKER_CONFIG="$docker_config" \
  docker login --username "$registry_username" --password-stdin "$registry_host" >/dev/null 2>&1
unset registry_password
[ -f "$docker_config/config.json" ] && [ ! -L "$docker_config/config.json" ]
chmod 0600 "$docker_config/config.json"
[ "$(stat -c '%u:%g:%a' "$docker_config/config.json")" = '0:0:600' ]
[ "$(docker_auth_entry_count "$docker_config/config.json")" = '1' ]

phase='single_exact_digest_pull'
pull_started=1
timeout --foreground --signal=TERM --kill-after=30s 2700s \
  env DOCKER_CONFIG="$docker_config" docker pull --platform linux/amd64 "$digest_ref" 2>&1 | tee "$pull_log"
pull_completed=1
pulled_digest="$(extract_pull_digest "$pull_log")"
[ "$pulled_digest" = "$manifest_digest" ]

phase='import_acceptance'
actual_config_digest="$(docker image inspect "$digest_ref" --format '{{.Id}}')"
[ "$actual_config_digest" = "$expected_config_digest" ]
[ "$(docker image inspect "$digest_ref" --format '{{.Architecture}}/{{.Os}}')" = 'amd64/linux' ]
[ "$(docker image inspect "$digest_ref" --format '{{.Config.User}}')" = 'noteai' ]
[ "$(docker image inspect "$digest_ref" --format '{{json .Config.Entrypoint}}')" = \
  '["/app/scripts/docker_entrypoint.sh"]' ]
[ "$(docker image inspect "$digest_ref" --format '{{json .Config.Cmd}}')" = \
  '["python","durable_ai_worker.py","--once"]' ]
[ "$(docker image inspect "$digest_ref" --format '{{json .Config.Healthcheck.Test}}')" = \
  '["NONE"]' ]
[ "$(docker image inspect "$digest_ref" --format '{{.Config.WorkingDir}}')" = '/app/model' ]
[ "$(docker image inspect "$digest_ref" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$release" ]
[ "$(docker image inspect "$digest_ref" --format '{{index .Config.Labels "org.opencontainers.image.created"}}')" = "$release_created" ]
[ "$(docker image inspect "$digest_ref" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$release_version" ]
[ "$(docker image inspect "$digest_ref" --format '{{index .Config.Labels "org.opencontainers.image.source"}}')" = "$oci_source" ]
[ "$(docker image inspect "$digest_ref" --format '{{index .Config.Labels "com.noteai.runtime.role"}}')" = 'ai-worker' ]
[ "$(docker image inspect "$digest_ref" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxc 'NOTEAI_DURABLE_AI_SUSPENDED=1')" = '1' ]
[ "$(docker image inspect "$digest_ref" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxc 'NOTEAI_RUNTIME_ROLE=ai-worker')" = '1' ]
docker image inspect "$digest_ref" | jq -e --arg digest_ref "$digest_ref" '
  length == 1 and .[0].RepoTags == [] and .[0].RepoDigests == [$digest_ref] and
  .[0].Size > 0 and
  (.[0].RootFS.Layers | type == "array" and length > 0) and
  all(.[0].RootFS.Layers[]; test("^sha256:[0-9a-f]{64}$"))
' >/dev/null
[ "$(docker image ls -aq | LC_ALL=C sort -u | wc -l | tr -d ' ')" = '1' ]
[ "$(docker ps -aq | wc -l | tr -d ' ')" = '0' ]
[ "$(docker volume ls -q | wc -l | tr -d ' ')" = '0' ]
[ "$(docker system df --format '{{.Type}}={{.TotalCount}}' | awk -F= '$1=="Build Cache" {print $2}')" = '0' ]
[ "$(database_connection_count)" = '0' ]

phase='credential_cleanup'
cleanup_sensitive_state
[ ! -e "$task_root" ] && [ ! -L "$task_root" ]
[ "$(docker_auth_entry_count)" = '0' ]
[ "$(docker ps -aq | wc -l | tr -d ' ')" = '0' ]
[ "$(database_connection_count)" = '0' ]
phase='imported_image_cleanup'
docker image rm "$digest_ref" >/dev/null
[ "$(docker image ls -aq | LC_ALL=C sort -u | wc -l | tr -d ' ')" = '0' ]
[ "$(docker system df --format '{{.Type}}={{.TotalCount}}' | awk -F= '$1=="Build Cache" {print $2}')" = '0' ]
trap - EXIT
printf 'NOTEAI_DURABLE_AI_CAD5_FRESH_IMPORTER=PASS release=%s tag=%s pulls=1 retries=0 containers_started=0\n' \
  "$release" "$tag"
printf 'NOTEAI_DURABLE_AI_CAD5_FRESH_IMPORTER_DIGESTS manifest=%s config=%s repo_digest=%s\n' \
  "$manifest_digest" "$actual_config_digest" "$digest_ref"
printf 'NOTEAI_DURABLE_AI_CAD5_FRESH_IMPORTER_CLEANUP docker_auth_entries=0 task_root=absent containers=0 database_connections=0 images=0 build_cache=0\n'
