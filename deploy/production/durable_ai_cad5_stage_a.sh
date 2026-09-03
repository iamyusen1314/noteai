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
  DOCKER_TLS_VERIFY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES \
  GIT_CEILING_DIRECTORIES \
  GIT_COMMON_DIR \
  GIT_CONFIG \
  GIT_CONFIG_COUNT \
  GIT_CONFIG_PARAMETERS \
  GIT_CONFIG_SYSTEM \
  GIT_DIR \
  GIT_DISCOVERY_ACROSS_FILESYSTEM \
  GIT_EXEC_PATH \
  GITHUB_RUN_ID \
  GIT_INDEX_FILE \
  GIT_NAMESPACE \
  GIT_OBJECT_DIRECTORY \
  GIT_REPLACE_REF_BASE \
  GIT_SHALLOW_FILE \
  GIT_TEMPLATE_DIR \
  GIT_WORK_TREE
export \
  DOCKER_CONTEXT=default \
  GIT_ATTR_NOSYSTEM=1 \
  GIT_CONFIG_NOSYSTEM=1 \
  GIT_CONFIG_GLOBAL=/dev/null \
  GIT_LFS_SKIP_SMUDGE=1 \
  GIT_NO_LAZY_FETCH=1 \
  GIT_NO_REPLACE_OBJECTS=1 \
  GIT_TERMINAL_PROMPT=0

release='cad5ce35664f617c6e19f90a6159285ddf975594'
release_tree='a1ce9c812a74a7e3824851581d1b4b6aaaaddb1c'
release_parent='cfc838b040e2582eca199f5c4d7dea94efa97f50'
prior_release='b55f11882100e9ef919522540729e366a511f88f'
prior_tree='ad3c949ae585ed529854d47a8599b7cb36a25ab2'
release_created='2026-08-05T14:30:09Z'
release_commit_time='2026-08-05T22:30:09+08:00'
release_version='git-cad5ce3-amd64-r1'
oci_source='https://github.com/iamyusen1314/noteai'
bundle_ref='refs/remotes/origin/codex/quality-stabilization-real-chain'
source_delta_commit_count='121'
source_total_commit_count='307'
source_bundle_size='1513408'
source_bundle_sha256='2a37c49c9284a3f354508601882ff4bbc07fc93aa754003aa7fe29fc307bd19b'
source_repository='/var/lib/noteai/b55-release-build/src'
transfer_root='/root/noteai-durable-ai-cad5-transfer'
source_bundle_path="${transfer_root}/source.bundle"
wheelhouse_archive_path="${transfer_root}/wheelhouse.tar"
scanner_archive_path="${transfer_root}/scanner-bundle.tar"
task_root='/var/lib/noteai/durable-ai-cad5-stage-a'
source_root="${task_root}/source"
evidence_root="${task_root}/evidence"
canonical_image='noteai-native-evidence:cad5ce3-ai-worker'
local_image='noteai-local:git-cad5ce3-amd64-ai-worker-r1'
inspect_container='noteai-durable-ai-cad5-inspect'
projected_runner_sha256='f6793eaeeef666511d910335f0257bad644abad13c57decfd69d36cbc7d636a8'
registry_host='noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com'
repository='noteai/app'
tag='git-cad5ce3-amd64-ai-worker-r1'
remote_image="${registry_host}/${repository}:${tag}"

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

