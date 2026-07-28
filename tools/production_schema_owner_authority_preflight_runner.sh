#!/usr/bin/env bash
set -u
set -o pipefail

mode="${1:-}"
task_root=/var/lib/noteai/schema-owner-authority-preflight-v1
source_root="${task_root}/source"
admin_env=/etc/noteai/admin.env
import_sentinel="${task_root}/import.passed"
result_path="${task_root}/result.json"
result_tmp="${result_path}.tmp"
error_path="${task_root}/error.log"
prepared_sentinel="${task_root}/audit.prepared"
dispatch_sentinel="${task_root}/audit.started"
container_name=noteai-schema-owner-authority-audit-once
import_container_name=noteai-schema-owner-authority-import-once
auditor_sha256=108333e143f0ae64ae173d81b518ce90cbf108a42afa819c91aa33da253bbf91

fail_preconnect() {
    printf '%s\n' \
        "SAFE_OWNER_AUTHORITY_PREFLIGHT mode=${mode} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
}

fail_connected_unknown() {
    cleanup_required=unknown
    case "${container_count:-unknown}" in
        0) cleanup_required=0 ;;
        unknown) ;;
        *) cleanup_required=1 ;;
    esac
    printf '%s\n' \
        "SAFE_OWNER_AUTHORITY_PREFLIGHT mode=${mode} incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown cleanup_required=${cleanup_required} automatic_retry=0 ids_printed=0 secrets=0"
    exit 1
}

fail_connected_known() {
    printf '%s\n' \
        "SAFE_OWNER_AUTHORITY_PREFLIGHT mode=${mode} incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=KNOWN_READ_ONLY_FAILURE audit_transaction=rolled_back database_write=0 cleanup_required=0 automatic_retry=0 ids_printed=0 secrets=0"
    exit 31
}

case "${mode}" in
    prepare | audit) ;;
    *) fail_preconnect ;;
esac
case "${task_root}" in
    /var/lib/noteai/schema-owner-authority-preflight-v1) ;;
    *) fail_preconnect ;;
esac

test -f "${source_root}/package.sha256" || fail_preconnect
test -f \
    "${source_root}/tools/production_schema_owner_authority_preflight.py" \
    || fail_preconnect
observed_auditor_line="$(
    sha256sum \
        "${source_root}/tools/production_schema_owner_authority_preflight.py"
)" || fail_preconnect
observed_auditor_sha="${observed_auditor_line%% *}"
test "${observed_auditor_sha}" = "${auditor_sha256}" || fail_preconnect
(cd "${source_root}" && sha256sum -c package.sha256 >/dev/null 2>&1) \
    || fail_preconnect
package_manifest_line="$(
    sha256sum "${source_root}/package.sha256"
)" || fail_preconnect
package_manifest_sha="${package_manifest_line%% *}"

api_container="$(
    docker ps \
        --filter label=com.noteai.runtime.role=api \
        --format '{{.ID}}'
)" || fail_preconnect
test -n "${api_container}" || fail_preconnect
case "${api_container}" in
    *$'\n'*) fail_preconnect ;;
esac
image_id="$(
    docker inspect --format '{{.Image}}' "${api_container}" 2>/dev/null
)" || fail_preconnect
test -n "${image_id}" || fail_preconnect
existing_container="$(
    docker ps -a \
        --filter "name=^/${container_name}$" \
        --format '{{.ID}}'
)" || fail_preconnect
test -z "${existing_container}" || fail_preconnect

if test "${mode}" = prepare; then
    existing_import_container="$(
        docker ps -a \
            --filter "name=^/${import_container_name}$" \
            --format '{{.ID}}'
    )" || fail_preconnect
    test -z "${existing_import_container}" || fail_preconnect
    test ! -e "${import_sentinel}" || fail_preconnect
    docker run \
        --rm \
        --pull never \
        --network none \
        --name "${import_container_name}" \
        --user 999:999 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -c 'import tools.production_schema_owner_authority_preflight' \
        >/dev/null 2>&1 \
        || fail_preconnect
    printf '%s\n' "${package_manifest_sha}" >"${import_sentinel}" \
        || fail_preconnect
    printf '%s\n' \
        "SAFE_OWNER_AUTHORITY_PREFLIGHT mode=prepare incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 import=passed automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

test -f "${import_sentinel}" || fail_preconnect
observed_import_sha="$(tr -d '\n' <"${import_sentinel}")" \
    || fail_preconnect
test "${observed_import_sha}" = "${package_manifest_sha}" \
    || fail_preconnect
