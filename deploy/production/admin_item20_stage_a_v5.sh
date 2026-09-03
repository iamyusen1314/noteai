#!/bin/bash
set -Eeuo pipefail
umask 077
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset \
  GIT_ALTERNATE_OBJECT_DIRECTORIES \
  GIT_CEILING_DIRECTORIES \
  GIT_COMMON_DIR \
  GIT_CONFIG \
  GIT_CONFIG_COUNT \
  GIT_CONFIG_PARAMETERS \
  GIT_CONFIG_SYSTEM \
  GIT_CONFIG_GLOBAL \
  GIT_DIR \
  GIT_DISCOVERY_ACROSS_FILESYSTEM \
  GIT_EXEC_PATH \
  GIT_INDEX_FILE \
  GIT_NAMESPACE \
  GIT_OBJECT_DIRECTORY \
  GIT_REPLACE_REF_BASE \
  GIT_SHALLOW_FILE \
  GIT_TEMPLATE_DIR \
  GIT_WORK_TREE
export \
  GIT_ATTR_NOSYSTEM=1 \
  GIT_CONFIG_NOSYSTEM=1 \
  GIT_CONFIG_GLOBAL=/dev/null \
  GIT_LFS_SKIP_SMUDGE=1 \
  GIT_NO_LAZY_FETCH=1 \
  GIT_NO_REPLACE_OBJECTS=1 \
  GIT_TERMINAL_PROMPT=0

release='5335bdaed933b1f999b5f819c047ec50c11821ae'
release_tree='38e574e56406ba3380acb78edbe784508cc537cd'
prior_release='b55f11882100e9ef919522540729e366a511f88f'
prior_tree='ad3c949ae585ed529854d47a8599b7cb36a25ab2'
release_parent='216be18bab10e5e0358e1f61e3f6b70bd207a8a8'
release_created='2026-07-30T13:29:02Z'
release_version='git-5335bda-amd64-r1'
oci_source='https://github.com/iamyusen1314/noteai'
task_root='/var/lib/noteai/admin-5335-current-v5'
source_root="$task_root/source"
evidence_root="$task_root/evidence"
source_repository='/var/lib/noteai/b55-release-build/src'
canonical_image='noteai-native-evidence:5335bda-admin'
local_image='noteai-local:git-5335bda-amd64-admin-r1'
inspect_container='noteai-admin-item20-inspect-v5'
phase='preflight'
source_bundle_size='159507'
source_bundle_sha256='4e62b0627b4be73d7ccc14d821d34f01894340297729456f9f3e22b45a6e75b3'
source_delta_commit_count='11'

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