verify_model_artifacts() {
  local repo_root="$1"
  local manifest="${repo_root}/model/artifacts/model_release_manifest.v04.json"
  local relative_name expected_sha actual_sha artifact_count=0

  [ -f "$manifest" ] && [ ! -L "$manifest" ]
  [ "$(sha256sum "$manifest" | awk '{print $1}')" = \
    '5ad98842a042d86282844e7009825554aa0da318f2bc0556590258dfcea8ad63' ]
  while IFS=$'\t' read -r relative_name expected_sha; do
    case "$relative_name" in model/*) ;; *) return 1 ;; esac
    case "/$relative_name/" in */../*|*/./*) return 1 ;; esac
    [[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]]
    [ -f "${repo_root}/${relative_name}" ] && [ ! -L "${repo_root}/${relative_name}" ]
    actual_sha="$(sha256sum "${repo_root}/${relative_name}" | awk '{print $1}')"
    [ "$actual_sha" = "$expected_sha" ]
    artifact_count=$((artifact_count + 1))
  done < <(jq -er '.artifacts[] | [.path, .sha256] | @tsv' "$manifest")
  [ "$artifact_count" = '4' ]
}

verify_source_repository() {
  local repo_root="$1"
  local git_bin git_dir

  [ -d "$repo_root" ] && [ ! -L "$repo_root" ]
  [ "$(readlink -f "$repo_root")" = "$repo_root" ]
  git_bin="$(command -v git)"
  git_dir="$("$git_bin" -C "$repo_root" rev-parse --absolute-git-dir)"
  [ "$git_dir" = "$repo_root/.git" ]
  [ -d "$git_dir" ] && [ ! -L "$git_dir" ]
  [ ! -e "$git_dir/info/grafts" ]
  [ ! -e "$git_dir/shallow" ]
  [ ! -e "$git_dir/objects/info/alternates" ]
  [ ! -e "$git_dir/objects/info/http-alternates" ]
  [ -z "$("$git_bin" -C "$repo_root" for-each-ref --format='%(refname)' refs/replace)" ]
  [ "$("$git_bin" -C "$repo_root" rev-parse --verify "${prior_release}^{commit}")" = \
    "$prior_release" ]
  [ "$("$git_bin" -C "$repo_root" rev-parse "${prior_release}^{tree}")" = \
    "$prior_tree" ]
  "$git_bin" -C "$repo_root" merge-base --is-ancestor \
    '5afc1717f09618de7ed7a191133a087d83317e39' "$prior_release"
  if "$git_bin" -C "$repo_root" config --local --get-regexp \
    '^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter)|uploadpack\.packobjectshook|core\.alternaterefscommand)$' \
    >/dev/null 2>&1; then
    return 1
  fi
  "$git_bin" -C "$repo_root" fsck --strict --full --no-dangling >/dev/null
}

prepare_source_from_bundle() {
  local destination="$1"
  local git_bin template_dir="${destination}.git-template"

  [ ! -e "$destination" ] && [ ! -L "$destination" ]
  verify_source_repository "$source_repository"
  [ "$(wc -c < "$source_bundle_path" | tr -d ' ')" = "$source_bundle_size" ]
  [ "$(sha256sum "$source_bundle_path" | awk '{print $1}')" = "$source_bundle_sha256" ]
  git_bin="$(command -v git)"
  [ "$("$git_bin" bundle list-heads "$source_bundle_path")" = \
    "$release $bundle_ref" ]

  install -d -m 0700 "$template_dir"
  "$git_bin" init -q --template="$template_dir" "$destination"
  rm -rf -- "$template_dir"
  env GIT_ALLOW_PROTOCOL=file \
    "$git_bin" -c protocol.file.allow=always -C "$destination" \
      fetch --quiet --no-tags "$source_repository" "$prior_release"
  [ "$("$git_bin" -C "$destination" rev-parse FETCH_HEAD)" = "$prior_release" ]
  "$git_bin" -C "$destination" bundle verify "$source_bundle_path" >/dev/null 2>&1
  env GIT_ALLOW_PROTOCOL=file \
    "$git_bin" -c protocol.file.allow=always -C "$destination" \
      fetch --quiet --no-tags "$source_bundle_path" "$bundle_ref"
  "$git_bin" -c filter.lfs.process= -c filter.lfs.smudge= \
    -c filter.lfs.required=false -C "$destination" checkout -q --detach FETCH_HEAD

  [ "$("$git_bin" -C "$destination" rev-parse HEAD)" = "$release" ]
  [ "$("$git_bin" -C "$destination" rev-parse 'HEAD^{tree}')" = "$release_tree" ]
  [ "$("$git_bin" -C "$destination" rev-parse 'HEAD^')" = "$release_parent" ]
  "$git_bin" -C "$destination" merge-base --is-ancestor "$prior_release" HEAD
  [ "$("$git_bin" -C "$destination" rev-list --count "$prior_release..HEAD")" = \
    "$source_delta_commit_count" ]
  [ "$("$git_bin" -C "$destination" rev-list --count HEAD)" = \
    "$source_total_commit_count" ]
  [ "$("$git_bin" -C "$destination" show -s --format=%cI HEAD)" = \
    "$release_commit_time" ]
  [ -z "$("$git_bin" -C "$destination" status --porcelain=v1 --untracked-files=all)" ]
  [ -z "$("$git_bin" -C "$destination" remote)" ]
  "$git_bin" -C "$destination" fsck --strict --full --no-dangling >/dev/null
}

verify_archive_members() {
  local archive="$1" prefix="$2"
  local member member_count expanded_size

  [ -f "$archive" ] && [ ! -L "$archive" ]
  [ "$(stat -c '%s' "$archive")" -le 1073741824 ]
  [ -n "$(tar -tf "$archive")" ]
  member_count="$(tar -tf "$archive" | wc -l | tr -d ' ')"
  [ "$member_count" -ge 1 ] && [ "$member_count" -le 512 ]
  [ -z "$(tar -tf "$archive" | LC_ALL=C sort | uniq -d | head -n 1)" ]
  expanded_size="$(tar -tvf "$archive" | awk 'substr($1,1,1)=="-" {sum += $3} END {printf "%.0f", sum}')"
  [ "$expanded_size" -le 2147483648 ]
  while IFS= read -r member; do
    [ -n "$member" ]
    case "$member" in
      /*|*'../'*|../*|*'/..'|.|..) return 1 ;;
      "$prefix"|"$prefix"/*|"._$prefix") ;;
      *) return 1 ;;
    esac
  done < <(tar -tf "$archive")
  [ -z "$(tar -tvf "$archive" | awk 'substr($1,1,1) != "-" && substr($1,1,1) != "d" {print; exit}')" ]
}

verify_embedded_manifest() {
  local root="$1"
  local listed actual

  [ -f "$root/SHA256SUMS" ] && [ ! -L "$root/SHA256SUMS" ]
  [ -z "$(awk '!/^[0-9a-f]{64}  [A-Za-z0-9][A-Za-z0-9._+\/~\/-]*$/ {print; exit}' \
    "$root/SHA256SUMS")" ]
  [ -z "$(awk '{name=substr($0,67); if (name ~ /(^|\/)\.\.($|\/)/ || name == "SHA256SUMS") print name}' \
    "$root/SHA256SUMS")" ]
  listed="$(awk '{print substr($0,67)}' "$root/SHA256SUMS" | LC_ALL=C sort)"
  actual="$(find "$root" -type f ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort)"
  [ -n "$listed" ] && [ "$listed" = "$actual" ]
  (cd "$root" && sha256sum -c SHA256SUMS >/dev/null)
}

extract_verified_archive() {
  local archive="$1" prefix="$2" destination="$3"
  verify_archive_members "$archive" "$prefix"
  install -d -m 0700 "$destination"
  tar --exclude='._*' --exclude='*/._*' -xf "$archive" \
    --no-same-owner --no-same-permissions -C "$destination"
  [ -d "$destination/$prefix" ] && [ ! -L "$destination/$prefix" ]
  [ -z "$(find "$destination/$prefix" \( -type l -o ! -type d -a ! -type f \) -print -quit)" ]
  chmod -R go-rwx "$destination/$prefix"
  verify_embedded_manifest "$destination/$prefix"
}