test -f "${admin_env}" || fail_preconnect
test ! -L "${admin_env}" || fail_preconnect
admin_env_meta="$(stat -c '%U:%G:%a' "${admin_env}")" \
    || fail_preconnect
test "${admin_env_meta}" = "root:root:600" || fail_preconnect
database_url_count="$(
    awk 'index($0,"DATABASE_URL=")==1 { count += 1 } END { print count+0 }' \
        "${admin_env}"
)" || fail_preconnect
test "${database_url_count}" = 1 || fail_preconnect
database_url_bytes="$(
    awk 'index($0,"DATABASE_URL=")==1 { print substr($0,14) }' \
        "${admin_env}" \
        | wc -c \
        | tr -d ' '
)" || fail_preconnect
test "${database_url_bytes}" -gt 1 || fail_preconnect
test "${database_url_bytes}" -le 2049 || fail_preconnect
database_url_scheme_count="$(
    awk '
        index($0,"DATABASE_URL=")==1 {
            value=substr($0,14)
            if (value ~ /^postgres(ql)?:\/\//) count += 1
        }
        END { print count+0 }
    ' "${admin_env}"
)" || fail_preconnect
test "${database_url_scheme_count}" = 1 || fail_preconnect
test ! -e "${dispatch_sentinel}" || fail_preconnect
test ! -e "${result_path}" || fail_preconnect
rm -f "${result_tmp}" "${error_path}" "${prepared_sentinel}" \
    || fail_preconnect
printf 'prepared\n' >"${prepared_sentinel}" || fail_preconnect
printf 'dispatched\n' >"${dispatch_sentinel}" || fail_preconnect

set +e
awk 'index($0,"DATABASE_URL=")==1 { printf "%s", substr($0,14) }' \
        "${admin_env}" \
    | docker run \
        --rm \
        --pull never \
        --network host \
        --name "${container_name}" \
        --user 999:999 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 128 \
        --memory 256m \
        --cpus 0.5 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -i \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -c 'import sys; value=sys.stdin.read(); from tools.production_schema_owner_authority_preflight import main; code=main(database_url=value); del value; raise SystemExit(code)' \
        >"${result_tmp}" 2>"${error_path}"
pipeline_status=("${PIPESTATUS[@]}")

awk_exit="${pipeline_status[0]:-125}"
audit_exit="${pipeline_status[1]:-125}"
error_bytes="$(wc -c <"${error_path}" | tr -d ' ')" \
    || fail_connected_unknown
container_ids="$(
    docker ps -a \
        --filter "name=^/${container_name}$" \
        --format '{{.ID}}'
)" || fail_connected_unknown
container_count=0
test -z "${container_ids}" || container_count=1
result_bytes=0
if test -f "${result_tmp}"; then
    result_bytes="$(wc -c <"${result_tmp}" | tr -d ' ')" \
        || fail_connected_unknown
fi

if { test "${audit_exit}" = 126 || test "${audit_exit}" = 127; } \
    && test "${container_count}" = 0 \
    && test "${result_bytes}" = 0; then
    fail_preconnect
fi

if test "${audit_exit}" = 2 \
    && grep -Fq 'incident_class=PRE_CONNECT' "${error_path}" \
    && test "${container_count}" = 0; then
    rm -f "${result_tmp}" || true
    fail_preconnect
fi

if test "${awk_exit}" = 0 \
    && { test "${audit_exit}" = 0 || test "${audit_exit}" = 30; } \
    && test "${result_bytes}" -gt 0 \
    && grep -Eq \
        '"status":"(owner_authority_verified|state_changed)"' \
        "${result_tmp}" \
    && grep -Fq '"incident_class":"CONNECTED_KNOWN"' "${result_tmp}" \
    && grep -Fq '"fixed_query_count":3' "${result_tmp}" \
    && grep -Fq '"owner_activation_command_count":1' "${result_tmp}" \
    && grep -Fq '"transaction_rolled_back":true' "${result_tmp}" \
    && grep -Fq '"database_write_count":0' "${result_tmp}"; then
    test "${container_count}" = 0 || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    printf '%s\n' \
        "SAFE_OWNER_AUTHORITY_PREFLIGHT mode=audit incident_class=CONNECTED_KNOWN audit_exit=${audit_exit} database_connection=1 database_outcome=READ_ONLY_CLASSIFIED audit_transaction=rolled_back database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 automatic_retry=0 ids_printed=0 secrets=0"
    exit "${audit_exit}"
fi

if test "${audit_exit}" = 31 \
    && grep -Fq 'incident_class=CONNECTED_KNOWN' "${error_path}" \
    && test "${container_count}" = 0; then
    fail_connected_known
fi

fail_connected_unknown
