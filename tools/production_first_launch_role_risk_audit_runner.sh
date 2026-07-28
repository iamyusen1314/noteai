#!/usr/bin/env bash
set -u
set -o pipefail

task_root=/var/lib/noteai/first-launch-role-risk-audit
source_root="${task_root}/source"
result_path="${task_root}/result.json"
result_tmp="${result_path}.tmp"
error_path="${task_root}/error.log"
prepared_sentinel="${task_root}/runner.prepared"
dispatch_sentinel="${task_root}/dispatch.started"
api_env=/etc/noteai/api.env
container_name=noteai-first-launch-role-risk-audit-once
import_container_name=noteai-first-launch-role-risk-import-once
auditor_sha256=24f17fbe700c2c525e7f876606472f375ee7156b94c6fe1ae703c95d07b5582f

fail_preconnect() {
    printf '%s\n' \
        "SAFE_ROLE_RISK_RUN incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
}

fail_connected_unknown() {
    printf '%s\n' \
        "SAFE_ROLE_RISK_RUN incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown automatic_retry=0 ids_printed=0 secrets=0"
    exit 1
}

case "${task_root}" in
    /var/lib/noteai/first-launch-role-risk-audit) ;;
    *) fail_preconnect ;;
esac

test -f "${source_root}/package.sha256" || fail_preconnect
test -f \
    "${source_root}/tools/production_first_launch_role_risk_audit.py" \
    || fail_preconnect
observed_auditor_line="$(
    sha256sum \
        "${source_root}/tools/production_first_launch_role_risk_audit.py"
)" || fail_preconnect
observed_auditor_sha="${observed_auditor_line%% *}"
test "${observed_auditor_sha}" = "${auditor_sha256}" || fail_preconnect
(cd "${source_root}" && sha256sum -c package.sha256 >/dev/null 2>&1) \
    || fail_preconnect

test -f "${api_env}" || fail_preconnect
test ! -L "${api_env}" || fail_preconnect
api_env_meta="$(stat -c '%U:%G:%a' "${api_env}")" || fail_preconnect
test "${api_env_meta}" = "root:root:600" || fail_preconnect
database_url_count=0
database_url=
while IFS= read -r env_line || test -n "${env_line}"; do
    case "${env_line}" in
        DATABASE_URL=*)
            database_url_count=$((database_url_count + 1))
            database_url="${env_line#DATABASE_URL=}"
            ;;
    esac
done <"${api_env}"
test "${database_url_count}" = 1 || fail_preconnect
test -n "${database_url}" || fail_preconnect

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
existing_import_container="$(
    docker ps -a \
        --filter "name=^/${import_container_name}$" \
        --format '{{.ID}}'
)" || fail_preconnect
test -z "${existing_import_container}" || fail_preconnect
test ! -e "${dispatch_sentinel}" || fail_preconnect
test ! -e "${result_path}" || fail_preconnect
rm -f \
    "${result_tmp}" \
    "${error_path}" \
    "${prepared_sentinel}" \
    || fail_preconnect
printf 'prepared\n' >"${prepared_sentinel}" || fail_preconnect
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
    -v "${source_root}:/audit:ro" \
    -w /audit \
    --entrypoint python \
    "${image_id}" \
    -c 'import tools.production_first_launch_role_risk_audit; import tools.production_schema_roles' \
    >/dev/null 2>&1 \
    || fail_preconnect
printf 'dispatched\n' >"${dispatch_sentinel}" || fail_preconnect

set +e
printf '%s' "${database_url}" \
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
        -v "${source_root}:/audit:ro" \
        -w /audit \
        --entrypoint python \
        "${image_id}" \
        -c 'import sys; value=sys.stdin.read(); from tools.production_first_launch_role_risk_audit import main; code=main(database_url=value); del value; raise SystemExit(code)' \
        >"${result_tmp}" 2>"${error_path}"
pipeline_status=("${PIPESTATUS[@]}")
printf_exit="${pipeline_status[0]:-125}"
audit_exit="${pipeline_status[1]:-125}"
unset database_url env_line

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
    printf '%s\n' \
        "SAFE_ROLE_RISK_RUN incident_class=PRE_CONNECT printf_exit=${printf_exit} audit_exit=${audit_exit} database_connection=0 transaction=0 database_write=0 result_bytes=0 error_bytes=${error_bytes} container=0 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
fi

if test "${audit_exit}" = 2 \
    && grep -Fq \
        'production_first_launch_role_risk_audit=FAIL' \
        "${error_path}" \
    && grep -Fq 'incident_class=PRE_CONNECT' "${error_path}"; then
    rm -f "${result_tmp}" || true
    test "${container_count}" = 0 || fail_preconnect
    printf '%s\n' \
        "SAFE_ROLE_RISK_RUN incident_class=PRE_CONNECT printf_exit=${printf_exit} audit_exit=${audit_exit} database_connection=0 transaction=0 database_write=0 result_bytes=${result_bytes} error_bytes=${error_bytes} container=0 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
fi

if test "${printf_exit}" = 0 \
    && { test "${audit_exit}" = 0 || test "${audit_exit}" = 30; } \
    && test "${result_bytes}" -gt 0 \
    && grep -Eq \
        '"status":"(accepted_risk_observed|state_changed)"' \
        "${result_tmp}" \
    && grep -Fq '"incident_class":"CONNECTED_KNOWN"' "${result_tmp}"; then
    test "${container_count}" = 0 || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    printf '%s\n' \
        "SAFE_ROLE_RISK_RUN incident_class=CONNECTED_KNOWN printf_exit=${printf_exit} audit_exit=${audit_exit} database_connection=1 transaction=1 database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 automatic_retry=0 ids_printed=0 secrets=0"
    exit "${audit_exit}"
fi

fail_connected_unknown