verify_trivy_metadata() {
  local metadata_path="$1" now_epoch="${2:-$(date -u +%s)}"
  case "$now_epoch" in ''|*[!0-9]*) return 1 ;; esac
  [ -f "$metadata_path" ] && [ ! -L "$metadata_path" ]
  jq -e --argjson now "$now_epoch" '
    def trivy_epoch:
      if type != "string" then error("Trivy timestamp must be a string")
      else sub("\\+00:00$"; "Z") | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601 end;
    (.UpdatedAt | trivy_epoch) as $updated |
    (.DownloadedAt | trivy_epoch) as $downloaded |
    (.NextUpdate | trivy_epoch) as $next_update |
    (($now - $updated) >= 0 and ($now - $updated) < 86400) and
    (($now - $downloaded) >= 0 and ($now - $downloaded) < 86400) and
    ($next_update > $now)
  ' "$metadata_path" >/dev/null
}

project_ai_worker_role() {
  local script_path="$1"
  local projected_path="${script_path}.tmp"
  local source_line='roles=(api admin payment ai-worker xhs-http)'
  [ -f "$script_path" ] && [ ! -L "$script_path" ] && [ ! -e "$projected_path" ]
  [ "$(grep -Fxc "$source_line" "$script_path")" = '1' ]
  sed 's/^roles=(api admin payment ai-worker xhs-http)$/roles=(ai-worker)/' \
    "$script_path" > "$projected_path"
  mv "$projected_path" "$script_path"
  [ "$(sha256sum "$script_path" | awk '{print $1}')" = "$projected_runner_sha256" ]
}