verify_model_artifacts() {
  local repo_root="$1"
  local manifest="$repo_root/model/artifacts/model_release_manifest.v04.json"
  local manifest_sha
  local relative_path
  local expected_sha
  local actual_sha
  local artifact_count=0

  [ -f "$manifest" ] && [ ! -L "$manifest" ] || return 1
  manifest_sha="$(sha256sum "$manifest" | awk '{print $1}')"
  [ "$manifest_sha" = '5ad98842a042d86282844e7009825554aa0da318f2bc0556590258dfcea8ad63' ] || return 1

  while IFS=$'\t' read -r relative_path expected_sha; do
    case "$relative_path" in
      model/*) ;;
      *) return 1 ;;
    esac
    case "/$relative_path/" in
      */../*|*/./*) return 1 ;;
    esac
    [[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]] || return 1
    [ -f "$repo_root/$relative_path" ] && [ ! -L "$repo_root/$relative_path" ] || return 1
    actual_sha="$(sha256sum "$repo_root/$relative_path" | awk '{print $1}')"
    [ "$actual_sha" = "$expected_sha" ] || return 1
    artifact_count=$((artifact_count + 1))
  done < <(
    jq -er '
      .artifacts[] |
      select((.path | type) == "string" and (.sha256 | type) == "string") |
      [.path, .sha256] | @tsv
    ' "$manifest"
  )
  [ "$artifact_count" = '4' ] || return 1
}

project_admin_role() {
  local script_path="$1"
  local projected_path="${script_path}.admin.tmp"
  local source_line='roles=(api admin payment ai-worker xhs-http)'

  [ -f "$script_path" ] && [ ! -L "$script_path" ] && [ ! -e "$projected_path" ] || return 1
  [ "$(grep -Fxc "$source_line" "$script_path")" = '1' ] || return 1
  sed 's/^roles=(api admin payment ai-worker xhs-http)$/roles=(admin)/' \
    "$script_path" > "$projected_path" || return 1
  [ "$(grep -Fxc 'roles=(admin)' "$projected_path")" = '1' ] || return 1
  mv "$projected_path" "$script_path"
}

verify_trivy_metadata() {
  local metadata_path="$1"
  local now_epoch="${2:-$(date -u +%s)}"

  case "$now_epoch" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ -f "$metadata_path" ] && [ ! -L "$metadata_path" ] || return 1
  jq -e --argjson now "$now_epoch" '
    def trivy_epoch:
      if type != "string" then
        error("Trivy timestamp must be a string")
      else
        sub("\\+00:00$"; "Z") |
        sub("\\.[0-9]+Z$"; "Z") |
        fromdateiso8601
      end;
    (.UpdatedAt | trivy_epoch) as $updated |
    (.DownloadedAt | trivy_epoch) as $downloaded |
    (.NextUpdate | trivy_epoch) as $next_update |
    (($now - $updated) >= 0 and ($now - $updated) < 86400) and
    (($now - $downloaded) >= 0 and ($now - $downloaded) < 86400) and
    ($next_update > $now)
  ' "$metadata_path" >/dev/null
}

verify_source_repository() {
  local repo_root="$1"
  local git_bin
  local git_dir

  [ -d "$repo_root" ] && [ ! -L "$repo_root" ] || return 1
  [ "$(readlink -f "$repo_root")" = "$repo_root" ] || return 1
  git_bin="$(command -v git)"
  [ -x "$git_bin" ] || return 1
  git_dir="$("$git_bin" -C "$repo_root" rev-parse --absolute-git-dir)"
  [ "$git_dir" = "$repo_root/.git" ] || return 1
  [ -d "$git_dir" ] && [ ! -L "$git_dir" ] || return 1
  [ "$(readlink -f "$git_dir")" = "$git_dir" ] || return 1
  [ ! -e "$git_dir/info/grafts" ]
  [ ! -e "$git_dir/shallow" ]
  [ ! -e "$git_dir/objects/info/alternates" ]
  [ ! -e "$git_dir/objects/info/http-alternates" ]
  [ -z "$("$git_bin" -C "$repo_root" for-each-ref \
    --format='%(refname)' refs/replace)" ]

  [ "$(
    env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 \
      "$git_bin" -C "$repo_root" rev-parse --verify "${prior_release}^{commit}"
  )" = "$prior_release" ] || return 1
  [ "$(
    env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 \
      "$git_bin" -C "$repo_root" rev-parse "${prior_release}^{tree}"
  )" = "$prior_tree" ] || return 1

  if "$git_bin" -C "$repo_root" config --local --get-regexp \
    '^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter)|uploadpack\.packobjectshook|core\.alternaterefscommand)$' \
    >/dev/null 2>&1; then
    return 1
  fi
  env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 \
    "$git_bin" -C "$repo_root" fsck --strict --full \
      --no-dangling >/dev/null
}

prepare_source_from_bundle() {
  local repo_root="$1"
  local destination="$2"
  local bundle_path="$3"
  local expected_bundle_size="$4"
  local expected_bundle_sha256="$5"
  local git_bin
  local template_dir="${destination}.git-template"

  [ ! -e "$destination" ] && [ ! -L "$destination" ] || return 1
  [ -f "$bundle_path" ] && [ ! -L "$bundle_path" ] || return 1
  [ "$(wc -c < "$bundle_path" | tr -d ' ')" = \
    "$expected_bundle_size" ] || return 1
  [ "$(sha256sum "$bundle_path" | awk '{print $1}')" = \
    "$expected_bundle_sha256" ] || return 1
  verify_source_repository "$repo_root" || return 1

  git_bin="$(command -v git)"
  [ "$(
    env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
      "$git_bin" bundle list-heads "$bundle_path"
  )" = "$release refs/heads/release" ] || return 1

  [ ! -e "$template_dir" ] && [ ! -L "$template_dir" ]
  install -d -m 0700 "$template_dir"
  "$git_bin" init -q --template="$template_dir" "$destination"
  rm -rf -- "$template_dir"
  env \
    GIT_ALLOW_PROTOCOL=file \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_NO_LAZY_FETCH=1 \
    GIT_TERMINAL_PROMPT=0 \
    GIT_LFS_SKIP_SMUDGE=1 \
    "$git_bin" -c protocol.file.allow=always -C "$destination" \
      fetch --quiet --no-tags "$repo_root" "$prior_release"
  [ "$("$git_bin" -C "$destination" rev-parse FETCH_HEAD)" = "$prior_release" ]
  env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 \
    "$git_bin" -C "$destination" bundle verify "$bundle_path" \
      >/dev/null 2>&1

  env \
    GIT_ALLOW_PROTOCOL=file \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_NO_LAZY_FETCH=1 \
    GIT_TERMINAL_PROMPT=0 \
    GIT_LFS_SKIP_SMUDGE=1 \
    "$git_bin" -c protocol.file.allow=always -C "$destination" \
      fetch --quiet --no-tags "$bundle_path" refs/heads/release
  env \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_NO_LAZY_FETCH=1 \
    GIT_LFS_SKIP_SMUDGE=1 \
    "$git_bin" \
      -c filter.lfs.process= \
      -c filter.lfs.smudge= \
      -c filter.lfs.required=false \
      -C "$destination" checkout -q --detach FETCH_HEAD

  [ "$("$git_bin" -C "$destination" rev-parse HEAD)" = "$release" ]
  [ "$("$git_bin" -C "$destination" rev-parse 'HEAD^{tree}')" = "$release_tree" ]
  [ "$("$git_bin" -C "$destination" rev-parse 'HEAD^')" = "$release_parent" ]
  "$git_bin" -C "$destination" merge-base --is-ancestor "$prior_release" HEAD
  [ "$("$git_bin" -C "$destination" rev-list --count "$prior_release..HEAD")" = \
    "$source_delta_commit_count" ]
  [ "$("$git_bin" -C "$destination" rev-list --count HEAD)" = '197' ]
  [ "$("$git_bin" -C "$destination" show -s --format=%cI HEAD)" = \
    '2026-07-30T21:29:02+08:00' ]
  [ -z "$("$git_bin" -C "$destination" status --porcelain=v1 --untracked-files=all)" ]
  [ -z "$("$git_bin" -C "$destination" remote)" ]
  [ ! -L "$destination/.git" ]
  env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 \
    "$git_bin" -C "$destination" fsck --strict --full --no-dangling >/dev/null
}

offline_self_test() (
  set -euo pipefail
  local repo_root="$1"
  local fixture_root
  local maker_repo
  local second_maker_repo
  local fixture_bundle
  local fixture_bundle_size
  local fixture_bundle_sha256
  local projected_source
  fixture_root="$(mktemp -d "${TMPDIR:-/tmp}/noteai-admin-stage-a-v5.XXXXXX")"
  case "$fixture_root" in
    "${TMPDIR:-/tmp}"/noteai-admin-stage-a-v5.*) ;;
    *) exit 95 ;;
  esac
  trap 'rm -rf -- "$fixture_root"' EXIT

  [ "$(docker_auth_entry_count "$fixture_root/missing-docker-config.json")" = '0' ]
  printf '{"auths":{},"credHelpers":{},"credsStore":""}\n' \
    > "$fixture_root/empty-docker-config.json"
  [ "$(docker_auth_entry_count "$fixture_root/empty-docker-config.json")" = '0' ]
  printf '{"auths":{"registry.invalid":{}},"credHelpers":{"helper.invalid":"x"},"credsStore":"store"}\n' \
    > "$fixture_root/nonempty-docker-config.json"
  [ "$(docker_auth_entry_count "$fixture_root/nonempty-docker-config.json")" = '3' ]
  printf '[]\n' > "$fixture_root/invalid-docker-config.json"
  if docker_auth_entry_count "$fixture_root/invalid-docker-config.json" \
    >/dev/null 2>&1; then
    exit 1
  fi

  maker_repo="$fixture_root/maker.git"
  second_maker_repo="$fixture_root/second-maker.git"
  fixture_bundle="$fixture_root/incremental.bundle"
  git clone -q --bare --shared "$repo_root" "$maker_repo"
  git clone -q --bare --shared "$repo_root" "$second_maker_repo"
  git -C "$maker_repo" update-ref refs/heads/prior "$prior_release"
  git -C "$maker_repo" update-ref refs/heads/release "$release"
  git -C "$second_maker_repo" update-ref refs/heads/prior "$prior_release"
  git -C "$second_maker_repo" update-ref refs/heads/release "$release"
  git -C "$maker_repo" bundle create "$fixture_bundle" \
    ^refs/heads/prior refs/heads/release
  git -C "$second_maker_repo" bundle create "$fixture_root/incremental-second.bundle" \
    ^refs/heads/prior refs/heads/release
  cmp "$fixture_bundle" "$fixture_root/incremental-second.bundle"
  fixture_bundle_size="$(wc -c < "$fixture_bundle" | tr -d ' ')"
  fixture_bundle_sha256="$(sha256sum "$fixture_bundle" | awk '{print $1}')"

  projected_source="$fixture_root/projected-source"
  prepare_source_from_bundle \
    "$repo_root" "$projected_source" "$fixture_bundle" \
    "$fixture_bundle_size" "$fixture_bundle_sha256"
  [ "$(git -C "$projected_source" rev-parse HEAD)" = "$release" ]
  [ "$(git -C "$projected_source" rev-parse 'HEAD^{tree}')" = "$release_tree" ]
  [ -z "$(git -C "$projected_source" status --porcelain=v1 --untracked-files=all)" ]

  cp "$fixture_bundle" "$fixture_root/tampered.bundle"
  printf 'x' >> "$fixture_root/tampered.bundle"
  if prepare_source_from_bundle \
    "$repo_root" "$fixture_root/tampered-source" \
    "$fixture_root/tampered.bundle" \
    "$fixture_bundle_size" "$fixture_bundle_sha256" >/dev/null 2>&1; then
    exit 1
  fi
  [ ! -e "$fixture_root/tampered-source" ]

  while IFS='|' read -r sha size rel; do
    [ "$(wc -c < "$repo_root/$rel" | tr -d ' ')" = "$size" ]
    [ "$(sha256sum "$repo_root/$rel" | awk '{print $1}')" = "$sha" ]
    install -m 0644 "$repo_root/$rel" "$projected_source/$rel"
  done <<'MODELS'
c708c76eef9e017e73bcb63794592baed100d2af73cc53dedbb471cb792cbde4|466815|model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb
5d6e5d5bab5bee321c486d96bb8670605138444ca56cd2589cbbd57c14d80f10|444681|model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb
1f3d0b12a6b32d89044480ab5f3add47076f6148d00ea87135fee2d5bfb7bb7b|454076|model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb
MODELS
  verify_model_artifacts "$projected_source"

  cp "$repo_root/scripts/ci/native_release_evidence.sh" \
    "$fixture_root/admin-native-release.sh"
  [ "$(sha256sum "$fixture_root/admin-native-release.sh" | awk '{print $1}')" = \
    '639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2' ]
  project_admin_role "$fixture_root/admin-native-release.sh"
  [ "$(sha256sum "$fixture_root/admin-native-release.sh" | awk '{print $1}')" = \
    'a2420972f187f461d283964e71cb5b5d4980f8e5251faf0489993ac7ca6df22c' ]
  printf 'roles=(api admin payment ai-worker xhs-http)\nroles=(api admin payment ai-worker xhs-http)\n' \
    > "$fixture_root/duplicate-roles.sh"
  if project_admin_role "$fixture_root/duplicate-roles.sh" >/dev/null 2>&1; then
    exit 1
  fi

  cat > "$fixture_root/trivy-metadata.json" <<'TRIVY_METADATA'
{"UpdatedAt":"2026-08-03T06:00:00.123456789Z","DownloadedAt":"2026-08-03T11:00:00+00:00","NextUpdate":"2026-08-03T18:00:00Z"}
TRIVY_METADATA
  fixture_now_epoch="$(
    jq -nr '"2026-08-03T12:00:00Z" | fromdateiso8601'
  )"
  verify_trivy_metadata "$fixture_root/trivy-metadata.json" "$fixture_now_epoch"
  cat > "$fixture_root/stale-trivy-metadata.json" <<'STALE_TRIVY_METADATA'
{"UpdatedAt":"2026-08-01T06:00:00Z","DownloadedAt":"2026-08-03T11:00:00Z","NextUpdate":"2026-08-03T18:00:00Z"}
STALE_TRIVY_METADATA
  if verify_trivy_metadata \
    "$fixture_root/stale-trivy-metadata.json" "$fixture_now_epoch" \
    >/dev/null 2>&1; then
    exit 1
  fi

  printf 'NOTEAI_ADMIN_STAGE_A_OFFLINE_SELF_TEST=PASS\n'
)
if [ "${1:-}" = '--offline-self-test' ]; then
  [ "$#" = '2' ]
  offline_self_test "$2"
  exit
fi

[ "$#" = '1' ] || {
  echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=source_bundle_argument'
  exit 90
}
source_bundle_path="$1"
case "$source_bundle_path" in
  /root/noteai-admin-stage-a-v5-transfer/source.bundle) ;;
  *) echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=unsafe_source_bundle_path'; exit 90 ;;
esac
[ "$(readlink -f "$(dirname "$source_bundle_path")")" = \
  '/root/noteai-admin-stage-a-v5-transfer' ] || {
  echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=unsafe_source_bundle_parent'
  exit 90
}
[ "$(stat -c '%u:%g:%a' "$(dirname "$source_bundle_path")")" = '0:0:700' ] || {
  echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=unsafe_source_bundle_parent_mode'
  exit 90
}
[ "$(stat -c '%u:%g:%a' "$source_bundle_path")" = '0:0:600' ] || {
  echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=unsafe_source_bundle_mode'
  exit 90
}
[ "$(stat -c '%u:%g' "$source_repository" "$source_repository/.git" | \
  LC_ALL=C sort -u)" = '0:0' ] || {
  echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=unsafe_source_repository_owner'
  exit 90
}
[ -z "$(find "$source_repository" "$source_repository/.git" \
  -maxdepth 0 -perm /022 -print)" ] || {
  echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=unsafe_source_repository_mode'
  exit 90
}

case "$task_root" in
  /var/lib/noteai/admin-5335-current-v5) ;;
  *) echo 'NOTEAI_ADMIN_STAGE_A=FAIL phase=unsafe_task_root'; exit 90 ;;
esac

cleanup_failure() {
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then
    printf 'NOTEAI_ADMIN_STAGE_A=FAIL phase=%s exit=%s\n' "$phase" "$rc"
    for log in "$task_root/scanner-db.log" "$task_root/build-scan.log"; do
      if [ -f "$log" ]; then
        printf 'NOTEAI_FAILURE_LOG path=%s\n' "$log"
        tail -n 80 "$log" || true
      fi
    done
    docker rm -f "$inspect_container" noteai-native-evidence-local-admin >/dev/null 2>&1 || true
    docker image rm "$local_image" "$canonical_image" >/dev/null 2>&1 || true
    if [ -e "$task_root" ]; then
      rm -rf -- "$task_root"
    fi
    printf 'NOTEAI_ADMIN_STAGE_A_CLEANUP target_images=%s task_root=%s running=%s\n'       "$(docker image inspect "$local_image" "$canonical_image" >/dev/null 2>&1 && echo present || echo absent)"       "$([ -e "$task_root" ] && echo present || echo absent)"       "$(docker ps -q | wc -l | tr -d ' ')"
    exit "$rc"
  fi
}
trap cleanup_failure EXIT

[ "$(id -u)" = '0' ]
[ "$(uname -m)" = 'x86_64' ]
[ "$(systemctl is-active docker)" = 'active' ]
[ "$(docker ps -q | wc -l | tr -d ' ')" = '0' ]
[ ! -e "$task_root" ]
! docker image inspect "$local_image" >/dev/null 2>&1
! docker image inspect "$canonical_image" >/dev/null 2>&1
[ "$(docker_auth_entry_count)" = '0' ]
[ "$(ps -eo args= | awk '/docker.* (build|push)( |$)/ || /buildx.* (build|create)( |$)/ || /buildkitd( |$)/ {n++} END{print n+0}')" = '0' ]
[ "$(df -Pm /var/lib/docker | awk 'NR==2{print $4}')" -ge 20480 ]
[ "$(awk '/MemAvailable:/{print int($2/1024)}' /proc/meminfo)" -ge 8192 ]
[ "$(jq -nr '"1970-01-01T00:00:00Z" | fromdateiso8601')" = '0' ]
real_git="$(command -v git)"
[ -x "$real_git" ]

install -d -o root -g root -m 0700 "$task_root"

phase='source_bundle_import'
prepare_source_from_bundle \
  "$source_repository" "$source_root" "$source_bundle_path" \
  "$source_bundle_size" "$source_bundle_sha256"
[ "$(stat -c '%u:%g:%a' "$source_root")" = '0:0:700' ]
[ "$(git -C "$source_root" rev-parse HEAD)" = "$release" ]
[ "$(git -C "$source_root" rev-parse 'HEAD^{tree}')" = "$release_tree" ]
[ "$(git -C "$source_root" show -s --format=%cI HEAD)" = '2026-07-30T21:29:02+08:00' ]

phase='model_materialization'
model_source="$source_repository"
while IFS='|' read -r sha size rel; do
  src="$model_source/$rel"
  dst="$source_root/$rel"
  [ -f "$src" ] && [ ! -L "$src" ]
  [ "$(stat -c '%s' "$src")" = "$size" ]
  [ "$(sha256sum "$src" | awk '{print $1}')" = "$sha" ]
  install -o root -g root -m 0644 "$src" "$dst"
done <<'MODELS'
c708c76eef9e017e73bcb63794592baed100d2af73cc53dedbb471cb792cbde4|466815|model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb
5d6e5d5bab5bee321c486d96bb8670605138444ca56cd2589cbbd57c14d80f10|444681|model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb
1f3d0b12a6b32d89044480ab5f3add47076f6148d00ea87135fee2d5bfb7bb7b|454076|model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb
MODELS

git -C "$source_root" status --porcelain=v1 --untracked-files=no |
  awk '{print $2}' | LC_ALL=C sort > "$task_root/materialized-paths.txt"
cat > "$task_root/expected-materialized-paths.txt" <<'PATHS'
model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb
model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb
model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb
PATHS
cmp "$task_root/expected-materialized-paths.txt" "$task_root/materialized-paths.txt"
[ -z "$(git -C "$source_root" diff --cached --name-only)" ]
[ -z "$(git -C "$source_root" ls-files --others --exclude-standard)" ]
verify_model_artifacts "$source_root"
[ "$(sha256sum "$source_root/Dockerfile" | awk '{print $1}')" = 'ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447' ]
[ "$(sha256sum "$source_root/model/requirements-api.txt" | awk '{print $1}')" = '0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9' ]
[ "$(sha256sum "$source_root/scripts/docker_entrypoint.sh" | awk '{print $1}')" = '77375834edc74d5d5a370de9ba106d77036a9aa1cf372b7d289083a822e20cfb' ]
jq -e '. == {"enabled":false,"cookie_valid":false,"last_run":null,"total_collected":0,"daily_limit":300,"schedule_hour":3}'   "$source_root/model/crawler_config.json" >/dev/null

phase='tool_prep'
real_docker="$(command -v docker)"
[ -x "$real_docker" ]
install -d -o root -g root -m 0700   "$task_root/bin" "$task_root/tools" "$task_root/base-index"   "$task_root/docker-empty" "$task_root/trivy-cache"
printf '{}\n' > "$task_root/docker-empty/config.json"
chmod 0600 "$task_root/docker-empty/config.json"
install -o root -g root -m 0500 /var/lib/noteai/b55-release-build/tools/syft "$task_root/bin/syft"
install -o root -g root -m 0500 /var/lib/noteai/b55-release-build9/tools/trivy "$task_root/tools/trivy-real"
[ "$(sha256sum "$task_root/bin/syft" | awk '{print $1}')" = '6368bf376b578991192e2e94f5e276e6c70d313d6368ad8c249866f020a86cb0' ]
[ "$(sha256sum "$task_root/tools/trivy-real" | awk '{print $1}')" = '0e69edd134a3c338baa1a6806920773615d682b18cbc6a0cba2a3b658ef9b63e' ]
install -o root -g root -m 0600   /var/lib/noteai/admin-5335-publication-v1/failed-attempt2/evidence/python-base-index.json   "$task_root/base-index/python-base-index.json"
install -o root -g root -m 0600   /var/lib/noteai/admin-5335-publication-v1/failed-attempt2/evidence/node-base-index.json   "$task_root/base-index/node-base-index.json"
[ "$(sha256sum "$task_root/base-index/python-base-index.json" | awk '{print $1}')" = '2cbba3aeca891b77c06479ae266614557b6bfef925df37472d4c690b878c587d' ]
[ "$(sha256sum "$task_root/base-index/node-base-index.json" | awk '{print $1}')" = '8fc034c9f2bbccb406ceaef6802be9a8921c17bc2109feccfcc33b901a56c8bc' ]
jq -e '.manifests[] | select(.platform.os=="linux" and .platform.architecture=="amd64") | .digest=="sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045"'   "$task_root/base-index/python-base-index.json" >/dev/null
jq -e '.manifests[] | select(.platform.os=="linux" and .platform.architecture=="amd64") | .digest=="sha256:3d0f05455dea2c82e2f76e7e2543964c30f6b7d673fc1a83286736d44fe4c41c"'   "$task_root/base-index/node-base-index.json" >/dev/null

cat > "$task_root/bin/docker" <<'DOCKER_WRAPPER'
#!/bin/bash
set -euo pipefail
if [ "$#" -eq 5 ] && [ "$1" = 'buildx' ] && [ "$2" = 'imagetools' ] && [ "$3" = 'inspect' ] && [ "$5" = '--raw' ]; then
  case "$4" in
    python:3.11.15-slim-trixie@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93)
      exec cat "$NOTEAI_PYTHON_INDEX_FILE"
      ;;
    node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0)
      exec cat "$NOTEAI_NODE_INDEX_FILE"
      ;;
    *)
      echo 'unexpected imagetools target' >&2
      exit 64
      ;;
  esac
fi
exec "$NOTEAI_REAL_DOCKER" "$@"
DOCKER_WRAPPER
chmod 0500 "$task_root/bin/docker"

cat > "$task_root/bin/trivy" <<'TRIVY_WRAPPER'
#!/bin/bash
set -euo pipefail
[ "$#" -ge 1 ] && [ "$1" = 'image' ] || { echo 'unexpected trivy command' >&2; exit 64; }
shift
exec "$NOTEAI_TRIVY_REAL" image   --cache-dir "$NOTEAI_TRIVY_CACHE"   --skip-db-update --skip-java-db-update --offline-scan "$@"
TRIVY_WRAPPER
chmod 0500 "$task_root/bin/trivy"

cp "$source_root/scripts/ci/native_release_evidence.sh" "$task_root/admin-native-release.sh"
[ "$(sha256sum "$task_root/admin-native-release.sh" | awk '{print $1}')" = '639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2' ]
project_admin_role "$task_root/admin-native-release.sh"
chmod 0500 "$task_root/admin-native-release.sh"
[ "$(sha256sum "$task_root/admin-native-release.sh" | awk '{print $1}')" = 'a2420972f187f461d283964e71cb5b5d4980f8e5251faf0489993ac7ca6df22c' ]

phase='scanner_db_refresh'
"$task_root/tools/trivy-real" image --help > "$task_root/trivy-image-help.txt"
grep -F -- '--download-db-only' "$task_root/trivy-image-help.txt" >/dev/null
grep -F -- '--timeout' "$task_root/trivy-image-help.txt" >/dev/null
rm -f "$task_root/trivy-image-help.txt"
timeout --foreground --signal=TERM --kill-after=30s 1200s \
  env DOCKER_CONFIG="$task_root/docker-empty" \
  "$task_root/tools/trivy-real" image \
    --cache-dir "$task_root/trivy-cache" \
    --db-repository ghcr.io/aquasecurity/trivy-db:2 \
    --timeout 15m \
    --download-db-only \
    2>&1 | tee "$task_root/scanner-db.log"
verify_trivy_metadata "$task_root/trivy-cache/db/metadata.json"
trivy_db_sha="$(sha256sum "$task_root/trivy-cache/db/trivy.db" | awk '{print $1}')"
trivy_metadata_sha="$(sha256sum "$task_root/trivy-cache/db/metadata.json" | awk '{print $1}')"

phase='admin_build_scan'
(
  cd "$source_root"
  timeout --foreground --signal=TERM --kill-after=30s 3600s     env       PATH="$task_root/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"       DOCKER_CONFIG="$task_root/docker-empty"       NOTEAI_REAL_DOCKER="$real_docker"       NOTEAI_PYTHON_INDEX_FILE="$task_root/base-index/python-base-index.json"       NOTEAI_NODE_INDEX_FILE="$task_root/base-index/node-base-index.json"       NOTEAI_TRIVY_REAL="$task_root/tools/trivy-real"       NOTEAI_TRIVY_CACHE="$task_root/trivy-cache"       RELEASE_COMMIT="$release"       NOTEAI_OCI_SOURCE="$oci_source"       NOTEAI_OCI_VERSION="$release_version"       NOTEAI_OCI_CREATED="$release_created"       NOTEAI_EVIDENCE_DIR="$evidence_root"       bash "$task_root/admin-native-release.sh"
) >"$task_root/build-scan.log" 2>&1

phase='evidence_acceptance'
[ "$(find "$evidence_root" -maxdepth 1 -type f | wc -l | tr -d ' ')" = '11' ]
jq -e --arg release "$release" --arg created "$release_created" --arg version "$release_version" '
  .release_commit==$release and .created==$created and .version==$version and
  .runner_architecture=="x86_64" and (.roles|length)==1 and
  .roles[0].role=="admin" and .roles[0].target=="admin-runtime" and
  .roles[0].platform=="linux/amd64" and
  .roles[0].findings.critical==4 and .roles[0].findings.high==19 and
  .roles[0].findings.secrets==0 and
  .roles[0].findings.browser_components==0 and
  .roles[0].findings.cryptography_48_0_1_components==1 and
  .roles[0].findings.forbidden_os_packages==0 and
  .roles[0].passed==false and .passed==false
' "$evidence_root/summary.json" >/dev/null

jq -r '.Results[]?.Vulnerabilities[]? |
  [.VulnerabilityID,.PkgName,.InstalledVersion,(.FixedVersion // ""),.Severity] | @tsv'   "$evidence_root/admin-vuln-high-critical.json" | LC_ALL=C sort > "$task_root/actual-vulnerability-rows.tsv"
cat > "$task_root/expected-vulnerability-rows.tsv" <<'VULNS'
CVE-2025-69720	libncursesw6	6.5+20250216-2		HIGH
CVE-2025-69720	libtinfo6	6.5+20250216-2		HIGH
CVE-2025-69720	ncurses-base	6.5+20250216-2		HIGH
CVE-2025-69720	ncurses-bin	6.5+20250216-2		HIGH
CVE-2026-13221	perl-base	5.40.1-6		CRITICAL
CVE-2026-41992	gzip	1.13-1		HIGH
CVE-2026-42496	perl-base	5.40.1-6		CRITICAL
CVE-2026-42497	perl-base	5.40.1-6		HIGH
CVE-2026-48962	perl-base	5.40.1-6		HIGH
CVE-2026-53615	bsdutils	1:2.41-5		HIGH
CVE-2026-53615	libblkid1	2.41-5		HIGH
CVE-2026-53615	liblastlog2-2	2.41-5		HIGH
CVE-2026-53615	libmount1	2.41-5		HIGH
CVE-2026-53615	libsmartcols1	2.41-5		HIGH
CVE-2026-53615	libuuid1	2.41-5		HIGH
CVE-2026-53615	login	1:4.16.0-2+really2.41-5		HIGH
CVE-2026-53615	mount	2.41-5		HIGH
CVE-2026-53615	util-linux	2.41-5		HIGH
CVE-2026-54369	libacl1	2.3.2-2+b1		HIGH
CVE-2026-57432	perl-base	5.40.1-6		HIGH
CVE-2026-57433	perl-base	5.40.1-6		CRITICAL
CVE-2026-8376	perl-base	5.40.1-6		CRITICAL
CVE-2026-9538	perl-base	5.40.1-6		HIGH
VULNS
LC_ALL=C sort -o "$task_root/expected-vulnerability-rows.tsv" "$task_root/expected-vulnerability-rows.tsv"
cmp "$task_root/expected-vulnerability-rows.tsv" "$task_root/actual-vulnerability-rows.tsv"

image_id="$(docker image inspect "$canonical_image" --format '{{.Id}}')"
[ -n "$image_id" ]
[ "$(docker image inspect "$canonical_image" --format '{{.Architecture}}/{{.Os}}')" = 'amd64/linux' ]
[ "$(docker image inspect "$canonical_image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$release" ]
[ "$(docker image inspect "$canonical_image" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$release_version" ]
[ "$(docker image inspect "$canonical_image" --format '{{index .Config.Labels "com.noteai.runtime.role"}}')" = 'admin' ]
[ "$(docker image inspect "$canonical_image" --format '{{.Config.User}}')" = 'noteai' ]
[ "$(docker image inspect "$canonical_image" --format '{{json .Config.Entrypoint}}')" = '["/app/scripts/docker_entrypoint.sh"]' ]
[ "$(docker image inspect "$canonical_image" --format '{{json .Config.Cmd}}')" = '["/app/scripts/render_start_admin.sh"]' ]

docker create --name "$inspect_container" "$canonical_image" >/dev/null
docker cp "$inspect_container:/app/model/crawler_config.json" "$task_root/crawler-config-runtime.json"
docker cp "$inspect_container:/etc/noteai-runtime-role" "$task_root/runtime-role"
docker rm "$inspect_container" >/dev/null
[ "$(tr -d '\r\n' < "$task_root/runtime-role")" = 'admin' ]
jq -e '. == {"enabled":false,"cookie_valid":false,"last_run":null,"total_collected":0,"daily_limit":300,"schedule_hour":3}'   "$task_root/crawler-config-runtime.json" >/dev/null
rm -f "$task_root/crawler-config-runtime.json" "$task_root/runtime-role"

docker tag "$canonical_image" "$local_image"
[ "$(docker image inspect "$local_image" --format '{{.Id}}')" = "$image_id" ]
[ "$(docker ps -q | wc -l | tr -d ' ')" = '0' ]
[ "$(ps -eo args= | awk '/docker.* (build|push)( |$)/ || /buildx.* (build|create)( |$)/ || /buildkitd( |$)/ {n++} END{print n+0}')" = '0' ]
[ "$(ss -Htan state established 2>/dev/null | awk '$4 ~ /:5432$/ || $5 ~ /:5432$/ {n++} END{print n+0}')" = '0' ]
[ "$(docker_auth_entry_count)" = '0' ]

build_metadata_sha="$(sha256sum "$evidence_root/admin-build-metadata.json" | awk '{print $1}')"
inspect_sha="$(sha256sum "$evidence_root/admin-inspect.json" | awk '{print $1}')"
sbom_sha="$(sha256sum "$evidence_root/admin-sbom.cdx.json" | awk '{print $1}')"
vuln_sha="$(sha256sum "$evidence_root/admin-vuln-high-critical.json" | awk '{print $1}')"
secret_sha="$(sha256sum "$evidence_root/admin-secret.json" | awk '{print $1}')"
summary_sha="$(sha256sum "$evidence_root/summary.json" | awk '{print $1}')"

phase='success_cleanup'
rm -rf -- "$task_root/trivy-cache" "$task_root/bin" "$task_root/tools" "$task_root/base-index" "$task_root/docker-empty"
trap - EXIT
printf 'NOTEAI_ADMIN_STAGE_A=PASS invocation=5 release=%s tree=%s image_id=%s local_tag=%s evidence_files=11 vuln_rows=23 secrets=0 browser=0 source_bundle_sha256=%s trivy_db_sha256=%s trivy_metadata_sha256=%s\n'   "$release" "$release_tree" "$image_id" "$local_image" "$source_bundle_sha256" "$trivy_db_sha" "$trivy_metadata_sha"
printf 'NOTEAI_ADMIN_STAGE_A_HASHES build_metadata=%s inspect=%s sbom=%s vuln=%s secret=%s summary=%s\n'   "$build_metadata_sha" "$inspect_sha" "$sbom_sha" "$vuln_sha" "$secret_sha" "$summary_sha"