extract_push_digest() {
  local log_path="$1" match
  match="$(awk '{for (field=1; field<=NF; field++) if ($field=="digest:" && $(field+1) ~ /^sha256:[0-9a-f]{64}$/) print $(field+1)}' "$log_path")"
  [[ "$match" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$match"
}

extract_descriptor_digest() {
  local descriptor_path="$1" match
  match="$(awk '$1=="Digest:" && $2 ~ /^sha256:[0-9a-f]{64}$/ {print $2}' "$descriptor_path")"
  [[ "$match" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$match"
}

expected_evidence_files=(
  ai-worker-build-metadata.json
  ai-worker-history.jsonl
  ai-worker-inspect.json
  ai-worker-os-packages.txt
  ai-worker-sbom.cdx.json
  ai-worker-secret.json
  ai-worker-summary.json
  ai-worker-vuln-high-critical.json
  node-base-index.json
  python-base-index.json
  summary.json
)

normalize_stage_a_evidence_permissions() {
  local evidence_name evidence_path
  [ -d "$evidence_root" ] && [ ! -L "$evidence_root" ]
  for evidence_name in "${expected_evidence_files[@]}"; do
    evidence_path="${evidence_root}/${evidence_name}"
    [ -f "$evidence_path" ] && [ ! -L "$evidence_path" ]
    chmod 0600 -- "$evidence_path"
  done
}

verify_stage_a_evidence() {
  local image_id="$1" evidence_name evidence_path
  local actual_vulnerabilities expected_vulnerabilities
  local sbom_sha vuln_sha secret_sha
  [ -d "$evidence_root" ] && [ ! -L "$evidence_root" ]
  [ "$(find "$evidence_root" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')" = '11' ]
  [ -z "$(find "$evidence_root" -mindepth 1 -maxdepth 1 \( ! -type f -o -type l \) -print -quit)" ]
  [ "$(find "$evidence_root" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort)" = \
    "$(printf '%s\n' "${expected_evidence_files[@]}" | LC_ALL=C sort)" ]
  for evidence_name in "${expected_evidence_files[@]}"; do
    evidence_path="${evidence_root}/${evidence_name}"
    [ -f "$evidence_path" ] && [ ! -L "$evidence_path" ]
    [ "$(stat -c '%u:%g:%a' "$evidence_path")" = '0:0:600' ]
  done
  jq -e --arg release "$release" --arg created "$release_created" \
    --arg version "$release_version" --arg image_id "$image_id" '
      .schema_version == "noteai.native-release-evidence.v2" and
      .release_commit == $release and .created == $created and .version == $version and
      .runner_architecture == "x86_64" and (.roles | length) == 1 and
      .roles[0].role == "ai-worker" and .roles[0].target == "ai-worker-runtime" and
      .roles[0].image_id == $image_id and .roles[0].platform == "linux/amd64" and
      .roles[0].findings.critical == 4 and .roles[0].findings.high == 19 and
      .roles[0].findings.secrets == 0 and .roles[0].findings.browser_components == 0 and
      .roles[0].findings.cryptography_version == "50.0.0" and
      .roles[0].findings.cryptography_components == 1 and
      .roles[0].findings.forbidden_os_packages == 0 and
      .roles[0].passed == false and .passed == false
    ' "$evidence_root/summary.json" >/dev/null
  jq -e --arg image_id "$image_id" '
    .role == "ai-worker" and .target == "ai-worker-runtime" and
    .image_id == $image_id and .platform == "linux/amd64"
  ' "$evidence_root/ai-worker-summary.json" >/dev/null
  jq -e --arg image_id "$image_id" \
    'type == "array" and length == 1 and .[0].Id == $image_id' \
    "$evidence_root/ai-worker-inspect.json" >/dev/null
  jq -e --arg image_id "$image_id" '
    .["containerimage.digest"] == $image_id and
    .["containerimage.config.digest"] == $image_id
  ' "$evidence_root/ai-worker-build-metadata.json" >/dev/null
  jq -e --arg image_id "$image_id" '
    .[0].RepoDigests == [] and .[0].Config.User == "noteai" and
    .[0].Config.Entrypoint == ["/app/scripts/docker_entrypoint.sh"] and
    .[0].Config.Cmd == ["python","durable_ai_worker.py","--once"] and
    .[0].Config.Healthcheck.Test == ["NONE"] and
    .[0].Config.WorkingDir == "/app/model" and
    .[0].Config.Labels["org.opencontainers.image.revision"] == "cad5ce35664f617c6e19f90a6159285ddf975594" and
    .[0].Config.Labels["org.opencontainers.image.created"] == "2026-08-05T14:30:09Z" and
    .[0].Config.Labels["org.opencontainers.image.version"] == "git-cad5ce3-amd64-r1" and
    .[0].Config.Labels["org.opencontainers.image.source"] == "https://github.com/iamyusen1314/noteai" and
    .[0].Config.Labels["com.noteai.runtime.role"] == "ai-worker" and
    (.[0].Config.Env | map(select(. == "NOTEAI_RUNTIME_ROLE=ai-worker")) | length) == 1 and
    (.[0].Config.Env | map(select(. == "NOTEAI_DURABLE_AI_SUSPENDED=1")) | length) == 1
  ' "$evidence_root/ai-worker-inspect.json" >/dev/null
  jq -e '
    [.components[]? | select(.name == "cryptography")] as $crypto |
    ($crypto | length) == 1 and $crypto[0].version == "50.0.0"
  ' "$evidence_root/ai-worker-sbom.cdx.json" >/dev/null
  jq -e '[.Results[]?.Vulnerabilities[]? | select(.PkgName == "cryptography")] | length == 0' \
    "$evidence_root/ai-worker-vuln-high-critical.json" >/dev/null
  jq -e '[.Results[]?.Secrets[]?] | length == 0' \
    "$evidence_root/ai-worker-secret.json" >/dev/null
  sbom_sha="$(sha256sum "$evidence_root/ai-worker-sbom.cdx.json" | awk '{print $1}')"
  vuln_sha="$(sha256sum "$evidence_root/ai-worker-vuln-high-critical.json" | awk '{print $1}')"
  secret_sha="$(sha256sum "$evidence_root/ai-worker-secret.json" | awk '{print $1}')"
  jq -e --arg sbom "$sbom_sha" --arg vuln "$vuln_sha" --arg secret "$secret_sha" '
    .roles[0].sbom_sha256 == $sbom and
    .roles[0].vulnerability_report_sha256 == $vuln and
    .roles[0].secret_report_sha256 == $secret
  ' "$evidence_root/summary.json" >/dev/null
  jq -e --arg sbom "$sbom_sha" --arg vuln "$vuln_sha" --arg secret "$secret_sha" '
    .sbom_sha256 == $sbom and .vulnerability_report_sha256 == $vuln and
    .secret_report_sha256 == $secret
  ' "$evidence_root/ai-worker-summary.json" >/dev/null
  jq -e '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") |
    .digest == "sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045"' \
    "$evidence_root/python-base-index.json" >/dev/null
  jq -e '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") |
    .digest == "sha256:3d0f05455dea2c82e2f76e7e2543964c30f6b7d673fc1a83286736d44fe4c41c"' \
    "$evidence_root/node-base-index.json" >/dev/null
  actual_vulnerabilities="$(jq -r '.Results[]?.Vulnerabilities[]? |
    [.VulnerabilityID,.PkgName,.InstalledVersion,(.FixedVersion // ""),.Severity] | @tsv' \
    "$evidence_root/ai-worker-vuln-high-critical.json" | LC_ALL=C sort)"
  expected_vulnerabilities="$(LC_ALL=C sort <<'VULNERABILITIES'
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
VULNERABILITIES
)"
  [ "$expected_vulnerabilities" = "$actual_vulnerabilities" ]
}

offline_self_test() (
  set -euo pipefail
  local repo_root="$1" fixture projected
  fixture="$(mktemp -d "${TMPDIR:-/tmp}/noteai-durable-ai-cad5.XXXXXX")"
  trap 'rm -rf -- "$fixture"' EXIT
  [ "$(docker_auth_entry_count "$fixture/missing.json")" = '0' ]
  printf '{"auths":{},"credHelpers":{},"credsStore":""}\n' > "$fixture/empty.json"
  [ "$(docker_auth_entry_count "$fixture/empty.json")" = '0' ]
  printf 'pushed: digest: sha256:%064d size: 1\n' 1 > "$fixture/push.log"
  [ "$(extract_push_digest "$fixture/push.log")" = "sha256:$(printf '%064d' 1)" ]
  printf 'pushed: digest: sha256:%064d size: 1\n' 3 >> "$fixture/push.log"
  if extract_push_digest "$fixture/push.log" >/dev/null 2>&1; then exit 1; fi
  printf 'Digest: sha256:%064d\n' 2 > "$fixture/descriptor.txt"
  [ "$(extract_descriptor_digest "$fixture/descriptor.txt")" = "sha256:$(printf '%064d' 2)" ]
  printf 'Digest: sha256:%064d\n' 4 >> "$fixture/descriptor.txt"
  if extract_descriptor_digest "$fixture/descriptor.txt" >/dev/null 2>&1; then exit 1; fi
  projected="$fixture/native.sh"
  git -C "$repo_root" show \
    "$release:scripts/ci/native_release_evidence_v2.sh" > "$projected"
  [ "$(sha256sum "$projected" | awk '{print $1}')" = \
    '35f59b31cd7038160c23746909aea6e325251d914cb91b645f65cf8bc7d509a9' ]
  project_ai_worker_role "$projected"
  printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A_OFFLINE_SELF_TEST=PASS\n'
)

build_mode() (
  set -Eeuo pipefail
  local wheelhouse_sha256="$1" scanner_sha256="$2"
  local phase='preflight' image_id source_materialized expected_materialized
  local wheelhouse_root scanner_root real_docker trivy_db_sha trivy_metadata_sha
  local build_metadata_sha inspect_sha sbom_sha vuln_sha secret_sha summary_sha

  [[ "$wheelhouse_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$scanner_sha256" =~ ^[0-9a-f]{64}$ ]]
  case "$task_root" in /var/lib/noteai/durable-ai-cad5-stage-a) ;; *) exit 90 ;; esac
  [ "$(id -u)" = '0' ]
  [ "$(uname -s)" = 'Linux' ] && [ "$(uname -m)" = 'x86_64' ]
  for command_name in docker git jq sha256sum awk find stat ps ss cmp sort wc tar timeout; do
    command -v "$command_name" >/dev/null
  done
  [ "$(systemctl is-active docker)" = 'active' ]
  [ "$(docker context show)" = 'default' ]
  [ "$(docker context inspect default --format '{{.Endpoints.docker.Host}}')" = \
    'unix:///var/run/docker.sock' ]
  [ -S /var/run/docker.sock ]
  [ -d "$transfer_root" ] && [ ! -L "$transfer_root" ]
  [ "$(stat -c '%u:%g:%a' "$transfer_root")" = '0:0:700' ]
  for input_path in "$source_bundle_path" "$wheelhouse_archive_path" "$scanner_archive_path"; do
    [ -f "$input_path" ] && [ ! -L "$input_path" ]
    [ "$(stat -c '%u:%g:%a' "$input_path")" = '0:0:600' ]
  done
  [ "$(wc -c < "$source_bundle_path" | tr -d ' ')" = "$source_bundle_size" ]
  [ "$(sha256sum "$source_bundle_path" | awk '{print $1}')" = "$source_bundle_sha256" ]
  [ "$(sha256sum "$wheelhouse_archive_path" | awk '{print $1}')" = "$wheelhouse_sha256" ]
  [ "$(sha256sum "$scanner_archive_path" | awk '{print $1}')" = "$scanner_sha256" ]
  [ ! -e "$task_root" ] && [ ! -L "$task_root" ]
  ! docker image inspect "$local_image" >/dev/null 2>&1
  ! docker image inspect "$canonical_image" >/dev/null 2>&1
  [ "$(docker_auth_entry_count)" = '0' ]
  [ "$(docker ps -aq | wc -l | tr -d ' ')" = '0' ]
  [ "$(build_or_push_process_count)" = '0' ]
  [ "$(database_connection_count)" = '0' ]
  [ "$(df -Pm /var/lib/docker | awk 'NR==2 {print $4}')" -ge 20480 ]
  [ "$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)" -ge 8192 ]

  cleanup_build_failure() {
    local exit_code=$?
    trap - EXIT
    if [ "$exit_code" -ne 0 ]; then
      printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A=FAIL phase=%s exit=%s\n' "$phase" "$exit_code" >&2
      docker rm -f "$inspect_container" noteai-native-evidence-local-ai-worker >/dev/null 2>&1 || true
      docker image rm "$local_image" "$canonical_image" >/dev/null 2>&1 || true
      if [ -e "$task_root" ]; then rm -rf -- "$task_root"; fi
    fi
    exit "$exit_code"
  }
  trap cleanup_build_failure EXIT

  install -d -o root -g root -m 0700 "$task_root" "$task_root/inputs"
  phase='offline_input_extract'
  extract_verified_archive "$wheelhouse_archive_path" wheelhouse "$task_root/inputs"
  extract_verified_archive "$scanner_archive_path" scanner-bundle "$task_root/inputs"
  wheelhouse_root="$task_root/inputs/wheelhouse"
  scanner_root="$task_root/inputs/scanner-bundle"
  [ "$(find "$wheelhouse_root" -maxdepth 1 -type f -iname 'cryptography-50.0.0-*.whl' | wc -l | tr -d ' ')" = '1' ]
  [ -z "$(find "$wheelhouse_root" -maxdepth 1 -type f -iname 'cryptography-48.0.1-*' -print -quit)" ]
  [ -z "$(find "$wheelhouse_root" -maxdepth 1 -type f \( -iname '*macosx*' -o -iname '*win32*' -o -iname '*aarch64*' -o -iname '*arm64*' \) -print -quit)" ]
  [ -z "$(find "$wheelhouse_root" -mindepth 1 -maxdepth 1 -type f ! -name SHA256SUMS ! -name '*.whl' ! -name 'jieba-0.42.1.tar.gz' -print -quit)" ]
  [ -x "$scanner_root/bin/syft" ] || chmod 0500 "$scanner_root/bin/syft"
  [ -x "$scanner_root/bin/trivy" ] || chmod 0500 "$scanner_root/bin/trivy"
  [ "$(sha256sum "$scanner_root/bin/syft" | awk '{print $1}')" = \
    '6368bf376b578991192e2e94f5e276e6c70d313d6368ad8c249866f020a86cb0' ]
  [ "$(sha256sum "$scanner_root/bin/trivy" | awk '{print $1}')" = \
    '0e69edd134a3c338baa1a6806920773615d682b18cbc6a0cba2a3b658ef9b63e' ]
  [ "$(sha256sum "$scanner_root/base-index/python-base-index.json" | awk '{print $1}')" = \
    '2cbba3aeca891b77c06479ae266614557b6bfef925df37472d4c690b878c587d' ]
  [ "$(sha256sum "$scanner_root/base-index/node-base-index.json" | awk '{print $1}')" = \
    '8fc034c9f2bbccb406ceaef6802be9a8921c17bc2109feccfcc33b901a56c8bc' ]
  verify_trivy_metadata "$scanner_root/trivy-cache/db/metadata.json"
  trivy_db_sha="$(sha256sum "$scanner_root/trivy-cache/db/trivy.db" | awk '{print $1}')"
  trivy_metadata_sha="$(sha256sum "$scanner_root/trivy-cache/db/metadata.json" | awk '{print $1}')"

  phase='source_bundle_import'
  prepare_source_from_bundle "$source_root"
  phase='model_materialization'
  while IFS='|' read -r expected_sha expected_size relative_name; do
    [ -f "$source_repository/$relative_name" ] && [ ! -L "$source_repository/$relative_name" ]
    [ "$(stat -c '%s' "$source_repository/$relative_name")" = "$expected_size" ]
    [ "$(sha256sum "$source_repository/$relative_name" | awk '{print $1}')" = "$expected_sha" ]
    install -o root -g root -m 0644 "$source_repository/$relative_name" "$source_root/$relative_name"
  done <<'MODELS'
c708c76eef9e017e73bcb63794592baed100d2af73cc53dedbb471cb792cbde4|466815|model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb
5d6e5d5bab5bee321c486d96bb8670605138444ca56cd2589cbbd57c14d80f10|444681|model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb
1f3d0b12a6b32d89044480ab5f3add47076f6148d00ea87135fee2d5bfb7bb7b|454076|model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb
MODELS
  source_materialized="$task_root/materialized-paths.txt"
  expected_materialized="$task_root/expected-materialized-paths.txt"
  git -C "$source_root" status --porcelain=v1 --untracked-files=no | awk '{print $2}' | LC_ALL=C sort > "$source_materialized"
  printf '%s\n' \
    model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb \
    model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb \
    model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb \
    > "$expected_materialized"
  cmp "$source_materialized" "$expected_materialized"
  [ -z "$(git -C "$source_root" diff --cached --name-only)" ]
  [ -z "$(git -C "$source_root" ls-files --others --exclude-standard)" ]
  verify_model_artifacts "$source_root"
  [ "$(sha256sum "$source_root/Dockerfile" | awk '{print $1}')" = \
    'ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447' ]
  [ "$(sha256sum "$source_root/model/requirements-api.txt" | awk '{print $1}')" = \
    '7a6adb458c44521dae7aa9cfa7fc36ae0f5ff0603e810901d7ce6da2e3ae4f6a' ]
  [ "$(sha256sum "$source_root/model/requirements.txt" | awk '{print $1}')" = \
    '1ef4150536e98b8057069981b1aadb469ca12f0f30f188a291af2f31e238724a' ]
  [ "$(sha256sum "$source_root/scripts/docker_entrypoint.sh" | awk '{print $1}')" = \
    '71d04b071c2352cfe53ef951c9333b8e24fcd5dfa1dcd1389de09b80002c9093' ]

  phase='offline_build_projection'
  [ "$(grep -Fxc 'RUN pip install --no-cache-dir -r requirements-api.txt \' "$source_root/Dockerfile")" = '1' ]
  awk '
    $0 == "RUN pip install --no-cache-dir -r requirements-api.txt \\" {
      print "RUN --network=none --mount=type=bind,from=noteai_wheelhouse,target=/wheelhouse,ro \\"
      print "    pip install --no-cache-dir --no-index --find-links=/wheelhouse -r requirements-api.txt \\"
      next
    }
    {print}
  ' "$source_root/Dockerfile" > "$task_root/Dockerfile.wheelhouse"
  chmod 0600 "$task_root/Dockerfile.wheelhouse"
  [ "$(grep -Fxc 'RUN --network=none --mount=type=bind,from=noteai_wheelhouse,target=/wheelhouse,ro \' "$task_root/Dockerfile.wheelhouse")" = '1' ]
  [ "$(grep -Fxc '    pip install --no-cache-dir --no-index --find-links=/wheelhouse -r requirements-api.txt \' "$task_root/Dockerfile.wheelhouse")" = '1' ]

  install -d -m 0700 "$task_root/bin" "$task_root/docker-empty"
  printf '{}\n' > "$task_root/docker-empty/config.json"
  install -m 0500 "$scanner_root/bin/syft" "$task_root/bin/syft"
  real_docker="$(command -v docker)"
  cat > "$task_root/bin/docker" <<'DOCKER_WRAPPER'
#!/bin/bash
set -euo pipefail
if [ "$#" -eq 5 ] && [ "$1" = buildx ] && [ "$2" = imagetools ] && [ "$3" = inspect ] && [ "$5" = --raw ]; then
  case "$4" in
    python:3.11.15-slim-trixie@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93)
      exec cat "$NOTEAI_PYTHON_INDEX_FILE" ;;
    node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0)
      exec cat "$NOTEAI_NODE_INDEX_FILE" ;;
    *) exit 64 ;;
  esac
fi
if [ "$#" -ge 2 ] && [ "$1" = buildx ] && [ "$2" = build ]; then
  shift 2
  args=(buildx build --network=default --file "$NOTEAI_WHEELHOUSE_DOCKERFILE" --build-context "noteai_wheelhouse=$NOTEAI_WHEELHOUSE_ROOT")
  pull_count=0
  for arg in "$@"; do
    if [ "$arg" = --pull ]; then
      pull_count=$((pull_count + 1))
    else
      args+=("$arg")
    fi
  done
  [ "$pull_count" = 1 ]
  exec "$NOTEAI_REAL_DOCKER" "${args[@]}"
fi
exec "$NOTEAI_REAL_DOCKER" "$@"
DOCKER_WRAPPER
  chmod 0500 "$task_root/bin/docker"
  cat > "$task_root/bin/trivy" <<'TRIVY_WRAPPER'
#!/bin/bash
set -euo pipefail
[ "$#" -ge 1 ] && [ "$1" = image ]
shift
exec "$NOTEAI_TRIVY_REAL" image --cache-dir "$NOTEAI_TRIVY_CACHE" \
  --skip-db-update --skip-java-db-update --offline-scan "$@"
TRIVY_WRAPPER
  chmod 0500 "$task_root/bin/trivy"
  install -m 0500 "$source_root/scripts/ci/native_release_evidence_v2.sh" "$task_root/native-release-ai-worker.sh"
  project_ai_worker_role "$task_root/native-release-ai-worker.sh"

  phase='offline_ai_worker_build_scan'
  (
    cd "$source_root"
    timeout --foreground --signal=TERM --kill-after=30s 5400s env \
      PATH="$task_root/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
      DOCKER_CONFIG="$task_root/docker-empty" \
      NOTEAI_REAL_DOCKER="$real_docker" \
      NOTEAI_WHEELHOUSE_DOCKERFILE="$task_root/Dockerfile.wheelhouse" \
      NOTEAI_WHEELHOUSE_ROOT="$wheelhouse_root" \
      NOTEAI_PYTHON_INDEX_FILE="$scanner_root/base-index/python-base-index.json" \
      NOTEAI_NODE_INDEX_FILE="$scanner_root/base-index/node-base-index.json" \
      NOTEAI_TRIVY_REAL="$scanner_root/bin/trivy" \
      NOTEAI_TRIVY_CACHE="$scanner_root/trivy-cache" \
      RELEASE_COMMIT="$release" NOTEAI_OCI_SOURCE="$oci_source" \
      NOTEAI_OCI_VERSION="$release_version" NOTEAI_OCI_CREATED="$release_created" \
      NOTEAI_EVIDENCE_DIR="$evidence_root" \
      bash "$task_root/native-release-ai-worker.sh"
  ) 2>&1 | tee "$task_root/build-scan.log"

  phase='evidence_acceptance'
  normalize_stage_a_evidence_permissions
  image_id="$(docker image inspect "$canonical_image" --format '{{.Id}}')"
  [ -n "$image_id" ]
  verify_stage_a_evidence "$image_id"
  [ "$(docker image inspect "$canonical_image" --format '{{.Architecture}}/{{.Os}}')" = 'amd64/linux' ]
  [ "$(docker image inspect "$canonical_image" --format '{{.Config.User}}')" = 'noteai' ]
  [ "$(docker image inspect "$canonical_image" --format '{{json .Config.Entrypoint}}')" = '["/app/scripts/docker_entrypoint.sh"]' ]
  [ "$(docker image inspect "$canonical_image" --format '{{json .Config.Cmd}}')" = '["python","durable_ai_worker.py","--once"]' ]
  [ "$(docker image inspect "$canonical_image" --format '{{json .Config.Healthcheck.Test}}')" = '["NONE"]' ]
  [ "$(docker image inspect "$canonical_image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$release" ]
  [ "$(docker image inspect "$canonical_image" --format '{{index .Config.Labels "com.noteai.runtime.role"}}')" = 'ai-worker' ]
  docker create --name "$inspect_container" "$canonical_image" >/dev/null
  docker cp "$inspect_container:/etc/noteai-runtime-role" "$task_root/runtime-role"
  docker cp "$inspect_container:/etc/passwd" "$task_root/passwd"
  docker rm "$inspect_container" >/dev/null
  [ "$(tr -d '\r\n' < "$task_root/runtime-role")" = 'ai-worker' ]
  grep -Eq '^noteai:x:999:999:' "$task_root/passwd"
  docker tag "$canonical_image" "$local_image"
  [ "$(docker image inspect "$local_image" --format '{{.Id}}')" = "$image_id" ]
  verify_stage_a_evidence "$image_id"

  build_metadata_sha="$(sha256sum "$evidence_root/ai-worker-build-metadata.json" | awk '{print $1}')"
  inspect_sha="$(sha256sum "$evidence_root/ai-worker-inspect.json" | awk '{print $1}')"
  sbom_sha="$(sha256sum "$evidence_root/ai-worker-sbom.cdx.json" | awk '{print $1}')"
  vuln_sha="$(sha256sum "$evidence_root/ai-worker-vuln-high-critical.json" | awk '{print $1}')"
  secret_sha="$(sha256sum "$evidence_root/ai-worker-secret.json" | awk '{print $1}')"
  summary_sha="$(sha256sum "$evidence_root/summary.json" | awk '{print $1}')"

  phase='success_cleanup'
  rm -rf -- "$source_root" "$task_root/inputs" "$task_root/bin" \
    "$task_root/docker-empty" "$task_root/native-release-ai-worker.sh" \
    "$task_root/Dockerfile.wheelhouse" \
    "$task_root/materialized-paths.txt" "$task_root/expected-materialized-paths.txt" \
    "$task_root/runtime-role" "$task_root/passwd"
  [ "$(docker ps -aq | wc -l | tr -d ' ')" = '0' ]
  [ "$(build_or_push_process_count)" = '0' ]
  [ "$(database_connection_count)" = '0' ]
  [ "$(docker_auth_entry_count)" = '0' ]
  trap - EXIT
  printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A=BUILD_PASS release=%s tree=%s image_id=%s evidence_files=11 build_network=default pip_network=none pip_index=none scanner_mode=offline\n' \
    "$release" "$release_tree" "$image_id"
  printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A_INPUTS source_bundle_sha256=%s wheelhouse_sha256=%s scanner_bundle_sha256=%s trivy_db_sha256=%s trivy_metadata_sha256=%s\n' \
    "$source_bundle_sha256" "$wheelhouse_sha256" "$scanner_sha256" \
    "$trivy_db_sha" "$trivy_metadata_sha"
  printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A_HASHES build_metadata=%s inspect=%s sbom=%s vuln=%s secret=%s summary=%s\n' \
    "$build_metadata_sha" "$inspect_sha" "$sbom_sha" "$vuln_sha" "$secret_sha" "$summary_sha"
)

publish_mode() (
  set -Eeuo pipefail
  local registry_username="$1" phase='preflight' task_publish_root docker_config
  local push_log descriptor_log raw_manifest local_image_id push_digest manifest_digest
  local manifest_config_digest raw_manifest_sha registry_password='' extra_input=''
  local remote_digest_ref
  local remote_alias_created=0 task_root_owned=0 push_started=0
  local publication_state='not_started'
  task_publish_root='/var/lib/noteai/durable-ai-cad5-publish'
  docker_config="$task_publish_root/docker-config"
  push_log="$task_publish_root/push.log"
  descriptor_log="$task_publish_root/descriptor.txt"
  raw_manifest="$task_publish_root/manifest.json"
  [[ "$registry_username" =~ ^[[:alnum:]_.:@+-]{1,256}$ ]]

  cleanup_publish() {
    unset registry_password
    if [ "$task_root_owned" = 1 ] && [ -d "$docker_config" ]; then
      env DOCKER_CONFIG="$docker_config" docker logout "$registry_host" >/dev/null 2>&1 || true
    fi
    if [ "$remote_alias_created" = 1 ]; then
      docker image rm "$remote_image" >/dev/null 2>&1 || true
    fi
    if [ "$task_root_owned" = 1 ] && [ -e "$task_publish_root" ]; then
      rm -rf -- "$task_publish_root"
    fi
  }
  on_publish_exit() {
    local exit_code=$? cleanup_exit=0
    trap - EXIT
    cleanup_publish || cleanup_exit=$?
    if [ "$exit_code" -eq 0 ] && [ "$cleanup_exit" -ne 0 ]; then exit_code="$cleanup_exit"; fi
    if [ "$exit_code" -ne 0 ]; then
      printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A=PUBLISH_FAIL phase=%s push_started=%s publication_state=%s manual_retries=0 reconcile_control_plane_before_any_next_action=required no_rerun=1\n' \
        "$phase" "$push_started" "$publication_state" >&2
    fi
    exit "$exit_code"
  }
  trap on_publish_exit EXIT

  [ "$(id -u)" = '0' ] && [ "$(uname -s)" = 'Linux' ] && [ "$(uname -m)" = 'x86_64' ]
  for command_name in docker jq sha256sum awk find stat ps ss sort wc; do command -v "$command_name" >/dev/null; done
  docker buildx version >/dev/null
  [ "$(docker context show)" = 'default' ]
  [ "$(docker context inspect default --format '{{.Endpoints.docker.Host}}')" = 'unix:///var/run/docker.sock' ]
  [ -S /var/run/docker.sock ]
  [ ! -e "$task_publish_root" ] && [ ! -L "$task_publish_root" ]
  [ "$(docker_auth_entry_count)" = '0' ]
  [ "$(docker ps -aq | wc -l | tr -d ' ')" = '0' ]
  [ "$(build_or_push_process_count)" = '0' ]
  [ "$(database_connection_count)" = '0' ]
  ! docker image inspect "$remote_image" >/dev/null 2>&1
  local_image_id="$(docker image inspect "$local_image" --format '{{.Id}}')"
  [ "$(docker image inspect "$canonical_image" --format '{{.Id}}')" = "$local_image_id" ]
  verify_stage_a_evidence "$local_image_id"

  phase='credential_input'
  IFS= read -r registry_password || [ -n "$registry_password" ]
  [ -n "$registry_password" ] && [ "${#registry_password}" -le 8192 ]
  if IFS= read -r extra_input || [ -n "$extra_input" ]; then
    echo 'registry password input must contain exactly one line' >&2
    exit 65
  fi
  unset extra_input
  mkdir -m 0700 -- "$task_publish_root"
  task_root_owned=1
  install -d -m 0700 "$docker_config"
  phase='registry_login'
  printf '%s\n' "$registry_password" | env DOCKER_CONFIG="$docker_config" \
    docker login --username "$registry_username" --password-stdin "$registry_host" >/dev/null 2>&1
  unset registry_password
  chmod 0600 "$docker_config/config.json"
  [ "$(docker_auth_entry_count "$docker_config/config.json")" = '1' ]

  phase='single_push'
  docker tag "$local_image" "$remote_image"
  remote_alias_created=1
  [ "$(docker image inspect "$remote_image" --format '{{.Id}}')" = "$local_image_id" ]
  push_started=1
  publication_state='unknown'
  env DOCKER_CONFIG="$docker_config" docker push "$remote_image" 2>&1 | tee "$push_log"
  push_digest="$(extract_push_digest "$push_log")"
  remote_digest_ref="${registry_host}/${repository}@${push_digest}"

  phase='manifest_readback'
  env DOCKER_CONFIG="$docker_config" docker buildx imagetools inspect "$remote_digest_ref" > "$descriptor_log"
  manifest_digest="$(extract_descriptor_digest "$descriptor_log")"
  env DOCKER_CONFIG="$docker_config" docker buildx imagetools inspect "$remote_digest_ref" --raw > "$raw_manifest"
  manifest_config_digest="$(jq -er '.config.digest' "$raw_manifest")"
  jq -e --arg local_id "$local_image_id" '
    .schemaVersion == 2 and (.manifests | not) and .config.digest == $local_id and
    .config.size > 0 and (.layers | type == "array" and length > 0) and
    all(.layers[]; (.digest | test("^sha256:[0-9a-f]{64}$")) and (.size > 0))
  ' "$raw_manifest" >/dev/null
  [ "$push_digest" = "$manifest_digest" ]
  [ "$manifest_config_digest" = "$local_image_id" ]
  [ "$manifest_digest" != "$local_image_id" ]
  raw_manifest_sha="$(sha256sum "$raw_manifest" | awk '{print $1}')"
  publication_state='verified'

  phase='cleanup'
  cleanup_publish
  [ "$(docker_auth_entry_count)" = '0' ]
  [ "$(docker ps -aq | wc -l | tr -d ' ')" = '0' ]
  [ "$(build_or_push_process_count)" = '0' ]
  [ "$(database_connection_count)" = '0' ]
  trap - EXIT
  printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A=PUBLISH_PASS release=%s tag=%s pushes=1 manual_retries=0\n' "$release" "$tag"
  printf 'NOTEAI_DURABLE_AI_CAD5_STAGE_A_DIGESTS local_config=%s push=%s manifest=%s raw_manifest_sha256=%s manifest_config=%s\n' \
    "$local_image_id" "$push_digest" "$manifest_digest" "$raw_manifest_sha" "$manifest_config_digest"
)

case "${1:-}" in
  --offline-self-test)
    [ "$#" = 2 ]
    offline_self_test "$2"
    ;;
  build)
    [ "$#" = 3 ] || { echo 'usage: durable_ai_cad5_stage_a.sh build WHEELHOUSE_SHA256 SCANNER_BUNDLE_SHA256' >&2; exit 64; }
    build_mode "$2" "$3"
    ;;
  publish)
    [ "$#" = 2 ] || { echo 'usage: durable_ai_cad5_stage_a.sh publish REGISTRY_USERNAME' >&2; exit 64; }
    publish_mode "$2"
    ;;
  *)
    echo 'usage: durable_ai_cad5_stage_a.sh {build WHEELHOUSE_SHA256 SCANNER_BUNDLE_SHA256|publish REGISTRY_USERNAME|--offline-self-test REPO_ROOT}' >&2
    exit 64
    ;;
esac
